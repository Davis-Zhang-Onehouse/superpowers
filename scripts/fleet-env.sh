# fleet-env.sh — the shell settings and helpers for working with any fleet on this box.
#
#     . /home/ubuntu/davis_root/superpowers/scripts/fleet-env.sh
#     . /home/ubuntu/davis_root/superpowers/scripts/fleet-env.sh <instants-dir>
#
# Source it; do not execute it. Nothing here is specific to an effort — the first form is enough to
# OBSERVE any fleet (`fleet-view`, `board`, `leases`, `status`, attaching to a session). Pass an
# instants directory only when you intend to CREATE instants there (`init`, `dispatch`).
#
# Why observation needs no instants directory: a dispatch record stores an ABSOLUTE `child_instant`, and
# `reconcile` re-resolves it through the stable key so it follows the worker's own rename. `FLEET_INSTANTS`
# is where NEW instants get made, not where existing ones are found.
#
# Each setting is defaulted, never forced, so an effort that wants a different store just exports it first.

# The record + pool store. Box-wide on purpose: the pool is ws1..ws6, a shared resource, and the watchdog
# reads the same store to decide which finished workers to stop auto-resuming. `fleet`'s read-only verbs
# already default here; it is stated anyway because a WRITE with no store named is refused outright, and
# "no default for a write" is much easier to live with when the read path and the write path agree.
# shellcheck shell=bash
export FLEET_HOME="${FLEET_HOME:-$HOME/.fleet}"

# The tmux SERVER dispatched sessions live on. Not the default server, deliberately:
#   * `close`/`harvest`/`abort` kill sessions BY NAME, and on the default server that name resolves
#     alongside other people's live work. A private server bounds the blast radius.
#   * a tmux session inherits the environment of the SERVER, not of the process asking for the session, so
#     a long-lived default server hands new sessions whatever environment it was started with. On this box
#     that put a dispatched coordinator under another operator's Claude account.
# Attaching still works, it just needs the flag:  tmux -L "$FLEET_TMUX_SOCKET" attach -t dt-<name>
export FLEET_TMUX_SOCKET="${FLEET_TMUX_SOCKET:-fleet}"

# The release area. `current` is a symlink to the deployed export — or to the git checkout itself in dev
# mode (`fleet release-deploy --dev`), which is the same one mechanism rather than a second one.
export FLEET_RELEASES="${FLEET_RELEASES:-/home/ubuntu/davis_root/fleet-releases}"

# Through `current`, never the checkout directly: that pointer IS the deployment, and a shell that
# bypassed it would run a different version from every other shell on this box — which is the whole
# problem the release pipeline exists to fix. Falls back to the checkout when no release area has been
# created yet, so a fresh clone still has a working `fleet`.
_fleet_bin="$FLEET_RELEASES/current/bin"
[ -d "$_fleet_bin" ] || _fleet_bin="/home/ubuntu/davis_root/superpowers/bin"
case ":$PATH:" in
  *":$_fleet_bin:"*) ;;
  *) export PATH="$_fleet_bin:$PATH" ;;
esac
unset _fleet_bin

# Only when you are going to create instants. An argument, so no effort's path is baked into this file.
#
# It must be a real directory, and that check is not pedantry. This file is designed to be sourced from a
# shell rc -- and on this box that rc sources it from INSIDE a function (`_load_davis_root_env`), where
# `$1` belongs to the function, not to the person sourcing. A stray positional would otherwise silently
# point FLEET_INSTANTS at nonsense, and the first symptom would be `init` creating an instant somewhere
# nobody looks. A non-directory argument is reported rather than ignored: a typo'd path the tool quietly
# discards is the same bug one step later.
if [ -n "${1:-}" ]; then
  if [ -d "$1" ]; then
    export FLEET_INSTANTS="$1"
  else
    echo "fleet-env.sh: '$1' is not a directory; FLEET_INSTANTS left as ${FLEET_INSTANTS:-unset}" >&2
  fi
fi

# --- helpers -----------------------------------------------------------------------------------------

# The CURRENT instant folder for a subject id. Use this instead of globbing an instants directory: an
# aborted run leaves `...-abort-append-<name>` beside `...-inflight-append-<name>`, and it sorts FIRST, so
# a glob hands you the dead one and every `--instant` read after it describes the wrong folder.
fleet_instant() {
  [ -n "${1:-}" ] || { echo "usage: fleet_instant <subject-id>" >&2; return 2; }
  fleet status --id "$1" --porcelain 2>/dev/null | awk -F'\t' '$1=="evidence.instant"{print $2}'
}

# Every running subject: "<id>\t<slot>".
fleet_running() {
  fleet board --porcelain 2>/dev/null | awk -F'\t' '$3=="RUNNING"{print $1"\t"$5}'
}

# Read a pane WITHOUT attaching. The trailing colon on the target is required: `-t '=name'` returns an
# EMPTY string for a session that exists, so a check written without it passes vacuously.
fleet_peek() {
  [ -n "${1:-}" ] || { echo "usage: fleet_peek <session> [lines]" >&2; return 2; }
  tmux -L "${FLEET_TMUX_SOCKET:-fleet}" capture-pane -p -t "=$1:" | grep -v '^$' | tail -"${2:-30}"
}

# Attach to a dispatched session without having to remember the -L.
fleet_attach() {
  [ -n "${1:-}" ] || { tmux -L "${FLEET_TMUX_SOCKET:-fleet}" ls; return 0; }
  tmux -L "${FLEET_TMUX_SOCKET:-fleet}" attach -t "=$1"
}

# `fv` is a convenience for interactive shells only; scripts should call `fleet-view` directly, since an
# alias does not exist in a non-interactive shell.
alias fv='fleet-view' 2>/dev/null || true
