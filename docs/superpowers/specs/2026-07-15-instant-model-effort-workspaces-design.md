# Instant-Model Revision of `maintaining-effort-workspaces` — Design

Date: 2026-07-15
Status: approved, implementing

## Problem

The current skill treats an effort as a single folder that mutates in place across
sessions. Real efforts branch: a base capability gets forked into several parallel
features, each proven independently, then folded back together. There was no vocabulary
for "which snapshot am I resuming", "what did this fork start from", or "these three
finished features are now one consolidated deliverable". State transitions and
fork/compaction were implicit, so resuming sessions still re-elicited context.

## Core idea

Model each effort snapshot as a **Hudi-timeline-style instant**: an immutable-ish,
named subfolder whose name encodes its lineage and lifecycle state. A state transition
is a folder **rename**. This gives every session an unambiguous unit to resume, fork
from, or compact.

## Naming grammar (literal)

```
<base_instant>-<curr_instant>-<state>-<opType>-<instantName>
```

- `base_instant` — `main`, or the parent instant's `curr_instant` (the fork point).
- `curr_instant` — `MMDDHHMM` this instant was created (e.g. `07181613`).
- `state` — `inflight` | `complete` | `abort`.
- `opType` — `append` (created by the `new` op) | `compact`.
- `instantName` — meaningful code (`toyExample`, `addfeature1`, `m1`).

`base_instant` is a *timestamp only*, never a full folder name, so it survives the
renames that state transitions cause.

### Worked lifecycle (from the requirement)

```
main-07181613-inflight-append-toyExample        # created
main-07181613-complete-append-toyExample         # renamed on completion
07181613-07191011-inflight-append-addfeature1    # 3 forks off the completed toyExample
07181613-07191013-inflight-append-addfeature2
07181613-07191016-inflight-append-addfeature3
07181613-07191011-complete-append-addfeature1    # each renamed as it completes
07181613-07191013-complete-append-addfeature2
07181613-07191016-complete-append-addfeature3
main-07191323-complete-compact-m1                # the three folded into one, rebased on main
```

## Physical model

- An instant is a **subfolder** under the base dir the partner points at.
- Each instant is self-contained with the canonical files (CHARTER, HANDOFF, STATE,
  RUNBOOK, DECISIONS, ISSUES, ASSUMPTIONS, evidence/INDEX.md, investigations/, …),
  exactly like the `0715/` reference folder.
- Git branch names may mirror the folder name, but the folder is the unit.
- `abort` instants are kept on disk as history.

## `/maintain-workspace-effort <ops> [param]` command

Lives at `commands/maintain-workspace-effort.md` (plugin auto-discovers it). It loads
this skill and executes:

- `new [name]` — on the base dir:
  - latest (max `curr_instant`) instant is `inflight` → `cd` in and resume it;
  - latest is `complete` → fork child `<parentCurr>-<now>-inflight-append-<name>`.
  - An explicit param may name the base instant to build on instead of the latest.
- `compact <instantA,instantB,…>` — produce `main-<now>-complete-compact-<name>`.

State transitions (`inflight`→`complete`/`abort`) are a manual `mv`, done at session end
as part of maintenance discipline.

## CHARTER restructured to the instant lifecycle

Four durable headings plus the raw-prompt capture:

1. **Setup to begin with** — starting branch set / base instant (`Empty` or a list).
2. **First 3 raw prompts** — verbatim, own section.
3. **Acceptance criteria** — each is *NL statement → executable proof* (green test run /
   automated grep for a beacon runtime log / GitHub CI run — the code itself put to
   execution decides pass/fail) → a running *self-review* of how captured evidence
   fulfills it. Brainstorm to clarify criteria as needed.
4. **Setup to end up with** — deliverables handoff (PRs, test-run links showing the
   beacon log, images, jars + where to find them, investigation summary, RCA doc) **and**
   a reproducible stack runnable with trivial effort (run cmds + grep, at most).

## ISSUES: table → prose sub-sections

Each issue: `## <ID> <title>` with `### Symptom` / `### Root cause` (link a separate RCA
doc when deep) / `### Action taken` / `### Status`. Register still append-only; starts
empty and accretes.

## Compact metadata (`COMPACTED.md`)

`main-<now>-complete-compact-<name>/COMPACTED.md` records:

- **Included instants** — the exact folder names folded in.
- **Merged acceptance criteria** — union of the inputs' criteria (default).
- **Compacted "Setup to end up with"** — the consolidated deliverables + a single stack
  whose setup re-derives all evidence for the merged criteria.

Consumed instants remain on disk untouched.

## Non-goals

- Not automating the `mv` state transition inside the command (kept manual/disciplined).
- Not deleting or archiving consumed/aborted instants.
- Not changing the Four Invariants, the resume contract's spirit, or the evidence/INDEX
  discipline — those still hold *within* each instant.
