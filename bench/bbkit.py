"""Bench tool: drive a Blackbox with no hands, through the bench kit of a DEV build that has it (src/kit.c,
src/kit_b2.c; notes/re/x6-input-and-card-paths.md sections 9 and 13). Needs that build's BBEXTRA.BIN on the card (the kit runs from bank 2).
Fork-only tool, like bench/bbusb.py, whose peek and poke it uses.

  bbkit.py info                          the kit's table, the screen showing, the GUI clock, the boot count
  bbkit.py knob KNOB COUNTS [N [GAP]]    N events of COUNTS (+-1 .. 32767) on KNOB (tl bl tr br, or 0-3), GAP passes
                                         apart (default 1 event, 0 passes)
  bbkit.py button NAME [press|release|hold]
                                         pads keys seqs song fx mix pset tools rec stop play back info (or 0-12)
  bbkit.py play | stop                   the PLAY / STOP button pressed
  bbkit.py touch down|move|up [X Y]      the kit's own finger, in the screenshot's pixels (320 x 240)
  bbkit.py tap X Y [PASSES]              down, and up PASSES GUI passes later (default 3)
  bbkit.py cancel                        end a knob or tap job still running (until it ends, the unit answers
                                         every other job -8, busy)
  bbkit.py presets                       the preset list, by index
  bbkit.py preset NAME                   load it, as the PSET screen's Load does (then the Pads screen)
  bbkit.py ls [PATH]                     a folder of the card ("" = the root)
  bbkit.py stat PATH                     size, attributes, date of a file
  bbkit.py get PATH [LOCAL]              copy a file off the card
  bbkit.py put LOCAL [PATH] [--replace]  copy a file onto the card; never replaces one unless --replace
  bbkit.py rm PATH                       delete a file on the card
  bbkit.py restart                       a clean reset, once stock is idle on the card and nothing plays or records
  bbkit.py shot OUT.png                  a screenshot (bench/bbshot.py, with the long peek)
  bbkit.py row CELL ROW [VALUE]          a pad's row, as bbusb.py set / get, through the kit's job 1 / 2

Each job: the request written into the mailbox at the boot-time SDRAM block + 0xc000 (seq last), the answer polled
every 20 ms, one request at a time (keep the USB light: heavy traffic has made the unit's USB go quiet before).
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # bbusb.py beside it
import bbusb  # noqa: E402

KIT1 = 0x3154494B
BLOCK_PTR, BLOCK_CHECK, PRISM_KEY = 0x38800F70, 0x38800F74, 0x5052534D
BOOTS = 0x38800FE0               # fault.c's boot count: the epoch every request carries
MBOX, DATA = 0xC000, 0x84900     # in the block: the mailbox; the kit's data area (a dev build's, at the tail's end)
NAME, CHUNK, CHUNK_BYTES = 0x200, 0x400, 4096
RESULTS = {0: "done", -1: "no such job (a build without it?)", -2: "stale: asked before the unit's last reset",
           -3: "bad argument", -4: "stock would not take it now", -5: "not found", -6: "FatFs error",
           -7: "wrong state (no file open, one open already, no touch down, one down already)",
           -8: "busy: a knob or tap job is running (bbkit.py cancel ends it)"}
BUSY = {1: "the transport plays", 2: "REC is held", 3: "file commands are queued", 4: "a preset load is pending",
        5: "the card's queue is busy", 6: "no card, or no kit data area"}
KNOBS = {"tl": 0, "bl": 1, "tr": 2, "br": 3}
BUTTONS = ["pads", "keys", "seqs", "song", "fx", "mix", "pset", "tools", "rec", "stop", "play", "back", "info"]
FATFS = {1: "disk error", 2: "internal error", 3: "not ready", 4: "no file", 5: "no path", 6: "invalid name",
         7: "denied", 8: "exists", 9: "invalid object", 10: "write protected", 11: "invalid drive", 12: "not enabled",
         13: "no filesystem", 15: "timeout", 16: "locked", 17: "not enough core", 18: "too many open files"}


class KitError(Exception):
    def __init__(self, result, r):
        self.result, self.r = result, r
        why = RESULTS.get(result, str(result))
        if result == -4 and r[0] in BUSY:
            why += f": {BUSY[r[0]]}"
        if result == -6:
            why += f" {r[0]} ({FATFS.get(r[0], '?')})"
        super().__init__(why)


def block():
    """the boot-time SDRAM block, with its tail (bank 2's payload was there at boot): where the kit lives"""
    mem = bbusb.word(BLOCK_PTR)
    if not 0xC0000000 <= mem < 0xC4000000 or bbusb.word(BLOCK_CHECK) != mem ^ PRISM_KEY:
        sys.exit(f"no SDRAM block with its tail (pointer {mem:#x}): no matching BBEXTRA.BIN on this unit, so no kit")
    return mem


def write(addr, data):
    """bytes into the unit's RAM, padded to whole words: the long poke, 4 096 bytes a request"""
    data = bytes(data) + bytes(-len(data) % 4)
    bbusb.poke_bytes(addr, data)


SPANS = {0x03: "knob", 0x05: "tap"}   # the jobs that span GUI passes: the box is theirs until they end
CANCEL = 0x08


def job(index, *args, timeout=5.0, base=None):
    """run job `index` with up to six i32 arguments; (r0, r1, r2, r3), or KitError. While a knob or tap job runs the
    unit answers every other request -8: none is sent then but a cancel. A knob or tap job that does not end within
    `timeout` is cancelled, so it does not go on behind the next command."""
    base = base if base is not None else block()
    mb = base + MBOX
    epoch = bbusb.word(BOOTS)
    box = bbusb.peek(mb + 0x24, 0x30)                    # seq, done ... +0x40 state ... +0x50 the job running
    seq_now, done = struct.unpack_from("<II", box)
    if struct.unpack_from("<I", box, 0x1C)[0] == 1 and index != CANCEL:
        sys.exit(f"job {index:#x} not sent: the unit is still running a {SPANS.get(box[0x2C], hex(box[0x2C]))} job "
                 "(bbkit.py cancel ends it)")
    seq = (max(seq_now, done) + 1) & 0xFFFFFFFF or 1
    a = [v & 0xFFFFFFFF for v in args] + [0] * (6 - len(args))
    write(mb, struct.pack("<IHHI6I", KIT1, index, 0, epoch, *a) + struct.pack("<I", seq))   # ascending: seq last
    t0 = time.time()
    while bbusb.word(mb + 0x28) != seq:
        if time.time() - t0 > timeout:
            if index in SPANS:
                r = job(CANCEL, base=base)
                how = f"after {r[1]} event(s)" if r[0] == 3 else "its contact lifted" if r[0] == 5 else "it had ended"
                sys.exit(f"no end to the {SPANS[index]} job in {timeout:g} s: cancelled ({how})")
            sys.exit(f"no answer to job {index:#x} in {timeout:g} s (a build without the kit, bank 2 not live, or the "
                     "task that runs it is not running)")
        time.sleep(0.02)
    result, *r = struct.unpack("<5i", bbusb.peek(mb + 0x2C, 20))
    if result:
        raise KitError(result, r)
    return tuple(r)


def put_name(base, text):
    raw = text.encode("latin-1") + b"\0"
    if len(raw) > 256:
        sys.exit("a name or path is at most 255 bytes")
    write(base + DATA + NAME, raw)


def ls(path=""):
    base = block()
    out, first = [], 0
    while True:
        put_name(base, path)
        n, more, used, _ = job(0x46, first, 1000, base=base)
        raw = bbusb.peek(base + DATA + CHUNK, used) if used else b""
        o = 0
        while o < used:
            lo, hi, attr, ln = struct.unpack_from("<IIBB", raw, o)
            out.append((raw[o + 10:o + 10 + ln].decode("latin-1"), lo | hi << 32, attr))
            o += (10 + ln + 3) & ~3
        first += n
        if not more:
            return out


def get(path, local):
    base = block()
    put_name(base, path)
    size = job(0x40, 0, base=base)
    size = size[0] & 0xFFFFFFFF | (size[1] & 0xFFFFFFFF) << 32
    got, t0 = bytearray(), time.time()
    try:
        while True:
            n = job(0x41, CHUNK_BYTES, base=base)[0]
            if n:
                got += bbusb.peek(base + DATA + CHUNK, n)
            if n < CHUNK_BYTES:
                break
    finally:
        job(0x44, base=base)
    open(local, "wb").write(got)
    return len(got), size, time.time() - t0


def put(local, path, replace=False):
    data = open(local, "rb").read()
    base = block()
    put_name(base, path)
    job(0x40, 2 if replace else 1, base=base)
    t0 = time.time()
    try:
        for at in range(0, len(data), CHUNK_BYTES):
            piece = data[at:at + CHUNK_BYTES]
            write(base + DATA + CHUNK, piece)
            if job(0x42, len(piece), base=base)[0] != len(piece):
                sys.exit(f"the card took less than {len(piece)} bytes at {at} (full?)")
    finally:
        job(0x44, base=base)
    return len(data), time.time() - t0


def presets():
    base = block()
    count = job(0x07, -1, base=base)[0]
    names = []
    for i in range(count):
        if job(0x07, i, base=base)[3]:
            names.append(bbusb.peek(base + DATA + NAME, 256).split(b"\0")[0].decode("latin-1"))
    return names


def button_index(text):
    t = text.lower()
    return BUTTONS.index(t) if t in BUTTONS else int(t, 0)


def main(argv):
    if not argv:
        sys.exit(__doc__)
    cmd, args = argv[0], argv[1:]
    try:
        if cmd == "info":
            r = job(0x00)
            print(f"kit v{r[0] >> 16}, {r[0] & 0xFFFF} job slots; screen {r[1]:#x}; GUI clock {r[2]} ms; boot #{r[3]}")
        elif cmd == "knob":
            knob = KNOBS.get(args[0].lower(), None)
            knob = int(args[0], 0) if knob is None else knob
            n = job(0x03, knob, int(args[1], 0), int(args[2], 0) if len(args) > 2 else 1,
                    int(args[3], 0) if len(args) > 3 else 0, timeout=60)[0]
            print(f"knob {knob}: {n} event(s) posted")
        elif cmd in ("button", "play", "stop"):
            i = button_index(args[0]) if cmd == "button" else BUTTONS.index(cmd)
            what = ["press", "release", "hold"].index(args[1]) if cmd == "button" and len(args) > 1 else 0
            print(f"{BUTTONS[i]} {['press', 'release', 'hold'][what]}: code {job(0x20, i, what)[0]:#x}")
        elif cmd == "touch":
            what = ["down", "move", "up"].index(args[0])
            xy = [int(v, 0) for v in args[1:3]] if what < 2 else []
            print(f"touch {args[0]}: widget {job(0x04, what, *xy)[0]:#x}")
        elif cmd == "tap":
            x, y = int(args[0], 0), int(args[1], 0)
            print(f"tap {x},{y}: widget {job(0x05, x, y, int(args[2], 0) if len(args) > 2 else 3, timeout=30)[0]:#x}")
        elif cmd == "cancel":
            r = job(CANCEL)
            print(f"cancelled the {SPANS[r[0]]} job ({'events posted' if r[0] == 3 else 'widget'} {r[1]})" if r[0] in SPANS
                  else "nothing was running")
        elif cmd == "presets":
            for i, n in enumerate(presets()):
                print(f"{i:3}  {n}")
        elif cmd == "preset":
            base = block()
            put_name(base, args[0])
            print(f"preset {args[0]!r}: index {job(0x06, base=base)[0]}, loading")
        elif cmd == "ls":
            for n, size, attr in ls(args[0] if args else ""):
                print(f"{'<dir>' if attr & 0x10 else size:>12}  {n}")
        elif cmd == "stat":
            base = block()
            put_name(base, args[0])
            lo, hi, attr, dt = job(0x45, base=base)
            d, t = (dt >> 16) & 0xFFFF, dt & 0xFFFF
            print(f"{args[0]}: {lo & 0xFFFFFFFF | (hi & 0xFFFFFFFF) << 32} B, attributes {attr:#x}, "
                  f"{1980 + (d >> 9)}-{d >> 5 & 15:02}-{d & 31:02} {t >> 11:02}:{t >> 5 & 63:02}:{(t & 31) * 2:02}")
        elif cmd == "get":
            local = args[1] if len(args) > 1 else os.path.basename(args[0].replace("\\", "/"))
            n, size, secs = get(args[0], local)
            print(f"{args[0]} -> {local}: {n} of {size} B in {secs:.1f} s")
        elif cmd == "put":
            rest = [a for a in args if a != "--replace"]
            path = rest[1] if len(rest) > 1 else os.path.basename(rest[0])
            n, secs = put(rest[0], path, replace="--replace" in args)
            print(f"{rest[0]} -> {path}: {n} B in {secs:.1f} s")
        elif cmd == "rm":
            base = block()
            put_name(base, args[0])
            job(0x47, base=base)
            print(f"{args[0]}: deleted")
        elif cmd == "restart":
            job(0x4F, 0x52455354)
            print("restarting: the unit resets now (watch it re-enumerate; bbusb.py crash says why it last reset)")
        elif cmd == "shot":
            import bbshot
            bbshot.main(args)
        elif cmd == "row":
            row, col = bbusb.cell(args[0])
            pid = bbusb.MBOX_ROWS[args[1].lower()]
            r = job(0x01, row, col, pid, int(args[2], 0)) if len(args) > 2 else job(0x02, row, col, pid)
            print(f"cell row {row} col {col}: {bbusb.show(pid, r[0])}")
        else:
            sys.exit(__doc__)
    except KitError as e:
        sys.exit(f"{cmd}: {e}")


if __name__ == "__main__":
    main(sys.argv[1:])
