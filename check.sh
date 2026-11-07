#!/bin/sh
# Build the cave, patch the image with every set, run every test suite; prints only failures and the image's sha.
cd "$(dirname "$0")"
./build.sh || exit 1
python3 patch.py solo slice duck chord cond filter cpu od comp seqfix fx2 munchi master fault cave | tail -1
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3               # needs unicorn, capstone and numpy
[ -f host/libdsp.dylib ] || sh host/build.sh     # the host build of the DSP (clang, or CC / cc: host/build.sh), which several suites hold the firmware's against

# Six suites run at a time: one by one the 31 suites take ~28 min (test_clipwin.py alone >11.6 min),
# over an unattended turn's budget. Pool of 6, longest-known suites queued first, so the pool fills
# with them immediately and the wall time tracks the longest suite instead of the serial sum.
# xargs -P, not `jobs`: /bin/sh is dash on Debian, where `jobs -p` in a script counts nothing.
heavy="test_clipwin.py test_munchi.py test_relapse.py test_confetti.py test_fx2.py test_switch.py test_smash.py"
order() {
  for t in $heavy; do [ -f "$t" ] && echo "$t"; done
  for t in test_*.py; do
    case " $heavy " in *" $t "*) ;; *) echo "$t" ;; esac
  done
}
rm -f out/*.rc                           # a worker killed mid-run must not leave the last run's 0 behind
order | xargs -n 1 -P 6 sh -c '"$0" "$1" > "out/$1.log" 2>&1; echo $? > "out/$1.rc"' "$PY"

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
