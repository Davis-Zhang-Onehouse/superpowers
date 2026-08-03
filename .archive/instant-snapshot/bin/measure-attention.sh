#!/usr/bin/env bash
# The attention population, on the REAL store, as a dated artifact.
#
# WHY: `D-9` adds PARKED to ACTIONABLE_STATES — the THIRD change to that tuple (`FI-14` widened it
# 2026-08-02; `G-4` would change it again). The standing constraint is that the counter is measured
# BETWEEN changes, because two semantic changes and one measurement make any regression unattributable.
#
# Read-only. `reconcile` mutates nothing (asserted by its own purity test).
#
# Usage: bash bin/measure-attention.sh before|after
set -uo pipefail
LABEL="${1:?usage: measure-attention.sh before|after}"
REPO="${REPO:-/home/ubuntu/davis_root/superpowers}"
INSTANT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$INSTANT_DIR/evidence/2026-08-03-attention-$LABEL.txt"

{
  echo "# attention population — $LABEL"
  echo "# when: $(TZ=UTC date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "# repo: $(git -C "$REPO" rev-parse --short HEAD)"
  echo "# FLEET_HOME=${FLEET_HOME:-/home/ubuntu/.fleet}"
  echo
  echo "## ACTIONABLE_STATES"
  ( cd "$REPO/fleet" && PYTHONPATH=src python3 -c \
      "from fleet.reconcile import ACTIONABLE_STATES; print(ACTIONABLE_STATES)" )
  echo
  echo "## every subject: state, needs-you, parked"
  ( cd "$REPO/fleet" && PYTHONPATH=src python3 - <<'PY'
import os, pathlib
from fleet.store import Store
from fleet.pool import Pool
from fleet.session import SessionLayer, default_probes
from fleet.reconcile import reconcile, needs_a_human

home = pathlib.Path(os.environ.get("FLEET_HOME", "/home/ubuntu/.fleet"))
sessions = SessionLayer(default_probes())
store, pool = Store(home), Pool(home, alive=sessions.alive)
instants = pathlib.Path(os.environ.get("FLEET_INSTANTS", home / "instants"))
subjects = reconcile(store, pool, sessions, instants)
wants = 0
for s in subjects:
    nah = needs_a_human(s)
    wants += 1 if nah else 0
    print(f"{s.kind}\t{s.identity}\t{s.state}\tneeds_you={nah}\t"
          f"parked={bool((s.evidence or {}).get('parked'))}")
print()
print(f"TOTAL subjects={len(subjects)}  NEEDS-YOU={wants}")
PY
  ) 2>&1
} | tee "$OUT"
echo
echo "captured -> evidence/$(basename "$OUT")"
