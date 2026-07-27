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

## Cold start (first 5 minutes — do this on every fresh/compacted session)

You are long-lived and WILL restart mid-effort. Never answer "status?" from memory.

1. `cd` to your coordinator instant; read HANDOFF.md Part A (the four tables) → CHARTER → DECISIONS → ISSUES.
2. `pdispatch board` and `pdispatch pool list` — the live truth about the fleet, across ALL efforts.
3. Reconcile the fleet table against reality: which slots are yours, which are another effort's, which are
   FREE/STALE. Fix the table; it rots the moment you look away.
4. Prove liveness of each of YOUR workers (see Gotchas) — leased ≠ alive.
5. Find work already owed to you: any worker done-but-ungated, gated-but-unharvested, or parked.
6. Then enter the tick loop. Only now are you entitled to report status.

## Every tick (~10 min while work is live)

1. **Liveness** — check each of your workers; a lease is not a heartbeat. Spot-check any instant running
   >~2h every ~30 min (alive-but-blocked and idle both look "running").
2. **Parked forks** — read every live worker's HANDOFF `## Parked decision`. Decide the ones that are yours
   (see Autonomy); escalate only genuine operator-only forks.
3. **Done → gate** (Phase C). **Gated → harvest** (Phase D), then free the slot.
4. **Eligible free slot → dispatch** the next READY milestone (Phase B).
5. **≥3 completed-and-harvested since the last compaction, and a slot free → compact** (Phase E).
6. **Registry** — reconcile the tables; write down anything durable that arrived this tick.
7. If nothing above is actionable, say so explicitly — don't manufacture work, and don't go quiet.

**READY** = disposition assigned, ACs written, and its dependencies have **LANDED** (their end-state exists,
gated, recorded in the lineage tracker). Anything else is BLOCKED with the blocker named. An idle eligible
slot or a worker sitting "done" for hours is YOUR failure — not the operator's job to notice.

## Phase A — Charter & sequence (once)

Bound the target set explicitly; everything else is written OUT and deferred, not scope-crept. Give each item
a disposition (port / rework / sanction) judged against the effort's north-star principle. Record principle +
ACs in CHARTER, at milestone+task+AC level, not execution detail. Three moves that decide the whole effort:

- **Sequence before you fan out.** Identify the enabling milestone(s) that gate the rest and land them
  SERIALLY first; parallelise only the mutually independent tail. Batch work sharing an expensive cost (long
  rebuilds, shared caches) into as few instants as possible.
- **Clean baseline.** If you inherit a prior stack that MIXES aligned work with deviations, fork a CLEAN
  baseline and re-land each item per its disposition (read the old stack reference-only) — a clean base is
  what makes goal-alignment auditable.
- **Lift the workaround.** Closing a target INCLUDES auditing for and REMOVING any pre-existing
  coarse/blanket workaround that already makes it "pass" while defeating the goal — even if a test is green
  with it in place.

## Phase B — Dispatch (per milestone)

Script-first: `pdispatch todo --no-launch`, then launch by running **the exact command the `--no-launch`
output printed** (it escapes correctly). Never hand-BUILD a launch line or seed; if you must compose a seed,
put it in a shell variable free of `| ; & < > ( )`.

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
the lineage tracker. **While a compaction is in flight**, new dispatches base on the pre-compaction latest
completed end-state and are marked `restack-pending`; the next compaction must fold them. Never base a
dispatch on an ungated or in-flight compaction. Don't stall the pipeline to compact.

## Phase F — Stop (defined endgame)

Stop new dispatch → let inflight finish → ONE final comprehensive compaction on the rolling base → gate it →
STOP. Park every operator-only item; do not drift past the endgame.

## Non-regression & evidence discipline

- **CI truth = the downloaded artifact, not the checkmark.** If jobs run non-failing (e.g. `--fail-never`)
  the summary is always green — trust the test report on the exact pushed SHA. Beware acceptance signals
  masked by an optimization/cache layer — disable the mask when probing.
- **Two diffs, not one.** Diff each run against (a) the fixed original baseline — catches classic green→red;
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
| "I'm heads-down; I'll check the fleet when the operator asks." | Stale status and idle eligible slots are your failure. Run the tick. |
| "This is feature dev but there's a do-not-commit reflex." | It's feature dev — cut branches, open PRs freely. Only *merging* is operator-only. |

## Gotchas to watch (from real coordination runs)

| Trap | Guard |
|---|---|
| The slot pool + board are **global**, shared with other efforts | Confirm ownership before you touch a slot: `pdispatch pool status <slot>` + `pdispatch board`. **Never run bare `pdispatch pool reap`** — it frees EVERY stale lease machine-wide, including other efforts'. Release only your own: `pdispatch pool release <slot>`. Dispatch with `--slot <ws>` you verified — an unslotted claim auto-reaps stale slots it finds. `pdispatch pool remove <your-own-slot>` so your coordinator workspace can never be claimed. |
| Background-shell liveness gives false "worker gone" | `pgrep -f "<session>"` + bash arrays + a startup grace window; not `tmux has-session`/unquoted `$vars`. |
| Monitors catch crash/done but not **alive-but-blocked** (permission modal) or idle | Pane-grep for modal signatures + the >2h/30-min spot-check. On a block, see Autonomy posture. |
| `send-keys` doesn't reliably submit to a busy worker | Verify delivery by pane capture; re-send. A message you didn't confirm landed was not delivered. |
| Two workers pushing ONE shared branch collide (non-fast-forward) | Each worker gets its OWN branch + draft PR off the common base; defer linear stacking to the compaction restack. |
| Parallel builds poison a shared cache / skew source-vs-binary provenance | Give each worker an isolated local build repo; the final restack must carry all pieces together. |
| Shared reference checkouts | READ-ONLY; any write needs an isolated worktree (superpowers:using-git-worktrees). |
| Usage/budget limits are account-wide across all your sessions | Stop new dispatch; send each inflight worker a **convergence nudge** (stop refinement cycles, finalize on current green evidence); make the final compaction lean by reusing the last one; economize polling; ensure every completed instant is independently pushed + green so a post-reset resumer can finish. **A budget plan never lowers the evidence bar** — a failed or stale run is not evidence; re-spend and record the overrun, and record any carried-over evidence as an explicit ASSUMPTION with a flagged optional re-run. |

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
