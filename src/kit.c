/*
 * The bench kit, the part in bank 1 (dev builds only, as usbdev.c's peek and poke; fork-only, D-019). Original 1010music
 * Blackbox, firmware 3.1.9.
 *
 * One gate and the screen task's hook. Everything the kit does is in bank 2 (kit_b2.c: the mailbox, the job table,
 * every job), reached only through kit_poll, and only once b2_live() says bank 2 holds this build's payload and the
 * boot-time SDRAM block is up. kit_poll is called from the three tasks that may run a job:
 *   the screen task - kit_scan below, which replaces the app pass's knob scan (bl FUN_08040724 @0x080a2cd6,
 *                     patches/cpu.py): the scan first, then the kit, so a knob event it posts is drained by stock's
 *                     own loop right after, in the same pass;
 *   the audio task  - usbdev_poll (usbdev.c), between two blocks;
 *   the card task   - b2load_thunk.S, in front of each of the card loop's three file command steps.
 * A release build compiles none of it: no gate, no hook (patches/cpu.py places the hook only when kit_scan exists).
 */
#ifndef PUBLIC_BUILD
#include <stdint.h>

uint8_t *master_block(void);                  /* master.c: the boot-time SDRAM block, or 0 */
int b2_live(void);                            /* cpu.c: may bank 2 be run (this build's payload, read clean) */
void kit_run(unsigned task, uint8_t *block);  /* kit_b2.c, bank 2 */
void kit_knob_scan(void *hw);                 /* FUN_08040724: the knobs' ADC scan, one bl at its fixed address */
__asm__(".global kit_knob_scan\n .thumb_set kit_knob_scan, 0x08040724\n");

/* task: 0 the screen task, 1 the audio task, 2 the card task (kit_b2.c's index ranges) */
void kit_poll(unsigned task)
{
    uint8_t *block = master_block();
    if (block && b2_live())
        kit_run(task, block);
}

/* Replaces bl FUN_08040724 @0x080a2cd6, the app pass's knob scan (usbdev.c's mailbox scan before the bench kit) */
void kit_scan(void *hw)
{
    kit_knob_scan(hw);
    kit_poll(0);
}
#endif
