/*
 * Clip Window, the part in flash bank 2: the maths and the policy of every Clip Window hook (clipwin.c,
 * notes/re/README.md sections 2, 3). Original 1010music Blackbox, firmware 3.1.9.
 *
 * Leaf code: it reads and writes the pad, its segments, the knob, the waveform widget and the bank it is handed, and
 * calls nothing outside this file (bank 2 is written once and lives through every bank 1 install, so a branch out of it
 * would go stale: test_bank2.py). It is here to leave bank 1's cave its room: everything that is maths or policy.
 * clipwin.c keeps the hooks, every stock call (the settings lookup, the source's length and prefetch, the readers, the
 * param-set, the recompute, the knob's ring, stepper and text) and the bank's set-up, and calls in here only when
 * b2_live() says the payload up there is this build's. Without it every hook is a straight pass to stock: Slip and
 * Region do nothing, the Slip row shows stock's plain number and the waveform no bracket.
 */
#include <stdint.h>

#include "clipwin.h"

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")   /* no memset / memcpy calls out of the bank */

#define REGION_FILE 1                /* Region's list: Auto, File, Loop */
#define REGION_LOOP 2

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

/* The rule: 1 when the Region setting plays the loop [ls, le) of a file of len frames. The region is [Loop Start, Loop
   End), Loop End taken as stock keeps it (stock's own default is the length). A WAV's smpl loop comes in with its dwEnd
   as Loop End, verbatim (x3 t6), and dwEnd is the loop's last frame: such a region is one frame short, which nothing
   hears. The whole file is File: [0, len) and [0, len - 1] alike (a load leaves Loop End = the length and Loop Start 0;
   a whole-file smpl loop ends on len - 1), for Loop too. Auto is Loop: Sample mode's Loop Mode is not asked (a take
   whose points were moved on the Clip-mode Waveform would stay on File: Loop Mode is a Sample-mode row the Clip pad
   never shows). The engine (adopt) and the Waveform screen's bracket (cw_bracket) both ask it. */
static __attribute__((noinline)) int is_loop(int mode, int32_t ls, int32_t le, int32_t len)
{
    return !(mode == REGION_FILE || len >= SRC_BAD || ls < 0 || ls >= le || le > len || (!ls && le >= len - 1));
}

/* The region pad q plays from now: its Region setting over the loop points. From the cell's class-H object, which
   stores them in queue order with everything else the pad hears; from the app's store (set, which clipwin.c read)
   when that link does not hold, keeping the last pair that made sense there (the app writes Loop Start and Loop End
   one at a time). */
static void adopt(struct cw_bank *b, unsigned q, const uint8_t *pad, int32_t len, const int32_t *set)
{
    const uint8_t *h = *(uint8_t *const *)(pad + PAD_SIBLING);
    int32_t ls, le;
    if (h && h[PAD_CLASS] == H_CLASS && *(const uint32_t *)(h + PAD_ID) == *(const uint32_t *)(pad + PAD_ID)) {
        ls = *(const int32_t *)(h + H_LOOP_START);
        le = *(const int32_t *)(h + H_LOOP_END);
    } else {
        ls = set[CW_SET_START];
        le = set[CW_SET_END];
        if (ls >= 0 && ls < le && le <= len) {
            b->good[q][0] = ls;
            b->good[q][1] = le;
        } else {
            ls = b->good[q][0];
            le = b->good[q][1];
        }
    }
    b->region[q].vlen = 0;
    if (!is_loop(set[CW_SET_REGION], ls, le, len))
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

static uint32_t gcd(uint32_t a, uint32_t c)
{
    while (c) {
        uint32_t x = a % c;
        a = c;
        c = x;
    }
    return a;
}

/* H3 (clipwin_len): the clip's length stock is told at site 0 .. 3, len = fw_src_len's. At site 1 (the recompute's
   first length) the pad takes its region when it is at its wrap (clipwin_wrap) or stopped: set = the rows of its
   store (CW_SET_*), read only for that site. Site 1 also keeps len for the Waveform screen (flen: the
   view's own copy of the file's length is the app's, which can be another pad's: clipwin.c, clip_len). */
int32_t cw_len(struct cw_bank *b, unsigned q, uint8_t *pad, int site, int32_t clip, int32_t len, const int32_t *set)
{
    int32_t rs;
    if (site == 1)
        b->flen[q] = len;
    if (site == 1 && (b->wrap == q + 1 || !(pad[LAYER0] | pad[LAYER0 + LAYER_SIZE])))
        adopt(b, q, pad, len, set);
    int32_t v = region_of(b, q, pad, len, &rs);
    if (!v)
        return len;
    /* seamless: no end on the last step (end = 1 - 1 = 0), so it crossfades into the next pass like any other step; H1
       latches it with the region, so what it plays past the end is the region's start. Not for a one-shot. */
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

/* H3' (clipwin_wrap), after the recompute at a wrap: was = what the pad had before it (the region, CW_WAS_GRID its wrap
   grid, CW_WAS_CLIP its clip in ticks), t = the tick the new pass starts on (0 for the unsynced wrap). 1 when the new
   region must wait (it is put back here, and the pad recomputed again): it moves the wrap grid off this pass, where
   stock would snap the pass's end into the past and double. A tick past 2^32 takes it at once, as stock would. It waits
   only for a wrap that can come (else a region grown from under half a beat would be held until a stop and a relaunch).
   The render snaps every pass start to the old grid g, so the passes start one old pass apart, s = the old clip snapped
   to g, a tie down (stock picks the grid point a block early, notes/re/a1: a clip of 2.5 grids passes every 2): t, t +
   s, t + 2s ... They meet the new grid iff gcd(s, grid) divides t, and then within grid / gcd(s, grid) passes. No old
   grid (a clip of 0 ticks, a region under half a beat on Beat Count Auto: its passes start where its length ends them)
   or a gcd that does not divide t: no such wrap, and the region is taken now, through stock's own snap (one pass off
   the grid, then on it). */
int cw_hold(struct cw_bank *b, unsigned q, const uint8_t *pad, const uint32_t *t, const int32_t *was)
{
    b->wrapped[q] = 1;               /* the next segment H1 makes for this pad is the new pass's step 0 (cw_latch) */
    uint32_t grid = *(const uint32_t *)(pad + PAD_WRAP_GRID), g = (uint32_t)was[CW_WAS_GRID];
    struct cw_region *r = &b->region[q];
    if (!t || t[1] || !grid || *(const uint32_t *)(pad + PAD_WRAP_GRID + 4) || !(t[0] % grid) ||
        (r->rs == was[0] && r->vlen == was[1]) || !g || was[CW_WAS_CLIP] <= 0)
        return 0;
    uint32_t a = gcd(((uint32_t)was[CW_WAS_CLIP] + g / 2 - 1) / g * g, grid);   /* gcd(s, grid) */
    if (!a || t[0] % a)
        return 0;
    r->rs = was[0];                  /* the pass plays the region it had; a layer is active, so no recompute adopts */
    r->vlen = was[1];
    return 1;
}

/* ---- Slip, the segments ---- */

/* H1 (clipwin_seg_start): slot k of pad q has just been made, from the pad's steps, at stock's prefetch point pos =
   max(0, start - 8); pos < 0 = the poll latching a launch that waits for its Quant point again (cw_drop), from its own
   start. len = fw_src_len's. Latches the slot's shift (Slip) and its region (or the whole file) and returns where to
   prefetch: where it will really read, or pos when it plays as stock. */
int32_t cw_latch(struct cw_bank *b, unsigned q, unsigned k, uint8_t *pad, int32_t len, int32_t pos)
{
    if (k > 3)
        return pos;
    const uint8_t *seg = pad + SEG0 + k * SEG_SIZE;
    int32_t start = (int32_t)*(const int64_t *)(seg + SEG_POS);
    if (pos < 0)
        pos = start > 8 ? start - 8 : 0;
    unsigned wrap = b->wrapped[q];   /* made right after the pad's wrap recompute: a pass's step 0, not a launch */
    b->wrapped[q] = 0;
    b->fin[q] &= (uint8_t)~(1u << k);
    b->pad[q] = pad;
    b->valid[q] &= (uint8_t)~(1u << k);
    b->hinted[q] &= (uint8_t)~(1u << k);
    b->h1[q] |= (uint8_t)(1u << k);
    int32_t slip = b->slip[q], rs = 0;
    /* the region this pass plays (H3 gave the recompute its length), or the whole file */
    int32_t vlen = region_of(b, q, pad, len, &rs);
    int region = vlen != 0;
    /* ticks per step: an i64 whose value stays far below 2^31 (a whole clip is at most 512 beats x 960) */
    int32_t tps = *(const int32_t *)(pad + PAD_TPS), tps_hi = *(const int32_t *)(pad + PAD_TPS + 4);
    uint32_t steps = *(const uint32_t *)(pad + PAD_STEPS);
    int32_t clip = tps > 0 && !tps_hi && steps && steps < 0x10000 ? tps * (int32_t)steps : 0;
    /* Slip needs a clip to turn ticks into frames; a region does not: Beat Count Auto makes a region under half a
       beat a clip of 0 ticks, and its segments must still read the region, not the file's first frames. */
    if (!clip)
        slip = 0;
    if (!vlen) {
        if (!slip || !pad[PAD_ON] || pad[PAD_SLICER] || len <= 0 || len >= SRC_BAD)
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
    f = fold2(f, vlen);
    struct cw_latch *l = &b->latch[q][k];
    l->rs = rs;
    l->vlen = vlen;
    l->delta = f;
    l->len = len;                    /* the FILE's length, not the region's: what H2 checks a load against */
    b->valid[q] |= (uint8_t)(1u << k);
    int32_t first = rs + fold2(fold2(start, vlen) + f, vlen);
    /* Stock starts a segment hard (no fade-in: 0x08065790 moves it into the countdown after this hook) when it is a
       launch's, and at Attack 0 (pad + 0xba1, stock's default) every step 0: right where the file starts, after the
       last step's fade-out or from silence. Here the segment can start inside the audio: its first frame is not stock's
       (Slip, a region from past frame 0), or it is the step 0 of a pass the last step crossfades into (a seamless wrap:
       a region, Loop On, not Trigger, cw_len; stock's own step 0 would come after its notch). Stock's hard start then
       clicks (from the notch) or sounds the audio twice for 256 samples (under the crossfade): its first read (cw_slot)
       gives it back the fade-in stock gives every other step. A launch at the file's own start stays hard, as stock has
       it. Only at Attack 0: with an Attack the voice's own envelope fades a launch in, and stock fades every step 0 in
       itself. */
    if (pad[PAD_HARD0] && (first != start || (wrap && !*(const uint32_t *)(seg + SEG_STEP) && region && pad[PAD_LOOP] &&
                                              pad[PAD_LAUNCH] != 1)))
        b->fin[q] |= (uint8_t)(1u << k);
    int32_t real = first - 8;
    return real < 0 ? 0 : real;
}

/* H1' (clipwin_slice_start): a slice-marker segment takes slot k: whatever was latched there no longer applies */
void cw_slice(struct cw_bank *b, unsigned q, unsigned k)
{
    b->wrapped[q] = 0;
    if (k < 4) {
        b->valid[q] &= (uint8_t)~(1u << k);
        b->h1[q] &= (uint8_t)~(1u << k);
    }
}

/* clipwin_tick, pad q: slip as its store has it. Bit 0 = the pad's pending segments must be made again (cw_drop), bit 2
   = the cached pad is pad q's. The row reads + = AHEAD, like a CDJ jog: clockwise pushes the loop ahead of the beat (it
   plays from further into the file), counter-clockwise drags it behind. That is the content's shift as this file keeps
   it. */
int cw_tick(struct cw_bank *b, unsigned q, int32_t slip)
{
    b->wrapped[q] = 0;               /* a wrap with no segment after it (the pad stopping) leaves nothing for a launch */
    slip = slip < -SLIP_MAX ? -SLIP_MAX : slip > SLIP_MAX ? SLIP_MAX : slip;
    int moved = slip != b->slip[q];
    b->slip[q] = slip;
    const uint8_t *pad = b->pad[q];
    /* a pad H1 has not seen has no segment to drop or retire */
    if (!pad || pad[PAD_CLASS] != 0x4c || cw_pad(pad) != (int)q)
        return 0;
    return moved | 4;
}

/* The poll, after cw_tick's bit 2: a pad whose file changed under it while it played (the browser loads each
   highlighted file into the pad it was opened from and gives the pad its own back at the end). Stock does not restart
   the voice: each segment reads on at its position in the new file. A segment with an end - the last step, which stops
   on the length - 1 of the file it was made for - whose position is past the new file's end can never get there: the
   reader reads nothing past the end, so it never moves, and it holds its layer, which then plays only its step 0, once
   each time that comes round, until a stop (on the unit: a slot at 315 848 of a 192 000-frame file, the pad repeating
   its first beat every 2 beats; at Slip 0 as well, stock's own). Such a segment is marked done: the render retires it
   after this block's read (it reads nothing there: no click), and the layer goes on from its next segment. Never a
   launch waiting for its Quant point (+0x3c), which marking done would sound at once. len = the source's (0, the
   sentinel: a file not open, nothing to judge by). */
void cw_retire(uint8_t *pad, int32_t len)
{
    if (len <= 0 || len >= SRC_BAD)
        return;
    for (unsigned k = 0; k < 4; k++) {
        uint8_t *seg = pad + SEG0 + k * SEG_SIZE;
        if (seg[0] && !seg[1] && !seg[SEG_FIRST] && *(const int64_t *)(seg + SEG_END) &&
            *(const int64_t *)(seg + SEG_POS) >= len)
            seg[1] = 1;
    }
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
   when it is not one of the four slots or no latch holds there. At a segment's first read, one cw_latch marked as
   starting inside the audio gets back the fade-in stock took from it: (0, c + 256) -> (256, c), stock's move undone, so
   its fade-out comes on the same sample. The reader calls this before the fade stage (FUN_08066164 at 0x08066632), on
   the block the segment starts in; a step with an end re-derives its countdown from the fade-in left on every later
   block (0x08066586). A countdown that would be left at 0 or -1 (the stage's "hold") stays hard. */
const struct cw_latch *cw_slot(struct cw_bank *b, unsigned q, const uint8_t *pad, float *frac)
{
    uint32_t off = (uint32_t)((const uint8_t *)frac - pad) - (SEG0 + SEG_FRAC);
    unsigned k = off / SEG_SIZE;
    if (off % SEG_SIZE || k > 3 || !(b->valid[q] & (1u << k)))
        return 0;
    if (b->fin[q] & (1u << k)) {
        b->fin[q] &= (uint8_t)~(1u << k);
        int32_t *fc = (int32_t *)((uint8_t *)frac + (SEG_FADE_IN - SEG_FRAC));   /* the fade-in left, the countdown */
        if (!fc[0] && fc[1] > FADE_IN) {
            fc[0] = FADE_IN;
            fc[1] -= FADE_IN;
        }
    }
    return &b->latch[q][k];
}

/* ...and with that latch l holding for the file the pad has: where segment position pos really reads (rs + ((pos mod
   vlen) + delta) mod vlen) */
int32_t cw_map(const struct cw_latch *l, int32_t pos)
{
    return l->rs + fold2(fold2(pos, l->vlen) + l->delta, l->vlen);
}

/* H5, the playhead (msg 0x4a): the frame slot k of pad q reads at stock's position pos, as clipwin_read reads it: the
   region and Slip (the latch's shift) folded as cw_map folds them. -1 = stock's: no latch for the slot (a slice
   segment, or one made before the bank was up), or a file that is not the latch's (clipwin_read reads as stock does
   then too). */
int32_t cw_playhead(const struct cw_bank *b, unsigned q, unsigned k, int32_t pos, int32_t len)
{
    if (k > 3 || !(b->valid[q] & (1u << k)) || len <= 0 || b->latch[q][k].len != len)
        return -1;
    return cw_map(&b->latch[q][k], pos);
}

/* ...the read at real (clipwin_read): 1 when rs must be hinted now. The segment's content crosses the region end
   mid-segment, where stock never hints, so it is hinted once, as soon as the seam is inside the hint's sure reach
   (notes/re/a2: 3 blocks of 8192 frames from the hinted one). */
int cw_hint(struct cw_bank *b, unsigned q, const struct cw_latch *l, int32_t real)
{
    unsigned k = (unsigned)(l - b->latch[q]);
    if (l->rs + l->vlen - real <= 16384 && !(b->hinted[q] & (1u << k))) {
        b->hinted[q] |= (uint8_t)(1u << k);
        return 1;
    }
    return 0;
}

/* ---- the Slip knob ---- */

/* clipwin_turn, the type-1 turn of the Slip knob (it has to be easy to set back to 0, and to turn smoothly from
   single ticks to large moves), by the stock accelerator's speed m (fw_ring_speed: 1 .. 6, about 8/7 x the
   counts per ms over the last 8 events):
     the move  every turn event hands the stepper counts x gain(m) (400 stepper counts a tick; its own accumulator
               keeps the fractions), gain(m) = KNOB_GAIN x (KNOB_GAIN_STEP / 256)^(m - 1): one curve, no tiers. Fitted
               to the bench's knob log (notes/bench/2026-10-16-gate3-part1.md, finding 1: events ~13 ms apart, median
               counts an event by speed 21, 35, 45, 63, 80, 116): at those medians 0.5, 1.6, 3.8, 9.7, 22.5 and 60 ticks
               an event, x 2.3 .. 3.1 a speed: speed 1 gives single ticks, 40 counts a tick, speed 6 a 1/64 an event;
     the top   m >= KNOB_TOP: the move rounded to the 1/64 grid (SLIP_GRID, 60 ticks), at least one 1/64 in the turn's
               way: round values are easy to hit at speed; below it nothing snaps;
     zero      a detent, not a wall: a move that reaches or crosses 0 stops on it, and the same turn going on stays
               there until the hold has passed since it ARRIVED (a turn that goes on passes 0 after that pause, however
               steadily it turns), then moves on at its own speed. The hold is ZERO_DETENT_SLOW_MS (400) for a turn
               that arrived at speed KNOB_DETENT_SLOW (2) or under, ZERO_DETENT_MS (150) for a faster one: at speeds 1
               and 2 the knob moves 40 to 120 ticks a second, and a hand that sees 0 needs about a quarter of a second
               to stop, so 150 ms let it run 5 to 15 ticks past, slightly on the other side; a fast sweep
               through 0 is meant to pass. A hold in counts was the other way (the knob log: 650 counts would be
               ~400 ms at speed 1, 240 at speed 2, 85 at speed 6), but it would hold a deliberate turn out of 0 from
               rest too, and the counts per revolution are still unmeasured. The other direction leaves 0 at once, and
               so does a turn that starts from 0 at rest (after the hold).
   The stepper (A3): +0x00 i64 accumulated counts, +0x08 counts per step (400 for type 1), +0x0c index, +0x18 start;
   index = floor(acc / step) with a step/3 hysteresis, so a value is set by parking acc mid-step. Each event leaves
   its counts and speed in cw_bank for a bench read: which speeds a hand makes on the unit (b = 0, no
   SDRAM block: no detent, nothing left). Returns 0 for no move (in the detent), else 1 with *add = the counts to hand
   the stepper (fw_stepper_add, in clipwin.c).
   Tuning, one number each: speed 1 too fast or slow = KNOB_GAIN; the climb too steep or flat = KNOB_GAIN_STEP (469:
   10 -> 206 at speed 6; 256 = no acceleration); the 1/64 snap from a lower speed = KNOB_TOP; the stop on 0 =
   ZERO_DETENT_SLOW_MS / ZERO_DETENT_MS, and which arrivals are slow = KNOB_DETENT_SLOW. test_clipwin.py reads them. */
#define KNOB_GAIN           10       /* speed 1: stepper counts a knob count (400 a tick): a tick per 40 counts */
#define KNOB_GAIN_STEP      469      /* x 1/256 a speed above 1 (x 1.83): 206 at speed 6, a 1/64 at its median counts */
#define KNOB_TOP            6        /* the speed that snaps to the 1/64 grid */
#define SLIP_GRID           60       /* a 1/64 note */
#define ZERO_DETENT_MS      150      /* how long a fast turn that arrived on 0 is held there, */
#define ZERO_DETENT_SLOW_MS 400      /* ...a slow one, */
#define KNOB_DETENT_SLOW    2        /* ...one that arrived at this speed or under */

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
        if (!v && dir == b->zero_dir && now - b->zero_at < (b->zero_slow ? ZERO_DETENT_SLOW_MS : ZERO_DETENT_MS))
            return 0;                                    /* in the detent: the turn that arrived, too soon */
    }
    int32_t g = KNOB_GAIN << 8;                          /* gain(m) x 256 */
    for (unsigned i = 1; i < m && i < KNOB_TOP; i++)
        g = g * KNOB_GAIN_STEP >> 8;
    int32_t a = counts * g / 256;                        /* |counts| < 2^15: no overflow */
    if (m < KNOB_TOP) {
        target = (acc + a) / step + start;               /* where the stepper would land (acc + a >= 0 here) */
        if (acc + a < 0 || !((v > 0 && target <= 0) || (v < 0 && target >= 0))) {
            *add = a;                                    /* no zero on the way: the stepper's own way */
            return 1;
        }
        target = 0;
    } else {
        int32_t to = v + a / step;                       /* the move, ticks, rounded to the 1/64 grid */
        target = (to + (to < 0 ? -SLIP_GRID / 2 : SLIP_GRID / 2)) / SLIP_GRID * SLIP_GRID;
        if (dir > 0 ? target <= v : target >= v)
            target = grid_next(v, dir, SLIP_GRID);       /* at least one 1/64 its way */
        if ((v > 0 && target < 0) || (v < 0 && target > 0))
            target = 0;
    }
    target = target < -SLIP_MAX ? -SLIP_MAX : target > SLIP_MAX ? SLIP_MAX : target;
    if (target == 0 && v != 0 && b) {
        b->zero_dir = (int8_t)dir;                       /* arrived: the detent starts now */
        b->zero_at = now;
        b->zero_slow = m <= KNOB_DETENT_SLOW;
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
   mode, [ls, le), the file's len frames), written here, never with FUN_080c6edc, which hides the slice markers
   (+0x238). was = the bracket as last drawn: the stock refresh clears it without marking the widget dirty, and so
   would leave a bracket that is gone on the screen. Returns the one edge that moved on a bracket shown before and
   after (a TL or TR turn: each moves one), for the view to go there; else -1 (a bracket that appears, goes, or moves
   at both ends: a load, a Region change). */
int32_t cw_bracket(uint8_t *wave, int mode, int32_t ls, int32_t le, int32_t len, int was)
{
    int show = is_loop(mode, ls, le, len);
    int32_t *lp = (int32_t *)(wave + WAVE_LOOP), edge = -1;
    if (show != was || (show && (lp[0] != ls || lp[1] != le)))
        wave[WAVE_DIRTY] = 1;
    if (show && was && (lp[0] != ls) != (lp[1] != le))
        edge = lp[0] != ls ? ls : le;
    if (show) {
        lp[0] = ls;
        lp[1] = le;
    }
    wave[WAVE_LOOP_ON] = (uint8_t)show;
    return edge;
}
