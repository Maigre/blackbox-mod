# Decisions — blackbox-mod (Thomas's fork)

Dated, with the reason. The plan is `notes/plan.md`; the hub tracks the tasks (`37Projects/projects/blackbox`).

- **D-001 (2026-10-15) — Base and shape.** Fork JOEBOX (j3threejay/blackbox-mod, MIT) rather than PocketRave or a
  fresh start: C in the cave, Unicorn suites, a browser patcher, and the stock internals already mapped. `main` is an
  untouched mirror of upstream; `maigre` is Thomas's integration branch and holds `notes/`; every feature is a
  `feat/<name>` branch cut from `main` so it can go upstream as one PR. Upstream squashes releases, so PRs are
  expected to be ported by hand.
- **D-002 (2026-10-15) — Slip is one row, one accelerating knob.** Stored in clock ticks (960/beat, ±3840 = ±1 bar),
  shown as beats.ticks; slow turn = 1 tick, fast turn = 60 ticks (1/64). Two coarse/fine rows were the cheaper code,
  Thomas prefers one knob.
- **D-003 (2026-10-15) — Region defaults to Auto.** A Clip pad plays the Sample-mode loop region [LpStr, LpEnd) when
  the pad has loop points, the whole file otherwise; `File` / `Loop` force it. Fresh recordings and plain files
  behave as stock. This removes the destructive Trim step from Workflow 1.
- **D-004 (2026-10-15) — Loop Len anchors where the music is (KP3 feel).** The window starts at the grid position
  where Loop Len was engaged, stays while it is on, clears on Off (the full loop resumes in phase); Slip shifts it.
- **D-005 (2026-10-15) — Looper FX on the XY page.** Touch = loop in on the grid, release = live (KP3), `Hold` latches
  (Traktor); X = Loop Len 1/16 … 4 bars (in-point fixed), Y = HPF cutoff on the loop (Thomas: "HPF if possible");
  knobs `Source Mix|In`, `Max Len`, `Slip`, `Hold`. Ring buffer in SDRAM, 16-bit stereo, Max Len bars.
- **D-006 (2026-10-15) — Save to a slot = resample via the stock recorder** (Rec Input Resam, Rec Quant 1 bar,
  Length = Max Len, RecToPlay), Loop Len/Slip copied to the pad. Zero file code; costs N bars of real time. A direct
  memory→WAV write is P6.
- **D-007 (2026-10-15) — The fork's images say `MAIGRE 1` on TOOLS** (`src/release.h`, fork-only commit, never in a
  `feat/*` branch): a bug report from this fork must never look like a JOEBOX build.
- **D-008 (2026-10-15) — First installs go without `BBEXTRA.BIN`.** JOEBOX 1 is on hold for units stuck restarting
  after the bank-2 self-install; none of our P2–P3 code needs bank 2. The full set without the second file keeps
  every bank-1 feature (Prism/Confetti/Insert read `---`). *Premise superseded by D-017 from P3 on: Loop Len needs
  bank 2.*
- **D-009 (2026-10-15) — Host DSP build on any C compiler, ARM-vs-host tolerance 1e-5.** mgr-ran (i7-3770K) has no
  FMA; the Cortex-M7 fuses multiply-adds, so the S950 Lo recursion drifts a few ulp between the two builds (misses
  at 2e-6, passes at 1e-5; a wrong coefficient misses by 1e-3+). `host/build.sh` and the `render_*.py` helpers take
  `CC`, then clang, then cc; the `.dylib` name stays (dlopen does not care). Candidate upstream PR `feat/host-linux`.
- **D-018 (2026-10-16) — Bank-1 room: the Clip Window's maths in bank 2; Slip and Region need `BBEXTRA.BIN` too;
  updates D-017** (Thomas at Gate 3: "move everything (that can be moved) to bbextra then so we give back room now",
  the room Fit and Loop Fade need, `#t-023`). Every piece of the Clip Window's own code that is maths or policy moved
  from `src/clipwin.c` to `src/clipwin_b2.c`, fourteen leaf `cw_*` functions: H1's latch (Slip's shift, the region,
  Loop Len's window: the design's R4), H2's slot decode, mapping and seam hint, Region's rule (R9) and its adoption
  from the class-H object or the store, the lengths H3 tells and the one-step clip's timing, the wrap-grid hold, the
  poll's clamps and pad check, the guarded drop, Loop Len's take with the Sync param-set message it builds (R6), the
  Slip knob's tiers and detent (`clipwin_turn` stays the hook; `cw_turn` returns what the stepper gets), the Slip
  row's beats.ticks text (no `snprintf`), the Waveform bracket. Bank 1 keeps the hooks, every stock call, the bank's
  set-up and the Waveform's binding; `bank()` asks `b2_live()` first. JOEBOX's own code (Munchi, the filter, master,
  insert, comp) did not move. Measured (`arm-none-eabi-size -A out/cave.elf`): `.cave` 57 624 → 56 312 B (112 → 1 424
  B free), `.bank2` 13 540 → 15 412 B; payload header id `0x78b96508` len `0x3c60` sum `0xc8978c56`. Consequences,
  accepted by Thomas: (1) without this build's `BBEXTRA.BIN` every Clip pad plays as stock: Slip, Region and Loop Len
  do nothing (the rows stay, turn and save), the Slip row reads stock's plain tick count and turns as a stock number
  row, the Waveform shows no bracket (its four rows still bind) (README Known issues). (2) Slip 0, Region File and
  Loop Len Off stay bit-identical to stock with or without bank 2: `test_clipwin.py`'s no-bank-2 checks now wipe the
  header before the first poll (the first `b2_live()` caches its verdict for the boot), and add a run with all three
  set (bit for bit every clipwin hook taken out) and one at Slip 0 / File / Off (bit for bit the stock image). (3)
  Every bank-1 call into bank 2 is behind `b2_live()`, and bank 2 calls nothing outside itself (`test_bank2.py` plants
  a `bl` in every `cw_*`). (4) What bank 2 is compiled against is now all of `cw_bank` and the pad, class-H, segment,
  stepper and waveform fields, pinned by `_Static_assert` in `src/clipwin.h`; the layout itself did not change (still
  `CWN5`, so `bench/bbusb.py` reads it as before). (5) The knob's tuning numbers (`KNOB_MEDIUM`, `KNOB_FAST`,
  `KNOB_STEP_MEDIUM`, `SLIP_GRID`, `ZERO_DETENT_MS`) live in `src/clipwin_b2.c` now: retuning the knob means a new
  bank-2 payload. (6) Cost, measured under Unicorn (instructions executed in the cave and bank 2 per engine block, one
  playing Clip pad, cell 0x102, `test_clipwin.py`'s rig, 300 blocks, the boot's one-time payload check left out):
  Slip 0 / File 360 → 454, Slip 480 469 → 569, Slip 480 + Region Loop 534 → 634, Loop Len 1/4 409 → 503: about +95 a
  block a pad (one `b2_live()` per hook call, a few reads of `cpu.c`'s state, and the calls across). Sixteen such pads
  would be about 1.6 k instructions, roughly 0.1 % of a 2.67 ms block at 480 MHz. Also new: `clipwin_len` reads the
  four store rows at every site-1 recompute, adopted or not (it read them only when adopting): a few lookups a
  recompute, not a block. Not measured on the unit (TOOLS' load is the check). A unit with this `BLACKBOX.bin` needs
  this build's `BBEXTRA.BIN` written by the card loader before any Clip Window check (TOOLS: no `!`).
- **D-017 (2026-10-16) — Bank-1 overflow goes to bank 2 now; Loop Len needs `BBEXTRA.BIN`; supersedes D-008's
  premise** (Thomas: if the cave overflows, move code to bank 2 rather than trim). The P3 Waveform knobs cost ~510 B
  against 48 B free after Loop Len, so Loop Len's take (`cw_looplen`, `src/clipwin_b2.c`, 522 B) moved to bank 2. On
  the `37loop/blackbox-t-018` stack (P3 over the stale-latch fix, which left 0 B after Loop Len) Loop Len's window
  (`cw_window`, latch()'s per-segment maths) went first, in the "bank 1 room" commit, with three bank-1 trims.
  Rules: bank 2 holds only leaf code that calls nothing outside itself (`test_bank2.py`), and every bank-1 call into it
  is gated by `b2_live()`, falling back to the stock-like value (Loop Len Off) when bank 2 is absent or stale.
  Consequences: (1) P3 needs the `BBEXTRA.BIN` from the same build on the card, beside `BLACKBOX.bin`; without it the
  Loop Len row stays live and saves but does nothing (README Known issues; the `---` alternative is open question 30
  in `notes/re/README.md`). (2) Bank 1 pairs with the whole payload at once, on its sum (`cpu.c` `b2_paired`): this
  `BLACKBOX.bin` on a unit whose bank 2 holds an older payload switches off Prism, Confetti, the inserts AND Loop Len
  until the card loader has written this build's `BBEXTRA.BIN`. Payload headers: release 37.1.1 through the Loop Len
  step (the same bytes) id `0xf5f0171b` len `0x3280` sum `0xbd37e09e`; on feat/region with the Waveform knobs id
  `0xfd79d330` len `0x3480` sum `0x1c178ca6`; on `37loop/blackbox-t-018` with the window (bank 1 room) id `0x15a78d08`
  len `0x3300` sum `0xd5c53b2d`, and with the knobs id `0x2c4676ca` len `0x3500` sum `0x73f8a581` (the cw_bank offsets
  bank 2 reads moved with the stale-latch fix's `len`: latch stride 16, origin `0x5c0`).
  (3) Gates 0 and 2 ran without the file, so Gate 3 is the first install on Thomas's unit that needs the card loader
  to write bank 2: TOOLS must show no `!` before the Loop Len checks. The restart loop D-008 steered around turned out
  to be the exclusive load in `b2_paired`, fixed in 37.0.2 (D-013). (4) What bank 2 is compiled against (the
  `cw_bank` and pad offsets in `src/clipwin.h`) is pinned by `_Static_assert`; bank 2's id still hashes its `.c` files
  only, so a bank-1-only edit of the header needs no reflash. *Updated by D-018: not only Loop Len, all of the Clip
  Window's maths is in bank 2 now, so Slip and Region need `BBEXTRA.BIN` too.*
- **D-016 (2026-10-15) — Slip: + = ahead, like a CDJ jog; replaces D-014** (Thomas, after Gate 2: "CCW would slower
  the record, like a turntable or CCW on a CDJ"). Clockwise pushes the loop ahead of the beat, counter-clockwise drags
  it behind, and the number follows the knob: `+` ahead, `−` behind. The engine reads the row as it is (the content's
  shift); test_clipwin.py's direction check: -0.480 plays every sample 12 000 samples later at 120 BPM. Same session:
  the knob gives single ticks slow, one 1/64 (60 ticks) a turn event fast, snapped to the 1/64 grid, and a turn stops
  on 0 (held while it goes on; a 250 ms pause or the other direction moves on) — Thomas: "tricky to set back to 0".
  *The knob part is revised in 37.2.1 (t-021; the feel is Thomas's to approve on the unit): 0 is a detent the same
  turn passes 150 ms after it arrived, and a medium tier (10 ticks a turn event) at speeds 3–4, the 1/64 at 5–6.*
- **D-015 (2026-10-15) — Ideas parked (Thomas: "later").** (a) A colour theme + splash branding, data-only (no cave
  bytes): the UI palette is 33 ARGB32 at `0x080F1D84` in 3.1.9, cyan accent `#09D7F5` at slots 4 6 9 26 28 30 (checked on
  our image; found by unremarkablegarden/blackbox-firmware-hacking, no license there: facts only, credit them). It would
  close JOEBOX issue #1, which is that author's offer. (b) For P4's Looper engine: DaisySP's `Looper` (MIT; JOEBOX already
  vendors DaisySP for Munchi) has record / overdub / replace modes over a buffer. That repo is not a base: data patches
  only, a bare-metal skeleton that boots nothing, and docs wrong for this unit (H750, "the encoder", stock USB-MIDI).
- **D-014 (2026-10-15) — Slip: + = later** (Thomas) — *replaced by D-016 the same evening*. The row's value pushes the hits behind the beat (`+0.480` = half a
  beat late). Inside clipwin.c, slip[] and the latches hold the content's shift, which goes the other way: the tick reads
  the row negated. test_clipwin.py's `store()` speaks the engine's shift (so its numbers stay), `store_raw()` the row's;
  a direction check proves +480 plays every sample 12 000 samples after stock at 120 BPM.
- **D-013 (2026-10-15) — The restart loop is an exclusive load in Device memory; fixed in 37.0.2.** Gate 0 step 2 (the
  full JOEBOX-1 set, dev build, NO `BBEXTRA.BIN`) looped on Thomas's unit: splash, Pads, reset every 4.1 s. Read over
  USB from the looping unit (`bench/bbusb.py catch`): src/fault.c's record, the same every boot — precise bus fault
  (CFSR 0x8200) at BFAR 0x2405fff3, PC in `b2_paired` (`cpu.c`) on `ldrexb`, reset by the recorder (RSR SOFTWARE). A plain
  USB read of that word worked (not ECC). The MPU, read live: regions 3-5 make 0x24050000..0x2407ffff Device memory
  (TEX0 C0 B1); patch RAM 0x2405ff54.. is inside, and an exclusive access there goes to the AXI bus, which errors.
  Fix: the four `__atomic_*` on `b2chk` become one read-modify-write with interrupts masked (`b2_change`); no
  LDREX/STREX left in the cave. 37.0.2d then booted cold with no fault and no watchdog record, stayed up, and free
  SDRAM read 1,495,296 B on the unit — X2's emulated figure to the byte. Unit: STM32H743 (0x450) rev V (0x2003),
  D-cache on, bootloader file 1.7.F on the card. Why other units (the maintainer's) survive the LDREXB is not known —
  candidate: MPU state left by a different bootloader. Upstream-worthy on its own: JOEBOX 1's hold is likely this — sent as
  j3threejay/blackbox-mod PR #2 (branch `fix/restart-loop-ldrex`, `01b5699`, with a no-exclusives check in test_cpu.py).
  Rule for every feature from now on: no atomics or exclusives on patch RAM or anything in 0x24050000..0x2407ffff.
- **D-012 (2026-10-15) — Release names are 37.x.y** (Thomas): `RELEASE_NAME` "37.<feature step>.<build>", dev builds
  the same with a `d` (`DEV_NAME`, USB peek / poke compiled in). 37.0.x = JOEBOX 1's code with none of the fork's
  features; 37.1.x will be Slip (P2). Replaces D-007's `MAIGRE 1`. Fork-only, never in a `feat/*` branch.
- **D-011 (2026-10-15) — Keep every JOEBOX feature; make bank 2 reliable before P4.** Measured: bank-1 cave has
  ~4.1 KB free (53,616 of 57,736 B used), enough for P2+P3 (≈2.5 KB) but not for the Looper + Save + shortcuts
  (≈4–6 KB more). SDRAM is fine (1,460 KB free at boot; the Looper ring borrows FX A Repeater's 3.84 MB, X2), and so
  are pad slots (14 free); param ids are tight (8 free) — enlarge the 500-entry table rather than take JOEBOX's.
  Thomas keeps all four groups (sound shaping, effects, sequencer extras, live I/O): nothing is stripped. Room comes
  from bank 2 (~770 KB, leaf DSP), whose self-install is JOEBOX 1's restart bug → find and fix it first, offer the
  fix upstream. Small companion fix: allocate Prism's and the inserts' SDRAM (~490 KB) only when bank 2 is live.
  Fallback only if bank 2 cannot be made safe: a fork-only lean build (`MUNCHI=0` frees 6.7 KB, upstream's own switch).
- **D-010 (2026-10-15) — Builds are not byte-identical to upstream's releases** (Arm GNU 14.2 here vs the
  maintainer's toolchain: 782,200 B vs 781,840 B for the same sources). The Unicorn suites are the proof of a build,
  not the sha; ask the maintainer which gcc he uses (first-contact item).
