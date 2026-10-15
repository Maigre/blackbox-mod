/* Looper FX (FX A types Looper / Loop In): what looper.c (firmware glue, bank 1) and looper_dsp.c (the ring, the
   loop and the HPF, bank 2; also built for the host) share. Every field is 4-byte or smaller and lp_dsp holds no
   pointer, so the state has one layout on the unit and on a 64-bit host. */
#ifndef LOOPER_H
#define LOOPER_H
#include <stdint.h>

#define LP_MAGIC      0x3152504cu    /* "LPR1": lp_bank, bumped with its layout */
#define LP_DSP_MAGIC  0x3150534cu    /* "LSP1": lp_dsp is set up; 0 = start it over (the latch, or another object) */
#define LP_OFFSET     (0x56800u + 0x2d900u)   /* in master.c's boot block: behind Prism's 0x56800 and the extras */
#define LP_BYTES      0x200u

#define LP_MODE_LOOPER 3             /* FX A index: Looper (source Out 1 at the DJ FX point) */
#define LP_MODE_IN     4             /* FX A index: Loop In (source the audio input) */

#define P_LP_FINGER   0x15           /* stock, unregistered: the XY pad's touch, 1 / 0 */
#define P_LP_HOLD     0x1a           /* stock, unregistered: FX A's Hold button */
#define P_LP_HPF      0x30           /* stock "HPF:" (EchoHP's), 0..1000: the Y axis */
#define P_LP_LEN      0x1cc          /* ours, "Length:": the X axis, 0 = 4 bars .. 6 = 1/16 */
#define LP_EV_RESET   0xffffu        /* an engine message of type 0x40 on the channel: release, Hold off */

#define LP_LENS       7              /* 4 bars, 2 bars, 1 bar, 1/2, 1/4, 1/8, 1/16 (stock's Clip Quant names) */
#define LP_T16        240u           /* ticks of the shortest, 1/16; length idx is 240 << (6 - idx) ticks */
#define LP_BAR4       15360u         /* ticks of the longest: every length divides it */
#define LP_SCALE      8192.0f        /* int16 ring: 12 dB of headroom over full scale */
#define LP_XF         64             /* frames of crossfade at every wrap and jump */
#define LP_RAMP       (1.0f / 256.0f) /* engage / release gain step per frame (stock's engage length) */
#define LP_FM_STEP    (1.0f / 128.0f) /* HPF in / out per frame */
#define LP_CAP_MARGIN 1024           /* a length must leave this much of the ring free */
#define LP_FREEZE     512            /* ...and writing stops this far before a held in-point would be overwritten */
#define LP_EVENTS     32
#define LP_REST_X     3              /* the XY view's rest values (FUN_080B1CE8): X = the middle band of 7, ... */
#define LP_REST_Y     500            /* ...Y = the middle of 0..1000 */
#define LP_LOCK_TOL   2.0f           /* ticks: the grid lock corrects a pass once it is further off than this */

struct lp_ev {
    uint16_t id;
    int16_t v;
};

/* lp_block's own state: pure data */
struct lp_dsp {
    uint32_t init;                   /* LP_DSP_MAGIC */
    uint32_t obj;                    /* the Repeater whose two ring buffers hold the ring */
    int32_t w;                       /* ring index of the next frame written */
    int32_t valid;                   /* frames of unbroken history ending at w (0 while frozen) */
    uint8_t engaged, finger, hold, live;      /* live: the read head is on the frame being written (first pass) */
    uint8_t len_idx, last_len, frozen, pend;  /* len_idx as capped; last_len as asked for; pend: engage next block */
    int16_t px, py;                  /* X / Y of the last block, applied one block late (-1 = none) */
    int32_t in_idx;                  /* ring index of the in-point */
    int32_t phi;                     /* frames into this pass (< 0: the in-point is still ahead) */
    int32_t lcur;                    /* this pass's length in frames */
    int32_t age;                     /* frames since the in-point, saturating */
    float lf, acc, fpt;              /* length in frames; exact frames into the pass = phi - acc; frames per tick */
    float g, gt;                     /* loop gain and its target */
    int32_t old_idx, xf;             /* crossfade: the read head going out, and frames left */
    float yt, ys, fm;                /* HPF: target 0..1, smoothed, bypass <-> filter mix */
    float s1[2], s2[2];              /* HPF integrators */
    uint8_t npass;                   /* passes of this length since the in-point: exact below 64, else 64 + (n mod 64) */
    uint8_t anch;                    /* in_tick holds: the loop is locked to the engine's grid (playing) */
    uint8_t old_live;                /* the crossfade's outgoing head is the live signal, not the ring */
    uint8_t hskip;                   /* a Hold toggle's rest posts are still to come (next drain): 1 = X, 2 = Y */
    uint32_t in_tick;                /* the in-point's tick, mod LP_BAR4 */
    int32_t rn;                      /* declick: frames left */
    float rs[2];                     /* declick: the step being faded out */
    float zp[2];                     /* the loop signal's last frame (before the HPF) */
    uint8_t jolt, _r[3];             /* a new crossfade cut a running one short: declick from this frame */
};

/* the block, as lp_gather (bank 2, firmware only) or a host test hands it to lp_block */
struct lp_in {
    const float *sl, *sr;            /* the source; 0 = silence */
    int16_t *rl, *rr;                /* the ring, planar int16 */
    int32_t cap;                     /* ring frames */
    uint32_t phase;                  /* the block's first tick mod LP_BAR4, floored */
    float fpt;                       /* frames per tick: 3000 / BPM */
    float gl, gr;                    /* the source's gain per channel: 1 for Out 1; Loop In: Rec Gain, 0 for a jack
                                        that is not AUDIO */
    uint8_t playing, edge, src, mon; /* edge: a transport change in this block; src 1 = Loop In; mon: the input is
                                        already in Out 1 (monitored) */
    uint8_t nev, _r[3];
    struct lp_ev ev[LP_EVENTS];      /* 0x15, 0x1a, 0x1cc, 0x30 and resets, in queue order */
};

/* bank 1 writes the head, bank 2 owns dsp */
struct lp_bank {
    uint32_t magic;
    uint8_t mode, _r[3];             /* FX A's index, latched in the slot setter: 0..4 */
    uint32_t sub;                    /* FX A's sub-slot (its +0x20 is the current effect) */
    uint32_t snap_sample;            /* duck_block: engine +0x00, low word: the block's first frame */
    uint32_t snap_tick_lo;           /* duck_block: engine +0x30, i64 ticks (960 a beat), as the pads see them */
    int32_t snap_tick_hi;
    uint8_t snap_play, _r2[3];       /* duck_block: engine +0x38 */
    struct lp_dsp dsp;
};
_Static_assert(sizeof(struct lp_bank) <= LP_BYTES, "master.c gives the Looper 0x200 bytes");

void lp_block(struct lp_dsp *d, const struct lp_in *in, float *l, float *r, int n);
void lp_run(struct lp_bank *b, uint8_t *fx, uint8_t *ctx, const uint8_t *q, float *l, float *r, int n);

#endif
