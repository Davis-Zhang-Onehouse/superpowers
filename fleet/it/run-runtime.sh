#!/usr/bin/env bash
# Explicit runtime coverage. Stub mode never launches a model; live mode is opt-in.
set -uo pipefail
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mode="${1:---stubs}"
case "$mode" in
  --stubs) ;;
  --live)
    if [ "${2:-}" != --runtime ] || { [ "${3:-}" != claude ] && [ "${3:-}" != codex ]; } || [ "$#" != 3 ]; then
      echo 'usage: run-runtime.sh --live --runtime claude|codex' >&2; exit 2
    fi
    if [ -z "${RT_LIVE_CONFIG:-}" ] || [ ! -d "$RT_LIVE_CONFIG" ]; then
      echo 'RT_LIVE_CONFIG must name a private authenticated native-plugin configuration directory' >&2; exit 2
    fi
    runtime="$3"
    . "$IT_ROOT/lib.sh"
    IT_FAILED=0
    it_own_cases 'RTL[0-9]+|ISOLATION-RTL-.*'
    it_section "RTL-$runtime-$$"
    export RT_ATTEMPT
    RT_ATTEMPT="$(mktemp -d "$EV/attempt-XXXXXX")"
    bash "$IT_ROOT/bin/source-pin.sh" before "$EV" || exit 2
    trap 'it_tmux kill-server 2>/dev/null || true' EXIT
    echo "Native $runtime test: $RT_ATTEMPT"
    echo "Trust/permission dialogs require inspection: tmux -L $FLEET_TMUX_SOCKET attach"
    if python3 "$IT_ROOT/runtime-live.py" "$runtime"; then
      it_pass RTL1 "fleet/it/$SECTION/$(basename "$RT_ATTEMPT")/evidence/commands.jsonl" 'native coordinator and two workers completed proposal/review/harvest and switch-back'
    else
      it_fail RTL1 "fleet/it/$SECTION" 'live lifecycle incomplete; inspect retained evidence and leases'
    fi
    it_tmux kill-server 2>/dev/null || true
    it_assert_isolation "RTL-$runtime-leave"
    bash "$IT_ROOT/bin/source-pin.sh" after "$EV" || exit 3
    exit "$IT_FAILED"
    ;;
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
