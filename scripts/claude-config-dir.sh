#!/usr/bin/env bash
#
# claude-config-dir.sh — which operator's `.claude` config directory owns a given directory.
#
#     claude-config-dir.sh /home/ubuntu/davis_root/ws3
#     -> /home/ubuntu/davis_root/.claude
#
# WHY THIS IS AN EXECUTABLE AND NOT A SHELL FUNCTION, which is the whole point:
#
# This box multiplexes several people's Claude accounts by cwd. The mapping lives in
# `/home/ubuntu/.claude-owners.tsv` (`<root>\t<email>`), and it was enforced by a `claude()` **zsh
# function** in `~/.zshrc` that sets `CLAUDE_CONFIG_DIR` from `$PWD` before calling the real binary.
#
# A shell function only exists in an INTERACTIVE zsh that sourced `.zshrc`. Measured:
#
#     zsh -c  'type claude'  ->  claude is /home/ubuntu/.local/bin/claude   (the guard is ABSENT)
#     zsh -ic 'type claude'  ->  claude is a shell function from ~/.zshrc
#
# `tmux new-session -d -s <s> -c <cwd> claude` runs the first shape. So every AUTOMATED path — a
# dispatch, a cron, a script, anything not a human at a prompt — bypassed the guard entirely and
# inherited `CLAUDE_CONFIG_DIR` from whatever started the tmux SERVER, which on a long-lived server is
# whoever happened to open it first, possibly weeks ago and possibly a different person.
#
# That is not a cosmetic slip. On 2026-07-31 a coordinator dispatched into `/home/ubuntu/davis_root/ws3`
# came up under `/home/ubuntu/chinmay_root/.claude`: another operator's credentials, settings, plugins and
# project-trust list, and it wrote its own trust decision into that person's config. The pane said
# "Welcome back Chinmay!" while doing davis's work.
#
# So the mapping is an executable, callable from any shell, any script, any non-interactive context — and
# the function and the automation can now share ONE implementation instead of two that drift.
#
# Longest-prefix wins, matching the zsh function's rule exactly: `/home/ubuntu/davis_root/ws3` is under
# `/home/ubuntu/davis_root`, and if a longer registered root also matched it would take precedence.
#
# Exit 0 and print the directory when a root owns the path. Exit 1 and print NOTHING on stdout when none
# does — a caller must be able to tell "unowned" from "owned by X" without parsing prose, because the
# safe reaction to "unowned" is to refuse, not to guess.
set -uo pipefail

MAP="${CLAUDE_OWNERS_MAP:-/home/ubuntu/.claude-owners.tsv}"

usage() { echo "usage: $(basename "$0") [--email] <directory>" >&2; }

# `--email` prints the owner's address instead of the config dir. Both facts come from the SAME row of the
# SAME map, which is the point: CLAUDE_CONFIG_DIR and CLAUDE_OWNER_EMAIL are two halves of one identity, and
# pinning one while letting the other be inherited is how a session ends up half-attributed.
WANT=dir
case "${1:-}" in
  --email) WANT=email; shift ;;
esac

case "${1:-}" in
  ""|--help|-h) usage; exit 2 ;;
esac

target="$1"
# Resolve so `..`, a symlink or a trailing slash cannot defeat the prefix test. A path that does not
# exist yet is still resolvable with -m, which matters because a caller may ask about a slot it is
# about to create.
target="$(readlink -m "$target" 2>/dev/null || printf '%s' "$target")"

[ -r "$MAP" ] || { echo "$(basename "$0"): no readable owners map at $MAP" >&2; exit 1; }

best=""; best_email=""
while IFS=$'\t' read -r root email; do
  [ -z "${root:-}" ] && continue
  case "$root" in \#*) continue ;; esac                 # allow comments in the map
  root="${root%/}"
  case "$target/" in
    "$root"/*) [ "${#root}" -gt "${#best}" ] && { best="$root"; best_email="$email"; } ;;
  esac
done < "$MAP"

if [ -z "$best" ]; then
  echo "$(basename "$0"): no root in $MAP owns $target" >&2
  exit 1
fi
if [ "$WANT" = email ]; then
  printf '%s\n' "$best_email"
else
  printf '%s/.claude\n' "$best"
fi
exit 0
