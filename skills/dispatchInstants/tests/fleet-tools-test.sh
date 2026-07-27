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
  capture-pane)
     # STUB_PANE_DELAY: return an empty pane for the first N samples (claude clears the screen
     # while starting up, so an early single sample legitimately matches nothing).
     d="${STUB_PANE_DELAY:-0}"; c="${STUB_COUNTER:-/dev/null}"
     n=$(cat "$c" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$c" 2>/dev/null
     if [ "$n" -le "$d" ]; then exit 0; fi
     cat "${STUB_PANE:-/dev/null}"; exit 0 ;;
  send-keys)
     # STUB_PASTE=1: claude turns long input into "[Pasted text #N +M lines]" and never echoes
     # the message text, so verifying by looking for the text is doomed.
     if [ "${STUB_PASTE:-0}" = "1" ]; then
       case " $* " in *" Enter "*) : ;; *) echo "[Pasted text #1 +3 lines]" >> "${STUB_PANE:-/dev/null}";; esac
       exit 0
     fi
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
  "seed_file": "$tmp/seed.txt", "dispatched_at": "2026-01-01T00:00:00Z",
  "launched_at": "2026-01-01T00:01:00Z" }
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

# PARKED: a worker blocked on a decision must surface — but the EMPTY template block must not
printf '# H\n\n## Parked decision (for the operator — empty unless I need you)\n<none>\n\n## Next\n' \
  > "$tmp/child/07180102-07190000-inflight-append-alpha/HANDOFF.md"
printf 'working\n' > "$STUB_PANE"
STUB_ALIVE=1 bash "$S/dispatch-health.sh" >/dev/null 2>&1
chk "empty parked-decision template does NOT fire" 0 $?
printf '# H\n\n## Parked decision\nShould I use approach A or B? Both meet the AC.\n\n## Next\n' \
  > "$tmp/child/07180102-07190000-inflight-append-alpha/HANDOFF.md"
# A parked OPERATOR-ONLY note while the worker keeps working is NOT a stall: it must not demand
# attention every tick (a permanently-red tick is the same false alarm as OBS-2, one layer up).
rm -f "$BOARD_DIR/health/alpha.hash"
printf 'still working, step 1\n' > "$STUB_PANE"
STUB_ALIVE=1 bash "$S/dispatch-health.sh" >/dev/null 2>&1
printf 'still working, step 2 — progress\n' > "$STUB_PANE"
out=$(STUB_ALIVE=1 bash "$S/dispatch-health.sh" 2>&1); rc=$?
chk "parked note + still progressing does NOT demand attention" 0 $rc
echo "$out" | grep -qi "parked" && ok "still surfaces the parked note" || bad "parked note not mentioned"
# ...but parked AND idle (no progress) is a genuine stall.
printf 'stuck here\n' > "$STUB_PANE"
STUB_ALIVE=1 IDLE_MIN=0 bash "$S/dispatch-health.sh" >/dev/null 2>&1
touch -d '-2 hours' "$BOARD_DIR/health/alpha.hash" 2>/dev/null
out=$(STUB_ALIVE=1 IDLE_MIN=0 bash "$S/dispatch-health.sh" 2>&1); rc=$?
chk "parked AND idle needs attention" 1 $rc
echo "$out" | grep -qi "PARKED" && ok "reports PARKED when genuinely stalled" || bad "did not report PARKED"
rm -f "$tmp/child/07180102-07190000-inflight-append-alpha/HANDOFF.md"

# json mode is machine-readable
out=$(STUB_ALIVE=1 bash "$S/dispatch-health.sh" --json 2>/dev/null)
echo "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert isinstance(d,(list,dict))' 2>/dev/null \
  && ok "--json parses" || bad "--json did not parse"

# A harvested record is terminal history, not owed work (coordinator RI-1).
python3 - "$BOARD_DIR/records/alpha.json" <<'PYX'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d["harvested_at"]="2026-01-02T00:00:00Z"; d["gate_verdict"]="READY"
json.dump(d,open(p,"w"))
PYX
mv "$tmp/child/07180102-07190000-inflight-append-alpha" "$tmp/child/07180102-07190000-complete-append-alpha"
printf 'idle\n' > "$STUB_PANE"
out=$(STUB_ALIVE=0 bash "$S/dispatch-health.sh" 2>&1); rc=$?
chk "a harvested instant no longer demands attention" 0 $rc
echo "$out" | grep -qi "harvested" && ok "shows it as harvested history" || bad "harvested state not shown"
mv "$tmp/child/07180102-07190000-complete-append-alpha" "$tmp/child/07180102-07190000-inflight-append-alpha"
python3 - "$BOARD_DIR/records/alpha.json" <<'PYX'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d.pop("harvested_at"); d.pop("gate_verdict"); json.dump(d,open(p,"w"))
PYX

# --base scopes health to ONE effort's records (a shared board shows every effort)
rec other "$tmp/child/07180102-07190001-complete-append-beta" dt-other
python3 - "$BOARD_DIR/records/other.json" <<'PYX'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d["base_instant"]="/some/other/effort"; json.dump(d,open(p,"w"))
PYX
out=$(STUB_ALIVE=1 bash "$S/dispatch-health.sh" --base "$tmp/base" 2>&1)
echo "$out" | grep -q "other" && bad "--base leaked another effort's record" || ok "--base scopes to my effort"
rm -f "$BOARD_DIR/records/other.json"

# RI-6: --no-launch writes the record immediately, but the session only exists after launch.
# The charter-review window the skill MANDATES therefore makes every correct dispatch look DEAD —
# and acting on that phantom (reap / re-dispatch) destroys a healthy worker.
python3 - "$BOARD_DIR/records/alpha.json" <<'PYX'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d.pop("launched_at",None); json.dump(d,open(p,"w"))
PYX
printf 'x\n' > "$STUB_PANE"
out=$(STUB_ALIVE=0 bash "$S/dispatch-health.sh" 2>&1); rc=$?
echo "$out" | grep -qi "PENDING" && ok "un-launched dispatch reads PENDING-LAUNCH, not DEAD" \
  || bad "phantom DEAD during the mandated review window"
chk "a pending-launch dispatch does not demand attention" 0 $rc
# ...but one left pending too long IS worth surfacing
out=$(STUB_ALIVE=0 PENDING_MAX_MIN=0 bash "$S/dispatch-health.sh" 2>&1); rc=$?
chk "a long-forgotten pending dispatch does demand attention" 1 $rc
# once launched, a missing session really is DEAD
python3 - "$BOARD_DIR/records/alpha.json" <<'PYX'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d["launched_at"]="2026-01-01T00:00:00Z"; json.dump(d,open(p,"w"))
PYX
out=$(STUB_ALIVE=0 bash "$S/dispatch-health.sh" 2>&1)
echo "$out" | grep -qi "dead" && ok "a launched-but-gone session is still DEAD" || bad "lost the real DEAD signal"

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

# A long message becomes a paste placeholder; the text never appears, but it WAS received.
: > "$STUB_LOG"; printf 'ready\n' > "$STUB_PANE"
STUB_ALIVE=1 STUB_PASTE=1 bash "$S/dispatch-send.sh" alpha "a very long coordination message that claude will turn into a pasted-text placeholder" >/dev/null 2>&1
chk "pasted-text placeholder counts as delivered" 0 $?
# Enter must be a SEPARATE keystroke, or the paste swallows it and nothing is submitted.
grep -qE 'send-keys .* Enter$' "$STUB_LOG" && ok "sends Enter as its own keystroke" || bad "Enter not sent separately"
# The busy-worker queue indicator is also proof of receipt.
: > "$STUB_LOG"; printf 'Press up to edit queued messages\n' > "$STUB_PANE"
STUB_ALIVE=1 STUB_ECHO=0 bash "$S/dispatch-send.sh" alpha "short msg" >/dev/null 2>&1
chk "queued-message indicator counts as delivered" 0 $?

STUB_ALIVE=0 bash "$S/dispatch-send.sh" alpha "x" >/dev/null 2>&1; chk "send to dead session fails" 1 $?
bash "$S/dispatch-send.sh" nosuch "x" >/dev/null 2>&1; chk "unknown id fails (rc=2)" 2 $?

echo "== dispatch-launch =="
: > "$STUB_LOG"; printf 'ready\n' > "$STUB_PANE"
STUB_ALIVE=0 STUB_ECHO=1 bash "$S/dispatch-launch.sh" alpha >/dev/null 2>&1
chk "launches a not-yet-running worker" 0 $?
grep -q "new-session" "$STUB_LOG" && ok "created the session" || bad "did not create session"
grep -q "remote-control" "$STUB_LOG" && ok "sent the claude invocation" || bad "did not send claude invocation"

# a pane that is blank while claude boots must still verify (poll, do not sample once)
: > "$STUB_LOG"; printf 'auto mode on (shift+tab to cycle)\n' > "$STUB_PANE"
export STUB_COUNTER="$tmp/cnt"; : > "$STUB_COUNTER"
STUB_ALIVE=0 STUB_ECHO=0 STUB_PANE_DELAY=2 bash "$S/dispatch-launch.sh" alpha >/dev/null 2>&1
chk "verifies a slow-starting session by polling" 0 $?
: > "$STUB_COUNTER"
# and a session that never starts must still fail
: > "$STUB_PANE"
STUB_ALIVE=0 STUB_ECHO=0 bash "$S/dispatch-launch.sh" alpha >/dev/null 2>&1
chk "still fails when the pane never shows claude" 1 $?
unset STUB_COUNTER

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
