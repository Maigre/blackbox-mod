# A5 — the DJ FX framework, the XY screen and the Repeater

Stock 3.1.9 (`BLACKBOX-3.1.9.bin`). Found 2026-10-15 (loop turn, blackbox#t-003). Revised the same day after an
independent verification pass (see **Verification** at the end).

**Short answer.** The DJ FX are table-driven at every layer:

- name lists;
- an index→class byte table per slot;
- a fixed pool of pre-built effect objects (two per class) behind one class-id switch;
- a per-type `{X id, Y id}` table for the XY pads.

Every effect implements one small virtual interface. FX A and FX B are two sub-slots of one engine module that runs
on **Out 1 only**, after the FX1/FX2 returns and the master EQ, **before** JOEBOX's Master FX, compressor and clipper.

On the XY pad, a finger sends param `0x15` = 1/0 (momentary), the stock **Hold** buttons send `0x1a`/`0x1b` (latch),
and X and Y send ordinary param ids through the generic msg `0x6e` forward.

The Repeater captures into a 2 s float buffer and replays the first `len` of it on each grid step of its length. The
capture start depends on the touch:

- a touch more than 384 samples after a grid line waits for the **next** line;
- a touch within 384 samples after one starts **at once, from the current tick** (off-grid), not from the line.

A Looper fits **FX A**. The cheapest engine route reuses the Repeater instance and its 3.84 MB of SDRAM (the Munchi
pattern). It needs:

- a cave hook in the slot setter that **latches the FX A index**: no app store holds the DJ FX type;
- a relocated FX A axis table: the bytes after it are a vtable header, not free space;
- three or four wrapped Repeater vtable entries.

## 1. Type lists, classes, and how a slot gets its effect

### The lists (app side)

| id | label | xml | names (table) | count | registered at |
|---|---|---|---|---|---|
| `0x18` | `FX A:` | `fxalgolivea` | Repeater, Gater, Filter (`0x080EB5B8`) | 3 | `bl 0x0808C594` |
| `0x19` | `FX B:` | `fxalgoliveb` | Crusher, Filter, Echo, EchoHP, Flanger, Echo2 (`0x080EB5A0`) | 6 | `bl 0x0808C5A8` |

The two slots have **different** lists; only Filter is in both. `Enabled` is **not** a DJ FX string: it is entry 0
of `0x71` "MIDI Out:" (`midithrumodetype`: Enabled / MIDI In Thru / USB Dvc Thru). FX A's name table is followed at
once by that MIDI list (`0x080EB5C4`), so a longer FX A list needs a new table (replace the registration call, as
`munchi_register` does for `0x197`).

The params the effects use (all from the stock registrar):

| id | label (xml) | values |
|---|---|---|
| `0x10` / `0x11` | Cutoff (`cutoffFx`) / Res | |
| `0x13` | Wet/Dry (`wet`) | |
| `0x16` / `0x17` | Bit Depth / Rate Reduc | |
| `0x1c` | Length (`repeatlen`) | 1/4, 1/8, 1/16, 1/32: names `0x080ECBD8`, beats `0x080ECBC8` = 1, 0.5, 0.25, 0.125 |
| `0x1d` / `0x1e` | Length (`gaterlen`, same lists) / Duty (`gaterduty`) | |
| `0x2b` / `0x2c` | Phase / Feedback (`flangfb`) | |
| `0x2d` / `0x2e` | Delay (`echodelay`) / Delay2 (`echo2delay`) | 11 / 6 values |
| `0x2f` / `0x30` | Feedback (`echofb`) / HPF (`echohpf`) | |

`0x15`, `0x1a` and `0x1b` are **not registered**: they are the touch/hold commands below.

### Engine classes

A class registry (12-byte `{u8 id, name, tag}` records at `0x2401FCAC`, filled by code at `0x08094C64`) names
`fxbitcrusher` `0x3a`, `fxecho` `0x3b`, `fxecho2` `0x3c`, `fxfilter` `0x3d`, `fxflanger` `0x3e`, `fxgater` `0x3f`,
`fxrepeater` `0x40` (and `looper` `0x15`, for A7).

Index → class uses two byte tables:

- **FX A `0x080DF6D8` = `40 3f 3d`**, plus one padding byte `0x080DF6DB` = `00`;
- **FX B `0x080DF6D0` = `3a 3d 3b 3b 3e 3c`**, plus two padding bytes.

Echo and EchoHP are the same class (`0x3b`). They differ only in the XY Y axis (`0x2f` Feedback vs `0x30` HPF).
Echo2's class `0x3c` lands on the **same** pool switch case as `0x3b` (both `tbb` entries go to `0x0806CDA8`), so all
three Echo types share one pair of echo instances.

### The pool (no `new`)

A static singleton holds **two pre-built instances of each class**: getter `FUN_0806ccf8`, object at `0x24015268`,
guard `0x24015260`, ctor `FUN_0806cc80`, `0x648` bytes.

| class | instances at pool + | ctor | size | vtable | in-use flags |
|---|---|---|---|---|---|
| Repeater `0x40` | `0x000`, `0x0d8` | `FUN_0806d2b8` | `0xd8` | `0x080DF580` | `+0x638`, `+0x639` |
| Echo `0x3b`/`0x3c` | `0x1b0`, `0x280` | `FUN_0806b3e0` | `0xd0` | `0x080DF360` | `+0x63a`, `+0x63b` |
| Flanger `0x3e` | `0x350`, `0x3a8` | `FUN_0806c0dc` | `0x58` | `0x080DF470` | `+0x63c`, `+0x63d` |
| Filter `0x3d` | `0x400`, `0x474` | `FUN_0806bca8` | `0x74` | `0x080DF3E8` | `+0x63e`, `+0x63f` |
| Crusher `0x3a` | `0x4e8`, `0x538` | `FUN_0806ae00` | `0x50` | `0x080DF2D8` | `+0x640`, `+0x641` |
| Gater `0x3f` | `0x588`, `0x5e0` | `FUN_0806c748` | `0x58` | `0x080DF4F8` | `+0x642`, `+0x643` |

- **Buffers**: `FUN_0806cd40(pool)` allocates them once from the permanent SDRAM allocator. It is called by the graph
  builder `FUN_080525f0` at `0x08052CA6`, and flag `+0x644` = done. Executed, it takes **9,236,480 B** in all:
  - Repeater 4 × 1,536,000 + 4 × 384,000 = 7,680,000;
  - echo 4 × 385,024 (`0x5E000`);
  - flanger 4 × 4,096.
- **Next pointers**: every instance's `+8` (next) is 0 after construction (executed, all 12).
- **Acquire** `FUN_0806cd80(pool, class)`: `r1` = class − `0x3a`, then `cmp r1, #6` and a `tbb`. It takes the first
  free instance of the pair, sets its flag and calls its `vt+0x78` (reset). Callers: `0x0806E06C`, `0x0806E0F0` (slot
  swap), `0x0806E3A0` (`FUN_0806e368`).
- **`0x0806CDA4` (4 bytes that return 0) is a shared exit.** It serves an unknown class (`r1` > 6 unsigned) and also
  "both instances busy" for a known class:
  - the `bne`s at `0x0806CDB6` (Echo), `0x0806CDD0` (Filter), `0x0806CDEA` (Flanger), `0x0806CE04` (Repeater),
    `0x0806CE1A` (Crusher);
  - the Gater path falling through at `0x0806CDA2`.

  On every path `r0` = pool and `r1` = class − `0x3a`.
- **Release** `FUN_0806ce7c(pool, obj)`: calls `obj→vt+0x78`, then clears the matching flag. A pointer that matches no
  pool slot is only reset (safe for a foreign object). There are 13 call sites.

### The DJ FX module and its two sub-slots

- **Container** (`engine + 0x28D90`, vtable `0x080DF670`):
  - Built in the engine ctor (`FUN_0806e244`, `bl` at `0x080515BA`).
  - Its process `FUN_0806dd0c(c, ctx)` runs `count` (`+0x180`, u16) sub-slots, then its own `next` (`+8`).
  - It has 8 sub-slots of `0x2c` bytes from `+0x20`. The ctor sets `count` = 4 and the graph builder sets it to **2**
    (`FUN_0806e35c`). `+0x182` = bypass.
- **Sub-slot** (vtable `0x080DF608`): `+0x18` channel (**A `0x30300`, B `0x30400`**), `+0x1e` output buffer (0 = Out 1),
  `+0x20` current effect, `+0x24` outgoing effect, `+0x28` its countdown. Its `+8` is 0 (executed). Process
  `FUN_0806e190(sub, ctx)`:
  1. Drains the channel's queue: every type-`0x39` record (id at `+0xc`, value at `+0x10`) goes to the **slot setter
     `FUN_0806e12c(sub, id, v)`**.
  2. Counts the outgoing effect down by the block's frames and releases it at ≤ 0.
  3. Runs the current effect's process **only if `effect→vt+0x70` (active) is true**.
  4. Then tail-calls **its own** `next` (`0x0806E208` → `0x0806E1F0`), whether or not the effect ran.
- **Slot setter `FUN_0806e12c`** (a `tbb` on id − `0x15` at `0x0806E134`):

| id | target | action |
|---|---|---|
| `0x15` | `0x0806E156` | `effect→vt+0x6c(v ≠ 0)`: finger down/up |
| `0x18` | **`0x0806E174`** | bound check `v` ≤ 2 (4 bytes; above it returns), then at `0x0806E178` (8 bytes) the class byte is loaded from the table (literal `0x0806E188` → `0x080DF6D8`) and a `b.w 0x0806E048` swaps |
| `0x19` | `0x0806E150` | bound check `v` ≤ 5, then the same at `0x0806E180` with literal `0x0806E18C` → `0x080DF6D0` |
| `0x1a`, `0x1b` | `0x0806E140` | `effect→vt+0x74(v ≠ 0)`: Hold |
| other | `0x0806E168` | `effect→vt+0x64(id, v)`: the effect's own params |

- **Swap `0x0806E048(sub, class)`** (uses only `r0`, `r1`):
  1. If the class equals the current one (`*vt+0x60()`), nothing happens: no swap, no reset.
  2. Otherwise it **acquires** the new instance first.
  3. It copies the channel and the output index. When `vt+0x4c`/`vt+0x50` are the defaults (`0x08046A0D`, which
     stores `+0x18`, and `0x08046A11`, which stores `+0x1e`), it inlines those stores; otherwise it calls them.
  4. It **releases** any previous outgoing effect.
  5. The old current effect becomes outgoing with countdown 256. The outgoing effect is **not processed**, so a type
     change cuts the old effect at once. It is released 256 frames later.

  Class 0 empties the slot. Because acquire runs before release, a return to a class within 256 frames gets the
  **second** instance: executed, Repeater → Gater → Repeater lands on `pool + 0xd8` = **`0x24015340`**. Acquire and
  release both call `vt+0x78`.
- **Defaults at build**: sub-slot 0 = Repeater, sub-slot 1 = Crusher (`FUN_0806e368` from `0x08052CE4`/`0x08052D18`,
  its only two callers). `FUN_0806e368(c, idx, class)` is a class-id setter with the same swap logic.

  The index setter `0x0806E12C` has one caller (`0x0806E1D0`, the sub-slot process). So **every runtime type change
  is a `0x18`/`0x19` message through `0x0806E174`/`0x0806E150`**.

### The effect interface (every DJ FX vtable, `0x80` bytes)

| vt+ | role | notes |
|---|---|---|
| `0x0c` | process(effect, ctx) | the Repeater's process tail-calls `effect+8` when non-zero (`0x0806D8AC`, `0x0806DAA4`), but it is always 0 here; the sub-slot runs its own `next` |
| `0x10`..`0x5c` | module base (shared with every engine module) | `+0x18` set_next, `+0x4c`/`+0x50` set channel / output |
| `0x60` | class() → pointer to the class byte | the byte sits at **vt+0x7c** |
| `0x64` | set_param(id, v) | every id the slot does not handle itself |
| `0x6c` | finger(v) ← `0x15` | base `0x0806E540` for all six |
| `0x70` | active() | base `0x0806E518`: finger ‖ hold ‖ fading out ‖ `+0x30` ≠ 0 |
| `0x74` | hold(v) ← `0x1a`/`0x1b` | base `FUN_0806e490`; Repeater `FUN_0806d134`, Echo `0x0806B2A4` extend it |
| `0x78` | reset | called on acquire and on release |

The Repeater's words: `0x080DF58C` (+0x0c) = `0x0806D859`, `0x080DF5E0` (+0x60) = `0x0806D005`, `0x080DF5E4`
(+0x64) = `0x0806D0B9`, `0x080DF5EC` (+0x6c) = `0x0806D09D`, `0x080DF5F0` (+0x70) = `0x0806D0A1`, `0x080DF5F4` (+0x74)
= `0x0806D135`, `0x080DF5F8` (+0x78) = `0x0806D03D`, `0x080DF5FC` (class) = `0x40`. Its `+0x6c`/`+0x70` are `b.w` to
the base methods.

**Base object fields** (base ctor `FUN_0806e4dc`, vtable `0x080DF6E4` from literal `0x0806E504`):

- `+0x04` type byte, `+0x08` next (0);
- `+0x18` channel (`0xFFFF` until set), `+0x1e` output buffer index;
- **`+0x20` finger**, **`+0x21` hold**;
- `+0x24` fade-in counter, `+0x28` fade-out counter (both from 256), `+0x2c`/`+0x30` tail length.

The methods:

- `finger(v)`: when Hold is on, only store `v`. Otherwise `v` = 1 starts a 256-sample fade-in and `v` = 0 a fade-out,
  each resuming from where an interrupted opposite fade stopped.
- `hold(v)`: the same rule with the two flags swapped.
- Wet-path helpers: `FUN_0806e5a0(obj, ctx, buf, &L, [sp] &R)` gives the wet buffer (a scratch buffer while fading),
  `FUN_0806e660` is the engage crossfade into the output, `FUN_0806e594` resets. Scratch buffers are
  `ctx + 0x151fc + i×0x14` (`FUN_0805f3a4`).

### Can a type be added by extending a table and a count?

**For FX A, one type, yes.** These are all the stock places that know the list:

| what | where | stock | room |
|---|---|---|---|
| names + count | registration `bl 0x0808C594` | 3 names at `0x080EB5B8` | none: replace the call (Munchi style) |
| index bound | `cmp r2, #2` at `0x0806E174` | 2 | patch to `#3` (2-byte Thumb imm), or hook (§5) |
| index → class | `0x080DF6D8` | `40 3f 3d` | **one byte, `0x080DF6DB`** (padding) |
| XY axes | count `0x080EEA78`, entries `0x080EEA7C` | 3 × `{u16 X, u16 Y}` | **none**; relocate (below) |
| class → instance | pool switch `FUN_0806cd80` | `0x3a..0x40` | new class: hook `0x0806CDA4`, minding the shared exit |

**The bytes after the two FX A tables are vtable headers, not free space.** All 14 vtables checked in the image are
preceded by 8 zero bytes: an Itanium offset-to-top word and a null RTTI pointer (no RTTI in this build).

- `0x080DF6DC..0x080DF6E3` is the header of the **base-effect vtable `0x080DF6E4`** (literal `0x0806E504`, stored by
  the base ctor at `0x0806E4F8`).
- `0x080EEA88`/`0x080EEA8C` are the header of the **app-store vtable `0x080EEA90`** (literal `0x0809041C`, stored into
  every store object at `0x0809037E`; entry 0 = `0x0808FC91`).

No reader of either header was found: no `dynamic_cast` or `typeid`, and the `[rX, #-8]` loads near the store code
are store-field accesses. But that is not proven, so the **safe move is to relocate FX A's axis table** (count +
4 entries, 20 bytes) into the cave. Patch the four literal words that point at it, which are the only ones in the
image:

- `0x080B1E44` (count) and `0x080B1E48` (entries), for `FUN_080B1DE0`;
- `0x080B20B8` (count) and `0x080B20BC` (entries), for the view handler, including its `0x15`/Hold rest paths.

The UI's bound checks all read the count through these literals, so the relocated count covers the view.

**FX B has no room**:

- Its axis entries end where FX A's count begins.
- Its class table has only 2 padding bytes (`0x080DF6D6`, `0x080DF6D7`).
- Its names are followed by FX A's.
- Extending it means relocating the tables (literals `0x080B1E4C`/`0x080B1E50`, `0x080B20C4`/`0x080B20C8`,
  `0x0806E18C`) and patching `cmp r2, #5` at `0x0806E150`.

Unlike the FX1 delay (one engine object whose behaviour JOEBOX switches on the stored type), each DJ FX type is its
own object behind a vtable. A new type is a new object, or a stock instance whose vtable entries are wrapped (§5).
No JOEBOX patch touches any of these sites.

## 2. Where FX A/B sit in the audio path

The engine is a set of singly linked module chains (`+8` = next; each process tail-calls `next→process`). Running the
graph builder `FUN_080525f0` whole gives two chains:

- **Main** (root at `engine + 0xD590`, reached through `engine + 0xFC00`). In order:
  - the head module, then the WAV recorder (the `0x2b0` module, vtable `0x080D07AC`, block method `0x0806201C`, ctor
    `FUN_08061c04`);
  - 16 pad modules (chans `0x1RRCC`) and the per-pad modules;
  - **FX2 reverb** (`0x1a0`, chan `0x30100`, writes bus 11), then **FX1 delay** (`0x224`, vtable `0x080D0660`, chan
    `0x30000`, writes bus 10);
  - the stock **looper** (class `0x15`, vtable `0x080D0190`, chan `0x400`; A7's subject), then a type-`0x2d` module
    (vtable `0x080D01F8`, chan `0x400`), then the end.
- **Out 1 tail**: **master EQ** → **DJ FX container** (`engine + 0x28D90`) → end. The EQ is `engine + 0x28D8C`: ctor
  `FUN_08046a74`, vtable `0x080CFC40`, process `0x08047600`, ids `0x118`–`0x12d` (`eqgain`…`eqbypass`), chan
  `0x30200`.

The FX rows are channel byte 1: delay 0, reverb 1, EQ 2, **DJ A 3, DJ B 4**. `SetCellParam` (`0x0809FA50`) maps cell
`0x3R0` to the app store at `APP + 0x2FC0 + R×0x18` (family `(cell >> 8) & 0x1f` = 3, row `(cell & 0xff) >> 4`).

**But no app store holds the DJ FX type.** APP init builds the four row stores at two sites (decompile around the
`FUN_08094a1c` calls with `0x26`, `0x4b`, `0x36`, `0`):

- row 0 (delay) with type `0x26`;
- row 1 (reverb) with `0x4b`;
- row 2 (EQ) with `0x36`;
- **row 3 (`APP + 0x3008` = `0x24023090`, DJ A) with type 0**.

The cell-type builder `FUN_08093F20` has no case 0, so DJ A's store stays empty. No builder call was found for row 4
(`APP + 0x3020`, DJ B). All 231 calls of the store-add `FUN_08093EF6` sit in `FUN_08093F20` and
`FUN_0809481C`, and none adds `0x18` or `0x19`.

For family 3, `SetCellParam` sets **`APP + 0x2C` = (v ≠ 0)** for id `0x1a` and **`APP + 0x2D`** for `0x1b`. Then, for
every id, it calls the update-only `FUN_08093ECC`, which is a no-op when the id is absent. So:

- `fw_setting(0x24023090, 0x18)` **always returns 0**;
- the type lives only in the engine (current effect's class) and in the view (`+0x8CC` A, `+0x8D0` B);
- both start at index 0 at boot: the view is built once by the UI ctor `FUN_0808BE4C` and its ctor zeroes both
  words (`0x080B22F8`/`0x080B22FC`); the graph builder installs Repeater/Crusher;
- so the DJ FX type is **not persisted** (inferred from these reads; not checked on the unit).

The tick `FUN_08053164` runs, in this order:

| address | step |
|---|---|
| `0x0805318C` → `0x08053C46` (call at `0x08053C76`) | if the queue at `engine + 0xDDE0/+0xDDE4` is non-empty: `FUN_080520EC` drains it. One of its commands tail-calls the **tempo setter `FUN_08069BEC`** (`0x08052236`), which rewrites the tempo map `clock + 8/+0x10/+0x18` |
| `0x080531BC` → `0x08053CB4` (call at `0x08053D1C`) | second queue (`engine + 0xE9E8/+0xE9EC`): `FUN_08051938` |
| `0x080531DA` | main chain (pads, recorder, FX1/FX2 into buses 10/11) |
| `0x080531E0` | clock advance `FUN_080696d8` |
| `0x080534DC` | `fw_position` cached at `engine + 0x28D78` |
| `0x08053506`, `0x08053516` | **Out 1 (buffer 0) += bus 10, += bus 11** |
| `0x0805351A`–`0x08053526` | **EQ → DJ FX A → DJ FX B** (both EQ exits, bypassed or not, call `next`) |
| `0x0805352E` | compressor branch → `bl 0x08053CA0` = JOEBOX `comp_process`: **Master FX → compressor → clipper** (`patches/master.py` makes the branch unconditional) |
| `0x0805353A` | `FUN_0804d880`: final Out 1 copied into input-bank buffer #2 (`ctx + 0x15864`; the bank at `ctx + 0x1583C` is the one `src/insert.c` uses, #0 = ADC bus) |
| then | Out 1 L/R copied to `io[0..3]` (two stereo pairs, inferred main + headphones), buffer 1 → `io[4..5]`, … |

So the DJ FX:

- sit on **Out 1 only**: a pad routed to Out 2 or 3 bypasses them;
- run **after** the FX1/FX2 returns (so the Repeater repeats the delay and reverb tails too) and after the EQ;
- run **before** JOEBOX's Master FX and the compressor/clipper.

Input-bank #2 receiving the final Out 1 is the **Resam** tap: with Rec Input = Resam the recorder overwrites input
bus 0 with it (`a6-input-monitor-path.md`, checked there by execution). A resample therefore records the Looper's
output post-compressor, one block late.

**Module context and buffers.** `ctx` = `engine + 0x128E0` (literal `0x0805344C`). Buffers are `ctx + i×0x14 + base`:
outputs at `0x150E4` (`FUN_0805F37C`), input bank at `0x1583C` (`FUN_0805F390`), scratch at `0x151FC`
(`FUN_0805F3A4`).

Each buffer is `{+0 cap, +4 len, +8 L, +0xC R, +0x10 lazy-clear, +0x11 R-valid}`. `FUN_0804D9C0(buf, &L, &R)`
returns both pointers after materialising them:

- lazy-clear set → zero both channels and clear the flag;
- R not valid → copy L to R;
- either way it ends with `+0x11` = 1.

A Looper that writes Out 1 should take its pointers through it.

**Cross-checks with A4.**

- `engine + 0x28D8C` is the **master EQ**, not the recorder. The WAV recorder is in the main chain, which runs
  **before** the clock advance. `duck_block` does its work and then calls the stock tick (`src/duck.c`), so the pads
  and the recorder see the same sample counter and ticks as `duck_block`. Only the EQ/DJ FX tail sees the advanced
  clock. A4's "add one block" rule for `cw_target` should be re-checked in A2 (the Clip pads are main-chain modules).
- One nuance: a tempo command drained at the top of the tick can re-base the tempo map **after** `duck_block` read
  it. Which command does this (its id) was not traced.
- **`ctx[0]` = engine is settled**: `FUN_080530FC` (the engine init that also calls the graph builder) stores the
  engine at `engine + 0x128E0` (`0x0805311C`). A4's main conclusion (`bufs[0]` = engine = clock) holds.
- A6 and A7 reached the same chain and the same EQ identification independently.

## 3. The XY screen

### Layout and identity

- **View**: ctor `FUN_080B20F0` (one caller, the UI ctor `FUN_0808BE4C` at `0x0808BF28`), vtable `0x080F0D90`. Its
  child-message handler is vt+0x30 = `0x080B1EE4`.
- **Two XY pads** (widget ctor `FUN_080B24EC`, vtable `0x080F0DD0`):
  - view `+0x22C` = **FX A**, rect `(65, 120, 255, 120)`;
  - view `+0x298` = **FX B**, rect `(65, 0, 255, 120)`.
- **Two `Hold` buttons** (string `0x080CF604`):
  - id **`0x97`** (A), rect `(0, 138, 64, 64)`;
  - id **`0x98`** (B), rect `(0, 37, 64, 64)`.
- **Two knob widgets** (the `slice.c` knob class `FUN_080B04C8`):
  - view `+0x308` bound to `0x18`, rect `(240, 210, 80, 30)`;
  - view `+0x5E8` bound to `0x19`, rect `(240, 0, 80, 30)`.
- **There are no other knob rows on the page.** Which half is on top depends on the y orientation, which is not
  settled here; a glance at the unit settles it.
- Each pad's `+0x38` holds its **cell id: `0x330` (A), `0x340` (B)**, copied by the view ctor from the descriptors at
  `0x2402EEEC`/`0x2402EEE4` (+4). Cell `0x3R0` ↔ engine channel `0x30R00` ↔ FX row R.

### Touch handling (pad widget)

| event | vt+ | handler | sends (msg `0x6e`) |
|---|---|---|---|
| down | `0x10` | `0x080B276C` | `+0x48`/`+0x49` = 1, then **`0x15` = 1**, then X value, then Y value at the touch point |
| move | `0x14` | `FUN_080B2824` | X and/or Y, only when the mapped value changes (`+0x40` / `+0x44` cache) |
| up | `0x18` | `0x080B24B0` | `+0x48` = 0, then **`0x15` = 0** |

All three post the generic `MSG_PARAM` `{u16 0x6e, tag 0x080CFBA4, u16 cell, i32 id, i32 value}` through `fw_post`
`0x080AED14`. `fw_post` is **synchronous**: it calls the parent's `vt+0x30` and recurses upwards while that returns
non-zero. It is the same forward `src/slice.c` relies on (view → `SetCellParam` → store + engine message `0x39` to the
cell's channel).

**Value mapping** `FUN_080B26C8(pad, coord, origin, size, id)`:

- `pos = clamp(coord − origin, 16, size − 16) − 16`; `frac = pos / (size − 32)`. That gives a 16 px dead margin at
  each edge.
- List ids (count `FUN_0808E2A4`): `index = min(count − 1, ⌊count × frac⌋)`, equal bands in list order.
- Numeric ids: `min + ⌊(max − min) × frac⌋`, clamped (min `FUN_0808E2D0`, max `FUN_0808E304`). **If `max == min` it
  returns 0, not `min`**, so a new axis id needs a real range or list.
- X uses the touch x over the pad width; Y the touch y over the pad height.

### X/Y per type — a data table

The table is `[u32 count][{u16 X id, u16 Y id} × count]`. It is bound by `FUN_080B1DE0(view, slot, index)`, which
sets each axis's label and range via `FUN_080B252C`, and the pad's `+0x3c` X id and `+0x3e` Y id:

| slot | type | X | Y |
|---|---|---|---|
| A (`0x080EEA78`) | Repeater | `0x1c` Length (1/4 … 1/32) | `0x13` Wet/Dry |
| | Gater | `0x1d` Length | `0x1e` Duty |
| | Filter | `0x10` Cutoff | `0x11` Res |
| B (`0x080EEA5C`) | Crusher | `0x16` Bit Depth | `0x17` Rate Reduc |
| | Filter | `0x10` Cutoff | `0x11` Res |
| | Echo | `0x2d` Delay | `0x2f` Feedback |
| | EchoHP | `0x2d` Delay | `0x30` HPF |
| | Flanger | `0x2b` Phase | `0x2c` Feedback |
| | Echo2 | `0x2e` Delay2 | `0x2f` Feedback |

### The view's handler (`0x080B1EE4`)

- **Hold buttons**: button `0x97` toggles view `+0xD2` and posts **`{cell 0x330, id 0x1a, v = new state}`**. Button
  `0x98` toggles `+0x1CA` and posts **`{0x340, 0x1b, v}`**.
- **Rest values** are posted by `FUN_080B1D68`, which puts the dot back and posts X then Y. `FUN_080B1CE8` gives a
  list its middle band (`count/2`), a numeric id its midpoint, and the Crusher's `0x16`/`0x17` their minimum. For the
  Repeater that is X = 1/16, Y = 50 %. It runs in two cases:
  - after a Hold toggle (either way). The `0x1a`/`0x1b` goes first, then X, then Y;
  - when a pad's `0x15` = 0 arrives while its Hold is **off**. The handler calls `FUN_080B1D68` and only **then**
    returns 1, which lets the `0x15` = 0 continue upwards. Because `fw_post` is synchronous, **the X/Y rest values
    reach `SetCellParam` and the engine queue before the release**.

  With Hold on, lifting the finger leaves the dot and the values where they were.
- **Type change**: a knob change arrives as msg `0x3c` `{cell, value, id 0x18|0x19}`. The view stores the index
  (`+0x8CC` A, `+0x8D0` B), re-binds that pad's axes, then forwards it as `0x6e`.
- The Hold buttons are refreshed from **`APP + 0x2C` / `+0x2D`** (`FUN_080B1D44`, on broadcasts `0x66` and `0xd4`).
  `SetCellParam` writes those bytes (§2). Whether they survive a preset load or a power cycle was not traced.

### Momentary vs latched

The finger (`0x15`) is **momentary** and the Hold button (`0x1a`/`0x1b`) is the **latch**. The effect is active while
either flag is set (plus the fade tails), with a 256-sample crossfade on every engage and release.

- Id `0x05` (`Trigger:` Gate / ON, `fxtrigmode`) is also understood by the Repeater's own reader (`v` == 1 →
  `finger(1)`). It is registered as a **pad** parameter (stock pad defaults store it as 0 at `0x080945C0`), and no
  XY-page sender was found.
- The path from touch to sound runs: pad → `0x6e` → view (`0x080B1EE4` passes it on) → generic forward →
  `SetCellParam` → engine queue → sub-slot `FUN_0806e190` → `FUN_0806e12c` → effect vtable. The engine side runs in
  the audio task, and all of a block's messages are applied before the effect's process in that block.

## 4. The Repeater

### Object (`0xd8` bytes; vtable `0x080DF580`; process `0x0806D858`, not a Ghidra function)

| offset | field |
|---|---|
| `+0x34` / `+0x38` / `+0x3c` / `+0x40` | ring: write index / length = **384,000** / L / R (float) |
| `+0x44` / `+0x48` / `+0x4c` / `+0x50` | capture: write index / length = **96,000** / L / R (float) |
| `+0x54` | capture samples still to take |
| `+0x58` | samples to wait before capture starts (negative = backfill from the ring) |
| `+0x5c` | repeating |
| `+0x5d` | finger down |
| `+0x5f` | start requested (by Hold) |
| `+0x60` | i64 absolute sample of the next slice trigger |
| `+0x68` | i64 slice length in ticks (default 480 = 1/8) |
| `+0x70` + k×`0x18` (k < 4) | voices `{u8 on, +4 read pos, +8 start delay, +0xc fade-in 256, +0x10 sustain, +0x14 fade-out 256}` |
| `+0xd0` | length index |
| `+0xd4` | float wet (default 0.5) |

### Buffers

- Allocated once by `FUN_0806d388`/`FUN_0806d392` from the **permanent SDRAM bump allocator** `0x0804436C`
  (JOEBOX's `fw_perm_alloc`) and zeroed. All float32.
- Per instance: ring 2 × `0x177000` B (8.0 s @ 48 kHz) and capture 2 × `0x5DC00` B (2.0 s).
- There are two Repeater instances: **7,680,000 B of SDRAM** in all (of the pool's 9,236,480 B). FX B cannot hold a
  Repeater, so the second instance is taken only by a fast FX A type round-trip (§1, Swap).

### Process

1. The Repeater's own reader `FUN_0806d654` re-reads the block's messages on its channel:
   - `0x15`: `v` ≠ 0 → finger on, and if not repeating, **start** (`FUN_0806d588`). `v` = 0 → finger off, and unless
     Hold is on, stop repeating.
   - `0x13` → wet = v/1000.
   - `0x1c` → length index, and `+0x68` = round(beats[v] × 960).
   - `0x05` → `finger(v == 1)`.
   - Message type `0x40` → reset. Type `0x32` → stop repeating; if Hold was on, clear it and post `0x8a` (with the
     channel) to the app. The senders of these two types are not identified.
2. A pending Hold start (`+0x5f`) starts the repeat.
3. **The block of Out 1 is written into the 8 s ring.** This happens only while the effect is active, because the
   sub-slot skips inactive effects (executed: the ring write index stays 0 while idle).
4. Capture into the 2 s buffer, then voices: when `clock samples ≥ +0x60`, a free voice is started (`FUN_0806d408`)
   for the next slice.
5. Mix with the engage crossfade (`FUN_0806e660`) **in place into Out 1**, then `next` (+8, which is 0).

### Start (`FUN_0806d588`) and the grid helper

- Clock = `ctx[0]` (the engine). **With the transport stopped (`+0x38` = 0) nothing is captured**. The effect still
  engages, so Y above 50 % ducks the dry (executed: silent at Y = 100 %).
- `G = FUN_0806a34c(out, clock, &len)`. For ticks `t` = `clock + 0x30` ≥ 0 and `p` = ⌊t/len⌋×len:
  - `t` on a line (`t mod len` = 0) → `G = t`;
  - else, if `|clock[0] − samples(p)| ≤ 384` (`cmp.w r3, #0x180` at `0x0806A388`) → **`G = t`, the current tick
    (off-grid)**, not `p`;
  - else → `G = p + len`, the next line.

  Executed at 120 BPM with `len` = 480: `now` 12,100 → 484, 12,384 → 495 (both "now"), 12,385 → 960.

  **So the helper never returns the line just passed.** A KP3-style looper that wants "the grid line at or before
  now" must compute `⌊t/len⌋×len` itself.
- The capture start is `samples(G) − clock[0]`. A negative value is backfilled from the ring. On a late touch that is
  only the sub-tick remainder (≤ 1 tick ≈ 50 samples at 120 BPM), and since the ring was not fed while idle, those
  samples are **zeros** (executed: 10 zero samples, then live input, inside the fade-in).
- Capture then takes **2 beats** from G (`FUN_08069c64` samples, capped at 96,000).
- The clock helpers are reusable from the cave (executed at 120, 97.3 and 174 BPM, with non-zero `tick0`/`sample0`):
  - `FUN_08069c64(clock, &t)` = samples from now to tick t;
  - `FUN_08069c80(out, clock, &t)` = absolute sample of tick t;
  - `FUN_08069c38(out, clock)` = ticks now (copies `+0x30`);
  - the tempo map is `clock + 8` {i64 tick0, i64 sample0, f32 BPM}: `samples = (t − tick0) × 48000 × 60 / (BPM × 960)
    + sample0`, rounded to nearest for positive results.

### Slices (`FUN_0806d408`)

- Each slice computes its own `G` with `FUN_0806A34C` (`0x0806D41C`). Its end `E` is `G + len` rounded to the
  **nearest** multiple of `len` (`0x0806D496`..`0x0806D4EC`), so an off-grid first slice is cut back onto the grid:
  486 + 480 → 960 in the late-touch run.
- The voice length is `samples(E) − samples(G)` (cap 95,488): a 256-sample fade-in, sustain = length − 512, and a
  256-sample fade-out.
- The voice reads the capture buffer **from its start**, so every slice replays the same first `len` of the
  captured audio.
- The next trigger is `samples(E) − 385` (`0x0806D47E`), so consecutive voices overlap at the seam. A trigger 385
  samples before a line finds that line as the next one, so every later slice is on the grid. Executed: the trigger
  after a touch at 12,160 is 23,615 = 24,000 − 385.

### Measured (Unicorn, real container + Repeater, 120 BPM, 128-frame blocks, wet 100 %, only FX A's channel fed)

Output samples were decoded back to the input sample they replay (§ How this was checked). "Exact" runs below exclude
the 256-sample fades.

| case | result |
|---|---|
| **early touch** at 12,800, length 1/8 (12,000 samples) | capture waits for the line at **24,000**. Slices are exactly 12,000 samples apart, each replaying input 24,128 … 35,616. The replay lags the grid by one block (128 samples) |
| **late touch** at 12,160 (160 samples after the 12,000 line) | repeating **starts at once**; the captured audio begins at tick 486 = input **12,150** (10 backfilled zeros, then live from 12,160). The first, short slice ends at the 24,000 line; slices at 24,000 / 36,000 / 48,000 each replay input 12,406 … 23,894 |
| touch at 12,288 (288 samples after) | starts at once from about the current tick, like the late touch |
| touch at 12,416 (416 samples after) | waits for 24,000, like the early touch |
| **X while repeating** (1/8 → 1/16 at 38,400) | the running slice finishes at 48,000. Slices are then 6,000 samples on the 1/16 grid, **still from the same in-point**. The out-point moves and the in-point stays (Traktor-like) |
| **Y law** (`0x13`) | two segments. Below 50 % the dry stays at 1.0 and the repeat rises along a fader taper (25 % → 0.025). At 50 % both are at 1.0. Above 50 % the repeat stays at 1.0 and the dry falls with the mirrored taper (75 % → 0.025, 100 % → 0) |
| **release** (`0x15` = 0 at 49,920, Hold off) | exact live input from 50,176: a 256-sample fade |
| **touch → Hold on → release → Hold off** | repeating continues through the release; Hold off at 51,200 gives exact live input from 51,456 |
| **Hold on, no touch**, with the view's rest posts (X 1/16, Y 50 %) | 1/16 slices from the next 1/16 line (18,000), repeat at unity **on top of** unity dry, until Hold off at 38,400 lets the running slice end (42,000); then exact dry. `finger` stays 1 (`FUN_0806d134` sets it to start the repeat) and `active()` stays 1, inaudible at Y 50 % |
| transport stopped, touch | nothing captured (`+0x54` = 0, not repeating), `finger` = 1; silent at Y 100 % |
| idle (never touched) | Out 1 is passed through bit-identical; param messages still reach the object (`vt+0x64`) |

**What X and Y control:** X = slice length 1/4, 1/8, 1/16, 1/32 (left = longest, the list order); Y = wet/dry
(bottom/top depends on the screen's y orientation, see §3).

## 5. What a "Looper" type has to provide

### Recommended route A — reuse the Repeater instance (the Munchi pattern)

**Stock patches (FX A only):**

1. Names `{Repeater, Gater, Filter, Looper}`, count 4, via a hook on `bl 0x0808C594` (a new name table in the cave).
2. **Index latch + class map in one hook**: a `b.w` at **`0x0806E174`**, the slot setter's `tbb` target for id `0x18`.
   It overwrites the 4-byte bound check, and nothing else branches to `0x0806E178..0x0806E17F`. On entry `r0` = sub-slot,
   `r1` = `0x18`, `r2` = index, and `lr` returns into the sub-slot's drain loop. The cave stub:
   1. `bx lr` if `r2` > 3 (unsigned, as stock);
   2. records `r2` as the FX A mode, keyed by `r0`, in the SDRAM state block (the cave has no `.bss`);
   3. on a change into or out of 3, resets the Looper/Repeater state itself (see below);
   4. sets `r1` = `0x40` for 3, else `byte[0x080DF6D8 + r2]`;
   5. `b.w 0x0806E048` (the swap uses only `r0`/`r1`).

   This makes the bound patch and the class byte unnecessary. The alternative is `cmp r2, #3` at `0x0806E174`,
   `0x080DF6DB` = `0x40`, and the same stub at `0x0806E178` (it then skips the bound).
3. **Relocated FX A axis table** in the cave: `{4, (0x1c,0x13), (0x1d,0x1e), (0x10,0x11), (Loop Len id, HPF id)}`,
   with the four literals `0x080B1E44`, `0x080B1E48`, `0x080B20B8`, `0x080B20BC` repointed. The two new ids must be
   registered with real ranges or lists (`FUN_080B26C8` maps `max == min` to 0). Writing the 4th entry over the store
   vtable's header at `0x080EEA88` is plausibly harmless (no reader found) but not proven.

**Engine:** wrap these Repeater vtable entries. In Looper mode each runs ours; otherwise it calls stock.

| entry | stock | Looper mode |
|---|---|---|
| `0x080DF58C` (+0x0c process) | `0x0806D859` | our process; it must also take the messages the Repeater's reader would have read (wrap +0x64, or re-read the queue the same way) |
| `0x080DF5F0` (+0x70 active) | `0x0806D0A1` | return 1, so the ring is fed every block |
| `0x080DF5F4` (+0x74 hold) | `0x0806D135` | base `FUN_0806e490`: the Repeater's hold forces `finger` = 1 (measured above), which would read as a finger down |
| `0x080DF5E4` (+0x64 set_param), optional | `0x0806D0B9` | catch the Loop Len and HPF ids |

The mode comes from the cave latch. The class is `0x40` for both Repeater and Looper, so the slot never swaps the
object between them. `fw_setting(0x24023090, 0x18)` cannot be used: it always returns 0 (§2).

**Things the wrapper must survive:**

- **Index 0 ↔ 3 never swaps or resets the object** (executed). The latch stub must clear our state, and stop any
  running Repeater slices (e.g. via the Repeater's reset `0x0806D03D`), on a mode change.
- **The object can be either Repeater instance.** A Gater → Looper change within 256 frames lands on `0x24015340`, not
  `0x24015268` (executed). So key Looper state to the object pointer, or keep it in the cave and take only the
  buffers from the current object.
- **`vt+0x78` reset runs on acquire and on release**, so state must tolerate it.
- **The Repeater's buffers are shared with Repeater mode.** A Repeater use overwrites the Looper's history, which is
  harmless.

This gives the Looper the Repeater's **8 s stereo float ring and 2 s buffer, already allocated** (3.84 MB). That is
4 bars at ≥ 120 BPM in float. Packed as int16 stereo the same ring holds 16 s (4 bars down to 60 BPM), as Munchi packs
its line (X2 §3 has the exact figures). No pool hook and no new SDRAM.

### Route B — a class of its own

1. Pick an id outside `0x3a..0x40` (A7 suggests `0x15`). The class map gets it either in the one spare byte
   `0x080DF6DB` or from the route A stub.
2. `b.w` at `0x0806CDA4` to an acquire that returns our object (after calling its `vt+0x78`) **only when
   `r1 + 0x3a` is our class**; `r1` ≤ 6 means a known class whose two instances are busy, and must return 0. Without
   that check a fast Gater round-trip would be handed the Looper.
3. Allocate the object and its buffers from `master_alloc`'s SDRAM block.

Release needs nothing (a foreign pointer is only reset).

### Either way, the object must

- Lay out the base fields (`+0x08` next = 0, `+0x18` channel, `+0x1e` output index, `+0x20` finger, `+0x21` hold,
  `+0x24`/`+0x28`/`+0x2c`/`+0x30` fades), so the stock helpers can be called for click-free engage and release:
  `0x0806E540` (finger), `FUN_0806e490` (hold), `FUN_0806e5a0`/`FUN_0806e660` (wet path + crossfade), `FUN_0806e594`
  (reset).
- Implement the vtable slots:
  - `+0x0c` process. It need **not** chain: the sub-slot runs its own `next`. Keep `+8` = 0 and **never link the
    object into a module chain**, or it would run twice;
  - the module base `+0x10`..`+0x5c` (copy the Repeater's);
  - `+0x60` class byte;
  - `+0x64` params: X Loop Len and Y HPF arrive here with no routing work;
  - `+0x6c` finger;
  - `+0x70` **always 1**: the ring must be fed while idle. The Repeater's is not, which is why it can only capture
    forwards;
  - `+0x74` hold, `+0x78` reset.
- **Set flags in `+0x6c` and act in the process.** On touch-down the UI sends `0x15` first and X/Y after it. Within a
  block the sub-slot applies all messages before the process runs, so the process sees the touched Loop Len.
- Be **retroactive** where the Repeater is not:
  - in-point = `⌊t/len⌋×len`, the grid line at or before "now" (KP3 feel), read from the ring. Do not use
    `FUN_0806A34C`: it returns the next line or "now";
  - loop `[in, in + len)` aligned to the grid, with its own seam crossfade;
  - an X change applies at the next loop boundary with the in-point kept, as the Repeater already behaves.
- Handle the **rest-value posts**:
  - A Hold toggle posts X = middle band (index 4 of a 9-entry Loop Len list) and Y = 50 %. That would jump a
    latched loop's length unless ignored while latched.
  - On finger-up with Hold off, the rest values arrive **before** `0x15` = 0. They are normally in the same block, but
    UI and audio are separate tasks, so this is not guaranteed (inferred). A length change that is followed by the
    release should not be applied audibly.
- Expect **no knob rows** on the XY page: `Source`, `Max Len` and `Slip` (plan P4) need another home. Options: the
  Master FX Tools page, or new knob widgets on the two physical knobs the XY view leaves unbound (`slice.c` pattern).
  The stock **Hold button already is the plan's `Hold`** (`0x1a` → `vt+0x74`).
- Read `Source: In` from input-bank #0 (`ctx + 0x1583C`, `src/insert.c`). `Source: Mix` is Out 1 at the DJ FX point
  (post FX1/FX2 returns and EQ). Per A6 the Rec Mon input is already in it (the recorder mixes the monitor into
  Out 1 early in the main chain). Caveat from A6: while Rec Input = Resam (the P5 Save), input bus 0 holds last
  block's Out 1, so `Source: In` would hear the Looper's own output during a Save.

## Open points (and what settles them)

- **Screen orientation**: which half is FX A, and whether Y grows upwards. One look at the unit, or the touch
  driver's y.
- **Hold persistence**: `SetCellParam` writes `APP + 0x2C`/`+0x2D`. Whether the preset writer saves them, or anything
  restores them, was not traced. A USB peek of `0x240200B4`/`0x240200B5` (APP + 0x2C/+0x2D) across a preset reload on
  the dev build (`src/usbdev.c`) settles it. Selecting Gater on FX A, power-cycling and reopening the XY page settles
  whether the DJ FX type persists (expected from the reads: back to Repeater).
- **DJ B's store**: `SetCellParam` targets `APP + 0x3020` for cell `0x340`. No builder call was found for it, and
  whether its count halfword is 0 (so the update is a no-op) was not checked. This does not matter for FX A.
- **Vtable header readers**: none found, not proven. Relocating the axis table (route A, item 3) avoids the question.
- **Senders of engine message types `0x32` and `0x40`** to the effects (transport stop? preset load?).
- **Which tempo command** in `FUN_080520EC` reaches `FUN_08069BEC`, and whether the Looper must re-read the tempo map
  after it (it reads `ctx[0]` in its own process, after the drain, so it sees the new map).
- **Echo2 vs Echo**: the pool hands an echo object (class byte `0x3b`) to a `0x3c` request. So re-selecting Echo2 is
  never seen as "same class", and how Echo2 differs inside the echo process was not read.
- **Count-4 FX A list on the unit**: never exercised on hardware. The P4 test should run the real view handler
  (`0x080B1EE4`) and `FUN_080B1DE0` with index 3 against the relocated table.

## How this was checked

- **Registrar** `FUN_0808C158` run whole under Unicorn (stub allocator; the two register functions record their
  arguments): the two lists, the param ids, labels, xml names and ranges above, and `Enabled` = `0x71`.
- **Class registry** filler `0x08094C64` run under Unicorn, then the table dumped.
- **Graph builder** `FUN_080525F0` run whole under Unicorn on a zeroed engine:
  - the container was pre-built with its real ctor, and one nested sub-object ctor (`FUN_0806EEEC`) was stubbed to
    return `this`;
  - the 60 modules and both chains were then walked through `+0x10` (list) and `+0x08` (next);
  - the EQ's identity comes from its registered ids (`0x118`–`0x12d`) and its ctor;
  - the tick's order and its two queue drains come from the instruction addresses listed in §2.
- **Pool + container + Repeater run for real** (stock image only): `FUN_0806ccf8`, `FUN_0806cd40`, `FUN_0806e244`,
  `FUN_0806e35c`, `FUN_0806e368`, then `FUN_0806dd0c` per 128-frame block.
  - The fake context had Out 1 at `+0x150E4`, scratch buffers at `+0x151FC` and a real tempo map at `ctx[0]`.
  - Messages were written into the queue format `FUN_0804F4D4` reads (`0x18`-byte records, count at `+0x600`). In
    the revision, **only FX A's channel** was served the queue. The first runs served it to both channels, which also
    engaged FX B's Crusher (A7 found this).
  - Stubs: the channel→queue lookup `FUN_0805F2C8`, the app post `FUN_0804F504`, the atexit registration, and the
    float zero-fill `FUN_0805F614` (reimplemented).
  - Out 1 carried a ramp encoding each sample's index, so every output sample decodes to the input sample it replays.
  - Code hooks on each class's `vt+0x78` recorded resets during type changes. Results: §1 Swap and §4 Measured.
- **Grid and clock helpers** called directly with a hand-built clock (several BPMs, non-zero `tick0`/`sample0`).
- **Static reads, each cross-checked by a second read** (decompile + disassembly):
  - the slot setter's `tbb` targets and the swap's acquire/release order;
  - the pool switch's shared exit;
  - the sub-slot's own `next` call;
  - the base engage/hold/active methods, and the Repeater's reader and start/slice routines;
  - the XY pad's down/move/up handlers, `fw_post`, and the view handler's `0x15`/Hold paths;
  - the axis tables and their literals (image scan for references) and the vtable headers (image scan of 14
    vtables);
  - the APP init store builds, the store builder's cases, every store-add call site, and `SetCellParam`'s family-3
    branch.
- Scratch harnesses (outside git): `/srv/dev/firmware/re-scratch/a5/`:
  - first pass: `stock.py` (stock-only Unicorn base), `reg.py`, `classtab.py`, `graph3.py`, `pool.py`, `rep.py` +
    `rep_t1..t4.py`;
  - revision: `r2_clk.py`, `r2_late.py`, `r2_backfill.py`, `r2_swap.py`, `r2_next.py`, `r2_alloc.py`,
    `r2_measure.py`, `r2_hold7.py`.

## Verification (2026-10-15)

An independent pass (`/srv/dev/firmware/re-scratch/v-a5/`) confirmed most claims and refuted eight. Each disputed
point was re-settled here by a fresh run or read; the verdicts below are this revision's.

| claim (first version) | verdict | how it was settled |
|---|---|---|
| `FUN_0806A34C` returns the line just passed when the touch is ≤ 385 samples late, and the missing samples come from the ring | **wrong** | Disassembly: the `≤ 0x180` branch stores `clock + 0x30` (now), not the line. Executed: 12,100 → 484, 12,384 → 495, 12,385 → 960. Container run: a touch at 12,160 replays input from 12,150; only 10 sub-tick samples are backfilled, and they are zeros |
| `0x080DF6DB..0x080DF6E3` (9 bytes) and `0x080EEA88`/`0x080EEA8C` are free | **wrong** | Image: all 14 vtables checked carry an 8-byte zero header; `0x080DF6E4` (literal `0x0806E504`) and `0x080EEA90` (literal `0x0809041C`) are vtables. Only `0x080DF6DB` is spare. A7 reached the same result for the class byte |
| Route A reads the Looper mode with `fw_setting(0x24023090, 0x18)` | **wrong** | Decompile: DJ A's store is built with type 0, the builder has no case 0, and all 231 store-add call sites (`findbl`) add no `0x18`/`0x19`. `SetCellParam` family 3 only updates. Replaced by the slot-setter latch at `0x0806E174` |
| an effect's process must chain to `+8` | **wrong** | Executed: `+8` = 0 in all 12 instances and both sub-slots. Disassembly: the sub-slot tail-calls its own `next` after the effect |
| Route B: hook `0x0806CDA4` as the "unknown class" exit | **incomplete** | Disassembly: the same exit serves "both instances busy" (5 `bne`s + Gater fall-through) with `r1` = 0..6; the hook must test `r1` |
| Route A: the slot never swaps between Repeater and Looper | **holds, with caveats** | Executed with the patches: 0 ↔ 3 = no swap, no reset. Gater → 3 within 256 frames lands on instance `0x24015340`, and acquire and release both reset |
| clock helpers | **hold**, except the grid helper (above) | executed at three tempos |
| XY message order on touch-down and Hold | **holds**; release order added | disassembly of `fw_post` (synchronous recursion) and the view's `0x15` path (`FUN_080B1D68` before `return 1`) |
| Measured Repeater behaviour | **holds** | all re-run with only FX A fed. The Hold-without-touch case, inferred before, is now executed |

Points the first version missed, now in the note: `SetCellParam` writes `APP + 0x2C/+0x2D`; the tick's two queue
drains and the tempo setter; `ctx[0]` = engine at `0x0805311C`; the buffer flags and `FUN_0804D9C0`; Echo/Echo2 share
instances; the pool's 9,236,480 B total; the XY map's `max == min` case; the stock looper module after FX1 in the
main chain; the Repeater hold's `finger` = 1 side effect, which route A must wrap.
