# Dev setup — build and test this fork on a Linux box (no root needed)

Done on mgr-ran 2026-10-15; the same recipe equips dev37 (the loop box) or any Linux machine.

```sh
# 1. Toolchain + Ghidra under /srv/dev (any user-writable prefix works)
mkdir -p /srv/dev/dl /srv/dev/toolchains /srv/dev/venvs /srv/dev/firmware/docs
cd /srv/dev/dl
curl -sLO https://developer.arm.com/-/media/Files/downloads/gnu/14.2.rel1/binrel/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi.tar.xz
gh release download --repo NationalSecurityAgency/ghidra --pattern 'ghidra_*_PUBLIC_*.zip' -D .   # needs Java 21+
cd /srv/dev/toolchains
tar -xJf /srv/dev/dl/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi.tar.xz && mv arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi arm-gnu-14.2
unzip -q /srv/dev/dl/ghidra_*_PUBLIC_*.zip -d /srv/dev/toolchains        # -> /srv/dev/toolchains/ghidra_12.1.4_PUBLIC

# 2. Python venv for the Unicorn suites and pyghidra
uv venv --python 3.12 /srv/dev/venvs/bb
VIRTUAL_ENV=/srv/dev/venvs/bb uv pip install unicorn capstone numpy scipy pyghidra

# 3. The stock firmware, once, outside every clone (public download from 1010music; never in git)
#    /srv/dev/firmware/BLACKBOX-3.1.9.bin  sha256 281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d

# 4. In the clone
cd ~/Bakery/blackbox-mod
ln -sf /srv/dev/firmware/BLACKBOX-3.1.9.bin firmware/BLACKBOX-3.1.9.bin   # gitignored
ln -sfn /srv/dev/venvs/bb .venv && echo .venv >> .git/info/exclude        # check.sh prefers .venv/bin/python
export PATH=/srv/dev/toolchains/arm-gnu-14.2/bin:$PATH
./check.sh            # build (dev), patch every set, run every suite -> "N suites, 0 failed", exit 0 only then
```

Release images (what goes on the card): `RELEASE=1 ./build.sh && python3 patch.py cave` (cave-only) or the
full set `python3 patch.py solo slice duck chord cond filter cpu od comp seqfix fx2 munchi master fault cave`.
`RELEASE=1` compiles the USB peek/poke out and shows `RELEASE_NAME` (`src/release.h`, 37.x.y; dev builds `DEV_NAME`, 37.x.yd) on TOOLS.
**Rebuild without `RELEASE=1` before running the suites** (they expect the dev build). Since 37.2.0 the Clip Window
runs from bank 2 (D-017, D-018): `out/BBEXTRA.BIN` from the same build goes on the card beside `BLACKBOX.bin` (D-008's
install without it is over).

Ghidra (the RE helpers in `ghidra/`): the scripts default to the Homebrew paths and read `GHIDRA_INSTALL_DIR`,
`JAVA_HOME` and `GHIDRA_PROJ` (where the analysed project lives; default `ghidra/`) from the environment. Keep the
project outside the clone so a fresh checkout or a loop worktree can reuse it:

```sh
export JAVA_HOME=/srv/dev/toolchains/jdk-21 GHIDRA_INSTALL_DIR=/srv/dev/toolchains/ghidra_12.1.4_PUBLIC GHIDRA_PROJ=/srv/dev/firmware/ghidra
mkdir -p "$GHIDRA_PROJ" && /srv/dev/venvs/bb/bin/python ghidra/import.py       # once: import + auto-analysis, 2,577 functions
/srv/dev/venvs/bb/bin/python ghidra/gq.py callers 0x0808c158                    # then any gq.py query
```

(dev37 has no system Java; `jdk-21` is a Temurin 21 tarball. mgr-ran's system Java 21/25 are runtimes without
`javac`, which Ghidra's launcher refuses, so mgr-ran uses a Temurin 21 tarball too: `/srv/dev/toolchains/jdk-21.0.12.1+1`.)

For grep-speed RE, export the analysed project once as text, **outside the clone** (it is 1010music's code):
`GHIDRA_OUT=/srv/dev/firmware/ghidra-out python ghidra/dump_all.py` writes `out_all.c` (every function decompiled) and
`python ghidra/export_listing.py /srv/dev/firmware/ghidra-out` writes `listing.txt` (every instruction with its call
and data references) + `functions.tsv`. On mgr-ran, `/srv/dev/bin/bb-env` sets the whole environment and
`/srv/dev/bin/gq <cmd>` runs `gq.py` under a lock, so parallel sessions never collide on the project.

Facts: this toolchain's output is not byte-identical to upstream's releases (D-010); the host CPU here has no FMA,
hence `HOST_TOL = 1e-5` in `test_machine.py` (D-009); `check.sh` prints `N suites, M failed` and exits non-zero
when any failed, so a verdict is its exit status, or `./check.sh 2>&1 | tail -1 | grep -q ', 0 failed'` — that line is
the hub's `verify:`.

## The check's time, a box's readiness, a check of any branch (fork-only, `bench/`)

**What a box lacks**: `bench/doctor.sh` (`--ghidra` to require Ghidra too, `-C <worktree>` for another tree) checks
the Arm toolchain, shasum, the suites' Python and its modules, the stock image's sha256 and a C compiler for
`host/libdsp`, prints each miss with the line that fixes it, and exits 0 only when `./check.sh` can run. A box with no C
compiler and no root (dev37) can use zig's: `VIRTUAL_ENV=/srv/dev/venvs/bb uv pip install ziglang` and
`export CC="/srv/dev/venvs/bb/bin/python -m ziglang cc"`; `host/build.sh` then builds a libdsp that the five suites
using it (test_confetti, test_filter, test_machine, test_prism, test_smash) pass against, as against gcc's.

**How the suites run**: `check.sh` sizes its pool to the box (`getconf _NPROCESSORS_ONLN`, `CHECK_JOBS=n` to change
it) and hands the suites to `bench/suites.py`, which queues them longest first (`bench/shards/times.tsv`) and runs
`test_clipwin.py` as shards of its own file; one log and one exit status per suite come back, so the tally, its last
line `N suites, M failed` and the exit status are what they were. Each job's wall and CPU seconds go to
`out/check-times.tsv`; `python3 bench/suites.py --table` prints them as below.

**The whole check, measured** (mgr-ran, 2026-11-12 16:43 to 16:56, pool 8, load average 4.4 at the start and up to
12.7, another session's test_clipwin running beside it): `32 suites, 0 failed`, exit 0, in 770 s with the build,
4 362 CPU s. Last to end: test_clipwin's shard 2 (765 s; 567 CPU s) and test_munchi (721 s; 546 CPU s). Eight jobs on
four cores run two to a core, at about half the speed of a suite alone (test_munchi: 397 CPU s run two at a time, 546
here). Before, the check took as long as test_clipwin in one process: 3 116 s here beside its own shards (load 10 to
20), 9.5 to 11.6 min on a calm box (the review). The five-minute target is not met: test_munchi, sequential, is now
the floor (~400 to 550 CPU s on this box, by load), and a calm mgr-ran was not available to measure the check on; the
only lever left under it is the instruction count (below).

**Shards** (`bench/shard.py`): shard I of N runs a contiguous run of a suite's sections (cut at its `# ===` / `# ---`
headers, and with a profile around any statement over 2 % of its seconds) and, with their output dropped and the
failure count kept, the statements of the other sections that its own read: the assignment reaching each name, and
every statement between that may change that object (a subscript or attribute store, a method call, a function that
does either to a global or to what it is handed). It is worked out from the source at each run: the suite is not edited
and its cases do not move, so the JOEBOX 2 merge's edits shard themselves. The planner balances the shards on the CPU
seconds of each statement in `bench/shards/<suite>.tsv` (`python3 bench/shard.py <suite> --profile` rewrites it; a
statement it does not hold counts nothing, so re-profile after big edits). The proof, to run again after any change
to a sharded suite: `python3 bench/shard.py test_clipwin.py --prove 6` runs the suite whole and as its six shards and
says PROVEN only when the shards' output, concatenated, is the whole run's line for line, their checks add up, and
each shard's exit status says whether its own lines hold a FAIL (`bench/shard_selftest.py`, with `MUTANT=1|2`, shows
a failing case failing its shard alone, also when another shard runs its statement quietly).
Only `test_clipwin.py` shards: test_munchi, test_relapse and test_confetti, also over two minutes, are one emulator
carried from statement to statement (the delay lines, `run.t`, the settings), so any later shard has to replay
everything before it (`--plan` shows it); they run whole.

**The timing table** (mgr-ran, i7-3770K: 4 cores, 8 threads; 2026-11-12, each suite run alone, two at a time, beside
four other sessions, load average 3 to 12; test_clipwin's row is its whole run beside its own six shards, load 10 to
20. On these hyperthreads a loaded box charges up to ~2x the CPU seconds of an idle one: the review's 9.5 to 11.6 min
for test_clipwin alone is the idle figure. The fourth column is the same suite with `emu.py`'s instruction count left
out, a trial outside the tree, see below; `bench/shards/times.tsv` holds the first three for the queue):

| suite | wall s | CPU s | CPU s, no count (trial) | shards |
|---|---:|---:|---:|---:|
| `test_clipwin.py` | 3116.0 | 2366.1 | 1119.5 (1 case fails) | 6 |
| `test_munchi.py` | 404.4 | 397.4 | 61.9 | 1 |
| `test_relapse.py` | 280.8 | 276.0 | 45.6 | 1 |
| `test_confetti.py` | 191.6 | 187.5 | 22.1 | 1 |
| `test_fx2.py` | 93.2 | 91.1 | 10.1 | 1 |
| `test_switch.py` | 76.3 | 75.6 | 100.6 | 1 |
| `test_smash.py` | 76.2 | 75.0 | 10.6 | 1 |
| `test_b2load.py` | 34.3 | 33.7 | 27.9 | 1 |
| `test_prism.py` | 15.6 | 15.3 | 1.6 | 1 |
| `test_master.py` | 13.7 | 13.4 | 1.5 | 1 |
| `test_rotate.py` | 6.1 | 6.1 | 9.1 | 1 |
| `test_comp.py` | 5.8 | 5.7 | 0.7 | 1 |
| `test_insert.py` | 4.7 | 5.2 | 5.3 | 1 |
| `test_machine.py` | 4.2 | 4.2 | 3.0 | 1 |
| `test_preroll.py` | 3.9 | 3.9 | 3.4 | 1 |
| `test_clipper.py` | 3.4 | 3.6 | 2.2 | 1 |
| `test_motion.py` | 1.9 | 2.4 | 2.3 | 1 |
| `test_bank2.py` | 2.0 | 2.0 | 2.5 | 1 |
| `test_lfo.py` | 1.2 | 1.2 | 0.7 | 1 |
| `test_clip.py` | 1.1 | 1.1 | 1.1 | 1 |
| `test_filter.py` | 1.1 | 1.1 | 0.6 | 1 |
| `test_cpu.py` | 0.8 | 0.8 | 0.5 | 1 |
| `test_duck.py` | 0.7 | 0.6 | 0.3 | 1 |
| `test_od.py` | 0.5 | 0.5 | 0.3 | 1 |
| `test_usbdev.py` | 0.4 | 0.4 | 0.3 | 1 |
| `test_cond.py` | 0.3 | 0.3 | 0.3 | 1 |
| `test_fault.py` | 0.3 | 0.3 | — (never ends) | 1 |
| `test_chord.py` | 0.2 | 0.2 | 0.3 | 1 |
| `test_trim.py` | 0.2 | 0.2 | 0.2 | 1 |
| `test_solo.py` | 0.2 | 0.2 | 0.2 | 1 |
| `test_slice.py` | 0.2 | 0.2 | 0.3 | 1 |
| `test_seqfix.py` | 0.2 | 0.2 | 0.3 | 1 |
| all 32, one after another | 4341 | 3571 | 1435 | |

**The instruction count is most of the time, but not free to drop**: `Emu.call` passes `count=` to Unicorn's
`emu_start`, and a count makes Unicorn 2.1.4 put its own hook on every instruction it translates. Left out
(`emu_start(addr | 1, RET)`, a trial in a copy of the tree, not in git), 30 of the 32 suites print the same PASS lines
in far fewer CPU seconds (test_munchi 397 -> 62 s, test_relapse 276 -> 46, test_confetti 188 -> 22, test_fx2 91 -> 10;
test_switch did not gain, 76 -> 100 under more load), but test_fault never ends (its `run()` relies on the count to
stop the fault recorder's deliberate spin) and test_clipwin, only ~1.8x faster (its time is the Python side), fails
one case it passes with the count (F-p: "the pad's own Sync is sent once after the open ... (blocks [])"). So it is no
drop-in change; `emu.py` is upstream's file, and whether to chase it is Thomas's call.

**Checking a branch** (`bench/bbci.sh`): `bench/bbci.sh <ref> [--remote <name>] [--keep]` resolves the ref (fetched
first from the remote into `refs/bbci/<id>`, no FETCH_HEAD), checks it out detached in a throwaway worktree under
`BBCI_WORK` (default `/data/dev/bbci`), sources the box's environment (`BBCI_ENV`, default `/srv/dev/bin/bb-env`),
runs `bench/doctor.sh -C` on it, then its own `./check.sh` under a lock (`BBCI_LOCK`), and writes
`runs/<time>-<id>/verdict.json` (ref, sha, subject, green | red | error, suites, failed and which, PASS and FAIL counts,
bank 1 used / size / free, bank 2's size, the image's and BBEXTRA.BIN's sha256, seconds: all, the check's own, the
wait for the lock) beside `check.log`, the
doctor's log, every suite's log and the job times; `verdicts/<sha>.json` keeps the newest per commit
(`bench/bbci.sh --last <ref>` prints it). Exit 0 green, 1 red, 2 error. The spool: `--enqueue <ref> [--remote x]` puts a
request in `spool/`, `--drain` runs them one after another (a second drain leaves at once). The units that drain it
when a request lands are templates in `bench/systemd/`, enabled with the one line in `bbci-spool.service`'s header;
none is enabled. First run (wip/blackbox-t-055 at ca2b1a1, 2026-11-12, behind the shared full-check lock): green,
32 suites, 1 874 PASS, 0 FAIL, bank 1 51 874 of 57 736 B (5 862 free), bank 2 24 672 B, its check 737 s for the suites.

## Branches, worktrees, releases

The model is D-019 (Thomas, 2026-10-16): `main` is a pure mirror of upstream, each feature's PR-shaped branch is that
feature's source of truth, and `maigre` is upstream plus every feature as if accepted plus a thin fork-only layer,
moved only by merges.

| branch | from | what | goes upstream? |
|---|---|---|---|
| `main` | upstream `main` | a pure mirror, fast-forward only, never committed to | — |
| `feat/<name>`, `fix/<name>` | upstream `main` | ONE feature as a PR, and that feature's source of truth: `src/<f>.c` + `patches/<f>.py` + `test_<f>.py` + its README bullet; no `notes/`, no fork names; comments cite `notes/re/...` as "in github.com/Maigre/blackbox-mod" | yes, opened by Thomas |
| `maigre` | `main` | upstream `main` + every feature branch merged, as if its PR were accepted + the fork-only layer (`notes/`, `bench/`, `FORK.md`, the 37.x names in `src/release.h`); moved **only by merges** (a feature branch, upstream `main`, a landed task branch), never a commit of feature code made on it | no (features go as their own PRs) |
| `37loop/blackbox-t-NNN` | `maigre` (or the unlanded branch it stacks on) | one hub task's work, one commit per feature or fix; lands on `maigre` when Thomas taps it | no |

A PR branch is cut from upstream `main`, the feature's commits cherry-picked without committing
(`git cherry-pick -n <sha>…`), fork-only wording taken out of the comments (D-0xx ids, names), then `./check.sh` on
upstream's base before ONE commit. From then on a fix to that feature is made on its branch first, and reaches
`maigre` by merging the branch. When Justin accepts a PR: fast-forward `main` to his, merge it into `maigre`, and
resolve every conflict toward his version (what he took, as he took it, replaces ours). How a task branch that carries
several features and notes (`37loop/blackbox-t-021`) is split into its feature branches at landing is not settled
yet (D-019). On this box before `feat/linux-dev` is upstream, a branch from his `main` needs a
`clang` on the PATH (`mkdir /dev/shm/x && ln -s /usr/bin/gcc /dev/shm/x/clang && PATH=/dev/shm/x:$PATH`) and shows
`test_machine.py`'s four S950 Lo misses (no FMA) — both are what `feat/linux-dev` fixes.

Worktrees on mgr-ran live under `/data/dev/bb-*` (one per branch in flight), the clone in `~/Bakery/blackbox-mod`.
Each needs its own `firmware/BLACKBOX-3.1.9.bin` link and `.venv` link (above).

A release: bump `src/release.h` (`RELEASE_NAME` 37.x.y, `DEV_NAME` 37.x.yd) in its own commit, then
`RELEASE=1 ./build.sh && python3 patch.py <the full set>` → `out/<set>/BLACKBOX.bin` (+ `out/BBEXTRA.BIN` when bank 2
holds code: both files from the SAME build run, or the pair is refused), copied out of `out/` with its sha256 and
release notes; then a dev rebuild before the suites again. Never commit an image (README "What is and isn't").
`python3 make_patch.py out/<set>/BLACKBOX.bin 37.x.y --extra out/BBEXTRA.BIN --out <outside the clone>` makes the
release's patch for `apply.py` from the same run (it refuses a pair that was not linked together); without `--out` it
writes into `docs/`, which is upstream's patcher folder. When bank 2's code changed, build with `BANK2_NEW=1`
(`build.sh`). On mgr-ran the images go to `/data/dev/release/<version>/` with a `SHA256SUMS`, dev builds to
`/data/dev/release/<version>d/`.
