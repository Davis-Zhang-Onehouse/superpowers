#!/usr/bin/env bash
# `scripts/release-postflight.sh`, asserted against a fake box built under `mktemp -d` -- never the real
# release area or the real `*_root` directories.
#
# The property worth testing is the one the header of the script under test exists to prevent: the
# original incident had `fleet release-status`, run from a second root, print "current DEV / checkout ...
# / head unknown" for a deployment that was perfectly correct -- a false alarm caused by `fleet` reporting
# root-relative to whichever FLEET_HOME it was handed. This script answers the box-relative question
# instead, without ever calling `fleet`, so the properties that matter are: it correctly clears a healthy,
# fully-shared deployment (no false alarm, matching the incident); it correctly IGNORES a root that has
# its own, unrelated release area (also no false alarm, per the "Scoping the roots correctly" section of
# its own brief); and it correctly CATCHES a root that genuinely lags -- the failure mode the incident's
# `fleet`-based check could not have told apart from the false alarm.
#
# `broot_root/fleet-releases` is built as a live symlink alias of the release area, exactly like
# `davis2_root/fleet-releases -> davis_root/fleet-releases` on the real box -- and, because that makes
# `current` the SAME FILE by construction, it can never disagree with the canonical root, by design. The
# "second root still on the previous version" scenario is therefore modelled the way that failure actually
# arises: a root whose `fleet-releases` is its OWN directory (not a live alias), with a `current` pointed
# by hand at one of this release area's OLDER version directories -- a half-migrated root, not a
# hypothetical one.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SCRIPT="$REPO/scripts/release-postflight.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fails=0
note() { printf '  %s\n' "$*"; }
check() { # check <label> <expected> <actual>
  local label="$1" want="$2" got="$3"
  if [ "$want" = "$got" ]; then
    note "ok   $label"
  else
    note "FAIL $label"
    note "       wanted: [$want]"
    note "       got:    [$got]"
    fails=1
  fi
}

ROOTS="$TMP/roots"
VERSION="1.0.0"
OLD_VERSION="0.9.0"
R="$ROOTS/aroot_root/fleet-releases"
mkdir -p "$ROOTS/aroot_root/.claude" "$ROOTS/broot_root/.claude"

# Build one release directory with everything assertions 1, 4 and 5 read.
build_release() { # build_release <dir> <version>
  local dir="$1" ver="$2"
  mkdir -p "$dir/.hermes-plugin" "$dir/.claude-plugin" "$dir/.release/evidence"
  cat >"$dir/.version-bump.json" <<'JSON'
{
  "files": [
    { "path": "package.json", "field": "version" },
    { "path": ".hermes-plugin/plugin.yaml", "field": "version" },
    { "path": ".claude-plugin/marketplace.json", "field": "plugins.0.version" }
  ]
}
JSON
  printf '{"version": "6.3.0+fleet.%s"}\n' "$ver" >"$dir/package.json"
  printf 'version: 6.3.0+fleet.%s\n' "$ver" >"$dir/.hermes-plugin/plugin.yaml"
  printf '{"plugins": [{"version": "6.3.0+fleet.%s"}]}\n' "$ver" >"$dir/.claude-plugin/marketplace.json"
  printf 'suite\tverdict\tevidence\tnote\nverdict\tGREEN\t-\tstub run\n' >"$dir/.release/evidence/VERDICT.tsv"
}
build_release "$R/fleet-v$VERSION" "$VERSION"
build_release "$R/fleet-v$OLD_VERSION" "$OLD_VERSION"
ln -s "fleet-v$VERSION" "$R/current"

# broot_root: the correct, live alias -- exactly davis2_root/fleet-releases -> davis_root/fleet-releases.
ln -s "$R" "$ROOTS/broot_root/fleet-releases"

settings_for() { # settings_for <settings.json path> <marketplace path>
  printf '{"extraKnownMarketplaces": {"superpowers-dev": {"source": {"path": "%s"}}}}\n' "$2" >"$1"
}
settings_for "$ROOTS/aroot_root/.claude/settings.json" "$R/current"
settings_for "$ROOTS/broot_root/.claude/settings.json" "$R/current"

run() { # run [version] -- defaults to $VERSION; never lets FLEET_RELEASES fall through to a real root
  FLEET_RELEASES="$R" RELEASE_POSTFLIGHT_ROOTS_PARENT="$ROOTS" bash "$SCRIPT" "${1:-$VERSION}"
}

# --- the happy path: exit 0, no MISMATCH, and the second root is actually checked (not just skipped) -----
out="$(run 2>&1)"
rc=$?
check "a fully-correct, fully-shared deployment exits 0" "0" "$rc"
case "$out" in
  *MISMATCH*)
    note "FAIL the happy path printed a MISMATCH: $out"
    fails=1
    ;;
  *) note "ok   the happy path printed no MISMATCH" ;;
esac
printf '%s' "$out" | grep -q "broot_root" \
  || {
    note "FAIL the second root (broot_root) was never mentioned -- was it actually checked?"
    fails=1
  }

# --- usage: a missing version argument is refused, not guessed at ----------------------------------------
bash "$SCRIPT" >/dev/null 2>&1
check "a missing version argument exits 2" "2" "$?"

# --- environment: FLEET_RELEASES unset is refused, from a directory with no .fleet-root above it ---------
out="$(cd "$TMP" && env -u FLEET_RELEASES RELEASE_POSTFLIGHT_ROOTS_PARENT="$ROOTS" bash "$SCRIPT" "$VERSION" 2>&1)"
rc=$?
check "FLEET_RELEASES unset exits 2" "2" "$rc"

# --- assertion 1: `current` resolves to the wrong version -------------------------------------------------
out="$(run "$OLD_VERSION" 2>&1)"
rc=$?
check "a 'current' that does not match the requested version exits 1" "1" "$rc"
case "$out" in
  *"MISMATCH: $R/current"*"fleet-v$OLD_VERSION"*) note "ok   assertion 1 names both the actual and wanted target" ;;
  *)
    note "FAIL assertion 1 did not name both sides: $out"
    fails=1
    ;;
esac

# --- scoping: an unrelated root with its OWN release area must NOT be flagged (no false alarm) -----------
mkdir -p "$ROOTS/unrelated_root/fleet-releases/fleet-v0.1.0"
ln -s fleet-v0.1.0 "$ROOTS/unrelated_root/fleet-releases/current"
out="$(run 2>&1)"
rc=$?
check "an unrelated root's own, unrelated release does not fail the run" "0" "$rc"
case "$out" in
  *unrelated_root*)
    note "FAIL the unrelated root was flagged -- exactly the false alarm the scoping exists to avoid"
    fails=1
    ;;
  *) note "ok   the unrelated root was correctly excluded from scope" ;;
esac
rm -rf "$ROOTS/unrelated_root"

# --- assertion 2: THE scenario this script exists to catch -----------------------------------------------
# A second root whose OWN `current` still points at the previous version. Modelled as a half-migrated root
# (see header): its own `fleet-releases` directory, with `current` pointed by hand into this release area's
# OLD version directory.
mkdir -p "$ROOTS/croot_root/fleet-releases"
ln -s "$R/fleet-v$OLD_VERSION" "$ROOTS/croot_root/fleet-releases/current"
out="$(run 2>&1)"
rc=$?
check "a second root stuck on the previous version exits 1" "1" "$rc"
case "$out" in
  *"MISMATCH: $ROOTS/croot_root/fleet-releases/current"*"fleet-v$OLD_VERSION"*"fleet-v$VERSION"*)
    note "ok   assertion 2 names both sides: the stale root's actual target and the wanted (deployed) one"
    ;;
  *)
    note "FAIL assertion 2 did not name both sides: $out"
    fails=1
    ;;
esac
rm -rf "$ROOTS/croot_root"

# --- assertion 3: the marketplace path in .claude/settings.json is stale ---------------------------------
# This one drifts for a genuinely different reason than assertion 2: it is a plain string in a config file
# that nothing keeps in sync automatically, unlike a shared `current` symlink.
cp "$ROOTS/broot_root/.claude/settings.json" "$TMP/settings.json.bak"
settings_for "$ROOTS/broot_root/.claude/settings.json" "$R/fleet-v$OLD_VERSION"
out="$(run 2>&1)"
rc=$?
check "a stale marketplace path exits 1" "1" "$rc"
case "$out" in
  *"MISMATCH: $ROOTS/broot_root/.claude/settings.json"*"fleet-v$OLD_VERSION"*"fleet-v$VERSION"*)
    note "ok   assertion 3 names both sides: the stale marketplace path and the wanted target"
    ;;
  *)
    note "FAIL assertion 3 did not name both sides: $out"
    fails=1
    ;;
esac
cp "$TMP/settings.json.bak" "$ROOTS/broot_root/.claude/settings.json"

# --- assertion 4a: a plain top-level field that .version-bump.json names, but was not actually bumped ----
# This is also the only check anywhere in the pipeline that reads .hermes-plugin/plugin.yaml -- Task 1's
# blind spot -- so it doubles as a YAML-manifest regression test.
cp "$R/fleet-v$VERSION/.hermes-plugin/plugin.yaml" "$TMP/plugin.yaml.bak"
printf 'version: 6.3.0+fleet.%s\n' "$OLD_VERSION" >"$R/fleet-v$VERSION/.hermes-plugin/plugin.yaml"
out="$(run 2>&1)"
rc=$?
check "an unbumped .hermes-plugin/plugin.yaml exits 1" "1" "$rc"
case "$out" in
  *"MISMATCH: .hermes-plugin/plugin.yaml"*)
    note "ok   assertion 4 catches a file .version-bump.json names that was not actually bumped (YAML)"
    ;;
  *)
    note "FAIL assertion 4 did not catch the unbumped YAML file: $out"
    fails=1
    ;;
esac
cp "$TMP/plugin.yaml.bak" "$R/fleet-v$VERSION/.hermes-plugin/plugin.yaml"

# --- assertion 4b: the one entry with a NESTED dotted field (plugins.0.version) ---------------------------
cp "$R/fleet-v$VERSION/.claude-plugin/marketplace.json" "$TMP/marketplace.json.bak"
printf '{"plugins": [{"version": "6.3.0+fleet.%s"}]}\n' "$OLD_VERSION" \
  >"$R/fleet-v$VERSION/.claude-plugin/marketplace.json"
out="$(run 2>&1)"
rc=$?
check "an unbumped nested dotted field (plugins.0.version) exits 1" "1" "$rc"
case "$out" in
  *"MISMATCH: .claude-plugin/marketplace.json#plugins.0.version"*)
    note "ok   assertion 4 reads the nested dotted field, not just a flat one"
    ;;
  *)
    note "FAIL the nested dotted field was not read or checked: $out"
    fails=1
    ;;
esac
cp "$TMP/marketplace.json.bak" "$R/fleet-v$VERSION/.claude-plugin/marketplace.json"

# --- assertion 5: a RED verdict fails the run; EXEMPT passes it same as GREEN -----------------------------
# Via `$R/current`, not the resolved `fleet-v$VERSION` path directly: the script reports this path through
# `current` (see its own MISMATCH line), so the expected string here has to match that, not the target.
VERDICT="$R/current/.release/evidence/VERDICT.tsv"
cp "$VERDICT" "$TMP/verdict.bak"

printf 'suite\tverdict\tevidence\tnote\nverdict\tRED\t-\tstub run\n' >"$VERDICT"
out="$(run 2>&1)"
rc=$?
check "a RED verdict exits 1" "1" "$rc"
case "$out" in
  *"MISMATCH: $VERDICT verdict is RED"*) note "ok   assertion 5 is named on a RED verdict" ;;
  *)
    note "FAIL assertion 5 was not named: $out"
    fails=1
    ;;
esac
cp "$TMP/verdict.bak" "$VERDICT"

printf 'suite\tverdict\tevidence\tnote\nverdict\tEXEMPT\t-\tstub run\n' >"$VERDICT"
out="$(run 2>&1)"
rc=$?
check "an EXEMPT verdict exits 0, same as GREEN" "0" "$rc"
cp "$TMP/verdict.bak" "$VERDICT"

# --- read-only: this script must never mutate anything under the roots it inspects ------------------------
before="$(find "$ROOTS" -printf '%p %s %T@ %l\n' 2>/dev/null | sort)"
run >/dev/null 2>&1
after="$(find "$ROOTS" -printf '%p %s %T@ %l\n' 2>/dev/null | sort)"
check "the run adds, removes, mutates and re-points nothing under the roots" "$before" "$after"

if [ "$fails" = 0 ]; then
  echo "PASS: release-postflight.sh clears a fully-shared, fully-correct deployment with no false alarm," \
       "correctly excludes an unrelated root's own release area, catches a second root whose current still" \
       "points at the previous version (naming both the actual and wanted target), catches a stale" \
       "marketplace path, catches an unbumped file for both a flat YAML field and a nested dotted JSON" \
       "field (.hermes-plugin/plugin.yaml and plugins.0.version), classifies RED vs EXEMPT/GREEN verdicts," \
       "refuses a missing version or an unset FLEET_RELEASES with exit 2, and mutates nothing it inspects"
  exit 0
fi
echo FAIL
exit 1
