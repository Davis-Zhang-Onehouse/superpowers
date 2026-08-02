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
# Check the property this script actually needs — that ROOT holds the trees it is about to hash — and NOT
# "is this a git repo". The pin is `sha256sum src/fleet/*.py tests/*.py`; git is never consulted, so a
# git-repo precondition gates the control on something it does not use.
#
# It also reintroduced, one line below the comment warning against it, the very failure `FI-34` records:
# a control that only works where you are already standing in the right place. The release pipeline is
# where it bit — `fleet release-verify` runs the suite against a `git archive` export, which is the exact
# tree under test and has no `.git` by construction. Every runner that pins died with exit 2 ("is not a
# git repo"), `run-all.sh` reported CONTAMINATED, and a release that was in fact green could never be
# promoted. A precondition that is a PROXY for the real one is `OBS-44`'s family: a property that holds
# because two things usually travel together is not a property.
[ -d "$ROOT/src/fleet" ] && [ -d "$ROOT/tests" ] || {
  echo "$ROOT is not the fleet package root — expected src/fleet/ and tests/ beneath it" >&2; exit 2; }
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
