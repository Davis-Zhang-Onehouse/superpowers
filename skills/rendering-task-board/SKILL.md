---
name: rendering-task-board
description: Use when an orchestration or maintain-workspace effort needs a shareable task/status board or a close-out deliverable — turning a workspace's scattered HANDOFF registry, ISSUES register, catalog, dispatch reports, and child-instant findings into one issue-per-ticket board folder (ClickUp/Jira-style). Triggers include "render a task board", "status board", "current status of tasks", "close-out tickets", "one ClickUp per issue".
---

# Rendering a Task Board

## Overview

A **task board** is a *deliverable folder* (its own git repo), not a printout: one markdown ticket per
issue plus a `00-INDEX.md` snapshot board. It answers ONE question for someone who was not in the churn:
**what are the tasks and what is each one's status right now.**

**Core principle: a task board is a LATEST-STATE SNAPSHOT, never a history log.** Every ticket shows the
current status of one issue; anything a later step overrode is gone. This is the rule authors most often
break — see the recipe below.

## When to use

- Closing out (or checkpointing) an orchestration effort — producing the operator's ClickUp/Jira tickets.
- You have a `maintain-workspace` / `coordinating-instants` workspace (HANDOFF.md, ISSUES.md, catalog, evidence/,
  dispatched child instants) and need a shareable board out of it.
- NOT for the workspace's own live registry — HANDOFF.md/ISSUES.md stay the working state. The board is the
  *outward* snapshot derived from them.

## The deliverable

```
<board>/                       # own git repo: commit 1 = baseline draft, commit 2 = revisions
  00-INDEX.md                  # snapshot board: north-star + bottom-line prose, then the AUTO region
  <class>-NN-slug.md           # ONE issue per file  (class ∈ gap|infra|hygiene|residual|scope|reconciliation)
```

`00-INDEX.md` carries author prose plus a tool-owned region:
```
<!-- board:auto:start -->
<!-- board:auto:end -->
```
`build-index.py --write <board>` fills that region (status-grouped tables, open tickets sub-grouped by
class). Author owns everything outside the markers; the tool owns everything inside.

## The standard (the judgment the tool cannot do)

**1. Snapshot, not history — the recipe for each ticket.** Write exactly these, at their LATEST state:
functional requirement (the gold) → current gap → chosen approach → current verification (the one PR, the one
CI number, the review gate). Then STOP. A ticket is snapshot-shaped when it reads the same whether written
after 1 attempt or 10 — it never narrates attempts. Delete on sight: multi-CI-run timelines, "review caught
X then we fixed it" arcs, superseded intermediate PRs shown as live, internal process tags.

**2. One issue per ticket.** One ClickUp = one issue. Split a "and also" ticket; a fix and the residual it
leaves behind are two tickets (link them).

**3. Source widely, then reconcile — this is where boards miss things.** The top-level HANDOFF/ISSUES
registry is NOT the whole truth. Residuals often live only in a child instant's
`investigations/catalog-delta.md` ("⬛ still OPEN" lines) or in catalog prose, never promoted to a
top-level issue — invisible to a naive close-out. Walk the dispatched child instants and the catalog, and
add one `reconciliation-*` ticket that accounts for every item (e.g. all goldens) and flags anything
untracked.

**4. Group by actionability.** Done together; open split into merge/hygiene blockers, in-scope residual tail
(documented, not regressions), and next-effort scope. Superseded work is closed as superseded, not shown as
active. The index reflects this automatically from the `<class>-` prefix.

**5. Clean status markers only.** Each ticket's `**Status:**` must be a legend token (✅ 🔵 ⏳ 🅿 🔲/⬜ ⛔),
optionally `— qualifier`. Prose like "mostly resolved" cannot be bucketed — `--check` flags it.

## The tool

`build-index.py` rolls the index up from tickets' `**Status:**` lines (the drift-prone mechanical part):

| Command | Does |
|---------|------|
| `build-index.py <board>` | print the grouped board (AUTO region) to stdout |
| `build-index.py --write <board>` | rewrite the AUTO region in `00-INDEX.md`, preserving author prose |
| `build-index.py --check <board>` | exit 1 if any ticket lacks a clean Status line, or the index drifted |

New ticket: copy `ticket-template.md`. After any ticket edit, re-run `--write` (or `--check` in CI) so the
index never drifts from the tickets. Run `tests/build-index-test.sh` to verify the tool on a fresh checkout.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Ticket narrates the journey (CI runs, caught-and-fixed bugs) | Snapshot recipe: requirement → current gap → approach → current proof. Stop. |
| Only reading HANDOFF/ISSUES | Walk child-instant `catalog-delta.md` + catalog; add a `reconciliation-*` ticket. |
| Superseded PR/task listed as active | Mark `⛔ superseded`; it moves to its own group. |
| Editing `00-INDEX` tables by hand | They are tool-owned — `--write`. Hand-edits drift; `--check` catches it. |
| Fuzzy status ("mostly done") | One legend marker + short qualifier. |
