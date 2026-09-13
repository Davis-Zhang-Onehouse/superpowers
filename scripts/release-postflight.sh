#!/usr/bin/env bash
#
# Prove a deployment reached every root that shares this release area.
#
# Usage:  scripts/release-postflight.sh <version>
#
# Invokes `fleet` NOT AT ALL, on purpose. `release-status` reports relative to the FLEET_HOME it is
# handed, and davis2_root/fleet-releases is a SYMLINK to davis_root/fleet-releases -- so running it from
# the second root printed "current DEV / checkout ... / head unknown" for a deployment that was perfectly
# correct, and cost a paragraph of reasoning to discount. The state was right; the presentation is
# root-relative while the question is box-relative. `readlink -f` answers the box-relative question
# directly, so this script never asks `fleet` anything -- it would inherit the very artifact that caused
# the confusion.
#
# Read-only: this proves a deployment, it does not perform one. It must never move `current`, mutate a
# release, or delete anything.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

V="${1:-}"
if [ -z "$V" ]; then
  echo "usage: $(basename "$0") <version>" >&2
  exit 2
fi

# Clear our own positional arg before sourcing fleet-env.sh: it takes an optional `$1` of its own (a
# directory, to set FLEET_INSTANTS), and scripts/release-gate.sh's header documents the exact confusing
# warning a leftover `$1` produces here ("'1.0.1' is not a directory; FLEET_INSTANTS left as unset").
set --

# shellcheck source=scripts/fleet-env.sh
. "$REPO/scripts/fleet-env.sh"

R="${FLEET_RELEASES:-}"
if [ -z "$R" ]; then
  echo "$(basename "$0"): FLEET_RELEASES is unset — source scripts/fleet-env.sh from inside a fleet root" >&2
  exit 2
fi

command -v python3 >/dev/null 2>&1 || {
  echo "$(basename "$0"): python3 is not on PATH — needed to read the JSON/YAML manifest fields" >&2
  exit 2
}

# Test seam: which /home/ubuntu-shaped directory to scan for `*_root` siblings. Production always scans
# the real box; a test builds a fake box under `mktemp -d` and points this here instead, so it can never
# reach the real roots.
ROOTS_PARENT="${RELEASE_POSTFLIGHT_ROOTS_PARENT:-/home/ubuntu}"

# The marketplace this release deploys into. Fixed by the release pipeline's own design (see
# docs/superpowers/plans/2026-08-02-fleet-release-pipeline.md), not a property of any one root, so it is
# a constant here rather than something derived per root.
MARKETPLACE_KEY="superpowers-dev"

FAILED=0
ok() { echo "OK: $*"; }
mismatch() { echo "MISMATCH: $*" >&2; FAILED=1; }

# Read a dotted field path (e.g. "plugins.0.version") out of a JSON or YAML file. JSON and YAML both
# because the files declared in .version-bump.json are a mix of both -- most are JSON, but
# .hermes-plugin/plugin.yaml is not, and that file is exactly the one this script exists to cover (a
# separate task in this plan found it invisible to the release scope classifier for ten releases).
read_field() { # read_field <file> <dotted-field>
  python3 - "$1" "$2" <<'PY'
import sys, json

path, field = sys.argv[1], sys.argv[2]
if path.endswith((".yaml", ".yml")):
    import yaml

    with open(path) as fh:
        data = yaml.safe_load(fh)
else:
    with open(path) as fh:
        data = json.load(fh)

cur = data
for part in field.split("."):
    cur = cur[int(part)] if isinstance(cur, list) else cur[part]
print(cur)
PY
}

# --- assertion 1: current points at fleet-v<version> ----------------------------------------------------
CUR="$R/current"
CUR_TARGET="$(readlink -f "$CUR")"
WANT_BASENAME="fleet-v$V"
case "$CUR_TARGET" in
  */"$WANT_BASENAME")
    ok "$CUR -> $CUR_TARGET (ends in $WANT_BASENAME)"
    ;;
  *)
    mismatch "$CUR -> $CUR_TARGET, wanted a path ending in $WANT_BASENAME"
    ;;
esac

# --- derive the in-scope roots: only the ones that actually share THIS release area ----------------------
# Other `*_root` directories on the box have their own release area and their own `current`; flagging
# them would be a false alarm. This is derived, not hardcoded, precisely so it proves the symlink topology
# (davis2_root/fleet-releases -> davis_root/fleet-releases) instead of assuming it.
#
# Two ways a root can share this area, checked in order:
#   1. `fleet-releases` itself is a live alias of $R -- the normal mechanism, confirmed on this box
#      (davis2_root/fleet-releases -> davis_root/fleet-releases, same inode both ways).
#   2. `fleet-releases` is not (or not yet) an alias, but its `current` nonetheless resolves INSIDE
#      this release area's tree -- a half-migrated root whose `current` was pointed by hand at one of
#      this area's `fleet-v*` directories. Skipping such a root because the enclosing directory is not
#      itself a symlink is exactly how a stale root goes unnoticed, so its `current` is checked too.
in_scope() { # in_scope <root>
  local fl="$1/fleet-releases" ct
  [ -e "$fl" ] || return 1
  [ "$(readlink -f "$fl")" = "$(readlink -f "$R")" ] && return 0
  ct="$(readlink -f "$fl/current" 2>/dev/null)" || return 1
  [ -n "$ct" ] && [ "$(dirname "$ct")" = "$(readlink -f "$R")" ]
}

IN_SCOPE_ROOTS=()
if [ -d "$ROOTS_PARENT" ]; then
  for root in "$ROOTS_PARENT"/*_root; do
    [ -d "$root" ] || continue
    in_scope "$root" && IN_SCOPE_ROOTS+=("$root")
  done
fi
ok "${#IN_SCOPE_ROOTS[@]} root(s) under $ROOTS_PARENT share this release area: ${IN_SCOPE_ROOTS[*]:-<none>}"

# --- assertions 2 & 3: every in-scope root agrees, both by the release symlink and by the settings ------
for root in "${IN_SCOPE_ROOTS[@]}"; do
  root_cur="$root/fleet-releases/current"
  root_cur_target="$(readlink -f "$root_cur")"
  if [ "$root_cur_target" = "$CUR_TARGET" ]; then
    ok "$root_cur -> $root_cur_target matches $CUR_TARGET"
  else
    mismatch "$root_cur -> $root_cur_target, wanted $CUR_TARGET"
  fi

  settings="$root/.claude/settings.json"
  mp=""
  if [ -f "$settings" ]; then
    mp="$(read_field "$settings" "extraKnownMarketplaces.$MARKETPLACE_KEY.source.path" 2>/dev/null)" || mp=""
  fi
  if [ -z "$mp" ]; then
    mismatch "$settings has no extraKnownMarketplaces.$MARKETPLACE_KEY.source.path, wanted a path resolving to $CUR_TARGET"
  else
    mp_target="$(readlink -f "$mp")"
    if [ "$mp_target" = "$CUR_TARGET" ]; then
      ok "$settings marketplace path $mp -> $mp_target matches $CUR_TARGET"
    else
      mismatch "$settings marketplace path $mp -> $mp_target, wanted $CUR_TARGET"
    fi
  fi
done

# --- assertion 4: every file named in .version-bump.json carries +fleet.<version> -----------------------
# The only check in this whole pipeline that covers .hermes-plugin/plugin.yaml. The file list is read out
# of the deployed .version-bump.json itself, never hardcoded, so a file added or removed there is covered
# automatically.
VB="$CUR/.version-bump.json"
WANT_SUFFIX="+fleet.$V"
if [ ! -f "$VB" ]; then
  mismatch "$VB does not exist"
else
  while IFS=$'\t' read -r relpath field; do
    [ -n "$relpath" ] || continue
    fpath="$CUR/$relpath"
    if [ ! -f "$fpath" ]; then
      mismatch "$fpath (field $field, from $VB) does not exist"
      continue
    fi
    val="$(read_field "$fpath" "$field" 2>/dev/null)" || val=""
    case "$val" in
      *"$WANT_SUFFIX")
        ok "$relpath#$field = $val (carries $WANT_SUFFIX)"
        ;;
      *)
        mismatch "$relpath#$field = ${val:-<unreadable>}, wanted a value ending in $WANT_SUFFIX"
        ;;
    esac
  done < <(python3 - "$VB" <<'PY'
import json
import sys

with open(sys.argv[1]) as fh:
    data = json.load(fh)
for f in data.get("files", []):
    print(f"{f['path']}\t{f['field']}")
PY
  )
fi

# --- assertion 5: the deployed release's own evidence says GREEN or EXEMPT ------------------------------
VERDICT_FILE="$CUR/.release/evidence/VERDICT.tsv"
if [ ! -f "$VERDICT_FILE" ]; then
  mismatch "$VERDICT_FILE does not exist"
else
  verdict="$(awk -F'\t' '$1=="verdict"{print $2; exit}' "$VERDICT_FILE")"
  case "$verdict" in
    GREEN | EXEMPT)
      ok "$VERDICT_FILE verdict is $verdict"
      ;;
    *)
      mismatch "$VERDICT_FILE verdict is ${verdict:-<missing>}, wanted GREEN or EXEMPT"
      ;;
  esac
fi

[ "$FAILED" = 0 ]
exit $?
