#!/usr/bin/env bash
#
# Install or verify the superpowers skills for a codex CODEX_HOME (FB-111).
#
# Usage:  scripts/fleet-codex-skills.sh --codex-home <dir> [--releases <dir>] [--dry-run | --check]
#
# Writes exactly one thing: the symlink <codex-home>/skills/superpowers -> <releases>/current/skills, whose
# text names `current` rather than the version it resolves to today. codex follows it when it scans its
# skills, so every deploy moves codex workers onto the deployed skills, the way the marketplace entry in
# .claude/settings.json moves claude workers. There is nothing to refresh at deploy.
#
#   --dry-run   print what would change; write nothing
#   --check     verify only: exit 1 when the link does not follow `current` or a core skill is not visible
#
# Exit codes: 0 done or already in place; 1 --check failed; 2 bad input; 4 refused. It refuses, and leaves
# alone, anything at that path it did not write: a real directory, or a link that does not resolve to a
# superpowers skills tree.
#
# `--codex-home` is required and never defaulted: the target is an operator's codex configuration (on this
# box, <root>/.codex, which the login shell's `codex` function exports), and guessing it wrong writes into
# someone else's. `--releases` defaults to $FLEET_RELEASES, which scripts/fleet-env.sh sets.
#
# Why a symlink and not `codex plugin marketplace add` / `codex plugin add`: measured on codex-cli 0.156.1, the
# marketplace records the RESOLVED release (stale at the next deploy), and plugin add git-clones the source
# and copies a snapshot. See fleet/src/fleet/codex_skills.py.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
PYTHONPATH="$REPO/fleet/src${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m fleet.codex_skills "$@"
