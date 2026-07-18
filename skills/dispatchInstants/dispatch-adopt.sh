#!/usr/bin/env bash
#
# dispatch-adopt.sh — bring an ALREADY-EXISTING effort instant under compliant
# pdispatch tracking, WITHOUT recreating it. The complement to dispatch-todo.sh:
#
#   dispatch-todo.sh  = fork a FRESH child instant + duplicate a golden + launch.
#   dispatch-adopt.sh = adopt an EXISTING instant (resumed / migrated / hand-made):
#       claim its ws slot lease  ->  ensure an interactive tmux `claude` is running
#       for it (adopt a live one in place, or relaunch+RESUME its session if dead)
#       ->  write the immutable dispatch record on the base so `pdispatch board`
#       renders it (▶ running / 🅿 parked / ✅ complete / ✖ abort, all derived).
#
# Why it exists: `pdispatch todo` refuses to reuse an enrolled slot as golden and
# always bootstraps a new child — so a resumed session (e.g. after a migration or a
# manual launch) had no compliant path into the pool + board. This is that path.
#
# Idempotent & non-destructive: a live matching tmux session is adopted IN PLACE
# (record + lease refreshed, session untouched) unless --force-relaunch. Only a
# dead/absent session is (re)launched. The instant's files and code are never touched.
#
# Usage:
#   dispatch-adopt.sh --base <base-instant> --instant <existing-child-instant> --slot <ws> \
#       [--resume <session-uuid>] [--resume-cwd <dir>] [--title "..."] \
#       [--seed <file|-|text>] [--todo <id>] [--tmux <name>] \
#       [--no-launch] [--force-relaunch]
#
#   --base           base/coordinator instant whose dispatch/ board tracks this TODO (needs HANDOFF.md)
#   --instant        the EXISTING child instant folder (needs HANDOFF.md + CHARTER.md)
#   --slot           ws slot the instant's code lives in (must be enrolled; will be leased)
#   --resume <uuid>  resume THIS claude session on (re)launch — preserves all prior work
#   --resume-cwd     cwd to launch claude from (default: the slot path). MUST equal the
#                    session's original project cwd or --resume can't find the session.
#   --title          board title (default: derived from the instant's instantName)
#   --seed <s>       if NOT resuming, seed for a fresh session: a file, '-' (stdin), or inline text
#   --todo <id>      TODO_ID (record filename + default tmux suffix). Default: instant's instantName.
#   --tmux <name>    tmux session name. Default: dt-<todo>.
#   --no-launch      write record + claim lease only; never touch tmux.
#   --force-relaunch even if the tmux session is alive, kill it and relaunch (resume) it.
#
set -euo pipefail

SELF="$(readlink -f "$0" 2>/dev/null || echo "$0")"; HERE="$(cd "$(dirname "$SELF")" && pwd)"
WSPOOL_SH="${WSPOOL_SH:-$HERE/wspool.sh}"

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_bold=$'\033[1m'; c_rst=$'\033[0m'
err()  { printf '%sERROR:%s %s\n' "$c_red" "$c_rst" "$*" >&2; }
warn() { printf '%sWARN:%s %s\n'  "$c_yel" "$c_rst" "$*" >&2; }
info() { printf '%s\n' "$*"; }
step() { printf '%s==>%s %s\n' "$c_bold" "$c_rst" "$*"; }

BASE="" INSTANT="" SLOT="" RESUME="" RESUME_CWD="" TITLE="" SEED="" TODO_ID="" TMUX_SESSION=""
NO_LAUNCH=0 FORCE_RELAUNCH=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --base)           BASE="$2"; shift 2;;
    --instant)        INSTANT="$2"; shift 2;;
    --slot)           SLOT="$2"; shift 2;;
    --resume)         RESUME="$2"; shift 2;;
    --resume-cwd)     RESUME_CWD="$2"; shift 2;;
    --title)          TITLE="$2"; shift 2;;
    --seed)           SEED="$2"; shift 2;;
    --todo)           TODO_ID="$2"; shift 2;;
    --tmux)           TMUX_SESSION="$2"; shift 2;;
    --no-launch)      NO_LAUNCH=1; shift;;
    --force-relaunch) FORCE_RELAUNCH=1; shift;;
    -h|--help)        sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) err "unknown arg: $1"; exit 2;;
  esac
done

[ -n "$BASE" ]    || { err "--base required"; exit 2; }
[ -n "$INSTANT" ] || { err "--instant required"; exit 2; }
[ -n "$SLOT" ]    || { err "--slot required"; exit 2; }
BASE="$(realpath -m -- "$BASE")"; INSTANT="$(realpath -m -- "$INSTANT")"
[ -f "$BASE/HANDOFF.md" ]    || { err "--base is not a maintain-workspace instant (needs HANDOFF.md): $BASE"; exit 2; }
[ -f "$INSTANT/HANDOFF.md" ] && [ -f "$INSTANT/CHARTER.md" ] \
  || { err "--instant is not a maintain-workspace instant (needs HANDOFF.md + CHARTER.md): $INSTANT"; exit 2; }
[ -x "$WSPOOL_SH" ] || { err "wspool.sh not found/executable at $WSPOOL_SH"; exit 2; }

# resolve the slot's enrolled path
WS="$(POOL_DIR="${POOL_DIR:-}" "$WSPOOL_SH" status "$(basename "$SLOT")" 2>/dev/null | sed -n 's/.*PATH=\([^ ]*\).*/\1/p' | head -1 || true)"
[ -n "$WS" ] || { err "slot '$SLOT' is not enrolled — run: pdispatch pool add <path>"; exit 2; }

# derive names from the instant grammar: <base>-<curr>-<state>-<opType>-<instantName>
INAME="$(basename "$INSTANT" | cut -d- -f5-)"
[ -n "$TODO_ID" ] || TODO_ID="$INAME"
[ -n "$TMUX_SESSION" ] || TMUX_SESSION="dt-${TODO_ID}"
[ -n "$RESUME_CWD" ] || RESUME_CWD="$WS"
[ -n "$TITLE" ] || TITLE="$INAME"

# Dispatch records live in the machine-global board store (D-11), NOT under the base.
# BOARD_DIR is env-overridable (default ~/.claude-dispatch-board) for hermetic tests.
BOARD_DIR="${BOARD_DIR:-$HOME/.claude-dispatch-board}"
RECORDS_DIR="$BOARD_DIR/records"
RECORD="$RECORDS_DIR/${TODO_ID}.json"

step "adopting instant $(basename "$INSTANT")"
info "  base    : $BASE"
info "  slot    : $(basename "$SLOT") -> $WS"
info "  tmux    : $TMUX_SESSION"
info "  resume  : ${RESUME:-<none (fresh seed)>}"

# ---- 1. claim (or re-affirm) the slot lease --------------------------------
# If already leased to THIS todo, refresh it; if leased to someone else, refuse.
existing="$(POOL_DIR="${POOL_DIR:-}" "$WSPOOL_SH" status "$(basename "$SLOT")" 2>/dev/null | sed -n 's/.*TODO_ID=\([^ ]*\).*/\1/p' | head -1 || true)"
if [ -n "$existing" ] && [ "$existing" != "$TODO_ID" ]; then
  err "slot $(basename "$SLOT") is already LEASED to a different TODO ($existing) — release it first"; exit 3
fi
POOL_DIR="${POOL_DIR:-}" "$WSPOOL_SH" release "$(basename "$SLOT")" >/dev/null 2>&1 || true
set +e
WSCLAIMED="$(POOL_DIR="${POOL_DIR:-}" "$WSPOOL_SH" claim --todo "$TODO_ID" --tmux "$TMUX_SESSION" \
             --base "$BASE" --child "$INSTANT" --slot "$(basename "$SLOT")")"
rc=$?
set -e
[ "$rc" -eq 0 ] || { err "wspool claim failed (rc=$rc)"; exit "$rc"; }
info "  leased $(basename "$SLOT") -> $WSCLAIMED"

# ---- 2. ensure an interactive tmux claude is running -----------------------
launch_cmd() {
  if [ -n "$RESUME" ]; then
    printf 'claude --permission-mode auto --remote-control %q --resume %q' "$TMUX_SESSION" "$RESUME"
  else
    local seedtext="$SEED"
    [ "$SEED" = "-" ] && seedtext="$(cat)"
    if [ -n "$seedtext" ] && [ -f "$seedtext" ]; then seedtext="$(cat "$seedtext")"; fi
    [ -n "$seedtext" ] || seedtext="You are a dispatched worker. Your effort instant is ${INSTANT} and your code is in ${WS} (cwd). Read HANDOFF.md then CHARTER.md and continue. Keep the instant maintained per maintain-workspace; park operator questions under a '## Parked decision' block; transition the instant folder state when done."
    printf 'claude --permission-mode auto --remote-control %q %q' "$TMUX_SESSION" "$seedtext"
  fi
}

if [ "$NO_LAUNCH" -eq 1 ]; then
  warn "  --no-launch: not touching tmux"
elif tmux has-session -t "$TMUX_SESSION" 2>/dev/null && [ "$FORCE_RELAUNCH" -eq 0 ]; then
  info "  tmux session '$TMUX_SESSION' already alive — adopted in place (not relaunched)"
else
  if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    warn "  --force-relaunch: killing live session $TMUX_SESSION"
    tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true
  fi
  step "launching interactive tmux session $TMUX_SESSION (cwd $RESUME_CWD)"
  tmux new-session -d -s "$TMUX_SESSION" -c "$RESUME_CWD"
  tmux send-keys -t "$TMUX_SESSION" "$(launch_cmd)" Enter
  info "  session live. Attach with:  tmux attach -t $TMUX_SESSION"
fi

# ---- 3. write the immutable dispatch record into the global board store -----
step "recording dispatch (global board store)"
mkdir -p "$RECORDS_DIR"
DISPATCHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
{
  printf '{\n'
  printf '  "todo_id": "%s",\n' "$TODO_ID"
  printf '  "title": %s,\n' "$(printf '%s' "$TITLE" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')"
  printf '  "child_instant": "%s",\n' "$INSTANT"
  printf '  "ws": "%s",\n' "$WS"
  printf '  "slot": "%s",\n' "$(basename "$SLOT")"
  printf '  "golden": "%s",\n' "(adopted — existing instant, no golden duplication)"
  printf '  "tmux": "%s",\n' "$TMUX_SESSION"
  printf '  "base_instant": "%s",\n' "$BASE"
  printf '  "resume_session": "%s",\n' "${RESUME:-}"
  printf '  "adopted": true,\n'
  printf '  "dispatched_at": "%s"\n' "$DISPATCHED_AT"
  printf '}\n'
} > "$RECORD"
info "  wrote $RECORD"

echo
step "ADOPTED ${c_grn}${TODO_ID}${c_rst}"
info "  instant : $INSTANT"
info "  record  : $RECORD"
info "  board   : pdispatch board"
