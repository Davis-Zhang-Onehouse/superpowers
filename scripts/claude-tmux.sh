#!/usr/bin/env bash
# claude-tmux.sh — launch claude inside a fresh tmux session so the davis_root
# auto-resume watchdog (scripts/claude-watchdog.sh) can arm it. The watchdog
# needs a tmux pane to scrape the limit banner and send-keys the resume; a claude
# started in a plain terminal can never be armed.
#
# claude is run through an INTERACTIVE login shell (zsh -i -c) so your existing
# ~/.zshrc `claude()` wrapper still applies — i.e. CLAUDE_CONFIG_DIR is still set
# per working directory exactly as when you run `claude` by hand.
#
# Behavior:
#   - Not in tmux: create a new tmux session (named claude-<dir>-<pid>), starting
#     in the current directory, and attach to it running claude.
#   - Already in tmux: just run claude here (already armable) — still via zsh -i
#     so the wrapper applies.
#
# Usage:  scripts/claude-tmux.sh [any claude args...]
#   e.g.  scripts/claude-tmux.sh
#         scripts/claude-tmux.sh --model opus
# Set CLAUDE_TMUX_DRYRUN=1 to print what would run instead of running it.
set -u

command -v zsh  >/dev/null 2>&1 || { echo "claude-tmux: zsh not found (needed to load your claude() wrapper)" >&2; exit 1; }
command -v tmux >/dev/null 2>&1 || { echo "claude-tmux: tmux not found" >&2; exit 1; }

start_dir="$PWD"

# Build a safely-quoted `claude <args>` command line for re-parsing by a shell.
cmd="claude"
for a in "$@"; do
  cmd+=" $(printf '%q' "$a")"
done

# Run claude via an interactive zsh so ~/.zshrc (and thus claude()) is sourced.
inner="zsh -i -c $(printf '%q' "$cmd")"

run() {  # run or, in dry-run mode, just print
  if [ -n "${CLAUDE_TMUX_DRYRUN:-}" ]; then
    printf 'DRYRUN: %s\n' "$*"
    return 0
  fi
  exec "$@"
}

if [ -n "${TMUX:-}" ]; then
  # Already inside tmux — armable already; just run claude here (wrapper applies).
  run zsh -i -c "$cmd"
fi

# Not in tmux: fresh session, current dir, attached. tmux session names may not
# contain '.' or ':', so sanitize the folder name.
safe_dir="$(basename "$start_dir")"
safe_dir="${safe_dir//[^A-Za-z0-9_-]/-}"
session="claude-${safe_dir}-$$"
run tmux new-session -s "$session" -c "$start_dir" "$inner"
