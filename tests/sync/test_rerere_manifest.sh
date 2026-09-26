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
pass
