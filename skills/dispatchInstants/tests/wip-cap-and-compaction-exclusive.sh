#!/usr/bin/env bash
#
# Hermetic tests for TWO INDEPENDENT operator rules (2026-07-29). They are tested together in one
# suite precisely because the danger is conflating them:
#
#   RULE 1 (WIP cap)      at most ONE instant in ACTIVE DEV. A worker that has DECLARED
#                         `Phase: AWAITING-CI` is excluded — it consumes no dev attention.
#   RULE 2 (exclusivity)  while a COMPACTION instant is inflight, NOTHING dispatches at all.
#
# Rule 2 is NOT a tightening of rule 1 and must not live inside the cap counter. The load-bearing
# case in this file is `== independence ==`: a compaction that is itself AWAITING-CI contributes
# ZERO to the cap count and must STILL block every dispatch. An implementation that folds rule 2
# into the cap counter fails one of those two assertions no matter which way it folds them.
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

# =============================================================================
echo "== W2-2: an inflight COMPACTION refuses every dispatch =="
# A compaction folds finished branches into one stacked chain and its end state becomes the base
# everything later builds on. Anything dispatched alongside it is based on the pre-compaction tree,
# so the compaction cannot fold it and it becomes the NEXT compaction's debt.
mkdir -p "$COMPACT_IN"
before=$(nrecords)
out=$(todo "Blocked While Compacting"); rc=$?
chk "dispatch-todo refuses while a compaction is inflight (rc=4)" 4 $rc
echo "$out" | grep -q "main-07290100-inflight-compact-foldTheStack" \
  && ok "todo NAMES the blocking compaction instant" \
  || bad "refused without naming the blocker — an alarm nobody can act on: $out"
echo "$out" | grep -qi "compaction" && ok "todo says WHY it refused" || bad "no reason given: $out"
[ "$(nrecords)" = "$before" ] && ok "the refused dispatch wrote no board record" || bad "refusal left a record behind"
[ -z "$(ls -d "$EFFORT"/*-inflight-append-blockedWhileCompacting* 2>/dev/null)" ] \
  && ok "the refused dispatch forked no child instant" || bad "refusal left a half-built child instant"

# `todo` and `launch` are TWO entry points to the same act. Guarding only the one you thought of
# leaves `pdispatch todo --no-launch` + `pdispatch launch` as a complete bypass.
rec pending "$WORKER" dt-pending
: > "$STUB_LOG"
out=$(STUB_ALIVE=0 bash "$S/dispatch-launch.sh" pending 2>&1); rc=$?
chk "dispatch-launch refuses while a compaction is inflight (rc=4)" 4 $rc
echo "$out" | grep -q "main-07290100-inflight-compact-foldTheStack" \
  && ok "launch NAMES the blocking compaction instant" || bad "launch refused anonymously: $out"
grep -q "new-session" "$STUB_LOG" && bad "launch still created the tmux session it refused to start" \
  || ok "the refused launch started no session"

# The COMPACTION'S OWN worker must still be launchable. `pdispatch todo --no-launch` + review +
# `pdispatch launch` is the mandated dispatch sequence, so a guard that lets a compaction block
# ITSELF is a deadlock whose only exit is the override — i.e. a guard everybody learns to bypass.
rec theCompactionsOwnWorker "$COMPACT_IN" dt-theCompactionsOwnWorker
: > "$STUB_LOG"
STUB_ALIVE=0 bash "$S/dispatch-launch.sh" theCompactionsOwnWorker >/dev/null 2>&1
chk "the compaction's OWN worker can still be launched (no self-deadlock)" 0 $?
rm -f "$BOARD_DIR/records/theCompactionsOwnWorker.json"

echo "== W2-2: the alarm CLEARS when the compaction completes =="
# A guard that cannot be cleared trains everyone to bypass it. The state transition is the RENAME.
mv "$COMPACT_IN" "$COMPACT_DONE"
out=$(todo "Allowed After Compaction"); rc=$?
chk "dispatch-todo dispatches again once the compaction is -complete- (rc=0)" 0 $rc
: > "$STUB_LOG"
STUB_ALIVE=0 bash "$S/dispatch-launch.sh" pending >/dev/null 2>&1; rc=$?
chk "dispatch-launch launches again once the compaction is -complete- (rc=0)" 0 $rc
grep -q "new-session" "$STUB_LOG" && ok "the allowed launch actually created the session" || bad "did not launch"

echo "== W2-2: a compaction in ANOTHER effort must not block this one =="
# The board is machine-global and several efforts run at once. Blocking on a foreign effort's
# compaction is the false alarm that gets the whole guard switched off.
other="$tmp/other-effort"; mkdir -p "$other/main-07290300-inflight-compact-someoneElsesFold"
out=$(todo "Unaffected By Foreign Compaction"); rc=$?
chk "a foreign effort's compaction does not block (rc=0)" 0 $rc

# =============================================================================
echo "== independence: the two rules are NOT one rule =="
# THE load-bearing case. A compaction that has declared `Phase: AWAITING-CI` consumes no dev
# attention, so rule 1 must count it as ZERO. Rule 2 must block anyway — its cost is not attention,
# it is that a sibling dispatch bases on the pre-compaction tree and becomes unfoldable debt.
#
# Both assertions run against ONE fixture, so neither folding direction can pass:
#   · rule 2 implemented inside the cap counter  -> the compaction counts -> (a) fails
#   · dispatch gated on "am I at the cap?"       -> AWAITING-CI means not at cap -> (b) fails
mv "$COMPACT_DONE" "$COMPACT_IN"
printf '# H\n\nPhase: AWAITING-CI\n\n## Next\nCI is running on the stacked chain\n' > "$COMPACT_IN/HANDOFF.md"
only_record theCompaction "$COMPACT_IN" dt-theCompaction
out=$(STUB_ALIVE=1 bash "$S/dispatch-health.sh" --base "$BASEI" --active-dev 2>&1)
echo "$out" | grep -qE '^0 (worker|instant)' \
  && ok "(a) an AWAITING-CI compaction contributes ZERO to the active-dev count" \
  || bad "(a) the cap counter is doing rule 2's job — it counted the CI-waiting compaction: $out"
echo "$out" | grep -q "room for 1 more" \
  && ok "(a) …so the cap counter alone would say 'go ahead and dispatch'" \
  || bad "(a) cap counter did not report room: $out"
out=$(todo "Still Blocked By A CI Waiting Compaction"); rc=$?
chk "(b) …yet the compaction STILL blocks the dispatch (rc=4)" 4 $rc
echo "$out" | grep -q "main-07290100-inflight-compact-foldTheStack" \
  && ok "(b) and still names it" || bad "(b) blocked without naming the blocker: $out"

# =============================================================================
echo "== W2-2: the override exists, and costs you a stated reason =="
# Mirrors how WIP_CAP is documented: overridable, but only with a reason recorded in DECISIONS.
# NOTE: the env assignment is confined to this command substitution's subshell, so it cannot leak
# into the later cases (a leaked override would silently disable the guard for the rest of the run).
out=$(ALLOW_DISPATCH_DURING_COMPACTION="hotfix: the compaction is itself blocked on this" \
        todo "Overridden By Env"); rc=$?
chk "the env override lets a justified dispatch through (rc=0)" 0 $rc
echo "$out" | grep -q "hotfix: the compaction is itself blocked on this" \
  && ok "the override echoes the reason back" || bad "override swallowed the reason: $out"
echo "$out" | grep -qi "DECISIONS" && ok "tells the operator where the reason must be recorded" \
  || bad "override does not say to record the reason: $out"

out=$(todo "Overridden By Flag" --allow-during-compaction "operator directive 2026-07-29"); rc=$?
chk "the --allow-during-compaction flag works too (rc=0)" 0 $rc
echo "$out" | grep -q "operator directive 2026-07-29" && ok "the flag echoes its reason" || bad "flag reason lost: $out"

# An empty reason must be rejected as BAD INPUT (2), NOT merely fall through to the ordinary policy
# refusal (4). Asserting only "non-zero" here cannot tell the two apart, so it would pass even with
# the validation deleted — the guard's own refusal masks it. (Found by mutation M-12; the earlier
# version of this case survived that mutation.)
out=$(todo "Override With No Reason" --allow-during-compaction ""); rc=$?
chk "an override with an EMPTY reason is rejected as bad input (rc=2), not treated as 'no override'" 2 $rc
echo "$out" | grep -qiE "requires a reason" && ok "says, in those words, that a reason is required" \
  || bad "refusal does not state that the flag needs a reason: $out"

if [ $fail = 0 ]; then echo "PASS"; else echo "FAIL"; fi
exit $fail
