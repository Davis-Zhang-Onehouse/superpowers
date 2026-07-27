#!/usr/bin/env bash
# Hermetic self-tests for dispatch-health.sh / dispatch-send.sh / dispatch-launch.sh.
# Uses a stub tmux (no real sessions) + an isolated BOARD_DIR. Prints PASS/FAIL.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$here/.."
fail=0
ok(){ echo "  ok   - $1"; }
bad(){ echo "  FAIL - $1"; fail=1; }
chk(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (expected rc=$2, got rc=$3)"; fi; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export BOARD_DIR="$tmp/board"; mkdir -p "$BOARD_DIR/records"
mkdir -p "$tmp/bin" "$tmp/ws" "$tmp/child"

# ---- stub tmux -------------------------------------------------------------
cat > "$tmp/bin/tmux" <<'STUB'
#!/usr/bin/env bash
log="${STUB_LOG:-/dev/null}"; echo "tmux $*" >> "$log"
case "$1" in
  has-session) [ "${STUB_ALIVE:-1}" = "1" ] && exit 0 || exit 1 ;;
  capture-pane) cat "${STUB_PANE:-/dev/null}"; exit 0 ;;
  send-keys)
     if [ "${STUB_ECHO:-1}" = "1" ]; then
       for a in "$@"; do :; done
       echo "${*:3}" >> "${STUB_PANE:-/dev/null}"
     fi; exit 0 ;;
  new-session) echo "created" >> "$log"; exit 0 ;;
  *) exit 0 ;;
esac
STUB
chmod +x "$tmp/bin/tmux"
export TMUX_BIN="$tmp/bin/tmux"
export STUB_LOG="$tmp/tmux.log"
export STUB_PANE="$tmp/pane.txt"; : > "$STUB_PANE"

rec(){ # rec <id> <child> [tmux]
  cat > "$BOARD_DIR/records/$1.json" <<EOF
{ "todo_id": "$1", "title": "T $1", "child_instant": "$2", "ws": "$tmp/ws",
  "slot": "ws9", "tmux": "${3:-dt-$1}", "base_instant": "$tmp/base",
  "seed_file": "$tmp/seed.txt", "dispatched_at": "2026-01-01T00:00:00Z" }
EOF
}
mkdir -p "$tmp/child/07180102-07190000-inflight-append-alpha"
mkdir -p "$tmp/child/07180102-07190001-complete-append-beta"
rec alpha "$tmp/child/07180102-07190000-inflight-append-alpha"
echo "do the work" > "$tmp/seed.txt"

echo "== dispatch-health =="
printf 'working on the thing\n' > "$STUB_PANE"
STUB_ALIVE=1 bash "$S/dispatch-health.sh" >/dev/null 2>&1; chk "healthy fleet exits 0" 0 $?
out=$(STUB_ALIVE=1 bash "$S/dispatch-health.sh" 2>&1); echo "$out" | grep -q "alpha" && ok "lists the worker" || bad "worker not listed"

STUB_ALIVE=0 bash "$S/dispatch-health.sh" >/dev/null 2>&1; chk "dead session needs attention (rc=1)" 1 $?
out=$(STUB_ALIVE=0 bash "$S/dispatch-health.sh" 2>&1); echo "$out" | grep -qi "dead" && ok "reports DEAD" || bad "did not report DEAD"

# alive-but-blocked: a permission modal in the pane
printf 'Do you want to proceed?\n 1. Yes\n 2. Yes, and do not ask again\n 3. No\n' > "$STUB_PANE"
STUB_ALIVE=1 bash "$S/dispatch-health.sh" >/dev/null 2>&1; chk "blocked worker needs attention (rc=1)" 1 $?
out=$(STUB_ALIVE=1 bash "$S/dispatch-health.sh" 2>&1); echo "$out" | grep -qi "blocked" && ok "reports BLOCKED" || bad "did not report BLOCKED"

# complete-but-unharvested is surfaced by health too
rec beta "$tmp/child/07180102-07190001-complete-append-beta"
printf 'idle\n' > "$STUB_PANE"
out=$(STUB_ALIVE=1 bash "$S/dispatch-health.sh" 2>&1)
echo "$out" | grep -qi "unharvested\|complete" && ok "surfaces complete-but-unharvested" || bad "missed unharvested worker"
rm -f "$BOARD_DIR/records/beta.json"

# the record stores the child path as of DISPATCH time; the worker renames the folder when it
# completes, so completion must be detected from the CURRENT folder, not the recorded name.
mv "$tmp/child/07180102-07190000-inflight-append-alpha" "$tmp/child/07180102-07190000-complete-append-alpha"
out=$(STUB_ALIVE=1 bash "$S/dispatch-health.sh" 2>&1)
echo "$out" | grep -qi "COMPLETE" && ok "detects completion after the folder was renamed" \
  || bad "stale recorded path hid a completed worker"
mv "$tmp/child/07180102-07190000-complete-append-alpha" "$tmp/child/07180102-07190000-inflight-append-alpha"

# json mode is machine-readable
out=$(STUB_ALIVE=1 bash "$S/dispatch-health.sh" --json 2>/dev/null)
echo "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert isinstance(d,(list,dict))' 2>/dev/null \
  && ok "--json parses" || bad "--json did not parse"

echo "== dispatch-send =="
: > "$STUB_LOG"; printf 'ready\n' > "$STUB_PANE"
STUB_ALIVE=1 STUB_ECHO=1 bash "$S/dispatch-send.sh" alpha "hello worker" >/dev/null 2>&1
chk "verified send succeeds" 0 $?
grep -q "send-keys" "$STUB_LOG" && ok "actually called send-keys" || bad "never called send-keys"

# undelivered: pane never changes -> must fail loudly, not silently succeed
: > "$STUB_LOG"; printf 'ready\n' > "$STUB_PANE"
STUB_ALIVE=1 STUB_ECHO=0 bash "$S/dispatch-send.sh" alpha "hello worker" >/dev/null 2>&1
chk "unverified delivery fails (rc=1)" 1 $?
n=$(grep -c "send-keys" "$STUB_LOG"); [ "$n" -ge 2 ] && ok "retried before failing ($n sends)" || bad "did not retry (n=$n)"

STUB_ALIVE=0 bash "$S/dispatch-send.sh" alpha "x" >/dev/null 2>&1; chk "send to dead session fails" 1 $?
bash "$S/dispatch-send.sh" nosuch "x" >/dev/null 2>&1; chk "unknown id fails (rc=2)" 2 $?

echo "== dispatch-launch =="
: > "$STUB_LOG"; printf 'ready\n' > "$STUB_PANE"
STUB_ALIVE=0 STUB_ECHO=1 bash "$S/dispatch-launch.sh" alpha >/dev/null 2>&1
chk "launches a not-yet-running worker" 0 $?
grep -q "new-session" "$STUB_LOG" && ok "created the session" || bad "did not create session"
grep -q "remote-control" "$STUB_LOG" && ok "sent the claude invocation" || bad "did not send claude invocation"

# refuses to double-launch a live session
: > "$STUB_LOG"
STUB_ALIVE=1 bash "$S/dispatch-launch.sh" alpha >/dev/null 2>&1; chk "refuses to relaunch a live session" 1 $?

# seed with shell metacharacters must survive (the OI-12 class of bug)
printf 'run a | b ; c && d > e\n' > "$tmp/seed.txt"
: > "$STUB_LOG"; printf 'ready\n' > "$STUB_PANE"
STUB_ALIVE=0 STUB_ECHO=1 bash "$S/dispatch-launch.sh" alpha >/dev/null 2>&1
chk "metacharacter seed launches cleanly" 0 $?
# %q escapes rather than quotes, so compare with the escapes removed: the seed must survive
# intact as ONE argument (escaped), never split on the metacharacters.
tr -d '\\' < "$STUB_LOG" | grep -Fq 'run a | b ; c && d > e' \
  && ok "seed survives intact as one escaped argument" || bad "seed mangled/split"
[ "$(grep -c 'send-keys' "$STUB_LOG")" = 1 ] \
  && ok "launched with a single send-keys (no shell re-parse)" || bad "unexpected send-keys count"

if [ $fail = 0 ]; then echo "PASS"; else echo "FAIL"; fi
exit $fail
