---
name: integrating-a-pr-stack
description: Use when several sibling branches delivered on a shared base must become one linear PR chain per repo - reusing the existing PRs, moving each paired repo's pin with the position it belongs to, and grading the resulting tip. Triggers include "restack the wave", "make these siblings one chain", "linearize the PRs", "the four wave branches all sit on the same base".
---

# Integrating a PR Stack

## Overview

A wave leaves N branches all rooted at the same base. They are siblings. The deliverable is a **chain** —
each position on top of its predecessor, one scoped change per PR, a tip somebody can merge.

Turning siblings into a chain is its own milestone with its own worker, because it needs authority no
ordinary worker has (force-push over branches other instants delivered) and produces a result no ordinary
worker can: the tip that the next wave dispatches from.

**You write no new production code and no new tests.** Conflicts are resolved preserving both sides'
delivered behaviour. That constraint is what makes this safe to grant force-push for.

**But do not read it as "this is mechanical."** The restack is the first time these changes share a tree,
which makes it the operation most able to surface a defect that belonged to no member instant. Step 7
exists for that and it is not a formality.

**Announce at start:** "I'm using the integrating-a-pr-stack skill to restack this wave."

## The routine

| # | Step |
|---|---|
| 1 | Snapshot every ref — including the ones you will not touch |
| 2 | Confirm the force-push grant is an enumerated list, not a pattern |
| 3 | Decide the order, and treat it as load-bearing for correctness |
| 4 | Rebase, moving each position's pins with it |
| 5 | Retarget the PRs; never rename a branch |
| 6 | Grade the tip, and never grade absence |
| 7 | Hunt for the failure that belongs to no member |
| 8 | Write the new tip back to the chain manifest |

## Step 1 — snapshot both sides of the question

Before touching anything, capture `git ls-remote` for every repo in play. Not just the branches you are
about to move — **all of them**.

The reason is that the proof obligation has two halves. "Did my branches end up where I meant?" is the
easy half. "Did anything *else* move?" is the half a targeted check has no way to answer, and it is the one
that matters when you have been granted force-push. A diff of the before and after snapshots answers both
at once.

Capture the snapshots into the instant's evidence directory as files, not as terminal scrollback.

## Step 2 — the grant is a list

Force-push authority is **an enumerated set of refs**, written down before you start. Not a glob, not "the
branches from this wave", not a prefix. A list.

Everything not on the list is untouchable — including refs that look like they belong to this effort, and
especially the positions *below* the fork point, which earlier waves already delivered and other work may
already sit on.

If the list turns out to be wrong mid-restack, stop and get it re-issued. Do not extend it yourself; the
whole value of an enumerated grant is that it was decided before you were in the middle of something.

**Force-with-lease, never plain force.** A lease failure means the ref moved under you, which means
somebody or something else is writing it — that is a stop-and-report event, not an obstacle. This matters
most when a sibling's own instant is still alive: a worker in `awaiting-ci` can still push.

## Step 3 — the order is load-bearing for correctness

The obvious ordering heuristic is cost: put the kernel-coupled positions low where their rebases are hard,
and the test-only positions high where the rebase is near-trivial. That heuristic is fine and usually
right.

**It is not the whole question, because order can change behaviour.** A dispatch chain that selects the
first matching rule and then flattens away a `None` will let a rule whose match is broader than its build
**swallow the message and drop it** — so a rule that lands *above* another in the chain can silently
disable it. Two rules that both pass their own suites in isolation can produce a wrong answer in one
order and a right answer in the other.

So for each wave, ask explicitly: **is there a correctness constraint on the order here, separate from
cost?** Write the answer down, with its reason, in the instant's decisions. "Kernel-coupled first" is a
cost argument; it is not an answer to that question.

## Step 4 — pins move with positions

This is the part that has no single-repo equivalent, and the part that fails quietly.

In a pinned multi-repo stack, each position of the primary repo builds against a specific commit of each
paired repo, resolved through a pin file in the tree. When you rebase the primary chain, **every
position's pin must be updated to point into the rebased paired history** — not the pre-restack history it
was originally cut against.

A position whose pin still points at the old history **builds and tests green**. It is simply testing
different native code than the one you think you are shipping. There is no error, no conflict, and no
signal — which is why this gets its own step rather than a line in step 4's commit message.

Order the repos accordingly: **paired repos first**, so their chained history exists before the primary
chain needs shas to point at.

At every position, the pinned commit must contain all the paired-repo changes the primary code at that
position needs. At the tip, the pin equals the paired chain's tip. Prove both by resolving the pin from
the tree, not by reading your own commit message.

`references/pinned-multi-repo.md` has the worked example.

## Step 5 — reuse the PRs, keep the branch names

**Zero PRs created. Zero closed.** The PR numbers are the review history, and a restack that opens fresh
PRs throws away every comment on the old ones.

**Never rename a branch.** A PR follows its head ref; renaming the branch breaks the association and
forces exactly the new-PR outcome you are avoiding. If two branch names collide cosmetically or a name is
now misleading, leave it — a confusing name costs a sentence of explanation, and a renamed one costs the
review history.

Retarget each PR's base to its new parent, and update the base named in the PR description if it carries
one. After retargeting, each PR's files-changed should show **only its own delta**; if it shows its
parent's too, the base is wrong.

## Step 6 — grade the tip, and never grade absence

The chain's tip is what gets graded. A member passing where it used to sit proves nothing about the chain.

Grade against a named list of required job names as that list reads **at grade time**, and confirm the
jobs **demonstrably executed** at the graded sha. Two ways a grader lies about this, both observed:

- **A job that never ran scores clean** under a check keyed on "did any step fail?". A reclaimed or
  cancelled runner produces a conclusion of failure with not one failed step — every step `skipped` or
  `cancelled`. Keyed on failures, that is zero failures.
- **A red run that was re-queued leaves the failed bucket.** A count of failing checks drops to zero
  because the failure was *replaced by a pending attempt*, not because anything went green.

So the grade is a positive assertion — *these named jobs ran, at this sha, and concluded success* — never
the absence of a red one. Where a job legitimately did not trigger, say so explicitly and say why; a
non-trigger recorded as a pass is the same defect wearing a better word.

Check attempt numbers. A run at attempt 3 had two earlier failures that the current view may no longer
show.

## Step 7 — the failure that belongs to no member

Because the restack is the first time these changes coexist, it can produce failures that no member
instant could have found and that no member instant owns.

The clearest shape is **suite order-fragility**: three suites that each pass alone, and fail when they run
in one tree in one JVM because one of them leaves global state behind. Measured exactly that way — alone,
passes; after a sibling's suite in the same process, fails.

Look for it deliberately at the tip:

- run the full set the chain now carries, in one tree, and compare against each member's own recorded run;
- treat any test that passes in isolation and fails in the chain as a **finding of this milestone**, not
  as somebody else's flake;
- if it belongs to no member, it belongs to the effort — raise it, with the measurement.

The failure mode this step exists to prevent is diagnosing such a failure as a pre-existing flake and
moving on, because every member's own evidence says it passed.

## Step 8 — write the tip back

The chain manifest is what the next wave dispatches from. Update every moved position: new tip sha, new
parent, new pins, and the grade with the sha it graded. State the new tip in the report you hand up.

## Red flags

| Thought | Reality |
|---|---|
| "It's a restack, the work is already graded" | It is the first time these changes share a tree. |
| "Nothing failed, so the tip is green" | A job that did not run is not a job that passed. Assert execution. |
| "I'll rename the branches to something cleaner" | Renaming breaks PR reuse, which is the point of the exercise. |
| "The pins were right before the rebase" | They pointed into unchained history. Every position's pin moves with it. |
| "This test is flaky, it passes locally" | Passes alone, fails in the chain, is a finding — and it is yours. |
| "The lease failed, I'll force it" | A lease failure means something else is writing that ref. Stop and report. |
| "My branches all moved correctly" | And did anything else? That is the half a targeted check misses. |
