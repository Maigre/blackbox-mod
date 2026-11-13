#!/bin/sh
# doctor.sh - fork-only (bench/, never in a PR): can this box run ./check.sh? Checks what the check needs, prints each
# miss with the line that fixes it, and exits 0 only when nothing required is missing.
#
#   bench/doctor.sh [-C dir] [--ghidra] [-q]
#     -C dir    check the tree at dir (a worktree of the fork) instead of the one this script is in
#     --ghidra  Ghidra (the RE helpers in ghidra/) counts as required too; without it, it is only reported
#     -q        print the misses only
#
# Required: the Arm GNU toolchain (arm-none-eabi-gcc/-g++/-nm/-objcopy/-size), shasum (build.sh), the Python that
# check.sh runs the suites with (.venv/bin/python, else python3; 3.9 or later) with unicorn, capstone, numpy, scipy and
# pyusb (`usb`: test_benchkit), the stock 3.1.9 image at firmware/BLACKBOX-3.1.9.bin with its sha256, and a C compiler
# for the suites that hold the firmware's DSP against a host build of the same C: test_filter and test_machine
# (host/libdsp, host/build.sh, which splits CC into words), test_clipper, test_insert, test_motion, test_transient and
# test_stretch (host/render_*.py and test_stretch.py build their library at every run and hand CC to Python's
# subprocess as ONE program name; both ways are tried); and a `clang` on the PATH if a suite calls it by name (none
# does; a merge of JOEBOX's, written on a Mac, may bring one back). The fixes are notes/dev-setup.md's recipe;
# /srv/dev is where this fork's boxes keep it.
# POSIX sh (dash on Debian).
TREE=$(dirname "$0")/..
GHIDRA=0
QUIET=0
while [ $# -gt 0 ]; do
  case $1 in
    -C) TREE=${2:?-C needs a directory}; shift ;;
    --ghidra) GHIDRA=1 ;;
    -q) QUIET=1 ;;
    *) sed -n '2,18p' "$0"; exit 2 ;;
  esac
  shift
done
cd "$TREE" || exit 2
STOCK_SHA=281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d
TC=/srv/dev/toolchains/arm-gnu-14.2/bin
VENV=/srv/dev/venvs/bb
miss=0

ok() { [ "$QUIET" = 1 ] || echo "ok    $1"; }
bad() {                                   # $1 what, $2 the fix (lines separated by \n), $3 optional: "opt"
  if [ "${3:-}" = opt ]; then echo "--    $1"; else echo "MISS  $1"; miss=$((miss + 1)); fi
  printf '%s\n' "$2" | sed 's/^/      fix: /'
}

# 1. the Arm toolchain
if command -v arm-none-eabi-gcc > /dev/null 2>&1; then
  v=$(arm-none-eabi-gcc -dumpversion 2>/dev/null)
  t=""
  for x in arm-none-eabi-g++ arm-none-eabi-nm arm-none-eabi-objcopy arm-none-eabi-size; do
    command -v "$x" > /dev/null 2>&1 || t="$t $x"
  done
  if [ -n "$t" ]; then
    bad "Arm toolchain incomplete (missing:$t)" "reinstall Arm GNU 14.2 (notes/dev-setup.md step 1)"
  elif [ "$v" = 14.2.1 ]; then
    ok "Arm GNU toolchain $v ($(command -v arm-none-eabi-gcc))"
  else
    ok "Arm GNU toolchain $v ($(command -v arm-none-eabi-gcc); the fork builds with 14.2.1, D-010: another version builds other bytes)"
  fi
elif [ -x "$TC/arm-none-eabi-gcc" ]; then
  bad "arm-none-eabi-gcc not on the PATH (it is in $TC)" "export PATH=$TC:\$PATH    # or: . /srv/dev/bin/bb-env"
else
  bad "Arm GNU toolchain (arm-none-eabi-gcc)" "mkdir -p /srv/dev/dl /srv/dev/toolchains && cd /srv/dev/dl && curl -sLO https://developer.arm.com/-/media/Files/downloads/gnu/14.2.rel1/binrel/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi.tar.xz
cd /srv/dev/toolchains && tar -xJf /srv/dev/dl/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi.tar.xz && mv arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi arm-gnu-14.2
export PATH=$TC:\$PATH"
fi

# 2. shasum (build.sh hashes bank 2's sources with it)
if command -v shasum > /dev/null 2>&1; then ok "shasum"; else
  bad "shasum (build.sh)" "sudo apt install perl    # Debian's shasum is perl's"
fi

# 3. the suites' Python
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3
if ! command -v "$PY" > /dev/null 2>&1 && [ ! -x "$PY" ]; then
  bad "python3" "uv venv --python 3.12 $VENV && ln -sfn $VENV .venv"
else
  pv=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)
  if "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    ok "Python $pv ($PY)"
  else
    bad "Python 3.9 or later for the suites ($PY is ${pv:-unusable})" "uv venv --python 3.12 $VENV && ln -sfn $VENV .venv"
  fi
  mods="" pkgs=""
  for m in unicorn capstone numpy scipy usb; do                     # usb is pyusb's: test_benchkit (bench/bbusb.py)
    "$PY" -c "import $m" 2>/dev/null || { mods="$mods $m"; pkgs="$pkgs $( [ $m = usb ] && echo pyusb || echo $m)"; }
  done
  if [ -z "$mods" ]; then
    ok "Python modules unicorn, capstone, numpy, scipy, usb (pyusb)"
  elif [ "$PY" = python3 ] && [ -x "$VENV/bin/python" ] && [ ! -e .venv ]; then
    bad "Python modules:$mods (check.sh uses .venv/bin/python first, and there is no .venv here)" \
      "ln -sfn $VENV .venv && grep -qx .venv \"\$(git rev-parse --git-common-dir)/info/exclude\" || echo .venv >> \"\$(git rev-parse --git-common-dir)/info/exclude\""
  else
    bad "Python modules:$mods (in $PY)" "VIRTUAL_ENV=$(dirname "$(dirname "$(command -v "$PY" 2>/dev/null || echo "$VENV/bin/python")")") uv pip install$pkgs"
  fi
fi

# 4. the stock image
if [ -f firmware/BLACKBOX-3.1.9.bin ]; then
  s=$( (sha256sum firmware/BLACKBOX-3.1.9.bin 2>/dev/null || shasum -a 256 firmware/BLACKBOX-3.1.9.bin) | cut -d' ' -f1)
  if [ "$s" = "$STOCK_SHA" ]; then ok "stock 3.1.9 image, sha256 ${s%"${s#????????????}"}..."; else
    bad "firmware/BLACKBOX-3.1.9.bin is not stock 3.1.9 (sha256 $s)" "replace it with 1010music's 3.1.9 BLACKBOX.bin (sha256 $STOCK_SHA)"
  fi
elif [ -f /srv/dev/firmware/BLACKBOX-3.1.9.bin ]; then
  bad "firmware/BLACKBOX-3.1.9.bin (gitignored)" "ln -sf /srv/dev/firmware/BLACKBOX-3.1.9.bin firmware/BLACKBOX-3.1.9.bin"
else
  bad "the stock 3.1.9 image" "download 1010music's Blackbox 3.1.9 firmware to /srv/dev/firmware/BLACKBOX-3.1.9.bin (sha256 $STOCK_SHA), never into git
ln -sf /srv/dev/firmware/BLACKBOX-3.1.9.bin firmware/BLACKBOX-3.1.9.bin"
fi

# 5. a C compiler for the host builds: CC, else clang, else cc, tried on a tiny shared library the way host/build.sh
#    runs it (CC split into words) and the way host/render_*.py do (CC as one program name, from Python)
cc_=${CC:-$(command -v clang || command -v cc)}
tmp=$(mktemp -d)
printf 'int f(int x) { return x + 1; }\n' > "$tmp/t.c"
needs="test_filter, test_machine, test_clipper, test_insert, test_motion, test_transient and test_stretch need it"
# shellcheck disable=SC2086
if [ -z "$cc_" ] || ! $cc_ -O2 -shared -fPIC -o "$tmp/t.so" "$tmp/t.c" > /dev/null 2>&1; then
  bad "a C compiler for the host builds (${cc_:-none found}; $needs)" "sudo apt install gcc
or, without root, zig's behind a one-line wrapper (CC must name one program: host/render_*.py run it as one):
VIRTUAL_ENV=$VENV uv pip install ziglang && printf '#!/bin/sh\\nexec $VENV/bin/python -m ziglang cc \"\$@\"\\n' > $VENV/bin/zig-cc && chmod +x $VENV/bin/zig-cc
export CC=$VENV/bin/zig-cc"
elif ! "$PY" -c 'import os, shutil, subprocess, sys
subprocess.run([os.environ.get("CC") or shutil.which("clang") or shutil.which("cc") or "cc", "-O2", "-shared", "-fPIC",
                "-o", os.path.join(sys.argv[1], "u.so"), os.path.join(sys.argv[1], "t.c")], check=True, capture_output=True)' \
    "$tmp" > /dev/null 2>&1; then
  bad "CC=\"$cc_\" builds for host/build.sh, but host/render_*.py and test_stretch.py run CC as one program name and cannot (test_clipper, test_insert, test_motion, test_transient, test_stretch)" \
    "a one-line wrapper: printf '#!/bin/sh\\nexec $cc_ \"\$@\"\\n' > $VENV/bin/cc-wrap && chmod +x $VENV/bin/cc-wrap && export CC=$VENV/bin/cc-wrap"
else
  ok "C compiler for the host builds ($cc_)"
fi
rm -rf "$tmp"

# 5b. a suite that runs clang by name, whatever CC says (none does; JOEBOX's suites are written on a Mac, and a merge
#     of his may bring one back): it needs a clang on the PATH
byname=$(grep -l '\["clang"' ./*.py host/*.py 2>/dev/null | sed 's|^\./||' | tr '\n' ' ')
if [ -z "$byname" ]; then
  ok "no suite calls clang by name"
elif command -v clang > /dev/null 2>&1; then
  ok "clang on the PATH for ${byname% } (by name)"
else
  bad "clang by name (${byname% } call it, not CC)" "ln -sf \"\$(command -v gcc || command -v cc)\" $VENV/bin/clang    # with $VENV/bin on the PATH"
fi

# 6. the tools check.sh, bench/bbci.sh and the shards use
for x in git flock; do
  if command -v "$x" > /dev/null 2>&1; then ok "$x"; else bad "$x" "sudo apt install $( [ $x = flock ] && echo util-linux || echo $x)"; fi
done
n=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo "?")
[ "$QUIET" = 1 ] || echo "info  $n cores: check.sh runs $n suites (or shards) at a time (CHECK_JOBS to change it)"

# 7. Ghidra (optional unless --ghidra)
o=opt
[ "$GHIDRA" = 1 ] && o=req
if [ -n "${GHIDRA_INSTALL_DIR:-}" ] && [ -x "${GHIDRA_INSTALL_DIR}/support/analyzeHeadless" ]; then
  if [ -n "${JAVA_HOME:-}" ] && [ -x "$JAVA_HOME/bin/javac" ]; then
    if [ -n "${GHIDRA_PROJ:-}" ] && [ -d "$GHIDRA_PROJ" ]; then
      [ "$o" = req ] && ok "Ghidra ($GHIDRA_INSTALL_DIR, project $GHIDRA_PROJ)" || ok "Ghidra (optional): $GHIDRA_INSTALL_DIR, project $GHIDRA_PROJ"
    else
      bad "Ghidra project (GHIDRA_PROJ=${GHIDRA_PROJ:-unset})" "export GHIDRA_PROJ=/srv/dev/firmware/ghidra && mkdir -p \"\$GHIDRA_PROJ\" && $PY ghidra/import.py" "$( [ $o = opt ] && echo opt)"
    fi
  else
    bad "a JDK 21 with javac (JAVA_HOME=${JAVA_HOME:-unset})" "a Temurin 21 tarball under /srv/dev/toolchains, then export JAVA_HOME=<it>   (notes/dev-setup.md)" "$( [ $o = opt ] && echo opt)"
  fi
else
  bad "Ghidra (GHIDRA_INSTALL_DIR=${GHIDRA_INSTALL_DIR:-unset})" "notes/dev-setup.md step 1 (Ghidra 12 + a JDK 21), then: . /srv/dev/bin/bb-env    # or export GHIDRA_INSTALL_DIR JAVA_HOME GHIDRA_PROJ" "$( [ $o = opt ] && echo opt)"
fi

if [ "$miss" -eq 0 ]; then
  echo "ready: ./check.sh can run here"
  exit 0
fi
echo "not ready: $miss missing"
exit 1
