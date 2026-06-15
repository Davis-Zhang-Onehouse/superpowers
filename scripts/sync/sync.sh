#!/usr/bin/env bash
set -euo pipefail
: "${SPSYNC_CONFIG:=$HOME/.superpowers-sync/config}"
. "$SPSYNC_CONFIG"
SPSYNC_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SPSYNC_SCRIPT_DIR/lib.sh"
load_state

# Don't start a new sync while a paused rebase awaits resolution.
if [ -f "$STATUS_FILE" ]; then
  echo "A rebase is paused — resolve it and run finish.sh (see $STATUS_FILE)."; exit 0
fi

g "$REPO" fetch "$UPSTREAM_REMOTE" --tags --quiet
NEW="$(latest_tag)"

if [ "$NEW" = "$BASE_TAG" ]; then
  log_event noop "$NEW" ""; prune_history; prune_snapshots; exit 0
fi

# Safety: never clobber in-progress edits in the live tree.
if ! g "$REPO" diff --quiet || ! g "$REPO" diff --cached --quiet; then
  log_event skipped-dirty "$NEW" ""
  echo "Live tree has uncommitted changes; skipping sync to $NEW."; exit 0
fi

# Fresh isolated worktree on a temp branch copied from live.
g "$REPO" worktree prune
rm -rf "$WORKTREE"
g "$REPO" worktree add -f -B sync-rebase "$WORKTREE" "$LIVE_BRANCH" >/dev/null

# rerere-aware rebase: auto-continue when rerere resolved everything; pause on new conflicts.
rebase_step() {
  g "$WORKTREE" -c rerere.enabled=true -c rerere.autoupdate=true \
     rebase --onto "$NEW" "$BASE_TAG" sync-rebase
}
continue_step() { GIT_EDITOR=true g "$WORKTREE" rebase --continue; }

# Upper bound on continue attempts: at most one per replayed commit (+ margin).
maxsteps=$(( $(g "$WORKTREE" rev-list --count "$BASE_TAG..$LIVE_BRANCH") + 2 ))
result="clean"
if ! rebase_step; then
  steps=0
  while true; do
    if g "$WORKTREE" diff --name-only --diff-filter=U | grep -q .; then
      result="paused"; break                      # genuine new conflict
    fi
    steps=$((steps + 1))
    if [ "$steps" -gt "$maxsteps" ]; then
      result="paused"; break                      # abnormal: not converging, hand to human
    fi
    if continue_step; then result="rerere-resolved"; break; fi
    # else: rerere staged this step; loop to advance to the next commit
  done
fi

if [ "$result" = "paused" ]; then
  conflicts="$(g "$WORKTREE" diff --name-only --diff-filter=U | tr '\n' ',' )"
  echo "$NEW" > "$PENDING_FILE"
  printf '%s\n' "⚠ superpowers rebase PAUSED in $WORKTREE onto $NEW — conflicts: ${conflicts%,}. cd there, resolve, 'git rebase --continue', then run finish.sh" > "$STATUS_FILE"
  log_event paused "$NEW" "" "${conflicts%,}"
  exit 0
fi

# Success — adopt the rebased branch into live and snapshot.
finalize_live "$NEW" "$result"
