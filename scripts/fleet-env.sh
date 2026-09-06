# fleet-env.sh — the shell settings and helpers for working with any fleet on this box.
#
#     . "$HOME/<root>/superpowers/scripts/fleet-env.sh"
#     . "$HOME/<root>/superpowers/scripts/fleet-env.sh" <instants-dir>
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

# Sourced, never executed, so there is no shebang to declare the dialect — say it for shellcheck.
# shellcheck shell=bash

# --- which fleet is this? ---------------------------------------------------------------------------
#
# A fleet is a property of a DIRECTORY. Walk up from $PWD to a `.fleet-root` marker, exactly as `fleet`
# itself does, and derive the store, the release area and the tmux server from it. Two roots under $HOME
# then share nothing: not a record, not a slot, not a server, not a release.
#
# Every setting below is a DEFAULT, never a force (`${VAR:-...}`): an effort that exports its own wins,
# which is what 1291 explicit call sites across the suites depend on.
#
# The walk stops BELOW $HOME. A marker there would make every root the same root while looking exactly
# like this working — the worst of the two failures available.
#
# Duplicated from `fleet.root` in shell ON PURPOSE. This file is sourced by a shell rc, so it must set
# PATH before `fleet` is runnable, and asking `fleet` where it would write would make the answer depend on
# the thing being configured. The duplication is bounded to the walk, and `scripts/tests/
# fleet-env-derives-root.sh` asserts both implementations agree.
_fleet_root=""
_fleet_d="$(pwd -P 2>/dev/null || pwd)"
while [ -n "$_fleet_d" ] && [ "$_fleet_d" != "/" ] && [ "$_fleet_d" != "$HOME" ]; do
  if [ -f "$_fleet_d/.fleet-root" ]; then _fleet_root="$_fleet_d"; break; fi
  _fleet_d="$(dirname "$_fleet_d")"
done
unset _fleet_d

if [ -n "$_fleet_root" ]; then
  # The declared name, not one slugified from the directory. `FI-421`: a fix for a dead path constant
  # shipped WITH a silent fallback because it derived a name, and the harness's own `_`->`-` mapping made
  # two spellings of one root diverge without a word. python3 rather than a sed, because the marker is
  # JSON and a regex over JSON is a second parser nobody maintains.
  _fleet_name="$(python3 -c 'import json,sys
try:
    print((json.load(open(sys.argv[1])).get("name") or "").strip())
except Exception:
    pass' "$_fleet_root/.fleet-root" 2>/dev/null)"

  if [ -n "$_fleet_name" ]; then
    # The record + pool store for THIS root.
    export FLEET_HOME="${FLEET_HOME:-$_fleet_root/.fleet}"

    # The tmux SERVER this root's sessions live on. Not the default server and not a shared one:
    #   * `close`/`harvest`/`abort` kill sessions BY NAME, so on a shared server that name resolves
    #     alongside another root's live work — and the loser dies with no diagnostic.
    #   * a tmux session inherits the environment of the SERVER, not of the process asking for the
    #     session, so a long-lived server hands new sessions whatever it was started with. On this box
    #     that once put a dispatched coordinator under another operator's Claude account.
    # Attaching still works, it just needs the flag:  tmux -L "$FLEET_TMUX_SOCKET" attach -t dt-<name>
    export FLEET_TMUX_SOCKET="${FLEET_TMUX_SOCKET:-fleet-$_fleet_name}"

    # The release area. `current` is a symlink to the deployed export — or to the git checkout itself in
    # dev mode (`fleet release-deploy --dev`), which is the same one mechanism rather than a second one.
    export FLEET_RELEASES="${FLEET_RELEASES:-$_fleet_root/fleet-releases}"

    # Through `current`, never a checkout directly: that pointer IS the deployment, and a shell that
    # bypassed it would run a different version from every other shell in this root — the whole problem
    # the release pipeline exists to fix. Falls back to the root's own superpowers checkout when no
    # release area has been created yet, so a fresh clone still has a working `fleet`.
    _fleet_bin="$FLEET_RELEASES/current/bin"
    [ -d "$_fleet_bin" ] || _fleet_bin="$_fleet_root/superpowers/bin"
    if [ -d "$_fleet_bin" ]; then
      case ":$PATH:" in
        *":$_fleet_bin:"*) ;;
        *) export PATH="$_fleet_bin:$PATH" ;;
      esac
    fi
    unset _fleet_bin
  else
    echo "fleet-env.sh: $_fleet_root/.fleet-root declares no name; nothing was set." >&2
  fi
else
  # SILENCE WOULD BE THE DEFECT. Exporting nothing is correct — there is no root here, and a default is
  # how a shell reaches another root's store — but a shell that is told nothing cannot tell "no fleet
  # here" from "configured". `fleet` itself refuses with the same reasoning; this says it earlier.
  echo "fleet-env.sh: no .fleet-root at or above $(pwd) (searched up to \$HOME); FLEET_HOME," \
       "FLEET_RELEASES and FLEET_TMUX_SOCKET were NOT set. Create the marker in this fleet's root," \
       'for example:  echo '"'"'{"name": "davis"}'"'"' > "$HOME/<root>/.fleet-root"' >&2
fi

# Only when you are going to create instants. An argument, so no effort's path is baked into this file.
#
# It must be a real directory, and that check is not pedantry. This file is designed to be sourced from a
# shell rc -- and a rc may source it from INSIDE a function, where
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
  # No `:-fleet` fallback. Reading the wrong server is how you conclude a healthy worker is dead, or a
  # dead one healthy, and a shared default is exactly the collision R2 exists to prove is real.
  [ -n "${FLEET_TMUX_SOCKET:-}" ] || { echo "fleet_peek: FLEET_TMUX_SOCKET is unset — source fleet-env.sh from inside a fleet root" >&2; return 2; }
  tmux -L "$FLEET_TMUX_SOCKET" capture-pane -p -t "=$1:" | grep -v '^$' | tail -"${2:-30}"
}

# Attach to a dispatched session without having to remember the -L.
fleet_attach() {
  [ -n "${FLEET_TMUX_SOCKET:-}" ] || { echo "fleet_attach: FLEET_TMUX_SOCKET is unset — source fleet-env.sh from inside a fleet root" >&2; return 2; }
  [ -n "${1:-}" ] || { tmux -L "$FLEET_TMUX_SOCKET" ls; return 0; }
  tmux -L "$FLEET_TMUX_SOCKET" attach -t "=$1"
}

# `fv` is a convenience for interactive shells only; scripts should call `fleet-view` directly, since an
# alias does not exist in a non-interactive shell.
alias fv='fleet-view' 2>/dev/null || true
