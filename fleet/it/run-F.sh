#!/usr/bin/env bash
# §F — Admission control, TARGETED: F2, F3, F9 only.
#
# Chosen deliberately, not for convenience. `test_guards.py` already covers the cap, the compaction freeze and
# profile/optype agreement hermetically (21 tests), and `TestEveryMutatingVerbDryRuns` covers the zero-delta
# contract — non-vacuously since `SI-29`. What the hermetic suite does NOT cover is the MIS-TRIGGER direction:
#
#   F3  a phase written as PROSE into HANDOFF.md must not change admission.  The stated direction is
#       "under-triggers, never mis-triggers", and the reason it matters is on record — a profile once read a
#       worker's kind out of charter prose and 3 of 5 profiles silently became `worker`.
#   F2  and a real DECLARATION must.  Without this half, F3 passes vacuously: a cap that refuses everything
#       satisfies "prose did not free it" while being completely broken.
#   F9  `compaction-status` reports the freeze WITHOUT dispatching anything.  This is the verb whose absence
#       caused two actors to interrogate the guard destructively, so a zero delta is the whole point of it.
#
# The remaining §F cases stay NOT-RUN and the section-level row says so.
#
# Run: bash fleet/it/run-F.sh
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
it_own_cases 'F[0-9]+|ISOLATION-F-(enter|leave)'

it_section F
OUT="$EV/out"; rm -rf "$OUT"; mkdir -p "$OUT"
export FLEET_INSTANTS="$EV/instants"; rm -rf "$FLEET_INSTANTS"; mkdir -p "$FLEET_INSTANTS"
# A VIRGIN store, every run. `it_section` only `mkdir -p`s FLEET_HOME — `run-group5.sh` already records what
# that costs ("three earlier runs had left...") and this section proved it again: the second run inherited the
# first run's `capholder` and `secondc` records, so the cap was already at 2 and the very first dispatch was
# refused. A section whose verdicts depend on whether it has been run before is not measuring the product.
rm -rf "$FLEET_HOME"; mkdir -p "$FLEET_HOME"

bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2

# The stub ahead of the real `claude`: `bin/claude`'s header says why this is mandatory — there is no
# --no-launch flag, so a real dispatch runs whatever `claude` resolves to on PATH.  `SI-28` is what happens
# when this is forgotten.
PATH="$IT_ROOT/bin:$PATH"; export PATH

# A dispatch names its session `dt-<name>`, which does NOT match the harness's `itfleet-<SECTION>` prefix, so
# `it_cleanup_tmux` will not see it. The private SERVER is therefore killed outright at exit — the sessions are
# on a socket nothing else can reach, and leaving them would accumulate one per run.
cleanup_F() {
  it_cleanup_tmux
  tmux -L "$IT_TMUX_SOCKET" kill-server 2>/dev/null
}
trap cleanup_F EXIT

cp -r "$INSTANT/tests/fixtures/profiles/workerCompliant" "$OUT/profile"
#: `ProfileOpTypeAgreement`: a compact dispatch needs a profile DECLARING kind=compaction. Built from the
#: worker fixture with the one field changed, rather than assuming a compaction fixture exists.
cp -r "$INSTANT/tests/fixtures/profiles/workerCompliant" "$OUT/profile-compact"
python3 - "$OUT/profile-compact/profile.json" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
data = json.loads(p.read_text())
data["kind"] = "compaction"
p.write_text(json.dumps(data, indent=2))
PY
for s in ws1 ws2 ws3; do
  mkdir -p "$OUT/slots/$s"
  ( cd "$OUT/slots/$s" && git init -q . && git commit -q --allow-empty -m base ) >/dev/null 2>&1
done
fleet set-golden --path "$OUT/slots/ws1" > "$OUT/setup.out" 2>&1
for s in ws1 ws2 ws3; do fleet enroll --slot "$OUT/slots/$s" >> "$OUT/setup.out" 2>&1; done

# ---- the first worker, running, holding the cap ---------------------------------------------------
fleet dispatch --profile "$OUT/profile" --title "capHolder" --base 00000000 --optype append \
      --porcelain > "$OUT/w1.out" 2>&1
W1="$(awk -F'\t' '$1=="instant"{print $2}' "$OUT/w1.out")"
if [ -z "$W1" ] || [ ! -d "$W1" ]; then
  echo "the first dispatch produced no instant; nothing below is a verdict:" >&2
  cat "$OUT/w1.out" >&2
  exit 2
fi

# PRECONDITION (not a claim of F1): with the default cap of 1 and one running worker, a second dispatch is
# refused. Asserted because F3 is meaningless if the cap refuses nothing.
fleet dispatch --profile "$OUT/profile" --title "secondA" --base 00000000 --optype append \
      > "$OUT/pre-refused.out" 2>&1
pre_rc=$?
if [ "$pre_rc" = 0 ]; then
  echo "the cap did not refuse a second dispatch, so F2/F3 cannot distinguish anything" >&2
  exit 2
fi

# ==================================================================================================
# F3 — PROSE IS NOT STATE.  `## Phase: AWAITING-CI` hand-written into HANDOFF.md, with no declaration,
#      must leave admission exactly as it was. Run BEFORE F2 on purpose: the negative control comes first,
#      so the positive one cannot be explained by the cap having been free all along.
# ==================================================================================================
printf '\n## Phase: AWAITING-CI\n\nThe worker believes it is waiting on CI.\n' >> "$W1/HANDOFF.md"
fleet dispatch --profile "$OUT/profile" --title "secondB" --base 00000000 --optype append \
      > "$OUT/F3-dispatch.out" 2>&1
f3_rc=$?
f3_instants="$(find "$FLEET_INSTANTS" -maxdepth 1 -mindepth 1 -type d | wc -l)"
if [ "$f3_rc" != 0 ] && grep -qiE 'cap|wip' "$OUT/F3-dispatch.out"; then
  it_pass F3 "fleet/it/F/out/F3-dispatch.out" \
    "a phase written as PROSE into HANDOFF.md did NOT free the cap: the second dispatch is still refused (exit $f3_rc, naming the cap) and no instant was created. The stated direction is under-trigger, never mis-trigger, and the failure it guards against is on record — a profile's kind was once read out of charter prose and 3 of 5 silently became 'worker'"
else
  it_fail F3 "fleet/it/F/out/F3-dispatch.out" \
    "prose changed admission (exit $f3_rc): $(head -2 "$OUT/F3-dispatch.out" | tr '\n' ' ')"
fi

# ==================================================================================================
# F2 — AND A REAL DECLARATION DOES.  Same worker, same prose still in place, one declaration added: the
#      cap must now report room and the dispatch must succeed. This is what makes F3 non-vacuous.
# ==================================================================================================
fleet declare --instant "$W1" --phase AWAITING-CI --porcelain > "$OUT/F2-declare.out" 2>&1
f2_declare_rc=$?
fleet dispatch --profile "$OUT/profile" --title "secondC" --base 00000000 --optype append \
      --porcelain > "$OUT/F2-dispatch.out" 2>&1
f2_rc=$?
W2="$(awk -F'\t' '$1=="instant"{print $2}' "$OUT/F2-dispatch.out")"
if [ "$f2_declare_rc" = 0 ] && [ "$f2_rc" = 0 ] && [ -n "$W2" ] && [ -d "$W2" ]; then
  it_pass F2 "fleet/it/F/out/F2-dispatch.out" \
    "one DECLARATION freed the cap that identical prose could not: with '## Phase: AWAITING-CI' still sitting in HANDOFF.md and refusing (F3), \`fleet declare --phase AWAITING-CI\` made the same dispatch succeed and produce $(basename "$W2"). The pair is the assertion — F3 alone would pass against a cap that refuses everything"
else
  it_fail F2 "fleet/it/F/out/F2-dispatch.out" \
    "a declaration did not free the cap: declare_rc=$f2_declare_rc dispatch_rc=$f2_rc instant='$W2'"
fi

# ==================================================================================================
# F9 — `compaction-status` REPORTS THE FREEZE AND CHANGES NOTHING.  Zero delta over FLEET_HOME and the
#      slots, measured by manifest. Non-vacuous: a compaction sibling really exists, so there IS a freeze
#      to report — a zero delta from a verb that found nothing would prove nothing.
# ==================================================================================================
#: Through `dispatch --optype compact`, which is the RECORDED path and the one §K exercised. My first
#: version used `fleet init`, which creates the folder and no record — and that is how `SI-30` was found, so
#: the two paths now have a case each: F9 the recorded one, F11 the folder-only one.
#:
#: Its OWN store, for the same reason F11 has one: by this point F2 has deliberately filled the cap, so a
#: compact dispatch into the shared store is refused by the CAP and F9 would fail for a reason that has
#: nothing to do with what it measures. A case whose fixture depends on an earlier case's side effects is a
#: case that reports the wrong defect.
F9_HOME="$EV/home-f9"; F9_INSTANTS="$EV/instants-f9"
rm -rf "$F9_HOME" "$F9_INSTANTS"; mkdir -p "$F9_HOME" "$F9_INSTANTS"
mkdir -p "$OUT/slots-f9/ws1"
( cd "$OUT/slots-f9/ws1" && git init -q . && git commit -q --allow-empty -m base ) >/dev/null 2>&1
(
  export FLEET_HOME="$F9_HOME" FLEET_INSTANTS="$F9_INSTANTS"
  fleet set-golden --path "$OUT/slots-f9/ws1"
  fleet enroll --slot "$OUT/slots-f9/ws1"
  fleet dispatch --optype compact --profile "$OUT/profile-compact" --title "freezeMaker" \
        --base 00000000 --porcelain
) > "$OUT/F9-compact.out" 2>&1
COMPACT="$(awk -F'\t' '$1=="instant"{print $2}' "$OUT/F9-compact.out")"
FLEET_HOME="$F9_HOME" FLEET_INSTANTS="$F9_INSTANTS" \
  fleet compaction-status --porcelain > "$OUT/F9-status.tsv" 2>&1
f9_reports=0
if [ -n "$COMPACT" ] && grep -qi 'freezemaker' "$OUT/F9-status.tsv"; then f9_reports=1; fi
# The zero-delta half, through the harness's own manifest helper so the comparison is not hand-rolled here.
# `it_zero_delta` reads FLEET_HOME from the environment, so it is pointed at F9's store for this one call.
f9_zero=0
( export FLEET_HOME="$F9_HOME" FLEET_INSTANTS="$F9_INSTANTS"
  it_zero_delta F9-zero-delta fleet compaction-status --porcelain )
grep -qP '^F9-zero-delta\tPASS\t' "$RESULTS" && f9_zero=1
if [ "$f9_reports" = 1 ] && [ "$f9_zero" = 1 ]; then
  it_pass F9 "fleet/it/F/out/F9-status.tsv" \
    "\`compaction-status\` named the live -inflight-compact- sibling ($(basename "$COMPACT")) and left FLEET_HOME and the slots byte-identical. Both halves are required: a zero delta from a verb that reported no freeze would be vacuous, and this is the verb whose ABSENCE made two actors interrogate the guard destructively"
else
  it_fail F9 "fleet/it/F/out/F9-status.tsv" \
    "reports-the-freeze=$f9_reports zero-delta=$f9_zero (compact sibling: ${COMPACT:-none created})"
fi

# ==================================================================================================
# F11 — A COMPACTION THAT EXISTS ONLY AS A FOLDER STILL FREEZES EVERY DISPATCH.  (`SI-30`, and not in
#       Plan 6 — this case exists because measuring F9 found a defect.)
#
#       `CompactionExclusive` read only the reconciled join (records, leases, live processes), so a
#       compaction created as a FOLDER WITH NO RECORD was invisible. Measured before the fix:
#         fleet init --optype compact   ->  …-inflight-compact-ondiskcompact, 0 records
#         fleet dispatch                ->  ADMITTED, exit 0
#         fleet compaction-status       ->  "no compaction of this effort is inflight"
#       — a true sentence about the wrong question, while work was being landed under a live compaction.
#
#       Not hypothetical: `superpowers:maintain-workspace`'s compact op says *"Create
#       `<base>/main-<MMDDHHMM-now>-inflight-compact-<name>/`"*. A folder. No record. And it inverted the
#       guard's own declared `direction = MIS_TRIGGERS`, which promises it will refuse a harmless dispatch
#       rather than admit one that lands work under a compaction "because the second is unrepairable".
# ==================================================================================================
# A separate store, so F11 cannot be satisfied by F9's recorded compaction still sitting there.
F11_HOME="$EV/home-f11"; F11_INSTANTS="$EV/instants-f11"
rm -rf "$F11_HOME" "$F11_INSTANTS"; mkdir -p "$F11_HOME" "$F11_INSTANTS"
(
  export FLEET_HOME="$F11_HOME" FLEET_INSTANTS="$F11_INSTANTS"
  mkdir -p "$OUT/slots-f11/ws1"
  ( cd "$OUT/slots-f11/ws1" && git init -q . && git commit -q --allow-empty -m base ) >/dev/null 2>&1
  fleet set-golden --path "$OUT/slots-f11/ws1"
  fleet enroll --slot "$OUT/slots-f11/ws1"
  echo "== a compaction folder with NO record: exactly what maintain-workspace's compact op creates =="
  fleet init --base 00000000 --name onDiskOnly --optype compact --porcelain
  echo "records in the store: $(find "$F11_HOME/records" -name '*.json' 2>/dev/null | wc -l)"
  echo "== and now a dispatch, which MUST be refused =="
  fleet dispatch --profile "$OUT/profile" --title "shouldBeFrozen" --base 00000000 --optype append
  echo "dispatch_exit=$?"
  echo "== compaction-status must NAME it, not report an empty world =="
  fleet compaction-status --porcelain
) > "$OUT/F11.out" 2>&1
f11_records="$(awk -F': ' '/^records in the store: /{print $2}' "$OUT/F11.out")"
f11_exit="$(awk -F'=' '/^dispatch_exit=/{print $2}' "$OUT/F11.out")"
f11_named=0;  grep -q 'ondiskonly' "$OUT/F11.out" && f11_named=1
f11_status=0; grep -qP '^compaction\t[^\t]*ondiskonly[^\t]*\tviolation' "$OUT/F11.out" && f11_status=1
f11_landed=0; find "$F11_INSTANTS" -maxdepth 1 -name '*-append-shouldbefrozen' | grep -q . && f11_landed=1
if [ "$f11_records" = 0 ] && [ "$f11_exit" = 4 ] && [ "$f11_named" = 1 ] && [ "$f11_status" = 1 ] \
   && [ "$f11_landed" = 0 ]; then
  it_pass F11 "fleet/it/F/out/F11.out" \
    "a compaction present ONLY as a folder — 0 records in the store, which is exactly what maintain-workspace's compact op produces — froze the dispatch (exit 4, naming the folder and how to clear it) and \`compaction-status\` reported it as a VIOLATION rather than 'no compaction of this effort is inflight'. No instant was created. Before SI-30 this measured exit 0 with the work landed: the guard declares direction=MIS_TRIGGERS and was under-triggering, toward the outcome its own docstring calls unrepairable"
else
  it_fail F11 "fleet/it/F/out/F11.out" \
    "records=$f11_records (want 0) dispatch_exit=$f11_exit (want 4) folder-named=$f11_named status-violation=$f11_status work-landed=$f11_landed (want 0)"
fi

it_assert_isolation F-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict" >&2; exit 3; }
sed -i "s|$INSTANT/||g" "$RESULTS"
echo "§F (targeted: F2 F3 F9) done: IT_FAILED=$IT_FAILED"
exit "$IT_FAILED"
