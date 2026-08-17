# tests/sync/test_finish_refresh_cwd.sh — the refresh must run from a directory that still exists.
# The paused-rebase STATUS banner tells you to `cd <worktree>` and then run finish.sh, but
# finalize_live deletes that worktree before running SPSYNC_REFRESH_CMD — so the refresh
# subprocess inherits a deleted cwd and dies (`claude` reports "ENOENT: Bun could not find a
# file"), logging refresh-failed on every conflict resolution done the documented way.
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config; . "$CTRL/config"
cat >> "$CTRL/config" <<EOF
SPSYNC_REFRESH_CMD='/bin/pwd > "$CTRL/refresh-cwd" 2>&1'
EOF

g "$FORK" checkout -q live
printf 'line1\nMY-EDIT\nline3\n' > "$FORK/skills/foo/SKILL.md"
g "$FORK" add -A; g "$FORK" commit -qm "custom: edit foo line2"
add_release v1.1.0 "UPSTREAM-EDIT"

run_sync                                            # conflict → paused
printf 'line1\nMY-EDIT\nline3\n' > "$WORKTREE/skills/foo/SKILL.md"
g "$WORKTREE" add skills/foo/SKILL.md

# Exactly what the STATUS banner instructs: run finish.sh from inside the worktree.
( cd "$WORKTREE" && SPSYNC_CONFIG="$CTRL/config" bash "$SCRIPTS/finish.sh" >/dev/null )

assert_file "$CTRL/refresh-cwd"
REFRESH_CWD="$(cat "$CTRL/refresh-cwd")"
[ -d "$REFRESH_CWD" ] || { echo "FAIL: refresh ran from a nonexistent cwd: [$REFRESH_CWD]"; exit 1; }
grep -q '"result":"refresh-failed"' "$CTRL/history.ndjson" && { echo "FAIL: refresh reported failure"; exit 1; }
pass
