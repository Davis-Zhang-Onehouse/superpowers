#!/usr/bin/env bash
# `ts_scratch_parent` (fleet/it/run-TS.sh): where §TS builds its scratch config root and its two slots.
#
# §TS asserts the pre-flight prediction (TS1c untrusted, TS2b trusted). Both fleet's trust walk and Claude
# 2.1.282's root finder treat ANY `.git` entry above a directory (a dir or a file, even an empty one) as a git
# root, so a stray `/tmp/.git` made both predictions UNKNOWN and failed the section on the environment, not the
# product. The chooser must pass over a candidate with a `.git` entry on itself or any ancestor, or one that
# `git -C` places in a work tree, and say which it rejected when none qualifies.
#
# Spends no claude and starts no tmux: the function is extracted from run-TS.sh and run over scratch dirs.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
#: The scratch layout itself must sit under no `.git` entry, or its "clean" candidate is not clean: a stray
#: `/tmp/.git` is the very case under test. /var/tmp first, then the system temp dir.
TMP=""
for base in /var/tmp "${TMPDIR:-/tmp}"; do
  d="$(cd "$base" 2>/dev/null && pwd -P)" || continue
  under=no; while :; do [ -e "$d/.git" ] && under=yes; [ "$d" = / ] && break; d="$(dirname "$d")"; done
  [ "$under" = no ] && TMP="$(mktemp -d -p "$base")" && break
done
[ -n "$TMP" ] || { echo "run-ts-scratch-root: SKIP — no scratch base outside every .git entry (/var/tmp, ${TMPDIR:-/tmp})"; exit 0; }
trap 'rm -rf "$TMP"' EXIT
TMP="$(cd "$TMP" && pwd -P)"

fails=0
note() { printf '  %s\n' "$*"; }
check() { if [ "$2" = "$3" ]; then note "ok   $1"; else note "FAIL $1 — wanted [$2] got [$3]"; fails=1; fi; }

FN="$(awk '/^ts_scratch_parent\(\) *\{/,/^}/' "$REPO/fleet/it/run-TS.sh")"
[ -n "$FN" ] || { echo "FAIL: ts_scratch_parent not found in fleet/it/run-TS.sh"; exit 1; }
#: RV-35: the `.git`-entry predicate it calls lives in lib.sh (shared with `it_outside_checkout_dir`).
PRED="$(awk '/^it_no_dot_git_above\(\) *\{/,/^}/' "$REPO/fleet/it/lib.sh")"
[ -n "$PRED" ] || { echo "FAIL: it_no_dot_git_above not found in fleet/it/lib.sh"; exit 1; }
FN="$PRED
$FN"
pick() { FN="$FN" bash -c 'eval "$FN"; ts_scratch_parent "$@"' _ "$@"; }

# A scratch layout: a/ has a fake (empty) .git dir above the first candidate; f/ has a .git FILE on the
# candidate itself; r/ is a real repository; clean/ has nothing.
mkdir -p "$TMP/a/.git" "$TMP/a/first" "$TMP/f" "$TMP/clean" "$TMP/r/sub"
: > "$TMP/f/.git"
git init -q "$TMP/r"

out="$(pick "$TMP/a/first" "$TMP/clean")"; rc=$?
check "a .git dir ABOVE the first candidate passes it over" "0|$TMP/clean" "$rc|$out"
out="$(pick "$TMP/f" "$TMP/clean")"; rc=$?
check "a .git FILE on the candidate itself passes it over" "0|$TMP/clean" "$rc|$out"
out="$(pick "$TMP/r/sub" "$TMP/clean")"; rc=$?
check "a candidate inside a real work tree is passed over" "0|$TMP/clean" "$rc|$out"
out="$(pick "" "$TMP/clean" "$TMP/a/first")"; rc=$?
check "an empty first candidate (TS_TMP_PARENT unset) is skipped" "0|$TMP/clean" "$rc|$out"
out="$(pick "$TMP/clean" "$TMP/a/first")"; rc=$?
check "the first qualifying candidate wins" "0|$TMP/clean" "$rc|$out"
out="$(pick "$TMP/missing" "$TMP/clean")"; rc=$?
check "a candidate that does not exist is passed over" "0|$TMP/clean" "$rc|$out"

# An exported GIT_DIR must not make a clean candidate look like a work tree.
out="$(GIT_DIR="$TMP/r/.git" GIT_WORK_TREE="$TMP/r" pick "$TMP/clean")"; rc=$?
check "GIT_DIR/GIT_WORK_TREE exported: the clean candidate still qualifies" "0|$TMP/clean" "$rc|$out"

# None qualifies: rc 1, and the answer names every candidate it rejected.
out="$(pick "$TMP/a/first" "$TMP/f" "$TMP/r/sub")"; rc=$?
check "no candidate qualifies: rc 1" 1 "$rc"
for d in "$TMP/a/first" "$TMP/f" "$TMP/r/sub"; do
  case "$out" in *"$d"*) note "ok   the rejection names $d" ;;
                 *) note "FAIL the rejection does not name $d: [$out]"; fails=1 ;; esac
done

# run-TS.sh wires it the way the finding asks.
TS="$REPO/fleet/it/run-TS.sh"
grep -q 'ts_scratch_parent "${TS_TMP_PARENT:-}" /tmp /var/tmp' "$TS" \
  && note "ok   run-TS.sh asks TS_TMP_PARENT, then /tmp, then /var/tmp" \
  || { note "FAIL run-TS.sh does not call ts_scratch_parent with TS_TMP_PARENT, /tmp, /var/tmp"; fails=1; }
grep -q 'SETUP: every candidate scratch parent sits under a .git entry' "$TS" \
  && note "ok   run-TS.sh skips TS1a with the SETUP reason" \
  || { note "FAIL run-TS.sh has no SETUP skip for TS1a"; fails=1; }
grep -q 'case "$TS_ROOT" in "$TS_PARENT"/fleet-it-ts.\*) rm -rf "$TS_ROOT"' "$TS" \
  && ! grep -q 'mktemp -d /tmp/fleet-it-ts' "$TS" \
  && note "ok   the rm guard is the chosen parent's fleet-it-ts.* only" \
  || { note "FAIL run-TS.sh's rm guard or mktemp still names /tmp"; fails=1; }

if [ "$fails" = 0 ]; then echo "run-ts-scratch-root: all ok"; else echo "run-ts-scratch-root: FAILED"; fi
exit "$fails"
