#!/usr/bin/env bash
#
# `scripts/release-preflight.sh`, asserted against a scratch release area -- never the real one, and
# never a real tmux socket other than a throwaway one this test owns.
#
# The property worth testing is the one the header of the script under test exists to prevent: a wrong or
# missing socket must be a REFUSAL (exit 2), not a quiet, confident report -- because on screen the two
# look identical, and that is exactly what cost a release-day box its "this is quiet" read. Everything
# else here is advisory (exit 0), including the orphan reaper's findings, and the reaper itself must
# refuse anything whose name is not an exact match rather than guess.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SCRIPT="$REPO/scripts/release-preflight.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fails=0
note() { printf '  %s\n' "$*"; }
check() { # check <label> <expected> <actual>
  if [ "$2" = "$3" ]; then note "ok   $1"; else
    note "FAIL $1"; note "       wanted: [$2]"; note "       got:    [$3]"; fails=1
  fi
}

# --- the one hard refusal: FLEET_TMUX_SOCKET literally 'fleet' -----------------------------------------
out="$(FLEET_TMUX_SOCKET=fleet bash "$SCRIPT" 2>&1)"; rc=$?
check "socket=fleet exits 2" "2" "$rc"
printf '%s' "$out" | grep -q "DERIVED" \
  || { note "FAIL the refusal does not name the derivation (fleet-env.sh)"; fails=1; }

# --- the one hard refusal: FLEET_TMUX_SOCKET unset ------------------------------------------------------
out="$(env -u FLEET_TMUX_SOCKET bash "$SCRIPT" 2>&1)"; rc=$?
check "socket unset exits 2" "2" "$rc"

# --- everything past this point uses a derived-looking socket and a scratch release area --------------
SOCKET="rp-test-$$"
RELEASES="$TMP/releases"
mkdir -p "$RELEASES"
export FLEET_TMUX_SOCKET="$SOCKET"
export FLEET_RELEASES="$RELEASES"
export FLEET_LAUNCHER_TEST_BIN="/nonexistent/fleet" # check 3 (slots) must degrade quietly without a real fleet binary

# --- an orphan whose pid is not running --------------------------------------------------------------
# A pid this large is very unlikely to exist; if it somehow does, kill -0 would still need the cmdline to
# say `release-verify`, which a pid picked out of thin air will not.
DEAD_PID=999999
ORPHAN_DIR="$RELEASES/.fleet-v0.0.1.$DEAD_PID.1.abc.tmp"
mkdir -p "$ORPHAN_DIR"

out="$(bash "$SCRIPT" 2>&1)"; rc=$?
check "a normal run exits 0 even with warnings present" "0" "$rc"
printf '%s' "$out" | grep -q "ORPHAN $ORPHAN_DIR" \
  || { note "FAIL a dead-pid tmp dir was not reported ORPHAN"; note "$out"; fails=1; }

# --- reap removes exactly that one -----------------------------------------------------------------
bash "$SCRIPT" --reap >/dev/null 2>&1
if [ -d "$ORPHAN_DIR" ]; then note "FAIL --reap did not remove the dead-pid orphan"; fails=1
else note "ok   --reap removed the dead-pid orphan"; fi

# --- BOTH halves of the liveness test: a running pid whose cmdline is NOT release-verify is still an
# orphan. This is the assertion that would fail if the reaper were simplified to `kill -0` alone -- the
# exact simplification the header comment warns would reap a live run mid-suite on a reused pid.
SELF_PID=$$
NOTVERIFY_DIR="$RELEASES/.fleet-v0.0.2.$SELF_PID.2.def.tmp"
mkdir -p "$NOTVERIFY_DIR"
out="$(bash "$SCRIPT" 2>&1)"
printf '%s' "$out" | grep -q "ORPHAN $NOTVERIFY_DIR" \
  || { note "FAIL a live pid whose cmdline is not release-verify was not reported ORPHAN"; note "$out"; fails=1; }
printf '%s' "$out" | grep -q "LIVE: $NOTVERIFY_DIR" \
  && { note "FAIL a non-release-verify pid was reported LIVE -- both halves of the test did not run"; fails=1; }

bash "$SCRIPT" --reap >/dev/null 2>&1
if [ -d "$NOTVERIFY_DIR" ]; then note "FAIL --reap did not remove the live-pid-wrong-cmdline orphan"; fails=1
else note "ok   --reap removed the orphan whose pid is alive but is not release-verify"; fi

# --- a name that does not match the full pattern is refused, not guessed at ---------------------------
BADNAME_DIR="$RELEASES/.fleet-v0.0.1.tmp"
mkdir -p "$BADNAME_DIR"
out="$(bash "$SCRIPT" 2>&1)"
printf '%s' "$out" | grep -q "does not match the orphan name pattern" \
  || { note "FAIL a badly-named tmp dir was silently ignored instead of being called out"; fails=1; }
bash "$SCRIPT" --reap >/dev/null 2>&1
if [ -d "$BADNAME_DIR" ]; then note "ok   --reap left the non-matching name alone"
else note "FAIL --reap deleted a directory that did not match the exact orphan pattern"; fails=1; fi
rm -rf "$BADNAME_DIR"

# --- the normal shape of a real orphan: a read-only release export under fleet/it/Q/releases/... -------
# Every verify worktree that got as far as the IT suite's §Q has one of these (dr-xr-xr-x, by design --
# a deployed export is not writable), and `rm -rf` cannot unlink entries inside a directory with no write
# bit. This is not a corner case for the reaper; it is what most real orphans on this box look like.
RO_DIR="$RELEASES/.fleet-v0.0.3.$DEAD_PID.3.cafe.tmp"
mkdir -p "$RO_DIR/fleet/it/Q/releases/fleet-v0.1.0/bin"
echo "fleet" >"$RO_DIR/fleet/it/Q/releases/fleet-v0.1.0/bin/fleet"
chmod -R 0555 "$RO_DIR/fleet/it/Q/releases/fleet-v0.1.0"
out="$(bash "$SCRIPT" --reap 2>&1)"; rc=$?
check "--reap exits 0 against a read-only §Q export" "0" "$rc"
printf '%s' "$out" | grep -q "reaped: $RO_DIR" \
  || { note "FAIL no reaped: line for the read-only export"; note "$out"; fails=1; }
if [ -e "$RO_DIR" ]; then note "FAIL --reap left the read-only export in place"; fails=1
else note "ok   --reap removed a read-only §Q export after restoring write access"; fi

# --- the assertion that would have caught the real bug: a removal that genuinely fails must be reported
# FAILED, not reaped, and must make the run exit non-zero. A stub `rm` stands in for the real failure mode
# (permission denied deep inside a read-only export) because that failure is owner-fixable and therefore
# not reproducible as a fixture running as this test's own uid -- the stub reproduces the OBSERVABLE
# behaviour (rm exits non-zero, the tree survives) without needing root or a foreign owner.
STUBBORN_DIR="$RELEASES/.fleet-v0.0.4.$DEAD_PID.4.beef.tmp"
mkdir -p "$STUBBORN_DIR/keep"
mkdir -p "$TMP/bin"
cat >"$TMP/bin/rm" <<EOF
#!/usr/bin/env bash
# Test stub standing in for a real 'Permission denied' deep inside a read-only export: refuses to
# remove exactly the one directory this test is checking, and defers to the real rm for everything else
# (including the trap cleanup at exit, which never invokes this path again after the test below).
for a in "\$@"; do
  if [ "\$a" = "$STUBBORN_DIR" ]; then
    echo "rm: cannot remove '\$a': Permission denied (test stub)" >&2
    exit 1
  fi
done
exec /bin/rm "\$@"
EOF
chmod +x "$TMP/bin/rm"

out="$(PATH="$TMP/bin:$PATH" bash "$SCRIPT" --reap 2>&1)"; rc=$?
check "a directory rm genuinely cannot remove makes --reap exit non-zero" "1" "$rc"
printf '%s' "$out" | grep -q "FAILED: $STUBBORN_DIR" \
  || { note "FAIL no FAILED: line for the directory rm could not remove"; note "$out"; fails=1; }
printf '%s' "$out" | grep -q "reaped: $STUBBORN_DIR" \
  && { note "FAIL a directory rm could not remove was still reported reaped:"; fails=1; }
if [ -d "$STUBBORN_DIR" ]; then note "ok   the stubborn directory was left in place, not silently dropped"
else note "FAIL the stubborn directory is gone even though rm reported failure"; fails=1; fi
rm -rf "$STUBBORN_DIR"

# --- an orphan that is itself a SYMLINK must be refused BEFORE the chmod ------------------------------
# GNU `chmod -R` DEREFERENCES a symlink handed to it as a command-line ARGUMENT; it declines only to
# follow links it meets during traversal, and it is the traversal case an earlier adversarial review
# tested. Reproduced against the real script: modes on an unrelated tree well outside the release area
# went from dr-xr-xr-x/-r-xr-xr-x to drwxr-xr-x/-rwxr-xr-x. Nothing outside is deleted -- `rm -rf` removes
# only the link -- but this script's sanction is that it touches nothing outside the `.fleet-v*.tmp`
# pattern, and widening modes on an arbitrary tree breaks it. `Verify._worktree()` only ever creates real
# directories, so a symlink here is anomalous and refusing is the right answer.
OUTSIDE="$TMP/somebody-elses-tree"
mkdir -p "$OUTSIDE/sub"
echo important >"$OUTSIDE/sub/file"
chmod -R 0555 "$OUTSIDE"
modes_before="$(stat -c '%A %n' "$OUTSIDE" "$OUTSIDE/sub" "$OUTSIDE/sub/file")"
LINK_DIR="$RELEASES/.fleet-v0.0.5.$DEAD_PID.5.f00d.tmp"
ln -s "$OUTSIDE" "$LINK_DIR"

out="$(bash "$SCRIPT" --reap 2>&1)"; rc=$?
check "an orphan that is a symlink makes --reap exit non-zero" "1" "$rc"
printf '%s' "$out" | grep -q "refusing to reap '$LINK_DIR' -- it is a symlink" \
  || { note "FAIL the symlink orphan was not refused by name"; note "$out"; fails=1; }
modes_after="$(stat -c '%A %n' "$OUTSIDE" "$OUTSIDE/sub" "$OUTSIDE/sub/file")"
check "--reap changes no mode outside the release area when the orphan is a symlink" \
  "$modes_before" "$modes_after"
if [ -L "$LINK_DIR" ]; then note "ok   the refused symlink was left in place, not unlinked"
else note "FAIL the refused symlink was removed anyway"; fails=1; fi
if [ -d "$OUTSIDE" ]; then note "ok   the tree the symlink pointed at still exists"
else note "FAIL the tree outside the release area was deleted"; fails=1; fi
rm -f "$LINK_DIR"
chmod -R u+w "$OUTSIDE"
rm -rf "$OUTSIDE"

# --- `git worktree prune` runs only when EVERY reap in the batch succeeded ----------------------------
# `reaped_any` is batch-wide. Two orphans, A clean and B stubborn: `rm` has already deleted enough of B
# -- including its `.git` file -- for `git worktree` to read it as corrupt and drop the registration on
# the next prune, while most of B's directory is still on disk. That husk state already cost a manual
# cleanup once, and a batch-wide flag reintroduces it one orphan narrower. A stale registration left by a
# stubborn tree is harmless and prunable by hand; a stripped registration over a surviving tree is not.
#
# The `git` stub also keeps the test off the REAL repository: `--reap` otherwise runs
# `git -C <this checkout> worktree prune` for real, on every case above.
mkdir -p "$TMP/bin6"
GIT_LOG="$TMP/git-calls.log"
cat >"$TMP/bin6/git" <<EOF
#!/usr/bin/env bash
# Records and does nothing else. release-preflight.sh's only git call is \`worktree prune\`, so recording
# it is enough to observe whether it ran -- and not executing it keeps this test off the real checkout.
echo "\$*" >>"$GIT_LOG"
EOF
chmod +x "$TMP/bin6/git"

# Positive control FIRST, so the assertion below cannot pass because the stub simply never fires.
CLEAN_DIR="$RELEASES/.fleet-v0.0.6.$DEAD_PID.6.aaaa.tmp"
mkdir -p "$CLEAN_DIR/keep"
out="$(PATH="$TMP/bin6:$PATH" bash "$SCRIPT" --reap 2>&1)"; rc=$?
check "a batch where every reap succeeded exits 0" "0" "$rc"
grep -q "worktree prune" "$GIT_LOG" 2>/dev/null \
  || { note "FAIL an all-clean batch did not prune, so the assertion below proves nothing"; fails=1; }
: >"$GIT_LOG"

# Now the partial failure: A reaps cleanly, B's rm fails.
A_DIR="$RELEASES/.fleet-v0.0.7.$DEAD_PID.7.bbbb.tmp"
B_DIR="$RELEASES/.fleet-v0.0.8.$DEAD_PID.8.cccc.tmp"
mkdir -p "$A_DIR/keep" "$B_DIR/keep"
cat >"$TMP/bin6/rm" <<EOF
#!/usr/bin/env bash
for a in "\$@"; do
  if [ "\$a" = "$B_DIR" ]; then
    echo "rm: cannot remove '\$a': Permission denied (test stub)" >&2
    exit 1
  fi
done
exec /bin/rm "\$@"
EOF
chmod +x "$TMP/bin6/rm"

out="$(PATH="$TMP/bin6:$PATH" bash "$SCRIPT" --reap 2>&1)"; rc=$?
check "a batch with one failed reap exits non-zero" "1" "$rc"
printf '%s' "$out" | grep -q "reaped: $A_DIR" \
  || { note "FAIL the clean orphan in the batch was not reaped"; note "$out"; fails=1; }
printf '%s' "$out" | grep -q "FAILED: $B_DIR" \
  || { note "FAIL the stubborn orphan was not reported FAILED"; note "$out"; fails=1; }
if grep -q "worktree prune" "$GIT_LOG" 2>/dev/null; then
  note "FAIL a batch with a failed reap still pruned -- that strips a registration whose tree survives"
  fails=1
else
  note "ok   a batch with a failed reap did not prune, so no surviving tree loses its registration"
fi
rm -f "$TMP/bin6/rm"
chmod -R u+w "$B_DIR" 2>/dev/null
rm -rf "$A_DIR" "$B_DIR"

# --- another root's server on a socket named literally `fleet` is REPORTED, not skipped ---------------
# Release 0.6.3's I-1: the scan globbed `fleet-*` only, so the quanton root's server -- socket `fleet`, three
# live dt- sessions -- never appeared and preflight read as a quiet box. The servers below are throwaway
# ones this test starts on sockets under $TMP, reached through RELEASE_PREFLIGHT_TMUX_DIRS; no real server
# is read or touched, and both are killed by socket PATH on exit.
SOCKDIR="$TMP/tmux-sockets/"
mkdir -p "$SOCKDIR"
LEGACY="${SOCKDIR}fleet"; DERIVED="${SOCKDIR}fleet-rpother"
trap 'tmux -S "$LEGACY" kill-server 2>/dev/null; tmux -S "$DERIVED" kill-server 2>/dev/null; rm -rf "$TMP"' EXIT
tmux -S "$LEGACY" new-session -d -s dt-rp-legacy-one 'sleep 300'
tmux -S "$LEGACY" new-session -d -s dt-rp-legacy-two 'sleep 300'
tmux -S "$LEGACY" new-session -d -s not-a-dispatch 'sleep 300'
tmux -S "$DERIVED" new-session -d -s plain 'sleep 300'
out="$(RELEASE_PREFLIGHT_TMUX_DIRS="$SOCKDIR" bash "$SCRIPT" 2>&1)"; rc=$?
check "a run that finds another root's live work still exits 0 (advisory)" "0" "$rc"
printf '%s' "$out" | grep -qF "another root's socket ($LEGACY) has 2 live dt- session(s)" \
  || { note "FAIL the server on a socket named literally 'fleet' was not reported with its 2 dt- sessions"; note "$out"; fails=1; }
printf '%s' "$out" | grep -qF "socket $DERIVED: 0 live dt- session(s)" \
  || { note "FAIL a fleet-* socket with no dt- session was not listed with its zero count"; note "$out"; fails=1; }
tmux -S "$LEGACY" kill-server 2>/dev/null; tmux -S "$DERIVED" kill-server 2>/dev/null
[ "$fails" = 0 ] && note "ok   the legacy 'fleet' socket is reported with its dt- count, and a quiet fleet-* socket is listed with 0"

if [ "$fails" = 0 ]; then
  echo "PASS: release-preflight refuses (exit 2) only when FLEET_TMUX_SOCKET is unset or literally" \
       "'fleet' -- the environment fleet-env.sh guarantees can never be a real fleet socket -- reports" \
       "everything else as advisory WARN lines with exit 0, classifies a tmp worktree ORPHAN unless BOTH" \
       "its pid is alive AND that pid's cmdline says release-verify, and --reap deletes only directories" \
       "matching the exact orphan name pattern, leaving anything else alone; --reap also restores write" \
       "access to a read-only §Q export before removing it, reports FAILED (exit non-zero) rather" \
       "than reaped: for a directory it did not actually manage to remove, refuses an orphan that is" \
       "itself a symlink BEFORE the chmod that would otherwise widen modes on an arbitrary tree outside" \
       "the release area, prunes worktree registrations only when every reap in the batch succeeded," \
       "and reports another root's server on a socket named literally 'fleet' as well as 'fleet-*'"
  exit 0
fi
echo FAIL
exit 1
