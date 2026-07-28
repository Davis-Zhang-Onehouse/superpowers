#!/usr/bin/env bash
# Hermetic self-tests for the dispatch SESSION LIFETIME: dispatch-close.sh, dispatch-sessions.sh,
# the wspool cwd coupling, and dispatch-health's unsubmitted-input detection.
#
# Why this suite exists: `dispatch-launch` stamps launched_at and nothing ever wrote the closing half,
# so finished sessions leaked. Two lived 9 days past their effort and held ~/ws3 as cwd at the same
# time as a current worker. See docs/superpowers/specs/2026-07-28-dispatch-session-lifetime-design.md.
#
# Everything is stubbed: tmux is a stub on PATH, live processes are described by probe scripts
# (SESSION_PROBE / WSPOOL_CWD_PROBE / MONITOR_PROBE), and BOARD_DIR/POOL_DIR are throwaway dirs.
# No real session, process or slot is touched.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$here/.."
fail=0
ok(){ echo "  ok   - $1"; }
bad(){ echo "  FAIL - $1"; fail=1; }
chk(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (expected rc=$2, got rc=$3)"; fi; }
has(){ if printf '%s' "$2" | grep -qiE "$3"; then ok "$1"; else bad "$1 — output lacked /$3/"; fi; }
hasnt(){ if printf '%s' "$2" | grep -qiE "$3"; then bad "$1 — output unexpectedly had /$3/"; else ok "$1"; fi; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export BOARD_DIR="$tmp/board"; mkdir -p "$BOARD_DIR/records"
export POOL_DIR="$tmp/pool"
mkdir -p "$tmp/bin" "$tmp/child" "$tmp/killed" "$tmp/ws1" "$tmp/ws2"

# ---- stub tmux -------------------------------------------------------------
# kill-session leaves a marker so a later has-session correctly reports the session GONE — a stub
# where kill has no effect would let an idempotency test pass without the kill ever happening.
cat > "$tmp/bin/tmux" <<STUB
#!/usr/bin/env bash
log="\${STUB_LOG:-/dev/null}"; echo "tmux \$*" >> "\$log"
name=""
for i in "\$@"; do case "\$prev" in -t) name="\$i";; esac; prev="\$i"; done
case "\$1" in
  has-session)  [ -f "$tmp/killed/\$name" ] && exit 1
                [ "\${STUB_ALIVE:-1}" = "1" ] && exit 0 || exit 1 ;;
  kill-session) touch "$tmp/killed/\$name"; exit 0 ;;
  capture-pane) [ -f "$tmp/killed/\$name" ] && exit 1
                cat "\${STUB_PANE:-/dev/null}"; exit 0 ;;
  *) exit 0 ;;
esac
STUB
chmod +x "$tmp/bin/tmux"
export TMUX_BIN="$tmp/bin/tmux"
export STUB_LOG="$tmp/tmux.log"
export STUB_PANE="$tmp/pane.txt"

# ---- pane fixtures ---------------------------------------------------------
# The real shapes, copied from live panes on 2026-07-28.
pane_idle(){ cat > "$STUB_PANE" <<'P'
  Nothing is parked and no operator input is needed.
                                       new task? /clear to save 148.6k tokens
────────────────────────────────────────────────────────────────────────────
❯
────────────────────────────────────────────────────────────────────────────
  ⏵⏵ auto mode on (shift+tab to cycle) · ← for agents
P
}
pane_unsubmitted(){ cat > "$STUB_PANE" <<'P'
  Nothing is parked and no operator input is needed.
                                       new task? /clear to save 148.6k tokens
────────────────────────────────────────────────────────────────────────────
❯ authorize one CI run for the 8 gaps green by name
────────────────────────────────────────────────────────────────────────────
  ⏵⏵ auto mode on (shift+tab to cycle) · ← for agents
P
}
pane_busy(){ cat > "$STUB_PANE" <<'P'
✻ Cogitating… (2h 32m 9s · esc to interrupt)
────────────────────────────────────────────────────────────────────────────
❯
────────────────────────────────────────────────────────────────────────────
P
}
pane_idle

# ---- board records ---------------------------------------------------------
rec(){ # rec <id> <child-dir> [extra-json] [slot]
  cat > "$BOARD_DIR/records/$1.json" <<EOF
{ "todo_id": "$1", "title": "T $1", "child_instant": "$2", "ws": "$tmp/ws1",
  "slot": "${4:-ws1}", "tmux": "dt-$1", "base_instant": "$tmp/base",
  "seed_file": "$tmp/seed.txt", "dispatched_at": "2026-01-01T00:00:00Z",
  "launched_at": "2026-01-01T00:01:00Z"${3:+, $3} }
EOF
}
mk_instant(){ mkdir -p "$tmp/child/$1/evidence"; echo "$tmp/child/$1"; }

RUNNING_DIR="$(mk_instant 07180102-07190000-inflight-append-running)"
DONE_DIR="$(mk_instant 07180102-07190001-complete-append-donebutopen)"
HARV_DIR="$(mk_instant 07180102-07190002-complete-append-harvested)"
rec running  "$RUNNING_DIR"
rec doneopen "$DONE_DIR"
rec harv     "$HARV_DIR" '"harvested_at": "2026-01-02T00:00:00Z", "gate_verdict": "READY"'

# ---- probe stubs -----------------------------------------------------------
# SESSION_PROBE describes the live claude processes: pid<TAB>cwd<TAB>remote-control-session
cat > "$tmp/bin/session-probe" <<PROBE
#!/usr/bin/env bash
cat "\${PROBE_FILE:-/dev/null}"
PROBE
chmod +x "$tmp/bin/session-probe"
export SESSION_PROBE="$tmp/bin/session-probe"
export PROBE_FILE="$tmp/probe.tsv"
printf '%s\t%s\t%s\n' 101 "$tmp/ws1" "dt-running"  >  "$PROBE_FILE"
printf '%s\t%s\t%s\n' 102 "$tmp/ws2" "dt-harv"     >> "$PROBE_FILE"
printf '%s\t%s\t%s\n' 103 "$tmp/elsewhere" ""      >> "$PROBE_FILE"   # UNCLAIMED: no record

# WSPOOL_CWD_PROBE <path> prints the pids holding it as cwd
cat > "$tmp/bin/cwd-probe" <<PROBE
#!/usr/bin/env bash
grep -P "\t\$1\t" "\${PROBE_FILE:-/dev/null}" 2>/dev/null | cut -f1
PROBE
chmod +x "$tmp/bin/cwd-probe"
export WSPOOL_CWD_PROBE="$tmp/bin/cwd-probe"

# MONITOR_PROBE prints monitor-pid<TAB>target-pid ; KILL_BIN records what got killed
printf '%s\t%s\n' 901 102 > "$tmp/monitors.tsv"
cat > "$tmp/bin/monitor-probe" <<PROBE
#!/usr/bin/env bash
cat "$tmp/monitors.tsv"
PROBE
chmod +x "$tmp/bin/monitor-probe"
export MONITOR_PROBE="$tmp/bin/monitor-probe"
cat > "$tmp/bin/killstub" <<KS
#!/usr/bin/env bash
echo "\$*" >> "$tmp/killed.log"
KS
chmod +x "$tmp/bin/killstub"
export KILL_BIN="$tmp/bin/killstub"

CLOSE="$S/dispatch-close.sh"
SESSIONS="$S/dispatch-sessions.sh"
WSPOOL="$S/wspool.sh"
HEALTH="$S/dispatch-health.sh"
GATE="$here/../../coordinating-instants/tools/workspace-gate.py"

echo "== dispatch-close: state guard =="
out=$(bash "$CLOSE" running 2>&1); rc=$?
chk "refuses to close a worker that is still running" 1 $rc
has "names the reason it refused" "$out" "not finished|still running|-complete-|harvested"

# A separate record, so dt-running stays alive for the enumeration tests below.
rec running2 "$RUNNING_DIR"
out=$(bash "$CLOSE" running2 --force 2>&1); rc=$?
chk "--force closes an unfinished worker anyway" 0 $rc

echo "== dispatch-close: the happy path =="
: > "$tmp/killed.log"
out=$(bash "$CLOSE" harv 2>&1); rc=$?
chk "closes a harvested worker" 0 $rc
grep -q "kill-session" "$tmp/tmux.log" && ok "issued tmux kill-session" || bad "never killed the session"
grep -q '"closed_at"' "$BOARD_DIR/records/harv.json" && ok "stamps closed_at on the record" \
  || bad "no closed_at stamped"
grep -q '"closed_by": *"manual"' "$BOARD_DIR/records/harv.json" && ok "stamps closed_by=manual" \
  || bad "no closed_by=manual"
has "prints the resume route at the moment of destruction" "$out" "claude --resume|resume"
ls "$HARV_DIR"/evidence/session-close/* >/dev/null 2>&1 \
  && ok "captured the pane to evidence BEFORE killing" || bad "no pane capture in evidence/"
grep -q '^901' "$tmp/killed.log" && ok "killed the auto-retry monitor aimed at that pid" \
  || bad "left the auto-retry monitor armed"

echo "== dispatch-close: idempotent =="
out=$(bash "$CLOSE" harv 2>&1); rc=$?
chk "closing an already-dead session exits 0" 0 $rc
has "says it was already closed" "$out" "already"

echo "== dispatch-close: unsubmitted input is not silently discarded =="
pane_unsubmitted
rec queued "$HARV_DIR" '"harvested_at": "2026-01-02T00:00:00Z"'
out=$(bash "$CLOSE" queued 2>&1); rc=$?
chk "refuses while the input box holds unsubmitted text" 1 $rc
has "quotes the text it would have destroyed" "$out" "authorize one CI run"
out=$(bash "$CLOSE" queued --force 2>&1); rc=$?
chk "--force overrides the unsubmitted-input refusal" 0 $rc

echo "== dispatch-close: never kill a pane that is mid-turn =="
pane_busy
rec busy "$HARV_DIR" '"harvested_at": "2026-01-02T00:00:00Z"'
out=$(bash "$CLOSE" busy 2>&1); rc=$?
chk "refuses a session that is actively working" 1 $rc
has "says why" "$out" "mid-turn|working|esc to interrupt|busy"
pane_idle

echo "== dispatch-close: id resolution =="
out=$(bash "$CLOSE" nosuchid 2>&1); rc=$?
chk "unknown id exits 2" 2 $rc
rec ambig1 "$HARV_DIR" '"harvested_at": "2026-01-02T00:00:00Z"'
rec ambig2 "$HARV_DIR" '"harvested_at": "2026-01-02T00:00:00Z"'
out=$(bash "$CLOSE" ambig 2>&1); rc=$?
chk "an ambiguous prefix is REFUSED, not silently resolved to the first" 2 $rc
# Both candidates must be named — one per line, so assert them separately rather than asserting an
# ordering on one line that was never a requirement.
has "lists candidate ambig1" "$out" "ambig1"
has "lists candidate ambig2" "$out" "ambig2"
rm -f "$BOARD_DIR/records/ambig1.json" "$BOARD_DIR/records/ambig2.json"

echo "== dispatch-close: releases only its OWN slot lease =="
bash "$WSPOOL" add "$tmp/ws1" "$tmp/ws2" >/dev/null 2>&1
mkdir -p "$POOL_DIR/leases/ws1" "$POOL_DIR/leases/ws2"
printf 'TODO_ID=slotted\nTMUX=dt-slotted\nWS_PATH=%s\n'    "$tmp/ws1" > "$POOL_DIR/leases/ws1/meta"
printf 'TODO_ID=someoneelse\nTMUX=dt-other\nWS_PATH=%s\n'  "$tmp/ws2" > "$POOL_DIR/leases/ws2/meta"
: > "$PROBE_FILE"     # nothing holds either cwd, so release is permitted

rec slotted "$HARV_DIR" '"harvested_at": "2026-01-02T00:00:00Z"' ws1
bash "$CLOSE" slotted >/dev/null 2>&1
[ ! -d "$POOL_DIR/leases/ws1" ] && ok "released its own lease" || bad "left its own lease held"

# The squatter's RECORD points at ws2, but ws2's lease meta names a different todo. Closing it must
# not free that lease. Without the ownership check this closes and frees another effort's slot —
# so the record must name the contested slot, or the assertion proves nothing.
rec squatter "$HARV_DIR" '"harvested_at": "2026-01-02T00:00:00Z"' ws2
bash "$CLOSE" squatter >/dev/null 2>&1
[ -d "$POOL_DIR/leases/ws2" ] && ok "left a lease whose meta names another todo alone" \
  || bad "freed someone else's lease"
printf '%s\t%s\t%s\n' 101 "$tmp/ws1" "dt-running" >  "$PROBE_FILE"
printf '%s\t%s\t%s\n' 102 "$tmp/ws2" "dt-harv"    >> "$PROBE_FILE"
printf '%s\t%s\t%s\n' 103 "$tmp/elsewhere" ""     >> "$PROBE_FILE"

echo "== dispatch-sessions: enumerate from SESSIONS, not from records =="
# Reset dt-harv to un-closed and alive: the close tests above deliberately killed it, and the
# enumeration tests need a FINISHED-but-still-alive session to classify.
rm -f "$tmp/killed/dt-harv"
rec harv "$HARV_DIR" '"harvested_at": "2026-01-02T00:00:00Z", "gate_verdict": "READY"'
out=$(bash "$SESSIONS" 2>&1); rc=$?
has "classifies the working worker ACTIVE"        "$out" "ACTIVE"
has "classifies the harvested worker FINISHED"    "$out" "FINISHED"
has "reports a session with NO record"            "$out" "UNCLAIMED"
has "names the unclaimed pid so it is not invisible" "$out" "103"

echo "== dispatch-sessions: --base scopes records, and says so about the rest =="
# Found by pointing the tool at the real fleet after the fixtures went green: an UNCLAIMED session
# has no record and therefore no base, so --base cannot scope it. Dropping it would rebuild the
# exact blind spot this command exists to remove; the honest answer is to keep it and say so.
out=$(bash "$SESSIONS" --base "$tmp/base" 2>&1)
has "--base keeps this effort's claimed rows"        "$out" "ACTIVE"
has "--base still surfaces the unclaimed stray"      "$out" "UNCLAIMED"
has "…and states that unclaimed rows are unscoped"   "$out" "machine-wide"
out=$(bash "$SESSIONS" --base "$tmp/someone-elses-effort" 2>&1)
# Anchored to the session NAME, not the word ACTIVE — the summary counter line contains
# "0 ACTIVE · …", so grepping the class word matches the tool's own tally and proves nothing.
hasnt "--base excludes another effort's claimed rows" "$out" "dt-running"

echo "== dispatch-sessions: escalation that can clear =="
SESSION_TTL_MIN=0 bash "$SESSIONS" >/dev/null 2>&1; rc=$?
chk "exits 1 while a FINISHED session is past its TTL" 1 $rc
out=$(SESSION_TTL_MIN=0 bash "$SESSIONS" --reap 2>&1); rc=$?
chk "--reap exits 0 after reaping" 0 $rc
grep -q '"closed_by": *"ttl"' "$BOARD_DIR/records/harv.json" && ok "records the TTL reap as closed_by=ttl" \
  || bad "TTL reap did not stamp closed_by=ttl"
# Weak form ("the word 103 did not appear near 'reaped'") would pass even if the sweep never ran.
# Assert the surviving state instead: after a full reap the unclaimed session is STILL listed.
after=$(SESSION_TTL_MIN=0 bash "$SESSIONS" 2>&1)
has "an UNCLAIMED session survives a --reap and is still reported" "$after" "UNCLAIMED"
has "…and it is still the same pid" "$after" "103"
SESSION_TTL_MIN=0 bash "$SESSIONS" >/dev/null 2>&1; rc=$?
chk "the alarm CLEARS once reaped (exit 0)" 0 $rc

echo "== dispatch-sessions: a huge TTL reaps nothing =="
printf '%s\t%s\t%s\n' 104 "$tmp/ws2" "dt-doneopen" >> "$PROBE_FILE"
SESSION_TTL_MIN=999999 bash "$SESSIONS" >/dev/null 2>&1; rc=$?
chk "a FINISHED session inside its TTL does not raise" 0 $rc

echo "== wspool: a slot a live process sits in is NOT free =="
mkdir -p "$POOL_DIR/leases/ws1"
printf 'TODO_ID=running\nTMUX=dt-running\nWS_PATH=%s\n' "$tmp/ws1" > "$POOL_DIR/leases/ws1/meta"
out=$(bash "$WSPOOL" release ws1 2>&1); rc=$?
chk "release refuses while a live process holds the slot as cwd" 1 $rc
has "names the pid that is still in there" "$out" "101"
[ -d "$POOL_DIR/leases/ws1" ] && ok "the lease survived the refused release" || bad "released it anyway"
out=$(bash "$WSPOOL" release ws1 --force 2>&1); rc=$?
chk "--force releases anyway" 0 $rc

echo "== wspool: claim skips an occupied slot =="
rm -rf "$POOL_DIR/leases"/*
# ws1 occupied, ws2 empty: the claim must land on ws2 rather than handing out the occupied slot.
printf '%s\t%s\t%s\n' 101 "$tmp/ws1" "dt-running" > "$PROBE_FILE"
out=$(bash "$WSPOOL" claim --todo newguy --tmux dt-newguy --base "$tmp/base" --child "$tmp/child" 2>&1); rc=$?
chk "claim succeeds" 0 $rc
hasnt "did not hand out ws1, which a live process occupies" "$out" "ws1$"

echo "== dispatch-health: a swallowed submit is visible =="
rm -f "$BOARD_DIR/records/"*.json; rm -rf "$tmp/killed"; mkdir -p "$tmp/killed"
rec running "$RUNNING_DIR"
export HEALTH_TAG="lifetest"
# Age the idle baseline by touching it rather than sleeping: `find -mmin` works in whole minutes,
# so a sleep long enough to be real would make this suite take a minute per assertion.
go_idle(){ rm -rf "$BOARD_DIR/health"; bash "$HEALTH" >/dev/null 2>&1
           touch -d '10 minutes ago' "$BOARD_DIR/health/$HEALTH_TAG"/*.hash 2>/dev/null; }

pane_unsubmitted
go_idle
out=$(IDLE_MIN=1 bash "$HEALTH" 2>&1)
has "flags unsubmitted input on an idle pane" "$out" "unsubmitted|unsent|queued"
has "quotes the stuck text" "$out" "authorize one CI run"

echo "== dispatch-health: the false-alarm direction is pinned too =="
# The direction that matters most: six false-alarm defects in this toolkit were all "the check fired
# on the empty template shape". An empty input box must never read as a swallowed submit.
pane_idle
go_idle
out=$(IDLE_MIN=1 bash "$HEALTH" 2>&1)
hasnt "an EMPTY input box is never reported as unsubmitted" "$out" "unsubmitted|unsent"

echo "== workspace-gate: harvest closes the session =="
rm -f "$BOARD_DIR/records/"*.json; rm -rf "$tmp/killed"; mkdir -p "$tmp/killed"
G="$tmp/child/07180102-07190009-complete-append-gated"
mkdir -p "$G/evidence"
cat > "$G/REVIEW.md" <<'RV'
# REVIEW
## Round R1 — 2026-07-27 · trigger: on-demand · scope: all
### Stage 1 — Format & hygiene   (verdict: PASS)
nothing open.
## Round summary — overall verdict: READY
- Stage verdicts: format=PASS · alignment=PASS · code=PASS
- Open findings: Critical 0 · Important 0 · Minor 0
RV
rec gated "$G"
pane_idle
out=$(python3 "$GATE" "$G" --harvest --record 2>&1); rc=$?
chk "the gate still passes" 0 $rc
grep -q '"closed_at"' "$BOARD_DIR/records/gated.json" && ok "harvest closed the session" \
  || bad "harvest left the session running"
grep -q '"closed_by": *"harvest"' "$BOARD_DIR/records/gated.json" && ok "closed_by=harvest" \
  || bad "wrong closed_by"

echo "== workspace-gate: --keep-session must be justified, and is recorded =="
rm -f "$BOARD_DIR/records/"*.json; rm -rf "$tmp/killed"; mkdir -p "$tmp/killed"
rec gated2 "$G"
out=$(python3 "$GATE" "$G" --harvest --record --keep-session "lift-03 may still need its tree" 2>&1); rc=$?
chk "the gate passes with --keep-session" 0 $rc
grep -q '"closed_at"' "$BOARD_DIR/records/gated2.json" && bad "--keep-session still closed it" \
  || ok "--keep-session left the session alone"
grep -q 'lift-03 may still need its tree' "$BOARD_DIR/records/gated2.json" \
  && ok "records WHY the session was kept" || bad "kept the session with no recorded reason"

echo "== the watchdog stops re-arming a finished dispatch =="
# The auto-retry daemon reconciles every 300s and used to re-attach a monitor to any in-scope
# session forever, because "finished" was not a fact it could read. A monitor on a stale worker is
# a keystroke injector: on a rate-limit banner it types "Continue where you left off." + Enter.
rm -f "$BOARD_DIR/records/"*.json; rm -rf "$tmp/killed"; mkdir -p "$tmp/killed"
rec running "$RUNNING_DIR"
rec harv    "$HARV_DIR" '"harvested_at": "2026-01-02T00:00:00Z"'
printf '%s\t%s\t%s\n' 101 "$tmp/ws1" "dt-running" >  "$PROBE_FILE"
printf '%s\t%s\t%s\n' 102 "$tmp/ws2" "dt-harv"    >> "$PROBE_FILE"
printf '%s\t%s\t%s\n' 199 "/somewhere/else" ""    >> "$PROBE_FILE"

out=$(bash "$SESSIONS" --finished-pids 2>/dev/null)
[ "$(printf '%s' "$out" | tr -d '[:space:]')" = "102" ] \
  && ok "--finished-pids names exactly the finished worker" \
  || bad "--finished-pids returned '$out', expected just 102"

cat > "$tmp/bin/wd-pids" <<PROBE
#!/usr/bin/env bash
cut -f1 "$PROBE_FILE"
PROBE
cat > "$tmp/bin/wd-cwd" <<PROBE
#!/usr/bin/env bash
awk -F'\t' -v p="\$1" '\$1==p {print \$2}' "$PROBE_FILE"
PROBE
chmod +x "$tmp/bin/wd-pids" "$tmp/bin/wd-cwd"

WD="$here/../../../scripts/claude-watchdog.sh"
ex=$(CLAUDE_WATCHDOG_ROOT="$tmp" CLAUDE_WATCHDOG_HOME="$tmp" \
     CLAUDE_WATCHDOG_SESSIONS_TOOL="$SESSIONS" \
     WATCHDOG_PIDS_PROBE="$tmp/bin/wd-pids" WATCHDOG_CWD_PROBE="$tmp/bin/wd-cwd" \
     bash "$WD" _excludes 2>/dev/null)
printf '%s\n' "$ex" | grep -qx 102 && ok "excludes the FINISHED worker from re-arming" \
  || bad "a finished dispatch would still be re-armed"
printf '%s\n' "$ex" | grep -qx 199 && ok "still excludes an out-of-scope session" \
  || bad "lost the pre-existing out-of-scope exclusion"
printf '%s\n' "$ex" | grep -qx 101 && bad "excluded a worker that is still working" \
  || ok "an ACTIVE worker stays armed"

echo
if [ "$fail" = 0 ]; then echo "PASS: dispatch session lifetime"; else echo "FAIL"; exit 1; fi
