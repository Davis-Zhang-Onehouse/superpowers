#!/usr/bin/env bash
# live-pane.sh — a REAL interactive pane, on demand, for reproducing TUI-level behaviour.
#
# WHY THIS EXISTS
# ---------------
# Some findings cannot be reproduced without a live terminal UI on the other end. `FI-15` says
# `tmux send-keys … Enter` does not submit a worker's input box and a printable character THEN Enter
# does; `FI-7` says `pane-guard` misread a live claude pane as `12 not-claude` once in ~118 polls. Neither
# is visible against a shell — a shell submits on bare Enter, which is precisely the difference — and
# neither is visible against `bin/claude`, the stub every other section uses.
#
# Before this, the only real-claude pane in the tree was §P's, built inline inside the one case that
# needed it. So the next person needing one would have built a second, and that is `FI-20`'s shape: the
# safety-critical setup implemented once per caller. This is the shared one.
#
# WHAT IT GUARANTEES
# ------------------
#   1. NEVER the default tmux server. Every command goes to `-L $PROBE_SOCKET`, a private socket. The
#      harness contract forbids touching the default server and this tool cannot be talked into it: there
#      is no code path here that omits `-L`.
#   2. NEVER a `dt-` name. `dt-*` is what `cli._do_dispatch` names a real dispatch, and the standing rule
#      is that nothing here creates, kills or writes one. Refused by name check, not by convention.
#   3. Names you can tell apart at a glance: `itfleet-probe-<purpose>-<pid>`.
#        · `itfleet-` so the isolation classifier in `lib.sh` ALREADY treats a leak of one onto the
#          default server as a hard FAIL — the prefix is load-bearing, not decoration;
#        · `probe-` so it is distinguishable from a section's own sessions AND from a real claude a human
#          started, which was the operator's requirement;
#        · the pid so two probes never collide.
#   4. A real `claude` costs the weekly allowance, so `start` refuses without `FLEET_ALLOW_LIVE_CLAUDE=1`.
#   5. `--shell` starts a plain shell under the same names and lifecycle. This is what makes the mechanism
#      itself testable without spending anything, and `selftest` below uses it.
#   6. Everything started is recorded in a ledger, so `reap` can clean up after a crash rather than
#      leaving panes for someone to find.
#
# USAGE
#   live-pane.sh start <purpose> [--shell]   start a pane; prints the session name on stdout
#   live-pane.sh type  <session> <text>      type text WITHOUT submitting (send-keys -l)
#   live-pane.sh key   <session> <key>...    send raw key name(s), e.g. Enter
#   live-pane.sh submit <session> <text>     type AND submit, waiting for the box to have it first
#   live-pane.sh cap   <session>             capture the pane
#   live-pane.sh guard <session>             `fleet pane-guard` against it; prints and returns its code
#   live-pane.sh list                        every probe session on the private socket
#   live-pane.sh stop  <session>             kill one
#   live-pane.sh reap                        kill every probe session and clear the ledger
#   live-pane.sh selftest                    exercise the whole mechanism with --shell; no allowance spent
#
# `type` and `key` are deliberately SEPARATE verbs. Collapsing them is what makes `FI-15` invisible:
# "put text in the box" and "press Enter" are different acts and the finding is about their interaction.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
IT_ROOT="$(dirname "$HERE")"
REPO="$(cd "$IT_ROOT/../.." && pwd)"

PROBE_SOCKET="${FLEET_PROBE_SOCKET:-fleetprobe}"
PROBE_PREFIX="itfleet-probe-"
LEDGER="${FLEET_PROBE_LEDGER:-$IT_ROOT/.live-pane-ledger}"
REAL_CLAUDE="${FLEET_REAL_CLAUDE:-/home/ubuntu/.local/bin/claude}"

die() { echo "live-pane: $*" >&2; exit 2; }

# Every tmux call in this file. There is no other, deliberately: a bare `tmux` here would reach the
# DEFAULT server, which is the one thing this tool must never do.
ptmux() { tmux -L "$PROBE_SOCKET" "$@"; }

# A name this tool is allowed to touch. Checked on every verb that acts on a session, not only on start —
# `stop itfleet-D-worker` or `stop dt-realwork` must be refused even though this tool never created them.
check_name() {
  local name="$1"
  case "$name" in
    dt-*) die "refusing to touch '$name': dt-* is a real dispatch session and this tool never touches one" ;;
    "$PROBE_PREFIX"*) : ;;
    *) die "refusing to touch '$name': not a probe session (must start with '$PROBE_PREFIX')" ;;
  esac
}

cmd_start() {
  local purpose="${1:-}"; shift || true
  local shell_mode=0
  for arg in "$@"; do [ "$arg" = "--shell" ] && shell_mode=1; done
  [ -n "$purpose" ] || die "start needs a <purpose>, which becomes part of the session name"
  case "$purpose" in *[!a-zA-Z0-9-]*) die "purpose must be [a-zA-Z0-9-]: got '$purpose'" ;; esac

  local name="${PROBE_PREFIX}${purpose}-$$"
  check_name "$name"

  if [ "$shell_mode" = 1 ]; then
    ptmux new-session -d -s "$name" "sh -c 'while :; do sleep 3600; done'" \
      || die "could not start a shell pane"
  else
    [ "${FLEET_ALLOW_LIVE_CLAUDE:-0}" = 1 ] \
      || die "a real claude spends the account's weekly allowance. Set FLEET_ALLOW_LIVE_CLAUDE=1 to mean it, or pass --shell to exercise the mechanism for free."
    [ -x "$REAL_CLAUDE" ] || die "no real claude at $REAL_CLAUDE (set FLEET_REAL_CLAUDE)"
    #: `cd` into a scratch dir so the model cannot be handed this repository by accident. A probe exists
    #: to be typed at, not to be given work.
    local scratch="$IT_ROOT/.live-pane-scratch/$name"
    mkdir -p "$scratch"
    ptmux new-session -d -s "$name" -c "$scratch" "$REAL_CLAUDE" \
      || die "could not start a claude pane"
  fi
  printf '%s\t%s\n' "$name" "$(date -u +%FT%TZ)" >> "$LEDGER"
  echo "$name"
}

cmd_type()  { check_name "$1"; ptmux send-keys -t "=$1:" -l "$2"; }
cmd_key()   { local s="$1"; check_name "$s"; shift; ptmux send-keys -t "=$s:" "$@"; }

# submit <session> <text> — type it and press Enter, WITHOUT losing the Enter.
#
# `FI-15`. `send-keys <text>` immediately followed by `send-keys Enter` DROPS the Enter: the TUI has not
# processed the text yet and the keystroke reaches a widget that is not ready for it. Measured on a real
# pane (investigations/fi-15/timing.txt): at gap=0 `pane-guard` read 0 straight after the type — the text
# had not even landed — and 10 after the Enter, meaning still queued, not submitted. At 50ms and above it
# submits every time.
#
# The reporter's workaround was to send a printable character before Enter, which works and works for the
# wrong reason: the extra round-trip buys the milliseconds. A leading space is a charm, not a mechanism,
# and believing it leaves the channel one scheduling hiccup from silently dropping instructions again.
#
# So this waits for a CONDITION, not a duration. `pane-guard` already answers exactly the right question
# — rc 10 is "there is text in the box" — so the contract is: type, poll until the box has it, then
# Enter. A fixed `sleep` would be the same bug with a bigger constant, wrong on a loaded box.
cmd_submit() {
  local session="$1" text="$2" i g
  check_name "$session"
  cmd_type "$session" "$text"
  for i in $(seq 1 50); do                      # 50 x 0.2s = 10s, generous for a keystroke to land
    g="$(cmd_guard "$session")" || true
    [ "$g" = 10 ] && break
    sleep 0.2
  done
  if [ "${g:-}" != 10 ]; then
    echo "live-pane: the text never reached the box (pane-guard=${g:-?} after 10s); NOT sending Enter, " \
         "because an Enter into an empty box submits nothing and looks like it worked" >&2
    return 1
  fi
  ptmux send-keys -t "=$session:" Enter
}
cmd_cap()   { check_name "$1"; ptmux capture-pane -p -t "=$1:"; }

cmd_guard() {
  check_name "$1"
  FLEET_TMUX_SOCKET="$PROBE_SOCKET" PYTHONPATH="$REPO/fleet/src" \
    python3 -m fleet.cli pane-guard --pane "$1" >/dev/null 2>&1
  local rc=$?
  echo "$rc"
  return "$rc"
}

cmd_list() { ptmux ls -F '#{session_name}' 2>/dev/null | grep "^$PROBE_PREFIX" || true; }

cmd_stop() { check_name "$1"; ptmux kill-session -t "=$1" 2>/dev/null; return 0; }

cmd_reap() {
  local n=0 s
  while read -r s; do
    [ -n "$s" ] || continue
    check_name "$s"; ptmux kill-session -t "=$s" 2>/dev/null; n=$((n+1))
  done < <(cmd_list)
  : > "$LEDGER"
  rm -rf "$IT_ROOT/.live-pane-scratch"
  echo "reaped $n probe session(s) from socket $PROBE_SOCKET"
}

# The mechanism's own test, with a shell rather than a model, so it costs nothing and can run in CI.
# It checks the GUARANTEES, not the happy path: the refusals are the part that matters.
cmd_selftest() {
  local fails=0
  ok()  { printf 'ok    %s\n' "$*"; }
  bad() { printf 'BAD   %s\n' "$*"; fails=$((fails+1)); }

  echo "=== live-pane selftest (shell mode; no allowance spent)"

  # 1. the refusals
  if ( cmd_stop "dt-something" ) >/dev/null 2>&1; then bad "stop accepted a dt- name"; else ok "stop refuses a dt- name"; fi
  if ( cmd_stop "itfleet-D-worker" ) >/dev/null 2>&1; then bad "stop accepted another section's session"; else ok "stop refuses a non-probe session"; fi
  if ( cmd_type "dt-x" "hi" ) >/dev/null 2>&1; then bad "type accepted a dt- name"; else ok "type refuses a dt- name"; fi
  if ( FLEET_ALLOW_LIVE_CLAUDE=0 cmd_start "gated" ) >/dev/null 2>&1; then
    bad "start launched a real claude without FLEET_ALLOW_LIVE_CLAUDE"
  else ok "start refuses a real claude unless the allowance is acknowledged"; fi

  # 2. the lifecycle
  local name; name="$(cmd_start selftest --shell)" || { bad "start --shell failed"; return 1; }
  case "$name" in "$PROBE_PREFIX"selftest-*) ok "the name is a probe name: $name" ;;
                  *) bad "unexpected name: $name" ;; esac
  cmd_list | grep -qx "$name" && ok "list sees it" || bad "list does not see it"

  # 3. it is NOT on the default server — the guarantee that matters most
  if tmux ls -F '#{session_name}' 2>/dev/null | grep -qx "$name"; then
    bad "THE PROBE IS ON THE DEFAULT SERVER"
  else
    ok "the probe is absent from the default server"
  fi

  # 4. type vs key are distinguishable
  cmd_type "$name" "echo probe-marker"
  sleep 0.3
  cmd_cap "$name" | grep -q "probe-marker" && ok "type puts text in the pane" || bad "type did not reach the pane"

  cmd_stop "$name"
  sleep 0.3
  cmd_list | grep -qx "$name" && bad "stop left the session behind" || ok "stop removed it"

  cmd_reap >/dev/null
  echo
  [ "$fails" = 0 ] && echo "ALL SELFTEST CHECKS HOLD" || echo "$fails CHECK(S) VIOLATED"
  return "$([ "$fails" = 0 ] && echo 0 || echo 1)"
}

case "${1:-}" in
  start)    shift; cmd_start "$@" ;;
  type)     shift; cmd_type "$@" ;;
  key)      shift; cmd_key "$@" ;;
  submit)   shift; cmd_submit "$@" ;;
  cap)      shift; cmd_cap "$@" ;;
  guard)    shift; cmd_guard "$@" ;;
  list)     cmd_list ;;
  stop)     shift; cmd_stop "$@" ;;
  reap)     cmd_reap ;;
  selftest) cmd_selftest ;;
  *) sed -n '/^# USAGE/,/^set -uo/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//;$d'; exit 2 ;;
esac
