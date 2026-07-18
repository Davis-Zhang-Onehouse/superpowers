#!/usr/bin/env bash
#
# AC-3 proof for dispatch-board.sh: the dashboard is fully DERIVED and tracks each
# child instant's state through renames. Hermetic (temp POOL_DIR + stubs).
#
# Verifies, after dispatching two TODOs:
#   - board lists both, marks them running, shows the tmux attach cmd + child path
#   - after one child is `mv`'d to -complete-, board reflects complete (located post-rename)
#   - after the other parks a decision in HANDOFF, board marks it PARKED
#   - summary counts are correct
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
for t in tmux claude; do printf '#!/usr/bin/env bash\nexit 0\n' > "$BIN/$t"; chmod +x "$BIN/$t"; done
printf '#!/usr/bin/env bash\nexit 0\n' > "$BIN/tmux"; cat > "$BIN/tmux" <<'S'
#!/usr/bin/env bash
[ "${1:-}" = has-session ] && exit 0
exit 0
S
chmod +x "$BIN/tmux"
printf '#!/usr/bin/env bash\nexit 0\n' > "$BIN/duplicate-workspace.sh"; chmod +x "$BIN/duplicate-workspace.sh"
export DUPLICATE_WS_SH="$BIN/duplicate-workspace.sh" WSPOOL_SH="$SKILL/wspool.sh"
export POOL_DIR="$ROOT/pool"

BASEDIR="$ROOT/tasks/eff"; BASE="$BASEDIR/main-07152335-complete-append-someBase"; mkdir -p "$BASE"
printf '# H\n' > "$BASE/HANDOFF.md"; printf '# C\n' > "$BASE/CHARTER.md"
G="$ROOT/wsG"; mkdir -p "$G"; A="$ROOT/wsA"; B="$ROOT/wsB"; mkdir -p "$A" "$B"
"$SKILL"/wspool.sh add "$A" "$B" >/dev/null

echo "== dispatch two TODOs (--no-launch) =="
c1out="$("$SKILL"/dispatch-todo.sh --base "$BASE" --title "gap alpha" --brief - --profile ansi --golden "$G" --no-launch <<<"brief alpha")"
c2out="$("$SKILL"/dispatch-todo.sh --base "$BASE" --title "gap beta"  --brief - --profile ansi --golden "$G" --no-launch <<<"brief beta")"
C1="$(sed -n 's/.*instant   : //p' <<<"$c1out" | head -1)"
C2="$(sed -n 's/.*instant   : //p' <<<"$c2out" | head -1)"
[ -d "$C1" ] && [ -d "$C2" ] && echo "  ok: two child instants created" || { echo "  XX: children missing"; FAILED=1; }

echo "== board 1: both running =="
BRD="$BASE/dispatch/REGISTRY.md"
"$SKILL"/dispatch-board.sh "$BASE" >/dev/null
has "lists gap alpha" "gap alpha" "$BRD"
has "lists gap beta" "gap beta" "$BRD"
has "shows attach cmd" "tmux attach -t dt-" "$BRD"
has "shows child instant path" "$C1" "$BRD"
run_ct=$(grep -c '▶ running' "$BRD"); check "two running rows" "$run_ct" "2"

echo "== transition C1 -> complete (rename), board must follow =="
C1c="${C1/-inflight-/-complete-}"; mv "$C1" "$C1c"
"$SKILL"/dispatch-board.sh "$BASE" >/dev/null
has "C1 now complete (located post-rename)" "✅ complete" "$BRD"
has "board shows renamed complete path" "$C1c" "$BRD"

echo "== C2 parks a decision, board must flag PARKED =="
# replace the <none> placeholder with a real parked question
python3 - "$C2/HANDOFF.md" <<'PY'
import sys,re
p=sys.argv[1]; s=open(p).read()
s=s.replace("<none>","Should I widen scope to also fix try_* path? Need operator call.")
open(p,"w").write(s)
PY
"$SKILL"/dispatch-board.sh "$BASE" >/dev/null
has "C2 flagged PARKED" "PARKED — needs you" "$BRD"
has "summary calls out parked" "need you" "$BRD"
park_ct=$(grep -c '🅿 PARKED' "$BRD"); check "exactly one parked row" "$park_ct" "1"

echo "== summary counts correct (1 running-ish? no: 1 complete + 1 parked) =="
has "summary: 1 complete" "✅ 1 complete" "$BRD"
has "summary: 1 parked" "🅿 1 parked" "$BRD"

echo
if [ "$FAILED" -eq 0 ]; then echo "PASS: dispatch-board AC-3 (fully-derived, rename-tracking dashboard)"; exit 0
else echo "FAIL: dispatch-board AC-3"; exit 1; fi
