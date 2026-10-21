"""Bench tool (fork-only, like bbusb.py): a read-only probe of stock's PCM sample cache, per wave (file): which
8192-frame blocks are in memory, and whether each holds sound or zeros. Layout: notes/re/x2-sdram-and-memory.md §2
(sys 0x2400A9C0, 615 descriptors x 0x1C; a descriptor's state byte, its +0x1F, runs into the next one).

  bbwaves.py [FLEN ...]     FLEN: file lengths in frames to label waves by (searched in each wave's record)

The wave record (0x170 B) holds the frames at +0x50 and the path at +0x5C; +0x010 is the audio's bytes, +0x00C the
loader's file position. F-n (2026-10-21): a wave with every block allocated but zeros past a first run, its +0x00C
past the file's end - a load whose card reads failed partway (notes/bench/2026-10-21-37.4.1d.md).
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # bbusb.py beside it
import bbusb  # noqa: E402

SYS = 0x2400A9C0
NDESC, DSZ = 0x267, 0x1C
BLOCK = 0x2000                       # floats per buffer = frames per block (one channel each buffer)


def read(addr, n):
    out = b""
    while n > 0:
        k = min(64, n)
        out += bbusb.peek(addr, k)
        addr += k
        n -= k
    return out


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


desc = read(SYS, NDESC * DSZ + 4)              # + the last state byte (+0x1F runs into the next descriptor)
wtab = u32(read(SYS + 0x4348, 4), 0)
idmap = struct.unpack("<576H", read(SYS + 0x434C, 576 * 2))
flens = [int(a) for a in sys.argv[1:]]

waves = {}
for i in range(NDESC):
    d = desc[i * DSZ:(i + 1) * DSZ]
    owner = struct.unpack_from("<H", d, 0x18)[0]
    if owner == 0xFFFF:
        continue
    waves.setdefault(owner, []).append((u32(d, 0x0C), desc[i * DSZ + 0x1F], u32(d, 0x04), u32(d, 0x10), i))

print(f"wave table {wtab:#x}; {sum(len(v) for v in waves.values())} of {NDESC} blocks owned by {len(waves)} waves")
for owner in sorted(waves):
    blocks = sorted(waves[owner])
    rec = idmap[owner] if owner < 576 else 0xFFFF
    label = ""
    if rec != 0xFFFF and flens:
        r = read(wtab + rec * 0x170, 0x170)
        hits = [(f, o) for f in flens for o in range(0, 0x170, 4) if u32(r, o) == f]
        label = " ".join(f"len {f} @+{o:#x}" for f, o in hits)
    idx = [b[0] for b in blocks]
    states = sorted(set(b[1] for b in blocks))
    # sound or zeros: 16 floats at three places in each block's first buffer
    marks = ""
    for (k, st, lp, lru, i) in blocks:
        z = True
        for off in (0x100, 0x4000, 0x7E00):
            if lp and any(struct.unpack("<16I", read(lp + off, 64))):
                z = False
                break
        marks += "." if z else "#"
    print(f"wave {owner:3d} rec {rec:#06x} blocks {len(blocks):3d} idx {idx[0]}..{idx[-1]} states {states} {label}")
    print(f"   by index ({BLOCK} frames each; # sound, . zeros): {marks}")
    missing = sorted(set(range(idx[0], idx[-1] + 1)) - set(idx))
    if missing:
        print(f"   not in memory: {missing[:40]}{' ...' if len(missing) > 40 else ''}")
