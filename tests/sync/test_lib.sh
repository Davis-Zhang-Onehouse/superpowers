# tests/sync/test_lib.sh
# shellcheck shell=bash
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config
export SPSYNC_CONFIG="$CTRL/config"

# shellcheck source=/dev/null  # written by the harness into a sandbox
. "$SPSYNC_CONFIG"; . "$SCRIPTS/lib.sh"
load_state
assert_eq "$BASE_TAG" "v1.0.0" base
set_state BASE_TAG v9.9.9
load_state
assert_eq "$BASE_TAG" "v9.9.9" base-after-set
log_event clean v9.9.9 snapshot/x
assert_grep '"result":"clean"' "$CTRL/history.ndjson"

# prune drops >90d lines, keeps recent
printf '%s\n' '{"ts":"2000-01-01T00:00:00Z","result":"old"}' >> "$CTRL/history.ndjson"
prune_history
grep -q '"old"' "$CTRL/history.ndjson" && { echo "FAIL: old line not pruned"; exit 1; }
log_event clean v9.9.9 snapshot/y
prune_history
assert_grep '"snapshot":"snapshot/y"' "$CTRL/history.ndjson"
pass
