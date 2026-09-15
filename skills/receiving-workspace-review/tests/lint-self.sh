#!/usr/bin/env bash
# V1+V2 over this skill. Discovered by bin/superpowers-selftest.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SKILL="$HERE/.."
LINT="$SKILL/../using-fleet/tools/lint-skill.py"

out="$(python3 "$LINT" "$SKILL" 2>&1)"
if [ $? = 0 ]; then
  echo "PASS: every fleet verb named in a code span is registered, and every refusal claim cites a passing case"
  exit 0
fi
printf '%s\n' "$out"
echo "FAIL"
exit 1
