#!/usr/bin/env bash
set -euo pipefail
SPSYNC_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Default to the config beside this script. bootstrap.sh writes config into the
# same control dir it copies these scripts into, so an install scoped outside
# $HOME (e.g. under a shared-box home subdir) works when invoked by absolute
# path with no SPSYNC_CONFIG set — which is how the paused-rebase STATUS
# instructions tell you to run finish.sh.
: "${SPSYNC_CONFIG:=$SPSYNC_SCRIPT_DIR/config}"
# shellcheck source=/dev/null  # generated at install time; there is no file in the repo to follow
. "$SPSYNC_CONFIG"
. "$SPSYNC_SCRIPT_DIR/lib.sh"
load_state
: "${BASE_TAG:=}"

# Parse the upstream tag a snapshot was built on, from its annotation "sync onto vX.Y.Z (...)"
snap_base() { g "$REPO" tag -l --format='%(contents)' "$1" | sed -n 's/.*sync onto \(v[0-9.]*\).*/\1/p' | head -n1; }

cmd="${1:-list}"
case "$cmd" in
  list)
    g "$REPO" tag -l 'snapshot/*' --sort=-creatordate \
      --format='%(refname:short)  %(creatordate:short)  %(contents:subject)'
    ;;
  to)
    snap="$2"
    g "$REPO" rev-parse -q --verify "refs/tags/$snap" >/dev/null || { echo "no such snapshot: $snap"; exit 1; }
    g "$REPO" switch -q "$LIVE_BRANCH"
    g "$REPO" reset --hard "$snap" >/dev/null
    base="$(snap_base "$snap")"; [ -n "$base" ] && set_state BASE_TAG "$base"
    [ -n "${SPSYNC_REFRESH_CMD:-}" ] && eval "$SPSYNC_REFRESH_CMD" || true
    echo "live now at $snap (base ${base:-unknown}). Loads on your next Claude session."
    ;;
  rework)
    snap="$2"
    g "$REPO" switch -q -c "rework/${snap#snapshot/}" "$snap"
    echo "On branch rework/${snap#snapshot/}. Edit + commit, then: rollback.sh promote"
    ;;
  promote)
    cur="$(g "$REPO" rev-parse --abbrev-ref HEAD)"
    case "$cur" in rework/*) ;; *) echo "Not on a rework/* branch."; exit 1;; esac
    g "$REPO" switch -q "$LIVE_BRANCH"
    g "$REPO" reset --hard "$cur" >/dev/null
    g "$REPO" branch -D "$cur" >/dev/null
    stamp="$(new_snapshot_tag)"
    g "$REPO" tag -a "$stamp" -m "promote rework onto ${BASE_TAG} (manual)"
    log_event promote "${BASE_TAG}" "$stamp"
    prune_history; prune_snapshots
    [ -n "${SPSYNC_REFRESH_CMD:-}" ] && eval "$SPSYNC_REFRESH_CMD" || true
    echo "Promoted to live as $stamp."
    ;;
  *) echo "usage: rollback.sh {list|to <snap>|rework <snap>|promote}"; exit 1;;
esac
