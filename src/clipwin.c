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
 * pad, saved with the preset as "clipslip". The knob: single ticks slow, 1/64 steps fast, and a turn stops on 0
 * (clipwin_turn).
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
 */
#include <stdint.h>

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

/* class-B pad ('L', vtable 0x080d0890) */
#define PAD_CLASS   0x04             /* u8 0x4c */
#define PAD_SIBLING 0x08             /* the cell's class-H ('H') object, the next module (notes/re/x3) */
#define PAD_ID      0x18             /* u32 row << 8 | col; bank << 16 (0 for the pads) */
#define PAD_SOURCE  0x24
#define PAD_ON      0x29             /* u8 Clip or Slicer mode active */
#define PAD_LOOP    0x1f4            /* u8 Loop Mode (0x8d) on */
#define PAD_SYNCED  0x1f5            /* u8 1: Quant and Sync are both not None (stock's, from the two) */
#define PAD_LAUNCH  0x1f8            /* u8 Launch Mode + 1: 1 Trigger, 2 Gate, 3 Toggle */
#define PAD_FPS     0x1fc            /* f32 source frames per step */
#define PAD_STEP_OUT 0x204           /* f32 output samples per step: a segment's countdown + 256 (FUN_08065550) */
#define PAD_TPS     0x208            /* i64 ticks per step */
#define PAD_STEPS   0x210            /* u32 steps n */
#define PAD_SYNC    0x220            /* i64 sync step, ticks: SYNC_SLICE = Sync Slice */
#define PAD_WRAP_GRID 0x230          /* i64 the wrap's grid, ticks: min(Quant, clip) */
#define PAD_SLICES  0x250            /* u32 slice markers */
#define PAD_SLICER  0x254            /* u8 */
#define LAYER0      0x260            /* two layers (voices) of 0x410: + 0 u8 active */
#define LAYER_SIZE  0x410
#define SYNC_SLICE  0xf0000
/* class-H ('H', vtable 0x080d06c8): the Sample-mode positions, kept in Clip mode too, source frames (x3) */
#define H_CLASS     0x48
#define H_LOOP_START 0xfc
#define H_LOOP_END  0x100
#define H_LOOP_MODE 0x108
#define SEG0        0x30
#define SEG_SIZE    0x70
#define SEG_POS     0x08
#define SEG_FRAC    0x1c
#define SEG_DELAY   0x20
#define SEG_STEP    0x34
#define SEG_FIRST   0x3c
#define SRC_BAD     0x10000000       /* fw_src_len's "the provider reported 0 frames" */

/* knob widget (notes/re/a3) */
#define KNOB_PARAM  0x14
#define KNOB_TYPE   0x31
#define KNOB_VALUE  0x34
#define KNOB_TEXT   0x9c
#define KNOB_STEP0  0x270            /* the stepper; its index at + 0x27c, its start at + 0x288 */
#define KNOB_RING   0x294
#define KNOB_FROZEN 0x2d8

struct cw_latch {
    int32_t rs, vlen, delta;         /* the region (v1: the whole file) and the shift, frames */
    int32_t len;                     /* fw_src_len when latched: the file the region and the shift were made for */
};

struct cw_bank {
    uint32_t magic, scan;
    int32_t slip[16];                /* as last polled */
    uint8_t *pad[16];                /* the engine's pad object, cached by H1 */
    uint8_t valid[16];               /* bit k: latch[q][k] holds */
    struct cw_latch latch[16][4];
    uint8_t h1[16];                  /* bit k: slot k's segment was made through H1 (not a slice segment, H1') */
    uint8_t hinted[16];              /* bit k: H2 has hinted rs for slot k's crossing of the region end */
    uint32_t zero_at;                /* the knob: GUI ms of the last turn event held on 0 */
    int8_t zero_dir;                 /* ...and the direction that turn was going */
    uint8_t zero_hold;               /* 1 while a turn that reached 0 goes on */
    uint8_t wrap;                    /* 1 + the pad whose wrap is recomputing right now (clipwin_wrap), else 0 */
    struct {
        int32_t rs, vlen;            /* the region the pad plays this pass, frames; vlen 0 = the whole file */
    } region[16];
    int32_t good[16][2];             /* the last loop points from the app's store that made sense (the fallback) */
    int32_t origin[16];              /* Loop Len: the window's in-point, ticks into the clip */
    uint8_t ll[16];                  /* Loop Len as taken (0 Off, else W = 240 << (ll - 1) ticks) */
    uint8_t forced[16];              /* 1: Loop Len has forced the pad's Sync; Off gives the store's back */
    int32_t sf[16][4];               /* Slip's part of latch[q][k].delta, frames (Loop Len's engage takes it out) */
};
#define CW_MAGIC  0x43574e34u        /* "CWN4": bumped with the layout (SDRAM keeps its contents through a reset) */
#define CW_OFFSET (0x56800u + 0x2d100u)   /* master.c: PRISM_BYTES + the old EXTRA_BYTES, where this bank begins */
_Static_assert(sizeof(struct cw_bank) <= 0x800, "master.c's EXTRA_BYTES gives the bank 0x800");
_Static_assert(CW_OFFSET == 0x56800u + 0x2d100u, "master.c: PRISM_BYTES + 0x2d100, cleared in master_alloc");

uint8_t *master_block(void);         /* master.c: the boot-time SDRAM block, or 0 */
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
    fw_store_add(store, P_REGION, 0); /* stock only overwrites ids already in a store: without these nothing saves */
    fw_store_add(store, P_SLIP, 0);
    fw_store_add(store, P_LOOPLEN, 0);
}

/* ---- the engine ---- */

static struct cw_bank *bank(void)
{
    uint8_t *mem = master_block();
    if (!mem)
        return 0;
    struct cw_bank *b = (struct cw_bank *)(mem + CW_OFFSET);
    if (b->magic != CW_MAGIC) {
        for (int q = 0; q < 16; q++) {
            b->slip[q] = 0;
            b->pad[q] = 0;
            b->valid[q] = 0;
            b->h1[q] = 0;
            b->hinted[q] = 0;
            b->region[q].vlen = 0;
            b->good[q][1] = 0;
            b->ll[q] = 0;
            b->forced[q] = 0;
        }
        b->zero_hold = 0;
        b->wrap = 0;
        b->scan = 0;
        b->magic = CW_MAGIC;
    }
    return b;
}

static const void *pad_store(unsigned q)
{
    return (const void *)(APP_PADS + (q >> 2) * 0xf0u + (q & 3) * 0x30u);
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
    /* The region is [Loop Start, Loop End), Loop End taken as stock keeps it (D-003; stock's own default is the
       length). A WAV's smpl loop comes in with its dwEnd as Loop End, verbatim (x3 t6), and dwEnd is the loop's last
       frame: such a region is one frame short, which nothing hears. The whole file is File: [0, len) and [0, len - 1]
       alike (a load leaves Loop End = the length with Loop Mode as it was; a whole-file smpl loop ends on len - 1),
       for Loop too. Auto also wants Loop Mode on. */
    b->region[q].vlen = 0;
    if (mode == REGION_FILE || len >= SRC_BAD || ls < 0 || ls >= le || le > len || (!ls && le >= len - 1) ||
        (mode != REGION_LOOP && !on))
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

/* Loop Len's window, ticks: 0 = Off, 1/16 (240) << (Loop Len - 1) */
static int32_t loop_w(const struct cw_bank *b, int q)
{
    unsigned ll = b->ll[q];
    return ll ? 240 << (ll - 1) : 0;
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
    /* Loop Len: a window the steps divide, shorter than the clip (else the whole clip plays) */
    int32_t W = loop_w(b, q), o = b->origin[q];
    int loop = W && W < clip && !(W % tps) && !(o % tps);
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
    /* the window's step that lines up with this one, played as stock plays a step: its first frame is stock's float
       product, truncated (a tick-domain formula is a frame off on a non-integer fps, notes/re/a2) */
    if (loop) {
        uint32_t w = (uint32_t)(o + fold((int32_t)*(uint32_t *)(seg + SEG_STEP) * tps - o, W)) / (uint32_t)tps;
        f += (int32_t)((float)w * *(float *)(pad + PAD_FPS)) - start;
    }
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

/* Loop Len on pad q, from clipwin_tick: 1 when the pad's pending segments must be made again. Nothing while a launch
   waits for its Quant point: a Sync change re-grids it, and it would sound at once (notes/re/a2, droplaunch); the
   poll comes back in 16 blocks. */
static int looplen(struct cw_bank *b, unsigned q, uint8_t *pad, uint8_t *engine, const void *store, unsigned ll)
{
    int live = 0;
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
    int32_t tps = *(int32_t *)(pad + PAD_TPS);
    int32_t clip = tps * *(int32_t *)(pad + PAD_STEPS);
    uint32_t u = (uint32_t)fw_setting(store, P_SYNC);   /* the user's Sync, as the app's store holds it */
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
            float fps = *(float *)(pad + PAD_FPS);
            for (unsigned k = 0; k < 4 && tps > 0 && fps > 0.0f; k++) {
                const uint8_t *seg = pad + SEG0 + k * SEG_SIZE;
                int32_t pos = (int32_t)*(const int64_t *)(seg + SEG_POS);
                int32_t e = pos - (int32_t)((float)*(const uint32_t *)(seg + SEG_STEP) * fps);
                if (seg[0] && !seg[1] && *(const int32_t *)(seg + SEG_DELAY) <= 0 && e < least) {
                    least = e;
                    if (b->valid[q] & (1u << k)) {
                        const struct cw_latch *l = &b->latch[q][k];
                        pos = fold(fold(pos, l->vlen) + l->delta - b->sf[q][k], l->vlen);
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
            if (u <= 6)
                set_sync(pad, engine, u);
        }
    }
    /* a window the steps do not divide: force the largest Sync (1 bar .. 1/16, idx 1 .. 5) that divides it, its
       in-point and the clip, starting from the user's (the store's), which wins when it divides them: then a forced
       Sync is given back as soon as it no longer needs to be (a longer window). Sent when the pad's differs: again if
       something moved it (the app re-sending Sync). Only on a synced pad (Quant and Sync not None): without a Quant
       there is no grid, on Sync None no clock phase, and stock's None-to-synced re-grid doubles a step (notes/re/a1). */
    int32_t W = loop_w(b, q), o = b->origin[q];
    if (W && W < clip && (W % tps || o % tps || b->forced[q]) && pad[PAD_SYNCED] &&
        !sliced(pad)) {
        uint32_t idx = u - 1 < 5 ? u : 1;
        int32_t t = 3840 >> (idx - 1);
        while (t > 240 && (W % t || o % t || clip % t)) {
            t >>= 1;
            idx++;
        }
        if (*(int32_t *)(pad + PAD_SYNC) != t) {
            set_sync(pad, engine, idx);
            b->forced[q] = idx != u;
        }
    }
    return moved;
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
    if (engine && (ll | b->ll[q]))
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

/* Replaces the stepper call of the type-1 turn path (bl FUN_080b0b74 @0x080b0dde). For the Slip knob (Thomas, after
   Gate 2: "tricky, especially to set back to 0"):
     slow     single ticks: 40 counts a tick, twice that rate at speed 2 (the stepper's own accumulator does the rest);
     fast     (speed 3 and up) one 1/64 step a turn event, onto the 1/64 grid (60 ticks): round values are easy to hit;
     zero     a move that reaches or crosses 0 stops on it, and stays there while that turn goes on (events less than
              ZERO_HOLD ms apart, the same way); a pause or the other direction moves it again.
   The stepper (A3): +0x00 i64 accumulated counts, +0x08 counts per step (400 for type 1), +0x0c index, +0x18 start;
   index = floor(acc / step) with a step/3 hysteresis, so a value is set by parking acc mid-step. */
#define SLIP_GRID 60                 /* a 1/64 note */
#define ZERO_HOLD 250                /* ms */

static int32_t grid_next(int32_t v, int dir)
{
    int32_t q = v / SLIP_GRID, r = v % SLIP_GRID;
    if (dir > 0)
        return (q - (r < 0)) * SLIP_GRID + SLIP_GRID;    /* the next multiple above v */
    return (q + (r > 0)) * SLIP_GRID - SLIP_GRID;        /* ...below v */
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
    if (b && b->zero_hold) {
        if (dir == b->zero_dir && now - b->zero_at < ZERO_HOLD) {
            b->zero_at = now;                            /* the same turn: stay on 0 */
            return;
        }
        b->zero_hold = 0;
    }
    int32_t step = *(int32_t *)(stepper + 0x08), start = *(int32_t *)(stepper + 0x18);
    int32_t acc = *(int32_t *)stepper;                   /* < steps x step = 7 681 x 400: the low word is all of it */
    int32_t v = *(int32_t *)(stepper + 0x0c) + start, target;
    if (m < 3) {
        int32_t add = counts * 10 * (int32_t)m;
        target = (acc + add) / step + start;             /* where the stepper would land (acc + add >= 0 here) */
        if (acc + add < 0 || !((v > 0 && target <= 0) || (v < 0 && target >= 0))) {
            fw_stepper_add(stepper, add);                /* no zero on the way: the stepper's own way */
            return;
        }
        target = 0;
    } else {
        target = grid_next(v, dir);
        if ((v > 0 && target < 0) || (v < 0 && target > 0))
            target = 0;
    }
    target = target < -SLIP_MAX ? -SLIP_MAX : target > SLIP_MAX ? SLIP_MAX : target;
    if (target == 0 && v != 0 && b) {
        b->zero_hold = 1;
        b->zero_dir = (int8_t)dir;
        b->zero_at = now;
    }
    fw_stepper_add(stepper, (target - start) * step + step / 2 - acc);   /* park mid-step on the target */
}
