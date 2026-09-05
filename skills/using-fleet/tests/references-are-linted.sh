#!/usr/bin/env bash
# V1 and V2 must cover every markdown file a skill SHIPS, not only SKILL.md.
#
# The gap this closes: `lint-skill.py` read `SKILL.md` and nothing else, so a `references/` page could name a
# fleet verb that does not exist and the skill still linted clean. References are where the worked examples
# live — exactly the prose a reader copies commands out of — so an unregistered verb there is likelier to be
# run than one in the overview, not less.
#
# Written RED first: against the SKILL.md-only lint this suite failed, because a reference naming
# `fleet <verb-that-does-not-exist>` produced no finding at all.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LINT="$HERE/../tools/lint-skill.py"
FIX="$(mktemp -d)"
trap 'rm -rf "$FIX"' EXIT

fails=0
check() { # name, expected-rc, actual-rc, output
  if [ "$2" = "$3" ]; then
    echo "  [PASS] $1"
  else
    echo "  [FAIL] $1 (wanted rc=$2, got rc=$3)"
    printf '%s\n' "$4" | sed 's/^/      /'
    fails=$((fails + 1))
  fi
}

mkdir -p "$FIX/skill/references"
printf -- '---\nname: fixture\ndescription: fixture\n---\n\n# Fixture\n\nNothing to see.\n' >"$FIX/skill/SKILL.md"

# 1. A bogus verb in a reference must be caught.
printf '# Ref\n\nRun `fleet zznotaverb --instant .` to do the thing.\n' >"$FIX/skill/references/worked.md"
out="$(python3 "$LINT" "$FIX/skill" 2>&1)"
check "an unregistered fleet verb in references/ is a finding" 1 "$?" "$out"
case "$out" in
  *zznotaverb*) echo "  [PASS] the finding names the offending verb" ;;
  *) echo "  [FAIL] the finding does not name zznotaverb"; fails=$((fails + 1)) ;;
esac
case "$out" in
  *references/worked.md*) echo "  [PASS] the finding names the file it came from" ;;
  *) echo "  [FAIL] the finding does not name references/worked.md"; fails=$((fails + 1)) ;;
esac

# 2. The v1-proposed escape hatch must work in a reference too.
printf '# Ref\n\nRun `fleet zznotaverb --instant .`\n\n<!-- v1-proposed: zznotaverb -->\n' >"$FIX/skill/references/worked.md"
out="$(python3 "$LINT" "$FIX/skill" 2>&1)"
check "a marked <!-- v1-proposed --> verb in references/ is accepted" 0 "$?" "$out"

# 3. A refusal claim in a reference, with the citation living in SKILL.md, is satisfied:
#    references are part of the skill, not separate documents that must each re-cite.
printf '# Ref\n\n`fleet close` refuses a pane holding unsubmitted input.\n' >"$FIX/skill/references/worked.md"
printf -- '---\nname: fixture\ndescription: fixture\n---\n\n# Fixture\n\n<!-- v2-cite: close-refuses-queued-pane J8 -->\n' >"$FIX/skill/SKILL.md"
out="$(python3 "$LINT" "$FIX/skill" 2>&1)"
check "a citation in SKILL.md covers a refusal claim made in references/" 0 "$?" "$out"

# 4. ...but an UNCITED refusal claim in a reference is still a finding.
printf -- '---\nname: fixture\ndescription: fixture\n---\n\n# Fixture\n\nNothing.\n' >"$FIX/skill/SKILL.md"
out="$(python3 "$LINT" "$FIX/skill" 2>&1)"
check "an uncited refusal claim in references/ is a finding" 1 "$?" "$out"

if [ "$fails" -gt 0 ]; then
  echo "FAIL"
  exit 1
fi
echo "PASS: V1 and V2 both reach references/, findings name their file, and a citation anywhere in the skill covers the whole skill"
exit 0
