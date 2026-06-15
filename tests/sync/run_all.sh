# tests/sync/run_all.sh
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
fail=0
for t in "$DIR"/test_*.sh; do
  echo "── $t"
  bash "$t" || { echo "  ^ FAILED"; fail=1; }
done
[ "$fail" = 0 ] && echo "ALL GREEN" || { echo "SOME FAILED"; exit 1; }
