# tests/sync/test_apply.sh — apply.sh commits, snapshots, and (would) refresh on manual edits
# shellcheck shell=bash
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config; . "$CTRL/config"
g "$FORK" checkout -q live

# 1) edit a skill, apply with a message → commits + snapshots + logs "edit"
mkdir -p "$FORK/skills/mine"
printf 'my new skill\n' > "$FORK/skills/mine/SKILL.md"
SPSYNC_CONFIG="$CTRL/config" bash "$SCRIPTS/apply.sh" -m "add mine"
assert_eq "$(g "$FORK" status --porcelain | wc -l | tr -d ' ')" "0" clean-after-apply
assert_eq "$(g "$FORK" tag -l 'snapshot/*' | wc -l | tr -d ' ')" "1" one-snapshot
assert_grep '"result":"edit"' "$CTRL/history.ndjson"
assert_eq "$(SPSYNC_CONFIG="$CTRL/config" bash "$SCRIPTS/rollback.sh" list | grep -c snapshot/)" "1" listed-in-timeline

# 2) apply with no -m and a dirty tree → refuses (exit non-zero), no new snapshot
printf 'dirty\n' >> "$FORK/skills/mine/SKILL.md"
SPSYNC_CONFIG="$CTRL/config" bash "$SCRIPTS/apply.sh" && { echo "FAIL: apply should refuse dirty tree without -m"; exit 1; }
assert_eq "$(g "$FORK" tag -l 'snapshot/*' | wc -l | tr -d ' ')" "1" no-new-snapshot-on-refusal

# 3) wrong branch → refuses
g "$FORK" checkout -- skills/mine/SKILL.md   # clean the dirty edit
g "$FORK" switch -q -c rework/x
SPSYNC_CONFIG="$CTRL/config" bash "$SCRIPTS/apply.sh" -m "x" && { echo "FAIL: apply should refuse off-live"; exit 1; }
pass
