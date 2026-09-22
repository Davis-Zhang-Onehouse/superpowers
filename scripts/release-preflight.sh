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

# Test seam, like FLEET above: the directories whose sockets section 2 scans. A test points it at a
# directory holding a throwaway server it owns, so the scan is exercised without reading any real server.
TMUX_SOCKET_DIRS="${RELEASE_PREFLIGHT_TMUX_DIRS:-/tmp/tmux-*/}"

# --- 1. this root ----------------------------------------------------------------------------------
n="$(count_dt_sessions "$FLEET_TMUX_SOCKET")"
[ "$n" -gt 0 ] && warn "this root ($FLEET_TMUX_SOCKET) has $n live dt- session(s)"

# --- 2. every other root -- the half the incident missed -------------------------------------------
#
# Another root's socket showing live work is not an error and not this root's business to touch -- it is
# an uncontrollable residual on a shared box, and refusing on it would make releases impossible here. It
# is still worth a WARN: a human deciding whether "now" is a good moment wants to know the box is busy.
#
# BOTH names a root's server can have: `fleet-<name>` (derived per root) AND literally `fleet`. The refusal
# above is about THIS shell's environment -- a bare `fleet` can never be the socket this root derives -- and
# says nothing about what other roots on the box run. A root on an older installation, which predates the
# per-root derivation, still serves its workers on `fleet`: on this box that was the quanton root with three
# live `dt-` sessions, and a `fleet-*` glob reported a quiet box over them (release 0.6.3's I-1). So `fleet`
# is scanned too, and every socket found gets a line with its count -- a socket that is listed with zero is
# a statement that it was looked at, where a socket that is never listed could equally have been missed.
# Read by PATH (`-S`), never by name: `-L` resolves the name under this shell's own TMUX_TMPDIR/uid, which
# is not necessarily the directory the glob found it in.
shopt -s nullglob
for sockdir in $TMUX_SOCKET_DIRS; do
  for sockpath in "$sockdir"fleet "$sockdir"fleet-*; do
    [ -S "$sockpath" ] || continue
    sockname="$(basename "$sockpath")"
    [ "$sockname" = "$FLEET_TMUX_SOCKET" ] && continue
    if ! sessions="$(tmux -S "$sockpath" ls -F '#{session_name}' 2>/dev/null)"; then
      echo "socket $sockpath: no server answering (a stale socket file, or not readable by this user)"
      continue
    fi
    n="$(printf '%s\n' "$sessions" | grep -c '^dt-')"
    if [ "$n" -gt 0 ]; then
      warn "another root's socket ($sockpath) has $n live dt- session(s) -- this box has live fleet work"
    else
      echo "socket $sockpath: 0 live dt- session(s)"
    fi
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
#
# A verify worktree that got as far as running the IT suite's §Q holds a release EXPORT under
# fleet/it/Q/releases/<version> -- made read-only (dr-xr-xr-x) by the release pipeline on purpose, because
# a deployed export is not writable. `rm -rf` cannot unlink entries inside a directory with no write bit,
# so it silently fails on exactly those paths unless something restores write access first. That
# restoration is scoped as tightly as the delete itself -- same pattern check, same ORPHAN
# classification, applied only to a path the delete is about to touch anyway -- so it cannot be pointed at
# anything the delete could not reach.
#
# Printing "reaped:" is not permission to assume it worked: this is the same defect shape the whole plan
# exists to eliminate (a control that reports success for work it did not do -- the piped gate reporting
# exit 0 over a dead run is the sibling case, quoted at the top of this file). So the directory's absence
# is checked, per directory, before anything is printed, and a `--reap` that could not reap exits non-zero
# -- one stubborn tree must not hide the others' success, but it also must not be reported as success.
if [ "$REAP" = 1 ]; then
  reap_failed=0
  reaped_any=0
  for d in "${orphans[@]}"; do
    base="$(basename "$d")"
    if [[ "$base" =~ $ORPHAN_RE ]]; then
      # A symlink is refused BEFORE the chmod, not reasoned about afterwards. GNU `chmod -R`
      # DEREFERENCES a symlink given as its command-line ARGUMENT -- it declines only to follow links it
      # meets during traversal, which is the case an earlier adversarial review tested; the argument case
      # escaped it. Reproduced: modes on an unrelated tree well outside the release area were widened
      # from `dr-xr-xr-x`/`-r-xr-xr-x` to `drwxr-xr-x`/`-rwxr-xr-x`. Nothing outside is deleted -- `rm -rf`
      # removes only the link -- so no file is lost, but modes are changed on an arbitrary tree, and this
      # script's whole sanction is that it never touches anything outside the `.fleet-v*.tmp` pattern.
      # `Verify._worktree()` only ever creates real directories, so a symlink here is anomalous and
      # refusing is the correct answer, not a limitation. Counted as a reap FAILURE, like every other
      # thing this loop could not do: it must not be reported as success, and it must not let the prune
      # below run over a registration whose tree is still there.
      if [ -L "$d" ]; then
        echo "$(basename "$0"): refusing to reap '$d' -- it is a symlink" >&2
        reap_failed=1
        continue
      fi
      chmod -R u+w -- "$d" 2>/dev/null || true
      rm_err="$(rm -rf -- "$d" 2>&1 1>/dev/null)"
      if [ -e "$d" ]; then
        echo "FAILED: $d -- ${rm_err:-still present after rm -rf}" >&2
        reap_failed=1
      else
        echo "reaped: $d"
        reaped_any=1
      fi
    else
      # Counted as a FAILURE, like every other thing this loop could not do. It is defence in depth --
      # `orphans` is only populated with names that already passed this same test -- but "refused" is
      # still "did not reap", and leaving it silent would let a `--reap` exit 0 having skipped a
      # directory it was asked to remove, and let the prune below run. That is the shape of every other
      # defect this file was written to close.
      echo "$(basename "$0"): refusing to reap '$d' -- name does not match the orphan pattern exactly" >&2
      reap_failed=1
    fi
  done
  # Pruning only after removals, and only if at least one actually succeeded: a failed reap must not
  # strip a worktree's registration while its directory is still on disk. That exact mismatch is what
  # turned three failed removals into unregistered half-deleted husks on this box -- `rm` had deleted
  # enough of each tree, including its `.git` file, for `git worktree` to read it as corrupt and drop the
  # registration on the next prune, even though most of the directory (the read-only skeleton) remained.
  # BOTH conditions, per orphan-batch. `reaped_any` alone is batch-wide: with two orphans where A reaps
  # cleanly and B's `rm -rf` deletes B's `.git` file and then fails on a read-only subtree, `reaped_any`
  # is 1, the prune runs, and it strips B's registration while B's directory is still on disk -- exactly
  # the husk state described above, one orphan narrower, and that state already cost a manual cleanup
  # once. A stale registration left behind by a stubborn tree is harmless and prunable by hand; a
  # stripped registration over a surviving tree is not.
  [ "$reaped_any" = 1 ] && [ "$reap_failed" = 0 ] && git -C "$REPO" worktree prune
  [ "$reap_failed" = 1 ] && exit 1
fi

exit 0
