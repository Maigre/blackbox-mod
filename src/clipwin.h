/*
 * Clip Window (clipwin.c): what bank 1 and bank 2 (clipwin_b2.c) share - the class-B pad's fields both read, the
 * knob's, and the state they keep in SDRAM. Bank 2 is compiled against this file, and the asserts at the end pin every
 * offset the cw_* functions read or write, so that moving one is a deliberate act: it makes a new bank 2 payload, and a
 * unit then needs this build's BBEXTRA.BIN. Until the card loader has written it every bank 2 feature (Prism, Confetti,
 * the inserts, and all of the Clip Window) is off, because bank 1 pairs with the whole payload at once, on its sum
 * (cpu.c, b2_live). Bank 2's id does not hash this file (build.sh): an edit here that leaves bank 2's bytes alone (a
 * comment, a field appended to cw_bank, a define bank 2 does not use) needs no reflash.
 */
#ifndef CLIPWIN_H
#define CLIPWIN_H
#include <stddef.h>
#include <stdint.h>

/* class-B pad ('L', vtable 0x080d0890) */
#define PAD_CLASS   0x04             /* u8 0x4c */
#define PAD_ID      0x18             /* u32 row << 8 | col; bank << 16 (0 for the pads) */
#define PAD_SOURCE  0x24
#define PAD_ON      0x29             /* u8 Clip or Slicer mode active */
#define PAD_HARD0   0xba1            /* u8 1 = Attack (0x3c) is 0: stock starts every step 0 without a fade-in */
#define PAD_TPS     0x208            /* i64 ticks per step */
#define PAD_STEPS   0x210            /* u32 steps n */
#define PAD_SLICER  0x254            /* u8 */
#define SEG0        0x30
#define SEG_SIZE    0x70
#define SEG_POS     0x08
#define SEG_END     0x10             /* i64 the frame it stops on (the last step: its file's length - 1), 0 none */
#define SEG_FRAC    0x1c
#define SEG_DELAY   0x20
#define SEG_FADE_IN 0x24             /* i32 fade-in samples left (256 when made), then +0x28 the countdown to the fade-out */
#define FADE_IN     256              /* stock's step crossfade, in and out (0x080656ba, 0x08065700) */
#define SEG_FIRST   0x3c
#define SRC_BAD     0x10000000       /* fw_src_len's "the provider reported 0 frames" */
/* the knob's stepper (notes/re/a3, at knob + 0x270): + 0 i64 accumulated counts, the counts per step, the index, the
   start (the value = index + start) */
#define STEPPER_STEP  0x08
#define STEPPER_INDEX 0x0c
#define STEPPER_START 0x18
/* the settings */
#define SLIP_MAX    3840             /* Slip's range, +- one bar of ticks */

struct cw_latch {
    int32_t rs, vlen, delta;         /* what is read circularly (the whole file: 0, its length) and the shift, frames */
    int32_t len;                     /* fw_src_len when latched: the file the shift was made for */
};

struct cw_bank {
    uint32_t magic, scan;
    int32_t slip[16];                /* as last polled */
    uint8_t *pad[16];                /* the engine's pad object, cached by H1 */
    uint8_t valid[16];               /* bit k: latch[q][k] holds */
    struct cw_latch latch[16][4];
    uint8_t h1[16];                  /* bit k: slot k's segment was made through H1 (not a slice segment, H1') */
    uint8_t hinted[16];              /* bit k: H2 has hinted rs for slot k's crossing of the file's end */
    uint32_t zero_at;                /* the Slip knob: GUI ms a turn last arrived on 0 (the detent counts from there) */
    int8_t zero_dir;                 /* ...and the direction that turn was going, */
    uint8_t zero_slow;               /* ...and 1 if it was slow (its hold is ZERO_DETENT_SLOW_MS, cw_turn) */
    uint8_t spare_4be[0x262];        /* room: no field after it moves */
    int16_t knob_counts;             /* the Slip knob's last turn event: its counts, */
    uint8_t knob_speed;              /* ...and the accelerator's speed for it (1 .. 6): a bench read */
    uint8_t spare_723[0x155];        /* room: no field after it moves */
    uint8_t fin[16];                 /* bit k: slot k's segment starts inside the audio: its first read gives back the
                                        fade-in stock takes from a hard start (cw_latch, cw_slot) */
    uint8_t spare_888[0x20];         /* room: the bank's size stays */
};
#define CW_MAGIC  0x43574e42u        /* "CWNB": bumped with the layout (SDRAM keeps its contents through a reset) */
#define CW_OFFSET (0x56800u + 0x2d100u)   /* master.c: PRISM_BYTES + 0x2d100, where this bank begins */
#define CW_BYTES  0x1000u            /* what master.c's EXTRA_BYTES gives the bank */
_Static_assert(sizeof(struct cw_bank) <= CW_BYTES, "master.c's EXTRA_BYTES gives the bank CW_BYTES");
_Static_assert(CW_OFFSET == 0x56800u + 0x2d100u, "master.c: PRISM_BYTES + 0x2d100, cleared in master_alloc");
_Static_assert(offsetof(struct cw_bank, zero_at) == 0x4b8 && offsetof(struct cw_bank, zero_dir) == 0x4bc &&
               offsetof(struct cw_bank, zero_slow) == 0x4bd &&
               offsetof(struct cw_bank, knob_counts) == 0x720 && offsetof(struct cw_bank, knob_speed) == 0x722 &&
               offsetof(struct cw_bank, fin) == 0x878 &&
               sizeof(struct cw_bank) == 0x8a8,
               "test_clipwin.py reads the knob's fields here");

/*
 * clipwin_b2.c, in bank 2: the maths and the policy of every hook. Call only when b2_live() holds (clipwin.c's
 * bank() asks it); each is leaf code, and clipwin.c makes every stock call they need.
 */
int cw_pad(const uint8_t *pad);      /* 0 .. 15 for one of the sixteen pads, else -1 */
/* H1: latch slot k, return where to prefetch (pos < 0: from the segment's own start); H1': a slice segment in slot k */
int32_t cw_latch(struct cw_bank *b, unsigned q, unsigned k, uint8_t *pad, int32_t len, int32_t pos);
void cw_slice(struct cw_bank *b, unsigned q, unsigned k);
/* H2: the latch of the segment whose fraction is at frac (0: none, read as stock); its real position for pos; 1 = hint
   rs now */
const struct cw_latch *cw_slot(struct cw_bank *b, unsigned q, const uint8_t *pad, float *frac);
int32_t cw_map(const struct cw_latch *l, int32_t pos);
int cw_hint(struct cw_bank *b, unsigned q, const struct cw_latch *l, int32_t real);
/* the poll: bit 0 = drop and remake the pending segments (cw_drop: the slots to latch again), bit 2 = the cached pad is
   pad q's (cw_retire may look at its segments, len = fw_src_len of its source) */
int cw_tick(struct cw_bank *b, unsigned q, int32_t slip);
unsigned cw_drop(const struct cw_bank *b, unsigned q, uint8_t *pad);
void cw_retire(uint8_t *pad, int32_t len);
/* the Slip knob: 0 = no move, else *add for the stepper; its text (at most 13 bytes) */
int cw_turn(struct cw_bank *b, const uint8_t *stepper, int counts, unsigned m, uint32_t now, int32_t *add);
void cw_text(char *t, int v);

/* what the cw_* functions are compiled against (no code: the compiler checks them). Changing one reprograms bank 2. */
_Static_assert(offsetof(struct cw_bank, slip) == 0x8 && offsetof(struct cw_bank, pad) == 0x48 &&
               offsetof(struct cw_bank, valid) == 0x88 && offsetof(struct cw_bank, latch) == 0x98 &&
               sizeof(struct cw_latch) == 16 && offsetof(struct cw_latch, vlen) == 4 &&
               offsetof(struct cw_latch, delta) == 8 && offsetof(struct cw_latch, len) == 12 &&
               offsetof(struct cw_bank, h1) == 0x498 && offsetof(struct cw_bank, hinted) == 0x4a8,
               "bank 2 (the cw_* functions) is compiled against these cw_bank offsets: moving one reprograms bank 2");
_Static_assert(SEG0 == 0x30 && SEG_SIZE == 0x70 && SEG_POS == 0x08 && SEG_FRAC == 0x1c && SEG_DELAY == 0x20 &&
               SEG_FADE_IN == 0x24 && FADE_IN == 256 &&
               SEG_FIRST == 0x3c && SEG_END == 0x10 && PAD_TPS == 0x208 &&
               PAD_STEPS == 0x210 && PAD_CLASS == 0x04 && PAD_ID == 0x18 && PAD_ON == 0x29 &&
               PAD_HARD0 == 0xba1 && PAD_SLICER == 0x254,
               "bank 2 (the cw_* functions) is compiled against these pad and segment offsets: changing one reprograms "
               "bank 2");
_Static_assert(STEPPER_STEP == 0x08 && STEPPER_INDEX == 0x0c && STEPPER_START == 0x18 && SLIP_MAX == 3840 &&
               SRC_BAD == 0x10000000,
               "bank 2 (cw_turn, cw_tick, cw_latch) is compiled against the knob's fields and these settings and "
               "values: changing one reprograms bank 2");

#endif
