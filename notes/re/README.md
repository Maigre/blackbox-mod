# RE notes — index and hand-off

Stock 3.1.9 (`BLACKBOX-3.1.9.bin`, sha256 `281ae303…1341d`), JOEBOX 1 full set where it says so. Written 2026-10-15
(blackbox#t-003) from the eleven P1 step notes below, after their verification rounds. Marks as in the notes: ✓ =
checked by running stock code under Unicorn, *inferred* = one static read, *design* = a choice, not a fact. Every
hook site named in §2 was re-read for this file (see "How this was checked").

**Status: P1 complete (2026-10-15).** Every step the task names has its note (A0–A7, X1–X3). What P2 still relies
on without a run is listed in the open questions below; P2's own `test_clipwin.py` and Gate 2 settle it, not more RE.

## 1. Index

| note | one line |
|---|---|
| [`a0-clip-pos-page.md`](a0-clip-pos-page.md) | The Clip Pos page (`0x080EF990`, class-0x4C copy `0x080EF288`) holds `0x8d 0xd2 0x47 0x94` then 32 empty slots; the list/beat tables; ids `0x1c8..0x1cf` are free. |
| [`a1-class-b-pad.md`](a1-class-b-pad.md) | The class-B (Clip/Slicer) pad object: param-set, recompute, pad/segment/layer fields, voice start, step and wrap scheduling on absolute grids, Sync = Slice. |
| [`a2-sync-target-and-wrap.md`](a2-sync-target-and-wrap.md) | The Sync step and wrap run whole under Unicorn; clock order in a block; **the Clip Window hook plan** (latch H1, mapped read H2, H3–H5) and the whole-process harness. |
| [`a3-waveform-clip-knobs.md`](a3-waveform-clip-knobs.md) | Waveform screen in Clip mode, knob step/range/value order, the knob → `SetCellParam` forward, acceleration (type 1 has none), the value formatter; Slip text/accel hooks, P3 knob hooks. |
| [`a4-clock-in-a-block.md`](a4-clock-in-a-block.md) | The control tick's arguments; the clock is the engine object. Its "add one block" and "recorder at `engine+0x28D8C`" are superseded (§5). |
| [`a5-djfx-xy-repeater.md`](a5-djfx-xy-repeater.md) | DJ FX framework (lists, class map, pool, sub-slots, swap), XY screen messages, the Repeater; Looper route A (reuse the Repeater) patch list. |
| [`a6-input-monitor-path.md`](a6-input-monitor-path.md) | The input monitor joins Out 1 before the pads, DJ FX and compressor; block order and clock per stage; the Resam tap; Gate 2's metronome recipe cannot work. |
| [`a7-stock-looper-class.md`](a7-stock-looper-class.md) | There is no stock looper/freeze/vinyl class; the stock contract for a DJ FX type of its own (route B); PocketRave's `0x24049808` is a note-sequence table. |
| [`x1-recorder-arm-and-midi-notes.md`](x1-recorder-arm-and-midi-notes.md) | Arming a recording from code (`FUN_0809F2E8`, the Save), what a take sets on its pad (S-B3), Global-In Pad Record notes, record-over (S-B2), message delivery inside a tick. |
| [`x2-sdram-and-memory.md`](x2-sdram-and-memory.md) | The SDRAM pool and allocators, free figures (upper bounds), the sample pool, where `cw_bank` and the Looper ring go, Patch RAM / backup SRAM maps. |
| [`x3-region-data-path.md`](x3-region-data-path.md) | How pad params reach the engine (40 class-B ids, the class-H sibling), mode change, WAV load and `smpl`/`acid` import, `fw_src_len`, mismatched-length wraps, the Region Auto rule. |

## 2. P2 hand-off — Clip Window v1 (Slip only)

Enough to write `src/clipwin.c` (+ `src/clipwin_thunk.S`), `patches/clipwin.py` and `test_clipwin.py` without
opening Ghidra.

### 2.1 What v1 does

- Stock plays a synced clip as one **segment per Sync step**: segment j starts at source frame
  `(int)((float)(u32)j × fps)` (fps = pad `+0x1FC`), crossfades 256 samples with the previous one, and only *when*
  it starts comes from the clock (absolute step grid). There is no clock-derived target to offset (A1, A2 ✓).
- **Slip = a constant circular shift of what every segment plays**: segment content = stock frame + `slip_f`,
  folded into the file. It is decided **once per segment, when stock creates it** (a per-slot latch, H1) and applied
  in the reader (H2). Stock's timing, crossfades, live Sync re-grid, wrap, one-shot and launch logic are untouched.
  Slip 0 → every hook passes through, bit-identical to today.
- **Live change**: a per-block poll sees the new value and marks the pad's *pending* segments done (the guarded
  drop); stock reschedules them in the same render and H1 re-latches them. The sounding segment keeps its latch, so
  the change is heard at the next step boundary through the normal crossfade, with no added silence (A2 ✓
  `k_live.py`). Stock Clip defaults are Sync 1/16 (✓ X3 t4), so usually within a 16th.
- Not in v1: Region, Loop Len, H3/H3′/H4/H5, the seamless wrap, Sync = Slice with markers (those segments never pass
  H1; Slip has no effect on them — document it).

**Active predicate** (H1 latches only when all hold; otherwise it invalidates): the cell id at pad `+0x18` is a real
pad (`id >> 16 == 0`, row = `id >> 8 & 0xFF` < 4, col = `id & 0xFF` < 4 — this excludes the 17th class-B object, cell
`0x401`, which has no H sibling and would alias pad 1 under JOEBOX's `& 3` masking); pad `+0x29` ≠ 0 (Clip/Slicer
mode active) and pad `+0x254` == 0 (not Slicer — Slip stays in the store when the pad changes mode); polled Slip ≠ 0;
`0 < fw_src_len(src) < 0x10000000` (0 = not open, `0x10000000` = provider reported 0 frames, X3 ✓); clip ticks > 0.

### 2.2 Hook sites

All stock sites are 4-byte `bl`, re-read with `disasm.py` for this file; none is patched by JOEBOX except
`0x08066622`.

| # | site | stock there | live at the site | ours |
|---|---|---|---|---|
| H1 | **`0x0806578C`** in `FUN_08065550` (segment start) | `bl 0x0806375C` (source prefetch hint, args `r0` src, `r1` pos) | r0 = src (pad `+0x24`), r1 = max(0, start − 8), **r4 = pad**, r5 = step j, fp = stock start frame, sl = end, sb = layer, r8 = first (launch), **`[sp+0x20]` = slot k**. Final here: seg `+0x08` start, `+0x10` end, `+0x34` step. Not final: `+0x24`/`+0x28`; `+0x3C` still 0 even for the launch. The caller reloads r2 (`ldr r2,[sp,#0x20]` at `0x08065790`) and r3 before use (✓ A2 `h1regs.py`; re-read here) | thunk `ldr r2,[sp,#0x20]; mov r3,r4; b.w clipwin_seg_start` → `void clipwin_seg_start(void *src, int32_t pos, unsigned k, uint8_t *pad)`. Read start/step from the segment (final). Latch or invalidate slot k, then call the prefetch itself with the mapped pos (§2.4). Every non-slice segment passes here: launch (`0x08065A9A`), every step and both wraps (`0x08066CF2`) ✓ |
| H1′ | **`0x0806541A`** in `FUN_08065290` (slice segment start; only caller is `FUN_08065550`) | `bl 0x0806375C` | r4 = pad, **`[sp+4]` = slot k** (stored at `0x0806540C`); after the call r3 is reloaded from `[sp+4]`, r0–r2 rewritten before use (static, two reads: A2 + this file) | thunk `ldr r2,[sp,#4]; mov r3,r4; b.w clipwin_slice_start` → invalidate latch [q][k], then tail-call the prefetch with (src, pos) unchanged. Needed in v1 so a slot reused by a slice segment cannot keep a stale latch |
| H2 | **`0x08066622`** in `FUN_08066454` (segment reader) | already JOEBOX: `bl clip_read_b` (stock `bl 0x080662E4`) | s0 rate (≤ 8.0), r0 pad, r1 filter (`fp + 0x14C`, set by `clip_read_b`), r2:r3 position (int64; stock uses the low word only), `[sp]` n, `[sp+4]` &used, **`[sp+8]` &frac = seg + 0x1C**, `[sp+0xC]` scratch, `[sp+0x10]` out, `[sp+0x14]` &result | change the one line in `src/filter_thunk.S` `clip_read_b`: `b.w clip_read` → `b.w clipwin_read` (same 11-arg C signature as `clip_read`). `k = (frac − pad − 0x30 − 0x1C) / 0x70`; require remainder 0 and k < 4, else pass through (§2.6). Alternative: re-hook `0x08066622` in `patches/clipwin.py` with old bytes = `bl clip_read_b` (then `filter` must precede `clipwin` in the set list) |
| tick | `duck_block` (`src/duck.c`, the JOEBOX hook of `bl 0x08053164` at `0x0804CE74`) | — | `engine` | add `clipwin_tick(engine);` after `insert_tick();` (one line). Runs before the pads in the same block, same audio task |
| F | **`0x080B0746`** (in `FUN_080B0728`, set-value, every type) and **`0x080B0E18`** (type-1/0x10 turn) | `bl 0x080B0528` (formatter, r0 = knob) | r0 = knob | `clipwin_format(knob)`: act only if `*(int*)(knob+0x14) == 0x1C9` **and** type `knob[0x31]` ∈ {1, 9} **and** `knob[0x2D8] == 0`; else tail-call `0x080B0528`. The type check matters: a reset knob keeps a stale id with type 0 (A3 ✓ E5) |
| K | **`0x080B0DDE`** (type-1/0x10 turn path of `FUN_080B0D54`) | `bl 0x080B0B74` (stepper add) | r0 = knob + `0x270` (stepper), r1 = counts (signed; the stepper sign-extends into an i64, so > 16 bits is fine) | `clipwin_turn(stepper, counts)`: knob = r0 − 0x270; for id `0x1C9` and type 1 scale counts (§2.7), then tail-call `0x080B0B74`. One site covers all 12 turn call sites, Pos-page list rows included (A3 ✓ E9). JOEBOX's `chord_knob` hooks a different stepper call (`0x080AE178`) |
| P | Pos page data, both copies | u16 `0x0000` at **`0x080EF998`** and **`0x080EF290`** (slot 5, right after Sync `0x94`) | — | `0x01C9`. P3 rewrites slots 5–7 to `0x1C8, 0x1C9, 0x1CA` |
| R | `master_register` (`src/master.c`, after `insert_register(table);`) | — | table | `clipwin_register(table)` → `fw_register_num 0x0808C12C(table, 0x1C9, 1, "Slip:", -3840, 3840, "clipslip")` |
| D | tail of `insert_defaults` (`src/insert.c`; called from `lfo_defaults`, the hook at `0x0809423C`) | — | store | `clipwin_defaults(store)` → `fw_store_add 0x08093EF6(store, 0x1C9, 0)`. Pad store 82 → 83 of 96 (JOEBOX's capacity; stock is 64) |
| M | `master_alloc` (`src/master.c`) | — | — | grow `EXTRA_BYTES` and clear `cw_bank`'s magic at `mem + PRISM_BYTES + 0x2D100` (§2.5) |

The xml names `clipslip`, `clipregion`, `cliplooplen` occur nowhere in the image or `src/` (grepped). Labels must be
≤ 9 characters.

### 2.3 Stock fields used

Pad = class-B `'L'` object (byte `+0x04` = `0x4C`, vtable `0x080D0890`, `0xBB8` bytes).

| object | offset | type | meaning (source) |
|---|---|---|---|
| pad | `+0x18` | u32 | cell id, `row << 8 \| col` (bank `<< 16`, 0 for pads) |
| pad | `+0x24` | ptr | sample source (arg of `fw_src_len 0x080636F0`, prefetch `0x0806375C`, fetches) |
| pad | `+0x29` | u8 | Clip/Slicer mode active (Pad Mode `0x8b` ∈ {1, 2}) |
| pad | `+0x254` | u8 | Slicer |
| pad | `+0x1F0` | f32 | source rate / 48000 |
| pad | `+0x1FC` | f32 | fps = source frames per step |
| pad | `+0x208` | i64 | tps = ticks per step (integer clip / n) |
| pad | `+0x210` | u32 | n = steps (1 when unsynced, Sync None, Slice) |
| seg k | `pad + 0x30 + k·0x70`, k = 0..3 | | one pool of 4 per pad, shared by both layers |
| seg | `+0x00` / `+0x01` | u8 | active / done |
| seg | `+0x08` | i64 | position, whole source frames (stock's "virtual" position; never rewrite it, A2 ✓ `s2bad.py`) |
| seg | `+0x1C` | f32 | fraction (the reader's `&frac` points here) |
| seg | `+0x20` | i32 | start delay, samples (> 0 = not started yet) |
| seg | `+0x34` | u32 | step index j |
| seg | `+0x3C` | u8 | first-block flag: set (after H1) on a launch segment until its first read; **a pending quantized launch** |
| layer L | `pad + 0x260 + L·0x410` | | `+0x00` active (the two layers are two voices) |
| app store | `0x24020088 + 0x1840 + row·0xF0 + col·0x30` | | `fw_setting 0x08093E9C(store, id)`: lock-free scan of `{u16 id; u16; i32 v}`; returns 0 for a missing id |
| knob | `+0x14` id, `+0x31` type, `+0x34` value, `+0x9C` value-text widget, `+0x270` stepper (`+0x27C` index, `+0x288` start), `+0x294` accel ring, `+0x2D8` freeze | | A3 |

Engine helpers v1 calls: prefetch `0x0806375C(src, pos)`; `fw_src_len 0x080636F0(src)`; `fw_src_stereo 0x08063790(src)`;
mono fetch `0x08063634(src, dst, count, pos, [sp] 0)`; stereo fetch `0x08063608(src, L, R, count, [sp] pos)`; buffer
frames `0x0804D8E8(buf)` (the scratch cap); mono channel `0x0804D934(buf)`; channel pair `0x0804DA0C(buf, &L, &R)`;
interpolation kernel `0x080603EC(s0 rate, r0 src, r1 count, r2 int *used, r3 float *frac, [sp] float *dst, [sp+4] n)`
(writes `*used` and `*frac`; ABI read twice for this file: decompile and capstone of the reader's call at
`0x0806638C`). Knob helpers in §2.7.

### 2.4 The formula (H1)

For pad q, slot k, at H1 (`len` = `fw_src_len(src)`, `slip` = the polled Slip in ticks, clamped to ±3840):

```
j      = u32 seg+0x34;   start = (int32) i64 seg+0x08          (final at H1)
tps    = i64 pad+0x208;  n = u32 pad+0x210;  clip = tps × n      (> 0, else inactive)
slip_f = floor(slip × len / clip) mod len                       int64; FLOOR, not C '/', for negative slip; into [0, len)
delta  = slip_f                                                 (v1: Loop Len off, Region = File → content − start = slip_f)
latch[q][k] = { rs = 0, vlen = len, delta, valid = 1 }
prefetch(src, max(0, ((start + delta) mod vlen) − 8))          replaces stock's max(0, start − 8)
```

General form for P3 (A2 ✓ `k_slip.py`, `k_looplen.py`): `w` = j, or with Loop Len W: `(origin + ((j·tps − origin) mod W))
/ tps`; `content = (int)((float)(u32)w × fps) + slip_f` with slip_f over the region's vlen; `delta = content − start`.
Use this float32 product and truncation, not a tick-domain formula: round 1's `((w·tps + slip) mod clip) × vlen // clip`
is one frame off on non-integer fps (88 615 frames, Slip 960, step 1). The latched `delta` makes every sample play
`(stock frame + slip_f) mod len`, launch late or off-grid included, any Sync (A2 ✓, max error 0.014 frame, gains equal
to stock's at every sample). Note `clip = tps × n` can differ from Beat Count × 960 when n does not divide it; use
the product, as the model did.

What Slip means musically: at each step start the content is the file's own position `j steps + slip ticks`, so the
offset is in the grid's ticks even for a file whose own tempo differs (*inferred* from the formula; the mismatched
files ran at audio level only at Slip 0 / model).

### 2.5 State (`cw_bank`)

SDRAM, behind JOEBOX's blocks: `master_block() + 0x56800 + 0x2D100` (= `+0x83900`; write it as a constant, because
`PRISM_BYTES + EXTRA_BYTES` moves once `EXTRA_BYTES` grows). `master_alloc` clears its magic at that offset (one line
beside the four existing clears); `master_block() == 0` → feature off, every hook passes through. Magic word bumped
with the layout, as `INS_MAGIC` (SDRAM keeps contents across a reset and a reflash). No `.data`/`.bss` in the cave.

Suggested layout: `u32 magic, scan; i32 slip[16]; uint8_t *pad[16]; u8 valid[16]` (bit k per slot) and
`struct { i32 rs, vlen, delta; } latch[16][4]` (768 B) ≈ 920 B for v1. **Reserve `0x800`, not the planned `0x400`**:
P3 adds an active and a pending region per pad (+256 B) and Loop Len origin/forced-Sync state, which no longer fits
in 1 KB. Add `_Static_assert(sizeof(struct cw_bank) <= …)` and a build-time assert on `PRISM_BYTES + EXTRA_BYTES`
(X2's ≤ ~0.4 MB budget; 2 KB is negligible). An oversized `master_alloc` hangs every boot (X2).

`pad[q]` is cached by H1 (`pad` is r4 there): a pad with pending segments has passed H1, since every non-slice
segment starts there. Validate before use (`pad[4] == 0x4C`, `+0x18` = the expected id). The alternative is A2's walk
of the engine's module list (first module at `engine + 0xFC08`, next at `+0x10`, keep class `+0x04 == 'L'`), *static,
two reads*.

### 2.6 The per-block poll and the reader

**`clipwin_tick(engine)`**, once per block from `duck_block`, one pad per call like `insert_tick` (`q = scan++ & 15`,
row = q >> 2, col = q & 3; all 16 within 16 blocks ≈ 43 ms):

1. `slip = fw_setting(store(q), 0x1C9)`, clamp ±3840.
2. If it differs from `slip[q]`: store it, then **guarded drop** on `pad[q]` (if cached and valid): for k = 0..3,
   seg = pad + 0x30 + k·0x70: if `seg[0] && !seg[1] && *(i32*)(seg+0x20) > 0 && seg[0x3C] == 0` → `seg[1] = 1`.
   **Never** drop a segment with `+0x3C` set: that is a pending quantized launch, and dropping it makes it sound at
   once off its Quant bar with no `+0x140` and no msg `0x1D` (A2 ✓ `droplaunch.py`, also when armed while stopped,
   `armed.py`).

Notes: the app writes its store before it posts, so this poll leads the engine. During a preset load the store is
cleared and rebuilt (`FUN_08093F20`) and a read can see 0 for a moment (X3 ✓ t11): harmless for Slip (a spurious 0 and
back; the load resets the pads anyway). No clock is read in v1, so the transport-edge caveat (A6) does not apply.
Capturing the value instead at the class-B param-set call `0x080685D2` (`bl 0x08067648`: r0 L, r1 clock, r2 msg
`{+0 u8 0x39, +8 cell, +0xC id (low 16 bits), +0x10 value}`, r3 ctx; X3) is possible but has no JOEBOX precedent and
nobody ran a `0x1C9` post through it.

**`clipwin_read(...)`** (H2), same arguments as `clip_read`:

- Latch invalid (or k bad, or no `cw_bank`) → `return clip_read(...)` unchanged: bit-identical to today.
- Latch valid: `v = pos mod vlen` (fold; floor), `real = rs + ((v + delta) mod vlen)`. The read needs frames
  `[real − 3, real + count)` (`count` = n when rate == 1.0 and `*frac` == 0, else `min((int)((float)n × rate) + 8,
  cap)`; the `− 3` is JOEBOX's machine-mode back-step `CLIP_BACK`).
  - **No seam inside that window** → `return clip_read(rate, pad, filter, real, 0, n, used, frac, scratch, out,
    result)`. Stock and the machine modes then read real, contiguous frames; `used`/`frac` do not depend on the
    position, and stock adds `used` to its own (virtual) seg `+0x08`. The stock bound `len + 0xFF < pos` sees `real <
    len` and never fires.
  - **Seam inside the window** (once per pass, in the segment whose content spans the file end) → do the stock
    reader's work with a mapped fetch: fetch `count` frames into the scratch buffer as two contiguous fetches (up to
    the region end, then from `rs`), mono through `0x0804D934` + `0x08063634`, stereo through `0x0804DA0C` +
    `0x08063608`; then, exactly as stock: rate 1 and frac 0 → `*used = n`, `*result = scratch`; otherwise run the
    kernel `0x080603EC` once (mono) or twice (stereo: left with *copies* of `*used`/`*frac`, then right with the real
    pointers), `*result = out`; return 1. This is the stock reader `0x080662E4` minus its bound check (A1/A2 + the
    capstone read here). A machine-mode pad gets stock interpolation for that one block (*design*; alternative: give
    `filter.c`'s machine path the same two-part fetch).
- The kernel interpolates across the seam as if the file were circular, which is the point (A2).

### 2.7 UI: the Slip row

| id | label | type | range | xml | default | page |
|---|---|---|---|---|---|---|
| `0x1C9` | `Slip:` | 1 (int) | −3840 … +3840 ticks | `clipslip` | 0 | Clip Pos slot 5, both copies |

- The engine ignores it: the class-B param-set drops ids > `0xF4` except `0x15F`/`0x1DD`, and neither class-B nor
  class-H stores `0x1C8..0x1CA` (X3 ✓ t1, t12). The row is stored and saved by stock (`SetCellParam` →
  `FUN_08093ECC`, which only overwrites ids already in the store — hence the defaults hook).
- **Text** (`clipwin_format`): value = `*(i32*)(knob+0x27C) + *(i32*)(knob+0x288)` for type 1 (not `+0x34`: the type-1
  turn never updates it), or `FUN_080B0416(knob, *(i32*)(knob+0x34))` for type 9; `FUN_080C89F4(buf, 32, "%c%d.%03d",
  v < 0 ? '-' : '+', |v| / 960, |v| % 960)` (stock `snprintf`, ✓ A3 E6: `+1.280`, `-0.030`, `+0.959`); then
  `FUN_080C3B98(knob + 0x9C, buf)` and `FUN_080B0480(knob)`. Ticks print 0..959 in a 3-digit field, so `+1.500` is
  1.52 beats (tell users; it matches the plan's `+0.480` = half a beat).
- **Acceleration** (`clipwin_turn`, type 1 has 400 counts per step and no acceleration of its own, A3 ✓):
  `FUN_080B0CC4(knob + 0x294, counts, *(u32*)0x2402EEE0)` (push to the 8-entry ring; `0x2402EEE0` = GUI time in ms),
  `m = FUN_080B0CE0(knob + 0x294)` (1..6 = |Σ counts| / span, counts per ms), then pass `counts × 10 × K[m − 1]`, e.g.
  K = {1, 2, 4, 10, 30, 60}: 1 tick per 40 counts slow, 60-tick steps fast (A3 ✓ E9: 11 ticks for 440 counts slow;
  fast clamps at 3840). K needs tuning on hardware (counts per revolution unmeasured). Do not combine with type 9.

### 2.8 What v1 leaves stock

Stock's playhead message `0x4A` (H5, `0x080668FC`) shows the unslipped position; Beat Count, Quant, Sync and the wrap
are unchanged; a Sync = Slice pad with markers ignores Slip; Slicer pads ignore it.

### 2.9 `test_clipwin.py` — what to copy and what to assert

Harness to copy (outside git, stock image only; port onto `emu.Emu(IMAGE, "out/cave.elf")` so the patched image,
cave and bank 2 load as in `emu.py` — `a2/stock.py` hard-codes the stock image):

| file | use |
|---|---|
| `/srv/dev/firmware/re-scratch/a2/clipproc.py` (`Rig`, R2-fixed) + `a2/stock.py` | the real class-B block method `0x08068C64` → process → render → reader, real clock advance; `params()`, `note_on()`, `param()`, `step_block()` with `pre_block` = where `clipwin_tick` runs; sample source stubbed (`0x080636F0` len, `0x0806377C` rate, `0x0806371C` ready, `0x0806375C` prefetch logged, `0x08063634`/`0x08063608` fetch logged) |
| `/srv/dev/firmware/re-scratch/a1/r2/base.py` `Rig2` | adds the input-bank buffers `ctx + 0x1583C + i·0x14` (caps 128 / 1024 / 128). **Required** for any rate ≠ 1 case, else the position creeps ~1 frame a block |
| `a2/r2/aud.py` (`Tracer` at `0x08066622` and the mix `0x080666E2`; `pair()` = DC + ramp runs) | audio-level checks: per-segment gain and the frame that sounds |
| `a2/r2/cw2.py` | the reference model of the hooks (Python stand-ins); replace by the cave code, keep its assertions |
| `a2/r2/k_slip.py`, `k_slip_lib.py`, `k_live.py`, `droplaunch.py`, `armed.py`, `h1regs.py` | the v1 cases and their expected numbers |
| `a3/r2/recheck.py` (E5, E6), `a3/r2/ownaccel.py` (E9) | formatter and acceleration on a knob bound by the real binder `FUN_080A7EE0` |
| repo `test_clip.py` (fetch stubs, machine modes), `test_insert.py` (fake stores, `is_bl`, thunk entry), A0's registrar run | unit parts |

Also set `*(engine + 0x128E0) = engine` (A6: the ctor + graph builder leave it 0; the Rig already stores it), and post
queue messages after `FUN_0805F3B8` in any tick-level harness.

Assertions:

1. **Image**: each site in §2.2 decodes to the intended `bl`/`b.w`; `clip_read_b` now branches to `clipwin_read`; both
   Pos pages read `0x8D, 0xD2, 0x47, 0x94, 0x1C9, 0…`; no other stock byte of the touched functions changes.
2. **Registration/defaults**: the patched registrar (`FUN_0808C158` run whole, register functions stubbed and
   recorded) registers `0x1C9` once, type 1, −3840..3840, label ≤ 9 chars, xml unique among all registered names (the
   stock `quantsize` duplicate is a warning, not ours); a type-3 pad store built by `FUN_08093F20` holds `0x1C9 = 0`
   with count ≤ 96.
3. **Off = stock**: Slip 0 on every pad → the Tracer's per-read (position, n, used, frac, fetch pos/count) and the
   mixed output are identical to the same scenario with the clipwin hooks bypassed, for the matched file, 88 615
   frames, a late launch and Sync None.
4. **Slip** (`k_slip.py`): Slip 0, 960, −30, 7, 3839 on 96 000 and 88 615 frames, launch 300 samples late, Quant 1 beat
   < Sync 1 bar, default Sync 1/16: every sounding sample plays `(stock frame + slip_f) mod len` (≤ 0.014 frame),
   summed gain equals stock's.
5. **Live** (`k_live.py`): 0 → 480 and 0 → −7 inside step 1: stock-identical up to the next step boundary, slipped
   after it, no extra zero-gain samples. **Pending launch**: a Slip change between the note and its Quant bar leaves
   the launch at its bar (288 000) with `+0x140` = 11 520 and msg `0x1D`.
6. **Gating**: a Slicer pad and a Clip pad with Sync = Slice + markers holding Slip ≠ 0 play stock; cell `0x401` and a
   `fw_src_len` of 0 or `0x10000000` → inactive; no SDRAM block → no writes, pass-through.
7. **Reader unit**: a block whose window crosses the file end, mono and stereo, rate 1 / frac 0 (straight copy) and
   rate ≠ 1 (kernel); a machine-mode pad off the seam still matches `test_clip.py`'s model at the mapped position.
8. **Not yet run anywhere — add**: a 44.1 kHz file, Pitch ≠ 0, stereo (all need `Rig2`).
9. **UI**: `+1.280`, `-0.030`, `+0.000`; a reset knob with stale id `0x1C9` prints `''`; slow turn 1 tick / 40 counts,
   fast capped by the range.

### 2.10 Gate 2 (bench) — corrected

The plan's reference clip (Resam of the metronome) cannot work: the click is added after the Resam tap and the
metronome mutes itself while a Resam take is armed (A6 ✓). Use the 1-bar factory drum loop (Loop On, Quant 1 bar,
Sync 1/4) or Resam one bar of a pad playing a click sample on Out 1; listen against the live metronome. Expect a
live Slip change to land at the next Sync step (1/16 on a recorded pad, 1/4 on the drum loop). `plan.md` is
corrected accordingly.

## 3. P3 / P4 / P5 notes

### P3 — Region, Loop Len, Clip-mode Waveform knobs

- **Region source**: the class-H sibling, `H = *(L + 8)`, valid iff `H && H[4] == 0x48 && *(u32*)(H+0x18) ==
  *(u32*)(L+0x18)`; LoopStart `H+0xFC`, LoopEnd `H+0x100`, Loop Mode `H+0x108` (0 None, 1 Fwd, 2 Bidir), in source
  frames, kept in Clip mode, in queue order (X3 ✓). Fallback: `fw_setting` with validation and last-good pair.
- **Auto** = Loop iff `0x8e ≠ 0 && 0 ≤ ls < le ≤ len && !(ls == 0 && le ≥ len − 1)`, else File (the last clause
  keeps a freshly loaded Loop-Forward pad on File; X3 ✓ t13). Treat `fw_src_len` 0 or `0x10000000` as "not ready /
  Region off" and re-validate every call (`L+0x24` refreshes only at a recompute).
- **H3** virtual length at `0x08064B2C`, `0x08064C5A`, `0x0806561E`, `0x08065690` (r4 = pad at all four ✓): return the
  *active* region's vlen; never `0x080662F6` (the reader bound must keep the real length; H2 folds). Beat Count Auto
  then follows the region ✓. Optional **seamless** wrap: `0x08065690` returns 1 only when active, Loop On and Launch ≠
  Trigger (A2 ✓ removes the 1 849-sample gap and the 2.0-gain overlap).
- **Region change while playing**: defer; promote at `bl 0x08064A94` `0x08066FAC` (synced wrap) / `0x08066E9E`
  (unsynced), r0 = pad, r1 = clock; at once when no layer is active. Immediate application gives 11 418 or 23 490
  zero-gain samples (A2 ✓). Relaunch sites (`0x08068312`/`0x0806838A`/`0x0806840C`/`0x08068632`/`0x080686A8`) not modelled.
- **Seam streaming**: the provider caches 8192-frame blocks and the hint reaches 3 blocks; a seam inside a segment
  jumps to `rs` unhinted. H2 should hint `rs` once per segment when the seam falls within 16 384 frames.
- **Loop Len** (KP3 anchor): origin from the newest sounding segment, `phase = j·tps + (p − (int)((float)j × fps)) ×
  tps / fps`, `origin = floor(phase / W) × W` (not `+0x140`, not `ticks − launch`; A2 ✓ off-grid). W < tps → force
  Sync with `FUN_08067648(pad, engine, {0x39, 0, cell, 0x94, idx}, engine + 0x128E0)`, idx 0..6 only (table
  `0x080EC82C`, no bounds check), restore on Off, never while a launch is pending. Needs Quant ≠ None.
- **Waveform knobs** (A3): binders `bl 0x080A7EE0` at `0x080A5806`/`12`/`1E`/`2A` (TL/TR/BL/BR); fix step → range →
  value at `0x080A53B0` (after `FUN_080A52C4`) and `0x080A5B0E` (after `FUN_080C6E8C`, every refresh); `KNOB_STEP` =
  `(int)view+0x1A0`; optional exact count `FUN_080B0984(knob+0x270, n)` against the top-end dead travel. Bracket:
  write `wave+0x22C/+0x230/+0x239` and dirty `+0x32` directly; never `FUN_080C6EDC` (clears slices `+0x238`). The
  forward stores `0x91/0x92` and our rows with no code. Playhead H5 at `0x080668FC` (msg `0x4A`, per-mille divisor
  from `0x08066B4A`), cosmetic.
- **Workflow traps**: Clip → Sample wipes the loop points (X3 ✓ t4); a Clip pad saved/trimmed by stock writes no
  `smpl` loop; an imported `acid` beat count refers to the whole file (rule needed when Region resolves to Loop).

### P4 — Looper FX (KP3 on the XY page)

- **Route A** (A5, recommended; X2 sized for it): the Looper is FX A's Repeater object in a 4th mode. Names: replace
  `bl 0x0808C594` (4-name table). Index latch: `b.w` at `0x0806E174` (r0 sub-slot, r1 `0x18`, r2 index; `bx lr` if > 3;
  record the mode in `cw_bank` keyed by r0; reset on a change into/out of 3; r1 = 0x40 for 3 else
  `byte[0x080DF6D8 + r2]`; `b.w 0x0806E048`). `fw_setting(0x24023090, 0x18)` is always 0 — never read the type there.
  Axis table relocated into the cave via the literals `0x080B1E44`/`48` and `0x080B20B8`/`BC`, new axis ids registered
  with real ranges. Wrap Repeater vtable words `0x080DF58C` (process), `0x080DF5F0` (active → 1), `0x080DF5F4` (hold →
  base `FUN_0806E490`), optionally `0x080DF5E4` (params).
- **Route B** (A7): own class (e.g. type `0x15`), map byte `0x080DF6DB`, `cmp r2,#3` at `0x0806E174`, `b.w` at the
  factory exit `0x0806CDA4` returning the object only when `r1 + 0x3A` is ours (r1 0..6 = "both busy"); reset
  idempotent, leaves `+0x18`/`+0x1E`.
- **Ring**: the Repeater buffers through `*(u32*)(0x2405FDE8 + 0x20)` every block (instance #1 `0x24015268` or #2
  `0x24015340`; `+0x24` = outgoing): ring L/R `+0x3C`/`+0x40` (384 000 floats each), capture `+0x4C`/`+0x50` (96 000
  each); int16 planar 16.0 s guaranteed, 20.0 s when the four are contiguous. Max Len bars = frames × BPM / (48000 ×
  60 × 4). CPU-only access (SDRAM is write-back cached).
- **Clock in the sub-slot** (after the advance): first sample = `engine+0x00 − io[0xB]`; first tick = the `duck_block`
  snapshot of `+0x30`; in-point `floor(t / len) × len` — not `FUN_0806A34C` (it returns the next line or "now").
- **Messages**: touch = `0x15` 1 then X then Y; Hold `0x1A`/`0x1B` then X/Y rest values; finger-up: X rest, Y rest,
  then `0x15` 0 (usually one block). `Source: Mix` already holds the monitored input (A6 ✓); `Source: In` = input bus 0
  read in `duck_block` (raw there). A post to the app from the DJ FX slot is wiped (X1 ✓): set a flag and append in
  the next `duck_block`. No knob rows on the XY page: Source/Max Len/Slip need another home.

### P5 — Save to slot and capture shortcuts

- **Arm**: `FUN_0809F2E8(0x24020088, ref)`, ref = `{u32 0x080EAF38, u16 row << 4 | col}` (MIDI refs at `0x2402EE60 +
  8N`), GUI task only. Check first: target name empty and `app+0x8CC1 == 0`. Settings go into the store the arm reads
  (`APP+0x8C90` when RecConfig `0xe1` = 0): `0x98 = 3` (1 bar), `0x97` = 3/4/5/6 (1/2/4/8 bars), `0x9a = 3` (Resam),
  `0xcf = 0`; RecToPlay `0x9d` is global and must be posted; JOEBOX Pre-roll `0x1b1` Off.
- **Keep the Record screen (4) up** from the call until the app handles `0x26`; leaving earlier aborts and deletes the
  take. The take starts at the next Rec Quant boundary: a Save never captures the bar that is playing.
- **After `0x26`/`0x29`**: the pad is Clip, Loop On, Toggle, Quant = Rec Quant (RecToPlay), Sync 1/16, Beat Count =
  round(ticks / quant) × quant / 960; Length `0x90` = 0 → write Length and the Clip Window ids yourself.
- Resam records after Master FX, compressor and clipper (A6 ✓; recorder compensates the tap delay). While Rec Input =
  Resam, input bus 0 holds last block's Out 1, so `Source: In` hears the Looper's own output during a Save.
- **Record-over** (S-B2): Clear-then-record keeps every store entry, including stale `0x8e/0x91/0x92`, which pass the
  Auto rule — reset Region/loop points on record-over.

## 4. Still unknown

| # | question | for | cheapest way to settle |
|---|---|---|---|
| 1 | Clip Window at rate ≠ 1 (44.1 kHz, Pitch) and stereo | P2 | Unicorn: `Rig2` + the cave code (item 8 of §2.9) |
| 2 | Slip on a machine-mode (Fidelity) pad, and the seam block | P2 | Unicorn: `test_clip.py` harness with a latch set |
| 3 | A negative type-1 value of a new id through preset save → load | P2 | Gate 2 step 6 on hardware; or Unicorn of the writer `0x08095328` + loader `0x08096AD8` on one pad store |
| 4 | Counts per knob revolution, GUI pass period (K tuning) | P2 | USB peek: `0x24001A30 + 4k` before/after one turn; `0x2402EEE0` in a loop |
| 5 | Cave space left after v1 (plan says ~4.5 KB free) | P2 | the link map of the P2 build |
| 6 | Does the app send a slice table to a Clip pad (Slip silently off there) | P2 doc | USB peek of pad `+0x250` on a Clip pad whose cell has markers |
| 7 | Attack 0 (`pad+0xBA1` = 1) on real presets (hard wrap start) | P2/P3 | USB peek on a few loaded pads |
| 8 | Live Slip under Sync None takes effect at the next restart | P2 doc | Unicorn: one `Rig` run |
| 9 | SD streaming at a region seam (cache misses) | P3 | USB peek of the miss counter `0x24013930`, stock vs Region = Loop with a mid-step seam; listen |
| 10 | When a provider reports 0 frames (`0x10000000` sentinel) | P3 | USB peek of `fw_src_len` inputs on a freshly loaded pad |
| 11 | Writers of `L+0x24` outside `0x08063000..0x0806A000` | P3 | whole-image store scan (static), or a hardware watch across a load |
| 12 | Does `0x08064C5A` feed the unsynced count `+0x240`? (notes disagree, §5) | P3 | Unicorn: A1's `t_len2.py` override, Sync None |
| 13 | Promote a pending Region at the relaunch recompute sites too | P3 | model it in `cw2.py` on the `Rig` |
| 14 | Record-over keeps `0x8e/0x91/0x92`; is a finished take ever re-opened by the loader | P3/P5 | Unicorn: X1's `r2/t_len.py` with the loop ids |
| 15 | Where the UI posts `0x8c` (cellmodeshort) | P3 | USB peek of `L+0x29`/`H+0x29` after using that list |
| 16 | Top-end dead travel of 0xD knobs on hardware | P3 | bench: Sample mode, zoomed, Loop End past the end and back |
| 17 | Task priorities behind the `fw_setting` race | P3 | static read of the thread-create calls (`main`) |
| 18 | Last-step overlap at the wrap (Sync on, file > Beat Count): audible? | P3 | bench listen |
| 19 | Count-4 FX A list with the relocated axis table | P4 | Unicorn: view handler `0x080B1EE4` + `FUN_080B1DE0`, index 3 |
| 20 | FX A slot, engine address on the unit | P4 | USB peek `0x2405FDE8+0x18` (= `0x30300`), `+0x20`; `0x24014434` (= `0x24037038`) |
| 21 | Hold (`APP+0x2C/+0x2D`) and DJ FX type across preset load / power cycle | P4 | USB peek `0x240200B4/B5`; power-cycle with Gater on FX A |
| 22 | XY orientation (which half is FX A, Y up?) | P4 | one look at the unit |
| 23 | Senders of effect messages `0x32`/`0x40`; which tempo command re-bases the map | P4 | static reads (`FUN_080520EC`) |
| 24 | Looper CPU cost | P4 | TOOLS load readout on the unit |
| 25 | Real free SDRAM after the largest preset load; preset save peak | all | USB peek `0x2400008C`/`0x24000088` after boot and after the load; Unicorn of the writer |
| 26 | Where the RecToPlay start lands in the stop block | P5 | Unicorn: the tick with a loaded Clip pad and the recorder at its stop block |
| 27 | XY → Record screen → XY Save hop end to end; Save from a `SetCellParam` intercept | P5 | Unicorn of the app path (`set_screen`, `0x26` handler), then Gate 5 |
| 28 | Buses 12/13 writers; trims `0x2400A9C0+0x9014..0x9030`; Rec Mon under RecConfig Per Pad | P5 | Unicorn of the recorder `0x105` path; static |
| 29 | Watchdog stamp writers (does a task-time overflow reset or hang) | trap only | static read of `0x080469C4`/`0x080469CA` callers |

## 5. Where the notes disagree (read the later or executed one)

| point | says | against | verdict |
|---|---|---|---|
| Recorder's place in the tick | A1 "Clock convention", A2 "clock in a block" table (`engine+0x28D8C`, after the advance, sees Sₖ₊₁), A4 | A6 ✓ (ran the tick), A7 (two writers + kind check), X1 ✓: `engine+0x28D8C` is the master EQ (vtable `0x080CFC40`); the recorder is root[4], before the advance, sees Sₖ | A6/A7/X1. P2 unaffected; P5 timing relies on A6/X1 |
| `cw_target` "+ one block" | A4 | A1/A2/A6 ✓: pads and `duck_block` see the same clock; and v1 has no clock target at all | superseded |
| `0x08064C5A` feeds `+0x240` | A2 table (*inferred*), X3 §4 table | A1 ✓ (overriding one BL result): only `+0x23C` and `+0x258` | A1. Harmless for H3 (both sites return the same vlen) |
| FX A axis table | A7 ("count `0x080EEA78` → 4, entry `0x080EEA88`") | A5 (revised): `0x080EEA88` is the store vtable `0x080EEA90`'s header; relocate the table via 4 literals | A5 |
| Looper ring memory | A7 (own ring, 1.5 MB SDRAM, from the plan) | X2 ✓: pool ≤ 1.43 MB free and is the preset-I/O scratch; use the Repeater buffers | X2 |
| Looper class | A5 route A (class `0x40` for both, latch hook) | A7 contract = route B (own type) | two options, not a conflict; pick one in P4 |
| Rec Active gates writing | X1 round 1 | A6 ✓, X1 revised ✓ | it does not gate |
| Plan's phase `(ticks − launch) mod loop` | plan | A1/A2 ✓ | step index; corrected in `plan.md` |
| Gate 2 reference clip | plan | A6 ✓ | corrected in `plan.md` |

## 6. Changes made to `plan.md` by this step

1. "Facts": Clip Sync = a new segment per step in the same voice, not a 2-layer handover.
2. "Engine architecture": a superseded-in-part box pointing here, and the corrected sentence about per-segment
   positions and the step-counter wrap.
3. "UI": Slip acceleration = our own curve at `0x080B0DDE` (type 1 has none).
4. "Looper FX": the ring lives in the FX A Repeater's buffers, not in `master_alloc`.
5. "Verification": the `cw_target` / `launch_tick` / split-read items marked superseded, pointing at §2.9.
6. "Gate 2 recipe": reference clip without the metronome Resam.
7. "Risks": the SDRAM-ring and input-monitor rows marked settled.

## How this was checked

- Every claim above is taken from the step notes and keeps their mark; where two notes disagree, §5 says which was
  executed.
- Re-read for this file with `disasm.py` on the stock image: the 4-byte `bl` at each of `0x0806578C`, `0x0806541A`,
  `0x08066622`, `0x080B0DDE`, `0x080B0746`, `0x080B0E18`, `0x080685D2`, `0x08064B2C`, `0x08064C5A`, `0x0806561E`,
  `0x08065690`, `0x08066FAC`, `0x08066E9E`, `0x080668FC`, `0x0804CE74`; the register use after H1 (`0x08065790..0x080657BC`)
  and H1′ (`0x0806540C..0x0806544C`); the stock reader `0x080662E4..0x080663BE` (bound compare on the low word, fetch and
  kernel argument order, matching the decompile); the Pos page words at `0x080EF990`/`0x080EF288`; the FX A map bytes
  `0x080DF6D8` and the bytes at `0x0806E174`/`0x0806CDA4`.
- Grep of `patches/` and `src/` for every proposed site: only `0x08066622` (filter) and `0x080A6C6C` (slice) are
  JOEBOX's. The candidate xml names occur nowhere.
- Not re-run here: no Unicorn run was made for this file; the ✓ marks are the step notes' own.
