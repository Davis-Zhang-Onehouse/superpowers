---
name: harvesting-an-instant
description: Use when a worker instant has finished and must be gated, closed, and emptied of everything it learned - reading the proposal's note rather than only its status, checking the inbox for a proposal that would regress a landed milestone, and re-homing findings that would otherwise die with the instant. Triggers include "the worker is done", "harvest x4", "close it out", "apply its proposal".
---

# Harvesting an Instant

## Overview

Harvesting has two halves and only the first one looks like work.

**Half one closes the worker down**: gate it, let it complete, close the pane, release the slot. It is a
sequence with a few sharp edges and it is finite.

**Half two empties it.** A worker instant is a folder full of things nobody else knows: findings it ruled
out of scope, questions it raised and answered, defects it measured in passing. When the folder goes
`-complete-`, all of that stops being anybody's. Half two is the act of deciding, for each of them,
whether it dies here.

Half two is the half that gets skipped, because half one has a satisfying end state and half two does not
announce itself.

**Announce at start:** "I'm using the harvesting-an-instant skill to close this worker out."

---

# Half one — close out

## The sequence

```
apply (dry-run, then for real)
  → fleet review          ← your gate on the work
  → the worker runs `fleet complete`   ← the RENAME is the state transition
  → pane checks (three samples + attachment)
  → fleet close
  → WAIT for the cwd-holding pid to exit
  → fleet harvest
```

Two waits, and both are where people reach for `--force`.

**`fleet close` refuses a pane holding unsubmitted input**, so teardown never discards a worker's last
turn.
<!-- v2-cite: close-refuses-queued-pane J8 -->

**`fleet harvest` run straight after `close` is refused** while the worker's process still holds the slot
as its working directory. That is exit 4 — a rule deciding against you — and it is transient, clearing in
seconds when the process exits. **Do not chain `close && harvest`**: the chained form reads as safe and
produces a confusing refusal at the end of a successful close-out, and a coordinator who reads exit 4 as
failure reaches for the one flag that could take a slot somebody is still working in.
<!-- v2-cite: harvest-commits-whole J2 -->

**`fleet harvest` exiting 1 does not mean it failed.** Read the `harvested … info` row for the outcome;
the exit status can be dominated by an unrelated standing violation.

## Never close on one pane sample

Require **three consecutive** non-wait samples from `fleet pane-guard`, and check attachment separately.
One poll in roughly a hundred has returned "not-claude" for a pane that was a live agent mid-turn — and
teardown reads that value as permission. A single sample is not an observation of an idle pane; it is one
observation, and this one is known to lie.

Distrust "not-claude" and "unknown-pane" outright while the board still calls the worker live. And note
that `pane-guard`'s "indeterminate" is a **failed observation**, not an observation of emptiness.

**Check attachment before treating anything as stuck.** A pane with unsubmitted text and a human attached
is a person mid-sentence. A pane with unsubmitted text, no human, and a busy agent is a queued note that
will deliver itself. Only a pane with an unanswered permission prompt is the case teardown logic exists
for. Reading all of these as "stuck" is how you interrupt someone.

## The review gate, exactly

`fleet review` gates the worker's `fleet complete`. The grammar is unforgiving and each mistake costs a
round:

- `--finding` is six colon-separated fields: `id:severity:status:location:finding:action`. Repeatable.
- `severity` ∈ `Critical | Important | Minor | Nit`
- `status` ∈ `open | applied | wont-fix` — **not** `ADDRESSED`, **not** `FIXED`. Those belong to your
  issue register's vocabulary and the verbs do not share a domain.
- `--verdict` ∈ `READY | READY-WITH-FIXES | NOT-READY`
- **There is no `--note`.** Everything you want on the record goes into a finding, which means your
  verification narrative becomes one finding per thing you actually checked.
- `--dry-run` evaluates the gate and writes nothing. Use it.

**Write findings about what you re-derived yourself**, not what the worker claimed. The gate is the one
place a successor sees your independent reading of the work.

**Never file your own follow-up as a finding against the worker.** An `Important` or `Critical` finding
left `open` makes the gate refuse a `READY` verdict — so filing *"the coordinator must apply the delta"*
holds a finished worker's gate hostage to your future action, for something it was forbidden to do. Your
follow-ups belong in your decisions and your next-actions.
<!-- v2-cite: open-blocking-finding-refuses-ready I2 -->

Do record a finding for a defect **you** caused that surfaced during the work. Attributing your own
mistake in the worker's review ledger is the point: it is the only place a successor reading that instant
will see it.

---

# Half two — carry the knowledge up

## 1. Read the note, not just the status

`fleet roadmap --porcelain` emits a `pending-proposal` row per proposal, and the proposer's note is the
**front of the row's detail field**. That note is the worker's actual report; the status is the envelope.

A coordinator once parsed these rows every tick for weeks and read only the status. A worker's complete
root-cause analysis — two thousand characters and a linked artifact — sat in that inbox for two hours,
printed on screen every tick, unread. Several of that effort's most valuable findings arrived through that
channel and were noticed late or by accident.

Read the note. Then decide.

## 2. Check for a proposal that would regress a landed milestone

**Before you apply anything, look at what applying would do.**

`fleet apply` moves a milestone to the status the proposal names. It validates the status name and the
evidence path — and nothing else. In particular it does not compare the incoming status to the one the
milestone already has, so **a stale proposal can move a `done` milestone backwards, at exit 0, with no
warning.**

Reproduced: a milestone landed `done`, then a stale `awaiting-ci` proposal from an earlier round was
applied, and the row moved back. Because readiness is derived, a dependent row that had opened went back
to blocked with it. Nothing in the output said anything had gone wrong.

This is `SI-48`. Until it is fixed, the check is yours:

- `fleet apply --dry-run` first, always, and read what it would land.
- Compare the proposal's status against the milestone's current status.
- Be suspicious of any proposal whose **instant has already completed** — that is the shape that produced
  the 13-day-old trap found in a live inbox.

`apply` carries the proposal's evidence onto the milestone and consumes the proposal, so replaying an
inbox cannot apply the same report twice.
<!-- v2-cite: apply-carries-evidence-and-consumes H3 -->

## 3. Carry findings up, with a non-colliding id

Findings that matter beyond this worker go into your own register. Two mechanical traps, both of which
have produced real collisions:

**Derive the next id BEFORE appending your own section.** Deriving it afterwards means your own text is
the maximum you measured against, and you renumber later.

**Check the id is not already taken.** Two instants once both appended an `I-53`, and every downstream
reference to "I-53" then meant one of two unrelated things.

Attribute each carried finding to the instant that produced it, so the original measurement stays
reachable.

## 4. Raise a row for anything that outlives the worker

An item that outlives the effort needs **both** a documented issue and a milestone on the roadmap. The
issue holds the *why*; the milestone holds the *reachability*.
<!-- v2-cite: carry-across-runs-on-fleet H9 -->

"Open, owned by the coordinator, later" is an orphan. See `superpowers:maintaining-a-roadmap` for getting
the title width right — this is exactly where a title drifts, because you are summarising somebody else's
finding.

## 5. Reconcile the completed instants

Periodically, and always at the endgame, ask the question a closed worker's folder no longer asks for
itself: **does any open issue in a `-complete-` instant have no owner?**

This has found a live product defect — a silent wrong answer, measured and reported by a worker, ruled out
of that worker's scope, and then carried by nothing when the worker completed.

**The check that finds these is itself the thing most likely to be wrong.** The first version of that
reconciliation grepped each completed instant for a status field and reported one instant as zero. The
zero was false: that instant had fifteen findings and simply did not use the field being grepped for. The
check could not see them, and it reported that as *none*.

So: **a check that returns zero must state what it examined**, and must be able to say *cannot tell*. A
zero from a check that had no way to see is not a result. If you write one of these, give it a population
line — how many instants, how many files, how many matched the shape it depends on — and read that line
before you read the count.

## Red flags

| Thought | Reality |
|---|---|
| "The proposal says done" | The note is the report. Read it before you apply it. |
| "Applying is just bookkeeping" | It can un-land a landed milestone and re-block its dependents, silently. |
| "The worker's issues are the worker's" | The worker is about to stop existing. Anything unowned dies with it. |
| "The reconciliation found nothing" | Ask what it examined. A zero from a blind check is not a zero. |
| "`harvest` exited 1, something broke" | Expected. Read the `harvested … info` row, not the status. |
| "The pane says not-claude, it's done" | One sample in a hundred says that about a live agent mid-turn. Take three. |
| "I'll note my follow-up as a finding" | An open blocking finding holds the worker's gate hostage to your future action. |
