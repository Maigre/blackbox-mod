"""Bench runner: Gate 3b's measurable checks on the unit, unattended (fork-only, like bench/bbusb.py).

    autogate.py [--only NAME,...] [--list] [--out DIR]

Drives the unit the way Thomas's hands did at Gate 3b, and measures as the session did:
  - rows through the parameter mailbox (`bbusb.py set` / `get`, a 37.3.1d+ DEV build): the app's own knob path;
  - pads started / stopped by MIDI note (Pad Note Default = 36 + q on the Global In channel, ch 1), at their Quant;
  - takes from the USB audio (Outs 1-3), the bank and the pad objects by the bounded peek, screenshots (bbshot.py).
Needs: the transport RUNNING (a launch quantized to a bar waits for it; MIDI Start does not move it on these
settings) and B (q 13) = the 2-bar Resam take, pad 1 (q 0) = the 14.015-beat take, as at Gate 3b; the four-pad load
also plays pad 3 (q 2) and pad 15 (q 14), Clip pads with files of 95 832 frames or more (the bench preset SYNTH). Checks
that need the mailbox are skipped (and say so) on a build without it. Every result goes to OUT/results.txt and one line
each to stdout; takes and logs beside it. Read the numbers against notes/bench/2026-10-17-gate3b-part1.md and the
feature doc's §7 (3b-10, 3b-12, 3b-14).
"""
import datetime
import os
import struct
import subprocess
import sys
import time

import numpy as np

BENCH = os.environ.get("BB_BENCH", os.path.dirname(os.path.abspath(__file__)))   # bbusb.py OF THE BUILD ON THE
# UNIT: point BB_BENCH at a copy taken from that build's commit when this worktree has moved on (a bank layout check)
TOOLS = os.path.dirname(os.path.abspath(__file__))   # bbmidi.py, bbshot.py beside it
sys.path.insert(0, BENCH)
import bbusb  # noqa: E402

PY = sys.executable
B, PAD1 = 13, 0
BEAT, BAR = 24000, 96000
MISSES = 0x24013930                  # the sample host's miss counter: an uncached block read as zeros (notes/re/a2)
METER = 0x2405FFD0                   # cpu.c's meter: + 8 sum, + 0x14 n | peak << 16 (per mille), + 0x22 late
LOAD4 = (PAD1, 2, B, 14)             # the four-pad load: pad 1, pad 3, B, pad 15


# ---------------------------------------------------------------- the unit

def run(*args, check=True):
    r = subprocess.run([PY, *args], capture_output=True, text=True, timeout=120)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(args[:3])}: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else r.returncode}")
    return r.stdout


def setrow(q, row, value):
    return run(f"{BENCH}/bbusb.py", "set", f"q{q}", row, str(value)).strip()


def getrow(q, row):
    return run(f"{BENCH}/bbusb.py", "get", f"q{q}", row).strip()


def has_mailbox():
    try:
        getrow(B, "slip")
        return True
    except Exception:
        return False


def note(q):
    run(f"{TOOLS}/bbmidi.py", "note", str(36 + q))


def bank():
    return bbusb.cw_bank()


def pad(q):
    return struct.unpack("<16I", bbusb.peek(bank() + 0x48, 64))[q]


def slots(q):
    p = pad(q)
    if not p:
        return []
    s = bbusb.peek(p + 0x30, 448)
    return [dict(active=s[0x70 * k], done=s[0x70 * k + 1], pos=struct.unpack_from("<q", s, 0x70 * k + 8)[0],
                 delay=struct.unpack_from("<i", s, 0x70 * k + 0x20)[0], step=struct.unpack_from("<I", s, 0x70 * k + 0x34)[0],
                 launch=s[0x70 * k + 0x3C]) for k in range(4)]


def sounding(q):
    """playing for real: an active, not done segment with no start delay left (a pending launch is not playing)"""
    return any(s["active"] and not s["done"] and s["delay"] <= 0 for s in slots(q))


def start(q, bars=3):
    if not sounding(q):
        note(q)
    t0 = time.time()
    while time.time() - t0 < bars * 2.0 + 1.0:
        if sounding(q):
            return
        time.sleep(0.05)
    note(q)                                           # take the pending launch back
    raise RuntimeError(f"q{q} did not start within {bars} bars: is the transport running?")


def stop(q):
    if sounding(q) or any(s["active"] and not s["done"] for s in slots(q)):
        note(q)
    t0 = time.time()
    while time.time() - t0 < 6 and any(s["active"] and not s["done"] for s in slots(q)):
        time.sleep(0.05)


def setrows(q, *pairs):
    for row, v in pairs:
        setrow(q, row, v)


def record(path, secs):
    run(f"{BENCH}/bbusb.py", "record", str(secs), path)


def recording(path, secs):
    """a take in the background, to change something while it records: (the process, when it was started)"""
    return subprocess.Popen([PY, f"{BENCH}/bbusb.py", "record", str(secs), path], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL), time.time()


def misses():
    return bbusb.word(MISSES)


def load(secs):
    """the engine's load over SECS, without TOOLS: cleared first as TOOLS' draw clears it (sum, n and peak; late is
    shared with bank 2's check byte, so it is counted from where it stands)"""
    bbusb.poke(METER + 8, 0); bbusb.poke(METER + 0x14, 0)
    m0 = bbusb.peek(METER, 0x24); time.sleep(secs); m1 = bbusb.peek(METER, 0x24)
    (s0,), (n0, _), (s1,), (n1, peak) = (struct.unpack_from(f, m, a) for f, m, a in
                                         (("<I", m0, 8), ("<HH", m0, 0x14), ("<I", m1, 8), ("<HH", m1, 0x14)))
    if n1 <= n0 or n0 > 400:
        return f"UNREAD (n {n0} -> {n1}: TOOLS drew during the window, or the clear did not take)"
    return f"mean {(s1 - s0) / (n1 - n0) / 10:.1f} % peak {peak / 10:.1f} % late +{m1[0x22] - m0[0x22]} ({n1 - n0} blocks)"


def shot(path):
    run(f"{TOOLS}/bbshot.py", path)


def wav(path):
    s = np.asarray(bbusb.read_wav(path), float)
    return s, bbusb.first_onset(s[:, 2])


# ---------------------------------------------------------------- measures (as in the session)

def shift(base, new):
    out = run(f"{BENCH}/bbusb.py", "shift", base, new)
    return int(out.split("moved")[1].split()[0])


def periodic(path, lag, n=200000):
    s, c = wav(path); x = s[:, 0]; n = min(n, len(x) - c - lag)
    return float(np.abs(x[c:c + n] - x[c + lag:c + lag + n]).max())


def recurring_steps(path, period, top=3, skip=0):
    """the largest steps found at the same place in every period after the first `skip` (the minimum over periods:
    one period without the step, such as a first bar still playing the previous setting, hides it)"""
    s, c = wav(path); d = np.abs(np.diff(s[:, 0])); n = (len(d) - c) // period
    rows = np.stack([d[c + k * period:c + (k + 1) * period] for k in range(skip, n)])
    rec = rows.min(axis=0); idx = np.argsort(rec)[-top:][::-1]
    return [(int(i), float(rec[i])) for i in idx], float(np.median(d))


def repeat_from(path, period, block=480):
    """where the take turns periodic over `period` for good, in samples: the end of the last block that differs from
    the same block a period later (against its own level)"""
    x = wav(path)[0][:, 0]; n = (len(x) - period) // block
    e = np.abs(x[:n * block] - x[period:period + n * block]).reshape(n, block).max(1)
    differs = np.nonzero(e > 0.2 * np.abs(x[:n * block]).reshape(n, block).max(1) + 1e-4)[0]
    return int((differs[-1] + 1) * block) if len(differs) else 0


def zero_run(path):
    """the longest run of exact zeros on Out 1 (both sides) after the first click, and where: an uncached block plays
    as zeros"""
    s, c = wav(path); c = c or 0
    z = np.r_[0, ((s[c:, 0] == 0) & (s[c:, 1] == 0)).astype(np.int8), 0]
    starts, ends = np.nonzero(np.diff(z) == 1)[0], np.nonzero(np.diff(z) == -1)[0]
    if not len(starts):
        return 0, None
    k = int(np.argmax(ends - starts))
    return int(ends[k] - starts[k]), int(starts[k] + c)


def audio_clock(path, proc, secs=2.0):
    """the host time of a background take's first frame: the earliest (now - frames on file) while it grows
    (arecord writes each period just after capturing it; a 44-byte header, 18 bytes a frame)"""
    best, t_end = None, time.time() + secs
    while time.time() < t_end and proc.poll() is None:
        try:
            n = (os.path.getsize(path) - 44) // 18
        except OSError:
            n = 0
        if n > 0:
            t = time.time() - n / 48000
            best = t if best is None else min(best, t)
        time.sleep(0.002)
    return best


# ---------------------------------------------------------------- checks

CHECKS = {}


def check(name, mailbox=True):
    def deco(f):
        CHECKS[name] = (f, mailbox)
        return f
    return deco


@check("ref")
def c_ref(o):
    for row, v in (("region", "File"), ("slip", 0), ("looplen", "Off"), ("fit", "Off"), ("fade", 0), ("sync", "1/4"),
                   ("quant", "1 bar"), ("beats", 0)):           # Beat Count 0 = Auto
        setrow(B, row, v)
    start(B); time.sleep(4.5)
    record(f"{o}/b_file.wav", 12)
    return f"B File reference; 2-bar periodic {periodic(f'{o}/b_file.wav', 2 * BAR):.5f}"


@check("region")
def c_region(o):
    setrow(B, "lps", 6072); setrow(B, "lpe", 102072); setrow(B, "region", "Loop"); time.sleep(4.5)
    record(f"{o}/loop.wav", 12)
    setrow(B, "region", "File"); time.sleep(4.5)
    record(f"{o}/file.wav", 12)
    return (f"Loop {shift(f'{o}/b_file.wav', f'{o}/loop.wav')} (expect -6072), "
            f"File {shift(f'{o}/b_file.wav', f'{o}/file.wav')} (expect 0)")


@check("auto")
def c_auto(o):
    setrow(B, "region", "Auto"); time.sleep(4.5)
    record(f"{o}/auto.wav", 12)
    return f"Auto {shift(f'{o}/b_file.wav', f'{o}/auto.wav')} (expect -6072)"


@check("settle")
def c_settle(o):
    """Loop Len taken ~0.3 s after the value rests (37.3.1: 7 polls), Off at once"""
    setrow(B, "region", "File"); setrow(B, "looplen", "Off"); time.sleep(1.0)
    b = bank(); setrow(B, "looplen", "1/4"); t0 = time.time(); taken = None   # from the mailbox's done (set waits)
    while time.time() - t0 < 2.0:
        if bbusb.peek(b + 0x600 + B, 1)[0] == 3:
            taken = time.time() - t0; break
        time.sleep(0.005)
    time.sleep(2.0); record(f"{o}/ll4.wav", 12)
    setrow(B, "looplen", "Off"); t1 = time.time(); off = None
    while time.time() - t1 < 1.0:
        if bbusb.peek(b + 0x600 + B, 1)[0] == 0:
            off = time.time() - t1; break
        time.sleep(0.005)
    return (f"1/4 taken after {taken if taken is None else round(taken, 3)} s (expect ~0.30-0.34 + the set), "
            f"Off after {off if off is None else round(off, 3)} s (expect at once); 1/4 loop 1-beat periodic "
            f"{periodic(f'{o}/ll4.wav', BEAT, 150000):.4f}")


@check("fit")
def c_fit(o):
    setrow(B, "lps", 6072); setrow(B, "lpe", 95744); setrow(B, "region", "Loop"); setrow(B, "fit", "Off")
    time.sleep(4.5); record(f"{o}/fit0.wav", 12)
    setrow(B, "fit", "Auto (Bars)"); time.sleep(4.5); record(f"{o}/fit1.wav", 12)
    fitline = run(f"{BENCH}/bbusb.py", "fit").strip().splitlines()
    res = [f"fit1 1-bar periodic {periodic(f'{o}/fit1.wav', BAR):.5f}", *[l for l in fitline if "row 3 col 1" in l]]
    for name, beats in (("3 beats", 3), ("6 beats", 6)):
        setrow(B, "fit", name); time.sleep(5.0); record(f"{o}/fit{beats}.wav", 16)
        res.append(f"{name}: {beats}-beat periodic {periodic(f'{o}/fit{beats}.wav', beats * BEAT, 150000):.5f}")
    setrow(B, "fit", "Off")
    return "; ".join(res)


@check("fade")
def c_fade(o):
    setrow(B, "fit", "Off"); setrow(B, "fade", 0); time.sleep(4.5); record(f"{o}/fade0.wav", 12)
    setrow(B, "fade", 50); time.sleep(4.5); record(f"{o}/fade5.wav", 12)
    # skip=1: Fit 6 beats -> Off can land after the 4.5 s wait (run-8: the first bar had no seam, and hid it)
    s0, m0 = recurring_steps(f"{o}/fade0.wav", BAR, skip=1); s5, m5 = recurring_steps(f"{o}/fade5.wav", BAR, skip=1)
    setrow(B, "fade", 0)
    return f"recurring steps 0 %: {s0} (median {m0:.4f}); 5 %: {s5} (median {m5:.4f}) — the seam's should be gone"


@check("fa_probe", mailbox=False)
def c_fa(o):
    """F-a: pad 1's slots around its wraps while it plays slipped (as set by hand, or by the mailbox if present)"""
    if has_mailbox():                                 # the preset's rows first: load4 leaves pad 1 on a short region
        setrows(PAD1, ("looplen", "Off"), ("fade", 0), ("sync", "1/16"), ("lps", 0), ("lpe", 336359), ("region", "Auto"),
                ("slip", "-0.645"), ("fit", "Auto (Bars)"))
    stop(B); start(PAD1)
    p = pad(PAD1); rows = []; t0 = time.time()
    proc = subprocess.Popen([PY, f"{BENCH}/bbusb.py", "record", "20", f"{o}/fa.wav"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        while time.time() - t0 < 18:
            s = bbusb.peek(p + 0x30, 448); t = time.time() - t0
            for k in range(4):
                q = 0x70 * k
                rows.append((t, k, s[q], s[q + 1], struct.unpack_from("<q", s, q + 8)[0], struct.unpack_from("<i", s, q + 0x20)[0],
                             struct.unpack_from("<i", s, q + 0x24)[0], struct.unpack_from("<i", s, q + 0x28)[0],
                             struct.unpack_from("<I", s, q + 0x34)[0], s[q + 0x3C]))
    finally:                                          # a peek timing out (F-i) left pad 1 playing under llr (run-9)
        proc.wait(); stop(PAD1)
    with open(f"{o}/fa_slots.csv", "w") as f:
        f.write("t,slot,active,done,pos,delay,fadein,countdown,step,launch\n")
        f.writelines(",".join(f"{v:.4f}" if isinstance(v, float) else str(v) for v in r) + "\n" for r in rows)
    steps, med = recurring_steps(f"{o}/fa.wav", 336000)
    wraps = sorted({r[0] for r in rows if r[8] == 0 and r[2] and not r[3]})
    return f"{len(rows) // 4} samples, step-0 segments seen at {len(wraps)} samples; recurring steps {steps} (median {med:.4f})"


@check("llr")
def c_llr(o):
    """3b-10: Loop Len 1/4 over a region with Slip (after ref: b_file.wav): the window keeps the region's grid and
    Slip's shift, and repeats the beat that was playing when it was taken"""
    setrows(B, ("looplen", "Off"), ("fit", "Off"), ("fade", 0), ("sync", "1/4"), ("quant", "1 bar"), ("beats", 0),
         ("lps", 6072), ("lpe", 102072), ("region", "Auto"), ("slip", "+0.060"))
    stop(PAD1); start(B); time.sleep(4.5)
    record(f"{o}/slip60.wav", 12)                     # the control: Slip at work, no Loop Len
    b = bank(); proc, t_rec = recording(f"{o}/llt.wav", 12); t_audio = audio_clock(f"{o}/llt.wav", proc)
    time.sleep(max(0.0, 5.0 - (time.time() - t_rec)))
    setrow(B, "looplen", "1/4"); t_take = None
    while time.time() - t_rec < 9.0:
        if bbusb.peek(b + 0x600 + B, 1)[0] == 3:
            t_take = time.time(); break
        time.sleep(0.005)
    proc.wait(); time.sleep(1.0); record(f"{o}/llr.wav", 12)
    origin = struct.unpack("<i", bbusb.peek(b + 0x5C0 + 4 * B, 4))[0]; forced = bbusb.peek(b + 0x610, 16)[B]
    setrows(B, ("looplen", "Off"), ("slip", 0))
    t0 = repeat_from(f"{o}/llt.wav", BEAT)
    if t_take is None or t_audio is None:
        seen = f"not timed (taken {t_take is not None}, audio clock {t_audio is not None})"
    else:
        at = round((t_take - t_audio) * 48000)
        seen = (f"taken at sample {at}, the repeat from {t0}: {'IN' if t0 <= at < t0 + BEAT else 'NOT in'} the "
                f"repeated beat ({at - t0} into it)")
    return (f"Slip control {shift(f'{o}/b_file.wav', f'{o}/slip60.wav')} (expect -7572), 1-beat periodic "
            f"{periodic(f'{o}/slip60.wav', BEAT, 150000):.4f}; Loop Len 1/4 {shift(f'{o}/b_file.wav', f'{o}/llr.wav')} "
            f"(expect -7572), 1-beat periodic {periodic(f'{o}/llr.wav', BEAT, 150000):.4f}; origin {origin} ticks, "
            f"forced {forced} (expect 0); {seen}")


@check("sd")
def c_sd(o):
    """3b-12: SD misses over 30 s of each case (no more than B on File; Gate 3: 0 in normal play), and no dropout - a
    run of exact zeros on Out 1 - on the step after Loop Len Off"""
    res = []

    def over(name, secs=30):
        m = misses(); time.sleep(secs); res.append(f"{name} {misses() - m}")
    setrows(B, ("looplen", "Off"), ("slip", 0), ("fit", "Off"), ("fade", 0), ("sync", "1/4"), ("region", "File"))
    stop(PAD1); start(B); time.sleep(4.5); over("B File")
    setrows(B, ("lps", 6072), ("lpe", 102072), ("region", "Loop"), ("slip", "+0.060")); time.sleep(4.5)
    over("Region Loop Slip +0.060")
    setrow(B, "lpe", 95832)                           # 3b-17's region: 3.74 beats, folding mid-step
    for fade, slip in ((50, 0), (250, 0), (50, "+0.060"), (250, "+0.060")):
        setrows(B, ("fade", fade), ("slip", slip)); time.sleep(4.5)
        over(f"Loop Fade {fade / 10:g} % Slip {slip}")
    setrows(B, ("fade", 0), ("slip", 0)); stop(B)
    setrows(PAD1, ("looplen", "Off"), ("slip", 0), ("fit", "Off"), ("fade", 0), ("sync", "1/4"), ("region", "File"))
    start(PAD1); time.sleep(4.5); record(f"{o}/p1.wav", 8)      # the reference: pad 1's own zeros
    m = misses(); setrow(PAD1, "looplen", "1/16"); time.sleep(10)
    proc, _ = recording(f"{o}/llo.wav", 14); time.sleep(3)
    setrow(PAD1, "looplen", "Off"); time.sleep(8); setrow(PAD1, "looplen", "1/16"); proc.wait(); time.sleep(3)
    res.append(f"pad 1 Loop Len 1/16, Off, 1/16 {misses() - m}")
    setrow(PAD1, "looplen", "Off"); stop(PAD1)
    (z1, at), (z0, _) = zero_run(f"{o}/llo.wav"), zero_run(f"{o}/p1.wav")
    res.append(f"longest exact-zero run on Out 1 {z1} samples (at {at}; Off at ~3 s), {z0} without Loop Len")
    return "misses: " + "; ".join(res)


@check("load4")
def c_load4(o):
    """3b-14's four-pad load: four pads over 3.74-beat regions (rate 0.935 at Fit Auto) at Fit Off, Fit Auto, then
    Loop Fade 5 %: the fitted pads a few % over Fit Off, no late block; then no fault or watchdog record"""
    for q in LOAD4:
        stop(q)
    res = [f"idle {load(15)}"]
    for q in LOAD4:
        setrows(q, ("looplen", "Off"), ("slip", 0), ("fit", "Off"), ("fade", 0), ("sync", "1/4"), ("quant", "1 bar"),
             ("beats", 0), ("lps", 6072), ("lpe", 95832), ("region", "Loop"))
    for q in LOAD4:
        start(q)
    time.sleep(4.5); res.append(f"four at Fit Off {load(20)}")
    for q in LOAD4:
        setrow(q, "fit", "Auto (Bars)")
    time.sleep(4.5); res.append(f"Fit Auto {load(20)}")
    fit = run(f"{BENCH}/bbusb.py", "fit")
    rates = [l.split("+0x1f0 ")[1].split()[0] for q in LOAD4 for l in fit.splitlines()
             if l.startswith(f"cell row {q >> 2} col {q & 3}:") and "+0x1f0 " in l]
    for q in LOAD4:
        setrow(q, "fade", 50)
    time.sleep(4.5); res.append(f"+ Loop Fade 5 % {load(20)}")
    for q in LOAD4:
        stop(q)
    crash = run(f"{BENCH}/bbusb.py", "crash")
    with open(f"{o}/crash.txt", "w") as f:
        f.write(crash)
    res += [f"rates {', '.join(rates)} (expect 0.935)",
            f"fault {'RECORD' if 'FAULT:' in crash else 'none'}, watchdog {'RECORD' if 'WATCHDOG:' in crash else 'none'}"]
    return "; ".join(res)


@check("screen", mailbox=False)
def c_screen(o):
    shot(f"{o}/screen.png")
    return "screenshot (whatever screen is up)"


# ---------------------------------------------------------------- main

def main(argv):
    if "--list" in argv:
        for n, (f, mb) in CHECKS.items():
            print(f"{n:9} {'mailbox' if mb else '       '}  {(f.__doc__ or '').strip().splitlines()[0] if f.__doc__ else ''}")
        return
    only = argv[argv.index("--only") + 1].split(",") if "--only" in argv else list(CHECKS)
    out = argv[argv.index("--out") + 1] if "--out" in argv else \
        os.path.join(os.environ.get("BB_AUTO", "out/autogate"), f"{datetime.datetime.now():%Y%m%d-%H%M%S}")
    os.makedirs(out, exist_ok=True)
    mb = has_mailbox()
    for q in (B, PAD1):                               # a run cut short may have left a pad playing
        try:
            stop(q)
        except Exception:
            pass
    with open(f"{out}/results.txt", "w") as res:
        head = f"# autogate {datetime.datetime.now():%F %T}; mailbox {'yes' if mb else 'NO (checks needing it skipped)'}"
        print(head); res.write(head + "\n")
        for name in only:
            f, needs = CHECKS[name]
            if needs and not mb:
                line = f"{name}: SKIPPED (no mailbox on this build)"
            else:
                try:
                    line = f"{name}: {f(out)}"
                except Exception as e:                # one check failing never stops the run
                    line = f"{name}: ERROR {e}"
            print(line, flush=True); res.write(line + "\n"); res.flush()
        for q in (B, PAD1):
            try:
                stop(q)
            except Exception:
                pass


if __name__ == "__main__":
    main(sys.argv[1:])
