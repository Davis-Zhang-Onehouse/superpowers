#!/usr/bin/env bash
# CXP (FB-110, D-45): a REAL codex worker, launched and revived by fleet, runs unattended with approval=never inside
# the workspace-write sandbox with network on. Opt-in (it spends model tokens and reads the root's codex credential).
# The credential is COPIED into a private CODEX_HOME and deleted on exit. A session that refreshes its token there may
# rotate a ChatGPT refresh token, which can invalidate the copy in the source root (the same exposure as RTC and CXS).
# Prefer an API-key credential when one is available (CXP_CODEX_HOME names the source).
#   run-codex-policy.sh            the fix: asserts GREEN (CXP1)
#   run-codex-policy.sh --red      the base: asserts the defect is observed (CXP-RED)
#   run-codex-policy.sh --red-escalate   the base, worker asked to escalate one denied write: stalls at a dialog (CXP-RED-ESC)
#   run-codex-policy.sh --green-escalate the fix, same seed: refused with no prompt, no keystroke, no write (CXP2)
set -uo pipefail
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "${1:-}" in
  '') expect=green case_id=CXP1 ;;
  --red) expect=red case_id=CXP-RED ;;
  --red-escalate) expect=red case_id=CXP-RED-ESC; export CXP_ESCALATE=1 ;;
  --green-escalate) expect=green case_id=CXP2; export CXP_ESCALATE=1 ;;
  *) echo 'usage: run-codex-policy.sh [--red|--red-escalate|--green-escalate]' >&2; exit 2 ;;
esac
. "$IT_ROOT/lib.sh"
IT_FAILED=0
it_own_cases 'CXP[0-9]+|CXP-RED(-ESC)?|ISOLATION-CXP-.*'
it_section "CXP-$$"
export RT_ATTEMPT CXP_EXPECT="$expect"
RT_ATTEMPT="$(mktemp -d "$EV/attempt-XXXXXX")"
bash "$IT_ROOT/bin/source-pin.sh" before "$EV" || exit 2
# The private CODEX_HOME holds a COPY of the credential; it never outlives the run, pass or fail.
trap 'it_tmux kill-server 2>/dev/null || true; rm -f "$RT_ATTEMPT/codex-home/auth.json"' EXIT
echo "Codex policy test ($expect): $RT_ATTEMPT (inspect: tmux -L $FLEET_TMUX_SOCKET attach)"
if python3 "$IT_ROOT/codex-policy-live.py" > "$RT_ATTEMPT/steps.log" 2>&1 </dev/null; then
  it_pass "$case_id" "fleet/it/$SECTION/$(basename "$RT_ATTEMPT")/evidence/verdict.json" \
    "codex worker policy ($expect): see verdict.json"
else
  it_fail "$case_id" "fleet/it/$SECTION/$(basename "$RT_ATTEMPT")/steps.log" \
    "codex worker policy ($expect) not shown; inspect the step log and frames"
fi
it_tmux kill-server 2>/dev/null || true
it_assert_isolation "CXP-leave"
bash "$IT_ROOT/bin/source-pin.sh" after "$EV" || exit 3
exit "$IT_FAILED"
