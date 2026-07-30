#!/usr/bin/env bash
# P-1 — a commit asserting green is verified from an EXPORT of that commit, never from the tree that
# produced it. FI-31: a commit of mine said "715 tests green" while HEAD did not import, because the
# named file list did not close under its own imports and a suite run in the working tree cannot tell
# you what the commit contains.
#
# Usage: assert-head-green.sh [<rev>]     Exit: 0 green · 1 red · 2 could not even import
set -uo pipefail
REV="${1:-HEAD}"
# Resolve the repo from THIS SCRIPT's location, not from the caller's cwd. A successor instant is a
# sibling folder and is NOT a git repo, so `git rev-parse --show-toplevel` failed there and the check
# reported "cannot export HEAD" — a control that only works when you are already standing in the right
# place is a control that fails in exactly the handoff it exists to protect (FI-34).
# TWO paths, because they are two different things and conflating them is how this control broke before.
# `PKG` is the package root (it/bin -> it -> fleet): it holds src/ and tests/. `ROOT` is the GIT root, which
# is what can be exported — and fleet now lives in a SUBDIRECTORY of it, so the export must be entered at
# `$OFFSET` before src/ and tests/ mean anything.
PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROOT="$(git -C "$PKG" rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$ROOT" ] || { echo "$PKG is not inside a git repo" >&2; exit 2; }
git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 || { echo "$ROOT is not a git repo" >&2; exit 2; }
OFFSET="${PKG#"$ROOT"/}"; [ "$OFFSET" = "$PKG" ] && OFFSET="."
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
git -C "$ROOT" archive "$REV" | tar -x -C "$T" || { echo "cannot export $REV" >&2; exit 2; }
cd "$T/$OFFSET"
if ! PYTHONPATH=src python3 -c 'import fleet.cli' 2>"$T/.imp"; then
  echo "RED($REV): the export does not import — $(tail -1 "$T/.imp")"; exit 2
fi
out="$(PYTHONPATH=src timeout 600 python3 -m unittest discover -s tests 2>&1)"
tail -3 <<<"$out"
if grep -qE '^OK$' <<<"$out"; then echo "GREEN($REV): verified from an export, not from the working tree"; exit 0; fi
echo "RED($REV)"; exit 1
