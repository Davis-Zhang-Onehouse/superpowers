# tests/sync/harness.sh — source this from each test. Builds an isolated sandbox.
# shellcheck shell=bash
set -euo pipefail

SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
UPSTREAM="$SANDBOX/upstream"
FORK="$SANDBOX/fork"
CTRL="$SANDBOX/ctrl"
SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../scripts/sync" && pwd)"

g() { git -C "$1" "${@:2}"; }   # g <repo> <git args...>

make_upstream() {
  git init -q "$UPSTREAM"
  g "$UPSTREAM" config user.email t@t; g "$UPSTREAM" config user.name t
  mkdir -p "$UPSTREAM/skills/foo"
  printf 'line1\nline2\nline3\n' > "$UPSTREAM/skills/foo/SKILL.md"
  g "$UPSTREAM" add -A; g "$UPSTREAM" commit -qm v1
  g "$UPSTREAM" tag v1.0.0
}

# add_release <tag> <new-foo-line2>   (changes line2 of foo to create rebase work/conflict)
add_release() {
  printf 'line1\n%s\nline3\n' "$2" > "$UPSTREAM/skills/foo/SKILL.md"
  g "$UPSTREAM" add -A; g "$UPSTREAM" commit -qm "$1"
  g "$UPSTREAM" tag "$1"
}

make_fork() {
  git clone -q "$UPSTREAM" "$FORK"
  g "$FORK" remote rename origin upstream
  g "$FORK" config user.email me@me; g "$FORK" config user.name me
  g "$FORK" checkout -q -b live v1.0.0
}

# add a custom commit on live. $1=relpath $2=content
fork_custom() {
  mkdir -p "$FORK/$(dirname "$1")"
  printf '%s\n' "$2" > "$FORK/$1"
  g "$FORK" add -A; g "$FORK" commit -qm "custom: $1"
}

make_config() {
  mkdir -p "$CTRL"
  g "$FORK" config rerere.enabled true
  cat > "$CTRL/config" <<EOF
REPO="$FORK"
LIVE_BRANCH="live"
UPSTREAM_REMOTE="upstream"
CONTROL_DIR="$CTRL"
WORKTREE="$CTRL/rebase-wt"
STATE_FILE="$CTRL/state"
STATUS_FILE="$CTRL/STATUS"
PENDING_FILE="$CTRL/PENDING"
HISTORY="$CTRL/history.ndjson"
RETENTION_DAYS=90
SPSYNC_REFRESH_CMD=""
EOF
  echo "BASE_TAG=v1.0.0" > "$CTRL/state"
}

run_sync()    { SPSYNC_CONFIG="$CTRL/config" bash "$SCRIPTS/sync.sh"; }
run_finish()  { SPSYNC_CONFIG="$CTRL/config" bash "$SCRIPTS/finish.sh"; }
run_rollback(){ SPSYNC_CONFIG="$CTRL/config" bash "$SCRIPTS/rollback.sh" "$@"; }

assert_eq()   { [ "$1" = "$2" ] || { echo "FAIL @ ${3:-}: expected [$2] got [$1]"; exit 1; }; }
assert_file() { [ -f "$1" ]   || { echo "FAIL: missing file $1"; exit 1; }; }
assert_nofile(){ [ ! -f "$1" ]|| { echo "FAIL: unexpected file $1"; exit 1; }; }
assert_grep() { grep -q "$1" "$2" || { echo "FAIL: '$1' not in $2"; exit 1; }; }
pass()        { echo "PASS: ${0##*/}"; }
