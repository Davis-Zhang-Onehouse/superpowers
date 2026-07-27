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
WS=""; EXPECT=""

if [ $# -ge 1 ] && [ "${1#--}" = "$1" ]; then
  rec="$BOARD_DIR/records/$1.json"
  [ -f "$rec" ] || { echo "no dispatch record for '$1'" >&2; exit 2; }
  WS="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("ws",""))' "$rec")"
  EXPECT="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("lineage_base","") or "")' "$rec")"
  [ -n "$EXPECT" ] || { echo "record '$1' has no lineage_base — pass --expect, or dispatch with --lineage-base" >&2; exit 2; }
  shift
fi
while [ $# -gt 0 ]; do
  case "$1" in
    --ws)     WS="${2:-}"; shift 2;;
    --expect) EXPECT="${2:-}"; shift 2;;
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
  # accept an abbreviated expected sha
  if [ "${have#"$want"}" != "$have" ] || [ "$have" = "$want" ]; then
    echo "ok: $repo at ${have:0:12}"
  else
    echo "MISMATCH: $repo is at ${have:0:12} but expected ${want:0:12}"
    echo "  reposition before building, or this milestone stacks on the wrong base:"
    echo "    git -C $d fetch --all && git -C $d checkout --detach $want"
    bad=1
  fi
done
[ "$bad" = 0 ] && echo "workspace positioned correctly: $WS"
exit "$bad"
