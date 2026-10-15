# A7 — the stock "looper" class: there is none

Stock 3.1.9. Found 2026-10-15 (blackbox#t-003), reworked the same day after verification. The question was: the
firmware carries the names `looper`/`LOOP`, `freeze`/`FRZE` and `vinyl`/`VNYL` among 1010music's engine class
names. Is a looper (or freeze, or vinyl) class actually compiled in, and could our code instantiate it as the Looper
FX's engine?

## Answer

**No.** All three are entries of a shared name table and nothing else. No class reports those types and no factory
or registry has an entry for them. They have no parameters (except one dead vinyl list, below) and no DSP. 3.1.9 never
creates one, so neither can we. The Looper FX brings its own engine, as the plan already assumes (SDRAM ring, P4). The
nearest code that already records and replays is JOEBOX's own Confetti, not stock (see "What it means for the Looper
FX"). If P4 makes the Looper a 7th FX A type, the exact stock contract it must meet is in the section of that name.

## Where the names live

A static initialiser, **`0x08094C64`** (entry in `.init_array` at `0x080CAB74`), fills a table at **`0x2401FCAC`**
of 12-byte entries `{u8 type; const char *name; const char *code}`. It uses 60 of 82 slots (`0x52`, the bound every
reader loops to: `cmp #0x52` at `0x0809534A`, `0x08095960`, `0x08096D2C`, `0x0809AEB0`). It is 1010music's shared type
vocabulary. Besides the Blackbox's own types it lists `laser*` (`0x0F..0x14`), `cvplayer`, `cvrecorder`,
`playcontrol` (`0x1B`), `transctrl`, `wavetable` (`0x51`) and more. The DJ FX classes are `fxbitcrusher` `0x3A` …
`fxrepeater` `0x40` (indices 19..25).

| name | type | index | entry |
|---|---|---|---|
| `looper` / `LOOP` | `0x15` | 39 | `0x2401FE80` |
| `freeze` / `FRZE` | `0x0A` | 30 | `0x2401FE14` |
| `vinyl` / `VNYL` | `0x21` | 58 | `0x2401FF64` |

A second, smaller table at `0x2401FC44` (13 × `{u32 id; name}`: `scenetrig`, `pitch`, `start`, `length` …) holds the
modulation-target names, not classes.

Everything that reads `0x2401FCAC` is about the app's cells, not the engine:

- preset writer `FUN_08095328`: a cell's vtable[0] gives its type, and the table gives the `type="…"` name;
- preset attribute reader `FUN_08095910` and loader `FUN_08096AD8`: name → entry → cell-type setter `FUN_08093F20`.
  The loader takes `0x03`/`0x4C` only on pads, `0x47` on sequences, `0x4E` on sections, `0x1F` on the song and `0x01`
  on assets. It takes any type on the five layer-3 cells (`app + 0x1780`, 0x18 bytes each);
- the modulation-target label `FUN_0809AD74`: an FX object's type → its four-letter code (which objects those are
  was not followed further).

No code holds the address of the looper, freeze or vinyl entry. **`FUN_08093F20(cell, entry)`** does the same two
things for every type, then adds defaults for some:

1. It calls `FUN_08093E6A(cell, 0x40)` (at `0x08093F28`). That allocates the cell's settings store (0x40 entries of
   8 bytes, from `0x0804436C`) when `cell + 4` is null. Otherwise it clears the store (`FUN_08093E44`: entries
   zeroed, `cell + 0x0A` count = 0).
2. It writes the type byte at `cell + 8` (at `0x080947E8`).

It writes default parameters for 20 types (sample 59, samtempl 37, misccontrol 23, eq 22, noteseq 11, asset 9,
delay 8, song 7, env 5, …) and **none** for `0x15`, `0x0A` or `0x21`. A preset naming `type="looper"` on a layer-3
cell would therefore empty that cell's settings store and set its type byte to `0x15`, and nothing else. That is
inferred from the code, not tried on a unit. JOEBOX raises the 0x40 capacity to 0x60 at `0x08093F26` and
`0x080949F0` (`patches/duck.py`); that does not change the picture.

## No class carries those types

3.1.9 has two families of classes that a type could select. Neither has a looper, freeze or vinyl.

### DJ FX (the XY page's effects; A5 owns the framework)

Each DJ FX vtable has 31 entries (`+0x00..+0x78`). Its `+0x60` getter returns `vt + 0x7C`, whose first byte is the
class's type. The two stock readers read only that byte (below). The two zero words after it are also the next
vtable's 8-byte header, since the vtables sit exactly `0x88` apart (8 header + 31 × 4 + 4). Whether 1010music's
class-info struct is 4 or 12 bytes cannot be told from the image. There are exactly six:

| type (name table) | name | vtable | pool offsets | `+4` byte |
|---|---|---|---|---|
| `0x3A` | fxbitcrusher (Crusher) | `0x080DF2D8` | `+0x4E8`, `+0x538` | `0x02` |
| `0x3B` | fxecho (Echo, EchoHP; also serves `0x3C` Echo2) | `0x080DF360` | `+0x1B0`, `+0x280` | `0x5D` |
| `0x3D` | fxfilter | `0x080DF3E8` | `+0x400`, `+0x474` | `0x18` |
| `0x3E` | fxflanger | `0x080DF470` | `+0x350`, `+0x3A8` | `0x19` |
| `0x3F` | fxgater | `0x080DF4F8` | `+0x588`, `+0x5E0` | `0x5E` |
| `0x40` | fxrepeater | `0x080DF580` | `+0x000`, `+0x0D8` | `0x5C` |

- **Three numberings, not one.** The class-info byte uses the name table's numbers. The FX A/B maps
  (`0x080DF6D8` = `40 3F 3D`, `0x080DF6D0` = `3A 3D 3B 3B 3E 3C`) use the same numbers, and so do the factory and the
  registry below. The object's `+4` byte is a third numbering, the one the base constructor `0x0806E4DC` takes as its
  argument. It is the engine-module "kind" numbering (next section). No reader of a DJ FX object's `+4` byte was found
  (see the checks).
- **Pool and factory.** The instances live in a static pool at **`0x24015268`** (guard `0x24015260`, getter
  `FUN_0806CCF8`), built once by `FUN_0806CC80`, with in-use flags at `pool + 0x638..0x643`. The factory
  **`FUN_0806CD80(pool, type)`** subtracts `0x3A` and switches on 0..6. It returns an instance for `0x3A..0x40` and
  **NULL for every other type**, `0x15`, `0x0A` and `0x21` included.
- **A write-only class registry.** Six more `.init_array` entries (`0x080CAB4C..0x080CAB60` → `0x0806B12C`,
  `0x0806BB74`, `0x0806BF8C`, `0x0806C59C`, `0x0806CC64`, `0x0806DCE8`) each register one class. The getter is
  `FUN_0806CF6C` (object `0x240158B4`, guard `0x240158B0`), and `FUN_0806CFB0` appends `{u8 type; class-info*;
  constructor}` to a 32-slot table (count at `+0x180`). The entries are `0x3A`, `0x3B`, `0x3D`, `0x3E`, `0x3F` and
  `0x40`, with the classes' second constructors `0x0806AD1C`, `0x0806B304`, `0x0806BC4C`, `0x0806BFB4`, `0x0806C6D4`
  and `0x0806D1EC`. Nothing reads the table: the getter's only callers are those six, and its address is in no other
  literal. So stock never creates a DJ FX by type through it, and it has no looper entry either.

### Engine modules (the fixed audio graph)

24/25-entry vtables. `+0x00` is clone (operator new `0x080CAAC4` + constructor) and `+0x0C` the block method. Object
`+0x04` is a one-byte *kind*, `+0x08` the next module in the chain and `+0x18` its code (`0x400` global, else
bank/row/col). Exactly **15** vtables in the image have a clone at `+0x00`. Every one is identified and every one is
built by stock:

| vtable | kind | size | what | built |
|---|---|---|---|---|
| `0x080D0054` | `0x0E` | `0x250` | chain root at `engine + 0xD590` (its block method only forwards) | engine ctor `FUN_080512A4` |
| `0x080D00BC` | `0x0A` | `0x684` | master compressor (`src/comp.c`, block `FUN_0804EDDC`) | engine ctor, at `engine + 0xFC40` |
| `0x080D0128` | `0x15` | `0x3D4` | event router (block method switches on message type) | graph ×1 |
| `0x080D0190` | `0x15` | `0x110` | pad-note map for the 20 cells (param `0xF5` Pad Note) | graph ×1 |
| `0x080D08F8` | `0x54` | `0x40` | clock / transport out (calls `fw_position`) | graph ×1 |
| `0x080D07AC` | `0x41` | `0x2B0` | WAV recorder (`src/preroll.c`) | graph ×1 |
| `0x080D0744` | `0x39` | `0xCB8` | note sequence (`src/seqfix.c`) | graph ×17 |
| `0x080EAA38` | `0x4D` | `0x670` | slice / transient scanner (param `0xB6` Threshold, 64 K-float buffer) | graph ×1 |
| `0x080CFFD4` | `0x08` | `0x380` | held-note tracker for the 20 cells | graph ×1 |
| `0x080D06C8` | `0x48` | `0x5C4` | pad class A, Sample / Multisample (`FUN_080596B0`) | graph ×16 |
| `0x080D0890` | `0x4C` | `0xBB8` | pad class B, Clip / Slicer (`FUN_08067FA4`) | graph ×17 |
| `0x080D0814` | `0x43` | `0x1A0` | reverb, FX2 (`src/fx2.c`) | graph ×1 |
| `0x080D0660` | `0x33` | `0x224` | delay, FX1 (`src/munchi.cpp`) | graph ×1 |
| `0x080CFC40` | `0x35` | `0x1CC` | master 4-band EQ (params `0x118..0x12E`) | graph ×1 |
| `0x080D01F8` | `0x2D` | `0x134` | metronome (params `0xCD` Metronome, `0xF7` Metro Gain) | graph ×1 |

The router, pad-note map, clock-out, held-note tracker and scanner are named from one reading of their block methods
(the messages and parameter ids they handle). That is inferred, and none of them has a buffer that could hold a loop.
The other rows are named by JOEBOX's sources or by their parameter ids.

The graph builder is **`FUN_080525F0`** (tail-called by the engine init `FUN_080530FC`). It allocates the 60 objects
of the 13 "graph" rows with `0x0804436C` and links them through `engine + 0xFC08` (head) / `+0xFC0C` (tail), object
`+0x10` (next) and `+0x14` (serial). It aborts if an existing serial has the wrong kind. It is a fixed list, not driven
by any type. Operator new has 16 callers: the engine's own allocation (`0x0804C1C6`) and the 15 clones. Each engine
vtable is referenced only from its own class's code (constructor, destructor, clone).

The **DJ FX container** (vtable `0x080DF670`) sits at `engine + 0x28D90` and embeds **8 sub-slot hosts** (vtable
`0x080DF608`, at container `+0x20 + k × 0x2C`). The active count at container `+0x180` (u16) is 4 after the engine
constructor and **2** after the graph builder. Host A (`+0x20`) has code `0x30300` and host B (`+0x4C`) `0x30400`;
hosts 2..7 keep `0xFFFF`. A host's current effect is at host `+0x20`, the outgoing one at `+0x24` and its countdown
at `+0x28`. At boot host A holds pool `+0x000` (Repeater) and host B pool `+0x4E8` (Crusher).

**Trap: the kind byte is not the name-table type.** Two classes have kind `0x15` and the compressor has `0x0A`. Those
are the same numbers as `looper` and `freeze`, by coincidence: routers and a compressor are neither. A search for
`#0x15` finds those two routers, not a looper. Most kinds name an unrelated table entry: note sequence `0x39` is
`flangerdist`, reverb `0x43` is `lfo`, EQ `0x35` is `env`, Filter `0x18` is `notemapper`. Others are past the table
(`0x41`, `0x54`, `0x5C..0x5E`). Two agree in a way that could be meaningful: the root `0x0E` = `ioconnectout` and
pad class B `0x4C` = `samtempl`. Whether the two numberings share an origin there was not settled, and nothing here
depends on it.

## Vinyl and freeze leftovers

- **Param `0x60`**, list `Mode:` = `Tape Stop`, `Scratch`, `Powerdown`, `Backspin` (names `0x080ECD2C`), xml
  `vinylmode`. The stock registrar `FUN_0808C158` registers it in the call at `0x0808CA92`, and nothing else uses it:
  - no page table in the pad-mode block (`0x080EF000..0x080F0000`) holds it;
  - the other 15 `mov`/`cmp #0x60` sites in the code are message codes, peripheral set-up and loop bounds;
  - every `tbb`/`tbh` switch whose range covers `0x60` sends it to its default target.

  So it is a dead list parameter, already registered with its strings and xml name. A later KP3-style "vinyl break"
  effect (P6 idea) could use it as its mode row with no registration code or strings: it would need a page slot and
  the DSP. A consumer that computes the id at run time cannot be excluded statically (medium confidence).
- **freeze**: the name only. `FreezeSequencer` (`0x080CB720`) is an Ableton Live set key, read beside `MasterTrack`
  and `ArrangerAutomation`. It has nothing to do with audio freeze. The `Freeze:` row in JOEBOX's Munchi (`0x1d3`) is
  JOEBOX's.

## What it means for the Looper FX

- **Nothing stock to instantiate, so there is no reuse cost to weigh.** The ring, touch-in, Loop Len and HPF are
  ours (plan P4). By the plan's own figures our own ring costs 1.5 MB of SDRAM for 4 bars at 120 BPM (8 s of 16-bit
  stereo), and twice that at 60 BPM. CPU is one write and one read of 128 frames a block, plus the SVF. That should
  be well under 1 % of the core, but it is an estimate and has not been measured.
- **Nearest existing record/replay code**: JOEBOX's Confetti (`src/confetti.c`, driven from `src/munchi.cpp`), a
  granular micro-looper in the FX1 delay slot. It records the send into the stock delay's lines and plays pieces back
  behind the write head with collision checks. Its `Stutter` mode is the closest to the KP3 catch.
  - The lines are line 1 at `obj + 0x30` and line 3 at `obj + 0x68`, 192,256 floats each (`munchi.cpp:21-23`).
  - Munchi uses them as 4.0 s live + 4.0 s freeze. Confetti uses both as one 16-bit stereo loop of 8.0 s
    (`confetti.c:4-5`; `munchi.cpp:594` takes `LINE_LIVE` and `LINE_FREEZE`, and `:610` passes them to
    `confetti_block`). Check: 2 × 192,256 × 4 B / 4 B per frame = 384,512 frames = 8.01 s at 48 kHz.
  - It is MIT and makes no firmware calls (it includes only `stdint.h` and `rev4.h`), so the ring logic can be copied.
  - The memory cannot be shared: those lines belong to FX1.

### If the Looper is a 7th FX A type

This is A5's route B: a class of its own. A5's route A, which reuses the Repeater instance, needs none of the factory
work below. The FX A list then needs these stock patches, besides A5's names/count registration (`bl 0x0808C594`)
and XY-axis table (`0x080EEA78`/`0x080EEA88`):

| site | stock | patch | why |
|---|---|---|---|
| FX A map `0x080DF6DB` | `00` (alignment padding) | the Looper's type, e.g. `0x15` | **the only free byte**: `0x080DF6DC..0x080DF6E3` is the 8-byte header of the FX base vtable `0x080DF6E4` (literal at `0x0806E504`, stored by the base constructor at `0x0806E4F8`). A5's "9 zero bytes" holds room for one new type, not more |
| bound `0x0806E174` | `cmp r2, #2` | `#3` | the slot setter rejects index > 2 |
| factory exit `0x0806CDA4` | `movs r0, #0; bx lr` (4 bytes, room for one `b.w`) | `b.w` to our acquire | see below |
| release `FUN_0806CE7C` | — | **none** | it calls `obj→vt+0x78`, then compares the pointer with the 12 pool slots. A foreign pointer matches none and returns at `0x0806CEF0` with no flag touched |
| registry `0x240158B4` | — | none | write-only |

**The factory-exit trap.** `0x0806CDA4` is the exit both for an unknown type and for "both instances of this class
busy". The busy exits are the `bne` at `0x0806CDB6` (Echo), `0x0806CDD0` (Filter), `0x0806CDEA` (Flanger),
`0x0806CE04` (Repeater) and `0x0806CE1A` (Crusher), plus the Gater path falling through. On every path `r0` = pool and
`r1` = type − `0x3A`, not the type. The hook must therefore return our object only when `r1 + 0x3A` equals the
Looper's type (`r1` = `0xFFFFFFDB` for `0x15`), and return 0 otherwise. A Looper type outside `0x3A..0x40` can never
be confused with a busy class, whose `r1` is 0..6. Like stock's acquire, the hook should call the object's
`vt+0x78` before returning it. A singleton needs no in-use flag.

**What stock calls on the Looper object** (each row seen under Unicorn with the real container process):

| vt+ | called by | when |
|---|---|---|
| `0x0C` process(obj, ctx) | host process `FUN_0806E190` | every block in which `0x70` returns true; the outgoing effect is never processed |
| `0x4C` set code(obj, code) | slot swap | on install. Skipped when it equals the base `0x08046A0D`; stock then stores host `+0x18` into `obj + 0x18` itself |
| `0x50` set output(obj, idx) | slot swap | on install. Skipped when it equals the base `0x08046A11`; stock then stores host `+0x1E` (u16) into `obj + 0x1E` |
| `0x60` class-info | swap `0x0806E05A`, class-id setter `FUN_0806E368` `0x0806E38E` | when a type is set while the Looper is current. Only byte 0 is read, compared with the requested type (`0x0806E05E`). A cave class-info `{0x15, 0, 0}` is enough |
| `0x64` param(obj, id, v) | slot setter `FUN_0806E12C` | every id except `0x15`, `0x18`..`0x1B` (X/Y arrive here) |
| `0x6C` finger(obj, v ≠ 0) | slot setter, id `0x15` | touch down/up |
| `0x70` active(obj) | host process | every block |
| `0x74` hold(obj, v ≠ 0) | slot setter, ids `0x1A`/`0x1B` | Hold button |
| `0x78` reset(obj) | our acquire hook; release | release happens when the outgoing countdown (256 frames) runs out, or at the next type swap |

- The getter the swap uses for `+0x1E` is the **host's** `vt+0x54` (`0x08046A15`, the base), not the effect's. The
  Looper's own `+0x54` is not called by the swap.
- **Reset must be idempotent and must leave `+0x18` and `+0x1E` alone**, as the base reset `FUN_0806E594` does (it
  clears only `+0x20/+0x21`, `+0x24`, `+0x28`, `+0x30`). The swap acquires the new effect and copies code and output
  into it, and only then releases the old outgoing effect. With a singleton Looper, the sequence Looper → Gater →
  Looper within 256 frames therefore runs: acquire Looper (reset), copy code, release the outgoing Looper (reset
  again), install. The reset lands on the object that has just been installed.
- **The `+4` byte** has no reader: none was found statically, and read hooks saw no read (see the checks). Any value
  works. `0x5F`, next after the Repeater/Echo/Gater numbers, keeps it distinct by convention.
- The type byte: `0x15` = `looper`/`LOOP` already exists in the name table, so it is the natural id. Whether any
  stock code would then show or save those strings by itself was not checked: the preset writer reads cell types, not
  DJ FX objects.

## PocketRave's "registry" `0x24049808`

It is not a class registry. The engine holds a 64-slot pointer table at **`engine + 0x127D0`** with its count at
**`engine + 0x128D0`**, directly after the slots.

- The engine constructor zero-fills the table (`memset` of 0x100 bytes, call at `0x08051602`) and zeroes the count
  (`0x080515E6`).
- The graph builder appends to it at `0x080528C6` and `0x080529BC`, writing the count at `0x080528CA`/`0x080529C0`.
  The bound check (`cmp #0x3F` after the increment) runs after the store.
- After the graph build it holds **17** objects, all note sequences (vtable `0x080D0744`, codes `0x20303` and
  `0x1RRCC` for the 16 pad sequences). That matches PocketRave's use of it: it looks up a sequence by code.

The absolute address fits if the engine sits at `0x24037038`:

- The engine is `0x28F18` bytes, allocated at `0x0804C1C6`. Its pointer is stored at `0x2400A9C0 + 0x9A74 =
  0x24014434`.
- At `0x24037038` it would end at `0x2405FF50`, 4 bytes under the heap's top `0x2405FF54`. Operator delete's range
  check at `0x080C8976` gives the heap as `0x2402F214..0x2405FF54`, exactly 200,000 bytes.

That is consistent but not proven. A dev-build peek of `0x24014434` (`src/usbdev.c`) settles it; the expected value is
`0x24037038`.

## Open

- **A4's recorder identification is wrong (a side finding).** `engine + 0x28D8C` is the master EQ (vtable
  `0x080CFC40`), not the recorder. It has exactly two writers: the engine constructor (0, at `0x080515FE`) and the
  graph builder (`0x08052C98`). The builder stores there only after checking that the object's kind is `0x35`, and
  only the EQ has kind `0x35`; the recorder is `0x41`. The EQ's `+0x08` is the DJ FX container. The recorder
  (`0x080D07AC`) sits in the main chain (root → router → clock-out → a note sequence → recorder → scanner …), and no
  engine word points at it. A4's clock conclusion does not depend on that identification. A5 and A6 reach the same
  result independently.
- What stock does at run time with a layer-3 cell whose type byte is `0x15` (only reachable from a hand-edited
  preset). The code says the cell gets an empty store, no defaults and no engine change. Loading such a preset on the
  unit settles it. The plan does not need it.

## Verification

The first version was challenged on ten points. None of its claims was refuted. Each point was settled with a fresh
check, not by taking either side's word:

| challenge | verdict | how it was settled |
|---|---|---|
| "both busy" also exits through `0x0806CDA4`, with `r1` = type − `0x3A` | **holds**, now in the note | the factory run under Unicorn: a third acquire of each type `0x3A..0x40` returns 0 through `0x0806CDA4` with `r1` = 0..6. Unknown types arrive with `r1` = type − `0x3A` (`0x15` → `0xFFFFFFDB`) |
| "patch those three switches" overstated: release needs no patch | **holds**, corrected | release run with a foreign object: only its `vt+0x78` is called, the 12 flags are unchanged, and it returns at `0x0806CEF0` |
| the vtable must provide `+0x78`, `+0x60`, `+0x4C/+0x50/+0x54` | **holds with one correction** | the swap read from the listing and run. `+0x4C`/`+0x50` are called on the new effect (or devirtualised); `+0x54` is read from the host's vtable, not the effect's |
| FX A map room is 1 byte, not 9 | **holds** | image bytes: `0x080DF6DC..E3` are the zero header before `0x080DF6E4`, which the literal at `0x0806E504` and the store at `0x0806E4F8` reference. Every DJ FX vtable has the same 8-byte zero header |
| DJ FX `+4` bytes are a third numbering | **holds** | each constructor's `movs r1, #imm` before `bl 0x0806E4DC`, and the 12 live pool instances after the engine build agree: `0x5C 0x5D 0x19 0x18 0x02 0x5E`. Read hooks on all twelve saw no reader |
| class-info zeros double as the next vtable's header | **holds** | vtables `0x88` apart; the six class-infos each have one extra literal reference, in the registry initialisers. The registry itself is a new finding |
| count at `engine + 0x128D0`, 17 at boot, ctor zero-fill | **holds**, now in the note | write hooks over `+0x127D0..+0x128D3` through the engine constructor and the graph builder |
| container embeds 8 hosts, 2 active | **holds**, corrected | container read after the engine build: 8 hosts of vtable `0x080DF608`, count 4 → 2, codes and boot instances as tabled |
| `FUN_08093F20` also clears/allocates the store | **holds**, corrected | the first run had stubbed `0x08093E6A`. Re-run live, every type calls it once with 0x40, and the cell writes are store, capacity, clear, then type byte |
| Confetti citations | **holds**, corrected | the source lines re-read. The call is at `munchi.cpp:610`, not `:614` |

The verifiers' nits are folded in: 6 literal pools hold the table base, not 7, and the note-sequence table also has
the constructor's zero-fill. Two side findings for **A5**:

- Its `a5-djfx-xy-repeater.md` "9 bytes" row should read "1 byte".
- Its harness `rep.py` serves one message queue to both FX channels. In its runs an FX A touch therefore also engaged
  FX B's Crusher (finger 1, active). Re-running a Repeater touch with per-channel queues changes the output in only
  511 samples (the Crusher's engage and release fades), by at most 0.0029. A5's timing results stand, but its
  "sample for sample" release check ran through that fade.

## How this was checked

- **Name table**: the static initialiser `0x08094C64` run under Unicorn (stock image only), table dumped from
  `0x2401FCAC`. An image scan for pointers to the six strings finds each one exactly once, in that initialiser's pool.
  Literal words pointing into `0x2401FC40..0x2401FFE0` are the table base (6 pools) and `0x2401FC44` (once, at
  `0x080952C8`). One more hit, at `0x080BEF56`, is the middle of two instructions.
- **Cell-type setter**: `FUN_08093F20` run under Unicorn for all 60 entries, with the allocator stubbed, a code hook on
  `0x08093E6A` and on the store-add `0x08093EF6`, and a write hook over the cell.
- **DJ FX**:
  - Pool constructor and factory run for every type `0..0x52`, both instances of each class taken and a third asked
    for. A code hook on `0x0806CDA4` recorded `r1`.
  - A static scan for class-info getters finds the same six.
  - The `.init_array` entries and the registry's literal and callers were read statically.
- **Simulated Looper**:
  - Set-up: the map byte and bound patched in emulator memory (translation cache flushed), and a Python hook on
    `0x0806CDA4` standing in for our acquire. The object is base-constructed, with a vtable copied from the Repeater's
    and stubs at `+0x0C/+0x60/+0x64/+0x6C/+0x70/+0x74/+0x78`.
  - Driven through the slot setter directly, and through A5's container harness with per-channel queues: select,
    touch with X and Y in one block, Hold, switch away. The outgoing release came after 256 frames, and FX B was
    unaffected.
  - The order touch → `0x6C`, then X and Y → `0x64`, then `0x70`/`0x0C` in the same block was observed.
- **Engine classes**:
  - An image scan for vtables (zero header plus code pointers) referenced from literal pools finds 132. Exactly 15
    have a clone at `+0x00`; findbl gives 16 `bl` to `0x080CAAC4` and no `b`.
  - Kinds were read from the constructors' immediates and from live objects. Classes were identified from their
    block methods' parameter ids or messages, and by JOEBOX's sources where they already name them.
- **Engine graph**: the engine constructor `FUN_080512A4` and then `FUN_080525F0`, run whole under Unicorn with the
  allocator and operator new stubbed. The ITCM page at 0 was mapped, because a class-B sub-object constructor reads
  address 8 before its pointer is set (harmless on the unit, where 0 is ITCM). The run gives 60 list objects of 13
  classes. Write hooks covered the note-sequence table, its count and `engine + 0x28D8C`.
- **vinylmode**:
  - Registration: A5's whole run of the stock registrar, and the call at `0x0808CA92` re-read (`r1` = `0x60`,
    `Mode:`, names `0x080ECD2C`, xml `vinylmode`).
  - Other uses: an operand scan of the listing for `#0x60` with each site read, and a u16 scan of the page-table
    block.
- Scripts (outside git): `/srv/dev/firmware/re-scratch/a7/` (first pass: `vt2.py`, `clones.py`, `fxfactory.py`,
  `celltype.py`, `graph_a7.py`) and `/srv/dev/firmware/re-scratch/a7/r2/` (rework: `r2_engine.py`,
  `r2_celltype.py`, `r2_djfx_run.py`, `r2_a5_queue.py`, `r2_a5_queue_cmp.py`).
