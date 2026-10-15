# X2 — memory for the Clip Window state and a Looper ring

Stock 3.1.9 (`BLACKBOX-3.1.9.bin`) and the JOEBOX 1 full set as built for Gate 0 (`out/gate0/full/BLACKBOX.bin`).
Found 2026-10-15 (blackbox#t-003), corrected the same day after an independent verification (see "Verification").
The questions were: how big is the SDRAM pool behind `fw_perm_alloc`, how much is left after boot, can it be used
after boot, where the sample pool is, and where a 3 MB looper ring can go.

## Answer

- **At the firmware's own "Initialized" print the SDRAM pool has 2,146,304 B free on stock and 1,495,296 B (1460 KB)
  on JOEBOX 1.** The firmware prints both ("`Initialized. Internal = %dKB, External = %dKB`": 2096 KB and 1460 KB).
  Both boots were executed, and an independent harness got the same numbers.
- **On the unit these are upper bounds.** The emulated boot read no file: no settings.tml, no preset. The first
  preset load allocates more permanent memory lazily (256 B strings, 512 B cell stores). That growth was not measured.
  A USB peek on the unit after loading the largest preset gives the real figure.
- That free span is not spare. Preset load and save build their XML there: about **4.6–4.9 × the preset.xml size**
  while a preset loads. Running out of it, at boot or later, **hangs the unit**. No allocator returns NULL.
- **A 3 MB ring does not fit in the pool.** It fits in the FX A Repeater's own buffers: 3,840,000 B per instance,
  allocated by stock at boot. As planar int16 they hold 16.0 s for sure (4 bars at ≥ 60 BPM). When the four buffers
  are contiguous they hold 20.0 s (4 bars at ≥ 48 BPM), and they were contiguous in both builds. The Looper finds the
  instance through FX A's slot at `0x2405FDE8 + 0x20` (§3).
- **Clip Window state (~1 KB): keep the plan's choice.** Put it behind JOEBOX's block (`EXTRA_BYTES` += `0x400`). It
  costs 1 KB of the 1460 KB.
- Budget for the whole fork: at most about **0.4 MB more permanent SDRAM** in total. That keeps about 1 MB free at
  "Initialized", before the lazy growth: enough for a preset.xml of about 210 KB.

## 1. The SDRAM pool (0xC0000000–0xC4000000, the whole 64 MB)

The SDRAM pool is a **two-ended stack**. Its two pointers live in `.data`, copied at reset from the image at `0x080F1E08`:

| | pointer | initial | direction | function |
|---|---|---|---|---|
| permanent ("low") | `*(u32*)0x2400008C` | `0xC0000000` | up | `fw_perm_alloc 0x0804436C(n)` |
| temporary ("high") | `*(u32*)0x24000088` | `0xC4000000` | down | alloc `0x08044404(n)`, free `0x08044470(p)` |

- **`0x0804436C`** rounds `n` up to 16 bytes and bumps *low*. It returns the old *low*.
  - It never reads `r1`, so the second argument JOEBOX and stock pass (0 or 1) is ignored.
  - It does not zero the memory.
  - Its limit is the *current* high pointer. An exact fit (new low == high) is accepted.
  - `n` = 0 returns the current low without moving it.
  - It takes no lock: a plain load / add / store of `0x2400008C`.
- **On overflow it hangs and never returns 0.**
  - It stores the advanced low pointer *first* and only then compares it with high. Executed: one byte too many
    leaves low at `0xC4000010`.
  - It then calls the print stub `0x08043DE4` with "ERROR: No more extended memory: crash" (`0x080CAD8C`), a no-op in
    this build.
  - Last comes `0x0808A37C`, which is `b .`.
- **Temporary** blocks carry a 16-byte header and sit on a list whose head is `0x24002E7C`. A free unlinks the block;
  the high pointer moves back up only when the lowest block goes, and to `0xC4000000` when the list empties. A
  failed temporary allocation hangs the same way.
  - The only users are **tinyxml2**: the document copy in `Parse 0x0804B018`, its 0xFE4-byte node pools and its string
    copies. Plus the file loader **`0x080971CC`**, which reads the whole file (+1) into a temporary block.
  - So the top of SDRAM is the scratch area for preset load (`0x08096AD8`) and preset save (`0x08095328`).
- **`0x080443F0`** returns *high − low*. Its only caller is that print in the GUI task (`0x08043DEC`).

**What a hang costs depends on when it happens.** The order of main's calls was read statically.

- **Inside `main`: a silent hang on every boot.** `main` starts the window watchdog at `0x080442FE` (`0x08046938`:
  WWDG1 clock on, prescaler /128, window and counter `0x7F`, early wakeup off). That call comes after all of main's
  SDRAM allocations and just before the scheduler starts. The GUI object is allocated at `0x08044270`, and the last
  logged allocation in `main` is 14,000 B from `0x0808C158`. So a hang before the watchdog starts never resets.
- **In a task (GUI bitmaps `0x0808F454`, XML temporaries): most likely a watchdog reset, then a boot loop** if the
  same allocation fails on every boot.
  - The supervisor `0x08046994` refreshes only while both task stamps at `0x2400A584` +0 / +4 are within `0xEA5` of
    its own counter (also `src/fault.c`).
  - Inferred, not traced: which tasks write the stamps. The writers are `0x080469C4`, called from `0x08072A40`,
    `0x08091D80` and `0x0809283C`, and `0x080469CA`, called from `0x080A2258`.
- **Either way, a boot-time overflow needs an SD reinstall of stock.**

Neighbouring allocators, for completeness:

- **`0x080443A8`** ("fast"):
  - Requests **above `0x42CC`** go straight to `fw_perm_alloc`, so they land in SDRAM. These are the GUI object
    (`0x90E78`), the 7 delay lines, two 256 KB engine buffers and six 32 KB buffers.
  - Requests up to `0x42CC` are rounded to 16. They come from DTCM `0x20000000 + *(0x24002E80)` while that stays below
    `0x1F800`. When DTCM is full they go to malloc, and when malloc fails to `fw_perm_alloc`.
- **`0x080444B0`**: 32-byte rounding, downward from `*(0x24000090)` (initially `0x24080000`), at most 128 KB. It
  returns 0 on failure.
- malloc and operator new are covered in §4.

### Measured (Unicorn, full boot, real allocators)

| point | low | free (high − low) |
|---|---|---|
| reset | `0xC0000000` | 67,108,864 |
| stock, `main` done (before the scheduler) | `0xC3C683D0` | 3,767,344 |
| **stock, defaultTask's "Initialized" print** | **`0xC3DF4000`** | **2,146,304 (2096 KB)** |
| **JOEBOX 1 full set, same point** | **`0xC3E92F00`** | **1,495,296 (1460 KB)** |

JOEBOX's extra 651,008 B (`0x9EF00`) are fully accounted for. A per-call-site diff of the two boot logs shows only
two differences:

- **`master_alloc`'s block**, `PRISM_BYTES + EXTRA_BYTES` = `0x83900` = 538,880 B. It is allocated inside `main`,
  from JOEBOX's hook at `0x0805462A` in the engine graph build.
- **438 setting stores at 768 B instead of 512 B**, +112,128 B. These are the 64-entry stores, made by the store
  allocator `0x08093E6A` (8 B per entry, allocated on first clear). JOEBOX patches `movs r1, #0x40` to `#0x60` before
  each of the three calls:

  | call | stores at boot | what | JOEBOX patch |
  |---|---|---|---|
  | `0x080949F4` | 432 | cell creation | `patches/duck.py` |
  | `0x08093F28` | 3 | pad defaults | `patches/duck.py` |
  | `0x08094822` | 3 | global settings defaults | `patches/comp.py` |

  The other **2,304 stores have 10 entries (80 B)** and are unchanged: 1,728 from `0x0808FE9A` and 576 from
  `0x0809A184`. All 2,742 stores at 256 B more would have been 701,952 B, which does not match.

Where the stock 64,962,560 B go. The logged request sizes, rounded, add up exactly to the pointer's movement:

| bytes | what (calls) |
|---|---|
| 40,304,640 | PCM sample cache: 615 blocks × 2 × 32 KB (`0x08070C26`, `0x08070C3C`) — §2 |
| 7,680,000 | DJ FX Repeater, 2 instances × 3,840,000 (`0x0806D392`) — §3 |
| 3,932,160 | 9 tables of 1024/2048 × 256 B (`0x080426F4`; inferred: file-name lists) |
| 3,463,168 | delay lines via `fw_line_alloc 0x0806AA80` (7; the stock FX1 delay, Munchi's lines) |
| 2,359,296 | 6 × 384 KB lazy buffers (`0x08063A7C`, purpose not read) |
| 1,732,608 | 576 × 3000 B per-wave buffers (`0x08070C98`, filled with `0xFF`; inferred: waveform overviews) |
| 1,088,000 | 4,250 string buffers of 256 B (`0x0804604A`, allocates on a member's first clear) |
| 1,393,312 | GUI object (`0x90E78`, `0x08044274`) + framebuffers and bitmaps (28 × `0x0808F454`, the largest 4 × 154,112 B) |
| 2,198,208 | 3 × 256 KB engine buffers (`0x0804D7E0` ×2, scanner `0x0807569C`), the 576 wave records (§2), 447 × 1 KB (`0x08063B08`), 2,742 setting stores (`0x08093E6A`: 438 × 512 + 2,304 × 80 B), 579 × 576 B (`0x08077414`) |
| 811,168 | the rest: small objects (engine graph modules, app cells, pointer tables, six 32 KB buffers from `0x08074D1C`) |

### After boot: can it be called, and what else grows it?

**Mechanically, yes.** Nothing marks the end of boot. Stock itself allocates lazily, through three helpers that
allocate a member's buffer the first time the member is cleared (its pointer is still 0):

| helper | buffer | `bl` sites | ran before "Initialized" | allocations then |
|---|---|---|---|---|
| `0x0804604A` (string clear) | 256 B | 76 | 30 | 4,250 |
| `0x08093C7C` (cell store clear) | 512 B | 14 | 8 | 67 |
| `0x08093E6A` (setting store clear) | 8 B × entries | 5 | 5 | 2,742 |

The 46 string sites and 6 cell-store sites that did not run sit in code that loads files or reacts to them:

- the preset loader `0x08096AD8` and its per-cell part `0x08095EC0` (a 512 B store and a string per `0xF0`-byte cell);
- the settings.tml code (it loads the file name's literal at `0x0809E1AC … 0x0809E8E0`), its neighbours
  `0x0809D308`, `0x0809D418`, `0x0809DFA0`, and 14 small initialisers at `0x0809067C … 0x080911C0`, most of them
  called from that code;
- the sample system's two strings at `sys + 0x47E0` / `+ 0x47E4` (512 B once).

All of them are object members, so each costs once per object, not once per call. The growth is bounded, but by
object counts that were not derived. No temporary allocation happened during the whole emulated boot. That confirms
the XML loader `0x080971CC` never ran, since it always takes a temporary block.

On the unit the audioTask (priority Realtime) and the pcmStreamer (Normal) run beside the defaultTask's GUI init. The
preset load is reachable from the pcmStreamer (`0x080743B0 → 0x08092F5C → 0x080922E4 → 0x08096AD8`).

Rules for a runtime allocation:

1. **There is no NULL.** Check `*(0x24000088) − *(0x2400008C)` (or call `0x080443F0`) first, or the unit hangs.
2. **There is no lock.** A call from the audio task can race the pcmStreamer's lazy allocations and its XML parse
   (which moves *high* at the same time). The window is small, but the outcome is two owners of the same memory.
3. **Nothing is freed.** A runtime allocation stays until reboot. Do it once, never per event.
4. **Whatever is taken shrinks the preset-I/O scratch.** The real tinyxml2 (ctor `0x0804AC6C` + `Parse`) was run on
   synthetic Blackbox-shaped presets. The temporary peak was 3.66–3.70 × the file in the first run (`xmlpeak.py`). A
   second generator with short values (the worst case) gave 3.58–3.87 ×, the highest on the smallest file:

   | preset.xml | peak | run |
   |---|---|---|
   | 20,052 B | 3.87 × | verification |
   | 57,813 B | 213,728 B (3.70 ×) | first |
   | 116,796 B | 3.60 × | verification |
   | 132,867 B | 489,840 B (3.69 ×) | first |
   | 309,772 B | 3.58 × | verification |
   | 403,203 B | 1,475,200 B (3.66 ×) | first |

   `0x080971CC` holds its own read buffer (1 × file) through the parse, so a load peaks at **≈ 4.6–4.9 × preset.xml**.
   - With JOEBOX 1's 1460 KB at most, that allows a preset.xml up to about 300–315 KB (stock: about 430–455 KB;
     KB = 1024 B, as the firmware prints), minus whatever the lazy growth takes.
   - Every 100 KB taken from the pool lowers that limit by about 21 KB of preset.
   - The save path builds its document with string copies and was not measured. It may peak higher.

`master_alloc`'s way stays the right one: **once, at boot, sized at build time**.

**Trap: an oversized block stops every boot.** `master_alloc` runs inside `main`. If `EXTRA_BYTES` grows past what
is free, a later stock allocation runs out:

- if it is in `main`, the unit hangs silently;
- if it is in the defaultTask's GUI init (the bitmaps), the unit most likely boot-loops on the watchdog.

The way out is an SD reinstall of stock. A unit test should assert that the total stays below the measured free
figure minus the reserve.

The permanent pool's other call sites are all accounted for:

- 52 of the 54 `bl 0x0804436C` sites ran during the emulated boot.
- `0x08075664` is in the transient scanner's clone `0x08075600` (operator new + 256 KB). Its only reference is the
  vtable word `0x080EAA38`, and A7 found that stock never calls module clones.
- `0x080637CE` is in `0x080637C2` (12 KB), which nothing references.

## 2. The sample pool (576 waves, 615 cache blocks)

Everything hangs off the system object **`0x2400A9C0`**, built by `FUN_08070BF4` (called from `0x0804C1A4`) at boot:

| what | where | size |
|---|---|---|
| **PCM cache blocks** | descriptors at `sys + 0x0000 … + 0x4344`, `0x1C` each, **615** (`0x267`) | buffers 615 × 2 × `0x8000` = 40,304,640 B |
| block descriptor | `+0x04`, `+0x08` two 32 KB SDRAM buffers (`0x2000` floats each, zeroed at boot; inferred: L/R); `+0x0C` block index within the wave; `+0x10` LRU stamp (counter `sys + 0x47CC`); `+0x18` owning wave (`0xFFFF` = free); `+0x1F` state (0 free, 2 owned, 3 seen on a streaming reservation) | |
| wave table | **576** (`0x240`) records × `0x170` B at `*(sys + 0x4348)` | 211,968 B |
| wave id → record | `u16[576]` at `sys + 0x434C` (`0xFFFF` = none) | in the object |
| per-wave buffers | pointers at `sys + 0x8670 + 4·i` → 3000 B each | 1,732,608 B |

- All the `+0x04` buffers were allocated first, then all the `+0x08` ones, so the two arrays sit 20,152,320 B apart.
- The per-wave buffers are 3600 B apart: a 16 B (`0x08070CE8`) and a 576 B (`0x0807742C`) allocation sit between
  them.

**Can the cache be borrowed?** Not cleanly.

- The blocks are allocated once and never resized. The cache allocator (`0x08072F0C`, which prints "Unable to
  allocate PCM blocks for internal sample") looks for runs of 128 free blocks for a streamed wave. Every walk is
  bounded by `0x267` or `sys + 0x4344`.
- Fencing the last *N* descriptors would probably keep the allocator and the two release paths (`0x08072670`,
  `0x08072898`) away from them: state ≠ 0 and an owner ≥ `0x240`, which those paths match against.
- **Unsettled:** the eviction paths (`0x08071E7C`, `0x0807241C`) were not read. A fence also takes the memory from the
  cache: 48 blocks = 3 MB = 7.8 % of it. It is not needed (§3).

## 3. A 16-bit stereo ring of 4 bars at 60 BPM (16 s, 3,072,000 B)

**The pool: no.** It has at most 1.43 MB on JOEBOX, which is also the preset-I/O scratch.

**The Repeater: yes.** The DJ FX pool (`0x24015268`, A5/A7) holds two Repeater instances: **#1 at `0x24015268`**,
**#2 at `0x24015340`**. Each one owns, from the permanent pool:

| field | buffer | bytes |
|---|---|---|
| `+0x3C`, `+0x40` | ring L, R (`+0x38` = 384,000 floats) | 2 × `0x177000` |
| `+0x4C`, `+0x50` | capture L, R (`+0x48` = 96,000 floats) | 2 × `0x5DC00` |

That is **3,840,000 B per instance**, and both runs found it contiguous in that order:

- stock #1 `0xC0435A00 … 0xC07DF200`, #2 up to `0xC0B88A00`;
- JOEBOX the same, shifted up by `0x83900`, because `master_alloc` runs before the DJ FX buffers are allocated.

The four buffers come from four consecutive permanent allocations in `0x0806D392`, with no allocation between them.
It is entered only through `0x0806D388`, which `0x0806CD40` calls once per instance at boot.

Pool in-use flags: `+0x638` #1, `+0x639` #2. After boot the pattern was `01 00 00 00 00 00 00 00 01 00 00 00`: FX A
holds Repeater #1 and FX B holds Crusher #1.

**Where FX A's instance is.** A5's DJ FX container is `engine + 0x28D90`, and its sub-slots are `0x2C` apart from
`+0x20`. With the engine at `0x24037038` (§4), that puts the two slots here:

| slot | address | `+0x18` channel | `+0x20` after boot |
|---|---|---|---|
| FX A | `0x2405FDE8` (`engine + 0x28DB0`) | `0x30300` | `0x24015268` (Repeater #1) |
| FX B | `0x2405FE14` | `0x30400` | `0x24015750` (`pool + 0x4E8`, Crusher #1) |

- Each slot holds the current effect at `+0x20`, the outgoing one at `+0x24` and its countdown at `+0x28`. After both
  boots `+0x24` and `+0x28` were 0.
- The outgoing effect is not processed (A5). The slot process (`0x0806E190`, release at `0x0806E232`) counts it down
  by the block's frames and releases it, clearing its pool flag, once the count reaches 0.
- **So the Looper reads the instance through `0x2405FDE8 + 0x20` every block. A Repeater found at `+0x24` is
  leaving**, and it is released 256 frames (2 blocks) later. These addresses come from the emulated boot. JOEBOX's
  `src/insert.c:64` has the same engine pointer from the unit, but the slot itself was not read on the unit.

**When does stock use #2?** The factory `0x0806CD80` returns #2 only while #1 is flagged in use.

- A slot's type change (`0x0806E048`; `0x0806E368` for the indexed form) works in this order:
  1. It acquires the new object.
  2. It releases any previous outgoing object.
  3. It moves the current object to `+0x24` with countdown `0x100`, and the new one to `+0x20`.
- FX B's type list has no Repeater (A7).
- So #2 is taken only when FX A comes back to Repeater while #1 is still outgoing: within 256 frames (≈ 5 ms) of
  leaving it.
- Executed in two runs (A5's, and the verification run's `fxslot.py`):
  - Repeater → Gater → Repeater in one block lands on #2.
  - With `pool + 0x639` preset to 1, the same switch returns 0 and leaves the slot as it was (`cbz r0` at
    `0x0806E072`).
  - Once the outgoing #1 is released, Repeater gets #1 again.

| option | memory | max ring (int16 stereo) | cost |
|---|---|---|---|
| **A — the Looper is FX A's Repeater object** (A5 route A) | the instance at `0x2405FDE8 + 0x20` | **16.0 s** planar (L in ring L, R in ring R; no contiguity needed) = 4 bars ≥ 60 BPM; **20.0 s** across all four buffers when `+0x40 == +0x3C + 0x177000`, `+0x4C == +0x40 + 0x177000`, `+0x50 == +0x4C + 0x5DC00` (true in both builds) = 4 bars ≥ 48 BPM | none; Repeater mode overwrites the Looper's history, which is harmless |
| B — Repeater #2, fenced | `pool + 0x639` = 1, set once at boot | same, independent of FX A (for the Master FX fallback slot) | a Repeater → X → Repeater switch within ≈ 5 ms is dropped: the factory returns NULL and the slot keeps its old type (executed) |
| C — fence PCM cache blocks | 48 blocks = 3 MB | — | unsettled (§2), smaller cache |
| D — the pool | ≤ 1.43 MB free | — | does not fit |

Max Len cap: `bars = frames × BPM / (48000 × 60 × 4)`. With 768,000 frames (16 s), 4 bars need ≥ 60 BPM; with
960,000 frames (20 s), ≥ 48 BPM. In route A planar, the capture buffers (768,000 B) stay free for Looper scratch.

**Cache.** The MPU setup `0x0804409C` makes SDRAM region 8: base `0xC0000000`, size code `0x19` (64 MB), TEX 0,
C 1, B 1 (normal memory, write-back, no write-allocate), not shareable, XN.

- A ring that only the CPU reads and writes needs nothing.
- Anything a DMA reads from it (USB audio, SAI) must first be cleaned from the data cache.
- JOEBOX's own USB audio ring already sits in SDRAM (`src/usbdev.c`, `RING_OFFSET`). The CPU copies it into the USB
  FIFO, so it needs no cache maintenance.

## 4. JOEBOX's claims, checked

- **Heap.**
  - Heap bounds (from the malloc literals at `0x080C8964`): `0x2402F214 … 0x2405FF54`, 200,000 B, with its free list
    at `*(0x240000E0)`.
  - The allocator `0x080C88CC` carves from the *top* of the chosen block; the engine's address shows it. That it is
    best fit was read statically only.
  - operator new is **`0x080CAAC4`**: it calls malloc through `0x080CAAA0` (new-handler loop), then aborts with
    "bad_alloc was thrown in -fno-exceptions mode" — a hang.
  - The engine (`0x28F18` = 167,704 B, `0x0804C1C6`) is the **first and only** malloc of the boot. It lands at
    `0x24037038 … 0x2405FF50`, the address JOEBOX read off its unit (`src/insert.c:64`).
  - That leaves 32,288 B in one free block: the firmware's own "Internal = 31KB".
  - **Who else can reach malloc, checked site by site.**
    - malloc has two `bl` callers: the fast allocator's fallback `0x080443D6` and operator new's loop `0x080CAAB0`.
      It has no `b.w` and no pointer word anywhere in the image.
    - operator new has **16** `bl` sites. One is the engine's.
    - Each of the other 15 is a small clone method (`new(size)`, then the class's ctor). None has a `bl` caller, and
      each is referenced by exactly one vtable word, for example `0x08075600` by `0x080EAA38`.
    - So after boot malloc is reached only by a module clone (A7: stock never calls them) or by the fast fallback,
      which needs DTCM full (69,072 B were free).
  - **Confirmed:** "operator new takes 167,704 of the 200,000 bytes in one block and hangs on failure". Anything
    malloc'd before the engine above 32 KB breaks the boot.
- **Patch RAM** `0x2405FF54 … 0x24060000` (172 B), JOEBOX's use:

  | from | struct | bytes |
  |---|---|---|
  | `0x2405FF60` | solo | 16 |
  | `0x2405FF70` | duck | 48 |
  | `0x2405FFA0` | slice anchor | 1 (+3 pad) |
  | `0x2405FFA4` | chord | 44 |
  | `0x2405FFD0` | cpu | 36 |
  | `0x2405FFF4` | filter's read park | 12, up to `0x24060000` |

  **Confirmed full**, except 12 unclaimed bytes at `0x2405FF54 … 0x2405FF5F`.
- **Backup SRAM** (4 KB at `0x38800000`), from `src/` literals and struct sizes:
  - od bank `0x000–0x384` · fault trails `–0x3C8` · bank-2 words `–0x3D4`;
  - comp `0x400` (Smash overlays it) · usbdev `0x650–0x680` · rotate `0x6F0` · seqfix `0x700–0x908` · USB-MIDI queue
    `–0x988` · motion `0x990–0x9BC`;
  - fx2 `0xA00–0xA5C` · FX2_OBJ `0xB00` · munchi `0xB10–0xB1C` · master UI `0xB1C` · VHS line `0xB20–0xF20` · gl
    `0xF20–0xF68` · Prism words `0xF70` · fault records `0xF78–0x1000`.
  - The holes total about 430 B. The largest is about 164 B at `0xA5C`. **Confirmed full** for anything ≥ 256 B.
  - **Side finding (JOEBOX bug, 4 bytes):** `struct comp_state` is 596 B (`0x254`), so it runs from `0x38800400` to
    `0x38800654`, while `usbdev_state` starts at `0x38800650`.
    - `la[71][1]` is the same word as `usbdev_state.setup[0..3]`.
    - That word is written on every compressor (re)initialisation (the clear loop over `LA_MAX` = 72) and every 72nd
      frame under Limit (lookahead 72).
    - This is upstream's to fix (move usbdev, or end comp at `0x650`).
- **Two more small spaces stock leaves alone after boot** (not needed for this plan):
  - **DTCM** `0x2000EA30 … 0x2001F800`, 69,072 B. All 31 fast-allocator sites ran during the boot. One of them, the
    GUI method `0x08093C66` (2 KB), could run again. Directly above the range, `0x2001F800 … 0x20020000` is the
    MSP / interrupt stack.
  - **AXI** `0x24060000 … 0x240633E0`, 13,280 B. All 13 sites of `0x080444B0` are boot-time, and no image literal
    points into that range. The MPU makes `0x24060000–0x2407FFFF` **Device memory** (regions 4/5: TEX 0, C 0, B 1;
    set at `0x0804409C`), so only aligned accesses are allowed there.
  - The FreeRTOS heap is separate: `ucHeap` `0x24016178`, `0x9000` B (heap_4, `0x08087CD4`).

## Recommendation

1. **CW state (`cw_bank`, ~1 KB)**:
   - SDRAM behind JOEBOX's block at `PRISM_BYTES + EXTRA_BYTES` (= `0x83900`), with `EXTRA_BYTES` += `0x400`;
   - magic cleared in `master_alloc`;
   - `master_block() == 0` → feature off.

   This is exactly the plan. It leaves at most 1,494,272 B free at "Initialized".
2. **Looper ring**: route A. Use the buffers of the Repeater object that FX A holds.
   - Read the object through `0x2405FDE8 + 0x20` every block and do not cache buffer addresses across type changes.
     A Repeater at `+0x24` is leaving.
   - Planar int16, **16.0 s guaranteed**: `Max Len` 4 bars at ≥ 60 BPM, capped by the formula above.
   - **20.0 s** when the contiguity check passes.
   - If the Looper ends up in the Master FX slot, use Repeater #2 with `pool + 0x639` set at boot.
   - Looper bookkeeping (indices, HPF state) goes in `cw_bank` or in the capture buffers.
   - CPU access only. A DMA reader needs a cache clean first.
3. **No new `fw_perm_alloc` calls after boot.** Total new permanent SDRAM for the fork ≤ ~0.4 MB. Add a test that
   fails the build when `PRISM_BYTES + EXTRA_BYTES` passes the budget. Lower the budget if the unit's free figure after
   a preset load comes in well under 1460 KB.

## Open, and what settles it

- **The free figure on the unit, and its growth in use.** On the dev build (USB peek, `src/usbdev.c`), read
  `0x2400008C` and `0x24000088` right after boot. JOEBOX 1 full should read at most `0xC3E92F00` / `0xC4000000`. Read
  them again after loading Thomas's largest preset and after playing for a while. The difference is the lazy growth
  that no emulation counted.
- **The size of Thomas's largest `preset.xml`** (on the card). With the ×4.9 rule it settles the reserve.
- **The preset save peak**: run the writer `0x08095328` under the same harness on a full app state.
- **The FX A slot on the unit**: peek `0x2405FDE8 + 0x18` (expect `0x30300`) and `+0x20` (expect `0x24015268` with
  FX A on Repeater).
- **Which tasks feed the watchdog stamps** (`0x080469C4` / `0x080469CA` callers): this decides whether a task-time
  overflow resets or hangs. It matters only for the trap, not for the plan.

## Verification

An independent verifier re-ran the boot with its own harness (`re-scratch/vx2/m7boot.py`, `run_m7.py`). It started
from the real reset vector including SystemInit, let the real thread creation run, and cleared peripheral polls by
flipping the polled register instead of stubbing. It got every pointer and free figure above to the byte. These
points were challenged and settled again here:

| point | challenge | settled by | result |
|---|---|---|---|
| JOEBOX's +112,128 B | "2,742 stores at 768 B" was wrong | per-site diff of both boot logs (`fix/sitediff.py`), a re-run boot tapping `0x08093E6A`'s callers and sizes (`fix/run_boot_taps2.py`), the entry-count immediates before the five calls in both images | **corrected**: 438 64-entry stores grew (432 + 3 + 3); the 2,304 10-entry stores did not. The totals stand |
| free figure | no file was read in either emulation | the re-run boot logged 0 temporary allocations, and a site count of the lazy helpers | **corrected**: the figures are upper bounds; the growth is unmeasured |
| overflow outcome | a hang in `main` and one in a task differ | static read of main's call order and the watchdog init `0x08046938` | **added**: silent hang in `main`, likely watchdog boot loop in a task |
| fast allocator | requests above `0x42CC` skip malloc | instruction read plus Unicorn (`fix/permedge.py`) | **corrected** |
| operator new sites | 16, not one | `bl` scan of the image, `b.w` and pointer-word scan for malloc, vtable references of the 15 clone thunks (`fix/newsites2.py`) | **corrected and checked** site by site |
| `fw_perm_alloc(0)`, write-before-check | edge cases | Unicorn (`fix/permedge.py`) | **added**, executed |
| FX slot addresses, `+0x24` outgoing | route A detail missing | own boot snapshots (both builds), static read of `0x0806E048`, A5's container layout | **added** |
| SDRAM cacheability | missing | instruction read of `0x0804409C` (region 8) | **added** |

Confirmed unchanged by the verifier (its own runs or reads): the pool pointers and allocator semantics, the hang
path, the XML ratio (with its own generator, folded into the table above), the 52/54 site coverage, the sample-pool
layout, the Repeater buffers, flags and contiguity, the heap bounds and engine address, the Patch RAM and backup SRAM
maps, the comp/usbdev overlap, the DTCM/AXI spare ranges and the MPU regions 4/5.

## How this was checked

- **Boot under Unicorn** (stock image only; scratch `/srv/dev/firmware/re-scratch/x2/boot.py`, `run_boot.py`):
  - The reset handler's `.data` / `.bss` / heap / `.init_array` work runs as is.
  - `main 0x08044188` runs whole up to the scheduler start. Three hardware-only functions are stubbed (clock setup
    `0x08043E84`, a HAL poll `0x08078AF0`, USB-host init `0x08044DA0`); a call-graph walk shows none of them reaches
    any allocator. HAL tick and delay are stubbed, M-profile `cpsid` / `msr` / `mrs` are skipped, and thread creation
    is only recorded.
  - Then the defaultTask `0x08043DEC` runs to its own print. The two numbers are the firmware's own computation (heap
    free list, high − low).
  - Every allocator ran its real code and was only tapped. The logged permanent requests sum exactly to the pointer's
    movement.
  - The same harness ran `out/gate0/full/BLACKBOX.bin` for JOEBOX 1.
  - Re-run for the corrections with extra taps on the three lazy helpers (`x2/fix/run_boot_taps*.py`, 29 s). It
    reproduced `0xC3DF4000` / 2096 KB.
- **Fixes** (`/srv/dev/firmware/re-scratch/x2/fix/`): `sitediff.py` (per-site diff of the two logs), `bysite.py` /
  `fastbig.py` (the breakdown table), `permedge.py` (allocator edge cases executed), `newsites2.py` (operator new
  sites).
- **XML peak:** the real tinyxml2 ctor + `Parse` on three generated presets, watching writes to `0x24000088`
  (`xmlpeak.py`). The verifier's `vx2/xml2.py` used a second generator.
- **Repeater buffers, flags, contiguity and the FX slots:** read from the emulated RAM after both boots.
- **Read statically (decompiler + listing, inferred unless executed above):** the factory / slot / release logic,
  the sample-pool layout, main's call order, the watchdog init and supervisor, and the MPU regions.
- **JOEBOX maps:** grep of `src/` plus struct sizes from host `gcc -m32 -ffreestanding`. `seq_clock`'s ARM layout
  (8-byte `int64` alignment, 520 B) was checked by hand. The verifier recomputed the Patch RAM sizes by hand.
