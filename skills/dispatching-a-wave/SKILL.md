---
name: dispatching-a-wave
description: Use when putting several worker instants in parallel onto one shared base - deriving the cap from the guard rather than a formula, taking the lineage base from the chain manifest rather than prose, and writing each worker's scope before releasing its seed. Triggers include "dispatch the next wave", "two rows are ready on the same base", "put three workers on this", "dispatch these milestones in parallel".
---

# Dispatching a Wave

## Overview

A **wave** is several workers admitted onto **one shared base** at roughly the same time. Each takes a
different milestone, cuts its own branch from the same lineage base, and opens its own PR. They are
siblings, not a chain — linearising them is a separate job
(`superpowers:integrating-a-pr-stack`).

Dispatching one worker is a `fleet dispatch` away and `superpowers:coordinating-instants` covers it.
Dispatching *several* adds four problems that one does not have: which rows are actually dispatchable, how
many you are allowed, whether two of them will collide, and a race between creating a worker and telling
it what to do.

**Announce at start:** "I'm using the dispatching-a-wave skill to dispatch this wave."

## The routine

| # | Step | Why it is not optional |
|---|---|---|
| 1 | **Re-derive the ready set and state it out loud.** | No verb enumerates it. See below. |
| 2 | **Take the base from the chain manifest, then confirm it on the remote.** | `fleet` checks that the slot *arrives* at the sha; nothing checks that it was the right sha. |
| 3 | **Ask the guard for the cap. Never compute it.** | The guard counts records; you would be counting your recollection. |
| 4 | **Declare the surface each worker will touch, or sequence them.** | Two workers on one file is a real event, not a hypothetical. |
| 5 | **`dispatch` → write the scope → *then* release the seed.** | The seed is the release signal, and the window is 180 seconds. |
| 6 | **Verify the launched process carried the right environment.** | A worker can come up attributed to somebody else. |
| 7 | **Write briefs one milestone ahead, never two.** | A brief written early decays faster than it is consumed. |

## Step 1 — the ready set is not printed anywhere

`fleet roadmap --porcelain` emits `not-ready` rows, `pending-proposal` rows, and one `population` row. It
does **not** emit a row for a milestone that is ready. The count is interpolated into the population row's
English:

```
population  <instant>  info  examined 3 milestone(s) of which 2 ready, 0 pending proposal(s), from <path>
```

So the one thing you are about to act on is the one thing you must parse out of a sentence — against the
standing rule that you read columns and never prose. This is `SI-47`.

Until it is fixed, derive the set explicitly and **write it down before dispatching any of it**: read the
roadmap file, subtract every row whose dependencies have not landed, subtract every row already claimed by
an inflight instant, and state the remainder. A set you named is auditable; a set you had in mind while
dispatching is not.

Do not skip the "already claimed" half. A ready row with a live claim is not dispatchable, and the two
facts live in different places — the roadmap knows readiness, `fleet board` knows claims.

## Step 2 — the base comes from the manifest, then from the remote

Read the current tip from the chain manifest, then confirm that ref still resolves to that sha on the
remote before you type it. Both halves matter: the manifest saves you from retyping a prose table, and the
remote check catches a manifest that has gone stale.

`--lineage-base` is the single authority for what a worker builds on. It is rendered into the seed and the
charter, and a claim of done from a slot that is not at the base is refused.
<!-- v2-cite: done-from-wrong-base-refused LB2 -->
What is **not** checked is whether the sha you typed was the correct one for that milestone. That
judgement is yours and there is no safety net under it.

For a wave, every member normally takes the *same* base — that is what makes them a wave, and what lets
the integration step assume a common root.

## Step 3 — ask the guard, do not compute the cap

Run the dispatch with `--dry-run` first and read `guard.wip-cap` out of the output:

```
guard.wip-cap  allow: 0 of 1 active-dev slot(s) in use. examined 0 subject(s) of 00000000; 0 counted, 0 excluded
```

That row names the count, the cap, the population examined, who is counted and who is excluded. It is the
answer. The guard's own cost note says it is free and safe to ask before every dispatch and safe to ask
twice, so there is no reason to ask anything else.

**Do not carry a formula.** The tempting one — *me, plus the workers already running, plus this one* — is
a remembered number with arithmetic on top, and it is **wrong in at least one ordinary case**: the cap
counts *records*, so whether your own coordinator counts depends on how it was created. A coordinator that
was itself dispatched has a record and counts, permanently. A coordinator created with `fleet init` has no
record and does not. Measured against a scratch store, an `init`-created coordinator with one worker
wanted reports `0 of 1` — the formula predicts 2.

A worker that has declared `awaiting-ci` stops counting; the declaration is what does it, and the same
words written as prose into a handoff do not.
<!-- v2-cite: declaration-frees-the-cap F2 -->
<!-- v2-cite: prose-does-not-free-the-cap F3 -->
A second dispatch over the cap exits 4 — refused by an admission rule, which is a rule deciding against
you rather than anything being broken.
<!-- v2-cite: cap-refuses-second-dispatch F1 -->
An inflight compaction of the same effort freezes dispatch entirely and names the instant responsible.
<!-- v2-cite: compaction-freezes-dispatch F4 -->

**The cap is not the only gate, and it is the weaker one.** The cap says how many *may* run. Your own
standing rule about how few must be left before another starts is a different question with a different
population, and the cap will happily admit a worker your throughput cannot absorb.

## Step 4 — collision is a real event

Two workers on the same file, at the same time, on sibling branches, is not a hypothetical. It has
happened at a scale that surprised the coordinator who found it: seven files under concurrent authorship
by two live workers, discovered after both had been running for hours.

Before dispatching a wave, for each member say **which surface it will touch**, and check the members
against each other. Where two overlap, either sequence them or give both charters an explicit note naming
the other and saying who resolves.

The reason to do this at dispatch rather than at integration is that a collision found at integration is a
merge conflict you resolve blind — neither worker is still around to say what they meant.

## Step 5 — scope before seed, and the window is 180 seconds

This is the ordering that costs the most when it is wrong.

`fleet dispatch` creates the child instant and writes its `CHARTER.md` **rendered from the profile**,
which means the scope section is whatever placeholder the profile carries. The launcher shim then waits up
to **180 seconds** for a seed; if none arrives it starts an interactive session anyway, and the worker
comes up holding a milestone claim with no briefing.

You fill the real scope into the child's `CHARTER.md` inside that window. So:

1. `fleet dispatch` (the instant now exists, with a placeholder scope)
2. write the real scope and acceptance criteria into the child's `CHARTER.md`
3. **only then** compose and release the seed

**Treat the seed as the release signal.** It is the last thing you do, and the worker does not begin until
it lands.

Two ways this goes wrong, both measured:

- **You take longer than 180 seconds.** One dispatch missed it by about a second; the worker booted with
  no seed argument at all.
- **The worker reads the charter while you are writing it.** One worker read a charter *growing under it*
  — 28,609 bytes, then 37,401 — and filed a decision on the premise that its scope and acceptance criteria
  were empty. They were mid-write. It withdrew the claim itself, which is luck, not a mechanism.

Nothing on your side catches this today. The `authoring-placeholder` lint does not run from any command a
coordinator can type (`SI-45`), and it would not match the HTML-comment placeholder convention anyway
(`SI-46`). **The only working defence is a self-check in the profile** — a first instruction telling the
worker to park if its scope block is still a placeholder rather than infer scope from the milestone title.
Put one in every worker-facing profile you author.

## Step 6 — verify what actually launched

Read the launched process's environment and confirm it carried the workspace's identity rather than the
tmux server's. A worker running under the wrong credential does not fail loudly — an API call returns an
empty list, which reads exactly like *nothing is wrong*.

Check the variable is **present**; never print its value.

## Step 7 — one milestone ahead

Writing the next brief during a CI wait feels like good use of dead time. It is, for exactly one
milestone. Beyond that the brief **decays faster than it is consumed**: a predecessor lifts a quarantine,
a decision supersedes a measurement, a tool moves, and the brief now teaches something that was true when
written.

If you deliver a brief written earlier, re-verify every claim in it that a predecessor could have changed
— every sha, every count, every "already measured, do not redo" — and record in the dispatch note that you
did. Then a claim that turns out wrong is attributable to a measurement rather than to staleness.

## Red flags

| Thought | Reality |
|---|---|
| "Cap 3 for three workers" | `--cap` counts records, not intentions, and whether yours is among them depends on how you were created. Read the guard. |
| "I'll fix the charter right after it boots" | The 180-second window is the whole race. Scope first, seed last. |
| "These two milestones are unrelated" | Seven files once said otherwise. Declare the surface; do not assume it. |
| "The profile lints clean" | Nothing lints a profile from the command line. That claim is not re-derivable today. |
| "The roadmap says two are ready" | It says a *number*, in prose. Name the rows before you dispatch them. |
| "The base is in my HANDOFF table" | That table is narrative. The manifest is state, and the remote is truth. |
| "I have three slots free, so I can run three" | Free slots are capacity, not throughput. The cap admits workers you may not be able to absorb. |
