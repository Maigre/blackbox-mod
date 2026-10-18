"""Bench tool: a screenshot of the running Blackbox over the dev build's USB peek (src/usbdev.c), as a PNG.

    bbshot.py OUT.png [--scale N]

Reads the LTDC's two layers where the controller says they are (L1/L2 CFBAR, pitch CFBLR, lines CFBLNR, format
PFCR; 320 x 240 ARGB1555 on 3.1.9) and blends them as the LTDC does (pixel alpha x constant alpha, BFCR 0x607) over
its background colour (BCCR). Every read stays exactly inside a framebuffer or is one register word: a peek past the
end of a memory region bus-faults the unit (gate3b F-j, 17/10). Read only. Fork-only tool, like bench/bbusb.py.
"""
import os
import struct
import sys
import zlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # bbusb.py beside it
import bbusb  # noqa: E402

LTDC = 0x50001000
SDRAM = (0xC0000000, 0xC4000000)


def reg(off):
    return struct.unpack("<I", bbusb.peek(LTDC + off, 4))[0]


def layer(base):
    """one enabled layer as (rgb float array h x w x 3, alpha h x w), or None"""
    if not reg(base) & 1:                                   # LxCR: LEN
        return None
    pf = reg(base + 0x10) & 7                               # LxPFCR
    if pf != 3:
        sys.exit(f"layer at +{base:#x}: pixel format {pf}, only ARGB1555 (3) is read")
    whpcr, wvpcr = reg(base + 0x04), reg(base + 0x08)
    w = (whpcr >> 16 & 0xFFF) - (whpcr & 0xFFF) + 1
    h = (wvpcr >> 16 & 0x7FF) - (wvpcr & 0x7FF) + 1
    addr, pitch, lines = reg(base + 0x28), reg(base + 0x2C) >> 16 & 0x1FFF, reg(base + 0x30) & 0x7FF
    size = pitch * lines
    if not (SDRAM[0] <= addr and addr + size <= SDRAM[1]) or pitch < 2 * w or lines < h:
        sys.exit(f"layer at +{base:#x}: framebuffer {addr:#x} pitch {pitch} lines {lines} not plainly in SDRAM")
    raw = np.frombuffer(bbusb.peek(addr, size), dtype="<u2").reshape(lines, pitch // 2)[:h, :w]
    a = (raw >> 15).astype(float) * (reg(base + 0x14) & 0xFF) / 255.0   # LxCACR
    rgb = np.stack([(raw >> s & 0x1F) for s in (10, 5, 0)], axis=-1).astype(float)
    return (rgb * 255.0 / 31.0), a, w, h


def png(path, img):
    h, w, _ = img.shape
    rows = b"".join(b"\0" + img[y].tobytes() for y in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def main(argv):
    if not argv:
        sys.exit(__doc__)
    out, scale = argv[0], int(argv[argv.index("--scale") + 1]) if "--scale" in argv else 2
    bccr = reg(0x2C)
    l1, l2 = layer(0x84), layer(0x104)
    w, h = (l1 or l2)[2], (l1 or l2)[3]
    img = np.empty((h, w, 3)); img[:] = [bccr >> 16 & 0xFF, bccr >> 8 & 0xFF, bccr & 0xFF]
    for lay in (l1, l2):                                    # layer 1 first, layer 2 on top
        if lay:
            rgb, a = lay[0], lay[1][..., None]
            img = rgb * a + img * (1.0 - a)
    img = np.clip(np.round(img), 0, 255).astype(np.uint8)
    if scale > 1:
        img = img.repeat(scale, axis=0).repeat(scale, axis=1)
    png(out, img)
    print(f"{out}: {w} x {h} (x{scale})")


if __name__ == "__main__":
    main(sys.argv[1:])
