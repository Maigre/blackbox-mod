/*
 * Crash-safe bank 2 (hub #t-059): the words, b2safe.c the rule. After B2_HOLD boots in a row that ended in a fault or
 * the window watchdog, bank 2 is held off: the next boots run as with no payload, so a payload that pairs cleanly and
 * then kills the unit before USB is up cannot keep it in a reset loop that only BACK + INFO gets out of.
 *
 * TWO WORDS OF BACKUP SRAM, in the hole after b2.h's three (free from 0x388003d4 to comp.c at 0x38800400) and in the
 * same 32-byte cache line as those:
 *   B2_CRASHES  how many boots in a row ended in a crash. B2_HOLD or more = held off.
 *   B2_FAULTED  B2_FAULT_SEEN while a boot is ending in a fault: fault.c's recorder writes it before the reset it asks
 *               for, and the next boot reads it and takes it down. The reset cause cannot tell that reset from a
 *               restart somebody asked for - the recorder's, the card loader's and the bench's are all SYSRESETREQ.
 */
#ifndef B2SAFE_H
#define B2SAFE_H
#include <stdint.h>

#define B2_CRASHES     ((volatile uint32_t *)0x388003d4u)
#define B2_FAULTED     ((volatile uint32_t *)0x388003d8u)
#define B2_FAULT_SEEN  0x31544c46u           /* "FLT1": the fault record's own magic, in a register there already */
#define B2_HOLD        3u
_Static_assert(0x388003d8u + 4u <= 0x38800400u, "the crash words run into comp.c's state at 0x38800400");
_Static_assert((0x388003c8u & ~31u) == (0x388003d8u & ~31u), "the crash words left b2.h's cache line");

/* RCC_RSR as fault.c's instrument_boot reads it, before stock clears it (RM0433; bench/bbusb.py decodes the same) */
#define RSR_BOR        (1u << 21)
#define RSR_POR        (1u << 23)
#define RSR_WWDG1      (1u << 28)

/* Stock's watchdog supervisor, three words at 0x2400a584 (fault.c's WDG_SUP): stamp A, the disk task's (pcmStreamer,
   every pass of its loop), stamp B, the screen task's (every app pass, FUN_080a2258), and its count of audio blocks,
   which FUN_08046994 adds one to in every block - whether it feeds the window watchdog or not. A stamp is a copy of the
   count made by its own task, and the dog is fed only while both are within 3,750 blocks (10 s) of it. All three are
   .bss, so 0 at every reset. Both stamps at B2_GOOD_BLOCKS or more = both tasks were alive after 12,288 blocks of 128
   frames at 48 kHz, 32.8 s; the audio is, since it runs the check. */
#define B2_STAMPS      ((const volatile uint32_t *)0x2400a584u)
#define B2_GOOD_BLOCKS 0x3000u

/* cpu_state.b2chk's last free bit (b2.h lists the others): held off, set with B2_UNPAIRED and B2_LOOKED */
#define B2_HELD        0x80u

void b2_crash_boot(uint32_t rsr);    /* fault.c's instrument_boot, once a boot, with the reset cause */
void b2_crash_uptime(void);          /* cpu.c's meter, every 376 wakes */

/* Is bank 2 held off after crashes. Inline: the meter's start makes no call before the queue wait (each one costs it
   16 bytes of registers kept), and b2_present has the address in a register already. */
static inline int b2_held(void)
{
    return *B2_CRASHES >= B2_HOLD;
}

#endif
