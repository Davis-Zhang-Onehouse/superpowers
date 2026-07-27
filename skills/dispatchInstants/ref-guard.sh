#!/usr/bin/env bash
#
# ref-guard.sh — enforce "shared reference checkouts are READ-ONLY; write via a worktree".
#
# Telling every worker not to write to a shared reference checkout is a rule that gets broken
# once and corrupts everyone. `protect` makes it physically read-only; `worktree` hands out the
# writable copy they actually needed; `check` reports whether a reference is still writable.
#
# Usage:
#   ref-guard.sh check    <ref-repo>              rc 0 = protected, 1 = still writable
#   ref-guard.sh protect  <ref-repo>              chmod -R a-w (idempotent)
#   ref-guard.sh worktree <ref-repo> <dest> [ref] create a writable git worktree at <dest>
set -uo pipefail

cmd="${1:-}"; ref="${2:-}"
[ -n "$cmd" ] && [ -n "$ref" ] || { sed -n '2,16p' "$0"; exit 2; }
[ -d "$ref" ] || { echo "no such path: $ref" >&2; exit 2; }

case "$cmd" in
  check)
    # Writable iff any tracked file/dir under the reference is user-writable.
    if [ -n "$(find "$ref" -path "$ref/.git" -prune -o -perm -u+w -print -quit 2>/dev/null)" ]; then
      echo "WRITABLE: $ref — a worker can corrupt this shared reference."
      echo "  Fix once:  ref-guard.sh protect $ref     (then use: ref-guard.sh worktree $ref <dest>)"
      exit 1
    fi
    echo "protected (read-only): $ref"; exit 0;;

  protect)
    chmod -R a-w "$ref" 2>/dev/null || true
    echo "protected (read-only): $ref"
    echo "  writable copies:  ref-guard.sh worktree $ref <dest> [git-ref]"
    exit 0;;

  worktree)
    dest="${3:-}"; gitref="${4:-HEAD}"
    [ -n "$dest" ] || { echo "usage: ref-guard.sh worktree <ref-repo> <dest> [git-ref]" >&2; exit 2; }
    if [ -d "$ref/.git" ] || git -C "$ref" rev-parse --git-dir >/dev/null 2>&1; then
      # A worktree needs to write .git/worktrees in the reference; allow just that, then re-protect.
      was_ro=0
      [ -w "$ref/.git" ] || { was_ro=1; chmod -R u+w "$ref/.git" 2>/dev/null || true; }
      if git -C "$ref" worktree add --detach "$dest" "$gitref" >/dev/null 2>&1; then
        [ "$was_ro" = 1 ] && chmod -R a-w "$ref/.git" 2>/dev/null || true
        echo "worktree ready (writable): $dest"; exit 0
      fi
      [ "$was_ro" = 1 ] && chmod -R a-w "$ref/.git" 2>/dev/null || true
      echo "git worktree failed for $ref" >&2; exit 1
    fi
    echo "not a git repo: $ref (cannot make a worktree)" >&2; exit 2;;

  *) echo "unknown subcommand: $cmd" >&2; exit 2;;
esac
