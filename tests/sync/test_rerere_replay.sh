# tests/sync/test_rerere_replay.sh — same conflict twice auto-resolves the 2nd time
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config; . "$CTRL/config"
g "$FORK" config rerere.enabled true
g "$FORK" checkout -q live
printf 'line1\nMY-EDIT\nline3\n' > "$FORK/skills/foo/SKILL.md"
g "$FORK" add -A; g "$FORK" commit -qm "custom: edit foo line2"

add_release v1.1.0 "UPSTREAM-EDIT"
run_sync                                            # conflict → paused
printf 'line1\nMY-EDIT\nline3\n' > "$WORKTREE/skills/foo/SKILL.md"
g "$WORKTREE" add skills/foo/SKILL.md
GIT_EDITOR=true g "$WORKTREE" -c rerere.enabled=true rebase --continue
run_finish                                          # rerere now remembers this resolution

# Reset live and BASE_TAG so the same conflict recurs on the next sync
g "$FORK" reset --hard v1.0.0
printf 'line1\nMY-EDIT\nline3\n' > "$FORK/skills/foo/SKILL.md"
g "$FORK" add -A; g "$FORK" commit -qm "custom: edit foo line2"
echo "BASE_TAG=v1.0.0" > "$CTRL/state"

run_sync                                            # same conflict → rerere auto-resolves
assert_nofile "$CTRL/STATUS"                        # auto-resolved, no pause
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.1.0" base-advanced-auto
assert_grep '"result":"rerere-resolved"' "$CTRL/history.ndjson"
pass
