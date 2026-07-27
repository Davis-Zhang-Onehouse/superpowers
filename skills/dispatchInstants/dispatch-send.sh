#!/usr/bin/env bash
#
# dispatch-send.sh — send a message to a dispatched worker and VERIFY it landed.
#
# `tmux send-keys` to a busy claude pane silently fails to submit often enough that
# "I sent it" is not evidence. This sends the text and Enter as SEPARATE keystrokes (a paste
# placeholder swallows a combined trailing Enter), then proves receipt from the pane in any of
# the three shapes it takes: echoed text, "[Pasted text #N]", or the queued-messages indicator.
#
# Usage:  dispatch-send.sh <todo-id> <message...>
# Exit:   0 = delivery verified   1 = not delivered / session dead   2 = unknown todo-id
# Env:    BOARD_DIR, TMUX_BIN, SEND_WAIT (seconds between send and re-read, default 2)
set -uo pipefail

BOARD_DIR="${BOARD_DIR:-$HOME/.claude-dispatch-board}"
TMUX_BIN="${TMUX_BIN:-tmux}"
WAIT="${SEND_WAIT:-2}"

[ $# -ge 2 ] || { echo "usage: dispatch-send.sh <todo-id> <message...>" >&2; exit 2; }
id="$1"; shift; msg="$*"

rec="$BOARD_DIR/records/$id.json"
[ -f "$rec" ] || { echo "no dispatch record for '$id' in $BOARD_DIR/records" >&2; exit 2; }
sess="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("tmux",""))' "$rec")"
[ -n "$sess" ] || { echo "record has no tmux session" >&2; exit 2; }

alive() { pgrep -f "remote-control $1" >/dev/null 2>&1 || "$TMUX_BIN" has-session -t "$1" >/dev/null 2>&1; }
alive "$sess" || { echo "session '$sess' is not alive — nothing to send to" >&2; exit 1; }

# Distinctive slice of the message to look for in the pane afterwards.
probe="$(printf '%s' "$msg" | head -c 24)"

# Receipt evidence, in the three shapes it actually takes:
#   - short input echoes into the pane          -> the probe text
#   - long input becomes a paste placeholder    -> "[Pasted text #N +M lines]" (text NEVER echoes)
#   - the worker is busy                        -> "Press up to edit queued messages"
received() {
  local pane; pane="$("$TMUX_BIN" capture-pane -p -t "$sess" 2>/dev/null | tail -80)"
  printf '%s' "$pane" | grep -Fq "$probe" && return 0
  printf '%s' "$pane" | grep -qE '\[Pasted text #[0-9]+|Press up to edit queued messages' && return 0
  return 1
}

attempt() {
  "$TMUX_BIN" send-keys -t "$sess" C-u >/dev/null 2>&1        # clear any half-typed input
  "$TMUX_BIN" send-keys -t "$sess" -l "$msg" >/dev/null 2>&1  # the text, literally
  sleep 1
  # Enter MUST be its own keystroke: when claude converts long input into a paste placeholder it
  # swallows a trailing Enter in the same send-keys, leaving the message sitting unsubmitted.
  "$TMUX_BIN" send-keys -t "$sess" Enter >/dev/null 2>&1
  sleep "$WAIT"
  received
}

if attempt; then echo "delivered to $sess: $probe…"; exit 0; fi
echo "first send not visible in pane — retrying once…" >&2
if attempt; then echo "delivered to $sess on retry: $probe…"; exit 0; fi

echo "COULD NOT VERIFY delivery to '$sess'. The worker did NOT receive this message." >&2
echo "Attach and check: tmux attach -t $sess" >&2
exit 1
