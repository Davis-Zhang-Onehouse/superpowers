#!/usr/bin/env bash
# Explicit runtime coverage. Stub mode never launches a model; live mode is opt-in.
set -uo pipefail
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mode="${1:---stubs}"
case "$mode" in
  --stubs) ;;
  --live) echo 'Live lifecycle requires the private interactive procedure in docs/README.fleet-runtimes.md; no model was started.' >&2; exit 2 ;;
  *) echo 'usage: run-runtime.sh --stubs' >&2; exit 2 ;;
esac
. "$IT_ROOT/lib.sh"
IT_FAILED=0
it_own_cases 'RT[0-9]+|ISOLATION-RT-(enter|leave)'
it_section RT
case "$FLEET_TMUX_SOCKET" in itfleet-*) ;; *) echo 'private socket required' >&2; exit 2 ;; esac
mkdir -p "$EV/out"
RT_ATTEMPT="$(mktemp -d "$EV/attempt-XXXXXX")"
export FLEET_HOME="$RT_ATTEMPT/home" FLEET_INSTANTS="$RT_ATTEMPT/instants"
mkdir -p "$FLEET_HOME" "$FLEET_INSTANTS"
bash "$IT_ROOT/bin/source-pin.sh" before "$EV/out" || exit 2
trap 'it_tmux kill-server 2>/dev/null || true' EXIT
export FLEET_CLAUDE_BIN="$IT_ROOT/bin/claude" FLEET_CODEX_BIN="$IT_ROOT/bin/claude"
export CODEX_HOME="$EV/codex-config"
mkdir -p "$CODEX_HOME"
# Keep a control pane so terminal exit does not remove the private server mid-check.
it_tmux new-session -d -s itfleet-RT-control sleep 100000 || exit 2
if python3 "$IT_ROOT/runtime-checks.py" > "$EV/out/runtime.json" 2> "$EV/out/runtime.stderr"; then
  it_pass RT1 'fleet/it/RT/out/runtime.json' 'both runtimes launch with attested seed bytes, refuse an early switch, and switch back after close-out'
else
  it_fail RT1 'fleet/it/RT/out/runtime.stderr' 'runtime CLI lifecycle failed; inspect the attributed step log'
fi
it_tmux kill-server 2>/dev/null || true
it_assert_isolation RT-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$EV/out" || exit 3
exit "$IT_FAILED"
