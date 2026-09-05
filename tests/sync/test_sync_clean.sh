# tests/sync/test_sync_clean.sh
# shellcheck shell=bash
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config
fork_custom "skills/mine/SKILL.md" "my custom skill"   # custom commit on live
add_release v1.1.0 "line2-upstream-changed"            # new upstream release, no overlap with mine

run_sync

# live now based on v1.1.0, custom commit replayed, upstream change present
assert_eq "$(g "$FORK" describe --tags --abbrev=0 live~1 2>/dev/null || echo none)" "v1.1.0" rebased-onto
assert_file "$FORK/skills/mine/SKILL.md"
assert_grep "line2-upstream-changed" "$FORK/skills/foo/SKILL.md"
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.1.0" base-updated
assert_eq "$(g "$FORK" tag -l 'snapshot/*' | wc -l | tr -d ' ')" "1" one-snapshot
assert_grep '"result":"clean"' "$CTRL/history.ndjson"
assert_nofile "$CTRL/STATUS"
pass
