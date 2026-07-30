#!/usr/bin/env bash
# §O — Failure injection, TARGETED: O7 and O9 only.
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
# Run: bash evidence/04-integration/run-O.sh
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
    it_fail O7 "evidence/04-integration/O/out/O7-lint.err" \
      "lint DID NOT TERMINATE within 30s on an instant containing a symlink loop — it was killed by timeout. A hang is the worst of the failure modes here because it is indistinguishable from slow work"
  elif [ "$o7_said_something" = 1 ]; then
    it_pass O7 "evidence/04-integration/O/out/O7-lint.tsv" \
      "lint TERMINATED (exit $o7_rc, not 124) on an instant containing two shapes of symlink loop — a self-referential 'loop -> .' and a mutual 'a/b/up -> ../..' — and reported $o7_rows row(s) plus $(wc -c < "$OUT/O7-lint.err") bytes on stderr rather than dying silently. Bounded by \`timeout 30\` deliberately: a hang is the failure being tested for, so an unbounded version of this case would hang the suite instead of failing it"
  else
    it_fail O7 "evidence/04-integration/O/out/O7-lint.tsv" \
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
  it_fail O9a "evidence/04-integration/O/out/O9-before-state.txt" \
    "the driver was never killed, so this measures nothing"
elif [ "$a_state" = absent ] && [ "$a_readable" = True ]; then
  it_pass O9a "evidence/04-integration/O/out/O9-before-state.txt" \
    "SIGKILL immediately before the atomic replace left NO record at all (not a truncated one) and the store still reads cleanly — so a crash mid-write costs the write and never the register. The temp file that was already on disk is not mistaken for a record, which matters more than the lost write: a store that becomes permanently unreadable after one crash is the worse outcome"
else
  it_fail O9a "evidence/04-integration/O/out/O9-before-state.txt" \
    "record_state=$a_state (want absent), store_readable=$a_readable (want True)"
fi

# ---- O9b: killed AFTER the replace ---------------------------------------------------------------
o9_check after
b_state="$(awk -F': ' '/^record_state:/{print $2}' "$OUT/O9-after-state.txt")"
b_readable="$(awk '/^store_readable:/{print $2}' "$OUT/O9-after-state.txt")"
b_rc="$(awk -F': ' '/^driver_rc:/{print $2}' "$OUT/O9-after-state.txt")"
if [ "$b_rc" = 99 ]; then
  it_fail O9b "evidence/04-integration/O/out/O9-after-state.txt" \
    "the driver was never killed, so this measures nothing"
elif [ "$b_state" = complete ] && [ "$b_readable" = True ]; then
  it_pass O9b "evidence/04-integration/O/out/O9-after-state.txt" \
    "SIGKILL immediately AFTER the atomic replace left a COMPLETE, parseable record. This is the half that makes O9a non-vacuous: without it, a store that simply never wrote anything would satisfy 'the record is absent' perfectly. Together the two say the window around the replace has exactly two states and no third"
else
  it_fail O9b "evidence/04-integration/O/out/O9-after-state.txt" \
    "record_state=$b_state (want complete), store_readable=$b_readable (want True)"
fi

# The section-level claim, stated once both halves are in.
if grep -qP '^O9a\tPASS\t' "$RESULTS" && grep -qP '^O9b\tPASS\t' "$RESULTS"; then
  it_pass O9 "evidence/04-integration/O/out/O9-before-state.txt" \
    "the tmp-then-replace guarantee holds across a REAL SIGKILL, in both directions (O9a absent, O9b complete) — never a truncated record. Every register in the package (records, leases, roadmaps, proposals, declarations) writes through this one function, so this is the case the whole store layer rests on and it had been argued from construction rather than crashed"
else
  it_fail O9 "evidence/04-integration/O/out/O9-before-state.txt" \
    "one or both halves failed; see O9a/O9b"
fi

it_assert_isolation O-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict" >&2; exit 3; }
sed -i "s|$INSTANT/||g" "$RESULTS"
echo "§O (targeted: O7 O9) done: IT_FAILED=$IT_FAILED"
exit "$IT_FAILED"
