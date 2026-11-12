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
        self.msg_app = []
        e.stub(0x080A1718, lambda: (self.msgs.append(tuple(struct.unpack("<6I", bytes(e.uc.mem_read(e.arg(1), 24))))),
                                    self.msg_app.append(e.arg(0))))
        self.store = {}
        e.stub(0x08093E9C, lambda: e.uc.reg_write(66, self.store.get((e.arg(0), e.arg(1)), -77) & 0xFFFFFFFF))
        e.stub(0x0808E2D0, lambda: e.uc.reg_write(66, -3840 & 0xFFFFFFFF if e.arg(0) == 0x1C9 else 0))
        e.stub(0x0808E304, lambda: e.uc.reg_write(66, 3840 if e.arg(0) == 0x1C9 else 7))
        e.uc.mem_write(MB, bytes(0x100))
        e.uc.mem_write(HW + 0x18E1, b"\x01")             # the knobs post (the GUI task's entry sets it)

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
    r = k.job(SCREEN, 0x03, 0, 5, 2, 0)                  # a knob job of two events: one this pass, one the next
    s1 = k.reply()
    k.run(SCREEN)
    r2 = k.reply()
    out.append(("a job spanning passes answers when it ends, not before", not r["answered"] and r["state"] == 1
                and r2["answered"] and r2["result"] == 0 and r2["r"][0] == 2 and r2["state"] == 0))
    r = k.job(SCREEN, 0x03, 0, 5, 1, 0)
    out.append(("...one that ends in its first pass answers in it", r["answered"] and r["result"] == 0 and r["r"][0] == 1))
    w0 = k.e.r32(HW + 0x1274)
    k.job(SCREEN, 0x03, 0, 5, 2, 0)
    k.run(AUDIO)
    k.run(CARD)
    r = k.reply()
    k.run(SCREEN)
    out.append(("...and only the screen task steps it", not r["answered"] and k.e.r32(HW + 0x1274) == w0 + 2 and k.reply()["answered"]))
    # while it runs the box is the screen task's: a request meanwhile is answered -8 (busy, r0 the job's index) by the
    # screen task, whatever task it names, and never run; the job's own answer never goes back over the newer one
    # (review 12/11: a knob's late done made the card task run a put's chunk a second time)
    k.e.uc.mem_write(0x24009AB0 + 10 * 0x18 + 8, struct.pack("<H", 0xF7))   # PLAY's press code, so a run would show
    g0, w0 = k.e.r32(0x240021BC + 0x604), k.e.r32(HW + 0x1274)
    s_knob = k.ask(0x03, 0, 5, 4, 0)                       # four events, one a pass
    k.run(SCREEN)
    k.run(SCREEN)
    r = k.reply()
    out.append(("...its own request is not taken again while it runs", not r["answered"] and r["state"] == 1
                and k.e.r32(HW + 0x1274) == w0 + 2))
    s_btn = k.ask(0x20, 10, 0, seq=s_knob + 1)              # PLAY, the audio task's, asked meanwhile
    k.run(AUDIO)
    r_left = k.reply()
    k.run(SCREEN)                                          # the third event, then the request: busy
    r_busy = k.reply()
    k.run(SCREEN)                                          # the fourth and last: the knob ends, unanswered
    k.run(AUDIO)
    out.append(("a request while a job spans passes: left by its own task, answered -8 (r0 3) by the screen task, never run",
                r_left["unset"] and r_busy["answered"] and r_busy["result"] == -8 and r_busy["r"][0] == 3
                and k.e.r32(0x240021BC + 0x604) == g0))
    out.append(("...and the job's end does not write its answer over the newer one: done stays the newer seq, the box is "
                "free (state 0), nothing runs twice", k.e.r32(MB + 0x28) == s_btn and k.reply()["state"] == 0
                and k.e.r32(HW + 0x1274) == w0 + 4 and k.e.r32(0x240021BC + 0x604) == g0))
    s = k.ask(0x03, 0, 5, 5, 0)
    k.run(SCREEN)
    r = k.job(SCREEN, 0x08, seq=s + 1)                     # a cancel: this pass steps the knob once more, then ends it
    k.run(SCREEN)
    out.append(("a cancel (job 8) ends it: answered 0, r0 its index (3), r1 the events posted (2); nothing posted after, "
                "the knob's own answer never written", r["answered"] and r["result"] == 0 and r["r"][:2] == (3, 2)
                and k.e.r32(HW + 0x1274) == w0 + 6 and k.e.r32(MB + 0x28) == s + 1 and k.reply()["state"] == 0))
    r = k.job(SCREEN, 0x08)
    out.append(("...with nothing running: answered 0, r0 0", r["answered"] and r["result"] == 0 and r["r"][:2] == (0, 0)))
    r = k.job(SCREEN, 0x00)
    out.append(("...and the next request runs", r["answered"] and r["result"] == 0 and r["r"][0] == 0x10060))
    k.ask(0x03, 0, 5, 3, 0)
    k.run(SCREEN)
    k.e.w32(BOOTS_AT, BOOTS + 1)                           # the unit reset under it: SDRAM kept the box
    k.run(SCREEN)
    r = k.reply()
    k.e.w32(BOOTS_AT, BOOTS)
    k.e.w32(MB + 0x48, BOOTS)                              # (back to this rig's boot for the cases after)
    out.append(("a job running when the unit reset does not go on: its request is stale (-2)", r["answered"] and r["result"] == -2))
    closes = []                                            # a file the card task left open, idle 10 s: only that task closes it
    k.e.stub(0x08086D76, lambda: closes.append(1), value=0)
    k.e.uc.mem_write(MB + 0x74, struct.pack("<IIB", BOOTS, 123456 - 10001, 1))
    k.run(SCREEN)
    k.run(AUDIO)
    c0 = len(closes)
    k.run(CARD)
    out.append(("the card upkeep (an idle file closed) is the card task's only", c0 == 0 and len(closes) == 1 and k.e.r8(MB + 0x7C) == 0))
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
check(f"gate mutants: {killed} of {total} caught by the cases above (every conditional branch of {', '.join(GATE_FNS)} "
      f"made always and never taken, each register compare made trivially equal, each IT condition inverted)",
      total >= 20 and not survived, survived)

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

# ====================================================================================================== 4. knobs
# The kit's event goes into the knob ring right after stock's scan (kit_scan); stock's own drain in the app pass
# (0x080a2cda .. 0x080a2d36) is run here for real and hands it to FUN_080a1718 (case 0x32) exactly as a turned knob's.
from unicorn.arm_const import UC_ARM_REG_R4, UC_ARM_REG_SP  # noqa: E402
from emu import STACK  # noqa: E402


def knob_pass(k):
    """the app pass from its knob scan to the end of the knob ring's drain: the hook, the kit, stock's drain"""
    e = k.e
    e.uc.reg_write(UC_ARM_REG_R4, APP)
    e.uc.reg_write(UC_ARM_REG_SP, STACK)
    k.msgs.clear()
    k.msg_app.clear()
    e.uc.emu_start(0x080A2CD4 | 1, 0x080A2D38, count=5_000_000)
    return [(m[0] & 0xFFFF, m[2] & 0xFFFF, m[3], m[4] - (1 << 32) if m[4] >> 31 else m[4], m[5]) for m in k.msgs]


k = Kit()
k.ask(0x03, 2, -7, 3, 1)                                   # TR, -7 counts, 3 events, one pass between
passes = [knob_pass(k) for _ in range(6)]
r = k.reply()
check(f"knob (job 3: TR, -7 counts, 3 events, 1 pass between): stock's drain hands FUN_080a1718(app) the knob message "
      f"{{0x32, 0, code 2, -7, 0}} in passes 1, 3 and 5 and nothing in between ({passes})",
      passes == [[(0x32, 0, 2, -7, 0)], [], [(0x32, 0, 2, -7, 0)], [], [(0x32, 0, 2, -7, 0)], []]
      and set(k.msg_app) <= {APP}, passes)
check("...answered after the last event, r0 = 3 events, the ring's read index caught up with its write index (3)",
      r["answered"] and r["result"] == 0 and r["r"][0] == 3 and k.e.r32(HW + 0x1270) == 3 == k.e.r32(HW + 0x1274), r)
ent = bytes(k.e.uc.mem_read(HW + 0xC70 + 2 * 0x18, 0x18))
check("...the ring entry as stock's scan writes it (FUN_08040724): +0 u16 0x32, +8 u16 0, +0xc the code, +0x10 the "
      "counts, +0x14 0", struct.unpack_from("<H", ent, 0)[0] == 0x32 and struct.unpack_from("<H", ent, 8)[0] == 0
      and struct.unpack_from("<iiI", ent, 0xC) == (2, -7, 0), ent.hex())
k.e.uc.mem_write(HW + 0x18E1, b"\x00")
r = k.job(SCREEN, 0x03, 0, 1, 1, 0)
k.e.uc.mem_write(HW + 0x18E1, b"\x01")
bad = [k.job(SCREEN, 0x03, *a)["result"] for a in ((4, 1, 1, 0), (0, 0, 1, 0), (0, 40000, 1, 0), (0, 1, 0, 0), (0, 1, 1, -1))]
check(f"knob refusals: -4 (r0 1) while stock has the knobs off, nothing posted; -3 for a knob past 3, 0 counts, "
      f"+-40 000, no events, a negative gap ({bad})", r["result"] == -4 and r["r"][0] == 1 and k.e.r32(HW + 0x1274) == 3
      and bad == [-3] * 5, (r, bad))
k.e.w32(HW + 0x1270, 10)
k.e.w32(HW + 0x1274, 10 + 64)                              # full: the drain has not run
r1 = k.job(SCREEN, 0x03, 1, 1, 1, 0)
k.e.w32(HW + 0x1270, 10 + 64)
k.run(SCREEN)
r2 = k.reply()
check("...a full ring: the event waits for the next pass instead of overwriting one",
      not r1["answered"] and r2["answered"] and r2["r"][0] == 1 and k.e.r32(HW + 0x1274) == 10 + 65, (r1, r2))
w = k.e.r32(HW + 0x1274)
k.ask(0x03, 1, 4, 3, 0)
k.run(SCREEN)                                              # the first event
k.e.uc.mem_write(HW + 0x18E1, b"\x00")                    # stock turns the knobs off before the next
k.run(SCREEN)
r = k.reply()
k.e.uc.mem_write(HW + 0x18E1, b"\x01")
k.run(SCREEN)
check("...stock turning the knobs off while a knob job runs ends it at its next event: -4, r0 the events posted (1), "
      "nothing posted after", r["answered"] and r["result"] == -4 and r["r"][0] == 1 and r["state"] == 0
      and k.e.r32(HW + 0x1274) == w + 1, (r, k.e.r32(HW + 0x1274) - w))

# ====================================================================================================== 5. buttons
# The kit's press is held against stock's own scan FUN_080437d4 run for real on the same table, with the button's pin
# read low (FUN_0807b348 stubbed): both rings get the same bytes. Then stock's two consumers, run for real: the GUI's
# FUN_080a2e60 (TOOLS -> screen 0x25, as on the unit 12/11) and the audio block's ring loop in FUN_0804cb1c
# (0x0804ccc4 .. 0x0804ce3a: PLAY -> FUN_08051eb8, STOP -> FUN_08052010, REC -> FUN_080524cc, on the clock).
PANEL, TABLE = 0x240021BC, 0x24009AB0
CODES = [(0xF9, 0, 0)] * 8 + [(0xF4, 0xF5, 0), (0xF6, 0, 0), (0xF7, 0, 0), (7, 0, 8), (0xC, 0, 0)]   # read off the unit, 12/11


def panel(k):
    e = k.e
    e.uc.mem_write(PANEL, bytes(0xC60))
    e.uc.mem_write(PANEL + 0xC14, b"\x01")                 # row k is index k (the unit's)
    for i, (p_, r_, h_) in enumerate(CODES):
        e.uc.mem_write(TABLE + i * 0x18, struct.pack("<IIHHHBxIB3x", 0x58020000 + 0x400 * (i % 4), 1 << i, p_, r_, h_, 1, 0, 0))


def rings(k):
    e = k.e
    return (bytes(e.uc.mem_read(PANEL, 0x18 * 4)), bytes(e.uc.mem_read(PANEL + 0x608, 0x18 * 4)),
            e.r32(PANEL + 0x604), e.r32(PANEL + 0xC0C))


def stock_scan(k, low, ticks=1000):
    e = k.e
    e.w32(PANEL + 0xC10, ticks)
    e.stub(0x0807B348, lambda: e.uc.reg_write(66, 0 if e.arg(1) == 1 << low else 1))
    e.call(0x080437D4, PANEL, count=5_000_000)


k = Kit()
for a in (0x0807B394, 0x080436F8):                         # anything the scan's LED half writes: stubbed
    k.e.stub(a)
same, posted = [], []
for i in range(13):
    panel(k)
    stock_scan(k, i)
    ref = rings(k)
    panel(k)
    r = k.job(AUDIO, 0x20, i, 0)
    same.append(rings(k) == ref and ref[2] == 1)
    posted.append(r["answered"] and r["result"] == 0 and r["r"][0] == CODES[i][0])
check(f"button press (job 0x20, each of the 13): both panel rings get the bytes stock's scan writes for that button "
      f"held down, and the press code back ({sum(same)} of 13 the same)", all(same) and all(posted), (same, posted))
panel(k)
stock_scan(k, 8)
stock_scan(k, 99, ticks=1100)                              # REC let go 100 ticks later
ref = rings(k)
panel(k)
k.job(AUDIO, 0x20, 8, 0)
r = k.job(AUDIO, 0x20, 8, 1)
check("REC press then release (0xf4, 0xf5): the same two entries in both rings as stock's scan writes",
      rings(k) == ref and ref[2] == 2 and r["r"][0] == 0xF5, (rings(k)[2:], ref[2:]))
panel(k)
stock_scan(k, 11)
stock_scan(k, 11, ticks=1700)                              # BACK still held 700 ticks later: the hold
ref = rings(k)
panel(k)
k.job(AUDIO, 0x20, 11, 0)
r = k.job(AUDIO, 0x20, 11, 2)
check("BACK press then hold (7, 8): as stock's scan writes them", rings(k) == ref and ref[2] == 2 and r["r"][0] == 8,
      (rings(k)[2:], ref[2:]))
panel(k)
bad = [k.job(AUDIO, 0x20, *a) for a in ((13, 0), (0, 3), (0, 1), (9, 2))]
k.e.w32(PANEL + 0x600, 5)
k.e.w32(PANEL + 0x604, 5 + 64)
full = k.job(AUDIO, 0x20, 10, 0)
check(f"button refusals: -3 for button 13, action 3, a release PADS does not have, a hold STOP does not have (r0 0); "
      f"-4 (r0 1) with a ring full, nothing written ({[b_['result'] for b_ in bad]}, {full['result']})",
      [b_["result"] for b_ in bad] == [-3] * 4 and bad[2]["r"][0] == 0 and full["result"] == -4 and full["r"][0] == 1
      and k.e.r32(PANEL + 0x604) == 69 and k.e.r32(PANEL + 0xC0C) == 0, (bad, full))
r = k.job(SCREEN, 0x20, 10, 0)
check("a button job is the audio task's: the screen task leaves it", r["unset"], r)

# the consumers
k = Kit()
panel(k)
k.e.uc.mem_write(APP + 0x8CC3, b"\x00")
screens = []
k.e.stub(0x0809EAEC, lambda: screens.append(k.e.arg(1)))
k.job(AUDIO, 0x20, 7, 0)                                   # TOOLS
buf = 0x24078000
k.e.call(0x08043A84, PANEL, buf)                           # the GUI's pop (ring G) ...
gmsg = bytes(k.e.uc.mem_read(buf, 0x18))
k.e.call(0x080A2E60, APP, buf, count=5_000_000)            # ... and its handler
check(f"TOOLS: the GUI's pop gives {{0xf9, index 7}}, and stock's handler FUN_080a2e60 sets screen 0x25, TOOLS ({screens})",
      struct.unpack_from("<H", gmsg)[0] == 0xF9 and struct.unpack_from("<i", gmsg, 0xC)[0] == 7 and screens == [0x25],
      (gmsg.hex(), screens))
ENGINE, CLOCK = 0x2400A9C0, 0x24070000
k.e.w32(ENGINE + 0x9A74, CLOCK)
clock = []
for a, name in ((0x08052010, "stop"), (0x08051EB8, "play"), (0x080524CC, "rec"), (0x080436F8, None)):
    k.e.stub(a, (lambda name=name: clock.append((name, k.e.arg(0), k.e.arg(1)))) if name else None)
for a in (0x080525D0, 0x080525D8):
    k.e.stub(a, value=0)


def audio_block(k):
    e = k.e
    e.uc.reg_write(UC_ARM_REG_R4, ENGINE + 0x9000)
    e.uc.reg_write(UC_ARM_REG_SP, STACK)
    e.uc.reg_write(UC_ARM_REG_R5, STACK + 0x30)
    e.uc.emu_start(0x0804CCC4 | 1, 0x0804CE3A, count=5_000_000)


from unicorn.arm_const import UC_ARM_REG_R5  # noqa: E402
panel(k)
for i, w in ((10, 0), (9, 0), (8, 0), (8, 1)):            # PLAY, STOP, REC press, REC release
    k.job(AUDIO, 0x20, i, w)
clock.clear()
audio_block(k)
check(f"PLAY, STOP, REC down, REC up through the audio block's own ring loop: FUN_08051eb8(clock), FUN_08052010(clock), "
      f"FUN_080524cc(clock, 1), FUN_080524cc(clock, 0) ({clock})",
      [(n, c) for n, c, _ in clock] == [("play", CLOCK), ("stop", CLOCK), ("rec", CLOCK), ("rec", CLOCK)]
      and [x for n, _, x in clock if n == "rec"] == [1, 0] and k.e.r32(PANEL + 0xC08) == 4, clock)

# ====================================================================================================== 6. touch
# The kit's contact against stock's own tracker FUN_0808b050 run on a real touch buffer: the same hit test, the same
# widget calls with the same points, in the same order. The hit test and the widget lookup are stubs over one fake
# widget (id 0x77, the left half of the screen); its three virtuals record.
GUIOBJ, WID, VT = 0x24070000, 0x24071000, 0x24071100
FNS = {"down": 0x24071200, "move": 0x24071210, "up": 0x24071220}


def touch_rig(k):
    e = k.e
    e.uc.mem_write(GUIOBJ, bytes(0x400))
    e.w32(0x24002E6C, GUIOBJ)
    e.uc.mem_write(WID, bytes(0x40))
    e.w32(WID, VT)
    e.w32(WID + 0x28, 0x77)
    k.calls = []
    for n, (name, a) in enumerate(FNS.items()):
        e.w32(VT + 0x10 + 4 * n, a | 1)
        e.uc.mem_write(a, b"\x70\x47")                     # bx lr
        e.uc.hook_add(UC_HOOK_CODE, lambda *x, name=name: k.calls.append(
            (name, e.arg(0), struct.unpack("<ii", bytes(e.uc.mem_read(e.arg(1), 8))), e.arg(2) & 0xFF)), begin=a, end=a)

    def hit():
        x, y = struct.unpack("<ii", bytes(e.uc.mem_read(e.arg(1), 8)))
        k.calls.append(("hit", e.arg(0) - GUIOBJ, (x, y)))
        if x < 160:
            e.w32(e.arg(2), WID)
        e.uc.reg_write(66, int(x < 160))

    def find():
        k.calls.append(("find", e.arg(0) - GUIOBJ, e.arg(1)))
        if e.arg(1) == 0x77:
            e.w32(e.arg(2), WID)
        e.uc.reg_write(66, int(e.arg(1) == 0x77))
    e.stub(0x080AB5F2, hit)
    e.stub(0x080AECDA, find)


def tracker(k, contacts):
    buf = 0x24072000
    k.e.uc.mem_write(buf, struct.pack("<H2x", len(contacts)) + b"".join(struct.pack("<hhB3xI", x, y, 15, 0) for x, y in contacts))
    k.e.call(0x0808B050, GUIOBJ, buf, count=5_000_000)


ref = Kit()
touch_rig(ref)
for c in ([(100, 50)], [(120, 70)], [(130, 90)], []):
    tracker(ref, c)
k = Kit()
touch_rig(k)
rs = [k.job(SCREEN, 0x04, 0, 100, 50), k.job(SCREEN, 0x04, 1, 120, 70), k.job(SCREEN, 0x04, 1, 130, 90),
      k.job(SCREEN, 0x04, 2)]
check(f"touch down, move, move, up (job 4) makes the calls stock's tracker makes for a finger: the hit test at the "
      f"point, the widget's +0x10 / +0x14 / +0x18 with the same points and id ({len(k.calls)} calls: "
      f"{[c[0] for c in k.calls]})", k.calls == ref.calls and len(ref.calls) == 8 and all(r_["result"] == 0 and r_["r"][0] == 0x77 for r_ in rs),
      (k.calls, ref.calls))
check("...and stock's tracker state is not touched (gui + 0x214 count 0): the panel's real 'no contact' cannot lift it",
      k.e.r16(GUIOBJ + 0x214) == 0 and ref.e.r16(GUIOBJ + 0x214) == 0)
k.calls.clear()
r = k.job(SCREEN, 0x04, 0, 200, 50)
r2 = k.job(SCREEN, 0x04, 2)
check("a touch on no widget: the hit test only, r0 0; its up looks the widget up and calls nothing",
      r["r"][0] == 0 and r2["r"][0] == 0 and [c[0] for c in k.calls] == ["hit", "find"], k.calls)
bad = [k.job(SCREEN, 0x04, *a)["result"] for a in ((1, 10, 10), (2,), (0, 320, 0), (0, 0, 240), (0, -1, 0), (3, 0, 0))]
k.job(SCREEN, 0x04, 0, 10, 10)
bad.append(k.job(SCREEN, 0x04, 0, 10, 10)["result"])
k.job(SCREEN, 0x04, 2)
check(f"touch refusals: -7 a move or an up with no contact down, a second down; -3 off the 320 x 240 screen or action 3 "
      f"({bad})", bad == [-7, -7, -3, -3, -3, -3, -7], bad)
k.calls.clear()
k.ask(0x05, 40, 60, 3)                                     # tap, held 3 passes
seen = []
for _ in range(5):
    k.run(SCREEN)
    seen.append((k.reply()["answered"], [c[0] for c in k.calls]))
    k.calls.clear()
check(f"tap (job 5, held 3 passes): down in its pass, up three passes later, answered then with the widget's id ({seen})",
      [x[1] for x in seen] == [["hit", "down"], [], [], ["find", "up"], []] and [x[0] for x in seen] == [False, False, False, True, True]
      and k.reply()["r"][0] == 0x77, seen)
k.job(SCREEN, 0x04, 0, 100, 50)                            # job 4's contact down
k.calls.clear()
r = k.job(SCREEN, 0x05, 40, 60, 3)
during = list(k.calls)
k.job(SCREEN, 0x04, 2)
check(f"a tap while job 4's contact is down: -7, no hit test, no widget call; that contact still lifts where it went down "
      f"({r['result']}, {during}, {k.calls})", r["result"] == -7 and not during and r["state"] == 0
      and [c[:3] for c in k.calls] == [("find", 0x280, 0x77), ("up", WID, (100, 50))], (r, during, k.calls))

# ====================================================================================================== 7. a restart
# The card task's job 0x4f: answered, the box's two cache lines written out, then SYSRESETREQ (AIRCR 0x05fa0004) - only
# while stock is idle on the card and nothing plays or records. Reached here through b2load_thunk itself (the card
# loop's file command step, stubbed, runs after it).
from unicorn import UC_HOOK_MEM_WRITE  # noqa: E402

k = Kit()
CMDS = 0x2401F508
RCLOCK = 0xC0100000                                        # the clock object: in SDRAM here (it is 0x12900 B)
k.e.w32(ENGINE + 0x9A74, RCLOCK)
k.e.uc.mem_write(RCLOCK, bytes(0x40))
k.e.uc.mem_write(RCLOCK + 0x128D4, b"\x00")
k.e.w32(CMDS + 0x390, 0x24078100)
k.e.uc.mem_write(0x24078100, b"\x00")
idle = [1]
k.e.stub(0x0807125C, lambda: k.e.uc.reg_write(66, idle[0]))
k.e.stub(0x08092F5C)                                       # stock's file command step, after the thunk
k.e.stub(sym["b2_load_poll"] & ~1)                         # the card loader has had its look this boot
resets, cleaned = [], []


order = []


def on_write(uc, kind, a, size, v, _):
    if a == 0xE000ED0C:
        resets.append(v & 0xFFFFFFFF)
        order.append("reset")
        uc.emu_stop()
    elif a == 0xE000EF68 and v & 0xFFFFFFFF >= BLOCK:
        cleaned.append(v & 0xFFFFFFFF)
        order.append("clean")
    elif a == MB + 0x28:
        order.append("done")


k.e.uc.hook_add(UC_HOOK_MEM_WRITE, on_write, begin=0xE000E000, end=0xE000EFFF)
k.e.uc.hook_add(UC_HOOK_MEM_WRITE, on_write, begin=MB + 0x28, end=MB + 0x28)


def card_step(k):
    """the card loop's call of its file command step, through b2load_thunk (r0 the step's argument)"""
    try:
        k.e.call(sym["b2load_thunk"], 0x2400A9C0, count=5_000_000)
        return "returned"
    except AssertionError:                                 # emu_stop() on the reset: it never returns
        return "reset"


refused = {}
for why, setup, undo in ((1, lambda: k.e.uc.mem_write(RCLOCK + 0x38, b"\x01"), lambda: k.e.uc.mem_write(RCLOCK + 0x38, b"\x00")),
                         (2, lambda: k.e.uc.mem_write(RCLOCK + 0x128D4, b"\x01"), lambda: k.e.uc.mem_write(RCLOCK + 0x128D4, b"\x00")),
                         (3, lambda: k.e.w32(CMDS + 0x124, 4), lambda: k.e.w32(CMDS + 0x124, 0)),
                         (4, lambda: k.e.uc.mem_write(0x24078100, b"P"), lambda: k.e.uc.mem_write(0x24078100, b"\x00")),
                         (5, lambda: idle.__setitem__(0, 0), lambda: idle.__setitem__(0, 1))):
    setup()
    k.ask(0x4F, 0x52455354)
    refused[why] = (card_step(k), k.reply()["result"], k.reply()["r"][0])
    undo()
check(f"restart refused, no reset, with its reason in r0, while: the transport plays (1), REC is held (2), file commands "
      f"are queued (3), a preset load is pending (4), the streamer is busy (5) ({refused})",
      all(v == ("returned", -4, why) for why, v in refused.items()) and not resets, refused)
k.ask(0x4F, 0x12345678)
bad = (card_step(k), k.reply()["result"])
k.ask(0x4F, 0x52455354, epoch=BOOTS - 1)
stale = (card_step(k), k.reply()["result"])
k.ask(0x4F, 0x52455354)
k.run(SCREEN)
k.run(AUDIO)
other = k.reply()
check(f"...a wrong check word: -3; a restart asked before the last reset: -2 (it must not run twice); the screen and audio "
      f"tasks leave it ({bad}, {stale})", bad == ("returned", -3) and stale == ("returned", -2) and other["unset"] and not resets)
order.clear()
got = card_step(k)
r = k.reply()
check(f"restart with stock idle: answered (done, result 0) and the box's two cache lines written out first, then AIRCR = "
      f"0x05fa0004 (SYSRESETREQ), from the card task ({got}, {[hex(x) for x in resets]}, {[hex(x) for x in cleaned]})",
      got == "reset" and resets == [0x05FA0004] and r["answered"] and r["result"] == 0 and cleaned == [MB, MB + 0x20]
      and order == ["done", "clean", "clean", "reset"], (got, r, order))

# ====================================================================================================== 8. the card's files
# The card task's jobs 0x40 - 0x47 against a stubbed FatFs (a dict of files behind stock's ten entry points, at their
# addresses): the FIL, DIR and FILINFO in the kit's data area (block + 0x84900, a dev build's), the name at +0x200, the
# bytes through the chunk at +0x400.
DATA = BLOCK + 0x84900
D_FIL, D_DIR, D_FNO, D_NAME, D_CHUNK = DATA, DATA + 0x58, DATA + 0xB0, DATA + 0x200, DATA + 0x400
FR_OK, FR_NO_FILE, FR_NO_PATH, FR_DENIED, FR_EXIST = 0, 4, 5, 7, 8


class FakeFs:
    def __init__(self, k):
        self.k, e = k, k.e
        self.files, self.open, self.dirs, self.calls = {}, {}, {}, []
        for a, fn in ((0x08086534, self.f_open), (0x08086866, self.f_read), (0x08086A06, self.f_write),
                      (0x08086D76, self.f_close), (0x08086D96, self.f_lseek), (0x0808724A, self.f_stat),
                      (0x080870F6, self.f_opendir), (0x080871A0, self.f_readdir), (0x0808718C, self.f_closedir),
                      (0x0808748E, self.f_unlink)):
            e.stub(a, lambda fn=fn: self.k.e.uc.reg_write(66, fn() & 0xFFFFFFFF))

    def cstr(self, a):
        return bytes(self.k.e.uc.mem_read(a, 256)).split(b"\0")[0].decode()

    def a(self, n):
        return self.k.e.arg(n)

    def fil(self, fp):
        name, pos, mode = self.open[fp]
        e = self.k.e
        e.uc.mem_write(fp + 0x10, struct.pack("<Q", len(self.files[name])))
        e.uc.mem_write(fp + 0x38, struct.pack("<Q", pos))

    def f_open(self):
        fp, name, mode = self.a(0), self.cstr(self.a(1)), self.a(2)
        self.calls.append(("open", fp, self.a(1), name, mode))
        if name in self.files and mode & 4:
            return FR_EXIST
        if name not in self.files:
            if not mode & 0x1C:
                return FR_NO_FILE
            self.files[name] = bytearray()
        if mode & 8:
            self.files[name] = bytearray()
        self.open[fp] = [name, 0, mode]
        self.fil(fp)
        return FR_OK

    def f_read(self):
        fp, buf, n, got = (self.a(i) for i in range(4))
        self.calls.append(("read", fp, buf, n))
        name, pos, mode = self.open[fp]
        if not mode & 1:
            return FR_DENIED
        data = bytes(self.files[name][pos:pos + n])
        self.k.e.uc.mem_write(buf, data)
        self.k.e.w32(got, len(data))
        self.open[fp][1] += len(data)
        self.fil(fp)
        return FR_OK

    def f_write(self):
        fp, buf, n, put = (self.a(i) for i in range(4))
        self.calls.append(("write", fp, buf, n))
        name, pos, mode = self.open[fp]
        if not mode & 2:
            return FR_DENIED
        f = self.files[name]
        f[pos:pos + n] = bytes(self.k.e.uc.mem_read(buf, n))
        self.k.e.w32(put, n)
        self.open[fp][1] += n
        self.fil(fp)
        return FR_OK

    def f_lseek(self):
        fp, ofs = self.a(0), self.a(2) | self.a(3) << 32
        self.calls.append(("lseek", fp, ofs))
        name, pos, mode = self.open[fp]
        self.open[fp][1] = ofs if mode & 2 else min(ofs, len(self.files[name]))
        if mode & 2 and ofs > len(self.files[name]):
            self.files[name] += bytes(ofs - len(self.files[name]))
        self.fil(fp)
        return FR_OK

    def f_close(self):
        self.calls.append(("close", self.a(0)))
        self.open.pop(self.a(0), None)
        return FR_OK

    def f_stat(self):
        name, fno = self.cstr(self.a(0)), self.a(1)
        self.calls.append(("stat", self.a(0), name, fno))
        if name not in self.files:
            return FR_NO_FILE
        self.k.e.uc.mem_write(fno, struct.pack("<QHHB13x", len(self.files[name]), 0x5A6C, 0x8421, 0x20) + name.encode() + b"\0")
        return FR_OK

    def f_opendir(self):
        dp, path = self.a(0), self.cstr(self.a(1))
        self.calls.append(("opendir", dp, self.a(1), path))
        names = sorted(n[len(path) + 1:] if path else n for n in self.files if (n.startswith(path + "/") if path else "/" not in n))
        if path and not names:
            return FR_NO_PATH
        self.dirs[dp] = [names, 0, path]
        return FR_OK

    def f_readdir(self):
        dp, fno = self.a(0), self.a(1)
        names, i, path = self.dirs[dp]
        if i >= len(names):
            self.k.e.uc.mem_write(fno + 0x1A, b"\0")
            return FR_OK
        self.dirs[dp][1] += 1
        full = f"{path}/{names[i]}" if path else names[i]
        self.k.e.uc.mem_write(fno, struct.pack("<QHHB13x", len(self.files[full]), 0, 0, 0x20) + names[i].encode() + b"\0")
        return FR_OK

    def f_closedir(self):
        self.calls.append(("closedir", self.a(0)))
        return FR_OK

    def f_unlink(self):
        name = self.cstr(self.a(0))
        self.calls.append(("unlink", self.a(0), name))
        if name not in self.files:
            return FR_NO_FILE
        del self.files[name]
        return FR_OK


def card_kit():
    k = Kit()
    k.fs = FakeFs(k)
    k.e.uc.mem_write(0x240021A4 + 0x15, b"\x01")           # stock has found a card
    return k


def name(k, text):
    k.e.uc.mem_write(D_NAME, text.encode() + b"\0")


def chunk(k, data=None, n=None):
    if data is not None:
        k.e.uc.mem_write(D_CHUNK, data)
    return bytes(k.e.uc.mem_read(D_CHUNK, n)) if n else None


k = card_kit()
fs = k.fs
blob = bytes((i * 7 + 3) & 0xFF for i in range(5000))
name(k, "A.BIN")
r_open = k.job(CARD, 0x40, 1)
chunk(k, blob[:4096])
r_w1 = k.job(CARD, 0x42, 4096)
chunk(k, blob[4096:])
r_w2 = k.job(CARD, 0x42, 5000 - 4096)
r_close = k.job(CARD, 0x44)
check(f"put (open new, write 4 096, write 904, close): the file holds the bytes; FatFs is called with the kit's FIL, its "
      f"name and its chunk ({fs.calls[0]})", fs.files.get("A.BIN") == blob and r_open["result"] == 0 and r_w1["r"][0] == 4096
      and r_w2["r"][0] == 904 and r_close["result"] == 0 and fs.calls[0] == ("open", D_FIL, D_NAME, "A.BIN", 2 | 4)
      and fs.calls[1] == ("write", D_FIL, D_CHUNK, 4096), (r_open, r_w1, r_w2, r_close, fs.calls[:3]))
r = k.job(CARD, 0x40, 1)
check("...a second put of a new file onto it is refused by FatFs (FR_EXIST, 8): -6, r0 8, the file unchanged, none open",
      r["result"] == -6 and r["r"][0] == 8 and fs.files["A.BIN"] == blob and k.e.r8(MB + 0x7C) == 0, r)
k.job(CARD, 0x40, 2)
chunk(k, b"new!")
k.job(CARD, 0x42, 4)
k.job(CARD, 0x44)
check("...open to replace (mode 2) writes it anew", fs.files["A.BIN"] == b"new!" and fs.calls[-3][4] == 2 | 8, fs.calls[-4:])
fs.files["B.WAV"] = bytearray(blob)
name(k, "B.WAV")
r = k.job(CARD, 0x40, 0)
got, reads = b"", []
while True:
    rr = k.job(CARD, 0x41, 4096)
    reads.append(rr["r"][0])
    got += chunk(k, n=rr["r"][0]) if rr["r"][0] else b""
    if rr["r"][0] < 4096:
        break
k.job(CARD, 0x44)
check(f"get (open to read, reads of 4 096 until a short one): the file's bytes; open's r0 the size ({r['r'][0]}), the "
      f"reads {reads}", got == blob and r["r"][0] == 5000 and reads == [4096, 904], (r, reads))
k.job(CARD, 0x40, 0)
rs = k.job(CARD, 0x43, 4000)
k.job(CARD, 0x41, 8)
at = chunk(k, n=8)
k.job(CARD, 0x44)
check("seek (job 0x43) to 4 000, then read 8: those bytes; r0 the position", rs["r"][:2] == (4000, 0) and at == blob[4000:4008]
      and ("lseek", D_FIL, 4000) in fs.calls, (rs, at))
k.job(CARD, 0x40, 3)
chunk(k, b"tail")
k.job(CARD, 0x42, 4)
k.job(CARD, 0x44)
check("append (mode 3): opened always, moved to its end, written there", fs.files["B.WAV"] == blob + b"tail"
      and ("lseek", D_FIL, 5000) in fs.calls, len(fs.files["B.WAV"]))
r = k.job(CARD, 0x45)
check("stat (job 0x45): r0 r1 the size, r2 the attributes, r3 date << 16 | time", r["result"] == 0 and r["r"] == (5004, 0, 0x20, 0x5A6C8421), r)
for n_ in ("C1", "C2", "C3", "a-long-name-of-forty-characters-0123.wav"):
    fs.files[n_] = bytearray(len(n_))
fs.files["DIR/X"] = bytearray(3)


def records(n):
    raw, out, o = chunk(k, n=n), [], 0
    while o < n:
        lo, hi, attr, ln = struct.unpack_from("<IIBB", raw, o)
        out.append((raw[o + 10:o + 10 + ln].decode(), lo | hi << 32, attr))
        o += (10 + ln + 3) & ~3
    return out


name(k, "")
k.e.uc.mem_write(D_NAME, b"\0")
r1 = k.job(CARD, 0x46, 0, 3)
l1 = records(r1["r"][2])
r2 = k.job(CARD, 0x46, 3, 10)
l2 = records(r2["r"][2])
check(f"list the root (job 0x46, the empty path): 3 records and 'more', then from the 4th the other 3 and no more; each "
      f"record name, size, attributes ({l1 + l2})", r1["r"][:2] == (3, 1) and r2["r"][:2] == (3, 0)
      and [x[0] for x in l1 + l2] == sorted(n_ for n_ in fs.files if "/" not in n_)
      and dict((x[0], x[1]) for x in l1 + l2)["B.WAV"] == 5004 and fs.calls[-1][0] == "closedir", (r1, r2, l1, l2))
name(k, "DIR")
r = k.job(CARD, 0x46, 0, 10)
name(k, "NOPE")
rn = k.job(CARD, 0x46, 0, 10)
check("...a folder by its path; one that is not there: -6 (FR_NO_PATH, 5)", records(r["r"][2]) == [("X", 3, 0x20)]
      and rn["result"] == -6 and rn["r"][0] == 5, (r, rn))
name(k, "C1")
r = k.job(CARD, 0x47)
r2 = k.job(CARD, 0x47)
# the chunk's cache lines around the card's DMA (stock's SD reads and writes go by SDMMC1's IDMA straight to the
# buffer, and SDRAM is write-back cached): written out and forgotten before a transfer, and again after a read -
# written out too, since f_read also copies bytes into the buffer with the CPU, which a line taken into the cache
# during the read would hold (review 12/11; the emulator has no cache, so this checks the operations only)
cache_ops = []
k.e.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, kind, a, size, v, _: cache_ops.append(
    ({0xE000EF70: "clean+forget", 0xE000EF5C: "forget"}[a], v & 0xFFFFFFFF)), begin=0xE000EF5C, end=0xE000EF70)
k.e.uc.hook_add(UC_HOOK_CODE, lambda *a: cache_ops.append(("fatfs", 0)), begin=0x08086866, end=0x08086866)
k.e.uc.hook_add(UC_HOOK_CODE, lambda *a: cache_ops.append(("fatfs", 0)), begin=0x08086A06, end=0x08086A06)
name(k, "B.WAV")
k.job(CARD, 0x40, 0)
cache_ops.clear()
k.job(CARD, 0x41, 4096)
rd = list(cache_ops)
k.job(CARD, 0x44)
k.job(CARD, 0x40, 3)
cache_ops.clear()
k.job(CARD, 0x42, 100)
wr = list(cache_ops)
k.job(CARD, 0x44)
lines = [D_CHUNK + 32 * i for i in range(128)]
check(f"the chunk's cache lines: a 4 096-byte read writes out and forgets its 128 lines before FatFs, and again after "
      f"(not only forgets them); a 100-byte write writes out and forgets its 4 lines before, nothing after ({len(rd)}, "
      f"{len(wr)} operations)", rd == [("clean+forget", a) for a in lines] + [("fatfs", 0)] + [("clean+forget", a) for a in lines]
      and wr == [("clean+forget", a) for a in lines[:4]] + [("fatfs", 0)], (rd[:3], rd[127:131], wr))
fs.files["B.WAV"] = fs.files["B.WAV"][:5004]
check("delete (job 0x47): gone; again: -6 (FR_NO_FILE, 4)", r["result"] == 0 and "C1" not in fs.files and r2["result"] == -6
      and r2["r"][0] == 4, (r, r2))
name(k, "C2")
k.job(CARD, 0x40, 0)
st = [k.job(CARD, 0x40, 0)["result"], k.job(CARD, 0x47)["result"], k.job(CARD, 0x4F, 0x52455354)["result"]]
k.job(CARD, 0x44)
st += [k.job(CARD, 0x44)["result"], k.job(CARD, 0x41, 4)["result"], k.job(CARD, 0x42, 4)["result"], k.job(CARD, 0x43, 0)["result"]]
check(f"one file at a time: with one open, a second open, a delete and a restart are refused (-7); with none, close, "
      f"read, write and seek are ({st})", st == [-7] * 7 and "C2" in fs.files, st)
bad = [k.job(CARD, 0x41, 0)["result"], k.job(CARD, 0x40, 4)["result"], k.job(CARD, 0x46, -1, 1)["result"], k.job(CARD, 0x46, 0, 0)["result"]]
k.job(CARD, 0x40, 0)
bad += [k.job(CARD, 0x41, 4097)["result"], k.job(CARD, 0x42, 0)["result"]]
k.job(CARD, 0x44)
k.e.uc.mem_write(D_NAME, b"\0")
bad.append(k.job(CARD, 0x40, 0)["result"])
k.e.uc.mem_write(D_NAME, b"x" * 256)
bad.append(k.job(CARD, 0x45)["result"])
check(f"bad arguments (-3): 0 or 4 097 bytes, mode 4, a negative first entry, no entries, an empty name, a name with no "
      f"end in its 256 bytes ({bad})", bad == [-3] * 8, bad)
name(k, "C3")
k.job(CARD, 0x40, 0)
k.e.w32(GUI_MS, 123456 + 10001)
n0 = len(fs.calls)
k.run(CARD)
check("a file left open more than 10 s with no job is closed by the card task", fs.calls[n0:] == [("close", D_FIL)]
      and k.e.r8(MB + 0x7C) == 0, fs.calls[n0:])
k.e.w32(GUI_MS, 123456)
k.job(CARD, 0x40, 0)
k.e.w32(BOOTS_AT, BOOTS + 1)                               # a reset: SDRAM kept the box, not the volume
n0 = len(fs.calls)
k.run(CARD)
r = k.job(CARD, 0x40, 0, epoch=BOOTS + 1)
check("after a reset the file of the boot before is forgotten, not closed (its FIL meant that boot's volume); a new open "
      "works", fs.calls[n0:n0 + 1] == [("open", D_FIL, D_NAME, "C3", 1)] and r["result"] == 0, (fs.calls[n0:], r))
k.e.w32(BOOTS_AT, BOOTS)
k.job(CARD, 0x44, epoch=BOOTS)
r = [k.job(t, 0x45) for t in (SCREEN, AUDIO)]
check("a card job is the card task's: the screen and audio tasks leave it", all(x["unset"] for x in r), r)
k.e.uc.mem_write(0x240021A4 + 0x15, b"\x00")
n0 = len(fs.calls)
r = k.job(CARD, 0x45)
k.e.uc.mem_write(0x240021A4 + 0x15, b"\x01")
k.e.w32(PCHECK, BLOCK ^ 0x434F5245)                        # the block without its tail (keyed CORE): no data area
r2 = k.job(CARD, 0x45)
k.e.w32(PCHECK, BLOCK ^ PKEY)
k.e.w32(PMEM, BLOCK + 16)                                 # a block that does not start a cache line: no data area
k.e.w32(PCHECK, (BLOCK + 16) ^ PKEY)
k.e.uc.mem_write(BLOCK + 16 + 0xC000, struct.pack("<IHHI6iI", KIT1, 0x45, 0, BOOTS, 0, 0, 0, 0, 0, 0, 1))
k.e.w32(BLOCK + 16 + 0xC028, 0)
k.run(CARD)
r3 = struct.unpack("<Iii", bytes(k.e.uc.mem_read(BLOCK + 16 + 0xC028, 12)))
k.e.w32(PMEM, BLOCK)
k.e.w32(PCHECK, BLOCK ^ PKEY)
check(f"...nor with a block that does not start a cache line (the chunk's lines would not be its own): -4, r0 6 ({r3})",
      r3 == (1, -4, 6) and len(fs.calls) == n0, r3)
check("no card, or no data area (the block without its tail): -4, r0 6, FatFs not called",
      r["result"] == -4 and r["r"][0] == 6 and r2["result"] == -4 and r2["r"][0] == 6 and len(fs.calls) == n0, (r, r2, fs.calls[n0:]))
# Review 12/11: a knob job spanning passes, then a card open and a read asked meanwhile (a computer that gave up
# waiting for the knob). Before the fix the card task answered both, the knob's end wrote its own done over theirs,
# and the card task ran the read a second time. Now both are answered -8 and never run, the knob's end leaves done
# alone, and the card task takes the next request once the knob has ended.
k = card_kit()
fs = k.fs
fs.files["A.BIN"] = bytearray(b"x" * 10)
s_knob = k.ask(0x03, 0, 5, 3, 2)                           # three events, two passes apart
k.run(SCREEN)
name(k, "A.BIN")
got = []
for i, (index, args) in enumerate(((0x40, (0,)), (0x41, (4,)))):
    k.ask(index, *args, seq=s_knob + 1 + i)
    k.run(CARD)
    k.run(SCREEN)
    got.append((k.reply()["result"], k.reply()["r"][0]))
for _ in range(8):
    k.run(SCREEN)
    k.run(CARD)
calls, done_then, state = list(fs.calls), k.e.r32(MB + 0x28), k.reply()["state"]
r = k.job(CARD, 0x40, 0)
k.job(CARD, 0x44)
check(f"a card open and a read asked while a knob job runs: each answered -8 (busy, r0 3) and never run; the knob's end "
      f"leaves done at the read's seq; then the next open runs ({got}, FatFs before: {calls})",
      got == [(-8, 3), (-8, 3)] and not calls and done_then == s_knob + 2 and state == 0 and r["result"] == 0
      and [c[0] for c in fs.calls] == ["open", "close"], (got, calls, hex(done_then), r))

# ====================================================================================================== 8b. a preset load by name
# The screen task's job 6: stock's own FUN_0804290c reads the names off the list (F + 0x32c) until one is the asked-for,
# and the message the PSET screen's Load button posts goes to the app's handler: run here for real, FUN_080a1718's case
# 0x18 hands its index to LoadBank (FUN_0809e218, a recorder here) with 1 (remember it for settings.tml), then shows Pads.
PLIST, PNAMES, PSTR = 0x2401F834, 0x24078300, 0x24078400
PRESETS = ["BASICS", "Live Set 2", "DRUMS-01", "Live Set"]


def preset_rig(k):
    e = k.e
    e.w32(PLIST, len(PRESETS))
    e.w32(PLIST + 4, 16)
    e.w32(PLIST + 0xC, PNAMES)
    e.uc.mem_write(PLIST + 0x10, b"\x00")
    at = PSTR
    for i, n_ in enumerate(PRESETS):
        e.w32(PNAMES + 4 * i, at)
        e.uc.mem_write(at, n_.encode() + b"\0")
        at += 0x20
    e.w32(0x2401F508 + 0x390, 0x24078100)                  # LoadBank's "a load is pending" string: empty
    e.uc.mem_write(0x24078100, b"\x00")
    k.idle = [1]
    e.stub(0x0807125C, lambda: e.uc.reg_write(66, k.idle[0]))


k = Kit()
preset_rig(k)
del k.e.stubs[0x080A1718]                                  # the app's real handler this time
loads, screens = [], []
k.e.stub(0x0809E218, lambda: loads.append((k.e.arg(0), k.e.arg(1), k.e.arg(2))))
k.e.stub(0x0809EAEC, lambda: screens.append((k.e.arg(1), k.e.arg(2))))
name(k, "Live Set")
r = k.job(SCREEN, 0x06)
check(f"preset load (job 6, 'Live Set'): found at index 3 (not 'Live Set 2'), the Load button's message through the app's "
      f"real handler: LoadBank(app, 3, 1), then the Pads screen ({loads}, {screens})",
      r["result"] == 0 and r["r"][0] == 3 and loads == [(APP, 3, 1)] and screens == [(2, 0)], (r, loads, screens))
loads.clear()
name(k, "live set")
r1 = k.job(SCREEN, 0x06)
k.e.uc.mem_write(D_NAME, b"\0")
r2 = k.job(SCREEN, 0x06)
k.e.uc.mem_write(0x24078100, b"X")
name(k, "BASICS")
r3 = k.job(SCREEN, 0x06)
k.e.uc.mem_write(0x24078100, b"\x00")
k.idle[0] = 0
r4 = k.job(SCREEN, 0x06)
k.idle[0] = 1
r5 = k.job(CARD, 0x06)
check(f"...refused, nothing loaded: a name not in the list as it is written (-5), none (-3), a load pending (-4, r0 4), "
      f"the card's queue busy (-4, r0 5); and the card task leaves it",
      (r1["result"], r2["result"], r3["result"], r3["r"][0], r4["result"], r4["r"][0]) == (-5, -3, -4, 4, -4, 5)
      and r5["unset"] and not loads, (r1, r2, r3, r4, r5))
names_back = []
for i in range(5):
    r = k.job(SCREEN, 0x07, i)
    names_back.append(bytes(k.e.uc.mem_read(D_NAME, 32)).split(b"\0")[0].decode() if r["r"][3] else None)
check(f"presets (job 7): r0 the count, each name by its index into the name area, none past the end ({names_back})",
      names_back == PRESETS + [None] and r["r"][:3] == (4, 0, 0), (names_back, r))

# ====================================================================================================== 8c. the host client
# bench/bbkit.py's own code against an emulated unit: its peek, word and long poke land in the emulator's memory, and
# each of its 20 ms waits runs the three tasks' hooks once. So the client's requests (layout, epoch, seq last), its
# reading of the answers and its file, listing and preset loops are the ones the unit will see.
sys.path.insert(0, "bench")
import bbkit  # noqa: E402
import bbusb  # noqa: E402

k = card_kit()
preset_rig(k)
k.e.w32(PMEM, BLOCK)
host_waits = []
bbusb.word = lambda a: k.e.r32(a) & 0xFFFFFFFF
bbusb.peek = lambda a, n=4: bytes(k.e.uc.mem_read(a, n))
bbusb.poke_bytes = lambda a, data: k.e.uc.mem_write(a, bytes(data))


class _Clock:
    time = staticmethod(__import__("time").time)

    @staticmethod
    def sleep(_):
        host_waits.append(1)
        for task in (SCREEN, AUDIO, CARD):
            k.run(task)


bbkit.time = _Clock
info = bbkit.job(0x00)
check(f"bbkit.py job: info comes back through the client (r0 0x10060, the boot count {BOOTS})", info[0] == 0x10060 and info[3] == BOOTS, info)
with tempfile.TemporaryDirectory() as tmp:
    src, dst = os.path.join(tmp, "in.bin"), os.path.join(tmp, "out.bin")
    payload = bytes((i * 31 + 7) & 0xFF for i in range(9000))
    open(src, "wb").write(payload)
    n, _ = bbkit.put(src, "K/IT.BIN")
    stored = bytes(k.fs.files.get("K/IT.BIN", b""))
    try:
        bbkit.put(src, "K/IT.BIN")
        again = None
    except bbkit.KitError as e_:
        again = (e_.result, e_.r[0], str(e_))
    n2, size, _ = bbkit.get("K/IT.BIN", dst)
    back = open(dst, "rb").read()
check(f"bbkit.py put then get: 9 000 bytes in three chunks onto the card and back the same; a second put of it refused "
      f"({again})", stored == payload and back == payload and n == n2 == size == 9000 and again and again[:2] == (-6, 8)
      and "exists" in again[2], (len(stored), len(back), again))
k.fs.files.update({"B.WAV": bytearray(5004), "C3": bytearray(2)})
listing = bbkit.ls("")
check(f"bbkit.py ls: the root's names and sizes ({listing})", ("B.WAV", 5004, 0x20) in listing and ("C3", 2, 0x20) in listing
      and not any("/" in n_ for n_, *_ in listing), listing)
check(f"bbkit.py presets: the list by index ({bbkit.presets()})", bbkit.presets() == PRESETS)
k.e.stub(0x080A1718, lambda: k.msgs.append(tuple(struct.unpack("<6I", bytes(k.e.uc.mem_read(k.e.arg(1), 24))))))
k.msgs.clear()
bbkit.main(["preset", "DRUMS-01"])
check("bbkit.py preset DRUMS-01: the Load button's message with index 2", k.msgs == [(0x18, 0, 0, 2, 0, 0)], k.msgs)
k.msgs.clear()
bbkit.main(["knob", "br", "-3", "2", "1"])
check("bbkit.py knob br -3 2 1: two knob events through the ring (the client waits while the job spans passes)",
      k.e.r32(HW + 0x1274) - k.e.r32(HW + 0x1270) == 2 and k.e.r32(MB + 0x30) == 2, (k.e.r32(HW + 0x1274), k.e.r32(HW + 0x1270)))
panel(k)
bbkit.main(["play"])
bbkit.main(["button", "rec", "release"])
codes = [k.e.r16(PANEL + i * 0x18) for i in range(2)]
check(f"bbkit.py play, button rec release: PLAY's and REC's release codes in the GUI's ring ({[hex(c) for c in codes]})",
      codes == [0xF7, 0xF5], codes)
w0 = k.e.r32(HW + 0x1274)
try:
    bbkit.job(0x03, 0, 1, 50, 1000, timeout=0.05)          # a knob job far longer than the client waits
    gave_up = None
except SystemExit as e_:
    gave_up = str(e_)
r = struct.unpack("<II", bytes(k.e.uc.mem_read(MB + 0x40, 4)) + bytes(k.e.uc.mem_read(MB + 0x50, 4)))
check(f"bbkit.py: a knob job that does not end in its time is cancelled, so it does not go on behind the next command "
      f"({gave_up!r})", gave_up and "cancelled (after 1 event(s))" in gave_up and r[0] == 0 and r[1] & 0xFF == 0
      and k.e.r32(HW + 0x1274) == w0 + 1, (gave_up, r))
k.ask(0x03, 0, 1, 50, 1000)                                # one left running (another client's, or a crashed one)
k.run(SCREEN)
seq0 = k.e.r32(MB + 0x24)
try:
    bbkit.job(0x00)
    refused = None
except SystemExit as e_:
    refused = str(e_)
check(f"bbkit.py: while a knob job runs, nothing is sent but a cancel ({refused!r})", refused and "still running a knob job"
      in refused and k.e.r32(MB + 0x24) == seq0, refused)
bbkit.main(["cancel"])
check("bbkit.py cancel: the job ended, and the next command runs", k.e.r32(MB + 0x40) == 0 and bbkit.job(0x00)[0] == 0x10060)
# bbusb.py set (MBX1, as bench/autogate.py uses it) right after a KIT1 request, with a GUI pass after every word the
# computer writes - the worst interleaving: the row is set once (review 12/11: the box's KIT1 words at +4 and +0x14
# read as MBX1's seq and done once the magic landed, and the row was set before its seq, then again)
bbusb.time = _Clock
bbusb.poke = lambda a, v: (k.e.w32(a, v & 0xFFFFFFFF), k.run(SCREEN))
bbkit.job(0x07, -1, 0, 9)                                  # KIT1: +4 index 7, +0x14 (arg 2) 9
k.store[(PAD12, 0x1C9)] = 11
k.msgs.clear()
res = bbusb.mailbox(1, 1, 2, 0x1C9, 11)
posts = list(k.msgs)
k.msgs.clear()
res2 = bbusb.mailbox(1, 1, 2, 0x1C9, 12)                   # MBX1 already in the box: the short way
posts2 = list(k.msgs)
check(f"bbusb.py set right after a KIT1 job, a GUI pass after every word written: the row is set once, answered 0; the "
      f"next set once too ({posts}, {posts2})", posts == [(0x6E, 0, 0x12, 0x1C9, 11, 0)] and res == (0, 11) and res2[0] == 0
      and posts2 == [(0x6E, 0, 0x12, 0x1C9, 12, 0)], (posts, res, posts2, res2))

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
