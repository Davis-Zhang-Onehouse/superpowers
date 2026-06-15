# Superpowers Fork Auto-Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a zero-dependency shell+cron system that keeps a personal Superpowers fork rebased on the latest upstream release daily, auto-replaying known conflict resolutions and pausing on new ones, with a snapshot-tag version timeline, rollback/rework, audit log, and 90-day retention — serving the live Claude Code plugin straight from the fork's working tree.

**Architecture:** A control directory `~/.superpowers-sync/` holds small POSIX-bash scripts (`lib.sh`, `sync.sh`, `finish.sh`, `rollback.sh`) plus mutable state (`config`, `state`, `STATUS`, `PENDING`, `history.ndjson`). All rebases run in an isolated git worktree so a paused/conflicted rebase never disturbs the live working tree. Git tags/reflog/rerere provide versioning, rollback, and audit. Every script reads its settings from `$SPSYNC_CONFIG`, so the whole system is testable against a throwaway sandbox repo.

**Tech Stack:** bash, git (worktree, rerere, rebase --onto, annotated tags), cron, `gh` (one-time fork only). No third-party dependencies. Tests are plain bash with a sandbox harness.

---

## File Structure

| Path | Responsibility |
|------|----------------|
| `~/.superpowers-sync/config` | Static settings (paths, remote, retention, refresh cmd). Sourced by every script. |
| `~/.superpowers-sync/state` | Mutable `BASE_TAG=...` — the upstream tag `live` is built on. |
| `~/.superpowers-sync/lib.sh` | Shared functions: load config/state, latest tag, state writer, event logger, prune, finalize, rerere-aware rebase. |
| `~/.superpowers-sync/sync.sh` | Daily driver (cron entry point). |
| `~/.superpowers-sync/finish.sh` | Completes a paused, manually-resolved rebase. |
| `~/.superpowers-sync/rollback.sh` | `list` / `to` / `rework` / `promote`. |
| `~/.superpowers-sync/STATUS` | Present only while paused; drives shell banner. |
| `~/.superpowers-sync/PENDING` | Target tag of an in-progress paused rebase. |
| `~/.superpowers-sync/history.ndjson` | Append-only audit log. |
| `~/.superpowers-sync/rebase-wt/` | Throwaway git worktree for rebases. |
| `<repo>/tests/sync/harness.sh` | Sandbox builder + asserts for tests (lives in the fork so it's versioned). |
| `<repo>/tests/sync/test_*.sh` | Behavior tests. |

The scripts are developed in `<repo>/scripts/sync/` (versioned in the fork) and **installed** (copied/symlinked) into `~/.superpowers-sync/` during bootstrap. Developing them inside the fork means they ride the same snapshot/version timeline as the skills.

---

## Task 1: Verify live-vs-cached marketplace behavior (the gating experiment)

**Why first:** The spec's one unknown. If a local-path marketplace serves the live working tree, no refresh step is needed. If it copies into cache, every finalize must re-register. This task's outcome sets `SPSYNC_REFRESH_CMD` in config.

**Files:** none (investigation only; record findings in the plan's notes / commit message).

- [ ] **Step 1: Create a scratch local marketplace from a copy**

```bash
mkdir -p /tmp/sp-exp && cp -r /home/ubuntu/superpowers /tmp/sp-exp/repo
claude plugin marketplace add /tmp/sp-exp/repo --scope local 2>&1 | tail -5
```
Expected: "Successfully added marketplace" (note the marketplace name it prints).

- [ ] **Step 2: Inspect whether install references the path or copies to cache**

```bash
claude plugin install superpowers@<name-from-step-1> --scope local 2>&1 | tail -5
cat ~/.claude/plugins/installed_plugins.json | grep -A6 'superpowers@<name>'
```
Look at `installPath`. If it points **into `/tmp/sp-exp/repo`** → live working tree (good). If it points into `~/.claude/plugins/cache/...` → it copied.

- [ ] **Step 3: Confirm by editing and diffing**

```bash
echo "# EXPERIMENT MARKER" >> /tmp/sp-exp/repo/skills/brainstorming/SKILL.md
# find what the install actually serves:
find ~/.claude/plugins -path '*brainstorming/SKILL.md' -newer /tmp/sp-exp/repo/package.json 2>/dev/null
grep -rl "EXPERIMENT MARKER" ~/.claude/plugins/ /tmp/sp-exp/repo 2>/dev/null
```
If the marker appears only in `/tmp/sp-exp/repo` and the install path is the cache → copy behavior. If install path is the repo → live.

- [ ] **Step 4: Record the verdict and clean up**

```bash
claude plugin uninstall superpowers@<name> --scope local 2>&1 | tail -2
claude plugin marketplace remove <name> 2>&1 | tail -2
rm -rf /tmp/sp-exp
```
Write the verdict into the commit message:
- **LIVE** → `SPSYNC_REFRESH_CMD=""` (empty) in Task 3 config.
- **COPY** → `SPSYNC_REFRESH_CMD="claude plugin marketplace update <name> && claude plugin update superpowers@<name>"` in Task 3 config.

- [ ] **Step 5: Commit the finding**

```bash
git commit --allow-empty -m "experiment: local marketplace serves <LIVE|COPY> — set refresh accordingly"
```

---

## Task 2: Test harness (sandbox builder)

**Files:**
- Create: `tests/sync/harness.sh`

- [ ] **Step 1: Write the harness**

```bash
# tests/sync/harness.sh — source this from each test. Builds an isolated sandbox.
set -euo pipefail

SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
UPSTREAM="$SANDBOX/upstream"
FORK="$SANDBOX/fork"
CTRL="$SANDBOX/ctrl"
SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../scripts/sync" && pwd)"

g() { git -C "$1" "${@:2}"; }   # g <repo> <git args...>

make_upstream() {
  git init -q "$UPSTREAM"
  g "$UPSTREAM" config user.email t@t; g "$UPSTREAM" config user.name t
  mkdir -p "$UPSTREAM/skills/foo"
  printf 'line1\nline2\nline3\n' > "$UPSTREAM/skills/foo/SKILL.md"
  g "$UPSTREAM" add -A; g "$UPSTREAM" commit -qm v1
  g "$UPSTREAM" tag v1.0.0
}

# add_release <tag> <new-foo-line2>   (changes line2 of foo to create rebase work/conflict)
add_release() {
  printf 'line1\n%s\nline3\n' "$2" > "$UPSTREAM/skills/foo/SKILL.md"
  g "$UPSTREAM" add -A; g "$UPSTREAM" commit -qm "$1"
  g "$UPSTREAM" tag "$1"
}

make_fork() {
  git clone -q "$UPSTREAM" "$FORK"
  g "$FORK" remote rename origin upstream
  g "$FORK" config user.email me@me; g "$FORK" config user.name me
  g "$FORK" checkout -q -b live v1.0.0
}

# add a custom commit on live. $1=relpath $2=content
fork_custom() {
  mkdir -p "$FORK/$(dirname "$1")"
  printf '%s\n' "$2" > "$FORK/$1"
  g "$FORK" add -A; g "$FORK" commit -qm "custom: $1"
}

make_config() {
  mkdir -p "$CTRL"
  cat > "$CTRL/config" <<EOF
REPO="$FORK"
LIVE_BRANCH="live"
UPSTREAM_REMOTE="upstream"
CONTROL_DIR="$CTRL"
WORKTREE="$CTRL/rebase-wt"
STATE_FILE="$CTRL/state"
STATUS_FILE="$CTRL/STATUS"
PENDING_FILE="$CTRL/PENDING"
HISTORY="$CTRL/history.ndjson"
RETENTION_DAYS=90
SPSYNC_REFRESH_CMD=""
EOF
  echo "BASE_TAG=v1.0.0" > "$CTRL/state"
}

run_sync()    { SPSYNC_CONFIG="$CTRL/config" bash "$SCRIPTS/sync.sh"; }
run_finish()  { SPSYNC_CONFIG="$CTRL/config" bash "$SCRIPTS/finish.sh"; }
run_rollback(){ SPSYNC_CONFIG="$CTRL/config" bash "$SCRIPTS/rollback.sh" "$@"; }

assert_eq()   { [ "$1" = "$2" ] || { echo "FAIL @ ${3:-}: expected [$2] got [$1]"; exit 1; }; }
assert_file() { [ -f "$1" ]   || { echo "FAIL: missing file $1"; exit 1; }; }
assert_nofile(){ [ ! -f "$1" ]|| { echo "FAIL: unexpected file $1"; exit 1; }; }
assert_grep() { grep -q "$1" "$2" || { echo "FAIL: '$1' not in $2"; exit 1; }; }
pass()        { echo "PASS: ${0##*/}"; }
```

- [ ] **Step 2: Commit**

```bash
git add tests/sync/harness.sh
git commit -m "test: sandbox harness for sync scripts"
```

---

## Task 3: Config template + lib.sh (loaders, state, logging, prune)

**Files:**
- Create: `scripts/sync/config.template`
- Create: `scripts/sync/lib.sh`
- Test: `tests/sync/test_lib.sh`

- [ ] **Step 1: Write the failing test**

```bash
# tests/sync/test_lib.sh
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config

SPSYNC_CONFIG="$CTRL/config" bash -c '
  . "$SPSYNC_CONFIG"; . "'"$SCRIPTS"'/lib.sh"; load_state
  assert_eq "$BASE_TAG" "v1.0.0" base
  set_state BASE_TAG v9.9.9
  load_state
  assert_eq "$BASE_TAG" "v9.9.9" base-after-set
  log_event clean v9.9.9 snapshot/x
'
assert_grep '"result":"clean"' "$CTRL/history.ndjson"
# prune drops >90d lines, keeps recent
printf '%s\n' '{"ts":"2000-01-01T00:00:00Z","result":"old"}' >> "$CTRL/history.ndjson"
SPSYNC_CONFIG="$CTRL/config" bash -c '. "$SPSYNC_CONFIG"; . "'"$SCRIPTS"'/lib.sh"; prune_history'
grep -q '"old"' "$CTRL/history.ndjson" && { echo "FAIL: old line not pruned"; exit 1; }
pass
```

- [ ] **Step 2: Run it to verify it fails**

Run: `bash tests/sync/test_lib.sh`
Expected: FAIL — `lib.sh` not found / functions undefined.

- [ ] **Step 3: Write `scripts/sync/config.template`**

```bash
# Installed to ~/.superpowers-sync/config by bootstrap. Edit paths as needed.
REPO="__REPO__"
LIVE_BRANCH="live"
UPSTREAM_REMOTE="upstream"
CONTROL_DIR="$HOME/.superpowers-sync"
WORKTREE="$CONTROL_DIR/rebase-wt"
STATE_FILE="$CONTROL_DIR/state"
STATUS_FILE="$CONTROL_DIR/STATUS"
PENDING_FILE="$CONTROL_DIR/PENDING"
HISTORY="$CONTROL_DIR/history.ndjson"
RETENTION_DAYS=90
# Set by Task 1 experiment: empty if plugin serves the live tree, else a refresh command.
SPSYNC_REFRESH_CMD=""
```

- [ ] **Step 4: Write `scripts/sync/lib.sh`**

```bash
# Shared helpers. Caller must have already sourced $SPSYNC_CONFIG.
g() { git -C "$1" "${@:2}"; }

load_state() { [ -f "$STATE_FILE" ] && . "$STATE_FILE" || true; }

set_state() { # set_state KEY VALUE  (idempotent rewrite)
  local k="$1" v="$2" tmp; tmp="$(mktemp)"
  touch "$STATE_FILE"
  grep -v "^$k=" "$STATE_FILE" > "$tmp" || true
  printf '%s=%s\n' "$k" "$v" >> "$tmp"
  mv "$tmp" "$STATE_FILE"
}

latest_tag() { # highest semver vX.Y.Z tag known to the repo
  g "$REPO" tag -l 'v*' --sort=-v:refname | head -n1
}

log_event() { # log_event RESULT NEWTAG SNAPSHOT [conflicts]
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"ts":"%s","result":"%s","base":"%s","new":"%s","snapshot":"%s","conflicts":"%s"}\n' \
    "$ts" "$1" "${BASE_TAG:-}" "${2:-}" "${3:-}" "${4:-}" >> "$HISTORY"
}

prune_history() { # drop ndjson lines whose ts is older than RETENTION_DAYS
  [ -f "$HISTORY" ] || return 0
  local cutoff tmp; cutoff="$(date -u -d "-${RETENTION_DAYS} days" +%Y-%m-%dT%H:%M:%SZ)"
  tmp="$(mktemp)"
  while IFS= read -r line; do
    local ts; ts="$(printf '%s' "$line" | sed -n 's/.*"ts":"\([^"]*\)".*/\1/p')"
    [ -z "$ts" ] || [ "$ts" \> "$cutoff" ] && printf '%s\n' "$line" >> "$tmp"
  done < "$HISTORY"
  mv "$tmp" "$HISTORY"
}

prune_snapshots() { # delete snapshot/* tags older than RETENTION_DAYS
  local cutoff; cutoff="$(date -u -d "-${RETENTION_DAYS} days" +%s)"
  g "$REPO" for-each-ref --format='%(refname:short) %(creatordate:unix)' 'refs/tags/snapshot/*' |
  while read -r tag epoch; do
    [ "$epoch" -lt "$cutoff" ] && g "$REPO" tag -d "$tag" >/dev/null
  done
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `bash tests/sync/test_lib.sh`
Expected: `PASS: test_lib.sh`

- [ ] **Step 6: Commit**

```bash
git add scripts/sync/config.template scripts/sync/lib.sh tests/sync/test_lib.sh
git commit -m "feat: sync config template + lib (state, logging, prune)"
```

---

## Task 4: `sync.sh` — rerere-aware rebase in isolated worktree

**Files:**
- Create: `scripts/sync/sync.sh`
- Test: `tests/sync/test_sync_clean.sh`, `tests/sync/test_sync_noop_dirty.sh`

- [ ] **Step 1: Write the failing test (clean rebase)**

```bash
# tests/sync/test_sync_clean.sh
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config
fork_custom "skills/mine/SKILL.md" "my custom skill"   # custom commit on live
add_release v1.1.0 "line2-upstream-changed"            # new upstream release, no overlap with mine

run_sync

# live now based on v1.1.0, custom commit replayed, upstream change present
assert_eq "$(g "$FORK" describe --tags --abbrev=0 live~1 2>/dev/null || echo none)" "v1.1.0" rebased-onto
assert_file "$FORK/skills/mine/SKILL.md"
assert_grep "line2-upstream-changed" "$FORK/skills/foo/SKILL.md"
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.1.0" base-updated
assert_eq "$(g "$FORK" tag -l 'snapshot/*' | wc -l | tr -d ' ')" "1" one-snapshot
assert_grep '"result":"clean"' "$CTRL/history.ndjson"
assert_nofile "$CTRL/STATUS"
pass
```

- [ ] **Step 2: Run to verify it fails**

Run: `bash tests/sync/test_sync_clean.sh`
Expected: FAIL — `sync.sh` missing.

- [ ] **Step 3: Write `scripts/sync/sync.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${SPSYNC_CONFIG:=$HOME/.superpowers-sync/config}"
. "$SPSYNC_CONFIG"
. "$(dirname "$0")/lib.sh"
load_state

# Don't start a new sync while a paused rebase awaits resolution.
if [ -f "$STATUS_FILE" ]; then
  echo "A rebase is paused — resolve it and run finish.sh (see $STATUS_FILE)."; exit 0
fi

g "$REPO" fetch "$UPSTREAM_REMOTE" --tags --quiet
NEW="$(latest_tag)"

if [ "$NEW" = "$BASE_TAG" ]; then
  log_event noop "$NEW" ""; prune_history; prune_snapshots; exit 0
fi

# Safety: never clobber in-progress edits in the live tree.
if ! g "$REPO" diff --quiet || ! g "$REPO" diff --cached --quiet; then
  log_event skipped-dirty "$NEW" ""
  echo "Live tree has uncommitted changes; skipping sync to $NEW."; exit 0
fi

# Fresh isolated worktree on a temp branch copied from live.
g "$REPO" worktree prune
rm -rf "$WORKTREE"
g "$REPO" worktree add -f -B sync-rebase "$WORKTREE" "$LIVE_BRANCH" >/dev/null

# rerere-aware rebase: auto-continue when rerere resolved everything; pause on new conflicts.
rebase_step() {
  g "$WORKTREE" -c rerere.enabled=true -c rerere.autoupdate=true \
     rebase --onto "$NEW" "$BASE_TAG" sync-rebase
}
continue_step() { GIT_EDITOR=true g "$WORKTREE" rebase --continue; }

result="clean"
if ! rebase_step; then
  while true; do
    if g "$WORKTREE" diff --name-only --diff-filter=U | grep -q .; then
      result="paused"; break                      # genuine new conflict
    fi
    if continue_step; then result="rerere-resolved"; break; fi
    # else loop: rerere staged this step, continue moves to next
  done
fi

if [ "$result" = "paused" ]; then
  conflicts="$(g "$WORKTREE" diff --name-only --diff-filter=U | tr '\n' ',' )"
  echo "$NEW" > "$PENDING_FILE"
  printf '%s\n' "⚠ superpowers rebase PAUSED in $WORKTREE onto $NEW — conflicts: ${conflicts%,}. cd there, resolve, 'git rebase --continue', then run finish.sh" > "$STATUS_FILE"
  log_event paused "$NEW" "" "${conflicts%,}"
  exit 0
fi

# Success — adopt the rebased branch into live and snapshot.
finalize_live "$NEW" "$result"
```

`finalize_live` is added to `lib.sh` in Step 4.

- [ ] **Step 4: Add `finalize_live` to `scripts/sync/lib.sh`**

```bash
finalize_live() { # finalize_live NEWTAG RESULT  — adopt sync-rebase into live, snapshot, log, prune, refresh
  local newtag="$1" result="$2" stamp
  g "$REPO" reset --hard sync-rebase >/dev/null   # live is checked out & clean (verified)
  g "$REPO" worktree remove --force "$WORKTREE" 2>/dev/null || true
  g "$REPO" branch -D sync-rebase >/dev/null 2>&1 || true
  set_state BASE_TAG "$newtag"
  stamp="snapshot/$(date +%Y-%m-%d-%H%M%S)"
  g "$REPO" tag -a "$stamp" -m "sync onto $newtag ($result)"
  log_event "$result" "$newtag" "$stamp"
  prune_history; prune_snapshots
  [ -n "${SPSYNC_REFRESH_CMD:-}" ] && eval "$SPSYNC_REFRESH_CMD" || true
}
```

- [ ] **Step 5: Write the no-op + dirty test**

```bash
# tests/sync/test_sync_noop_dirty.sh
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config
run_sync                                            # no new tag → no-op
assert_grep '"result":"noop"' "$CTRL/history.ndjson"
assert_eq "$(g "$FORK" tag -l 'snapshot/*' | wc -l | tr -d ' ')" "0" no-snapshot-on-noop

add_release v1.1.0 "x"
echo "dirty" >> "$FORK/skills/foo/SKILL.md"         # uncommitted edit
run_sync
assert_grep '"result":"skipped-dirty"' "$CTRL/history.ndjson"
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.0.0" base-unchanged-when-dirty
pass
```

- [ ] **Step 6: Run both tests**

Run: `bash tests/sync/test_sync_clean.sh && bash tests/sync/test_sync_noop_dirty.sh`
Expected: `PASS: test_sync_clean.sh` and `PASS: test_sync_noop_dirty.sh`

- [ ] **Step 7: Commit**

```bash
chmod +x scripts/sync/sync.sh
git add scripts/sync/sync.sh scripts/sync/lib.sh tests/sync/test_sync_clean.sh tests/sync/test_sync_noop_dirty.sh
git commit -m "feat: sync.sh rerere-aware rebase in isolated worktree"
```

---

## Task 5: Conflict pause + rerere replay + `finish.sh`

**Files:**
- Create: `scripts/sync/finish.sh`
- Test: `tests/sync/test_conflict_finish.sh`, `tests/sync/test_rerere_replay.sh`

- [ ] **Step 1: Write the conflict→finish test**

```bash
# tests/sync/test_conflict_finish.sh
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config
# custom commit edits the SAME line upstream will change → conflict
g "$FORK" checkout -q live
printf 'line1\nMY-EDIT\nline3\n' > "$FORK/skills/foo/SKILL.md"
g "$FORK" add -A; g "$FORK" commit -qm "custom: edit foo line2"
add_release v1.1.0 "UPSTREAM-EDIT"

run_sync
assert_file "$CTRL/STATUS"                          # paused
assert_grep "PAUSED" "$CTRL/STATUS"
assert_eq "$(cat "$CTRL/PENDING")" "v1.1.0" pending-tag
# live tree must be untouched (isolation invariant)
assert_grep "MY-EDIT" "$FORK/skills/foo/SKILL.md"
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.0.0" base-still-old

# user resolves in the worktree, keeping MY-EDIT
printf 'line1\nMY-EDIT\nline3\n' > "$WORKTREE/skills/foo/SKILL.md"
g "$WORKTREE" add skills/foo/SKILL.md
GIT_EDITOR=true g "$WORKTREE" -c rerere.enabled=true rebase --continue

run_finish
assert_nofile "$CTRL/STATUS"
assert_nofile "$CTRL/PENDING"
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.1.0" base-advanced
assert_grep "MY-EDIT" "$FORK/skills/foo/SKILL.md"   # live now updated, edit preserved
assert_grep '"result":"manual-resolved"' "$CTRL/history.ndjson"
pass
```

- [ ] **Step 2: Run to verify it fails**

Run: `bash tests/sync/test_conflict_finish.sh`
Expected: FAIL — `finish.sh` missing.

- [ ] **Step 3: Write `scripts/sync/finish.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${SPSYNC_CONFIG:=$HOME/.superpowers-sync/config}"
. "$SPSYNC_CONFIG"
. "$(dirname "$0")/lib.sh"
load_state

[ -f "$STATUS_FILE" ] || { echo "No paused rebase."; exit 0; }
NEW="$(cat "$PENDING_FILE")"

# Refuse if the rebase isn't actually finished in the worktree.
rebase_dir="$(g "$WORKTREE" rev-parse --git-path rebase-merge 2>/dev/null || true)"
if [ -n "$rebase_dir" ] && [ -d "$WORKTREE/$rebase_dir" -o -d "$rebase_dir" ]; then
  echo "Rebase still in progress in $WORKTREE — resolve conflicts and run 'git rebase --continue' first."
  exit 1
fi

finalize_live "$NEW" "manual-resolved"
rm -f "$STATUS_FILE" "$PENDING_FILE"
echo "Resolved and applied: live now on $NEW. Changes load on your next Claude session."
```

- [ ] **Step 4: Run the finish test**

Run: `bash tests/sync/test_conflict_finish.sh`
Expected: `PASS: test_conflict_finish.sh`

- [ ] **Step 5: Write the rerere-replay test**

```bash
# tests/sync/test_rerere_replay.sh — same conflict twice auto-resolves the 2nd time
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config
g "$FORK" config rerere.enabled true
g "$FORK" checkout -q live
printf 'line1\nMY-EDIT\nline3\n' > "$FORK/skills/foo/SKILL.md"
g "$FORK" add -A; g "$FORK" commit -qm "custom: edit foo line2"

add_release v1.1.0 "UPSTREAM-EDIT-A"
run_sync                                            # conflict → paused
printf 'line1\nMY-EDIT\nline3\n' > "$WORKTREE/skills/foo/SKILL.md"
g "$WORKTREE" add skills/foo/SKILL.md
GIT_EDITOR=true g "$WORKTREE" -c rerere.enabled=true rebase --continue
run_finish                                          # rerere now remembers this resolution

add_release v1.2.0 "UPSTREAM-EDIT-B"                # same line conflicts again
run_sync
assert_nofile "$CTRL/STATUS"                        # auto-resolved, no pause
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.2.0" base-advanced-auto
assert_grep '"result":"rerere-resolved"' "$CTRL/history.ndjson"
pass
```

Note: `make_config` must enable rerere in the fork. Add this line to `make_config` in `harness.sh` (Task 2) — update it now:
```bash
  g "$FORK" config rerere.enabled true
```
(Insert inside `make_config` after `mkdir -p "$CTRL"`.)

- [ ] **Step 6: Run the replay test**

Run: `bash tests/sync/test_rerere_replay.sh`
Expected: `PASS: test_rerere_replay.sh`

- [ ] **Step 7: Commit**

```bash
chmod +x scripts/sync/finish.sh
git add scripts/sync/finish.sh tests/sync/test_conflict_finish.sh tests/sync/test_rerere_replay.sh tests/sync/harness.sh
git commit -m "feat: finish.sh + rerere conflict replay"
```

---

## Task 6: `rollback.sh` — list / to / rework / promote

**Files:**
- Create: `scripts/sync/rollback.sh`
- Test: `tests/sync/test_rollback.sh`

- [ ] **Step 1: Write the failing test**

```bash
# tests/sync/test_rollback.sh
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config
fork_custom "skills/mine/SKILL.md" "v-a"
add_release v1.1.0 "u1"; run_sync                   # snapshot #1 (mine = v-a)
SNAP1="$(g "$FORK" tag -l 'snapshot/*' | head -n1)"
printf 'v-b\n' > "$FORK/skills/mine/SKILL.md"; g "$FORK" add -A; g "$FORK" commit -qm "mine v-b"
add_release v1.2.0 "u2"; run_sync                   # snapshot #2 (mine = v-b)

# list shows 2 snapshots
assert_eq "$(run_rollback list | grep -c snapshot/)" "2" list-count

# rollback to SNAP1 → live tree shows v-a again, BASE_TAG reset to that snapshot's base
run_rollback to "$SNAP1"
assert_grep "v-a" "$FORK/skills/mine/SKILL.md"
. "$CTRL/state"; assert_eq "$BASE_TAG" "v1.1.0" base-after-rollback

# rework: branch off SNAP1, edit, promote → live carries the reworked content + new snapshot
run_rollback rework "$SNAP1"
printf 'v-a-reworked\n' > "$FORK/skills/mine/SKILL.md"; g "$FORK" add -A; g "$FORK" commit -qm "rework"
run_rollback promote
assert_grep "v-a-reworked" "$FORK/skills/mine/SKILL.md"
assert_eq "$(g "$FORK" rev-parse --abbrev-ref HEAD)" "live" back-on-live
assert_eq "$(g "$FORK" tag -l 'snapshot/*' | wc -l | tr -d ' ')" "3" new-snapshot-after-promote
pass
```

- [ ] **Step 2: Run to verify it fails**

Run: `bash tests/sync/test_rollback.sh`
Expected: FAIL — `rollback.sh` missing.

- [ ] **Step 3: Write `scripts/sync/rollback.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${SPSYNC_CONFIG:=$HOME/.superpowers-sync/config}"
. "$SPSYNC_CONFIG"
. "$(dirname "$0")/lib.sh"
load_state

# Parse the upstream tag a snapshot was built on, from its annotation "sync onto vX.Y.Z (...)"
snap_base() { g "$REPO" tag -l --format='%(contents)' "$1" | sed -n 's/.*sync onto \(v[0-9.]*\).*/\1/p' | head -n1; }

cmd="${1:-list}"
case "$cmd" in
  list)
    g "$REPO" tag -l 'snapshot/*' --sort=-creatordate \
      --format='%(refname:short)  %(creatordate:short)  %(contents:subject)'
    ;;
  to)
    snap="$2"
    g "$REPO" rev-parse -q --verify "refs/tags/$snap" >/dev/null || { echo "no such snapshot: $snap"; exit 1; }
    g "$REPO" switch -q "$LIVE_BRANCH"
    g "$REPO" reset --hard "$snap" >/dev/null
    base="$(snap_base "$snap")"; [ -n "$base" ] && set_state BASE_TAG "$base"
    [ -n "${SPSYNC_REFRESH_CMD:-}" ] && eval "$SPSYNC_REFRESH_CMD" || true
    echo "live now at $snap (base ${base:-unknown}). Loads on your next Claude session."
    ;;
  rework)
    snap="$2"
    g "$REPO" switch -q -c "rework/${snap#snapshot/}" "$snap"
    echo "On branch rework/${snap#snapshot/}. Edit + commit, then: rollback.sh promote"
    ;;
  promote)
    cur="$(g "$REPO" rev-parse --abbrev-ref HEAD)"
    case "$cur" in rework/*) ;; *) echo "Not on a rework/* branch."; exit 1;; esac
    g "$REPO" switch -q "$LIVE_BRANCH"
    g "$REPO" reset --hard "$cur" >/dev/null
    g "$REPO" branch -D "$cur" >/dev/null
    stamp="snapshot/$(date +%Y-%m-%d-%H%M%S)"
    g "$REPO" tag -a "$stamp" -m "promote rework onto ${BASE_TAG} (manual)"
    log_event promote "${BASE_TAG}" "$stamp"
    prune_history; prune_snapshots
    [ -n "${SPSYNC_REFRESH_CMD:-}" ] && eval "$SPSYNC_REFRESH_CMD" || true
    echo "Promoted to live as $stamp."
    ;;
  *) echo "usage: rollback.sh {list|to <snap>|rework <snap>|promote}"; exit 1;;
esac
```

- [ ] **Step 4: Run the rollback test**

Run: `bash tests/sync/test_rollback.sh`
Expected: `PASS: test_rollback.sh`

- [ ] **Step 5: Commit**

```bash
chmod +x scripts/sync/rollback.sh
git add scripts/sync/rollback.sh tests/sync/test_rollback.sh
git commit -m "feat: rollback.sh list/to/rework/promote"
```

---

## Task 7: Test runner + retention integration test

**Files:**
- Create: `tests/sync/run_all.sh`
- Test: `tests/sync/test_retention.sh`

- [ ] **Step 1: Write the retention test**

```bash
# tests/sync/test_retention.sh — old snapshots pruned on sync
DIR="$(cd "$(dirname "$0")" && pwd)"; . "$DIR/harness.sh"
make_upstream; make_fork; make_config
fork_custom "skills/mine/SKILL.md" "x"
# Fabricate an old snapshot tag (95 days ago) using a backdated commit date
OLD="$(GIT_COMMITTER_DATE='95 days ago' g "$FORK" -c rerere.enabled=false commit-tree \
       "$(g "$FORK" rev-parse live^{tree})" -p "$(g "$FORK" rev-parse live)" -m old 2>/dev/null)"
GIT_COMMITTER_DATE='95 days ago' g "$FORK" tag -a 'snapshot/2000-01-01-000000' "$OLD" -m "sync onto v1.0.0 (clean)"
add_release v1.1.0 "u"; run_sync                     # triggers prune_snapshots
g "$FORK" rev-parse -q --verify 'refs/tags/snapshot/2000-01-01-000000' >/dev/null \
  && { echo "FAIL: old snapshot not pruned"; exit 1; }
pass
```

- [ ] **Step 2: Run to verify it fails or passes**

Run: `bash tests/sync/test_retention.sh`
Expected: PASS if prune wired in Task 4; if FAIL, ensure `prune_snapshots` is called in `finalize_live` and on no-op path in `sync.sh` (both already present).

- [ ] **Step 3: Write the runner**

```bash
# tests/sync/run_all.sh
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
fail=0
for t in "$DIR"/test_*.sh; do
  echo "── $t"
  bash "$t" || { echo "  ^ FAILED"; fail=1; }
done
[ "$fail" = 0 ] && echo "ALL GREEN" || { echo "SOME FAILED"; exit 1; }
```

- [ ] **Step 4: Run the whole suite**

Run: `bash tests/sync/run_all.sh`
Expected: each `PASS:` line then `ALL GREEN`.

- [ ] **Step 5: Commit**

```bash
chmod +x tests/sync/run_all.sh
git add tests/sync/run_all.sh tests/sync/test_retention.sh
git commit -m "test: retention + full suite runner"
```

---

## Task 8: Bootstrap script (fork, remotes, live branch, install, cron, banner)

**Files:**
- Create: `scripts/sync/bootstrap.sh`

This task touches your real environment. It is idempotent and prints each action. Run it manually once.

- [ ] **Step 1: Write `scripts/sync/bootstrap.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
REPO="${REPO:-/home/ubuntu/superpowers}"
CTRL="$HOME/.superpowers-sync"
SCRIPTS_SRC="$REPO/scripts/sync"
GH_UPSTREAM="obra/superpowers"

echo "== 1. Remotes & fork =="
if ! git -C "$REPO" remote | grep -qx upstream; then
  # current 'origin' points at upstream OSS; rename it and create a real fork
  git -C "$REPO" remote rename origin upstream
  gh repo fork "$GH_UPSTREAM" --clone=false --remote=false
  me="$(gh api user -q .login)"
  git -C "$REPO" remote add origin "git@github.com:$me/superpowers.git"
fi
git -C "$REPO" fetch upstream --tags --quiet
LATEST="$(git -C "$REPO" tag -l 'v*' --sort=-v:refname | head -n1)"

echo "== 2. live branch on $LATEST + rerere =="
git -C "$REPO" config rerere.enabled true
if ! git -C "$REPO" rev-parse -q --verify live >/dev/null; then
  # base live on latest release; current local commits (e.g. specs/scripts) replay on top
  cur="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
  git -C "$REPO" branch live "$cur"
  git -C "$REPO" switch live
  git -C "$REPO" rebase --onto "$LATEST" "$(git -C "$REPO" merge-base "$LATEST" live)" live || {
    echo "Resolve initial rebase, then re-run bootstrap."; exit 1; }
fi
git -C "$REPO" switch live

echo "== 3. control dir + scripts =="
mkdir -p "$CTRL"
cp "$SCRIPTS_SRC"/{lib.sh,sync.sh,finish.sh,rollback.sh} "$CTRL/"
chmod +x "$CTRL"/*.sh
if [ ! -f "$CTRL/config" ]; then
  sed "s#__REPO__#$REPO#" "$SCRIPTS_SRC/config.template" > "$CTRL/config"
fi
echo "BASE_TAG=$LATEST" > "$CTRL/state"

echo "== 4. switch plugin to live local marketplace =="
# Remove the cache-based install so there is one source of truth.
claude plugin uninstall superpowers@claude-plugins-official --scope user 2>/dev/null || true
claude plugin marketplace add "$REPO" --scope user 2>&1 | tail -2
MKT="$(claude plugin marketplace list 2>/dev/null | sed -n 's/.*\b\([a-z0-9-]*\) .*'"$REPO"'.*/\1/p' | head -n1)"
MKT="${MKT:-superpowers}"
claude plugin install "superpowers@$MKT" --scope user 2>&1 | tail -2
echo "If Task 1 found COPY behavior, set SPSYNC_REFRESH_CMD in $CTRL/config now."

echo "== 5. cron (03:30 daily) =="
LINE="30 3 * * * /usr/bin/env bash $CTRL/sync.sh >> $CTRL/cron.log 2>&1"
( crontab -l 2>/dev/null | grep -v "$CTRL/sync.sh"; echo "$LINE" ) | crontab -

echo "== 6. shell banner =="
SNIP='[ -f "$HOME/.superpowers-sync/STATUS" ] && cat "$HOME/.superpowers-sync/STATUS"'
grep -qF "$SNIP" "$HOME/.zshrc" 2>/dev/null || printf '\n# superpowers-sync paused-rebase notice\n%s\n' "$SNIP" >> "$HOME/.zshrc"

echo "== DONE. Open a new Claude session and verify a skill edit appears. =="
```

- [ ] **Step 2: Lint the script (no execution yet)**

Run: `bash -n scripts/sync/bootstrap.sh && echo "syntax OK"`
Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
chmod +x scripts/sync/bootstrap.sh
git add scripts/sync/bootstrap.sh
git commit -m "feat: bootstrap (fork, live branch, plugin swap, cron, banner)"
```

---

## Task 9: Run bootstrap + end-to-end verification

**Files:** none (operational). Requires `gh auth status` to be logged in.

- [ ] **Step 1: Confirm prerequisites**

Run: `gh auth status 2>&1 | tail -3 && command -v crontab && echo "ok"`
Expected: authenticated GitHub user + crontab present. If `gh` is not authenticated, run `! gh auth login` in-session first.

- [ ] **Step 2: Run the full test suite once more**

Run: `bash tests/sync/run_all.sh`
Expected: `ALL GREEN`.

- [ ] **Step 3: Execute bootstrap**

Run: `bash scripts/sync/bootstrap.sh`
Expected: all six sections print; ends with DONE. Verify `git -C /home/ubuntu/superpowers remote -v` shows `origin`=your fork, `upstream`=obra.

- [ ] **Step 4: Verify live plugin source**

Run: `cat ~/.claude/plugins/installed_plugins.json | grep -A6 superpowers`
Expected: a single superpowers entry whose `installPath` reflects the live setup from Task 1's verdict.

- [ ] **Step 5: End-to-end live-edit check**

```bash
git -C /home/ubuntu/superpowers switch live
# make a trivial, clearly-yours marker in a skill description
```
Then open a NEW Claude session and confirm the edit is present (and, if COPY mode, that `SPSYNC_REFRESH_CMD` applied it). Revert the marker afterward and commit.

- [ ] **Step 6: Dry-run the daily sync**

Run: `bash ~/.superpowers-sync/sync.sh && tail -1 ~/.superpowers-sync/history.ndjson`
Expected: a `noop` line (already on latest tag) and no STATUS file.

- [ ] **Step 7: Commit any markers/cleanup**

```bash
git -C /home/ubuntu/superpowers add -A
git -C /home/ubuntu/superpowers commit -m "chore: e2e verification cleanup" || true
```

---

## Self-Review

**Spec coverage:**
- Live plugin from fork → Tasks 1, 8 (marketplace swap), 9 (verify). ✓
- Auto-apply on edit → live marketplace + optional `SPSYNC_REFRESH_CMD` (Tasks 1/3/4). ✓
- Daily rebase onto latest release tag → `latest_tag` + `rebase --onto` (Task 4), cron (Task 8). ✓
- rerere replay, pause on new → Tasks 4, 5. ✓
- One-line pause notice + apply after resolve → STATUS/PENDING + banner + finish.sh (Tasks 5, 8). ✓
- Isolation (live tree safe during conflict) → worktree + tests assert live unchanged (Tasks 4, 5). ✓
- Version timeline / rollback / rework → snapshot tags + rollback.sh (Task 6). ✓
- Auditability → history.ndjson + tag annotations + rerere cache (Tasks 3, 4). ✓
- 3-month retention → prune_history + prune_snapshots (Tasks 3, 4, 7). ✓
- Zero deps, headless → bash+git+cron only. ✓

**Placeholder scan:** No TBD/TODO; `__REPO__` is an intentional template token replaced by bootstrap. ✓

**Type/name consistency:** `finalize_live`, `latest_tag`, `set_state`, `load_state`, `log_event`, `prune_history`, `prune_snapshots`, `snap_base`, config keys (`BASE_TAG`, `WORKTREE`, `STATUS_FILE`, `PENDING_FILE`, `SPSYNC_REFRESH_CMD`) are defined once and used consistently across `lib.sh`/`sync.sh`/`finish.sh`/`rollback.sh`/`harness.sh`. ✓

**Known assumption to validate during execution:** `git rev-parse --git-path rebase-merge` path handling in `finish.sh` differs slightly across git versions; Task 5's test exercises the finished-rebase path. If the in-progress guard misfires on the host git version, adjust the check to `[ -d "$WORKTREE/.git/rebase-merge" ] || [ -d "$WORKTREE/.git/rebase-apply" ]`.
