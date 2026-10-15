# X1 — the recorder's arm path, what a recording sets on its pad, the Pad Record notes

Stock 3.1.9. Found 2026-10-15 (blackbox#t-003, step X1), revised the same day after verification (see
"Verification"). For P5: the "Save to slot" gesture and the capture shortcuts S-B1/S-B2/S-B3. Builds on
`src/preroll.c` (the recorder's start routine and fields), A4 (the engine object is the clock) and A6 (the order of
one audio block). Scratch scripts: `/srv/dev/firmware/re-scratch/x1/` and `x1/r2/` (the re-checks), outside git.

## Answers in short

1. **Arming a recording from code is one app call: `FUN_0809F2E8(app, padref)`**, exactly what MIDI notes 68+N
   and 103 run. It selects the target pad, opens the Record screen (screen 4), whose entry arms the **selected** pad,
   and queues a REC press (REC + PLAY when the transport is stopped). The settings are not arguments: the arm reads
   Length, Rec Quant, Rec Input, RecThresh, Threshold and Mon Output from the **global settings store**
   (RecConfig = Global) or from the **pad's own store** (RecConfig = Per Pad), and pushes them to the recorder.
   RecToPlay is global only. So code writes the values into the right store first, then makes the call. The pad must
   be empty and nothing may be recording. The Record screen has to be up from the call until writing starts (0x26);
   see "Constraints".
2. **S-B3 — what stock sets.** When writing starts (recorder message 0x26), an empty pad becomes a sample pad.
   If the take is quantized (Rec Quant not None, RecThresh Off), its mode becomes **Clip** with Clip's own defaults:
   **Loop Mode On, Launch Mode Toggle, Quant Size 1 bar, Sync 1/16, Beat Count Auto**. With RecToPlay On, Quant Size
   is then set **to the Rec Quant value**. When the take ends (0x29), **Beat Count** is set to the take's length in
   beats: the length rounded to the nearest whole number of Rec Quant units (a tie rounds up), then divided by one
   beat, truncating. The beat count is also handed to the WAV writer. Stock does **not** match Sync to anything: it
   stays 1/16. **Pad Length `0x90` ends up 0** on a pad that was empty-class at 0x26, and stale on a cleared pad.
3. **The Global-In note handler** runs in the audio task, inside the session object's block method (function entry
   **`0x0804FE18`**). With Pad Record on, notes 68–83, 84–99 and 100–104 on the Global In channel become app messages
   0x2B, 0x2C and 0x2D. "Record" on a loaded pad only selects the pad and shows the Pads screen; nothing is armed.
   "Clear" stops the pad and forgets the file but **leaves every pad parameter in place**. A loaded pad can be
   re-recorded in one press by clearing it and then recording, or through stock's own Pad Mode "New Rec". Both keep
   the parameters.

## The parameter ids

Registered by `FUN_0808C158` (run whole under Unicorn, as A0 did). "Store" says where the app keeps the value the
recorder is given. The recorder field is where its engine object holds the value after a 0x39 param message (the
recorder's 0x39 table at `0x080621F8`).

| id | label | xml | values | store | recorder field |
|---|---|---|---|---|---|
| `0x97` | `Length:` | `recpresetlen` | Custom, 1/4, 1/2, 1 bar, 2, 4, 8, 16, 32, 64, 128 bars (beats table `0x080EC770`: 0,1,2,4,8,…,512) | per RecConfig | `+0x40` int64 ticks = round(beats×960) |
| `0x98` | `Rec Quant:` | `recquant` | 8 bars, 4, 2, 1 bar, 1/2, 1/4, 1/8, 1/16, None (beats `0x080EC728`: 32…0.25, 0) | per RecConfig | `+0x38` int64 ticks |
| `0x9a` | `Rec Input:` | `recinput` | L+R, Left, Right, **Resam = 3** (`0x9b` is the Multi page's 3-entry alias) | per RecConfig | `+0x58` |
| `0xcf` | `RecThresh:` | `recusethres` | Off/On | per RecConfig | `+0x60` |
| `0xce` | `Threshold:` | `recthresh` | −96…0 dB (milli-dB) | per RecConfig | `+0x5c` |
| `0xdc` | `Mon Output:` | `recmonoutbus` | Out1 … Out3R | per RecConfig | `+0x68` |
| `0x9d` | `RecToPlay:` | `recautoplay` | Off/On (default On) | global only | `+0x4b` |
| `0x99` | `Rec Mon:` | `recmonmode` | On, Auto, Off (default Auto) | global only | `+0x59` |
| `0xd8` | `Gain:` | `ingain` | −96…+20 dB | global only | `+0x64` (linear float) |
| `0xe1` | `RecConfig:` | `recparmsperpad` | Global, Per Pad (default Global) | global | — (app only) |
| `0xd5` | `Lead In:` | `reccountdown` | Off/On (default On) | global | engine `+0x28D80` |
| `0xe2` | `Pad Record:` | `midikeyrec` | Off/On (default Off) | global | session object `+0x345` |
| `0x9c` | `Rec Active:` | `recactive` | — (never shown) | — | `+0x5a`: input monitoring under Rec Mon Auto, and lets a `0x28` message start an unarmed recorder. **It does not gate recording.** |
| `0x76` | `Global In:` | `midiglobchan` | None, Ch 1…16, Omni | global | — |

The defaults (above, in brackets) come from the global-settings defaults `FUN_0809481C`: Length Custom, Rec Quant
1 bar, Rec Input L+R, RecThresh Off. The class-3 and class-0x4C pad defaults (`FUN_08093F20`) add the six per-pad
values too, with the same defaults.
The six per-pad ids are the u16 list at **`0x080EEC80`**: `0x97, 0x98, 0x9a, 0xcf, 0xce, 0xdc`. The 1x Record page
is the list at `0x080EEB80` (Rec Input, Gain, RecToPlay, Length, Rec Quant, Rec Mon, Mon Output, RecThresh;
Threshold is on the next page). Tools > Rec is `0x080EED60` (RecToPlay, RecConfig, Lead In; JOEBOX adds Pre-roll
`0x1b1`), and Tools > MIDI is `0x080EEDA8` (Global In, Pad Record, …).

Two internal ids carry the arm itself, both to engine cell `0x400`: **`0xc5` = armed (1/0)** and **`0xc6` = target
cell** (`row<<8 | col`). `0xc7` is the WAV writer handle (recorder `+0x50`; `0xc6` lands at recorder `+0x54`).
`0x10b` = Multi on; `0xe0` = the selected pad, posted by every pad select.

## The chain, end to end

Engine cell ids are `row<<8 | col`. App pad refs are 8 bytes, `{u32 0x080EAF38, u16 row<<4 | col}`. The app object
is `APP = 0x24020088`, and the audio interface is `0x2400A9C0` (`+0x9A74` → engine). Within the engine, `ctx` =
engine + `0x128E0`. `set_screen` is `FUN_0809EAEC(app, screen, …)`; the selected pad's ref is `app+0x10`.

1. **Record request** — `FUN_0809F2E8(app, ref)`. If the current screen (`app+0x8CA4`) is already 4, it first calls
   `set_screen(app, 2)`, which disarms whatever pad was armed (below). Then it selects the target (`FUN_080978E4`:
   `app+0x14` = cell, posts `0xe0`). If the target's file name (store `+0x18`) is empty (`FUN_08046070`), it calls
   `set_screen(app, 4)` and posts UI message `0x60` to `app+0xC38`. If the pad is loaded, it calls
   `set_screen(app, 2)` and stops there.
2. **Arm** — `set_screen(…, 4)` calls **`FUN_0809B168(app, app+0x10)`** (`tbh` at `0x0809EB02`, indexed by
   screen − 1; the call is at `0x0809EC9C`). The arm works on the **selected** pad, not on a ref passed anywhere. For
   an empty pad it:
   - stops and releases the cell first if its record already has `+0xb` or `+9`;
   - posts `0xc5 = 1` to cell 0x400;
   - picks the store: global (`APP+0x8C90`, read with the global ref u16 `0x40`) if RecConfig = Global, else the pad's;
   - posts the six per-pad ids to cell 0x400 (the recorder) **and** to the pad's own cell;
   - creates the WAV writer (`FUN_0804C40C`): stereo if Rec Input is L+R or Resam, mono if Left or Right;
   - posts `0xc6` (the target cell) and `0xc7` (the writer handle) to 0x400, and sets the pad's file name to the new
     file;
   - resets the pad's engine cell (message 0x40), pushes the whole pad to the engine and sets the pad's cell record
     `+9` (armed).

   The only other caller is `SetCellParam`'s Rec Input branch (`0x0809FD5C`), which re-arms when Rec Input switches
   between mono and stereo while armed.
3. **Disarm** — `set_screen` to **any screen other than 4** runs `FUN_0809EA20(app, app+0x10)` on the selected pad.
   It acts only when the cell record's `+9` (armed) is set: it stops and releases the cell, clears `+9/+0xa/+0xb/+0xc`,
   deletes the new file, empties the name and posts `0xc5 = 0`. `+9` is cleared at 0x26, so after writing has
   started a screen change no longer disarms.
4. **Rec Active** — the Record view `FUN_080BF174` posts `0x9c = 1` (to the global ref and to the pad) when it
   activates (its message 0xd4) and `0x9c = 0` on 0xd3 (deactivation). Both go through the view's generic `0x6e` →
   `SetCellParam`. In the recorder this only switches input monitoring (A6) and the `0x28` start path; it does not
   decide whether samples are written.
5. **REC** — the main loop's handling of UI `0x60` (`0x080A2D48`…`0x080A2D6C`) calls
   `FUN_0804C8B4(iface, rec=1, stop=0, play=!playing)`. That posts engine messages `0x73(1)`, then `0x74` when the
   transport is stopped, then `0x73(0)`: REC down, PLAY, REC up. STOP is `0x75`.
6. **Engine** — `FUN_080520EC`. The `0x73(1)` handler sets the REC-held flag engine `+0x128D4`. With the clock running
   (`+0x38`) it toggles engine `+0x143`: when `+0x143` and `+0x144` are both 0 it sends **`0x60`** (rec on) to 0x400
   and `0x66` (`+0xc = 1`) to the app list; otherwise `0x61` (rec off) and `0x66(0)`. PLAY (`FUN_08051EB8`) with REC
   held sends `0x60` too and starts the clock at 0, or at **−3840 ticks** with Lead In.
7. **Session object** — the engine object whose block method is `0x08050464` (first module of the root chain; it
   also holds the MIDI note handler). It keeps `0xc5` at `+0x2A4` and `0xc6` at `+0x2A8` (its 0x39 table at
   `0x08050844`). On `0x60` while armed it sends **`0x25` to queue 0x400 with `+8` = the target cell** and sets state
   `+0x2A6 = 2`. On `0x61`, or on `0xc5 = 0` while in state 2, it sends `0x27` (stop). When `+0x2A5` is set (writer
   not found; meaning not traced) 0x60/0x61 take another path instead (`0x77`/`0x78`, state 3). The app also gets
   `0x6a` at arm.
8. **Recorder** — vtable `0x080D07AC`, block method `0x0806201C`, type table `0x08062084`. **`0x25` calls the start
   routine `0x08061C94` with no check at all** (`0x08062104`), giving start = the clock rounded up to Rec Quant and
   stop = start + Length (`src/preroll.c`). Rec Active plays no part: the take is written, and 0x26/0x29 and the
   RecToPlay note-on are sent, with `+0x5a` 0, 1 or never set. At the first written block it sends **`0x26` with
   `+8` = the target cell**. At the end it sends **`0x29`** (same `+8`). The first write lands one block after the
   block holding the start sample, from the start frame, as `test_preroll.py` documents for Resam; with Resam, 0x26
   and 0x29 also come one block later than with the jack inputs (observed: block 6 vs 5, 486 vs 485).
9. **RecToPlay** — when Length is set and RecToPlay is on (`+0x4c`), the recorder sends a **type-2 message (a
   note-on into a cell) to the target cell in the block where `stop` falls**, through `FUN_0805F32C`. Its `+4` is
   the frame of the stop sample within that block. Type 2 is the same message the note handler forwards to pads that
   have their own MIDI channel (`0x0804FE8A`). The pad reads it **in the same tick** (see "Messages inside one tick").
10. **App on 0x26** → `FUN_0809D418`; **app on 0x29** → `0x0809F4B4`. These are dispatched from the main loop
   `FUN_080A2258` through its jump table at `0x080A24C0` (base 0x1d), alongside `0x66` → `0x0809AC60` and
   `0x2B/0x2C/0x2D` (the notes, below).

The app's REC flags live in `0x0809AC60` (engine message `0x66`). `app+0x8CC0` = REC on. `app+0x8CC1` = 2 (a pad
recording) **only if the current screen is 4** when the app handles that 0x66 (`cmp r3, #4` at `0x0809AC7C`); on any
other screen it is 1 and REC starts **sequence recording** (`FUN_08098288`, sequence param `0xbe = 1`). With REC on,
screen 4 and the selected pad armed, the cell record gets `+0xa = 1`. With REC off: `+0xc = 1` (stop asked) if
8CC1 was 2, `FUN_08097D78` if it was 1, then `app+0x8CC1 = 0`.

Pad cell record (`APP + 0x8A88 + row*0x78 + col*0x18`, `FUN_0809A778`, as `src/insert.c` / `src/solo.c` use for
`+0xd` muted; refs outside rows 0–3 / cols 0–4 map to `APP+0x8D28`):

| offset | meaning |
|---|---|
| `+0x0` | writer handle (0xffff none) |
| `+0x4` | 0xffff when idle |
| `+0x8` | playing |
| `+0x9` | armed (Record screen up, waiting for REC or for the quantized start); cleared at 0x26 |
| `+0xa` | REC pressed, waiting for the quantized start |
| `+0xb` | recording (set at 0x26) |
| `+0xc` | stop asked |
| `+0xd` | muted (app mirror) |

## Messages inside one tick

Checked by running the stock tick `FUN_08053164` on the engine A6's harness builds.

- **Order** (by execution): the root chain (`0x080531DA`) runs the session object, then the recorder, then the
  pads; then the clock advance `FUN_080696D8` (`0x080531E0`); then the **drain** of the per-tick list at
  `ctx + 0x15238` into the app ring (`0x080531FC`…`0x08053414`); then the rest of the block, including the DJ FX
  manager; and last, at `0x08053B6A`, `FUN_0805F3B8`, which zeroes every per-module queue count (`ctx+4`, stride
  `0x604`, up to `ctx+0x150E4`) and the `ctx+0x15238` list's count (`+0x600`).
- **Per-module queues.** A module finds its queue with `FUN_0805F2C8(ctx, its cell)` (0x400 → `ctx+4`, 0x401 →
  `ctx+0x608`, a pad cell → `ctx + 4 + 0x604 × (row + 4×(col + 4×seq) + 2)`) and reads all of it at the top of its
  block method. `FUN_0805F32C` / `FUN_0805F460` append to the target's queue. So a message sent to a module later in
  the chain is handled **in the same tick**, and one sent to a module that has already run is wiped at the end of
  the tick. The recorder's RecToPlay note-on reaches the pad in the same tick: a planted type-2 entry in cell
  0x102's queue at the recorder's stage was read by both pad modules of 0x102 in that tick.
- **The app list `ctx + 0x15238`** (64 × 0x18 bytes, count at `+0x600`, appended with `FUN_0804F504`, which **drops
  silently** when 64 are pending). An entry appended **before the tick** (in `duck_block`, before it chains to the
  stock tick at `0x0804CE74`) or **by a root-chain module** is drained into the app ring in that same tick. An entry
  appended **after the drain** (the DJ FX stage, the master chain) is wiped by `FUN_0805F3B8` and never delivered.
- **The app ring** at engine `+0xE9F0` (64 × 0x18, tail `+0xEFF0`, head `+0xEFF4`). The drain dispatches on the type
  (table `0x0805322C`, type − 0x15). 0x26 and 0x2B–0x2D take the copy path at `0x0805336C`, which drops a new entry
  when an **identical 24-byte entry** is still pending, comparing from head−1 back to tail+1 (the oldest pending
  entry is not compared, and nothing is compared while at most one is pending). Run: five appends 0x2B(5), 0x2B(5),
  0x2B(5), 0x2B(9), 0x2B(5) in one tick gave three ring entries 5, 5, 9.
- **The app → engine ring** at engine `+0xD7E0` (64 × 0x18, head `+0xDDE4`, tail `+0xDDE0`) is what `FUN_0804C59C`
  (a 0x39 param post) fills, through `FUN_08051738`. After writing, `FUN_08051738` spins on `FUN_08077958(1)` (a
  busy-wait on the millisecond tick, not a yield) while 33 or more entries are pending. The ring is drained at the
  top of the tick (`0x08053186` / `0x08053C46`). It is a single-producer ring with no lock. **Call
  `FUN_0804C59C` from the GUI task only**; from the audio task a full ring would spin forever (inferred: its consumer
  is the same task) and a concurrent GUI post could clobber the slot.

## Constraints for arming from code (the Save gesture, S-B1)

- **Target pad empty.** Empty means a blank file name only. A cleared pad keeps class 3 and still counts as empty.
- **Nothing recording.** If `app+0x8CC1 ≠ 0` and the target pad is not itself recording, `FUN_0809F2E8` does nothing
  at all, not even the select. If the target is the pad that is recording or waiting (`+0xb` or `+0xa`,
  `FUN_0809AC48`), the call is a **stop**: one REC press (`FUN_0804C8B4(iface, 1, 0, 0)`), then `+0xc = 1`. A second
  call with `+0xc` set does nothing.
- **Side effects of the call itself.** If the Record screen is already up, the call leaves it first, which disarms
  the pad armed there. On a loaded pad it selects the pad and jumps to the Pads screen. A Save should test the empty
  name and `app+0x8CC1` itself before calling.
- **The Record screen, and for how long.** Rec Active does not gate the take, so the screen is needed for three
  other reasons, all stock:
  1. the arm `FUN_0809B168` runs on entry to screen 4 (or must be called directly on the selected pad);
  2. `0x0809AC60` makes REC a pad recording only if screen 4 is up when the engine's 0x66 arrives; otherwise REC
     starts sequence recording;
  3. any screen change before 0x26 runs the disarm, which aborts the take and deletes the file.

  After 0x26 (`+9` cleared), leaving the Record screen only posts Rec Active 0 (input monitoring off). The Record
  view's other deactivation action, a `0x61` sent up its parent chain (`FUN_080AED14`), happens only when its `+0xa24`
  is set. That flag is set by view message `0x155` and cleared by `0x157`, and the only senders of those are the
  Multi auto-sampler's start (`FUN_080931F4`/`FUN_080931FA`, which read Start Note, End Note, Sample Every, Vel Layers
  and post Note Length / Release Len) and stop (`FUN_08093304`). So for a 1x take it is not sent. The 0x29 handler
  returns to Pads (screen 2) only if screen 4 is still up; it never returns to the originating screen. **Inferred, not
  run end to end:** a Save from the XY page can show the Record screen from the call until 0x26 (at most one Rec
  Quant unit plus a block), then go back to the XY page. Avoiding the hop entirely would mean calling `FUN_0809B168`
  on the selected pad directly and patching the screen compare at `0x0809AC7C`, and the screen changes that the app
  makes on its own would still disarm before 0x26.
- **Settings.** Write them into the store the arm will read: `APP+0x8C90` if RecConfig (`0xe1`) is 0, else the pad
  store `APP+0x1840+row*0xF0+col*0x30`. Two ways:
  - `fw_store_set 0x08093ECC`: in memory, not saved, **sets only ids already in the store** (it never adds one);
  - `SetCellParam 0x0809FA50` with the **global ref** (u16 `0x40`; `0x140` is accepted too). It writes
    `APP+0x8C90` through `fw_store_set`. When the id is in that store, it also calls
    `FUN_08090CBC(0x2401F508, "settings.tml", store)`, which queues a save job for a worker (16-slot ring, de-duplicated).
    It then posts `(iface, 0x400, id, value, 0, 0)` and does not mark the preset dirty. GUI task only. Do not pass
    the global ref to `FUN_08098D0C` (it maps any ref outside the pad grid to `APP+0x8CF8`); `FUN_08099504` and
    `SetCellParam` special-case it.

  Values: `0x98 = 3` (1 bar); `0x97` = 3/4/5/6 for 1/2/4/8 bars; `0x9a = 3` (Resam); `0xcf = 0`.

  The **0x26 and 0x29 handlers read Rec Quant and RecThresh from the same store again**, to decide Clip mode and
  Beat Count. Overriding only the recorder with direct 0x39 posts would give a correct take and a wrong pad.
  **RecToPlay `0x9d` is global and is not pushed at arm**: set it through `SetCellParam` on the global ref, or
  store-set it **and** post it (`FUN_0804C59C(iface, 0x400, 0x9d, 1, 0, 0)`). JOEBOX Pre-roll `0x1b1` must be Off;
  `preroll_start` reads it live. Lead In only matters when the transport is stopped.
- **A custom arm** (anything that skips `FUN_0809B168`) must still set the cell record's `+9` the way it does: the
  0x26 handler does nothing unless the ref is not `0x40` and `+9` is set, and the 0x29 handler does nothing but set
  the dirty flag `app+0x8CC4` unless `+0xb` is set.
- **New Rec arms the selected pad.** `SetCellParam(app, ref, 0x8b, 4)` clears and converts `ref` but then calls
  `set_screen(4)`, which arms `app+0x10`. Select the target first with `FUN_080978E4(APP, ref)`. Otherwise it arms
  whatever pad is selected, which does nothing if that pad is loaded.
- **Timing with the transport running.** REC → 0x60 → 0x25 in the next blocks. The take starts at the **next** Rec
  Quant boundary after that (1 bar: the next bar line), so a Save never captures the bar that is playing. Gate 5's
  "catch → Save" therefore records the looper's output from the next bar on.
- **Where to call it from.** `FUN_0809F2E8`, `set_screen` and `SetCellParam` belong to the GUI task (the main loop
  runs them for MIDI and for the UI). Stock `SetCellParam` also calls `set_screen(4/5)` itself (Pad Mode New Rec,
  Rec Type `0x109`), so a Save row handled in a `SetCellParam` intercept may call `FUN_0809F2E8` too (inferred from
  that precedent, not run). From the audio task, the MIDI-equal route is to append `{0x2B, +8 = pad index 0..15}` to
  `ctx + 0x15238` with `FUN_0804F504`. It is delivered **only if appended before the drain**: in `duck_block` before
  it chains to the stock tick, or from a root-chain module. **A post from the DJ FX slot (the Looper FX) is lost**;
  set a flag there and append it in the next tick's `duck_block`. A repeat of the same entry may be dropped while an
  identical one is pending.

## S-B3 — what stock sets on the new pad

**At 0x26** (`FUN_0809D418`; nothing happens unless the ref is not `0x40` and the cell record's `+9` is set). Only if
the pad's class (store `+8`, read through vtable slot 0) is **0x4C**, the empty-pad class, the pad becomes class 3, a
loaded sample pad, in one of two ways:

- **Untouched empty pad (Default Template `0xdf` = 1, the 0x4C default):** the store is rebuilt from class-3
  defaults. Pad Mode is **Clip** if Rec Quant ≠ None and RecThresh is Off, otherwise **Sample**. Then the mode
  defaults `FUN_0809AA94` apply (below).
- **Customised template (`0xdf` = 0):** the parameters are carried over through `FUN_0809D308`, which copies the
  store, rebuilds it as class 3 and sets back every id the new class has. Pad Mode is set to Clip plus the mode
  defaults **only if it is not Clip already** and the take is quantized. `SetCellParam` clears `0xdf` whenever a
  value that is in an empty pad's store changes.
- In both cases the pad's **Output `0x95` := Mon Output**, and the store's file length `+0x20/+0x24` is **zeroed**
  before the mode defaults run.

Then, for any class, if **RecToPlay** (global) is on, the pad is Clip and the take is quantized: **Quant Size `0x47`
:= the Rec Quant index**, posted to the engine. The two 9-entry lists are identical (beats `0x080ECAE4` /
`0x080EC728`). Finally the cell record goes from armed to recording (`+0xb = 1`, `+9 = +0xa = 0`).

`FUN_0809AA94`, the mode defaults: Clip sets Start 0, **Length `0x90` = store `+0x20`**, **Quant Size 3 (1 bar),
Sync 5 (1/16), Launch 2 (Toggle), Loop Mode 1 (On), Beat Count 0 (Auto)**. Sample/Granular set Launch Trigger, Loop
None and start/end over the whole file (`+0x20`). Slicer sets Quant None, Sync None, Launch Trigger, Loop Off.

**Pad Length after a recording.** Because `+0x20` is zeroed first, an untouched or template pad comes out of 0x26
with **`0x90 = 0`** (class 0x4C has no `0x90`; a template already in Clip gets the class-3 default, also 0). The 0x29
handler writes only `0xd2`, so nothing refreshes `0x90` or `+0x20` before the preset is reloaded. A **cleared** pad
(class 3, S-B2 clear + record) keeps the **old file's** `0x90` and `+0x20`. Class B does not take the length from
`0x90` (the value only triggers its recompute `FUN_08064A94`), but app-side readers (the waveform view, a Region
"File" mode) would see 0 or a stale length.

**At 0x29** (`0x0809F4B4`; if the ref is `0x40` it returns, and if the cell record's `+0xb` is not set it only sets
the dirty flag). When Rec Quant ≠ None and RecThresh is Off (read from the RecConfig store):

- The take's length in samples is converted to ticks at the current BPM (`FUN_0804C500`: samples/48000 × BPM/60 ×
  960, rounded).
- **Beat Count `0xd2` := round(ticks / quant) × quant / 960**: the nearer multiple, **a tie rounds up**, then the
  division by 960 **truncates**. It is an explicit count, not Auto. A sub-beat Rec Quant therefore gives an inexact
  whole-beat count (5 sixteenths → 1). At 1 bar: 9599 ticks → 8 beats, 9600 (2.5 bars) → 12.
- The info block at `*(app+0xE984)` gets `+4` = beats and `+0x21C` = 1 and is handed to the writer as it closes the
  file (`FUN_0804C498`). That is where "beat count embedded in the WAV" comes from; the chunk format was not examined.
- The whole pad is pushed to the engine (`FUN_08099200`).

Always: the file is closed, `0xc5 = 0`, the cell record flags are cleared, the preset is marked dirty, and Pads is
shown if screen 4 is still up.

Results of `FUN_0809D418` run on the stock image (pad mode / loop / launch / quant / sync / beats / output):

| case | result |
|---|---|
| untouched, Rec Quant 1 bar, RecToPlay On | Clip / On / Toggle / 1 bar / 1/16 / Auto / Mon Output |
| untouched, Rec Quant 4 bars, RecToPlay On | same, Quant Size **4 bars** |
| untouched, Rec Quant 4 bars, RecToPlay Off | same, Quant Size 1 bar |
| untouched, Rec Quant None, or RecThresh On | Sample / Off / Trigger |
| template (`0xdf`=0) in Sample mode, Gate, Sync 1/4, Rec Quant 2 bars | Clip **defaults** (Toggle, 1/16, Auto), Quant 2 bars |
| template already Clip, Loop Off, Gate, Sync 1/4, Beats 8 | all kept, Quant Size := 2 bars |
| cleared class-3 pad, any mode | untouched except Quant Size if Clip + RecToPlay |

**Our own pad ids follow JOEBOX's.** The same run on the JOEBOX full-set image uses LFO 2/3 (`0x1a9…`) as stand-ins;
JOEBOX adds them through `lfo_defaults` at the tails of the class-3 (`0x0809423C`) and class-0x4C (`0x080943B4`)
defaults:

- an untouched pad comes back with JOEBOX's defaults;
- a template or a cleared pad keeps its values.

On the stock image, ids that are not in the class-3 defaults are dropped by the 0x4C → 3 conversion. So the Clip
Window ids must be added at that same tail (`insert_defaults`, as the plan has it). Even then, **Loop Len / Slip
copied before arming are lost on an untouched empty pad**, unless writing them first makes it a template
(`0xdf` = 0). The robust order for Save is to write them **after 0x26**, or after 0x29 together with Beat Count, and
to write the take's length into `0x90` (and `+0x20` if an app-side reader needs it) at the same time.

## The Global-In note handler (Pad Record)

**Engine side, audio task:** entry **`0x0804FE18`**, called from the session block method at `0x08050B5C` with
`(session, event, ctx)`. The entry loads `r3 = session+0x344` (the Global-In-changed flag) and, when it is set,
rebuilds the channel-role table at `session+0x334` with `FUN_0804FC9C` before running the body at `0x0804FE1C`.

- `event+8` = channel, `+0xc` = note, `+0x10` = velocity. Note 0 returns.
- The note is forwarded as type 2 (`0x0804FE8A`) to every pad whose own MIDI In channel matches (entries at `+0x24`,
  stride `0xc`, 20 of them). After a Pad Record post, execution goes on into the per-pad note loop
  (`0x08050042` → `0x0804FFC6`) with a local flag cleared; what that loop does with notes 68–104 was not traced.
- If the channel's role byte at `session + 0x334 + ch` is 2 (Global In, ch ≤ 15) **and Pad Record (`+0x345`) is
  on**:
  - notes **68–83** → app message **`0x2B`, `+8` = note − 68**;
  - **84–99** → **`0x2C`, `+8` = note − 84**;
  - **100–104** → **`0x2D`, `+8` = the note**.

  `+4` = event `+4`. They are appended to `ctx + 0x15238` with `FUN_0804F504`, and the drain later in the same tick
  copies them into the app ring at engine `+0xE9F0`.
- With Pad Record off, 68–104 do nothing. Notes 36–51 still play pads and 52–67 still send sequences (`0x63`).
  PocketRave's `HOOK_B 0x0805004C` sits inside this function.

**App side**, all from the main loop:

| message | handler | effect |
|---|---|---|
| `0x2B` | `0x0809F3A0` | `FUN_0809F2E8(app, 0x2402EE60 + 8*N)` — "record pad N" |
| `0x2C` | `0x0809F3B4` | ignored while `app+0x8CC1 ≠ 0`; else select pad N, `FUN_0809E970(app, app+0x10)` (clear the selected pad), Pads screen |
| `0x2D` 100/101 | `FUN_0809F3EC` | select previous / next (`FUN_08097C7C` ±1, wraps over 16), Pads screen |
| `0x2D` 102 | | post `0x42` (pad trigger, `FUN_0804C61C`) for the selected pad |
| `0x2D` 103 | | `FUN_0809F2E8(app, app+0x10)` — **the only action still taken while recording** (it is the stop) |
| `0x2D` 104 | | clear the selected pad, Pads screen |

Pad index N → the 16 refs that `0x080A2DC0` builds at **`0x2402EE60`** (8 bytes each): cell `(N/4)<<4 | N%4`, i.e.
row N/4, column N%4. The manual calls index 0 "bottom left"; which store row the screen draws at the bottom was not
checked.

**How "record" refuses a loaded pad.** The empty test is the blank file name. A loaded pad is selected and the
Pads screen comes up; there is no message, arm or REC. While another pad records, the press is ignored entirely.

**What clearing does** (`FUN_0809E970`, run): if the pad is playing, it sends note-off `0x43` and releases the
engine's file streams for the cell (`FUN_0804C3A8`). It drops the pad's linked-file records (`FUN_0809DF18`: the
0x28-byte records from `APP+0x3088`, matched by their own `0xe8`/`0xe9` = row/col) and **empties the file name**.
The cell record is reset (`+0`/`+4` = 0xffff, all flags 0, `+0xd` muted mirror 0) and the preset is marked dirty.
**The store is untouched**: same class (3), every parameter, a stale file length at `+0x20` and in `0x90`. Our Clip
Window values would survive a clear.

## S-B2 — record over a loaded pad

Two stock routes, both run under Unicorn, both keep the pad's parameters:

- **Clear then record** — `FUN_0809E970` then `FUN_0809F2E8`, the MIDI 84+N, 68+N sequence. The pad stays class 3,
  so at 0x26 nothing changes except Quant Size (Clip + RecToPlay). At 0x29 Beat Count is set. A Sample-mode pad stays
  Sample. `0x90` and `+0x20` keep the old file's length.
- **Pad Mode → "New Rec"** — `SetCellParam(app, ref, 0x8b, 4)`. It clears `ref`, converts it to class 0x4C with its
  parameters (`FUN_0809D308`, which zeroes `+0x20`), sets `0xdf = 0` and calls `set_screen(4)`, which arms **the
  selected pad**. From the UI the pad being edited is the selected one; from code, select `ref` first. Run on a Clip
  pad (Loop Off, Gate, Sync 1/4, Beats 8): after New Rec the pad mode is still Clip; at 0x26 everything is kept,
  Quant Size := Rec Quant and `0x90` = 0. A non-Clip pad would get the Clip defaults if quantized. Output := Mon
  Output.

Either way **the old take stops at the press**. The pad is silent until RecToPlay starts the new take at its end:
for a Length of N bars, that is the wait for the next Rec Quant boundary plus N bars. That matters for "one-press
re-takes" (workflow c), not for a looper Save.

## Open points

1. **Where exactly the RecToPlay start lands.** Settled now: the pad handles the recorder's note-on in the **same
   tick** (root-chain order and per-module queues, run). Still inferred: what the class-B voice start then does with
   it. A1's launch rule (`0x080683AE`, run by A1) takes the next Quant multiple, or launches at once when the
   previous multiple is at most 0x180 samples behind the block's sample counter. The stop sample is a Rec Quant
   multiple inside this block and RecToPlay has just set Quant Size = Rec Quant, so the start should fall on the stop
   frame. Settle it by running the tick with a loaded Clip pad and the recorder at its stop block, or on hardware by
   recording a loop over a click.
2. **The WAV beat metadata** (`+4` / `+0x21C` of the 0x23C-byte info block, consumed by writer `0x080710AC`) was not
   decoded. It is not needed while Save goes through the stock recorder.
3. **The Save hop, end to end.** The bound above (Record screen from the call until 0x26) is from static reads of
   `set_screen`, `FUN_0809EA20`, `0x0809AC60`, the 0x26 handler and the Record view. Not run: a Save from the XY page
   that returns there right after 0x26. Gate 5 should say whether up to one Rec Quant unit on the Record screen is
   acceptable. A Save from a `SetCellParam` intercept was not run either; only the stock precedent supports it.
4. Recorder `+0x18` = 0x400 was assumed in the standalone recorder harness. It is consistent with every 0x39 the arm
   posts to 0x400 taking effect, but the constructor that stores it was not read.
5. Session `+0x2A5` (the 0x77/0x78 path) has no byte store by immediate offset in the image; the initialiser's
   halfword store at `0x0804F6FE` (`r4` = 0) clears `+0x2A4/+0x2A5` together. What sets it was not traced. It may be
   the Multi path; that is a guess, and it does not matter for a 1x Save unless something sets it.

## Verification

Independent verifiers re-checked fourteen claims. Thirteen held (one could not be checked). One was wrong, and they
found nine further points. Each disputed point was settled again for this revision:

| point | verdict | how it was settled here |
|---|---|---|
| X1-5 "nothing is written without Rec Active" | **wrong, corrected** | The original 20-block run ended about 336 blocks before the start bar line. Re-run 1340 blocks (`vx1/t5b.py`): identical with Rec Active never set / 0 / 1 (961 writes, 2 bars, 0x26 at 356, 0x29 at 1316, RecToPlay at 1315). Own run `r2/t_recactive.py`, start close to a bar: 27 cases (Rec Input L+R/Left/Resam × Rec Mon On/Auto/Off × Rec Active none/0/1), all write exactly one bar and send 0x26/0x29 and the note-on. Statically, type table `0x08062084`: 0x25 → `0x08062104`, a direct call to the start routine. The six `+0x5a` reads (`0x080620F4`, `0x080624C6`, `0x080629DA`, `0x08062ADA`, `0x08062B0E`, `0x08062DCC`) select monitoring or the `0x28` start of an unarmed recorder (`0x080623B8` → `0x080620F4`). |
| Record-screen hop reasons | rewritten | Static: `set_screen` case 4 is the only caller of the arm besides the Rec Input re-arm (`findbl`: `0x0809EC9C`, `0x0809FD5C`); `cmp r3, #4` at `0x0809AC7C`; every other screen runs `FUN_0809EA20`, which acts only on `+9`. |
| New Rec / `set_screen(4)` arm the selected pad | confirmed, added | Run `r2/t_newrec2.py` with the real `set_screen` and the arm stubbed: New Rec on ref 0x02 with pad 0x33 selected arms 0x33. |
| `FUN_0809F2E8` leaves screen 4 first | confirmed, added | Decompile and listing (`0x0809F308` → `0x0809F37C`, `set_screen(2)`, then the select). |
| `0x90` = 0 after a recording | confirmed, added | Run `r2/t_len.py`: untouched and template pads `0x90 = 0`, `+0x20 = 0` after 0x26 and after 0x29; cleared class-3 pads keep 96000 in both. New Rec then 0x26: `0x90 = 0`. Static: the only store write in `0x0809F4B4` is `0xd2` (`0x0809F72E`). |
| `FUN_0804C59C` spin, `FUN_0804F504` drop | confirmed, added | Decompiles of `FUN_08051738` (33-entry threshold), `FUN_08077958` (busy-wait), `FUN_0804F504` (cap 0x40); ring consumers found at `0x08053186` / `0x08053C46` in the tick. |
| Open point 2 (list delivery) | **settled by execution** | Run `r2/t_list.py` on A6's built engine with the stock tick: an entry placed before the tick or from the recorder stage reaches the app ring; one placed at `0x08053506` (after the drain) does not, in that tick or the next; the dedup case 5,5,5,9,5 → 5,5,9; stage order traced with hooks. Static: `FUN_0805F3B8` literals `0x150E4`, `0x151FC`, `0x15238`. |
| Note handler entry `0x0804FE18` | confirmed, corrected | Disassembly at `0x0804FE18` (the `+0x344` load), `0x0804FE2A` → `0x0804FF50` → `FUN_0804FC9C`; `findbl`: the only call is `0x08050B5C`. |
| 0x26 / 0x29 preconditions | confirmed, added | Run `r2/t_len.py`: 0x26 with `+9 = 0` changes nothing; 0x29 with `+0xb = 0` only sets `app+0x8CC4`. Listing of `0x0809F4B4` (`cmp r5, #0x40`, the `+0xb` test). |
| Beat Count rounding | confirmed, added | Run `r2/t_beats.py` on X1's harness and `vx1/t7.py` on the verifier's: 9599 → 8, 9600 → 12, 1/16 × 1250 or 1320 ticks → 1, 4 bars × 23040 → 32. |
| Record view 0xd3 sends 0x61 | confirmed, scoped | Decompile of `FUN_080BF174` (0x155 sets `+0xa24`, 0x157 clears it, 0xd3 sends 0x61 via `FUN_080AED14` only when set); senders of 0x155/0x157 found by constant search are the Multi auto-sampler's start and stop, identified by the ids they read (`0xfb`–`0x101`, labels from the registrar dump). |
| `SetCellParam` on the global ref | confirmed, added | Decompile: ref mask `0xfffffeff == 0x40`, write to `APP+0x8C90`, `FUN_08090CBC` with pool values `0x2401F508` / `"settings.tml"` read from the image, post to 0x400, no dirty flag. `fw_store_set` and `FUN_08098D0C` from their decompiles. |
| X1-14 RecToPlay timing | narrowed | The same-tick part is now run (`r2/t_route.py`); the voice-start part stays inferred (open point 1). |

## How this was checked

All by Unicorn on the **stock image** unless noted. Harness `x1/stock.py` maps the regions of the step brief, stubs
the allocator and any call it records, and uses param stores laid out as `FUN_08093E9C`/`ECC`/`EF6` read them, with
pads built by the real class defaults `FUN_08093F20`. Tick-level runs use A6's harness (`a6/harness.py`: the engine
constructor `FUN_080512A4` and graph builder `FUN_080525F0` run whole at the engine's real address).

| what | how |
|---|---|
| ids, labels, lists, xml names | `reg.py`: the registrar `FUN_0808C158` run whole, 267 registrations |
| arm `FUN_0809B168` | `t_arm.py`: the posts with RecConfig Global vs Per Pad, writer channels for Resam vs Left, `0xc5`/`0xc6`/`0xc7`, the armed flag, nothing on a loaded pad |
| record request `FUN_0809F2E8`, UI 0x60 → REC, `FUN_0804C8B4` | `t_record_note.py`: seven cases (empty, loaded, screen already 4, target recording/waiting/stop asked, another pad recording); the 0x60 branch of the main loop run as a slice (`0x080A2D4E`→`0x080A2D3E`) with the clock stopped and running; the message sequence for REC / REC+PLAY / STOP / PLAY |
| engine REC/PLAY, session object | `t_engine_rec.py`: `FUN_080520EC` with 0x73 (playing, stopped, already on), `FUN_08051EB8` with/without REC held and Lead In; block method `0x08050464` run until its queue is empty, with arm/REC/REC-again/disarm sequences |
| recorder | `t_recorder.py`, `t_recorder2.py`: block method `0x0806201C` (stubs as `test_preroll.py`) with 0x39 params then 0x25: the param-to-field map, 0x26/0x29 with `+8` = target, exactly 2 bars written, the type-2 RecToPlay message at frame 112 of the block holding the stop sample (start tick 1001), none with RecToPlay Off or Length Custom. `r2/t_recactive.py`: Rec Active has no effect on writing (27 cases) |
| S-B3 at 0x26 | `t_started.py`: ten cases; `t_started_joebox.py`: the same on the JOEBOX full-set image (`out/solo+…+cave/BLACKBOX.bin`); `r2/t_len.py`: `0x90`/`+0x20` through 0x26 and 0x29, preconditions |
| S-B3 at 0x29 | `t_done.py`: Beat Count for six lengths and quants, RecThresh, Per Pad, the info block given to the writer; `r2/t_beats.py`: ties and truncation |
| clear | `t_clear.py`: store before = after, name emptied, cell record reset |
| note handler and app handlers | `t_notes.py`: the handler for notes 36…105 with Pad Record on/off and on a non-Global channel (run from `0x0804FE1C` with `r3` = 0, i.e. the role table already built); `0x080A2DC0` builds the pad refs; `0x0809F3A0` / `0x0809F3B4` / `FUN_0809F3EC` for each note, idle and while recording |
| the screen-4 test | `t_recflag.py`: `0x0809AC60` on screens 4, 2, 0x25 |
| New Rec | `t_newrec.py`: `SetCellParam` with `0x8b = 4` on a loaded Clip pad, then `FUN_0809D418`; `r2/t_newrec2.py`: which pad the real `set_screen(4)` arms |
| tick: list, queues, order | `r2/t_list.py`, `r2/t_route.py` on A6's engine (above) |

Static only, each from two reads (Ghidra decompile, plus the instruction listing, a capstone disassembly or a decoded
table from the image bytes):

- the main loop's dispatch of 0x26 / 0x29 / 0x66 / 0x2B–0x2D (table `0x080A24C0`);
- `set_screen` index 3 → `FUN_0809B168`, and the disarm on every other screen;
- the recorder's type table `0x08062084` and its `+0x5a` reads;
- the Record view's Rec Active posts and its 0xd3 / 0x155 / 0x157 handling (`FUN_080BF174`);
- the app→engine routing of 0x25/0x27/… to queue 0x400 (`FUN_080520EC`, `FUN_0805F460`, `FUN_0805F2C8`), the
  app→engine ring (`FUN_08051738`), the tick's drain table `0x0805322C`;
- `SetCellParam`'s global-ref branch, `fw_store_set`, `FUN_08098D0C`, `FUN_08099504`.
