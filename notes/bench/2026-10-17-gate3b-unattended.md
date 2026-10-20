# Gate 3b — the unattended runs on 37.3.2d and 37.3.3d (2026-10-17 evening)

The measurable part of Gate 3b, run by `bench/autogate.py` with nobody at the unit: rows through the dev build's
parameter mailbox (`bbusb.py set` / `get`), pads started and stopped by MIDI note (`bbmidi.py`; Pad Note "Default" =
36 + q on the Global In channel), takes over USB audio, the bank and the pad objects by the bounded peek, screenshots
(`bbshot.py`). Takes and logs: mgr-ran `/data/dev/gate3b/auto/run-*`. The part-1 report this follows is
`2026-10-17-gate3b-part1.md`.

## Conditions that matter

- **The internal clock, with the transport left playing.** Under an external MIDI clock (Tools > Clock > Receive =
  USB Device, the host sending 24 ppqn at 120) the unit's tempo estimate moves: the fitted BPM took three values in
  10 s (119.9954 … 120.0008), rate 0.934044 … 0.934093. Inaudible (about a thousandth of a semitone) and it answers
  row 23's question (review F5: yes, the fitted BPM moves while the clock stands still) — but a bar is then not
  96 000 samples and every sample-exact check fails by construction (run-1, run-2).
- **The bench client of the build on the unit.** `bbusb.py` checks the bank's layout magic; autogate takes the copy
  from the installed build's commit (`BB_BENCH`), never a worktree another session is changing.
- **Light USB traffic.** Twice the unit's USB went quiet for a moment under audio capture + 448-byte segment peeks
  every ~19 ms + MIDI clock every 20.8 ms (F-i): an audio read error and a control timeout together, no restart, no
  fault record. On 37.3.3d the link answered correctly right after (37.3.1d's EP0 flush at work). Not seen again
  once the MIDI clock was off.

## 37.3.2d (run-3, run-4: internal clock)

| check | measured | |
|---|---|---|
| reference (B on File) | exactly 2-bar periodic | ✓ |
| Region Loop / File | **−6 072** / **0** | ✓ |
| Region Auto | **−6 072** | ✓ |
| Loop Len settle (37.3.1's 7 polls) | 1/4 taken 0.267 s after the mailbox's done (~0.31 s after the store changed); Off 0.001 s | ✓ |
| Fit Auto, 3 beats, 6 beats | exactly periodic over 4, 3, 6 beats; Auto 4 beats, rate 0.934083 | ✓ |
| Loop Fade | the seam step 0.1198 recurring at 0 %, gone at 5 % | ✓ |
| F-a (pad 1, Slip −0.645, Fit Auto) | a 0.0919 step recurring every pass: the click | ✗ |

The F-a probe found the cause: every ordinary step's segment starts with fade-in 256 / countdown 5 744, the step-0
segment at each wrap with fade-in 0 / countdown 6 000 — at full gain while step 55 fades out. Both pads read have
`+0xBA1` = 1, Attack 0 (stock's default), where stock starts step 0 hard; once Slip, a Region or a window moves step
0 into the audio, each wrap is a hard cut (RE README open point 7, answered). Fixed in 37.3.3 (D-028).

## 37.3.3d (run-6, run-7: internal clock)

Install: the first boot rewrote bank 2 and restarted once (header `21324242 7f4ed13e 00004220 fbc60061`, magic
`CWNB`), TOOLS `37.3.3d` with no `!`, no fault or watchdog record.

| check | measured | |
|---|---|---|
| reference, Region Loop / File, Auto | exact, −6 072 / 0 / −6 072 | ✓ |
| Fit Auto, 3, 6 beats | exact | ✓ |
| Loop Len settle | 0.27 s / Off 0.002 s | ✓ |
| Loop Fade | 0 %: the seam recurs (0.1198); 5 %: gone. This region (3.74 beats, Fit Off) folds mid-step, where 37.3.3's step-0 rule cannot reach: Loop Fade stays the answer there | ✓ |
| **F-a** | the largest recurring step **0.0217** (37.3.2d: 0.092; the Slip-0 baseline 0.022): **the click is gone** (withdrawn on 2026-10-19 over F-l, upheld on 2026-10-20: this take is slipped, it equals 20/10's slipped take of pad 1 to within 75 samples; 20/10 measured 0.0197 slipped and at Slip 0, `2026-10-20-gate3b-part3.md`) | ✓ |

The slot snapshots see step 0 before its first read, still in stock's form (fade-in 0, countdown 6 000 = 5 744 +
256); `cw_slot` rewrites it to 256 / 5 744 at that read. The audio is the evidence.

Left for part 2 (Thomas at the unit): 3b-10 to 3b-15, 3b-18, row 21's preset load, and the corner labels and the
playhead (H5) seen on the screen.
