# tests/sync/test_rollback.sh
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config
fork_custom "skills/mine/SKILL.md" "v-a"
add_release v1.1.0 "u1"; run_sync                   # snapshot #1 (mine = v-a)
SNAP1="$(g "$FORK" tag -l 'snapshot/*' | head -n1)"
printf 'v-b\n' > "$FORK/skills/mine/SKILL.md"; g "$FORK" add -A; g "$FORK" commit -qm "mine v-b"
add_release v1.2.0 "u2"; run_sync                   # snapshot #2 (mine = v-b)

# list shows 2 snapshots
assert_eq "$(run_rollback list | grep -c snapshot/)" "2" list-count

# rollback to SNAP1 → live tree shows v-a again, BASE_TAG reset to that snapshot's base
run_rollback to "$SNAP1"
assert_grep "v-a" "$FORK/skills/mine/SKILL.md"
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.1.0" base-after-rollback

# rework: branch off SNAP1, edit, promote → live carries the reworked content + new snapshot
run_rollback rework "$SNAP1"
printf 'v-a-reworked\n' > "$FORK/skills/mine/SKILL.md"; g "$FORK" add -A; g "$FORK" commit -qm "rework"
run_rollback promote
assert_grep "v-a-reworked" "$FORK/skills/mine/SKILL.md"
assert_eq "$(g "$FORK" rev-parse --abbrev-ref HEAD)" "live" back-on-live
assert_eq "$(g "$FORK" tag -l 'snapshot/*' | wc -l | tr -d ' ')" "3" new-snapshot-after-promote
pass
