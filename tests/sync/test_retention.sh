# tests/sync/test_retention.sh — old snapshots pruned on sync
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config
fork_custom "skills/mine/SKILL.md" "x"
# Fabricate an old snapshot tag (95 days ago) using a backdated commit/tag date
OLD_DATE="$(date -u -d '-95 days' +%Y-%m-%dT%H:%M:%SZ)"
OLD="$(GIT_COMMITTER_DATE="$OLD_DATE" g "$FORK" commit-tree \
       "$(g "$FORK" rev-parse live^{tree})" -p "$(g "$FORK" rev-parse live)" -m old)"
GIT_COMMITTER_DATE="$OLD_DATE" g "$FORK" tag -a 'snapshot/2000-01-01-000000' "$OLD" -m "sync onto v1.0.0 (clean)"
add_release v1.1.0 "u"; run_sync                     # triggers prune_snapshots
if g "$FORK" rev-parse -q --verify 'refs/tags/snapshot/2000-01-01-000000' >/dev/null 2>&1; then
  echo "FAIL: old snapshot not pruned"; exit 1
fi
pass
