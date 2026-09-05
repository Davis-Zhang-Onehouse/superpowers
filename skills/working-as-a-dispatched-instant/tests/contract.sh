#!/usr/bin/env bash
# The worker's contract, asserted against the fleet surface rather than against prose.
#
# Each case is a promise this skill makes to a dispatched instant. If `fleet` stops refusing one of them, this
# suite fails and the skill is wrong — which is the point: a skill's promises and the tool's behaviour must not
# be able to drift apart quietly. V2 checks that a cited case passed; this checks the behaviour is still there
# on THIS machine, today.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
FLEET="$REPO/bin/fleet"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export FLEET_HOME="$TMP/home" FLEET_INSTANTS="$TMP/instants"
mkdir -p "$FLEET_HOME" "$FLEET_INSTANTS"

fails=0
note() { printf '  %s\n' "$*"; }

expect() {                # expect <label> <want-rc> <cmd...>
  local label="$1" want="$2"; shift 2
  "$@" > "$TMP/$label.out" 2>&1
  local rc=$?
  if [ "$rc" != "$want" ]; then
    note "$label: exit $rc, wanted $want"
    sed 's/^/        /' "$TMP/$label.out" | tail -3
    fails=1
  fi
}

W="$("$FLEET" init --base 00000000 --name contractWorker --porcelain | awk -F'\t' '$1=="path"{print $2}')"
if [ -z "$W" ] || [ ! -d "$W" ]; then
  echo "could not create the instant; nothing below would be a verdict"; echo "FAIL"; exit 1
fi
"$FLEET" milestone --instant "$W" --id c1 --title "the work" >/dev/null 2>&1

# CLAIM: a worker can orient itself with ONE read-only command.
expect brief 0 "$FLEET" brief --instant "$W" --porcelain
# ...and that command must tell it where a report would land, or the skill's first instruction is hollow.
if ! "$FLEET" brief --instant "$W" --porcelain | grep -q '^destination'; then
  note "brief-destination: brief emitted no destination row, so a worker cannot see where its report goes"
  fails=1
fi

# CLAIM: evidence is mandatory — a proposal without it is a claim, not a report.
expect no-evidence 2 "$FLEET" propose --instant "$W" --milestone c1 --status running

# CLAIM: a worker cannot bring a milestone into existence by proposing about it.
expect invented-milestone 2 "$FLEET" propose --instant "$W" --milestone neverAdded \
                            --status "done" --evidence evidence/INDEX.md

# CLAIM: completing with no review round is UNDECIDABLE, not "not ready". The distinction matters: nothing has
# been judged, and a gate that says "not ready" invites the reader to argue with a verdict it never reached.
"$FLEET" complete --instant "$W" > "$TMP/no-review.out" 2>&1
if ! grep -qi 'undecidable' "$TMP/no-review.out"; then
  note "no-review: complete did not refuse as UNDECIDABLE"
  sed 's/^/        /' "$TMP/no-review.out" | tail -3
  fails=1
fi

# CLAIM: park records a question, and an empty park is not a park.
expect empty-park 2 "$FLEET" park --instant "$W" --question ""
expect real-park  0 "$FLEET" park --instant "$W" --question "which baseline is the ruler?"
expect unpark     0 "$FLEET" unpark --instant "$W"

# CLAIM: base-check is answerable for an instant with no recorded lineage — it must say "nothing to check"
# rather than fail, because that is the state of most dispatches.
TODO="$("$FLEET" resume --instant "$W" --porcelain 2>/dev/null | awk -F'\t' '$1=="todo_id"{print $2}')"
if [ -n "$TODO" ]; then
  expect base-check 0 "$FLEET" base-check --id "$TODO" --porcelain
else
  note "base-check: could not adopt the instant to get a todo id, so this claim was not exercised"
  fails=1
fi

if [ "$fails" = 0 ]; then
  echo "PASS: every contract this skill states is enforced by fleet on this machine — brief orients read-only AND names where a report would land, evidence is mandatory, an unknown milestone is refused, completing with no review round is UNDECIDABLE rather than not-ready, an empty park is refused, and base-check answers for an instant with no recorded lineage"
  exit 0
fi
echo "FAIL"
exit 1
