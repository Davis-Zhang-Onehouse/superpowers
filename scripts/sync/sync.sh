#!/usr/bin/env bash
set -euo pipefail
SPSYNC_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Default to the config beside this script. bootstrap.sh writes config into the
# same control dir it copies these scripts into, so an install scoped outside
# $HOME (e.g. under a shared-box home subdir) works when invoked by absolute
# path with no SPSYNC_CONFIG set — which is how the paused-rebase STATUS
# instructions tell you to run finish.sh.
: "${SPSYNC_CONFIG:=$SPSYNC_SCRIPT_DIR/config}"
. "$SPSYNC_CONFIG"
. "$SPSYNC_SCRIPT_DIR/lib.sh"
load_state
: "${BASE_TAG:=}"

# Don't start a new sync while a paused rebase awaits resolution.
if [ -f "$STATUS_FILE" ]; then
  echo "A rebase is paused — resolve it and run finish.sh (see $STATUS_FILE)."; exit 0
fi

# Only operate when the repo is on the live branch (rework/other branches are off-limits).
cur_branch="$(g "$REPO" rev-parse --abbrev-ref HEAD)"
if [ "$cur_branch" != "$LIVE_BRANCH" ]; then
  log_event skipped-branch "" ""
  echo "Repo is on '$cur_branch', not '$LIVE_BRANCH'; skipping sync."; exit 0
fi

# Need a known base to rebase from.
if [ -z "$BASE_TAG" ]; then
  log_event error-no-base "" ""
  echo "No BASE_TAG in $STATE_FILE; run bootstrap.sh first."; exit 1
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
  # --rebase-merges: live can carry a merge that reconciled a diverged copy of the fork, whose
  # two parents hold the same work twice. Linearising that replays every commit of the second
  # parent on top of its own already-applied twin — one conflict per duplicate, and a silent
  # revert wherever the stale patch still applies. Preserving the merge replays each parent
  # onto the new base exactly once. For linear history it behaves like a plain rebase.
  g "$WORKTREE" -c rerere.enabled=true -c rerere.autoupdate=true \
     rebase --rebase-merges --onto "$NEW" "$BASE_TAG" sync-rebase
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
  {
    echo "⚠ superpowers auto-sync PAUSED: rebase onto $NEW hit conflicts."
    echo "  Conflicted files: ${conflicts%,}"
    echo "  Resolve (copy-paste — everything after 'git add' is automatic):"
    echo "    cd \"$WORKTREE\""
    echo "    # edit the files above: resolve <<<<<<< ======= >>>>>>> markers"
    echo "    git add -A"
    echo "    \"$CONTROL_DIR/finish.sh\"   # continues the rebase, adopts into live, refreshes the plugin"
  } > "$STATUS_FILE"
  log_event paused "$NEW" "" "${conflicts%,}"
  exit 0
fi

# Success — adopt the rebased branch into live and snapshot.
finalize_live "$NEW" "$result"
