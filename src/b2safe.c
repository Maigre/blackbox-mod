/*
 * Crash-safe bank 2 (hub #t-059). Original 1010music Blackbox, firmware 3.1.9.
 *
 * THE FAILURE IT IS FOR. Bank 2 holds more and more of the mod's code, and a payload can pair cleanly - this image's
 * id and sum, every flash word read clean - and still crash the unit: a fault, or a hang the window watchdog ends, at
 * every boot, before USB is up. The scan's mark (b2.h) covers only a flash word that cannot be read. Without this the
 * unit loops until somebody holds BACK + INFO; with it, the fourth boot comes up without bank 2.
 *
 * THE RULE.
 *   At every boot (b2_crash_boot, from fault.c's instrument_boot: before any audio block, before the lists ask
 *   b2_present, before stock clears RCC_RSR at 0x0804695e and before the scheduler starts anything that can reach
 *   bank 2's code):
 *     - a power-on or a brown-out (POR, BOR) is not a crash: the count goes to 0, whatever else the register holds;
 *     - a reset by the window watchdog (WWDG1RSTF), or one the fault recorder asked for (B2_FAULTED), is a crash:
 *       the count goes up by one;
 *     - every other reset is not a crash, and the count goes to 0: a pin reset, a restart asked for without a fault
 *       (the card loader's, after it writes bank 2: nothing else in this tree asks for one), the installer's.
 *     B2_FAULTED goes back down either way, so one fault counts once.
 *   During a boot (b2_crash_uptime, from the meter every 376 wakes, about once a second): once the unit has run
 *     B2_GOOD_BLOCKS audio blocks (32.8 s), a count of 1 or 2 goes to 0. Not at boot: a payload that dies at second 5
 *     would never add up. B2_HOLD and over stays: a boot with bank 2 held off proves nothing about the payload.
 *     "Run" means every task the watchdog waits on: the screen and disk tasks' own stamps (b2safe.h) must have
 *     passed B2_GOOD_BLOCKS, not only the audio's count - the count goes on in a task that has stopped feeding the
 *     dog, so a screen task hung at second 25 would clear the count at 32.8 s and be reset at 35 s, a 1 each boot.
 *   A count of B2_HOLD or more = HELD (b2_held):
 *     - cpu.c's start, at the meter's first block, sets b2chk to unpaired, looked and held: nothing runs bank 2 or
 *       reads it (no pairing scan), and the card loader stays out - it could only write the same payload again,
 *       restart, and the count would start over: a loop, and an erase each time round;
 *     - b2_present says there is no payload: the lists read "---", master_alloc takes no tail, no boot graphic;
 *     - Tools reads "!held" where an unpaired bank 2 reads "!" (cpu.c's compose).
 *   A HOLD ENDS with the first reset that is not a crash. A held boot runs no card loader, and nothing here restarts
 *     the unit on request (the USB poke writes RAM, never the SCB), so that is a power-cycle or the installer (BACK +
 *     INFO at power-on): hands either way, with the unit up and on USB meanwhile. A power-cycle gives the payload three
 *     boots again (the test unit's backup SRAM does not even keep the count through one). A NEW payload can only come
 *     with a new BLACKBOX.bin - the loader takes this image's id and sum alone - so through the installer, and the
 *     card loader writes it under a count of 0.
 *
 * ONLY BANK 1 DECIDES. Whatever lives in bank 2 takes no part in deciding whether bank 2 runs: this file, the token in
 * fault.c's recorder and the gate in cpu.c are all in the cave. Every write goes through bkp_put: a write held in the
 * data cache is lost by the very reset it is meant to outlive (fault.c).
 */
#include "b2.h"
#include "b2safe.h"

void b2_crash_boot(uint32_t rsr)
{
    uint32_t n = *B2_CRASHES + 1u;
    if ((rsr & (RSR_POR | RSR_BOR)) || !((rsr & RSR_WWDG1) || *B2_FAULTED == B2_FAULT_SEEN))
        n = 0;
    *B2_FAULTED = 0;                     /* the same cache line as the count: bkp_put cleans both */
    bkp_put(B2_CRASHES, n);
}

void b2_crash_uptime(void)
{
    if (B2_STAMPS[0] >= B2_GOOD_BLOCKS && B2_STAMPS[1] >= B2_GOOD_BLOCKS && *B2_CRASHES - 1u < B2_HOLD - 1u)
        bkp_put(B2_CRASHES, 0);
}
