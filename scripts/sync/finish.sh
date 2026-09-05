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
# Drive the rebase to completion automatically: keep running 'git rebase --continue'
# while every conflict has been resolved+staged. Stop only if genuine unmerged files
# remain (the one thing a human must fix), telling the user exactly what to do.
maxsteps=$(( $(g "$WORKTREE" rev-list --count "$BASE_TAG..$LIVE_BRANCH" 2>/dev/null || echo 200) + 5 ))
steps=0
while rebase_in_progress; do
  if g "$WORKTREE" diff --name-only --diff-filter=U | grep -q .; then
    echo "⚠ Unresolved conflicts remain — edit these, then re-run finish.sh:"
    g "$WORKTREE" diff --name-only --diff-filter=U | sed 's/^/    /'
    echo
    echo "  cd \"$WORKTREE\""
    echo "  # resolve <<<<<<< ======= >>>>>>> markers in the files above"
    echo "  git add -A"
    echo "  \"$SPSYNC_SCRIPT_DIR/finish.sh\""
    exit 1
  fi
  steps=$((steps + 1))
  if [ "$steps" -gt "$maxsteps" ]; then
    echo "Rebase not converging after $steps steps — inspect $WORKTREE manually."; exit 1
  fi
  # Keep git's own output: it is the only thing that says WHY the continue failed (commit
  # became empty, object store unwritable, a hook or signer refused). Discarding it leaves
  # the one-line "inspect the worktree" message and nothing to act on.
  if ! continue_out="$(GIT_EDITOR=true g "$WORKTREE" rebase --continue 2>&1)"; then
    echo "git rebase --continue failed with no unmerged files — inspect $WORKTREE."
    echo "git said:"
    printf '%s\n' "$continue_out" | sed 's/^/    /'
    exit 1
  fi
done

finalize_live "$NEW" "manual-resolved"
rm -f "$STATUS_FILE" "$PENDING_FILE"
echo "Resolved and applied: live now on $NEW. Changes load on your next Claude session."
