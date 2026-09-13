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

# shellcheck source=scripts/fleet-env.sh
. "$REPO/scripts/fleet-env.sh"

# Test seam: a stub script the test points here instead of a real, ~45-minute `fleet release-verify`.
# Narrow on purpose -- it is the ONLY variable this script consults instead of deriving the binary from
# `$REPO`, so a test overriding it cannot accidentally also override the paths the launch-correctness
# assertions (no pipe, `setsid` present, `$REPO/bin/fleet` by absolute path) are checking.
FLEET="${FLEET_BIN:-$REPO/bin/fleet}"

V="${1:-}"
if [ -z "$V" ]; then
  echo "usage: $(basename "$0") <version> [--full]" >&2
  exit 2
fi

FULL=""
case "${2:-}" in
  "") ;;
  --full) FULL="--full" ;;
  *)
    echo "$(basename "$0"): unknown argument '$2' (only --full)" >&2
    exit 2
    ;;
esac

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

echo "$(basename "$0"): launching release-verify for $V (log: $LOG)"

# The launch line the four incidents are each a violation of: no pipe (Trap: `| tail` ate the exit
# status), no `timeout` (Trap: rc=124 on a guessed duration), `setsid` (Trap: a harness background task's
# process group took the run down with it on teardown).
setsid nohup "$FLEET" release-verify --version "$V" --releases "$R" $FULL \
  >"$LOG" 2>&1 </dev/null &
pid=$!
echo "$pid" >"$PIDFILE"

echo "$(basename "$0"): pid $pid — a detached run outlives this shell; find it by this pid or this log"

# Wait on the disjunction, unbounded. No fixed iteration cap and no `timeout`: the gate has taken ~45
# minutes on this box against the ~24 a stale skill used to quote, and a cap sized for the old number
# reports "no verdict" over a run that is healthy and mid-flight.
while [ ! -f "$EV/VERDICT.tsv" ] && kill -0 "$pid" 2>/dev/null; do
  sleep 30
done

if [ -f "$EV/VERDICT.tsv" ]; then
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
echo "$(basename "$0"): pid $pid is gone and $EV/VERDICT.tsv was never written — the run died" >&2
if [ -f "$EV/hermetic.log" ]; then
  stat --format='hermetic.log: %s bytes, modified %y' "$EV/hermetic.log"
else
  echo "hermetic.log: not present"
fi
echo "--- last 20 lines of $LOG ---"
tail -n 20 "$LOG" 2>/dev/null || true
exit 3
