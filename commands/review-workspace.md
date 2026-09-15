---
description: Review an effort-workspace instant — a hunt at a frozen tip, or a closure round after a receive pass (see reviewing-workspace skill)
argument-hint: --base <base-folder-path> [--instant <instant-folder>] [--closure] [--scope all|format|alignment|code]
---

Invoke the `superpowers:reviewing-workspace` skill, then run the review below.

Arguments: `$ARGUMENTS`
- `--base <base-folder-path>` (**mandatory, always**): the folder that holds the instants. If absent, stop and elicit it.
- `--instant <instant-folder>` (optional): default = the latest `…-inflight-…` instant under `--base`.
- `--closure` (optional): run a closure round after a receive pass instead of a hunt. Requires the tip the findings were raised against, the tip now, the pass number and the withdrawals path — ask for any that is missing.
- `--scope all|format|alignment|code` (optional, default `all`): which lenses the hunt dispatches. Each lens's findings are recorded under its own scope, and `fleet complete` needs all three covered across the ledger, so a single-lens hunt is deliberately partial.

**Before doing anything:** confirm `--base`. If missing, ask your human partner for the base folder path and wait for it.

## What this runs

Without `/review-workspace --closure`: a **hunt** — Stage 0 freeze, then the three lenses in one wave at the frozen tip, recorded through `fleet review`, one call per lens under its own scope. Then hand to `superpowers:receiving-workspace-review`. The hunt is the mid-effort mode too: run it whenever deviation should be caught early, and again before `fleet complete`, each with its own frozen tip. With `/review-workspace --closure`: the closure reviewer over the fix delta, the restated findings recorded under the scope(s) the hunt actually covered (`--scope all` only when all three lenses ran; otherwise the lens scope(s) of the findings restated, one call per scope), and the stop rule applied. Verdicts: `READY | READY-WITH-FIXES | NOT-READY`. `fleet complete` refuses on `NOT-READY` or an open blocking finding.
