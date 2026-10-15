# A6 — the audio input monitor path

Stock 3.1.9 (plus the JOEBOX full set where it says so). Found 2026-10-15 (loop turn, blackbox#t-003); revised the
same day after an independent verification, every disputed point re-run on a corrected harness (see "Verification").
The question: with Rec Mon On and Mon Output Out 1, does the monitored input reach Out 1 before or after the DJ FX
slots, the compressor and JOEBOX's Master FX insert? What does a Looper FX hear with `Source: Mix`, where does it read
the raw input for `Source: In`, and what does Resam record?

**Short answer: before all of them.** The monitor is mixed into Out 1's bus by the WAV recorder, which runs early in
the module chain, before the pads have even rendered. Everything on Out 1 that comes later in the block sees the
monitored input: the master EQ, both DJ FX slots, JOEBOX's Master FX, the compressor, the clipper, and the Resam tap.
Checked by execution on the stock image and on the JOEBOX full set.

Two findings that change the plan: **Gate 2's reference clip cannot be a Resam of the metronome** (the click never
reaches the tap, and the metronome mutes itself while a Resam take is armed), and **a test harness must set
`*(engine + 0x128E0) = engine`** or every module reads a null clock.

## The settings

| id | label | xml | values | engine field |
|---|---|---|---|---|
| `0x99` | `Rec Mon:` | `recmonmode` | **On (0)**, Auto (1), Off (2) | recorder `+0x59` |
| `0xdc` | `Mon Output:` | `recmonoutbus` | Out1, Out2, Out3, Out1L, Out1R, Out2L, Out2R, Out3L, Out3R | recorder `+0x68` = the output-bus index (0..8) |
| `0x9a` | `Rec Input:` | `recinput` | L+R (0), Left, Right, **Resam (3)** | recorder `+0x58`; metronome `+0x12D` = (value == 3) |
| `0x9c` | `Rec Active:` | `recactive` | (posted by the Record view, X1) | recorder `+0x5a` |
| `0xc5` | — (armed) | — | 1/0, posted when the Record screen arms an empty pad (X1) | metronome `+0x12C`; session object `+0x2A4` (X1); **not** read by the recorder |
| `0xd8` | `Gain:` | `ingain` | milli-dB (type 7), up to +20 dB | recorder `+0x64`, as a linear factor |
| `0xf8` | `Input:` (per jack) | `inputiocon` | GATE, CV, CLK, AUDIO | recorder `+0x280` / `+0x281` = jack 1 / 2 is AUDIO (message `0x72`) |
| `0xcd` | `Metronome:` | `metroopts` | Off (0), Rec (1), Play (2) (list `0x080EC614`) | metronome `+0x128` |
| `0xf7` | `Metro Gain:` | — | milli-dB | metronome `+0x130`, linear (−6000 → 0.501, run) |
| `0xf6` | `Metro Out:` | `metoutbus` | Out1 … Out3R, HP (9, the default) | engine `+0x28d88` |
| `0xba`..`0xbd` | `Headphone:`, `Out 1 Vol:` … `Out 3 Vol:` | `headphvol`, `out1vol` … | dB | engine `+0x28d64`, `+0x28d68`, `+0x28d6c`, `+0x28d70` |
| `0xb4` | `Compressor:` | — | Off / On (JOEBOX: the model list) | engine `+0x28d60` |

Params travel as message `0x39` `{u8 type; …; u32 cell @+8; u16 id @+0xc; i32 value @+0x10}`. The recorder (cell
`0x400`, its `+0x18`) and the metronome (also cell `0x400`) both read the cell-`0x400` queue. The recorder's `0x39`
switch (table `0x080621F8`) also stores `0x97` → `+0x40`, `0x98` → `+0x38`, `0x9d` (RecToPlay) → `+0x4b`, `0xc6` →
`+0x54`, `0xc7` → `+0x50`, `0xce` → `+0x5c`, `0xcf` → `+0x60`, `0x100..0x103` → `+0x28c/+0x290/+0x284/+0x288`, `0x104` →
`FUN_08061e60`, `0x105` → `+0x2a9`, `0x106` → `+0x298`. Registrations are in `FUN_0808c158` (`0x99` at `0x0808D17A`,
`0xdc` at `0x0808D6C6`, `0xf6` at `0x0808D990`; `0xcd` is the call at `0x0808D5C8`); the engine-global ones (`0xb4`, `0xba..0xbd`,
`0xf6`) are handled in `FUN_080520ec`, which forwards other cell-`0x400` params to the modules.

**Defaults and resets.** The recorder ctor `FUN_08061C04` leaves L+R, **Rec Mon Off**, Gain 1.0, Mon Output 0 and
both jacks AUDIO. Message `0x40` addressed to cell `0x400` resets it (`0x080621B4`): `str r3, [r4, #0x48]` is a word
store, so it clears `+0x48..+0x4b` (RecToPlay included), plus `+0x4c`, `+0x5a`, `+0x5c`, `+0x60`, and sets L+R / Rec Mon
Off; Gain and Mon Output survive. The app's global default (Rec Mon Auto, X1) only arrives as a later `0x39`.

## Buses

`ctx = engine + 0x128e0` (what every module's block method gets as its second argument). **`*(ctx)` is the clock
(the engine itself)**; it is stored by the engine init `FUN_080530FC` (`0x0805311C`), which the audio object's setup
calls (`0x0804C208`) after the ctor and which tail-calls the graph builder. Buffer objects are `0x14` bytes:
`{i32 cap, i32 len, float *l, float *r, u8 silent, u8 stereo}` (the `struct fw_buf` of `src/insert.c`).

| family | getter | address | index → meaning |
|---|---|---|---|
| output buses | `0x0805F37C` | `ctx + 0x150e4 + i*0x14` | 0 Out 1, 1 Out 2, 2 Out 3 (stereo) · 3..8 Out1L, Out1R, Out2L, Out2R, Out3L, Out3R (mono: **read by their left channel**) · 9 metronome · 10 delay return · 11 reverb return · 12/13 levels that *replace* io[2]/io[3] when not silent (written by the recorder when its `0x105` flag is set: inferred, not run) |
| input buses | `0x0805F390` | `ctx + 0x1583c + i*0x14` | 0 the ADC input (the bus `src/insert.c` reads) · 1 (`ctx + 0x15850`) **not an input**: a work buffer both pad classes take directly (class A at `0x080599AA`, class B at `0x08066804`, both pools hold `0x15850`) and mark silent before use · 2 the Resam copy (`ctx + 0x15864`) |
| scratch | `0x0805F3A4` | `ctx + 0x151fc + i*0x14` | work buffers (callers include the metronome, both pad classes, the reverb and the DJ FX code) |

The getter `0x0805F390` is called from two places only, both with index 0 (`0x08051906` the input copy,
`0x08062034` the recorder); the only literals `0x15850` in the image are the ctor's and the two pads'.
The tick's tail calls `FUN_0805f3b8(ctx, n)` (`0x08053B6A`): it empties the 0x38 per-cell message queues
(`ctx + 4 + k*0x604`) and marks output buses 0..13 (`ctx + 0x150e4` up to `ctx + 0x151fc`) silent with length n. It
touches neither the input buses nor the scratch family.

## One audio block, in order

The audio task `FUN_08041470` calls `FUN_0804caa4` (input) then `FUN_0804cb1c` (everything else) per DMA half.

| # | where | what happens to Out 1 (bus 0) / the input / the clock |
|---|---|---|
| 1 | `FUN_0804caa4` | ADC words → floats in the audio object's own buffers (`0x2400a9c0 + 0x8fb0` L, `+0x8fb4` R; then DC offset `+0x9038/+0x9040`, then trim `+0x9034/+0x903c`), then copied into **input bus 0** (`FUN_080518f0`), made stereo, 128 frames. |
| 2 | `0x0804CE74` | JOEBOX: `duck_block` (`lfo_tick`, `insert_tick`), then the stock tick `FUN_08053164`. |
| 3 | tick `0x08053182..0x080531BC` | **engine commands drained**: queue `engine+0xd7e0` (0x18-byte entries, indices `+0xdde0/+0xdde4`) → `FUN_080520ec`; queue indices `+0xe9e8/+0xe9ec` → `FUN_08051938`. PLAY (`0x74` → `FUN_08051eb8` → `FUN_0806996c`) and STOP (`0x75` → `FUN_08052010` → `FUN_08069a94`) take effect **here**, after `duck_block` and before any module. |
| 4 | `0x080531DA` | the **root chain** (`*(engine+0xfc00)` = `engine+0xd590`, linked by `+8`; names from `a7-stock-looper-class.md`): root[0] the chain head (forwards only), root[1] event router / session object (block `0x08050464`), root[2] clock out (cell `0x10400`), root[3] a note sequence (cell `0x20303`), **root[4] the WAV recorder** (vtable `0x080D07AC`, block `0x0806201C`), root[5] slice scanner, sixteen note sequences, held-note tracker, the 33 pads (class B `0x080D0890` and class A `0x080D06C8` interleaved per cell, + one class B at cell `0x401`), the **reverb** (cell `0x30100`, bus 11), the **delay** (cell `0x30000`, bus 10), the pad-note map, root[59] the **metronome** (cell `0x400`, bus 9). The recorder adds the monitor here, **before any pad renders**. |
| 5 | `0x080531E0` | the clock advance `FUN_080696d8` (**after** the root chain). |
| 6 | `0x080534DC` | `fw_position` cached at `engine + 0x28d78`. |
| 7 | `0x08053506`, `0x08053516` | bus 0 += bus 10 (delay) + bus 11 (reverb). |
| 8 | `0x08053526` | the chain at `engine + 0x28d8c`: the **master EQ** (type `0x35`, vtable `0x080CFC40`, cell `0x30200`) → the **DJ FX container** (`engine + 0x28d90`, vtable `0x080DF670`): 2 sub-slots, FX A (cell `0x30300`) then FX B (cell `0x30400`) (A5), both on bus 0. |
| 9 | `0x0805352E` → `0x08053CA0` | stock: the compressor `FUN_0804eddc` (`engine+0xfc40`) when `+0x28d60` is set. JOEBOX: `comp_process` always — **Master FX, then the compressor model, then the clipper**. |
| 10 | `0x0805353A` | **the Resam tap**: input bus 2 := a copy of bus 0 (`FUN_0804d880`). |
| 11 | `0x08053554..` | bus 0 copied to io[2..3] (Out 1) and io[0..1] (HP); buses 1, 2 → io[4..7], added to HP; mono buses 3..8 added to their io and to HP; **then** bus 9 (metronome) per `Metro Out` (TBH at `0x08053674`); **then** buses 12/13 overwrite io[2]/io[3] (the metronome on Out 1 included). |
| 12 | `0x08053AFA..0x08053B5A` | the Out volumes: io[0..1] × HP, io[2..3] × Out 1 Vol, … |
| 13 | `0x08053B6A` | bus reset `FUN_0805f3b8` (above). |
| 14 | `FUN_0804cb1c`, after the tick | per-channel trims (`0x2400a9c0 + 0x9014..0x9030`, not traced), then `FUN_0806002c` ×2 and `FUN_0805feb4` ×2 turn io into codec words (`src/usbdev.c`'s tap). Nothing adds audio after the tick. |

## The clock inside the block

All modules take their clock as `*(ctx)` (= the engine). Readers seen in a run: the router/session object, clock out,
the note sequences, the recorder (`0x0806202A`), class-A pads, class-B pads (`0x08067FB4`), the metronome
(`0x0805402C`), and three more; JOEBOX's `comp_process` reads the BPM there too (`src/comp.c:276-279`).

| engine field | unit | meaning |
|---|---|---|
| `+0x00` | samples (i64) | sample counter; `+= io[0xb]` in the advance, always |
| `+0x2c` | blocks | `+= 1` in the advance |
| `+0x30` | **ticks** (i64, 960/beat) | position: `+0x00` converted through the tempo anchor `+0x08..+0x18`, rounded to the nearest tick (run: 5.12 → 5, 25.6 → 26 at 120 BPM). Recomputed by the advance only while `+0x38` is set, and by PLAY (`FUN_0806996c`); frozen while stopped |
| `+0x38` | flag | playing; set by PLAY, cleared by STOP (`FUN_08069a94`, which is the whole function) |
| `+0x28d78` | ticks | `fw_position` cached after the advance (step 6) |

`fw_position 0x08069C38` only copies `+0x30`. `FUN_08069C64(clock, &ticks)` converts a tick position through the
anchor and returns it in samples **minus `+0x00`** (an i32 offset from the current counter; static read).

What each stage sees, by execution (sample counter planted at 1,000,000, 120 BPM, 128 frames):

| stage | `+0x00` | `+0x30` / `+0x28d78` | play state |
|---|---|---|---|
| `duck_block` (tick entry) | block start S | block start / same | before this block's commands |
| root chain: recorder, pads, metronome … | S | block start / same | **after** this block's commands |
| master EQ, DJ FX A/B, compressor, tap | S + 128 | block **end** / same | after |

So the pads see the same counter and position as `duck_block` **except on a block where an engine command changes
the transport**. On the PLAY block `duck_block` saw "stopped" and the old position; the pads see "playing", position
0 (or −3840 with Lead In, X1) and the new anchor. On the STOP block `duck_block` saw "playing"; the pads see
"stopped" with the position frozen.

## The monitor itself (recorder block `0x0806201C`)

Per block, once its messages are read: if Rec Input is Resam, input bus 0 is **overwritten** with input bus 2 (the
previous block's tap, `0x08062784`). Otherwise the recorder decides whether it is **listening**: Rec Mon On, or Rec
Active (`+0x5a`), or a take started (`+0x48`). `+0x48` is not the arm: the start routine `0x08061C94` (message `0x25`,
or `0x28` when idle with Rec Active) writes u16 `0x101` to `+0x48/+0x49`, and `+0x49` drops when writing begins. The
arm (`0xc5`) is kept by the session object and the metronome only.

When listening, and the jacks allow it, it multiplies **Rec Gain into input bus 0 in place** (`0x080624E0`,
`0x08062508`) and feeds its meters. The jack rule is per channel (runs below):

| Rec Input | needs | scaled in place | monitored as |
|---|---|---|---|
| L+R | **both** jacks AUDIO (`+0x280` and `+0x281`); one jack is not enough | L and R | stereo |
| Left | jack 1 | L only (R left raw) | L on both sides |
| Right | jack 2 | R only (L left raw) | R on both sides |

Monitor resolved On = Rec Mon On, or Rec Mon Auto with Rec Active or a started take. Auto therefore follows the
Record view (which posts Rec Active when it opens, X1) and the take, not the arm. Rec Mon Off with Rec Active scales
the input but monitors nothing. When the monitor is On, Rec Input is not Resam and the jacks allow it, the input is
**added** into output bus `Mon Output` (`0x080627EE`, `0x080627F8`): L += in L, R += in R (a Left/Right source goes
to both sides). So:

- Mon Output **Out1** → bus 0 → through steps 7–12 like any pad on Out 1.
- Mon Output **Out1L/Out1R/…** → a mono bus → straight to io at step 11: no EQ, DJ FX, Master FX, compressor or
  Resam. A mono bus is read by its left channel, so **with Rec Input L+R, Out1R carries the input's left channel**
  and the right input is dropped (with Rec Input Right it carries the right input).
- Mon Output **Out2/Out3** → buses 1/2 → straight to io: same.
- Resam never monitors (it would feed back).

## Answers for the Looper FX (P4)

**`Source: Mix` as a DJ FX type (a sub-slot of the container, step 8).** It hears bus 0 after: the pads routed to
Out 1, the delay and reverb returns, **the monitored input when Rec Mon resolves On and Mon Output = Out1** (× Rec
Gain, jacks as above), JOEBOX "Input:" pads on Out 1, the master EQ, and — in FX B only — FX A's effect. It does
**not** hear: the metronome, pads or monitor on Out1L/Out1R, Out 2/3, Out 1 Vol, and nothing of JOEBOX's Master FX /
compressor / clipper (they come after it). In JOEBOX's Master FX slot instead (the fallback), it hears all that plus
both DJ FX, still before the compressor.

**`Source: In`.** The raw input of the current block is input bus 0, `*(0x2400a9c0 + 0x9a74) + 0x128e0 + 0x1583c`
(the address `src/insert.c` already reads safely), 128 frames, stereo once step 1 has run. Read it **in `duck_block`
(next to `insert_tick`)**: there it is always raw. Later in the block it may have been scaled by Rec Gain — whole or,
with Rec Input Left/Right, one channel only — or replaced by last block's Out 1 (Rec Input = Resam). Alternative that
is raw at any point of the block: the audio object's own float buffers `*(float **)(0x2400a9c0 + 0x8fb0)` / `+0x8fb4`
(written only by `FUN_0804caa4`; static read). With monitoring on and Mon Output = Out1, the live input is *also* in
bus 0, so a looper that replaces bus 0 while engaged silences the live input too; mix instead, or monitor on Out 2 /
Out1L-R.

**Clock in a DJ FX sub-slot** (after the advance). Keep units apart: `+0x00` is samples, `+0x30` is ticks.
- The block's first sample is `engine+0x00 − io[0xb]`.
- The block's first tick is the `+0x30` value **before** the advance: take it from a `duck_block` snapshot (equal to
  what the pads read, transport edges aside). Do not subtract frames from `fw_position`; and converting 128 frames to
  ticks at the tempo (5.12 at 120 BPM) misses `+0x30`'s rounding by up to one tick.
- Where a tick lands in the block: `FUN_08069C64(engine, &tick) + io[0xb]` frames (it is relative to the counter, which
  already points at the block's end there; static read).

## Resam (Rec Input = Resam)

Resam records **input bus 2 = bus 0 as it was at step 10 of the previous block**: Out 1 after the delay/reverb
returns, the master EQ, both DJ FX and the compressor (JOEBOX: Master FX, compressor model, clipper); before Out 1
Vol, the metronome, the Out1L/Out1R mono buses and the per-channel trims. The manual's "after the compressor" is
right; with the stock compressor on, a steady 0.25 / 0.5 input came out −4.0 dB at the tap (one first block of a
freshly built compressor at its defaults, not a steady-state figure). The one-block delay of the tap is compensated
by the recorder: its start/stop sample is offset by `0x80` frames for Resam and `0x40` for the inputs
(`0x0806294C`/`0x08062950` and `0x08062DC0`/`0x08062DC4`; static read). So **P5's Save-via-Resam records the looper's
output** (if the looper is a DJ FX or Master FX type) through Master FX + compressor + clipper, and needs no extra
latency fix. To get a pre-compressor Save, a mod can take its own copy before `comp_process` runs the model and
replace the tap at `0x0805353A`.

**The metronome and Resam.** The click never reaches the tap: bus 9 is added to io at step 11, after step 10, whatever
`Metro Out` says. And the metronome **mutes itself** while armed (`0xc5`, cached at metronome `+0x12C`) with Rec Input
= Resam (`+0x12D`): the branch at `0x08054170..0x0805417A` skips its add into bus 9 (`0x080541A0`). The click keeps
running silently and is heard again as soon as `0xc5` drops (run F below).

## Corrections to earlier notes and the plan

1. **A4: `engine + 0x28d8c` is the master EQ, not the recorder.** The recorder is root[4] of the root chain, and the
   whole root chain (recorder, pads, delay, reverb, metronome) runs **before** the clock advance. The pads see the
   same counter and position as `duck_block`, not one block ahead; only the master EQ, the DJ FX, the compressor and
   the tap see the advanced clock. **Exception: a transport block.** Engine commands are applied between
   `duck_block` and the root chain, so on a PLAY or STOP block `duck_block`'s snapshot of `+0x38`/`+0x30`/the anchor
   is stale. `cw_target` should read the clock at the thunked pad call itself (`*(ctx)`), or treat any block whose
   command queue was non-empty at `duck_block` (`engine+0xdde0 != engine+0xdde4`) as a transport edge.
2. **Plan, Gate 2 recipe: "Resam one bar of the BB's own click" cannot work, twice over.** Resam taps Out 1 before
   the metronome is added, and the metronome is silent anyway while the Resam take is armed. Use the plan's fallback
   (a 1-bar factory drum loop) or **a pad playing a click sample routed to Out 1**: a pad goes through bus 0 and the
   tap. A cable loopback from Out 1 into the inputs (Rec Input L+R) would record the click, but adds the converters'
   round-trip latency, which is what Gate 2 is measuring.
3. **Harness (A2 / `test_clipwin.py`, and anything built from `re-scratch/a6/harness.py`).** The engine ctor
   `FUN_080512a4` plus the graph builder `FUN_080525f0` leave `*(engine+0x128e0)` = 0. Then every module reads its
   clock from address 0 (the mapped ITCM zero page): the transport looks stopped, positions 0, BPM 0. Call the real init
   `FUN_080530FC(engine, 0x080CB060, 0x2400A9C0, 0, [sp] = a 0x3604-byte block)` after the ctor (it runs whole under
   Unicorn and builds the same chain), or store the engine at `ctx` by hand. A2's `clipproc.py` already stores it.
   Two more traps: `FUN_0805f3b8` empties the cell queues, so post a message to a module after calling it; and
   `FUN_0805f410(ctx, msg, cell)` broadcasts to every cell **except** `cell` (PLAY uses it), while `FUN_0805f460`
   posts to that one cell.
4. **Plan risk row "input monitor reaches Out 1 after the FX insert": it does not**, for Mon Output = Out1.
5. For JOEBOX's "Input:" pads (`src/insert.c`): they read input bus 0 after the recorder, so with monitoring on they
   play the input × Rec Gain, and with Rec Input = Resam they play last block's Out 1 (a feedback loop). That is
   upstream's to know, not ours to change.
6. **For X1 (not A6's question, found on the way).** X1 says samples are written only while Rec Active is set. In
   my runs (full engine, a real `0x25` take start, stub writer, transport playing) a take with Rec Active 0 wrote
   every block from its start tick and sent `0x26`. That held for Rec Quant None and for Rec Quant 1/16 (start at
   tick 240, first write in block 47), exactly as with Rec Active 1. X1's own "never set" run stopped after 20 blocks,
   before its 1-bar start, so it did not test the condition. X1 should re-check before P5 relies on it.

## Not settled

- When the app sends `Rec Active` (`0x9c`) beyond the Record view, and which pad's Rec Mon / Mon Output reaches cell
  `0x400` under RecConfig Per Pad: app side (X1 covers the arm path).
- Buses 12/13: who writes them and when (the recorder's `0x105` flag is the inferred source; not run).
- The trims at `0x2400a9c0 + 0x9014..0x9030`: not traced.
- Whether anything aliases the audio object's float buffers at `+0x8fb0/+0x8fb4` through a pointer copy (a literal
  scan finds no other user; a pointer copy would not show).
- On hardware, the dev build's USB peek (`src/usbdev.c`) would confirm the layout in a few reads:
  `*(0x2400a9c0+0x9a74)` = engine (`0x24037038` on the test unit); `*(engine+0x128e0)` = engine;
  `*(engine+0x28d8c)` points at an object whose first word is `0x080CFC40` (the EQ); `*(engine+0xfc00)` =
  `engine+0xd590`; following `+8` from there, the fifth object's first word is `0x080D07AC` (the recorder), and its
  `+0x68` changes with Mon Output.

## Verification

An independent verifier (scratch `re-scratch/v-a6/`) confirmed the note's ten main claims and raised the points
below. Each was re-checked here with new scripts (`re-scratch/a6/r2/`), on an engine built by the real init.

| point raised | settled by | outcome |
|---|---|---|
| The metronome mutes itself when armed with Resam; Gate 2 recipe impossible | `t2_metro.py`: the real metronome, **nothing stubbed**, driven only by real messages (PLAY, `0xcd` Play, `0xf7`, `0xf6`, `0xc5`, `0x9a`) through the engine queue; static read of its `0x39` handler and the branch | holds: click 0.5 on io[2..3] (Out1) or io[0..1] (HP), never in the tap; armed + Resam → silent everywhere; armed + L+R or Resam unarmed → audible; disarm → audible mid-click |
| Round-1 harness left `*(ctx)` = 0 | `h2.py`: ctor + builder → `*(ctx)` = 0; ctor + `FUN_080530FC` → engine, same 60-module chain; store at `0x0805311C` | holds; round-1 runs had a stopped, null clock. Its monitor/order results were re-run with the clock set and the transport playing, and are unchanged |
| `fw_position` is ticks, the P4 formula mixed units | `t2_clock.py` and the disassembly of `0x08069C38` / `FUN_080696d8` | holds; refined: PLAY (`FUN_0806996c`) also writes `+0x30`, and `+0x30` is rounded to the nearest tick |
| Transport commands are applied between `duck_block` and the pads | `t2_clock.py`: PLAY and STOP posted with the real `FUN_08051738`; static: the drain at `0x08053182..0x080531BC`, the `FUN_080520ec` switch (`0x74` → `FUN_08051eb8`, `0x75` → `FUN_08052010`) | holds (table in "The clock inside the block") |
| `+0x48` is "take started", not "armed" | static: the start routine writes u16 `0x101` there; `t2_take.py`: a real `0x25` sets it and Auto then monitors with Rec Active 0 | holds |
| Out1R carries the input's left channel | `t2_mon.py` H2 / HR | holds (Right → Out1R carries the right input) |
| Per-jack rule | `t2_mon.py` D, D1, D2, L1, L2, R1, R2 | holds. Round 1's "jacks not AUDIO" case had not actually run (its setup ignored the jacks): now run |
| Input bus 1 is a pad work buffer; reset range | literal scan of the image, `findbl` on the getter, disassembly of `FUN_0805f3b8` | holds |
| `0x40` reset, ctor default Off | `t2_reset.py`: `0x40` to `0x401` ignored, to `0x400` resets; ctor fields read after the build | holds; refined: the word store also clears RecToPlay (`+0x4b`) |
| Other `0x39` ids of the recorder and the metronome | capstone over the switch at `0x080621F8` and the metronome's handler; `t2_reset.py` / `t2_metro.py` store checks | holds |
| Tail order: mono buses before bus 9, 12/13 overwrite after | `t2_tail.py`: a distinct value planted in each bus, every write to io[2]/io[3] logged with PC and caller | holds; the 12/13 overwrite also removes the metronome from Out 1 |
| Recorder is root[4], four modules before it | `h2.py` chain walk | holds; the table now names root[0..4] |

## How this was checked

- **The graph, by execution** (stock image only): the engine ctor `FUN_080512a4` and the init `FUN_080530FC` (which
  runs the graph builder `FUN_080525f0`) run whole under Unicorn at the test unit's engine address. The allocators
  `0x0804436C`/`0x080443A8` are bump-stubbed into SDRAM and the C++ static-guard calls
  `0x080CA9D0`/`0x080CAA30`/`0x080CA97C` stubbed. ITCM is mapped because one constructor reads a null object at `+8`.
  Then both chains are walked by `+8`: vtables, type bytes, cells and output buses as in the table.
- **The order and the clock, by execution**: the stock tick `FUN_08053164` run block by block on that engine, with
  hooks on every module's block method and on the tick's stages, recording bus 0 and the clock fields at each. PLAY
  and STOP were posted through the engine's own queue.
- **The monitor, by execution**: input bus 0 = 0.25 / 0.5, the previous tap planted at 0.111 / 0.222, recorder fields
  set directly (or by real `0x39` messages in `t2_reset.py`), one tick per case, transport both stopped and playing.
  Results:
  - On → Out1: in bus 0 from the recorder on, at the EQ, both DJ FX, the compressor, the tap and io[2..3].
  - Stock compressor on: −4.0 dB at the tap.
  - Gain 0.5: input bus 0 scaled in place.
  - Out2: io[4..5] + HP only.
  - Out1L / Out1R: io[2] or io[3] + HP, the left input in both cases.
  - Off: nothing. Off + Rec Active: scaled, not monitored.
  - Auto: nothing, unless Rec Active or a take is started.
  - Resam: no monitor; input bus 0 = the planted previous tap.
  - The per-jack cases as tabulated.
- **Takes, by execution** (`t2_take.py`, `t2_take_q.py`): `0x25` posted to the cell-`0x400` queue with
  `FUN_0805f460`, a stub WAV writer at recorder `+0x20`.
- **The metronome, by execution** (`t2_metro.py`): the real module, envelope included, six cases × six blocks.
- **JOEBOX, by execution** (`t2_joebox.py`, the full-set image of 2026-10-15 14:49 with `out/cave.elf` symbols),
  entered at `duck_block`, `master_on` stubbed to 1. Order: recorder (monitor added) → advance → FX A → FX B →
  `comp_process` → `master_fx` (handed bus 0 with the monitored input, and BPM 120 now that the clock is set) →
  `clip_stage` → tap.
- **Static**: listings and decompiles of the tick, `FUN_0804cb1c`, `FUN_0804caa4`, the graph builder, `FUN_080530FC`,
  the command handler `FUN_080520ec` and its PLAY/STOP routines, `FUN_080696d8`, `FUN_0806996c`, the bus getters and
  reset, the metronome block `0x0805401C`, and the EQ / reverb / recorder block methods (the last three made functions
  in a rolled-back Ghidra transaction, project unchanged). Ids and names come from the registrar's pools and lists.
- Scripts (outside git): round 1 `/srv/dev/firmware/re-scratch/a6/` (`harness.py`, `tick_run.py`, `joebox_run.py`,
  `extra_run.py`, `decnf.py`); round 2 `/srv/dev/firmware/re-scratch/a6/r2/` (`h2.py`, `t2_clock.py`, `t2_mon.py`,
  `t2_metro.py`, `t2_reset.py`, `t2_tail.py`, `t2_take.py`, `t2_take_q.py`, `t2_joebox.py`); the verifier's
  `/srv/dev/firmware/re-scratch/v-a6/`.
