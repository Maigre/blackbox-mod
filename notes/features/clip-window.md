# Clip Window: Slip, Region, Loop Len, Fit, Loop Fade and the Clip-mode Waveform knobs

Release **37.3.1** (dev build 37.3.1d), branch `halo`, cut from `37loop/blackbox-t-021` at 37.3.0; the release
notes are `notes/releases/37.3.1.md` (37.3.0's: `notes/releases/37.3.0.md`). Its history:

- **37.2.0** (branch `37loop/blackbox-t-018`): Slip (release 37.1.1) and its stale-latch fix (`37loop/blackbox-t-004`),
  then Region, Loop Len and the Waveform knobs (P3's three commits, first built on `feat/region`, ported onto the
  fix), a "bank 1 room" commit before the knobs, and JOEBOX's pre-listen cell fix.
- **37.2.1**: the Slip knob's v2 (a detent on 0 and three speed tiers).
- **37.3.0**, after Gate 3 part 1 on the unit (`notes/bench/2026-10-16-gate3-part1.md`): the Clip Window's maths moved
  to bank 2 (D-018); the Gate 3 fix batch: the Waveform's short names (finding 2), Region Auto without Loop Mode (7),
  no endless wrap-grid hold (5), Loop Len taken when it settles (8), the Waveform's file length (12, and the view that
  froze), the knob's v3 (1, hub #t-021), and the pad the browser left stuck (9, 10); then Fit and Loop Fade (hub
  #t-022, findings 3, 4 and 6, D-026; the design and Thomas's answers: `/srv/dev/firmware/re-scratch/fit/DESIGN.md`,
  outside the repo).
- **37.3.1**, at Gate 3b: the Waveform screen's four corner labels white with a 1 px black edge, in every pad mode
  (Thomas, on 37.3.0d: "the current light grey is almost unreadable over the blue waveform"; "simple common rules
  applies everywhere"), all in bank 1 (it is nothing but stock calls, which bank 2's leaf code may not make); H5,
  the playhead line showing the frame heard (finding F-e: on B's region from 6 072 it ran 6 072 frames behind, wrapped
  before Loop End and ignored Slip; Thomas: "yes"); Loop Len's settle from 4 polls to 7, 299 to 341 ms (F-g: an
  ordinary turn rested 216 ms on 1/8 and took it; Thomas: "settle"). Those two change bank 2.

Status on 2026-10-16:

- Every part passes under Unicorn: `test_clipwin.py` 455 checks, `test_bank2.py` 44, `./check.sh` 31 suites,
  0 failed.
- 37.3.1's corner labels (§12b), playhead (§11d) and settle (§11) pass under Unicorn and have not been on the unit:
  §7's checks on 37.3.1d.
- Slip v1 was measured on the unit at Gate 2 (37.1.0d, `notes/bench/2026-10-15-gate2-slip.md`).
- Gate 3 part 1 (37.2.0d, then 37.2.1d) ran on the unit: the first bank-2 install, Region by the knobs, Slip on a
  region, Loop Len 1/4, Off and 1/16, save / power-cycle / reload, the load and the pre-listen, all measured to the
  sample, and ten findings. 37.3.0 answers them. **Nothing of 37.3.0 has been on the unit yet**: §7 is Gate 3b's run.
- The knob on the unit, 37.2.0d (2026-10-16), Thomas: "blocking at 0 is not great. maybe just a small "pause" not
  a complete block break would help. also accelerator is too fast it seems". The v2 (37.2.1d) answered both; on it,
  at Gate 3, Thomas: "the detent could be a bit stronger at low speed: when approaching 0 i still endup slightly on
  the other side", "acceleration could be smoother too". The v3 (37.3.0) answers those; its feel is for Gate 3b.
- **This build needs both files from the same build on the card**: `BLACKBOX.bin` and `BBEXTRA.BIN` (payload id
  `0x2a0e4094`, §3.5). The maths of every Clip Window hook runs in flash bank 2 (D-017, D-018, §3.5): without the
  matching `BBEXTRA.BIN` every Clip pad plays as on stock, and Slip, Region, Loop Len, Fit and Loop Fade do nothing.
  37.2.x's `BBEXTRA.BIN` does not match: the first boot of 37.3.0 with its own file rewrites bank 2 and restarts once.
- Fit and Loop Fade pass under Unicorn (`test_clipwin.py` §11b, §11c) and have not been on the unit: §6 checks 20–26.
  Fit's polymetric rule rests on what the emulated stock render does with a clip that is no whole number of bars
  (§1 Fit), which the Gate 3 report's 14-beat take did not show on the unit: check 21 measures it again.

Other documents: the decisions are `notes/decisions.md` (D-002, D-003, D-004, D-016, D-017, D-018, D-026) and the
reverse engineering behind it is `notes/re/README.md` §2–§3 (step notes a1, a2, a3, x3). Users read the README bullets
and Known issues. The research model of the hooks is outside the repo, in `/srv/dev/firmware/re-scratch/a2/r2/cw2.py`
(with `k_region.py`, `k_looplen.py`, `k_seam.py`).

## 1. What it does on the unit

### Where the controls are

| where | control | id | values | default | saved as |
|---|---|---|---|---|---|
| Clip pad, Pos tab, row 5 | `Region:` | `0x1c8` | Auto, File, Loop | Auto | `clipregion` |
| Clip pad, Pos tab, row 6; Clip Waveform BL (`Slip`) | `Slip:` | `0x1c9` | −4.000 … +4.000 (−3840 … +3840 ticks) | +0.000 | `clipslip` |
| Clip pad, Pos tab, row 7; Clip Waveform BR (`LpLen`) | `Loop Len:` | `0x1ca` | Off, 1/16, 1/8, 1/4, 1/2, 1 bar, 2 bars, 4 bars | Off | `cliplooplen` |
| Clip pad, Pos tab, row 8 | `Fit:` | `0x1cb` | Off, Auto (Bars), 1/4, 1/2, 3 beats, 1 bar, 6 beats, 2 bars, 4 bars, 8 bars, Auto (Beats) | Off | `clipfit` |
| Clip pad, Pos tab, row 9 | stock's Loop Fade | stock `0xfa` | 0 … 100 % (0 … 1000) | 0 | stock's |
| Clip Waveform TL | `LpS` | stock `0x91` | 0 … Loop End, frames | stock's | stock's |
| Clip Waveform TR | `LpE` | stock `0x92` | Loop Start … the file's length, frames | stock's | stock's |

The Pos tab now reads Loop Mode, Beat Count, Quant Size, Sync, Region, Slip, Loop Len, Fit, Loop Fade. As on every
stock pad page, TL/TR move the selection and BL/BR turn the selected row. All five rows are per pad and saved with the
preset.
At their defaults the pad plays exactly as stock (bit for bit, under emulation).

### Slip

- **What it does.** It shifts what the clip plays against the clock, up to a bar either way. Every sample plays the
  frame stock would play, plus a constant amount, folded round the file (or the region). Stock's own timing is left
  as it is, so launch quantization, the grid, the 256-sample crossfades and the wrap all stay stock's.
- **Sign (D-016).** It works like a CDJ jog: `+` = ahead, `−` = behind. Clockwise pushes the loop ahead of the beat
  (it plays from further into the file, so the hits come *earlier*). Counter-clockwise drags it behind. `-0.480`
  plays every sample half a beat (12 000 samples at 120 BPM) later than stock.
- **Display.** The value is beats.ticks, at 960 ticks to a beat, and the ticks print 0..959 in three digits. So
  `+1.500` is one beat and 500 ticks (1.52 beats), not one and a half. At 120 BPM one tick is 25 samples (0.52 ms)
  and a 1/64 is 60 ticks.
- **Knob feel** (v3, 37.3.0, hub #t-021; the same code on the Pos tab and on the Waveform's BL: both turn through the
  one type-1 turn path, `clipwin_turn`). It goes by the stock accelerator's speed m, 1..6 (about 8/7 × the counts per
  ms over the last 8 events). Every number is a `#define` at the top of the knob section in `src/clipwin_b2.c`
  (`cw_turn`, bank 2 since D-018: retuning means a new `BBEXTRA.BIN`, D-018 (5)). Thomas on v2 (37.2.1d): "the detent
  could be a bit stronger at low speed: when approaching 0 i still endup slightly on the other side", "acceleration
  could be smoother too" (v2's tiers stepped ×3.4, ×5.7, ×1, ×6, ×1 between speeds).
  - **One curve.** Each turn event moves the value by its counts × gain(m) (400 stepper counts a tick, the fractions
    kept by the stepper), gain(m) = `KNOB_GAIN` × (`KNOB_GAIN_STEP` / 256)^(m − 1) = 10 × 1.83^(m − 1). Fitted to the
    bench's knob log (`/data/dev/gate3/knob-log-1.txt`, Gate 3 finding 1: events about 13 ms apart, median counts an
    event by speed 21, 35, 45, 63, 80, 116): at those medians it moves 0.5, 1.6, 3.8, 9.7, 22.5 and 60 ticks an event,
    ×2.3 to ×3.1 a speed. Speed 1 keeps v2's single ticks (one per 40 counts); speed 6 is a 1/64 an event.
  - **The 1/64 grid at the top speed only** (`KNOB_TOP` = 6): there the move is rounded to the 1/64 (`SLIP_GRID` =
    60 ticks), at least one 1/64 in the turn's direction, so round values are easy to hit at speed. From `+0.025` the
    first top-speed event lands on `+0.060`. Below it nothing snaps.
  - **Zero is a detent, not a wall.** A turn that reaches or crosses 0 stops on `+0.000`. If the same turn goes on,
    it passes 0 a hold after it **arrived** there, at its own speed: the hold is counted from the arrival, not from
    the last event, so a steady turn always gets through. The hold is `ZERO_DETENT_SLOW_MS` = 400 ms when the turn
    arrived at speed `KNOB_DETENT_SLOW` = 2 or under, `ZERO_DETENT_MS` = 150 ms when faster. At speeds 1 and 2 the
    knob moves 40 to 120 ticks a second, and a hand that sees 0 needs about a quarter of a second to stop: v2's 150 ms
    let it run 5 to 15 ticks past ("slightly on the other side"). A fast sweep through 0 is meant to pass, so it keeps
    150 ms. Turning the other way leaves 0 at once, and so does a turn that starts from 0 at rest (after the hold).
  - Why a hold in time and not in counts: a counts hold (about 650 counts: ~400 ms at speed 1, 240 ms at speed 2,
    85 ms at speed 6 by the log) would also hold a deliberate turn out of 0 from rest, and the counts per revolution
    are still unmeasured.
  - On a reversal the stock ring's sum of signed counts drops, so the first event back reads a lower speed. That is
    stock's accelerator, kept.
  - It clamps at ±4.000.
  - Each event leaves its counts and its speed in `cw_bank` (`0x720`), and an arrival whether it was slow (`0x4BD`):
    `bbusb.py knob` shows which speeds a hand makes on the unit, and each arrival's hold.
- **When a change is heard.** At the next Sync step, through stock's crossfade, with no added silence. A recorded pad
  defaults to Sync 1/16, so that is within a sixteenth. A launch that is waiting for its Quant point still starts on
  its bar, and it plays the new Slip from its first sample. On Sync None, a change waits for the clip's restart.
- **A step 0 inside the audio** (37.3.3, Gate 3b F-a; D-028). At Attack 0 (`pad + 0xBA1` = 1, stock's default, on
  both pads of the unit's preset) stock starts every pass's step 0, and every launch, without its 256-sample fade-in
  (`0x08065790`: the fade-in moved into the countdown, after H1): right at the file's own start, after the last
  step's fade-out. Slipped, on a region that starts past frame 0, in Loop Len's window, or on a seamless wrap (a
  region or Fit, Loop On, Launch not Trigger: there the last step crossfades into step 0), that start is inside the
  audio, and it clicked out of the notch or sounded the audio twice under the crossfade. `cw_latch` (H1) marks such a
  segment (`cw_bank.fin`: its first frame is not stock's, or it is a pass's step 0, which `cw_hold` flags at each wrap
  in `cw_bank.wrapped`, on a seamless pad); at its first read `cw_slot` (H2) gives it back the fade-in stock gives
  every other step, (fade-in, countdown) = (0, c + 256) → (256, c), before the reader's fade stage runs, so its fade-out
  starts on the same sample: the timing is stock's to the sample. The wrap is then the 256-sample crossfade of any
  step (summed gain 0.73 .. 1), and a launch inside the audio fades in over 256 samples. Unchanged: a launch on the
  file's frame 0 (hard, as stock has it, even on a seamless pad), a pad with an Attack (stock fades every step 0 in
  itself, and the voice's envelope a launch), a pad the hooks leave alone (Slip 0, Region File or the whole file, no
  window, no Fit), and everything without this build's bank 2. Covered too: the Region seam of finding 6 (Loop
  Fade's case): its step 0 starts at Loop Start, or on the seamless wrap from frame 0. Loop Fade's own content
  crossfade at the seam is separate and unchanged.
- **A new file under a playing pad** (a load, a take landing in it, or the browser's pre-listen, which loads every
  highlighted file into the pad it was opened from): stock does not restart the voice, its segments read on at their
  positions in the new file. The segments made for the old file (the sounding one and the pending one) then read as
  stock reads them, unslipped and without the region or the window, and the next segment latches the new file. So
  for up to two Sync steps the pad plays as stock would, then as set.
- **The pad gets its file back from the browser** (Gate 3 finding 9). The browser hands the pad its own file when it
  is left. If the file it had loaded was longer and the pad had played into that file's last step, the step reads at
  a position past the end of the pad's own file: the reader reads nothing there, the position never moves, and the
  step, which stops only on the longer file's end, never ends. Stock then plays only the pad's step 0, once each time
  it comes round, until a stop (on the unit: slot 0 at 315 848 of B's 192 000 frames, the first beat every 2 beats;
  at Slip 0 too). The poll retires such a step at once (`cw_retire`: an active segment with an end whose position is
  past the file's end is marked done, never a launch waiting for its bar), and the pad plays its own file from its
  next pass, in time.

### Region

- **What it does.** A Clip pad plays the loop of the file, `[Loop Start, Loop End)`, as if it were the whole file.
  The loop points are the same ones Sample mode uses. Stock keeps them in Clip mode, and a WAV's own `smpl` loop
  arrives in them. A loop cut from a longer recording therefore needs no Trim, and the file stays whole.
- **The values:**
  - **Auto** (the default, D-003) plays the loop when the pad has one: `0 ≤ start < end ≤ length`, and the loop is
    not the whole file (`[0, ≥ length − 1]` is what a load leaves). Any other pad plays the file. So fresh recordings
    and plain files play as stock. Sample mode's Loop Mode is not asked (Gate 3 finding 7: a take whose points were
    moved on the Clip-mode Waveform has Loop Mode None, a row the Clip pad never shows, and stayed on File in 37.2.x).
  - **File** always plays the whole file, as stock does.
  - **Loop** plays the loop points, the whole file still the whole file: since Auto no longer asks Loop Mode, the
    same as Auto (kept, so presets and an explicit choice still read).
  - The region always plays forward, whatever Loop Mode says (Bidir too).
- **Inside the region:**
  - Beat Count Auto counts the region.
  - The Sync steps divide the region, and Slip shifts within it.
  - The region's end crossfades into its start like any other Sync step (the seamless wrap), provided Loop Mode is
    On and Launch is not Trigger. A region that is not a whole number of beats therefore leaves no gap and no
    doubling at the loop point, even when the whole loop is one Sync step. (Two rows share the name: the Clip Pos
    tab's Loop Mode, On/Off, governs this wrap; Sample mode's Loop Mode, None/Forward/Bidir, is what Auto reads.)
- **A change while the pad plays:**
  - It is heard from the next time the loop comes round. If it is made during the loop's last Sync step, it is heard
    one pass later.
  - A change that makes the loop longer can wait more: it starts where a launch would start the new loop (on the
    Quant, or on the new loop's own length when that is shorter), so it never doubles. When the loop it plays can
    never come round to such a point (a loop under half a beat, which has no grid; or one whose passes never meet the
    new grid), it starts at the next time round instead, and the pass after that falls back into time through
    stock's own snapping: a short gap and one doubled Sync step, once (Gate 3 finding 5: 37.2.x waited for a stop and
    a relaunch).
  - A stopped pad, and a one-shot (Launch Trigger or Loop Off), takes the new region at its next launch.

### Loop Len

- **What it does** (D-004: the KP3's loop, anchored where the music is). When you turn it on, only a window of that
  length loops, in time. The window is the part of the clip that was playing when you engaged it, rounded down to the
  length's grid in the clip. For example, 1/4 engaged during beat 3 repeats beat 3, and 1/16 repeats the sixteenth of
  it that was playing.
- **When it is taken.** Once the knob has stopped on a value: a value other than Off is taken after the pad's poll
  has read it unchanged seven more times (299 to 341 ms after the knob stopped there), Off at once. A turn from Off
  to 1/4 passes 1/16 and 1/8 on the way; 37.2.x took the first of them, so its in-point was a 1/16 of the beat and
  1/4 then forced Sync 1/16 (Gate 3 finding 8). Now 1/4 engages on the beat playing when it is taken. A list value
  is 400 counts and the stock accelerator's speed m is trunc(8/7 × counts a ms), so a turn at speed 3 stays 114 to
  152 ms on each value, at speed 2 152 to 229 ms, at speed 1 229 to 457 ms (the knob log's mean rates: 142, 184,
  241 ms). Speeds 2 and up never settle on a value they pass; a slow step-through, resting about a second on each,
  takes each value in turn. Three polls (128 to 171 ms, the first cut) still took 1/16 or 1/8 at speed 2 (review F1);
  four (171 to 213 ms, 37.3.0) took 1/8 at Gate 3b, where an ordinary turn rested 216 ms on it (F-g). A quick
  correction that rests longer than 341 ms on an overshoot still takes it: the bench's flicks (`ll-off-flick`) rested
  387 to 693 ms on 4 bars, 1 bar and 1/2 before turning back.
  The stutter gesture (Off and on again) takes the beat playing when the knob rests, so within one Sync step only
  when that step is longer than the pause: not a 1/16 or a 1/8 at 120 BPM.
- **Changing it:**
  - Changing the length while it is on keeps the in-point and moves the end.
  - Off goes back to the whole loop in phase, as if it had played on all along.
  - Off and on again within one Sync step takes the same window back (the value turned on again is taken 299 to
    341 ms after the knob rests: within a 1/4 step at 120 BPM, not within a 1/16 or a 1/8 one).
  - A change is heard at the pad's next Sync step.
- **The knob.** It is a list knob: one name per 400 counts, no acceleration (a stock list). It is the same row on the
  Pos tab and on the Waveform's BR.
- **Sync is forced when it has to be.** A window shorter than the pad's Sync step, or one that is not on the step
  grid, needs a finer Sync. Loop Len then sets the pad's Sync, as the app would, to the largest of yours … 1/16 that
  divides the window, its in-point and the clip. The Sync row still shows yours. Yours comes back as soon as the
  window fits it again (a longer length), or at Off.
- **With Region and Slip.** It works over Region (the window is inside the region), and Slip shifts what the window
  plays.
- **When it does nothing:**
  - with Quant None or Sync None;
  - on Slicer pads, and on Sync Slice with markers;
  - with a length of the whole loop or more;
  - without this build's bank 2.

### Fit

- **What it does** (Gate 3 findings 3 and 4: a WAV's Beat Count over a shorter region, and a region that is no whole
  number of beats, stutter at every Sync step, because Mk1 Clip mode never stretches). The loop - the region, or the
  whole file - is made to last a whole number of beats at the tempo: it plays faster or slower (the pitch moves with
  it), so every Sync step lands where the audio already is. Auto takes the nearest whole number of beats (14.015 → 14,
  3.74 → 4, 15.6 → 16; at least one, at most 1 024), counted once per loop length: a tempo change keeps the count and
  changes the speed. A recompute that finds the pad's file closed forgets the count, so a file opened again is counted
  at the tempo then. The list's other values force a length. Thomas at Gate 3 (16/10, ~13:00), of pad 1's 14.015-beat
  take: « that weird length is intended as polyrhythmic loop and should be handled properly », so Auto is not stock's
  Beat Count Auto (the power of two nearest the length, which makes that take 16 beats). That Auto is **Auto (Beats)**
  since D-031 (#t-029), last in the list; **Auto (Bars)**, second, keeps a loop cut by ear on the bar (Thomas, 20/10:
  « fit auto doesnt make the loop metronome syncable »): under a bar the nearest of 1/4, 1/2 and 1 bar, from a bar up
  the nearest whole number of bars, both of the length itself, ties up (5.9 beats → 1 bar, 6 → 2 bars, 14.015 → 4
  bars). A preset saved with Auto loads as Auto (Bars); its lengths load as they were.
- **Polymetric.** A length that is no whole number of Quants (3, 5, 6, 7, 14 beats on Quant 1 bar) comes round every
  so many beats against the bar. Each pass starts one loop after the one before, seamlessly. Under emulation stock does
  not keep such a clip (§5, 11b): it snaps each pass's end to its wrap grid min(Quant, clip), so a 14-beat clip on
  Quant 1 bar has every other pass's end half a bar back, in the past (that pass starts at once over the last step,
  a 1/16 early at Sync 1/16, and the next wrap waits a 1/16 in silence); 7 beats waits for the bar after (a beat of
  silence a pass); 5 beats at Sync 1/2 is cut into two steps of 2 400 ticks. The Gate 3 report has stock wrapping
  pad 1's take cleanly every 14 beats on the unit; the take does not say which of its transients are pad 1's, so §6
  check 21 measures that again. Fit's wrap grid is gcd(Quant, clip), on which every launch point and every pass start
  lies, and its steps divide the clip: one step when the Sync step is the clip or longer (as stock), else gcd(Sync,
  clip), the largest step up to the Sync that divides the clip (14 beats with Sync 1 bar re-sync every half bar, 5
  beats with Sync 1/2 every beat). Like stock's, the steps lie on the clock's grid of their length, so a pad launched
  off the Sync grid (Quant 1/16 under Sync 1/4, a 1/16 after the bar) is pulled onto the beat at its first step - one
  jump, the one Fit Off and the stock image make - and every pass after starts on the grid. (Steps of gcd(Sync,
  gcd(Quant, clip)), this rule's first form, kept such a pad a 1/16 late for good, a whole-bar clip too: the review's
  F1.)
- **Changing it.** It is taken with the region, at the pad's wrap or while it is stopped: heard from the next pass.
  One that moves the wrap grid off the pass that would take it (1 bar → 2 bars on Quant 4 bars) waits with the region
  for a wrap on the new grid (H3′); a polymetric clip's passes are on its own grid, so they are never held for being
  off the bar.
- **With the rest.** Slip shifts the fitted audio (slip_f over the fitted clip); Loop Len loops a fitted beat; a
  whole file fitted is read round its end like a region, so its loop point crossfades too (Thomas's answer 5: no
  stock V-notch). A one-shot lasts the clip. Pitch reads faster on top of the rate, and stock re-places a pitched clip
  at every step, as it does without Fit. At Quant None (no grid) a fitted loop free-runs on exactly its length.
- **When it does nothing:** Off; on Slicer pads and Sync Slice with markers; without this build's bank 2; until the
  poll has seen the engine once (the first block after boot).

### Loop Fade

- **What it does** (Gate 3 finding 6: the region's seam is a hard splice, a single-sample step of 0.13 / 0.21 at every
  wrap). Sample mode's own Loop Fade row (`0xfa`) is on the Clip Pos tab too, row 9 (the design's answer 4). On a pad
  playing a region it crossfades the region's last F frames into the F before Loop Start, as Sample mode does:
  F = (int)((Loop End − Loop Start) × row / 1000), at most Loop Start, equal-gain and linear (FUN_08056fd0 at
  `0x08057146`; its ramps FUN_0805fc08 / FUN_0805fc38, then a sum). Under emulation a mismatched 441 Hz sine's largest
  sample step goes from 0.31 at 0 % to the sine's own (0.058, its steps' crossfades included) at 1 % and 5 %, with
  Fit too.
- **When.** Taken with the region (at the wrap, or while stopped): heard from the next pass.
- **When it does nothing:** a whole file, or a region from frame 0 (nothing before Loop Start); a one-shot (Launch
  Trigger, Loop Off); a region under 2 048 frames; a rate above about 3.9 (the window and its copy no longer fit the
  1 024-frame scratch); a machine mode (Fidelity's readers are `filter.c`'s); while Loop Len is taken (a window goes
  back to its own start, never on into Loop Start: on the region's last beat each repetition would end on the audio
  before Loop Start, the review's F4); without this build's bank 2. There it is bit for bit Loop Fade 0. The class-B pad drops the row (ids above `0xF4`), and the class-H object stores it as
  in Sample mode, unused in Clip mode.

### The Waveform screen in Clip mode

Stock leaves all four knobs blank in Clip mode and draws no loop bracket.

- **TL Loop Start, TR Loop End.** These are Sample mode's own rows and its own knob type (sample positions, shown as
  frame numbers).
  - One step is one pixel of the waveform at the current zoom, and never less than one frame. Pinch-zoom in for finer
  steps.
  - A turn snaps the value onto that pixel grid. For example, one step down from 24 000 at 256 frames a pixel gives
    23 552, exactly as Sample mode's knobs do.
  - They accelerate as stock's position knobs do (×1 … ×6 with turning speed).
  - The ranges are Sample mode's: Loop Start 0 … Loop End, and Loop End Loop Start … the file's length.
  - **The file's length is the pad's** (Gate 3 finding 12): the length the engine measured at the pad's last
    recompute (`fw_src_len`, kept in `cw_bank` as `flen`), for the TR range, the bracket's whole-file test, the
    waveform's playhead clamp and the overview strip. The view's own copy (`view + 0x2390`, the app's store `+ 0x20`)
    is what the app's `0xE` handler `FUN_080A121C` wrote, at `0x080A12D0`, into the **first** cell whose pad record
    holds the asset just opened (`FUN_0809A9C4`: row 0 col 0 first), and the pad load `FUN_080A0AC8` zeroes it. A file
    that two pads' records name (the browser loads its files into the pad it was opened from) gives its length to the
    first of them only: on the unit both pad stores read 192 000 while pad 1 played 336 359 frames, so TR stopped at
    192 000, Loop End 192 000 with Loop Start 0 read as the whole file (no bracket), and the view stopped following
    the playhead at 57 % of the loop (finding (h): the waveform's tick `FUN_080C6C34` clamps the playhead to its
    `+0x254`, which the bind block's `FUN_080C6F44` sets from that length). Without bank 2, or before the pad's first
    recompute, the view's own length is used, as stock does.
  - Turned all the way into each other, they leave no loop, and the pad plays the whole file until they part.
- **BL Slip and BR Loop Len.** These are the Pos tab's rows, with the same text and feel.
- **The names.** A knob there draws one line, "name value", 12 px a character (the 6 × 8 font at double size), in a
  151-px box: left-aligned from x 6 on the left, right-aligned to x 309 on the right. Twelve characters stay in the
  box. The rows' own names ("Loop Start:", "Loop End:", "Loop Len:", 37.2.x) ran the left value under the right
  knob's name (Gate 3 finding 2), so this screen renames them after binding, as stock's Sample mode renames its own
  four ("Str:", "Len:", "LpStr:", "LpEnd:"): `LpS`, `LpE`, `Slip`, `LpLen`. The positions get three letters so
  that eight digits still fit: "LpS 12345678" is 12 characters (a file of up to 99 999 999 frames, 34 minutes at
  48 kHz), where "LpStr 1234567" would already cross into its neighbour from 1 000 000 frames (21 s). "Slip -4.000"
  and "LpLen 4 bars" fit as well.
- **The text, in every pad mode** (37.3.1). Stock greys the four corner knobs once, in the view's constructor
  (`FUN_080A5B90`: colour 9, #666666, into each knob's three labels), and that grey reads 3.3:1 on the waveform's
  cyan (#09D7F5) and 3.2:1 on the background (#141414). One colour cannot fix it: white alone reads 1.7:1 on the
  cyan, black 1.1:1 on the background. So each knob's line is white (palette 15) with a 1 px black edge (14), 12:1 or
  better on both, in the same font, size and names. It is stock's own label draw run nine times on a copy of the
  label: eight times in black one pixel off in each direction, then once in white, all in the label's box inset by a
  pixel (the doubled glyphs touch the box's left and bottom edges: a value that changes then leaves nothing outside
  the box the screen repaints). The label keeps its grey, its box and its dirty flags; only its vtable is a copy of
  stock's (`0x080F17A4`) with the whole draw and the clipped draw replaced (`clipwin_label`, §3.2). Sample, Granular,
  Slicer, New Rec and New Multi get it too: the four knobs are the same ones in every mode. Without this build's bank
  2 both draws are stock's, bit for bit.
- **The white bracket.** It shows the loop Region plays, using the engine's own rule, as soon as you turn. A playing
  pad takes the new loop the next time its loop comes round, so while you turn, the bracket is ahead of what you hear.
  There is no bracket (and the loop points are not heard) on Region File, or when the points are the whole file.
  Slice markers stay visible beside the bracket.

## 2. Workflow: a loop from an unsynced recording

This is Workflow 1 of the plan: a loose take from a phone, or from hardware with no clock, played as a groove-locked
loop with no Trim.

1. **Clock.** On TOOLS, set the internal clock to the tempo you will play at and turn Metro On. On Rec, set
   RecToPlay Off, Lead In Off and Pre-roll Off.
2. **Record.** Pick an empty pad, then INFO > Load/Record: input L+R, Gain, Length Custom, **Rec Quant None** (a loose
   take, so the pad comes out a plain sample). Press REC + PLAY, then STOP. Loading a WAV from the card works the
   same way from here.
3. **Make it a clip.** Set Pad Mode → **Clip**. On the Pos tab:
   - Loop Mode On;
   - Beat Count Auto;
   - Quant 1 bar;
   - Sync 1 bar for melodic material, 1/4 for rhythmic;
   - **Region Loop**.

   On the Conf tab, set Launch Toggle. Trigger plays once and gets no seamless wrap.
4. **Play.** Press PLAY and touch the pad. A fresh take's loop points are the whole file, so for now it plays the
   whole file in sync.
5. **Cut the loop on the Waveform screen.**
   - Turn TL Loop Start to where the loop should begin and TR Loop End to where it should end. Zoom in for finer steps.
   - The bracket shows the cut at once, and the pad plays it from its next wrap.
   - Beat Count Auto rounds the region to whole beats at the clock's tempo, but stock never stretches: a cut that is
     not a whole number of beats stutters at every Sync step (Gate 3 findings 3, 4). Set **Fit Auto** (Pos row 8): the
     loop then lasts the nearest whole number of beats, a little faster or slower (and higher or lower), and a cut
     that is not a whole number of bars plays as a polyrhythm against the bar. Or a Fit length, to force one.
   - A click at the loop point (the cut's end and start do not meet): **Loop Fade** (Pos row 9) a few %.
   - **Or the stock way, with audition**, before step 3: in Sample mode set Pos Loop Mode Forward, set Waveform BL/BR
     to Loop Start/End, and press Trigger until the turnaround is clean. Then set Pad Mode → Clip with Region Auto:
     the loop comes along, because Sample → Clip keeps it. Do not go back to Sample mode afterwards: stock clears the
     loop points on Clip → Sample.
6. **Slip.** Use Waveform BL, or Pos Slip. Turn fast (1/64 steps) to get close to the metronome, then slower (down to
   single ticks) until the hits sit. It stops on 0 on the way (0.4 s if you come in slowly), then goes on if you keep
   turning.
7. **Refine, if needed.**
   - Move TL/TR again. A change is heard at the next wrap.
   - Loop Len (BR) 1/4 or 1/16 loops a beat or a sixteenth of what is playing. Off returns to the whole loop, in phase.
8. **PSET Save.** The preset holds Region, Slip, Loop Len, Fit, Loop Fade and the loop points.

## 3. How it is built

### 3.1 The idea

Stock plays a synced clip as **one segment per Sync step**. Segment j starts on the clock's step grid at source frame
`(int)((float)j × fps)` (fps = pad `+0x1FC`) and crossfades 256 samples with the one before. Only *when* a segment
starts comes from the clock. Each class-B pad has a pool of four segment slots (`pad + 0x30 + k·0x70`), shared by
its two voices (notes/re/a1, a2).

The Clip Window leaves all of stock's timing alone and changes two things:

1. **What each segment plays**, decided once, when stock makes it. A per-slot latch `{rs, vlen, delta, len}` is set
   at the segment start (H1). The reader (H2) then plays frame `rs + ((pos mod vlen) + delta) mod vlen` in place of
   `pos`. Slip is a constant `delta`, Region is `rs`/`vlen`, and Loop Len adds a per-segment term to `delta`. `len` is
   the file's length the latch was made for: while the source's differs (a new file under the playing pad), H2 reads
   as stock does.
2. **What stock thinks the file is.** The four length calls that shape a clip (H3) answer the region's length. Beat
   Count Auto, the frames per step, the steps and the last step's end then follow the region, and stock's own
   machinery does the rest.

A live change marks the pad's *pending* segments done, the guarded drop in `clipwin_tick`. Stock re-makes them in
the same render, and H1 re-latches them. The sounding segment keeps its latch, so the change lands on the next step
boundary through stock's crossfade.

### 3.2 Hooks

All the stock sites are 4-byte `bl` instructions, re-routed in `patches/clipwin.py`. That file rides with the `filter`
set, which imports it. The thunks are in `src/clipwin_thunk.S` and the C is in `src/clipwin.c` (bank 1) and
`src/clipwin_b2.c` (bank 2).

| hook | site (stock function) | stock call | ours | job |
|---|---|---|---|---|
| H1 | `0x0806578C` (`FUN_08065550`, segment start) | `bl 0x0806375C` prefetch | `clipwin_seg_start_b` → `clipwin_seg_start(src, pos, k = [sp+0x20], pad = r4)` | latch slot k (bank 2's `cw_latch`: Slip, region, Loop Len window, the file's length), prefetch where it will really read |
| H1′ | `0x0806541A` (`FUN_08065290`, slice-marker segment) | `bl 0x0806375C` | `clipwin_slice_start_b` → `clipwin_slice_start(src, pos, k = [sp+4], pad)` | invalidate slot k, clear its `h1` bit (`cw_slice`), prefetch unchanged |
| H2 | `0x08066622` (`FUN_08066454`, segment reader; already JOEBOX's `clip_read_b`) | `bl 0x080662E4` | `src/filter_thunk.S` `clip_read_b` now ends in `b.w clipwin_read` | mapped read (`cw_map`: the real position, the seam hint): stock's reader at the real position, or its work done over two fetches at a seam; machine modes through `filter.c`'s `clip_read_ring`; stock's read when the file's length is not the latch's |
| H3 site 1 | `0x08064B2C` (recompute, first length) | `bl 0x080636F0` `fw_src_len` | `clipwin_len_recompute_b` → `clipwin_len(src, pad, 1, —)` | `cw_len`: adopt a new region, Fit and Loop Fade (at this pad's wrap, or when no layer plays; the five store rows Region, Loop Start, Loop End, Fit, Loop Fade read here for it); answer the region's length (Beat Count Auto, frames per step); the file's length kept as `flen` for the Waveform |
| H3 site 3 | `0x08064C5A` (recompute, second length) | `bl 0x080636F0` | `clipwin_len_steps_b` (r3 = r9 = the clip in output samples) | the region's length; a synced clip of one step gets `+0x204` = the clip, not the length; a fitted pad gets Fit's step fields and rate (`cw_fit`, §3.4) |
| H3 site 0 | `0x0806561E` (`FUN_08065550`'s `> 0` check) | `bl 0x080636F0` | `clipwin_len_b` | the region's length |
| H3 site 2 | `0x08065690` (the last step's end, `len − 1`) | `bl 0x080636F0` | `clipwin_len_end_b` | seamless wrap: 1 (end = 0) when Loop On and not Trigger; else the region's length |
| H3′ | `0x08066FAC` (render, the synced wrap) | `bl 0x08064A94` recompute | `clipwin_wrap_b` (r2 = sp + 0x58, the next pass's tick) → `clipwin_wrap(pad, clock, t)` | the recompute with this pad marked wrapping (it adopts); put a grid-moving region back until a wrap on its grid (`cw_hold`) |
| H3′ | `0x08066E9E` (render, the unsynced wrap) | `bl 0x08064A94` | `clipwin_wrap_free_b` (r2 = 0) | the same, no grid check |
| H5 | `0x080668FC` (render, msg `0x4A`: the playhead) | `bl 0x0804F504` post | `clipwin_playhead_b` (r2 = r6 the pad, r3 = fp the slot) → `clipwin_playhead(ui, msg, pad, k)` | the position (`+0x10`) the frame heard, as slot k's latch maps it for the reader (`cw_playhead` → `cw_map`: region, Slip, Loop Len's window; Fit's rate is in stock's positions), per mille (`+0x14`) as stock reckons it, `(float)pos × 1000 / file`; stock's message without a latch or bank 2 |
| F | `0x080B0746` (set value) and `0x080B0E18` (type-1 turn) | `bl 0x080B0528` formatter | `clipwin_format(knob)` | Slip's beats.ticks text (`cw_text`; type 1 or 9, id `0x1C9`, not frozen) |
| K | `0x080B0DDE` (`FUN_080B0D54`, type-1 turn) | `bl 0x080B0B74` stepper add | `clipwin_turn(stepper, counts)` | Slip's knob (`cw_turn`): one gain curve by the speed, the 1/64 grid at the top speed, a detent on 0 held longer after a slow arrival |
| W bind | `0x080A582A` (`FUN_080A54A0`, the Clip bind block's last unbind, BR) | `bl 0x080A7EE0` binder | `clipwin_bind` | bind TL `0x91`, TR `0x92`, BL Slip, BR Loop Len through the stock binder with the view store's values; name them `LpS`, `LpE`, `Slip`, `LpLen` (`FUN_080B03C0`) and recompose each line (`FUN_080B0480`) |
| W zoom | `0x080A53B0` (`FUN_080A53A2`, every bind and zoom change) | `bl 0x080A52C4` | `clipwin_zoom(view, zoom)` | Clip only: the waveform's `+0x254` and the overview strip (`FUN_080C4DF0`) given the pad's file length; TL/TR step = max(1, zoom), then range, then value; the bracket |
| W refresh | `0x080A5B0E` (the Waveform refresh's Clip case) | `bl 0x080C6E8C` slice markers | `clipwin_wave(wave, slices)` | stock first, then range/value of TL/TR, re-value BL/BR when the store differs, the bracket |
| L | `0x080A660A`, `0x080A6612`, `0x080A661A`, `0x080A6622` (`FUN_080A5B90`, the Waveform view's constructor: TL, BL, TR, BR) | `bl 0x080B02E6` the knob's colour (9) | `clipwin_label(knob, colour)` | stock's colour, then the knob's line (`+0xF4`) given `label_vt`, stock's label vtable with `label_draw` / `label_clip`: nine passes of stock's draw (`FUN_080C3D2C`, `FUN_080C3FC6`), black around, white on top, in the box inset by a pixel, while `b2_live()`; stock's draw otherwise |
| P | `0x080EF998` and `0x080EF290` (both copies of the Clip Pos page) | u16 `0, 0, 0, 0, 0` | `0x1C8, 0x1C9, 0x1CA, 0x1CB, 0xFA` | the five rows in slots 5–9 (stock's own Loop Fade `0xFA` in slot 9) |
| tick | `duck_block` (`src/duck.c`, JOEBOX's hook of `0x0804CE74`), after `insert_tick()` | — | `clipwin_tick(engine)` | one pad a block: Slip and Loop Len from the app's store (`cw_tick`); the segments its file no longer reaches retired (`cw_retire`, with the source's `fw_src_len`); Loop Len's take (`cw_looplen`) and its Sync; the guarded drop (`cw_drop`) |
| H4 | none: `clipwin_tick` sends `cw_looplen`'s message | — | `FUN_08067648(pad, engine, {0x39, 0, cell, 0x94, idx, 0}, engine + 0x128E0)` | Loop Len's forced Sync, as the app's message would set it (stock re-grids live) |
| R | `master_register` (`src/master.c`) | — | `clipwin_register(table)` | `fw_register_list` Region (3 names), `fw_register_num` Slip (type 1, ±3840), `fw_register_list` Loop Len (8 of stock's own strings), `fw_register_list` Fit (10 names, stock's strings but "3 beats" and "6 beats") |
| D | `insert_defaults` tail (`src/insert.c`) | — | `clipwin_defaults(store)` | `fw_store_add` of the four ids `0x1C8..0x1CB` at 0 (`0xFA` is stock's own); a pad store holds 86 of JOEBOX's 96 |
| M | `master_alloc` (`src/master.c`) | — | `CORE_BYTES` `0xC100` on every unit, `cw_bank` its last `0x1000` (D-030; until then `EXTRA_BYTES` `0x2E100` behind Prism's, `0x2D900` and `0x800` before Fit) | the bank's magic cleared at `block + 0xB100` every boot |

H5 (37.3.1) rewrites only the message: the render keeps stock's position for itself (`pad + 0x248`, its own test
that the position moved).

Every `cw_*` named above is in bank 2 (§3.5); bank 1 keeps the hooks and the stock calls. Without this build's bank 2
each hook is a straight pass to stock: no latch, no region, no forced Sync, stock's text and stepper for the Slip
knob, no bracket. The Waveform still binds its four rows (TL and TR are stock's own Loop Start and End).

### 3.3 State: `cw_bank`

The bank lives in SDRAM at `master_block() + 0xB100`, the end of the block's core, which every unit takes with or
without bank 2 (D-030; `+ 0x83900` before, behind Prism's), with `0x1000` reserved (`0x800` until Fit) and `0x8A8` used (`0x898` until Auto (Bars), D-031). The layout is in `src/clipwin.h`
and the magic is `CWNB`. The magic history: `CWN1` was 37.1.x, `CWN2`
the stale-latch fix (the latch's `len`), `CWN3` the Region step, `CWN4` arrived with Loop Len, and `CWN5` with the
knob's v2 (37.2.1: the bench fields at `0x720`, `zero_hold` gone), `CWN6` with Loop Len's settle (`llv`, `llc`,
37.3.0), `CWN7` with the Waveform's file length (`flen`), `CWN8` with the knob's v3 (`zero_slow` at `0x4BD`), `CWN9`
with Fit (`fit` … `engine`), `CWNA` with Loop Fade (`fade`), `CWNB` with the step-0 fade-in (`fin`, `wrapped`; 37.3.3). (On
`feat/region`,
without the fix, `CWN2`/`CWN3` were Region/Loop Len and the bank used `0x620`.) When the magic is wrong the bank is
cleared whole, with a word loop, and the magic set. `master_alloc` clears the magic at every boot, because SDRAM keeps
its contents through a reset. If there is no block, or no matching bank 2 (`bank()` asks `b2_live()` first, and
nothing sets the bank up without it), every hook passes through. There is no `.data` or `.bss`, and no
exclusive access anywhere (D-013).

| offset | field | meaning |
|---|---|---|
| `0x000` | `u32 magic, scan` | `CWNB`; the poll's pad counter (`q = scan++ & 15`) |
| `0x008` | `i32 slip[16]` | Slip as last polled, ticks (+ = ahead) |
| `0x048` | `u8 *pad[16]` | the class-B pad object, cached by H1 (validated before use: class `0x4C`, same cell) |
| `0x088` | `u8 valid[16]` | bit k: `latch[q][k]` holds |
| `0x098` | `{i32 rs, vlen, delta, len} latch[16][4]` | per segment slot: the region (or the file) and the shift, frames; the file length it was made for |
| `0x498` | `u8 h1[16]` | bit k: slot k was made through H1, not H1′ |
| `0x4A8` | `u8 hinted[16]` | bit k: H2 has hinted `rs` for this slot's crossing |
| `0x4B8` | `u32 zero_at; i8 zero_dir; u8 zero_slow` | the Slip knob's detent: when a turn last arrived on 0, its direction, and whether it came slowly (the long hold) |
| `0x4BE` | `u8 wrap` | 1 + the pad whose wrap recompute is running (`clipwin_wrap`) |
| `0x4C0` | `{i32 rs, vlen} region[16]` | the region each pad plays this pass; `vlen` 0 = the whole file |
| `0x540` | `i32 good[16][2]` | the last loop points from the app's store that made sense (fallback source) |
| `0x5C0` | `i32 origin[16]` | Loop Len's in-point, ticks into the clip |
| `0x600` | `u8 ll[16]` | Loop Len as taken (0 Off, else `W = 240 << (ll − 1)`) |
| `0x610` | `u8 forced[16]` | 1: Loop Len has forced the pad's Sync |
| `0x620` | `i32 sf[16][4]` | Slip's part of `latch[q][k].delta`, frames |
| `0x720` | `i16 knob_counts; u8 knob_speed` | the Slip knob's last turn event: its counts and the accelerator's speed (`bbusb.py knob`) |
| `0x723` | `u8 llv[16]` | Loop Len as the poll last read it from the store (the settle, finding 8) |
| `0x733` | `u8 llc[16]` | the polls since it changed: taken at `LL_SETTLE` (7; 4 until 37.3.0) |
| `0x744` | `i32 flen[16]` | `fw_src_len` at the pad's last recompute (H3 site 1): the Clip Waveform's file length (finding 12) |
| `0x784` | `u8 fit[16]` | Fit as taken with the region (0 Off, 1 Auto (Bars), 2 … 9 = 1/4 … 8 bars, 10 Auto (Beats)) |
| `0x794` | `u8 pfit[16]` | the Fit the pad had before its wrap's adoption: `cw_hold` puts it back |
| `0x7A4` | `u8 fon[16]` | 1: the pad's last recompute stored Fit's step fields (the poll's tempo check, the whole file's seamless end and latch) |
| `0x7B4` | `u16 abeats[16]` | Fit Auto's count … |
| `0x7D4` | `i32 alen[16]` | … and the length it counted (0: none) |
| `0x814` | `f32 bpm[16]` | the tempo a fitted pad's step fields were made at |
| `0x854` | `u8 *engine` | the engine (the clock) as the poll last had it: `cw_fit`'s tempo |
| `0x858` | `u16 fade[16]` | Loop Fade as taken with the region (0 … 1000) |
| `0x878` | `u8 fin[16]` | bit k: slot k's segment starts inside the audio and gets its fade-in back at its first read (`cw_latch` → `cw_slot`, F-a, §1 Slip) |
| `0x888` | `u8 wrapped[16]` | 1: the pad's wrap has just been recomputed (`cw_hold`): its next segment is that pass's step 0, not a launch (cleared by that latch, a slice segment or the poll) |
| `0x898` | `u8 abars[16]` | 1: `abeats` is Auto (Bars)' count, 0: Auto (Beats)' (the other Auto chosen counts again; D-031) |

Bank 2 reads and writes every field but `magic` and `scan` (D-018), so every offset it is compiled against is pinned
by `_Static_assert` in `src/clipwin.h`, with the pad, class-H, segment, stepper and waveform fields and the settings it
uses. Moving one makes a new bank-2 payload. Another assert pins the knob's fields and the size, which
`bench/bbusb.py knob` and `test_clipwin.py` read. The D-018 move changed no offset, so it kept the magic (`CWN5`
then).

### 3.4 The maths

**Stock fields** (pad): `+0x1FC` fps (f32 source frames per step), `+0x208` tps (i64 ticks per step), `+0x210` n
(steps), `+0x220` the Sync step in ticks, `+0x230` the wrap grid = min(Quant, clip), `+0x1F4` Loop On, `+0x1F5`
synced (Quant and Sync both not None), `+0x1F8` Launch + 1. **Segment fields**: `+0x08` the frame (i64, stock's
"virtual" position; never rewritten), `+0x1C` frac, `+0x20` start delay, `+0x34` step j, `+0x3C` first block (a
pending launch).

**Slip in frames** (H1; `vlen` is the region's length, or the file's):

```
clip   = tps × n                                 (not Beat Count × 960: Beat Count 29 on Sync 1 bar is 7 × 3977 = 27 839)
slip_f = floor(slip × vlen / clip)               in double (the M7's FPU; no 64-bit division in the cave); 0 when clip = 0
```

**The latch** (H1, slot k; start = seg `+0x08`, j = seg `+0x34`):

```
delta = slip_f                                               Slip, over the region
      + (int)((float)w × fps) − start      if the Loop Len window applies (below)
delta = delta mod vlen  (floored);   sf[q][k] = slip_f;   len = fw_src_len (the file's, not the region's)
prefetch at max(0, rs + ((start mod vlen) + delta) mod vlen − 8)      (replaces stock's max(0, start − 8))
```

H1 latches when a region applies, when Slip ≠ 0 with a clip, or when a window applies. Otherwise it invalidates the
slot, and the segment reads as stock. A region under half a beat on Beat Count Auto is a clip of 0 ticks. It still
latches its region, with Slip forced to 0.

**The read** (H2, the slot `k = (&frac − pad − 0x4C) / 0x70`): `real = rs + ((pos mod vlen) + delta) mod vlen`.

- If `fw_src_len(src)` is not the latch's `len`, the file changed under the segment since H1 (the slot closes, then the
  new file opens: notes/re/x3 §§3-4). H2 then calls stock's reader at `pos`, unmapped, as stock would read the new
  file; the next segment H1 makes latches it. Not the source pointer: the key map hands the freed asset entry out
  again, so a load often keeps it.

- If the read's window `[real, real + count)` stays inside the region, H2 calls stock's reader at `real`. Here
  `count` = n at rate 1 with frac 0, else `(int)(n × rate) + 8`, capped. Stock adds `used` to its own unmapped
  position, which the next block maps again.
- If it crosses the region's end, which happens once a pass, H2 does stock's reader's work with the fetch split in
  two parts (up to the end, then from `rs`). The stock kernel `0x080603EC` then interpolates across the seam as if
  the file were circular. Mono and stereo are both covered, and the straight copy at rate 1.
- A machine mode (Fidelity SP1200 … SP 45) goes to `filter.c`'s `clip_read_ring` over the circular region, at the
  seam or not.
- **The seam hint.** When the read is within 16 384 frames of the region's end (the provider's sure reach, about 128
  blocks at rate 1), H2 prefetches `rs` once for that slot. Stock never hints a seam inside a segment.

**Region.**

- **The rule** (`is_loop`, shared by the engine and the bracket):

  ```
  Loop  iff  mode != File  &&  len valid  &&  0 <= ls < le <= len  &&  !(ls == 0 && le >= len − 1)
  ```

  Here `mode` is the Region row and `len` is `fw_src_len`. A length of 0 or the provider's `0x10000000` sentinel
  means no region. Sample mode's Loop Mode (`0x8E`) is not asked (37.2.x asked it for Auto: finding 7).
- **The source.** The loop points are read from the cell's class-H object, `H = *(pad + 8)`, when it is class `0x48`
  on the same cell: `+0xFC` Loop Start, `+0x100` Loop End, in queue order. Otherwise they come from the app's store
  (`0x91`, `0x92`), which keeps the last pair that made sense. The region is
  `rs = ls`, `vlen = le − ls`.
- **What H3 answers.** It returns `vlen` at sites 0, 1 and 3. At site 2 it returns 1, so the last step has no end and
  crossfades into the next pass like any other step; that applies only with Loop On and Launch not Trigger. At site 3
  a synced clip of one step (n = 1, clip > 0) gets `+0x204` = the clip in output samples. Stock times that step by
  the length, which doubles or leaves a gap each wrap.
- **When a new region is taken.** A new region is adopted only at site 1, and only while this pad's wrap recompute
  runs (`wrap == q + 1`) or while neither of its layers plays. A change in mid-pass would leave the steps already made
  pointing past the new end: 11 418 or 23 490 silent samples (a2).
- **The wrap grid.** After the wrap's recompute, `clipwin_wrap` asks bank 2's `cw_hold`, which compares the next
  pass's start tick `t` (the render's i64 at `[sp + 0x58]`) with the new `+0x230`. If `t mod grid ≠ 0` and the region
  changed, it puts the old region back, and `clipwin_wrap` runs the recompute again, so the pass plays as it was.
  Without this, stock snaps that pass's end into the past and starts two passes at once at gain 2, which is what
  stock does on a live Beat Count change from 2 to 4. Ticks past 2³² skip the check.
  It holds only for a wrap that can come (finding 5). `clipwin_wrap` hands it the pad's wrap grid `g` and clip `L`
  (ticks) from before the recompute: the render snaps every pass start to `g`, so the passes start `s` apart, `s` =
  `L` snapped to `g` (a tie down: stock picks the grid point a block early, notes/re/a1), and they meet the new grid
  iff `gcd(s, grid)` divides `t`, within `grid / gcd` passes.
  With `g = 0` (a clip of 0 ticks: a region under half a beat on Beat Count Auto, whose passes start where its length
  ends them) or a `gcd` that does not divide `t` (a 3-bar loop on Quant 1 bar, launched on bar 1 mod 3, cut to 3 beats)
  that wrap never comes, and the region is taken at once. Its first pass then starts off the grid and stock's own snaps
  put the next one back: measured on the 3/8-beat region grown to 2 beats (Sync 1/16), a gap of 496 samples at its
  step 1 and 6 903 samples at gain 2 where its end snaps back (one 1/16 step), then in time.

**Loop Len.**

- **The window** (bank 2, `cw_window`, asked by H1 when Loop Len is taken and `b2_live()` holds). `W = 240 << (v − 1)`
  ticks: 1/16 = 240 … 4 bars = 15 360. It applies in H1 when `W < clip`, `W mod tps = 0` and `origin mod tps = 0`. A
  segment of step j then plays step `w = (origin + ((j·tps − origin) mod W)) / tps` from stock's own product,
  `(int)((float)w × fps)`. A tick-domain formula would be a frame off on a non-integer fps.
- **The take** (bank 2, `cw_looplen`, called from `clipwin_tick`):
  0. **The settle** (bank 2's `cw_tick`, before the take; finding 8): `llv[q]` = the value the poll last read,
     `llc[q]` = the polls since it changed. A value other than Off waits until `llc` reaches `LL_SETTLE` (7: seven
     more polls of the pad, 16 blocks each, so 299..341 ms at 48 kHz; 4 until 37.3.0); until then the taken value
     stays. Off is taken
     at once.
  1. A pending launch (a segment active, not done, `+0x3C` set) means nothing is taken this time. A Sync re-grid
     would sound the launch at once, off its bar. The poll comes back within 16 blocks.
  2. No active segment (the pad is stopped) means `origin = 0`, so the next launch loops from the clip's start.
  3. **The engage** (Off → on). Among the sounding segments it picks the one that started last: the least *signed*
     `e = pos − (int)(j × fps)`. At rate ≠ 1, stock's `0x94` re-index puts j ahead of pos. Its frame is the latch's
     mapped frame with Slip taken out, `((pos mod vlen) + delta − sf) mod vlen`, when the slot is latched, else
     `pos`. The phase is `(u32)(frame × tps / fps)`, and `origin = phase − phase mod W`. Changing W while it is on
     keeps the origin.
  4. **The forced Sync**, when the window does not apply as it is (or is already forced), W < clip and the pad is
     synced and not sliced: start from the user's Sync (store `0x94`; idx 1..5 = 1 bar … 1/16, otherwise 1 bar),
     `t = 3840 >> (idx − 1)`, and halve t while `t > 240` and t does not divide W, origin and clip. It is sent when
     the pad's `+0x220 ≠ t`, so it is re-sent if the app re-sends Sync. `forced = (idx ≠ user's)`. At Off, a forced
     pad gets the user's Sync back (idx ≤ 6).
  5. It returns bit 0 = moved and bit 1 = `msg` holds the class-B param-set's `{0x39, cell, 0x94, idx}` for the
     Sync. `clipwin_tick` (bank 1) sends it through the param-set (H4), then, on `moved`, does the guarded drop, so
     H1 re-latches the pending steps.

**Fit** (bank 2's `cw_fit`, from `cw_len` at H3 site 3, where stock has just stored its step fields). `len` = what the
pad plays (its region, or the file), `base` = `+0x1F0` as this recompute set it (source rate / 48 000), `bpm` = the
engine's `+0x18`:

- beats: with f = `len / (base × 48 000) × bpm / 60`, Auto (Beats) `(int)(f + 0.5)`, Auto (Bars) 1 under f = 1.5, 2
  under 3, else `(int)(f / 4 + 0.5) × 4`; 1 … 1 024, counted once per `len` (`alen`) and Auto (`abars`), counted
  again when an Auto is chosen again or after a recompute that found the file closed (`len` 0 or `0x10000000`); else
  the list's 1, 2, 3, 4, 6, 8, 16 or 32;
- clip = beats × 960; grid = gcd(Quant, clip) (0 for Quant None); step = gcd(Sync, clip) when the pad is synced,
  grid > 0 and clip / Sync > 1, else the clip; n = clip / step; samples = `(int)(48000 × (clip / 960 / bpm) × 60 +
  0.5)` (as `FUN_08070420`);
- stored: `+0x230` = grid, `+0x208` = step, `+0x210` = n, `+0x1FC` = len / n, `+0x204` = samples / n, `+0x1F0` = len /
  samples. Every segment takes `+0x1F0` as its rate (`FUN_08065550`, `0x080656DE`), so stock's re-placement at each
  step, the last step's end countdown and the Sync re-index all reckon with it; what stock goes on to compute from
  site 3's answer (`+0x23C`, `+0x240`, `+0x244`) follows. The app is still told stock's clip (`+0xBA8`, msg `0x8D`).
- the seamless end and the circular latch take a fitted file as a region of the whole file (`fon`);
- the poll (`cw_tick`, bit 3) recomputes a fitted pad whose `bpm` is not the engine's now (exactly: a tolerance would
  leave the clip off the tempo by up to it, a re-placement jump at every step); the steps already made play out at
  their rate.

**Loop Fade** (H2: bank 2's `cw_map`, `cw_hint`, `cw_fade`; bank 1's `clipwin_read`). `cw_map` gives the real
position and F (above); the read takes it but in a machine mode and when 2 × count ≤ the scratch's 1 024 frames.
A window that reaches into [le − F, le) takes the seam's path: the window as read over the region, the same window
again `vlen` earlier (before Loop Start) after it in the scratch, then `y = x + g (copy − x)`, g = (j − (le − F)) / F,
0 before, 1 from le on (there the copy is the region's start itself), before stock's kernel. F is 0 while Loop Len is
taken (`ll`). The seam hint (`cw_hint`, once per crossing segment) goes to rs − F, where the copy starts, and to rs,
when the read takes the fade (a hint is sure of 16 384 frames, a fade can be longer, and on a slipped pad nothing else
hints rs: the review's F2), else to rs alone, as before.

**The guarded drop** (bank 2's `cw_drop`, from `clipwin_tick` on a Slip or Loop Len change). Each slot that is
active, not done and has delay > 0 is marked done. The exception is a slot with `+0x3C` set: dropping a pending
launch would sound it at once, off its bar. `cw_drop` returns those slots that H1 made, and `clipwin_tick` latches
them again in place (`cw_latch` with pos −1) and prefetches there.

**The Slip knob** (v3). The stepper has 400 counts per step for type 1, and the stock accelerator speed is m (1..6).

- First, the detent: on 0 (v = 0), an event in `zero_dir` less than the hold after `zero_at` is dropped; the hold is
  `ZERO_DETENT_SLOW_MS` if `zero_slow`, else `ZERO_DETENT_MS`.
- The move: `a = counts × g / 256`, `g` = `KNOB_GAIN` × 256 times `KNOB_GAIN_STEP` / 256 for each speed above 1
  (integer, as `cw_turn` computes it; 10, 18.3, 33.6, 61.5, 112.6, 206.4 a count).
- m < `KNOB_TOP`: it adds `a`, unless that would reach or cross 0, in which case the target is 0.
- m ≥ `KNOB_TOP`: the target is `v + a / 400` rounded to the nearest 1/64 (half away from 0), at least one 1/64 in
  the turn's direction, or 0 if that crosses it.
- A target of 0 reached from another value is an arrival: `zero_at` = now, `zero_dir` = the direction, `zero_slow` =
  m ≤ `KNOB_DETENT_SLOW`.
- The value is set by parking the accumulator mid-step on the target: `(target − start) × step + step/2 − acc`.

### 3.5 Bank 2

The maths and the policy of every hook are in `src/clipwin_b2.c`, which runs from bank 2 (D-017, then D-018 — Thomas
at Gate 3: "move everything (that can be moved) to bbextra then so we give back room now"). Loop Len's window
(`cw_window`) moved first, in the "bank 1 room" commit, then its take (`cw_looplen`) with the Waveform knobs; D-018
moved the rest of the Clip Window's own code, fourteen leaf functions in all:

| function | for | what it does |
|---|---|---|
| `cw_pad` | every pad hook, `cw_tick` | the pad's index 0..15 from its cell, −1 for anything else |
| `cw_len` | H3 | adopt the region and Fit at site 1 (class-H points, or the store's with the last good pair), Region's rule, the length told, the seamless last step, the one-step clip's timing |
| `cw_fit` | H3 site 3 | a fitted pad's step fields and rate (§3.4) |
| `cw_hold` | H3′ | the wrap-grid hold: put the region (and Fit) back when it would move the grid off this pass |
| `cw_latch`, `cw_window` | H1, the poll | the latch: Slip's shift, the region or the file, Loop Len's window; the prefetch point |
| `cw_slice` | H1′ | clear slot k's bits |
| `cw_slot`, `cw_map`, `cw_hint` | H2 | the slot the reader's fraction belongs to and its latch; the real position and Loop Fade's frames; the one seam hint per crossing segment |
| `cw_fade` | H2 | Loop Fade's crossfade over a read's window |
| `cw_tick`, `cw_looplen`, `cw_drop` | the poll | the clamps, Loop Len's settle, the pad check, Loop Len's take and its Sync message (R6), Fit's tempo, the guarded drop and the launches to latch again |
| `cw_retire` | the poll | a segment with an end, past the end of the pad's file (a file swapped under it), marked done (finding 9) |
| `cw_turn` | K | the knob's gain curve and its detent (`KNOB_*`, `SLIP_GRID`, `ZERO_DETENT_*` live here) |
| `cw_text` | F | `+b.ttt`, as `"%c%d.%03d"` would print it |
| `cw_bracket` | W | Region's rule over the view's store, the bracket's fields and dirty flag |

- They are leaf code: they read and write what they are handed (the bank, the pad and its segments, the stepper, the
  waveform widget, a message buffer) and call nothing outside their file. `test_bank2.py` enforces that, because bank 2
  lives through every bank-1 install and a call out of it would go stale; it plants a `bl` in each to prove its scan
  still sees one.
- Bank 1 (`src/clipwin.c`) keeps the hooks, every stock call (the settings lookup, the source's length and prefetch,
  the readers and the kernel, the class-B param-set, the recompute, the knob's ring, stepper, text and redraw), the
  bank's set-up and the Waveform's knob binding. `bank()` asks `b2_live()` first, and `clipwin_format`,
  `clipwin_turn` and the bracket ask it too, so a bank-2 function runs only when this build's payload is up there and
  reads clean. Otherwise every hook passes through to stock (§3.2).
- Slip 0, Region File and Loop Len Off stay bit-identical to stock with bank 2 and without it (`test_clipwin.py` §3,
  §11). What costs: one `b2_live()` (three reads of `cpu.c`'s state) per hook call, and bank 1's argument set-up:
  about +95 instructions per block per playing Clip pad, measured under Unicorn (D-018 (6)), not yet on the unit.
  The Gate 3 fix batch adds about 13 more (the poll's settle and `cw_retire`, one pad a block): 453.5 → 466.2 a block
  at Slip 0 / File, 568.5 → 581.3 at Slip 480, 633.6 → 646.4 with a region, 502.9 → 515.4 with Loop Len 1/4.
- Bank 2's id hashes its `.c` files only (`build.sh`). Bank 1 pairs with the payload on its sum, and a bank-1-only
  edit of `clipwin.h` leaves bank 2's bytes, and so needs no reflash.

**Sizes, this build** (`arm-none-eabi-size -A out/cave.elf`, 37.3.1): `.cave` 57 728 of 57 736 B (8 free; 57 160 before
the dev build's bench tools, +568 B, §6) and
`.bank2` 16 724 B; the release build (`RELEASE=1`: no USB peek / poke) 57 040 (696 free), the same bank 2. The
bank-2 payload header is id `0xce1ead5b`, len `0x4180`, sum `0xc6b2bdbc`. 37.3.1 took 416 B of the cave (the corner
labels 288, H5 128) and 72 B of bank 2 (`cw_playhead`; the settle is a constant). 37.3.0 (and 37.3.0d):
`.cave` 56 744 (992 free), `.bank2` 16 652, id `0x2a0e4094`, len `0x4120`, sum `0x2cbfbf38`. Loop Fade took 144 B of the
cave (its store row, the second fetch, the hint's place and its second hint at rs, the count before the machine
readers) and 268 B of bank 2 (`cw_fade`, F in `cw_map`, `cw_hint`). Fit before it: `.cave` 56 600 (1 136 free),
`.bank2` 16 384, id `0xd926e3db`, len `0x4020`, sum `0x1c35c65c`; it took 128 B of the cave (its row and names, the
two store rows read at site 1, the poll's recompute; 8 of it the payload's length past 0x4000, no longer an immediate
in `b2_ok` and `header_ok`) and 700 B of bank 2 (`cw_fit`, the whole file's seamless end and latch, the hold's Fit,
the tempo). Before that, the Gate 3 fix batch's final commit:
`.cave` 56 472, `.bank2` 15 684, id `0x85810156`, len `0x3d60`, sum `0x27d47ee1`. The Gate 3 fix batch (the
labels, Region's rule, the hold, Loop Len's settle, the Waveform's length, the knob's v3, `cw_retire`) took 168 B of
the cave (the labels +56, Region's rule −8, the hold's old grid and clip +8, the Waveform's length +88, the poll's
retire +24) and 272 B of bank 2 (Region's rule −28, the hold +44, the settle +56, `flen` +8, the knob's v3 +112,
`cw_retire` +80). Before it (D-018):
`.cave` 56 312 (1 424 free), `.bank2` 15 412, id `0x78b96508`, len `0x3c60`, sum `0xc8978c56`. Before D-018 (37.2.1):
`.cave` 57 624 (112 free), `.bank2` 13 540, id `0x2c4676ca`, len `0x3500`, sum `0x73f8a581`. The previous payloads,
release 37.1.1 (and 37.1.x with the stale-latch fix), id `0xf5f0171b`, len `0x3280`; `feat/region`'s 37.2.0 build,
id `0xfd79d330`, len `0x3480`. How the cave got here: notes/re/README.md question 5.

### 3.6 What stays stock

- **The timing.** When every segment starts, launch quantization, the 256-sample crossfades, the Sync step grid and
  its live re-grid, wrap scheduling, one-shots, retriggers and Sync None restarts are all stock's.
- **The reader.** The reader and its kernel (called at the mapped position) and the machine modes' DSP (`filter.c`)
  are unchanged. Stock's segment positions are never rewritten.
- **The engine and the app.** The engine ignores `0x1C8..0x1CA`: the class-B param-set drops ids above `0xF4`. Stock
  stores and saves the rows through `SetCellParam`. The view's generic forward stores the four Waveform knobs with no
  code of ours.
- **Excluded pads.** Slicer pads and Clip pads on Sync Slice with markers play stock (their segments start in H1′).
- **The display.** Stock's Beat Count, Quant and Sync rows are unchanged; a forced Sync is not shown. The playhead
  line (msg `0x4A`) is ours since 37.3.1 (H5): the frame heard.

## 4. Limits and known issues

**Slip**

- It needs this build's bank 2 (§3.5), as Region and Loop Len do. Without it the row is there and saves, but does
  nothing; it reads stock's plain number of ticks and turns as a stock number row.
- It does nothing on Slicer pads, or on a Clip pad set to Sync Slice with slice markers.
- On Sync None, a live change waits for the clip's restart (len − 257 samples).
- `+1.500` reads as beats.ticks, which is 1.52 beats, not one and a half.
- **A file loaded under a playing pad** (the browser's pre-listen loads every highlighted file into the pad too)
  plays as stock would, unslipped and without its region or window, for up to two Sync steps, then as set (§1). Fixed
  here: before the fix the pad kept mapping its latches over the old length until its next segment, silent past a
  shorter file's end or with the old shift (`37loop/blackbox-t-004` `9ac8c24`, ported into each P3 step). The
  streaming misses and stock's own gaps after a file change are stock's and stay.
- **A fitted pad stuck on its Slip, seen once** (Gate 3b part 2, F-l, 2026-10-19, 37.4.0d; revised 2026-10-20):
  pad 1 (Fit Auto, Sync 1/16) played slipped by −0.645 whatever its Slip row. Its takes at Slip 0 and −0.645 were
  bit-identical, and both equal the slipped take of every other day to within the same 75 samples (37.3.0d's
  `slip_fit.wav`, 37.3.2d, 37.3.3d run-7, 37.4.0d run-8, 20/10's). Its latch held −0.645's shift (320 216). Thomas
  had turned it to 0 by hand ("slip on pad 1 is not applied"); with Fit Off it followed its Slip again. Not the build:
  on 2026-10-20 the same image, freshly booted, took every change exactly (the mailbox set on a stopped pad then
  started, changed while playing, a stop and start; a browse from B over pad 1's file for 10 s; the Slip knob; Loop
  Start moved and back). A state the pad got into on 19/10 between autogate run-8 (10:35) and 18:20; what it was is
  not known. If it comes back, before touching anything: `bbusb.py slip` and `fit`, the pad's rows, its latch
  (`cw_bank + 0x98`) and slots, an 8 s take at its Slip and one at another; and what the pad went through since boot.
- **The click on pad 1 at Slip −0.645** (F-a, Gate 3b 3b-19, `slip_fit.wav` against `poly_fit.wav`): **fixed in
  37.3.3, on the unit too.** 2026-10-20 (37.4.0d): pad 1 at Fit Auto, Sync 1/16, its slip checked (−7 874 = +16 126
  modulo a beat against Slip 0): the largest recurring step 0.0197 at −0.645 and 0.0197 at Slip 0 (37.3.2d: 0.092).
  The 37.3.3d run-7 and 37.4.0d run-8 takes (0.0217) are slipped too, so their result stands (doubted on 19/10 over
  F-l above). It is not the fold (the take's ends meet; the fold, 16 126 samples into each pass, is clean) but the
  slipped pass's wrap (step 55 → step 0, on the beat), where for about 180 samples the output was the content twice
  over (0.193 where the delayed unslipped take has 0.099). Traced on the unit (37.3.2d, `auto/run-1/fa_slots.csv`):
  every ordinary step's segment starts with fade-in 256 / countdown 5 744, each pass's step 0 with 0 / 6 000, because
  both pads have Attack 0 (`pad + 0xBA1` = 1, stock's default): stock then starts every step 0 hard
  (`0x08065790..0x080657BC`, after H1). Every Unicorn run until 37.3.3 had `0xBA1` = 0, so none saw it. Thomas: "an
  automatic crossfade" (D-028). The cure is in bank 2 (§1 Slip, "A step 0 inside the audio"). A fold mid-step on a
  file whose ends do not meet is still a hard splice (H2's two-part read): no declick is built for it (Loop Fade
  cannot reach a whole file), since the click heard was not that.
- **The pad stuck after the browser** (finding 9, stock's own, with or without Slip): fixed by `cw_retire` (§1),
  with this build's bank 2. The 99 % load peak seen during it (finding 10): under emulation the stuck pad's block
  costs about 28 % more (4 456 against 3 471 instructions a block, the stock code included) and asks a prefetch every
  other block, of a position past the file's end (none once it has recovered); what those do on the SD side is the
  unit's to measure.

**Region**

- It does nothing on the pads Slip ignores, nor without this build's bank 2 (no bracket either).
- Clip → Sample clears the loop points (stock).
- A Beat Count that is not Auto, including one read from the WAV's `acid` chunk at load, is taken as the region's
  length in beats.
- A stopped pad, and a one-shot, takes a new region at its next launch. Until then the clip length it reports (msg
  `0x8D`, Beat Count Auto's display) is the old one.
- **A region under half a beat** counts 0 beats on Beat Count Auto, as stock counts a file that short. It loops on its
  own length, restarting 125 samples early with a 379-sample overlap at peak 1.69 (stock's 9 000-frame file: 8 625
  sample period, peak 1.66), and Slip does nothing. Give it a Beat Count.
- **A change that would put the pass off its wrap grid** waits for a wrap on the new grid. When that wrap cannot
  come (a region grown from under half a beat, or passes that never meet the new grid) it is taken at the next wrap
  instead, at the cost of one pass out of time: a short gap and one Sync step doubled at gain 2 (§3.4). 37.2.x waited
  for a stop and a relaunch there (Gate 3 finding 5).
- A WAV's `smpl` loop end is stored inclusive (`dwEnd`), so such a region is one frame short. It is kept that way;
  nothing hears it.
- Taking a pending region at the relaunch recompute sites (`0x08068312` and the others) is not modelled (open question
  13). A pad relaunched while it plays keeps its region.
- SD streaming at the region seam has not been run on the unit. The hint is checked, the cache is not (miss counter
  `0x24013930`, question 9).

**The playhead** (H5, 37.3.1)

- It shows the frame each segment reads, as the reader maps it. At a step change the render posts the fading
  segment's position too (its tail, past its step), as stock does: for a block (2.7 ms) the line can show that frame,
  in Loop Len's window the frame after the window's end, before the new segment's post. Under emulation 4 posts in
  887 on a 1/4 window; whether the screen ever draws one is the unit's to show.
- Slicer pads and Sync Slice with markers, a file loaded under a playing pad (until its next segment) and a pad
  without bank 2 keep stock's line.

**Loop Len**

- **When it does nothing.** It needs Quant and Sync, and a pad that is synced. It does nothing on the pads Slip
  ignores, or with a length of the whole loop or more.
- **When it is taken.** It is taken from what the pad plays. Set while a launch waits for its bar, it starts once the
  pad plays. On a pad not played since power-on, it starts at the pad's first launch.
- **A stopped pad forgets its in-point.** Its next launch loops from the clip's start. This was chosen so that a
  relaunch, a power-cycle and a preset reload behave the same, and **the rule needs Thomas's OK**. Whether a preset
  load stops the pad is not verified: if it does not, a playing pad keeps the old in-point.
- **The Sync row while forced.** It still shows yours, and turning that knob puts yours back for up to 43 ms before
  Loop Len sets it again. While forced it may also move to a coarser Sync when one fits; each such move is one of
  stock's own re-grids.
- On a loop the length does not divide (a 3-beat loop with 1/2), the window starts over with the loop.
- **At rate ≠ 1** (any 44.1 kHz file), stock's step re-index can leave the playing segment a step ahead of its frames.
  The in-point is then the clock's half (origin 0), and the re-indexed segment plays on to its end before the window
  starts. This follows D-004; listen on the unit.
- **Off drops the pending step.** Stock re-makes it at once, so its prefetch leads by only the rest of the current
  step, and it may jump far back on a 2–4-bar clip (question 9). If misses show, add one prefetch of the in-phase
  position at Off.
- **Without this build's bank 2**, the row is there, turns and saves, but does nothing, as Slip and Region (D-018).
  An older payload in bank 2 also switches off Prism, Confetti and the inserts. Whether to show `---` instead is open
  question 30, Thomas's call: it measured +48 B, which the release build's cave has (696 B free; the dev build's has
  8, after its bench tools).
- **Not run anywhere:** Pitch with it on; a Trigger or Gate relaunch with it on; a Region or Beat Count change with it
  on (the in-point is kept and may fold round a shorter clip).
- A take right after a file change (review F1, release 37.2.0): Loop Len turned Off and on again within two Sync
  steps of a new file loaded into the playing pad maps the sounding segment through its old latch (`cw_looplen` does
  not check `len`, H2 does), so the in-point can be the old window's beat (probe: origin 0 where 1 920 is played).
  Fix later in bank 1: `clipwin_tick` clears the valid bits of latches whose `len` differs from `fw_src_len` before
  `looplen()` (a few bytes, no new bank-2 payload).

**Fit**

- It changes the speed, so the pitch: it is not a time-stretch (P6).
- The Beat Count row and the clip length the app is told (msg `0x8D`) stay stock's.
- A tempo change is followed at the pad's next poll (within 16 blocks, 43 ms); the step already under way finishes at
  the old rate, and overlaps the next once at gain 2, as stock's own steps do at a tempo change.
- A fitted loop that must play at another rate than 1 reads through stock's interpolating kernel: under emulation
  8 211 instructions a block for the 3.74-beat region at rate 0.935 against 3 859 Fit Off (the whole pad block, stock
  code included); a 48 kHz loop fitted to its own length (rate 1) stays on the straight copy. Our own code: 702 a block
  fitted against 700 Fit Off on the region; 636 against 482 on a whole file (read round its end now).
- Steps on a frame that is not whole (a 44.1 kHz loop's 5 154.06 frames a step) are placed where stock places them,
  `(int)(j × fps)`: up to a frame's re-placement at a step, as on stock (§5).
- The hold restores Fit's value but not Auto's count: a region change held over a tempo change re-counts the old
  length at the new tempo.
- Auto's count lives as long as the pad's file stays open (it is forgotten at a recompute that finds the file closed).
  Whether a preset load closes a file the new preset plays too is not known: if not, a preset at another tempo keeps
  the count made at the old one, where a boot into it counts at its own (Gate 3b, check 21; the review's F3).
- The tempo check is exact: a tempo that moves in small steps (an external MIDI clock, if 3.1.9's engine follows it
  that way) recomputes a playing fitted pad at most once per 16 blocks, each a small rate change at its next step;
  not measured on the unit (check 23; the review's F5).

**Loop Fade**

- It does nothing where §1 says (a region from frame 0, a whole file, a one-shot, under 2 048 frames, above a rate of
  about 3.9, a machine mode); the row shows on every Clip pad all the same.
- While the fade plays the pad reads its file in two places (the region's end and the frames before Loop Start): the
  seam hint goes to where the copy starts and to the region's start. The copy's frames past the hint's reach (a fade
  over 16 384 frames: 25 % of a 4-second loop is 24 000) lean on the card's own read-ahead, as the rest of any stock
  step longer than 24 576 frames does: Gate 3b check 26, with Slip too.
- While Loop Len is taken the region is not faded: a window that holds the seam splices there as at 0 %.
- Cost, under emulation (the whole pad block, stock code included, over a pass of the 3.74-beat region): 4 042
  instructions a block at 5 % against 3 859 at 0 % (a read in the fade about 3 100 more); every read of a pad with
  Loop Fade set pays its length check.

**The Waveform knobs**

- Loop Start turned up to Loop End leaves no loop, and the pad plays the whole file until they part.
- On Region File the knobs move the points but nothing is heard and no bracket shows.
- **Not checked on the unit: a file loaded into the pad the screen shows** (review F3). The screen takes the length
  the engine measured at the pad's last recompute (`flen`) whenever it has one, and nothing sets the screen up again
  when that measure changes. Right after a load it can still be the old file's (static, inferred): the pad load
  `FUN_080A0AC8` drops the cell's key-map entry and only queues its slot's close (`FUN_0804C3A8` → `FUN_08070DB0`,
  the loader's ring), adds the new entry at the first free index, which can be the one just freed (`FUN_0804BA00`),
  and re-posts, so the engine's recompute can read the old file still open in that slot; the `0xE` handler later
  posts `0x90` to the engine and then refreshes the screen, which may run first. A screen set up in that moment
  (leaving the browser, which gives the pad its own file back, is the likely one) keeps the old length for TR, the
  bracket, the playhead's clamp and the overview until its next setup or zoom, where stock's own copy is right for a
  file only this pad names. Gate 3b, check 19. If it shows: measure at the setup instead of keeping the recompute's
  (`fw_src_len` of the pad's source then, which the loader has filled by the time it posts `0xE`).
- The dead travel at the top of a sample-position knob is stock's, kept: up to `step − 1` positions above the
  maximum all read the maximum. It has not been seen on hardware (question 16).
- After Clip, New Rec and New Multi keep these four rows bound, as stock keeps Sample's after Sample.
- The corner labels (37.3.1): a line drawn before the meter's first block (`b2_live()` says "not yet" then) is
  stock's grey until it is drawn again; the screen is opened long after boot, so this is not expected to show. A
  right-aligned line longer than its box (Sample mode's `LpEnd:` from 1 000 000 frames) starts left of its box on
  stock already; its edge goes one pixel further. A line costs nine of stock's draws in the GUI task (§5: ×9.0 the
  instructions), not in the audio's.

**Space**

- Bank 1 has 696 B free in the release build (`.cave` 57 040 of 57 736) and 8 in the dev build (57 728: its bench
  tools, the bounded peek and poke and the mailbox, took 568 B; §6) after 37.3.1's H5
  (+128 B), 704 after its corner labels (+288 B), 992 after Loop Fade (+144 B, §3.5), 1 136 after Fit (+128), 1 264
  after the Gate 3 fix batch;
  1 424 B after D-018
  moved the Clip Window's maths to bank 2 (−1 312 B;
  `clipwin.o` 3 561 → 2 243 B, `clipwin_b2.o` 644 → 2 516 B). Before it: 112 B, after the "bank 1 room" commit took
  216 B back (Loop Len's window to bank 2, −116 B; a stale bank cleared with a word loop, −64 B; `pad_store()` one
  multiply, −24 B; `clipwin_defaults()` a loop, −8 B). The size of the id check in `b2_ok` / `header_ok` moves by a
  few bytes when the bank-2 id changes, and the linker refuses an overflow.
- What is left of the Clip Window in bank 1 is the hooks and their stock calls, `clipwin_register` and the Waveform's
  binding: what remains to move is a few bytes of glue each (the slot decode in `clipwin_read`, its count and seam
  test). More than that means JOEBOX's own code (Munchi's engine split out of `munchi.cpp`), which is not ours to move.

## 5. How each piece was tested

**What the suite runs.** `test_clipwin.py` runs the real patched firmware under Unicorn on `emu.Emu(IMAGE,
"out/cave.elf")`:

- The whole class-B block method, block after block, with the real clock advance.
- The cell's class-H object, the real param-set for every setting, and `clipwin_tick` reading the app's stores.
- The stock registrar and store builder, `master_alloc`, the stock knob paths, the Waveform screen's setup, handlers
  and `SetCellParam`, and bank 2's `cw_looplen` and `cw_window`.

**What it compares against.** Every scenario also runs with the clipwin hooks taken out at run time, and the Slip-0
ones on the stock 3.1.9 image. **Attack:** the rig's pad had `pad + 0xBA1` = 0 (stock fades every step 0 in) until 37.3.3; §12d
runs Attack 0 through stock's param-set (`0xBA1` = 1, the unit's presets) and measures F-a's step 0 against the same
runs with bank 2's marks cleared (37.3.2) and with `0xBA1` = 0: Fit Auto and Off, Slip −645 and +60, Sync 1/16 and
1/4, a Region from 6 072, the launch, Fit at Slip 0, an Attack, a pad left alone, no bank 2. Region scenarios run against the stock image playing a file as long as the region.
The research model's numbers (a2/r2) are asserted.

**The sample source** is stubbed with a ramp (frame q holds `(q + 1)·2⁻²⁰`), so every output sample decodes to the
frame it plays and the gain it plays at.

| § | what | how it is proven |
|---|---|---|
| 1 image | every site, the thunks' registers, both Pos pages, no other stock byte changed, `master_alloc` | each site decodes to the intended `bl`; the stock facts the two newer thunks rely on (r9 at `0x08064C5A`, `[sp+0x58]` at the wrap) re-read in the image |
| 2 registration | the four rows (Fit's list and names), labels ≤ 9 characters, unique xml names, defaults | the stock registrar `FUN_0808C158` and store builder `FUN_08093F20` run whole; 86 of 96 entries |
| poll | `clipwin_tick` unit: one pad a call, the clamp, the guarded drop, a stale cached pointer, no SDRAM, a stale bank (another magic, every byte 0xa5) | fake stores, fake pads; the stale bank is zeroed whole by the first poll and nothing past its `0x724` bytes is touched |
| 3 off = stock | Slip 0 on the matched file, an 88 615-frame file, a late launch, Sync None | every read, fetch, prefetch, output sample and message identical to the hooks out **and** to stock 3.1.9 |
| 4 Slip | Slip 0, 960, −30, 7, 3839 on 96 000 / 88 615 frames; a late launch; Quant 1 beat < Sync 1 bar; Sync 1/16; a retrigger; a live Sync change; a tempo change; `clip = tps × n` | every sounding sample plays `(stock frame + slip_f) mod len` (max error 0.0106 frame) at stock's summed gain; every write lands in `cw_bank`; the seam hint fires from exactly the crossing segments |
| 5 live change | 0 → 480 and 0 → −7 in a step; the sign; Sync None; a pending launch; armed while stopped | stock-identical up to the step boundary, slipped after, no added silence; the launch keeps its bar (`+0x140` 11 520, msg `0x1D`) and plays slipped from its first read |
| 5b new file | the load chain (the slot closes, a recompute while closed, the new file opens, the 0xE handler's `0x90`) under a playing pad, with a shorter, a longer and a same-length file; the browser's round trip (finding 9: a 168 000-frame file played into its last step, then the pad's own 96 000 back: stuck on stock 3.1.9 and without `cw_retire`, in time again with it, Slip 0 and 960; the block's cost in both states); Slip 0, 960, −480; a latch made for another length in the reader unit | stock as measured (no restart, the pending step on the old grid); Slip 0 bit for bit stock; the segments latched before the change read exactly as stock's, no added silence, no read past the new end stock does not make; the next segment latches the new file and plays stock + slip_f; the same length keeps the latch |
| 6 gating | Slicer with and without markers, Sync Slice + markers, cell `0x401`, `fw_src_len` 0 / sentinel, no SDRAM | plays exactly as with the hooks out, no latch |
| 7 reader | seam reads mono and stereo, rate 1 / 0.7 / 2.3 / 8, a 40-frame file; every machine mode at, before and after the seam; the filter object's rate | bit for bit what the stock reader (or `filter.c`'s `clip_read`) makes of the file turned circular |
| 8 rate, stereo | a 44.1 kHz file, stereo 48 and 44.1 kHz, Pitch +7 | every sample stock + slip_f, the same gain |
| 9 knob | texts (`+1.280`, `-0.030`, `+4.000`, a stale or frozen knob); on the pad page and the Waveform turn path (v3): the knob log's median counts at each speed 1..6 (the stepper fed counts × gain, the top speed onto the 1/64 grid; ticks an event 0.5, 1.6, 3.8, 9.7, 22.5, 60, ×2.3 to ×3.2 a speed), the snap at the top speed only, the clamps, the detent (a fast arrival held `ZERO_DETENT_MS`, slow ones at speeds 1 and 2 held `ZERO_DETENT_SLOW_MS`, speed 3 not; a steady 20 ms stream passing 160 ms after it, a new turn inside the pause and one after it, a reversal, a turn from 0 at rest), the bench fields; six other knobs | the stock binder, turn paths and stepper; the numbers read from `src/clipwin_b2.c`'s `#define`s; other knobs post exactly as on stock. Against v2 (37.2.1d) the curve's and the slow detent's checks fail (×5.7 and ×1 steps; 150 ms after a slow arrival) |
| 10 Region | the rule over 20 cases (Loop Mode not asked: finding 7); each H3 site; adoption only at the wrap; the wrap-grid hold, and only for a wrap that can come (a 0-tick clip, passes that never meet the new grid: finding 5; a region grown from 3/8 beat to 2 beats while it plays); the fallback source; whole-process runs; a new file under a playing region (50 000 frames: the region no longer fits; 192 000: it does) | against stock playing the region as a file: every sample at `rs + (frame + slip_f) mod vlen`, every recompute field equal, no zero-gain sample; seamless wraps (stock: 8 006 zero-gain samples on a short region, peak 2.0 on a long one; ours 0, 1.0); one-step clips (32 000: peak 2.0 → 1.0; 20 000: 16 012 zero-gain → 0); the 9 000-frame region; live changes (heard at the wrap, a pass later from the last step, held to the bar where stock doubles, region → File); Sync None; 44.1 kHz stereo; gating; writes; the new file: the old segments read at their own positions in it (no mapping, nothing past its end, no silence), the next latch `(0, 50 000, 25 000)` or `(24 000, 48 000, 24 000)` made for the new length, Slip 960 = the Slip 0 run + slip_f |
| 11 Loop Len | the settle (finding 8, F-g: Off → 1/16 → 1/8 → 1/4 at speed 3 takes only 1/4, on the beat then playing, Sync not forced, and so does a value every 149, 171, 216 or 299 ms, speed 3's slow end, speed 2's fast half, Gate 3b's rest on 1/8 and one poll short of the settle, at four poll phases; a slow step-through, a second on each value, takes each value; Off at once; the 37.2.x runs written a settle earlier, so they take where they took); `k_looplen` L1–L4: origin 7 680, 1 200, 1 920, the launch held; live 1/4 → 1/8 → 1/2; 88 615 frames; over a region with Slip; the five do-nothing cases; Sync re-sent by the app; a stopped pad; a 44.1 kHz file; off/on in one step; stop and relaunch; a 5-beat clip; no bank 2 (its header wiped before the first poll): Loop Len set and Off, all three set with a live Slip change, Slip 0 / File / Off over a loop; a new file under a playing window (50 000 and 192 000 frames) | each segment starts on `(int)((float)w × fps)`; the forced Sync times every segment and gain exactly as stock sent that Sync itself; Off in phase; without bank 2 bit for bit as never set, as every clipwin hook taken out, and as the stock image, no `cw_*` entered; after the new file, the old segments read as stock, the next ones are made for its length and replay its frame 0 |
| 11b Fit | site 3's fields for Auto (Beats) over eight lengths (14.015, 3.74, 15.6, a 14.5 tie up, 0.3, a bar, 44.1 kHz, 2 000 beats) and Auto (Bars) over eleven (the 1.5 and 3-beat ties up, 5.9 → 1 bar, 6 → 2 bars, 14.015 → 4 bars, 2 000 beats → 1 024), the other Auto counting again, the list's eight lengths, the polymetric grid and steps (Quant 1 bar / 4 bars / 1/4 / 1/16 / None, Sync 1/16 … 1 bar, Slice, None), counted once per length and forgotten at a closed file (0 frames, the provider's 0), the do-nothing cases; the whole process on a 3.74-beat region and file, Beat Count 8 on a bar, a tempo change, Slip 480, Loop Len 1/4, 44.1 kHz stereo, Pitch +12, a one-shot; 34 polymetric cases (a file and a region of 3, 5, 6, 7, 14 beats at Quant 1 bar and Sync 1/16, 1/4, 1 bar; Quant None; 5 beats at Sync 1/2; `CW_FULL=1`: 60, Quant None at every Sync) against stock playing the same files at their Beat Count; launches 1/16 after the bar, off the Sync grid (a bar, 14 beats, the 3.74-beat region at Quant 1/16 under Sync 1/4; 2 bars at Quant 1/4 under Sync 1 bar), against Fit Off and the stock image; live changes (Off → Auto; 1 bar → 2 bars at Quant 4 bars and 1 bar); a fitted 14-beat region made 16 and 13 beats; the hold's Fit; Fit Off against no row; the writes | the rule's own numbers at site 3, in the M7's single precision; a fitted clip: every pass one clip after the one before (off the Sync grid: the one jump onto the beat at the first step, then passes on the grid, as Fit Off and stock), the audio carrying on at every joint (under half a frame; under a frame where stock starts a step on a whole frame), no zero-gain sample, no gain over 1, where stock passes off the clip, doubles a step or leaves silence; Slip's shift exact (0.004 frame); Fit Off bit for bit as no row; without bank 2 with Fit set, every hook stock's (§11's check) |
| 11c Loop Fade | 5 % on the 3.74-beat region at rate 1, with Fit Auto, 44.1 kHz stereo and Slip 480; a region from 1 000 (F clamped to Loop Start); a mismatched 441 Hz sine at 0, 1 and 5 %, with Fit; a one-shot, Loop Off, a 2 000-frame region, Pitch +24, Fidelity SP1200; Loop Fade 0 against no row; Loop Len 1/4 taken in the region's last beat; 25 % with Slip 480 (the seam hint); the store and the registration (stock's row) | every sample of the faded run against stock's formula applied to the Loop Fade 0 run's frames (max error 0.005 frame at rate 1, 0.08 through the kernel); the hints where the copy starts and at rs; the sine's splice gone; the do-nothing cases, Loop Len's window among them, bit for bit Loop Fade 0 (prefetches included); a prefetch covering rs before the slipped crossing, as at 0 %; without bank 2 with Loop Fade set, every hook stock's (§11's check) |
| 11d playhead | H5's site and thunk; a region from 6 072 of a 192 000-frame file, with Slip +0.060 and −0.120; a whole file with Slip +0.480; Loop Len 1/4; Fit Auto on 3.74 beats (rate 0.935); the region with H5 alone taken out; no bank 2 | in every block one segment plays throughout, the position posted is the frame after the block's last sample heard (to the frame at rate 1; at 0.935 the posted whole frame 1 to 2.1 behind the decoded one plus the rate, the kernel's offset and the cut fraction), its per mille `(float)pos × 1000 / file`; stock's line on the region 6 072 behind the same audio; without bank 2 every message the stock image's, bit for bit |
| 12b corner labels | the four sites; `label_vt` against stock's vtable; `clipwin_label` on the four knobs as the constructor leaves them (the knob's real layout, which makes the line its child); 24 lines (four corners, Clip's and Sample's names, 8 to 12 characters, on the background and on the cyan) through the knob's real draw into an 8-bit layer; the clipped draw (the box as the dirty rectangle, and a rectangle that cuts it); a value that changes (the box repainted between); no bank 2; every pad mode's setup and refresh on the screen; the cost; a preview (`out/halo-preview.png`) | white exactly where stock draws the glyphs in the box inset by a pixel, black exactly on the pixels around them, nothing else changed, all inside the box; the clipped draw the whole draw's pixels inside its rectangle; after a change, a fresh draw's frame; without bank 2 the stock image's frame bit for bit, grey; the vtable and the grey kept through Clip, Sample, Granular, Slicer and New Rec |
| 12 Waveform | the length (a view holding another pad's 192 000 for a 336 359-frame pad: TR's range, the bracket, the waveform's clamp, the overview; the waveform's real tick following the playhead past 192 000), the bind order, the four rows, names and texts, the lines' width (the real redraw, the knob's set-rect on the constructor's rects, the text draw's measure: each line in its box, clear of its neighbour), the bracket, TL/TR turns, the forward, `SetCellParam`, zoom, other modes | the same six turns give the same posts, steps, ranges and pending positions as stock's Sample-mode Loop Start/End knobs; Sample, Granular, Slicer, Sample after Clip are the screen with the hooks out; without bank 2 the Slip knob's text and turns are the knob hooks' taken out, and no bracket |

**Elsewhere.** `test_bank2.py` (44 checks) holds bank 2 to the leaf rule. Its scan now tells the second half of
an instruction from a planted `bl`, using the linker's mapping symbols, and plants one in each of the nineteen `cw_*`
functions (`cw_fit`, `cw_hint` and `cw_fade` among them), at its first instruction and at its first division where it
has one.
`test_insert.py` and `test_lfo.py` hold the pre-listen cell `0x401` off pad 2. `./check.sh` runs all 31 suites.

**On the unit.** Gate 2 ran on 37.1.0d, with Slip v1 under D-014's sign and no bank 2:

- `+0.060` moved Out 1 by +1 500 samples, exactly, and `−0.120` by −3 000.
- A live change was smooth.
- Save, power-cycle and reload kept `+0.120`.
- There was no fault.

Gate 3 part 1 ran on 37.2.0d and 37.2.1d, with bank 2 (`notes/bench/2026-10-16-gate3-part1.md`):

- the first bank-2 install: written at the first boot, one restart by itself, no `!`, unchanged over two
  power-cycles;
- a region set by the Waveform knobs: shift −Loop Start exactly (−6 144); Slip on it under the D-016 sign: `+0.060`
  → −1 500, `−0.120` → +3 000;
- Loop Len 1/4 a one-beat stutter in time, Off back in phase (shift 0), 1/16 forcing Sync 1/16 and Off giving it back;
- a negative Slip (−120) and the region through save, power-cycle and reload (question 3 settled);
- the load: 24–25 % with pads playing, and the ten findings 37.3.0 answers.

**Not checked on the unit yet** (Gate 3b, §7): all of 37.3.0 (the bank-2 move of D-018, the fix batch, the knob's
v3, Fit, Loop Fade, its bank-2 install); Region live and Region Auto through Sample mode (the Pad Mode change feeding
the class-H object, posted in emulation as the app posts it); on/off/on within a beat; Loop Len over a region with
Slip; SD streaming at a seam; the Waveform knobs' steps and dead travel; the workflow on a real song; the pre-listen
cell fix; the knob's counts per revolution; the CPU cost of bank 2's calls on the chip.

## 6. How to bench it: the Gate 3 recipe

The full list of checks, numbered as the bench reports cite them. Gate 3 part 1 ran it on 37.2.0d / 37.2.1d; what is
left, and what 37.3.0 changed, is §7 (Gate 3b), which points back at these rows.

**Unit and tools.** Use the dev build of the release under test (USB peek in: 37.2.0d at Gate 3 part 1, 37.3.0d at
Gate 3b), with **`BLACKBOX.bin` and `BBEXTRA.BIN` from the same build**. Cable the power jack to mgr-ran's USB.
Measurements come from `bench/bbusb.py` over the USB audio (Outs 1–3, 24-bit / 48 kHz) and the peek.

**Setup.**

- Internal clock 120 BPM, metronome **Metro Out = Out 2**: it reaches the capture only there. Pads on Out 1.
- Numbers at 120 BPM: 1 tick = 25 samples, 1/64 = 1 500, 1/16 = 6 000, beat = 24 000, bar = 96 000.

**Recording and reading takes.**

- `bbusb.py record 12 NAME.wav` records a take. Start it only after the pad has played one whole pass in the state
  being measured.
- `bbusb.py shift BASE.wav NEW.wav` prints how far Out 1 moved between two takes, each aligned on its own first whole
  click. **`+` = later**, folded into ± half a beat (±12 000).
- Under D-016, a Slip of `+` is *ahead* and reads **negative**.

**The bank.**

- `bbusb.py slip` prints the bank address, the polled Slip per pad and the latched slots.
- `bbusb.py knob [SECONDS]` prints the Slip knob's last turn event (counts, the accelerator's speed 1..6) and the
  detent's last arrival on 0, slow or fast; with SECONDS it samples while you turn and ends with how often each speed
  was seen. Read only.
- `bbusb.py fit` prints, per pad with Fit or Loop Fade set, Fit as taken, the tempo it was fitted at, Auto's beats
  and the length it counted, Loop Fade, and the pad's step fields (`+0x1f0` rate, `+0x204`, `+0x208`, `+0x210`,
  `+0x230`). Read only.
- All three refuse a bank whose magic is not `CWNA` (37.3.0's layout): 0 means the bank was not set up this boot (no
  matching bank 2, TOOLS shows `!`), and whatever else is in it is a previous boot's.
- For pad q = 4 × row + col (rows counted from the bottom: B at row 3 col 1 is q = 13), with `B` the bank address
  `slip` prints:

| what | address | B's (q = 13) |
|---|---|---|
| region | `B + 0x4C0 + 8q` (rs, vlen) | `B + 0x528` |
| origin | `B + 0x5C0 + 4q` | `B + 0x5F4` |
| `ll` | `B + 0x600 + q` (a byte) | `B + 0x60D` |
| `forced` | `B + 0x610 + q` (a byte) | `B + 0x61D` |
| latch, slot k | `B + 0x98 + 64q + 16k` (rs, vlen, delta, len) | `B + 0x3D8` |
| `llv`, `llc` (Loop Len's settle) | `B + 0x723 + q`, `B + 0x733 + q` (bytes) | `B + 0x730`, `B + 0x740` |
| `flen` (the Waveform's file length) | `B + 0x744 + 4q` | `B + 0x778` |

- `peek` prints little-endian words, so byte q is byte `q % 4` (lowest first) of word `q / 4`; `peek ADDR N` reads N
  bytes from ADDR (any address, any length up to what you ask).
- The pad object is the `pad object` printed by `slip`. Its `+0x220` is the Sync step in ticks (960 = 1/4, 240 =
  1/16). Its four segment slots are at `+0x30 + 0x70 k`: `+0` active, `+1` done, `+0x08` the position (i64),
  `+0x20` the start delay, `+0x34` the step j (`peek PAD+30 448` reads all four; notes/re/a1).
- **The load, without TOOLS**: `cpu.c`'s meter is at `0x2405FFD0`. `peek 2405FFE4` gives the blocks measured (low
  half) and the **peak** in per mille (high half) since TOOLS last drew its bar; `peek 2405FFF0`'s byte 2 is the late
  blocks since then. TOOLS' own figure is the same peak, rounded to a percent (and its draw clears both).

**The dev build's bench tools** (37.3.1d; `src/usbdev.c`, `#ifndef PUBLIC_BUILD`, fork-only: D-019; a release build
has none of it and is byte for byte the image without it):

- **The peek and poke are bounded** (F-j: a 64-byte peek at `0x38800FD8` read `0x38801000`, past backup SRAM, and the
  bus fault restarted the unit). A peek reads aligned words inside one of: the LTDC's registers `0x50001000 ..
  0x50001147` (a read changes none of them), `RCC_RSR` `0x580244D0`, flash `0x08000000 .. 0x081FFFFF`, DTCM, AXI SRAM
  `0x24000000 .. 0x2407FFFF`, SRAM1–3 `0x30000000 .. 0x30047FFF`, SRAM4 `0x38000000 .. 0x3800FFFF`, backup SRAM
  `0x38800000 .. 0x38800FFF`, SDRAM `0xC0000000 .. 0xC3FFFFFF`, and stops at its end (a short reply); a request that
  starts outside them, or unaligned, is stalled. A poke writes an aligned word in the RAMs and SDRAM only (never flash,
  never a peripheral); anything else is stalled and writes nothing. `bbusb.py peek` aligns its requests.
- **A new setup drops a stale reply** (F-i: after a host-side timeout each reply was the previous request's). Every
  setup disables endpoint 0 IN if it is still armed and flushes TX FIFO 0 before it answers.
- **The parameter mailbox**: the host does what a hand does on the Pos and Waveform rows. A request at **cw_bank +
  0xF00** (master.c's SDRAM block + `0x84800`; `bbusb.py set` / `get`):

  | offset | field | who |
  |---|---|---|
  | `+0x00` | magic `0x3158424D` ("MBX1") | host |
  | `+0x04` | seq: written last, one more than the last `done` | host |
  | `+0x08` | op (1 SET, 2 GET), row, col (rows from the bottom), 0 | host |
  | `+0x0C` | id (u16), 0 | host |
  | `+0x10` | value (i32) | host |
  | `+0x14` | done: the seq served, written last | unit |
  | `+0x18` | result: 0 done, −1 unknown op, −2 not a pad, −3 not a row it sets, −4 out of range | unit |
  | `+0x1C` | the store's value of the id after it | unit |

  The GUI task serves it right after its knob scan (the app pass's `bl FUN_08040724` at `0x080A2CD6`, patched in dev
  builds only), as the `0x6E` message a knob's view sends the app (`FUN_080A1718` → `SetCellParam`): the pad's store,
  the engine's `0x39`, the screens' `0x66`, so a preset save and every Clip Window hook (Region, Slip, Loop Len's
  settle, Fit, Loop Fade) see it as a turn. Rows: Pad Mode `0x8B` (Sample .. Granular only: never New Rec / New Multi),
  Loop Mode `0x8D`, Quant Size `0x47`, Loop Start `0x91`, Loop End `0x92` (any frame count: the table holds 0 .. 1000
  there), Launch Mode `0x93`, Sync `0x94`, Beat Count `0xD2`, Loop Fade `0xFA`, Region `0x1C8`, Slip `0x1C9`, Loop Len
  `0x1CA`, Fit `0x1CB`; a value is checked against the stock table's min and max (`FUN_0808E2D0`, `FUN_0808E304`).
  One request at a time, each seq served once, nothing while the magic is absent; no tempo, play / stop, recording,
  presets or browser. `bbusb.py set 1,2 slip -0.645`, `set q13 looplen 1/4`, `get 1,2 fit`: list values by the
  unit's own names (read from its table), Slip as beats.ticks.

**The test take.**

1. Pad A: the 1-bar factory drum loop as at Gate 2 (Clip, Loop On, Quant 1 bar, Sync 1/4, Launch Toggle).
2. Resam two bars of A into an empty pad B (Rec Input Resam, Length 2 bars, Rec Quant 1 bar). B is a clip of two
   identical bars, 192 000 frames, Beat Count 8.
3. On B, set Beat Count **Auto**, Quant 1 bar, Sync 1/4, Toggle, and Region **Auto** (its loop is the whole file).
4. Play only B.

Because B is two copies of one bar, a one-bar region inside it is continuous audio at its seam. Anything heard at the
loop point is the mod's.

| # | check | how | expect |
|---|---|---|---|
| 0 | install | both files on the card, BACK + INFO at power-on; let the first boot restart itself once (bank 2 written) | TOOLS shows the build's name (`37.2.0d` at part 1) with **no `!`** before the load figures; `bbusb.py crash`: no fault or watchdog record |
| 1 | reference | A alone → `a.wav`; then B alone on Region Auto (= File), Slip 0, Loop Len Off → `b_file.wav` | sounds as stock; `shift a.wav b_file.wav` gives the Resam's own offset (note it; every check below is against `b_file.wav`) |
| 2 | Region by the knobs | Region **Loop**; Waveform TL Loop Start to L ≈ 6 000, then TR Loop End to L + 96 000 (one bar; the knob shows frames and moves in whole steps from its range's start, so zoom in until it lands; note L) → `region.wav` | the bracket shows at once and is heard from the next wrap; `shift b_file.wav region.wav` **−L** (−6 000 = −240.0 ticks for L = 6 000); peek region[q] = (L, 96 000); no click, flam or gap at the loop point |
| 3 | Slip on the region | Slip `+0.060` → `rslip1.wav`; `−0.120` → `rslip2.wav` | **−L − 1 500** and **−L + 3 000** (−7 500 and −3 000 for L = 6 000; the D-016 sign: `+` comes earlier); the seam now falls mid-step (Sync 1/4): still no click |
| 4 | Slip knob feel (v3, 37.3.0; Gate 3b) | turn BL slowly, a bit faster, then fast, then through 0 without stopping, slowly and fast; the same on the Pos tab; `bbusb.py knob 20` while turning | slow = single ticks, and the speed grows with the turn with no step you can feel; full speed = 1/64 steps (`0.060`); a slow turn into 0 stops on `+0.000` about 0.4 s (`knob` says "slow"), a fast one about 0.15 s, then goes on; the speeds `knob` reports (to tune `KNOB_GAIN`, `KNOB_GAIN_STEP`, `KNOB_TOP`, the two holds) |
| 5 | Region live | Slip 0; while B plays: Region Loop → File, then File → Loop; record after each | heard at a wrap, never doubled; File: `shift` **0**; Loop again: **−L** |
| 6 | Auto via Sample mode | B to Sample (stock clears its loop), Loop Mode Forward, BL/BR Loop Start L′ ≈ 6 000 / Loop End L′ + 96 000, back to Clip (Region **Auto**; check Beat Count Auto, Quant, Sync, Toggle again) → `auto.wav` | the bracket is there; `shift` **−L′**. This is the unit's Pad Mode path into the class-H object, which emulation did not run |
| 7 | Loop Len 1/4 | Region File, Slip 0; engage 1/4 while beat 3 plays (count with the metronome) → `ll4.wav` | beat 3 on every beat, in time; peek ll[q] = 3, origin[q] = 1 920 or 5 760 (bar 1 or 2 of the clip); `forced` 0, pad `+0x220` = 960; `shift b_file.wav ll4.wav` **0** (the window is on the grid; this reading holds for a loop whose beats share a grid, as a drum loop's do) |
| 8 | Off, in phase | Off; record after it → `ll_off.wav` | `shift b_file.wav ll_off.wav` **0**: the whole loop resumes as if it had played on |
| 9 | Loop Len 1/16, forced Sync | 1/16 → stutter; then Off | while on: `forced[q]` = 1, pad `+0x220` = 240, the Sync row still reads 1/4; after Off: `forced` 0, `+0x220` 960 |
| 10 | on/off/on in one beat | 1/4 on, Off, on again within the same beat | the same beat comes back (origin unchanged) |
| 11 | Loop Len over Region + Slip | the region of 6 (Region Auto), Slip `+0.060`, Loop Len 1/4 → `llr.wav` | `shift` **−L′ − 1 500**, as without Loop Len: the window keeps the region's beat grid and Slip's shift; by ear, the beat repeated is the one that was playing |
| 12 | Waveform knobs | TL/TR at several zooms, slow and fast; Loop Start up into Loop End; Loop End past the file's end and back (question 16) | one step = one pixel (1 frame zoomed all the way in); the bracket follows each turn and the pad takes it at the next wrap; no loop → the whole file plays; count the steps back from the top before Loop End moves (stock's dead travel) |
| 13 | save, power-cycle, reload | the region of 6, Slip **−0.120** (a negative value: question 3), Loop Len Off → `presave.wav`, PSET Save, power-cycle, reload → `reload.wav`; then Loop Len 1/4 saved the same way | `bbusb.py slip` shows Slip −120 on B; `shift presave.wav reload.wav` **0**; Loop Len 1/4 comes back and, the pad not played since power-on, loops the clip's first beat at the first launch (origin 0) |
| 14 | SD at the seam (question 9) | `bbusb.py peek 24013930` before and after 30 s of each: B on File; B Region Loop with Slip `+0.060`; a 4-bar clip with Loop Len 1/16, then Off, then on | no more misses than on File; no dropout on the step after Off. Misses → add one prefetch of the in-phase position at Off |
| 15 | load, faults | TOOLS load figure against 37.1.1 with the same preset; `bbusb.py crash` at the end | no change worth noting; no fault or watchdog record |
| 16 | the workflow, for real | §2 on a phone recording of a real song, no Trim | sits in the groove; report by ear |
| 17 | pre-listen under a slipped pad (the stale-latch fix) | B on Region File, Slip `+0.060`, playing; open the browser from B and scroll through a few files, then leave it → `prelisten.wav` after leaving | while browsing, each file plays from its own position, unslipped, for at most two Sync steps, then slipped, with no silence a stock pad would not have; after leaving (B's own file back) `shift b_file.wav prelisten.wav` **−1 500** |
| 18 | the pre-listen voice is no pad (the pre-listen cell fix) | pad 2 (row 0, col 1) with Input In 1+2, an Insert on and LFO 2 on Retrig; pre-listen files from another pad's browser | the pre-listen carries no live input and no insert; pad 2's LFO does not restart on each file; pad 2 itself unchanged |
| 20 | Fit Auto on a 3.74-beat region (Gate 3b, #t-022) | B, Region Loop [L, L + 89 760), Beat Count Auto, Sync 1/4; Fit Off → `fit0.wav`, then Fit Auto (Bars) → `fit1.wav`; `bbusb.py fit` | Off stutters at every beat (findings 3, 4); Auto is clean (either Auto counts 4 beats here); `fit`: Fit Auto (Bars), fitted at 120.00 BPM, Auto 4 beats for 89 760 frames, `+0x1f0` 0.935000, `+0x204` 24000.0, `+0x208` 960, `+0x210` 4, `+0x230` 3840 |
| 21 | polymetric, stock and Fit | pad 1's 14.015-beat take, File, Quant 1 bar, Sync 1/16: Beat Count 14, Fit Off → `poly_off.wav` (30 s, pad 1 alone); then Beat Count Auto, Fit Auto (Beats) → `poly_fit.wav`; `bbusb.py fit` (Fit Auto (Bars) on it: 16 beats, a pass every 4 bars) | Off: under emulation stock starts every other pass a 1/16 early over the last step and leaves a 1/16 of silence before the next (passes 330 264 / 341 736 samples apart); the Gate 3 report heard it clean. Measure which (pass starts against the metronome, silent runs). Fit: a pass every 336 000 samples, no doubled or silent 1/16; `fit`: Auto 14 beats, `+0x230` 1920, `+0x210` 56. Then save it as a preset; load one at 90 BPM whose pad plays the same file at Fit Auto (`fit`: Auto 11), then this one again: `fit` should show Auto 14, as after a boot. 11 = the count outlived the load (the file stayed open through it): Auto's count then wants resetting at a stopped pad's recompute (the review's F3, option b; Thomas's call, since "once per length" is his rule) |
| 22 | a WAV's Beat Count | B's 1-bar region at Beat Count 8 (the Resam's own): Fit Off, then Auto (Bars) | Off chops it (8 steps of a half beat, each played a beat); Auto: `+0x210` 4, clean |
| 23 | tempo | Fit 1 bar on the region of 20, then the tempo 120 → 126; then the tempo from an external MIDI clock at 120, 30 s, `bbusb.py fit` every few seconds | within 43 ms `fit` shows the new tempo and `+0x1f0` 0.9817; from the next pass on, clean and in time. Under the external clock: whether the "fitted at" BPM moves while the clock stands still (the poll then recomputes the pad up to every 16 blocks, each a tiny rate change at the next step; the review's F5) - clean by ear either way |
| 24 | Fit live | Quant 4 bars, Fit 1 bar → 2 bars while it plays | the bar plays on until the next 2-bar point, then 2 bars; never doubled |
| 25 | Loop Fade on a region (finding 6) | B, Region Loop over a region whose ends do not match (L ≈ 6 000 to L + 89 760, say); Loop Fade 0 → `fade0.wav`, then 5 % → `fade5.wav`; `/srv/dev/firmware/re-scratch/fit/probes/wrapstep.py TAKE.wav 96000` on each | at 0 % the largest steps all fall at one phase of the pass (the splice); at 5 % they spread over the audio's own transients; `bbusb.py fit`: Loop Fade 5 % |
| 26 | Loop Fade, SD | `bbusb.py peek 24013930` before and after 30 s at Loop Fade 5 % and 25 % on that region, at Slip 0 and at Slip `+0.060` (the seam inside a step: nothing but the seam hint reaches the region's start) | no more misses than at 0 %; misses at 25 % only → the copy's frames past the hint's reach want hinting as the copy goes (a hint per 16 384 frames of it) |
| 19 | the Waveform's length after a load (Gate 3b, review F3) | pad 1 in the Clip Waveform, Region Loop over part of its file; open the browser from it, pre-listen a file of another length, leave the browser (pad 1's own file back); then without touching anything `bbusb.py peek` the view's TR range and the waveform's `+0x254`; then load a file of another length into pad 1 for good and read them again | both read pad 1's file's length (336 359 for the Gate 3 file), the bracket where Loop Start / Loop End are, and the overview follows the playhead to the end of the loop; a stale value is the previous file's length (see §4) |

Report in the form of `notes/bench/2026-10-15-gate2-slip.md`: one row per check, the measured value, and pass or
not. Three things to answer along the way:

- whether a preset load stops a playing pad (Loop Len's F4 rule);
- whether the bracket's lead over what you hear is acceptable;
- whether Loop Len (and now Slip and Region) without bank 2 should read `---` (question 30).

## 7. Gate 3b: the run on 37.3.0d

What Gate 3 part 1 left (§6 checks 5, 6, 10, 12, 16, 18; 11 and 14 are not in its report either), what 37.3.0
changed (the knob's v3, findings 1, 2, 5, 7, 8, 9, 10 and 12, D-018's move to bank 2), and Fit and Loop Fade (§6
checks 19–26). Same unit, cabling, setup, pads and takes as §6: 120 BPM, Metro Out = Out 2, pads on Out 1, pad A the
1-bar drum loop, pad B the 2-bar Resam take of A (192 000 frames, row 3 col 1, q = 13), pad 1 the 14.015-beat take
(336 359 frames, row 0 col 0, q = 0). L is Loop Start, in frames; `shift` is `bbusb.py shift` (+ = later), `peek` is
`bbusb.py peek`, and the bank addresses are §6's table (B's column). Takes and readings go to
`/data/dev/gate3b/` on mgr-ran.

**The pair.** `/data/dev/release/37.3.0d/`: `BLACKBOX.bin` and `BBEXTRA.BIN` from one build (sha256 in its
`SHA256SUMS` and in `notes/releases/37.3.0.md`), payload id `0x2a0e4094`, len `0x4120`, sum `0x2cbfbf38`.

| # | check | how | expect |
|---|---|---|---|
| 3b-0 | install (D-018) | before: `peek 08100000 16` (37.2.x's header: `21324242 2c4676ca 00003500 73f8a581`); both files on the card, BACK + INFO at power-on; then two power-cycles | the first boot rewrites bank 2 and restarts itself once; `peek 08100000 16` → `21324242 2a0e4094 00004120 2cbfbf38`; TOOLS `37.3.0d` with no `!`; `bbusb.py slip` prints magic `0x43574e41` (`CWNA`); `bbusb.py sdram` about 1 491 200 B free (Gate 3: 1 493 248; the bank is 0x1000 now, −2 048); `bbusb.py crash`: no fault, no watchdog record; the power-cycles: the header unchanged, no rewrite |
| 3b-1 | references (§6 check 1) | A alone → `a.wav`; B alone on Region File, Slip 0, Loop Len Off, Fit Off, Loop Fade 0 → `b_file.wav` | `shift a.wav b_file.wav` +192, as at Gate 3 (the Resam's latency): with all five at their defaults B is stock. Every shift below is against this `b_file.wav` |
| 3b-2 | the Waveform's names (finding 2) | B on the Clip Waveform with Region Loop over [6 000, 102 000); then pad 1 with Loop End at its end; photo | `LpS 6000`, `LpE 102000`, `Slip +0.000`, `LpLen Off`, every value whole and clear of the other knob's name; on pad 1 `LpE 336359` |
| 3b-3 | the knob's v3 (finding 1; §6 check 4) | Waveform BL and Pos Slip: slowly, a bit faster, fast, then into and through 0, slowly and fast; `bbusb.py knob 60` while turning → `knob-log-3b.txt` | no step you can feel between speeds; at the knob log's median counts an event moves 0.5, 1.6, 3.8, 9.7, 22.5 and 60 ticks at speeds 1..6, only speed 6 on the 1/64 grid (`+0.025` → `+0.060`); a slow arrival on 0 prints `arrived on 0 (slow)` and holds about 0.4 s, a fast one about 0.15 s, then the same turn goes on. Thomas's feel decides; the speeds seen are what `KNOB_GAIN`, `KNOB_GAIN_STEP`, `KNOB_TOP` and the holds are retuned on (a new `BBEXTRA.BIN`, D-018 (5)) |
| 3b-4 | Region live (§6 check 5) | Slip 0; B playing Region Loop [L, L + 96 000) (L ≈ 6 000), then File, then Loop again; record after each | each change heard at a wrap, never doubled; File `shift` **0**, Loop again **−L** |
| 3b-5 | Region Auto without Loop Mode (finding 7) | B on Region **Auto** (a Resam take: Sample mode's Loop Mode None); on the Clip Waveform TL to L ≈ 6 000, then TR to L + 96 000 → `auto_k.wav` | the bracket shows at once (37.2.x: none, the pad stayed on File); from the next wrap `shift` **−L**; `peek B+528 8` = (L, 96 000) |
| 3b-6 | Region Auto through Sample mode (§6 check 6) | as §6 row 6 | the bracket; `shift` **−L′**. The Pad Mode change feeding the class-H object, never run on the unit |
| 3b-7 | a region grown from under half a beat (finding 5) | B, Region Loop, Beat Count Auto, Quant 1 bar, Sync 1/16: TR to L + 9 000 (3/8 beat) and play; then TR to L + 48 000 (2 beats) without stopping → `grow.wav` (20 s from the change) | the 2-beat loop is heard from the next time round, no stop / play needed (37.2.x held the old one until a relaunch); one pass out of time, a short gap and one 1/16 doubled (emulated: 496 samples of gap, then 6 903 samples at gain 2), then in time: from the next pass `grow.wav` matches a take of the same region launched from stop (`shift` **0**); `peek B+528 8` = (L, 48 000) |
| 3b-8 | Loop Len taken when it settles (finding 8; §6 checks 7, 9) | Region File, Slip 0: from Off turn BR at an ordinary speed to 1/4 while beat 3 plays → `ll4b.wav`; then Off; then step Off → 1/16 → 1/8 → 1/4 slowly, resting about 1 s on each | 1/4 engages on the beat playing about 0.2 s after the knob rests: `peek B+600 32`: `ll` byte 13 = 3, `forced` byte 13 = 0; `peek B+5F4` origin a multiple of 960 (1 920 or 5 760 when taken in beat 3); `peek B+730` byte 0 (`llv`) 3, `peek B+740` byte 0 (`llc`) 4; pad `+0x220` 960 (Gate 3: in-point 2 160, Sync forced 1/16); `shift b_file.wav ll4b.wav` **0**. The slow step-through takes each value in turn (1/16: `forced` 1, `+0x220` 240); Off: `forced` 0, `+0x220` 960 |
| 3b-9 | on / off / on within a beat (§6 check 10) | 1/4 on and taken; Off, then 1/4 again within about 0.3 s | the same beat comes back (origin unchanged), since 1/4 is taken again 171..213 ms after the knob rests and a beat is 500 ms (37.3.1: 299..341 ms, still inside the beat) |
| 3b-10 | Loop Len over a region with Slip (§6 check 11, never run) | the region of 3b-5, Slip `+0.060`, Loop Len 1/4 → `llr.wav` | `shift` **−L − 1 500**; the beat repeated is the one that was playing |
| 3b-11 | the Waveform knobs and the pad's length (§6 checks 12, 19; finding 12) | pad 1, Region Loop over part of it: TR turned to its top, then back; TL / TR at several zooms; `peek B+744 4` (`flen[0]`); then §6 row 19's browser round trip and load | TR's top reads `LpE 336359` (37.2.x stopped at 192 000), `flen[0]` = 336 359 (`0x000521e7`); the view follows the playhead to the loop's end; one step = one pixel; the dead travel at the top counted (question 16); after the round trip and after a load, TR's top and `flen` are the file's length then (a stale one is review F3: §4) |
| 3b-12 | SD at a seam (§6 checks 14, 26; question 9) | `peek 24013930` before and after 30 s of each: B on File; Region Loop with Slip `+0.060`; a 4-bar clip with Loop Len 1/16, Off, on; the region of 3b-17 at Loop Fade 5 % and 25 %, Slip 0 and `+0.060` | no more misses than B on File (Gate 3: 0 in normal play); no dropout on the step after Loop Len Off |
| 3b-13 | the pad the browser left stuck (finding 9; §6 check 17 again) | visit TOOLS (it clears the meter); B on Region File, Slip `+0.060`, Sync 1/4, playing; open the browser from B, highlight pad 1's file and stay on it 9 s or more (its 16 beats: B plays into its last step), then leave → record 20 s → `prelisten3b.wav`; while it plays `peek PAD+30 448` twice, 1 s apart; `peek 24013930` before and after; `peek 2405FFE4` and `peek 2405FFF0` before going back to TOOLS; then the same at Slip 0 | B plays its own file again from its next pass, in time, with no stop / play: `shift b_file.wav prelisten3b.wav` **−1 500** (at Slip 0: **0**); no slot active and not done at a position past 192 000 (Gate 3: slot 0 at 315 848 for 1.4 s, step 0 restarting every 2 beats); the misses as Gate 3's browse (0 → 176: stock streaming) |
| 3b-14 | the load (finding 10; §6 check 15) | the peak of 3b-13 (`peek 2405FFE4`'s high half, per mille; the late count `2405FFF0` byte 2), then TOOLS; TOOLS at boot and with the Gate 3 preset playing; then four pads on Fit Auto over 3.74-beat regions (rate 0.935), and the same four at Loop Fade 5 %; `bbusb.py crash` at the end | the browse's peak near the clean browse's 24 %, no late block (Gate 3: 99 % peak during the stuck episode); 8/13 % at boot and 24–25 % playing as on 37.2.1d (bank 2's calls: about +110 instructions a block a playing Clip pad under emulation, far under 1 %); the four fitted pads a few % more than at Fit Off (emulated +4 352 instructions a block a pad through the interpolating reader; Loop Fade 5 % about +180 more); no fault or watchdog record |
| 3b-15 | the pre-listen voice is no pad (§6 check 18) | as §6 row 18 | as there |
| 3b-16 | Fit (§6 checks 20–24) | as §6 rows 20–24; and Fit 3 beats and 6 beats on B's 1-bar region [L, L + 96 000) at Quant 1 bar, Sync 1/4 → `fit3.wav`, `fit6.wav` | as there; 3 beats: `fit` `+0x1f0` 1.333333, `+0x210` 3, `+0x230` 960, a pass every 72 000 samples; 6 beats: 0.666667, 6, 1920, every 144 000; each in time against the metronome, no doubled or silent step. They stay in the list only if they behave (D-026) |
| 3b-17 | Loop Fade (§6 check 25; finding 6) | as §6 row 25: B, Region Loop [L, L + 89 760) with L ≥ 4 488, Fit Off; Loop Fade 0 → `fade0.wav`, 5 % → `fade5.wav` | as there; at 5 % F = 4 488 frames; `fit`: Loop Fade 5 % |
| 3b-18 | the workflow, for real (§6 check 16) | §2 on a phone recording of a real song, no Trim, with Fit Auto (Bars) and a few % of Loop Fade | sits in the groove; report by ear |

On 37.3.1d, when it is installed (both files: bank 2 changed, so the first boot rewrites it and restarts once; the
header then reads `21324242 ce1ead5b 00004180 c6b2bdbc`):

- 3b-2's photo again, in Clip mode and in Sample mode: each corner reads white with a black edge on the cyan and on
  the background.
- The playhead (F-e): B on Region Loop over [6 072, 102 072), Slip 0, then `+0.060` and `-0.120`: the line sits on
  the hits it plays, starts at the bracket's left edge and wraps at its right edge; on a whole file with Slip it
  leads or trails stock's by the Slip; Loop Len 1/4: it loops inside the beat; Fit Auto on pad 1's take: it covers
  the whole file once a pass.
- The settle (F-g): 3b-8's ordinary turn Off → 1/4 again (`bbusb.py peek B+600`/`B+723`/`B+733` sampled as in
  `ll4b-bank.txt`): only 1/4 taken, Sync not forced; the slow step-through still takes each value (about 0.3 s after
  each arrival); a flick that overshoots and comes straight back takes nothing.

Answer along the way, beside §6's three: whether the knob's v3 feels right; whether 3 and 6 beats stay in Fit's list;
whether stock wraps pad 1's 14-beat take cleanly at Quant 1 bar (check 21: the emulation says it does not); whether
Fit Auto's count outlives a preset load (check 21's second half: the review's F3). Report as
`notes/bench/2026-10-1x-gate3b.md`, in the form of the Gate 3 part 1 report.

## 8. Files

- `src/clipwin.c`: bank 1, the hooks and their stock calls (the poll, the reader, the knob, the Waveform's binding,
  its corner labels).
- `src/clipwin_b2.c`: bank 2, the maths and the policy of every hook (§3.5).
- `src/clipwin.h`: the shared pad, knob and waveform fields, `cw_bank`, the `cw_*` prototypes, and the asserts that pin
  bank 2's offsets.
- `src/clipwin_thunk.S`: the H1, H1′, H3 and H3′ thunks.
- `src/filter_thunk.S`: `clip_read_b` → `clipwin_read`.
- The chain lines are in `src/duck.c` (`clipwin_tick(engine)`), `src/master.c` (`clipwin_register`, `CORE_BYTES`,
  the magic clear) and `src/insert.c` (`clipwin_defaults`).
- `build.sh` (`BANK2_SRCS` += `clipwin_b2`).
- `patches/clipwin.py`: the sites and the Pos pages; it is imported by `patches/filter.py`.
- `test_clipwin.py`, `test_bank2.py`.
- `README.md`: the Slip, Region, Loop Len, Fit, Loop Fade and Waveform bullets, and Known issues.
- `bench/bbusb.py`: `slip`, `knob`, `fit`, `shift`, `record`, `peek`, `crash`.
