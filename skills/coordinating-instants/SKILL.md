---
name: coordinating-instants
description: Use when a Claude session is the standing coordinator of a multi-milestone effort executed by dispatched worker instants, or is resuming that role. Triggers include "you are the coordinator instant", "dispatch one instant per milestone", "what's the fleet status", "resume coordinating", "apply the workers' proposals", "harvest the finished worker".
---

# Coordinating Instants

## Overview

You are the standing coordinator of an effort that other instants execute. You do no development yourself.
Your own `.fleet/roadmap.json` **is** the project-level registry: there is no second board to keep in sync,
and no milestone table in your `HANDOFF.md` that has to agree with it.

Three facts define the role, and each is a mechanism rather than a resolution:

- **You are the roadmap's only writer.** Workers send proposals; `fleet apply` is the only function in the
  package that changes a milestone's status. A worker's `fleet propose` cannot produce a roadmap delta at
  all — it returns a proposal and appends it to your inbox.
  <!-- v2-cite: worker-cannot-move-roadmap H2 -->
  This is structural because it once was not: a dispatch profile instructed *every* worker to update the
  canonical registry and survived an entire effort that way, because nothing could tell a worker's write
  from the coordinator's.
- **Readiness is derived, never stored.** `fleet roadmap` recomputes it from whether each dependency reached
  `done`, and names the blocker for every row that is not ready. Do not maintain a `ready` flag by hand; a
  stored copy of a fact the dependencies already carry drifts the moment a dependency slips.
- **Evidence is mandatory on every proposal.** A proposal without it is a claim, and is refused at the
  producer. So a status that reaches you always arrives attributed and with a path behind it.

The verb surface, exit codes, porcelain schema and store environment are in **superpowers:using-fleet**.
Read it once; this skill does not restate it.

**Announce at start:** "I'm using the coordinating-instants skill to coordinate this effort."

## The loop

Nine phases. Run Observe → Reconcile on every fresh or compacted session before you answer "status?" — you
are long-lived and will restart mid-effort, and memory is not a source.

| Phase | What you type | Why it is not optional |
|---|---|---|
| **Observe** | `fleet board --porcelain`, `fleet leases --porcelain`, `fleet roadmap --instant . --porcelain` | Three different questions: who holds a slot, what slots exist, what work exists. Reading one and inferring the others is how a worker gets dispatched onto an unlanded base. |
| **Reconcile** | `fleet reconcile --porcelain`, `fleet reap --all` | `reap` recovers a slot whose writer died; skipping it leaks capacity silently. A live session the board cannot account for is reported to you, never reaped <!-- v2-cite: unclaimed-session-never-reaped J7 --> — one such stray sat idle for eight days, invisible to every records-first check. |
| **Decide** | *nothing* — read the `ready` rows | Readiness is derived. A row you believe is ready whose dependency has not landed is not ready, and the row says which dependency. |
| **Raise** | `fleet milestone --instant . --id <x> --title "<what it is>" --dep <y>` | The only way work becomes dispatchable. Every `--dep` must already be on the roadmap, and is checked at the moment you type it — a typo'd dependency is not an error later, it is a milestone that reads as permanently in progress. Add dependencies in order. |
| **Dispatch** | `fleet dispatch --profile <dir> --title <t> --base <b> --optype append --from . --milestone <m> --lineage-base "repo=<sha>" --cap <n>` | One command claims the lease, creates the instant, renders the charter and seed, records `origin.json` so the worker's reports reach *your* roadmap, and claims the milestone. State the cap you want; do not police it. A compaction present only as a folder still freezes every dispatch in the effort <!-- v2-cite: folder-compaction-freezes F11 --> and a worker that has declared `awaiting-ci` no longer counts against the cap <!-- v2-cite: declaration-does-free-the-cap F2 --> — both are computed, not remembered. The `--lineage-base` you type is the single authority: it is rendered into the seed and the charter, and a claim of done from a slot that is not there is refused. <!-- v2-cite: done-from-wrong-base-refused LB2 --> |
| **Receive** | `fleet roadmap --instant . --porcelain` shows the pending proposal → `fleet apply --instant . --milestone <m>` | `apply` moves the status, carries the evidence onto the milestone, and consumes the proposal, so replaying your inbox cannot apply the same report twice. Readiness recomputes and the dependent rows open. |
| **Escalate** | `fleet park --instant <w> --question "<the fork>"` / `fleet unpark --instant <w>` | A blocked worker becomes a named question instead of a stalled pane. Most parked forks are yours to answer; escalate only the operator-only ones. |
| **Abandon** | `fleet abort --instant <w> --reason "<why>"` | A reason is mandatory, and the abort releases the milestone's claim so the work is re-dispatchable. |
| **Close out** | `fleet review --instant <w> --scope all --verdict READY` → the worker's own `fleet complete` → `fleet harvest --id <todo>` | `review` gates `complete`, and the **rename is the state transition** — the one signal a worker cannot fake with a document. `harvest` applies the remaining proposals, kills the session, stamps the record and releases the slot as one transaction; a crash part-way through does not leave a free slot holding an in-flight record. <!-- v2-cite: harvest-commits-whole J2 --> It also refuses to close a pane holding unsubmitted input, so teardown never discards a worker's last turn. <!-- v2-cite: close-refuses-queued-pane J8 --> |

Two verbs answer specific questions when the loop is not enough: `fleet status --id <todo>` for one subject in
full, and `fleet compaction-status` for what is holding dispatch.

## Two judgements the tool cannot make

**Act on `attention`, report `info`.** Every checker row carries a severity. A finished milestone and a
legitimately empty population are `info`. Treating them as alarms is how a green board comes to read as red
and then gets ignored — along with the real alarm next to it.

**Read porcelain, never prose.** Every observation verb takes `--porcelain` and emits tab-separated fields
whose schema is declared data. Parse columns. Never grep a sentence, and never take a worker's `HANDOFF.md`
narrative as state: the roadmap is authoritative because its entries arrived as evidence, and prose that
disagrees with it is a document to fix, not a fact.
<!-- v2-cite: prose-is-not-state F3 -->

## The endgame

Stop new dispatch, let the inflight work finish, compact once onto the rolling base, gate that, stop.

**An item that outlives the effort is carried by two acts, both required:** a documented issue in your
workspace, where a resuming session already reads, **and** `fleet milestone` on the roadmap, which makes it
dispatchable. The issue holds the *why*; the milestone holds the *reachability*. Neither alone suffices, and
"open, owned by the coordinator, later" is an orphan — you are the coordinator and you are stopping.

**There is no reassignment, deliberately.** A milestone names no owner it has to invent, so the failure that
motivated the old reassignment machinery — eight items reassigned by name to an instant that existed nowhere
on the box — is unrepresentable rather than merely detected. The carry-across is `fleet milestone` and
nothing else. <!-- v2-cite: carry-across-runs-on-fleet H9 -->

**A carry-over needs an expiry, not a paragraph.** Evidence carried over from an earlier or infra-flaked run
is an assumption with a stated re-prove condition, never a proof. A dimension that flaked was not verified:
re-run it at the tip, or record it as an explicit open acceptance criterion.

## What the coordinator never does

- Write another instant's `roadmap.json`.
- Touch a `dt-` session, pane or folder belonging to another effort.
- Merge, publish or delete outward state. "Proceed autonomously" means keep development moving and park
  decisions; it is not authority over anything irreversible and outward-facing.
- Set a milestone's status without an applied proposal behind it.

## What is measured and what is argued

Be exact about this when you report, because a coordinator's own confidence is the thing nobody else audits.

- **Measured.** The refusals cited above each have an integration case that passed: the single-writer
  invariant, the derived readiness, the compaction freeze over records ∪ disk, the cap-freeing declaration,
  the lineage gate, the unclaimed-session rule, the queued-pane refusal, and the atomicity of close-out.
  `fleet`'s suite stands at 219 PASS / 9 SKIP / 5 NOT-RUN. This skill's own suites check three further
  properties: every verb it names is a registered verb (V1), every refusal it claims cites a case that
  passed (V2), and the loop above executes against a scratch store (V3).
- **Argued, not measured.** Five integration sections are only partially covered (`§F §G §I §J §O`), and
  `§P` — a real dispatch against a real `claude` — has never run. So "these instructions are followable by a
  model" is an argument. V1–V3 prove the commands exist, the refusals are real and the sequence executes;
  they say nothing about whether a worker reading its seed does the right thing.
- **Not checked at all:** whether the `--lineage-base` SHA you typed is the *right* base for the milestone.
  Only that the slot ends up there and every document agrees. The predecessor's tip is recorded in its
  `HANDOFF.md` branch-stack table and retyped into the next dispatch; the design that closes this is worked
  out and deferred as `SI-33`.

## Hard-won rules

Each row cost something. They are here because no mechanism decides them for you.

| Rule | What it cost |
|---|---|
| Absence is never success — a check that finds nothing states what it examined | *"no compaction of this effort is inflight"* was true about the wrong question |
| Never pipe a control | `tail` exits 0 regardless, and a commit landed with a control red |
| A check over a resource the operator also uses must attribute before it accuses | a check charged the operator's own session to a test section |
| The source pin is a shared resource — nothing edits it while anything measures | one edit contaminated a whole section's measuring run |
| A total loss is usually a broken measurement | 48/48 turned out to be the fixture, not the product |
| For each thing your role must do, ask: what do I type? | four capabilities existed, were tested, and could not be invoked |
| Detect and prevent are different asks — if the actor forgets the remedy, what happens? | a check you must remember to run fails the same way as the thing it checks |
| Verify inherited claims; do not adopt them | a "green" claim was false within the hour |
| A refusal must name what clears it and who clears it | otherwise it gets forced blindly |
