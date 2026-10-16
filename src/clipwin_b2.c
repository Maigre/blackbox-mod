/*
 * Clip Window, the part in flash bank 2: Loop Len's window (clipwin.c, notes/re/README.md section 3). Original 1010music
 * Blackbox, firmware 3.1.9.
 *
 * Leaf code: it reads the pad and the bank it is handed and calls nothing outside this file (bank 2 is written once and
 * lives through every bank 1 install, so a branch out of it would go stale: test_bank2.py). It moved here to make room
 * in the bank 1 cave. clipwin.c calls it only when b2_live() says the payload up there is this build's; without it
 * Loop Len stays Off.
 */
#include <stdint.h>

#include "clipwin.h"

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")   /* no memset / memcpy calls out of the bank */

static int32_t fold2(int32_t v, int32_t len)
{
    v %= len;
    return v < 0 ? v + len : v;
}

/* Loop Len's window for the segment H1 makes in slot k (clipwin.c's latch, when Loop Len is taken), clip = ticks per
   step x steps (0 without a clip): what to add to the frame stock starts it on so that it plays the window's step that
   lines up with its own, w = (origin + ((j x tps - origin) mod W)) / tps, played as stock plays a step: its first frame
   is stock's float product (int)((float)w x fps), truncated (a tick-domain formula is a frame off on a non-integer fps,
   notes/re/a2). CW_NO_WINDOW for none: Off, a window of the whole clip or more, or one the steps or the in-point do not
   divide (the poll forces the Sync for those). */
int32_t cw_window(const struct cw_bank *b, unsigned q, const uint8_t *pad, unsigned k, int32_t clip)
{
    unsigned ll = b->ll[q];
    int32_t tps = *(const int32_t *)(pad + PAD_TPS), o = b->origin[q];
    int32_t W = ll ? 240 << (ll - 1) : 0;
    if (!W || W >= clip || W % tps || o % tps)
        return CW_NO_WINDOW;
    const uint8_t *seg = pad + SEG0 + k * SEG_SIZE;
    uint32_t w = (uint32_t)(o + fold2((int32_t)*(const uint32_t *)(seg + SEG_STEP) * tps - o, W)) / (uint32_t)tps;
    return (int32_t)((float)w * *(const float *)(pad + PAD_FPS)) - (int32_t)*(const int64_t *)(seg + SEG_POS);
}
