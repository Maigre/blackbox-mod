# Spike: moving a whole module to bank 2 by tool (`bench/b2split.py`)

Hub task blackbox#t-057, 2026-11-12, on pristine JOEBOX 2 (upstream `main` `da84b1b`), branch
`wip/blackbox-t-057`. The question: can a module move from bank 1 to bank 2 with **no edit to its source**? The tool
would generate bank-1 stubs that call the bank-2 body while `b2_live()` holds, and fall back to stock otherwise. The
answer is a go or no-go, with numbers, and a list of what a hand still has to write.

## Verdict: go, as a fork tool with a short declaration per module

- **ChopShop** (`chop.c` + `chopmode.c`) moves by tool with its two files untouched. A declaration of 7 names and 2
  values, and no C, frees **3,583 B** of bank 1, against about **4,004 B** for the hand split.
- With one hand-written fallback of 25 lines of C (148 B, in `bench/`), it frees **3,957 B**, the hand split's figure
  within about 1 %.
- A second module of another shape, **note repeat** (`repeat.c`: an audio-task tick every block, three stock call
  sites, a UI button), moves whole with **two declared return values**. It frees **1,497 B** of its 1,733.
- Both modules together, with no C written by hand: bank 1 goes from 1,067 B free to **6,054 B** free.
- Nothing is proven on a unit yet. The proofs here come from Unicorn and the linker (see "Not proven").

## What the tool does

`python3 bench/b2split.py chop chopmode --decl bench/splits/chopshop.py` runs upstream's `./build.sh` as it stands.
It only puts a stand-in for `arm-none-eabi-gcc` on the PATH, which records how each moved module is compiled and takes
over the final link (the one given `-T out/cave.ld`). At that link the tool does the following.

1. **Compiles each module again** with the build's own flags plus `-ffunction-sections -fdata-sections -fno-ipa-ra`,
   then splits that one object into two copies, chosen section by section over the relocation graph.
   - **Bank 2:** every function, renamed `<name>__b2`, plus what it reaches (statics, strings, tables).
   - **Bank 1:** what is declared `KEEP`, data that stock or the cave reads, and what those reach. Calls from this
     copy into moved functions land on the stubs: the moved names are weakened here, so the stub's definition wins.
2. **Reads the patch sets.** It evaluates `patches/*.py` against stand-in symbols to learn every stock site that
   reaches a module symbol. For each site it records what stock had there: the callee of a `bl` or `b.w`, or the old
   word of a vtable or data pointer.
3. **Writes one stub per entry.** A stub is `mov.w ip, #k; b.w b2s_dispatch` plus a pair of words: body, fallback.
   The shared dispatcher saves r0–r3, ip and lr, calls `b2_live()`, restores them, and tail-jumps. Live, it goes to
   the body. Otherwise it goes to the fallback: the stock callee the patch replaced, the old vtable word, a declared
   value, or a hand-written function. Stack arguments, the return address and the return value pass through untouched.
   Entries with float or double arguments go through a second dispatcher that also saves d0–d7. The tool reads the
   arguments from the definition.
4. **Handles bank 2's calls back into the cave.** Bank 2 may not branch into the cave (`test_bank2.py`). So each cave
   callee gets a 14-byte veneer in bank 2 that jumps through a table in bank 1 (`b2s_vec`). The dispatcher writes the
   table's address into one word of patch RAM, `B2S_VEC` at `0x2405FF5C`, before every body. Bank 2 then holds no
   branch and no literal into the cave, and **its bytes do not depend on where the cave's code lands** (see Proofs).
5. **Handles the module's data.**
   - State: the cave already discards `.data`/`.bss`, so a module keeps its state at fixed addresses or behind a cave
     call (`stretch_bank()`, `master_block()`), and those calls go through the veneers. The tool refuses a module
     with writable data.
   - Constants stock reads: a symbol a data patch points stock at stays in bank 1, found automatically. This is
     `chop_mode_names`, the 7-entry Mode list, with the strings it points to.
   - Name tables handed to stock by kept code stay with that code (`type_names`, `tempo_names` with `chop_register`).
6. **Writes `out/b2split/cave.ld`** from `out/cave.ld` (explicit section lists, the copies kept out of the cave's
   wildcard) and links. `build.sh` then finishes as usual: header, sum, `b2_expect_sum`, `BBEXTRA.BIN`.

The tool refuses to build, and says why, in these cases:
- a reached entry returns a value and replaced no stock call, with no declared fallback;
- the sites of one entry replaced different stock callees, or replaced bytes that were not a call (clipsel's `sel_setup`
  trampoline would be one; clipsel was not tried);
- the moved code reads cave **data**;
- a `KEEP` name that no module defines;
- a variadic entry;
- a bank-2 object that calls a moved function.

`--verify` (run after `patch.py`) decodes bank 2 function by function and runs every stub with bank 2 live and blank.
`--absent test_x.py` runs any suite with bank 2 blank. `--run ./check.sh` runs the full check split the same way.

## Numbers (bank 1 = `.cave`, 57,736 B; built on this box, arm-gnu 14.2)

| build | `.cave` | free | freed |
|---|---|---|---|
| JOEBOX 2 as is | 56,669 | 1,067 | — |
| ChopShop, tool only, stubs for what bank 1 reaches | 53,086 | 4,650 | **3,583** |
| ChopShop, tool only, a stub for every global (what the suites call) | 53,242 | 4,494 | 3,427 |
| ChopShop, `chop_set` moved with a hand fallback, reached stubs | 52,712 | 5,024 | **3,957** |
| ChopShop, same, every global | 52,904 | 4,832 | 3,765 |
| hand split (blackbox#t-052, on the fork's merged build: 3,641 B over → 363 B free) | — | — | ≈ 4,004 |
| note repeat (`repeat.c`), nothing kept | 55,172 | 2,564 | **1,497** |
| ChopShop (tool only, every global) + note repeat | 51,682 | **6,054** | 4,987 |

- The ceiling for ChopShop is 4,848 B: `chop.o` (3,362 B) and `chopmode.o` (1,486 B) in bank 1 today, text plus
  constants plus strings.
- The hand split was measured on another base (the fork's merge), so its 4,004 B is comparable within a few tens of
  bytes, not to the byte. `chop.o` is 3,362 B on both bases.

What bank 1 still holds for ChopShop:

| | tool only, reached | hand fallback, reached |
|---|---|---|
| kept whole (`KEEP` + Mode-list data + strings) | 1,064 | 566 |
| stubs: 8 B of code + 8 B of pair each | 7 × 16 = 112 | 6 × 16 = 96 |
| dispatcher (one, no float entries) | 52 | 52 |
| vector table (3 cave callees: `stretch_bank`, `sel_ask_pad`, `sel_take_pad`) | 12 | 12 |
| declared return values | 22 | 18 |
| hand-written fallback | — | 148 |

**The cost in bank-1 bytes per stub is 16 B**: `mov.w`, `b.w` and two words. On top of that come a fixed 52 B for
the dispatcher (60 B more for a second one if any entry takes float arguments), 4 B per cave callee and a few bytes per
declared value. Bank 2 pays a 14 B veneer per cave callee. The "every global" mode costs 16 B per extra stub, plus the
float dispatcher here (`chop_beats` and `chop_onto_hits` take floats). It only serves the suites, which call internal
functions by name.

Run time: the split build runs `build.sh` plus one more compile of each module. One run each on this box, shared
with four other jobs: plain `./build.sh` 21.4 s, the split of both modules 24.0 s.

## What works by tool, and what a hand still writes

By tool, with nothing declared:
- the stock-site fallbacks: `chop_pages`, `chop_header_post`, `chop_view_tick` (a vtable word), `repeat_pad_down/up`,
  `repeat_rec_tick`;
- void entries the cave calls: `chop_poll`, `repeat_tick` on the audio task every block, `repeat_hold`,
  `repeat_next_div`;
- the Mode-list data that stock reads;
- the three ChopShop and three note-repeat calls back into the cave;
- the moved code's static helpers, strings and tables.

Declared, because the tool cannot know them. A wrong declaration still links; it shows only with bank 2 absent, which
`--absent` and `--verify` check.
1. **Code that runs before bank 2 is checked.** `b2_live()` answers 0 until the meter's first audio block, so a stub
   called while the app is being built silently takes its fallback. These are kept: `chop_register` (the param table),
   `chop_defaults` (the store entry), and `chop_header_mode` (a WAV header read at project load must keep a ChopShop
   pad a Slicer).
2. **Invariants that must hold with or without bank 2:** `chop_invariant` (the flag only on a Slicer).
3. **A data patch that changes what stock's fallback means.** The Mode list has 7 entries whatever bank 2 does, so
   with bank 2 off stock would read position 4 as Granular. The fix is to keep `chop_set` and the two popup highlights
   whole (tool only, +498 B), or to write `chop_set`'s fallback by hand: `bench/splits/chopshop_fallback.c`, list
   position to stored mode, the flag, and the Tempo code cleared on entering or leaving ChopShop. It is 25 lines and
   148 B: this is the one function a hand writes.
4. **Return values of reached entries that replaced no stock call.** The tool refuses to build until they are named:
   `chop_roll_text` → `"[:.:]"`, `chop_retempo` → 0, `repeat_div_name` → `"---"`, `repeat_held` → 0.

The ChopShop declaration is 7 `KEEP` names and 2 fallbacks (`bench/splits/chopshop.py`); note repeat's is 2 fallbacks.
The hand split was sized at about 800 lines and a new bank-2 table (blackbox#t-052, turn 3's estimate), plus suite
edits. **When JOEBOX
changes these files, the declaration fails loudly**: a `KEEP` name that is gone, or a new reached non-void entry, stops
the build. A new boot-time or invariant function does not stop it.

## Bank 2 absent

- `--verify` with bank 2 erased: every one of the 13 ChopShop stubs and the 8 note-repeat stubs reaches its fallback
  (the stock callee hit, or the declared value returned), and **not one instruction runs in bank 2**. With bank 2
  live, each reaches its body and `B2S_VEC` holds the table.
- test_chopmode, tool only, bank 2 blank: 36/39. The three failures are exactly what only bank 2 adds: the Chop and
  Roll rows on the POS page, their values, and the Roll text. The Mode list, the highlights, the WAV-header mode and
  the invariant all pass.
- test_chopmode, hand fallback, bank 2 blank: 26/39. It also loses what the bank-2 `chop_set` did: the Gate, Sync and
  Cyclic defaults when ChopShop is entered, the Chop row's clamp, the Tempo row, chop requests. The mapping and the
  Tempo-code clear pass.
- test_chop, bank 2 blank: stops at its first check (`chop_beats` answers 0 points, its default); it is not written
  for a no-op.
- test_repeat, bank 2 blank: 10/22, no fault. Note repeat is off, the pads play as stock, and the recorder stamps
  stock's raw tick.
- **What a unit without the payload loses:** ChopShop's chops and rows (the mode still shows and stores), and note
  repeat (the button reads `---`). Today on JOEBOX 2 both work without bank 2.

## Proofs run

- **The full check, on both modules split together** (`bench/splits/both.py`, ChopShop tool only, a stub for every
  global, plus note repeat; `.cave` 51,682 B): `python3 bench/b2split.py --decl bench/splits/both.py --run ./check.sh`
  → **54 suites, 3 failed, 7 failing checks**, 54 minutes on this box. Each of the three is explained below and none
  is a fault:
  - test_machine: the four known S950 Lo misses (no FMA on this CPU);
  - test_bank2: the `sdiv` false positive;
  - test_solo: the two division-label checks.

  Every other suite passes, test_savexml (a whole emulated preset save) among them. On a pristine JOEBOX 2 build here,
  test_solo is 69/69, test_bank2 23/23 and test_chopmode 39/39.
- **Suites, with bank 2 live:**
  - ChopShop, tool only: test_chop 66/66, test_chopmode 39/39, test_theme 20/20.
  - Hand-fallback variant: test_chop 66/66, test_theme 20/20, test_chopmode 32/39. The 7 failures are the suite
    stubbing `chop_request` by name, while the moved `chop_set` now calls `chop_request__b2` inside bank 2. A scratch
    copy that also stubs `chop_request__b2` passes 39/39 (a one-line change to the test).
  - Note repeat: test_repeat 22/22, test_bank2 23/23, test_groove 28/28.
  - test_solo 67/69 (it ran with note repeat in bank 2). Its own emulator loads no bank 2, so the division label reads
    `---` where it expects `1/16`.
- **test_bank2 with ChopShop in bank 2: 22/23.** The failure is a false positive. Its scan steps two bytes at a time
  through bank 2 and read the second half of an `sdiv` in `chop_roll_text__b2` (`fb91 f6f5` at `0x08118522`) as a BL.
  The tool's veneers first tripped the same scan (`ldr.w pc, …` ends in `0xF00k`) and now use `bx ip`. Decoding bank 2
  one function at a time (`--verify`) finds no branch out of bank 2 and no literal into the cave.
- **Bank 2's bytes do not depend on the cave's layout.**
  - Keeping one more function in bank 1 moves `sel_ask_pad`, `sel_take_pad` and `stretch_bank` by 0x38, and
    `out/bank2.bin` stays byte for byte the same.
  - A `RELEASE=1` link (a different cave) gives the same `bank2.bin` too (101,696 B).
  - So a bank-1-only change needs no new `BBEXTRA.BIN`. That is what test_bank2's rule protects.
- **The veneers:** each lands on its cave function with `B2S_VEC` set (`--verify`).

## Findings to carry

- **test_bank2.py's two-byte scan gives false positives on general code.** DSP code happened not to trip it; ChopShop
  does, at the first `sdiv`. Before modules move for real, the scan should confirm each candidate by decoding from its
  function's start, as `--verify` does. That is a change to upstream's rule test.
- **Suites that stub an internal function by name miss the calls that stay in bank 2** (test_chopmode's
  `chop_request`).
- **The pairing gate is per call.** Every call through a stub runs `b2_live()` (the magic check and the cached
  verdict) and a store to `B2S_VEC`. Under Unicorn this is **38 instructions** from the stub to the body (40 when
  d0–d7 are saved), measured on `repeat_tick`, `chop_poll` and `chop_beats`. For `repeat_tick` that is once per audio
  block. The first call of a boot runs the pairing scan (386,650 emulated instructions), which `b2_live()` does once
  per boot for every bank-2 user anyway. **Cycles on the core were not measured** (`vpush`/`vpop` of 8 registers are
  one instruction each but many cycles).
- **The dispatcher clobbers the flags and ip.** That is legal under AAPCS, and every C caller is fine. An assembly
  thunk that keeps flags or ip across a call to a moved entry would not be (no such case in ChopShop or note repeat).
- **`B2_ID` does not cover the moved sources.** `build.sh` hashes `BANK2_SRCS`, so editing `chop.c` keeps the id.
  `b2_expect_sum` (the linked payload's sum) still pairs exactly, and the card loader checks it, so a stale payload is
  refused. The id alone is now a weaker label. The fork's integration should add the moved files to the hash.
- **`B2S_VEC` takes one word of the 12 unclaimed bytes of patch RAM** (`0x2405FF54..0x2405FF5F`, notes
  re/x2-sdram-and-memory.md). The alternative is a table pinned at a fixed cave address, which costs a literal into
  the cave in bank 2 and an exception to test_bank2's rule.
- **Bank-2 strings handed to stock** (`repeat_div_name` to a label, `chop_roll_text` to a text setter) are only valid
  while bank 2 is live. It does not go away within a boot (the card loader restarts the unit).
- **Not tried, and likely to need more:**
  - C++ modules (`munchi.cpp`: the stand-in only records `.c` compiles);
  - entries reached from interrupt context (`usbdev.c`: the first `b2_live()` may run the whole pairing scan there);
  - modules whose sites are raw-byte trampolines (the tool refuses them);
  - modules reading cave data (the tool refuses them).

## Not proven

- Nothing on a unit. In particular: the dispatcher on the real core, the `B2S_VEC` word in patch RAM, ChopShop and note
  repeat heard as on JOEBOX 2 with the payload, and stock behaviour without it.
- The hand split was not rebuilt here (its branch lives on dev37). The comparison stands on blackbox#t-052's figure.
- The gate's cost in cycles on the core (its instruction count is above).
- No full `./check.sh` ran on the hand-fallback variant or on note repeat alone. The one full check ran on both
  modules together (Proofs, above).

## How to run

```sh
. /srv/dev/bin/bb-env
python3 bench/b2split.py --decl bench/splits/chopshop.py [--stubs reached]   # or chopshop_hand.py, repeat.py, both.py
python3 patch.py solo slice duck chord cond filter cpu od comp seqfix fx2 munchi master fault cave
python3 bench/b2split.py --verify
python3 bench/b2split.py --absent test_chopmode.py
python3 bench/b2split.py --decl bench/splits/both.py --run ./check.sh
```

`out/b2split/report.json` lists, for each module:
- what moved, and what bank 1 reaches and from where;
- each stub's fallback and why;
- the veneers;
- the bytes on each side.
