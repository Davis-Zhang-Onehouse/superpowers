#!/usr/bin/env bash
set -euo pipefail
: "${SPSYNC_CONFIG:=$HOME/.superpowers-sync/config}"
. "$SPSYNC_CONFIG"
SPSYNC_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SPSYNC_SCRIPT_DIR/lib.sh"
load_state

[ -f "$STATUS_FILE" ] || { echo "No paused rebase."; exit 0; }
NEW="$(cat "$PENDING_FILE" 2>/dev/null || true)"
[ -n "$NEW" ] || { echo "PENDING tag missing in $PENDING_FILE; cannot finish. Remove $STATUS_FILE manually if stuck."; exit 1; }

# Refuse if the rebase isn't actually finished in the worktree.
rebase_in_progress() {
  local d p
  for d in rebase-merge rebase-apply; do
    p="$(g "$WORKTREE" rev-parse --git-path "$d" 2>/dev/null || true)"
    [ -n "$p" ] && { [ -d "$p" ] || [ -d "$WORKTREE/$p" ]; } && return 0
  done
  return 1
}
if rebase_in_progress; then
  echo "Rebase still in progress in $WORKTREE — resolve conflicts and run 'git rebase --continue' first."
  exit 1
fi

finalize_live "$NEW" "manual-resolved"
rm -f "$STATUS_FILE" "$PENDING_FILE"
echo "Resolved and applied: live now on $NEW. Changes load on your next Claude session."
