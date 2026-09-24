#!/usr/bin/env bash
# §H — Roadmap.  plans/plan-6-integration-tests.md lines 191-200.
#
# Written to catch a defect already found by hand while designing on top of this protocol: the CLI collapses
# `propose`'s TWO instants — the roadmap holder and the PROPOSER — into one `--instant` flag, so
#   * a worker cannot propose at all (the milestone is looked up in the worker's own empty roadmap), and
#   * every proposal is attributed to the roadmap's own instant, losing who asked.
# The library is right: `Roadmap.propose(instant, …)` takes the proposer separately, and
# `tests/test_roadmap.py::TestSingleWriter` asserts `p.instant == worker`. Only the wiring is wrong, and
# `H2` is the case Plan 6 already specified for exactly this — it had just never been run.
#
# H5–H8 are GONE, with the reason recorded at their old position: `reassign` and the deferred-owner
# machinery were removed from the model (`SD-5`). An orphan is now a documented issue plus a milestone, and
# a milestone names no owner it has to invent — so `SI-24` ("reassign has no verb") dissolved rather than
# being fixed, which is the cheaper of the two resolutions.
#
# Run: bash fleet/it/run-H.sh
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
it_own_cases 'H[0-9]+[a-z]?|ISOLATION-H-(enter|leave)'   # incl. H5-H8, so a re-run RETIRES their old rows

it_section H

# H10 performs a REAL dispatch, which names its session `dt-<name>` — and that does NOT match the harness's
# `itfleet-<SECTION>` prefix, so `it_cleanup_tmux` never sees it. Measured after the fact: `itfleet-H` was
# still running `dt-joinedworker` long after the section finished. Harmless (a private socket the live server
# cannot see) and still a leak, one per run. The private SERVER is therefore torn down outright at exit.
trap 'it_cleanup_tmux; tmux -L "$IT_TMUX_SOCKET" kill-server 2>/dev/null' EXIT
OUT="$EV/out"; rm -rf "$OUT"; mkdir -p "$OUT"
export FLEET_INSTANTS="$EV/instants"; rm -rf "$FLEET_INSTANTS"; mkdir -p "$FLEET_INSTANTS"
it_fresh_store            # §H was measured inheriting a previous run's WIP-cap holder (H10)
TAG="h$$"

bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2

h_init() {                       # h_init <name> -> prints the instant path
  local out="$OUT/init-$1.out"
  fleet init --base 00000000 --name "$1" --porcelain > "$out" 2>&1
  awk -F'\t' '$1=="path"{print $2; exit}' "$out"
}
py() { python3 - "$@"; }         # a library driver; §C's precedent for verbs that do not exist

COORD="$(h_init "coord$TAG")"
WORKER="$(h_init "worker$TAG")"
[ -d "$COORD" ] && [ -d "$WORKER" ] || { echo "init produced no instants; nothing below is a verdict" >&2; exit 2; }

# ==================================================================================================
# H1 — three milestones with a dependency chain: `ready` names ONLY the one whose deps have LANDED,
#      and every other row NAMES ITS BLOCKER.
# ==================================================================================================
#: m1 has no deps and is done -> m2's dep has LANDED. m3 depends on m2, which has NOT landed. So exactly
#: one milestone is ready, and the two that are not each have a nameable blocker. A chain rather than a
#: pair, because with only two the "names its blocker" half can pass by naming the single obvious one.
#:
#: Seeded through `fleet milestone`, NOT through a python driver. It was a driver until `SI-26`, under the
#: comment "a library driver; §C's precedent for verbs that do not exist" — and that was the whole defect:
#: `Roadmap.add` had no verb, so the mechanism `SD-5` made load-bearing was unreachable from a command line
#: and §H proved a property of the library while saying nothing about the coordinator's actual surface.
{
  fleet milestone --instant "$COORD" --id m1 --title "enabling" --status "done" \
        --evidence "evidence/INDEX.md" --porcelain
  fleet milestone --instant "$COORD" --id m2 --title "middle" --dep m1 --porcelain
  fleet milestone --instant "$COORD" --id m3 --title "tail"   --dep m2 --porcelain
} > "$OUT/H1-seed.txt" 2>&1
echo "seeded m1(done) <- m2 <- m3 through the CLI" >> "$OUT/H1-seed.txt"
cat "$OUT/H1-seed.txt"
fleet roadmap --instant "$COORD" --porcelain > "$OUT/H1-roadmap.tsv" 2>&1
py "$COORD" > "$OUT/H1-ready.txt" 2>&1 <<'PY'
import pathlib, sys
from fleet.roadmap import Roadmap
rm = Roadmap(pathlib.Path(sys.argv[1]))
print("ready:", [m.id for m in rm.ready()])
for row in rm.report():
    if row.kind == "not-ready":
        print(f"not-ready {row.subject}: blocker={row.detail!r}")
PY
cat "$OUT/H1-ready.txt"
h1_ready="$(awk -F': ' '/^ready:/{print $2}' "$OUT/H1-ready.txt")"
h1_m2_named=0; grep -q "not-ready m2:.*m1" "$OUT/H1-ready.txt" && h1_m2_named=1
h1_m3_named=0; grep -q "not-ready m3:.*m2" "$OUT/H1-ready.txt" && h1_m3_named=1
if [ "$h1_ready" = "['m2']" ] && [ "$h1_m3_named" = 1 ]; then
  it_pass H1 "fleet/it/H/out/H1-ready.txt" \
    "three milestones in a chain m1(done)<-m2<-m3: ready is exactly ['m2'] — the one whose dep has LANDED, not merely exists — and m3's row NAMES m2 as its blocker. A chain rather than a pair on purpose: with two milestones 'names its blocker' can pass by naming the only candidate"
elif [ "$h1_ready" = "['m2']" ]; then
  it_fail H1 "fleet/it/H/out/H1-ready.txt" \
    "readiness is right (['m2']) but a not-ready row does not name its blocker: m2_named=$h1_m2_named m3_named=$h1_m3_named — see the file"
else
  it_fail H1 "fleet/it/H/out/H1-ready.txt" \
    "ready=$h1_ready, wanted ['m2'] (m1 is done so m2's dep has landed; m3's has not)"
fi

# ==================================================================================================
# H2 — `propose` FROM THE WORKER'S INSTANT: the roadmap is unchanged, and the proposal is listed.
#      This is the case that catches the CLI's collapsed-instants defect.
# ==================================================================================================
before_bytes="$(sha256sum "$COORD/.fleet/roadmap.json" | cut -d' ' -f1)"
before_mtime="$(stat -c '%Y.%N' "$COORD/.fleet/roadmap.json")"

# The worker proposes a status for a milestone in the COORDINATOR's roadmap. `--instant` is documented as
# "the proposing instant", so the worker names ITSELF; the roadmap it is proposing INTO is the coordinator's.
fleet propose --instant "$WORKER" --to "$COORD" --milestone m2 --status "done" \
      --evidence "evidence/INDEX.md" --porcelain > "$OUT/H2-propose.out" 2>&1
h2_rc=$?
cat "$OUT/H2-propose.out"

after_bytes="$(sha256sum "$COORD/.fleet/roadmap.json" | cut -d' ' -f1)"
after_mtime="$(stat -c '%Y.%N' "$COORD/.fleet/roadmap.json")"
py "$COORD" "$WORKER" > "$OUT/H2-attribution.txt" 2>&1 <<'PY'
import json, pathlib, sys
coord, worker = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
p = coord / ".fleet" / "proposals.json"
data = json.loads(p.read_text()) if p.is_file() else {"pending": []}
for entry in data.get("pending", []):
    print(f"pending milestone={entry['milestone']} status={entry['status']} instant={entry['instant']}")
print("worker was:", worker)
print("attributed_to_worker:", any(e["instant"] == str(worker) for e in data.get("pending", [])))
PY
cat "$OUT/H2-attribution.txt"
h2_unchanged=0; [ "$before_bytes" = "$after_bytes" ] && [ "$before_mtime" = "$after_mtime" ] && h2_unchanged=1
h2_listed=0;    grep -q 'pending milestone=m2' "$OUT/H2-attribution.txt" && h2_listed=1
h2_attributed=0; grep -q '^attributed_to_worker: True$' "$OUT/H2-attribution.txt" && h2_attributed=1
if [ "$h2_rc" = 0 ] && [ "$h2_unchanged" = 1 ] && [ "$h2_listed" = 1 ] && [ "$h2_attributed" = 1 ]; then
  it_pass H2 "fleet/it/H/out/H2-attribution.txt" \
    "a WORKER proposed into the coordinator's roadmap: roadmap.json byte-identical AND mtime-identical (propose must not even rewrite identical bytes), the proposal is listed as pending, and it is attributed to the WORKER's instant rather than to the roadmap's own — so the coordinator's inbox can say who asked"
elif [ "$h2_rc" != 0 ]; then
  it_fail H2 "fleet/it/H/out/H2-propose.out" \
    "a worker cannot propose at all (rc=$h2_rc): $(head -1 "$OUT/H2-propose.out" | cut -c1-200)"
else
  it_fail H2 "fleet/it/H/out/H2-attribution.txt" \
    "rc=$h2_rc roadmap_unchanged=$h2_unchanged proposal_listed=$h2_listed attributed_to_worker=$h2_attributed — attribution=0 means every proposal claims to come from the roadmap's own instant, so the inbox cannot say who asked"
fi

# ==================================================================================================
# H3 — `apply` changes the status.   H4 — `apply` with empty evidence ⇒ exit 2.
# ==================================================================================================
fleet apply --instant "$COORD" --milestone m2 --porcelain > "$OUT/H3-apply.out" 2>&1
h3_rc=$?
py "$COORD" > "$OUT/H3-after.txt" 2>&1 <<'PY'
import pathlib, sys
from fleet.roadmap import Roadmap
rm = Roadmap(pathlib.Path(sys.argv[1]))
print("m2 status:", rm.milestone("m2").status)
print("m2 evidence:", rm.milestone("m2").evidence)
print("pending now:", [(p.milestone, p.instant.split('/')[-1]) for p in rm.proposals()])
print("ready now:", [m.id for m in rm.ready()])
PY
cat "$OUT/H3-after.txt"
if [ "$h3_rc" = 0 ] && grep -q '^m2 status: done$' "$OUT/H3-after.txt" \
   && grep -q '^pending now: \[\]$' "$OUT/H3-after.txt" && grep -q "^ready now: \['m3'\]$" "$OUT/H3-after.txt"; then
  it_pass H3 "fleet/it/H/out/H3-after.txt" \
    "apply moved m2 to done, carried the proposal's evidence onto the milestone, CONSUMED the proposal (pending is now empty, so replaying the inbox cannot apply it twice), and readiness recomputed — m3 is now ready because its dep has LANDED. Four consequences of one call, asserted together"
else
  it_fail H3 "fleet/it/H/out/H3-after.txt" \
    "rc=$h3_rc; wanted m2=done, pending=[], ready=['m3'] — see the file"
fi

# H4: empty evidence. Asserted at the LIBRARY, because the CLI's --evidence is repeatable and an empty
# string is the reachable shape of "empty" there; both doors are checked.
fleet propose --instant "$WORKER" --to "$COORD" --milestone m3 --status "done" --evidence "" \
      > "$OUT/H4-cli.out" 2>&1
h4_cli_rc=$?
py "$COORD" > "$OUT/H4-lib.out" 2>&1 <<'PY'
import pathlib, sys
from fleet.roadmap import Roadmap
from fleet.errors import FleetError
rm = Roadmap(pathlib.Path(sys.argv[1]))
for label, ev in (("empty list", []), ("blank string", [""]), ("whitespace", ["   "])):
    try:
        rm.propose(pathlib.Path("/x"), "m3", "done", ev)
        print(f"{label}: ACCEPTED (wrong)")
    except FleetError as exc:
        print(f"{label}: refused exit={exc.exit_code} {type(exc).__name__}")
PY
cat "$OUT/H4-lib.out"
h4_lib_ok=$(grep -c 'refused exit=2' "$OUT/H4-lib.out")
if [ "$h4_cli_rc" = 2 ] && [ "$h4_lib_ok" = 3 ]; then
  it_pass H4 "fleet/it/H/out/H4-lib.out" \
    "empty evidence is refused with exit 2 at BOTH doors: through the CLI (rc=$h4_cli_rc) and at the library for all three shapes of empty — [] , [\"\"] and whitespace-only. A proposal with no evidence is a claim, and the producer refuses it"
else
  it_fail H4 "fleet/it/H/out/H4-lib.out" \
    "cli_rc=$h4_cli_rc (want 2), library refusals=$h4_lib_ok of 3 — see the files"
fi

# ==================================================================================================
# H5 / H6 / H7 / H8 — REMOVED, not skipped, and not silently dropped.
#
# Plan 6 specifies four cases over `reassign` and the deferred-owner alarm. That whole concept has been
# REMOVED from the model (`SD-5`), so these cases have no feature to test — which is a different state from
# "cannot be asserted" (`K6`) and from "unrunnable as specified" (`D2`, `D9`). A SKIP row would claim the
# property still exists and is merely unproven; there is no property.
#
# They are recorded here rather than deleted because the four of them passed, at 8/8, on the code that was
# then removed — including `H7`, which showed that claiming a deferred owner cleared its row. That evidence
# is real and is in git; what it proves is that the deleted machinery worked, not that anything is missing.
#
# What replaced them: an item that outlives its effort becomes a documented issue in the workspace plus a
# MILESTONE on the roadmap, so `H1`'s readiness/blocker assertions are the coverage. `FI-7`'s failure — a
# reassignment naming an instant that exists nowhere — is now unrepresentable rather than detected, so
# there is nothing left for a case to assert about it.
#
# Plan 6 §H is the parent's file and the parent is a live writer, so the divergence is named here and in
# my ISSUES register (`SD-0`), not edited there.

# ==================================================================================================
# H9 — `SD-5`'s CARRY-ACROSS IS REACHABLE FROM A COMMAND LINE.  (`SI-26`)
#
#      `SD-5` removed reassignment on the argument that an item outliving its effort becomes "a documented
#      issue in the workspace plus a milestone on the roadmap, and the coordinator dispatches it later like
#      any other milestone." That claim has two halves and only the first was ever measured: the roadmap
#      COULD hold such a milestone (H1), but nothing showed a coordinator could PUT one there. `Roadmap.add`
#      was correct, locked and tested with no verb attached — `SI-19`'s shape for the third time, introduced
#      by the same commit that made it load-bearing.
#
#      So this case runs the full loop with nothing but `fleet`: coordinator raises the carried item, a
#      worker proposes it done against the coordinator's roadmap, the coordinator applies. If any step needs
#      python, `SD-5` is prose and not a mechanism.
# ==================================================================================================
h9_rc=0
{
  echo "== 1. the coordinator raises the carried item, depending on the unfinished m3 =="
  fleet milestone --instant "$COORD" --id carried --title "an item that outlived its effort" \
        --dep m3 --porcelain || h9_rc=1
  echo "== 2. its blocker is NAMED, so it cannot be silently dispatched early =="
  fleet roadmap --instant "$COORD" --porcelain | grep '^not-ready.carried' || h9_rc=1
  echo "== 3. m3 lands, through the two-party protocol =="
  fleet propose --instant "$WORKER" --to "$COORD" --milestone m3 --status "done" \
        --evidence "evidence/INDEX.md" --porcelain || h9_rc=1
  fleet apply --instant "$COORD" --milestone m3 --porcelain || h9_rc=1
  echo "== 4. and NOW the carried item is ready — derived, nobody set a flag =="
  fleet roadmap --instant "$COORD" --porcelain || h9_rc=1
} > "$OUT/H9-carry.out" 2>&1
h9_ready_after=0
# The carried item is ready iff, after its dep landed, it is no longer a not-ready subject AND it IS a `ready`
# row. The positive half is `B04`: before it, ready milestones had no row, so this could only be proved by an
# absence — which a roadmap that printed nothing at all would also have satisfied.
grep -q '^not-ready.carried' "$OUT/H9-carry.out" && h9_step2=1 || h9_step2=0
awk '/^== 4\./{seen=1} seen && /^not-ready\tcarried\t/{bad=1} seen && /^ready\tcarried\t/{good=1}
     END{exit (bad || !good)?1:0}' "$OUT/H9-carry.out" \
  && h9_ready_after=1
h9_added=0; grep -q '^added.carried' "$OUT/H9-carry.out" && h9_added=1
if [ "$h9_rc" = 0 ] && [ "$h9_added" = 1 ] && [ "$h9_step2" = 1 ] && [ "$h9_ready_after" = 1 ]; then
  it_pass H9 "fleet/it/H/out/H9-carry.out" \
    "SD-5's replacement for reassignment is a MECHANISM, not prose: the whole carry-across runs on \`fleet\` alone — the coordinator raises the carried item with \`fleet milestone\` (which did not exist until SI-26; §H seeded via python and so proved nothing about the coordinator's surface), its blocker is named while the dep is unlanded, a worker lands the dep through propose/apply, and the item becomes ready by DERIVATION with nobody setting a flag"
else
  it_fail H9 "fleet/it/H/out/H9-carry.out" \
    "the carry-across does not run from a command line: rc=$h9_rc added=$h9_added blocker-named=$h9_step2 ready-after-dep-landed=$h9_ready_after"
fi

# ==================================================================================================
# H10 — THE MILESTONE<->INSTANT JOIN, END TO END, THROUGH THE CLI ONLY.  (`SI-27`)
#
#      §H proved the coordinator's roadmap could hold work and that a worker could report INTO it. What it
#      never asked was the question a coordinator actually has when three workers are out: WHICH ONE IS ON
#      WHICH MILESTONE. Measured while designing that loop:
#        * `dispatch` recorded no milestone and `Record` had no field for one, so `board` showed N workers,
#          `roadmap` showed N milestones, and nothing connected them;
#        * `propose` defaulted its destination to the PROPOSER, so a worker that did not name `--to` wrote
#          into its own inbox — coordinator 0 pending, worker 1 pending, and no error anywhere; and
#        * `harvest` then applied that proposal into the worker's own roadmap and closed the folder.
#
#      This case dispatches a REAL worker (the `bin/claude` stub, on the private section socket) and asserts
#      the join from all three sides that have to agree: the record, the child's origin.json, and the
#      milestone's owner.
# ==================================================================================================
h10_rc=0
H10="$OUT/h10"; mkdir -p "$H10"
# The stub ahead of the real `claude` on PATH. `bin/claude`'s own header says why this is mandatory: there is
# no --no-launch flag, so a real dispatch runs whatever `claude` resolves to.
PATH="$IT_ROOT/bin:$PATH"; export PATH
cp -r "$INSTANT/tests/fixtures/profiles/workerCompliant" "$H10/profile"
( mkdir -p "$H10/slot" && cd "$H10/slot" && git init -q . && git commit -q --allow-empty -m base ) >/dev/null 2>&1
{
  echo "== a fresh READY milestone for this case (no deps) =="
  fleet milestone --instant "$COORD" --id j1 --title "work with an owner" --porcelain || h10_rc=1
  fleet set-golden --path "$H10/slot" --porcelain || h10_rc=1
  fleet enroll --slot "$H10/slot" --porcelain || h10_rc=1
  echo "== dispatch NAMING the milestone and the dispatching coordinator =="
  fleet dispatch --profile "$H10/profile" --title "joinedWorker" --base 00000000 --optype append \
        --from "$COORD" --milestone j1 --porcelain || h10_rc=1
} > "$H10/dispatch.out" 2>&1
J_CHILD="$(awk -F'\t' '$1=="instant"{print $2}' "$H10/dispatch.out")"

# Side 1: the RECORD names the milestone.  Side 2: the CHILD records its coordinator and milestone.
# Side 3: the MILESTONE names the instant executing it — and its STATUS is untouched, because `apply` is
# the only thing allowed to move a status.
python3 - "$COORD" "$J_CHILD" > "$H10/join.txt" 2>&1 <<'PY'
import os, pathlib, sys
from fleet import origin as origin_mod
from fleet.roadmap import Roadmap
from fleet.store import Store
coord, child = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
#: Through the STORE, not by guessing where records sit relative to instants: FLEET_HOME and FLEET_INSTANTS
#: are independent, and a hand-built path here would assert a layout instead of reading the registry.
matched = [r for r in Store(pathlib.Path(os.environ["FLEET_HOME"])).all() if r.child_instant == str(child)]
print("record.milestone:", matched[0].milestone if matched else "NO-RECORD-FOUND")
recorded = origin_mod.read(child)
print("origin.coordinator_matches:", recorded is not None and recorded.coordinator == str(coord))
print("origin.milestone:", recorded.milestone if recorded else None)
m = Roadmap(coord).milestone("j1")
print("milestone.owner_is_child:", m.owner == str(child))
print("milestone.status:", m.status)
PY
cat "$H10/join.txt"

# A second dispatch onto the same milestone must be refused: two instants on one milestone is the failure
# the join exists to make visible.
fleet dispatch --profile "$H10/profile" --title "secondWorker" --base 00000000 --optype append \
      --from "$COORD" --milestone j1 --cap 5 > "$H10/second.out" 2>&1
h10_second_rc=$?

# And the worker's report reaches the COORDINATOR with no --to, which is the half that was silently lost.
before_pending="$(python3 -c "
import json,pathlib,sys
p=pathlib.Path(sys.argv[1])/'.fleet'/'proposals.json'
print(len(json.loads(p.read_text())['pending']) if p.is_file() else 0)" "$COORD")"
fleet propose --instant "$J_CHILD" --milestone j1 --status "done" --evidence "evidence/INDEX.md" \
      --porcelain > "$H10/propose.out" 2>&1
after_pending="$(python3 -c "
import json,pathlib,sys
p=pathlib.Path(sys.argv[1])/'.fleet'/'proposals.json'
print(len(json.loads(p.read_text())['pending']) if p.is_file() else 0)" "$COORD")"
worker_pending="$(python3 -c "
import json,pathlib,sys
p=pathlib.Path(sys.argv[1])/'.fleet'/'proposals.json'
print(len(json.loads(p.read_text())['pending']) if p.is_file() else 0)" "$J_CHILD")"
fleet board --porcelain > "$H10/board.tsv" 2>&1

h10_rec=0;   grep -q '^record.milestone: j1$'            "$H10/join.txt" && h10_rec=1
h10_orig=0;  grep -q '^origin.coordinator_matches: True$' "$H10/join.txt" \
             && grep -q '^origin.milestone: j1$'          "$H10/join.txt" && h10_orig=1
h10_own=0;   grep -q '^milestone.owner_is_child: True$'   "$H10/join.txt" && h10_own=1
h10_stat=0;  grep -q '^milestone.status: blocked$'        "$H10/join.txt" && h10_stat=1
h10_dbl=0;   [ "$h10_second_rc" != 0 ] && grep -qi 'already claimed' "$H10/second.out" && h10_dbl=1
h10_dest=0;  grep -q 'origin.json, written by the dispatcher' "$H10/propose.out" && h10_dest=1
h10_land=0;  [ "$after_pending" -gt "$before_pending" ] && [ "$worker_pending" = 0 ] && h10_land=1
h10_board=0; grep -q "	j1	" "$H10/board.tsv" && h10_board=1

if [ "$h10_rc" = 0 ] && [ "$h10_rec$h10_orig$h10_own$h10_stat$h10_dbl$h10_dest$h10_land$h10_board" = "11111111" ]; then
  it_pass H10 "fleet/it/H/out/h10/join.txt" \
    "the milestone<->instant join holds from all three sides that must agree — the RECORD names j1, the CHILD's origin.json names both this coordinator and j1, and the MILESTONE names the child as owner while its STATUS stays 'blocked' (only \`apply\` may move a status). A second dispatch onto j1 is refused as already claimed. And the worker's \`propose\` with NO --to reached the COORDINATOR's inbox ($before_pending -> $after_pending) leaving its own at $worker_pending: before SI-27 that measured 0 at the coordinator and 1 at the worker, after which \`harvest\` applied it locally and closed the folder — a report lost with no error. \`board\` names j1 in its milestone column"
else
  it_fail H10 "fleet/it/H/out/h10/join.txt" \
    "the join does not hold: rc=$h10_rc record=$h10_rec origin=$h10_orig owner=$h10_own status-untouched=$h10_stat double-dispatch-refused=$h10_dbl destination=$h10_dest reached-coordinator=$h10_land($before_pending->$after_pending, worker=$worker_pending) board=$h10_board"
fi

# ==================================================================================================
# H11 — `B02`: the proposal queue has a lifecycle.
#   * three reports for one milestone -> ONE apply lands the NEWEST; the two earlier rows close as superseded
#     and their evidence (incl. a typo'd path the worker had corrected) never reaches the milestone;
#   * `milestone --retire` closes the milestone's pending rows;
#   * a late row cannot move a `done` milestone (exit 2), and `withdraw` clears it without touching the roadmap.
# On the base: one apply printed three `applied` rows and unioned all three evidence paths, retire left both
# rows pending, the late row un-landed the milestone at exit 0, and `withdraw` was not a verb.
# ==================================================================================================
H11="$OUT/h11"; mkdir -p "$H11"
{
  fleet milestone --instant "$COORD" --id q1 --title "three reports" --porcelain
  fleet milestone --instant "$COORD" --id q2 --title "retired with rows" --porcelain
  fleet milestone --instant "$COORD" --id q3 --title "landed" --status done --evidence evidence/INDEX.md --porcelain
  # `B03`: `propose` admits only evidence that resolves against the proposer, so the worker holds each file
  # it cites (the "typo" in e2's name is B02's story about superseded rows, not a missing file), and `apply`
  # stores the landed item ANCHORED at the worker's folder, which the state check below expects.
  mkdir -p "$WORKER/evidence"
  for f in e0 e1 e2-typo q2 late; do printf '%s\n' "$f" > "$WORKER/evidence/$f.log"; done
  for pair in "running:evidence/e0.log" "awaiting-ci:evidence/e1.log" "running:evidence/e2-typo.log"; do
    fleet propose --instant "$WORKER" --to "$COORD" --milestone q1 --status "${pair%%:*}" \
          --evidence "${pair#*:}" --porcelain; sleep 1.1       # distinct `at` stamps
  done
  fleet propose --instant "$WORKER" --to "$COORD" --milestone q2 --status running --evidence evidence/q2.log --porcelain
  fleet propose --instant "$WORKER" --to "$COORD" --milestone q3 --status awaiting-ci --evidence evidence/late.log --porcelain
} > "$H11/seed.txt" 2>&1
fleet apply --instant "$COORD" --milestone q1 --porcelain > "$H11/apply-q1.out" 2>&1; h11_apply=$?
fleet milestone --instant "$COORD" --id q2 --retire --reason "done by another route" --porcelain > "$H11/retire-q2.out" 2>&1; h11_retire=$?
fleet apply --instant "$COORD" --milestone q3 --porcelain > "$H11/apply-q3.out" 2>&1; h11_late=$?
h11_rm_before="$(sha256sum "$COORD/.fleet/roadmap.json" | cut -d' ' -f1) $(stat -c %Y.%y "$COORD/.fleet/roadmap.json")"
fleet withdraw --instant "$COORD" --milestone q3 --reason "residue after landing" --porcelain > "$H11/withdraw-q3.out" 2>&1; h11_wd=$?
h11_rm_after="$(sha256sum "$COORD/.fleet/roadmap.json" | cut -d' ' -f1) $(stat -c %Y.%y "$COORD/.fleet/roadmap.json")"
[ "$h11_rm_before" = "$h11_rm_after" ] && h11_untouched=1 || h11_untouched=0
h11_closed_count=$(grep -c $'^proposals-closed\t1 pending proposal' "$H11/retire-q2.out")
py "$COORD" > "$H11/state.txt" 2>&1 <<'PY'
import pathlib, sys
from fleet.roadmap import Roadmap
rm = Roadmap(pathlib.Path(sys.argv[1]))
print("q1:", rm.milestone("q1").status, rm.milestone("q1").evidence)
print("q3:", rm.milestone("q3").status)
print("pending q-rows:", sorted(p.milestone for p in rm.proposals() if p.milestone.startswith("q")))
print("closed:", sorted((c["milestone"], c["closed_as"]) for c in rm.closed()))
PY
cat "$H11/apply-q1.out" "$H11/state.txt"
h11_applied=$(grep -c '^applied' "$H11/apply-q1.out"); h11_super=$(grep -c '^superseded' "$H11/apply-q1.out")
if [ "$h11_apply" = 0 ] && [ "$h11_applied" = 1 ] && [ "$h11_super" = 2 ] \
   && grep -qF "q1: running ['$WORKER/evidence/e2-typo.log']" "$H11/state.txt" \
   && [ "$h11_retire" = 0 ] && [ "$h11_late" = 2 ] && grep -qF "q3: done" "$H11/state.txt" \
   && [ "$h11_wd" = 0 ] && [ "$h11_untouched" = 1 ] && [ "$h11_closed_count" = 1 ] \
   && grep -qF "pending q-rows: []" "$H11/state.txt" \
   && grep -qF "closed: [('q1', 'superseded'), ('q1', 'superseded'), ('q2', 'retired'), ('q3', 'withdrawn')]" "$H11/state.txt"; then
  it_pass H11 "fleet/it/H/out/h11/state.txt" \
    "one apply landed only the newest of three reports (1 applied, 2 superseded; evidence = the newest's alone), retire closed its milestone's row, a late row could not move a done milestone (exit 2) and withdraw closed it — every row left pending by a recorded exit"
else
  it_fail H11 "fleet/it/H/out/h11/state.txt" \
    "apply rc=$h11_apply applied=$h11_applied superseded=$h11_super retire rc=$h11_retire proposals-closed=1?$h11_closed_count late-apply rc=$h11_late (want 2) withdraw rc=$h11_wd roadmap-untouched-by-withdraw=$h11_untouched — see the directory"
fi

# ==================================================================================================
# H12 — `B03`: a proposal's evidence is a location. On the base `propose` accepted a path that never existed
# (rc=0), stored an absolute `-inflight-` self-path verbatim, `apply` copied it onto the milestone after the
# proposer's rename (rc=0, dangling), and `fleet roadmap` printed evidence only as a count.
# ==================================================================================================
H12="$OUT/h12"; mkdir -p "$H12"
EW="$(h_init "evw$TAG")"
mkdir -p "$EW/evidence"; printf 'the artifact\n' > "$EW/evidence/proof.log"; printf 'soon gone\n' > "$EW/evidence/gone.log"
fleet milestone --instant "$COORD" --id ev1 --title "evidence resolves" --porcelain > "$H12/seed.txt" 2>&1
fleet milestone --instant "$COORD" --id ev2 --title "evidence dangles" --porcelain >> "$H12/seed.txt" 2>&1
fleet propose --instant "$EW" --to "$COORD" --milestone ev1 --status done --evidence evidence/nope-typo.log \
      --porcelain > "$H12/typo.out" 2>&1; h12_typo=$?
fleet propose --instant "$EW" --to "$COORD" --milestone ev1 --status done --evidence "$EW/evidence/proof.log" \
      --porcelain > "$H12/abs.out" 2>&1; h12_abs=$?
fleet propose --instant "$EW" --to "$COORD" --milestone ev2 --status done --evidence evidence/gone.log \
      --porcelain > "$H12/gone.out" 2>&1; h12_gone=$?
EW_DONE="${EW/-inflight-/-complete-}"; mv "$EW" "$EW_DONE"          # the worker's completion rename
rm -f "$EW_DONE/evidence/gone.log"                                  # an artifact deleted after it was cited
fleet roadmap --instant "$COORD" --porcelain > "$H12/roadmap.out" 2>&1
h12_col="$(awk -F'\t' '$1=="pending-proposal" && $2=="ev1"{print $9}' "$H12/roadmap.out")"
fleet apply --instant "$COORD" --milestone ev1 --porcelain > "$H12/apply-ev1.out" 2>&1; h12_apply=$?
fleet apply --instant "$COORD" --milestone ev2 --porcelain > "$H12/apply-ev2.out" 2>&1; h12_dangle=$?
py "$COORD" > "$H12/state.txt" 2>&1 <<'PY2'
import pathlib, sys
from fleet.roadmap import Roadmap
rm = Roadmap(pathlib.Path(sys.argv[1]))
print("ev1:", rm.milestone("ev1").status, [(e, pathlib.Path(e).is_file()) for e in rm.milestone("ev1").evidence])
print("ev2:", rm.milestone("ev2").status, "pending:", len([p for p in rm.proposals() if p.milestone == "ev2"]))
PY2
cat "$H12/state.txt"
if [ "$h12_typo" = 2 ] && [ "$h12_abs" = 0 ] && grep -qP '^evidence\tevidence/proof\.log$' "$H12/abs.out" \
   && [ "$h12_gone" = 0 ] && [ "$h12_col" = "$EW_DONE/evidence/proof.log" ] && [ -f "$h12_col" ] \
   && [ "$h12_apply" = 0 ] && grep -qF "ev1: done [('$EW_DONE/evidence/proof.log', True)]" "$H12/state.txt" \
   && [ "$h12_dangle" = 2 ] && grep -q "do not resolve" "$H12/apply-ev2.out" \
   && grep -qF "ev2: blocked pending: 1" "$H12/state.txt"; then
  it_pass H12 "fleet/it/H/out/h12/state.txt" \
    "a typo'd evidence path was refused at propose (exit 2); an absolute self-path was stored relative, and after the proposer's -inflight- -> -complete- rename \`fleet roadmap\` printed it (\$9) at a path that opens and \`apply\` stored it anchored there; a row whose artifact was deleted after citing was refused by \`apply\` (exit 2) and left pending"
else
  it_fail H12 "fleet/it/H/out/h12/state.txt" \
    "typo rc=$h12_typo (want 2) abs rc=$h12_abs gone rc=$h12_gone column='$h12_col' apply rc=$h12_apply dangling-apply rc=$h12_dangle (want 2) — see the directory"
fi

# ==================================================================================================
# H13 — `B09` + `B08` (+ FB-44): the re-measure's scenA, on H10's REAL dispatched worker. Its completion
# rename is the moment a coordinator checks, and on the base that moment broke four things at once:
#   * `seed-check` read the seed through the resolver and the delivery record through the RAW recorded
#     path, so the ATTESTED row degraded to not-delivered on the rename (NEW-1);
#   * `seed-check` printed "This is NOT a pass" and exited 0 (i13) — here the seed is removed to force it;
#   * `apply` rewrote status and evidence but never `owner`, so roadmap.json and `brief` named the
#     `-inflight-` folder that no longer existed (i31) — and `--disown` must still find the OPEN record
#     across the rename once `owner` does follow it;
#   * `milestone --evidence` stored a typo'd path at exit 0 (FB-44).
# ==================================================================================================
H13="$OUT/h13"; mkdir -p "$H13"
J_TODO="$(awk -F'\t' '$1=="todo_id"{print $2; exit}' "$H10/dispatch.out")"
J_SESS="$(awk -F'\t' '$1=="tmux"{print $2; exit}' "$H10/dispatch.out")"
J_DONE="${J_CHILD/-inflight-/-complete-}"
fleet seed-check --id "$J_TODO" --porcelain > "$H13/seed-before.tsv" 2>&1; h13_before=$?
mv "$J_CHILD" "$J_DONE"                                              # the worker's completion rename
fleet seed-check --id "$J_TODO" --porcelain > "$H13/seed-renamed.tsv" 2>&1; h13_renamed=$?
fleet milestone --instant "$COORD" --id j1 --disown --reason "h13 before apply" > "$H13/disown-before.out" 2>&1
h13_disown_before=$?
fleet apply --instant "$COORD" --milestone j1 --porcelain > "$H13/apply.out" 2>&1; h13_apply=$?
h13_owner="$(py "$COORD" <<'PY3'
import json, pathlib, sys
print(next(m for m in json.loads((pathlib.Path(sys.argv[1]) / ".fleet" / "roadmap.json").read_text())["milestones"]
           if m["id"] == "j1")["owner"])
PY3
)"
fleet brief --instant "$J_DONE" --porcelain > "$H13/brief.tsv" 2>&1; h13_brief=$?
fleet milestone --instant "$COORD" --id j1 --disown --reason "h13 after apply" > "$H13/disown-after.out" 2>&1
h13_disown_after=$?
rm -f "$J_DONE/.fleet/seed.txt"                                      # force the check that cannot run
fleet seed-check --id "$J_TODO" --porcelain > "$H13/seed-unreadable.tsv" 2>&1; h13_unreadable=$?
fleet milestone --instant "$COORD" --id h13typo --title "typo'd evidence" --evidence evidence/nope-typo.md \
      --porcelain > "$H13/milestone-typo.out" 2>&1; h13_typo=$?
{ echo "todo=$J_TODO session=$J_SESS child=$J_CHILD -> $J_DONE"
  echo "seed-check before rename rc=$h13_before";   cat "$H13/seed-before.tsv"
  echo "seed-check after rename rc=$h13_renamed";   cat "$H13/seed-renamed.tsv"
  echo "disown before apply rc=$h13_disown_before"; cat "$H13/disown-before.out"
  echo "apply rc=$h13_apply";                       cat "$H13/apply.out"
  echo "roadmap.json owner=$h13_owner exists=$([ -d "$h13_owner" ] && echo yes || echo no)"
  echo "brief rc=$h13_brief";                       grep '^milestone' "$H13/brief.tsv"
  echo "disown after apply rc=$h13_disown_after";   cat "$H13/disown-after.out"
  echo "seed-check with no seed rc=$h13_unreadable"; cat "$H13/seed-unreadable.tsv"
  echo "milestone --evidence typo rc=$h13_typo";    cat "$H13/milestone-typo.out"; } > "$H13/state.txt" 2>&1
cat "$H13/state.txt"
h13_att0=0; [ "$h13_before" = 0 ]   && grep -q "^attested	$J_SESS	" "$H13/seed-before.tsv"  && h13_att0=1
h13_att1=0; [ "$h13_renamed" = 0 ]  && grep -q "^attested	$J_SESS	" "$H13/seed-renamed.tsv" && h13_att1=1
h13_own=0;  [ "$h13_apply" = 0 ] && [ "$h13_owner" = "$J_DONE" ] && [ -d "$h13_owner" ] && h13_own=1
h13_brf=0;  grep -q "^milestone	.*owner=$J_DONE;" "$H13/brief.tsv" && h13_brf=1
h13_hold=0; [ "$h13_disown_before" = 4 ] && [ "$h13_disown_after" = 4 ] && h13_hold=1
h13_unr=0;  [ "$h13_unreadable" = 1 ] && grep -q "^unreadable	$J_SESS	" "$H13/seed-unreadable.tsv" && h13_unr=1
h13_ev=0;   [ "$h13_typo" = 2 ] && grep -q 'nope-typo.md' "$H13/milestone-typo.out" && h13_ev=1
if [ "$h13_att0$h13_att1$h13_own$h13_brf$h13_hold$h13_unr$h13_ev" = "1111111" ]; then
  it_pass H13 "fleet/it/H/out/h13/state.txt" \
    "on a real dispatched worker's -complete- rename: \`seed-check\` still reads ATTESTED (rc=0) because the delivery record is read through the same resolver as the seed; \`apply\` rewrote roadmap.json's owner to the -complete- folder, which exists, and \`brief\` prints it; \`--disown\` still refuses (rc=4) before and after the rewrite because the worker's record is open; with the seed removed \`seed-check\` prints 'NOT a pass' and exits 1; \`milestone --evidence\` refuses a typo'd path (rc=2)"
else
  it_fail H13 "fleet/it/H/out/h13/state.txt" \
    "attested-before=$h13_att0(rc=$h13_before) attested-after-rename=$h13_att1(rc=$h13_renamed) owner-rewritten=$h13_own('$h13_owner') brief=$h13_brf disown-refused=$h13_hold($h13_disown_before/$h13_disown_after) unreadable-exits-1=$h13_unr(rc=$h13_unreadable) milestone-typo-refused=$h13_ev(rc=$h13_typo)"
fi

# H14 — instant operands use the caller's cwd for `.` and `../sibling`, and refusals
# report the resolved path. Both relative spellings failed before the shared resolver fix.
H14="$OUT/h14"; mkdir -p "$H14"
( cd "$COORD" && fleet milestone --instant . --id h14new --title "relative path" --dry-run \
      --porcelain ) > "$H14/dot.out" 2>&1; h14_dot=$?
( cd "$COORD" && fleet review --instant "../$(basename "$WORKER")" --scope all \
      --verdict READY --dry-run --porcelain ) > "$H14/sibling.out" 2>&1; h14_sibling=$?
( cd "$COORD" && fleet roadmap --instant ./missing --porcelain ) > "$H14/missing.out" 2>&1
h14_missing=$?
if [ "$h14_dot" = 0 ] && grep -q $'^id\th14new$' "$H14/dot.out" \
   && grep -q 'would record scope all' "$H14/sibling.out" \
   && ! grep -q 'not an instant on disk' "$H14/sibling.out" \
   && [ "$h14_missing" = 2 ] && grep -qF "$COORD/missing is not an instant on disk" "$H14/missing.out"; then
  it_pass H14 "fleet/it/H/out/h14/dot.out" \
    "milestone resolves dot, review resolves a sibling path, and a missing path refusal names the resolved absolute path"
else
  it_fail H14 "fleet/it/H/out/h14/missing.out" \
    "dot rc=$h14_dot sibling rc=$h14_sibling missing rc=$h14_missing; see h14 outputs"
fi

it_assert_isolation H-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict" >&2; exit 3; }
sed -i "s|$INSTANT/||g" "$RESULTS"
echo "§H done: IT_FAILED=$IT_FAILED"
#: `II-11`. Was `exit "$IT_FAILED"` — a COUNT. `exit` truncates modulo 256, so a section with
#: exactly 256 failures reported SUCCESS, and one with 300 reported 44, a number meaning nothing
#: to any reader. An exit status is a one-byte verdict, not a tally: the count is already printed
#: on the line above and is in the register, which is where a consumer should read it anyway.
if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
exit 1
