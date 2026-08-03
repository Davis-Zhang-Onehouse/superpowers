# Recommended execution sequence — and why it differs from the impact ranking

Written 2026-08-03, alongside `../PRIORITIES.md`. Read that first for the per-gap analysis; this is the
one thing it cannot express in a table.

---

## The two orders are not the same, and that is deliberate

`PRIORITIES.md` ranks by **cost while open** — what each gap charges you for existing. That is the right
way to decide what MATTERS.

It is the wrong way to decide what to DO FIRST, because it ignores two things a ranking cannot hold:

1. **Dependencies.** A gap that must precede another is not more important; it is merely earlier.
2. **Verifiability.** Some work makes later work checkable. Doing it out of order does not just delay a
   fix — it makes the next fix unverifiable, and an unverifiable fix is one you find out about later, in
   production, from an operator.

| | ranked by cost | recommended order |
|---|---|---|
| 1 | `G-2` stall actuation | **`G-7`** (an hour, and it clears the thinking for `G-8`) |
| 2 | `G-8` false status in the registry | `G-5` (**J7 + J2 only**) |
| 3 | `G-1` delivery verb | `G-1` + `G-2` **as one piece** |
| 4 | `G-7` refusal names no route | `G-8` |
| 5 | `G-5` every case can fail | `G-4` |
| 6 | `G-4` BLOCKED discriminator | `G-3`'s cheap half |
| 7 | `G-3` dispatch scope | the rest of `G-5`, `G-3`'s full split |

**`G-7` jumps to first in the recommended order** and only fourth by cost, which is the clearest example
of why the two orders differ. It is an hour's work; it corrects a false belief that has already produced
two wrong conclusions (the reporter's and mine); and `G-8`'s central design question — should the status
choice live in an attributed proposal rather than a direct write — is `G-7`'s question. Answering it
first makes `G-8` a smaller decision.

## Why `G-5` moves from third to first — but only two cases of it

**`G-5` in full stays last.** It is the largest item and most of it is grind. What moves to the front is
a slice: the `J7` and `J2` mutations. Roughly a day.

The argument is not that those cases matter more than the stall loop. It is that **`G-3` and `G-4` are
semantic changes to states the IT suite asserts, and right now no case in that suite has been shown to
fail when its subject breaks.**

That is not a theoretical worry. In two days this line of work found six cases that could not fail, or
failed for the wrong reason:

- `II-4` — a missing fixture counted as a product failure
- `II-9` — a name match a chained call defeats
- `II-10` — a grep that matched every verb's usage block, so its bucket could never fire
- `II-8` — an aggregate reciting all its sub-assertions whatever failed
- `E9` mode 1 — one of the two row kinds `reap` actually emits
- `SI-38` — a gate reading a file nobody had opened, which **shipped**

Changing what `BLOCKED` means while the tests guarding it are unmeasured is how a regression ships green.
The suite is the instrument every later fix is verified by; calibrate it before the measurements you
intend to trust.

**`J7` earns its place on its own**, independent of that argument. Its header:

> *"a tmux session that NO record claims is reported and never reaped. If this is wrong, `reap` kills
> somebody else's pane — 'some of those sessions are people's'."*

That is the strongest safety claim in the suite and it is currently **unproven**. Not doubted — unproven.
The difference matters: nobody has broken the product and watched `J7` notice.

## Why `G-1` and `G-2` are ONE item, not two

They appear as two rows because they are two defects. They should be executed as one piece of work.

`G-1`'s deferral was reasonable when it had no caller — a new outward-acting verb in a package whose
outward call sites are audited exactly, with no concrete consumer to shape it. `G-2` is that consumer.
Building `G-2` first means a seventh implementation of the keystroke sequence `FI-15` proved everybody
gets wrong; building `G-1` first, alone, means designing a verb against an imagined caller.

Splitting them across sessions is the likeliest way this goes wrong.

## Why `G-3`'s cheap half comes before its expensive half

`G-3` is "a worker boots with an empty scope and either asks or guesses". The full fix is a two-phase
dispatch — it touches the verb's contract, the profile templates, and what `reconcile` says about a
half-dispatched instant.

But **the damaging half of the symptom is the silent wrong start**, not the empty scope itself. A worker
that ASKS has cost a turn; a worker that GUESSES has cost a branch. Making the worker refuse to start on
an unfilled scope — or having `brief` report it — removes the guessing case in an afternoon, without
touching the dispatch contract at all.

Do that, then **measure whether the full split is still worth it.** It may not be. That is a cheaper
answer than designing the split and discovering the same thing.

## The honest counter-argument to all of this

Putting `G-5` first delays `G-2` by about a day, and `G-2` is the only gap costing you something every
day. If the stall loop is hurting more than it reads on paper, invert the first two: do `G-1`+`G-2`
first, and take `J7`+`J2` immediately after, before `G-4`.

**What must not happen is `G-4` before the mutations.** That is the one ordering with a real failure mode
rather than a preference — a semantic change to the attention counter, verified by cases nobody has shown
can fail, with `FI-14` having already changed that same tuple yesterday.

## The two constraints that are not preferences
1. **`G-1` before `G-2`** — or accept a seventh send implementation and record it as debt.
2. **Never change `ACTIONABLE_STATES` semantics twice without measuring in between.** `FI-14` widened it
   on 2026-08-02; `G-4` would change it again. Two changes and one measurement makes any regression
   unattributable — the failure this whole line of work keeps re-learning.
