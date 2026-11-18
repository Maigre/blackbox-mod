"""Looper FX: FX A types Looper / Loop In on the XY page (see src/looper.c, src/looper_dsp.c, notes/re/README.md P4).

Rides with the `master` set (patches/master.py imports it), which already owns the boot block the Looper's state lives
in, so the patched image keeps its name. duck_block's hook (patches/duck.py) carries the per-block clock snapshot.
Apply together with `cave`."""
import os

from thumb import ROOT, bl, bw, symbols, word

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))

AXES_COUNT, AXES = 0x080EEA78, 0x080EEA7C     # FX A's stock XY axis table: count, then {X, Y} per type

PATCHES = [
    # FX A's type list (0x18): Repeater, Gater, Filter + Looper, Loop In; and the X axis "Length:" (0x1cc)
    (0x0808C594, bl(0x0808C594, 0x0808C0D8), bl(0x0808C594, sym["looper_register_fxa"])),
    # the slot setter's case for 0x18: `cmp r2, #2; bhi` -> latch the index, then stock's swap
    (0x0806E174, bytes.fromhex("022aedd8"), bw(0x0806E174, sym["looper_fxa_set"])),
    # the axis table moves to the cave (5 types): FUN_080b1de0's two literals, then the view handler's
    (0x080B1E44, word(AXES_COUNT), word(sym["lp_axes"])),
    (0x080B1E48, word(AXES), word(sym["lp_axes"] + 4)),
    (0x080B20B8, word(AXES_COUNT), word(sym["lp_axes"])),
    (0x080B20BC, word(AXES), word(sym["lp_axes"] + 4)),
    # the Repeater's vtable: process (+0x0c) and active (+0x70)
    (0x080DF58C, word(0x0806D859), word(sym["looper_process"] | 1)),
    (0x080DF5F0, word(0x0806D0A1), word(sym["looper_active"] | 1)),
]
