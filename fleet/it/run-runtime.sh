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
  --choice-live)
    # RTC (pt2): real native CLIs, trivial seeds, on a private server and store whose box runtime is claude.
    # (a) claude on claude-fable-5-1, (b) codex on its default model, (d) each revived with its runtime and model.
    . "$IT_ROOT/lib.sh"
    IT_FAILED=0
    it_own_cases 'RTC[0-9]+|ISOLATION-RTC-.*'
    it_section "RTC-$$"
    export RT_ATTEMPT
    RT_ATTEMPT="$(mktemp -d "$EV/attempt-XXXXXX")"
    bash "$IT_ROOT/bin/source-pin.sh" before "$EV" || exit 2
    # The private CODEX_HOME holds a COPY of the credential; it never outlives the run, pass or fail.
    trap 'it_tmux kill-server 2>/dev/null || true; rm -f "$RT_ATTEMPT/codex-home/auth.json"' EXIT
    echo "Native runtime-choice test: $RT_ATTEMPT (inspect: tmux -L $FLEET_TMUX_SOCKET attach)"
    if python3 "$IT_ROOT/runtime-choice-live.py" > "$RT_ATTEMPT/steps.log" 2>&1; then
      it_pass RTC1 "fleet/it/$SECTION/$(basename "$RT_ATTEMPT")/evidence/verdict.json" 'on a claude box: a claude-fable-5-1 worker and a codex default-model worker each start, answer, pass seed-check and pane-guard, and revive with the same runtime and model'
    else
      it_fail RTC1 "fleet/it/$SECTION/$(basename "$RT_ATTEMPT")/steps.log" 'native runtime-choice lifecycle incomplete; inspect the step log and frames'
    fi
    it_tmux kill-server 2>/dev/null || true
    it_assert_isolation "RTC-leave"
    bash "$IT_ROOT/bin/source-pin.sh" after "$EV" || exit 3
    exit "$IT_FAILED"
    ;;
  *) echo 'usage: run-runtime.sh --stubs | --live --runtime claude|codex | --choice-live' >&2; exit 2 ;;
esac
. "$IT_ROOT/lib.sh"
IT_FAILED=0
it_own_cases 'RT[0-9]+|ISOLATION-RT-(enter|leave)'
it_section RT
# The private socket is `it_section`'s to set (`itfleet-RT`, one line up), so there is nothing to check
# here; the refusals that actually decide are `it_tmux`'s own and the stand-in's (`bin/claude`), both of
# which refuse any non-`itfleet-` server before touching tmux.
mkdir -p "$EV/out"
RT_ATTEMPT="$(mktemp -d "$EV/attempt-XXXXXX")"
export FLEET_HOME="$RT_ATTEMPT/home" FLEET_INSTANTS="$RT_ATTEMPT/instants"
mkdir -p "$FLEET_HOME" "$FLEET_INSTANTS"
bash "$IT_ROOT/bin/source-pin.sh" before "$EV/out" || exit 2
trap 'it_tmux kill-server 2>/dev/null || true' EXIT
export FLEET_CLAUDE_BIN="$IT_ROOT/bin/claude" FLEET_CODEX_BIN="$IT_ROOT/bin/claude"
# Per attempt (FB-111): its skills link points into this run's releases area, removed on exit.
export CODEX_HOME="$RT_ATTEMPT/codex-config"
mkdir -p "$CODEX_HOME"
# FB-111. A codex dispatch is refused when CODEX_HOME cannot see the superpowers skills, so the stub home gets them
# the way a root's does: the installer's one link, through a private releases area whose `current` is this checkout.
# The releases area lives OUTSIDE the checkout: `current` names the checkout, and a link to an ancestor inside it is
# a cycle for any `rglob` over the tree. Removed on exit, with the server.
RT_RELEASES="$(mktemp -d)"
trap 'it_tmux kill-server 2>/dev/null || true; rm -rf "$RT_RELEASES"' EXIT
ln -s "$(cd "$IT_ROOT/../.." && pwd)" "$RT_RELEASES/current"
bash "$IT_ROOT/../../scripts/fleet-codex-skills.sh" --codex-home "$CODEX_HOME" --releases "$RT_RELEASES" \
  > "$EV/out/codex-skills.txt" 2>&1 || { echo "codex skills install failed: $EV/out/codex-skills.txt" >&2; exit 2; }
# Keep a control pane so terminal exit does not remove the private server mid-check.
it_tmux new-session -d -s itfleet-RT-control sleep 100000 || exit 2
if python3 "$IT_ROOT/runtime-checks.py" > "$EV/out/runtime.json" 2> "$EV/out/runtime.stderr"; then
  it_pass RT1 'fleet/it/RT/out/runtime.json' 'both runtimes launch with attested seed bytes, refuse an early switch, and switch back after close-out'
else
  it_fail RT1 'fleet/it/RT/out/runtime.stderr' 'runtime CLI lifecycle failed; inspect the attributed step log'
fi
# RT2 (pt2): per-dispatch runtime/model on a claude box, in a store of its own (RT1's asserts it starts empty).
RT2_ATTEMPT="$(mktemp -d "$EV/attempt-XXXXXX")"
mkdir -p "$RT2_ATTEMPT/home"
if FLEET_HOME="$RT2_ATTEMPT/home" FLEET_INSTANTS="$RT2_ATTEMPT/instants" \
   python3 "$IT_ROOT/runtime-choice-checks.py" > "$EV/out/runtime-choice.json" 2> "$EV/out/runtime-choice.stderr"; then
  it_pass RT2 'fleet/it/RT/out/runtime-choice.json' 'on a claude box: no flags launch the base argv exactly; --model reaches the claude argv and the record; --runtime codex launches codex with no model flag and leaves the box selection untouched'
else
  it_fail RT2 'fleet/it/RT/out/runtime-choice.stderr' 'per-dispatch runtime/model choice failed; inspect the step log'
fi
it_tmux kill-server 2>/dev/null || true
it_assert_isolation RT-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$EV/out" || exit 3
exit "$IT_FAILED"
