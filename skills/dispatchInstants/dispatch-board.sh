#!/usr/bin/env bash
#
# dispatch-board.sh — render the fleet dashboard for a base instant. EVERYTHING is
# DERIVED (never hand-maintained, so it can't drift): it joins the immutable
# dispatch records under <base>/dispatch/ against (a) each child instant's CURRENT
# folder-state — found even after a state-rename, because instantName is dashless —
# (b) the child HANDOFF's '## Parked decision' block, and (c) the live ws lease.
#
# Writes <base>/dispatch/REGISTRY.md and prints it. Read-only w.r.t. all instants.
#
# Design: dispatchInstants/docs/2026-07-16-dispatch-instants-design.md §5, DECISIONS D-5.
#
# Usage:   dispatch-board.sh <base-instant>
# Env:     POOL_DIR (passed to wspool.sh), WSPOOL_SH (default alongside this script)
#
set -euo pipefail
SELF="$(readlink -f "$0" 2>/dev/null || echo "$0")"; HERE="$(cd "$(dirname "$SELF")" && pwd)"
WSPOOL_SH="${WSPOOL_SH:-$HERE/wspool.sh}"

err(){ printf 'ERROR: %s\n' "$*" >&2; }

BASE="${1:-}"
[ -n "$BASE" ] || { err "usage: dispatch-board.sh <base-instant>"; exit 2; }
BASE="$(realpath -m -- "$BASE")"
[ -f "$BASE/HANDOFF.md" ] || { err "not a maintain-workspace instant: $BASE"; exit 2; }
DISPATCH_DIR="$BASE/dispatch"
OUT="$DISPATCH_DIR/REGISTRY.md"

# locate the CURRENT child folder for a recorded (possibly-renamed) child_instant path.
# grammar: <base>-<curr>-<state>-<opType>-<instantName>; only <state> changes on transition.
current_child() {
  local rec="$1" dir name f1 f2 f5 g
  dir="$(dirname "$rec")"; name="$(basename "$rec")"
  f1="$(cut -d- -f1 <<<"$name")"; f2="$(cut -d- -f2 <<<"$name")"; f5="$(cut -d- -f5- <<<"$name")"
  for g in "$dir/${f1}-${f2}-"*"-append-${f5}"; do
    [ -d "$g" ] && { printf '%s\n' "$g"; return 0; }
  done
  return 1
}

# parked? child HANDOFF '## Parked decision' block has real content (not empty / not <none>)
is_parked() {
  local h="$1/HANDOFF.md" block cleaned
  [ -f "$h" ] || return 1
  block="$(awk '/^## Parked decision/{f=1;next} /^## /{f=0} f' "$h")"
  cleaned="$(printf '%s' "$block" | sed 's/<none>//Ig' | tr -d '[:space:]')"
  [ -n "$cleaned" ]
}

lease_state_for() {  # echo lease STATE for a slot name, or "-" if unknown
  local slot="$1" line
  line="$(POOL_DIR="${POOL_DIR:-}" "$WSPOOL_SH" status "$slot" 2>/dev/null | head -1 || true)"
  if [ -n "$line" ]; then sed -n 's/.*STATE=\([A-Z]*\).*/\1/p' <<<"$line"; else echo "-"; fi
}

mkdir -p "$DISPATCH_DIR"
TODAY="$(date +%Y-%m-%d)"
tmp="$(mktemp)"
{
  printf '# Dispatch board — %s\n' "$(basename "$BASE")"
  printf 'Updated: %s | Status: LIVE (DERIVED — do not hand-edit; run dispatch-board.sh)\n\n' "$TODAY"
} > "$tmp"

shopt -s nullglob
records=("$DISPATCH_DIR"/*.json)
if [ "${#records[@]}" -eq 0 ]; then
  printf 'No TODOs dispatched from this base instant yet.\n' >> "$tmp"
else
  printf '| TODO | Status | WS (lease) | Attach | Child instant |\n' >> "$tmp"
  printf '|------|--------|-----------|--------|---------------|\n' >> "$tmp"
  n_run=0 n_park=0 n_done=0 n_abort=0 n_gone=0
  for rec in "${records[@]}"; do
    eval "$(python3 - "$rec" <<'PY'
import json,sys,shlex
d=json.load(open(sys.argv[1]))
for k in ("todo_id","title","child_instant","ws","slot","tmux"):
    print("R_%s=%s"%(k.upper(), shlex.quote(str(d.get(k,"")))))
PY
)"
    cur="$(current_child "$R_CHILD_INSTANT" || true)"
    if [ -z "$cur" ]; then
      status="⚠ gone"; n_gone=$((n_gone+1)); child_disp="$R_CHILD_INSTANT (missing)"
    else
      st="$(basename "$cur" | cut -d- -f3)"
      child_disp="$cur"
      case "$st" in
        complete) status="✅ complete"; n_done=$((n_done+1));;
        abort)    status="✖ abort"; n_abort=$((n_abort+1));;
        inflight)
          if is_parked "$cur"; then status="🅿 PARKED — needs you"; n_park=$((n_park+1));
          else status="▶ running"; n_run=$((n_run+1)); fi;;
        *) status="? $st";;
      esac
    fi
    ls_state="$(lease_state_for "$R_SLOT")"
    ws_disp="$R_WS ($R_SLOT: $ls_state)"
    attach="\`tmux attach -t $R_TMUX\`"
    printf '| %s | %s | %s | %s | %s |\n' "$R_TITLE" "$status" "$ws_disp" "$attach" "$child_disp" >> "$tmp"
  done
  {
    printf '\n**Summary:** ▶ %d running · 🅿 %d parked · ✅ %d complete · ✖ %d abort' "$n_run" "$n_park" "$n_done" "$n_abort"
    [ "$n_gone" -gt 0 ] && printf ' · ⚠ %d gone' "$n_gone"
    printf '\n'
    [ "$n_park" -gt 0 ] && printf '\n> 🅿 %d session(s) need you — attach and answer the `## Parked decision` block.\n' "$n_park"
  } >> "$tmp"
fi

mv "$tmp" "$OUT"
cat "$OUT"
