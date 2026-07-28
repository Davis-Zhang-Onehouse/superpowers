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
