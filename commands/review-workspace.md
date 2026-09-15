---
description: Review an effort-workspace instant — a hunt at a frozen tip, or a closure round after a receive pass (see reviewing-workspace skill)
argument-hint: --base <base-folder-path> [--instant <instant-folder>] [--closure] [--scope all|format|alignment|code]
---

Invoke the `superpowers:reviewing-workspace` skill, then run the review below.

Arguments: `$ARGUMENTS`
- `--base <base-folder-path>` (**mandatory, always**): the folder that holds the instants. If absent, stop and elicit it.
- `--instant <instant-folder>` (optional): default = the latest `…-inflight-…` instant under `--base`.
- `--closure` (optional): run a closure round after a receive pass instead of a hunt. Requires the tip the findings were raised against, the tip now, the pass number and the withdrawals path — ask for any that is missing.
- `--scope all|format|alignment|code` (optional, default `all`): which lenses the hunt dispatches.

**Before doing anything:** confirm `--base`. If missing, ask your human partner for the base folder path and wait for it.

## What this runs

Without `--closure`: a **hunt** — Stage 0 freeze, then the three lenses in one wave at the frozen tip, recorded through `fleet review`. Then hand to `superpowers:receiving-workspace-review`. With `--closure`: the closure reviewer over the fix delta, the restated findings recorded, and the stop rule applied. Verdicts: `READY | READY-WITH-FIXES | NOT-READY`. `fleet complete` refuses on `NOT-READY` or an open blocking finding.
