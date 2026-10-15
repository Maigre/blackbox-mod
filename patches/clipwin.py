"""Clip Window: per-pad Slip on Clip pads (see src/clipwin.c; reverse-engineering notes: github.com/Maigre/blackbox-mod, branch maigre, notes/re/).

Rides with the `filter` set (patches/filter.py imports it), which already owns the clip reader's call and the pad
pages, so the patched image keeps its name. The clip read itself needs no patch here: filter.py's hook at 0x08066622
goes to clip_read_b (src/filter_thunk.S), which now continues into clipwin_read. Apply together with `cave`."""
import os
import struct

from thumb import ROOT, bl, symbols

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))


def hook(at, stock, name):
    return (at, bl(at, stock), bl(at, sym[name]))


PATCHES = [
    # segment starts: the source prefetch in FUN_08065550 (every non-slice segment: launch, steps, wraps) and in
    # FUN_08065290 (slice-marker segments)
    hook(0x0806578C, 0x0806375C, "clipwin_seg_start_b"),
    hook(0x0806541A, 0x0806375C, "clipwin_slice_start_b"),
    # the knob's value text: set value (every type) and the type-1 turn
    hook(0x080B0746, 0x080B0528, "clipwin_format"),
    hook(0x080B0E18, 0x080B0528, "clipwin_format"),
    # the type-1 turn's stepper call: Slip's acceleration
    hook(0x080B0DDE, 0x080B0B74, "clipwin_turn"),
    # the Clip Pos page (FUN_08098d40 page 1: Loop Mode 0x8d, Beat Count 0xd2, Quant Size 0x47, Sync 0x94, then 32 empty
    # slots), both copies of the tables: Slip in slot 5
    (0x080EF998, struct.pack("<H", 0), struct.pack("<H", 0x1C9)),
    (0x080EF290, struct.pack("<H", 0), struct.pack("<H", 0x1C9)),
]
