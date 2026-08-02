#!/usr/bin/env bash
# The permanently-leaked slot. Found by the §E re-run under W-1 (E9 FAIL, 2 unrecoverable orphans in 80
# iterations), then reduced to this deterministic case by the successor.
#
# `mkdir` IS the lock (`pool` docstring) and the body `lease.json` is written INSIDE the claim afterwards.
# A crash between the body's write and its rename therefore leaves a claim dir holding only
# `.lease.json.<pid>.<ns>.<rand>.tmp`. From there:
#
#   * every READER reads the BODY  -> the slot is free
#   * every CLAIMANT tests the DIR -> the slot is taken
#
# so the slot was simultaneously free and unclaimable, and `reap` — the verb the refusal NAMES as the
# remedy — reported success while freeing nothing.
#
# ***THESE CASES ARE NOW INVERTED.*** They asserted the defect while it stood, which is what made the fix
# falsifiable; they now assert the REPAIRED behaviour. Inverted rather than deleted, deliberately: a
# regression case that is removed once it goes green takes the description of the defect with it, and the
# next person to touch `pool.claim` has nothing telling them what the ordering is load-bearing for. Each
# case below says what it used to prove and what it proves now.
#
# This runs NO tmux, spawns no session and touches no live store: it is pure lease-file state.
# Run: bash fleet/it/run-e9-leak.sh
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
it_own_cases 'E9-leak-[a-z]+'

# `it_section` rather than hand-rolled variables: it is what asserts the isolation contract on entry, and
# §A's A2c audit found this runner (and run-m9-mutation.sh) skipping it entirely — running without ever
# re-diffing the live stores, which the plan forbids in as many words.
rm -rf "$IT_ROOT/E9leak"
it_section E9leak
OUT="$EV/out"
mkdir -p "$OUT" "$EV/slots/s1" "$EV/slots/s2" "$EV/slots/s3"

bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2

for s in s1 s2 s3; do
  fleet enroll --slot "$EV/slots/$s" > "$OUT/enroll-$s.out" 2>&1 \
    || { echo "enrolment of $s failed — every assertion below would be vacuous" >&2; exit 2; }
done
fleet leases --porcelain > "$OUT/leases-baseline.tsv" 2>/dev/null
if [ "$(grep -c 'free' "$OUT/leases-baseline.tsv")" -ne 3 ]; then
  echo "baseline is not three free slots; refusing to measure" >&2; exit 2
fi

# --- plant the interrupted claim -------------------------------------------------------------------
# The body is COMPLETE and VALID JSON, written under the exact tmp name `atomic.tmp_name` produces. The
# kill lands between write() and rename(), which is a window of real width: the §E re-run hit it twice in
# 80 SIGKILL iterations.
mkdir -p "$FLEET_HOME/pool/leases/s2"
python3 - "$FLEET_HOME" "$EV/slots/s2" <<'PY' > "$OUT/plant.txt"
import json, pathlib, sys
from fleet.atomic import tmp_name
home, slotpath = pathlib.Path(sys.argv[1]), sys.argv[2]
d = home / "pool" / "leases" / "s2"
body = {"slot": "s2", "path": slotpath, "todo_id": "victim-1", "tmux": "dt-victim",
        "base_instant": "00000000", "child_instant": "x",
        "claimed_at": "2026-07-30T15:00:00Z", "claimed_ns": 1}
#: the real staging name, from the product's own helper — not a hand-guessed one.
(d / tmp_name("lease.json")).write_text(json.dumps(body, indent=2))
print("claim dir:", sorted(p.name for p in d.iterdir()))
PY
cat "$OUT/plant.txt"

# --- E9-leak-a · GIVEN the planted interrupted claim, WHEN `leases` is read, ------------------------
# THEN s2 reads INTERRUPTED and not free.
fleet leases --porcelain > "$OUT/leases-after-plant.tsv" 2>/dev/null
# WAS: asserted 'leases' reports s2 FREE. NOW: it must report `interrupted` -- an unclaimable slot described
# as free is an answer that gets you NoCapacity, and it was half of the two-authorities disagreement.
if grep -qP '^s2\tinterrupted' "$OUT/leases-after-plant.tsv"; then
  it_pass E9-leak-a "fleet/it/E9leak/out/leases-after-plant.tsv" \
    "the leases view reports s2 as INTERRUPTED, not free (it reported 'free' before the fix, while no claimant could take it)"
elif grep -qP '^s2\tfree' "$OUT/leases-after-plant.tsv"; then
  it_fail E9-leak-a "fleet/it/E9leak/out/leases-after-plant.tsv" \
    "REGRESSION: the leases view is back to calling an unclaimable slot 'free'"
else
  it_fail E9-leak-a "fleet/it/E9leak/out/leases-after-plant.tsv" \
    "s2 is in neither expected state: $(tr '\n' ' ' < "$OUT/leases-after-plant.tsv")"
fi

# --- E9-leak-b · GIVEN that claim aged past INTERRUPTED_CLAIM_AGE_S, WHEN `reap --all` runs, --------
# THEN it RECLAIMS s2 and says so under its own row kind.
# WAS: asserted `reap --all` exits 0 reporting "0 of them leased; 0 freed, 0 could not be freed" -- absence
# presented as success, with even the "could not be freed" counter at zero.
# NOW: it must reclaim the claim and name it under its own row kind.
#
# The claim's mtime is set back rather than the age floor being lowered: reclaiming is gated on
# INTERRUPTED_CLAIM_AGE_S so that a claim mid-birth is never deleted, and a case that relaxes the guard it is
# verifying proves only that the guard is relaxable. This exercises the SHIPPED default.
touch -d '2 hours ago' "$FLEET_HOME/pool/leases/s2" 2>/dev/null || true
fleet reap --all --porcelain > "$OUT/reap.tsv" 2>&1; reap_rc=$?
if grep -q 'reap-reclaimed' "$OUT/reap.tsv" && grep -q 's2' "$OUT/reap.tsv"; then
  it_pass E9-leak-b "fleet/it/E9leak/out/reap.tsv" \
    "reap RECLAIMED the interrupted claim on s2 and named it under its own kind reap-reclaimed (rc=$reap_rc). Before the fix this exited 0 reporting '0 of them leased; 0 freed, 0 could not be freed'"
else
  it_fail E9-leak-b "fleet/it/E9leak/out/reap.tsv" \
    "REGRESSION: reap did not reclaim it or did not name it (rc=$reap_rc): $(tr '\n' ' ' < "$OUT/reap.tsv" | head -c 300)"
fi

# --- E9-leak-c · GIVEN the reap has run, WHEN free_slots(), lease() and the claim path are each asked, ---
# THEN all three agree s2 is claimable — the point being agreement between readers, not any one verdict.
# WAS: asserted `claim` refuses forever while free_slots() excluded it and every body-reader called it free
# -- two disagreeing notions of "free" in one pool, reconcilable by no verb.
python3 - "$FLEET_HOME" > "$OUT/claim.txt" 2>&1 <<'PY'
import pathlib, sys
from fleet.pool import Pool
p = Pool(pathlib.Path(sys.argv[1]))
print("free_slots():", p.free_slots())
print("lease('s2') :", p.lease('s2'))
print("interrupted :", p.interrupted_claims(min_age_s=0.0))
try:
    print("claim ->", p.claim(todo_id="new", tmux="dt-new", base_instant="00000000",
                              child_instant="y", slot="s2").slot)
except Exception as e:
    print("claim REFUSED:", type(e).__name__ + ":", e)
PY
cat "$OUT/claim.txt"
if grep -q '^claim -> s2$' "$OUT/claim.txt" && grep -q 'interrupted : \[\]' "$OUT/claim.txt"; then
  it_pass E9-leak-c "fleet/it/E9leak/out/claim.txt" \
    "after the reap the slot is CLAIMABLE and no interrupted claim remains: free_slots(), lease() and the claim path all agree. Before the fix this raised NoCapacity('already leased by an unnamed claim') for the life of the store"
else
  it_fail E9-leak-c "fleet/it/E9leak/out/claim.txt" \
    "REGRESSION: the slot did not come back: $(tr '\n' ' ' < "$OUT/claim.txt" | head -c 300)"
fi

# --- E9-leak-d · GIVEN a pool exhausted by an interrupted claim, WHEN a dispatch is refused, --------
# THEN the refusal NAMES s3, says it is a dead writer rather than work in progress, and points at the fix.
# WAS: asserted the refusal counts the leaked slot as leased and sends the operator to `reap`, which was
# inert on exactly that -- `FI-30a`'s unclearable alarm, in the component a coordinator depends on for
# workspaces.
# NOW: `reap` genuinely clears it, so the old sentence became true. That is not enough on its own: an
# exhausted pool must not READ THE SAME whether its slots are doing work or merely lost. A fresh interrupted
# claim is planted and the refusal must name it.
#
# s2 is held by case c at this point, so s3 gets the fresh interrupted claim and s1 is claimed to exhaust.
mkdir -p "$FLEET_HOME/pool/leases/s3"
python3 - "$FLEET_HOME" > "$OUT/plant2.txt" 2>&1 <<'PY'
import pathlib, sys
from fleet.atomic import tmp_name
d = pathlib.Path(sys.argv[1]) / "pool" / "leases" / "s3"
(d / tmp_name("lease.json")).write_text('{"slot": "s3"}')
print("planted:", sorted(x.name for x in d.iterdir()))
PY
cat "$OUT/plant2.txt"
python3 - "$FLEET_HOME" > "$OUT/exhausted.txt" 2>&1 <<'PY'
import pathlib, sys
from fleet.pool import Pool
p = Pool(pathlib.Path(sys.argv[1]))
for i in range(3):
    try:
        print("claim ->", p.claim(todo_id="auto%d" % i, tmux="dt-a%d" % i,
                                  base_instant="00000000", child_instant="z").slot)
    except Exception as e:
        print("REFUSED:", type(e).__name__ + ":", e)
PY
cat "$OUT/exhausted.txt"
if grep -qi 'INTERRUPTED claim' "$OUT/exhausted.txt" \
   && grep -q "'s3'" "$OUT/exhausted.txt" \
   && grep -qi 'reap' "$OUT/exhausted.txt"; then
  it_pass E9-leak-d "fleet/it/E9leak/out/exhausted.txt" \
    "the exhausted-pool refusal now NAMES the interrupted claim ('s3'), says it is a dead writer rather than work in progress, and points at reap -- which E9-leak-b proves actually clears it. Before the fix the same sentence named a remedy that was inert, which is FI-30a's unclearable alarm"
else
  it_fail E9-leak-d "fleet/it/E9leak/out/exhausted.txt" \
    "the refusal does not distinguish a lost slot from a busy one: $(tr '\n' ' ' < "$OUT/exhausted.txt" | head -c 400)"
fi

# Leave the store clean: the planted claim is this runner's litter, not a finding.
fleet reap --all >/dev/null 2>&1 || true
rm -rf "$FLEET_HOME/pool/leases/s3"

it_assert_isolation E9leak-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict from this run" >&2; exit 3; }
echo "E9-leak done: IT_FAILED=$IT_FAILED  (PASS here now means the FIX holds; these cases were inverted when it landed)"
#: `II-11`. Was `exit "$IT_FAILED"` — a COUNT. `exit` truncates modulo 256, so a section with
#: exactly 256 failures reported SUCCESS, and one with 300 reported 44, a number meaning nothing
#: to any reader. An exit status is a one-byte verdict, not a tally: the count is already printed
#: on the line above and is in the register, which is where a consumer should read it anyway.
if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
exit 1
