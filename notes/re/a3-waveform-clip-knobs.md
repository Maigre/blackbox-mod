# A3 — the Waveform screen in Clip mode, and the knob machinery a new numeric row needs

Stock 3.1.9 (`BLACKBOX-3.1.9.bin`). Found 2026-10-15 (blackbox#t-003), revised the same day after an independent
verification round (see "Verification"). Four questions: what the Clip branch of the Waveform setup binds and draws;
whether the generic knob forward stores Loop Start/End for a Clip pad; whether numeric rows accelerate; how the
value→text formatter could print beats.ticks for one id.

## 1. The Waveform setup's pad-mode switch

`FUN_080A54A0(view, force)` reads Pad Mode `0x8b` (`cellmode`: 0 Sample, 1 Clip, 2 Slicer, 3 Granular, 4 New Rec,
5 New Multi) and MultiSam `0xea` from the view's own copy of the pad store at `view+0x2370` (filled by
`FUN_0809A830`). It has two parts:

- a **bind block**, run only when the mode changed, the WAV changed, `view+0x23F8` is set (msg `0x67` for this pad)
  or `force` is 1 (msg `0xd4`);
- a **refresh switch** (`tbh` at `0x080A563A`: Sample and Granular → `0x080A598C`, Clip → `0x080A5B04`, Slicer →
  `0x080A5B14`), run on every call, after the bind block when that runs. Every `0x66` ("param changed") for the
  view's pad calls `FUN_080A54A0(view, 0)` from the view's event handler `FUN_080A6D28`, so every stored change of
  any pad param refreshes the screen.

The four knobs are `TL view+0x670`, `BL +0x950`, `TR +0xC30`, `BR +0xF10` (widgets `0x2E0` apart). In encoder
message `0x32`, knob index 0 = TL, 1 = BL, 2 = TR, 3 = BR.

| Mode | TL | TR | BL | BR | white loop bracket | pink start/length | slice markers | zoom on bind |
|---|---|---|---|---|---|---|---|---|
| Sample, Granular | `0x8f` Start | `0x90` Length | `0x91` Loop Start | `0x92` Loop End | on unless Loop Mode `0x8e` = None (then BL/BR greyed) | on | off | whole file |
| **Clip** | — | — | — | — | **off, cleared on every refresh** | off | on if the WAV has slices | 256 samples/px at 0 |
| Slicer | `0x4e` Slice | `0x31` Slice Pos | — | — | off | off | on if slices | 256 samples/px |

With MultiSam on, the Sample/Granular refresh greys all four knobs and hides both brackets.

**Clip bind block** (`0x080A57FE`): four "unbind" calls `bl 0x080A7EE0` with `r0 = r1 = 0` and `r2` = knob, at
**`0x080A5806` (TL), `0x080A5812` (TR), `0x080A581E` (BL), `0x080A582A` (BR)**. That is the same call shape as Slicer's
`0x080A58F2` / `0x080A58FE`, which JOEBOX's `slice_bind_start` / `slice_bind_end` already replace. Binding id 0
gives a NULL label, type 0 and range 0..0, so the knob is blank. Then come `0x080A5836` `FUN_080B0984(view+0x47C8, 0)`
and `0x080A583C` `FUN_080A53A2(view)` (zoom refresh, below), and the block falls into the refresh switch.
`view+0x47C8` is a stepper object (`FUN_080B0984` is the stepper's set-count) sized per mode: Sample 4, or 2 with
Loop None; Slicer 1; Clip 0. Its consumer was not traced. The rebind block also clears every knob's greyed byte
(knob `+0x30`) first. So **all four knobs are unbound in Clip mode**, the bottom pair included.

**Clip refresh** (switch case 1): only **`0x080A5B0E` `bl 0x080C6E8C`** (`wave_slices(wave, view+0x2398)`). That
call copies the slice list only if it differs from the widget's own (`+0x184`), sets `+0x238` = (slice count ≠ 0) and
**clears `+0x239` and `+0x23A`**. It sets the dirty byte `+0x32` **only when the slice list changed**: clearing the
bracket flags alone does not mark the widget dirty. So stock never draws the loop bracket in Clip mode, anything that
sets it is undone by the next refresh, and a hook that re-asserts it must set `+0x32` itself when it changes anything.

**Marker fields of the waveform widget** (`wave = view+0x38`):

| field | meaning |
|---|---|
| `+0x228`, `+0x234` | Start and Length. The pink bracket spans `+0x228 .. +0x228 + +0x234`, colour byte `+0x258`. |
| `+0x22C`, `+0x230` | Loop Start and Loop End. The white bracket uses colour byte `+0x259`. |
| `+0x238` | show the slice markers (list at `+0x184`; selected slice `+0x25C` is highlighted) |
| `+0x239` | show the white loop bracket |
| `+0x23A` | show the pink start/length bracket |
| `+0x32` | dirty (redraw) |

The draw `FUN_080C6338` gates the white bracket on `+0x239` alone. After drawing it, it continues to the `+0x238`
slice test (`0x080C68EC` → `0x080C6514`), so the bracket and the slice markers can show together. The setters
have side effects:

- `FUN_080C6EDC(wave, ls, le, show)` writes the loop pair and `+0x239`, and **clears `+0x238`** on every path. Calling
  it in Clip mode would hide a Sync=Slice clip's slices, so a Clip hook should write `+0x22C/+0x230/+0x239` (and
  `+0x32` on change) directly.
- `FUN_080C6F14` sets `+0x23A` and also clears `+0x238`.

### Who sets the position knobs' step and range

`KNOB_STEP` is knob `+0x28C` (samples per stepper index, for type 0xD). The zoom is the float `view+0x1A0` (samples
per pixel), truncated to int.

| code | when it runs | `KNOB_STEP` | range (`FUN_080B09E4`) | value |
|---|---|---|---|---|
| `FUN_080A52C4(view, zoom)`, Sample/Granular branch | each bind, each zoom change | TL, TR, BL, BR = zoom | TL 0..len, TR 0..len, BL 0..LpEnd, BR LpStr..len (len = `view+0x2390`) | all four, after the range |
| `FUN_080A52C4`, Slicer branch | same | TR = zoom, then `FUN_080A5210` | — | — |
| `FUN_080A5210` (Slicer; called from `FUN_080A52C4`, the Slicer bind `0x080A58E6`, the Slicer refresh `0x080A5B64` and the `0x4E` handler `0x080A6C86`) | | TR = zoom (`0x080A5268`) | TR = the selected slice's bounds | TR |
| Sample/Granular refresh `0x080A598C` | **every refresh** | — | BL 0..LpEnd (`0x080A59F2`), BR LpStr..len (`0x080A5A1C`) | TL/TR via `FUN_080A7FE6`, BL/BR via `FUN_080B0790` |
| Clip (bind, refresh, zoom) | — | nothing | nothing | nothing |

`FUN_080A52C4` returns at once for Clip (and New Rec/New Multi). Its single caller is **`0x080A53B0`** inside
`FUN_080A53A2`, which runs from the three bind branches (`0x080A5772` Sample/Granular, `0x080A583C` Clip,
`0x080A591A` Slicer) and on msg `0xE5` (zoom changed, `FUN_080A66DC` → `0x080A67A8`). Msg `0xE5` does **not** run
the refresh. On bind, Clip mode calls `FUN_080C6F44(wave, len, 1)`, the Slicer setting: 256 samples/px, scrolled
to 0. Sample and Granular fit the whole file.

### Setting up a type-0xD (sample position) knob: step, then range, then value

- The binder `FUN_080A7EE0(id, value, knob)` resets the knob (type 0, `KNOB_STEP` 1, pending position `+0x290` =
  `0x7FFFFFFE` "none", freeze flag `+0x2D8` 0; it does **not** touch the id `+0x14`). It then sets the label, stores
  the id through vtable `+0x24` (`0x080A3316`, which only stores its argument to `+0x14`) and the type. For types 4 and 5 it
  sets up a list. Every other type, 6 included, gets the table range and then `knob_value`.
- For `0x91`/`0x92` the table says type 0xD, range **0..1000** (`Loop Start:`, `Loop End:`). After the binder alone
  with LpStr 50000: `+0x34` = 1000 (clamped), `+0x290` = 50000, stepper index 1000 of 1001, and the text reads
  `50000`, because the formatter prints the pending position. **One slow turn down then posts 999**, which would
  store Loop Start = 999. P3 must re-range and re-value before the first turn.
- The 0xD range code reads `KNOB_STEP` (`0x080B0ACE`):
  - start `+0x288` = trunc(min/step) × step;
  - n = q − trunc(min/step) + 1, with q = trunc(max/step).
  - When max is not a multiple of step, q grows by **step**, not by 1 (`add.lt r1,r1,r0` at `0x080B0AE4`).
  
  So the step must be in place before the range call. That is the order `FUN_080A52C4` and `FUN_080A5210` use. Done
  the other way round, the knob keeps the step-1 count: 80 001 positions for 0..80000 instead of 569.
- `knob_value` on a 0xD knob:
  - stores v as the pending position;
  - moves the stepper only if trunc((v − min)/step) falls outside [idx − 1, idx];
  - clamps `+0x34` into the range.
  
  The printed and posted value is the pending position if one is set. Otherwise it is idx × step + start, clamped to
  [min, max] (`FUN_080B03CC`). A turn clears the pending position.
- **Stock quirk: dead travel at the top.** The `+ step` above gives a 0xD knob up to step − 1 extra positions above
  max, all of which read max. Under Unicorn, range 0..80000 at 256 samples/px gives n = 569 (exact: 314). After an
  overshoot it takes 256 slow steps back before the value drops below 80000. Calling `FUN_080B0984(knob+0x270,
  exact n)` right after the range call cuts that to 2 steps. Stock Sample-mode position knobs use the same code, but
  this has not been seen on hardware (open point).

## 2. Would the generic forward store `0x91`/`0x92` for a Clip pad? Yes. Nothing filters by pad mode.

The path, with all of it run under Unicorn except the parent walk:

1. A numeric knob turn posts `0x3D {+0xC value, +0x10 id}`. A list knob (types 4–6) posts `0x3C {+0xC list index,
   +0x10 id}` instead (`0x080B0DB0`..`0x080B0DD4`). `FUN_080AED14` delivers either synchronously by walking the
   parent chain (`+0x2C`) and calling each parent's vtable `+0x30` until one returns 0.
2. The waveform view's handler `FUN_080A66DC`:
   - **`0x3D`**: id `0x31` (Slice Pos) is handled (`FUN_080A53B8`, hooked by JOEBOX at `0x080A6C8E`) and **swallowed**.
     Id `0x4E` (Slice) is handled (`view+0x47E4`, `FUN_080C6EC8`, `FUN_080A5210`) and **then forwarded too**
     (`0x080A6C8A` branches back to the forward). Every other id is re-posted as `0x6E {+8 pad cell = view+0x29C,
     +0xC id, +0x10 value}` at `0x080A6C6C`, already JOEBOX's `slice_forward` hook.
   - **`0x3C`**: forwarded the same way at **`0x080A6C10`**. When the id is `0x8b` (the mode list), the view first
     runs a side effect (`FUN_080BD24C(view+0x23FC, 1)`, two icons hidden).
   
   The pad page forwards the same way at `0x080A77DE` (handler `0x080A7468`; not a Ghidra function).
3. In the app (`FUN_080A1718`), case `0x6E` → `SetCellParam 0x0809FA50(app, cell, id, value, c)`. For a pad cell
   (bits 8..12 of the cell = 0, row < 4, col < 5) it takes the last branch and does three things:
   - overwrites the value with `FUN_08093ECC`, which silently ignores an id that is not in the store;
   - posts `0x39 {+8 cell code, +0xC id, +0x10 value}` to the engine (`FUN_0804C59C`);
   - posts `0x66` for the pad to the UI and sets dirty `app+0x8CC4`.

Every pad store holds `0x8f..0x92` from creation: the class-3 defaults in `FUN_08093F20` add them unconditionally,
next to `0x8b`. So the overwrite finds them in any mode.

**Engine side:** the class-B param-set `FUN_08067648` (message `0x39` of the class-B process `FUN_08067FA4`) has no
case for `0x8f`, `0x91` or `0x92`. It also returns at once for any id above `0xF4` except `0x15F` and `0x1DD`, so
`0x1c8..0x1ca` are ignored too. The Clip engine therefore ignores Loop Start/End today. Note that `0x90` (Length) is
consumed on class B (`FUN_08064A94`, A1's). Separately, the class-B process's own `case 0x91` is an *engine message
code*, not this param id: it writes `pad+0xB74 = value × 0.001`, and its sender was not traced.

**For P3:** BL/BR bound to the stock ids `0x91`/`0x92` in Clip mode need no forward code:

- the values are stored and saved with the preset;
- they are sent to the engine, where class B ignores them (the Clip Window reads them from the app store, plan
  step 2);
- they come back as a `0x66` refresh.

The same holds for our own registered rows (`0x1c9` Slip, `0x1ca` Loop Len) once the defaults hook has added them to
the store. Binding them on TL/TR needs no private id and no intercept. The stock binder `FUN_080A7EE0(id, value,
knob)` takes label, type and range from the table. A list row such as Loop Len forwards through `0x080A6C10`, not
`0x080A6C6C`, and is stored the same way.

## 3. Knob acceleration: numeric (type 1) rows do NOT accelerate

**Hardware.** The knobs are endless dual-wiper pots read by ADC. `FUN_08040724` (hardware object `0x24000170`)
works like this:

- averages 32 frames of 16 channels;
- keeps a ±10 LSB hysteresis per channel;
- takes each knob's delta from the wiper nearer mid-scale (`0x800`), with the sign from the other wiper's half;
- adds it to the knob's position at `0x24001A30 + 4k`;
- when that position moved, posts **one** `0x32 {+0xC knob index, +0x10 this call's delta in ADC LSB}` per knob
  into a 64-entry queue (`hw+0xC70`, index `hw+0x1274`).

Counts per revolution were **not measured**: about 8192 if each wiper sweeps full scale per half turn (inferred).
A single event is at least 11 counts because of the hysteresis.

**Everything runs in the GUI loop, one pass at a time.** One pass of `FUN_08043DEC` does, in order:

1. waits on a semaphore (`osSemaphoreAcquire(*(0x24001FAC+0x110), 1000)`, `FUN_08041B70`);
2. stores the tick count to **`0x2402EEE0`** (`FUN_0808B044`);
3. reads the touch panel;
4. calls the UI object's vtable `+8`. The object at `*(0x24002E6C)` is built by `FUN_0808BE4C` with vtable
   `0x080EAF4C`, so this is `FUN_0808B654`. It runs the app pass `FUN_080A2258` (`0x0808B664`, its only caller).
   - The app pass runs the knob scan (`0x080A2CD6`, its only caller).
   - It then drains the knob queue into `FUN_080A1718` (`0x080A2D28`), whose `0x32` case pushes the message into a
     128-entry UI ring at `app+0x30` (`0x080A1AB6`).
   - `FUN_0808B654` drains that ring to the views in the same pass (`0x0808B686`).
5. draws (`FUN_0808B2D0`).

So a knob event is handled in the pass that scanned it, with that pass's timestamp, and **one knob produces at most
one event per pass**. The semaphore is given by the LTDC interrupt handler `FUN_0807D126` on its register-reload flag
(`→ FUN_08041B60` at `0x0807D1FA`). The pass therefore probably runs once per display frame (inferred; the period
is unmeasured). `0x2402EEE0` is in 1 ms ticks: the SysTick reload is SystemCoreClock × `0x10624DD3` >> 38 =
clock / 1000.

**The Waveform view's own gate.** The view hands `0x32` to its knobs only while byte `view+0x3740` ≠ 0 (test at
`0x080A6E46`). Otherwise the turn goes to the popup list at `view+0x3710` (`FUN_080AED32`). Writes to the byte:

- set to 1 on msg `0xD3` and on several other paths (`0x080A6902`, `0x080A69D4`, `0x080A6BC8`; not traced);
- cleared right after the view opens that popup (`FUN_080B17DC` with `0xB5`/`0xB6`; `0x080A68BA`, `0x080A68E2`).

Both the view and the pad page read the knob index and the counts with `ldrsh` (16 bits, signed, in the message).
The stepper `FUN_080B0B74` sign-extends the int32 count into its i64 accumulator, so a hook may pass a scaled count
wider than 16 bits.

**The turn `FUN_080B0D54(knob, counts)`** switches on the knob type (`+0x31`; jump table at `0x080B0D68`):

| type (stock examples) | counts per step (`+0x278`, set by `FUN_080B0B08`) | accelerated | message and value posted | text |
|---|---|---|---|---|
| 1, 0x10 (Slice, BPM, Transpose) | 400 | **no** | `0x3D`, idx + start | `%ld` |
| 4, 5, 6 (on/off, lists) | 400 (6: 800) | no | `0x3C`, list index | name |
| 7 (Level, EQ Gain: milli-dB) | 80 | ×1..×6 | `0x3D`, idx×100 + start, ±500 dead zone | `±%d.%01d dB` |
| 8, 9, 0xA, 0xB (percent, bipolar percent, Hz, Q) | 40 | ×1..×6 | `0x3D`, idx + start, ±10 dead zone | `%d.%01d%%` etc. |
| 0xC (Pitch: milli-semitones) | 40 | ×1..×6 | `0x3D`, idx×10 + start, ±100 dead zone | `±%d.%02d sem` |
| 0xD (sample positions) | 400 | ×1..×6 | `0x3D`, see §1 | `%ld` |
| 0xE, 0xF (ms) | 40 | no | `0x3D`, idx×10 + start | `%ld ms` |

The list-row binder `FUN_080B1084` sets up both 5 and 6 as lists, and its list setup `FUN_080B0998` writes type 5,
so a type-6 row ends as type 5 with 800 counts per step. The view binder `FUN_080A7EE0` treats 6 as numeric.

**Accelerator.** A ring of 8 `{counts, time}` pairs sits at knob `+0x294`, with the write index at `+0x2D4`.
`FUN_080B0CC4` pushes and `FUN_080B0CE0` reads. The multiplier is

> **m = trunc(|Σ last 8 counts| / (t_newest − t_oldest))**, in counts per ms; 0 → 1, ≥ 6 → 6, zero span → 1.

The accelerated types feed `counts × m` to the stepper. A knob's 8 entries come from 8 different passes, so for a
physical turn the span is never 0 and m ≈ 8/7 × the turning speed in counts/ms, whatever the pass period. A zero
span (8 events with one timestamp) gives m = 1. Only a second producer of `0x32`, or a hook that turns the same knob
several times in one pass, could cause that.

**Stepper** (`+0x270`):

- `+0x270` i64 accumulated counts, `+0x278` counts per step, `+0x27C` index, `+0x280` steps, `+0x284` wrap;
- index = floor(acc / step), with a hysteresis of step/3 (10 when step < 30) against flipping back;
- acc is clamped to [0, steps × step − 1];
- setting a value parks acc mid-step.

The stock reset does not clear the accelerator ring, and type 1 never touches it.

**Who calls the turn.** `FUN_080B0D54` has 12 `bl` call sites: `0x080A6E70` (Waveform), `0x080AAAA2`,
`0x080ABCFC`, `0x080B11AC`, `0x080B1758`, `0x080B1EC0`, `0x080B1EDE`, `0x080B5E18`, `0x080B9A62` (list widget),
`0x080C178A`, `0x080C17C4`, `0x080C398C`. `0x080B5E18` is in `FUN_080B5C70`, next to the Pads-screen methods
`src/solo.c` uses (inferred: the Pads screen). The list widget `FUN_080B9A3C(list, counts)` turns the knob of the
selected row: rows are `0x328` bytes, built by `FUN_080B97D0`, with an embedded knob (vtable `0x080F0C88`) at row
`+0x38`; the first knob is at list `+0x120`. It has 10 call sites on 5 screens: `0x080A7958`/`0x080A7970` (pad
page), `0x080B7A90`/`0x080B7AA8`, `0x080B927C`/`0x080B9294`, `0x080BF86E`/`0x080BF882`, `0x080C5342`/`0x080C5356`.
On the pad page (`0x32` at `0x080A7932`), BL/BR turn the selected row and TL/TR (`FUN_080B9BA4`) move the selection.

**Measured** (80 equal events; total counts 880 / 2400 / 8000 / 16000):

| speed | 0.6 counts/ms | 3 | 20 | 100 |
|---|---|---|---|---|
| type 1: steps | 2 | 6 | 20 | 40 (= total / 400 exactly) |
| type 8: posted value (after the dead zone) | 12 | 160 | 1103 | 2215 |
| type 0xD: steps | 2 | 17 | 111 | 223 |

Multiplier for 8 equal events of c counts dt ms apart: (11, 20) → 1, (40, 20) → 2, (40, 10) → 4, (40, 5) → 6,
(400, 1) → 6, (40, 0) → 1.

**What it means for Slip (−3840..+3840 ticks):**

- **Type 1** gives about 20 ticks per revolution (inferred) with no acceleration. That is useless for this range.
- **Type 9**, the stock bipolar type (Pan, Mod Amount, Macro X/Y, −1000..1000), accelerates with no new code.
  - Speed: 1 tick per 40 counts slow, 6 per 40 counts fast; about 200 and 1200 ticks per revolution (inferred).
  - Dead zone: posted values are plain ticks, but raw −10..+10 all post 0, a centre detent. From a stored 0 (raw 0,
    parked mid-step) the first non-zero post comes after **11 slow steps, about 420–440 counts**, in either
    direction. The 0 plateau is 21 raw steps wide (about 840 counts), so going from +1 to −1 takes 22 steps (about
    880 counts).
  - Range: widened internally to `min−10..max+10`.
  - It cannot reach the plan's "fast = 60-tick steps"; ×6 is the cap.
- **Own curve** (meets the plan's 1 → 60): keep type 1 and scale the counts of the Slip knob before the stepper.
  - **Recommended site: `0x080B0DDE`**, the `bl FUN_080B0B74` of the type-1/0x10 turn path. The turn's jump table
    is its only way in. At that point r0 = knob + `0x270` and r1 = counts. One patched `bl` covers all 12 turn
    sites: Waveform, every list screen, the Pads screen if P4 binds Slip there. JOEBOX's `chord_knob` hooks a
    different `FUN_080B0B74` call (`0x080AE178`).
  - For the Slip id (and type 1): `FUN_080B0CC4(knob+0x294, counts, *(u32 *)0x2402EEE0)`, then
    `m = FUN_080B0CE0(knob+0x294)`, then pass `counts × 10 × K(m)` to `FUN_080B0B74`. For example K = {1, 2, 4, 10,
    30, 60}, with an optional snap to the 60-tick grid when m ≥ 5. The ring is free on a type-1 knob.
  - Alternative: wrap the two turn calls `0x080A6E70` (Waveform) and `0x080B9A62` (list widget). This misses the
    other ten sites (any other screen that turns a Slip knob gets plain 400-count steps).
  - Do **not** combine it with type 9: the stock ring would see the scaled counts and feed back.
  - K must be tuned on hardware once counts per revolution and the pass period are known.

## 4. The formatter `FUN_080B0528(knob)`

It switches on the knob type `+0x31` and `snprintf`s (`FUN_080C89F4`) into a zeroed 32-byte stack buffer. The format
strings are read from the image:

- types 1 and 0x10: `%ld`;
- type 7: `±%d.%01d dB`;
- types 8 and 9: `%d.%01d%%` (`-` prefix when negative);
- type 0xA: `%dHz` / `%d.%01dkHz`;
- type 0xB: `%.1f`;
- type 0xC: `±%d.%02d sem`;
- type 0xD: `%ld`;
- types 0xE and 0xF: `%ld ms`;
- any other type (0 included): nothing, so the buffer stays empty.

Then, **only if byte `+0x2D8` is 0**, it sets the value label (`FUN_080C3B98` on knob `+0x9C`), and it always
redraws with `FUN_080B0480`, which composes the name (`+0x75`) and value (`+0xCD`) into `+0xF4`. List types never
come here: `FUN_080B08F4` writes the list name.

The value it prints depends on the type:

- type 1: stepper idx + start (`+0x27C + +0x288`). It is **not** `+0x34`, because the type-1 turn path never
  updates `+0x34`.
- types 7–0xC: `FUN_080B0416(knob, +0x34)`, the dead zone removed.
- type 0xD: `FUN_080B03CC` (the pending position, else idx × step + start, clamped).

Call sites (all `bl`; no data words point at it):

- **`0x080B0746`**, in `FUN_080B0728` (set value). It is reached by `knob_value FUN_080B0790` for every type,
  including type 0 (`0x080B08E4`), and by the turn paths of types 7, 8–0xB and 0xC.
- **`0x080B0E18`**: type 1 / 0x10 turn.
- `0x080B0E68`: type 0xE / 0xF turn.
- `0x080B0EDA`: type 0xD turn.

**A freeze primitive exists.** `FUN_080B0404(knob, text)` sets the value label and `+0x2D8 = 1`. The formatter then
leaves the text alone: checked, a turn still posts `0x3D` but writes no text. The reset `FUN_080B04C8` and the
row binder `FUN_080B1084` clear the flag. Its one stock caller is at `0x080B9F6E`, in the list widget.

Hook candidates for a `+1.240` (beats.ticks, 960 ticks per beat) text on one id:

- **A (recommended).** Redirect `0x080B0746` and `0x080B0E18` to `knob_format(knob)`. It acts only if all three
  hold: `*(int *)(knob+0x14) == P_SLIP`, the type `knob[0x31]` is 1 or 9, and `knob[0x2D8] == 0`. Then it:
  1. takes `v` as the stock does for that type (type 1: `+0x27C + +0x288`; type 9: `FUN_080B0416(knob, +0x34)`);
  2. formats it with `FUN_080C89F4(buf, 32, "%c%d.%03d", v < 0 ? '-' : '+', |v| / 960, |v| % 960)`;
  3. calls `FUN_080C3B98(knob+0x9C, buf)` and `FUN_080B0480(knob)`.

  Otherwise it tail-calls `FUN_080B0528`. That is two patched `bl`, and it covers the pad page row and any Waveform
  knob bound to the id.
  - **Why the type check.** The stock reset leaves `+0x14` as it was and sets type 0, and `knob_value` on a type-0
    knob still reaches `0x080B0746`, where stock writes an empty text. An id-only hook would print beats.ticks
    there. Both binders store the id before typing and valuing, so on a bound knob the id is always current.
  - If the row ever became type 0xD/0xE/0xF, the other two sites would join.
  - **Display design point.** The stock `snprintf` handles `%c` and the `0` flag. `+1.280` is 1 beat + 280 ticks;
    `+0.959` is 959 ticks. Ticks run 0..959 in a 3-digit field, so the text reads like a decimal fraction: `+1.500`
    is 1.52 beats, not 1.5. That matches the plan's own examples (`+0.480` = half a beat), but users should be told.
- **B.** No formatter patch: call `FUN_080B0404` from the forward hook (`slice_forward` already sees the `0x6E`) and
  from the bind/refresh hooks. It is fragile: every reset or rebind shows the stock `%ld` until our next write.
- **C.** An entry patch of `FUN_080B0528`. It needs the displaced prologue re-run, and JOEBOX does not use that pattern.

## 5. The corner labels: the knob's line, its colour, its draw (37.3.1)

Static reads of the 3.1.9 image and the decompile, checked under Unicorn (`test_clipwin.py` §12b); the palette read
from the unit at `0x24000000` on 2026-10-16 (37.3.0d), which matches the image's `.data` load image (`0x080F1D80`).

- **A text label** (vtable `0x080F17A4`, 14 entries, `0x58` bytes): `+0x04` x, y, w, h (i32); `+0x31` the text (31
  chars, `FUN_080C3B98` sets it and marks `+0x55` or `+0x56` dirty by `+0x52`); `+0x51` alignment (1 left, 2 centre,
  3 right); `+0x52` which pass draws it (the draw context's byte 0 or byte 1); `+0x53` the colour, a palette index;
  `+0x54` the size: `0x10` is the 6 × 8 font doubled (12 × 16 px a glyph), anything else the same font at 1 × (a
  second path, `FUN_080C3BEC`). There is no other size and no bold. `[1]` `FUN_080C3D2C(label, ctx)` draws it whole,
  `[2]` `FUN_080C3FC6(label, ctx, rect)` clipped to a dirty rectangle (`FUN_0808F0A0`: the fast path only when the box
  lies wholly in it, else every pixel tested). The text draw `FUN_0808EE54` cuts the text to the box's width, never
  its height; each glyph is `FUN_0808ED4C`, each lit font pixel four calls of `FUN_0808F524(layer, x, y, colour)`.
  The draw context is two pass bytes and, at `+4`, the layer: `{u32 pixels, u16 w, u16 h, u8 format (5: 8-bit
  indexed), u8 rotation (1: rows flipped, y counts up)}`.
- **The font** (`.data` `0x240000D0` → `{0x080ECDC4, 6, 8}`): column 0 is lit in 279 places over the 96 glyphs,
  column 5 in 3; row 7 (descenders) in 15. Doubled, a glyph fills `[x, x + 12) × [y, y + 16)` of a box 20 px high, so a
  pixel of edge around it leaves the box on the left and below unless the box is inset.
- **The palette** (ARGB): 2, 8 and 13 `#141414` (the background), 3 `#FCFCFC`, 5, 7, 10, 27, 29 and 31 `#09D7F5` (the
  waveform's cyan), 9 `#666666`, 14 `#000000`, 15 `#FFFFFF`; 34 entries, 0 transparent.
- **The knob** (vtable `0x080F0C88`) has three labels: its name `+0x44`, its value `+0x9C`, its line `+0xF4` (`"%s
  %s"`, `FUN_080B0480`). Its set-rect `FUN_080AFEB2` (vtable `[8]`) lays them out by `+0x32`: 0 the name and the value
  as two children; 1..4 the line alone, as its only child, at the top-left, bottom-left, top-right or bottom-right of
  its rectangle (y up), 20 px high, left-aligned from x + 6 or right-aligned to the right edge. `FUN_080B02E6(knob, c)`
  sets the colour of all three; `FUN_080B02F6(knob, b)` their `+0x52`.
- **The Waveform view's four** (`FUN_080A5B90`, once): TL `+0x670` layout 1 in (0, 74, 157, 73), BL `+0x950` layout 2
  in (0, 0, 157, 73), TR `+0xC30` layout 3 in (158, 74, 157, 73), BR `+0xF10` layout 4 in (158, 0, 157, 73); then
  `FUN_080B02E6(knob, 9)` for each at `0x080A660A`, `0x080A6612`, `0x080A661A`, `0x080A6622` (the hook sites). The
  lines' boxes: (6, 127, 151, 20), (6, 0, 151, 20), (158, 127, 151, 20), (158, 0, 151, 20). Nothing sets a label's
  vtable after its constructor, so a vtable given there holds in every pad mode.

## Hook sites for P3 (Clip-mode Waveform knobs)

None of these is patched by JOEBOX today (each address grepped in `patches/` and `src/`), except `0x080A6C6C`.
JOEBOX's nearby `0x080A6C8E` (`slice_pos_moved`, the `0x31` path) is not a proposed site.

| site | stock call | runs | use |
|---|---|---|---|
| `0x080A5806` / `0x080A5812` / `0x080A581E` / `0x080A582A` | `FUN_080A7EE0(0, 0, knob)` TL / TR / BL / BR | Clip bind block | bind BL `0x91`, BR `0x92` (stock ids, type 0xD, as in Sample mode) and TL/TR = Slip / Loop Len via the stock binder. On its own this leaves the 0xD knobs at the table range 0..1000 with the value only pending (§1); the two hooks below run later in the same setup call and must fix it before any turn. |
| `0x080A53B0` | `FUN_080A52C4(view, zoom)` | each bind (all modes) and each zoom change `0xE5`; no refresh follows `0xE5` | call stock, then for Clip on each bound 0xD knob: `KNOB_STEP` = zoom, **then** range (BL 0..LpEnd, BR LpStr..len), **then** value. Optionally `FUN_080B0984(knob+0x270, exact n)` against the top-end dead travel. |
| `0x080A5B0E` | `FUN_080C6E8C(wave, slices)` | every Clip refresh (each `0x66`, each setup) | call stock, then do what the Sample refresh does: range + value for BL/BR, re-value TL/TR from the view store (`FUN_080A7FE6(id, value, knob)`, which handles lists too). Re-assert the bracket (`+0x22C/+0x230/+0x239`, keep `+0x238`) when the region is the loop, and set `+0x32` when anything changed. |
| `0x080A6C6C` (JOEBOX `slice_forward`), `0x080A6C10` | `FUN_080AED14` | numeric (`0x3D`) / list (`0x3C`) knob changes | nothing needed for `0x91/0x92` or registered rows |
| `0x080B0746`, `0x080B0E18` | `FUN_080B0528` | every value format | Slip text (check id **and** type) |
| `0x080B0DDE` | `FUN_080B0B74` (type-1/0x10 turn) | every type-1 turn on every screen | own Slip acceleration (recommended); alternative `0x080A6E70` + `0x080B9A62` |

## Open points

- **Counts per revolution and the GUI pass period.** A USB peek (dev build, `src/usbdev.c`) settles both:
  - read `0x24001A30 + 4k` before and after one full turn of knob k;
  - read `0x2402EEE0` in a tight loop: the step between distinct values is the pass period.
  
  This turns the per-revolution figures above from inferred to measured, and K can then be tuned.
- **The top-end dead travel on hardware.** In Sample mode, zoomed in, turn Loop End past the end of the file, then
  back. If the value sticks at the end for many steps, the quirk in §1 is real on the device and P3 should apply
  the exact-n call.
- **Type 9 for Slip: save/load and modulation.** JOEBOX's type-8 rows (`TYPE_PCT`, 0..1000) already save and load,
  and stock type-9 rows hold negative values (Pan), so a negative type-9 Slip should round-trip. Whether the MOD page
  scales a modulation amount by the destination's type was not looked at.
- **The `view+0x47C8` stepper** (Clip 0). If touch-dragging the loop markers in Clip mode is wanted, its consumer is
  where to look.
- **Other `0x32` producers.** Only the knob scan was found to post `0x32`, but no image-wide search for other
  producers was done. A second producer is the only way the "zero span → m = 1" case could occur.

## Verification

An independent round challenged the note. Every disputed point was re-checked here (scripts in
`/srv/dev/firmware/re-scratch/a3/r2/`, experiments E1–E9):

| point | first version said | outcome | settled by |
|---|---|---|---|
| Who sets step and range of the position knobs | only `FUN_080A52C4` | **wrong, corrected** (§1 table): the Sample/Granular refresh re-ranges and re-values BL/BR on every refresh, and `FUN_080A5210` writes TR's step for Slicer | listing of `0x080A598C..0x080A5A2C` and `FUN_080A5210`; refresh `tbh` decoded from the image bytes; listing grep of every store to `+0x8FC/+0xEBC/+0xBDC/+0x119C/+0x28C`; `findbl.py` for all callers |
| Order for type-0xD knobs | "set range and step yourself" | **confirmed and sharpened**: step → range → value. The verifier's range formula was off in one detail: q grows by step, not 1. That gives the dead-travel quirk. | Unicorn E1 (binder alone: `+0x34` 1000, pending 50000, text `50000`), E1d (one turn down posts 999), E1b/E1c (both orders), E8 (n = 357 for 0..25601 at step 256) |
| `view+0x3740` gate, `ldrsh`, i64 sign extension | not mentioned | **confirmed** | listing `0x080A6E42..0x080A6E86` and the `0x3740` writes; Unicorn E7 (+40000 → 100 steps, −80000 → −100) |
| `0x4E` forwarded, `0x3C` forwarded | "special-cases 0x4E and 0x31" | **corrected**: only `0x31` is swallowed; lists forward at `0x080A6C10` | listing of `FUN_080A66DC` dispatch and `0x080A6BE8..0x080A6C8E`; turn path `0x080B0DB0` posts `0x3C` |
| Type-9 detent size | "about 840 counts before the value leaves 0" | **wrong, corrected**: 11 steps / 420–440 counts from 0; 22 steps from +1 to −1 | Unicorn E2 (registered type-9 Slip, bound by the real binder; acc parked 20 counts into its step) |
| Burst blind spot (≥ 8 events of one knob in one GUI pass → m = 1) | not mentioned | **the mechanism is real but cannot come from the knobs**: the scan runs inside the GUI pass and posts ≤ 1 event per knob per pass. The pass period stays open. | Unicorn E3 (8 × 200 counts at one stamp → m 1; 2 ms apart → m 6); static chain `FUN_08043DEC` → vtable `0x080EAF4C`+8 → `FUN_0808B654` → `FUN_080A2258` → scan, and the scan's single post per knob |
| Turn call sites | two sites named | **confirmed**: 12 sites of `FUN_080B0D54`, 10 of `FUN_080B9A3C`. That led to the single-site `0x080B0DDE` recommendation. | `findbl.py`; Unicorn E9: a code hook at `0x080B0DDE` scaling r1 was hit on every event through both `FUN_080B9A3C` and `FUN_080B0D54` (slow: 11 ticks for 440 counts; fast: clamps at 3840) |
| `knob_format` keyed on the id alone | id + freeze flag | **corrected**: check type 1/9 too | Unicorn E5 (reset knob with stale id `0x1C9` → `knob_value` writes `''`); reset listing (no write to `+0x14`) |
| `snprintf` with `%c%d.%03d` | assumed | **confirmed** | Unicorn E6: `+1.280`, `-0.030`, `+0.000`, `+0.959`, `+4.000`, `-4.000` |
| Dirty flag and slices with the bracket | "keep `+0x238`" | **confirmed, with the dirty caveat** | Unicorn E4 (same list → dirty 0, changed list → dirty 1, flags cleared either way); draw listing `0x080C68EC` → `0x080C6514` |
| The two binders | not compared | **confirmed** (§3), plus `FUN_080B0998` forcing type 5 | listings of `FUN_080A7EE0`, `FUN_080B1084`, `FUN_080B0998`; row ctor `FUN_080B97D0` |

The verifiers confirmed everything else independently. That covers the Clip bind calls, the refresh clearing, the
`FUN_080C6EDC` side effect, the forward and engine path, the type-1 turn figures, the accelerator formula, the
type-9 range widening, the formatter table and call sites, the freeze flag, the knob scan and the JOEBOX grep.

## How this was checked

Unicorn on the stock image only. The harness is `stock.py` plus one script per check in
`/srv/dev/firmware/re-scratch/a3/`:

- **Param table:** the registrar `FUN_0808C158` run whole (allocator stubbed) to get the real table: mode names,
  types, ranges, the `0x8b` list.
- **The setup:** `FUN_080A54A0` run whole for Sample, Clip, Slicer and Granular.
  - Real: the binder, the knob widget, the wave marker setters, the store.
  - Stubbed: the app's store copy and file lookup, labels and icons, `FUN_080A53A2`, `FUN_080A5210`, the mode list
    widget.
  - Recorded: binds, knob types and ranges, wave flags. A Clip refresh with `+0x239` forced to 1 came back 0.
- **The forward:** `FUN_080A66DC` and `SetCellParam 0x0809FA50` run with a pad store in mode 1, 0 and 2. In all
  three, 0x91 and 0x92 were stored, posted to the engine (`0x39`, cell code `0x102`) and posted to the UI (`0x66`).
- **The engine param-set:** `FUN_08067648` run with ids `0x8f`, `0x91`, `0x92` and `0x1c8..0x1ca`: no write to the
  pad. The control `0x8d` writes `pad+0x1F4`.
- **The turn:** `FUN_080B0D54` on a widget bound by the real `FUN_080A7EE0` to id `0x1c9`, registered by the real
  `fw_register_num` as type 1, 8 or 0xD. Real stepper, accelerator, dead-zone map and formatter; the GUI time
  written before each event.
- **The accelerator:** `FUN_080B0CC4` / `FUN_080B0CE0` alone, for the multiplier table.
- **Freeze:** `FUN_080B0404`, then a turn, then a reset.

Round 2, in `r2/`:

- `recheck.py`: E1 binder and order for type 0xD, E2 type-9 detent, E3 burst, E5 type-0 knob, E6 `snprintf`,
  E7 wide counts, E8 range count;
- `wave.py`: E4 `FUN_080C6E8C` flags and dirty, E1d one turn after the binder alone;
- `quirk.py`: dead travel with and without the exact-n call;
- `cps.py`: counts per step for every type;
- `ownaccel.py`: E9 the single-site acceleration hook through both paths.

Static reads:

- the draw's flag gating (`FUN_080C6338`);
- `FUN_080A52C4` and `FUN_080A5210`, and the refresh cases;
- the range, value and pending-position code (`FUN_080B09E4`, `FUN_080B0790`, `FUN_080B03CC`);
- the binders;
- the knob scan `FUN_08040724` and the GUI-loop chain down to it;
- the LTDC handler that paces the loop;
- the GUI time source and the SysTick reload constant;
- the pad page handlers `0x080A789C` / `0x080A7468` (capstone, since Ghidra has no function there);
- the jump tables and format strings, read from the image.

Call sites come from `findbl.py`, a scan of every 32-bit `bl` in the image.
