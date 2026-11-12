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
 * code in r0); -7 the wrong state (no file open, one open already, no touch down, one down already); -8 busy: a job
 * spanning passes runs (a knob, a tap; r0 its index), and until it ends every request but a cancel (0x08) is answered
 * so, by the screen task.
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
enum { R_OK = 0, R_INDEX = -1, R_EPOCH = -2, R_ARG = -3, R_REFUSED = -4, R_NOT_FOUND = -5, R_FATFS = -6, R_STATE = -7,
       R_BUSY = -8 };
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
    uint32_t card_boot;               /* +0x74: the boot the card task's state below belongs to */
    uint32_t file_ms;                 /* +0x78: the GUI clock at the last file job */
    uint8_t file_open;                /* +0x7c: the kit's file: 0 none, 1 open to read, 2 open to write */
};
_Static_assert(__builtin_offsetof(struct kit_box, seq) == 0x24 && __builtin_offsetof(struct kit_box, r) == 0x30 &&
               __builtin_offsetof(struct kit_box, screen_boot) == 0x48 && __builtin_offsetof(struct kit_box, touch_wid) == 0x70 &&
               __builtin_offsetof(struct kit_box, file_open) == 0x7c &&
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

/* ---- the long peek and the long poke (usbdev.c's peek 0xc0 / 0x50 with wLength over 64, its poke 0x40 / 0x54): one
   control transfer of up to 4 096 bytes, a 64-byte packet at a time, each next one moved from the controller's
   interrupt the moment the last has gone (from the poll it would be one packet a block, 24 KB/s). usbdev.c checks the
   range (the peek's regions; the poke's RAMs) and b2_live(), sends the peek's first 64 bytes itself, and calls in here
   only while its flag in DAINTMSK is up; every reset clears that register, so nothing up here runs in a boot that did
   not start a transfer. These touch the controller's registers and nothing else. ---- */
#define USB         0x40040000u
#define USBREG(o)   (*(volatile uint32_t *)(USB + (o)))
#define GINTMSK     USBREG(0x018)
#define DIEPMSK     USBREG(0x810)
#define DAINTMSK    USBREG(0x81c)
#define DIEPCTL0    USBREG(0x900)
#define DIEPINT0    USBREG(0x908)
#define DIEPTSIZ0   USBREG(0x910)
#define DOEPCTL0    USBREG(0xb00)
#define DOEPTSIZ0   USBREG(0xb10)
#define SETUP_ARM   ((3u << 29) | (1u << 19) | 64u)   /* usbdev.c's: one 64-byte packet (or three setups) */
#define FIFO0       USBREG(0x1000)
#define EPENA       (1u << 31)
#define CNAK        (1u << 26)
#define XFRC        (1u << 0)
#define IEPINT      (1u << 18)
#define KIT_IN      (1u << 0)                      /* DAINTMSK: endpoint 0 IN's interrupt - a long peek runs */
#define KIT_OUT     (1u << 16)                     /* DAINTMSK: endpoint 0 OUT's, never let through - a long poke runs */
struct kit_long {
    uint32_t at, end;                              /* the bytes still to move: [at, end) */
};
#define LONG ((volatile struct kit_long *)0x388006b8u)   /* backup SRAM, behind usbdev.c's usbdiag, before rotate.c */

/* usbdev.c's request(), the poll: the rest of a long transfer */
void kit_long(uint32_t at, uint32_t end, unsigned out)
{
    LONG->at = at;
    LONG->end = end;
    if (out) {
        DAINTMSK |= KIT_OUT;
        return;
    }
    DIEPINT0 = XFRC;                               /* nothing earlier counts: the first packet's "sent" is the next */
    DIEPMSK |= XFRC;
    GINTMSK |= IEPINT;
    DAINTMSK |= KIT_IN;
}

/* usbaud_isr, a long peek running: its next packet once the last has gone, or the end */
void kit_usb_in(void)
{
    if (!(DIEPINT0 & XFRC))
        return;
    DIEPINT0 = XFRC;
    uint32_t at = LONG->at, n = LONG->end - at;
    if (!n) {
        DAINTMSK &= ~KIT_IN;                       /* endpoint 0 is the poll's again */
        return;
    }
    if (n > 64u)
        n = 64u;
    LONG->at = at + n;
    DIEPTSIZ0 = (1u << 19) | n;
    DIEPCTL0 |= EPENA | CNAK;
    for (const volatile uint32_t *p = (const volatile uint32_t *)at; n; n -= 4u)
        FIFO0 = *p++;                              /* a word at a time, as the peek reads: the LTDC's registers want it */
}

/* usbaud_isr's receive(), a long poke running: one entry of endpoint 0's receive FIFO - a packet's words, kept while
   they fit, or "that packet is in": arm for the next, or, the last one in, the status stage (an empty packet back) */
void kit_usb_out(uint32_t status)
{
    uint32_t bytes = (status >> 4) & 0x7ffu, at = LONG->at, end = LONG->end;
    if (((status >> 17) & 0xfu) == 2u) {
        for (uint32_t i = 0; i < bytes; i += 4u) {
            uint32_t w = FIFO0;
            if (at < end) {
                *(volatile uint32_t *)at = w;
                at += 4u;
            }
        }
        LONG->at = at;
        return;
    }
    if (at < end) {
        DOEPTSIZ0 = SETUP_ARM;
        DOEPCTL0 |= EPENA | CNAK;
        return;
    }
    DAINTMSK &= ~KIT_OUT;
    DIEPTSIZ0 = 1u << 19;
    DIEPCTL0 |= EPENA | CNAK;
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

/* ---- jobs that span passes: the screen task steps the one running, once a pass, before it looks at anything new.
   While one runs, the box is the screen task's alone (kit_gate): what the computer asks meanwhile is answered -8 or,
   a cancel, ends it. So only this task writes done until it ends, and its answer is written only while its own
   request is still in the box - done never goes back to an older seq, which would make the task of the newer request
   run it a second time. It is answered before it lets the box go (run 0), so another task can take the next. ---- */
static void finish(volatile struct kit_box *b, int r)
{
    if (b->seq == b->run_seq) {
        b->r[0] = b->run == 0x03 ? b->run_count : (int32_t)b->touch_wid;
        reply(b, r, b->run_seq);
    }
    b->run = 0;
    b->state = 0;
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

/* 0x08 cancel: ends the job spanning passes (a tap's contact lifted where it went down first); r0 its index (0: none
   ran), r1 the knob's events posted or the tap's widget. The ended job's own request is never answered. */
#define KIT_CANCEL 0x08u
static int job_cancel(volatile struct kit_box *b)
{
    unsigned run = b->run;
    b->r[0] = (int32_t)run;
    b->r[1] = 0;
    if (run == 0x05)
        touch(b, 2, b->touch_x, b->touch_y);
    if (run)
        b->r[1] = run == 0x03 ? b->run_count : (int32_t)b->touch_wid;
    b->run = 0;
    b->state = 0;
    return R_OK;
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

/* ---- the card's files (x6 §6): stock's FatFs (R0.13-style, exFAT, tiny, long names) from the card task only - it
   takes no lock, and every stock caller runs in this task (b2load.c's header). One file at a time, its FIL in the kit's
   data area; a file left open 10 s with no job is closed, so a computer that went away leaves no open write behind.
   The data area (dev builds: master.c's KIT_BYTES at the tail's end, block + 0x84900):
     +0x000 FIL (0x58)   +0x058 DIR (0x58)   +0x0b0 FILINFO (0x120)   +0x200 a path or name, 256 B, the computer's
     +0x400 the chunk, 4 096 B: a file's bytes either way, a listing's records ---- */
#define KIT_DATA    0x84900u                       /* CORE_BYTES + PRISM_BYTES + 0x22000 */
#define D_FIL       0x000u
#define D_DIR       0x058u
#define D_FNO       0x0b0u
#define D_NAME      0x200u
#define D_CHUNK     0x400u
#define CHUNK       4096u
#define PRISM_MEM   (*(const volatile uint32_t *)0x38800f70u)   /* master.c: the block, and its check word */
#define PRISM_CHECK (*(const volatile uint32_t *)0x38800f74u)
#define CARD_FOUND  (*(const volatile uint8_t *)(0x240021a4u + 0x15u))   /* stock's "the root opened" (b2load.c) */
#define GUI_MS      (*(const volatile uint32_t *)0x2402eee0u)
#define WDG_DISK    (*(volatile uint32_t *)0x2400a584u)                 /* the card task's watchdog stamp ... */
#define WDG_NOW     (*(const volatile uint32_t *)0x2400a58cu)           /* ... and the counter it copies */
#define IDLE_MS     10000u

typedef int (*f_open_fn)(void *fp, const char *path, unsigned mode);
typedef int (*f_rw_fn)(void *fp, void *buf, unsigned n, unsigned *done);
typedef int (*f_fp_fn)(void *fp);
typedef int (*f_lseek_fn)(void *fp, uint64_t ofs);                 /* the offset in r2:r3 (checked at stock's calls) */
typedef int (*f_path_fn)(const char *path, void *fno);
typedef int (*f_dir_fn)(void *dp, const char *path);
typedef int (*f_readdir_fn)(void *dp, void *fno);
typedef int (*f_unlink_fn)(const char *path);
#define fw_f_open     ((f_open_fn)B2_FN(0x08086534))
#define fw_f_read     ((f_rw_fn)B2_FN(0x08086866))
#define fw_f_write    ((f_rw_fn)B2_FN(0x08086a06))
#define fw_f_close    ((f_fp_fn)B2_FN(0x08086d76))
#define fw_f_lseek    ((f_lseek_fn)B2_FN(0x08086d96))
#define fw_f_stat     ((f_path_fn)B2_FN(0x0808724a))
#define fw_f_opendir  ((f_dir_fn)B2_FN(0x080870f6))
#define fw_f_readdir  ((f_readdir_fn)B2_FN(0x080871a0))
#define fw_f_closedir ((f_fp_fn)B2_FN(0x0808718c))
#define fw_f_unlink   ((f_unlink_fn)B2_FN(0x0808748e))
#define FA_READ 1u
#define FA_WRITE 2u
#define FA_CREATE_NEW 4u                           /* fails with FR_EXIST (8) on a file that is there */
#define FA_CREATE_ALWAYS 8u
#define FA_OPEN_ALWAYS 0x10u

/* the data area: the block's tail is there (master.c's check word keyed PRISM), or 0. And the block on a cache line's
   start (it is, on the unit: 0xc0435720 on 37.4.1d, 12/11), so the chunk's lines are its own (chunk_lines). */
static uint8_t *data_area(volatile struct kit_box *b)
{
    uint32_t block = (uint32_t)b - KIT_AT;
    return PRISM_MEM == block && PRISM_CHECK == (block ^ 0x5052534du) && !(block & 31u) ? (uint8_t *)block + KIT_DATA : 0;
}

/* The card's DMA and the chunk: stock reads and writes whole sectors with SDMMC1's IDMA straight into or out of the
   caller's buffer (HAL_SD_ReadBlocks_DMA, FUN_0807fef0) and keeps no data cache maintenance at all, while SDRAM is
   write-back cached (x2) and the long peek and poke reach the chunk through the cache. So before a read or a write
   every line of the bytes it moves is written out and forgotten (the card gets what the computer put; no dirty line
   lands later on what the card wrote), and after a read written out and forgotten again (the computer's next peek
   reads SDRAM). Written out, not only forgotten, after the read too (review 12/11): f_read also copies bytes into the
   buffer with the CPU (a partial sector, its window's sector: FUN_08084200 in FUN_08086866), and SDRAM takes no line
   on a write miss (x2), so those bytes are in SDRAM - unless a line came back into the cache during the read (a
   speculative read, a peek of the chunk), when they sit in that line and forgetting it would lose them. A line that
   only the DMA wrote is clean in the cache or absent, so writing it out changes nothing. Not closed: a line holding
   both bytes the CPU copied and bytes the DMA wrote (only a read that starts at no sector's start gives one: after a
   seek), and taken into the cache during that read. */
#define DCCIMVAC    (*(volatile uint32_t *)0xe000ef70u)   /* data cache: write this line out and forget it */
static void chunk_lines(volatile uint32_t *op, const uint8_t *chunk, uint32_t n)
{
    __asm__ volatile("dsb" : : : "memory");
    for (uint32_t a = (uint32_t)chunk; a < (uint32_t)chunk + n; a += 32u)
        *op = a;
    __asm__ volatile("dsb\n isb" : : : "memory");
}

static uint64_t fil_u64(const uint8_t *fil, unsigned at)
{
    return *(const volatile uint32_t *)(fil + at) | (uint64_t) * (const volatile uint32_t *)(fil + at + 4u) << 32;
}

/* a FatFs result as the job's: 0, or -6 with FatFs's code in r0 */
static int fatfs(volatile struct kit_box *b, int res)
{
    if (!res)
        return R_OK;
    b->r[0] = res;
    return R_FATFS;
}

/* What every file job needs first: the data area, a card, a name that ends inside its 256 bytes when it takes one, and
   the kit's file open (want 1) or not (want 0) or either (want 2). 0, or the job's refusal. */
static int file_ready(volatile struct kit_box *b, const uint8_t *d, int name, unsigned want)
{
    if (!d || CARD_FOUND != 1u) {
        b->r[0] = 6;
        return R_REFUSED;
    }
    if (name) {
        unsigned i = 0;
        while (i < 256u && d[D_NAME + i])
            i++;
        if (i == 0 || i == 256u)
            return R_ARG;
    }
    if (want < 2u && (b->file_open != 0) != want)
        return R_STATE;
    b->file_ms = GUI_MS;
    return R_OK;
}

/* 0x40 open (0 read, 1 write a new file - refused with FatFs's FR_EXIST (8) if it is there, 2 write replacing it, 3
   append; the path at +0x200): r0, r1 the file's size */
static int job_open(volatile struct kit_box *b)
{
    static const uint8_t MODES[4] = {FA_READ, FA_WRITE | FA_CREATE_NEW, FA_WRITE | FA_CREATE_ALWAYS, FA_WRITE | FA_OPEN_ALWAYS};
    uint8_t *d = data_area(b);
    uint32_t mode = (uint32_t)b->arg[0];
    int r = mode > 3u ? R_ARG : file_ready(b, d, 1, 0);
    if (r)
        return r;
    for (unsigned i = 0; i < 0x58u / 4u; i++)      /* stock clears the FIL before each f_open */
        ((volatile uint32_t *)(d + D_FIL))[i] = 0;
    r = fw_f_open(d + D_FIL, (const char *)d + D_NAME, MODES[mode]);
    if (!r && mode == 3u && (r = fw_f_lseek(d + D_FIL, fil_u64(d + D_FIL, 0x10u))) != 0)
        fw_f_close(d + D_FIL);
    if (r)
        return fatfs(b, r);
    b->file_open = mode ? 2u : 1u;
    uint64_t size = fil_u64(d + D_FIL, 0x10u);    /* the FIL's object size */
    b->r[0] = (int32_t)(uint32_t)size;
    b->r[1] = (int32_t)(uint32_t)(size >> 32);
    return R_OK;
}

/* 0x41 read (bytes, 1 .. 4 096, into the chunk), 0x42 write (bytes from the chunk): r0 the bytes moved (a read short of
   what was asked is the file's end) */
static int job_rw(volatile struct kit_box *b)
{
    uint8_t *d = data_area(b);
    uint32_t n = (uint32_t)b->arg[0];
    int r = n - 1u >= CHUNK ? R_ARG : file_ready(b, d, 0, 1);
    if (r)
        return r;
    unsigned done = 0, read = b->index == 0x41;
    chunk_lines(&DCCIMVAC, d + D_CHUNK, n);
    r = (read ? fw_f_read : fw_f_write)(d + D_FIL, d + D_CHUNK, n, &done);
    if (read)
        chunk_lines(&DCCIMVAC, d + D_CHUNK, n);
    b->r[0] = (int32_t)done;
    return r ? fatfs(b, r) : R_OK;
}

/* 0x43 seek (the offset, low and high words): r0, r1 where the file is now */
static int job_seek(volatile struct kit_box *b)
{
    uint8_t *d = data_area(b);
    int r = file_ready(b, d, 0, 1);
    if (r)
        return r;
    r = fw_f_lseek(d + D_FIL, (uint32_t)b->arg[0] | (uint64_t)(uint32_t)b->arg[1] << 32);
    if (r)
        return fatfs(b, r);
    uint64_t at = fil_u64(d + D_FIL, 0x38u);       /* the FIL's position */
    b->r[0] = (int32_t)(uint32_t)at;
    b->r[1] = (int32_t)(uint32_t)(at >> 32);
    return R_OK;
}

static int file_close(volatile struct kit_box *b, uint8_t *d)
{
    b->file_open = 0;
    return fw_f_close(d + D_FIL);
}

/* 0x44 close */
static int job_close(volatile struct kit_box *b)
{
    uint8_t *d = data_area(b);
    int r = file_ready(b, d, 0, 1);
    return r ? r : fatfs(b, file_close(b, d));
}

/* 0x45 stat (the path): r0, r1 the size, r2 the attributes (0x10 a folder), r3 date << 16 | time (FAT's) */
static int job_stat(volatile struct kit_box *b)
{
    uint8_t *d = data_area(b);
    int r = file_ready(b, d, 1, 2);
    if (r)
        return r;
    if ((r = fw_f_stat((const char *)d + D_NAME, d + D_FNO)) != 0)
        return fatfs(b, r);
    uint64_t size = fil_u64(d + D_FNO, 0);
    b->r[0] = (int32_t)(uint32_t)size;
    b->r[1] = (int32_t)(uint32_t)(size >> 32);
    b->r[2] = d[D_FNO + 0xc];
    b->r[3] = (int32_t)((uint32_t)*(volatile uint16_t *)(d + D_FNO + 8) << 16 | *(volatile uint16_t *)(d + D_FNO + 0xa));
    return R_OK;
}

/* 0x46 list (the folder's path, "" the root; the first entry to give, the most to give): records into the chunk, each
   {u32 size low, u32 size high, u8 attributes, u8 name length, the name, zeros to a whole word}; r0 the records, r1 1
   when more entries follow, r2 the chunk's bytes used */
static int job_list(volatile struct kit_box *b)
{
    uint8_t *d = data_area(b);
    int32_t skip = b->arg[0], max = b->arg[1];
    int r = skip < 0 || max < 1 ? R_ARG : file_ready(b, d, 0, 2);
    if (r)
        return r;
    if ((r = fw_f_opendir(d + D_DIR, (const char *)d + D_NAME)) != 0)
        return fatfs(b, r);
    uint32_t used = 0, count = 0, more = 0;
    uint8_t *fno = d + D_FNO;
    for (;;) {
        WDG_DISK = WDG_NOW;                        /* a long folder: this task's watchdog stamp, as stock's loops do */
        if ((r = fw_f_readdir(d + D_DIR, fno)) != 0 || !fno[0x1a])
            break;
        if (skip) {
            skip--;
            continue;
        }
        unsigned len = 0;
        while (len < 255u && fno[0x1a + len])
            len++;
        uint32_t rec = (10u + len + 3u) & ~3u;
        if ((int32_t)count == max || used + rec > CHUNK) {
            more = 1;
            break;
        }
        uint8_t *o = d + D_CHUNK + used;
        for (unsigned i = 0; i < 8u; i++)
            o[i] = fno[i];
        o[8] = fno[0xc];
        o[9] = (uint8_t)len;
        for (unsigned i = 0; i < rec - 10u; i++)
            o[10u + i] = i < len ? fno[0x1a + i] : 0;
        used += rec;
        count++;
    }
    fw_f_closedir(d + D_DIR);
    b->r[0] = (int32_t)count;
    b->r[1] = (int32_t)more;
    b->r[2] = (int32_t)used;
    return fatfs(b, r);
}

/* 0x47 delete (the path): refused while the kit's file is open */
static int job_delete(volatile struct kit_box *b)
{
    uint8_t *d = data_area(b);
    int r = file_ready(b, d, 1, 0);
    return r ? r : fatfs(b, fw_f_unlink((const char *)d + D_NAME));
}

/* The card task's own upkeep, every call: a file of the boot before is no file (its FIL meant that boot's volume),
   and one left open IDLE_MS with no job is closed. */
__attribute__((noinline)) static void card_upkeep(volatile struct kit_box *b)
{
    if (b->card_boot != BOOTS) {
        b->card_boot = BOOTS;
        b->file_open = 0;
    }
    uint8_t *d;
    if (b->file_open && GUI_MS - b->file_ms > IDLE_MS && (d = data_area(b)) != 0)
        file_close(b, d);
}

/* stock's state the preset load and the restart look at */
#define SYSTEM      0x2400a9c0u                    /* the engine / system object (FUN_08070bf4) */
#define CLOCK       (*(const uint8_t *const volatile *)(SYSTEM + 0x9a74u))   /* the transport's clock */
#define PRESETS     ((const uint8_t *)0x2401f508u)  /* the preset manager F */
#define CMD_READ    (*(const volatile uint32_t *)(PRESETS + 0x120u))   /* its file command ring */
#define CMD_WRITE   (*(const volatile uint32_t *)(PRESETS + 0x124u))
#define LOAD_NAME   (*(const char *const volatile *)(PRESETS + 0x390u))  /* a preset load asked for, not done yet */
typedef int (*idle_fn)(uint32_t system);
#define fw_streamer_idle ((idle_fn)B2_FN(0x0807125c))   /* LoadBank's own "is the card's command queue empty" */
#define DCCMVAC     (*(volatile uint32_t *)0xe000ef68u) /* data cache: write this line out */
#define AIRCR       (*(volatile uint32_t *)0xe000ed0cu)

/* ---- a preset load by name (x6 §5): the GUI task finds the name in stock's preset list and posts the message the
   PSET screen's Load button posts, {0x18, the list's index at +0xc}, to the app's handler FUN_080a1718, whose case 0x18
   runs LoadBank (FUN_0809e218: the pads' sample work dropped, the card's command 0x22 queued) and shows the Pads screen.
   LoadBank's own refusals are checked first, so the job can say which one held. ---- */
#define PRESET_LIST ((uint8_t *)0x2401f834u)        /* F + 0x32c: {u32 count, ..., +0xc char **names, +0x10 re-sort} */
#define D_SCRATCH   0x300u                         /* the data area's 256 bytes the kit reads a name into */
typedef int (*preset_name_fn)(uint8_t *list, uint32_t i, char *to);
#define fw_preset_name ((preset_name_fn)B2_FN(0x0804290c))   /* name i (re-sorting first when due), 1 while i < count */

static int same(const char *a, const char *b)
{
    while (*a && *a == *b)
        a++, b++;
    return *a == *b;
}

/* 0x06 preset load (the name at +0x200, as the list has it): r0 the list's index. -5 not in the list; -4 with r0 4 a
   load pending, 5 the card's queue busy (LoadBank would refuse it); -4 r0 6 no data area. */
static int job_preset(volatile struct kit_box *b)
{
    uint8_t *d = data_area(b);
    if (!d) {
        b->r[0] = 6;
        return R_REFUSED;
    }
    if (!d[D_NAME])
        return R_ARG;
    uint32_t i = 0;
    while (fw_preset_name(PRESET_LIST, i, (char *)d + D_SCRATCH) && !same((const char *)d + D_SCRATCH, (const char *)d + D_NAME))
        i++;
    if (i >= *(volatile uint32_t *)PRESET_LIST)
        return R_NOT_FOUND;
    b->r[0] = LOAD_NAME && *LOAD_NAME ? 4 : fw_streamer_idle(SYSTEM) ? 0 : 5;
    if (b->r[0])
        return R_REFUSED;
    uint32_t msg[6] = {0x18, 0, 0, i, 0, 0};
    fw_app_msg(APP, msg);
    b->r[0] = (int32_t)i;
    return R_OK;
}

/* 0x07 presets (the list's index, -1 for none): r0 the count, r1 1 while a load is pending, r2 the card's file commands
   queued; r3 1 with the name at +0x200 when the index is in the list */
static int job_presets(volatile struct kit_box *b)
{
    uint8_t *d = data_area(b);
    if (!d) {
        b->r[0] = 6;
        return R_REFUSED;
    }
    b->r[3] = b->arg[0] >= 0 && fw_preset_name(PRESET_LIST, (uint32_t)b->arg[0], (char *)d + D_NAME);
    b->r[0] = *(volatile int32_t *)PRESET_LIST;
    b->r[1] = LOAD_NAME && *LOAD_NAME;
    b->r[2] = (int32_t)(CMD_WRITE - CMD_READ);
    return R_OK;
}

/* ---- a restart (x6 §7): stock 3.1.9 never resets itself in software, so the kit does it as b2load.c and fault.c do,
   SYSRESETREQ behind a dsb, from the card task between two file command steps (no FatFs call half done), and only
   while stock is idle on the card and nothing is being recorded. Not found yet: a flag that says a take is being
   written to the card, so it refuses while the transport plays or REC is held. ---- */
/* why stock is not idle: 0 it is; 1 the transport plays, 2 REC held, 3 file commands queued, 4 a preset load pending,
   5 the streamer busy */
static int busy(void)
{
    const uint8_t *clock = CLOCK;
    if (clock && clock[0x38])
        return 1;
    if (clock && clock[0x128d4])
        return 2;
    if (CMD_READ != CMD_WRITE)
        return 3;
    if (LOAD_NAME && *LOAD_NAME)
        return 4;
    return fw_streamer_idle(SYSTEM) ? 0 : 5;
}

/* 0x4f restart ("REST" = 0x52455354 as a check): answered 0, then the unit resets; -4 with busy()'s reason in r0 */
static int job_restart(volatile struct kit_box *b)
{
    if ((uint32_t)b->arg[0] != 0x52455354u)
        return R_ARG;
    if (b->file_open)
        return R_STATE;                            /* the kit's own file first: close it (0x44) */
    int why = busy();
    if (why) {
        b->r[0] = why;
        return R_REFUSED;
    }
    reply(b, R_OK, b->seq);                        /* answered first: SDRAM keeps it through the reset, and the next */
    DCCMVAC = (uint32_t)b;                         /* boot's count makes the request stale (-2), so it never runs twice */
    DCCMVAC = (uint32_t)b + 0x20u;
    __asm__ volatile("dsb");
    AIRCR = (0x5fau << 16) | (1u << 2);            /* SYSRESETREQ */
    for (;;)
        ;
}

static const job_fn JOBS[KIT_JOBS] = {
    [0x00] = job_info,
    [0x01] = job_row,
    [0x02] = job_row,
    [0x03] = job_knob,
    [0x04] = job_touch,
    [0x05] = job_tap,
    [0x06] = job_preset,
    [0x07] = job_presets,
    [KIT_CANCEL] = job_cancel,
    [0x20] = job_button,
    [0x40] = job_open,
    [0x41] = job_rw,
    [0x42] = job_rw,
    [0x43] = job_seek,
    [0x44] = job_close,
    [0x45] = job_stat,
    [0x46] = job_list,
    [0x47] = job_delete,
    [0x4f] = job_restart,
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
    unsigned run = b->run;
    if (run && (task != KIT_SCREEN || seq == b->run_seq))
        return KIT_NONE;                           /* a job spans passes: its own request waits for its end, and the */
    barrier();                                     /* box is the screen task's until then (finish) */
    unsigned index = b->index;
    if (index >= KIT_JOBS || !JOBS[index])
        return task == KIT_SCREEN ? R_INDEX : KIT_NONE;
    if (run && index != KIT_CANCEL) {              /* any task's job, meanwhile: not now */
        b->r[0] = (int32_t)run;
        return R_BUSY;
    }
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
        if (b->run)                                /* a job spanning passes: one step, then what is new (kit_gate) */
            step(b);
    }
    if (task == KIT_CARD)
        card_upkeep(b);
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
