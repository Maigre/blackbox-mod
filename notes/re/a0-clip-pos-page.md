# A0 — the Clip Pos page: which ids, which lists

Stock 3.1.9 (`BLACKBOX-3.1.9.bin`, sha256 `281ae303…1341d`). Found 2026-10-15 (loop turn, blackbox#t-003).

## The page

Each pad mode has a table of 5 pages × 36 u16 ids (`0x48` bytes a page, `0x168` a mode). The Clip table starts at
`0x080EF948` (Main); page 1, **Pos, is `0x080EF990`**, and the class-0x4C copy's Pos is `0x080EF288` (copy base
`0x080EF240`). Both copies hold the same four ids, in this order, followed by 32 zero slots:

| row | id | kind | label | xml | values |
|---|---|---|---|---|---|
| 1 | `0x8d` | num, type 4 (Off/On, like Reverse `0x6c`) | `Loop Mode:` | `loopmode` | Off / On |
| 2 | `0xd2` | list, 513 entries | `Beat Count:` | `beatcount` | `Auto`, `1` … `512` (names `0x080EB810`) |
| 3 | `0x47` | list, 9 entries | `Quant Size:` | `quantsize` | `8 bars`, `4 bars`, `2 bars`, `1 bar`, `1/2`, `1/4`, `1/8`, `1/16`, `None` (names `0x080ECB08`) |
| 4 | `0x94` | list, 7 entries | `Sync:` | `synctype` | `Slice`, `1 bar`, `1/2`, `1/4`, `1/8`, `1/16`, `None` (names `0x080EC848`) |

So the three Clip Window rows (`0x1c8..0x1ca`) go into slots 5–7 of both copies without moving a stock row.

For comparison, the Sample Pos page (`0x080EFC60`, copy `0x080EF3F0`) is `0x8e` Loop Mode (list `None` / `Forward` /
`Bidirect`, xml `loopmodes`), `0xfa` Loop Fade (`loopfadeamt`), `0x6c` Reverse, `0x8f` Start (`samstart`), `0x90`
Length (`samlen`), `0x91` Loop Start (`loopstart`), `0x92` Loop End (`loopend`); `0x8f..0x92` are type `0xd` (sample
position). Clip mode's Loop Mode is a different id (`0x8d`, on/off) from Sample mode's (`0x8e`, three-way), under
the same label.

## The beat tables beside the lists

Each list's name table sits right after a float table of the same length, in beats:

- Clip Quant Size `0x47`: `0x080ECAE4` = 32, 16, 8, 4, 2, 1, 0.5, 0.25, 0 (the `None` entry is 0). Rec Quant `0x98`
  has an identical pair at `0x080EC728` / `0x080EC74C`.
- Sync `0x94`: `0x080EC82C` = 1024 (`Slice`, a sentinel), 4, 2, 1, 0.5, 0.25, 0 (`None`).
- The 13-entry pair `0x080ECC70` (floats: 8, 4, 2, 4/3, 1, 2/3, 0.5, 1/3, 0.25, 1/6, 0.125, 1/12, 0.0625) / `0x080ECCA4`
  (`2 bars` … `1/64`, with triplets) belongs to **`0x45` Quant Size (`quantsize`), `0x46` Quant Size
  (`quantsizeseq`) and `0x48` Length (`steplen`)** — not to the Clip page. `0x45` is on none of the nine pad-mode
  tables dumped here (Slicer, Clip, Multisample, Sample, their 0x4C copies, Granular); where it is shown is not
  settled.

That the float table is the one the engine reads for each list is inferred from position and length (each one ends
right where its name table starts and has one entry per name); A1/A2 see the consumer.

## Open points this raises

- **Two ids share the xml name `quantsize`**: `0x45` (13 entries) and the Clip's `0x47` (9 entries). What a preset
  save/load does with the second one is unknown — the Clip Window rows must not repeat the pattern (P2's test checks
  that our three xml names are distinct, as `test_insert.py` does for its own).
- The engine-side meaning of the Clip Quant (launch quantization) vs Sync (realign step) and which pad fields they
  write is A1's.

## Ids `0x1c8..0x1cf` are free

- The stock pad-parameter registrar is **`FUN_0808c158`** (one caller, `0x08097814`; allocates a `0x36b0`-byte table,
  then calls `fw_register_list 0x0808C0D8` / `fw_register_num 0x0808C12C` per id). Run whole, it registers **267 ids,
  the highest `0x19b`**: nothing in `0x19c..0x1ff`.
- No stock instruction loads `0x1c8..0x1cf` as an id. The only immediates in that range are struct offsets and stack
  frame sizes, plus `#0x1cc` as an object size (`0x08046A62` delete, `0x08046C52` new, `0x08052FE2` allocator
  `0x0804436c`) and a struct field (`0x080768E2`). The same scan finds `movw` loads of the ids JOEBOX already
  knows are special (`0x1b5` at four sites, `0x1e5` at six including `SetCellParam 0x0809FA50`), so it would have
  shown one.

## How this was checked

- The page ids: read straight from the image at both page addresses (plus every mode's five pages, to place them).
- The labels, xml names, kinds and lists: **`FUN_0808c158` run whole under Unicorn** (stock image only; allocator
  `0x0804436c` and the two register functions stubbed, recording their arguments as `test_insert.py` does) — it
  returns normally after 267 registrations; the four Clip Pos rows are the registrations at `0x0808CF46` (`0x8d`),
  `0x0808D708` (`0xd2`), `0x0808C74E` (`0x47`) and `0x0808D104` (`0x94`).
- The float tables: read from the image next to each name table.
- The free ids: an operand scan of the analysed Ghidra project for the values `0x1c8..0x1cf`, with `0x1b5` / `0x1e5`
  as controls.
- P2's `test_clipwin.py` turns this into checks: both Pos copies read `0x8d, 0xd2, 0x47, 0x94` + ours, and the stock
  registrar run under the suite's own harness still registers nothing at `0x1c8..0x1cf`.
