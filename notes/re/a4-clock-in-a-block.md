# A4 — the clock in a block

Stock 3.1.9. Found 2026-10-15 (loop turn, blackbox#t-003). The question was: is the second argument of the
engine's control tick `FUN_08053164` the `bufs` the recorder reads its clock from? **No — and the clock is the
engine itself.**

## What the control tick is given

`FUN_08053164(engine, io, x)` — the call JOEBOX's `duck_block(engine, a, b)` replaces (`src/duck.c`):

- `io` is the block's audio table: `io[0..7]` are eight channel buffers (handed in pairs to `FUN_0805f5c0`,
  `FUN_080617c0` and `FUN_0805fd14`: four stereo pairs), `io[0xb]` is the number of frames in the block.
  It carries no clock.
- The modules' context is computed inside: `engine + 0x128e0` (pool `0x08053F84`). That is what the module block
  methods receive as their second argument — the recorder (object at `engine + 0x28d8c`, block method at vtable
  `+0xc`, `0x0806201C`) among them.

## The clock is the engine object

Early in the tick, `FUN_080696d8(engine, io[0xb])` advances it:

- `+0x00` int64 sample counter, plus the block's frames (the low word is what `duck_block` reads as `now`);
- `+0x2c` a block counter, plus one;
- while `+0x38` (playing) is set, `+0x30` int64 position in ticks is recomputed from the sample counter through the
  tempo state at `+0x08` (`FUN_0804d708`); `+0x18` is the float BPM.

Later in the same tick, before the recorder's block method runs, the tick calls `fw_position 0x08069C38` **with
`engine` as the clock** and caches the result at `engine + 0x28d78` (int64 ticks).

The recorder takes `bufs[0]` as its clock (`0x0806202A`) and hands it to `fw_position` (`0x0806283A`) and to its start
routine `0x08061c94`, reading the same `+0x18` / `+0x30` / `+0x38` fields `src/preroll.c` documents — so `bufs[0]`
is the engine, by every field it is used for. The store that sets it was not found; nothing below depends on it.

## What it means for the Clip Window

- `clipwin_tick` (plan, engine step 2) takes **`engine`** from `duck_block`, not its `a`: `fw_position(out, engine)`
  for ticks, `engine + 0x18` for BPM, `engine + 0x00` for samples.
- `duck_block` runs **before** the tick's advance, so what it reads is the clock one block (`io[0xb]` frames) behind
  what the modules see in the same tick, and `engine + 0x28d78` there still holds the previous tick's position.
  `cw_target` must add one block, or the A2 harness must show that stock's Sync maths reads the clock at the same
  point. A2 settles which, on the real class-B process.

## How this was checked

Ghidra 12.1.4 headless on dev37 (project outside the repo, `GHIDRA_PROJ=/srv/dev/firmware/ghidra`), decompiling
`FUN_08053164`, `FUN_080696d8`, `FUN_08069c38` and the engine constructor `FUN_080512a4`; the recorder's block method
(which Ghidra does not make a function) read with `disasm.py`.
