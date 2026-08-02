#!/usr/bin/env bash
# FI-30c — the two read-modify-writes the parent left unfixed, MEASURED.
#
# `review._save` and `roadmap._save` publish through the one `atomic_write`, so no reader ever sees half a
# ledger. What that does NOT buy is an indivisible read-modify-write: `record` and `propose` each read the
# whole registry, append to it in memory, and write it back. Two concurrent writers therefore resolve
# last-writer-wins, and one of them vanishes.
#
# The parent declined to fix it, and gave the right reason: *"no §E case measures either path, so fixing
# them would be shipping a mechanism whose motivating failure has not been observed"* — `W2-3`'s demotion.
# Plan 7 W-4 then puts the choice exactly here: **either a case measures them and they get fixed, or they
# become an accepted risk with all four fields.** This is that case. Measuring is cheaper than arguing.
#
# Real OS processes released by a FIFO barrier, the way §E does it — a thread pool in one interpreter would
# measure the GIL, not the file.
#
# Run: bash fleet/it/run-rmw.sh [iterations]
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
it_own_cases 'RMW-(review|roadmap)'

ITERS="${1:-10}"
WRITERS=6

it_section RMW
OUT="$EV/out"; rm -rf "$OUT"; mkdir -p "$OUT"
export FLEET_INSTANTS="$EV/instants"; rm -rf "$FLEET_INSTANTS"; mkdir -p "$FLEET_INSTANTS"
TAG="r$$"        # run-unique: the instant timestamp is minute-resolution, so two runs in one
                 # minute would ask init for the same folder and be refused.

bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2

barrier() { GO="$OUT/go.fifo"; rm -f "$GO"; mkfifo "$GO"; }
release() { exec 9>"$GO"; exec 9>&-; }

# ------------------------------------------------------------------------------------------------
# RMW-review — N concurrent `review` rounds on ONE instant. Every one is a distinct round, so the
# ledger must end with exactly N. Fewer means a write was lost.
# ------------------------------------------------------------------------------------------------
lost_total=0; iters_with_loss=0; ran_review=0
printf 'iter\twriters\trounds_expected\trounds_found\tlost\n' > "$OUT/review-per-iteration.tsv"
for i in $(seq 1 "$ITERS"); do
  fleet init --base 00000000 --name "rmwRev$TAG$i" --instants-dir "$FLEET_INSTANTS" --porcelain \
       > "$OUT/review-init-$i.out" 2>&1
  #: from the verb's OWN output. `init` NORMALISES the name (rmwReview1 -> rmwreview1), so globbing for the
  #: name I passed finds nothing — which is how the first run of this file reported PASS on zero iterations.
  inst="$(awk -F'\t' '$1=="path" {print $2; exit}' "$OUT/review-init-$i.out")"
  [ -n "$inst" ] && [ -d "$inst" ] || { echo "init produced no instant for iteration $i" >&2; break; }
  ran_review=$(( ran_review + 1 ))
  barrier
  for w in $(seq 1 "$WRITERS"); do
    ( read -r _ < "$GO"
      fleet review --instant "$inst" --scope all --verdict READY \
            --finding "R$w:Minor:open:x:writer $w:none" >> "$OUT/review-w$w-$i.out" 2>&1 ) &
  done
  sleep 0.3
  release
  wait
  found="$(python3 -c "
import json,sys,pathlib
p = pathlib.Path(sys.argv[1]) / '.fleet' / 'review.json'
print(len(json.loads(p.read_text())['rounds']) if p.is_file() else 0)" "$inst" 2>/dev/null || echo 0)"
  lost=$(( WRITERS - found ))
  [ "$lost" -lt 0 ] && lost=0
  printf '%s\t%s\t%s\t%s\t%s\n' "$i" "$WRITERS" "$WRITERS" "$found" "$lost" \
    >> "$OUT/review-per-iteration.tsv"
  lost_total=$(( lost_total + lost ))
  [ "$lost" -gt 0 ] && iters_with_loss=$(( iters_with_loss + 1 ))
done

if [ "$ran_review" -eq 0 ]; then
  it_skip RMW-review "fleet/it/RMW/out/review-per-iteration.tsv" \
    "NOT MEASURED: zero iterations completed setup, so nothing was raced. Reported rather than passed — a loss counter that stayed at 0 because no writer ever ran is absence presented as success, and this runner did exactly that on its first attempt (SI-8's rule, applied to itself)"
elif [ "$lost_total" -eq 0 ]; then
  it_pass RMW-review "fleet/it/RMW/out/review-per-iteration.tsv" \
    "n=$ITERS x $WRITERS concurrent review rounds on one instant: every round survived in all $ran_review exercised iteration(s) (0 lost of $(( ran_review * WRITERS )) ). review._save's read-modify-write did NOT lose a write under this load"
else
  it_fail RMW-review "fleet/it/RMW/out/review-per-iteration.tsv" \
    "MEASURED LOSS: $lost_total of $(( ran_review * WRITERS )) rounds vanished across $iters_with_loss of the exercised iterations. review._save reads the whole ledger, appends in memory and writes it back, so two concurrent rounds resolve last-writer-wins — FI-30c, now observed rather than argued"
fi

# ------------------------------------------------------------------------------------------------
# RMW-roadmap — N concurrent `Roadmap.add` on ONE instant. Same shape, the other path.
# Not through `propose`: that verb REQUIRES the milestone to exist first, so racing it measured six
# BadInput failures and scored them as six lost writes. `add` -> `_save` is the read-modify-write itself.
# ------------------------------------------------------------------------------------------------
lost_total=0; iters_with_loss=0; ran_road=0
printf 'iter\twriters\tproposals_expected\tproposals_found\tlost\n' > "$OUT/roadmap-per-iteration.tsv"
for i in $(seq 1 "$ITERS"); do
  fleet init --base 00000000 --name "rmwRoad$TAG$i" --instants-dir "$FLEET_INSTANTS" --porcelain \
       > "$OUT/road-init-$i.out" 2>&1
  inst="$(awk -F'\t' '$1=="path" {print $2; exit}' "$OUT/road-init-$i.out")"
  [ -n "$inst" ] && [ -d "$inst" ] || { echo "init produced no instant for iteration $i" >&2; break; }
  ran_road=$(( ran_road + 1 ))
  barrier
  for w in $(seq 1 "$WRITERS"); do
    ( read -r _ < "$GO"
      python3 - "$inst" "$w" >> "$OUT/road-w$w-$i.out" 2>&1 <<'PY'
import pathlib, sys
from fleet.roadmap import Roadmap, Milestone
inst, w = pathlib.Path(sys.argv[1]), sys.argv[2]
Roadmap(inst).add(Milestone(id=f"m{w}", title=f"milestone {w}", status="ready", deps=[], evidence=["evidence/INDEX.md"]))
PY
    ) &
  done
  sleep 0.3
  release
  wait
  found="$(python3 -c "
import json,sys,pathlib
p = pathlib.Path(sys.argv[1]) / '.fleet' / 'roadmap.json'
print(len(json.loads(p.read_text())['milestones']) if p.is_file() else 0)" "$inst" 2>/dev/null || echo 0)"
  lost=$(( WRITERS - found ))
  [ "$lost" -lt 0 ] && lost=0
  printf '%s\t%s\t%s\t%s\t%s\n' "$i" "$WRITERS" "$WRITERS" "$found" "$lost" \
    >> "$OUT/roadmap-per-iteration.tsv"
  lost_total=$(( lost_total + lost ))
  [ "$lost" -gt 0 ] && iters_with_loss=$(( iters_with_loss + 1 ))
done

if [ "$ran_road" -eq 0 ]; then
  it_skip RMW-roadmap "fleet/it/RMW/out/roadmap-per-iteration.tsv" \
    "NOT MEASURED: zero iterations completed setup, so nothing was raced. See RMW-review's note"
elif [ "$lost_total" -eq 0 ]; then
  it_pass RMW-roadmap "fleet/it/RMW/out/roadmap-per-iteration.tsv" \
    "n=$ITERS x $WRITERS concurrent Roadmap.add calls on one instant: every milestone survived in all $ran_road exercised iteration(s) (0 lost of $(( ran_road * WRITERS )) ). roadmap._save's read-modify-write did NOT lose a write under this load"
else
  it_fail RMW-roadmap "fleet/it/RMW/out/roadmap-per-iteration.tsv" \
    "MEASURED LOSS: $lost_total of $(( ran_road * WRITERS )) milestones vanished across $iters_with_loss of the exercised iterations. roadmap._save is a last-writer-wins read-modify-write — FI-30c, now observed"
fi

it_assert_isolation RMW-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict" >&2; exit 3; }
sed -i "s|$INSTANT/||g" "$RESULTS"
echo "RMW done: IT_FAILED=$IT_FAILED"
#: `II-11`. Was `exit "$IT_FAILED"` — a COUNT. `exit` truncates modulo 256, so a section with
#: exactly 256 failures reported SUCCESS, and one with 300 reported 44, a number meaning nothing
#: to any reader. An exit status is a one-byte verdict, not a tally: the count is already printed
#: on the line above and is in the register, which is where a consumer should read it anyway.
if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
exit 1
