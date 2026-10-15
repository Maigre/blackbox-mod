"""Clip Window v1, Slip (src/clipwin.c, clipwin_thunk.S, patches/clipwin.py; notes/re/README.md section 2) under Unicorn.

Real firmware runs for: the whole class-B pad block method (0x08068c64) block after block - process, voice start,
segment start (FUN_08065550 with H1 in it, FUN_08065290 with H1'), render, fades, the segment reader with JOEBOX's
clip_read_b and clipwin_read in it, filter.c's clip_read and clip_read_ring, the stock clip reader and its kernel - then
the engine's own clock advance (0x080696d8), in the control tick's order; the pad constructor and the real param-set
for every setting (Pad Mode, Launch, Loop, Beat Count, Quant, Sync, Pitch, slice markers, a live Sync change, Launch
Trigger relaunches, the transport stopped and its start message 0x57); clipwin_tick reading the app's pad stores
through the stock settings lookup, once a block where duck_block calls it; filter.c's machine readers (every machine
mode, SP 45 included) at and near the seam; the stock pad-parameter registrar (FUN_0808c158) with master_register /
clipwin_register in it, the stock pad-store builder (FUN_08093f20) with the defaults chain in it, master_alloc; the
stock knob binder (FUN_080a7ee0), set-value, the turn (FUN_080b0d54) and list-widget (FUN_080b9a3c) paths with
clipwin_format / clipwin_turn in them, the stock ring push and speed, stepper and snprintf; both thunks entered as their
sites enter them. Every scenario also runs on this image with the clipwin hooks taken out at run time, and the Slip 0
ones on the stock 3.1.9 image, for the comparisons.
Stubbed: the allocator, the log print, the sample source (length, rate, ready, the prefetch hint - recorded, with the
read it was made in - and the mono / stereo fetch, which serve a ramp: frame q holds (q + 1) * 2^-20, the right channel
its negative, or 1.0 for the gain runs; in the reader unit two sines, the file or the file turned circular), the knob's
text widget, redraw and post to the app (recorded).
Reference: the research harness's stock measurements (notes/re/a2: launch on the bar at 288 000 with +0x140 = 11 520
and msg 0x1d, a launch 300 samples late at once with +0x140 = 11 532, steps at (int)(j x fps), Sync None restarting
every len - 257 samples) and its model's assertions (a2/r2/k_slip.py, k_live.py, droplaunch.py, armed.py): every
sounding sample plays (stock frame + slip_f) mod len, the summed gain is stock's - a launch waiting for its bar when
Slip changes included; for the reader, the stock reader on the file turned circular; for a machine-mode pad, filter.c's
own clip_read on the file turned circular (at the seam, on the last blocks before it, near the start: bit for bit) and
test_clip.py's drop-sample model off the seam; for the seam hint, notes/re/a2's provider (a hint covers the block of
its position and the next two: 16 384 frames sure).
NOT checked: duck_block and the control tick around clipwin_tick (only its place in duck_block, from the image); the
app writing the store from the knob (SetCellParam) and a negative value through preset save / load; SD streaming at
the seam (the source is in RAM: the hints are checked - H1's, and H2's one at rs per crossing segment - not whether the
unit's cache still holds the hinted blocks when the read gets there: the miss counter 0x24013930, on the unit); Fidelity
machine modes inside the whole process (the reader alone is); the playhead on the waveform (left stock); relaunches at
the other recompute sites beyond the retriggers; the knob's counts per revolution on the hardware (the acceleration's
K); how it sounds; CPU on the chip.
"""
import struct
import subprocess
import sys

import numpy as np
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                               UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R8, UC_ARM_REG_R11, UC_ARM_REG_S0,
                               UC_ARM_REG_SP, UC_ARM_REG_LR)

from emu import BASE, RET, STACK, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
STOCK = "firmware/BLACKBOX-3.1.9.bin"
e = Emu(IMAGE, "out/cave.elf")
img, stock = open(IMAGE, "rb").read(), open(STOCK, "rb").read()
S = e.sym

P_SLIP = 0x1C9
APP = 0x24020088
APP_PADS = APP + 0x1840
GUI_MS = 0x2402EEE0
PMEM, PCHECK, KEY = 0x38800F70, 0x38800F74, 0x5052534D
BLOCK = 0xC0000000                                   # master.c's boot-time SDRAM block, here
BANK = BLOCK + 0x56800 + 0x2D100                     # clipwin.c's cw_bank in it
B_SLIP, B_PAD, B_VALID, B_LATCH, B_H1, B_HINTED = 8, 0x48, 0x88, 0x98, 0x398, 0x3A8
B_SIZE = 0x3B8                                       # sizeof(struct cw_bank)
CW_MAGIC = 0x43574E31
HEAP = 0xC1000000
ARR = 0x24072000                                     # the stores' entry arrays, 0x100 a pad
N = 128
RAMP = 2.0 ** -20
CTOR, PSET, BLOCKM, ADVANCE = 0x080640D0, 0x08067648, 0x08068C64, 0x080696D8
PREFETCH, SRC_LEN, FETCH, FETCH2 = 0x0806375C, 0x080636F0, 0x08063634, 0x08063608
SITE_H1, SITE_H1P, SITE_READ, SITE_MIX_L, SITE_MIX_R = 0x0806578C, 0x0806541A, 0x08066622, 0x080666E2, 0x080666FA
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def info(text):
    print("     " + text)


def maps(m):
    """what the class-B code and the cave touch beyond emu.py's map: ITCM/DTCM/SRAM, backup SRAM + RCC, WWDG, SDRAM"""
    for a, n in ((0x00000000, 0x10000), (0x20000000, 0x80000), (0x30000000, 0x48000), (0x38000000, 0x10000),
                 (0x38800000, 0x1000), (0x58024000, 0x1000), (0x50003000, 0x1000), (0xC0000000, 0x1800000)):
        m.uc.mem_map(a, n)


def sdram(m, on=True):
    m.w32(PMEM, BLOCK if on else 0)
    m.w32(PCHECK, (BLOCK ^ KEY) if on else 0)


def store(m, q, vals):
    """the app's settings store of pad q (row q // 4, col q % 4): {id: value}. Slip goes in as the ENGINE's shift of the
    content (+ = earlier), the number every check below reasons in; the row itself reads + = later (Thomas, 2026-10-15),
    so what lands in the store is its negative. store_raw writes the row's own value."""
    return store_raw(m, q, {i: (-v if i == P_SLIP else v) for i, v in vals.items()})


def store_raw(m, q, vals):
    """the app's settings store of pad q, values as the app keeps them"""
    rows = sorted(vals.items())
    at = ARR + q * 0x100
    m.uc.mem_write(at, b"".join(struct.pack("<HHi", i, 0, v) for i, v in rows))
    s = APP_PADS + (q // 4) * 0xF0 + (q % 4) * 0x30
    m.w32(s + 4, at)
    m.uc.mem_write(s + 10, struct.pack("<H", len(rows)))


def slips(m, d):
    for q in range(16):
        store(m, q, {0x4: 500, P_SLIP: d.get(q, 0)})


def u32(m, a):
    return m.r32(a) & 0xFFFFFFFF


def bank_slip(m, q):
    return m.r32(BANK + B_SLIP + 4 * q)


def bank_valid(m, q):
    return m.r8(BANK + B_VALID + q)


def latch(m, q, k):
    return struct.unpack("<3i", m.uc.mem_read(BANK + B_LATCH + (q * 4 + k) * 12, 12))


def slip_f(slip, length, clip):
    return (slip * length // clip) % length


# ====================================================================================================== 1. the image
def branch(at, data=img):
    """target of the 4-byte bl / b.w at `at`, and which one it is"""
    h1, h2 = struct.unpack_from("<HH", data, at - BASE)
    s = (h1 >> 10) & 1
    i1, i2 = 1 - (((h2 >> 13) & 1) ^ s), 1 - (((h2 >> 11) & 1) ^ s)
    off = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    off -= (1 << 25) if s else 0
    kind = "bl" if h1 >> 11 == 0b11110 and h2 & 0xD000 == 0xD000 else "b.w" if h1 >> 11 == 0b11110 and h2 & 0xD000 == 0x9000 else "?"
    return kind, at + 4 + off


cs = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def code(name, n):
    a = S[name]
    return [(i.address, i.mnemonic, i.op_str) for i in cs.disasm(img[a - BASE:a - BASE + n], a)]


sites = {"H1 (segment start, FUN_08065550)": (0x0806578C, PREFETCH, "clipwin_seg_start_b"),
         "H1' (slice segment start, FUN_08065290)": (0x0806541A, PREFETCH, "clipwin_slice_start_b"),
         "F (set-value text, FUN_080b0728)": (0x080B0746, 0x080B0528, "clipwin_format"),
         "F (type-1 turn text)": (0x080B0E18, 0x080B0528, "clipwin_format"),
         "K (type-1 turn stepper)": (0x080B0DDE, 0x080B0B74, "clipwin_turn")}
for what, (at, was, now) in sites.items():
    check(f"{what} at {at:#010x}: stock 'bl {was:#010x}' is now 'bl {now}'",
          branch(at, stock) == ("bl", was) and branch(at) == ("bl", S[now]), (branch(at, stock), branch(at)))
check("H2: the segment reader's call at 0x08066622 is still JOEBOX's 'bl clip_read_b' (stock: bl 0x080662e4)",
      branch(0x08066622, stock) == ("bl", 0x080662E4) and branch(0x08066622) == ("bl", S["clip_read_b"]))
c = code("clip_read_b", 8)
check("clip_read_b: 'add.w r1, fp, #0x14c' then 'b.w clipwin_read' (was b.w clip_read)",
      [x[1] for x in c] == ["add.w", "b.w"] and c[0][2] == "r1, fp, #0x14c" and branch(c[1][0]) == ("b.w", S["clipwin_read"]), c)
for thunk, slot, target in (("clipwin_seg_start_b", "#0x20", "clipwin_seg_start"), ("clipwin_slice_start_b", "#4", "clipwin_slice_start")):
    c = code(thunk, 8)
    check(f"{thunk}: r2 = the slot at [sp, {slot}], r3 = r4 (the pad), then b.w {target}",
          [(x[1], x[2]) for x in c[:2]] == [("ldr", f"r2, [sp, {slot}]"), ("mov", "r3, r4")] and branch(c[2][0]) == ("b.w", S[target]), c)
sizes = {l.split()[3]: int(l.split()[1], 16) for l in subprocess.run(["arm-none-eabi-nm", "-S", "out/cave.elf"], capture_output=True,
                                                                    text=True, check=True).stdout.splitlines() if len(l.split()) == 4}
duck = code("duck_block", sizes["duck_block"])
order = [int(x[2].lstrip("#"), 16) for x in duck if x[1] == "bl"]
tail = img[S["duck_block"] - BASE:S["duck_block"] - BASE + sizes["duck_block"]]
check("duck_block: lfo_tick, insert_tick, then clipwin_tick (once a block, before the pads), then the tail call into the "
      "engine's control tick (0x08053164)", order[-3:] == [S["lfo_tick"], S["insert_tick"], S["clipwin_tick"]]
      and order.count(S["clipwin_tick"]) == 1 and struct.pack("<I", 0x08053165) in tail, [hex(t) for t in order])
for page in (0x080EF990, 0x080EF288):
    got = struct.unpack_from("<36H", img, page - BASE)
    check(f"Clip Pos page at {page:#010x}: Loop Mode, Beat Count, Quant Size, Sync, Slip (0x1c9), then 31 empty slots",
          got == (0x8D, 0xD2, 0x47, 0x94, P_SLIP) + (0,) * 31 and struct.unpack_from("<36H", stock, page - BASE) == (0x8D, 0xD2, 0x47, 0x94) + (0,) * 32,
          [hex(x) for x in got[:8]])
touched = {"FUN_08065550": (0x08065550, 936, [0x0806578C]), "FUN_08065290": (0x08065290, 688, [0x0806541A]),
           "FUN_08066454": (0x08066454, 856, [0x08066622]), "FUN_080662e4 (stock clip reader)": (0x080662E4, 368, []),
           "FUN_080b0728": (0x080B0728, 36, [0x080B0746]), "FUN_080b0d54": (0x080B0D54, 772, [0x080B0DDE, 0x080B0E18]),
           "the Clip Pos page": (0x080EF990, 72, [0x080EF998]), "its class-0x4c copy": (0x080EF288, 72, [0x080EF290])}
for name, (start, size, at) in touched.items():
    allowed = {a + i for a in at for i in range(4 if a < 0x080EF000 else 2)}
    diff = {start + i for i in range(size) if img[start - BASE + i] != stock[start - BASE + i]}
    check(f"{name}: no stock byte changes outside the hook sites ({', '.join(hex(a) for a in at) or 'none'})",
          diff <= allowed and (not at or diff), sorted(hex(a) for a in diff - allowed))

# ---- master_alloc: the bank is cleared at every boot and fits the block
maps(e)
allocs = []
e.stub(0x0806AA80, lambda: allocs.append(("line", e.arg(0), e.arg(1))))
e.stub(0x0804436C, lambda: allocs.append(("perm", e.arg(0))), value=BLOCK)
e.w32(BANK, CW_MAGIC)
e.call("master_alloc", 0x24076000, 192000)
e.meter_up()
check("master_alloc: one 0x84100-byte block, cw_bank's 0x800 bytes at its end (+0x83900), its magic cleared each boot",
      allocs[-1] == ("perm", 0x84100) and BANK + 0x800 == BLOCK + 0x84100 and u32(e, BANK) == 0, (allocs, hex(u32(e, BANK))))
del e.stubs[0x0806AA80], e.stubs[0x0804436C]

# ====================================================================================================== 2. registration
regs = []


def registrar(m, table):
    """the stock pad-parameter registrar run whole; every registration recorded at the one writer (FUN_0808c0a8)"""
    out = []

    def write():
        a = m.arg(1)
        pid, typ = m.r16(a), m.r8(a + 2)
        lab, lo, hi, xml = u32(m, a + 4), m.r32(a + 0x10), m.r32(a + 0x14), u32(m, a + 0x18)
        out.append((pid, typ, m.cstr(lab) if lab else None, lo, hi, m.cstr(xml) if xml else None))
    m.uc.hook_add(UC_HOOK_CODE, lambda *a: write(), begin=0x0808C0A8, end=0x0808C0A8)
    m.stub(0x0804436C, value=table)
    m.call(0x0808C158, 0, count=20_000_000)
    del m.stubs[0x0804436C]
    return out


TABLE = 0x24040000
regs = registrar(e, TABLE)
st_m = Emu(STOCK, "out/cave.elf")
maps(st_m)
stock_regs = registrar(st_m, TABLE)
ours = [r for r in regs if r[0] == P_SLIP]
check("the patched registrar registers 0x1c9 once: 'Slip:', type 1 (int), -3840 .. 3840, saved as 'clipslip'",
      ours == [(P_SLIP, 1, "Slip:", -3840, 3840, "clipslip")], ours)
check("the label fits the screen (<= 9 characters)", ours and len(ours[0][2]) <= 9)
check("stock registers nothing in 0x1c8 .. 0x1cf; the patched image only 0x1c9 there",
      not [r for r in stock_regs if 0x1C8 <= r[0] <= 0x1CF] and [r[0] for r in regs if 0x1C8 <= r[0] <= 0x1CF] == [P_SLIP],
      [hex(r[0]) for r in regs if 0x1C8 <= r[0] <= 0x1CF])
xmls = [r[5] for r in regs if r[5]]
dups = sorted({x for x in xmls if xmls.count(x) > 1})
stock_xmls = [r[5] for r in stock_regs if r[5]]
check("'clipslip' is unique among every registered xml name (and new to the image)",
      xmls.count("clipslip") == 1 and "clipslip" not in stock_xmls and b"clipslip" not in stock)
if dups:
    info(f"xml names registered more than once (stock's own: {sorted({x for x in stock_xmls if stock_xmls.count(x) > 1})}): {dups}")
check(f"the patched registrar still registers stock's {len(stock_regs)} ids under their stock xml names (JOEBOX relabels a few)",
      {(r[0], r[5]) for r in stock_regs} <= {(r[0], r[5]) for r in regs}, sorted({(r[0], r[5]) for r in stock_regs} - {(r[0], r[5]) for r in regs}))

# ---- the type-3 (pad) store built by the stock builder, with lfo_defaults -> insert_defaults -> clipwin_defaults in it
PSTORE, TYPE, PARR = 0x24073000, 0x24073100, 0x24074000
e.uc.mem_write(PSTORE, bytes(0x20))
e.uc.mem_write(TYPE, b"\x03")
e.stub(0x0804436C, lambda: e.uc.mem_write(PARR, bytes(e.arg(0))), value=PARR)
e.call(0x08093F20, PSTORE, TYPE)
del e.stubs[0x0804436C]
count, cap = e.r16(PSTORE + 10), e.r16(PSTORE + 12)
entries = [struct.unpack_from("<HHi", bytes(e.uc.mem_read(PARR + 8 * i, 8))) for i in range(count)]
ids = [x[0] for x in entries]
check(f"a new pad's store (FUN_08093f20, type 3) holds Slip 0 once ({count} of {cap} entries used)",
      ids.count(P_SLIP) == 1 and entries[ids.index(P_SLIP)][2] == 0 and cap == 96 and count < cap, (count, cap, ids[-4:]))

# ====================================================================================================== the poll (unit)
sdram(e)
e.uc.mem_write(BANK, bytes(0x800))
values = {0: 960, 1: -30, 2: 7, 3: 3839, 4: -3840, 5: 5000, 6: -9999, 9: 1}
for q in range(16):
    store(e, q, {0x4: 500} if q == 7 else {0x4: 500, P_SLIP: values.get(q, 0)})
e.call("clipwin_tick")
check("clipwin_tick with a fresh block: the bank is set up (magic 'CWN1') and one pad polled per call",
      u32(e, BANK) == CW_MAGIC and e.r32(BANK + 4) == 1 and bank_slip(e, 0) == 960 and bank_slip(e, 1) == 0,
      (hex(u32(e, BANK)), e.r32(BANK + 4), bank_slip(e, 0), bank_slip(e, 1)))
for _ in range(15):
    e.call("clipwin_tick")
want = [max(-3840, min(3840, values.get(q, 0))) for q in range(16)]
check("sixteen calls read all sixteen pads' stores (row * 0xf0 + col * 0x30), clamped to +-3840; a store without the id reads 0",
      [bank_slip(e, q) for q in range(16)] == want, [bank_slip(e, q) for q in range(16)])

# the guarded drop on a cached pad
UPAD = 0x24060000


def upad(q, cls=0x4C):
    e.uc.mem_write(UPAD, bytes(0xC00))
    e.uc.mem_write(UPAD + 4, bytes([cls]))
    e.w32(UPAD + 0x18, (q // 4) << 8 | q % 4)
    for k, (act, done, delay, first) in enumerate(((1, 0, 500, 0), (1, 0, 500, 1), (1, 0, 0, 0), (0, 0, 500, 0))):
        b = UPAD + 0x30 + k * 0x70
        e.uc.mem_write(b, bytes([act, done]))
        e.w32(b + 0x20, delay)
        e.uc.mem_write(b + 0x3C, bytes([first]))
    e.w32(BANK + B_PAD + 4 * q, UPAD)


def done():
    return [e.r8(UPAD + 0x31 + k * 0x70) for k in range(4)]


def tick_until(q):
    for _ in range(16):
        e.call("clipwin_tick")
        if (e.r32(BANK + 4) - 1) & 15 == q:
            return


upad(9)
store(e, 9, {0x4: 500, P_SLIP: 480})
tick_until(9)
check("a Slip change drops the pad's pending segment (active, not done, delay > 0) and nothing else: not a pending "
      "launch (+0x3c set), not the sounding one (delay 0), not an inactive slot", done() == [1, 0, 0, 0] and bank_slip(e, 9) == 480, done())
upad(9)
tick_until(9)
check("the same value polled again: no drop", done() == [0, 0, 0, 0], done())
for what, cls, cell_q in (("a cached object that is not a class-B pad", 0x48, 9), ("a cached pad whose cell moved", 0x4C, 10)):
    upad(9, cls)
    e.w32(UPAD + 0x18, (cell_q // 4) << 8 | cell_q % 4)
    store(e, 9, {0x4: 500, P_SLIP: -480 if cell_q == 9 else 300})
    tick_until(9)
    check(f"{what}: the new value is taken, nothing is dropped", done() == [0, 0, 0, 0] and bank_slip(e, 9) in (-480, 300), done())
sdram(e, False)
e.uc.mem_write(BANK, bytes(16))
e.call("clipwin_tick")
check("no SDRAM block (master_alloc did not run): clipwin_tick writes nothing", bytes(e.uc.mem_read(BANK, 16)) == bytes(16))


# ====================================================================================================== the rig
POS, SID, AT, FET = 2, 6, 7, 12          # a read row: block, slot, POSition (virtual), n, rate, frac, Segment ID, the
#                                         sample it sounds AT; then return, used, frac, buffer, its FETches, clip_read ran


class Rig:
    """The class-B pad process block by block (notes/re/a2's Rig, with a1's Rig2 input-bank buffers), on an Emu.

    One pad, one engine; pre_block runs where duck_block would (clipwin_tick), then the block method, then the clock
    advance. Logs: reads at the segment reader's call (block, slot, virtual position, n, rate, frac, then the result:
    return, used, frac, buffer, the fetches made inside it, whether filter.c's clip_read ran), fetches, prefetches,
    every segment start (H1 and H1'), each segment's mixed samples, the summed output, the messages to the app."""

    def __init__(self, frames=96000, src_rate=48000, bpm=120.0, stereo=False, cell=0, image=IMAGE, block=True,
                 bypass=False, dc=False):
        self.m = m = Emu(image, "out/cave.elf")
        uc = self.uc = m.uc
        maps(m)
        self.patched = image == IMAGE
        self.heap = HEAP
        self.len, self.src_rate, self.stereo, self.dc = frames, src_rate, stereo, dc
        self.q = (cell >> 8 & 3) * 4 + (cell & 3)
        sdram(m, block)
        m.stubs[0x0804436C] = lambda: m.ret(self.alloc(m.arg(0)))
        m.stub(0x08043DE4, value=0)
        self.src = self.alloc(0x40)
        m.w32(self.src + 0x24, 0x1234)
        uc.mem_write(self.src + 0x1C, bytes([int(stereo)]))
        m.stubs[SRC_LEN] = lambda: m.ret(self.len)
        m.stubs[0x0806377C] = lambda: m.ret(self.src_rate)
        m.stub(0x0806371C, value=1)
        self.prefetches, self.fetches, self.hints, self.reading = [], [], [], None
        m.stub(PREFETCH, self._prefetch, value=0)
        m.stub(FETCH, self._fetch_mono, value=0)
        m.stub(FETCH2, self._fetch_stereo, value=0)
        self.engine = eng = self.alloc(0x30000, 0x100)
        self.ctx = ctx = eng + 0x128E0
        m.w32(ctx, eng)
        uc.mem_write(eng + 0x18, struct.pack("<f", bpm))
        uc.mem_write(eng + 0x38, b"\x01")
        self._buffers()
        self.pad = pad = self.alloc(3000)
        m.call(CTOR, pad)
        m.w32(pad + 0x24, self.src)
        m.w32(pad + 0x18, cell)
        uc.mem_write(pad + 0xB79, b"\x01")
        self.queue = ctx + {0x400: 4, 0x401: 0x608}.get(cell, ((cell >> 8 & 0xFF) + ((cell & 0xFF) + (cell >> 16) * 4) * 4 + 2) * 0x604 + 4)
        self.block, self._S0 = 0, 0
        self.posted, self.reads, self.mix, self.out, self.made = [], [], [], [], []
        self.pre_block = None
        self.sid, self.nsid, self.cur, self.in_clip_read = {}, 0, None, False
        for a, fn in ((SITE_H1, self._on_h1), (SITE_H1P, self._on_h1p), (SITE_READ, self._on_read),
                      (SITE_READ + 4, self._on_read_ret), (SITE_MIX_L, lambda: self._on_mix(0)),
                      (SITE_MIX_R, lambda: self._on_mix(1))):
            uc.hook_add(UC_HOOK_CODE, lambda u, a_, s_, d_, fn=fn: fn(), begin=a, end=a)
        if self.patched:
            uc.hook_add(UC_HOOK_CODE, lambda *a: setattr(self, "in_clip_read", True), begin=S["clip_read"], end=S["clip_read"])
        if bypass and self.patched:
            go = lambda target: (lambda: uc.reg_write(UC_ARM_REG_PC, target | 1))
            m.stubs[S["clipwin_seg_start_b"]] = go(PREFETCH)
            m.stubs[S["clipwin_slice_start_b"]] = go(PREFETCH)
            m.stubs[S["clipwin_read"]] = go(S["clip_read"])
            m.stub(S["clipwin_tick"])

    def alloc(self, n, align=8):
        a = (self.heap + align - 1) & ~(align - 1)
        self.heap = a + n
        self.uc.mem_write(a, bytes(n))
        return a

    def _prefetch(self):
        pos = struct.unpack("<i", struct.pack("<I", self.m.arg(1)))[0]
        self.prefetches.append((self.block, pos))
        if self.reading is not None:                          # a hint made inside a segment read (H2): whose read
            self.hints.append((self.block, pos, self.reading))

    def _data(self, pos, n, right=False):
        q = np.arange(pos, pos + n, dtype=np.int64)
        v = np.ones(n) if self.dc else (q + 1) * RAMP * (-1.0 if right else 1.0)
        return np.where((q >= 0) & (q < self.len), v, 0.0).astype(np.float32).tobytes()

    def _fetch_mono(self):
        m = self.m
        dst, n, pos = m.arg(1), m.arg(2), struct.unpack("<i", struct.pack("<I", m.arg(3)))[0]
        self.fetches.append((self.block, pos, n))
        self.uc.mem_write(dst, self._data(pos, n))

    def _fetch_stereo(self):
        m = self.m
        n, pos = m.arg(3), m.r32(self.uc.reg_read(UC_ARM_REG_SP))
        self.fetches.append((self.block, pos, n))
        self.uc.mem_write(m.arg(1), self._data(pos, n))
        self.uc.mem_write(m.arg(2), self._data(pos, n, True))

    def _buffers(self):
        def mk(addr, cap=N):
            l, r = self.alloc(cap * 4), self.alloc(cap * 4)
            self.uc.mem_write(addr, struct.pack("<IIIIBBxx", cap, 0, l, r, 1, 0))
            return l
        for k in range(3):
            mk(self.ctx + 0x151FC + k * 0x14)
        self.buses = [(self.ctx + 0x150E4 + k * 0x14, mk(self.ctx + 0x150E4 + k * 0x14)) for k in range(16)]
        for k, cap in enumerate((N, 0x400, N, N)):         # Rig2: the input bank (the reader's scratch is #1)
            mk(self.ctx + 0x1583C + k * 0x14, cap)

    def i64(self, a):
        return struct.unpack("<q", self.uc.mem_read(a, 8))[0]

    @property
    def S(self):
        return self.i64(self.engine)

    def goto(self, at):
        e_ = self.engine
        self.uc.mem_write(e_ + 8, bytes(16))
        self.uc.mem_write(e_, struct.pack("<q", at - N))
        self.m.call(ADVANCE, e_, N)

    def set_bpm(self, bpm):
        """a tempo change as a re-anchored tempo state looks: origin = (ticks now, samples now)"""
        self.uc.mem_write(self.engine + 8, struct.pack("<qq", self.i64(self.engine + 0x30), self.S))
        self.uc.mem_write(self.engine + 0x18, struct.pack("<f", bpm))

    def post(self, mtype, offset=0, w8=0, wc=0, w10=0, w14=0):
        n = self.m.r32(self.queue + 0x600)
        self.uc.mem_write(self.queue + 0x18 * n, struct.pack("<BxxxIIIII", mtype, offset, w8, wc, w10 & 0xFFFFFFFF, w14))
        self.m.w32(self.queue + 0x600, n + 1)

    def cell(self):
        return u32(self.m, self.pad + 0x18)

    def note_on(self, note=60, vel=100):
        self.post(2, 0, 0, note, vel)

    def param(self, pid, value):
        self.post(0x39, 0, self.cell(), pid, value)

    def params(self, beats=4, quant=3, sync=3, loop=1, launch=2, mode=1):
        for pid, v in ((0x8B, mode), (0x93, launch), (0x8D, loop), (0xD2, beats), (0x47, quant), (0x94, sync)):
            msg = self.alloc(0x18)
            self.uc.mem_write(msg, struct.pack("<BxxxIIII", 0x39, 0, self.cell(), pid, v & 0xFFFFFFFF))
            self.m.call(PSET, self.pad, self.engine, msg, self.ctx)

    def markers(self, frames):
        self.post(0x3C, 0, self.cell(), 0, 1000)
        for f in frames:
            self.post(0x3C, 0, self.cell(), f, 1)

    def _new(self, k, how, step, start, stock_pos, launch=0):
        self.nsid += 1
        self.sid[k] = self.nsid
        self.made.append(dict(sid=self.nsid, k=k, how=how, step=step, start=start, block=self.block, stock_pos=stock_pos, launch=launch,
                              valid_before=(bank_valid(self.m, self.q) >> k) & 1 if self.patched else 0,
                              h1_before=(self.m.r8(BANK + B_H1 + self.q) >> k) & 1 if self.patched and self.q < 16 else 0,
                              prefetch_at=len(self.prefetches)))

    def _on_h1(self):
        uc, m = self.uc, self.m
        k = m.r32(uc.reg_read(UC_ARM_REG_SP) + 0x20)
        self._new(k, "H1", uc.reg_read(UC_ARM_REG_R5), self.i64(self.pad + 0x38 + k * 0x70), uc.reg_read(UC_ARM_REG_R1),
                  uc.reg_read(UC_ARM_REG_R8))

    def _on_h1p(self):
        uc, m = self.uc, self.m
        k = m.r32(uc.reg_read(UC_ARM_REG_SP) + 4)
        self._new(k, "H1'", None, None, uc.reg_read(UC_ARM_REG_R1))

    def _on_read(self):
        uc, m = self.uc, self.m
        k = (uc.reg_read(UC_ARM_REG_R4) - self.pad - 0x30) // 0x70
        sp = uc.reg_read(UC_ARM_REG_SP)
        n = m.r32(sp)
        pos = uc.reg_read(UC_ARM_REG_R2) | uc.reg_read(UC_ARM_REG_R3) << 32
        self.cur = (k, n)
        self._ptrs = [u32(m, sp + o) for o in (4, 8, 0x14)]
        self._f0 = len(self.fetches)
        self.in_clip_read = False
        self.reads.append([self.block, k, pos, n, uc.reg_read(UC_ARM_REG_S0), u32(m, self._ptrs[1]), self.sid.get(k),
                           self._S0 + N - n])
        self.reading = self.sid.get(k)

    def _on_read_ret(self):
        m = self.m
        self.reading = None
        self.reads[-1] += [self.uc.reg_read(UC_ARM_REG_R0)] + [u32(m, p) for p in self._ptrs] + \
            [tuple(self.fetches[self._f0:]), self.in_clip_read]

    def _on_mix(self, ch):
        if self.cur is None:
            return
        uc = self.uc
        k, n = self.cur
        if ch == 1 or not self.stereo:
            self.cur = None
        cnt = uc.reg_read(UC_ARM_REG_R1)
        v = np.frombuffer(bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R0), 4 * cnt)), np.float32).copy()
        self.mix.append((self._S0 + (N - n), self.sid.get(k), ch, v))

    def step_block(self):
        m, uc = self.m, self.uc
        self._S0 = self.S
        if self.pre_block:
            self.pre_block(self)
        z = bytes(N * 4)
        for a, buf in self.buses:
            m.w32(a + 4, 0)
            uc.mem_write(a + 0x10, b"\x01")
            uc.mem_write(buf, z)
        m.call(BLOCKM, self.pad, self.ctx, count=20_000_000)
        acc = np.zeros(N, np.float32)
        for a, buf in self.buses:
            acc += np.frombuffer(bytes(uc.mem_read(buf, N * 4)), np.float32)
        self.out.append(acc)
        q = self.ctx + 0x15238                                # the app queue: log, then drained
        for i in range(m.r32(q + 0x600)):
            b = bytes(uc.mem_read(q + 0x18 * i, 0x18))
            self.posted.append((self.block, b[0], struct.unpack("<5I", b[4:])))
        m.w32(q + 0x600, 0)
        m.w32(self.queue + 0x600, 0)                          # the engine drains the pad queues (FUN_0805f3b8)
        m.call(ADVANCE, self.engine, N)                       # then the clock advance, as at 0x080531e0
        self.block += 1

    def run(self, blocks):
        for _ in range(blocks):
            self.step_block()
        return self

    def seg(self, k):
        b = self.pad + 0x30 + k * 0x70
        return dict(active=self.m.r8(b), done=self.m.r8(b + 1), delay=self.m.r32(b + 0x20), first=self.m.r8(b + 0x3C),
                    step=u32(self.m, b + 0x34))

    def layer(self, L=0):
        b = self.pad + 0x260 + L * 0x410
        return dict(active=self.m.r8(b), launch_tick=self.i64(b + 0x140), armed=self.m.r8(b + 0x148))

    def seam_reads(self):
        return [r for r in self.reads if not r[-1]]


def poll(r):
    r.m.call("clipwin_tick")


def starts(r):
    """each segment that sounded: (its first sample, step, stock start frame), in order"""
    first = {}
    for x in r.reads:
        first.setdefault(x[SID], x[AT])
    return sorted((first[m_["sid"]], m_["step"], m_["start"]) for m_ in r.made if m_["sid"] in first)


def scenario(frames=96000, beats=4, quant=3, sync=3, at=287000, blocks=900, slip=0, others=None, pre=None, setup=None,
             note=60, launch=2, **kw):
    """A Clip pad (Launch Toggle, Loop On) with Slip `slip` in its store, the app's other pads per `others`; the poll
    has seen the stores before the note (as on the unit, where the app writes its store before it posts)."""
    r = Rig(frames=frames, **kw)
    d = dict(others or {})
    d[r.q] = slip
    slips(r.m, d)
    if r.patched:
        for _ in range(16):
            poll(r)

    def pb(rr):
        if rr.patched:
            poll(rr)
        if pre:
            pre(rr)
    r.pre_block = pb
    r.params(beats=beats, quant=quant, sync=sync, launch=launch)
    if setup:
        setup(r)
    r.goto(at)
    r.note_on(note)
    return r.run(blocks)


def same(a, b, silent=False):
    """everything the two runs did, bit for bit: reads (and their results and fetches), prefetches, mixed output, posts"""
    strip = lambda rs: [x[:SID] + x[AT:-1] for x in rs]            # the segment numbering and clip_read flag aside
    d = dict(reads=strip(a.reads) == strip(b.reads), fetches=a.fetches == b.fetches, prefetches=a.prefetches == b.prefetches,
             out=len(a.out) == len(b.out) and all(np.array_equal(x.view(np.uint32), y.view(np.uint32)) for x, y in zip(a.out, b.out)),
             posted=a.posted == b.posted)
    return all(d.values()) and (silent or len(a.reads) > 0), d


def decode(rd, rr, ch=0):
    """a gain run (source 1.0) and a ramp run of the same scenario -> per sample: summed gain, sounding segments, and
    when one segment sounds, which one and the source frame it plays"""
    a = [x for x in rd.mix if x[2] == ch]
    b = [x for x in rr.mix if x[2] == ch]
    assert len(a) == len(b) and all(x[0] == y[0] and x[1] == y[1] and len(x[3]) == len(y[3]) for x, y in zip(a, b))
    s = np.concatenate([x[0] + np.arange(len(x[3])) for x in a])
    sid = np.concatenate([np.full(len(x[3]), x[1] or 0) for x in a])
    g = np.concatenate([x[3] for x in a]).astype(np.float64)
    v = np.concatenate([y[3] for y in b]).astype(np.float64)
    base = int(s.min())
    idx = s - base
    live = np.abs(g) > 1e-7
    cnt = np.bincount(idx, weights=live.astype(float))
    single = live & (cnt[idx] == 1)
    frame, who = np.full(len(cnt), np.nan), np.zeros(len(cnt), np.int64)
    frame[idx[single]] = (-1.0 if ch else 1.0) * v[single] / g[single] / RAMP - 1
    who[idx[single]] = sid[single]
    return dict(base=base, gain=np.bincount(idx, weights=g), cnt=cnt, frame=frame, sid=who, rig=rr)


def audio(**kw):
    return decode(scenario(dc=True, **kw), scenario(**kw))


def window(ref, cw):
    lo, hi = max(ref["base"], cw["base"]), min(ref["base"] + len(ref["gain"]), cw["base"] + len(cw["gain"]))
    cut = lambda d, key: d[key][lo - d["base"]:hi - d["base"]]
    return lo, {k: (cut(ref, k), cut(cw, k)) for k in ("frame", "gain", "sid")}


def shifted(ref, cw, sf, length, edge=0):
    """samples where one segment sounds in both runs: max |cw frame - (stock frame + slip_f) mod len| (circular), the
    count of samples off by more than 0.05 frame, and of samples whose summed gain differs. `edge` > 0 leaves out the
    samples within that many frames of the file's ends in either run (the kernel's support: there stock interpolates
    into the silence after the file, the Clip Window into the file's start)."""
    lo, w = window(ref, cw)
    fs, fc = w["frame"]
    gs, gc = w["gain"]
    ok = ~np.isnan(fs) & ~np.isnan(fc)
    want = np.mod(fs + sf, length)
    near = lambda f: (f < edge) | (f > length - 1 - edge)
    if edge:
        ok &= ~near(fs) & ~near(want)
    err = np.abs(fc - want)
    err = np.minimum(err, length - err)[ok]
    gdiff = np.abs(gs - gc) > 1e-6
    if edge:
        gdiff &= ~(near(np.nan_to_num(fs, nan=length / 2)) | near(np.nan_to_num(fc, nan=length / 2)))
    return int(ok.sum()), float(err.max()) if len(err) else 9e9, int((err > 0.05).sum()), int(gdiff.sum())


def wraps(d, length):
    """how often the frame played by one segment jumps from the file's end back to its start"""
    f, sid = d["frame"], d["sid"]
    i = np.where(~np.isnan(f[:-1]) & ~np.isnan(f[1:]) & (sid[:-1] == sid[1:]) & (sid[:-1] > 0))[0]
    return int((f[i + 1] - f[i] < -length / 2).sum())


# ====================================================================================================== 3. off = stock
off_cases = [("the matched file (96 000 frames, 4 beats), Quant 1 bar, Sync 1/4", dict(frames=96000, at=287000, cell=0x102)),
             ("a fast file (88 615 frames, fps 22 153.75)", dict(frames=88615, at=287000, cell=0x0)),
             ("88 615 frames, the note 300 samples after the bar", dict(frames=88615, at=288300, cell=0x303)),
             ("Sync None", dict(frames=96000, at=287000, sync=6, cell=0x201))]
for name, sc in off_cases:
    q = (sc["cell"] >> 8) * 4 + (sc["cell"] & 3)
    others = {p: 960 for p in range(16) if p != q}
    cw = scenario(slip=0, others=others, **sc)
    by = scenario(slip=0, others=others, bypass=True, **sc)
    st = scenario(slip=0, image=STOCK, **sc)
    ok1, d1 = same(cw, by)
    ok2, d2 = same(cw, st)
    check(f"Slip 0, {name} (pad {q + 1}; every other pad's Slip 960): each read (position, n, rate, frac, used, buffer, "
          "fetches), prefetch, mixed sample and message identical to the hooks taken out", ok1, d1)
    check("  ...and to the stock 3.1.9 image", ok2, d2)
    check("  ...no latch made, the poll did run", bank_valid(cw.m, q) == 0 and u32(cw.m, BANK) == CW_MAGIC and bank_slip(cw.m, (q + 1) % 16) == 960)
    st_ = starts(cw)
    if "matched" in name:
        check("  stock as measured (notes/re/a2): launch on the bar at 288 000 (+0x140 = 11 520, msg 0x1d), steps at "
              "312 000 / 336 000 / 360 000 on frames 24 000 j, the wrap at 384 000 back to frame 0",
              cw.layer()["launch_tick"] == 11520 and [b for b, t, _ in cw.posted if t == 0x1D] and
              st_[:5] == [(288000, 0, 0), (312000, 1, 24000), (336000, 2, 48000), (360000, 3, 72000), (384000, 0, 0)],
              (cw.layer(), st_[:5]))
    if "fast" in name:
        check("  stock as measured: steps start on (int)(j x 22153.75) = 0, 22 153, 44 307, 66 461, on the same grid",
              st_[:4] == [(288000, 0, 0), (312000, 1, 22153), (336000, 2, 44307), (360000, 3, 66461)], st_[:4])
    if "300" in name:
        check("  stock as measured: a launch 300 samples late starts at once on frame 0 (+0x140 = 11 532), step 1 still "
              "on the grid (312 000)", cw.layer()["launch_tick"] == 11532 and st_[:2] == [(288300, 0, 0), (312000, 1, 22153)],
              (cw.layer(), st_[:2]))
    if "None" in name:
        check("  stock as measured: Sync None, one segment for the whole file, restarted every len - 257 samples",
              st_[:2] == [(288000, 0, 0), (288000 + 96000 - 257, 0, 0)], st_[:3])

# ====================================================================================================== 4. Slip
slip_cases = [("matched 96 000, launch on the bar", dict(frames=96000, at=287000, blocks=900), (0, 960, -30, 7, 3839)),
              ("fast 88 615, launch on the bar", dict(frames=88615, at=287000, blocks=900), (0, 960, -30, 7, 3839)),
              ("fast 88 615, launch 300 samples late", dict(frames=88615, at=288300, blocks=900), (960, -30, 3839)),
              ("16 beats (384 000), Quant 1 beat < Sync 1 bar, note at tick 8 000", dict(frames=384000, beats=16, quant=5, sync=1, at=200000, blocks=1000), (960, -30, 3839)),
              ("fast 88 615, default Sync 1/16", dict(frames=88615, sync=5, at=287000, blocks=900), (960, 7, 3839))]
for name, sc, values in slip_cases:
    sc = dict(sc, cell=0x102)
    ref = audio(**sc)
    clip = sc.get("beats", 4) * 960
    for slip in values:
        cw = audio(slip=slip, **sc)
        sf = slip_f(slip, sc["frames"], clip)
        n, err, bad, gd = shifted(ref, cw, sf, sc["frames"])
        r = cw["rig"]
        h1 = [m_ for m_ in r.made if m_["how"] == "H1"]
        pf = [r.prefetches[m_["prefetch_at"]][1] for m_ in h1]
        lat = [latch(r.m, 6, k) for k in range(4) if bank_valid(r.m, 6) >> k & 1]
        check(f"{name}, Slip {slip} (slip_f {sf}): every sounding sample plays (stock frame + slip_f) mod len "
              f"({n} samples, max error {err:.4f} frame), summed gain = stock's at every sample",
              n > 80000 and err <= 0.02 and bad == 0 and gd == 0, (n, err, bad, gd))
        if slip:
            wr = wraps(cw, sc["frames"])
            check(f"  H1 latched every segment start ({len(h1)}): slot k from the caller's frame, (0, len, slip_f), and "
                  f"prefetched where it will read; the content wraps inside a segment {wr} time(s), {len(r.seam_reads())} "
                  "block(s) read by clipwin_read's own fetch (across the file end, or within 3 frames of its start)",
                  h1 and pf == [max(0, (m_["start"] + sf) % sc["frames"] - 8) for m_ in h1] and lat and
                  all(x == (0, sc["frames"], sf) for x in lat) and len(r.seam_reads()) >= min(wr, 1),
                  (pf[:4], [m_["start"] for m_ in h1][:4], lat, len(r.seam_reads())))

# more of what stock does around a slipped pad: it keeps doing it, every sample still stock + slip_f
for name, sc, slip in (("a retrigger (Launch Trigger, Quant 1 beat, a second note in step 1): two voices' segments",
                        dict(launch=0, quant=5, pre=lambda rr: rr.note_on() if rr.block == 200 else None), 960),
                       ("a live Sync change (1/4 -> 1/2 in step 1): stock re-grids the playing segment, re-makes the pending one",
                        dict(pre=lambda rr: rr.param(0x94, 2) if rr.block == 265 else None), -30),
                       ("a tempo change (120 -> 126 BPM in step 1)", dict(pre=lambda rr: rr.set_bpm(126.0) if rr.block == 265 else None), 7)):
    sc = dict(sc, cell=0x102, frames=88615)
    ref, cw = audio(**sc), audio(slip=slip, **sc)
    sf = slip_f(slip, 88615, 3840)
    n, err, bad, gd = shifted(ref, cw, sf, 88615)
    launches = sum(1 for m_ in cw["rig"].made if m_["launch"])
    check(f"{name}, Slip {slip}: every sounding sample plays stock + slip_f ({n} samples, max {err:.4f} frame), summed "
          f"gain = stock's ({launches} launch(es))", n > 50000 and err <= 0.02 and bad == 0 and gd == 0
          and launches == (2 if "retrigger" in name else 1), (n, err, bad, gd, launches))
# clip = ticks per step x steps, not Beat Count x 960, where the steps do not divide the clip
r = scenario(frames=1392000, beats=29, sync=1, slip=3840, cell=0x102, blocks=40)
tps, n_ = r.i64(r.pad + 0x208), u32(r.m, r.pad + 0x210)
got = [latch(r.m, 6, k) for k in range(4) if bank_valid(r.m, 6) >> k & 1]
check(f"Beat Count 29, Sync 1 bar: {n_} steps of {tps} ticks ({tps * n_}, not 27 840); slip_f = floor(3840 x len / {tps * n_})"
      f" = {slip_f(3840, 1392000, tps * n_)} (README 2.4: the product, as the model)",
      (tps, n_) == (3977, 7) and got and all(x == (0, 1392000, slip_f(3840, 1392000, 27839)) for x in got)
      and slip_f(3840, 1392000, 27839) != slip_f(3840, 1392000, 27840), (tps, n_, got))

# the cave writes nothing in the block but its own bank: every write from clipwin.o's code (its static helpers, latch
# and bank, included: the link map gives the object's .text), a launch on the seam (Slip 3839) and a live change
w = []
r = Rig(cell=0x102)
cw_code = [(int(l.split()[1], 16), int(l.split()[1], 16) + int(l.split()[2], 16)) for l in open("out/cave.map")
           if l.split()[:1] and l.split()[0].startswith(".text") and l.rstrip().endswith("out/obj/clipwin.o") and len(l.split()) == 4]
r.uc.hook_add(UC_HOOK_MEM_WRITE, lambda u, acc, addr, size_, v, d: w.append((addr, size_)) if any(
    a <= u.reg_read(UC_ARM_REG_PC) < b for a, b in cw_code) else None, begin=BLOCK, end=BLOCK + 0x100000)
slips(r.m, {6: 3839})
for _ in range(16):
    poll(r)
r.pre_block = lambda rr: (poll(rr), store(rr.m, 6, {0x4: 500, P_SLIP: -30}) if rr.block == 150 else None)
r.params()
r.goto(287000)
r.note_on()
r.run(300)
hit = {name: any(lo <= a - BANK < hi for a, s in w) for name, lo, hi in (("valid", B_VALID, B_LATCH), ("latch", B_LATCH, B_H1),
                                                                         ("h1", B_H1, B_HINTED), ("hinted", B_HINTED, B_SIZE))}
check(f"in a Slip run, every write clipwin.c makes into the SDRAM block lands in cw_bank's {B_SIZE:#x} bytes (of the 0x800 "
      f"reserved; valid, latch, h1 and hinted written: {hit})", cw_code and w and all(hit.values())
      and all(BANK <= a and a + s <= BANK + B_SIZE for a, s in w), (cw_code, sorted({hex(a) for a, s in w if not BANK <= a < BANK + B_SIZE})[:4]))

# H2's seam hint (README 2.6): once a segment reads within 16 384 frames of the region end (the hint's sure reach,
# notes/re/a2), clipwin_read hints rs once for that slot; H1 clears the bit at the next latch
for name, sc, exact in (("96 000 frames, Slip 7, Sync 1/4 (the seam mid-step)", dict(frames=96000, slip=7, blocks=1600), True),
                        ("88 615 frames, Slip 960, Sync 1/4 (a step crosses mid-step, the next starts on the seam)",
                         dict(frames=88615, slip=960, blocks=1400), True),
                        ("88 615 frames, Slip 960, Sync 1/16 (steps shorter than the reach)", dict(frames=88615, slip=960, sync=5, blocks=1400), False)):
    r = scenario(cell=0x102, **sc)
    ln, sf = sc["frames"], slip_f(sc["slip"], sc["frames"], 3840)
    near = {x[SID] for x in r.reads if ln - (x[POS] + sf) % ln <= 16384}          # the rule, from each read's real position
    cross = {}
    for x in r.seam_reads():
        cross.setdefault(x[SID], x[0])
    sids = [s for _, _, s in r.hints]
    lead = sorted(max((b - hb for hb, _, _ in r.hints if 0 <= b - hb <= 300), default=-1) for b in cross.values())
    check(f"seam hint, {name}: {len(r.hints)} hint(s) from clipwin_read, all at rs = 0, one per segment, from exactly the "
          f"segments that read within 16 384 frames of the end ({len(near)}){', which are the crossing ones' if exact else ''} "
          f"({len(cross)} crossing in {len(r.made)} segments); every seam read hinted {lead} blocks ahead (>= 100); no other "
          "prefetch than H1's", r.hints and all(p == 0 for _, p, _ in r.hints) and len(set(sids)) == len(sids)
          and set(sids) == near and set(cross) <= near and (not exact or set(cross) == near) and len(cross) >= 2
          and min(lead) >= 100 and len(r.prefetches) == len(r.made) + len(r.hints),
          (r.hints[:6], sorted(near), cross, lead, len(r.prefetches), len(r.made)))
r = scenario(frames=96000, slip=-30, cell=0x102, blocks=40)
seam = [x[0] for x in r.seam_reads()][:1]
info(f"observed: a launch whose slipped content starts near the end (Slip -30: frame 95 250) is hinted at rs only at its "
     f"first read (block {r.hints[0][0] if r.hints else None}; H1's own prefetch at {r.prefetches[0][1]}), "
     f"{seam[0] - r.hints[0][0] if seam and r.hints else None} block(s) before its seam read (block {seam[:1]})")

# ====================================================================================================== 5. live change
for frames in (96000, 88615):
    ref = audio(frames=frames, cell=0x102)
    for slip in (480, -7):
        seen = {}

        def change(rr, slip=slip):
            if rr.block == 265:                               # sample 320 920, inside step 1 (312 000 .. 336 000)
                store(rr.m, 6, {0x4: 500, P_SLIP: slip})
            if "at" not in seen and bank_slip(rr.m, 6) == slip:
                seen["at"] = rr.block
        cw = audio(frames=frames, cell=0x102, pre=change)
        r = cw["rig"]
        sf = slip_f(slip, frames, 3840)
        at = seen.get("at", -1)
        lo, w = window(ref, cw)
        fs, fc = w["frame"]
        gs, gc = w["gain"]
        sid = w["sid"][1]
        newer = np.array([r.made[s - 1]["block"] >= at if s else False for s in sid])
        both = ~np.isnan(fs) & ~np.isnan(fc)
        old, new = both & ~newer, both & newer
        e_old = float(np.abs(fc[old] - fs[old]).max()) if old.any() else 9e9
        e_new = np.abs(fc[new] - np.mod(fs[new] + sf, frames))
        e_new = float(np.minimum(e_new, frames - e_new).max()) if new.any() else 9e9
        first_new = min((x[AT] for x in r.reads if x[SID] and r.made[x[SID] - 1]["block"] >= at), default=-1)
        alone = int(np.argmax(new)) + lo
        remade = [(m_["k"], m_["step"], m_["block"]) for m_ in r.made if m_["step"] == 2][:2]
        bdy = (336000 - 287000) // N
        check(f"live {frames} frames, Slip 0 -> {slip} in step 1 (polled at block {at}, {at - 265} block(s) after the store "
              f"changed): the pending step 2 is dropped and re-made in that block, same slot",
              0 <= at - 265 < 16 and len(remade) == 2 and remade[1][2] == at and remade[0][0] == remade[1][0], remade)
        check(f"  everything up to the step boundary (336 000) identical to stock; the sounding segment keeps playing stock "
              f"frames (max {e_old:.4f}); the re-made step starts on the boundary ({first_new}, through stock's crossfade: "
              f"alone from {alone}) and every sample of it plays stock + slip_f (max {e_new:.4f}); summed gain = stock's at "
              "every sample (no added silence)",
              all(np.array_equal(x, y) for x, y in zip(ref["rig"].out[:bdy], r.out[:bdy])) and e_old == 0 and e_new <= 0.02
              and first_new == 336000 and not (np.abs(gs - gc) > 1e-6).any(),
              (e_old, e_new, first_new, int((np.abs(gs - gc) > 1e-6).sum())))

# The row's sign (Thomas, 2026-10-15): + = LATER. Here the row's own value goes in, raw: +480 (+0.480 on screen, half a
# beat) must play every sample 12 000 samples (half a beat at 120 BPM) after stock plays it: content = stock - 12 000.
ref = audio(frames=96000, cell=0x102)


def user_late(rr):
    if rr.block == 0:
        store_raw(rr.m, 6, {0x4: 500, P_SLIP: 480})


cw = audio(frames=96000, cell=0x102, pre=user_late)
n, err, bad, gd = shifted(ref, cw, slip_f(-480, 96000, 3840), 96000)
check(f"the row's sign: Slip +0.480 (raw 480) plays every sample half a beat LATER than stock - content = stock frame "
      f"- 12 000 ({n} samples, max {err:.4f} frame), and the bank holds the content's shift -480",
      n > 25000 and err <= 0.02 and bad == 0 and gd == 0 and bank_slip(cw["rig"].m, 6) == -480, (n, err, bad, gd))

# Sync None: no pending segment to drop - the new Slip waits for the restart (README section 4, open question 8)
seen = {}


def change_none(rr):
    if rr.block == 300:
        store(rr.m, 6, {0x4: 500, P_SLIP: 960})
    if "at" not in seen and bank_slip(rr.m, 6) == 960:
        seen["at"] = rr.block


r = scenario(frames=96000, sync=6, cell=0x102, pre=change_none, blocks=900)
first = {}
for x in r.reads:
    first.setdefault(x[SID], x)
remade = [m_ for m_ in r.made if m_["block"] == seen.get("at")]
restart = first.get(remade[0]["sid"]) if len(remade) == 1 else None
check("Sync None, Slip 0 -> 960 while playing (README section 4, question 8): the playing segment plays on stock; the "
      "pending restart is re-made when the poll sees it, and that restart (len - 257 samples on) plays slipped",
      restart and first[1][FET][0][1] == 0 and restart[AT] == 288000 + 96000 - 257 and restart[FET][0][1] == 24000,
      ([(m_["block"], m_["start"]) for m_ in r.made], seen, [(x[AT], x[FET][:1]) for x in first.values()]))

# the pending launch (droplaunch, armed): never dropped (that would sound it at once, off its bar); the poll latches it
# again in place, so it plays the new Slip from its first read, on its bar
seen = {}


def change_pending(rr):
    if rr.block == 20:                                        # between the note (193 000) and its bar (288 000)
        seen["segs"] = [rr.seg(k) for k in range(4)]
        store(rr.m, 6, {0x4: 500, P_SLIP: 960})
    if "at" not in seen and bank_slip(rr.m, 6) == 960:       # the poll ran just before, in this block
        seen["at"] = rr.block
        seen["pending"] = [rr.seg(k) for k in range(4)]
        seen["latch"] = [latch(rr.m, 6, k) if bank_valid(rr.m, 6) >> k & 1 else None for k in range(4)]


r = scenario(frames=96000, at=193000, blocks=960, cell=0x102, pre=change_pending)
launch = [m_ for m_ in r.made if m_["step"] == 0][:2]
k0 = launch[0]["k"] if launch else 0
p0 = seen["pending"][k0] if "pending" in seen and launch else dict(active=0, done=0, delay=0, first=0)
check("pending launch: when the poll sees the change, the launch segment is waiting (delay > 0, +0x3c set) and is "
      "not dropped (no step-0 segment made again); only the step after it is re-made",
      p0["active"] and not p0["done"] and p0["delay"] > 0 and p0["first"] and len(launch) == 1
      and [m_["block"] for m_ in r.made if m_["step"] == 1][:2] == [0, seen.get("at")], (p0, [(m_["step"], m_["block"]) for m_ in r.made]))
check("  ...so it still launches on its bar: first read at 288 000, layer +0x140 = 11 520, msg 0x1d posted",
      r.reads[0][AT] == 288000 and r.layer()["launch_tick"] == 11520 and [b for b, t, _ in r.posted if t == 0x1D][:1] == [742],
      (r.reads[0][AT], r.layer(), [b for b, t, _ in r.posted if t == 0x1D][:2]))
step1 = [x for x in r.reads if r.made[x[SID] - 1]["step"] == 1]
check(f"  the poll latches the waiting launch again in place (slot {k0}: (0, 96 000, 24 000), prefetched at 23 992 in that "
      "block): it plays slipped from its first read (first fetch 24 000 = slip_f), the next step too (24 000 + 24 000)",
      seen.get("latch", [None] * 4)[k0] == (0, 96000, 24000) and (seen.get("at"), 23992) in r.prefetches
      and r.reads[0][FET][0][1] == 24000 and step1 and step1[0][FET][0][1] == 48000,
      (seen.get("latch"), [p for p in r.prefetches if p[0] == seen.get("at")], r.reads[0][FET][:1], step1[0][FET][:1] if step1 else None))
ref = audio(frames=96000, at=193000, blocks=960, cell=0x102)
cw = decode(scenario(dc=True, frames=96000, at=193000, blocks=960, cell=0x102, pre=change_pending), r)
n, err, bad, gd = shifted(ref, cw, 24000, 96000)
check(f"  every sounding sample, the launch step's first included, plays (stock frame + slip_f) mod len ({n} samples, max "
      f"{err:.4f} frame), summed gain = stock's", n > 25000 and err <= 0.02 and bad == 0 and gd == 0, (n, err, bad, gd))


def armed(bypass):
    """a note while the transport is stopped, Slip 0 -> 960 while it is armed, then PLAY on the bar at 384 000"""
    r = Rig(cell=0x102, bypass=bypass)
    slips(r.m, {})
    for _ in range(16):
        poll(r)
    r.pre_block = poll
    r.params()
    r.goto(193000)
    r.uc.mem_write(r.engine + 0x38, b"\x00")                  # transport stopped
    r.note_on()
    r.run(10)
    before = [r.seg(k) for k in range(4)]
    store(r.m, 6, {0x4: 500, P_SLIP: 960})
    r.run(20)
    held = dict(segs=[r.seg(k) for k in range(4)], armed=r.layer()["armed"], slip=bank_slip(r.m, 6), reads=len(r.reads),
                latch=latch(r.m, 6, 0) if bank_valid(r.m, 6) & 1 else None, pf=[p for b, p in r.prefetches if b >= 10])
    r.goto(384000)                                             # PLAY: the transport runs, and its start message (0x57)
    r.uc.mem_write(r.engine + 0x38, b"\x01")
    r.post(0x57)
    r.run(300)
    return r, before, held


r, before, held = armed(False)
by = armed(True)[0]
check("armed while the transport is stopped (delay 1, +0x3c set, layer +0x148 = 1): a Slip change leaves the launch armed "
      "and untouched, and latches it again in place (slot 0: (0, 96 000, 24 000), prefetched at 23 992)",
      before[0]["first"] and before[0]["delay"] == 1 and held["segs"] == before and held["armed"] == 1 and held["slip"] == 960
      and not held["reads"] and held["latch"] == (0, 96000, 24000) and held["pf"] == [23992], (before[0], held))
timing = lambda rr: [x[:SID] + x[AT:FET] for x in rr.reads]          # every read but its fetches
step1 = [x for x in r.reads if r.made[x[SID] - 1]["step"] == 1]
check("  PLAY (msg 0x57) on the bar at 384 000: it sounds from 384 001 (stock's delay 1; +0x140 = 15 360, msg 0x1d), every "
      "read's timing and bookkeeping and every message as with the hooks out, and it plays slipped from its first read: "
      "first fetch 24 000 (slip_f; hooks out: 0), the next step 48 000",
      r.reads and by.reads and r.reads[0][AT] == by.reads[0][AT] == 384001 and r.layer()["launch_tick"] == by.layer()["launch_tick"] == 15360
      and [b for b, t, _ in r.posted if t == 0x1D][:1] == [30] and timing(r) == timing(by) and r.posted == by.posted
      and r.reads[0][FET][0][1] == 24000 and by.reads[0][FET][0][1] == 0 and step1 and step1[0][FET][0][1] == 48000,
      (r.reads[0][AT] if r.reads else None, r.layer(), by.layer(), timing(r) == timing(by), r.posted == by.posted,
       r.reads[0][FET][:1] if r.reads else None, step1[0][FET][:1] if step1 else None))

# ====================================================================================================== 6. gating


def gate(name, slip_map, silent=False, **kw):
    a = scenario(others=slip_map, **kw)
    b = scenario(others=slip_map, bypass=True, **kw)
    ok, d = same(a, b, silent)
    return a, ok, d


def slicer_setup(ms):
    def setup(r):
        r.goto(287000 - N)
        r.markers(ms)
        r.step_block()
    return setup


all960 = {q: 960 for q in range(16)}
MK = (0, 20000, 50000, 70000)                                 # slice markers
for name, kw in (("a Slicer pad (no markers: its segments pass H1)", dict(setup=lambda r: (r.params(mode=2), None)[1])),
                 ("a Slicer pad with markers, note 37 (segments through H1')", dict(setup=lambda r: (r.params(mode=2), slicer_setup(MK)(r)), note=37)),
                 ("a Clip pad, Sync = Slice, with markers (H1')", dict(sync=0, setup=slicer_setup(MK)))):
    a, ok, d = gate(name, all960, slip=960, cell=0x102, blocks=500, **kw)
    hits = {h: sum(1 for m_ in a.made if m_["how"] == h) for h in ("H1", "H1'")}
    check(f"{name}, Slip 960: plays exactly as with the hooks out, no latch ({hits})",
          ok and bank_valid(a.m, 6) == 0 and bank_slip(a.m, 6) == 960 and sum(hits.values()) > 0, d)

# Slip changed live on those pads: the poll still drops their pending segments (it does not know Slip is ignored there)


def changes(rr):
    if rr.block in (150, 260, 330, 420):
        store(rr.m, 6, {0x4: 500, P_SLIP: {150: 960, 260: -30, 330: 480, 420: 7}[rr.block]})


for name, kw in (("a Slicer pad (no markers)", dict(setup=lambda r: (r.params(mode=2), None)[1])),
                 ("a Slicer pad with markers", dict(setup=lambda r: (r.params(mode=2), slicer_setup(MK)(r)), note=37)),
                 ("a Clip pad, Sync = Slice, with markers", dict(sync=0, setup=slicer_setup(MK)))):
    a = scenario(slip=0, cell=0x102, blocks=600, pre=changes, **kw)
    b = scenario(slip=0, cell=0x102, blocks=600, pre=changes, bypass=True, **kw)
    ok, d = same(a, b)
    remade = len(a.made) - len(b.made)
    check(f"{name}, Slip changed four times while it plays: every read, fetch, output sample and message as with the "
          f"hooks out ({remade} pending segment(s) dropped and re-made by stock, {len(a.prefetches) - len(b.prefetches)} "
          "extra prefetch hint(s))", d["reads"] and d["fetches"] and d["out"] and d["posted"] and bank_valid(a.m, 6) == 0, d)

# a slot H1 latched, reused by a slice segment (H1' clears it): live Sync -> Slice on a slipped pad


def to_slice(r):
    if r.block == 300:
        r.param(0x94, 0)


runs = [scenario(slip=960, cell=0x102, blocks=900, pre=to_slice, setup=slicer_setup(MK), bypass=b)
        for b in (False, True)]
sl = [[x[FET] for x in r_.reads if r_.made[x[SID] - 1]["how"] == "H1'"] for r_ in runs]
stale = [m_ for m_ in runs[0].made if m_["how"] == "H1'" and m_["valid_before"]]
check("Sync -> Slice while slipped: slice segments reuse slots H1 had latched (H1' clears them) and read the stock "
      "frames, exactly as with the hooks out", stale and sl[0] and sl[0] == sl[1], (len(stale), len(sl[0]), sl[0][:2], sl[1][:2]))
sounding = {x[SID] for x in runs[0].reads if x[0] == 300}
past = [(x[POS], x[FET][0][1] if x[FET] else None) for x in runs[0].reads if x[SID] in sounding and x[POS] >= 96000][:1]
past_by = [(x[POS], x[FET][0][1] if x[FET] else None) for x in runs[1].reads if x[POS] >= 96000][:1]
info("observed: the segment sounding at the switch keeps its latch and stock re-times it to run on past the file's end; "
     f"stock reads silence there {past_by}, the Clip Window the folded, slipped frames {past} (virtual, real)")

# a launch waiting for its bar on Sync = Slice (a slice segment, H1') is never latched again by the poll, even in a slot
# an earlier H1 segment used: Launch Trigger, Sync 1/4 (H1 caches the pad, every slot passes H1), a relaunch on the
# next bar, Sync -> Slice with markers live, another relaunch (now through H1'), then Slip 0 -> 960 before its bar
seen = {}


def slice_relaunch(rr):
    s = seen.setdefault(rr.hooks_out, {})
    if rr.block == 100:
        rr.note_on()                                          # relaunch on the bar at 384 000, through H1
    if rr.block == 800:
        rr.param(0x94, 0)                                     # Sync -> Slice
    if rr.block == 830:
        rr.note_on()                                          # relaunch on the bar at 480 000, through H1'
    if rr.block == 840:
        s["cached"] = u32(rr.m, BANK + B_PAD + 4 * 6) == rr.pad
        s["pending"] = [k for k in range(4) if rr.seg(k)["active"] and rr.seg(k)["delay"] > 0 and rr.seg(k)["first"]]
        store(rr.m, 6, {0x4: 500, P_SLIP: 960})
    if rr.block == 870:
        s["slip"], s["valid"] = bank_slip(rr.m, 6), bank_valid(rr.m, 6)


runs = []
for b_ in (False, True):
    def tag(r, b_=b_):
        r.hooks_out = b_
        slicer_setup(MK)(r)
    runs.append(scenario(slip=0, sync=3, launch=0, cell=0x102, at=287000, blocks=1600, pre=slice_relaunch, setup=tag, bypass=b_))
ok, d = same(*runs)
a, s = runs[0], seen.get(False, {})
rel = [m_ for m_ in a.made if m_["how"] == "H1'" and m_["block"] == 830 and m_["k"] in s.get("pending", [])]
check(f"Sync = Slice, a relaunch pending for its bar (slot {[m_['k'] for m_ in rel]}, made through H1' in a slot H1 had used: "
      f"h1 bit {[m_['h1_before'] for m_ in rel]} before), pad cached by H1 ({s.get('cached')}), Slip 0 -> 960 before the bar: "
      f"every read, fetch, output sample and message as with the hooks out (msg 0x1d at {[b for b, t, _ in a.posted if t == 0x1D]}), "
      f"no latch; only prefetch hints differ ({len(a.prefetches) - len(runs[1].prefetches)} extra: pending slice steps re-made)",
      d["reads"] and d["fetches"] and d["out"] and d["posted"] and len(rel) == 1 and rel[0]["h1_before"] == 1 and s.get("cached")
      and s.get("slip") == 960 and s.get("valid") == 0 and bank_valid(a.m, 6) == 0
      and [b for b, t, _ in a.posted if t == 0x1D][-1:] == [1508], (d, s, [(m_["how"], m_["block"], m_["k"], m_["h1_before"]) for m_ in a.made]))

a, ok, d = gate("0x401", all960, slip=960, blocks=400, cell=0x401)
check(f"cell 0x401 (the 17th class-B object, queue ctx + 0x608; pad 2's store under & 3), Slip 960 on every pad: "
      f"inactive - plays ({len(a.reads)} reads) as with the hooks out, no latch, not cached as any pad",
      ok and not any(bank_valid(a.m, q) for q in range(16)) and not any(u32(a.m, BANK + B_PAD + 4 * q) for q in range(16)),
      (d, len(a.reads)))
a, ok, d = gate("len 0", all960, silent=True, slip=960, blocks=400, frames=0)
check(f"fw_src_len 0 (not open), Slip 960: nothing plays, as with the hooks out ({len(a.reads)} reads), no latch",
      ok and not any(bank_valid(a.m, q) for q in range(16)), d)
a, ok, d = gate("len bad", all960, slip=960, blocks=400, frames=0x10000000)
check(f"fw_src_len 0x10000000 (the provider reported 0 frames), Slip 960: inactive - plays ({len(a.reads)} reads) as with "
      "the hooks out, no latch", ok and not any(bank_valid(a.m, q) for q in range(16)), d)
fill = bytes([0xA5]) * 0x1000
a = Rig(block=False, cell=0x102)
a.uc.mem_write(BANK - 0x800, fill)
slips(a.m, all960)
a.pre_block = poll
a.params()
a.goto(287000)
a.note_on()
a.run(400)
b = scenario(slip=960, others=all960, cell=0x102, blocks=400, bypass=True)
ok, d = same(a, b)
check("no SDRAM block, Slip 960: the poll and both hooks pass through - same as the hooks out, the memory where the "
      "bank would be untouched", ok and bytes(a.uc.mem_read(BANK - 0x800, 0x1000)) == fill, d)

# ====================================================================================================== 7. the reader (unit)
LENU = 50000
t = np.arange(LENU)
L_SIG = (0.4 * np.sin(2 * np.pi * 3000 * t / 48000) + 0.3 * np.sin(2 * np.pi * 9500 * t / 48000)).astype(np.float32)
R_SIG = (0.25 * np.sin(2 * np.pi * 5000 * t / 48000)).astype(np.float32)
RPAD, RSRC, SCR, OUT, VARS = 0x24060000, 0x24061000, 0x24062000, 0x24062100, 0x24062200
SCRD, SCRR, OUTD, OUTR = 0x24064000, 0x24065000, 0x24066000, 0x24067000   # 1024 floats each
VOICE = RPAD + 0x260 + 0x410
QU = 6


def sigs(length):
    """the test file's two channels, `length` frames (the first LENU are L_SIG / R_SIG)"""
    t_ = np.arange(length)
    return ((0.4 * np.sin(2 * np.pi * 3000 * t_ / 48000) + 0.3 * np.sin(2 * np.pi * 9500 * t_ / 48000)).astype(np.float32),
            (0.25 * np.sin(2 * np.pi * 5000 * t_ / 48000)).astype(np.float32))


def reader(image, rotate=None, length=LENU):
    """a machine with a RAM-served source: frame p of the file, or of the file turned by `rotate` (circular)"""
    m = Emu(image, "out/cave.elf")
    maps(m)
    m.fetches = []
    sig_l, sig_r = (L_SIG, R_SIG) if length == LENU else sigs(length)

    def frames_of(pos, n, sig):
        p = np.arange(pos, pos + n)
        if rotate is not None:
            return sig[np.mod(p + rotate, length)].tobytes()
        return np.where((p >= 0) & (p < length), sig[np.clip(p, 0, length - 1)], 0).astype(np.float32).tobytes()

    def fetch():
        pos = struct.unpack("<i", struct.pack("<I", m.arg(3)))[0]
        m.fetches.append((pos, m.arg(2)))
        m.uc.mem_write(m.arg(1), frames_of(pos, m.arg(2), sig_l))

    def fetch2():
        pos = m.r32(m.uc.reg_read(UC_ARM_REG_SP))
        m.fetches.append((pos, m.arg(3)))
        m.uc.mem_write(m.arg(1), frames_of(pos, m.arg(3), sig_l))
        m.uc.mem_write(m.arg(2), frames_of(pos, m.arg(3), sig_r))
    m.stub(FETCH, fetch)
    m.stub(FETCH2, fetch2)
    m.stub(SRC_LEN, value=length)
    m.uc.mem_write(RPAD, bytes(0xC00))
    m.uc.mem_write(RPAD + 4, b"\x4c")
    m.w32(RPAD + 0x24, RSRC)
    m.w32(RPAD + 0x18, (QU // 4) << 8 | QU % 4)
    sdram(m)
    m.uc.mem_write(BANK, bytes(0x800))
    m.w32(BANK, CW_MAGIC)
    return m


def set_latch(m, k, delta, valid=True, q=QU, length=LENU):
    m.uc.mem_write(BANK + B_LATCH + (q * 4 + k) * 12, struct.pack("<3i", 0, length, delta))
    m.uc.mem_write(BANK + B_VALID + q, bytes([(1 << k) if valid else 0]))


def read(m, target, pos, frac, rate, stereo=False, n=64, k=1, frac_at=None):
    m.stub(0x08063790, value=int(stereo))
    for buf, dl, dr in ((SCR, SCRD, SCRR), (OUT, OUTD, OUTR)):
        m.uc.mem_write(buf, struct.pack("<IIIIBB", 1024, 1024, dl, dr if stereo else 0, 0, int(stereo)))
    for a in (OUTD, OUTR, SCRD, SCRR):
        m.uc.mem_write(a, bytes(4096))
    fp = frac_at if frac_at is not None else RPAD + 0x30 + k * 0x70 + 0x1C
    m.uc.mem_write(fp, struct.pack("<f", frac))
    m.uc.mem_write(VARS, struct.pack("<iI", -1, 0))
    m.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", rate))[0])
    for i, v in enumerate((n, VARS, fp, SCR, OUT, VARS + 4)):
        m.w32(STACK + 4 * i, v)
    m.fetches.clear()
    m.uc.reg_write(UC_ARM_REG_R11, VOICE)
    if target == 0x080662E4 or target == "clip_read":
        m.call(target, RPAD, VOICE + 0x14C, pos, 0, count=20_000_000)
    else:
        m.call(target, RPAD, 0, pos, 0, count=20_000_000)
    ok = m.uc.reg_read(UC_ARM_REG_R0)
    used, res = struct.unpack("<iI", m.uc.mem_read(VARS, 8))
    nfrac = struct.unpack("<f", m.uc.mem_read(fp, 4))[0]
    dl, dr = (OUTD, OUTR) if res == OUT else (SCRD, SCRR)
    left = np.frombuffer(bytes(m.uc.mem_read(dl, 4 * n)), np.float32).copy()
    right = np.frombuffer(bytes(m.uc.mem_read(dr, 4 * n)), np.float32).copy() if stereo else None
    return ok, used, nfrac, res, left, right, list(m.fetches)


def fidelity(m, v):
    store(m, QU, {0x4: 500, 0xDB: 0, 0xF1: v})


cw_m = reader(IMAGE)
for name, delta, pos, rate, frac, stereo, n, length in (
        ("rate 1, frac 0 (the straight copy)", 30000, 19970, 1.0, 0.0, False, 64, LENU),
        ("rate 0.7, frac 0.25 (the kernel)", 30000, 19980, 0.7, 0.25, False, 64, LENU),
        ("rate 2.3, frac 0.6", 12345, LENU - 12345 - 70, 2.3, 0.6, False, 64, LENU),
        ("rate 8, 128 frames (the fetch capped at the scratch's 1024)", 30000, 19990, 8.0, 0.3, False, 128, LENU),
        ("stereo, rate 1, frac 0", 30000, 19970, 1.0, 0.0, True, 64, LENU),
        ("stereo, rate 0.91875 (44.1 kHz), frac 0.4", 30000, 19985, 0.91875, 0.4, True, 64, LENU),
        ("rate 1, frac 0, real position 1 (no seam in stock's window: its reader at the real position)", 30001, 20000, 1.0, 0.0, False, 64, LENU),
        ("rate 0.8, real position 2 (the same)", 2, 0, 0.8, 0.1, False, 64, LENU),
        ("a 40-frame file, 64 frames read (round the file twice)", 13, 20, 1.0, 0.0, False, 64, 40),
        ("a 40-frame file, stereo, rate 1.7", 13, 30, 1.7, 0.2, True, 64, 40)):
    m = cw_m if length == LENU else reader(IMAGE, length=length)
    ref_m = reader(STOCK, rotate=delta, length=length)
    set_latch(m, 1, delta, length=length)
    fidelity(m, 0)
    got = read(m, "clip_read_b", pos, frac, rate, stereo, n=n)
    want = read(ref_m, 0x080662E4, pos, frac, rate, stereo, n=n)
    real = (pos + delta) % length
    count = n if rate == 1.0 and frac == 0.0 else min(int(np.float32(n) * np.float32(rate)) + 8, 1024)
    ring = got[6][0][0] == real and all(f[0] == 0 for f in got[6][1:]) and sum(f[1] for f in got[6]) == count
    check(f"{'seam' if real + count > length else 'mapped'} read, {name}: what the stock reader makes of the file turned circular (output, used, frac, buffer, "
          f"bit for bit); fetched {got[6]}", ring and got[0] == want[0] == 1 and got[1:4] == want[1:4]
          and np.array_equal(got[4].view(np.uint32), want[4].view(np.uint32))
          and (not stereo or np.array_equal(got[5].view(np.uint32), want[5].view(np.uint32))), (got[:4], want[:4], got[6], want[6]))

# off the seam: filter.c's machine modes read the mapped position (test_clip.py's model)
FIR26 = [0.00302, 0.24563, 0.5027, 0.24563, 0.00302]


def drop_model(P, rate, n, grid=26040):
    g, out = 48000 / grid, []
    for i in range(n):
        j = round(np.floor((P + i * rate) / g + 1 / 8192) * g)
        out.append(sum(FIR26[t] * float(L_SIG[(j - 2 + t) % LENU]) for t in range(5)))
    return np.array(out)


set_latch(cw_m, 1, 30000)
fidelity(cw_m, 2)
got = read(cw_m, "clip_read_b", 5000, 0.25, 0.5)
bad = np.where(np.abs(got[4] - drop_model(35000 + 1.25, 0.5, 64)) > 2e-4)[0]
fidelity(cw_m, 0)
norm = read(cw_m, "clip_read_b", 5000, 0.25, 0.5)
check("off the seam, Fidelity SP1200, rate 0.5: the drop-sample reader at the mapped position (35 000; test_clip.py's "
      f"model, {len(bad)} of 64 off), position bookkeeping as Fidelity Normal, one fetch from real - 3 {got[6]}",
      len(bad) <= 2 and got[1:3] == norm[1:3] and got[6] == [(34997, 40)], (bad[:4], got[1:3], norm[1:3], got[6]))

# a machine mode at or near the seam: filter.c's machine reader over the circular region (clip_read_ring), seam or not.
# The reference: filter.c's own clip_read at the real position on the file truly circular, bit for bit.
MODES = ((2, "SP1200"), (3, "SP-12"), (4, "S950"), (5, "MPC60"), (6, "SP Raw"), (7, "S950 Lo"), (8, "SP 45"))
circ_m = reader(IMAGE, rotate=0)


def same_read(got, want, stereo):
    return got[:4] == want[:4] and np.array_equal(got[4].view(np.uint32), want[4].view(np.uint32)) and (
        not stereo or np.array_equal(got[5].view(np.uint32), want[5].view(np.uint32)))


fidelity(cw_m, 2)
fidelity(circ_m, 2)
set_latch(cw_m, 1, 30000)
got = read(cw_m, "clip_read_b", 19980, 0.25, 0.5)
want = read(circ_m, "clip_read", 49980, 0.25, 0.5)
check(f"on the seam, Fidelity SP1200, rate 0.5 (real 49 980): filter.c's machine reader over the circular file, bit for "
      f"bit its clip_read on the file turned circular (output, used, frac, buffer); fetched {got[6]}, all inside the file",
      same_read(got, want, False) and got[6] == [(49977, 23), (0, 17)], (got[:4], want[:4], got[6], want[6]))
set_latch(cw_m, 1, 30001)
got = read(cw_m, "clip_read_b", 20000, 0.25, 0.5)
want = read(circ_m, "clip_read", 50001, 0.25, 0.5)
check("Fidelity SP1200 one frame into the file (real 1): the machine reader's back-step wraps to the file's end, bit for "
      "bit clip_read on the circular file one pass later (50 001: the 26 040 Hz grid repeats every 50 000 frames, 27 125 "
      f"steps); fetched {got[6]}", same_read(got, want, False) and got[6] == [(49998, 2), (0, 38)],
      (got[:4], want[:4], got[6], want[6]))

# F1: rate 1, frac 0 on the last blocks before the seam. Stock's straight copy needs n frames and has no seam there; a
# machine reads [real - 3, real + n + 5), across the end (gap 0..4) or onto it (5)
for v, name in MODES:
    fidelity(cw_m, v)
    fidelity(circ_m, v)
    bad, outside = [], []
    for stereo in (False, True):
        for gap in range(6):
            real = LENU - N - gap
            set_latch(cw_m, 1, 30000)
            got = read(cw_m, "clip_read_b", real - 30000, 0.0, 1.0, stereo, n=N)
            want = read(circ_m, "clip_read", real, 0.0, 1.0, stereo, n=N)
            outside += [f for f in got[6] if not 0 <= f[0] <= f[0] + f[1] <= LENU]
            if not (same_read(got, want, stereo) and got[6][0][0] == real - 3 and sum(c for _, c in got[6]) == N + 8):
                bad.append((stereo, gap, got[:4], want[:4], got[6]))
    check(f"F1, Fidelity {name}, rate 1, frac 0, real = len - 128 - 0..5, mono and stereo: the machine's 136 frames from "
          "real - 3 fetched inside [0, len) only (in two parts where they wrap), and bit for bit clip_read on the circular file",
          not bad and not outside, (bad[:2], outside[:4]))

# near the start (real 0..2): the back-step wraps to the end. The reference reads one pass later, on a 240 000-frame file
# (5 x 48 000: the grid of every machine but SP 45, 19 288.9 Hz, repeats over it)
LONG = 240000
long_m, long_ref = reader(IMAGE, length=LONG), reader(IMAGE, rotate=0, length=LONG)
for v, name in MODES[:6]:
    fidelity(long_m, v)
    fidelity(long_ref, v)
    bad = []
    for stereo in (False, True):
        for real, rate, frac in ((0, 1.0, 0.0), (1, 1.0, 0.0), (2, 1.0, 0.0), (1, 0.91875, 0.4), (2, 0.8, 0.1)):
            set_latch(long_m, 1, 1234, length=LONG)
            got = read(long_m, "clip_read_b", (real - 1234) % LONG, frac, rate, stereo, n=N)
            want = read(long_ref, "clip_read", real + LONG, frac, rate, stereo, n=N)
            if not (same_read(got, want, stereo) and got[6][0] == (LONG - 3 + real, 3 - real)
                    and all(0 <= p_ <= p_ + c_ <= LONG for p_, c_ in got[6])):
                bad.append((real, rate, stereo, got[:4], want[:4], got[6]))
    check(f"near the start, Fidelity {name}, real 0 / 1 / 2 at rates 1, 0.91875, 0.8, mono and stereo: the back-step's "
          "frames fetched from the file's end, nothing outside it, and bit for bit clip_read on the circular file one pass "
          "later", not bad, bad[:2])

# ABI-1: the filter object's rate (+0x60) is the reader's to write; a clocked machine (S950, S950 Lo) takes its DAC clock
# and its low-pass from it, and a rate that makes no sense as "no reader ran". A seam block must write it too.
for v, name in ((4, "S950"), (7, "S950 Lo")):
    fidelity(cw_m, v)
    fidelity(circ_m, v)
    rows = []
    for stereo in (False, True):
        for rate, frac, real in ((0.91875, 0.4, LENU - 20), (1.0, 0.0, LENU - 60), (1.498, 0.3, LENU - 60)):
            set_latch(cw_m, 1, 30000)
            cw_m.uc.mem_write(VOICE + 0x14C + 0x60, struct.pack("<f", 0.5))       # left by another rate
            got = read(cw_m, "clip_read_b", real - 30000, frac, rate, stereo, n=N)
            after = struct.unpack("<f", cw_m.uc.mem_read(VOICE + 0x14C + 0x60, 4))[0]
            want = read(circ_m, "clip_read", real, frac, rate, stereo, n=N)
            rows.append((rate, stereo, after, len(got[6]) == 2 and same_read(got, want, stereo)))
    check(f"ABI-1, Fidelity {name}: a stale rate at the filter object + 0x60 (0.5) is rewritten by a seam block (rates "
          "0.91875, 1, 1.498, mono and stereo, the fetch in two parts), and the block is clip_read's on the circular file",
          all(after == np.float32(rate) and ok_ for rate, _, after, ok_ in rows), rows)
fidelity(cw_m, 0)

# when the read is not ours to map
base_m = reader(IMAGE)
for name, prep, kw in (("the latch is not valid", lambda m: set_latch(m, 1, 30000, valid=False), {}),
                       ("the latch is for another slot", lambda m: set_latch(m, 2, 30000), {}),
                       ("&frac is not a segment's fraction", lambda m: set_latch(m, 1, 30000), dict(frac_at=RPAD + 0x30 + 0x70 + 0x20)),
                       ("&frac is past the fourth segment", lambda m: set_latch(m, 1, 30000), dict(frac_at=RPAD + 0x30 + 4 * 0x70 + 0x1C)),
                       ("the pad is cell 0x401", lambda m: (set_latch(m, 1, 30000), m.w32(RPAD + 0x18, 0x401)), {}),
                       ("no SDRAM block", lambda m: (set_latch(m, 1, 30000), sdram(m, False)), {})):
    m = reader(IMAGE)
    prep(m)
    got = read(m, "clip_read_b", 19970, 0.25, 0.7, **kw)
    want = read(base_m, "clip_read", 19970, 0.25, 0.7, **kw)
    check(f"{name}: filter.c's clip_read, unchanged", got[:4] == want[:4] and np.array_equal(got[4], want[4]) and got[6] == want[6],
          (got[:4], want[:4], got[6], want[6]))

# thunks entered as the patched sites enter them


def enter(m, thunk, r4, words):
    sp = STACK - 0x100
    for off, v in words.items():
        m.w32(sp + off, v)
    for reg, v in ((UC_ARM_REG_R0, RSRC), (UC_ARM_REG_R1, 1234), (UC_ARM_REG_R2, 0x33330000), (UC_ARM_REG_R3, 0x44440000),
                   (UC_ARM_REG_R4, r4)):
        m.uc.reg_write(reg, v)
    m.uc.reg_write(UC_ARM_REG_SP, sp)
    m.uc.reg_write(UC_ARM_REG_LR, RET | 1)
    m.uc.emu_start(S[thunk] | 1, RET, count=1_000_000)
    return m.uc.reg_read(UC_ARM_REG_PC) == RET and m.uc.reg_read(UC_ARM_REG_SP) == sp and m.uc.reg_read(UC_ARM_REG_R4) == r4


m = reader(IMAGE)
pf = []
m.stub(PREFETCH, lambda: pf.append((m.arg(0), m.arg(1))))
set_latch(m, 2, 777)
for at in (B_VALID, B_H1, B_HINTED):
    m.uc.mem_write(BANK + at + QU, b"\x0f")
bits = lambda: [m.r8(BANK + at + QU) for at in (B_VALID, B_H1, B_HINTED)]
ok = enter(m, "clipwin_slice_start_b", RPAD, {4: 2, 0x20: 1})
check("H1' thunk: the slot from [sp + 4], the pad from r4: that slot's latch and its 'made through H1' bit cleared, the "
      "others kept, the prefetch called with the caller's source and position", ok and bits() == [0x0B, 0x0B, 0x0F]
      and pf == [(RSRC, 1234)], ([hex(x) for x in bits()], pf))
m.uc.mem_write(RPAD + 0x29, b"\x01")
m.uc.mem_write(RPAD + 0x208, struct.pack("<qI", 960, 4))
m.uc.mem_write(RPAD + 0x30 + 3 * 0x70 + 8, struct.pack("<q", 37000))
m.w32(BANK + B_SLIP + 4 * QU, 960)
m.uc.mem_write(BANK + B_H1 + QU, b"\x03")                     # slot 3 last held a slice segment
pf.clear()
ok = enter(m, "clipwin_seg_start_b", RPAD, {4: 1, 0x20: 3})
check("H1 thunk: the slot from [sp + 0x20]: slot 3 latched (0, 50 000, 12 500), marked made through H1, its seam hint "
      "re-armed (hinted bit cleared), prefetched at 37 000 + 12 500 - 8",
      ok and bits() == [0x0B, 0x0B, 0x07] and latch(m, QU, 3) == (0, LENU, 12500) and pf == [(RSRC, 49492)]
      and u32(m, BANK + B_PAD + 4 * QU) == RPAD, ([hex(x) for x in bits()], latch(m, QU, 3), pf))

# ====================================================================================================== 8. rate, stereo


def rate_case(name, frames, src_rate, stereo, slip, pitch=None):
    pre = (lambda rr: rr.param(0x5C, pitch) if rr.block == 0 else None) if pitch else None
    sc = dict(frames=frames, src_rate=src_rate, stereo=stereo, cell=0x102, pre=pre)
    rd0, rr0 = scenario(dc=True, **sc), scenario(**sc)
    rd1, rr1 = scenario(dc=True, slip=slip, **sc), scenario(slip=slip, **sc)
    sf = slip_f(slip, frames, 3840)
    rate = struct.unpack("<f", struct.pack("<I", rr1.reads[3][4]))[0]
    for ch in ((0, 1) if stereo else (0,)):
        n, err, bad, gd = shifted(decode(rd0, rr0, ch), decode(rd1, rr1, ch), sf, frames, edge=3)
        check(f"{name}{', right' if ch else (', left' if stereo else '')} (rate {rate:.5f}), Slip {slip}: every sounding "
              f"sample plays stock + slip_f ({n} samples, max {err:.4f} frame; the 3 frames at each end of the file "
              "aside), summed gain = stock's", n > 90000 and err <= 0.02 and bad == 0 and gd == 0, (n, err, bad, gd))
    seam = rr1.seam_reads()
    check(f"  {len(seam)} seam block(s) read through clipwin_read's own fetch{' pair' if stereo else ''} and "
          f"{'the kernel' if rate != 1.0 else 'the straight copy'}", len(seam) >= 1 and all(len(x[FET]) == 2 for x in seam if x[FET][0][1] > 3))


rate_case("44.1 kHz file (88 200 frames)", 88200, 44100, False, 960)
rate_case("stereo 48 kHz", 96000, 48000, True, -30)
rate_case("stereo 44.1 kHz", 88200, 44100, True, 3839)
rate_case("Pitch +7 semitones", 96000, 48000, False, 960, pitch=7000)

# ====================================================================================================== 9. the knob
texts, posts = [], []
e.stub(0x080C3B98, lambda: texts.append((e.arg(0), e.cstr(e.arg(1)))))
e.stub(0x080B0480)
e.stub(0x080AED14, lambda: posts.append((e.r16(e.arg(1)), e.r32(e.arg(1) + 0xC), e.r32(e.arg(1) + 0x10))))
LIST = 0x24050000
KN = LIST + 0x120


def fresh():
    e.uc.mem_write(LIST, bytes(0xA000))
    e.w32(KN, 0x080F0C88)
    e.uc.mem_write(LIST + 0x404, b"\x01")


def vtext():
    return [x for a, x in texts if a == KN + 0x9C]


regs = registrar(e, TABLE)                             # a real table for the binder
for v, want in ((1240, "+1.280"), (-30, "-0.030"), (0, "+0.000"), (959, "+0.959"), (3840, "+4.000"), (-3840, "-4.000")):
    fresh()
    texts.clear()
    e.call(0x080A7EE0, P_SLIP, v, KN)
    check(f"Slip {v} on a knob bound by the stock binder: type {e.r8(KN + 0x31)}, range {e.r32(KN + 0x14C)}..{e.r32(KN + 0x150)}, "
          f"text {want!r} (beats.ticks)", vtext()[-1:] == [want] and e.r8(KN + 0x31) == 1
          and (e.r32(KN + 0x14C), e.r32(KN + 0x150)) == (-3840, 3840), (vtext(), e.r8(KN + 0x31)))
fresh()
e.w32(KN + 0x14, P_SLIP)
e.call(0x080B04C8, KN)
texts.clear()
e.call(0x080B0790, KN, 1240)
check("a reset knob that kept the stale id 0x1c9 (type 0) prints what stock prints there: ''", vtext() == [""], vtext())
fresh()
e.call(0x080A7EE0, P_SLIP, 1240, KN)
e.uc.mem_write(KN + 0x2D8, b"\x01")
texts.clear()
e.call("clipwin_format", KN)
ours_ = vtext()
texts.clear()
e.call(0x080B0528, KN)
check(f"a frozen knob (+0x2d8 set): clipwin_format leaves it to the stock formatter (text {ours_}, stock {vtext()})",
      ours_ == vtext() and "+1.280" not in ours_, (ours_, vtext()))
e.uc.mem_write(TABLE + P_SLIP * 0x1C + 2, b"\x09")         # registered as a type-9 row instead (P3 may)
fresh()
texts.clear()
e.call(0x080A7EE0, P_SLIP, 1240, KN)
check("the same row registered as type 9 (a list position): the value it stands for, '+1.280'",
      e.r8(KN + 0x31) == 9 and vtext()[-1:] == ["+1.280"], (e.r8(KN + 0x31), vtext()))
e.uc.mem_write(TABLE + P_SLIP * 0x1C + 2, b"\x01")


def turn(path, per_ms, events=40, sign=1):
    fresh()
    e.call(0x080A7EE0, P_SLIP, 0, KN)
    c, t = sign * int(per_ms * 16), 10_000
    posts.clear()
    texts.clear()
    for _ in range(events):
        t += 16
        e.w32(GUI_MS, t)
        if path == "list":
            e.call(0x080B9A3C, LIST, c)
        else:
            e.call(0x080B0D54, KN, c)
    return e.r32(KN + 0x27C) + e.r32(KN + 0x288), c * events


for path in ("list", "turn"):
    got = {s: turn(path, s) for s in (0.7, 1.5, 3, 6, 12)}
    vals = [v for v, _ in got.values()]
    per = [v / c for v, c in got.values()]                    # ticks per count
    slow, counts = got[0.7]
    check(f"{'pad page list (FUN_080b9a3c)' if path == 'list' else 'waveform turn (FUN_080b0d54)'}: slow, 1 tick per 40 "
          f"counts ({counts} counts -> {slow}); faster turns give more ticks per count ({vals} for "
          f"{[c for _, c in got.values()]} counts); fast stops at +3840",
          slow == counts // 40 and per[:3] == sorted(per[:3]) and per[2] > 2 * per[0] and vals[-1] == 3840, got)
    v, _ = turn(path, 12, sign=-1)
    check("  fast the other way stops at -3840; the value text follows the turn, and the app is sent 0x1c9 = the value",
          v == -3840 and vtext()[-1:] == ["-4.000"] and posts and posts[-1] == (0x3D, -3840, P_SLIP), (v, vtext()[-1:], posts[-1:]))

# other knobs: the same text, steps and posts as on the stock image
for m_ in (st_m,):
    m_.stub(0x080B0480)
st_texts, st_posts = [], []
st_m.stub(0x080C3B98, lambda: st_texts.append((st_m.arg(0), st_m.cstr(st_m.arg(1)))))
st_m.stub(0x080AED14, lambda: st_posts.append((st_m.r16(st_m.arg(1)), st_m.r32(st_m.arg(1) + 0xC), st_m.r32(st_m.arg(1) + 0x10))))
others = [r for r in stock_regs if r[1] in (1, 0xD, 9)][:6]


def knob_run(m, tx, ps, pid, v, counts):
    m.uc.mem_write(LIST, bytes(0xA000))
    m.w32(KN, 0x080F0C88)
    tx.clear()
    ps.clear()
    m.call(0x080A7EE0, pid, v, KN)
    t_ = 50_000
    for c in counts:
        t_ += 16
        m.w32(GUI_MS, t_)
        m.call(0x080B0D54, KN, c)
    return [x for a, x in tx if a == KN + 0x9C], list(ps), m.r32(KN + 0x34), m.r32(KN + 0x27C)


for pid, typ, lab, lo, hi, xml in others:
    v = lo + (hi - lo) // 3
    counts = [11] * 10 + [192] * 10 + [-40] * 5
    a_, b_ = knob_run(e, texts, posts, pid, v, counts), knob_run(st_m, st_texts, st_posts, pid, v, counts)
    check(f"another knob ({lab!r}, id {pid:#x}, type {typ}): bound and turned slow and fast, the same text, posts and "
          "position as on the stock image", a_ == b_, (a_[0][-2:], b_[0][-2:], a_[1][-1:], b_[1][-1:], a_[2:], b_[2:]))

print(f"{fails} failed")
sys.exit(1 if fails else 0)
