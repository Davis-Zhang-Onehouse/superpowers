#!/usr/bin/env bash
#
# dispatch-health.sh — one correct implementation of "is each worker actually OK?"
#
# Replaces per-coordinator hand-rolled liveness checks. Classifies every dispatched worker:
#   PENDING-LAUNCH  dispatched with --no-launch and not launched yet (the mandated review window)
#   DEAD       LAUNCHED and the session is gone (robust check: pgrep on the remote-control name, then tmux)
#   BLOCKED    alive but sitting on a permission modal — invisible to a plain liveness probe
#   IDLE       pane unchanged for $IDLE_MIN minutes (alive, doing nothing)
#   PARKED     parked decision AND not progressing (a parked note while still working is just a note)
#   COMPLETE   its instant folder is renamed -complete- => awaiting YOUR gate + harvest
#   HARVESTED  gated + harvested (recorded by `pdispatch gate --harvest --record`) — terminal history
#   AWAITING-CI  declared local validation done, waiting on CI — excluded from the WIP cap
#   RUNNING    working
#
# Usage:  dispatch-health.sh [--json] [--id <todo-id>] [--base <base-instant>] [--orphans]
# Exit:   0 = nothing needs attention   1 = something does   2 = bad input
# Env:    BOARD_DIR, TMUX_BIN, IDLE_MIN (default 30), HEALTH_TAG (idle-baseline namespace per caller)
set -uo pipefail
# shellcheck source=lib/dispatch-lib.sh
. "$(cd "$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")" && pwd)/lib/dispatch-lib.sh"

BOARD_DIR="${BOARD_DIR:-$HOME/.claude-dispatch-board}"
RECORDS="$BOARD_DIR/records"
TMUX_BIN="${TMUX_BIN:-tmux}"
IDLE_MIN="${IDLE_MIN:-30}"
# The idle baseline is mutable state on disk. Namespace it per caller ($HEALTH_TAG): a monitor
# sampling every 60s and a coordinator sampling on its own tick otherwise overwrite each other's
# baseline, so IDLE — and every state derived from it — flaps. Two watchers must not share one view.
HEALTH="$BOARD_DIR/health/${HEALTH_TAG:-shared}"

JSON=0; ONLY=""; ONLY_BASE=""; ORPHANS=0; ACTIVEDEV=0
# Default ONE (operator, 2026-07-29). Capacity was never the constraint — attention is. Every extra
# concurrent worker costs a review gate, a harvest, and a parked decision to answer. See
# coordinating-instants/SKILL.md § "The WIP cap" for what each past value of this number was derived
# from: it has been correct at "no cap", at 3, and now at 1, for three DIFFERENT efforts.
WIP_CAP="${WIP_CAP:-1}"
while [ $# -gt 0 ]; do
  case "$1" in
    --json) JSON=1; shift;;
    --id)   ONLY="${2:-}"; shift 2;;
    --base) ONLY_BASE="${2:-}"; shift 2;;
    --orphans) ORPHANS=1; shift;;
    --active-dev) ACTIVEDEV=1; shift;;
    # Print the header comment block, however long it is — counting lines drifted twice.
    -h|--help) awk 'NR==1{next} /^#/{print; next} {exit}' "$0"; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

[ -d "$RECORDS" ] || { echo "no records dir: $RECORDS" >&2; exit 2; }
mkdir -p "$HEALTH"

# A permission modal / prompt awaiting a human. Keep patterns broad: a false BLOCKED costs a
# glance, a missed one costs hours of a silently stalled worker.
MODAL_RE='Do you want to|and do not ask again|and don.t ask again|\(y/n\)|❯ 1\. Yes|1\. Yes, and|Allow this|Approve\?'

alive() { # $1 = tmux session name
  pgrep -f "remote-control $1" >/dev/null 2>&1 && return 0
  "$TMUX_BIN" has-session -t "$1" >/dev/null 2>&1
}

field() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2],"") or "")' "$1" "$2" 2>/dev/null; }

# The record stores the child path as of DISPATCH time, but a worker RENAMES its folder
# (-inflight- -> -complete-/-abort-) as its completion signal. Resolve the current folder by
# the instant's stable <base>-<curr> timestamp prefix, or completion stays invisible.
resolve_instant() { # $1 = recorded child path -> echoes the CURRENT basename
  local p="$1" d b pre m
  [ -n "$p" ] || return 0
  b="$(basename "$p")"
  if [ -d "$p" ]; then echo "$b"; return; fi
  d="$(dirname "$p")"
  # Match on <base>-<curr>-<ANY state>-<rest>: same-minute instants share the timestamps but
  # differ in <rest>, so keying on the timestamps alone can read a SIBLING's state (observed:
  # r2 and r3 were both 07270639-07270656).
  pre="$(printf '%s' "$b" | grep -oE '^[0-9]{8}-[0-9]{8}' || true)"
  rest="$(printf '%s' "$b" | sed -E 's/^[0-9]{8}-[0-9]{8}-(inflight|complete|abort)-//')"
  if [ -n "$pre" ] && [ -n "$rest" ] && [ -d "$d" ]; then
    m="$(ls -1 "$d" 2>/dev/null | grep -E "^${pre}-(inflight|complete|abort)-${rest}$" | head -1)"
    [ -n "$m" ] && { echo "$m"; return; }
  fi
  echo "$b"
}

need_attention=0
rows=(); orphans=(); running_n=0; active_dev=0

for f in "$RECORDS"/*.json; do
  [ -e "$f" ] || continue
  id="$(field "$f" todo_id)"; [ -n "$id" ] || id="$(basename "$f" .json)"
  [ -z "$ONLY" ] || [ "$ONLY" = "$id" ] || continue
  sess="$(field "$f" tmux)"
  child="$(field "$f" child_instant)"
  slot="$(field "$f" slot)"
  cname="$(resolve_instant "$child")"
  rbase="$(field "$f" base_instant)"
  harvested="$(field "$f" harvested_at)"
  launched="$(field "$f" launched_at)"
  # The board is machine-global: scope to one effort's records when asked.
  if [ -n "$ONLY_BASE" ] && [ "$rbase" != "$ONLY_BASE" ] \
     && [ "$(realpath -m -- "$rbase" 2>/dev/null)" != "$(realpath -m -- "$ONLY_BASE" 2>/dev/null)" ]; then
    continue
  fi

  state="RUNNING"; note=""; queued_txt=""
  # Self-heal: a record with no launched_at whose session is ALIVE was obviously launched — stamp it,
  # so records predating the launched_at field stop misreporting (they cannot be re-launched to fix).
  if [ -z "$launched" ] && alive "$sess"; then
    python3 - "$f" <<'PYS' 2>/dev/null || true
import json, sys, datetime
p = sys.argv[1]
d = json.load(open(p))
d["launched_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
d["launched_at_inferred"] = True
json.dump(d, open(p, "w"), indent=2, ensure_ascii=False)
PYS
    launched="inferred"
  fi

  if ! alive "$sess" && [ -z "$launched" ]; then
    # `--no-launch` writes the record immediately; the session only exists after `dispatch-launch`.
    # The charter review the skill MANDATES therefore opens a window where a healthy dispatch looks
    # DEAD — and reaping that phantom destroys a real worker. Only call it dead once it was launched.
    age=$(( ( $(date +%s) - $(stat -c %Y "$f" 2>/dev/null || echo 0) ) / 60 ))
    state="PENDING-LAUNCH"
    note="dispatched but not launched yet (${age}m) — review the charter, then: pdispatch launch $id"
    if [ "$age" -ge "${PENDING_MAX_MIN:-60}" ]; then
      # Old, unstamped, no session: this predates launched_at or was forgotten — we genuinely
      # cannot tell pending from dead. Say so and demand attention; never quietly excuse it.
      need_attention=1
      state="UNKNOWN"
      note="no launched_at and no session after ${age}m — legacy record or forgotten dispatch; cannot tell PENDING from DEAD. Check the pane, then launch or reap."
    fi
  elif ! alive "$sess"; then
    state="DEAD"; note="session gone — reap its slot (yours only) and decide: succeed it or re-dispatch"
  else
    pane="$("$TMUX_BIN" capture-pane -p -t "$sess" 2>/dev/null | tail -60)"
    # Text typed into the input box and never submitted. `send` was taught to PROVE delivery, but
    # nothing ever checked the receiving end, so a swallowed Enter is silent: on 2026-07-28 three
    # of four live panes were holding one, including an authorization a coordinator believed it had
    # sent. Only reported once the pane is IDLE — a human mid-typing is not a stuck submit.
    queued_txt="$(dl_pane_unsubmitted "$pane" || true)"
    if printf '%s' "$pane" | grep -qE "$MODAL_RE"; then
      state="BLOCKED"; note="waiting on a permission modal — answer only if reversible, else deny + park"
    else
      h="$(printf '%s' "$pane" | cksum | awk '{print $1}')"
      hf="$HEALTH/$id.hash"
      if [ -f "$hf" ] && [ "$(cat "$hf" 2>/dev/null)" = "$h" ]; then
        if [ -n "$(find "$hf" -mmin +"$IDLE_MIN" 2>/dev/null)" ]; then
          state="IDLE"; note="pane unchanged for >${IDLE_MIN}m — check whether it is done, stuck, or waiting"
        fi
      else
        printf '%s' "$h" > "$hf"
      fi
    fi
  fi

  # A worker that finished local validation and is only waiting on GitHub CI is not consuming dev
  # attention, so it must not hold a slot against the WIP cap. It can only be excluded if it DECLARES
  # the transition — hence a structural slot in its HANDOFF rather than a guess from the pane.
  hoff="$(dirname "$child")/$cname/HANDOFF.md"
  if [ "$state" = "RUNNING" ] || [ "$state" = "IDLE" ]; then
    if [ -f "$hoff" ] && grep -qiE '^\**(phase|state|status)\**:?[[:space:]]*AWAITING[-[:space:]]?CI' "$hoff" 2>/dev/null; then
      state="AWAITING-CI"
      note="local validation done; waiting on CI — does NOT count against the WIP cap"
    fi
  fi

  # A worker blocked on a decision is the most expensive silent stall. Detect the section's
  # CONTENT, not its heading: every instant is born with an empty "## Parked decision" block.
  if [ -f "$hoff" ]; then
    block="$(awk '/^## +Parked decision/{f=1;next} /^## /{f=0} f' "$hoff" 2>/dev/null)"
    # A "<none>" marker means empty even when the author adds an explanatory sentence after it —
    # filtering only the marker line leaves the prose and fires a false PARKED.
    if printf '%s' "$block" | grep -qiE '^\s*[(<]?none[)>]?\.?\s*$'; then
      parked=""
    else
      parked="$(printf '%s' "$block" | grep -vE '^\s*$|^-+$|^_+$' | head -3)"
    fi
    if [ -n "$parked" ]; then
      first="$(printf '%s' "$parked" | head -1 | cut -c1-80)"
      # An actionable blocker (a modal you can answer now, a dead session) must NOT be masked by a
      # standing operator note that will sit there all effort — that sends you to the wrong problem.
      if [ "$state" = "BLOCKED" ] || [ "$state" = "DEAD" ] || [ "$state" = "PENDING-LAUNCH" ]; then
        note="$note  [also parked: $first]"
      elif [ "$state" = "RUNNING" ]; then
        # Recorded an operator-only item and kept working — a NOTE, not a stall. Surface it, but do
        # not demand attention every tick: a permanently-red tick trains everyone to ignore red.
        note="parked note (still progressing): $first"
      else
        state="PARKED"
        note="STALLED on a parked decision: $first — decide it if it is yours"
      fi
    fi
  fi

  # A renamed folder is the worker's completion signal — surface it regardless of session state.
  # But once the coordinator has GATED + HARVESTED it, the record says so and it becomes terminal
  # history: a finished effort must stop demanding attention forever (coordinator RI-1 / RI-5).
  if [ -n "$harvested" ]; then
    state="HARVESTED"; note="gated ($(field "$f" gate_verdict)) + harvested $harvested — history, nothing owed"
    # A harvested worker still holding a live session is an ORPHAN: it consumes account-wide budget
    # for no work. Informational on the row, never "needs attention" — a permanently-red harvested
    # fleet would be the alarm-that-never-clears trap this tool exists to avoid.
    if alive "$sess"; then
      note="$note  [session still alive]"
      orphans+=("$id|$slot|$sess")
    fi

  elif [ -n "$cname" ] && [[ "$cname" == *-complete-* ]]; then
    state="COMPLETE"; note="folder renamed -complete- — UNHARVESTED: run the gate, then harvest"
    # Also an orphan if its session lives, but COMPLETE still governs the state: the completion
    # signal must survive — noting the orphan must never cost the reason the row matters.
    if alive "$sess"; then
      orphans+=("$id|$slot|$sess (no harvest marker — pre-dates it)")
    fi
  fi

  # An idle pane holding unsubmitted text is a message that was never received. Actionable and
  # cheap to fix, so it demands attention — and it clears the moment someone submits or clears it.
  if [ "$state" = "IDLE" ] && [ -n "$queued_txt" ]; then
    note="UNSUBMITTED text left in the input box: \"$queued_txt\" — submit it or clear it. $note"
    need_attention=1
  fi

  case "$state" in RUNNING|IDLE|BLOCKED|PARKED) active_dev=$((active_dev+1));; esac
  [ "$state" = "RUNNING" ] && running_n=$((running_n+1))
  case "$state" in DEAD|BLOCKED|IDLE|COMPLETE|PARKED) need_attention=1;; esac
  rows+=("$id|$state|$slot|$sess|$cname|$note")
done

if [ "$ACTIVEDEV" = 1 ]; then
  echo "$active_dev worker(s) in ACTIVE DEV (cap $WIP_CAP) — AWAITING-CI and harvested/complete excluded"
  if [ "$active_dev" -ge "$WIP_CAP" ]; then
    echo "  at or over the cap: do NOT dispatch another milestone until one drains or declares AWAITING-CI"
  else
    echo "  room for $(( WIP_CAP - active_dev )) more"
  fi
  exit 0
fi

if [ "$ORPHANS" = 1 ]; then
  if [ "${#orphans[@]}" = 0 ]; then
    echo "no orphaned sessions: every harvested worker has been torn down"
  else
    echo "${#orphans[@]} harvested/complete worker(s) still holding a live session:"
    for o in "${orphans[@]}"; do
      IFS='|' read -r oid oslot osess <<<"$o"
      printf '  %-46s slot %-5s %s\n' "$oid" "$oslot" "$osess"
    done
    echo
    # This block used to assert that idle sessions compete for account-wide budget. Measured on
    # 2026-07-28 against two nine-day-old ones: 28m of CPU across 9 days, blocked in ep_poll, no
    # child processes, no conversational turn in the transcript for 8 days. An idle session makes
    # no API calls. The claim was never measured, and it is what pushed an irreversible teardown.
    echo "  What this actually costs, measured — not the budget claim this tool used to make:"
    echo "   · tokens: none. An idle session is blocked on its event loop and issues no API calls."
    echo "   · memory: ~0.5 GB RSS each."
    echo "   · WRONG-TREE HAZARD (the real one): its cwd is a pool slot that may since have been"
    echo "     re-leased and repositioned onto another effort's branch. Two live processes, one"
    echo "     workspace — observed on ~/ws3."
    echo "   · LIVE TRIGGER: claude-watchdog re-arms a claude-auto-retry monitor on it, which types"
    echo "     'Continue where you left off.' + Enter on a rate-limit banner. With text queued in the"
    echo "     input box that submits the concatenation, inside that possibly-foreign tree."
    echo "  Teardown is RECOVERABLE: transcripts persist under ~/.claude/projects/, so closing a pane"
    echo "  costs its loaded context, not its history (claude --resume <session-id> brings it back)."
    if [ "$running_n" -gt 0 ]; then
      echo "   · $running_n worker(s) still RUNNING. If any audits earlier work (they usually do), a"
      echo "     defect in a harvested worker surfaces then — teardown is cheap to defer, so prefer"
      echo "     sequencing it AFTER the auditing milestones report."
    else
      echo "   · no worker is still running, so late-discovery risk is at its lowest right now."
    fi
    echo
    echo "  close one:  pdispatch close <todo-id>          (refuses a busy pane or unsubmitted input)"
    echo "  sweep all:  pdispatch sessions --reap          (also finds sessions with NO board record)"
  fi
  exit 0
fi

if [ "$JSON" = 1 ]; then
  printf '%s\n' "${rows[@]:-}" | python3 -c '
import sys, json
out=[]
for ln in sys.stdin.read().splitlines():
    if not ln.strip(): continue
    p=(ln.split("|",5)+[""]*6)[:6]
    out.append(dict(zip(["todo_id","state","slot","tmux","instant","note"],p)))
print(json.dumps(out, indent=2, ensure_ascii=False))'
else
  if [ "${#rows[@]}" = 0 ]; then
    echo "no dispatch records in $RECORDS"
  else
    printf '%-34s %-9s %-5s %s\n' "TODO" "STATE" "SLOT" "NOTE"
    for r in "${rows[@]}"; do
      IFS='|' read -r id st slot sess cname note <<<"$r"
      printf '%-34s %-9s %-5s %s\n' "$id" "$st" "$slot" "$note"
    done
    # commentary to stderr: stdout must stay parseable as pure data rows
    [ "$need_attention" = 1 ] && echo "=> items above need your attention this tick." >&2
  fi
fi
exit "$need_attention"
