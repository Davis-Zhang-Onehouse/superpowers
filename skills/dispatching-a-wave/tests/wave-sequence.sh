#!/usr/bin/env bash
# V3 — the wave sequence this skill documents must actually RUN.
#
# The lint proves every verb named exists. It cannot prove the SEQUENCE is coherent: a skill can name only
# real verbs and still order them impossibly. This suite performs the routine's derivations in order,
# against a scratch store.
#
# On a PRIVATE tmux socket, and `dispatch` is --dry-run: a real dispatch launches a claude session, which
# this suite has no business doing. What is under test is the ORDER and the derivations.
#
# Step 1 is a column read since SI-47 was closed (`B04`): this suite used to carry an INVERTED assertion
# pinning SI-47 open, which fired when the fix landed. It now asserts the documented recipe — ready rows,
# with the claim in the owner column — returns exactly the dispatchable set.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
FLEET="$REPO/bin/fleet"
PROFILE="$REPO/skills/using-fleet/profiles/worker"
SOCK="wave-seq-$$"
TMP="$(mktemp -d)"
trap 'tmux -L "$SOCK" kill-server 2>/dev/null; rm -rf "$TMP"' EXIT

export FLEET_HOME="$TMP/home" FLEET_INSTANTS="$TMP/instants" FLEET_TMUX_SOCKET="$SOCK"
export FLEET_CLAUDE_BIN=/bin/true CLAUDE_OWNERS_MAP="$TMP/owners.tsv"
printf '%s\t%s\n' "$TMP" test > "$CLAUDE_OWNERS_MAP"
mkdir -p "$TMP/.claude"
mkdir -p "$FLEET_HOME" "$FLEET_INSTANTS" "$TMP/slotA" "$TMP/slotB"

fails=0
note() { printf '  %s\n' "$*"; }
check() { if [ "$2" = "$3" ]; then note "ok   $1"; else note "FAIL $1 (want $2, got $3)"; fails=$((fails+1)); fi; }

I="$("$FLEET" init --name waveCoord --base 00000000 --optype append --porcelain 2>/dev/null \
      | awk -F'\t' '$1=="path"{print $2}')"
[ -n "$I" ] || { echo "FAIL: init produced no path row"; exit 1; }
"$FLEET" enroll --slot "$TMP/slotA" >/dev/null 2>&1
"$FLEET" enroll --slot "$TMP/slotB" >/dev/null 2>&1

"$FLEET" milestone --instant "$I" --id m1 --title "wave member one" --status ready >/dev/null 2>&1
"$FLEET" milestone --instant "$I" --id m2 --title "wave member two" --status ready >/dev/null 2>&1
"$FLEET" milestone --instant "$I" --id m3 --title "needs m1 first" --dep m1        >/dev/null 2>&1

# Routine step 1. Readiness is DERIVED: m3 is not ready because its dep has not landed.
blocked="$("$FLEET" roadmap --instant "$I" --porcelain 2>/dev/null | awk -F'\t' '$1=="not-ready" && $2=="m3"' | wc -l)"
check "derived readiness names m3's unlanded dep" 1 "$blocked"

# Routine step 1, the recipe SKILL.md prints: `ready` rows with an empty owner ($8), named with their title ($7).
dispatchable="$("$FLEET" roadmap --instant "$I" --porcelain 2>/dev/null \
                | awk -F'\t' '$1=="ready" && $8==""{print $2 "=" $7}' | sort | tr '\n' ' ')"
check "the ready rows name exactly the dispatchable set, with titles" \
      "m1=wave member one m2=wave member two " "$dispatchable"

# Routine step 3. The cap comes from the guard, not from a formula.
"$FLEET" dispatch --profile "$PROFILE" --title waveOne --base 00000000 --optype append \
  --from "$I" --milestone m1 --slot slotA --cap 1 --dry-run --porcelain >"$TMP/dry.txt" 2>&1
check "dry-run dispatch evaluates every gate" 0 $?
grep -q 'guard.wip-cap' "$TMP/dry.txt"; check "the wip-cap guard reports its count and population" 0 $?
grep -q '^dry-run' "$TMP/dry.txt"; check "dry-run states that nothing was claimed or created" 0 $?

# This is the measurement behind the skill's "do not carry a formula" rule: an init-created coordinator
# has no record, so it does NOT count against the cap, and the formula would predict otherwise.
grep -qE 'guard\.wip-cap.*allow: 0 of 1' "$TMP/dry.txt"
check "an init-created coordinator does not count against the cap" 0 $?

# The zero-delta contract the routine depends on: a dry run leaves no child instant behind.
count="$(find "$FLEET_INSTANTS" -maxdepth 1 -mindepth 1 -type d | wc -l)"
check "dry-run created no child instant (only the coordinator remains)" 1 "$count"

if [ "$fails" = 0 ]; then echo "PASS: the wave sequence runs in the documented order"; exit 0; fi
echo "FAIL: $fails check(s) failed"; exit 1
