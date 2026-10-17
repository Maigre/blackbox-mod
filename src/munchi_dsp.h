/* Munchi Delay's engine (munchi_dsp.cpp, in flash bank 2) as the delay slot's glue (munchi.cpp, in the cave) calls
   it. The glue reads the settings and moves the audio in and out through stock; everything in between is up there. */
#pragma once
#include <stdint.h>

#define MUNCHI_MAXN 128                  /* frames in one block, at most (the glue clamps to it) */

/* The settings as the store holds them: Wand / Random / Feedback 0..1000, Freeze / Clock / Width / Duck list indexes */
struct munchi_params {
    int32_t wand, random, feedback, freeze, clock, width, duck;
};

#ifdef __cplusplus
extern "C" {
#endif
/* The state in line 2, (re)started on the two 16-bit lines when it is not Munchi's already; 0: the lines cannot hold
   it. Then one block: the settings, the clock, n frames of the send in, the wet out in *wl / *wr (inside the state). */
void *munchi_ready(void *st, uint32_t st_floats, int16_t *live, uint32_t live_floats, int16_t *frozen, uint32_t frozen_floats,
                   int fresh);
void munchi_block(void *state, const struct munchi_params *p, float bpm, const float *il, const float *ir, int n,
                  const float **wl, const float **wr);
#ifdef __cplusplus
}
#endif
