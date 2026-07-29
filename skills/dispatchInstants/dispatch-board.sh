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
# Two renderings from one derivation:
#   - $BOARD_DIR/REGISTRY.md : persisted MARKDOWN (all bases) — a file artifact.
#   - stdout                 : a terminal-friendly, stacked-block view (ANSI colors only
#                              when stdout is a TTY, so pipes/redirects stay clean).
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
# BOTH middle fields are wildcards. <state> because that is what a transition rewrites; <opType>
# because it is a real field with two legal values, and hardcoding `-append-` here made every
# compaction dispatched with `pdispatch todo --optype compact` unresolvable — the board reported it
# `(missing)` and counted it as gone, from the moment it was dispatched. That was invisible while
# dispatch-todo could not produce a `-compact-` child; it became reachable the day it could, in the
# very flow Phase E mandates. A parser that hardcodes a VALUE of a field it claims to parse is the
# same defect class as one that never reads the field at all.
current_child() {
  local rec="$1" dir name f1 f2 f5 g
  dir="$(dirname "$rec")"; name="$(basename "$rec")"
  f1="$(cut -d- -f1 <<<"$name")"; f2="$(cut -d- -f2 <<<"$name")"; f5="$(cut -d- -f5- <<<"$name")"
  for g in "$dir/${f1}-${f2}-"*"-"*"-${f5}"; do
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

# ---- derive structured rows, grouped by base -------------------------------
US=$'\x1f'                    # field separator (never appears in titles/paths)
declare -A GROUP=()          # base_instant -> record-lines (US-joined fields, \n-separated)
declare -A GROUP_LABEL=()    # base_instant -> display label (basename)
n_run=0 n_park=0 n_done=0 n_abort=0 n_gone=0

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
  raw=""
  if [ -z "$cur" ]; then
    kind=gone; n_gone=$((n_gone+1)); child_disp="$R_CHILD_INSTANT (missing)"
  else
    st="$(basename "$cur" | cut -d- -f3)"; child_disp="$cur"
    case "$st" in
      complete) kind=complete; n_done=$((n_done+1));;
      abort)    kind=abort;    n_abort=$((n_abort+1));;
      inflight) if is_parked "$cur"; then kind=parked; n_park=$((n_park+1)); else kind=running; n_run=$((n_run+1)); fi;;
      *)        kind=other; raw="$st";;
    esac
  fi
  lease="$(lease_state_for "$R_SLOT")"
  GROUP[$R_BASE_INSTANT]+="${kind}${US}${raw}${US}${R_TITLE}${US}${R_WS}${US}${R_SLOT}${US}${lease}${US}${R_TMUX}${US}${child_disp}"$'\n'
done

# stable base ordering, reused by both renderers
mapfile -t BASES < <(printf '%s\n' "${!GROUP[@]}" | sort)

# ---- render 1: persisted markdown REGISTRY.md (file artifact) ---------------
md_status(){ case "$1" in
  running)  printf '▶ running';;
  parked)   printf '🅿 PARKED — needs you';;
  complete) printf '✅ complete';;
  abort)    printf '✖ abort';;
  gone)     printf '⚠ gone';;
  *)        printf '? %s' "$2";;
esac; }

body="$(mktemp)"
{
  printf '# Dispatch board (global)\n'
  printf 'Updated: %s | Status: LIVE (DERIVED — do not hand-edit; run `pdispatch board`)\n' "$TODAY"
  printf 'Store: %s\n\n' "$RECORDS_DIR"
} > "$body"

if [ "${#RECS[@]}" -eq 0 ]; then
  printf 'No TODOs dispatched yet (global store %s is empty).\n' "$RECORDS_DIR" >> "$body"
else
  for base in "${BASES[@]}"; do
    [ -z "$base" ] && continue
    printf '## %s\n`%s`\n\n' "${GROUP_LABEL[$base]}" "$base" >> "$body"
    printf '| TODO | Status | WS (lease) | Attach | Child instant |\n' >> "$body"
    printf '|------|--------|-----------|--------|---------------|\n' >> "$body"
    while IFS= read -r line; do
      [ -z "$line" ] && continue
      IFS="$US" read -r kind raw title ws slot lease tmux child <<<"$line"
      printf '| %s | %s | %s (%s: %s) | `tmux attach -t %s` | %s |\n' \
        "$title" "$(md_status "$kind" "$raw")" "$ws" "$slot" "$lease" "$tmux" "$child" >> "$body"
    done <<<"${GROUP[$base]}"
    printf '\n' >> "$body"
  done
  {
    printf '**Summary:** ▶ %d running · 🅿 %d parked · ✅ %d complete · ✖ %d abort' "$n_run" "$n_park" "$n_done" "$n_abort"
    [ "$n_gone" -gt 0 ] && printf ' · ⚠ %d gone' "$n_gone"
    printf '\n'
    [ "$n_park" -gt 0 ] && printf '\n> 🅿 %d session(s) need you — attach and answer the `## Parked decision` block.\n' "$n_park"
  } >> "$body"
fi
mv "$body" "$OUT"

# ---- render 2: terminal-friendly stacked view to stdout --------------------
if [ -t 1 ]; then
  b=$'\033[1m'; d=$'\033[2m'; rst=$'\033[0m'
  cyan=$'\033[36m'; grn=$'\033[32m'; yel=$'\033[33m'; red=$'\033[31m'
else
  b=""; d=""; rst=""; cyan=""; grn=""; yel=""; red=""
fi

term_tag(){ local kind="$1" raw="$2" glyph word col
  case "$kind" in
    running)  glyph='▶'; word='running';    col="$grn";;
    parked)   glyph='🅿'; word='PARKED';     col="$b$yel";;
    complete) glyph='✅'; word='done';       col="$d";;
    abort)    glyph='✖'; word='abort';      col="$red";;
    gone)     glyph='⚠'; word='gone';       col="$red";;
    *)        glyph='?'; word="${raw:-?}";  col="";;
  esac
  printf '%s%s %-7s%s' "$col" "$glyph" "$word" "$rst"
}
term_lease(){ case "$1" in
  LEASED) printf '%s%s%s' "$yel" "$1" "$rst";;
  FREE)   printf '%s%s%s' "$grn" "$1" "$rst";;
  STALE)  printf '%s%s%s' "$red" "$1" "$rst";;
  *)      printf '%s%s%s' "$d"   "$1" "$rst";;
esac; }
home_short(){ printf '%s' "${1/#$HOME/\~}"; }

if [ "${#RECS[@]}" -eq 0 ]; then
  printf '%sDispatch board%s — no TODOs dispatched yet\n' "$b" "$rst"
  printf '%sstore %s%s\n' "$d" "$(home_short "$RECORDS_DIR")" "$rst"
else
  printf '%sDispatch board%s — %s%d TODOs%s · %s▶ %d running%s · %s🅿 %d parked%s · %s✅ %d complete%s' \
    "$b" "$rst" "$b" "${#RECS[@]}" "$rst" "$grn" "$n_run" "$rst" "$b$yel" "$n_park" "$rst" "$d" "$n_done" "$rst"
  [ "$n_abort" -gt 0 ] && printf ' · %s✖ %d abort%s' "$red" "$n_abort" "$rst"
  [ "$n_gone"  -gt 0 ] && printf ' · %s⚠ %d gone%s'  "$red" "$n_gone"  "$rst"
  printf '\n%sstore %s · updated %s%s\n' "$d" "$(home_short "$RECORDS_DIR")" "$TODAY" "$rst"

  for base in "${BASES[@]}"; do
    [ -z "$base" ] && continue
    printf '\n%s%s▌ %s%s\n' "$b" "$cyan" "${GROUP_LABEL[$base]}" "$rst"
    while IFS= read -r line; do
      [ -z "$line" ] && continue
      IFS="$US" read -r kind raw title ws slot lease tmux child <<<"$line"
      printf '  %s  %s\n' "$(term_tag "$kind" "$raw")" "$title"
      case "$kind" in
        running|parked) att="tmux attach -t $tmux";;
        *)              att="$tmux";;
      esac
      printf '              %s %s · %s%s%s\n' "$slot" "$(term_lease "$lease")" "$d" "$att" "$rst"
    done <<<"${GROUP[$base]}"
  done

  if [ "$n_park" -gt 0 ]; then
    [ "$n_park" -eq 1 ] && noun="1 session needs" || noun="$n_park sessions need"
    printf '\n%s🅿 %s you%s — attach & answer its "## Parked decision".\n' "$b$yel" "$noun" "$rst"
  fi
fi
