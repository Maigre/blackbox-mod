"""Bench tool: talk to a Blackbox running this fork over the USB cable on its POWER jack (src/usbdev.c).

The power jack is a USB device (1209:0003, "Blackbox"): class-compliant MIDI, USB audio (Outs 1-3 as 6 channels of
24-bit / 48 kHz) and, on a DEV build only (no RELEASE=1), a debug peek / poke of the unit's memory. Fork-only tool:
never part of a feat/* branch or a PR.

  bbusb.py info                         is it there, which build (dev builds answer a peek)
  bbusb.py peek ADDR [BYTES]            words at ADDR (hex), up to 64 bytes a request
  bbusb.py poke ADDR VALUE              write one 32-bit word (hex) - DEV build; you can break the running unit
  bbusb.py sdram                        free SDRAM between the two pool pointers (notes/re/x2)
  bbusb.py slip                         Clip Window bank: polled Slip per pad, latched slots (src/clipwin.c)
  bbusb.py record SECONDS FILE.wav      capture the 6 USB channels (arecord)
  bbusb.py offsets FILE.wav [A B]       onset offsets between channel A and B (default 0 = Out1 L, 2 = Out2 L)
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
        mem = word(0x38800F70)
        if not 0xC0000000 <= mem < 0xC4000000:
            sys.exit(f"no SDRAM block (Prism pointer {mem:#x})")
        bank = mem + 0x83900
        hdr = peek(bank, 8 + 64 + 64 + 16)
        magic, scan = struct.unpack_from("<II", hdr)
        slip = struct.unpack_from("<16i", hdr, 8)
        pads = struct.unpack_from("<16I", hdr, 72)
        valid = hdr[136:152]
        print(f"bank {bank:#010x} magic {magic:#010x} scan {scan}")
        for q in range(16):
            if slip[q] or valid[q]:
                print(f"pad {q + 1:2}: slip {slip[q]:+5} ticks  pad object {pads[q]:#010x}  latched slots {valid[q]:04b}")
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
