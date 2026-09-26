#!/usr/bin/env bash
# §SYNC (OI-13): the upstream-sync suite, tests/sync/test_*.sh, one row per script. Each script builds its own
# sandbox repos under mktemp -d and touches no fleet store and no tmux server; run here so a sync fix ships
# proved by the release gate rather than by instant evidence alone.
# Run: bash fleet/it/run-sync.sh
set -uo pipefail
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"
IT_FAILED=0
it_own_cases 'SYNC-.*|ISOLATION-SYNC-(enter|leave)'
it_section SYNC
trap 'it_cleanup_tmux' EXIT
OUT="$EV/out"
rm -rf "$OUT"; mkdir -p "$OUT"
rows="$(bash "$IT_ROOT/bin/sync-rows.sh" "$IT_ROOT/../../tests/sync" "$OUT")"
while IFS=$'\t' read -r case verdict log note; do
  [ -n "$case" ] || continue
  evidence="fleet/it/$SECTION/out/$log"; [ "$log" = - ] && evidence="tests/sync"
  if [ "$verdict" = PASS ]; then it_pass "$case" "$evidence" "$note"; else it_fail "$case" "$evidence" "$note"; fi
done <<< "$rows"
[ -n "$rows" ] || it_fail SYNC-suite "tests/sync" "bin/sync-rows.sh printed no row at all"
it_assert_isolation SYNC-leave
[ "$IT_FAILED" -eq 0 ]
