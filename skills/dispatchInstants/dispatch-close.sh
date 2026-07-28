#!/usr/bin/env bash
#
# dispatch-close.sh — the missing counterpart to dispatch-launch.
#
# `dispatch-launch` creates a session and stamps launched_at. Nothing ever wrote the closing half,
# so finished sessions leaked: on 2026-07-28 four were alive with no work left, two of them for nine
# days past the end of their effort, and two live processes held ~/ws3 as cwd simultaneously because
# the slot had been re-leased under one of them. Teardown was a chore nobody owned; now it is a verb.
#
# What it refuses, and why each refusal exists:
#   · not finished        — closing a working worker is not cleanup
#   · pane is mid-turn    — the model is producing something right now
#   · unsubmitted input   — the box holds text that was typed and never sent; destroying the pane
#                           destroys the instruction. One such queued authorization was found live.
# Every refusal names the flag that overrides it.
#
# Usage:  dispatch-close.sh <todo-id|unique-prefix> [--force] [--by manual|harvest|ttl] [--quiet]
# Exit:   0 = closed (or already closed)   1 = refused   2 = bad input / no such record
# Env:    BOARD_DIR, POOL_DIR, TMUX_BIN, KILL_BIN, and the probes in lib/dispatch-lib.sh
set -uo pipefail
SELF="$(readlink -f "$0" 2>/dev/null || echo "$0")"
HERE="$(cd "$(dirname "$SELF")" && pwd)"
# shellcheck source=lib/dispatch-lib.sh
. "$HERE/lib/dispatch-lib.sh"

BOARD_DIR="${BOARD_DIR:-$HOME/.claude-dispatch-board}"
RECORDS="$BOARD_DIR/records"
POOL_DIR="${POOL_DIR:-$HOME/.claude-ws-pool}"

FORCE=0; BY="manual"; QUIET=0; WANT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1; shift;;
    --by)    BY="${2:-manual}"; shift 2;;
    --quiet) QUIET=1; shift;;
    -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    -*) echo "unknown arg: $1" >&2; exit 2;;
    *)  [ -z "$WANT" ] && WANT="$1" || { echo "unexpected extra arg: $1" >&2; exit 2; }; shift;;
  esac
done
say() { [ "$QUIET" = 1 ] || printf '%s\n' "$*"; }

[ -n "$WANT" ] || { echo "usage: dispatch-close.sh <todo-id> [--force] [--by manual|harvest|ttl]" >&2; exit 2; }
[ -d "$RECORDS" ] || { echo "no records dir: $RECORDS" >&2; exit 2; }

id="$(dl_resolve_id "$RECORDS" "$WANT")"; rc=$?
case "$rc" in
  1) echo "no dispatch record matches '$WANT' in $RECORDS" >&2; exit 2;;
  2) { echo "'$WANT' is AMBIGUOUS — refusing rather than picking one:"
       printf '%s\n' "$id" | sed 's/^/  /'
       echo "  give more of the id."; } >&2; exit 2;;
esac

rec="$RECORDS/$id.json"
sess="$(dl_field "$rec" tmux)"
slot="$(dl_field "$rec" slot)"
ws="$(dl_field "$rec" ws)"
child="$(dl_field "$rec" child_instant)"
closed="$(dl_field "$rec" closed_at)"

# --- already closed ---------------------------------------------------------
if [ -n "$closed" ] && ! dl_alive "$sess"; then
  say "$id: already closed at $closed (by $(dl_field "$rec" closed_by)) — nothing to do"
  exit 0
fi

# --- state guard ------------------------------------------------------------
if ! dl_is_finished "$rec" && [ "$FORCE" != 1 ]; then
  {
    echo "REFUSED: $id is not finished — no harvested_at, and its folder is not -complete-/-abort-."
    echo "  Closing a worker that is still running is not cleanup. Override with --force."
  } >&2
  exit 1
fi

# --- pane guards + capture --------------------------------------------------
pane=""
if dl_alive "$sess"; then
  pane="$("$TMUX_BIN" capture-pane -p -t "$sess" 2>/dev/null || true)"

  if dl_pane_busy "$pane" && [ "$FORCE" != 1 ]; then
    {
      echo "REFUSED: $id is mid-turn (the pane shows 'esc to interrupt') — it is working right now."
      echo "  Wait for it, or override with --force."
    } >&2
    exit 1
  fi

  queued="$(dl_pane_unsubmitted "$pane" || true)"
  if [ -n "$queued" ] && [ "$FORCE" != 1 ]; then
    {
      echo "REFUSED: $id has UNSUBMITTED text in its input box — teardown would destroy it:"
      echo "    $queued"
      echo "  Someone typed that and it was never sent. Submit it, clear it, or override with --force."
    } >&2
    exit 1
  fi

  # Capture BEFORE killing: the pane is the one artifact teardown destroys, and a decision made
  # without it (what was this worker last told? what did it last say?) cannot be revisited.
  idir="$(dl_instant_dir "$child" 2>/dev/null || true)"
  if [ -n "$idir" ] && [ -d "$idir" ]; then
    cap="$idir/evidence/session-close"
    mkdir -p "$cap"
    { echo "# pane of $sess captured by dispatch-close at $(dl_now) (by=$BY)"; printf '%s\n' "$pane"; } \
      > "$cap/$id-$(date -u +%Y%m%dT%H%M%SZ).txt"
    say "  captured the pane to ${cap#"$(dirname "$idir")/"}/"
  fi

  "$TMUX_BIN" kill-session -t "$sess" >/dev/null 2>&1
  say "  killed session $sess"
fi

# --- stamp the record -------------------------------------------------------
dl_set_fields "$rec" closed_at "$(dl_now)" closed_by "$BY"

# --- release the lease, but ONLY if it is ours ------------------------------
# The pool is machine-global. Freeing a slot whose meta names a different todo hands another
# effort's workspace away while it is still using it.
if [ -n "$slot" ] && [ -f "$POOL_DIR/leases/$slot/meta" ]; then
  owner="$(sed -n 's/^TODO_ID=//p' "$POOL_DIR/leases/$slot/meta" | head -1)"
  if [ "$owner" = "$id" ]; then
    rm -rf "${POOL_DIR:?}/leases/$slot"
    say "  released slot $slot"
  else
    say "  left slot $slot alone — its lease names '$owner', not this todo"
  fi
fi

# --- disarm the auto-retry monitor aimed at that pid ------------------------
# A finished session keeping a live claude-auto-retry monitor is a keystroke injector pointed at a
# stale worker: on a rate-limit banner the monitor types "Continue where you left off." and Enter.
# With text already queued in the box, that submits the concatenation — inside a tree that may since
# have been re-leased to somebody else.
if [ -n "$sess" ]; then
  tpid="$(dl_session_probe | awk -F'\t' -v s="$sess" '$3==s {print $1; exit}')"
  if [ -n "$tpid" ]; then
    while IFS=$'\t' read -r mpid target; do
      [ "$target" = "$tpid" ] || continue
      "$KILL_BIN" "$mpid" >/dev/null 2>&1
      say "  disarmed auto-retry monitor $mpid (was aimed at pid $tpid)"
    done < <(dl_monitors)
  fi
fi

# --- state the recovery route AT the moment of destruction ------------------
# Teardown was long treated as irreversible, and that framing pushed a decision that cost a fix
# path. It is not: the pane is gone, the transcript is not.
slug="$(printf '%s' "${ws:-$PWD}" | sed 's#/#-#g')"
say "closed $id (by=$BY)"
say "  recoverable — the pane is gone, the history is not:"
say "    ls ~/.claude/projects/$slug/*.jsonl     then     claude --resume <session-id>"
exit 0
