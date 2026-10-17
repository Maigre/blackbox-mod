# This fork: blackbox-mod 37.x (Maigre/blackbox-mod)

Thomas's fork of [JOEBOX](https://github.com/j3threejay/blackbox-mod) — the unofficial feature mod for the original
1010music Blackbox (Mk1, stock firmware 3.1.9) — aimed at two things the stock unit cannot do:

1. **A loop cut by ear from an unsynced recording, played in sync and set into the groove**: Clip pads get *Slip*
   (shift the loop against the clock, live), *Region* (play the Sample-mode loop points instead of the whole file — no
   destructive Trim), *Loop Len* (loop a window of 1/16 … 4 bars where the music is), *Fit* (the loop made a whole
   number of beats at the tempo, polymetric when it is no whole number of bars) and *Loop Fade* on a region (the
   loop point crossfaded, as in Sample mode).
2. **A KP3-style looper on the XY page**: touch catches the bar that was playing, X sets the loop length, Y an HPF,
   lifting the finger returns to the live signal.

Everything JOEBOX 1 has stays (D-011). Every feature is built so that it can go back to JOEBOX as its own pull request,
in JOEBOX's layout and conventions; the maintainer chooses what he takes.

Same rules as upstream: no 1010music firmware, images, disassembly or manuals in this repository. You bring your own
stock 3.1.9 `BLACKBOX.bin`; the build patches your copy.

## Versions

`37.<feature step>.<build>` on the Tools page; dev builds carry a `d` (`37.1.1d`) and add the USB debug peek/poke
(src/usbdev.c), never in a release. `src/release.h` holds both names. Release notes, with each release's sha256:
[`notes/releases/`](notes/releases/37.3.1.md).

| version | adds | where |
|---|---|---|
| 37.0.1 | JOEBOX 1 under the fork's name | `maigre` |
| 37.0.2 | the **restart-loop fix** (JOEBOX 1's hold: an LDREXB on patch RAM, which stock's MPU maps as Device memory — D-013) | `maigre`; upstream **PR #2** |
| 37.1.x | **Slip** on Clip pads; the knob: single ticks slow, 1/64 fast, stops on 0; + = ahead like a CDJ jog; then the **stale-latch fix** (a new file under a playing slipped pad reads as stock until the next segment latches it) | branch `37loop/blackbox-t-004` (lands on `maigre` after review); upstream branch `feat/slip` |
| 37.2.0 | **Region**, **Loop Len** and the **Clip-mode waveform knobs** on Clip pads, with the two fixes: the stale latch (37.1.x's, ported) and the **pre-listen cell** (the browser's pre-listen voice, cell 0x401, is no pad: pad 2's input, insert and LFO retriggers stay off it). Needs this build's `BBEXTRA.BIN` (Loop Len runs from bank 2, D-017) | branch `37loop/blackbox-t-018`, stacked on `37loop/blackbox-t-004`; lands on `maigre` after Gate 3 |
| 37.2.1 | the **Slip knob v2**: a detent on 0 instead of a wall, a medium step between single ticks and 1/64 | branch `37loop/blackbox-t-021`, on 37.2.0 |
| 37.3.0 | after Gate 3 part 1 on the unit: the Clip Window's maths moved to bank 2 (D-018: Slip and Region need `BBEXTRA.BIN` too); the **Gate 3 fixes** (short Waveform knob names, Region Auto without Loop Mode, no endless hold of a grown region, Loop Len taken once the knob rests, the Waveform's real file length, a pad the browser left stuck recovers); the **Slip knob v3** (one smooth curve, a longer detent after a slow approach); **Fit** and **Loop Fade** on Clip pads (D-026). Needs this build's `BBEXTRA.BIN` | branch `37loop/blackbox-t-021`, lands on `maigre` after Gate 3b |
| 37.3.1 | the Waveform screen's **readable corner labels**: white with a 1 px black edge in every pad mode (stock's grey read 3.3:1 on the cyan). Bank 1 only: 37.3.0's `BBEXTRA.BIN` pairs with it | branch `halo`, on 37.3.0; merged into `37loop/blackbox-t-021` at the next occasion |
| — | **Looper FX** (P4) | branch `feat/looper` (local, kept apart until Gate 3) |

## Upstream pull requests (one feature each, from upstream `main`)

The branch model is D-019: `main` mirrors upstream; each feature's PR branch below is that feature's source of truth;
`maigre` is upstream + every feature as if accepted + the fork's own layer (`notes/`, `bench/`, this file, the 37.x
names), moved only by merges. When a PR is accepted, upstream's `main` is merged in and wins every conflict
(`notes/dev-setup.md`).

| branch | what | state |
|---|---|---|
| `fix/restart-loop-ldrex` | the restart-loop fix + a no-exclusives check in test_cpu.py | open: j3threejay/blackbox-mod#2 |
| `feat/linux-dev` | build and test on Linux / hosts without clang or FMA; Ghidra paths from the environment; `check.sh` exit status | ready (PR text prepared, Thomas opens it) |
| `feat/slip` | Slip on Clip pads (src/clipwin.c, test_clipwin.py) + the stale-latch fix: 2 commits | ready (PR text prepared, Thomas opens it) |
| `fix/preview-cell` | JOEBOX's insert and LFO retrigger took the browser's pre-listen voice (cell 0x401) for pad 2 | ready (Thomas opens it) |

## Build, install, bench

- Build and test: [`notes/dev-setup.md`](notes/dev-setup.md) (Linux, no root: Arm GNU 14.2, a Python venv, Ghidra 12 +
  a JDK 21). `./check.sh` must print `N suites, 0 failed`.
- Install: copy the patched `BLACKBOX.bin` (and `BBEXTRA.BIN` when a build has one) to the card root, hold BACK + INFO
  while powering on, on the unit's normal power supply. Back to stock the same way with 1010music's file.
- Bench over USB: [`bench/bbusb.py`](bench/bbusb.py) — the power jack of a modded unit is a USB device: audio of
  Outs 1–3 (measure a feature in samples), MIDI, and on dev builds the memory (the crash recorder, the Clip Window's
  state). Gate reports: [`notes/bench/`](notes/bench/).

## Where things are

- [`notes/`](notes/README.md) — the plan, the decisions (`notes/decisions.md`), the reverse-engineering notes
  (`notes/re/`, prose + addresses), feature docs (`notes/features/`), bench reports.
- Tasks, bench cards and the project log live in Thomas's hub (37Projects, project `blackbox`), not here.
