#!/usr/bin/env bash
# ONE validation run over a DECLARED roster, sequentially, each runner into its own results file, then
# merged by this script as the single writer.
#
# TWO rosters, because "every runner" was a claim this file did not keep: it ran 11 of the 19 on disk, and
# F, G, H, I, J, O, P and LB were absent with no comment saying why. They are later work — their headers
# say `COMPLETE: F1-F11`, `COMPLETE: J1-J9`, `Not in Plan 6` — each run standalone and never added here.
#
#   (default)  the GATE roster: everything that is safe and quick enough to run for every release.
#   --full     every runner, EXCEPT §P unless FLEET_IT_ALLOW_CLAUDE=1.
#
# §P is excluded from `--full` by default for BUDGET, not capability: it dispatches a real `claude` and
# spends the account's weekly allowance. A release gate that silently consumes that is a gate that gets
# switched off.
#
# Why sequential and not parallel: `source-pin.sh` pins `src/*.py` and `tests/*.py` GLOBALLY, so two
# sections measuring at once are fine only while nobody edits those trees — but a run that finds a defect
# and gets it fixed invalidates every verdict measured before the fix. Sequential means the whole file is
# attributable to ONE tree state, which is the only way `RESULTS.tsv` can be read as a statement about HEAD
# rather than about a sequence of trees. `SI-14` is what taught me that: I contaminated §A's first run by
# editing `src/` beside it.
#
# Why this exists at all: after the `SI-15`/`SI-16`/`SI-20`/`SI-21`/`SI-22` fixes, every section that had
# already run was carrying a verdict measured against a tree that no longer exists. `SI-16` in particular
# changes a harvest row from VIOLATION to INFO, and §E's `E6` pins that violation BY KIND — so a fix in one
# module silently moved another section's expectation. Re-running everything is the only honest answer, and
# it needs to be one command or it will not happen.
#
# Run: bash fleet/it/run-all.sh
set -uo pipefail
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTANT="$(cd "$IT_ROOT/../.." && pwd)"
LOG="$IT_ROOT/FULL-RUN-closeout.log"
: > "$LOG"

# §A's `A2c` audits every `run-*.sh` for the isolation contract and counted this one as missing it. It was
# right to: an orchestrator that delegates is still a thing that runs, and "the runners I called each
# asserted" is an argument, not an assertion. Bracketing the whole BATCH is also strictly more than the sum
# of the parts — it catches drift that happens BETWEEN sections, which no single section can see.
IT_RESULTS="$IT_ROOT/RESULTS-closeout-all.tsv"
printf 'case\tverdict\tevidence\tnote\n' > "$IT_RESULTS"
export IT_RESULTS
# shellcheck disable=SC1091
. "$IT_ROOT/lib.sh"
IT_FAILED=0
SECTION=ALL
it_own_cases 'ISOLATION-ALL-(enter|leave)'
it_assert_isolation ALL-enter

say() { printf '%s\n' "$*" | tee -a "$LOG"; }

say "=== pinning the source for the WHOLE run ==="
bash "$IT_ROOT/bin/source-pin.sh" before "$IT_ROOT" | tee -a "$LOG"

# name : command  — order is cheapest-first so a broken harness is found in seconds, not after §E.
RUNNERS=(
  "w1:bash $IT_ROOT/run-w1.sh"
  "m9mut:bash $IT_ROOT/run-m9-mutation.sh"
  "e9leak:bash $IT_ROOT/run-e9-leak.sh"
  "A:bash $IT_ROOT/run-A.sh"
  "B:bash $IT_ROOT/run-B.sh"
  "C:bash $IT_ROOT/run-C.sh"
  "D:bash $IT_ROOT/run-D.sh"
  "Q:bash $IT_ROOT/run-Q.sh"
  #: In the DEFAULT roster, not `FULL_EXTRA`. It costs about ten seconds and it guards `FI-208` — the
  #: defect that made every input-box alarm in a live effort a false positive for ten and a half hours
  #: and left a finished worker unclosable except by `--force`. A control that only runs under `--full`
  #: is a control that is mostly not running.
  "i7:bash $IT_ROOT/run-i7.sh"
  "rmw:bash $IT_ROOT/run-rmw.sh 8"
  "K:bash $IT_ROOT/run-group3.sh K"
  "group5:bash $IT_ROOT/run-group5.sh L M N"
  "E:bash $IT_ROOT/run-group3.sh E"
)

# The sections added after this orchestrator was written. No prerequisites — checked per runner: each
# carries the same plain `Run: bash fleet/it/run-X.sh` line as the eleven above.
FULL_EXTRA=(
  "F:bash $IT_ROOT/run-F.sh"
  "G:bash $IT_ROOT/run-G.sh"
  "H:bash $IT_ROOT/run-H.sh"
  "I:bash $IT_ROOT/run-I.sh"
  "J:bash $IT_ROOT/run-J.sh"
  "O:bash $IT_ROOT/run-O.sh"
  "LB:bash $IT_ROOT/run-lineage.sh"
)

IT_FULL=no
for arg in "$@"; do
  case "$arg" in
    --full) IT_FULL=yes ;;
    *) echo "run-all.sh: unknown argument '$arg' (only --full is declared)" >&2; exit 2 ;;
  esac
done

if [ "$IT_FULL" = yes ]; then
  RUNNERS+=("${FULL_EXTRA[@]}")
  if [ "${FLEET_IT_ALLOW_CLAUDE:-0}" = 1 ]; then
    RUNNERS+=("P:bash $IT_ROOT/run-P.sh")
  else
    say "§P SKIPPED: it dispatches a real claude and spends the weekly allowance. Set FLEET_IT_ALLOW_CLAUDE=1 to include it."
  fi
fi
say "roster: $IT_FULL full; ${#RUNNERS[@]} runner(s)"

declare -A RC
for entry in "${RUNNERS[@]}"; do
  name="${entry%%:*}"; cmd="${entry#*:}"
  out="$IT_ROOT/RESULTS-closeout-$name.tsv"
  printf 'case\tverdict\tevidence\tnote\n' > "$out"
  say ""
  say "=== $name ==="
  IT_RESULTS="$out" $cmd >> "$LOG" 2>&1
  RC[$name]=$?
  say "--- $name exit=${RC[$name]}  $(grep -cP '\tPASS\t' "$out") PASS / $(grep -cP '\tFAIL\t' "$out") FAIL / $(grep -cP '\tSKIP\t' "$out") SKIP"
done

# The batch's own leave assertion, before the pin: if a section leaked something onto the live server, this
# is where it is caught even when the leaking section's own leave assertion passed.
IT_RESULTS="$IT_ROOT/RESULTS-closeout-all.tsv" RESULTS="$IT_ROOT/RESULTS-closeout-all.tsv" \
  it_assert_isolation ALL-leave

say ""
say "=== pinning the source AFTER the whole run ==="
if bash "$IT_ROOT/bin/source-pin.sh" after "$IT_ROOT" | tee -a "$LOG"; then
  say "the whole validation run is attributable to ONE tree state"
else
  say "CONTAMINATED: src/ or tests/ changed during the run. NO verdict below is a verdict."
  exit 3
fi

# --- the merge, by the single writer -------------------------------------------------------------
say ""
say "=== merging into RESULTS.tsv (one writer) ==="
python3 - "$IT_ROOT" all "${!RC[@]}" <<'PY' | tee -a "$LOG"
import pathlib, sys
root = pathlib.Path(sys.argv[1])
main = root / "RESULTS.tsv"
def rows(p):
    return [l for l in p.read_text().splitlines()[1:] if l.strip()]
header = main.read_text().splitlines()[0]
fresh, owned = [], set()
for name in sys.argv[2:]:
    f = root / f"RESULTS-closeout-{name}.tsv"
    if not f.is_file():
        continue
    for r in rows(f):
        fresh.append(r); owned.add(r.split("\t")[0])
# A section that RAN replaces its NOT-RUN row. Derived from the case ids present, never typed: a hand-kept
# list of "which sections ran" is a second copy of the truth (SD-2).
for sec in "ABCDEFGHIJKLMNOP":
    if any(r.split("\t")[0].startswith(sec) and r.split("\t")[0][1:2].isdigit() for r in fresh):
        owned.add(f"§{sec}")
existing = rows(main)
kept = [r for r in existing if r.split("\t")[0] not in owned]
notrun = [r for r in kept if "\tNOT-RUN\t" in r]
kept = [r for r in kept if "\tNOT-RUN\t" not in r]
main.write_text("\n".join([header] + kept + fresh + notrun) + "\n")
dupes = {}
for r in (kept + fresh + notrun):
    dupes[r.split("\t")[0]] = dupes.get(r.split("\t")[0], 0) + 1
print(f"merged {len(fresh)} fresh row(s) for {len(owned)} owned id(s); {len(kept)} untouched; "
      f"{len(notrun)} NOT-RUN")
print("duplicate case ids:", sorted(k for k, v in dupes.items() if v > 1) or "none")
PY

say ""
for v in PASS FAIL SKIP NOT-RUN; do
  say "$(printf '%-8s %s' "$v" "$(grep -cP "\t$v\t" "$IT_ROOT/RESULTS.tsv")")"
done
say "NOT-RUN sections: $(grep -P '\tNOT-RUN\t' "$IT_ROOT/RESULTS.tsv" | cut -f1 | tr '\n' ' ')"
say "FAIL rows: $(grep -P '\tFAIL\t' "$IT_ROOT/RESULTS.tsv" | cut -f1 | tr '\n' ' ')"
say ""
say "per-runner exit codes:"
for name in "${!RC[@]}"; do say "  $name=${RC[$name]}"; done

# --- the batch verdict ----------------------------------------------------------------------------
# `II-6`. This script used to end at the line above and fall off the end, so its status was whatever the
# last `say` returned — 0, always, over any number of failures. It COLLECTED `RC[$name]` for every runner
# and never acted on it. As a report for a human reading tallies that is defensible; as something a
# machine can gate on it is worse than useless, because it answers "fine". The release gate asked it, was
# told 0, and recorded GREEN over a suite with 7 FAIL rows.
#
# Derived from THIS RUN's registers. NOT from `RESULTS.tsv`: that file is MERGED and keeps rows from
# earlier runs of sections this run did not execute, so a count over it reports failures that did not
# happen now — and it would go green the moment a stale FAIL was replaced by a fresh PASS elsewhere.
#
# NOT from the per-runner exit codes either, and that is the sharper reason: every runner ends
# `exit "$IT_FAILED"`, which is a COUNT, so a section with exactly 256 failures exits 0. The codes are
# still consulted, but only for the one thing a row count cannot see — a runner that DIED before writing
# its rows. A crash with an empty register is a runner that never reached its cases, not one that passed
# them, and the source-pin contamination path produces exactly that shape.
fail_rows=0
for name in "${!RC[@]}" all; do
  reg="$IT_ROOT/RESULTS-closeout-$name.tsv"
  [ -f "$reg" ] || continue
  fail_rows=$(( fail_rows + $(grep -cP '\tFAIL\t' "$reg" || true) ))
done
crashed=""
for name in "${!RC[@]}"; do
  [ "${RC[$name]}" = 0 ] || crashed="$crashed $name(exit${RC[$name]})"
done

say ""
if [ "$fail_rows" = 0 ] && [ -z "$crashed" ]; then
  say "BATCH VERDICT: ok — 0 FAIL rows and no non-zero runner exit across the ${#RUNNERS[@]} runner(s) this run executed"
  exit 0
fi
say "BATCH VERDICT: attention — $fail_rows FAIL row(s) across the ${#RUNNERS[@]} runner(s) this run executed; runners exiting non-zero:${crashed:- none}"
exit 1
