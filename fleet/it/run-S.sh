#!/usr/bin/env bash
# §S — the `SI-51`..`SI-55` batch.  docs/superpowers/fleet-infra-backlog.md
#
# Five register items, each measured live at 0.4.0 before it was fixed, each driven here through the REAL
# surface rather than through the library: every one of them is a defect in what a COORDINATOR types, and
# four of the five were found because a coordinator typed it and got a true sentence about the wrong thing.
#
#   S1  `abort` releases the milestone it claimed                                    SI-51
#   S2  `abort` does NOT release a milestone a different instant is running          SI-51
#   S3  `milestone --disown` frees a stranded claim, and refuses while the owner is open  SI-51
#   S4  `dispatch --seed-extra` reaches the seed; a missing file costs no slot       SI-53
#   S5  `pane-guard --id` and `--pane` answer the same thing about the same pane     SI-54
#   S6  a long-argv NON-claude pane is unverifiable, never FOREIGN                   SI-52
#   S7  a recorded send-keys delivery reads ATTESTED, and a mismatch is refused      SI-55
#
# ⚠️ RUN RED, not assumed to be red. `FI-303`: a control that cannot fire on the defect that motivated it
# certifies its own blind spot. Every case here was run against a worktree at `fleet/v0.4.0` — the tree
# before these five fixes — and all seven FAILED there while all seven pass at HEAD. What each red actually
# measured, because the strength differs and pretending otherwise is the same defect one level up:
#
#   S1  released=0 with claimed-first=1 — the fixture claimed the milestone and the abort left it claimed.
#       The defect itself.
#   S6  `foreign  itfleet-S-longargv  violation` for a plain `sh` pane holding a long argument. The
#       destructive misclassification, reproduced live, on the shape every awaiting-ci worker has.
#   S3  freed=0 — the stranded claim could not be released.
#   S4  the seed carried neither the addition nor its source, and the missing-file path was not refused.
#   S5  `--pane` answered 13 for the record's own pane while `--id` exited 2.
#   S7  nothing could be recorded, so the session stayed unverifiable.
#   S2  WEAKEST, and worth saying so: the property "does not free a sibling's claim" already held at 0.4.0
#       for the uninteresting reason that `abort` touched the roadmap at all. Its red is the REPORTING
#       half — names-the-owner=0. It guards a regression in the new code rather than reproducing an old
#       defect, which is a smaller claim than the other six.
#
# S6 is the one worth reading twice. `FOREIGN` is the only verdict that KILLS a session (`cli._do_dispatch`),
# and before `SI-52` any process at or below the pane holding a long positional produced it — which a CI
# waiter, the shape every `awaiting-ci` worker runs, is. The pane here is `sh` with a 400-character
# argument: the defect's exact shape, built rather than waited for.
#
# Run: bash fleet/it/run-S.sh
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$IT_ROOT/lib.sh"

IT_FAILED=0
it_own_cases 'S[0-9]+[a-z]?|ISOLATION-S-(enter|leave)'

it_section S
#: S8 stands up a SECOND server — the defect needs a session reachable somewhere and not from where the
#: command runs — so the trap kills both. A section that leaves a server behind fails the next section's
#: isolation assertion, which is the correct outcome and an expensive way to learn it.
trap 'it_cleanup_tmux; tmux -L "$IT_TMUX_SOCKET" kill-server 2>/dev/null; tmux -L "${TMUX_PREFIX}-otherserver" kill-server 2>/dev/null' EXIT
OUT="$EV/out"; rm -rf "$OUT"; mkdir -p "$OUT"
export FLEET_INSTANTS="$EV/instants"; rm -rf "$FLEET_INSTANTS"; mkdir -p "$FLEET_INSTANTS"
it_fresh_store
bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2

# The stub ahead of the real `claude`. `bin/claude`'s header says why this is mandatory: there is no
# --no-launch flag, so a real dispatch runs whatever `claude` resolves to on PATH.
PATH="$IT_ROOT/bin:$PATH"; export PATH

s_init() {                       # s_init <name> -> prints the instant path
  local out="$OUT/init-$1.out"
  fleet init --base 00000000 --name "$1" --porcelain > "$out" 2>&1
  awk -F'\t' '$1=="path"{print $2; exit}' "$out"
}
py() { python3 - "$@"; }

PROFILE="$OUT/profile"
cp -r "$INSTANT/tests/fixtures/profiles/workerCompliant" "$PROFILE"
for n in 1 2 3 4 5 6; do
  ( mkdir -p "$OUT/slot$n" && cd "$OUT/slot$n" && git init -q . && git commit -q --allow-empty -m base ) \
    >/dev/null 2>&1
done
fleet set-golden --path "$OUT/slot1" --porcelain > "$OUT/setup.out" 2>&1
for n in 1 2 3 4 5 6; do fleet enroll --slot "$OUT/slot$n" --porcelain >> "$OUT/setup.out" 2>&1; done

COORD="$(s_init coordS)"
[ -d "$COORD" ] || { echo "init produced no coordinator; nothing below is a verdict" >&2; exit 2; }

# `--cap 9` on every dispatch, deliberately. The cap is a real admission rule and this section dispatches
# several workers; a case that failed on capacity would report a cap refusal as a defect in the thing it
# was measuring.
s_dispatch() {                   # s_dispatch <title> <milestone|-> -> prints the child path
  local title="$1" milestone="$2" out="$OUT/dispatch-$1.out"
  if [ "$milestone" = "-" ]; then
    fleet dispatch --profile "$PROFILE" --title "$title" --base 00000000 --optype append \
          --cap 9 --porcelain > "$out" 2>&1
  else
    fleet dispatch --profile "$PROFILE" --title "$title" --base 00000000 --optype append \
          --from "$COORD" --milestone "$milestone" --cap 9 --porcelain > "$out" 2>&1
  fi
  awk -F'\t' '$1=="instant"{print $2; exit}' "$out"
}

s_todo() {                       # s_todo <child path> -> the todo id its record carries
  py "$1" <<'PY'
import os, pathlib, sys
from fleet.store import Store
child = str(pathlib.Path(sys.argv[1]))
found = [r for r in Store(pathlib.Path(os.environ["FLEET_HOME"])).all() if r.child_instant == child]
print(found[0].todo_id if found else "")
PY
}

s_owner() {                      # s_owner <milestone> -> "<owner>|<disowned_reason>"
  #: `getattr`, not `m.disowned_reason`, and that is not defensiveness. This section is run RED against the
  #: pre-fix tree, where the field does not exist — a driver that raised there would make every S1..S3 row
  #: fail on the HARNESS rather than on the product, and a red that comes from the measuring instrument
  #: proves nothing about the defect.
  py "$COORD" "$1" <<'PY'
import pathlib, sys
from fleet.roadmap import Roadmap
m = Roadmap(pathlib.Path(sys.argv[1])).milestone(sys.argv[2])
print(f"{m.owner or '(none)'}|{getattr(m, 'disowned_reason', '') or '(none)'}")
PY
}

# ==================================================================================================
# S1 — `SI-51`. `abort` releases the milestone it claimed.
#
#      `Roadmap.disown` existed, was correct, and had exactly ONE caller — dispatch's rollback. So a
#      milestone claimed by a dispatch that was later aborted stayed owned by an `-abort-` folder
#      permanently, while `claim`'s own refusal told the reader that *"the work is released by aborting it
#      with a reason"*. The live escape was editing roadmap.json by hand, nine times.
# ==================================================================================================
fleet milestone --instant "$COORD" --id s1 --title "released by abort" --porcelain \
      > "$OUT/S1-milestone.out" 2>&1
S1_CHILD="$(s_dispatch abortReleaser s1)"
s1_claimed="$(s_owner s1)"
fleet abort --instant "$S1_CHILD" --reason "the baseline moved under it" --porcelain \
      > "$OUT/S1-abort.out" 2>&1
s1_abort_rc=$?
s1_after="$(s_owner s1)"
{ echo "claimed: $s1_claimed"; echo "after abort: $s1_after"; echo "abort rc=$s1_abort_rc";
  grep -E '^(milestone|milestone_released)\b' "$OUT/S1-abort.out"; } > "$OUT/S1.txt" 2>&1
cat "$OUT/S1.txt"
s1_was=0;   [ "${s1_claimed%%|*}" = "$S1_CHILD" ] && s1_was=1
s1_free=0;  [ "${s1_after%%|*}" = "(none)" ] && s1_free=1
s1_why=0;   case "$s1_after" in *"the baseline moved under it"*) s1_why=1 ;; esac
s1_says=0;  grep -qP '^milestone_released\tyes' "$OUT/S1-abort.out" && s1_says=1
if [ "$s1_abort_rc" = 0 ] && [ "$s1_was$s1_free$s1_why$s1_says" = "1111" ]; then
  it_pass S1 "fleet/it/S/out/S1.txt" \
    "a dispatch claimed milestone s1, and aborting that instant GAVE THE CLAIM BACK — the milestone is unowned again and the roadmap records the abort's own reason for it. Before SI-51 the claim survived the abort forever: --override does not clear it, harvest refuses an aborted instant, and abort refuses to run twice, so the only escape was editing roadmap.json by hand"
else
  it_fail S1 "fleet/it/S/out/S1.txt" \
    "abort rc=$s1_abort_rc claimed-first=$s1_was released=$s1_free reason-recorded=$s1_why reported=$s1_says (owner after abort: $s1_after)"
fi

# ==================================================================================================
# S2 — `SI-51`, the hazard half. An abort of instant A must not free a milestone instant B is running.
#      The abort still COMPLETES — refusing would strand the instant it was asked to abandon — and it
#      reports whose claim it left alone.
# ==================================================================================================
fleet milestone --instant "$COORD" --id s2 --title "claimed by somebody else" --porcelain \
      > "$OUT/S2-milestone.out" 2>&1
S2_CHILD="$(s_dispatch abortStaleOrigin s2)"
SIBLING="$FLEET_INSTANTS/00000000-07300001-inflight-append-theRealOwner"
py "$COORD" "$SIBLING" <<'PY'
import pathlib, sys
from fleet.roadmap import Roadmap
rm = Roadmap(pathlib.Path(sys.argv[1]))
rm.disown("s2")
rm.claim("s2", sys.argv[2])
PY
fleet abort --instant "$S2_CHILD" --reason "wrong worker" --porcelain > "$OUT/S2-abort.out" 2>&1
s2_abort_rc=$?
s2_after="$(s_owner s2)"
{ echo "abort rc=$s2_abort_rc"; echo "owner after: $s2_after";
  grep -E '^milestone_released\b' "$OUT/S2-abort.out"; } > "$OUT/S2.txt" 2>&1
cat "$OUT/S2.txt"
s2_kept=0;  [ "${s2_after%%|*}" = "$SIBLING" ] && s2_kept=1
s2_gone=0;  [ ! -d "$S2_CHILD" ] && s2_gone=1
s2_says=0;  grep -qP '^milestone_released\tno' "$OUT/S2-abort.out" \
            && grep -qF "$SIBLING" "$OUT/S2-abort.out" && s2_says=1
if [ "$s2_abort_rc" = 0 ] && [ "$s2_kept$s2_gone$s2_says" = "111" ]; then
  it_pass S2 "fleet/it/S/out/S2.txt" \
    "the aborted instant's origin named s2, the roadmap said a DIFFERENT instant was running it, and the abort left that claim exactly where it was while still completing — the folder is aborted and the output names whose claim it did not touch. A release that cleared whatever it found would have freed a live sibling's milestone, which is the failure \`claim\`'s two-workers-on-one-milestone refusal exists to prevent"
else
  it_fail S2 "fleet/it/S/out/S2.txt" \
    "abort rc=$s2_abort_rc other-claim-kept=$s2_kept instant-aborted=$s2_gone names-the-owner=$s2_says (owner after: $s2_after)"
fi

# ==================================================================================================
# S3 — `SI-51`, the ones already stranded. Fixing `abort` reaches none of them: `abort` refuses to run
#      twice, so an instant already renamed `-abort-` has no second pass. `--disown` is the repair, and it
#      refuses while the owner still has an OPEN record — otherwise it would put two instants on one
#      milestone by another door.
# ==================================================================================================
fleet milestone --instant "$COORD" --id s3 --title "stranded before the fix" --porcelain \
      > "$OUT/S3-milestone.out" 2>&1
fleet milestone --instant "$COORD" --id s3b --title "still being worked on" --porcelain \
      >> "$OUT/S3-milestone.out" 2>&1
GONE="$FLEET_INSTANTS/00000000-07300002-abort-append-longGone"
py "$COORD" "$GONE" <<'PY'
import pathlib, sys
from fleet.roadmap import Roadmap
Roadmap(pathlib.Path(sys.argv[1])).claim("s3", sys.argv[2])
PY
fleet milestone --instant "$COORD" --id s3 --disown --reason "aborted before abort released claims" \
      --porcelain > "$OUT/S3-disown.out" 2>&1
s3_rc=$?
S3_CHILD="$(s_dispatch stillRunning s3b)"
fleet milestone --instant "$COORD" --id s3b --disown --reason "I want the slot" \
      > "$OUT/S3-refused.out" 2>&1
s3_refused_rc=$?
s3_after="$(s_owner s3)"
s3b_after="$(s_owner s3b)"
{ echo "disown rc=$s3_rc"; echo "s3 owner after: $s3_after";
  echo "disown-while-open rc=$s3_refused_rc"; echo "s3b owner after: $s3b_after"; } > "$OUT/S3.txt" 2>&1
cat "$OUT/S3.txt"
s3_freed=0;  [ "$s3_rc" = 0 ] && [ "${s3_after%%|*}" = "(none)" ] && s3_freed=1
s3_why=0;    case "$s3_after" in *"aborted before abort released claims"*) s3_why=1 ;; esac
s3_held=0;   [ "$s3_refused_rc" != 0 ] && [ "${s3b_after%%|*}" = "$S3_CHILD" ] && s3_held=1
s3_names=0;  grep -qF "$S3_CHILD" "$OUT/S3-refused.out" && s3_names=1
if [ "$s3_freed$s3_why$s3_held$s3_names" = "1111" ]; then
  it_pass S3 "fleet/it/S/out/S3.txt" \
    "a claim held by an instant that no longer exists was released by \`milestone --disown --reason\`, recording why; and the same flag pointed at a milestone whose owner still has an OPEN record was refused (rc=$s3_refused_rc), naming that owner. Without the second half the repair verb would put two instants on one milestone by a door \`claim\` does not guard"
else
  it_fail S3 "fleet/it/S/out/S3.txt" \
    "freed=$s3_freed reason=$s3_why refused-while-open=$s3_held names-owner=$s3_names (rc=$s3_rc, refused rc=$s3_refused_rc, s3=$s3_after, s3b=$s3b_after)"
fi

# ==================================================================================================
# S4 — `SI-53`. The addition is INSIDE the dispatch transaction, so the window in which a coordinator
#      raced a launcher to append to seed.txt is zero. And a path that is not there costs a refusal, not
#      a slot: reading it before the claim is the whole reason it is read where it is.
# ==================================================================================================
EXTRA="$OUT/seed-extra.md"
printf 'Coordinate with the sibling before touching the shared fixture.\n' > "$EXTRA"
fleet dispatch --profile "$PROFILE" --title "seedExtraWorker" --base 00000000 --optype append \
      --cap 9 --seed-extra "$EXTRA" --porcelain > "$OUT/dispatch-seedExtraWorker.out" 2>&1
s4_rc=$?
S4_CHILD="$(awk -F'\t' '$1=="instant"{print $2; exit}' "$OUT/dispatch-seedExtraWorker.out")"
s4_seed="$S4_CHILD/.fleet/seed.txt"
# The refusal, measured with the pool and the instants directory bracketed either side.
s4_leases_before="$(find "$FLEET_HOME/pool/leases" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')"
s4_instants_before="$(find "$FLEET_INSTANTS" -maxdepth 1 -mindepth 1 | wc -l | tr -d ' ')"
fleet dispatch --profile "$PROFILE" --title "neverBorn" --base 00000000 --optype append --cap 9 \
      --seed-extra "$OUT/does-not-exist.md" > "$OUT/S4-missing.out" 2>&1
s4_missing_rc=$?
s4_leases_after="$(find "$FLEET_HOME/pool/leases" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')"
s4_instants_after="$(find "$FLEET_INSTANTS" -maxdepth 1 -mindepth 1 | wc -l | tr -d ' ')"
{ echo "dispatch rc=$s4_rc"; echo "seed: $s4_seed";
  echo "--- the addition, in the seed the worker is briefed from ---";
  grep -n 'Coordinate with the sibling' "$s4_seed" 2>&1;
  echo "--- the profile's own text is still there ---";
  grep -c . "$s4_seed" 2>&1;
  echo "missing-file rc=$s4_missing_rc";
  echo "leases $s4_leases_before -> $s4_leases_after";
  echo "instants $s4_instants_before -> $s4_instants_after"; } > "$OUT/S4.txt" 2>&1
cat "$OUT/S4.txt"
s4_in=0;    grep -q 'Coordinate with the sibling' "$s4_seed" 2>/dev/null && s4_in=1
s4_src=0;   grep -qF "$EXTRA" "$s4_seed" 2>/dev/null && s4_src=1
#: The profile fixture's own rendered seed, not a guess at what a seed says: `workerCompliant/seed.txt`
#: is "Do the work for {{TITLE}}." and the title here is `seedExtraWorker`.
s4_kept=0;  grep -q 'Do the work for seedExtraWorker' "$s4_seed" 2>/dev/null && s4_kept=1
s4_ref=0;   [ "$s4_missing_rc" != 0 ] && grep -q 'does-not-exist.md' "$OUT/S4-missing.out" && s4_ref=1
s4_cost=0;  [ "$s4_leases_before" = "$s4_leases_after" ] \
            && [ "$s4_instants_before" = "$s4_instants_after" ] && s4_cost=1
if [ "${s4_rc:-1}" = 0 ] && [ "$s4_in$s4_src$s4_kept$s4_ref$s4_cost" = "11111" ]; then
  it_pass S4 "fleet/it/S/out/S4.txt" \
    "\`--seed-extra\` put the coordinator's sentence into the seed the worker is briefed from, inside the dispatch transaction — the profile's own text is still there and the seed names the file the addition came from, so a worker reading two paragraphs that disagree can tell which was written for it. A missing file was refused (rc=$s4_missing_rc) with leases $s4_leases_before->$s4_leases_after and instants $s4_instants_before->$s4_instants_after: a typo costs a refusal, not a slot"
else
  it_fail S4 "fleet/it/S/out/S4.txt" \
    "dispatch rc=${s4_rc:-1} addition-present=$s4_in names-source=$s4_src profile-seed-kept=$s4_kept missing-refused=$s4_ref nothing-claimed=$s4_cost (leases $s4_leases_before->$s4_leases_after, instants $s4_instants_before->$s4_instants_after)"
fi

# ==================================================================================================
# S5 — `SI-54`. `pane-guard` was the only verb keyed on `--pane <session>` while everything around it
#      takes `--id <todo>`. The two differ by a timestamp suffix, so the natural transcription is wrong,
#      and the answer to a wrong pane name is `13` — a sentence about a healthy worker that reads as a
#      dead one. This is the verb an external monitor calls before EVERY send (FD-10).
# ==================================================================================================
S5_TODO="$(s_todo "$S4_CHILD")"
S5_PANE="$(py "$S4_CHILD" <<'PY'
import os, pathlib, sys
from fleet.store import Store
child = str(pathlib.Path(sys.argv[1]))
found = [r for r in Store(pathlib.Path(os.environ["FLEET_HOME"])).all() if r.child_instant == child]
print(found[0].tmux if found else "")
PY
)"
fleet pane-guard --pane "$S5_PANE" --porcelain > "$OUT/S5-pane.out" 2>&1; s5_pane_rc=$?
fleet pane-guard --id   "$S5_TODO" --porcelain > "$OUT/S5-id.out"   2>&1; s5_id_rc=$?
fleet pane-guard --pane "$S5_PANE" --id "$S5_TODO" > "$OUT/S5-both.out" 2>&1; s5_both_rc=$?
fleet pane-guard > "$OUT/S5-neither.out" 2>&1; s5_neither_rc=$?
{ echo "todo=$S5_TODO pane=$S5_PANE";
  echo "--pane rc=$s5_pane_rc"; echo "--id rc=$s5_id_rc";
  echo "both rc=$s5_both_rc"; echo "neither rc=$s5_neither_rc";
  echo "--- by --id ---"; cat "$OUT/S5-id.out"; } > "$OUT/S5.txt" 2>&1
cat "$OUT/S5.txt"
s5_agree=0;  [ -n "$S5_PANE" ] && [ "$s5_pane_rc" = "$s5_id_rc" ] && s5_agree=1
s5_names=0;  grep -qP "^pane\t$S5_PANE\$" "$OUT/S5-id.out" && s5_names=1
s5_both=0;   [ "$s5_both_rc" = 2 ] && s5_both=1
s5_none=0;   [ "$s5_neither_rc" = 2 ] && grep -q -- '--id' "$OUT/S5-neither.out" && s5_none=1
if [ "$s5_agree$s5_names$s5_both$s5_none" = "1111" ]; then
  it_pass S5 "fleet/it/S/out/S5.txt" \
    "\`pane-guard --id $S5_TODO\` resolved the pane through the record and answered exactly what \`--pane $S5_PANE\` answered (both rc=$s5_id_rc), naming the pane it resolved to. Naming both is refused (rc=$s5_both_rc) because two identifiers that can disagree is a third failure mode, and naming neither is refused (rc=$s5_neither_rc) with BOTH flags in the message. Neither refusal returns a pane-guard code: a caller branching on the number must never read 'you did not say what to look at' as an observation of a pane"
else
  it_fail S5 "fleet/it/S/out/S5.txt" \
    "agree=$s5_agree(--pane rc=$s5_pane_rc, --id rc=$s5_id_rc) names-pane=$s5_names both-refused=$s5_both(rc=$s5_both_rc) neither-refused=$s5_none(rc=$s5_neither_rc)"
fi

# ==================================================================================================
# S6 — `SI-52`. The destructive one. `FOREIGN` is the only verdict that KILLS a session, and before this
#      fix ANY process at or below the pane holding a non-flag argument over 200 characters produced it —
#      which is exactly what a CI waiter is, and every `awaiting-ci` worker runs one.
#
#      The pane below is `sh` holding a 400-character argument: the defect's shape, built rather than
#      waited for. The assertion that matters is the NEGATIVE one — not FOREIGN — because FOREIGN's
#      printed remedy is to dispatch the worker again.
# ==================================================================================================
S6_SESS="${TMUX_PREFIX}-longargv"
S6_LONG="$(python3 -c "print('e' * 400)")"
tmux -L "$IT_TMUX_SOCKET" new-session -d -s "$S6_SESS" \
     "sh -c 'while :; do sleep 1; done' $S6_LONG" 2>"$OUT/S6-tmux.err"
S6_INST="$(s_init longArgvSubject)"
mkdir -p "$S6_INST/.fleet"
printf 'Read CHARTER.md and then run `fleet brief`. %s\n' "$(python3 -c "print('briefing padding. ' * 20)")" \
  > "$S6_INST/.fleet/seed.txt"
#: `--slot` is the enrolled slot's NAME, not its path — the pool refuses a path it never enrolled.
fleet resume --instant "$S6_INST" --slot slot5 --tmux "$S6_SESS" --porcelain \
      > "$OUT/S6-resume.out" 2>&1
s6_resume_rc=$?
fleet seed-check --porcelain > "$OUT/S6-seedcheck.tsv" 2>&1
s6_row="$(grep -F "$S6_SESS" "$OUT/S6-seedcheck.tsv" | head -1)"
{ echo "resume rc=$s6_resume_rc"; echo "pane argv:";
  tmux -L "$IT_TMUX_SOCKET" list-panes -t "=$S6_SESS:" -F '#{pane_pid}' 2>/dev/null \
    | while read -r pid; do tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | cut -c1-120; echo; done
  echo "row: $s6_row"; } > "$OUT/S6.txt" 2>&1
cat "$OUT/S6.txt"
s6_found=0;   [ -n "$s6_row" ] && s6_found=1
s6_notfgn=0;  case "$s6_row" in *foreign*) ;; *) s6_notfgn=1 ;; esac
s6_says=0;    case "$s6_row" in *not-delivered*) s6_says=1 ;; esac
s6_claude=0;  case "$s6_row" in *claude*) s6_claude=1 ;; esac
if [ "$s6_resume_rc" = 0 ] && [ "$s6_found$s6_notfgn$s6_says$s6_claude" = "1111" ]; then
  it_pass S6 "fleet/it/S/out/S6.txt" \
    "a pane whose process is \`sh\` holding a 400-character argument — the shape every awaiting-ci worker's CI waiter has — is reported NOT-DELIVERED and explicitly NOT foreign, and the detail says no claude process was found at or below it rather than implying one was examined. FOREIGN is the verdict that kills a session inside \`dispatch\`, so an uncertain probe must not be able to reach it"
else
  it_fail S6 "fleet/it/S/out/S6.txt" \
    "resume rc=$s6_resume_rc row-found=$s6_found not-foreign=$s6_notfgn says-unverifiable=$s6_says names-the-missing-process=$s6_claude :: $s6_row"
fi

# ==================================================================================================
# S7 — `SI-55`. The positive verdict was reachable only through argv, and a send-keys delivery leaves
#      nothing there — so a rescued worker read NOT-DELIVERED for the life of its instant while a sibling
#      read VERIFIED. A row that can never change is a row that stops being read.
#
#      Recorded, then COMPARED: a delivery that does not carry the rendered seed is refused at write time
#      rather than stored for a later reader to discover.
# ==================================================================================================
S7_SENT="$OUT/S7-sent.txt"
{ printf 'Your slot is %s.\n\n' "slot5"; cat "$S6_INST/.fleet/seed.txt"; } > "$S7_SENT"
S7_TODO="$(s_todo "$S6_INST")"
fleet seed-delivered --id "$S7_TODO" --delivered "$S7_SENT" --porcelain > "$OUT/S7-record.out" 2>&1
s7_rc=$?
S7_WRONG="$OUT/S7-wrong.txt"
python3 -c "print('an entirely different briefing. ' * 20)" > "$S7_WRONG"
fleet seed-delivered --id "$S7_TODO" --delivered "$S7_WRONG" > "$OUT/S7-refused.out" 2>&1
s7_wrong_rc=$?
fleet seed-check --porcelain > "$OUT/S7-seedcheck.tsv" 2>&1
s7_row="$(grep -F "$S6_SESS" "$OUT/S7-seedcheck.tsv" | head -1)"
s7_md5_after="$(py "$S6_INST" <<'PY'
import pathlib, sys
from fleet import seedcheck
d = seedcheck.read_delivery(pathlib.Path(sys.argv[1]))
print(d.delivered_md5 if d else "(none)")
PY
)"
s7_expected="$(py "$S7_SENT" <<'PY'
import pathlib, sys
from fleet import seedcheck
print(seedcheck.digest(pathlib.Path(sys.argv[1]).read_text()))
PY
)"
{ echo "record rc=$s7_rc"; echo "mismatch rc=$s7_wrong_rc";
  echo "stored md5: $s7_md5_after"; echo "expected md5: $s7_expected";
  echo "row: $s7_row"; } > "$OUT/S7.txt" 2>&1
cat "$OUT/S7.txt"
s7_ok=0;      [ "$s7_rc" = 0 ] && s7_ok=1
s7_att=0;     case "$s7_row" in *attested*) s7_att=1 ;; esac
s7_chan=0;    case "$s7_row" in *send-keys*) s7_chan=1 ;; esac
s7_refused=0; [ "$s7_wrong_rc" != 0 ] && s7_refused=1
s7_intact=0;  [ "$s7_md5_after" = "$s7_expected" ] && s7_intact=1
s7_pop=0;     grep -q 'attested' "$OUT/S7-seedcheck.tsv" && s7_pop=1
if [ "$s7_ok$s7_att$s7_chan$s7_refused$s7_intact$s7_pop" = "111111" ]; then
  it_pass S7 "fleet/it/S/out/S7.txt" \
    "the actor that briefed a pane by send-keys recorded WHAT IT SENT, fleet digested it and compared it against the seed it had rendered, and \`seed-check\` now reports ATTESTED for that session — a fourth state whose detail names the channel, so no reader mistakes it for an observation of the worker's own argv. A preamble is accepted and a DIFFERENT briefing is refused at write time (rc=$s7_wrong_rc) leaving the good record intact, which is the misdelivery class this module exists for"
else
  it_fail S7 "fleet/it/S/out/S7.txt" \
    "record rc=$s7_rc attested=$s7_att names-channel=$s7_chan mismatch-refused=$s7_refused($s7_wrong_rc) record-intact=$s7_intact population-row=$s7_pop :: $s7_row"
fi

# ==================================================================================================
# S8 — `SI-59`. A verb that ACTS on a session must not act when that session answers on a DIFFERENT
#      tmux server. Measured on the live box at `0.5.2`, against a running worker, from a shell pointed
#      at another server: `fleet close` returned **rc=0**, printed `closed dt-<name>`, stamped
#      `closed_at` and reported the monitor disarmed — while `tmux -L fleet ls` still listed the
#      session. It did not fail to find the pane. It reported success for a pane it never touched.
#
#      Two servers are the whole fixture, and the second one is created here rather than borrowed: the
#      defect needs a session that is reachable somewhere and not from where the command runs, which is
#      a state no single-server section can produce.
#
#      Asserted NEGATIVELY, on the record and on the session: a refusal that still stamped the record,
#      or still killed the pane, is the same defect wearing a non-zero exit code.
# ==================================================================================================
S8_OTHER="${TMUX_PREFIX}-otherserver"
S8_SESS="${TMUX_PREFIX}-strayed"
tmux -L "$S8_OTHER" new-session -d -s "$S8_SESS" 'sh -c "while :; do sleep 1; done"' 2>"$OUT/S8-tmux.err"
S8_INST="$(s_init strayedSubject)"
#: Recorded from a shell pointed at the OTHER server, which is how a real dispatch records one: the
#: server it is talking to is the server it creates the session on.
FLEET_TMUX_SOCKET="$S8_OTHER" fleet resume --instant "$S8_INST" --slot slot6 --tmux "$S8_SESS"       --porcelain > "$OUT/S8-resume.out" 2>&1
s8_resume_rc=$?
S8_ID="$(awk -F'\t' '$1=="todo_id"{print $2}' "$OUT/S8-resume.out" | head -1)"
[ -n "$S8_ID" ] && s8_socket="$(fleet status --id "$S8_ID" --porcelain 2>/dev/null       | awk -F'\t' '$1=="evidence.tmux_socket"{print $2}')"

#: Now act on it from the section's OWN server — the wrong one for this record.
fleet close --id "$S8_ID" > "$OUT/S8-close.out" 2>&1
s8_close_rc=$?
s8_alive=0; tmux -L "$S8_OTHER" has-session -t "=$S8_SESS" 2>/dev/null && s8_alive=1
#: Read from the RECORD, not from a report: the question is whether the refused close wrote anything, and
#: asking a view about it would put the thing under test between the assertion and the fact.
s8_closed_at="$(python3 -c "import json,sys
try:
    print(json.load(open(sys.argv[1])).get('closed_at') or '')
except Exception:
    print('UNREADABLE')" "$FLEET_HOME/records/$S8_ID.json" 2>/dev/null)"
{ echo "resume rc=$s8_resume_rc id=$S8_ID recorded_socket=${s8_socket:-<none>}";
  echo "close rc=$s8_close_rc"; echo "--- close output ---"; cat "$OUT/S8-close.out";
  echo "session still alive on $S8_OTHER: $s8_alive"; echo "closed_at: ${s8_closed_at:-<empty>}"; }   > "$OUT/S8.txt" 2>&1
cat "$OUT/S8.txt"

s8_refused=0; [ "$s8_close_rc" != 0 ] && s8_refused=1
s8_names=0;   grep -qF "$S8_OTHER" "$OUT/S8-close.out" && s8_names=1
s8_here=0;    grep -qF "$IT_TMUX_SOCKET" "$OUT/S8-close.out" && s8_here=1
s8_unstamped=0; [ -z "$s8_closed_at" ] && s8_unstamped=1
s8_recorded=0; [ "$s8_socket" = "$S8_OTHER" ] && s8_recorded=1
if [ "$s8_resume_rc" = 0 ]    && [ "$s8_refused$s8_names$s8_here$s8_alive$s8_unstamped$s8_recorded" = "111111" ]; then
  it_pass S8 "fleet/it/S/out/S8.txt"     "a record whose session lives on another tmux server is REFUSED by \`close\` (rc=$s8_close_rc) naming both the server it looked on and the one the session is on; the session is still alive there and the record carries no closed_at, so the refusal did not do half the job it refused. The record also carries the server it was dispatched on ($s8_socket), which is the fix underneath the guard: a session NAME is not an address, and every reader before this had to infer the server from whatever the shell exported"
else
  it_fail S8 "fleet/it/S/out/S8.txt"     "resume rc=$s8_resume_rc refused=$s8_refused(rc=$s8_close_rc) names-other-server=$s8_names names-this-server=$s8_here session-still-alive=$s8_alive record-unstamped=$s8_unstamped socket-recorded=$s8_recorded(${s8_socket:-<none>})"
fi

it_assert_isolation S-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict" >&2; exit 3; }
sed -i "s|$INSTANT/||g" "$RESULTS"
echo "§S done: IT_FAILED=$IT_FAILED"
if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
exit 1
