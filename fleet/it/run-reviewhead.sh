#!/usr/bin/env bash
# §RH — a review round is bound to the head it reviewed, end to end against a REAL git repo in a REAL
# leased slot. Tasks 1-5 made `fleet review` record the slot's repo HEADs on each round and made
# `propose --status done` refuse (exit 4, `review-head` in stderr) when the newest measured round's
# heads differ from the slot's current HEADs. Unit tests (`test_cli.py::TestProposeDoneRefusesAn
# UnreviewedHead`) prove this against a fake git; this section proves it against a real one:
#
#   RH1 review at HEAD, then propose done                -> 0 (admitted)
#   RH2 commit after the round, then propose done         -> 4, `review-head` named
#   RH3 review again at the new head, then propose done   -> 0 (admitted again)
#
# The slot is positioned AT the lineage base before any case runs, so `_lineage_gate` (`SI-32`, §LB)
# already admits `propose --status done` and the only gate under test here is `review-head`.
#
# Run: bash fleet/it/run-reviewhead.sh
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
it_own_cases 'RH[0-9]+|ISOLATION-RH-(enter|leave)'

it_section RH
OUT="$EV/out"; rm -rf "$OUT"; mkdir -p "$OUT"
export FLEET_INSTANTS="$EV/instants"; rm -rf "$FLEET_INSTANTS"; mkdir -p "$FLEET_INSTANTS"
rm -rf "$FLEET_HOME"; mkdir -p "$FLEET_HOME"

bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2

PATH="$IT_ROOT/bin:$PATH"; export PATH
trap 'it_cleanup_tmux; tmux -L "$IT_TMUX_SOCKET" kill-server 2>/dev/null' EXIT

# ---- the slot: one repo, one commit, the lineage base IS the slot's current head ----------------------
SLOT="$OUT/slot"
mkdir -p "$SLOT/alpha"
(
  cd "$SLOT/alpha" && git init -q . && git config user.email it@fleet && git config user.name it
  echo base > f.txt && git add -A && git commit -q -m "A: base"
) >/dev/null 2>&1
L="$(git -C "$SLOT/alpha" rev-parse HEAD)"
{ echo "lineage base L = $L"; echo "slot HEAD      = $(git -C "$SLOT/alpha" rev-parse HEAD)"; } > "$OUT/fixture.txt"
cat "$OUT/fixture.txt"

# A profile whose SEED renders the generated instruction (unused by these cases, kept for parity with §LB).
cp -r "$INSTANT/tests/fixtures/profiles/workerCompliant" "$OUT/profile"

fleet set-golden --path "$SLOT" > "$OUT/setup.out" 2>&1
fleet enroll --slot "$SLOT" >> "$OUT/setup.out" 2>&1

fleet dispatch --profile "$OUT/profile" --title "reviewHead" --base 00000000 --optype append \
      --lineage-base "alpha=$L" --porcelain > "$OUT/RH-dispatch.out" 2>&1
W="$(awk -F'\t' '$1=="instant"{print $2}' "$OUT/RH-dispatch.out")"
if [ -z "$W" ] || [ ! -d "$W" ]; then
  it_fail RH1 "fleet/it/RH/out/RH-dispatch.out" \
    "the dispatch produced no instant: $(head -2 "$OUT/RH-dispatch.out" | tr '\n' ' ')"
  it_fail RH2 "fleet/it/RH/out/RH-dispatch.out" "no instant to test against — dispatch failed"
  it_fail RH3 "fleet/it/RH/out/RH-dispatch.out" "no instant to test against — dispatch failed"
else
  fleet milestone --instant "$W" --id m1 --title "the reviewed work" --porcelain > "$OUT/RH-milestone.out" 2>&1

  # Position the slot AT the lineage base before any case runs, so `_lineage_gate` admits `propose
  # --status done` from the first case on and only `review-head` is exercised below.
  git -C "$SLOT/alpha" checkout -q --detach "$L" 2>>"$OUT/RH-checkout.err"

  # ================================================================================================
  # RH1 — REVIEW AT THE SLOT'S CURRENT HEAD, THEN PROPOSE DONE: ADMITTED.
  # ================================================================================================
  fleet review --instant "$W" --scope all --verdict READY \
        --finding "RV-1:Minor:applied:SPEC.md:reviewed here:none" > "$OUT/RH1-review.out" 2>&1
  rh1_review_rc=$?
  fleet propose --instant "$W" --milestone m1 --status "done" --evidence "evidence/INDEX.md" \
        > "$OUT/RH1-propose.out" 2>&1
  rh1_propose_rc=$?
  if [ "$rh1_review_rc" = 0 ] && [ "$rh1_propose_rc" = 0 ]; then
    it_pass RH1 "fleet/it/RH/out/RH1-propose.out" \
      "the round was recorded at the slot's current head (review exit $rh1_review_rc) and \`propose --status done\` was admitted (exit $rh1_propose_rc) — the newest round and the slot agree"
  else
    it_fail RH1 "fleet/it/RH/out/RH1-propose.out" \
      "review_rc=$rh1_review_rc(want 0) propose_rc=$rh1_propose_rc(want 0) :: $(head -2 "$OUT/RH1-propose.out" | tr '\n' ' ')"
  fi

  # ================================================================================================
  # RH2 — A COMMIT AFTER THE ROUND REFUSES THE CLAIM, NAMING `review-head`.
  # ================================================================================================
  git -C "$SLOT/alpha" commit --allow-empty -qm "post-review fix" > "$OUT/RH2-commit.out" 2>&1
  fleet propose --instant "$W" --milestone m1 --status "done" --evidence "evidence/INDEX.md" \
        > "$OUT/RH2-propose.out" 2>&1
  rh2_propose_rc=$?
  rh2_named=0; grep -qF "review-head" "$OUT/RH2-propose.out" && rh2_named=1
  if [ "$rh2_propose_rc" = 4 ] && [ "$rh2_named" = 1 ]; then
    it_pass RH2 "fleet/it/RH/out/RH2-propose.out" \
      "a commit landed on the slot after the round the ledger reviewed; \`propose --status done\` was REFUSED (exit $rh2_propose_rc), naming \`review-head\` — the head being graded carries a commit no round has seen"
  else
    it_fail RH2 "fleet/it/RH/out/RH2-propose.out" \
      "propose_rc=$rh2_propose_rc(want 4) names-review-head=$rh2_named :: $(head -2 "$OUT/RH2-propose.out" | tr '\n' ' ')"
  fi

  # ================================================================================================
  # RH3 — REVIEWING THE NEW HEAD CLEARS IT: PROPOSE DONE IS ADMITTED AGAIN.
  # ================================================================================================
  fleet review --instant "$W" --scope code --verdict READY \
        --finding "RV-2:Minor:applied:SPEC.md:re-reviewed at the new head:none" > "$OUT/RH3-review.out" 2>&1
  rh3_review_rc=$?
  fleet propose --instant "$W" --milestone m1 --status "done" --evidence "evidence/INDEX.md" \
        > "$OUT/RH3-propose.out" 2>&1
  rh3_propose_rc=$?
  if [ "$rh3_review_rc" = 0 ] && [ "$rh3_propose_rc" = 0 ]; then
    it_pass RH3 "fleet/it/RH/out/RH3-propose.out" \
      "reviewing the new head (review exit $rh3_review_rc) cleared the mismatch — \`propose --status done\` was admitted again (exit $rh3_propose_rc)"
  else
    it_fail RH3 "fleet/it/RH/out/RH3-propose.out" \
      "review_rc=$rh3_review_rc(want 0) propose_rc=$rh3_propose_rc(want 0) :: $(head -2 "$OUT/RH3-propose.out" | tr '\n' ' ')"
  fi
fi

it_assert_isolation RH-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict" >&2; exit 3; }
sed -i "s|$INSTANT/||g" "$RESULTS"
echo "§RH done: IT_FAILED=$IT_FAILED"
#: `II-11`. An exit status is a one-byte verdict, not a tally — see §LB for why this is not
#: `exit "$IT_FAILED"`.
if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
exit 1
