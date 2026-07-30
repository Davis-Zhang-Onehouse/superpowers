#!/usr/bin/env bash
# Tests for lint-skill.py — the V1/V2 checks every fleet skill runs against itself.
#
# Both directions for every rule, because a lint nobody has seen fire is decoration: each rule gets a fixture
# that SHOULD trip it and one that should not. The prose case is here because running V1 over the design spec
# produced exactly that false positive, and the marker cases are here because a forward reference to an
# unbuilt verb is a legitimate thing for a skill to contain.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LINT="$HERE/../lint-skill.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fails=0
note() { printf '  %s\n' "$*"; }

mk() { mkdir -p "$TMP/$1"; printf '%s\n' "$2" > "$TMP/$1/SKILL.md"; printf '%s' "$TMP/$1"; }

# rule, fixture-name, body, expectation(clean|finding), needle-that-must-appear-in-a-finding
run_case() {
  local rule="$1" name="$2" body="$3" want="$4" needle="${5:-}"
  local d out rc
  d="$(mk "$name" "$body")"
  out="$(python3 "$LINT" "$d" 2>&1)"; rc=$?
  if [ "$want" = clean ]; then
    if [ "$rc" != 0 ]; then note "FAIL $rule: expected clean, got findings:"; printf '%s\n' "$out" | sed 's/^/      /'; fails=1; fi
  else
    if [ "$rc" = 0 ]; then note "FAIL $rule: expected a finding, got a clean pass"; fails=1
    elif [ -n "$needle" ] && ! printf '%s' "$out" | grep -qF "$needle"; then
      note "FAIL $rule: finding did not mention '$needle':"; printf '%s\n' "$out" | sed 's/^/      /'; fails=1
    fi
  fi
}

run_case V1-detects badverb \
  'Run `fleet nosuchverb --instant .` to begin.' finding 'nosuchverb'
# Prose that names the tool WITHOUT claiming a refusal, so this case isolates V1 from V2. The first version
# said "fleet refuses it" and V2 correctly fired on an uncited claim — the tool was right and the fixture was
# testing two rules at once.
run_case V1-ignores-prose proseonly \
  'The point is that fleet state is authoritative. See fleet/src/fleet and fleet.cli for the code.' clean
run_case V1-real-verb goodverb \
  'Run `fleet roadmap --instant .` to see readiness.' clean
# A directory listing inside a fence is ordinary skill content, and `bin/fleet   this launcher` was read as
# the verb `this` before the lookbehind existed. Found by running this lint over the first real skill.
run_case V1-path-not-command pathlisting \
  'Layout:
```
fleet/src/fleet/      the package
bin/fleet             this launcher
```
And `<instant>/.fleet/roadmap.json` holds the registry.' clean
run_case V1-marker markedverb \
  'Run `fleet notbuiltyet --instant .` first.
<!-- v1-proposed: notbuiltyet -->' clean
run_case V1-stale-marker stalemarker \
  'Run `fleet roadmap --instant .` first.
<!-- v1-proposed: roadmap -->' finding 'stale promise'
run_case V2-detects uncited \
  'Note that `fleet propose` refuses an empty evidence list.' finding 'cites no case'
run_case V2-clears cited \
  'Note that `fleet propose` refuses an empty evidence list.
<!-- v2-cite: empty-evidence H4 -->' clean
run_case V2-fake-case fakecite \
  'Note that `fleet propose` refuses an empty evidence list.
<!-- v2-cite: empty-evidence NOSUCHCASE -->' finding 'NOSUCHCASE'

if [ "$fails" = 0 ]; then
  echo "PASS: lint-skill.py fires on an unknown verb, an uncited refusal claim, a stale proposed-verb marker and a citation to a case that did not pass — and stays quiet on prose, a real verb, a marked forward reference and a properly cited claim"
  exit 0
fi
echo "FAIL"
exit 1
