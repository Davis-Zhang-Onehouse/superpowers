# Impact analysis and suggested priorities   (written 2026-08-03; revisit if the facts move)

`G-6` is CLOSED (`d07b4a2`). `G-7` and `G-8` were added 2026-08-03 from `FI-16`/`FI-17`, which
arrived in the coordinator's register that night. **Seven remain.** This ranks them by **what each one costs while it stays open**,
not by effort — effort is the tiebreak.

## The ranking

| # | gap | cost of leaving it open | effort | risk of fixing | blocked by |
|---|---|---|---|---|---|
| 1 | **G-2** stall actuation | **the operator is the mitigation, daily** | M | low | wants `G-1` |
| 2 | **G-8** no honest closing status | **a false status in the authoritative registry, twice in five days** | M | med | `G-7` first |
| 3 | **G-1** pane-delivery verb | 6 send paths drift; blocks `G-2` | M | med | a design call |
| 4 | **G-7** refusal names no route | readers conclude "impossible" — **it already happened twice** | S | low | nothing |
| 5 | **G-5** every case can fail | the gate's own trustworthiness is unmeasured | L | none | nothing |
| 6 | **G-4** BLOCKED discriminator | a wrong nudge target; gates `G-2`'s safety | S–M | **high** | brainstorm |
| 7 | **G-3** dispatch scope race | one wasted turn per dispatch, sometimes | M–L | med | brainstorm |

## Why in that order

### 1. `G-2` — the only gap with a human paying for it every day
Everything else costs latent risk. This one costs **you**, continuously: *"the entire system stuck forever
until I send messages waking folks up."* The detection half shipped in `0.2.3`; the actuation half has no
owner but you.

It is also the gap whose cost **grows with the fleet**. One stalled worker is a nudge; five concurrent
efforts stalling independently is a full-time polling job. Every other gap's cost is flat.

**Counter-argument, honestly:** the mitigation exists and works. This is not on fire — it is a tax. But
it is a tax on the scarcest thing here, which is your attention, and it is the only item on the list
where "do nothing" has a recurring price.

### 2. `G-1` — small in itself, and the thing `G-2` should be built on
On its own this is bookkeeping: six callers each implement a keystroke sequence. It ranks second because
`G-2` needs it, and building `G-2` without it means a seventh implementation of the exact primitive
`FI-15` proved everybody gets wrong.

**Take them as one piece of work.** `G-1`'s deferral was reasonable when it had no caller; it has one now,
which is precisely the argument it was missing. The design call left is small — verb vs library, and
whether it gates internally (it should: that is the choke point `DA-2` wanted).

**Risk to watch:** it is a new *outward-acting* verb in a package whose outward call sites are audited
exactly. Route the send through `session.default_probes` and the seam count stays three; do it any other
way and §M9 fails, correctly.

### 2. `G-8` — the only gap that puts a FALSE FACT in the authoritative registry
Every other gap costs a missing signal, a wasted turn, or unmeasured confidence. This one writes
something untrue into the thing successors read: `q4 = done` means "the tests pass", and they are
permanently disabled by sanction. The compensation was prose in three places, and the skill's own rule
says prose is what not to trust.

**Twice in one five-day effort** (`p1`, `q4`) — common, not exotic. And it composes: `--retire` writes
`dropped`, `dropped` does not land, so retiring strands dependents. We already shipped that trap and
fixed its severity half (`11f2f58`); the vocabulary gap remains.

**Take `G-7` first** — if `--retire` becomes sugar over propose/apply, the status choice moves into the
proposal where it is attributed and evidenced, which is the right home for a decision this consequential.

### 4. `G-7` — small, and it is the cheapest correction of a real cost
One clause on one refusal. It ranks fourth on cost and would rank first on ratio: it has already caused
two wrong conclusions — the reporter's `FI-10` entry, and MINE, which I shipped a verb on top of.

It also names a CLASS worth auditing: a refusal that states its rule and no route. `FI-5` was that shape
with an impossible route; this is the same shape with an absent one.

### 5. `G-5` — the one that decides whether any of the rest can be trusted
No design, no decisions, no blockers. Pure grind, and it is the only item that measures the **instrument**
rather than the product.

The case for doing it before `G-3`/`G-4`: those are semantic changes to states the suite asserts, and
right now **no case in that suite has been shown to fail when its subject breaks**. Changing what
`BLOCKED` means while the tests guarding it are unmeasured is how a regression ships green.

The case against: it is the largest single item, and its first target (`J7`) protects against a failure
nobody has actually observed.

**Compromise, and my recommendation:** do `J7` and `J2` — the two highest-consequence targets, perhaps a
day — before starting `G-4`, and leave the rest of the frame as background work. `J7` is worth it alone:
*"if this is wrong, `reap` kills somebody else's pane."* That claim is currently unproven.

### 6. `G-4` — highest risk-of-fixing on the list, and it gates `G-2`'s safety
Small change, large blast radius: it alters what an existing state MEANS, on the state driving the
attention counter, which `FI-14` widened yesterday.

It ranks above `G-3` only because `G-2` needs it — **a nudge must never go to a pane a human is attached
to**, and today nothing can tell. If `G-2` ships first it will need an interim `#{session_attached}`
check of its own, which is a second implementation of this discriminator and should be recorded as
temporary if taken.

**Two traps, both already written into the brief:** the reporter's original remedy is RETRACTED (deriving
BLOCKED from `park.json` deletes the signal, because a worker at a permission modal has no `park.json`
either) and you nearly implemented it. And the sequencing — `FI-14` already changed this tuple, so
measure the attention count between the two changes or a regression is unattributable.

### 7. `G-3` — real, bounded, and the least urgent
A worker boots with an empty scope and either asks or guesses. Costs a turn, occasionally a wrong start.
Genuinely annoying; nobody is blocked.

It ranks last because the cost is per-dispatch and bounded, while the fix touches the core dispatch
contract — every dispatch on the box uses the single-call form.

**There may be a cheap 80% here that is worth taking first:** make the worker REFUSE to start on an
unfilled scope, or have `brief` report it. That removes the silent-wrong-start case without touching the
two-phase dispatch question at all, and it can be done in an afternoon. Worth measuring before committing
to the full split.

## Two sequencing constraints that are not negotiable
1. **`G-1` before `G-2`**, or accept a seventh send implementation and record it as debt.
2. **Do not change `ACTIONABLE_STATES` semantics twice without measuring in between.** `FI-14` widened it
   on 2026-08-02; `G-4` would change it again. Two changes, one measurement, and any regression is
   unattributable — which is the failure this whole line of work keeps re-learning.

## What I would actually do, in order
**This differs from the ranking above, deliberately — the reasoning is in
`evidence/recommended-sequence.md`.** A ranking by cost-while-open cannot express dependencies or
verifiability, and both change the order.

1. **`G-7`** — an hour. One clause on a refusal, and decide whether `--retire` becomes sugar over
   propose/apply. It is a prerequisite for thinking clearly about `G-8`.
2. **`J7` + `J2` mutations from `G-5`** — a day, no decisions, and it makes everything after it
   verifiable.
3. **`G-1` + `G-2` as ONE piece** — stops the daily tax and closes the loop properly.
4. **`G-8`** — brainstorm the vocabulary; measure readiness on a real roadmap before and after any
   `LANDED` change.
5. **`G-4`** — brainstorm first, measure the attention counter before and after.
6. **`G-3`'s cheap half**, then measure whether the full split is still needed.
7. The rest of `G-5`'s frame, and `G-3`'s full split, as background.

## Health warning
`A-1` in `ASSUMPTIONS.md` applies to every row above: these briefs describe the tree at `0.3.1`.
**Re-measure before starting.** Of the findings picked up on 2026-08-02/03, `FI-8` was already fixed,
half of `FI-11` was already fixed, and `FI-3` was not a fleet defect at all — three out of about a dozen.
