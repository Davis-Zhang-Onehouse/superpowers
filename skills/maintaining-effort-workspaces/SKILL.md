---
name: maintaining-effort-workspaces
description: Use when one effort spans multiple sessions, forks, or rewinds and state keeps getting lost — you re-elicit status, PR/branch links, scope, repro commands, or "where did we leave off", or your partner re-pastes the same context each session.
---

# Maintaining Effort Workspaces

## Overview

A long-running effort (one issue worked across many sessions) accumulates progress, surprises, decisions, and "how to run it" knowledge. If that state lives only in a session transcript, every resume, fork, or rewind loses it — and your human partner re-pastes the same status, PR links, scope, and build commands over and over.

**Core principle:** the workspace folder — not the conversation — is the interface between sessions. Lay it out with fixed file names so a cold session pointed at the folder knows the starting point, current state, what's left, and how to resume.

**Acceptance test:** point a fresh session at the folder → it reaches the next productive action without asking you for status, scope, PR links, or repro commands.

## When to Use

- Work on one issue/feature is **spanning multiple sessions** (or you expect it to).
- You run **concurrent/forked sessions** or get **rewound**, and state gets lost.
- Your partner keeps re-asking or re-pasting: "status?", "PR links?", "what's the scope again?", the build command, "is it actually green?".
- Code is checked out in **more than one working directory** (e.g. `~/ws1`/`ws2`/`ws3`).

**Not for** single-session tasks or anything that finishes before you stop. `HANDOFF.md` + `CHARTER.md` is the floor; the rest scales with the effort.

## The Four Invariants

1. **One entry point, fixed name.** Every effort folder has a `HANDOFF.md` at its root — *the* first file a resuming session reads. Everything else hangs off it via links.
2. **Durable vs. live, never mixed.** A doc is DURABLE (rarely changes; no CI run-ids, no "in progress") or LIVE (a dated snapshot understood to rot). Volatile state lives **only** in `HANDOFF.md`'s snapshot or `STATE.md`'s CI column — never in durable docs.
3. **One fact, one home.** The PR-stack table lives in exactly one file (`STATE.md`). Everywhere else *links* to it. Copies drift.
4. **Capture evidence into the folder, not `/tmp`.** A claim of "green" cites a file in `evidence/`, referenced by relative path — `/tmp` is gone on resume.

Plus two register rules: **registers append, never rewrite** (decisions/issues/assumptions accrete with stable IDs + dates), and **the charter is sacred** (goal/scope/acceptance/constraints written once, edited deliberately, so your partner never re-pastes them).

## Canonical Layout (fixed names at the effort root)

```
<effort>/
  HANDOFF.md      ← ENTRY POINT. workspace folder + resume cmd + session log + live snapshot + index
  CHARTER.md      ← DURABLE. goal · scope(in/out) · acceptance · standing rules · env
  STATE.md        ← single source of truth: repo → branch → tip githash → PR → CI status
  RUNBOOK.md      ← how to build / run tests / repro the gap / prove it ran
  DECISIONS.md    ← DURABLE. dated decision log + rationale (D-1, D-2, …)
  ISSUES.md       ← DURABLE. stable-ID register: OPEN/FIXED/DEFERRED/DOCUMENTED + tickets
  ASSUMPTIONS.md  ← DURABLE. unverified beliefs: OPEN/VERIFIED/REFUTED/SANCTIONED/DEFERRED
  investigations/ ← one subfolder per deep dive: <topic>/{analysis,validation,callstack}.md
  evidence/       ← captured logs/artifacts referenced as proof (NOT /tmp)
  plans/ specs/   ← superpowers plan & spec docs (existing convention)
```

Small efforts may fold `STATE`+`RUNBOOK` into `HANDOFF` and `ASSUMPTIONS` into `ISSUES` — but **always keep `HANDOFF.md` and `CHARTER.md`**. Never invent a new name for an existing role (no `progress.md` *and* `TRACKING.md` *and* `STATUS.md` — that drift is the failure this skill prevents).

**File templates for every canonical file:** see `templates.md` in this skill directory. Copy them when bootstrapping an effort folder.

## Maintenance Discipline

- **End every session by updating `HANDOFF.md`** — treat it like a commit, the last action before stopping: refresh the one-paragraph "where we are", the next action, the live snapshot, the "Resume here" header, AND **append a row to the session log** (`date | workspace | resume cmd | did what`). A single "Resume:" line loses every session but the latest; the log keeps each one re-attachable.
- **Record both the workspace folder AND the session uuid.** `claude --resume <uuid>` attaches the conversation but does **not** restore the working directory — without the `cd`, a resumed session operates on the wrong tree. (The uuid is the transcript filename under `~/.claude/projects/-home-ubuntu-ws<N>…/`.)
- **Write the fact to its home, then link.** New PR → a row in `STATE.md`, referenced from `HANDOFF.md` by link. Never paste the table twice.
- **A surprise → a row in `ISSUES.md` or `ASSUMPTIONS.md` the moment it's spotted**, with a status — even "OPEN, unchecked". This is how hiccups/unverified assumptions get tracked instead of lost.
- **A decision → a dated `DECISIONS.md` row** with rationale, the moment it's made.
- **Durable docs carry no volatile state.** Tempted to write a CI run-id into `CHARTER`/`DECISIONS`/`ISSUES`? It belongs in `HANDOFF`'s snapshot or `STATE`'s CI column.
- **Header every doc:** `Updated: <date> by <uuid> | Status: DURABLE | LIVE`.

## The Resume Contract (what a cold session does in ~60s)

1. Read `HANDOFF.md` → workspace folder + resume command(s), session log, where-we-are, next action, index.
2. Read `CHARTER.md` → stay in scope; don't re-ask criteria/constraints.
3. Skim `STATE.md` → know the working set; don't re-elicit branches/PRs.
4. Open `RUNBOOK.md` → rebuild + rerun validation without re-pasting commands.
5. Glance `ASSUMPTIONS.md` + `ISSUES.md` → know open risks and what's deferred (so you don't re-propose a REFUTED approach).
6. Only then dive into `investigations/` for the specific task.

If those six files can't carry a fresh session from cold to productive, the layout failed.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Three docs each claiming to be "the" status | One `HANDOFF.md`. Others link to it. |
| CI run-ids / "watcher …" in `CHARTER`/`DECISIONS` | Quarantine volatile state to `HANDOFF` snapshot or `STATE`. |
| PR table pasted in two files | One home (`STATE.md`); link elsewhere. |
| Proof logs in `/tmp` | `evidence/<date>-<name>.log`, referenced by relative path. |
| Recording resume uuid but not the workspace folder | Record both — uuid alone resumes onto the wrong tree. |
| Re-pasting goal/scope each session | Write it once in `CHARTER.md`. |
| Overwriting issue/decision history | Registers append; add rows, don't rewrite. |
