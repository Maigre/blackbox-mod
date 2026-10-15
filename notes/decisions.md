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
