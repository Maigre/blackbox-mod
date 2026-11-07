# Trim on a Clip pad

Hub task #t-040 (plan #t-031 rev 1). Reverse engineering: `notes/re/x4-trim.md`. Decision: D-033. **Status: dev
build, Unicorn-tested; the unit proof is hub #t-041.**

## 1. What it does on the unit

On a **Clip** pad whose **Region** plays a loop (Auto or Loop, with loop points that are not the whole file), the
browser's File menu offers **Trim**, which stock offers only on a Sample pad. Stock's « Trim and Save? » follows; on
yes the pad's own file is overwritten with `[Loop Start − F, Loop End)` and an `smpl` loop `[F, end)`, where F is Loop
Fade's pre-roll (`(Loop End − Loop Start) × Loop Fade / 1000`, at most Loop Start). The pad reloads with its rows
kept — Region, Slip, Loop Len, Fit and Loop Fade untouched — and Loop Start := F, so it plays and fades as before and a
second Trim cuts nothing more.

Trim stays off when: Region is File; the region is the whole file or empty; Loop End is past the file; the highlighted
file is not the pad's own; MultiSam is on; Pad Mode 3; or **another pad of the preset names the same file** (stock's
trim would reload that pad onto the cut file).

## 2. How it is built

`src/trim.c`, `src/trim_thunk.S`, `patches/trim.py` (imported by `patches/filter.py`, like `clipwin.py`). Three hooks,
no state between them (the cave has no `.bss`):

| site | stock call | hook |
|---|---|---|
| `0x080B3620`, FUN_080B3194 case `0x127` | the Trim enable FUN_080BD566 | `trim_menu_b` → `trim_menu`: on for such a pad, own file, MultiSam 0 |
| `0x080A0FD0`, FUN_080A0DD4 | the write request `0x0804CA88` | `trim_write_b` → `trim_write`: on a trim, smpl `{LS, LE, forward}` + crop `(LS − F, LE − LS + F)` |
| `0x080A0FE0`, FUN_080A0DD4 | the reload FUN_080A0AC8 | `trim_reload`: region read first, then fresh byte := 0 and Loop Start := F |

`trim_ok` is the one rule all three read: pad cell → store, Pad Mode 1, the bracket's `is_loop`, the file's length
from `clipwin_flen` (else Length), F as `clipwin_b2.c` computes it, and the same-file scan over stock's cells (rows
0–3 × cols 0–4, the name at store `+0x18`).

## 3. How it was tested

- `test_trim.py` (34 checks, 0.3 s): the three call sites, the menu's truth table, the same-file refusal, the save's
  loop and crop across Loop Fade and the clamp, the reload's store. Two mutants (refusal off, clamp off) fail it.
- `notes/re/x4-trim.md`: stock's disk copy run under Unicorn cutting exactly `[LS − F, LE)` (§7), the reload's `0xE`
  on the trimmed store (§9), the menu's enables (§8).

## 4. Not yet checked

A trimmed pad's render equal to the untrimmed region's with Slip and Fit on; a Trim under a playing pad; the whole
chain on the unit (hub #t-041: a real take, Loop Fade a few %, listen before and after).
