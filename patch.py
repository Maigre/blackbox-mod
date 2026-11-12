"""Apply byte patches to the stock Blackbox firmware and write an SD-card-ready BLACKBOX.bin.

  python3 patch.py <patchset> [...]     e.g. python3 patch.py version_tag

Each patchset in patches/ is a module defining PATCHES = [(addr, old_bytes, new_bytes), ...].
Every patch verifies the stock bytes before writing, so a patch built for the wrong firmware fails loudly.
A module may also define TAKES = (addr, ...): call sites another module patches too (a BL takes one target).
At those addresses only the module that takes them writes; the other's entry is skipped and printed.
"""
import hashlib
import importlib
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
STOCK = os.path.join(ROOT, "firmware", "BLACKBOX-3.1.9.bin")
STOCK_SHA256 = "281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d"
BASE = 0x08040000

data = bytearray(open(STOCK, "rb").read())
assert hashlib.sha256(data).hexdigest() == STOCK_SHA256, "stock firmware hash mismatch"

sys.path.insert(0, os.path.join(ROOT, "patches"))
names = sys.argv[1:]
mods = [(name, importlib.import_module(name)) for name in names]
taken = {addr: name for name, mod in mods for addr in getattr(mod, "TAKES", ())}
for name, mod in mods:
    for addr, old, new in mod.PATCHES:
        if taken.get(addr, name) != name:
            print(f"{name}: {addr:#010x} left to {taken[addr]}")
            continue
        o = addr - BASE
        if o == len(data):
            assert old == b"", f"{name}: append at {addr:#x} must have empty old bytes"
            data += new
            continue
        assert data[o:o + len(old)] == old, f"{name}: stock bytes differ at {addr:#x}"
        assert len(old) == len(new), f"{name}: size change at {addr:#x}"
        data[o:o + len(new)] = new
        print(f"{name}: {addr:#010x} {old.hex()} -> {new.hex()}")

# The Mk1 bootloader (1.0.22) compares up to 4 bytes past a last chunk that is no multiple of 4. Up to the next 32-byte
# boundary those are bytes it programmed itself; past it, erased flash against a stale buffer. So an image whose length
# is 29, 30 or 31 modulo 32 ends its install on "Unable to verify" (notes/re/x7 section 4.2: read from the bootloader,
# never seen on a unit). Stock is 24 modulo 32, so this is a cave of 5, 6 or 7 modulo 32: grow or shrink it by a few
# bytes (a pad in src/, not here: the browser patcher writes the same bytes).
assert len(data) % 32 not in (29, 30, 31), (
    f"the image is {len(data)} bytes, {len(data) % 32} modulo 32: the unit's installer would fail its verify "
    f"(notes/re/x7 section 4.2). Change the cave's size by a few bytes.")

out_dir = os.path.join(ROOT, "out", "+".join(names))
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, "BLACKBOX.bin")
open(out, "wb").write(data)
print(f"wrote {out} ({len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()[:16]})")
