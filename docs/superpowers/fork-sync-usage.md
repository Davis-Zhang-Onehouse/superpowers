# Superpowers Fork Auto-Sync — Usage

Personal fork of Superpowers that stays rebased on the latest upstream release, served
to Claude Code as a live local-marketplace plugin (`superpowers@superpowers-dev`).

- **Repo:** `/home/ubuntu/superpowers` — branch `live` = latest release tag + your commits
- **Remotes:** `origin` = your fork, `upstream` = `obra/superpowers`
- **Control dir:** `~/.superpowers-sync/` (`config`, `state`, scripts, `history.ndjson`)
- **Cron:** daily 03:30 → `sync.sh` (log: `~/.superpowers-sync/cron.log`)

> Note: Claude Code **copies** the plugin into its cache, so changes apply on your
> **next Claude session** after a refresh. `apply.sh` and the daily sync run the refresh
> for you; you don't normally call it by hand.

## Edit / write a skill

```bash
git -C ~/superpowers switch live          # if not already on live
# ...edit or add skills under ~/superpowers/skills/...
~/.superpowers-sync/apply.sh -m "improve brainstorming skill"
```
`apply.sh` commits, stamps a `snapshot/<ts>` rollback point, and refreshes the live
plugin. Open a new Claude session to use the change. Push backups when you like:
`git -C ~/superpowers push origin live`.

## Version timeline / rollback / rework

```bash
~/.superpowers-sync/rollback.sh list                 # timeline of snapshots
~/.superpowers-sync/rollback.sh to snapshot/<ts>     # switch live to an old version
~/.superpowers-sync/rollback.sh rework snapshot/<ts> # branch off to redo a version
#   ...edit + commit on the rework/* branch...
~/.superpowers-sync/rollback.sh promote              # make the reworked version current
```

## Daily upstream sync (automatic)

At 03:30 the cron rebases your commits onto the newest upstream **release tag**:
- **Clean / known conflict** (`git rerere` replays prior resolutions) → applied, snapshot stamped.
- **New conflict** → the rebase **pauses in `~/.superpowers-sync/rebase-wt/`** (your live
  plugin keeps serving the last good version). A one-line notice prints when you open a
  shell. Resolve it, then finish:
  ```bash
  cd ~/.superpowers-sync/rebase-wt
  # ...fix conflicts...
  git rebase --continue
  ~/.superpowers-sync/finish.sh
  ```

## Audit & retention

- `~/.superpowers-sync/history.ndjson` — one JSON line per run (result, base→new, conflicts, snapshot).
- Snapshots and the log are pruned to **90 days**.

## Run a sync manually

```bash
~/.superpowers-sync/sync.sh        # safe to run anytime; no-ops if already on the latest release
```
