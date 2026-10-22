# X4 — stock's Trim on a Clip pad (blackbox#t-040)

Stock 3.1.9. Marks as in the other notes: ✓ = run under Unicorn, *inferred* = a static read (Ghidra 12.1.4 on a
/tmp copy of `/srv/dev/firmware/ghidra`), *design* = a choice. Plan of record: hub `blackbox` notes
`2026-10-22-t-031-close.md` (rev 1, ratified 22/10).

**Status (22/10, turn 3): the static half, plus §6 ✓ (the meta's loop and crop) and §7 ✓ (the disk copy's bytes).** The chain
below is read, its hook sites named. Still owed before the patch leans on it, by a Unicorn run (FatFs served from
memory): the rest of §5's list.

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

1. A Clip pad's File menu reaches case `0x127` (the browser opened from a Clip pad), and `0x080B3620`'s `on` for
   mode 1 is 0 on stock.
2. ✓ *(§6 the meta and its chunks, §7 the audio bytes)* `FUN_080A0DD4` on a Clip pad with the meta patched at `0x080A0FD0`: the bytes the disk copy writes (FatFs served
   from memory) are `[LS − F, LE)` and the `smpl` loop reads back `[F, end)` — `dwEnd` as written (x3: `0x92` is
   written verbatim, read back verbatim).
3. The reload with the fresh byte cleared after `0x080A0FE0`: Quant, Sync, Launch, Loop Mode, Beat Count kept;
   `0x91` where the patch put it after `0xE` and `0x1B`.
4. That `FUN_080B3194` runs in the GUI task, as `FUN_080A2258` does (§4): a hook at `0x080B38B4` that records the
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
