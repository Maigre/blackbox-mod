"""Bench tool (fork-only, like bbusb.py): switch the unit's power from this machine.

The Blackbox is powered by the USB port its POWER jack is cabled to, so cutting that hub port's power is a power
cycle - with nobody at the desk. Needs `uhubctl` and a hub that really cuts a port's power (many only cut the
data lines); `cycle` proves it by the unit's own uptime counter.

  bbpower.py where             the hub and port the unit is on (or the one remembered from the last `off`)
  bbpower.py off | on          cut / restore that port's power
  bbpower.py cycle [SECONDS]   off, SECONDS (default 5), on, wait until the unit is back on USB; on a dev build,
                               its uptime before and after (a unit that kept running was not power-cycled)

Permissions: uhubctl needs write access to the hub's device node and to its ports' `disable` switch in sysfs.
Once, as root (hubs only, group plugdev; mgr-ran has it as /etc/udev/rules.d/61-usb-hub-power.rules):
  SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{bDeviceClass}=="09", MODE="0664", GROUP="plugdev"
  SUBSYSTEM=="usb", DRIVER=="hub", RUN+="/bin/sh -c \\"chown -f root:plugdev $sys$devpath/*port*/disable || true\\"", \\
    RUN+="/bin/sh -c \\"chmod -f 664 $sys$devpath/*port*/disable || true\\""
then `udevadm control --reload && udevadm trigger --attr-match=subsystem=usb`.

Proven on mgr-ran 2026-11-12: the unit on hub 9-1.4.4 (0bda:5411, behind a 2109:2822), port 1 - uptime 258 s
before, 5 s after, reset cause power-on.
"""
import glob
import os
import struct
import subprocess
import sys
import time

VID, PID = "1209", "0003"
MEMO = os.path.expanduser("~/.cache/blackbox-mod/power-port")     # where the unit was, for `on` after an `off`
UPTIME = 0x2400A58C          # stock's audio-block counter (the watchdog's clock, src/b2load.c): 375 a second


def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def find():
    """(hub location, port) of the unit as uhubctl names them, from sysfs; None when it is not on USB"""
    for d in glob.glob("/sys/bus/usb/devices/*"):
        if read(d + "/idVendor") == VID and read(d + "/idProduct") == PID:
            name = os.path.basename(d)                           # "9-1.4.4.1": bus 9, ports 1, 4, 4, 1
            if "." in name:
                return tuple(name.rsplit(".", 1))
            return tuple(name.split("-", 1))                     # on a root hub: "9-2" -> hub "9", port "2"
    return None


def where():
    at = find()
    if at:
        os.makedirs(os.path.dirname(MEMO), exist_ok=True)
        with open(MEMO, "w") as f:
            f.write("%s %s\n" % at)
        return at
    memo = read(MEMO).split()
    if len(memo) == 2:
        return tuple(memo)
    sys.exit("no Blackbox (1209:0003) on USB and no remembered port: plug it in once, then `bbpower.py where`")


def switch(at, action):
    r = subprocess.run(["uhubctl", "-l", at[0], "-p", at[1], "-a", action], capture_output=True, text=True)
    if r.returncode or "permission" in (r.stdout + r.stderr).lower():
        sys.exit("uhubctl failed (permissions? see this file's header):\n" + (r.stdout + r.stderr).strip())


def uptime():
    """seconds since boot on a dev build (the peek), None otherwise"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import bbusb
        return struct.unpack("<I", bbusb.peek(UPTIME, 4))[0] / 375.0
    except (SystemExit, Exception):
        return None


def wait(present, seconds):
    t = time.time()
    while time.time() - t < seconds:
        if (find() is not None) == present:
            return time.time() - t
        time.sleep(0.25)
    return None


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "where"
    at = where()
    if cmd == "where":
        print("hub %s port %s%s" % (at[0], at[1], "" if find() else " (remembered: the unit is not on USB now)"))
    elif cmd in ("off", "on"):
        switch(at, cmd)
        print("%s: hub %s port %s" % (cmd, at[0], at[1]))
    elif cmd == "cycle":
        hold = float(argv[2]) if len(argv) > 2 else 5.0
        before = uptime() if find() else None
        switch(at, "off")
        gone = wait(False, 5)
        time.sleep(hold)
        switch(at, "on")
        back = wait(True, 60)
        if back is None:
            sys.exit("the unit did not come back on USB within 60 s (hub %s port %s)" % at)
        time.sleep(3)                                            # the dev build answers a few seconds after it enumerates
        after = None
        for _ in range(10):
            after = uptime()
            if after is not None:
                break
            time.sleep(1)
        print("cycled hub %s port %s: off the bus %s, back on USB %.1f s after power-on" % (
            at[0], at[1], "at once" if gone is not None else "NOT seen", back))
        if before is not None and after is not None:
            print("uptime %.0f s before, %.0f s after: %s" % (
                before, after, "the unit lost power and booted" if after < before else
                "THE UNIT KEPT RUNNING - this port cuts the data lines only, not the power"))
            if after >= before:
                sys.exit(1)
        else:
            print("no uptime to compare (not a dev build, or it was off before): power cut not proven")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
