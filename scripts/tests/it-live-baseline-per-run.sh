#!/usr/bin/env bash
# The IT harness's live-session baseline is keyed PER RUN (FB-60, and FB-34/FB-47 before it).
#
# The baseline used to be one gitignored file per checkout, written only when absent and never advanced. In a
# leased slot it outlived the lessee that took it: a predecessor's `dt-` session, harvested between two runs,
# FAILed `ISOLATION-*` in every section of every later run. And a `dt-` session born AFTER that stale baseline
# could be killed inside a section with no alarm at all, because it was never in the baseline. Three instants
# lost time to the first half in one day. Nobody had seen the second.
#
# Driven for real: `lib.sh` and `facts.env` are copied into scratch and run as separate section processes.
# The "live" server is a PRIVATE default tmux server (TMUX_TMPDIR=<scratch>, TMUX unset), so the sessions
# created and killed here exist on no server anyone else uses. HOME and the cwd are scratch too, so the
# harness's live-store and live-instants halves watch nothing real.
#
# Run: bash scripts/tests/it-live-baseline-per-run.sh      (~3s; needs tmux)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
command -v tmux >/dev/null || { echo "FAIL: tmux is not installed, so nothing below can run"; exit 1; }
TMP="$(mktemp -d "${TMPDIR:-/tmp}/it-baseline-per-run-XXXXXX")"
export TMUX_TMPDIR="$TMP/tmux" HOME="$TMP/home"
unset TMUX FLEET_INSTANTS FLEET_ROOT FLEET_INSTANT FLEET_HOME IT_RUN_ID IT_RESULTS
mkdir -p "$TMUX_TMPDIR" "$HOME" "$TMP/it"
cleanup() { tmux kill-server 2>/dev/null; rm -rf "$TMP"; }
trap cleanup EXIT
cp "$REPO/fleet/it/lib.sh" "$REPO/fleet/it/facts.env" "$TMP/it/"
cd "$TMP" || exit 1            # lib.sh walks UP from the cwd for a .fleet-root; from scratch it finds none

fails=0
note() { printf '  %s\n' "$*"; }
# row <section> <case> -> "VERDICT<TAB>note" of that ISOLATION row, or MISSING. A missing row is never a pass.
row() { awk -F'\t' -v c="ISOLATION-$2" '$1==c {print $2 "\t" $4; f=1} END {if (!f) print "MISSING"}' "$TMP/results-$1.tsv"; }
want() {  # want <label> <section> <case> <verdict> [<substring the note must carry>]
  local got; got="$(row "$2" "$3")"
  if [ "${got%%$'\t'*}" != "$4" ]; then note "FAIL $1 — wanted $4, got: ${got:0:300}"; fails=1; return; fi
  if [ -n "${5:-}" ] && [[ "$got" != *"$5"* ]]; then note "FAIL $1 — $4 but the note lacks [$5]: ${got:0:300}"; fails=1; return; fi
  note "ok   $1"
}

cat > "$TMP/runner.sh" <<'EOF'
. "$IT/lib.sh"
IT_FAILED=0
it_section "$1"
[ "$2" = none ] || tmux kill-session -t "=$2"
it_assert_isolation "$1-leave"
EOF
section() { IT="$TMP/it" IT_RESULTS="$TMP/results-$1.tsv" bash "$TMP/runner.sh" "$1" "$2" >/dev/null 2>&1; }

tmux new-session -d -s zsh-operator
tmux new-session -d -s dt-predecessor

# --- THE CASE: a dt- session lost BETWEEN two runs is not the second run's doing -------------------------
section P1 none
want "run 1 establishes (a SKIP, not a pass)" P1 P1-enter SKIP "ESTABLISHED"
tmux kill-session -t =dt-predecessor
section P2 none
want "run 2 is not charged for a dt- session lost before it began" P2 P2-enter PASS "BETWEEN runs"
want "the loss is named in run 2's note" P2 P2-enter PASS "dt-predecessor"
want "run 2's own leave compares against run 2's baseline" P2 P2-leave PASS "byte-identical"
[ -s "$TMP/it/live-tmux-rebaselines.tsv" ] && grep -q 'dt-predecessor' "$TMP/it/live-tmux-rebaselines.tsv" \
  && note "ok   the re-establishment is logged, naming what moved" \
  || { note "FAIL no live-tmux-rebaselines.tsv row names dt-predecessor"; fails=1; }

# --- THE NEGATIVE CONTROL: a dt- session killed DURING a run is still a FAIL (SI-1) -----------------------
# dt-victim is created AFTER every earlier baseline. The pre-fix harness never saw its loss, because its
# stale baseline predated it; this is the case that proves the baseline now starts with the run.
tmux new-session -d -s dt-victim
section P3 dt-victim
want "a dt- session killed inside a section FAILs" P3 P3-leave FAIL "dt-victim"

# --- within ONE run, a loss between two sections is still charged (ISOLATION-ALL's purpose) --------------
tmux new-session -d -s dt-between
export IT_RUN_ID="same-run-$$"
section Q1 none
tmux kill-session -t =dt-between
section Q2 none
unset IT_RUN_ID
want "a dt- loss between two sections of ONE run FAILs" Q2 Q2-enter FAIL "dt-between"

# --- a harness-prefixed session left on the live server is a FAIL across runs too, and keeps firing -------
tmux new-session -d -s itfleet-Z-leaked
section R1 none
want "a harness-prefixed session found at a run's start FAILs" R1 R1-enter FAIL "itfleet-Z-leaked"
section R2 none
want "and the next run FAILs again: the handover did not advance past it" R2 R2-enter FAIL "itfleet-Z-leaked"
tmux kill-session -t =itfleet-Z-leaked
section R3 none
want "once it is cleared, the next run is clean again" R3 R3-enter PASS

n_runs="$(cd "$TMP/it" && ls live-tmux-sessions-run-*.txt 2>/dev/null | wc -l)"
[ "$n_runs" -ge 6 ] && note "ok   one baseline file per run ($n_runs), none shared" \
                    || { note "FAIL expected a per-run baseline file per run, found $n_runs"; fails=1; }

if [ "$fails" = 0 ]; then
  echo "PASS: the live-session baseline is per run — a dt- session lost BETWEEN runs is a logged NOTE, one lost DURING a run (inside a section or between two of its sections) is a FAIL, and a harness-prefixed leak FAILs every run until cleared"
  exit 0
fi
echo FAIL
exit 1
