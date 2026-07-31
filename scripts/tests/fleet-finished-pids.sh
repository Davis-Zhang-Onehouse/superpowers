#!/usr/bin/env bash
# `scripts/fleet-finished-pids.sh`, asserted in BOTH directions against a real store, a real tmux server and
# real live processes.
#
# Why this exists: the switch that made this script the watchdog's default was made on a differential check in
# which BOTH the old tool and the new one printed nothing. Two tools agreeing on the empty case is not
# agreement — the whole risk lives in the non-empty cases, and the catastrophic one (printing a pid that must
# NOT be excluded) cannot be observed at all from an empty store.
#
# The failure this guards against is silent by construction. The watchdog only ever receives a list of pids;
# a pid excluded in error is indistinguishable from a pid correctly excluded, and the symptom is not an error
# but the ABSENCE of an auto-resume, weeks later, in a session nobody is watching.
#
# `claude` here is a copy of `/bin/sleep` under that name, because the CLI builds its probes with
# `default_probes()` and `pgrep -x claude` is therefore not overridable from outside. No real claude is spent,
# and every session lives on a private tmux socket whose name cannot collide with a `dt-` dispatch session.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SHIM="$REPO/scripts/fleet-finished-pids.sh"
FLEET="$REPO/bin/fleet"

SOCKET="ffp-$$"
TMP="$(mktemp -d)"
cleanup() {
  tmux -L "$SOCKET" kill-server 2>/dev/null || true
  [ -n "${FAKE_PIDS:-}" ] && kill $FAKE_PIDS 2>/dev/null
  rm -rf "$TMP"
}
trap cleanup EXIT

export FLEET_HOME="$TMP/home" FLEET_INSTANTS="$TMP/instants" FLEET_TMUX_SOCKET="$SOCKET"
mkdir -p "$FLEET_HOME" "$FLEET_INSTANTS" "$TMP/bin" "$TMP/slots/a" "$TMP/slots/b" "$TMP/slots/c"

fails=0
note() { printf '  %s\n' "$*"; }
check() {                     # check <label> <expected> <actual>
  local label="$1" want="$2" got="$3"
  if [ "$want" = "$got" ]; then note "ok   $label"; else
    note "FAIL $label"; note "       wanted: [$want]"; note "       got:    [$got]"; fails=1
  fi
}

# --- case D first: an EMPTY store must print nothing and exit 0 -------------------------------------
# This is the degrade-safe direction. If it ever prints anything, every box with no fleet records loses
# auto-resume entirely, which is the single worst outcome available to this script.
out="$(bash "$SHIM" --finished-pids 2>/dev/null)"; rc=$?
check "empty-store prints nothing" "" "$out"
check "empty-store exits 0" "0" "$rc"

# --- build a real fleet: two instants, one finished and one still working ---------------------------
cp /bin/sleep "$TMP/bin/claude"

start_fake() {                # start_fake <session> <cwd> -> echoes the claude pid
  local name="$1" cwd="$2"
  tmux -L "$SOCKET" new-session -d -s "$name" -c "$cwd" "$TMP/bin/claude 3000" 2>/dev/null || return 1
  local tries=0 pid=""
  while [ "$tries" -lt 40 ]; do
    pid="$(pgrep -x claude 2>/dev/null | while read -r p; do
             [ "$(readlink -f "/proc/$p/cwd" 2>/dev/null)" = "$(readlink -f "$cwd")" ] && echo "$p"
           done | head -1)"
    [ -n "$pid" ] && { echo "$pid"; return 0; }
    tries=$((tries + 1)); sleep 0.1
  done
  return 1
}

# Instants are created by `fleet init`, not by mkdir. An instant name is `base-curr-state-optype-name` and
# `InstantName.parse` is the only thing that reads it: a hand-made folder that is one field short parses as
# nothing, `_folder_state` returns None, and the subject silently comes back RUNNING — a fixture that would
# have made the positive assertion below unreachable while looking like a product bug.
DONE_INSTANT="$("$FLEET" init --base 00000000 --name ffpFinished --porcelain | awk -F'\t' '$1=="path"{print $2}')"
WORK_INSTANT="$("$FLEET" init --base 00000000 --name ffpWorking  --porcelain | awk -F'\t' '$1=="path"{print $2}')"
if [ ! -d "$DONE_INSTANT" ] || [ ! -d "$WORK_INSTANT" ]; then
  echo "could not create the instants; nothing below would be a verdict"; echo FAIL; exit 1
fi
# The rename IS the completion signal, and it outranks the recorded path — so the finished worker is made
# finished the same way a real one does it, by renaming its own folder.
DONE_INSTANT_COMPLETE="${DONE_INSTANT/-inflight-/-complete-}"
mv "$DONE_INSTANT" "$DONE_INSTANT_COMPLETE"
DONE_INSTANT="$DONE_INSTANT_COMPLETE"

PID_DONE="$(start_fake ffp-finished "$TMP/slots/a")" || { echo "could not start the finished fake"; echo FAIL; exit 1; }
PID_WORK="$(start_fake ffp-working  "$TMP/slots/b")" || { echo "could not start the working fake"; echo FAIL; exit 1; }
PID_ORPH="$(start_fake ffp-orphan   "$TMP/slots/c")" || { echo "could not start the orphan fake"; echo FAIL; exit 1; }
FAKE_PIDS="$PID_DONE $PID_WORK $PID_ORPH"

# Records are written through the store's own public API — the same one `reconcile` reads — so this test
# cannot pass against a record shape the product would reject.
PYTHONPATH="$REPO/fleet/src" python3 - "$DONE_INSTANT" "$WORK_INSTANT" <<'PY' || { echo "could not write records"; echo FAIL; exit 1; }
import os, sys
from pathlib import Path
from fleet.store import Record, Store

done_instant, work_instant = (Path(p).name for p in sys.argv[1:3])
store = Store(Path(os.environ["FLEET_HOME"]))
for todo, instant, tmux_name in (("ffpDone", done_instant, "ffp-finished"),
                                 ("ffpWork", work_instant, "ffp-working")):
    store.write(Record(
        todo_id=todo, child_instant=instant, base_instant="00000000",
        slot=str(Path(os.environ["FLEET_HOME"]).parent / "slots" / ("a" if todo == "ffpDone" else "b")),
        tmux=tmux_name, profile="worker", golden="", lineage_base="",
        title="a test subject", dispatched_at="2026-07-31T00:00:00Z"))
print("records written", file=sys.stderr)
PY

# Sanity: the join must actually SEE what we built, or every assertion below is vacuous.
recon="$("$FLEET" reconcile --porcelain 2>/dev/null)"
if ! printf '%s' "$recon" | grep -q 'ffpDone'; then
  note "the join does not see ffpDone at all, so nothing below would be a verdict:"
  printf '%s\n' "$recon" | sed 's/^/       /' | head -8
  echo FAIL; exit 1
fi
printf '%s' "$recon" | grep -q 'state COMPLETE' || {
  note "ffpDone is not COMPLETE; the fixture is wrong, not the shim:"
  printf '%s\n' "$recon" | sed 's/^/       /' | head -8
  echo FAIL; exit 1
}

# --- the three real cases --------------------------------------------------------------------------
out="$(bash "$SHIM" --finished-pids 2>/dev/null)"

# POSITIVE: the finished worker's pid IS printed. Without this the switch is unverified in the only
# direction that does any work.
check "a finished worker's pid is printed" "$PID_DONE" "$(printf '%s\n' "$out" | grep -x "$PID_DONE")"

# NEGATIVE: a worker still working must NOT be excluded — excluding it kills auto-resume for live work.
check "a WORKING worker is not printed" "" "$(printf '%s\n' "$out" | grep -x "$PID_WORK")"

# NEGATIVE, and the catastrophic one: a live session with NO dispatch record is `unknown-session`, which
# `reconcile` reports as `unarmed`. Mapping `unarmed -> exclude` would print this pid and switch auto-resume
# off for every unmanaged session on the box — the exact inversion the shim's header warns about.
check "an UNMANAGED session is not printed" "" "$(printf '%s\n' "$out" | grep -x "$PID_ORPH")"

# And the whole output is exactly one pid, so nothing extra rode along.
check "exactly one pid in total" "1" "$(printf '%s\n' "$out" | grep -c '^[0-9][0-9]*$')"

# --- the contract's edges --------------------------------------------------------------------------
bash "$SHIM" >/dev/null 2>&1; check "no argument exits 2" "2" "$?"
bash "$SHIM" --nonsense >/dev/null 2>&1; check "an unknown argument exits 2" "2" "$?"
FLEET_BIN=/nonexistent/fleet bash "$SHIM" --finished-pids >"$TMP/nofleet.out" 2>/dev/null
check "no fleet binary exits 0" "0" "$?"
check "no fleet binary prints nothing" "" "$(cat "$TMP/nofleet.out")"

if [ "$fails" = 0 ]; then
  echo "PASS: against a real store, a real tmux server and three live processes, the shim prints exactly the finished worker's pid — not the worker still working, and not the unmanaged session whose exclusion would switch auto-resume off for the whole box — and it degrades to printing nothing when the store is empty or fleet is absent"
  exit 0
fi
echo FAIL
exit 1
