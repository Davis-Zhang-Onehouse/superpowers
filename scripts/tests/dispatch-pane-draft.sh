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
exit "$fail"
