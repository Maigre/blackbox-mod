/*
 * The DJ FX slot setter's case for id 0x18, FX A's type (b.w @0x0806e174, over stock's `cmp r2, #2; bhi`).
 * Entered with r0 the sub-slot, r1 0x18, r2 the index, lr back into the sub-slot's message loop. Index 0..4: latch it
 * (looper.c: looper_latch answers the class, 0x40 for Looper and Loop In) and go on into stock's swap at 0x0806e048,
 * which takes the sub-slot in r0 and the class in r1 and nothing else. Above 4: return, as stock did above 2.
 */
    .syntax unified
    .thumb
    .text

    .global looper_fxa_set
    .thumb_func
    .type looper_fxa_set, %function
looper_fxa_set:
    cmp     r2, #4
    bhi     1f
    push    {r0, lr}
    mov     r1, r2
    bl      looper_latch
    mov     r1, r0
    pop     {r0, lr}
    ldr     r3, =0x0806e049
    bx      r3
1:  bx      lr
    .ltorg
