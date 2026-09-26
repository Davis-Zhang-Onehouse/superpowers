# tests/sync/test_rerere_manifest.sh — RV-27 (sync-adopt 2026-09-26).
# rerere recorded every manifest resolution resolve_manifest_versions made (399 in the v6.4.2 adoption), so a later run
# that met the same conflict again — a stale-base re-run — had rerere replay and stage it before the resolver was ever
# asked, and the run read `rerere-resolved`. The resolver must stay the only thing that settles a version-only conflict:
# no such resolution survives a run, and a re-run is resolved by the resolver again.
# shellcheck shell=bash
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"

manifests_at() {
  mkdir -p "$1/.claude-plugin"
  printf '{\n  "name": "x",\n  "version": "%s"\n}\n' "$2" > "$1/package.json"
  printf '{\n  "name": "x",\n  "version": "%s",\n  "author": "a"\n}\n' "$2" > "$1/.claude-plugin/plugin.json"
  printf '{ "files": [ { "path": "package.json", "field": "version" }, { "path": ".claude-plugin/plugin.json", "field": "version" } ] }\n' > "$1/.version-bump.json"
}
up_release() { manifests_at "$UPSTREAM" "$2"; g "$UPSTREAM" add -A; g "$UPSTREAM" commit -qm "Release $1"; g "$UPSTREAM" tag "$1"; }
fleet_release() {
  manifests_at "$FORK" "1.0.1+fleet.$1"
  g "$FORK" add -A; g "$FORK" commit -qm "fleet v$1"
}
recorded() { find "$FORK/.git/rr-cache" -mindepth 2 -name postimage 2>/dev/null | wc -l | tr -d ' '; }
last_result() { tail -1 "$CTRL/history.ndjson" | sed -n 's/.*"result":"\([^"]*\)".*/\1/p'; }

make_upstream; up_release v1.0.1 1.0.1
make_fork; g "$FORK" reset -q --hard v1.0.1; make_config; echo "BASE_TAG=v1.0.1" > "$CTRL/state"; . "$CTRL/config"
fleet_release 0.1.0
up_release v1.1.0 1.1.0
run_sync
assert_nofile "$CTRL/STATUS"
assert_eq "$(last_result)" "manifest-resolved" first-run-resolver
assert_eq "$(recorded)" "0" no-manifest-resolution-kept

# A stale-base re-run meets the identical conflict: the resolver settles it again, rerere does not.
g "$FORK" reset -q --hard v1.0.1
fleet_release 0.1.0
echo "BASE_TAG=v1.0.1" > "$CTRL/state"
run_sync
assert_nofile "$CTRL/STATUS"
assert_eq "$(last_result)" "manifest-resolved" rerun-resolver-not-rerere
assert_eq "$(recorded)" "0" still-none-kept

# R2-1: a pause on a stop that mixes a version-only manifest conflict with a genuine one. The pause-time purge must not
# delete an rr-cache entry the paused MERGE_RR still names (git's rerere segfaults on the next continue), and the
# operator's genuine resolution must be recorded when finish.sh continues.
rm -rf "$UPSTREAM" "$FORK" "$CTRL"
make_upstream; up_release v1.0.1 1.0.1
make_fork; g "$FORK" reset -q --hard v1.0.1; make_config; echo "BASE_TAG=v1.0.1" > "$CTRL/state"; . "$CTRL/config"
fleet_release 0.1.0
manifests_at "$FORK" "1.0.1+fleet.0.2.0"; printf 'line1\nOURS\nline3\n' > "$FORK/skills/foo/SKILL.md"
g "$FORK" add -A; g "$FORK" commit -qm "fleet v0.2.0 with a skill edit"
manifests_at "$UPSTREAM" 1.1.0; printf 'line1\nTHEIRS\nline3\n' > "$UPSTREAM/skills/foo/SKILL.md"
g "$UPSTREAM" add -A; g "$UPSTREAM" commit -qm "Release v1.1.0"; g "$UPSTREAM" tag v1.1.0
run_sync
assert_file "$CTRL/STATUS"
manifests_at "$WORKTREE" "1.1.0+fleet.0.2.0"; printf 'line1\nMERGED\nline3\n' > "$WORKTREE/skills/foo/SKILL.md"
g "$WORKTREE" add -A
run_finish || { echo "FAIL @ finish-after-mixed-pause: finish.sh failed"; exit 1; }
assert_nofile "$CTRL/STATUS"
assert_grep '^line1$' "$FORK/skills/foo/SKILL.md"; assert_grep '^MERGED$' "$FORK/skills/foo/SKILL.md"
assert_eq "$(recorded)" "1" genuine-resolution-recorded-manifest-dropped
pass
