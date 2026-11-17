"""Bench tool (fork-only, like bbpower.py): hand the unit's card to this machine and back, through the USB-SD-Mux FAST
in its slot (Linux Automation; on mgr-ran since 2026-11-17, serial 00048.02052).

  bbsd.py where    which side holds the card, the mux's device, the unit's power port
  bbsd.py host     the unit off (bbpower.py's port), the card to this machine, mounted; prints where
  bbsd.py dut      the card unmounted and back in the unit, the unit on and back on USB; its uptime and free sample memory

The unit is OFF whenever the card moves: switching under a running unit is pulling its card mid-read (stock's FatFs in
pcmStreamer, bank 2's write at boot - src/b2load.c). `dut` unmounts first: the desktop automounts the card read-write the
moment it reaches this side, so it must be flushed and released before it leaves.

Needs `usbsdmux` (`uv tool install usbsdmux`) and the vendor's udev rule, once, as root, at
/etc/udev/rules.d/99-usbsdmux.rules (contrib/udev/ in github.com/linux-automation/usbsdmux; it names the mux
/dev/usb-sd-mux/id-<serial>, group plugdev), then `udevadm control --reload` and
`udevadm trigger --action=add --subsystem-match=scsi_generic`. The mount goes through udisksctl (a desktop session).

Proven on mgr-ran 2026-11-17: `host` showed the unit's card (vfat 6AF0-0F5D, 14.8 GB: 37.5.0's BLACKBOX.BIN and
BBEXTRA.BIN, the presets); after `dut` the unit booted (uptime 19 s) on its last preset, the pads named after the
card's takes (bench/bbshot.py), 63 MB of sample memory taken.
"""
import glob
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bbpower  # noqa: E402


def tool():
    t = shutil.which("usbsdmux") or os.path.expanduser("~/.local/bin/usbsdmux")
    if not os.path.exists(t):
        sys.exit("no usbsdmux: `uv tool install usbsdmux` (see this file's header)")
    return t


def mux():
    found = sorted(glob.glob("/dev/usb-sd-mux/id-*"))
    if not found:
        sys.exit("no /dev/usb-sd-mux/id-*: the mux is not on USB, or the udev rule is missing (see this file's header)")
    if len(found) > 1 and not os.environ.get("BBSD"):
        sys.exit("several muxes (%s): name one with BBSD=/dev/usb-sd-mux/id-..." % " ".join(found))
    return os.environ.get("BBSD") or found[0]


def run(*args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        sys.exit("%s failed:\n%s" % (" ".join(args), (r.stdout + r.stderr).strip()))
    return r.stdout.strip()


def state(sg):
    return run(tool(), sg, "get")


def card(sg):
    """the card's block device on this side (its first partition if it has one), None while the mux holds it away"""
    serial = os.path.basename(sg)[len("id-"):]
    for pattern in ("-0:0-part1", "-0:0"):
        for dev in glob.glob("/dev/disk/by-id/usb-LinuxAut_*%s%s" % (serial, pattern)):
            size = subprocess.run(["lsblk", "-bndo", "SIZE", dev], capture_output=True, text=True).stdout.strip()
            if size.isdigit() and int(size) > 0:
                return dev
    return None


def mounted(dev):
    out = subprocess.run(["lsblk", "-no", "MOUNTPOINTS", dev], capture_output=True, text=True).stdout.split("\n")
    return next((m.strip() for m in out if m.strip()), "")


def until(test, seconds):
    t = time.time()
    while time.time() - t < seconds:
        got = test()
        if got:
            return got
        time.sleep(0.25)
    return None


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "where"
    sg = mux()
    at = bbpower.where()
    if cmd == "where":
        dev = card(sg)
        print("mux %s: %s; card here %s%s; unit on hub %s port %s%s" % (
            sg, state(sg), dev or "no", (" at " + mounted(dev)) if dev and mounted(dev) else "",
            at[0], at[1], "" if bbpower.find() else " (not on USB)"))
    elif cmd == "host":
        if bbpower.find():
            bbpower.switch(at, "off")
            if bbpower.wait(False, 5) is None:
                sys.exit("the unit is still on USB after its port was cut: card NOT moved")
        run(tool(), sg, "host")
        dev = until(lambda: card(sg), 20)
        if not dev:
            sys.exit("mux says %s but no card appeared here in 20 s (is a card in the mux?)" % state(sg))
        subprocess.run(["udevadm", "settle", "-t", "5"])   # the disk has a size a moment before its partition's link
        dev = card(sg) or dev
        where = until(lambda: mounted(dev), 5)        # the desktop's automount, else udisks by hand
        if not where:
            run("udisksctl", "mount", "-b", dev)
            where = mounted(dev)
        print("card on this machine: %s at %s (the unit is off; `bbsd.py dut` gives it back)" % (dev, where))
    elif cmd == "dut":
        dev = card(sg)
        if dev and mounted(dev):
            subprocess.run(["sync"])
            run("udisksctl", "unmount", "-b", dev)
        run(tool(), sg, "dut")
        bbpower.switch(at, "on")
        if bbpower.wait(True, 60) is None:
            sys.exit("card back in the unit, but the unit did not come back on USB within 60 s (hub %s port %s)" % at)
        up = None
        for _ in range(15):
            time.sleep(1)
            up = bbpower.uptime()
            if up is not None and up > 5:              # past the boot's preset load
                break
        line = "card back in the unit; the unit is on USB"
        if up is not None:
            import bbusb
            free = bbusb.word(0x24000088) - bbusb.word(0x2400008C)
            line += ", uptime %.0f s, sample memory free %s B (bbshot.py for its screen)" % (up, format(free, ","))
        print(line)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
