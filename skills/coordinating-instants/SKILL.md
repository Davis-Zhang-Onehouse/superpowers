---
name: coordinating-instants
description: Use when a Claude session is appointed the standing coordinator / orchestrator of a multi-milestone effort executed by parallel dispatched worker instants — it owns a central task/status registry, dispatches one worker per milestone, and must keep the effort moving and correct while the operator is away. Triggers include "you are the coordinator/orchestrator instant", "central task/milestone registry", "dispatch one instant per milestone", "harvest deliverables into the catalog", "poll the workers and coordinate", "proceed autonomously, I'll be unavailable for N hours".
---

# Coordinating Instants

## Overview

A **coordinator** (orchestrator) is a long-lived Claude session that owns the *central task/milestone
registry* for an effort and drives it through **parallel worker instants** — one dispatched session per
milestone. It is built ON TOP of four sub-skills, one per verb, and its whole job is to run the loop
between them correctly and unattended.

**Core principle: the coordinator does NO dev. It is the single source of truth and the fleet's engine —
it verifies everything from artifacts, gates every worker, keeps every ready slot full, and never takes an
irreversible operator-only action on its own.** Violating the letter of these rules violates the spirit.

**REQUIRED SUB-SKILLS** (this skill orchestrates them; it does not restate them):
- superpowers:maintain-workspace — the instant model + the coordinator's own registry; the `compact` and stop(rename) ops.
- superpowers:dispatchInstants — the dispatch mechanism (`pdispatch` pool/todo/board) + fleet monitoring.
- superpowers:reviewing-workspace — the completion gate (`workspace review --all`).
- superpowers:rendering-task-board — turning the registry into a shareable status board / close-out deliverable.
Chartering uses superpowers:brainstorming → superpowers:writing-plans; workers are seeded RCA-first
(superpowers:systematic-debugging → superpowers:test-driven-development).

## When to use

- You've been told you ARE the coordinator/orchestrator instant, or to prepare one and run it.
- An effort has ≥2 milestones you'll farm out to separate worker sessions and must track centrally.
- NOT for doing the dev yourself, NOT for a single one-shot task, NOT for lightweight in-session
  investigation fan-out (that's superpowers:dispatching-parallel-agents).

## The loop

Run this cycle every tick; never wait to be nudged.

1. **Charter** — bound the target set explicitly (everything else is written OUT and deferred, not scope-crept);
   give each item a disposition judged against the effort's north-star principle; record the principle + ACs in
   CHARTER. Break down to milestone+task+AC level, not execution detail. (brainstorming → writing-plans)
2. **Dispatch — script-only, and review-it-yourself FIRST.** Never hand-launch tmux/claude. Run
   `pdispatch todo --no-launch`, then READ the rendered child `CHARTER.md` **and** the seed message: confirm the
   right base/branch (lineage — see step 6), the intended ACs, dependencies, scope, and philosophy — no leftover
   `{{PLACEHOLDER}}`. Only then launch, and verify it fired (pane capture shows the right pipeline starting).
3. **Monitor — never let status go stale.** Put a monitor on every dispatch; poll the board/pool (~10 min while
   active). Use robust liveness (see Gotchas). On each tick: reap dead slots, and **fill every free slot with the
   next ready milestone** (concurrency caps are a load heuristic, not a reason to leave work idle). A worker sitting
   "done" for hours, or an idle ready slot, means you failed — not the operator's job to notice.
4. **Gate — the hard rule.** NO worker instant is marked complete (folder renamed / harvested) until it has run
   `workspace review --all` and reached READY or READY-WITH-FIXES with findings addressed. A green CI is not a
   passed gate.
5. **Harvest — single-writer.** The worker delivers a *proposed* catalog delta + CI evidence; **only you** apply it
   to the canonical registry, so the cross-session source of truth never has two writers. Verify from artifacts, not
   self-reports (see Non-regression). Then free the slot and dispatch the next milestone.
6. **Compact + track lineage.** Every 3–5 completed instants, dispatch ONE compaction: fold them into one
   PR-stack-per-repo, re-prove the merged ACs *together*, same CI with zero regression vs the canonical registry,
   ISSUES due-diligence, review gate. A new instant's **base = the end-state it inherits** (normally the latest
   compaction) — record the lineage. Don't stall the pipeline to compact; keep dispatching.
7. **Stop — defined endgame.** Stop new dispatch → let inflight finish → one final comprehensive compaction on the
   rolling base → gate it green → STOP. Park all operator-only items; do not drift past the endgame.

## Non-regression & evidence discipline

- **CI truth = the downloaded artifact, not the checkmark.** If jobs run non-failing (e.g. `--fail-never`) the
  summary is always green — trust the surefire/test report on the exact pushed SHA. Beware acceptance signals masked
  by an optimization/cache layer (e.g. AQE hiding real offload) — disable the mask when probing.
- **Every previously-green test that flips red is a candidate regression.** RCA-classify each: intended
  (now-throws / now-offloads / now-correct / irrelevant-noise) → *sanctioned* with a GOLD-cited, individually
  justified, append-only allowlist entry; otherwise REGRESSION → must fix. Zero unresolved flips to finish.
  Prefer fixing the test's expectation to correct behavior over sanctioning; **never mask real behavior by scoping
  the feature off**, and never blanket-allowlist.
- Every causal claim ties to a captured artifact under the instant's `evidence/`, never `/tmp`.

## Non-negotiable rules — STOP if you catch yourself here

| Rationalization | Reality |
|---|---|
| "CI is green and the operator wants throughput — mark it complete." | Green CI ≠ reviewed. No complete without `workspace review --all` passing. The joint gate catches cross-fix bugs no single check sees. |
| "It's all green and merge-ready and they said proceed autonomously — I'll merge the PRs." | **"Proceed autonomously" = keep DEV moving and PARK decisions — NOT authority to merge/publish/delete.** Merging to a shared branch is irreversible and operator-only. STOP and park it. |
| "I'll let the worker update the shared catalog to save a step." | Single-writer only. Two writers corrupt the cross-session source of truth. Worker proposes; you apply. |
| "I'll fire the workers fast and check the charters later." | A mis-seeded worker burns a slot producing confidently-wrong output. Review charter + seed BEFORE each launch. |
| "I'm heads-down; I'll check the fleet when the operator asks." | Stale status and idle slots are your failure. Monitor + fill every tick. |
| "The operator told me that rule in chat; I'll remember it." | If it isn't written into the workspace it dies at the next compaction/handoff. Ingrain every durable rule via maintain-workspace, continuously. |
| "This is feature dev but there's a do-not-commit reflex." | It's feature dev — cut branches, open PRs freely. Don't block on a commit gate. Only *merging* is operator-only. |

## Gotchas to watch (from real coordination runs)

| Trap | Guard |
|---|---|
| Background-shell liveness check gives false "worker gone" | Use `pgrep -f "<session>"` + bash arrays + a startup grace window; not `tmux has-session`/unquoted `$vars`. |
| Monitor catches crash/done but not **alive-but-blocked** (permission modal) or idle | Pane-grep for modal signatures + a heartbeat for any instant running > a couple hours. |
| `send-keys` doesn't reliably submit to a busy worker | Verify delivery by pane capture; re-send. A dispatch you didn't confirm landed is not running. |
| Seeds break on shell metacharacters (`| ; & < > ( )`) | Keep seeds short and metachar-free; the CHARTER is authoritative, not the seed. |
| Parallel builds poison a shared cache (`~/.m2`) / skew source-vs-binary provenance | Give each worker an isolated local repo; the final restack must carry all kernels together. |
| Shared reference checkouts | READ-ONLY; any write needs an isolated git worktree (superpowers:using-git-worktrees). |
| Budget/usage limits are account-wide across all your sessions | Economize polling; wind down aggressively near limits. |

## Autonomy posture

Park a `## Parked decision` block ONLY for genuine operator-only forks; never block on go/no-go for reversible
actions — proceed. Reversible (dispatch, gate, harvest, compact, open PRs, edit the workspace) → just do it.
Irreversible / outward-facing / operator-only (merge to shared branches, publish, delete, anything you didn't
create) → STOP and park, even under "proceed autonomously."

## Common mistakes

- Treating the coordinator as a doer — it dispatches and verifies; it does not implement.
- Marking done on the worker's word instead of artifacts you checked yourself + the review gate.
- Letting the registry rot: durable rules the operator gives in chat must be written into the workspace the same tick.
- Compacting too late (stack drift) or stalling dispatch to compact — keep the pipeline full.
