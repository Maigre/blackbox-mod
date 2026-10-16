/*
 * Clip Window (clipwin.c): what bank 1 and bank 2 (clipwin_b2.c) share - the class-B pad's fields both read and the
 * state they keep in SDRAM. Bank 2 is compiled against this file, and the asserts at the end pin every offset bank 2
 * reads, so that moving one is a deliberate act: it makes a new bank 2 payload, and a unit then needs this build's
 * BBEXTRA.BIN. Until the card loader has written it every bank 2 feature (Prism, Confetti, the inserts, Loop Len) is
 * off, because bank 1 pairs with the whole payload at once, on its sum (cpu.c, b2_live). Bank 2's id does not hash
 * this file (build.sh): an edit here that leaves bank 2's bytes alone (a comment, a field appended to cw_bank, a define
 * bank 2 does not use) needs no reflash.
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
#define H_LOOP_MODE 0x108
#define SEG0        0x30
#define SEG_SIZE    0x70
#define SEG_POS     0x08
#define SEG_FRAC    0x1c
#define SEG_DELAY   0x20
#define SEG_STEP    0x34
#define SEG_FIRST   0x3c
#define SRC_BAD     0x10000000       /* fw_src_len's "the provider reported 0 frames" */

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

/* clipwin_b2.c, in bank 2 (call only when b2_live()): Loop Len's window for a segment H1 makes */
#define CW_NO_WINDOW ((int32_t)0x80000000)
int32_t cw_window(const struct cw_bank *b, unsigned q, const uint8_t *pad, unsigned k, int32_t clip);

/* what cw_window is compiled against (no code: the compiler checks them). Changing one reprograms bank 2. */
_Static_assert(offsetof(struct cw_bank, origin) == 0x5c0 && offsetof(struct cw_bank, ll) == 0x600,
               "bank 2 (cw_window) is compiled against these cw_bank offsets: moving one reprograms bank 2");
_Static_assert(SEG0 == 0x30 && SEG_SIZE == 0x70 && SEG_POS == 0x08 && SEG_STEP == 0x34 && PAD_FPS == 0x1fc &&
               PAD_TPS == 0x208,
               "bank 2 (cw_window) is compiled against these pad and segment offsets: changing one reprograms bank 2");

#endif
