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

derive() {                # derive <todo-id> -> sets SESSION SOCKET INSTANT SLOT CONFIG_DIR RUNTIME
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

  RUNTIME="$(field "$status" evidence.runtime)"
  RUNTIME="${RUNTIME:-claude}"
  CONFIG_DIR="$(field "$status" evidence.runtime_config_dir)"
  if [ -z "$CONFIG_DIR" ]; then
    [ "$RUNTIME" = claude ] || die "record has no Codex configuration; use fleet revive for explicit resolution"
    CONFIG_DIR="$("$HERE/claude-config-dir.sh" "$SLOT")" || die "cannot resolve legacy Claude configuration"
  fi
  [ -d "$CONFIG_DIR" ] || die "recorded configuration directory is unavailable: $CONFIG_DIR"

}

# --- subcommands --------------------------------------------------------------------------------------

cmd_plan() {
  derive "$1"
  echo "revive plan for $1"
  note "session"    "$SESSION"
  note "server"     "$SOCKET   (from $SOCKET_SOURCE)"
  note "slot"       "$SLOT"
  note "instant"    "$INSTANT"
  note "config dir" "$CONFIG_DIR"
  note "runtime"    "$RUNTIME"
  local alive="no"
  tmux -L "$SOCKET" has-session -t "=$SESSION" 2>/dev/null && alive="YES — nothing to revive"
  note "alive now"  "$alive"
}

cmd_transcripts() {
  derive "$1"
  python3 - "$RUNTIME" "$CONFIG_DIR" "$SLOT" <<'PY_LIST'
import json
from pathlib import Path
import sys
runtime, config, slot = sys.argv[1:]
base = Path(config) / ('sessions' if runtime == 'codex' else 'projects')
for path in sorted(base.rglob('*.jsonl')):
    try:
        with path.open() as stream:
            for line in stream:
                row = json.loads(line)
                if runtime == 'codex':
                    if row.get('type') != 'session_meta':
                        continue
                    data = row.get('payload', {})
                    identity = data.get('id')
                else:
                    data, identity = row, row.get('sessionId')
                if identity and data.get('cwd'):
                    if Path(data['cwd']).resolve() == Path(slot).resolve():
                        print(identity, path, sep='\t')
                    break
    except (OSError, ValueError) as exc:
        print(f'Cannot inspect {path}: {exc}', file=sys.stderr)
        sys.exit(1)
PY_LIST

}

cmd_launcher() {
  derive "$1"
  local transcript="${2:-}" out="$INSTANT/.fleet/revive-launcher.sh" store
  [ -n "$transcript" ] || die "usage: launcher <todo-id> <session-uuid>"
  "$FLEET" revive --id "$1" --session-id "$transcript" --dry-run || return $?
  store="$("$FLEET" runtime --porcelain | awk -F'\t' '$1=="home"{print $2}')"
  [ -n "$store" ] || die "could not resolve fleet store"
  python3 - "$out" "$(command -v "$FLEET")" "$1" "$transcript" "$store" "$(dirname "$INSTANT")" <<'PY_LAUNCH'
from pathlib import Path
import shlex
import sys
out, binary, record, session, store, instants = sys.argv[1:]
path = Path(out)
path.parent.mkdir(parents=True, exist_ok=True)
argv = [binary, 'revive', '--id', record, '--session-id', session,
        '--home', store, '--instants-dir', instants]
path.write_text('#!/usr/bin/env bash\nset -euo pipefail\nexec ' + shlex.join(argv) + '\n')
path.chmod(0o700)
print(path)
PY_LAUNCH
}

cmd_start() {
  derive "$1"
  local launcher="$INSTANT/.fleet/revive-launcher.sh"
  [ -x "$launcher" ] || die "run launcher $1 <session-uuid> first"
  # fleet acquires the admission and pane locks at actual start.
  bash "$launcher"
}

case "${1:-}" in
  plan)        [ $# -eq 2 ] || die "usage: plan <todo-id>";                    cmd_plan "$2" ;;
  transcripts) [ $# -eq 2 ] || die "usage: transcripts <todo-id>";             cmd_transcripts "$2" ;;
  launcher)    [ $# -eq 3 ] || die "usage: launcher <todo-id> <transcript-id>"; cmd_launcher "$2" "$3" ;;
  start)       [ $# -eq 2 ] || die "usage: start <todo-id>";                   cmd_start "$2" ;;
  *) die "unknown subcommand '${1:-}'. One of: plan, transcripts, launcher, start" ;;
esac
