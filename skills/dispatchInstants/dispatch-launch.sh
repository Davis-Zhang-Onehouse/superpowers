#!/usr/bin/env bash
#
# dispatch-launch.sh — launch a worker from its RECORDED seed, correctly quoted.
#
# The `--no-launch` review gate used to end with a human copy-pasting (or worse, retyping)
# the printed launch line — where seeds containing | ; & < > ( ) get split and the worker
# starts on a mangled prompt. This replays the recorded seed with proper quoting instead, so
# no launch line is ever hand-built.
#
# Usage:  dispatch-launch.sh <todo-id> [--force] [--seed-file <f>] [--allow-during-compaction "<reason>"]
# Exit:   0 = launched + verified   1 = already running / could not verify   2 = bad input
#         4 = REFUSED, a compaction instant is inflight
# Env:    BOARD_DIR, TMUX_BIN, LAUNCH_WAIT (default 3), ALLOW_DISPATCH_DURING_COMPACTION="<reason>"
set -uo pipefail
# shellcheck source=lib/dispatch-lib.sh
. "$(cd "$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")" && pwd)/lib/dispatch-lib.sh"

BOARD_DIR="${BOARD_DIR:-$HOME/.claude-dispatch-board}"
TMUX_BIN="${TMUX_BIN:-tmux}"
WAIT="${LAUNCH_WAIT:-3}"
FORCE=0; SEED_FILE=""; ALLOW_COMPACT=0; ALLOW_COMPACT_REASON=""

[ $# -ge 1 ] || { echo "usage: dispatch-launch.sh <todo-id> [--force] [--seed-file <f>] [--allow-during-compaction \"<reason>\"]" >&2; exit 2; }
id="$1"; shift
while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1; shift;;
    # Every value-taking flag needs the dl_need_arg check: as a trailing argument, `shift 2` shifts
    # nothing and returns 1, and this script has no `set -e`, so the loop spun forever. --seed-file
    # carried the same latent hang; fixed together because it is the same shape one line away.
    --seed-file) dl_need_arg "$1" $# || exit 2; SEED_FILE="$2"; shift 2;;
    --allow-during-compaction) dl_need_arg "$1" $# || exit 2
                               ALLOW_COMPACT=1; ALLOW_COMPACT_REASON="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

rec="$BOARD_DIR/records/$id.json"
[ -f "$rec" ] || { echo "no dispatch record for '$id'" >&2; exit 2; }
get(){ python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2],"") or "")' "$rec" "$1"; }
sess="$(get tmux)"; ws="$(get ws)"
[ -n "$SEED_FILE" ] || SEED_FILE="$(get seed_file)"
[ -n "$sess" ] && [ -n "$ws" ] || { echo "record missing tmux/ws" >&2; exit 2; }
[ -n "$SEED_FILE" ] && [ -f "$SEED_FILE" ] || { echo "no seed file (record has no seed_file; pass --seed-file)" >&2; exit 2; }

# ---- a compaction instant is EXCLUSIVE (see dl_compaction_guard) ------------
# `todo` guards the same rule, but `todo --no-launch` + `launch` is a second door into the same act:
# guarding only one of them is not a guard. Fired before tmux is touched, so a refusal leaves no
# half-started session behind. The record's own instant is excluded, or a compaction dispatched
# with --no-launch could never be launched at all.
if ! ALLOW_COMPACT_REASON="$(dl_override_reason "$ALLOW_COMPACT" "$ALLOW_COMPACT_REASON")"; then
  echo "--allow-during-compaction requires a REASON: --allow-during-compaction \"<why this cannot wait>\"" >&2
  echo "  the reason is the mechanism — record it in your DECISIONS register too" >&2
  exit 2
fi
base_i="$(get base_instant)"
if [ -n "$base_i" ]; then
  self_i="$(dl_resolve_instant "$(get child_instant)")"
  dl_compaction_guard "$(dirname -- "$base_i")" "$self_i" "$ALLOW_COMPACT_REASON" || exit $?
else
  # Every tool that writes a record sets base_instant, so this is unreachable through the shipped
  # path — but a hand-written/migrated/legacy record would otherwise bypass a safety gate in
  # SILENCE, which is the one failure mode a guard must never have. Say so instead.
  echo "WARN: record '$id' has no base_instant — the compaction gate could NOT be evaluated." >&2
  echo "      Check by hand for a *-inflight-compact-* sibling before trusting this launch." >&2
fi

alive() { pgrep -f "remote-control $1" >/dev/null 2>&1 || "$TMUX_BIN" has-session -t "$1" >/dev/null 2>&1; }
if alive "$sess" && [ "$FORCE" != 1 ]; then
  echo "session '$sess' is already running — refusing to double-launch (use --force)" >&2
  exit 1
fi

SEED="$(cat "$SEED_FILE")"
"$TMUX_BIN" new-session -d -s "$sess" -c "$ws" >/dev/null 2>&1 || true
# %q keeps the whole seed ONE argument no matter what metacharacters it holds.
cmd="claude --permission-mode auto --remote-control $(printf '%q' "$sess") $(printf '%q' "$SEED")"
"$TMUX_BIN" send-keys -t "$sess" "$cmd" Enter >/dev/null 2>&1

# Claude clears and redraws the screen while booting, so ONE early sample legitimately matches
# nothing (this produced a false "could not verify" on a session that had started fine). Poll.
UI_RE='remote-control is active|auto mode|shift\+tab|esc to interrupt|Skill\(|claude'
for _ in $(seq 1 "${LAUNCH_VERIFY_TRIES:-10}"); do
  sleep "$WAIT"
  if "$TMUX_BIN" capture-pane -p -t "$sess" 2>/dev/null | tail -60 | grep -qE "$UI_RE"; then
    python3 - "$rec" <<'PYL'
import json, sys, datetime
p = sys.argv[1]
try:
    d = json.load(open(p))
    d["launched_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    json.dump(d, open(p, "w"), indent=2, ensure_ascii=False)
except Exception:
    pass
PYL
    echo "launched $id in $sess (ws=$ws)"
    echo "  attach: tmux attach -t $sess"
    exit 0
  fi
done
echo "launched but COULD NOT VERIFY the pane started claude — attach and check: tmux attach -t $sess" >&2
exit 1
