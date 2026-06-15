# tests/sync/test_conflict_finish.sh
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config; . "$CTRL/config"
# custom commit edits the SAME line upstream will change → conflict
g "$FORK" checkout -q live
printf 'line1\nMY-EDIT\nline3\n' > "$FORK/skills/foo/SKILL.md"
g "$FORK" add -A; g "$FORK" commit -qm "custom: edit foo line2"
add_release v1.1.0 "UPSTREAM-EDIT"

run_sync
assert_file "$CTRL/STATUS"                          # paused
assert_grep "PAUSED" "$CTRL/STATUS"
assert_eq "$(cat "$CTRL/PENDING")" "v1.1.0" pending-tag
# live tree must be untouched (isolation invariant)
assert_grep "MY-EDIT" "$FORK/skills/foo/SKILL.md"
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.0.0" base-still-old

# user resolves in the worktree, keeping MY-EDIT
printf 'line1\nMY-EDIT\nline3\n' > "$WORKTREE/skills/foo/SKILL.md"
g "$WORKTREE" add skills/foo/SKILL.md
GIT_EDITOR=true g "$WORKTREE" -c rerere.enabled=true rebase --continue

run_finish
assert_nofile "$CTRL/STATUS"
assert_nofile "$CTRL/PENDING"
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.1.0" base-advanced
assert_grep "MY-EDIT" "$FORK/skills/foo/SKILL.md"   # live now updated, edit preserved
assert_grep '"result":"manual-resolved"' "$CTRL/history.ndjson"
pass
