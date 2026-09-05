---
name: maintaining-a-roadmap
description: Use when putting work on the milestone registry or changing what is already there - writing a title exactly as wide as the finding it carries, adding dependencies that must exist when typed, retiring superseded rows with a reason the successor needs, and ranking the ready population without overriding a blocker. Triggers include "raise a milestone", "a finding just landed", "re-rank the priorities", "retire that row", "the roadmap is out of date".
---

# Maintaining a Roadmap

## Overview

The roadmap is the effort's registry, and you are its only writer. Workers propose; `fleet apply` is what
moves a status.
<!-- v2-cite: apply-is-the-single-writer H2 -->

Most of the mechanics are in `superpowers:coordinating-instants`. This skill is about the two properties
that decide whether the registry is *true*: whether each row is **exactly as wide as what it carries**,
and whether the work it names is **reachable**.

Both fail quietly. A registry full of rows that are individually plausible and collectively misleading
looks exactly like a healthy one.

**Announce at start:** "I'm using the maintaining-a-roadmap skill to update the registry."

## 1. Title width is the discipline

A milestone's title is the only part of it most readers ever see. It is what an adjudicator matches on
when asking *"is this finding already carried by an existing row?"* — so a title that is the wrong width
does not merely read badly, it changes what gets dropped.

**Both directions have failed, four days apart, in the same effort.**

**Too narrow.** A row titled for `array<bigint>` whose underlying finding also covered maps and structs.
The narrow title made the other two invisible: anybody scanning the registry for map coverage found
nothing and reasonably concluded nobody had looked.

**Too broad, and this one is worse.** A row asserting a scope that its own worker had declared undelivered
— *in writing, in that worker's own handoff*: "the milestone title is now a misnomer for what was
delivered." The row read `done`. Anything that title covered was now, to every future reader, finished.

Too broad is worse because of the direction the error travels. A narrow title loses a finding that someone
may re-find. A broad title **actively dismisses** the finding when it is re-found, because there is
already a `done` row that appears to cover it.

**The test, applied when you write the title and again when you apply a `done`:**

> Name something this title claims that the work did not actually establish. If you can, the title is too
> broad. Name something the work established that this title does not claim. If you can, it is too narrow.

Run it at both ends. The second run matters more, because what a worker delivers is routinely not what its
title anticipated, and the moment of applying `done` is the last moment anybody looks.

## 2. Readiness is derived — never store it

`fleet roadmap` recomputes readiness from whether each dependency reached `done`, and names the blocker
for every row that is not ready.
<!-- v2-cite: readiness-is-derived H1 -->
Do not maintain a `ready` flag by hand. A stored copy of a fact the dependencies already carry drifts the
moment a dependency slips — and it drifts silently, because both the flag and the dependency look right in
isolation.

**Know what the derived view will and will not show you.** It emits a row for every milestone that is
*not* ready, plus a population row, plus pending proposals. **It emits no row for a milestone that is
ready** — the ready count appears only inside the population row's prose. That is `SI-47`. Reconstruct the
ready set explicitly rather than assuming a quiet roadmap means no work is available; a roadmap with
twenty dispatchable rows and no blockers prints almost nothing.

## 3. Three kinds of row

An effort tracks deliveries, questions and probes (see `superpowers:running-a-stacked-effort`). `fleet` has
no field for this yet (`SI-42`), so put the kind in the **first token of the title** and record the
convention in `CHARTER.md`.

The distinction earns its keep at `done`. A probe reaching `done` means *we now know*; a delivery reaching
`done` means *the code is on the chain*. A dependent row that opens because its dependency landed is
entitled to know which of those it got — and if you cannot tell from the registry, you will assume the
second, because that is what `done` normally means.

## 4. Dependencies are checked when you type them, and not editable afterwards

Every `--dep` must already exist on the roadmap, and it is checked at the moment you type it. A typo'd
dependency is not an error later; it is a milestone that reads as permanently in progress. Add
dependencies in order — a row before the rows it depends on is a row you have to retire and re-raise.

**And you get one chance.** Raising a milestone whose id already exists is rejected with *"refusing to
shadow it"*, and there is no amend verb. (That one is covered by `fleet`'s hermetic suite rather than by an
integration case, so it carries no citation here — the guarantee is real, the evidence just lives
elsewhere.)
So **a dependency discovered after a row is raised has nowhere mechanical to live.** This is `SI-44`, and
it is the most consequential gap in this routine.

Two workarounds, in order of preference:

**Retire and re-raise**, when the row has not started. The new row carries the dep, and the retirement
reason names the original. History is preserved and the constraint is mechanical.

**Carry it in `PRIORITIES.md` and enforce it at dispatch**, when the row is already inflight or already
depended on. This is a real workaround and you should name it as one in the file itself.

Understand what you are accepting when you take the second option. The live example from the source
effort is an ordering constraint between two cast-family rows: dispatched in the wrong order, the second
one *ships map entries that never fire, and grades green*. **A constraint whose violation produces a
green result is exactly the kind that must not depend on somebody remembering to read a paragraph.**
Where you are forced into prose, put the constraint at the top of the ranking file, in the row's own
entry, and in the dispatch note — three places, because the failure is silent.

## 5. Retire with a reason the successor needs

A superseded row is retired, not left to rot: once its dependencies land it derives ready forever, and a
phantom ready row is worse than no row.

**The reason is not a courtesy field.** Write what the superseding row must not lose. The good retirement
reasons in a mature roadmap read like handover notes — *"superseded by X: the title carried the cost
ranking, and dropped two sequencing constraints that are not negotiable"* — because the next person to
read them is deciding whether the new row is adequate.

A retirement reason that says only "superseded" throws away the one thing retiring knew that raising did
not.

## 6. `PRIORITIES.md` ranks; it never overrides

A ranking file orders the rows that are **already derived ready**. The moment it names a row the roadmap
says is blocked, you have two registries disagreeing, and the one made of prose will win because it is the
one a human reads first.

State that constraint at the top of the file. Then keep the file honest: strike completed entries in
place, so the ranking reads as a record of what was dispatched and why, rather than a wish list that
silently accumulated.

## Red flags

| Thought | Reality |
|---|---|
| "I'll widen the title so it covers both findings" | A broad title is what lets a real finding be dismissed as already-carried. |
| "The worker delivered roughly what the title said" | "Roughly" is where the drift lives. Re-run the width test before applying `done`. |
| "I'll add the dep later" | There is no amend. Retire and re-raise, or accept a silent constraint. |
| "PRIORITIES says it's next, so dispatch it" | Ranking never overrides a derived blocker. |
| "The roadmap is quiet, so there's nothing ready" | It prints blockers, not opportunities. Reconstruct the ready set. |
| "It's superseded, just drop it" | The reason is where the successor learns what it must keep. |
| "This is a question, I'll note it in ISSUES" | A question that is not a row is not dispatchable. |
