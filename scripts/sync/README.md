# Superpowers fork auto-sync

Keep a personal fork of [obra/superpowers](https://github.com/obra/superpowers) automatically
rebased onto each new upstream **release**, with your own skills/commits on top, served to
Claude Code as a live local plugin. A daily cron does the rebase; conflicts pause safely with
copy-paste instructions and the rest completes hands-off.

- **Branch model:** `live` = latest upstream release tag **+ your commits**. (`main` is unused.)
- **Control dir:** `~/.superpowers-sync/` — deployed scripts, `config`, `state`, `history.ndjson`.
- **Schedule:** daily 03:30 via cron → `sync.sh` (log: `~/.superpowers-sync/cron.log`).

---

## Bootstrap (new machine)

Prereqs: `git`, `gh` logged in (`gh auth login`), the `claude` CLI logged in, GitHub access.

```bash
git clone https://github.com/<you>/superpowers.git ~/superpowers
cd ~/superpowers && git switch live
REPO=~/superpowers bash scripts/sync/bootstrap.sh
~/.superpowers-sync/sync.sh          # first sync; expect "exit 0"
```

Then open a **fresh** Claude session (the plugin cache is a copy, so edits load next session).

`bootstrap.sh` is idempotent and self-correcting: it adds the `upstream` remote if missing,
derives `BASE_TAG` from the tag `live` is actually on, sets the cron PATH so `claude` resolves
at 03:30, and switches Claude Code to the live local-marketplace plugin.

---

## Everyday commands (one-liners)

| Do this | Command |
|---|---|
| **Check status + rebase history** | `~/.superpowers-sync/status.sh` |
| **Edit/add a skill, then apply it** | edit under `~/superpowers/skills/…`, then `~/.superpowers-sync/apply.sh -m "what changed"` |
| **Sync with upstream now** | `~/.superpowers-sync/sync.sh` |
| **See snapshot timeline** | `~/.superpowers-sync/rollback.sh list` |
| **Roll back to a snapshot** | `~/.superpowers-sync/rollback.sh to snapshot/<ts>` |
| **Back up to your fork** | `git -C ~/superpowers push origin live --force-with-lease` |

`status.sh` shows branch, `BASE_TAG` vs reality (flags drift), whether an upstream update is
available, your commit count, worktree cleanliness, cron schedule, plugin-cache versions, any
paused rebase, and the last N sync results. `-n 30` for more history, `--no-fetch` to skip the
network check.

---

## When the daily sync hits a merge conflict

The rebase **pauses** — your live plugin keeps serving the last good version. New shells print a
one-line notice (banner reads `~/.superpowers-sync/STATUS`); `status.sh` shows the details. To
resolve, copy-paste what the STATUS message gives you:

```bash
cd ~/.superpowers-sync/rebase-wt
# edit the conflicted files: resolve <<<<<<< ======= >>>>>>> markers
git add -A
~/.superpowers-sync/finish.sh
```

`finish.sh` does **everything else automatically**: it drives `git rebase --continue` through all
remaining commits, adopts the result into `live`, stamps a rollback snapshot, and refreshes the
plugin cache. If a *later* commit also conflicts, it stops and re-prints the same three steps for
the new files — repeat until it reports "live now on vX.Y.Z".

---

## Uninstall

```bash
crontab -l | grep -v '.superpowers-sync/sync.sh' | crontab -   # remove the cron job
rm -rf ~/.superpowers-sync
claude plugin uninstall superpowers@superpowers-dev --scope user
claude plugin marketplace remove superpowers-dev
```

---

## Files

```
scripts/sync/            # source of truth (this dir), committed on `live`
  bootstrap.sh   one-shot setup / idempotent re-run
  sync.sh        daily rebase onto latest release (rerere-aware; pauses on conflict)
  finish.sh      finalize after you resolve a paused rebase (auto-continues the rebase)
  apply.sh       commit local edits + snapshot + refresh plugin
  rollback.sh    snapshot timeline / rollback / rework / promote
  status.sh      health + history (read-only)
  lib.sh         shared helpers (incl. resolve_manifest_versions)
  refresh-control.sh  copy the six code files above into a control dir (--check / --dry-run)
  config.template
```

Scripts are copied into `~/.superpowers-sync/` by `bootstrap.sh`. A fleet release deploy refreshes them from the
DEPLOYED export (`releasing-fleet`: `bash "$FLEET_RELEASES/current/scripts/sync/refresh-control.sh" --ctrl <control dir>`),
which writes only the six code files — never `config`, `state`, `STATUS`, `PENDING`, `history.ndjson` or the rebase
worktree. By hand: `refresh-control.sh --ctrl <dir>` from this checkout, or re-run `bootstrap.sh`.

## Version-manifest conflicts resolve themselves (D-136)

Every fleet release commit stamps `"version": "<upstream>+fleet.<x>"` into the manifests `.version-bump.json` names, and
every upstream release bumps the same line, so each replayed release commit used to conflict on every upstream tag
(2026-09-26: v6.4.1 → v6.4.2 paused on exactly those files). When EVERY unmerged path is such a manifest and EVERY
conflict hunk differs only in the version value, `sync.sh` (and `finish.sh`, for the commits after a manual fix) takes
upstream's version with the replayed commit's `+fleet.<x>` suffix, stages it and continues. The run is logged as
`"result":"manifest-resolved"` with the resolved files in `conflicts` — never silently as `clean`. Any other conflict — a
non-manifest file, or a manifest hunk touching anything besides the version — still pauses exactly as before.
