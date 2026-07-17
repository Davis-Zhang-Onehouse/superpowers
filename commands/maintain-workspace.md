---
description: Create, resume, or compact an effort-workspace instant (see maintain-workspace skill)
argument-hint: <new|compact> --base <base-folder-path> [--from <base-instant>] [--instants <a,b,c>]
---

Invoke the `superpowers:maintain-workspace` skill, then execute the operation below.

Arguments: `$ARGUMENTS`
- `op` (leading token, **mandatory**): `new` or `compact`.
- `--base <base-folder-path>` (**mandatory, always**): the folder that holds the instants — where they are created and found. **If it is not supplied, stop and elicit it in chat.** Never default to the current working directory.
- `--from <base-instant>` (optional, `new` only): the existing instant to fork from / resume. Omit to use the default rule below. Never a *name* — always an existing instant folder.
- `--instants <a,b,c>` (**mandatory for `compact`**): comma-separated list of instants to fold together. If `op = compact` and this is absent, stop and elicit it in chat.

The new instant's **name is derived from the effort's purpose** (brainstorm it / confirm with your partner) — it is NOT taken from any argument.

**Before doing anything:** confirm `--base`. If missing, ask your partner for the base folder path and wait for it.

## If op = `new`

Resume the effort or fork a new instant, per the skill's `new` flow. All instants live under `--base`:

1. **Pick the base instant:**
   - If `--from` is given, the base is **that** instant. (This is how you fork a *parallel sibling* off a shared parent — e.g. build `addfeature4` off `toyExample`, not off the most recent sibling.)
   - Else the base is the instant with the max `curr_instant` in `--base`.
2. If the base is `…-inflight-…` → `cd` into it and resume (read HANDOFF → CHARTER → STATE → RUNBOOK per the Resume Contract). Do **not** create a new folder.
3. If the base is `…-complete-…` → create child `<base>/<baseCurr>-<MMDDHHMM-now>-inflight-append-<derivedName>/`, bootstrap the canonical files from `templates.md`, and carry forward `Setup to begin with` from the base's `STATE.md` / end state (if the base has none yet, record it as TBD and open an issue). `base_instant` = the base's `curr_instant` (a timestamp — survives the base's later renames).
4. Capture the session's **first 3 raw prompts** into the new CHARTER's dedicated section. If interactive, brainstorm (superpowers:brainstorming) with your partner to pick the instant name and sharpen acceptance criteria; otherwise distill both from the prompts.

## If op = `compact`

Fold the instants in `--instants` into one, per the skill's Compaction section and `compaction.md` (all under `--base`). Compaction **stacks existing work — it is not new feature dev**:

1. Verify each listed instant is `…-complete-…`. **Warn on any that isn't** — an `inflight` input may still be folded, but its unmet acceptance criteria merge in as **open** ACs the compact must later prove on the stack.
2. Create `<base>/main-<MMDDHHMM-now>-inflight-compact-<name>/` — **born `inflight`**; rename to `…-complete-compact-…` only once every merged AC is proven on the stack (the rename IS the state transition). Bootstrap the canonical files.
3. **Fork & stack the inputs' PRs** — for same-repo PRs, restack them into a **single chain** (`base → f1 → f2 → …`); record the chain (restack base + rebase fix-ups) in STATE.md.
4. Write `COMPACTED.md` from the template in `compaction.md`, satisfying the **four-part contract**: **① the stacked PR chain** · **② merged acceptance criteria** (union — **each proven on the compacted stack**, not just listed) · **③ evidence disposition** (each criterion REGENERATED, or CARRIED-OVER with an explicit justification) · **④ lingering-issue reconciliation** (every open concern from each input's ISSUES.md/HANDOFF.md → **remains-open | addressed | transformed**, nothing dropped) · compacted "Setup to end up with".
5. Consolidate STATE / RUNBOOK / evidence/INDEX.md. **RUNBOOK stays self-contained** — one build + one validation run re-derives all evidence for the merged criteria. **Leave the consumed instants on disk untouched.**
6. Carry every `remains-open` / `transformed` issue into the compact's ISSUES.md as a live sub-section (origin noted).

Follow the Four Invariants and the maintenance discipline throughout. End by updating HANDOFF.md.
