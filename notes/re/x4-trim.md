# X4 — stock's Trim on a Clip pad (blackbox#t-040)

Stock 3.1.9. Marks as in the other notes: ✓ = run under Unicorn, *inferred* = a static read (Ghidra 12.1.4 on a
/tmp copy of `/srv/dev/firmware/ghidra`), *design* = a choice. Plan of record: hub `blackbox` notes
`2026-10-22-t-031-close.md` (rev 1, ratified 22/10).

**Status (22/10, turn 4): the static half, plus §6 ✓ (the meta's loop and crop), §7 ✓ (the disk copy's bytes) and §8
(the menu's enables ✓, the task read).** The chain below is read, its hook sites named. Still owed before the patch
leans on it, by a Unicorn run: §5 item 3, the reload.

## 1. The menu — `FUN_080B3194`, case `0x127` (the File menu opening) *inferred*

The browser's File menu enables its items as it opens (`FUN_080BD566(menu, item, on)`, menu = `browser + 0xDD0`):

| call | item | enabled when |
|---|---|---|
| `0x080B3590` / `0x080B35A2` / `0x080B35B4` | Save `0x123` / Save As `0x122` / Trim `0x124` | MultiSam `0xEA` == 0 |
| `0x080B35F6` | Save `0x123` | and the highlighted file is the pad's own (`FUN_08099D1C` path == the browser's, `FUN_080C8B48`) |
| **`0x080B3620`** | **Trim `0x124`** | **Pad Mode `0x8B` == 0 (Sample)** and `0xEA` == 0 and the pad's own file |

So `0x080B3620` is the last word on Trim: one `bl` to redirect for the Clip case (*design*: a bank-1 thunk that
keeps stock's `on` and ORs in « Clip, Region plays a loop, no other cell of the preset names the file, `0xEA` == 0,
own file »). `0xEA` is MultiSam: a mode change clears it (x3 §1), so a Clip pad
always passes that half.

## 2. The confirm — « Trim and Save? » *inferred*

Case `0x124` opens the dialog (string `DAT_080B3948`) and sets the browser state to 300. On yes, state 300:
`FUN_0804290C` builds the path, then **`bl FUN_080A0DD4` at `0x080B38B4`** with trim = 1, cell = `browser + 0x3AC`.
The other two callers are Save (`0x080B384A`, trim 0, onto the own path) and Save As (`0x080B304C`, trim 0, the typed
path). Nothing between the dialog and the call reads Pad Mode.

## 3. Save / Trim — `FUN_080A0DD4(app, cell, path, trim)` *inferred*

In order, with the call sites the patch can take:

1. The meta block `app + 0xE984` is cleared (`FUN_08077440`), the cell's cues copied in (`FUN_08077718`), then Root
   `0xD0`, Beat Count `0xD2` and Pad Mode `0x8B` from the store.
2. **Only if Pad Mode is 0 or 3**: if Loop Mode `0x8E` ≠ 0, the `smpl` loop `{0x91, 0x92, 0x8E == 2}` goes in
   (`bl FUN_08077738` at `0x080A0EE2`); if trim, the crop `bl FUN_0807775C(meta, Start 0x8F, Length 0x90)` at
   `0x080A0F00`. A Clip pad (mode 1) skips both: no loop, no crop.
3. For every other cell (4 rows × 5 columns) whose path equals `path`: `FUN_0804C360(host, cell code, path)`
   (`0x080A0F30`; read as the release of that cell's file before the write, not run).
4. **The write request: `bl thunk_FUN_080712C8(host, asset, meta, path)` at `0x080A0FD0`.** The disk copy
   `FUN_08072A40` crops by meta `+0x228`/`+0x22C` whatever the mode (t-031's read).
5. **The reload of the cell: `bl FUN_080A0AC8(app, path, cell, 0)` at `0x080A0FE0`** (trim; Save takes
   `FUN_080A0CFC` at `0x080A0FFA`, a re-point without a reload).
6. Every other cell naming `path` is reloaded too (`0x080A108A`), then `FUN_0809EAEC(app, 6, 0)`.

So the cut stays stock's if, for a Clip pad, the meta carries the loop and the crop **before step 4**: *design* —
redirect `0x080A0FD0` to a bank-1 thunk that, when a Clip trim is pending, calls `FUN_08077738(meta, 0, &{LS, LE,
type})` and `FUN_0807775C(meta, LS − F, LE − LS + F)` (the call shapes: §6), then tail-calls stock's request. The crop moves the loop
into the cut file as `[F, F + LE − LS)` (t-031's read of `FUN_0807775C`, to prove: §5). Step 2's branch and the store
stay stock's.

## 4. The reload — what it does to a Clip pad's rows (x3 §3, ✓ t13 / t6 there)

- `FUN_080A0AC8` zeroes Start `0x8F`, Length `0x90`, Loop Start `0x91`, sets the record's fresh byte
  (`app + 0x8A88 + row*0x78 + col*0x18 + 0xE`) and asks the loader.
- The loader task posts `0xE` then, if the file has `acid` or `smpl`, `0x1B`, through one ring the **app's
  host-message loop** `FUN_080A2258` reads in order. `0xE` (`FUN_080A121C`) sets Length := Loop End := frames.
- `0x1B` (`FUN_0809D998`): **on a fresh load only**, Pad Mode from the file, `FUN_0809AA94`'s Clip defaults
  (Quant 1 bar, Sync 1/16, Launch, Loop Mode) and the file's `smpl` loop. Not fresh: Root and an Auto Beat Count only.

What follows for the patch (*inferred*, to prove in §5):

- **The same task.** The Trim call (§2) runs in the menu handler, the reload's fresh byte is set inside it, and the
  `0x1B` that would read it is handled later by the app's message loop. That loop is the GUI task's: `FUN_080A2258`
  (`0x080A2258..0x080A2D99`) holds both the `0xE`/`0x1B` dispatch (x3 §3) and the knob scan's `bl` at `0x080A2CD6`
  that the dev builds' parameter mailbox is served from in the GUI task (feature doc, the mailbox). The menu handler
  is a view's, and x1 puts the views in the GUI task too. So clearing the fresh byte right after `0x080A0FE0`
  returns cannot race the `0x1B`, as long as both hold (the menu's side is the weaker read).
- **Cleared fresh byte = rows kept, but no loop from the file**: the non-fresh `0x1B` does not apply `smpl`, and the
  load left Loop Start 0. So Loop Start := F is the patch's own write (with Loop End = the cut file's length, which
  `0xE` sets). Where: after the reload (the `0xE` handler posts `0x91` from the store) or at the `0x1B` for that asset.
- **Beat Count is not at risk.** A fixed Beat Count counts the region (feature doc, « a Beat Count that is not Auto
  … is taken as the region's length »), and the region keeps its length. The writer saves it in `acid`; the non-fresh
  `0x1B` only touches an Auto one.
- Clip Window rows `0x1C8..0x1CB` and Loop Fade `0xFA`: stock's reload does not write them (t-031's read).

## 5. Owed to the Unicorn run (sub-step ① not done until these are ✓)

1. ✓ *(§8)* A Clip pad's File menu reaches case `0x127` (the browser opened from a Clip pad), and `0x080B3620`'s `on` for
   mode 1 is 0 on stock. (Case `0x127` has no mode gate of its own; that a Clip pad's page opens the browser is
   the patch test's and #t-041's.)
2. ✓ *(§6 the meta and its chunks, §7 the audio bytes)* `FUN_080A0DD4` on a Clip pad with the meta patched at `0x080A0FD0`: the bytes the disk copy writes (FatFs served
   from memory) are `[LS − F, LE)` and the `smpl` loop reads back `[F, end)` — `dwEnd` as written (x3: `0x92` is
   written verbatim, read back verbatim).
3. ✓ *(§9 the `0xE` link run on the trim's own store; the load is x3 t13, the non-fresh `0x1B` x3 t6)* The reload with the fresh byte cleared after `0x080A0FE0`: Quant, Sync, Launch, Loop Mode, Beat Count kept;
   `0x91` where the patch put it after `0xE` and `0x1B`. *Read so far (turn 4), from x3's two runs, not yet one run of
   the trim's case*: `FUN_0809D998` tests the byte at `app + 0x8A96 + row·0x78 + col·0x18` (= §4's `+0xE`); its
   `0xEA` branch (the MultiSam zone) returns before it, so it never fires on a Clip pad; not fresh, only Root (store
   0) and an Auto Beat Count are written (x3 t6), and the Clip defaults `FUN_0809aa94` and the `smpl` loop sit past
   that test. The `0xE` handler `FUN_080A121C` sets Length := Loop End := frames and posts `0x8F`–`0x92` **from the
   store** (x3 t13). So the patch writes `0x91` := F into the store right where it clears the fresh byte, after
   `0x080A0FE0` returns (§8: before any `0xE` is read), and `0xE` posts it. The run owes: that chain on one Clip
   store, fresh byte cleared, `0x91` set, the cut file's header and `smpl`.
4. ✓ *(§8, a static read of the call chain)* That `FUN_080B3194` runs in the GUI task, as `FUN_080A2258` does (§4): a hook at `0x080B38B4` that records the
   task, or the thread-create calls in `main` (README's open question 17).

## 6. ✓ The meta's loop and crop — stock's two helpers under Unicorn (22/10, turn 2)

Run on the stock image (`/srv/dev/firmware/BLACKBOX-3.1.9.bin`), meta block in RAM behind a handle, three cues
(one before the region, one in it, one at Loop End), 1 M frames:

- **`FUN_08077738(meta**, index, loop*)`** writes only when `index` == 0 (its first instruction is `cbnz r1`). `loop`
  points at `{u32 start, u32 end, u8 type}`; it sets meta `+0x20C` start, `+0x210` end, `+0x214` type, `+0x218` = 1
  (has a loop), `+0x21C` = 1 (dirty). So the thunk builds that 9-byte record on its stack and passes `r1` = 0;
  §3's « with the region's `[LS, LE)` » was short of the shape.
- **`FUN_0807775C(meta**, start, length)`** sets `+0x228` start, `+0x22C` length, `+0x21C` = 1, keeps the cues in
  `[start, start + length)` rebased by − start (a cue AT the crop's end is dropped, half-open) and **rebases the loop
  by − start**. LS 300 000, LE 700 000, F 4 800 → crop `(295 200, 404 800)`, loop `[4 800, 404 800)`: `[F, F + LE −
  LS)` with its end at the cut file's end, as §3 planned. LE at the file's end (1 M) gives `[4 800, 704 800)`, same
  rule. F 0 gives `[0, 400 000)`.
- **Loop Start < F has to clamp** (*design*, from the run): with LS 4 000 and F 4 800 there is no `LS − F`; the crop
  that starts at 0 keeps the loop at `[4 000, 700 000)`. So the patch crops from `LS − min(F, LS)` and Loop Start
  := `min(F, LS)` after the reload; the task's « `[Loop Start − F, Loop End)` » reads with that `F`.
- **What reaches the card's chunks.** `FUN_08072A40` (the disk copy, static) reads the crop at `+0x228`/`+0x22C`
  (length 0 = the whole asset), streams the audio in `0xC000`-byte blocks, then hands the meta to `FUN_0807723c`,
  which writes `acid` (24 B), `smpl` (36 B + 24 B per loop), `cue ` and a 7-byte chunk through `f_write`
  (`0x08086a06`; `f_lseek` `0x08086d96`). Run with those two stubbed on the meta the crop left: `smpl` loop 0 =
  `{type 0, start 4 800, end 404 800}` (LE 1 M: `end 704 800`), the cue at `204 800`. So **`dwEnd` goes out as the
  cut file's frame count**, the exclusive end, verbatim from `+0x210` (x3's « written verbatim, read back
  verbatim »): a fresh load would set Loop End := the file's end, which is the region's end.
- The audio bytes `FUN_08072A40` copies: §7.

## 7. ✓ The disk copy — `FUN_08072A40` under Unicorn, FatFs served from memory (22/10, turn 3)

Run on the stock image: the meta as §6 leaves it (smpl helper, then the crop `(LS − min(F, LS), LE − that)`), one
asset record (`+0x170` stride behind host `+0x4348`, index table `+0x434C`): `+4` its `FIL`, `+8` data offset 44,
`+0x10` data bytes, `+0x18..+0x26` fmt (PCM, 2 ch, 48 k, 6 B/frame, 24 bit), `+0x28` open, `+0x5C` its path. A
60 000-frame source whose frame *i* holds *i*. Stubbed by address: `f_open` `0x08086534`, `f_read` `0x08086866`,
`f_write` `0x08086a06`, `f_lseek` `0x08086d96` (64-bit offset in `r2:r3`), `f_close` `0x08086d76`, and the five calls
below; the header buffer is the word at `DAT_0807697c` (`0x24015CE0`: null = no header written).

- **The bytes are `[LS − F, LE)`, frame for frame.** LS 30 000, LE 50 000, F 4 800: the source is sought to
  `44 + 25 200 × 6`, then 24 800 frames in `0xC000`-byte blocks, equal to source frames `[25 200, 50 000)`. Also
  equal on the unaligned branch (LS 12 345, LE 50 001: a start whose byte offset is 2 mod 4 goes through the
  `memmove` path), with LE at the file's end, and with the clamp (LS 4 000 < F: `[0, 50 000)`, loop `[4 000, …)`).
- **The file on the card**: a `0x200`-byte header (`fmt `, `JUNK` 460, data at `0x200`; `FUN_08076874`, rewritten at
  close), the audio, then `smpl` (no `acid`, no `cue `: this meta had neither): loop 0 `{type 0, 4 800, 24 800}`,
  so `dwEnd` = the cut's frame count, as §6.
- **Trim onto its own file goes through a temp file.** When the request's path equals the asset's (`FUN_080c8b48`), the
  copy opens **`-WRITETEMP-.WAV`** (`DAT_08072d78`) with mode 10, and after the close calls `FUN_08072898(host,
  asset)` (the source asset's release, *inferred*: it walks the voices on that asset), `FUN_08042e30(fs, path)`
  then `FUN_08042e24(fs, temp, path)` (read as unlink and rename; stubbed, not run), then `FUN_0809151c(…, path)`.
  Another path: no temp, no release, no rename. It posts `0x1C` (progress, per cent) after each block and `0x1D` at
  the end, on the ring at host `+0x7C50`.
- **The request is queued, and it takes the meta with it** (*inferred*, `FUN_080712C8`): `FUN_0807744c(host +
  0x8F74, meta)` at the request, then a type-`0xB` entry on the ring at host `+0x5808` (580 × 16 B, count
  `+0x7C4C`) and a signal (`FUN_08088402`). So the thunk at `0x080A0FD0` writes the loop and the crop before the
  meta is handed over, and the copy runs later, in the disk task.

What follows for the patch (*design*): the stock path already does the in-place overwrite and the source release; a
Clip pad that is playing loses its file under the copy's `FUN_08072898` the way a Sample pad does (the sub-step ②
case « a trim under a playing pad »). And the reload reads the new file, *inferred*: the load `0x080A0FE0` asks for
(`FUN_0804c310` → `FUN_08070db0`, type `8 − 1` = 7) goes on the same ring, `+0x5808` / `+0x7C4C`, of the same host
(`DAT_080a10b8` = `DAT_080a0cf0` = `0x2400A9C0`) right after the `0xB`, so in ring order it runs after the rename.
§5 item 3's run proves it with the rest of the reload.

## 8. The menu's enables ✓ and the task that runs the Trim (22/10, turn 4)

**The enables, case `0x127` under Unicorn** (bare `Uc` on the stock image as §6; browser object in RAM, the message
`{u16 2, …, +12: u16 0x127}`; stubbed by address: the cell-param getter `FUN_08099504` (`0xEA` and `0x8B` from the
case), the path builders `FUN_0804290c` / `FUN_08099d1c`, `FUN_080bd566` recorded, `FUN_080bd24c` / `FUN_080a3e00`
null; stock's compare `FUN_080c8b48` runs). The case reads only `0xEA` then `0x8B`, nothing else of the pad. The
last word on each item, Pad Mode 0–3 × MultiSam 0/1 × own file or another:

| Pad Mode | `0xEA` | own file | Trim `0x124` (`0x080B3620`) | Save `0x123` (`0x080B35F6`) | Save As `0x122` |
|---|---|---|---|---|---|
| 0 Sample | 0 | yes | **1** | 1 | 1 |
| 0 Sample | 0 | no | 0 | 0 | 1 |
| 1 Clip, 2, 3 | 0 | yes / no | **0** | own file | 1 |
| any | 1 | yes / no | 0 | own file | 0 |

- So on stock a Clip pad never gets Trim, **and neither does mode 3**: §3's « mode 0 or 3 » is the smpl/crop branch
  inside `FUN_080A0DD4`, not the menu. The thunk at `0x080B3620` keeps stock's `on` and ORs the Clip case in.
- Stock quirk, kept: Save's second enable is « own file » alone; it overrides the first, so MultiSam 1 + own file
  leaves Save on.
- Case `0x127` has no mode gate before the enables (all four modes reach them in the run). Whether a Clip pad's page
  opens the browser is a UI path this run does not take: the patch's test drives it, #t-041 sees it.

**The task, a static read of the call chain** (*inferred*, not run; stronger than §4's): `FUN_080A2258`'s only caller
is `FUN_0808b654`, slot 2 of the vtable at `0x080EAF4C` (its pointer at `0x080EAF54`; the base vtable `0x080EAF38`
has the same three slots). That method calls `FUN_080A2258(app)` once, **then** drains the UI queue
(`FUN_08097aae`) into the view stack at `+0x280`: all 27 calls of `FUN_080ab570` sit in it. `FUN_080ab570` takes the
current view (`+0x34`) to `FUN_080aed32`, its slot `+0x34`; a view's handler passes the message on to its focused
child (`+0x2c`) through `FUN_080aed14`, which calls the child's slot `+0x30` (254 call sites, the views'). The browser
vtable (`0x080F0E10`, constructor `0x080B3D00`) has `FUN_080B3194` at `+0x30` (`0x080F0E40`). Case `0x124` opens the
« Trim and Save? » child (`browser + 0x20E0`) with the reply id 300 at `+0x2250`; message 300 is the branch that calls
`FUN_080A0DD4(…, 1)` at `0x080B38B4`.

What follows for the patch (*design*): the Trim and the host-message pass run inside **one call** of the same method,
the pass first. The `0x1B` that would read the reload's fresh byte is posted by the loader task and read only by a
later `FUN_080A2258` pass, so clearing the byte right after `0x080A0FE0` returns, in the same drain, comes first by
construction. Only the reload itself (§5 item 3) is still owed to a run.

## 9. ✓ The `0xE` handler on the trim's own store (22/10, turn 5)

**Run** (bare `Uc` as §6): stock `FUN_080A121C(app, asset, frames, 0)` whole, with stock's store getter `FUN_08093E9C`
and setter `FUN_08093ECC` running for real on a store built in RAM (`+4` → entries `{u16 id; u16; i32 value}`,
`+0xA` = count). Stubbed by address: the cell finder `FUN_0809A9C4` (row 1, col 2), the store lookup `FUN_08098D0C`,
the engine post `FUN_0804C59C` and the UI post `FUN_080B5758` (both recorded), `FUN_080A10C4` (recorded, never hit).
The store is a Clip pad right after `FUN_080A0AC8` (x3 t13: `0x8f`, `0x90`, `0x91` := 0, `0x92` and `0x8e` kept),
then the patch's write `0x91` := F. LS 24000, LE 72000, F 4800, so the cut file has 52800 frames.

| store before | frames | store after | posted to the engine |
|---|---|---|---|
| patched: `0x91` = F, Length 0 | 52800 | only `0x90` and `0x92` := 52800 | `0x8f` 0, `0x90` 52800, **`0x91` 4800**, `0x92` 52800 |
| stock: `0x91` = 0, Length 0 | 52800 | the same | `0x91` 0 |
| Length not 0 (30000) | 52800 | nothing | the store as it is |
| any | 0 | nothing, nothing posted | — |

Pad Mode `0x8b`, Loop Mode `0x8e`, Beat Count `0xd2`, the Clip Window rows `0x1C8..0x1CB`, Loop Fade `0xFA` and three
sentinels were not touched. Both cases post UI messages `0x67` then `0x66`. `+0x20/+0x24` := frames.

The disassembly agrees: the handler's only store writes are `+0x20/+0x24` (`0x080A12D0`) and, when the getter
returns Length 0, `0x90` and `0x92` (`0x080A13A0`, `0x080A13AA`). It reads `0x91` (`0x080A132E`) and posts it
(`0x080A133E`). So the patch writes Loop Start := F into the store next to the fresh-byte clear, and the next
`0xE` sends it to the engine with Loop End = the cut length. The loop then plays `[F, end)`.

**What closes item 3.** The links are each run on stock, in three runs and not as one chain:

- the load `FUN_080A0AC8` (x3 t13);
- the patch's two writes (fresh byte 0, `0x91` := F), which are plain stores;
- this `0xE`;
- the non-fresh `0x1B` on an `acid` + `smpl` file (x3 t6: only Root and an Auto Beat Count are written).

The patch's own test runs the whole chain on the built firmware.
