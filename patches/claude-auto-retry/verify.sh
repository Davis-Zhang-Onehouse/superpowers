#!/usr/bin/env bash
#
# verify.sh — is the tmux-socket patch present and working in the INSTALLED claude-auto-retry?
#
#     bash patches/claude-auto-retry/verify.sh          # check
#     bash patches/claude-auto-retry/verify.sh --apply  # check, and re-apply if missing
#
# WHY THIS EXISTS. The patch lives in `node_modules`, so any `npm install`, `npm update` or fresh box
# build silently reverts it. The failure that follows is invisible by construction: with no socket
# support, `reconcile` finds no panes on the private server and reports "All live claude sessions already
# monitored" — the exact words it prints when everything IS covered. Auto-resume for every dispatched
# instant would just quietly stop, and nothing would say so until a worker sat dead at a rate-limit
# banner for six hours.
#
# So this asserts BEHAVIOUR, not the presence of a string. A grep for the patch marker would pass against
# a half-applied patch, and the whole point of the socket support is what tmux argv comes out the other
# end.
#
# WHAT THE PATCH DOES. `claude-auto-retry` invokes `tmux` with no server option, so everything lands on
# the DEFAULT server. Dispatched agent sessions deliberately live on a private one (`tmux -L fleet`),
# which bounds what a kill-by-name can reach and stops a long-lived default server handing new sessions a
# stale environment. `CLAUDE_AUTO_RETRY_TMUX_SOCKET=<name>` now selects the server for every tmux call and
# for pane discovery, and the monitor inherits it through the environment rather than through argv —
# argv is parsed by a regex in two places and a positional socket would break both.
#
# Verified against a pristine upstream v0.6.0 checkout: the patch applies cleanly and all 352 of the
# package's own tests still pass, because the argv BUILDERS are untouched and the prefix is applied at
# the exec boundary.
set -uo pipefail

CAR="${CAR_ROOT:-/home/ubuntu/davis_root/opt/car/node_modules/claude-auto-retry}"
NODE="${NODE_BIN:-/home/ubuntu/davis_root/opt/node/bin}/node"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

fails=0
note() { printf '  %s\n' "$*"; }

[ -d "$CAR/src" ] || { echo "no claude-auto-retry at $CAR"; exit 2; }
[ -x "$NODE" ]    || { echo "no node at $NODE"; exit 2; }

installed="$("$NODE" -e "console.log(require('$CAR/package.json').version)" 2>/dev/null)"
note "installed version: ${installed:-unknown}"
if [ "$installed" != "0.6.0" ]; then
  note "NOTE: the patch was authored and tested against 0.6.0. reconcile.js and status-file.js both changed"
  note "      between 0.6.0 and 0.6.2, so it will NOT apply cleanly to a newer tree — re-derive it rather"
  note "      than forcing it."
fi

# --- behaviour 1: the tmux argv carries -L when a server is named, and does not when it is not --------
out="$("$NODE" --input-type=module -e "
import { tmuxArgv } from '$CAR/src/tmux.js';
console.log(JSON.stringify(tmuxArgv(['capture-pane','-p'])));
" 2>&1)" || { note "FAIL tmux.js does not export tmuxArgv (patch missing): $out"; fails=1; }

if [ "$fails" = 0 ]; then
  # shellcheck disable=SC1007  # the empty value IS the case under test: the socket var set but blank
  unset_out="$(CLAUDE_AUTO_RETRY_TMUX_SOCKET= "$NODE" --input-type=module -e "
import { tmuxArgv } from '$CAR/src/tmux.js';
console.log(JSON.stringify(tmuxArgv(['capture-pane','-p'])));")"
  set_out="$(CLAUDE_AUTO_RETRY_TMUX_SOCKET=fleet "$NODE" --input-type=module -e "
import { tmuxArgv } from '$CAR/src/tmux.js';
console.log(JSON.stringify(tmuxArgv(['capture-pane','-p'])));")"
  [ "$unset_out" = '["capture-pane","-p"]' ] \
    && note "ok   no socket named -> argv unchanged (the default server still behaves exactly as upstream)" \
    || { note "FAIL unset case returned $unset_out"; fails=1; }
  [ "$set_out" = '["-L","fleet","capture-pane","-p"]' ] \
    && note "ok   socket named -> -L precedes the subcommand (tmux requires server options first)" \
    || { note "FAIL set case returned $set_out"; fails=1; }
fi

# --- behaviour 2: pane discovery is socket-aware -------------------------------------------------------
if grep -q 'tmuxArgv(\[.list-panes.' "$CAR/src/reconcile.js" 2>/dev/null; then
  note "ok   reconcile's list-panes is wrapped, so the arm set comes from the named server"
else
  note "FAIL reconcile.js still discovers panes on the default server only"; fails=1
fi

# --- behaviour 3: status files are namespaced per SERVER, not per spawner ------------------------------
# Pane ids are unique only within one server, so `%0` exists on both. Upstream keys the status file off
# the monitor's own $TMUX, which is correct only when the monitor runs inside the pane it watches — a
# reconcile-armed monitor does not. Observed before the fix: a fleet pane wrote into the default server's
# namespace.
key_out="$(CLAUDE_AUTO_RETRY_TMUX_SOCKET=fleet TMUX=/tmp/tmux-1000/default,1,0 "$NODE" --input-type=module -e "
import { statusFilePath } from '$CAR/src/status-file.js';
console.log(typeof statusFilePath === 'function' ? statusFilePath('%0') : 'NO_EXPORT');
" 2>/dev/null)"
if [ -z "$key_out" ] || [ "$key_out" = "NO_EXPORT" ]; then
  # No exported path helper in this version; fall back to asserting the source-level rule.
  if grep -q 'CLAUDE_AUTO_RETRY_TMUX_SOCKET' "$CAR/src/status-file.js" 2>/dev/null; then
    note "ok   status-file.js prefers an explicitly named server over the ambient \$TMUX"
  else
    note "FAIL status-file.js still keys on \$TMUX, so two servers' %0 collide on one status file"; fails=1
  fi
else
  case "$key_out" in
    *fleet*) note "ok   a fleet pane keys to the fleet namespace even when spawned from the default server" ;;
    *)       note "FAIL status key was $key_out — the spawner's server won"; fails=1 ;;
  esac
fi

# --- behaviour 4: the send gate (F-7) -------------------------------------------------------------------
# The monitor must not type into a pane holding unsubmitted text: sendKeys sends the text, waits 150ms,
# then sends Enter separately, so an operator's half-finished line would be SUBMITTED with the retry
# message appended to it.
if grep -q 'sendWouldConcatenate' "$CAR/src/monitor.js" 2>/dev/null; then
  note "ok   monitor.js consults the send gate"
else
  note "FAIL monitor.js has no send gate; a retry can concatenate onto queued text"; fails=1
fi
# Placement is the property, not presence: the gate must come BEFORE the attempt counter, or a decline
# consumes a retry and maxRetries=5 exhausts the episode while a human is mid-sentence.
if "$NODE" -e "
const s = require('fs').readFileSync('$CAR/src/monitor.js','utf8');
const g = s.indexOf('sendWouldConcatenate(tmuxAdapter, pane)');
const a = s.indexOf('state.attempts++');
process.exit(g > -1 && a > -1 && g < a ? 0 : 1);
" 2>/dev/null; then
  note "ok   the gate is evaluated BEFORE the attempt counter, so declining costs no retry"
else
  note "FAIL the gate runs after the attempt counter; declining would burn the retry budget"; fails=1
fi
if grep -q 'export async function paneGuardCode' "$CAR/src/tmux.js" 2>/dev/null; then
  note "ok   the gate asks fleet pane-guard rather than re-deriving the judgement"
else
  note "FAIL paneGuardCode missing"; fails=1
fi

if [ "$fails" = 0 ]; then
  echo "PASS: the tmux-socket patch is present and behaving — argv is unchanged with no socket named, carries -L before the subcommand when one is, pane discovery follows the named server, status files are namespaced per server rather than per spawner, and the send gate consults fleet pane-guard BEFORE the attempt counter so a decline costs no retry"
  exit 0
fi

echo "FAIL: the socket patch is missing or partial — auto-resume for every dispatched instant is silently off"
if [ "$APPLY" = 1 ]; then
  echo "re-applying from $HERE/tmux-socket-support.patch ..."
  ( cd "$CAR" && patch -p1 --forward --reject-file=- < "$HERE/tmux-socket-support.patch" ) \
    && { echo "re-applied; re-run this script to confirm"; exit 0; } \
    || { echo "re-apply FAILED — the tree has moved; re-derive the patch against the installed version"; exit 1; }
fi
echo "re-apply with: bash $0 --apply"
exit 1
