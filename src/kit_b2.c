/*
 * The bench kit, the part in flash bank 2 (dev builds only; fork-only, D-019; notes/re/x6-input-and-card-paths.md §9).
 * Original 1010music Blackbox, firmware 3.1.9.
 *
 * WHAT IT IS. A session on the computer at the power jack drives the unit with no hands: it writes a job into the
 * mailbox with the dev build's poke, the task that may run that job finds it at a hook that already exists, runs it
 * through the path stock's own input takes, and writes the answer back for the peek. Bank 1 keeps only the gate
 * (kit.c: the SDRAM block and b2_live(), then kit_run here) and the hooks it is called from:
 *   the screen task  - the app pass's knob scan (0x080a2cd6, kit_scan): rows, info;
 *   the audio task   - usbdev_poll, between two blocks;
 *   the card task    - b2load_thunk.S, in front of each of the card loop's three file command steps.
 * Every job is reached by its INDEX in JOBS (never an address from the computer), and only by the task its index
 * names: 0x00-0x1f the screen task, 0x20-0x3f the audio task, 0x40-0x5f the card task. A request for another task is
 * left for that task; an index with no job is answered by the screen task, which runs every pass.
 *
 * Leaf code, as clipwin_b2.c: it calls stock 3.1.9 at fixed addresses and nothing in the cave (test_bank2.py), and
 * is handed the block by bank 1. Compiled only without PUBLIC_BUILD: a release's bank 2 is byte for byte what it was
 * (build.sh puts this file in bank 2 for dev builds only), and nothing in a release's bank 1 calls up here.
 *
 * THE MAILBOX, at block + 0xc000 (cw_bank's 4 KB, its last 0x100 bytes: where usbdev.c's parameter mailbox was).
 * The computer writes the request, seq LAST; the unit writes the reply, done LAST. One request at a time.
 *   +0x00 magic KIT1         +0x04 u16 index, u16 flags (0)      +0x08 epoch: the boot count (0x38800fe0)
 *   +0x0c six i32 arguments  +0x24 seq
 *   unit: +0x28 done (= the seq served)   +0x2c result   +0x30 four values back   +0x40 1 while a job spans passes
 *         +0x44 KIT_VERSION << 16 | the table's size    +0x48.. the kit's own state (the computer never writes it)
 * Results: 0 done; -1 no such job; -2 stale epoch (a request from before the last reset: SDRAM keeps it, and it must
 * not run again); -3 a bad argument; -4 stock would not take it now (r0 says why); -5 not found; -6 a FatFs error (its
 * code in r0); -7 the wrong state (no file open, one open already, no touch down, one down already).
 * MBX1, the 13-row request of 37.3.1d - 37.4.1d (bench/bbusb.py set / get), is still served at the same place with
 * the same offsets and results: +0x04 seq, +0x08 op / row / col, +0x0c id, +0x10 value; +0x14 done, +0x18 result,
 * +0x1c the store's value after.
 */
#ifndef PUBLIC_BUILD
#include <stdint.h>

#include "clipwin.h"

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")   /* no memset / memcpy calls out of the bank */

#define KIT_AT       0xc000u          /* in master.c's block: CW_OFFSET + 0xf00 */
#define KIT_MAGIC    0x3154494bu      /* "KIT1" */
#define MBX_MAGIC    0x3158424du      /* "MBX1" */
#define KIT_VERSION  1u
#define BOOTS        (*(const volatile uint32_t *)0x38800fe0u)   /* fault.c's boot record: boots since cleared */
#define APP          ((uint8_t *)0x24020088u)
#define B2_FN(addr)  ((addr) | 1u)
_Static_assert(CW_OFFSET + 0xf00u == KIT_AT && sizeof(struct cw_bank) <= 0xf00u, "the mailbox sits past cw_bank, in its 4 KB");

enum { KIT_SCREEN, KIT_AUDIO, KIT_CARD };
enum { R_OK = 0, R_INDEX = -1, R_EPOCH = -2, R_ARG = -3, R_REFUSED = -4, R_NOT_FOUND = -5, R_FATFS = -6, R_STATE = -7 };
#define R_LATER 1                     /* a job that spans passes: its done comes when it ends */

struct kit_box {
    uint32_t magic;
    uint16_t index, flags;
    uint32_t epoch;
    int32_t arg[6];
    uint32_t seq;                     /* +0x24 */
    uint32_t done;                    /* +0x28 */
    int32_t result;
    int32_t r[4];                     /* +0x30 */
    uint32_t state;                   /* +0x40 */
    uint32_t version;                 /* +0x44 */
    /* the unit's own from here */
    uint32_t screen_boot;             /* +0x48: the boot the screen task's state below belongs to */
};
_Static_assert(__builtin_offsetof(struct kit_box, seq) == 0x24 && __builtin_offsetof(struct kit_box, r) == 0x30 &&
               __builtin_offsetof(struct kit_box, screen_boot) == 0x48 && sizeof(struct kit_box) <= 0x100u,
               "the mailbox's layout is bench/bbkit.py's");

struct mbx {                          /* MBX1, as usbdev.c had it */
    uint32_t magic, seq;
    uint8_t op, row, col, pad0;
    uint16_t id, pad1;
    int32_t value;
    uint32_t done;
    int32_t result, back;
};

typedef int32_t (*param_fn)(unsigned id);
typedef int32_t (*get_fn)(const void *store, unsigned id);
typedef void (*app_msg_fn)(uint8_t *app, const void *msg);
#define fw_param_min ((param_fn)B2_FN(0x0808e2d0))     /* the parameter table's min ... */
#define fw_param_max ((param_fn)B2_FN(0x0808e304))     /* ... and max of an id */
#define fw_get       ((get_fn)B2_FN(0x08093e9c))       /* a store's value of an id */
#define fw_app_msg   ((app_msg_fn)B2_FN(0x080a1718))   /* the app's message handler: where every view's post ends */

static inline void barrier(void)
{
    __asm__ volatile("dmb" : : : "memory");
}

/* ---- the 13 pad rows (usbdev.c's parameter mailbox before the bench kit) ----
   A row is set as the 0x6e message a turned knob's view sends the app (FUN_080a1718 -> SetCellParam: the pad's store,
   the engine's 0x39, the screens' 0x66), so the store, the engine, a preset save and every Clip Window hook see a
   turn. Pad Mode, Loop Mode, Quant Size, Loop Start, Loop End, Launch Mode, Sync, Beat Count, Loop Fade, Region, Slip,
   Loop Len, Fit. op 1 sets (in the table's min .. max; Pad Mode only Sample .. Granular, never New Rec / New Multi),
   op 2 reads. Result 0, -1 an unknown op, -2 not a pad, -3 not a row it may set, -4 out of range; *back the store's
   value after. */
static const uint16_t ROWS[] = {0x8b, 0x8d, 0x47, 0x91, 0x92, 0x93, 0x94, 0xd2, 0xfa, 0x1c8, 0x1c9, 0x1ca, 0x1cb};

__attribute__((noinline)) int32_t kit_row(unsigned op, unsigned row, unsigned col, unsigned id, int32_t v, int32_t *back)
{
    unsigned known = 0;
    for (unsigned i = 0; i < sizeof ROWS / sizeof ROWS[0]; i++)
        known |= ROWS[i] == id;
    if (op != 1 && op != 2)
        return -1;
    if (row > 3 || col > 3)
        return -2;
    if (!known)
        return -3;
    if (op == 1) {
        int32_t lo = fw_param_min(id), hi = fw_param_max(id);
        if (id - 0x91u < 2)                          /* Loop Start / End: the table holds 0 .. 1000 there, not frames */
            lo = 0, hi = SRC_BAD - 1;
        if (id == 0x8b)
            hi = 3;
        if (v < lo || v > hi)
            return -4;
        uint32_t msg[6] = {0x6e, 0, row << 4 | col, id, (uint32_t)v, 0};
        fw_app_msg(APP, msg);
    }
    *back = fw_get(APP + 0x1840u + row * 0xf0u + col * 0x30u, id);
    return 0;
}

static void mbx(volatile struct mbx *x)
{
    uint32_t seq = x->seq;
    if (seq == x->done)
        return;
    barrier();                                   /* the request, read once its seq says it is all there */
    int32_t back = 0, r = kit_row(x->op, x->row, x->col, x->id, x->value, &back);
    if (r >= 0)
        x->back = back;
    x->result = r;
    barrier();
    x->done = seq;
}

/* ---- the jobs ---- */

typedef int (*job_fn)(volatile struct kit_box *b);

/* 0x00 info: the table, the screen showing (app + 0x8ca4), the GUI's ms clock, the boot count */
static int job_info(volatile struct kit_box *b)
{
    b->r[0] = (int32_t)(KIT_VERSION << 16 | 0x60u);
    b->r[1] = APP[0x8ca4];
    b->r[2] = *(const volatile int32_t *)0x2402eee0u;
    b->r[3] = (int32_t)BOOTS;
    return R_OK;
}

/* 0x01 row set (cell row, col, id, value), 0x02 row get (cell row, col, id): r0 the store's value after */
static int job_row(volatile struct kit_box *b)
{
    int32_t back = 0, r = kit_row(b->index, (unsigned)b->arg[0], (unsigned)b->arg[1], (unsigned)b->arg[2], b->arg[3], &back);
    b->r[0] = r < 0 ? r : back;                  /* refused: MBX1's reason (-2 not a pad, -3 not a row, -4 range) */
    return r < 0 ? R_ARG : R_OK;
}

#define KIT_JOBS 0x60u
static const job_fn JOBS[KIT_JOBS] = {
    [0x00] = job_info,
    [0x01] = job_row,
    [0x02] = job_row,
};

/*
 * THE GATE: what of the request in the box this task is to answer. A job index (>= 0) to run, a result to answer
 * with (< 0, never R_LATER), or KIT_NONE: nothing for this task. Its own function so test_benchkit.py's mutants can
 * reach every one of its branches.
 */
#define KIT_NONE (-100)
__attribute__((noinline)) int kit_gate(unsigned task, volatile struct kit_box *b, uint32_t seq)
{
    if (b->magic != KIT_MAGIC || seq == b->done)
        return KIT_NONE;
    barrier();
    unsigned index = b->index;
    if (index >= KIT_JOBS || !JOBS[index])
        return task == KIT_SCREEN ? R_INDEX : KIT_NONE;
    if (index >> 5 != task)
        return KIT_NONE;
    if (b->epoch != BOOTS)
        return R_EPOCH;
    return (int)index;
}

static void reply(volatile struct kit_box *b, int r, uint32_t seq)
{
    b->result = r;
    b->version = KIT_VERSION << 16 | KIT_JOBS;
    barrier();
    b->done = seq;
}

/* Bank 1's kit_poll, from each of the three tasks, with the boot-time SDRAM block, once bank 2 is live. */
void kit_run(unsigned task, uint8_t *block)
{
    volatile struct kit_box *b = (volatile struct kit_box *)(block + KIT_AT);
    if (b->magic == MBX_MAGIC) {
        if (task == KIT_SCREEN)
            mbx((volatile struct mbx *)b);
        return;
    }
    uint32_t seq = b->seq;
    int g = kit_gate(task, b, seq);
    if (g == KIT_NONE)
        return;
    int r = g < 0 ? g : JOBS[g](b);
    if (r != R_LATER)
        reply(b, r, seq);
}
#endif
