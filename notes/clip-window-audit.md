# Clip Window — audit and a consolidation plan (proposal, 2026-10-21, for Thomas's review)

Asked at the end of P3: look at the plan, the path, the upgrades and the difficulties, and say whether a cleverer and
more robust reimplementation exists, and whether it is worth doing now. Read for this: `notes/plan.md`,
`notes/decisions.md` (D-001..D-031), `notes/features/clip-window.md`, `notes/re/README.md`, a1, a2, x3, the seven
bench reports, `src/clipwin*.{c,h,S}`, `patches/clipwin.py`, `test_clipwin.py`'s layout, `test_bank2.py`'s rule, the
hub's dossiers for #t-008, #t-009, #t-010 and the 20/10 log (the `clip-upgrade` group). Sizes are the 37.4.1d build in
`out/` (`arm-none-eabi-nm -S out/cave.elf`).

## 1. Verdict

- **The core is right, and it is the clever part.** P1's finding that stock has no clock-derived target - the phase of
  a playing clip *is* the step index of each segment - made the Clip Window a per-segment latch (H1) plus a mapped read
  (H2), with stock's launch quantization, grid, live re-grid, crossfades and wrap untouched. Every unit measurement
  since Gate 2 agreed with the emulator to the sample, in both directions (the one disagreement, pad 1's polymetric
  wrap at 3b-16, was the ear's). No finding in four gates touched the mapping. Do not rewrite it. Four other
  architectures are weighed in §4; none beats it.
- **The pain is in one layer: *when* and *from where* a setting is taken.** Seven of the ten unit findings are there
  (§3), and each was answered where it hurt: a flag in `cw_bank` and a branch in one of five functions. The policy now
  lives in five places driven by four triggers; the settings are polled from the app's store every 43 ms although the
  engine already receives each one on the pad's queue; and F-p's fix put policy back into bank 1. That is accretion,
  not a design flaw, and it is what makes #t-030 (Live Region), #t-032 (Region Move) and P5's Save expensive if they
  are built on top of it as it is.
- **Recommendation: a staged consolidation, not a revamp** (§5): (1) take the settings from the engine's queue at the
  one param-set site, (2) one timing model and one explicit apply rule, (3) optionally, let bank 2 call stock. The
  H1/H2 maths, the seam read, the knob, the Waveform screen, H5, the labels and every audio-level test section stay
  as they are. About 3-4 machine days and one bench sitting on the Gate 3b recipe.
- **Not now.** Close Gate 3 on 37.4.1 / 37.4.2 first (autogate's three rows, #t-033, #t-034): the current build is
  proven, and that proof is worth keeping under the PR. Then do the consolidation as the first item of `clip-upgrade`,
  before #t-030 and #t-032 are built - the apply rule *is* their design - and before P5. P4 does not wait on it: bank
  1 has 6.8 KB free since D-029, and the PR map's "the Looper does not fit" is stale (the #t-010 dossier says so).

## 2. What was built (the shape to audit)

Three ideas carry the feature:

1. **The latch and the mapped read** (H1, H2: `cw_latch`, `cw_slot`, `cw_map`, `cw_hint`, `cw_fade`,
   `clipwin_read`). Each segment decides once, when stock makes it, which frames it plays - the region, Slip, Loop Len's
   window - and the reader folds positions through that. Exact to the sample on the unit (Gate 2, 3, 3b).
2. **The virtual length** (H3, four `fw_src_len` sites: `cw_len`). Stock is told the file is the region, so Beat Count
   Auto, the frames per step and the last step's end follow it. Site 2 also gives the seamless wrap.
3. **Owned step fields** (H3 site 3: `cw_fit`). A fitted pad gets its grid, ticks per step, steps, frames per step,
   output samples per step and rate written again after stock's recompute, so stock's own re-placement lands where the
   audio is. Proven on the unit at 3b-16, a live tempo change included.

Around them: the poll (`clipwin_tick` / `cw_tick`, one pad a block from `duck_block`) - Slip and Loop Len from the app's
store, the settle, Loop Len's take and its forced Sync (a stock param-set message), the guarded drop, `cw_retire`,
Fit's tempo follow, F-p's re-send; the wrap hook (H3′: `clipwin_wrap` / `cw_hold`), where a region is adopted and the
grid hold decided; H5; the knob; the Waveform screen; the labels.

Footprint (37.4.1d): 19 patched call sites, two page tables, the reader thunk, four chain lines. Bank 1 about 3.2 KB
(`clipwin_read` 696 B, `clipwin_tick` 500, the screen 266 + 104 + 88 + 32, the labels 162 + 64 + 40). Bank 2 about
4.0 KB (`cw_fit` 628, `cw_looplen` 586, `cw_latch` 578, `cw_turn` 354, `cw_len` 326, `cw_tick` 246, `cw_hold` 186).
`cw_bank`: 0x8A8 B in about thirty fields, eleven layouts (`CWN1` .. `CWNB`) between 15 and 17 October.
`test_clipwin.py`: 5 201 lines, 455 checks, 11.6 min.

## 3. The path, read as a pattern

What went well: RE before code; every policy measured at audio level under the Rig before the unit; bit for bit
pass-through at the defaults; one layer per commit, so each fix stayed small. What the findings say read together:

| finding | cause | answer | where it landed |
|---|---|---|---|
| the stale latch (t-004) | a new file under a playing pad | `len` in the latch; H2 reads stock while it differs | H1 / H2 (the mapping) |
| 5: a grown region held forever | the hold waited for a wrap that could not come | the gcd rule in `cw_hold` | policy, the wrap |
| 7: Auto asked Loop Mode | a Sample-mode row Clip never shows | the rule changed | policy, the adopt |
| 8 / F-g: Loop Len taken on a passed value | the poll takes what it sees | a settle, 4 then 7 polls (`llv`, `llc`) | policy, the poll |
| 9: a slot stuck past the file's end | stock's own, after the browser | `cw_retire` | the poll |
| 12: the view's length is another pad's | the app's store `+0x20` | `flen` | the screen |
| F-a: a hard step 0 inside the audio | Attack 0, stock's default, never in the rig | `fin`, `wrapped`; `cw_slot` gives the fade-in back | H1 / H2 |
| F-p: a take loaded into a playing pad keeps the old window | stock re-gridded onto the closed slot's 2^28 clip | Sync sent again once the file is open | **policy, in bank 1** (`clipwin_tick`) |
| F-l: a pad stuck on its Slip, once | unknown | a watch | - |
| D-031 / #t-033: Fit's list order | a preset stores the index | the order, no migration | the UI |

Seven of ten are about when a setting is taken, or what the pad is at that moment. None is in the mapping. Today the
"when" is decided in five functions on four triggers:

- `cw_len` at H3 site 1: adopt the region, Fit and Loop Fade, only while this pad's wrap recompute runs or no layer
  plays;
- `cw_hold` at H3′: put them back when the new grid misses this pass (`wrap`, `was[]`, `pfit`, `wrapped`);
- `cw_tick`, from the poll: Slip's change, Loop Len's settle, Fit's tempo, `cw_retire`, the drop;
- `cw_looplen`, from the poll: the engage (the origin), the forced Sync and its give-back (`forced`), never while a
  launch waits;
- `clipwin_tick`, bank 1: F-p's re-send, the drop's re-latch.

Three structural facts sit behind that:

1. **The engine already has every setting, in order.** `SetCellParam` posts every id as a `0x39` message in every
   mode, and the class-B process hands each to its param-set at one `bl` (`0x080685D2`), which drops ours (ids above
   `0xF4`). The P1 notes name that site as the other way to get our ids (x3 §1; README §2.6: "possible but has no
   JOEBOX precedent"). Instead the poll reads the app's store with `fw_setting`, one pad a block: 16 blocks of latency
   (a change in the last 43 ms before a step lands a step late), the known race during a preset load (x3 t11), and
   `good[]` for loop points read half-written. Loop Start / End, Sync and Quant reach the engine on the same queue, so
   a hook there sees a region change, and the Sync set F-p is about, in the order the pad does.
2. **Every region change waits for the wrap, whether it moves the clip or not.** A2 settled that a change made
   mid-pass must not move the steps already made (11 418 / 23 490 silent samples), and the wrap was the safe point.
   But Fit's tempo follow (37.3.0) and Slip (37.1) already change what the next segment plays, and at what rate, live,
   through the drop: the clean path exists and is proven on the unit. What makes a change unsafe is a change of the
   clip's length in ticks (the grid moves). A change that keeps the clip - Region Move; any region under a fixed Fit or
   an explicit Beat Count; Loop Fade - is Slip's case. The 20/10 log reads #t-030 that way already. The code has no such
   distinction: `adopt` runs at the wrap, or not at all.
3. **The bank split is eroding.** D-018's rule (hooks and stock calls in bank 1, maths and policy in bank 2) held until
   F-p: its re-send, a stock message decided by policy, sits in `clipwin_tick`, now 500 B of bank 1. `cw_looplen`
   builds a message bank 1 sends; `cw_len` is handed store rows bank 1 read. `test_bank2.py`'s leaf rule has two
   halves: "no branch lands in the cave" (JOEBOX's invariant since 3.3.c: the cave is relinked every build) and "none
   leaves bank 2 at all". The second is stricter than the invariant needs: stock's addresses never move (3.1.9 is the
   last firmware), so a `bl` from bank 2 into stock is as safe as one from the cave. The MIDI plan already lists this
   option (`notes/pr-map.md`, Risks).

## 4. The other ways to consider the problem

| | idea | why not |
|---|---|---|
| A | **An own scheduler**: replace stock's step scheduling with a tick-based model of ours | a2's rejected experiments (`s2bad.py`): stock's positions cannot be rewritten, a Sync re-grid from a rewritten position cuts the segment, and the launch / Quant / re-grid logic is stock code we would write again without its tests. Everything the current design gets for free (launch quantization, the live re-grid, the crossfade, one-shots, Toggle stops) would be ours to keep |
| B | **"Arch C" of the plan**: all anchoring in the reader, an own re-anchor crossfade | no stock timing to lean on at a re-anchor; a second crossfade engine beside stock's; nothing it buys that the latch does not |
| C | **Loop Len as a temporary region** (rs = the window's start, vlen = W frames, its own clip) | loses what the step remap gives for free: stock's step counter keeps running through the whole clip, so Off is in phase with no bookkeeping; a W-clip would restart j at its wrap |
| D | **A true time-stretch** (Fit keeps the pitch) | another feature (P6, granular, bank 2), not another architecture; it sits under the same latch |
| E | **Consolidate the policy layer on the current core** | the one that removes §3's pattern: §5 |

Looked at and kept: the latch with its `len` (the right answer to a file change: a segment made for one file never
maps another), `cw_retire`, F-a's fade-in restore (segment-level facts, not policy), the Waveform screen's hooks,
the knob, H5, the labels, the bank mechanism (`b2_live`, the magic cleared at boot).

## 5. The consolidation

Three stages, each shippable alone, in this order. Untouched by all three: `cw_latch`, `cw_window`, `cw_slot`,
`cw_map`, `cw_hint`, `cw_fade`, `clipwin_read`'s seam path, `cw_retire`, `cw_turn` / `cw_text` / `clipwin_turn` /
`clipwin_format`, `clipwin_bind` / `clipwin_zoom` / `clipwin_wave` / `cw_bracket`, H5, the labels, the bank's set-up,
`master_alloc`.

### Stage 1 - the settings from the engine's queue (one new hook)

- Hook the `bl FUN_08067648` at `0x080685D2` → `clipwin_param(pad, clock, msg, ctx)` (r0 the pad, r1 the clock, r2 the
  message `{0x39, flag, cell, id, value}`, r3 the context: x3 §1): for the ids `0x1C8 .. 0x1CB`, `0xFA`, `0x91`,
  `0x92`, `0x47`, `0x94` record the value in the pad's **pending** settings (bank 2, `cw_param`), then call stock's
  param-set as it was called. One compare for every other id.
- The poll keeps the housekeeping only: Loop Len's settle countdown (so many blocks since the last `0x1CA` message),
  `cw_retire`, Fit's tempo check. No `fw_setting` from the audio task but one: a pad's store the first time it is
  seen, until the emulator confirms the preset load's re-post (`FUN_08099200`, which §5b's load chain already models)
  delivers our ids. That one check is the only fact stage 1 rests on that is not in the notes.
- Gone: `good[16][2]` (the points arrive in order, as the class-H object gets them), the Sync re-read for the
  give-back, the 43 ms, the store race. The bench mailbox (`SetCellParam`) and the knobs reach the hook unchanged.
- Risk low: one caller, the message's registers as the process built them. Cost: a thunk of a few words;
  `clipwin_tick` shrinks.

### Stage 2 - one timing model, one apply rule (bank 2)

- `cw_model(pad, settings)` → `{beats, clip, grid, step, n, fps, step_out, rate, rs, vlen, fade}`: stock's own rule
  when nothing of ours applies (a1's recompute, ✓), stock's rule over the region when Region applies and Fit is Off
  (what the site-1 lie yields today), Fit's rule otherwise. Called at H3 site 3 - every recompute from any caller:
  the wraps, the param-set, the launches, `0x90` - it writes the fields `cw_fit` writes today, and `+0xBA8`, so the
  app's Beat Count display reads the region's. Site 1 stays (the cheapest way to keep stock's arithmetic bit-exact
  at Fit Off on a region); site 2 stays (seamless); site 0 can go (a `> 0` check).
- `cw_apply(pad)`: pending against applied. A change that keeps `clip` (Region Move; a region under a fixed Fit or an
  explicit Beat Count; Slip; Loop Fade) applies **now**: fields, recompute, the guarded drop - Slip's live path, which
  the tempo follow has proven mid-pass on the unit. A change that moves `clip` waits for a wrap on the new grid:
  `cw_hold`'s rule, kept, now on one number. A stopped pad applies at once.
- That is #t-030's clean case and all of #t-032, with no engine code of their own beyond the UI; #t-030's
  count-changing case stays Thomas's call (log 20/10) and is one branch in `cw_apply`.
- Gone: the adopt at site 1 and its wrap-or-stopped gate, `wrap`, `was[]`, `pfit`, `fon` (the model owns the fields
  it applies), the one-step clip's special case in `cw_len` (`+0x204` is the model's). To decide, not before: whether
  Loop Len's forced Sync becomes the model's step (the step the search finds today, written into the fields, stock's
  re-grid `0x08064E7C` called after them, the pending-launch guard kept; no message, no `forced[]`) or stays as it
  is, proven at 3b-8 / 3b-9 - the smaller change is to keep it. Stays: `fin`, `wrapped`, `latch.len`, `abeats` /
  `alen` / `abars`, the settle.
- Verification. Every whole-process section of `test_clipwin.py` (§3, §4, §5, §5b, §6, §8, §10, §11, §11b, §11c,
  §11d) is audio-level and blind to the architecture: they are the net. The unit sections that name `cw_len`,
  `cw_hold`, `cw_looplen` and `cw_tick` are written again against `cw_model` / `cw_apply`. New: the clip-keeping live
  change (a region moved under Fit 1 bar, heard at the next step, no silence, no gain over 1), and the clip-moving one
  (held to the grid, as today). On the unit: Gate 3b's 3b-4, 3b-5, 3b-7, 3b-8, 3b-16 (Fit live) and 3b-18, plus the
  two live region cases.

### Stage 3 - bank 2 may call stock (a rule, then a move)

- `test_bank2.py`'s second check becomes "no branch leaves bank 2 for anything but stock 3.1.9's text (`0x08040000 ..
  0x080FFFFF` less the cave)": JOEBOX's invariant kept whole, the stricter half dropped. Then the stock-only paths
  move: F-p's re-send and the drop's re-latch (`clipwin_tick` → bank 2: `fw_pad_param`, `fw_prefetch`, `fw_src_len`
  are stock), the message send in `cw_looplen`, `clipwin_len`'s store reads, H5's length. Bank 1 keeps the thunks,
  the dispatch into `filter.c`'s readers (cave code), the Waveform binding (it could follow), the labels.
- Buys about 0.8-1 KB of bank 1 and the split's rule back (policy never in bank 1 again). Not urgent: 37.4.1 has
  6 782 B free (release), 6 158 (dev), and P4 needs 673. For the fork the rule is Thomas's to set; for upstream it
  needs Justin (the PR map's open point).

### What it costs, what it risks

| | machine | bench | bank 2 |
|---|---|---|---|
| stage 1 | ~1 day (the hook, `cw_param`, the poll's cut, tests, the re-post check) | the Gate 3b rows that turn a knob while playing (3b-3, 3b-8, 3b-13) | a new payload |
| stage 2 | ~2 days (`cw_model`, `cw_apply`, the unit sections, the two live cases) | one sitting: 3b-4 / 5 / 7 / 8 / 16 / 18 and the live region cases | a new payload |
| stage 3 | ~0.5-1 day | none (the audio bit for bit the same; `prcheck` proves the union) | a new payload |

Risks: (1) the policy's unit proof is reset - the recipe exists and autogate covers the unattended rows, so it is one
sitting, not a gate; (2) three `BBEXTRA.BIN` reflashes, or one if the stages ship together; (3) F-l (seen once,
unexplained) is neither fixed nor worsened by any of this; (4) the PR: if Justin answers issue #4 before stage 2
lands, send the layers as they are (proven) and the consolidation follows as one PR; if not, fold it in. Either way
the PR is not held for it.

A side win worth taking at stage 2: splitting `test_clipwin.py` by layer (6a .. 6e, as the PR map wants) lets
`check.sh`'s pool run them beside each other, so the 11.6 min that caps every unattended turn drops to the longest
layer's.

## 6. Why not now, one line each

- 37.4.1 is proven on the unit for everything but 3b-10, 3b-12 and the four-pad load; a consolidation before Gate 3
  closes would open again what is closed.
- #t-033 and #t-034 are at the bench on 37.4.1d's bank 2; a new payload now puts them back a boot.
- The PR's shape is still Justin's to answer; proven layers are the stronger first contact.
- `clip-upgrade` is held until Gate 3 closes by Thomas's own call (20/10); the consolidation is its first item, and
  #t-030 / #t-032 are better re-cut on it than built on today's adopt-at-wrap.

## 7. For Thomas

1. Go or no-go on the consolidation as `clip-upgrade`'s first item (a task, `@who(claude)`, `@after(blackbox#t-009)`),
   with #t-030 and #t-032 re-cut on it.
2. Stage 3's rule (bank 2 → stock allowed): fork-only now, upstream later with Justin's view, or not at all.
3. In stage 2, Loop Len's forced Sync: the model's step, or as it is (the smaller change).
