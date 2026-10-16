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
  bbusb.py record SECONDS FILE.wav      capture the 6 USB channels (arecord)
  bbusb.py offsets FILE.wav [A B]       onset offsets between channel A and B (default 0 = Out1 L, 2 = Out2 L)
  bbusb.py shift BASE.wav NEW.wav [BPM] how far Out 1 moved between two takes, aligned on the metronome (Out 2)
  bbusb.py note NOTE [VEL]              send a note on (then off 100 ms later) on the Global In channel (amidi)

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
    d, out = dev(), b""
    while len(out) < n:
        k = min(64, n - len(out))
        a = addr + len(out)
        out += bytes(d.ctrl_transfer(0xC0, 0x50, a & 0xFFFF, a >> 16, (k + 3) & ~3))
    return out[:n]


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


CW_MAGIC = 0x43574E35            # "CWN5": src/clipwin.h's cw_bank layout this tool reads
GUI_MS = 0x2402EEE0              # the GUI's ms clock (clipwin.c GUI_MS)


def cw_bank():
    """the Clip Window bank in SDRAM (src/clipwin.h): master.c's block (its pointer in backup SRAM) + 0x83900"""
    mem = word(0x38800F70)
    if not 0xC0000000 <= mem < 0xC4000000:
        sys.exit(f"no SDRAM block (Prism pointer {mem:#x})")
    return mem + 0x83900


def knob_state(bank):
    """(counts, speed, zero_at, zero_dir, now): cw_bank + 0x720 i16 knob_counts, u8 knob_speed; + 0x4b8 u32 zero_at,
    i8 zero_dir (clipwin_turn); the GUI clock"""
    zero_at, zero_dir = struct.unpack("<Ib3x", peek(bank + 0x4B8, 8))
    counts, speed = struct.unpack("<hBx", peek(bank + 0x720, 4))
    return counts, speed, zero_at, zero_dir, word(GUI_MS)


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
            sys.exit(f"cw_bank magic {magic:#010x}, not {CW_MAGIC:#010x} (CWN5, 37.2.1 on): "
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
        # the tiers (KNOB_MEDIUM, KNOB_FAST there). Read only: nothing is written to the unit.
        bank = cw_bank()
        magic = word(bank)
        if magic != CW_MAGIC:
            sys.exit(f"cw_bank magic {magic:#010x}, not {CW_MAGIC:#010x} (CWN5, 37.2.1 on): another layout, no knob fields "
                     "- or no matching bank 2, which leaves the bank unset (D-018: TOOLS shows a '!')")
        counts, speed, zero_at, zero_dir, now = knob_state(bank)
        print(f"last Slip turn event: {counts:+d} counts, speed {speed}; last arrival on 0: "
              + (f"{now - zero_at} ms ago, turning {'up' if zero_dir > 0 else 'down'}" if zero_dir else "none"))
        if args:
            secs, seen, last, t0 = float(args[0]), {}, (counts, speed, zero_at), time.time()
            print(f"sampling for {secs:g} s: turn the Slip knob (a line per change; two events between samples count once)")
            while time.time() - t0 < secs:
                counts, speed, zero_at, zero_dir, now = knob_state(bank)
                if (counts, speed, zero_at) != last:
                    arrived = zero_at != last[2]
                    last = (counts, speed, zero_at)
                    seen[speed] = seen.get(speed, 0) + 1
                    print(f"{time.time() - t0:7.3f} s  {counts:+5d} counts  speed {speed}" + ("  arrived on 0" if arrived else ""))
                time.sleep(0.005)
            print("speeds seen: " + (", ".join(f"{m}: {n}" for m, n in sorted(seen.items())) or "none (no turn?)"))
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
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
