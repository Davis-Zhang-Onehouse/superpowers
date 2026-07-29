---
name: coordinating-instants
description: Use when a Claude session is appointed the standing coordinator / orchestrator of a multi-milestone effort executed by parallel dispatched worker instants, or is resuming that role after a restart. Triggers include "you are the coordinator/orchestrator instant", "central task/milestone registry", "dispatch one instant per milestone", "poll the workers and coordinate", "harvest deliverables into the catalog", "what's the fleet status", "resume coordinating", "proceed autonomously, I'll be unavailable for N hours".
---

# Coordinating Instants

## Overview

A **coordinator** (orchestrator) is a long-lived Claude session that owns the *central task/milestone
registry* for an effort and drives it through **parallel worker instants** — one dispatched session per
milestone. It does NO dev itself.

**Core principle: you are the single source of truth and the fleet's engine — you verify everything from
artifacts, you gate every worker, you keep every eligible slot full, and you never take an irreversible
operator-only action on your own.** Violating the letter of these rules violates the spirit.

**REQUIRED SUB-SKILLS** (this skill runs the loop between them; it does not restate them):
- superpowers:maintain-workspace — the instant model; your own registry; the `compact` op.
- superpowers:dispatchInstants — the dispatch mechanism (`pdispatch` pool/todo/board) + fleet monitoring.
- superpowers:reviewing-workspace — invoked as `superpowers:review-workspace`; the completion gate for
  workers, and a periodic format-only pass on your OWN registry (a coordinator's workspace rots too).

Chartering uses superpowers:brainstorming → superpowers:writing-plans. Workers are seeded RCA-first
(superpowers:systematic-debugging → superpowers:test-driven-development). For a shareable status board or
close-out, superpowers:rendering-task-board — an optional close-out, not part of the loop.

**Your registry schema is `coordinator-registry.md` in this skill directory** — copy its four tables
(milestone registry · fleet/slots · lineage tracker · single-writer catalog overlay) into your HANDOFF.md
Part A before your first dispatch. Every step below reads and writes those tables.
**What you must put in each worker's brief is `brief-contract.md`** in this skill directory.

## The tools — run these instead of remembering

Most of what used to be "watch out for X" is now enforced. Prefer the command over the vigilance.

| Command | Replaces the vigilance of |
|---|---|
| `pdispatch health` | hand-rolled liveness; catches DEAD / BLOCKED-on-modal / IDLE / COMPLETE-unharvested. Exit 1 = something needs you. Run it every tick. |
| `pdispatch gate <instant> [--harvest]` | reading a REVIEW.md and talking yourself into "findings addressed". Fails closed; `--harvest` also requires the worker's own `-complete-` rename. |
| `pdispatch drift --handoff <f> --instants-dir <d>` | eyeballing the registry for rot; finds done-but-unharvested and stale rows. |
| `pdispatch regress --baseline B --current C --lineage-base L [--closed-from-md REG]` | the two-diff rule + re-asserting every registry-closed row by name. |
| `pdispatch send <id> <msg>` | "I sent it" — verifies the message actually landed, retries, fails loudly. |
| `pdispatch launch <id>` | hand-building a launch line; replays the RECORDED seed, correctly quoted. |
| `pdispatch pool reap --base <your-instant>` | remembering not to stomp another effort's slot — foreign leases are now refused by default. |
| `pdispatch guard <repo> <shared-branch>` | trusting workers not to push the shared base branch. |
| `pdispatch profile <profile-dir>` | trusting a dispatch profile; lints it against the contract (single-writer, gate, report-back, rename) by profile KIND. Run before selecting one, and after editing one — a defect patched only in a brief leaves the profile armed for the next effort. |
| `pdispatch gate <instant> --harvest --record` | harvest state living only in prose; records the verdict + `harvested_at` in the board so a successor coordinator inherits it (and finished work stops asking for attention). |
| `pdispatch health --base <your-instant>` | a shared board showing every effort's records as if they were yours. |
| `pdispatch ref protect\|worktree <ref>` | trusting workers not to write a shared reference checkout. |

`dispatch-todo` now also persists the rendered seed, archives the profile into the child instant,
and points each workspace at its own build cache — no longer your job to remember.

## Cold start (first 5 minutes — do this on every fresh/compacted session)

You are long-lived and WILL restart mid-effort. Never answer "status?" from memory.

1. `cd` to your coordinator instant; read HANDOFF.md Part A (the four tables) → CHARTER → DECISIONS → ISSUES.
2. `pdispatch board` and `pdispatch pool list` — the live truth about the fleet, across ALL efforts.
3. Reconcile the fleet table against reality: which slots are yours, which are another effort's, which are
   FREE/STALE. Fix the table; it rots the moment you look away.
4. `pdispatch health` — leased ≠ alive; this also surfaces work already owed to you
   (done-but-ungated, blocked, idle). Then `pdispatch drift` on your registry.
5. Then enter the tick loop. Only now are you entitled to report status.

## Every tick (~10 min while work is live)

1. **`pdispatch health`** — one command; exit 1 means something needs you. It classifies DEAD /
   BLOCKED (permission modal) / IDLE / COMPLETE-unharvested, so a lease is never mistaken for a heartbeat.
2. **Parked forks** — read every live worker's HANDOFF `## Parked decision`. Decide the ones that are yours
   (see Autonomy); escalate only genuine operator-only forks.
3. **Done → gate** (`pdispatch gate <instant> --harvest --record`, Phase C). **Gated → harvest** (Phase D).
   `--record` now **closes the worker's session** as part of the same transaction and frees its slot —
   teardown used to be a separate decision that simply never got made, and finished sessions outlived
   their effort by nine days while holding a pool slot another worker had since been given. If you have a
   reason to keep one alive, `--keep-session "<reason>"` records it: keeping is what needs justifying now.
4. **Under the WIP cap AND no compaction inflight → dispatch** the next READY milestone (Phase B). Check the
   cap with **`pdispatch health --base <your-instant> --active-dev`**; at or over it, do not dispatch. The
   compaction gate is separate: `pdispatch todo`/`launch` exit 4 while a `*-inflight-compact-*` sibling
   exists, even when the cap says you have room — but see the KNOWN GAP under "A compaction instant is
   EXCLUSIVE": a green `pdispatch todo` does not prove no compaction is inflight, so eyeball the instants
   dir too.
5. **≥3 completed-and-harvested since the last compaction, and a slot free → compact** (Phase E).
6. **Registry, including YOUR OWN** — `pdispatch drift` to reconcile the tables, and
   **`pdispatch lint <your-own-instant>`**. You lint every worker as part of the gate; the instant doing the
   gating is the one nobody else checks. Two coordinators in one effort gated nine workspaces all day and
   each found a format violation in their own the first time they looked. Make it a step, not a virtue.
   Then **`pdispatch sessions --reap`** — the backstop for anything step 3 missed. It enumerates live
   claude SESSIONS and asks the board who claims them, so it also surfaces strays no record mentions
   (one such session sat idle for eight days, invisible to every records-first check). It never reaps a
   session the board cannot account for.
7. If nothing above is actionable, say so explicitly — don't manufacture work, and don't go quiet.

**READY** = disposition assigned, ACs written, and its dependencies have **LANDED** (their end-state exists,
gated, recorded in the lineage tracker). Anything else is BLOCKED with the blocker named. A worker sitting
"done" for hours is YOUR failure — not the operator's job to notice.

## The WIP cap — at most ONE in active dev

**Open with at most 1 dispatched instant, and hold at most 1 in ACTIVE DEV thereafter.** Free slots are not
a reason to dispatch: capacity is not the constraint, your attention is. Every extra concurrent worker costs
a gate, a harvest, a parked fork to decide, and a share of an account-wide budget — and the coordinator is
the single writer of the registry they all feed.

**A worker that has finished local validation and is only waiting on GitHub CI does NOT count against the
cap.** It is not consuming dev attention, and CI is slow enough that blocking on it would idle the effort.
So the cap counts RUNNING / IDLE / BLOCKED / PARKED workers, and excludes AWAITING-CI, COMPLETE and HARVESTED.

This only works if the transition is DECLARED, so require it in the brief: when a worker finishes local
validation it writes `Phase: AWAITING-CI` in its HANDOFF. Then `pdispatch health --base <instant> --active-dev`
answers "may I dispatch?" mechanically instead of by eyeball. Override the default with `WIP_CAP=<n>` only
with a reason recorded in DECISIONS.

**Where this number came from — check before you obey it.** This rule has had three different *correct*
values in three contexts, and each revision silently overwrote its predecessor, so the skill kept confidently
telling the next coordinator something that was true for someone else's effort. Judge which row describes
YOU; if none does, the honest move is to derive your own number and add a row, not to inherit one.

| Value | When | Derived from |
|---|---|---|
| "fill every eligible free slot; concurrency caps are a load heuristic" | before 2026-07-28 | an effort where an **idle slot was the failure mode** — throughput was the scarce thing |
| at most **3** in active dev | 2026-07-28 ([`18d10e5`](https://github.com/Davis-Zhang-Onehouse/superpowers/commit/18d10e5)) | operator: capacity is not the constraint, **attention** is |
| at most **1** in active dev | 2026-07-29 | operator directive — the same reasoning taken to its end: one gate, one harvest, one parked fork at a time |

## A compaction instant is EXCLUSIVE — while one is inflight, nothing dispatches

This is a **second, independent rule**, not a tightening of the WIP cap. A compaction folds several finished
branches into one stacked chain, and its end state becomes the base every later instant builds on. Anything
dispatched *alongside* it is based on the pre-compaction tree, so that compaction cannot fold it and it
becomes the **next** compaction's debt. So while a compaction is inflight, **nothing else dispatches at all.**

Keep the two rules apart in your head, because they come apart in practice: a compaction that has declared
`Phase: AWAITING-CI` counts **zero** against the WIP cap — it consumes no dev attention — and still blocks
every dispatch, because its cost is unfoldable rebase debt rather than attention. "The cap says I have room"
is therefore not an answer to "may I dispatch?".

`pdispatch todo` and `pdispatch launch` both **refuse with exit 4** while a sibling `*-inflight-compact-*`
instant exists in the effort's instants directory, and the refusal names it. The rename to
`*-complete-compact-*` is what clears it — the rename IS the state transition. To dispatch anyway:
`--allow-during-compaction "<reason>"` (or `ALLOW_DISPATCH_DURING_COMPACTION="<reason>"`); a reason is
mandatory and belongs in DECISIONS, exactly like a `WIP_CAP` override.

> ⚠️ **KNOWN GAP as of 2026-07-29 — the rule is yours to hold; the tool only helps sometimes.** The guard
> detects a compaction by the instant grammar's `<opType>` field, and **`pdispatch todo` cannot write that
> field** — it hardcodes `-inflight-append-`. So a compaction dispatched the normal way (Phase E,
> `pdispatch todo --profile <a compaction profile>`) is born `…-inflight-append-<name>` and **the guard does
> not see it.** Measured 2026-07-29: every compaction this fleet has ever run is `-append-`; the only two
> `-compact-` opType instants on the box were made by hand with `/maintain-workspace compact`.
>
> **So a green `pdispatch todo` is NOT evidence that no compaction is inflight.** Until this is closed,
> check it yourself — `ls <instants-dir> | grep inflight` and read the names — exactly as you did before the
> guard existed. The guard under-triggers; it never mis-triggers, so a refusal is always real.

## Phase A — Charter & sequence (once)

Bound the target set explicitly; everything else is written OUT and deferred, not scope-crept. Give each item
a disposition (port / rework / sanction) judged against the effort's north-star principle. Record principle +
ACs in CHARTER, at milestone+task+AC level, not execution detail. Three moves that decide the whole effort:

- **Sequence before you fan out, and open small.** Identify the enabling milestone(s) that gate the rest and
  land them SERIALLY first; parallelise only the mutually independent tail — and open with **at most one**
  dispatched instant (see The WIP cap). Batch work sharing an expensive cost (long
  rebuilds, shared caches) into as few instants as possible.
- **Clean baseline.** If you inherit a prior stack that MIXES aligned work with deviations, fork a CLEAN
  baseline and re-land each item per its disposition (read the old stack reference-only) — a clean base is
  what makes goal-alignment auditable.
- **Lift the workaround.** Closing a target INCLUDES auditing for and REMOVING any pre-existing
  coarse/blanket workaround that already makes it "pass" while defeating the goal — even if a test is green
  with it in place.

## Phase B — Dispatch (per milestone)

Script-first: `pdispatch todo --no-launch` → review (below) → **`pdispatch launch <todo-id>`**, which
replays the recorded seed correctly quoted. Never hand-build a launch line.

Author the brief per `brief-contract.md`. Then, **before launching, review the rendered child `CHARTER.md`
and seed — all seven, per worker** (S3's baseline failure is omitting items here):

- [ ] base/branch is the end-state it inherits (lineage), and its dependencies have landed
- [ ] the ACs are the ones you intended
- [ ] dependencies + scope stated; north-star philosophy present
- [ ] no leftover `{{PLACEHOLDER}}`
- [ ] the seed/profile does NOT tell the worker to write the canonical registry (propose-only)
- [ ] report-back path + "then rename your own folder `-inflight-`→`-complete-`" are present
- [ ] the profile is the RIGHT KIND for this work (a fix profile ≠ a compaction profile)

Then launch, and confirm it fired (pane capture shows the intended pipeline starting) — confirming delivery
is necessary but is NOT the content review. Archive a copy of every profile you dispatched with into your
workspace (and re-archive after you edit one) — profiles live outside your workspace and you mutate them
mid-effort; without a snapshot the effort is unreproducible.

**Succession — replacing a worker mid-milestone** (context exhausted, wedged, budget): never kill without a
flush. Require first: HANDOFF "Resume here" + "Next action", the fully-scoped remaining plan in `plans/`, the
decisions/approvals it obtained recorded, a branch/stack table with tips, all WIP committed and tree clean —
then "reply DONE and STOP, do no further work." Seed the successor explicitly as **CONTINUING** that
milestone (predecessor's HANDOFF + plan are the authoritative resume — do NOT restart from scratch); prefer
`pdispatch adopt` of the existing instant over a fresh dispatch. Record the succession in the lineage tracker.

## Phase C — Gate (blocking)

Invoke **`superpowers:review-workspace` yourself** on the worker's instant, `--scope all`. That skill is
advisory *to an operator*; **for this effort you adopt it as a BLOCKING gate — your adoption overrides its
advisory posture.** A green CI is not a passed gate.

The bar: a recorded `REVIEW.md` round with **READY**, or **READY-WITH-FIXES with zero open
Critical/Important**, and every AC VERIFIED on evidence fresh at the delivered tip. **Read this from the
REVIEW file, not from the worker's summary.** If Important findings were fixed, re-run the affected stage and
record a second round before the rename.

## Phase D — Harvest (single-writer)

**A report file is not a completion signal.** Harvest only when BOTH the gate verdict passed AND the worker
has renamed its own folder to `-complete-`. A reported-but-ungated worker stays inflight.

The worker delivers a *proposed* registry delta + evidence; **only you** apply it to the canonical registry,
so the cross-session source of truth never has two writers. Verify from artifacts you checked yourself. Then
free the slot (`pdispatch pool release <slot>`) and dispatch the next READY milestone.

## Phase E — Compact (every 3–5 completed instants)

Dispatch ONE compaction — with its OWN profile (a compaction charter/seed, distinct from the fix profile;
read it pre-flight) and its own slot. It must: fold the inputs into one PR-stack-per-repo (recording every
rebase/restack fix-up); re-prove the merged ACs **together**; run the same CI with zero regression (see
two-diff rule); carry EVERY compacted instant's open issues forward classified (remains-open / addressed /
transformed — nothing dropped); pass the gate; and deliver a **self-contained compaction handoff** (what was
folded in, from which instants, merged AC proof, reconciled evidence index) — the whole point is that the
next instant inherits delivered progress by reading ONE document.

A new instant's **base = the end-state it inherits** (normally the latest gated compaction) — record it in
the lineage tracker. **While a compaction is in flight, you dispatch NOTHING** (see "A compaction instant is
EXCLUSIVE"); `pdispatch todo` and `pdispatch launch` exit 4 when they can see it — which today is only when
the compaction carries the `-compact-` opType, so read that section's KNOWN GAP before relying on it. Never base a dispatch on an
ungated or in-flight compaction. Compact promptly so the pipeline is not stalled for long — but a stalled
pipeline is the cheaper of the two failures.

> **HISTORICAL (superseded 2026-07-29, operator directive):** this paragraph used to read *"while a
> compaction is in flight, new dispatches base on the pre-compaction latest completed end-state and are
> marked `restack-pending`; the next compaction must fold them. Don't stall the pipeline to compact."*
> That is the debt-accepting policy the exclusivity rule replaced: `restack-pending` work is precisely
> what the compaction cannot fold, so it survives as the next compaction's debt.

## Phase F — Stop (defined endgame)

Stop new dispatch → let inflight finish → ONE final comprehensive compaction on the rolling base → gate it →
STOP. Park every operator-only item; do not drift past the endgame.

**Leave no orphans.** At wind-down every open issue must end in exactly one of three states: **fixed**,
**parked for the operator** (named, in the parked block), or **reassigned to a NAMED successor instant**.
"Owned by the coordinator, later" is an orphan — you are the coordinator and you are stopping, so nobody
will ever run it. This is how a validate-suite failure on a secondary CI dimension survived a whole effort
and would have shipped with the merge.

**A carry-over needs an expiry, not a paragraph.** Evidence carried over from an earlier or infra-flaked
run is an ASSUMPTION with a stated re-prove condition — never a proof. A dimension that flaked was not
verified; either re-run it at the tip or record it as an explicit open AC.

## When a standard changes mid-effort

A long effort improves its own rules while running — a review finds a bug class, a tool gains a check, a
brief gains a clause. That is healthy, and it creates **retroactive debt**: work already gated under the
older, weaker standard.

**A new standard never retroactively invalidates a passed gate** — the gate was honestly met at the time,
and re-opening every harvested instant on each tightening would stop the effort. But the debt is real and
must be *dispositioned*, never silently grandfathered. For each item already harvested under the old rule,
pick one and write it down:

- **re-prove** — cheap enough to just do (add the missing test, re-run the one dim), or
- **carry as an explicit open AC** on the next compaction, which is where the union is re-proven anyway, or
- **accept**, with a written justification of why the gap is tolerable for this item specifically.

Record which, with the reason, next to the item in the registry. "It passed the gate we had" is a fact, not
a disposition. The failure mode to avoid is a standard that only ever applies to work done after it, so the
earliest and least-reviewed work permanently carries the weakest guarantees.

## Non-regression & evidence discipline

- **CI truth = the downloaded artifact, not the checkmark.** If jobs run non-failing (e.g. `--fail-never`)
  the summary is always green — trust the test report on the exact pushed SHA. Beware acceptance signals
  masked by an optimization/cache layer — disable the mask when probing.
- **Two diffs, not one** (`pdispatch regress`). Diff each run against (a) the fixed original baseline — catches classic green→red;
  AND (b) the **lineage base** (the end-state this instant inherited) — catches an already-CLOSED item
  re-breaking, which is red→red versus the original baseline and therefore invisible there. Every row your
  registry marks closed must be re-asserted green by name. "Zero green→red vs baseline" is NOT sufficient.
- **Every previously-green test that flips red is a candidate regression.** RCA-classify each: intended
  (now-throws / now-offloads / now-correct / irrelevant-noise) → *sanctioned* with an individually justified,
  GOLD-cited, append-only allowlist entry; otherwise REGRESSION → must fix. Zero unresolved flips to finish.
  Sanctioning is only for a test whose expectation is already correct and whose result is intentionally
  different; if the expectation can be corrected to the new correct behavior, correct it instead. Never mask
  real behavior by scoping the feature off; never blanket-allowlist.
- A flip can also be a **cross-worker artifact** — caused by a sibling in-flight worker's incomplete state
  and resolved only by the final restack. Don't charge it to the worker under review; track it to its owner
  and confirm it closes on the consolidated stack.
- **A pass is not proof that the claimed path ran.** A green test can evaluate on the reference
  implementation via a shared trait, a suite can be skipped and produce no result at all, a dimension can
  flake and be carried over — each yields a real pass behind a false claim. Require a positive artifact that
  the intended engine/path executed; treat a missing result as unproven, never as unbroken.
- Every causal claim ties to a captured artifact under the instant's `evidence/`, never `/tmp`.

## Non-negotiable rules — STOP if you catch yourself here

| Rationalization | Reality |
|---|---|
| "CI is green and the operator wants throughput — mark it complete." | Green CI ≠ reviewed. No complete without a passing `superpowers:review-workspace` round, read from REVIEW.md. |
| "The review skill says it's advisory, so it can't block me." | It is advisory to the OPERATOR. You adopted it as this effort's blocking gate. Advisory ≠ optional for you. |
| "It's all green and merge-ready and they said proceed autonomously — I'll merge the PRs." | **"Proceed autonomously" = keep DEV moving and PARK decisions — NOT authority to merge/publish/delete.** Irreversible + outward = operator-only. STOP and park. |
| "The worker parked a question, so it's blocked on the operator." | Most parked forks are YOURS to decide. Decide the reversible ones and tell it to proceed; escalate only operator-only ones. A worker parked on a question you could have answered is your stall. |
| "The report arrived, so the milestone is done." | Report ≠ done. Gate passed AND folder renamed, or it stays inflight. |
| "I'll let the worker update the shared registry to save a step." | Single-writer only. Worker proposes; you apply. |
| "I'll fire the workers fast and check the charters later." | A mis-seeded worker burns a slot producing confidently-wrong output. All seven checks, per worker, before launch. |
| "I'm heads-down; I'll check the fleet when the operator asks." | Stale status and unharvested work are your failure. Run the tick. |
| "A slot is free, so I should fill it." | Free capacity is not the trigger — the WIP cap is. At 1 in active dev you dispatch nothing, however many slots are idle. |
| "The cap says I have room, so I may dispatch." | The cap is one of two gates. A compaction inflight blocks everything, even at zero active dev. Two rules, not one — and `pdispatch todo` only catches the compactions it can see (KNOWN GAP), so a green dispatch is not an all-clear. |
| "I'll note it as open and owned by the coordinator, and wind down." | You ARE the coordinator. At wind-down that is an orphan nobody will run. Fix it, park it for the operator by name, or hand it to a named successor. |
| "That dimension flaked, but it's behaviourally identical — carry it over." | A flaked run is not evidence. Carry-over is an ASSUMPTION with a re-prove condition, or an open AC. |
| "This is feature dev but there's a do-not-commit reflex." | It's feature dev — cut branches, open PRs freely. Only *merging* is operator-only. |

## Traps and alarm hygiene → `hard-won-lessons.md`

Two reference sections live in `hard-won-lessons.md` in this skill directory, because they are field notes
rather than loop steps: **Gotchas** (shared-pool leases, liveness, message delivery, branch topology, build
caches, shared references, usage limits) and **Alarm hygiene** (the largest observed defect family — the
machinery reporting on the work being wrong rather than the work). Read it before your first dispatch.

Two rules from it are load-bearing enough to state here:
- **Absence is never success.** A missing result, an uncovered dimension, a suite that produced no output, a
  baseline that never covered the row — all mean UNPROVEN, never unbroken.
- **An alarm that cannot be cleared is a defect, not caution.** If doing what it asks leaves it firing, it
  will be ignored, and so will the real one beside it.

## Autonomy posture

Reversible (dispatch, gate, harvest, compact, open PRs, edit your workspace, decide a worker's fork) → just
do it; never block on go/no-go. Irreversible or outward-facing (merge to shared branches, publish, delete,
anything affecting another effort's state) → STOP and park, even under "proceed autonomously."

Answering a blocked worker's permission modal is in scope **only** when the pending action is reversible and
you can verify its blast radius locally (check whether the worker's work is committed/pushed first).
Anything irreversible or statically unresolvable → deny it and park.

**Propagation — where a new rule goes, the same tick it arrives:** an operator RULE or new shared resource →
(a) your registry, (b) the dispatch profile so future workers inherit it, (c) every currently-running worker
(notify + confirm they ingrained it). A coordination MISS or infra TRAP you hit → a fourth destination:
**durable cross-effort memory** — your workspace dies with the effort; the trap will recur in the next one.
