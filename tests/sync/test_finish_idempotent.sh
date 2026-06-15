# tests/sync/test_finish_idempotent.sh — re-running finish after a wedge clears STATUS
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config; . "$CTRL/config"
g "$FORK" checkout -q live
printf 'line1\nMY-EDIT\nline3\n' > "$FORK/skills/foo/SKILL.md"
g "$FORK" add -A; g "$FORK" commit -qm "custom: edit foo line2"
add_release v1.1.0 "UPSTREAM-EDIT"
run_sync                                       # paused
printf 'line1\nMY-EDIT\nline3\n' > "$WORKTREE/skills/foo/SKILL.md"
g "$WORKTREE" add skills/foo/SKILL.md
GIT_EDITOR=true g "$WORKTREE" -c rerere.enabled=true rebase --continue
run_finish                                     # normal completion (sync-rebase deleted)
assert_nofile "$CTRL/STATUS"
# Simulate a crash that left STATUS/PENDING behind after sync-rebase was already gone
echo "v1.1.0" > "$CTRL/PENDING"
echo "stale paused notice" > "$CTRL/STATUS"
run_finish                                     # must tolerate missing sync-rebase and clear STATUS
assert_nofile "$CTRL/STATUS"
assert_nofile "$CTRL/PENDING"
pass
