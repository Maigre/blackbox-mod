# PR map — how the fork's work becomes JOEBOX PRs (proposal, 2026-10-17, for Thomas's review)

D-019 sets the branch model (`main` a mirror, one PR-shaped branch per feature or fix, `maigre` = upstream + every PR
as if taken + a thin fork layer) and leaves open how a `37loop/…` task branch is split into those branches. This is
the proposal for that, and the map of what we have. Upstream moved on 2026-10-17: **JOEBOX 1 rc4** (`19d29f1`) fixes
the restart loop with PRIMASK instead of LDREXB/STREXB — the same root cause as our PR #2, which it supersedes — and
reworks `src/usbdev.c` (+130) and `src/cpu.c`. A local branch `rc4-sync` (37.3.2) merges it into 37.3.1.

## The layers

| # | branch (from upstream `main`, rc4) | what | state | depends on |
|---|---|---|---|---|
| 1 | `fix/restart-loop-ldrex` (PR #2) | b2chk without exclusive access | **superseded by rc4**: close with a thank-you (Thomas) | — |
| 2 | `fix/preview-cell` | the pre-listen voice is no pad (input, insert, LFO retrigger) | PR-shaped, 1 commit; rebase on rc4 (insert renames) | — |
| 3 | `fix/usbdev-debug` *(new)* | DEBUG peek / poke bounded to whole regions (gate3b F-j: an over-read bus-faulted the unit); EP0 IN flushed on a new SETUP (F-i: a stale reply answered every later request) | in 37.3.1d's `usbdev.c`; to cut onto rc4's `usbdev.c`, without the mailbox | — |
| 4 | `fix/waveform-labels` *(new)* | the Waveform screen's corner labels white with a 1 px black edge, every pad mode (gate3b F-d) | inside `clipwin.c` today, gated on the Clip Window's bank 2; to move into its own module (`src/wavelabel.c`, `patches/wavelabel.py`, `test_wavelabel.py`), unconditional, no tie to the Clip Window | — |
| 5 | `feat/linux-dev` | build and test on Linux (no clang, no FMA), Ghidra paths from the environment | PR-shaped, 1 commit; rebase on rc4 (`build.sh`) | — |
| 6a | `feat/clip-slip` *(replaces `feat/slip`)* | Slip: the row, the reader's fold, the knob v3 (accelerator, detent), the file-change latch fix, the browser stuck-pad retire (finding 9) | `feat/slip` has the 37.1 layout (all in bank 1); rebuild in 37.3's split (hooks in `clipwin.c`, maths in `clipwin_b2.c`, bank 2) so later layers add code, not churn | — |
| 6b | `feat/clip-region` | Region Auto / File / Loop; the Clip-mode Waveform knobs (TL/TR/BL/BR, names, bracket, the pad's own file length — finding 12); the playhead (H5) | in 37.3.1 | 6a |
| 6c | `feat/clip-looplen` | Loop Len: the window, the forced Sync, the settle (7 polls) | in 37.3.1 | 6b |
| 6d | `feat/clip-fit` | Fit (rows and D-026's rules, the interpolating reader, the tempo follow) | in 37.3.1 | 6b |
| 6e | `feat/clip-loopfade` | Loop Fade on a Clip region | in 37.3.1 | 6b |
| 7 | `feat/looper` → PR-shaped cut | Looper FX (P4): FX A types Looper / Loop In, the XY page | built, not on a unit; cut after Gate 4 | — |
| — | fork-only, never a PR | `notes/`, `bench/` (`bbusb.py`, `bbshot`, `bbmidi`), the parameter mailbox (dev builds, needs `cw_bank`), the 37.x names in `src/release.h`, `FORK.md` | | |

The Clip Window shares, across 6a–6e: the reserved ids `0x1C8–0x1CB` (ask Justin to reserve them, first contact
#t-006), `cw_bank` in SDRAM (the core of master's block, `CORE_BYTES`), its bank-2 payload, and the chain lines (`master.c` register / alloc,
`insert.c` defaults, one line in `duck_block`). Each layer adds its own rows, hooks and maths to `clipwin*.c`.

## Two ways to ship the Clip Window

- **A stack of five PRs (6a → 6e).** Each builds and passes `./check.sh` alone on upstream + the layers below. Best to
  review; costs a careful split of `clipwin.c` / `clipwin_b2.c` (the layers interleave there today) and a test file
  per layer — about 1–2 days.
- **One PR with a clean five-commit series**, one commit per layer, each commit building and passing. Cheaper (the
  split is by commit, not by branch); Justin squashes releases anyway.

Recommendation: ask Justin which he prefers at first contact; prepare the five-commit series either way (a stack is
then five branches cut at those commits).

## Mechanics (closing D-019's open point)

1. From now on **one commit = one layer**: never `src/` and `notes/` in one commit, never two features in one
   commit. A trailer names the layer (`Layer: clip-fit`, `Layer: fork`).
2. To cut a PR branch from a task branch: start at upstream `main` (or the layer below), take that layer's files in
   their final state (not commit-by-commit cherry-picks of mixed commits), add its README bullet and test, commit as
   one PR commit in JOEBOX's style (addresses as C comments, no fork names).
3. Every PR branch passes `./check.sh` alone. A fork-only `bench/prcheck.sh` builds each branch in a temporary
   worktree against stock 3.1.9 and reports its suites, its `.cave` room and its image hash.
4. `maigre` = upstream `main` + a merge of each PR branch + the fork layer (D-019 (3)); the unit runs `maigre`'s
   release line.
5. When Justin takes something, merge his `main` and resolve toward his version (D-019 (4)), as `rc4-sync` does for
   the restart fix.

## Order to propose upstream

1. Close PR #2 (superseded). 2. `fix/preview-cell`, `fix/usbdev-debug`, `fix/waveform-labels` (small, independent,
useful to every JOEBOX user). 3. `feat/linux-dev`. 4. First contact (#t-006 / #t-007): the Clip Window, its ids,
one PR or a stack. 5. The Clip Window layers, one at a time. 6. The Looper after Gate 4.

## Risks

- **Bank-1 room** is the hard budget: the release build has 696 B free after 37.3.1, the dev build 8 B. Each PR must
  fit on upstream alone; the layers' sizes are measured by `prcheck.sh`, not guessed.
- The split must not change behaviour: the union of the PR branches, built, must be byte-identical to `maigre`'s
  release build (`prcheck.sh` checks this).
- Upstream keeps moving (rc2 → rc4 in three days): cut the PR branches right before proposing them.
- **The Looper does not fit beside the Clip Window as it stands**: it needs 673 B of bank 1 (`looper.o` 645 +
  `looper_thunk.o` 28, features/looper.md "Costs") against 696 B free in the 37.3.1 release build and 8 B in its dev
  build; and its SDRAM bank (master's block `+ 0x84100`) now falls inside the inserts' bank (`+ 0x62900`, since D-030;
  the Clip Window's `+ 0x83900` before). Bank-1 room is the architecture question before P4 lands, and the MIDI plan meets the same wall (its option:
  let bank-2 code call stock at its fixed 3.1.9 addresses, never the cave — needs Justin's view).
