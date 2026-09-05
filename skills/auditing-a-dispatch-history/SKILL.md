---
name: auditing-a-dispatch-history
description: Use when making a dispatch auditable as it happens, or reconstructing afterwards what a dispatch contributed to a milestone - joining milestones to the instants that moved them, their evidence, and the PR positions that carry the result. Triggers include "what did that instant contribute", "is anything unaccounted for", "show me the dispatch history", "reconcile the completed instants".
---

# Auditing a Dispatch History

## Overview

Two directions, and they are different jobs.

**Forward** is cheap and happens at dispatch time: leave enough behind that the question is answerable
later. **Backward** is expensive and happens when someone asks *what did this instant actually
contribute?* — usually at a close-out, sometimes because a finding resurfaced and nobody can tell whether
it was already handled.

The backward direction is only as good as the forward one. An effort that did not record what it sent
has no way to reconstruct it from what came back.

**Announce at start:** "I'm using the auditing-a-dispatch-history skill to audit this dispatch history."

## Forward — what every dispatch leaves behind

At the moment of dispatch, in one place, recorded together:

| Artifact | Why it has to be kept, not regenerated |
|---|---|
| the **brief** | what you asked for, before the answer shaped your memory of the question |
| the **exact seed sent** | the seed is composed per dispatch; a profile plus your recollection is not it |
| the **lineage base and how you derived it** | the sha is checkable later, the reasoning is not |
| the **cap derivation** | the guard's own output at the moment you dispatched |
| the **milestone claimed** | the join between this instant and the registry |

Keep the seed **as sent**. The rendered seed is the profile's text plus per-milestone specifics, and
reconstructing it later from the profile silently loses the specifics — which are the part that was
actually about this worker.

If a brief was written earlier and re-verified before delivery, **record that you re-verified it and what
moved.** Then a claim that turns out wrong is attributable to a measurement rather than to staleness, and
the next person knows which of those they are looking at.

## Backward — reconstructing contribution

The join runs:

```
milestone  →  the instant(s) that owned it  →  their evidence  →  the chain positions that carry it
```

Each hop has a source: the roadmap carries the owner and the evidence paths; the instant carries its own
registers; the chain manifest carries the positions.

**Where the join breaks is between hops 3 and 4.** An instant's evidence says what it proved; the chain
says what landed. Nothing automatically connects them, and it is entirely possible for a milestone to be
`done`, its evidence to be real, and its code to be absent from the base a later worker is building on —
that has happened, and it was found by an auditor asking a question the coordinator had not thought to
ask. When you reconstruct, check that hop explicitly rather than inferring it from `done`.

For a human-facing board, hand off to `superpowers:rendering-task-board` rather than building a second
view here.

## Two rules the audit itself must obey

These are about the checks you write, and both were learned by writing checks that lied.

### A check that returns zero must state what it examined

A reconciliation once reported one instant as having zero open issues. It had fifteen — it simply did not
use the field the check grepped for. **The check could not see them, and reported that as none.**

So every check emits a **population line**: how many things it examined, how many matched the shape it
depends on, and how many it could not classify. Read that line *before* the count. `fleet`'s own checkers
model this — each report ends with a population row precisely so a narrowed scope does not read as a pass
— and it is worth copying exactly.

A check with no way to answer must report **could not determine**. "Could not determine" and "none"
are different findings, and only one of them is safe to act on.

**Absence is never success.** The general form: *nothing failed* is not *everything passed*. A job that
never ran, a suite that was skipped, a run that was re-queued rather than fixed, a grep against a shape
the data does not use — each produces a clean-looking zero.

### A long delegation must produce incremental artifacts

A reconciliation spanning 35 instants and around 150 findings ran for two hours, hit a session limit, and
left **nothing**. Its brief had asked for one report at the end.

**The defect was in the brief, not the delegate.** For any job large enough to be interrupted — and
anything spanning a whole effort's history is — ask for output *as it goes*: one file per batch, appended
as each completes. Then an interruption costs the current batch instead of the whole run.

The same applies to your own long sweeps. If you are two hours into something and have written nothing
down, you are one limit away from having done nothing.

## Verify before you relay

Anything an audit hands you that would gate an irreversible or outward-facing act — a red you are about to
wake a worker with, a verdict, a harvest, a dispatch base — **re-derive yourself from the raw source**
before acting on it. Verification is re-derivation, not re-reading the report.

This is not distrust of the auditor. A coordinator once relayed two unverified facts to a worker; the
worker wrote both into its instant, and the tool that would have caught the error was the coordinator's
own. The failure mode is that a claim gains authority purely by being repeated by someone with more
context.

Equally: when an audit contradicts you, check before conceding. A confident correction can be wrong, and
adopting it wholesale replaces one unverified claim with another.

## Red flags

| Thought | Reality |
|---|---|
| "The sweep came back clean" | Clean over what population? Read the population line before the count. |
| "The delegate will write it up at the end" | Then a limit at 90% leaves you nothing. Ask for incremental artifacts. |
| "The audit agent confirmed it" | Re-derive anything that gates an irreversible act. |
| "The milestone is done, so its code is on the chain" | Those are different facts. Check the hop. |
| "I can reconstruct the seed from the profile" | The profile is the template. The specifics were the point. |
| "Nothing showed up in the report" | Distinguish *found nothing* from *could not look*. |
