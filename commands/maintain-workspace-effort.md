---
description: Create, resume, or compact an effort-workspace instant (see maintaining-effort-workspaces skill)
argument-hint: <new|compact> [base-instant | instantA,instantB,...]
---

Invoke the `superpowers:maintaining-effort-workspaces` skill, then execute the operation below. The base directory of instants is the current working directory unless the argument or the conversation names another — confirm it before creating anything.

Arguments: `$ARGUMENTS`
- `$1` = ops: `new` or `compact`
- `$2` = optional param — **the existing instant to build on / compact**, never a name:
  - for `new`: the base instant to fork from (omit to use the default rule below)
  - for `compact`: a comma-separated list of instants to fold together

The new instant's **name is derived from the effort's purpose** (brainstorm it / confirm with your partner) — it is NOT taken from `$2`.

## If ops = `new`

Resume the effort or fork a new instant, per the skill's `new` flow:

1. **Pick the base instant:**
   - If `$2` is given, the base is **that** instant. (This is how you fork a *parallel sibling* off a shared parent — e.g. build `addfeature4` off `toyExample`, not off the most recent sibling.)
   - Else the base is the instant with the max `curr_instant` in the base dir.
2. If the base is `…-inflight-…` → `cd` into it and resume (read HANDOFF → CHARTER → STATE → RUNBOOK per the Resume Contract). Do **not** create a new folder.
3. If the base is `…-complete-…` → create child `<baseCurr>-<MMDDHHMM-now>-inflight-append-<derivedName>/`, bootstrap the canonical files from `templates.md`, and carry forward `Setup to begin with` from the base's `STATE.md` / end state (if the base has none yet, record it as TBD and open an issue). `base_instant` = the base's `curr_instant` (a timestamp — survives the base's later renames).
4. Capture the session's **first 3 raw prompts** into the new CHARTER's dedicated section. If interactive, brainstorm (superpowers:brainstorming) with your partner to pick the instant name and sharpen acceptance criteria; otherwise distill both from the prompts.

## If ops = `compact`

Fold the instants in `$2` into one, per the skill's Compaction section:

1. Verify each listed instant is `…-complete-…` (warn on any that isn't).
2. Create `main-<MMDDHHMM-now>-complete-compact-<name>/`.
3. Write `COMPACTED.md` from the template: **included instants**, **merged acceptance criteria (union of inputs')**, **compacted "Setup to end up with"** with a single stack that re-derives all evidence for the merged criteria.
4. Consolidate STATE / RUNBOOK / evidence/INDEX.md. **Leave the consumed instants on disk untouched.**

Follow the Four Invariants and the maintenance discipline throughout. End by updating HANDOFF.md.
