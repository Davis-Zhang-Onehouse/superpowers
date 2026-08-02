#!/usr/bin/env bash
# `bin/fleet-view`, asserted against a real store.
#
# The view's whole safety argument is that it COMPUTES NOTHING: it reads `--porcelain` and lays it out. So
# the properties worth testing are the ones that would make that false — that it invents or drops a
# subject, that it disagrees with `fleet` about a state, or that it fails where `fleet` succeeds — plus the
# layout invariants that are easy to break silently (alignment under colour, one column eating the line).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
VIEW="$REPO/bin/fleet-view"
FLEET="$REPO/bin/fleet"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export FLEET_HOME="$TMP/home" FLEET_INSTANTS="$TMP/instants" FLEET_VIEW_WIDTH=100
mkdir -p "$FLEET_HOME" "$FLEET_INSTANTS" "$TMP/slots/wsA" "$TMP/slots/wsB"

fails=0
note() { printf '  %s\n' "$*"; }
check() { if [ "$2" = "$3" ]; then note "ok   $1"; else note "FAIL $1"; note "       wanted [$2] got [$3]"; fails=1; fi; }

# --- an empty store must render, not crash -----------------------------------------------------------
out="$(FLEET_VIEW_WIDTH=100 python3 "$VIEW" 2>&1)"; rc=$?
check "an empty fleet renders" "0" "$rc"
printf '%s' "$out" | grep -q "SUBJECTS" || { note "FAIL no SUBJECTS heading on an empty fleet"; fails=1; }

# --- build a real fleet ------------------------------------------------------------------------------
"$FLEET" enroll --slot "$TMP/slots/wsA" >/dev/null 2>&1
"$FLEET" enroll --slot "$TMP/slots/wsB" >/dev/null 2>&1
W="$("$FLEET" init --base 00000000 --name viewWorker --porcelain 2>/dev/null | awk -F'\t' '$1=="path"{print $2}')"
PYTHONPATH="$REPO/fleet/src" python3 - "$W" <<'PY'
import os, sys
from pathlib import Path
from fleet.store import Record, Store
from fleet.pool import Pool
W = sys.argv[1]; home = Path(os.environ["FLEET_HOME"])
Store(home).write(Record(todo_id="viewworker-07310000", child_instant=W, base_instant="00000000",
    slot="wsA", tmux="dt-viewworker", profile="w", golden="", lineage_base="", title="t",
    dispatched_at="2026-07-31T00:00:00Z", launched_at="2026-07-31T00:00:00Z"))
Pool(home, cwd_probe=lambda p: [], alive=lambda n: False).claim("wsA", "viewworker-07310000",
                                                                "00000000", "dt-viewworker")
PY

# --- THE core property: the view must not disagree with the product ----------------------------------
# Every subject `fleet board --porcelain` reports must appear, with the SAME state. A view that quietly
# drops a row is worse than no view: the row it drops is the one nobody then chases.
while IFS=$'\t' read -r ident kind state rest; do
  [ -n "${ident:-}" ] || continue
  v="$(FLEET_VIEW_WIDTH=200 python3 "$VIEW" board --wide 2>/dev/null)"
  printf '%s' "$v" | grep -q -- "$ident" \
    || { note "FAIL subject $ident is in porcelain but not in the view"; fails=1; }
  printf '%s' "$v" | grep -q -- "$state" \
    || { note "FAIL state $state for $ident is in porcelain but not in the view"; fails=1; }
done < <("$FLEET" board --porcelain 2>/dev/null)
note "ok   every subject and state in porcelain appears in the view"

# --- the view must never mutate anything -------------------------------------------------------------
before="$(find "$FLEET_HOME" "$FLEET_INSTANTS" -type f -printf '%p %s %T@\n' 2>/dev/null | sort)"
python3 "$VIEW" >/dev/null 2>&1
python3 "$VIEW" leases >/dev/null 2>&1
after="$(find "$FLEET_HOME" "$FLEET_INSTANTS" -type f -printf '%p %s %T@\n' 2>/dev/null | sort)"
check "rendering writes nothing" "$before" "$after"

# --- alignment is computed on VISIBLE width, so colour cannot skew it --------------------------------
# Same data, colour forced on and off: the de-ANSI'd output must be byte-identical. This is the failure
# that looks fine on the author's terminal and ragged on everyone else's.
plain="$(FLEET_VIEW_WIDTH=100 NO_COLOR=1 python3 "$VIEW" leases 2>/dev/null)"
colored="$(FLEET_VIEW_WIDTH=100 python3 - <<PY 2>/dev/null
import runpy, sys
sys.argv = ["fleet-view", "leases"]
import builtins
runpy.run_path("$VIEW", run_name="__main__")
PY
)"
stripped="$(printf '%s' "$colored" | sed 's/\x1b\[[0-9;]*m//g')"
check "colour does not change layout" "$plain" "$stripped"

# --- no line may exceed the width, EXCEPT one that cannot be broken -----------------------------------
# A single unbreakable token -- an absolute instant path -- is allowed to run long on purpose. Wrapping a
# path mid-directory makes it un-copy-pasteable, which costs more than a ragged line; the terminal will
# soft-wrap it. Anything with a space in it had the chance to wrap and did not, so that IS a defect.
long="$(FLEET_VIEW_WIDTH=100 NO_COLOR=1 python3 "$VIEW" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' \
        | awk '{ line=$0; sub(/^ +/, "", line);
                 if (length($0) > 100 && line ~ / /) c++ } END { print c+0 }')"
check "no wrappable line overflows the terminal width" "0" "$long"

# --- path elision keeps the tail ----------------------------------------------------------------------
el="$(PYTHONPATH="$REPO/fleet/src" python3 - <<PY
import runpy
m = runpy.run_path("$VIEW")
print(m["shorten"]("/a/very/long/prefix/that/goes/on/00000000-07310348-inflight-append-coordinator", 40))
PY
)"
case "$el" in
  *coordinator) note "ok   a long path is elided from the left, keeping the identifying tail" ;;
  *) note "FAIL path elision lost the tail: $el"; fails=1 ;;
esac

# --- the releases view renders, and never truncates a reason -----------------------------------------
# `reason` is operator free text — the one field somebody typed BECAUSE it would otherwise be lost. Every
# table in `fleet-view` elides a value to fit (35% of the width per column, or the note budget), so the
# history is deliberately rendered as a LIST instead, where a long value wraps rather than being cut.
#
# Two things this assertion has to get right, or it certifies nothing:
#
#  * WRAPPED IS NOT TRUNCATED. A grep for a phrase inside the reason fails the moment the wrap lands
#    between its two words, which says nothing about whether anything was lost. So the rendering is
#    flattened to one whitespace-collapsed line first, and the WHOLE reason must survive in it.
#  * IT MUST BE A REASON ONLY THE HISTORY CARRIES. `release-status` re-reports the most recent reason, so
#    checking that one would pass even if the history section cut every row it drew. The older row's
#    reason appears in the history and nowhere else, which is why the fixture has two rows.
RELDIR="$TMP/releases"
mkdir -p "$RELDIR/fleet-v0.1.0/.release"
printf 'version\t0.1.0\ncut_at\t2026-08-02T10:00:00Z\n' > "$RELDIR/fleet-v0.1.0/.release/MANIFEST.tsv"
printf 'RELEASED\n' > "$RELDIR/fleet-v0.1.0/.release/STATE"
OLD_LONG="promoted after the full suite went green on the export, and after the two flake reruns that C4 asks for"
LONG="harvest wedged on a leased slot and the coordinator could not clear it without a manual reap, so we went back"
printf 'ts\taction\tversion\tfrom_version\tactor\thost\treason\tevidence\n' > "$RELDIR/RELEASE-HISTORY.tsv"
printf '2026-08-02T10:30:00Z\tDEPLOY\t0.2.0\t0.1.0\tdavis@onehouse.ai\tbox\t%s\t-\n' "$OLD_LONG" \
  >> "$RELDIR/RELEASE-HISTORY.tsv"
printf '2026-08-02T11:00:00Z\tROLLBACK\t0.1.0\t0.2.0\tdavis@onehouse.ai\tbox\t%s\t-\n' "$LONG" \
  >> "$RELDIR/RELEASE-HISTORY.tsv"

rv="$(FLEET_RELEASES="$RELDIR" FLEET_VIEW_WIDTH=100 NO_COLOR=1 python3 "$VIEW" releases 2>&1)"; rc=$?
check "the releases view renders" "0" "$rc"
printf '%s' "$rv" | grep -q "0.1.0" || { note "FAIL the releases view omits the release"; fails=1; }
printf '%s' "$rv" | grep -q "ROLLBACK" \
  || { note "FAIL the releases view omits the history"; fails=1; }
flat="$(printf '%s' "$rv" | tr '\n' ' ' | tr -s ' ')"
case "$flat" in
  *"$OLD_LONG"*) note "ok   a long history reason reaches the reader whole, wrapped and not cut" ;;
  *) note "FAIL a long reason was truncated — list form exists so it is not"; fails=1 ;;
esac

# The releases view must not disagree with the product either: every version `release-list --porcelain`
# reports has to appear. Same property as the board check above, applied to the surface that just landed.
while IFS=$'\t' read -r ver state rest; do
  [ -n "${ver:-}" ] || continue
  printf '%s' "$rv" | grep -q -- "$ver" \
    || { note "FAIL release $ver is in porcelain but not in the view"; fails=1; }
done < <(FLEET_RELEASES="$RELDIR" "$FLEET" release-list --porcelain 2>/dev/null)
note "ok   every release in porcelain appears in the releases view"

# Colour cannot skew the releases layout any more than it may skew the leases table.
rplain="$(FLEET_RELEASES="$RELDIR" FLEET_VIEW_WIDTH=100 NO_COLOR=1 python3 "$VIEW" releases 2>/dev/null)"
rcolored="$(FLEET_RELEASES="$RELDIR" FLEET_VIEW_WIDTH=100 python3 - <<PY 2>/dev/null
import runpy, sys
sys.argv = ["fleet-view", "releases"]
runpy.run_path("$VIEW", run_name="__main__")
PY
)"
rstripped="$(printf '%s' "$rcolored" | sed 's/\x1b\[[0-9;]*m//g')"
check "colour does not change the releases layout" "$rplain" "$rstripped"

# --- an unknown view is REFUSED, exit 2 ---------------------------------------------------------------
# `fleet` answers an unknown verb with exit 2 and the list; this viewer used to fall through every branch
# and exit 0. That is why `check "the … view renders" "0" "$rc"` passed for views that did not exist yet —
# the assertion could not tell "rendered" from "silently did nothing".
python3 "$VIEW" totalNonsense >/dev/null 2>"$TMP/unknown.err"; rc=$?
check "an unknown view exits 2" "2" "$rc"
grep -q "is not a fleet-view view" "$TMP/unknown.err" \
  || { note "FAIL the refusal does not name the problem"; fails=1; }
grep -q "releases" "$TMP/unknown.err" \
  || { note "FAIL the refusal does not list the views"; fails=1; }
for v in all board leases roadmap releases; do
  python3 "$VIEW" "$v" >/dev/null 2>&1 || { note "FAIL known view '$v' no longer exits 0"; fails=1; }
done
note "ok   every declared view still exits 0"

if [ "$fails" = 0 ]; then
  echo "PASS: fleet-view renders every subject porcelain reports with the same state, writes nothing, lays out identically with and without colour, keeps every WRAPPABLE line inside the terminal width (an unbreakable path is allowed to run long, because cutting it makes it un-copy-pasteable), elides long paths from the left so the identifying tail survives, and renders the release history in list form so a long reason reaches the reader whole"
  exit 0
fi
echo FAIL
exit 1
