/*
 * Looper FX, the part in flash bank 2: the always-recording ring, the loop, the HPF, and the reading of the block's
 * messages and clock. Original 1010music Blackbox, firmware 3.1.9. The glue (the hooks, the latch) is looper.c.
 *
 * BANK 2 RULE: nothing in here calls anything outside this file (test_bank2.py), so no libgcc either: no 64-bit
 * division, no conversion between 64-bit integers and floats, no memset / memcpy (word loops), no doubles.
 * lp_block takes no firmware address at all, so host/ builds this same file and the suites hold the two builds
 * against each other. lp_gather reads the firmware's objects (the channel's message queue, the engine's clock, the
 * raw input, the recorder) and only runs on the unit, behind looper.c's b2_live() gate.
 *
 * THE RING is the FX A Repeater's own two ring buffers (384,000 floats each, allocated by stock at boot, X2), used as
 * 768,000 frames of planar int16: 16.0 s. It is written every block whether or not anything is looping, so a touch
 * can loop what has already played.
 *
 * TOUCH = loop in on the grid. The in-point is floor(t / L) * L for the length L picked on X, t the tick of the
 * block's first frame as the pads see it (duck_block's snapshot). The read head starts on the frame being written,
 * so the output stays the live signal until the first out-point; there it jumps back to the in-point with a 64-frame
 * crossfade, and does so on every pass. The pass lengths carry their fractions (lcur, acc), and while the transport
 * plays the loop is locked to the engine's grid: a pass that has drifted more than 2 ticks off it (a tempo change, a
 * clock that follows MIDI, a PLAY that restarts the count) is lengthened or shortened at its out-point to land on the
 * grid again. RELEASE = back to live over 256 frames, unless Hold is on.
 *
 * X = length, the in-point fixed, and the read head always at the grid's phase of that length: shorter jumps to the
 * same phase of the shorter loop, longer to where the longer loop is now (live, if its first pass is not over yet).
 * Each jump is crossfaded; a jump that lands on a crossfade still running is declicked (the step left by the cut is
 * faded out over 64 frames). Y = a 12 dB/oct high-pass (src/filter.c's SVF, copied: bank 2 cannot call bank 1),
 * 10 Hz .. 4 kHz; Y = 0 takes it out entirely.
 */
#include "looper.h"

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")

#define LP_FS     48000.0f
#define LP_PI     3.14159265f
#define LP_SMOOTH 0.33333f            /* per-block HPF smoothing, as filter.c */
#define LP_RES    1.0f                /* SVF damping: Q 1, a mild bump at the cutoff */

static inline int32_t lp_round(float x)
{
    return (int32_t)(x + (x >= 0.0f ? 0.5f : -0.5f));
}

static inline int32_t lp_wrap(int32_t i, int32_t cap)
{
    while (i < 0)
        i += cap;
    while (i >= cap)
        i -= cap;
    return i;
}

/* floored x mod m, m > 0 */
static inline uint32_t lp_mod(int32_t x, uint32_t m)
{
    int32_t r = x % (int32_t)m;
    return (uint32_t)(r < 0 ? r + (int32_t)m : r);
}

static inline int16_t lp_s16(float x)
{
    x *= LP_SCALE;
    x = x > 32767.0f ? 32767.0f : x < -32767.0f ? -32767.0f : x;
    return (int16_t)lp_round(x);
}

/* tan(x), 0 <= x < 1.45: Pade (3,2), as filter.c */
static inline float lp_tan(float x)
{
    float x2 = x * x;
    return x * (15.0f - x2) / (15.0f - 6.0f * x2);
}

/* 2^x, as master.c's exp2_fast */
static inline float lp_exp2(float x)
{
    int i = (int)x - (x < 0.0f);
    float f = x - (float)i, p = 1.0f + f * (0.6565f + f * 0.3435f);
    union {
        float f;
        uint32_t u;
    } v;
    v.u = (uint32_t)(i + 127) << 23;
    return v.f * p;
}

/* the pass count as npass keeps it: exact below 64, else 64 + (n mod 64). Every length divides 4 bars, which is at
   most 64 passes of 1/16, so n mod 64 is all a length change needs, and "64 or more" all the live test needs. */
static inline uint8_t lp_np(uint32_t c)
{
    return (uint8_t)(c >= 64u ? 64u + (c & 63u) : c);
}

/* the longest of `idx` and the shorter lengths that leaves the ring its margin at this tempo */
static int lp_cap_idx(int idx, float fpt, int32_t cap)
{
    while (idx < LP_LENS - 1 && (float)(LP_T16 << (LP_LENS - 1 - idx)) * fpt > (float)(cap - LP_CAP_MARGIN))
        idx++;
    return idx;
}

/* a new crossfade from ring index `from`, or from the live signal. One that cuts a running crossfade short also
   declicks: the frame loop fades out the step the cut leaves. */
static void lp_xstart(struct lp_dsp *d, int32_t from, int live)
{
    if (d->xf > 0)
        d->jolt = 1;
    d->old_idx = from;
    d->old_live = (uint8_t)live;
    d->xf = LP_XF;
}

/* ...from the read head as it is now */
static void lp_xfrom(struct lp_dsp *d, int32_t cap)
{
    lp_xstart(d, d->live ? d->w : lp_wrap(d->in_idx + d->phi, cap), d->live);
}

static void lp_engage(struct lp_dsp *d, const struct lp_in *in, int want_idx)
{
    int32_t cap = in->cap;
    float fpt = in->fpt;
    int idx = lp_cap_idx(want_idx, fpt, cap);
    uint32_t lt = LP_T16 << (LP_LENS - 1 - idx);
    float lf = (float)lt * fpt;
    if (d->frozen) {
        /* a held loop stopped the ring and this catch came before its release had faded out (a re-touch within 256
           frames): the ring writes again from here, and nothing in it is history any more */
        d->frozen = 0;
        d->valid = 0;
    }
    /* frames from the in-point to this block's first frame: the phase in the grid of this length, or with the
       transport stopped a whole length (the last L, looping at once) */
    float off = in->playing ? (float)(in->phase % lt) * fpt : lf;
    int32_t offi = lp_round(off);
    if (offi > d->valid) {
        /* the ring does not go back that far (just switched on, or after a frozen hold): move the in-point forward by
           whole loops, so the loop is always true history, if that means live until it comes round */
        float miss = (float)(offi - d->valid);
        int32_t k = (int32_t)(miss / lf);
        if ((float)k * lf < miss)
            k++;
        off -= (float)k * lf;
        offi = lp_round(off);
    }
    if (d->g > 0.0f) {                       /* caught again while fading out: cross over from where the old head is */
        lp_xfrom(d, cap);
    } else {
        d->xf = 0;
        d->rn = 0;
        d->jolt = 0;
        d->s1[0] = d->s1[1] = d->s2[0] = d->s2[1] = 0.0f;
        d->fm = 0.0f;
        d->ys = d->yt;
    }
    d->in_idx = lp_wrap(d->w - offi, cap);
    d->phi = offi;
    d->age = offi > 0 ? offi : 0;
    d->acc = (float)offi - off;
    d->lf = lf;
    d->lcur = lp_round(lf + d->acc);
    d->fpt = fpt;
    d->len_idx = (uint8_t)idx;
    d->npass = 0;
    d->anch = 0;                             /* lp_lock takes the in-point's tick in this same block */
    d->live = 1;
    d->engaged = 1;
    d->gt = 1.0f;
}

/* X while engaged: the in-point stays, and the read head goes where the new length's loop is on the grid now */
static void lp_length(struct lp_dsp *d, int32_t cap, int want_idx)
{
    d->last_len = (uint8_t)want_idx;
    int idx = lp_cap_idx(want_idx, d->fpt, cap), old = d->len_idx;
    if (idx == old)
        return;
    float lfo = d->lf, lf = (float)(LP_T16 << (LP_LENS - 1 - idx)) * d->fpt;
    float e = (float)d->phi - d->acc;        /* exact frames into this pass */
    uint32_t c = d->npass;
    if (idx > old) {                         /* shorter: the same phase, a whole number of the new passes further on */
        uint32_t m = 0;
        if (e >= lf) {
            m = (uint32_t)(e / lf);
            e -= (float)m * lf;
        }
        c = (c << (idx - old)) + m;
    } else {                                 /* longer: which of its shorter passes this one is, from the count */
        uint32_t s = (uint32_t)(old - idx);
        e += (float)(c & ((1u << s) - 1u)) * lfo;
        c = c >= 64u ? 64u + ((c & 63u) >> s) : c >> s;
    }
    c = lp_np(c);
    if (e < 0.0f && c > 0) {                 /* the grid lock has this pass end a little late: the last one, still */
        e += lf;
        c = c == 64u ? 127u : c - 1u;
    }
    if (e >= lf) {
        e -= lf;
        c = lp_np(c + 1u);
    }
    d->npass = (uint8_t)c;
    d->len_idx = (uint8_t)idx;
    d->lf = lf;
    if (c == 0) {                            /* the new length's first pass is not over: the read head is live */
        if (!d->live) {
            lp_xfrom(d, cap);
            d->phi = lp_wrap(d->w - d->in_idx, cap);
            d->live = 1;
        }
    } else {
        int32_t p = lp_round(e);
        if (d->live || p != d->phi) {
            lp_xfrom(d, cap);
            d->live = 0;
            d->phi = p;
        }
    }
    d->acc = (float)d->phi - e;
    d->lcur = lp_round(lf + d->acc);
    if (d->lcur > cap - LP_CAP_MARGIN) {     /* a pass the lock had run on, now longer than the ring keeps: cut it */
        d->lcur = cap - LP_CAP_MARGIN;
        d->acc = (float)d->lcur - lf;
    }
}

/* The grid lock, once a block while engaged and the transport plays. The in-point's tick is taken once (after the
   catch, and again after a PLAY / STOP) as the grid line nearest to where this pass began, less the passes already
   played. From then on, every block, the frames left in this pass are held against the frames left to the grid's
   next line of this length. Within LP_LOCK_TOL ticks they are left alone (the tick is rounded, so a loop on time
   reads up to a tick either way); beyond, this pass's out-point moves to the grid's line. That also holds after a
   tempo change, when a pass at the catch's tempo is no longer as long as the grid's: each pass is then cut or run on
   to the grid's length. The read head does not move: the next seam takes it there. */
static void lp_lock(struct lp_dsp *d, const struct lp_in *in)
{
    uint32_t lt = LP_T16 << (LP_LENS - 1 - d->len_idx);
    float fpt = in->fpt;
    if (!d->anch) {
        float e = (float)d->phi - d->acc;
        int32_t s = (int32_t)in->phase - lp_round(e / fpt);            /* the tick this pass began on */
        int32_t k = lp_round((float)s / (float)lt);                    /* the nearest grid line of this length */
        uint32_t back = (uint32_t)d->npass & (LP_BAR4 / lt - 1u);       /* passes before it, within 4 bars */
        d->in_tick = lp_mod(k * (int32_t)lt - (int32_t)(back * lt), LP_BAR4);
        d->anch = 1;
    }
    float lg = (float)lt * fpt;              /* this length on the grid, at the tempo now */
    float left = (float)(lt - lp_mod((int32_t)in->phase - (int32_t)d->in_tick, LP_BAR4) % lt) * fpt;
    float lcx = d->lf + d->acc;              /* this pass's out-point, exactly (lcur is it rounded) */
    float diff = lcx - (float)d->phi - left; /* > 0: this pass would end after the grid's line */
    diff -= (float)lp_round(diff / lg) * lg;
    float tol = LP_LOCK_TOL * fpt;
    if ((diff <= tol && diff >= -tol) || diff > 0.5f * d->lf || diff < -0.5f * d->lf || d->phi < 0)
        return;                              /* on time; the tempo under half or over twice the catch's; or the in-point
                                                still ahead (moved forward at the catch): its frame is not written yet */
    lcx -= diff;
    int32_t lc = lp_round(lcx);
    if (lc < 1 || lc > in->cap - LP_CAP_MARGIN)
        return;                              /* an out-point before the in-point, or a pass longer than the ring keeps */
    d->acc = lcx - d->lf;                    /* the wrap then leaves acc = lcx - lc, the fraction it carries */
    d->lcur = lc;
}

void lp_block(struct lp_dsp *d, const struct lp_in *in, float *l, float *r, int n)
{
    int32_t cap = in->cap;
    if (d->init != LP_DSP_MAGIC) {
        uint32_t obj = d->obj;
        for (unsigned i = 0; i < sizeof *d / 4; i++)
            ((volatile uint32_t *)d)[i] = 0;
        d->obj = obj;
        d->last_len = 2;                     /* 1 bar */
        d->px = d->py = -1;
        d->init = LP_DSP_MAGIC;
    }
    if (d->w >= cap || d->w < 0)
        d->w = 0;

    /* ---- the messages. The XY view posts "rest" values for X and Y that are not the finger's: right after a Hold
       toggle, and right before a finger-up that leaves Hold off. Those are skipped, also when this block cut the UI
       task off between a Hold toggle and its rest posts (they then lead the next drain: hskip). */
    int ne = in->nev > LP_EVENTS ? LP_EVENTS : in->nev;
    uint8_t skip[LP_EVENTS];
    int h = d->hold, after_hold = 0, carry = d->hskip, rest = 0;
    int down = 0, got = 0;                   /* a touch-down is the last touch event here; its X (1) / Y (2) came */
    for (int i = 0; i < ne; i++) {
        unsigned id = in->ev[i].id;
        int v = in->ev[i].v;
        skip[i] = 0;
        if (id == P_LP_FINGER || id == P_LP_HOLD || id == LP_EV_RESET) {
            carry = rest = after_hold = 0;
            if (id == P_LP_FINGER) {
                if (!v && !h)
                    skip[i] = 2;             /* a release the view announced with rest posts */
                down = v != 0;
                got = 0;
            } else if (id == P_LP_HOLD) {
                h = v != 0;
                after_hold = 1;
                rest = 3;                    /* its rest posts, X then Y, are to follow */
            } else {
                h = 0;
            }
        } else {
            int bit = id == P_LP_LEN ? 1 : 2;
            got |= bit;
            rest &= ~bit;
            if (after_hold) {
                skip[i] = 1;
            } else if ((carry & bit) && v == (bit == 1 ? LP_REST_X : LP_REST_Y)) {
                skip[i] = 1;                 /* the last drain's Hold toggle's rest post, a drain late */
                carry &= ~bit;
            }
        }
    }
    d->hskip = (uint8_t)rest;
    int before_rel = 0;
    for (int i = ne - 1; i >= 0; i--) {
        unsigned id = in->ev[i].id;
        if (id == P_LP_FINGER || id == P_LP_HOLD || id == LP_EV_RESET)
            before_rel = skip[i] == 2;
        else if (before_rel)
            skip[i] = 1;
    }
    int nx = -1, ny = -1;
    for (int i = 0; i < ne; i++) {
        unsigned id = in->ev[i].id;
        int v = in->ev[i].v;
        if (id == P_LP_FINGER) {
            d->finger = v != 0;
        } else if (id == P_LP_HOLD) {
            d->hold = v != 0;
        } else if (id == LP_EV_RESET) {
            d->finger = d->hold = 0;
        } else if (skip[i] != 1) {
            if (id == P_LP_LEN)
                nx = v < 0 ? 0 : v > LP_LENS - 1 ? LP_LENS - 1 : v;
            else if (id == P_LP_HPF)
                ny = v < 0 ? 0 : v > 1000 ? 1000 : v;
        }
    }

    /* ---- the policy */
    if (d->finger || d->hold) {
        if (!d->engaged) {
            if (!d->pend) {                  /* a new catch: X / Y of this drain, else the last length and no HPF */
                if (nx >= 0)
                    d->last_len = (uint8_t)nx;
                d->yt = ny >= 0 ? (float)ny * 0.001f : 0.0f;
            } else {                         /* deferred from the last block: anything newer wins */
                if (nx >= 0)
                    d->last_len = (uint8_t)nx;
                if (ny >= 0)
                    d->yt = (float)ny * 0.001f;
            }
            d->px = d->py = -1;
            /* wait one block when the clock snapshot is stale (a PLAY / STOP block), or when a touch-down came
               without the X and Y the view always posts right behind it: they are still on their way */
            if (in->edge || (down && got != 3 && !d->pend)) {
                d->pend = 1;
            } else {
                d->pend = 0;
                lp_engage(d, in, d->last_len);
            }
        } else {                             /* re-touch or move: last block's X / Y now, this block's next time */
            if (d->px >= 0)
                lp_length(d, cap, d->px);
            if (d->py >= 0)
                d->yt = (float)d->py * 0.001f;
            d->px = (int16_t)nx;
            d->py = (int16_t)ny;
        }
    } else {
        d->pend = 0;
        d->px = d->py = -1;
        if (d->engaged) {
            d->engaged = 0;
            d->gt = 0.0f;
        }
    }

    /* ---- the grid lock (the clock only moves while the transport plays) */
    if (in->edge || !in->playing)
        d->anch = 0;
    else if (d->engaged)
        lp_lock(d, in);

    /* ---- the HPF coefficients, once a block */
    d->ys += LP_SMOOTH * (d->yt - d->ys);
    float gh = lp_tan(LP_PI * 10.0f * lp_exp2(d->ys * 8.643856f) / LP_FS);
    float hh = 1.0f / (1.0f + LP_RES * gh + gh * gh), rg = LP_RES + gh;

    /* ---- the frames */
    const float *sl = in->sl, *sr = in->sr;
    float gl = in->gl, gr = in->gr;
    int16_t *rl = in->rl, *rr = in->rr;
    int loop_in = in->src, ontop = in->src && !in->mon;
    int32_t w = d->w;
    for (int i = 0; i < n; i++) {
        float al = sl ? sl[i] * gl : 0.0f, ar = sr ? sr[i] * gr : 0.0f;
        if (!d->frozen) {
            rl[w] = lp_s16(al);
            rr[w] = lp_s16(ar);
            if (d->valid < cap)
                d->valid++;
        }
        if (d->engaged || d->g > 0.0f) {
            if (d->phi >= d->lcur) {          /* the out-point: back to the in-point, the continuation fading out */
                lp_xstart(d, d->live ? w : lp_wrap(d->in_idx + d->phi, cap), d->live);
                d->live = 0;
                d->phi -= d->lcur;
                d->acc += d->lf - (float)d->lcur;
                d->lcur = lp_round(d->lf + d->acc);
                d->npass = lp_np((uint32_t)d->npass + 1u);
            }
            /* the live signal as the loop stands in for it: the source, or nothing when Loop In plays on top */
            float vl = ontop ? 0.0f : al, vr = ontop ? 0.0f : ar;
            float xl, xr;
            if (d->live) {
                xl = vl;
                xr = vr;
            } else {
                int32_t k = lp_wrap(d->in_idx + d->phi, cap);
                xl = (float)rl[k] * (1.0f / LP_SCALE);
                xr = (float)rr[k] * (1.0f / LP_SCALE);
            }
            if (d->xf > 0) {
                float t = (float)d->xf * (1.0f / LP_XF), ol = vl, orr = vr;
                if (!d->old_live) {
                    ol = (float)rl[d->old_idx] * (1.0f / LP_SCALE);
                    orr = (float)rr[d->old_idx] * (1.0f / LP_SCALE);
                }
                xl += (ol - xl) * t;
                xr += (orr - xr) * t;
                if (++d->old_idx >= cap)
                    d->old_idx = 0;
                d->xf--;
            }
            if (d->jolt) {                    /* the crossfade that was running is gone: fade out the step it leaves */
                d->rs[0] = d->zp[0] - xl;
                d->rs[1] = d->zp[1] - xr;
                d->rn = LP_XF;
                d->jolt = 0;
            }
            if (d->rn > 0) {
                float t = (float)d->rn * (1.0f / LP_XF);
                xl += d->rs[0] * t;
                xr += d->rs[1] * t;
                d->rn--;
            }
            d->zp[0] = xl;
            d->zp[1] = xr;
            d->phi++;
            if (d->phi > 0 && d->age < cap)
                d->age++;
            if (!d->frozen && d->age >= cap - LP_FREEZE) {
                d->frozen = 1;               /* a held loop is never written over: the ring stops instead */
                d->valid = 0;
            }

            if (d->yt > 0.0f || d->fm > 0.0f) {
                float x[2] = {xl, xr};
                for (int c = 0; c < 2; c++) {
                    float hp = (x[c] - rg * d->s1[c] - d->s2[c]) * hh;
                    float bp = gh * hp + d->s1[c];
                    d->s1[c] = gh * hp + bp;
                    float lp = gh * bp + d->s2[c];
                    d->s2[c] = gh * bp + lp;
                    x[c] += d->fm * (hp - x[c]);
                }
                xl = x[0];
                xr = x[1];
                d->fm += d->yt > 0.0f ? LP_FM_STEP : -LP_FM_STEP;
                if (d->fm >= 1.0f) {
                    d->fm = 1.0f;
                } else if (d->fm <= 0.0f) {
                    d->fm = 0.0f;
                    d->s1[0] = d->s1[1] = d->s2[0] = d->s2[1] = 0.0f;
                }
            }

            float dl = l[i], dr = r[i], g = d->g;
            if (loop_in) {                   /* Loop In: in place of the monitored input, else on top */
                l[i] = dl + g * (xl - vl);
                r[i] = dr + g * (xr - vr);
            } else {                         /* Looper: in place of Out 1 */
                l[i] = dl + g * (xl - dl);
                r[i] = dr + g * (xr - dr);
            }
            if (g < d->gt) {
                g += LP_RAMP;
                d->g = g > d->gt ? d->gt : g;
            } else if (g > d->gt) {
                g -= LP_RAMP;
                if (g <= 0.0f) {             /* faded out: live again, and the ring runs on */
                    g = 0.0f;
                    d->frozen = 0;
                    d->xf = 0;
                    d->rn = 0;
                    d->jolt = 0;
                    d->phi = 0;
                    d->live = 0;
                }
                d->g = g;
            }
        }
        if (++w >= cap)
            w = 0;
        d->w = w;
    }
    /* a filter that blew up starts again */
    for (int c = 0; c < 2; c++)
        if (!(d->s1[c] > -1e4f && d->s1[c] < 1e4f && d->s2[c] > -1e4f && d->s2[c] < 1e4f))
            d->s1[c] = d->s2[c] = 0.0f;
}

/* ---- firmware side: what the block is, read from stock's objects. Device memory (D-013) is read with aligned
   volatile loads only. */

#define LP_REC_VT 0x080d07acu        /* the WAV recorder (root[4] of the engine's main chain) */
#define LP_AUDIO  0x2400a9c0u        /* the audio object: +0x8fb0 / +0x8fb4 point at this block's raw input, L / R */

static inline int lp_ram(uintptr_t a)
{
    return !(a & 3u) && a >= 0x24000000u && a < 0x24080000u;
}

static inline int lp_sdram(uintptr_t a, uint32_t bytes)
{
    return !(a & 3u) && a >= 0xc0000000u && a < 0xc4000000u && bytes <= 0xc4000000u - a;
}

static inline int lp_chans(uintptr_t a, int n)
{
    uintptr_t end = a + 4u * (uint32_t)n;
    return !(a & 3u) && ((a >= 0x20000000u && end <= 0x20020000u) || (a >= 0x24000000u && end <= 0x24080000u)
                         || (a >= 0xc0000000u && end <= 0xc4000000u));
}

#define U8(a)  (*(const volatile uint8_t *)(a))
#define U16(a) (*(const volatile uint16_t *)(a))
#define U32(a) (*(const volatile uint32_t *)(a))

/* floored t mod LP_BAR4 for an i64 t, in 32-bit operations (2^32 mod 15360 = 4096) */
static uint32_t lp_phase(uint32_t lo, int32_t hi)
{
    uint64_t t = (uint64_t)(uint32_t)hi << 32 | lo;
    int neg = hi < 0;
    if (neg)
        t = (uint64_t)0 - t;
    uint32_t rr = ((uint32_t)(t >> 32) % LP_BAR4 * 4096u + (uint32_t)t % LP_BAR4) % LP_BAR4;
    return neg && rr ? LP_BAR4 - rr : rr;
}

static int lp_gather(struct lp_in *in, const struct lp_bank *b, uintptr_t fx, uintptr_t ctx, uintptr_t q, float *l,
                     float *r, int n)
{
    for (unsigned i = 0; i < sizeof *in / 4; i++)
        ((volatile uint32_t *)in)[i] = 0;
    /* the ring: this Repeater's two ring buffers */
    uint32_t floats = U32(fx + 0x38);
    uintptr_t rl = U32(fx + 0x3c), rr = U32(fx + 0x40);
    if (floats < 0x8000u || floats > 384000u || !lp_sdram(rl, floats * 4u) || !lp_sdram(rr, floats * 4u))
        return 0;
    in->rl = (int16_t *)rl;
    in->rr = (int16_t *)rr;
    in->cap = (int32_t)(floats * 2u);
    /* the clock: the engine (ctx[0]) after this block's advance, and duck_block's snapshot from before it */
    uintptr_t eng = U32(ctx);
    if (!lp_ram(eng))
        return 0;
    float bpm = *(const volatile float *)(eng + 0x18);
    bpm = bpm >= 20.0f && bpm <= 400.0f ? bpm : bpm > 400.0f ? 400.0f : bpm >= 0.0f ? 20.0f : 120.0f;
    in->fpt = 3000.0f / bpm;
    in->playing = U8(eng + 0x38) != 0;
    in->edge = b->snap_play != in->playing || b->snap_sample + (uint32_t)n != U32(eng);
    in->phase = lp_phase(b->snap_tick_lo, b->snap_tick_hi);
    /* the source */
    if (b->mode != LP_MODE_IN) {
        in->sl = l;
        in->sr = r;
        in->gl = in->gr = 1.0f;
    } else {
        /* Loop In: the audio input as the recorder takes it (Rec Input, the jacks, Rec Gain), read raw, so that it is
           the input whatever the recorder has done to input bus 0 by now: scaled it in place while it listens, or
           (Rec Input Resam) put last block's Out 1 there */
        in->src = 1;
        unsigned rin = 0, j1 = 1, j2 = 1;
        float gain = 1.0f;
        uintptr_t rec = U32(eng + 0xfc00);
        for (int k = 0; k < 4 && lp_ram(rec); k++)
            rec = U32(rec + 8);
        if (lp_ram(rec) && U32(rec) == LP_REC_VT) {
            rin = U8(rec + 0x58);            /* Rec Input: L+R, Left, Right, Resam */
            unsigned rmon = U8(rec + 0x59);  /* Rec Mon: On, Auto, Off */
            j1 = U8(rec + 0x280) != 0;       /* the jacks: AUDIO, or GATE / CV / CLK (silenced) */
            j2 = U8(rec + 0x281) != 0;
            float gv = *(const volatile float *)(rec + 0x64);   /* Rec Gain, linear */
            if (rin != 3 && gv >= 0.0f && gv <= 16.0f)
                gain = gv;
            int listen = rmon == 0 || (rmon == 1 && (U8(rec + 0x5a) || U8(rec + 0x48)));
            int jacks = rin == 0 ? j1 && j2 : rin == 1 ? j1 : rin == 2 ? j2 : 0;
            in->mon = listen && jacks && U32(rec + 0x68) == 0;   /* Mon Output Out1 */
        }
        uintptr_t il = U32(LP_AUDIO + 0x8fb0), ir = U32(LP_AUDIO + 0x8fb4);   /* 0x200 bytes each: 128 frames */
        if (n > 128 || !lp_chans(il, n) || !lp_chans(ir, n)) {
            /* not where A6 found it: input bus 0, as insert.c reads it - raw unless the recorder listens (scaled
               already) or resamples (Out 1: then Loop In stays silent) */
            il = ir = 0;
            gain = 1.0f;
            uintptr_t bus = ctx + 0x1583cu;
            int bn = (int)U32(bus + 4);
            if (!bn)
                bn = (int)U32(bus);
            uintptr_t bl = U32(bus + 8), br = U8(bus + 0x11) ? U32(bus + 12) : bl;
            if (rin != 3 && !U8(bus + 0x10) && bn >= n && bn <= 1024 && lp_chans(bl, n) && lp_chans(br, n)) {
                il = bl;
                ir = br;
            }
        }
        if (il) {
            in->sl = (const float *)(rin == 2 ? ir : il);
            in->sr = (const float *)(rin == 1 ? il : ir);
            in->gl = (rin == 2 ? j2 : j1) ? gain : 0.0f;
            in->gr = (rin == 1 ? j1 : j2) ? gain : 0.0f;
        }
    }
    /* the messages on FX A's channel, in order. Within a run of X / Y posts (between two touch / Hold / reset
       events) only the last X and the last Y count, so a run keeps one of each: posts piled up by a stall can never
       push a release out of the 32 slots. */
    uint32_t cnt = U32(q + 0x600);
    if (cnt > 64)
        cnt = 64;
    int run = 0;
    for (uint32_t i = 0; i < cnt; i++) {
        uintptr_t m = q + i * 0x18u;
        unsigned type = U8(m), id = U16(m + 0xc);
        int32_t v = (int32_t)U32(m + 0x10);
        if (type == 0x40) {
            id = LP_EV_RESET;
            v = 0;
        } else if (type != 0x39 || (id != P_LP_FINGER && id != P_LP_HOLD && id != P_LP_LEN && id != P_LP_HPF)) {
            continue;
        }
        int16_t sv = (int16_t)(v < -32768 ? -32768 : v > 32767 ? 32767 : v);
        if (id == P_LP_LEN || id == P_LP_HPF) {
            int j = in->nev - 1;
            while (j >= run && in->ev[j].id != id)
                j--;
            if (j >= run) {
                in->ev[j].v = sv;
                continue;
            }
            if (in->nev >= LP_EVENTS)
                continue;
        } else {
            if (in->nev >= LP_EVENTS)
                in->nev = LP_EVENTS - 1;     /* more than ten touches in one block: the newest takes the last slot */
            run = in->nev + 1;
        }
        in->ev[in->nev].id = (uint16_t)id;
        in->ev[in->nev].v = sv;
        in->nev++;
    }
    return 1;
}

/* looper.c's process wrapper, every block in Looper / Loop In mode, once b2_live() has said yes */
void lp_run(struct lp_bank *b, uint8_t *fx, uint8_t *ctx, const uint8_t *q, float *l, float *r, int n)
{
    struct lp_in in;
    if (b->dsp.obj != (uint32_t)(uintptr_t)fx)
        b->dsp.init = 0;                     /* the other Repeater instance: its buffers hold no history of ours */
    b->dsp.obj = (uint32_t)(uintptr_t)fx;
    if (lp_gather(&in, b, (uintptr_t)fx, (uintptr_t)ctx, (uintptr_t)q, l, r, n))
        lp_block(&b->dsp, &in, l, r, n);
}
