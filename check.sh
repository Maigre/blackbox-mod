#!/bin/sh
# Build the cave, patch the image with every set, run every test suite; prints only failures and the image's sha.
cd "$(dirname "$0")"
./build.sh || exit 1
python3 patch.py solo slice duck chord cond filter cpu od comp seqfix fx2 munchi master fault cave | tail -1
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3               # needs unicorn, capstone and numpy
[ -f host/libdsp.dylib ] || sh host/build.sh     # the host build of the DSP (clang, or CC / cc: host/build.sh), which several suites hold the firmware's against

# One by one the suites take ~28 min, over an unattended turn's budget: they run in a pool as wide as the box
# (CHECK_JOBS to change it). The fork's runner (bench/suites.py) queues the longest first and runs a suite over ~2 min
# as shards of its own file (bench/shard.py), leaving one log and one exit status per suite all the same.
# xargs -P, not `jobs`: /bin/sh is dash on Debian, where `jobs -p` in a script counts nothing.
J=${CHECK_JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 6)}
rm -f out/*.rc                           # a worker killed mid-run must not leave the last run's 0 behind
if [ -f bench/suites.py ]; then
  "$PY" bench/suites.py "$J"
else
  ls test_*.py | xargs -n 1 -P "$J" sh -c '"$0" "$1" > "out/$1.log" 2>&1; echo $? > "out/$1.rc"' "$PY"
fi

bad=0
total=0
for t in test_*.py; do
  total=$((total + 1))
  rc=$(cat "out/$t.rc" 2>/dev/null) || rc=1
  if [ "$rc" != 0 ]; then
    bad=$((bad + 1))
    echo "FAILED $t"
    grep -v '^PASS' "out/$t.log" | head -20
  fi
done
echo "$total suites, $bad failed"
[ "$bad" -eq 0 ]                         # the exit status says it too, for scripts and hooks
