#!/bin/bash
# sync-upstream.sh - fork-only (never in a PR): bring JOEBOX's updates (j3threejay/blackbox-mod main) into the fork.
#
#   bench/sync-upstream.sh [-C repo] [-n] [-j jobs] [pr-branch...]
#     -C  the clone (default: the repo this script sits in)
#     -n  report only: what would merge, which PR branches are behind; no ref moves
#     -j  prcheck.sh's parallel jobs (default 3)
#     pr-branch...  the open PR branches to bring up to date (default: bench/pr-branches, one per line)
#
# What it does (D-019 (4): where Justin took one of ours, HIS version wins; README.md is kept ours, .gitattributes
# `README.md merge=ours`, the driver set below):
#   1. fetch upstream and origin; fast-forward the local `main` mirror to upstream/main (refuses if main diverged);
#   2. merge upstream/main into `maigre` on a temporary branch sync/maigre-<sha> in a temporary worktree, refresh
#      docs/JOEBOX.md from upstream's README, commit; on a conflict it STOPS and leaves that worktree for a human;
#   3. merge upstream/main into each PR branch the same way (sync/<branch>-<sha>), never a rebase;
#   4. bench/prcheck.sh -b upstream/main on the sync branches (each built and checked alone);
#   5. prints the result and the commands that land it (fast-forward each real branch to its sync branch, push).
# It never pushes and never moves maigre, main's remote or a PR branch on origin: landing is Thomas's (one paste).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(git -C "$HERE" rev-parse --show-toplevel)
DRY=0; JOBS=3
while getopts "C:nj:" o; do case $o in C) REPO=$OPTARG;; n) DRY=1;; j) JOBS=$OPTARG;; *) exit 2;; esac; done
shift $((OPTIND - 1))
G() { git -C "$REPO" "$@"; }
PRS=("$@")
[ ${#PRS[@]} -eq 0 ] && [ -f "$HERE/pr-branches" ] && mapfile -t PRS < <(grep -v '^\s*#' "$HERE/pr-branches" | grep .)

G config merge.ours.driver true                       # `merge=ours` in .gitattributes: keep our side of README.md
G fetch -q upstream && G fetch -q origin || { echo "fetch failed"; exit 1; }
UP=$(G rev-parse upstream/main); S=${UP:0:7}
echo "upstream/main = $S  $(G log -1 --format='%cs %s' "$UP" | cut -c1-100)"

# 1. the main mirror (local), fast-forward only
if G merge-base --is-ancestor main "$UP"; then
    [ "$(G rev-parse main)" = "$UP" ] && echo "main: up to date" || {
        echo "main: $(G rev-list --count main.."$UP") new upstream commit(s)"
        [ $DRY = 1 ] || G fetch -q . "$UP":main; }
else
    echo "main: DIVERGED from upstream/main (it must stay a pure mirror) - stopping"; exit 1
fi

WORK=${SYNC_WORK:-$REPO/out/sync}; mkdir -p "$WORK"
merge_into() {                                        # $1 branch: merge upstream into sync/<branch>-<sha>
    local b=$1 sb="sync/$(echo "$1" | tr '/' '-')-$S" wt="$WORK/$(echo "$1" | tr '/' '-')-$S"
    if G merge-base --is-ancestor "$UP" "$b"; then echo "$b: already has $S"; return 0; fi
    echo "$b: $(G rev-list --count "$b".."$UP") upstream commit(s) to merge"
    [ $DRY = 1 ] && return 0
    rm -rf "$wt"; G worktree add -q -B "$sb" "$wt" "$b" || return 1
    ln -sf /srv/dev/firmware/BLACKBOX-3.1.9.bin "$wt/firmware/BLACKBOX-3.1.9.bin" 2>/dev/null
    ln -sfn /srv/dev/venvs/bb "$wt/.venv"
    if ! git -C "$wt" merge -q --no-ff --no-edit -m "Merge JOEBOX upstream $S into $b" "$UP"; then
        echo "  CONFLICT in $b: resolve in $wt (toward Justin's version where he took ours, D-019 (4)), commit, rerun"
        git -C "$wt" diff --name-only --diff-filter=U | sed 's/^/    /'; return 1
    fi
    if [ "$b" = maigre ]; then                        # Justin's README, whole, with where it came from
        mkdir -p "$wt/docs"
        { echo "<!-- JOEBOX's README.md at upstream $S ($(G log -1 --format=%cs "$UP")), copied by bench/sync-upstream.sh;"
          echo "     edit nothing here: it is replaced at every sync. The fork's own README is ../README.md. -->"; echo
          G show "$UP":README.md; } > "$wt/docs/JOEBOX.md"
        git -C "$wt" add docs/JOEBOX.md
        git -C "$wt" diff --cached --quiet || git -C "$wt" commit -q -m "docs/JOEBOX.md: JOEBOX's README at upstream $S"
    fi
    echo "  merged: $sb = $(git -C "$wt" rev-parse --short HEAD)"; SYNCED+=("$sb"); return 0
}

SYNCED=(); FAIL=0
for b in maigre "${PRS[@]}"; do merge_into "$b" || FAIL=1; done
[ $DRY = 1 ] && exit 0
[ ${#SYNCED[@]} -eq 0 ] && { echo "nothing to merge"; exit $FAIL; }

# 4. each sync branch built and checked alone, against upstream
"$HERE/prcheck.sh" -C "$REPO" -j "$JOBS" -b upstream/main "${SYNCED[@]}"

# 5. how to land it (Thomas)
echo; echo "To land (after reading the report above):"
for sb in "${SYNCED[@]}"; do
    b=${sb#sync/}; b=${b%-$S}
    for real in maigre "${PRS[@]}"; do [ "$(echo "$real" | tr '/' '-')" = "$b" ] && b=$real; done
    echo "  git -C $REPO fetch . $sb:$b && git -C $REPO push origin $b"
done
echo "  git -C $REPO push origin main          # the mirror"
exit $FAIL
