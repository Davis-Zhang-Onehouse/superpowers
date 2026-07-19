---
description: Review an effort-workspace instant (format/invariants, goal-alignment, PR code review) and record findings in REVIEW.md (see reviewing-workspace skill)
argument-hint: --base <base-folder-path> [--instant <instant-folder>] [--scope all|format|alignment|code] [--note "<why this round>"]
---

Invoke the `superpowers:reviewing-workspace` skill, then run the review below.

Arguments: `$ARGUMENTS`
- `--base <base-folder-path>` (**mandatory, always**): the folder that holds the instants. **If it is not supplied, stop and elicit it in chat.** Never default to the current working directory.
- `--instant <instant-folder>` (optional): the specific instant subfolder to review. Default = the latest `…-inflight-…` instant under `--base`. If none is inflight, ask which instant to review.
- `--scope all|format|alignment|code` (optional, default `all`): which pipeline stage(s) to run. `all` runs the full gated pipeline; a single value runs only that stage (still opening/closing a REVIEW.md round).
- `--note "<text>"` (optional): free-text reason recorded as the round's trigger note.

**Before doing anything:** confirm `--base`. If missing, ask your partner for the base folder path and wait for it.

## What this runs

The skill runs a **sequential gated pipeline** — Stage 1 format & hygiene (auto-fix mechanical issues, flag anything requiring judgment), Stage 2 goal alignment / evidence-chain, Stage 3 delta PR code review — records findings in the instant's REVIEW.md as an **append-only round**, and reports an overall verdict: **READY | READY-WITH-FIXES | NOT-READY**. It is **ADVISORY**: it never blocks completion and never renames the instant.

Safe to run **mid-effort** (catch deviation early) or **right before** `mv …-inflight-… …-complete-…`.
