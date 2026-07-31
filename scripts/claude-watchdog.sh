#!/usr/bin/env bash
# claude-watchdog.sh — arm/disarm auto-resume for Claude CLI sessions under a root dir.
#
# Fully self-contained under $DAVIS (/home/ubuntu/davis_root): local Node, a local
# claude-auto-retry install, all state/config/logs, and the scheduler (a setsid daemon
# loop, NOT systemd/cron) live under $DAVIS. Nothing is written outside it.
#
# Why: the Claude CLI has no built-in auto-resume; a session that hits its usage/token
# limit halts until manual input. claude-auto-retry watches the session's tmux pane
# (zero token cost while waiting) and, once the limit resets, sends-keys a "continue".
# The daemon re-runs a scoped reconcile every $INTERVAL so new sessions get picked up
# and coverage self-heals.
#
# Scope: this box is a single shared unix account (ubuntu, HOME=/home/ubuntu), so there
# is no per-OS-user isolation. Scoping is BEHAVIORAL, by working directory: only claude
# sessions whose cwd is under $ROOT are ever monitored; everyone else's sessions are
# excluded and any stray monitor on them is reaped. Override with CLAUDE_WATCHDOG_ROOT.
#
# Only sessions running inside tmux can be covered (the tool needs a pane to scrape and
# to send-keys the resume into) — see scripts/claude-tmux.sh to launch one.
#
# Usage:
#   scripts/claude-watchdog.sh arm       Turn ON:  start the daemon + arm in-scope sessions now
#   scripts/claude-watchdog.sh disarm    Turn OFF: stop the daemon + kill in-scope monitors
#   scripts/claude-watchdog.sh status    Show daemon state + per-session coverage (default)
#
# Idempotent: arm and disarm each converge to the same end state no matter how often run.
set -u

DAVIS="/home/ubuntu/davis_root"
ROOT="${CLAUDE_WATCHDOG_ROOT:-$DAVIS}"
NODE_BIN="$DAVIS/opt/node/bin"
CAR="$DAVIS/opt/car/node_modules/.bin/claude-auto-retry"
CAR_HOME="${CLAUDE_WATCHDOG_HOME:-$DAVIS}"                       # HOME for the tool -> its state/config land under $DAVIS
CAR_DIR="$CAR_HOME/.claude-auto-retry"
EXCLUDE_FILE="$CAR_DIR/reconcile-exclude"
PIDFILE="$CAR_DIR/watchdog-daemon.pid"
LOGFILE="$CAR_DIR/watchdog-daemon.log"
INTERVAL="${CLAUDE_WATCHDOG_INTERVAL:-300}"
SELF="$(readlink -f "$0")"

# Run the local claude-auto-retry with local Node on PATH and HOME pinned to $DAVIS so
# all of its state/config/exclude/logs live under $DAVIS. Children (monitors) inherit this.
run_car() { PATH="$NODE_BIN:$PATH" HOME="$CAR_HOME" "$CAR" "$@"; }

# --- helpers ---------------------------------------------------------------

in_scope() { case "${1%/}/" in "${ROOT%/}"/*) return 0 ;; *) return 1 ;; esac; }
# Probes are overridable so the exclude logic is testable without owning a real fleet
# (WATCHDOG_PIDS_PROBE prints pids; WATCHDOG_CWD_PROBE <pid> prints its cwd).
claude_pids() {
  if [ -n "${WATCHDOG_PIDS_PROBE:-}" ]; then "$WATCHDOG_PIDS_PROBE"; else pgrep -x claude 2>/dev/null; fi
}
cwd_of() {
  if [ -n "${WATCHDOG_CWD_PROBE:-}" ]; then "$WATCHDOG_CWD_PROBE" "$1"
  else readlink -f "/proc/$1/cwd" 2>/dev/null; fi
}
monitor_target_pid() { printf '%s\n' "$1" | grep -oE 'monitor\.js +%[0-9]+ +[0-9]+' | grep -oE '[0-9]+$'; }

# A dispatched worker that is FINISHED (harvested, or its instant folder renamed -complete-) must
# stop being re-armed. The daemon reconciles every $INTERVAL and previously re-attached a monitor to
# any in-scope claude session forever, because "finished" was not a fact it could read: on
# 2026-07-28 two workers nine days past the end of their effort still had live monitors. That is not
# merely wasteful — on a rate-limit banner the monitor types "Continue where you left off." + Enter
# into a pane whose cwd may since have been re-leased to a different effort.
#
# The default is now the FLEET-backed answer. pdispatch is retired, and a default pointing into a retired
# tree is a dependency that works until somebody deletes a directory and then fails the safe way — silently,
# because `finished_dispatch_pids` treats every failure as "no exclusions", which is correct for a fault and
# indistinguishable from a genuinely empty answer. `CLAUDE_WATCHDOG_SESSIONS_TOOL` still overrides, so the
# old tool remains one variable away for as long as it exists.
#
# Verified in both directions by `scripts/tests/fleet-finished-pids.sh` against a real store, a real tmux
# server and three live processes: a finished worker's pid is printed, a working worker's is not, and an
# UNMANAGED session's is not — that last one being the failure that matters, since excluding unmanaged
# sessions would switch auto-resume off for the whole box while looking like a quiet success.
DISPATCH_SESSIONS="${CLAUDE_WATCHDOG_SESSIONS_TOOL:-$DAVIS/superpowers/scripts/fleet-finished-pids.sh}"

# The store is STATED, not inherited. `fleet`'s read-only verbs default to `$HOME/.fleet` on their own, so
# leaving this unset would work — and would mean the watchdog's exclusion silently followed whatever
# `FLEET_HOME` happened to be exported into the shell that armed the daemon, which is a different store per
# operator and per effort. A daemon that reconciles every 300s for weeks must not depend on that.
FLEET_HOME="${FLEET_HOME:-$HOME/.fleet}"; export FLEET_HOME

# `finished_dispatch_pids` treats EVERY failure as "exclude nothing". That is the right default — excluding a
# pid in error costs an auto-resume that should have happened, and there is no error channel back to a caller
# that only reads pids — but it makes a broken exclusion and an empty one look identical. And they are not
# the same thing at all: on a box with no fleet store, "exclude nothing" is permanent.
#
# So the two are distinguished in the LOG, and only when the answer CHANGES. The daemon wakes every
# $INTERVAL; a line per pass would be ~288/day of the same sentence, which is how a log stops being read.
EXCLUSION_STATE_FILE="$CAR_DIR/watchdog-exclusion.state"
log_exclusion_state() {           # log_exclusion_state <state-string>
  local now="$1" was=""
  [ -f "$EXCLUSION_STATE_FILE" ] && was="$(cat "$EXCLUSION_STATE_FILE" 2>/dev/null)"
  [ "$now" = "$was" ] && return 0
  mkdir -p "$CAR_DIR"
  printf '%s\n' "$now" > "$EXCLUSION_STATE_FILE"
  printf '[%s] exclusion: %s\n' "$(date -Is 2>/dev/null || date)" "$now" >> "$LOGFILE" 2>/dev/null || true
}

finished_dispatch_pids() {
  if [ ! -x "$DISPATCH_SESSIONS" ]; then
    log_exclusion_state "INACTIVE — no executable exclusion tool at $DISPATCH_SESSIONS, so no finished worker will ever be excluded"
    return 0
  fi
  local out; out="$("$DISPATCH_SESSIONS" --finished-pids 2>/dev/null)"
  if [ -n "$out" ]; then
    log_exclusion_state "active — excluding $(printf '%s\n' "$out" | grep -c '^[0-9]') finished worker pid(s): $(printf '%s' "$out" | tr '\n' ' ')"
    printf '%s\n' "$out"
  elif [ ! -d "$FLEET_HOME/records" ]; then
    # Not a fault, and not nothing-to-do either: there is no store to ask. Worth one log line, because the
    # exclusion is inert until a dispatch actually writes records HERE, and nothing else would ever say so.
    log_exclusion_state "INERT — no store at $FLEET_HOME/records, so there are no dispatch records to derive finished workers from"
  else
    log_exclusion_state "active — store at $FLEET_HOME/records has no finished workers to exclude"
  fi
  return 0
}

# Rebuild the exclude list = every live claude PID that must NOT be armed:
#   · cwd is not under $ROOT (someone else's session), or
#   · it is a dispatched worker whose work is over.
rebuild_exclude() {
  mkdir -p "$CAR_DIR"
  local tmp pid cwd fin
  tmp="$(mktemp)"
  echo "# auto-generated by claude-watchdog.sh — claude PIDs that must not be armed" > "$tmp"
  echo "# (cwd not under $ROOT, or a dispatched worker that has finished)" >> "$tmp"
  fin="$(finished_dispatch_pids)"
  for pid in $(claude_pids); do
    cwd="$(cwd_of "$pid")" || continue
    [ -n "$cwd" ] || continue
    if ! in_scope "$cwd"; then echo "$pid" >> "$tmp"; continue; fi
    printf '%s\n' "$fin" | grep -qx "$pid" && echo "$pid" >> "$tmp"
  done
  mv "$tmp" "$EXCLUDE_FILE"
}

# Kill armed monitors by scope. $1 = "out" (kill out-of-scope) | "in" (kill in-scope).
reap_monitors() {
  local which="$1" mpid rest tpid cwd
  pgrep -af 'monitor\.js' 2>/dev/null | while read -r mpid rest; do
    tpid="$(monitor_target_pid "$rest")"
    [ -n "${tpid:-}" ] || continue
    cwd="$(cwd_of "$tpid")"
    if [ "$which" = out ]; then
      in_scope "${cwd:-/}" || kill "$mpid" 2>/dev/null || true
    else
      in_scope "${cwd:-/}" && kill "$mpid" 2>/dev/null || true
    fi
  done
}

# --- daemon (self-contained scheduler; replaces systemd/cron) --------------

daemon_pid() { [ -f "$PIDFILE" ] && cat "$PIDFILE" 2>/dev/null; }
daemon_running() { local p; p="$(daemon_pid)"; [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }

start_daemon() {
  daemon_running && return 0
  mkdir -p "$CAR_DIR"
  setsid "$SELF" _daemon >>"$LOGFILE" 2>&1 </dev/null &
  disown 2>/dev/null || true
  # Wait (briefly) for the setsid child to write its pidfile so callers see it running.
  local waited=0
  while [ "$waited" -lt 10 ]; do
    daemon_running && return 0
    sleep 0.2
    waited=$((waited + 1))
  done
}

stop_daemon() {
  local p; p="$(daemon_pid)"
  [ -n "$p" ] && kill "$p" 2>/dev/null || true
  rm -f "$PIDFILE"
}

cmd_daemon() {  # internal: the loop. Single-instance guarded.
  local existing; existing="$(daemon_pid)"
  if [ -n "$existing" ] && [ "$existing" != "$$" ] && kill -0 "$existing" 2>/dev/null; then
    exit 0
  fi
  mkdir -p "$CAR_DIR"
  echo $$ > "$PIDFILE"
  trap 'rm -f "$PIDFILE"' EXIT INT TERM
  while true; do
    cmd_reconcile >/dev/null 2>&1 || true
    sleep "$INTERVAL"
  done
}

# --- subcommands -----------------------------------------------------------

# Internal: one scoped reconcile pass (used by the daemon and by arm).
cmd_reconcile() {
  [ -x "$CAR" ] || { echo "claude-auto-retry not found at $CAR" >&2; exit 1; }
  [ -x "$NODE_BIN/node" ] || { echo "local node not found at $NODE_BIN/node" >&2; exit 1; }
  rebuild_exclude
  reap_monitors out
  run_car reconcile
}

cmd_arm() {
  cmd_reconcile
  start_daemon
  echo
  cmd_status
}

cmd_disarm() {
  stop_daemon
  reap_monitors in
  echo "Disarmed: daemon stopped, in-scope monitors killed."
  echo "(sessions themselves are untouched — they just won't auto-resume on a limit hit)"
}

cmd_status() {
  local pid cwd armed_pids any=0 st dstate
  if daemon_running; then dstate="running (pid $(daemon_pid), every ${INTERVAL}s)"; else dstate="stopped"; fi
  echo "Watchdog daemon: $dstate     scope: $ROOT"
  armed_pids="$(pgrep -af 'monitor\.js' 2>/dev/null | while read -r _ rest; do monitor_target_pid "$rest"; done | sort -u)"
  echo "In-scope claude sessions:"
  for pid in $(claude_pids); do
    cwd="$(cwd_of "$pid")" || continue
    [ -n "$cwd" ] || continue
    in_scope "$cwd" || continue
    any=1
    if printf '%s\n' "$armed_pids" | grep -qx "$pid"; then st="ARMED"; else st="unarmed"; fi
    printf "  pid %-8s  %-48s  %s\n" "$pid" "$cwd" "$st"
  done
  [ "$any" = 0 ] && echo "  (none running under tmux)"
  return 0
}

case "${1:-status}" in
  arm)        cmd_arm ;;
  disarm)     cmd_disarm ;;
  status)     cmd_status ;;
  # Debug hook: rebuild the exclude list and print it. Exists so the "a finished dispatch is never
  # re-armed" rule is a tested assertion rather than a claim about code nobody exercises.
  _excludes)  rebuild_exclude; cat "$EXCLUDE_FILE" ;;
  _reconcile) cmd_reconcile ;;
  _daemon)    cmd_daemon ;;
  -h|--help|help)
    sed -n '2,44p' "$SELF" | sed 's/^# \{0,1\}//; s/^#//' ;;
  *)
    echo "Unknown command: ${1}" >&2
    echo "Usage: claude-watchdog.sh {arm|disarm|status}" >&2
    exit 2 ;;
esac
