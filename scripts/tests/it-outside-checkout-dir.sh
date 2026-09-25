#!/usr/bin/env bash
# `it_outside_checkout_dir` (fleet/it/lib.sh): the directory a real-agent section (§P) builds its slot in.
#
# Claude Code bounds its folder-trust walk-up at the enclosing git toplevel, so the helper must return a
# directory in NO git work tree, even when the checkout's parent is itself a repository and even when the
# caller exported GIT_DIR (a hook, `git rebase -x`), which makes git describe some other repository. It
# also runs an `rm -rf`, so it must remove nothing but its own directory.
#
# Spends no claude and starts no tmux: the function is extracted from lib.sh and run over a scratch layout
# (HOME and every path are scratch), never by sourcing lib.sh into a section.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
TMP="$(cd "$TMP" && pwd -P)"

fails=0
note() { printf '  %s\n' "$*"; }
check() { if [ "$2" = "$3" ]; then note "ok   $1"; else note "FAIL $1 — wanted [$2] got [$3]"; fails=1; fi; }
git_q() { env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR -u GIT_CEILING_DIRECTORIES git "$@"; }
in_work_tree() { [ "$(git_q -C "$1" rev-parse --is-inside-work-tree 2>/dev/null)" = true ] && echo yes || echo no; }

FN="$(awk '/^it_outside_checkout_dir\(\) *\{/,/^}/' "$REPO/fleet/it/lib.sh")"
[ -n "$FN" ] || { echo "FAIL: it_outside_checkout_dir not found in fleet/it/lib.sh"; exit 1; }

# The nested layout: <T>/outer is a git repo; <T>/outer/checkout is a clone-like repo inside it, holding
# fleet/it (the helper's IT_ROOT). The first ancestor in no work tree is <T> itself.
T="$TMP/box"; OUTER="$T/outer"; CHECKOUT="$OUTER/checkout"; ITROOT="$CHECKOUT/fleet/it"
mkdir -p "$ITROOT"
git_q init -q "$OUTER"; git_q init -q "$CHECKOUT"
: > "$T/keep-file"; mkdir -p "$T/keep-dir" "$T/fleet-it-Y"; : > "$T/keep-dir/x"
: > "$T/fleet-it-Y/x"

helper() {   # helper <name> [VAR=value ...] -> prints the dir; rc passes through
  local name="$1"; shift
  #: Bounded: an unscrubbed GIT_WORK_TREE makes every `rev-parse --show-toplevel` answer the same dir, and the
  #: walk never ends (measured: `timeout` answers rc 124 at the bound).
  env HOME="$TMP/home" IT_ROOT="$ITROOT" FN="$FN" "$@" timeout 20 bash -c 'eval "$FN"; it_outside_checkout_dir "$0"' "$name"
}
mkdir -p "$TMP/home"

# --- 1. the checkout's parent is a repository ----------------------------------------------------------
dir="$(helper X)"; rc=$?
check "the helper succeeds in a nested layout" 0 "$rc"
check "its parent is the first non-repo ancestor" "$T" "$(dirname "$dir")"
check "the dir exists and is in no git work tree" "yes|no" "$([ -d "$dir" ] && echo yes || echo no)|$(in_work_tree "$dir")"

# --- 2. an exported GIT_DIR must not move the answer -----------------------------------------------------
# With GIT_DIR set, `git -C <dir> rev-parse --show-toplevel` answers <dir> for EVERY dir, so an unscrubbed
# walk runs to `/`.
dir2="$(helper X GIT_DIR="$OUTER/.git")"; rc=$?
check "GIT_DIR exported: the helper succeeds" 0 "$rc"
check "GIT_DIR exported: same parent" "$T" "$(dirname "$dir2")"
dir3="$(helper X GIT_DIR="$OUTER/.git" GIT_WORK_TREE="$OUTER" GIT_CEILING_DIRECTORIES="$CHECKOUT")"; rc=$?
check "GIT_DIR, GIT_WORK_TREE and GIT_CEILING_DIRECTORIES exported: same parent" "0|$T" "$rc|$(dirname "$dir3")"

# --- 3. it removes nothing unexpected -------------------------------------------------------------------
check "a sibling file survives" yes "$([ -f "$T/keep-file" ] && echo yes || echo no)"
check "a sibling dir and its content survive" yes "$([ -f "$T/keep-dir/x" ] && echo yes || echo no)"
check "another section's fleet-it-* dir survives" yes "$([ -f "$T/fleet-it-Y/x" ] && echo yes || echo no)"
check "the checkout and the outer repo survive" yes "$([ -d "$CHECKOUT/.git" ] && [ -d "$OUTER/.git" ] && echo yes || echo no)"

# --- 4. IT_REAL_AGENT_PARENT overrides the walk ---------------------------------------------------------
mkdir -p "$TMP/trusted"
dir4="$(helper X IT_REAL_AGENT_PARENT="$TMP/trusted")"; rc=$?
check "IT_REAL_AGENT_PARENT is the parent" "0|$TMP/trusted" "$rc|$(dirname "$dir4")"

# --- 5. RV-31: a STABLE name, so §P adds one projects[<cwd>] entry to the operator's Claude config, not one
# per run (Claude writes it itself for every cwd it starts in), and a SIGKILLed run leaves nothing new behind -------
p1="$(helper P)"; rc=$?
check "the §P dir is <parent>/fleet-it-P" "0|$T/fleet-it-P" "$rc|$p1"
: > "$p1/stale-from-a-killed-run"
p2="$(helper P)"; rc=$?
check "a second run gets the same path" "0|$p1" "$rc|$p2"
check "a dead run's leftovers are removed and the dir recreated" no \
  "$([ -e "$p2/stale-from-a-killed-run" ] && echo yes || echo no)"
check "the dir records the pid that owns it" yes "$([ -s "$p2/.it-pid" ] && echo yes || echo no)"

# --- 6. RV-31: a LIVE §P holding the dir is refused, exit 2, naming the pid; nothing of it is removed ----------
sleep 60 & live=$!
printf '%s\n' "$live" > "$p2/.it-pid"; : > "$p2/live-run-work"
err="$(helper P 2>&1 >/dev/null)"; rc=$?
check "a live holder: exit 2" 2 "$rc"
case "$err" in *"$live"*) note "ok   the refusal names the live pid ($live)" ;;
               *) note "FAIL the refusal does not name the live pid $live: [$err]"; fails=1 ;; esac
check "a live holder's files are untouched" yes "$([ -e "$p2/live-run-work" ] && echo yes || echo no)"
kill "$live" 2>/dev/null; wait "$live" 2>/dev/null
p3="$(helper P)"; rc=$?
check "once that pid is gone the dir is taken over" "0|$p1|no" "$rc|$p3|$([ -e "$p3/live-run-work" ] && echo yes || echo no)"

# --- 7. run-P.sh's rm guard matches the stable name, and only it --------------------------------------------
grep -q 'case "$P_DIR" in \*/fleet-it-P) rm -rf "$P_DIR"' "$REPO/fleet/it/run-P.sh" \
  && ! grep -q 'fleet-it-P-\*' "$REPO/fleet/it/run-P.sh" \
  && note "ok   run-P.sh removes only */fleet-it-P" || { note "FAIL run-P.sh's rm guard is not the stable */fleet-it-P pattern"; fails=1; }

if [ "$fails" = 0 ]; then echo "it-outside-checkout-dir: all ok"; else echo "it-outside-checkout-dir: FAILED"; fi
exit "$fails"
