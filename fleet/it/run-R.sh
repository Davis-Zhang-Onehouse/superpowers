#!/usr/bin/env bash
# §R — per-root isolation.  docs/superpowers/specs/2026-09-06-fleet-root-isolation-design.md
#
# Two marked roots side by side, driven through the REAL marker walk: every case runs with FLEET_HOME,
# FLEET_INSTANTS and FLEET_TMUX_SOCKET UNSET and a fake $HOME, so what resolves the destination is the
# `.fleet-root` file and nothing else. A case that exported a store would be testing tier 3 and claiming
# to test tier 5.
#
# The roots are named `itr1` and `itr2`, not `davis`, and that is not cosmetic: the socket derives from
# the declared name, R2 starts REAL tmux servers on the derived sockets, and a root named `davis` here
# would have this section starting and killing servers that a live fleet may be using.
#
# Four of the eight cases are refusals with a known-bad input available today, so they were written and
# run RED before the fix existed (`FI-303`: a control that cannot fire on the defect that motivated it
# certifies its own blind spot). R7 is the regression half and is the one that matters most for
# confidence: 1291 occurrences across 238 files name the store explicitly, and none of them may move.
#
# Run: bash fleet/it/run-R.sh
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
it_own_cases 'R[0-9]+[a-z]?|ISOLATION-R-(enter|leave)'

it_section R
it_fresh_store

# The derived sockets are real tmux servers (R2). They are outside `$TMUX_PREFIX`, so `it_cleanup_tmux`
# cannot see them and they are torn down by name.
trap 'it_cleanup_tmux; for s in fleet-itr1 fleet-itr2; do tmux -L "$s" kill-server 2>/dev/null; done;
      tmux -L "$IT_TMUX_SOCKET" kill-server 2>/dev/null' EXIT

OUT="$EV/out"; rm -rf "$OUT"; mkdir -p "$OUT"
bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2

# A fake $HOME holding both roots. The walk stops BELOW $HOME, so the roots must be its children — which
# is also the shape the design specifies for the real box.
RHOME="$EV/home"; rm -rf "$RHOME"
R1="$RHOME/itr1_root"; R2D="$RHOME/itr2_root"
for pair in "$R1:itr1" "$R2D:itr2"; do
  d="${pair%%:*}"; n="${pair##*:}"
  mkdir -p "$d/ws1" "$d/instants"
  printf '{"name": "%s"}\n' "$n" > "$d/.fleet-root"
done
UNMARKED="$RHOME/unmarked"; mkdir -p "$UNMARKED"

# Every fleet call in this section: a clean environment, a fake HOME, and a cwd that decides the answer.
# `env -u` rather than a subshell unset, so nothing can leak in from `it_section`'s exports.
r_fleet() {                        # r_fleet <cwd> <args...>
  local cwd="$1"; shift
  ( cd "$cwd" && env -u FLEET_HOME -u FLEET_INSTANTS -u FLEET_TMUX_SOCKET -u FLEET_ROOT \
      HOME="$RHOME" PYTHONPATH="$INSTANT/src" python3 -m fleet.cli "$@" )
}
py() { env PYTHONPATH="$INSTANT/src" python3 - "$@"; }

# ==================================================================================================
# R1 — two roots, two stores, nothing shared.
# ==================================================================================================
r1_rc=0
r_fleet "$R1/ws1"   init --name r1subject --optype append --instants-dir "$R1/instants"   \
        > "$OUT/R1-init1.out" 2>&1 || r1_rc=1
r_fleet "$R2D/ws1"  init --name r2subject --optype append --instants-dir "$R2D/instants"  \
        > "$OUT/R1-init2.out" 2>&1 || r1_rc=1
{
  echo "== root1 store =="; find "$R1/.fleet"  -type f | sed "s|$RHOME/||" | sort
  echo "== root2 store =="; find "$R2D/.fleet" -type f | sed "s|$RHOME/||" | sort
  echo "== root1 instants =="; ls -1 "$R1/instants"
  echo "== root2 instants =="; ls -1 "$R2D/instants"
} > "$OUT/R1-stores.txt" 2>&1
cat "$OUT/R1-stores.txt"
r1_both=0; [ -d "$R1/.fleet" ] && [ -d "$R2D/.fleet" ] && r1_both=1
# Disjointness asserted by CONTENT, not by path: two directories with different names prove nothing.
r1_x1=0; grep -q 'r2subject' -r "$R1/.fleet"  2>/dev/null || r1_x1=1
r1_x2=0; grep -q 'r1subject' -r "$R2D/.fleet" 2>/dev/null || r1_x2=1
r1_own1=0; [ -n "$(find "$R1/instants"  -maxdepth 1 -name '*r1subject*')" ] && r1_own1=1
r1_own2=0; [ -n "$(find "$R2D/instants" -maxdepth 1 -name '*r2subject*')" ] && r1_own2=1
if [ "$r1_rc" = 0 ] && [ "$r1_both$r1_x1$r1_x2$r1_own1$r1_own2" = "11111" ]; then
  it_pass R1 "fleet/it/R/out/R1-stores.txt" \
    "two marked roots each resolved their OWN store from the marker alone — FLEET_HOME unset in both calls — and neither store mentions the other's subject. Disjointness is asserted on CONTENT rather than on the two directories having different names, which would prove nothing"
else
  it_fail R1 "fleet/it/R/out/R1-stores.txt" \
    "rc=$r1_rc both-stores=$r1_both root1-clean=$r1_x1 root2-clean=$r1_x2 own1=$r1_own1 own2=$r1_own2"
fi

# ==================================================================================================
# R2 — two roots, two tmux SERVERS. `close`/`abort`/`harvest` kill BY NAME, so a shared server means
#      one root can kill the other's identically-named session.
# ==================================================================================================
py "$R1" "$R2D" "$RHOME" > "$OUT/R2-sockets.txt" 2>&1 <<'PY'
import os, pathlib, sys
from fleet import cli
r1, r2, home = (pathlib.Path(a) for a in sys.argv[1:4])
env = {"HOME": str(home)}
parsed = cli.parse(cli.VERBS["board"], [])
print("root1 socket:", cli.resolve_socket(parsed, env, r1 / "ws1"))
print("root2 socket:", cli.resolve_socket(parsed, env, r2 / "ws1"))
PY
cat "$OUT/R2-sockets.txt"
r2_s1="$(awk -F': ' '/^root1 socket:/{print $2}' "$OUT/R2-sockets.txt")"
r2_s2="$(awk -F': ' '/^root2 socket:/{print $2}' "$OUT/R2-sockets.txt")"
# Resolution is half the claim. The other half is that the two servers really cannot see each other, so
# a session name present on one is absent from the other — which is the property `close` depends on.
tmux -L "$r2_s1" new-session -d -s dt-collide sleep 60 2>/dev/null
tmux -L "$r2_s2" new-session -d -s dt-collide sleep 60 2>/dev/null
{
  echo "== sessions on $r2_s1 =="; tmux -L "$r2_s1" ls -F '#{session_name}' 2>&1
  echo "== killing dt-collide on $r2_s1 only =="; tmux -L "$r2_s1" kill-session -t '=dt-collide' 2>&1
  echo "== after: $r2_s1 =="; tmux -L "$r2_s1" ls -F '#{session_name}' 2>&1
  echo "== after: $r2_s2 =="; tmux -L "$r2_s2" ls -F '#{session_name}' 2>&1
} > "$OUT/R2-servers.txt" 2>&1
cat "$OUT/R2-servers.txt"
r2_named=0; [ "$r2_s1" = "fleet-itr1" ] && [ "$r2_s2" = "fleet-itr2" ] && r2_named=1
r2_survived=0
awk '/^== after: fleet-itr2 ==$/{s=1;next} s&&/dt-collide/{f=1} END{exit f?0:1}' "$OUT/R2-servers.txt" \
  && r2_survived=1
if [ "$r2_named" = 1 ] && [ "$r2_survived" = 1 ]; then
  it_pass R2 "fleet/it/R/out/R2-servers.txt" \
    "the two roots derive DIFFERENT tmux servers from their declared names ($r2_s1 / $r2_s2), and killing session 'dt-collide' by name on one leaves the identically-named session on the other ALIVE. That kill-by-name is what close, abort and harvest do, so a shared server means one root can tear down the other's worker"
else
  it_fail R2 "fleet/it/R/out/R2-servers.txt" \
    "sockets-named=$r2_named ($r2_s1 / $r2_s2) other-root-session-survived=$r2_survived"
fi
for s in "$r2_s1" "$r2_s2"; do tmux -L "$s" kill-server 2>/dev/null; done

# ==================================================================================================
# R3a — a dispatch may not point its instants directory into ANOTHER root. `G1`, and the live half:
#       containment at dispatch is what stops FI-382 one level out.
# ==================================================================================================
cp -r "$INSTANT/tests/fixtures/profiles/workerCompliant" "$OUT/profile" 2>/dev/null
r_fleet "$R1/ws1" dispatch --profile "$OUT/profile" --title "foreignTree" --base 00000000 \
        --optype append --instants-dir "$R2D/instants" > "$OUT/R3a.out" 2>&1
r3a_rc=$?
cat "$OUT/R3a.out"
r3a_named_both=0
grep -q "$R2D/instants" "$OUT/R3a.out" && grep -q "$R1" "$OUT/R3a.out" && r3a_named_both=1
# A refusal that still created the folder would satisfy an rc-only assertion while defeating the point.
r3a_nothing=0; [ -z "$(find "$R2D/instants" -maxdepth 1 -iname '*foreigntree*' 2>/dev/null)" ] \
  && r3a_nothing=1
if [ "$r3a_rc" != 0 ] && [ "$r3a_named_both" = 1 ] && [ "$r3a_nothing" = 1 ]; then
  it_pass R3a "fleet/it/R/out/R3a.out" \
    "a dispatch from root1 naming root2's instants tree is REFUSED (rc=$r3a_rc), the message names BOTH the offending directory and the root that owns the call, and no instant was created in root2. This is the live half of G1: records live inside a store, so the reachable defect is not a foreign record but a local record whose CONTENTS point out of the root"
else
  it_fail R3a "fleet/it/R/out/R3a.out" \
    "rc=$r3a_rc (want non-zero) names-both-paths=$r3a_named_both nothing-created=$r3a_nothing"
fi

# ==================================================================================================
# R3b — a record STAMPED with another root is refused; a record with NO root is NOT MEASURED.
#       The second half is the one that stops this guard refusing every pre-isolation record.
# ==================================================================================================
py "$R1" > "$OUT/R3b-seed.txt" 2>&1 <<'PY'
import json, pathlib, sys
r1 = pathlib.Path(sys.argv[1])
recs = r1 / ".fleet" / "records"
recs.mkdir(parents=True, exist_ok=True)
base = dict(todo_id="", child_instant="/i/x", base_instant="00000000", slot="", tmux="",
            profile="", golden="", lineage_base="", title="t", dispatched_at="2026-09-06T00:00:00Z",
            override_reason="", lineage_mode="", golden_base="", milestone=None, root="",
            launched_at=None, gate_verdict=None, harvested_at=None, closed_at=None, schema_version=1)
foreign = dict(base, todo_id="foreignroot-09060000", root="/somewhere/else_root")
legacy = dict(base, todo_id="legacyroot-09060000")          # written before isolation: no root
for rec in (foreign, legacy):
    (recs / f"{rec['todo_id']}.json").write_text(json.dumps(rec, indent=2))
    print("seeded", rec["todo_id"], "root=", repr(rec["root"]))
PY
cat "$OUT/R3b-seed.txt"
# `base-check` and not `status`: a verb that ACTS on one named record goes through `_record`, while
# `status` enumerates via `subjects()` -> `store.all()`. That difference is deliberate and is asserted
# below, not worked around.
r_fleet "$R1/ws1" base-check --id foreignroot-09060000 > "$OUT/R3b-foreign.out" 2>&1; r3b_f_rc=$?
r_fleet "$R1/ws1" base-check --id legacyroot-09060000  > "$OUT/R3b-legacy.out"  2>&1; r3b_l_rc=$?
r_fleet "$R1/ws1" board                                > "$OUT/R3b-board.out"   2>&1; r3b_b_rc=$?
tail -2 "$OUT/R3b-foreign.out"; tail -2 "$OUT/R3b-legacy.out"
r3b_refused=0; [ "$r3b_f_rc" != 0 ] && grep -q 'else_root' "$OUT/R3b-foreign.out" && r3b_refused=1
r3b_legacy_ok=0; [ "$r3b_l_rc" = 0 ] && r3b_legacy_ok=1
r3b_board_ok=0; [ "$r3b_b_rc" = 0 ] && r3b_board_ok=1
if [ "$r3b_refused" = 1 ] && [ "$r3b_legacy_ok" = 1 ] && [ "$r3b_board_ok" = 1 ]; then
  it_pass R3b "fleet/it/R/out/R3b-legacy.out" \
    "three properties of the stamped-root guard, and two of them are limits rather than powers. (1) a verb ACTING on a record stamped with a foreign root refuses (rc=$r3b_f_rc, message names it). (2) a record carrying NO root still reads cleanly (rc=$r3b_l_rc) — 75 records in the live store predate this field, and treating their absent root as 'a different root' would refuse every one, which is FI-417's rule that a check unable to see something must not report an answer about it. (3) \`board\` still exits 0 (rc=$r3b_b_rc) with that same foreign record on disk: the READ path deliberately does not refuse, because one stray record making the board permanently unreadable is the FI-402 failure where a gate that is always red gets read past and takes the real alarm with it. This state is reachable only by COPYING a store between roots — dispatch containment and G3 prevent creating it — so the guard is cheap insurance, and saying so is the point"
else
  it_fail R3b "fleet/it/R/out/R3b-foreign.out" \
    "acting-verb-refused=$r3b_refused (rc=$r3b_f_rc) legacy-still-readable=$r3b_legacy_ok (rc=$r3b_l_rc) board-still-usable=$r3b_board_ok (rc=$r3b_b_rc)"
fi
rm -f "$R1/.fleet/records/foreignroot-09060000.json" "$R1/.fleet/records/legacyroot-09060000.json"

# ==================================================================================================
# R4 — `G3`. A slot outside the root cannot be ENROLLED, which is what makes "davis2 cannot lease a
#      davis_root workspace" mechanical rather than conventional.
# ==================================================================================================
r_fleet "$R1/ws1" enroll --slot "$R2D/ws1" > "$OUT/R4.out" 2>&1; r4_rc=$?
cat "$OUT/R4.out"
r4_named_both=0; grep -q "$R2D/ws1" "$OUT/R4.out" && grep -q "$R1" "$OUT/R4.out" && r4_named_both=1
r4_not_registered=0; [ ! -f "$R1/.fleet/pool/enrolled/ws1.json" ] && r4_not_registered=1
# The accept direction, or the refusal could be `enroll` being broken outright.
r_fleet "$R1/ws1" enroll --slot "$R1/ws1" > "$OUT/R4-own.out" 2>&1; r4_own_rc=$?
r4_own=0; [ "$r4_own_rc" = 0 ] && [ -f "$R1/.fleet/pool/enrolled/ws1.json" ] && r4_own=1
if [ "$r4_rc" != 0 ] && [ "$r4_named_both" = 1 ] && [ "$r4_not_registered" = 1 ] && [ "$r4_own" = 1 ]; then
  it_pass R4 "fleet/it/R/out/R4.out" \
    "enrolling root2's workspace from root1 is REFUSED (rc=$r4_rc) naming both paths and registering nothing, while root1's OWN workspace enrolls cleanly (rc=$r4_own_rc). Both directions, because a refusal alone is also what a broken \`enroll\` looks like"
else
  it_fail R4 "fleet/it/R/out/R4.out" \
    "foreign-rc=$r4_rc names-both=$r4_named_both not-registered=$r4_not_registered own-slot-enrolls=$r4_own"
fi

# ==================================================================================================
# R5 — from an UNMARKED directory a READ-ONLY verb refuses rather than reading a shared store.
#      This is the revision to SI-15, and it is the one behaviour change a user will notice.
# ==================================================================================================
mkdir -p "$RHOME/.fleet/records"        # the old shared default, present and tempting
r_fleet "$UNMARKED" board > "$OUT/R5.out" 2>&1; r5_rc=$?
cat "$OUT/R5.out"
r5_named_cwd=0; grep -q "$UNMARKED" "$OUT/R5.out" && r5_named_cwd=1
r5_clears=0;    grep -q 'Clears when' "$OUT/R5.out" && r5_clears=1
r5_created=0;   [ -z "$(ls -A "$UNMARKED" 2>/dev/null)" ] && r5_created=1
r5_readonly=0
py > "$OUT/R5-readonly.txt" 2>&1 <<'PY'
from fleet.cli import VERBS
print("board.read_only:", VERBS["board"].read_only)
PY
grep -q 'board.read_only: True' "$OUT/R5-readonly.txt" && r5_readonly=1
if [ "$r5_rc" = 2 ] && [ "$r5_named_cwd$r5_clears$r5_created$r5_readonly" = "1111" ]; then
  it_pass R5 "fleet/it/R/out/R5.out" \
    "from an unmarked directory a READ-ONLY verb exits 2 naming the cwd it searched and what clears it, creates nothing, and does NOT fall through to the shared ~/.fleet that exists two directories away. SI-15 let reads default on the ground that 'nothing is enrolled' is a real answer; under isolation that answer is about a DIFFERENT ROOT's fleet, which is FI-417's shape — a true sentence answering the wrong question"
else
  it_fail R5 "fleet/it/R/out/R5.out" \
    "rc=$r5_rc (want 2) names-cwd=$r5_named_cwd clears-when=$r5_clears created-nothing=$r5_created board-is-read-only=$r5_readonly"
fi

# ==================================================================================================
# R6 — `SI-56` / `FI-382`. A verb that CREATES an instant refuses when nobody named the directory.
# ==================================================================================================
r_fleet "$R1/ws1" init --name r6stray --optype append > "$OUT/R6.out" 2>&1; r6_rc=$?
cat "$OUT/R6.out"
r6_cites=0;   grep -q 'SI-56' "$OUT/R6.out" && r6_cites=1
r6_nothing=0; [ -z "$(find "$R1/.fleet" -name '*r6stray*' 2>/dev/null)" ] && r6_nothing=1
# The accept direction: naming the directory clears it. Otherwise "refuses" could mean `init` is broken.
r_fleet "$R1/ws1" init --name r6named --optype append --instants-dir "$R1/instants" \
        > "$OUT/R6-named.out" 2>&1; r6_named_rc=$?
r6_named=0; [ "$r6_named_rc" = 0 ] \
  && [ -n "$(find "$R1/instants" -maxdepth 1 -name '*r6named*')" ] && r6_named=1
if [ "$r6_rc" != 0 ] && [ "$r6_cites$r6_nothing$r6_named" = "111" ]; then
  it_pass R6 "fleet/it/R/out/R6.out" \
    "creating an instant with the home DERIVED and no instants directory named is refused (rc=$r6_rc, cites SI-56) and plants nothing under the derived store, while the same call with --instants-dir succeeds. This is NOT fixed by isolation and the guard is what closes it: under isolation the stray would land in \$ROOT/.fleet/instants — the right root and still the wrong tree, invisible until an endgame compaction cannot find the worker"
else
  it_fail R6 "fleet/it/R/out/R6.out" \
    "rc=$r6_rc (want non-zero) cites-SI-56=$r6_cites nothing-created=$r6_nothing named-form-works=$r6_named"
fi

# ==================================================================================================
# R7 — THE REGRESSION CASE. 1291 occurrences across 238 files name the store explicitly; tiers 1 and 3
#      must resolve exactly as they did before. Run from an UNMARKED cwd, so the marker cannot rescue
#      a broken flag path and make this pass for the wrong reason.
# ==================================================================================================
R7S="$OUT/r7store"; mkdir -p "$R7S/records"
r_fleet "$UNMARKED" board --home "$R7S" --porcelain > "$OUT/R7-flag.out" 2>&1;  r7_flag_rc=$?
( cd "$UNMARKED" && env -u FLEET_INSTANTS -u FLEET_TMUX_SOCKET -u FLEET_ROOT HOME="$RHOME" \
    FLEET_HOME="$R7S" PYTHONPATH="$INSTANT/src" python3 -m fleet.cli board --porcelain ) \
    > "$OUT/R7-env.out" 2>&1; r7_env_rc=$?
# And the store each one actually chose, from the stderr line G2 prints.
r_fleet "$UNMARKED" board --home "$R7S" > "$OUT/R7-flag-src.out" 2>&1
{ echo "--home rc=$r7_flag_rc"; echo "FLEET_HOME rc=$r7_env_rc"; grep '^root ' "$OUT/R7-flag-src.out"; } \
  > "$OUT/R7.txt" 2>&1
cat "$OUT/R7.txt"
r7_ok=0; [ "$r7_flag_rc" = 0 ] && [ "$r7_env_rc" = 0 ] && r7_ok=1
r7_src=0; grep -q "root $R7S (--home)" "$OUT/R7-flag-src.out" && r7_src=1
if [ "$r7_ok" = 1 ] && [ "$r7_src" = 1 ]; then
  it_pass R7 "fleet/it/R/out/R7.txt" \
    "both explicit forms still work from a directory with NO marker above it — \`--home <store>\` and \`FLEET_HOME=<store>\` each exit 0 — and the resolved-root line names the store AND the tier it came from. Run unmarked deliberately: under a marker this case would pass even if the flag path were broken, which is the shape of a control that certifies its own blind spot"
else
  it_fail R7 "fleet/it/R/out/R7.txt" \
    "--home rc=$r7_flag_rc, FLEET_HOME rc=$r7_env_rc (both want 0), source-line-correct=$r7_src — a failure here means the 1291 explicit call sites moved"
fi

it_assert_isolation R-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict" >&2; exit 3; }
sed -i "s|$INSTANT/||g" "$RESULTS"
echo "§R done: IT_FAILED=$IT_FAILED"
if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
exit 1
