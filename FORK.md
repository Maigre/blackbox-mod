# This fork: blackbox-mod 37.x (Maigre/blackbox-mod)

Thomas's fork of [JOEBOX](https://github.com/j3threejay/blackbox-mod) — the unofficial feature mod for the original
1010music Blackbox (Mk1, stock firmware 3.1.9) — aimed at two things the stock unit cannot do:

1. **A loop cut by ear from an unsynced recording, played in sync and set into the groove**: Clip pads get *Slip*
   (shift the loop against the clock, live), *Region* (play the Sample-mode loop points instead of the whole file — no
   destructive Trim) and *Loop Len* (loop a window of 1/16 … 4 bars where the music is).
2. **A KP3-style looper on the XY page**: touch catches the bar that was playing, X sets the loop length, Y an HPF,
   lifting the finger returns to the live signal.

Everything JOEBOX 1 has stays (D-011). Every feature is built so that it can go back to JOEBOX as its own pull request,
in JOEBOX's layout and conventions; the maintainer chooses what he takes.

Same rules as upstream: no 1010music firmware, images, disassembly or manuals in this repository. You bring your own
stock 3.1.9 `BLACKBOX.bin`; the build patches your copy.

## Versions

`37.<feature step>.<build>` on the Tools page; dev builds carry a `d` (`37.1.1d`) and add the USB debug peek/poke
(src/usbdev.c), never in a release. `src/release.h` holds both names.

| version | adds | where |
|---|---|---|
| 37.0.1 | JOEBOX 1 under the fork's name | `maigre` |
| 37.0.2 | the **restart-loop fix** (JOEBOX 1's hold: an LDREXB on patch RAM, which stock's MPU maps as Device memory — D-013) | `maigre`; upstream **PR #2** |
| 37.1.x | **Slip** on Clip pads; the knob: single ticks slow, 1/64 fast, stops on 0; + = ahead like a CDJ jog | branch `37loop/blackbox-t-004` (lands on `maigre` after review); upstream branch `feat/slip` |
| 37.2.x | **Region** and **Loop Len** on Clip pads, Clip-mode waveform knobs | branch `feat/region` (in progress) |
| — | **Looper FX** (P4) | branch `feat/looper` (in progress, kept apart until 37.2 is benched) |

## Upstream pull requests (one feature each, from upstream `main`)

| branch | what | state |
|---|---|---|
| `fix/restart-loop-ldrex` | the restart-loop fix + a no-exclusives check in test_cpu.py | open: j3threejay/blackbox-mod#2 |
| `feat/linux-dev` | build and test on Linux / hosts without clang or FMA; Ghidra paths from the environment; `check.sh` exit status | ready (PR text prepared, Thomas opens it) |
| `feat/slip` | Slip on Clip pads (src/clipwin.c, test_clipwin.py) | ready (PR text prepared, Thomas opens it) |

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
