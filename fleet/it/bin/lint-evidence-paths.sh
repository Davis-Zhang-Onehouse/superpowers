#!/usr/bin/env bash
# P-3 — no evidence path outside the instant. Invariant 4: evidence is captured INTO the folder and
# referenced by relative path, because /tmp is gone on resume.
#
# FI-32: the proof for 9-of-9 concurrency passes -- the most valuable result of the build -- was cited by
# absolute /tmp path, one reboot from being an unbacked claim, in the results file for the section that
# justified the whole integration exercise.
set -uo pipefail
# Resolve the repo from THIS SCRIPT's location, not from the caller's cwd. A successor instant is a
# sibling folder and is NOT a git repo, so `git rev-parse --show-toplevel` failed there and the check
# reported "cannot export HEAD" — a control that only works when you are already standing in the right
# place is a control that fails in exactly the handoff it exists to protect (FI-34).
# Scoped to the PACKAGE root (it/bin -> it -> fleet), not to the git root. This invariant is about fleet's
# own evidence; scanning the whole skills repo would flag unrelated documents that legitimately quote an
# absolute path, and a control that reports other people's files gets switched off.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT" || { echo "cannot enter $ROOT" >&2; exit 2; }
bad=0
while IFS= read -r f; do
  [ -f "$f" ] || continue
  if hits="$(grep -nE '(^|[[:space:]"'"'"'(])/(tmp|home|var|root)/' "$f")"; then
    printf 'VIOLATION %s\n%s\n' "$f" "$hits" >&2; bad=1
  fi
done < <(find . -name 'RESULTS*.tsv' -o -name 'INDEX.md' -o -name 'RESULTS.md' 2>/dev/null | grep -v '/\.git/')
[ "$bad" = 0 ] && echo "OK: every evidence reference is instant-relative" || echo "evidence paths escape the instant" >&2
exit "$bad"
