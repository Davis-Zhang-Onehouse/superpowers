#!/usr/bin/env bash
# OI-13: run each tests/sync/test_*.sh and print one row per script on stdout, for run-sync.sh to record through
# lib.sh's it_pass/it_fail (so the row lock, in-place placement and ownership check all apply):
#   SYNC-<name> <TAB> PASS|FAIL <TAB> <log file name> <TAB> <note>
# usage: sync-rows.sh <tests-sync-dir> <log-dir>
# Each script gets SYNC_TEST_TIMEOUT seconds (default 300): a hung test is a FAIL row, never a hung release gate.
# Exit 0 only when every script passed and at least one ran. Extracted from run-sync.sh so a hermetic test can drive
# it without a section's live-store isolation checks.
set -uo pipefail
suite="$1"; logs="$2"; limit="${SYNC_TEST_TIMEOUT:-300}"
mkdir -p "$logs"
ran=0; failed=0
for t in "$suite"/test_*.sh; do
  [ -f "$t" ] || continue
  name="$(basename "$t" .sh)"; ran=$((ran + 1))
  timeout "$limit" bash "$t" > "$logs/$name.log" 2>&1 < /dev/null
  rc=$?
  if [ "$rc" -eq 0 ]; then
    printf 'SYNC-%s\tPASS\t%s\t%s\n' "$name" "$name.log" "tests/sync/$name.sh exited 0"
  elif [ "$rc" -eq 124 ]; then
    failed=$((failed + 1))
    printf 'SYNC-%s\tFAIL\t%s\t%s\n' "$name" "$name.log" "tests/sync/$name.sh timed out after ${limit}s"
  else
    failed=$((failed + 1))
    printf 'SYNC-%s\tFAIL\t%s\t%s\n' "$name" "$name.log" "tests/sync/$name.sh exited $rc"
  fi
done
if [ "$ran" -eq 0 ]; then
  printf 'SYNC-suite\tFAIL\t-\t%s\n' "no tests/sync/test_*.sh found: an empty suite is not a pass"
  exit 1
fi
[ "$failed" -eq 0 ]
