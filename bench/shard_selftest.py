"""shard_selftest.py - fork-only (bench/): a small suite in the shape of the real ones, for bench/shard.py's own proof.

  python3 bench/shard.py bench/shard_selftest.py --prove 3                 the shards' output is the whole's
  MUTANT=1 python3 bench/shard.py bench/shard_selftest.py --prove 3        a failing case fails its shard, and the
  MUTANT=2 python3 bench/shard.py bench/shard_selftest.py --prove 3        whole; one in a statement another shard
                                                                           runs quietly fails only its own shard
Three sections; state carried from one to the next (a list grown in place, an object changed through a method, a
function reading a global set later, a function changing what it is handed, a method changing a module global, a
method named like a read-only one (copy) that writes its object), so a shard that skipped what it needs would print
something else or crash. The last case reads the failure counter: it must run once, not in every shard's verdict.
"""
import os
import sys

MUTANT = int(os.environ.get("MUTANT", "0"))
fails = 0
MODE = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


class Meter:
    def __init__(self):
        self.n = 0
        self.mem = {}

    def add(self, k):
        self.n += k

    def set_mode(self, m):                             # a method that changes a module global (review of #t-055)
        global MODE
        MODE = m

    def copy(self, vals):                              # named like dict.copy, but writes its object (Screen.copy)
        self.mem.update(vals)


def scaled(x):
    return x * SCALE                                   # SCALE: a global the caller's section sets


def widen(meter, k):
    meter.add(k)                                       # changes what it is handed: its caller's statement changes m


def render():
    return MODE * 7                                    # reads the global a method set


# ==== 1. the list and the meter
acc = []
m = Meter()
for i in range(3):                                     # MUTANT=2 fails here: section 2 runs this loop quietly
    acc.append(i)
    m.add(i)
    check(f"step {i} taken", MUTANT != 2 or i != 1)
check("the list holds three", len(acc) == 3)
check("the first section's own case", MUTANT != 1)     # MUTANT=1 fails here, in shard 1 only
rig = Meter()
rig.set_mode(2)                                        # rig is never read again: only MODE carries this on
m.copy({"a": 1})

# ==== 2. what the first left
SCALE = 10
total = sum(acc)
check(f"the sum is the first section's ({total})", total == 3)
check(f"the meter carried on ({m.n})", m.n == 3)
check(f"a function reads a global set here ({scaled(total)})", scaled(total) == 30)
check(f"a global a method set in the first ({render()})", render() == 14)
print("     an info line, as the suites print them")
widen(m, 100)

# ==== 3. what the second changed
acc.append(10)
m.add(10)
check(f"the list grew in place ({acc})", acc == [0, 1, 2, 10])
check(f"the meter too, widened by the second ({m.n})", m.n == 113)
check(f"SCALE is still the second section's ({scaled(1)})", scaled(1) == 10)
check(f"what copy() wrote in the first ({m.mem})", m.mem == {"a": 1})
if MUTANT == 0:
    check("nothing failed before the verdict", fails == 0)

print(f"{fails} failed")
sys.exit(1 if fails else 0)
