#!/usr/bin/env bash
# `scripts/release-gate.sh`, asserted against a stub `fleet` -- never a real ~45-minute
# `release-verify`.
#
# What would make the script's argument false, and what each check below catches:
#
#   * the launch line pipes the verb's own exit status through another command ("never pipe a control" --
#     `release-verify … | tail` reported EXIT 0 for a run that never wrote a VERDICT.tsv). Asserted
#     structurally, on the script's own source, because the only way to prove a pipeline is ABSENT is to
#     read the line and see there is none.
#   * the launch is not detached (`setsid` missing), which is what let a harness's own teardown take a
#     healthy run down with it.
#   * a verdict is read from the wrong outcome, or a dead run is misreported as a finished one.
#   * a FAIL is attributed from the merged `it-RESULTS.tsv`, which does not carry the runner, instead of
#     the per-runner `it-RESULTS-closeout-*.tsv` files.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
GATE="$REPO/scripts/release-gate.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fails=0
note() { printf '  %s\n' "$*"; }
check() { # check <label> <expected> <actual>
  local label="$1" want="$2" got="$3"
  if [ "$want" = "$got" ]; then
    note "ok   $label"
  else
    note "FAIL $label"
    note "       wanted: [$want]"
    note "       got:    [$got]"
    fails=1
  fi
}

# A store nowhere near a real fleet root: `release-gate.sh` sources `fleet-env.sh`, which walks up from
# $PWD looking for `.fleet-root`. Running from inside a real checkout (this repo has one at its ancestor)
# would otherwise let the walk find it and derive `FLEET_RELEASES` for someone else's releases area —
# these exports win over that derivation (`fleet-env.sh` only defaults, never forces), but only if they
# are set BEFORE the script runs, which is why every invocation below carries its own env prefix.
export FLEET_HOME="$TMP/home" FLEET_RELEASES="$TMP/releases" FLEET_TMUX_SOCKET="release-gate-test-$$"
mkdir -p "$FLEET_HOME"

# --- the stub `fleet`: a narrow double for `release-verify`, driven entirely by env vars a case sets ----
#
# STUB_MODE selects the behaviour; STUB_SLEEP lets the "still running, verdict lands late" case exist
# without a real 45-minute run. It never touches the real gate.
STUB="$TMP/fleet"
cat >"$STUB" <<'STUB_EOF'
#!/usr/bin/env bash
set -uo pipefail
# Parse just enough to find --releases and --version; this stub only ever plays `release-verify`.
releases="" version=""
while [ $# -gt 0 ]; do
  case "$1" in
    --releases) releases="$2"; shift 2 ;;
    --version) version="$2"; shift 2 ;;
    *) shift ;;
  esac
done
ev="$releases/fleet-v$version/.release/evidence"
mkdir -p "$ev"
[ -n "${STUB_SLEEP:-}" ] && sleep "$STUB_SLEEP"
case "${STUB_MODE:-green}" in
  green)
    printf 'suite\tverdict\tevidence\tnote\nverdict\tGREEN\t-\tstub run\n' >"$ev/VERDICT.tsv"
    ;;
  red)
    printf 'suite\tverdict\tevidence\tnote\nverdict\tRED\t-\tstub run\n' >"$ev/VERDICT.tsv"
    printf 'name\tverdict\tevidence\tdetail\nit-9\tFAIL\t-\tper-runner failure\n' \
      >"$ev/it-RESULTS-closeout-groupA.tsv"
    printf 'name\tverdict\tevidence\tdetail\nit-merged-only\tFAIL\t-\tshould never be reported\n' \
      >"$ev/it-RESULTS.tsv"
    ;;
  die)
    printf 'stub: hermetic half ran, then died\n' >"$ev/hermetic.log"
    exit 1
    ;;
esac
STUB_EOF
chmod +x "$STUB"

run_gate() { # run_gate <version> [gate-args...]
  local version="$1"; shift
  FLEET_BIN="$STUB" bash "$GATE" "$version" "$@"
}

# --- structural properties: read from the script's own source, not its behaviour --------------------
# These are the two properties a passing behavioural test cannot distinguish from a lucky pipeline: a
# pipe that happens not to lose data on a fast stub still loses it on a real 45-minute run.
launch_line="$(grep '"\$FLEET" release-verify' "$GATE")"
case "$launch_line" in
  *'|'*) note "FAIL the release-verify launch line contains a pipe: $launch_line"; fails=1 ;;
  *) note "ok   the release-verify launch line contains no pipe" ;;
esac
case "$launch_line" in
  *setsid*) note "ok   the launch line uses setsid" ;;
  *)
    # setsid may lead the PRECEDING line if the command wrapped; check the two lines around the verb too.
    context="$(grep -B1 '"\$FLEET" release-verify' "$GATE")"
    case "$context" in
      *setsid*) note "ok   the launch line uses setsid" ;;
      *) note "FAIL no setsid around the release-verify launch"; fails=1 ;;
    esac
    ;;
esac

# --- missing version argument: exit 2, no stub involved -----------------------------------------------
bash "$GATE" >/dev/null 2>&1
check "a missing version argument exits 2" "2" "$?"

# --- a release directory that does not exist: exit 2 ---------------------------------------------------
run_gate "9.9.9" >/dev/null 2>&1
check "a nonexistent release directory exits 2" "2" "$?"

mkdir -p "$FLEET_RELEASES/fleet-v1.0.0/.release"
mkdir -p "$FLEET_RELEASES/fleet-v1.0.1/.release"
mkdir -p "$FLEET_RELEASES/fleet-v1.0.2/.release"

# --- outcome 1: GREEN verdict -> exit 0 -----------------------------------------------------------------
out="$(STUB_MODE=green run_gate 1.0.0 2>&1)"; rc=$?
check "a GREEN verdict exits 0" "0" "$rc"
case "$out" in
  *"verdict"*"GREEN"*) note "ok   the verdict row is printed" ;;
  *) note "FAIL the verdict row was not printed: $out"; fails=1 ;;
esac

# --- outcome 1: RED verdict -> exit 1, and FAIL rows come from the PER-RUNNER file only -----------------
out="$(STUB_MODE=red run_gate 1.0.1 2>&1)"; rc=$?
check "a RED verdict exits 1" "1" "$rc"
case "$out" in
  *"it-9"*) note "ok   the per-runner FAIL row is reported" ;;
  *) note "FAIL the per-runner FAIL row (it-9) is missing from: $out"; fails=1 ;;
esac
case "$out" in
  *"it-merged-only"*)
    note "FAIL a FAIL present only in the merged it-RESULTS.tsv was reported (must come from per-runner files only)"
    fails=1
    ;;
  *) note "ok   the merged-only FAIL row is not reported" ;;
esac

# --- outcome 3: the process dies without writing VERDICT.tsv -> exit 3 ----------------------------------
# This is the one the pipe hid: `release-verify … | tail` reported exit 0 for exactly this case.
out="$(STUB_MODE=die run_gate 1.0.2 2>&1)"; rc=$?
check "a dead run with no VERDICT.tsv exits 3" "3" "$rc"
case "$out" in
  *"hermetic.log"*) note "ok   hermetic.log is surfaced on a dead run" ;;
  *) note "FAIL hermetic.log was not mentioned on a dead run: $out"; fails=1 ;;
esac

# --- fleet binary not executable: exit 2 -----------------------------------------------------------------
FLEET_BIN="$TMP/no-such-fleet" bash "$GATE" 1.0.0 >/dev/null 2>&1
check "a non-executable fleet binary exits 2" "2" "$?"

if [ "$fails" = 0 ]; then
  echo "PASS: release-gate.sh launches release-verify with no pipe on the launch line and setsid present, classifies GREEN -> exit 0, RED -> exit 1 with FAIL rows attributed from the per-runner it-RESULTS-closeout files only (never the merged file), a dead run with no VERDICT.tsv -> exit 3 with hermetic.log surfaced, and refuses a missing version, a nonexistent release, or a non-executable fleet binary with exit 2"
  exit 0
fi
echo FAIL
exit 1
