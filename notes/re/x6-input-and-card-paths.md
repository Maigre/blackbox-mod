# X6 — How input, the transport, a preset load and the card reach stock 3.1.9's app (blackbox#t-054, pass 1)

Stock 3.1.9 (`BLACKBOX-3.1.9.bin`), this fork at `maigre` `d23b389` (37.4.1 + Clip Window stage 3). Found 2026-11-12
for the bench kit: after one install of a dev build, a session on mgr-ran drives the unit with no hands. This note
answers six questions — (a) a knob turn, each button and a touch; (b) play and stop; (c) a preset load by name;
(d) stock's FatFs beyond `f_open` / `f_read` / `f_close`; (e) a clean reset; (f) endpoint 0 beyond 64 bytes — and
ends with the design of the kit's job mailbox (§9). Pass 2 builds it.

Marks: ✓ unit = read on the unit over the dev peek (37.4.1d, 12/11); ✓ injected = done once on the unit by raw
poke; *static* = a read of the decompile or the disassembly; *inferred* = what the code implies, not seen running;
*design* = a choice. Nothing here ran under Unicorn yet: `test_benchkit.py` (pass 2) is where the static claims get
run.

## 1. Short answers

| question | stock's path | the one injection that the app cannot tell from the real input |
|---|---|---|
| knob turn | ADC scan `FUN_08040724` (GUI task, inside the app pass at `0x080A2CD6`) → 64-entry ring at `0x24000DE0` → drained in the same pass into `FUN_080A1718`, case `0x32` → the views | one entry `{0x32, knob, counts}` appended to that ring by the GUI task right after the scan (the existing hook) |
| button (13) | GPIO scan `FUN_080437D4` (audio task, top of each block) → the same message into TWO rings of the panel object `0x240021BC`: one the GUI app pass reads, one the audio block reads | the same pair of entries appended by the audio task between blocks (`usbdev_poll`). **✓ injected**: TOOLS |
| touch | the touch controller on I2C `0xBA`, read by `FUN_08042548` (GUI loop) → tracker `FUN_0808B050` → hit test, then the widget's down / move / up virtuals (`+0x10` / `+0x14` / `+0x18`) | the tracker's three calls made by the GUI task for one contact of our own (§4) |
| play / stop | buttons 10 (PLAY, code `0xF7`) and 9 (STOP, `0xF6`) → audio block → `FUN_08051EB8` / `FUN_08052010` on the clock | a press of button 10 or 9, as above |
| preset load by name | PSET's **Load** button posts `0x18 {index}` → `FUN_080A1718` → LoadBank `FUN_0809E218` → command `0x22` to the card task | the GUI task finds the index of the name in the preset list and posts `0x18` to `FUN_080A1718`, as the button's view does at the top of its post |
| card files | FatFs R0.13-style with exFAT, tiny buffers, long names: write `0x08086A06`, lseek `0x08086D96`, sync `0x08086C28`, opendir / readdir / closedir `0x080870F6` / `0x080871A0` / `0x0808718C`, stat `0x0808724A`, unlink `0x0808748E`; `FIL` = `0x58` B | calls from the card task only (§6) |
| reset | **stock never resets itself in software**: only the window watchdog and power | `SYSRESETREQ` as `src/b2load.c` does, from the card task, guarded (§7) |
| endpoint 0 > 64 B | the core arms EP0 IN for at most 127 B (one 64-B packet in practice); `usbdev.c` sends one packet per audio block | the OTG interrupt re-arms EP0 IN on each packet's completion: a 4 096-B peek per request (§8) |

## 2. The three tasks and where each input arrives

The task table at `0x080CFBB0` (*static*, X2): `defaultTask` (the GUI, entry `0x08043DEC`), `audioTask` (priority 3,
entry `0x08043E64`), `pcmStreamer` (the card task, entry `0x08043E74`). One pass of the GUI loop `FUN_08043DEC`:
wait on the frame semaphore (`FUN_08041B70`, the LTDC interrupt gives it, A3), store the ms clock at `0x2402EEE0`,
read the touch panel into a 64-byte buffer on the loop's stack (`FUN_08042548`), call the UI object's vtable `+8`
= `FUN_0808B654`, draw. `FUN_0808B654` first feeds the touch buffer to the tracker (`bl FUN_0808B050` at
`0x0808B65E`), then runs the app pass `FUN_080A2258` (`0x0808B664`), then drains the UI ring at `app+0x30` to the
views. Inside the app pass, in this order (*static*): the panel ring the GUI reads (§3.2), the engine → app ring,
the loader → app ring, the preset manager → app ring (`FUN_080905D0`), **then the knob scan and its ring** (§3.1),
then the ring at `app+0xC38` (only `0x60` is acted on).

`app` is `0x24020088` throughout. The UI object is `*(0x24002E6C)` (on the unit `0xC3C59FF0`, ✓ unit: it is in
SDRAM, from stock's permanent allocator).

**Every view post that is passed on ends in the app handler, synchronously.** A widget posts with `fw_post`
`0x080AED14`, which walks the parent chain calling each parent's `vt+0x30` while it returns non-zero (A5). The Pads view (`gui+0x490`, vtable
`0x080F0E50`) has the container `gui+0x280` as its parent (✓ unit: its `+0x2C` = `0xC3C5A270` = `gui+0x280`). The
container's vtable is `0x080F073C` (✓ unit) and its `vt+0x30` is `0x080AB4A8`, which calls `FUN_080A1718(0x24020088,
msg)` and returns 0. Ghidra has no function there, which is why `FUN_080A1718` looked like it had only the knob ring
and `0x080A211E` as callers: it has three. So `usbdev.c`'s mailbox calling `FUN_080A1718` directly with `0x6E` is
exactly where a turned knob's `0x6E` arrives, and the same holds for any message a view posts.

## 3. Knobs and buttons

### 3.1 Knobs ✓ unit (structure), *static* (path)

A3 has the scan and the knob types; what the kit needs:

- **Hardware object** `hw` = `0x24000170` (built by `FUN_080405A0`): the ADC frame ring at `+0` (96 rows of 16
  channels), the knob event ring at `+0xC70` (64 entries × `0x18`), its read index `+0x1270` and write index
  `+0x1274`, a second 64-entry ring at `+0x1278` (indices `+0x1878` / `+0x187C`) that the audio block reads and
  `FUN_08045468` feeds (*static*; not an input this kit needs), the knob positions at `+0x18C0` (`0x24001A30`).
- **Producer and consumer are the same task.** `FUN_08040724(hw)` is called only from the app pass (`0x080A2CD6`, the
  site `usbdev_mailbox_scan` already replaces in dev builds). Right after it, the same pass copies each entry out
  (`0x080A2CE8`..`0x080A2D36`), advances the read index, and calls `FUN_080A1718(app, msg)`, whose case `0x32` pushes
  the message into the UI ring at `app+0x30` (`FUN_080B5758`); `FUN_0808B654` hands it to the current view in the
  same pass. Nothing else writes the ring (every writer of `+0x1274` was grepped in the listing and the decompile).
- **The message** (the ring entry, then the copy the app gets): `+0x00` u16 `0x32`; `+0x04` the tag `0x080CFBA4`
  (set once by the ring's constructor; no reader uses it); `+0x08` u16 0; `+0x0C` i32 the knob's code; `+0x10` i32
  this scan's delta in ADC LSB; `+0x14` 0. The views read the code and the delta as 16-bit signed (A3), so a delta
  stays inside ±32 767.
- **Knob codes**: the app's index, 0 = TL, 1 = BL, 2 = TR, 3 = BR (A3). The scan maps ADC wiper pairs (1, 3) (5, 7)
  (9, 11) (13, 14) (`0x080CFBEC`) to codes through one of two tables, chosen by `hw+0x19CE`: `0x080CFC0C` = (3, 1, 2,
  0) when 0, `0x080CFC14` = (0, 2, 1, 3) when 1. ✓ unit: `hw+0x19CE` = 1. An injection gives the app's code directly.
- **Gates**: the scan posts only while `hw+0x18E1` ≠ 0 (set to 1 by the GUI task's entry, `0x24001A51`); `hw+0x18E0`
  ≠ 0 makes one scan resync the positions and post nothing. ✓ unit: `+0x18E0` = 0, `+0x18E1` = 1.
- Stock posts at most one event per knob per pass, and never checks the ring for room (64 entries).

**Injection** (*design*): in the GUI task, right after `FUN_08040724` returns (the hook that exists), write one
entry at `hw + 0xC70 + (w & 63) × 0x18` and then `w + 1` to `hw+0x1274` behind a `dmb`, as `FUN_08040BAC` does. The
drain that follows delivers it in the same pass, after any real knob's events. Only when `hw+0x18E1` ≠ 0 and the
ring has room. One event per pass per knob keeps the accelerator (A3: 8 `{counts, ms}` pairs, `m` = counts per ms)
seeing what a hand gives it: a burst in one pass would read as a zero span (`m` = 1).

### 3.2 Buttons ✓ unit (table, rings), ✓ injected (TOOLS)

- **Panel object** `P` = `0x240021BC`. Its button table is at `0x24009AB0` (13 rows × `0x18`, built by the
  constructor `FUN_08045544`): `+0` GPIO port, `+4` pin mask, `+8` u16 press code, `+0xA` u16 release code (0 = none),
  `+0xC` u16 hold code (0 = none), `+0xE` u8 last level (1 = up), `+0x10` u32 tick of the last change, `+0x14` u8
  "hold already sent". The LED table is at `0x24009A2C` (11 rows × `0xC`).
- **Scan**: `FUN_080437D4(P)`, called at the top of every audio block by the block function `FUN_0804CB1C`, so ~375
  times a second (✓ unit: `P+0xC10`, its tick, went up by 362 a second while peeked). A level change counts only 25
  ticks (67 ms) after the last; a hold fires after 600 ticks (1.6 s) held. A row's physical pin maps to its logical
  index through `P+0xC14`: 1 = row k is index k, 0 = reversed. ✓ unit: 1.
- **Two rings, one message.** Each event is written to ring G at `P+0x000` (64 × `0x18`, read `P+0x600`, write
  `P+0x604`) and to ring E at `P+0x608` (read `P+0xC08`, write `P+0xC0C`): `+0` u16 code, `+8` u16 0, `+0xC` i32
  logical index, `+0x10` 0, `+0x14` 0 (`+4` is not written; no reader uses it). The GUI app pass drains G at its
  very start (`FUN_08043A84` → `FUN_080A2E60`); the audio block drains E (`FUN_08043A2C`, in `FUN_0804CB1C`). Both
  stop at `w == r`; neither checks for overflow.
- **The 13 buttons** (codes ✓ unit; what they do *static*):

  | index | button | press | release | hold | GUI (`FUN_080A2E60`, ignored while `app+0x8CC3` ≠ 0) | audio block |
  |---|---|---|---|---|---|---|
  | 0–7 | PADS KEYS SEQS SONG FX MIX PSET TOOLS | `0xF9` | — | — | screen by index: 0 → 2 (Pads), 1 → `0x2B` (or `0x31` from `0x2B`), 2 → `0x2C`, 3 → `0x2D`, 4 → `0x37` / `0x36` / `0x30` by the current one, 5 → `0x2E` (or `0x2F` from `0x2E`), 6 → 7 (PSET), 7 → `0x25` (TOOLS) | ignored |
  | 8 | REC | `0xF4` | `0xF5` | — | wakes the screen (`FUN_080A16C4(app, 0)`) | `FUN_080524CC(clock, 1 / 0)`: REC held flag `clock+0x128D4`; pressed while playing toggles recording |
  | 9 | STOP | `0xF6` | — | — | wakes the screen | `FUN_08052010(clock)`: stop |
  | 10 | PLAY | `0xF7` | — | — | wakes the screen | `FUN_08051EB8(clock)`: start (engine message `0x57`; with REC held, record first) |
  | 11 | BACK | `7` | — | `8` | `7`: back, per screen; `8`: `FUN_080A16C4(app, 1)` (standby, *inferred*) | ignored |
  | 12 | INFO | `0xC` | — | — | deeper, per screen | ignored |

  The clock is `*(engine + 0x9A74)`; after `0xF6` / `0xF7` the block relights LED 10 from "playing" (`clock+0x38`,
  `FUN_080525D0`) and LED 8 from "recording" (`FUN_080525D8`).
- **✓ injected** (12/11, raw pokes in RAM, the only write this pass made): with both rings idle at 0/0 and the Pads
  screen up (`app+0x8CA4` = 2), one TOOLS press (code `0xF9`, index 7) written into the next entry of both rings and
  both write indices advanced. 0.3 s later both read indices had followed (1/1) and `app+0x8CA4` read `0x25` (TOOLS)
  with `0x02` as the previous screen. The poke runs in `usbdev_poll`, in the audio task, the producer's own task,
  which is why it cannot race the scan.

**Injection** (*design*): from the audio task between blocks (`usbdev_poll`), with the code taken from stock's own
table row (press `+8`, release `+0xA`, hold `+0xC`; refuse an action whose code is 0), the entry into G, then into E,
then each write index behind a `dmb`. Refuse when a ring is full (`w − r` ≥ 64).

## 4. Touch

*static*, the tracker's state ✓ unit.

- **Driver**: `FUN_08042548(T, buf)`, `T` = `0x24001FAC`, in the GUI loop once a pass. It reads the touch
  controller at I2C address `0xBA` (a Goodix GT9xx by its register map, *inferred*): status register `0x814E` (bit
  7 = new data, bits 0–2 = contacts), the contacts from `0x814F` (7 bytes read from each 8-byte record), then clears
  the status. Only when bit 7 is set does it rewrite `buf`; otherwise the buffer — on the GUI loop's stack, kept
  from pass to pass — still says what it said last time.
- **Buffer**: `+0` u16 contact count (≤ 5); contact i at `+4 + 12i`: s16 x, s16 y, u8 track id. x and y are screen
  pixels, clamped to 0..319 and 0..239, after a transform set by `T+0x198` (swap / flip) and `T+0x199` (scale off),
  with `T+0x19C` / `T+0x1A0` the panel's height and width. ✓ unit: `T+0x198` = 1, `T+0x199` = 0, 240 and 320.
  That the pixel grid is the screenshot's (x right, y down from the top left) is *inferred*.
- **Tracker** `FUN_0808B050(gui, buf)`, the first thing `FUN_0808B654` does: up to 4 contacts at `gui+0x214` (u16
  count) and `gui+0x218 + 12i` {s16 x, s16 y, u8 id, widget id at `+8`}.
  - **Down** (an id not tracked): hit test `FUN_080AB5F2(gui+0x280, &{x, y}, &widget)` (the current screen's `vt+0x28`
    first, then the container's own children); keep the widget's id (`widget+0x28`); call `widget->vt[+0x10](widget,
    &{x, y}, id)`.
  - **Move** (a tracked id at another x or y): find the widget again by id, `FUN_080AECDA(gui+0x280, wid, &widget)`
    (it may be gone: then nothing); `vt[+0x14]`.
  - **Up** (a tracked id absent): the same lookup; `vt[+0x18]`; the slot is removed.
  - Nothing else in the image reads or writes `gui+0x214..` (grepped). ✓ unit: count 0, no contact.
- What the three virtuals do is each widget's own (A5 has the XY pad's: `0x6E` posts of `0x15`, X, Y).

**Injection** (*design*): the GUI task, at the knob-scan hook, runs one contact of its own through the same three
calls: hit test, then the widget's `vt+0x10` with the kit's id (15: GT911 ids are 0–9) on down; lookup by the kept
widget id, then `vt+0x14` on move and `vt+0x18` on up. Stock's tracker never sees it, so the real buffer's "no
contact" cannot lift it at the next pass, and a held touch lasts as long as the host wants. The difference from a
finger: the calls come later in the same pass (inside the app pass rather than before it); every post they make is
synchronous (§2), so its effect lands in the same pass. *Alternative*, more faithful and one new site: replace `bl
FUN_0808B050` at `0x0808B65E` with a call that overwrites `buf` with the kit's contact before stock's tracker runs
(about 16 B of bank 1).

## 5. A preset load by name

*static*, the counts ✓ unit.

- **The Load button.** The PSET view's constructor `FUN_080BE20C` builds its buttons with their message codes: Load
  `0x18`, Save `0x20`, File `0x127`; the File menu's New `0x1A`, SaveAs `0x21`, Rename `0x1D`, Pack `0x22`, Clean
  `0x23`, Delete `0x1C` (view messages to the app, not the card commands below). `FUN_080A1718`'s case `0x18` (and `0xD8`, which is the same; its sender was not found)
  calls **LoadBank** `FUN_0809E218(app, msg+0xC, 1)` and then `FUN_0809EAEC(app, 2, 0)`, the Pads screen. That the
  view puts the selected row's index in `+0xC` is *inferred* from the handler. The engine → app message `0x6B` also
  runs LoadBank (with no screen change; a MIDI program change, *inferred*).
- **LoadBank** (log strings `SessionMgr::LoadBank …`) refuses, in order: a load already pending (the preset
  manager's `F+0x390` string not empty); the streamer busy (`FUN_0807125C(0x2400A9C0)` = 0: its pending list or
  command ring not empty, "REJECTED based on file command queue"); an index ≥ the list's count. Then it drops the
  pads' sample work (`FUN_0804C664` per cell, *inferred*), takes name i from the list, and calls `FUN_08090B78(F, name)`
  (`PresetMgr::RequestPresetLoad`: refuses a stacked load, sets `F+0x390` to the name, queues command `0x22`, wakes
  the card task); with its last argument 1 it also records the name for `settings.tml` (`FUN_08090CBC`).
- **The preset manager** `F` = `0x2401F508`: command ring at `F+0x20` (16 × `0x10`: `+0` word, `+4` u8 command,
  `+5` u8 flag, `+8` and `+0xC` two 256-B string handles), read `F+0x120`, write `F+0x124`; reply ring at `F+0x128`
  (16 × `0x18`, write `F+0x2AC`) that the app pass reads; the **preset list** at `F+0x32C` = `0x2401F834` {u32 count,
  u32 capacity, …, `+0xC` char** names, `+0x10` u8 "re-sort first"}; `FUN_0804290C(list, i, buf)` copies name i
  (sorting first when needed) and says whether i < count. ✓ unit: 75 presets (`F+0x32C`), ring 3/3 (idle).
- **The card side**: the card task's loop `FUN_080743B0` calls the command step `FUN_08092F5C` (the three sites
  `b2load_thunk` holds); command `0x22` → `FUN_08091988` → `FUN_080918C8`, the load; a name that fails falls back to
  the first loadable preset of the list; the reply (`3`, ok flag at `+0x10`) goes back through `F+0x128`.
  **A precision on X2**: X2's chain `0x080743B0 → 0x08092F5C → 0x080922E4 → 0x08096AD8` is command `0x23`
  (`FUN_0809113C` queues it, from `FUN_0809E8E4`, not traced), not the Load button's `0x22`; `0x22` reaches the same
  XML loader `FUN_08096AD8` through `FUN_08091988` → `FUN_080918C8`.

**Injection** (*design*): the GUI task, not the card task — LoadBank is GUI-side and hands the card its part. Find i
with `FUN_0804290C` over the list, then call `FUN_080A1718(app, {0x18, …, +0xC = i})`: the message the Load button's
post delivers at its top. The kit checks LoadBank's three refusals first so it can say which one held.

## 6. Stock's FatFs

*static*; the argument registers of `f_lseek` checked at two stock call sites.

The build is FatFs R0.12–R0.13 style with exFAT (64-bit sizes and positions), `FF_FS_TINY` (no per-file buffer: the
volume's window serves every file), long names (255), fast seek and find. Entries:

| call | address | signature | stock callers |
|---|---|---|---|
| `f_mount` | `0x080864E8` | `(fs, path, opt)` | |
| `f_open` | `0x08086534` | `(fp, path, mode)` | known |
| `f_read` | `0x08086866` | `(fp, buf, n, *got)` | known |
| `f_write` | `0x08086A06` | `(fp, buf, n, *put)` | `0x0804B1C4`, `0x08076874`, `0x080771DC`, `0x0807723C` (the preset and WAV writers, *inferred*); Trim's copy `FUN_08072A40` (X4) |
| `f_sync` | `0x08086C28` | `(fp)` | only `f_close` |
| `f_close` | `0x08086D76` | `(fp)` (= `f_sync`, then the handle invalid) | known |
| `f_lseek` | `0x08086D96` | `(fp, -, ofs_lo, ofs_hi)`: **the 64-bit offset in r2:r3**, r1 unused (the calls at `0x080768FA` and `0x0806F9F8` load r2 and r3 just before) | the WAV header reader (`FUN_08076AF4`, X3) and others |
| `f_opendir` | `0x080870F6` | `(dp, path)` | `FUN_08042C1C` (card present), `f_findfirst` |
| `f_closedir` | `0x0808718C` | `(dp)` | |
| `f_readdir` | `0x080871A0` | `(dp, fno)` | `f_findnext` |
| `f_findfirst` | `0x0808722E` | `(dp, fno, path, pattern)` | the directory lists (`FUN_08042CD0`, `0x08042DAC`, `0x08042F64`, `0x08043284`) |
| `f_findnext` | `0x080871F0` | `(dp, fno)` | the same |
| `f_stat` | `0x0808724A` | `(path, fno)` | `FUN_08042E44` (a file's size) |
| `f_getfree` | `0x08087290` | `(path, *clusters, **fs)` | the free-space readout (`0x08045BE2`) |
| `f_truncate` | `0x080873C8` | `(fp)` | |
| `f_unlink` | `0x0808748E` | `(path)` | `FUN_08042E30`, the folder delete `0x08043284`, `0x08091E40` |
| `f_mkdir` | `0x08087558` | `(path)` | `FUN_08042E3A` |
| `f_rename` | `0x080876C8` | `(old, new)` | `FUN_08042E24` |

- **Objects**: `FIL` = **`0x58`** B (stock clears `0x58` before `f_open`, and the layout adds up: the object id
  `0x30` with a 64-bit size at `+0x10`; flag `+0x30`, error `+0x31`, position u64 `+0x38`, cluster `+0x40`, sector
  `+0x44`, directory sector and pointer, the fast-seek table `+0x50`). `DIR` = **`0x58`** B (stock clears `0x58`;
  the find pattern at `+0x50`). `FILINFO` = **`0x120`** B: size u64 `+0`, attribute u8 `+0xC`, long name `+0x1A`
  (256), as stock's own lists and size query use them; date u16 `+8`, time u16 `+0xA` and the short name `+0xD` are
  FatFs's layout (*inferred*).
- Modes are FatFs's: read 1, write 2, create-new 4 (fails with `FR_EXIST` = 8 when the file exists), create-always 8,
  open-always `0x10`. A put that must not replace opens with write | create-new.
- Paths: stock builds them with `\` (`0x080CACDC`); FatFs takes `\` and `/` alike. The root is the empty path
  (`0x080CB060`), as `b2load.c` notes.
- **One task**: stock's FatFs takes no lock (`validate` `0x08084440`), and every stock call found runs in the card
  task (`b2load.c`'s header). The card-found byte is `0x240021A4 + 0x15`.

## 7. A reset

*static*. **Stock 3.1.9 never resets itself in software**: no `SYSRESETREQ` anywhere (the two `AIRCR` users are the
priority grouping `FUN_08078BA4` and FreeRTOS's priority check `FUN_080881C4`). Its resets are the window watchdog
(started in `main` by `FUN_08046938`, fed from the audio block by `FUN_08046994` while both watched tasks have
stamped within 3 750 blocks, X2 / `b2load.c`) and power. The fork has two: `b2load.c`'s `restart()` after writing
bank 2, and `fault.c`'s after a fault, both `AIRCR = 0x05FA0004` behind a `dsb`, `fault.c` after cleaning backup
SRAM's cache lines (its header: a reset does not write the data cache out).

What "clean" has to cover (*design*, from the above): no FatFs write half-done — run from the card task between
file commands (the `b2load_thunk` sites), with the kit's own file closed (`f_close` flushes the window and the
directory entry); stock idle: command ring empty (`F+0x120` = `F+0x124`), no load pending (`F+0x390` empty), the
streamer idle (`FUN_0807125C`); every cache line the next boot must see cleaned (the job's request and reply in
SDRAM, any backup SRAM word, as `bkp_put` does); then `dsb`, `SYSRESETREQ`. SDRAM keeps its contents through a
software reset (X2) — and through a re-flash — so a restart request still lying in the mailbox must not run again
at the next boot (§9: the epoch). Not found: a flag that says a take is being recorded to the card (the WAV writer
keeps its file open across command steps); until it is, the reset should refuse while the transport plays or the
recorder is armed.

## 8. Endpoint 0 beyond 64 bytes, and a bulk read

*static*, from `src/usbdev.c` and the OTG core's registers.

- Today a vendor peek answers at most 64 B (one packet): `request()` runs from `usbdev_poll`, once per audio block
  (2.67 ms), when it sees the SETUP. A descriptor longer than 64 B is sent a packet per block by `serve()`
  (`more_at` / `more_left`). `bench/bbshot.py` reads a 320 × 240 ARGB1555 layer (153 600 B) in 2 400 such peeks:
  13 s, about 5.4 ms (two blocks) a peek.
- **The core's limit**: EP0 IN is armed through `DIEPTSIZ0`, whose transfer size is 7 bits and packet count 2 bits
  (127 B, 3 packets), and a short packet ends the data stage, so one arming carries one 64-B packet. Its TX FIFO is
  `0x40` words (256 B, `core_setup`). **More than 64 B per request = re-arm EP0 IN after each packet**: from the poll
  that is 24 KB/s; from the OTG interrupt (vector 77, `usbaud_isr`, which today takes only endpoint 2 and the receive
  FIFO) it is as fast as the host asks. It needs EP0 IN's completion enabled (`DAINTMSK` bit 0 beside bit 2;
  `DIEPMSK` already has `XFRC` while audio runs), and the poll must leave `DIEPINT0` to the interrupt while a long
  read is running (today `serve()` clears it every block).
- **The host's limit**: Linux's usbfs, which pyusb uses, refuses a control transfer longer than one page (4 096 B)
  (*from memory of the kernel source, not tried*: a request with wLength 8 192 settles it without reaching the
  unit). So a 4 096-B long peek: a layer in 38 requests. Each costs the SETUP's wait for the poll (≤ 2.67 ms) and 64
  packets at the host's pace: about 0.4 s a layer, if the host schedules 8 or more control packets a frame
  (*estimate*, unmeasured; the audio stream's 882 B a frame only count while a capture runs).
- **The same for writes**: a file put needs host → unit bytes, and today's poke is 2 requests a word (1 MB = 23
  minutes). An EP0 OUT data stage of up to 4 096 B (`DOEPTSIZ0`: one packet an arming, re-armed by the interrupt
  on each "OUT done", the words copied out of the receive FIFO where `receive()` already reads them) gives the
  same rate as the long peek.
- **A bulk endpoint instead** (EP3 IN on a vendor interface): +16 B of descriptors (`bNumInterfaces` 3 → 4,
  `wTotalLength`), a TX FIFO (the 4 KB FIFO RAM has 2 KB free after RX `0x80`, TX0 `0x40`, TX1 `0x40`, TX2 `0x100`
  words), arming at SET_CONFIGURATION, an empty-FIFO interrupt to feed it; no 4 096-B cap, and a bulk read at full
  speed gets what the frame has left (~1 MB/s at best). Cost: about 200–300 B of bank 1, a configuration that
  differs between dev and release (hosts cache descriptors: `bcdDevice` would have to move), and a second path to
  test. Not worth it unless the long peek measures under ~200 KB/s. (The FIFO RAM's size, 4 KB, is the reference
  manual's figure for this part, not read off the unit.)

## 9. The design: the job mailbox

*design*, for pass 2.

### 9.1 Where things live

- **Bank 1, dev builds only** (new file `src/kit.c`, all of it under `#ifndef PUBLIC_BUILD`): one gate
  `kit_poll(task)` — the SDRAM block (`master_block()`) and `b2_live()`, then `kit_run(task, block)` in bank 2 —
  and the call-outs: the knob-scan hook becomes `FUN_08040724(hw); kit_poll(SCREEN)` (the present mailbox's body
  moves to bank 2); `usbdev_poll`'s `RUNNING` case calls `kit_poll(AUDIO)`; the three card sites call
  `kit_card_b` (`kit_poll(CARD)`, then `b2load_thunk` as today), chosen in `patches/master.py` only when the symbol
  exists, as `patches/cpu.py` does for the mailbox; `request()` hands vendor requests `0x53` (long peek) and `0x54`
  (long poke) to `kit.c`, and `usbaud_isr` calls `kit.c` on EP0 IN / OUT completion while one runs. The USB plumbing
  stays in bank 1: it must not depend on bank 2 for enumeration, and the long transfer only starts when `b2_live()`
  said yes.
- **Bank 2** (new file `src/kit_b2.c`, in `BANK2_SRCS`): `kit_run`, the function table and every job. It calls
  stock 3.1.9 at fixed addresses and nothing in the cave (`test_bank2.py`'s rule); bank 1 passes it the block.
- **One payload** for dev and release: `kit_b2.c` uses no `PUBLIC_BUILD`, so `BBEXTRA.BIN` stays byte for byte the
  same in both builds, as it is today (12/11: `RELEASE=1` and dev `out/bank2.bin` identical, 24 672 B, id
  `0x82b303ee`). In a release nothing in bank 1 calls it: no dispatcher, no hook, no peek. Two payloads would make
  every dev ↔ release install rewrite bank 2 (one restart, flash wear) and the release's `BBEXTRA.BIN` would not be
  the one benched. The cost: the kit's few KB sit unused in a release's bank 2 (~900 KB free there).

### 9.2 The request

At the present mailbox's place, block + `0xC000` (`cw_bank` + `0xF00`, its 4 KB's last `0x100` B). All words
little-endian. The host writes the request in one long poke (or word pokes), **`seq` last**: it is the last word,
so a long poke written in ascending order completes it last.

| offset | written by | field |
|---|---|---|
| `+0x00` | host | magic `KIT1` (`0x3154494B`); `MBX1` = today's 13-row request (§9.4) |
| `+0x04` | host | u16 function index, u16 flags (0) |
| `+0x08` | host | epoch: the boot count the host read at `0x38800FE0` (`fault.c`'s boot record) |
| `+0x0C`..`+0x20` | host | six i32 arguments |
| `+0x24` | host | seq (last) |
| `+0x28` | unit | done = the seq served (written last, after the rest) |
| `+0x2C` | unit | result: 0 done; −1 index out of range; −2 stale epoch; −3 bad argument; −4 stock refused (busy, pending, ring full, knobs off); −5 not found; −6 FatFs error (its code in r0); −7 file state (none open / one open already) |
| `+0x30`..`+0x3C` | unit | r0..r3, values back |
| `+0x40` | unit | state: 1 while a multi-pass job runs (knob events, a tap) |
| `+0x44` | unit | the table's version and size, so a host knows what it talks to |
| `+0x48`..`+0xFF` | unit | the open file's `FIL` (`0x58`) and spare |

**Data area**, dev builds only: block + `0xC100`, `0x2000` B — the core grows by `0x2000` under `#ifndef
PUBLIC_BUILD` (`master.c`'s `CORE_BYTES`; the release block unchanged). `+0x000` a name or path (256 B), `+0x100`
`DIR` and `FILINFO`, `+0x400` the 4 096-B chunk (file data, a listing's records). The long poke writes only into the
mailbox page and this area; the long peek reads the peek's bounded regions.

**The gate** (bank 2, every call): magic `KIT1`, seq ≠ done, epoch = the boot count now, index < table size, the
entry's task = the calling task. A request for another task is left for that task; anything else is answered by the
screen task, which runs every pass. Without bank 2 live nothing answers (the host times out and can read
`cpu_state.b2chk`). The epoch is what keeps a restart, or any request, written before a reset from running after it
(SDRAM keeps it).

### 9.3 The function table

Index space by task: `0x00–0x1F` screen, `0x20–0x3F` audio, `0x40–0x5F` card. Each entry: task, flags, function.

| index | task (hook) | job | arguments | back |
|---|---|---|---|---|
| `0x00` | screen | info | — | table id, screen (`app+0x8CA4`), GUI ms, epoch |
| `0x01` | screen | row set (today's op 1) | cell, id, value | the store's value after |
| `0x02` | screen | row get (today's op 2) | cell, id | the value |
| `0x03` | screen | knob | knob 0–3, counts per event (±32 767), events, passes between | events posted |
| `0x04` | screen | touch | 0 down / 1 move / 2 up, x, y | the widget id hit (0 none) |
| `0x05` | screen | tap | x, y, passes held | widget id |
| `0x06` | screen | preset load | the name in the data area | its index (or −4 with which of LoadBank's refusals, −5 not in the list) |
| `0x07` | screen | preset state | — | load pending, commands queued, count; the current name into the data area |
| `0x20` | audio | button | index 0–12, 0 press / 1 release / 2 hold | the code posted |
| `0x40` | card | open | 0 read / 1 write new / 2 write, replacing / 3 append; the path in the data area | FatFs result, size |
| `0x41` | card | read | bytes ≤ 4 096 → the chunk | bytes read |
| `0x42` | card | write | bytes ≤ 4 096 from the chunk | bytes written |
| `0x43` | card | seek | offset low, high | |
| `0x44` | card | close | — | |
| `0x45` | card | stat | the path | size, attribute, date, time |
| `0x46` | card | list | the path, first entry, max | records {size, attribute, name} in the chunk, count, "more" |
| `0x47` | card | delete | the path | FatFs result |
| `0x4F` | card | restart | `0x52455354` ("REST") as a check | nothing: the unit resets, or −4 / −7 and why |

Play and stop are a button press (10, 9) on the host's side; the clients `knob`, `button`, `touch`, `play`, `stop`,
`preset`, `put`, `get`, `ls`, `rm`, `restart` map onto this table, `shot` onto the long peek. A file left open more
than ~10 s with no job is closed by the card dispatcher, so a host that died mid-put leaves no open write handle.
Long card jobs (a listing) stamp the card task's watchdog word (`0x2400A584` ← `0x2400A58C`) as `b2load.c` does.

### 9.4 The present 13-row mailbox

Its request (`MBX1`: magic, seq at `+4`, op / row / col `+8`, id `+0xC`, value `+0x10`; done `+0x14`, result
`+0x18`, value back `+0x1C`) is served by the screen task's `kit_run` as jobs `0x01` / `0x02`, with the same checks,
results and reply offsets as today. So the installed build's `bbusb.py set / get` (and `bench/autogate.py`'s
`BB_BENCH`, which runs that copy) work unchanged against the new firmware; the new `bbusb.py` uses `KIT1`. **One
change**: set / get now need bank 2 live (they ran in bank 1 before), so a stock row (Pad Mode, Sync, …) no longer
answers on a unit without this build's `BBEXTRA.BIN`. The gates the bench runs need bank 2 for the Clip Window
anyway (D-018).

### 9.5 Bank 1 bytes

Measured 12/11 with `arm-none-eabi-size -A out/cave.elf` on `d23b389`: dev `.cave` **51 874 B** (5 862 free of 57
736), release 51 258 B; the present mailbox is `usbdev_mailbox_scan` **248 B** + `MBOX_IDS` **26 B** = 274 B, all of
which moves to bank 2. (The JOEBOX 2 merge, not on this base, leaves 363 B free: the rule below is relative, so it
holds on either base.) Estimates for pass 2 to measure: the gate ~24 B, the scan hook ~12, the audio call-out ~6,
the card call-out ~16, the long peek ~70 (`request()` branch + interrupt refill), the long poke ~70 → ~200 B, about
**−75 B net**. The cap: dev `.cave` ≤ today's + 100 B.

## 10. On the unit, 12/11

- Read (dev peek, bounded): the panel rings and button table, the knob ring and gates, the touch tracker and
  transform, the UI object, the Pads view's parent and the container's vtable, the preset manager's list count and
  command ring, the app's screen byte. Every one as §3–5 say.
- Written: one TOOLS press, by poke into the two panel rings (§3.2). Nothing else.
- The unit then **power-cycled twice** (kernel log: disconnects 14:32:37 and 14:33:40, back 12 s and 10 s later;
  `bbusb.py crash` after each: reset cause power-on (POR / BOR / PIN, `RSR 0x00FE0000`), boot record #1, no fault
  or watchdog record — backup SRAM had lost power too). The first came within a minute of the injected TOOLS press
  (the unit had answered right after it), the second during a `bbshot.py` run. At 14:28:14 the unit had moved from
  bus 1 to a new hub chain (VIA `2109:2822`, then Realtek `0bda:5411`, plugged 14:25:31), which it was on for all
  three boots. A RAM poke cannot cut power, and a crash or a watchdog would have left a record; a USB supply that
  sags under load (TOOLS shows the card's free space, and a card scan draws current: *inferred*) is the likelier
  cause, not proven. The kit's work on the unit stopped there.

## 11. How this was checked

- Static: the Ghidra exports (`out_all.c`, `listing.txt`, `functions.tsv`) and capstone (`disasm.py`) on the stock
  image, for every address above; the functions Ghidra did not make (the Pads view's `vt+0x30` `0x080B3E84`, the
  container's `0x080AB4A8`) disassembled by hand. Grep for every writer of the knob ring's write index, the panel
  rings' indices and the touch tracker's fields; for every `bl` / `b` into `FUN_080A1718` (two) and every literal of
  `0x080A1719` (none) before the unit showed the container's call.
- The unit: as §10. Not run anywhere: any injection but the TOOLS press; the touch virtuals, the knob ring entry and
  LoadBank under Unicorn (pass 2's `test_benchkit.py`); the long peek's speed; Linux's 4 096-B cap.

## 12. Still open

| # | question | for | cheapest way |
|---|---|---|---|
| 1 | GUI passes per second (the knob job's pacing, a tap's length) | knob, touch | peek `0x2402EEE0` and a counter the pass bumps, twice |
| 2 | the touch grid = the screenshot's grid (0, 0 top left) | touch | one tap on a known button, then a screenshot |
| 3 | which message a held finger on a pad posts per pass (repeat or not) | touch | Unicorn on the Pads view |
| 4 | who posts `0xD8` (same handler as `0x18`) | preset | grep a message table; not needed |
| 5 | a flag that a take is being written to the card | restart | static: the WAV writer's object (`0x0807723C`'s callers) |
| 6 | the card task's loop rate (latency of a card job) | files | a counter in `kit_run`, peeked |
| 7 | the long peek's real rate on this host | shot | measure in pass 2 |
| 8 | why the unit lost power twice on the new hub | bench | Thomas: the unit back on its own supply or a powered port |

## 13. Pass 2: what was built, and where it left §9

Built 12/11 on `wip/blackbox-t-054` (`src/kit.c`, `src/kit_b2.c`, call-outs in `src/usbdev.c`, `src/b2load_thunk.S`,
`src/master.c`, `patches/cpu.py`; `bench/bbkit.py`; `test_benchkit.py`, long transfers in `test_usbdev.py`). Every
claim here ran under Unicorn on the patched image; none has run on the unit (it runs 37.4.1d until Thomas installs).

- **Two payloads, not one** (§9.1 said one). The release's bank 1 holds the payload's sum (`b2_expect_sum`) and id
  (`B2_ID`, `header_ok`, `b2_ok`), so any kit code in a release's bank 2 changes the release's `BLACKBOX.bin`. `build.sh`
  puts `kit_b2` in bank 2 for dev builds only, after every other object: a dev `BBEXTRA.BIN` is the release's code
  plus the kit, and a `RELEASE=1` image is byte for byte the base's (checked against `d23b389`'s, sha256). The cost:
  a dev ↔ release install rewrites bank 2 (one restart at the first boot).
- **The data area sits at the tail's end, not in a grown core** (§9.2 said `CORE_BYTES` + `0x2000`). Dev builds only:
  `master.c`'s `KIT_BYTES` = `0x1400` at block + `0x84900`, so Prism, the inserts and `cw_bank` keep the offsets a
  release has; only `master_alloc`'s size changes (`0x85D00`). It exists only with the tail (the check word keyed
  PRISM), which is what a live bank 2 implies; `kit_b2.c`'s `data_area()` checks the key anyway. Layout: `+0x000`
  `FIL`, `+0x058` `DIR`, `+0x0B0` `FILINFO`, `+0x200` a name or path (256 B), `+0x300` the preset job's scratch name,
  `+0x400` the 4 096-B chunk.
- **The mailbox** is §9.2's at block + `0xC000`; the unit's own state from `+0x48`: the screen task's boot stamp and
  the job spanning passes (`+0x4C` seq, `+0x50` index, `+0x52` wait, `+0x54`..`+0x67` its counts), the kit's touch
  (`+0x51` down, `+0x68` x, `+0x6C` y, `+0x70` widget id), the card task's boot stamp `+0x74`, the last file job's GUI
  ms `+0x78`, the open file `+0x7C` (0 none, 1 read, 2 write). Each task resets its own part when the boot count moved.
  `+0x44` = version 1 << 16 | `0x60` slots.
- **The gate**: bank 1's `kit_poll(task)` (`master_block()` and `b2_live()`, 32 B) then bank 2's `kit_gate`: magic
  `KIT1`, seq ≠ done, index < `0x60` with a job (else the screen task answers −1), `index >> 5` = the task, epoch =
  the boot count (else −2). A job spanning passes (knob, tap) blocks new requests until it ends.
- **The jobs** (§9.3's table, as built): `0x00` info, `0x01` / `0x02` row set / get, `0x03` knob, `0x04` touch,
  `0x05` tap, `0x06` preset load by name, `0x07` the preset list by index (r0 count, r1 pending, r2 queued, the name to
  `+0x200`), `0x20` button, `0x40`..`0x47` open, read, write, seek, close, stat, list, delete, `0x4F` restart. Not
  built: §9.3's "preset state" with the current preset's name (its place in the app was not found).
- **Touch**: the kit's contact runs through the tracker's own three calls from the knob-scan hook (§4's first choice);
  under Unicorn its calls are the same, in the same order, with the same points, as `FUN_0808B050`'s for a finger
  (down, two moves, up), and the tracker's state at `gui+0x214` stays untouched.
- **Buttons**: the entries the kit writes are byte for byte what stock's `FUN_080437D4` writes for that pin held low
  (run for real on the same table, all 13 buttons, REC's release, BACK's hold). Stock's two consumers ran for real
  on them: the GUI's `FUN_080A2E60` (TOOLS → screen `0x25`) and the audio block's ring loop (`0x0804CCC4`..
  `0x0804CE3A`: PLAY → `FUN_08051EB8`, STOP → `FUN_08052010`, REC → `FUN_080524CC(clock, 1 / 0)`).
- **Knobs**: stock's drain (`0x080A2CDA`..`0x080A2D36`) ran for real after `kit_scan` and handed `FUN_080A1718` the
  kit's `{0x32, code, counts}` once a pass.
- **Preset load**: `FUN_080A1718`'s case `0x18` ran for real: `LoadBank(app, index, 1)`, then screen 2.
- **Restart**: refused (−4, r0 the reason) while the transport plays (clock + `0x38`), REC is held (clock +
  `0x128D4`), file commands are queued (F + `0x120` ≠ + `0x124`), a load is pending (`*(F + 0x390)` not empty) or
  `FUN_0807125C` says the streamer is busy; −7 while the kit's file is open. Otherwise: answered, the box's two cache
  lines cleaned, `AIRCR` = `0x05FA0004`. Still no flag found for a take being written (§12 #5).
- **The long peek is the old peek (`0xC0` / `0x50`) with wLength 65..4 096**, not a new request `0x53`: usbdev.c sends
  the first 64 bytes as ever and hands the rest to bank 2 (`kit_long`), whose `kit_usb_in` loads each next packet from
  the interrupt. A long peek it cannot take (range leaving its region, bank 2 not live, not whole words, over 4 096)
  is now **stalled**: a full 64-byte answer would leave the computer waiting for the rest. An older build does exactly
  that, so `bbusb.peek` asks once with a 0.25 s timeout and falls back to 64-B requests for that process.
- **The long poke is `0x40` / `0x54`**, wLength 4..4 096 bytes into the RAMs the word poke may write; usbdev.c's
  `receive()` hands endpoint 0's OUT entries to `kit_usb_out` while it runs, which keeps the words, re-arms the
  endpoint, and after the last sends the empty status packet.
- **Their flags are `DAINTMSK` bits**, which every reset clears (backup SRAM and SDRAM would not): bit 0 (endpoint 0
  IN's interrupt, on only while a long peek runs) and bit 16 (endpoint 0 OUT's, which `GINTMSK` never lets through:
  the long poke's flag). The interrupt calls bank 2 only while one is up, so it never does in a boot that did not
  start a transfer behind `b2_live()`. Every SETUP clears both: a transfer the computer gave up on ends there.
  The transfer's cursor is at `0x388006B8` (backup SRAM, 8 B, behind `usbdiag`, before `rotate.c`'s `ACC`).
- **Bank 1, measured** (`arm-none-eabi-size -A out/cave.elf`): base dev `.cave` 51 874 B; the dispatcher and the rows
  moved (step 1) 51 666; with everything 51 878 (+4 net). Out: `usbdev_mailbox_scan` 248 + `MBOX_IDS` 26. In:
  `kit_poll` 32, `kit_scan` 16, `usbdev_poll` +188 (the audio call-out, the SETUP's flag clear, the long peek's and
  the long poke's branches), `usbaud_isr` +32 (the two interrupt call-outs), `b2load_thunk` +6. `B2_ID` is a hash and
  its encoding moves `b2_ok` / `header_ok` by 4 B each from one id to another: this build's costs 8 B more than the
  base's. Release `.cave` 51 258, unchanged.
- **Bank 2**: base `.bank2` 24 656 B (both builds); dev with the kit 28 416 B; release 24 656 B, unchanged.
