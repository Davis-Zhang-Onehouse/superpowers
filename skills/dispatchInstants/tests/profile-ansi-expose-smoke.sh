#!/usr/bin/env bash
#
# Regression proof for the `ansi-expose` dispatch profile. Hermetic: temp POOL_DIR/
# BOARD_DIR, a fake base instant, and stubbed tmux/claude/duplicate-workspace on PATH.
# Never touches the real ws pool, ~/wsN, or a real Claude session.
#
# Guards the exact surprise this profile was created to prevent: an EXPOSURE effort must
# NOT be seeded with the FIX pipeline, and the self-contained charter must not duplicate
# the (short) brief.
#
# Verifies the child CHARTER rendered from `--profile ansi-expose`:
#   * carries the exposure framing (EXPOSURE / COMPLETENESS, masking audit, fallback census)
#   * carries NO fix-pipeline language (LOCAL REPRO first / AC-3 FIX / red->green)
#   * carries the brief exactly once (no duplication) and the evidence pointer
#   * and that the launched seed is the exposure seed, not the fix seed
#
# Exit 0 + PASS = all held.
#
set -uo pipefail

SKILL="$(cd "$(dirname "$0")/.." && pwd)"
DISPATCH="$SKILL/dispatch-todo.sh"
[ -f "$DISPATCH" ] || { echo "FAIL: dispatch-todo.sh missing"; exit 1; }
[ -d "$SKILL/profiles/ansi-expose" ] || { echo "FAIL: profiles/ansi-expose missing"; exit 1; }
chmod +x "$SKILL"/wspool.sh "$DISPATCH"

FAILED=0
has()   { if grep -qF -- "$2" "$1"; then echo "  ok: charter has [$2]"; else echo "  XX: charter MISSING [$2]"; FAILED=1; fi; }
hasnt() { if grep -qF -- "$2" "$1"; then echo "  XX: charter WRONGLY has fix-language [$2]"; FAILED=1; else echo "  ok: charter free of [$2]"; fi; }

ROOT="$(mktemp -d)"; trap 'rm -rf "$ROOT"' EXIT
BIN="$ROOT/bin"; mkdir -p "$BIN"; export PATH="$BIN:$PATH"
export TMUX_LOG="$ROOT/tmux.log" DUP_LOG="$ROOT/dup.log" ROOT
cat > "$BIN/tmux" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$TMUX_LOG"
case "${1:-}" in has-session) exit 0;; new-session) exit 0;; send-keys) exit 0;; *) exit 0;; esac
STUB
cat > "$BIN/claude" <<'STUB'
#!/usr/bin/env bash
echo "claude $*" >> "$ROOT/claude.log"; exit 0
STUB
cat > "$BIN/duplicate-workspace.sh" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$DUP_LOG"; exit 0
STUB
chmod +x "$BIN"/tmux "$BIN"/claude "$BIN"/duplicate-workspace.sh
export DUPLICATE_WS_SH="$BIN/duplicate-workspace.sh" WSPOOL_SH="$SKILL/wspool.sh"

export POOL_DIR="$ROOT/pool" BOARD_DIR="$ROOT/board"
BASEDIR="$ROOT/tasks/effort"; BASE="$BASEDIR/main-07152335-complete-append-someBase"; mkdir -p "$BASE"
printf '# base HANDOFF\n' > "$BASE/HANDOFF.md"; printf '# base CHARTER\n' > "$BASE/CHARTER.md"
GOLDEN="$ROOT/wsG"; mkdir -p "$GOLDEN"
SLOT="$ROOT/wsA"; mkdir -p "$SLOT"; "$SKILL"/wspool.sh add "$SLOT" >/dev/null

BRIEF="$ROOT/brief.md"
printf 'Prove branch-1.7 (ARM) exposes ALL ANSI gaps; resolve the SENTINEL_NEEDS_RCA tail.\n' > "$BRIEF"

echo "== dispatch with --profile ansi-expose =="
out="$("$DISPATCH" --base "$BASE" --title "expose all ansi gaps" --brief "$BRIEF" \
        --profile ansi-expose --golden "$GOLDEN" --evidence "baseline/CATALOG.md" 2>&1)" \
  || { echo "$out"; echo "FAIL: dispatch errored"; exit 1; }
CHILD="$(printf '%s\n' "$out" | sed -n 's/.*instant   : //p' | head -1)"
CH="$CHILD/CHARTER.md"
[ -f "$CH" ] || { echo "FAIL: child CHARTER not rendered"; exit 1; }

echo "-- exposure framing present --"
has   "$CH" "EXPOSURE / COMPLETENESS"
has   "$CH" "AC-2 — Masking audit"
has   "$CH" "AC-3 — Fallback census"
has   "$CH" "0 hidden ANSI gaps"
has   "$CH" "do not fix gaps"

echo "-- fix-pipeline language absent --"
hasnt "$CH" "LOCAL REPRO first"
hasnt "$CH" "AC-3 FIX + local validation"
hasnt "$CH" "red→green"
hasnt "$CH" "RCA via systematic-debugging (RCA-FIRST"

echo "-- brief carried exactly once (no duplication) + evidence present --"
n=$(grep -cF "SENTINEL_NEEDS_RCA" "$CH")
if [ "$n" = "1" ]; then echo "  ok: brief sentinel appears exactly once"; else echo "  XX: brief sentinel appears $n times (want 1)"; FAILED=1; fi
has "$CH" "baseline/CATALOG.md"

echo "-- launched seed is the exposure seed, not the fix seed --"
# the seed is %q-escaped inside the send-keys line, so match an escape-safe token
if grep -qF "EXPOSURE" "$TMUX_LOG" && grep -qF "send-keys" "$TMUX_LOG"; then
  echo "  ok: exposure seed sent to the session"
else echo "  XX: exposure seed NOT sent (send-keys seed wrong)"; FAILED=1; fi

echo
if [ "$FAILED" = 0 ]; then echo "PASS: profile-ansi-expose-smoke"; exit 0
else echo "FAIL: profile-ansi-expose-smoke"; exit 1; fi
