#!/usr/bin/env bash
#
# with-skill-hidden.sh — capture an HONEST RED baseline for a skill's pressure tests.
#
# Once a skill is installed, a "baseline" subagent can discover and read it, so the RED run
# silently measures the skill instead of its absence. (That happened for real: a baseline agent
# quoted a string that existed only in the skill under test.) This hides the skill directory for
# the duration of one command and always restores it — even if the command fails or is killed.
#
# Usage:  with-skill-hidden.sh <skill-dir> -- <command...>
# Exit:   the command's exit code (2 on bad input)
set -uo pipefail

skill="${1:-}"; shift || true
[ "${1:-}" = "--" ] && shift || { echo "usage: with-skill-hidden.sh <skill-dir> -- <command...>" >&2; exit 2; }
[ -n "$skill" ] && [ -d "$skill" ] || { echo "no such skill dir: $skill" >&2; exit 2; }
[ $# -ge 1 ] || { echo "no command given" >&2; exit 2; }

hidden="$(dirname "$skill")/.hidden-$(basename "$skill").$$"
restore() {
  if [ -d "$hidden" ]; then
    mv "$hidden" "$skill" && echo "[with-skill-hidden] restored $skill" >&2
  fi
}
trap restore EXIT INT TERM HUP

mv "$skill" "$hidden" || { echo "could not hide $skill" >&2; exit 2; }
echo "[with-skill-hidden] $skill is hidden — running baseline" >&2
set +e
"$@"
rc=$?
set -e
exit $rc
