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
# Recorded BEFORE parsing, because a passthrough is only proved by what the verb actually received --
# asserting on the gate's own source would pass against a flag it accepts and then drops.
[ -n "${STUB_ARGS_FILE:-}" ] && printf '%s\n' "$@" >"$STUB_ARGS_FILE"
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
  archive | archive-die)
    # What `Verify.run()` actually does, in its actual order: `archive_previous_attempt` FIRST -- a
    # RENAME of everything loose in evidence/ into `attempt-<n>-<verdict>/` -- and only AFTER fork, arg
    # parsing, `_refuse_if_self_deployed` and the whole exemption diff (a `git diff` plus up to ten
    # `git show` subprocesses). The two sleeps stand in for those two delays; the gate's wait loop fires
    # its first check microseconds after the pidfile write, so without them there is no race to lose and
    # the case would pass against the defective script too.
    sleep "${STUB_ARCHIVE_DELAY:-1}"
    mkdir -p "$ev/attempt-1-RED"
    [ -f "$ev/VERDICT.tsv" ] && mv "$ev/VERDICT.tsv" "$ev/attempt-1-RED/VERDICT.tsv"
    sleep "${STUB_ARCHIVE_DELAY:-1}"
    if [ "${STUB_MODE}" = "archive-die" ]; then
      printf 'stub: archived the previous attempt, then died\n' >"$ev/hermetic.log"
      exit 1
    fi
    printf 'suite\tverdict\tevidence\tnote\nverdict\tGREEN\t-\tthis run\n' >"$ev/VERDICT.tsv"
    ;;
esac
STUB_EOF
chmod +x "$STUB"

run_gate() { # run_gate <version> [gate-args...]
  local version="$1"; shift
  # RELEASE_GATE_POLL is the gate's own poll-interval seam (documented next to FLEET_BIN in
  # release-gate.sh): production polls every 30s, which would make this test's own wait loop race a
  # near-instant stub into a real 30s sleep on every case that loses the race -- observed making one
  # otherwise-sub-second run take 90s. A short interval here does not change what is being tested, only
  # how long the test waits to observe it.
  FLEET_BIN="$STUB" RELEASE_GATE_POLL=0.05 bash "$GATE" "$version" "$@"
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

# --- outcome 1, re-verified: a PREVIOUS attempt's VERDICT.tsv must never be reported as this run's -------
# Every case above starts from an empty evidence directory, which is exactly why this was invisible. The
# workflow the skill prescribes -- re-verify a version after an INCONCLUSIVE on a quiet box -- always
# starts from a NON-empty one, and `fleet-v0.5.9`/`fleet-v0.5.6` are CANDIDATE with RED VERDICT.tsv files
# on this box right now. Against a wait loop that tests mere PRESENCE, this prints the stale RED and exits
# 1 in under a second, while leaving a real ~45-minute detached run nobody is waiting on.
mkdir -p "$FLEET_RELEASES/fleet-v1.0.3/.release/evidence"
STALE="$FLEET_RELEASES/fleet-v1.0.3/.release/evidence/VERDICT.tsv"
printf 'suite\tverdict\tevidence\tnote\nverdict\tRED\t-\tSTALE previous attempt\n' >"$STALE"
out="$(STUB_MODE=archive STUB_ARCHIVE_DELAY=1 run_gate 1.0.3 2>&1)"; rc=$?
check "a re-verify over a previous attempt's VERDICT.tsv reports THIS run's verdict" "0" "$rc"
case "$out" in
  *"STALE previous attempt"*)
    note "FAIL the previous attempt's verdict row was reported as this run's: $out"
    fails=1
    ;;
  *"GREEN"*"this run"*) note "ok   the verdict reported is the one this run wrote, not the stale one" ;;
  *) note "FAIL neither verdict was reported: $out"; fails=1 ;;
esac
case "$out" in
  *"No such file"*)
    # The first attempt at this fix compared identity alone, which changes to "absent" the moment the
    # archive's rename unlinks the path -- so the wait broke out into a file that was not there yet.
    note "FAIL the wait broke out before the verdict existed (the archive's rename, not this run's write)"
    fails=1
    ;;
  *) note "ok   the wait did not break out on the archive's own rename" ;;
esac

# --- outcome 3 over a stale verdict: a dead run must still be a dead run, not the old attempt's answer ---
mkdir -p "$FLEET_RELEASES/fleet-v1.0.4/.release/evidence"
printf 'suite\tverdict\tevidence\tnote\nverdict\tGREEN\t-\tSTALE previous attempt\n' \
  >"$FLEET_RELEASES/fleet-v1.0.4/.release/evidence/VERDICT.tsv"
out="$(STUB_MODE=archive-die STUB_ARCHIVE_DELAY=1 run_gate 1.0.4 2>&1)"; rc=$?
check "a dead run over a previous attempt's VERDICT.tsv still exits 3" "3" "$rc"
# The stub archived before dying, so that file is NOT in $EV any more -- it is under attempt-1-RED/.
# A provenance message that is itself wrong about provenance is worse than none, so the location is
# checked rather than asserted.
case "$out" in
  *"archived into"*) note "ok   the archived earlier attempt is reported as archived, not as still in \$EV" ;;
  *"still in"*)
    note "FAIL the dead-run path claimed the earlier attempt is still in \$EV after the stub archived it: $out"
    fails=1
    ;;
  *) note "FAIL the earlier attempt's file was not named on the dead-run path: $out"; fails=1 ;;
esac

# --- the same message, the other way: a run that died BEFORE archiving leaves the file where it was -----
mkdir -p "$FLEET_RELEASES/fleet-v1.0.5/.release/evidence"
printf 'suite\tverdict\tevidence\tnote\nverdict\tGREEN\t-\tSTALE previous attempt\n' \
  >"$FLEET_RELEASES/fleet-v1.0.5/.release/evidence/VERDICT.tsv"
out="$(STUB_MODE=die run_gate 1.0.5 2>&1)"; rc=$?
check "a run that dies before archiving still exits 3" "3" "$rc"
case "$out" in
  *"still in"*) note "ok   an un-archived earlier attempt is reported as still in \$EV" ;;
  *) note "FAIL the un-archived earlier attempt was not located correctly: $out"; fails=1 ;;
esac

# --- --repo is passed through to release-verify ---------------------------------------------------------
# A release cut before MANIFEST.tsv carried `source_repo` (II-7) refuses INSIDE the detached process and
# writes no VERDICT.tsv, which this script would otherwise classify as outcome 3, "the run died" -- a
# wrong diagnosis produced by the launcher rather than by the gate.
ARGS_FILE="$TMP/verify-args"
STUB_ARGS_FILE="$ARGS_FILE" STUB_MODE=green run_gate 1.0.0 --repo "$TMP/some checkout" >/dev/null 2>&1
if grep -qx -- "--repo" "$ARGS_FILE" 2>/dev/null && grep -qxF -- "$TMP/some checkout" "$ARGS_FILE" 2>/dev/null; then
  note "ok   --repo and its path reach release-verify as two separate argv entries"
else
  note "FAIL --repo did not reach release-verify intact: $(tr '\n' ' ' <"$ARGS_FILE" 2>/dev/null)"
  fails=1
fi

rm -f "$ARGS_FILE"
STUB_ARGS_FILE="$ARGS_FILE" STUB_MODE=green run_gate 1.0.0 --full --repo "$TMP/co" >/dev/null 2>&1
if grep -qx -- "--full" "$ARGS_FILE" 2>/dev/null && grep -qx -- "--repo" "$ARGS_FILE" 2>/dev/null; then
  note "ok   --full and --repo can be given together"
else
  note "FAIL --full and --repo are not both passed: $(tr '\n' ' ' <"$ARGS_FILE" 2>/dev/null)"
  fails=1
fi

run_gate 1.0.0 --repo >/dev/null 2>&1
check "--repo without a path exits 2" "2" "$?"

run_gate 1.0.0 --bogus >/dev/null 2>&1
check "an unknown argument exits 2" "2" "$?"

# --- fleet binary not executable: exit 2 -----------------------------------------------------------------
FLEET_BIN="$TMP/no-such-fleet" bash "$GATE" 1.0.0 >/dev/null 2>&1
check "a non-executable fleet binary exits 2" "2" "$?"

if [ "$fails" = 0 ]; then
  echo "PASS: release-gate.sh launches release-verify with no pipe on the launch line and setsid present, classifies GREEN -> exit 0, RED -> exit 1 with FAIL rows attributed from the per-runner it-RESULTS-closeout files only (never the merged file), a dead run with no VERDICT.tsv -> exit 3 with hermetic.log surfaced, waits for THIS run's verdict rather than a previous attempt's surviving VERDICT.tsv (and without breaking out on the archive's own rename), still reports a dead run as exit 3 when an earlier attempt's verdict is on disk, and refuses a missing version, a nonexistent release, or a non-executable fleet binary with exit 2"
  exit 0
fi
echo FAIL
exit 1
