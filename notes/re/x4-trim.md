# X4 — stock's Trim on a Clip pad (blackbox#t-040)

Stock 3.1.9. Marks as in the other notes: ✓ = run under Unicorn, *inferred* = a static read (Ghidra 12.1.4 on a
/tmp copy of `/srv/dev/firmware/ghidra`), *design* = a choice. Plan of record: hub `blackbox` notes
`2026-10-22-t-031-close.md` (rev 1, ratified 22/10).

**Status (22/10, turn 1): the static half.** The chain below is read, its hook sites named. Still owed before the
patch leans on it, by a Unicorn run (FatFs served from memory): §5's list.

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
redirect `0x080A0FD0` to a bank-1 thunk that, when a Clip trim is pending, calls `FUN_08077738` with the region's
`[LS, LE)` and `FUN_0807775C(meta, LS − F, LE − LS + F)`, then tail-calls stock's request. The crop moves the loop
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
2. `FUN_080A0DD4` on a Clip pad with the meta patched at `0x080A0FD0`: the bytes the disk copy writes (FatFs served
   from memory) are `[LS − F, LE)` and the `smpl` loop reads back `[F, end)` — `dwEnd` as written (x3: `0x92` is
   written verbatim, read back verbatim).
3. The reload with the fresh byte cleared after `0x080A0FE0`: Quant, Sync, Launch, Loop Mode, Beat Count kept;
   `0x91` where the patch put it after `0xE` and `0x1B`.
4. That `FUN_080B3194` runs in the GUI task, as `FUN_080A2258` does (§4): a hook at `0x080B38B4` that records the
   task, or the thread-create calls in `main` (README's open question 17).
