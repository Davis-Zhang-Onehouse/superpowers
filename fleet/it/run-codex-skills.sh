#!/usr/bin/env bash
# CXS (FB-111): a real codex worker, dispatched by fleet, finds the superpowers skills, reads them and acts on
# them. Opt-in: it spends real codex model turns.
#
#   run-codex-skills.sh --live              CXS1 (GREEN) against this checkout: the dispatch gate refuses a bare
#                                           CODEX_HOME, the installer links the skills, and the worker reads and
#                                           follows systematic-debugging and using-fleet
#   run-codex-skills.sh --red <fleet-repo>  RED capture, no RESULTS row: the same probe driven by another fleet
#                                           (the base), with nothing installed; the evidence records what it saw
#
# Private socket (itfleet-CXS-*), private store, private CODEX_HOME holding a COPY of the credential (removed on
# exit). CXS_CODEX_HOME names the source config (read only; default /home/ubuntu/davis_root/.codex).
set -uo pipefail
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mode="${1:-}"
case "$mode" in
  --live) [ "$#" = 1 ] || { echo 'usage: run-codex-skills.sh --live | --red <fleet-repo>' >&2; exit 2; } ;;
  --red)
    [ "$#" = 2 ] && [ -x "$2/bin/fleet" ] || { echo 'usage: run-codex-skills.sh --red <fleet-repo with bin/fleet>' >&2; exit 2; }
    export CXS_FLEET_REPO CXS_INSTALL=0
    CXS_FLEET_REPO="$(cd "$2" && pwd)"
    ;;
  *) echo 'usage: run-codex-skills.sh --live | --red <fleet-repo>' >&2; exit 2 ;;
esac
. "$IT_ROOT/lib.sh"
IT_FAILED=0
it_own_cases 'CXS[0-9]+|ISOLATION-CXS-.*'
it_section "CXS-$$"
export CXS_ATTEMPT
CXS_ATTEMPT="$(mktemp -d "$EV/attempt-XXXXXX")"
bash "$IT_ROOT/bin/source-pin.sh" before "$EV" || exit 2
# The private CODEX_HOME's credential never outlives the run, pass or fail.
trap 'it_tmux kill-server 2>/dev/null || true; rm -f "$CXS_ATTEMPT/codex-home/auth.json"' EXIT
echo "codex skills test: $CXS_ATTEMPT (inspect: tmux -L $FLEET_TMUX_SOCKET attach)"
python3 "$IT_ROOT/codex-skills-live.py" > "$CXS_ATTEMPT/steps.log" 2>&1
rc=$?
if [ "$mode" = --live ]; then
  if [ "$rc" = 0 ]; then
    it_pass CXS1 "fleet/it/$SECTION/$(basename "$CXS_ATTEMPT")/evidence/verdict.json" 'a bare CODEX_HOME is refused at dispatch; after the install a real codex worker reads systematic-debugging and using-fleet and follows them (RCA before the fix, the skill'"'"'s exit codes)'
  else
    it_fail CXS1 "fleet/it/$SECTION/$(basename "$CXS_ATTEMPT")/steps.log" 'codex skills lifecycle incomplete; inspect the step log, verdict and frames'
  fi
else
  echo "RED capture (rc=$rc): $CXS_ATTEMPT/evidence/verdict.json"
fi
it_tmux kill-server 2>/dev/null || true
it_assert_isolation "CXS-leave"
bash "$IT_ROOT/bin/source-pin.sh" after "$EV" || exit 3
exit "$IT_FAILED"
