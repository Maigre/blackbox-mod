#!/usr/bin/env python3
"""The Blackbox's rig gates (rig.toml) - fork-only, like bench/. The runner and its contract: 37Dev docs/RIG.md.

mgr-ran's rig runner starts these in a container with no network: /src is this tree read-only, /out the job's folder,
/tmp a tmpfs. What the rig lends (37Dev rig/hosts/mgr-ran.toml):
  usb-power:blackbox   /rig/power.sock - one line in (on, off, cycle [s], status), one out (ok on|off, err why)
  audio:fireface       /dev/snd as it was when the job started, RIG_ALSA = the Fireface UFX. The unit's own ALSA card
                       (its MIDI and its 6 USB channels) comes with it when the unit was on at that moment.
No /proc/asound in a container: cards and ports are found through alsa-lib (`arecord -l`, `amidi -l`). /sys is the
host's, read-only: where the host has the unit after a power cycle is read there (host_view).

  gates.py soak [--takes N] [--every S] [--length S] [--pad Q]
      pad Q (default 0) started by its MIDI note (36 + q, channel 1); then N takes (3), one every S seconds (600),
      each LENGTH seconds (10) on USB (Out 1 L/R) and, at the same time, on the Fireface's rear inputs 3/4 (the
      unit's phones out, as built 12/11). The first take is the reference: a crunch (#t-025, F-o) is the analog
      side's residual against USB rising DIVERGE_DB over the first take's.
  gates.py bootloop [--cycles N] [--pads Q,Q,...]
      boot 0, then N power cycles (5) through the socket; after each boot, each pad (all 16) by its MIDI note, a
      take on USB around it. Boot 0 is the reference: a pad that sounded there and is silent after a later boot is
      F-n's catch (#t-026, boot half). A pad silent on boot 0 has nothing loaded, or waits for the transport: not
      a catch.
  gates.py io
      what this container sees: the unit's card and MIDI port, the Fireface, the power socket, the unit's USB.

On a crunch or a catch, the card's reads at once, before anything else is touched (blackbox#t-025 / #t-026 cards):
a USB record, then - by peek only, never a poke nor the mailbox - `bbusb.py crash`, `fit`, the words 2405FFE4,
2405FFF0, 24013930 (twice) and two dumps of 2400A9C0 (37 632 bytes). The peeks need the unit's USB device itself,
which no mgr-ran resource lends yet: without it they are skipped, and the verdict says so.

Verdict: /out/<gate>.txt (rig.toml `verdict`): a `seen:` line (the unit's card and port, its USB lent or not, the
power, where the host has the unit), one line per take or boot, then PASS or FAIL and why; takes and reads beside it
in /out. The `seen:` line comes back when the unit is lost too: a unit that did not boot, or one that booted outside
the devices this container was lent at its start (another card number or minor), read apart. Exit 0 = pass, 1 = fail (a crunch, a catch, or the gate could not run - it says which).
"""
import argparse
import os
import re
import socket
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bench"))
import bbusb  # noqa: E402  (read_wav; the peeks, run as a tool so a missing pyusb only skips them)

OUT = os.environ.get("RIG_OUT", "/out")
SOCK = os.environ.get("RIG_POWER_SOCK", "/rig/power.sock")
RATE = 48000
NOTE0, CH = 36, 1                     # Pad Note "Default" = 36 + q on the Global In channel (bench/bbmidi.py)
FF_PHONES = (2, 3)                    # the Fireface's rear inputs 3/4, 0-based: the unit's phones out
USB_OUT1 = (0, 1)                     # the unit's USB channels: Out 1 L/R first
FF_CHANNELS = 22
SILENT = 1e-3                         # RMS (full scale = 1): about -60 dBFS
DIVERGE_DB = 10.0                     # a crunch: the residual this far over the first take's
WINDOW = RATE // 2                    # the comparison's windows: each aligned on its own, the two clocks drift
MAX_LAG = RATE // 4                   # the two captures start a few ms apart (two arecords); a quarter second is room
BOOT_WAIT = 60                        # seconds for the unit to come back on USB after power on
SETTLE = 8                            # seconds after it is back, before the first note (the preset load)


# ---------------------------------------------------------------- what the container sees

def blackbox_card(listing):
    """the unit's card number from `arecord -l`, or None"""
    for line in listing.splitlines():
        if line.startswith("card ") and "Blackbox" in line:
            return line.split()[1].rstrip(":")
    return None


def blackbox_midi(listing):
    """the unit's raw MIDI port from `amidi -l` (`IO  hw:2,0,0  Blackbox MIDI 1`), or None"""
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1].startswith("hw:") and "Blackbox" in line:
            return parts[1]
    return None


def host_unit(sys_root="/sys"):
    """the unit as the HOST sees it, through sysfs (read-only in a container, not namespaced for sound):
    (on its USB bus: bool, its card number or None, {node name: "major:minor"} of that card's nodes);
    None when sysfs has no sound class to read"""
    snd = os.path.join(sys_root, "class", "sound")
    try:
        names = sorted(os.listdir(snd))
    except OSError:
        return None
    on_bus = False
    usb = os.path.join(sys_root, "bus", "usb", "devices")
    want = (f"{bbusb.VID:04x}", f"{bbusb.PID:04x}")
    for d in (os.listdir(usb) if os.path.isdir(usb) else ()):
        try:
            ids = tuple(open(os.path.join(usb, d, k)).read().strip().lower() for k in ("idVendor", "idProduct"))
        except OSError:
            continue
        on_bus = on_bus or ids == want
    card = None
    for n in names:
        if n.startswith("card"):
            try:
                if open(os.path.join(snd, n, "id")).read().strip() == "Blackbox":
                    card = n[4:]
            except OSError:
                continue
    nodes = {}
    if card is not None:
        for n in names:
            if re.fullmatch(rf"[a-z]+C{card}(D\d+[pc]?)?", n):
                try:
                    nodes[n] = open(os.path.join(snd, n, "dev")).read().strip()
                except OSError:
                    continue
    return on_bus, card, nodes


def held_nodes(names, dev_snd="/dev/snd"):
    """{node name: "major:minor"} of the nodes this container holds, among `names`"""
    got = {}
    for n in names:
        try:
            st = os.stat(os.path.join(dev_snd, n))
        except OSError:
            continue
        got[n] = f"{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}"
    return got


def host_view(seen, held):
    """one line: where the host has the unit (host_unit) against the nodes this container holds (held_nodes)"""
    if seen is None:
        return "host: sysfs has no sound class here - where the host has the unit is unknown"
    on_bus, card, nodes = seen
    bus = f"unit on the host's USB ({bbusb.VID:04x}:{bbusb.PID:04x}): {'yes' if on_bus else 'no'}"
    if card is None:
        return f"host: {bus}, no Blackbox card" + ("" if on_bus else " (off, booting, or off the bus)")
    off = [f"{n} {d} here {held.get(n, 'absent')}" for n, d in sorted(nodes.items()) if held.get(n) != d]
    if not off:
        return f"host: {bus}, card {card}, its {len(nodes)} nodes held here as they are"
    return (f"host: {bus}, card {card}, {len(off)} of its {len(nodes)} nodes not held here as they are ("
            + "; ".join(off[:3]) + ("; ..." if len(off) > 3 else "")
            + ") - it came back outside what this container was lent")


def plug(alsa):
    """hw:X,Y -> plughw:X,Y: the plug converts the format, the channel count stays what is asked"""
    return "plug" + alsa if alsa.startswith("hw:") else alsa


def power(cmd, path=SOCK, timeout=90):
    """one line to the power socket, its answer's word after `ok` (on | off); `err ...` raises"""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(path)
        s.sendall((cmd + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(256)
            if not chunk:
                break
            buf += chunk
    answer = buf.decode(errors="replace").strip()
    if not answer.startswith("ok"):
        raise RuntimeError(f"power {cmd}: {answer or 'no answer'}")
    return answer[2:].strip()


class Unit:
    """the real I/O: ALSA through alsa-utils, the power through the socket. Tests pass their own."""

    def __init__(self, out):
        self.out = out
        self.alsa = os.environ.get("RIG_ALSA", "")

    def card(self):
        return blackbox_card(subprocess.run(["arecord", "-l"], capture_output=True, text=True).stdout)

    def midi(self):
        return blackbox_midi(subprocess.run(["amidi", "-l"], capture_output=True, text=True).stdout)

    def send(self, hexbytes):
        port = self.midi()
        if not port:
            raise RuntimeError("the unit's MIDI port is gone (amidi -l)")
        subprocess.run(["amidi", "-p", port, "-S", hexbytes], check=True, capture_output=True, timeout=10)

    def note(self, q):
        n = NOTE0 + q
        self.send(f"{0x90 | (CH - 1):02X} {n:02X} 64")
        time.sleep(0.1)
        self.send(f"{0x80 | (CH - 1):02X} {n:02X} 00")

    def power(self, cmd):
        return power(cmd)

    def seen(self):
        """the verdict's `seen:` line: what this container reaches, and where the host has the unit"""
        try:
            pw = power("status", timeout=10)
        except Exception as e:
            pw = f"unread ({e})"
        h = host_unit()
        held = held_nodes(h[2]) if h and h[2] else {}
        return (f"card {self.card()}, MIDI {self.midi()}, Fireface {self.alsa or '-'}, power {pw}, unit USB lent "
                f"(peeks): {'yes' if self.usb_lent() else 'no'}; {host_view(h, held)}")

    def _arecord(self, dev, channels, fmt, seconds, path):
        return subprocess.Popen(["arecord", "-q", "-D", dev, "-c", str(channels), "-r", str(RATE), "-f", fmt,
                                 "-d", str(int(seconds)), path], stderr=subprocess.PIPE)

    def take_usb(self, seconds, name, during=None):
        """frames x 6 from the unit's USB; `during` runs while it records (a note), 0.3 s in"""
        path = os.path.join(self.out, name + ".wav")
        p = self._arecord(f"hw:{self.card()}", 6, "S24_3LE", seconds, path)
        if during:
            time.sleep(0.3)
            during()
        _, err = p.communicate(timeout=seconds + 15)
        if p.returncode:
            raise RuntimeError(f"USB take: arecord {p.returncode}: {err.decode(errors='replace').strip()}")
        return bbusb.read_wav(path)

    def take_both(self, seconds, name):
        """(USB frames x 6, Fireface frames x 22), started together"""
        pu, pf = os.path.join(self.out, name + "-usb.wav"), os.path.join(self.out, name + "-ff.wav")
        a = self._arecord(f"hw:{self.card()}", 6, "S24_3LE", seconds, pu)
        b = self._arecord(plug(self.alsa), FF_CHANNELS, "S32_LE", seconds, pf)
        errs = []
        for p, what in ((a, "USB"), (b, "Fireface")):
            _, err = p.communicate(timeout=seconds + 15)
            if p.returncode:
                errs.append(f"{what} take: arecord {p.returncode}: {err.decode(errors='replace').strip()}")
        if errs:
            raise RuntimeError("; ".join(errs))
        return bbusb.read_wav(pu), bbusb.read_wav(pf)

    def usb_lent(self):
        """the unit's USB device reachable here (the peeks): pyusb sees 1209:0003 and may open it"""
        try:
            import usb.core
            d = usb.core.find(idVendor=bbusb.VID, idProduct=bbusb.PID)
            if d is None:
                return False
            d.ctrl_transfer(0x80, 0, 0, 0, 2, timeout=500)       # GET_STATUS: opening it is the test
            return True
        except Exception:
            return False

    def reads(self, why, n):
        """the card's reads, by peek only (module doc); returns the lines for the verdict"""
        d = os.path.join(self.out, f"reads-{n}")
        os.makedirs(d, exist_ok=True)
        lines = [f"reads-{n} ({why}):"]
        try:
            self.take_usb(10, f"reads-{n}/record")
            lines.append("  record: reads-%d/record.wav (10 s, 6 USB channels)" % n)
        except Exception as e:
            lines.append(f"  record: {e}")
        if not self.usb_lent():
            lines.append("  peeks SKIPPED: the unit's USB (1209:0003) is not lent to this container - no usb:blackbox "
                         "resource on this host")
            return lines
        bb = os.path.join(HERE, "..", "bench", "bbusb.py")
        steps = [("crash", ["crash"]), ("fit", ["fit"]), ("2405FFE4", ["peek", "2405FFE4", "4"]),
                 ("2405FFF0", ["peek", "2405FFF0", "4"]), ("24013930-a", ["peek", "24013930", "4"]),
                 ("24013930-b", ["peek", "24013930", "4"]), ("dump-a", ["peek", "2400A9C0", "37632"]),
                 ("dump-b", ["peek", "2400A9C0", "37632"])]
        for tag, args in steps:
            r = subprocess.run([sys.executable, bb, *args], capture_output=True, text=True, timeout=120)
            with open(os.path.join(d, tag + ".txt"), "w") as f:
                f.write(r.stdout + r.stderr)
            head = (r.stdout.strip().splitlines() or [r.stderr.strip() or f"exit {r.returncode}"])[0]
            lines.append(f"  {tag}: {head[:100]}")
        return lines


# ---------------------------------------------------------------- the measures

def rms(x):
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def align(ref, sig, max_lag=MAX_LAG):
    """the lag (in samples) at which `sig` best matches `ref`: sig[i + lag] ~ ref[i]"""
    n = len(ref) + len(sig)
    size = 1 << (n - 1).bit_length()
    c = np.fft.irfft(np.fft.rfft(sig, size) * np.conj(np.fft.rfft(ref, size)), size)
    lags = np.concatenate([np.arange(0, max_lag + 1), np.arange(-max_lag, 0)])
    vals = np.concatenate([c[:max_lag + 1], c[-max_lag:]])
    return int(lags[int(np.argmax(np.abs(vals)))])


def frames(x, nseg=1024):
    w = np.hanning(nseg)
    return np.array([np.abs(np.fft.rfft(w * x[s:s + nseg])) ** 2 for s in range(0, len(x) - nseg + 1, nseg // 2)])


def residual_db(usb, ana, window=WINDOW, max_lag=MAX_LAG):
    """how far the analog side is from USB, in dB under the signal. Each window that carries sound is re-aligned on
    its own (the two clocks drift) and cut in short frames; per frequency, the path's gain is the median over the
    frames of analog over USB power (the phones amp, the cable, the converters: whatever is the same each frame);
    the residual is the analog power the path does not explain - noise, and a crunch's distortion - over what it
    does. Magnitudes only: the drift's fractional delay moves the phase, not this. None when USB is silent.
    usb, ana: frames x 2 (L, R)."""
    u, a = usb.mean(axis=1), ana.mean(axis=1)
    lag = align(u[: min(len(u), 4 * RATE)], a[: min(len(a), 4 * RATE)], max_lag)
    pu, pa = [], []
    for start in range(max_lag, len(u) - window - max_lag, window):
        uw = u[start:start + window]
        s = start + lag
        if rms(uw) < SILENT or s - 64 < 0 or s + window + 64 > len(a):
            continue
        d = align(uw, a[s - 64:s + window + 64], 128) - 64        # the drift since the first alignment
        aw = a[s + d:s + d + window]
        if len(aw) == window:
            pu.append(frames(uw))
            pa.append(frames(aw))
    if not pu:
        return None
    pu, pa = np.concatenate(pu), np.concatenate(pa)
    heard = pu > 1e-7 * pu.max()                                  # bins the USB side carries
    ratio = np.where(heard, pa / np.maximum(pu, 1e-30), np.nan)
    h = np.nan_to_num(np.nanmedian(np.where(heard.any(axis=0), ratio, 0), axis=0))
    model = h * pu
    excess = np.maximum(pa - model, 0)
    return float(10 * np.log10(max(excess.sum(), 1e-20) / max(model.sum(), 1e-20)))


def sounded(take, pre_s=0.25, post_from=0.5):
    """a pad's take on USB (frames x channels; the note at 0.3 s): it sounded when, on some channel, what follows the
    note is over SILENT and 4x what came before it (a pad still ringing from the one before is not this one)"""
    pre, post = take[: int(pre_s * RATE)], take[int(post_from * RATE):]
    for ch in range(take.shape[1]):
        p, q = rms(pre[:, ch]), rms(post[:, ch])
        if q > SILENT and q > 4 * p:
            return True
    return False


# ---------------------------------------------------------------- the gates

class Verdict:
    def __init__(self, gate, out):
        self.path = os.path.join(out, gate + ".txt")
        self.lines = []

    def say(self, line):
        self.lines.append(line)
        print(line, flush=True)
        with open(self.path, "w") as f:
            f.write("\n".join(self.lines) + "\n")

    def end(self, ok, why):
        self.say(("PASS " if ok else "FAIL ") + why)
        return 0 if ok else 1


def present(unit):
    """the unit's card and MIDI port are here; else the reason the gate cannot run"""
    if unit.card() is None:
        return ("the unit's ALSA card is not in this container: it was off or away when the job started (the rig "
                "lends /dev/snd as found), or PipeWire holds it")
    if unit.midi() is None:
        return "the unit's MIDI port is not in this container (amidi -l)"
    return None


def soak(unit, out, takes=3, every=600, length=10, pad=0, sleep=time.sleep):
    v = Verdict("soak", out)
    v.say(f"soak: pad q{pad} by note {NOTE0 + pad}, {takes} takes of {length} s every {every} s, crunch at "
          f"+{DIVERGE_DB:g} dB over the first take's residual")
    v.say("seen: " + unit.seen())
    why = present(unit)
    if why:
        return v.end(False, "could not run: " + why)
    unit.note(pad)
    sleep(2)
    ref = None
    for k in range(takes):
        if k:
            sleep(max(0, every - length))
        if unit.card() is None:
            v.say("seen: " + unit.seen())
            for line in unit.reads(f"take {k}: the unit left USB", k):
                v.say(line)
            return v.end(False, f"take {k}: the unit's card is gone (it reset, or its USB went quiet: F-i)")
        usb, ff = unit.take_both(length, f"take-{k}")
        u, a = usb[:, list(USB_OUT1)], ff[:, list(FF_PHONES)]
        lu, la = rms(u), rms(a)
        if lu < SILENT:
            return v.end(False, f"take {k}: USB Out 1 silent ({lu:.1e}): pad q{pad} is not playing (its Quant waits "
                                f"for the transport, or nothing is loaded on it) - not a crunch")
        if la < SILENT:
            return v.end(False, f"take {k}: the Fireface's inputs 3/4 are silent ({la:.1e}) while USB plays: cabling or "
                                f"routing, not a crunch")
        db = residual_db(u, a)
        if db is None:
            return v.end(False, f"take {k}: no window carried sound on both sides")
        if ref is None:
            ref = db
            v.say(f"take {k} at {k * every} s: residual {db:.1f} dB (the reference); USB {lu:.3f}, analog {la:.3f}")
            continue
        v.say(f"take {k} at {k * every} s: residual {db:.1f} dB ({db - ref:+.1f} over the reference); USB {lu:.3f}, "
              f"analog {la:.3f}")
        if db - ref >= DIVERGE_DB:
            for line in unit.reads(f"crunch at take {k}", k):
                v.say(line)
            unit.note(pad)
            return v.end(False, f"crunch at take {k} ({k * every} s): analog {db - ref:+.1f} dB off USB (F-o, #t-025)")
    unit.note(pad)                                     # a Toggle pad stops on its note
    return v.end(True, f"no crunch in {takes} takes over {(takes - 1) * every} s")


def wait_back(unit, sleep=time.sleep, limit=BOOT_WAIT):
    for _ in range(int(limit)):
        if unit.card() is not None and unit.midi() is not None:
            sleep(SETTLE)
            return True
        sleep(1)
    return False


def one_boot(unit, pads, n):
    """{pad: sounded} after one boot, each pad by its note, stopped again if it still plays"""
    got = {}
    for q in pads:
        take = unit.take_usb(2.5, f"boot-{n}-q{q}", during=lambda q=q: unit.note(q))
        got[q] = sounded(take)
        if got[q]:
            tail = unit.take_usb(1, f"boot-{n}-q{q}-tail")
            if rms(tail) > SILENT:
                unit.note(q)                           # a Toggle pad: its note stops it
    return got


def bootloop(unit, out, cycles=5, pads=tuple(range(16)), off_s=5, sleep=time.sleep):
    v = Verdict("bootloop", out)
    v.say(f"bootloop: boot 0 then {cycles} power cycles ({off_s} s off), pads {','.join('q%d' % q for q in pads)}")
    v.say("seen: " + unit.seen())
    why = present(unit)
    if why:
        return v.end(False, "could not run: " + why)
    ref = None
    for n in range(cycles + 1):
        unit.power(f"cycle {off_s}")
        if not wait_back(unit, sleep):
            v.say("seen: " + unit.seen())
            return v.end(False, f"boot {n}: the unit did not come back on USB within {BOOT_WAIT} s (no boot, or it "
                                f"re-enumerated outside the devices this container was lent)")
        got = one_boot(unit, pads, n)
        on = [q for q in pads if got[q]]
        if ref is None:
            ref = set(on)
            v.say(f"boot 0 (the reference, card {unit.card()}): {len(on)} pads sound: {','.join('q%d' % q for q in on) or 'none'}")
            if not on:
                return v.end(False, "boot 0: no pad sounded - nothing to compare (the preset, or every pad waits for "
                                    "the transport)")
            continue
        silent = sorted(ref - set(on))
        v.say(f"boot {n} (card {unit.card()}): {len(on)} pads sound" + (f", SILENT: {','.join('q%d' % q for q in silent)}" if silent else ""))
        if silent:
            for line in unit.reads(f"boot {n}: pads {silent} silent", n):
                v.say(line)
            return v.end(False, f"boot {n}: pad(s) {','.join('q%d' % q for q in silent)} silent after a power cycle "
                                f"(F-n, #t-026)")
    return v.end(True, f"{cycles} power cycles, every pad of boot 0 sounded after each")


def io(unit):
    print("unit card:", unit.card())
    print("unit MIDI:", unit.midi())
    print("Fireface (RIG_ALSA):", unit.alsa or "-")
    print("power socket:", SOCK if os.path.exists(SOCK) else "-")
    print("unit USB lent (peeks):", unit.usb_lent())
    print("RIG_NEEDS:", os.environ.get("RIG_NEEDS", "-"))
    h = host_unit()
    print(host_view(h, held_nodes(h[2]) if h and h[2] else {}))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(prog="gates.py")
    sub = ap.add_subparsers(dest="gate", required=True)
    s = sub.add_parser("soak")
    s.add_argument("--takes", type=int, default=3)
    s.add_argument("--every", type=int, default=600)
    s.add_argument("--length", type=int, default=10)
    s.add_argument("--pad", type=int, default=0)
    b = sub.add_parser("bootloop")
    b.add_argument("--cycles", type=int, default=5)
    b.add_argument("--pads", default=",".join(str(q) for q in range(16)))
    sub.add_parser("io")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    unit = Unit(OUT)
    if a.gate == "soak":
        return soak(unit, OUT, a.takes, a.every, a.length, a.pad)
    if a.gate == "bootloop":
        return bootloop(unit, OUT, a.cycles, tuple(int(q) for q in a.pads.split(",")))
    return io(unit)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
