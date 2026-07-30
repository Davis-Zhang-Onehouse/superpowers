#!/usr/bin/env bash
# SOURCE this before probing `fleet` by hand.  `SI-28`.
#
# Why it exists. `fleet dispatch` starts a REAL `claude` in a REAL tmux session named `dt-<name>`, on
# whatever server the environment points at. Run from a bare shell with no `FLEET_TMUX_SOCKET`, that is the
# LIVE server — and a `dt-` session on the live server is the one thing the operator's seed forbids
# outright, because a live ANSI coordinator was attached to `dt-ansiFinalCompactionAndCloseout`.
#
# I did exactly that while hand-testing `SI-27`: `dt-probec` appeared on the live server with a live claude
# inside it. Attribution was unambiguous (one pane, one pid, cwd in a scratchpad directory created two
# minutes earlier) and it was killed within a minute, but the point is that nothing stopped it.
#
# `SD-1` had already built the seam that prevents this — the tmux socket is a parameter, and `it_section`
# sets `FLEET_TMUX_SOCKET` for every IT section. The gap was never the product; it was that the harness is
# safe and a bare shell is not, so the protection applied to written tests and not to the ad-hoc probing
# that precedes them. A rule I have to remember is worth less than a file I can source, which is the north
# star's "prefer a mechanical fix to a documented warning" pointed at my own workflow.
#
# Usage:
#   . evidence/04-integration/bin/adhoc-sandbox.sh            # a fresh scratch store + private server
#   . evidence/04-integration/bin/adhoc-sandbox.sh keep        # reuse the previous one
#
# It exports FLEET_HOME, FLEET_INSTANTS, FLEET_TMUX_SOCKET and PYTHONPATH, and prints what it set.
# It deliberately does NOT cd anywhere and does not touch the live store or the live server.

# Locating THIS file when sourced, in either shell. `BASH_SOURCE` is empty under zsh, which is the operator's
# login shell — and an empty value made `dirname` return `.`, so the first version of this script silently
# resolved the repo root from the caller's cwd and exported a PYTHONPATH that did not contain `fleet`. That is
# `FI-34` again, one directory over: a helper that resolves its own location from the caller's position works
# from exactly one directory. The zsh form is behind `eval` because bash cannot parse `${(%):-%x}` at all.
_adhoc_self=""
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  _adhoc_self="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then
  eval '_adhoc_self="${(%):-%x}"'
fi
[ -n "$_adhoc_self" ] || _adhoc_self="$0"
_adhoc_root="$(cd "$(dirname "$_adhoc_self")/../.." && pwd)"

# The scratchpad, never the instant: this is throwaway state and `P-3` lints evidence paths for `/tmp`
# precisely so throwaway state never gets cited as evidence.
_adhoc_base="${TMPDIR:-/tmp}/fleet-adhoc-$$"
if [ "${1:-}" = "keep" ] && [ -n "${FLEET_ADHOC_BASE:-}" ]; then
  _adhoc_base="$FLEET_ADHOC_BASE"
else
  rm -rf "$_adhoc_base"
fi
mkdir -p "$_adhoc_base/home" "$_adhoc_base/instants" "$_adhoc_base/slots"

export FLEET_ADHOC_BASE="$_adhoc_base"
export FLEET_HOME="$_adhoc_base/home"
export FLEET_INSTANTS="$_adhoc_base/instants"
#: THE line that matters. A private server, named for the shell that made it, so a `dt-` session created by
#: a hand-run dispatch cannot land where the operator's coordinator lives — and cannot be seen from there.
export FLEET_TMUX_SOCKET="itfleet-adhoc-$$"
export PYTHONPATH="$_adhoc_root/src"

printf 'ad-hoc fleet sandbox\n'
printf '  FLEET_HOME         %s\n' "$FLEET_HOME"
printf '  FLEET_INSTANTS     %s\n' "$FLEET_INSTANTS"
printf '  FLEET_TMUX_SOCKET  %s   <- dispatch lands HERE, not on the live server\n' "$FLEET_TMUX_SOCKET"
printf '  PYTHONPATH         %s\n' "$PYTHONPATH"
printf 'tear down with:  tmux -L %s kill-server 2>/dev/null; rm -rf %s\n' \
  "$FLEET_TMUX_SOCKET" "$_adhoc_base"

unset _adhoc_root _adhoc_base _adhoc_self
