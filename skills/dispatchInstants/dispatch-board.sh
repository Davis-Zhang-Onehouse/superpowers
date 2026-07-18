#!/usr/bin/env bash
#
# dispatch-board.sh — render the fleet dashboard from the MACHINE-GLOBAL board store
# (D-11). Takes NO arguments (like `wspool list`): the old per-base-path form is fully
# deprecated and errors out. EVERYTHING is DERIVED (never hand-maintained, so it can't
# drift): for every dispatch record it joins (a) the record against each child instant's
# CURRENT folder-state — found even after a state-rename, because instantName is dashless
# — (b) the child HANDOFF's '## Parked decision' block, and (c) the live ws lease. Rows are
# grouped by base_instant.
#
# Records live in $BOARD_DIR/records/*.json (default ~/.claude-dispatch-board). A fallback
# read also merges any leftover legacy <base>/dispatch/*.json for every base_instant seen in
# the global store (dedup by todo_id; global wins) so a stray/late legacy record still shows.
#
# Writes $BOARD_DIR/REGISTRY.md (all bases) and prints it. Read-only w.r.t. all instants.
#
# Design: dispatchInstants/docs/2026-07-18-global-dispatch-board-design.md (supersedes
#         2026-07-16-dispatch-instants-design.md §5).
#
# Usage:   dispatch-board.sh          (no arguments)
# Env:     BOARD_DIR (default ~/.claude-dispatch-board), POOL_DIR (passed to wspool.sh),
#          WSPOOL_SH (default alongside this script)
#
set -euo pipefail
SELF="$(readlink -f "$0" 2>/dev/null || echo "$0")"; HERE="$(cd "$(dirname "$SELF")" && pwd)"
WSPOOL_SH="${WSPOOL_SH:-$HERE/wspool.sh}"

err(){ printf 'ERROR: %s\n' "$*" >&2; }

# The base-path form is gone (D-11): the board is global and argument-less.
if [ "$#" -gt 0 ]; then
  err "pdispatch board no longer takes a base path — records are global; run 'pdispatch board' with no arguments"
  exit 2
fi

BOARD_DIR="${BOARD_DIR:-$HOME/.claude-dispatch-board}"
RECORDS_DIR="$BOARD_DIR/records"
OUT="$BOARD_DIR/REGISTRY.md"

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

mkdir -p "$RECORDS_DIR"
TODAY="$(date +%Y-%m-%d)"

# ---- gather record files ----------------------------------------------------
# 1) authoritative global store; 2) fallback legacy <base>/dispatch/*.json for every
# base_instant referenced by a global record, merged by todo_id (global wins).
shopt -s nullglob
declare -a RECS=()
declare -A SEEN_TODO=()     # todo_id -> 1 (dedup; global store claims them first)
declare -A SEEN_BASE=()     # base_instant -> 1 (which legacy dirs to scan)

for rec in "$RECORDS_DIR"/*.json; do
  tid="$(basename "$rec" .json)"
  [ -n "${SEEN_TODO[$tid]:-}" ] && continue
  SEEN_TODO[$tid]=1
  RECS+=("$rec")
  b="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("base_instant",""))' "$rec" 2>/dev/null || true)"
  [ -n "$b" ] && SEEN_BASE[$b]=1
done

for base in "${!SEEN_BASE[@]}"; do
  for rec in "$base"/dispatch/*.json; do
    tid="$(basename "$rec" .json)"
    [ -n "${SEEN_TODO[$tid]:-}" ] && continue      # global wins on collision
    SEEN_TODO[$tid]=1
    RECS+=("$rec")
  done
done

# ---- build rows, grouped by base -------------------------------------------
tmp="$(mktemp)"; body="$(mktemp)"
n_run=0 n_park=0 n_done=0 n_abort=0 n_gone=0
declare -A GROUP=()          # base_instant -> accumulated markdown rows
declare -A GROUP_LABEL=()    # base_instant -> display label (basename)

for rec in "${RECS[@]}"; do
  eval "$(python3 - "$rec" <<'PY'
import json,sys,shlex
d=json.load(open(sys.argv[1]))
for k in ("todo_id","title","child_instant","ws","slot","tmux","base_instant"):
    print("R_%s=%s"%(k.upper(), shlex.quote(str(d.get(k,"")))))
PY
)"
  [ -n "$R_BASE_INSTANT" ] || R_BASE_INSTANT="(unknown base)"
  GROUP_LABEL[$R_BASE_INSTANT]="$(basename "$R_BASE_INSTANT")"

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
  GROUP[$R_BASE_INSTANT]+="$(printf '| %s | %s | %s | %s | %s |' "$R_TITLE" "$status" "$ws_disp" "$attach" "$child_disp")"$'\n'
done

{
  printf '# Dispatch board (global)\n'
  printf 'Updated: %s | Status: LIVE (DERIVED — do not hand-edit; run `pdispatch board`)\n' "$TODAY"
  printf 'Store: %s\n\n' "$RECORDS_DIR"
} > "$body"

if [ "${#RECS[@]}" -eq 0 ]; then
  printf 'No TODOs dispatched yet (global store %s is empty).\n' "$RECORDS_DIR" >> "$body"
else
  # stable base ordering
  while IFS= read -r base; do
    [ -z "$base" ] && continue
    printf '## %s\n' "${GROUP_LABEL[$base]}" >> "$body"
    printf '`%s`\n\n' "$base" >> "$body"
    printf '| TODO | Status | WS (lease) | Attach | Child instant |\n' >> "$body"
    printf '|------|--------|-----------|--------|---------------|\n' >> "$body"
    printf '%s\n' "${GROUP[$base]}" >> "$body"
  done < <(printf '%s\n' "${!GROUP[@]}" | sort)

  {
    printf '**Summary:** ▶ %d running · 🅿 %d parked · ✅ %d complete · ✖ %d abort' "$n_run" "$n_park" "$n_done" "$n_abort"
    [ "$n_gone" -gt 0 ] && printf ' · ⚠ %d gone' "$n_gone"
    printf '\n'
    [ "$n_park" -gt 0 ] && printf '\n> 🅿 %d session(s) need you — attach and answer the `## Parked decision` block.\n' "$n_park"
  } >> "$body"
fi

mv "$body" "$tmp"
mv "$tmp" "$OUT"
cat "$OUT"
