# Clip Window: Slip, Region, Loop Len and the Clip-mode Waveform knobs

Release **37.2.0** (dev build 37.2.0d), branch `37loop/blackbox-t-018`. It sits on Slip (release 37.1.1) and its
stale-latch fix (`37loop/blackbox-t-004`), and adds Region, Loop Len and the Waveform knobs (P3's three commits, first
built on `feat/region`, ported onto the fix), a "bank 1 room" commit before the knobs, and JOEBOX's pre-listen cell fix.
Status on 2026-10-16:

- All four parts pass under Unicorn: `test_clipwin.py` 349 checks, `test_bank2.py` 25, `./check.sh` 31 suites, 0
  failed.
- Slip v1 was measured on the unit at Gate 2 (37.1.0d, `notes/bench/2026-10-15-gate2-slip.md`).
- The knob rework and the CDJ sign (37.1.1), Region, Loop Len and the Waveform knobs have not been on the unit yet.
  That is Gate 3, and §6 is its recipe.
- **This build needs both files from the same build on the card**: `BLACKBOX.bin` and `BBEXTRA.BIN`. Loop Len's
  take and its window run in flash bank 2 (D-017).

Other documents: the decisions are `notes/decisions.md` (D-002, D-003, D-004, D-016, D-017) and the reverse
engineering behind it is `notes/re/README.md` §2–§3 (step notes a1, a2, a3, x3). Users read the README bullets and
Known issues. The research model of the hooks is outside the repo, in `/srv/dev/firmware/re-scratch/a2/r2/cw2.py`
(with `k_region.py`, `k_looplen.py`, `k_seam.py`).

## 1. What it does on the unit

### Where the controls are

| where | control | id | values | default | saved as |
|---|---|---|---|---|---|
| Clip pad, Pos tab, row 5 | `Region:` | `0x1c8` | Auto, File, Loop | Auto | `clipregion` |
| Clip pad, Pos tab, row 6; Clip Waveform BL | `Slip:` | `0x1c9` | −4.000 … +4.000 (−3840 … +3840 ticks) | +0.000 | `clipslip` |
| Clip pad, Pos tab, row 7; Clip Waveform BR | `Loop Len:` | `0x1ca` | Off, 1/16, 1/8, 1/4, 1/2, 1 bar, 2 bars, 4 bars | Off | `cliplooplen` |
| Clip Waveform TL | `Loop Start:` | stock `0x91` | 0 … Loop End, frames | stock's | stock's |
| Clip Waveform TR | `Loop End:` | stock `0x92` | Loop Start … the file's length, frames | stock's | stock's |

The Pos tab now reads Loop Mode, Beat Count, Quant Size, Sync, Region, Slip, Loop Len. As on every stock pad page,
TL/TR move the selection and BL/BR turn the selected row. All three rows are per pad and saved with the preset. At
their defaults the pad plays exactly as stock (bit for bit, under emulation).

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
- **Knob feel** (the same on the Pos tab and on the Waveform's BL):
  - **Slow:** single ticks, one per 40 counts. At the stock accelerator's speed 2 it gives one per 20 counts.
  - **Fast** (speed 3 and up, ≥ 3 counts/ms): one 1/64 per turn event, snapped to the 1/64 grid. From `+0.025`, the
    first fast step lands on `+0.060`.
  - **Zero is a detent.** A turn that reaches or crosses 0 stops on `+0.000` and stays there while the same turn
    goes on (events less than 250 ms apart, in the same direction). A 250 ms pause, or turning the other way, moves
    on. This came from Gate 2: "tricky, especially to set back to 0".
  - It clamps at ±4.000.
- **When a change is heard.** At the next Sync step, through stock's crossfade, with no added silence. A recorded pad
  defaults to Sync 1/16, so that is within a sixteenth. A launch that is waiting for its Quant point still starts on
  its bar, and it plays the new Slip from its first sample. On Sync None, a change waits for the clip's restart.
- **A new file under a playing pad** (a load, a take landing in it, or the browser's pre-listen, which loads every
  highlighted file into the pad it was opened from): stock does not restart the voice, its segments read on at their
  positions in the new file. The segments made for the old file (the sounding one and the pending one) then read as
  stock reads them, unslipped and without the region or the window, and the next segment latches the new file. So
  for up to two Sync steps the pad plays as stock would, then as set.

### Region

- **What it does.** A Clip pad plays the loop of the file, `[Loop Start, Loop End)`, as if it were the whole file.
  The loop points are the same ones Sample mode uses. Stock keeps them in Clip mode, and a WAV's own `smpl` loop
  arrives in them. A loop cut from a longer recording therefore needs no Trim, and the file stays whole.
- **The values:**
  - **Auto** (the default, D-003) plays the loop when the pad has one: Sample mode's Loop Mode is Forward or Bidir,
    `0 ≤ start < end ≤ length`, and the loop is not the whole file (`[0, ≥ length − 1]` is what a load leaves). Any
    other pad plays the file. So fresh recordings and plain files play as stock.
  - **File** always plays the whole file, as stock does.
  - **Loop** plays the loop points whatever Loop Mode says. The whole file is still the whole file.
  - Bidir counts as on, but the region always plays forward.
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
    Quant, or on the new loop's own length when that is shorter), so it never doubles.
  - A stopped pad, and a one-shot (Launch Trigger or Loop Off), takes the new region at its next launch.

### Loop Len

- **What it does** (D-004: the KP3's loop, anchored where the music is). When you turn it on, only a window of that
  length loops, in time. The window is the part of the clip that was playing when you engaged it, rounded down to the
  length's grid in the clip. For example, 1/4 engaged during beat 3 repeats beat 3, and 1/16 repeats the sixteenth of
  it that was playing.
- **Changing it:**
  - Changing the length while it is on keeps the in-point and moves the end.
  - Off goes back to the whole loop in phase, as if it had played on all along.
  - Off and on again within one Sync step takes the same window back.
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
  - Turned all the way into each other, they leave no loop, and the pad plays the whole file until they part.
- **BL Slip and BR Loop Len.** These are the Pos tab's rows, with the same text and feel.
- **The white bracket.** It shows the loop Region plays, using the engine's own rule, as soon as you turn. A playing
  pad takes the new loop the next time its loop comes round, so while you turn, the bracket is ahead of what you hear.
  There is no bracket (and the loop points are not heard) on Region File, or on Auto with Loop Mode None. Slice
  markers stay visible beside the bracket.

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
   - Beat Count Auto rounds the region to whole beats at the clock's tempo. If the cut is far from a whole number of
     beats, set Beat Count to what it should be.
   - **Or the stock way, with audition**, before step 3: in Sample mode set Pos Loop Mode Forward, set Waveform BL/BR
     to Loop Start/End, and press Trigger until the turnaround is clean. Then set Pad Mode → Clip with Region Auto:
     the loop comes along, because Sample → Clip keeps it. Do not go back to Sample mode afterwards: stock clears the
     loop points on Clip → Sample.
6. **Slip.** Use Waveform BL, or Pos Slip. Turn fast (1/64 steps) to get close to the metronome, then slowly (single
   ticks) until the hits sit. It stops on 0 on the way: pause, then turn on.
7. **Refine, if needed.**
   - Move TL/TR again. A change is heard at the next wrap.
   - Loop Len (BR) 1/4 or 1/16 loops a beat or a sixteenth of what is playing. Off returns to the whole loop, in phase.
8. **PSET Save.** The preset holds Region, Slip, Loop Len and the loop points.

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
| H1 | `0x0806578C` (`FUN_08065550`, segment start) | `bl 0x0806375C` prefetch | `clipwin_seg_start_b` → `clipwin_seg_start(src, pos, k = [sp+0x20], pad = r4)` | latch slot k (Slip, region, Loop Len window from bank 2's `cw_window`, the file's length), prefetch where it will really read |
| H1′ | `0x0806541A` (`FUN_08065290`, slice-marker segment) | `bl 0x0806375C` | `clipwin_slice_start_b` → `clipwin_slice_start(src, pos, k = [sp+4], pad)` | invalidate slot k, clear its `h1` bit, prefetch unchanged |
| H2 | `0x08066622` (`FUN_08066454`, segment reader; already JOEBOX's `clip_read_b`) | `bl 0x080662E4` | `src/filter_thunk.S` `clip_read_b` now ends in `b.w clipwin_read` | mapped read: stock's reader at the real position, or its work done over two fetches at a seam; machine modes through `filter.c`'s `clip_read_ring`; the seam hint; stock's read when the file's length is not the latch's |
| H3 site 1 | `0x08064B2C` (recompute, first length) | `bl 0x080636F0` `fw_src_len` | `clipwin_len_recompute_b` → `clipwin_len(src, pad, 1, —)` | adopt a new region (at this pad's wrap, or when no layer plays); answer the region's length (Beat Count Auto, frames per step) |
| H3 site 3 | `0x08064C5A` (recompute, second length) | `bl 0x080636F0` | `clipwin_len_steps_b` (r3 = r9 = the clip in output samples) | the region's length; a synced clip of one step gets `+0x204` = the clip, not the length |
| H3 site 0 | `0x0806561E` (`FUN_08065550`'s `> 0` check) | `bl 0x080636F0` | `clipwin_len_b` | the region's length |
| H3 site 2 | `0x08065690` (the last step's end, `len − 1`) | `bl 0x080636F0` | `clipwin_len_end_b` | seamless wrap: 1 (end = 0) when Loop On and not Trigger; else the region's length |
| H3′ | `0x08066FAC` (render, the synced wrap) | `bl 0x08064A94` recompute | `clipwin_wrap_b` (r2 = sp + 0x58, the next pass's tick) → `clipwin_wrap(pad, clock, t)` | the recompute with this pad marked wrapping (it adopts); put a grid-moving region back until a wrap on its grid |
| H3′ | `0x08066E9E` (render, the unsynced wrap) | `bl 0x08064A94` | `clipwin_wrap_free_b` (r2 = 0) | the same, no grid check |
| F | `0x080B0746` (set value) and `0x080B0E18` (type-1 turn) | `bl 0x080B0528` formatter | `clipwin_format(knob)` | Slip's beats.ticks text (type 1 or 9, id `0x1C9`, not frozen) |
| K | `0x080B0DDE` (`FUN_080B0D54`, type-1 turn) | `bl 0x080B0B74` stepper add | `clipwin_turn(stepper, counts)` | Slip's knob: slow ticks, fast 1/64 grid, stop on 0 |
| W bind | `0x080A582A` (`FUN_080A54A0`, the Clip bind block's last unbind, BR) | `bl 0x080A7EE0` binder | `clipwin_bind` | bind TL `0x91`, TR `0x92`, BL Slip, BR Loop Len through the stock binder with the view store's values |
| W zoom | `0x080A53B0` (`FUN_080A53A2`, every bind and zoom change) | `bl 0x080A52C4` | `clipwin_zoom(view, zoom)` | Clip only: TL/TR step = max(1, zoom), then range, then value; the bracket |
| W refresh | `0x080A5B0E` (the Waveform refresh's Clip case) | `bl 0x080C6E8C` slice markers | `clipwin_wave(wave, slices)` | stock first, then range/value of TL/TR, re-value BL/BR when the store differs, the bracket |
| P | `0x080EF998` and `0x080EF290` (both copies of the Clip Pos page) | u16 `0, 0, 0` | `0x1C8, 0x1C9, 0x1CA` | the three rows in slots 5–7 |
| tick | `duck_block` (`src/duck.c`, JOEBOX's hook of `0x0804CE74`), after `insert_tick()` | — | `clipwin_tick(engine)` | one pad a block: Slip and Loop Len from the app's store; the guarded drop; Loop Len's take (bank 2) and its Sync |
| H4 | none: `clipwin_tick` → `set_sync` | — | `FUN_08067648(pad, engine, {0x39, 0, cell, 0x94, idx, 0}, engine + 0x128E0)` | Loop Len's forced Sync, as the app's message would set it (stock re-grids live) |
| R | `master_register` (`src/master.c`) | — | `clipwin_register(table)` | `fw_register_list` Region (3 names), `fw_register_num` Slip (type 1, ±3840), `fw_register_list` Loop Len (8 of stock's own strings) |
| D | `insert_defaults` tail (`src/insert.c`) | — | `clipwin_defaults(store)` | `fw_store_add` of the three ids at 0; a pad store holds 85 of JOEBOX's 96 |
| M | `master_alloc` (`src/master.c`) | — | `EXTRA_BYTES` `0x2D900` (includes `0x800` for `cw_bank`) | the bank's magic cleared at `block + 0x83900` every boot |

H5, the playhead message `0x4A` at `0x080668FC`, is not built. The playhead stays stock's.

### 3.3 State: `cw_bank`

The bank lives in SDRAM at `master_block() + 0x83900` (`PRISM_BYTES 0x56800 + 0x2D100`), with `0x800` reserved and
`0x720` used. The layout is in `src/clipwin.h` and the magic is `CWN4`. The magic history: `CWN1` was 37.1.x, `CWN2`
the stale-latch fix (the latch's `len`), `CWN3` the Region step, and `CWN4` arrived with Loop Len. (On `feat/region`,
without the fix, `CWN2`/`CWN3` were Region/Loop Len and the bank used `0x620`.) When the magic is wrong the bank is
cleared whole, with a word loop, and the magic set. `master_alloc` clears the magic at every boot, because SDRAM keeps
its contents through a reset. If there is no block, every hook passes through. There is no `.data` or `.bss`, and no
exclusive access anywhere (D-013).

| offset | field | meaning |
|---|---|---|
| `0x000` | `u32 magic, scan` | `CWN4`; the poll's pad counter (`q = scan++ & 15`) |
| `0x008` | `i32 slip[16]` | Slip as last polled, ticks (+ = ahead) |
| `0x048` | `u8 *pad[16]` | the class-B pad object, cached by H1 (validated before use: class `0x4C`, same cell) |
| `0x088` | `u8 valid[16]` | bit k: `latch[q][k]` holds |
| `0x098` | `{i32 rs, vlen, delta, len} latch[16][4]` | per segment slot: the region (or the file) and the shift, frames; the file length it was made for |
| `0x498` | `u8 h1[16]` | bit k: slot k was made through H1, not H1′ |
| `0x4A8` | `u8 hinted[16]` | bit k: H2 has hinted `rs` for this slot's crossing |
| `0x4B8` | `u32 zero_at; i8 zero_dir; u8 zero_hold` | the Slip knob's stop on 0 |
| `0x4BE` | `u8 wrap` | 1 + the pad whose wrap recompute is running (`clipwin_wrap`) |
| `0x4C0` | `{i32 rs, vlen} region[16]` | the region each pad plays this pass; `vlen` 0 = the whole file |
| `0x540` | `i32 good[16][2]` | the last loop points from the app's store that made sense (fallback source) |
| `0x5C0` | `i32 origin[16]` | Loop Len's in-point, ticks into the clip |
| `0x600` | `u8 ll[16]` | Loop Len as taken (0 Off, else `W = 240 << (ll − 1)`) |
| `0x610` | `u8 forced[16]` | 1: Loop Len has forced the pad's Sync |
| `0x620` | `i32 sf[16][4]` | Slip's part of `latch[q][k].delta`, frames |

The offsets that bank 2 reads are pinned by `_Static_assert` in `src/clipwin.h`: `valid`, `latch`, `origin`, `ll`,
`forced`, `sf`, and the pad and segment fields. Moving one makes a new bank-2 payload.

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
  Loop  iff  mode != File  &&  len valid  &&  0 <= ls < le <= len  &&  !(ls == 0 && le >= len − 1)  &&  (mode == Loop || on)
  ```

  Here `mode` is the Region row, `on` is Sample mode's Loop Mode (`0x8E`), and `len` is `fw_src_len`. A length of 0
  or the provider's `0x10000000` sentinel means no region.
- **The source.** The loop points are read from the cell's class-H object, `H = *(pad + 8)`, when it is class `0x48`
  on the same cell: `+0xFC` Loop Start, `+0x100` Loop End, `+0x108` Loop Mode, in queue order. Otherwise they come
  from the app's store (`0x91`, `0x92`, `0x8E`), which keeps the last pair that made sense. The region is
  `rs = ls`, `vlen = le − ls`.
- **What H3 answers.** It returns `vlen` at sites 0, 1 and 3. At site 2 it returns 1, so the last step has no end and
  crossfades into the next pass like any other step; that applies only with Loop On and Launch not Trigger. At site 3
  a synced clip of one step (n = 1, clip > 0) gets `+0x204` = the clip in output samples. Stock times that step by
  the length, which doubles or leaves a gap each wrap.
- **When a new region is taken.** A new region is adopted only at site 1, and only while this pad's wrap recompute
  runs (`wrap == q + 1`) or while neither of its layers plays. A change in mid-pass would leave the steps already made
  pointing past the new end: 11 418 or 23 490 silent samples (a2).
- **The wrap grid.** After the wrap's recompute, `clipwin_wrap` compares the next pass's start tick `t` (the render's
  i64 at `[sp + 0x58]`) with the new `+0x230`. If `t mod grid ≠ 0` and the region changed, it puts the old region
  back and runs the recompute again, so the pass plays as it was. Without this, stock snaps that pass's end into the
  past and starts two passes at once at gain 2, which is what stock does on a live Beat Count change from 2 to 4.
  Ticks past 2³² skip the check.

**Loop Len.**

- **The window** (bank 2, `cw_window`, asked by H1 when Loop Len is taken and `b2_live()` holds). `W = 240 << (v − 1)`
  ticks: 1/16 = 240 … 4 bars = 15 360. It applies in H1 when `W < clip`, `W mod tps = 0` and `origin mod tps = 0`. A
  segment of step j then plays step `w = (origin + ((j·tps − origin) mod W)) / tps` from stock's own product,
  `(int)((float)w × fps)`. A tick-domain formula would be a frame off on a non-integer fps.
- **The take** (bank 2, `cw_looplen`, called from `clipwin_tick`):
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
  5. It returns `(idx + 1) << 8 | moved`. Bank 1 sends the Sync through the param-set (H4). On `moved`, it does the
     guarded drop, so H1 re-latches the pending steps.

**The guarded drop** (`clipwin_tick`, on a Slip or Loop Len change). Each slot that is active, not done and has
delay > 0 is marked done. The exception is a slot with `+0x3C` set: dropping a pending launch would sound it at once,
off its bar. Such a slot is latched again in place if H1 made it.

**The Slip knob.** The stepper has 400 counts per step for type 1, and the stock accelerator speed is m (1..6).

- m < 3: it adds `counts × 10 × m`, unless that would cross 0, in which case the target is 0.
- m ≥ 3: the target is the next multiple of 60 in the turn's direction, or 0 if that crosses it.
- The value is set by parking the accumulator mid-step on the target: `(target − start) × step + step/2 − acc`.

### 3.5 Bank 2

Two functions of `src/clipwin_b2.c` run from bank 2 (D-017, Thomas: move to bank 2 rather than trim): `cw_window`,
Loop Len's per-segment window (moved by the "bank 1 room" commit, when the port of the stale-latch fix had left Loop
Len at 0 B free), and `cw_looplen`, Loop Len's take (moved when the Waveform knobs came).

- They are leaf code: they read the bank and the pad they are handed and call nothing outside their file.
  `test_bank2.py` enforces that, because bank 2 lives through every bank-1 install and a call out of it would go
  stale; it plants a `bl` in each to prove its scan still sees one.
- `latch()` asks `cw_window` and `clipwin_tick` calls `cw_looplen` only when `b2_live()` holds, which means this
  build's payload is up there and read clean. Otherwise Loop Len stays Off: the row is kept as stored but never taken,
  and no Sync is forced.
- Bank 2's id hashes its `.c` files only (`build.sh`). Bank 1 pairs with the payload on its sum, and a bank-1-only
  edit of `clipwin.h` leaves bank 2's bytes, and so needs no reflash.

**Sizes, this build** (`arm-none-eabi-size -A out/cave.elf`): `.cave` 57 624 of 57 736 B (112 free) and `.bank2`
13 540 B. The bank-2 payload header is id `0x2c4676ca`, len `0x3500`, sum `0x73f8a581`. The previous payload, release
37.1.1 (and 37.1.x with the stale-latch fix), was id `0xf5f0171b`, len `0x3280`; `feat/region`'s 37.2.0 build had id
`0xfd79d330`, len `0x3480`. How the cave got here: notes/re/README.md question 5.

### 3.6 What stays stock

- **The timing.** When every segment starts, launch quantization, the 256-sample crossfades, the Sync step grid and
  its live re-grid, wrap scheduling, one-shots, retriggers and Sync None restarts are all stock's.
- **The reader.** The reader and its kernel (called at the mapped position) and the machine modes' DSP (`filter.c`)
  are unchanged. Stock's segment positions are never rewritten.
- **The engine and the app.** The engine ignores `0x1C8..0x1CA`: the class-B param-set drops ids above `0xF4`. Stock
  stores and saves the rows through `SetCellParam`. The view's generic forward stores the four Waveform knobs with no
  code of ours.
- **Excluded pads.** Slicer pads and Clip pads on Sync Slice with markers play stock (their segments start in H1′).
- **The display.** The playhead line (msg `0x4A`) shows stock's position: unslipped, outside the region, not
  windowed. Stock's Beat Count, Quant and Sync rows are unchanged; a forced Sync is not shown.

## 4. Limits and known issues

**Slip**

- It does nothing on Slicer pads, or on a Clip pad set to Sync Slice with slice markers.
- On Sync None, a live change waits for the clip's restart (len − 257 samples).
- `+1.500` reads as beats.ticks, which is 1.52 beats, not one and a half.
- **A file loaded under a playing pad** (the browser's pre-listen loads every highlighted file into the pad too)
  plays as stock would, unslipped and without its region or window, for up to two Sync steps, then as set (§1). Fixed
  here: before the fix the pad kept mapping its latches over the old length until its next segment, silent past a
  shorter file's end or with the old shift (`37loop/blackbox-t-004` `9ac8c24`, ported into each P3 step). The
  streaming misses and stock's own gaps after a file change are stock's and stay.

**Region**

- It does nothing on the pads Slip ignores. The playhead line is wrong on a pad playing a region.
- Clip → Sample clears the loop points (stock).
- A Beat Count that is not Auto, including one read from the WAV's `acid` chunk at load, is taken as the region's
  length in beats.
- A stopped pad, and a one-shot, takes a new region at its next launch. Until then the clip length it reports (msg
  `0x8D`, Beat Count Auto's display) is the old one.
- **A region under half a beat** counts 0 beats on Beat Count Auto, as stock counts a file that short. It loops on its
  own length, restarting 125 samples early with a 379-sample overlap at peak 1.69 (stock's 9 000-frame file: 8 625
  sample period, peak 1.66), and Slip does nothing. Give it a Beat Count.
- **A change that would put the pass off its wrap grid** waits for a wrap on the new grid. In rare setups (Quant
  changed while the pad plays) that wrap never comes, and the change waits for a stop and relaunch. Neither case has
  been run.
- A WAV's `smpl` loop end is stored inclusive (`dwEnd`), so such a region is one frame short. It is kept that way;
  nothing hears it.
- Taking a pending region at the relaunch recompute sites (`0x08068312` and the others) is not modelled (open question
  13). A pad relaunched while it plays keeps its region.
- SD streaming at the region seam has not been run on the unit. The hint is checked, the cache is not (miss counter
  `0x24013930`, question 9).

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
- **Without this build's bank 2**, the row is there, turns and saves, but does nothing. An older payload in bank 2
  also switches off Prism, Confetti and the inserts. Whether to show `---` instead is open question 30, Thomas's call:
  it measured +48 B of the 112 free.
- **Not run anywhere:** Pitch with it on; a Trigger or Gate relaunch with it on; a Region or Beat Count change with it
  on (the in-point is kept and may fold round a shorter clip).
- A take right after a file change (review F1, release 37.2.0): Loop Len turned Off and on again within two Sync
  steps of a new file loaded into the playing pad maps the sounding segment through its old latch (`cw_looplen` does
  not check `len`, H2 does), so the in-point can be the old window's beat (probe: origin 0 where 1 920 is played).
  Fix later in bank 1: `clipwin_tick` clears the valid bits of latches whose `len` differs from `fw_src_len` before
  `looplen()` (a few bytes, no new bank-2 payload).

**The Waveform knobs**

- Loop Start turned up to Loop End leaves no loop, and the pad plays the whole file until they part.
- On Region File, or Auto with Loop Mode None, the knobs move the points but nothing is heard and no bracket shows.
- The dead travel at the top of a sample-position knob is stock's, kept: up to `step − 1` positions above the
  maximum all read the maximum. It has not been seen on hardware (question 16).
- After Clip, New Rec and New Multi keep these four rows bound, as stock keeps Sample's after Sample.

**Space**

- Bank 1 has 112 B free, after the "bank 1 room" commit took 216 B back (Loop Len's window to bank 2, -116 B; a stale
  bank cleared with a word loop, -64 B; `pad_store()` one multiply, -24 B; `clipwin_defaults()` a loop, -8 B). The size
  of the id check in `b2_ok` / `header_ok` moves by a few bytes when the bank-2 id changes, and the linker refuses an
  overflow.
- What else could go: only Loop Len's code is bank-2 by rule (Slip and Region work without bank 2), and what is left of
  it in bank 1 is calls and the Sync message (about 40 B if `cw_looplen` built the message itself). More than that means
  Slip/Region maths in bank 2 (they would then need `BBEXTRA.BIN`) or JOEBOX's Munchi engine split out of `munchi.cpp`.

## 5. How each piece was tested

**What the suite runs.** `test_clipwin.py` runs the real patched firmware under Unicorn on `emu.Emu(IMAGE,
"out/cave.elf")`:

- The whole class-B block method, block after block, with the real clock advance.
- The cell's class-H object, the real param-set for every setting, and `clipwin_tick` reading the app's stores.
- The stock registrar and store builder, `master_alloc`, the stock knob paths, the Waveform screen's setup, handlers
  and `SetCellParam`, and bank 2's `cw_looplen` and `cw_window`.

**What it compares against.** Every scenario also runs with the clipwin hooks taken out at run time, and the Slip-0
ones on the stock 3.1.9 image. Region scenarios run against the stock image playing a file as long as the region.
The research model's numbers (a2/r2) are asserted.

**The sample source** is stubbed with a ramp (frame q holds `(q + 1)·2⁻²⁰`), so every output sample decodes to the
frame it plays and the gain it plays at.

| § | what | how it is proven |
|---|---|---|
| 1 image | every site, the thunks' registers, both Pos pages, no other stock byte changed, `master_alloc` | each site decodes to the intended `bl`; the stock facts the two newer thunks rely on (r9 at `0x08064C5A`, `[sp+0x58]` at the wrap) re-read in the image |
| 2 registration | the three rows, labels ≤ 9 characters, unique xml names, defaults | the stock registrar `FUN_0808C158` and store builder `FUN_08093F20` run whole; 85 of 96 entries |
| poll | `clipwin_tick` unit: one pad a call, the clamp, the guarded drop, a stale cached pointer, no SDRAM, a stale bank (another magic, every byte 0xa5) | fake stores, fake pads; the stale bank is zeroed whole by the first poll and nothing past its `0x720` bytes is touched |
| 3 off = stock | Slip 0 on the matched file, an 88 615-frame file, a late launch, Sync None | every read, fetch, prefetch, output sample and message identical to the hooks out **and** to stock 3.1.9 |
| 4 Slip | Slip 0, 960, −30, 7, 3839 on 96 000 / 88 615 frames; a late launch; Quant 1 beat < Sync 1 bar; Sync 1/16; a retrigger; a live Sync change; a tempo change; `clip = tps × n` | every sounding sample plays `(stock frame + slip_f) mod len` (max error 0.0106 frame) at stock's summed gain; every write lands in `cw_bank`; the seam hint fires from exactly the crossing segments |
| 5 live change | 0 → 480 and 0 → −7 in a step; the sign; Sync None; a pending launch; armed while stopped | stock-identical up to the step boundary, slipped after, no added silence; the launch keeps its bar (`+0x140` 11 520, msg `0x1D`) and plays slipped from its first read |
| 5b new file | the load chain (the slot closes, a recompute while closed, the new file opens, the 0xE handler's `0x90`) under a playing pad, with a shorter, a longer and a same-length file; Slip 0, 960, −480; a latch made for another length in the reader unit | stock as measured (no restart, the pending step on the old grid); Slip 0 bit for bit stock; the segments latched before the change read exactly as stock's, no added silence, no read past the new end stock does not make; the next segment latches the new file and plays stock + slip_f; the same length keeps the latch |
| 6 gating | Slicer with and without markers, Sync Slice + markers, cell `0x401`, `fw_src_len` 0 / sentinel, no SDRAM | plays exactly as with the hooks out, no latch |
| 7 reader | seam reads mono and stereo, rate 1 / 0.7 / 2.3 / 8, a 40-frame file; every machine mode at, before and after the seam; the filter object's rate | bit for bit what the stock reader (or `filter.c`'s `clip_read`) makes of the file turned circular |
| 8 rate, stereo | a 44.1 kHz file, stereo 48 and 44.1 kHz, Pitch +7 | every sample stock + slip_f, the same gain |
| 9 knob | texts (`+1.280`, `-0.030`, `+4.000`, a stale or frozen knob), slow/fast/zero on the pad page and the Waveform, six other knobs | the stock binder and turn paths; other knobs post exactly as on stock |
| 10 Region | the rule over 20 cases; each H3 site; adoption only at the wrap; the wrap-grid hold; the fallback source; whole-process runs; a new file under a playing region (50 000 frames: the region no longer fits; 192 000: it does) | against stock playing the region as a file: every sample at `rs + (frame + slip_f) mod vlen`, every recompute field equal, no zero-gain sample; seamless wraps (stock: 8 006 zero-gain samples on a short region, peak 2.0 on a long one; ours 0, 1.0); one-step clips (32 000: peak 2.0 → 1.0; 20 000: 16 012 zero-gain → 0); the 9 000-frame region; live changes (heard at the wrap, a pass later from the last step, held to the bar where stock doubles, region → File); Sync None; 44.1 kHz stereo; gating; writes; the new file: the old segments read at their own positions in it (no mapping, nothing past its end, no silence), the next latch `(0, 50 000, 25 000)` or `(24 000, 48 000, 24 000)` made for the new length, Slip 960 = the Slip 0 run + slip_f |
| 11 Loop Len | `k_looplen` L1–L4: origin 7 680, 1 200, 1 920, the launch held; live 1/4 → 1/8 → 1/2; 88 615 frames; over a region with Slip; the five do-nothing cases; Sync re-sent by the app; a stopped pad; a 44.1 kHz file; off/on in one step; stop and relaunch; a 5-beat clip; no bank 2; a new file under a playing window (50 000 and 192 000 frames) | each segment starts on `(int)((float)w × fps)`; the forced Sync times every segment and gain exactly as stock sent that Sync itself; Off in phase; without bank 2 bit for bit as never set, neither `cw_looplen` nor `cw_window` entered; after the new file, the old segments read as stock, the next ones are made for its length and replay its frame 0 |
| 12 Waveform | the bind order, the four rows and texts, the bracket, TL/TR turns, the forward, `SetCellParam`, zoom, other modes | the same six turns give the same posts, steps, ranges and pending positions as stock's Sample-mode Loop Start/End knobs; Sample, Granular, Slicer, Sample after Clip are the screen with the hooks out |

**Elsewhere.** `test_bank2.py` (25 checks) holds bank 2 to the leaf rule. Its scan now tells the second half of an
instruction from a planted `bl`, using the linker's mapping symbols, and plants one in each of `cw_looplen` and
`cw_window`. `test_insert.py` and `test_lfo.py` hold the pre-listen cell `0x401` off pad 2. `./check.sh` runs all 31
suites.

**On the unit.** Gate 2 ran on 37.1.0d, with Slip v1 under D-014's sign and no bank 2:

- `+0.060` moved Out 1 by +1 500 samples, exactly, and `−0.120` by −3 000.
- A live change was smooth.
- Save, power-cycle and reload kept `+0.120`.
- There was no fault.

**Not checked anywhere yet:**

- the D-016 sign and the knob rework, by ear;
- Region, Loop Len and the Waveform knobs on hardware;
- the bank-2 install of this build;
- SD streaming at a seam;
- a negative Slip through preset save / load (question 3);
- the app's loader and Pad Mode change feeding the class-H object (posted in emulation as the app posts them);
- the knob's counts per revolution;
- the bracket as drawn;
- CPU cost on the chip.

## 6. How to bench it: Gate 3 recipe

**Unit and tools.** Use the dev build 37.2.0d (USB peek in), with **`BLACKBOX.bin` and `BBEXTRA.BIN` from the same
build**. Cable the power jack to mgr-ran's USB. Measurements come from `bench/bbusb.py` over the USB audio (Outs 1–3,
24-bit / 48 kHz) and the peek.

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
- For pad q = 4 × row + col, with `B` the bank address it prints:

| what | address |
|---|---|
| region | `B + 0x4C0 + 8q` (rs, vlen) |
| origin | `B + 0x5C0 + 4q` |
| `ll` | `B + 0x600 + q` (a byte) |
| `forced` | `B + 0x610 + q` (a byte) |
| latch, slot k | `B + 0x98 + 64q + 16k` (rs, vlen, delta, len) |

- `peek` prints little-endian words, so byte q is byte `q % 4` (lowest first) of word `q / 4`.
- The pad object is the `pad object` printed by `slip`. Its `+0x220` is the Sync step in ticks (960 = 1/4, 240 =
  1/16).

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
| 0 | install | both files on the card, BACK + INFO at power-on; let the first boot restart itself once (bank 2 written) | TOOLS shows `37.2.0d` with **no `!`** before the load figures; `bbusb.py crash`: no fault or watchdog record |
| 1 | reference | A alone → `a.wav`; then B alone on Region Auto (= File), Slip 0, Loop Len Off → `b_file.wav` | sounds as stock; `shift a.wav b_file.wav` gives the Resam's own offset (note it; every check below is against `b_file.wav`) |
| 2 | Region by the knobs | Region **Loop**; Waveform TL Loop Start to L ≈ 6 000, then TR Loop End to L + 96 000 (one bar; the knob shows frames and moves in whole steps from its range's start, so zoom in until it lands; note L) → `region.wav` | the bracket shows at once and is heard from the next wrap; `shift b_file.wav region.wav` **−L** (−6 000 = −240.0 ticks for L = 6 000); peek region[q] = (L, 96 000); no click, flam or gap at the loop point |
| 3 | Slip on the region | Slip `+0.060` → `rslip1.wav`; `−0.120` → `rslip2.wav` | **−L − 1 500** and **−L + 3 000** (−7 500 and −3 000 for L = 6 000; the D-016 sign: `+` comes earlier); the seam now falls mid-step (Sync 1/4): still no click |
| 4 | Slip knob feel (first time on the unit) | turn BL slowly, then fast, then back through 0; the same on the Pos tab | slow = single ticks; fast = 1/64 steps (values move by `0.060`); a turn stops on `+0.000`, a short pause then goes past it |
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

Report in the form of `notes/bench/2026-10-15-gate2-slip.md`: one row per check, the measured value, and pass or
not. Three things to answer along the way:

- whether a preset load stops a playing pad (Loop Len's F4 rule);
- whether the bracket's lead over what you hear is acceptable;
- whether Loop Len without bank 2 should read `---` (question 30).

## 7. Files

- `src/clipwin.c`: bank 1, the hooks, the poll, the reader, the knob and the Waveform.
- `src/clipwin_b2.c`: bank 2, Loop Len's take and its window.
- `src/clipwin.h`: the shared pad fields, `cw_bank`, and the asserts that pin bank 2's offsets.
- `src/clipwin_thunk.S`: the H1, H1′, H3 and H3′ thunks.
- `src/filter_thunk.S`: `clip_read_b` → `clipwin_read`.
- The chain lines are in `src/duck.c` (`clipwin_tick(engine)`), `src/master.c` (`clipwin_register`, `EXTRA_BYTES`,
  the magic clear) and `src/insert.c` (`clipwin_defaults`).
- `build.sh` (`BANK2_SRCS` += `clipwin_b2`).
- `patches/clipwin.py`: the sites and the Pos pages; it is imported by `patches/filter.py`.
- `test_clipwin.py`, `test_bank2.py`.
- `README.md`: the Slip, Region, Loop Len and Waveform bullets, and Known issues.
- `bench/bbusb.py`: `slip`, `shift`, `record`, `peek`, `crash`.
