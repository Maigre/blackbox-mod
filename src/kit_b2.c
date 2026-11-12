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
    uint32_t run_seq;                 /* +0x4c: the seq of the job spanning passes */
    uint8_t run;                      /* +0x50: that job's index, 0 = none */
    uint8_t touch_down;               /* +0x51: the kit's own contact is down */
    uint16_t run_wait;                /* +0x52: passes until its next step */
    int32_t run_left;                 /* +0x54: events (knob) still to post */
    int32_t run_arg[2];               /* +0x58: knob: code, counts; tap: - */
    int32_t run_gap;                  /* +0x60: knob: passes between events */
    int32_t run_count;                /* +0x64: events posted */
    int32_t touch_x, touch_y;         /* +0x68: where the contact is */
    uint32_t touch_wid;               /* +0x70: the widget it went down on (its id, gui widget + 0x28) */
};
_Static_assert(__builtin_offsetof(struct kit_box, seq) == 0x24 && __builtin_offsetof(struct kit_box, r) == 0x30 &&
               __builtin_offsetof(struct kit_box, screen_boot) == 0x48 && __builtin_offsetof(struct kit_box, touch_wid) == 0x70 &&
               sizeof(struct kit_box) <= 0x100u, "the mailbox's layout is bench/bbkit.py's");

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
#define KIT_JOBS 0x60u

static void reply(volatile struct kit_box *b, int r, uint32_t seq)
{
    b->result = r;
    b->version = KIT_VERSION << 16 | KIT_JOBS;
    barrier();
    b->done = seq;
}

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

/* ---- knobs (x6 §3.1): one event {0x32, code, counts} appended to the knob ring right after stock's scan, in the
   same task; stock's drain that follows delivers it to FUN_080a1718 (case 0x32 -> the UI ring -> the view) in the same
   pass, after any real knob's events. One event a pass at most, as stock posts, so the views' accelerator sees a
   hand's pace (a burst in one pass reads as a zero span). ---- */
#define HW          ((uint8_t *)0x24000170u)               /* the hardware object (FUN_080405a0) */
#define KNOB_RING   0xc70u                                 /* 64 entries x 0x18 */
#define KNOB_READ   (*(volatile uint32_t *)(HW + 0x1270u))
#define KNOB_WRITE  (*(volatile uint32_t *)(HW + 0x1274u))
#define KNOBS_ON    (*(const volatile uint8_t *)(HW + 0x18e1u))   /* the scan posts only while this is set */

/* 0 posted, 1 the ring is full (next pass), R_REFUSED knobs off */
static int knob_post(int32_t code, int32_t counts)
{
    if (!KNOBS_ON)
        return R_REFUSED;
    uint32_t w = KNOB_WRITE;
    if (w - KNOB_READ >= 64u)
        return 1;
    volatile uint8_t *e = HW + KNOB_RING + (w & 63u) * 0x18u;     /* stock's own five stores (FUN_08040724) */
    *(volatile uint16_t *)e = 0x32;
    *(volatile uint16_t *)(e + 8) = 0;
    *(volatile int32_t *)(e + 0xc) = code;
    *(volatile int32_t *)(e + 0x10) = counts;
    *(volatile uint32_t *)(e + 0x14) = 0;
    barrier();                                     /* as FUN_08040bac: the entry before the index */
    KNOB_WRITE = w + 1u;
    return 0;
}

/* ---- touch (x6 §4): the kit's own contact, run through what stock's tracker FUN_0808b050 does for a finger - the
   hit test, then the widget's down / move / up virtuals - from the screen task. Stock's tracker never sees it, so the
   panel's "no contact" cannot lift it, and it stays down until the computer lifts it. ---- */
#define GUI         (*(uint8_t *const volatile *)0x24002e6cu)
#define TOUCH_ID    15                             /* the contact's id: the controller's are 0 .. 9 */
typedef int (*hit_fn)(void *container, int32_t pt[2], void **widget);
typedef int (*find_fn)(void *container, uint32_t id, void **widget);
typedef void (*touch_fn)(void *widget, int32_t pt[2], int id);
#define fw_hit      ((hit_fn)B2_FN(0x080ab5f2))   /* the current screen's hit test, then the container's children */
#define fw_find     ((find_fn)B2_FN(0x080aecda))  /* a widget by its id (it may be gone) */

/* down (0), move (1), up (2) at x, y; the widget's id or 0 */
static uint32_t touch(volatile struct kit_box *b, unsigned what, int32_t x, int32_t y)
{
    uint8_t *gui = GUI;
    int32_t pt[2] = {x, y};
    void *w = 0;
    if (what == 0) {
        b->touch_wid = fw_hit(gui + 0x280, pt, &w) ? *(uint32_t *)((uint8_t *)w + 0x28) : 0;
        b->touch_down = 1;
    } else if (!fw_find(gui + 0x280, b->touch_wid, &w))
        w = 0;
    if (w)
        (*(touch_fn *)(*(uint8_t **)w + 0x10u + 4u * what))(w, pt, TOUCH_ID);  /* vt + 0x10 / + 0x14 / + 0x18 */
    b->touch_x = x;
    b->touch_y = y;
    if (what == 2)
        b->touch_down = 0;
    return b->touch_wid;
}

static int screen_xy(int32_t x, int32_t y)
{
    return x >= 0 && x < 320 && y >= 0 && y < 240;
}

/* ---- jobs that span passes: the screen task steps the one running, once a pass, before it looks at anything new ---- */
static void finish(volatile struct kit_box *b, int r)
{
    b->r[0] = b->run == 0x03 ? b->run_count : (int32_t)b->touch_wid;
    b->run = 0;
    b->state = 0;
    reply(b, r, b->run_seq);
}

static void step(volatile struct kit_box *b)
{
    if (b->run_wait) {
        b->run_wait--;
        return;
    }
    if (b->run == 0x05) {                          /* the tap's hold is over: up where it went down */
        touch(b, 2, b->touch_x, b->touch_y);
        finish(b, R_OK);
        return;
    }
    int p = knob_post(b->run_arg[0], b->run_arg[1]);
    if (p == 1)
        return;                                    /* ring full: the next pass */
    if (p < 0) {
        finish(b, p);
        return;
    }
    b->run_count++;
    b->run_wait = (uint16_t)b->run_gap;
    if (--b->run_left <= 0)
        finish(b, R_OK);
}

/* the job in the box goes on over the next passes; R_LATER, or R_DONE when its first step ended it (answered already) */
#define R_DONE 2
static int start(volatile struct kit_box *b, unsigned index, uint32_t wait, int now)
{
    b->run_seq = b->seq;
    b->run = (uint8_t)index;
    b->run_wait = (uint16_t)wait;
    b->state = 1;
    if (now)
        step(b);
    return b->run ? R_LATER : R_DONE;
}

/* 0x03 knob (code 0 TL, 1 BL, 2 TR, 3 BR; counts per event, +-1 .. 32 767; events 1 .. 10 000; passes between, 0 .. 1 000):
   r0 the events posted. -4 (r0 = 1) while stock has the knobs off. */
static int job_knob(volatile struct kit_box *b)
{
    int32_t code = b->arg[0], counts = b->arg[1], n = b->arg[2], gap = b->arg[3];
    if ((uint32_t)code > 3u || !counts || counts > 32767 || counts < -32767 || n < 1 || n > 10000 || gap < 0 || gap > 1000)
        return R_ARG;
    if (!KNOBS_ON) {
        b->r[0] = 1;
        return R_REFUSED;
    }
    b->run_arg[0] = code;
    b->run_arg[1] = counts;
    b->run_left = n;
    b->run_gap = gap;
    b->run_count = 0;
    return start(b, 0x03, 0, 1);                   /* the first event in this pass */
}

/* 0x04 touch (0 down, 1 move, 2 up; x 0 .. 319, y 0 .. 239, the screenshot's pixels): r0 the widget's id (0: none
   there). -7 a down on a contact already down, a move or up with none down. */
static int job_touch(volatile struct kit_box *b)
{
    unsigned what = (unsigned)b->arg[0];
    if (what > 2u || (what < 2u && !screen_xy(b->arg[1], b->arg[2])))
        return R_ARG;
    if (!GUI)
        return R_REFUSED;
    if ((what == 0) == (b->touch_down != 0))
        return R_STATE;
    b->r[0] = (int32_t)touch(b, what, what == 2u ? b->touch_x : b->arg[1], what == 2u ? b->touch_y : b->arg[2]);
    return R_OK;
}

/* 0x05 tap (x, y, passes held 1 .. 1 000): down in this pass, up that many passes later at the same place; r0 the
   widget's id */
static int job_tap(volatile struct kit_box *b)
{
    int32_t held = b->arg[2];
    if (!screen_xy(b->arg[0], b->arg[1]) || held < 1 || held > 1000)
        return R_ARG;
    if (!GUI)
        return R_REFUSED;
    if (b->touch_down)
        return R_STATE;
    touch(b, 0, b->arg[0], b->arg[1]);
    return start(b, 0x05, (uint32_t)held - 1u, 0);
}

/* ---- buttons (x6 §3.2): the press, release or hold code of the button's own row in stock's table, written as stock's
   scan FUN_080437d4 writes it, into both of the panel's rings - G, which the GUI's app pass drains (FUN_080a2e60: the
   screens, BACK, INFO), then E, which the audio block drains (FUN_0804cb1c: REC, STOP, PLAY on the clock). From the
   audio task, the scan's own, between two blocks. PLAY is button 10, STOP 9, REC 8. ---- */
#define PANEL       ((uint8_t *)0x240021bcu)
#define BUTTONS     ((const uint8_t *)0x24009ab0u)  /* 13 rows x 0x18: +8 press, +0xa release, +0xc hold (u16, 0 = none) */

static void panel_put(uint32_t ring, uint32_t write_at, uint16_t code, int32_t index)
{
    volatile uint32_t *w = (volatile uint32_t *)(PANEL + write_at);
    uint32_t at = *w;
    volatile uint8_t *e = PANEL + ring + (at & 63u) * 0x18u;
    *(volatile uint16_t *)e = code;
    *(volatile uint16_t *)(e + 8) = 0;
    *(volatile int32_t *)(e + 0xc) = index;
    *(volatile uint32_t *)(e + 0x10) = 0;
    *(volatile uint32_t *)(e + 0x14) = 0;
    barrier();
    *w = at + 1u;
}

/* 0x20 button (0 PADS 1 KEYS 2 SEQS 3 SONG 4 FX 5 MIX 6 PSET 7 TOOLS 8 REC 9 STOP 10 PLAY 11 BACK 12 INFO; 0 press,
   1 release, 2 hold): r0 the code posted. -3 a button that has no such code (r0 0); -4 a ring full (r0 1). */
static int job_button(volatile struct kit_box *b)
{
    uint32_t i = (uint32_t)b->arg[0], what = (uint32_t)b->arg[1];
    if (i > 12u || what > 2u)
        return R_ARG;
    uint16_t code = *(const volatile uint16_t *)(BUTTONS + i * 0x18u + 8u + 2u * what);
    b->r[0] = code;
    if (!code)
        return R_ARG;
    if (*(volatile uint32_t *)(PANEL + 0x604) - *(volatile uint32_t *)(PANEL + 0x600) >= 64u ||
        *(volatile uint32_t *)(PANEL + 0xc0c) - *(volatile uint32_t *)(PANEL + 0xc08) >= 64u) {
        b->r[0] = 1;
        return R_REFUSED;
    }
    panel_put(0x000, 0x604, code, (int32_t)i);
    panel_put(0x608, 0xc0c, code, (int32_t)i);
    return R_OK;
}

static const job_fn JOBS[KIT_JOBS] = {
    [0x00] = job_info,
    [0x01] = job_row,
    [0x02] = job_row,
    [0x03] = job_knob,
    [0x04] = job_touch,
    [0x05] = job_tap,
    [0x20] = job_button,
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

/* Bank 1's kit_poll, from each of the three tasks, with the boot-time SDRAM block, once bank 2 is live. */
void kit_run(unsigned task, uint8_t *block)
{
    volatile struct kit_box *b = (volatile struct kit_box *)(block + KIT_AT);
    if (task == KIT_SCREEN) {
        if (b->screen_boot != BOOTS) {             /* SDRAM keeps the box through a reset: a job or a contact of the */
            b->screen_boot = BOOTS;                /* boot before is not this boot's */
            b->run = 0;
            b->touch_down = 0;
            b->state = 0;
        }
        if (b->run) {                              /* a job spanning passes: one step, and nothing new meanwhile */
            step(b);
            return;
        }
    }
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
    if (r <= R_OK)                                 /* R_LATER: its done comes when it ends; R_DONE: it ended already */
        reply(b, r, seq);
}
#endif
