#!/usr/bin/env bash
# Every fleet skill must CARRY a lint suite. Without this, a skill can be added with no V1/V2 at all and the
# absence of findings reads as a clean bill of health — "absence is never success" applied to the coverage of
# the checks rather than to their results.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SKILLS="$HERE/../.."
WANT="using-fleet coordinating-instants working-as-a-dispatched-instant dispatching-subagents"
missing=""
for s in $WANT; do
  [ -d "$SKILLS/$s" ] || { missing="$missing $s(absent)"; continue; }
  [ -f "$SKILLS/$s/tests/lint-self.sh" ] || missing="$missing $s(no-lint)"
done
if [ -n "$missing" ]; then
  printf 'fleet skills without a lint suite:%s\n' "$missing"
  echo "FAIL"
  exit 1
fi
echo "PASS: all four fleet skills exist and each carries tests/lint-self.sh, so none can be added or changed without V1+V2 running over it"
exit 0
