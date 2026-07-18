#!/usr/bin/env bash
#
# AC proof for dispatch-adopt.sh: adopting an EXISTING instant updates the ws
# board properly. Hermetic: temp POOL_DIR, a fake base + child instant, stubbed
# tmux/claude on PATH. Never touches the real pool, ~/wsN, or a real session.
#
# Verifies:
#   (in-place) live session + inflight child -> lease claimed + record written
#              (adopted:true) + session adopted IN PLACE (not relaunched) + board
#              renders a ▶ running row with the slot LEASED and the attach cmd.
#   (parked)   child HANDOFF with a real '## Parked decision' -> board shows 🅿.
#   (relaunch) dead session -> adopt relaunches (tmux new-session) + record still
#              written so the board still tracks it.
#
# Exit 0 + PASS = all held.
#
set -uo pipefail

SKILL="$(cd "$(dirname "$0")/.." && pwd)"
ADOPT="$SKILL/dispatch-adopt.sh"
BOARD="$SKILL/dispatch-board.sh"
[ -f "$ADOPT" ] || { echo "FAIL: dispatch-adopt.sh missing"; exit 1; }
chmod +x "$SKILL"/wspool.sh "$ADOPT" "$BOARD"

FAILED=0
check() { if [ "$2" = "$3" ]; then printf '  ok: %s (%s)\n' "$1" "$2"; else printf '  XX: %s — got [%s] want [%s]\n' "$1" "$2" "$3"; FAILED=1; fi; }
checkf(){ if [ -e "$2" ]; then printf '  ok: %s exists\n' "$1"; else printf '  XX: %s MISSING (%s)\n' "$1" "$2"; FAILED=1; fi; }
has()   { if grep -q -- "$2" "$3" 2>/dev/null; then printf '  ok: %s\n' "$1"; else printf '  XX: %s — [%s] not in %s\n' "$1" "$2" "$3"; FAILED=1; fi; }
hasnt() { if grep -q -- "$2" "$3" 2>/dev/null; then printf '  XX: %s — [%s] unexpectedly in %s\n' "$1" "$2" "$3"; FAILED=1; else printf '  ok: %s\n' "$1"; fi; }

ROOT="$(mktemp -d)"; trap 'rm -rf "$ROOT"' EXIT
BIN="$ROOT/bin"; mkdir -p "$BIN"; export PATH="$BIN:$PATH"
export ROOT
# tmux stub: has-session honors $FAKE_ALIVE (1=alive/0=dead); logs everything.
cat > "$BIN/tmux" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$ROOT/tmux.log"
case "${1:-}" in
  has-session) [ "${FAKE_ALIVE:-1}" = 1 ] && exit 0 || exit 1 ;;
  *) exit 0 ;;
esac
STUB
cat > "$BIN/claude" <<'STUB'
#!/usr/bin/env bash
echo "claude $*" >> "$ROOT/claude.log"; exit 0
STUB
chmod +x "$BIN"/tmux "$BIN"/claude
export WSPOOL_SH="$SKILL/wspool.sh"
export POOL_DIR="$ROOT/pool"
export BOARD_DIR="$ROOT/board"            # global dispatch-record store (D-11)
REG="$BOARD_DIR/REGISTRY.md"

BASEDIR="$ROOT/tasks/eff"
BASE="$BASEDIR/main-07152335-complete-append-someBase"; mkdir -p "$BASE"
printf '# base HANDOFF\n' > "$BASE/HANDOFF.md"; printf '# base CHARTER\n' > "$BASE/CHARTER.md"
mkchild() {  # mkchild <name> <parked?>  -> prints the child path
  local c="$BASEDIR/$1"; mkdir -p "$c"
  printf '# %s CHARTER\n' "$1" > "$c/CHARTER.md"
  if [ "${2:-}" = parked ]; then
    printf '# HANDOFF\n## Parked decision\nNeed operator to pick strategy A vs B.\n## Live snapshot\n' > "$c/HANDOFF.md"
  else
    printf '# HANDOFF\n## Parked decision\n<none>\n## Live snapshot\n' > "$c/HANDOFF.md"
  fi
  printf '%s\n' "$c"
}

echo "== Test 1: adopt-in-place (live session) updates the board =="
: > "$ROOT/tmux.log"
CHILD1="$(mkchild someBase-07160000-inflight-append-gapAlpha)"
WS1="$ROOT/wsA"; mkdir -p "$WS1"; "$SKILL"/wspool.sh add "$WS1" >/dev/null
out1="$(FAKE_ALIVE=1 "$ADOPT" --base "$BASE" --instant "$CHILD1" --slot "$WS1" --resume uuid-1 2>&1)" \
  || { echo "$out1"; echo "  XX: adopt errored"; FAILED=1; }
REC1="$BOARD_DIR/records/gapAlpha.json"
checkf "dispatch record written (global store)" "$REC1"
python3 -c "import json;d=json.load(open('$REC1'));assert d['adopted'] is True;assert d['slot']=='wsA';assert d['child_instant'].endswith('gapAlpha');assert d['resume_session']=='uuid-1';print('  ok: record adopted:true + slot + child + resume match')" || { echo "  XX: record fields wrong"; FAILED=1; }
leased=$(find "$POOL_DIR/leases" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
check "slot leased after adopt" "$leased" "1"
hasnt "live session NOT relaunched (no new-session)" "new-session" "$ROOT/tmux.log"
# board renders it as running, with the slot LEASED and the attach cmd
FAKE_ALIVE=1 "$BOARD" >/dev/null 2>&1
has "board lists the adopted TODO" "gapAlpha" "$REG"
has "board row shows running"      "running"  "$REG"
has "board row shows LEASED slot"  "wsA: LEASED" "$REG"
has "board row shows attach cmd"   "tmux attach -t dt-gapAlpha" "$REG"

echo "== Test 2: a parked instant renders as PARKED on the board =="
CHILD2="$(mkchild someBase-07160001-inflight-append-gapBeta parked)"
WS2="$ROOT/wsB"; mkdir -p "$WS2"; "$SKILL"/wspool.sh add "$WS2" >/dev/null
FAKE_ALIVE=1 "$ADOPT" --base "$BASE" --instant "$CHILD2" --slot "$WS2" --resume uuid-2 --no-launch >/dev/null 2>&1
FAKE_ALIVE=1 "$BOARD" >/dev/null 2>&1
has "board flags the parked TODO" "PARKED" "$REG"
has "board summary counts 1 parked" "1 parked" "$REG"

echo "== Test 3: dead session => adopt relaunches, record still written =="
: > "$ROOT/tmux.log"
CHILD3="$(mkchild someBase-07160002-inflight-append-gapGamma)"
WS3="$ROOT/wsC"; mkdir -p "$WS3"; "$SKILL"/wspool.sh add "$WS3" >/dev/null
FAKE_ALIVE=0 "$ADOPT" --base "$BASE" --instant "$CHILD3" --slot "$WS3" --resume uuid-3 >/dev/null 2>&1
has "dead session was relaunched (new-session)" "new-session" "$ROOT/tmux.log"
checkf "record still written for relaunched adopt" "$BOARD_DIR/records/gapGamma.json"

echo
if [ "$FAILED" -eq 0 ]; then echo "PASS: dispatch-adopt AC (board update: in-place + parked + relaunch)"; exit 0
else echo "FAIL: dispatch-adopt AC"; exit 1; fi
