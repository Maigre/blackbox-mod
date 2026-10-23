/*
 * Clip Window: Slip. Original 1010music Blackbox, firmware 3.1.9.
 * The reverse engineering and the bench measurements behind it are in github.com/Maigre/blackbox-mod, branch
 * maigre: notes/re/ and notes/bench/ (cited below as notes/...).
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
 * restart the voice; its segments read on at their positions in the new file. A segment latched for another file
 * length reads as stock does (H2), and the next one made latches the new file. A last step whose position is past
 * the new file's end would never end, and holds the pad on its step 0 (stock's own): the poll retires it (cw_retire).
 * Not covered: Slicer pads and Clip pads on Sync = Slice with markers (their segments start in H1': no shift); the
 * playhead on the waveform still shows the unslipped position.
 * Setting: "Slip:" on the Clip Pos page after Sync, -3840 .. +3840 ticks shown as beats.ticks ("+1.480" is one beat and
 * 480 ticks), + = ahead of the beat, - = behind (a CDJ jog: clockwise speeds up, counter-clockwise slows down), per
 * pad, saved with the preset as "clipslip". The knob: single ticks slow, faster as it turns faster (one curve), 1/64
 * steps at the top speed, and a detent on 0: a turn stops there, and passes after a pause, longer when it came
 * slowly (clipwin_turn).
 *
 * Bank 2: the maths and the policy of every hook below are in flash bank 2, clipwin_b2.c (the cw_* functions: the
 * latch, the read's mapping and seam hint, the poll and its drop, the knob's tiers and detent, the Slip row's text).
 * This file keeps the hooks, every stock call they make and the bank's set-up, which leaves room in the bank 1 cave.
 * bank() asks b2_live() first: without this build's payload up there every hook passes straight through to stock, so
 * every Clip pad plays as stock does, Slip does nothing (its row is kept, as stored) and the Slip row shows stock's
 * plain number.
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
#define fw_knob_redraw  ((knob_fn)FN(0x080b0480))        /* composes the knob's line: "name value" */
#define fw_knob_name    ((text_fn)FN(0x080b03c0))        /* the knob's name (its + 0x44 text) */
#define fw_list_value   ((knob_value_fn)FN(0x080b0416))  /* type 9: the value a list position stands for */
#define fw_set_text     ((text_fn)FN(0x080c3b98))
#define fw_ring_push    ((ring_push_fn)FN(0x080b0cc4))   /* the knob's 8-entry acceleration ring */
#define fw_ring_speed   ((ring_speed_fn)FN(0x080b0ce0))  /* 1 .. 6 from |sum of counts| / span */
#define fw_stepper_add  ((stepper_fn)FN(0x080b0b74))
#define GUI_MS          (*(volatile uint32_t *)0x2402eee0u)

#define P_SLIP      0x1c9            /* ours: 0x1c8..0x1cf are unused by stock (notes/re/a0) */
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
    fw_register_num(table, P_SLIP, TYPE_INT, "Slip:", -SLIP_MAX, SLIP_MAX, "clipslip");
}

void clipwin_defaults(void *store)
{
    fw_store_add(store, P_SLIP, 0);   /* stock only overwrites ids already in a store: without it nothing saves */
}

/* ---- the engine ---- */

/* The bank, when bank 2 holds this build's payload (every hook's maths is there) and the boot-time SDRAM block is up;
   else 0, and the hook is stock's. */
static __attribute__((noinline)) struct cw_bank *bank(void)
{
    uint8_t *mem = b2_live() ? master_block() : 0;
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

/* ...and pad's index q (cw_pad), when it is one of the sixteen pads */
static __attribute__((noinline)) struct cw_bank *pad_bank(const uint8_t *pad, int *q)
{
    struct cw_bank *b = bank();
    return b && (*q = cw_pad(pad)) >= 0 ? b : 0;
}

static const void *pad_store(unsigned q)
{
    return (const void *)(APP_PADS + (q + (q >> 2)) * 0x30u);   /* row * 0xf0 + col * 0x30 */
}

/* H1. src = pad + 0x24, pos = stock's prefetch point max(0, start - 8), k = the segment slot ([sp + 0x20] in
   FUN_08065550, clipwin_thunk.S), pad = r4. The segment's start (+0x08) and step (+0x34) are final here: cw_latch
   latches slot k's shift and says where to prefetch, where it will really read. */
void clipwin_seg_start(void *src, int32_t pos, unsigned k, uint8_t *pad)
{
    int q;
    struct cw_bank *b = pad_bank(pad, &q);
    if (b)
        pos = cw_latch(b, (unsigned)q, k, pad, fw_src_len(src), pos);
    fw_prefetch(src, pos);
}

/* H1': a slice-marker segment takes slot k: whatever was latched there no longer applies */
void clipwin_slice_start(void *src, int32_t pos, unsigned k, uint8_t *pad)
{
    int q;
    struct cw_bank *b = pad_bank(pad, &q);
    if (b)
        cw_slice(b, (unsigned)q, k);
    fw_prefetch(src, pos);
}

/* duck_block calls this once per engine block, before the pads render: one pad's Slip per call (16 within 43 ms),
   cw_tick's; the segments the pad's file no longer reaches retired (cw_retire). Then, on a change, the guarded drop
   (cw_drop), and the launches waiting for their Quant point latched again in place. */
void clipwin_tick(void)
{
    struct cw_bank *b = bank();
    if (!b)
        return;
    unsigned q = b->scan++ & 15;
    int32_t slip = fw_setting(pad_store(q), P_SLIP);
    int r = cw_tick(b, q, slip);
    uint8_t *pad = b->pad[q];
    if (r & 4)                           /* a segment its file no longer reaches (cw_retire) */
        cw_retire(pad, fw_src_len(*(void **)(pad + PAD_SOURCE)));
    if (!(r & 1))
        return;
    unsigned again = cw_drop(b, q, pad);
    for (unsigned k = 0; k < 4; k++)
        if (again & (1u << k)) {
            void *src = *(void **)(pad + PAD_SOURCE);
            fw_prefetch(src, cw_latch(b, q, k, pad, fw_src_len(src), -1));
        }
}

/* H2: in place of filter.c's clip_read, with its arguments (the stock reader FUN_080662e4's). */
int clipwin_read(float rate, uint8_t *pad, uint8_t *filter, int32_t pos, int32_t pos_hi, int n, int *used,
                 float *frac, void *scratch, void *out, void **result)
{
    int q;
    struct cw_bank *b = pad_bank(pad, &q);
    const struct cw_latch *l = b ? cw_slot(b, (unsigned)q, pad, frac) : 0;
    if (!l)
        return clip_read(rate, pad, filter, pos, pos_hi, n, used, frac, scratch, out, result);
    void *src = *(void **)(pad + PAD_SOURCE);
    /* The file changed under the segment since H1 (notes/re/x3 section 4: the slot closes, fw_src_len answers 0, then
       the new file's length). Stock reads on at the segment's position in the new file; the latch's shift belongs to
       the old length and could map past the new end. Read as stock does while the length differs: the next
       segment made latches the new file, and a file of the latched length (back after a close) maps as before. Not
       the source pointer: the key map hands the freed asset entry out again, so a load often keeps it. */
    if (fw_src_len(src) != l->len)
        return clip_read(rate, pad, filter, pos, pos_hi, n, used, frac, scratch, out, result);
    int32_t rs = l->rs, vlen = l->vlen;
    int32_t real = cw_map(l, pos);       /* where it really reads */
    int straight = rate == 1.0f && *frac == 0.0f;
    int cap = fw_buf_frames(scratch);
    int count = straight ? n : (int)((float)n * rate) + 8;
    if (count > cap)
        count = cap;
    /* A machine mode: filter.c's machine reader over the file read circularly, seam or not (it fetches from real - 3,
       n x rate + 8 frames even at rate 1). */
    int ring = clip_read_ring(rate, pad, filter, real, rs, vlen, n, used, frac, scratch, out, result);
    /* the seam hint at rs, once a crossing segment is within its reach (cw_hint) */
    if (cw_hint(b, (unsigned)q, l, real))
        fw_prefetch(src, rs);
    if (ring >= 0)
        return ring;
    /* No seam in the window the read needs: stock's reader at the real position. Stock adds `used` to its own
       position, which stays the unslipped one: the next block maps it again. */
    if (real + count <= rs + vlen)
        return clip_read(rate, pad, filter, real, 0, n, used, frac, scratch, out, result);
    /* The read crosses the end of the file (once a pass): the stock reader's own work, with the fetch in two parts
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

/* Replaces the value-text call (bl FUN_080b0528) at 0x080b0746 (set value, every type) and 0x080b0e18 (type-1 turn):
   the Slip row reads beats.ticks with its sign (cw_text), stock's plain number without bank 2. */
void clipwin_format(uint8_t *knob)
{
    unsigned type = knob[KNOB_TYPE];
    if (*(int32_t *)(knob + KNOB_PARAM) != P_SLIP || knob[KNOB_FROZEN] || (type != TYPE_INT && type != 9) ||
        !b2_live()) {
        fw_format(knob);                 /* a reset knob keeps a stale id with type 0: the type test matters */
        return;
    }
    uint8_t *st = knob + KNOB_STEP0;
    int v = type == TYPE_INT ? *(int32_t *)(st + STEPPER_INDEX) + *(int32_t *)(st + STEPPER_START)
                             : fw_list_value(knob, *(int32_t *)(knob + KNOB_VALUE));
    char text[16];
    cw_text(text, v);
    fw_set_text(knob + KNOB_TEXT, text);
    fw_knob_redraw(knob);
}

/* Replaces the stepper call of the type-1 turn path (bl FUN_080b0b74 @0x080b0dde), which every screen's turn of a
   type-1 knob goes through: the Pos page's list and the Clip-mode Waveform screen's BL are the same code. For the
   Slip knob: the event goes into the stock accelerator's ring, and cw_turn (its gain by the speed, the detent on 0;
   clipwin_b2.c has the rule and its numbers) says what the stepper gets. Without bank 2, stock's stepper as it was
   called. */
void clipwin_turn(uint8_t *stepper, int counts)
{
    uint8_t *knob = stepper - KNOB_STEP0;
    if (*(int32_t *)(knob + KNOB_PARAM) != P_SLIP || knob[KNOB_TYPE] != TYPE_INT || !counts || !b2_live()) {
        fw_stepper_add(stepper, counts);
        return;
    }
    struct cw_bank *b = bank();
    uint32_t now = GUI_MS;
    int32_t add;
    fw_ring_push(knob + KNOB_RING, counts, now);
    if (cw_turn(b, stepper, counts, fw_ring_speed(knob + KNOB_RING), now, &add))
        fw_stepper_add(stepper, add);
}
