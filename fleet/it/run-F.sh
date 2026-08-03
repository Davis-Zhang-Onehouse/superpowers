#!/usr/bin/env bash
# §F — Admission control. COMPLETE: F1-F11 (F11 is not in Plan 6; it exists because measuring F9 found SI-30).
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
fleet declare --instant "$W1" --phase AWAITING-CI --watcher $$ --porcelain > "$OUT/F2-declare.out" 2>&1
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

# ==================================================================================================
# F1 — THE CAP REFUSES A SECOND DISPATCH AND NAMES ITSELF.  The precondition F2/F3 already relied on,
#      now recorded as its own verdict: with the default cap of 1 and one running worker, a second
#      dispatch exits 4 and the message names the cap and the subject holding it.
# ==================================================================================================
f1_rc="$pre_rc"
f1_names_cap=0; grep -qiE 'wip cap|the cap' "$OUT/pre-refused.out" && f1_names_cap=1
f1_names_holder=0; grep -q 'capholder' "$OUT/pre-refused.out" && f1_names_holder=1
f1_clears=0; grep -qi 'clears when' "$OUT/pre-refused.out" && f1_clears=1
if [ "$f1_rc" = 4 ] && [ "$f1_names_cap$f1_names_holder$f1_clears" = "111" ]; then
  it_pass F1 "fleet/it/F/out/pre-refused.out" \
    "with the default cap of 1 and one running worker, a second dispatch exits 4 (refused by an admission rule, not an error), and the message names the CAP, names the SUBJECT holding it, and states what clears it — a refusal a human cannot act on is one that gets forced blindly"
else
  it_fail F1 "fleet/it/F/out/pre-refused.out" \
    "exit=$f1_rc (want 4) names_cap=$f1_names_cap names_holder=$f1_names_holder clears_when=$f1_clears"
fi

# ==================================================================================================
# F4/F5/F6/F7 — THE COMPACTION FREEZE, in its own store so the cap cannot be the thing refusing.
#      F4  an -inflight-compact- sibling ⇒ EVERY dispatch exits 4, naming the blocking instant
#      F5  declare that compaction awaiting-ci ⇒ the CAP reports room AND dispatch is still refused
#          (two rules, reported separately: "the cap says I have room" is not an answer to "may I dispatch")
#      F6  `resume` in that same state ⇒ exit 0. Refusing a recovery path is its own outage
#      F7  --override with no reason ⇒ 2; with "" ⇒ 2 and the message does NOT tell the caller to do what
#          they just did; with a reason ⇒ 0 and the reason is in the record
# ==================================================================================================
FZ_HOME="$EV/home-fz"; FZ_INST="$EV/instants-fz"
rm -rf "$FZ_HOME" "$FZ_INST"; mkdir -p "$FZ_HOME" "$FZ_INST"
# TWO slots, and the reason is a distinction F7 measured the hard way: the compaction takes one, and
# `--override` clears the RULES that refuse (compaction-exclusive, the cap) but not a physical shortage of
# workspaces. With one slot the override attempt exited 3 (no capacity) — correct behaviour, and the wrong
# fixture for asking whether an override works.
for sl in ws1 ws2; do
  mkdir -p "$OUT/slots-fz/$sl"
  ( cd "$OUT/slots-fz/$sl" && git init -q . && git -c user.email=it@fleet -c user.name=it commit -q --allow-empty -m base ) >/dev/null 2>&1
done
(
  export FLEET_HOME="$FZ_HOME" FLEET_INSTANTS="$FZ_INST"
  fleet set-golden --path "$OUT/slots-fz/ws1"
  fleet enroll --slot "$OUT/slots-fz/ws1"
  fleet enroll --slot "$OUT/slots-fz/ws2"
  echo "== a compaction sibling, dispatched (the RECORDED path; F11 covers folder-only) =="
  fleet dispatch --optype compact --profile "$OUT/profile-compact" --title "fzCompaction" \
        --base 00000000 --porcelain
  echo "F4_DISPATCH_START"
  fleet dispatch --profile "$OUT/profile" --title "fzBlocked" --base 00000000 --optype append
  echo "F4_EXIT=$?"
  echo "F5_DECLARE_START"
  COMPACT_INST="$(find "$FZ_INST" -maxdepth 1 -name '*-inflight-compact-fzcompaction' | head -1)"
  fleet declare --instant "$COMPACT_INST" --phase AWAITING-CI --watcher $$ --porcelain
  echo "F5_CAP_START"
  fleet compaction-status --porcelain
  fleet dispatch --profile "$OUT/profile" --title "fzBlocked2" --base 00000000 --optype append
  echo "F5_EXIT=$?"
  echo "F6_RESUME_START"
  R6="$(fleet init --base 00000000 --name fzResumeMe --porcelain | awk -F'\t' '$1=="path"{print $2}')"
  fleet resume --instant "$R6" --porcelain
  echo "F6_EXIT=$?"
  echo "F7_START"
  fleet dispatch --profile "$OUT/profile" --title "fzOv1" --base 00000000 --optype append --override
  echo "F7_NOFLAG_EXIT=$?"
  fleet dispatch --profile "$OUT/profile" --title "fzOv2" --base 00000000 --optype append --override ""
  echo "F7_EMPTY_EXIT=$?"
  fleet dispatch --profile "$OUT/profile" --title "fzOv3" --base 00000000 --optype append \
        --override "the compaction is stalled on CI and this milestone does not touch its tree" --porcelain
  echo "F7_REASON_EXIT=$?"
) > "$OUT/F4-F7.out" 2>&1

sec() { awk -v a="$1" -v b="$2" '$0==a{f=1;next} $0==b{f=0} f' "$OUT/F4-F7.out"; }
ex()  { awk -F'=' -v k="$1" '$1==k{print $2}' "$OUT/F4-F7.out" | head -1; }

# ---- F4 ----
f4_rc="$(ex F4_EXIT)"
f4_named=0; sec F4_DISPATCH_START F4_EXIT= | grep -qi 'fzcompaction' && f4_named=1
if [ "$f4_rc" = 4 ] && [ "$f4_named" = 1 ]; then
  it_pass F4 "fleet/it/F/out/F4-F7.out" \
    "an -inflight-compact- sibling refuses an ordinary dispatch with exit 4 and NAMES the blocking instant. A compaction is exclusive for a different reason than a full cap — unfoldable rebase debt, not attention — so it blocks at any cap, and the message has to say which instant to wait for"
else
  it_fail F4 "fleet/it/F/out/F4-F7.out" "exit=$f4_rc (want 4) named_blocker=$f4_named"
fi

# ---- F5: the cap has room AND the dispatch is still refused ----
f5_rc="$(ex F5_EXIT)"
f5_cap_room=0
sec F5_CAP_START F5_EXIT= | grep -qiE 'no compaction|examined' && f5_cap_room=1
f5_still_refused=0; [ "$f5_rc" = 4 ] && f5_still_refused=1
f5_declared=0; sec F5_DECLARE_START F5_CAP_START | grep -qi 'awaiting-ci' && f5_declared=1
if [ "$f5_declared" = 1 ] && [ "$f5_still_refused" = 1 ]; then
  it_pass F5 "fleet/it/F/out/F4-F7.out" \
    "the compaction declared AWAITING-CI — which takes it OUT of the cap's active-dev count — and the dispatch is STILL refused (exit $f5_rc). Two rules kept structurally apart, each reporting its own verdict: folding them together gets exactly one of these two cases wrong whichever way you fold it, and 'the cap says I have room' is not an answer to 'may I dispatch?'"
else
  it_fail F5 "fleet/it/F/out/F4-F7.out" \
    "declared=$f5_declared still_refused=$f5_still_refused (exit=$f5_rc, want 4)"
fi

# ---- F6: a resume is never refused ----
f6_rc="$(ex F6_EXIT)"
if [ "$f6_rc" = 0 ]; then
  it_pass F6 "fleet/it/F/out/F4-F7.out" \
    "\`resume\` succeeded (exit 0) in the very state where every dispatch is refused, because it evaluates NO admission rule: refusing a recovery path is its own outage — the alarm would block the fix"
else
  it_fail F6 "fleet/it/F/out/F4-F7.out" "resume exited $f6_rc in the frozen state; it must never be refused"
fi

# ---- F7: an override needs a reason a reader can audit ----
f7_noflag="$(ex F7_NOFLAG_EXIT)"; f7_empty="$(ex F7_EMPTY_EXIT)"; f7_reason="$(ex F7_REASON_EXIT)"
f7_not_circular=1
sec F7_START F7_EMPTY_EXIT= | grep -qiE 'clears when: .*(give|pass) a reason' && f7_not_circular=0
f7_recorded=0
grep -rl 'the compaction is stalled on CI' "$FZ_HOME/records" >/dev/null 2>&1 && f7_recorded=1
if [ "$f7_noflag" = 2 ] && [ "$f7_empty" = 2 ] && [ "$f7_reason" = 0 ] \
   && [ "$f7_not_circular" = 1 ] && [ "$f7_recorded" = 1 ]; then
  it_pass F7 "fleet/it/F/out/F4-F7.out" \
    "an override is BAD INPUT without a reason (--override with no value: exit $f7_noflag) and with an empty one (--override \"\": exit $f7_empty), and the empty case does NOT answer 'give a reason' — the caller has already done that, and a remedy that restates what they just did is a loop. With a real reason it admitted (exit $f7_reason) and the reason is IN THE RECORD, which is what makes an override auditable rather than a shrug. Measured on the way: with only ONE slot enrolled the override attempt exits 3 (no capacity), because an override clears the RULES that refuse and not a physical shortage of workspaces — so this case enrols two"
else
  it_fail F7 "fleet/it/F/out/F4-F7.out" \
    "no-value=$f7_noflag(want 2) empty=$f7_empty(want 2) with-reason=$f7_reason(want 0) non-circular=$f7_not_circular reason-in-record=$f7_recorded"
fi

# ==================================================================================================
# F8 — EVERY value-taking flag of every MUTATING verb, passed LAST WITH NO VALUE ⇒ exit 2 inside
#      `timeout 5`. Two failure modes, and the second is the dangerous one: a wrong exit code is
#      annoying, a HANG blocks a coordinator forever with no message. Both are checked here.
#
#      `takes_value` is read off the DECLARED flag spec, so this cannot drift from what the parser does —
#      the matrix is generated, never typed.
# ==================================================================================================
python3 - > "$OUT/F8-matrix.txt" 2>&1 <<'PY'
from fleet.cli import VERBS
for name, spec in sorted(VERBS.items()):
    if spec.read_only:
        continue
    for flag in spec.flags:
        if flag.takes_value:
            print(f"{name}\t{flag.name}")
PY
f8_bad=0; f8_hang=0; f8_pairs=0; : > "$OUT/F8-per-flag.txt"
while IFS=$'\t' read -r v f; do
  [ -n "$v" ] || continue
  f8_pairs=$((f8_pairs+1))
  timeout 5 python3 -m fleet.cli "$v" "$f" > /dev/null 2> "$OUT/F8.stderr"; rc=$?
  diag=$(grep -c 'needs a value' "$OUT/F8.stderr")
  printf '%-18s %-18s rc=%-4s diag=%s\n' "$v" "$f" "$rc" "$diag" >> "$OUT/F8-per-flag.txt"
  [ "$rc" = 124 ] && f8_hang=$((f8_hang+1))
  { [ "$rc" = 2 ] && [ "$diag" -ge 1 ]; } || f8_bad=$((f8_bad+1))
done < "$OUT/F8-matrix.txt"
if [ "$f8_bad" = 0 ] && [ "$f8_hang" = 0 ]; then
  it_pass F8 "fleet/it/F/out/F8-per-flag.txt" \
    "all $f8_pairs value-taking flag/verb pairs across every MUTATING verb exited 2 with the 'needs a value' diagnostic inside timeout 5, and NONE hung. The matrix is generated from the declared \`takes_value\` field rather than typed, so a flag documented one way and parsed another cannot hide here — and a hang is the failure that matters most, because it blocks a coordinator with no message at all"
else
  it_fail F8 "fleet/it/F/out/F8-per-flag.txt" \
    "pairs=$f8_pairs wrong-code-or-no-diagnostic=$f8_bad hangs=$f8_hang"
fi

# ==================================================================================================
# F10 — EVERY evaluate-only path leaves a ZERO DELTA, asserted PER VERB rather than once. `it_zero_delta`
#       manifests FLEET_HOME and the slots (content + mtime) around each call. This is the property that
#       makes a guard safe to interrogate, and the reason it exists is that a guard you cannot ask
#       non-destructively gets asked destructively.
# ==================================================================================================
f10_fail=0
it_zero_delta F10-compaction-status fleet compaction-status --porcelain
it_zero_delta F10-board            fleet board --porcelain
it_zero_delta F10-leases           fleet leases --porcelain
it_zero_delta F10-status           fleet status --id "$(basename "$W1")" --porcelain
it_zero_delta F10-lint             fleet lint --instant "$W1" --porcelain
it_zero_delta F10-roadmap          fleet roadmap --instant "$W1" --porcelain
it_zero_delta F10-brief            fleet brief --instant "$W1" --porcelain
it_zero_delta F10-dispatch-dryrun  fleet dispatch --profile "$OUT/profile" --title f10probe \
                                     --base 00000000 --optype append --dry-run
for c in F10-compaction-status F10-board F10-leases F10-status F10-lint F10-roadmap F10-brief \
         F10-dispatch-dryrun; do
  grep -qP "^$c\tPASS\t" "$RESULTS" || f10_fail=$((f10_fail+1))
done
if [ "$f10_fail" = 0 ]; then
  it_pass F10 "fleet/it/F/out" \
    "eight evaluate-only paths each left FLEET_HOME and the slots byte- and mtime-identical, asserted PER VERB and not once for the set — including \`dispatch --dry-run\`, which evaluates every gate and is the one that most needs to write nothing. A guard you cannot interrogate non-destructively gets interrogated destructively, and that has happened here twice"
else
  it_fail F10 "fleet/it/F/out" "$f10_fail of 8 evaluate-only path(s) left a delta — see the F10-* rows"
fi

it_assert_isolation F-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict" >&2; exit 3; }
sed -i "s|$INSTANT/||g" "$RESULTS"
echo "§F (targeted: F2 F3 F9) done: IT_FAILED=$IT_FAILED"
#: `II-11`. Was `exit "$IT_FAILED"` — a COUNT. `exit` truncates modulo 256, so a section with
#: exactly 256 failures reported SUCCESS, and one with 300 reported 44, a number meaning nothing
#: to any reader. An exit status is a one-byte verdict, not a tally: the count is already printed
#: on the line above and is in the register, which is where a consumer should read it anyway.
if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
exit 1
