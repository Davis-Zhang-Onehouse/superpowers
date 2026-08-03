#!/usr/bin/env bash
# REPRO for G-2 — "fleet DETECTS an idle worker and nothing ACTS on it".
#
# G-2's symptom is an ABSENCE, and an absence cannot be photographed. So this reproduces the three
# separable facts the RCA needs, each with its own artifact:
#
#   PART 1  the detector genuinely WORKS today   — drive `reconcile()` on a synthetic idle worker and
#                                                  show it yields IDLE + needs_a_human=True
#   PART 2  the signal reaches a VIEW and stops  — enumerate every consumer of that judgement
#   PART 3  the detector is UNVERIFIED           — mutate it away and watch the suite stay green
#
# PART 3 carries its own CONTROL, because "the suite does not catch X" is worthless from a harness that
# cannot catch anything: M-2 reverts `FI-14`'s actual one-line fix and MUST be killed. A mutation that
# survives next to a control that dies is a measurement; a mutation that survives alone is a bug report
# about the runner.
#
# Follows `fleet/it/run-m9-mutation.sh`: `cp -r` the tree (src AND tests — a mutant with no tests/ dies of
# ModuleNotFoundError, which is a kill for the wrong reason), assert every anchor present-and-unique,
# assert the baseline GREEN before trusting any kill, and check WHY each mutant died.
#
# EXPECT below was updated in G-10 (fleet task 1 of the stall-loop plan): M-1 and M-3 were SURVIVE
# because the IDLE detector had no guard. `TestTheIdleDetectorIsProduced` in `test_reconcile.py` closed
# that gap, so all three mutants — M-1, the CONTROL M-2, and M-3 — are now expected to KILL. A run
# that goes back to SURVIVE on M-1 or M-3 means the guard regressed, not that this table is stale.
#
# Run:   bash bin/repro-g2-stall-loop.sh        (~6 min; 4 full hermetic suite runs)
# Costs: nothing. No tmux, no claude, no network. Writes only under evidence/repro-g2/.
set -uo pipefail

REPO="${REPO:-/home/ubuntu/davis_root/superpowers}"
INSTANT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EV="$INSTANT_DIR/evidence/repro-g2"
# A previous run's output is ARCHIVED, never deleted. This opened with `rm -rf "$EV"` — which made an
# evidence script that destroys evidence: a Task-1 implementer put its BEFORE mutation table in here as the
# brief asked, re-ran the script, and lost the artifact it had been told to preserve. It then reconstructed
# the table from its own transcript, which is exactly the "reading is not capturing" failure the RCA
# discipline exists to prevent.
#
# The `rm` was there for a real reason and it still has to be handled: `part3-mutations.tsv` is APPENDED to
# (`>>`), so a surviving file from a previous run would silently double its rows. Moving the whole directory
# aside satisfies both — a clean slate for this run, and nothing lost from the last one.
if [ -d "$EV" ]; then
  mv "$EV" "$EV-prev-$(TZ=UTC date -u '+%Y%m%dT%H%M%SZ')"
fi
mkdir -p "$EV"

echo "# G-2 reproduction — $(TZ=UTC date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "# repo $REPO @ $(git -C "$REPO" rev-parse --short HEAD), tree $( [ -z "$(git -C "$REPO" status --porcelain)" ] && echo CLEAN || echo DIRTY )"
echo "# artifacts -> evidence/repro-g2/"
echo

# =============================================================== PART 1 — the detector works
echo "== PART 1: does reconcile() actually produce IDLE for a stalled worker? =="
PYTHONPATH="$REPO/fleet/src:$REPO/fleet/tests" python3 - "$EV" <<'PY' 2>&1 | tee "$EV/part1-detector.txt"
import os, pathlib, sys, time
from test_cli import Fleet, IDLE_PANE, BUSY_PANE          # the package's OWN fixture (working method 6)
from fleet.reconcile import reconcile, needs_a_human, ACTIONABLE_STATES

EV = pathlib.Path(sys.argv[1])
fleet = Fleet()

# Two workers, identical except for what their pane shows and how long ago the instant changed.
stalled = fleet.worker("stalled", slot="ws1", pane=IDLE_PANE)
working = fleet.worker("working", slot="ws2", pane=BUSY_PANE)

def backdate(instant, seconds):
    """Age every path `_idle_for` looks at: the instant root, its children, and .fleet/*."""
    old = time.time() - seconds
    paths = [instant] + list(instant.iterdir())
    for child in list(instant.iterdir()):
        if child.name == ".fleet" and child.is_dir():
            paths += list(child.iterdir())
    for path in paths:
        os.utime(path, (old, old))

# 45 minutes of nothing — past the shipped 1800s threshold.
# `store.all()`, not `store.records` — the latter is the records DIRECTORY (a Path), and calling it
# raises "'PosixPath' object is not callable". Cost me one run.
for rec in fleet.store.all():
    instant = pathlib.Path(rec.child_instant)
    if "stalled" in instant.name:
        backdate(instant, 2700)

subjects = reconcile(fleet.store, fleet.pool, fleet.sessions, fleet.instants, idle_after_s=1800)

print(f"ACTIONABLE_STATES = {ACTIONABLE_STATES}")
print()
rows = []
for s in subjects:
    row = (s.identity, s.state, needs_a_human(s), s.note)
    rows.append(row)
    print(f"  {row[0]:<34} state={row[1]:<11} needs_a_human={row[2]!s:<5} note={row[3]!r}")
print()

idle = [r for r in rows if r[1] == "IDLE"]
if len(idle) == 1 and idle[0][2] is True:
    print("VERDICT PART 1: the DETECTOR WORKS. A worker untouched for 2700s with a non-working pane is")
    print("                classified IDLE and needs_a_human() returns True. The judgement exists and is")
    print("                correct — so G-2 is NOT a broken detector. Whatever is missing is downstream.")
    (EV / "part1-verdict.txt").write_text("DETECTOR-WORKS\n")
else:
    print(f"VERDICT PART 1: UNEXPECTED — {len(idle)} IDLE subject(s): {idle}")
    print("                The detector did not fire. G-2's premise as written would be WRONG, and the")
    print("                brief must be corrected before anything is designed. Do not proceed.")
    (EV / "part1-verdict.txt").write_text("DETECTOR-DID-NOT-FIRE\n")
    sys.exit(1)
PY
part1=$?
echo

# =============================================================== PART 2 — where the signal dies
echo "== PART 2: who consumes the judgement? =="
{
  echo "# Every reference to the actionable judgement, repo-wide, at $(git -C "$REPO" rev-parse --short HEAD)."
  echo "# reconcile.py is the PRODUCER and is excluded. Anything left is a consumer."
  echo
  grep -rn --include="*.py" --include="*.sh" --include="*.md" \
       "ACTIONABLE_STATES\|needs_a_human" "$REPO/fleet/src" "$REPO/scripts" "$REPO/skills" "$REPO/bin" \
       2>/dev/null | grep -v "src/fleet/reconcile.py"
  echo
  echo "# --- and the only daemon on the box: does it know the word reconcile? ---"
  grep -n "reconcile" "$REPO/scripts/claude-watchdog.sh" || echo "(no match: claude-watchdog.sh never calls fleet reconcile)"
} > "$EV/part2-consumers.txt" 2>&1
sed -n '1,40p' "$EV/part2-consumers.txt"
echo

# =============================================================== PART 3 — the detector is unverified
echo "== PART 3: mutation — is the IDLE detector protected by any test? =="
SUITE=(python3 -m unittest discover -s tests)

# A mutant tree must MIRROR THE REPO LAYOUT, not just hold src+tests. Four cases resolve the repo root
# as `Path(__file__).resolve().parents[2]` and read `skills/using-fleet/{SKILL.md,profiles/}` —
# `test_contracts.py:772`, `test_profiles.py:226`. A flat `$EV/mutN/{src,tests}` puts parents[2] at
# `$EV`, those four go RED, and the baseline gate then refuses every result. That is what the first run
# of this script did: 1183 tests, 2 failures + 2 errors, all four of them my copy's fault and none of
# them the product's. `skills/` is SYMLINKED because the mutations touch only `src/fleet/reconcile.py`
# and those four cases only ever read it.
make_tree() {   # make_tree <name> -> populates $EV/<name>/fleet/{src,tests} + $EV/<name>/skills
  local root="$EV/$1"
  rm -rf "$root"; mkdir -p "$root/fleet"
  cp -r "$REPO/fleet/src" "$REPO/fleet/tests" "$root/fleet/"
  ln -s "$REPO/skills" "$root/skills"
}

run_suite() {   # run_suite <tree-name> <logfile>
  ( cd "$EV/$1/fleet" && PYTHONPATH=src "${SUITE[@]}" ) > "$2" 2>&1
}

# --- baseline: the pristine copy must be GREEN, or every result below is noise -----------------
make_tree baseline
if run_suite baseline "$EV/baseline.out"; then
  echo "  baseline   GREEN   $(tail -3 "$EV/baseline.out" | tr '\n' ' ')"
else
  echo "  baseline   RED     — refusing to report mutation results; a killer verified against a red"
  echo "                       baseline proves nothing. See evidence/repro-g2/baseline.out"
  exit 1
fi

for n in 1 2 3; do make_tree "mut$n"; done

python3 - "$EV" <<'PY'
import pathlib, sys
EV = pathlib.Path(sys.argv[1])

def inject(rel, old, new, label):
    path = EV / rel
    text = path.read_text()
    count = text.count(old)
    # present-and-unique, asserted: a mutation applied twice or not at all makes the result
    # unattributable, and a `cp -r` copy is exactly where that goes unnoticed (M9's lesson).
    assert count == 1, f"{label}: anchor appears {count} times, not once"
    path.write_text(text.replace(old, new))
    print(f"  injected M-{label}")

# M-1: the DETECTOR. Make the idle threshold unreachable, so `_live_state` can never emit IDLE.
# Everything else — the state constant, the tuple, the note, the render — is untouched.
inject("mut1/fleet/src/fleet/reconcile.py",
       "    elif _idle_for(instant) > idle_after_s:",
       "    elif False and _idle_for(instant) > idle_after_s:   # M-1: detector disabled",
       "1 the IDLE detector never fires")

# M-2: the CONTROL. Revert FI-14's actual shipped fix — drop IDLE from the actionable tuple.
# `test_render.py` asserts this tuple's contents literally, so this MUST die. If it does not, the
# harness cannot kill anything and M-1's survival says nothing.
inject("mut2/fleet/src/fleet/reconcile.py",
       "ACTIONABLE_STATES = (BLOCKED, IDLE)",
       "ACTIONABLE_STATES = (BLOCKED,)   # M-2: FI-14 reverted",
       "2 CONTROL — FI-14's fix reverted")

# M-3: the ACTIVITY PROBE. `_idle_for` always reports fresh, so the threshold is never crossed even
# though the branch is intact. Separates "the branch is untested" from "the probe is untested".
inject("mut3/fleet/src/fleet/reconcile.py",
       "    if instant is None:\n        return 0.0",
       "    if True:   # M-3: activity probe always reports fresh\n        return 0.0",
       "3 the activity probe always says fresh")
PY
echo

declare -A WHAT=(
  [1]="the IDLE detector never fires — \`_live_state\`'s threshold branch is dead, so no worker is EVER classified IDLE"
  [2]="CONTROL: \`FI-14\`'s shipped one-line fix reverted (IDLE dropped from ACTIONABLE_STATES)"
  [3]="the activity probe always reports the instant as fresh, so the threshold is never crossed"
)
#: What a legitimate kill must NAME. A non-zero exit is not a kill — an ImportError exits non-zero too,
#: and that is how four M9 mutants were once "killed" while none had been applied.
declare -A WHY=(
  [1]="IDLE"
  [2]="needs-you population is reconcile"
  [3]="IDLE"
)
declare -A EXPECT=( [1]="KILL" [2]="KILL" [3]="KILL" )

for n in 1 2 3; do
  if run_suite "mut$n" "$EV/mut$n.out"; then
    result=SURVIVED
    detail="the whole suite is GREEN with this mutation in place"
  elif grep -q "${WHY[$n]}" "$EV/mut$n.out"; then
    result=KILLED
    detail="died naming '${WHY[$n]}' — $(grep -m1 -E "^(FAIL|ERROR):" "$EV/mut$n.out" | cut -c1-110)"
  else
    result=WRONG-REASON
    detail="died WITHOUT naming '${WHY[$n]}' — a kill for the wrong reason proves nothing: $(grep -m1 -E "Error|FAIL:" "$EV/mut$n.out" | cut -c1-110)"
  fi
  expected="${EXPECT[$n]}"
  case "$result:$expected" in
    SURVIVED:SURVIVE) mark="AS-PREDICTED" ;;
    KILLED:KILL)      mark="AS-PREDICTED" ;;
    *)                mark="UNEXPECTED" ;;
  esac
  printf '  M-%s  %-12s %-13s %s\n' "$n" "$result" "$mark" "${WHAT[$n]}"
  printf '        %s\n' "$detail"
  printf 'M-%s\t%s\t%s\t%s\n' "$n" "$result" "$mark" "${WHAT[$n]}" >> "$EV/part3-mutations.tsv"
done
echo

# =============================================================== verdict
m1=$(cut -f2 "$EV/part3-mutations.tsv" | sed -n 1p)
m2=$(cut -f2 "$EV/part3-mutations.tsv" | sed -n 2p)
if [ "$m1" = SURVIVED ] && [ "$m2" = KILLED ]; then
  cat <<'TXT'
VERDICT: REPRODUCED, with the control holding.

  The control (M-2) DIED, so this harness can kill: the suite does assert that IDLE is in
  ACTIONABLE_STATES. The detector mutation (M-1) SURVIVED the same harness. So `FI-14`'s detection
  half is guarded only where the TUPLE is asserted, and nowhere at all where the DETECTOR is —
  `_live_state` can be made permanently blind to a stalled worker without one test noticing.

  Part 1 showed the detector does work today. Part 3 shows nothing would tell us if it stopped.
  That is the foundation G-2's actuation was about to be built on top of.
TXT
else
  echo "VERDICT: NOT the predicted pattern (M-1=$m1, M-2=$m2). Read the rows above before designing"
  echo "         anything — the premise this repro exists to establish did not hold."
fi
exit 0
