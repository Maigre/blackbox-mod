/*
 * Clip Window (clipwin.c): the two segment-start hooks. Both replace a `bl FUN_0806375c` (the source prefetch, r0 = src,
 * r1 = position) with a bl to a thunk that adds the segment slot and the pad, then tail-calls C, which ends in the
 * prefetch itself. sp is the caller's at the bl, so the slot is read where the caller keeps it; r4 is the pad at both
 * sites, and the callers reload r2 / r3 before using them again (notes/re/a2, README section 2.2).
 */
    .syntax unified
    .thumb
    .text

/* H1, FUN_08065550 @0x0806578c: the slot is at [sp + 0x20] */
    .global clipwin_seg_start_b
    .thumb_func
    .type clipwin_seg_start_b, %function
clipwin_seg_start_b:
    ldr     r2, [sp, #0x20]
    mov     r3, r4
    b.w     clipwin_seg_start

/* H1', FUN_08065290 @0x0806541a: the slot is at [sp + 4] (stored at 0x0806540c) */
    .global clipwin_slice_start_b
    .thumb_func
    .type clipwin_slice_start_b, %function
clipwin_slice_start_b:
    ldr     r2, [sp, #4]
    mov     r3, r4
    b.w     clipwin_slice_start
