# Decisions — blackbox-mod (Thomas's fork)

Dated, with the reason. The plan is `notes/plan.md`; the hub tracks the tasks (`37Projects/projects/blackbox`).

- **D-001 (2026-10-15) — Base and shape.** Fork JOEBOX (j3threejay/blackbox-mod, MIT) rather than PocketRave or a
  fresh start: C in the cave, Unicorn suites, a browser patcher, and the stock internals already mapped. `main` is an
  untouched mirror of upstream; `maigre` is Thomas's integration branch and holds `notes/`; every feature is a
  `feat/<name>` branch cut from `main` so it can go upstream as one PR. Upstream squashes releases, so PRs are
  expected to be ported by hand. *Refined by D-019: the feature branch is the feature's source of truth, and `maigre`
  (upstream + every feature as if accepted + the fork layer) moves only by merges.*
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
- **D-036 (2026-11-12) — JOEBOX 2 is merged; the Clip Window's ids move to `0x150..0x154`** (hub #t-047, #t-052).
  JOEBOX 2's TapeScam registers `0x1c8..0x1cf` as global settings, where Region, Slip, Loop Len, Fit and TL Knob
  sat. The registry keeps one entry per id and the later registration wins, so one of the two would have become the
  other's control. Ours move, same order, into the `0x13c..0x17b` gap stock registers nothing in and upstream uses
  only at `0x143..0x14d`, `0x15c..0x162` and from `0x170`. Presets key on the xml names (`clipregion`, `clipslip`,
  ...), which do not move: a saved preset loads as before. The Pos page rows, the bench mailbox, `bbusb.py` and the
  suites follow.
- **D-037 (2026-11-12) — On a Clip pad a Region wins; with no Region the pad plays JOEBOX 2's selection** (Thomas:
  « selection-unless-region », hub #t-052). JOEBOX 2's Clip selection and the Clip Window send the same five calls
  elsewhere (the two file-length calls of stock setup's recompute, the Waveform's zoom, its Clip knob bind, its
  redraw). `patch.py` lets a module name such sites in `TAKES`: only it writes there, the other module's entry is
  skipped and printed. `patches/clipwin.py` takes the five, so on a Clip pad the Waveform screen and its four knobs
  stay the Clip Window's, and `slice.py` stays byte for byte upstream's. Where no Region is set, the two length
  sites answer the selection's length; with no selection either, the file's.
- **D-038 (2026-11-12) — What the merge cost in scarce room** (hub #t-052). Bank 1: JOEBOX 2 alone leaves 1,067 B, so
  ChopShop's bodies went to bank 2 by hand (`chop.c` whole, `chopmode_b2.c`), its hooks staying in bank 1 as stubs
  that fall back to stock: 331 B free in the merged dev build. A unit with no bank 2 therefore has no ChopShop, on
  top of what upstream's own layout already keeps up there (since JOEBOX 2 Motion and Relapse too, with Munchi and
  Confetti). Settings stores:
  a Sample pad needs 99 entries (JOEBOX 2's 94 + ours 5) and held 96; stock's add returns silently when full, so
  three rows were dropped without a word. All three sizing sites go from `0x60` to `0x70` together, because stock's
  store copy never reads the destination's size. The boot SDRAM block: `0x84900` → `0x95910`, past D-030's bound,
  and JOEBOX 2's stretch takes another `0x58000` at boot. Measured on the unit on 12/11, running 37.4.1d: the pool
  has 1,491,200 B free after boot (`0x24000088` / `0x2400008C`, x2 §1); a 37.5.0 dev build takes 435,216 B more
  (the bench kit's `0x1400` included), so its boot fits with about 1.0 MB left. That room is also the scratch a
  preset load and save need (4.6 to 4.9 times the `preset.xml`, x2): the largest preset a unit can load drops from
  about 300 KB to about 215 KB, nearly all of it upstream's own cost. *D-039 is not used.*
- **D-040 (2026-11-12) — Upstream is a vendor: the PRs are frozen, `maigre` is the product** (Thomas, on the 12/11
  review; hub log 2026-11-12). Six PRs open since 20–23/10 and the first-contact issue got no comment or review,
  nor did another contributor's PR; JOEBOX ships squashed releases built in private (JOEBOX 2: 9 commits, 167
  files), TapeScam took the ids the first-contact issue asked to reserve, and its Clip selection uses the Waveform
  knobs our Region uses. So: the PRs stay open upstream but are no longer synced (`bench/pr-branches` is empty); no
  new PR-shaped branch, no byte-identical union check, no JOEBOX commit style; `main` stays his mirror and his
  releases keep being merged into `maigre` (`bench/sync-upstream.sh`). A closing note upstream, if any, is Thomas's
  to send. *Replaces D-019's PR-shaped branches and D-032; D-011 (keep every JOEBOX feature) stands.* Numbers
  D-036 to D-039 are left to the JOEBOX 2 merge branch, which was cut before this.
- **D-041 (2026-11-12) — Bank 2 first, and autonomy on the unit** (same review). Bank 1 is full for good: upstream
  alone has 1,067 B free, the merged dev build 363 B. Bank 1 keeps JOEBOX's code and our thin hooks; our bodies
  live in bank 2, which installs itself from the card at boot with no button held. Scarce things shared with
  upstream (ids, SDRAM offsets, store entries, patched sites, page slots) are read by one tool and checked before a
  merge (hub #t-056); our files sit beside his, never inside. A dev-build bench kit (hub #t-054) and a rig on
  mgr-ran (switchable hub, SD multiplexer, audio loop on the Fireface; hub #t-060) let a session install bank 2
  and check on the unit alone; repeated crashes switch bank 2 off by themselves (hub #t-059). Bank-1 installs stay
  Thomas's BACK + INFO until the bootloader read (hub #t-058) says otherwise.
- **D-042 (2026-11-12) — The six Looper picks are taken as built** (Thomas: « go »). D-020 to D-025 stand as
  `feat/looper` has them; corrections come at the unit, at Gate 4. The Looper comes up on the merged JOEBOX 2 base
  with its body in bank 2 (its 673 B of bank-1 glue no longer fit).
- **D-043 (2026-11-12) — Crash-safe bank 2** (hub #t-059; the hold and its end proven on the unit the same day,
  `notes/bench/2026-11-12-37.5.0d.md`; the three points below taken as built, Thomas 12/11:
  « close as built »). Three boots in a row ended by a fault (the recorder's « FLT1 » token at `0x388003d8`) or by
  the window watchdog hold bank 2 off from the next boot on: no pairing scan, no card loader, `b2_present` says no
  payload, Tools reads « !held » (« ! » alone in a `USB_DIAG` build, whose label is the USB line). A power-on, a
  brown-out and every other reset that is not a crash set the count (`0x388003d4`) to 0 and end a hold; a boot
  clears a count below three once both of stock's watchdog stamps (the disk task's and the screen task's) have
  passed 12,288 blocks (32.8 s). The rule is `src/b2safe.c`, bank 1 only, release builds too; +48 B of bank 1.
  To confirm: (1) *a hold ends at a power-cycle or an install*, not only at a new payload: the loader takes this
  image's payload alone, so a different one always comes through the installer, which clears the count; on the
  bench the switched USB port does it with no hands. (2) `bkp_put` moves out of line in upstream's `b2.h` (112 B
  back; without it the feature costs 160 B). (3) Upstream's card loader keeps its try count after a clean write:
  the same payload is written twice per power-on at most. Before, a payload that paired on the rescan and failed
  the next boot was erased, written and restarted at every boot; four of upstream's `test_b2load.py` checks
  follow. Worth offering upstream as its own change (his to send).
- **D-044 (2026-11-12) — Scarce resources are checked, not remembered** (hub #t-056). `test_resources.py` refuses
  two modules on one parameter id, xml name, SDRAM or backup-SRAM range, or stock byte; a store past its cap; a
  hooked stock `store_add` that no `resources: store` tag names; and a module's copy of its own id that has drifted
  from the registered value. A module that takes another's call site says so in its `TAKES`; two modules on one
  backup-SRAM range say so in a `resources: shares` tag (taking turns, as `comp.c` and `compm.c`, or one reading
  the other's word, as the bench kit). Stock facts the sources do not state are `resources:` tag comments beside
  the patch they describe. `bench/resources.py report . upstream/main` is run and read before every upstream merge;
  an exit 2 (something not read) is never taken as clean. On the JOEBOX 2 merge it named the clashes the merge had
  met by hand, the one still ahead included: the call at `0x080685D2`, which the Clip Window's stage 1 planned to
  hook, is JOEBOX 2's `sel_param` now (found by reading on 11/11, hub #t-044; `notes/resources.md`).
- **D-045 (2026-11-12) — The bench kit lives in bank 2 of dev builds only: two payloads** (hub #t-054; every job
  run on the unit the same day, `notes/re/x6` §13.2). A release's bank 1 holds its payload's sum and id, so one shared payload would have changed the
  release image; a `RELEASE=1` build has none of the kit, in either bank. Cost: going from a dev build to a release or
  back rewrites bank 2 (one restart). The kit's data area is `0x1400` B behind the block in dev builds only
  (`0x96D10` against a release's `0x95910`), so Prism, the inserts and the Clip Window keep a release's offsets. Its
  mailbox is where `usbdev.c`'s parameter mailbox was (the last `0x100` B of the Clip Window's 4 KB), and the old
  13-row request is still served there, from bank 2: `bbusb.py set` / `get` need this build's `BBEXTRA.BIN`. The
  long peek is the dev peek with a length of 65..4096; the long poke is its own request. Their flags are bits of
  the USB core's own interrupt mask, which every reset clears, so the interrupt reaches bank 2 only during a
  transfer this boot began behind `b2_live()` (tested with a probe on bank 2). The long poke writes up to 4 KB into
  any RAM the word poke may write, wider than x6 §9.2 first drew it and kept on purpose (x6 §13). One request at a
  time: a knob or tap job holds the mailbox until it ends, a request made meanwhile is answered busy (−8), and a
  cancel job ends the running one; `bbkit.py` cancels a job that outlasts its time. `master_alloc` clears the box at
  every boot, because the boot count restarts at 1 after a power-on. Net bank 1: 4 B less than before the kit.
- **D-046 (2026-11-12) — A long suite is split by the runner, never by editing it; a split runs only on a proven
  plan** (hub #t-055). `bench/shard.py` runs a slice of a suite's sections and, without printing anything, the
  statements of the other sections that the slice reads or that change what it reads (method calls followed by
  name), worked out from the source at each run. The proof is `bench/shard.py <suite> --prove N`: the shards'
  output joined is the whole run's line for line and the counts add up; it is recorded in
  `bench/shards/proven.tsv` against a digest of the suite's text and of what each shard runs. `bench/suites.py`
  shards a suite only when that digest still matches: any edit to the suite makes it run whole until it is proven
  again, so a shard can never pass where the whole run fails. Only `test_clipwin.py` is split (6 shards);
  `test_munchi`, `test_relapse` and `test_confetti` keep one emulator running from statement to statement and run
  whole, so `test_munchi` sets the check's floor: about 12.5 min on mgr-ran, not the five the task aimed at. On
  37.5.0 (59 suites) the check takes 17.5 min and JOEBOX 2's `test_savexml` is the floor; Thomas, 12/11: 20 minutes
  is enough. A suite missing from `bench/shards/times.tsv` is queued as a 2-minute job: redo the table from
  `out/check-times.tsv` when suites arrive.
  `check.sh`'s pool is the box's core count (`CHECK_JOBS` overrides it); its diff against upstream stays the pool
  and one call into `bench/suites.py`, with an xargs fallback when `bench/` is absent.
- **D-047 (2026-11-12) — A module moves to bank 2 by tool, its source untouched** (Thomas: « go for the split »,
  hub #t-057; `notes/spikes/b2split.md`). `bench/b2split.py` wraps the build: the module's functions go to bank 2
  whole, bank 1 keeps one 16-byte stub per entry and a 52-byte dispatcher that runs the body when bank 2 is live
  and the fallback otherwise (the stock callee the patch replaced, a declared value, or a hand-written function).
  Bank 2 holds no branch and no pointer into the cave: its calls back go through a table whose address sits in one
  word of patch RAM (`0x2405FF5C`). So an upstream module that must leave bank 1 no longer needs its source
  edited, and the next JOEBOX release merges where a hand split conflicts. Measured: on pristine JOEBOX 2,
  ChopShop and note repeat moved, bank 1 from 1,067 B to 6,054 B free; on 37.5.0 (ChopShop already split by hand,
  D-038), note repeat alone leaves 1,784 B free where there were 287, the tool's verify green, two checks of
  `test_solo.py` to adjust. When ChopShop itself is moved by tool, at the next upstream merge, `chop_header_post`
  and `chop_forget` stay in bank 1 (`--keep`, +128 B): before the meter's first audio block every stub takes its
  fallback, and a project loaded that early would skip part of ChopShop's header handling. Until then the hand
  split stands. Not on a unit yet: the dispatcher, the patch-RAM word, the gate's cost (38 instructions a call).
- **D-034 (2026-11-06) — Region Move posts the pair in the safe order and guards the wrap between the posts** (hub
  #t-042, plan #t-032). `TL Knob:` (`0x1cc`, Loop Start | Move) per pad, saved. In Move, `clipwin_move` (the view's
  forward) posts the knob's Loop Start as two posts: the edge ahead first (Loop End moving forward, Loop Start moving
  back), because `SetCellParam` clamps neither point against the other (notes/re/x5 1), so every pair between the
  posts is a valid region holding both the old and the new one. An audio tick can fall between the posts (x5 3); the
  pad is marked `cw_bank.moving` across them and a wrap that finds the mark keeps the region it had (`adopt`), so no
  pass plays the longer intermediate region. cw_bank grows to `0x8B8`, magic `CWNC`. A second knob event never reads
  a half-moved pair: both posts complete inside the first event's handler and the view's copy is refilled whole
  (x5 x2). The view goes to Loop Start after the second post in both directions.
- **D-033 (2026-10-21) — Fit's order: `Off, Auto (Bars), Auto (Beats), 1/4 … 8 bars`** (hub #t-033). Thomas at the
  37.4.1d bench (21/10): both Autos together after Off. It reverses D-031's order only (Auto (Beats) was last), not
  what either Auto counts. No preset migration, his call: a preset stores the list's index, so one saved with a length
  or with Auto (Beats) before loads one place off: a length as the row before it (1/4 as Auto (Beats), 1 bar as 3
  beats, 8 bars as 4 bars), Auto (Beats) as 8 bars; Off and Auto (Bars) load as they were. He re-saves his. `FIT_BEATS` 10 → 2; the lengths are rows 3 … 10; cw_bank's layout is unchanged.
- **D-035 (2026-11-07) — Trim on a Clip pad: three stateless hooks, riding with the `filter` set** (hub #t-040, plan
  #t-031 rev 1). The cave discards `.data`/`.bss`, so nothing carries state between the File menu's enable, the write
  request and the reload: each hook reads the pad's store itself, and two asm thunks pass the caller's cell and trim
  flag in as arguments. The patch list rides with `filter`, as Clip Window's does, so the image keeps the name every
  suite opens (a separate `trim` set renamed it under all 31). Trim is refused while another cell of the preset names
  the same file — stock's trim reloads those too — compared by the name in each store, as stock's own loop does.
- **D-032 (2026-10-21) — The Clip Window goes upstream as one PR of five commits** (hub #t-039). Thomas, the night
  Gate 3 closed: « one PR with five-commits ». One branch, `feat/clip-window`, from upstream `main`: slip, region (+
  the Clip-mode Waveform knobs and the playhead), looplen, fit, loopfade, each commit building and passing
  `./check.sh` alone (notes/pr-map.md). The corner labels stay PR #9's, the parameter mailbox fork-only. Opened after
  Justin answers the first-contact issue (#4); if he asks for a stack, it is five branches cut at those commits.
- **D-031 (2026-10-21) — Fit has two Autos: Auto (Bars), second, and Auto (Beats), last** (hub #t-027 → #t-029).
  Thomas at Gate 3b part 4 (20/10): « fit auto doesnt make the loop metronome
  syncable », then « yes separate entry: Auto (Bars), then Auto (Beats) »; under a bar the nearest of 1/4, 1/2, 1 bar:
  « ok ». The list is `Off, Auto (Bars), 1/4 … 8 bars, Auto (Beats)` (order answered 21/10, bars-first-beats-last): a
  preset stores the list's index, so the lengths keep theirs and a saved Auto (1) loads as Auto (Bars) — pad 1's
  14.015-beat take then plays as 4 bars until set to Auto (Beats). Auto (Bars) rounds the length itself, not Auto
  (Beats)' count (5.9 beats is 6 beats but 1 bar), ties up as D-026's. Both share `abeats`/`alen`; `abars` (cw_bank
  `0x898`, appended, the magic kept: no field moves) says which Auto counted, so the other one chosen counts again.
- **D-030 (2026-10-20) — The boot SDRAM block is core first, then a tail taken only with this image's payload in bank
  2; D-011's companion fix, built** (Thomas, hub #t-016: "build it after 37.3.0"). `master_alloc` asks `b2_present()`:
  still `main`, before the scheduler, so no task races it, and the card loader restarts the unit after it writes bank 2,
  so the answer holds for the whole boot. Core, on every unit, 0xC100 B: the LFOs +0, the USB ring +0x1000, the S950
  bank +0x7000, the clipper +0xB000, the Clip Window bank +0xB100 (its 4 KB hold the bench mailbox, so it stays in the
  core). Tail, 0x78800 B: Prism's +0, the inserts' bank +0x56800, reached through `master_tail()`. The check word's key
  says which block it is (`PRISM_KEY` with the tail, `CORE_KEY` without), so Prism and the inserts get no memory from a
  core-only block even if bank 2 pairs later in that boot. The whole block stays 0x84900 B (a bigger one hangs the
  boot, X2): a paired unit allocates what 37.4.0 did, and a unit without a usable payload keeps 493,568 B more for
  presets. Bank 2 is byte for byte 37.4.0's (no rewrite at install); bank 1 +24 B. `bench/bbusb.py` finds the Clip
  Window bank by its magic at either offset, so it still reads a 37.4.0 unit.
- **D-029 (2026-10-18) — Munchi's engine in bank 2 on our line (37.4.0): bank-1 room for the Looper and MIDI; the
  upstream PR `feat/munchi-bank2` pending Justin** (Thomas: "merge `feat/munchi-bank2` into our line for 37.4"; hub
  #t-014). Bank 1 was the hard budget: 37.3.3 left 656 B free in the release build and 16 in the dev build, while the
  Looper needs 673 B (`notes/pr-map.md` Risks) and the MIDI plan more. `feat/munchi-bank2` (`c3ccbb5`, one commit on
  upstream `main` `66329ad`) moves Munchi's engine to bank 2 (`src/munchi_dsp.cpp`, a leaf with no undefined symbol)
  and leaves every hook and stock call in bank 1 (`src/munchi.cpp`, 10 371 → 3 939 B), with the output bit for bit
  rc4's (a fingerprint in `test_munchi.py`; `test_bank2.py` extended; `MUNCHI_OFF` fixed on the way). Merged into
  `rc4-sync` by D-019 as if accepted: the branch's code as it is; the two conflicts were README's "The second file"
  (its Munchi wording joined to our Clip-pad wording) and `build.sh`'s id comment (its `B2_SRC` code, both comments).
  Bank 1 back: the dev build's `.cave` 6 454 B free (16 before), the release build's 7 094 (656 before). Consequences: Munchi now needs
  this build's `BBEXTRA.BIN` (without it the delay Type reads `---` and the slot plays the stock delay, as Confetti
  does), and every unit rewrites bank 2 once. It is upstream PR material (`notes/upstream-first-contact.md` item 6,
  Justin's trade-off to judge); if he takes it, D-019 (4) applies, and if he declines it stays a fork-only layer.
- **D-028 (2026-10-17) — F-a: a step 0 that starts inside the audio gets stock's fade-in, automatically** (Thomas:
  "an automatic crossfade"; hub #t-023, 37.3.3). Root cause, on the unit: Attack 0 (`pad + 0xBA1` = 1, stock's
  default, both pads) makes stock start every step 0 and every launch hard; slipped, on a region past frame 0, in
  Loop Len's window or on a seamless wrap that start is inside the audio and clicks or doubles. No new row, no new
  setting: such a segment (its first frame not stock's, or a pass's step 0 on a seamless pad) gets the ordinary
  256-sample fade-in back at its first read, its fade-out on the same sample, all in bank 2 (`cw_latch`, `cw_hold`,
  `cw_slot`; bank 1 unchanged but for the bank's magic, `CWNB`, and size). A launch on the file's frame 0 stays hard,
  and so does everything at Attack ≠ 0, on a pad the hooks leave alone, or without this build's bank 2. The Region
  seam (finding 6) is covered by the same rule; Loop Fade's content crossfade is unchanged (feature doc §1 Slip).
- **D-027 (2026-10-17) — JOEBOX 1 rc4 supersedes our PR #2: the restart-loop fix is Justin's now** (hub #t-023).
  Upstream `19d29f1` (JOEBOX 1 rc4, 2026-10-17) changes `b2chk` in `cpu.c` with `b2_step`: PRIMASK saved, interrupts
  masked, one read and one write, PRIMASK restored, instead of the LDREXB / STREXB the atomics compiled to. That is
  the fault D-013 found on Thomas's unit (and JOE DIAG then caught on two testers' units, serials from ~2001009700),
  fixed his way. Merged into `rc4-sync` (cut from `halo`, 37.3.1) by D-019 (4): his `b2_step` and its comment replace
  our `b2_change` (cpsid / cpsie) at all five call sites; his `emu.py` stands in for `mrs` / `msr primask` under
  Unicorn; the Device-memory reading of the fault stays in D-013. j3threejay/blackbox-mod PR #2
  (`fix/restart-loop-ldrex`) is superseded: Thomas closes it; the branch stays as it is. Kept of ours: `test_cpu.py`'s
  no-exclusives check (PR #2's test, not in rc4), which his fix passes. The rest of rc4 as he made it: `usbdev.c`'s
  state moved 0x38800650 → 0x38800680, since `comp.c`'s Limit lookahead overwrote the SETUP packet's first word (X2's
  side finding; USB with the compressor on Limit), with our dev-only F-j bounds, F-i flush and parameter mailbox
  re-applied on his file unchanged; the insert models renamed (Stone → Pebble, Mistress → Electra, ADA → Jet: names
  only, presets keep their values); the `FAULT_SHOW` / `USB_DIAG` diagnostic builds (`build.sh` flags; TOOLS reads
  his names for them, `JOE DIAG` / `JOE USB` or `3.3.g` / `3.3.i`, not 37.x). Bank 2 is unchanged: the payload is
  37.3.1's byte for byte. Bank 1 pays +36 B (`usbdev.o` +32 from the moved state, `cpu.o` +4 for the PRIMASK save):
  the release build fits (664 B free), the dev build (8 B free on 37.3.1d) came out 32 B over. **The dev build's room
  comes from dev-only code** (Thomas, the same day; nothing moved to bank 2, nothing trimmed, the release build byte
  for byte as before, `usbdev.o` included): the mailbox's five stock calls are direct `bl`s to absolute Thumb symbols
  at their 3.1.9 addresses (`.thumb_set`; −24 B, `test_clipwin.py` §12c checks they are `bl`, not `blx`); the
  mailbox reads its request through a plain pointer behind a compiler barrier once the volatile seq has been seen
  (−12 B of zero-extends); the peek's range table holds each range's last-word offset, one subtract and compare a
  range (−4 B); the peek stores each word it read with one 4-byte `__builtin_memcpy` instead of four byte stores
  (−16 B). The dev build's `.cave` is 57 712 of 57 736 B (24 free). The other options weighed: the mailbox's checks
  as a bank-2 leaf (32 B free, but a new payload: every unit rewrites bank 2 once), the label outline's vtable copy
  in bank 2 (bank 2 would hold bank-1 addresses, the coupling 3.3.c removed), JOEBOX code to bank 2 (his). Found on
  the way, upstream's: `B2LOAD_WRITE=0` (the read-only card loader) no longer compiled, its tries counter and restart
  being unused outside `#if B2LOAD_WRITE` under `-Werror`; they now sit under that `#if` (`b40d531`, the default build
  byte for byte the same; the read-only build's `test_b2load.py` passes): a candidate fix PR, `fix/b2load-readonly`.
- **D-026 (2026-10-16) — Fit's answers: Auto = the nearest whole beat, polymetric; 3 and 6 beats explicit; a whole
  file fitted is seamless; Loop Fade on row 9; the clip's own wrap grid; the bank 0x1000** (hub #t-022; the design and
  Thomas's answers 1-5: `/srv/dev/firmware/re-scratch/fit/DESIGN.md`. The messages of `06eaeb7` and `86fd580` call
  this D-019: it was renumbered, D-019 being the branch model and D-020..D-025 the Looper's on `feat/looper`). Thomas
  at Gate 3 (~13:00), of pad 1's 14.015-beat take: « that weird length is intended as polyrhythmic loop and should be
  handled properly ». So Fit Auto is the nearest whole number of beats (14.015 → 14, 3.74 → 4, 15.6 → 16; ties up, at
  least 1, at most 1 024), counted once per loop length (and again once a recompute finds the file closed), not stock's
  power-of-two Beat Count Auto (answer 2, replaced). The list is Off, Auto, 1/4, 1/2, 3 beats, 1 bar, 6 beats, 2, 4,
  8 bars: stock's names for 1 and 2 beats (answer 3); 3 and 6 beats as explicit values, not reached by Auto (answer 2,
  Thomas: "might be cool … not sure yet": kept because their wrap grid holds at Quant 1 bar under emulation; dropped
  if they misbehave on the unit, Gate 3b). Fit is the Pos tab's row 8 (`0x1cb`, xml `clipfit`, default Off). A clip
  that is no whole number of Quants cycles against the bar: its wrap grid is gcd(Quant, clip), on which every launch
  point and pass start lies; its steps one when Sync is the clip or longer, else gcd(Sync, clip), on the clock's grid
  of their length as stock's are, so a pad launched off the Sync grid is pulled onto it at its first step as on stock
  (the review's F1: steps of gcd(Sync, gcd(Quant, clip)) kept it there, a 1/16 late for good). Under emulation stock's
  own min(Quant, clip) does not keep such a clip (a 14-beat file at Quant 1 bar: every other pass a 1/16 early, then a
  1/16 of silence), which the Gate 3 report heard clean on the unit: Gate 3b check 21 measures it again. The
  wrap-grid hold (H3') holds Fit with the region and reads the clip's own grid. A whole file fitted is seamless
  (answer 5: read round its end like a region, no stock V-notch at its loop point). **Loop Fade** (answer 4): stock's
  own row `0xfa` (0 … 1000) on the Clip Pos tab, row 9, after Fit; on a pad playing a region it crossfades the loop
  point with Sample mode's formula (F = region × row / 1000, at most Loop Start; equal-gain, linear), taken with the
  region, so heard from the next pass; not in the machine modes, not on a one-shot, not while Loop Len is taken (the
  review's F4). The fields (`fit` … `engine`) took `cw_bank` past 0x800 (0x858, `CWN9`; `fade` at 0x858, `CWNA`):
  `EXTRA_BYTES` + 0x800, the bank 0x1000, the boot block 0x84900 B.
- **D-019 (2026-10-16) — The fork's branch model: `main` a pure mirror, each feature's PR-shaped branch its source of
  truth, `maigre` = upstream + every feature as if accepted + a thin fork layer, moved only by merges; refines D-001**
  (Thomas, 16/10).
  (1) `main` stays a pure mirror of upstream `main`: fast-forward only, never committed to.
  (2) Each feature has one PR-shaped branch (`feat/<name>` or `fix/<name>`, cut from upstream `main`: its `src/`,
  `patches/`, `test_*.py` and README bullet, in JOEBOX's layout, no `notes/`, no fork names), and that branch is the
  feature's source of truth: what upstream would get is what is there.
  (3) `maigre` = upstream `main` + every feature as if Justin had accepted its PR + a thin fork-only layer (`notes/`,
  `bench/`, `FORK.md`, the 37.x names in `src/release.h`). It moves only by merges, never by a commit of feature code
  made on it.
  (4) When Justin accepts a PR, we merge his `main` (into `main`, then into `maigre`) and resolve every conflict toward
  his version: what he took, as he took it (his squash or rewrite), replaces ours.
  Consequences: `maigre` shows at any time what the unit runs and what upstream would have if every PR were taken, and
  an upstream release lands on it as one merge; a feature's fix goes to its own branch, then reaches `maigre` by a
  merge; `notes/dev-setup.md`'s branch table follows this. How a `37loop/blackbox-t-NNN` task branch (features and notes
  together, one commit per feature or fix, as `37loop/blackbox-t-021`) is split into its feature branches when it lands
  is not settled here. Ideas parked the same day (Thomas: later; hub #t-014, P6): a `Tools > Rec` Resam tap Post /
  Pre Comp / Pre FX (one stock call at `0x0805353A`); bank 2 over USB (needs a bank-1 ↔ bank-2 interface, and
  Justin's view); a true time-stretch that keeps the pitch (granular, in bank 2; Fit, D-026, changes the speed and so
  the pitch).
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
  bank-2 payload (v3, 37.3.0: `KNOB_GAIN`, `KNOB_GAIN_STEP`, `KNOB_TOP`, `SLIP_GRID`, `ZERO_DETENT_MS`,
  `ZERO_DETENT_SLOW_MS`, `KNOB_DETENT_SLOW`). (6) Cost, measured under Unicorn (instructions executed in the cave and
  bank 2 per engine block, one playing Clip pad, cell 0x102, `test_clipwin.py`'s rig, 300 blocks, the boot's one-time
  payload check left out): Slip 0 / File 360 → 454, Slip 480 469 → 569, Slip 480 + Region Loop 534 → 634, Loop Len 1/4
  409 → 503: about +95 a block a pad (one `b2_live()` per hook call, a few reads of `cpu.c`'s state, and the calls
  across). Sixteen such pads would be about 1.6 k instructions, roughly 0.1 % of a 2.67 ms block at 480 MHz. Also new:
  `clipwin_len` reads the four store rows at every site-1 recompute, adopted or not (it read them only when adopting): a
  few lookups a recompute, not a block. Not measured on the unit (TOOLS' load is the check). A unit with this
  `BLACKBOX.bin` needs this build's `BBEXTRA.BIN` written by the card loader before any Clip Window check (TOOLS: no
  `!`).
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
  turn passes 150 ms after it arrived, and a medium tier (10 ticks a turn event) at speeds 3–4, the 1/64 at 5–6.
  Revised again in 37.3.0 (v3, after Gate 3: "the detent could be a bit stronger at low speed", "acceleration could be
  smoother too"): one gain curve by the accelerator's speed, 10 × 1.83^(m − 1) stepper counts a count, the 1/64 grid
  at the top speed only, and the detent held 400 ms after an arrival at speed 2 or under, 150 ms after a faster one.*
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
  *Superseded by D-027 for the fix itself: since JOEBOX 1 rc4 it is upstream's own `b2_step` (PRIMASK saved and
  restored), and PR #2 is superseded (Thomas closes it); the rule stands.*
  *Addendum (2026-11-12, `notes/re/x7` §5):* the Device mapping at `0x24050000..0x2405FFFF` comes from bootloader
  1.0.22's MPU region 3, which stock 3.1.9 never rewrites (the app sets only regions 4, 5, 8, 9). A unit whose
  bootloader leaves region 3 unset maps it Normal and survives the LDREXB: the candidate for « why other units
  survive » (inferred: no other bootloader has been read). The « 1.7.F » above matches nothing in the dump, whose
  version is 1.0.22.
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
  *Built by D-030 (core first, Prism and the inserts in a tail taken only with the payload).*
- **D-010 (2026-10-15) — Builds are not byte-identical to upstream's releases** (Arm GNU 14.2 here vs the
  maintainer's toolchain: 782,200 B vs 781,840 B for the same sources). The Unicorn suites are the proof of a build,
  not the sha; ask the maintainer which gcc he uses (first-contact item).
