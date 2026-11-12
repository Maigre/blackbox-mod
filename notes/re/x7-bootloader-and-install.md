# X7 — the bootloader and the install path (blackbox#t-058)

Thomas's Mk1 (STM32H743 rev V), its bootloader read off the unit on 2026-11-12 through the dev build's bounded peek:
bank 1's first two sectors, `0x08000000–0x0803FFFF` (the dump stays on the dev box, `/srv/dev/firmware/unit-dumps/`,
sha256 `9343d292…`). Read 2026-11-12 in its own Ghidra project and with `arm-none-eabi-objdump` on the raw file; the
app's side from stock 3.1.9's exports. Nothing was tried on the unit.

Marks: ✓ = the bootloader's own code run under Unicorn (scratch harnesses, see "How this was checked"); *static* =
read twice (decompile and disassembly of the same bytes); *inferred* = a reasoning step past what was read.

## Short answers

1. **How it chooses.** Two GPIO levels and the app's first 128 bytes, nothing else. Right after reset it reads PC2
   and PC3 once (GPIOC IDR, no debounce) and scans `0x08040000–0x0804007F` for a word that is not `0xFFFFFFFF`. Both
   pins high (no button held) and one such word → it jumps to the app. Otherwise it stays, and the first pass of its
   screen loop starts the installer if PC3 (INFO) is low at that moment, or its factory test pages if not. No backup
   SRAM, no RTC backup register, no reset-cause flag, no RAM word, no file name takes part. ✓ High confidence.
2. **Before the jump** it checks nothing more: no checksum, no size, no version, no sanity of the stack pointer or the
   reset vector. One non-blank word anywhere in the 128-byte window is enough (✓: a blank reset vector with one word at
   `0x0804007C` jumps to `0xFFFFFFFF`). High confidence.
3. **The install.** It looks for `BLACKBOX.BIN` at the root of the SD card, erases **bank 1 sectors 2–7 and bank 2
   sectors 0–6, on every install whatever the file's size**, programs the file from `0x08040000` in file order (into
   bank 2 if it is longer than 786,432 B, never past `0x081DFFE0`), reads it back against flash and restarts. No
   check of the file's content, and a card read error is taken for the end of the file (§4.2). **It never touches
   bank 2 sector 7** (the factory calibration) and never bank 1 sectors 0–1 (itself). ✓ High confidence on the code;
   the bank 2 erase disagrees with one bench line (§4.3).
4. **It never updates itself.** The only erases in the dump are the installer's two and the calibration's one (bank 2
   sector 7); no path writes below `0x08040000`. ✓ / *static*. High confidence.
5. **No buttonless path through the stock bootloader.** Its only input the app could influence would have to survive a
   reset and be read before the decision; nothing it reads does (§6). Short of wiring the INFO button, an install
   with no hands needs code of our own. High confidence.
6. **Our own updater** is possible from the app, the way `b2load.c` writes bank 2, but it rewrites the bank it runs
   from: it must run from ITCM with interrupts off, have the whole file in SDRAM first, feed the window watchdog, and
   write the 128-byte vector window last (§7). What only hands repair: anything in bank 1 sectors 2–7. What nothing
   short of a debug probe repairs: bank 1 sectors 0–1 and the option bytes. **Recommendation: keep the hands** (§8).

Side findings: **INFO alone starts the installer** (✓ in the code, never tried); the bootloader's MPU region 3 is
the Device mapping under JOEBOX's patch RAM in D-013 (§5); a `BLACKBOX.bin` whose length is 29, 30 or 31 modulo 32
fails the installer's verify in the model unless 1–3 particular bytes of it are `0xFF` (§4.2); a card read error
part way through can end in "Success!" with a partial app (§4.2).

## 1. What is in the dump

- 103,384 B used, `0x08000000–0x080193D7`; the rest of sector 0 and all of sector 1 (`0x08020000–0x0803FFFF`) are
  blank. Vectors: stack `0x24044628`, reset `0x0800051F`; the reset handler sets its own stack (`0x24080000`) and VTOR
  (`0x08000000`), copies `.data` from `0x08019340`, zeroes `.bss`, runs ten constructors (`0x080181F4–0x0801821C`),
  then `main` at `0x08000FB4`.
- Its asserts name the project `BBBL` (`C:\Projects\Code\matrixsw2\BBBL\Src\…`: SDMgr, MidiPort, AnalogInput,
  AudioDriverBoombox, I2CPortBoombox, usbh_conf). Three RTOS tasks with the app's names: defaultTask, audioTask
  (priority 3), pcmStreamer, plus a USB host thread.
- **Version `1.0.22`** (`0x08018AA8`), drawn only on the first factory test page ("Pot Input Test:  1.0.22",
  `0x08015794`). D-013's "bootloader file 1.7.F on the card" matches nothing in the dump or in stock 3.1.9; where that
  name was read is not known to this note.
- Three screens: the installer, eleven factory test pages, and a calibration procedure (§3).

## 2. Boot: the app or the bootloader

`main` (`0x08000FB4`), in order, before it decides (*static*, and ✓ by the log of every peripheral address the run
touched):

1. GPIO ports A–K clocked (RCC AHB4ENR `0x580244E0`); 13 pins set as inputs with no pull and 12 as outputs, from two
   tables a constructor builds (`0x24000DE4`, `0x24001494`; `0x08001544`); the PC2 and PC3 analog switches closed
   (SYSCFG PMCR `0x58000404`, bits 26–27).
2. The MPU programmed and enabled (`0x08000E1C`, 13 regions, PRIVDEFENA; table in §5).
3. `GPIOC->IDR & 4` (PC2) and `& 8` (PC3), read at `0x08000FC6` and `0x08000FD0` by the HAL's read-pin `0x0800DC1C`.
4. The scan of `0x08040000–0x0804007F` for a word other than `0xFFFFFFFF`.
5. If PC2 = 1, PC3 = 1 and a word was found: `blx` to the word at `0x08040004` (`0x08000FF6`). Otherwise on into the
   bootloader (`0x08000FF8`).

✓ The truth table, 16 runs from the reset vector (pins × app present / blank / one word at `0x0804007C` / one word
at `0x08040080`, just outside the window): it jumps only with both pins high and a word inside the window, and with
one word at `0x0804007C` and a blank reset vector it jumps to `0xFFFFFFFF`. The pins are read once each; nothing
else is read before the jump: the run touched only the AXI interconnect (`0x51008108`), SYSCFG, the GPIO ports'
configuration, GPIOC IDR and RCC. No RTC or backup register (`0x58004000`), no backup SRAM (`0x38800000`), no RCC_RSR
(`0x580244D0`), no PWR, no flash controller, nothing in bank 2. The dump's literal pools hold none of those addresses
at all (*static*).

**What the app inherits**: the bootloader's stack (the app's reset loads its own, `0x24080000`, and sets VTOR to
`0x08040000` itself), the HSI clock (the PLL and the tick are set up after the decision, `0x0800EE44` / `0x08000C78`),
both caches off (the I-cache is enabled after the decision, `0x08001008`; the bootloader never enables its D-cache),
no interrupt source enabled, and the GPIO, analog-switch and MPU settings above with the MemManage fault enabled. ✓
The only core registers the run wrote before the jump are VTOR, CPACR (the FPU), FPDSCR, the MPU's and SHCSR's
MemManage enable: no NVIC enable, no SysTick, no CCR.

**Which pin is which.** PC3 is INFO: the calibration's "Then press Info" waits on PC3 (`0x08016284` → `0x08015D00`).
PC2 is BACK by elimination: the manual says BACK + INFO and these are the only two pins read (*inferred*). The app
reads the same two pins in its own button table (the entries written at `0x080456C4` and `0x080456EC`: PC2 → key 7,
PC3 → key `0x0C`; *static*). **Either button alone keeps the bootloader.**

## 3. Inside the bootloader: installer, test pages, calibration

defaultTask (`0x08000C1C`, not marked as a function by Ghidra's auto-analysis) calls the screen-loop step
`0x08015D34` forever, on a 0xA78-byte UI object built by `0x08015650`.

- **The first pass decides.** The constructor sets a one-shot flag (`+0xA1C`); on the first pass the step reads PC3
  (`0x08015D00`) and, if low, sets `+0xA1D` = 1: the installer. The flag is then cleared and nothing sets it again. ✓
  (the step run on a fresh object): PC3 low → "Blackbox Installer", whatever PC2; PC3 high → test page 0; a second
  pass with both pins low does not start the installer.
- So: **BACK + INFO or INFO alone → installer; BACK alone → factory test pages; no button and no app → factory test
  pages.** The installer starts only if INFO is still held when the screen loop first runs, after the RTOS and the
  display are up; the manual's "hold until you see Blackbox Installer" covers that.
- **Factory test pages**: the order is the table at `0x08018CDC` (pages 0, 2, 4–12), INFO steps to the next. The
  strings name them: Pot Input (with the version), CV Input, Brightness, Touchscreen, MIDI Input, Clock, MIDI TRS A/B
  loopback, Audio Sinewave / Loopback, and the **SD Card Test at 25 / 50 / 100 MHz, which writes and reads back a
  1 MB `TESTDATA.BIN` at the card root on every pass** while the page shows (`0x08003994`). No page leads back to the
  app: a power cycle does.
- **Calibration**: on the Clock Test page, INFO held 121 polls 16 ms apart (about 2 s, *static*) starts it (`+0xA28`);
  each step asks for a +5 V DC signal on an input, or to adjust an output to +5.00 V, then "Then press Info". At the
  end ("Calibration Complete") it **erases bank 2 sector 7 and writes 224 B at `0x081E0000`** (`0x08004AFC`, magic
  `0x1234ABCD`), retrying until it succeeds. It is the only code in the dump that touches sector 7. At every boot both
  the bootloader (`0x08004AD4`) and the app (`0x080416D8`) copy 0xE8 B from there if the magic is present, "No
  Calibration. Using defaults" otherwise. Reaching it takes BACK alone at power-on, four INFO presses and a 2-s hold.

## 4. The installer

### 4.1 The steps

The state machine `0x08015BDC` shows each message for 60 passes of the screen loop before running its step (the
loop's rate was not measured; the manual says the whole install takes about 15 s). ✓ (the machine run with its four
steps stubbed): a good install takes 480 passes and ends in a reset; no file → "Unable to find firmware." for 300
passes, then a reset (the old app, untouched, starts if no button is held); a failed erase, program or verify →
its message forever, no reset.

| step | where | what (✓ for the flash ranges: the steps run with FatFs stubbed and the flash controller as plain registers) |
|---|---|---|
| search | `0x080047EC` | `f_stat` then `f_open` (read) of `"BLACKBOX.BIN"` (`0x08018534`) at the card root. Only the SD card (SDMMC1, `0x52007000`) is linked to FatFs: no USB stick. FatFs matches the name in any case (*inferred*). The size used later is the directory entry's |
| erase | `0x08004948` → `0x080048EC` | unlock both banks, clear both banks' error flags, then two sector erases: **bank 1 sectors 2–7** (`0x08040000–0x080FFFFF`), then **bank 2 sectors 0–6** (`0x08100000–0x081DFFFF`). Unconditional |
| program | `0x08004998` | 32 KB reads into AXI SRAM `0x24029320`, each programmed as 256-bit flash words from `0x08040000` on, in file order (the vectors first), the last chunk rounded up to 32 B with whatever the buffer held. At `0x08100000` it waits for bank 1, clears both banks' flags and goes on into bank 2. `0x0800495C` writes no word above `0x081DFFE0`: past it the rest is dropped and the step still reports success. `f_read`'s return code is never looked at (`0x080049D0`): a read that delivers 0 bytes ends the step with success, and each chunk is programmed over the length asked for, not the length delivered |
| verify | `0x08004834` | reopen, reread in 32 KB chunks, compare byte for byte from `0x08040000`. The same two gaps (`0x08004878`): a read that delivers 0 bytes ends the verify with success, and a chunk is compared over the length asked for |
| done | `0x08015608` | "Success! Restarting.", 180 passes, `NVIC_SystemReset`. The next boot decides as in §2: with a button still held it is the bootloader again |

Every size run (728,696 B = stock 3.1.9, 784,448, 786,432, 786,507, 786,508, 1,703,936, 1,704,000, 0, 31): the same 13
sector erases, bank 1 sectors 0–1 and bank 2 sector 7 byte for byte as before. ✓

### 4.2 What it does not check, and its edges

- **No content check.** Any file named `BLACKBOX.BIN` is erased over and programmed: a truncated download, a WAV with
  the wrong name. ✓ A 0-byte file passes all four steps ("Success!") and leaves bank 1 erased: the next boot finds
  no app and shows the factory test pages.
- **A card read that fails part way through.** Neither the program nor the verify looks at `f_read`'s return code;
  both take a read that delivers no bytes for the end of the file and report success. ✓ (`fixcheck.py`, a 728,696 B
  file, FatFs's error sticking after the first failure): a failure at chunk 5 in both passes → "Success! Restarting."
  with only the first 163,840 B in flash; a failure half way through chunk 5 in both passes → "Success!" with that
  chunk's second half programmed from stale buffer bytes; a failure in the program pass only → "Unable to verify.";
  a failure in the verify pass only, or earlier in it than in the program pass → "Success!". So the verify catches a
  short program pass only when its own reads get further. A card that fails at the same place, or earlier, on the
  second read leaves a partial app behind a success message: the next boot jumps into it, and hands repair it.
- **A file over 786,432 B** (`0xC0000`) spills into bank 2 sector 0; ✓ in the model it programs and verifies (75 and
  76 B over). `src/cave.ld` records that JOEBOX's 3.1.G, 76 B over, failed "unable to verify" on a unit: this read
  does not explain that. Either way `cave.ld`'s cap stays right: a tail in bank 2 sector 0 is a foreign payload to
  `b2load.c`, which then leaves the effects off.
- **A file over 1,703,936 B** is cut at `0x081DFFE0` and fails the verify. ✓ Sector 7 stays intact.
- **The verify's tail.** For a last chunk whose length is not a multiple of 4, the compare runs 4 bytes past it
  (`0x0800487C`). The bytes up to the next 32-byte boundary were programmed from the same stale buffer the verify
  sees again, so they match. For a length ≡ 29, 30 or 31 (mod 32), 1–3 compared bytes lie past that boundary: erased
  flash (`0xFF`) against stale buffer bytes, which for a file over 32 KB are the file's own bytes 32,768 B before the
  boundary (the previous chunk's, at the same buffer offset). Such a file fails "Unable to verify." **unless those
  1–3 bytes happen to be `0xFF`**. ✓ In the model, of 64 sizes with random bytes (every residue modulo 32, twice),
  exactly the ≡ 29, 30 and 31 fail; the same three sizes with those bytes set to `0xFF` verify (`fixcheck.py`).
  **A prediction, never seen on a unit.** Stock 3.1.9 is ≡ 24. A fork image is stock + the cave, so it is safe while
  the cave's size is not ≡ 5, 6 or 7 (mod 32) (37.4.1's release cave, 50,954 B, is ≡ 10). A build-time check on the
  image's length closes it without changing a byte; padding the image to a multiple of 32 B would too.
- **A cut install.** Power lost before the first chunk is programmed: no app, the factory test pages. After it: the
  vectors are there, so the bootloader jumps into a partial app. Both need hands, and hands always work: the
  installer never erases the bootloader.

### 4.3 Bank 2, and what it means for the fork (a conflict to settle)

By this read **every BACK + INFO install erases bank 2 sectors 0–6**: `BBEXTRA.BIN`'s payload and `b2load.c`'s claim
word at `0x081C0000` (sector 6) included. The next boot's card loader then finds bank 2 blank, claims it again (the
same claim word), rewrites it from `BBEXTRA.BIN` and restarts once; with no `BBEXTRA.BIN` on the card, the effects
stay off and TOOLS shows "!". Back to stock leaves bank 2 sectors 0–6 blank.

That disagrees with the fork's own record in five places: `b2load.c`'s header ("The SD installer writes bank 1
only"), `emu.py`'s comment (bank 2 "the hardware keeps … across bank 1 installs"), the README and release notes ("when
a release changes the second file, the first boot installs it"; 37.3.2: "from 37.3.1 … no restart"), D-030 ("no
rewrite at install"), and the one bench line that observed it, Gate 3 part 1 (2026-10-16): "Installing 37.2.1d over
it (BLACKBOX.bin only, same `BBEXTRA.BIN`): paired at once, no rewrite." Every other recorded install restarted once,
but each of those also changed the second file, so they cannot tell. The bank 2 header reads the same after a rewrite
of the same payload; only the self-restart or boot 2's reset cause (SOFTWARE) tells a rewrite from none. The code is
read twice and run, and the bench line is one observation of something hard to see; this note does not settle it.
The bench check is in §9.

## 5. The app's side

- **Stock 3.1.9 never names the bootloader** (*static*, from its exports): no literal in `0x08000000–0x0803FFFF`, no
  system reset of its own (its only AIRCR write is the priority grouping at `0x08078BA4`), no RTC backup register, no
  backup SRAM (the fork's `od.c` found it unused). It clears RCC_RSR's flags (`0x08046956`) when it starts the window
  watchdog, which the bootloader never reads anyway. Its SystemInit sets VTOR to `0x08000000`, then its reset handler
  sets `0x08040000`.
- **The fork** resets with SYSRESETREQ (`fault.c`, `b2load.c`) and keeps its state in backup SRAM; the bootloader
  reads neither.
- **The MPU handover.** ✓ The bootloader leaves 13 regions:

  | region | base, size | type |
  |---|---|---|
  | 0 | `0x20000000` DTCM, 128 KB | Normal WB, shareable, XN |
  | 1, 2 | `0x24000000` 256 KB, `0x24040000` 64 KB | Normal WB, XN |
  | **3** | **`0x24050000`, 64 KB** | **Device (TEX 0, C 0, B 1), XN** |
  | 4, 5 | `0x24060000`, `0x24070000`, 64 KB each | Normal WB, XN |
  | 6 | `0x30000000` SRAM1–3, 512 KB | Normal WB, XN |
  | 7 | `0x08000000` flash, 2 MB | write-through, executable |
  | 8 | `0xC0000000` SDRAM, 64 MB | Normal WB, XN |
  | 9, 10 | `0x40000000` 512 MB, `0x60000000` 8 KB | Device, XN |
  | 11, 12 | `0x1FF0F000` 8 KB, `0x10040000` 64 KB | Normal WB, XN (12 shareable) |

  The app's `0x0804409C` (called once from its `main`) rewrites only regions 4 and 5 (Device), 8 (SDRAM) and 9
  (`0x30000000`, 512 KB) (*static*). **Regions 0–3, 6, 7, 10–12 stay the bootloader's.** D-013's bus fault was at
  `0x2405FFF3`, inside region 3: the Device mapping under JOEBOX's patch RAM comes from bootloader 1.0.22, not from
  the app. A unit whose bootloader leaves region 3 unset would map `0x24050000–0x2405FFFF` by the default map (Normal
  memory), where an LDREXB works: a candidate for D-013's open "why other units survive" (*inferred*: no other
  bootloader has been read).
- Every RAM region the two set is XN (the app's four too, *static*). Code runs only from flash (region 7) and from
  the RAM no region covers, by the default map: ITCM at `0x00000000` (stock's startup copies nothing there, *static*),
  SRAM4 at `0x38000000` and backup SRAM.

## 6. No buttons: is there a path?

No. ✓ / *static*: the decision is two GPIO levels read right after reset, and the installer one more read of PC3.
What the app could try, and why it fails:

- Leave a word in RAM, backup SRAM or an RTC register: never read (§2).
- Drive PC3 low before a reset: a system reset puts every GPIO back in its reset state (*inferred*, STM32H7 reset
  scheme), and the bootloader sets the pin up as an input itself.
- Erase the app's vectors: the bootloader stays, but on its test pages; the installer still wants INFO at the first
  pass. A unit left like that needs hands.
- Jump into the bootloader past its decision: it reinitialises the whole machine and reads PC3 again at the first pass.
- Call its install steps from the app: they depend on its own FatFs, SD driver and RAM layout, which overlap the app's.

## 7. What our own updater would need

A design, not a fact. The app rewriting bank 1 itself, the way `b2load.c` writes bank 2:

- **Stage everything before the first erase.** Read the new `BLACKBOX.bin` from the card into SDRAM (stock's FatFs,
  from the pcmStreamer task, as `b2load.c` does; ~1.49 MB of SDRAM is free on a paired unit, D-013 / X2) and check it
  there: at most 786,432 B, its id and sum (the fork's images carry them), a stack pointer in RAM and a reset vector
  inside `0x08040000–0x080FFFFF`. A card error then costs nothing.
- **Commit from ITCM.** Bank 1 sectors 2–7 hold the running app, its vectors and its fault handlers; any fetch from
  bank 1 during an erase stalls, and after it there is nothing there. The flasher is copied to ITCM (with SRAM4, the
  only RAM the MPU lets execute, §5), interrupts are masked, and from then on it touches no flash code, no literal
  pool and no stock function; it ends with a reset.
- **Feed the window watchdog** inside every wait: stock's WWDG1 (`0x50003000`, prescaler /128, counter and window
  `0x7F`, `fault.c`) cannot be stopped once started, and 64 of its ticks of about 5 ms (`fault.c`) make about a third
  of a second (*inferred*), far less than a 128 KB sector erase. A refresh is one register write and is allowed at
  any time with that window.
- **Order, so that a cut leaves the benign state.** Erase sector 2 first (the vectors go: a cut from here on leaves
  "no app" and the bootloader's test pages, not a crash loop into a half app), then sectors 3–7; program 3–7, then
  sector 2 from `0x08040080` on, verify each against SDRAM with the data cache invalidated over flash (region 7 is
  cacheable and the app runs with the D-cache on); **program the 128-byte window `0x08040000–0x0804007F` last**, verify,
  lock bank 1, reset. The same rule as `b2load.c`'s header-last.
- **Only bank 1 sectors 2–7.** A hard check on every sector number and bank before each erase; never bank 1 sectors
  0–1, never bank 2 sector 7, never the option-byte registers (`FLASH_OPTKEYR` / `OPTCR`). Leave bank 2 alone: the
  card loader pairs it on the next boot.
- **Tests first**: under Unicorn with the flash controller modelled (as `test_b2load.py` does), a fault on any fetch
  from `0x08000000–0x081FFFFF` during the commit, a cut at every step, and an image of each bad shape refused before
  the first erase.

What can go wrong, and what repairs it:

| failure | state left | repaired by |
|---|---|---|
| power cut, watchdog reset or fault during the commit | bank 1 sectors 2–7 partly written; with the order above, no app (test pages) | **hands**: INFO (or BACK + INFO) at power-on with a good `BLACKBOX.bin` on the card |
| a good-looking wrong image | an app that crashes at every boot | **hands**, the same |
| a bug that erases or writes bank 1 sector 0 or 1 | no bootloader: BACK + INFO no longer exists | **nothing on the unit**: a debug probe on SWD, or the STM32 ROM loader with BOOT0 (the case opened) |
| a write to the option bytes (RDP, BOOT_ADD, SWAP_BANK, write protection) | the unit boots elsewhere or locks; RDP level 2 is permanent | **nothing**, or a probe |
| an erase of bank 2 sector 7 | defaults instead of the factory trims, no crash | hands plus instruments: the bootloader's calibration (§3) |

The stock installer has the same exposure in the first two rows, and a worse cut state: it writes the vectors first.

## 8. Recommendation

**Keep the hands.** No buttonless path exists through the stock bootloader, and the one we could build adds a failure
with no repair on the unit (row 3 above) to save a two-finger hold at power-on. Hands are needed after a failed install
either way. Build the updater only for a real unattended need (an automated bench), from §7, first on the bench unit
with a known-good `BLACKBOX.bin` on the card. Cheaper and worth doing now (*design*): a build-time check that
`BLACKBOX.bin`'s length is not ≡ 29, 30 or 31 (mod 32) (§4.2), and correct the fork's wording on bank 2 once §9's
check has settled §4.3.

## 9. Open

- **Bank 2 at install** (§4.3): at the next install with an unchanged `BBEXTRA.BIN`, watch for the self-restart and
  read boot 2's reset cause: SOFTWARE means the installer had erased bank 2. Or peek `0x08100000` before and after
  the install screen, before the first boot (the card loader cannot run in between).
- **BACK alone at power-on** should show "Pot Input Test:  1.0.22" with no flash write: it proves PC2 = BACK and the
  version. Leave by power cycle; do not step to the SD Card Test pages (they write `TESTDATA.BIN`) nor hold INFO on
  the Clock Test page (calibration).
- INFO alone starting the installer: in the code, never tried.
- A card read error ending in "Success!" (§4.2): the code run in the model with FatFs stubbed; never seen on a unit.
- The option bytes (write protection of sectors 0–1, RDP, boot addresses, bank swap) are not in the dump; the dev
  build's peek does not reach the flash registers (`0x52002000`). Not read.
- JOEBOX's 3.1.G "unable to verify" at 76 B over (§4.2); the name "1.7.F" (§1).
- The screen loop's rate, hence the installer's real timing, was not measured.

## How this was checked

- Ghidra project `/srv/dev/firmware/ghidra-boot` (`mk1boot`, imported at `0x08000000` by a scratch copy of
  `ghidra/import.py`; 822 functions, 36 more created by hand at task entries and pointer targets). Query tool and
  exports in `/srv/dev/firmware/re-scratch/w1/boot/` (`bq.py`, `out_boot.c`, `objdump.txt`, `strings.txt`); never in
  the clone.
- The app: `/srv/dev/firmware/ghidra-out` (`listing.txt`, `out_all.c`) for the MPU setup, the button table, the
  calibration load, the watchdog and the absence of any reference to the bootloader's range.
- Unicorn, the dump's own code (`/srv/dev/firmware/re-scratch/w1/boot/emu/`): `bootrun.py`, from the reset vector to
  the jump or to `0x08000FF8`, the 16-case truth table, the MPU registers written, every peripheral address touched;
  `uirun.py`, the screen-loop step on a UI object built by its own constructor (4 pin cases) and the installer's
  state machine for five outcomes; `flashrun.py`, the real erase / program / verify functions with FatFs stubbed and
  every sector erase logged, 9 sizes and 64 residues. Their outputs: `truth.txt`, `ui.txt`, `flash.txt`,
  `residues.txt` there.
- A second reader's review the same day led to §4.2's card read error and the tail's dependence on the image's bytes.
  Each was reproduced before it went in. `fixcheck.py` (output `fixcheck.txt`): the program and verify steps with
  chosen file bytes and card read failures, the verify's tail with the stale bytes `0xFF` or not and six read-failure
  cases.
