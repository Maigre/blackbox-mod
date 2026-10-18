"""Munchi Delay in the delay slot, under Unicorn.

Real firmware runs for: settings lookup, the list helpers (fill / remove), buffer pointer / length helpers and the
output mix (FUN_08061844). Stubbed: the stock delay process, its line clear, the send gate, the bus lookup, the
param registrars and store add.
NOT checked: how it sounds, the settings page redrawing when Type changes, CPU on the real chip (counted here as
instructions), and anything else in the firmware touching the delay's lines while Munchi owns them.
The engine is in flash bank 2 (src/munchi_dsp.cpp), loaded here beside the image the way the unit has it; what it plays
is held to the bit by a fixed run (the fingerprint below), and without bank 2 Munchi has to be the stock delay.
"""
import hashlib
import math
import struct
import sys

from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_SP

from emu import STACK, Emu

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin", "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(0x50003000, 0x1000)                       # WWDG1: audio_watch re-arms the early wakeup each block
e.uc.mem_map(0xC0000000, 0x400000)                     # SDRAM: the delay's lines
e.uc.mem_map(0x30000000, 0x10000)                      # fake objects
OBJ, VT, BUFS, CTX, BUS, IN = 0x30000000, 0x30001000, 0x30001100, 0x30001200, 0x30001300, 0x30001400
BUSL, BUSR, INL, INR, ARR, STORE2, VT2 = 0x30002000, 0x30002400, 0x30002800, 0x30002C00, 0x30003000, 0x30003400, 0x30003500
LIVE, STATE, FRZ = 0xC0000000, 0xC0100000, 0xC0200000
APPFX = 0x24020088 + 0x2FC0
N = 128
fs = 48000

e.w32(OBJ, VT)
e.w32(VT + 0x54, 0x08046A15)
e.w32(OBJ + 0x18, 3 << 16 | 0 << 8)
e.uc.mem_write(OBJ + 0x1E, struct.pack("<H", 2))
e.uc.mem_write(OBJ + 0x2C, struct.pack("<f", 0.5))
e.uc.mem_write(OBJ + 0x21F, b"\x01")
for off, ptr, floats in ((0x30, LIVE, 192256), (0x4C, STATE, 96256), (0x68, FRZ, 192256)):
    e.w32(OBJ + off, ptr)
    e.w32(OBJ + off + 0x14, floats)
e.w32(BUFS, CTX)


def bpm(v):
    e.uc.mem_write(CTX + 0x18, struct.pack("<f", v))


bpm(120.0)


def buf(addr, l, r):
    e.w32(addr, N)
    e.w32(addr + 4, N)
    e.w32(addr + 8, l)
    e.w32(addr + 12, r)
    e.uc.mem_write(addr + 0x10, b"\x00\x01")


buf(BUS, BUSL, BUSR)
buf(IN, INL, INR)
calls = []
e.stub(0x080548C8, lambda: calls.append("stock"), value=1)
e.stub(0x0806AAC0, lambda: calls.append(("clear", e.arg(0) - OBJ)))
e.stub(0x0804F0D4)
e.stub(0x0804F270, lambda: e.w32(e.arg(2), IN))
e.stub(0x0805F37C, value=BUS)

params = {}


def store(**kv):
    params.update(kv)
    ids = {"type": 0x197, "fb": 0x38, "wand": 0x1D1, "random": 0x1D2, "freeze": 0x1D3, "clock": 0x1D4, "width": 0x1D5, "duck": 0x1D6}
    data = b"".join(struct.pack("<HHI", ids[k], 0, v) for k, v in params.items())
    e.uc.mem_write(ARR, data)
    e.w32(APPFX + 4, ARR)
    e.uc.mem_write(APPFX + 10, struct.pack("<H", len(params)))


def block(x):
    e.uc.mem_write(INL, struct.pack(f"<{N}f", *[v[0] for v in x]))
    e.uc.mem_write(INR, struct.pack(f"<{N}f", *[v[1] for v in x]))
    e.uc.mem_write(BUSL, bytes(4 * N))
    e.uc.mem_write(BUSR, bytes(4 * N))
    calls.clear()
    e.call("munchi_process", OBJ, BUFS, count=50_000_000)
    return (struct.unpack(f"<{N}f", e.uc.mem_read(BUSL, 4 * N)), struct.unpack(f"<{N}f", e.uc.mem_read(BUSR, 4 * N)))


def run(seconds, src=lambda t: (0.0, 0.0)):
    out_l, out_r = [], []
    t0 = run.t
    for b in range(int(seconds * fs / N)):
        l, r = block([src(t0 + b * N + i) for i in range(N)])
        out_l += l
        out_r += r
    run.t += int(seconds * fs / N) * N
    return out_l, out_r


run.t = 0
fails = 0
ENGINE = any("granularDelay" in k for k in e.sym)      # False in a MUNCHI_OFF build (build.sh): Type 1 is "---" = stock delay
MUNCHI_PAGE = [0x197, 0x38, 0x1D1, 0x1D2, 0x1D3, 0x1D4, 0x1D5, 0x1D6]   # slot 1 is Munchi's own now; Motion is slot 2
# the motion's own three come from the fill, which this harness's store does not carry (test_motion.py has the real page)


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def energy(x):
    return sum(v * v for v in x)


# --- registration, defaults, page list
reg = []
e.stub(0x0808C0D8, lambda: reg.append(("list", e.arg(1), e.cstr(e.arg(2)), [e.cstr(e.r32(e.arg(3) + 4 * i)) for i in range(e.r32(e.uc.reg_read(UC_ARM_REG_SP)))])))
e.stub(0x0808C12C, lambda: reg.append(("num", e.arg(1), e.arg(2), e.cstr(e.arg(3)), e.r32(e.uc.reg_read(UC_ARM_REG_SP)), e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4))))
e.w32(STACK, 2)
e.call("munchi_register", 0x24001000, 0x197, 0, 0)
check("registered: Type Delay/Munchi, Wand, Random, Freeze, Clock 1x/1/2x/2x, Width, Duck",
      reg[:7] == [("list", 0x197, "Type:", ["Delay", "Munchi", "Motion", "Relapse", "Confetti"] if ENGINE else ["Delay", "---", "Motion", "Relapse", "Confetti"]), ("num", 0x1D1, 8, "Wand:", 0, 1000), ("num", 0x1D2, 8, "Random:", 0, 1000), ("list", 0x1D3, "Freeze:", ["Off", "On"]),
              ("list", 0x1D4, "Clock:", ["1x", "1/2x", "2x"]), ("list", 0x1D5, "Width:", ["TEMPO", "Mono", "Wide", "Huge"]), ("list", 0x1D6, "Duck:", ["Auto", "Off", "Light", "Heavy"])], reg)
added = []
e.stub(0x08093EF6, lambda: added.append((e.arg(1), e.arg(2))))
e.call("munchi_defaults_first", 0x30005000, 0x32, 400)
e.call("munchi_defaults_last", 0x30005000, 0x35, 1)
check("delay defaults: Type first; Wand 25 %, Random 30 %, Freeze Off, Clock 1x, Width TEMPO, Duck Auto after Ping",
      added[:9] == [(0x197, 0), (0x32, 400), (0x35, 1), (0x1D1, 250), (0x1D2, 300), (0x1D3, 0), (0x1D4, 0), (0x1D5, 0), (0x1D6, 0)] , added)

# page list: store with every delay param, the cell's type from its vtable
e.w32(STORE2, VT2)
e.w32(VT2, 0x30006001)
e.uc.mem_write(0x30006000, b"\x26\x20\x70\x47")          # movs r0,#0x26 ; bx lr
ids = [0x197, 0x32, 0x33, 0x38, 0x0E, 0xCA, 0x34, 0xC9, 0x35, 0x1D1, 0x1D2, 0x1D3, 0x1D4, 0x1D5, 0x1D6]


def page(type_, ids=ids, type_id=0x197):
    e.uc.mem_write(ARR + 0x100, b"".join(struct.pack("<HHI", i, 0, type_ if i == type_id else 7) for i in ids))
    e.w32(STORE2 + 4, ARR + 0x100)
    e.uc.mem_write(STORE2 + 10, struct.pack("<H", len(ids)))
    LIST = 0x30007000
    e.w32(LIST, 0)
    e.call("munchi_list", LIST, STORE2)
    return [e.r16(LIST + 4 + 12 * i) for i in range(e.r32(LIST))]


check("Type Delay page: Type + the stock 7 + Delay knob variant (8 slots), no Munchi controls",
      page(0) == [0x197, 0x32, 0x33, 0x38, 0x0E, 0xCA, 0x34, 0xC9, 0x35], [hex(i) for i in page(0)])
check("Type Munchi page: the 8 slots = Type, Feedback, Wand, Random, Freeze, Clock, Width, Duck" if ENGINE else
      "engine left out: the second Type (\"---\") lists Type and Feedback only", page(1) == (MUNCHI_PAGE if ENGINE else [0x197, 0x38]),
      [hex(i) for i in page(1)])
e.uc.mem_write(0x30006100, b"\x4b\x20\x70\x47")          # a reverb cell (fresh address: Unicorn caches code)
e.w32(VT2, 0x30006101)
rids = [0x198, 0x37, 0x3B, 0x3A, 0x1D7, 0x1D8, 0x1D9, 0x1DA]
check("reverb page, Type Plate: Type + Decay / Predelay / Damping only", page(0, rids, 0x198) == [0x198, 0x37, 0x3B, 0x3A], [hex(i) for i in page(0, rids, 0x198)])
check("reverb page, Type Room: all 8 (Size, Mod, Early, Width added)", page(1, rids, 0x198) == rids, [hex(i) for i in page(1, rids, 0x198)])
e.uc.mem_write(0x30006200, b"\x30\x20\x70\x47")          # some other cell type: untouched
e.w32(VT2, 0x30006201)
check("other FX cells' pages untouched", len(page(1)) == len(ids))

# --- Type Delay: stock
store(type=0, fb=400, wand=250, random=0, freeze=0)
block([(0.0, 0.0)] * N)
check("Type Delay: the stock delay runs, its lines untouched", calls == ["stock"], calls)

if not ENGINE:
    store(type=1, random=0)
    block([(0.0, 0.0)] * N)
    check("engine left out: the second Type (\"---\") runs the stock delay, its lines untouched", calls == ["stock"], calls)
    block([(0.0, 0.0)] * N)
    check("  ... and goes on doing so (rc4 cleared the three lines under stock on every block)", calls == ["stock"], calls)
    store(type=0)
    block([(0.0, 0.0)] * N)
    check("  and going back to Delay clears nothing", calls == ["stock"], calls)
    print("     Munchi's engine is not in this build (MUNCHI_OFF): its own tests are skipped. MUNCHI=1 ./build.sh puts it back.")
    print(f"\n{fails} failure(s)")
    sys.exit(1 if fails else 0)

# --- no bank 2, or not this image's: the engine is up there, so Munchi reads "---" and IS the stock delay (as Confetti)
B2, MODE = 0x08100000, 0x38800B14
b2_head = bytes(e.uc.mem_read(B2, 16))
e.uc.mem_write(B2, bytes(16))                          # the header gone: no payload
e.meter_up()                                           # a boot without it (b2_live keeps its verdict for the boot)
reg.clear()
e.call("munchi_register", 0x24001000, 0x197, 0, 0)
check("no bank 2: the Type list reads Delay / --- / Motion / Relapse / --- (Munchi and Confetti are up there)",
      reg[0] == ("list", 0x197, "Type:", ["Delay", "---", "Motion", "Relapse", "---"]), reg[:1])
entered = [0]
hooks = [e.uc.hook_add(UC_HOOK_CODE, lambda *_: entered.__setitem__(0, entered[0] + 1), begin=e.sym[f] & ~1, end=e.sym[f] & ~1)
         for f in ("munchi_ready", "munchi_block")]
store(type=1, random=0)
seen = []
for _ in range(3):
    out = block([(0.5, 0.5)] * N)
    seen.append(list(calls))
check("no bank 2, Type Munchi: the stock delay runs every block, its lines untouched", seen == [["stock"]] * 3, seen)
check("  ... and nothing of the engine is entered", entered[0] == 0, entered[0])
check("  ... and the slot adds nothing of its own (the bus is what stock left)", max(abs(v) for v in out[0] + out[1]) == 0)
e.w32(MODE, (0x4D32 << 16) | 1)                         # Munchi ran last: a new image, its BBEXTRA.BIN not written yet
seen = []
for _ in range(3):
    block([(0.5, 0.5)] * N)
    seen.append(list(calls))
check("no bank 2 after Munchi ran: the three lines are cleared ONCE, then stock alone",
      seen == [[("clear", 0x30), ("clear", 0x4C), ("clear", 0x68), "stock"], ["stock"], ["stock"]], seen)
for h in hooks:
    e.uc.hook_del(h)
e.uc.mem_write(B2, b2_head)
e.meter_up()
store(type=0)
block([(0.0, 0.0)] * N)

# --- Munchi: an impulse comes back after the note length
store(type=1, random=0)
run(0.6)
check("switching to Munchi: stock not called", calls == [], calls)
imp_l, imp_r = run(2.0, lambda t: (1.0, 1.0) if t == run.t else (0.0, 0.0))
ok = all(math.isfinite(v) for v in imp_l + imp_r)
pk_l = max(range(len(imp_l)), key=lambda i: abs(imp_l[i]))
pk_r = max(range(len(imp_r)), key=lambda i: abs(imp_r[i]))
# Wand 25 % -> division 5 (1/2 of TEMPO's half-note unit) = a quarter note: 24000 samples at 120 BPM, L/R offsets 960/480
check(f"Wand 25 %, 120 BPM: first repeat at {pk_l / 48:.0f} ms left / {pk_r / 48:.0f} ms right (quarter note 500 ms + TEMPO's 20/10 ms stereo offsets)",
      ok and abs(pk_l - 24960) < 200 and abs(pk_r - 24480) < 200, (pk_l, pk_r))
second = max(abs(v) for v in imp_l[pk_l + 20000:pk_l + 28000])
check(f"Feedback 40 %: second repeat lower ({abs(imp_l[pk_l]):.2f} -> {second:.2f})", 0.05 < second < abs(imp_l[pk_l]))
level = abs(imp_l[pk_l])
check(f"output = the delay's level x wet (first repeat {level:.2f} with level 0.5)", 0.2 < level < 0.6, level)

bpm(90.0)
run(1.5)
l, r = run(2.0, lambda t: (1.0, 1.0) if t == run.t else (0.0, 0.0))
pk = max(range(len(l)), key=lambda i: abs(l[i]))
check(f"follows tempo: at 90 BPM the repeat moves to {pk / 48:.0f} ms (667 + 20)", abs(pk - (32000 + 960)) < 300, pk)

bpm(40.0)
run(1.5)
l, r = run(2.0, lambda t: (1.0, 1.0) if t == run.t else (0.0, 0.0))
pk = max(range(len(l)), key=lambda i: abs(l[i]))
check(f"40 BPM: the quarter note is honoured ({pk / 48:.0f} ms = 1500 + 20)", abs(pk - (72000 + 960)) < 400, pk)
store(wand=430)                             # near the middle: the longest division, a bar = 6 s at 40 BPM
l, r = run(4.0, lambda t: (1.0, 1.0) if t == run.t else (0.0, 0.0))
check("40 BPM, a bar-long division (6 s) in a 4 s buffer: clamped, finite, no crash", all(math.isfinite(v) for v in l + r))
store(wand=250)
bpm(120.0)

# --- reverb side, random events, stability
store(wand=800, random=500, fb=600)
noise = lambda t: ((((t * 7919) % 2001) - 1000) / 2000.0, (((t * 104729) % 2001) - 1000) / 2000.0) if t % 48000 < 4800 else (0.0, 0.0)
l, r = run(3.0, noise)
check("Wand 80 % (delay into reverb), Random 50 %: finite, wet, stereo", all(math.isfinite(v) for v in l + r) and energy(l) > 1 and energy(r) > 1)
store(wand=100, random=1000, fb=1000)
l, r = run(4.0, noise)
peak = max(abs(v) for v in l + r)
check(f"Wand 10 %, Random 100 %, Feedback 100 %: bounded (peak {peak:.2f})", math.isfinite(peak) and peak < 8, peak)

# --- freeze
steady = lambda t: ((((t * 7919) % 2001) - 1000) / 2000.0, (((t * 104729) % 2001) - 1000) / 2000.0)
store(wand=250, random=0, fb=0, freeze=0)
run(1.0, steady)
tail_off = energy(run(1.5)[0][48000:])
run(1.0, steady)
store(freeze=1)
run(0.3, steady)
held = energy(run(2.0)[0][48000:])
check(f"Freeze On keeps looping after the send stops (energy {held:.1f} vs {tail_off:.4f} without)", held > 1 and tail_off < 0.01, (held, tail_off))
store(freeze=0)
run(0.5)

# --- 3.1.m controls: Clock, Width, Duck
store(wand=250, random=0, fb=0, freeze=0, clock=2)
bpm(120.0)
run(1.0)
l, r = run(1.0, lambda t: (1.0, 1.0) if t == run.t else (0.0, 0.0))
pk = max(range(len(l)), key=lambda i: abs(l[i]))
check(f"Clock 2x: the quarter-note repeat comes at 2x tempo ({pk / 48:.0f} ms = 250 + 20)", abs(pk - (12000 + 960)) < 200, pk)
store(clock=1)
run(1.5)
l, r = run(1.5, lambda t: (1.0, 1.0) if t == run.t else (0.0, 0.0))
pk = max(range(len(l)), key=lambda i: abs(l[i]))
check(f"Clock 1/2x: repeat at half tempo ({pk / 48:.0f} ms = 1000 + 20)", abs(pk - (48000 + 960)) < 300, pk)
store(clock=0, width=1)
run(1.0)
l, r = run(1.0, lambda t: (1.0, 1.0) if t == run.t else (0.0, 0.0))
check("Width Mono: left and right repeats identical", max(abs(a - b) for a, b in zip(l, r)) < 1e-6)
store(width=3)
run(1.0)
l, r = run(1.0, lambda t: (1.0, 1.0) if t == run.t else (0.0, 0.0))
pl = max(range(len(l)), key=lambda i: abs(l[i])); pr = max(range(len(r)), key=lambda i: abs(r[i]))
check(f"Width Huge: L/R offsets x5 (L {pl / 48:.0f} ms, R {pr / 48:.0f} ms: 500 + 100 / 50)", abs(pl - (24000 + 4800)) < 200 and abs(pr - (24000 + 2400)) < 200, (pl, pr))
store(width=0)


def ducked(duck):
    store(duck=duck, fb=300)
    run(1.0, steady)
    l, _ = run(1.0, steady)
    return energy(l)


steady = lambda t: ((((t * 7919) % 2001) - 1000) / 2000.0, (((t * 104729) % 2001) - 1000) / 2000.0)
e_off, e_heavy = ducked(1), ducked(3)
check(f"Duck Heavy pulls the repeats down under a busy send (energy {e_heavy:.1f} vs {e_off:.1f} with Off)", e_heavy < 0.6 * e_off, (e_heavy, e_off))
store(duck=0)

# --- THE FINGERPRINT: what Munchi plays, to the bit. A fixed run over every control, from a clean start; the digest is
# over every sample Munchi put on the bus and, at the end, the three lines and its words in backup SRAM. It is the same
# for the engine in the cave (rc4) and in bank 2, and for JOEBOX 1 rc4's release image as published, built on another
# machine: so it does not depend on whose compiler, and any change to the sound, or to where the state sits in the
# lines, shows here. A change to the sound that is meant updates FINGERPRINT.
FINGERPRINT = ("5d146c1047a43b26", "e7dff53b990107b1")
clicks = lambda t: (1.0, 0.7) if t % 24000 == 0 else (0.0, 0.0)
bursts = lambda t: steady(t) if t % 48000 < 4800 else (0.0, 0.0)
tone = lambda t: ((((t * 37) % 400) - 200) / 400.0, (((t * 53) % 300) - 150) / 300.0)
silence = lambda t: (0.0, 0.0)
FP_SCRIPT = [                                          # settings, BPM, the send, seconds; Type 1 = Munchi
    (dict(type=0, fb=400, wand=250, random=0, freeze=0, clock=0, width=0, duck=0), 120.0, clicks, 0.05),
    (dict(type=1), 120.0, clicks, 1.1),                                        # Wand 25 %: quarter-note repeats
    (dict(wand=100, random=500, fb=600), 120.0, bursts, 1.0),                  # glitch side, random events
    (dict(wand=800, random=300, fb=500), 120.0, bursts, 1.0),                  # reverb side
    (dict(wand=250, random=0, fb=300, freeze=1), 120.0, steady, 0.3),          # Freeze on ...
    (dict(), 120.0, silence, 0.5),                                             # ... held with the send silent ...
    (dict(freeze=0), 120.0, bursts, 0.3),                                      # ... and off
    (dict(clock=2), 120.0, clicks, 0.5),
    (dict(clock=1), 120.0, clicks, 0.5),
    (dict(clock=0, width=1), 120.0, tone, 0.3),
    (dict(width=3), 120.0, clicks, 0.5),
    (dict(width=0, duck=3, fb=300), 120.0, steady, 0.4),
    (dict(duck=0, fb=900), 120.0, bursts, 0.4),                                # Duck Auto, high feedback
    (dict(fb=400), 90.0, clicks, 0.6),                                         # tempo changes
    (dict(wand=430), 40.0, clicks, 0.6),                                       # a bar at 40 BPM: clamped
    (dict(type=0), 120.0, clicks, 0.1),                                        # type switches: Delay ...
    (dict(type=1, wand=300, random=400), 120.0, bursts, 0.6),                  # ... Munchi afresh ...
    (dict(type=3), 120.0, clicks, 0.2),                                        # ... Relapse ...
    (dict(type=1, wand=700, random=100), 120.0, steady, 0.6),                  # ... Munchi over Relapse's lines
]
rng = e.r32(0x38800B10)
e.w32(0x38800B10, 0)                                   # Munchi's random generator, unseeded: start() seeds it
fp_out, t, fp_blocks = hashlib.sha256(), 0, 0
for kv, tempo, src, seconds in FP_SCRIPT:
    store(**kv)
    bpm(tempo)
    for _ in range(int(seconds * fs / N)):
        l, r = block([src(t + i) for i in range(N)])
        t += N
        if params["type"] == 1:
            fp_out.update(struct.pack(f"<{N}f", *l) + struct.pack(f"<{N}f", *r))
            fp_blocks += 1
fp_mem = hashlib.sha256()
for a, n in ((LIVE, 192256 * 4), (STATE, 96256 * 4), (FRZ, 192256 * 4), (0x38800B10, 12)):
    fp_mem.update(bytes(e.uc.mem_read(a, n)))
got = (fp_out.hexdigest()[:16], fp_mem.hexdigest()[:16])
check(f"the fingerprint: {fp_blocks} blocks of Munchi over every control, bit for bit what it has always played", got[0] == FINGERPRINT[0],
      got[0])
check("  ... and its state in the lines and backup SRAM, byte for byte where it has always been", got[1] == FINGERPRINT[1], got[1])
e.w32(0x38800B10, rng)                                 # the rest of this file as it ran before the fingerprint
bpm(120.0)
store(type=1, wand=250, random=0, fb=300, freeze=0, clock=0, width=0, duck=0)   # as the Duck checks left them

# --- the page rebuilds when Type changes
SCREEN, MSG = 0x30008000, 0x30009000
seen_msgs = []
e.stub(0x080AB900, lambda: seen_msgs.append(e.r16(e.arg(1))))
view = SCREEN + 0x450
e.w32(view + 0x3C, 0)
for k, pid in enumerate((0x197, 0x38, 0x1D1)):
    e.uc.mem_write(view + 0xD4 + k * 0x3D0, struct.pack("<H", pid))


def screen_msg(mid, idx):
    seen_msgs.clear()
    e.uc.mem_write(MSG, struct.pack("<H", mid) + bytes(10) + struct.pack("<h", idx) + bytes(18))
    e.call("fx_screen_msg", SCREEN, MSG)
    return list(seen_msgs)


check("Type knob turned (0x32 on slot 0): the page rebuilds (0x66 follows)", screen_msg(0x32, 0) == [0x32, 0x66], screen_msg(0x32, 0))
check("another knob turned: no rebuild", screen_msg(0x32, 1) == [0x32])
check("other messages pass through alone", screen_msg(0xD4, 0) == [0xD4])
e.uc.mem_write(view + 0xD4, struct.pack("<H", 0x198))
GUI = 0x3000C000
e.w32(0x24002E6C, GUI)
e.uc.mem_write(GUI + 0x280 + 0x38, b"\0\0")
screen_msg(0x32, 1)
check("another knob: no full redraw asked", bytes(e.uc.mem_read(GUI + 0x280 + 0x38, 2)) == b"\0\0")
check("reverb Type knob: rebuild too", screen_msg(0x32, 0) == [0x32, 0x66])
check("Type change asks the GUI for a full clear + redraw (no stale knobs from the other type)", bytes(e.uc.mem_read(GUI + 0x280 + 0x38, 2)) == b"\x01\x01")
e.w32(0x24002E6C, 0)
check("no GUI pointer yet: still rebuilds, no write", screen_msg(0x32, 0) == [0x32, 0x66])

# --- integrity
e.uc.mem_write(STATE, bytes(64))
l, r = run(0.2, noise)
check("state wiped by someone else: Munchi restarts cleanly, no crash", all(math.isfinite(v) for v in l + r))

# --- back to Delay
store(type=0)
block([(0.0, 0.0)] * N)
check("switching back to Delay: the three lines are cleared, then stock runs",
      calls == [("clear", 0x30), ("clear", 0x4C), ("clear", 0x68), "stock"], calls)
block([(0.0, 0.0)] * N)
check("... only once", calls == ["stock"], calls)

# --- cost
store(type=1, wand=250, random=300, fb=400, freeze=0)
run(0.2, noise)
cnt = [0]
h = e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: cnt.__setitem__(0, cnt[0] + 1))
for wand in (250, 800):
    store(wand=wand)
    run(0.05, noise)
    cnt[0] = 0
    block([noise(i) for i in range(N)])
    print(f"     cost at Wand {wand / 10:.0f} %: {cnt[0]} instructions per 128-frame block, {cnt[0] / N:.0f} per frame")
e.uc.hook_del(h)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
