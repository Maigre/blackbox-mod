/*
 * Clip Window, the part in flash bank 2: Loop Len's take and its window (clipwin.c, notes/re/README.md section 3).
 * Original 1010music Blackbox, firmware 3.1.9.
 *
 * Leaf code: it reads the pad and the bank it is handed and calls nothing outside this file (bank 2 is written once and
 * lives through every bank 1 install, so a branch out of it would go stale: test_bank2.py). It moved here to make room
 * in the bank 1 cave: the window first, then the take when the Waveform knobs came. clipwin.c calls it only when
 * b2_live() says the payload up there is this build's; without it Loop Len stays Off.
 */
#include <stdint.h>

#include "clipwin.h"

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")   /* no memset / memcpy calls out of the bank */

static int32_t fold2(int32_t v, int32_t len)
{
    v %= len;
    return v < 0 ? v + len : v;
}

/* Loop Len on pad q, from clipwin_tick: ll = the row (0 Off, else W = 240 << (ll - 1) ticks), sync = the user's Sync
   (the app's store), force = the pad may have its Sync forced (Quant and Sync not None: without a Quant there is no
   grid, on Sync None no clock phase, and stock's None-to-synced re-grid doubles a step, notes/re/a1; and not sliced).
   Returns 0 while a launch waits for its Quant point: a Sync change re-grids it, and it would sound at once
   (notes/re/a2, droplaunch); the poll comes back in 16 blocks. Else bit 0 = the value moved (the pending steps must be
   made again), bits 8 and up = 1 + the Sync index to send the pad, 0 for none (clipwin.c sends it: the param-set is
   bank 1's). */
int cw_looplen(struct cw_bank *b, unsigned q, const uint8_t *pad, unsigned ll, uint32_t sync, int force)
{
    int live = 0, send = 0;
    for (unsigned k = 0; k < 4; k++) {
        const uint8_t *seg = pad + SEG0 + k * SEG_SIZE;
        if (seg[0] && !seg[1]) {
            if (seg[SEG_FIRST])
                return 0;
            live = 1;
        }
    }
    /* a stopped pad: its next launch takes the window from where it starts, the clip's start, as the first launch
       after power-on does - an in-point does not outlive the playing it was taken from */
    if (!live)
        b->origin[q] = 0;
    int32_t tps = *(const int32_t *)(pad + PAD_TPS);
    int32_t clip = tps * *(const int32_t *)(pad + PAD_STEPS);
    int moved = ll != b->ll[q];
    if (moved) {
        if (!b->ll[q]) {
            /* engaged: where the music is. The sounding segment that started last (the least elapsed since its step's
               first frame, signed: at rate != 1 stock's re-grid puts the step ahead of the position, notes/re/a1)
               gives the phase from the frame it plays: its latch's, Slip taken out, when it has one (it may still
               play an earlier window, after Off), else stock's position; in ticks, x tps / fps. The window is the W
               around it, on the grid. */
            int32_t least = 0x7fffffff;
            uint32_t ph = 0;
            float fps = *(const float *)(pad + PAD_FPS);
            for (unsigned k = 0; k < 4 && tps > 0 && fps > 0.0f; k++) {
                const uint8_t *seg = pad + SEG0 + k * SEG_SIZE;
                int32_t pos = (int32_t)*(const int64_t *)(seg + SEG_POS);
                int32_t e = pos - (int32_t)((float)*(const uint32_t *)(seg + SEG_STEP) * fps);
                if (seg[0] && !seg[1] && *(const int32_t *)(seg + SEG_DELAY) <= 0 && e < least) {
                    least = e;
                    if (b->valid[q] & (1u << k)) {
                        const struct cw_latch *l = &b->latch[q][k];
                        pos = fold2(fold2(pos, l->vlen) + l->delta - b->sf[q][k], l->vlen);
                    }
                    ph = (uint32_t)((float)pos * (float)tps / fps);
                }
            }
            uint32_t W = 240u << (ll - 1);
            b->origin[q] = (int32_t)(ph - ph % W);
        }
        b->ll[q] = (uint8_t)ll;
        if (!ll && b->forced[q]) {
            b->forced[q] = 0;            /* Off: the user's Sync back */
            if (sync <= 6)
                send = (int)sync + 1;
        }
    }
    /* a window the steps do not divide: force the largest Sync (1 bar .. 1/16, idx 1 .. 5) that divides it, its
       in-point and the clip, starting from the user's (the store's), which wins when it divides them: then a forced
       Sync is given back as soon as it no longer needs to be (a longer window). Sent when the pad's differs: again if
       something moved it (the app re-sending Sync). */
    int32_t W = ll ? 240 << (ll - 1) : 0, o = b->origin[q];
    if (W && W < clip && (W % tps || o % tps || b->forced[q]) && force) {
        uint32_t idx = sync - 1 < 5 ? sync : 1;
        int32_t t = 3840 >> (idx - 1);
        while (t > 240 && (W % t || o % t || clip % t)) {
            t >>= 1;
            idx++;
        }
        if (*(const int32_t *)(pad + PAD_SYNC) != t) {
            send = (int)idx + 1;
            b->forced[q] = idx != sync;
        }
    }
    return send << 8 | moved;
}

/* Loop Len's window for the segment H1 makes in slot k (clipwin.c's latch, when Loop Len is taken), clip = ticks per
   step x steps (0 without a clip): what to add to the frame stock starts it on so that it plays the window's step that
   lines up with its own, w = (origin + ((j x tps - origin) mod W)) / tps, played as stock plays a step: its first frame
   is stock's float product (int)((float)w x fps), truncated (a tick-domain formula is a frame off on a non-integer fps,
   notes/re/a2). CW_NO_WINDOW for none: Off, a window of the whole clip or more, or one the steps or the in-point do not
   divide (the poll forces the Sync for those, cw_looplen). */
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
