#!/usr/bin/env bash
# refresh-control.sh — bring the sync control dir's CODE up to the scripts beside this file (S6 / coordinator D-136).
#
# bootstrap.sh copies lib.sh, sync.sh, finish.sh, rollback.sh, apply.sh and status.sh into the control dir once; a fleet
# release never touched them again, so a fix to the sync (D-136's version-manifest auto-resolve) would never reach the
# 03:30 cron. The release deploy runs this from the DEPLOYED export, so the control dir follows `current`:
#
#   bash "$FLEET_RELEASES/current/scripts/sync/refresh-control.sh" --ctrl <control dir> [--check | --dry-run]
#
# Only those six code files are written. config, state, STATUS, PENDING, history.ndjson, cron.log and the rebase
# worktree are never read or written, so a PAUSED sync stays exactly as it is (its next finish.sh runs the new code).
# --check exits 1 when any file differs (read-only); --dry-run prints what would change and writes nothing.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
FILES=(lib.sh sync.sh finish.sh rollback.sh apply.sh status.sh)
CTRL="" MODE=write
while [ $# -gt 0 ]; do
  case "$1" in
    --ctrl) CTRL="${2:-}"; shift 2 ;;
    --check) MODE=check; shift ;;
    --dry-run) MODE=dry-run; shift ;;
    *) echo "refresh-control: unknown argument '$1' (--ctrl <dir> [--check|--dry-run])" >&2; exit 2 ;;
  esac
done
[ -n "$CTRL" ] || { echo "refresh-control: --ctrl <control dir> is required" >&2; exit 2; }
[ -d "$CTRL" ] && [ -f "$CTRL/config" ] || { echo "refresh-control: $CTRL is not a sync control dir (no config)" >&2; exit 2; }
differ=0
for f in "${FILES[@]}"; do
  [ -f "$SRC/$f" ] || { echo "refresh-control: $SRC/$f is missing" >&2; exit 2; }
  if cmp -s "$SRC/$f" "$CTRL/$f"; then echo "same     $f"; continue; fi
  differ=1
  case "$MODE" in
    check)   echo "DIFFERS  $f" ;;
    dry-run) echo "would-write $f" ;;
    write)   tmp="$(mktemp "$CTRL/.$f.XXXXXX")"; cp "$SRC/$f" "$tmp"; chmod 755 "$tmp"; mv -f "$tmp" "$CTRL/$f"; echo "wrote    $f" ;;
  esac
done
[ "$MODE" = check ] && [ "$differ" = 1 ] && exit 1
exit 0
