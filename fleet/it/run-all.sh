#!/usr/bin/env bash
# ONE validation run: every runner, sequentially, each into its own results file, then merged by this
# script as the single writer.
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
  "rmw:bash $IT_ROOT/run-rmw.sh 8"
  "K:bash $IT_ROOT/run-group3.sh K"
  "group5:bash $IT_ROOT/run-group5.sh L M N"
  "E:bash $IT_ROOT/run-group3.sh E"
)

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
