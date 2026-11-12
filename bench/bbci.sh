#!/bin/sh
# bbci.sh - fork-only (bench/, never in a PR): check one ref of blackbox-mod in a throwaway worktree with this box's
# environment, and leave a verdict a later turn can read. Never pushes, never moves a branch.
#
#   bench/bbci.sh <ref> [--remote <name>] [--keep]    check it now (one check at a time on the box: a lock)
#   bench/bbci.sh --enqueue <ref> [--remote <name>]   put a request in the spool and return
#   bench/bbci.sh --drain                             run the spool's requests one after another, oldest first, until
#                                                     it is empty (a second --drain meanwhile leaves at once)
#   bench/bbci.sh --last <ref|sha>                    print the newest verdict of that sha (a ref the clone resolves)
#
# <ref>: a branch, tag or sha the clone knows; with --remote, fetched from that remote first into refs/bbci/<id>
# (deleted once the worktree stands; FETCH_HEAD is not written, so a concurrent fetch cannot swap it).
# BBCI_REPO   the clone (default: the one this script is in)
# BBCI_WORK   where it all goes (default /data/dev/bbci):
#   runs/<yyyymmdd-hhmmss>-<XXXX>/   verdict.json, check.log, doctor.log, times.tsv, logs/ (every suite's log)
#   verdicts/<sha>.json              the newest verdict of that sha
#   spool/<time>-<pid>.req           the queue; done/ the requests run, each with its verdict's path appended
#   wt/<id>                          the throwaway worktree (removed after; --keep leaves it)
# BBCI_ENV    a file sourced before the check (default /srv/dev/bin/bb-env when it exists): the box's toolchain, venv
# BBCI_STOCK  the stock 3.1.9 image linked into the worktree (default /srv/dev/firmware/BLACKBOX-3.1.9.bin)
# BBCI_VENV   linked as the worktree's .venv (default /srv/dev/venvs/bb when it exists)
# BBCI_LOCK   the lock every check holds (default $BBCI_WORK/.check.lock); CHECK_JOBS passes on to check.sh
#
# bench/doctor.sh -C <worktree> must say ready first, or the verdict is "error". The check is the ref's own
# ./check.sh. Exit status: 0 green (N suites, 0 failed), 1 red (a suite or the build failed), 2 error (no such ref,
# the fetch, the worktree, the box not ready).
# verdict.json: ref, remote, sha, subject, verdict (green | red | error), error, suites, failed, failed_suites, checks
# {pass, fail}, bank1_used, bank1_size, bank1_free (the cave, bytes: .cave of out/cave.elf against CAVE's LENGTH in
# src/cave.ld.in), bank2_size (out/bank2.bin, bytes), image_sha256 (the check's patched BLACKBOX.bin), extra_sha256
# (BBEXTRA.BIN), seconds (all of it), check_seconds (./check.sh, the lock held), lock_wait_seconds, jobs (the pool),
# host, started, run (the run's folder).
# A run that is stopped (TERM, INT, HUP: a turn's time cap, Ctrl-C) stops its check, takes its worktree and its fetched
# ref away and leaves verdict "error", error "interrupted by SIG..."; one killed outright (-9, the box off) is found by
# the next bbci run on the box (its pid is gone and it left no verdict), which does the same for it. A request the
# drain took says how it ended either way.
# A unit that drains the spool when a request lands: bench/systemd/ (templates; enabling them is a line in there).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=${BBCI_REPO:-$(git -C "$HERE" rev-parse --show-toplevel)}
WORK=${BBCI_WORK:-/data/dev/bbci}
ENVF=${BBCI_ENV:-/srv/dev/bin/bb-env}
STOCK=${BBCI_STOCK:-/srv/dev/firmware/BLACKBOX-3.1.9.bin}
VENV=${BBCI_VENV:-/srv/dev/venvs/bb}
LOCK=${BBCI_LOCK:-$WORK/.check.lock}

usage() { sed -n '2,20p' "$0"; exit 2; }

json() {                                  # write the verdict: $1 the file; the fields come from the environment
  python3 - "$1" <<'PY'
import json, os, sys
e = os.environ
def num(k):
    v = e.get(k, "")
    return int(v) if v.lstrip("-").isdigit() else None
v = {
    "ref": e.get("V_REF"), "remote": e.get("V_REMOTE") or None, "sha": e.get("V_SHA") or None,
    "subject": e.get("V_SUBJECT") or None, "verdict": e.get("V_VERDICT"), "error": e.get("V_ERROR") or None,
    "suites": num("V_SUITES"), "failed": num("V_FAILED"),
    "failed_suites": e.get("V_FAILED_SUITES", "").split(),
    "checks": {"pass": num("V_PASS"), "fail": num("V_FAIL")},
    "bank1_used": num("V_B1USED"), "bank1_size": num("V_B1SIZE"), "bank1_free": num("V_B1FREE"),
    "bank2_size": num("V_B2SIZE"), "image_sha256": e.get("V_IMAGE") or None, "extra_sha256": e.get("V_EXTRA") or None,
    "seconds": num("V_SECONDS"), "check_seconds": num("V_CHECK_SECONDS"),
    "lock_wait_seconds": num("V_LOCK_SECONDS"), "jobs": num("V_JOBS"),
    "host": e.get("V_HOST"), "started": e.get("V_STARTED"), "run": e.get("V_RUN"),
}
with open(sys.argv[1], "w") as f:
    json.dump(v, f, indent=1)
    f.write("\n")
PY
}

killtree() {                              # $1 a pid: TERM to it, then to every process it had under it
  set -- "$1" $(ps -o pid= --ppid "$1" 2>/dev/null)
  kill -TERM "$1" 2>/dev/null
  shift
  for k in "$@"; do killtree "$k"; done
}

drop_worktree() {                         # $1 the run's folder, $2 the worktree, $3 its id, $4 keep (0/1)
  if [ "$4" = 1 ] && [ -d "$2" ]; then
    echo "worktree kept: $2" >> "$1/worktree.log"
  elif [ -d "$2" ]; then
    git -C "$REPO" worktree remove --force "$2" >> "$1/worktree.log" 2>&1 || { rm -rf "$2"; git -C "$REPO" worktree prune; }
  fi
  git -C "$REPO" update-ref -d "refs/bbci/$3" 2>/dev/null
  return 0
}

reap() {                                  # runs killed outright (no trap ran): their worktree and ref out, a verdict
  for p in "$WORK"/runs/*/pid; do
    [ -f "$p" ] || continue
    d=${p%/pid}
    [ -f "$d/verdict.json" ] && continue
    pid=$(cat "$p")                                          # still running (or its pid taken again): left alone;
    { [ -d "/proc/$pid" ] || kill -0 "$pid" 2>/dev/null; } && continue    # /proc too: kill -0 fails on another user's
    rid=$(basename "$d")
    drop_worktree "$d" "$WORK/wt/$rid" "$rid" 0
    (
      for v in $(env | sed -n 's/^\(V_[A-Z0-9_]*\)=.*/\1/p'); do unset "$v"; done
      export V_REF="$(sed -n 1p "$d/request" 2>/dev/null)" V_REMOTE="$(sed -n 2p "$d/request" 2>/dev/null)"
      export V_SHA="$(cat "$d/sha" 2>/dev/null)" V_VERDICT=error V_RUN="$d" V_HOST="$(hostname)"
      export V_ERROR="interrupted: its process ($(cat "$p")) ended without a verdict; found by a later bbci run, $(date -Iseconds)"
      json "$d/verdict.json"
    )
    [ -f "$d/spool-req" ] && echo "bbci: interrupted (killed), found later -> $d/verdict.json" >> "$(cat "$d/spool-req")"
    echo "bbci: reaped $d (killed without a verdict)"
  done
}

finish() {                                # write the verdict and say it; $1 the exit status
  export V_ERROR V_SHA V_SUBJECT V_VERDICT V_SUITES V_FAILED V_FAILED_SUITES V_PASS V_FAIL V_B1USED V_B1SIZE V_B1FREE
  export V_B2SIZE V_IMAGE V_EXTRA V_CHECK_SECONDS V_LOCK_SECONDS V_JOBS
  export V_SECONDS=$(( $(date +%s) - t0 ))
  json "$run/verdict.json"
  [ -n "$V_SHA" ] && cp "$run/verdict.json" "$WORK/verdicts/$V_SHA.json"
  line="bbci: $ref ${V_SHA:+${V_SHA%"${V_SHA#???????}"} }$V_VERDICT${V_SUITES:+: $V_SUITES suites, $V_FAILED failed}${V_ERROR:+ ($V_ERROR)}, ${V_SECONDS} s -> $run/verdict.json"
  echo "$line"
  [ -n "${BBCI_REQ:-}" ] && echo "$line" >> "$BBCI_REQ"
  return "$1"
}

interrupted() {                           # $1 the signal: stop the check, clean up, an "error" verdict, leave
  trap '' HUP INT TERM
  trap - EXIT
  if [ -n "${cpid:-}" ]; then killtree "$cpid"; sleep 1; fi
  drop_worktree "$run" "$wt" "$id" "$keep"
  V_VERDICT=error
  V_ERROR="interrupted by $1 after $(( $(date +%s) - t0 )) s${cpid:+, during the check}"
  finish 2
  exit 2
}

check_one() {                             # $1 ref, $2 remote (or empty), $3 keep (0/1)
  ref=$1 remote=$2 keep=$3
  t0=$(date +%s)
  export V_REF="$ref" V_REMOTE="$remote" V_HOST="$(hostname)" V_STARTED="$(date -Iseconds)"
  export V_SHA="" V_SUBJECT="" V_VERDICT=error V_ERROR="" V_SUITES="" V_FAILED="" V_FAILED_SUITES="" V_PASS="" V_FAIL=""
  export V_B1USED="" V_B1SIZE="" V_B1FREE="" V_B2SIZE="" V_IMAGE="" V_EXTRA="" V_CHECK_SECONDS="" V_LOCK_SECONDS="" V_JOBS="${CHECK_JOBS:-}"
  mkdir -p "$WORK/runs" "$WORK/verdicts" "$WORK/wt"
  reap
  run=$(mktemp -d "$WORK/runs/$(date +%Y%m%d-%H%M%S)-XXXX") || return 2
  id=$(basename "$run")
  export V_RUN="$run"
  wt="$WORK/wt/$id"
  cpid=""
  printf '%s\n' "$ref" "$remote" > "$run/request"
  [ -n "${BBCI_REQ:-}" ] && echo "$BBCI_REQ" > "$run/spool-req"
  echo $$ > "$run/pid"                    # for reap(): a run whose pid is gone and has no verdict was killed
  trap 'interrupted SIGHUP' HUP
  trap 'interrupted SIGINT' INT
  trap 'interrupted SIGTERM' TERM
  trap 'interrupted "an unexpected exit"' EXIT
  sha=""
  if [ -n "$remote" ]; then
    if git -C "$REPO" fetch -q --no-write-fetch-head "$remote" "$ref:refs/bbci/$id" > "$run/fetch.log" 2>&1; then
      sha=$(git -C "$REPO" rev-parse --verify -q "refs/bbci/$id^{commit}")
    else
      V_ERROR="fetch of $ref from $remote failed: $(head -n 1 "$run/fetch.log")"
    fi
  else
    sha=$(git -C "$REPO" rev-parse --verify -q "$ref^{commit}") || V_ERROR="no such ref in $REPO: $ref"
  fi
  rc=2
  if [ -n "$sha" ]; then
    V_SHA=$sha
    echo "$sha" > "$run/sha"
    V_SUBJECT=$(git -C "$REPO" log -1 --format=%s "$sha")
    if git -C "$REPO" worktree add -q --detach "$wt" "$sha" > "$run/worktree.log" 2>&1; then
      [ -n "$remote" ] && git -C "$REPO" update-ref -d "refs/bbci/$id"
      ln -sf "$STOCK" "$wt/firmware/BLACKBOX-3.1.9.bin"
      [ -d "$VENV" ] && ln -sfn "$VENV" "$wt/.venv"
      (                                   # in the background, so a signal reaches the trap while it runs
        [ -f "$ENVF" ] && . "$ENVF"
        if ! sh "$HERE/doctor.sh" -C "$wt" > "$run/doctor.log" 2>&1; then
          exit 3
        fi
        c0=$(date +%s)
        (cd "$wt" && flock "$LOCK" sh -c 'date +%s > "$1"; exec ./check.sh' sh "$run/check.start") > "$run/check.log" 2>&1
        c=$?
        c1=$(cat "$run/check.start" 2>/dev/null || echo "$c0")
        echo $(( $(date +%s) - c1 )) > "$run/check.seconds"    # the check's own time, the lock held
        echo $(( c1 - c0 )) > "$run/lock.seconds"              # how long it waited for the lock
        exit $c
      ) &
      cpid=$!
      wait "$cpid"
      c=$?
      cpid=""
      if [ $c = 3 ] && [ ! -f "$run/check.seconds" ]; then
        V_ERROR="the box is not ready: $(grep -c '^MISS' "$run/doctor.log") missing (doctor.log)"
      else
        V_CHECK_SECONDS=$(cat "$run/check.seconds")
        V_LOCK_SECONDS=$(cat "$run/lock.seconds" 2>/dev/null)
        line=$(grep -E '^[0-9]+ suites, [0-9]+ failed$' "$run/check.log" | tail -n 1)
        if [ -n "$line" ]; then
          V_SUITES=${line%% *}
          V_FAILED=$(echo "$line" | sed 's/.*, \([0-9]*\) failed$/\1/')
          V_FAILED_SUITES=$(sed -n 's/^FAILED \(test_.*\)/\1/p' "$run/check.log" | tr '\n' ' ')
          if [ "$c" = 0 ] && [ "$V_FAILED" = 0 ]; then V_VERDICT=green; rc=0; else V_VERDICT=red; rc=1; fi
        else
          V_VERDICT=red
          V_ERROR="no verdict line: the build or the patch failed (check.log)"
          rc=1
        fi
        mkdir -p "$run/logs"
        p=0 f=0
        for t in "$wt"/out/test_*.py.log; do
          [ -f "$t" ] || continue
          cp "$t" "$run/logs/"
          p=$((p + $(grep -c '^PASS' "$t")))
          f=$((f + $(grep -c '^FAIL' "$t")))
        done
        V_PASS=$p V_FAIL=$f
        if [ -f "$wt/out/check-times.tsv" ]; then
          cp "$wt/out/check-times.tsv" "$run/times.tsv"
          V_JOBS=$(sed -n '1s/.*(pool \([0-9]*\),.*/\1/p' "$wt/out/check-times.tsv")
        fi
        cap=$(sed -n 's/.*CAVE.*LENGTH = \(0x[0-9A-Fa-f]*\).*/\1/p' "$wt/src/cave.ld.in" | head -n 1)
        used=$( ( [ -f "$ENVF" ] && . "$ENVF"; arm-none-eabi-size -A "$wt/out/cave.elf" 2>/dev/null ) | awk '$1 == ".cave" {print $2}')
        if [ -n "$cap" ] && [ -n "$used" ]; then
          V_B1SIZE=$((cap)) V_B1USED=$used V_B1FREE=$((cap - used))
        fi
        [ -f "$wt/out/bank2.bin" ] && V_B2SIZE=$(wc -c < "$wt/out/bank2.bin" | tr -d ' ')
        chain=$(sed -n 's/^python3 patch.py \([^|]*\).*/\1/p' "$wt/check.sh" | head -n 1)
        img="$wt/out/$(echo $chain | tr ' ' '+')/BLACKBOX.bin"
        [ -f "$img" ] && V_IMAGE=$(sha256sum "$img" | cut -d' ' -f1)
        [ -f "$wt/out/BBEXTRA.BIN" ] && V_EXTRA=$(sha256sum "$wt/out/BBEXTRA.BIN" | cut -d' ' -f1)
      fi
    else
      V_ERROR="git worktree add failed (worktree.log)"
    fi
  fi
  drop_worktree "$run" "$wt" "$id" "$keep"
  trap - HUP INT TERM EXIT
  finish $rc
}

[ $# -ge 1 ] || usage
case $1 in
  --enqueue)
    shift
    [ $# -ge 1 ] || usage
    mkdir -p "$WORK/spool"
    req="$WORK/spool/$(date +%Y%m%d-%H%M%S)-$$.req"
    printf '%s\n' "$@" > "$req.tmp" && mv "$req.tmp" "$req"   # the drain never sees half a request
    echo "queued: $req"
    ;;
  --drain)
    mkdir -p "$WORK/spool" "$WORK/done"
    exec 9> "$WORK/.drain.lock"
    flock -n 9 || { echo "bbci: a drain is running already; it takes this request too"; exit 0; }
    while :; do
      req=$(ls "$WORK"/spool/*.req 2>/dev/null | head -n 1)
      [ -n "$req" ] || break
      mv "$req" "$WORK/done/" || break
      req="$WORK/done/$(basename "$req")"
      r="" rm_="" k=0
      set -- $(cat "$req")
      while [ $# -gt 0 ]; do
        case $1 in
          --remote) rm_=${2:-}; shift ;;
          --keep) k=1 ;;
          *) r=$1 ;;
        esac
        shift
      done
      if [ -z "$r" ]; then
        echo "empty request" >> "$req"
        continue
      fi
      BBCI_REQ=$req                       # check_one appends how it ended: a verdict, or interrupted
      check_one "$r" "$rm_" "$k"
      BBCI_REQ=
    done
    ;;
  --last)
    [ $# -ge 2 ] || usage
    sha=$(git -C "$REPO" rev-parse --verify -q "$2^{commit}" || echo "$2")
    if [ -f "$WORK/verdicts/$sha.json" ]; then cat "$WORK/verdicts/$sha.json"; else echo "no verdict for $2"; exit 2; fi
    ;;
  -*) usage ;;
  *)
    r=$1 rm_="" k=0
    shift
    while [ $# -gt 0 ]; do
      case $1 in
        --remote) rm_=${2:?--remote needs a name}; shift ;;
        --keep) k=1 ;;
        *) usage ;;
      esac
      shift
    done
    check_one "$r" "$rm_" "$k"
    exit $?
    ;;
esac
