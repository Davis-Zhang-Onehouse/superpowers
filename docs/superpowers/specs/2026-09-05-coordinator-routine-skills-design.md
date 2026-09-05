# Coordinator routine skills — design

**Date:** 2026-09-05
**Status:** design approved in brainstorm; implementation plan not yet written
**Source effort:** `operations/tasks/quantonOnSpark4V2/instants/00000000-07310348-inflight-append-v2stackcoordinator`

## Why

One coordinator instant has run a multi-milestone, multi-repo PR-stack effort for five weeks: 205
milestones, 60+ dispatched workers, six restack instants, 421 recorded infra findings. The routine it
evolved works, and it exists nowhere except in that folder — as a 30KB `RUNBOOK.md`, a 1.2MB
`DECISIONS.md`, and the shape of the folder itself.

`superpowers:coordinating-instants` already carries the generic loop (Observe → Reconcile → Decide →
Raise → Dispatch → Receive → Escalate → Abandon → Close out). None of the four routines that effort
actually spends its time on are in it:

- dispatching a **wave** of append instants onto one shared base,
- **integrating** the wave's siblings into a linear PR stack,
- **harvesting** a worker, including the half that carries its knowledge up,
- **maintaining** the roadmap so the registry stays true.

Plus the arc above them: a project goal, its milestones, its known and unknown unknowns, and an audit
trail joining dispatches to the milestones they moved.

## What this design is built from

Read in full: `CHARTER.md`, `RUNBOOK.md`, `PRIORITIES.md`, the 205-row `roadmap.json`, the `dispatch/`,
`launchers/`, `audits/` and `tools/` trees, the `x2`–`x6` restack charters, and issues `FI-387`–`FI-421`
plus `I-52`–`I-56`.

**Every mechanical claim below was measured against `fleet 0.3.18`, not inherited from those registers.**
That discipline immediately paid: five candidate infra gaps drawn from the effort's own `ISSUES.md` were
tested, and **two were already fixed** (unknown flags now exit 2, not 0; the proposal `note` now leads the
`pending-proposal` row). Recording those as open would have reproduced `FI-404` — the failure where the
coordinator relayed two false facts to a worker and the worker wrote both into its instant.

Verification also found **three gaps the effort had not recorded** (`SI-45`, `SI-46`, `SI-47`) and
**reproduced one it had only observed** (`SI-48`). All seven live in
[`docs/superpowers/fleet-infra-backlog.md`](../fleet-infra-backlog.md).

## The skill set

| Skill | Routine | New? |
|---|---|---|
| `running-a-stacked-effort` | the project arc; owns the charter, the registries, the cycle, the endgame | new (umbrella) |
| `dispatching-a-wave` | admit *k* workers onto one shared base without racing or colliding | new |
| `integrating-a-pr-stack` | N siblings → one linear chain per repo, PRs reused, pins moved, tip graded | new |
| `harvesting-an-instant` | gate, close, **and carry the knowledge up** | new |
| `maintaining-a-roadmap` | keep the registry true: title width, deps, readiness, retirement, ranking | new |
| `auditing-a-dispatch-history` | forward: make a dispatch auditable. backward: reconstruct contribution | new |
| `coordinating-instants` | the nine-phase loop and the fleet mechanics | **unchanged**, gains a routing pointer |

They are separate skills rather than one document because **each has a different failure mode**, and the
failure mode is what a Red Flags table has to be written against:

| Skill | How it fails |
|---|---|
| `dispatching-a-wave` | races its own charter write; the worker boots on an empty scope |
| `integrating-a-pr-stack` | creates a defect that belonged to no member instant |
| `harvesting-an-instant` | drops the worker's findings on the floor, silently |
| `maintaining-a-roadmap` | drifts a title until it no longer describes what was delivered |
| `auditing-a-dispatch-history` | returns zero and is believed |

## The shared spine

All six touch the same artifacts, so sole-writership is settled once.

| Artifact | Sole writer | Kind |
|---|---|---|
| `.fleet/roadmap.json` | coordinator, via `fleet apply` / `fleet milestone` | **state** |
| **chain manifest** | `integrating-a-pr-stack` writes tips; `dispatching-a-wave` reads | **state** (new, `SI-43`) |
| `CHARTER.md` | coordinator, once; DURABLE | contract |
| `PRIORITIES.md` | coordinator | ranking only — never overrides a derived blocker |
| `DECISIONS.md`, `ISSUES.md` | coordinator; append-only, corrections written **in place** | record |
| `HANDOFF.md` | coordinator | **narrative — explicitly not state** |
| `dispatch/<id>-brief.md`, `launchers/<id>/` | the dispatch routine | audit trail |

The third row is the one change to current practice. Today `HANDOFF.md`'s branch-stack table is *de facto*
state — the coordinator reads the next `--lineage-base` out of it and retypes it — while the same skill
says never to treat a `HANDOFF.md` narrative as state. The chain manifest resolves the contradiction:
**it becomes the only source of a lineage base, and `HANDOFF.md` goes back to being narrative.**

---

## 1. `running-a-stacked-effort` (umbrella)

**Triggers:** "you're the coordinator for X", "let's start this effort", "what's the state of the
project", resuming into an effort root.

**Sections.**

1. **Chartering.** The operator's description becomes a goal plus *"done means all N, and I do not get to
   soften any of them"* — phrasing taken verbatim from the source charter, because the alternative is a
   goal that quietly narrows as it gets hard. Acceptance criteria are written as **NL statement →
   executable proof → running self-review**, the self-review column updated as evidence lands rather than
   composed at the end.
2. **Preserving the operator's framing.** First three raw prompts verbatim. When a line stops being
   operative, strike it **in place, and say why** rather than deleting it — a reader grepping for a rule
   lands on the struck line, so it must carry its own correction. The source charter does exactly this for
   two rules that changed under it (`ws4` routing, `--cap 3`).
3. **The registries** — the spine table above, and "prose is not state".
4. **The unknowns ledger.** `kind=delivery|question|probe` rows in the one registry (`SI-42`). Known
   unknowns are rows; *unknown* unknowns are what `auditing-a-dispatch-history` files as new rows. Rule: a
   `probe` reaching `done` means *we now know*, which is not what a `delivery` reaching `done` means, and
   a dependent row is entitled to know which it got.
5. **The cycle** — rank ready rows → wave → integrate → harvest → re-rank, with load-when-you-get-there
   pointers to the five routine skills.
6. **The endgame** — inherited from `coordinating-instants`, plus: an item outliving the effort needs
   *both* a documented issue and a `fleet milestone`, because the issue holds the why and the milestone
   holds the reachability.
7. **Red flags.**

**Red flags.**

| Thought | Reality |
|---|---|
| "The HANDOFF table says the tip is X" | Narrative is not state. Read the manifest, or `git ls-remote`. `FI-390` |
| "This milestone is basically about Y" | A title one word wider is what dismisses a real finding as already-carried. `FI-420` |
| "The check returned zero, so we're clean" | A check that returns zero is the one to distrust — it may not be able to see. `FI-417` |
| "The worker proposed done, so it's done" | The `note` is the report. The status is the envelope. `FI-409` |
| "I'll draft the next three briefs while CI runs" | A brief written more than one milestone ahead decays faster than it is consumed. |

---

## 2. `dispatching-a-wave`

**Triggers:** "dispatch the next wave", "two rows are ready on the same base", "put k workers on this".

**Routine.** Given ready milestones sharing a base, admit *k* workers without racing, colliding, or
building on the wrong thing.

| Step | Rule | Grounding |
|---|---|---|
| 1 | **Re-derive the ready set and state it out loud.** | `SI-47` — no verb names it; the count is prose. |
| 2 | **Take the base from the chain manifest, then `git ls-remote` it.** Never retype from `HANDOFF.md`. | `SI-43`; `fleet` checks arrival, never correctness. |
| 3 | **Ask the guard for the cap; never compute it.** `--dry-run` prints `guard.wip-cap`, naming who counts and who is excluded. | Measured; see below. |
| 4 | **Declare overlap before dispatching, or sequence.** | `FI-408` — 7 files authored concurrently by 2 live workers. |
| 5 | **dispatch → write scope → *then* release the seed.** The seed is the release signal. | `launcher:128`/`:133`; `FI-387`. |
| 6 | **Verify the launch carried the environment**, not the tmux server's. | `RUNBOOK` §2 step 6. |
| 7 | **One milestone ahead, never two.** | The source effort's own conclusion about itself. |

**Step 3 is where this skill improves on the observed routine rather than transcribing it.** The effort
computes `N = 1 (me) + (admitted workers not awaiting-ci) + 1` and calls that "compute it, never type a
remembered number". But a formula evaluated over a population you are recalling *is* a remembered number,
and it is **wrong for a coordinator created by `init`**: measured, such a coordinator has no record, so
`_workers()` does not count it and `guard.wip-cap` reads `0 of 1`. The guard already knows the answer,
prints it on every `--dry-run`, and names the excluded set. Its own `cost_on_pass` says it is "safe to ask
before every dispatch and safe to ask twice."

**Step 5 is the non-negotiable ordering.** `dispatch` writes the rendered charter (`cli.py:1053`); the
launcher shim then waits up to 180s for a seed and, failing that, starts "an interactive session rather
than a blank prompt". The coordinator fills real scope into the child's `CHARTER.md` inside that window.
Measured in the field: a worker read a charter **growing under it**, 28,609 → 37,401 bytes, and filed a
decision on the premise its scope was empty. Related: `SI-46` — fleet's placeholder detector cannot see
the `<!-- COORDINATOR: … -->` convention the profiles actually use, so nothing catches this today.

**Red flags.**

| Thought | Reality |
|---|---|
| "Cap 3 for three workers" | `--cap` counts records, not intentions, and whether yours is among them depends on how you were created. Read the guard. |
| "I'll fix the charter right after it boots" | The 180s window is the whole race. Scope first, seed last. |
| "These two milestones are unrelated" | `FI-408` was two workers on one file. Declare the surface, do not assume it. |
| "The profile lints clean" | `profiles.lint()` has no CLI caller (`SI-45`) — that claim is not re-derivable by any command you can type. |

---

## 3. `integrating-a-pr-stack`

**Triggers:** "restack the wave", "make these siblings one chain", "linearize the PRs".

**Routine.** N sibling branches → one linear chain per repo, PRs reused, pins moved with each position,
tip graded, manifest updated.

| Step | Rule | Grounding |
|---|---|---|
| 1 | **Snapshot every ref before and after** — including the ones you will not touch. | The snapshot diff is the proof nothing outside the grant moved (`x4` AC-1). |
| 2 | **Force-push authority is an enumerated branch list, never a pattern.** | `x4` grants exactly 8: "NOTHING else … every other ref are untouchable." |
| 3 | **Order is load-bearing for correctness, not only for conflicts.** | `FI-414` — `collectFirst{…}.flatten`: a rule that matches but builds `None` still *consumes* the message. |
| 4 | **Every position's pin must resolve into the *chained* history.** | `x4` AC-3: "a chain position that builds against un-chained velox is the defect this milestone exists to prevent." |
| 5 | **Reuse PRs. Never rename a branch** — renaming breaks reuse. Retarget with `gh pr edit --base`. | `x4` AC-2: zero PRs created or closed. |
| 6 | **Grade the tip; absence is never success.** | `FI-411` — a grader keyed on "did any step fail?" scores a *reclaimed* job clean. `FI-400` — `failed=0` meant the red run was re-queued, not fixed. |
| 7 | **Hunt for failures that belong to no member.** | `FI-410` — three suites each pass alone and fail once the restack puts them in one tree. |
| 8 | **Write the new tip back to the manifest.** | That is the handoff to the next wave. |

**Step 4 is the multi-repo core** and the reason this skill treats pinned lineage as a first-class
concept rather than an extension. A single-repo restack is a rebase; a pinned multi-repo restack is a
rebase plus a simultaneous pin-move at every position, and the pin is the half that fails silently — the
chain still builds, against the wrong native code.

**Step 7 is the skill's distinctive claim.** A restack is normally treated as mechanical work over
already-graded code — `x4`'s own charter says "you write NO new production code and NO new tests" — and
it is nonetheless the operation most able to produce a defect no member instant could have found, because
it is the first time those changes coexist.

**Red flags.**

| Thought | Reality |
|---|---|
| "It's a restack, the work is already graded" | The restack is the first time these changes share a tree. `FI-410` |
| "Nothing failed, so the tip is green" | A job that did not run is not a job that passed. `FI-400`, `FI-411` |
| "I'll rename the branches to something cleaner" | Renaming breaks PR reuse, which is the milestone's own acceptance criterion. |
| "The pins were right before the rebase" | They pointed at un-chained history. Every position's pin moves with it. |

---

## 4. `harvesting-an-instant`

**Triggers:** "the worker's done", "harvest x4", "close it out".

**Routine.** Two halves, and the second is the one that gets skipped.

**Half one — close out.** `apply` (dry-run first) → `fleet review` gate → the worker's own `fleet complete`
(the rename *is* the transition) → three consecutive non-wait `pane-guard` samples plus an attachment
check → `close` → **wait for the cwd-holding pid** → `harvest`. Do not chain `close && harvest`: the
refusal is exit 4, correct, and transient. `harvest` exiting 1 is expected and does not mean failure.

**Half two — carry the knowledge up.** This is where the routine currently loses things:

1. **Read the proposal's `note`, not only its status.** `FI-409`: parsed every tick for weeks, never read
   once; a worker's full RCA sat unread for two hours, and `FI-410`/`FI-411`/`FI-415` all arrived through
   that channel. (The infra half is fixed — the note now leads the row — so what remains is the habit.)
2. **Check the inbox for a regressing proposal before applying.** `SI-48`, reproduced: applying a stale
   proposal moved a `done` milestone back to `awaiting-ci` at rc=0, and a dependent row that had become
   ready went back to blocked. Nothing refuses this.
3. **Carry findings into the coordinator's `ISSUES.md` with a non-colliding id** — derive the next id
   *before* appending your own section (`FI-421`), and check for an existing number (`I-56` was appended
   as a second `I-53`).
4. **Raise a roadmap row for anything that outlives the worker.** Issue plus milestone, both.
5. **Reconcile the completed instants**: *does any open issue in a `-complete-` instant have no owner?*
   `FI-416` found a live silent wrong answer sitting in one, carried by nothing — and `FI-417` found that
   the check which found it was itself under-reporting, because it grepped for a field shape one instant
   did not use. **The check must be able to say "cannot tell", and must never report that as zero.**

**Red flags.**

| Thought | Reality |
|---|---|
| "The proposal says done" | The `note` is the report. Read it before you apply it. `FI-409` |
| "Applying is safe, it's just bookkeeping" | It can un-land a landed milestone and re-block its dependents, silently. `SI-48` |
| "The worker's issues are the worker's" | The worker is about to stop existing. Anything unowned dies with it. `FI-416` |
| "The reconciliation found nothing" | Ask what it examined. A zero from a check that cannot see is not a zero. `FI-417` |
| "`harvest` exited 1, something's wrong" | Expected. Read the `harvested … info` row, not the status. |

---

## 5. `maintaining-a-roadmap`

**Triggers:** "a finding landed", "raise a milestone", "re-rank the priorities", "retire that row".

**Routine.** Keep the registry true — which is mostly about **width** and **reachability**.

1. **Title width is the discipline.** A title must be exactly as wide as what it carries. Both directions
   have failed: `FI-419`, twice, a title narrower than its finding (a row saying `array<bigint>` whose
   finding also covered MAP and ROW); `FI-420`, a `done` row asserting a scope its own worker declared
   undelivered *in writing, in its own HANDOFF*. Too broad is worse, because a broad title is what an
   adjudicator matches on to dismiss a real finding as already-carried.
2. **Readiness is derived. Never store it.** And note that the derived answer is not fully readable
   today — `SI-47`.
3. **`kind` distinguishes a delivery from a question from a probe** (`SI-42`).
4. **Deps are checked when you type them and cannot be added later** (`SI-44`). When a sequencing
   constraint is learned after a row is raised, it has nowhere mechanical to live. The skill documents the
   workaround — PRIORITIES prose, plus the coordinator enforcing it at dispatch — **and names it as a
   workaround**, because the live instance is a constraint whose violation grades *green*: "`v9x` MUST
   land before `v9f`… a `v9f` dispatched first ships map entries that never fire and can grade green."
5. **Retire with a reason that says what the successor must keep.** The source roadmap has 56 dropped
   rows; the good `retired_reason`s name what the superseding row must not lose.
6. **`PRIORITIES.md` ranks the derived-ready population; it never overrides a blocker.**

**Red flags.**

| Thought | Reality |
|---|---|
| "I'll widen the title so it covers both" | That is how a real finding gets dismissed as carried. `FI-420` |
| "I'll add the dep later" | You cannot. `add` refuses an existing id and there is no amend. `SI-44` |
| "PRIORITIES says it's next, so dispatch it" | Ranking never overrides a derived blocker. |
| "It's superseded, just drop it" | A drop without a reason loses what the successor must keep. |

---

## 6. `auditing-a-dispatch-history`

**Triggers:** "what did x4 contribute", "is anything unaccounted for", "show me the dispatch history".

**Routine.** Two directions.

**Forward — make a dispatch auditable as it happens.** Every dispatch leaves, in one place: the brief, the
exact seed sent (`launchers/<id>/seed-to-send.txt`), the lineage base and how it was derived, the cap
derivation, and the milestone claimed. The source effort does this well already; the skill's job is to
state it as an obligation rather than a habit.

**Backward — reconstruct contribution.** milestone → owning instants → their evidence → the PR positions
they moved. Hands the human-facing view to `superpowers:rendering-task-board` rather than duplicating it.

**Two rules the audit machinery itself has to obey**, both learned expensively:

- **A check that returns zero must state what it examined.** `FI-417`. Fleet models this well — every
  checker emits a `population` row precisely so a narrowed scope cannot read as a pass — and the skill
  adopts it as a requirement for any check a coordinator writes.
- **A long-running delegation must produce incremental artifacts.** `FI-418`: a 2-hour reconciliation
  spanning 35 instants and ~150 findings hit a session limit and left **nothing**, because the brief asked
  for one report at the end. The defect was in the brief, not the delegate.

**Red flags.**

| Thought | Reality |
|---|---|
| "The sweep came back clean" | Clean over what population? A check that cannot see reports zero. `FI-417` |
| "The delegate will write it up at the end" | Then a ceiling at 90% leaves you nothing. Incremental artifacts. `FI-418` |
| "The audit agent confirmed it" | Re-derive anything that gates an irreversible act. `FI-404` |

---

## Infra dependencies

Seven, all in [`fleet-infra-backlog.md`](../fleet-infra-backlog.md), all measured at `0.3.18`. The skills
are written to work **without** these — documenting the workaround and naming it as one — so nothing here
blocks authoring.

| id | gap | blocks |
|---|---|---|
| `SI-42` | milestones have no `kind` | the unknowns ledger |
| `SI-43` | no chain manifest; `--lineage-base` correctness unchecked (subsumes `SI-33`) | wave, integrate |
| `SI-44` | a milestone cannot be amended, so late deps live in prose | roadmap |
| `SI-45` | `profiles.lint()` has no CLI caller | wave |
| `SI-46` | the placeholder detector cannot see the convention profiles use | wave |
| `SI-47` | `roadmap` prints every row except the ready ones | wave |
| `SI-48` | `apply` silently regresses a `done` milestone, cascade included | harvest |

`SI-48` is the one worth fixing first regardless of this work: it un-lands landed work at rc=0.

## How these skills get verified

Per `CLAUDE.md`, skill content is behaviour-shaping and changes need evidence, not argument.

1. **`superpowers:writing-skills`** drives authoring and pressure-testing.
2. **Structural checks**, following `coordinating-instants`' own suites: every `fleet` verb a skill names
   is a registered verb; every refusal a skill quotes is one the tool actually produces.
3. **Cite by symbol, never by line number.** The line citations in *this document* were each verified
   on 2026-09-05 and are point-in-time; a **skill** must not carry them. `FI-403` is the reason and it is
   almost funny: a standing rule written to fix a hard-coded-line-number bug prescribed
   `sed -n '93,$p'` to splice a charter, drifted silently, and truncated every brief for days. A skill
   cites `Roadmap.apply`, not `roadmap.py:458`.
4. **The claims ledger.** Every mechanical claim carries the command that produced it. The scratch-store
   transcript behind `SI-47` and `SI-48` is the model: a fresh `FLEET_HOME`/`FLEET_INSTANTS`, three
   milestones, and the exact sequence reproduced.
5. **Explicitly argued, not measured:** that six skills is the right cut rather than four or eight. The
   decomposition follows failure modes, which is a judgement.

## Out of scope

- Fixing any `SI-*`. Tracked, deliberately separate, operator to schedule.
- Changing `coordinating-instants` beyond adding a routing pointer.
- The gluten/velox domain content itself — `SPARK_ANSI_SPEC.md`, the ANSI gaps, the profiles. Those stay
  in the effort; the skills carry the *shape*, with that effort as the worked example.
