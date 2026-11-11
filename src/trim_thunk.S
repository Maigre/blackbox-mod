/*
 * Trim on a Clip pad (trim.c): the File menu's Trim enable, bl FUN_080BD566(menu, 0x124, on) @0x080B3620 in
 * FUN_080B3194 case 0x127. r6 = the pad's cell, r7 = 0 when the highlighted file is the pad's own (strcmp at
 * 0x080B35E4), [sp, #4] = MultiSam (0xEA); sp is the caller's at the bl. Anything else: stock's enable, untouched.
 */
    .syntax unified
    .thumb
    .text

    .global trim_menu_b
    .thumb_func
    .type trim_menu_b, %function
trim_menu_b:
    cbnz    r7, 1f
    ldr     r3, [sp, #4]
    cbnz    r3, 1f
    mov     r3, r6
    b.w     trim_menu
1:  ldr     r12, =0x080bd566 + 1
    bx      r12

/* FUN_080A0DD4 @0x080A0FD0, the write request (host, asset, meta, path): r6 = the cell, [sp, #0x10] = trim; trim_write
   takes them as its fifth and sixth arguments */
    .global trim_write_b
    .thumb_func
    .type trim_write_b, %function
trim_write_b:
    push    {r4, lr}
    ldr     r12, [sp, #0x18]
    sub     sp, #8
    str     r6, [sp]
    str     r12, [sp, #4]
    bl      trim_write
    add     sp, #8
    pop     {r4, pc}
    .ltorg
