#!/usr/bin/env bash
# Which subjects would `fleet nudge` actually send to?  (asked by the operator, 2026-08-03)
#
# THE QUESTION. A child instant that legitimately needs a decision asks a question and waits. The real
# unblock is the COORDINATOR answering — never a "continue where you left off", which at best wastes a turn
# and at worst makes the child guess. So: would the designed nudge verb hit a parked child?
#
# Answering it by reading `_live_state` is not good enough. `park` and the idle threshold interact inside
# one if/elif chain, and the interaction is the whole answer. So this constructs each situation with the
# package's own fixture and prints what `reconcile` actually yields.
#
# Four situations, hermetic, no tmux and no claude:
#   1  idle, not parked                     — the case the nudge exists for
#   2  parked with a question, instant FRESH — the child just asked
#   3  parked with a question, instant IDLE  — the child asked and has been waiting > threshold
#   4  awaiting-ci, instant IDLE            — a legitimate long wait that must never be nudged
#
# Run:   bash bin/probe-nudge-eligibility.sh
set -uo pipefail
REPO="${REPO:-/home/ubuntu/davis_root/superpowers}"
INSTANT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$INSTANT_DIR/evidence/2026-08-03-nudge-eligibility.txt"

PYTHONPATH="$REPO/fleet/src:$REPO/fleet/tests" python3 - <<'PY' 2>&1 | tee "$LOG"
import os, pathlib, time
from test_cli import Fleet, IDLE_PANE, BUSY_PANE
from fleet.reconcile import (reconcile, needs_a_human, ACTIONABLE_STATES,
                             IDLE, BLOCKED, PARKED, AWAITING_CI)
from fleet.store import Declarations
import subprocess

head = subprocess.run(["git", "-C", "/home/ubuntu/davis_root/superpowers", "rev-parse", "--short", "HEAD"],
                      capture_output=True, text=True).stdout.strip()
print(f"# nudge-eligibility probe — repo @ {head}")
print(f"# ACTIONABLE_STATES = {ACTIONABLE_STATES}   (PARKED actionable? {PARKED in ACTIONABLE_STATES})")
print()

fleet = Fleet()
plain   = fleet.worker("plain-idle",   slot="ws1", pane=IDLE_PANE)
asked   = fleet.worker("parked-fresh", slot="ws2", pane=IDLE_PANE)
waiting = fleet.worker("parked-idle",  slot="ws3", pane=IDLE_PANE)
ci      = fleet.worker("awaiting-ci",  slot="ws4", pane=IDLE_PANE)

QUESTION = "which baseline is the ruler? I cannot proceed without a decision"

def instant_of(name):
    for rec in fleet.store.all():
        p = pathlib.Path(rec.child_instant)
        if name in p.name:
            return p
    raise SystemExit(f"no instant matching {name}")

def backdate(instant, seconds):
    """Age every path `_idle_for` reads. Written LAST, so a declaration does not refresh the mtime."""
    old = time.time() - seconds
    paths = [instant] + list(instant.iterdir())
    for child in list(instant.iterdir()):
        if child.name == ".fleet" and child.is_dir():
            paths += list(child.iterdir())
    for path in paths:
        os.utime(path, (old, old))

# declare FIRST, then backdate — otherwise writing .fleet/declare.json makes the instant look fresh
Declarations(instant_of("parked-fresh")).park(QUESTION)
Declarations(instant_of("parked-idle")).park(QUESTION)
Declarations(instant_of("awaiting-ci")).set_phase("awaiting-ci")

backdate(instant_of("plain-idle"), 2700)
backdate(instant_of("parked-idle"), 2700)
backdate(instant_of("awaiting-ci"), 2700)
# parked-fresh deliberately NOT backdated

subjects = {s.identity.split("-0730")[0]: s
            for s in reconcile(fleet.store, fleet.pool, fleet.sessions, fleet.instants, idle_after_s=1800)}

CASES = [
    ("1 idle, not parked",              "plain-idle",   "NUDGE — this is what the verb is for"),
    ("2 parked+question, fresh",        "parked-fresh", "COORDINATOR must answer"),
    ("3 parked+question, idle >30min",  "parked-idle",  "COORDINATOR must answer — NEVER nudge"),
    ("4 awaiting-ci, idle >30min",      "awaiting-ci",  "leave alone"),
]

print(f"{'case':<34} {'state':<12} {'needs_a_human':<14} {'parked?':<8} would-be-nudged")
print("-" * 104)
verdict_rows = []
for label, key, want in CASES:
    s = subjects.get(key)
    if s is None:
        print(f"{label:<34} (subject missing)")
        continue
    # `parked` is NOT a Subject attribute — it lives in `subject.evidence["parked"]` (reconcile.py:233).
    # The first version of this probe used getattr(s, "parked", ""), which is always "", so every row read
    # parked=False and the verdict came back "no parked subject would be nudged" — vacuously. A probe
    # written to look for green-for-the-wrong-reason, green for the wrong reason. Fixed and kept on the
    # record, because it is the same class as `G-10` and it took one run to catch.
    parked = bool((s.evidence or {}).get("parked") or "")
    # The design as presented: NUDGEABLE_STATES = (IDLE,). Nothing about park in it.
    nudged_by_design = (s.state == IDLE)
    verdict_rows.append((label, key, s.state, needs_a_human(s), parked, nudged_by_design, want))
    print(f"{label:<34} {s.state:<12} {str(needs_a_human(s)):<14} {str(parked):<8} "
          f"{'YES' if nudged_by_design else 'no'}")
print()
for label, key, state, nah, parked, nudged, want in verdict_rows:
    print(f"{label}")
    print(f"    note: {subjects[key].note!r}")
    print(f"    want: {want}")
    print()

bad = [r for r in verdict_rows if r[4] and r[5]]     # parked AND would be nudged
print("=" * 104)
if bad:
    print("VERDICT: THE DESIGN AS PRESENTED IS WRONG for these cases:")
    for label, key, state, nah, parked, nudged, want in bad:
        print(f"  - {label}: parked with a question, state={state}, and `NUDGEABLE_STATES = (IDLE,)`")
        print(f"    would send it a nudge. The park is APPENDED to the note, not reflected in the STATE,")
        print(f"    so a state-only filter cannot see it.")
    print()
    print("  The operator's concern is CONFIRMED, and it is not hypothetical: a child that correctly")
    print("  declared a question and waited past the idle threshold is indistinguishable, BY STATE, from")
    print("  a child that simply stopped.")
else:
    print("VERDICT: no parked subject would be nudged by a state-only filter.")

invisible = [r for r in verdict_rows if r[4] and not r[3]]   # parked and NOT needs_a_human
if invisible:
    print()
    print("AND A SECOND FINDING — parked subjects that nothing surfaces at all:")
    for label, key, state, nah, parked, nudged, want in invisible:
        print(f"  - {label}: state={state}, needs_a_human={nah}. The child is waiting on an answer and")
        print(f"    does NOT appear in the 'N needs you' population. Nothing routes the question anywhere.")
PY
