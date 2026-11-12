# Scarce resources: what each module takes, and where two trees collide

The JOEBOX 2 merge (hub #t-047, #t-052) met its clashes one loop turn at a time: parameter ids, call sites, a page
slot, the pad store, the SDRAM block, bank 1. Each was found by a build or a suite failing. `bench/resources.py`
finds them by reading the two trees, before a merge is tried; `test_resources.py` keeps one tree free of them.

## At a new upstream release

```sh
. /srv/dev/bin/bb-env                       # the toolchain: compiler probes, and --build
git fetch upstream
python3 bench/resources.py report . upstream/main --md /tmp/joebox.md --json /tmp/joebox.json
# with the flash estimate (builds three copies in temporary folders, about 35 s):
python3 bench/resources.py report . upstream/main --build --base $(git merge-base HEAD upstream/main) --md /tmp/joebox.md
```

Either side can be a folder or any ref of this repository (unpacked with `git archive` into a temporary folder;
neither tree is written). Exit status: 0 clean, 1 collisions (everything read), 2 something not read in either tree
(an id, a pointer, a patch table, a hooked store_add no tag names), whatever else it found: the console line counts
what was not read, and the markdown says so under its title. Read the "Not read" list before trusting a clean report.
`scan [TREE]` lists one tree per module, `check [TREE]` prints what `test_resources.py` refuses (and what it could not
read).

## What is scarce, and where it is read from

| resource | the limit | read from |
|---|---|---|
| parameter ids | one parameter per id in a registry of 500; one id per xml name (presets are keyed by it) | every call of a macro bound to a stock registrar (`FN(0x0808c0d8)`, `FN(0x0808c12c)`: a binding named *regist*), directly, through a helper taking the id, or through a function-like macro, its id evaluated from the file's `#define`s, enums, `for` loops and const arrays; the xml name (last argument) says which parameter it is. An id a hook only forwards (stock's own) is counted as stock's. A registrar held in a variable is said not read |
| where ids are read | a copy of an id must move with it | the calls of a binding named *setting* (`fw_setting`, `fw_setting_set`: store, id), evaluated the same way; the few computed at run time are listed apart |
| stock functions called | a call into stock lands in whatever hook the other side put on its first bytes | every macro binding a stock address with `FN()` / `B2_FN()` |
| settings-store entries | a store's cap: stock `movs r1, #0x40`, 96 since JOEBOX (`patches/duck.py`, `patches/comp.py`) | the chains behind every stock `bl store_add` (0x08093ef6) a patch table hooks: the functions reached from that hook, their `fw_store_add` calls. Which store a site fills, the cap sites and stock's own count are `resources: store` tags (below); a hooked site no tag names is a problem in-tree and "not read" in the report |
| the boot-time SDRAM block | the size `master_alloc` asks of stock's permanent allocator; our core (`master_block()`, on every unit) and tail (`master_tail()`, with a bank-2 payload only); D-030's bound, `_Static_assert(CORE_BYTES + TAIL_BYTES == 0x84900u)` | the allocation (a binding named *perm_alloc*) and master.c's accessors; every `p + NAME` or `&p[NAME]` in `src/` (NAME a macro or an enum) whose pointer `p` is traced to `master_block()` / `master_tail()`: assigned from it, a parameter its callers pass it in (the bank-2 `uint8_t *mem`), an out-parameter (`*m = master_block()`), a macro, a file static; `master_block() + NAME` too. Comments play no part. A block-like offset (`*_OFFSET`, `*_AT`) on a pointer traced to nothing, and a literal offset on the block's pointer, are said not read; what a module's own `*_mem()` accessor hands out stays inside its part. A part's size: its `STEM_BYTES`, else the smallest `sizeof(struct)` budget a `_Static_assert` gives it, else the room up to the next part. Other boot allocations (upstream's `stretch_alloc`) are listed beside it |
| backup SRAM (0x38800000, 4 KB) | ranges of two modules apart | every pointer cast (in code and macro bodies) whose operand evaluates, with the file's macros, into backup SRAM (`(struct od_bank *)BKPSRAM`, `(uint32_t *)(BKP + 0x800u)`), `.S` literals, and the `_Static_assert(ADDR + size <= END)` that bound them (ADDR a literal or a macro); a struct with no assert gets its `sizeof` from the compiler. A cast on a backup-SRAM macro with a variable offset is said not read |
| stock bytes: call sites, page slots, constants | one module per byte | each `patches/*.py` imported with a stand-in symbol table, so no build is needed: (site, stock bytes, new bytes) for every patch of a set `check.sh` applies, in its order; a BL's target read back as its symbol name. Page slots and caps are data patches like any other |
| planned hooks | a site a feature will need | `resources: wants` tags |
| flash bank 1 / bank 2 | the cave's 57,736 B (`src/cave.ld.in`) | with `--build`: `out/cave.map` of a fresh build in a temporary copy, bytes per object per bank, each input section counted up to the next one's address (a merged string section is listed at full size under every object; summing the listed sizes overcounted by 2.5..3.5 KB). The per-object bytes add up to the cave's size |

Two trees collide when: the two sides do not hold the same parameters (xml names) on an id (the row lists where
each side reads that id: those reads move with it); an xml name sits on different ids; one side reads an id it does
not register and the other side registers; stock bytes both patch hold different values in the two patched images
(a call site with two targets, a slot with two ids); a stock function one side calls through `FN()` has its first
bytes patched by the other (`binds`); a wanted site is patched by the other side; stock's entries + the union of
both sides' entries pass the cap; their SDRAM parts, at their own offsets, land on our parts or past our block; the
same part sits at different offsets (one layout or the other: the merge re-bases); the merged block (our block +
their parts that ride in no slack of ours) passes our bound; backup-SRAM ranges overlap, equal or not, unless they
share a module, a struct type or the macro naming them (code moved between files), or the other tree already holds
the pair side by side (its own check judges it); the merged cave's estimate (ours + theirs - base, per object) passes
bank 1 at its high end.

Inside one tree (`check`, `test_resources.py`), beyond one owner per thing: a module's copy of its own id under
another name (`B2_P_SLIP` for `P_SLIP`, read through `fw_setting`) must hold the value registered under the first.

### The tags

Only where nothing in the sources states a fact, in a comment of the file that describes it:

- `resources: store <name> sites=<stock store_add sites> cap=<movs sites> stock=<n>`: `patches/duck.py` (pad 59,
  the class-0x4c cell 37), `patches/comp.py` (global 41), `patches/munchi.py` (delay 8), `patches/fx2.py` (reverb 3).
  Stock's counts are the `bl 0x08093ef6` of each cell's case in FUN_08093f20 and in FUN_0809481c, counted on the
  listing (no branch inside a case); the pad's 59 is the figure `test_lfo.py` already gave.
- `resources: wants site=<addr> callee=<stock callee> by=<function>`: a site a feature not written yet will hook.
  None in the tree since the JOEBOX 2 merge: the one that stood in `patches/clipwin.py` (stage 1's capture at
  `0x080685D2`, hub #t-044) fired there, because that call is now `slice.py`'s `sel_param`. The comment in its
  place says how stage 1 takes the site (TAKES, ending in `sel_param`).
- `resources: shares at=<addr> with=<module>,<module>`: two modules on one backup-SRAM range by design. Taking
  turns: `comp.c` and `compm.c` at 0x38800400 (one compressor runs at a time; the tag is in `src/compm.c`). One
  reading the other's word: the bench kit (`src/kit_b2.c`) reads `master.c`'s block pointer and check word and
  `fault.c`'s boot count.

A module's `TAKES` (a list of site addresses, or a dict keyed by them) lets it patch a site another module patches;
a module whose stock bytes are another's new bytes (master.py on comp.py's Tools page) is a chain patch.py accepts.

## Proof: this tree (maigre d23b389 + the tool) against upstream main (JOEBOX 2, da84b1b)

The merge's clashes as met by hand (hub work/t-047.md, work/t-052.md), and what the report says. 27 collisions
(param-id 5, site 5, data 2, binds 1, wants 1, store 1, sdram 12), 6..13 s; 28 with `--build --base 66329ad`, 22..53 s
(eight cores shared with other work). The same counts the other way round; a tree against itself gives 0 collisions
(exit 2 for upstream against itself: it has no store tags, so its store sums are not read).

| clash | found | how |
|---|---|---|
| ids 0x1c8..0x1cc: TapeScam there, the Clip Window here | yes, 5 rows | `clipregion` / `tsinput` … `cliptlknob` / `tsnoise`: their ids come from a const array in master.c (`ts_num[k]`) |
| stage 3's bank-2 copies of those ids (clipwin_b2.c, t-052 turn 3, fixed in 8d7d5b8) | yes, on the id rows | the 0x1c9 row lists `clipwin_b2.c:794 (B2_P_SLIP)`, 0x1ca `:795 (B2_P_LOOPLEN)`, 0x1c8 and 0x1cb `:853` (region_rows): the reads that must move with the ids. On the merged tree with the three lines set back, `check` names B2_P_SLIP and B2_P_LOOPLEN (param-use); region_rows, a table of literals, only the report shows |
| JOEBOX 2's trampoline on stock setup (`0x08064A94` -> `sel_setup`), which our code calls | yes, 1 row | binds: `clipwin.c:145 fw_recompute calls stock 0x8064a94` against `slice.py -> sel_setup` |
| call sites 0x08064B2C, 0x08064C5A, 0x080A53B0, 0x080A582A, 0x080A5B0E | yes, 5 rows | each BL has two targets: `clipwin_*` here, `sel_*` there |
| 0x080685D2, which stage 1 wants | yes, but only through the `wants` tag | nothing of ours patches it yet (stage 1 is not written); without the tag it is missed |
| the pad store, 99 entries of 96 | yes | stock 59 + 40 (28 here, 35 there, 23 both); also cell 0x4c 77, global 81, delay 31, reverb 11, all within 96 |
| the Clip Pos page: Stretch and the Clip Window on one slot | yes, 2 rows | both copies of the page table (0x080EF998, 0x080EF290): 0x1c8 here, Stretch's 0x14c there |
| the SDRAM block: their new parts against D-030's core-first layout, past 0x84900 | yes, 12 rows | 6 parts at different offsets; 9 of their parts land, as written, on Prism, the insert bank or past our end; merged 0x95910 on either layout (t-047's figure), our core 0xc100 -> 0x1d110 (t-047's core); their stretch.c allocates another 0x58000 at boot |
| bank 1 (the trial build's wall: 4,505 B over before stage 3, 3,641 B after) | a range, 1 row | 57,610..61,359 B of 57,736: -126..+3,623 B. The low end, the three-way sum per object, fits; the high end counts munchi.o (both sides moved its engine to bank 2) as the larger side. The hand merge 88e766b (these two heads plus t-047's two small commits), built the same way: 61,377 B, +3,641, 18 B above the high end, its munchi.o 3,749 B (theirs' size, as the high end assumes). So read the high end; the low end is not a promise that it fits |

What it does not see, from the same merge:
- a hook on a call our code works behind or inside, rather than on the first bytes of a function we call: their
  `sel_block` on the call of FUN_08067fa4 (the clip / slicer pads' block, which od.c and insert.c work inside) at
  `0x08068C6A`, and JOEBOX 2's hooks inside functions `test_clipwin.py` pins (t-052 turn 7). The tool knows no
  function's extent, so no row.
- a table of literal ids inside one tree (`region_rows`): the in-tree rule follows a copy under a macro name only.
  Ids read other than through `fw_setting` (compared with `knob + KNOB_PARAM`, in `clip_knobs`) are not reads to it.
- that the store copy trusts the destination's size, so the pad's cap and the global's move together (t-052
  turn 5); each store is checked alone.
- what a collision means for the product (whose Waveform knobs, whose selection length): it says where, not which.
- sizes the sources do not state: a part with no `BYTES` and no assert claims the room up to the next part; an
  array base cast (`GLBUF`) reads as one element.
- which store a hooked `store_add` fills: the tags say it. A hook on a site no tag names is refused (in-tree) or
  left out of the sums and said not read (report); the stock switch in FUN_08093f20 that maps a cell's class to its
  case is not decoded.

On the merge branch alone (wip/blackbox-t-052, 4342733): `check` gives the comp.c / compm.c overlap at 0x38800400
(needs the `shares` tag) and its seven hooked store_add sites, which carry no tags there; TAKES (a tuple in
patches/clipwin.py, re-exported by filter.py) is read, so no site problem. `report wip/blackbox-t-052 upstream/main`:
10 collisions (the five TAKES sites, the three cap bytes 0x70 against 0x60, two SDRAM rows), merged block 0x95910 =
the branch's own; exit 2 until its stores are tagged.

With this tool on that merge (the wave of 12/11): the store tags came with it, and `check` then gave two problems,
both real. The comp.c / compm.c block: tagged `shares`. And `0x080685D2`, wanted by stage 1 and patched by
`slice.py` -> `sel_param`: the clash still ahead of us, which the hub had found by reading both trees on 11/11
(#t-044) and the tool names from one tag. With the bench kit merged it also asked for the kit's words to be
declared: its mailbox inside the Clip Window's 4 KB, and three backup-SRAM words it reads from `master.c` and
`fault.c` (`shares` tags in `src/kit_b2.c`). `check .` is at 0 problems, `test_resources.py` at 0 failed.

Checked against the code: on the built image of each tree, `test_resources.py` runs every registration and
store-defaults hook under Unicorn and compares the ids with what was read: here 78 ids in 5 hooks and 80 entries
in 6 chains; on da84b1b, in a built copy, 103 ids and 106 chain entries; every hook the same as read.
