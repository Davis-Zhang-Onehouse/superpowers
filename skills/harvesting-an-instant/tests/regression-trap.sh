#!/usr/bin/env bash
# SI-48 — a stale proposal can regress a `done` milestone, and the readiness cascade goes with it.
#
# THIS SUITE ASSERTS A HAZARD, NOT A GUARANTEE. It passes while the hazard exists. When `apply` learns to
# refuse a regression, this suite FAILS — and that failure is the signal to update SKILL.md half two item
# 2 and mark SI-48 closed in docs/superpowers/fleet-infra-backlog.md. Do not "repair" it by loosening the
# assertion; the skill tells a coordinator to check by hand, and that instruction is only worth carrying
# while it is true.
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

# The trap: a stale proposal from an earlier round, applied without reading it.
"$FLEET" propose --instant "$I" --milestone m1 --status awaiting-ci \
  --evidence "$I/evidence/p.txt" --note "stale, from an earlier round" >/dev/null 2>&1
"$FLEET" apply --instant "$I" --milestone m1 >/dev/null 2>&1

after="$(status_of m1)"
if [ "$after" = "done" ]; then
  echo "SI-48 IS FIXED: apply held m1 at done rather than regressing it."
  echo "  -> update skills/harvesting-an-instant/SKILL.md half two item 2,"
  echo "  -> mark SI-48 closed in docs/superpowers/fleet-infra-backlog.md, then retire this suite."
  echo "FAIL"
  exit 1
fi

reblocked="$("$FLEET" roadmap --instant "$I" --porcelain 2>/dev/null | awk -F'\t' '$1=="not-ready" && $2=="m2"' | wc -l)"
if [ "$reblocked" -lt 1 ]; then
  echo "FAIL: m1 regressed done -> $after but m2 did NOT go back to not-ready."
  echo "      The skill's cascade claim is wrong and must be corrected."
  exit 1
fi

echo "PASS: the hazard is live — m1 regressed done -> $after at exit 0, and m2 went back to not-ready"
exit 0
