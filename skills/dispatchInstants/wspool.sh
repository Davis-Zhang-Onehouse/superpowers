#!/usr/bin/env bash
#
# wspool.sh — machine-global, race-safe, crash-safe lease manager for a pool of
# pre-built workspace slots (~/ws1 .. ~/wsN) shared across parallel dispatched
# Claude sessions.
#
# WHY: several dispatched TODOs run at once; each needs its OWN workspace and must
# never collide with another. The pool is a SHARED machine resource — some ~/wsN
# slots hold unrelated live work — so slots are claimable ONLY after explicit
# opt-in enrollment (`add`). Claiming is atomic via `mkdir` (no flock/lockfile
# races). A crashed holder's slot is auto-recovered by tmux-liveness reaping.
#
# Design: dispatchInstants/docs/2026-07-16-dispatch-instants-design.md §3, DECISIONS D-6/D-7.
#
# Usage:
#   wspool.sh add <ws-path>...                 enroll slots (idempotent)
#   wspool.sh remove [--force] <slot|path>...  unenroll (refuses if leased unless --force)
#   wspool.sh list                             human view: FREE/LEASED/STALE + holder
#   wspool.sh status [slot]                    machine view (KEY=VALUE), all slots or one
#   wspool.sh claim --todo <id> --tmux <s> --base <p> --child <p> [--slot <ws>]
#                                              atomically grab a free slot; prints its
#                                              path on stdout. exit 0 ok / 3 pool-full.
#   wspool.sh release <slot|path>              free a slot (idempotent)
#   wspool.sh reap                             free every STALE lease (dead tmux)
#
# Env:
#   POOL_DIR   pool root (default ~/.claude-ws-pool). Override for hermetic tests.
#
# A slot is FREE  iff enrolled in $POOL_DIR/pool AND $POOL_DIR/leases/<slot> absent.
# A lease is STALE iff its meta's TMUX session is not alive (`tmux has-session`).
# A lease dir with no meta yet is treated as BUSY (a claim in progress), never stale.
#
set -euo pipefail

POOL_DIR="${POOL_DIR:-$HOME/.claude-ws-pool}"
POOL_FILE="$POOL_DIR/pool"
LEASE_DIR="$POOL_DIR/leases"

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_bold=$'\033[1m'; c_rst=$'\033[0m'
err()  { printf '%sERROR:%s %s\n' "$c_red" "$c_rst" "$*" >&2; }
warn() { printf '%sWARN:%s %s\n'  "$c_yel" "$c_rst" "$*" >&2; }
info() { printf '%s\n' "$*"; }

ensure_pool() { mkdir -p "$LEASE_DIR"; touch "$POOL_FILE"; }

# slot name = basename of the ws path (unique for ~/wsN). Accepts a slot name or a path.
slot_name() { basename -- "$1"; }

# resolve an enrolled slot name -> its absolute path (from the pool file). empty if not enrolled.
slot_path() {
  local want="$1" line
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    if [ "$(basename -- "$line")" = "$want" ] || [ "$line" = "$want" ]; then
      printf '%s\n' "$line"; return 0
    fi
  done < "$POOL_FILE"
  return 1
}

enrolled_slots() {  # print "name<TAB>path" per enrolled slot
  local line
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    printf '%s\t%s\n' "$(basename -- "$line")" "$line"
  done < "$POOL_FILE"
}

# Is the tmux session recorded in a lease dir alive? absent meta/TMUX => treat as ALIVE (busy).
lease_alive() {
  local ld="$1" tmux_s=""
  [ -f "$ld/meta" ] || return 0                       # meta not written yet => claim in progress
  tmux_s="$(sed -n 's/^TMUX=//p' "$ld/meta" | head -1)"
  [ -n "$tmux_s" ] || return 0                        # no session recorded => don't reap
  tmux has-session -t "$tmux_s" 2>/dev/null           # 0 alive / non-0 dead
}

lease_state() {  # echo FREE|LEASED|STALE for an enrolled slot name
  local name="$1" ld="$LEASE_DIR/$name"
  if [ ! -d "$ld" ]; then echo FREE; return; fi
  if lease_alive "$ld"; then echo LEASED; else echo STALE; fi
}

reap_one() {  # free the slot if its lease is stale; echo freed name or nothing
  local name="$1" ld="$LEASE_DIR/$name"
  [ -d "$ld" ] || return 1
  if lease_alive "$ld"; then return 1; fi
  rm -rf "$ld"
  printf '%s\n' "$name"
}

cmd_add() {
  ensure_pool
  [ "$#" -ge 1 ] || { err "add: need at least one ws path"; exit 2; }
  local p abs
  for p in "$@"; do
    abs="$(realpath -m -- "$p")"
    [ -d "$abs" ] || { warn "add: $abs is not an existing directory — enrolling anyway (must exist at claim time)"; }
    if grep -qxF -- "$abs" "$POOL_FILE" 2>/dev/null; then
      info "already enrolled: $abs"
    else
      printf '%s\n' "$abs" >> "$POOL_FILE"
      info "enrolled: $abs"
    fi
  done
}

cmd_remove() {
  ensure_pool
  local force=0; local -a targets=()
  local a
  for a in "$@"; do case "$a" in --force) force=1;; *) targets+=("$a");; esac; done
  [ "${#targets[@]}" -ge 1 ] || { err "remove: need a slot name or path"; exit 2; }
  local name path tmp
  tmp="$(mktemp)"
  cp "$POOL_FILE" "$tmp"
  for a in "${targets[@]}"; do
    name="$(slot_name "$a")"
    if [ "$(lease_state "$name")" = LEASED ] && [ "$force" -eq 0 ]; then
      err "remove: $name is LEASED (use --force to remove anyway)"; rm -f "$tmp"; exit 1
    fi
    path="$(slot_path "$name" || true)"
    if [ -n "$path" ]; then
      grep -vxF -- "$path" "$tmp" > "$tmp.2" || true; mv "$tmp.2" "$tmp"
      info "unenrolled: $path"
    else
      warn "not enrolled: $a"
    fi
  done
  mv "$tmp" "$POOL_FILE"
}

cmd_list() {
  ensure_pool
  local any=0 name path st holder ld
  while IFS=$'\t' read -r name path; do
    [ -z "$name" ] && continue
    any=1
    st="$(lease_state "$name")"
    holder=""
    ld="$LEASE_DIR/$name"
    if [ -f "$ld/meta" ]; then
      holder="$(sed -n 's/^TODO_ID=//p' "$ld/meta" | head -1)"
    fi
    case "$st" in
      FREE)   printf '  %s%-6s%s %sFREE%s        %s\n'   "$c_bold" "$name" "$c_rst" "$c_grn" "$c_rst" "$path";;
      LEASED) printf '  %s%-6s%s %sLEASED%s  -> %s   %s\n' "$c_bold" "$name" "$c_rst" "$c_yel" "$c_rst" "${holder:-?}" "$path";;
      STALE)  printf '  %s%-6s%s %sSTALE%s   (dead tmux; run: wspool reap)  %s\n' "$c_bold" "$name" "$c_rst" "$c_red" "$c_rst" "$path";;
    esac
  done < <(enrolled_slots)
  [ "$any" -eq 1 ] || info "  (pool empty — enroll slots with: wspool.sh add ~/wsN)"
}

cmd_status() {
  ensure_pool
  local want="${1:-}" name path st ld
  while IFS=$'\t' read -r name path; do
    [ -z "$name" ] && continue
    [ -n "$want" ] && [ "$name" != "$(slot_name "$want")" ] && continue
    st="$(lease_state "$name")"
    ld="$LEASE_DIR/$name"
    printf 'SLOT=%s STATE=%s PATH=%s' "$name" "$st" "$path"
    if [ -f "$ld/meta" ]; then
      printf ' %s' "$(tr '\n' ' ' < "$ld/meta")"
    fi
    printf '\n'
  done < <(enrolled_slots)
}

cmd_claim() {
  ensure_pool
  local todo="" tmux_s="" base="" child="" want_slot=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --todo)  todo="$2"; shift 2;;
      --tmux)  tmux_s="$2"; shift 2;;
      --base)  base="$2"; shift 2;;
      --child) child="$2"; shift 2;;
      --slot)  want_slot="$2"; shift 2;;
      *) err "claim: unknown arg $1"; exit 2;;
    esac
  done
  [ -n "$todo" ] || { err "claim: --todo required"; exit 2; }

  # candidate slot names, in enrollment order (or just the requested one).
  local -a cands=()
  local name path
  while IFS=$'\t' read -r name path; do
    [ -z "$name" ] && continue
    if [ -n "$want_slot" ]; then
      [ "$name" = "$(slot_name "$want_slot")" ] && cands+=("$name")
    else
      cands+=("$name")
    fi
  done < <(enrolled_slots)

  [ "${#cands[@]}" -ge 1 ] || { err "claim: no enrolled slots match ${want_slot:-<any>}"; exit 3; }

  # Try to win a slot: attempt mkdir (the atomic gate). If it exists, it's held —
  # unless STALE, in which case reap it and retry that same slot once.
  local ld attempt
  for attempt in 1 2; do
    for name in "${cands[@]}"; do
      ld="$LEASE_DIR/$name"
      if mkdir "$ld" 2>/dev/null; then
        # We won it. Write meta atomically-ish (single small file).
        {
          printf 'TODO_ID=%s\n' "$todo"
          printf 'TMUX=%s\n'    "$tmux_s"
          printf 'BASE_INSTANT=%s\n'  "$base"
          printf 'CHILD_INSTANT=%s\n' "$child"
          printf 'WS_PATH=%s\n'  "$(slot_path "$name")"
          printf 'HOLDER_HOST=%s\n' "$(hostname 2>/dev/null || echo '?')"
          printf 'EPOCH=%s\n'   "$(date +%s)"
        } > "$ld/meta"
        slot_path "$name"           # stdout = the claimed ws path
        return 0
      fi
    done
    # No free slot this pass. On the first pass, reap stale candidates and retry.
    if [ "$attempt" -eq 1 ]; then
      local reaped=0
      for name in "${cands[@]}"; do
        if reap_one "$name" >/dev/null 2>&1; then reaped=1; fi
      done
      [ "$reaped" -eq 1 ] && continue
    fi
    break
  done
  err "claim: pool full (no free slot among: ${cands[*]})"
  exit 3
}

cmd_release() {
  ensure_pool
  [ "$#" -ge 1 ] || { err "release: need a slot name or path"; exit 2; }
  local a name
  for a in "$@"; do
    name="$(slot_name "$a")"
    rm -rf "${LEASE_DIR:?}/$name"
    info "released: $name"
  done
}

cmd_reap() {
  ensure_pool
  local ld name freed=0
  for ld in "$LEASE_DIR"/*/; do
    [ -d "$ld" ] || continue
    name="$(basename -- "$ld")"
    if reap_one "$name" >/dev/null 2>&1; then
      info "reaped (dead tmux): $name"; freed=1
    fi
  done
  [ "$freed" -eq 1 ] || info "no stale leases."
}

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    add)     cmd_add "$@";;
    remove)  cmd_remove "$@";;
    list)    cmd_list "$@";;
    status)  cmd_status "$@";;
    claim)   cmd_claim "$@";;
    release) cmd_release "$@";;
    reap)    cmd_reap "$@";;
    -h|--help|help|"") sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) err "unknown command: $cmd"; exit 2;;
  esac
}
main "$@"
