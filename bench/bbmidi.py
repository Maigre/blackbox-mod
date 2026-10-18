"""Bench tool: MIDI to the Blackbox over its USB MIDI port (raw ALSA device), for unattended bench runs.

    bbmidi.py serve BPM                hold the port: MIDI Start, then 24 ppqn clock at BPM until stopped (SIGTERM or a
                                       `quit` command: MIDI Stop first); takes commands meanwhile from the FIFO below
    bbmidi.py note NOTE [VEL] [CH]     a note on (Toggle pads start or stop on it at their Quant), the note off 50 ms on
    bbmidi.py bpm BPM                  the served clock's tempo (no server: error)
    bbmidi.py start | stop | quit      MIDI Start / Stop through the server; quit ends it (Stop first)
    bbmidi.py raw HEX...               bytes as given, e.g. raw 90 24 64
    bbmidi.py clock BPM SECONDS [--start] [--stop]   a one-off clock without a server

The raw MIDI device is exclusive: a second open blocks until the first closes. So with a server up (its FIFO exists
and its pid is alive) every command goes through the FIFO; without one, `note` / `raw` open the device themselves.
The unit follows the clock with Clock receive = USB Device (Tools > MIDI). Pad Note "Default" = 36 + q on the Global
In channel (1). CH is 1..16. Fork-only tool, like bench/bbusb.py.
"""
import os
import select
import signal
import sys
import time

RUN = os.environ.get("BBMIDI_RUN", os.path.join(os.environ.get("TMPDIR", "/tmp"), "bbmidi"))   # its FIFO, pid
FIFO, PIDF = RUN + ".fifo", RUN + ".pid"


def device():
    for line in open("/proc/asound/cards"):
        parts = line.split()
        if len(parts) > 1 and parts[1] == "[Blackbox":
            path = f"/dev/snd/midiC{parts[0]}D0"
            if os.path.exists(path):
                return path
    sys.exit("no ALSA card named Blackbox with a MIDI device (is the power jack on this machine's USB?)")


def server_alive():
    try:
        pid = int(open(PIDF).read())
        os.kill(pid, 0)
        return os.path.exists(FIFO)
    except (OSError, ValueError):
        return False


def to_server(line):
    fd = os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK)
    try:
        os.write(fd, (line.strip() + "\n").encode())
    finally:
        os.close(fd)


def note_bytes(args):
    note = int(args[0]); vel = int(args[1]) if len(args) > 1 else 100; ch = (int(args[2]) if len(args) > 2 else 1) - 1
    return [0x90 | ch, note & 0x7F, vel & 0x7F], [0x80 | ch, note & 0x7F, 0]


def serve(bpm):
    if server_alive():
        sys.exit("a server is already running")
    if os.path.exists(FIFO):
        os.unlink(FIFO)
    os.mkfifo(FIFO)
    open(PIDF, "w").write(str(os.getpid()))
    dev = os.open(device(), os.O_WRONLY)
    rd = os.open(FIFO, os.O_RDONLY | os.O_NONBLOCK)
    keep = os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK)        # keeps the FIFO open between writers
    state = {"bpm": float(bpm), "run": True, "offs": []}

    def end(*_):
        state["run"] = False
    signal.signal(signal.SIGTERM, end)
    signal.signal(signal.SIGINT, end)
    os.write(dev, bytes([0xFA]))
    period = 60.0 / (state["bpm"] * 24.0); t_next = time.perf_counter(); buf = b""
    try:
        loop(dev, rd, state, period, t_next, buf)
    except OSError as e:                                     # the unit left USB (ENODEV): end cleanly
        print(f"bbmidi serve: {e}; the unit is gone, the server ends", file=sys.stderr)
        state["gone"] = True
    if not state.get("gone"):
        os.write(dev, bytes([0xFC]))
    for fd in (dev, rd, keep):
        try:
            os.close(fd)
        except OSError:
            pass
    for p in (FIFO, PIDF):
        try:
            os.unlink(p)
        except OSError:
            pass


def loop(dev, rd, state, period, t_next, buf):
    while state["run"]:
        now = time.perf_counter()
        if now >= t_next:
            os.write(dev, bytes([0xF8]))
            t_next += period
            if t_next < now:                                 # never catch up in a burst after a stall
                t_next = now + period
        for due, data in list(state["offs"]):
            if now >= due:
                os.write(dev, bytes(data)); state["offs"].remove((due, data))
        r, _, _ = select.select([rd], [], [], max(0.0, min(0.002, t_next - time.perf_counter())))
        if r:
            try:
                buf += os.read(rd, 4096)
            except BlockingIOError:
                pass
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd, *args = line.decode().split() or [""]
                if cmd == "note":
                    on, off = note_bytes(args); os.write(dev, bytes(on)); state["offs"].append((time.perf_counter() + 0.05, off))
                elif cmd == "raw":
                    os.write(dev, bytes(int(h, 16) for h in args))
                elif cmd == "bpm":
                    state["bpm"] = float(args[0]); period = 60.0 / (state["bpm"] * 24.0)
                elif cmd == "start":
                    os.write(dev, bytes([0xFA]))
                elif cmd == "stop":
                    os.write(dev, bytes([0xFC]))
                elif cmd == "quit":
                    state["run"] = False


def main(argv):
    if not argv:
        sys.exit(__doc__)
    cmd, args = argv[0], argv[1:]
    if cmd == "serve":
        return serve(args[0] if args else 120)
    if server_alive():
        if cmd in ("note", "raw", "bpm", "start", "stop", "quit"):
            return to_server(" ".join([cmd, *args]))
        sys.exit(f"{cmd}: not with a server running (it holds the port)")
    if cmd in ("bpm", "start", "stop", "quit"):
        sys.exit(f"{cmd}: no server running")
    fd = os.open(device(), os.O_WRONLY)
    try:
        if cmd == "note":
            on, off = note_bytes(args); os.write(fd, bytes(on)); time.sleep(0.05); os.write(fd, bytes(off))
        elif cmd == "raw":
            os.write(fd, bytes(int(h, 16) for h in args))
        elif cmd == "clock":
            bpm, secs = float(args[0]), float(args[1]); period = 60.0 / (bpm * 24.0)
            if "--start" in args:
                os.write(fd, bytes([0xFA]))
            t0 = time.perf_counter(); n = 0
            while t0 + n * period - t0 < secs:
                while time.perf_counter() < t0 + n * period:
                    time.sleep(0.0005)
                os.write(fd, bytes([0xF8])); n += 1
            if "--stop" in args:
                os.write(fd, bytes([0xFC]))
            print(f"{n} clocks at {bpm} BPM")
        else:
            sys.exit(__doc__)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main(sys.argv[1:])
