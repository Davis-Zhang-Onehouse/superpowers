#!/usr/bin/env bash
#
# profile-check.sh — lint a dispatch profile against the coordination contract.
#
# Profiles live OUTSIDE any workspace and are globally mutable. When a coordinator finds a
# defect it usually patches the BRIEF for that one dispatch — so the profile stays broken and
# the next effort re-learns it a week later. (Real case: a profile told every worker to
# "update the CATALOG", contradicting the single-writer rule, and survived a whole effort.)
# Run this before selecting a profile, and after editing one.
#
# Usage:  profile-check.sh <profile-dir>
# Exit:   0 clean · 1 violations found · 2 bad input
set -uo pipefail

d="${1:-}"
[ -n "$d" ] && [ -d "$d" ] || { echo "usage: profile-check.sh <profile-dir>" >&2; exit 2; }
[ -f "$d/charter.md" ] || { echo "profile has no charter.md: $d" >&2; exit 2; }
text="$(cat "$d/charter.md" "$d/seed.txt" 2>/dev/null)"
bad=0
say(){ echo "  $1"; }

# Rules depend on WHAT KIND of instant the profile dispatches. Applying worker rules to a
# coordinator profile produces confident false alarms (the coordinator IS the catalog writer,
# and it does not report back to itself).
kind=worker
printf '%s' "$text" | grep -qiE '^Kind:.*COORDINATOR|Kind: \*\*COORDINATOR' && kind=coordinator
printf '%s' "$text" | grep -qiE '^Kind:.*COMPACTION|Kind: \*\*COMPACTION' && kind=compaction
echo "profile kind: $kind"

if [ "$kind" = coordinator ]; then
  # A coordinator OWNS the registry; the rule it must carry is that it GATES its workers.
  printf '%s' "$text" | grep -qiE 'review-workspace|workspace review|pdispatch gate' \
    || { say "MISSING gate duty: a coordinator profile must require gating each worker before harvest."; bad=1; }
else
  # 1) single-writer: a worker must never be told to write the canonical registry.
  if printf '%s' "$text" | grep -qiE '(update|edit|write|flip)[^.]{0,40}(the )?(m1 )?catalog(\.md)?\b' \
     && ! printf '%s' "$text" | grep -qiE 'propose|proposed delta|never edit the canonical|do NOT edit'; then
    say "VIOLATION single-writer: the profile tells the worker to update the catalog/registry."
    say "  The coordinator is the only writer; a worker delivers a PROPOSED delta."
    bad=1
  fi
  # 2) the completion gate must be in the contract the worker actually reads.
  printf '%s' "$text" | grep -qiE 'review-workspace|workspace review' \
    || { say "MISSING gate: no superpowers:review-workspace requirement before completion."; bad=1; }
  # 3) the coordinator's two completion signals must be demanded explicitly.
  printf '%s' "$text" | grep -qiE 'report' \
    || { say "MISSING report-back: the worker is never told to write a report the coordinator can find."; bad=1; }
  printf '%s' "$text" | grep -qiE 'renam|-complete-|complete-|transition' \
    || { say "MISSING rename: the worker is never told to transition its own folder to -complete-."; bad=1; }
fi

# 4) leftover template tokens mean the profile was edited carelessly.
if printf '%s' "$text" | grep -qE '\{\{[A-Z_]+\}\}'; then
  :  # placeholders are EXPECTED in a profile (they render at dispatch); not a violation.
fi

if [ "$bad" = 0 ]; then echo "profile OK: $d"; else echo "profile has violations: $d" >&2; fi
exit "$bad"
