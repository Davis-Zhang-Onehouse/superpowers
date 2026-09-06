#!/usr/bin/env bash
# Move a box-wide `~/.fleet` into the root that owns it, and mark the roots.
#
#     bash scripts/fleet-migrate-root.sh --dry-run          # print the plan, write nothing
#     bash scripts/fleet-migrate-root.sh                    # do it
#
# Idempotent: a second run is a no-op and says so. Reversible: the move leaves a compatibility symlink
# at the old path, so anything that still names `~/.fleet` keeps resolving while it is fixed.
#
# ⚠️ THE SYMLINK IS A NET AND IT IS ALSO A HAZARD, so the order below is not negotiable. While `~/.fleet`
# still resolves, a shell carrying a stale `FLEET_HOME=~/.fleet` export with no marker above its cwd
# reaches this root's store through tier 3 — the exact interference this whole change removes, wearing
# the compatibility layer as a disguise. `scripts/fleet-env.sh` must therefore already have stopped
# exporting a literal `FLEET_HOME` (it has, as of the `consumers:` commit) BEFORE this runs. The check
# below refuses if it has not.
#
# ⚠️ The tmux SOCKET changes name (`fleet` -> `fleet-<name>`). Sessions already running on the old server
# are NOT migrated: they keep running and stay reachable with `tmux -L fleet attach`. Stated because a
# coordinator watching `dt-*` sessions disappear from the new server should read that as the rename and
# not as dead workers.
set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
ROOT="${FLEET_MIGRATE_ROOT:-$(cd "$REPO/.." && pwd)}"          # the root that owns the store
NAME="${FLEET_MIGRATE_NAME:-$(basename "$ROOT" | sed 's/_root$//')}"
LEGACY="${FLEET_MIGRATE_LEGACY:-$HOME/.fleet}"
DRY=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    *) echo "fleet-migrate-root.sh: unknown argument '$arg' (only --dry-run is declared)" >&2; exit 2 ;;
  esac
done

say()  { printf '%s\n' "$*"; }
step() { printf '  %s\n' "$*"; }
die()  { printf 'REFUSED: %s\n' "$*" >&2; exit 4; }

say "root      $ROOT"
say "name      $NAME"
say "legacy    $LEGACY"
say "target    $ROOT/.fleet"
say ""

# --- refusals, all before anything is written --------------------------------------------------------

[ -d "$ROOT" ] || die "$ROOT is not a directory"

# A held lease means a worker is live in a slot this store leases. Moving the store under it would leave
# the lease unreachable and the worker unaccounted for.
if [ -d "$LEGACY/pool/leases" ]; then
  held="$(find "$LEGACY/pool/leases" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')"
  [ "$held" = 0 ] || die "$held lease(s) are held in $LEGACY/pool/leases. Migrating under a live worker would leave its lease unreachable. Wait for them to finish, or release them, then re-run."
fi

# The hazard named in the header. If `fleet-env.sh` still exports a literal FLEET_HOME, the symlink this
# script creates becomes a route back to the shared store rather than a net under a fixed one.
if grep -qE '^\s*export FLEET_HOME=.*(\$HOME/\.fleet|/home/[^/]+/\.fleet)' "$REPO/scripts/fleet-env.sh"; then
  die "scripts/fleet-env.sh still exports a literal \$HOME/.fleet. Fix that first, or the compatibility symlink becomes a route back to the shared store instead of a net under a fixed one."
fi

# --- the plan ----------------------------------------------------------------------------------------

records=0; enrolled=0
[ -d "$LEGACY/records" ]       && records="$(find "$LEGACY/records" -name '*.json' | wc -l | tr -d ' ')"
[ -d "$LEGACY/pool/enrolled" ] && enrolled="$(find "$LEGACY/pool/enrolled" -name '*.json' | wc -l | tr -d ' ')"

say "PLAN"
if [ -L "$LEGACY" ]; then
  step "1. $LEGACY is ALREADY a symlink to $(readlink -f "$LEGACY") — nothing to move"
elif [ -d "$ROOT/.fleet" ] && [ ! -d "$LEGACY" ]; then
  step "1. the store is already at $ROOT/.fleet and $LEGACY is gone — nothing to move"
elif [ -d "$LEGACY" ]; then
  step "1. mv $LEGACY -> $ROOT/.fleet   ($records record(s), $enrolled enrolled slot(s))"
  step "   ln -s $ROOT/.fleet $LEGACY   (compatibility net; remove once nothing names the old path)"
else
  step "1. no store at $LEGACY and none at $ROOT/.fleet — nothing to move"
fi
if [ -f "$ROOT/.fleet-root" ]; then
  step "2. $ROOT/.fleet-root exists: $(cat "$ROOT/.fleet-root")"
else
  step "2. write $ROOT/.fleet-root  {\"name\": \"$NAME\"}"
fi
step "3. socket becomes fleet-$NAME (sessions on the old 'fleet' server keep running; tmux -L fleet attach)"
say ""

if [ "$DRY" = 1 ]; then say "--dry-run: nothing was written."; exit 0; fi

# --- do it -------------------------------------------------------------------------------------------

if [ ! -L "$LEGACY" ] && [ -d "$LEGACY" ]; then
  [ -e "$ROOT/.fleet" ] && die "$ROOT/.fleet already exists and $LEGACY is a real directory. Two stores, and this script will not guess which is authoritative. Merge or remove one by hand."
  mv "$LEGACY" "$ROOT/.fleet" || die "mv failed"
  ln -s "$ROOT/.fleet" "$LEGACY" || die "the store MOVED but the symlink failed; anything naming $LEGACY is now broken. Create it by hand: ln -s $ROOT/.fleet $LEGACY"
  say "moved: $LEGACY -> $ROOT/.fleet (symlink left behind)"
else
  say "store: nothing to move"
fi

if [ ! -f "$ROOT/.fleet-root" ]; then
  printf '{"name": "%s"}\n' "$NAME" > "$ROOT/.fleet-root" || die "could not write $ROOT/.fleet-root"
  say "marked: $ROOT/.fleet-root"
else
  say "marker: already present"
fi

# --- verify, by asking the product rather than by assuming ------------------------------------------

say ""
say "VERIFY (from $ROOT, with no FLEET_* exported)"
out="$(cd "$ROOT" && env -u FLEET_HOME -u FLEET_INSTANTS -u FLEET_TMUX_SOCKET -u FLEET_ROOT \
        "$REPO/bin/fleet" board --porcelain 2>&1)"
rc=$?
printf '%s\n' "$out" | grep '^root ' | sed 's/^/  /'
step "board rc=$rc"
[ "$rc" = 0 ] || die "the migrated root does not resolve. The store is at $ROOT/.fleet and the marker is written; investigate before dispatching anything."

after_records=0
[ -d "$ROOT/.fleet/records" ] && after_records="$(find "$ROOT/.fleet/records" -name '*.json' | wc -l | tr -d ' ')"
step "records before=$records after=$after_records"
[ "$records" = 0 ] || [ "$records" = "$after_records" ] || die "record count changed during the move ($records -> $after_records)"

say ""
say "DONE. Next: fix anything that still names $LEGACY, then remove the symlink and re-run the gate."
