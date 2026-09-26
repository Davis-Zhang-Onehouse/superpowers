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
mkdir -p "$OUT"
if ! bash "$IT_ROOT/bin/sync-rows.sh" "$IT_ROOT/../../tests/sync" "$IT_RESULTS" "$OUT" "fleet/it/$SECTION/out"; then
  IT_FAILED=1
fi
it_assert_isolation SYNC-leave
[ "$IT_FAILED" -eq 0 ]
