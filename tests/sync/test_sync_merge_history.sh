# tests/sync/test_sync_merge_history.sh — a merge on live must not be linearised into a
# duplicate replay.
#
# live's history is not always a straight line: reconciling a diverged copy of the fork
# (origin/live vs local live) leaves a merge whose two parents carry the SAME work twice.
# `git rebase --onto` drops the merge and replays BOTH parents in sequence, so every commit
# on the second parent is re-applied on top of its own already-applied twin. The real fork hit
# this with 119 duplicates behind one such merge: 119 hand resolutions, each one a chance to
# silently restore older content.
#
# Pausing on a genuine conflict is by design. What must NOT happen is the human paying one
# resolution per duplicate: the cost has to track real divergence, not the duplicated history.
# The setup merge is made with rerere OFF on purpose — with a recorded resolution rerere
# quietly patches over the duplicate replay and the bug looks harmless.
# shellcheck shell=bash
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config; . "$CTRL/config"

# live: five commits, each evolving the same file.
g "$FORK" checkout -q live
for i in 1 2 3 4 5; do
  printf 'V%s\n' "$i" > "$FORK/dup.md"; g "$FORK" add -A; g "$FORK" commit -qm "dup: V$i"
done

# The diverged copy: the same five commits made independently off the same base.
g "$FORK" checkout -q -b other v1.0.0
for i in 1 2 3 4 5; do
  printf 'V%s\n' "$i" > "$FORK/dup.md"; g "$FORK" add -A; g "$FORK" commit -qm "dup: V$i (twin)"
done

# Reconcile it into live, keeping live's content — the merge this fork actually has.
g "$FORK" checkout -q live
g "$FORK" -c rerere.enabled=false merge --no-commit other >/dev/null 2>&1 || true
printf 'V5\n' > "$FORK/dup.md"; g "$FORK" -c rerere.enabled=false add dup.md
g "$FORK" -c rerere.enabled=false commit -qm "merge: reconcile the diverged copy, keeping live" >/dev/null

add_release v1.1.0 "UPSTREAM-EDIT"                  # unrelated upstream work

run_sync

# Play the human: keep the already-built side of every conflict, then re-run finish.sh.
rounds=0
while [ -f "$CTRL/STATUS" ]; do
  rounds=$((rounds + 1))
  [ "$rounds" -gt 6 ] && { echo "FAIL: still conflicting after $rounds resolutions"; exit 1; }
  g "$WORKTREE" checkout --ours . >/dev/null 2>&1 || true
  g "$WORKTREE" add -A
  run_finish >/dev/null 2>&1 || true
done

# One merge really did conflict, so one resolution is legitimate. Five is the bug: one per twin.
[ "$rounds" -le 1 ] || { echo "FAIL: $rounds hand resolutions for 5 duplicated commits (expected at most 1)"; exit 1; }
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.1.0" base-advanced
assert_eq "$(cat "$FORK/dup.md")" "V5" newest-content-survived
assert_grep "UPSTREAM-EDIT" "$FORK/skills/foo/SKILL.md"
pass
