# X3 — the data path behind "Region = Loop"

Stock 3.1.9. Found 2026-10-15 (blackbox#t-003), revised the same day after verification (see "Verification").
Four questions:

1. How does a pad parameter reach the Clip engine, and can engine code get Loop Start/End for a Clip pad?
2. What does a Pad Mode change do to the engine object and to the stored loop points?
3. Where are the WAV `smpl` loop points read, what does a load do to the stored loop points, and where is Beat Count
   Auto resolved?
4. What does the source length `0x080636F0` return, and does the clip player wrap on it?

Marks: ✓ means checked by running stock code under Unicorn; *inferred* means a single static read. Offsets are
relative to the object named in each table. Builds on A1 (class-B fields), A3 (the knob forward) and X1 (the
recorder).

## Short answers

1. **Clip pads ignore `0x8f..0x92`, but the pad's other engine object keeps them.**
   - Every pad parameter reaches the engine as message `0x39`, in every mode. The class-B param-set acts on exactly
     40 ids ✓. `0x8f`, `0x91` and `0x92` are not among them. `0x90` only triggers the recompute; its value is
     ignored.
   - Each pad also has a second engine object, the class-H (Sample) object. It reads the same per-cell queue and
     stores Start / LoopStart / LoopEnd / Length / Loop Mode at H `+0xF8 / +0xFC / +0x100 / +0x104 / +0x108`,
     **including while the pad is in Clip mode** ✓.
   - The class-B pad reaches its H through `L+8` ✓. This is the recommended engine-side source.
   - Reading the app store with `fw_setting` from the audio task is memory-safe but can briefly read 0 (details
     below).
   - Neither engine class keeps our own ids `0x1c8..0x1ca` ✓. Those have to come from the app store, or from a
     hook at the single param-set call `0x080685D2`.
2. **Changing Pad Mode never destroys or re-creates anything.**
   - Every pad permanently has both objects, a class-B `'L'` and a class-H `'H'` ✓. Pad Mode only switches which
     one is active.
   - A change runs, in this order: the `0x8b` post, a cell reset (message `0x40`), then a re-post of the whole
     store ✓.
   - **Sample → Clip keeps Loop Start/End and Loop Mode in the store. Clip → Sample or Granular wipes them**
     (Loop Start 0, Loop End = file length, Loop Mode None) ✓.
   - Pad Mode has two ids: `0x8b` `cellmode` (6 entries) and `0x8c` `cellmodeshort` (5 entries, no New Multi). A
     `0x8c` change rewrites the store but never tells the engine ✓.
3. **A load resets Loop Start/End to the whole file; the file's own loop points come after.**
   - On a used pad, the pad load `FUN_080A0AC8` zeroes Start, Length and Loop Start and the app's file length
     (`store+0x20`); it leaves Loop End and Loop Mode alone ✓. An empty pad is rebuilt from the template (all 0) ✓.
   - When the loader has opened the file, its message `0xE {asset, frames}` reaches the app's handler
     **`FUN_080A121C`**. It sets `store+0x20` to the frame count and, because Length is 0 after a load, sets
     **Length and Loop End to the frame count**, then posts `0x8f..0x92` ✓.
   - **Loop Mode `0x8e` survives a load** unless the file's metadata turns the pad into Sample/Granular ✓. A pad that
     had Loop Forward ends up with `0x8e = 1`, Loop Start 0, Loop End = len.
   - The loader parses the header with `FUN_08076AF4`, keeping only the **first** `smpl` loop ✓. If the file has any
     metadata, its message `0x1B` (posted after `0xE`) reaches `FUN_0809D998`, which on a fresh load sets Pad Mode
     from the file, then Loop Mode / Loop Start / Loop End from `smpl`, in Clip mode too ✓.
   - **Beat Count Auto** is resolved in the engine, from the file length and the current BPM (A1). The app first
     replaces Auto by the file's `acid` beat count whenever there is one ✓.
4. **`fw_src_len(src)` returns the frame count of the file's whole data chunk.** That count comes from the loader
   slot, through the provider's info method ✓.
   - It returns 0 when the asset is not open, and `0x10000000` when the slot reports 0 frames ✓.
   - With Sync None, the loop period is that length ✓.
   - When synced, the steps start on the clock grid (Beat Count ticks). Each step plays one Sync step's worth of
     samples from `step × len/n`, unbounded, except the last step, which runs to `len − 1` ✓. So a file shorter than
     Beat Count leaves a gap before the wrap, and a longer one makes the last step overlap the next cycle's first ✓.

## 1. From SetCellParam to the engine

### The post

`SetCellParam 0x0809FA50(app, cell, id, value, c)` handles a pad cell (app cell code `row<<4 | col`, kind bits
8..12 = 0) in four steps:

1. It reads the old value.
2. It writes the store, with one exception: `0x8b` is written later, in the mode block.
3. It posts to the engine: `ParamPost 0x0804C59C(host, row<<8 | col, id, value, [sp] 0, [sp+4] 0)`.
4. It posts `0x66` to the UI.

`host` is the global object at `0x2400A9C0`, which is also the disk manager and the sample provider (§4).
ParamPost builds a 0x18-byte message on its stack and hands it to the engine at `host + 0x9A74` (through
`0x08051738`):

| offset | field |
|---|---|
| `+0x00` | u8 type `0x39` (bytes 1..3 zero) |
| `+0x04` | i32 flag (the `[sp]` argument) |
| `+0x08` | cell code |
| `+0x0C` | id, a full word; both param-sets use only its low 16 bits (`uxth`) |
| `+0x10` | value |
| `+0x14` | u16 slot (the `[sp+4]` argument, stored with `strh`; `+0x16` is 0) |

The engine routes it to the cell's queue. **Both engine objects of the pad read that same queue each block.**
SetCellParam does not filter by mode: A3 ran it with `0x91`/`0x92` on Clip, Sample and Slicer pads, and all
three were stored and posted.

A second way the ids reach the engine is a **full re-post**: `FUN_08099200(app, row, col)` posts every store entry
in store order, then the slice list. It has ten call sites, among them the mode change, the sample load
`FUN_080A0AC8`, the metadata apply `FUN_0809D998`, the recorder's take end and paste. So the engine is re-sent
`0x8f..0x92` many times ✓ (t4, t6).

### The class-B param-set `FUN_08067648`: the 40 ids it acts on

It is reached only from the class-B process, at **`0x080685D2`** (`bl`, the process's message type `0x39` case;
types decoded from the process's jump table at `0x08068018`). Ids `0x00`/`0x01` return at once. Ids above `0xF4` are
compared to `0x15F` and `0x1DD` at `0x080678B8` and otherwise dropped. The rest go through a `tbh` table at
`0x08067682`: 38 live entries; all others go to the return at `0x080678B4`.

| ids | what |
|---|---|
| `0x02`, `0x04` | Level (percent / dB) |
| `0x08..0x0D` | LFO (wave, rate, sync rate, depth, beat sync, key trig) |
| `0x11`, `0xC8` | Res, Filter |
| `0x3C`, `0x3E`, `0x3F`, `0x40` | envelope A / D / S / R |
| `0x47` | Clip Quant Size, recompute |
| `0x4E` | Slice |
| `0x5C` | Pitch |
| `0x62` | Pan |
| `0x64`, `0x15F` | mute |
| `0x69` | VEL Amount |
| `0x6A` | MIDI In |
| `0x8B` | Pad Mode → `+0x29` / `+0x254` |
| `0x8D` | Clip Loop Mode |
| **`0x90`** | **recompute only; the value is ignored** |
| `0x93` | Launch Mode |
| `0x94` | Sync, recompute |
| `0x95` | Output |
| `0x9F`, `0xA0` | Mono / Poly |
| `0xA2` | Slice Seq |
| `0xD0` | Root |
| `0xD2` | Beat Count |
| `0xD9`, `0xDA` | FX1 / FX2 Send |
| `0xDB` | Overdrive |
| `0xF2`, `0xF3`, `0xF4` | PlayThru, Slicer Quant, Slicer Sync |
| `0x1DD` | writes `+0x29` (unregistered, sender not traced) |

Checks:

- **Static:** the jump table decoded from the image (by X3 and again by the verifier).
- **✓ Execution:** the real ctor + param-set, run for every id `0..0x1FF` with values 0/1/2/5 and the pad memory
  diffed. Exactly these 40 ids change the pad or run the recompute. **`0x8C`, `0x8E`, `0x8F`, `0x91`, `0x92` and
  `0x1C8..0x1CA` change nothing.** The verifier's own run of the real L block method (real queue) agrees.

Side fact: posting `0x90` to a class-B pad is a cheap, legal way to force its recompute `FUN_08064A94`. Engine code
can also simply call the recompute itself. Stock relies on this after every load (§3).

### The class-H sibling holds the Sample-mode positions (✓ t2, t3)

The graph builder `FUN_080525F0` creates two objects per pad. It does this once; later rebuilds reuse objects by
sequence number.

| object | type byte `+4` | size | ctor | vtable |
|---|---|---|---|---|
| class-B `'L'` | `0x4C` | 3000 | `0x080640D0` | `0x080D0890` |
| class-H `'H'` | `0x48` | `0x5C4` | `0x08055450` | `0x080D06C8` |

The two objects share the cell id at `+0x18` (`row<<8 | col`). The builder links `L → H` through vtable `+0x18`,
which is `0x0805F22C` for both classes and stores its argument at `+8`. The block method of L, `0x08068C64`, runs
the class-B process and then tail-calls `(L+8)`'s block method, so **H runs right after L, every block, in every
mode**.

H's own queue loop runs whenever `H+0x20` is non-null. The builder sets it, as for L, to the sample map at
`engine + 0x2C74`. H's param-set stores these fields with no mode check:

| H offset | id | meaning |
|---|---|---|
| `+0xF8` | `0x8f` | Start |
| `+0xFC` | `0x91` | **Loop Start** |
| `+0x100` | `0x92` | **Loop End** |
| `+0x104` | `0x90` | Length (a non-zero value also clears `+0x5C0`) |
| `+0x108` | `0x8e` | Loop Mode (0 None, 1 Forward, 2 Bidirect) |
| `+0x29` | `0x8b` | active = Pad Mode ∈ {Sample, Granular} |
| `+0x589` | `0x8b` | Granular |

Executed (t2): with Pad Mode posted as Clip (`H+0x29` = 0), posts of `0x8f/0x90/0x91/0x92/0x8e` landed in those
five fields. Message `0x40` zeroed them, and the re-posted `0x91`/`0x92` restored them.

Two differences from L in how H reads the queue (static, capstone):

- **H checks the cell.** Its `0x39` handler (`0x0805A140`) and its `0x40` handler (`0x08059C5C`) both drop a
  message unless `msg+8 == H+0x18`. L's `0x39` case does not compare; it trusts the queue, which the process looks
  up by `L+0x18` (`FUN_0805F2C8(ctx, L+0x18)`).
- **Flag-1 messages** (multisample zone updates, `[sp]` = 1) also reach these fields. `0x91`/`0x92` are stored and
  then passed to `FUN_080550AC`; the `0x8e` handler (`0x0805AE24`) has no flag test at all. `FUN_0809D998`'s
  MultiSam branch posts `0x8e/0x91/0x92` with flag 1, so on a multisample pad `+0xFC/+0x100/+0x108` hold the last
  zone's values. A mode change clears MultiSam `0xEA` in SetCellParam's `0x8b` block, so a Clip pad never has it.

**H's fields are in source frames.** H's end-of-sample computation (`0x08056E84`) clamps `Length + modulation` to
`fw_src_len` (`0x08056EBC..0x08056F04`). When `H+0x5C0` is set (by message `0x40`, `0x08059D72`; cleared by a
non-zero `0x90`, `0x0805ADD4`) it uses the whole file length instead. *Static.*

Running the builder whole under Unicorn (t3; it stops later, at an unrelated indirect call) gives:

- 16 pads, cells `0x000..0x303`.
- For every pad: `L+8` = the H of the same cell, and `L+0x20` = `H+0x20` = `engine+0x2C74`.
- A 17th class-B object, cell `0x401` (probably the browser preview), is followed by a type-`0x43` object instead.
  **Engine code must check `H+4 == 0x48` and `H+0x18 == L+0x18`** before trusting the link.

### Three ways for our engine code to get LpStr/LpEnd (and our own rows)

**A. H sibling (recommended for `0x91`/`0x92`/`0x8e`).**

```
H = *(L + 8);  if (H && H[4] == 0x48 && *(u32 *)(H + 0x18) == *(u32 *)(L + 0x18)) {
    ls = *(i32 *)(H + 0xFC); le = *(i32 *)(H + 0x100); lmode = *(i32 *)(H + 0x108); }
```

- The audio task writes these fields itself, in queue order with every other parameter the class-B pad sees.
- No hook, no app memory.
- A `0x91` change shows up one block later for code that runs inside L or in `duck_block` (H runs after L).

**B. `fw_setting(APP + 0x1840 + row*0xF0 + col*0x30, id)` from the audio task.** This is JOEBOX's existing pattern:
`src/filter.c` `pad_setting` reads Interp this way on every clip read, and `src/insert.c` / `src/lfo.c` do the
same.

- **Memory-safe ✓ (t11).** `fw_setting` is a lock-free linear scan of `{u16 id; u16; i32 value}` at `store+4`,
  bounded by the count at `+0xA`. The entry array is allocated once (`FUN_08093E6A` only allocates when `+4` is 0)
  by a bump allocator whose free is empty, so it is never freed or moved. Values are single 32-bit stores.
- **Capacity.** The capacity at `+0xC` is fixed by that first allocation: **64 in stock** (`movs r1,#0x40` at
  `0x08093F26` in the defaults and at `0x080949F0` in the first-create path; t13 shows a real type-3 store at 59 of
  64). **JOEBOX patches both to 96** (`patches/duck.py`) because its LFO and insert defaults bring a type-3 store to
  82 (59 stock + 8 `lfo_defaults` + 15 `insert_defaults`). Our three rows make 85 of 96. When a store is full, the
  add `FUN_08093EF6` silently does nothing, and `fw_setting` then returns 0 for the missing id.
- **Not consistent ✓ (t11).** The cell-type defaults `FUN_08093F20` clear every entry (the clear zeroes all
  `capacity` entries while the old count is still visible, then count := 0) and re-add the defaults one by one:
  59 adds for a type-3 pad. During that window a read returns 0 for an id not yet re-added, then its default, which
  is 0 for `0x8b/0x91/0x92`. That function runs on preset load (`FUN_08096AD8`, `FUN_08095910`), pad clear, type
  change and the empty-pad load (14 call sites).
- LpStr and LpEnd are also two separate writes, so a read can pair a new LpStr with an old LpEnd. Code must
  validate (`0 ≤ ls < le ≤ len`) and keep the last good pair.
- The app writes its store *before* it posts, so B is ahead of A by at least one block.
- That the audio task can preempt the app task mid-update is *inferred*: task priorities were not read.

**C. A capture hook at `0x080685D2`** (`bl FUN_08067648`, the class-B process's only call to its param-set; not
patched by JOEBOX, whose nearest hook is the 4-byte `bl` at `0x080685C4`, the `0x3A` case).

- At the site: `r0` = L, `r1` = `*(ctx)` (the clock), `r2` = the message (a 0x18-byte copy at the process's
  `sp+0x30`, layout above), `r3` = `ctx` (the process's second argument). Checked by the prologue read
  (`r7` = ctx, `r8` = `*ctx`) and by the verifier's hook in a real L-then-H run.
- A thunk would copy `0x91`/`0x92`/`0x8e` and **our ids `0x1C8..0x1CA`** into `cw_bank` per pad (id = low 16 bits
  of `+0x0C`), then branch to stock.
- Neither engine class keeps `0x1C8..0x1CA` ✓ (t12: no byte of L or H changes).
- This is the only engine-ordered source for our own rows; option B is the JOEBOX-style alternative for them.

## 2. Pad Mode change (✓ t4: real SetCellParam, real `FUN_0809AA94`, real re-post `FUN_08099200`)

**Ids.** `0x8b` `Pad Mode:` `cellmode` lists Sample, Clip, Slicer, Granular, New Rec, New Multi. `0x8c` `Pad Mode:`
`cellmodeshort` is the same list without New Multi. Registrar dump: `0x0808CF1E`, `0x0808CF32`.

**What `0x8b` does (old ≠ new, mode 0..3).** SetCellParam's tail runs, in this order:

1. posts `0x39 {0x8b}`;
2. if MultiSam is on: zone clean-up, then MultiSam := 0;
3. writes store `0x8b`;
4. **`FUN_0809AA94`** sets the mode defaults (table below);
5. `FUN_0804C664` posts **message `0x40`** (cell reset) to the engine;
6. `FUN_08099200` re-posts every store entry;
7. `FUN_0809A538` posts the mod routes.

New Rec / New Multi take a different branch (`FUN_0809E970` clears the pad's file, store type back to `0x4C`, page
switch). The same value again: only the `0x39` post ✓.

Defaults written by `FUN_0809AA94` (L = the file length the app keeps at `store+0x20`, set by the `0xE` handler, §3):

| new mode | Start `0x8f` | Length `0x90` | Loop Start `0x91` | Loop End `0x92` | Loop Mode `0x8e` | others |
|---|---|---|---|---|---|---|
| Sample (0), Granular (3) | 0 | L | **0** | **L** | **None** | Launch Trigger |
| **Clip (1)** | 0 | L | **kept** | **kept** | **kept** | Quant 1 bar, Sync 1/16, Launch Toggle, Loop Mode `0x8d` On, Beat Count Auto |
| Slicer (2) | 0 | L | kept | kept | kept | Quant None, Sync None, Launch Trigger, `0x8d` Off |

All modes also get two default mod routes.

Executed (t4): a Sample pad with Loop Forward `[24000, 72000)` went to Clip and the store kept `0x8e=1, 0x91=24000,
0x92=72000`. The engine saw `0x8b=1`, reset, then the full list including `0x91=24000, 0x92=72000`. Back to Sample,
the store held `0x8e=0, 0x91=0, 0x92=96000`.

**Workflow consequence:** in workflow (a), going back to Sample mode to re-adjust the loop by ear loses the points.
Two fixes for P3: the planned Clip-mode Waveform knobs on `0x91`/`0x92` (A3), or a guard around `FUN_0809AA94`'s
Sample branch when the pad's Region is Loop.

**`0x8c` (cellmodeshort)** ✓: SetCellParam writes store `0x8b`, runs `FUN_0809AA94` and changes page
(`FUN_0809F9C0`). The engine gets only `0x39 {0x8c}`: no reset and no re-post. Both engine classes ignore `0x8c` ✓
(t1, t2), so the engine stays in the old mode until the next full re-post, for example the sample load that follows
on an empty pad. Where the UI offers `0x8c` was not found: the six `#0x8c` immediates in the UI code look like
widget geometry. *Open.*

**Engine side of the change.**

- **`0x8b`.** On L, `+0x29` = (mode ∈ {1, 2}) and `+0x254` = (mode = 2). If L was active and is leaving, it stops
  through `FUN_080644A8`. On H, `+0x29` = (mode ∈ {0, 3}); if H was active it stops its voices.
- **Message `0x40`.**
  - On L: stops both layers (`FUN_08064650`) and resets the fields to defaults: Loop Mode, synced, Mono, Launch,
    Quant, Sync, slices, Root, Beat Count, Pitch, LFO/env/filter copies. It also sets `+0x29 := 1`; the re-posted
    `0x8b` corrects that.
  - On H: `+0x29 := 0`, voices stopped, `+0xF8..+0x108` zeroed, `+0x5C0 := 1` (whole-file length until the
    re-posted `0x90` clears it).
  - Neither touches the source pointer `L+0x24`.
- **No allocation happens** (builder reuse, t3). A mode change always stops a playing clip.

Side find (recording, `FUN_0809D418` on the recorder's `0x26`):

- With Rec Quant ≠ None and RecThresh Off, Pad Mode := Clip through the same `FUN_0809AA94`, so `0x91`/`0x92` are
  untouched.
- With setting `0x9D` on, Clip Quant Size := the Rec Quant index.

X1 has the details.

## 3. Loading a WAV: loop points, metadata and beat count

### The chain (✓ t13, t14: all real stock code from the load request to the metadata apply)

1. **Pad load `FUN_080A0AC8(app, path, cell, 0)`** (app task).
   - Empty pad (store type `0x4C`): the type change `FUN_0809D308` rebuilds the store as type 3 (defaults, then the
     template's values copied back), so Length, Loop Start and Loop End are 0 ✓ (t14).
   - Used pad (type 3): **Length `0x90`, Start `0x8f` and Loop Start `0x91` := 0** ✓. Loop End `0x92` and Loop Mode
     `0x8e` are left as they were.
   - Both: `store+0x20/+0x24` (the app's copy of the file length) := 0, the pad record's fresh byte
     (`app + 0x8A88 + row*0x78 + col*0x18 + 0xE`) := 1, load request `FUN_0804C310`, full re-post `FUN_08099200`.
2. **Loader task `FUN_080741D0`** (host slot table `host+0x4348`, 0x170-byte slots, asset → slot map at
   `host+0x434C`) opens the file with `FUN_08076AF4(wav, path, meta)`.
   - It keeps the **data size / block align** as the slot's frame count at `+0x50` (i64).
   - It posts `0xE {asset, frames}` to the app. A failed header read posts `0xE` with 0 frames.
   - If the meta has anything (`FUN_08077460` → `meta+0x21C`, set by any parsed `acid`/`smpl` chunk, ✓ hasmeta),
     it then posts **`0x1B {asset}`**.
   - Both go into the same 64-entry ring (`+0x7C50`, write index `+0x8254`, read index `+0x8250`), which the app
     reads in order (`0x0804C760`), so `0xE` is always handled first.
3. **The app's host-message loop `FUN_080A2258`** dispatches through a jump table at `0x080A2998` (index =
   type − `0xE`): `0xE` → **`FUN_080A121C`** (`bl` at `0x080A2974`), `0x1B` → **`FUN_0809D998`** (`bl` at
   `0x080A2A0C`).
4. **`FUN_080A121C(app, asset, frames_lo, frames_hi)`**, the `0xE` handler.
   - It finds the cell that holds the asset (`FUN_0809A9C4`, or a multisample zone through `app+0x3098`).
   - It does nothing if the frame count's low word is 0, or the cell is not a pad.
   - It writes `store+0x20/+0x24` := frames (`0x080A12D0`).
   - **If Length `0x90` is 0** (always true right after a load): **Length := Loop End := frames**
     (`0x080A139A..0x080A13AA`).
   - It posts `0x8f`, `0x90`, `0x91`, `0x92` (flag 0) to the engine, then two UI messages. The `0x90` post makes the
     class-B pad recompute against the now-open file.
5. **`FUN_0809D998(app, asset)`**, the `0x1B` handler (details below): only on a fresh load does it set Pad Mode and
   the file's loop points.

What a load leaves in the store (t13: a 96000-frame pad, then a 50000-frame file):

| before | file | after `0xE` | after `0x1B` |
|---|---|---|---|
| Sample, Loop Forward `[24000, 72000)` | plain PCM (no `0x1B`) | `0x8e=1`, `0x91=0`, `0x92=50000`, `0x90=50000` | — |
| Clip, Loop Forward `[24000, 72000)` | plain PCM | the same, Clip kept | — |
| Sample, Loop Forward | `acid` looping 8 beats, no `smpl` | the same | **Clip**, `0x8e=1`, `0x91=0`, `0x92=50000` |
| Clip, Loop Forward | `acid` looping 8 beats + `smpl` `[10000, 29999]` | the same | Clip, `0x8e=1`, `0x91=10000`, `0x92=29999` |
| Sample, Loop Forward | `smpl` with a root and no loop | the same | Sample defaults: `0x8e=0`, `0x91=0`, `0x92=50000` |
| empty pad (type `0x4C`) | plain PCM | Sample, `0x8e=0`, `0x91=0`, `0x92=50000` | — |
| Sample, Loop Forward | failed read (`0xE` with 0 frames) | unchanged: `0x90=0`, `0x92=72000` stale, `+0x20=0` | — |

So after any successful load, Loop End is the new file's length, and **Loop Mode keeps its old value** unless the
file's metadata makes the pad Sample or Granular. The pad record's asset field is what `FUN_0809A9C4` matches; in
t13 the stubbed load request wrote it, as the real one hands the record to the loader.

### The header reader `FUN_08076AF4`

With a meta, it fills the 0x23C-byte block (✓ t5):

| chunk | what it keeps |
|---|---|
| `acid` (24 bytes, `FUN_08077470`) | `+0x4` = beats (only if ≠ 0); `+0x230` = 1 if the one-shot bit (flags bit 0) is clear. The acid root note is **not** used. |
| `smpl` (`FUN_080774F4` / `FUN_0807754C`) | `+0x0` = MIDI unity note (if ≠ 0). **Only the first loop**: `+0x20C` start, `+0x210` end (the `dwEnd` field as written), `+0x214` = type ≠ 0 (bidirectional), `+0x218` = 1. |
| `cue ` (`FUN_080775A0` / `FUN_080775C0`) | up to 128 offsets at `+0x8 + 4i`, count `+0x208` |
| `inst` (`FUN_0807762C`) | key / velocity ranges `+0x232..+0x238` |

### The metadata apply `FUN_0809D998(app, asset)`

- It copies the asset's meta into `*(app+0xE984)` and finds the pad.
- Multisample pads get per-zone posts with flag 1 (§1). Otherwise:
  - **Root** `0xD0` := file root, if it is 0.
  - **Beat Count** `0xD2` := acid beats, if the store says Auto (0) and the file has a count (stored and posted).
  - **Only on a fresh load** (the record's fresh byte, set by `FUN_080A0AC8`, cleared here):
    - Pad Mode := `FUN_080776A8`: **Clip if the acid chunk is not one-shot, Slicer if there are cues, otherwise
      Sample**;
    - then `FUN_0809AA94` defaults (with the length `0xE` just stored), a full re-post, root and beats again,
      cues → slices;
    - then, **if the file has a `smpl` loop: `0x8E` := Forward or Bidirect, `0x91` := start, `0x92` := end, stored
      and posted, in whatever mode the pad now has, Clip included** ✓.

Executed (t6, real `FUN_0809D998`, `FUN_0809AA94` and `FUN_08099200`):

| file | load | store after |
|---|---|---|
| acid looping, 8 beats, smpl `[24000, 71999]` | fresh | `0x8b=1` (Clip), `0xd2=8`, `0x8e=1`, `0x91=24000`, `0x92=71999` |
| same file | not fresh, store Beat Count Auto | only `0xd2 := 8` (and root); mode and loop untouched |
| same file | not fresh, store Beat Count 4 | 4 is kept |
| whole-file smpl loop `[0, 95999]`, no acid | fresh | Sample, **`0x92 = 95999` (= len − 1, not len)** |

### What stock writes back

Save / Trim `FUN_080A0DD4` → writer `FUN_0807723C`; round trip ✓ t9:

- the pad's Root, Beat Count (0 if Auto) and Pad Mode go into the meta, which is always marked non-empty;
- an `smpl` loop is written **only for a Sample/Granular pad with Loop Mode on**, as `0x91`/`0x92` verbatim (a
  default `0x92` = len is written as `dwEnd` = len);
- **a Clip pad saves `acid` (looping, its Beat Count) and no loop points;**
- a Sample pad with a Beat Count saves `acid` flagged **one-shot**;
- Trim crops cues and loop into `[Start, Start+Length)` (`FUN_0807775C`) **for a Sample/Granular pad only**: the
  crop sits inside that branch. Trim then reloads the pad through `FUN_080A0AC8` (*static*), so the load chain
  above applies to the trimmed file.

**The recorder** (X1 found that `0x0809F4B4` puts the take's beats at `meta+4`):

- the meta it hands the writer has **mode 0** ✓ (t10: a sentinel at `+0x220` is cleared to 0 and never set);
- so a Rec-Quant take's WAV carries `acid` with N beats but **flagged one-shot**;
- the pad that recorded stays Clip with Beat Count N (store side). The same WAV loaded fresh onto another pad comes
  back as **Sample** with Beat Count N (*inferred* from t9 + t10; the full record-then-reload was not run);
- Rec Quant None writes no metadata.

### Beat Count Auto

- The engine resolves Auto in the recompute `FUN_08064A94`: `fw_src_len` (`0x08064B2C`), the source rate and the
  **current BPM**, snapped to a power-of-2 grid (A1's formula, ✓ there).
- Auto survives only for files without an `acid` beat count, or with 0 beats. Otherwise the app replaces it at load
  (above). The recorder replaces it at take end (X1).
- The app has its own frames → ticks conversion `FUN_0804C500` (frames / rate × BPM / 60 × 960). It has two
  callers: the recording-in-progress display (`0x0809A916`) and the recorder's take-end handler (`0x0809F558`),
  where it gives the take length that becomes Beat Count (X1). It does not resolve Auto.

## 4. The source length

**What the source is.** The class-B pad's `+0x24` is not a file but an entry of the engine's sample map:

- The map lives at `engine + 0x2C74`: `[0]` = key map (`host + 0xA684`), `[1]` = 0x240 entries of 0x34 bytes
  (`FUN_08055004`).
- Entry `i` has `+0x20` = provider = the host `0x2400A9C0`, and `+0x24` = asset `i`.
- Entry `+0x28/+0x2C/+0x30` hold per-zone loop start / end / mode, written only for multisample zones.
- Without a provider, the entry is a RAM buffer: `+4`/`+8` data, `+0x10` length, `+0x1C` stereo.

**When `L+0x24` changes.** The recompute calls `FUN_08055054(map, cell, note 60, velocity 100, &L+0x24)`; when the
key map resolves the cell (`FUN_0804BCF0`) it stores `map[1] + idx*0x34`, and when it does not, the recompute
returns early and `L+0x24` keeps its old value. The ctor zeroes it. A scan of the class-B code range
`0x08063000..0x0806A000` (direct stores, `strd`/`stm`, address-takes) finds no other writer; code outside that range
was not scanned. *Static.* So right after a load, `fw_src_len(L+0x24)` can still answer for the **old** entry (its
length, or 0 once that slot is closed) until a recompute runs. After a load, stock's recomputes come from the two
`0x90` posts: the load's own re-post (the new slot may not be open yet) and the `0xE` handler's post (slot open).
*Inferred* from two checked links: a `0x90` post runs the recompute (§1), and both posts happen (t13).

**`fw_src_len 0x080636F0(src)`** calls the provider's vtable `+0x14`. The host's vtable is `0x080E9604`, installed by
the base ctor `0x08070A74`. Its entries:

| vtable slot | method | returns |
|---|---|---|
| `+0x14` | `0x080708FC` | the slot's i64 `+0x50` (frames), or `{−1, −1}` if the asset is ≥ `0x240`, unmapped (`0xFFFF`) or the slot is not open (`+0x2C` = 0) |
| `+0x18` | `0x08070944` (rate) | slot `+0x1C`, the fmt sample rate |
| `+0x20` | `0x0807097C` (channels) | slot `+0x1A`, the fmt channel count |

`fw_src_len` uses only the low word of the i64: negative → 0, zero → `0x10000000`. The stereo getter `0x08063790`
returns `src+0x1C`, cached by the readiness check `0x0806371C`.

| case (✓ t7, real vtable, nothing stubbed; re-run by the verifier) | `fw_src_len` | rate |
|---|---|---|
| open slot, 96000 frames | 96000 | 44100 |
| open slot, 0 frames | **`0x10000000`** | 44100 |
| slot not open / asset unmapped / asset ≥ `0x240` | **0** | 0 |
| open slot, 2³² + 100 frames / 2³¹ frames | 100 / 0 | 44100 |
| no provider, `+0x10` = 12345 | 12345 | — |

So the value is the **whole data chunk in frames at the file's own rate**, independent of Start/Length/loop. All of
`0x8f..0x92`, the `smpl` loop, H's positions and class-B positions (seg `+0x08`) use the same unit.

**The class-B call sites** (all `bl`; none patched by JOEBOX):

| site | function | role |
|---|---|---|
| `0x08064B2C` | recompute | Auto clip ticks, output length when n = 1 |
| `0x08064C5A` | recompute | `+0x23C` = len, step count `+0x240` |
| `0x0806561E` | segment start `FUN_08065550` | `> 0` check |
| `0x08065690` | segment start | **last step's end = len − 1** |
| `0x08065596`, `0x080657C6` | segment start | Slicer / Sync=Slice: last slice length and end |
| `0x080652A8` | `FUN_08065290` | `> 0` check |
| `0x080662F6` | clip reader | reads nothing once pos > len + `0xFF` |
| `0x080668EA`, `0x08066B4A` | render | UI playhead per-mille |

JOEBOX's machine-mode `clip_read` calls `fw_src_len` itself (`src/filter.c`). A virtual-length thunk at the stock
sites does not cover that call.

### The wrap

A1's harness: real voice start + layer render, clip reader stubbed (used = n × rate), 120 BPM (one beat = 24000
samples), Quant 1 bar, Beat Count 4, Launch Toggle, Loop On. Each synced step's segment gets the start position
`step × len/n` (`+0x1FC` frames per step) and **no end bound (0), except the last step, whose end is `len − 1`**
(`0x08065690`). A step's segment plays until the next step starts (then a 256-sample crossfade) or until it reaches
its end bound. The position is never wrapped modulo the length.

| Sync | length | step sources (frames) | what each step plays | at the wrap (next step 0 at sample 384000) |
|---|---|---|---|---|
| 1/4 | 96000 | 0 / 24000 / 48000 / 72000 | one beat each | seamless (✓ t8, t15) |
| 1/4 | 80000 | 0 / 20000 / 40000 / 60000 | steps 0–2: one beat, running 4000 frames into the next chunk; step 3 stops at 79999 | gap (✓ t8) |
| 1/4 | 50000 | 0 / 12500 / 25000 / 37500 | steps 0–2: one beat (into the next chunk); step 3: 12456 samples, to 49999 | **silence for ≈ 11500 samples** (✓ t15, t18: no read from 372584 to 384000) |
| 1/4 | 120000 | 0 / 30000 / 60000 / 90000 | steps 0–2: one beat, then cut by the next step (6000 frames of each chunk never play); step 3: ≈ 30000 samples, to 119999 | **step 3 keeps playing ≈ 6000 samples on top of the next step 0** (✓ t16, t18: two reads per block from 383976 to 390120) |
| None | 80000 / 96000 | — | n = 1: the only step is the last, bounded at len − 1 | next start 79743 / 95743 samples later (len − 257): **wraps on the length** (✓ t8; the verifier's 50000 / 77777 give len − 257 too) |

So with Sync on, the length shapes playback through `+0x1FC`, the step count and the last step's end; the period is
the clock grid (Beat Count). With Sync None it is also the period.

## What it means for the Clip Window (*inferred*, for P2/P3)

**Region source.** Use LpStr / LpEnd / Loop Mode from the class-H sibling (A above); keep the app store as a
fallback.

**Region Auto rule.** Stock leaves LpEnd in these shapes:

- **0**: a pad without a file (template), the window between the load request and the `0xE` handler, a store being
  rebuilt, or a failed header read (which also leaves `+0x20` and Length at 0);
- **len**: the Sample/Granular default, and **every successful load** (the `0xE` handler);
- **len − 1**: a whole-file `smpl` loop;
- **arbitrary**: the user's points or a `smpl` import;
- **stale, from another file**: not through a load (corrected, see "Verification"), but through X1's record-over
  route: Clear then record keeps every store entry, so the old file's `0x8e/0x91/0x92` meet the new take (X1, ✓
  there for "store untouched"; not run here for the loop ids).

Loop Mode `0x8e` alone does not say the user set a loop: it survives Sample → Clip, a plain load and a load that
resolves to Clip (t13) or Slicer (same "kept" defaults, t4), and is reset to None only by the Sample/Granular
defaults (mode change, or a fresh load whose metadata resolves to Sample). It is set by the `smpl` import. So Auto should mean Loop only when
**Loop Mode `0x8e` ≠ None** and `0 ≤ ls < le ≤ len`, **and not when `ls == 0 && le ≥ len − 1`**. That last exclusion
is load-bearing: it is what keeps a Loop-Forward pad that just received a new file (`0x8e=1`, `[0, len)`) on File.
The stale record-over case passes this rule; P5's record-over should reset the pad's loop points or Region.

**The length a thunk sees.** `fw_src_len(L+0x24)` can describe the old file, or be 0, between a load and the `0xE`
handler's recompute. A Clip Window thunk must treat 0 as "not ready", re-validate the region against the current
length every time, and keep reading the region from H (which receives the `0xE` posts in the same order).

**Beat Count with Region.** A virtual length at `0x08064B2C` / `0x08064C5A` / `0x08065690` makes Auto follow the
region (plan item 8). Auto snaps to a power-of-2 beat grid, so a region that is not a power-of-2 beats long plays
like the 50000 or 120000 rows above: steps run into the next chunk and the last one leaves a gap, or chunks are cut
and the last step overlaps the next cycle. The Clip Window reader therefore sees positions past the region end (up
to one Sync step beyond it) and must decide what they return: stock reads silence past `len + 0xFF`; wrapping inside
the region is the alternative. An imported `acid` count is
explicit and refers to the **whole file**; a file carrying both `acid` beats and an `smpl` loop (typical DAW
exports) would map the whole-file count onto the region. P3 needs a rule here, for example: ignore an imported
count when Region resolves to Loop, or document it.

**Saving.** A Clip pad saved or trimmed by stock loses its loop points in the file (they stay in the preset), and
Trim does not crop a Clip pad. That is stock behaviour and should be documented for workflow (a).

**Our own rows** (`0x1C8..0x1CA`) are invisible to both engine classes. Read them with `fw_setting` (JOEBOX style)
or capture them at `0x080685D2`. They need three free entries in the pad store: JOEBOX's 96 leave 14.

## Open points

- Where the UI posts `0x8c` (cellmodeshort), and whether that can happen on a pad with a file. A USB peek of
  `L+0x29` / `H+0x29` after using that list on a loaded pad would settle it.
- The task priorities that make option B racy. JOEBOX's existing store reads from the audio task suggest it is fine
  in practice.
- Whether the record-over route really keeps `0x91/0x92/0x8e` (X1 ran the store for `0x90`/`+0x20` only), and
  whether a finished take is ever opened by the loader before a preset reload (which would run the `0xE` handler).
  A Unicorn run of X1's `r2/t_len.py` with the loop ids added, or a dev-build peek of the store after Clear + record,
  would settle both.
- Whether anything outside `0x08063000..0x0806A000` writes `L+0x24`. A whole-image scan for stores at `+0x24` on
  objects of vtable `0x080D0890`, or a hardware watch of the field across a load, would settle it.
- The overlap at the wrap (Sync on, file longer than Beat Count) is shown by the render's reads and mix calls; it
  was not listened to on hardware.

## Verification

Independent verifiers re-checked the first version. Each point was settled again here with a fresh check:

| point | verdict | how it was settled |
|---|---|---|
| 40 ids of the class-B param-set; L/H pairing; H fields; store accessors; `0x080685D2`; mode change; `0x8c`; loader; metadata apply; Save; `fw_src_len`; segment ends (X3-1…X3-13) | confirmed by the verifiers | their own decodes and runs; `fw_src_len`'s table re-run here (`vx3/srclen.py`) |
| "Loading a WAV onto a used pad leaves a stale Loop End" (X3-14) | **wrong, corrected** | the static read stopped at `FUN_080A0AC8`. The `0xE` handler `FUN_080A121C` sets Length and Loop End to the new length. t13 runs the whole chain (load → `0xE` → `0x1B`) on real code; jump table at `0x080A2998` decoded |
| "Where `store+0x20` is written: not traced" | **closed** | `FUN_080A121C`, `0x080A12D0` (t13) |
| "`0x1B` dispatch: no direct `bl`" | **wrong, corrected** | `bl FUN_0809D998` at `0x080A2A0C`, case `0x1B` of the same table |
| "Store capacity 96" | **corrected: 64 in stock, 96 in JOEBOX** | capstone at `0x08093F26` / `0x080949F0`, `patches/duck.py`; t13's real defaults allocate 64 |
| Loop Mode survives a load | confirmed, refined | t13: plain and Clip-resolving loads keep `0x8e`; a load whose metadata resolves to Sample resets it |
| Hook ABI at `0x080685D2`; ParamPost layout | confirmed | process prologue and the `0x39` case (jump table `0x08068018`); ParamPost's `strh` at `+0x14`; `uxth` of the id at `0x08067652` |
| H checks the cell; L does not | confirmed | H `0x0805A140`/`0x08059C5C` compare `H+0x18` with `msg+8`; L's `0x39` case branches straight to the call |
| Flag-1 posts overwrite `H+0x108` | confirmed | `0x0805AE24` has no flag test; `FUN_0809D998`'s MultiSam posts use flag 1 |
| "Only the last synced step has an end bound; the others play a full step from `step × len/n`" | confirmed | t15/t16: end 0 on steps 0–2, `len − 1` on step 3; one beat played per step |
| "With a longer file the last step is cut by the next grid start" | **not confirmed** | t16/t18 at len 120000: step 3 keeps its own count and end, and the render reads it and the next step 0 in the same blocks for ≈ 6000 samples. It overlaps, it is not cut |
| `L+0x24` refreshed only by the recompute | confirmed in the class-B range | `FUN_08055054` stores through the pointer the recompute passes; range scan as stated in §4 |
| Trim's crop only for Sample/Granular | confirmed | `FUN_080A0DD4`: `FUN_0807775C` sits inside the mode 0/3 branch |
| H clamps Length to `fw_src_len`; `+0x5C0` | confirmed | capstone `0x08056EBC..0x08056F04`, `0x08059D72`, `0x0805ADD4` |

## How this was checked

Unicorn on the stock image only. Scripts are in `/srv/dev/firmware/re-scratch/x3/` and `x3/v2/` (the re-checks),
outside git. They reuse A1's `stock.py` / `padb.py` / `render.py` / `vstart.py` (copied) and X1's harness module
(imported read-only). The verifiers' scripts are in `/srv/dev/firmware/re-scratch/vx3/`.

| script | what it runs | what it shows |
|---|---|---|
| `t1_pset_sweep.py`, `t1b_pset_values.py` | real class-B ctor + param-set, every id `0..0x1FF`, values 0/1/2/5, pad memory diffed | exactly the 40 ids above; equal to the `tbh` table at `0x08067682` (decoded from the image) plus `0x15F`/`0x1DD` |
| `t2_classh.py` | real class-H ctor + process `FUN_080596B0`, messages through the real per-cell queue | `0x8f..0x92`/`0x8e` kept while in Clip mode; message `0x40` zeroes them; re-post restores; `0x8c` ignored |
| `t3_builder.py` | the graph builder `FUN_080525F0` whole, allocator stubbed | per pad `L+8` = H of the same cell; the 17th class-B object is not followed by an H |
| `t4_modeswitch.py` | real SetCellParam, `FUN_0809AA94`, `FUN_08099200`, store accessors; posts stubbed and recorded | the defaults table, the post order, the `0x8c` path |
| `t5_wav.py` | real header reader `FUN_08076AF4` on synthetic WAVs (FatFs open/read/seek stubbed to serve memory) + the meta getters | the meta fields and the mode rule |
| `t6_meta_apply.py` | real `FUN_0809D998` on a pad store, fresh and not fresh | the metadata table in §3 |
| `t7_srclen.py` | `fw_src_len`, rate getter, against the real host vtable on a fake slot table | the §4 table |
| `t8_wrap.py` | A1's render harness with lengths 80000 / 96000, Sync 1/4 and None | the wrap rows for those lengths |
| `t9_roundtrip.py` | real chunk writer `FUN_0807723C` → real reader | what Save writes for each mode |
| `t10_recmeta.py` | X1's run of `0x0809F4B4`, logging the meta handed to the writer | beats set, mode field 0 |
| `t11_store_race.py` | real `FUN_08093F20`, sampled at each of its 59 adds | the transient 0s and the fixed entry pointer |
| `t12_ownids.py` | both engine classes fed `0x1C8..0x1CA` | no byte changes |
| `v2/t13_load_chain.py` | real defaults `FUN_08093F20`, real `FUN_080A0AC8` → real `FUN_080A121C` → real `FUN_0809D998` (header parsed by the real reader); UI posts, ParamPost, path and load-request helpers stubbed | the load table in §3, capacity 64, the four `0xE` posts with flag 0 |
| `v2/t14_empty_pad.py` | the same on a type-`0x4C` pad, with the real type change `FUN_0809D308` | Length / Loop End = len after `0xE` |
| `v2/hasmeta.py` | real reader + `FUN_08077460` | which files make the loader post `0x1B` |
| `v2/t15_wrap_steps.py`, `v2/t16_wrap_overlap.py`, `v2/t18_wrap_reads.py` | A1's render harness, lengths 50000 / 96000 / 120000, Sync 1/4; per-segment state each block; every clip-reader call and mix call counted | the step bounds and the 50000 / 120000 wrap rows |
| `v2/jt_app.py`, `v2/jt_l.py`, `v2/jt_h.py` | decode the app's host-message table `0x080A2998`, the class-B process table `0x08068018`, class H's `0x0805971C` | the `0xE`/`0x1B` dispatch, the `0x39`/`0x40` cases |

Static reads (Ghidra decompile/listing plus capstone):

- SetCellParam's pad branch and tail; ParamPost;
- `FUN_08099200`, `FUN_0809AA94`, `FUN_08093E9C`/`ECC`/`EF6`/`E6A`/`E44`, the capacity immediates at `0x08093F26` /
  `0x080949F0`;
- the class-B process's message switch (`0x39`, `0x40`, `0x6F`) and the call site `0x080685D2`; class H's
  param-set, its `0x39`/`0x40` cell checks, its `0x40` reset and the length clamp `0x08056E84`;
- the builder's pad loop; vtables `0x080D0890` / `0x080D06C8` / `0x080E9604`;
- the WAV reader and writer and their meta accessors `0x08077414..0x08077858`;
- `FUN_080741D0`, the app ring reader `0x0804C760`, `FUN_080A2258`'s dispatch, `FUN_080A121C`, `FUN_0809D998`,
  `FUN_080A0AC8`, `FUN_080A0DD4`, `FUN_0809D418`;
- `FUN_08055054` and the class-B range scan for writers of `+0x24`;
- every `bl` to `0x080636F0` (`findbl.py`); every store write of `0x91`/`0x92` (decompile and `movs r1,#0x9x` scans).
