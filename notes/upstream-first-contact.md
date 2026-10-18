# Upstream first contact — the message for Thomas to send (draft, 2026-10-18)

To Justin (j3threejay/blackbox-mod), as a new **issue** on his repo. **Thomas edits and sends it**; nothing here is
posted by a session. Re-check before sending: upstream `main` (rc4 = 66329ad when written), the six branches below on
`Maigre/blackbox-mod` (pushed?), and that PR #2 is closed (it is, with the MPU note, 17/10). The 15/10 outline it
replaces is on `37loop/blackbox-t-006`.

---

**Title:** From the Maigre fork: six small PRs ready on rc4, and the Clip Window — how would you like them?

Hi Justin,

Thomas here (Mk1 owner, fork [Maigre/blackbox-mod](https://github.com/Maigre/blackbox-mod)). Thanks for rc4: it
replaced my PR #2 cleanly (closed, with a note on the MPU's Device-memory regions in case it helps with "why some
units"), and it runs on my unit, the one that looped at the logo.

I have six small, independent branches, each cut from your `main` at rc4, in your layout (`src/`, `patches/`,
`test_*.py`, README bullet), each passing `./check.sh` on its own:

1. **`fix/b2load-readonly`** — `B2LOAD_WRITE=0` doesn't build on `main` (`tries`, `tries_set`, `restart` unused under
   `-Werror`). Two `#if` lines; the default build is byte-identical; the read-only build links and `test_b2load.py`
   passes in that mode.
2. **`fix/preview-cell`** — the browser's pre-listen voice is no pad: pad 2's input, insert and LFO retrigger no longer
   leak into a pre-listen. +64 B of bank 1.
3. **`fix/usbdev-debug`** (dev builds only, release image byte-identical) — the DEBUG peek / poke bounded to whole
   memory regions (a 64-byte peek at 0x38800FD8 read 0x38801000, past backup SRAM, and bus-faulted my unit), and EP0
   IN flushed on a new SETUP (after a host-side timeout the abandoned reply stayed in TX FIFO 0 and every later
   reply was the previous request's). The allowed list is narrow (memories, LTDC, RCC_RSR) and commented on how to
   widen it.
4. **`fix/waveform-labels`** — the Waveform screen's four corner labels are palette 9 (#666666) over the cyan
   waveform (#09D7F5): about 3.3:1, hard to read. White with a 1 px black edge, every pad mode, same font and names
   (stock's own label draw, nine passes inset by a pixel). +264 B of bank 1.
5. **`feat/linux-dev`** — build and test on Linux: no clang needed, and `test_machine.py`'s S950 Lo checks pass on a
   CPU without FMA (tolerance 1e-5); Ghidra paths from the environment.
6. **`feat/munchi-bank2`** — Munchi's engine moved to bank 2, its glue left in bank 1: **6.4 KB of bank 1 back**
   (4 120 → 10 562 B free on rc4). Output bit-identical — 27 s of scripted Munchi (wand both sides, random, freeze,
   clock, width, duck, tempo changes, type switches), every sample, against rc4 built here and against your published
   rc4 image — with a fingerprint test so it stays that way. It also fixes `MUNCHI_OFF`, which on rc4 clears the
   delay lines under the stock delay every block. The trade-off is yours to judge: Munchi then needs `BBEXTRA.BIN`
   (without it the Type reads "---" and the slot plays the stock delay, as Confetti does).

**The bigger one, the Clip Window** (per pad, on Clip pads, saved with the preset, inert at defaults): **Slip**
(move the loop against the clock, ±4 beats in ticks, a knob with a detent on 0), **Region** Auto / File / Loop (a
Clip pad plays its loop points, live, synced — no Trim step), **Loop Len** (a KP3-style beat repeat on the grid),
**Fit** (a loop cut by ear plays an exact number of beats at the tempo, polymetric when that's no whole bar), **Loop
Fade** on a region, the Clip-mode Waveform knobs, and a playhead that shows the frame heard. Measured on my unit to
the sample over two test sessions. About 3 KB of bank 1 (hooks and their stock calls) and 4 KB of bank 2 (the maths).

Three questions:

1. **Parameter ids:** it uses `0x1c8`–`0x1cb` (free in 3.1.9, the gap between your `0x1c7` and `0x1d0`). Could you
   reserve `0x1c8`–`0x1cf` for it, or name the range you prefer?
2. **Shape:** one PR as a five-commit series (Slip → Region → Loop Len → Fit → Loop Fade, each commit building and
   passing), or a stack of five PRs?
3. **Order and pace:** shall I open the six small ones now, one PR each, or one at a time as you review?

Also, if useful: my unit (rev V) is free for your release candidates, and the fork's USB bench tools (peek, record,
screenshots, MIDI-driven test runs) can come upstream if you want them.

Thanks for JOEBOX,
Thomas

---

## Before sending (for Thomas)

- The six branches must be on `Maigre/blackbox-mod` (pushed 18/10 if this line says so) so the links work.
- "Measured on my unit over two test sessions": Gate 2 (Slip, 15/10) and Gate 3 / 3b (16–17/10); part 2 of 3b
  (browser, SD at seams, a real song) is still to run — fine to send before.
- Left out on purpose: the Looper (Gate 4 not run), MIDI (a plan under review), the colour theme (D-015a, parked).
