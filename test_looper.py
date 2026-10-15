"""Looper FX (FX A types Looper / Loop In: src/looper.c, src/looper_dsp.c) under Unicorn, plus the host build of the DSP.

Real firmware runs for: the DJ FX pool, its buffers and the container (ctor, type setter, per-block process with its
message drain, slot setter, swap, acquire / release), the Repeater (process, reset, finger / hold) in Repeater mode,
the buffer helpers, the registrar FUN_0808C158 and the XY view's axis binder FUN_080B1DE0 and value map FUN_080B26C8.
Stubbed: the permanent allocator (a bump in the fake SDRAM), the float zero-fill, the channel -> queue lookup (FX A's
channel gets the test's queue), atexit, the app post, the two register functions (recording), the XY label setter.
The engine is a fake clock object: duck_block's snapshot is taken with looper_tick at the block's first frame, then the
clock is advanced by one block, as the real tick does before the DJ FX run.
Harness copied from notes/re's A5 scratch run (re-scratch/a5/rep.py): Out 1 carries a ramp that encodes each frame's
index exactly in int16, so every output frame decodes to the input frame it replays.
NOT checked here: the real XY pad handlers end to end (posts are written straight into the queue), the full engine tick,
the recorder's own block (Loop In's monitor rule is read from fields set by hand, and input bus 0 and the raw input at
the audio object are planted as A6 found them), how it sounds, CPU on the chip (counted as instructions).
T17 runs the host build on its own clock for the cases a review of v1 found: races between the UI and audio tasks,
overlapping crossfades, a re-catch inside a release, tempo changes.
"""
import ctypes
import math
import os
import shutil
import struct
import subprocess
import sys

import numpy as np
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP

from emu import STACK, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
STOCK = "firmware/BLACKBOX-3.1.9.bin"
N = 128
FS = 48000
CTX, Q, QE, L0, R0, SCR, INL, INR = 0xC0000000, 0xC0020000, 0xC0021000, 0xC0022000, 0xC0023000, 0xC0024000, 0xC0030000, 0xC0031000
CONT, HEAP, MB = 0xC0100000, 0xC0200000, 0xC0E00000
AUDIO, RAWL, RAWR = 0x2400A9C0, 0xC0032000, 0xC0033000   # the audio object; where the rig puts its raw input buffers
ENG, ROOT = 0x24060000, 0x24068000
PMEM, PCHECK = 0x38800F70, 0x38800F74
LP = MB + 0x56800 + 0x2D900                      # looper.c's bank in master.c's block
DSP = LP + 28
REP_VT, REP1, REP2 = 0x080DF580, 0x24015268, 0x24015340
CHAN_A, CHAN_B = 0x30300, 0x30400
P_FINGER, P_HOLD, P_LEN, P_HPF = 0x15, 0x1A, 0x1CC, 0x30
LENS = ["4 bars", "2 bars", "1 bar", "1/2", "1/4", "1/8", "1/16"]
TICKS = [15360, 7680, 3840, 1920, 960, 480, 240]

fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


DSP_FMT = "<2I2i8B2h4i5f2i7f4BIi4f4B"
DSP_KEYS = ("init obj w valid engaged finger hold live len_idx last_len frozen pend px py in_idx phi lcur age lf acc fpt "
            "g gt old_idx xf yt ys fm s1l s1r s2l s2r npass anch old_live hskip in_tick rn rsl rsr zpl zpr jolt _r0 _r1 _r2").split()
DSP_SIZE = struct.calcsize(DSP_FMT)
assert DSP_SIZE == 132


def enc(k):
    """frame index -> (L, R): exact in the ring's int16 (scale 8192)"""
    k = np.asarray(k, dtype=np.int64)
    return (((k % 16384) - 8192) / 8192.0).astype(np.float32), ((((k // 16384) % 16384) - 8192) / 8192.0).astype(np.float32)


def dec(l, r):
    """(L, R) -> the frame index they carry, or -1 where they are not exactly a ring value"""
    a, b = np.asarray(l, np.float64) * 8192 + 8192, np.asarray(r, np.float64) * 8192 + 8192
    ok = (np.abs(a - np.round(a)) < 1e-6) & (np.abs(b - np.round(b)) < 1e-6)
    return np.where(ok, np.round(a).astype(np.int64) + 16384 * np.round(b).astype(np.int64), -1)


class Rig:
    """The DJ FX container with its real pool and Repeater, FX A fed from a queue, on a fake clock."""

    def __init__(self, image=IMAGE, bpm=120.0, master=True):
        e = self.e = Emu(image, "out/cave.elf")
        self.patched = image == IMAGE
        for base, size in ((0x38800000, 0x1000), (0x58024000, 0x1000), (0x50003000, 0x1000), (0xC0000000, 0x1000000)):
            e.uc.mem_map(base, size)
        self.heap, self.posts, self.msgs, self.resets = [HEAP], [], [], []
        self.S, self.bpm, self.playing, self.tick_shift = 0, bpm, 1, 0

        def alloc():
            a = self.heap[0]
            self.heap[0] += (e.arg(0) + 31) & ~31
            e.uc.reg_write(UC_ARM_REG_R0, a)
        e.stub(0x0804436C, alloc)
        e.stub(0x080CA97C, value=0)

        def fill0():
            if e.arg(1):
                e.uc.mem_write(e.arg(0), bytes(4 * e.arg(1)))
        e.stub(0x0805F614, fill0)
        e.stub(0x0805F2C8, lambda: e.uc.reg_write(UC_ARM_REG_R0, Q if e.arg(1) == CHAN_A else QE))
        e.stub(0x0804F504, lambda: self.posts.append(bytes(e.uc.mem_read(e.arg(1), 0x18))))
        rst = 0x0806D03C
        e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: self.resets.append(uc.reg_read(UC_ARM_REG_R0)), begin=rst, end=rst)
        e.call(0x0806CCF8)
        self.pool = e.uc.reg_read(UC_ARM_REG_R0)
        e.call(0x0806CD40, self.pool, count=50_000_000)
        e.call(0x0806E244, CONT)
        e.call(0x0806E35C, CONT, 2)
        for i, (chan, cls) in enumerate(((CHAN_A, 0x40), (CHAN_B, 0x3A))):
            sub = CONT + 0x20 + i * 0x2C
            e.w32(sub + 0x18, chan)
            e.uc.mem_write(sub + 0x1E, b"\0\0")
            e.call(0x0806E368, CONT, i, cls)
        self.sub = CONT + 0x20
        e.w32(CTX, ENG)
        e.uc.mem_write(ENG + 0x18, struct.pack("<f", bpm))
        self.set_bus(CTX + 0x150E4, L0, R0)
        for k in range(4):
            self.set_bus(CTX + 0x151FC + k * 0x14, SCR + k * 0x1000, SCR + k * 0x1000 + 0x800)
        self.set_bus(CTX + 0x1583C, INL, INR)
        e.w32(Q + 0x600, 0)
        e.w32(QE + 0x600, 0)
        if master:
            e.w32(PMEM, MB)
            e.w32(PCHECK, MB ^ 0x5052534D)
        self.inp = None                                  # input bus 0: frame -> (L, R), default silence
        self.raw = None                                  # the raw input at the audio object, default none there

    def set_bus(self, at, l, r):
        e = self.e
        e.w32(at, N)
        e.w32(at + 4, N)
        e.w32(at + 8, l)
        e.w32(at + 12, r)
        e.uc.mem_write(at + 0x10, b"\x00\x01")

    def ticks(self, s):
        return int(math.floor(s * self.bpm / 3000.0 + 0.5)) + self.tick_shift

    def clock(self, s):
        e = self.e
        e.uc.mem_write(ENG, struct.pack("<q", s))
        e.uc.mem_write(ENG + 0x30, struct.pack("<q", self.ticks(s)))
        e.uc.mem_write(ENG + 0x38, bytes([self.playing]))

    def post(self, pid, v, chan=CHAN_A, kind=0x39):
        self.msgs.append((kind, chan, pid, v))

    def block(self, sig=enc, play_change=None):
        """One engine block of Out 1 = sig(frames). play_change: the transport changes between duck_block and the
        DJ FX (a PLAY / STOP command drained in this block's tick)."""
        e, S = self.e, self.S
        k = np.arange(S, S + N)
        xl, xr = sig(k)
        e.uc.mem_write(L0, np.asarray(xl, np.float32).tobytes())
        e.uc.mem_write(R0, np.asarray(xr, np.float32).tobytes())
        if self.inp:
            il, ir = self.inp(k)
            e.uc.mem_write(INL, np.asarray(il, np.float32).tobytes())
            e.uc.mem_write(INR, np.asarray(ir, np.float32).tobytes())
        if self.raw:                                 # the audio object's own raw input buffers (A6 step 1)
            il, ir = self.raw(k)
            e.uc.mem_write(RAWL, np.asarray(il, np.float32).tobytes())
            e.uc.mem_write(RAWR, np.asarray(ir, np.float32).tobytes())
            e.w32(AUDIO + 0x8FB0, RAWL)
            e.w32(AUDIO + 0x8FB4, RAWR)
        self.set_bus(CTX + 0x150E4, L0, R0)
        self.set_bus(CTX + 0x1583C, INL, INR)
        self.clock(S)
        if self.patched:
            e.call("looper_tick", ENG)
        if play_change is not None:
            self.playing = play_change
        self.clock(S + N)
        for i, (kind, chan, pid, v) in enumerate(self.msgs):
            e.uc.mem_write(Q + i * 0x18, struct.pack("<BBBBIIHHiI", kind, 0, 0, 0, 0, chan, pid, 0, v, 0))
        e.w32(Q + 0x600, len(self.msgs))
        self.msgs = []
        e.call(0x0806DD0C, CONT, CTX, count=20_000_000)
        self.S += N
        return (np.frombuffer(bytes(e.uc.mem_read(L0, 4 * N)), np.float32).copy(),
                np.frombuffer(bytes(e.uc.mem_read(R0, 4 * N)), np.float32).copy())

    def run(self, blocks, sig=enc):
        ls, rs = [], []
        for _ in range(blocks):
            l, r = self.block(sig)
            ls.append(l)
            rs.append(r)
        return (np.concatenate(ls), np.concatenate(rs)) if ls else (np.zeros(0, np.float32), np.zeros(0, np.float32))

    def until(self, frame, sig=enc):
        """run whole blocks until the next block would start at or after `frame`"""
        return self.run(max(0, (frame - self.S + N - 1) // N), sig)

    def fx(self):
        return self.e.r32(self.sub + 0x20) & 0xFFFFFFFF

    def dsp(self):
        return dict(zip(DSP_KEYS, struct.unpack(DSP_FMT, self.e.uc.mem_read(DSP, DSP_SIZE))))

    def mode(self):
        return self.e.r8(LP + 4)

    def ring(self, frames, fx=None):
        fx = fx or self.fx()
        e = self.e
        rl, rr = e.r32(fx + 0x3C) & 0xFFFFFFFF, e.r32(fx + 0x40) & 0xFFFFFFFF
        return (np.frombuffer(bytes(e.uc.mem_read(rl, 2 * frames)), "<i2"), np.frombuffer(bytes(e.uc.mem_read(rr, 2 * frames)), "<i2"))


def frames_at(rig, ticks):
    """the exact frame of a tick at the rig's tempo"""
    return (ticks - rig.tick_shift) * 3000.0 / rig.bpm


sym = Emu(IMAGE, "out/cave.elf").sym
img = open(IMAGE, "rb").read()
stock = open(STOCK, "rb").read()


def iw(a, data=img):
    return struct.unpack_from("<I", data, a - 0x08040000)[0]


# ---- T1 build: where the code went, and what it costs
size = subprocess.run(["arm-none-eabi-size", "out/obj/looper.o", "out/obj/looper_thunk.o", "out/obj/looper_dsp.o"],
                      capture_output=True, text=True, check=True).stdout.split("\n")
text = {line.split()[-1].split("/")[-1]: int(line.split()[0]) for line in size[1:] if line.strip()}
print(f"     bank 1: looper.o {text['looper.o']} B + looper_thunk.o {text['looper_thunk.o']} B; bank 2: looper_dsp.o {text['looper_dsp.o']} B")
check("the glue is in the cave (bank 1): hooks, latch, process / active wrappers, tick, axis table",
      all(0x080F1E78 <= sym[s] < 0x08100000 for s in ("looper_register_fxa", "looper_latch", "looper_process", "looper_active",
                                                      "looper_tick", "looper_fxa_set", "lp_axes")), {s: hex(sym[s]) for s in ("looper_latch", "lp_axes")})
check("the DSP is in bank 2: lp_run, lp_block", all(0x08100000 <= sym[s] < 0x081E0000 for s in ("lp_run", "lp_block")))
check(f"bank 1 costs at most 700 B ({text['looper.o'] + text['looper_thunk.o']} B)", text["looper.o"] + text["looper_thunk.o"] <= 700)
dis = subprocess.run(["arm-none-eabi-objdump", "-d", "out/obj/looper_dsp.o"], capture_output=True, text=True, check=True).stdout
calls = sorted({ln.split("<")[1].split(">")[0].split("+")[0] for ln in dis.splitlines() if "\tbl\t" in ln or "\tblx\t" in ln or "\tb.w\t" in ln})
check("looper_dsp.c calls only itself (bank 2 is leaf code: no libgcc, no memset)",
      set(calls) <= {"lp_round", "lp_wrap", "lp_ram", "lp_chans", "lp_block", "lp_engage", "lp_length", "lp_cap_idx", "lp_gather",
                     "lp_phase", "lp_exp2", "lp_tan", "lp_sdram", "lp_s16", "lp_run", "lp_xstart", "lp_xfrom", "lp_lock", "lp_mod",
                     "lp_np"}, calls)
excl = [ln for ln in subprocess.run(["arm-none-eabi-objdump", "-d", "out/obj/looper.o", "out/obj/looper_dsp.o", "out/obj/looper_thunk.o"],
                                    capture_output=True, text=True, check=True).stdout.splitlines() if "\tldrex" in ln or "\tstrex" in ln]
check("no exclusive access in the Looper's code (D-013)", not excl, excl[:3])

# the boot hook clears the Looper's magic, so a reset never inherits a half-made state from SDRAM
b = Emu(IMAGE, "out/cave.elf")
for base, size_ in ((0x38800000, 0x1000), (0x58024000, 0x1000), (0x50003000, 0x1000), (0xC0000000, 0x1000000)):
    b.uc.mem_map(base, size_)
b.stub(0x0806AA80)
b.stub(0x0804436C, lambda: b.calls.append(b.arg(0)), value=MB)
b.w32(LP, 0x3152504C)
b.calls.clear()
b.call("master_alloc", 0x24076000, 192000)
check("master_alloc: the block grows to 0x84300 (the Looper's 0x200 at +0x2d900, 0x800 before it kept for the Clip Window) and the Looper's magic is cleared",
      b.r32(LP) == 0 and b.r32(PMEM) & 0xFFFFFFFF == MB, (hex(b.r32(LP)), hex(b.r32(PMEM) & 0xFFFFFFFF)))

# ---- T2 the patch sites, decoded from the image
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs  # noqa: E402
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def insn(a, data=img):
    i = next(md.disasm(data[a - 0x08040000:a - 0x08040000 + 4], a))
    return i.mnemonic, int(i.op_str.lstrip("#"), 16) if i.op_str.startswith("#0x") else i.op_str


check("0x0808c594: FX A's list registration calls looper_register_fxa", insn(0x0808C594) == ("bl", sym["looper_register_fxa"] & ~1), insn(0x0808C594))
check("0x0806e174: the slot setter's FX A case branches (b.w) to looper_fxa_set", insn(0x0806E174) == ("b.w", sym["looper_fxa_set"] & ~1), insn(0x0806E174))
check("...and its stock neighbours are untouched (the class load at 0x0806e178, FX B's case at 0x0806e150)",
      img[0x0806E178 - 0x08040000:0x0806E188 - 0x08040000] == stock[0x0806E178 - 0x08040000:0x0806E188 - 0x08040000]
      and img[0x0806E150 - 0x08040000:0x0806E154 - 0x08040000] == stock[0x0806E150 - 0x08040000:0x0806E154 - 0x08040000])
check("the four FX A axis-table literals point at lp_axes / lp_axes + 4",
      [iw(a) for a in (0x080B1E44, 0x080B1E48, 0x080B20B8, 0x080B20BC)] == [sym["lp_axes"], sym["lp_axes"] + 4] * 2)
check("FX B's four literals are stock", [iw(a) for a in (0x080B1E4C, 0x080B1E50, 0x080B20C4, 0x080B20C8)] == [iw(a, stock) for a in (0x080B1E4C, 0x080B1E50, 0x080B20C4, 0x080B20C8)])
check("Repeater vtable: process (+0x0c) -> looper_process, active (+0x70) -> looper_active",
      iw(0x080DF58C) == sym["looper_process"] | 1 and iw(0x080DF5F0) == sym["looper_active"] | 1)
check("...hold (+0x74) and set_param (+0x64) stay stock", iw(0x080DF5F4) == 0x0806D135 and iw(0x080DF5E4) == 0x0806D0B9)
ax = struct.unpack_from("<I10H", img, sym["lp_axes"] - 0x08040000)
check("lp_axes: 5 types; Repeater, Gater, Filter as stock; Looper and Loop In = (Length 0x1cc, HPF 0x30)",
      ax == (5, 0x1C, 0x13, 0x1D, 0x1E, 0x10, 0x11, P_LEN, P_HPF, P_LEN, P_HPF)
      and stock[0x080EEA7C - 0x08040000:0x080EEA88 - 0x08040000] == struct.pack("<6H", *ax[1:7]) and sym["lp_axes"] % 4 == 0, ax)

# ---- T3 registration: the stock registrar, whole, with the real register functions (they fill the param registry)
u = Emu(IMAGE, "out/cave.elf")
for base, size_ in ((0x38800000, 0x1000), (0x58024000, 0x1000), (0x50003000, 0x1000), (0xC0000000, 0x400000)):
    u.uc.mem_map(base, size_)
uheap = [0xC0000000]


def ualloc():
    a = uheap[0]
    uheap[0] += (u.arg(0) + 31) & ~31
    u.uc.mem_write(a, bytes(u.arg(0)))
    u.uc.reg_write(UC_ARM_REG_R0, a)


u.stub(0x0804436C, ualloc)
regs = {}


def sp(n):
    return u.r32(u.uc.reg_read(UC_ARM_REG_SP) + 4 * n) & 0xFFFFFFFF


def ustr(a):
    try:
        return bytes(u.uc.mem_read(a, 32)).split(b"\0")[0].decode("latin1")
    except Exception:
        return f"<{a:#x}>"


def on_list(uc, a, s_, _):
    cnt = sp(0)
    names = u.arg(3)
    regs[u.arg(1)] = ("list", ustr(u.arg(2)), [ustr(u.r32(names + 4 * i) & 0xFFFFFFFF) for i in range(min(cnt, 64))] if names else [], ustr(sp(1)))


def on_num(uc, a, s_, _):
    regs[u.arg(1)] = ("num", u.arg(2), ustr(u.arg(3)), u.r32(u.uc.reg_read(UC_ARM_REG_SP)), sp(1), ustr(sp(2)))


u.uc.hook_add(UC_HOOK_CODE, on_list, begin=0x0808C0D8, end=0x0808C0D8)
u.uc.hook_add(UC_HOOK_CODE, on_num, begin=0x0808C12C, end=0x0808C12C)
u.call(0x0808C158, 0x24064000, count=50_000_000)
check("FX A (0x18): Repeater, Gater, Filter, Looper, Loop In ('FX A:', fxalgolivea)",
      regs.get(0x18) == ("list", "FX A:", ["Repeater", "Gater", "Filter", "Looper", "Loop In"], "fxalgolivea"), regs.get(0x18))
check("Length (0x1cc): 4 bars, 2 bars, 1 bar, 1/2, 1/4, 1/8, 1/16 (stock's own strings), xml looperlen",
      regs.get(P_LEN) == ("list", "Length:", LENS, "looperlen"), regs.get(P_LEN))
check("HPF (0x30) is still stock's: type 0xa, 0..1000, echohpf", regs.get(0x30) == ("num", 0xA, "HPF:", 0, 1000, "echohpf"), regs.get(0x30))
check("FX B (0x19) is untouched: six types", regs.get(0x19, ("", "", []))[2] == ["Crusher", "Filter", "Echo", "EchoHP", "Flanger", "Echo2"], regs.get(0x19))
xmls = [r[-1] for r in regs.values()]
check("'looperlen' is a new xml name (no clash)", xmls.count("looperlen") == 1)
u2 = Emu(IMAGE, "out/cave.elf")
for base, size_ in ((0x38800000, 0x1000), (0x58024000, 0x1000), (0x50003000, 0x1000)):
    u2.uc.mem_map(base, size_)
got = []
u2.stub(0x0808C0D8, lambda: got.append([u2.cstr(u2.r32(u2.arg(3) + 4 * i) & 0xFFFFFFFF) for i in range(u2.r32(u2.uc.reg_read(UC_ARM_REG_SP)))]))
u2.stub(sym["b2_present"], value=0)
u2.w32(STACK, 3)
u2.w32(STACK + 4, 0x080CBA54)
u2.call("looper_register_fxa", 0x24064000, 0x18, 0x080CBA4C, 0x080EB5B8)
check("no bank 2 payload: Looper and Loop In read '---' (as master.c's Prism)", got[0] == ["Repeater", "Gater", "Filter", "---", "---"], got)

# ---- T4 the XY view, real code: axis binding, rest values, value map, the type-change and finger-up paths
VIEW = 0x24064000
u.uc.mem_write(VIEW, bytes(0x900))
u.uc.mem_write(0x2402EEEC, struct.pack("<IH", 0, 0x330))      # the pad descriptors the view compares cells against
u.uc.mem_write(0x2402EEE4, struct.pack("<IH", 0, 0x340))
posts = []
u.stub(0x080AED14, lambda: posts.append(struct.unpack_from("<HxxIHxxIi", bytes(u.uc.mem_read(u.arg(1), 0x18)))), value=1)
binds = {}
for idx in range(5):
    u.call(0x080B1DE0, VIEW, 0, idx, count=5_000_000)
    pad = VIEW + 0x22C
    binds[idx] = (u.r16(pad + 0x3C), u.r16(pad + 0x3E), u.r32(pad + 0x40), u.r32(pad + 0x44))
check("FX A index 0..4 binds (X, Y): Repeater (0x1c, 0x13), Gater (0x1d, 0x1e), Filter (0x10, 0x11), Looper / Loop In (0x1cc, 0x30)",
      [b[:2] for b in binds.values()] == [(0x1C, 0x13), (0x1D, 0x1E), (0x10, 0x11), (P_LEN, P_HPF), (P_LEN, P_HPF)], binds)
check("...and the dot's rest position for the Looper is X = 3 (1/2), Y = 500: the values the view posts at rest",
      binds[3][2:] == (3, 500), binds[3])
u.call(0x080B1DE0, VIEW, 0, 5, count=5_000_000)
check("index 5 is past the relocated count: nothing is bound", u.r16(VIEW + 0x22C + 0x3C) == P_LEN)
fxb = []
for idx in range(6):
    u.call(0x080B1DE0, VIEW, 1, idx, count=5_000_000)
    fxb.append((u.r16(VIEW + 0x298 + 0x3C), u.r16(VIEW + 0x298 + 0x3E)))
check("FX B binds as stock", fxb == [(0x16, 0x17), (0x10, 0x11), (0x2D, 0x2F), (0x2D, 0x30), (0x2B, 0x2C), (0x2E, 0x2F)], fxb)


def xymap(coord, origin, size_, pid):
    u.w32(STACK, pid)
    u.call(0x080B26C8, VIEW + 0x22C, coord, origin, size_, count=1_000_000)
    return u.uc.reg_read(UC_ARM_REG_R0)


xs = [xymap(65 + c, 65, 255, P_LEN) for c in range(256)]
bands = [xs.index(i) for i in range(7)] if all(i in xs for i in range(7)) else []
widths = np.diff(bands[1:]) if len(bands) == 7 else []
check("X over the pad's 255 px: 7 equal bands (~32 px) in list order, 4 bars at the left, 1/16 at the right",
      xs[0] == 0 and xs[-1] == 6 and xs == sorted(xs) and len(bands) == 7 and bands[1] == 48 and all(31 <= w <= 33 for w in widths),
      (xs[:3], xs[-3:], bands))
ys = [xymap(120 + c, 120, 120, P_HPF) for c in range(121)]
check("Y over the pad's 120 px: 0..1000, 0 at the near edge (inside the 16 px margin)", ys[0] == 0 and ys[16] == 0 and ys[-1] == 1000 and ys == sorted(ys), (ys[:20:4], ys[-5:]))

# the stretch: the view's own handler. A knob change to type 3 / 4 (msg 0x3c) re-binds through the relocated table,
# and a finger-up with Hold off posts the rest values, X then Y, before the release goes on up.
for idx in (3, 4):
    posts.clear()
    u.uc.mem_write(VIEW + 0x22C + 0x3C, b"\0" * 4)
    u.uc.mem_write(0x24065000, struct.pack("<HHIHHIi", 0x3C, 0, 0, 0x330, 0, idx, 0x18))
    u.call(0x080B1EE4, VIEW, 0x24065000, count=5_000_000)
    check(f"view handler, msg 0x3c type {idx}: index stored, pad bound to (0x1cc, 0x30), the change forwarded",
          u.r32(VIEW + 0x8CC) == idx and (u.r16(VIEW + 0x22C + 0x3C), u.r16(VIEW + 0x22C + 0x3E)) == (P_LEN, P_HPF)
          and posts and posts[-1][2:] == (0x330, 0x18, idx), (u.r32(VIEW + 0x8CC), posts))
posts.clear()
u.uc.mem_write(0x24065000, struct.pack("<HHIHHIi", 0x6E, 0, 0, 0x330, 0, P_FINGER, 0))
ret = u.call(0x080B1EE4, VIEW, 0x24065000, count=5_000_000)
check("finger-up on FX A with Hold off: the view posts X rest (0x1cc = 3) then Y rest (0x30 = 500), and lets the 0x15 = 0 on",
      [(p[2], p[3], p[4]) for p in posts] == [(0x330, P_LEN, 3), (0x330, P_HPF, 500)] and u.uc.reg_read(UC_ARM_REG_R0) == 1, posts)


def touch(rig, x=None, y=None):
    """the pad's down handler: 0x15 = 1, then X, then Y at the touch point"""
    rig.post(P_FINGER, 1)
    if x is not None:
        rig.post(P_LEN, x)
    if y is not None:
        rig.post(P_HPF, y)


def lift(rig, hold=False):
    """the pad's up handler; with Hold off the view posts the rest values first"""
    if not hold:
        rig.post(P_LEN, 3)
        rig.post(P_HPF, 500)
    rig.post(P_FINGER, 0)


def hold_button(rig, v):
    """the Hold button: 0x1a, then the view's rest values"""
    rig.post(P_HOLD, v)
    rig.post(P_LEN, 3)
    rig.post(P_HPF, 500)


# ---- T5 the latch and the swap, on the real container
rig = Rig()
rig.run(4)
rig.resets.clear()
rig.post(0x18, 3)
l, r = rig.run(1)
d = rig.dsp()
check("Repeater -> Looper: same object, no swap, the Repeater reset once (our latch), mode 3",
      rig.fx() == REP1 and rig.e.r32(rig.sub + 0x24) == 0 and rig.resets == [REP1] and rig.mode() == 3, (hex(rig.fx()), rig.resets, rig.mode()))
check("...and the Looper runs in the same block: one block of ring", d["init"] == 0x3150534C and d["valid"] == N and d["obj"] == REP1, d)
rig.run(50)
rig.resets.clear()
rig.post(0x18, 4)
rig.run(1)
check("Looper -> Loop In: no reset, same object; the ring starts over (it held the other source)",
      rig.resets == [] and rig.fx() == REP1 and rig.mode() == 4 and rig.dsp()["valid"] == N, (rig.resets, rig.dsp()["valid"]))
rig.run(10)
fx = rig.fx()
rlp, rrp = rig.e.r32(fx + 0x3C) & 0xFFFFFFFF, rig.e.r32(fx + 0x40) & 0xFFFFFFFF
for p in (rlp, rrp):                              # what a full ring leaves at the end of the buffers: int16 pairs, NaN as floats
    rig.e.uc.mem_write(p + 4 * (384000 - 4096), b"\xff\xff" * 2 * 4096)
rig.post(0x18, 0)
rig.run(1)
tails = [np.frombuffer(bytes(rig.e.uc.mem_read(p + 4 * (384000 - 2048), 4 * 2048)), "<f4") for p in (rlp, rrp)]
check("Loop In -> Repeater: the Repeater is reset, and the last 2048 floats of both ring buffers are 0.0 (the backfill's reach)",
      rig.resets == [REP1] and rig.mode() == 0 and all((t == 0).all() for t in tails), (rig.resets, [int(np.isnan(t).sum()) for t in tails]))
# the Repeater as A5 measured it: touch, 1/8, wet 100 %; slices 12,000 frames apart, every one the same audio, never NaN
rig.post(P_FINGER, 1)
rig.post(0x1C, 1)
rig.post(0x13, 1000)
l, r = rig.run(400)
k = dec(l, r)
w0 = len(k) - 36000
rep_ok = np.mean((k[w0:w0 + 24000] == k[w0 + 12000:w0 + 36000]) & (k[w0:w0 + 24000] >= 0))
check(f"...then the Repeater repeats as stock: slices 12,000 frames apart ({rep_ok:.1%} of a 24,000-frame window), no NaN",
      rep_ok > 0.9 and np.isfinite(l).all() and np.isfinite(r).all(), rep_ok)
rig.post(P_FINGER, 0)
rig.run(4)
rig.post(0x18, 3)
rig.run(2)
rig.post(0x18, 1)
rig.post(0x18, 3)
l, r = rig.run(1)
check("Looper -> Gater -> Looper in one block: lands on the second Repeater (0x24015340), the Looper starts over on it",
      rig.fx() == REP2 and rig.dsp()["obj"] == REP2 and rig.dsp()["valid"] == N and rig.mode() == 3, (hex(rig.fx()), rig.dsp()["valid"]))
l, r = rig.run(20)
check("...and works there: Out 1 passes untouched, the ring fills", (dec(l, r) == np.arange(rig.S - 20 * N, rig.S)).all() and rig.dsp()["valid"] == 21 * N)
rig.post(0x18, 5)
rig.run(1)
check("index 5: ignored (bound kept), type and mode unchanged", rig.mode() == 3 and rig.fx() == REP2)


def nomaster(idx):
    rg = Rig(master=False)
    rg.run(2)
    rg.post(0x18, idx)
    rg.run(90)
    rg.post(P_FINGER, 1)
    rg.post(0x1C, 1)
    rg.post(0x13, 1000)
    return rg.run(300)


a, b = nomaster(3), nomaster(0)
check("no boot block (master_alloc did not run): Looper behaves exactly as the Repeater", np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])
      and not np.array_equal(a[0], enc(np.arange(92 * N, 392 * N))[0]))

# ---- T6 idle: the ring is fed, Out 1 untouched
rig = Rig()
rig.post(0x18, 3)
l, r = rig.run(200)
k = dec(l, r)
rl, rr = rig.ring(200 * N)
check("idle Looper, 200 blocks: Out 1 bit-identical to the input", (k == np.arange(0, 200 * N)).all() and np.array_equal(l, enc(np.arange(200 * N))[0]))
check("...the ring holds the same frames as int16 (x 8192)", np.array_equal(rl, (enc(np.arange(200 * N))[0] * 8192).astype(np.int16))
      and np.array_equal(rr, (enc(np.arange(200 * N))[1] * 8192).astype(np.int16)))
rig.e.call("looper_active", REP1)
act = rig.e.uc.reg_read(UC_ARM_REG_R0)
rig.e.w32(LP + 4, 0)
rig.e.call("looper_active", REP1)
check("active() = 1 in Looper mode (the ring is fed while idle), the Repeater's own answer otherwise", act == 1 and rig.e.uc.reg_read(UC_ARM_REG_R0) == 0)
rig.e.w32(LP + 4, 3)


# ---- T7 the catch, on the grid
def catch(bpm, at, x, passes, y=0, tick_shift=0):
    rg = Rig(bpm=bpm)
    rg.tick_shift = tick_shift
    rg.post(0x18, 3)
    rg.until(at)
    touch(rg, x, y)
    S = rg.S
    t = rg.ticks(S)
    lt = TICKS[x]
    in_tick = (t // lt) * lt
    L = lt * 3000.0 / bpm
    l, r = rg.until(int(frames_at(rg, in_tick) + (passes + 1) * L) + 256)
    return rg, S, t, in_tick, L, l, r


rig, S, t, in_tick, L, l, r = catch(120.0, 243200, 2, 3)
k = dec(l, r)
IN = 192000
check("touch mid-bar (tick 9728, 120 BPM, 1 bar): the in-point is the bar line at tick 7680 = frame 192,000",
      in_tick == 7680 and rig.dsp()["in_idx"] == IN and t == 9728, (in_tick, rig.dsp()["in_idx"]))
live = k[:288000 - S]
check("until the bar line the output is the input, bit for bit (the read head is on the frame being written)",
      (live == np.arange(S, 288000)).all() and np.array_equal(l[:288000 - S], enc(np.arange(S, 288000))[0]))
ok, seams = True, True
for p in range(3):
    T = 288000 + p * 96000
    seg = k[T - S + 64:T - S + 96000]
    ok &= (seg == np.arange(IN + 64, IN + 96000)).all()
    j = np.arange(64)
    tt = (64 - j) / 64.0
    want_l = enc(IN + j)[0] + (enc(IN + 96000 + j)[0] - enc(IN + j)[0]) * tt
    seams &= np.allclose(l[T - S:T - S + 64], want_l, atol=1e-6)
check("then 3 passes of input [192,000, 288,000), exact outside the 64-frame seams", ok)
check("each seam is the linear blend of the continuation (in + L + j) and the in-point (in + j)", seams)


def wraps(rg, S, l, r, in_tick, L, bpm):
    """the pass starts seen in the output, against the tempo grid: (count, worst error in frames)"""
    k = dec(l, r)
    tfr = np.arange(S, S + len(k))
    ok = k >= 0
    starts = tfr[ok] - (k[ok] - rg.dsp()["in_idx"])        # frame where this frame's pass started (ring index = frame here)
    vals, counts = np.unique(starts, return_counts=True)
    vals = vals[counts > L / 4]
    grid = frames_at(rg, in_tick)
    errs = [abs(v - (grid + round((v - grid) / L) * L)) for v in vals]
    return len(vals), max(errs) if errs else 1e9


for bpm in (97.3, 174.0):
    rig, S, t, in_tick, L, l, r = catch(bpm, 300032, 6, 50)
    n_, err = wraps(rig, S, l, r, in_tick, L, bpm)
    fpt = 3000.0 / bpm
    check(f"{bpm} BPM, 1/16 ({L:.2f} frames), 50 passes: every pass starts within 0.5 tick + 1 frame of the grid ({n_} passes, worst {err:.2f} frames, bound {0.5 * fpt + 1:.2f})",
          n_ >= 50 and err <= 0.5 * fpt + 1, (n_, err))


def engaged_rig(x=2, y=0, at=243200, bpm=120.0, sig=enc):
    rg = Rig(bpm=bpm)
    rg.post(0x18, 3)
    rg.until(at, sig)
    touch(rg, x, y)
    rg.run(1, sig)
    return rg


# ---- T8 X: the in-point stays
rig = engaged_rig()
rig.until(288000 + 50048)
rig.post(P_LEN, 6)                                # a move to 1/16: the view posts it, it applies one block later
l0, r0 = rig.run(1)
d0 = rig.dsp()
Sj = rig.S
l, r = rig.run(200)
k = dec(l, r)
t = np.arange(Sj, Sj + len(k))
want = IN + (t - 288000) % 6000
mask = ((t - Sj) >= 64) & (((t - 288000) % 6000) >= 64)
check("X 1 bar -> 1/16 mid-pass (posted, applied one block later): held for that block, then a jump to the same phase of the 1/16 loop",
      d0["len_idx"] == 2 and d0["px"] == 6 and (dec(l0, r0) == IN + np.arange(Sj - N, Sj) - 288000).all() and (k[mask] == want[mask]).all(),
      (d0["len_idx"], d0["px"], int(np.sum(k[mask] != want[mask]))))
check("...the jump is crossfaded (64 frames), and the 1/16 loop repeats [192,000, 198,000) on the grid", (k[:64] < 0).sum() > 32 and rig.dsp()["lf"] == 6000.0)
Pk = 288000 + ((rig.S - 288000) // 6000) * 6000      # the current pass's start
rig.until(Pk + 6000 + 1024)
rig.post(P_LEN, 2)
rig.run(1)
Sk = rig.S                                         # 1 bar applies at the start of this block
l, r = rig.until(rig.S + 2 * 96000)
k = dec(l, r)
t = np.arange(Sk, Sk + len(k))
want = IN + (t - 288000) % 96000
mask = ((t - Sk) >= 64) & (((t - 288000) % 96000) >= 64)
check("1/16 -> 1 bar: the read head goes (crossfaded) to where the bar is on the grid, so its passes start on the bar lines again",
      (k[mask] == want[mask]).all() and (k[:64] < 0).sum() > 32, int(np.sum(k[mask] != want[mask])))
rig = engaged_rig(x=4)                             # 1/4 from tick 9600 (frame 240,000): passes of 24,000 frames
rig.until(264000 + 6016)                           # into its second pass: it loops
rig.post(P_LEN, 2)
rig.run(1)
Sx = rig.S
l, r = rig.until(336000 + 96000 + 1024)
k = dec(l, r)
t = np.arange(Sx, Sx + len(k))
lv = (t >= Sx + 64) & (t < 336000)
lp_ = (t >= 336000 + 64) & ((t - 336000) % 96000 >= 64)
check("1/4 -> 1 bar before a bar has passed since the in-point: live again until in + 1 bar, then the bar [240,000, 336,000) loops",
      (k[lv] == t[lv]).all() and (k[lp_] == 240000 + (t[lp_] - 336000) % 96000).all() and rig.dsp()["in_idx"] == 240000,
      (int(np.sum(k[lv] != t[lv])), int(np.sum(k[lp_] != 240000 + (t[lp_] - 336000) % 96000))))

TONE = 221.37                                      # Hz: no loop length holds a whole number of its cycles
OWN = 0.5 * 2 * np.pi * TONE / FS                  # the tone's own largest step between frames
STEP = OWN + 2 * 0.5 / 64                          # a crossfade between two parts of it may add up to 2 x peak / 64


def sine(kk):
    x = (0.5 * np.sin(2 * np.pi * TONE * np.asarray(kk) / FS)).astype(np.float32)
    return x, x


cut = min(abs(np.sin(np.pi * ((TONE * lt * 25 / FS) % 1.0))) for lt in TICKS)
check(f"the click tests' tone is not coherent with any length at 120 BPM: a hard cut at a seam would step by >= {cut:.3f}, the bound is {STEP:.4f}",
      cut > 2 * STEP, cut)
rig = engaged_rig(sig=sine)
outs = []
for x in (2, 3, 4, 5, 6, 5, 4, 3, 2, 1, 0, 1, 2, 6, 0, 6, 3):
    rig.post(P_LEN, x)
    outs.append(rig.run(25, sine)[0])
o = np.concatenate(outs)
step = float(np.max(np.abs(np.diff(o))))
check(f"X swept over all 7 lengths on a {TONE} Hz sine: largest step between frames {step:.4f} (bound {STEP:.4f})", step <= STEP, step)
for b, x, want_idx in ((60.0, 0, 1), (60.1, 0, 0), (120.0, 0, 0)):
    rg = engaged_rig(x=x, bpm=b, at=243200)
    d = rg.dsp()
    check(f"4 bars at {b} BPM: {'clamped to 2 bars (the ring holds 16.0 s)' if want_idx else 'fits'}", d["len_idx"] == want_idx and d["last_len"] == 0, d["len_idx"])

# ---- T9 release
rig = engaged_rig()
rig.until(300032)
lf0 = rig.dsp()["lf"]
lift(rig)
Sr = rig.S
l, r = rig.run(12)
d = rig.dsp()
k = dec(l, r)
loop = enc(IN + (np.arange(Sr, Sr + 256) - 288000) % 96000)
g = 1 - np.arange(256) / 256.0
live = enc(np.arange(Sr, Sr + 256))
check("finger-up with Hold off (rest posts X = 1/2, Y = 50 % in the same drain): the rest posts are not applied",
      d["lf"] == lf0 and d["len_idx"] == 2 and d["yt"] == 0.0 and d["engaged"] == 0, d)
check("the loop fades to live over 256 frames", np.allclose(l[:256], live[0] + g * (loop[0] - live[0]), atol=1e-6))
check("...then it is live, bit for bit", np.array_equal(l[256:], enc(np.arange(Sr + 256, Sr + 12 * N))[0])
      and np.array_equal(r[256:], enc(np.arange(Sr + 256, Sr + 12 * N))[1]))
rig = engaged_rig()
rig.until(300032)
rig.post(P_LEN, 3)                                # the race: the rest posts in one block, the release in the next
rig.post(P_HPF, 500)
l1, r1 = rig.run(1)
d1 = rig.dsp()
rig.post(P_FINGER, 0)
rig.run(1)
d2 = rig.dsp()
k1 = dec(l1, r1)
check("race (rest posts one block before the 0x15 = 0): they wait a block, and the release drops them; no length jump is heard",
      d1["px"] == 3 and d1["lf"] == 96000.0 and (k1 == IN + np.arange(rig.S - 2 * N, rig.S - N) - 288000).all()
      and d2["px"] == -1 and d2["lf"] == 96000.0 and d2["yt"] == 0.0 and d2["engaged"] == 0, (d1["px"], d2["lf"], d2["yt"]))

# a stall piles up the posts: 40 moves in one drain (more than the 32 event slots), the lp_gather path
rig = engaged_rig()
rig.until(300032)
for i in range(40):
    rig.post(P_LEN, (i // 2) % 7) if i % 2 == 0 else rig.post(P_HPF, 10 * i)
rig.post(P_LEN, 5)
rig.post(P_HPF, 700)
rig.run(2)
d = rig.dsp()
check("42 moves in one drain: the last X and Y win (1/8, HPF 70 %), the in-point kept", d["len_idx"] == 5 and abs(d["yt"] - 0.7) < 1e-6 and d["in_idx"] == IN, d)
for i in range(40):
    rig.post(P_LEN, (i // 2) % 7) if i % 2 == 0 else rig.post(P_HPF, 10 * i)
lift(rig)
rig.run(2)
check("40 moves then the release in one drain: released (v1 kept the first 32 posts and dropped the release)",
      rig.dsp()["engaged"] == 0 and rig.dsp()["gt"] == 0.0 and rig.dsp()["len_idx"] == 5)

# ---- T10 Hold
rig = engaged_rig(x=4)
hold_button(rig, 1)
rig.run(1)
d = rig.dsp()
check("touch (1/4), then Hold on with its rest posts: latched, still 1/4, HPF open", d["hold"] == 1 and d["len_idx"] == 4 and d["yt"] == 0.0 and d["engaged"] == 1, d)
lift(rig, hold=True)
rig.run(1)
in0 = rig.dsp()["in_idx"]
l, r = rig.run(400)
k = dec(l, r)
t = np.arange(rig.S - 400 * N, rig.S)
P0 = 240000                                      # tick 9728 lies in the 1/4 that starts at 9600 = frame 240,000
want = P0 + (t - P0) % 24000
mask = ((t - P0) % 24000) >= 64
check("finger up while held: it keeps looping the same quarter", rig.dsp()["engaged"] == 1 and in0 == P0 and (k[mask] == want[mask]).all())
touch(rig, 6, 200)
rig.run(2)
d = rig.dsp()
check("a re-touch while latched moves X / Y only: 1/16 and HPF 20 %, the same in-point", d["in_idx"] == P0 and d["len_idx"] == 6 and abs(d["yt"] - 0.2) < 1e-6, d)
lift(rig, hold=True)
hold_button(rig, 0)
rig.run(1)
check("Hold off (finger up): released", rig.dsp()["engaged"] == 0 and rig.dsp()["gt"] == 0.0)
rig.run(4)
hold_button(rig, 1)
rig.run(1)
d = rig.dsp()
check("Hold alone engages: the last length (1/16), HPF open", d["engaged"] == 1 and d["len_idx"] == 6 and d["yt"] == 0.0, d)
rg = Rig()
rg.post(0x18, 3)
rg.run(800)
hold_button(rg, 1)
rg.run(1)
check("Hold alone on a fresh Looper: 1 bar", rg.dsp()["engaged"] == 1 and rg.dsp()["len_idx"] == 2)

# ---- T11 the HPF, and the firmware DSP against the host build of the same file
LIB = "out/liblooper.so"
subprocess.run([os.environ.get("CC") or shutil.which("clang") or shutil.which("cc") or "cc", "-O2", "-shared", "-fPIC",
                "-Wno-unknown-pragmas", "-Wno-ignored-pragmas", "-o", LIB, "src/looper_dsp.c"], check=True)
host = ctypes.CDLL(os.path.abspath(LIB))


class Ev(ctypes.Structure):
    _fields_ = [("id", ctypes.c_uint16), ("v", ctypes.c_int16)]


class HIn(ctypes.Structure):
    _fields_ = [("sl", ctypes.c_void_p), ("sr", ctypes.c_void_p), ("rl", ctypes.c_void_p), ("rr", ctypes.c_void_p),
                ("cap", ctypes.c_int32), ("phase", ctypes.c_uint32), ("fpt", ctypes.c_float), ("gl", ctypes.c_float),
                ("gr", ctypes.c_float), ("playing", ctypes.c_uint8),
                ("edge", ctypes.c_uint8), ("src", ctypes.c_uint8), ("mon", ctypes.c_uint8), ("nev", ctypes.c_uint8),
                ("_r", ctypes.c_uint8 * 3), ("ev", Ev * 32)]


host.lp_block.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIn), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]


class HostLooper:
    """lp_block on the host: one block at a time, the same arguments the firmware's lp_gather would hand it"""

    def __init__(self, cap=768000, src=0, mon=0):
        self.d = ctypes.create_string_buffer(512)
        self.rl, self.rr = np.zeros(cap, np.int16), np.zeros(cap, np.int16)
        self.cap, self.src, self.mon = cap, src, mon

    def state(self):
        return dict(zip(DSP_KEYS, struct.unpack(DSP_FMT, self.d.raw[:DSP_SIZE])))

    def block(self, l, r, sl=None, sr=None, events=(), phase=0, fpt=25.0, playing=1, edge=0, gl=1.0, gr=1.0):
        l, r = np.ascontiguousarray(l, np.float32).copy(), np.ascontiguousarray(r, np.float32).copy()
        sl = l.copy() if sl is None else np.ascontiguousarray(sl, np.float32)
        sr = r.copy() if sr is None else np.ascontiguousarray(sr, np.float32)
        h = HIn()
        h.sl, h.sr = sl.ctypes.data, sr.ctypes.data
        h.rl, h.rr = self.rl.ctypes.data, self.rr.ctypes.data
        h.cap, h.phase, h.fpt, h.playing, h.edge, h.src, h.mon = self.cap, phase, fpt, playing, edge, self.src, self.mon
        h.gl, h.gr = gl, gr
        h.nev = len(events)
        for i, (pid, v) in enumerate(events):
            h.ev[i].id, h.ev[i].v = pid, v
        host.lp_block(self.d, ctypes.byref(h), l.ctypes.data, r.ctypes.data, len(l))
        return l, r


def gain(y, f, seconds=1.0):
    """the loop's level through the HPF at Y = y, for a sine at f (host build, first pass = live input)"""
    hl = HostLooper()
    kk = np.arange(int(seconds * FS) // N * N)
    x = (0.5 * np.sin(2 * np.pi * f * kk / FS)).astype(np.float32)
    out = []
    for b in range(len(kk) // N):
        ev = [(P_FINGER, 1), (P_LEN, 0), (P_HPF, int(round(y * 1000)))] if b == 0 else []
        l, _ = hl.block(x[b * N:(b + 1) * N], x[b * N:(b + 1) * N], events=ev, phase=0)
        out.append(l)
    o = np.concatenate(out)[len(kk) // 2:]
    return float(np.sqrt(np.mean(o.astype(np.float64) ** 2)) / (0.5 / math.sqrt(2)))


for y in (0.25, 0.5, 0.75):
    fc = 10 * 400 ** y
    lo, hi = fc * 0.3, fc * 2
    for _ in range(18):
        mid = math.sqrt(lo * hi)
        lo, hi = (mid, hi) if gain(y, mid) < 1 / math.sqrt(2) else (lo, mid)
    f3 = math.sqrt(lo * hi)
    at_fc = 20 * math.log10(gain(y, fc))
    want = 0.786 * fc                              # a 2-pole high-pass at Q 1 is 3 dB down at 0.786 fc (and 0 dB at fc)
    check(f"HPF at Y = {y:.2f}: fc {fc:.0f} Hz; -3 dB at {f3:.1f} Hz (Q 1: {want:.1f}), {at_fc:+.2f} dB at fc",
          abs(f3 / want - 1) < 0.1 and abs(at_fc) < 0.6, (f3, want, at_fc))

# firmware lp_block against the host build: 300 blocks of noise and random gestures, both sources
fw = Emu(IMAGE, "out/cave.elf")
fw.uc.mem_map(0xC0000000, 0x400000)
FD, FIN, FL, FR, FSL, FSR, FRL, FRR = 0xC0000000, 0xC0001000, 0xC0002000, 0xC0003000, 0xC0004000, 0xC0005000, 0xC0010000, 0xC0100000
CAPT = 96000
rng = np.random.default_rng(37)
for src, mon in ((0, 0), (1, 1)):
    hl = HostLooper(cap=CAPT, src=src, mon=mon)
    fw.uc.mem_write(FD, bytes(512))
    fw.uc.mem_write(FRL, bytes(2 * CAPT))
    fw.uc.mem_write(FRR, bytes(2 * CAPT))
    worst, finger, hold, nan, later = 0.0, 0, 0, False, []
    for b in range(300):
        ev, later = later, []
        u_ = rng.random()
        if u_ < 0.06:
            finger ^= 1
            ev += [(P_FINGER, 1), (P_LEN, int(rng.integers(0, 7))), (P_HPF, int(rng.integers(0, 1001)))] if finger else [(P_LEN, 3), (P_HPF, 500), (P_FINGER, 0)]
        elif u_ < 0.08:
            hold ^= 1
            ev += [(P_HOLD, hold), (P_LEN, 3), (P_HPF, 500)]
        elif u_ < 0.2:
            ev += [(P_LEN, int(rng.integers(0, 7)))] if rng.random() < 0.5 else [(P_HPF, int(rng.integers(0, 1001)))]
        elif u_ < 0.21:
            ev += [(0xFFFF, 0)]
        if len(ev) == 3 and rng.random() < 0.3:      # the UI task cut off by this block: the rest of a gesture drains next time
            cut_ = int(rng.integers(1, 3))
            ev, later = ev[:cut_], ev[cut_:]
        dl, dr = (rng.standard_normal(N) * 0.3).astype(np.float32), (rng.standard_normal(N) * 0.3).astype(np.float32)
        sl, sr = (rng.standard_normal(N) * 0.2).astype(np.float32), (rng.standard_normal(N) * 0.2).astype(np.float32)
        if not src:
            sl, sr = dl, dr
        phase, edge = (b * N // 25) % 15360, int(rng.random() < 0.02)
        gain = 1.0 if not src else 0.75
        hlo, hro = hl.block(dl, dr, sl, sr, ev, phase=phase, edge=edge, gl=gain, gr=gain)
        fw.uc.mem_write(FL, dl.tobytes())
        fw.uc.mem_write(FR, dr.tobytes())
        fw.uc.mem_write(FSL, sl.tobytes())
        fw.uc.mem_write(FSR, sr.tobytes())
        evb = b"".join(struct.pack("<Hh", pid, v) for pid, v in ev).ljust(128, b"\0")
        fw.uc.mem_write(FIN, struct.pack("<4IiI3f4B4B", FSL, FSR, FRL, FRR, CAPT, phase, 25.0, gain, gain, 1, edge, src, mon, len(ev), 0, 0, 0) + evb)
        fw.w32(STACK, N)                              # n, the fifth argument, on the stack
        fw.call("lp_block", FD, FIN, FL, FR, count=5_000_000)
        flo = np.frombuffer(bytes(fw.uc.mem_read(FL, 4 * N)), np.float32)
        fro = np.frombuffer(bytes(fw.uc.mem_read(FR, 4 * N)), np.float32)
        nan |= not (np.isfinite(flo).all() and np.isfinite(fro).all())
        worst = max(worst, float(np.max(np.abs(flo - hlo))), float(np.max(np.abs(fro - hro))))
    fs_ = dict(zip(DSP_KEYS, struct.unpack(DSP_FMT, fw.uc.mem_read(FD, DSP_SIZE))))
    hs_ = hl.state()
    same = all(fs_[k_] == hs_[k_] for k_ in ("w", "valid", "engaged", "in_idx", "phi", "lcur", "len_idx", "frozen", "xf", "npass",
                                             "anch", "in_tick", "rn", "hskip", "pend"))
    check(f"{'Loop In (monitored)' if src else 'Looper'}: the unit's lp_block and the host build agree within 1e-5 over 300 random blocks "
          f"(worst {worst:.1e}), same loop state, never NaN", worst <= 1e-5 and same and not nan, (worst, {k_: (fs_[k_], hs_[k_]) for k_ in ("phi", "lcur", "in_idx")}))

rig = engaged_rig(sig=lambda kk: ((np.random.default_rng(int(kk[0])).standard_normal(N) * 0.4).astype(np.float32),) * 2)
noise = lambda kk: ((np.random.default_rng(int(kk[0])).standard_normal(N) * 0.4).astype(np.float32),) * 2  # noqa: E731
fms, bad = [], False
for y in list(range(0, 1001, 50)) + list(range(1000, -1, -50)) + [0]:
    rig.post(P_HPF, y)
    l, r = rig.run(3, noise)
    bad |= not (np.isfinite(l).all() and np.isfinite(r).all()) or np.max(np.abs(l)) > 20
    fms.append(rig.dsp()["fm"])
l, r = rig.run(4, noise)
d = rig.dsp()
check("Y swept 0 -> 1000 -> 0 on noise: no NaN, no blow-up; the filter fades in, and out again to a reset, exact bypass",
      not bad and max(fms) == 1.0 and d["fm"] == 0.0 and d["s1l"] == 0.0 and d["s2r"] == 0.0, (bad, max(fms), d["fm"]))

# ---- T17 (host build) the races, overlaps and drifts a review found in v1


class HostRun(HostLooper):
    """lp_block on a clock: frame counter S; the tick of a frame is rounded, as the engine's +0x30; Out 1 = sig"""

    def __init__(self, sig=enc, bpm=120.0, cap=768000, src=0, mon=0):
        super().__init__(cap, src, mon)
        self.sig, self.S, self.bpm, self.playing, self.t0, self.S0 = sig, 0, bpm, 1, 0.0, 0

    def fpt(self):
        return 3000.0 / self.bpm

    def tick(self, s):
        return int(math.floor((s - self.S0) / self.fpt() + self.t0 + 0.5))

    def set_bpm(self, bpm):
        """a tempo change: the tick count goes on from where it is, at the new rate"""
        self.t0, self.S0, self.bpm = (self.S - self.S0) / self.fpt() + self.t0, self.S, bpm

    def step(self, events=(), src_sig=None):
        kk = np.arange(self.S, self.S + N)
        l, r = self.sig(kk)
        sl, sr = src_sig(kk) if src_sig else (None, None)
        out = self.block(l, r, sl, sr, events, phase=self.tick(self.S) % 15360, fpt=self.fpt(), playing=self.playing)
        self.S += N
        return out

    def run(self, blocks, src_sig=None):
        out = [self.step(src_sig=src_sig) for _ in range(blocks)]
        return (np.concatenate([o[0] for o in out]), np.concatenate([o[1] for o in out])) if out else (np.zeros(0), np.zeros(0))

    def until(self, frame, src_sig=None):
        return self.run(max(0, (frame - self.S + N - 1) // N), src_sig)


# a held loop that froze the ring, released, and caught again inside its 256-frame release: the ring writes again, and
# no frame from before the re-catch is ever played (v1 kept the ring frozen and replayed audio up to 5.5 s old)
for playing in (1, 0):
    h = HostRun(cap=96000)
    h.playing = playing
    h.until(100096)
    h.step([(P_FINGER, 1), (P_LEN, 4), (P_HPF, 0)])
    h.step([(P_HOLD, 1), (P_LEN, 3), (P_HPF, 500)])
    h.step([(P_FINGER, 0)])
    while not h.state()["frozen"]:
        h.step()
    h.run(200)
    h.step([(P_HOLD, 0), (P_LEN, 3), (P_HPF, 500)])
    g0 = h.state()["g"]
    h.step([(P_FINGER, 1), (P_LEN, 4), (P_HPF, 0)])
    st = h.state()
    Sx = h.S - N
    l, r = h.run(1500)
    k = dec(l, r)
    old = k[(k >= 0) & (k < Sx)]
    check(f"{'playing' if playing else 'stopped'}, a frozen hold released and caught again within its release (g {g0:.2f}): the ring "
          f"writes again, nothing recorded before the re-catch is played ({len(old)} frames)",
          0 < g0 < 1 and st["frozen"] == 0 and st["engaged"] == 1 and len(old) == 0 and (k >= 0).mean() > 0.9, (st["frozen"], len(old)))

# a shortening jump that lands within 64 frames of the shorter loop's out-point: two crossfades overlap
found = []
for extra in range(0, 750):
    h = HostRun(sig=sine)
    h.until(243200)
    h.step([(P_FINGER, 1), (P_LEN, 2), (P_HPF, 0)])
    h.until(288000 + 96000)
    h.run(extra)
    st = h.state()
    e_next = st["phi"] + N - st["acc"]               # where X, posted now, is applied: the next block's start
    if not (6000 - 64 < e_next % 6000 < 6000 - 2):
        continue
    o = np.concatenate([h.step([(P_LEN, 6)])[0], h.run(3, )[0]])
    found.append(float(np.max(np.abs(np.diff(o)))))
    if len(found) >= 4:
        break
check(f"X 1 bar -> 1/16 landing within 64 frames of the 1/16 out-point ({len(found)} cases): the cut crossfade is declicked, "
      f"largest step {max(found):.4f} (bound {STEP:.4f}; v1 0.42)", len(found) == 4 and max(found) <= STEP, found)
# caught again inside the release fade, transport stopped: the catch's crossfade and the wrap at its first frame overlap
for playing in (1, 0):
    h = HostRun(sig=sine)
    h.playing = playing
    h.until(243200)
    h.step([(P_FINGER, 1), (P_LEN, 4), (P_HPF, 0)])
    h.run(300)
    o = np.concatenate([h.step([(P_LEN, 3), (P_HPF, 500), (P_FINGER, 0)])[0], h.step([(P_FINGER, 1), (P_LEN, 4), (P_HPF, 0)])[0],
                        h.run(10)[0]])
    stp = float(np.max(np.abs(np.diff(o))))
    check(f"{'playing' if playing else 'stopped'}: released and caught again within the release fade: largest step {stp:.4f} "
          f"(bound {STEP:.4f}; v1 0.146 stopped)", stp <= STEP, stp)

# a touch-down whose X / Y the audio task drains a block after the 0x15 (an earlier gesture left 1/16 as the length)
h = HostRun()
h.until(51200)
h.step([(P_FINGER, 1), (P_LEN, 6), (P_HPF, 0)])
h.step([(P_LEN, 3), (P_HPF, 500), (P_FINGER, 0)])
h.until(243200)
h.step([(P_FINGER, 1)])
s1 = h.state()
h.step([(P_LEN, 0), (P_HPF, 300)])
s2 = h.state()
check("touch-down split from its X / Y: the catch waits for them one block, then loops 4 bars from the 4-bar line (within half a tick), HPF 30 %",
      s1["pend"] == 1 and s1["engaged"] == 0 and s2["engaged"] == 1 and s2["len_idx"] == 0 and abs(s2["yt"] - 0.3) < 1e-6
      and min(s2["in_idx"] % 384000, -s2["in_idx"] % 384000) <= 12.5, (s1["pend"], s2["len_idx"], s2["in_idx"]))
h = HostRun()
h.until(243200)
h.step([(P_FINGER, 1)])
h.step()
check("...and if they never come, it catches a block late with the last length and no HPF", h.state()["engaged"] == 1 and h.state()["len_idx"] == 2)

# Hold toggled with the finger down, its rest posts (X 1/2, Y 500) drained a block after the 0x1a
for split in (False, True):
    h = HostRun()
    h.until(243200)
    h.step([(P_FINGER, 1), (P_LEN, 2), (P_HPF, 0)])
    h.run(10)
    if split:
        h.step([(P_HOLD, 1)])
        h.step([(P_LEN, 3), (P_HPF, 500)])
    else:
        h.step([(P_HOLD, 1), (P_LEN, 3), (P_HPF, 500)])
    h.run(3)
    st = h.state()
    check(f"Hold on with its rest posts {'a drain late' if split else 'in the same drain'}: still 1 bar, HPF open",
          st["len_idx"] == 2 and st["yt"] == 0.0 and st["hold"] == 1 and st["engaged"] == 1, (st["len_idx"], st["yt"]))
h.step([(P_LEN, 3)])
h.run(2)
check("...but a real X = 1/2 a drain after that is applied (only the drain right after a Hold toggle is suspect)", h.state()["len_idx"] == 3)

# the tempo moves while a 1-bar loop is latched (a knob nudge, a clock that follows MIDI): the loop stays on the grid
for bpm2 in (120.1, 121.0, 117.0):
    h = HostRun()
    h.until(243200)
    h.step([(P_FINGER, 1), (P_LEN, 2), (P_HPF, 0)])
    h.step([(P_HOLD, 1), (P_LEN, 3), (P_HPF, 500)])
    h.step([(P_FINGER, 0)])
    h.until(288000 + 96000)
    h.set_bpm(bpm2)
    S0 = h.S
    l, r = h.run(int(60 * FS) // N)
    k = dec(l, r)
    t = np.arange(S0, S0 + len(k))
    ok_ = (k >= IN) & (k < IN + 96000)
    starts, counts = np.unique(t[ok_] - (k[ok_] - IN), return_counts=True)   # when each pass's in-point frame plays
    heads = starts[counts > 10000]
    errs = [((x - h.S0) / h.fpt() + h.t0 + 1920) % 3840 - 1920 for x in heads]   # ticks off the nearest bar line
    worst = max(abs(e) for e in errs[1:]) * h.fpt()
    check(f"120 -> {bpm2} BPM while latched, 1 minute: {len(heads)} passes, each from the bar line within {worst:.1f} frames "
          f"(lock tolerance 2 ticks = {2 * h.fpt():.1f}; v1 drifted by up to 479 ms)", len(heads) >= 28 and worst <= 2 * h.fpt() + 1, (len(heads), worst))

# Loop In with the input not on Out 1: nothing is added while the first pass is live, then the loop fades in


def pads440(kk):
    x = (0.3 * np.sin(2 * np.pi * 440.0 * np.asarray(kk) / FS)).astype(np.float32)
    return x, x


def srcsig(kk):
    x = (0.25 * np.sin(2 * np.pi * 97.0 * np.asarray(kk) / FS)).astype(np.float32)
    return x, x


h = HostRun(sig=pads440, src=1, mon=0)
h.until(243200, srcsig)
S0 = h.S
o = [h.step([(P_FINGER, 1), (P_LEN, 2), (P_HPF, 0)], src_sig=srcsig)[0]]
o.append(h.until(288000 + 2048, srcsig)[0])
o = np.concatenate(o)
t = np.arange(S0, S0 + len(o))
extra = o - pads440(t)[0]
pre = t < 288000
check("Loop In on top of Out 1: from the touch to the first out-point it adds nothing (v1 added the live input: a double)",
      float(np.max(np.abs(extra[pre]))) == 0.0, float(np.max(np.abs(extra[pre]))))
check("...and at the out-point the loop comes in from silence over the 64-frame crossfade (no step)",
      float(np.max(np.abs(np.diff(extra[t >= 288000 - 1])))) <= 0.25 / 64 + 0.25 * 2 * np.pi * 97 / FS + 1e-3, float(np.max(np.abs(np.diff(extra)))))

# ---- T12 Loop In: the audio input alone, read raw, in place of the monitored input (or on top)
REC = ROOT + 4 * 0x300
CODE = 3_000_000                                  # the input's frames carry k + CODE, Out 1's pads a tone
TAP = 5_000_000                                   # what Resam leaves in input bus 0 (last block's Out 1): anything else


def tone(kk):
    x = (0.3 * np.sin(2 * np.pi * 440.0 * kk / FS)).astype(np.float32)
    return x, x


def inp(kk):
    return enc(kk + CODE)


def loop_in_rig(rec_input=0, rec_mon=0, mon_out=0, jacks=(1, 1), recorder=True, gain=1.0, rec_active=0, raw=True):
    """FX A = Loop In, the recorder's fields set by hand. As A6 found the block: the raw input at the audio object;
    input bus 0 = that input, scaled in place by Rec Gain while the recorder listens (on Rec Input's channels), or
    last block's Out 1 under Resam; Out 1 = the pads, plus the scaled input when it is monitored on Out 1."""
    rg = Rig()
    if recorder:
        for k_ in range(4):
            rg.e.w32(ROOT + k_ * 0x300 + 8, ROOT + (k_ + 1) * 0x300)
        rg.e.w32(ENG + 0xFC00, ROOT)
        rg.e.w32(REC, 0x080D07AC)
        rg.e.uc.mem_write(REC + 0x58, bytes([rec_input, rec_mon, rec_active]))
        rg.e.uc.mem_write(REC + 0x64, struct.pack("<f", gain))
        rg.e.w32(REC + 0x68, mon_out)
        rg.e.uc.mem_write(REC + 0x280, bytes(jacks))
    j1, j2 = jacks
    listen = recorder and (rec_mon == 0 or (rec_mon == 1 and rec_active))
    jack_ok = (j1 and j2) if rec_input == 0 else j1 if rec_input == 1 else j2 if rec_input == 2 else 0
    mon = bool(listen and jack_ok and mon_out == 0)
    g_ = gain if recorder and rec_input != 3 else 1.0

    def src(kk):                                  # the input as Rec Input takes it, a jack that is not AUDIO silent
        il, ir = inp(kk)
        sl = (ir if rec_input == 2 else il) * (g_ if (j2 if rec_input == 2 else j1) else 0.0)
        sr = (il if rec_input == 1 else ir) * (g_ if (j1 if rec_input == 1 else j2) else 0.0)
        return sl.astype(np.float32), sr.astype(np.float32)

    def bus0(kk):
        il, ir = inp(kk)
        if recorder and rec_input == 3:
            return enc(kk + TAP)
        if listen and jack_ok:                    # scaled in place on Rec Input's channels (L+R both, Left L, Right R)
            return (il * g_ if rec_input != 2 else il), (ir * g_ if rec_input != 1 else ir)
        return il, ir

    def out1(kk):
        tl, tr = tone(kk)
        if not mon:
            return tl, tr
        sl, sr = src(kk)
        return tl + sl, tr + sr
    rg.inp = bus0
    rg.raw = inp if raw else None
    rg.post(0x18, 4)
    rg.until(243200, out1)
    touch(rg, 2, 0)
    S = rg.S
    l, r = rg.until(288000 + 2 * 96000, out1)
    rg.case = (S, src, out1, mon)
    return rg, l, r


def loop_in_ok(rg, l, r, atol=2e-5):
    """the live pass: Out 1 untouched; then Out 1 = the pads + the input's loop (the monitored input replaced)"""
    S, src, out1, mon = rg.case
    t = np.arange(S, S + len(l))
    lv = t < 288000
    o1l, o1r = out1(t)
    m = (t >= 288000 + 64) & ((t - 288000) % 96000 >= 64)
    sl, sr = src(IN + (t - 288000) % 96000)
    tl, tr = tone(t)
    return (np.array_equal(l[lv], o1l[lv]) and np.array_equal(r[lv], o1r[lv])
            and np.allclose(l[m], tl[m] + sl[m], atol=atol) and np.allclose(r[m], tr[m] + sr[m], atol=atol))


rg, l, r = loop_in_rig()
rl, rr = rg.ring(288000)
check("Loop In, Rec Mon On / Mon Output Out1 / L+R, both jacks AUDIO: Out 1 = pads + the input's loop (the live input replaced)",
      rg.dsp()["engaged"] == 1 and rg.case[3] and loop_in_ok(rg, l, r))
check("...the ring holds the input alone: not a trace of the pads", (dec(rl[IN:IN + 96000] / 8192.0, rr[IN:IN + 96000] / 8192.0) == np.arange(IN, IN + 96000) + CODE).all())
for label, kw in (("Mon Output Out2", dict(mon_out=1)), ("Rec Mon Off", dict(rec_mon=2)), ("Rec Mon Auto, nothing recording", dict(rec_mon=1)),
                  ("no recorder found", dict(recorder=False))):
    rg, l, r = loop_in_rig(**kw)
    check(f"Loop In, {label}: the input is not on Out 1, so nothing is added while live, then the loop goes on top of the pads",
          not rg.case[3] and loop_in_ok(rg, l, r))
rg, l, r = loop_in_rig(jacks=(1, 0))
check("Loop In, L+R with jack 2 not AUDIO (GATE / CV / CLK): not monitored, so on top; the loop's right side is silent, not the control voltage",
      not rg.case[3] and loop_in_ok(rg, l, r) and np.abs(r - tone(np.arange(rg.case[0], rg.S))[1]).max() < 1e-6)
rg, l, r = loop_in_rig(rec_input=1, jacks=(1, 0))
check("Loop In, Rec Input Left (jack 1 AUDIO): the loop is the left input on both sides, in place of the monitored one", rg.case[3] and loop_in_ok(rg, l, r))
rg, l, r = loop_in_rig(rec_input=2, jacks=(0, 1))
check("Loop In, Rec Input Right: the right input on both sides", rg.case[3] and loop_in_ok(rg, l, r))
rg, l, r = loop_in_rig(rec_input=3)
rl, rr = rg.ring(288000)
check("Loop In, Rec Input Resam (input bus 0 = last block's Out 1): the loop is still the input itself, on top; v1 looped Out 1 and doubled it",
      not rg.case[3] and loop_in_ok(rg, l, r) and (dec(rl[IN:IN + 96000] / 8192.0, rr[IN:IN + 96000] / 8192.0) == np.arange(IN, IN + 96000) + CODE).all())
rg, l, r = loop_in_rig(gain=0.5)
check("Loop In, Rec Gain 0.5, Rec Mon On: the monitored input is x 0.5, and so is the loop: it replaces it exactly", rg.case[3] and loop_in_ok(rg, l, r, atol=7e-5))
rl_on = rg.ring(288000)[0][IN:IN + 96000].copy()
rg, l, r = loop_in_rig(gain=0.5, rec_mon=1)
rl_off = rg.ring(288000)[0][IN:IN + 96000]
check("Loop In, Rec Gain 0.5, Rec Mon Auto with the recorder not listening (bus 0 left unscaled): the ring is at the same level, x 0.5",
      not rg.case[3] and loop_in_ok(rg, l, r, atol=7e-5) and np.array_equal(rl_on, rl_off))
rg, l, r = loop_in_rig(raw=False)
check("Loop In, no raw input found at the audio object: input bus 0 instead (v1's source), still the input loop", rg.case[3] and loop_in_ok(rg, l, r))
rg, l, r = loop_in_rig(raw=False, rec_input=3)
check("...and under Resam then, silent: Out 1 untouched rather than doubled", np.array_equal(l, tone(np.arange(rg.case[0], rg.S))[0]))
# the recorder's fields as the recorder's own block reads them (FUN_0806201C): their widths
rec_code = stock[0x0806201C - 0x08040000:0x08062900 - 0x08040000]
widths = {}
for i_ in md.disasm(rec_code, 0x0806201C):
    if i_.mnemonic in ("ldrb.w", "ldrb", "ldr", "ldr.w") and "[r4, #" in i_.op_str:
        off = int(i_.op_str.split("#")[1].rstrip("]"), 16)
        widths.setdefault(off, set()).add(i_.mnemonic.split(".")[0])
check("the recorder reads Rec Input +0x58, Rec Mon +0x59, Rec Active +0x5a, take +0x48, the jacks +0x280 / +0x281 as bytes and Mon Output +0x68 as a word",
      all(widths.get(o) == {"ldrb"} for o in (0x58, 0x59, 0x5A, 0x48, 0x280, 0x281)) and widths.get(0x68) == {"ldr"},
      {hex(o): widths.get(o) for o in (0x58, 0x59, 0x5A, 0x48, 0x68, 0x280, 0x281)})

# ---- T13 the transport
rg = Rig()
rg.playing = 0
rg.post(0x18, 3)
rg.until(243200)
touch(rg, 4, 0)
S = rg.S
l, r = rg.run(400)
k = dec(l, r)
t = np.arange(S, S + len(k))
m = ((t - S) % 24000 >= 64) & (t - S >= 256)
check("stopped: a touch loops the last 1/4 at once (from 24,000 frames back), faded in from live over the 256-frame engage",
      (k[m] == (S - 24000) + (t[m] - S) % 24000).all() and rg.dsp()["in_idx"] == S - 24000)
rg = Rig()
rg.playing = 0
rg.post(0x18, 3)
rg.until(243200)
touch(rg, 2, 0)
rg.tick_shift = -rg.ticks(rg.S + N) + rg.tick_shift   # PLAY: the position restarts at 0 with the new anchor
rg.block(play_change=1)
d1 = rg.dsp()
rg.run(1)
d2 = rg.dsp()
check("touch on the PLAY block (duck_block saw it stopped): the catch waits one block for a clean clock, then engages",
      d1["pend"] == 1 and d1["engaged"] == 0 and d2["pend"] == 0 and d2["engaged"] == 1, (d1["pend"], d1["engaged"], d2["engaged"]))
rg = engaged_rig()
rg.until(300032)
rg.block(play_change=0)
l, r = rg.run(300)
k = dec(l, r)
t = np.arange(rg.S - len(k), rg.S)
m = (t - 288000) % 96000 >= 64
check("STOP while looping: it keeps looping", rg.dsp()["engaged"] == 1 and (k[m] == IN + (t[m] - 288000) % 96000).all())
rg.tick_shift = -rg.ticks(rg.S + N) + rg.tick_shift   # PLAY: the count restarts at 0, at the next block's first frame
Pz = rg.S + N
rg.block(play_change=1)
l, r = rg.run(int(3 * 96000 / N))
k = dec(l, r)
t = np.arange(rg.S - len(k), rg.S)
ok_ = (k >= IN) & (k < IN + 96000)
starts, counts = np.unique(t[ok_] - (k[ok_] - IN), return_counts=True)
heads = starts[counts > 24000]
errs = [((x - Pz) + 48000) % 96000 - 48000 for x in heads]
check(f"...then PLAY (the count restarts {(Pz - 288000) % 96000} frames past an old bar line): from the next pass on, the bar loops "
      f"from the new bar lines (off by {[int(e) for e in errs]} frames)", len(heads) >= 3 and all(abs(e) <= 2 * 25 + 1 for e in errs[1:]), errs)
rig, S, t, in_tick, L, l, r = catch(120.0, 243200, 2, 1, tick_shift=-20000)
check("lead-in (negative ticks: -10,272): the in-point is the bar line below, -11,520 (floored, not truncated)",
      t == -10272 and in_tick == -11520 and rig.dsp()["in_idx"] == S - 1248 * 25, (t, in_tick, rig.dsp()["in_idx"], S))

# ---- T14 the ring's limits: a held loop is never overwritten; stale history is never replayed
hl = HostLooper()
blk = lambda kk: enc(kk)  # noqa: E731
frozen_at, ok = None, True
for b in range(int(60 * FS) // N):
    kk = np.arange(b * N, (b + 1) * N)
    xl, xr = enc(kk)
    ev = [(P_FINGER, 1), (P_LEN, 2), (P_HPF, 0)] if b == 1900 else [(P_HOLD, 1), (P_LEN, 3), (P_HPF, 500)] if b == 1901 else []
    if b == 1902:
        ev = [(P_FINGER, 0)]
    l, r = hl.block(xl, xr, events=ev, phase=(b * N // 25) % 15360)
    st = hl.state()
    if frozen_at is None and st["frozen"]:
        frozen_at = b * N
    if b > 1950 and b % 50 == 0:
        kd = dec(l, r)
        tt = kk
        mm = (tt - 288000) % 96000 >= 64
        ok &= (kd[mm] == IN + (tt[mm] - 288000) % 96000).all()
st = hl.state()
check(f"host, a 1-bar loop held 60 s: the ring stops at {(frozen_at or 0) / FS:.2f} s, when the in-point (4.00 s) is 16 s less 512 frames old, and the loop plays on unchanged",
      frozen_at is not None and abs(frozen_at - (IN + 768000 - 512)) <= N and ok and st["valid"] == 0, (frozen_at, ok))
rg = Rig()
rg.e.w32(REP1 + 0x38, 48000)                      # a 2 s ring (96,000 frames), to reach its end in a short run
rg.post(0x18, 3)
rg.until(100096)
touch(rg, 4, 0)                                   # 1/4 = 24,000 frames
rg.run(1)
hold_button(rg, 1)
lift(rg, hold=True)
rg.run(1)
froze = None
for _ in range(1200):
    rg.run(1)
    if froze is None and rg.dsp()["frozen"]:
        froze = rg.S
in0, S0 = rg.dsp()["in_idx"], rg.S
l, r = rg.run(50)
k = dec(l, r)
t = np.arange(S0, S0 + len(k))
P0 = 96000                                        # the quarter of tick 4003 starts at tick 3840
m = (t - P0) % 24000 >= 64
check("Unicorn, 2 s ring: the held quarter freezes the ring before its in-point would be overwritten, and still plays the same audio",
      froze is not None and (k[m] == P0 + (t[m] - P0) % 24000).all(), (froze, int(np.sum(k[m] != P0 + (t[m] - P0) % 24000))))
hold_button(rg, 0)
rg.run(3)
resume = rg.S - 3 * N + 256 - N                   # writing starts again once the release has faded (frames from here on)
touch(rg, 3, 0)                                   # 1/2 bar: 48,000 frames back is older than the ring's history
Sx = rg.S
l, r = rg.run(700)
k = dec(l, r)
d = rg.dsp()
check("re-touch right after: the in-point moves forward by whole loops into true history; nothing older is ever played",
      d["engaged"] == 1 and (k[k >= 0] >= rg.S - 700 * N - 2 * N).all() and (k >= 0).mean() > 0.9, (int(k[k >= 0].min()), Sx))

# ---- T15 cost: instructions per 128-frame block in the whole FX A + FX B container (Unicorn's count, not cycles)


def cost(rg, blocks=1):
    n_ = [0]
    h = rg.e.uc.hook_add(UC_HOOK_CODE, lambda *_: n_.__setitem__(0, n_[0] + 1))
    rg.run(blocks)
    rg.e.uc.hook_del(h)
    return n_[0] // blocks


base = Rig()
base.run(2)
c_stock = cost(base, 2)
rg = Rig()
rg.post(0x18, 3)
rg.run(2)
c_idle = cost(rg, 2)
rg = engaged_rig()
rg.until(300032)
c_loop = cost(rg, 2)
rg.post(P_HPF, 600)
rg.run(2)
rg.until(384000 - 64)
c_xf = cost(rg, 1)
print(f"     instructions per block: stock Repeater idle {c_stock:,}; Looper idle {c_idle:,}, looping {c_loop:,}, wrap + crossfade + HPF {c_xf:,}")
check(f"the Looper's worst block stays under 40,000 instructions ({c_xf:,}; the block is 1.28 M cycles at 480 MHz)", max(c_idle, c_loop, c_xf) < 40_000)

# ---- T16 Repeater mode is stock, sample for sample: A5's measured cases on the stock image and on this one
SCRIPT = [(12800, [(0x1C, 1), (0x13, 1000), (P_FINGER, 1)]), (25600, [(P_FINGER, 0)]),          # early touch, 1/8, wet 100 %
          (36000 + 160, [(P_FINGER, 1)]), (38400, [(0x1C, 2)]), (49920, [(P_FINGER, 0)]),     # late touch, X while repeating, release
          (60032, [(P_FINGER, 1)]), (62080, [(P_HOLD, 1), (0x1C, 2), (0x13, 500)]),           # touch -> Hold on -> release -> Hold off
          (64000, [(P_FINGER, 0)]), (76800, [(P_HOLD, 0), (0x1C, 2), (0x13, 500)]),
          (90112, [(P_HOLD, 1), (0x1C, 2), (0x13, 500)]), (110080, [(P_HOLD, 0), (0x1C, 2), (0x13, 500)]),   # Hold without a touch
          (120064, [(0x13, 250), (P_FINGER, 1)]), (130048, [(P_FINGER, 0)])]                  # Y below 50 %


def script(rg, at0=0):
    out_l, out_r = [], []
    for at, msgs in SCRIPT:
        l, r = rg.until(at0 + at)
        out_l.append(l)
        out_r.append(r)
        for pid, v in msgs:
            rg.post(pid, v)
    l, r = rg.run(200)
    return np.concatenate(out_l + [l]), np.concatenate(out_r + [r])


ref = script(Rig(image=STOCK))
ours = script(Rig())
check("Repeater on this image (FX A index 0): Out 1 identical to stock's, sample for sample, over A5's cases",
      np.array_equal(ref[0], ours[0]) and np.array_equal(ref[1], ours[1]) and not np.array_equal(ref[0], enc(np.arange(len(ref[0])))[0]))
# ...and after the Looper has had the Repeater's buffers: past 16 s, so the whole ring has been int16 (NaN as floats)
AT = 832000
sr_ = Rig(image=STOCK)
sr_.until(AT - 16 * N)
sr_.post(0x18, 0)
ref = script(sr_, AT)
rg = Rig()
rg.post(0x18, 3)
rg.until(243200)
touch(rg, 2, 400)
rg.until(400000)
lift(rg)
rg.until(AT - 16 * N)
check("(the Looper's ring has wrapped: every float of both buffers has held int16 pairs)", rg.dsp()["valid"] == 768000 and rg.dsp()["w"] < AT - 768000)
rg.post(0x18, 0)
ours = script(rg, AT)
check("...and the same after a Looper session on the same Repeater (a loop played and released, the ring wrapped): identical",
      np.array_equal(ref[0], ours[0]) and np.array_equal(ref[1], ours[1]))

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
