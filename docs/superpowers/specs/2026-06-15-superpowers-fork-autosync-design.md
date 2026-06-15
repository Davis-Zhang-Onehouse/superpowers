# Superpowers Fork Auto-Sync & Versioning — Design

**Date:** 2026-06-15
**Status:** Approved (design), pending implementation plan
**Author:** Davis Zhang (with Claude Code, Opus 4.8)

## Problem

I want to maintain my own fork of the Superpowers skills plugin so I can improve
existing skills and author new ones based on analysis of my historical Claude
sessions. I need that fork to:

1. Be the source the live Claude Code plugin actually loads.
2. Pick up my edits automatically (next session), with no manual re-install.
3. Stay rebased on top of the latest upstream OSS *release* daily, auto-resolving
   conflicts I've resolved before and pausing only on genuinely new ones — with a
   one-line notice telling me where to resolve, after which the result applies
   automatically.
4. Give me a version timeline I can roll back to, rework, and move forward from,
   with good auditability.
5. Keep only the most recent 3 months of activity.

## Decisions (settled during brainstorming)

| Topic | Decision |
|-------|----------|
| Fork model | Real GitHub fork + local clone. `origin`=my fork, `upstream`=obra/superpowers |
| Rebase target | Latest upstream **release tag** (`vX.Y.Z`) |
| Conflict policy | `git rerere` replays known resolutions; pause on anything new |
| Version unit | Daily **snapshot tags** (`snapshot/<YYYY-MM-DD-HHMM>`) |
| Refresh model | **Live local marketplace** — the working tree IS the plugin source |
| Pause notice | `STATUS` file + guarded `~/.zshrc` banner (one line) |
| Packaging | Plain shell scripts + cron (zero deps, headless, auditable) |
| Retention | 90 days for both the activity log and snapshot tags |
| Cron time | 03:30 local daily (adjustable) |

## Architecture

### Git topology

```
upstream  → github.com/obra/superpowers      (OSS repo, read-only)
origin    → github.com/<me>/superpowers       (my fork, my changes + backup)

branch `live` = upstream <latest release tag>  +  my custom commits on top
                ↑ the ONLY branch the plugin ever reads
```

- I edit/author skills on `live`, commit, push to `origin`.
- A state file records the upstream tag `live` is currently built on (`BASE_TAG`).
- The daily rebase replays *only my commits*:
  `git rebase --onto <new tag> <BASE_TAG> live`.

### Isolation invariant

The live plugin reads the working tree directly. Therefore **all rebases happen in
a separate git worktree** (`~/.superpowers-sync/rebase-wt/`), never in the live
tree. A paused/conflicted rebase never exposes conflict markers to running Claude
sessions; the live plugin keeps serving the last good snapshot until a rebase fully
succeeds and `live` is atomically repointed.

## Components — `~/.superpowers-sync/`

| File | Responsibility |
|------|----------------|
| `sync.sh` | Daily driver. Fetch tags → if newer release, rebase my commits onto it in `rebase-wt` → on success repoint `live` + stamp snapshot + log; on conflict pause + write `STATUS` |
| `finish.sh` | Run after I resolve a paused rebase: complete the swap, stamp snapshot, record resolution in audit log, clear `STATUS` |
| `rollback.sh` | `list` / `to <snapshot>` / `rework <snapshot>` — timeline, switch, branch-off-to-rework |
| `state` | `BASE_TAG`, current snapshot pointer, repo path |
| `STATUS` | Present only while a rebase is paused; drives the shell banner |
| `history.ndjson` | Append-only audit log, one JSON line per run |
| `rebase-wt/` | Throwaway git worktree where rebases happen |

Dependencies: `git`, plus `gh` for the one-time fork. `git rerere` enabled in the repo.

## Data flow — daily run (`sync.sh`)

**Happy path**
1. `git fetch upstream --tags`; resolve latest `vX.Y.Z`. If `== BASE_TAG`, log a
   `no-op` line and exit.
2. **Safety:** if the live tree has uncommitted changes, write a "skipped — tree
   dirty" notice and exit (never clobber in-progress edits).
3. In `rebase-wt`: `git rebase --onto <newtag> <BASE_TAG> live`. `rerere`
   auto-resolves previously-seen conflicts.
4. Success → atomically repoint `live` to the result, set `BASE_TAG=<newtag>`,
   stamp `snapshot/<timestamp>`, append a `clean` / `rerere-resolved` audit line.
   The change loads on my **next Claude session**.

**Conflict path**
1. Rebase stops in `rebase-wt`. `sync.sh` writes `STATUS`, e.g.:
   `⚠ superpowers rebase PAUSED in ~/.superpowers-sync/rebase-wt onto v5.2.0 — conflicts: skills/foo/SKILL.md. cd there, resolve, run finish.sh`
2. Shell rc prints that one line on next terminal open.
3. Live plugin keeps serving the last good snapshot (isolation invariant).
4. I `cd rebase-wt`, resolve, `git rebase --continue`, run `finish.sh`. `rerere`
   memorizes the fix so it never recurs. Live updates next session.

## Versioning, rollback & audit

Git is the version engine; no custom storage.

- **Timeline:** `snapshot/<YYYY-MM-DD-HHMM>` annotated tags — one per successful
  sync and one per skill-change commit. `rollback.sh list` prints a one-line-per-
  version timeline (date, base upstream tag, subject, clean/resolved).
- **Rollback:** `rollback.sh to <snapshot>` repoints `live`. Next session runs the
  old version. Reversible.
- **Rework & move on:** `rollback.sh rework <snapshot>` branches from a snapshot so
  I can edit an old version; `finish.sh` brings the reworked result forward as a new
  snapshot on `live`.
- **Audit:** each run appends one JSON line to `history.ndjson`: timestamp,
  `BASE_TAG → newtag`, result, conflicted files, resolution commit SHAs, snapshot
  created. With the `rerere` cache and `git reflog`, I can see what conflict
  happened, how it was resolved, and redo it differently.

## Notifications & retention

- **Pause notice:** `STATUS` file + a guarded `~/.zshrc` snippet that prints the one
  line only when a paused rebase exists; clears when `finish.sh` runs.
- **Retention (3 months):** at end of each run, prune `history.ndjson` lines and
  delete `snapshot/*` tags older than 90 days. Rollback depth = log depth = 90 days.

## One-time bootstrap

1. `gh repo fork obra/superpowers` → `origin`=fork, `upstream`=obra.
2. Create `live` from current state, set `BASE_TAG` to latest tag, enable `rerere`.
3. Switch the plugin to the live local marketplace pointing at the repo; remove the
   old cache-based install so there is exactly one source of truth.
4. Install scripts into `~/.superpowers-sync/`, add the daily cron entry (03:30),
   add the `.zshrc` banner snippet.
5. Verify end-to-end: edit a skill → open a new session → confirm the change is live.

## Open integration point (resolve first in implementation)

`claude plugin marketplace add` accepts a local path, but it is **not yet verified**
whether Claude Code serves a local-path marketplace from the live working tree or
copies it into the plugin cache. The implementation's first task is a short
experiment to confirm "live" truly means live. If Claude copies to cache, `sync.sh`
and `finish.sh` gain a one-line re-register/refresh step so changes still apply
automatically. The goal (auto-applied changes) holds either way.

## Non-goals (YAGNI)

- No cloud/remote scheduling (local git/worktrees can't be driven from a cloud agent).
- No LLM-in-the-loop for the rebase itself (deterministic git mechanics only).
- No overlay/second-repo structure (edits happen in place on `live`).
- No conflict auto-resolution beyond `rerere` replay (no path-ownership guessing).
