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
neither tree is written). Exit status 1 when it found a collision. `scan [TREE]` lists one tree per module,
`check [TREE]` prints what `test_resources.py` refuses.

## What is scarce, and where it is read from

| resource | the limit | read from |
|---|---|---|
| parameter ids | one parameter per id in a registry of 500; one id per xml name (presets are keyed by it) | every call of a macro bound to a stock registrar (`FN(0x0808c0d8)`, `FN(0x0808c12c)`: a binding named *regist*), its id evaluated from the file's `#define`s, enums, `for` loops and const arrays; the xml name (last argument) says which parameter it is. An id a hook only forwards (stock's own) is counted as stock's |
| settings-store entries | a store's cap: stock `movs r1, #0x40`, 96 since JOEBOX (`patches/duck.py`, `patches/comp.py`) | the chains behind every stock `bl store_add` (0x08093ef6) a patch table hooks: the functions reached from that hook, their `fw_store_add` calls. Which store a site fills, the cap sites and stock's own count are `resources: store` tags (below) |
| the boot-time SDRAM block | the size `master_alloc` asks of stock's permanent allocator; our core (`master_block()`, on every unit) and tail (`master_tail()`, with a bank-2 payload only); D-030's bound, `_Static_assert(CORE_BYTES + TAIL_BYTES == 0x84900u)` | the allocation (a binding named *perm_alloc*) and master.c's accessors; every `<block pointer> + NAME` in `src/`. A part's size: its `STEM_BYTES`, else the smallest `sizeof(struct)` budget a `_Static_assert` gives it, else the room up to the next part. Other boot allocations (upstream's `stretch_alloc`) are listed beside it |
| backup SRAM (0x38800000, 4 KB) | ranges of two modules apart | pointer casts of `0x388xxxxx` (in code and macro bodies, `.S` literals) and the `_Static_assert(ADDR + size <= END)` that bound them; a struct with no assert gets its `sizeof` from the compiler |
| stock bytes: call sites, page slots, constants | one module per byte | each `patches/*.py` imported with a stand-in symbol table, so no build is needed: (site, stock bytes, new bytes) for every patch of a set `check.sh` applies, in its order; a BL's target read back as its symbol name. Page slots and caps are data patches like any other |
| planned hooks | a site a feature will need | `resources: wants` tags |
| flash bank 1 / bank 2 | the cave's 57,736 B (`src/cave.ld.in`) | with `--build`: `out/cave.map` of a fresh build in a temporary copy, bytes per object per bank |

Two trees collide when: an id has no parameter (xml name) in common on both sides; an xml name sits on different
ids; stock bytes both patch hold different values in the two patched images (a call site with two targets, a slot
with two ids); a wanted site is patched by the other side; stock's entries + the union of both sides' entries pass
the cap; their SDRAM parts, at their own offsets, land on our parts or past our block; the same part sits at
different offsets (one layout or the other: the merge re-bases); the merged block (our block + their parts that
ride in no slack of ours) passes our bound; backup-SRAM ranges of different modules overlap; the merged cave
(ours + theirs - base, per object) passes bank 1.

### The tags

Only where nothing in the sources states a fact, in a comment of the file that describes it:

- `resources: store <name> sites=<stock store_add sites> cap=<movs sites> stock=<n>`: `patches/duck.py` (pad 59,
  the class-0x4c cell 37), `patches/comp.py` (global 41), `patches/munchi.py` (delay 8), `patches/fx2.py` (reverb 3).
  Stock's counts are the `bl 0x08093ef6` of each cell's case in FUN_08093f20 and in FUN_0809481c, counted on the
  listing (no branch inside a case); the pad's 59 is the figure `test_lfo.py` already gave.
- `resources: wants site=<addr> callee=<stock callee> by=<function>`: `patches/clipwin.py`, stage 1's capture at
  `0x080685D2` (`notes/clip-window-audit.md`, hub #t-044).
- `resources: shares at=<addr> with=<module>,<module>`: two modules that take turns on one backup-SRAM block
  (upstream's `comp.c` and `compm.c` at 0x38800400: one compressor runs at a time). None in this tree yet; the
  JOEBOX 2 merge needs that one.

A module's `TAKES` (a list of site addresses, or a dict keyed by them) lets it patch a site another module patches;
a module whose stock bytes are another's new bytes (master.py on comp.py's Tools page) is a chain patch.py accepts.

## Proof: this tree (maigre d23b389 + the tool) against upstream main (JOEBOX 2, da84b1b)

The merge's clashes as met by hand (hub work/t-047.md, work/t-052.md), and what the report says. 26 collisions,
about 7 s; 27 with `--build --base 66329ad`, about 35 s (eight cores shared with other work).

| clash | found | how |
|---|---|---|
| ids 0x1c8..0x1cc: TapeScam there, the Clip Window here | yes, 5 rows | `clipregion` / `tsinput` … `cliptlknob` / `tsnoise`: their ids come from a const array in master.c (`ts_num[k]`) |
| call sites 0x08064B2C, 0x08064C5A, 0x080A53B0, 0x080A582A, 0x080A5B0E | yes, 5 rows | each BL has two targets: `clipwin_*` here, `sel_*` there |
| 0x080685D2, which stage 1 wants | yes, but only through the `wants` tag | nothing of ours patches it yet (stage 1 is not written); without the tag it is missed |
| the pad store, 99 entries of 96 | yes | stock 59 + 40 (28 here, 35 there, 23 both); also cell 0x4c 77, global 81, delay 31, reverb 11, all within 96 |
| the Clip Pos page: Stretch and the Clip Window on one slot | yes, 2 rows | both copies of the page table (0x080EF998, 0x080EF290): 0x1c8 here, Stretch's 0x14c there |
| the SDRAM block: their new parts against D-030's core-first layout, past 0x84900 | yes, 12 rows | 6 parts at different offsets; 9 of their parts land, as written, on Prism, the insert bank or past our end; merged 0x95910 on either layout (t-047's figure), our core 0xc100 -> 0x1d110 (t-047's core); their stretch.c allocates another 0x58000 at boot |
| bank 1 (the trial build's wall: 4,505 B over before stage 3, 3,641 B after) | an estimate | 60,547..64,897 B of 57,736: 2,811..7,161 B over; the low end is the three-way sum per object, the high end counts munchi.o (both sides moved its engine to bank 2) as the larger side. The 3,641 B measured on the hand merge (these two heads plus t-047's two small commits) is inside |

What it does not see, from the same merge:
- a hook on a stock function our code calls: their trampoline on stock setup (`0x08064A94` -> `sel_setup`), which
  our `clipwin_wrap_b` calls, and `sel_block` at `0x08068C6A`; and JOEBOX 2's hooks inside functions
  `test_clipwin.py` pins (t-052 turn 7). No byte is patched twice, so no row.
- that the store copy trusts the destination's size, so the pad's cap and the global's move together (t-052
  turn 5); each store is checked alone.
- what a collision means for the product (whose Waveform knobs, whose selection length): it says where, not which.
- sizes the sources do not state: a part with no `BYTES` and no assert claims the room up to the next part; an
  array base cast (`GLBUF`) reads as one element.

Checked against the code: on the built image of each tree, `test_resources.py` runs every registration and
store-defaults hook under Unicorn and compares the ids with what was read: here 78 ids in 5 hooks and 80 entries
in 6 chains; on da84b1b, in a built copy, 103 ids and 106 chain entries; every hook the same as read.
