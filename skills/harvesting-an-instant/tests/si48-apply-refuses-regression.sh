#!/usr/bin/env bash
# SI-48 — a stale proposal must NOT regress a `done` milestone (and re-block its dependents).
#
# This file was `regression-trap.sh`, a suite that ASSERTED THE HAZARD and was written to fail the day
# `apply` learned to refuse a regression, as the signal to update the skill and close SI-48. B02 taught
# `apply` that refusal (exit 2, the row stays pending, `--reopen` is the deliberate door), so the suite is
# inverted into the guarantee: the stale row is refused, m1 stays `done`, m2 stays open, and only
# `--reopen` moves m1. harvesting-an-instant section 2 and the backlog's SI-48 entry were updated with it.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
FLEET="$REPO/bin/fleet"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export FLEET_HOME="$TMP/home" FLEET_INSTANTS="$TMP/instants" FLEET_TMUX_SOCKET="regr-trap-$$"
mkdir -p "$FLEET_HOME" "$FLEET_INSTANTS"

I="$("$FLEET" init --name trapCoord --base 00000000 --optype append --porcelain 2>/dev/null \
      | awk -F'\t' '$1=="path"{print $2}')"
[ -n "$I" ] || { echo "FAIL: init produced no path row"; exit 1; }
mkdir -p "$I/evidence"; echo proof > "$I/evidence/p.txt"

status_of() { python3 -c "
import json,sys
d=json.load(open(sys.argv[1]))
print(next(m['status'] for m in d['milestones'] if m['id']==sys.argv[2]))" "$I/.fleet/roadmap.json" "$1"; }

"$FLEET" milestone --instant "$I" --id m1 --title "the landed one" --status ready >/dev/null 2>&1
"$FLEET" milestone --instant "$I" --id m2 --title "depends on m1"  --dep m1       >/dev/null 2>&1

"$FLEET" propose --instant "$I" --milestone m1 --status "done" \
  --evidence "$I/evidence/p.txt" --note "the real report" >/dev/null 2>&1
"$FLEET" apply --instant "$I" --milestone m1 >/dev/null 2>&1
[ "$(status_of m1)" = "done" ] || { echo "FAIL: setup did not land m1 (got '$(status_of m1)')"; exit 1; }

# m2's dep has landed, so m2 must now be absent from the not-ready rows.
still_blocked="$("$FLEET" roadmap --instant "$I" --porcelain 2>/dev/null | awk -F'\t' '$1=="not-ready" && $2=="m2"' | wc -l)"
[ "$still_blocked" = "0" ] || { echo "FAIL: setup — m2 did not open when m1 landed"; exit 1; }

# A stale proposal from an earlier round, applied without reading it.
"$FLEET" propose --instant "$I" --milestone m1 --status awaiting-ci \
  --evidence "$I/evidence/p.txt" --note "stale, from an earlier round" >/dev/null 2>&1
"$FLEET" apply --instant "$I" --milestone m1 >/dev/null 2>"$TMP/apply.err"; rc=$?

after="$(status_of m1)"
[ "$rc" = "2" ] || { echo "FAIL: apply of a regressing row exited $rc, want 2 (refused)"; exit 1; }
[ "$after" = "done" ] || { echo "FAIL: m1 regressed done -> $after (SI-48 is back)"; exit 1; }
grep -q "fleet withdraw" "$TMP/apply.err" || { echo "FAIL: the refusal does not name \`fleet withdraw\`"; exit 1; }
reblocked="$("$FLEET" roadmap --instant "$I" --porcelain 2>/dev/null | awk -F'\t' '$1=="not-ready" && $2=="m2"' | wc -l)"
[ "$reblocked" = "0" ] || { echo "FAIL: m2 went back to not-ready although m1 stayed done"; exit 1; }

# The deliberate door still opens.
"$FLEET" apply --instant "$I" --milestone m1 --reopen >/dev/null 2>&1
[ "$(status_of m1)" = "awaiting-ci" ] || { echo "FAIL: --reopen did not move m1 (got '$(status_of m1)')"; exit 1; }

echo "PASS: apply refused the stale row (exit 2), m1 stayed done and m2 open; --reopen moved it deliberately"
exit 0
