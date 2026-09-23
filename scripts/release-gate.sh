#!/usr/bin/env bash
#
# Run the release gate for one version, once, and report its verdict.
#
# Usage:  scripts/release-gate.sh <version> [--full]
#
# Exists because four separate gate runs were lost or misread in one session, and not one of them was a
# property of the gate:
#   * `release-verify … | tail -40` reported EXIT 0 for a run that never wrote a VERDICT.tsv -- a
#     pipeline's exit status is the last stage's (fleet/CLAUDE.md "never pipe a control"), so a dead run
#     became indistinguishable from a finished gate.
#   * a waiter with a fixed iteration cap reported "NO VERDICT FILE" over a run that was healthy and
#     mid-flight. The gate measures ~45 min here, against the ~24 the skill used to quote.
#   * `nohup … &` inside a harness background task stays in that task's process group, so stopping the
#     task signalled the group and took the run with it. `setsid` is what detaches.
#   * `timeout 300` was a guess about a duration the operator did not know. rc=124.
#
# It runs the gate ONCE. Re-running is a separate human invocation, on purpose: a gate you retry until
# it passes is not a gate.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

# Capture and clear OUR OWN positional args before sourcing fleet-env.sh, and for exactly the reason its
# own header warns about: it takes an optional `$1` of its own (a directory, to set FLEET_INSTANTS), and
# a rc may source it "from inside a function, where `$1` belongs to the function, not to the person
# sourcing." A gate invocation IS such a function call — sourcing with `$1` still set to our <version>
# made fleet-env.sh print `'1.0.1' is not a directory; FLEET_INSTANTS left as unset` on every single run,
# a confusing, wrong-looking warning at the top of the one script this task exists to make trustworthy.
V="${1:-}"
if [ -z "$V" ]; then
  echo "usage: $(basename "$0") <version> [--full] [--repo <path>]" >&2
  exit 2
fi
shift

# `--repo` is passed straight through because `release-verify` needs it for a release cut before
# MANIFEST.tsv carried `source_repo` (II-7). Without it such a release refuses INSIDE the detached
# process, writes no VERDICT.tsv, and this script would classify a legible refusal as outcome 3, "the
# run died" -- a wrong diagnosis produced by the launcher rather than by the gate. Not live today (all
# ten retained releases carry `source_repo`), which is why it is a passthrough and not a default.
FULL=""
REPO_ARG=()
while [ $# -gt 0 ]; do
  case "$1" in
    --full)
      FULL="--full"
      shift
      ;;
    --repo)
      if [ $# -lt 2 ] || [ -z "$2" ]; then
        echo "$(basename "$0"): --repo needs a path" >&2
        exit 2
      fi
      REPO_ARG=(--repo "$2")
      shift 2
      ;;
    *)
      echo "$(basename "$0"): unknown argument '$1' (only --full and --repo <path>)" >&2
      exit 2
      ;;
  esac
done
set --

# shellcheck source=scripts/fleet-env.sh
. "$REPO/scripts/fleet-env.sh"

# Test seam: a stub script the test points here instead of a real, ~45-minute `fleet release-verify`.
# Narrow on purpose -- it is the ONLY variable this script consults instead of deriving the binary from
# `$REPO`, so a test overriding it cannot accidentally also override the paths the launch-correctness
# assertions (no pipe, `setsid` present, `$REPO/bin/fleet` by absolute path) are checking.
# NOT `FLEET_BIN` (FB-56). `fleet dispatch` exports FLEET_BIN into every worker it starts, naming the fleet
# that ran dispatch, so reading that name here ran the DISPATCHER'S binary (for a release worker, the deployed
# copy) instead of the one this script ships beside. The seam has a name nothing exports.
FLEET="${FLEET_LAUNCHER_TEST_BIN:-$REPO/bin/fleet}"

# Test seam: the wait loop's poll interval. Production default stays 30s -- a real gate runs ~45 minutes,
# so 30s costs nothing there -- but a test driving a near-instant stub would otherwise race the loop's
# FIRST check against the backgrounded stub even being scheduled, and lose that race into a real 30s
# sleep. The test overrides this to something small instead of shrinking the production default.
SLEEP_S="${RELEASE_GATE_POLL:-30}"

[ -x "$FLEET" ] || {
  echo "$(basename "$0"): '$FLEET' is not executable — build/checkout looks wrong" >&2
  exit 2
}

R="${FLEET_RELEASES:-}"
if [ -z "$R" ]; then
  echo "$(basename "$0"): FLEET_RELEASES is unset — source scripts/fleet-env.sh from inside a fleet root" >&2
  exit 2
fi

REL="$R/fleet-v$V"
if [ ! -d "$REL" ]; then
  echo "$(basename "$0"): no release directory for $V at $REL. \`fleet release-list\` shows what has been cut." >&2
  exit 2
fi

EV="$REL/.release/evidence"

# The launch's OWN bookkeeping — never inside `$REL`, because nothing here may mutate a release: `.release`
# is the artifact's mutable half (state + evidence, written by `fleet` itself), and this script is not
# `fleet`. A sibling directory under the releases root, named by version, keeps it out of the release
# while still being where an operator looking for "the gate for 0.5.12" would look first.
GATEDIR="$R/.release-gate"
mkdir -p "$GATEDIR"
LOG="$GATEDIR/$V.log"
PIDFILE="$GATEDIR/$V.pid"

# The identity of any VERDICT.tsv a PREVIOUS attempt left behind, snapshotted BEFORE the launch.
#
# Presence alone is not a usable condition, and reading it as one reimplemented the very defect this
# script exists to eliminate: a control reporting an outcome it did not measure, exactly like the piped
# `| tail` reporting EXIT 0 over a dead run. `Verify.run()` calls `archive_previous_attempt` FIRST
# (release_verify.py), but "first" is still after fork, arg parsing, `_refuse_if_self_deployed` and the
# whole exemption diff (a `git diff` plus up to ten `git show` subprocesses) -- while the wait loop's
# first check fires microseconds after the pidfile write, so a presence test wins that race essentially
# always. Measured against a stub of that shape: the script printed the previous attempt's
# `verdict RED … STALE previous attempt` and exited 1 in under a second, while the real run's GREEN
# landed six seconds later -- leaving a detached ~45-minute run nobody was waiting on, and later an
# orphan worktree. `fleet-v0.5.9` and `fleet-v0.5.6` are CANDIDATE with RED VERDICT.tsv files on this box
# today, and re-verifying after an INCONCLUSIVE is the workflow the skill itself prescribes, so this was
# not a corner case.
#
# Identity, not presence, because `archive_previous_attempt` moves the old file away with
# `path.rename(destination / path.name)` -- a rename WITHIN the evidence directory, into
# `attempt-<n>-<verdict>/`. The old file stays alive there, so its inode cannot be reused and this run's
# VERDICT.tsv is always a fresh one. (inode, mtime) therefore changes exactly when this run writes it.
#
# And identity is not enough on its own, which is the second half of the same measurement: that rename
# UNLINKS the path before this run writes anything, so between the archive and the verdict the identity
# has already changed -- to "absent". A bare "has the identity changed" test therefore breaks out of the
# wait into a file that is not there yet, and `awk` reports `No such file or directory` twice. Measured,
# on the first attempt at this fix. Both halves are required: a verdict is THIS run's only when the path
# exists AND is not the one the snapshot recorded.
verdict_identity() { stat -c %i:%Y "$EV/VERDICT.tsv" 2>/dev/null || echo none; }
STALE_VERDICT="$(verdict_identity)"

this_runs_verdict() { # 0 when VERDICT.tsv is present and is not the one a previous attempt left behind
  local now
  now="$(verdict_identity)"
  [ "$now" != "none" ] && [ "$now" != "$STALE_VERDICT" ]
}

echo "$(basename "$0"): launching release-verify for $V with $FLEET (log: $LOG)"

# The launch line the four incidents are each a violation of: no pipe (Trap: `| tail` ate the exit
# status), no `timeout` (Trap: rc=124 on a guessed duration), `setsid` (Trap: a harness background task's
# process group took the run down with it on teardown).
setsid nohup "$FLEET" release-verify --version "$V" --releases "$R" $FULL ${REPO_ARG[@]+"${REPO_ARG[@]}"} \
  >"$LOG" 2>&1 </dev/null &
pid=$!
echo "$pid" >"$PIDFILE"

echo "$(basename "$0"): pid $pid — a detached run outlives this shell; find it by this pid or this log"

# Wait on the disjunction, unbounded. No fixed iteration cap and no `timeout`: the gate has taken ~45
# minutes on this box against the ~24 a stale skill used to quote, and a cap sized for the old number
# reports "no verdict" over a run that is healthy and mid-flight.
while ! this_runs_verdict && kill -0 "$pid" 2>/dev/null; do
  sleep "$SLEEP_S"
done

# Re-read rather than trusting the loop's last look: the pid can exit in the same instant it writes the
# verdict, which leaves the loop through the `kill -0` half with the file already in place.
if this_runs_verdict; then
  # Outcome 1: the verdict is in. Print it, then every FAIL row — read from the PER-RUNNER files, never
  # the merged `it-RESULTS.tsv`, because only the per-runner files carry which runner a FAIL came from.
  awk -F'\t' '$1=="verdict"{print}' "$EV/VERDICT.tsv"
  result="$(awk -F'\t' '$1=="verdict"{print $2; exit}' "$EV/VERDICT.tsv")"

  shopt -s nullglob
  fail_files=("$EV"/it-RESULTS-closeout-*.tsv)
  shopt -u nullglob
  if [ "${#fail_files[@]}" -gt 0 ]; then
    awk -F'\t' '$2=="FAIL"{print FILENAME" :: "$1" :: "$4}' "${fail_files[@]}"
  fi

  case "$result" in
    GREEN | EXEMPT) exit 0 ;;
    *) exit 1 ;;
  esac
fi

# Outcome 2: the pid is gone and no verdict was written — a dead run, not a finished one. Trap 8's
# checklist, executed here rather than left for the operator to remember under time pressure.
echo "$(basename "$0"): pid $pid is gone and this run never wrote $EV/VERDICT.tsv — the run died" >&2
if [ "$STALE_VERDICT" != "none" ]; then
  # Named, never printed as a verdict: a file this run did not write is evidence of the attempt BEFORE
  # it, and letting it stand in for this one is the defect the identity snapshot above exists to prevent.
  #
  # WHERE it is now is checked rather than asserted. If the run got far enough to call
  # `archive_previous_attempt` before dying, that file has already been renamed into
  # `$EV/attempt-<n>-<verdict>/` and saying it "is still in $EV" would be false -- a message about
  # provenance that is itself wrong about provenance is worse than no message.
  if [ -f "$EV/VERDICT.tsv" ]; then
    echo "(a VERDICT.tsv from an earlier attempt is still in $EV — it is NOT this run's and was not read)" >&2
  else
    echo "(the earlier attempt's VERDICT.tsv was archived into $EV/attempt-*/ — this run wrote none)" >&2
  fi
fi
if [ -f "$EV/hermetic.log" ]; then
  stat --format='hermetic.log: %s bytes, modified %y' "$EV/hermetic.log"
else
  echo "hermetic.log: not present"
fi
echo "--- last 20 lines of $LOG ---"
tail -n 20 "$LOG" 2>/dev/null || true
exit 3
