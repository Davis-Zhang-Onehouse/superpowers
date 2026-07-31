#!/usr/bin/env bash
#
# dispatch-sessions.sh — enumerate live claude SESSIONS, then ask the board who claims them.
#
# This is `health --orphans` inverted, and the inversion is the point. --orphans walks dispatch
# RECORDS and asks "do you still have a session?", so a session with no record cannot appear in it
# at all — which is how a `claude --resume` under GNU screen sat idle for 8 days unseen. Starting
# from processes and asking the board "does a record claim you?" is the only direction that can
# report what nobody wrote down.
#
#   ACTIVE     a record claims it and the work is not finished        -> never touched
#   FINISHED   harvested, or its instant folder is -complete-/-abort- -> reapable once past the TTL
#   UNCLAIMED  no dispatch record claims this process                 -> REPORTED, never reaped
#
# UNCLAIMED is deliberately never reaped: a tool that can kill a session it does not understand is
# a tool nobody will leave armed, and some of those sessions are people's.
#
# It ESCALATES (exit 1) when a FINISHED session is past its TTL — which is safe only because the
# condition CLEARS: `--reap` in the same tick removes it. An alarm that cannot be cleared may not
# escalate; this one can, so it must.
#
# Usage:  dispatch-sessions.sh [--reap] [--base <base-instant>] [--json]
# Exit:   0 = nothing reapable   1 = a FINISHED session is past its TTL   2 = bad input
# Env:    BOARD_DIR, SESSION_TTL_MIN (default 360), plus the probes in lib/dispatch-lib.sh
set -uo pipefail
SELF="$(readlink -f "$0" 2>/dev/null || echo "$0")"
HERE="$(cd "$(dirname "$SELF")" && pwd)"
# shellcheck source=lib/dispatch-lib.sh
. "$HERE/lib/dispatch-lib.sh"

BOARD_DIR="${BOARD_DIR:-$HOME/.claude-dispatch-board}"
RECORDS="$BOARD_DIR/records"
TTL="${SESSION_TTL_MIN:-360}"

REAP=0; JSON=0; ONLY_BASE=""; PIDS_ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --reap) REAP=1; shift;;
    --json) JSON=1; shift;;
    # Bare pid lists, for callers that need the classification but not the report. claude-watchdog
    # uses --finished-pids to stop re-arming an auto-retry monitor on a dispatch that is over.
    --finished-pids)  PIDS_ONLY="FINISHED"; shift;;
    --unclaimed-pids) PIDS_ONLY="UNCLAIMED"; shift;;
    --base) ONLY_BASE="${2:-}"; shift 2;;
    -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
[ -d "$RECORDS" ] || { echo "no records dir: $RECORDS" >&2; exit 2; }

# Which record claims this tmux session? Answered by reading the recorded name, never by rebuilding
# "dt-<id>" from the id — every hand-derived session name in this toolkit has eventually been wrong.
record_for() { # <session name> -> record path, or ""
  local s="$1" f
  [ -n "$s" ] || return 0
  for f in "$RECORDS"/*.json; do
    [ -e "$f" ] || continue
    [ "$(dl_field "$f" tmux)" = "$s" ] && { printf '%s' "$f"; return 0; }
  done
  return 0
}

# Minutes since a worker finished: its harvest stamp if it has one, else when its folder was last
# touched. Reported as -1 when unknowable, and an unknowable age never counts as "past the TTL" —
# inferring a duration we cannot measure is how "new" got shipped as a measurement once already.
finished_age_min() { # <record.json>
  local rec="$1" h idir
  h="$(dl_field "$rec" harvested_at)"
  if [ -n "$h" ]; then
    python3 - "$h" <<'PY' 2>/dev/null || echo -1
import sys, datetime
try:
    t = datetime.datetime.strptime(sys.argv[1], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    print(int((datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() // 60))
except Exception:
    print(-1)
PY
    return
  fi
  idir="$(dl_instant_dir "$(dl_field "$rec" child_instant)" 2>/dev/null || true)"
  if [ -n "$idir" ] && [ -d "$idir" ]; then
    echo $(( ( $(date +%s) - $(stat -c %Y "$idir" 2>/dev/null || echo 0) ) / 60 ))
  else
    echo -1
  fi
}

rows=(); reapable=(); n_seen=0; n_active=0; n_finished=0; n_unclaimed=0

while IFS=$'\t' read -r pid cwd sess; do
  [ -n "${pid:-}" ] || continue
  n_seen=$((n_seen+1))

  # The probe is a snapshot taken before anything in this run acted. For a session we can verify
  # cheaply, verify: otherwise a session reaped a moment ago would still be listed as live and the
  # alarm would never clear.
  if [ -n "$sess" ] && ! dl_alive "$sess"; then continue; fi

  rec="$(record_for "$sess")"
  if [ -z "$rec" ]; then
    n_unclaimed=$((n_unclaimed+1))
    rows+=("UNCLAIMED|$pid|${sess:--}|-|-|$cwd")
    continue
  fi

  id="$(dl_field "$rec" todo_id)"; [ -n "$id" ] || id="$(basename "$rec" .json)"
  rbase="$(dl_field "$rec" base_instant)"
  if [ -n "$ONLY_BASE" ] && [ "$rbase" != "$ONLY_BASE" ] \
     && [ "$(realpath -m -- "$rbase" 2>/dev/null)" != "$(realpath -m -- "$ONLY_BASE" 2>/dev/null)" ]; then
    continue
  fi

  if dl_is_finished "$rec"; then
    age="$(finished_age_min "$rec")"
    n_finished=$((n_finished+1))
    rows+=("FINISHED|$pid|$sess|$id|${age}m|$cwd")
    if [ "$age" -ge 0 ] && [ "$age" -ge "$TTL" ]; then reapable+=("$id"); fi
  else
    n_active=$((n_active+1))
    rows+=("ACTIVE|$pid|$sess|$id|-|$cwd")
  fi
done < <(dl_session_probe)

if [ -n "$PIDS_ONLY" ]; then
  for r in "${rows[@]:-}"; do
    IFS='|' read -r c p _ _ _ _ <<<"$r"
    [ "$c" = "$PIDS_ONLY" ] && printf '%s\n' "$p"
  done
  exit 0
fi

if [ "$JSON" = 1 ]; then
  printf '%s\n' "${rows[@]:-}" | python3 -c '
import sys, json
out=[]
for ln in sys.stdin.read().splitlines():
    if not ln.strip(): continue
    p=(ln.split("|",5)+[""]*6)[:6]
    out.append(dict(zip(["class","pid","tmux","todo_id","finished_age","cwd"],p)))
print(json.dumps(out, indent=2, ensure_ascii=False))'
else
  # stdout is pure data rows; everything else goes to stderr so a script can parse this.
  if [ "${#rows[@]}" -gt 0 ]; then
    printf '%-10s %-8s %-46s %-30s %-7s %s\n' CLASS PID SESSION TODO AGE CWD
    for r in "${rows[@]}"; do
      IFS='|' read -r c p s t a w <<<"$r"
      printf '%-10s %-8s %-46s %-30s %-7s %s\n' "$c" "$p" "$s" "$t" "$a" "$w"
    done
  fi
  echo "examined $n_seen live claude session(s): $n_active ACTIVE · $n_finished FINISHED · $n_unclaimed UNCLAIMED" >&2
  # --base scopes the rows a RECORD can be matched to. An UNCLAIMED session has no record and so no
  # base, and silently dropping it would rebuild the blind spot this command exists to remove — so
  # they stay listed, and the scope of what you are looking at is stated rather than assumed.
  if [ -n "$ONLY_BASE" ] && [ "$n_unclaimed" -gt 0 ]; then
    echo "  (--base scopes CLAIMED sessions only; the $n_unclaimed UNCLAIMED row(s) are machine-wide" >&2
    echo "   and may belong to another effort or to a person — listed, never reaped)" >&2
  fi
fi

if [ "$REAP" = 1 ] && [ "${#reapable[@]}" -gt 0 ]; then
  still=()
  for id in "${reapable[@]}"; do
    if "$HERE/dispatch-close.sh" "$id" --by ttl; then :; else still+=("$id"); fi
  done
  reapable=("${still[@]:-}")
  # Drop the empty-string artefact of expanding an empty array under `set -u`.
  [ "${#reapable[@]}" = 1 ] && [ -z "${reapable[0]}" ] && reapable=()
fi

if [ "${#reapable[@]}" -gt 0 ]; then
  {
    echo "${#reapable[@]} FINISHED session(s) past the ${TTL}m TTL still holding a pane:"
    printf '  %s\n' "${reapable[@]}"
    echo "  reap them:  this tool is RETIRED except for the live claude-watchdog; \`pdispatch\` is gone."
    echo "              see skills/dispatchInstants/README.md, and \`fleet reap\` for the replacement."
    echo "  (transcripts persist under ~/.claude/projects/ — closing a pane loses context, not history)"
  } >&2
  exit 1
fi
exit 0
