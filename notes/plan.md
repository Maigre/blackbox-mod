# Plan — Clip Window (Region / Slip / Loop Len) + Looper FX (KP3-style on-touch looper)

## The two deliverables (Thomas, 2026-10-15, second clarification)

1. **Workflow 1 — unsynced recording → synced slot with Slip.** Record a loose chunk from an unsynced source,
   quickly set Loop Start/End in it, make it available to a slot that later plays that loop synced ("time-stretched"
   = Mk1 Sync re-alignment) with an easy Slip and, optionally, a quantized adjust of start/stop. → **Clip Window**
   on Clip pads (P2–P3).
2. **Workflow 2 — a simplified KP3 interface.** Catch a loop **on touch** from what is playing *now* (audio input,
   the BB's own mix, or both); the caught loop's quantized length is changeable live (KP3 / Traktor style); the
   loop can optionally be **saved to a slot** (base loop = max length, as a sample loop with the quantized length
   carried over) for later use. → **Looper FX** on the XY screen (P4) + **Save to slot** (P5). Both end on the same
   Clip Window semantics (Loop Len / Slip), so a saved loop behaves exactly like the live one.

## Context

Thomas owns a 1010music Blackbox **Mk1** (stock firmware 3.1.9, July 2026 — the last one; the product is
archived, replaced by the Blackbox 2). In 2024 he asked on the wish list for a way to shift where a Clip-mode
loop sits against the clock ("Slip", as on the Electrix Repeater). Neither Mk1 3.1.9 nor Blackbox 2 1.1.0 has it.

The full need (2026-10-15): (1) record a loose chunk from an unsynced source (phone), set Loop Start/End by ear in
Sample mode, play it at the BB BPM in Clip mode, then **fine Start/End + Slip** to lock it into the groove;
(2) **capture a quantized bar live** from hardware and slip it; (3) a **multi-slot KP3-like looper** (live loop
length per pad = KP3 X-axis, Y-axis FX later); (4) a **documented workflow** with shortcuts; (5) built as a
**fork of j3threejay/blackbox-mod (JOEBOX)**, each feature **PR-compatible**.

Two unofficial 3.1.9 mods appeared in Oct 2026: JOEBOX (C in a flash "cave" + Thumb call-site redirects,
Unicorn test suites, MIT) and PocketRave (Python Thumb-2 codegen, MIT; incompatible with JOEBOX — same cave
base, overlapping ids). JOEBOX is the base. Its newest release JOEBOX 1 is on hold (2026-10-14, some units stuck
restarting, suspected bank-2 self-install); a build installed **without `BBEXTRA.BIN`** keeps every bank-1
feature and avoids that path.

## Facts the design rests on (manuals, 3.1.9 strings, both repos — all read this session)

- **Mk1 Clip mode does not time-stretch**: at each Sync step (1/16 … 1 bar / Slice) stock starts a new *segment*
  in the same voice at frame `step × len/n`, crossfaded over 256 samples, on the absolute step grid (RE A1/A2; the
  two layers `pad+0x260` / `pad+0x670` are two voices, not a handover pair). Small BPM mismatch is inaudible;
  large = stutter. Clip mode plays the **whole WAV**; `samstart/samlen/loopstart/loopend` are ignored
  there — that is why Trim (destructive) exists in today's workflow.
- Clock: **960 ticks/beat**, bar = 4 beats; `fw_position 0x08069C38(i32 out[2], clock)`; clock = `bufs[0]`
  (`+0x18` float BPM, `+0x30` i64 ticks, `+0x38` playing); block = 128 frames @48 kHz.
- Clip reader chain: pad process `0x08067FA4` → render `0x080667B8` → segment reader `0x08066454` (keeps
  `position += used`) → **`fw_clip_read 0x080662E4(float rate, pad, filter, i32 pos, i32 pos_hi, n, *used, *frac,
  scratch, out, **result)`** — its single call site `@0x08066622` is already wrapped by JOEBOX (`src/filter_thunk.S:26-35`,
  `src/filter.c:590-661`). Class-B voice start `0x08065908` has 3 sites (`0x080683AE/0x08068656/0x080686CC`),
  all already thunked by `duck_voice_start_b` (`patches/duck.py:21-23`). Per-block pre-engine hook `duck_block`
  (`src/duck.c:91-150`) already chains `lfo_tick(); insert_tick();`.
- Stock recorder (3.1.9): Rec Quant ≠ None → always a clip, beat count embedded in the WAV, non-power-of-2 lengths,
  RecToPlay works. **MIDI Pad Record** (Tools>MIDI, Global In): notes 68–83 record pad 1–16 (pad must be empty;
  press again = stop), 84–99 clear, 100/101 prev/next, 102 play selected, 103 record selected, 104 clear selected.
  Clearing keeps pad parameters. Internals: `src/preroll.c` (+0x28 start, +0x30 stop, +0x38 RecQuant, +0x40 Length, +0x4b RecToPlay).
- Params: `fw_register_list 0x0808C0D8`, `fw_register_num 0x0808C12C`, `fw_store_add 0x08093EF6`,
  `fw_setting 0x08093E9C`, `SetCellParam 0x0809FA50` (stores + saves + posts to engine). Pad stores
  `APP(0x24020088)+0x1840+row*0xf0+col*0x30` (`{u16 id; u16; i32 value}` array at +4, count at +10), 96 slots,
  82 used → **14 free**. **Free ids 0x1c8–0x1cf** (0x1b5, 0x1e5 not free). Page tables 5×36 u16 per mode:
  Clip Main `0x080EF948`, **Pos `0x080EF990`** (Loop Mode `0x8d`, Beat Count `0xd2`, Quant Size `0x47`, Sync `0x94`,
  then 32 free slots — `re/a0-clip-pos-page.md`), class-0x4C copy Pos `0x080EF288`. The 13-entry quant tables
  `0x080ECC70/0x080ECCA4` are `0x45/0x46/0x48`'s; the Clip's Quant Size is 9 entries (`0x080ECAE4/0x080ECB08`).
- Memory: cave (bank 1) **~4.5 KB free** beside JOEBOX 1 (53,144 / 57,736); bank 2 = leaf DSP only; patch RAM full;
  new state → the SDRAM block from `master_alloc` (`src/master.c:498-531`, grow `EXTRA_BYTES`, magic cleared there).
  No `.data/.bss` (freestanding, `-Werror`, state behind magic words).
- UI: Waveform-screen knob binding pattern `src/slice.c` (Slicer mode: reset/label/type/range/value `0x080B04C8/…`,
  `KNOB_STEP` follows zoom, type 0xd = sample position; Sample-mode ids TR 0x90 / BL 0x91 / BR 0x92 = Length /
  Loop Start / Loop End); the view's generic forward (msg 0x6e → `SetCellParam`) stores stock ids with no code.
- MIDI CC: stock MOD page Learn stores `src=0x8000|ch<<7|cc` in the app pad store `+0x10` mod list; PocketRave
  applies CC itself (hook `0x0804FACC`, mailbox, `SetCellParam` from defaultTask — `pocketrave/mod/modcc.py`).
- KP3(+) looper = X axis loop length in beats, Y a modifier; touch loops what plays, release = live.
- Hub: no scaffold script — mint by hand (precedents `81a7120d mint(k1000)`, `060e3ef4 project(midiran2)`); fork
  schema `relation: fork` + `base:` (`docs/plan.md:74-79`); allowlist memory → `blackbox-mod:branch` in
  `config/loop.conf`; `prepare` refuses a repo without `verify:`; landings on a repo with another committer = GATE.
- mgr-ran: Java 25 ✓, `gcc-arm-none-eabi` 14.2 in apt (not installed), Python 3.14 (no unicorn/capstone → uv venv
  3.12), 18 GB free, `gh` logged in as **Maigre**. The stock 3.1.9 zip is a public download (sha256
  `281ae303…1341d`, verified) — kept once at `/srv/dev/firmware/`, never in git.

## Design (recommended)

### One feature family on Clip pads — "Clip Window" (per pad, saved with the preset)

| id | Row | Values | Meaning |
|---|---|---|---|
| 0x1c8 | `Region:` | Auto \| File \| Loop | `Loop`: the clip plays the Sample-mode loop region [LpStr, LpEnd) (already in the pad + WAV `smpl` chunk) instead of the whole file; Beat Count refers to the region. **Removes the Trim step.** **Default Auto** (Thomas's choice) = Loop when the pad has loop points (`0 ≤ LpStr < LpEnd < file length`, i.e. not the whole file), else File — a fresh recording or a plain file stays stock. |
| 0x1c9 | `Slip:` | −3840 … +3840 ticks, one row (Thomas's choice) | signed offset of where the loop sits against the clock; shown as beats.ticks (`+1.240`, `-0.030`); **accelerating knob**: slow turn = 1 tick (≈0.5 ms @120), fast turn = 60-tick (1/64) steps. Needs a value formatter hook (the knob text fn `0x080B0528` switches on type → intercept our id) and either the stock knob acceleration (RE A3 checks it on numeric rows) or our own step logic in a `slice_forward`-style intercept on the row. |
| 0x1ca | `Loop Len:` | Off \| 1/16 \| 1/8 \| 1/4 \| 1/2 \| 1 bar \| 2 bars \| 4 bars | only a window of that length loops, re-aligned to the clock = KP3 "looper beat" per pad; live. **Anchor = KP3 feel** (Thomas's choice): `window_origin` = the grid position (quantized to Loop Len) at the block where Loop Len was engaged, kept while it stays on, cleared on Off (full loop resumes in phase); Slip then shifts the window. |
| (0x1cb) | `Stretch:` | Sync \| Repitch | P6: rate so the region spans exactly Beat Count beats at the project BPM (no jumps; pitch follows tempo) |

(0x1cc–0x1cf stay free for P4/P5 rows: `Loop Rec`, CC mailbox needs none.)

Maths (one pure function, shared with the Python model in the test):
```
clip_ticks = beats×960;  loop = looplen ? min(looplen_ticks, clip_ticks) : clip_ticks
phase      = (ticks − launch_tick) mod loop
pos_ticks  = (slip + window_origin + phase) mod clip_ticks        (negatives normalised)
sample     = region_start + pos_ticks × region_len / clip_ticks   (int64 intermediate)
```
`window_origin` = the grid position (rounded down to Loop Len) at the moment Loop Len was engaged (KP3 feel —
decided), 0 while Loop Len is Off.

### Engine architecture: feed stock a **virtual file** (do not reimplement the clip player)

> **Superseded in part by P1 (A2):** there is no clock-derived target and no per-pad "next sync tick". Pieces 3–5
> are replaced by a per-segment latch at segment start plus a mapped read, piece 6 is four `fw_src_len` sites,
> piece 7 is a mapped fetch, and the maths below is replaced by A2's content formula. The corrected hook plan is
> `re/README.md` §2 (P2) and §3 (P3).

Stock keeps a whole-frame position per *segment* (one segment per Sync step, each started at `step × len/n`) and
wraps by a step-counter compare, not by "file length" (A1/A2). We make stock believe the file is `[0, vlen)` with `vlen` = region (or window) length,
offset its clock-derived target by Slip, and map virtual `p` → real sample in the reader hook. Stock's own launch
quantization, Sync realign, wrap, Loop Mode off (one-shot) and crossfade do the rest. Pieces (all bank 1, ≈2.5 KB):

1. **State** `struct cw_bank { magic, scan, ticks, now, bpm, pad[16] }` in SDRAM behind the clipper block:
   `CW_OFFSET = 0x56800+0x2d100`, `EXTRA_BYTES` +0x400, magic cleared in `master_alloc` (one line at
   `src/master.c:514-518`); `master_block()==0` → feature off (pattern `src/insert.c:108-130`).
2. **Per-block poll** `clipwin_tick(engine, bufs)` called next to `insert_tick()` in `duck_block`
   (`src/duck.c:146-147`): snapshot `fw_position`, BPM, sample counter; one pad per block reads
   Region/Slip/Fine/LoopLen + stock LpStr/LpEnd from the app store (latency 16 blocks ≈ 43 ms, like the insert);
   sets `dirty` on change.
3. **Launch**: the note-on voice-start site (labelled in RE A1) goes to a new asm `clipwin_voice_start_b` that
   calls `clipwin_launch` (records `launch_tick`, seeds the start sample = `cw_target`) then `b.w duck_voice_start_b`
   — chained, never double-hooked (`patches/duck.py:23`, `src/duck_thunk.S`).
4. **Sync target**: per-site thunk on the `fw_position`/`0x08069C64` call that feeds stock's target maths →
   `clipwin_position(out, clock, pad)` returns stock position + slip (+ window origin) — the `preroll_position`
   pattern (`src/preroll.c:88-95`). Loop Len: write the pad's clip-ticks/samples-per-tick fields from `clipwin_tick`
   (data only, audio task), restore on Off.
5. **Live Slip** → if RE finds a per-pad "next sync tick", `clipwin_tick` sets it to now when `dirty` → stock
   realigns + crossfades next block; else: takes effect at the next Sync step (documented).
6. **Virtual length**: thunk on the class-B `fw_src_len` call(s) that decide the wrap → `clipwin_len(src, pad)`
   returns `looplen ? loop_samples : region_len`.
7. **Reader mapping**: `src/filter_thunk.S:33-35` → `b.w clipwin_read` (same 11-arg signature) which maps
   `real = region_start + ((p + origin) mod region_len)`, splits the read when the window straddles the region end
   (two `clip_read` calls, `used` summed, second output written `n1` frames in via a temp buf header), then
   calls filter.c's `clip_read` so machine modes keep working. Feature off for the pad → straight pass-through
   (bit-identical to today).
8. **Beat Count Auto with Region=Loop**: free if the engine resolves Auto from `fw_src_len` (virtual length);
   if app-side: v1 documents "explicit Beat Count", v2 hooks the app's `fw_src_len` in the auto-detect.
9. **Repitch (P6)**: `rate *= (region_len/clip_ticks) / (48000×60/(bpm×960))` inside `clipwin_read`.

Fallback **arch C** if stock's Sync maths is inlined and un-doctorable: anchored mapping entirely in the reader
(per-layer `anchor_p/anchor_pos`, re-anchor on fresh voices and when `clipwin_tick` crosses a Sync boundary) — no
stock maths needed, loses the stock crossfade at our re-anchors (add a 64-sample in-reader crossfade later).

### UI
- Pos page rows: data patches on both copies (`0x080EF990`, `0x080EF288`): stock 4 ids + `0x1c8..0x1ca`
  (`patches/clipwin.py`, pattern `patches/filter.py:34-53`). Registration from `master_register` after
  `insert_register` (`src/master.c:180-181`); defaults at the tail of `insert_defaults` (`src/insert.c:95-104`):
  Region 0 (Auto), Slip 0, Loop Len 0. Store 82+3 = 85 ≤ 96. Slip is `fw_register_num` type 1 (int) −3840..3840
  with a formatter intercept for its id (beats.ticks) and our own acceleration curve (A3: type-1 rows do not
  accelerate; hook the stepper call at `0x080B0DDE`).
- Waveform screen in Clip mode (P3): hook the Clip branch's "unbind bottom knob" calls (RE A3) with
  `clip_bind_loopstart/_loopend` modelled on `slice_bind_start` (`src/slice.c:255-266`), binding the **stock ids
  0x91/0x92** with `KNOB_STEP` = samples per pixel (fine at full zoom) — the view's generic forward stores them;
  only the two refresh hooks are ours (`patches/slice.py:16-18`). Put it in `src/slice.c` "Clip mode" section to
  reuse its statics (space). BL/BR = Slip/Loop Len via private ids (`PARAM_ZOOM 0x3e2` style) later.
- Pads-screen LOOP knob position (P4): 4th position of the lower-right stepper (`src/solo.c` MIX → Mute → Solo →
  LOOP): TL Loop Len, TR Slip of the selected pad.
- MIDI CC (P5): CC hook `0x0804FACC` → 32-byte mailbox in `cw_bank` → applied in `clipwin_tick` to pads whose mod
  list has `dest ∈ {0x1c9,0x1ca,0x1cb}` with a CC source; INFO→MOD page for our rows via the can-modulate flag
  trick in `insert_info` (`src/master.c:330-349`).

### Looper FX — Workflow 2 (KP3-style, on touch, retroactive)

**Surface**: the 3.1.9 DJ FX XY screen (FX button → XY page; two slots `FX A:`/`FX B:`, xml `fxalgolivea/b`, stock
types Crusher/Filter/Echo/EchoHP/Flanger/Echo2/Repeater/Gater + `Enabled`). A new type **`Looper`** in that list (the
Repeater is its closest stock relative: a beat-synced repeat of the master). If the DJ FX list is not table-driven,
fallback = JOEBOX's Master FX slot (`src/master.c`, TOOLS row, list `Off/VHS/Prism` → `+Looper`) with the XY page's
touch forwarded to it (RE A5 decides).

**Behaviour** (decided with Thomas):
- Always-recording **ring** of the source in the FX A Repeater's own SDRAM buffers (X2 route A: 16 s of int16
  stereo guaranteed; the `master_alloc` pool cannot hold a ring — budget ≤ ~0.4 MB in all; size = `Max Len` bars at
  the current BPM, capped) — the same `cw_target` maths as the Clip Window applied to a ring:
  region = `[in_point, in_point + max_len)` in the ring, `clip_ticks = max_len` beats.
- **Touch = loop in** at the grid position (quantized to Loop Len, i.e. the beat/bar that was playing — the KP3
  feel); the loop plays *instead of* the live signal while engaged; **release = back to live** (KP3), knob
  `Hold: Off|On` latches it (Traktor) — default Off.
- **X = Loop Len** `1/16 … 4 bars` (9 zones; the in-point stays, the out-point moves — Traktor); **Y = HPF cutoff**
  on the looped signal (KP3 "Looper & HPF": bottom = open, top ≈ 4 kHz, mild fixed resonance; the SVF high-pass
  output from `src/filter.c`). Knob rows on the FX page: `Source: Mix | In` (Mix = everything on Out 1 incl. the
  monitored input via Rec Mon; In = the audio input alone, pre-mix), `Max Len: 1|2|4 bars`, `Slip` (ticks, the
  same accelerating row as the Clip Window), `Hold`. Optional if space: `Y Ctl: HPF | Slip | Wet`.
- **Output**: replaces the master signal with the loop while engaged (as the Repeater does); dry/wet later.

**Save to slot (P5)** = **resample via the stock recorder** (decided): one gesture (the `Save` row, or the Pads
LOOP knob position's button, or MIDI note 103) arms the stock recorder on the selected empty pad with Rec Input
Resam, Rec Quant 1 bar, Length = `Max Len`, RecToPlay On, Lead In/Pre-roll Off — it records the looper's output for
N bars while the loop keeps playing; the pad then holds a clip (beats embedded by 3.1.9) and gets **Loop Len / Slip
copied from the looper** so it behaves identically. Zero new file code. Direct memory→WAV write = P6.

### Stock-recorder capture, kept as the fallback/complement
Pre-armed 1-bar capture already works on 3.1.9 (Rec Quant = Length = 1 bar, RecToPlay, Pad Record → note 68+N
records the *next* bar into pad N). Shortcuts (P5, with Save): **S-B1** `Loop Rec: Off/1/2/4 bars` row on
Tools>Rec (sets Rec Quant = Length = N, RecToPlay On, Lead In/Pre-roll Off, Pad Record On — also what Save uses);
**S-B2** note 68+N / 103 on a *loaded* pad = clear + record, Slip/Loop Len kept; **S-B3** recorded-clip defaults
(Loop On, Toggle, Quant/Sync 1 bar — check what stock sets, RE); **S-A1** "Clip (loop)" pad-mode entry; **S-C1**
Pads LOOP knob position (TL Loop Len, TR Slip of the selected pad); **S-A4** Slip reset; `LOOPER.md`.

## Reverse-engineering plan (P1, Ghidra headless on mgr-ran; notes go to the hub, never the repo)

| Step | How | Validation gate (Unicorn) | Est. |
|---|---|---|---|
| **A0** Clip Pos page ids | unpack 36×u16 at `0x080EF990`/`0x080EF288` (+ Sample Pos for comparison); `gq.py sref "Beat Count:" "Quant Size:" "Sync:" "Loop Mode:"` → registrar pools → `disasm.py` 40 B before each `bl 0x0808c0d8/0x0808c12c` gives id/kind/names; tie xml names `beatcount/quantsize/synctype/loopmode/loopstart/loopend`; check pocketrave's 0x45/0x48 quant-table claim | stub the two register fns, run the stock registrar, assert (id,label,names) | 1 h |
| **A1** class-B pad fields | `findbl.py 0x08069C38 0x08069C64 0x080636F0 0x08065908` → class-B callers; `gq.py dec 0x08067fa4 0x080667b8 0x08066454 0x08065908` + the command handler containing `0x080683AE`; the param-set switch (`gq.py consts <P_BEATS>`) → which fields Beat Count/Sync/Quant/Loop Mode write; signature of `0x08065908` (s0 is a real arg) and which of the 3 sites is note-on / Sync realign / handover-wrap; the position field (i32 vs i64+frac) and the end-of-segment return | fake pad through the real param-set method, assert field offsets | 4 h |
| **A2** Sync target maths + wrap | formula around each `fw_position`/`0x08069C64` call; whether target is "start other layer at sample" (handover) or "write p"; where `samples_per_tick`/clip ticks come from (Beat Count Auto engine- or app-side: `gq.py callers 0x080636f0` in app range); the wrap compare + reset | **run the real class-B process `0x08067FA4` for hundreds of blocks** (recorder-style harness from `test_preroll.py`, source stubs from `test_clip.py:44-62`, clock +8 ticks/block, `0x08069C64` stubbed at 16 samples/tick); assert stock jumps to `(ticks mod clip_ticks)×16` at Sync steps and wraps at LEN → this harness becomes the backbone of `test_clipwin.py` (fallback: per-function tests + hardware) | 5 h (+4 h harness) |
| **A3** Waveform screen, Clip branch | `gq.py dec 0x080a58e6` → mode switch; Clip branch knob bindings + loop-marker flag; confirm the view forwards 0x91/0x92 generically and the class-B param-set ignores unknown ids | extend `test_slice.py`'s harness | 2 h |
| **A4** clock in a block | confirm `FUN_08053164`'s 2nd arg is the recorder's `bufs` | — | 0.5 h |
| **A5** DJ FX framework + XY screen (for the Looper FX) | `gq.py sref "FX A:" "Repeater" "repeatlen" "Enabled"` → the DJ FX type list/table and how a slot instantiates its effect (vtable per type? one switch?), the Repeater's process (ring + beat length — our template), the XY screen handler (touch down/up, X/Y → which params, "Enabled" = momentary vs latched), where FX A/B sit on Out 1 relative to JOEBOX's Master FX insert and the compressor (`src/comp.c:22,237`) | run the Repeater's process under Unicorn for a few blocks: it loops the last beat | 4 h |
| **A6** input monitor path | does Rec Mon (Mon Output = Out 1) reach Out 1 *before* the DJ FX / Master FX insert? (`0x0805F390` input-bus getter, the mixer in `0x08053164`'s callees) — decides whether `Source: Mix` already covers the input or whether `Source: In` needs the bus read directly (`src/insert.c:48-69` has the bus) | — | 1 h |
| **A7** the stock `looper`/`LOOP` engine class | the module registry (`0x24049808`, 64 entries; pocketrave `mod/sync.py:19-41`) lists class names incl. `looper`, `freeze`, `vinyl`: `gq.py sref looper` → is a complete looper module compiled in (shared 1010music engine)? If instantiable with params, it may replace our ring DSP | instantiate under Unicorn | 2 h |
| also | recorder clip flag/beat embed with Rec Quant; the recorder's arm/start message path for the Save gesture (`0x25` start, Rec Input/Length/Quant ids); Global-In note handler (68+N/84+N/103) for S-B2; what stock sets on a Rec-Quant clip (S-B3); free SDRAM pool size (`fw_perm_alloc` pool bounds) | | 3 h |

RE helpers: `ghidra/import.py` (edit `install_dir`, `JAVA_HOME` for Linux; project `ghidra/BLACKBOX-3.1.9`, Cortex LE
at `0x08040000`), `gq.py xref|sref|dec|fn|callers|callees|consts`, `disasm.py`, `findbl.py`, `findref.py`.
Dev builds (no `RELEASE=1`) expose USB peek/poke (`src/usbdev.c:453-467`) to read RAM on the running unit if an
address is in doubt. Fault/watchdog recorder (`src/fault.c`) stays on.

## Workflows on the unit (STOCK = today · NEW = needs the feature)

**(a) Offline loop from the phone → groove-locked clip** — 1 STOCK Phone→IN; Tools>Rec RecToPlay Off, Lead In Off,
Pre-roll Off; Metro On (Out 1); internal clock at the BPM you'll play at. 2 STOCK empty pad > INFO > Load/Record
(1x): L+R, Gain, Length Custom, Rec Quant None (RecThresh to skip silence); REC+PLAY, STOP. 3 STOCK Pad Mode →
Sample; Pos: Loop Mode Forward (Loop Fade 2–5 % if the join clicks); Conf: Launch Toggle; Waveform BL/BR = Loop
Start/End, pinch-zoom, Trigger to audition until the turnaround is clean. 4 ~~Trim~~ **removed by Region=Loop**.
5 NEW Pad Mode → Clip; Pos: Region = Loop, Loop On, Beat Count = region beats, Quant 1 bar, Sync 1 bar (melodic) /
1/4 (rhythmic) [S-A1 = one touch]. 6 STOCK PLAY, touch the pad. 7 NEW Waveform (Clip): Slip / Slip Fine against the
click until it sits; TL/TR Loop Start/End for a finer end. 8 STOCK PSET Save.

**(b) Workflow 2 — KP3 looper on touch, then save** — 1 STOCK clock: BB master (Send MIDI) or follow (Receive);
hardware → IN; Tools>Rec: Rec Mon On, Mon Output Out 1 (so the input is in the mix; or `Source: In`). 2 NEW FX
button → XY page: FX A = **Looper** (`Source: Mix`, `Max Len: 4 bars`, `Hold: Off`). 3 STOCK PLAY; play/let the
hardware play. 4 NEW **touch the XY pad**: the bar that was playing loops from its grid start; slide **X** to
shorten/lengthen (1/16 … 4 bars, in-point fixed), **Y** for the HPF sweep, the `Slip` knob to nudge it; lift =
live again (or `Hold: On` to latch). 5 NEW **Save**: select an empty pad, `Save` → the stock recorder resamples
the loop for `Max Len` bars into the pad as a clip with Loop Len/Slip carried over (RecToPlay plays it); the looper
is released; the pad now follows Workflow 1's Clip Window (Pads LOOP knobs, waveform Slip, CC). 6 STOCK PSET Save.

**(c) Multi-slot session (4 pads, Launchpad-like controller)** — preset LOOPER: RecConfig Per Pad, RecToPlay On,
Pad Record On; pads 1–4 empty with `Loop Rec` = 1 bar (1–2) / 4 bars (3–4); controller Drum mode: 36–39
play/toggle, 68–71 record (pre-armed next-bar capture, or Save after a looper catch), 84–87 clear. Jam: catch with
the looper, Save into the next slot while it plays, mute via pad toggle / MIX>Mute, Loop Len/Slip of any slot live
from the Pads LOOP knobs (P5) or CC (P6).

## Phases, gates, estimates

State on 2026-10-21: P0–P3 done; **Gate 3 passed** on 37.4.1d (21/10) — Workflow 1 is complete. P4 (the Looper) is
next. What went upstream and how: `notes/pr-map.md` and `FORK.md`.

| Phase | Deliverable | Bench gate (Thomas) | Est. |
|---|---|---|---|
| **P0 setup + pipeline** | fork `Maigre/blackbox-mod` (`main` = upstream mirror, `maigre` = integration), mgr-ran toolchain, stock image at `/srv/dev/firmware/`, `check.sh` green on Linux (host build → gcc `.so`), fork-only commit (`src/release.h` RELEASE_NAME "BBLOOP 1" ≤8 chars, distinct BUILD letter), build cave-only (`patch.py cave`) + full-set images, hub mint + arming | **Gate 0**: cave-only image WITHOUT `BBEXTRA.BIN` boots, TOOLS shows our name, pads play; then the full set (restart loop yes/no = data for the maintainer); back to stock | machine 1 d · bench 0.5 h |
| **P1 RE** | the table above; notes `projects/blackbox-mod/notes/`; Unicorn gates incl. the class-B process harness | — | 2–3 d |
| **P2 Clip Window v1 = Slip only (M0)** | `src/clipwin.c`, `patches/clipwin.py`, `test_clipwin.py`, Slip (+Fine) rows, chain lines, README bullet; `feat/slip` for a PR | **Gate 2** (click vs click, below) | 1–2 d · 0.5 h |
| **P3 Region + Loop Len + Waveform knobs** (= Workflow 1 complete) | Region Auto\|File\|Loop (+ Beat Count Auto from region), Loop Len (KP3 anchor), Clip-mode Waveform knobs, Slip reset | **Gate 3**: workflow (a) on a real song with no Trim; Loop Len 1/4 = one-beat stutter, Off = whole loop in phase, no click at the region edge; save/power-cycle/reload keeps all values; installed with this build's `BBEXTRA.BIN` beside `BLACKBOX.bin` (D-017: Loop Len runs from bank 2), TOOLS shows no `!` | 3–5 d · 1 h |
| **P4 Looper FX v1** (= Workflow 2 live part) | `src/looper.c` (+ ring DSP in bank 2 if > 2 KB, else bank 1), `patches/looper.py`, `test_looper.py`: Looper type in the DJ FX list (or Master FX fallback), SDRAM ring, touch = loop in on the grid, X = Loop Len, Y = HPF, knobs Source/Max Len/Slip/Hold, release = live | **Gate 4**: hardware playing into IN + a BB drum loop; touch catches the bar that was playing, in time; X from 1 bar down to 1/16 and back without clicks; Y sweeps; lift = live; `Hold` latches; `Source: In` excludes the BB's own pads; CPU load readout stays < ~85 % | 4–6 d · 1 h |
| **P5 Save to slot + capture shortcuts + doc** | `Save` gesture (stock recorder resample, Loop Len/Slip copied to the pad), S-B1 `Loop Rec` row, S-B2 record-over, S-B3 recorded-clip defaults, S-C1 Pads LOOP knobs, `LOOPER.md` | **Gate 5**: catch → Save → the pad plays the same loop in phase with the live one, Loop Len/Slip carried; 4 slots filled in a 2-min jam with the Launchpad-style controller, one-press re-takes | 3–4 d · 1 h |
| **P6 MIDI CC + extras** | Learn → Slip/Loop Len per pad and for the looper; then optional: Repitch stretch, direct memory→WAV save, `Y Ctl` selector / Wet, second-slot FX layer, per-pad XY | one gate each (CC: no zipper, Learn survives reload; Repitch: a 118-BPM loop at 120 with no stutter) | 2–6 d each |

Feature-only build is not practical (registration/defaults/SDRAM chain through the comp/master/duck sets) → Thomas's
unit runs the **full JOEBOX 1 set + ours**, through P2 without `BBEXTRA.BIN`, **from P3 with the `BBEXTRA.BIN` of
the same build** (D-017, D-018: the Clip Window's maths is in bank 2; without it Slip, Region and Loop Len do
nothing, and an older payload up there also switches Prism, Confetti and the inserts off); the feature is inert at
default settings (pass-through everywhere), so behaviour = JOEBOX 1 until a row is changed.

## PR strategy (upstream j3threejay/blackbox-mod)

- Fork branches: `main` = fast-forward mirror, never committed to; `feat/<name>` one feature each from `main`;
  `maigre` = integration (`main` + all `feat/*` + the release-name commit); hub `repos: branch: maigre` so loop
  branches `37loop/blackbox-mod-t-NNN` cut from it and the bench tests the union. Tag `thomas-YYYY-MM-DD` per install.
- Upstream squashes releases → PRs are ported by hand; one PR = one feature: `src/<f>.c` (+ `_thunk.S`),
  `patches/<f>.py`, `test_<f>.py`, README bullet (+ Known issues), minimal chain touch (one `x_register(table);` +
  `x_defaults(store);` appended at the END of the chains in `src/master.c` / `src/insert.c`; one line in `duck_block`),
  set name in `check.sh` + README build line, the hardcoded `IMAGE =` lines updated in the same commit (upstream's own churn).
- Never in fork/PR: `firmware/*`, `out/`, patched images, `BBEXTRA.BIN`, Ghidra projects/exports, decompiled
  listings, manuals, RE notes (hub only), `docs/*.json` + `docs/index.html` (maintainer's release artefacts; Thomas's
  builds come out of `make_patch.py` locally, uncommitted). Addresses only as C comments, JOEBOX style.
- First contact (Thomas sends after Gate 2; I only draft an outline in the hub — hard rule 4): who/our install data on
  the JOEBOX 1 hold; what we add and why; asks (reserve ids 0x1c8–0x1cf, Linux host build, an `IMAGE` convention);
  his preferences; offer a second test unit.

## Addition (Thomas, before approval): project "BlackBox" in Trente-Sept, fork under Maigre, working docs in the fork

- Hub project slug **`blackbox`** (title "BlackBox — Clip Window + Looper FX firmware mod (JOEBOX fork)"),
  `organisation: people/trente-sept` (no GitHub org of that name exists; Trente-sept is the hub org).
- GitHub fork **`Maigre/blackbox-mod`** (fork keeps upstream's name); `main` = untouched mirror, **`maigre`** =
  working branch (integration + working docs).
- **All working docs live in the fork** on `maigre`, under `notes/` (K1000 precedent: the repo is the project
  workspace): `notes/plan.md` (this plan), `notes/re/*.md` (RE findings, prose + addresses, no listings),
  `notes/workflows.md` (→ later `LOOPER.md`), `notes/decisions.md`. They are never part of a `feat/*` PR branch.
  Never in the fork (upstream's request): firmware, patched images, disassembly/decompiled listings, 1010music
  manuals (the manual texts stay local at `/srv/dev/firmware/docs/`).
- The hub keeps the brief/tasks/log, bench cards (`work/t-NNN.md`) and the bench session — and links to the fork's notes.

## Execution order (what happens on approval, in this hub session)

1. **Hub mint** (hub writes are allowed here): `projects/blackbox-mod/{project.md,tasks.md,log/2026.md,notes/2026-10-15-plan.md}`
   + `work/t-NNN.md` bench cards + `config/bench-sessions.md` `## blackbox` + `config/loop.conf` arming; small
   commits (`mint(blackbox-mod): …`, `config: arm blackbox-mod at branch level — Thomas 2026-10-15`), push.
   - `project.md`: `kind: tool`, `status: active`, `organisation: people/trente-sept`, `tags: [music, sampler, looper,
     firmware-mod, reverse-engineering, cortex-m7, ghidra, unicorn, c, midi, perso]`, `hardware: [blackbox-mk1]`,
     milestones `p0-pipeline p1-re p2-slip p3-window p4-looper p5-save p6-extras upstream`, `repos:`
     `github.com/Maigre/blackbox-mod` `role: main` `branch: maigre` `relation: fork`
     `base: {url: github.com/j3threejay/blackbox-mod, branch: main}` `last_reviewed_base_commit: ""`,
     `verify: "ln -sf /srv/dev/firmware/BLACKBOX-3.1.9.bin firmware/BLACKBOX-3.1.9.bin && ./check.sh 2>&1 | tail -1 | grep -q ', 0 failed'"`
     (check.sh always exits 0; declared once P0 proves it on mgr-ran). ≤10-line Brief.
   - `tasks.md` (≤650 chars/row, `@since(2026-10-15) @est @ms @after`): t-001 claude P0 pipeline (toolchain, fork,
     clones, Linux host build, check.sh green, release name, two images) · t-002 Thomas answer the design questions ·
     t-003 bench Gate 0 · t-004 claude P1 RE `@repo(hub)` (A0–A7) · t-005 claude P2 Slip · t-006 bench Gate 2 ·
     t-007 claude first-contact outline `@repo(hub)` · t-008 Thomas send it + open `feat/slip` PR · t-009 claude P3
     (Workflow 1 complete) · t-010 bench Gate 3 · t-011 claude P4 Looper FX · t-012 bench Gate 4 · t-013 claude P5
     Save + shortcuts + `LOOPER.md` · t-014 bench Gate 5 · t-015 P6 backlog (CC, Repitch, direct save, Y Ctl, snap
     start/end; unassigned, split when picked). Bench rows get a `## Bench card` (Setup · Steps · Done when · Report back).
2. **Fork + toolchain** (asked for by Thomas → allowed): `gh repo fork j3threejay/blackbox-mod --clone=false`
   (public, MIT kept), branch `maigre`; `sudo apt install gcc-arm-none-eabi` (sudo prompt), Ghidra 12 tarball to
   `/opt/ghidra`, `uv venv --python 3.12 /srv/dev/venvs/bb` + `unicorn capstone numpy pyghidra`; clones
   `~/Bakery/blackbox-mod` on `maigre`; stock image to `/srv/dev/firmware/`
   (unzip the public 3.1.9 zip, verify sha256).
3. **P0 in the clone**: port `host/build.sh` to Linux (clang-or-gcc, `.so`; `host/dsp.py`, `test_machine.py:279`,
   `test_filter.py:406` pick the platform name), run `RELEASE=1 ./build.sh && python3 patch.py …` and verify
   byte-identity with `docs/blackbox-mod-joebox-1.json`'s `output_sha256` (proves the toolchain), `./check.sh`
   green, release-name commit, cave-only + full images left in `out/` → bench card t-003. Commits carry
   `Refs-37: blackbox-mod#t-001`.
4. Then P1 → P2 as loop/dev sessions on the repo (`/brain-in` there), gates on the bench.

## Verification

- **Toolchain proof**: rebuilding upstream's JOEBOX 1 from source must reproduce `docs/blackbox-mod-joebox-1.json`
  `output_sha256` byte for byte (README says it is); `./check.sh` → "N suites, 0 failed".
- **`test_clipwin.py`** (templates `test_preroll.py`, `test_clip.py`, `test_insert.py`, `test_slice.py`): image
  checks (BL decode of every site, both Pos page copies, untouched stock bytes, size ≤ 786,432) · registration/
  defaults (ids 0x1c8..0x1ca, 3 distinct xml names, labels ≤ 9 chars; Slip formatter renders ±beats.ticks) ·
  *(the `cw_target` / `launch_tick` / split-read / doctored-thunk items below are superseded by A2's latch + mapped
  read; the P2 test list is `re/README.md` §2.9)* · `clipwin_tick` with fake stores/clock/SDRAM
  (no SDRAM → no writes) · `cw_target` vs the Python formula on ~2000 random cases (negative slip, loop > clip, ticks
  before launch) · reader mapping: feature off = bit-identical audio/used/frac to stock; Region=[1000,5000)+slip equals
  stock reads at the mapped positions; split read at the region end = two stock reads concatenated; SP1200 machine
  mode still matches `drop_model` · voice-start chain passes r0–r3/stack/s0, duck's trigger bit still set,
  `launch_tick` recorded · doctored position/length thunks change only the intended register · **whole class-B
  process**: Sync steps land at `cw_target`, wrap at `region_end`, slip change realigns at the next Sync step,
  Loop Len 1/4 wraps every 240 ticks, Region File + Slip 0 + Loop Len Off → trace identical to the unpatched image.
- **Gate 2 recipe (Slip, ~20 min)**: P2 image on the card (BACK+INFO at power-on). Tools: Metro On → Out 1, clock
  120. Reference clip: **not** a Resam of the metronome — the click never reaches the Resam tap and the metronome
  mutes itself while a Resam take is armed (A6). Use a 1-bar factory drum loop (Loop On, Quant 1 bar, Sync 1/4), or
  Resam one bar of a pad playing a click sample on Out 1 into empty pad 1 (Length 1 bar, Rec Quant 1 bar,
  RecToPlay On); the live metronome stays the reference to listen against. Checks: (1) Slip 0 → clicks coincide, no flam; (2) Slip +0.480 (half a beat) → exactly
  between the metronome's; (3) +1.000 → coincide again, accent on beat 2; (4) back to 0 while playing → no dropout,
  heard within one Sync step; (5) −0.480 mirrors (2); (5b) slow turn moves 1 tick, fast turn 60 ticks; (6) PSET Save, power-cycle, reload → same value, same sound;
  (7) TOOLS load readout unchanged. Report: `37 wrap blackbox-mod t-006` with seven yes/no.
- Gates 3/4/5 as in the phase table; each bench card written at hand-off by the machine turn that ships the image.

## Risks

| Risk | Mitigation |
|---|---|
| Sync maths inlined/un-doctorable | per-site thunks on the shared callee; else arch C (anchored mapping in the reader) |
| position is 64-bit fixed point we can't set | arch C never sets stock's position; B4 only doctors inputs |
| Beat Count Auto app-side | v1 explicit Beat Count with Region=Loop; v2 hook |
| cave space (~4.5 KB) | ≈2.5 KB estimate; slip names via stock pointers; Slip Fine deferrable. **Measured**: Region + Loop Len + the Waveform knobs filled it (16 B free on feat/region); overflow goes to bank 2 as leaf code behind `b2_live()` (D-017: Loop Len's take and its window; the sizes as built: `notes/re/README.md` question 5) |
| JOEBOX 1 restart bug | found and fixed in 37.0.2 (D-013); upstream's own fix since JOEBOX 1 rc4, merged in 37.3.2 (D-027). Through P2 no bank-2 dependency (install without `BBEXTRA.BIN`); from P3 Loop Len needs it (D-017): install `BLACKBOX.bin` and `BBEXTRA.BIN` from the same build; fault recorder on; stock reinstall from the card always works |
| doctored clock also feeds launch quantization at the same call | prefer hooking `0x08069C64` if it is target-only; else per-site thunk |
| DJ FX type list not table-driven | Looper in JOEBOX's Master FX slot (`src/master.c` list) with the XY page's touch/X/Y forwarded to it; worst case a dedicated knob page without XY (X/Y on two knobs) |
| Looper DSP needs bank 2 (cave left ≈ 2 KB after the Clip Window) | design the ring/HPF as a bank-2 leaf (Confetti pattern, `BANK2_SRCS`); then `BBEXTRA.BIN` is required → investigate JOEBOX 1's restart bug in `src/b2load.c` first (our unit's Gate 0 data point), or trim bank-1 code (slip names via stock pointers) |
| SDRAM pool too small for a 4-bar ring at slow tempos | **settled (X2)**: the pool has ≤ 1.43 MB free and is the preset-I/O scratch; the ring lives in the FX A Repeater's buffers (16 s int16 stereo = 4 bars ≥ 60 BPM, 20 s when contiguous); cap `Max Len` = frames × BPM / (48000 × 60 × 4) |
| input monitor reaches Out 1 after the FX insert | **settled (A6): it does not** — the recorder mixes the monitor into bus 0 before the pads render, so `Source: Mix` hears it; `Source: In` reads input bus 0 in `duck_block`, where it is raw |
| Save via resample records post-compressor at a few dB less | Tools>Comp Off during Save (the stock manual's own advice), or hook the Resam tap before the compressor (`src/comp.c:237` is at the compressor stage already) |
| bricking | boot code untouched; installer re-verifies; sector 7 (calibration) never written; SD reinstall of stock = recovery |
| warranty/support | affected while modded; stock first before asking 1010music anything |
| hub landing gate | upstream committer within 12 months → every landing is a GATE Thomas taps (fine) |

## Decisions taken with Thomas (2026-10-15)

1. **Slip = one row, accelerating knob** (ticks; slow = 1 tick, fast = 1/64 steps; display beats.ticks). Adds to P2:
   the formatter hook + an acceleration check in RE A3 (fallback: our own step logic on the row).
2. **Region default Auto** → Loop when the pad has loop points, else File.
3. **Loop Len anchors where the music is** (KP3 feel): origin captured at engage, cleared on Off.
4. **Controller = a Launchpad-like pad controller** → stock Global-In note map (36–51 play, 68–83 record, 84–99
   clear; Drum mode pre-mapped); P5 (CC) stays after P4 (Pads LOOP knobs).
5. Already decided by Thomas's brief: fork JOEBOX, PR-compatible per feature; CC optional/later.
6. **Looper release = back to live (KP3)** with a `Hold` knob to latch (Traktor).
7. **Looper Y axis = HPF cutoff** on the looped signal ("if possible" → yes: the SVF high-pass from `src/filter.c`);
   Slip of the caught loop on a knob row; a `Y Ctl: HPF|Slip|Wet` selector only if space allows.
8. **Save to slot v1 = resample via the stock recorder** (N bars of real time, zero file code); direct memory→WAV = P6.
9. Workflow 1's optional "quantize-adjust start/stop" = a snap-to-grid option on the Clip-mode Loop Start/End knobs
   (steps of 1/16 of the region's beat grid), P6.
