# tests/sync/test_refresh_control.sh — S6 / D-136: the deploy refreshes the control dir's code, and nothing else.
# shellcheck shell=bash
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config
R="$SCRIPTS/refresh-control.sh"
for f in lib.sh sync.sh finish.sh rollback.sh apply.sh status.sh; do echo "# old $f" > "$CTRL/$f"; done
echo "PAUSED" > "$CTRL/STATUS"; echo v9 > "$CTRL/PENDING"; echo '{"x":1}' > "$CTRL/history.ndjson"; mkdir -p "$CTRL/rebase-wt"; echo keep > "$CTRL/rebase-wt/f"
cp "$CTRL/config" "$CTRL/config.before"; cp "$CTRL/state" "$CTRL/state.before"

set +e; bash "$R" --ctrl "$CTRL" --check > "$SANDBOX/check.out"; rc=$?; set -e
assert_eq "$rc" 1 check-differs
bash "$R" --ctrl "$CTRL" --dry-run > "$SANDBOX/dry.out"
assert_grep "would-write sync.sh" "$SANDBOX/dry.out"
assert_grep "# old sync.sh" "$CTRL/sync.sh"                              # a dry run writes nothing

bash "$R" --ctrl "$CTRL" > "$SANDBOX/write.out"
for f in lib.sh sync.sh finish.sh rollback.sh apply.sh status.sh; do cmp -s "$SCRIPTS/$f" "$CTRL/$f" || { echo "FAIL: $f not refreshed"; exit 1; }; done
bash "$R" --ctrl "$CTRL" --check > /dev/null                            # now equal: rc 0
# the paused sync and the settings are untouched
assert_eq "$(cat "$CTRL/STATUS")" PAUSED status-kept; assert_eq "$(cat "$CTRL/PENDING")" v9 pending-kept
assert_eq "$(cat "$CTRL/rebase-wt/f")" keep worktree-kept; assert_eq "$(cat "$CTRL/history.ndjson")" '{"x":1}' history-kept
cmp -s "$CTRL/config" "$CTRL/config.before" || { echo "FAIL: config changed"; exit 1; }
cmp -s "$CTRL/state" "$CTRL/state.before" || { echo "FAIL: state changed"; exit 1; }
# a directory that is not a control dir is refused
set +e; bash "$R" --ctrl "$SANDBOX" > /dev/null 2>&1; rc=$?; set -e
assert_eq "$rc" 2 not-a-control-dir
pass
