#!/usr/bin/env bash
# fleet-revive.sh — revive EVERY dead pane of the fleet whose root holds the current directory.
#
#     cd /home/ubuntu/<name>_root            # anywhere inside the fleet root (the directory holding .fleet-root)
#     bash scripts/fleet-revive.sh plan      # read-only: every DEAD record, every derived value, every refusal
#     bash scripts/fleet-revive.sh revive    # the same pre-flight, then `fleet revive` for each record
#
# `superpowers:reviving-dead-panes` owns the JUDGEMENT — revive or abort, whether a resume menu is really on
# screen, whether to send a key at all. This owns everything that is derivation: which root, which server,
# which slot, which configuration directory, which transcript. Nothing is typed by an operator. Three environment
# values are read: `$HOME` (the marker walk stops below it, as `fleet`'s does), `FLEET_LAUNCHER_TEST_BIN` (the test
# seam for which binary acts, `$REPO/bin/fleet` otherwise; printed on the second line — an ambient `FLEET_BIN`
# is deliberately NOT read, FB-56) and, for a legacy Claude record only, `CLAUDE_OWNERS_MAP` through
# `claude-config-dir.sh`.
#
# THE ROOT IS THE WORKING DIRECTORY'S. The marker walk is the same one `fleet` and `fleet-env.sh` perform,
# and it stops below $HOME for the same reason. A directory outside every root is refused: there is no fleet
# to ask. Exported `FLEET_*` values are dropped rather than honoured, because `fleet` ranks `$FLEET_HOME`
# above `--root` and a stale export from another root would silently redirect the store — the exact failure
# per-root isolation exists to prevent.
#
# THE TRANSCRIPT IS DERIVED FROM THE RECORD'S SEED. A record carries no native session UUID, and a slot's
# project directory holds every past occupant's transcripts, so mtime is not identity (three occupants of
# one slot were measured weeks apart). What IS identity: the worker's first user message is the record's
# `.fleet/seed.txt` verbatim, and the seed embeds the instant path with its dispatch timestamp. The transcript
# whose metadata cwd is the lease path and whose first user messages (the first five, because both CLIs inject
# user-role blocks — a caveat row, `<recommended_plugins>`, an AGENTS.md preamble — ahead of the prompt) carry
# the WHOLE seed is the worker's; a `subagents/` file is never a candidate; several matches choose the one
# last written to and print all of them; two records resolving to one transcript refuse the run.
#
# ANY PRE-FLIGHT PROBLEM REFUSES THE WHOLE RUN (rc 2, nothing started): a record on the other runtime, a
# recorded abort, a seed no transcript received, or a `fleet revive --dry-run` refusal. `fleet revive` is the
# only actor — every lock and check it performs (runtime match, held lease, unoccupied pane and workspace,
# transcript-vs-workspace, verified resume) applies unchanged.
set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
# NOT `FLEET_BIN` (FB-56). `fleet dispatch` exports FLEET_BIN into every worker it starts, naming the fleet
# that ran dispatch, so reading that name here ran the DISPATCHER'S binary (for a release worker, the deployed
# copy) instead of the one this script ships beside. The seam has a name nothing exports.
FLEET="${FLEET_LAUNCHER_TEST_BIN:-$REPO/bin/fleet}"
[ -x "$FLEET" ] || { printf 'fleet-revive: no executable fleet at %s\n' "$FLEET" >&2; exit 2; }

die()  { printf 'fleet-revive: %s\n' "$*" >&2; exit 2; }

MODE="${1:-}"
case "$MODE" in
  plan|revive) [ $# -eq 1 ] || die "usage: $0 plan | revive   (no other argument: every value is derived)" ;;
  *) die "usage: $0 plan | revive   — run from inside a fleet root; \`plan\` is read-only, \`revive\` starts every DEAD record" ;;
esac
note() { printf '  %-12s %s\n' "$1" "$2"; }
field() { awk -F'\t' -v k="$2" '$1==k{print $2; exit}' "$1"; }   # field <status-tsv> <name>

# --- the root ---------------------------------------------------------------------------------------------

ROOT=""; NAME=""; SOCKET=""
resolve_root() {
  local d home
  d="$(pwd -P)"
  home="$(cd "${HOME:-/nonexistent}" 2>/dev/null && pwd -P)" || home=/nonexistent
  case "$d/" in "$home"/*) ;; *) die "$d is not under \$HOME ($home), so no fleet root can hold it: fleet's marker walk only looks under \$HOME" ;; esac
  while [ -n "$d" ] && [ "$d" != "/" ] && [ "$d" != "$home" ]; do
    if [ -f "$d/.fleet-root" ]; then ROOT="$d"; break; fi
    d="$(dirname "$d")"
  done
  [ -n "$ROOT" ] || die "$(pwd -P) is not inside a fleet root: no .fleet-root marker between here and \$HOME. cd into the fleet's root directory (the one holding .fleet-root, e.g. /home/ubuntu/davis_root) and run again"
  NAME="$(python3 -c 'import json,sys
try:
    print((json.load(open(sys.argv[1])).get("name") or "").strip())
except Exception:
    pass' "$ROOT/.fleet-root" 2>/dev/null)"
  [ -n "$NAME" ] || die "$ROOT/.fleet-root declares no name; fleet cannot resolve this root either"
  SOCKET="fleet-$NAME"

  # Dropped, not honoured: `fleet` ranks $FLEET_HOME above --root, so a value exported for another root
  # would win over the directory the operator is standing in.
  local v
  for v in FLEET_HOME FLEET_ROOT FLEET_TMUX_SOCKET FLEET_RELEASES FLEET_INSTANTS; do
    if [ -n "${!v:-}" ]; then
      printf 'fleet-revive: ignoring exported %s=%s (the root is derived from the working directory)\n' "$v" "${!v}" >&2
      unset "$v"
    fi
  done
}

F() { local verb="$1"; shift; "$FLEET" "$verb" --root "$ROOT" "$@"; }

# --- per-record derivation --------------------------------------------------------------------------------

PROBLEMS=()
problem() { PROBLEMS+=("$1: $2"); printf '  %-12s %s\n' "PROBLEM" "$2"; }

# derive <todo-id> -> RT SESSION RSOCKET INSTANT SLOT CONFIG_DIR CONFIG_SOURCE SEED SESSION_ID MATCHES
derive() {
  local id="$1" status leases
  RT=""; SESSION=""; RSOCKET=""; INSTANT=""; SLOT=""; CONFIG_DIR=""; CONFIG_SOURCE=""; SEED=""; SESSION_ID=""; MATCHES=""
  status="$(mktemp)"; leases="$(mktemp)"
  # shellcheck disable=SC2064  # expanded now on purpose
  trap "rm -f '$status' '$leases'" RETURN

  echo "revive plan for $id"
  if ! F status --id "$id" --porcelain > "$status" 2>/dev/null; then
    problem "$id" "\`fleet status --id $id\` failed"; return
  fi
  RT="$(field "$status" evidence.runtime)"; RT="${RT:-claude}"
  SESSION="$(field "$status" evidence.tmux)"
  RSOCKET="$(field "$status" evidence.tmux_socket)"
  INSTANT="$(field "$status" evidence.instant)"
  note "runtime"  "$RT   (fleet selection: $SELECTION)"
  note "session"  "$SESSION on tmux server ${RSOCKET:-"(record names none; fleet asks $SOCKET)"}"
  note "instant"  "$INSTANT"

  if [ "$RT" != "$SELECTION" ]; then
    problem "$id" "the record ran on $RT and the fleet is set to $SELECTION; fleet revive refuses this too. \`fleet runtime\` shows the selection; change it back (or harvest the record) rather than reviving across runtimes"
  fi
  case "$INSTANT" in *" (missing)") problem "$id" "the instant folder is missing: ${INSTANT% (missing)}"; return ;; esac
  [ -d "$INSTANT" ] || { problem "$id" "instant $INSTANT is not a directory"; return; }
  if [ -f "$INSTANT/.fleet/abort.json" ]; then
    problem "$id" "an abort is recorded in $INSTANT/.fleet/abort.json; finish it with \`fleet abort --id $id --reason …\` instead of reviving"
  fi

  #: The slot PATH, from the lease — the lease is what says where this worker actually is.
  if ! F leases --porcelain > "$leases" 2>/dev/null; then problem "$id" "\`fleet leases\` failed"; return; fi
  SLOT="$(awk -F'\t' -v id="$id" '$3==id{print $7; exit}' "$leases")"
  [ -n "$SLOT" ] || { problem "$id" "no lease in this store is held by $id; a released lease means the work is not revivable in place"; return; }
  note "slot" "$SLOT"
  [ -d "$SLOT" ] || { problem "$id" "slot $SLOT is not a directory"; return; }

  CONFIG_DIR="$(field "$status" evidence.runtime_config_dir)"; CONFIG_SOURCE="the record"
  if [ -z "$CONFIG_DIR" ]; then
    if [ "$RT" = claude ]; then
      CONFIG_DIR="$("$HERE/claude-config-dir.sh" "$SLOT")" || { problem "$id" "legacy record and no owner resolves for $SLOT"; return; }
      CONFIG_SOURCE="the owner of the slot (legacy record)"
    else
      problem "$id" "the record names no Codex configuration directory"; return
    fi
  fi
  note "config dir" "$CONFIG_DIR   (from $CONFIG_SOURCE)"
  [ -d "$CONFIG_DIR" ] || { problem "$id" "configuration directory $CONFIG_DIR is unavailable"; return; }

  SEED="$INSTANT/.fleet/seed.txt"
  [ -s "$SEED" ] || { problem "$id" "no seed at $SEED, so no transcript can be matched; revive by hand with \`fleet revive --id $id --session-id <uuid>\`"; return; }

  local merr rc
  merr="$(mktemp)"
  MATCHES="$(python3 - "$RT" "$CONFIG_DIR" "$SLOT" "$SEED" 2>"$merr" <<'PY_MATCH'
import datetime
import json
import sys
from pathlib import Path

runtime, config, slot, seed_path = sys.argv[1:]

#: How many user-role blocks are inspected before a transcript is ruled out. Both CLIs put user-role
#: blocks ahead of the prompt: Claude a `<local-command-caveat>` meta row, Codex `<environment_context>`,
#: `<recommended_plugins>` and an `# AGENTS.md instructions` preamble (measured: 4 of 6 rollouts on this
#: box open with one of those). Five covers every measured shape with room to spare: on the dispatch path the
#: seed is argv and lands as user block 1 (Claude) or 2 (Codex). A launch path that ran slash commands before
#: the seed would push it further (each writes three user rows here); the rule then degrades to a refusal,
#: never to a wrong choice.
USER_BLOCKS = 5
#: Rows read before a file is given up on; the first user blocks sit within the first few dozen rows.
ROW_CAP = 4000


def squash(text):
    return " ".join(str(text or "").split())


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(block.get("text", "")) for block in content
                        if isinstance(block, dict) and block.get("type") in ("text", "input_text"))
    return ""


def rows(path):
    with path.open(errors="replace") as handle:
        for index, line in enumerate(handle):
            if index > ROW_CAP:
                return
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def claude_meta(path):
    sid = cwd = None
    users = []
    for row in rows(path):
        sid = sid or row.get("sessionId")
        cwd = cwd or row.get("cwd")
        if row.get("type") == "user":
            users.append(text_of((row.get("message") or {}).get("content")))
            if len(users) >= USER_BLOCKS:
                break
    return sid, cwd, users


def codex_meta(path):
    sid = cwd = None
    users = []
    for row in rows(path):
        payload = row.get("payload") or {}
        kind = row.get("type")
        if kind == "session_meta":
            sid, cwd = payload.get("id"), payload.get("cwd")
        elif kind == "event_msg" and payload.get("type") == "user_message":
            users.append(str(payload.get("message", "")))
        elif kind == "response_item" and payload.get("type") == "message" and payload.get("role") == "user":
            users.append(text_of(payload.get("content")))
        if len(users) >= USER_BLOCKS:
            break
    return sid, cwd, users


try:
    slot = Path(slot).resolve()
    #: The WHOLE seed. A prefix stops being an identity the moment the instant path (with its dispatch
    #: timestamp) falls outside it — measured at 28 characters of margin on one profile — after which
    #: every worker of an effort dispatched into this slot compares equal.
    seed = squash(Path(seed_path).read_text(errors="replace"))
    if not seed:
        print("empty seed", file=sys.stderr)
        sys.exit(3)
    if runtime == "codex":
        files = list(Path(config, "sessions").rglob("rollout-*.jsonl"))
        meta = codex_meta
    else:
        files = [p for p in Path(config, "projects").rglob("*.jsonl") if "subagents" not in p.parts]
        meta = claude_meta
    matches = []
    for path in files:
        try:
            sid, cwd, users = meta(path)
            written = path.stat().st_mtime
        except (FileNotFoundError, PermissionError):
            continue        # rotated away or not ours between the listing and the read: not a candidate
        except OSError as exc:
            print(f"cannot read {path}: {exc}", file=sys.stderr)
            sys.exit(3)
        if not sid or not cwd or not users:
            continue
        try:
            if Path(cwd).resolve() != slot:
                continue
        except (OSError, TypeError, ValueError):
            continue
        if any(seed in squash(text) for text in users):
            stamp = datetime.datetime.fromtimestamp(written, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            matches.append((written, stamp, sid, str(path)))
except OSError as exc:
    print(f"cannot inspect {config}: {exc}", file=sys.stderr)
    sys.exit(3)
matches.sort()
#: Exit codes the shell branches on. 4 is "no match" and 5 is "a tie" precisely because 1 is what an uncaught
#: exception exits with, and a traceback must never be read as "the seed was never delivered".
if len(matches) > 1 and matches[-1][0] == matches[-2][0]:
    for _, stamp, sid, path in matches:
        print(stamp, sid, path, sep="\t")
    print("two transcripts carry this seed with identical write times; nothing tells them apart", file=sys.stderr)
    sys.exit(5)
for _, stamp, sid, path in matches:
    print(stamp, sid, path, sep="\t")
sys.exit(0 if matches else 4)
PY_MATCH
  )"
  rc=$?
  case "$rc" in
    0) rm -f "$merr" ;;
    4) rm -f "$merr"
       problem "$id" "no transcript under $CONFIG_DIR has cwd $SLOT and this record's seed among its first user messages; the seed may never have been delivered. Revive by hand with \`fleet revive --id $id --session-id <uuid>\` if you know the session"
       return ;;
    5) rm -f "$merr"
       printf '%s\n' "$MATCHES" | awk -F'\t' '{printf "               %s  last written %s  %s\n", $2, $1, $3}'
       problem "$id" "two transcripts carry this seed with identical write times, so nothing says which is the live thread; revive by hand with \`fleet revive --id $id --session-id <uuid>\` after reading both"
       return ;;
    *) problem "$id" "the transcript search failed (rc $rc): $(tail -1 "$merr")"
       rm -f "$merr"; return ;;
  esac
  local count
  count="$(printf '%s\n' "$MATCHES" | wc -l)"
  SESSION_ID="$(printf '%s\n' "$MATCHES" | tail -1 | cut -f2)"
  if [ "$count" -gt 1 ]; then
    note "candidates" "$count transcripts carry this seed; the one last written to is chosen:"
    printf '%s\n' "$MATCHES" | awk -F'\t' '{printf "               %s  last written %s  %s\n", $2, $1, $3}'
  fi
  note "transcript" "$SESSION_ID   (last written $(printf '%s\n' "$MATCHES" | tail -1 | cut -f1))"
}

# --- the run ----------------------------------------------------------------------------------------------

resolve_root
echo "fleet root $ROOT   (name $NAME, server $SOCKET, store $ROOT/.fleet)"
echo "fleet binary $FLEET"

SELECTION="$(F runtime --porcelain 2>/dev/null | awk -F'\t' '$1=="runtime"{print $2; exit}')"
[ -n "$SELECTION" ] || die "\`fleet runtime\` reports no selection for $ROOT; is the store readable?"

BOARD="$(mktemp)"; trap 'rm -f "$BOARD"' EXIT
F board --porcelain > "$BOARD" || die "\`fleet board\` failed for $ROOT"
mapfile -t DEAD < <(awk -F'\t' '$2=="worker" && $3=="DEAD"{print $1}' "$BOARD")
UNREACHABLE="$(awk -F'\t' '$2=="worker" && $3=="UNREACHABLE"{n++} END{print n+0}' "$BOARD")"

if [ "${#DEAD[@]}" -eq 0 ]; then
  echo "nothing to revive: no DEAD record on the board of $ROOT"
  [ "$UNREACHABLE" -gt 0 ] && echo "($UNREACHABLE UNREACHABLE: a live pid holds the slot, so there is nothing to revive; read the server in its note)"
  exit 0
fi
echo "${#DEAD[@]} DEAD record(s): ${DEAD[*]}"
[ "$UNREACHABLE" -gt 0 ] && echo "($UNREACHABLE UNREACHABLE row(s) are not revived: a live pid holds the slot)"

declare -A PLAN_SESSION PLAN_INSTANT
for id in "${DEAD[@]}"; do
  derive "$id"
  PLAN_SESSION[$id]="$SESSION_ID"; PLAN_INSTANT[$id]="$INSTANT"
done

# Two records resolving to ONE transcript is a wrong revival waiting to happen: the verb only checks that
# the transcript's cwd is the lease path, which both would satisfy.
for id in "${DEAD[@]}"; do
  [ -n "${PLAN_SESSION[$id]}" ] || continue
  for other in "${DEAD[@]}"; do
    if [[ "$other" > "$id" ]] && [ "${PLAN_SESSION[$other]}" = "${PLAN_SESSION[$id]}" ]; then
      problem "$id" "$id and $other resolve to the same transcript ${PLAN_SESSION[$id]}; one of the two seeds is not its record's identity"
    fi
  done
done

# `fleet revive --dry-run` applies the verb's own checks to every record before anything starts.
if [ "${#PROBLEMS[@]}" -eq 0 ]; then
  for id in "${DEAD[@]}"; do
    if ! out="$(F revive --id "$id" --session-id "${PLAN_SESSION[$id]}" --instants-dir "$(dirname "${PLAN_INSTANT[$id]}")" --dry-run 2>&1)"; then
      problem "$id" "fleet revive --dry-run refused: $(printf '%s' "$out" | tail -1)"
    fi
  done
fi

if [ "${#PROBLEMS[@]}" -gt 0 ]; then
  echo
  echo "refusing: ${#PROBLEMS[@]} problem(s), nothing started" >&2
  printf '  %s\n' "${PROBLEMS[@]}" >&2
  exit 2
fi

case "${MODE}" in
  plan)
    echo
    echo "plan only: ${#DEAD[@]} record(s) would be revived. Run \`$0 revive\` from this directory to start them."
    exit 0 ;;
  revive) ;;
esac

echo
FAILED=()
for id in "${DEAD[@]}"; do
  echo "reviving $id ..."
  if F revive --id "$id" --session-id "${PLAN_SESSION[$id]}" --instants-dir "$(dirname "${PLAN_INSTANT[$id]}")"; then
    guard="$(F pane-guard --id "$id" --porcelain 2>/dev/null | awk -F'\t' '$1=="code"||$1=="verdict"{printf "%s ", $2}')"
    note "pane-guard" "${guard:-"(no answer)"}   (first poll; a resume menu reads 10 or 15 — read the pane)"
  else
    rc=$?
    FAILED+=("$id")
    note "FAILED" "fleet revive exited $rc for $id; the lease is retained. Inspect the pane before retrying"
  fi
done

echo
F board
if [ "${#FAILED[@]}" -gt 0 ]; then
  echo "revived $(( ${#DEAD[@]} - ${#FAILED[@]} )) of ${#DEAD[@]}; failed: ${FAILED[*]}. Re-run \`$0 revive\` after inspecting them; it revives what is still DEAD" >&2
  exit 1
fi
echo "revived ${#DEAD[@]} of ${#DEAD[@]}. The board corrects itself as each process comes up; no verb is needed"
exit 0
