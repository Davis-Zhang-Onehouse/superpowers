#!/usr/bin/env bash
# §LB — the GIT LINEAGE gate.  `SI-32`.  Not in Plan 6: these cases exist because the operator asked how a
# mechanism prevents a dispatched instant from forgetting to check out its base, and the honest answer was
# that the check I had proposed did not prevent it — it detected it, if you remembered to run the detector.
#
# The failure is on record twice in one worker's own register
# (quantonOnSpark4/07270639-07271113-complete-append-lift01InvertVeloxCastAnsiGateBounded/ISSUES.md):
#
#   OI-2  "ws3 arrived at gluten 4020d0715 / velox 8d62aac98 — the golden prebuild — not at my lineage base.
#          Slots are leased from a pre-built golden image so no worker pays a full rebuild; nothing moves a
#          slot forward to a milestone's own base. The failure mode is invisible: the build succeeds and tests
#          pass, so the whole milestone silently stacks on the pre-fix baseline. TWO WORKERS IN THE PREVIOUS
#          WAVE HIT EXACTLY THIS."
#
#   OI-1  the rendered SEED (once per wave, from a profile) named one lineage base and the per-milestone
#          CHARTER named another, so the worker had to arbitrate between two prose authorities.
#
#   OI-3  and `pdispatch basecheck lift-01` did not even resolve, because the brief called the worker
#          `lift-01` while the record key was the full slug — a check the worker tried to run and could not.
#
# The fixture reproduces the position exactly: the lineage base is a commit on a DIVERGED SIBLING branch, not
# an ancestor of the golden, because in the real incident lift-01 stacked on R2's tips rather than on the
# wave's terminal tip — *"some milestones deliberately stack on a sibling's tips."*
#
# Run: bash fleet/it/run-lineage.sh
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
it_own_cases 'LB[0-9]+|ISOLATION-LB-(enter|leave)'

it_section LB
OUT="$EV/out"; rm -rf "$OUT"; mkdir -p "$OUT"
export FLEET_INSTANTS="$EV/instants"; rm -rf "$FLEET_INSTANTS"; mkdir -p "$FLEET_INSTANTS"
rm -rf "$FLEET_HOME"; mkdir -p "$FLEET_HOME"

bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2

PATH="$IT_ROOT/bin:$PATH"; export PATH
trap 'it_cleanup_tmux; tmux -L "$IT_TMUX_SOCKET" kill-server 2>/dev/null' EXIT

# ---- the slot: one repo, three commits, the golden DIVERGED from the lineage base -------------------
SLOT="$OUT/slot"
mkdir -p "$SLOT/alpha"
(
  cd "$SLOT/alpha" && git init -q . && git config user.email it@fleet && git config user.name it
  echo base > f.txt && git add -A && git commit -q -m "A: common ancestor"
  git branch -q ancestor
  git checkout -q -b sibling && echo siblingwork > f.txt && git commit -qam "L: the sibling's tip"
  git checkout -q ancestor && git checkout -q -b goldenbranch
  echo goldenwork > g.txt && git add -A && git commit -q -m "G: the golden prebuild"
) >/dev/null 2>&1
L="$(git -C "$SLOT/alpha" rev-parse sibling)"
G="$(git -C "$SLOT/alpha" rev-parse goldenbranch)"
# A prebuilt native artifact, as the golden image ships. Backdated so it predates any later checkout.
touch -d '2020-01-01' "$SLOT/alpha/libvelox.so"
{ echo "lineage base L (sibling) = $L"; echo "golden        G           = $G"; \
  echo "slot HEAD                = $(git -C "$SLOT/alpha" rev-parse HEAD)"; } > "$OUT/fixture.txt"
cat "$OUT/fixture.txt"

# A profile whose SEED renders the generated instruction.
cp -r "$INSTANT/tests/fixtures/profiles/workerCompliant" "$OUT/profile"
printf '\n\n=== POSITION YOUR WORKSPACE ===\n{{CHECKOUT}}\n' >> "$OUT/profile/seed.txt"

fleet set-golden --path "$SLOT" > "$OUT/setup.out" 2>&1
fleet enroll --slot "$SLOT" >> "$OUT/setup.out" 2>&1

# ==================================================================================================
# LB1 — DISPATCH RECORDS THE BASE, AND THE SEED CARRIES THE LITERAL COMMANDS.  (`OI-1`)
#       One datum, rendered. Two documents that both say `{{CHECKOUT}}` cannot disagree about the base;
#       two hand-written prose statements did, and the worker had to decide which was authoritative.
# ==================================================================================================
fleet dispatch --profile "$OUT/profile" --title "liftOne" --base 00000000 --optype append \
      --lineage-base "alpha=$L" --porcelain > "$OUT/LB1-dispatch.out" 2>&1
W="$(awk -F'\t' '$1=="instant"{print $2}' "$OUT/LB1-dispatch.out")"
TODO="$(awk -F'\t' '$1=="todo_id"{print $2}' "$OUT/LB1-dispatch.out")"
if [ -z "$W" ] || [ ! -d "$W" ]; then
  it_fail LB1 "fleet/it/LB/out/LB1-dispatch.out" \
    "the dispatch produced no instant: $(head -2 "$OUT/LB1-dispatch.out" | tr '\n' ' ')"
else
  cp "$W/.fleet/seed.txt" "$OUT/LB1-seed.txt"
  lb1_recorded=0; grep -q "^lineage_base	alpha=$L$" "$OUT/LB1-dispatch.out" && lb1_recorded=1
  lb1_golden=0;   grep -q "^golden_base	alpha=$G$" "$OUT/LB1-dispatch.out" && lb1_golden=1
  lb1_cmd=0;      grep -qF "git -C alpha checkout --detach $L" "$OUT/LB1-seed.txt" && lb1_cmd=1
  lb1_warns=0;    grep -qF "REFUSE" "$OUT/LB1-seed.txt" && lb1_warns=1
  lb1_native=0;   grep -qi 'native' "$OUT/LB1-seed.txt" && lb1_native=1
  if [ "$lb1_recorded$lb1_golden$lb1_cmd$lb1_warns$lb1_native" = "11111" ]; then
    it_pass LB1 "fleet/it/LB/out/LB1-seed.txt" \
      "dispatch recorded the git lineage as DATA (lineage_base=alpha=${L:0:12}) and, separately, where the slot actually was (golden_base=alpha=${G:0:12}, read-only — this verb performs no checkout). The seed the worker reads first carries the LITERAL command \`git -C alpha checkout --detach ${L:0:12}\`, generated from that same field, plus the fact that propose/complete REFUSE without it and a note about the prebuilt native artifacts. OI-1 was two prose authorities disagreeing about the base; an instruction generated from the recorded field cannot drift from the field the gate checks"
  else
    it_fail LB1 "fleet/it/LB/out/LB1-seed.txt" \
      "recorded=$lb1_recorded golden_base=$lb1_golden checkout-command=$lb1_cmd names-the-refusal=$lb1_warns native-note=$lb1_native"
  fi

  fleet milestone --instant "$W" --id L1 --title "the lift" --porcelain > "$OUT/LB-milestone.out" 2>&1

  # ================================================================================================
  # LB2 — FROM THE GOLDEN, A CLAIM OF DONE IS REFUSED; `running` IS NOT.  (`OI-2`, and mechanism B)
  #       The slot is exactly where ws3 arrived: at the golden, with the base fetched, nothing moved.
  # ================================================================================================
  fleet propose --instant "$W" --milestone L1 --status running --evidence "evidence/INDEX.md" \
        > "$OUT/LB2-running.out" 2>&1
  lb2_running_rc=$?
  fleet propose --instant "$W" --milestone L1 --status done --evidence "evidence/INDEX.md" \
        > "$OUT/LB2-done.out" 2>&1
  lb2_done_rc=$?
  fleet complete --instant "$W" > "$OUT/LB2-complete.out" 2>&1
  lb2_complete_rc=$?
  fleet base-check --id "$TODO" --porcelain > "$OUT/LB2-basecheck.tsv" 2>&1
  lb2_bc_rc=$?
  lb2_named=0; grep -qF "${L:0:12}" "$OUT/LB2-done.out" && lb2_named=1
  lb2_howto=0; grep -qF "base-check" "$OUT/LB2-done.out" && lb2_howto=1
  lb2_still_inflight=0; case "$(basename "$W")" in *-inflight-*) lb2_still_inflight=1;; esac
  lb2_viol=0; grep -qP '^lineage\t[^\t]*\tviolation\t' "$OUT/LB2-basecheck.tsv" && lb2_viol=1
  if [ "$lb2_running_rc" = 0 ] && [ "$lb2_done_rc" != 0 ] && [ "$lb2_complete_rc" != 0 ] \
     && [ "$lb2_named" = 1 ] && [ "$lb2_howto" = 1 ] && [ "$lb2_still_inflight" = 1 ] \
     && [ "$lb2_viol" = 1 ] && [ "$lb2_bc_rc" != 0 ]; then
    it_pass LB2 "fleet/it/LB/out/LB2-done.out" \
      "from the unrepositioned golden — the exact position ws3 arrived in — \`propose --status done\` was REFUSED (exit $lb2_done_rc) and so was \`complete\` (exit $lb2_complete_rc), each naming the base ${L:0:12} it expected and pointing at \`fleet base-check\`; the folder is still -inflight-, so the rename that IS the state transition did not happen. \`propose --status running\` was ALLOWED (exit 0), because a worker legitimately reports progress from wherever it is while it works — gating that would fire on every worker before it had done anything. This is why the mechanism is a GATE and not a check the worker runs: OI-3 records the worker running the old check and the id failing to resolve"
  else
    it_fail LB2 "fleet/it/LB/out/LB2-done.out" \
      "running_rc=$lb2_running_rc(want 0) done_rc=$lb2_done_rc(want !=0) complete_rc=$lb2_complete_rc(want !=0) names-base=$lb2_named says-base-check=$lb2_howto still-inflight=$lb2_still_inflight basecheck-violation=$lb2_viol basecheck_rc=$lb2_bc_rc(want !=0)"
  fi

  # ================================================================================================
  # LB3 — DO WHAT THE SEED SAID, AND THE GATE OPENS.  Without this half LB2 passes against a gate that
  #       refuses everything, which is a worse product than the defect.
  # ================================================================================================
  git -C "$SLOT/alpha" checkout -q --detach "$L" 2>>"$OUT/LB3-checkout.err"
  fleet base-check --id "$TODO" --porcelain > "$OUT/LB3-basecheck.tsv" 2>&1
  lb3_bc_rc=$?
  fleet propose --instant "$W" --milestone L1 --status done --evidence "evidence/INDEX.md" \
        > "$OUT/LB3-done.out" 2>&1
  lb3_done_rc=$?
  lb3_at_base=0; grep -qF "at the base" "$OUT/LB3-basecheck.tsv" && lb3_at_base=1
  lb3_no_viol=1; grep -qP '^lineage\t[^\t]*\tviolation\t' "$OUT/LB3-basecheck.tsv" && lb3_no_viol=0
  if [ "$lb3_done_rc" = 0 ] && [ "$lb3_at_base" = 1 ] && [ "$lb3_no_viol" = 1 ] && [ "$lb3_bc_rc" = 0 ]; then
    it_pass LB3 "fleet/it/LB/out/LB3-basecheck.tsv" \
      "running the one command the seed printed cleared the gate: base-check reports 'at the base' with no violation (exit 0) and the same \`propose --status done\` that was refused in LB2 now succeeds. The pair is the assertion — LB2 alone would pass against a gate that refuses every claim of done, which would be a worse product than the defect it fixes"
  else
    it_fail LB3 "fleet/it/LB/out/LB3-basecheck.tsv" \
      "done_rc=$lb3_done_rc(want 0) at-base=$lb3_at_base no-violation=$lb3_no_viol basecheck_rc=$lb3_bc_rc(want 0)"
  fi

  # ================================================================================================
  # LB4 — THE STALE-NATIVE WARNING FIRES, AND CLEARS.  The check that actually caught something in the
  #       real incident: *"basecheck additionally warned that the prebuilt native artifacts were still the
  #       GOLDEN ones — material here because this milestone is a velox change."*
  #
  #       Both halves are required. A warning that cannot clear is an alarm that gets ignored (`SD-4`), and
  #       this one is judged by mtime against the last checkout precisely so a rebuild clears it.
  # ================================================================================================
  lb4_fires=0
  grep -qi 'STALE NATIVE ARTIFACTS' "$OUT/LB3-basecheck.tsv" && lb4_fires=1
  # "Rebuild": the artifact becomes newer than the checkout that moved the source.
  sleep 1; touch "$SLOT/alpha/libvelox.so"
  fleet base-check --id "$TODO" --porcelain > "$OUT/LB4-after-rebuild.tsv" 2>&1
  lb4_clears=1
  grep -qi 'STALE NATIVE ARTIFACTS' "$OUT/LB4-after-rebuild.tsv" && lb4_clears=0
  lb4_info=0
  grep -qP '^lineage\t[^\t]*\tinfo\t[^\t]*STALE NATIVE' "$OUT/LB3-basecheck.tsv" && lb4_info=1
  if [ "$lb4_fires" = 1 ] && [ "$lb4_clears" = 1 ] && [ "$lb4_info" = 1 ]; then
    it_pass LB4 "fleet/it/LB/out/LB3-basecheck.tsv" \
      "the stale-native warning FIRED once the source moved off the commit the slot was leased at (libvelox.so predating the checkout) and CLEARED when the artifact was rebuilt — and it is severity=info, never a refusal, because a JVM-only milestone is legitimately unaffected and nothing here can tell whether this milestone touches native code. This is the check that actually caught something in the real incident, and the half that clears is what stops it becoming an alarm nobody reads"
  else
    it_fail LB4 "fleet/it/LB/out/LB4-after-rebuild.tsv" \
      "fires-when-stale=$lb4_fires clears-after-rebuild=$lb4_clears severity-is-info=$lb4_info"
  fi
fi

it_assert_isolation LB-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict" >&2; exit 3; }
sed -i "s|$INSTANT/||g" "$RESULTS"
echo "§LB done: IT_FAILED=$IT_FAILED"
#: `II-11`. Was `exit "$IT_FAILED"` — a COUNT. `exit` truncates modulo 256, so a section with
#: exactly 256 failures reported SUCCESS, and one with 300 reported 44, a number meaning nothing
#: to any reader. An exit status is a one-byte verdict, not a tally: the count is already printed
#: on the line above and is in the register, which is where a consumer should read it anyway.
if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
exit 1
