/*
 * Looper FX: a KP3-style looper on the XY page, as two more FX A types. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Why: the DJ FX Repeater only repeats forwards from the touch. A looper should loop what was ALREADY playing: touch
 *   the pad and the bar (or beat) under the finger comes round again, on the grid; lift the finger and it is live
 *   again; Hold latches it; X picks the length, Y sweeps a high-pass over the loop.
 * Stock: FX A is a sub-slot of the DJ FX container on Out 1 (after the FX1 / FX2 returns and the EQ, before JOEBOX's
 *   Master FX and the compressor). Its type list is Repeater, Gater, Filter; the type lives only in the engine, as the
 *   class of the effect object the slot holds (notes/re/a5-djfx-xy-repeater.md). The XY pad sends 0x15 (touch) and
 *   the X / Y ids of a per-type axis table; the Hold button sends 0x1a.
 * This: FX A lists Looper and Loop In after Filter. Both are the slot's own Repeater object in another mode (the
 *   Munchi pattern): the index is latched in the slot setter (looper_fxa_set, looper_thunk.S), the Repeater's
 *   process and active() are wrapped, and its two 8 s float ring buffers become the looper's 16 s int16 ring.
 *   Looper loops Out 1 itself (pads, returns and a monitored input) in place of Out 1; Loop In loops the audio input
 *   alone, in place of the monitored input (or on top, when the input is not monitored on Out 1).
 *   X = Length: 4 bars, 2 bars, 1 bar, 1/2, 1/4, 1/8, 1/16 (left = longest, as the Repeater), the in-point fixed.
 *   Y = HPF on the loop: bottom = open, top = 4 kHz. The stock Hold button latches. The DSP is looper_dsp.c, in bank 2.
 * Setting: nothing is stored: like stock, the DJ FX type is Repeater again after a power cycle.
 */
#include "looper.h"

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")

#define FN(addr) ((addr) | 1u)
typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*fx_fn)(uint8_t *fx);
typedef int (*process_fn)(uint8_t *fx, uint8_t *ctx);
typedef int (*active_fn)(uint8_t *fx);
typedef uint8_t *(*bus_fn)(uint8_t *ctx, unsigned index);
typedef int (*frames_fn)(uint8_t *buf);
typedef void (*chans_fn)(uint8_t *buf, float **l, float **r);
typedef uint8_t *(*queue_fn)(uint8_t *ctx, uint32_t chan);
#define fw_register_list ((register_list_fn)FN(0x0808c0d8))
#define fw_rep_reset     ((fx_fn)FN(0x0806d03c))      /* the Repeater's vt+0x78 */
#define fw_rep_process   ((process_fn)FN(0x0806d858)) /* the Repeater's vt+0x0c */
#define fw_rep_active    ((active_fn)FN(0x0806d0a0))  /* the Repeater's vt+0x70 */
#define fw_out_bus       ((bus_fn)FN(0x0805f37c))     /* ctx + 0x150e4 + index * 0x14 */
#define fw_buf_frames    ((frames_fn)FN(0x0804d8e8))
#define fw_buf_lr        ((chans_fn)FN(0x0804d9c0))   /* both channels, clearing / copying L to R as the flags ask */
#define fw_queue         ((queue_fn)FN(0x0805f2c8))   /* the engine messages of one channel, this block */

#define REP_VT        0x080df580u     /* the Repeater's vtable */
#define FXA_CLASS     ((const uint8_t *)0x080df6d8)   /* FX A index -> class: 40 3f 3d */
#define CLASS_REP     0x40u
#define SUB_EFFECT    0x20            /* sub-slot: the current effect */
#define TAIL          2048            /* floats of each ring buffer the Repeater's backfill can reach */

uint8_t *master_block(void);     /* master.c: the boot-time SDRAM block, or 0 */
int b2_live(void);               /* cpu.c: may bank 2 be run */
int b2_present(void);            /* cpu.c: is this image's bank 2 payload there (for the names) */

/* FX A: the stock three (their own strings) and ours */
static const char *const fxa_names[5] = {(const char *)0x080cd4d4, (const char *)0x080cd4e0, (const char *)0x080cd4ac,
                                         "Looper", "Loop In"};
static const char *const fxa_names_none[5] = {(const char *)0x080cd4d4, (const char *)0x080cd4e0,
                                              (const char *)0x080cd4ac, "---", "---"};
/* The XY axis table, moved here from 0x080eea78 (the bytes after it are a vtable's header): {count, {X, Y} x count}.
   Repeater, Gater and Filter as stock; Looper and Loop In both X = Length, Y = HPF. */
const uint16_t lp_axes[12] __attribute__((aligned(4))) = {5, 0, 0x1c, 0x13, 0x1d, 0x1e, 0x10, 0x11, P_LP_LEN, P_LP_HPF, P_LP_LEN, P_LP_HPF};

/* the Looper's state, in master.c's boot block; 0 when there is none */
static struct lp_bank *looper_bank(void)
{
    uint8_t *mem = master_block();
    if (!mem)
        return 0;
    struct lp_bank *b = (struct lp_bank *)(mem + LP_OFFSET);
    if (b->magic != LP_MAGIC) {
        for (unsigned i = 0; i < sizeof *b / 4; i++)
            ((volatile uint32_t *)b)[i] = 0;
        b->magic = LP_MAGIC;
    }
    return b;
}

/* Replaces bl FUN_0808c0d8 @0x0808c594: FX A's type list (stock: 3 names at 0x080eb5b8). Also registers the X axis. */
void looper_register_fxa(void *table, int param, const char *label, const char *const *names, int count, const char *xml)
{
    (void)names;
    (void)count;
    fw_register_list(table, param, label, b2_present() ? fxa_names : fxa_names_none, 5, xml);
    /* "Length:" and the stock Clip Quant names 4 bars .. 1/16 (0x080ecb0c; its 8th, None, is left out) */
    fw_register_list(table, P_LP_LEN, (const char *)0x080cb8bc, (const char *const *)0x080ecb0c, LP_LENS, "looperlen");
}

/*
 * looper_fxa_set (looper_thunk.S, b.w @0x0806e174, the slot setter's case for id 0x18 = FX A's type) calls this with
 * the sub-slot and an index 0..4; it answers the class the slot should hold. Looper and Loop In are the Repeater's
 * class, so going between them and Repeater swaps nothing: the Repeater is reset here instead.
 */
unsigned looper_latch(uint8_t *sub, unsigned idx)
{
    unsigned cls = idx >= LP_MODE_LOOPER ? CLASS_REP : FXA_CLASS[idx];
    struct lp_bank *b = looper_bank();
    if (!b)
        return cls;                  /* no state: Looper and Loop In stay Repeaters */
    unsigned was = b->mode;
    b->mode = (uint8_t)idx;
    b->sub = (uint32_t)sub;
    if (was == idx || (was < LP_MODE_LOOPER && idx < LP_MODE_LOOPER))
        return cls;
    b->dsp.init = 0;                 /* the loop stops and the ring starts over, as any DJ FX type change cuts */
    uint8_t *fx = *(uint8_t *volatile *)(sub + SUB_EFFECT);   /* the sub-slot is Device memory: one aligned load */
    if ((was < LP_MODE_LOOPER) == (idx < LP_MODE_LOOPER) || !fx || *(uint32_t *)fx != REP_VT)
        return cls;                  /* Looper <-> Loop In, or the slot holds another type */
    fw_rep_reset(fx);                /* no Repeater slices left running, either way */
    if (idx < LP_MODE_LOOPER) {
        /* Leaving: the Repeater's backfill reads the ring behind its write index, which the reset put at 0, so the
           end of both buffers. Our int16 pairs read as floats can be NaN: zero that end. */
        uint32_t floats = *(uint32_t *)(fx + 0x38);
        for (int c = 0; c < 2; c++) {
            uint32_t p = *(uint32_t *)(fx + 0x3c + 4 * c);
            if (floats >= TAIL && floats <= 384000u && !(p & 3u) && p >= 0xc0000000u && p + floats * 4u <= 0xc4000000u)
                for (uint32_t i = floats - TAIL; i < floats; i++)
                    ((volatile uint32_t *)p)[i] = 0;
        }
    }
    return cls;
}

/* The Repeater's vt+0x0c (word @0x080df58c): in Looper / Loop In mode, the looper runs instead. */
int looper_process(uint8_t *fx, uint8_t *ctx)
{
    struct lp_bank *b = looper_bank();
    if (!b || b->mode < LP_MODE_LOOPER || !b->sub || *(uint8_t *volatile *)(b->sub + SUB_EFFECT) != fx)
        return fw_rep_process(fx, ctx);
    if (b2_live()) {                 /* the DSP is in bank 2: pass Out 1 through rather than run a bad one */
        uint8_t *bus = fw_out_bus(ctx, *(volatile uint16_t *)(fx + 0x1e));
        int n = fw_buf_frames(bus);
        float *l = 0, *r = 0;
        fw_buf_lr(bus, &l, &r);
        uint8_t *q = fw_queue(ctx, *(volatile uint32_t *)(fx + 0x18));
        if (l && r && q && n > 0 && n <= 1024)
            lp_run(b, fx, ctx, q, l, r, n);
    }
    return 1;
}

/* The Repeater's vt+0x70 (word @0x080df5f0): a looper is always active, so the ring is fed while nothing loops. */
int looper_active(uint8_t *fx)
{
    struct lp_bank *b = looper_bank();
    return b && b->mode >= LP_MODE_LOOPER ? 1 : fw_rep_active(fx);
}

/* duck_block, before the stock tick: the clock as the pads will see it this block (the DJ FX run after the advance). */
void looper_tick(uint8_t *engine)
{
    struct lp_bank *b = looper_bank();
    if (!b || b->mode < LP_MODE_LOOPER)
        return;
    b->snap_sample = *(volatile uint32_t *)engine;
    b->snap_tick_lo = *(volatile uint32_t *)(engine + 0x30);
    b->snap_tick_hi = *(volatile int32_t *)(engine + 0x34);
    b->snap_play = *(volatile uint8_t *)(engine + 0x38);
}
