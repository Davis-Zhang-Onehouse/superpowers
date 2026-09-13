#!/usr/bin/env bash
#
# `scripts/release-preflight.sh`, asserted against a scratch release area -- never the real one, and
# never a real tmux socket other than a throwaway one this test owns.
#
# The property worth testing is the one the header of the script under test exists to prevent: a wrong or
# missing socket must be a REFUSAL (exit 2), not a quiet, confident report -- because on screen the two
# look identical, and that is exactly what cost a release-day box its "this is quiet" read. Everything
# else here is advisory (exit 0), including the orphan reaper's findings, and the reaper itself must
# refuse anything whose name is not an exact match rather than guess.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SCRIPT="$REPO/scripts/release-preflight.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fails=0
note() { printf '  %s\n' "$*"; }
check() { # check <label> <expected> <actual>
  if [ "$2" = "$3" ]; then note "ok   $1"; else
    note "FAIL $1"; note "       wanted: [$2]"; note "       got:    [$3]"; fails=1
  fi
}

# --- the one hard refusal: FLEET_TMUX_SOCKET literally 'fleet' -----------------------------------------
out="$(FLEET_TMUX_SOCKET=fleet bash "$SCRIPT" 2>&1)"; rc=$?
check "socket=fleet exits 2" "2" "$rc"
printf '%s' "$out" | grep -q "DERIVED" \
  || { note "FAIL the refusal does not name the derivation (fleet-env.sh)"; fails=1; }

# --- the one hard refusal: FLEET_TMUX_SOCKET unset ------------------------------------------------------
out="$(env -u FLEET_TMUX_SOCKET bash "$SCRIPT" 2>&1)"; rc=$?
check "socket unset exits 2" "2" "$rc"

# --- everything past this point uses a derived-looking socket and a scratch release area --------------
SOCKET="rp-test-$$"
RELEASES="$TMP/releases"
mkdir -p "$RELEASES"
export FLEET_TMUX_SOCKET="$SOCKET"
export FLEET_RELEASES="$RELEASES"
export FLEET_BIN="/nonexistent/fleet" # check 3 (slots) must degrade quietly without a real fleet binary

# --- an orphan whose pid is not running --------------------------------------------------------------
# A pid this large is very unlikely to exist; if it somehow does, kill -0 would still need the cmdline to
# say `release-verify`, which a pid picked out of thin air will not.
DEAD_PID=999999
ORPHAN_DIR="$RELEASES/.fleet-v0.0.1.$DEAD_PID.1.abc.tmp"
mkdir -p "$ORPHAN_DIR"

out="$(bash "$SCRIPT" 2>&1)"; rc=$?
check "a normal run exits 0 even with warnings present" "0" "$rc"
printf '%s' "$out" | grep -q "ORPHAN $ORPHAN_DIR" \
  || { note "FAIL a dead-pid tmp dir was not reported ORPHAN"; note "$out"; fails=1; }

# --- reap removes exactly that one -----------------------------------------------------------------
bash "$SCRIPT" --reap >/dev/null 2>&1
if [ -d "$ORPHAN_DIR" ]; then note "FAIL --reap did not remove the dead-pid orphan"; fails=1
else note "ok   --reap removed the dead-pid orphan"; fi

# --- BOTH halves of the liveness test: a running pid whose cmdline is NOT release-verify is still an
# orphan. This is the assertion that would fail if the reaper were simplified to `kill -0` alone -- the
# exact simplification the header comment warns would reap a live run mid-suite on a reused pid.
SELF_PID=$$
NOTVERIFY_DIR="$RELEASES/.fleet-v0.0.2.$SELF_PID.2.def.tmp"
mkdir -p "$NOTVERIFY_DIR"
out="$(bash "$SCRIPT" 2>&1)"
printf '%s' "$out" | grep -q "ORPHAN $NOTVERIFY_DIR" \
  || { note "FAIL a live pid whose cmdline is not release-verify was not reported ORPHAN"; note "$out"; fails=1; }
printf '%s' "$out" | grep -q "LIVE: $NOTVERIFY_DIR" \
  && { note "FAIL a non-release-verify pid was reported LIVE -- both halves of the test did not run"; fails=1; }

bash "$SCRIPT" --reap >/dev/null 2>&1
if [ -d "$NOTVERIFY_DIR" ]; then note "FAIL --reap did not remove the live-pid-wrong-cmdline orphan"; fails=1
else note "ok   --reap removed the orphan whose pid is alive but is not release-verify"; fi

# --- a name that does not match the full pattern is refused, not guessed at ---------------------------
BADNAME_DIR="$RELEASES/.fleet-v0.0.1.tmp"
mkdir -p "$BADNAME_DIR"
out="$(bash "$SCRIPT" 2>&1)"
printf '%s' "$out" | grep -q "does not match the orphan name pattern" \
  || { note "FAIL a badly-named tmp dir was silently ignored instead of being called out"; fails=1; }
bash "$SCRIPT" --reap >/dev/null 2>&1
if [ -d "$BADNAME_DIR" ]; then note "ok   --reap left the non-matching name alone"
else note "FAIL --reap deleted a directory that did not match the exact orphan pattern"; fails=1; fi
rm -rf "$BADNAME_DIR"

if [ "$fails" = 0 ]; then
  echo "PASS: release-preflight refuses (exit 2) only when FLEET_TMUX_SOCKET is unset or literally" \
       "'fleet' -- the environment fleet-env.sh guarantees can never be a real fleet socket -- reports" \
       "everything else as advisory WARN lines with exit 0, classifies a tmp worktree ORPHAN unless BOTH" \
       "its pid is alive AND that pid's cmdline says release-verify, and --reap deletes only directories" \
       "matching the exact orphan name pattern, leaving anything else alone"
  exit 0
fi
echo FAIL
exit 1
