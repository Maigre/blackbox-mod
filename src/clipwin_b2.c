/*
 * Clip Window, the part in flash bank 2: the maths and the policy of every Clip Window hook (clipwin.c,
 * notes/re/README.md sections 2, 3). Original 1010music Blackbox, firmware 3.1.9.
 *
 * Leaf code: it reads and writes the pad, its segments, the knob, the waveform widget and the bank it is handed, and
 * calls nothing outside this file (bank 2 is written once and lives through every bank 1 install, so a branch out of it
 * would go stale: test_bank2.py). It came here to give bank 1's cave its room back (D-017, then D-018, Thomas on
 * 2026-10-16: "move everything (that can be moved) to bbextra then so we give back room now"): first Loop Len's window
 * and take, then everything else that is maths or policy. clipwin.c keeps the hooks, every stock call (the settings
 * lookup, the source's length and prefetch, the readers, the param-set, the recompute, the knob's ring, stepper and
 * text) and the bank's set-up, and calls in here only when b2_live() says the payload up there is this build's.
 * Without it every hook is a straight pass to stock: Slip, Region and Loop Len do nothing, the Slip row shows stock's
 * plain number and the waveform no bracket.
 */
#include <stdint.h>

#include "clipwin.h"

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")   /* no memset / memcpy calls out of the bank */

#define REGION_FILE 1                /* Region's list: Auto, File, Loop */
#define REGION_LOOP 2
#define CW_NO_WINDOW ((int32_t)0x80000000)

static int32_t fold2(int32_t v, int32_t len)
{
    v %= len;
    return v < 0 ? v + len : v;
}

/* 0 .. 15 for one of the sixteen pads, -1 for anything else (the 17th class-B object, cell 0x401, would alias pad 1) */
int cw_pad(const uint8_t *pad)
{
    uint32_t id = *(const uint32_t *)(pad + PAD_ID);
    uint32_t row = (id >> 8) & 0xff, col = id & 0xff;
    if ((id >> 16) || row > 3 || col > 3)
        return -1;
    return (int)(row * 4 + col);
}

/* ---- Region ---- */

/* The rule: 1 when the Region setting plays the loop [ls, le) of a file of len frames. The region is [Loop Start,
   Loop End), Loop End taken as stock keeps it (D-003; stock's own default is the length). A WAV's smpl loop comes in
   with its dwEnd as Loop End, verbatim (x3 t6), and dwEnd is the loop's last frame: such a region is one frame short,
   which nothing hears. The whole file is File: [0, len) and [0, len - 1] alike (a load leaves Loop End = the length
   with Loop Mode as it was; a whole-file smpl loop ends on len - 1), for Loop too. Auto also wants Loop Mode on. The
   engine (adopt) and the Waveform screen's bracket (cw_bracket) both ask it. */
static __attribute__((noinline)) int is_loop(int mode, int32_t ls, int32_t le, int on, int32_t len)
{
    return !(mode == REGION_FILE || len >= SRC_BAD || ls < 0 || ls >= le || le > len || (!ls && le >= len - 1) ||
             (mode != REGION_LOOP && !on));
}

/* The region pad q plays from now: its Region setting over the loop points. From the cell's class-H object, which
   stores them in queue order with everything else the pad hears; from the app's store (set, which clipwin.c read)
   when that link does not hold, keeping the last pair that made sense there (the app writes Loop Start and Loop End
   one at a time). */
static void adopt(struct cw_bank *b, unsigned q, const uint8_t *pad, int32_t len, const int32_t *set)
{
    const uint8_t *h = *(uint8_t *const *)(pad + PAD_SIBLING);
    int32_t ls, le, on;
    if (h && h[PAD_CLASS] == H_CLASS && *(const uint32_t *)(h + PAD_ID) == *(const uint32_t *)(pad + PAD_ID)) {
        ls = *(const int32_t *)(h + H_LOOP_START);
        le = *(const int32_t *)(h + H_LOOP_END);
        on = *(const int32_t *)(h + H_LOOP_MODE);
    } else {
        ls = set[CW_SET_START];
        le = set[CW_SET_END];
        on = set[CW_SET_MODE];
        if (ls >= 0 && ls < le && le <= len) {
            b->good[q][0] = ls;
            b->good[q][1] = le;
        } else {
            ls = b->good[q][0];
            le = b->good[q][1];
        }
    }
    b->region[q].vlen = 0;
    if (!is_loop(set[CW_SET_REGION], ls, le, on, len))
        return;
    b->region[q].rs = ls;
    b->region[q].vlen = le - ls;
}

/* not a Clip pad playing its steps: not in Clip mode, a Slicer pad, or Sync Slice with markers (slices are file frames,
   timed from the file's tempo, and start in H1') */
static __attribute__((noinline)) int sliced(const uint8_t *pad)
{
    return !pad[PAD_ON] || pad[PAD_SLICER] ||
           (*(const uint32_t *)(pad + PAD_SYNC) == SYNC_SLICE && *(const uint32_t *)(pad + PAD_SLICES));
}

/* the region pad q plays, if it applies to this pad as it is now: its length (0 = the whole file), *rs its start.
   Not where sliced(). H1 and H3 both ask. */
static __attribute__((noinline)) int32_t region_of(const struct cw_bank *b, unsigned q, const uint8_t *pad, int32_t len,
                                                   int32_t *rs)
{
    int32_t s = b->region[q].rs, v = b->region[q].vlen;
    if (v <= 0 || len >= SRC_BAD || s > len - v || sliced(pad))
        return 0;
    *rs = s;
    return v;
}

/* H3 (clipwin_len): the clip's length stock is told at site 0 .. 3, len = fw_src_len's. At site 1 (the recompute's
   first length) the pad takes its region when it is at its wrap (clipwin_wrap) or stopped: set = the four rows of its
   store (CW_SET_*), read only for that site. */
int32_t cw_len(struct cw_bank *b, unsigned q, uint8_t *pad, int site, int32_t clip, int32_t len, const int32_t *set)
{
    int32_t rs;
    if (site == 1 && (b->wrap == q + 1 || !(pad[LAYER0] | pad[LAYER0 + LAYER_SIZE])))
        adopt(b, q, pad, len, set);
    int32_t v = region_of(b, q, pad, len, &rs);
    if (!v)
        return len;
    /* seamless: no end on the last step (end = 1 - 1 = 0), so it crossfades into the next pass like any other step;
       H1 latches it with the region, so what it plays past the end is the region's start. Not for a one-shot. */
    if (site == 2 && pad[PAD_LOOP] && pad[PAD_LAUNCH] != 1)
        return 1;
    /* A synced clip of one step (Sync >= the clip): stock times that step by the length (+0x204 = the region in output
       samples), not by the clip, so the seamless step would run past the next pass (doubling) or stop short of it (a
       gap), as stock does with a file that long. Time it by the clip, as stock times every step when there are two or
       more. Only a step with no end reads +0x204 (an end re-derives the countdown): a one-shot is unchanged. A clip of
       0 ticks (Beat Count Auto of a region under half a beat) has no grid: the step keeps the region's length, so the
       region loops on its own length, as with Sync None. */
    if (site == 3 && pad[PAD_SYNCED] && *(const uint32_t *)(pad + PAD_STEPS) == 1 && clip > 0)
        *(float *)(pad + PAD_STEP_OUT) = (float)clip;
    return v;
}

/* H3' (clipwin_wrap), after the recompute at a wrap: was = the region before it, t = the tick the new pass starts on
   (0 for the unsynced wrap). 1 when the new region must wait (it is put back here, and the pad recomputed again): it
   moves the wrap grid off this pass, where stock would snap the pass's end into the past and double. A tick past 2^32
   takes it at once, as stock would. */
int cw_hold(struct cw_bank *b, unsigned q, const uint8_t *pad, const uint32_t *t, const struct cw_region *was)
{
    uint32_t grid = *(const uint32_t *)(pad + PAD_WRAP_GRID);
    struct cw_region *r = &b->region[q];
    if (!t || t[1] || !grid || *(const uint32_t *)(pad + PAD_WRAP_GRID + 4) || !(t[0] % grid) ||
        (r->rs == was->rs && r->vlen == was->vlen))
        return 0;
    r->rs = was->rs;                 /* the pass plays the region it had; a layer is active, so no recompute adopts */
    r->vlen = was->vlen;
    return 1;
}

/* ---- Loop Len ---- */

/* Loop Len's window for the segment H1 makes in slot k (cw_latch, when Loop Len is taken), clip = ticks per step x
   steps (0 without a clip): what to add to the frame stock starts it on so that it plays the window's step that lines
   up with its own, w = (origin + ((j x tps - origin) mod W)) / tps, played as stock plays a step: its first frame is
   stock's float product (int)((float)w x fps), truncated (a tick-domain formula is a frame off on a non-integer fps,
   notes/re/a2). CW_NO_WINDOW for none: Off, a window of the whole clip or more, or one the steps or the in-point do
   not divide (the poll forces the Sync for those, cw_looplen). */
__attribute__((noinline)) int32_t cw_window(const struct cw_bank *b, unsigned q, const uint8_t *pad, unsigned k,
                                            int32_t clip)
{
    unsigned ll = b->ll[q];
    int32_t tps = *(const int32_t *)(pad + PAD_TPS), o = b->origin[q];
    int32_t W = ll ? 240 << (ll - 1) : 0;
    if (!W || W >= clip || W % tps || o % tps)
        return CW_NO_WINDOW;
    const uint8_t *seg = pad + SEG0 + k * SEG_SIZE;
    uint32_t w = (uint32_t)(o + fold2((int32_t)*(const uint32_t *)(seg + SEG_STEP) * tps - o, W)) / (uint32_t)tps;
    return (int32_t)((float)w * *(const float *)(pad + PAD_FPS)) - (int32_t)*(const int64_t *)(seg + SEG_POS);
}

/* Loop Len on pad q, from cw_tick: ll = the row (0 Off, else W = 240 << (ll - 1) ticks), sync = the user's Sync (the
   app's store). The pad may have its Sync forced when Quant and Sync are not None (without a Quant there is no grid, on
   Sync None no clock phase, and stock's None-to-synced re-grid doubles a step, notes/re/a1) and it is not sliced.
   Returns 0 while a launch waits for its Quant point: a Sync change re-grids it, and it would sound at once
   (notes/re/a2, droplaunch); the poll comes back in 16 blocks. Else bit 0 = the value moved (the pending steps must
   be made again), bit 1 = msg holds the class-B param-set's {0x39, cell, 0x94, idx} for the Sync to send the pad
   (clipwin.c sends it: the param-set is stock's, in bank 1). */
__attribute__((noinline)) int cw_looplen(struct cw_bank *b, unsigned q, const uint8_t *pad, unsigned ll, uint32_t sync,
                                         uint32_t *msg)
{
    int live = 0, send = 0, force = pad[PAD_SYNCED] && !sliced(pad);
    for (unsigned k = 0; k < 4; k++) {
        const uint8_t *seg = pad + SEG0 + k * SEG_SIZE;
        if (seg[0] && !seg[1]) {
            if (seg[SEG_FIRST])
                return 0;
            live = 1;
        }
    }
    /* a stopped pad: its next launch takes the window from where it starts, the clip's start, as the first launch
       after power-on does - an in-point does not outlive the playing it was taken from */
    if (!live)
        b->origin[q] = 0;
    int32_t tps = *(const int32_t *)(pad + PAD_TPS);
    int32_t clip = tps * *(const int32_t *)(pad + PAD_STEPS);
    int moved = ll != b->ll[q];
    if (moved) {
        if (!b->ll[q]) {
            /* engaged: where the music is. The sounding segment that started last (the least elapsed since its step's
               first frame, signed: at rate != 1 stock's re-grid puts the step ahead of the position, notes/re/a1)
               gives the phase from the frame it plays: its latch's, Slip taken out, when it has one (it may still
               play an earlier window, after Off), else stock's position; in ticks, x tps / fps. The window is the W
               around it, on the grid. */
            int32_t least = 0x7fffffff;
            uint32_t ph = 0;
            float fps = *(const float *)(pad + PAD_FPS);
            for (unsigned k = 0; k < 4 && tps > 0 && fps > 0.0f; k++) {
                const uint8_t *seg = pad + SEG0 + k * SEG_SIZE;
                int32_t pos = (int32_t)*(const int64_t *)(seg + SEG_POS);
                int32_t e = pos - (int32_t)((float)*(const uint32_t *)(seg + SEG_STEP) * fps);
                if (seg[0] && !seg[1] && *(const int32_t *)(seg + SEG_DELAY) <= 0 && e < least) {
                    least = e;
                    if (b->valid[q] & (1u << k)) {
                        const struct cw_latch *l = &b->latch[q][k];
                        pos = fold2(fold2(pos, l->vlen) + l->delta - b->sf[q][k], l->vlen);
                    }
                    ph = (uint32_t)((float)pos * (float)tps / fps);
                }
            }
            uint32_t W = 240u << (ll - 1);
            b->origin[q] = (int32_t)(ph - ph % W);
        }
        b->ll[q] = (uint8_t)ll;
        if (!ll && b->forced[q]) {
            b->forced[q] = 0;            /* Off: the user's Sync back */
            if (sync <= 6)
                send = (int)sync + 1;
        }
    }
    /* a window the steps do not divide: force the largest Sync (1 bar .. 1/16, idx 1 .. 5) that divides it, its
       in-point and the clip, starting from the user's (the store's), which wins when it divides them: then a forced
       Sync is given back as soon as it no longer needs to be (a longer window). Sent when the pad's differs: again if
       something moved it (the app re-sending Sync). */
    int32_t W = ll ? 240 << (ll - 1) : 0, o = b->origin[q];
    if (W && W < clip && (W % tps || o % tps || b->forced[q]) && force) {
        uint32_t idx = sync - 1 < 5 ? sync : 1;
        int32_t t = 3840 >> (idx - 1);
        while (t > 240 && (W % t || o % t || clip % t)) {
            t >>= 1;
            idx++;
        }
        if (*(const int32_t *)(pad + PAD_SYNC) != t) {
            send = (int)idx + 1;
            b->forced[q] = idx != sync;
        }
    }
    if (send) {
        msg[0] = 0x39;
        msg[1] = 0;
        msg[2] = *(const uint32_t *)(pad + PAD_ID);
        msg[3] = P_SYNC;
        msg[4] = (uint32_t)send - 1;
        msg[5] = 0;
    }
    return (send ? 2 : 0) | moved;
}

/* ---- Slip, the segments ---- */

/* H1 (clipwin_seg_start): slot k of pad q has just been made, from the pad's steps, at stock's prefetch point pos =
   max(0, start - 8); pos < 0 = the poll latching a launch that waits for its Quant point again (cw_drop), from its own
   start. len = fw_src_len's. Latches the slot's shift (Slip, and Loop Len's window) and its region (or the whole file)
   and returns where to prefetch: where it will really read, or pos when it plays as stock. */
int32_t cw_latch(struct cw_bank *b, unsigned q, unsigned k, uint8_t *pad, int32_t len, int32_t pos)
{
    if (k > 3)
        return pos;
    const uint8_t *seg = pad + SEG0 + k * SEG_SIZE;
    int32_t start = (int32_t)*(const int64_t *)(seg + SEG_POS);
    if (pos < 0)
        pos = start > 8 ? start - 8 : 0;
    b->pad[q] = pad;
    b->valid[q] &= (uint8_t)~(1u << k);
    b->hinted[q] &= (uint8_t)~(1u << k);
    b->h1[q] |= (uint8_t)(1u << k);
    int32_t slip = b->slip[q], rs = 0;
    /* the region this pass plays (H3 gave the recompute its length), or the whole file */
    int32_t vlen = region_of(b, q, pad, len, &rs);
    /* ticks per step: an i64 whose value stays far below 2^31 (a whole clip is at most 512 beats x 960) */
    int32_t tps = *(const int32_t *)(pad + PAD_TPS), tps_hi = *(const int32_t *)(pad + PAD_TPS + 4);
    uint32_t steps = *(const uint32_t *)(pad + PAD_STEPS);
    int32_t clip = tps > 0 && !tps_hi && steps && steps < 0x10000 ? tps * (int32_t)steps : 0;
    /* Loop Len: the window's step for this one */
    int32_t wd = b->ll[q] ? cw_window(b, q, pad, k, clip) : CW_NO_WINDOW;
    int loop = wd != CW_NO_WINDOW;
    /* Slip needs a clip to turn ticks into frames; a region does not: Beat Count Auto makes a region under half a
       beat a clip of 0 ticks, and its segments must still read the region, not the file's first frames. */
    if (!clip)
        slip = 0;
    if (!vlen) {
        if ((!slip && !loop) || !pad[PAD_ON] || pad[PAD_SLICER] || len <= 0 || len >= SRC_BAD)
            return pos;
        vlen = len;
    }
    /* slip_f = floor(slip x vlen / clip) mod vlen, clip = ticks per step x steps (not Beat Count x 960: the two differ
       when the steps do not divide the clip); 0 without a clip. Double precision is the M7's own; no 64-bit division
       here (no libgcc). */
    int32_t f = 0;
    if (slip) {
        double x = (double)slip * (double)vlen / (double)clip;
        f = (int32_t)x;
        if ((double)f > x)
            f--;
    }
    b->sf[q][k] = f;
    if (loop)
        f += wd;
    f = fold2(f, vlen);
    struct cw_latch *l = &b->latch[q][k];
    l->rs = rs;
    l->vlen = vlen;
    l->delta = f;
    l->len = len;                    /* the FILE's length, not the region's: what H2 checks a load against */
    b->valid[q] |= (uint8_t)(1u << k);
    int32_t real = rs + fold2(fold2(start, vlen) + f, vlen) - 8;
    return real < 0 ? 0 : real;
}

/* H1' (clipwin_slice_start): a slice-marker segment takes slot k: whatever was latched there no longer applies */
void cw_slice(struct cw_bank *b, unsigned q, unsigned k)
{
    if (k < 4) {
        b->valid[q] &= (uint8_t)~(1u << k);
        b->h1[q] &= (uint8_t)~(1u << k);
    }
}

/* clipwin_tick, pad q: slip and ll as its store has them, sync its Sync (read only when Loop Len is set or taken),
   engine = the clock (0: no Loop Len). Bit 0 = the pad's pending segments must be made again (cw_drop), bit 1 = send
   msg to the pad (Loop Len's Sync). The row reads + = AHEAD, like a CDJ jog (Thomas, D-016): clockwise pushes the loop
   ahead of the beat (it plays from further into the file), counter-clockwise drags it behind. That is the content's
   shift as this file keeps it. */
int cw_tick(struct cw_bank *b, unsigned q, int32_t slip, unsigned ll, uint32_t sync, const void *engine, uint32_t *msg)
{
    slip = slip < -SLIP_MAX ? -SLIP_MAX : slip > SLIP_MAX ? SLIP_MAX : slip;
    if (ll > LOOPLEN_MAX)
        ll = 0;
    int moved = slip != b->slip[q];
    b->slip[q] = slip;
    const uint8_t *pad = b->pad[q];
    /* Loop Len waits for a pad H1 has seen (it is taken from what the pad plays) */
    if (!pad || pad[PAD_CLASS] != 0x4c || cw_pad(pad) != (int)q)
        return 0;
    if (engine && (ll | b->ll[q]))
        moved |= cw_looplen(b, q, pad, ll, sync, msg);
    return moved;
}

/* The guarded drop, after a change (cw_tick's bit 0, and after the Sync was sent): a segment made but not started yet
   is marked done, so stock makes it again in this render and H1 latches the new Slip. Never one with the first-block
   flag: that is a launch waiting for its Quant point, and dropping it makes it sound at once, off the bar (notes/re/a2,
   droplaunch). The sounding segment keeps its latch: the change is heard at the next step, through stock's crossfade.
   Returns the slots of the launches waiting for their Quant point that H1 made: they have read nothing yet, so
   clipwin_tick latches them again in place (cw_latch with pos -1); a slice segment (H1') in the slot keeps it. */
unsigned cw_drop(const struct cw_bank *b, unsigned q, uint8_t *pad)
{
    unsigned again = 0;
    for (unsigned k = 0; k < 4; k++) {
        uint8_t *seg = pad + SEG0 + k * SEG_SIZE;
        if (!seg[0] || seg[1] || *(const int32_t *)(seg + SEG_DELAY) <= 0)
            continue;
        if (!seg[SEG_FIRST])
            seg[1] = 1;
        else if (b->h1[q] & (1u << k))
            again |= 1u << k;
    }
    return again;
}

/* H2 (clipwin_read): the latch of the segment whose reader fraction is at frac (pad + 0x30 + k x 0x70 + 0x1c), or 0
   when it is not one of the four slots or no latch holds there */
const struct cw_latch *cw_slot(const struct cw_bank *b, unsigned q, const uint8_t *pad, const float *frac)
{
    uint32_t off = (uint32_t)((const uint8_t *)frac - pad) - (SEG0 + SEG_FRAC);
    unsigned k = off / SEG_SIZE;
    return off % SEG_SIZE || k > 3 || !(b->valid[q] & (1u << k)) ? 0 : &b->latch[q][k];
}

/* ...and with that latch l holding for the file the pad has: *real = where segment position pos really reads (rs +
   ((pos mod vlen) + delta) mod vlen). 1 when rs must be hinted now: the segment's content crosses the region end
   mid-segment, where stock never hints, so it is hinted once, as soon as the seam is inside the hint's sure reach
   (notes/re/a2: 3 blocks of 8192 frames from the hinted one). */
int cw_map(struct cw_bank *b, unsigned q, const struct cw_latch *l, int32_t pos, int32_t *real)
{
    unsigned k = (unsigned)(l - b->latch[q]);
    int32_t rs = l->rs, vlen = l->vlen;
    int32_t at = rs + fold2(fold2(pos, vlen) + l->delta, vlen);
    *real = at;
    if (rs + vlen - at <= 16384 && !(b->hinted[q] & (1u << k))) {
        b->hinted[q] |= (uint8_t)(1u << k);
        return 1;
    }
    return 0;
}

/* ---- the Slip knob ---- */

/* clipwin_turn, the type-1 turn of the Slip knob (Thomas, after Gate 2: "tricky, especially to set back to 0"; v2 after
   37.2.0d: "blocking at 0 is not great ... accelerator is too fast it seems"), by the stock accelerator's speed m
   (fw_ring_speed: 1 .. 6, about 8/7 x the counts per ms over the last 8 events):
     slow     m < KNOB_MEDIUM: single ticks, 40 counts a tick, twice that rate at speed 2 (the stepper's own
              accumulator does the rest);
     medium   m < KNOB_FAST: one KNOB_STEP_MEDIUM (10 ticks, a 1/384 note) a turn event, onto its own grid;
     fast     m >= KNOB_FAST: one SLIP_GRID (60 ticks, a 1/64 note) a turn event, onto the 1/64 grid: round values are
              easy to hit. KNOB_STEP_MEDIUM divides SLIP_GRID, so the first fast step from a medium value is on it;
     zero     a detent, not a wall: a move that reaches or crosses 0 stops on it, and the same turn going on stays
              there until ZERO_DETENT_MS after it ARRIVED (from the arrival, not from the last event: a turn that goes
              on passes 0 after that pause, however steadily it turns), then moves on at its own speed. The other
              direction leaves 0 at once, and so does a turn that starts from 0 at rest. A rule in time, not counts:
              the same felt pause whatever the speed, and no counts per revolution (still unmeasured) in it.
   The stepper (A3): +0x00 i64 accumulated counts, +0x08 counts per step (400 for type 1), +0x0c index, +0x18 start;
   index = floor(acc / step) with a step/3 hysteresis, so a value is set by parking acc mid-step. Each event leaves
   its counts and speed in cw_bank for a bench read (bbusb.py knob): which speeds a hand makes on the unit (b = 0, no
   SDRAM block: no detent, nothing left). Returns 0 for no move (in the detent), else 1 with *add = the counts to hand
   the stepper (fw_stepper_add, in clipwin.c).
   Tuning, one number each: the stop on 0 too long or too short = ZERO_DETENT_MS; the 10-tick steps come too soon or
   too late = KNOB_MEDIUM; the 1/64 steps too soon = KNOB_FAST (6: the top speed only); the medium steps too fine =
   KNOB_STEP_MEDIUM (15, a 1/256 note; 20 and 30 also divide 60). test_clipwin.py reads them from here. */
#define KNOB_MEDIUM      3           /* the speed (1 .. 6) from which a turn event is one medium step, */
#define KNOB_FAST        5           /* ...and from which one 1/64 */
#define KNOB_STEP_MEDIUM 10          /* ticks: a 1/384 note; it must divide SLIP_GRID */
#define SLIP_GRID        60          /* a 1/64 note */
#define ZERO_DETENT_MS   150         /* how long a turn that arrived on 0 is held there */
_Static_assert(SLIP_GRID % KNOB_STEP_MEDIUM == 0, "a medium step must divide the 1/64 grid");

static int32_t grid_next(int32_t v, int dir, int32_t grid)
{
    int32_t q = v / grid, r = v % grid;
    if (dir > 0)
        return (q - (r < 0)) * grid + grid;              /* the next multiple above v */
    return (q + (r > 0)) * grid - grid;                  /* ...below v */
}

int cw_turn(struct cw_bank *b, const uint8_t *stepper, int counts, unsigned m, uint32_t now, int32_t *add)
{
    int dir = counts > 0 ? 1 : -1;
    int32_t step = *(const int32_t *)(stepper + STEPPER_STEP), start = *(const int32_t *)(stepper + STEPPER_START);
    int32_t acc = *(const int32_t *)stepper;             /* < steps x step = 7 681 x 400: the low word is all of it */
    int32_t v = *(const int32_t *)(stepper + STEPPER_INDEX) + start, target;
    if (b) {
        b->knob_counts = (int16_t)counts;
        b->knob_speed = (uint8_t)m;
        if (!v && dir == b->zero_dir && now - b->zero_at < ZERO_DETENT_MS)
            return 0;                                    /* in the detent: the turn that arrived, too soon */
    }
    if (m < KNOB_MEDIUM) {
        int32_t a = counts * 10 * (int32_t)m;
        target = (acc + a) / step + start;               /* where the stepper would land (acc + a >= 0 here) */
        if (acc + a < 0 || !((v > 0 && target <= 0) || (v < 0 && target >= 0))) {
            *add = a;                                    /* no zero on the way: the stepper's own way */
            return 1;
        }
        target = 0;
    } else {
        target = grid_next(v, dir, m < KNOB_FAST ? KNOB_STEP_MEDIUM : SLIP_GRID);
        if ((v > 0 && target < 0) || (v < 0 && target > 0))
            target = 0;
    }
    target = target < -SLIP_MAX ? -SLIP_MAX : target > SLIP_MAX ? SLIP_MAX : target;
    if (target == 0 && v != 0 && b) {
        b->zero_dir = (int8_t)dir;                       /* arrived: the detent starts now */
        b->zero_at = now;
    }
    *add = (target - start) * step + step / 2 - acc;     /* park mid-step on the target */
    return 1;
}

/* clipwin_format: the Slip row's text for v ticks, beats.ticks with the sign ("+1.480" is one beat and 480 ticks, 960
   to a beat), as "%c%d.%03d" of the sign, |v| / 960 and |v| % 960 would print it. At most 13 bytes with the 0. */
void cw_text(char *t, int v)
{
    unsigned a = (unsigned)(v < 0 ? -v : v), beats = a / 960, ticks = a % 960, n = 0;
    char d[10];
    *t++ = v < 0 ? '-' : '+';
    do {
        d[n++] = (char)('0' + beats % 10);
        beats /= 10;
    } while (beats);
    while (n)
        *t++ = d[--n];
    t[0] = '.';
    t[1] = (char)('0' + ticks / 100);
    t[2] = (char)('0' + ticks / 10 % 10);
    t[3] = (char)('0' + ticks % 10);
    t[4] = 0;
}

/* ---- the Waveform screen in Clip mode ---- */

/* clip_view (clipwin.c): the white bracket, which shows the loop when Region plays it (is_loop over the view's store:
   mode, [ls, le), Loop Mode on, the file's len frames), written here, never with FUN_080c6edc, which hides the slice
   markers (+0x238). was = the bracket as last drawn: the stock refresh clears it without marking the widget dirty, and
   so would leave a bracket that is gone on the screen. */
void cw_bracket(uint8_t *wave, int mode, int32_t ls, int32_t le, int on, int32_t len, int was)
{
    int show = is_loop(mode, ls, le, on, len);
    int32_t *lp = (int32_t *)(wave + WAVE_LOOP);
    if (show != was || (show && (lp[0] != ls || lp[1] != le)))
        wave[WAVE_DIRTY] = 1;
    if (show) {
        lp[0] = ls;
        lp[1] = le;
    }
    wave[WAVE_LOOP_ON] = (uint8_t)show;
}
