#!/usr/bin/env bash
# V23-I: title correction through the real CLI, on a private store and socket.
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"
IT_FAILED=0
it_own_cases 'RETITLE|ISOLATION-RETITLE-(enter|leave)'
it_section RETITLE
trap 'it_cleanup_tmux; tmux -L "$IT_TMUX_SOCKET" kill-server 2>/dev/null' EXIT
it_fresh_store
OUT="$EV/out"
mkdir -p "$OUT"
"$IT_FLEET" init --base 00000000 --name retitleCase --porcelain > "$OUT/init.txt" 2>&1
coord="$(awk -F '\t' '$1=="path"{print $2; exit}' "$OUT/init.txt")"
if [ -z "$coord" ] || [ ! -d "$coord" ]; then
  it_fail RETITLE "fleet/it/RETITLE/out/init.txt" "setup did not create a coordinator"
else
  "$IT_FLEET" milestone --instant "$coord" --id parent --title 'old scope' > "$OUT/add.txt" 2>&1; add_rc=$?
  "$IT_FLEET" milestone --instant "$coord" --id child --title 'dependent' --dep parent >> "$OUT/add.txt" 2>&1; dep_rc=$?
  "$IT_FLEET" milestone --instant "$coord" --id parent --retitle 'corrected scope' --reason 'finding clarified' --porcelain > "$OUT/retitle.txt" 2>&1; edit_rc=$?
  "$IT_FLEET" milestone --instant "$coord" --id parent --history --porcelain > "$OUT/history.txt" 2>&1; history_rc=$?
  "$IT_FLEET" roadmap --instant "$coord" --porcelain > "$OUT/roadmap.txt" 2>&1; view_rc=$?
  "$IT_FLEET" milestone --instant "$coord" --id parent --retitle 'bad' --reason 'mixed' --retire > "$OUT/refusal.txt" 2>&1; refusal_rc=$?
  if [ "$add_rc$dep_rc$edit_rc$history_rc$view_rc$refusal_rc" = '000002' ] \
    && grep -qF 'old scope' "$OUT/history.txt" \
    && grep -qF 'finding clarified' "$OUT/history.txt" \
    && grep -qF 'corrected scope' "$OUT/roadmap.txt" \
    && grep -qF $'not-ready\tchild' "$OUT/roadmap.txt"; then
    it_pass RETITLE "fleet/it/RETITLE/out/roadmap.txt" "the title changed on the same id, the dependent remained, history is readable and mixed operations refuse"
  else
    it_fail RETITLE "fleet/it/RETITLE/out/roadmap.txt" "retitle/history/render/refusal failed (rcs $add_rc$dep_rc$edit_rc$history_rc$view_rc$refusal_rc)"
  fi
fi
it_assert_isolation RETITLE-leave
[ "$IT_FAILED" -eq 0 ]
