#!/usr/bin/env bash
# P-2 — every measurement run pins the source before and after. A run whose pin CHANGED is reported as
# CONTAMINATED, never as a result.
#
# This is the single control that let Pile 1 be separated from Pile 2 in the RCA: it-group5 pinned
# unprompted and could therefore prove its final pass ran against a stable tree, while §E's E4 rows
# turned out to be 37 iterations measured through another agent's half-written edit (FI-20's
# correction). Without a pin, a contaminated run is indistinguishable from a finding.
#
# Usage: source-pin.sh before <dir> | after <dir>     Exit(after): 0 stable · 1 CONTAMINATED
set -uo pipefail
phase="${1:?before|after}"; out="${2:?output dir}"
# Resolve the repo from THIS SCRIPT's location, not from the caller's cwd. A successor instant is a
# sibling folder and is NOT a git repo, so `git rev-parse --show-toplevel` failed there and the check
# reported "cannot export HEAD" — a control that only works when you are already standing in the right
# place is a control that fails in exactly the handoff it exists to protect (FI-34).
# The PACKAGE root (it/bin -> it -> fleet), because what this pins is src/*.py and tests/*.py.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 || { echo "$ROOT is not a git repo" >&2; exit 2; }
mkdir -p "$out"
pin() { (cd "$ROOT" && sha256sum src/fleet/*.py tests/*.py 2>/dev/null | sort); }
case "$phase" in
  before) pin > "$out/SOURCE-PIN-before.txt"; echo "pinned $(wc -l < "$out/SOURCE-PIN-before.txt") files";;
  after)  pin > "$out/SOURCE-PIN-after.txt"
          if diff -q "$out/SOURCE-PIN-before.txt" "$out/SOURCE-PIN-after.txt" >/dev/null; then
            echo "STABLE — every verdict in this run is attributable to one tree state"; exit 0
          fi
          { echo "CONTAMINATED — the source changed DURING this run. Every verdict is suspect."
            echo "Changed:"; diff "$out/SOURCE-PIN-before.txt" "$out/SOURCE-PIN-after.txt" \
              | grep '^[<>]' | awk '{print "  " $3}' | sort -u; } | tee "$out/SOURCE-CONTAMINATED.txt"
          exit 1;;
  *) echo "usage: source-pin.sh before|after <dir>" >&2; exit 2;;
esac
