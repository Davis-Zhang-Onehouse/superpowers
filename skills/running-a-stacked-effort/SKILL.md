---
name: running-a-stacked-effort
description: Use when standing up or resuming a multi-milestone effort that delivers a stacked chain of PRs across one or more pinned repos - owns the project goal, the milestone registry, the known and unknown unknowns, and the cycle that dispatches waves and integrates their output. Triggers include "you are the coordinator for this effort", "let's start this project", "what is the state of the project", resuming into an effort root.
---

# Running a Stacked Effort

## Overview

You are the standing coordinator of an effort whose deliverable is a **chain of PRs somebody will merge**.
Not a branch, not a proof, not a report — a stack where each position is one scoped change on top of its
predecessor, and the tip is landable.

That deliverable shapes everything else. Work arrives as milestones, gets executed by dispatched workers
in parallel on a shared base, and then has to be **linearised** into the chain before the next wave can
build on it. The effort therefore has a rhythm rather than a queue: waves go out, the wave comes back, the
chain grows by several positions at once, and the next wave dispatches from the new tip.

**You do no development.** You charter, raise, dispatch, gate, apply, harvest, and keep the registries
true.

`superpowers:coordinating-instants` owns the nine-phase loop, the verb surface and the refusals. Read it
once. This skill owns the arc above it and does not restate the mechanics.

**Announce at start:** "I'm using the running-a-stacked-effort skill to coordinate this effort."

## Chartering

Before any dispatch, the effort needs a goal that cannot be softened later. Write it as **"done means all
N, and I do not get to soften any of them."** That phrasing is not decoration. A goal stated as a
direction — *get the stack landable* — quietly narrows every time a clause turns out to be expensive, and
nothing in the system notices, because there was never a clause to fail.

Each acceptance criterion is three columns: the **NL statement**, the **executable proof** that would
settle it, and a **running self-review** you update as evidence lands. The self-review column is not
written at the end. Its value is that it is wrong in public while the work is in flight — a criterion
sitting at "not started" three weeks in is information, and one composed at the close-out is a summary.

Do not write an AC whose proof is a judgement. *"CI is green"* is not a criterion; *"every check in this
named list of job-name strings is green on the PR's own checks page"* is one. A principle is not
checkable, and the list is the difference.

`references/chartering.md` carries the worked shape.

## Preserving the operator's framing

Keep the first three raw prompts **verbatim** in `CHARTER.md`. Paraphrase loses the thing you will need
later: not what the operator wanted, but how they said it, which is what settles the reading of a clause
nobody anticipated.

**When a line stops being operative, strike it in place and say why.** Do not delete it. A reader greps
this file for a rule and lands on whatever is there — so a superseded instruction that has simply
vanished takes its correction with it, while a struck line carries its own. Two rules in the source effort
changed under it mid-flight (a slot-routing preference, a hard-coded worker cap) and both are still in its
charter, struck, each with the ruling that retired it.

The same discipline applies to your own registers. A correction goes **at the original heading**, not
appended silently at the end, and if the heading itself carries the wrong claim, strike the heading —
otherwise the wrong number stays in the index and in every grep.

## The registries, and who writes them

Four artifacts, three kinds of truth. The distinction is what stops a narrative from being mistaken for
state.

| Artifact | Sole writer | Kind |
|---|---|---|
| `.fleet/roadmap.json` | you, via `fleet apply` and `fleet milestone` | **state** — authoritative |
| the chain manifest | the integration routine writes tips; the wave routine reads them | **state** |
| `CHARTER.md` | you, once; durable | contract |
| `PRIORITIES.md` | you | ranking only |
| `DECISIONS.md`, `ISSUES.md` | you; append-only | record |
| `HANDOFF.md` | you | **narrative — not state** |

**Prose is not state.** The roadmap is authoritative because its entries arrived as evidence through an
applied proposal. A `HANDOFF.md` sentence that disagrees with it is a document to fix, not a fact to act
on.

**The one place that rule is easy to break is the lineage base.** It is tempting to keep the current chain
tip in the `HANDOFF.md` branch table and read the next dispatch's base out of it — the table is right
there, and it is written in your own hand. Do not. The base belongs in the chain manifest, and the
manifest is what a dispatch reads. `references/chain-manifest.md` has the format and what each position
records.

**`PRIORITIES.md` ranks; it never overrides.** Readiness is derived from whether each dependency landed.
A ranking file orders the rows that are *already* ready — the moment it starts naming a row the roadmap
says is blocked, you have two registries disagreeing and one of them is prose.

## The unknowns ledger

An effort tracks three different things, and they belong in one registry so that nothing is tracked in a
place nobody reads:

- **deliveries** — a change that lands on the chain.
- **known unknowns** — a question whose answer changes what you build. *Does the native layer have a
  kernel for this operation, or does every path fall back?*
- **probes** — a measurement you need before you can scope. *What is the blast radius of flipping this
  default?*

All three are roadmap rows. A question is not a note in `ISSUES.md` that you intend to get to; it is a row
with dependencies and an owner, because that is what makes it dispatchable and what makes it visible when
it blocks something.

**A probe reaching `done` means "we now know". A delivery reaching `done` means "the code is on the
chain".** Those are different facts and a dependent row is entitled to know which it got. `fleet` has no
field for this yet, so **put the kind in the first token of the title** (`probe: …`, `question: …`) and
say in `CHARTER.md` that you are doing so. A convention you have written down is auditable; one you are
merely observing is not.

**Unknown unknowns are not tracked — they are hunted.** They arrive as findings from workers, from the
audit routine, and from checks that disagree with each other. The obligation is that when one surfaces, it
becomes a row rather than a paragraph. See `superpowers:auditing-a-dispatch-history`.

## The cycle

```
rank the ready rows  ->  dispatch a wave  ->  integrate the wave  ->  harvest  ->  re-rank
      ^                                                                              |
      +------------------------------------------------------------------------------+
```

Load the routine when you reach it, not before:

| You are about to | Load |
|---|---|
| put several workers on one shared base | `superpowers:dispatching-a-wave` |
| turn the wave's siblings into one chain | `superpowers:integrating-a-pr-stack` |
| gate, close and empty a finished worker | `superpowers:harvesting-an-instant` |
| raise, retire or re-rank rows | `superpowers:maintaining-a-roadmap` |
| reconstruct what a dispatch contributed | `superpowers:auditing-a-dispatch-history` |

**The integration step is not optional and it is not bookkeeping.** A wave leaves N sibling branches all
rooted at the same base. Until they are linearised, there is no tip to dispatch the next wave from, and
every day they sit as siblings is a day their conflicts get worse. Integrate before you dispatch again.

## The endgame

Stop new dispatch, let the inflight work finish, integrate the last wave, gate the tip, stop.

**An item that outlives the effort is carried by two acts, both required:** a documented issue in your
workspace, where a resuming session already reads, and a `fleet milestone` on the roadmap, which makes it
reachable. The issue holds the *why*; the milestone holds the *reachability*. "Open, owned by the
coordinator, later" is an orphan — you are the coordinator and you are stopping.
<!-- v2-cite: carry-across-runs-on-fleet H9 -->

**A carry-over needs an expiry, not a paragraph.** Evidence inherited from an earlier run, or from a
dimension that flaked, is an assumption with a stated re-prove condition — never a proof. A dimension that
flaked was not verified.

## Red flags

| Thought | Reality |
|---|---|
| "The HANDOFF table says the tip is X" | Narrative is not state. Read the manifest, then confirm it on the remote. |
| "This milestone is basically about Y" | A title one word wider is what lets a real finding be dismissed as already-carried. |
| "The check returned zero, so we're clean" | A check that returns zero is the one to distrust — ask what it was able to examine. |
| "The worker proposed done, so it's done" | The proposal's note is the report. The status is the envelope. |
| "I'll draft the next three briefs while CI runs" | A brief written more than one milestone ahead decays faster than it is consumed. |
| "The wave is finished, dispatch the next one" | Siblings are not a chain. Integrate first, or the next wave builds on a base that does not exist. |
| "I'll track that question in ISSUES for now" | A question that is not a row is not dispatchable and is invisible when it blocks something. |
