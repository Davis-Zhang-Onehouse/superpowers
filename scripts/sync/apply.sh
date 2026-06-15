#!/usr/bin/env bash
set -euo pipefail
: "${SPSYNC_CONFIG:=$HOME/.superpowers-sync/config}"
. "$SPSYNC_CONFIG"
SPSYNC_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SPSYNC_SCRIPT_DIR/lib.sh"
load_state
: "${BASE_TAG:=}"

# Optional: -m "message" commits all current changes before snapshotting.
msg=""
if [ "${1:-}" = "-m" ]; then msg="${2:-}"; fi

# Must be on the live branch.
cur="$(g "$REPO" rev-parse --abbrev-ref HEAD)"
[ "$cur" = "$LIVE_BRANCH" ] || { echo "Not on $LIVE_BRANCH (on '$cur'). Switch to $LIVE_BRANCH first."; exit 1; }

# Don't apply while a rebase is paused.
[ -f "$STATUS_FILE" ] && { echo "A rebase is paused; run finish.sh before applying edits."; exit 1; }

if [ -n "$msg" ]; then
  g "$REPO" add -A
  if g "$REPO" diff --cached --quiet; then
    echo "Nothing staged to commit."
  else
    g "$REPO" commit -q -m "$msg"
  fi
else
  if ! g "$REPO" diff --quiet || ! g "$REPO" diff --cached --quiet; then
    echo "Uncommitted changes present. Commit them, or pass -m \"message\" to commit + apply."; exit 1
  fi
fi

stamp="$(new_snapshot_tag)"
g "$REPO" tag -a "$stamp" -m "edit on ${BASE_TAG:-unknown} (manual)"
log_event edit "${BASE_TAG}" "$stamp"
prune_history; prune_snapshots

if [ -n "${SPSYNC_REFRESH_CMD:-}" ]; then
  eval "$SPSYNC_REFRESH_CMD" || log_event refresh-failed "${BASE_TAG}" "$stamp"
fi
echo "Applied: $stamp (plugin cache refreshed). Changes load on your next Claude session."
