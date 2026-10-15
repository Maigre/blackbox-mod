# Upstream first contact — an outline for Thomas

The points for Thomas's message to the JOEBOX maintainer (Justin, j3threejay/blackbox-mod). **An outline only:
Thomas writes the message and sends it** (hub `blackbox#t-007`). Facts as of 2026-10-15, 23:00; re-check the
"Where it stands" block before sending.

## Where it stands — the first contact has already happened

- **PR #2** (Thomas, 2026-10-15 19:36 UTC, `fix/restart-loop-ldrex` @01b5699) already carries three of this outline's
  five points: who we are (Thomas, a Mk1 owner, the fork Maigre/blackbox-mod), Gate 0's install data on the JOEBOX 1
  hold (the unit, the fault record, the MPU's Device-memory regions, the fix, 37.0.2d stable), and what we add
  (Slip, later a KP3-style looper, "as separate PRs, one feature each, following your conventions — if you're open
  to it"). It also mentions the Linux host build and the FMA misses, kept out of the PR.
- No answer yet: 0 comments, 0 reviews. Upstream `main` has not moved since c4fadf6 (14/10, the hold notice). Open
  issues: #1 (a colour scheme mod, unremarkablegarden) and our #2.
- So the message is the **second** contact: the asks and the preferences, pointing at PR #2 rather than repeating it.

## The outline

1. **Context, one line** — a pointer to PR #2 for who we are and the hold. Nothing retold.
2. **Hold data, only what is new since PR #2**
   - Gate 2's session ran on the fixed full set (37.1.0d = JOEBOX 1 + the fix + Slip): installs, save / power-cycle /
     reload, TOOLS load 11/15 %, no fault record (`notes/bench/2026-10-15-gate2-slip.md`, on the unlanded
     `37loop/blackbox-t-004`).
   - Not tried yet on this unit: a two-file build (`BBEXTRA.BIN`) and its self-install — say so, and offer to report
     when it is done (hub `#t-016`). Re-check its state before sending.
3. **What we add, and why**
   - **Slip** (first PR, `feat/slip`): a per-pad row on the Clip Pos page that moves a Clip pad against the clock,
     live — ±1 bar in clock ticks, shown as beats.ticks, one knob (single ticks slow, 1/64 fast, stops on 0),
     `+` = ahead like a CDJ jog (D-016). Why: a 2024 wish of Thomas's (the Electrix Repeater's slip), in neither
     stock 3.1.9 nor the Blackbox 2. Proof: `test_clipwin.py` (Slip 0 bit-identical to stock) and the unit,
     measured to the sample (+60 ticks = +1 500 samples at 120 BPM).
   - **Later, one PR each**: per-pad `Region Auto|File|Loop` + `Loop Len` (a Clip pad plays the Sample-mode loop
     region — the Trim step goes), then a `Looper` FX on the XY page (touch catches the bar that was playing,
     X = length, Y = HPF), then Save to a slot. Each = `src/<f>.c` + `patches/<f>.py` + `test_<f>.py` + a README
     bullet, cut from his `main`, inert at default settings.
4. **The asks**
   - **Param ids `0x1c8–0x1cf`**: free in stock 3.1.9 (A0: the stock registrar stops at `0x19b`, no stock load of
     those values) and the gap between JOEBOX's `0x1c7` and `0x1d0`. Slip takes `0x1c9`; Region / Loop Len would
     take `0x1c8` / `0x1ca`. Ask him to keep that run for these features, or to name the range he prefers. With
     only these 8 left, ask too whether he would rather enlarge the 500-entry table than share it out (D-011).
   - **Linux host build** (`feat/host-linux`): `host/build.sh` takes `CC`, then clang, then cc and builds a `.so`; the
     ARM-vs-host DSP tolerance goes from 2e-6 to 1e-5 so `test_machine.py`'s S950 Lo checks pass on a CPU without FMA
     (D-009). Ask whether he wants it as a PR, and whether he prefers the looser tolerance or a skip without FMA.
   - **An `IMAGE` convention**: four suites (`test_b2load`, `test_bank2`, `test_clip`, `test_preroll`) hardcode the
     full set's path `out/solo+…+fault+cave/BLACKBOX.bin`, so every feature that joins the set rewrites those lines
     (+ `check.sh`, the README build line). Ask whether he wants one shared definition (a constant the suites import,
     or a path `check.sh` exports), or keeps it as is and we follow.
   - **His toolchain**: which `arm-none-eabi-gcc` builds his releases — Arm GNU 14.2.rel1 gives 782,200 B where his
     release is 781,840 B for the same sources (D-010), so a fork build cannot reproduce his `output_sha256` yet.
5. **His preferences** — questions, not assumptions
   - PR order and size: Slip first and alone?
   - Default-off: is "inert at default settings" his rule for new rows?
   - Labels and README voice: row labels (≤ 9 chars), a Known-issues line per feature?
   - Bug reports: our images say `37.x.y` on TOOLS (D-012) so a report from the fork never looks like a JOEBOX build
     — tell him, and ask how he wants fork reports routed (issues here, or the fork).
   - `bench/bbusb.py` (the USB peek / record tool that measured the fault and Slip) is fork-only today: would he
     want it upstream?
6. **A second test unit** — offer Thomas's unit for his release candidates: the README says JOEBOX "has run on very
   few units", and this one is the case that looped (rev V, bootloader 1.7.F). On a dev build any register can be read
   over USB at his request (PR #2 already offers that for the MPU question).

## Leave out

- Firmware, images, listings, manuals — his README's rule; link only the fork and PR #2.
- Dates or promises.
- The colour theme (D-015a, parked "later" by Thomas). It would close his issue #1; raise it only if Thomas
  un-parks it.

## Timing (Thomas's call)

- PR #2 is a few hours old and unanswered. Options: (a) wait for his first reply on PR #2, then open the issue —
  one open thread at a time, and his reply may already answer the preferences; (b) open the issue now; (c) put the
  asks in a comment on PR #2 — it mixes a fix's review with feature questions.
- The `feat/slip` PR follows his answer (`#t-007`); the branch itself is `#t-004`'s to cut from `main`.
