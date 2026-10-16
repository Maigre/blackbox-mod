/*
 * Clip Window (clipwin.c): what bank 1 and bank 2 (clipwin_b2.c) share - the class-B pad's fields both read, the knob's
 * and the waveform's, and the state they keep in SDRAM. Bank 2 is compiled against this file, and the asserts at the
 * end pin every offset the cw_* functions read or write, so that moving one is a deliberate act: it makes a new bank 2
 * payload, and a unit then needs this build's BBEXTRA.BIN. Until the card loader has written it every bank 2 feature
 * (Prism, Confetti, the inserts, and since D-018 all of Slip, Region and Loop Len) is off, because bank 1 pairs with
 * the whole payload at once, on its sum (cpu.c, b2_live). Bank 2's id does not hash this file (build.sh): an edit here
 * that leaves bank 2's bytes alone (a comment, a field appended to cw_bank, a define bank 2 does not use) needs no
 * reflash.
 */
#ifndef CLIPWIN_H
#define CLIPWIN_H
#include <stddef.h>
#include <stdint.h>

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
#define SEG0        0x30
#define SEG_SIZE    0x70
#define SEG_POS     0x08
#define SEG_END     0x10             /* i64 the frame it stops on (the last step: its file's length - 1), 0 none */
#define SEG_FRAC    0x1c
#define SEG_DELAY   0x20
#define SEG_STEP    0x34
#define SEG_FIRST   0x3c
#define SRC_BAD     0x10000000       /* fw_src_len's "the provider reported 0 frames" */
/* the knob's stepper (notes/re/a3, at knob + 0x270): + 0 i64 accumulated counts, the counts per step, the index, the
   start (the value = index + start) */
#define STEPPER_STEP  0x08
#define STEPPER_INDEX 0x0c
#define STEPPER_START 0x18
/* the waveform widget: the white bracket, i32 Loop Start and End, and whether it is shown; its dirty flag */
#define WAVE_DIRTY  0x32
#define WAVE_LOOP   0x22c
#define WAVE_LOOP_ON 0x239
/* the settings */
#define P_SYNC      0x94             /* stock's Sync: Slice, 1 bar, 1/2, 1/4, 1/8, 1/16, None (0 .. 6, unchecked) */
#define SLIP_MAX    3840             /* Slip's range, +- one bar of ticks */
#define LOOPLEN_MAX 7                /* Loop Len: Off, then 1/16 << (value - 1) up to 4 bars */

struct cw_latch {
    int32_t rs, vlen, delta;         /* the region (v1: the whole file) and the shift, frames */
    int32_t len;                     /* fw_src_len when latched: the file the region and the shift were made for */
};

struct cw_region {
    int32_t rs, vlen;                /* the region the pad plays this pass, frames; vlen 0 = the whole file */
};

struct cw_bank {
    uint32_t magic, scan;
    int32_t slip[16];                /* as last polled */
    uint8_t *pad[16];                /* the engine's pad object, cached by H1 */
    uint8_t valid[16];               /* bit k: latch[q][k] holds */
    struct cw_latch latch[16][4];
    uint8_t h1[16];                  /* bit k: slot k's segment was made through H1 (not a slice segment, H1') */
    uint8_t hinted[16];              /* bit k: H2 has hinted rs for slot k's crossing of the region end */
    uint32_t zero_at;                /* the Slip knob: GUI ms a turn last arrived on 0 (the detent counts from there) */
    int8_t zero_dir;                 /* ...and the direction that turn was going, */
    uint8_t zero_slow;               /* ...and 1 if it was slow (its hold is ZERO_DETENT_SLOW_MS, cw_turn) */
    uint8_t wrap;                    /* 1 + the pad whose wrap is recomputing right now (clipwin_wrap), else 0 */
    struct cw_region region[16];
    int32_t good[16][2];             /* the last loop points from the app's store that made sense (the fallback) */
    int32_t origin[16];              /* Loop Len: the window's in-point, ticks into the clip */
    uint8_t ll[16];                  /* Loop Len as taken (0 Off, else W = 240 << (ll - 1) ticks) */
    uint8_t forced[16];              /* 1: Loop Len has forced the pad's Sync; Off gives the store's back */
    int32_t sf[16][4];               /* Slip's part of latch[q][k].delta, frames (Loop Len's engage takes it out) */
    int16_t knob_counts;             /* the Slip knob's last turn event: its counts, */
    uint8_t knob_speed;              /* ...and the accelerator's speed for it (1 .. 6): bbusb.py knob reads both */
    uint8_t llv[16];                 /* Loop Len as the poll last read it from the store, */
    uint8_t llc[16];                 /* ...and how many polls since it changed (it is taken at LL_SETTLE, cw_tick) */
    int32_t flen[16];                /* fw_src_len at the pad's last recompute (H3 site 1): the Waveform's length */
};
#define CW_MAGIC  0x43574e38u        /* "CWN8": bumped with the layout (SDRAM keeps its contents through a reset) */
#define CW_OFFSET (0x56800u + 0x2d100u)   /* master.c: PRISM_BYTES + the old EXTRA_BYTES, where this bank begins */
_Static_assert(sizeof(struct cw_bank) <= 0x800, "master.c's EXTRA_BYTES gives the bank 0x800");
_Static_assert(CW_OFFSET == 0x56800u + 0x2d100u, "master.c: PRISM_BYTES + 0x2d100, cleared in master_alloc");
_Static_assert(offsetof(struct cw_bank, zero_at) == 0x4b8 && offsetof(struct cw_bank, zero_dir) == 0x4bc &&
               offsetof(struct cw_bank, zero_slow) == 0x4bd &&
               offsetof(struct cw_bank, knob_counts) == 0x720 && offsetof(struct cw_bank, knob_speed) == 0x722 &&
               sizeof(struct cw_bank) == 0x784, "bench/bbusb.py knob and test_clipwin.py read the knob's fields here");

/*
 * clipwin_b2.c, in bank 2: the maths and the policy of every hook (D-018). Call only when b2_live() holds (clipwin.c's
 * bank() asks it); each is leaf code, and clipwin.c makes every stock call they need.
 */
int cw_pad(const uint8_t *pad);      /* 0 .. 15 for one of the sixteen pads, else -1 */
/* H3: the length stock is told at site 0 .. 3; set = the pad's store rows below, read for site 1 only */
#define CW_SET_REGION 0
#define CW_SET_START  1
#define CW_SET_END    2
int32_t cw_len(struct cw_bank *b, unsigned q, uint8_t *pad, int site, int32_t clip, int32_t len, const int32_t *set);
/* H3': after the wrap's recompute, 1 = the region before it (was: rs, vlen, then the wrap grid and the clip, ticks, the
   pad had) is back and the pad must recompute again */
#define CW_WAS_GRID 2
#define CW_WAS_CLIP 3
int cw_hold(struct cw_bank *b, unsigned q, const uint8_t *pad, const uint32_t *t, const int32_t *was);
/* H1: latch slot k, return where to prefetch (pos < 0: from the segment's own start); H1': a slice segment in slot k */
int32_t cw_latch(struct cw_bank *b, unsigned q, unsigned k, uint8_t *pad, int32_t len, int32_t pos);
void cw_slice(struct cw_bank *b, unsigned q, unsigned k);
/* H2: the latch of the segment whose fraction is at frac (0: none, read as stock); its real position for pos, 1 = hint
   rs now */
const struct cw_latch *cw_slot(const struct cw_bank *b, unsigned q, const uint8_t *pad, const float *frac);
int cw_map(struct cw_bank *b, unsigned q, const struct cw_latch *l, int32_t pos, int32_t *real);
/* the poll: bit 0 = drop and remake the pending segments (cw_drop: the slots to latch again), bit 1 = send msg, bit 2 =
   the cached pad is pad q's (cw_retire may look at its segments, len = fw_src_len of its source) */
int cw_tick(struct cw_bank *b, unsigned q, int32_t slip, unsigned ll, uint32_t sync, const void *engine, uint32_t *msg);
unsigned cw_drop(const struct cw_bank *b, unsigned q, uint8_t *pad);
void cw_retire(uint8_t *pad, int32_t len);
/* Loop Len's take (from cw_tick) and its window (from cw_latch) */
int cw_looplen(struct cw_bank *b, unsigned q, const uint8_t *pad, unsigned ll, uint32_t sync, uint32_t *msg);
int32_t cw_window(const struct cw_bank *b, unsigned q, const uint8_t *pad, unsigned k, int32_t clip);
/* the Slip knob: 0 = no move, else *add for the stepper; its text (at most 13 bytes); the Waveform's bracket */
int cw_turn(struct cw_bank *b, const uint8_t *stepper, int counts, unsigned m, uint32_t now, int32_t *add);
void cw_text(char *t, int v);
void cw_bracket(uint8_t *wave, int mode, int32_t ls, int32_t le, int32_t len, int was);

/* what the cw_* functions are compiled against (no code: the compiler checks them). Changing one reprograms bank 2. */
_Static_assert(offsetof(struct cw_bank, slip) == 0x8 && offsetof(struct cw_bank, pad) == 0x48 &&
               offsetof(struct cw_bank, valid) == 0x88 && offsetof(struct cw_bank, latch) == 0x98 &&
               sizeof(struct cw_latch) == 16 && offsetof(struct cw_latch, vlen) == 4 &&
               offsetof(struct cw_latch, delta) == 8 && offsetof(struct cw_latch, len) == 12 &&
               offsetof(struct cw_bank, h1) == 0x498 && offsetof(struct cw_bank, hinted) == 0x4a8 &&
               offsetof(struct cw_bank, wrap) == 0x4be && offsetof(struct cw_bank, region) == 0x4c0 &&
               sizeof(struct cw_region) == 8 && offsetof(struct cw_bank, good) == 0x540 &&
               offsetof(struct cw_bank, origin) == 0x5c0 && offsetof(struct cw_bank, ll) == 0x600 &&
               offsetof(struct cw_bank, forced) == 0x610 && offsetof(struct cw_bank, sf) == 0x620 &&
               offsetof(struct cw_bank, llv) == 0x723 && offsetof(struct cw_bank, llc) == 0x733 &&
               offsetof(struct cw_bank, flen) == 0x744,
               "bank 2 (the cw_* functions) is compiled against these cw_bank offsets: moving one reprograms bank 2");
_Static_assert(SEG0 == 0x30 && SEG_SIZE == 0x70 && SEG_POS == 0x08 && SEG_FRAC == 0x1c && SEG_DELAY == 0x20 &&
               SEG_STEP == 0x34 && SEG_FIRST == 0x3c && SEG_END == 0x10 && PAD_FPS == 0x1fc && PAD_TPS == 0x208 &&
               PAD_STEPS == 0x210 &&
               PAD_SYNC == 0x220 && PAD_CLASS == 0x04 && PAD_SIBLING == 0x08 && PAD_ID == 0x18 && PAD_ON == 0x29 &&
               PAD_LOOP == 0x1f4 && PAD_SYNCED == 0x1f5 && PAD_LAUNCH == 0x1f8 && PAD_STEP_OUT == 0x204 &&
               PAD_WRAP_GRID == 0x230 && PAD_SLICES == 0x250 && PAD_SLICER == 0x254 && LAYER0 == 0x260 &&
               LAYER_SIZE == 0x410 &&
               H_CLASS == 0x48 && H_LOOP_START == 0xfc && H_LOOP_END == 0x100 &&
               offsetof(struct cw_region, vlen) == 4,
               "bank 2 (the cw_* functions) is compiled against these pad, class-H and segment offsets: changing one "
               "reprograms bank 2");
_Static_assert(STEPPER_STEP == 0x08 && STEPPER_INDEX == 0x0c && STEPPER_START == 0x18 && WAVE_DIRTY == 0x32 &&
               WAVE_LOOP == 0x22c && WAVE_LOOP_ON == 0x239 && P_SYNC == 0x94 && SLIP_MAX == 3840 && LOOPLEN_MAX == 7 &&
               SRC_BAD == 0x10000000 && SYNC_SLICE == 0xf0000 && CW_SET_REGION == 0 && CW_SET_START == 1 &&
               CW_SET_END == 2 && CW_WAS_GRID == 2 && CW_WAS_CLIP == 3,
               "bank 2 (cw_turn, cw_bracket, cw_tick, cw_looplen, cw_len, cw_latch, cw_hold) is compiled against the "
               "knob's and the waveform's fields, these settings and values, clipwin_len's row order and "
               "clipwin_wrap's: changing one reprograms bank 2");

#endif
