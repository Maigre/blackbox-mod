#!/usr/bin/env python3
"""suites.py - fork-only (bench/, never in a PR): run every test suite of the tree in a pool as wide as the box, the
long ones as shards of their own file (bench/shard.py), and leave what check.sh's tally reads: out/<suite>.log and
out/<suite>.rc, one of each per suite however many shards it ran as (the shards' logs joined in order, the first
non-zero exit). Run from the tree's root by check.sh, with the interpreter the suites need.

  suites.py JOBS            run them all, JOBS at a time
  suites.py --plan JOBS     print the jobs it would start, longest first, and the shard counts
  suites.py --table         the timing table (notes/dev-setup.md) from the last run's out/check-times.tsv

Each job's wall and CPU seconds (user + sys, from the kernel's rusage of that process) go to out/check-times.tsv.
bench/shards/times.tsv holds, per suite, the seconds measured on mgr-ran (the queue's order: longest first) and how
many shards it runs as (at most JOBS); a suite it does not know runs whole, queued as if it took UNKNOWN_S (120) s.
A suite shards only where its plan (bench/shard.py SUITE --plan N) shows shards that cost less than the whole: one
whose statements all hang on the ones before (one emulator, its state carried on) gains nothing from it.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TIMES = os.path.join(HERE, "shards", "times.tsv")
UNKNOWN_S = 120.0
LAST = "out/check-times.tsv"


def known_times():
    """suite -> (CPU seconds, shards)"""
    t = {}
    try:
        for line in open(TIMES):
            if line.strip() and not line.startswith("#"):
                f = line.rstrip("\n").split("\t")
                t[f[0]] = (float(f[2]), int(f[3]))        # suite, wall, cpu, shards
    except OSError:
        pass
    return t


def jobs(width):
    """[(est. CPU s, suite, shard i, of n)], longest first"""
    suites = sorted(f for f in os.listdir(".") if f.startswith("test_") and f.endswith(".py"))
    known = known_times()
    out = []
    for s in suites:
        cpu, n = known.get(s, (UNKNOWN_S, 1))
        n = max(1, min(n, width))
        for i in range(1, n + 1):
            out.append((cpu / n, s, i, n))
    return sorted(out, key=lambda j: (-j[0], j[1], j[2]))


def run(width):
    todo = jobs(width)
    py = sys.executable
    os.makedirs("out", exist_ok=True)
    for s in {j[1] for j in todo}:
        for ext in (".rc", ".log"):
            try:
                os.remove(f"out/{s}{ext}")
            except OSError:
                pass
    running, done = {}, []
    t_start = time.monotonic()
    while todo or running:
        while todo and len(running) < width:
            est, s, i, n = todo.pop(0)
            log = f"out/{s}.log" if n == 1 else f"out/{s}.{i}of{n}.log"
            cmd = [py, s] if n == 1 else [py, os.path.join(HERE, "shard.py"), s, f"{i}/{n}"]
            f = open(log, "w")
            p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
            running[p.pid] = (p, f, s, i, n, log, time.monotonic())
        pid, status, ru = os.wait4(-1, 0)
        if pid not in running:
            continue
        p, f, s, i, n, log, t0 = running.pop(pid)
        p.returncode = os.waitstatus_to_exitcode(status)
        f.close()
        done.append((s, i, n, log, p.returncode, time.monotonic() - t0, ru.ru_utime + ru.ru_stime))
        if n > 1 and sum(1 for d in done if d[0] == s) == n:
            merge(s, n, done)
        elif n == 1:
            with open(f"out/{s}.rc", "w") as r:
                r.write(f"{p.returncode}\n")
    wall = time.monotonic() - t_start
    with open(LAST, "w") as t:
        t.write(f"# suite\tshard\twall s\tcpu s\texit\t(pool {width}, {wall:.0f} s for every suite, "
                f"{os.uname().nodename}, {time.strftime('%Y-%m-%d %H:%M')}, load {os.getloadavg()[0]:.1f})\n")
        for s, i, n, log, rc, w, c in sorted(done):
            t.write(f"{s}\t{i}/{n}\t{w:.1f}\t{c:.1f}\t{rc}\n")


def merge(s, n, done):
    """the shards of one suite: one log (theirs in order), one exit status (the first that is not 0)"""
    mine = sorted((d for d in done if d[0] == s), key=lambda d: d[1])
    with open(f"out/{s}.log", "w") as out:
        for d in mine:
            out.write(open(d[3]).read())
    rc = next((d[4] for d in mine if d[4] != 0), 0)
    with open(f"out/{s}.rc", "w") as r:
        r.write(f"{rc}\n")


def table():
    """per suite: its wall (the longest shard's) and CPU (all its shards') seconds"""
    rows = {}
    head = ""
    for line in open(LAST):
        if line.startswith("#"):
            head = line.strip("# \n").split("\t")[-1]
            continue
        s, sh, w, c, rc = line.rstrip("\n").split("\t")
        r = rows.setdefault(s, [0, 0.0, 0.0, 0])
        r[0] = int(sh.split("/")[1])
        r[1] = max(r[1], float(w))
        r[2] += float(c)
        r[3] = r[3] or int(rc)
    print(f"| suite | shards | wall s | CPU s |  ({head})")
    print("|---|---:|---:|---:|")
    for s, (n, w, c, rc) in sorted(rows.items(), key=lambda x: -x[1][2]):
        print(f"| `{s}` | {n} | {w:.1f} | {c:.1f} |" + (" failed |" if rc else ""))
    print(f"| all | | | {sum(r[2] for r in rows.values()):.0f} |")


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    if argv[1] == "--plan":
        for est, s, i, n in jobs(int(argv[2])):
            print(f"{est:7.1f} s  {s}" + (f"  shard {i}/{n}" if n > 1 else ""))
    elif argv[1] == "--table":
        table()
    else:
        run(int(argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
