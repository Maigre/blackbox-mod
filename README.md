# blackbox-mod — the Maigre fork (37.x)

A feature mod for the **original 1010music Blackbox** (Mk1, not the Blackbox 2), built on stock firmware **3.1.9**.
It is Thomas's fork of [JOEBOX](https://github.com/j3threejay/blackbox-mod) by Justin Joe: everything JOEBOX has,
plus a family of new tools for **Clip pads** — play a loop cut by ear in sync with the clock, slide it into the
groove, fit it to the tempo, repeat a beat of it — and, coming next, a KP3-style **looper** and a deeper **MIDI**
remote. Every feature is written so that it can go back to JOEBOX as its own pull request.

> **Not affiliated with, endorsed by, or supported by 1010music**, nor by JOEBOX's author. This repository does not
> contain 1010music's firmware: you supply your own copy of stock 3.1.9 and patch it yourself. Tested on a small
> number of units; use at your own risk; flash stock before asking 1010music for support.

**Current release: 37.4.0, on JOEBOX 1 rc4** — a test release. Release notes, with each build's sha256:
[`notes/releases/`](notes/releases/). The Tools page shows the version (`37.4.0`; a `d` marks a developer build).

---

## For players

### What this fork adds

On a **Clip pad**, a few rows on the Pos tab (all saved with the preset; at their defaults the pad plays as on
JOEBOX):

- **Slip** — moves what the loop plays against the clock, live, up to a bar either way, like a CDJ jog: `+` pushes
  the loop ahead of the beat, `−` drags it behind. One knob: single ticks when you turn slowly, 1/64 steps at full
  speed, a short detent on 0. The change is heard at the next step.
- **Region** Auto / File / Loop — the pad plays its **loop points** (set on the Clip pad's waveform or in Sample
  mode), in sync, instead of the whole file: no destructive Trim. Auto follows the loop points whenever they are not
  the whole file.
- **Loop Len** Off, 1/16 … 4 bars — a beat repeat on the grid: the window where the music is, looped, until you turn
  it Off and the loop carries on in phase.
- **Fit** Off, Auto (Bars), 1/4 … 8 bars, Auto (Beats) — the loop lasts exactly that many beats at the tempo (a
  little faster or slower, pitch with it; not a time-stretch). Auto (Bars) picks the nearest whole number of bars (under
  a bar: 1/4, 1/2 or 1 bar), so a loop cut by ear stays on the metronome's bar; Auto (Beats) picks the nearest whole
  number of beats, and a length that is no whole bar (3, 5, 14 beats…) plays as a polyrhythm, each pass in time. It follows
  tempo changes.
- **Loop Fade** on a region — the loop point crossfades as in Sample mode, so a loop whose ends do not meet does not
  click.
- **The Waveform screen in Clip mode**: the four knobs are Loop Start, Loop End, Slip and Loop Len; the loop bracket
  shows; the playhead line shows the frame you hear. Turning Loop Start or Loop End takes the view to that edge, and
  it follows the playhead again after a pause.

Everywhere:

- **Readable corner labels** on the Waveform screen (white with a black edge over the waveform, in every pad mode).
- **More room in the firmware** for what comes next: Munchi's engine lives in the second flash bank (bit-identical
  sound).
- Fixes found on the bench: no click where a slipped or regioned loop comes round; the browser's pre-listen voice no
  longer takes pad 2's input, insert or LFO; a pad the browser left stuck recovers on its own.

And **everything JOEBOX 1 adds** — live input on a pad, per-pad inserts, LFO 2 and 3, ENV and KEY sources, the Master
FX slot (VHS, Prism), the Motion / Relapse / Munchi delays, Smash and the master clipper, the rebuilt Fidelity
machines, record pre-roll, sequence rotate, MUTE and SOLO, USB audio and MIDI on the power jack, the load readout,
chords, note conditions and more. Justin's own documentation of all of it, with its history, is kept whole in
[`docs/JOEBOX.md`](docs/JOEBOX.md).

Coming: a **Looper FX** on the XY page (touch catches the bar that was playing; X = length, Y = a high-pass), saving
a caught loop to a pad, and a **MIDI remote** (every parameter reachable from outside, with feedback for
controllers). Known issues per feature: [`notes/features/clip-window.md`](notes/features/clip-window.md) §4.

### Install

1. Download stock firmware **3.1.9** from <https://1010music.com/downloads> (its `BLACKBOX.bin`).
2. Get this repository (Code > Download ZIP, or `git clone`), and patch your copy with the release's patch file,
   in `docs/`: `python3 apply.py path/to/BLACKBOX.bin docs/blackbox-mod-37.4.0.json`. Name the file: `docs/` also
   holds JOEBOX's own patch. `apply.py` needs only Python 3; it checks that your file is the stock 3.1.9 and writes
   **two files**, `BLACKBOX.bin` and `BBEXTRA.BIN`. Patched firmware is never distributed here.
3. Copy **both** to the root of the Blackbox's SD card.
4. Power on holding **BACK + INFO**. When a release changes the second file, the first boot installs it and
   **restarts once** by itself: leave the power on until it is back.
5. TOOLS shows `37.4.0` with no `!` in front of the load figures. A `!` means the two files are not from the same
   build: copy both again.

Back to stock: the stock `BLACKBOX.bin` on the card, the same BACK + INFO start.

---

## For developers

### Layout

| path | what |
|---|---|
| `src/`, `patches/` | the mod: one feature = `src/<f>.c` (+ a thunk) and `patches/<f>.py`, in JOEBOX's layout |
| `test_*.py`, `check.sh`, `emu.py` | the suites: the real stock code run under Unicorn, plus host builds of the DSP |
| `build.sh`, `patch.py`, `make_patch.py`, `apply.py` | build, patch, release patch file, apply |
| `bench/` | **fork-only** tools for a unit on USB: `bbusb.py` (peek, record, measure), `bbshot.py` (screenshots), `bbmidi.py` (MIDI, clock), `autogate.py` (unattended test runs), `prcheck.sh` (each PR branch checked alone), `sync-upstream.sh` |
| `notes/` | **fork-only** working docs: the plan, decisions (`decisions.md`), reverse-engineering notes, feature docs, bench reports, release notes |
| `docs/JOEBOX.md` | upstream's README, kept whole and refreshed at each sync |

### Build and test

Linux, no root: Arm GNU 14.2, a Python venv (unicorn, capstone, numpy), and your own stock 3.1.9 image —
[`notes/dev-setup.md`](notes/dev-setup.md). `./check.sh` must end with `N suites, 0 failed`; `RELEASE=1 ./check.sh`
for a release build. On a unit: [`notes/features/clip-window.md`](notes/features/clip-window.md) §6–7 and
`bench/autogate.py` (the internal clock, transport playing).

### Branches and how the fork works with JOEBOX

- **`maigre`** (this branch, the default) is the fork: JOEBOX's code + all our features + the fork-only layer
  (`notes/`, `bench/`, this README, the 37.x names). It moves only by merges.
- **`main`** mirrors JOEBOX's `main`, fast-forward only.
- **`feat/*`, `fix/*`** are pull-request-shaped branches cut from JOEBOX's `main`, one feature or fix each, in his
  layout; each is merged into `maigre` when ready and offered upstream; JOEBOX's updates are merged into them (never
  rebased). The map of what goes upstream, and in which order: [`notes/pr-map.md`](notes/pr-map.md).
- **JOEBOX's updates reach the fork** through `bench/sync-upstream.sh`: merge his `main` into `maigre` (where he took
  one of our features, his version wins), refresh `docs/JOEBOX.md`, merge into every open PR branch, check
  everything. `README.md` is kept ours on merges (`.gitattributes`; the script sets the merge driver).
- The rules behind this: [`notes/decisions.md`](notes/decisions.md) D-019; the version scheme `37.<step>.<build>`:
  D-012; the history of every release: [`FORK.md`](FORK.md).

---

## History and credits

- **1010music** made the Blackbox; this mod patches their firmware 3.1.9 and contains none of it.
- **JOEBOX** — the mod this fork builds on — is **Justin Joe**'s ([j3threejay](https://github.com/j3threejay)): the
  code cave, the second flash bank, the patch tooling, the Unicorn suites and every JOEBOX feature listed above.
  His README, with its full feature documentation and update history, is [`docs/JOEBOX.md`](docs/JOEBOX.md).
- **Munchi Delay** is Charles Vestal's port of CHOMPI TEMPO's dual delay (MIT); sources and licences in
  `src/munchi/`.
- **This fork** (Thomas, since 2026-10-15): the Clip Window (Slip, Region, Loop Len, Fit, Loop Fade, the Clip-mode
  Waveform), the corner labels, Munchi in bank 2, the bench tools, and the fixes they turned up — including the
  restart-loop analysis that met JOEBOX 1 rc4's own fix.

## License

As upstream: see [`LICENSE`](LICENSE) and [`THIRD_PARTY.md`](THIRD_PARTY.md). Never in this repository: 1010music's
firmware, patched images, disassembly or manuals.
