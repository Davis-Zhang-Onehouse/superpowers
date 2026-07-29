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
for n in $(seq 1 12); do mkdir -p "$tmp/ws$n"; bash "$S/wspool.sh" add "$tmp/ws$n" >/dev/null 2>&1; done

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
echo "== W2-2: detection is the opTYPE FIELD, not the word \"compact\" in a name =="
# D-3 rejected substring matching as the label-instead-of-the-thing error, and OI-1's open remedy
# list contains exactly that temptation: broadening the glob to *ompact* would close the gap and
# keep every other assertion green. This case is the only thing that makes that rejection durable.
# It is not hypothetical — a real live instant is named `…-inflight-append-ansiFinalCompactionAndCloseout`.
# The REAL compaction must be out of the way, or a rc=4 here would come from it and this case would
# prove nothing. Complete it for the duration, then put it back for the override cases.
mv "$COMPACT_IN" "$COMPACT_DONE"
decoy="$EFFORT/07290000-07290400-inflight-append-ansiFinalCompactionAndCloseout"
mkdir -p "$decoy"
out=$(todo "Not Blocked By A Mere Name"); rc=$?
chk "an -append- instant with 'Compaction' in its NAME does not block (rc=0)" 0 $rc
echo "$out" | grep -q "ansiFinalCompactionAndCloseout" \
  && bad "matched a compaction by NAME — that is the label, not the thing (D-3)" \
  || ok "never mentions the decoy: detection reads <opType>, not the name"
rm -rf "$decoy"
mv "$COMPACT_DONE" "$COMPACT_IN"

# The independence section wiped the board (only_record), so re-create the launch fixture.
rec pending "$WORKER" dt-pending

echo "== both entry points reject a flag passed with no value at all =="
# `shift 2` on a trailing flag shifts nothing and returns 1. Under `set -uo pipefail` (launch) the
# arg loop then spins FOREVER; under `set -euo pipefail` (todo) the script dies with a bare rc=1 and
# no message. "The operator forgot the reason" is the likeliest way an override is ever mistyped,
# so it has to produce a diagnostic, not a hang. Guarded with `timeout` so a regression fails the
# suite in 5s instead of wedging CI.
out=$(timeout 5 bash "$S/dispatch-todo.sh" --base "$BASEI" --profile "$tmp/prof" --title T \
        --brief "$tmp/brief.md" --golden "$tmp/golden" --no-launch --no-duplicate \
        --allow-during-compaction 2>&1); rc=$?
chk "todo: trailing --allow-during-compaction exits 2 (not a silent rc=1)" 2 $rc
echo "$out" | grep -qi "requires a value" && ok "todo: says the flag was left without a value" \
  || bad "todo: no diagnostic for the trailing flag: $out"
out=$(timeout 5 bash "$S/dispatch-launch.sh" pending --allow-during-compaction 2>&1); rc=$?
chk "launch: trailing --allow-during-compaction exits 2 (124 would mean it hung)" 2 $rc
out=$(timeout 5 bash "$S/dispatch-launch.sh" pending --seed-file 2>&1); rc=$?
chk "launch: trailing --seed-file exits 2 too (same shape, one line away)" 2 $rc

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

echo "== the override works through dispatch-launch too, not just dispatch-todo =="
# D-1's whole rationale is that a previous effort shipped four defects that were "the same fix
# applied in one place and not the adjacent one". Testing the override only through `todo` leaves
# the adjacent copy — the one where the trailing-flag hang lived — completely uncovered.
: > "$STUB_LOG"
out=$(ALLOW_DISPATCH_DURING_COMPACTION="env override on the launch side" \
        STUB_ALIVE=0 bash "$S/dispatch-launch.sh" pending 2>&1); rc=$?
chk "launch: the env override lets a justified launch through (rc=0)" 0 $rc
echo "$out" | grep -q "env override on the launch side" && ok "launch: echoes the reason" \
  || bad "launch: override reason lost: $out"
: > "$STUB_LOG"
out=$(STUB_ALIVE=0 bash "$S/dispatch-launch.sh" pending --allow-during-compaction "flag override on the launch side" 2>&1); rc=$?
chk "launch: the --allow-during-compaction flag works (rc=0)" 0 $rc
out=$(STUB_ALIVE=0 bash "$S/dispatch-launch.sh" pending --allow-during-compaction "" 2>&1); rc=$?
chk "launch: an override with an EMPTY reason is bad input (rc=2), not a policy refusal (4)" 2 $rc
echo "$out" | grep -qiE "requires a reason" && ok "launch: says a reason is required" \
  || bad "launch: unclear refusal: $out"

echo "== a SET-BUT-EMPTY env override is diagnosed, not silently ignored =="
# Falling through to the ordinary refusal would answer "set ALLOW_DISPATCH_DURING_COMPACTION" to
# someone who just set it — a remedy that sends them in a circle.
out=$(ALLOW_DISPATCH_DURING_COMPACTION="" todo "Empty Env Override"); rc=$?
chk "an empty ALLOW_DISPATCH_DURING_COMPACTION is bad input (rc=2)" 2 $rc
echo "$out" | grep -qiE "requires a reason" && ok "and says a reason is required" \
  || bad "empty env var fell through to the generic refusal: $out"

echo "== --optype: dispatch-todo can finally WRITE the field the guard READS (OI-1) =="
# The whole point of OI-1: the grammar has an <opType> field, the guard reads it, and the only tool
# that creates instants could not write it — so the guard was inert against every compaction the
# fleet actually produces. A flag that sets it is only half the fix; the case that matters is the
# END-TO-END one below, where a compaction dispatched through the normal path actually blocks.
mv "$COMPACT_IN" "$COMPACT_DONE"          # clear the hand-made blocker for this section
out=$(todo "Fold The Stack" --optype compact); rc=$?
chk "--optype compact dispatches (rc=0)" 0 $rc
made=$(ls -d "$EFFORT"/*-inflight-compact-foldTheStack 2>/dev/null | head -1)
[ -n "$made" ] && ok "the child instant carries opType 'compact'" \
  || bad "no *-inflight-compact-foldTheStack child: $(ls "$EFFORT" | tr '\n' ' ')"
# It must still be a well-formed 5-field name, or every OTHER parser of the grammar breaks on it.
case "$(basename "${made:-x}")" in
  [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-inflight-compact-foldTheStack)
     ok "…and still matches <curr>-<now>-<state>-<opType>-<name> with numeric timestamps";;
  *) bad "malformed instant name: $(basename "${made:-<none>}")";;
esac

# THE CASE THAT CLOSES OI-1: a compaction dispatched the NORMAL way now blocks the next dispatch.
# Before this change the child was born -inflight-append- and the guard never saw it.
out=$(todo "Blocked By A Normally Dispatched Compaction"); rc=$?
chk "a compaction dispatched via --optype compact BLOCKS the next dispatch (rc=4)" 4 $rc
echo "$out" | grep -q "inflight-compact-foldTheStack" \
  && ok "and names the compaction that pdispatch itself created" || bad "did not name it: $out"
rm -rf "$made"
mv "$COMPACT_DONE" "$COMPACT_IN"

echo "== --optype: the default is unchanged, and a bad value is refused =="
# Default must stay `append`: every existing caller passes no --optype, and a silent change of the
# opType for ordinary milestones would make each of them look like a compaction to the guard.
# A compaction is inflight again at this point, so the override is needed just to reach the code
# under test — the assertion below is about the child's NAME, not about the guard.
out=$(ALLOW_DISPATCH_DURING_COMPACTION="checking the default opType" todo "Ordinary Milestone"); rc=$?
chk "a dispatch with no --optype still succeeds (rc=0)" 0 $rc
[ -n "$(ls -d "$EFFORT"/*-inflight-append-ordinaryMilestone 2>/dev/null)" ] \
  && ok "…and is still born -inflight-append- (default unchanged)" \
  || bad "the default opType changed: $(ls "$EFFORT" | tr '\n' ' ')"
out=$(todo "Bad Optype" --optype banana); rc=$?
chk "an unknown --optype value is refused as bad input (rc=2)" 2 $rc
echo "$out" | grep -qiE "append|compact" && ok "names the values it accepts" || bad "unhelpful message: $out"
out=$(timeout 5 bash "$S/dispatch-todo.sh" --base "$BASEI" --profile "$tmp/prof" --title T \
        --brief "$tmp/brief.md" --golden "$tmp/golden" --no-launch --no-duplicate --optype 2>&1); rc=$?
chk "trailing --optype exits 2 (the same shape that hung the override flag)" 2 $rc

echo "== the guard is STILL ARMED at the end of the run =="
# Every override case above expects success, so a future refactor that hoisted the env assignment
# out of its command substitution would disable the guard for the whole tail of the suite and
# nothing would notice. This re-asserts the default from the same fixture, last.
out=$(todo "Guard Still Armed"); rc=$?
chk "with no override in the environment, the compaction still refuses (rc=4)" 4 $rc

if [ $fail = 0 ]; then echo "PASS"; else echo "FAIL"; fi
exit $fail
