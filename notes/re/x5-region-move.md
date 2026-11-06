# X5 — Region Move: what one move's two posts do (blackbox#t-042, sub-step ①)

Stock 3.1.9 + this fork's Clip Waveform (`src/clipwin.c` at `5d2fc81`). Found 2026-10-22. Region Move (plan rev 1,
hub blackbox#t-032) turns TL into a slide of the whole region: each turn posts Loop Start `0x91` AND Loop End `0x92`
by the same delta. Three questions came before the patch:

1. Does the app clamp a Loop Start posted past Loop End (or a Loop End below Loop Start)? That decides the post order.
2. What do the two refreshes of one move do to the white bracket and to the moved-marker view (#t-028's rule)?
3. Can a wrap fall between the two posts?

Marks as in X3: ✓ = run under Unicorn; *inferred* = a static read.

## Short answers

1. **No clamp anywhere in the app.** ✓ `SetCellParam 0x0809FA50` (real) on a Clip pad's store (Loop Start 24 000,
   Loop End 72 000): Loop Start 80 000 is stored and posted as 80 000, Loop End is left at 72 000; Loop End 10 000
   is stored under Loop Start 24 000 just as plainly; `0x7FFFFFF0` and −5 go through too. Each call is one engine
   `0x39 {0x102, id, value}` and one UI `0x66`, and it never touches the other id. So an inverted pair can sit in
   the store and in the class-H object between a move's two posts, and nothing but the post order prevents it.
   **The order that keeps every intermediate pair valid: moving forward, Loop End first; moving back, Loop Start
   first** (the intermediate region then contains both the old and the new one).
2. **Each refresh moves one edge, so the view jumps twice and ends on the edge posted second.** ✓ (the Screen rig
   of `test_clipwin.py` §12: the view's refresh `0x66` through `FUN_080A6D28`, `clip_view` and `cw_bracket` real,
   `fw_wave_show 0x080C6E68` hooked):

   | posts (from [24 000, 72 000) or the row above) | bracket after each | view sent to |
   |---|---|---|
   | forward 4 096: Loop End 76 096, then Loop Start 28 096 | [24 000, 76 096), [28 096, 76 096) | 76 096, then **28 096** |
   | back 4 096: Loop Start 24 000, then Loop End 72 000 | [24 000, 76 096), [24 000, 72 000) | 24 000, then **72 000** |
   | forward, the wrong order: Loop Start first, then Loop End | [28 096, 72 000), [28 096, 76 096) | 28 096, then 76 096 |
   | forward 61 904, the wrong order: Loop Start 90 000 past Loop End 76 096, then Loop End 138 000 | **off** (is_loop: ls ≥ le), then [90 000, 138 000) | nothing, nothing |

   So with the safe order the view lands on Loop Start moving forward and on **Loop End moving back**: the task's
   « the view goes to Loop Start on a move » needs code of the patch's own (the refresh must know a move is under
   way, or the move must show Loop Start itself after its second post). In the wrong order a move longer than the
   region hides the bracket for one refresh and leaves the view where it was (both edges moved: `cw_bracket` −1).
   TL's range today is `0 .. Loop End` from the store (`clip_view`), so after the intermediate refresh it reads the
   half-moved pair; Move's range `0 .. len − (Loop End − Loop Start)` must come from a whole pair.
3. **Yes, a tick can fall between the two posts** (*inferred*). The app → engine ring (engine `+0xD7E0`, X1) is
   drained at the top of each audio tick (`0x08053186` / `0x08053C46`), and the audioTask runs at priority Realtime
   (X2) over the GUI task that posts. A tick that starts after the first `FUN_0804C59C` and before the second hands
   the class-H object only the first, and a wrap in that tick adopts it (`adopt` reads H `+0xFC` / `+0x100`, in
   `src/clipwin_b2.c`). The window is the GUI's time between the two posts (one `SetCellParam`'s tail, its `0x66`,
   the next one's head): microseconds against a tick of a block, and the wrap must be in that tick, so it is rare;
   it cannot be measured here (no RTOS under Unicorn). In the safe order its effect is one pass of the intermediate
   region: valid, `|delta|` longer than the clip (under Fit, that pass at another rate). The plan's guard is what
   closes it: the move marks its pad in `cw_bank` before the first post and clears it after the second, and a wrap
   that finds the mark keeps the region it had.

## For the patch (sub-step ②)

- Post in the safe order from the hook, both from the GUI task (X1: never `FUN_0804C59C` from the audio task).
- Take the length from one whole pair (the app's store, read before the first post), not from the view's copy
  between refreshes.
- The view: Loop Start at the end of a move, in both directions (row 2 of the table is the case to test).
- The wrap guard in `cw_bank` (bank 2), or a reason in the feature doc why one wrong pass is accepted.

## Reproduce

In a worktree after `./build.sh` and check.sh's `patch.py` line, with the toolchain on `PATH` and `PYTHONPATH=.`:
a scratch script that `exec`s `test_clipwin.py` lines 1–906 and 4105–4246 (the Screen class), builds `Screen()`, and
then (1) calls `0x0809FA50` on a pad store set up as §12's « what the forward sends » block does, reading back with
`0x08093E9C`; (2) `sc.open(CLIP12)`, then `sc.stored(_92=…)` / `sc.stored(_91=…)` with a `UC_HOOK_CODE` on
`0x080C6E68` recording `r1`. Each runs in seconds.

## x2 — a knob event between a move's two refreshes (hub blackbox#t-042 turn 6, static)

clipwin_move reads Loop Start and Loop End from the view's copy of the pad store (`view+0x2370`), and that copy is
filled whole by `FUN_0809A830` from the app's store on each refresh (notes/re/a3). Both `SetCellParam`s of a move run
inside the knob event's own handler, in the GUI task, so the app's store holds the whole moved pair before any later
message runs: a refresh handled after the move copies both edges, never one. A second knob event queued ahead of
the move's refreshes reads the whole old pair: its delta is taken from that pair and its two posts keep that length,
so the region lands where the second turn says, at the same length. No half pair reaches clipwin_move.
