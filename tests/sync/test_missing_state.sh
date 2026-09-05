# tests/sync/test_missing_state.sh — missing BASE_TAG fails loudly, doesn't corrupt live
# shellcheck shell=bash
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config
fork_custom "skills/mine/SKILL.md" "x"
rm -f "$CTRL/state"                            # state lost/corrupt
add_release v1.1.0 "u"
run_sync || true                              # expected to exit non-zero
assert_grep '"result":"error-no-base"' "$CTRL/history.ndjson"
assert_eq "$(g "$FORK" rev-parse --abbrev-ref HEAD)" "live" still-on-live
assert_eq "$(g "$FORK" tag -l 'snapshot/*' | wc -l | tr -d ' ')" "0" no-snapshot
pass
