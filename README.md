# blackbox-mod

An unofficial feature mod for the **original 1010music Blackbox** (not the Blackbox 2), built on stock firmware 3.1.9.

> **Not affiliated with, endorsed by, or supported by 1010music.** This repository does not contain 1010music's
> firmware. You supply your own copy, downloaded from 1010music, and patch it yourself. Use at your own risk: this is
> tested on one unit, it may misbehave on yours, and running modified firmware may affect your warranty. Don't ask
> 1010music for support on a modded unit; flash stock first.

**Get new builds by email:** sign up at <https://justinjoe.com/blackbox-mod> and I'll send a note when a new build is
out (new FX, fixes). That's all the list is for.

## What it adds (build 3.1.n)

- **Solo** in the mixer: MIX cycles Mixer → Mute → Solo. Tap pads to solo them (yellow).
- **Slicer knobs**: on the waveform screen, bottom-left = slice Start, bottom-right = slice End, top-right = Zoom.
- **Pad-1 ducker**: four new modulation Sources (EXP1, EXP2, PUMP, LINR) that fire when pad 1 plays. Put your kick
  on pad 1, set a negative Amount on another pad's Level, and you have sidechain pumping. About 0.65 dB per 1%.
- **Chords on the Keys screen**: top-right knob picks a shape (Tri, 7th, 9th, Su2, Su4, 6th, Ad9, Pwr, Oct, Opn, Shl,
  Qrt, m7, m9, Mj7). In-scale shapes follow the Keys Scale/Root. Chords record into sequences.
- **Note conditions**: the piano roll's PLAY list gains 1:2 … 8:8 ("play the Ath of every B loops").
- **Fidelity** (was Interp): sample-rate crunch plus machine modes SP1200, SP-12, S950, MPC60 and SP Raw, with
  drop-sample pitching. Machine modes work on Sample and Multisample pads.
- **Filter**: 24 dB/oct state-variable filter; drive comes in as Res goes past noon.
- **Saturation** (was Overdrive): soft saturation in place of the hard clip.
- **Master compressor models**: Stock, Glue, Punch, Opto, Squash, Limit, plus a Comp Thresh setting.
- **Reverb Type**: Plate (stock) or Room.
- **Delay Type**: Delay (stock) or Munchi (a port of the CHOMPI TEMPO granular delay).
- **Sequencer fix**: a note added just ahead of the playhead plays on that pass.

### Known issues

- Solo can stick: after un-soloing, pads may stay muted. Unmute them in Mute mode.
- A note placed very close ahead of the playhead is still sometimes silent.
- Chords need the pad out of Mono Poly Mode.
- Presets saved with a Fidelity value on an older mod build may read a different value.

## Install

1. Download **blackbox 3.1.9** from <https://1010music.com/downloads> and unzip it. You need the `BLACKBOX.bin` inside.
2. Patch it, either way:
   - **In your browser:** <https://j3threejay.github.io/blackbox-mod/>. Your file never leaves your computer.
   - **With Python 3:** `python3 apply.py path/to/BLACKBOX.bin` → `out/blackbox-mod-<version>/`
3. Keep the stock `BLACKBOX.bin` somewhere safe. That file is your way back.
4. Copy what the patcher gives you to the **root** of the Blackbox's microSD card. Newer builds are **two files,
   `BLACKBOX.bin` and `BBEXTRA.BIN`, and both have to be there** (the browser patcher hands you a zip with both).
5. Install it the way you install any 1010music firmware update: hold BACK + INFO while powering on, and let go as
   soon as the install screen shows.
6. On a two-file build the Blackbox **restarts itself once**, a second or two into the first boot. That is the
   second file being installed. Leave the card in and the power on until it is back up.
7. TOOLS should show the new version.

### The second file

Part of the mod (Prism, Confetti and the per-pad insert effects) is too big to fit beside 1010music's firmware. The
chip has a second block of flash that 1010music's installer never touches, so the mod keeps that code there and
installs it itself from `BBEXTRA.BIN` the first time it starts. The file holds this project's own code and nothing of
1010music's. You can leave it on the card.

- **`!` in front of the load figures on TOOLS** (for example `!62/75%`) means the second part is not installed or
  does not match this build. Everything else works; those three effects are switched off.
- **`---` in the Insert, Master FX or delay Type lists** is the same thing seen from the menus: the effect that
  belongs there is not installed. A preset that uses one keeps its setting and gets the effect back once it is.
- To fix either: put the `BBEXTRA.BIN` **from the same download** as your `BLACKBOX.bin` in the root of the card and
  power the Blackbox off and on. The two files are a matched pair; one from a different build is ignored.
- If the second part cannot be written after two tries, the mod stops trying and leaves those effects off rather
  than wearing the flash. Installing any build (with its own `BBEXTRA.BIN`) starts the count again.

**To go back to stock:** put the stock `BLACKBOX.bin` on the card and install it the same way. The second part
stays in the chip, unused: stock firmware never looks at it, and it does not touch the unit's calibration.

The patcher checks your file's SHA-256 before it writes anything
(`281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d`) and checks the result afterwards. It only
works on 3.1.9.

## Build from source

Needs `arm-none-eabi-gcc` and Python 3. Put your stock image at `firmware/BLACKBOX-3.1.9.bin` (see
`firmware/README.md`).

```
./build.sh
python3 patch.py solo slice duck chord cond filter cpu od comp seqfix fx2 munchi cave
```

That writes `out/<patchsets>/BLACKBOX.bin`, byte-identical to the release. `python3 make_patch.py <image> <version>`
turns an image into the release patch in `docs/`.

How it works: the stock image is left as it is. New code (`src/`) is compiled and appended after it, and a handful of
call sites and table entries (`patches/`) are redirected to the new code.

Tests (`test_*.py`) run the patched functions under Unicorn (`pip install unicorn`). They test the new functions, not
a full boot. The first power-on of any build is the real test.

`ghidra/`, `disasm.py`, `findbl.py`, `findref.py` are the helpers used to find things in your own copy of the image.

## What is and isn't in this repository

In it: original source code, patch definitions (addresses and replacement bytes), tools, and MIT-licensed third-party
DSP with its notices ([THIRD_PARTY.md](THIRD_PARTY.md)).

Not in it, and please don't add it in issues, pull requests or forks: 1010music's firmware, patched firmware images,
decompiled or disassembled listings of the firmware, and 1010music's manuals or artwork.

## License

MIT for the original work here ([LICENSE](LICENSE)). "1010music" and "Blackbox" are trademarks of 1010music LLC, used
only to say what this mod is for.

If you are from 1010music and have a concern about anything here, open an issue or email justin.joe.dev@gmail.com and
it will be dealt with promptly.
