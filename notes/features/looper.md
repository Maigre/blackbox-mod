# Looper FX — P4 (`feat/looper`, blackbox#t-010)

Status (2026-10-16): v1 built, reviewed twice, review fixes in; Unicorn and host suites green
(`test_looper.py`, `./check.sh` 0 failed). **Not yet on the unit**: Gate 4 (blackbox#t-012) is the first time it
runs on hardware. Bank 2 changed, so the bench needs this build's `BBEXTRA.BIN` next to its `BLACKBOX.bin`.

Plan: `notes/plan.md` "Looper FX — Workflow 2". Decisions: D-005 (the behaviour), D-020..D-025 (how it was mapped onto
the XY page and built). RE: `notes/re/README.md` §3 "P4 — Looper FX", A5 (DJ FX and the XY page), A6 (where the input
is in a block), A4 (the clock), X2 (memory).

## What it does on the unit

FX button → XY page. FX A's type list gains **Looper** and **Loop In** after Repeater, Gater and Filter (they read
`---` when bank 2 is not installed, like Prism). Both keep recording the last 16 s of their source all the time, so a
touch can loop what has *already* played (the stock Repeater can only repeat forwards from the touch).

- **Touch** the pad: the loop's start is the grid line at or before the playhead for the length under X (`floor(t /
  L) * L`, t the tick the pads see). The music plays on, live, until that cell ends (the out-point); from there the
  cell repeats, each pass in time with the pads. So a touch never jumps the music: what you hear next is the bar you
  were in, coming round. At 4 bars this can mean up to 4 bars before the first repeat (D-025 asks Thomas whether he
  wants the alternative, "loop the last complete cell at once").
- **Lift**: back to live over 256 frames (5.3 ms), unless Hold is on.
- **Hold** (the stock XY Hold button of FX A): latches. Hold alone, with no finger, catches with the last length.
- **X**: the length, 7 equal zones, left to right: 4 bars, 2 bars, 1 bar, 1/2, 1/4, 1/8, 1/16 (left = longest, as the
  Repeater's X). The start stays where it is; the read head jumps (64-frame crossfade) to where the new length's
  loop is on the grid now. Going shorter lands on the same phase of the shorter loop; going longer lands where the
  longer loop is (live again if its first pass is not over). So 1 bar → 1/16 → 1 bar comes back on the bar lines.
- **Y**: a 12 dB/oct high-pass on the loop. Bottom = filter out entirely; then 10 Hz at the bottom to 4 kHz at the
  top (`10 × 400^y`), Q 1.
- **Transport**: stopped, a touch loops the last L frames at once (there is no grid to wait for). STOP while looping
  keeps looping. PLAY re-phases the loop to the restarted grid within a pass. A tempo change keeps the loop on the
  grid: each pass is cut short or runs on to the new length (no stretching).
- **Looper** (Source: Mix) loops Out 1 at the DJ FX point: pads, the FX1/FX2 returns, the master EQ, the input when it
  is monitored on Out 1, JOEBOX `Input:` pads on Out 1. It replaces Out 1 while engaged.
- **Loop In** (Source: In) loops the audio input alone, as the recorder takes it: Rec Input (L+R, Left = L on both
  sides, Right = R on both sides), each channel silenced when its jack is not set to AUDIO (GATE / CV / CLK), times
  Rec Gain. If the input is monitored on Out 1 (Rec Mon On, or Auto with the Record view open or a take running,
  Mon Output Out1, the jacks allowing it), the loop replaces it there; otherwise the loop plays on top of Out 1 and
  adds nothing until its first out-point. Under Rec Input Resam it is still the input, on top.
- Like every DJ FX type, FX A is Repeater again after a power cycle (RE open point #21).

## How it is implemented

Route A of the plan (D-024): the Looper *is* FX A's own Repeater object in two more modes, the pattern
`src/munchi.c` uses for the delay. Nothing new is allocated for the ring.

### Hooks (`patches/looper.py`, riding the `master` set; `duck_block` in the `duck` set)

| site | stock | now | why |
|---|---|---|---|
| `0x0808C594` | `bl FUN_0808C0D8` (FX A list, 3 names) | `bl looper_register_fxa` | 5 names; also registers `0x1cc` "Length:" on stock's Clip Quant names `0x080ECB0C` (7 of them) |
| `0x0806E174` | `cmp r2, #2; bhi` (slot setter, FX A type) | `b.w looper_fxa_set` (`looper_thunk.S`) | index ≤ 4 → `looper_latch` answers the class (`0x40`, the Repeater, for 3 / 4) → stock's swap `0x0806E048`; > 4 → `bx lr` as stock |
| `0x080B1E44/48`, `0x080B20B8/BC` | literals → axis table `0x080EEA78` (count 3) | → `lp_axes` (count 5) | Looper / Loop In axes: X = `0x1cc`, Y = `0x30` (EchoHP's `HPF:`, 0..1000) |
| `0x080DF58C` | Repeater vt+0x0c → `0x0806D859` | `looper_process` | in mode 3 / 4, `lp_run` (bank 2) instead of the Repeater |
| `0x080DF5F0` | Repeater vt+0x70 → `0x0806D0A1` | `looper_active` | always 1 in mode 3 / 4, so the container runs it (and the ring is fed) while nothing loops |
| `src/duck.c` | — | `looper_tick(engine)` before the stock tick | the clock as the pads see it this block: sample, tick (i64), playing |

Not wrapped: the Repeater's hold (+0x74) and set_param (+0x64). The DSP reads FX A's channel queue itself
(`0x15` finger, `0x1a` Hold, `0x1cc` X, `0x30` Y, type `0x40` = reset), in order, every block.

Changing type in and out of Looper / Loop In resets the Repeater, and leaving zeroes the last 2048 floats of both
ring buffers: the Repeater's backfill reads behind its write index, and our int16 pairs read as floats can be NaN.
Looper ↔ Loop In restarts the ring (it held the other source).

### State

`struct lp_bank` (`src/looper.h`), 0x200 bytes at `PRISM_BYTES + 0x2d900` in master.c's boot block (`EXTRA_BYTES`
0x2db00; 0x2d100..0x2d900 is kept for the Clip Window's bank so neither offset moves when `feat/slip` merges).
`master_alloc` clears its magic at every boot. Bank 1 (`looper.c`) writes the head: the latched mode, the sub-slot,
the clock snapshot. Bank 2 owns `struct lp_dsp` (132 bytes, no pointers, one layout on the unit and on a 64-bit host):
the ring's write index and history length, the loop (in-point, pass position `phi` with its fraction `acc`, pass
length, pass count `npass`), the grid lock (`in_tick`, `anch`), the crossfade and the declick, the HPF.

### The ring

FX A's Repeater allocates two ring buffers of 384,000 floats at boot (X2). In Looper modes they are 768,000 frames of
planar int16 (L in one, R in the other): 16.0 s. The scale is 8192 per full scale (12 dB of headroom: Out 1 before
the compressor can exceed 1.0). It is written every block. A loop may be at most `cap − 1024` frames (4 bars needs
more than 60 BPM), and a held loop never gets written over: once its in-point is `cap − 512` frames old the ring
stops writing until the loop is released (a catch right after then moves its in-point forward by whole loops, to
true history).

### One block (`lp_block`, bank 2; `lp_gather` reads the firmware's objects first)

1. **Messages**, in queue order (`lp_gather` keeps only the last X and Y of each run between touch / Hold / reset
   events, so a stall can never push a release out of the 32 slots). The view's *rest posts* are skipped: X = 1/2,
   Y = 500 after a Hold toggle (also when they arrive a drain late: `hskip`), and the X / Y it posts just before a
   finger-up with Hold off.
2. **Policy.** Finger or Hold and not engaged → catch, unless the clock snapshot is stale (a PLAY / STOP block) or the
   touch-down's X and Y have not arrived yet (the UI task was cut off between its posts): then the catch waits one
   block. Engaged → last block's X / Y now (`lp_length`), this block's next time: rest posts that race ahead of their
   release (UI and audio are separate tasks) are dropped by that delay. Neither → release.
3. **Catch** (`lp_engage`): in-point from the snapshot tick's phase in this length's grid (within half a tick of the
   grid: 0.26 ms at 120 BPM); read head on the frame being written (live) until the out-point.
4. **X** (`lp_length`): the pass count since the in-point (`npass`, exact below 64, then kept mod 64) plus the position
   in this pass give the position in the new length's loop; the read head goes there (crossfaded), or back to live.
5. **Grid lock** (`lp_lock`, while the transport plays): the in-point's tick is taken after each catch and after each
   PLAY / STOP. Every block, the frames left in this pass are held against the frames left to the grid's next line;
   more than 2 ticks apart, the out-point moves to the line. Within 2 ticks nothing moves (the tick is rounded, so a
   loop on time reads up to a tick either way), so at a steady tempo the loop is sample-exact. No correction while
   the in-point is still ahead, none that would end a pass before its in-point or make it longer than the ring keeps.
6. **Frames**: write the ring; at the out-point jump back to the in-point with a 64-frame crossfade from the
   continuation; a new crossfade that cuts a running one short is declicked (the step it leaves fades out over 64
   frames); the HPF (`src/filter.c`'s SVF, copied: bank 2 cannot call bank 1); the mix (Looper: in place of Out 1;
   Loop In: in place of the monitored input, or on top); the engage / release gain ramp.

**Loop In's source** (`lp_gather`): the audio object's own raw input buffers (`*(0x2400A9C0 + 0x8FB0 / 0x8FB4)`,
written once a block by `FUN_0804CAA4` before the tick, A6 step 1), times Rec Gain (`rec + 0x64`, float) on Rec
Input's channels, a non-AUDIO jack silenced. Read raw because input bus 0 is not the input any more at the DJ FX point:
the recorder scales it in place while it listens and, under Resam, overwrites it with last block's Out 1. If those
pointers are not valid RAM the source falls back to input bus 0 (v1's source), and to silence under Resam.

### Costs (this build)

- Bank 1: `looper.o` 645 B + `looper_thunk.o` 28 B. Bank 1 has about 3.4 KB left; nothing of the review fixes is in
  bank 1.
- Bank 2: `looper_dsp.o` 4,516 B (bank 2 payload 17,412 B of ~770 KB).
- SDRAM: master.c's block grows by 0xA00 (0x84300 in all); the ring is the Repeater's own 3 MB.
- Stack below the DJ FX container: `looper_process` 48 + `lp_run` 232 + `lp_block` 120 + `lp_xfrom` 8 = 408 B (Prism's
  path below `comp_process` is 600 B).
- CPU: Unicorn instruction counts per 128-frame block (the block is 1.28 M cycles at 480 MHz): idle 10.7 k, looping
  20.5 k, a wrap with crossfade and HPF 28.8 k. The unit's TOOLS load readout settles it (RE open point #24).

### Tests (`test_looper.py`)

T1 build and placement · T2 the patch sites decoded from the image · T3 the real registrar · T4 the XY view (axis
binding, value map, rest posts, the view's own handler) · T5 latch and swap on the real container · T6 idle · T7
the catch on the grid (97.3 / 120 / 174 BPM) · T8 X (phase both ways, back to live, a sweep over all lengths on a
tone no length holds whole cycles of, step bound) · T9 release, the rest-post race, 42 moves in one drain · T10
Hold · T11 the HPF's response, and the unit's `lp_block` against the host build over 300 random blocks (split drains
included) · T12 Loop In (monitored / on top, jacks, Rec Input, Resam, Rec Gain, the bus-0 fallback) · T13 the
transport (stopped catch, PLAY block, STOP and PLAY while looping, lead-in) · T14 the ring's limits · T15 cost ·
T16 Repeater mode identical to stock, also after a Looper session · T17 (host) the review's cases: re-catch inside
the release of a frozen hold, overlapping crossfades, split touch-down, split Hold rest posts, tempo changes while
latched, Loop In's live pass on top.

## Not done yet

- **Rows**: `Source` is the type (Looper / Loop In); `Max Len` waits for P5 (`0x1cd` reserved next to `Loop Rec`);
  `Slip` waits for the `t004` merge and a knob home (D-022). `Y Ctl` is P6.
- **Save to a slot** (P5): Rec Input Resam records the Looper's output; Loop In keeps looping the input meanwhile.
- **Tempo**: the loop stays on the grid but is not stretched (P6 `Repitch`).
- **Loop In and the master EQ**: exact only with the EQ flat (the EQ runs between the monitor and the DJ FX); an
  `Input:` pad playing the same input is not replaced. Doc only (README Known issues).
- **16-bit loop**: no dither (−78 dBFS floor at the 12 dB headroom). A TPDF dither would put constant hiss at about
  that level on every loop; left out until a bench listen says the grain on quiet tails matters.
- Hold and the DJ FX type across a preset load / power cycle (open point #21), the XY orientation (#22), the FX A
  slot's address on the unit (#20): one look at Gate 4.

## How to bench it (Gate 4)

Build: `./build.sh && python3 patch.py solo slice duck chord cond filter cpu od comp seqfix fx2 munchi master fault
cave` (dev build: the USB peek works), then **both** `out/<set>/BLACKBOX.bin` and `out/BBEXTRA.BIN` on the card. Bank 2
changed, so the first boot reinstalls it and restarts once; TOOLS must show the load figures without `!`, and FX A's
list must read Looper / Loop In, not `---`.

1. A drum loop on pads into Out 1, 120 BPM, playing. FX A = Looper, Hold off. Touch mid-bar at X = 1 bar: the music
   plays on to the bar line, then the bar repeats in time with the pads. Lift: live, no click.
2. X from 1 bar down to 1/16 and back while holding: no clicks; back at 1 bar the loop's downbeat is on the pads'
   downbeat again (record Out 1 over USB, `bench/bbusb.py record 20 x.wav`, and line the onsets up).
3. Y from bottom to top while looping: a clean sweep, the bottom position bit-identical to no filter.
4. Hold on, lift: keeps looping. Hold off: back to live. Hold alone: catches 1 bar (or the last length).
5. Hardware into IN (Rec Mon On, Mon Output Out1, both jacks AUDIO). FX A = Loop In: the loop is the input only,
   the pads play on live over it; with Rec Mon Off it plays on top and nothing is added before the first repeat.
   Set jack 2 to CV: the loop's right side is silent.
6. Nudge the tempo ±1 BPM while a 1-bar loop is held for a minute: it stays with the pads. STOP, then PLAY: within a
   bar the loop is back on the bar lines.
7. TOOLS load readout while looping with the HPF up: average under about 85 % with the usual preset.
8. One look each for the open points: which half of the XY page is FX A and whether Y grows upwards (#22); after a
   power cycle, FX A's type and Hold (#21).

State on the unit, for when something looks wrong (`bench/bbusb.py peek`, dev build): the boot block's address is
the word at `0x38800F70`; the Looper's bank is at that `+ 0x84100`: `+4` the mode (3 / 4), `+0x1c` the `lp_dsp`
(`test_looper.py`'s `DSP_FMT` decodes it: `engaged` at `+0x2c`, `in_idx` `+0x38`, `phi` `+0x3c`, `npass` `+0x80`).
