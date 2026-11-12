"""Crash-safe bank 2 (src/b2safe.c, hub #t-059) under Unicorn: the crash count from boot to boot, the hold, and what a
held boot does.

A boot here is the real boot path: master_alloc (the delay constructor's hook: instrument_boot, which counts the reset,
then b2_present for the block's tail), then the audio task's waits (cpu_wait: the meter's start at the first wake,
where a hold is applied, and the 32.8 s check every 376th). Between boots RCC_RSR is set to what that reset leaves on
the unit (bench/bbusb.py's bits; a fault's reset and the loader's restart both read CPU + PIN + SOFTWARE), backup SRAM
keeps what it held (after a power-on: noise), stock's block counter at 0x2400a58c and the disk and screen tasks' stamps
beside it start again from 0 (.bss) and are set to the uptime a case needs (a hung task's stamp stops where it hung). A
crash by fault runs fault_record on a stacked frame, up to the reset it asks for; a
watchdog reset leaves WWDG1RSTF. The card loader runs with stock's file calls stubbed, and b2_program (the flash write,
test_b2load.py's) stubbed to put the card's payload in bank 2.

MUTANTS, at the end: each rule's instruction is patched in a fresh emulator, and the checks that guard it must fail.

Not shown here, and only the unit can: the data cache (the emulator has none, so the order of the writes and the line
cleans is checked instead), the reset itself, stock clearing RCC_RSR after the boot hook, the real length of a block.
"""
import random
import struct
import subprocess
import sys

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE

from emu import BASE, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
ELF = "out/cave.elf"
B2, B2_END, CLAIM_AT = 0x08100000, 0x081E0000, 0x081C0000
LINE, MARK, CRASHES, FAULTED = 0x388003C0, 0x388003C8, 0x388003D4, 0x388003D8
TRIES_N, SCANNING = 0x388003D0, 0x4E435332
FLT1 = 0x31544C46
SR2, ECC = 0x52002110, 1 << 25
RCC_RSR, UPTIME = 0x580244D0, 0x2400A58C
STAMP_DISK, STAMP_APP = 0x2400A584, 0x2400A588      # stock's watchdog stamps: pcmStreamer's loop, the screen task's app pass
M = 0x2405FFD0
B2CHK = M + 35
DCCMVAC, AIRCR = 0xE000EF68, 0xE000ED0C
KEYR2, CR2 = 0x52002104, 0x5200210C
F_OPEN, F_READ, F_CLOSE, CARD_FOUND = 0x08086534, 0x08086866, 0x08086D76, 0x240021A4 + 0x15
LINE_ALLOC, PERM_ALLOC, LABEL_SET, RECEIVE = 0x0806AA80, 0x0804436C, 0x080A3DEC, 0x08088756
BLOCK, CORE = 0xC0100000, 0x1D110
FRAME = 0x30000100
SPACE, SPACE_TEXT = 0x24062174, 0x24063000
CPU, D1, D2, BOR, PIN, POR, SFT, WWDG = (1 << b for b in (17, 19, 20, 21, 22, 23, 24, 28))
POWER_ON = POR | BOR | PIN                 # what a power-cycle read on the test unit (bench notes 2026-10-16, -10-20)
RESTART = SFT | PIN | CPU                  # a SYSRESETREQ: the loader's restart (Gate 3 part 1) and the recorder's both read this
WATCHDOG = WWDG | PIN | CPU
HELD = 0x86                                # b2chk: B2_HELD | B2_LOOKED | B2_UNPAIRED
PER_SECOND = 375                           # audio blocks: 128 frames at 48 kHz

payload = open("out/bank2.bin", "rb").read()   # the payload THIS image expects (the suites' emu may load the unit's)
stale = bytearray(payload)
stale[100:200] = bytes(100)
struct.pack_into("<I", stale, 12, 0)          # another build's payload: bank 2 not paired, the card file still this one's
stale = bytes(stale)
sym = {l.split()[2]: int(l.split()[0], 16) for l in subprocess.run(["arm-none-eabi-nm", ELF], capture_output=True, text=True,
                                                                   check=True).stdout.splitlines() if len(l.split()) == 3}
WHOLE = 0x95910 + (0x1400 if "kit_run" in sym else 0)   # a dev build adds the bench kit's area at the tail's end (src/master.c)
size = {l.split()[3]: int(l.split()[1], 16) for l in subprocess.run(["arm-none-eabi-nm", "-S", ELF], capture_output=True,
                                                                    text=True, check=True).stdout.splitlines() if len(l.split()) == 4}
img = open(IMAGE, "rb").read()
noise = random.Random(59)


class Unit:
    """One unit, from a power-on, across as many resets as a case needs."""

    def __init__(self, patches=()):
        self.patches = patches                 # a case that needs a second unit builds it with the same mutant
        self.e = e = Emu(IMAGE, ELF)
        self.uc = uc = e.uc
        for base, n in ((0x38800000, 0x1000), (0x58024000, 0x1000), (0x50003000, 0x1000), (0x30000000, 0x1000),
                        (0xC0000000, 0x200000)):
            uc.mem_map(base, n)
        uc.mem_write(B2, b"\xff" * (B2_END - B2))
        uc.mem_write(B2, payload)
        uc.mem_write(CLAIM_AT, struct.pack("<8I", 0x43324242, ~0x43324242 & 0xFFFFFFFF, 1, 0, 0, 0, 0, 0))
        self.log = []                      # in order: ("w", addr, value) to the bank 2 line, ("c", line) cleaned, ("r", value)
        self.reads = self.runs = self.flash = self.programs = self.opens = 0
        self.card, self.pos, self.allocs, self.labels, self.asked = payload, 0, [], [], False
        uc.hook_add(UC_HOOK_MEM_WRITE, lambda _u, _a, a, _s, v, _d: self.log.append(("w", a, v & 0xFFFFFFFF)), begin=LINE, end=LINE + 31)
        uc.hook_add(UC_HOOK_MEM_WRITE, lambda _u, _a, a, _s, v, _d: self.log.append(("c", v & ~31 & 0xFFFFFFFF)),
                    begin=DCCMVAC, end=DCCMVAC + 3)
        uc.hook_add(UC_HOOK_MEM_WRITE, self._reset, begin=AIRCR, end=AIRCR + 3)
        uc.hook_add(UC_HOOK_MEM_READ, lambda *_: setattr(self, "reads", self.reads + 1), begin=B2, end=B2_END - 1)
        uc.hook_add(UC_HOOK_CODE, lambda *_: setattr(self, "runs", self.runs + 1), begin=B2, end=B2_END - 1)
        uc.hook_add(UC_HOOK_MEM_WRITE, lambda _u, _a, a, *_: setattr(self, "flash", self.flash + 1) if a in (KEYR2, CR2) else None,
                    begin=0x52002000, end=0x52002FFF)
        uc.hook_add(UC_HOOK_MEM_WRITE, lambda *_: setattr(self, "flash", self.flash + 1), begin=B2, end=B2_END - 1)
        e.stub(LINE_ALLOC, lambda: self.allocs.append("line"))
        e.stubs[PERM_ALLOC] = self._perm
        e.stubs[RECEIVE] = self._receive
        e.stub(LABEL_SET, lambda: self.labels.append((e.arg(0), e.cstr(e.arg(1)))))
        e.stubs[F_OPEN], e.stubs[F_READ] = self._open, self._read
        e.stub(F_CLOSE, value=0)
        e.stub(sym["b2_program"] & ~1, self._program, value=1)
        uc.mem_write(SPACE_TEXT, b"12.3 GB\0")
        for at, data in patches:
            uc.mem_write(at, data)

    def _reset(self, uc, _a, _addr, _s, value, _d):
        self.log.append(("r", value & 0xFFFFFFFF))
        self.asked = True
        uc.emu_stop()

    def _perm(self):
        self.allocs.append(("perm", self.e.arg(0)))
        self.e.ret(BLOCK if len(self.allocs) == 2 else 0)     # the block, then stretch.c's area: refused here

    def _receive(self):
        self.e.w32(0xE0001004, self.u32(0xE0001004) + 1_280_000)
        self.e.ret(1)

    def _open(self):
        self.opens += 1
        self.pos = 0
        self.e.ret(4 if self.card is None else 0)

    def _read(self):
        to, n, got = self.e.arg(1), self.e.arg(2), self.e.arg(3)
        chunk = self.card[self.pos:self.pos + n]
        self.uc.mem_write(to, chunk)
        self.e.w32(got, len(chunk))
        self.pos += len(chunk)
        self.e.ret(0)

    def _program(self):
        self.programs += 1
        self.uc.mem_write(B2, self.card)

    def u32(self, a):
        return struct.unpack("<I", self.uc.mem_read(a, 4))[0]

    def call(self, fn, *args):
        """True if it asked for a reset (SYSRESETREQ) instead of returning."""
        self.asked = False
        try:
            self.e.call(fn, *args, count=50_000_000)
        except AssertionError:
            if not self.asked:
                raise
        return self.asked

    # ---- what happens to the unit
    def power_on(self, keep=False, rsr=POWER_ON):
        """keep: backup SRAM held its words through a short power-off (a fast power-cycle, or a battery)"""
        if not keep:
            self.uc.mem_write(LINE, bytes(noise.getrandbits(8) for _ in range(32)))
        self.uc.mem_write(M, bytes(noise.getrandbits(8) for _ in range(36)))
        self.boot(rsr)

    def boot(self, rsr):
        """out of a reset that left `rsr`: the boot hook, then the audio task's first wake"""
        self.e.w32(RCC_RSR, rsr)
        for at in (UPTIME, STAMP_DISK, STAMP_APP):           # stock's .bss: 0 at every reset
            self.e.w32(at, 0)
        self.allocs.clear()
        self.reads = self.runs = 0
        self.call("master_alloc", 0x24076000, 192000)
        self.wake()

    def wake(self, n=1):
        for _ in range(n):
            self.e.call("cpu_wait", 0x24001F00, 0x24001F80, 2000, 0)

    def up(self, seconds, hung=None):
        """the unit stays up: stock's block counter at `seconds`, both tasks' stamps with it (a healthy task stamps on
        every pass) unless `hung` ({stamp: second}) says that task stopped there, and 376 wakes so the meter looks once"""
        blocks = int(seconds * PER_SECOND)
        self.e.w32(UPTIME, blocks)
        for at in (STAMP_DISK, STAMP_APP):
            self.e.w32(at, int(hung[at] * PER_SECOND) if hung and at in hung else blocks)
        self.wake(376)

    def fault(self, seconds=5):
        """up for a while, then a fault in bank 2's code: the recorder, and the reset it asks for"""
        self.up(seconds)
        self.uc.mem_write(FRAME, struct.pack("<8I", 0, 1, 2, 3, 12, 0x08100235, 0x08100240, 0x61000000))
        assert self.call("fault_record", FRAME, 0xFFFFFFED), "the recorder did not ask for the reset"
        self.boot(RESTART)

    def watchdog(self, seconds=5):
        self.up(seconds)
        self.boot(WATCHDOG)

    def scan_dies(self):
        """this boot's pairing scan dies on a flash word it cannot read: b2_paired's mark is up (its bkp_put before the
        read), the read bus-faults, the recorder asks for the reset"""
        self.up(1)
        self.e.w32(MARK, SCANNING)
        self.uc.mem_write(FRAME, struct.pack("<8I", 0, 1, 2, 3, 12, 0x080F6300, 0x080F6300, 0x61000000))
        assert self.call("fault_record", FRAME, 0xFFFFFFED), "the recorder did not ask for the reset"
        self.boot(RESTART)

    # ---- what the boot made of it
    def count(self):
        return self.u32(CRASHES)

    def held(self):
        return self.uc.mem_read(B2CHK, 1)[0] == HELD

    def tail(self):
        """master_alloc's block: the whole one when b2_present said the payload is there"""
        return [a for a in self.allocs if a != "line"][:1] == [("perm", WHOLE)]

    def live(self):
        self.e.call("b2_live", count=50_000_000)
        return self.uc.reg_read(66)                           # r0

    def present(self):
        self.e.call("b2_present", count=50_000_000)
        return self.uc.reg_read(66)

    def tools(self):
        self.labels.clear()
        self.e.call("cpu_tools", SPACE, SPACE_TEXT)
        return dict(self.labels).get(SPACE - 0xA0, "")

    def loader(self, card=payload):
        """the disk task's pass through the loader, with `card` on the card (None: no file); True = it restarted"""
        self.card, self.opens, self.programs, self.flash = card, 0, 0, 0
        self.uc.mem_write(CARD_FOUND, b"\x01")
        return self.call("b2_load_poll")


# ---------------------------------------------------------------- the cases, each a list of (label, ok, detail)
def held_boot(u, what):
    """everything a held boot must be, from the boot hook on"""
    out = [(f"{what}: b2chk is unpaired, looked and held (0x86) from the meter's first block", u.held(),
            hex(u.uc.mem_read(B2CHK, 1)[0]))]
    reads, runs = u.reads, u.runs
    out.append(("...the boot hook took the core block only: b2_present said no payload, without reading bank 2",
                not u.tail() and reads == 0, (u.allocs, reads)))
    out.append(("...b2_live says no, and nothing reads bank 2 or runs there (no pairing scan)",
                u.live() == 0 and u.present() == 0 and u.reads == 0 and u.runs == 0 and runs == 0, (u.reads, u.runs)))
    text = u.tools()
    out.append((f"...Tools leads with '!held' ({text!r})", text.startswith("!held "), text))
    asked = u.loader()
    out.append(("...the card loader, this image's payload on the card, stays out: no file opened, nothing written, no restart",
                not asked and u.opens == 0 and u.programs == 0 and u.flash == 0, (asked, u.opens, u.programs, u.flash)))
    return out


def three_faults(u):
    u.power_on()
    out = [("power-on: the count is 0, bank 2 paired and live, the whole block taken", u.count() == 0 and not u.held()
            and u.tail() and u.live() == 1, (u.count(), u.allocs))]
    counts, held = [], []
    for _ in range(3):
        u.fault(5)
        counts.append(u.count())
        held.append(u.held())
    out.append(("THREE BOOTS ENDED BY A FAULT AT SECOND 5: the count goes 1, 2, 3 and the third crash's next boot is held",
                counts == [1, 2, 3] and held == [False, False, True], (counts, held)))
    return out + held_boot(u, "the held boot")


def three_watchdogs(u):
    u.power_on()
    counts = []
    for _ in range(3):
        u.watchdog(5)
        counts.append(u.count())
    return [("THREE BOOTS ENDED BY THE WINDOW WATCHDOG: 1, 2, 3, held", counts == [1, 2, 3] and u.held(), counts)]


def faults_and_watchdogs(u):
    u.power_on()
    u.fault()
    u.watchdog()
    u.fault()
    return [("a fault, a watchdog, a fault: they add up the same, held", u.count() == 3 and u.held(), u.count())]


def good_boot(u):
    u.power_on()
    u.fault()
    u.fault()
    out = [("two crashed boots: count 2, not held, bank 2 live", u.count() == 2 and not u.held() and u.live() == 1, u.count())]
    u.up(32)
    out.append(("the third boot stays up 32 s: still 2 (the line is 12,288 blocks, 32.8 s)", u.count() == 2, u.count()))
    u.up(33)
    out.append(("...and at 33 s THE COUNT IS 0: a boot that stays up is a good one", u.count() == 0, u.count()))
    u.fault(40)
    out.append(("TWO CRASHES AND A GOOD BOOT DO NOT HOLD: the good boot's own crash at second 40 counts 1, not 3",
                u.count() == 1 and not u.held() and u.live() == 1, u.count()))
    u.fault()
    u.watchdog()
    out.append(("...and two more crashed boots after that one make three: held", u.count() == 3 and u.held(), u.count()))
    return out


def hung_task(u):
    """The audio runs the 32.8 s check, so it is alive by definition; the screen and disk tasks are what the watchdog
    also waits on. One that hangs at second 25 stops its stamp there and the watchdog resets the unit 10 s later, at 35."""
    out = []
    for name, stamp in (("the screen task (the app pass's stamp)", STAMP_APP), ("the disk task (pcmStreamer's stamp)", STAMP_DISK)):
        u.power_on()
        u.fault()
        u.fault()
        u.up(33, hung={stamp: 25})
        kept = u.count()
        u.boot(WATCHDOG)
        out.append((f"two crashed boots, then {name} hangs at second 25 while the audio runs on: at 33 s the count is STILL 2, "
                    "and the watchdog's reset at 35 s makes three: held", kept == 2 and u.count() == 3 and u.held(), (kept, u.count())))
    return out


def hold_holds(u):
    u.power_on()
    for _ in range(3):
        u.fault()
    counts = []
    for crash in (u.fault, u.fault, u.watchdog, u.fault):
        crash()
        counts.append((u.count(), u.held()))
    out = [("THE HOLD HOLDS ACROSS FURTHER CRASHED BOOTS (fault, fault, watchdog, fault): 4, 5, 6, 7, held every time",
            counts == [(4, True), (5, True), (6, True), (7, True)], counts)]
    u.up(60)
    out.append(("a held boot that stays up 60 s keeps the count: bank 2 was off, that proves nothing of it",
                u.count() == 7, u.count()))
    u.fault(65)
    out.append(("...so its crash at second 65 leaves the next boot held too", u.count() == 8 and u.held(), u.count()))
    return out + held_boot(u, "eight crashes in")


def honest(u):
    out = []
    u.power_on()
    seen = []
    for _ in range(5):
        u.fault(2)                                           # it crashes 2 s in ...
        seen.append((u.count(), u.held()))
        u.up(1)
        u.power_on(keep=True)                                # ... and is power-cycled at once, backup SRAM kept through it
        seen.append((u.count(), u.held()))
    out.append(("a unit power-cycled fast after each of five crashes: 1, 0, 1, 0 ... never held",
                seen == [(1, False), (0, False)] * 5, seen))
    for label, reset in (("a SYSRESETREQ with no fault (the loader's kind of restart)", lambda: u.boot(RESTART)),
                         ("a pin reset", lambda: u.boot(PIN | CPU)),
                         ("a power-on", lambda: u.power_on(keep=True)),
                         ("the installer's reset into the new image", lambda: u.boot(RESTART | POR | BOR))):
        u.fault()
        u.fault()
        before = u.count()
        u.up(3)
        reset()
        out.append((f"two crashed boots, then {label}: NOT A CRASH, the count goes back to 0", before == 2 and u.count() == 0
                    and not u.held(), (before, u.count())))
    u.fault()
    u.fault()
    u.up(3)
    u.uc.mem_write(FRAME, struct.pack("<8I", 0, 1, 2, 3, 12, 0x08100235, 0x08100240, 0x61000000))
    u.call("fault_record", FRAME, 0xFFFFFFED)                # FAULT_SHOW holds here, and the user power-cycles
    u.power_on(keep=True, rsr=POWER_ON | RESTART)            # flags from before stock's clear can still be there
    out.append(("a power-on that finds the fault's token still in backup SRAM (FAULT_SHOW's hold, power-cycled): 0",
                u.count() == 0 and u.u32(FAULTED) == 0, (u.count(), hex(u.u32(FAULTED)))))
    u.fault()
    u.fault()
    u.up(3)
    u.call("fault_record", FRAME, 0xFFFFFFED)                # the token is up again ...
    u.boot(BOR | PIN | WWDG)                                 # ... and a brown-out alone, a watchdog flag still there
    out.append(("a BROWN-OUT ALONE (BOR, no POR) that finds the token and a watchdog flag: not a crash, 0",
                u.count() == 0 and u.u32(FAULTED) == 0, (u.count(), hex(u.u32(FAULTED)))))
    u.uc.mem_write(B2, stale)                                  # bank 2 holds another build's payload ...
    u.fault()
    u.fault()
    before = u.count()
    asked = u.loader()                                         # ... the loader writes this one's and restarts
    u.boot(RESTART)
    out.append(("two crashed boots, then THE LOADER'S RESTART AFTER IT WROTE BANK 2: 0, and the payload is paired and live",
                before == 2 and asked and u.programs == 1 and u.count() == 0 and not u.held() and u.live() == 1,
                (before, asked, u.programs, u.count())))
    return out


def hold_ends(u):
    out = []
    for label, leave in (("a power-cycle", lambda: u.power_on(keep=True)),
                         ("a power-cycle that wipes backup SRAM", lambda: u.power_on()),
                         ("a SYSRESETREQ with no fault (the installer's, if its bootloader restarts that way: not observed)",
                          lambda: u.boot(RESTART))):
        u.power_on()
        for _ in range(3):
            u.watchdog()
        was = u.held()
        leave()
        out.append((f"held, then {label}: count 0, bank 2 scanned, paired and live, the whole block", was and u.count() == 0
                    and not u.held() and u.tail() and u.live() == 1 and u.reads > 0, (was, u.count(), u.allocs)))
    u.power_on()
    for _ in range(3):
        u.fault()
    asked = u.loader(card=None)
    u.power_on(keep=True)
    out.append(("A UNIT WITH NO CARD, held: the loader does nothing, and a power-cycle gives the payload its boots again",
                not asked and u.opens == 0 and u.count() == 0 and u.live() == 1, (asked, u.count())))
    return out


def new_payload(u):
    """The loader takes only this image's payload (b2load.c's header_ok: this id, this sum), so a payload with another
    id comes only with another image, and that goes in through the installer. The emulator runs one image, so what is
    shown is the installer's power-on clearing a hold and the loader writing the card's payload after it - not an id
    that changed."""
    u.power_on()
    u.uc.mem_write(B2, stale)                                  # bank 2 is not the payload this image expects
    for _ in range(3):
        u.fault()
    asked = u.loader()
    out = [("held, a stale bank 2 and this image's payload on the card: no write while held (it could only be this one again)",
            u.held() and not asked and u.opens == 0 and u.programs == 0, (u.held(), asked, u.opens))]
    u.power_on(keep=True)                                      # the installer: BACK + INFO at power-on (docs/JOEBOX.md)
    asked = u.loader()
    out.append(("held, then THE INSTALLER'S POWER-ON (the only way a payload with another id arrives): count 0, the loader "
                "writes the card's payload and restarts", u.count() == 0 and asked and u.programs == 1, (u.count(), asked, u.programs)))
    u.boot(RESTART)
    out.append(("...and the boot after that write is 0, paired, live, the whole block", u.count() == 0 and not u.held()
                and u.live() == 1 and u.tail(), (u.count(), u.allocs)))
    return out


def loader_loop(u):
    """The loader's restart is not a crash, so the count cannot stop a loop of rewrites: B2_MAX_TRIES has to. A write
    that reads back clean (b2_rescan pairs) and a boot after it that still cannot use bank 2 - its scan dies on a word
    that reads marginal after a reset, or only sees the ECC flag - is that loop."""
    out = []
    u.power_on()
    u.uc.mem_write(B2, stale)                                  # another build's payload: the loader will write this one's
    u.boot(RESTART)
    writes = []
    for _ in range(5):
        asked = u.loader()
        writes.append((asked, u.programs, u.u32(TRIES_N)))
        if not asked:
            break
        u.boot(RESTART)                                        # the loader's restart: count 0
        u.scan_dies()                                          # the boot after it dies in the scan: count 1
    u.up(33)
    out.append(("THE SAME PAYLOAD IS NOT REWRITTEN IN A LOOP: the rescan pairs, the next boot's scan dies - two writes, then left alone",
                [w[:2] for w in writes] == [(True, 1), (True, 1), (False, 0)], writes))
    out.append(("...and the boot it is left alone in stays up without bank 2: not live, '!' on Tools, the count back to 0",
                u.live() == 0 and u.tools().startswith("!") and u.count() == 0, (u.live(), u.count())))

    u = Unit(u.patches)
    flaky = {"on": True}
    u.uc.hook_add(UC_HOOK_MEM_READ, lambda uc, _a, a, _s, _v, _d: uc.mem_write(SR2, struct.pack("<I", ECC if flaky["on"] else 0)),
                  begin=SR2, end=SR2 + 3)

    def program_reads_clean():
        u._program()
        flaky["on"] = False                                    # right after the write the bank reads clean ...

    u.e.stub(sym["b2_program"] & ~1, program_reads_clean, value=1)
    u.power_on()
    writes = []
    for _ in range(5):
        flaky["on"] = True                                     # ... and after the reset it shows the ECC flag again
        asked = u.loader()
        writes.append((asked, u.programs, u.count()))
        if not asked:
            break
        u.boot(RESTART)
    out.append(("...THE SAME WITH NO CRASH AT ALL (the boot's scan sees the ECC flag, the rescan does not): two writes, then left alone",
                [w[:2] for w in writes] == [(True, 1), (True, 1), (False, 0)], writes))
    return out


def cache(u):
    out = []
    u.power_on()
    u.fault()
    u.up(5)
    u.log.clear()
    u.uc.mem_write(FRAME, struct.pack("<8I", 0, 1, 2, 3, 12, 0x08100235, 0x08100240, 0x61000000))
    u.call("fault_record", FRAME, 0xFFFFFFED)
    log = list(u.log)
    token = next((i for i, x in enumerate(log) if x == ("w", FAULTED, FLT1)), None)
    reset = next((i for i, x in enumerate(log) if x[0] == "r"), None)
    out.append(("the recorder writes the token, then cleans its line, then asks for the reset", token is not None and reset is not None
                and token < reset and ("c", LINE) in log[token:reset], log[-3:]))
    # On each boot the next thing to touch that line must be its clean. A boot that is not held gets one a moment later
    # anyway, from b2_present's bkp_put of the naming mark; a held boot does not, so both kinds are looked at.
    for what, crash, n in (("a crashed boot, not held", lambda: u.boot(RESTART), 2), ("the boot that is held", u.fault, 3),
                           ("a held boot's crash", u.watchdog, 4)):
        u.log.clear()
        crash()
        at = next((i for i, x in enumerate(u.log) if x[:2] == ("w", CRASHES)), None)
        out.append((f"{what}: the boot takes the token down, writes the count ({n}), and the very next thing is the clean of their line",
                    at is not None and u.log[at] == ("w", CRASHES, n) and ("w", FAULTED, 0) in u.log[:at] and u.log[at + 1:at + 2] == [("c", LINE)],
                    u.log[:6]))
    u.power_on()
    u.fault()
    u.log.clear()
    u.up(33)
    clear = next((i for i, x in enumerate(u.log) if x == ("w", CRASHES, 0)), None)
    out.append(("the 32.8 s clear writes 0, and the very next thing is the clean of its line",
                clear is not None and u.log[clear + 1:clear + 2] == [("c", LINE)], u.log[:4]))
    dis = subprocess.run(["arm-none-eabi-objdump", "-d", "--no-show-raw-insn", "--disassemble=bkp_put", ELF], capture_output=True,
                         text=True).stdout
    ins = [l.split("\t", 1)[1] for l in dis.splitlines() if l.strip()[:1] == "8" and "\t" in l]
    st = next((i for i, l in enumerate(ins) if l.startswith("str") and "0xf68" in l), None)
    out.append(("bkp_put: the write, the clean of its line (DCCMVAC), then DSB", st is not None and any(l.startswith("dsb") for l in ins[st:]),
                ins))
    return out


CASES = {f.__name__: f for f in (three_faults, three_watchdogs, faults_and_watchdogs, good_boot, hung_task, hold_holds, honest,
                                  hold_ends, new_payload, loader_loop, cache)}


# ---------------------------------------------------------------- mutants: one rule broken each, in the linked image
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def insns(fn):
    a = sym[fn] & ~1
    return list(md.disasm(img[a - BASE:a - BASE + size[fn]], a))


def pair(fn, first, then):
    """the two instructions in a row that `first` and `then` match: exactly one such pair, or None"""
    i = insns(fn)
    hits = [(i[k], i[k + 1]) for k in range(len(i) - 1) if first(i[k]) and then(i[k + 1])]
    return hits[0] if len(hits) == 1 else (None, None)


def after(fn, first, then):
    return pair(fn, first, then)[1]


def one(fn, match):
    hits = [x for x in insns(fn) if match(x)]
    return hits[0] if len(hits) == 1 else None


def nop(x):
    return [(x.address, b"\x00\xbf" if x.size == 2 else b"\xaf\xf3\x00\x80")] if x else None


def imm8(x, value):
    """a 16-bit instruction with its immediate in the low byte (cmp / mov imm8)"""
    return [(x.address, bytes([value, x.bytes[1]]))] if x and x.size == 2 else None


def to_b(x):
    """a 16-bit conditional branch made unconditional, same target"""
    if not x or x.size != 2:
        return None
    off = (int(x.op_str.lstrip("#"), 16) - (x.address + 4)) >> 1
    return [(x.address, struct.pack("<H", 0xE000 | (off & 0x7FF)))]


def literal(fn, old, new):
    a = sym[fn] & ~1
    hits = [o for o in range((a + 3) & ~3, a + size[fn], 4) if struct.unpack_from("<I", img, o - BASE)[0] == old]
    return [(hits[0], struct.pack("<I", new))] if len(hits) == 1 else None


def is_(mn, *ops):
    return lambda x: x.mnemonic.split(".")[0] == mn and all(o in x.op_str for o in ops)


def ldr_count(x):
    return x.mnemonic.startswith("ldr") and "#0x3d4]" in x.op_str


def branch(*mn):
    return lambda x: x.mnemonic.split(".")[0] in mn


def add2():
    x = one("b2_crash_boot", lambda x: x.mnemonic == "adds" and x.op_str.endswith("#1"))
    if not x:
        return None
    h = struct.unpack("<H", x.bytes)[0]
    return [(x.address, struct.pack("<H", (h & ~(7 << 6)) | (2 << 6)))]


def no_clean():
    x = one("b2_crash_boot", lambda x: x.mnemonic == "b.w" and int(x.op_str.lstrip("#"), 16) == sym["bkp_put"] & ~1)
    return [(x.address, b"\x01\x60\x70\x47")] if x else None           # str r1, [r0]; bx lr: the write without the clean


def never_clear():
    x = one("b2_crash_uptime", lambda x: x.mnemonic == "b.w" and int(x.op_str.lstrip("#"), 16) == sym["bkp_put"] & ~1)
    return [(x.address, b"\x70\x47\x00\xbf")] if x else None           # bx lr: the clear never written


def no_bor():
    """the power-on test without BOR: tst #0xa00000 (POR | BOR) made #0x800000, its modified immediate's 0x20 bit off"""
    x = one("b2_crash_boot", is_("tst", "#0xa00000"))
    if not x or x.size != 4:
        return None
    return [(x.address, bytes(x.bytes[:2]) + struct.pack("<H", struct.unpack_from("<H", x.bytes, 2)[0] & ~0x20))]


def stamp_gate(field):
    """the branch that skips the 32.8 s clear while this stamp (#0x584 the disk task's, #0x588 the screen task's) is
    under 12,288 blocks"""
    i = insns("b2_crash_uptime")
    hits = [i[k + 2] for k in range(len(i) - 2) if i[k].mnemonic.startswith("ldr") and f"#{field}]" in i[k].op_str
            and is_("cmp", "#0x3000")(i[k + 1]) and branch("bcc", "blo")(i[k + 2])]
    return hits[0] if len(hits) == 1 else None


def no_wait():
    disk, app = nop(stamp_gate("0x584")), nop(stamp_gate("0x588"))
    return disk + app if disk and app else None


def text_off():
    x = pair("cpu_tools", is_("ldrb", "#0xf3]"), is_("lsls", "#0x18"))[0]
    if not x or x.size != 4:
        return None
    return [(x.address, bytes(x.bytes[:2]) + struct.pack("<H", (struct.unpack_from("<H", x.bytes, 2)[0] & ~0xFFF) | 0xF2))]  # late, not b2chk


MUTANTS = [
    ("the window watchdog's reset is not counted", lambda: to_b(after("b2_crash_boot", is_("ands", "#0x10000000"), branch("beq"))),
     ["three_watchdogs"]),
    ("the boot does not take the recorder's token for a crash", lambda: literal("b2_crash_boot", FLT1, FLT1 ^ 1), ["three_faults"]),
    ("the recorder leaves no token", lambda: nop(one("fault_record", lambda x: x.mnemonic.startswith("str") and "#0x3d8]" in x.op_str)),
     ["three_faults"]),
    ("every SYSRESETREQ is a crash (the token not asked)", lambda: nop(after("b2_crash_boot", is_("cmp", "r0, r3"), branch("bne"))),
     ["honest"]),
    ("a power-on does not clear the count", lambda: nop(after("b2_crash_boot", ldr_count, branch("bne"))), ["honest"]),
    ("a brown-out does not clear the count (POR alone)", no_bor, ["honest"]),
    ("a crash counts two", add2, ["good_boot"]),
    ("the count clears at boot, not after 32.8 s", no_wait, ["three_faults"]),
    ("the clear does not wait for the disk task's stamp", lambda: nop(stamp_gate("0x584")), ["hung_task"]),
    ("the clear does not wait for the screen task's stamp", lambda: nop(stamp_gate("0x588")), ["hung_task"]),
    ("a boot that stays up never clears the count", never_clear, ["good_boot"]),
    ("the 32.8 s clear also clears a hold", lambda: nop(after("b2_crash_uptime", is_("cmp", "#1"), branch("bhi"))), ["hold_holds"]),
    ("the hold needs four crashes", lambda: imm8(after("cpu_wait", ldr_count, is_("cmp", "#3")), 4), ["three_faults"]),
    ("a held boot lets the card loader in", lambda: imm8(one("cpu_wait", lambda x: x.mnemonic.startswith("mov") and x.op_str.endswith("#0x86")), 0x82),
     ["three_faults", "new_payload"]),
    ("a held boot still pairs bank 2", lambda: imm8(one("cpu_wait", lambda x: x.mnemonic.startswith("mov") and x.op_str.endswith("#0x86")), 0x84),
     ["three_faults"]),
    ("b2_present ignores the hold", lambda: nop(after("b2_present", lambda x: is_("cmp", "#2")(x), branch("bhi"))), ["three_faults"]),
    ("Tools shows no '!held'", text_off, ["three_faults"]),
    ("the boot's count is written without cleaning its line", no_clean, ["cache"]),
    ("B2_MAX_TRIES does not stop the card loader", lambda: nop(after("b2_load_poll", is_("cmp", "#1"), branch("bhi"))), ["loader_loop"]),
]


def run(case, u):
    try:
        return CASES[case](u)
    except Exception as exc:                                   # a mutant may take the code off the rails: that is red too
        return [(f"{case} ran to the end", False, repr(exc)[:200])]


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


for name in CASES:
    print(f"--- {name}")
    for label, ok, detail in run(name, Unit()):
        check(label, ok, detail)

print("--- mutants")
for what, make, cases in MUTANTS:
    patches = make()
    if not patches:
        check(f"MUTANT '{what}': its instruction is found in this build", False, "not found exactly once: the suite needs updating")
        continue
    red = [label for case in cases for label, ok, _ in run(case, Unit(patches)) if not ok]
    check(f"MUTANT '{what}' is caught ({len(red)} red: {red[0][:70] if red else '-'})", red, cases)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
