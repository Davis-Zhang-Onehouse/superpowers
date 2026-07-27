#!/usr/bin/env bash
#
# dispatch-alive.sh — is this dispatched session alive? Answered from the RECORD, never reconstructed.
#
# The tmux session is `dt-<todo-id>`. A watcher that rebuilt the name from the todo-id alone (omitting
# the prefix) reported a perfectly healthy coordinator as GONE and terminated itself on the false alarm.
# Four separate identifier bugs in one day came from hand-deriving names; this exists so no caller has
# to. It also prints the session it checked, so a wrong answer is visible rather than silent.
#
# Usage:  dispatch-alive.sh <todo-id> [--quiet]
#         dispatch-alive.sh --base <base-instant> [--quiet]   (every worker of one effort, no pattern)
# Exit:   0 alive · 1 not alive · 2 no such record (NOT the same as dead)
set -uo pipefail
BOARD_DIR="${BOARD_DIR:-$HOME/.claude-dispatch-board}"
TMUX_BIN="${TMUX_BIN:-tmux}"
[ $# -ge 1 ] || { echo "usage: dispatch-alive.sh <todo-id>|--base <instant> [--quiet]" >&2; exit 2; }
quiet=0; base=""; id=""
while [ $# -gt 0 ]; do
  case "$1" in
    --quiet) quiet=1; shift;;
    --base)  base="${2:-}"; shift 2;;
    *)       id="$1"; shift;;
  esac
done

alive_one() { pgrep -f "remote-control $1" >/dev/null 2>&1 || "$TMUX_BIN" has-session -t "$1" >/dev/null 2>&1; }

# --base: enumerate every worker of ONE effort from the records. A liveness PATTERN is wrong in both
# directions — a narrow one silently excludes later milestone names, a broad one counts other efforts
# and the coordinator itself. Records know exactly who belongs to this base.
if [ -n "$base" ]; then
  n=0; up=0; lines=""
  for f in "$BOARD_DIR"/records/*.json; do
    [ -e "$f" ] || continue
    rb="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("base_instant","") or "")' "$f")"
    [ "$rb" = "$base" ] || [ "$(realpath -m -- "$rb" 2>/dev/null)" = "$(realpath -m -- "$base" 2>/dev/null)" ] || continue
    tid="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("todo_id",""))' "$f")"
    ts="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("tmux",""))' "$f")"
    n=$((n+1))
    if alive_one "$ts"; then up=$((up+1)); lines="$lines\n  alive      $tid"
    else lines="$lines\n  NOT alive  $tid  ($ts)"; fi
  done
  [ "$n" -gt 0 ] || { echo "no dispatch records for base: $base" >&2; exit 2; }
  if [ "$quiet" = 0 ]; then
    echo "ALIVE $up/$n for base $(basename "$base")"
    printf '%b\n' "${lines#\\n}"
  fi
  [ "$up" -eq "$n" ] && exit 0 || exit 1
fi

[ -n "$id" ] || { echo "usage: dispatch-alive.sh <todo-id>|--base <instant> [--quiet]" >&2; exit 2; }
rec="$BOARD_DIR/records/$id.json"
[ -f "$rec" ] || { echo "no dispatch record for '$id' — cannot judge liveness (this is NOT 'dead')" >&2; exit 2; }
sess="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("tmux",""))' "$rec")"
[ -n "$sess" ] || { echo "record for '$id' has no tmux session name" >&2; exit 2; }
if alive_one "$sess"; then
  [ "$quiet" = 1 ] || echo "alive: $sess"
  exit 0
fi
[ "$quiet" = 1 ] || echo "not alive: $sess (no matching process and no tmux session)"
exit 1
