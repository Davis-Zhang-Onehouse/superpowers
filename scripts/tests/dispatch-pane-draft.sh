#!/usr/bin/env bash
# A real draft with placeholder-like words stays queued; a dim suggestion is empty.
set -uo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
. "$repo/skills/dispatchInstants/lib/dispatch-lib.sh"
fail=0
check() {
  local name="$1" input="$2" want="$3" got rc
  got="$(dl_pane_unsubmitted "$input")"; rc=$?
  if [ "$got" != "$want" ]; then
    printf 'FAIL %s: rc=%s got=[%s] want=[%s]\n' "$name" "$rc" "$got" "$want"
    fail=1
  fi
}
check ask $'❯ Ask him first:\n' 'Ask him first:'
check try $'❯ Try "pytest" next\n' 'Try "pytest" next'
check dim $'❯ \033[2mAsk anything\033[0m\n' ''
check ordinary $'❯ ordinary draft\n' 'ordinary draft'

# OR-3 (v23-u review): a helper that cannot run the parser must not answer "no draft" (rc 1). A copy of the library
# with no fleet/src beside it, over an EMPTY box: the refusing answer, rc 0, and a reason on stderr.
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/skills/dispatchInstants/lib"
cp "$repo/skills/dispatchInstants/lib/dispatch-lib.sh" "$tmp/skills/dispatchInstants/lib/"
got="$(env -u PYTHONPATH bash -c '. "$1"; dl_pane_unsubmitted "$2"' _ \
        "$tmp/skills/dispatchInstants/lib/dispatch-lib.sh" $'❯ \033[2mAsk anything\033[0m\n' 2>"$tmp/err")"; rc=$?
if [ "$rc" != 0 ] || ! grep -q 'dl_pane_unsubmitted' "$tmp/err"; then
  printf 'FAIL unimportable fleet: rc=%s got=[%s] stderr=[%s] want rc=0 (fail closed) and a reason\n' "$rc" "$got" "$(cat "$tmp/err")"
  fail=1
fi
exit "$fail"
