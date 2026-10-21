"""Bench tool (fork-only, like bbusb.py): scan a Blackbox card for WAVs whose header promises more audio than the file
holds - a truncated copy. The unit trusts the header: it allocates the whole length, reads to the file's end and plays
zeros after it, with no error (F-n, 2026-10-21: preset B's copy of RC000032.wav, 903 168 of 4 833 890 bytes).

  bbcard.py CARD_ROOT       e.g. /run/media/mgr/6AF0-0F5D (read only)
"""
import os
import struct
import sys


def check(path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(12)
        if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            return None
        riff = struct.unpack("<I", head[4:8])[0] + 8
        at = 12
        while at + 8 <= size:
            f.seek(at)
            cid, n = struct.unpack("<4sI", f.read(8))
            if cid == b"data":
                end = at + 8 + n
                return (end, riff, size) if end > size else None
            at += 8 + n + (n & 1)
    return None


def main(root):
    bad = seen = 0
    for d, _, files in os.walk(root):
        for name in sorted(files):
            if not name.lower().endswith(".wav"):
                continue
            p = os.path.join(d, name)
            seen += 1
            r = check(p)
            if r:
                bad += 1
                end, riff, size = r
                print(f"TRUNCATED {os.path.relpath(p, root)}: {size} B on the card, the header's data ends at {end} B "
                      f"({100 * size / end:.0f} %)")
    print(f"{seen} WAVs, {bad} truncated")


if __name__ == "__main__":
    main(sys.argv[1])
