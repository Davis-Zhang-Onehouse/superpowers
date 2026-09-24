#!/usr/bin/env bash
# §OR (v23-k, FB-113): a REAL codex worker on a claude box, observed with its RECORD's runtime by pane-guard and board.
# Live and opt-in like `run-runtime.sh --choice-live`: it launches the native codex CLI (one model turn per step) under
# a private CODEX_HOME holding a COPY of the credential, on a private itfleet-OR- server and store.
set -uo pipefail
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"
IT_FAILED=0
it_own_cases 'OR[0-9]+|ISOLATION-OR-.*'
it_section "OR-$$"
export OR_ATTEMPT
OR_ATTEMPT="$(mktemp -d "$EV/attempt-XXXXXX")"
bash "$IT_ROOT/bin/source-pin.sh" before "$EV" || exit 2
# The private CODEX_HOME holds a COPY of the credential; it never outlives the run, pass or fail.
trap 'it_tmux kill-server 2>/dev/null || true; rm -f "$OR_ATTEMPT/codex-home/auth.json"' EXIT
echo "Observe-record-runtime test: $OR_ATTEMPT (inspect: tmux -L $FLEET_TMUX_SOCKET attach)"
if python3 "$IT_ROOT/observe-runtime-live.py" > "$OR_ATTEMPT/steps.log" 2>&1; then
  it_pass OR1 "fleet/it/$SECTION/$(basename "$OR_ATTEMPT")/evidence/verdict.json" 'on a claude box a codex worker reads pane-guard 0 idle and 11 mid-turn (nested claude process, background terminal), and board never reports a runtime mismatch'
else
  it_fail OR1 "fleet/it/$SECTION/$(basename "$OR_ATTEMPT")/steps.log" 'a codex pane was misread; see verdict.json problems and evidence/frames'
fi
it_tmux kill-server 2>/dev/null || true
it_assert_isolation "OR-leave"
bash "$IT_ROOT/bin/source-pin.sh" after "$EV" || exit 3
exit "$IT_FAILED"
