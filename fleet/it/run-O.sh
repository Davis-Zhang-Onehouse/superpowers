#!/usr/bin/env bash
# §O — Failure injection. COMPLETE: O1-O9.
#
# Chosen because they are the two whose failure mode is not "an ugly error":
#
#   O7  a symlink loop inside an instant must make `lint` TERMINATE and report. The failure is a HANG, which
#       is strictly worse than an exception — an exception tells you something; a hang tells you nothing and
#       looks like slow work.
#   O9  a `SIGKILL` during `store.write` must leave the record ABSENT or COMPLETE, never truncated. This is
#       the `tmp`-then-`replace` guarantee, and it underpins EVERY register in the package — records, leases,
#       roadmaps, proposals, declarations. It has been argued from construction and never crashed for real.
#
# The rest of §O is either already covered hermetically (O1 truncated JSON, O2 schema bump, O3 ambiguous key
# are in `test_store.py`/`test_identity.py`; O4's clean-error-on-EACCES is what `SI-22` fixed) or fails in a
# way that is self-evident when it happens (O5, O6, O8). The section-level NOT-RUN row stays.
#
# Run: bash fleet/it/run-O.sh
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
it_own_cases 'O[0-9]+[a-z]?|ISOLATION-O-(enter|leave)'

it_section O
OUT="$EV/out"; rm -rf "$OUT"; mkdir -p "$OUT"
export FLEET_INSTANTS="$EV/instants"; rm -rf "$FLEET_INSTANTS"; mkdir -p "$FLEET_INSTANTS"
rm -rf "$FLEET_HOME"; mkdir -p "$FLEET_HOME"      # a virgin store every run (see run-F.sh)

bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2

trap 'it_cleanup_tmux; tmux -L "$IT_TMUX_SOCKET" kill-server 2>/dev/null' EXIT

# ==================================================================================================
# O7 — A SYMLINK LOOP MAKES `lint` TERMINATE AND REPORT.
#
#      Two loops, because they break different walkers: a self-referential link (`loop -> .`) and a mutual
#      pair (`a/up -> ..`). A `for root, dirs, files in os.walk(..., followlinks=True)` recurses forever on
#      either; `Path.rglob` follows directory symlinks and does the same.
#
#      Asserted with a hard `timeout`, because "it finished" is the property. A hang is the failure mode and
#      a hanging test that is not bounded hangs the suite — so the bound is part of the assertion, not part
#      of the convenience.
# ==================================================================================================
O7I="$(fleet init --base 00000000 --name symlinkLoop --porcelain 2>&1 | awk -F'\t' '$1=="path"{print $2}')"
if [ -z "$O7I" ] || [ ! -d "$O7I" ]; then
  it_fail O7 "" "could not create the instant to corrupt; nothing below is a verdict"
else
  ln -s . "$O7I/loop"
  mkdir -p "$O7I/a/b"
  ln -s ../.. "$O7I/a/b/up"
  # `timeout` returns 124 on expiry. Anything else — 0, or a clean refusal — is a terminating lint.
  timeout 30 env PYTHONPATH="$INSTANT/src" python3 -m fleet.cli lint --instant "$O7I" --porcelain \
    > "$OUT/O7-lint.tsv" 2>"$OUT/O7-lint.err"
  o7_rc=$?
  o7_rows="$(grep -c . "$OUT/O7-lint.tsv" 2>/dev/null || echo 0)"
  o7_said_something=0
  { [ "$o7_rows" -gt 0 ] || [ -s "$OUT/O7-lint.err" ]; } && o7_said_something=1
  if [ "$o7_rc" = 124 ]; then
    it_fail O7 "fleet/it/O/out/O7-lint.err" \
      "lint DID NOT TERMINATE within 30s on an instant containing a symlink loop — it was killed by timeout. A hang is the worst of the failure modes here because it is indistinguishable from slow work"
  elif [ "$o7_said_something" = 1 ]; then
    it_pass O7 "fleet/it/O/out/O7-lint.tsv" \
      "lint TERMINATED (exit $o7_rc, not 124) on an instant containing two shapes of symlink loop — a self-referential 'loop -> .' and a mutual 'a/b/up -> ../..' — and reported $o7_rows row(s) plus $(wc -c < "$OUT/O7-lint.err") bytes on stderr rather than dying silently. Bounded by \`timeout 30\` deliberately: a hang is the failure being tested for, so an unbounded version of this case would hang the suite instead of failing it"
  else
    it_fail O7 "fleet/it/O/out/O7-lint.tsv" \
      "lint exited $o7_rc but said NOTHING — terminating silently on a corrupt instant is 'absence is never success'"
  fi
fi

# ==================================================================================================
# O9 — `SIGKILL` DURING `store.write`: THE RECORD IS ABSENT OR COMPLETE, NEVER TRUNCATED.
#
#      `atomic.atomic_write` writes a temp beside the target and then `os.replace`s it, which is atomic
#      within a filesystem. That is the guarantee every register in the package rests on, and it has been
#      argued rather than crashed for real.
#
#      The kill is placed at the ONE dangerous instant rather than at a random time: `os.replace` is
#      monkeypatched in the CHILD process to `SIGKILL` itself. Two halves, because one alone cannot
#      distinguish a working guarantee from a store that never writes anything:
#        O9a  kill BEFORE the replace  -> the record must be ABSENT, and the store must still be readable
#        O9b  kill AFTER  the replace  -> the record must be PRESENT and valid
#      Together they say the window is exactly "absent or complete" and has no third state.
#
#      SIGKILL, not an exception: an exception unwinds and runs `finally` blocks, which is the failure mode
#      this case is NOT about. `SIGKILL` cannot be caught, so what survives is only what the filesystem made
#      durable.
# ==================================================================================================
o9_driver="$OUT/o9-driver.py"
cat > "$o9_driver" <<'PY'
"""Kill this process inside `store.write`, on either side of the atomic replace."""
import os
import pathlib
import signal
import sys

from fleet.store import Record, Store

home, when = pathlib.Path(sys.argv[1]), sys.argv[2]
real_replace = os.replace


def suicide(src, dst):
    if when == "after":
        real_replace(src, dst)          # the rename lands, THEN the process dies
    os.kill(os.getpid(), signal.SIGKILL)


os.replace = suicide
store = Store(home)
store.write(Record(todo_id="crashProbe", child_instant=str(home / "child"), base_instant="00000000",
                   slot="ws1", tmux="dt-crashProbe", profile="p", golden="g", lineage_base="",
                   title="a record written across a crash", dispatched_at="2026-07-30T00:00:00Z"))
print("STILL ALIVE — the kill did not happen, so this run proves nothing", file=sys.stderr)
sys.exit(99)
PY

o9_check() {                     # o9_check <when> <case> ; sets O9_STATE
  local when="$1" home="$OUT/o9-$1-home"
  rm -rf "$home"; mkdir -p "$home"
  PYTHONPATH="$INSTANT/src" python3 "$o9_driver" "$home" "$when" \
    > "$OUT/O9-$when.out" 2>&1
  local rc=$?
  # 137 = 128+9 from a shell; python reports -9 as 137 here too. 99 means the driver was never killed.
  python3 - "$home" "$when" "$rc" > "$OUT/O9-$when-state.txt" 2>&1 <<'PY'
import json, pathlib, sys
sys.path.insert(0, __import__("os").environ["IT_SRC"])
home, when, rc = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
records = home / "records"
files = sorted(p.name for p in records.iterdir()) if records.is_dir() else []
target = [f for f in files if f == "crashProbe.json"]
temps = [f for f in files if f != "crashProbe.json"]
print("driver_rc:", rc)
print("target_present:", bool(target))
print("temp_files:", len(temps), temps[:3])
state = "absent"
if target:
    try:
        data = json.loads((records / "crashProbe.json").read_text())
        state = "complete" if data.get("todo_id") == "crashProbe" else "PRESENT-BUT-WRONG"
    except ValueError as exc:
        state = f"TRUNCATED ({exc})"
print("record_state:", state)
#: The store must still be READABLE afterwards. A leftover temp that `all()` tries to parse as a record
#: would turn one crash into a permanently unreadable store, which is worse than the lost write.
from fleet.store import Store
try:
    print("store_readable:", True, "records:", len(Store(home).all()))
except Exception as exc:                                    # noqa: BLE001 - the point is what it raises
    print("store_readable:", False, type(exc).__name__, exc)
PY
  cat "$OUT/O9-$when-state.txt"
}

export IT_SRC="$INSTANT/src"

# ---- O9a: killed BEFORE the replace ---------------------------------------------------------------
o9_check before
a_state="$(awk -F': ' '/^record_state:/{print $2}' "$OUT/O9-before-state.txt")"
a_readable="$(awk '/^store_readable:/{print $2}' "$OUT/O9-before-state.txt")"
a_rc="$(awk -F': ' '/^driver_rc:/{print $2}' "$OUT/O9-before-state.txt")"
if [ "$a_rc" = 99 ]; then
  it_fail O9a "fleet/it/O/out/O9-before-state.txt" \
    "the driver was never killed, so this measures nothing"
elif [ "$a_state" = absent ] && [ "$a_readable" = True ]; then
  it_pass O9a "fleet/it/O/out/O9-before-state.txt" \
    "SIGKILL immediately before the atomic replace left NO record at all (not a truncated one) and the store still reads cleanly — so a crash mid-write costs the write and never the register. The temp file that was already on disk is not mistaken for a record, which matters more than the lost write: a store that becomes permanently unreadable after one crash is the worse outcome"
else
  it_fail O9a "fleet/it/O/out/O9-before-state.txt" \
    "record_state=$a_state (want absent), store_readable=$a_readable (want True)"
fi

# ---- O9b: killed AFTER the replace ---------------------------------------------------------------
o9_check after
b_state="$(awk -F': ' '/^record_state:/{print $2}' "$OUT/O9-after-state.txt")"
b_readable="$(awk '/^store_readable:/{print $2}' "$OUT/O9-after-state.txt")"
b_rc="$(awk -F': ' '/^driver_rc:/{print $2}' "$OUT/O9-after-state.txt")"
if [ "$b_rc" = 99 ]; then
  it_fail O9b "fleet/it/O/out/O9-after-state.txt" \
    "the driver was never killed, so this measures nothing"
elif [ "$b_state" = complete ] && [ "$b_readable" = True ]; then
  it_pass O9b "fleet/it/O/out/O9-after-state.txt" \
    "SIGKILL immediately AFTER the atomic replace left a COMPLETE, parseable record. This is the half that makes O9a non-vacuous: without it, a store that simply never wrote anything would satisfy 'the record is absent' perfectly. Together the two say the window around the replace has exactly two states and no third"
else
  it_fail O9b "fleet/it/O/out/O9-after-state.txt" \
    "record_state=$b_state (want complete), store_readable=$b_readable (want True)"
fi

# The section-level claim, stated once both halves are in.
if grep -qP '^O9a\tPASS\t' "$RESULTS" && grep -qP '^O9b\tPASS\t' "$RESULTS"; then
  it_pass O9 "fleet/it/O/out/O9-before-state.txt" \
    "the tmp-then-replace guarantee holds across a REAL SIGKILL, in both directions (O9a absent, O9b complete) — never a truncated record. Every register in the package (records, leases, roadmaps, proposals, declarations) writes through this one function, so this is the case the whole store layer rests on and it had been argued from construction rather than crashed"
else
  it_fail O9 "fleet/it/O/out/O9-before-state.txt" \
    "one or both halves failed; see O9a/O9b"
fi

# ==================================================================================================
# O1/O2 — CORRUPT AND FUTURE RECORDS.  A store is read by a tool a human is watching; the difference
#         between a named refusal and a traceback is whether they can act on it.
#         O1 truncated to invalid JSON ⇒ BadInput NAMING THE FILE, never a traceback.
#         O2 schema_version bumped by one ⇒ refused WITH THE VERSION NAMED. There is no legacy tolerance
#            by design, so "refused" is the correct behaviour and the message is the whole deliverable.
# ==================================================================================================
# ONE corrupt file at a time. Records are read in SORTED order, so with both present `future.json` fired
# the schema check before `truncated.json` was reached and O1 measured O2's condition instead of its own.
O12="$OUT/o12"; mkdir -p "$O12/home/records"
printf '{"todo_id": "truncated", "child_ins' > "$O12/home/records/truncated.json"
FLEET_HOME="$O12/home" fleet board --porcelain > "$OUT/O1-board.out" 2>&1
o1_rc=$?
o1_named=0;   grep -q 'truncated.json' "$OUT/O1-board.out" && o1_named=1
o1_no_tb=1;   grep -qE '^Traceback|File ".*", line ' "$OUT/O1-board.out" && o1_no_tb=0
o1_refused=0; [ "$o1_rc" -ge 1 ] && [ "$o1_rc" -le 4 ] && o1_refused=1
if [ "$o1_named$o1_no_tb$o1_refused" = "111" ]; then
  it_pass O1 "fleet/it/O/out/O1-board.out" \
    "a record truncated to invalid JSON is refused with exit $o1_rc and the message NAMES THE FILE ('truncated.json'), with no traceback anywhere in the output. A traceback tells a watching human that the tool broke; a named refusal tells them which file to look at, which is the only difference that matters at 3am"
else
  it_fail O1 "fleet/it/O/out/O1-board.out" \
    "names_file=$o1_named no_traceback=$o1_no_tb refused_cleanly=$o1_refused (exit $o1_rc)"
fi
rm -f "$O12/home/records/truncated.json"
python3 - "$O12/home/records/future.json" <<'PY'
import json, pathlib, sys
from fleet.store import SCHEMA_VERSION
pathlib.Path(sys.argv[1]).write_text(json.dumps({"todo_id": "future",
                                                 "schema_version": SCHEMA_VERSION + 1}))
PY
FLEET_HOME="$O12/home" fleet board --porcelain > "$OUT/O2-board.out" 2>&1
o2_rc=$?
o2_ver=0; grep -qE 'schema_version' "$OUT/O2-board.out" && o2_ver=1
o2_num=0; grep -qE "schema_version=[0-9]+|knows [0-9]+" "$OUT/O2-board.out" && o2_num=1
o2_no_tb=1; grep -qE '^Traceback' "$OUT/O2-board.out" && o2_no_tb=0
if [ "$o2_ver$o2_num$o2_no_tb" = "111" ] && [ "$o2_rc" -ge 1 ]; then
  it_pass O2 "fleet/it/O/out/O2-board.out" \
    "a record from a FUTURE schema is refused (exit $o2_rc) and the message names the version it carries and the one this build knows. There is deliberately no legacy tolerance, so refusing is right — and a refusal that does not say WHICH version leaves the reader unable to tell a corrupt file from a newer one"
else
  it_fail O2 "fleet/it/O/out/O2-board.out" \
    "mentions_schema=$o2_ver names_numbers=$o2_num no_traceback=$o2_no_tb exit=$o2_rc"
fi

# ==================================================================================================
# O3 — TWO INSTANTS SHARING A STABLE KEY ⇒ AmbiguousId, refused, and NEITHER is chosen. Resolving to
#      "whichever sorts first" is the failure: it is silent, and it is wrong half the time.
# ==================================================================================================
O3D="$OUT/o3"; mkdir -p "$O3D/home" "$O3D/instants"
(
  export FLEET_HOME="$O3D/home" FLEET_INSTANTS="$O3D/instants"
  A="$(fleet init --base 00000000 --name o3Twin --porcelain | awk -F'\t' '$1=="path"{print $2}')"
  # `resolve` only reaches its ambiguity branch when the RECORDED path is stale — if it still exists it is
  # returned immediately and there is nothing to be ambiguous about. So the scenario is the real one: a path
  # recorded at dispatch, the folder since renamed, and TWO candidates carrying the same stable key. The first
  # version of this case left the original in place and therefore measured nothing.
  cp -r "$A" "${A/-inflight-/-complete-}"
  cp -r "$A" "${A/-inflight-/-abort-}"
  rm -rf "$A"
  echo "twins:"; ls -d "$O3D/instants"/*o3twin*
  fleet lint --instant "$A" --porcelain
  echo "O3_EXIT=$?"
) > "$OUT/O3.out" 2>&1
o3_rc="$(awk -F'=' '/^O3_EXIT=/{print $2}' "$OUT/O3.out")"
o3_ambig=0; grep -qiE 'ambiguous|two instants|more than one' "$OUT/O3.out" && o3_ambig=1
o3_twins=$(grep -c 'o3twin' "$OUT/O3.out")
if [ "$o3_ambig" = 1 ] && [ "$o3_rc" != 0 ]; then
  it_pass O3 "fleet/it/O/out/O3.out" \
    "two instants sharing a stable key (same base-curr-optype-name, differing only in state) are REFUSED as ambiguous with exit $o3_rc rather than resolved to whichever sorts first. Silently picking one is wrong half the time and says nothing; `resolve` follows a state rename on purpose, so two candidates is the one case it must not guess at"
else
  it_fail O3 "fleet/it/O/out/O3.out" \
    "two candidates for one stable key did NOT produce an ambiguity refusal (exit=$o3_rc, ambiguous-wording=$o3_ambig, $o3_twins twin line(s)) — picking one silently is wrong half the time"
fi

# ==================================================================================================
# O4 — AN UNREADABLE RECORDS DIRECTORY ⇒ a clean error and NO PARTIAL WRITE. `SI-22` added the OSError
#      handler this exercises; before it, an errno escaped as a traceback.
#      Permissions are restored in a trap, because a 000 directory the runner leaves behind cannot be
#      cleaned by the next run either.
# ==================================================================================================
O4D="$OUT/o4"; mkdir -p "$O4D/home/records" "$O4D/instants"
o4_restore() { chmod 755 "$O4D/home/records" 2>/dev/null || true; }
trap 'o4_restore; it_cleanup_tmux; tmux -L "$IT_TMUX_SOCKET" kill-server 2>/dev/null' EXIT
# The instant is created BEFORE the chmod, because `init` writes to FLEET_INSTANTS and never touches
# records — aiming this case at `init` measured nothing (it exited 0, correctly). `resume` writes a RECORD,
# so it is the verb an unreadable records directory must refuse cleanly.
chmod 755 "$O4D/home/records"
O4I="$( export FLEET_HOME="$O4D/home" FLEET_INSTANTS="$O4D/instants"
        fleet init --base 00000000 --name o4probe --porcelain | awk -F'\t' '$1=="path"{print $2}' )"
before_manifest="$(it_manifest "$O4D/home" 2>/dev/null | sha256sum | cut -d" " -f1)"
chmod 000 "$O4D/home/records"
( export FLEET_HOME="$O4D/home" FLEET_INSTANTS="$O4D/instants"
  fleet resume --instant "$O4I" --porcelain; echo "O4_EXIT=$?" ) > "$OUT/O4.out" 2>&1
o4_restore
o4_rc="$(awk -F'=' '/^O4_EXIT=/{print $2}' "$OUT/O4.out")"
o4_no_tb=1; grep -qE '^Traceback' "$OUT/O4.out" && o4_no_tb=0
o4_errno=0; grep -qiE 'permission|denied|errno|EACCES' "$OUT/O4.out" && o4_errno=1
after_manifest="$(it_manifest "$O4D/home" 2>/dev/null | sha256sum | cut -d" " -f1)"
o4_no_partial=0; [ "$before_manifest" = "$after_manifest" ] && o4_no_partial=1
if [ "$o4_no_tb" = 1 ] && [ "$o4_errno" = 1 ] && [ "$o4_no_partial" = 1 ]; then
  it_pass O4 "fleet/it/O/out/O4.out" \
    "an unreadable records directory produced a CLEAN error naming the permission problem (exit $o4_rc), no traceback, and a byte-identical store — nothing half-written. The zero delta is the half that matters: an errno a human can read is good, and a store left in an intermediate state is what actually costs them the morning"
else
  it_fail O4 "fleet/it/O/out/O4.out" \
    "no_traceback=$o4_no_tb names_permission=$o4_errno store_unchanged=$o4_no_partial (exit $o4_rc)"
fi

# ==================================================================================================
# O5 — A GARBAGE lease.json ⇒ `reap` and `status` DEGRADE GRACEFULLY and SAY WHAT THEY COULD NOT READ.
#      Silently skipping an unreadable lease is the failure: the slot then belongs to nobody the tool can
#      name, which is how a lease leaks with a clean bill of health.
# ==================================================================================================
O5D="$OUT/o5"; mkdir -p "$O5D/home" "$O5D/slots/ws1"
( cd "$O5D/slots/ws1" && git init -q . && git -c user.email=it@fleet -c user.name=it commit -q --allow-empty -m base ) >/dev/null 2>&1
(
  export FLEET_HOME="$O5D/home" FLEET_INSTANTS="$O5D/instants"
  mkdir -p "$O5D/instants"
  fleet set-golden --path "$O5D/slots/ws1" >/dev/null
  fleet enroll --slot "$O5D/slots/ws1" >/dev/null
  mkdir -p "$O5D/home/pool/leases/ws1"
  printf 'this is not json at all\n' > "$O5D/home/pool/leases/ws1/lease.json"
  echo "O5_REAP_START"; fleet reap --all --porcelain; echo "O5_REAP_EXIT=$?"
  echo "O5_LEASES_START"; fleet leases --porcelain; echo "O5_LEASES_EXIT=$?"
) > "$OUT/O5.out" 2>&1
o5_reap_rc="$(awk -F'=' '/^O5_REAP_EXIT=/{print $2}' "$OUT/O5.out")"
o5_no_tb=1; grep -qE '^Traceback' "$OUT/O5.out" && o5_no_tb=0
o5_says=0; grep -qiE 'unreadable|could not|not json|malformed|cannot' "$OUT/O5.out" && o5_says=1
o5_names=0; grep -q 'ws1' "$OUT/O5.out" && o5_names=1
if [ "$o5_no_tb" = 1 ] && [ "$o5_says" = 1 ] && [ "$o5_names" = 1 ]; then
  it_pass O5 "fleet/it/O/out/O5.out" \
    "a lease whose lease.json is not JSON did not crash reap or leases (no traceback, reap exit $o5_reap_rc) and BOTH said what they could not read, naming the slot 'ws1'. Skipping it silently is the real failure: the slot then belongs to nobody the tool can name, which is a leaked lease with a clean bill of health"
else
  it_fail O5 "fleet/it/O/out/O5.out" \
    "no_traceback=$o5_no_tb says_what_it_could_not_read=$o5_says names_slot=$o5_names (reap exit $o5_reap_rc)"
fi

# ==================================================================================================
# O6 — A SLOT PATH THAT IS A FILE ⇒ REFUSED AT ENROL. Enrolment is the door; a non-directory admitted
#      here becomes a lease claim that fails much later, somewhere with less context.
# ==================================================================================================
O6D="$OUT/o6"; mkdir -p "$O6D/home" "$O6D/instants"
printf 'I am a file, not a workspace\n' > "$O6D/not-a-dir"
( export FLEET_HOME="$O6D/home" FLEET_INSTANTS="$O6D/instants"
  fleet enroll --slot "$O6D/not-a-dir"; echo "O6_EXIT=$?" ) > "$OUT/O6.out" 2>&1
o6_rc="$(awk -F'=' '/^O6_EXIT=/{print $2}' "$OUT/O6.out")"
o6_no_tb=1; grep -qE '^Traceback' "$OUT/O6.out" && o6_no_tb=0
o6_enrolled=1; [ -d "$O6D/home/pool/enrolled" ] && [ -n "$(ls -A "$O6D/home/pool/enrolled" 2>/dev/null)" ] || o6_enrolled=0
if [ "$o6_rc" = 2 ] && [ "$o6_no_tb" = 1 ] && [ "$o6_enrolled" = 0 ]; then
  it_pass O6 "fleet/it/O/out/O6.out" \
    "a slot path that is a FILE is refused at enrol with exit 2 and nothing entered the pool. Enrolment is the door: a non-directory admitted here would surface later as a lease claim failing somewhere with far less context about why"
else
  it_fail O6 "fleet/it/O/out/O6.out" \
    "exit=$o6_rc (want 2) no_traceback=$o6_no_tb pool_still_empty=$([ "$o6_enrolled" = 0 ] && echo yes || echo NO)"
fi

# ==================================================================================================
# O8 — A 10 MB REGISTER ⇒ harvest COMPLETES and REPORTS ITS POPULATION. The population line is the
#      point: a tick that silently truncated a huge register would read exactly like a tick over a small
#      one, and "how many did you examine" is the only question that distinguishes them.
# ==================================================================================================
O8D="$OUT/o8"; mkdir -p "$O8D/home" "$O8D/instants/00000000-07300900-inflight-append-o8big"
BIG="$O8D/instants/00000000-07300900-inflight-append-o8big/ISSUES.md"
{ echo "# ISSUES"; i=0; while [ "$i" -lt 40000 ]; do
    printf '## OB-%s Some finding with enough prose to be realistic, repeated to reach ten megabytes.\n' "$i"
    i=$((i+1)); done; } > "$BIG"
BIG_MB=$(( $(wc -c < "$BIG") / 1048576 ))
o8_start=$(date +%s)
( export FLEET_HOME="$O8D/home" FLEET_INSTANTS="$O8D/instants"
  python3 - <<'PY'
import os, pathlib
from fleet.harvest import Harvest
home = pathlib.Path(os.environ["FLEET_HOME"])
inst = next(pathlib.Path(os.environ["FLEET_INSTANTS"]).glob("*o8big*"))
h = Harvest(home)
src = h.register(str(inst), str(inst / "ISSUES.md"))
print("primed count:", h.prime(src))
PY
  echo "O8_PRIME_EXIT=$?"
  timeout 300 fleet harvest --porcelain; echo "O8_EXIT=$?" ) > "$OUT/O8.out" 2>&1
o8_secs=$(( $(date +%s) - o8_start ))
o8_rc="$(awk -F'=' '/^O8_EXIT=/{print $2}' "$OUT/O8.out")"
o8_pop=0; grep -qP '^population\t' "$OUT/O8.out" && o8_pop=1
o8_count=0; grep -qE 'examined [0-9]+' "$OUT/O8.out" && o8_count=1
o8_no_timeout=1; [ "$o8_rc" = 124 ] && o8_no_timeout=0
if [ "$o8_pop" = 1 ] && [ "$o8_count" = 1 ] && [ "$o8_no_timeout" = 1 ]; then
  it_pass O8 "fleet/it/O/out/O8.out" \
    "harvest completed over a ${BIG_MB}MB register in ${o8_secs}s (exit $o8_rc, not a timeout) and REPORTED ITS POPULATION with a count of what it examined. The count is the assertion: a tick that silently truncated a huge register would look identical to a tick over a small one, and 'how many did you examine' is the only question that tells them apart"
else
  it_fail O8 "fleet/it/O/out/O8.out" \
    "population_row=$o8_pop names_count=$o8_count completed=$o8_no_timeout (${BIG_MB}MB, ${o8_secs}s, exit $o8_rc)"
fi

it_assert_isolation O-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict" >&2; exit 3; }
sed -i "s|$INSTANT/||g" "$RESULTS"
echo "§O (targeted: O7 O9) done: IT_FAILED=$IT_FAILED"
#: `II-11`. Was `exit "$IT_FAILED"` — a COUNT. `exit` truncates modulo 256, so a section with
#: exactly 256 failures reported SUCCESS, and one with 300 reported 44, a number meaning nothing
#: to any reader. An exit status is a one-byte verdict, not a tally: the count is already printed
#: on the line above and is in the register, which is where a consumer should read it anyway.
if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
exit 1
