#!/usr/bin/env bash
# OI-13: run each tests/sync/test_*.sh and write one SYNC-<name> row per script into a results register.
# usage: sync-rows.sh <tests-sync-dir> <results.tsv> <log-dir> [<evidence-prefix>]
# The evidence column cites <evidence-prefix>/<name>.log (default: the log dir), so a runner can cite a
# relative path (P-3: no evidence cited by absolute path).
# Exit 0 only when every script passed and at least one ran. Extracted from run-sync.sh so a hermetic test can
# drive it without a section's live-store isolation checks.
set -uo pipefail
suite="$1"; results="$2"; logs="$3"; cite="${4:-$3}"
mkdir -p "$logs"
ran=0; failed=0
for t in "$suite"/test_*.sh; do
  [ -f "$t" ] || continue
  name="$(basename "$t" .sh)"; ran=$((ran + 1))
  if bash "$t" > "$logs/$name.log" 2>&1 < /dev/null; then
    printf 'SYNC-%s\tPASS\t%s\t%s\n' "$name" "$cite/$name.log" "tests/sync/$name.sh exited 0" >> "$results"
  else
    rc=$?; failed=$((failed + 1))
    printf 'SYNC-%s\tFAIL\t%s\t%s\n' "$name" "$cite/$name.log" "tests/sync/$name.sh exited $rc" >> "$results"
  fi
done
if [ "$ran" -eq 0 ]; then
  printf 'SYNC-suite\tFAIL\t%s\t%s\n' "tests/sync" "no tests/sync/test_*.sh found: an empty suite is not a pass" >> "$results"
  exit 1
fi
[ "$failed" -eq 0 ]
