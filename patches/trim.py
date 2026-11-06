"""Trim to Region on a Clip pad: the File menu's Trim, the save's loop and crop, the reload's rows kept (see src/trim.c).
Apply with `cave`."""
import os

from thumb import ROOT, bl, symbols

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))

PATCHES = [
    # the File menu's Trim enable (FUN_080B3194 case 0x127)
    (0x080B3620, bl(0x080B3620, 0x080BD566), bl(0x080B3620, sym["trim_menu_b"])),
    # FUN_080A0DD4's write request: the loop and the crop on a Clip trim
    (0x080A0FD0, bl(0x080A0FD0, 0x0804CA88), bl(0x080A0FD0, sym["trim_write_b"])),
    # FUN_080A0DD4's reload on the trim path: the pad's rows kept, Loop Start := F
    (0x080A0FE0, bl(0x080A0FE0, 0x080A0AC8), bl(0x080A0FE0, sym["trim_reload"])),
]
