#!/usr/bin/env bash
#
# dispatch-launch.sh — launch a worker from its RECORDED seed, correctly quoted.
#
# The `--no-launch` review gate used to end with a human copy-pasting (or worse, retyping)
# the printed launch line — where seeds containing | ; & < > ( ) get split and the worker
# starts on a mangled prompt. This replays the recorded seed with proper quoting instead, so
# no launch line is ever hand-built.
#
# Usage:  dispatch-launch.sh <todo-id> [--force] [--seed-file <f>]
# Exit:   0 = launched + verified   1 = already running / could not verify   2 = bad input
# Env:    BOARD_DIR, TMUX_BIN, LAUNCH_WAIT (default 3)
set -uo pipefail

BOARD_DIR="${BOARD_DIR:-$HOME/.claude-dispatch-board}"
TMUX_BIN="${TMUX_BIN:-tmux}"
WAIT="${LAUNCH_WAIT:-3}"
FORCE=0; SEED_FILE=""

[ $# -ge 1 ] || { echo "usage: dispatch-launch.sh <todo-id> [--force] [--seed-file <f>]" >&2; exit 2; }
id="$1"; shift
while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1; shift;;
    --seed-file) SEED_FILE="${2:-}"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

rec="$BOARD_DIR/records/$id.json"
[ -f "$rec" ] || { echo "no dispatch record for '$id'" >&2; exit 2; }
get(){ python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2],"") or "")' "$rec" "$1"; }
sess="$(get tmux)"; ws="$(get ws)"
[ -n "$SEED_FILE" ] || SEED_FILE="$(get seed_file)"
[ -n "$sess" ] && [ -n "$ws" ] || { echo "record missing tmux/ws" >&2; exit 2; }
[ -n "$SEED_FILE" ] && [ -f "$SEED_FILE" ] || { echo "no seed file (record has no seed_file; pass --seed-file)" >&2; exit 2; }

alive() { pgrep -f "remote-control $1" >/dev/null 2>&1 || "$TMUX_BIN" has-session -t "$1" >/dev/null 2>&1; }
if alive "$sess" && [ "$FORCE" != 1 ]; then
  echo "session '$sess' is already running — refusing to double-launch (use --force)" >&2
  exit 1
fi

SEED="$(cat "$SEED_FILE")"
"$TMUX_BIN" new-session -d -s "$sess" -c "$ws" >/dev/null 2>&1 || true
# %q keeps the whole seed ONE argument no matter what metacharacters it holds.
cmd="claude --permission-mode auto --remote-control $(printf '%q' "$sess") $(printf '%q' "$SEED")"
"$TMUX_BIN" send-keys -t "$sess" "$cmd" Enter >/dev/null 2>&1
sleep "$WAIT"

if "$TMUX_BIN" capture-pane -p -t "$sess" 2>/dev/null | tail -40 | grep -q "claude\|remote-control"; then
  echo "launched $id in $sess (ws=$ws)"
  echo "  attach: tmux attach -t $sess"
  exit 0
fi
echo "launched but COULD NOT VERIFY the pane started claude — attach and check: tmux attach -t $sess" >&2
exit 1
