#!/bin/bash
# prcheck.sh - fork-only (never in a PR, never committed): build and check PR-shaped branches of blackbox-mod, each in
# a throwaway worktree against the stock 3.1.9 image, and report per branch: the suites passed / failed, .cave used /
# free (dev and RELEASE=1), and the dev and release images' sha256 (BLACKBOX.bin and BBEXTRA.BIN).
#
#   prcheck.sh [-C repo] [-j jobs] [-b base] [-k] [-o dir] branch...
#     -C  the clone (default /home/mgr/Bakery/blackbox-mod); a branch is any rev it knows (fix/x, upstream/main, a sha)
#     -j  how many at once (default 3; one ./check.sh is ~16 min of one core on mgr-ran)
#     -b  also check this base (e.g. upstream/main): each branch's failing suites that the base passes are marked NEW,
#         and its images and .cave are compared with the base's
#     -k  keep the worktrees (default: removed when done; the logs are kept either way). A run that is killed
#         leaves its worktrees in $WORK/tmp/: git worktree remove --force <it>
#     -o  where the run's logs and summaries go (default $WORK/runs/<date-time>; WORK = $PRCHECK_WORK or out/prcheck)
#   prcheck.sh -r dir     the report of an earlier run, again
#
# Each branch: git worktree add --detach (a branch checked out elsewhere is fine, no ref is moved), the firmware and
# .venv links as in notes/dev-setup.md, then the branch's own ./check.sh (the dev build, the patch.py line of its
# check.sh, every suite), then RELEASE=1 ./build.sh and the same patch.py line for the release image. The chain is
# read from the branch's check.sh, so a branch that adds a set builds with it.
# Never talks to the unit, a remote or a branch ref. On this box (no clang, no FMA) a branch from upstream main without
# feat/linux-dev gets a clang -> gcc shim on the PATH and shows test_machine.py's four S950 Lo ARM-vs-host misses.
set -u
REPO=/home/mgr/Bakery/blackbox-mod
JOBS=3
BASE=
KEEP=0
OUT=
REPORT=
STOCK=/srv/dev/firmware/BLACKBOX-3.1.9.bin
STOCK_SHA=281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d
VENV=/srv/dev/venvs/bb
TOOLS=/srv/dev/toolchains/arm-gnu-14.2/bin
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=${PRCHECK_WORK:-$HERE/../out/prcheck}   # runs/, tmp/ (worktrees), shim/: under out/, which git ignores

key() { echo "$1" | tr '/' '-'; }

one() {                                   # one rev: $1 rev, $2 its result dir
    local rev=$1 dir=$2 sha wt chain img rc t0 t n=0 p=0 f=0 cap used
    mkdir -p "$dir"
    sha=$(git -C "$REPO" rev-parse --verify -q "$rev^{commit}") || { echo "status=no such rev" > "$dir/summary"; return; }
    wt="$WORK/tmp/$(key "$rev")-${sha:0:7}-$$"
    rm -rf "$wt"
    git -C "$REPO" worktree add -q --detach "$wt" "$sha" > "$dir/worktree.log" 2>&1 ||
        { echo "status=worktree add failed" > "$dir/summary"; return; }
    ln -sf "$STOCK" "$wt/firmware/BLACKBOX-3.1.9.bin"
    ln -sfn "$VENV" "$wt/.venv"
    chain=$(sed -n 's/^python3 patch.py \([^|]*\).*/\1/p' "$wt/check.sh" | head -1)
    chain=$(echo $chain)
    img="out/$(echo "$chain" | tr ' ' '+')/BLACKBOX.bin"
    cap=$(( $(sed -n 's/.*CAVE.*LENGTH = \(0x[0-9A-Fa-f]*\).*/\1/p' "$wt/src/cave.ld.in" | head -1) ))
    t0=$(date +%s)
    (cd "$wt" && ./check.sh) > "$dir/check.log" 2>&1
    rc=$?
    {
        echo "rev=$rev"
        echo "sha=$sha"
        echo "subject=$(git -C "$REPO" log -1 --format=%s "$sha")"
        echo "chain=$chain"
        echo "check_exit=$rc"
        echo "check_secs=$(( $(date +%s) - t0 ))"
        echo "verdict=$(grep -E '^[0-9]+ suites, [0-9]+ failed$' "$dir/check.log" | tail -1)"
        echo "failed=$(grep -E '^FAILED test_' "$dir/check.log" | sed 's/^FAILED //' | tr '\n' ' ' | sed 's/ $//')"
        for t in "$wt"/out/test_*.py.log; do
            [ -f "$t" ] || continue
            n=$((n + 1))
            p=$((p + $(grep -c '^PASS' "$t")))
            f=$((f + $(grep -c '^FAIL' "$t")))
            echo "suite.$(basename "$t" .py.log)=$(grep -c '^PASS' "$t") $(grep -c '^FAIL' "$t")"
        done
        echo "checks=$p $f $n"
        used=$(arm-none-eabi-size -A "$wt/out/cave.elf" 2>/dev/null | awk '$1 == ".cave" {print $2}')
        echo "dev_cave=${used:-0} $cap"
        echo "dev_image=$( [ -f "$wt/$img" ] && sha256sum "$wt/$img" | cut -d' ' -f1 || echo none)"
        echo "dev_extra=$( [ -f "$wt/out/BBEXTRA.BIN" ] && sha256sum "$wt/out/BBEXTRA.BIN" | cut -d' ' -f1 || echo none)"
        mkdir -p "$dir/logs" && cp "$wt"/out/test_*.py.log "$dir/logs/" 2>/dev/null
        if (cd "$wt" && RELEASE=1 ./build.sh && python3 patch.py $chain) > "$dir/release.log" 2>&1; then
            used=$(arm-none-eabi-size -A "$wt/out/cave.elf" | awk '$1 == ".cave" {print $2}')
            echo "rel_cave=$used $cap"
            echo "rel_image=$(sha256sum "$wt/$img" | cut -d' ' -f1)"
            echo "rel_extra=$(sha256sum "$wt/out/BBEXTRA.BIN" | cut -d' ' -f1)"
        else
            echo "rel_cave=0 $cap"
            echo "rel_image=release build failed"
            echo "rel_extra=none"
        fi
        echo "status=done"
    } > "$dir/summary"
    if [ "$KEEP" = 1 ]; then
        echo "worktree=$wt" >> "$dir/summary"
    else
        git -C "$REPO" worktree remove --force "$wt" >> "$dir/worktree.log" 2>&1 || rm -rf "$wt"
    fi
}

get() { sed -n "s/^$2=//p" "$1/summary" 2>/dev/null | head -1; }

report() {                                # $1 the run's dir, $2 the base's key (or empty), then the revs' keys
    local run=$1 base=$2 k d st u c bf nf
    shift 2
    printf '%-24s %-9s %-26s %-19s %-19s %-17s %s\n' "branch" "sha" "suites (checks ok/bad)" ".cave dev used/free" \
        ".cave rel used/free" "dev BLACKBOX.bin" "release BLACKBOX.bin / BBEXTRA.BIN"
    for k in "$@"; do
        d=$run/$k
        st=$(get "$d" status)
        if [ "$st" != done ]; then printf '%-24s %s\n' "$(get "$d" rev || echo "$k")" "${st:-not run}"; continue; fi
        read -r u c <<< "$(get "$d" dev_cave)"
        local devc="$u/$((c - u))"
        read -r u c <<< "$(get "$d" rel_cave)"
        local relc="$u/$((c - u))"
        read -r cp cf cn <<< "$(get "$d" checks)"
        printf '%-24s %-9s %-26s %-19s %-19s %-17s %s / %s\n' "$(get "$d" rev)" "$(get "$d" sha | cut -c1-7)" \
            "$(get "$d" verdict | awk '{printf "%d/%d pass", $1 - $3, $1}') ($cp/$cf)" "$devc" "$relc" \
            "$(get "$d" dev_image | cut -c1-16)" "$(get "$d" rel_image | cut -c1-16)" "$(get "$d" rel_extra | cut -c1-16)"
        bf=$(get "$d" failed)
        [ -n "$bf" ] && echo "    failed: $bf"
        if [ -n "$base" ] && [ "$k" != "$base" ]; then
            nf=""
            for t in $bf; do case " $(get "$run/$base" failed) " in *" $t "*) ;; *) nf="$nf $t" ;; esac; done
            [ -n "$bf" ] && echo "    NEW against $(get "$run/$base" rev):${nf:- none (the base fails the same)}"
            read -r u c <<< "$(get "$d" dev_cave)"; local du=$u
            read -r u c <<< "$(get "$run/$base" dev_cave)"; du=$((du - u))
            read -r u c <<< "$(get "$d" rel_cave)"; local ru=$u
            read -r u c <<< "$(get "$run/$base" rel_cave)"; ru=$((ru - u))
            echo "    against $(get "$run/$base" rev): .cave dev $( [ $du -ge 0 ] && echo +)$du B, release $( [ $ru -ge 0 ] && echo +)$ru B;" \
                "dev image $( [ "$(get "$d" dev_image)" = "$(get "$run/$base" dev_image)" ] && echo SAME || echo differs)," \
                "release image $( [ "$(get "$d" rel_image)" = "$(get "$run/$base" rel_image)" ] && echo SAME || echo differs)," \
                "BBEXTRA.BIN $( [ "$(get "$d" rel_extra)" = "$(get "$run/$base" rel_extra)" ] && echo SAME || echo differs)"
        fi
    done
}

if [ "${1:-}" = --one ]; then             # internal: xargs runs one rev per call: --one keep repo rev dir
    KEEP=$2
    REPO=$3
    export PATH="$TOOLS:$PATH"
    command -v clang > /dev/null || export PATH="$WORK/shim:$PATH"
    one "$4" "$5"
    exit 0
fi

while getopts C:j:b:ko:r: o; do
    case $o in
    C) REPO=$OPTARG ;;
    j) JOBS=$OPTARG ;;
    b) BASE=$OPTARG ;;
    k) KEEP=1 ;;
    o) OUT=$OPTARG ;;
    r) REPORT=$OPTARG ;;
    *) sed -n '2,15p' "$0"; exit 2 ;;
    esac
done
shift $((OPTIND - 1))
if [ -n "$REPORT" ]; then
    keys=$(cat "$REPORT/revs")
    report "$REPORT" "$(cat "$REPORT/base")" $keys
    exit 0
fi
[ $# -gt 0 ] || { sed -n '2,15p' "$0"; exit 2; }
[ "$(sha256sum "$STOCK" 2>/dev/null | cut -d' ' -f1)" = "$STOCK_SHA" ] || { echo "stock 3.1.9 image missing or wrong: $STOCK"; exit 1; }
OUT=${OUT:-$WORK/runs/$(date +%Y%m%d-%H%M%S)}
mkdir -p "$OUT" "$WORK/tmp"
if ! PATH="$TOOLS:$PATH" command -v clang > /dev/null; then   # host/build.sh before feat/linux-dev calls clang by name
    mkdir -p "$WORK/shim" && ln -sf "$(command -v gcc || command -v cc)" "$WORK/shim/clang"
fi

revs=("$@")
[ -n "$BASE" ] && revs=("$BASE" "${revs[@]}")
keys=""
for r in "${revs[@]}"; do keys="$keys $(key "$r")"; done
echo "$keys" > "$OUT/revs"
echo "${BASE:+$(key "$BASE")}" > "$OUT/base"
echo "prcheck: ${#revs[@]} revs, $JOBS at a time, logs in $OUT"
for r in "${revs[@]}"; do printf '%s\0%s\0' "$r" "$OUT/$(key "$r")"; done |
    xargs -0 -n 2 -P "$JOBS" "$0" --one "$KEEP" "$REPO"
report "$OUT" "${BASE:+$(key "$BASE")}" $keys | tee "$OUT/report.txt"
