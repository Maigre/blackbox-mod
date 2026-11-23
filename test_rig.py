"""The rig gates (rig.toml, rig/gates.py) on dev37, with a fake unit: no ALSA, no socket of the rig's, no Blackbox.

Here: rig.toml reads as the runner reads it (37Dev bin/rig: the gate-name pattern, an argv command, a timeout under
6 h that the gate's own length fits in, the recipe and the script present, the needs among what mgr-ran lends); the
comparison sees a clean analog take as clean (a delay, a gain, a polarity, noise, two clocks 50 ppm apart) and a
bit-reduced one as a crunch; a pad sounds when the take after its note rises over what came before, not when the pad
before still rings; alsa-utils' listings give the unit's card and port; sysfs tells where the host has the unit against the nodes the
container holds; the power socket's client; the soak and
the boot loop end to end on a fake unit, passing, catching, and refusing to judge what they cannot.
NOT checked here: the unit, the Fireface, the container, the runner - that is the rig run itself (a `Rig:` tip).
"""
import os
import re
import socket
import sys
import contextlib
import io
import tempfile
import threading
import tomllib

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "rig"))
import gates  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" - {detail}"))
    fails += 0 if ok else 1


RATE = gates.RATE
rng = np.random.default_rng(37)


def music(seconds, seed=0):
    """a loop-like signal: decaying tones and noise bursts every quarter second, stereo, about -12 dBFS"""
    r = np.random.default_rng(seed)
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    x = np.zeros(n)
    for k in range(int(seconds * 4)):
        s = int(k * RATE / 4)
        m = min(n - s, RATE // 4)
        env = np.exp(-np.arange(m) / (0.05 * RATE))
        f = r.choice([110, 220, 330, 440, 660])
        x[s:s + m] += env * (0.3 * np.sin(2 * np.pi * f * t[:m]) + 0.1 * r.standard_normal(m))
    return np.stack([x, 0.9 * x], axis=1) * 0.5


def analog(usb, crunch_bits=None, delay=37, gain=-0.7, ppm=50, noise=3e-4):
    """the phones out as the Fireface hears it: delayed, scaled (inverted), resampled by a clock ppm off (a 16-tap
    windowed sinc: band-limited, as converters are), noise"""
    n = len(usb)
    src = np.arange(n) * (1 + ppm * 1e-6) - delay
    i0, fr = np.floor(src).astype(int), src - np.floor(src)
    a = np.zeros(usb.shape)
    for k in range(-7, 9):
        tap = np.sinc(k - fr) * (0.5 + 0.5 * np.cos(np.pi * (k - fr) / 8.5))
        idx = i0 + k
        ok = (idx >= 0) & (idx < n)
        a[ok] += tap[ok, None] * usb[idx[ok]]
    if crunch_bits:
        q = 2.0 ** (crunch_bits - 1)
        a = np.round(a * q) / q
    return gain * a + noise * rng.standard_normal(a.shape)


# ---------------------------------------------------------------- rig.toml, as the runner reads it

GATE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")        # 37Dev bin/rig, 37Hub's door
LENT = {"usb-power:blackbox", "audio:fireface", "gpu", "gpu:rtx3090", "data:walldance"}   # mgr-ran.toml today


def seconds(t):
    m = re.fullmatch(r"(\d+)([smh])", t)
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600}[m.group(2)] if m else None


rt = tomllib.loads(open("rig.toml").read())
check("rig.toml version 1, a default image", rt["rig"]["version"] == 1 and os.path.isfile(rt["rig"]["image"]))
check("rig.toml declares soak and bootloop", set(rt["gate"]) == {"soak", "bootloop"}, sorted(rt["gate"]))
for name, g in rt["gate"].items():
    cmd = g["command"]
    check(f"{name}: a name the door takes", bool(GATE_RE.match(name)))
    check(f"{name}: an argv array whose script is here",
          isinstance(cmd, list) and all(isinstance(c, str) for c in cmd) and os.path.isfile(cmd[1]), cmd)
    check(f"{name}: needs only what mgr-ran lends", set(g["needs"]) <= LENT, g["needs"])
    lim = seconds(g["timeout"])
    check(f"{name}: a timeout of at most 6 h", lim is not None and lim <= 6 * 3600, g["timeout"])
    check(f"{name}: a verdict file named after it", g.get("verdict") == name + ".txt", g.get("verdict"))
    if name == "soak":
        i = cmd.index
        span = (int(cmd[i("--takes") + 1]) - 1) * int(cmd[i("--every") + 1]) + int(cmd[i("--length") + 1])
        check("soak: its takes fit its timeout with 5 min to spare", span + 300 <= lim, (span, lim))
    if name == "bootloop":
        boots = int(cmd[cmd.index("--cycles") + 1]) + 1
        worst = boots * (gates.BOOT_WAIT + gates.SETTLE + 16 * (2.5 + 1 + 0.3) + 5)
        check("bootloop: its boots fit its timeout at the worst", worst <= lim, (worst, lim))
src = open("rig/Containerfile").read()
check("the recipe brings arecord / amidi, numpy, pyusb",
      all(p in src for p in ("alsa-utils", "python3-numpy", "python3-usb")))

# ---------------------------------------------------------------- the comparison

u = music(10)
clean = [gates.residual_db(u, analog(u)) for _ in range(2)]
check("a clean analog take: residual under -20 dB", all(c is not None and c < -20 for c in clean), clean)
check("two clean takes agree within 3 dB", abs(clean[0] - clean[1]) < 3, clean)
crunched = gates.residual_db(u, analog(u, crunch_bits=6))
check(f"a 6-bit take is a crunch (+{gates.DIVERGE_DB:g} dB over clean)",
      crunched is not None and crunched - clean[0] >= gates.DIVERGE_DB, (clean[0], crunched))
check("a silent USB take has no residual", gates.residual_db(np.zeros((RATE * 3, 2)), analog(u)[:RATE * 3]) is None)
check("align finds a 400-sample delay", gates.align(u[:, 0], np.concatenate([np.zeros(400), u[:-400, 0]])) == 400)

# ---------------------------------------------------------------- a pad's take

quiet = 1e-5 * rng.standard_normal((int(2.5 * RATE), 6))
hit = quiet.copy()
hit[int(0.35 * RATE):, 2] += music(2.15)[:, 0]
check("a pad that starts after its note sounded", gates.sounded(hit))
check("silence did not", not gates.sounded(quiet))
ring = quiet.copy()
ring[:, 0] += 0.2 * np.sin(np.arange(len(ring)) / 7)
check("the pad before, still ringing, is not this pad", not gates.sounded(ring))

# ---------------------------------------------------------------- what alsa-utils lists

AREC = """**** List of CAPTURE Hardware Devices ****
card 1: UFX23108111 [Fireface UFX (23108111)], device 0: USB Audio [USB Audio]
card 3: Blackbox [Blackbox], device 0: USB Audio [USB Audio]
"""
AMIDI = """Dir Device    Name
IO  hw:1,0,0  Fireface UFX (23108111) MIDI 1
IO  hw:3,0,0  Blackbox MIDI 1
"""
check("arecord -l: the unit is card 3", gates.blackbox_card(AREC) == "3")
check("arecord -l without it: None", gates.blackbox_card(AREC.splitlines()[1]) is None)
check("amidi -l: the unit's port", gates.blackbox_midi(AMIDI) == "hw:3,0,0")
check("RIG_ALSA through the plug", gates.plug("hw:UFX23108111,0") == "plughw:UFX23108111,0")

# ---------------------------------------------------------------- where the host has the unit (sysfs)

def fake_sys(root, card="3", nodes=(("controlC3", "116:13"), ("pcmC3D0c", "116:12"), ("midiC3D0", "116:11")),
             on_bus=True):
    """a /sys with the Fireface as card 1 and, when `card`, the unit"""
    def put(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").write(text + "\n")
    put(os.path.join(root, "class/sound/card1/id"), "UFX23108111")
    put(os.path.join(root, "class/sound/controlC1/dev"), "116:6")
    if card:
        put(os.path.join(root, f"class/sound/card{card}/id"), "Blackbox")
        for n, d in nodes:
            put(os.path.join(root, f"class/sound/{n}/dev"), d)
    put(os.path.join(root, "bus/usb/devices/9-1.4.4/idVendor"), "2109")
    put(os.path.join(root, "bus/usb/devices/9-1.4.4/idProduct"), "2817")
    if on_bus:
        put(os.path.join(root, "bus/usb/devices/9-1.4.4.1/idVendor"), "1209")
        put(os.path.join(root, "bus/usb/devices/9-1.4.4.1/idProduct"), "0003")


with tempfile.TemporaryDirectory() as d:
    fake_sys(d)
    h = gates.host_unit(d)
    check("sysfs: the unit on the bus, card 3, its three nodes",
          h == (True, "3", {"controlC3": "116:13", "pcmC3D0c": "116:12", "midiC3D0": "116:11"}), h)
    line = gates.host_view(h, dict(h[2]))
    check("held as the host has them: said so", "nodes held here as they are" in line and "card 3" in line, line)
    line = gates.host_view(h, {"controlC3": "116:13", "pcmC3D0c": "116:7"})
    check("another minor, a node missing: both named, and what it means",
          "2 of its 3" in line and "pcmC3D0c 116:12 here 116:7" in line and "midiC3D0 116:11 here absent" in line
          and "outside what this container was lent" in line, line)
with tempfile.TemporaryDirectory() as d:
    fake_sys(d, card=None, on_bus=False)
    h = gates.host_unit(d)
    line = gates.host_view(h, {})
    check("no unit on the host: off the bus, no card", h == (False, None, {}) and "USB (1209:0003): no" in line
          and "no Blackbox card (off" in line, (h, line))
with tempfile.TemporaryDirectory() as d:
    fake_sys(d, card=None)
    line = gates.host_view(gates.host_unit(d), {})
    check("on the bus, no card yet: not called off", "USB (1209:0003): yes, no Blackbox card" in line
          and "(off" not in line, line)
with tempfile.TemporaryDirectory() as d:
    fake_sys(d, card="30", nodes=(("controlC30", "116:40"),))
    h = gates.host_unit(d)
    check("card 30's nodes are its own, not card 3's", h[1] == "30" and set(h[2]) == {"controlC30"}, h)
check("no sysfs sound class: unknown, said so", gates.host_unit("/nonexistent") is None
      and "unknown" in gates.host_view(None, {}))

# ---------------------------------------------------------------- the power socket's client

with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "power.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(4)
    said = []

    def serve():
        for answer in ("ok on", "err cycle takes 0 to 60 seconds"):
            c, _ = srv.accept()
            said.append(c.recv(64).decode().strip())
            c.sendall((answer + "\n").encode())
            c.close()

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    check("power: `cycle 5` answered on", gates.power("cycle 5", path, timeout=5) == "on")
    try:
        gates.power("cycle 99", path, timeout=5)
        check("power: an err raises", False, "no raise")
    except RuntimeError as e:
        check("power: an err raises, and says why", "0 to 60" in str(e), str(e))
    th.join(5)
    srv.close()
    check("power: one line each, as sent", said == ["cycle 5", "cycle 99"], said)


# ---------------------------------------------------------------- the gates on a fake unit

class Fake:
    """a unit whose takes are synthetic: `crunch_at` = the soak take that is bit-reduced; `dead` = {boot: pads silent}"""

    def __init__(self, out, crunch_at=None, dead=None, loaded=range(16), here=True, usb_lent=False):
        self.out, self.crunch_at, self.dead, self.loaded = out, crunch_at, dead or {}, set(loaded)
        self.here, self.lent = here, usb_lent
        self.boot, self.takes, self.notes, self.powers, self.reads_n = -1, 0, [], [], []
        self.alsa = "hw:UFX23108111,0"
        self.playing = set()

    def card(self):
        return "3" if self.here else None

    def midi(self):
        return "hw:3,0,0" if self.here else None

    def note(self, q):
        """every pad a Toggle: its note starts it, the next stops it; a dead or empty pad stays quiet"""
        self.notes.append(q)
        if q in self.playing:
            self.playing.discard(q)
        elif q in self.loaded and q not in self.dead.get(self.boot, ()):
            self.playing.add(q)

    def power(self, cmd):
        self.powers.append(cmd)
        self.boot += 1
        self.playing = set()                           # a boot starts with nothing playing
        return "on"

    def take_both(self, seconds, name):
        usb = np.concatenate([music(seconds, seed=self.takes), np.zeros((int(seconds * RATE), 4))], axis=1)
        a = analog(usb[:, :2], crunch_bits=6 if self.takes == self.crunch_at else None)
        ff = np.zeros((len(usb), 22))
        ff[:, 2:4] = a
        self.takes += 1
        return usb, ff

    def take_usb(self, seconds, name, during=None):
        """what plays before the note fills the take; what the note starts, from 0.35 s on"""
        x = 1e-5 * rng.standard_normal((int(seconds * RATE), 6))
        before = set(self.playing)
        if before:
            x[:, 1] += music(seconds, seed=9)[:, 0]
        if during:
            during()
            if self.playing - before:
                x[int(0.35 * RATE):, 0] += music(seconds - 0.35)[:, 0]
        return x

    def usb_lent(self):
        return self.lent

    def seen(self):
        return f"card {self.card()}, host: boot {self.boot}"

    def reads(self, why, n):
        self.reads_n.append(why)
        return [f"reads-{n}"]


def run(fn, fake, **kw):
    with tempfile.TemporaryDirectory() as d:
        fake.out = d
        with contextlib.redirect_stdout(io.StringIO()):          # the gate's own lines: in its verdict
            rc = fn(fake, d, sleep=lambda s: None, **kw)
        text = open(os.path.join(d, fn.__name__ + ".txt")).read()
    return rc, text


rc, text = run(gates.soak, Fake(None), takes=3, every=600, length=10)
check("soak, clean: pass", rc == 0 and text.splitlines()[-1].startswith("PASS"), text)
check("soak: the pad started and stopped by its note", "pad q0" in text)
check("soak: its verdict's second line is what it sees", text.splitlines()[1].startswith("seen: card 3"), text)
f = Fake(None, crunch_at=2)
rc, text = run(gates.soak, f, takes=4, every=600, length=10)
check("soak, a crunch at the third take: fail, named, the reads taken",
      rc == 1 and "crunch at take 2" in text and f.reads_n == ["crunch at take 2"], text)
rc, text = run(gates.soak, Fake(None, here=False))
check("soak without the unit's card: could not run, and says why", rc == 1 and "could not run" in text, text)

f = Fake(None)
rc, text = run(gates.bootloop, f, cycles=3, pads=tuple(range(16)))
check("bootloop, every pad back each time: pass", rc == 0 and "3 power cycles" in text, text)
check("bootloop: one cycle a boot, boot 0 included", f.powers == ["cycle 5"] * 4, f.powers)
check("bootloop: what it sees first, the card each boot came back as",
      text.splitlines()[1].startswith("seen: ") and "boot 0 (the reference, card 3)" in text and "boot 3 (card 3)" in text,
      text)
check("bootloop: a stop note for each pad that kept playing", f.notes.count(0) == 2 * 4, f.notes.count(0))
f = Fake(None, dead={2: {5}})
rc, text = run(gates.bootloop, f, cycles=4, pads=tuple(range(16)))
check("bootloop, pad q5 silent after boot 2: the catch, the reads, stop there",
      rc == 1 and "boot 2" in text and "q5" in text and len(f.powers) == 3 and len(f.reads_n) == 1, text)
f = Fake(None, loaded={0, 1}, dead={1: {7}})
rc, text = run(gates.bootloop, f, cycles=2, pads=tuple(range(16)))
check("bootloop: a pad silent at boot 0 is not a catch later", rc == 0, text)
rc, text = run(gates.bootloop, Fake(None, loaded=set()), cycles=2, pads=(0, 1))
check("bootloop: no pad at boot 0 - nothing to compare, fail", rc == 1 and "no pad sounded" in text, text)


class Gone(Fake):
    def card(self):
        return None if self.boot >= 1 else "3"


rc, text = run(gates.bootloop, Gone(None), cycles=2, pads=(0,))
check("bootloop: a unit that never comes back is not taken for a catch", rc == 1 and "did not come back" in text,
      text)
check("bootloop: a unit lost, what it sees then, before the FAIL",
      text.splitlines()[-2] == "seen: card None, host: boot 1", text)

# the reads without the unit's USB: the record, then the peeks said skipped
with tempfile.TemporaryDirectory() as d:
    u = gates.Unit(d)
    u.take_usb = lambda seconds, name, during=None: np.zeros((10, 6))
    u.usb_lent = lambda: False
    lines = u.reads("test", 0)
check("the reads without the unit's USB: record, peeks SKIPPED and why",
      any("record:" in x for x in lines) and any("SKIPPED" in x and "usb:blackbox" in x for x in lines), lines)

print(f"{'ALL PASS' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
