"""Bench tool: talk to a Blackbox running this fork over the USB cable on its POWER jack (src/usbdev.c).

The power jack is a USB device (1209:0003, "Blackbox"): class-compliant MIDI, USB audio (Outs 1-3 as 6 channels of
24-bit / 48 kHz) and, on a DEV build only (no RELEASE=1), a debug peek / poke of the unit's memory. Fork-only tool:
never part of a feat/* branch or a PR.

  bbusb.py info                         is it there, which build (dev builds answer a peek)
  bbusb.py peek ADDR [BYTES]            words at ADDR (hex), up to 64 bytes a request
  bbusb.py poke ADDR VALUE              write one 32-bit word (hex) - DEV build; you can break the running unit
  bbusb.py sdram                        free SDRAM between the two pool pointers (notes/re/x2)
  bbusb.py crash                        src/fault.c's records: reset cause, fault / watchdog PC, the trail into the reset
  bbusb.py catch [SECONDS]              boot loop: read those records at every boot as soon as the unit enumerates
  bbusb.py slip                         Clip Window bank: polled Slip per pad, latched slots (src/clipwin.c)
  bbusb.py knob [SECONDS]               the Slip knob's last turn event: counts, accelerator speed, the detent on 0;
                                        with SECONDS, sampled while you turn: each change, then the speeds seen
  bbusb.py fit                          Fit per pad: the row as taken, fitted or not, Auto's beats, the pad's step
                                        fields (+0x1f0 rate, +0x204, +0x208, +0x210, +0x230), and its Loop Fade
  bbusb.py record SECONDS FILE.wav      capture the 6 USB channels (arecord)
  bbusb.py offsets FILE.wav [A B]       onset offsets between channel A and B (default 0 = Out1 L, 2 = Out2 L)
  bbusb.py shift BASE.wav NEW.wav [BPM] how far Out 1 moved between two takes, aligned on the metronome (Out 2)
  bbusb.py note NOTE [VEL]              send a note on (then off 100 ms later) on the Global In channel (amidi)
  bbusb.py set CELL ROW VALUE           a pad's row as its knob sets it (the parameter mailbox, DEV build: src/usbdev.c):
                                        CELL = R,C (rows from the bottom) or qN; ROW = slip, region, looplen, fit, fade,
                                        lps, lpe, sync, quant, beats, loopmode, launch, padmode; VALUE = a number, a
                                        list row's name ("1/4", "Loop") or Slip as beats.ticks ("-0.645")
  bbusb.py get CELL ROW                 that row from the pad's store (the same mailbox)

Permissions: the peek / poke needs write access to the device node. Once, as root:
  echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1209", ATTR{idProduct}=="0003", MODE="0660", GROUP="plugdev"' \
    > /etc/udev/rules.d/60-blackbox-mod.rules && udevadm control --reload && udevadm trigger
Audio and MIDI go through ALSA and need nothing.
"""
import os
import struct
import subprocess
import sys
import time

VID, PID = 0x1209, 0x0003


def dev():
    import usb.core
    d = usb.core.find(idVendor=VID, idProduct=PID)
    if d is None:
        sys.exit("no Blackbox (1209:0003) on USB: is the power jack cabled to this machine, and the mod installed?")
    return d


def peek(addr, n=4):
    """n bytes at addr. The unit reads aligned words inside one memory at a time (src/usbdev.c, F-j), so the requests
    are aligned here and none runs past what was asked; a stall means there is nothing readable there."""
    d, start = dev(), addr & ~3
    end, out = addr + n, b""
    while start + len(out) < end:
        a = start + len(out)
        got = bytes(d.ctrl_transfer(0xC0, 0x50, a & 0xFFFF, a >> 16, min(64, (end - a + 3) & ~3)))
        if not got:
            break
        out += got
    return out[addr - start:addr - start + n]


def word(addr):
    return struct.unpack("<I", peek(addr, 4))[0]


def poke(addr, value):
    d = dev()
    d.ctrl_transfer(0x40, 0x51, addr & 0xFFFF, addr >> 16, None)
    d.ctrl_transfer(0x40, 0x52, value & 0xFFFF, (value >> 16) & 0xFFFF, None)


RSR_BITS = {17: "CPU", 19: "D1", 20: "D2", 21: "BOR(brownout)", 22: "PIN", 23: "POR(power-on)", 24: "SOFTWARE",
            26: "IWDG", 28: "WWDG(window watchdog)", 30: "LOWPOWER"}


def print_crash():
    """src/fault.c's records in backup SRAM (they survive a reset; the boot record is latched once per boot)."""
    def words(addr, n):
        return struct.unpack(f"<{n}I", peek(addr, 4 * n))
    boot = words(0x38800FD8, 4)
    if boot[0] == 0x31544F42:
        causes = [name for bit, name in RSR_BITS.items() if boot[1] >> bit & 1]
        print(f"boot: #{boot[2]} since records cleared, reset cause RSR {boot[1]:#010x} = {', '.join(causes) or '?'}")
    else:
        print(f"boot record: none (magic {boot[0]:#x})")
    f = words(0x38800F78, 16)
    if f[0] == 0x31544C46:
        print(f"FAULT: PC {f[1]:#010x} LR {f[2]:#010x} xPSR {f[3]:#010x} CFSR {f[4]:#010x} HFSR {f[5]:#010x} "
              f"MMFAR {f[6]:#010x} BFAR {f[7]:#010x} EXC_RETURN {f[8]:#010x} SP {f[9]:#010x} ok {f[10]} "
              f"r0-r3 {f[11]:#x} {f[12]:#x} {f[13]:#x} {f[14]:#x} lowest-SP {f[15]:#010x}")
    else:
        print(f"fault record: none (magic {f[0]:#x})")
    w = words(0x38800FB8, 8)
    if w[0] == 0x31474457:
        print(f"WATCHDOG: PC {w[1]:#010x} LR {w[2]:#010x} xPSR {w[3]:#010x} stamp ages A {w[4]} B {w[5]} "
              f"(> 3749 = that task stopped) now {w[6]} CR|SR {w[7]:#010x}")
    else:
        print(f"watchdog record: none (magic {w[0]:#x})")
    sp = words(0x38800FE8, 2)
    aud, gui = words(0x388003A4, 4), words(0x388003B4, 4)
    print(f"delay-dispatch SP lowest {sp[0]:#010x} last {sp[1]:#010x}; trail into the last reset: "
          f"audio {' '.join(f'{x:08x}' for x in aud)} | gui {' '.join(f'{x:08x}' for x in gui)}")
    b2 = words(0x388003C8, 3)
    print(f"bank-2 words {b2[0]:#010x} {b2[1]:#010x} {b2[2]:#010x}")


def read_wav(path):
    """a capture as floats, frames x channels (S24_3LE from `record`, or 16-bit)"""
    import numpy as np
    import wave
    w = wave.open(path)
    raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.uint8)
    ch, width = w.getnchannels(), w.getsampwidth()
    if width == 2:
        return np.frombuffer(raw.tobytes(), dtype="<i2").reshape(-1, ch).astype(float) / 32768
    f = raw.reshape(-1, ch, width).astype(np.int32)
    x = f[..., -3] | f[..., -2] << 8 | f[..., -1] << 16
    return np.where(x & 0x800000, x - 0x1000000, x).astype(float) / 0x800000


def first_onset(s, skip=1000):
    """the first click that is whole: one in the first `skip` samples may have started before the take (Gate 2: a click
    96 samples in skewed the alignment by 16)"""
    import numpy as np
    e = np.abs(s)
    if e.max() < 1e-3:
        return None
    hits = np.nonzero(e[skip:] > 0.3 * e.max())[0]
    return int(hits[0]) + skip if len(hits) else None


CW_MAGIC = 0x43574E41            # "CWNA": src/clipwin.h's cw_bank layout this tool reads
GUI_MS = 0x2402EEE0              # the GUI's ms clock (clipwin.c GUI_MS)


def cw_bank():
    """the Clip Window bank in SDRAM (src/clipwin.h): master.c's block (its pointer in backup SRAM) + 0x83900"""
    mem = word(0x38800F70)
    if not 0xC0000000 <= mem < 0xC4000000:
        sys.exit(f"no SDRAM block (Prism pointer {mem:#x})")
    return mem + 0x83900


# The parameter mailbox (src/usbdev.c, DEV builds): cw_bank + 0xF00. magic, seq, op/row/col, id, value; the unit writes
# done, result and the store's value after. Applied in the GUI task as a knob turn's 0x6e message is (SetCellParam).
MBOX_MAGIC = 0x3158424D          # "MBX1"
MBOX_ROWS = {"padmode": 0x8B, "loopmode": 0x8D, "quant": 0x47, "lps": 0x91, "loopstart": 0x91, "lpe": 0x92,
             "loopend": 0x92, "launch": 0x93, "sync": 0x94, "beats": 0xD2, "beatcount": 0xD2, "fade": 0xFA,
             "loopfade": 0xFA, "region": 0x1C8, "slip": 0x1C9, "looplen": 0x1CA, "fit": 0x1CB}
MBOX_RESULT = {0: "done", -1: "unknown op", -2: "not a pad", -3: "not a row the mailbox sets", -4: "out of range"}
PARAM_TABLE = 0x2401F4FC         # the parameter table's pointer: 0x1c bytes an id (type, label, names, count, min, max)


def cstr(addr, n=32):
    return peek(addr, n).split(b"\0")[0].decode("latin-1")


def param(pid):
    """the stock table's entry for pid: (label, type, list names or None, min, max)"""
    e = peek(word(PARAM_TABLE) + pid * 0x1C, 0x1C)
    typ, label, names, count, lo, hi = e[2], *struct.unpack_from("<IIIii", e, 4)
    lst = [cstr(word(names + 4 * i)) for i in range(count)] if names and 0 < count < 64 else None
    return (cstr(label) if label else hex(pid)), typ, lst, lo, hi


def cell(text):
    if text.lower().startswith("q"):
        q = int(text[1:])
        return q >> 2, q & 3
    r, c = (int(x) for x in text.split(","))
    return r, c


def mailbox(op, row, col, pid, value=0):
    mb = cw_bank() + 0xF00
    poke(mb + 8, op | row << 8 | col << 16)
    poke(mb + 0xC, pid)
    poke(mb + 0x10, value & 0xFFFFFFFF)
    poke(mb, MBOX_MAGIC)
    seq = (max(word(mb + 4), word(mb + 0x14)) + 1) & 0xFFFFFFFF
    poke(mb + 4, seq)                                      # last: the request is whole
    t0 = time.time()
    while word(mb + 0x14) != seq:
        if time.time() - t0 > 2:
            sys.exit("no answer from the mailbox in 2 s (a release build, or the GUI task is not running?)")
        time.sleep(0.01)
    result, back = struct.unpack("<ii", peek(mb + 0x18, 8))
    return result, back


def show(pid, v):
    label, typ, lst, lo, hi = param(pid)
    if lst and 0 <= v < len(lst):
        return f"{label} {lst[v]} ({v})"
    if pid == 0x1C9:
        return f"{label} {'-' if v < 0 else '+'}{abs(v) // 960}.{abs(v) % 960:03d} ({v} ticks)"
    return f"{label} {v}"


def knob_state(bank):
    """(counts, speed, zero_at, zero_dir, zero_slow, now): cw_bank + 0x720 i16 knob_counts, u8 knob_speed; + 0x4b8 u32
    zero_at, i8 zero_dir, u8 zero_slow (cw_turn, v3: 1 = the arrival was slow, held ZERO_DETENT_SLOW_MS); the GUI
    clock"""
    zero_at, zero_dir, zero_slow = struct.unpack("<IbB2x", peek(bank + 0x4B8, 8))
    counts, speed = struct.unpack("<hBx", peek(bank + 0x720, 4))
    return counts, speed, zero_at, zero_dir, zero_slow, word(GUI_MS)


def alsa_card():
    out = subprocess.run(["arecord", "-l"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "Blackbox" in line and line.startswith("card "):
            return line.split()[1].rstrip(":")
    sys.exit("no ALSA capture device named Blackbox (arecord -l)")


def main(argv):
    if not argv:
        sys.exit(__doc__)
    cmd, args = argv[0], argv[1:]
    if cmd == "info":
        d = dev()
        print(f"found {VID:04x}:{PID:04x} bus {d.bus} address {d.address}")
        try:
            print(f"dev build: peek works (word at 0x08040000 = {word(0x08040000):#010x})")
        except Exception as e:  # a release build stalls the vendor request
            print(f"release build (or no permission for the peek): {e}")
    elif cmd == "peek":
        addr, n = int(args[0], 16), int(args[1], 0) if len(args) > 1 else 4
        data = peek(addr, n)
        for i in range(0, len(data), 16):
            words = struct.unpack(f"<{len(data[i:i + 16]) // 4}I", data[i:i + 16])
            print(f"{addr + i:#010x}: " + " ".join(f"{w:08x}" for w in words))
    elif cmd == "poke":
        poke(int(args[0], 16), int(args[1], 16))
    elif cmd == "sdram":
        low, high = word(0x2400008C), word(0x24000088)
        print(f"permanent pointer {low:#010x}, temporary pointer {high:#010x}, free {high - low:,} B")
    elif cmd == "slip":
        bank = cw_bank()
        hdr = peek(bank, 8 + 64 + 64 + 16)
        magic, scan = struct.unpack_from("<II", hdr)
        if magic != CW_MAGIC:
            # master_alloc clears only the magic at each boot, and SDRAM keeps the rest through a reset: without the
            # bank set up this boot, every field below is a previous boot's, not live
            sys.exit(f"cw_bank magic {magic:#010x}, not {CW_MAGIC:#010x} (CWNA, Loop Fade on): "
                     + ("the bank is not set up this boot - no matching bank 2 (D-018: TOOLS shows a '!'); its Slip "
                        "rows, pad pointers and latched slots are a previous boot's" if not magic else "another layout"))
        slip = struct.unpack_from("<16i", hdr, 8)
        pads = struct.unpack_from("<16I", hdr, 72)
        valid = hdr[136:152]
        print(f"bank {bank:#010x} magic {magic:#010x} scan {scan}")
        for q in range(16):
            if slip[q] or valid[q]:
                print(f"cell row {q >> 2} col {q & 3}: Slip row {slip[q]:+5} ticks (+ = ahead)  pad object {pads[q]:#010x}  "
                      f"latched slots {valid[q]:04b}")
    elif cmd == "knob":
        # src/clipwin_b2.c cw_turn (from clipwin.c's clipwin_turn) leaves each Slip turn event's counts and the stock
        # accelerator's speed m (1 .. 6, about 8/7 x the counts per ms) in cw_bank: which speeds a hand makes, against
        # the gain curve (KNOB_GAIN, KNOB_GAIN_STEP, KNOB_TOP there), and whether each arrival on 0 was slow (the long
        # hold, ZERO_DETENT_SLOW_MS). Read only: nothing is written to the unit.
        bank = cw_bank()
        magic = word(bank)
        if magic != CW_MAGIC:
            sys.exit(f"cw_bank magic {magic:#010x}, not {CW_MAGIC:#010x} (CWNA, Loop Fade on): another layout, no "
                     "knob fields - or no matching bank 2, which leaves the bank unset (D-018: TOOLS shows a '!')")
        counts, speed, zero_at, zero_dir, zero_slow, now = knob_state(bank)
        print(f"last Slip turn event: {counts:+d} counts, speed {speed}; last arrival on 0: "
              + (f"{now - zero_at} ms ago, turning {'up' if zero_dir > 0 else 'down'}, "
                 f"{'slow (the long hold)' if zero_slow else 'fast'}" if zero_dir else "none"))
        if args:
            secs, seen, last, t0 = float(args[0]), {}, (counts, speed, zero_at), time.time()
            print(f"sampling for {secs:g} s: turn the Slip knob (a line per change; two events between samples count once)")
            while time.time() - t0 < secs:
                counts, speed, zero_at, zero_dir, zero_slow, now = knob_state(bank)
                if (counts, speed, zero_at) != last:
                    arrived = zero_at != last[2]
                    last = (counts, speed, zero_at)
                    seen[speed] = seen.get(speed, 0) + 1
                    print(f"{time.time() - t0:7.3f} s  {counts:+5d} counts  speed {speed}"
                          + (f"  arrived on 0 ({'slow' if zero_slow else 'fast'})" if arrived else ""))
                time.sleep(0.005)
            print("speeds seen: " + (", ".join(f"{m}: {n}" for m, n in sorted(seen.items())) or "none (no turn?)"))
    elif cmd == "fit":
        # src/clipwin_b2.c cw_fit: cw_bank + 0x784 u8 fit[16] (the row as the pad took it, with its region: 0 Off,
        # 1 Auto, then 1/4 .. 8 bars), + 0x7a4 u8 fon[16] (its last recompute stored Fit's step fields), + 0x7b4 u16
        # abeats[16] and + 0x7d4 i32 alen[16] (Auto's count and the length it counted), + 0x814 f32 bpm[16] (the tempo
        # they were made at), + 0x858 u16 fade[16] (Loop Fade as taken, 0 .. 1000); the pad object (+ 0x48 + 4q) for its
        # step fields. Read only.
        bank = cw_bank()
        magic = word(bank)
        if magic != CW_MAGIC:
            sys.exit(f"cw_bank magic {magic:#010x}, not {CW_MAGIC:#010x} (CWNA, Loop Fade on): another layout, no "
                     "Fit fields - or no matching bank 2, which leaves the bank unset (D-018: TOOLS shows a '!')")
        names = ["Off", "Auto", "1/4", "1/2", "3 beats", "1 bar", "6 beats", "2 bars", "4 bars", "8 bars"]
        fit, fon = peek(bank + 0x784, 16), peek(bank + 0x7A4, 16)
        abeats = struct.unpack("<16H", peek(bank + 0x7B4, 32))
        alen = struct.unpack("<16i", peek(bank + 0x7D4, 64))
        bpm = struct.unpack("<16f", peek(bank + 0x814, 64))
        pads = struct.unpack("<16I", peek(bank + 0x48, 64))
        fade = struct.unpack("<16H", peek(bank + 0x858, 32))
        for q in range(16):
            if not (fit[q] or fon[q] or fade[q]):
                continue
            line = (f"cell row {q >> 2} col {q & 3}: Fit {names[fit[q]] if fit[q] < len(names) else fit[q]}, "
                    + (f"fitted at {bpm[q]:.2f} BPM" if fon[q] else "not fitted")
                    + (f", Auto {abeats[q]} beats for {alen[q]} frames" if alen[q] else "")
                    + (f", Loop Fade {fade[q] / 10:g} %" if fade[q] else ""))
            if (0x20000000 <= pads[q] < 0x40000000 or 0xC0000000 <= pads[q] < 0xC4000000) and not pads[q] & 3:
                f = peek(pads[q] + 0x1F0, 0x48)
                rate, = struct.unpack_from("<f", f, 0)
                out, tps, n = struct.unpack_from("<fqI", f, 0x14)
                grid, = struct.unpack_from("<q", f, 0x40)
                line += f"; pad +0x1f0 {rate:.6f} +0x204 {out:.1f} +0x208 {tps} +0x210 {n} +0x230 {grid}"
            print(line)
    elif cmd == "crash":
        print_crash()
    elif cmd == "catch":
        # A unit in a boot loop is alive for seconds at a time: read the records (src/fault.c, latched at boot) as
        # soon as it enumerates, once per boot, for up to SECONDS.
        import usb.core
        secs = float(args[0]) if args else 120.0
        t0, seen = time.time(), 0
        while time.time() - t0 < secs:
            if usb.core.find(idVendor=VID, idProduct=PID) is None:
                time.sleep(0.05)
                continue
            seen += 1
            print(f"--- boot {seen}, {time.time() - t0:.1f} s")
            try:
                print_crash()
            except Exception as e:
                print(f"read failed: {e}")
            while usb.core.find(idVendor=VID, idProduct=PID) is not None and time.time() - t0 < secs:
                time.sleep(0.05)
            print(f"    gone at {time.time() - t0:.1f} s")
        if not seen:
            print("never enumerated (no 1209:0003)")
    elif cmd == "record":
        secs, path = float(args[0]), args[1]
        subprocess.run(["arecord", "-D", f"hw:{alsa_card()}", "-c", "6", "-r", "48000", "-f", "S24_3LE",
                        "-d", str(int(secs + 0.999)), path], check=True)
    elif cmd == "offsets":
        import numpy as np
        import wave
        a, b = (int(args[1]), int(args[2])) if len(args) > 2 else (0, 2)
        w = wave.open(args[0])
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.uint8)
        ch, width = w.getnchannels(), w.getsampwidth()
        frames = raw.reshape(-1, ch, width).astype(np.int32)
        x = frames[..., 0] | frames[..., 1] << 8 | frames[..., 2] << 16
        x = np.where(x & 0x800000, x - 0x1000000, x).astype(float) / 0x800000

        def onsets(s, gap=2400):
            e = np.abs(s)
            thr = max(1e-3, 0.3 * e.max())
            out, last = [], -gap
            for i in np.nonzero(e > thr)[0]:
                if i - last >= gap:
                    out.append(int(i))
                last = i
            return out
        oa, ob = onsets(x[:, a]), onsets(x[:, b])
        diffs = [min((o - p for p in oa), key=abs) for o in ob if oa]
        print(f"{len(oa)} onsets on ch {a}, {len(ob)} on ch {b}")
        if diffs:
            d = np.array(diffs)
            print(f"ch {b} minus ch {a}: median {np.median(d):+.1f} samples ({np.median(d) / 48:+.3f} ms), "
                  f"spread {d.min():+d} .. {d.max():+d}")
    elif cmd == "shift":
        # Gate 2: how far Out 1 moved between two takes, each aligned on its own metronome (Out 2): + = later.
        import numpy as np
        base, new = read_wav(args[0]), read_wav(args[1])
        bpm = float(args[2]) if len(args) > 2 else 120.0
        per_tick = 48000 * 60 / (bpm * 960)
        cb, cn = first_onset(base[:, 2]), first_onset(new[:, 2])
        if cb is None or cn is None:
            sys.exit("no metronome click on Out 2 (channel 2) in one of the takes")
        span = min(len(base) - cb, len(new) - cn, int(16 * 48000 * 60 / bpm))   # up to 4 bars
        a, b = base[cb:cb + span, 0], new[cn:cn + span, 0]
        nfft = 1 << int(np.ceil(np.log2(2 * span)))
        xc = np.fft.irfft(np.fft.rfft(b, nfft) * np.conj(np.fft.rfft(a, nfft)), nfft)
        lags = np.concatenate([np.arange(0, span), np.arange(-span + 1, 0)])
        vals = np.concatenate([xc[:span], xc[nfft - span + 1:]])
        lag = int(lags[np.argmax(vals)])
        beat = int(round(48000 * 60 / bpm))       # the takes align on their first click, which may be another beat
        lag = (lag + beat // 2) % beat - beat // 2  # of the bar: fold into +- half a beat (exact for small Slips)
        print(f"Out 1 moved {lag:+d} samples ({lag / per_tick:+.1f} ticks at {bpm:g} BPM; + = later) between the takes, "
              f"each aligned on its first click (base {cb}, new {cn})")
    elif cmd == "note":
        note, vel = int(args[0]), int(args[1]) if len(args) > 1 else 100
        port = subprocess.run(["amidi", "-l"], capture_output=True, text=True).stdout
        hw = next((l.split()[1] for l in port.splitlines() if "Blackbox" in l), None)
        if not hw:
            sys.exit("no MIDI port named Blackbox (amidi -l)")
        subprocess.run(["amidi", "-p", hw, "-S", f"90 {note:02X} {vel:02X}"], check=True)
        time.sleep(0.1)
        subprocess.run(["amidi", "-p", hw, "-S", f"80 {note:02X} 00"], check=True)
    elif cmd in ("set", "get"):
        row, col = cell(args[0])
        pid = MBOX_ROWS.get(args[1].lower().replace(" ", "").replace("_", "").replace("-", ""))
        if pid is None:
            sys.exit(f"row: one of {', '.join(MBOX_ROWS)}")
        v = 0
        if cmd == "set":
            text, (_, _, lst, lo, hi) = args[2], param(pid)
            names = [n.lower() for n in lst] if lst else []
            if text.lower() in names:
                v = names.index(text.lower())
            elif pid == 0x1C9 and "." in text:               # Slip as beats.ticks: "-0.645" = 645 ticks behind
                b_, t_ = text.lstrip("+-").split(".")
                v = (int(b_) * 960 + int(t_)) * (-1 if text.startswith("-") else 1)
            else:
                v = int(text, 0)
        result, back = mailbox(1 if cmd == "set" else 2, row, col, pid, v)
        if result:
            sys.exit(f"cell row {row} col {col}: {MBOX_RESULT.get(result, result)}")
        print(f"cell row {row} col {col}: {show(pid, back)}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
