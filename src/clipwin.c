/*
 * Clip Window v1: Slip. Original 1010music Blackbox, firmware 3.1.9.
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
 *                            latch slot k's shift, prefetch where it will really read
 *   H1' clipwin_slice_start  the same in FUN_08065290, slice-marker segments (bl FUN_0806375c @0x0806541a): no shift
 *   H2  clipwin_read         the segment read (filter_thunk.S clip_read_b ends here; filter.c's clip_read next)
 *   clipwin_tick             duck_block, once per block: one pad's Slip from the app's store; on a change, mark the
 *                            pad's pending segments done so stock re-makes them, and H1 re-latches, in the same render
 * Stock's timing, crossfades, Sync re-grid, wrap, one-shot and launch logic are untouched, and with Slip 0 every hook
 * passes through: bit-identical to stock. A Slip change is heard at the next Sync step, through stock's crossfade.
 * A new file under a playing pad (a load, the browser's pre-listen into the pad, a take landing in it): stock does not
 * restart the voice; its segments read on at their positions in the new file. A segment latched for another length
 * reads as stock does (H2), and the next one made latches the new file.
 * Not covered: Slicer pads and Clip pads on Sync = Slice with markers (their segments start in H1': no shift); the
 * playhead on the waveform still shows the unslipped position.
 * Setting: "Slip:" on the Clip Pos page after Sync, -3840 .. +3840 ticks shown as beats.ticks ("+1.480" is one beat and
 * 480 ticks), + = ahead of the beat, - = behind (a CDJ jog: clockwise speeds up, counter-clockwise slows down), per
 * pad, saved with the preset as "clipslip". The knob: single ticks slow, 1/64 steps fast, and a turn stops on 0
 * (clipwin_turn).
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
#define fw_register_num ((register_num_fn)FN(0x0808c12c))
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

#define P_SLIP      0x1c9            /* ours: 0x1c8..0x1cf are unused by stock (notes/re/a0) */
#define SLIP_MAX    3840             /* one bar of ticks */
#define TYPE_INT    1
#define APP_PADS    (0x24020088u + 0x1840u)   /* the app's pad stores: + row * 0xf0 + col * 0x30 */

/* class-B pad ('L', vtable 0x080d0890) */
#define PAD_CLASS   0x04             /* u8 0x4c */
#define PAD_ID      0x18             /* u32 row << 8 | col; bank << 16 (0 for the pads) */
#define PAD_SOURCE  0x24
#define PAD_ON      0x29             /* u8 Clip or Slicer mode active */
#define PAD_TPS     0x208            /* i64 ticks per step */
#define PAD_STEPS   0x210            /* u32 steps n */
#define PAD_SLICER  0x254            /* u8 */
#define SEG0        0x30
#define SEG_SIZE    0x70
#define SEG_POS     0x08
#define SEG_FRAC    0x1c
#define SEG_DELAY   0x20
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
};
#define CW_MAGIC  0x43574e32u        /* "CWN2": bumped with the layout (SDRAM keeps its contents through a reset) */
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
    fw_register_num(table, P_SLIP, TYPE_INT, "Slip:", -SLIP_MAX, SLIP_MAX, "clipslip");
}

void clipwin_defaults(void *store)
{
    fw_store_add(store, P_SLIP, 0);   /* stock only overwrites ids already in a store: without this nothing saves */
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
        }
        b->zero_hold = 0;
        b->scan = 0;
        b->magic = CW_MAGIC;
    }
    return b;
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

static int32_t fold(int32_t v, int32_t len)
{
    v %= len;
    return v < 0 ? v + len : v;
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
    int32_t len = fw_src_len(src);
    /* ticks per step: an i64 whose value stays far below 2^31 (a whole clip is at most 512 beats x 960) */
    int32_t tps = *(int32_t *)(pad + PAD_TPS), tps_hi = *(int32_t *)(pad + PAD_TPS + 4);
    uint32_t steps = *(uint32_t *)(pad + PAD_STEPS);
    if (slip && pad[PAD_ON] && !pad[PAD_SLICER] && len > 0 && len < SRC_BAD && tps > 0 && !tps_hi && steps &&
        steps < 0x10000) {
        /* slip_f = floor(slip x len / clip) mod len, clip = ticks per step x steps (not Beat Count x 960: the two
           differ when the steps do not divide the clip). Double precision is the M7's own; no 64-bit division in
           the cave (no libgcc). */
        double x = (double)slip * (double)len / ((double)tps * (double)steps);
        int32_t f = (int32_t)x;
        if ((double)f > x)
            f--;
        f = fold(f, len);
        struct cw_latch *l = &b->latch[q][k];
        l->rs = 0;
        l->vlen = len;
        l->delta = f;
        l->len = len;
        b->valid[q] |= (uint8_t)(1u << k);
        int32_t start = (int32_t)*(int64_t *)(pad + SEG0 + k * SEG_SIZE + SEG_POS);
        int32_t real = fold(fold(start, len) + f, len) - 8;
        pos = real < 0 ? 0 : real;
    }
    return pos;
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

/* duck_block calls this once per engine block, before the pads render: one pad's Slip per call (16 within 43 ms). */
void clipwin_tick(void)
{
    struct cw_bank *b = bank();
    if (!b)
        return;
    unsigned q = b->scan++ & 15;
    const void *store = (const void *)(APP_PADS + (q >> 2) * 0xf0u + (q & 3) * 0x30u);
    /* The row reads + = AHEAD, like a CDJ jog (Thomas, D-016): clockwise pushes the loop ahead of the beat (it plays
       from further into the file), counter-clockwise drags it behind. That is the content's shift as this file keeps it. */
    int32_t slip = fw_setting(store, P_SLIP);
    slip = slip < -SLIP_MAX ? -SLIP_MAX : slip > SLIP_MAX ? SLIP_MAX : slip;
    if (slip == b->slip[q])
        return;
    b->slip[q] = slip;
    uint8_t *pad = b->pad[q];
    if (!pad || pad[PAD_CLASS] != 0x4c || pad_index(pad) != (int)q)
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
