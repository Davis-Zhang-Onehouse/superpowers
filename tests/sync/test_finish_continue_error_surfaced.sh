# tests/sync/test_finish_continue_error_surfaced.sh — when `git rebase --continue` fails with no
# unmerged files, finish.sh discards git's stdout AND stderr and prints only "failed with no
# unmerged files — inspect <worktree>". The one message that says WHY (empty commit, refused
# commit object, unwritable object store) is thrown away, leaving the user nothing to act on.
# finish.sh must relay what git said.
#
# git itself is stubbed for this one call: --continue failures are environment-dependent
# (git 2.34 silently drops now-empty commits), so a stub is the only deterministic way to
# reach the error path. Everything else in the run is real git.
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config; . "$CTRL/config"

g "$FORK" checkout -q live
printf 'line1\nMY-EDIT\nline3\n' > "$FORK/skills/foo/SKILL.md"
g "$FORK" add -A; g "$FORK" commit -qm "custom: edit foo line2"
add_release v1.1.0 "UPSTREAM-EDIT"

run_sync                                            # conflict → paused
printf 'line1\nMY-EDIT\nline3\n' > "$WORKTREE/skills/foo/SKILL.md"
g "$WORKTREE" add skills/foo/SKILL.md

REAL_GIT="$(command -v git)"
mkdir -p "$SANDBOX/bin"
cat > "$SANDBOX/bin/git" <<EOF
#!/bin/sh
for a in "\$@"; do
  [ "\$a" = "--continue" ] && { echo "SENTINEL-REASON" >&2; exit 1; }
done
exec "$REAL_GIT" "\$@"
EOF
chmod +x "$SANDBOX/bin/git"

set +e
OUT="$(PATH="$SANDBOX/bin:$PATH" SPSYNC_CONFIG="$CTRL/config" bash "$SCRIPTS/finish.sh" 2>&1)"; RC=$?
set -e

assert_eq "$RC" "1" finish-reports-failure
printf '%s\n' "$OUT" | grep -q "SENTINEL-REASON" || {
  echo "FAIL: finish.sh swallowed git's reason. Its whole output was:"
  printf '%s\n' "$OUT" | sed 's/^/    /'; exit 1; }
assert_file "$CTRL/STATUS"                          # still paused, nothing adopted
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.0.0" base-unchanged
pass
