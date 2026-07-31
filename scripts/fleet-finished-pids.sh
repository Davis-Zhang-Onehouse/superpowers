#!/usr/bin/env bash
#
# fleet-finished-pids.sh — the `dispatch-sessions.sh --finished-pids` contract, answered from `fleet`.
#
# A drop-in for `claude-watchdog.sh`'s one remaining pdispatch dependency. Point the watchdog at it with:
#
#     CLAUDE_WATCHDOG_SESSIONS_TOOL=/home/ubuntu/davis_root/superpowers/scripts/fleet-finished-pids.sh
#
# The watchdog already exposes that override, so switching costs no edit to the daemon's logic and is undone by
# unsetting one variable. That is why this is a separate script and not a patch.
#
# THE CONTRACT, and it is narrow: print one pid per line for every live claude process that is a DISPATCHED
# WORKER WHOSE WORK IS OVER. Nothing else. The watchdog adds those to its exclude list so a finished worker
# stops being re-armed, and the reason is recorded in the watchdog itself — on 2026-07-28 two workers nine days
# past the end of their effort still had live monitors, and "on a rate-limit banner the monitor types 'Continue
# where you left off.' + Enter into a pane whose cwd may since have been re-leased to a different effort."
#
# WHAT MUST NOT BE PRINTED, because getting it backwards switches auto-resume off for the whole box:
#
#   * a session with NO dispatch record. `fleet reconcile` marks those `unarmed`, because nothing in the store
#     authorises acting on them — the right answer to reconcile's question and the WRONG answer to this one. An
#     unmanaged in-scope session is exactly what the watchdog exists to protect. Mapping `unarmed -> exclude`
#     would exclude every session on a box with no fleet records.
#   * a worker still working. Only `state COMPLETE` qualifies, which is the state reconcile assigns when the
#     instant folder is `-complete-` or `-abort-`: the work is over either way.
#
# With an empty or absent FLEET_HOME there are no worker subjects, so this prints nothing — identical to what
# the old tool printed against an empty board. It degrades to "exclude nothing", never "exclude everything".
#
# TWO calls, deliberately. `reconcile` says WHICH subjects are finished but its rows carry no pid; `status`
# carries `evidence.pid`. Reading the pid out of reconcile's prose would mean parsing a sentence, and the pid
# is not in it — checked, not assumed.
#
# Exit 0 always, like the tool it replaces: the watchdog treats failure as "no exclusions", so a non-zero exit
# would be indistinguishable from that while looking like a fault.
set -uo pipefail

case "${1:-}" in
  --finished-pids) ;;
  --help|-h) sed -n '2,36p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  "")  echo "usage: $(basename "$0") --finished-pids" >&2; exit 2 ;;
  *)   echo "$(basename "$0"): unknown argument '$1' (only --finished-pids)" >&2; exit 2 ;;
esac

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FLEET="${FLEET_BIN:-$HERE/../bin/fleet}"
[ -x "$FLEET" ] || exit 0                     # no fleet, no exclusions — the safe direction

# Subjects whose work is over. `reconcile`'s arm-set rows are `armed`/`unarmed` with the state leading the
# detail column, so an exact prefix match is enough and no state list is restated here.
finished="$("$FLEET" reconcile --porcelain 2>/dev/null \
            | awk -F'\t' '($1=="armed" || $1=="unarmed") && $4 ~ /^state COMPLETE,/ { print $2 }')"
[ -n "$finished" ] || exit 0

# `kind == worker` is then re-asserted, and this is belt-and-braces rather than a fix for a live bug — the
# distinction is worth stating precisely, because a comment that overclaims is how the next reader loses trust
# in the rest of them.
#
# The state filter alone IS sufficient today: `state COMPLETE` is produced at exactly one place in
# `reconcile.py`, and only for a `worker` subject. Non-worker kinds get `UNKNOWN_SESSION` or `STALE_LEASE`,
# never COMPLETE. So nothing else can currently reach the loop below.
#
# It is asserted anyway because the sufficiency is a coincidence in ANOTHER module, and one this file cannot
# see. `reconcile` renders `state <STATE>` at the head of the detail column for every subject regardless of
# why it declined to arm one, so the moment any non-worker kind gains a folder-derived state, a row beginning
# `state COMPLETE,` starts meaning something this tool must not act on — and the failure would be invisible,
# because the watchdog only ever sees a pid, and a pid excluded in error looks exactly like a pid correctly
# excluded. One field comparison buys immunity to a change made three modules away.
#
# Kind is asked of `status`, which emits it as a field, in the pass that already reads the pid. `reconcile`
# cannot answer it: its own `kind` column carries `armed`/`unarmed`, and a subject's kind reaches that
# porcelain only inside the refusal prose for non-workers. Matching prose would work today and break the next
# time somebody rewords a sentence; a field will not.
for subject in $finished; do
  # `evidence.pid` is empty when no live process matched the record — a finished worker that has already gone
  # needs no exclusion, because there is nothing left to arm.
  "$FLEET" status --id "$subject" --porcelain 2>/dev/null \
    | awk -F'\t' '$1=="kind"          { kind = $2 }
                  $1=="evidence.pid" && $2 ~ /^[0-9]+$/ { pid = $2 }
                  END { if (kind == "worker" && pid != "") print pid }'
done | sort -un
exit 0
