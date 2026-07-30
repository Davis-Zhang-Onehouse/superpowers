# tests/sync/test_config_beside_script.sh
# The paused-rebase STATUS text tells you to run "$CONTROL_DIR/finish.sh" with no
# SPSYNC_CONFIG set. That copy-paste must work for a control dir living anywhere,
# not just $HOME/.superpowers-sync — so each script defaults its config to the one
# beside itself, the way bootstrap.sh lays them out.
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config
fork_custom "skills/mine/SKILL.md" "my custom skill"
add_release v1.1.0 "line2-upstream-changed"

# Mirror bootstrap.sh: scripts installed alongside the config in the control dir.
cp "$SCRIPTS"/{lib.sh,sync.sh,finish.sh,rollback.sh,apply.sh,status.sh} "$CTRL/"

# HOME points somewhere with no .superpowers-sync at all — the old $HOME-based
# default would fail here with "config: No such file or directory".
FAKE_HOME="$SANDBOX/elsewhere"; mkdir -p "$FAKE_HOME"
env -u SPSYNC_CONFIG HOME="$FAKE_HOME" bash "$CTRL/sync.sh"

. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.1.0" base-updated-without-spsync-config
assert_grep '"result":"clean"' "$CTRL/history.ndjson"

# An explicit SPSYNC_CONFIG still wins over the beside-the-script default.
OTHER="$SANDBOX/other-config"
sed "s#^RETENTION_DAYS=.*#RETENTION_DAYS=7#" "$CTRL/config" > "$OTHER"
assert_eq "$(env HOME="$FAKE_HOME" SPSYNC_CONFIG="$OTHER" bash "$CTRL/status.sh" --no-fetch >/dev/null 2>&1; echo $?)" "0" explicit-config-honored
pass
