#!/usr/bin/env bash
# Run: bash fleet/it/run-TE.sh
#
# §TE — B26: AN EMPTY OR EXITING TMUX SERVER IS AN EMPTY POPULATION, NOT A DEAD FLEET.
#
# `session.pane_owners` read `list-panes -a` and allowed exactly two stderr shapes to mean "no pane here".
# Two more server states hold no pane and used to kill `board`, `status`, `dispatch`, `harvest`'s tail and
# `bin/fleet-view` with `FleetError: Cannot inspect tmux server: …`. Both were hit live, both reproduced here
# on this section's PRIVATE server, tmux 3.2a:
#
#   A  alive, ZERO sessions — `list-panes -a` answers `no current target`. Built with `exit-empty off`; the
#      live cause was a stopped `tmux attach` client outliving its session.
#   B  exiting but held — a SIGSTOPped attached client, then `kill-server`: the server stays, waiting for the
#      client, and every command answers `server exited unexpectedly`.
#
# TE1-TE3 prove A reads as empty AND is usable (a real dispatch starts a session on it, and the record reads
# once that session is gone); TE4-TE5 prove B reads as empty and that a dispatch onto it is refused WITH A
# ROUTE; TE6 is the control that the fixtures are the states they claim to be.
set -uo pipefail
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck disable=SC1091
. "$IT_ROOT/lib.sh"
RESULTS="${IT_RESULTS:-$IT_ROOT/RESULTS-TE.tsv}"
[ -f "$RESULTS" ] || printf 'case\tverdict\tevidence\tnote\n' > "$RESULTS"
it_own_cases 'TE[0-9]+|ISOLATION-TE-(enter|leave)'
IT_FAILED=0

it_section TE
it_fresh_store
export FLEET_INSTANTS="$EV/instants"; rm -rf "$FLEET_INSTANTS"; mkdir -p "$FLEET_INSTANTS"
OUT="$EV/out"; rm -rf "$OUT"; mkdir -p "$OUT"
CLIENT_PID=""
# The stopped client is OURS, killed by the pid we captured — never by a pattern, which would match this shell.
te_cleanup() {
  if [ -n "$CLIENT_PID" ]; then kill -CONT "$CLIENT_PID" 2>/dev/null; kill "$CLIENT_PID" 2>/dev/null; fi
  tmux -L "$IT_TMUX_SOCKET" kill-server 2>/dev/null
  exec 9>&- 2>/dev/null
  # A server that exits by kill-server leaves its socket file behind, and every stale file costs each later
  # `session_servers` probe one `has-session`. Ours only.
  rm -f "${TMUX_TMPDIR:-/tmp}/tmux-$(id -u)/$IT_TMUX_SOCKET"
}
trap te_cleanup EXIT
bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2
PATH="$IT_ROOT/bin:$PATH"; export PATH          # the stand-in `claude`: a dispatch here launches no model

# A store with one enrolled slot and a coordinator whose READY milestones the dispatches take.
COORD="$(fleet init --base 00000000 --name "coordte$$" --porcelain 2>"$OUT/init.err" | awk -F'\t' '$1=="path"{print $2; exit}')"
cp -r "$INSTANT/tests/fixtures/profiles/workerCompliant" "$OUT/profile"
for sl in slot slot2; do
  ( mkdir -p "$OUT/$sl" && cd "$OUT/$sl" && git init -q . && git commit -q --allow-empty -m base ) >/dev/null 2>&1
done
{ fleet milestone --instant "$COORD" --id te1 --title "dispatch onto an empty server" --porcelain &&
  fleet milestone --instant "$COORD" --id te2 --title "dispatch onto an exiting server" --porcelain &&
  fleet set-golden --path "$OUT/slot" --porcelain && fleet enroll --slot "$OUT/slot" --porcelain &&
  fleet enroll --slot "$OUT/slot2" --porcelain
} > "$OUT/setup.out" 2>&1 || { echo "setup failed; nothing below is a verdict (see $OUT/setup.out)" >&2; exit 2; }

observe() {                      # observe <tag> [status-id] -> board (+ status), rc captured before anything else runs
  fleet board > "$OUT/$1-board.out" 2>&1; echo "$?" > "$OUT/$1-board.rc"
  if [ -n "${2:-}" ]; then fleet status --id "$2" > "$OUT/$1-status.out" 2>&1; echo "$?" > "$OUT/$1-status.rc"; fi
}

# ---- state A -----------------------------------------------------------------------------------------------
printf 'set -g exit-empty off\n' > "$OUT/empty.conf"
it_tmux -f "$OUT/empty.conf" new-session -d -s itfleet-TE-x 'sleep 600'
it_tmux kill-session -t =itfleet-TE-x
it_tmux list-panes -a > "$OUT/A-list-panes.out" 2>&1; a_lp=$?
it_tmux list-sessions > "$OUT/A-list-sessions.out" 2>&1; a_ls=$?
observe A
if [ "$(cat "$OUT/A-board.rc")" = 0 ] && ! grep -q 'Cannot inspect tmux' "$OUT/A-board.out"; then
  it_pass TE1 "fleet/it/TE/out/A-board.out" 'board reads a live server with zero sessions as an empty population'
else it_fail TE1 "fleet/it/TE/out/A-board.out" "board rc=$(cat "$OUT/A-board.rc") on an empty live server"; fi

fleet dispatch --profile "$OUT/profile" --title "teWorkerA" --base 00000000 --optype append \
      --from "$COORD" --milestone te1 --porcelain > "$OUT/A-dispatch.out" 2>&1; a_d=$?
it_tmux list-sessions -F '#{session_name}' > "$OUT/A-sessions-after.out" 2>&1
if [ "$a_d" = 0 ] && [ -s "$OUT/A-sessions-after.out" ]; then
  it_pass TE2 "fleet/it/TE/out/A-dispatch.out" 'dispatch onto the empty live server succeeds and its session is on that server'
else it_fail TE2 "fleet/it/TE/out/A-dispatch.out" "dispatch rc=$a_d on the empty live server"; fi
A_ID="teworkera"                 # the record identity is `<slug>-<stamp>`; status takes a unique substring

# The worker's session goes away under a live server: back to state A, now with a RECORD whose session is gone.
for s in $(it_tmux list-sessions -F '#{session_name}' 2>/dev/null); do it_tmux kill-session -t "=$s"; done
observe A2 "$A_ID"
if [ "$(cat "$OUT/A2-board.rc")" = 0 ] && [ "$(cat "$OUT/A2-status.rc")" = 0 ]; then
  it_pass TE3 "fleet/it/TE/out/A2-status.out" 'board and status of a dispatched record read an emptied live server'
else it_fail TE3 "fleet/it/TE/out/A2-status.out" "board rc=$(cat "$OUT/A2-board.rc") status rc=$(cat "$OUT/A2-status.rc")"; fi

# ---- state B -----------------------------------------------------------------------------------------------
# On the SAME server: attach a client, stop it, end the sessions, kill the server. `script` gives the client
# the pty tmux insists on.
if ! command -v script >/dev/null 2>&1; then
  it_skip TE4 "" 'util-linux `script` is not installed, so no client can be attached to hold the server'
  it_skip TE5 "" 'same: state B cannot be built without an attached client'
else
  it_tmux new-session -d -s itfleet-TE-y 'sleep 600'
  # stdin is a FIFO this shell holds open: /dev/zero floods the pane and /dev/null ends `script` at EOF.
  # `script` runs its command with $SHELL, and zsh expands a leading `=word` as a command path, so the
  # shell is named. $TMUX is unset because an attach from inside a tmux pane is refused as nesting.
  mkfifo "$OUT/client.in"; exec 9<>"$OUT/client.in"
  env -u TMUX SHELL=/bin/sh setsid script -qfc "tmux -L $IT_TMUX_SOCKET attach -t =itfleet-TE-y" /dev/null \
      < "$OUT/client.in" > "$OUT/B-client.tty" 2>&1 &
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    CLIENT_PID="$(it_tmux list-clients -F '#{client_pid}' 2>/dev/null | head -1)"; [ -n "$CLIENT_PID" ] && break; sleep 0.5
  done
  echo "client pid: ${CLIENT_PID:-NONE}" > "$OUT/B-client.out"
  [ -n "$CLIENT_PID" ] && kill -STOP "$CLIENT_PID"
  it_tmux kill-session -t =itfleet-TE-y
  it_tmux kill-server
  sleep 1
  it_tmux list-panes -a > "$OUT/B-list-panes.out" 2>&1; b_lp=$?
  observe B "$A_ID"
  if [ "$(cat "$OUT/B-board.rc")" = 0 ] && [ "$(cat "$OUT/B-status.rc")" = 0 ]; then
    it_pass TE4 "fleet/it/TE/out/B-board.out" 'board and status read an exiting server held by a stopped client as empty'
  else it_fail TE4 "fleet/it/TE/out/B-board.out" "board rc=$(cat "$OUT/B-board.rc") status rc=$(cat "$OUT/B-status.rc")"; fi
  fleet leases --porcelain > "$OUT/B-leases-before.out" 2>&1
  fleet dispatch --profile "$OUT/profile" --title "teWorkerB" --base 00000000 --optype append \
        --from "$COORD" --milestone te2 --cap 5 --porcelain > "$OUT/B-dispatch.out" 2>&1; b_d=$?
  fleet leases --porcelain > "$OUT/B-leases-after.out" 2>&1
  if [ "$b_d" != 0 ] && grep -q 'clears when:' "$OUT/B-dispatch.out" && grep -q 'ps -o pid,stat,args -C tmux' "$OUT/B-dispatch.out"; then
    it_pass TE5 "fleet/it/TE/out/B-dispatch.out" "dispatch onto the exiting server is refused (rc=$b_d) and names the route"
  else it_fail TE5 "fleet/it/TE/out/B-dispatch.out" "dispatch rc=$b_d without a route"; fi
fi

# ---- TE6: the fixtures are the states they claim, or every verdict above is about something else ----------
if [ "$a_lp" = 1 ] && grep -qx 'no current target' "$OUT/A-list-panes.out" && [ "$a_ls" = 0 ] &&
   { [ ! -f "$OUT/B-list-panes.out" ] || grep -qx 'server exited unexpectedly' "$OUT/B-list-panes.out"; }; then
  it_pass TE6 "fleet/it/TE/out/A-list-panes.out" 'fixture control: A answers `no current target` with list-sessions rc=0; B answers `server exited unexpectedly`'
else it_fail TE6 "fleet/it/TE/out/A-list-panes.out" 'the fixture did not build the claimed server state'; fi

te_cleanup; CLIENT_PID=""
it_assert_isolation TE-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || exit 3
exit "$IT_FAILED"
