# Compacting Effort Instants — the full recipe

`compact` folds instants into one deliverable instant. See `SKILL.md` § Compaction
for the short contract; this file is the full procedure + the required `COMPACTED.md`
template. Invoked by `/maintain-workspace compact --base <dir> --instants <a,b,c>`.

**Compaction stacks existing work — it is NOT new feature development.** You
fork the inputs' PRs into a single reviewable chain and *re-prove them together*;
you do not build new behavior. That framing decides every judgment call below —
above all, how a lingering issue is reconciled (§4).

**The compact instant is born `inflight`, not `complete`.** Like every instant, it
starts life as `main-<now>-inflight-compact-<name>/` and is renamed to
`…-complete-compact-<name>/` only once the four-part contract holds — every merged
AC (§2) proven on the stacked chain. Creating it `…-complete-…` before the proofs
exist is the same lie as leaving finished work labeled `inflight`. (Preparing the
fold without running the restack/builds/CI yet? It stays `inflight-compact`.)

**Inputs should be `complete`; an `inflight` input is allowed but you inherit its
debt.** Warn on any input that isn't `…-complete-…`. You MAY still fold it — but
its unmet acceptance criteria merge in as **open** ACs (§2), and the compact cannot
go `complete` until they are proven on the stack. Folding an inflight input never
lets its unmet promise silently disappear; it just moves the obligation onto the fold.

## The four-part contract (all four are mandatory)

### 1. One stacked PR chain (per repo)

For inputs whose PRs live in the **same repo**, fork and restack them on top of
each other into a **single chain** — `base → feature1 → feature2 → …` — so the
compact is one reviewable stack, not N parallel branches off a shared base.

- Pick the restack base (usually `main`, or the shared base instant's tip).
- Rebase each input's branch onto the previous link, in a deliberate order;
  resolve conflicts as fix-up commits, and **note each fix-up** (it is a real
  change the inputs never saw together).
- The compacted `STATE.md` PR-stack table reflects the **chain** — each row's
  branch tips onto the row above it. Record every PR as a full-URL link.
- Different repos → one chain per repo; say how the chains relate in STATE.
- **Inputs need not share a `base_instant`.** What §1 requires is a common
  **restack base branch** for the chain, not a common lineage in the folder names.
  Inputs forked from different parents whose fix branches already sit on the same
  branch → that branch is your restack base. If they sit on genuinely different
  bases, pick one, restack the rest onto it, and record the choice in `DECISIONS.md`.

### 2. Every merged acceptance criterion is MET

The compact owns the **union** of the inputs' acceptance criteria. Each must be
**proven on the compacted stack**, not merely copied into a checklist:

- A merged AC with no passing proof against the *stacked chain* **blocks the
  compact** — do not mark it done because the input once proved it in isolation.
- If the partner deliberately narrows or supersedes a criterion, record which
  and why in `DECISIONS.md`. Never silently drop a promise an input made.

### 3. Evidence: regenerated, or carried-over-with-justification

For each merged criterion, its evidence lands in `evidence/INDEX.md` one of two ways:

- **REGENERATED** — re-run the proof against the compacted stack and capture a
  fresh artifact (invariant 4: provenance + how-to-regenerate). This is the
  default; the stacked chain is new code that never ran together before.
- **CARRIED OVER** — reuse the input's original artifact **only with an explicit
  written justification** that the artifact still holds *on the compacted stack*.
  Record it in the `COMPACTED.md` evidence-disposition table AND the INDEX row.
  The justification must fit one of these shapes:
  - **Byte-identical PR** — the restack left the input's PR unchanged (same commits,
    no rebase fix-up), so its original CI run exercises identical code.
  - **Static, code-independent artifact** — an RCA / source-citation / analysis doc
    that reads gold-vs-actual source and doesn't depend on a runtime run; carry it,
    but re-verify any line-number references after the rebase.

  **What CANNOT be carried over — must REGENERATE:** any *runtime* proof (CI run,
  E2E/golden run, unit-green log) when the restack changed what runs. Two common
  triggers: (a) the branch took a rebase fix-up; (b) a **cross-repo / native rebuild
  makes the build cache-MISS**, so even an untouched branch now runs against changed
  dependency code (e.g. one input forces a Velox rebuild that the whole gluten chain
  then builds on). Byte-identical reasoning is void in both cases — regenerate.

Silent reuse of stale evidence — carrying an input's log over with no note on why
it still holds on the stacked chain — is not allowed.

### 4. Every lingering issue / follow-up is reconciled

Inputs are marked `complete`, but "complete" can mean *complete with concerns*:
open items live in each input's `ISSUES.md` (status `OPEN`/`DEFERRED`/`DOCUMENTED`)
and in the "Blockers"/"Live snapshot"/follow-up notes of its `HANDOFF.md`.

Enumerate **all** of them across every input, then reconcile each against the new
stack into **exactly one** bucket — nothing dropped silently:

| Bucket | Means | Typical cause |
|--------|-------|---------------|
| **remains-open** | still open on the compacted stack | we only stacked PRs — no new dev, so an input's open issue stays open (carry it into the compact's `ISSUES.md` with its history) |
| **addressed** | closed on the compacted stack | another input's PR fixes it, OR it was trivial and handled inline during the restack (link the fixing PR / the fix-up commit) |
| **transformed** | partly addressed / changed shape | stacking resolved part of it, or it became a *different* follow-up — record what remains as a new issue and link back to the original |

The reconciliation table is a required `COMPACTED.md` section. Any issue that ends
up `remains-open` or `transformed` must also exist as a live sub-section in the
compact's own `ISSUES.md` (append-only, with its origin noted) so a resumer sees it.

## Consolidation (the rest of the fold)

- **RUNBOOK.md is self-contained.** The compact's RUNBOOK holds **one** build +
  **one** validation run that re-derives ALL evidence for the merged criteria —
  a few commands + grep, at most. A reviewer never needs an input's RUNBOOK.
- **STATE.md** carries the single reviewer guide (how each artifact was built &
  tested) for the stacked chain, and the chain's PR table.
- **evidence/INDEX.md** has a row per merged criterion → artifact → source →
  regenerate, tagged REGENERATED or CARRIED-OVER(+why) per §3.
- **Consumed instants stay on disk untouched** as history.

## `COMPACTED.md` template (compact instants ONLY)

Copy this when bootstrapping the compact instant. It makes the fold auditable:
what was folded, the one chain, every promise now owned + how it is proven, and
every inherited concern's disposition.

```markdown
# <name> — COMPACTED   (fold record for main-<curr_instant>-<state>-compact-<name>; born inflight)
Updated: <date>

## Included instants (folded into this one; originals kept on disk)
- 07181613-07191011-complete-append-addfeature1
- 07181613-07191013-complete-append-addfeature2
- 07181613-07191016-complete-append-addfeature3

## Stacked PR chain (§1 — inputs restacked into ONE chain per repo)
Restack base: <main@<sha> | shared-base tip>
| Order | Repo | Branch | Tips onto | PR (full URL) | Rebase fix-ups |
|-------|------|--------|-----------|---------------|----------------|
| 1 | <repo> | <feature1-branch> | <restack base> | [#<n>](…) | <none / what changed> |
| 2 | <repo> | <feature2-branch> | <feature1-branch> | [#<n>](…) | <none / what changed> |
| 3 | <repo> | <feature3-branch> | <feature2-branch> | [#<n>](…) | <none / what changed> |
Full PR/branch/CI table → STATE.md.

## Merged acceptance criteria (§2 — union of inputs'; ALL must be MET on the stack)
Each is proven against the COMPACTED stack, not the input in isolation.
- [ ] AC-1 <from addfeature1> — proof on stack → evidence/INDEX #<n>
- [ ] AC-2 <from addfeature2> — proof on stack → evidence/INDEX #<n>
- [ ] AC-3 <from addfeature3> — proof on stack → evidence/INDEX #<n>
(Narrowed/superseded any? Record which + why in DECISIONS.md — never drop silently.)

## Evidence disposition (§3 — regenerated, or carried over WITH justification)
| Criterion | Artifact | Disposition | Justification (required if CARRIED-OVER) |
|-----------|----------|-------------|------------------------------------------|
| AC-1 | `<file>` | REGENERATED | re-ran on stacked chain — see INDEX #<n> |
| AC-2 | `<file>` | CARRIED-OVER | restack left PR byte-identical (same commits, no fix-up) → original run exercises identical code |

## Lingering-issue reconciliation (§4 — every open concern from inputs' ISSUES/HANDOFF)
Enumerate ALL open/deferred items from each input; resolve each to exactly one bucket.
| Origin (input · issue/blocker) | Reconciliation | Note |
|--------------------------------|----------------|------|
| addfeature1 · OI-11 <title> | remains-open | only stacked PRs, no new dev → carried to this instant's ISSUES.md as OI-1 |
| addfeature2 · OI-7 <title>  | addressed | fixed by addfeature3's [#<n>](…) once stacked | 
| addfeature2 · HANDOFF blocker <x> | transformed | stacking fixed the crash; remaining perf gap → new OI-2, links back |
(remains-open / transformed items MUST also appear as live sub-sections in ISSUES.md.)

## Compacted "Setup to end up with"
- Consolidated deliverables: <the single stacked PR chain, images, jars — links;
  superseding the per-feature handoffs>
- Single reproducible stack: <one build + one validation run (see RUNBOOK.md) that
  re-derives ALL evidence for the merged criteria — a few cmds + grep, at most>
- Evidence: every merged criterion has an evidence/INDEX.md row (regenerated or
  carried-over-with-justification per the disposition table above).
```
