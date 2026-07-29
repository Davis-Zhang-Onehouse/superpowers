#!/usr/bin/env bash
#
# Hermetic tests for TWO INDEPENDENT operator rules (2026-07-29). They are tested together in one
# suite precisely because the danger is conflating them:
#
#   RULE 1 (WIP cap)      at most ONE instant in ACTIVE DEV. A worker that has DECLARED
#                         `Phase: AWAITING-CI` is excluded — it consumes no dev attention.
#   RULE 2 (exclusivity)  while a COMPACTION instant is inflight, NOTHING dispatches at all.
#
# Rule 2 lands in the NEXT commit, together with the code that enforces it; this file already sets
# up the shared fixture (an effort dir with a compaction sibling) that its cases will need.
#
# Hermetic: stub tmux, isolated BOARD_DIR + POOL_DIR, no network, no real sessions.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$here/.."
fail=0
ok(){ echo "  ok   - $1"; }
bad(){ echo "  FAIL - $1"; fail=1; }
chk(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (expected rc=$2, got rc=$3)"; fi; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export BOARD_DIR="$tmp/board"; mkdir -p "$BOARD_DIR/records"
export POOL_DIR="$tmp/pool"
export LAUNCH_WAIT=0
mkdir -p "$tmp/bin"

# ---- stub tmux (same shape as fleet-tools-test.sh) --------------------------
cat > "$tmp/bin/tmux" <<'STUB'
#!/usr/bin/env bash
log="${STUB_LOG:-/dev/null}"; echo "tmux $*" >> "$log"
case "$1" in
  has-session) [ "${STUB_ALIVE:-1}" = "1" ] && exit 0 || exit 1 ;;
  capture-pane) cat "${STUB_PANE:-/dev/null}"; exit 0 ;;
  send-keys)    echo "${*:3}" >> "${STUB_PANE:-/dev/null}"; exit 0 ;;
  new-session)  echo "created" >> "$log"; exit 0 ;;
  *) exit 0 ;;
esac
STUB
chmod +x "$tmp/bin/tmux"
export TMUX_BIN="$tmp/bin/tmux"
export STUB_LOG="$tmp/tmux.log"
export STUB_PANE="$tmp/pane.txt"; printf 'working on the thing\n' > "$STUB_PANE"

# ---- the effort: an instants DIRECTORY holding sibling instants -------------
# This mirrors the real layout exactly: `dirname <base-instant>` IS the effort's instants dir, which
# is how dispatch-todo already resolves where to fork a child. Rule 2's detection must use the SAME
# convention — a second way of naming "the effort" is how the two halves of a check drift apart.
EFFORT="$tmp/effort"
BASEI="$EFFORT/main-07290000-inflight-append-theBase"
mkdir -p "$BASEI"; : > "$BASEI/HANDOFF.md"; : > "$BASEI/CHARTER.md"
COMPACT_IN="$EFFORT/main-07290100-inflight-compact-foldTheStack"
COMPACT_DONE="$EFFORT/main-07290100-complete-compact-foldTheStack"
WORKER="$EFFORT/07290000-07290200-inflight-append-alpha"
mkdir -p "$WORKER"

# ---- dispatch-todo prerequisites (mirrors hygiene-test.sh) ------------------
mkdir -p "$tmp/golden" "$tmp/prof"
printf 'CHARTER for {{TITLE}}\n{{BRIEF}}\n' > "$tmp/prof/charter.md"
printf 'seed for {{TITLE}}\n'               > "$tmp/prof/seed.txt"
printf 'do the thing\n'                     > "$tmp/brief.md"
for n in 1 2 3 4 5; do mkdir -p "$tmp/ws$n"; bash "$S/wspool.sh" add "$tmp/ws$n" >/dev/null 2>&1; done

todo(){ # todo <title> [extra args...] -> runs a dispatch that needs no golden clone
  local title="$1"; shift
  bash "$S/dispatch-todo.sh" --base "$BASEI" --profile "$tmp/prof" --title "$title" \
       --brief "$tmp/brief.md" --golden "$tmp/golden" --no-launch --no-duplicate "$@" 2>&1
}
nrecords(){ ls -1 "$BOARD_DIR/records"/*.json 2>/dev/null | wc -l; }
rec(){ # rec <id> <child-instant-path> [tmux-name]
  cat > "$BOARD_DIR/records/$1.json" <<EOF
{ "todo_id": "$1", "title": "T $1", "child_instant": "$2", "ws": "$tmp/ws1",
  "slot": "ws1", "tmux": "${3:-dt-$1}", "base_instant": "$BASEI",
  "seed_file": "$tmp/seed.txt", "dispatched_at": "2026-01-01T00:00:00Z",
  "launched_at": "2026-01-01T00:01:00Z" }
EOF
}
only_record(){ # wipe the board so a cap COUNT assertion is about exactly the fixture it names
  rm -f "$BOARD_DIR"/records/*.json; rm -rf "$BOARD_DIR/health"
  printf 'working on the thing\n' > "$STUB_PANE"; rec "$@"
}
echo "do the work" > "$tmp/seed.txt"

# =============================================================================
echo "== W2-1: the default WIP cap is ONE =="
# The value has been three different correct numbers in three contexts, so the DEFAULT is the thing
# under test: a coordinator that sets nothing must get 1. (WIP_CAP=<n> stays an override, below.)
only_record alpha "$WORKER"
printf '# H\n\n## Next\nstill coding\n' > "$WORKER/HANDOFF.md"
out=$(STUB_ALIVE=1 bash "$S/dispatch-health.sh" --base "$BASEI" --active-dev 2>&1)
echo "$out" | grep -qE '\(cap 1\)' && ok "default WIP cap is 1" || bad "default cap is not 1: $out"
echo "$out" | grep -qE '^1 (worker|instant)' && ok "counts the one working worker" || bad "count wrong: $out"
echo "$out" | grep -qi "at or over the cap" \
  && ok "ONE active worker is already AT the cap — do not dispatch" \
  || bad "one active worker did not read as at-cap: $out"
echo "$out" | grep -qi "room for" && bad "offered room while at the cap" || ok "offers no room while at the cap"

# The env override is the documented escape hatch (with a reason in DECISIONS) and must keep working.
out=$(WIP_CAP=3 STUB_ALIVE=1 bash "$S/dispatch-health.sh" --base "$BASEI" --active-dev 2>&1)
echo "$out" | grep -qE '\(cap 3\)' && ok "WIP_CAP=3 still overrides the default" || bad "override lost: $out"
echo "$out" | grep -q "room for 2 more" && ok "override arithmetic is right (3-1=2)" || bad "bad arithmetic: $out"

echo "== W2-1: a DECLARED CI-waiter still does not count against the cap =="
# Unchanged behaviour, re-asserted at the new cap: at cap 3 an off-by-one here was invisible, at
# cap 1 it is the difference between "dispatch" and "do not dispatch".
printf '# H\n\nPhase: AWAITING-CI\n\n## Next\nwaiting on run 123\n' > "$WORKER/HANDOFF.md"
rm -rf "$BOARD_DIR/health"
out=$(STUB_ALIVE=1 bash "$S/dispatch-health.sh" --base "$BASEI" --active-dev 2>&1)
echo "$out" | grep -qE '^0 (worker|instant)' && ok "a CI-waiter is excluded from the count" || bad "counted a CI-waiter: $out"
echo "$out" | grep -q "room for 1 more" && ok "excluding it frees the single slot" || bad "no room reported: $out"

if [ $fail = 0 ]; then echo "PASS"; else echo "FAIL"; fi
exit $fail
