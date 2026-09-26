#!/usr/bin/env bash
# `cleanup_TS` (fleet/it/run-TS.sh): §TS's teardown must leave no `fleet-it-ts.*` scratch root behind.
#
# RV-41. `kill-server` returns once tmux has sent SIGHUP, and the dying claude still flushes its transcript and
# config into the scratch CLAUDE_CONFIG_DIR ($TS_ROOT/.claude) after that. An `rm -rf` straight after the kill
# races it, and the late write re-creates the root. The teardown must wait (bounded) until no process holds the
# root, remove it, and report a residue it could not remove.
#
# Spends no claude and starts no tmux: `cleanup_TS` is extracted from run-TS.sh and run with its fleet and tmux
# calls stubbed. The stubbed `kill-server` SIGTERMs a fake claude that, like the real one, writes into
# $TS_ROOT/.claude a moment AFTER it was told to die.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
TMP="$(mktemp -d)"; TMP="$(cd "$TMP" && pwd -P)"
PIDS=()
trap 'for p in "${PIDS[@]}"; do kill -KILL "$p" 2>/dev/null; done; rm -rf "$TMP"' EXIT

fails=0
note() { printf '  %s\n' "$*"; }
check() { if [ "$2" = "$3" ]; then note "ok   $1"; else note "FAIL $1 — wanted [$2] got [$3]"; fails=1; fi; }

TS="$REPO/fleet/it/run-TS.sh"
FN="$(awk '/^(cleanup_TS|ts_root_holders|ts_release_root)\(\) *\{/,/^}/' "$TS")"
case "$FN" in *'cleanup_TS()'*) ;; *) echo "FAIL: cleanup_TS not found in fleet/it/run-TS.sh"; exit 1 ;; esac

# fake_claude <root> <cwd> <late> [env...]: dies <late> seconds after SIGTERM, writing into <root>/.claude first
# ("never" ignores SIGTERM). Prints its pid.
fake_claude() {
  local root="$1" cwd="$2" late="$3"; shift 3
  local on_term="sleep $late; mkdir -p '$root/.claude' && echo flushed > '$root/.claude/late-flush'; exit 0"
  [ "$late" = never ] && on_term=":"
  ( cd "$cwd" && exec env "$@" bash -c "trap \"$on_term\" TERM; while :; do sleep 0.1; done" ) >/dev/null 2>&1 &
  echo $!
}

# teardown <root> <fake pid> [TS_RELEASE_WAIT] -> runs cleanup_TS with stubs; prints the IT rows it wrote
#: The root is handed over in the script text, not the environment: run-TS.sh does not export TS_ROOT, and a
#: shell whose environment names the root is itself one of its holders.
teardown() {
  FN="$FN" FAKE="$2" OUT="$TMP/out" TS_RELEASE_WAIT="${3:-10}" bash -c "TS_ROOT='$1'; TS_PARENT='$TMP'"'
    TODOS=()
    fleet() { :; }; it_cleanup_tmux() { :; }
    it_tmux() { [ "$1" = kill-server ] && kill -TERM "$FAKE"; return 0; }
    it_pass() { echo "PASS $1 $3"; }; it_fail() { echo "FAIL $1 $3"; }
    eval "$FN"; cleanup_TS'
}
mkdir -p "$TMP/out"

# --- 1. the dying claude sits in a slot under the root and flushes 1s after the kill ---------------------------
R1="$TMP/fleet-it-ts.one"; mkdir -p "$R1/untrusted-slot" "$R1/.claude"
p1="$(fake_claude "$R1" "$R1/untrusted-slot" 1 CLAUDE_CONFIG_DIR="$R1/.claude")"; PIDS+=("$p1")
sleep 0.3
rows1="$(teardown "$R1" "$p1")"
while kill -0 "$p1" 2>/dev/null; do sleep 0.1; done; sleep 0.3
check "a claude that flushes after the kill: no scratch root is left" no "$([ -e "$R1" ] && echo yes || echo no)"
case "$rows1" in *"FAIL TS3"*) note "FAIL a clean teardown reported residue: [$rows1]"; fails=1 ;; *) note "ok   no residue reported" ;; esac

# --- 2. a holder known only by its environment (CLAUDE_CONFIG_DIR), with its cwd elsewhere ---------------------
R2="$TMP/fleet-it-ts.two"; mkdir -p "$R2/.claude"
p2="$(fake_claude "$R2" "$TMP" 1 CLAUDE_CONFIG_DIR="$R2/.claude")"; PIDS+=("$p2")
sleep 0.3
teardown "$R2" "$p2" >/dev/null
while kill -0 "$p2" 2>/dev/null; do sleep 0.1; done; sleep 0.3
check "a holder by CLAUDE_CONFIG_DIR only: no scratch root is left" no "$([ -e "$R2" ] && echo yes || echo no)"

# --- 3. a holder that never exits: bounded, and the residue is REPORTED, naming the pid ---------------------------
R3="$TMP/fleet-it-ts.three"; mkdir -p "$R3/untrusted-slot"
p3="$(fake_claude "$R3" "$R3/untrusted-slot" never)"; PIDS+=("$p3")
sleep 0.3
t0=$(date +%s); rows3="$(teardown "$R3" "$p3" 2)"; t1=$(date +%s)
check "a holder that never exits: the wait is bounded" yes "$([ $((t1 - t0)) -le 6 ] && echo yes || echo no)"
case "$rows3" in *"FAIL TS3"*"$p3"*) note "ok   the residue is reported as FAIL TS3 naming pid $p3" ;;
                 *) note "FAIL no FAIL TS3 naming pid $p3: [$rows3]"; fails=1 ;; esac
kill -KILL "$p3" 2>/dev/null

if [ "$fails" = 0 ]; then echo "run-ts-teardown: all ok"; else echo "run-ts-teardown: FAILED"; fi
exit "$fails"
