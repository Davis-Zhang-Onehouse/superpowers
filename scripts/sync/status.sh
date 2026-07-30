#!/usr/bin/env bash
# Read-only health + history view for the superpowers fork-sync setup.
# Usage: status.sh            # status + last 10 syncs
#        status.sh -n 30      # status + last 30 syncs
#        status.sh --no-fetch # skip the upstream fetch (offline / faster)
set -uo pipefail
SPSYNC_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Default to the config beside this script. bootstrap.sh writes config into the
# same control dir it copies these scripts into, so an install scoped outside
# $HOME (e.g. under a shared-box home subdir) works when invoked by absolute
# path with no SPSYNC_CONFIG set — which is how the paused-rebase STATUS
# instructions tell you to run finish.sh.
: "${SPSYNC_CONFIG:=$SPSYNC_SCRIPT_DIR/config}"
. "$SPSYNC_CONFIG"
. "$SPSYNC_SCRIPT_DIR/lib.sh"
load_state

N=10; FETCH=1
while [ $# -gt 0 ]; do
  case "$1" in
    -n) N="${2:-10}"; shift 2 ;;
    --no-fetch) FETCH=0; shift ;;
    *) shift ;;
  esac
done

jget() { printf '%s' "$1" | sed -n "s/.*\"$2\":\"\([^\"]*\)\".*/\1/p"; }

echo "superpowers fork-sync — status"
echo "──────────────────────────────"

branch="$(g "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
[ "$branch" = "$LIVE_BRANCH" ] && bnote="ok" || bnote="EXPECTED $LIVE_BRANCH"
printf '%-14s %s (%s)\n' "Repo:" "$REPO" "$branch=$bnote"

actual="$(g "$REPO" describe --tags --abbrev=0 --match 'v[0-9]*.[0-9]*.[0-9]*' --exclude '*-*' "$LIVE_BRANCH" 2>/dev/null || echo '?')"
[ "${BASE_TAG:-}" = "$actual" ] && dnote="ok" || dnote="DRIFT — fix: printf 'BASE_TAG=$actual\\n' > $STATE_FILE"
printf '%-14s %s   (live actually on %s — %s)\n' "BASE_TAG:" "${BASE_TAG:-unset}" "$actual" "$dnote"

if [ "$FETCH" = 1 ]; then
  g "$REPO" fetch "$UPSTREAM_REMOTE" --tags --quiet 2>/dev/null || echo "  (warning: upstream fetch failed — showing cached tags)"
fi
latest="$(latest_tag 2>/dev/null || echo '?')"
if [ "$latest" = "$actual" ]; then
  printf '%-14s %s (up to date)\n' "Upstream:" "$latest"
else
  printf '%-14s %s   ← UPDATE AVAILABLE (run: %s)\n' "Upstream:" "$latest" "$SPSYNC_SCRIPT_DIR/sync.sh"
fi

ncommits="$(g "$REPO" rev-list --count "$actual..$LIVE_BRANCH" 2>/dev/null || echo '?')"
printf '%-14s %s on top of %s\n' "Your commits:" "$ncommits" "$actual"

if ! g "$REPO" diff --quiet 2>/dev/null || ! g "$REPO" diff --cached --quiet 2>/dev/null; then
  printf '%-14s %s\n' "Worktree:" "DIRTY (uncommitted changes — commit with apply.sh -m \"...\")"
else
  printf '%-14s %s\n' "Worktree:" "clean"
fi

if crontab -l 2>/dev/null | grep -q "$CONTROL_DIR/sync.sh"; then
  sched="$(crontab -l 2>/dev/null | grep "$CONTROL_DIR/sync.sh" | head -1 | awk '{print $1,$2,$3,$4,$5}')"
  printf '%-14s scheduled (%s)\n' "Cron:" "$sched"
else
  printf '%-14s %s\n' "Cron:" "NOT scheduled — re-run bootstrap.sh"
fi

cache="$HOME/.claude/plugins/cache/superpowers-dev/superpowers"
[ -d "$cache" ] && printf '%-14s %s\n' "Plugin cache:" "$(ls "$cache" 2>/dev/null | tr '\n' ' ')"

if [ -f "$STATUS_FILE" ]; then
  echo
  echo "⚠ PAUSED REBASE — action needed:"
  sed 's/^/   /' "$STATUS_FILE"
fi

echo
echo "Recent syncs (last $N):"
if [ -f "$HISTORY" ] && [ -s "$HISTORY" ]; then
  tail -n "$N" "$HISTORY" | while IFS= read -r l; do
    [ -n "$l" ] || continue
    ts="$(jget "$l" ts)"; res="$(jget "$l" result)"
    base="$(jget "$l" base)"; new="$(jget "$l" new)"; conf="$(jget "$l" conflicts)"
    arrow=""; [ -n "$new" ] && [ "$new" != "$base" ] && arrow=" → $new"
    cx=""; [ -n "$conf" ] && cx="  conflicts: $conf"
    printf '   %s  %-15s %s%s%s\n' "$ts" "$res" "$base" "$arrow" "$cx"
  done
else
  echo "   (none yet)"
fi

echo
echo "Snapshot timeline / rollback:  $SPSYNC_SCRIPT_DIR/rollback.sh list"
