# A2 — the Sync step, the wrap, and where the Clip Window hooks in

Stock 3.1.9. Found 2026-10-15 (loop turn, blackbox#t-003), revised the same day after an independent verification
(round 2, "R2"; see "Verification"). Builds on A1 (`a1-class-b-pad.md`: pad, segment and layer fields) and A4
(`a4-clock-in-a-block.md`: the clock is the engine). ✓ = checked by running stock code under Unicorn (the real
class-B process, block by block; see "The harness"). *Inferred* = static read only. R2 runs measure **audio**: what
each segment mixes, sample by sample.

## The short answers

1. **Which clock.** The Sync step reads the **sample counter `clock[0]` and the tempo state** (`+0x08` tick origin,
   `+0x10` sample origin, `+0x18` BPM) through `FUN_08069C44` (`0x08066C58`) and `FUN_08069C64` (`0x08066CD0`). It
   reads neither `fw_position` / `+0x30` nor the cached `engine + 0x28D78` (no class-B load of it). **The pads see
   `clock[0]` = the first sample of the block being rendered** ✓. The module chain runs at `0x080531DA`, before the
   clock advance at `0x080531E0`, and `duck_block` runs before the whole control tick, so `clipwin_tick` sees the same
   `clock[0]` and `+0x30` as the pads: **no one-block correction**. Two things do reach the pads after
   `clipwin_tick` in the same block: the engine messages (a tempo change) and the pad's own `0x39` param messages
   (see "Tick order").
2. **The step's target position is not computed from the clock.** Each step is a **new segment in the same layer**,
   started by `FUN_08065550` at frame `(int)((float)(u32)step × +0x1FC)`: `vcvt.f32.u32` at `0x080656AC`, `vmul.f32`
   at `0x080656BC`, truncating `vcvt.s32.f32` at `0x080656D0`, int64 store at `0x0806570A`. It fades in over 256
   samples while the previous segment fades out. The clock only picks **when** the step starts: the grid tick
   nearest the previous step's nominal end. At every step start this equals the clock-derived target
   `((tick − launch) mod clip) × len / clip` **when the launch is on the Sync grid** ✓, whatever the file's own tempo.
3. **Shared or duplicated.** One segment-start function serves every case: the launch (`0x08065A9A`), every step and
   both kinds of wrap (`0x08066CF2`), and the layer `+0xEC` branch at `0x08066B9A` (*inferred*: a slicer slice
   change). `FUN_08065550` has exactly these three callers and no pointer to it exists. The tick rounding is inlined
   twice: the step on `+0x208` (`0x08066C58` → `0x08066CD0`) and the synced wrap on `+0x230` (`0x08066F22` →
   `0x08066F9E`). Both then share the tail at `0x08066CD6` (minus one block, clamped ≥ 0).
4. **The wrap** is a step-counter compare, `next ≥ +0x244 + +0x240` (`0x08066C4C` synced, `0x08066E80` unsynced).
   Step 0 restarts at frame 0. There is **no `p −= len`**: the file end is the last step's `end = len − 1`
   (`0x08065690`), so that segment stops at the file end ✓. The wrap is **not a crossfade** (measured below). Loop
   Mode Off or Launch Trigger → the layer ends after the last step ✓.
5. **Launch:** the voice start calls `FUN_08065550(step 0, first = 1)` at `0x08065A9A`, so **frame 0, always** ✓, with
   no fade-in. Only after that call does it set the first-block flag (seg `+0x3C`, `0x08065ABA`). The flag stays set
   until the launch segment's first read, which writes layer `+0x140` and posts msg `0x1D` ✓. **A launch waiting for
   its Quant bar is a segment with delay > 0 and `+0x3C` = 1** (also when armed with the transport stopped:
   delay 1, layer `+0x148` = 1 ✓). Anything that marks it done (our live-change drop, or stock's own `0x94`
   re-grid) makes it sound at once on the Sync grid, with no `+0x140` and no `0x1D` ✓.
6. **Quant vs Sync.** Quant (`+0x218`) quantizes the **launch** (`0x08065F1E`) and the **quantized stop**
   (`FUN_0806475C`, ✓ Toggle). It also sets the **wrap grid** `+0x230 = min(quant, clip)`, and it must be ≠ None
   for anything to be synced. Sync (`+0x220`) sets the **step length**: `n = clip / sync` steps, each snapped to the
   nearest multiple of `+0x208`. Neither one changes the playback rate. Sync None → one step, free-running ✓.
   **Stock defaults for a class-`'L'` cell** (`FUN_08093F20`, case `0x4C`, *inferred*, one read): Quant `0x47` = 3
   (1 bar), **Sync `0x94` = 5 (1/16)**, **Attack `0x3C` = 0**, Loop `0x8D` = 0, Launch `0x93` = 0.

## The clock in a block ✓

| who | when in the control tick `FUN_08053164` | `clock[0]` it sees |
|---|---|---|
| `duck_block` (JOEBOX, replaces the `bl` at `0x0804CE74`, calls the tick last) | before the tick | S<sub>k</sub> = first sample of block k |
| engine message drains: ring of 64 × 0x18 at `engine + 0xD7E0` (indices `+0xDDE0` / `+0xDDE4`) → `FUN_080520EC` (`0x08053C76`); second ring (indices `+0xE9E8` / `+0xE9EC`) → `FUN_08051938` (`0x08053D1C`) | tick start, before the chain (all paths rejoin at `0x080531D0`/`0x080531DC`) | S<sub>k</sub> |
| module chain, head `engine + 0xFC00` (pads among them) | `blx` at `0x080531DA` | S<sub>k</sub>, and `+0x30` = tick(S<sub>k</sub>) |
| clock advance `FUN_080696D8` | `0x080531E0` | sets S<sub>k+1</sub>, then `+0x30` = tick(S<sub>k+1</sub>) while playing (`+0x38`) |
| cache `engine + 0x28D78` = fw_position | `0x080534DC`, after the advance | — (never read by class-B) |
| recorder (`engine + 0x28D8C`, vtable `+0xC`) | `0x08053526` | S<sub>k+1</sub> |

**Tick order caveats for `clipwin_tick`** (static, two reads: capstone of the tick head and `FUN_080520EC`):

- A tempo message (`0x20`) is applied in the drain: `b.w FUN_08069BEC` at `0x08052236` re-anchors the tempo state
  (`+0x08` / `+0x10` / `+0x18`). In that one block `clipwin_tick` sees the old tempo and the pads the new one.
  Harmless: steps are scheduled in samples (see "Tempo change").
- A pad's `0x39` param messages (an app re-send of Sync, say) are applied inside the pad process, after
  `clipwin_tick`. So H4's "re-force" below sees a Sync change one block late, and stock may already have re-gridded
  to the user's Sync during that block.

The pad's block method `0x08068C64` is a chain link: it runs the process, then tail-calls the next module (pad `+8`,
vtable `+0xC`). **Finding the pads from `clipwin_tick`**: the cell factory `FUN_080525F0` (built once at boot, single
caller chain `0x0804C208` → `FUN_080530FC` → `FUN_080525F0`) appends every module to a list: head `engine + 0xFC08`,
tail `+0xFC0C`, next at module `+0x10`. Class byte at `+0x04` (`'L'` = 0x4C = the class-B pad), cell id at `+0x18`
(`a << 8 | b`, a and b in 0..3, no bank bit), factory serial at `+0x14`. **Every cell also gets an `'H'` (0x48)
module with the same `+0x18`**, so filter on `+0x04 == 'L'`. The pad's queue slot is
`(id >> 8) + 4 × (id & 0xFF) + 2` (`FUN_0805F2C8`). Two static reads (the factory, and `FUN_080519E0`, which walks the
same list by `+0x10` matching `+0x18`).

**Tick precision** ✓ (`r2/tickprec2.py`, the real `FUN_08069C44`). `FUN_0804D708` forms the beat count in single
precision, so the error grows with the time since the tempo origin. Worst |tick − exact| over 10-s windows:

| BPM | 10 min | 60 min | 2 h | 4 h |
|---|---|---|---|---|
| 97.3 | 0.53 | 0.76 | 1.25 | 2.50 |
| 120 | 0.60 | 0.92 | 0.96 | 1.92 |
| 133 | 0.60 | 0.96 | 1.13 | 2.24 |
| 174 | 0.67 | 1.21 | 2.41 | 4.81 |

Irrelevant for steps (snapped to a grid hundreds of ticks wide) and fine for `clipwin_tick`. The origin moves at
every tempo change.

## The Sync step in detail

**When a step is created.** When a layer holds at most one segment, the render schedules the next one right away. So
a step is created **about one step before it sounds** ✓ (lead 23 640–23 896 samples at 120 BPM, Sync 1/4), and step 1
is created together with the launch.

**Formula** (render `0x080667B8`, layer `L`, current segment `c`, pad `P`):

```
next    = c.step + 1                               (step index at seg +0x34)
remain  = c.delay + c.fade_in + c.countdown + c.fade_out + c.tail − 256
synced, next < count :  t = tick(clock[0] + remain)            0x08066C58
                        t = nearest multiple of P+0x208 (tie → up), absolute grid
                        delay = samples(t) − clock[0] − block  0x08066CD0, 0x08066CD8 (≥ 0)
synced, wrap         :  same with grid P+0x230 = min(quant, clip); then recompute     0x08066F22..0x08066FAC
unsynced             :  delay = remain (no grid)               0x08066EF0; wrap: recompute first 0x08066E9E
then FUN_08065550(P, L, delay, next or 0, clock, note, first=0)                    0x08066CF2
start   = (int)((float)(u32)step × P+0x1FC)   end = len − 1 on the last step, else 0
countdown = (int)P+0x204 − 256        (end ≠ 0: re-derived every block from (end − pos) / rate)
```

The delay is in samples (seg `+0x20`), decremented only by the reader. The recompute `0x08064A94` is also called by
the param-set (`0x080679CE`, `0x08067B38`) and by the process before each voice start (`0x08068312`, `0x0806838A`,
`0x0806840C`, `0x08068632`, `0x080686A8`), not only at a wrap.

**The grid is absolute, not launch-relative** ✓. With Quant 1/4 < Sync 1 bar, a launch on beat 2 snaps step 1 to the
next bar line: one beat early. Step 0 still plays its full bar, so the two segments sound together for a beat + 254
samples (24 254, audio ✓ `r2/qls_audio.py`; grid from `quant_lt_sync.py`). So a playing clip's **phase is stock's
own step index**: step × `+0x208` + elapsed. The plan's `(ticks − launch) mod clip` is right only when the launch lies on the Sync grid.

**Mismatched files** (4-beat clip, Quant 1 bar, Sync 1/4, 120 BPM; audio ✓, `r2/fades.py`, `r2/k_seam.py`):

| file | step starts (frames) | steps 0–2 play | last step | at the wrap |
|---|---|---|---|---|
| 96 000 frames (= 120 BPM) | 0, 24 000, 48 000, 72 000 | 256 + 23 744 + 256 | stops at frame 95 999 | V-notch: fade-out, 3 zero-gain samples, fade-in |
| 115 200 (100 BPM, slower) | k × 28 800 | 24 256 frames, last 4 544 of each chunk skipped | plays on to the file end | **overlaps the next pass for 4 797 samples at summed gain 2.0** (+6 dB, both full gain) |
| 88 615 (130 BPM, faster) | (int)(k × 22 153.75) | 24 256 frames, running into the next chunk | stops at frame 88 614 | **1 849 zero-gain samples** before step 0 |

**Fade shapes** ✓ (DC source, each segment's gain sample by sample). The 256-sample step crossfade is not
equal-gain: the summed gain dips to **0.73** mid-fade. The wrap is a fade-out to 0 then a fade-in from 0 (~512
samples of notch), not a crossfade. **Attack = 0** (param `0x3C` → pad `+0xBA1` = 1, read at `0x08065798` /
`0x08065426`) drops the fade-in of every step-0 segment: the wrap becomes fade-out then **hard start** (2 zero-gain
samples, then full gain). Attack 0 is the stock default for class-`'L'` cells (above), so a hard start at the wrap
is the common case. Whether a given preset keeps 0 is not checked. The slow-file doubling reaches the pad's bus at
twice the matched file's peak: nothing in the pad limits it.

**Tempo change** (120 → 126 inside step 1) ✓. The step already scheduled keeps its sample delay: it sounds where the
old tempo put it, 30 ticks off the new grid. The step after it lands on the new grid. `+0x204` (out samples per step)
is refreshed only by the next recompute.

**Live Sync / Quant change** (queued `0x39` message, Sync 1/4 → 1/2 inside step 1) ✓. The param-set saves the old
`+0x1FC` / `+0x1F5` / `+0x220` (into `+0x200` / `+0x1F6` / `+0x228`), recomputes, then re-grids (`0x08064E7C`)
every playing segment from **its own position**: `p_out = start + (pos − start) / rate` with `start = step × old
fps`, new step `= p_out / new fps`, new countdown `= (new step + 1) × new fps − p_out`. Seg `+0x08` itself is not
rewritten. Segments still waiting on a delay get `done = 1` and are rescheduled. The clip stays in phase. **Caveat
(stock behaviour) ✓**: that `done = 1` also hits a pending quantized launch. A Sync message (even a re-send of the
current value) between the note and its Quant bar makes the launch sound at once on the Sync grid (sample
195 688 instead of 288 000 in `r2/droplaunch.py`), with no `+0x140` and no `0x1D`. The `0x94` index is used unchecked as a table index
(`0x08067ADA`): anything that sends it must stay in 0..6.

**Others** ✓: Sync None → one step (the whole file), launch on the bar, then a restart every `len − 257` samples (the
loop drifts, as A1 found). A launch up to 384 samples (3 blocks) after a bar starts at once at frame 0 (300 late:
`+0x140` = 11 532, step 1 still on tick 12 480); 385 or more waits for the next bar (`r2/late.py`). A Toggle second
press stops at the next bar: the countdown at layer `+0x130` expires and the envelope releases.

## The harness — for P2's `test_clipwin.py`

`/srv/dev/firmware/re-scratch/a2/` (outside git; stock image only). Run with `/srv/dev/venvs/bb/bin/python <file>`
from that directory (or from `r2/`).

**R2 fix.** The round-1 `Rig` did not initialise the render's scratch buffer `ctx + 0x15850` (family
`ctx + 0x1583C`, stride `0x14`, `FUN_0805F390`; literal at `0x08066A78`). It was all zero, so every fetch wrote to
address 0 (✓, `r2/gap.py`) and **no round-1 check measured audio**. `clipproc.py` now builds that family (4 ×
`{cap 128, used 0, L, R, clear 1, stereo 0}`), sources frame q as (q + 1) × 2⁻²⁰ (frame 0 ≠ silence), clears the
buses each block and keeps their summed output in `r.out`. With the fix, `checks.py` (27) and `cwchecks.py` (22)
print **exactly the same** results as before: scheduling never depended on the buffer, only the audio did.

| file | what |
|---|---|
| `stock.py` | Unicorn wrapper (flash 2 MB at `0x08000000`, image at `0x08040000`, AXI, DTCM, SRAM, SDRAM 64 MB, stubs by address) |
| `clipproc.py` | **`Rig`**: the real class-B pad process, block by block (R2-fixed) |
| `checks.py` | 27 stock checks: A matched, B slow, C fast, D tempo change, E live Sync change, F one-shots, G Sync None, H late launch, I toggle stop, J advance-first. All pass |
| `order.py` | the stock control tick `FUN_08053164` with the pad as chain head (the clock-order proof) |
| `cwmodel.py`, `cwchecks.py` | round-1 Clip Window model and its 22 checks. **Superseded** by `r2/cw2.py` (different content formula, no launch guard, no region deferral) |
| `r2/aud.py` | **audio measurement**: a `Tracer` hooks the clip read (`0x08066622`) and the mix of the gained samples (`0x080666E2`, `FUN_080617C0`); `pair()` runs a scenario twice (DC source → each segment's gain; ramp → the frame that sounds) |
| `r2/cw2.py` | **the corrected hook spec** (below), as Python stand-ins acting on the real process |
| `r2/k_slip.py`, `k_live.py`, `k_seam.py`, `k_region.py`, `k_looplen.py` | the model checks quoted below |
| `r2/gap.py`, `qls_audio.py`, `late.py`, `fades.py`, `droplaunch.py`, `armed.py`, `h1regs.py`, `permille.py`, `recomp.py`, `hint.py`, `readmiss.py`, `tickprec2.py` | the single stock experiments quoted in this note |

**`Rig(frames, src_rate, bpm, stereo, cell)`** builds the pad (real ctor `0x080640D0`, `+0xB79 = 1` as the factory
sets it), an **engine block** of `0x30000` zero bytes (the clock: `+0x18` BPM, `+0x38` playing), the **context**
`ctx = engine + 0x128E0` holding the engine at `[ctx]` (`FUN_080530FC`), the buffer families `{cap, used, L, R,
clear, stereo}` at `ctx + 0x151FC` (3 scratch, `FUN_0805F3A4`), `ctx + 0x150E4` (16 buses, `FUN_0805F37C`) and
`ctx + 0x1583C` (4, `FUN_0805F390`), and the pad queue at the `FUN_0805F2C8` address.

Stubs: allocator `0x0804436C`, log `0x08043DE4`, and the sample source: `fw_src_len 0x080636F0`, rate `0x0806377C`,
ready `0x0806371C`, prefetch `0x0806375C` (logged), fetch `0x08063634` / `0x08063608` (log `(block, pos, n, real)`,
optional `r.map(v) → real`, `r.value(q)` for the data). Everything else is stock. An alternative that runs stock's
own length and fetch: a **RAM source** (`src+0x20 = 0`, `+0x04` data, `+0x10` length), with only `0x0806371C` and
`0x0806377C` stubbed (the verifier's harness did this; its audio results agree with these).

`params(...)` goes through the real param-set; `goto(S)` uses the real advance; `set_bpm(b)` re-anchors the tempo
origin; `note_on()` / `param(id, v)` queue type `2` / `0x39` messages. `step_block()` follows the control tick's order:
`pre_block(rig)` (the place of `duck_block` / `clipwin_tick`), the pad's block method `0x08068C64`, drain the app and
pad queues, the real advance. Logs: `reads`, `segs` (hooked at `0x0806578C`), `fetches`, `prefetches`, `posted`, `out`.

**For `test_clipwin.py`**: keep the Rig plumbing and load the **patched** image plus `out/cave.elf` the way `emu.py`
does; replace `cw2.CW2` by the real cave code and keep its assertions (audio level, via `aud.pair`). Required
cases: Clip Window off = stock bit for bit; a **non-integer-fps file** (88 615 frames); **off-grid launches**
(300 samples late; Quant 1 beat < Sync 1 bar); Slip ± incl. negative; live Slip with a **pending launch**; Region
change while playing; Loop Len engaged off-grid; the seamless wrap with the Clip Window on and off. Not yet run
anywhere: rate ≠ 1 (a 44.1 kHz file or Pitch) and stereo.

## Hook plan (corrected in R2)

There is no clock-derived target to offset, and no per-pad "next sync tick" to set. Everything stock knows about
the phase is the **step index of each segment**. So the Clip Window decides **what content each segment plays,
once, when the segment is created** (a per-slot latch), and maps frames in the reader. Stock's positions, timing,
crossfades, live re-grid, wrap and one-shot logic stay untouched. "Active" below = the pad's Clip Window does
something (Region ≠ whole file, or Slip ≠ 0, or Loop Len on); inactive → every hook passes through.

| hook | site | live there | does |
|---|---|---|---|
| **H1 segment latch** | `bl 0x0806375C` (prefetch hint) at **`0x0806578C`**, in `FUN_08065550`. Every non-slice segment passes here (the launch, every step, both wraps) | ✓ r0 = source (pad `+0x24`), r1 = max(0, start − 8), **r4 = pad**, **r5 = step**, **fp = stock start frame**, sl = end (0, or len − 1), sb = layer, **r8 = first** (launch), **`[sp+0x20]` = slot k**, `[sp+0x60]` = engine, `[sp+0x64]` = note. Final here: seg `+0x08` start, `+0x10` end, `+0x34` step. **Not final**: `+0x24` fade-in and `+0x28` countdown (for the launch and, with `+0xBA1`, step-0 segments, `0x080657A8–0x080657BA` move the fade-in into the countdown after the call); `+0x3C` is still 0 even for the launch (set at `0x08065ABA`) — take "first" from r8 | active: latch `(rs, vlen, delta)[pad][k]`, `delta = content − start`; prefetch at `rs + ((start + delta) mod vlen) − 8`. Inactive: invalidate, prefetch unchanged. Thunk: `ldr r2,[sp,#0x20]; mov r3,r4; b.w clipwin_seg_start(src, pos, k, pad)` (r2/r3 are reloaded by the caller) |
| H1′ latch clear | `bl 0x0806375C` at `0x0806541A`, in `FUN_08065290` (slicer, Sync = Slice; only caller is `FUN_08065550`) | r4 = pad, `[sp+4]` = slot k (static, two reads; the verifier also ran it with a slice table) | invalidate `[pad][k]`, then prefetch |
| **H2 mapped read** | `bl 0x080662E4` at **`0x08066622`** (JOEBOX's `clip_read_b` → `clip_read`) | s0 rate (≤ 8), r0 pad, r2/r3 position, `[sp]` n, `[sp+4]` &used, **`[sp+8]` &frac = seg + 0x1C**, `[sp+0xC]` scratch, `[sp+0x10]` out, `[sp+0x14]` &result | k = (frac − 0x1C − pad − 0x30) / 0x70. Latch valid: **fold** p to `p mod vlen` (the stock bound check, `fw_src_len + 0xFF < pos` → nothing mixed, must never see a virtual position), fetch each frame v at `rs + ((v + delta) mod vlen)` with the latched rs/vlen, wrapping inside one fetch; count `(int)(n × rate) + 8`, capped at the scratch frames; then stock's own kernel `FUN_080603EC`, or the straight copy when rate = 1 and frac = 0. Invalid → today's path, bit-identical |
| **H3 virtual length** | `bl 0x080636F0` at **`0x08064B2C`**, **`0x08064C5A`** (recompute), **`0x0806561E`** (> 0 check), **`0x08065690`** (last-step end) | r0 = source, **r4 = pad** at all four ✓ | active: return the **active** region's vlen, else the real length. **Seamless wrap** option, at `0x08065690` only: return 1 (end = 0, the last step crossfades into step 0) **only when the pad is active** (same predicate as H1, so H2 folds that segment), Loop Mode On and Launch ≠ Trigger |
| **H3′ region promote** | `bl 0x08064A94` (recompute) at **`0x08066FAC`** (synced wrap) and **`0x08066E9E`** (unsynced wrap) | r0 = pad (from r6), r1 = clock (from sl) | if a Region change is pending, make it the active region, then call the recompute. `clipwin_tick` promotes at once when no layer of the pad is active |
| H4 Loop Len grid | none: data from `clipwin_tick` | engine; ctx = engine + `0x128E0` | if W < `+0x208`, call the param-set `FUN_08067648(pad, engine, {0x39, 0, cell, 0x94, idx(W)}, ctx)` (only caller passes exactly this) so stock re-grids live ✓; restore the user's index on Off; re-force if `+0x220` changes under it. **Never while the pad has a pending launch** (an active, not-done segment with `+0x3C` set): the `0x94` re-grid would fire it early. Index 0..6 only |
| H5 UI playhead (P3) | `bl 0x0804F504` at **`0x080668FC`** (msg `0x4A`) | r1 = sp+0x58 = message (`+0x08` cell id, `+0x0C` source id, `+0x10` position, `+0x14` u16 per-mille), r6 = pad, fp = slot k | rewrite position and per-mille to the real frame. The per-mille divisor is the **second** `fw_src_len`, at **`0x08066B4A`** ✓ (`0x080668EA` only gates on len ≠ 0); rewriting the message covers both. Cosmetic |
| live change | `clipwin_tick` in `duck_block` | engine (same clock as the pads) | Slip or Loop Len changes on a playing pad: set `done = 1` (seg `+0x01`) on its segments that are active, not done, delay `+0x20` > 0 **and `+0x3C` == 0**. Stock drops and reschedules them in the same render and H1 re-latches ✓. Region changes: **deferred** to H3′ (below) |

**Every class-B `fw_src_len` call** (`findbl 0x080636F0`, 10 sites):

| site | in | what it feeds | Clip Window |
|---|---|---|---|
| `0x08064B2C` | recompute | ✓ `+0x1FC` frames per step, Beat Count Auto (n, clip), `+0x204` when n = 1 | H3 |
| `0x08064C5A` | recompute | ✓ `+0x23C`, file BPM `+0x258`; unsynced count `+0x240` (*inferred*) | H3 |
| `0x0806561E` | seg start | > 0 check | H3 |
| `0x08065690` | seg start | last-step end `len − 1` | H3 (+ seamless) |
| `0x08065596`, `0x080657C6` | seg start, slice path | slice ends | no (Slice) |
| `0x080652A8` | `FUN_08065290` (slicer) | slice ends | no (Slice) |
| `0x080662F6` | clip reader | bound check `len + 0xFF < pos` → nothing mixed | no: keep the real length; H2 folds |
| `0x080668EA` | render | len ≠ 0 gate for msg `0x4A` | no |
| `0x08066B4A` | render | per-mille divisor of msg `0x4A` | H5 rewrites the message |

`fw_src_len` itself (two reads): a **RAM source** (`src+0x20` == 0) returns `src+0x10`, and its prefetch
`0x0806375C` is a no-op. A provider source asks vtable `+0x14`: a negative length gives 0, and **length 0 gives the
sentinel `0x10000000`**. So H3 and the Region clamp must not derive vlen from that value: an unknown length → treat
Region as inactive (*design*).

**Content start** (H1; slot k, step j = r5, n = `+0x210`, tps = `+0x208`, fps = `+0x1FC` (float), clip = n × tps,
vlen and rs = the active region):

```
slip_f  = floor(slip_ticks × vlen / clip) mod vlen      int64, FLOOR (C '/' truncates: fix negatives), into [0, vlen)
w       = j                                             Loop Len Off, or W ≥ clip
        = (origin + ((j·tps − origin) mod W)) / tps     W ≥ tps (W, origin multiples of tps; mod taken ≥ 0)
        (W < tps: H4 makes tps = W first)
content = (int)((float)(uint32_t)w × fps) + slip_f      stock's own float32 product and truncation
delta   = content − start                               start = fp = (int)((float)(uint32_t)j × fps)
```

With Loop Len Off, `delta = slip_f` for every segment: **Slip is a pure constant shift**, and Slip 0 is stock frame for
frame. ✓ at audio level (`r2/k_slip.py`): for Slip 0, 960, −30, 7 and 3839, every sample where one segment sounds
plays `(stock frame + slip_f) mod len` (max error 0.014 frame, float decoding), and every sample's summed gain equals
stock's. Cases: the matched file, **88 615 frames (fps 22 153.75)**, a launch 300 samples late, Quant 1 beat < Sync
1 bar, default Sync 1/16. Round 1's model used `((w·tps + slip) mod clip) × vlen // clip` instead. That differs by one
frame on a non-integer fps (88 615 frames, Slip 960, step 1: 44 306 here, 44 307 there): **use the formula above**.

**Live Slip** ✓ (`r2/k_live.py`; Slip 0 → 480 and 0 → −7 inside step 1, files 96 000 and 88 615): the guarded drop
takes the one pending step (slot 0) and stock reschedules it in the same block. The sounding segment keeps its
latch, so nothing jumps: up to the next step boundary every sample equals stock. From the boundary (336 000) every
sample plays `(stock frame + slip_f) mod len`, reached through the normal 256-sample crossfade; the summed gain
equals stock's at every sample (no added silence or doubling).

**Loop Len origin** (KP3 anchor), at engage: take the layer's sounding segment (delay ≤ 0, not done; the newest one).
Its content phase is `j × tps + (p − (int)((float)j × fps)) × tps / fps` with p = seg `+0x08` (unslipped), j = seg
`+0x34`; `origin` = that phase rounded down to W. Do not use `+0x140` or `(ticks − launch)`. ✓ (`r2/k_looplen.py`):

- Quant 1 beat < Sync 1 bar, launch on beat 2 (tick 8 640), engage 1 bar at tick 15 500 inside step 2 (sounding frame
  195 520): origin 7 680, and steps 3 and 0 both replay from frame 192 000, the window that was playing. The
  launch-relative formula would give origin 3 840 (a jump back one bar).
- Loop Len 1/16 with Sync 1/4 inside step 1 (frame 33 000): origin 1 200; H4 forces Sync 1/16 and stock re-times the
  playing segment (next segment at 324 000); every later segment plays frame 30 000. Off one bar later: Sync 1/4
  restored, the next segment is step 2 at 432 000 playing 48 000: in phase.
- Launch 300 samples late (`+0x140` = 11 532), Loop Len 1/4 inside step 2: every later step replays 48 000.
- Engage requested while the launch is pending: refused until the launch has sounded (block 743, one block after
  the launch's first read); the launch stays at 288 000 with `+0x140` = 11 520.

Loop Len needs Quant ≠ None (stock's synced flag is Quant ≠ 0 and Sync ≠ 0). With rate ≠ 1 the (j, p) pairing after a
stock `0x94` re-grid is untested: `p_out` mixes source frames and output samples there.

**Region change on a playing pad: defer it to the next wrap** ✓ (`r2/k_region.py`; 96 000-frame clip, region →
[0, 48 000) at tick 12 840, inside step 1):

| procedure | result |
|---|---|
| round 1: new vlen now, drop pending, re-send `0x94` with the current index | the re-grid moves the playing segment to another step: segments start off-grid (ticks 12 845.16, 12 973.16), **11 418 zero-gain samples** |
| new vlen now, drop pending, no re-send | step 3's stock start 72 000 is past the new end 47 999: **23 490 zero-gain samples** until the bar |
| **deferred** (pending region, promoted at H3′; per-slot latch keeps each segment's own region) | stock-identical up to the wrap; the wrap's step 0 is the first segment of the new region (frames 0, 12 000, 24 000, 36 000). No silence caused by the change |

The deferred run still shows 12 003 zero-gain samples before the next wrap: that is the new region's own fast-file
gap (48 000 frames over 4 beats), which the seamless option removes. A relaunch while playing (a Gate/Toggle retrigger
on the other layer) recomputes at `0x08068312` / `0x0806838A` / `0x0806840C` / `0x08068632` / `0x080686A8` before
its voice start; promoting there too is possible but not modelled.

**Seamless wrap** ✓ (`r2/k_seam.py`, 2.4 bars after the launch):

| file | stock | seamless + latch/fold | seamless without the latch (stock reader) |
|---|---|---|---|
| 96 000 | 3 zero-gain samples at the wrap | 0 | 1 |
| 115 200 (slow) | 4 797 samples at gain 2.0 | 0 above 1.0 | 0 above 1.0 |
| 88 615 (fast) | 1 849 zero-gain samples | 0 | **1 847**: reads past `len + 0xFF` are refused |

Hence the gate on "active" above.

**Rejected: writing the slip into stock's position** (seg `+0x08` / `+0x10`) at H1 ✓ (`s2bad.py`). Positions past
`len + 0xFF` make the stock reader return silence. Even with the reader folded, a live Sync change re-grids from the
slipped position and cuts the playing segment early: ~91 silent blocks (the verifier measured 11 746 zero-gain
samples) against the normal notch for the latch.

**What this changes in the plan** (`notes/plan.md`):

- Engine piece 4 ("thunk on the `fw_position` / `0x08069C64` call feeding the target maths") is moot: there is no
  target maths. Slip = H1 + H2.
- Piece 5 ("per-pad next sync tick") does not exist. The guarded drop does the job at the next step boundary, and
  must skip a pending launch (`+0x3C`). With Sync None it is the next restart.
- Piece 6 is four `fw_src_len` sites (of ten), not "the wrap". Region changes take effect at the next wrap (H3′).
- Piece 7 is a mapped fetch, not two `clip_read` calls: the kernel then interpolates across the region seam as if the
  file were circular.
- `cw_target` needs no extra block. The phase is "step index", equal to `(ticks − launch_tick) mod loop` only for
  launches on the Sync grid.
- Launch needs no position hook: H1 sees the launch segment (step 0, r8 = 1).
- Piece 8 holds: Beat Count Auto is resolved from the `0x08064B2C` length H3 returns ✓.
- The risk "doctored clock also feeds launch quantization" is gone; the new risk is dropping a pending launch, guarded
  by `+0x3C`.
- State: `rs`, `vlen`, `delta` (int32 each) + valid per pad × 4 slots ≈ 0.8 KB in `cw_bank`, plus active/pending
  region per pad. Segment bytes `+0x40..+0x6F` are not free (the reader's gain ramps use them).

## Open, and what settles it

- **SD streaming at mapped jumps.** Samples come through the host provider (`0x2400A9C0`, vtable `0x080E9604`, X3).
  ✓ by execution on a hand-built host (`r2/hint.py`, `r2/readmiss.py`):
  - **Read** (`+0x08` = `0x08074A00`) serves **8192-frame blocks** (block = pos >> 13) from a cache of `0x267`
    entries of `0x1C`. An uncached block reads as **zeros** and increments a u32 miss counter at host `+0x8F70` =
    **`0x24013930`**.
  - **Hint** (`+0x10` = `0x08074CE8` → `0x08074554`) covers **3 blocks**: the one holding the position and the next
    2, i.e. 16 385–24 576 frames ahead of the position. Cached blocks get their LRU stamp refreshed; uncached ones are
    queued as type-4 requests when the reader slot's `+0x2C` flag is set.

  Stock hints each segment's start about one step ahead, and H1 hints the mapped start the same way. A region seam
  **inside** a segment jumps to `rs` with no hint. Mitigation: H2 issues the hint for `rs` once per segment when the
  mapped range will cross the seam within the next 16 384 frames (the hint's guaranteed reach). **Settle on the unit**
  with the dev build's USB peek (`src/usbdev.c`) of `0x24013930`, before and after one minute of each case: stock clip
  playback (baseline, expected constant), then Region = Loop with a Slip that puts the seam mid-step, on a file longer
  than the cache. Listen for drop-outs at the same time.
- **When a provider reports length 0** (the `0x10000000` sentinel) is not known; peek `fw_src_len` behaviour on a
  freshly loaded pad, or treat the sentinel as "Region off".
- **Rate ≠ 1** (44.1 kHz files, Pitch) and **stereo** were not run. The mapping is in frames and the stereo fetch is
  symmetric, so both should hold (*inferred*). The Loop Len origin after a `0x94` re-grid at rate ≠ 1 is untested.
- **Attack 0 on real presets**: the default is 0 (static); peek pad `+0xBA1` on a few loaded pads to see how common
  the hard wrap start is.

## Verification (R2)

An independent verifier re-ran this note with its own harness (RAM source, audio level) and challenged six claims and
the hook plan. Each point was settled again here with a fresh run or a fresh static read:

| point | challenge | settled by | outcome |
|---|---|---|---|
| Harness | Rig never initialised `ctx + 0x15850`: fetches went to address 0, no audio measured | `r2/gap.py` (dst = 0x0), static: literal `0x15850` at `0x08066A78` in the render; fixed Rig, re-ran all checks | **upheld**; fixed. All 49 round-1 checks print identical results; every audio claim here is from R2 runs |
| Live-change drop (P2-8) | dropping every pending segment kills a pending quantized launch | `r2/droplaunch.py`, `r2/armed.py` | **upheld**: unguarded drop → launch at 195 688 instead of 288 000, `+0x140` 0, no `0x1D`; guard `+0x3C == 0` → identical to no drop. Also covers a launch armed while stopped |
| Stock `0x94` before the launch | stock re-grid does the same | `r2/droplaunch.py` (`0x39 {0x94, 3}` at block 20) | **upheld** (stock behaviour); H4 waits for the launch (`r2/k_looplen.py` L4) |
| C11 seamless | without the fold, the fast-file gap stays | `r2/k_seam.py` | **upheld**: 1 847 zero-gain samples without the latch, 0 with it; gated on "active" |
| C13 hint reach | 3 blocks, not 4 | `r2/hint.py` (stamps blocks 2, 3, 4 for pos 20 000) + capstone (`sb = block + 3`, exit on `r6 == sb`) | **upheld**; read side (zeros + miss counter) ✓ by `r2/readmiss.py` |
| C16 tick precision | ~1.05 ticks at 2 h, not ≤ 1 | `r2/tickprec2.py` | **upheld** and widened: up to 1.25 (97–133 BPM, 2 h), 2.4 at 174 BPM |
| P2-14 per-mille | divisor is `0x08066B4A` | `r2/permille.py` (doubling the length there halves the per-mille; at `0x080668EA` no effect) + capstone | **upheld** |
| H1 "after final" | `+0x24`/`+0x28` change after the hook; `+0x3C` still 0 | `r2/h1regs.py` (launch: 256/23 744 at H1 → 0/24 000 after; Attack-0 wrap the same; `+0x3C` 0 → 1) + capstone `0x080657A8–0x080657BA` | **upheld**; table corrected |
| Content formula | model floored once on ticks, note twice with a float product | arithmetic + `r2/k_slip.py` on the note's formula | **note's formula kept**; ✓ exact on non-integer fps and off-grid launches |
| Loop Len origin | never tested off-grid | `r2/k_looplen.py` L1–L3 | **settled**: segment-based origin is right; launch-relative is wrong off-grid |
| Region live change | the round-1 procedure fails | `r2/k_region.py` | **upheld** (11 418 / 23 490 zero-gain samples); replaced by deferral (no silence) |
| `+0x1FC` attribution | from `0x08064B2C`, not `0x08064C5A` | `r2/recomp.py` (redirect each site to 48 000) | **upheld**: B2C → `+0x1FC`, Auto n / clip, `+0x204` (n = 1); C5A → `+0x23C`, `+0x258` |
| Tick order | engine/pad messages after `duck_block` | capstone of `0x08053164`/`0x08053C46`, decompile of `FUN_080520EC` case `0x20` | **upheld**; added |
| `0x94` bounds, H/L modules, cell id, queue index, `fw_src_len` sentinel / RAM path | — | capstone + decompile | **upheld**; added |
| Fade shapes | crossfade dip, slow-wrap gain 2.0, notch | `r2/fades.py`, `r2/k_seam.py` | **upheld**: dip 0.73, 4 797 samples at 2.0, 3-sample V notch; added |
| Attack default | not checked | static: `FUN_08093F20` case `0x4C` stores `0x3C = 0` | **upheld**: Attack 0 is the class-`'L'` default; preset values open |
| Citation | the multiply is `0x080656BC` | capstone | fixed (`0x080656AC` / `0x080656BC` / `0x080656D0`) |

Claims confirmed by the verifier and re-run here without change: the chain/advance order (`order.py`), the absolute
grid (`quant_lt_sync.py`), the mismatched-file table (now audio), the live Sync re-grid, the tempo change, Sync None,
late launch and Toggle stop (`checks.py`), Auto from the virtual length.

## How this was checked

- **Unicorn, stock image only** (`/srv/dev/firmware/re-scratch/a2/`): the real pad block method `0x08068C64` →
  process `0x08067FA4`, 1 200–3 600 blocks of 128 frames per scenario, the real clock advance after each block.
  `checks.py` 27/27, `cwchecks.py` 22/22 (both before and after the R2 harness fix, identical output). R2 audio runs:
  each scenario twice (DC, ramp) with the per-segment `Tracer`; the R2 model `cw2.py` acts at the hook sites with
  Python stand-ins. The clock order came from running the **stock control tick `FUN_08053164`** itself
  (`order.py`). The provider's hint and read ran on a hand-built host.
- **Static, two reads each** (Ghidra decompile + capstone): chain order and the message drains; the segment start
  (`0x08065550–0x08065908`) and the post-H1 fade move; the render scheduler and wrap (`0x08066C1C–0x08066D10`,
  `0x08066E7A–0x08066FD4`); the per-mille (`0x080668D8–0x08066B6C`); `fw_src_len` and its ten class-B callers
  (`findbl.py`); the `0x94` case (`0x08067ABA`); the factory list and `FUN_0805F2C8`; the hint loop
  (`0x08074554–0x0807470C`).
- One static read only (*inferred*): the class-`'L'` defaults (`FUN_08093F20`); the exact BPM store of the tempo
  message (`FUN_0804D648` is only partly decompiled); the unsynced count's dependence on `0x08064C5A`.
