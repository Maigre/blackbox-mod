/*
 * Clip Window: Slip, Region and Loop Len. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Why: a clip that plays in sync can only start on the grid. A loop cut by ear from an unsynced recording (a song off a
 * phone, a take from other hardware) then sits a little ahead of or behind the groove of everything else, and nothing
 * on the unit moves it. Slip shifts what a Clip pad plays against the clock, by up to a bar either way, in ticks (960 to
 * a beat: one tick is about half a millisecond at 120 BPM), live: the Electrix Repeater's "Slip".
 *
 * Stock (notes/re/a1, a2, README section 2): a synced clip plays one segment per Sync step. Segment j starts at source
 * frame (int)((float)j * fps) (fps = pad + 0x1fc) when the clock reaches its grid point and crossfades 256 samples with
 * the one before. Only WHEN a segment starts comes from the clock; there is no clock-derived target to offset. Each
 * class-B pad owns one pool of four segments (pad + 0x30 + k * 0x70), shared by its two voices:
 *   +0x00 u8 active, +0x01 u8 done, +0x08 i64 position (whole source frames), +0x1c f32 fraction (the reader's frac),
 *   +0x20 i32 start delay (> 0: not started yet), +0x34 u32 step j, +0x3c u8 first-block flag (a pending launch).
 *
 * This: Slip is a constant circular shift of what every segment plays (stock frame + slip_f, folded into the file),
 * decided once per segment when stock creates it and applied where the segment reads:
 *   H1  clipwin_seg_start    the source prefetch in FUN_08065550, the segment start (bl FUN_0806375c @0x0806578c):
 *                            latch slot k's shift (and region), prefetch where it will really read
 *   H1' clipwin_slice_start  the same in FUN_08065290, slice-marker segments (bl FUN_0806375c @0x0806541a): no shift
 *   H2  clipwin_read         the segment read (filter_thunk.S clip_read_b ends here; filter.c's clip_read next)
 *   H3  clipwin_len          Region: the clip's length where it shapes the clip (four bl FUN_080636f0, below)
 *   H3' clipwin_wrap         Region: the recompute at the two wraps (bl FUN_08064a94), where a new region starts
 *   clipwin_tick             duck_block, once per block: one pad's Slip (and Loop Len) from the app's store; on a
 *                            change, mark the pad's pending segments done so stock re-makes them, and H1 re-latches, in
 *                            the same render
 * Stock's timing, crossfades, Sync re-grid, wrap, one-shot and launch logic are untouched, and with Slip 0 (and no
 * region, Loop Len Off) every hook passes through: bit-identical to stock. A Slip change is heard at the next Sync
 * step, through stock's crossfade.
 * A new file under a playing pad (a load, the browser's pre-listen into the pad, a take landing in it): stock does not
 * restart the voice; its segments read on at their positions in the new file. A segment latched for another file
 * length reads as stock does (H2), and the next one made latches the new file.
 * Not covered: Slicer pads and Clip pads on Sync = Slice with markers (their segments start in H1': no shift); the
 * playhead on the waveform still shows the unslipped position.
 * Setting: "Slip:" on the Clip Pos page after Sync, -3840 .. +3840 ticks shown as beats.ticks ("+1.480" is one beat and
 * 480 ticks), + = ahead of the beat, - = behind (a CDJ jog: clockwise speeds up, counter-clockwise slows down), per
 * pad, saved with the preset as "clipslip". The knob: single ticks slow, 10-tick steps faster, 1/64 steps at the
 * top speeds, and a detent on 0: a turn stops there, and passes after a short pause (clipwin_turn).
 *
 * Region (notes/re/README.md section 3, a2, x3): a Clip pad plays its Sample-mode loop [Loop Start, Loop End) instead
 * of the whole file - no Trim. Stock keeps those points in Clip mode, in the cell's class-H object (pad + 8), so they
 * are read there. Stock is made to believe the file IS the region: the four fw_src_len calls that shape a clip (H3,
 * clipwin_len) answer the region's length, so Beat Count Auto, the frames per step and the last step's end follow it,
 * and every segment latches [rs, rs + vlen) in H1, which H2 reads circularly (the same latch Slip uses). A region
 * changed while the pad plays waits for its next wrap (clipwin_wrap, the recompute there, which runs when the next
 * pass's step 0 is made, about one Sync step before it sounds; a stopped pad takes it at its next recompute, the
 * launch's at the latest): changed mid-pass, the steps already made would point past the new end (notes/re/a2: 11 418
 * or 23 490 silent samples). One that moves the wrap grid (a longer clip) waits for a wrap on its own grid, where a
 * launch would start it: elsewhere stock snaps that pass's end into the past and doubles. Seamless wrap: with a region, Loop On and Launch not Trigger the last step has no end, so
 * it crossfades into the next pass like any step: no notch, no gap when the region is shorter than its beats, no
 * doubling when longer; a clip of one Sync step has that step timed by the clip (H3 site 3), as stock times steps when
 * there are more. A region under half a beat on Beat Count Auto is a clip of 0 ticks: no grid, it loops on its length.
 * Setting: "Region:" Auto | File | Loop before Slip, saved as "clipregion". Auto = Loop when the pad has a loop: Loop
 * Mode on and 0 <= start < end <= length, not the whole file ([0, length - 1] or more: what a load leaves, x3 t13);
 * File = stock; Loop = the loop points whatever Loop Mode says, the whole file still File.
 *
 * Loop Len (notes/re/README.md section 3, a2 k_looplen; D-004): only a window of W ticks loops, on the clock, where the
 * music was when it was engaged (the KP3's loop). Stock keeps making its steps on its grid; each segment H1 makes is
 * latched to play the step of the window that lines up with its own: w = (origin + ((j x tps - origin) mod W)) / tps,
 * content = (int)((float)w x fps) + slip_f, stock's own product, so a window plays the frames its steps would. origin
 * = the phase of the frame the sounding segment that started last plays (its latch's, Slip taken out, so a window
 * still sounding after Off is taken again; else stock's position), x tps / fps, rounded down to W; taken when Loop Len
 * leaves Off and kept while it changes (the in-point stays), so the window holds the beat that was playing. A stopped
 * pad sets it back to 0: its next launch loops from the clip's start, as after power-on. A W the steps do not divide
 * (shorter than a Sync step) has the pad's Sync forced, as the app would set it (the class-B param-set, FUN_08067648
 * with 0x94): the largest Sync up to the user's that divides W, the origin and the clip, so the user's comes back as
 * soon as it divides them again (a longer W), and on Off, as the app's store has it. Stock re-grids the playing segment
 * there (notes/re/a1), so the change lands on the new grid. Never while a launch waits for its Quant point (the
 * re-grid would sound it at once); the poll tries again. Off: every new segment plays its own step again, in phase.
 * Needs Quant and Sync (no grid, or no clock phase, without them); a W of the whole clip or more does nothing.
 * Setting: "Loop Len:" Off | 1/16 | 1/8 | 1/4 | 1/2 | 1 bar | 2 bars | 4 bars after Slip, saved as "cliplooplen".
 * Its take (the in-point, the Sync a window needs) and its window (the frames a segment plays) are in flash bank 2,
 * clipwin_b2.c (cw_looplen, cw_window): leaf maths, called only when b2_live() says the payload there is this build's.
 * Without it Loop Len stays Off.
 *
 * The Waveform screen in Clip mode (notes/re/a3, README section 3): stock unbinds all four knobs and draws no loop
 * bracket. TL = Loop Start, TR = Loop End (stock's 0x91 / 0x92, sample positions one zoom pixel a step, ranged as in
 * Sample mode), BL = Slip, BR = Loop Len; the white bracket shows the loop Region plays, from the view's store, so a
 * playing pad catches up with it at its next wrap (clipwin_bind, clipwin_zoom, clipwin_wave). The view's own forward
 * stores them all.
 */
#include <stdint.h>

#include "clipwin.h"

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")

#define FN(addr) ((addr) | 1u)
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
typedef int (*setting_fn)(const void *store, unsigned param);
typedef int (*src_int_fn)(void *src);
typedef void (*prefetch_fn)(void *src, int32_t pos);
typedef void (*fetch_fn)(void *src, float *dst, int n, int32_t pos, int zero);
typedef void (*fetch2_fn)(void *src, float *left, float *right, int n, int32_t pos);
typedef int (*buf_int_fn)(void *buf);
typedef float *(*buf_mono_fn)(void *buf);
typedef int (*buf_pair_fn)(void *buf, float **left, float **right);
typedef void (*kernel_fn)(float rate, const float *src, int n_src, int *used, float *frac, float *dst, int n);
typedef void (*knob_fn)(uint8_t *knob);
typedef int (*knob_value_fn)(uint8_t *knob, int value);
typedef void (*text_fn)(void *widget, const char *text);
typedef int (*snprintf_fn)(char *buf, unsigned size, const char *fmt, ...);
typedef void (*ring_push_fn)(void *ring, int counts, uint32_t ms);
typedef unsigned (*ring_speed_fn)(void *ring);
typedef void (*stepper_fn)(void *stepper, int counts);
typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*recompute_fn)(uint8_t *pad, void *clock);
typedef void (*pad_param_fn)(uint8_t *pad, void *clock, const void *msg, void *ctx);
#define fw_register_num ((register_num_fn)FN(0x0808c12c))
#define fw_pad_param    ((pad_param_fn)FN(0x08067648))   /* the class-B param-set: what a 0x39 message does */
#define fw_register_list ((register_list_fn)FN(0x0808c0d8))
#define fw_recompute    ((recompute_fn)FN(0x08064a94))   /* the class-B pad's recompute: lengths, steps, Beat Count Auto */
#define fw_store_add    ((store_add_fn)FN(0x08093ef6))
#define fw_setting      ((setting_fn)FN(0x08093e9c))
#define fw_src_len      ((src_int_fn)FN(0x080636f0))
#define fw_src_stereo   ((src_int_fn)FN(0x08063790))
#define fw_prefetch     ((prefetch_fn)FN(0x0806375c))
#define fw_fetch        ((fetch_fn)FN(0x08063634))
#define fw_fetch2       ((fetch2_fn)FN(0x08063608))
#define fw_buf_frames   ((buf_int_fn)FN(0x0804d8e8))
#define fw_buf_mono     ((buf_mono_fn)FN(0x0804d934))
#define fw_buf_pair     ((buf_pair_fn)FN(0x0804da0c))
#define fw_kernel       ((kernel_fn)FN(0x080603ec))      /* the stock clip reader's four-point kernel */
#define fw_format       ((knob_fn)FN(0x080b0528))        /* a knob's value text */
#define fw_knob_redraw  ((knob_fn)FN(0x080b0480))
#define fw_list_value   ((knob_value_fn)FN(0x080b0416))  /* type 9: the value a list position stands for */
#define fw_set_text     ((text_fn)FN(0x080c3b98))
#define fw_snprintf     ((snprintf_fn)FN(0x080c89f4))
#define fw_ring_push    ((ring_push_fn)FN(0x080b0cc4))   /* the knob's 8-entry acceleration ring */
#define fw_ring_speed   ((ring_speed_fn)FN(0x080b0ce0))  /* 1 .. 6 from |sum of counts| / span */
#define fw_stepper_add  ((stepper_fn)FN(0x080b0b74))
#define GUI_MS          (*(volatile uint32_t *)0x2402eee0u)

#define P_REGION    0x1c8            /* ours: 0x1c8..0x1cf are unused by stock (notes/re/a0) */
#define P_SLIP      0x1c9
#define P_LOOPLEN   0x1ca            /* Off, then 1/16 << (value - 1) */
#define LOOPLEN_MAX 7
#define P_SYNC      0x94             /* stock's Sync: Slice, 1 bar, 1/2, 1/4, 1/8, 1/16, None (0 .. 6, unchecked) */
#define CLOCK_CTX   0x128e0          /* the modules' context, from the engine (= the clock, notes/re/a4) */
#define REGION_FILE 1                /* Region's list: Auto, File, Loop */
#define REGION_LOOP 2
#define P_LOOP_MODE 0x8e             /* stock's Sample-mode loop: Loop Mode (0 None), Loop Start, Loop End, frames */
#define P_LOOP_START 0x91
#define P_LOOP_END  0x92
#define SLIP_MAX    3840             /* one bar of ticks */
#define TYPE_INT    1
#define APP_PADS    (0x24020088u + 0x1840u)   /* the app's pad stores: + row * 0xf0 + col * 0x30 */

/* knob widget (notes/re/a3) */
#define KNOB_PARAM  0x14
#define KNOB_TYPE   0x31
#define KNOB_VALUE  0x34
#define KNOB_TEXT   0x9c
#define KNOB_STEP0  0x270            /* the stepper; its index at + 0x27c, its start at + 0x288 */
#define KNOB_RING   0x294
#define KNOB_FROZEN 0x2d8

uint8_t *master_block(void);         /* master.c: the boot-time SDRAM block, or 0 */
int b2_live(void);                   /* cpu.c: may bank 2 be run (this build's payload, read clean) */
int clip_read(float rate, uint8_t *pad, uint8_t *filter, int32_t pos, int32_t pos_hi, int n, int *used, float *frac,
              void *scratch, void *out, void **result);
int clip_read_ring(float rate, uint8_t *pad, uint8_t *filter, int32_t real, int32_t rs, int32_t vlen, int n, int *used,
                   float *frac, void *scratch, void *out, void **result);
void clip_fetch(void *src, int stereo, float *l, float *r, int count, int32_t start, int32_t rs, int32_t vlen);

/* ---- the setting ---- */

/* master.c calls these from its registration and pad-defaults chains. */
void clipwin_register(void *table)
{
    static const char *const region_names[3] = {"Auto", "File", "Loop"};
    /* stock's own strings: "Off", then Quant Size's names (0x080ecb08) from 1/16 up to 4 bars */
    static const char *const looplen_names[LOOPLEN_MAX + 1] = {
        (const char *)0x080cd7a8, (const char *)0x080ce714, (const char *)0x080ce710, (const char *)0x080ce70c,
        (const char *)0x080ce708, (const char *)0x080ce700, (const char *)0x080ce6f8, (const char *)0x080ce6f0};
    fw_register_list(table, P_REGION, "Region:", region_names, 3, "clipregion");
    fw_register_num(table, P_SLIP, TYPE_INT, "Slip:", -SLIP_MAX, SLIP_MAX, "clipslip");
    fw_register_list(table, P_LOOPLEN, "Loop Len:", looplen_names, LOOPLEN_MAX + 1, "cliplooplen");
}

void clipwin_defaults(void *store)
{
    for (int p = P_REGION; p <= P_LOOPLEN; p++)   /* Region, Slip, Loop Len (0x1c8 .. 0x1ca), in that order */
        fw_store_add(store, p, 0);   /* stock only overwrites ids already in a store: without these nothing saves */
}

/* ---- the engine ---- */

static struct cw_bank *bank(void)
{
    uint8_t *mem = master_block();
    if (!mem)
        return 0;
    struct cw_bank *b = (struct cw_bank *)(mem + CW_OFFSET);
    if (b->magic != CW_MAGIC) {
        /* all of it zero: master_alloc clears only the magic, and SDRAM keeps the rest through a reset (a word loop,
           smaller than clearing the fields that need it, which it covers) */
        for (uint32_t *w = &b->magic; w < (uint32_t *)(b + 1); w++)
            *w = 0;
        b->magic = CW_MAGIC;
    }
    return b;
}

static const void *pad_store(unsigned q)
{
    return (const void *)(APP_PADS + (q + (q >> 2)) * 0x30u);   /* row * 0xf0 + col * 0x30 */
}

/* 0 .. 15 for one of the sixteen pads, -1 for anything else (the 17th class-B object, cell 0x401, would alias pad 1) */
static int pad_index(const uint8_t *pad)
{
    uint32_t id = *(const uint32_t *)(pad + PAD_ID);
    uint32_t row = (id >> 8) & 0xff, col = id & 0xff;
    if ((id >> 16) || row > 3 || col > 3)
        return -1;
    return (int)(row * 4 + col);
}

static __attribute__((noinline)) int32_t fold(int32_t v, int32_t len)   /* out of line: the cave is tight */
{
    v %= len;
    return v < 0 ? v + len : v;
}

/* ---- Region ---- */

/* The rule: 1 when the Region setting plays the loop [ls, le) of a file of len frames. The region is [Loop Start,
   Loop End), Loop End taken as stock keeps it (D-003; stock's own default is the length). A WAV's smpl loop comes in
   with its dwEnd as Loop End, verbatim (x3 t6), and dwEnd is the loop's last frame: such a region is one frame short,
   which nothing hears. The whole file is File: [0, len) and [0, len - 1] alike (a load leaves Loop End = the length
   with Loop Mode as it was; a whole-file smpl loop ends on len - 1), for Loop too. Auto also wants Loop Mode on. The
   engine (adopt) and the Waveform screen's bracket (clip_view) both ask it. */
static __attribute__((noinline)) int is_loop(int mode, int32_t ls, int32_t le, int on, int32_t len)
{
    return !(mode == REGION_FILE || len >= SRC_BAD || ls < 0 || ls >= le || le > len || (!ls && le >= len - 1) ||
             (mode != REGION_LOOP && !on));
}

/* The region pad q plays from now: its Region setting over the loop points. From the cell's class-H object, which
   stores them in queue order with everything else the pad hears; from the app's store when that link does not hold,
   keeping the last pair that made sense there (the app writes Loop Start and Loop End one at a time). */
static void adopt(struct cw_bank *b, int q, uint8_t *pad, int32_t len)
{
    const void *store = pad_store((unsigned)q);
    int mode = fw_setting(store, P_REGION);
    uint8_t *h = *(uint8_t **)(pad + PAD_SIBLING);
    int32_t ls, le, on;
    if (h && h[PAD_CLASS] == H_CLASS && *(uint32_t *)(h + PAD_ID) == *(uint32_t *)(pad + PAD_ID)) {
        ls = *(int32_t *)(h + H_LOOP_START);
        le = *(int32_t *)(h + H_LOOP_END);
        on = *(int32_t *)(h + H_LOOP_MODE);
    } else {
        ls = fw_setting(store, P_LOOP_START);
        le = fw_setting(store, P_LOOP_END);
        on = fw_setting(store, P_LOOP_MODE);
        if (ls >= 0 && ls < le && le <= len) {
            b->good[q][0] = ls;
            b->good[q][1] = le;
        } else {
            ls = b->good[q][0];
            le = b->good[q][1];
        }
    }
    b->region[q].vlen = 0;
    if (!is_loop(mode, ls, le, on, len))
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
   Not where sliced(). Out of line: H1 and H3 both call it, and the cave is tight (40 bytes). */
static __attribute__((noinline)) int32_t region_of(struct cw_bank *b, int q, const uint8_t *pad, int32_t len, int32_t *rs)
{
    int32_t s = b->region[q].rs, v = b->region[q].vlen;
    if (v <= 0 || len >= SRC_BAD || s > len - v || sliced(pad))
        return 0;
    *rs = s;
    return v;
}

/* H3. Replaces bl FUN_080636f0 (fw_src_len, r0 = the source; r4 = the pad, clipwin_thunk.S) at 0x08064b2c (site 1: the
   recompute's first, Beat Count Auto and the frames per step), 0x08064c5a (site 3: its second, the file tempo, right
   after it stored the step fields; clip = r9 there, the clip in output samples), 0x0806561e (site 0: FUN_08065550's
   > 0 check) and 0x08065690 (site 2: the last step's end, length - 1). Never at 0x080662f6: the reader's bound keeps
   the real length, clipwin_read folds. A playing pad takes its region only at its wrap; a stopped one at its next
   recompute, which nothing triggers when only the Region row or the loop points change: at the latest the one before
   its next voice start (0x0806838a, 0x08068632, 0x080686a8), so until the launch the clip length told the app (msg
   0x8d) can be the old one. */
int32_t clipwin_len(void *src, uint8_t *pad, int site, int32_t clip)
{
    int32_t len = fw_src_len(src), rs;
    struct cw_bank *b = bank();
    int q = pad_index(pad);
    if (!b || q < 0)
        return len;
    if (site == 1 && (b->wrap == q + 1 || !(pad[LAYER0] | pad[LAYER0 + LAYER_SIZE])))
        adopt(b, q, pad, len);
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
    if (site == 3 && pad[PAD_SYNCED] && *(uint32_t *)(pad + PAD_STEPS) == 1 && clip > 0)
        *(float *)(pad + PAD_STEP_OUT) = (float)clip;
    return v;
}

/* H3'. Replaces bl FUN_08064a94 (the recompute, r0 = pad, r1 = the clock) at 0x08066fac (the synced wrap; t = the
   render's [sp + 0x58], the tick the new pass starts on, snapped to the old +0x230) and 0x08066e9e (the unsynced one;
   t = 0), through clipwin_thunk.S: the region changed while the pad played starts with this pass.
   Unless it moves the wrap grid off this pass: stock snaps a pass's end to +0x230 = min(Quant, clip), so a longer clip
   whose first pass does not start on its own grid has that end snapped back into the past, and the next pass sounds
   at once over the last step: two early passes at gain 2, then the bar (stock does exactly that after a live Beat
   Count change). Such a region waits for a wrap on its grid, where a launch would have started it. A tick past 2^32
   (26 days at 120 BPM) takes it at once, as stock would. */
void clipwin_wrap(uint8_t *pad, void *clock, const uint32_t *t)
{
    struct cw_bank *b = bank();
    int q = pad_index(pad);
    if (!b || q < 0) {
        fw_recompute(pad, clock);
        return;
    }
    int32_t rs = b->region[q].rs, vlen = b->region[q].vlen;
    b->wrap = (uint8_t)(q + 1);
    fw_recompute(pad, clock);
    b->wrap = 0;
    uint32_t grid = *(uint32_t *)(pad + PAD_WRAP_GRID);
    if (t && !t[1] && grid && !*(uint32_t *)(pad + PAD_WRAP_GRID + 4) && t[0] % grid &&
        (b->region[q].rs != rs || b->region[q].vlen != vlen)) {
        b->region[q].rs = rs;        /* the pass plays the region it had; a layer is active, so no recompute adopts */
        b->region[q].vlen = vlen;
        fw_recompute(pad, clock);
    }
}

/* H1. src = pad + 0x24, pos = stock's prefetch point max(0, start - 8), k = the segment slot ([sp + 0x20] in
   FUN_08065550, clipwin_thunk.S), pad = r4. The segment's start (+0x08) and step (+0x34) are final here. */
static int32_t latch(struct cw_bank *b, int q, unsigned k, uint8_t *pad, void *src, int32_t pos)
{
    b->pad[q] = pad;
    b->valid[q] &= (uint8_t)~(1u << k);
    b->hinted[q] &= (uint8_t)~(1u << k);
    b->h1[q] |= (uint8_t)(1u << k);
    int32_t slip = b->slip[q];
    int32_t len = fw_src_len(src), rs = 0;
    /* the region this pass plays (H3 gave the recompute its length), or the whole file */
    int32_t vlen = region_of(b, q, pad, len, &rs);
    uint8_t *seg = pad + SEG0 + k * SEG_SIZE;
    int32_t start = (int32_t)*(int64_t *)(seg + SEG_POS);
    /* ticks per step: an i64 whose value stays far below 2^31 (a whole clip is at most 512 beats x 960) */
    int32_t tps = *(int32_t *)(pad + PAD_TPS), tps_hi = *(int32_t *)(pad + PAD_TPS + 4);
    uint32_t steps = *(uint32_t *)(pad + PAD_STEPS);
    int clip = tps > 0 && !tps_hi && steps && steps < 0x10000 ? tps * (int32_t)steps : 0;
    /* Loop Len: the window's step for this one, from bank 2 (clipwin_b2.c's cw_window), so only with this build's
       payload there */
    int32_t wd = b->ll[q] && b2_live() ? cw_window(b, (unsigned)q, pad, k, clip) : CW_NO_WINDOW;
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
       in the cave (no libgcc). */
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
    f = fold(f, vlen);
    struct cw_latch *l = &b->latch[q][k];
    l->rs = rs;
    l->vlen = vlen;
    l->delta = f;
    l->len = len;                    /* the FILE's length, not the region's: what H2 checks a load against */
    b->valid[q] |= (uint8_t)(1u << k);
    int32_t real = rs + fold(fold(start, vlen) + f, vlen) - 8;
    return real < 0 ? 0 : real;
}

void clipwin_seg_start(void *src, int32_t pos, unsigned k, uint8_t *pad)
{
    struct cw_bank *b = bank();
    int q = pad_index(pad);
    if (b && q >= 0 && k < 4)
        pos = latch(b, q, k, pad, src, pos);
    fw_prefetch(src, pos);
}

/* H1': a slice-marker segment takes slot k: whatever was latched there no longer applies */
void clipwin_slice_start(void *src, int32_t pos, unsigned k, uint8_t *pad)
{
    struct cw_bank *b = bank();
    int q = pad_index(pad);
    if (b && q >= 0 && k < 4) {
        b->valid[q] &= (uint8_t)~(1u << k);
        b->h1[q] &= (uint8_t)~(1u << k);
    }
    fw_prefetch(src, pos);
}

/* Sync on pad q as the app would set it: the class-B param-set with {0x39, cell, 0x94, idx}, the clock and its context
   (the only caller, 0x080685d2, passes exactly these). It re-grids the playing segments from their own positions and
   marks the pending ones done (notes/re/a1). */
static void set_sync(uint8_t *pad, uint8_t *engine, uint32_t idx)
{
    uint32_t msg[6];
    msg[0] = 0x39;
    msg[1] = 0;
    msg[2] = *(uint32_t *)(pad + PAD_ID);
    msg[3] = P_SYNC;
    msg[4] = idx;
    msg[5] = 0;
    fw_pad_param(pad, engine, msg, engine + CLOCK_CTX);
}

/* Loop Len on pad q, from clipwin_tick: 1 when the pad's pending segments must be made again. Its take (the in-point,
   the Sync a window needs) is cw_looplen, in bank 2 (clipwin_b2.c), which the caller has checked; the Sync it asks for
   is sent from here. */
static int looplen(struct cw_bank *b, unsigned q, uint8_t *pad, uint8_t *engine, const void *store, unsigned ll)
{
    int r = cw_looplen(b, q, pad, ll, (uint32_t)fw_setting(store, P_SYNC), pad[PAD_SYNCED] && !sliced(pad));
    if (r >> 8)
        set_sync(pad, engine, (uint32_t)(r >> 8) - 1);
    return r & 1;
}

/* duck_block calls this once per engine block, before the pads render, with the engine (the clock): one pad's Slip
   and Loop Len per call (16 within 43 ms). */
void clipwin_tick(uint8_t *engine)
{
    struct cw_bank *b = bank();
    if (!b)
        return;
    unsigned q = b->scan++ & 15;
    const void *store = pad_store(q);
    /* The row reads + = AHEAD, like a CDJ jog (Thomas, D-016): clockwise pushes the loop ahead of the beat (it plays
       from further into the file), counter-clockwise drags it behind. That is the content's shift as this file keeps it. */
    int32_t slip = fw_setting(store, P_SLIP);
    slip = slip < -SLIP_MAX ? -SLIP_MAX : slip > SLIP_MAX ? SLIP_MAX : slip;
    unsigned ll = (unsigned)fw_setting(store, P_LOOPLEN);
    if (ll > LOOPLEN_MAX)
        ll = 0;
    int moved = slip != b->slip[q];
    b->slip[q] = slip;
    uint8_t *pad = b->pad[q];
    /* Loop Len waits for a pad H1 has seen (it is taken from what the pad plays) */
    if (!pad || pad[PAD_CLASS] != 0x4c || pad_index(pad) != (int)q)
        return;
    /* Loop Len's take and window are in bank 2: without this build's payload there it stays Off (the row is kept, as
       stored), and is not taken, so it forces no Sync either */
    if (engine && (ll | b->ll[q]) && b2_live())
        moved |= looplen(b, q, pad, engine, store, ll);
    if (!moved)
        return;
    /* The guarded drop: a segment made but not started yet is marked done, so stock makes it again in this render and
       H1 latches the new Slip. Never one with the first-block flag: that is a launch waiting for its Quant point, and
       dropping it makes it sound at once, off the bar (notes/re/a2, droplaunch). The sounding segment keeps its latch:
       the change is heard at the next step, through stock's crossfade. */
    for (unsigned k = 0; k < 4; k++) {
        uint8_t *seg = pad + SEG0 + k * SEG_SIZE;
        if (!seg[0] || seg[1] || *(int32_t *)(seg + SEG_DELAY) <= 0)
            continue;
        if (!seg[SEG_FIRST]) {
            seg[1] = 1;
            continue;
        }
        /* a launch waiting for its Quant point (never dropped): it has read nothing yet, so latch it again in place,
           unless a slice segment (H1') holds the slot */
        if (b->h1[q] & (1u << k)) {
            void *src = *(void **)(pad + PAD_SOURCE);
            int32_t start = (int32_t)*(int64_t *)(seg + SEG_POS);
            fw_prefetch(src, latch(b, (int)q, k, pad, src, start > 8 ? start - 8 : 0));
        }
    }
}

/* H2: in place of filter.c's clip_read, with its arguments (the stock reader FUN_080662e4's). */
int clipwin_read(float rate, uint8_t *pad, uint8_t *filter, int32_t pos, int32_t pos_hi, int n, int *used,
                 float *frac, void *scratch, void *out, void **result)
{
    struct cw_bank *b = bank();
    int q = pad_index(pad);
    uint32_t off = (uint32_t)((uint8_t *)frac - pad) - (SEG0 + SEG_FRAC);
    unsigned k = off / SEG_SIZE;
    if (!b || q < 0 || off % SEG_SIZE || k > 3 || !(b->valid[q] & (1u << k)))
        return clip_read(rate, pad, filter, pos, pos_hi, n, used, frac, scratch, out, result);
    const struct cw_latch *l = &b->latch[q][k];
    void *src = *(void **)(pad + PAD_SOURCE);
    /* The file changed under the segment since H1 (notes/re/x3 section 4: the slot closes, fw_src_len answers 0, then
       the new file's length). Stock reads on at the segment's position in the new file; the latch's region and shift
       belong to the old length and could map past the new end. Read as stock does while the length differs: the next
       segment made latches the new file, and a file of the latched length (back after a close) maps as before. Not
       the source pointer: the key map hands the freed asset entry out again, so a load often keeps it. */
    if (fw_src_len(src) != l->len)
        return clip_read(rate, pad, filter, pos, pos_hi, n, used, frac, scratch, out, result);
    int32_t rs = l->rs, vlen = l->vlen;
    int32_t real = rs + fold(fold(pos, vlen) + l->delta, vlen);
    /* The segment's content crosses the region end mid-segment, where stock never hints: hint rs once, as soon as
       the seam is inside the hint's sure reach (notes/re/a2: 3 blocks of 8192 frames from the hinted one). */
    if (rs + vlen - real <= 16384 && !(b->hinted[q] & (1u << k))) {
        b->hinted[q] |= (uint8_t)(1u << k);
        fw_prefetch(src, rs);
    }
    /* A machine mode: filter.c's machine reader over the circular region, seam or not (it fetches from real - 3,
       n x rate + 8 frames even at rate 1). */
    int ring = clip_read_ring(rate, pad, filter, real, rs, vlen, n, used, frac, scratch, out, result);
    if (ring >= 0)
        return ring;
    int straight = rate == 1.0f && *frac == 0.0f;
    int cap = fw_buf_frames(scratch);
    int count = straight ? n : (int)((float)n * rate) + 8;
    if (count > cap)
        count = cap;
    /* No seam in the window the read needs: stock's reader at the real position. Stock adds `used` to its own
       position, which stays the unslipped one: the next block maps it again. */
    if (real + count <= rs + vlen)
        return clip_read(rate, pad, filter, real, 0, n, used, frac, scratch, out, result);
    /* The read crosses the end of the region (once a pass): the stock reader's own work, with the fetch in two parts
       so the kernel interpolates across the seam as if the file were circular. */
    int stereo = fw_src_stereo(src);
    float *sl = 0, *sr = 0;
    if (stereo)
        fw_buf_pair(scratch, &sl, &sr);
    else
        sl = fw_buf_mono(scratch);
    clip_fetch(src, stereo, sl, sr, count, real, rs, vlen);
    if (straight) {
        *used = n;
        *result = scratch;
        return 1;
    }
    if (stereo) {
        float *ol = 0, *orr = 0;
        fw_buf_pair(out, &ol, &orr);
        int u = *used;
        float f = *frac;
        fw_kernel(rate, sl, count, &u, &f, ol, n);
        fw_kernel(rate, sr, count, used, frac, orr, n);
    } else {
        fw_kernel(rate, sl, count, used, frac, fw_buf_mono(out), n);
    }
    *result = out;
    return 1;
}

/* ---- the knob ---- */

/* Replaces the value-text call (bl FUN_080b0528) at 0x080b0746 (set value, every type) and 0x080b0e18 (type-1 turn). */
void clipwin_format(uint8_t *knob)
{
    unsigned type = knob[KNOB_TYPE];
    if (*(int32_t *)(knob + KNOB_PARAM) != P_SLIP || knob[KNOB_FROZEN] || (type != TYPE_INT && type != 9)) {
        fw_format(knob);                 /* a reset knob keeps a stale id with type 0: the type test matters */
        return;
    }
    int v = type == TYPE_INT ? *(int32_t *)(knob + KNOB_STEP0 + 0xc) + *(int32_t *)(knob + KNOB_STEP0 + 0x18)
                             : fw_list_value(knob, *(int32_t *)(knob + KNOB_VALUE));
    unsigned a = (unsigned)(v < 0 ? -v : v);
    char text[32];
    fw_snprintf(text, sizeof text, "%c%d.%03d", v < 0 ? '-' : '+', (int)(a / 960), (int)(a % 960));
    fw_set_text(knob + KNOB_TEXT, text);
    fw_knob_redraw(knob);
}

/* Replaces the stepper call of the type-1 turn path (bl FUN_080b0b74 @0x080b0dde), which every screen's turn of a
   type-1 knob goes through: the Pos page's list and the Clip-mode Waveform screen's BL are the same code. For the
   Slip knob (Thomas, after Gate 2: "tricky, especially to set back to 0"; v2 after 37.2.0d: "blocking at 0 is not
   great ... accelerator is too fast it seems"), by the stock accelerator's speed m (fw_ring_speed: 1 .. 6, about
   8/7 x the counts per ms over the last 8 events):
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
   its counts and speed in cw_bank for a bench read (bbusb.py knob): which speeds a hand makes on the unit.
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

void clipwin_turn(uint8_t *stepper, int counts)
{
    uint8_t *knob = stepper - KNOB_STEP0;
    if (*(int32_t *)(knob + KNOB_PARAM) != P_SLIP || knob[KNOB_TYPE] != TYPE_INT || !counts) {
        fw_stepper_add(stepper, counts);
        return;
    }
    struct cw_bank *b = bank();
    uint32_t now = GUI_MS;
    int dir = counts > 0 ? 1 : -1;
    fw_ring_push(knob + KNOB_RING, counts, now);
    unsigned m = fw_ring_speed(knob + KNOB_RING);
    int32_t step = *(int32_t *)(stepper + 0x08), start = *(int32_t *)(stepper + 0x18);
    int32_t acc = *(int32_t *)stepper;                   /* < steps x step = 7 681 x 400: the low word is all of it */
    int32_t v = *(int32_t *)(stepper + 0x0c) + start, target;
    if (b) {
        b->knob_counts = (int16_t)counts;
        b->knob_speed = (uint8_t)m;
        if (!v && dir == b->zero_dir && now - b->zero_at < ZERO_DETENT_MS)
            return;                                      /* in the detent: the turn that arrived, too soon */
    }
    if (m < KNOB_MEDIUM) {
        int32_t add = counts * 10 * (int32_t)m;
        target = (acc + add) / step + start;             /* where the stepper would land (acc + add >= 0 here) */
        if (acc + add < 0 || !((v > 0 && target <= 0) || (v < 0 && target >= 0))) {
            fw_stepper_add(stepper, add);                /* no zero on the way: the stepper's own way */
            return;
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
    fw_stepper_add(stepper, (target - start) * step + step / 2 - acc);   /* park mid-step on the target */
}

/* ---- the Waveform screen in Clip mode (notes/re/a3, README section 3) ---- */

/* Stock unbinds all four knobs there and draws no loop bracket. This binds TL = Loop Start (0x91), TR = Loop End (0x92):
   stock's own Sample-mode rows, sample positions (type 0xd) one zoom pixel a step, ranged as stock ranges them in
   Sample mode (Loop Start 0 .. Loop End, Loop End Loop Start .. the length); BL = Slip, BR = Loop Len, the Pos page's
   rows (Slip with its own text and turn, clipwin_format and clipwin_turn). The view's generic forward stores every one
   of them (0x3d at 0x080a6c6c, a list's 0x3c at 0x080a6c10: SetCellParam), and the class-H object takes Loop Start
   and End from the queue as in Sample mode, where Region reads them: no code. The white bracket shows the loop when
   Region plays it.
   The view (FUN_080a54a0's): + 0x38 the waveform widget, + 0x1a0 its zoom (f32 frames per pixel), knobs TL + 0x670,
   BL + 0x950, TR + 0xc30, BR + 0xf10, + 0x2370 its copy of the pad's store (refreshed at each setup), + 0x2390 the
   file's length. */
typedef void (*bind_fn)(int param, int value, uint8_t *knob);
typedef void (*range_fn)(uint8_t *knob, int lo, int hi);
typedef void (*view_zoom_fn)(uint8_t *view, int zoom);
typedef void (*wave_fn)(uint8_t *wave, const void *slices);
#define fw_bind         ((bind_fn)FN(0x080a7ee0))        /* the view's binder: label, type, range from the table; value */
#define fw_revalue      ((bind_fn)FN(0x080a7fe6))        /* the view's re-value: a list's position, else knob_value */
#define fw_knob_range   ((range_fn)FN(0x080b09e4))
#define fw_knob_value   ((knob_value_fn)FN(0x080b0790))
#define fw_view_zoom    ((view_zoom_fn)FN(0x080a52c4))   /* the position knobs' step, range, value: not for Clip */
#define fw_wave_slices  ((wave_fn)FN(0x080c6e8c))
#define VIEW_WAVE   0x38
#define VIEW_STORE  0x2370
#define VIEW_LEN    0x2390
#define VIEW_BR     0xf10
#define P_PAD_MODE  0x8b             /* Pad Mode: Sample, Clip, Slicer, Granular, New Rec, New Multi */
#define PAD_MODE_CLIP 1
#define KNOB_STEP   0x28c            /* type 0xd: frames per step */
#define WAVE_DIRTY  0x32
#define WAVE_LOOP   0x22c            /* the white bracket: i32 Loop Start, i32 Loop End, then at + 0x239 u8 shown */
#define WAVE_LOOP_ON 0x239

/* the knob (its offset in the view << 16) and its row */
static const uint32_t clip_knobs[4] = {0x670u << 16 | P_LOOP_START, 0xc30u << 16 | P_LOOP_END, 0x950u << 16 | P_SLIP,
                                       VIEW_BR << 16 | P_LOOPLEN};

/* Replaces bl FUN_080a7ee0 @0x080a582a, the last of the Clip bind block's four unbinds (BR; r2 = view + 0xf10, the
   other three have run): binds all four, through the view's own binder, with the values of the view's store. */
void clipwin_bind(int param, int value, uint8_t *knob)
{
    (void)param;
    (void)value;
    uint8_t *view = knob - VIEW_BR;
    for (unsigned i = 0; i < 4; i++) {
        unsigned id = clip_knobs[i] & 0xffff;
        fw_bind((int)id, fw_setting(view + VIEW_STORE, id), view + (clip_knobs[i] >> 16));
    }
}

/* The knobs and the bracket from the view's store; step = frames per pixel for the two position knobs, 0 = as they
   are. The binder leaves a type-0xd knob at the table's range (0 .. 1000) with its value only pending, and one turn
   would post the clamped value (notes/re/a3): the step goes first (the range is counted in steps of it), then the
   range, then the value, as stock does for Sample mode. was = the bracket as last drawn: the stock refresh clears it
   without marking the widget dirty, and so would leave a bracket that is gone on the screen. */
static void clip_view(uint8_t *view, int step, int was)
{
    uint8_t *tl = view + (clip_knobs[0] >> 16), *tr = view + (clip_knobs[1] >> 16), *wave = view + VIEW_WAVE;
    if (*(int32_t *)(tl + KNOB_PARAM) != P_LOOP_START)
        return;                      /* another mode's knobs (FUN_080a53a2 runs for every mode) */
    if (step) {
        *(int32_t *)(tl + KNOB_STEP) = step;
        *(int32_t *)(tr + KNOB_STEP) = step;
    }
    const void *st = view + VIEW_STORE;
    int32_t ls = fw_setting(st, P_LOOP_START), le = fw_setting(st, P_LOOP_END), len = *(int32_t *)(view + VIEW_LEN);
    fw_knob_range(tl, 0, le);
    fw_knob_value(tl, ls);
    fw_knob_range(tr, ls, len);
    fw_knob_value(tr, le);
    /* Slip and Loop Len: re-valued only when the store has another value. Every turn comes back as a refresh, and
       a set value parks the stepper mid-step: done each time, it would make the Slip knob twice as fast here as on
       the Pos page (which does not re-value). */
    for (unsigned i = 2; i < 4; i++) {
        uint8_t *k = view + (clip_knobs[i] >> 16);
        unsigned id = clip_knobs[i] & 0xffff;
        int v = fw_setting(st, id);
        if (*(int32_t *)(k + KNOB_STEP0 + 0xc) + *(int32_t *)(k + KNOB_STEP0 + 0x18) != v)
            fw_revalue((int)id, v, k);
    }
    /* the bracket: written here, never with FUN_080c6edc, which hides the slice markers (+0x238) */
    int show = is_loop(fw_setting(st, P_REGION), ls, le, fw_setting(st, P_LOOP_MODE), len);
    int32_t *lp = (int32_t *)(wave + WAVE_LOOP);
    if (show != was || (show && (lp[0] != ls || lp[1] != le)))
        wave[WAVE_DIRTY] = 1;
    if (show) {
        lp[0] = ls;
        lp[1] = le;
    }
    wave[WAVE_LOOP_ON] = (uint8_t)show;
}

/* Replaces bl FUN_080a52c4 @0x080a53b0, in FUN_080a53a2 (r1 = (int)zoom): every bind of the screen, every zoom change
   (msg 0xe5, which no refresh follows). Stock returns at once for Clip. Only in Clip mode: New Rec and New Multi bind
   nothing, so after Clip the knobs still hold these rows there (as they hold Sample's after Sample, on stock). */
void clipwin_zoom(uint8_t *view, int zoom)
{
    fw_view_zoom(view, zoom);
    if (fw_setting(view + VIEW_STORE, P_PAD_MODE) == PAD_MODE_CLIP)
        clip_view(view, zoom > 0 ? zoom : 1, view[VIEW_WAVE + WAVE_LOOP_ON]);
}

/* Replaces bl FUN_080c6e8c @0x080a5b0e (the slice markers), the Clip case of the screen's refresh: every setup and every
   0x66 of the pad (any of its settings stored). */
void clipwin_wave(uint8_t *wave, const void *slices)
{
    int was = wave[WAVE_LOOP_ON];
    fw_wave_slices(wave, slices);
    clip_view(wave - VIEW_WAVE, 0, was);
}
