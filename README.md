# blackbox-mod

> **Fork 37.x** (Maigre/blackbox-mod): JOEBOX 1 (rc4) + Clip Window (Slip, Region, Loop Len, Fit, Loop Fade)
> and, on its way, a KP3-style looper. What it adds, its versions and its upstream PRs: [`FORK.md`](FORK.md). The text
> below is upstream's README, with each fork feature's bullet added where it lands.

An unofficial feature mod for the **original 1010music Blackbox** (not the Blackbox 2), built on stock firmware 3.1.9.

> **Not affiliated with, endorsed by, or supported by 1010music.** This repository does not contain 1010music's
> firmware. You supply your own copy, downloaded from 1010music, and patch it yourself. Use at your own risk: this is
> tested on a small number of units, it may misbehave on yours, and running modified firmware may affect your warranty. Don't ask
> 1010music for support on a modded unit; flash stock first.

**Get new builds by email:** sign up at <https://justinjoe.com/blackbox-mod> and I'll send a note when a new build is
out (new FX, fixes). That's all the list is for.

## What it adds (JOEBOX 1)

Releases have names now. JOEBOX 1 is the one after 3.1.n, and TOOLS shows it as the version.

**Updated 2026-10-17, same name.** The first JOEBOX 1 got some units stuck restarting at the logo. This build fixes
that (two of those units have confirmed it boots now). It also fixes USB audio not showing up when the compressor is
on Limit, and the insert models have their own names (Pebble, Electra, Jet). If you installed JOEBOX 1 before, patch
again and put both files on the card the same way.

New since 3.1.n:

- **Slip on Clip pads**: a "Slip" row on a Clip pad's Pos tab, after Sync. It shifts what the clip plays against the
  clock, up to a bar either way, so a loop cut by ear sits where the groove wants it. Like a CDJ jog: clockwise pushes
  the loop ahead, counter-clockwise drags it behind. The value is beats.ticks, 960 ticks to a beat (`-0.480` is half a
  beat behind; one tick is about half a millisecond at 120 BPM). Turn slowly for single ticks; it speeds up smoothly
  as you turn faster, up to 1/64 steps (60 ticks) at full speed; 0 is a detent: a turn stops there for a moment
  (0.4 s when you come in slowly, 0.15 s when fast), then goes on past it if you keep turning. A change is heard at
  the next Sync step. Saved with the preset; 0 is stock.
- **Region on Clip pads**: a "Region" row on a Clip pad's Pos tab, before Slip: Auto, File or Loop. Loop plays only the
  pad's loop (Loop Start to Loop End, set in Sample mode or read from the WAV's own loop) as if it were the whole file,
  so a loop cut from a longer recording needs no Trim. Auto, the default, does that when the pad has a loop (its loop
  points are not the whole file; Sample mode's Loop Mode does not matter) and plays the file otherwise, so fresh
  recordings and plain files play as before. File always plays the whole file. Beat Count Auto counts the region, Slip shifts within it, and the end of the region
  crossfades into its start like any other Sync step, so a region that is not a whole number of beats leaves no gap
  and no doubling at the loop point, even when the whole loop is one Sync step. A change while the pad plays is heard
  from the next time the loop comes round, or the time after that if it is made during the loop's last Sync step. A
  change that makes the loop longer can wait a little more: it starts where a launch would start the new loop (on the
  Quant, or on the new loop's own length when that is shorter), so it never doubles. If the loop playing can never
  come round to such a point (a loop shorter than half a beat, say), the new one starts the next time round and falls
  into time over one pass, with one step doubled. Saved with the preset.
- **Loop Len on Clip pads**: a "Loop Len" row on a Clip pad's Pos tab, after Slip: Off, 1/16, 1/8, 1/4, 1/2, 1 bar,
  2 bars or 4 bars. Only that much of the clip loops, in time, and it is the part that was playing when you turned it
  on, like a KP3's loop: 1/4 repeats the beat that was playing, 1/16 a sixteenth of it. It is taken once the knob
  rests on a value (about 0.3 s), so turning from Off to 1/4 engages 1/4 on the beat playing then, not the 1/16 or
  the 1/8 it passed on the way; stepped through slowly, it takes each value in turn. Off is immediate. Turned Off and on again,
  it takes the beat playing when the knob comes to rest: the same one if that beat is still playing then. Changing
  the length while it is on keeps the same start and moves the end. Off goes back to the whole loop, in phase, as if
  it had played on all along. A length shorter than the pad's Sync step sets Sync to fit, and your Sync comes back as
  soon as the length fits it again, or at Off. It works over Region and with Slip, which shifts what the window
  plays. A change is heard at the pad's next Sync step. Saved with the preset.
- **Fit on Clip pads**: a "Fit" row on a Clip pad's Pos tab, after Loop Len: Off, Auto, 1/4, 1/2, 3 beats, 1 bar,
  6 beats, 2 bars, 4 bars or 8 bars. The loop (the Region, or the whole file) then lasts exactly that many beats at the
  tempo: it plays a little faster or slower, and its pitch moves with it (it is not a time-stretch). A loop cut by ear
  that is not a whole number of beats no longer stutters at every Sync step, and a WAV's own Beat Count no longer chops
  a shorter Region. Auto takes the nearest whole number of beats (a loop of 14.015 beats plays as 14, one of 3.74 as
  4), counted once for each loop length: change the tempo and it keeps its beats and follows. A length that is not a
  whole number of bars (3, 5, 7 or 14 beats, say) is a polyrhythm: the loop comes round every so many beats against the
  bar, each pass in time and seamless; the pad's Sync steps then fall on that loop's own grid (14 beats with Sync 1 bar
  re-sync every half bar). The loop point crossfades into the start like any other step, a whole file's too. A change
  while the pad plays is heard from the next time the loop comes round; one that moves where the loop can start (1 bar
  to 2 bars on a Quant of 4 bars) waits for a point where a launch would start it, as a Region change does. Saved with
  the preset; Off is stock.
- **Loop Fade on a Region**: Sample mode's Loop Fade row is on a Clip pad's Pos tab too, after Fit. On a pad playing a
  Region it smooths the loop point as Sample mode does: the end of the loop (that share of its length, at most as long
  as what lies before Loop Start) crossfades into the audio just before Loop Start, so a loop whose end and start do
  not meet no longer clicks each time it comes round. Heard from the next time round; 0 is stock.
- **Knobs on a Clip pad's waveform**: stock leaves all four blank in Clip mode. Top-left is Loop Start and top-right
  Loop End, the same loop points as Sample mode's, which Region plays: one step is one pixel of the waveform, so zoom
  in for finer steps. The white loop bracket shows the loop Region plays, as soon as you turn: a playing pad takes the
  new loop the next time its loop comes round, as with any Region change, so while you turn, the bracket is ahead of
  what you hear. Bottom-left is Slip and bottom-right Loop Len, the same rows as on the Pos tab. The four read
  `LpS`, `LpE`, `Slip` and `LpLen` there, short enough that each value stays clear of its neighbour.
- **Readable waveform knobs**: on every pad's waveform screen, whatever its mode, the four corner knobs' text is
  white with a thin black edge instead of stock's grey, so it reads over the waveform's cyan as well as over the
  background. Same font, size and names. Without this build's `BBEXTRA.BIN` it is stock's grey.
- **Live input on a pad**: an "Input" row on a pad's Conf tab (Off, In 1, In 2, In 1+2). The audio input plays
  through that pad, so it gets the pad's insert, its reverb and delay sends, its level and pan, and the master FX.
  Muting the pad mutes it.
- **An insert effect per pad**: "Insert" on the Conf tab, INFO opens its knobs. Phaser (five models), Flanger
  (four models) or Gate. Sample, Multisample, Clip and Slicer pads.
- **LFO 2 and LFO 3 per pad**, on a new "LFO+" tab: twelve shapes (the stock nine plus two exponential ramps and
  a smooth random), tempo-synced rates from 32 bars to 1/32, Free / Retrig / Once, and a start Offset. They appear
  as LFO2 and LFO3 in the modulation Source list.
- **ENV and KEY as modulation sources**: the pad's own envelope, and key tracking.
- **Master FX slot** on TOOLS: VHS (wow, flutter, saturation, dropouts, noise) or Prism, a four-block multi-effect
  (drive, motion, space, texture; twenty effects). INFO on the row opens the knobs.
- **Delay types**: Motion (the stock delay with tremolo, filter, duck or swell on the repeats), Relapse (a memory
  echo) and Confetti (a granular micro-looper), next to Delay and Munchi.
- **Smash**, a three-band compressor, in the compressor list, and a **master clipper** after the compressor
  (Clean or Diode).
- **Fidelity**: the S950 mode rebuilt from the machine's schematic, S950 Lo and SP 45 added, and the machine modes
  now work on Clip and Slicer pads.
- **Record pre-roll**: TOOLS, Rec, Pre-roll (1, 2, 4 or 8 bars). The loop plays that long before the recording
  starts, so a resampled loop holds its own tails.
- **Rotate a sequence**: in the piano roll's Event editor the top-right knob shifts the whole layer a step at a time.
- **MUTE and SOLO on the Pads screen.**
- **USB on the power jack**: plugged into a computer the Blackbox is a class-compliant USB MIDI device and sends
  its three stereo outputs as six channels of 24-bit 48 kHz audio.
- **Load readout on TOOLS**: average / peak, for example `62/75%`. Over about 100% peak the engine is out of time
  and you will hear it.
- **Fixed**: the naming keyboard's 9 key (3.1.n typed "n").

From 3.1.n and earlier:

- **Solo** in the mixer: MIX cycles Mixer → Mute → Solo. Tap pads to solo them (yellow).
- **Slicer knobs**: on the waveform screen, bottom-left = slice Start, bottom-right = slice End, top-right = Zoom.
- **Pad-1 ducker**: four modulation Sources (EXP1, EXP2, PUMP, LINR) that fire when pad 1 plays. Put your kick
  on pad 1, set a negative Amount on another pad's Level, and you have sidechain pumping. About 0.65 dB per 1%.
- **Chords on the Keys screen**: top-right knob picks a shape (Tri, 7th, 9th, Su2, Su4, 6th, Ad9, Pwr, Oct, Opn, Shl,
  Qrt, m7, m9, Mj7). In-scale shapes follow the Keys Scale/Root. Chords record into sequences.
- **Note conditions**: the piano roll's PLAY list gains 1:2 … 8:8 ("play the Ath of every B loops").
- **Fidelity** (was Interp): sample-rate crunch plus machine modes SP1200, SP-12, S950, MPC60 and SP Raw, with
  drop-sample pitching.
- **Filter**: 24 dB/oct state-variable filter; drive comes in as Res goes past noon.
- **Saturation** (was Overdrive): soft saturation in place of the hard clip.
- **Master compressor models**: Stock, Glue, Punch, Opto, Squash, Limit, plus a Comp Thresh setting.
- **Reverb Type**: Plate (stock) or Room.
- **Munchi**, a port of the CHOMPI TEMPO granular delay, as a delay type.
- **Sequencer fix**: a note added just ahead of the playhead plays on that pass.

### Known issues

- This has run on very few units. If yours does something this list doesn't mention, I want to hear about it.
- The Blackbox only has so much CPU, and the mod lets you spend all of it. Room and Prism are the expensive ones.
  Watch the load readout on TOOLS.
- LFO 2 / 3, ENV, the insert and Input are not on Granular pads.
- A note placed very close ahead of the playhead is still sometimes silent.
- Chords need the pad out of Mono Poly Mode.
- Slip, Region, Loop Len, Fit and a Region's Loop Fade all run from the second file (`BBEXTRA.BIN`, flash bank 2),
  which has to come from the same download as `BLACKBOX.bin`. Without it (or with one from another build) every Clip
  pad plays exactly as on stock: the rows are there and save, but do nothing; the Slip row shows a plain number of
  ticks instead of beats.ticks and turns like any number row, and the Clip-mode waveform shows no loop bracket (its
  four knobs still turn: Loop Start and Loop End move the loop points, which the pad then does not play; Slip and Loop
  Len there do nothing). TOOLS shows the `!`.
- Slip does nothing on Slicer pads, or on a Clip pad set to Sync Slice with slice markers. The playhead line on the
  waveform shows stock's position there. A new file loaded into a playing Clip pad plays unslipped, without its region
  or Loop Len, for up to two Sync steps, then as set. (A pad that the file browser gave its own file back while it
  played a longer file's last step no longer sticks on its first beat: it plays on from its next pass. That needs the
  second file too.) The playhead line on the waveform shows the frame you hear, with Slip, Region, Loop Len and Fit;
  for a moment at a step change it can show where the fading step was reading.
- Region does nothing on those pads either. Switching a Clip
  pad to Sample mode clears its loop points (stock does that), so a pad sent back to Sample mode to adjust the loop
  needs it set again. A Beat Count that is not Auto, including one read from the WAV when it was loaded, is taken as
  the region's length in beats (Fit Auto or a Fit length overrides it).
  A pad that never loops round (Launch Trigger, or Loop Off) takes a new region at its
  next launch after it has stopped, and so does a stopped pad: until that launch, the length it reports for Beat Count
  Auto is the old one. A region shorter than half a beat counts 0 beats on Beat Count Auto, as a file that short does
  on stock: it loops on its own length, restarting slightly early with a short overlap, and Slip does nothing there.
  Give it a Beat Count. Such a region made longer while it plays has no grid to wait for: the new one starts the next
  time round and falls into time over one pass, with a short gap and one step doubled.
- Loop Len needs a Quant and a Sync (with Quant None or Sync None it does nothing), does nothing on the pads Slip
  ignores, and a length of the whole loop or more does nothing. It is taken from what the pad plays: set while a launch
  waits for its bar, it starts once the pad plays; on a pad not played since power-on, at its first launch. A pad that
  stops forgets what it was looping: its next launch loops from the start of the clip. While it holds a shorter Sync,
  the Sync row still shows yours, and turning that knob puts yours back for a moment (up to 43 ms) before Loop Len sets
  it again. On a loop the length does not divide (a 3-beat loop with 1/2) the window starts over with the loop. A
  slow, steady turn (about 0.3 s or more on each value) takes the values it passes, and the first of them sets where
  the window starts; so does a quick turn that overshoots and rests there that long before you turn back.
  Turned Off and on again within two Sync steps of a new file loaded into the playing pad, it can take its in-point from the old file's window (the beat before, not the one playing).
- Fit changes the speed, so the pitch: a 3.74-beat loop fitted to 4 beats plays 6.5% slower and a little lower. The
  Beat Count row and the clip length the app shows stay stock's (Beat Count Auto's), not Fit's. Pitch on a fitted pad
  re-places the loop at every Sync step, as on stock. After a tempo change the pad follows within 43 ms; the step
  already under way finishes at the old tempo and overlaps the next one once, as on stock. A fitted loop that has to
  play at another speed than its own reads through the interpolating reader (as a 44.1 kHz file does on stock), which
  costs more CPU. Fit does nothing on the pads Slip ignores (Slicer, Sync Slice with markers), and has no knob on the
  waveform screen. When your Sync step does not divide a fitted loop, the pad re-syncs on the largest step that does
  (half a bar for 14 beats at Sync 1 bar, a beat for 5 beats at Sync 1/2). Auto's count is kept while the pad's file
  stays open: a preset at another tempo that plays the same file may keep the count made at the old tempo (not yet
  checked on the unit). To count it again at the tempo now, play a pass with Fit on another value, then Auto.
- Loop Fade does nothing on a loop that starts at the very beginning of the file (there is nothing before Loop Start
  to fade from), on a whole file, on a pad that never loops round (Launch Trigger, or Loop Off), on a loop shorter than
  2 048 samples, in Fidelity's machine modes, above about four times the speed (two octaves up), or while Loop Len is
  on (its short loop goes back to its own start, not on into Loop Start). While the fade plays, the pad reads its file
  in two places at once; whether the card keeps up with a long fade is not yet measured on the unit. The Loop Fade row
  also shows on a Clip pad that plays its whole file, where it does nothing.
- On a Clip pad's waveform, Loop Start turned all the way up to Loop End (or Loop End down to Loop Start) leaves no
  loop, so the pad plays the whole file until they are apart again. With Region on File the two knobs still move the
  loop points but nothing is heard and no bracket shows.
- Presets saved on an older mod build can come back with a neighbouring Fidelity or delay Type, because those
  lists gained entries. Set them again and save.
- USB on the power jack doesn't work on every unit. On some, that jack's USB data side is dead with any firmware,
  stock included (1010music never used it for data). The Blackbox boots and plays fine, you just don't get USB audio
  and MIDI. If your computer never sees the Blackbox over that jack, it's the unit, not the mod.
- The machine Fidelity modes (SP1200, SP-12, MPC60, SP Raw, SP 45) can come out grittier on one hit than the next.
  Fixed in the next build.

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
7. TOOLS should show `JOEBOX 1`.

### The second file

Part of the mod (Prism, Confetti, Munchi, the per-pad insert effects and Clip pads' Slip, Region, Loop Len and Fit)
is too big to fit beside 1010music's firmware. The chip has a second block of flash that 1010music's installer never
touches, so the mod keeps that code there and installs it itself from `BBEXTRA.BIN` the first time it starts. The file
holds this project's own code and nothing of 1010music's. You can leave it on the card.

- **`!` in front of the load figures on TOOLS** (for example `!62/75%`) means the second part is not installed or
  does not match this build. Everything else works; those effects are switched off (Munchi plays the plain delay),
  and Clip pads play as on stock (Slip, Region, Loop Len and Fit do nothing).
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
RELEASE=1 ./build.sh
python3 patch.py solo slice duck chord cond filter cpu od comp seqfix fx2 munchi master fault cave
```

That writes `out/<patchsets>/BLACKBOX.bin` and `out/BBEXTRA.BIN`, byte-identical to the release.
`python3 make_patch.py <image> "JOEBOX 1" --extra out/BBEXTRA.BIN` turns the pair into the release patch in `docs/`.
Without `RELEASE=1` you get a test build: a letter for a version, and a raw memory peek / poke over USB for
development. That one can write anywhere in the machine, so it is not in a release.

How it works: the stock image is left as it is. New code (`src/`) is compiled and appended after it, and a handful of
call sites and table entries (`patches/`) are redirected to the new code.

`./check.sh` builds, patches and runs every suite (`test_*.py`) under Unicorn (`pip install unicorn capstone numpy
scipy`), prints `N suites, M failed`, and exits non-zero when any failed. Several suites hold the firmware's DSP against
a build of the same C for the computer (`host/build.sh`: clang on a Mac; elsewhere `CC`, else `cc`, e.g. gcc on Linux;
the library keeps its `.dylib` name, `dlopen` does not mind). On a host CPU without FMA (x86 before Haswell) the
S950 Lo checks in `test_machine.py` allow 1e-5 (`HOST_TOL`): the M7 fuses its multiply-adds, so the recursion differs
by a few ulp. They test the new functions, not a full boot. The first power-on of any build is the real test.

`ghidra/`, `disasm.py`, `findbl.py`, `findref.py` are the helpers used to find things in your own copy of the image.
The Ghidra scripts default to the Homebrew paths and take `GHIDRA_INSTALL_DIR`, `JAVA_HOME` (a full JDK 21: Ghidra's
launcher refuses a JRE) and `GHIDRA_PROJ` (where the analysed project lives, default `ghidra/`) from the environment.
`ghidra/export_listing.py` writes every function's instructions (with call and data references) and an index as text,
for grep; like `out_all.c`, its output is the firmware's code: keep it out of git.

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
