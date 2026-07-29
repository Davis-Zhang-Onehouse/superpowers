#!/usr/bin/env bash
#
# dispatch-lib.sh — shared primitives for the dispatch toolkit. Source it; do not execute it.
#
# Everything here answers a question that was previously answered by hand in each caller, which is
# how this toolkit acquired six identifier bugs and six false-alarm bugs in a single day. Two rules
# are encoded rather than remembered:
#   · read identity from the record that already holds it — never rebuild a name from a pattern.
#   · every environment probe is overridable, so a suite can describe a fleet without owning one.
#
# Probe overrides (all used by skills/dispatchInstants/tests/session-lifetime.sh):
#   SESSION_PROBE      prints "pid<TAB>cwd<TAB>remote-control-session" per live claude process
#   WSPOOL_CWD_PROBE   <path> -> the pids holding it as cwd
#   MONITOR_PROBE      prints "monitor-pid<TAB>target-pid" per live claude-auto-retry monitor
#   KILL_BIN           the kill command (default: kill)
#   TMUX_BIN           the tmux command (default: tmux)

TMUX_BIN="${TMUX_BIN:-tmux}"
KILL_BIN="${KILL_BIN:-kill}"

# --- record access ----------------------------------------------------------

dl_field() { # <record.json> <key> -> value ("" if absent)
  python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get(sys.argv[2],"") or "")
except Exception: print("")' "$1" "$2" 2>/dev/null
}

dl_set_fields() { # <record.json> <key> <value> [<key> <value> ...]
  python3 - "$@" <<'PY'
import json, sys
p = sys.argv[1]
try:
    d = json.load(open(p, encoding="utf-8"))
except Exception:
    d = {}
kv = sys.argv[2:]
for k, v in zip(kv[0::2], kv[1::2]):
    d[k] = v
json.dump(d, open(p, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
PY
}

dl_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# A worker RENAMES its folder (-inflight- -> -complete-/-abort-) as its completion signal, so the
# path recorded at dispatch time goes stale. Resolve the CURRENT folder. <base>-<curr> alone is not
# unique — two instants dispatched in the same minute share it — so the whole name is matched with
# only the <state> token varying.
dl_resolve_instant() { # <recorded child path> -> current basename ("" if unresolvable)
  local p="$1" b d pre rest m
  [ -n "$p" ] || return 0
  b="$(basename -- "$p")"
  if [ -d "$p" ]; then printf '%s' "$b"; return 0; fi
  d="$(dirname -- "$p")"
  pre="$(printf '%s' "$b" | grep -oE '^[0-9]{8}-[0-9]{8}' || true)"
  rest="$(printf '%s' "$b" | sed -E 's/^[0-9]{8}-[0-9]{8}-(inflight|complete|abort)-//')"
  if [ -n "$pre" ] && [ -n "$rest" ] && [ -d "$d" ]; then
    m="$(ls -1 "$d" 2>/dev/null | grep -E "^${pre}-(inflight|complete|abort)-${rest}$" | head -1)"
    [ -n "$m" ] && { printf '%s' "$m"; return 0; }
  fi
  printf '%s' "$b"
}

dl_instant_dir() { # <recorded child path> -> current absolute dir
  local p="$1" n
  [ -n "$p" ] || return 1
  n="$(dl_resolve_instant "$p")"
  [ -n "$n" ] || return 1
  printf '%s/%s' "$(dirname -- "$p")" "$n"
}

# Has this worker finished? Two independent signals, either is sufficient: the coordinator has
# harvested it, or the worker renamed its own folder. A report file is NOT a completion signal.
dl_is_finished() { # <record.json>
  local rec="$1" name
  [ -n "$(dl_field "$rec" harvested_at)" ] && return 0
  name="$(dl_resolve_instant "$(dl_field "$rec" child_instant)")"
  case "$name" in *-complete-*|*-abort-*) return 0;; esac
  return 1
}

dl_alive() { # <tmux session name>
  [ -n "$1" ] || return 1
  pgrep -f "remote-control $1" >/dev/null 2>&1 && return 0
  "$TMUX_BIN" has-session -t "$1" >/dev/null 2>&1
}

# --- rule: a COMPACTION instant is exclusive ---------------------------------
# A compaction folds several finished branches into ONE stacked chain, and its end state becomes the
# base every later instant builds on. Anything dispatched ALONGSIDE it is based on the pre-compaction
# tree, so the compaction cannot fold it and it lands as the NEXT compaction's debt. Therefore: while
# a compaction is inflight, nothing else dispatches at all.
#
# This is a SEPARATE rule from the WIP cap, and it deliberately does NOT live in the cap counter. A
# compaction that has declared `Phase: AWAITING-CI` counts ZERO against the cap — it consumes no dev
# attention — and must still block everything, because its cost is unfoldable rebase debt, not
# attention. Folding rule 2 into rule 1 gets exactly one of those two cases wrong, whichever way you
# fold it (see tests/wip-cap-and-compaction-exclusive.sh § independence).
#
# Detection needs no new metadata. The instant grammar already encodes it:
#   <base_instant>-<curr_instant>-<state>-<opType>-<instantName>
# so a live compaction is a sibling with <state>=inflight and <opType>=compact. The effort is scoped
# the way every other tool here scopes it — the instants dir is `dirname <base-instant>` — rather
# than by a second convention that would drift away from the first.

# Reserved so a caller can tell this refusal from bad input (2) or a full pool (3).
DL_RC_COMPACTION_INFLIGHT=4

dl_inflight_compactions() { # <instants-dir> [<self-instant-basename>] -> names one per line; rc 0 if any
  local dir="$1" self="${2:-}" p n rc=1
  [ -n "$dir" ] && [ -d "$dir" ] || return 1
  for p in "$dir"/*-inflight-compact-*; do
    [ -d "$p" ] || continue
    n="$(basename -- "$p")"
    # Launching the compaction ITSELF must never be blocked by its own folder.
    if [ -n "$self" ] && [ "$n" = "$self" ]; then continue; fi
    printf '%s\n' "$n"
    rc=0
  done
  return "$rc"
}

# The refusal, shared by EVERY dispatch entry point. `todo` and `launch` are two doors into the same
# act, so guarding one leaves `todo --no-launch` + `launch` as a complete bypass.
# Returns non-zero by design, so every caller must suspend errexit at the call site
# (`dl_compaction_guard ... || exit $?`), never call it bare under `set -e`.
dl_compaction_guard() { # <instants-dir> <self-basename|""> <override-reason|"">  rc 0 = proceed
  local dir="$1" self="${2:-}" reason="${3:-}" blockers
  blockers="$(dl_inflight_compactions "$dir" "$self")" || return 0
  if [ -n "$reason" ]; then
    {
      printf 'WARN: a COMPACTION instant is inflight and this dispatch was OVERRIDDEN.\n'
      printf '%s\n' "$blockers" | while IFS= read -r n; do
        if [ -n "$n" ]; then printf '  blocking compaction: %s\n' "$n"; fi
      done
      printf '  reason given: %s\n' "$reason"
      printf '  RECORD this reason in your DECISIONS register: an unrecorded override is silent rebase\n'
      printf '  debt for whoever runs the next compaction.\n'
    } >&2
    return 0
  fi
  {
    printf 'ERROR: refusing to dispatch — a COMPACTION instant is inflight in %s\n' "$dir"
    printf '%s\n' "$blockers" | while IFS= read -r n; do
      if [ -n "$n" ]; then printf '  blocking compaction: %s\n' "$n"; fi
    done
    printf '  A compaction folds the finished branches into one stacked chain, and its end state becomes\n'
    printf '  the base everything later builds on. Anything dispatched now is based on the PRE-compaction\n'
    printf '  tree, so that compaction cannot fold it and it becomes the next one'\''s debt.\n'
    printf '  Wait for the rename to -complete-compact- (the rename IS the state transition), or override:\n'
    printf '    --allow-during-compaction "<reason>"   or   ALLOW_DISPATCH_DURING_COMPACTION="<reason>"\n'
    printf '  and record that reason in DECISIONS.\n'
  } >&2
  return "$DL_RC_COMPACTION_INFLIGHT"
}

# Resolve the override reason from flag-then-env, and refuse an override with no reason at all — the
# reason IS the mechanism (mirrors how WIP_CAP is documented as needing a reason in DECISIONS).
dl_override_reason() { # <flag-was-passed 0|1> <flag-value> -> reason on stdout; rc 2 = given but empty
  local given="$1" val="${2:-}"
  if [ "$given" = 1 ]; then
    [ -n "$val" ] || return 2
    printf '%s' "$val"; return 0
  fi
  # A SET-BUT-EMPTY env var is an operator error too, and must not fall through to the ordinary
  # refusal — that refusal's remedy is "set ALLOW_DISPATCH_DURING_COMPACTION", which they just did.
  # Telling someone to do the thing they already did sends them in a circle. `+set` distinguishes
  # set-to-empty from unset; `:-` cannot.
  if [ -n "${ALLOW_DISPATCH_DURING_COMPACTION+set}" ] && [ -z "$ALLOW_DISPATCH_DURING_COMPACTION" ]; then
    return 2
  fi
  printf '%s' "${ALLOW_DISPATCH_DURING_COMPACTION:-}"
}

# A flag passed as the LAST argument has no value, and `shift 2` then shifts nothing and returns 1:
# under `set -uo pipefail` the arg loop spins forever, under `set -euo pipefail` the script dies with
# a bare rc=1. "Operator forgot the reason" is the most likely way an override is mistyped, so it
# must produce a message, not a hang.
dl_need_arg() { # <flag-name> <remaining $#>  rc 2 if there is no value after the flag
  if [ "${2:-0}" -lt 2 ]; then
    printf '%s requires a value, but it was the last argument with nothing after it\n' "$1" >&2
    return 2
  fi
  return 0
}

# --- pane predicates --------------------------------------------------------
# Both are deliberately anchored to the LAST few lines. A `❯` earlier in the buffer is scrollback,
# and treating history as current state is how a watcher re-alarms its whole past on every restart.

# Text typed into the input box but never submitted. Claude turns long input into a paste
# placeholder and can swallow an Enter sent in the same keystroke batch, so this state is real and
# silent: on 2026-07-28 three of four live panes were holding one, including an authorization a
# coordinator believed it had delivered.
dl_pane_unsubmitted() { # <pane text> -> prints the queued text; rc 0 if there is any
  local pane="$1" line txt
  line="$(printf '%s\n' "$pane" | tail -8 | grep -m1 -E '^[[:space:]]*❯[[:space:]]+[^[:space:]]' 2>/dev/null || true)"
  [ -n "$line" ] || return 1
  txt="$(printf '%s' "$line" | sed -E 's/^[[:space:]]*❯[[:space:]]+//; s/[[:space:]]+$//')"
  [ -n "$txt" ] || return 1
  # Precautionary: an empty box can render dim placeholder text, which is not a swallowed submit.
  # The primary guard is the caller's idle gate; this only removes the shapes we know render there.
  case "$txt" in
    'Try "'*|'Ask '*|'/ for commands'*|'# for memory'*|'new task?'*) return 1;;
  esac
  printf '%s' "$txt"
}

# Mid-turn: the model is working and the pane is not a safe thing to destroy.
dl_pane_busy() { # <pane text>
  printf '%s\n' "$1" | tail -15 | grep -qiE 'esc to interrupt'
}

# --- environment probes -----------------------------------------------------

# Live claude processes: "pid<TAB>cwd<TAB>remote-control-session". Enumerating PROCESSES rather than
# board records is the whole point — a session with no record (a bare `claude --resume` under GNU
# screen, say) is invisible to any records-first sweep, and one such stray went unseen for 8 days.
dl_session_probe() {
  if [ -n "${SESSION_PROBE:-}" ]; then "$SESSION_PROBE"; return 0; fi
  local pid cwd args sess
  for pid in $(pgrep -x claude 2>/dev/null); do
    cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    args="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    sess="$(printf '%s' "$args" | grep -oE 'remote-control +[^ ]+' | awk '{print $2}' | head -1)"
    printf '%s\t%s\t%s\n' "$pid" "$cwd" "$sess"
  done
}

dl_cwd_holders() { # <path> -> pids holding it as cwd
  local path="$1" d p
  path="$(realpath -m -- "$path" 2>/dev/null || printf '%s' "$path")"
  if [ -n "${WSPOOL_CWD_PROBE:-}" ]; then "$WSPOOL_CWD_PROBE" "$path"; return 0; fi
  for d in /proc/[0-9]*; do
    p="$(readlink -f "$d/cwd" 2>/dev/null || true)"
    [ "$p" = "$path" ] && basename -- "$d"
  done
  return 0
}

dl_monitors() { # -> "monitor-pid<TAB>target-pid" per live claude-auto-retry monitor
  if [ -n "${MONITOR_PROBE:-}" ]; then "$MONITOR_PROBE"; return 0; fi
  local mp rest t
  pgrep -af 'monitor\.js' 2>/dev/null | while read -r mp rest; do
    t="$(printf '%s' "$rest" | grep -oE '[0-9]+$' || true)"
    [ -n "$t" ] && printf '%s\t%s\n' "$mp" "$t"
  done
  return 0
}

# --- id resolution ----------------------------------------------------------
# An ambiguous id is REFUSED rather than resolved to whichever sorts first. Every time this toolkit
# picked a winner from an ambiguous key it eventually picked a sibling's record.
dl_resolve_id() { # <records-dir> <partial-id> -> exact id on stdout; rc 0 ok, 1 none, 2 ambiguous
  local dir="$1" want="$2" f b hits=()
  [ -f "$dir/$want.json" ] && { printf '%s' "$want"; return 0; }
  for f in "$dir"/*.json; do
    [ -e "$f" ] || continue
    b="$(basename "$f" .json)"
    case "$b" in *"$want"*) hits+=("$b");; esac
  done
  case "${#hits[@]}" in
    0) return 1;;
    1) printf '%s' "${hits[0]}"; return 0;;
    *) printf '%s\n' "${hits[@]}"; return 2;;
  esac
}
