# tests/sync/test_sync_manifest_versions.sh — S6 / coordinator D-136.
# Every fleet release commit on live sets "version": "<upstream>+fleet.<x>" in the manifests .version-bump.json names,
# and every upstream release bumps the same line, so each replayed release commit conflicted on every upstream tag and
# the 03:30 sync PAUSED (2026-09-26, v6.4.1 -> v6.4.2, only the version manifests). A conflict whose EVERY unmerged path
# is a version manifest and whose every hunk differs ONLY in the version value is resolved: upstream's version, the
# replayed commit's "+fleet.<x>" suffix. Anything else still pauses exactly as before.
# shellcheck shell=bash
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"

manifests_at() {   # manifests_at <repo> <version>: write the two manifests + .version-bump.json with <version>
  mkdir -p "$1/.claude-plugin" "$1/.hermes-plugin"
  printf '{\n  "name": "x",\n  "description": "d",\n  "version": "%s"\n}\n' "$2" > "$1/package.json"
  printf '{\n  "name": "x",\n  "version": "%s",\n  "author": "a"\n}\n' "$2" > "$1/.claude-plugin/plugin.json"
  printf 'name: x\nversion: %s\n' "$2" > "$1/.hermes-plugin/plugin.yaml"
  printf '{ "files": [ { "path": "package.json", "field": "version" }, { "path": ".claude-plugin/plugin.json", "field": "version" }, { "path": ".hermes-plugin/plugin.yaml", "field": "version" } ] }\n' > "$1/.version-bump.json"
}
up_release() {     # up_release <tag> <version> [extra sed on package.json]
  manifests_at "$UPSTREAM" "$2"
  [ -n "${3:-}" ] && sed -i "$3" "$UPSTREAM/package.json"
  g "$UPSTREAM" add -A; g "$UPSTREAM" commit -qm "Release $1"; g "$UPSTREAM" tag "$1"
}
fleet_release() {  # fleet_release <fleet version>: a fleet cut on live stamps <upstream core>+fleet.<x>
  local core; core="$(sed -n 's/.*"version": "\([^+"]*\).*/\1/p' "$FORK/package.json")"
  manifests_at "$FORK" "$core+fleet.$1"
  printf '%s\n' "$1" > "$FORK/FLEET_VERSION"
  g "$FORK" add -A; g "$FORK" commit -qm "fleet v$1"
}
version_of() { sed -n 's/.*"version": "\([^"]*\)".*/\1/p' "$1"; }
fresh() {          # a new sandbox each case
  rm -rf "$UPSTREAM" "$FORK" "$CTRL"
  make_upstream; up_release v1.0.1 1.0.1
  make_fork; g "$FORK" reset -q --hard v1.0.1; make_config; echo "BASE_TAG=v1.0.1" > "$CTRL/state"; . "$CTRL/config"
}

# 1. two fleet release commits, upstream bumps the version: resolved, not paused, and said so
fresh
fleet_release 0.1.0; fleet_release 0.2.0
up_release v1.1.0 1.1.0
run_sync
assert_nofile "$CTRL/STATUS"
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.1.0" base-advanced
assert_eq "$(version_of "$FORK/package.json")" "1.1.0+fleet.0.2.0" package-version
assert_eq "$(version_of "$FORK/.claude-plugin/plugin.json")" "1.1.0+fleet.0.2.0" plugin-version
assert_grep '^version: 1.1.0+fleet.0.2.0$' "$FORK/.hermes-plugin/plugin.yaml"
assert_grep '"author": "a"' "$FORK/.claude-plugin/plugin.json"
assert_grep '"result":"manifest-resolved"' "$CTRL/history.ndjson"
assert_grep '"conflicts":"[^"]*package.json' "$CTRL/history.ndjson"
g "$FORK" log --format=%s v1.1.0..live | grep -q '^fleet v0.1.0$' || { echo "FAIL: the release commits were not replayed"; exit 1; }

# 2. a manifest hunk that touches another field besides the version still PAUSES
fresh
fleet_release 0.1.0
g "$FORK" checkout -q live; sed -i 's/"description": "d"/"description": "ours"/' "$FORK/package.json"
g "$FORK" commit -qam "custom: description"
up_release v1.1.0 1.1.0 's/"description": "d"/"description": "theirs"/'
run_sync
assert_file "$CTRL/STATUS"
assert_grep '"result":"paused"' "$CTRL/history.ndjson"
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.0.1" base-still-old

# 3. a version-only manifest conflict together with a conflict in a non-manifest file still PAUSES
fresh
g "$FORK" checkout -q live
printf 'line1\nMY-EDIT\nline3\n' > "$FORK/skills/foo/SKILL.md"; manifests_at "$FORK" "1.0.1+fleet.0.1.0"
g "$FORK" add -A; g "$FORK" commit -qm "fleet v0.1.0 with a skill edit"
printf 'line1\nUPSTREAM-EDIT\nline3\n' > "$UPSTREAM/skills/foo/SKILL.md"
up_release v1.1.0 1.1.0
run_sync
assert_file "$CTRL/STATUS"
assert_grep 'skills/foo/SKILL.md' "$CTRL/STATUS"
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.0.1" base-still-old

# 4. RV-S6Y-1/6: after a manual fix, finish.sh settles EVERY later release commit's version conflict in ONE run
fresh
g "$FORK" checkout -q live
printf 'line1\nMY-EDIT\nline3\n' > "$FORK/skills/foo/SKILL.md"; g "$FORK" commit -qam "custom: edit foo line2"
fleet_release 0.1.0; fleet_release 0.2.0
printf 'line1\nUPSTREAM-EDIT\nline3\n' > "$UPSTREAM/skills/foo/SKILL.md"
up_release v1.1.0 1.1.0
run_sync
assert_file "$CTRL/STATUS"                                         # the skill edit is a real conflict
printf 'line1\nMY-EDIT\nline3\n' > "$WORKTREE/skills/foo/SKILL.md"; g "$WORKTREE" add skills/foo/SKILL.md
run_finish                                                          # one run, two release commits after the fix
assert_nofile "$CTRL/STATUS"
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.1.0" finish-base-advanced
assert_eq "$(version_of "$FORK/package.json")" "1.1.0+fleet.0.2.0" finish-package-version
assert_grep '"result":"manual+manifest-resolved"' "$CTRL/history.ndjson"

# 5. RV-S6Y-3: a recreated MERGE whose version line conflicts pauses (its "theirs" is the second parent)
fresh
g "$FORK" checkout -q live; fleet_release 1
g "$FORK" checkout -q -b side; fleet_release 2
g "$FORK" checkout -q live; fleet_release 3
g "$FORK" merge -q --no-ff side -m "merge side" >/dev/null 2>&1 || { manifests_at "$FORK" "1.0.1+fleet.3"; g "$FORK" add -A; g "$FORK" commit -qm "merge side (kept fleet.3)"; }
up_release v1.1.0 1.1.0
run_sync
assert_file "$CTRL/STATUS"
assert_grep 'auto-resolved before the pause' "$CTRL/history.ndjson"    # RV-S6Y-5: said in history, not only STATUS
pass
