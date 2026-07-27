#!/usr/bin/env bash
#
# base-check.sh — prove a workspace is positioned on the base the milestone is supposed to build on.
#
# The pool duplicates from the GOLDEN checkout (that is what makes the prebuilt native artifacts
# valid), but a milestone's work must stack on its LINEAGE base. Repositioning is the worker's first
# step — and forgetting it is invisible: the build succeeds, the tests pass, and the work is stacked
# on the pre-fix baseline. Two of five workers in one effort hit this. Verify it mechanically.
#
# Usage:
#   base-check.sh <todo-id>                         # expectation read from the dispatch record
#   base-check.sh --ws <dir> --expect "repo=sha,repo=sha"
# Exit: 0 all repos at the expected commit · 1 mismatch/missing · 2 bad input
set -uo pipefail

BOARD_DIR="${BOARD_DIR:-$HOME/.claude-dispatch-board}"
WS=""; EXPECT=""; GOLDEN_BASE=""; MODE="auto"

if [ $# -ge 1 ] && [ "${1#--}" = "$1" ]; then
  rec="$BOARD_DIR/records/$1.json"
  [ -f "$rec" ] || { echo "no dispatch record for '$1'" >&2; exit 2; }
  WS="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("ws",""))' "$rec")"
  EXPECT="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("lineage_base","") or "")' "$rec")"
  GOLDEN_BASE="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("golden_base","") or "")' "$rec")"
  [ -n "$EXPECT" ] || { echo "record '$1' has no lineage_base — pass --expect, or dispatch with --lineage-base" >&2; exit 2; }
  shift
fi
while [ $# -gt 0 ]; do
  case "$1" in
    --ws)     WS="${2:-}"; shift 2;;
    --expect) EXPECT="${2:-}"; shift 2;;
    --golden-base) GOLDEN_BASE="${2:-}"; shift 2;;
    --mode)   MODE="${2:-}"; shift 2;;
    --ws-head) shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
[ -n "$WS" ] && [ -d "$WS" ] || { echo "usage: base-check.sh <todo-id> | --ws <dir> --expect 'repo=sha,...'" >&2; exit 2; }
[ -n "$EXPECT" ] || { echo "no --expect given" >&2; exit 2; }

bad=0
IFS=',;' read -ra PAIRS <<< "$EXPECT"
for pair in "${PAIRS[@]}"; do
  pair="$(printf '%s' "$pair" | tr -d ' ')"
  [ -n "$pair" ] || continue
  repo="${pair%%=*}"; want="${pair#*=}"
  d="$WS/$repo"
  if [ ! -d "$d/.git" ]; then
    echo "MISSING: $repo is not a git repo in $WS"; bad=1; continue
  fi
  have="$(git -C "$d" rev-parse HEAD 2>/dev/null)"
  # A healthy worker occupies THREE legitimate states, not one:
  #   (a) exactly at the base — freshly repositioned
  #   (b) a DESCENDANT of it — a code milestone with commits on top (the intended end-state)
  #   (c) parked on the golden with the base fetched, read via refs — an analysis milestone, which
  #       is the better choice there because it keeps the prebuilt native artifacts valid.
  # Only (d) "the workspace does not even have this commit" is unambiguously broken.
  if [ "${have#"$want"}" != "$have" ] || [ "$have" = "$want" ]; then
    echo "ok: $repo at ${have:0:12} (at the base)"
  elif git -C "$d" merge-base --is-ancestor "$want" HEAD 2>/dev/null; then
    echo "ok: $repo at ${have:0:12} — a descendant of ${want:0:12} (work committed on top)"
  elif git -C "$d" cat-file -e "${want}^{commit}" 2>/dev/null; then
    if [ "$MODE" = "code" ]; then
      echo "MISMATCH: $repo has ${want:0:12} but is not on it (HEAD ${have:0:12}); --mode code requires it"
      echo "    git -C $d checkout --detach $want"
      bad=1
    else
      echo "advisory: $repo is at ${have:0:12}, base ${want:0:12} present but NOT checked out."
      echo "  Legitimate for an ANALYSIS milestone reading via refs (git diff/show) — and it keeps the"
      echo "  prebuilt native artifacts valid. Wrong for a CODE milestone: use --mode code to enforce."
    fi
  else
    echo "MISSING BASE: $repo does not have ${want:0:12} at all (HEAD ${have:0:12})"
    echo "  it can neither build on it nor read it:  git -C $d fetch --all"
    bad=1
  fi
done
# FIDELITY: the prebuilt native artifacts in this slot were built from the GOLDEN commit. Once the
# source is repositioned onto the lineage base they no longer correspond to it, so a test run
# exercises NEW source against OLD native code — a false green nobody can see. Warn, do not fail:
# a JVM-only milestone is legitimately unaffected, and an alarm that always fires gets ignored.
if [ -n "$GOLDEN_BASE" ]; then
  IFS=',;' read -ra GPAIRS <<< "$GOLDEN_BASE"
  for pair in "${GPAIRS[@]}"; do
    pair="$(printf '%s' "$pair" | tr -d ' ')"; [ -n "$pair" ] || continue
    repo="${pair%%=*}"; gsha="${pair#*=}"; d="$WS/$repo"
    [ -d "$d/.git" ] || continue
    have="$(git -C "$d" rev-parse HEAD 2>/dev/null)"
    [ "${have#"$gsha"}" != "$have" ] && continue           # still at the golden: artifacts match
    so="$(find "$d" -name '*.so' -print -quit 2>/dev/null)"
    [ -n "$so" ] || continue
    echo "WARNING: $repo has prebuilt native artifacts from the GOLDEN commit ${gsha:0:12},"
    echo "  but the source is now at ${have:0:12} (e.g. $(basename "$so"))."
    echo "  A test run here exercises NEW source against OLD native code — rebuild the native side,"
    echo "  or confirm this milestone touches no native code before trusting a green result."
  done
fi

[ "$bad" = 0 ] && echo "workspace positioned correctly: $WS"
exit "$bad"
