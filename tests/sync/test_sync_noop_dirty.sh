# tests/sync/test_sync_noop_dirty.sh
# shellcheck shell=bash
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config
run_sync                                            # no new tag → no-op
assert_grep '"result":"noop"' "$CTRL/history.ndjson"
assert_eq "$(g "$FORK" tag -l 'snapshot/*' | wc -l | tr -d ' ')" "0" no-snapshot-on-noop

add_release v1.1.0 "x"
echo "dirty" >> "$FORK/skills/foo/SKILL.md"         # uncommitted edit
run_sync
assert_grep '"result":"skipped-dirty"' "$CTRL/history.ndjson"
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.0.0" base-unchanged-when-dirty
pass
