#!/usr/bin/env bash
# fleet-revive.sh — the MECHANICS of bringing a dead worker's pane back.
#
#     bash scripts/fleet-revive.sh plan        <todo-id>
#     bash scripts/fleet-revive.sh transcripts <todo-id>
#     bash scripts/fleet-revive.sh launcher    <todo-id> <transcript-id>
#     bash scripts/fleet-revive.sh start       <todo-id>
#
# `superpowers:reviving-dead-panes` owns the JUDGEMENT — revive or abort, whether the menu is really on
# screen, whether to send a key at all. This owns the parts that are pure derivation and were being
# retyped from a runbook: which server, which slot, which config directory, which transcript.
#
# Everything is DERIVED FROM THE RECORD, never from the environment. `SI-59` is why: a record carries the
# tmux server it was dispatched on, and reviving a session on a different server than the record names
# leaves `board` looking at the recorded one and not finding it. Every value this script uses is printed
# by `plan` before anything is created, so the derivation can be checked rather than trusted.
#
# It creates NOTHING except the launcher script and the tmux session, and it never sends a key.
set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

die()  { printf 'fleet-revive: %s\n' "$*" >&2; exit 2; }
note() { printf '  %-16s %s\n' "$1" "$2"; }

FLEET="${FLEET_BIN:-fleet}"
command -v "$FLEET" >/dev/null 2>&1 || FLEET="$REPO/bin/fleet"
command -v "$FLEET" >/dev/null 2>&1 || die "no \`fleet\` on PATH and none at $REPO/bin/fleet"

# --- derivation ---------------------------------------------------------------------------------------

field() {                 # field <status-tsv> <name> -> value ("" when absent)
  awk -F'\t' -v k="$2" '$1==k{print $2; exit}' "$1"
}

derive() {                # derive <todo-id> -> sets SESSION SOCKET INSTANT SLOT ROOT CONFIG_DIR
  local id="$1" status leases
  status="$(mktemp)"; leases="$(mktemp)"
  # shellcheck disable=SC2064  # the paths are expanded now on purpose
  trap "rm -f '$status' '$leases'" RETURN
  "$FLEET" status --id "$id" --porcelain > "$status" 2>/dev/null \
    || die "\`fleet status --id $id\` failed; is that the right record? (\`fleet board\` lists them)"

  SESSION="$(field "$status" evidence.tmux)"
  [ -n "$SESSION" ] || die "record $id names no tmux session, so there is no pane to revive. \`fleet resume --instant <instant> --tmux <session>\` attaches one."

  #: The SERVER, from the record. Empty means the record predates the field (`SI-59`) — NOT MEASURED, so
  #: it is reported as a guess the caller has to confirm rather than silently defaulted to anything.
  SOCKET="$(field "$status" evidence.tmux_socket)"
  SOCKET_SOURCE="the record"
  if [ -z "$SOCKET" ]; then
    SOCKET="${FLEET_TMUX_SOCKET:-}"
    SOCKET_SOURCE="\$FLEET_TMUX_SOCKET — THE RECORD DOES NOT SAY, so confirm this is where it ran"
  fi
  [ -n "$SOCKET" ] || die "record $id names no tmux server and \$FLEET_TMUX_SOCKET is unset; nothing says which server to revive on"

  INSTANT="$(field "$status" evidence.instant)"
  case "$INSTANT" in *" (missing)") die "the instant folder in record $id is missing: ${INSTANT% (missing)}" ;; esac
  [ -d "$INSTANT" ] || die "instant $INSTANT is not a directory"

  #: The slot PATH, from the lease rather than from the record's `golden` — the lease is what says where
  #: this worker actually is.
  "$FLEET" leases --porcelain > "$leases" 2>/dev/null || die "\`fleet leases\` failed"
  SLOT="$(awk -F'\t' -v id="$id" '$3==id{print $7; exit}' "$leases")"
  [ -n "$SLOT" ] || die "no lease in this store is held by $id, so its slot is unknown. \`fleet leases\` shows what is held; a released lease means the work is not revivable in place."
  [ -d "$SLOT" ] || die "slot $SLOT is not a directory"

  #: The ROOT, by the same walk `fleet` and `fleet-env.sh` do — up from the slot to a `.fleet-root`
  #: marker, stopping BELOW $HOME. The config directory is a property of the root, and getting it wrong
  #: is the trap that makes `--resume` find nothing.
  ROOT=""
  local d="$SLOT"
  while [ -n "$d" ] && [ "$d" != "/" ] && [ "$d" != "$HOME" ]; do
    [ -f "$d/.fleet-root" ] && { ROOT="$d"; break; }
    d="$(dirname "$d")"
  done
  [ -n "$ROOT" ] || die "no .fleet-root at or above $SLOT (searched up to \$HOME); this slot is not inside a fleet root"
  CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$ROOT/.claude}"
  [ -d "$CONFIG_DIR" ] || die "$CONFIG_DIR is not a directory; \`--resume\` would read a config directory that does not exist"
}

# --- subcommands --------------------------------------------------------------------------------------

cmd_plan() {
  derive "$1"
  echo "revive plan for $1"
  note "session"    "$SESSION"
  note "server"     "$SOCKET   (from $SOCKET_SOURCE)"
  note "slot"       "$SLOT"
  note "instant"    "$INSTANT"
  note "root"       "$ROOT"
  note "config dir" "$CONFIG_DIR"
  local alive="no"
  tmux -L "$SOCKET" has-session -t "=$SESSION" 2>/dev/null && alive="YES — nothing to revive"
  note "alive now"  "$alive"
}

cmd_transcripts() {
  derive "$1"
  #: The slug claude uses for a project directory. Listed NEWEST FIRST but never chosen: a slot is
  #: re-leased across efforts, so the newest transcript in it can belong to a previous occupant. Pick the
  #: one whose mtime matches the death — that judgement is the operator's and the skill says why.
  local slug; slug="$(printf '%s' "$SLOT" | tr '/_' '--')"
  local dir="$CONFIG_DIR/projects/$slug"
  [ -d "$dir" ] || die "no transcript directory at $dir — nothing was ever recorded for this slot under this config directory"
  echo "transcripts for $SLOT"
  echo "  (newest first; pick the one whose time matches the death, NOT simply the first)"
  ls -lat --time-style=+'%Y-%m-%d %H:%M' "$dir"/*.jsonl 2>/dev/null \
    | awk '{printf "  %-6s %s %s  %s\n", $5, $6, $7, $NF}' \
    || die "no *.jsonl in $dir"
}

cmd_launcher() {
  derive "$1"
  local transcript="${2:-}"
  [ -n "$transcript" ] || die "usage: launcher <todo-id> <transcript-id>   (\`transcripts\` lists them)"
  local out="$INSTANT/.fleet/revive-launcher.sh"
  mkdir -p "$INSTANT/.fleet"
  #: NOT named `claude`, and not on any PATH. A shim called `claude` on the tmux server's PATH is the
  #: stale-shim shape `dispatch`'s seed-integrity check exists to catch — one such shim once handed a
  #: worker another instant's briefing byte for byte.
  cat > "$out" <<LAUNCHER
#!/usr/bin/env bash
# Written by scripts/fleet-revive.sh for $1. Started by tmux through \`sh -c\`, which sees no shell
# functions and inherits the SERVER's environment — so every value below is stated rather than assumed.
export CLAUDE_CONFIG_DIR="$CONFIG_DIR"
export FLEET_ROOT="$ROOT"
export FLEET_INSTANTS="$(dirname "$INSTANT")"
export FLEET_TMUX_SOCKET="$SOCKET"
export INSTANT="$INSTANT"
export PATH="$ROOT/fleet-releases/current/bin:\$PATH"
cd "$SLOT" || exit 1
exec claude --resume "$transcript"
LAUNCHER
  chmod +x "$out"
  echo "$out"
}

cmd_start() {
  derive "$1"
  local launcher="$INSTANT/.fleet/revive-launcher.sh"
  [ -x "$launcher" ] || die "no launcher at $launcher — run \`launcher $1 <transcript-id>\` first"
  if tmux -L "$SOCKET" has-session -t "=$SESSION" 2>/dev/null; then
    die "$SESSION already exists on server $SOCKET; there is nothing to revive"
  fi
  tmux -L "$SOCKET" new-session -d -s "$SESSION" -c "$SLOT" "$launcher" \
    || die "tmux refused to start $SESSION on server $SOCKET"
  echo "started $SESSION on server $SOCKET"
  #: The socket goes IN FRONT of `fleet_peek`: the helper reads it from the environment, which is this
  #: shell's server and not necessarily the record's. Printing the bare form taught the wrong habit.
  echo "  read it with:   FLEET_TMUX_SOCKET=$SOCKET fleet_peek $SESSION"
  echo "                  (or: tmux -L $SOCKET capture-pane -p -t '=$SESSION:')"
  echo "  check it with:  fleet pane-guard --id $1"
  echo "  DO NOT send a key until you have CAPTURED the pane and seen what is on it."
}

case "${1:-}" in
  plan)        [ $# -eq 2 ] || die "usage: plan <todo-id>";                    cmd_plan "$2" ;;
  transcripts) [ $# -eq 2 ] || die "usage: transcripts <todo-id>";             cmd_transcripts "$2" ;;
  launcher)    [ $# -eq 3 ] || die "usage: launcher <todo-id> <transcript-id>"; cmd_launcher "$2" "$3" ;;
  start)       [ $# -eq 2 ] || die "usage: start <todo-id>";                   cmd_start "$2" ;;
  *) die "unknown subcommand '${1:-}'. One of: plan, transcripts, launcher, start" ;;
esac
