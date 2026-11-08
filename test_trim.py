"""Trim to Region on a Clip pad under Unicorn (src/trim.c, notes/re/x4-trim.md).

Real firmware runs for: the three call sites' thunks and hooks, the store getter and setter (FUN_08093E9C,
FUN_08093ECC) and stock's strncmp (FUN_080C8B48). Stubbed: the File menu's enable (FUN_080BD566, recorded), the smpl
helper and the crop (FUN_08077738, FUN_0807775C, recorded), the write request (0x0804CA88, recorded), the reload
(FUN_080A0AC8: what x4 §4 read it doing to a Clip pad - 0x8F, Length and Loop Start := 0, the fresh byte := 1) and
clipwin_flen (0, so the file's length is the store's Length).
NOT checked here: stock's disk copy writing [LS - F, LE) (run in x4 §7), the 0xE and 0x1B after the reload (x4 §9), a
trimmed pad's render equal to the untrimmed region's with Slip and Fit on, a Trim under a playing pad, and the unit.
"""
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R6, UC_ARM_REG_R7

from emu import STACK, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
e = Emu(IMAGE, "out/cave.elf")
img = open(IMAGE, "rb").read()

APP = 0x24020088
PADS = APP + 0x1840                              # + row * 0xF0 + col * 0x30, cols 0-4 (FUN_08098D0C)
ENTRIES, NAMES, CELL, MENU = 0x24060000, 0x24078000, 0x24070000, 0x24071000
HOST, ASSET, META, PATH = 0x2400A9C0, 0x24072000, 0x24073000, 0x24074000
LEN, ROW, COL = 200000, 1, 2
CELL_TAG = 0x080EAF38

fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def bl_target(at):
    h1, h2 = struct.unpack_from("<HH", img, at - 0x08040000)
    s, j1, j2 = (h1 >> 10) & 1, (h2 >> 13) & 1, (h2 >> 11) & 1
    off = (s << 24) | ((1 - (j1 ^ s)) << 23) | ((1 - (j2 ^ s)) << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    return at + 4 + (off - (1 << 25) if s else off)


def signed(v):
    return struct.unpack("<i", struct.pack("<I", v & 0xFFFFFFFF))[0]


def store_of(row, col):
    return PADS + row * 0xF0 + col * 0x30


def fresh_of(row, col):
    return APP + 0x8A96 + row * 0x78 + col * 0x18


def reset():
    e.uc.mem_write(PADS, bytes(4 * 0xF0))
    e.uc.mem_write(ENTRIES, bytes(20 * 0x100))
    e.uc.mem_write(NAMES, bytes(20 * 0x100))
    e.uc.mem_write(APP + 0x8A96, bytes(4 * 0x78))
    got.clear()


def name(row, col, text):
    buf = NAMES + (row * 5 + col) * 0x100
    e.uc.mem_write(buf, text.encode() + b"\0")
    e.w32(store_of(row, col) + 0x18, buf)


def pad(vals, row=ROW, col=COL, file="TAKE01.WAV"):
    s, ent = store_of(row, col), ENTRIES + (row * 5 + col) * 0x100
    e.w32(s + 4, ent)
    e.uc.mem_write(s + 0xA, struct.pack("<H", len(vals)))
    for i, (k, v) in enumerate(vals.items()):
        e.uc.mem_write(ent + 8 * i, struct.pack("<HHi", k, 0, v))
    if file is not None:
        name(row, col, file)
    e.uc.mem_write(CELL, struct.pack("<IHH", CELL_TAG, row << 4 | col, 0))


def get(k, row=ROW, col=COL):
    s = store_of(row, col)
    ent, n = e.r32(s + 4) & 0xFFFFFFFF, e.r16(s + 0xA)
    for i in range(n):
        kk, _, v = struct.unpack("<HHi", e.uc.mem_read(ent + 8 * i, 8))
        if kk == k:
            return v


def clip(mode=1, region=0, ls=24000, le=72000, fade=100):
    # Pad Mode, 0x8F, Length, Loop Start, Loop End, Loop Fade, Region (0 Auto, 1 File, 2 Loop), Slip, Loop Len, Fit
    return {0x8B: mode, 0x8F: 0, 0x90: LEN, 0x91: ls, 0x92: le, 0xFA: fade, 0x1C8: region, 0x1C9: 7, 0x1CA: 0, 0x1CB: 1}


got = {}
e.stub(e.sym["clipwin_flen"], value=0)
e.stub(0x080BD566, lambda: got.__setitem__("on", e.arg(2)))
e.stub(0x08077738, lambda: got.setdefault("order", []).append("smpl") or got.__setitem__(
    "loop", struct.unpack("<IIB", e.uc.mem_read(e.arg(2), 9))))
e.stub(0x0807775C, lambda: got.setdefault("order", []).append("crop") or got.__setitem__(
    "crop", (signed(e.arg(1)), signed(e.arg(2)))))
e.stub(0x0804CA88, lambda: got.setdefault("order", []).append("request") or got.__setitem__(
    "request", tuple(e.arg(i) for i in range(4))))


def stock_reload():
    code = e.r16(e.arg(2) + 4)
    row, col = (code >> 4) & 0xF, code & 0xF
    got["reload"] = tuple(e.arg(i) for i in range(4))
    s = store_of(row, col)
    ent, n = e.r32(s + 4) & 0xFFFFFFFF, e.r16(s + 0xA)
    for i in range(n):
        kk = e.r16(ent + 8 * i)
        if kk in (0x8F, 0x90, 0x91):
            e.uc.mem_write(ent + 8 * i + 4, struct.pack("<i", 0))
    e.uc.mem_write(fresh_of(row, col), b"\x01")


e.stub(0x080A0AC8, stock_reload)


def menu(stock_on=0, own=True, multisam=0):
    e.w32(STACK + 4, multisam)
    got.pop("on", None)
    e.uc.reg_write(UC_ARM_REG_R6, CELL)
    e.uc.reg_write(UC_ARM_REG_R7, 0 if own else 1)
    e.call("trim_menu_b", MENU, 0x124, stock_on)
    return got.get("on")


def write(trim):
    e.w32(STACK + 0x10, trim)
    e.uc.reg_write(UC_ARM_REG_R6, CELL)
    e.call("trim_write_b", HOST, ASSET, META, PATH)

# --- 1. the call sites
check("the File menu's Trim enable @0x080B3620 goes to trim_menu_b", bl_target(0x080B3620) == e.sym["trim_menu_b"])
check("FUN_080A0DD4's write request @0x080A0FD0 goes to trim_write_b", bl_target(0x080A0FD0) == e.sym["trim_write_b"])
check("FUN_080A0DD4's reload on the trim path @0x080A0FE0 goes to trim_reload", bl_target(0x080A0FE0) == e.sym["trim_reload"])

# --- 2. the menu's truth table (pad 1,2 alone in the preset)
for label, vals, kw, want in [
        ("a Clip pad, Region Auto playing a loop: Trim on", clip(), {}, 1),
        ("a Clip pad, Region Loop: Trim on", clip(region=2), {}, 1),
        ("a Clip pad, Region File: Trim off", clip(region=1), {}, 0),
        ("a Clip pad whose region is the whole file: Trim off", clip(ls=0, le=LEN), {}, 0),
        ("a Clip pad whose region starts at the file's start (LS = 0): Trim off, the cut's loop would be its whole file",
         clip(ls=0), {}, 0),
        ("a Clip pad with an empty region (LS = LE): Trim off", clip(ls=24000, le=24000), {}, 0),
        ("a Clip pad whose Loop End is past the file: Trim off", clip(le=LEN + 5), {}, 0),
        ("a Clip pad, another file highlighted: stock's off", clip(), {"own": False}, 0),
        ("a Clip pad with MultiSam: stock's off", clip(), {"multisam": 1}, 0),
        ("Pad Mode 3: stock's off", clip(mode=3), {}, 0),
        ("a Sample pad: stock's on, untouched", clip(mode=0), {"stock_on": 1}, 1),
        ("a Sample pad stock leaves off: off", clip(mode=0), {}, 0)]:
    reset()
    pad(vals)
    on = menu(**kw)
    check(label, on == want, on)

# --- 3. another cell naming the same file
for label, others, own, want in [
        ("another pad, another file: Trim on", [(0, 0, "TAKE02.WAV"), (3, 3, "TAKE01.WAV2")], "TAKE01.WAV", 1),
        ("other pads with no file: Trim on", [(0, 1, ""), (2, 2, "")], "TAKE01.WAV", 1),
        ("pad 0,0 names the same file: Trim off", [(0, 0, "TAKE01.WAV")], "TAKE01.WAV", 0),
        ("pad 3,3 names the same file: Trim off", [(3, 3, "TAKE01.WAV")], "TAKE01.WAV", 0),
        ("cell 2,4 (stock's fifth column) names the same file: Trim off", [(2, 4, "TAKE01.WAV")], "TAKE01.WAV", 0),
        ("the pad names no file: Trim off", [], "", 0),
        ("the pad's name pointer is null: Trim off", [], None, 0)]:
    reset()
    pad(clip(), file=own)
    for r, c, t in others:
        name(r, c, t)
    on = menu()
    check(label, on == want, on)

# --- 4. the write request: the save's loop and crop
for label, vals, trim, others, loop, crop in [
        ("Trim, Loop Fade 100: smpl {24000, 72000, forward}, crop (19200, 52800) - F = 4800 kept",
         clip(), 1, [], (24000, 72000, 0), (19200, 52800)),
        ("Trim, Loop Fade 0: crop (23999, 48001), one frame kept so the loop is not the whole file", clip(fade=0), 1, [],
         (24000, 72000, 0), (23999, 48001)),
        ("Trim, Loop Start 2000 under Loop Fade 100: F clamps to Loop Start, crop (0, 72000)",
         clip(ls=2000), 1, [], (2000, 72000, 0), (0, 72000)),
        ("Save (trim 0) on a Clip pad: no loop, no crop", clip(), 0, [], None, None),
        ("Trim on a Sample pad: stock's own loop and crop, nothing added", clip(mode=0), 1, [], None, None),
        ("Trim while pad 3,3 names the same file: nothing added", clip(), 1, [(3, 3, "TAKE01.WAV")], None, None)]:
    reset()
    pad(vals)
    for r, c, t in others:
        name(r, c, t)
    write(trim)
    ok = got.get("loop") == loop and got.get("crop") == crop and got.get("request") == (HOST, ASSET, META, PATH)
    check(label, ok, (got.get("loop"), got.get("crop"), got.get("request")))
reset()
pad(clip())
write(1)
check("the loop and the crop are in the meta before the request is posted", got.get("order") == ["smpl", "crop", "request"],
      got.get("order"))

# --- 5. the reload: the pad's rows kept, Loop Start := F
for label, vals, fresh, ls in [("a Clip pad, Loop Fade 100: fresh byte 0, Loop Start := F = 4800", clip(), 0, 4800),
                               ("a Clip pad, the clamp: Loop Start := 2000", clip(ls=2000), 0, 2000),
                               ("a Clip pad, Loop Fade 0: Loop Start := 1, the frame kept", clip(fade=0), 0, 1),
                               ("a Sample pad: stock's reload, untouched", clip(mode=0), 1, 0)]:
    reset()
    pad(vals)
    e.call("trim_reload", APP, PATH, CELL, 0)
    kept = all(get(k) == vals[k] for k in (0x8B, 0x92, 0xFA, 0x1C8, 0x1C9, 0x1CA, 0x1CB))
    check(label, e.r8(fresh_of(ROW, COL)) == fresh and get(0x91) == ls and kept,
          (e.r8(fresh_of(ROW, COL)), get(0x91), {hex(k): get(k) for k in vals}))
    check(f"  {label.split(':')[0]}: stock's reload gets the same arguments", got.get("reload") == (APP, PATH, CELL, 0),
          got.get("reload"))

print(f"{fails} failed")
sys.exit(1 if fails else 0)
