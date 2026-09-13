#!/usr/bin/env bash
#
# Report what would make this a bad moment to cut a release. Advisory: exit 0 with WARN lines.
#
# Usage:  scripts/release-preflight.sh [--reap]
#
# The check this replaces was `tmux -L fleet ls; tmux ls`, which printed "error connecting to
# /tmp/tmux-1000/fleet" and was read as a quiet box. It was not quiet: `release-verify` printed "this box
# has live fleet work" on all three of its runs that day, and the live session was on `fleet-davis2`.
# The socket is DERIVED PER ROOT (`fleet-env.sh`: FLEET_TMUX_SOCKET=fleet-$name) and that file
# deliberately UNSETS a socket named literally `fleet` -- so `-L fleet` can never be a fleet socket, and
# its failure is spelled the same as an empty server. A wrong guess and a quiet box look identical.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

# Test seam, matching scripts/release-gate.sh: the narrow variable a test overrides instead of the real
# ~few-hundred-ms `fleet board` call, so a stubbed run cannot also mask the real thing this script checks.
FLEET="${FLEET_BIN:-$REPO/bin/fleet}"

REAP=0
case "${1:-}" in
  "") ;;
  --reap) REAP=1 ;;
  *)
    echo "$(basename "$0"): unknown argument '$1' (only --reap)" >&2
    exit 2
    ;;
esac

# --- the one hard refusal ------------------------------------------------------------------------------
#
# An unset or literal `fleet` socket means the environment was never derived (see fleet-env.sh, "which
# fleet is this?" and its SI-57 section) -- and every count below would then be measuring nothing, while
# reading exactly like measuring an empty box. Reporting confidently from a broken environment is worse
# than refusing, because the reader cannot tell the two apart on screen. This is the only refusal in this
# script; every other finding below is advisory.
if [ -z "${FLEET_TMUX_SOCKET:-}" ] || [ "${FLEET_TMUX_SOCKET:-}" = "fleet" ]; then
  echo "$(basename "$0"): FLEET_TMUX_SOCKET is unset or literally 'fleet'. The socket must be DERIVED" \
       "per root: scripts/fleet-env.sh sets FLEET_TMUX_SOCKET=fleet-<name> and deliberately unsets a bare" \
       "'fleet' socket, because that name belongs to no root and 'tmux -L fleet ls' failing looks exactly" \
       "like a quiet box even when it is not. Source scripts/fleet-env.sh from inside a fleet root first." \
       >&2
  exit 2
fi

warn() { echo "WARN: $*"; }

count_dt_sessions() { # count_dt_sessions <socket-name> -- number of dt- (dispatch) sessions on it
  tmux -L "$1" ls 2>/dev/null | grep -c '^dt-'
}

# --- 1. this root ----------------------------------------------------------------------------------
n="$(count_dt_sessions "$FLEET_TMUX_SOCKET")"
[ "$n" -gt 0 ] && warn "this root ($FLEET_TMUX_SOCKET) has $n live dt- session(s)"

# --- 2. every other root -- the half the incident missed -------------------------------------------
#
# Another root's socket showing live work is not an error and not this root's business to touch -- it is
# an uncontrollable residual on a shared box, and refusing on it would make releases impossible here. It
# is still worth a WARN: a human deciding whether "now" is a good moment wants to know the box is busy.
shopt -s nullglob
for sockdir in /tmp/tmux-*/; do
  for sockpath in "$sockdir"fleet-*; do
    sockname="$(basename "$sockpath")"
    [ "$sockname" = "$FLEET_TMUX_SOCKET" ] && continue
    n="$(count_dt_sessions "$sockname")"
    [ "$n" -gt 0 ] && warn "another root's socket ($sockname) has $n live dt- session(s) -- this box has live fleet work"
  done
done
shopt -u nullglob

# --- 3. slots still held by a COMPLETE subject ------------------------------------------------------
if [ -x "$FLEET" ]; then
  while IFS=$'\t' read -r ident _kind state _label slot _rest; do
    [ -n "${ident:-}" ] || continue
    [ "$state" = "COMPLETE" ] || continue
    warn "subject $ident is COMPLETE but still holds slot $slot"
  done < <("$FLEET" board --porcelain 2>/dev/null)
fi

# --- 4. the sync cron window -------------------------------------------------------------------------
#
# The 03:30 UTC sync (crontab -l) rewrites the live branch the release area is cut from. A gate that
# straddles it can measure a tree that changed under it mid-run. The gate has taken ~45 minutes on this
# box (scripts/release-gate.sh), so that is the window checked against, not a guess.
GATE_MINUTES=45
sync_line="$(crontab -l 2>/dev/null | awk '$0 !~ /^#/ && /sync\.sh/ {print; exit}')"
if [ -n "$sync_line" ]; then
  cron_min="$(awk '{print $1}' <<<"$sync_line")"
  cron_hour="$(awk '{print $2}' <<<"$sync_line")"
  if [[ "$cron_min" =~ ^[0-9]+$ ]] && [[ "$cron_hour" =~ ^[0-9]+$ ]]; then
    now_epoch="$(date -u +%s)"
    cron_epoch="$(date -u -d "today $cron_hour:$cron_min:00" +%s 2>/dev/null || true)"
    if [ -n "$cron_epoch" ]; then
      [ "$cron_epoch" -le "$now_epoch" ] && cron_epoch=$((cron_epoch + 86400))
      gate_end=$((now_epoch + GATE_MINUTES * 60))
      if [ "$cron_epoch" -le "$gate_end" ]; then
        mins_until=$(((cron_epoch - now_epoch) / 60))
        warn "a $GATE_MINUTES-minute gate started now would straddle the $cron_hour:$cron_min UTC sync cron, which fires in $mins_until minute(s)"
      fi
    fi
  fi
fi

# --- 5. orphaned verify worktrees (F7) ----------------------------------------------------------------
#
# Every abnormally-terminated `release-verify` leaves a `.fleet-v*.tmp` git worktree behind; the run that
# finishes normally cleans up after itself. The directory name is
# `.{dirname}.{pid}.{monotonic_ns}.{rand}.tmp` -- the creating pid is in the name, which is the whole
# reason this reaper is cheap: no lockfile, no registry, just the name and /proc.
#
# BOTH halves of the liveness test are required. Pids are reused by the kernel; `kill -0` alone would call
# a directory LIVE because some unrelated process happens to reuse its old pid, and reaping it mid-suite
# would produce a suite failure with no honest explanation. Checking /proc/<pid>/cmdline for
# `release-verify` is what tells "the pid that made this directory is still that run" from "the pid now
# means something else".
ORPHAN_RE='^\.fleet-v.*\.[0-9]+\.[0-9]+\.[0-9a-f]+\.tmp$'
orphans=()
if [ -n "${FLEET_RELEASES:-}" ]; then
  shopt -s nullglob
  for d in "$FLEET_RELEASES"/.fleet-v*.tmp; do
    base="$(basename "$d")"
    size="$(du -sh "$d" 2>/dev/null | cut -f1)"
    mtime="$(date -u -r "$d" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null)"
    if [[ "$base" =~ ^\.fleet-v.*\.([0-9]+)\.[0-9]+\.[0-9a-f]+\.tmp$ ]]; then
      pid="${BASH_REMATCH[1]}"
      live=0
      if kill -0 "$pid" 2>/dev/null \
        && tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | grep -q 'release-verify'; then
        live=1
      fi
      if [ "$live" = 1 ]; then
        echo "LIVE: $d (pid $pid is running release-verify) $size $mtime"
      else
        warn "ORPHAN $d $size $mtime"
        orphans+=("$d")
      fi
    else
      warn "$d does not match the orphan name pattern; leaving it alone"
    fi
  done
  shopt -u nullglob
else
  warn "FLEET_RELEASES is unset -- skipping the orphan check"
fi

# --- --reap: delete ONLY what was just reported ORPHAN, and only if its name matches exactly -----------
#
# This is the only deletion any script in this plan performs. `orphans` already holds only directories
# that (a) were classified ORPHAN above and (b) matched $ORPHAN_RE -- but the pattern is checked again
# here, literally, rather than trusted from the loop above: a deletion is refused, not guessed at.
if [ "$REAP" = 1 ]; then
  for d in "${orphans[@]}"; do
    base="$(basename "$d")"
    if [[ "$base" =~ $ORPHAN_RE ]]; then
      rm -rf -- "$d"
      echo "reaped: $d"
    else
      echo "$(basename "$0"): refusing to reap '$d' -- name does not match the orphan pattern exactly" >&2
    fi
  done
  git -C "$REPO" worktree prune
fi

exit 0
