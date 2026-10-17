# A1 — the class-B (Clip / Slicer) pad object and its voices

Stock 3.1.9. Found 2026-10-15 (loop turn, blackbox#t-003), revised the same day after independent verification (see
"Verification"). Offsets are from the pad object unless stated. ✓ = checked by running the stock code under Unicorn;
everything else is a static read, marked *inferred* when a single read.

## The short answers

1. **Param-set** is `FUN_08067648(pad, clock, msg, ctx)`, reached from the pad process for queue message type
   `0x39` (id at msg +0xc, value at +0x10). Loop Mode → `+0x1f4` (byte). Beat Count → `+0xb80` (int beats, 0 =
   Auto). Quant Size → `+0x218` (int64 ticks). Sync → `+0x220` (int64 ticks). Quant and Sync rerun the pad's
   timing recompute `FUN_08064a94` and then re-grid the playing segments ✓. Param `0x90` reruns the recompute
   alone ✓. Beat Count, Pitch and the Slicer quant `0xf3` do not recompute ✓.
2. **Voice start** is `FUN_08065908(pad, clock, offset, note, [sp] velocity, [sp+4] ctx)`. Its result is void, and
   **s0 is not an argument** ✓. All three call sites are **launches**, one per kind of trigger message ✓. Every
   later step, and the wrap, is a new segment started by the layer render `0x080667b8` through `FUN_08065550` at
   **`0x08066CF2`**.
3. **The position is per segment, not per voice:** an int64 whole-frame position at seg `+0x08` plus a float
   fraction at seg `+0x1c` ✓. The playback rate is the source rate (× root/pitch). **Sync never changes the rate**:
   it only decides when each step's segment starts, and from which frame.
4. **The launch tick** comes from `FUN_0806a34c(out, clock, &pad[0x218])`, called by the voice start at
   `0x08065F1E`: the next Quant boundary, or "now" if the last boundary passed ≤ 384 samples ago ✓. The tick that
   actually sounded is stored at **layer `+0x140`** (int64) ✓. Stock writes it and never reads it. It is **not** a
   phase anchor: steps and wraps snap to absolute grids counted from tick 0 (see "The phase against the clock").
5. **Clock convention: settled, no stock-internal mismatch.** Launch and step scheduling agree under any convention
   ✓, and the pads see `clock[0]` = the first sample of the block being rendered, as `duck_block` does (A2 ran the
   control tick; A6 measured each stage). `clipwin_tick` needs no one-block correction.

## Objects

| object | where | size | notes |
|---|---|---|---|
| pad (class B, type byte `+0x04` = `0x4c` 'L') | built by the engine cell factory `FUN_080525f0`: alloc 3000 bytes, ctor `FUN_080640d0`, then `+0xb79 = 1` (`0x08052AB2`) | `0xbb8` | vtable `0x080D0890`; block method (vtable `+0xc`) `0x08068C64` calls the process `FUN_08067fa4(pad, ctx)` |
| segment ×4 | `pad + 0x30 + k*0x70`, k = 0..3 | `0x70` | **one pool for the pad, shared by both layers**. `FUN_08065290` / `FUN_08065550` take the first free one, or return −1 if all four are busy |
| layer (voice) ×2 | `pad + 0x260 + L*0x410` | `0x410` | the voice object (`fp` in the segment reader), each with its own envelope, filter and modulation copies |

The two layers are **two voices**, not a handover pair. In Poly mode a new launch takes a free layer. If both are
busy, it steals the one with the older start sample (layer `+0xe0`) ✓. In Mono mode (`+0x1f7`) the playing layers
get a quantized note-off first. The step **crossfade happens inside one layer, between its segments**: the next
segment starts 256 samples before the current one ends ✓.

The pad's message queue is at `ctx + 4 + 0x604 × ((id>>8 & 0xff) + 4×(id & 0xff) + 16×(id>>16) + 2)` (`FUN_0805F2C8`;
ids `0x400` / `0x401` map to slots 0 / 1). In JOEBOX's naming (byte 1 = row, byte 0 = col) that is **col×4 + row**,
the transpose of `duck_thunk.S`'s row×4+col bit index. Call `FUN_0805F2C8` rather than re-deriving it.

### Pad fields

| off | type | meaning | written by |
|---|---|---|---|
| `+0x18` | u32 | cell id (bank<<16 \| row<<8 \| col, JOEBOX naming) | factory |
| `+0x24` | ptr | sample source | resolved through `FUN_08055054` at the top of the recompute (*inferred*) |
| `+0x28` | u8 | has-voice; cleared by the process when no layer is left (then posts `0x1e` / `0x4c`) | voice start |
| `+0x29` | u8 | Clip/Slicer mode active (Pad Mode `0x8b` ∈ {1, 2}) | param `0x8b`, msg `0x40` |
| `+0x1f0` | f32 | source rate / 48000 (1.0 if unknown); **no pitch term** | recompute ✓ |
| `+0x1f4` | u8 | **Loop Mode** (`0x8d`) | param ✓ |
| `+0x1f5` | u8 | synced = Quant ≠ 0 **and** Sync ≠ 0 (`0xf3` does not update it) | `0x47` / `0x94` ✓ |
| `+0x1f6`, `+0x200`, `+0x228` | u8, f32, i64 | previous synced flag / frames-per-step / sync ticks, saved before a Quant or Sync change | `0x47` / `0x94` |
| `+0x1f7` | u8 | Mono (`0x9f` Mono Mode = Mono, or `0xa0` Poly Mode = Mono) | param |
| `+0x1f8` | u8 | **Launch Mode + 1** (`0x93`: 1 Trigger, 2 Gate, 3 Toggle) | param ✓ |
| `+0x1fc` | f32 | **source frames per step** = file length / n | recompute ✓ |
| `+0x204` | f32 | **output samples per step**: samples(clip ticks) / n when n > 1, else round(len / rate) | recompute ✓ |
| `+0x208` | i64 | **ticks per step** = clip / n (integer division) | recompute ✓ |
| `+0x210` | u32 | n, the number of steps | recompute ✓ |
| `+0x218` | i64 | **launch quantum, ticks** (Clip Quant Size `0x47`, or Slicer `0xf3` when `+0x254`) | param ✓ |
| `+0x220` | i64 | **sync step, ticks** (`0x94`; `Slice` = sentinel `0xF0000` = 1024 beats) | param ✓ |
| `+0x230` | i64 | wrap grid = min(quant, clip ticks) | recompute ✓ |
| `+0x238` / `+0x23c` | u32 | 0 / file length. Written by the ctor and the recompute; no load of either was found | recompute ✓ |
| `+0x240` / `+0x244` | u32 | step count (= n if synced, else 1) / first step (always 0) | recompute ✓ |
| `+0x24c` / `+0x250` | ptr / u32 | **slice table** (frames, sorted, ≤ 128) / slice count | queue msg `0x3c` ✓ (below) |
| `+0x254` / `+0x255` / `+0x256` | u8 | Slicer / PlayThru (`0xf2`) / Slicer Sync (`0xf4`) | param ✓ |
| `+0x258` | f32 | clip_beats × 60 × 48000 / len: the file's tempo **as if its frames were 48 kHz samples** (= the file BPM only for a 48 kHz file; 130.6 for a 120 BPM file at 44.1 kHz) | recompute ✓ |
| `+0x25c` | u32 | MIDI In channel (`0x6a`) | param |
| `+0xa80` | i32 | Pitch (`0x5c`), milli-semitones (no recompute) | param ✓ |
| `+0xb78` | u8 | muted (param `100` / `0x15f`) | param |
| `+0xb79` | u8 | launch quantization enabled (the ctor zeroes it, the factory sets 1; no other store found) | factory |
| `+0xb7c` | u32 | Root Note (`0xd0`; 0 = None, which means key 60 is the reference) | param ✓ |
| `+0xb80` | u32 | **Beat Count** (`0xd2`; 0 = Auto; no recompute) | param ✓ |
| `+0xba1` | u8 | Attack (`0x3c`) == 0: step-0 segments start without a fade-in (`0x08065798`) ✓. The same param writes value/1000 to layer `+0x298`. 1 on both pads of a real preset (Gate 3b; README open point 7); the Clip Window gives a step 0 that starts inside the audio its fade-in back (37.3.3, `cw_slot`) | param ✓ |
| `+0xba8` / `+0xbb0` | i64 / u8 | clip ticks last resolved / changed flag; the process then posts msg `0x8d` {cell id, clip ticks} to the app queue `ctx + 0x15238` ✓ | recompute ✓ |

### The recompute `FUN_08064a94(pad, clock)` ✓

```
len_a     = fw_src_len(src) at 0x08064B2C        len_b = fw_src_len(src) at 0x08064C5A   (the same value in stock)
Auto      : t = round(f32(len_a/src_rate × BPM/60) × 960); b = round(t/960)
            g = 960 if b < 2 else 960 × (largest power of 2 ≤ b);  clip = multiple of g nearest t (tie → up)
Beat Count: clip = beats × 960
synced    = quant ≠ 0 and sync ≠ 0;  n = clip / sync (integer) if synced and that is > 1, else 1
+0x208 = clip / n      +0x210 = n      +0x230 = min(quant, clip)      +0x240 = n if synced else 1
+0x1fc = len_a / n
+0x204 = samples(clip at the current BPM) / n           if n > 1
       = round(len_a / max(0.01, 2^(pitch/12000) × src_rate/48000))   if n = 1 (unsynced, Slice, or clip ≤ sync)
+0x23c = len_b         +0x258 = (clip/960) × 60 × 48000 / len_b
```

Auto is **engine-side** and depends on the **current BPM**; Pitch and Root Note do not enter it. Because n is an
integer division, a clip that is not a multiple of Sync gets steps that are not Sync long (7 beats with Sync 1/2:
n = 3, 2240 ticks a step) ✓.

**What reruns it:** every launch (`0x08068312`, `0x0806838A`, `0x08068632`, `0x080686A8`), every loop wrap
(`0x08066E9E` unsynced, `0x08066FAC` synced), a Quant or Sync change (`0x080679CE`), **param `0x90`** (its case
`0x08067B30` tail-calls the recompute with `b.w` at `0x08067B38`, which a BL scan misses) ✓, and queue msg `0x6f`,
but only while the pad has a voice (`0x080683FE`). Beat Count alone takes effect at the next launch or wrap, or at once
if `0x90` follows it ✓ (Beat Count 8, then `0x90` → clip 7680). Pitch (`0x5c`, a plain store at `0x08067A64`) and
`0xf3` (`0x08067CFA`) never recompute.

### Param-set side effects worth knowing

- `0x8d` Loop On while a voice plays clears the "ending" byte (layer `+0x09`) on both active layers, so a one-shot
  that was finishing keeps looping ✓.
- `0x47` / `0x94` while playing: after the recompute, every playing segment is **re-indexed** from its own position
  (new step = position / new `+0x1fc`, new countdown), and segments still waiting on their delay are marked done, so
  they get rescheduled ✓. Re-sending the same value changes nothing audible ✓. Sync 1/4 → 1/2 inside step 1: the
  playing segment becomes step 0, step 1 lands on the new grid (tick 13440), the wrap stays on the bar ✓.
- `0x90` reruns the recompute **without** the re-index: playing segments keep their step index against the new
  `+0x1fc` / `+0x204` (the missing re-index is static; the recompute ran ✓).
- `0x47` is ignored in Slicer mode; there `0xf3` (14-entry table `0x080ECB2C`) writes `+0x218` instead ✓.

## Segment (`pad + 0x30 + k*0x70`)

| off | type | meaning |
|---|---|---|
| `+0x00` / `+0x01` | u8 | active / **done** (set by the fade stage machine `FUN_08066164` at `0x08066248` when countdown, fade-out and tail are all 0) ✓ |
| `+0x08` | i64 | **position, whole source frames** (`+= used` each block, 64-bit) ✓ |
| `+0x10` | i64 | end frame (0 = none; the last non-slice step gets `len − 1`) |
| `+0x18` | f32 | rate = `+0x1f0` × root-note transposition (`FUN_0805f6b8(note − root)`) |
| `+0x1c` | f32 | **fraction** carried by the kernel ✓ |
| `+0x20` | i32 | start delay in samples, used up before any read |
| `+0x24` / `+0x28` / `+0x2c` / `+0x30` | i32 | fade-in left (256) / countdown to fade-out / fade-out left (256) / silent tail |
| `+0x34` | u32 | **step index** (or slice) |
| `+0x38` | i32 | note |
| `+0x3c` | u8 | first-block flag: on the block the segment starts, the reader posts `0x1d` and stores the tick at layer `+0x140` |

**Segment reader** `FUN_08066454(pad, layer, seg, -, first, …, &pos_out, &changed, ctx)`. At the clip-read call
`0x08066622`: `r5` = pad, `r4` = **segment**, `fp` = layer, `r10` = frames **minus any delay consumed this block**;
the output is mixed later at that offset. The position goes in **r2:r3 as an int64**; `[sp+8]` = &frac = seg + 0x1c.
The effective rate is `FUN_0805f728(pitch/12000 + layer pitch mod (layer +0x94)) × seg.rate`, clamped to ≤ 8.0
(`vselgt` at `0x08066618`) ✓. The clip reader is called only while the fade-out counter is > 0. The reader returns
void. Its outputs: the position and fraction advanced; `*changed` = 1 if the end-based countdown moved by more than 4
samples this block (the render then drops that layer's not-yet-started segments, so they get rescheduled); and, for
the first layer, the position written to `*pos_out` (the render posts it as UI msg `0x4a`, in per-mille of the file).

**The stock clip reader `0x080662E4`** returns 0 (nothing mixed) when `pos > len + 0xff` (`0x080662F6`), evaluated
on whatever position it is passed. At rate 1 with fraction 0 it copies straight to the output. Otherwise it fetches
`min(int(n × rate) + 8, 1024)` **contiguous** source frames into a fixed work buffer, `ctx + 0x15850`. The render
passes that buffer from the literal at `0x08066A78`, and the engine ctor sizes it to 1024 frames (`0x08051566`; the
input buffers on either side get 128). It then runs the four-point kernel `FUN_080603EC` ✓.

**JOEBOX already owns this call:** `patches/filter.py` redirects `0x08066622` to `clip_read_b` (`src/filter_thunk.S`),
which puts the voice's filter object in r1 and branches to `clip_read` (`src/filter.c`). Anything else at this site
has to chain inside `clip_read`.

## Layer (`pad + 0x260 + L*0x410`)

| off | meaning |
|---|---|
| `+0x00` / `+0x04` / `+0x08` / `+0x09` | active / note / started / **ending** (no new segment will be scheduled) |
| `+0x0c`, `+0x58`, `+0x94` | modulated params read in the segment reader (pan-like, level, pitch) |
| `+0xc8..+0xd4`, `+0xd8` | segment indices (−1 = none), count |
| `+0xe0` | i64 clock sample counter at the voice start (steal-the-older test) |
| `+0xe8` / `+0xec` | Slicer only: current slice / a 512-sample window after a no-key launch (set to `0x200` at `0x08065F7E`, only when `+0x254` is set). While it is > 0 the render re-picks the slice from `FUN_080649e0` and restarts it through `FUN_08065550` at `0x08066B9A` (static; the only other store is the decrement at `0x08066BC2`) |
| `+0x130` / `+0x134` | quantized-stop countdown in samples / pending (from `FUN_0806475c`) |
| `+0x138` | envelope hold-off = the launch delay |
| `+0x13c` | velocity (stored raw; the call sites clamp it) |
| `+0x140` | **i64 tick at which the launch segment actually started** ✓ (stock writes it at `0x08066748`; no read found) |
| `+0x148` | **armed**: launched while the transport was stopped. The render skips the layer until msg `0x57` (transport start, posted by `FUN_08051d80` on MIDI `0xFA`/`0xFB` and by `FUN_08051eb8`) clears it ✓ |
| `+0x14c`, `+0x258` | filter object (JOEBOX `filter_voice_b`), envelope |
| `+0x298` | f32 Attack / 1000 (param `0x3c`; the meaning is *inferred*) |

## Voice start and its three sites ✓

`FUN_08065908(r0 pad, r1 clock, r2 offset, r3 note, [sp] velocity, [sp+4] ctx)`:

- `clock` is `ctx[0]`, the engine (A4). `offset` is message `+4`, the event's sample offset.
- `velocity` is message `+0x10`, clamped at the call sites by `FUN_080607e0` (≤ 0 → 100, > 127 → 128). For type `5`
  the raw word is passed.
- `note` 0 means no transposition. Notes ≥ 36 pick a slice on a Slicer pad.

The pad process dispatches its queue through the jump table at `0x08068018` (type − 2, 0x90 entries), then runs the
render for both layers (`bl` at `0x0806887C`):

| site | message types (handler) | note passed | trigger, as far as known |
|---|---|---|---|
| **`0x080683AE`** | `2` (`0x08068348`); in Toggle mode a second `2` on the same note stops instead | msg note | note-on with a key: the MIDI handler (`0x0804F884`) and RecToPlay (`0x08062DA2`) post it |
| **`0x08068656`** | `0x11` (`0x080686D2`), `0x8b` (`0x080683B4`: fades both layers out first = retrigger), `0x1a` (`0x080685F2`: start if idle, stop if playing = toggle), `5` (`0x080682CA`: only if MIDI In set and Quant None) | msg note (`0x1a`: 0) | `0x11` is posted at `0x0805CF62`; `0x8b`/`0x8c` on/off at `0x0805CEA0` (an event loop, likely the sequencer); `0x1a` sender not found |
| **`0x080686CC`** | `0x18` (`0x08068674`) | 0 | the MIDI handler at `0x0804F7EC` (paired with `0x19` stop at `0x0804F9AC`): a no-key pad trigger, probably Global-In notes |

Every site first runs the recompute and checks the source (`FUN_0806371c`). `duck_voice_start_b` already covers all
three sites and passes every argument through.

What the voice start does on a Clip pad (120 BPM, 25 samples/tick, Quant 1 bar):

1. **Quantized and playing** (`+0xb79`, `+0x218` ≠ 0, clock `+0x38`): `t = FUN_0806a34c(clock, quant)`: the next
   multiple of quant above the current tick, unless the previous multiple is ≤ `0x180` samples behind `clock[0]`, in
   which case `t` = the current tick, clock `+0x30` (`t < 0` → 0). Then `delay = FUN_08069c64(clock, t)` =
   samples(t) − `clock[0]`. If delay ≤ 0 the launch starts at once (delay 0, posts `0x1d`); otherwise it waits
   (posts `0x1b` queued). The event offset is **dropped** on both quantized paths ✓.
   Checks ✓: 1000 samples past a bar → next bar (delay 95 000); 300 past → now (`+0x140` = 11532); 384 past → now;
   385 past → next bar; 300 before → the bar; Quant 1 beat → the next beat. Because the current tick is *rounded*
   from samples, "now" can be up to half a tick ahead: 13 past the bar → current tick 11521, delay 12, `0x1b`, first
   sound 25 samples after the bar ✓.
2. **Quantized and stopped:** delay 1, layer `+0x148` = 1 (armed), posts `0x1b` ✓.
3. **Quant None:** delay = `offset` ✓, posts `0x1d`.
4. Choose a layer, then `FUN_08065550(pad, layer, delay, step 0, clock, note, first=1)` at `0x08065A9A`: frame 0
   always. The first segment gets no fade-in: its 256 are added to the countdown, so countdown = `+0x204` ✓.

## Steps, wraps and their timing (✓ by running the real process and render)

When a layer holds at most one segment, the render (after this block's reads) schedules the next one:

```
count == 1 : next = c.step + 1,  remaining = c.delay + c.fade_in + c.countdown + c.fade_out + c.tail − 256   0x08066EB8
             (counted from the START OF THE NEXT BLOCK: this block's frames are already consumed) ✓
count == 0 and not ending : next = 0, remaining = 0                                                     0x08066A18
synced (+0x1f5), non-Slice:
  next < +0x240 + +0x244 : t = tick(clock[0] + remaining)  0x08066C58;  nearest multiple of +0x208, tie → up  0x08066C7A
  else (wrap)            : layer ends if Loop Off or Launch = Trigger; else t = tick(clock[0] + remaining),
                           nearest multiple of +0x230 (0x08066F22..0x08066F9E), recompute (0x08066FAC), next = 0
                           delay = max(0, samples(t) − clock[0] − block)                  0x08066CD0, 0x08066CD8
unsynced   : step:  delay = max(0, remaining)                                                            0x08066EF0
             wrap:  same end test; recompute (0x08066E9E), next = 0, delay = max(0, remaining)           0x08066EA6
then FUN_08065550(pad, layer, delay, next, clock, note, first = 0)                                       0x08066CF2
```

`FUN_08065550` (non-Slice) starts the segment at frame `(int)((float)step × +0x1fc)` with countdown
`(int)+0x204 − 256` and rate `+0x18` (no BPM term). On the **last** step (`step == +0x240 − 1`) the end is
`len − 1` (`0x08065690`) and the countdown is re-derived every block from (end − pos) / rate: **the last step plays
its whole chunk at the native rate**, the others play `+0x204` output samples and skip the rest of their chunk ✓.
Measured, 44.1 kHz file of 211 680 frames at 133 BPM, Auto (clip 7680, 8 steps, `+0x204` 21 654): steps 0–6 sound
~21 910 samples (21 654 + fade-out), step 7 sounds ~28 800 (26 460 frames / 0.91875) and overlaps the next pass by
~7 150. A file shorter
than the clip leaves a gap instead (A2's table for 48 kHz files).

Two timing details, both ✓:

- **The synced grid choice is biased early.** `remaining` already counts from the next block, but the synced path
  adds it to `clock[0]` (this block's first sample): the nearest-grid decision is made on the previous segment's
  natural end − 256 − one block (−384 samples at 128 frames). The delay itself subtracts the block again, so on-grid
  steps land exactly (120 BPM, 4 beats, Sync 1/4: 11520, 12480, 13440, 14400, wrap 15360). The bias only tips exact
  ties (cases A and F below). The unsynced path has no bias: Sync None restarts every `len − 257` samples ✓ (95 743
  for 96 000 frames, 99 743 for 100 000).
- **Launch vs step convention.** The launch segment is created during the dispatch and read in the same process call
  (render `bl` at `0x0806887C`), so its delay is counted from `clock[0]`. A step segment is appended after this block's
  reads (`0x08066CFC`) and first read in the next block, hence the one-block subtraction. Both put the segment at
  samples(t) in the same frame: with the pads fed `clock[0]` one block ahead, a delayed launch and every step all
  sound exactly 128 samples early together ✓.

If `FUN_08065550` returns −1 (pool full) at `0x08066CF2`, the render logs and releases the layer's envelope
(`0x08066FD4..0x08066FEC`, static). A non-ending layer left with no segment would restart at step 0 on the nearest
step-grid tick (`0x08066A18`, static): phase is lost then. Neither was observed in any run.

`FUN_08065550` has a third caller, `0x08066B9A`, in the Slicer-only `+0xec` window (layer table). A hook on
`FUN_08065550` sees it, but a Clip pad never reaches it (the only store that opens the window is gated by `+0x254`).

## Sync = Slice on a Clip pad ✓

Sync's first entry (`Slice`, `+0x220` = `0xF0000`) gives n = 1. **Without slice markers** (`+0x250` = 0) the clip
plays as one synced step: the whole file, wrapping on the `+0x230` grid ✓. **With markers** it is a different
playback model:

- **Markers** come in on queue message `0x3c` (`0x0806856C`): `+0xc` = frame, `+0x10` = 1 inserts (sorted, ≤ 128),
  0 removes, 1000 clears ✓. The app sends a cell's whole list (clear, then one insert per marker) from `FUN_08099200`
  (9 callers, among them SetCellParam `0x0809FA50`), and edits through `FUN_080992ac` / `FUN_080993a8` /
  `FUN_08099434` / `FUN_0809aa20`. None of them tests the pad mode, so a Clip pad whose cell carries markers (made in
  Slicer mode, say) most likely has a table (*inferred*, static; not run through the app).
- **Segments** (`FUN_08065550` → `0x08065658` → `FUN_08065290` at `0x080655E6`): slice k starts at frame
  `+0x24c[k]`. Its frames are the next marker − this one, or `len − start` for the last (`fw_src_len` at
  `0x08065596`). Its output length is `round(slice_frames × +0x258 / BPM)` (`0x0806559C..0x080655C2`). That works out
  to the slice's share of the clip duration at the current tempo, for any source rate. The segment plays its frames at
  native rate and is cut at the output length when the tempo is faster, or followed by a silent tail up to it when
  slower ✓ (100 BPM: slice 0 = 20 000 samples of audio, then ~4 000 of tail).
- **Scheduling** (render `0x08066C2A` → `0x08066EE2`): the next slice is chained, `delay = max(0, remaining)`, with
  **no grid rounding**. The wrap comes when next ≥ `+0x250` (`0x08066EEC`) and is still rounded on `+0x230` ✓. So
  slice k starts at launch + (`+0x24c[k]` / len) × clip ticks. Markers [0, 20 000, 50 000, 70 000] on a 96 000-frame
  4-beat clip: ticks 11520, 12320, 13520, 14320, wrap 15360, the same ticks at 100 and 120 BPM. A 44.1 kHz 88 200-frame
  file gives 12390.76 / 13696.88 / 14567.64 ✓.
- Slice segments never pass `0x0806578C` (A2's H1); `FUN_08065290` prefetches at `0x0806541A` instead.

## The phase against the clock ✓

Stock has no launch-relative phase. **Every step boundary lands on the absolute multiple of `+0x208` (counted from
tick 0) nearest the previous segment's natural end, and every wrap on the nearest absolute multiple of `+0x230`**
(both biased early, as above). A target already in the past starts at once (delay clamped to 0). Stock's phase is
therefore its own step index (A2): step × `+0x208` + elapsed.

`phase = (ticks − anchor) mod clip` holds only in the **regular case**: the launch lies on the step grid (Quant a
multiple of `+0x208`), and the wrap grid divides both the clip and the launch tick (clip a multiple of Quant, or Quant
a multiple of clip). Then anchor = the launch's Quant boundary, which is `+0x140` only for an on-time launch: after a
late "now" launch `+0x140` holds the late tick (11532) while step 1 still lands on 12480. Measured at 120 BPM, a
48 kHz file the clip's length, launch queued before its boundary:

| case | Beat Count / Quant / Sync | `+0x208` / `+0x230` | launch | what stock does |
|---|---|---|---|---|
| regular | 4 / 1 bar / 1/4 | 960 / 3840 | 11520 | steps every 960, wraps 15360, 19200 … |
| E | 3 / 1 bar / 1/4 | 960 / 2880 | 11520 | regular (11520 is a multiple of 2880): wraps 14400, 17280 … |
| B | 4 / 1/16 / 1/4 | 960 / 240 | 7920 | step 1 at **8640** (a 16th early), then 9600, 10560, wrap 11520: anchor 7680 |
| C | 4 / 1/4 / 1/2 | 1920 / 960 | 12480 (beat 2) | step 1 at **13440** (a beat early), wrap 15360: anchor 11520 |
| E2 | 3 / 1 bar / 1/4 | 960 / 2880 | 15360 | the wrap rounds to 17280, already past: step 0 restarts at 17293 over step 2, then on the 2880 grid |
| A | 6 / 1 bar / 1/4 | 960 / 3840 | 11520 | the first wrap (17280) is a tie between 15360 and 19200, tipped early into the past: step 0 restarts at 16330.6 over step 5, step 1 at 17282.9, then a beat of silence (22080–23040) before the next wrap at 23040 |
| F | 3 / 1/2 / 1/4 | 960 / 1920 | 13440 | every wrap ties and tips into the past: step 0 restarts ~13 ticks after step 2 starts, every pass |
| D | 7 / 1 bar / 1/2 | 2240 / 3840 | 11520 | steps 11520, 13440, 15680 (multiples of 2240, off the beat), silence 17923–19200, wrap 19200, then 22400, 24640 |

With Sync None there is no clock phase: only the launch is quantized, and the loop free-runs (period `len − 257` at
rate 1). With Sync = Slice and markers the slices chain free within a pass, and only the wrap is on a grid.

## Clock convention — settled

The open point of the first version ("launches one block late, steps one block early if the pads see the advanced
clock") was wrong; see "Launch vs step convention" above. A2 ran the stock control tick `FUN_08053164` with the pad
as chain head: the pads run at `0x080531DA`, before the advance at `0x080531E0`, and see `clock[0]` = Sₖ, the
block's first sample. A6 measured that `duck_block` sees the same Sₖ, and the same `+0x30`, except on a block where
an engine command changes the transport (PLAY / STOP). So whatever `clipwin_tick` reads in `duck_block` is what the
pads use: **no block to add**. Only a module after the advance (DJ FX, the recorder) sees Sₖ₊₁.

## What it means for the Clip Window (for P2/P3; A2 owns the hook plan)

- **Phase:** use stock's step index per segment (A2's content-start formula), not `+0x140`. Outside the regular case
  stock itself re-phases onto the absolute grids; a launch-relative formula would disagree with what is heard.
- **Slip / mapped read:** inside JOEBOX's `clip_read` (chain, do not replace `clip_read_b`). The position is an int64
  in r2:r3. The fetch of `int(n × rate) + 8` frames is contiguous, so a rotated read that crosses the region end
  inside one block must be split. Fold the position before stock's `len + 0xff` bound sees it. Clamp the fetch to the
  1024-frame buffer, as stock does.
- **Virtual length — every `fw_src_len` site in class B**, with what each feeds (✓ by overriding one BL result at a
  time, unless marked):

  | site | feeds |
  |---|---|
  | `0x08064B2C` | Auto clip ticks (→ n, `+0x208`, `+0x230`, `+0x258`), `+0x1fc` frames per step, and `+0x204` when n = 1 ✓ |
  | `0x08064C5A` | `+0x23c` and `+0x258` only (not the step count) ✓ |
  | `0x08065690` | last non-slice step's end `len − 1` (static) |
  | `0x0806561E`, `0x080652A8` | `> 0` checks in `FUN_08065550` / `FUN_08065290` (static) |
  | `0x08065596` | last slice's frames, `len − start` (Sync = Slice on a Clip pad, or Slicer Sync; static) |
  | `0x080657C6` | Slicer without Slicer Sync: last slice end `len − 1` (static) |
  | `0x080662F6` | the clip reader's `len + 0xff` bound (static) |
  | `0x080668EA`, `0x08066B4A` | UI playhead (msg `0x4a` per-mille; static) |

  A Region that supports Sync = Slice also needs `0x08065596` and the slice table itself (frames are file frames).
- **Live changes:** re-sending Sync or Quant re-grids at once through stock code ✓; `0x90` only recomputes.
- **Sync = Slice with markers** bypasses H1. Either leave the Clip Window off for it, or extend A2's H1′ at
  `0x0806541A`.

## Still open

- Whether the app really sends a slice table to a pad in Clip mode (static only). A dev build's USB peek of pad
  `+0x250` on a Clip pad whose cell has markers settles it.
- The segment pool running dry (`FUN_08065550` → −1) was never produced. Two layers, each holding at most two segments
  when it schedules, fit in four slots, so it may be unreachable.
- `+0x23c` has no reader in class-B code; one elsewhere was not excluded.

## Verification

Independent verifiers re-ran or re-read every claim. All were re-checked here with fresh runs (`a1/r2/`). Outcomes:

| challenge | fresh check | outcome |
|---|---|---|
| C14: under the advanced-clock convention launches sound late and steps early | `t_conv.py`: launch queued 1000 samples early → conv 0: 0 / 24000 / 48000 …; conv 1: −128 / 23872 / 47872 … (all −128). Static: dispatch before render `0x0806887C`, step appended at `0x08066CFC` | **Corrected**: no mismatch, common offset. Real order from A2 / A6: no correction |
| C7: start frame = step × `+0x1fc`, countdown `+0x204 − 256` | `t_slice*.py` (Slice with markers: frames = table, chained), `t_last.py` (last step at native rate) | **Narrowed** to non-Slice steps other than the last; Slice path and last step described |
| Phase `(ticks − launch) mod clip`, anchor `+0x140` floored to Quant | `t_phase.py`, `t_phase2.py`, `t_gaps.py` (cases above) | **Replaced**: absolute grids; regular-case conditions stated; `+0x140` is not the anchor |
| Param `0x90` missing from the recompute triggers; `0x5c`, `0xf3` | `tables.py` (TBH `0x0806767E` decoded: `0x90` → `0x08067B30`), `t_params.py` (Beat Count 8 then `0x90` → clip 7680) | **Added**; `0x5c` / `0xf3` confirmed as no recompute |
| `fw_src_len` roles of `0x08064B2C` / `0x08064C5A`; sites `0x08065596`, `0x080657C6` missing | `t_params.py`, `t_len2.py` (override one BL result), `findbl.py` | **Corrected** (`0x08064C5A` was wrongly "step count"); both sites added |
| `+0x258` computed with 48000 | `t_params.py`, `t_slice.py` (130.612 for a 44.1 kHz 120 BPM file) | **Confirmed.** Not a defect where stock uses it: the Slice output length comes out right for any rate |
| Unsynced paths have no block subtraction; synced choice biased one block early | `t_bias.py`: remaining from the next block (286 920 + 128 + 24 952 = 312 000); unsynced period `len − 257` | **Confirmed**, added |
| count == 0 → step 0; third caller `0x08066B9A`; Attack 0 | static (`0x08066A18`; `scan_ec.py`: one `+0xec` store, Slicer-gated); `t_attack.py` (wrap step 0: fade-in 0, countdown 24 000) | **Added** (first two static) |
| Slip thunk site already taken | `patches/filter.py`, `src/filter_thunk.S`, `src/filter.c` read | **Confirmed**: chain inside `clip_read` |
| "Immediate" launch can be a few samples late | `t_misc.py`: 13 past → delay 12, `0x1b`, `+0x140` 11521 | **Added** |
| Live re-send of Sync / Quant was *inferred* | `t_resend.py` | **Now ✓** |
| Clock rounding | `t_clk.py`: ticks→samples = s0 + trunc(x + 0.5) for all 81 ticks around a nonzero origin, one sample late for t < t0; samples→ticks rounds as `round()` | **Confirmed** (matters only right after a tempo re-anchor) |
| Queue index formula | static read of `FUN_0805F2C8`; both harnesses post through it | **Confirmed**, transposition noted |

One defect turned up in the shared harness while checking: **A2's `Rig` leaves `ctx + 0x15850` zero**, so at rate ≠ 1
(any 44.1 kHz file, any Pitch) the stock reader fetches 0 frames and the position advances about 1 frame a block. The
countdown-based step timing is unaffected; positions and the last step's length are wrong. `a1/r2/base.py` `Rig2` adds
the input-bank buffers with the engine ctor's sizes (128, 1024, 128). It then advances 117.6 frames a block at
0.91875, and 192 a block at Pitch +7 semitones ✓. P2's `test_clipwin.py` must carry this fix before its rate ≠ 1 case.

## How this was checked

- Static: Ghidra decompile/listing and capstone of `FUN_08067648` (and its TBH table), `FUN_08064a94`,
  `FUN_08065908`, `FUN_08065550` (slice branch `0x08065550..0x080656A0`, fade-in drop `0x08065790..0x080657BC`),
  `FUN_08065290`, `FUN_08066454`, `FUN_080662E4`, `FUN_08066164`, `FUN_080667b8` (`0x080667B8..0x08066A60`,
  `0x08066B6E..0x08066D2A`, `0x08066E7A..0x08067000`), the process head and render call, `FUN_0806a34c`,
  `FUN_0806475c`, `FUN_0805F2C8`, the buffer helpers `0x0804D7E0` and `0x0804D8D0..0x0804D944`, the engine ctor at
  `0x08051540`, the pad ctor `FUN_080640d0` and the factory `FUN_080525f0`. The jump tables at `0x08068018` and
  `0x0806767E` were decoded from the image; `findbl.py` was run for `fw_src_len`, `FUN_08065550`, `FUN_08064a94` and
  `FUN_08065290`. Operand scans covered the message senders, `+0x238`/`+0x23c`, layer `+0x140` and `+0xec`.
- Labels: the stock registrar `FUN_0808c158` run whole under Unicorn, then its table read for each id.
- **Unicorn, stock image only**, first pass (`/srv/dev/firmware/re-scratch/a1/`): `padb.py` / `padb_checks.py`
  (ctor + param-set + recompute, 60 checks), `vstart.py` / `vstart_checks.py` (voice start), `dispatch.py` (the real
  process, one message per type), `render.py` (the real render after a real launch).
- **Second pass** (`/srv/dev/firmware/re-scratch/a1/r2/`): A2's whole-process `Rig` copied in (real block method,
  process, render, reader, stock clip reader and kernel, and clock advance; the source is stubbed as a ramp), plus
  `Rig2` (the input-bank fix) in `base.py`. The checks: `t_conv.py`, `t_slice.py`, `t_slice2.py`, `t_slice3.py`,
  `t_phase.py`, `t_phase2.py`, `t_gaps.py`, `t_bias.py`, `t_params.py`, `t_len2.py`, `t_misc.py`, `t_last.py`,
  `t_133*.py`, `t_pitch.py`, `t_resend.py`, `t_attack.py`, `t_clk.py`, `t_kern*.py` (the harness defect),
  `tables.py` and `scan_ec.py`. Each takes a few seconds with `/srv/dev/venvs/bb/bin/python <file>` from that
  directory.
- The verifiers' own harness (`/srv/dev/firmware/re-scratch/verify-a1/h.py`, `rend.py`) runs the real accessors
  against a fake sample-manager vtable and stubs the clip reader. Its results agree with the above wherever both ran.
