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
  every bank-1 feature (Prism/Confetti/Insert read `---`).
- **D-009 (2026-10-15) — Host DSP build on any C compiler, ARM-vs-host tolerance 1e-5.** mgr-ran (i7-3770K) has no
  FMA; the Cortex-M7 fuses multiply-adds, so the S950 Lo recursion drifts a few ulp between the two builds (misses
  at 2e-6, passes at 1e-5; a wrong coefficient misses by 1e-3+). `host/build.sh` and the `render_*.py` helpers take
  `CC`, then clang, then cc; the `.dylib` name stays (dlopen does not care). Candidate upstream PR `feat/host-linux`.
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

P4 (Looper FX, `feat/looper`). D-017..D-019 are left to P3 on `t004`. D-020..D-023 are **proposed: they change the
plan and need Thomas's OK** before Gate 4; D-024 is how it was built; D-025 is what the review changed, with three
more points for Thomas. The feature's own doc is `notes/features/looper.md`.

- **D-020 (2026-10-15, proposed) — `Source: Mix | In` is two FX A types, not a row.** The XY page has no knob rows
  (A5), so FX A lists Repeater, Gater, Filter, **Looper** (Mix: Out 1 at the DJ FX point, so pads + returns + EQ +
  the input when it is monitored on Out 1) and **Loop In** (the audio input alone; it replaces the monitored input,
  or plays on top of Out 1 when the input is not monitored there). No id, no page, picked on the XY page itself.
  Switching between the two restarts the ring (it held the other source), as any DJ FX type change cuts.
  "Replaces" is exact only with the master EQ flat: the EQ runs between the recorder's monitor and the DJ FX (A6
  step 8), so with EQ the difference EQ(in) − in stays under the loop; a JOEBOX `Input:` pad playing the same input
  is another copy that is not removed. An exact fix needs the input's contribution before the EQ; README Known issue.
- **D-021 (2026-10-15, proposed) — `Hold` is the stock XY Hold button** (msg `0x1a`, `APP+0x2C`); no new parameter.
  Hold alone engages with the last length and the HPF open. The view's rest posts (X = 1/2, Y = 50 % after a Hold
  toggle and before a finger-up with Hold off) are ignored; X / Y moves while looping are applied one block late, so
  rest posts that race ahead of their release (UI and audio are separate tasks) are dropped by it. The same race on
  the other two gestures is handled too (D-025): a Hold toggle's rest posts drained a block late are still skipped,
  and a touch-down whose X / Y have not been drained yet waits one block for them.
- **D-022 (2026-10-15, proposed) — `Max Len` waits for P5, `Slip` for the `t004` merge.** v1 loops the length on X,
  capped by the 16.0 s ring at the tempo: 4 bars at 60.1 BPM or faster, else 2 bars. P5 adds `Loop Max` next to
  `Loop Rec` (id `0x1cd` reserved), where Save needs it. Looper Slip reuses `clipwin_format` / `clipwin_turn` and has
  no knob home yet (P6 `Y Ctl`, or new knob widgets on the XY view).
- **D-023 (2026-10-15, proposed) — X = 7 zones, Y = stock `HPF:`.** X is the new list `0x1cc` "Length:" with stock's
  Clip Quant names (4 bars, 2 bars, 1 bar, 1/2, 1/4, 1/8, 1/16; `0x080ECB0C`, no new strings), left = longest as on
  the Repeater; not the plan's 9 (8 bars cannot fit the ring, None means nothing on an axis). Y is stock param `0x30`
  (EchoHP's `HPF:`, 0..1000): 0 = the filter out entirely, then 10 Hz .. 4 kHz (10 × 400^y), 12 dB/oct, Q 1 (0 dB at
  the cutoff, -3 dB at 0.79 of it). One new param id: `0x1cc`; `0x1cd..0x1cf` stay free for P5.
- **D-024 (2026-10-15) — Built as route A.** The Looper is FX A's own Repeater object in modes 3 / 4: the index is
  latched in the slot setter (`b.w` at `0x0806E174` → `looper_fxa_set` → `looper_latch`, class `0x40` for both), the
  axis table is relocated into the cave (4 literals), the Repeater's process (`+0x0c`) and active (`+0x70`) are
  wrapped; hold and set_param are not (the DSP reads the channel's queue itself). The ring is int16 planar in that
  Repeater's two ring buffers (768,000 frames, 16.0 s); leaving Looper mode resets the Repeater and zeroes the last
  2048 floats of both (its backfill would read our int16 pairs as floats, NaN included). Bank 1 glue 673 B; the DSP
  (`looper_dsp.c`, 3.2 KB) is in bank 2 behind `b2_live()`, so Gate 4 needs a new `BBEXTRA.BIN`. State: 0x200 B at
  `PRISM_BYTES + 0x2d900` in master.c's block (`EXTRA_BYTES` 0x2db00; 0x2d100..0x2d900 reserved for the Clip Window's
  bank so neither offset moves at the merge). The in-point comes from duck_block's tick snapshot, so it is within half
  a tick of the grid (0.26 ms at 120 BPM); the pass lengths carry their fractions, and the grid lock of D-025 keeps
  the passes on the grid when the tempo is not the catch's.
- **D-025 (2026-10-16) — The v1 review: what changed.** Two reviewers (hooks / ABI / races, and DSP) re-run here; all
  fixes are in bank 2 (`looper_dsp.c`), bank 1 is unchanged; `test_looper.py` T8, T9, T12, T13 and T17 carry a case
  for each. **Fixed**: a re-catch inside the release of a held loop that had stopped the ring left it stopped and
  replayed audio up to 5.5 s old (`lp_engage` restarts the ring); a 64-frame crossfade cut short by another jump
  (a jump landing near an out-point, a stopped re-catch) stepped by up to 0.42 (now declicked); X longer kept the
  read head where it was, so after 1 bar → 1/16 → 1 bar the bar played off the bar lines for good (the pass count
  since the in-point now puts the read head where the new length's loop is on the grid, both ways); the loop drifted
  without bound off the grid at any tempo but the catch's, 48 ms a minute at 0.1 BPM off (a grid lock: each block
  the pass's end is held against the grid's next line, and moved when more than 2 ticks apart; PLAY re-phases);
  Loop In under Resam looped last block's Out 1 and doubled it, looped a jack set to CV, and changed level when the
  recorder started listening (it reads the raw input at the audio object now, × Rec Gain, a non-AUDIO jack silent);
  Loop In on top doubled the live input until its first out-point (it adds nothing while live now); the split
  touch-down and split Hold races (D-021); more than 32 posts in one drain could push out the release (`lp_gather`
  keeps one X and one Y per run). README's "60 BPM or faster" was wrong at exactly 60. **Not changed**: the
  master-EQ residue of Loop In (D-020, doc); the 16-bit loop's undithered floor (−78 dBFS; a dither would add hiss to
  every loop; README). **For Thomas** (each is a small change to turn back): (a) a touch loops the cell in progress and
  is heard when it comes round, as the plan says — the alternative is to loop the last complete cell at once, still
  on the grid; (b) after a tempo change the loop stays on the grid, each pass cut or run on to the new length
  (v1 kept the catch's length and drifted); (c) X longer re-phases to the grid (v1 kept playing on).
