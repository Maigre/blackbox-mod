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

Everything JOEBOX has stays (D-011): since 37.5.0 that is JOEBOX 2. Upstream is merged in as a vendor (D-040): `main`
mirrors it, `maigre` is the product, and the pull requests offered until 12/11 are frozen.

Same rules as upstream: no 1010music firmware, images, disassembly or manuals in this repository. You bring your own
stock 3.1.9 `BLACKBOX.bin`; the build patches your copy.

## Versions

`37.<feature step>.<build>` on the Tools page; dev builds carry a `d` (`37.1.1d`) and add the USB debug peek/poke
(src/usbdev.c), never in a release. `src/release.h` holds both names. Release notes, with each release's sha256:
[`notes/releases/`](notes/releases/37.4.1.md).

| version | adds | where |
|---|---|---|
| 37.0.1 | JOEBOX 1 under the fork's name | `maigre` |
| 37.0.2 | the **restart-loop fix** (JOEBOX 1's hold: an LDREXB on patch RAM, which stock's MPU maps as Device memory — D-013); replaced in 37.3.2 by JOEBOX 1 rc4's own fix (D-027) | `maigre`; upstream **PR #2** (superseded) |
| 37.1.x | **Slip** on Clip pads; the knob: single ticks slow, 1/64 fast, stops on 0; + = ahead like a CDJ jog; then the **stale-latch fix** (a new file under a playing slipped pad reads as stock until the next segment latches it) | branch `37loop/blackbox-t-004` (lands on `maigre` after review); upstream branch `feat/slip` |
| 37.2.0 | **Region**, **Loop Len** and the **Clip-mode waveform knobs** on Clip pads, with the two fixes: the stale latch (37.1.x's, ported) and the **pre-listen cell** (the browser's pre-listen voice, cell 0x401, is no pad: pad 2's input, insert and LFO retriggers stay off it). Needs this build's `BBEXTRA.BIN` (Loop Len runs from bank 2, D-017) | branch `37loop/blackbox-t-018`, stacked on `37loop/blackbox-t-004`; lands on `maigre` after Gate 3 |
| 37.2.1 | the **Slip knob v2**: a detent on 0 instead of a wall, a medium step between single ticks and 1/64 | branch `37loop/blackbox-t-021`, on 37.2.0 |
| 37.3.0 | after Gate 3 part 1 on the unit: the Clip Window's maths moved to bank 2 (D-018: Slip and Region need `BBEXTRA.BIN` too); the **Gate 3 fixes** (short Waveform knob names, Region Auto without Loop Mode, no endless hold of a grown region, Loop Len taken once the knob rests, the Waveform's real file length, a pad the browser left stuck recovers); the **Slip knob v3** (one smooth curve, a longer detent after a slow approach); **Fit** and **Loop Fade** on Clip pads (D-026). Needs this build's `BBEXTRA.BIN` | branch `37loop/blackbox-t-021`, lands on `maigre` after Gate 3b |
| 37.3.1 | at Gate 3b: the Waveform screen's **readable corner labels** (white with a 1 px black edge in every pad mode; stock's grey read 3.3:1 on the cyan); the **playhead** line on the frame heard (H5: Region, Slip, Loop Len, Fit); **Loop Len's settle** 0.3 s (7 polls, was 4). Needs this build's `BBEXTRA.BIN` | branch `halo`, on 37.3.0; merged into `37loop/blackbox-t-021` at the next occasion |
| 37.3.2 | 37.3.1 on **JOEBOX 1 rc4** (upstream `19d29f1`, D-027): the restart-loop fix is upstream's own `b2_step` now (our PR #2 superseded); USB with the compressor on Limit (usbdev's state off the Limit lookahead); the insert models' new names (Pebble, Electra, Jet). Bank 2 unchanged: 37.3.1's `BBEXTRA.BIN` pairs with it. The dev build (37.3.2d) fits: its dev-only code made smaller, same behaviour, the release build unchanged (D-027) | branch `rc4-sync` (local), `halo` + upstream `main` |
| 37.3.3 | Gate 3b F-a: **a step 0 inside the audio fades in** (at Attack 0, stock's default, stock starts each pass's step 0 and each launch hard; slipped, on a Region past frame 0, in Loop Len's window or on a seamless wrap that clicked or doubled: it now gets stock's 256-sample fade-in at its first read, its timing unchanged; D-028). Needs this build's `BBEXTRA.BIN` (bank 2 changed: one restart at the first boot) | branch `rc4-sync` (local), on 37.3.2 |
| 37.4.0 | 37.3.3 + **Munchi's engine in bank 2** (`feat/munchi-bank2`, D-029): 6.4 KB of bank 1 back for the Looper and MIDI, Munchi's output bit for bit rc4's. Munchi now needs this build's `BBEXTRA.BIN` (bank 2 changed: one restart at the first boot) | branch `rc4-sync` (local), on 37.3.3 |
| 37.4.1 | after Gate 3b part 4: **a take loaded into a playing Clip pad plays its own window** (F-p: the pad's Sync sent again after the open when its step came from the closed slot); **Fit's two Autos**, Auto (Bars) and Auto (Beats) (D-031: a saved Auto loads as Auto (Bars)); **the Waveform view goes to the marker you turn**; the boot SDRAM block core first (D-030). Needs this build's `BBEXTRA.BIN` (bank 2 changed: one restart at the first boot). **Gate 3 passed on 37.4.1d** (21/10): the Clip Window is proven on the unit | `maigre` |
| 37.5.0 | 37.4.1 on **JOEBOX 2** (upstream `da84b1b`; D-036 to D-038): the Clip Window's ids at `0x150..0x154` (saved presets load as before); on a Clip pad a Region wins and, with none, JOEBOX 2's selection plays; ChopShop's bodies in bank 2. **Crash-safe bank 2** (D-043): if bank 2 crashes the unit three boots in a row, the fourth comes up without it and Tools reads « !held »; a power-cycle or the next install gives the payload its three boots again; the card loader writes the same `BBEXTRA.BIN` twice per power-on at most. Dev builds: the **bench kit** (D-045), jobs a computer sends over USB, so a session can turn a knob, press a button, load a preset, move files on the card, restart and take a screenshot with nobody at the unit. **On the unit since 12/11** (`notes/bench/2026-11-12-37.5.0d.md`): it boots, the Clip Window measures as on 37.4.1d, the kit and the crash-safe hold are proven with no hands; the listening sitting is still owed. Needs this build's `BBEXTRA.BIN` | `maigre` |
| — | **Looper FX** (P4) | branch `feat/looper` (on origin, built, never on a unit): next, now that Gate 3 has passed |

## Upstream pull requests (one feature each, from upstream `main`)

**Frozen since 2026-11-12 (D-040).** No PR or issue got an answer, so the PRs below stay open upstream but are no
longer kept up to date, and nothing new is cut as a PR: `maigre` is the product, `main` mirrors JOEBOX, and his
releases are merged in. What follows is the record of what was offered.

The branch model is D-019: `main` mirrors upstream; each feature's PR branch below is that feature's source of truth;
`maigre` (the fork's default branch on GitHub since 18/10) is upstream + every feature as if accepted + the fork's
own layer (`notes/`, `bench/`, `README.md`, this file, the 37.x names), moved only by merges. When a PR is accepted, upstream's `main` is merged in and wins every conflict
(`notes/dev-setup.md`).

| branch | what | state |
|---|---|---|
| `fix/restart-loop-ldrex` | the restart-loop fix + a no-exclusives check in test_cpu.py | **closed** 17/10: superseded by JOEBOX 1 rc4's own fix (`19d29f1`, `b2_step` under PRIMASK; D-027), with a note handing over the MPU observation (j3threejay/blackbox-mod#2) |
| `fix/b2load-readonly` | `B2LOAD_WRITE=0` (the read-only card loader) compiles again; the default build byte for byte the same | **PR #6** (opened 20/10, `d046828`) |
| `fix/preview-cell` | the browser's pre-listen voice (cell 0x401) is no pad: pad 2's input, insert and LFO retrigger stay off it | **PR #7** (opened 20/10, `f3e6f91`) |
| `fix/usbdev-debug` | dev builds: DEBUG peek / poke bounded to whole regions; EP0 IN flushed at every SETUP; the release image unchanged | **PR #8** (opened 20/10, `9692f7f`) |
| `fix/waveform-labels` | the Waveform screen's corner labels white with a 1 px black edge, every pad mode; its own module, riding on the `slice` set | **PR #9** (opened 20/10, `eefe93b`) |
| `feat/linux-dev` | build and test on Linux / hosts without clang or FMA; Ghidra paths from the environment | **PR #10** (opened 20/10, `fff2d37`) |
| `feat/munchi-bank2` | Munchi's engine in bank 2, its hooks and stock calls in bank 1: 6.4 KB of the cave back, the output bit for bit; MUNCHI_OFF fixed | on origin (`c3ccbb5`); merged here for 37.4.0 (D-029); its PR held until F-o (the analog crunch) is told apart from it |
| `feat/repo-layout` | the suites in `tests/`, the RE helpers in `tools/`; images byte-identical | local (`452f4f8`): offered to Justin first, adopted here only if he takes it |
| `feat/clip-window` | the Clip Window: **one PR of five commits**, one per layer (slip, region + the Waveform knobs, looplen, fit, loopfade; D-032) | to cut from upstream `main` (hub #t-039); opened after Justin answers the first-contact issue; `feat/slip` (37.1 layout) is superseded by it |

The five small PRs' changes are on `maigre`, though not as merges of their branches, and two in another form: the
corner labels inside `src/clipwin.c` (PR #9 makes them a module), the bounded peek beside the fork's parameter
mailbox in `src/usbdev.c`.
Their branches are merged in when Justin takes them, his version winning.

First contact: an issue on j3threejay/blackbox-mod (#4, 18/10; no answer yet on 21/10), text in
`notes/upstream-first-contact.md`. JOEBOX's updates
reach the fork through `bench/sync-upstream.sh` (a hub watcher opens a task when his `main` moves).

## Build, install, bench

- Build and test: [`notes/dev-setup.md`](notes/dev-setup.md) (Linux, no root: Arm GNU 14.2, a Python venv, Ghidra 12 +
  a JDK 21). `./check.sh` must print `N suites, 0 failed`.
- Checking a branch: `bench/doctor.sh` says whether a box can run `./check.sh`, and prints the line that fixes each
  miss. `./check.sh` runs the suites in a pool as wide as the box, `test_clipwin.py` as six shards of its own file
  when `bench/shards/proven.tsv` holds the proof of that plan, whole otherwise (D-046; after an edit to that suite:
  `python3 bench/shard.py test_clipwin.py --prove 6`). `bench/bbci.sh <ref> [--remote <name>]` checks any ref in a
  throwaway worktree and leaves `verdict.json`, an `error` one when it is stopped.
- Install: copy the patched `BLACKBOX.bin` (and `BBEXTRA.BIN` when a build has one) to the card root, hold BACK + INFO
  while powering on, on the unit's normal power supply. Back to stock the same way with 1010music's file.
- Room in bank 1: `python3 bench/b2split.py <module> --decl bench/splits/<module>.py` moves a whole module to bank 2
  with generated bank-1 stubs that fall back to stock, its source untouched (D-047,
  [`notes/spikes/b2split.md`](notes/spikes/b2split.md)); `--verify` after `patch.py` checks the result.
- Before an upstream merge: `python3 bench/resources.py report . upstream/main` (add `--build --base $(git merge-base
  HEAD upstream/main)` for bank 1) lists where the release collides with the fork: parameter ids and their reads, call
  sites, calls into stock the release hooks, page slots, settings stores, the SDRAM block, backup SRAM, flash
  ([`notes/resources.md`](notes/resources.md), D-044). Exit 1 = collisions; exit 2 = something was not read, so read
  its « Not read » list before trusting the result. `test_resources.py` keeps one tree free of them.
- The unit's power from mgr-ran: [`bench/bbpower.py`](bench/bbpower.py) `off | on | cycle` (the hub port it is
  plugged in; the cut is proven by the unit's own uptime counter).
- Bench kit (dev builds, 37.5.0d on; needs that build's `BBEXTRA.BIN`): [`bench/bbkit.py`](bench/bbkit.py) sends
  jobs through a mailbox: info, knob, button, play, stop, touch, tap, cancel, preset, presets, ls, stat, get, put,
  rm, restart (waits for the unit to come back and prints the new boot number), shot, row. `bbshot.py` and
  `bbusb.py peek` read 4 KB a request on such a build (`notes/re/x6` sections 9 and 13); `bbusb.py set` / `get`
  there need that build's own `bbusb.py`.
  `bench/bbusb.py crash` also prints the crashed-boot count and the fault token (`BANK 2 HELD OFF` from 3).
- Bench over USB: [`bench/bbusb.py`](bench/bbusb.py) — the power jack of a modded unit is a USB device: audio of
  Outs 1–3 (measure a feature in samples), MIDI, and on dev builds the memory (the crash recorder, the Clip Window's
  state). Gate reports: [`notes/bench/`](notes/bench/).

## Where things are

- [`notes/`](notes/README.md) — the plan, the decisions (`notes/decisions.md`), the reverse-engineering notes
  (`notes/re/`, prose + addresses), feature docs (`notes/features/`), bench reports.
- Tasks, bench cards and the project log live in Thomas's hub (37Projects, project `blackbox`), not here.
