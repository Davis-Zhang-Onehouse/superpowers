#!/usr/bin/env bash
#
# AC-3 proof for dispatch-board.sh (D-11: machine-global, argument-less board).
# Hermetic (temp POOL_DIR + BOARD_DIR + stubs). Verifies:
#   - `dispatch-board.sh` (NO args) renders the global store, GROUPED BY BASE, marking
#     each TODO running, with the tmux attach cmd + child path
#   - two DIFFERENT bases both appear as their own group
#   - passing a base path is DEPRECATED -> exits 2 with the deprecation message
#   - fallback legacy read: a leftover <base>/dispatch/*.json is merged in (the base is
#     discovered from the global store); a todo_id collision is deduped (global wins)
#   - after a child is `mv`'d to -complete-, board reflects complete (located post-rename)
#   - after a child parks a decision in HANDOFF, board marks it PARKED; summary counts hold
#
set -uo pipefail
SKILL="$(cd "$(dirname "$0")/.." && pwd)"
chmod +x "$SKILL"/wspool.sh "$SKILL"/dispatch-todo.sh "$SKILL"/dispatch-board.sh
FAILED=0
check(){ if [ "$2" = "$3" ]; then printf '  ok: %s (%s)\n' "$1" "$2"; else printf '  XX: %s — got [%s] want [%s]\n' "$1" "$2" "$3"; FAILED=1; fi; }
has(){ if grep -qF -- "$2" "$3"; then printf '  ok: %s\n' "$1"; else printf '  XX: %s — %s not in %s\n' "$1" "$2" "$3"; FAILED=1; fi; }
hasnt(){ if grep -qF -- "$2" "$3"; then printf '  XX: %s — unexpected %s in %s\n' "$1" "$2" "$3"; FAILED=1; else printf '  ok: %s\n' "$1"; fi; }

ROOT="$(mktemp -d)"; trap 'rm -rf "$ROOT"' EXIT
BIN="$ROOT/bin"; mkdir -p "$BIN"; export PATH="$BIN:$PATH"
cat > "$BIN/tmux" <<'S'
#!/usr/bin/env bash
[ "${1:-}" = has-session ] && exit 0
exit 0
S
for t in claude duplicate-workspace.sh; do printf '#!/usr/bin/env bash\nexit 0\n' > "$BIN/$t"; chmod +x "$BIN/$t"; done
chmod +x "$BIN/tmux"
export DUPLICATE_WS_SH="$BIN/duplicate-workspace.sh" WSPOOL_SH="$SKILL/wspool.sh"
export POOL_DIR="$ROOT/pool"
export BOARD_DIR="$ROOT/board"                       # global dispatch-record store (D-11)
BRD="$BOARD_DIR/REGISTRY.md"

# two DIFFERENT base instants (different effort dirs => distinct groups)
BASE="$ROOT/tasks/effA/main-07152335-complete-append-someBase"; mkdir -p "$BASE"
printf '# H\n' > "$BASE/HANDOFF.md"; printf '# C\n' > "$BASE/CHARTER.md"
BASE2="$ROOT/tasks/effB/main-07160000-inflight-append-otherBase"; mkdir -p "$BASE2"
printf '# H\n' > "$BASE2/HANDOFF.md"; printf '# C\n' > "$BASE2/CHARTER.md"
G="$ROOT/wsG"; mkdir -p "$G"
A="$ROOT/wsA"; B="$ROOT/wsB"; C="$ROOT/wsC"; mkdir -p "$A" "$B" "$C"
"$SKILL"/wspool.sh add "$A" "$B" "$C" >/dev/null

echo "== dispatch two TODOs on BASE + one on BASE2 (--no-launch) =="
c1out="$("$SKILL"/dispatch-todo.sh --base "$BASE"  --title "gap alpha" --brief - --profile ansi --golden "$G" --no-launch <<<"brief alpha")"
c2out="$("$SKILL"/dispatch-todo.sh --base "$BASE"  --title "gap beta"  --brief - --profile ansi --golden "$G" --no-launch <<<"brief beta")"
c3out="$("$SKILL"/dispatch-todo.sh --base "$BASE2" --title "gap gamma" --brief - --profile ansi --golden "$G" --no-launch <<<"brief gamma")"
C1="$(sed -n 's/.*instant   : //p' <<<"$c1out" | head -1)"
C2="$(sed -n 's/.*instant   : //p' <<<"$c2out" | head -1)"
C3="$(sed -n 's/.*instant   : //p' <<<"$c3out" | head -1)"
{ [ -d "$C1" ] && [ -d "$C2" ] && [ -d "$C3" ]; } && echo "  ok: three child instants created" || { echo "  XX: children missing"; FAILED=1; }
[ ! -d "$BASE/dispatch" ] && echo "  ok: records went to the global store, not <base>/dispatch/" || { echo "  XX: <base>/dispatch/ unexpectedly created"; FAILED=1; }

echo "== board (NO args): global, grouped by base, all running =="
"$SKILL"/dispatch-board.sh >/dev/null
has "lists gap alpha" "gap alpha" "$BRD"
has "lists gap beta"  "gap beta"  "$BRD"
has "lists gap gamma" "gap gamma" "$BRD"
has "group header for BASE"  "$(basename "$BASE")"  "$BRD"
has "group header for BASE2" "$(basename "$BASE2")" "$BRD"
has "shows attach cmd" "tmux attach -t dt-" "$BRD"
has "shows a child instant path" "$C1" "$BRD"
run_ct=$(grep -c '▶ running' "$BRD"); check "three running rows" "$run_ct" "3"

echo "== deprecation: passing a base path errors out =="
drc=0; dmsg="$("$SKILL"/dispatch-board.sh "$BASE" 2>&1)" || drc=$?
check "board with a path exits 2" "$drc" "2"
grep -q "no longer takes a base path" <<<"$dmsg" && echo "  ok: prints deprecation message" || { echo "  XX: missing deprecation message"; FAILED=1; }

echo "== fallback legacy read + dedup (global wins) =="
# (a) a genuine leftover legacy record for BASE2 (new todo_id) -> must be merged
mkdir -p "$BASE2/dispatch"
LC="$ROOT/tasks/effB/otherBase-07160005-inflight-append-legacyGap"; mkdir -p "$LC"
printf '# H\n## Parked decision\n<none>\n' > "$LC/HANDOFF.md"; printf '# C\n' > "$LC/CHARTER.md"
cat > "$BASE2/dispatch/legacyGap.json" <<EOF
{ "todo_id":"legacyGap","title":"legacy fallback row","child_instant":"$LC","ws":"$C","slot":"wsC","tmux":"dt-legacyGap","base_instant":"$BASE2","dispatched_at":"2026-07-16T00:00:00Z" }
EOF
# (b) a SHADOW legacy record colliding with gap alpha's global todo_id -> global must win
ALPHA_ID="$(basename "$(grep -rl '"title": "gap alpha"' "$BOARD_DIR/records"/*.json | head -1)" .json)"
mkdir -p "$BASE/dispatch"
cat > "$BASE/dispatch/${ALPHA_ID}.json" <<EOF
{ "todo_id":"$ALPHA_ID","title":"SHADOW SHOULD NOT WIN","child_instant":"$C1","ws":"$A","slot":"wsA","tmux":"dt-$ALPHA_ID","base_instant":"$BASE","dispatched_at":"2026-07-16T00:00:00Z" }
EOF
"$SKILL"/dispatch-board.sh >/dev/null
has "legacy fallback row merged in" "legacy fallback row" "$BRD"
hasnt "global record wins the todo_id collision" "SHADOW SHOULD NOT WIN" "$BRD"

echo "== transition C1 -> complete (rename), board must follow =="
C1c="${C1/-inflight-/-complete-}"; mv "$C1" "$C1c"
"$SKILL"/dispatch-board.sh >/dev/null
has "C1 now complete (located post-rename)" "✅ complete" "$BRD"
has "board shows renamed complete path" "$C1c" "$BRD"

echo "== C2 parks a decision, board must flag PARKED =="
python3 - "$C2/HANDOFF.md" <<'PY'
import sys
p=sys.argv[1]; s=open(p).read()
s=s.replace("<none>","Should I widen scope to also fix try_* path? Need operator call.")
open(p,"w").write(s)
PY
"$SKILL"/dispatch-board.sh >/dev/null
has "C2 flagged PARKED" "PARKED — needs you" "$BRD"
has "summary calls out parked" "need you" "$BRD"
park_ct=$(grep -c '🅿 PARKED' "$BRD"); check "exactly one parked row" "$park_ct" "1"
has "summary: 1 complete" "✅ 1 complete" "$BRD"
has "summary: 1 parked" "🅿 1 parked" "$BRD"

echo
if [ "$FAILED" -eq 0 ]; then echo "PASS: dispatch-board AC-3 (global, grouped, deprecation + fallback-dedup, rename-tracking)"; exit 0
else echo "FAIL: dispatch-board AC-3"; exit 1; fi
