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
# Exit:   0 alive · 1 not alive · 2 no such record (NOT the same as dead)
set -uo pipefail
BOARD_DIR="${BOARD_DIR:-$HOME/.claude-dispatch-board}"
TMUX_BIN="${TMUX_BIN:-tmux}"
[ $# -ge 1 ] || { echo "usage: dispatch-alive.sh <todo-id> [--quiet]" >&2; exit 2; }
id="$1"; quiet=0; [ "${2:-}" = "--quiet" ] && quiet=1
rec="$BOARD_DIR/records/$id.json"
[ -f "$rec" ] || { echo "no dispatch record for '$id' — cannot judge liveness (this is NOT 'dead')" >&2; exit 2; }
sess="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("tmux",""))' "$rec")"
[ -n "$sess" ] || { echo "record for '$id' has no tmux session name" >&2; exit 2; }
if pgrep -f "remote-control $sess" >/dev/null 2>&1 || "$TMUX_BIN" has-session -t "$sess" >/dev/null 2>&1; then
  [ "$quiet" = 1 ] || echo "alive: $sess"
  exit 0
fi
[ "$quiet" = 1 ] || echo "not alive: $sess (no matching process and no tmux session)"
exit 1
