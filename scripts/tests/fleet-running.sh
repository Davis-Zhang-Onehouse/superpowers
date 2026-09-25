#!/usr/bin/env bash
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# The helper is pure shell after sourcing; a function supplies recorded board porcelain.
. "$REPO/scripts/fleet-env.sh" >/dev/null 2>&1
fleet() {
  [ "$*" = 'board --porcelain' ] || return 2
  printf 'a\tworker\tRUNNING\ta\tws1\tm\tn\tr\ts\tsock\t\tfalse\n'
  printf 'b\tworker\tPARKED\tb\tws2\tm\tn\tr\ts\tsock\t\ttrue\n'
  printf 'c\tworker\tPARKED\tc\tws3\tm\tn\tr\ts\tsock\t\tfalse\n'
  printf 'd\tworker\tBLOCKED\td\tws4\tm\tn\tr\ts\tsock\t\tfalse\n'
}
got="$(fleet_running)"
want="$(printf 'a\tws1\nb\tws2')"
if [ "$got" = "$want" ]; then
  echo 'fleet-running: ALL GREEN'
else
  printf 'fleet-running: wanted [%s], got [%s]\n' "$want" "$got" >&2
  exit 1
fi
