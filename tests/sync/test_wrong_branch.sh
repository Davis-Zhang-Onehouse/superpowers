# tests/sync/test_wrong_branch.sh — sync refuses to run when repo is not on live
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config
fork_custom "skills/mine/SKILL.md" "x"
add_release v1.1.0 "u"
g "$FORK" switch -q -c rework/test            # repo now NOT on live
run_sync
assert_grep '"result":"skipped-branch"' "$CTRL/history.ndjson"
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.0.0" base-unchanged
assert_eq "$(g "$FORK" rev-parse --abbrev-ref HEAD)" "rework/test" still-on-rework
assert_eq "$(g "$FORK" tag -l 'snapshot/*' | wc -l | tr -d ' ')" "0" no-snapshot
pass
