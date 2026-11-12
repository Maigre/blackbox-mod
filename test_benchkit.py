"""The bench kit (src/kit.c in bank 1, src/kit_b2.c in bank 2; dev builds only) under Unicorn on the patched image.

The kit's job mailbox at block + 0xC000: the computer writes {magic KIT1, index, epoch, six arguments, seq last}, the
task the index names runs the job at its hook (the screen task in the app pass's knob scan, the audio task in
usbdev_poll, the card task in b2load_thunk), and writes {done, result, four values}. Here: the hooks are where they
should be; the gate answers nothing without bank 2, without the block, without the magic, twice for one seq, for
another task, and refuses an index with no job and a stale epoch; mutants of every branch of the gate are caught;
every job reaches stock's own handler with the message stock's own input gives it; a release build has none of it.
NOT checked here: the unit (the kit reaches it only at Thomas's next install), the task timing, the real controller.
"""
import os
import struct
import subprocess
import sys
import tempfile

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from unicorn import UC_HOOK_CODE

from emu import BASE, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
ELF = "out/cave.elf"
STOCK = "firmware/BLACKBOX-3.1.9.bin"
B2, CAVE_LO = 0x08100000, 0x080F1E78
BLOCK = 0xC0000000                       # master.c's boot-time block, here
MB = BLOCK + 0xC000                      # the mailbox: cw_bank's 4 KB, its last 0x100 bytes
PMEM, PCHECK, PKEY = 0x38800F70, 0x38800F74, 0x5052534D
BOOTS_AT, BOOTS = 0x38800FE0, 7          # fault.c's boot count: the epoch
B2CHK = 0x2405FFD0 + 0x23                # cpu.c's cpu_state.b2chk: 1 paired, 2 not
KIT1, MBX1 = 0x3154494B, 0x3158424D
APP, GUI_MS, HW = 0x24020088, 0x2402EEE0, 0x24000170
SCREEN, AUDIO, CARD = 0, 1, 2
UNSET = 0x5A5A5A5A                       # done / result before a request: "not answered" leaves it
fails = 0
img, stock = open(IMAGE, "rb").read(), open(STOCK, "rb").read()
cs = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
sym = {l.split()[2]: int(l.split()[0], 16) for l in subprocess.run(["arm-none-eabi-nm", ELF], capture_output=True, text=True,
                                                                   check=True).stdout.splitlines() if len(l.split()) == 3}
sizes = {l.split()[3]: int(l.split()[1], 16) for l in subprocess.run(["arm-none-eabi-nm", "-S", ELF], capture_output=True,
                                                                     text=True, check=True).stdout.splitlines() if len(l.split()) == 4}


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def code_at(addr, n, data=img):
    return list(cs.disasm(data[addr - BASE:addr - BASE + n], addr))


def branch(at, data=img):
    i = code_at(at, 4, data)[0]
    return i.mnemonic, int(i.op_str.lstrip("#"), 16)


class Kit:
    """the patched image on an emulator, with the block, the boot count and bank 2 as a running dev unit has them"""

    def __init__(self, live=True, paired=False):
        e = self.e = Emu(IMAGE, ELF)
        for a, n in ((0x38800000, 0x1000), (0x58020000, 0x5000), (0xC0000000, 0x200000)):
            e.uc.mem_map(a, n)
        b2len = len(open("out/bank2.bin", "rb").read())   # flash past the payload reads erased, as on the unit
        e.uc.mem_write(B2 + b2len, b"\xff" * (0xE0000 - b2len))
        e.w32(PMEM, BLOCK)
        e.w32(PCHECK, BLOCK ^ PKEY)
        e.w32(BOOTS_AT, BOOTS)
        e.w32(GUI_MS, 123456)
        e.uc.mem_write(APP + 0x8CA4, b"\x02")              # the Pads screen
        if not live:
            e.uc.mem_write(B2CHK, b"\x02")                 # the pairing said: not this build's payload
        if paired:                                         # the pairing said yes already: a mutant written into bank 2
            e.uc.mem_write(B2CHK, b"\x01")                 # below would otherwise fail its sum, and prove nothing
        self.ran = []                                      # entries into kit_run (bank 2)
        e.uc.hook_add(UC_HOOK_CODE, lambda *a: self.ran.append(e.arg(0)), begin=sym["kit_run"] & ~1, end=sym["kit_run"] & ~1)
        e.stub(0x08040724)                                 # the knob scan's ADC: no knob turned
        self.msgs = []                                     # what reached the app's handler FUN_080a1718
        e.stub(0x080A1718, lambda: self.msgs.append(tuple(struct.unpack("<6I", bytes(e.uc.mem_read(e.arg(1), 24))))))
        self.store = {}
        e.stub(0x08093E9C, lambda: e.uc.reg_write(66, self.store.get((e.arg(0), e.arg(1)), -77) & 0xFFFFFFFF))
        e.stub(0x0808E2D0, lambda: e.uc.reg_write(66, -3840 & 0xFFFFFFFF if e.arg(0) == 0x1C9 else 0))
        e.stub(0x0808E304, lambda: e.uc.reg_write(66, 3840 if e.arg(0) == 0x1C9 else 7))
        e.uc.mem_write(MB, bytes(0x100))

    def ask(self, index, *args, epoch=BOOTS, magic=KIT1, seq=None):
        e = self.e
        seq = (e.r32(MB + 0x28) + 1) & 0xFFFFFFFF if seq is None else seq
        e.w32(MB + 0x28, UNSET)
        e.w32(MB + 0x2C, UNSET)
        e.uc.mem_write(MB + 0x30, bytes(16))
        a = list(args) + [0] * (6 - len(args))
        e.uc.mem_write(MB, struct.pack("<IHHI6i", magic, index, 0, epoch, *a))
        e.w32(MB + 0x24, seq)
        self.seq = seq
        self.ran.clear()
        self.msgs.clear()
        return seq

    def run(self, task):
        if task == SCREEN:
            self.e.call("kit_scan", HW, count=5_000_000)
        else:
            self.e.call("kit_poll", task, count=5_000_000)

    def reply(self):
        e = self.e
        done, result, r0, r1, r2, r3, state, version = struct.unpack("<IiiiiiII", bytes(e.uc.mem_read(MB + 0x28, 0x20)))
        return dict(answered=done == self.seq, unset=done == UNSET and result == UNSET, result=result, r=(r0, r1, r2, r3),
                    state=state, version=version)

    def job(self, task, index, *args, **kw):
        self.ask(index, *args, **kw)
        self.run(task)
        return self.reply()


# ====================================================================================================== 1. where it lives
check("the app pass's knob scan at 0x080a2cd6: stock 'bl 0x08040724' is now 'bl kit_scan' (the screen task's hook)",
      branch(0x080A2CD6, stock) == ("bl", 0x08040724) and branch(0x080A2CD6) == ("bl", sym["kit_scan"] & ~1))
ks = code_at(sym["kit_scan"] & ~1, sizes["kit_scan"])
check("kit_scan: stock's knob scan first, then the gate for the screen task (r0 = 0), so a knob event it posts is "
      "drained by stock's loop right after",
      (ks[1].mnemonic, ks[1].op_str) == ("bl", "#0x8040724") and any(i.mnemonic in ("b.w", "bl") and
      int(i.op_str.lstrip("#"), 16) == sym["kit_poll"] & ~1 for i in ks) and any(i.op_str == "r0, #0" for i in ks),
      [(i.mnemonic, i.op_str) for i in ks])
th = code_at(sym["b2load_thunk"] & ~1, 24)
th_s = [(i.mnemonic, i.op_str) for i in th]
check("the card task: b2load_thunk (the card loop's three file command steps) runs the loader, then the gate with r0 = 2, "
      "then stock's step with its own r0 back",
      th_s[1] == ("bl", f"#{sym['b2_load_poll'] & ~1:#x}") and th_s[2] == ("movs", "r0, #2")
      and th_s[3] == ("bl", f"#{sym['kit_poll'] & ~1:#x}") and th_s[4][0].startswith("pop"), th_s)
up = code_at(sym["usbdev_poll"] & ~1, sizes["usbdev_poll"])
calls = [k for k, i in enumerate(up) if i.mnemonic in ("bl", "b.w") and int(i.op_str.lstrip("#"), 16) == sym["kit_poll"] & ~1]
check("the audio task: usbdev_poll calls the gate once, with r0 = 1, after serving the controller",
      len(calls) == 1 and any(i.op_str == "r0, #1" for i in up[calls[0] - 3:calls[0]]), [(up[k].address, up[k].op_str) for k in calls])
in_b2 = sorted(n for n, a in sym.items() if n.startswith("kit_") and B2 <= a < B2 + 0xE0000)
in_cave = sorted(n for n, a in sym.items() if n.startswith("kit_") and CAVE_LO <= a < B2)
check(f"bank 1 holds the gate and the hook only ({', '.join(in_cave)}); the dispatcher and every job are bank 2's "
      f"({', '.join(in_b2)})", in_cave == ["kit_poll", "kit_scan"] and {"kit_run", "kit_gate", "kit_row"} <= set(in_b2),
      (in_cave, in_b2))
check("the usbdev.c mailbox of 37.3.1d - 37.4.1d is gone from the cave", "usbdev_mailbox_scan" not in sym and "MBOX_IDS" not in sym)

# ====================================================================================================== 2. the gate
k = Kit()
r = k.job(SCREEN, 0x00)
check(f"info (job 0), from the screen task: answered, result 0, r0 = the table (version 1, 0x60 jobs), r1 = the screen "
      f"(2, Pads), r2 = the GUI's ms clock, r3 = the boot count ({r})",
      r["answered"] and r["result"] == 0 and r["r"] == (0x10060, 2, 123456, BOOTS) and r["version"] == 0x10060
      and k.ran == [SCREEN], r)


def unanswered(k, r):
    return r["unset"]


def gate_suite(k):
    """every refusal the gate makes, on one emulator; (name, held) per case"""
    out = []
    r = k.job(SCREEN, 0x00)
    out.append(("a good request is answered, by its job", r["answered"] and r["result"] == 0 and r["r"][0] == 0x10060))
    k.ask(0x00, magic=0)
    k.run(SCREEN)
    out.append(("no magic: nothing written", unanswered(k, k.reply())))
    k.ask(0x00, magic=KIT1 + 1)
    k.run(SCREEN)
    out.append(("another magic: nothing written", unanswered(k, k.reply())))
    k.ask(0x00, seq=UNSET)                                 # seq == done: served already
    k.run(SCREEN)
    out.append(("a seq already served: nothing written", k.e.r32(MB + 0x2C) & 0xFFFFFFFF == UNSET))
    for task in (AUDIO, CARD):
        k.ask(0x00)
        k.run(task)
        out.append((f"a screen job is left alone by task {task}", unanswered(k, k.reply())))
    r = k.job(SCREEN, 0x60)
    out.append(("index 0x60 (past the table): -1", r["answered"] and r["result"] == -1))
    r = k.job(SCREEN, 0xFFFF)
    out.append(("index 0xffff: -1", r["answered"] and r["result"] == -1))
    r = k.job(SCREEN, 0x1F)
    out.append(("index 0x1f (no job): -1", r["answered"] and r["result"] == -1))
    k.ask(0x60)
    k.run(AUDIO)
    out.append(("an index with no job is the screen task's to answer, not the audio task's", unanswered(k, k.reply())))
    r = k.job(SCREEN, 0x00, epoch=BOOTS - 1)
    out.append(("a request from the boot before: -2, not run", r["answered"] and r["result"] == -2 and r["r"] != (0x10060, 2, 123456, BOOTS)))
    r = k.job(SCREEN, 0x00, epoch=BOOTS + 1)
    out.append(("an epoch ahead of the boot count: -2", r["answered"] and r["result"] == -2))
    k.e.w32(PCHECK, 0)                                     # the block's check word does not vouch for it
    k.ask(0x00)
    k.run(SCREEN)
    out.append(("no SDRAM block: nothing written, bank 2 never entered", unanswered(k, k.reply()) and not k.ran))
    k.e.w32(PCHECK, BLOCK ^ PKEY)
    k.e.uc.mem_write(B2CHK, b"\x02")
    k.ask(0x00)
    k.run(SCREEN)
    out.append(("bank 2 not this build's: nothing written, bank 2 never entered", unanswered(k, k.reply()) and not k.ran))
    k.e.uc.mem_write(B2CHK, b"\x01")
    r = k.job(SCREEN, 0x00)
    out.append(("...and answered again once it is", r["answered"] and r["result"] == 0))
    k.store[(PAD12, 0x1C9)] = 11
    for task in (AUDIO, CARD):
        x = mbx(k, 1, 1, 2, 0x1C9, 11, task=task)
        out.append((f"MBX1 is left alone by task {task}", not x["done"] and not x["msgs"]))
    x = mbx(k, 1, 1, 2, 0x1C9, 11)
    out.append(("MBX1 set is served by the screen task, the value back", x["done"] and x["result"] == 0 and x["back"] == 11
                and x["msgs"] == [(0x6E, 0, 0x12, 0x1C9, 11, 0)]))
    x = mbx(k, 1, 1, 2, 0x1C9, 11, seq=k.e.r32(MB + 0x14))
    out.append(("MBX1: a served seq is not run again", not x["msgs"] and x["result"] == UNSET))
    k.e.w32(MB + 0x1C, UNSET)
    x = mbx(k, 1, 4, 2, 0x1C9, 11)
    out.append(("MBX1 refused: its reason, no value back", x["done"] and x["result"] == -2 and x["back"] == UNSET))
    return out


PAD12 = APP + 0x1840 + 1 * 0xF0 + 2 * 0x30


def mbx(k, op, row, col, pid, v, task=SCREEN, seq=None, magic=MBX1):
    e = k.e
    seq = (e.r32(MB + 0x14) + 1) & 0xFFFFFFFF if seq is None else seq
    e.uc.mem_write(MB, struct.pack("<IIBBBBHHi", magic, 0, op, row, col, 0, pid, 0, v))
    e.w32(MB + 0x18, UNSET)
    e.w32(MB + 4, seq)
    k.msgs.clear()
    k.run(task)
    done, res, back = struct.unpack("<Iii", bytes(e.uc.mem_read(MB + 0x14, 12)))
    return dict(done=done == seq, result=res, back=back, msgs=list(k.msgs))


GATE_FNS = ("kit_poll", "kit_gate", "kit_run")
suite = gate_suite(k)
for name, held in suite:
    check("gate: " + name, held)
k2 = Kit(live=False)
r = k2.job(SCREEN, 0x00)
check("gate: an emulator whose bank 2 never paired answers nothing and never enters bank 2", r["unset"] and not k2.ran)

# --- mutants: every conditional branch of the gate (kit_poll in bank 1, kit_gate and kit_run in bank 2) made always
# taken and never taken, every register compare made to compare a register with itself, every IT block's condition
# inverted. Each must make at least one case of gate_suite fail.


def b16(at, tgt):
    return struct.pack("<H", 0xE000 | (((tgt - (at + 4)) >> 1) & 0x7FF))


sys.path.insert(0, "patches")
from thumb import bw  # noqa: E402


def mutants(fn):
    a, n = sym[fn] & ~1, sizes[fn]
    data = img if a < B2 else open("out/bank2.bin", "rb").read()
    base = BASE if a < B2 else B2
    out = []
    for i in cs.disasm(data[a - base:a - base + n], a):
        m, ops = i.mnemonic, i.op_str
        if m in ("cbz", "cbnz") or (m.startswith("b") and m.rstrip(".nw") in (
                "beq", "bne", "bhs", "blo", "bhi", "bls", "bge", "blt", "bgt", "ble", "bcs", "bcc", "bmi", "bpl")):
            tgt = int(ops.split("#")[-1], 16)
            never = b"\x00\xbf" * (i.size // 2)
            always = b16(i.address, tgt) if i.size == 2 else bw(i.address, tgt)
            out += [(f"{fn}+{i.address - a:#x} {m} never taken", i.address, never),
                    (f"{fn}+{i.address - a:#x} {m} always taken", i.address, always)]
        elif m == "cmp" and i.size == 2 and "#" not in ops:
            ra = ops.split(",")[0].strip()
            rn = int(ra[1:])
            out.append((f"{fn}+{i.address - a:#x} cmp {ra}, {ra}", i.address, struct.pack("<H", 0x4280 | rn << 3 | rn)))
        elif m == "cmp.w" and "#" not in ops and "lsr" in ops:
            ra = int(ops.split(",")[0].strip()[1:])
            out.append((f"{fn}+{i.address - a:#x} cmp.w {ops} -> cmp {ops.split(',')[0]}, itself", i.address,
                        struct.pack("<H", 0x4280 | ra << 3 | ra) + b"\x00\xbf"))
        elif m.startswith("it"):
            h = struct.unpack("<H", i.bytes)[0]
            fc, mask = (h >> 4) & 0xF, h & 0xF
            low = mask & -mask
            flipped = (mask ^ ((~(low | (low - 1))) & 0xF)) & 0xF
            out.append((f"{fn}+{i.address - a:#x} {m} {ops} inverted", i.address, struct.pack("<H", 0xBF00 | (fc ^ 1) << 4 | flipped)))
    return out


killed, survived, total = 0, [], 0
for fn in GATE_FNS:
    for name, at, new in mutants(fn):
        total += 1
        km = Kit(paired=True)
        km.e.uc.mem_write(at, new)
        try:
            res = gate_suite(km)
            ok = all(h for _, h in res)
        except Exception:                                  # a mutant that runs off: caught too
            ok = False
        if ok:
            survived.append(name)
        else:
            killed += 1
# Step 1 has no job that spans passes, so kit_run's "a job answers later" branch (R_LATER) is never taken by a correct
# build either: that one mutant is equivalent until the knob job exists.
LATER_ONLY = [n for n in survived if n.startswith("kit_run+") and "beq never taken" in n]
check(f"gate mutants: {killed} of {total} caught by the cases above (every conditional branch of {', '.join(GATE_FNS)} "
      f"made always and never taken, each register compare made trivially equal, each IT condition inverted)"
      + (f"; {LATER_ONLY[0]} (R_LATER) equivalent until a job spans passes" if LATER_ONLY else ""),
      total >= 20 and len(survived) - len(LATER_ONLY) == 0 and len(LATER_ONLY) <= 1, survived)

# ====================================================================================================== 3. the 13 pad rows
# MBX1 (bench/bbusb.py set / get of 37.3.1d - 37.4.1d, and bench/autogate.py's BB_BENCH copy): the same offsets and
# results as usbdev.c's mailbox had, served by the screen task only. test_clipwin.py 12c runs it through the real app
# handler and SetCellParam; here the handler is a recorder and the store a dict.
k = Kit()
k.store[(PAD12, 0x1C9)] = -645
x = mbx(k, 1, 1, 2, 0x1C9, -645)
check(f"MBX1 set (Slip -645 on row 1 col 2): served, result 0, the app gets the 0x6e message a turned knob's view sends "
      f"({x['msgs']}), the store's value read back", x["done"] and x["result"] == 0 and x["back"] == -645
      and x["msgs"] == [(0x6E, 0, 0x12, 0x1C9, -645 & 0xFFFFFFFF, 0)], x)
x = mbx(k, 2, 1, 2, 0x1C9, 0)
check("MBX1 get: the store's value, nothing posted", x["done"] and x["result"] == 0 and x["back"] == -645 and not x["msgs"], x)
bad = {name: mbx(k, *a) for name, a in (("op 3", (3, 1, 2, 0x1C9, 0)), ("row 4", (1, 4, 2, 0x1C9, 0)),
                                         ("Length 0x90", (1, 1, 2, 0x90, 1)), ("Slip 3841", (1, 1, 2, 0x1C9, 3841)),
                                         ("Pad Mode 4", (1, 1, 2, 0x8B, 4)))}
check(f"MBX1 refusals, each served once with its reason, nothing posted: { {n: v['result'] for n, v in bad.items()} }",
      {n: v["result"] for n, v in bad.items()} == {"op 3": -1, "row 4": -2, "Length 0x90": -3, "Slip 3841": -4, "Pad Mode 4": -4}
      and all(v["done"] and not v["msgs"] for v in bad.values()), bad)
x = [mbx(k, 1, 1, 2, 0x1C9, 5, task=t) for t in (AUDIO, CARD)]
check("MBX1 is the screen task's only: the audio and card tasks leave it", not any(v["done"] or v["msgs"] for v in x), x)
x = mbx(k, 1, 1, 2, 0x1C9, 7, seq=k.e.r32(MB + 0x14))
check("MBX1: a seq already served is not applied again", not x["msgs"] and x["result"] == UNSET, x)

k.store[(PAD12, 0x1CA)] = 3
r = k.job(SCREEN, 0x01, 1, 2, 0x1CA, 3)
check("KIT1 row set (job 1: Loop Len 1/4 on row 1 col 2): the same 0x6e message, r0 the store's value after",
      r["answered"] and r["result"] == 0 and r["r"][0] == 3 and k.msgs == [(0x6E, 0, 0x12, 0x1CA, 3, 0)], (r, k.msgs))
r = k.job(SCREEN, 0x02, 1, 2, 0x1CA)
check("KIT1 row get (job 2): r0 the store's value, nothing posted", r["answered"] and r["result"] == 0 and r["r"][0] == 3 and not k.msgs, r)
r = k.job(SCREEN, 0x01, 1, 2, 0x1C9, 9999)
check("KIT1 row set out of range: -3 (a bad argument), r0 = MBX1's reason (-4), nothing posted",
      r["answered"] and r["result"] == -3 and r["r"][0] == -4 and not k.msgs, r)

# ====================================================================================================== 9. the release build
# A release (RELEASE=1: PUBLIC_BUILD) compiles none of the kit: kit.c and kit_b2.c are empty, usbdev.c and
# b2load_thunk.S do not call it, build.sh leaves kit_b2 out of bank 2 (so the release's bank 2, and the bank 1 that
# holds its sum, are byte for byte what they were), patches/cpu.py places no hook.
with tempfile.TemporaryDirectory() as tmp:
    flags = ["-mcpu=cortex-m7", "-mthumb", "-mfloat-abi=hard", "-mfpu=fpv5-d16", "-Os", "-ffreestanding", "-nostdlib",
             "-fno-builtin", "-DB2_ID=0x1", "-DB2LOAD_WRITE=1", "-DPUBLIC_BUILD=1", "-c"]
    objs = {}
    for src in ("src/kit.c", "src/kit_b2.c", "src/usbdev.c", "src/b2load_thunk.S", "src/master.c"):
        o = os.path.join(tmp, os.path.basename(src) + ".o")
        subprocess.run(["arm-none-eabi-gcc", *flags, "-o", o, src], check=True)
        objs[src] = subprocess.run(["arm-none-eabi-nm", o], capture_output=True, text=True, check=True).stdout
    kit_syms = {src: [l for l in out.splitlines() if "kit" in l.split()[-1]] for src, out in objs.items()}
    check("PUBLIC_BUILD: kit.c and kit_b2.c compile to nothing; usbdev.c, b2load_thunk.S and master.c neither define "
          "nor call anything of the kit's", not any(objs["src/kit.c"].split()) and not any(objs["src/kit_b2.c"].split())
          and not any(kit_syms.values()), kit_syms)
bsh = open("build.sh").read()
check("build.sh: kit_b2 goes up only in a dev build (RELEASE=1 empties KIT_SRCS), into the id's hash and the link both",
      'KIT_SRCS="kit_b2"' in bsh and '[ "${RELEASE:-0}" = 1 ] && KIT_SRCS=""' in bsh
      and 'for b in $KIT_SRCS; do B2_SRC="$B2_SRC src/$b.c"; done' in bsh and "for b in $KIT_SRCS; do B2_PAT=" in bsh)
src_cpu = open("patches/cpu.py").read()
check("patches/cpu.py places the knob-scan hook only when the image has kit_scan", 'if "kit_scan" in sym:' in src_cpu)

print(f"{'ALL PASS' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
