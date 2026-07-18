#!/usr/bin/env bash
#
# AC-2 proof for dispatch-todo.sh. Hermetic: a temp POOL_DIR, a fake base instant,
# and stubbed `tmux` / `claude` / `duplicate-workspace.sh` on PATH — never touches
# the real ws pool, ~/wsN, or any real Claude session.
#
# Verifies:
#   (happy) one dispatch -> leased slot + duplicate invoked + child instant with an
#           RCA-first seeded CHARTER + dispatch record + tmux session launched (send-keys).
#   (rollback-early) duplicate fails  -> lease released, no child created.
#   (rollback-late)  tmux launch fails -> child + record removed AND lease released.
#   (guard) golden enrolled in the pool -> refused.
#
# Exit 0 + PASS = all held.
#
set -uo pipefail

SKILL="$(cd "$(dirname "$0")/.." && pwd)"
DISPATCH="$SKILL/dispatch-todo.sh"
[ -f "$DISPATCH" ] || { echo "FAIL: dispatch-todo.sh missing"; exit 1; }
chmod +x "$SKILL"/wspool.sh "$DISPATCH"

FAILED=0
check() { if [ "$2" = "$3" ]; then printf '  ok: %s (%s)\n' "$1" "$2"; else printf '  XX: %s — got [%s] want [%s]\n' "$1" "$2" "$3"; FAILED=1; fi; }
checkf(){ if [ -e "$2" ]; then printf '  ok: %s exists\n' "$1"; else printf '  XX: %s MISSING (%s)\n' "$1" "$2"; FAILED=1; fi; }
checknf(){ if [ ! -e "$2" ]; then printf '  ok: %s absent (rolled back)\n' "$1"; else printf '  XX: %s STILL PRESENT (%s)\n' "$1" "$2"; FAILED=1; fi; }

ROOT="$(mktemp -d)"; trap 'rm -rf "$ROOT"' EXIT
BIN="$ROOT/bin"; mkdir -p "$BIN"
export PATH="$BIN:$PATH"
TMUX_LOG="$ROOT/tmux.log"; DUP_LOG="$ROOT/dup.log"

# ---- stubs ------------------------------------------------------------------
cat > "$BIN/tmux" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$TMUX_LOG"
case "${1:-}" in
  has-session) exit 0 ;;                                  # always alive
  new-session) [ "${FAIL_TMUX:-0}" = 1 ] && exit 1 || exit 0 ;;
  send-keys)   exit 0 ;;
  *) exit 0 ;;
esac
STUB
cat > "$BIN/claude" <<'STUB'
#!/usr/bin/env bash
echo "claude $*" >> "$ROOT/claude.log"; exit 0
STUB
cat > "$BIN/duplicate-workspace.sh" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$DUP_LOG"; exit "${DUP_RC:-0}"
STUB
chmod +x "$BIN"/tmux "$BIN"/claude "$BIN"/duplicate-workspace.sh
export TMUX_LOG DUP_LOG ROOT
export DUPLICATE_WS_SH="$BIN/duplicate-workspace.sh"
export WSPOOL_SH="$SKILL/wspool.sh"

# ---- fake base instant + pool ----------------------------------------------
export POOL_DIR="$ROOT/pool"
export BOARD_DIR="$ROOT/board"            # global dispatch-record store (D-11); records land here
RECS_DIR="$BOARD_DIR/records"
BASEDIR="$ROOT/tasks/effortX"                          # holds instants (siblings)
BASE="$BASEDIR/main-07152335-complete-append-someBase"
mkdir -p "$BASE"
printf '# base HANDOFF\n' > "$BASE/HANDOFF.md"
printf '# base CHARTER\n' > "$BASE/CHARTER.md"
GOLDEN="$ROOT/wsG"; mkdir -p "$GOLDEN"                 # golden OUTSIDE the pool
SLOTA="$ROOT/wsA"; SLOTB="$ROOT/wsB"; mkdir -p "$SLOTA" "$SLOTB"
"$SKILL"/wspool.sh add "$SLOTA" "$SLOTB" >/dev/null

echo "== Test 1: happy path (--no-launch off; stub tmux) =="
BRIEF="$ROOT/brief1.md"; printf 'Close ANSI gap: int4 overflow. Spark throws ARITHMETIC_OVERFLOW; Velox returns wrapped value.\n' > "$BRIEF"
out="$("$DISPATCH" --base "$BASE" --title "Close ANSI gap int4 overflow" --brief "$BRIEF" \
        --profile ansi --golden "$GOLDEN" --evidence "RANKING.md#1" --evidence "c1/analysis.md" 2>&1)" || { echo "$out"; echo "FAIL: dispatch errored"; exit 1; }
CHILD="$(printf '%s\n' "$out" | sed -n 's/.*instant   : //p' | head -1)"
WS="$(printf '%s\n' "$out" | sed -n 's/.*workspace : \([^ ]*\).*/\1/p' | head -1)"
checkf "child instant dir" "$CHILD"
# grammar: exactly 5 dash-fields, dashless (camelCase) instantName, so a renamed folder stays locatable
cname="$(basename "$CHILD")"; nf=$(awk -F- '{print NF}' <<<"$cname")
check "child name has exactly 5 grammar fields" "$nf" "5"
iname="$(cut -d- -f5 <<<"$cname")"
check "instantName field is dashless camelCase" "$iname" "closeAnsiGapInt4Overflow"
checkf "child CHARTER" "$CHILD/CHARTER.md"
checkf "child HANDOFF" "$CHILD/HANDOFF.md"
checkf "child investigations/" "$CHILD/investigations"
grep -q 'RCA-FIRST'       "$CHILD/CHARTER.md" && echo "  ok: CHARTER carries RCA-FIRST mandate" || { echo "  XX: CHARTER lacks RCA-FIRST"; FAILED=1; }
grep -q 'Spark-Java=GOLD' "$CHILD/CHARTER.md" && echo "  ok: CHARTER frames gold-vs-actual" || { echo "  XX: CHARTER missing gold framing"; FAILED=1; }
grep -q 'RANKING.md#1'    "$CHILD/CHARTER.md" && echo "  ok: CHARTER carries evidence pointers" || { echo "  XX: evidence pointers missing"; FAILED=1; }
grep -q 'int4 overflow'   "$CHILD/CHARTER.md" && echo "  ok: CHARTER carries the brief" || { echo "  XX: brief missing"; FAILED=1; }
# dispatch record — now in the machine-global store, NOT under the base
checknf "no per-base dispatch dir created" "$BASE/dispatch"
REC="$(ls "$RECS_DIR"/*.json 2>/dev/null | head -1)"
checkf "dispatch record json (global store)" "$REC"
python3 -c "import json,sys; d=json.load(open('$REC')); assert d['ws']=='$WS'; assert d['child_instant']=='$CHILD'; assert d['tmux'].startswith('dt-'); print('  ok: record JSON valid + fields match')" || { echo "  XX: record json invalid"; FAILED=1; }
# duplicate invoked with golden -> ws --force
dupcall=$(grep -c -- "--force" "$DUP_LOG" 2>/dev/null || echo 0)
[ "$dupcall" -ge 1 ] && echo "  ok: duplicate-workspace.sh invoked (--force)" || { echo "  XX: duplicate not invoked"; FAILED=1; }
# tmux launched
ns=$(grep -c 'new-session' "$TMUX_LOG" 2>/dev/null || echo 0)
sk=$(grep -c 'send-keys' "$TMUX_LOG" 2>/dev/null || echo 0)
[ "$ns" -ge 1 ] && [ "$sk" -ge 1 ] && echo "  ok: interactive tmux session launched (new-session + send-keys)" || { echo "  XX: tmux launch not performed"; FAILED=1; }
# slot leased
leased=$(find "$POOL_DIR/leases" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
check "one slot leased after happy dispatch" "$leased" "1"

echo "== Test 2: rollback-early — duplicate fails => lease released, no child =="
: > "$DUP_LOG"; : > "$TMUX_LOG"
before_children=$(find "$BASEDIR" -maxdepth 1 -name '*-inflight-append-*' -type d | wc -l | tr -d ' ')
DUP_RC=1 "$DISPATCH" --base "$BASE" --title "will fail dup" --brief - --profile ansi --golden "$GOLDEN" <<<"brief" >/dev/null 2>&1
rc=$?
after_children=$(find "$BASEDIR" -maxdepth 1 -name '*-inflight-append-*' -type d | wc -l | tr -d ' ')
leased2=$(find "$POOL_DIR/leases" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
check "dispatch exited non-zero on dup failure" "$([ $rc -ne 0 ] && echo yes || echo no)" "yes"
check "no new child instant created" "$after_children" "$before_children"
check "lease count unchanged (early lease released)" "$leased2" "1"

echo "== Test 3: rollback-late — tmux launch fails => child+record+lease all removed =="
: > "$TMUX_LOG"
recs_before=$(ls "$RECS_DIR"/*.json 2>/dev/null | wc -l | tr -d ' ')
FAIL_TMUX=1 "$DISPATCH" --base "$BASE" --title "will fail launch" --brief - --profile ansi --golden "$GOLDEN" --no-duplicate <<<"brief" >/dev/null 2>&1
rc3=$?
recs_after=$(ls "$RECS_DIR"/*.json 2>/dev/null | wc -l | tr -d ' ')
child_late=$(find "$BASEDIR" -maxdepth 1 -name '*-willFailLaunch' -type d | wc -l | tr -d ' ')
leased3=$(find "$POOL_DIR/leases" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
check "dispatch exited non-zero on launch failure" "$([ $rc3 -ne 0 ] && echo yes || echo no)" "yes"
check "child instant removed (late rollback)" "$child_late" "0"
check "dispatch record removed (late rollback)" "$recs_after" "$recs_before"
check "lease released (late rollback, still just the Test-1 lease)" "$leased3" "1"

echo "== Test 4: golden guard — golden enrolled in pool is refused =="
"$SKILL"/wspool.sh add "$GOLDEN" >/dev/null       # wrongly enroll the golden
grc=0
"$DISPATCH" --base "$BASE" --title "bad golden" --brief - --profile ansi --golden "$GOLDEN" --no-launch <<<"b" >/dev/null 2>&1 || grc=$?
check "dispatch refuses enrolled golden" "$([ $grc -ne 0 ] && echo yes || echo no)" "yes"
"$SKILL"/wspool.sh remove --force "$(basename "$GOLDEN")" >/dev/null

echo "== Test 5: no profile selected (no flag/env/pool file) => error =="
prc=0
DISPATCH_PROFILE= "$DISPATCH" --base "$BASE" --title "no profile" --brief - --golden "$GOLDEN" --no-launch <<<"b" >/dev/null 2>&1 || prc=$?
check "dispatch errors when no profile is selected" "$([ $prc -ne 0 ] && echo yes || echo no)" "yes"

echo "== Test 6: unknown profile name => error =="
urc=0
"$DISPATCH" --base "$BASE" --title "bad profile" --brief - --golden "$GOLDEN" --profile doesNotExist --no-launch <<<"b" >/dev/null 2>&1 || urc=$?
check "dispatch errors on unknown profile name" "$([ $urc -ne 0 ] && echo yes || echo no)" "yes"

echo "== Test 7: custom profile dir => content + substitution =="
CUSTOM="$ROOT/customProfile"; mkdir -p "$CUSTOM"
printf 'CUSTOM CHARTER for {{TITLE}} in {{WS}}\nBRIEF: {{BRIEF}}\n' > "$CUSTOM/charter.md"
printf 'custom seed for {{TITLE}}\n' > "$CUSTOM/seed.txt"
BRIEF7="$ROOT/brief7.md"; printf 'my custom brief body\n' > "$BRIEF7"
out7="$("$DISPATCH" --base "$BASE" --title "Custom Effort X" --brief "$BRIEF7" --golden "$GOLDEN" --profile "$CUSTOM" --no-launch 2>&1)" || { echo "$out7"; echo "  XX: custom-profile dispatch errored"; FAILED=1; }
CHILD7="$(printf '%s\n' "$out7" | sed -n 's/.*instant   : //p' | head -1)"
grep -q 'CUSTOM CHARTER for Custom Effort X' "$CHILD7/CHARTER.md" && echo "  ok: custom CHARTER title substituted" || { echo "  XX: custom CHARTER not rendered"; FAILED=1; }
grep -q 'my custom brief body' "$CHILD7/CHARTER.md" && echo "  ok: custom CHARTER brief substituted" || { echo "  XX: brief not substituted"; FAILED=1; }
! grep -q '{{TITLE}}' "$CHILD7/CHARTER.md" && echo "  ok: no unrendered placeholders left" || { echo "  XX: placeholders left unrendered"; FAILED=1; }

echo
if [ "$FAILED" -eq 0 ]; then echo "PASS: dispatch-todo AC-2 (launcher + clean rollback + guards + profiles)"; exit 0
else echo "FAIL: dispatch-todo AC-2"; exit 1; fi
