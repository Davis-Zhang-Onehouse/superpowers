# Design: `superpowers:reviewing-workspace`

Date: 2026-07-19
Status: Approved (brainstorming), pending implementation

## Problem

`maintain-workspace` gives a long-running effort a durable, resumable folder (an *instant*)
with fixed canonical files and hard invariants. But nothing **checks** an instant before it
is marked `complete`. Today a maintainer eyeballs it, and drift slips through:

- The example instant `07182132-07182241-…m11AnsiFullExposureCompleteness` ships a stray
  `STATE.md` — explicitly forbidden by invariant 3 and the Common Mistakes table (state must
  fold into `HANDOFF.md`). Nothing caught it.
- Its `AC-4` (GitHub CI + catalog update) is parked/incomplete, yet the instant sits one
  `mv` away from being renamed `…-complete-…`. Nothing verifies the acceptance chain before
  that transition.

`requesting-code-review` guards a code change with a fresh-eyes reviewer subagent. There is
no equivalent guard for a *workspace*. This skill is that guard.

## Goal

A companion skill `superpowers:reviewing-workspace` (+ `/review-workspace` command) that reviews
an effort-workspace instant across three lenses, records findings in an auditable ledger, and
can run mid-flight (catch deviation early) or as an advisory pre-complete gate.

## Scope

- **IN:** review pipeline for a single instant; a new canonical `REVIEW.md` ledger; the
  `/review-workspace` command; small additive edits to `maintain-workspace` (layout row,
  pointer section, advisory-gate line, template, common-mistakes rows).
- **OUT:** blocking/hard gates (advisory only); rewriting maintain-workspace's tuned
  behavior-shaping prose; a second source of truth for the invariants (the reviewer derives
  its checklist FROM maintain-workspace, it does not restate it); reviewing more than one
  instant per run; auto-completing/renaming the instant (reviewer recommends, operator decides).

## Design decisions (from brainstorming)

1. **New standalone skill, advisory.** Not an extension of maintain-workspace; completion is
   never blocked — findings are recorded and a verdict is recommended.
2. **Sequential gated pipeline, cheapest/most-foundational lens first:**
   Stage 1 Format & hygiene → Stage 2 Goal alignment → Stage 3 PR code review. Each stage
   gates the next; you cannot trust content review on a malformed workspace, and PR review is
   premature until the goal/deliverable is understood.
3. **Orchestrator + fresh-context read-only reviewer subagents.** The main session orchestrates
   and is the only writer; each stage dispatches a subagent with no session history (fresh
   eyes, the whole point of code review). Workspace *docs* are mutable by the orchestrator
   (stage-1 mechanical fixes); the *code checkout* is read-only in stage 3.
4. **Stage 1 auto-fixes mechanical violations, flags judgment ones.** Fold a stray `STATE.md`,
   rewrite a bare `#123` → full URL, add a missing `evidence/INDEX.md` row, etc., recorded as
   `ADDRESSED (auto-fix)`. Missing evidence / contradictory decisions → `OPEN`, untouched.
5. **One append-only `REVIEW.md` register** — a new canonical maintain-workspace file, same
   append/supersede discipline as DECISIONS/ISSUES.
6. **Stage 3 is delta + incremental.** Review only PRs authored on this instant (per the
   HANDOFF PR-stack table), diffed base→head; inherited base-instant PRs skipped + noted;
   `REVIEW.md` records the last-reviewed head SHA per PR so a re-run only reviews new commits.
   Reuses `requesting-code-review/code-reviewer.md` verbatim per PR.
7. **Stage 2 is analytic-primary.** It builds the setup→deliverable→evidence→goal chain from
   the charter and evidence index; it MAY spot-check *cheap one-command* RUNBOOK re-derivations
   read-only, and recommends (never forces) heavier regeneration.

## Architecture

### Command

`/review-workspace --base <base-folder> [--instant <instant-folder>] [--scope all|format|alignment|code] [--note "<why this round>"]`

- `--base` mandatory; never default to cwd; elicit in chat if missing (same rule as maintain-workspace).
- `--instant` optional → defaults to the latest `…-inflight-…` under `--base`.
- `--scope` optional → defaults to `all`; lets a single stage run on demand.
- `--note` optional → free text recorded as the round's trigger/reason.

The command loads the skill and runs the matching flow.

### Triggers

1. **On-demand** — run anytime mid-flight to catch deviation early.
2. **Pre-complete (advisory gate)** — maintain-workspace's "transition by renaming
   `inflight→complete`" step gains a companion line: before the `mv`, you SHOULD run
   `/review-workspace`. Completing with OPEN Critical findings is allowed but MUST be recorded
   in `REVIEW.md` as an explicit operator override. Never blocks.

### Pipeline

**Stage 0 — Setup (orchestrator).** Identify the instant from `--base`/`--instant`. Read
`HANDOFF.md` + `CHARTER.md`. Ensure `REVIEW.md` exists (bootstrap from template if not). Open a
new round: id `R<n>`, date, trigger (`on-demand`/`pre-complete`), scope, and a git-SHA snapshot
of each repo in the PR-stack table.

**Stage 1 — Format & hygiene.** Dispatch a read-only reviewer with a checklist *derived from*
maintain-workspace's Four Invariants + the three register/reconciliation rules + the Common
Mistakes table + the Canonical Layout. It returns findings tagged `mechanical | judgment` with
`file:line`. The orchestrator:
- **auto-fixes mechanical** violations in place → records each as `ADDRESSED (auto-fix)` with a
  before/after note. Examples: stray `STATE.md`/`CAPABILITIES.md`/`MODES.md` folded into their
  canonical home; bare `#123`/`run 4711` → full-URL markdown link; missing PR-stack table slot
  added; missing `evidence/INDEX.md` row added; volatile state quarantined out of a durable doc;
  missing/`Updated:` doc headers.
- **flags judgment** items (missing evidence, contradictory decisions, an instant still named
  `…-inflight-…` after acceptance is met) → `OPEN`.
- Gate: stage 2 runs on the now-normalized workspace.

**Stage 2 — Goal alignment / chain verification.** Dispatch a read-only reviewer that digests
the charter (goal · setup-to-begin · acceptance NL→proof→self-review · setup-to-end ·
constraints & design philosophy) and **builds the chain**:
`setup-to-begin → each deliverable → its backing evidence (evidence/INDEX.md) → does that prove
the acceptance criterion → do the deliverables chain up to setup-to-end and satisfy the goal?`
Per acceptance criterion it returns exactly one verdict:
- `VERIFIED` — evidence present, sufficient, and re-derivable (cite the artifact).
- `INSUFFICIENT` — evidence missing or weak; names exactly what must be supplemented.
- `MISALIGNED` — the approach violates a charter constraint/design philosophy (e.g. a bandaid
  where the charter demanded a long-term fix, or a fallback that violates a stated north-star).
It may spot-check a cheap one-command RUNBOOK re-derivation read-only. Findings → `REVIEW.md`.
Gate: alignment recorded; proceed to stage 3. A Critical misalignment may recommend deferring
stage 3 as premature — reviewer advises, operator decides.

**Stage 3 — PR code review (delta, incremental).** Orchestrator reads the HANDOFF PR-stack
table, selects PRs authored on this instant (inherited base PRs skipped + noted), computes
`base→head`, and reads the last-reviewed head SHA per PR from `REVIEW.md` so only commits added
since the previous round are reviewed. For each in-scope PR it dispatches
`requesting-code-review/code-reviewer.md` **verbatim** (DESCRIPTION ← HANDOFF; PLAN_OR_REQUIREMENTS
← CHARTER acceptance; BASE/HEAD SHAs). Read-only on the checkout. Merges each reviewer's
Strengths/Issues/Assessment into `REVIEW.md`; updates last-reviewed SHA per PR.

**Stage 4 — Close (orchestrator).** Write a round summary to `REVIEW.md`: per-stage verdict,
finding counts by severity/status, and one overall verdict:
- `READY` — no OPEN Critical/Important; every AC `VERIFIED`; chain intact.
- `READY-WITH-FIXES` — only Minor/Important open; enumerated.
- `NOT-READY` — an OPEN Critical, a broken chain, or an `INSUFFICIENT`/`MISALIGNED` AC.
Append a HANDOFF session-log row pointing at the round. Do NOT rename the instant (advisory).

### `REVIEW.md` (new canonical file, append-only register)

```
Updated: <date> by <uuid> | Status: LIVING register

## Round R<n> — <date> · trigger: <on-demand|pre-complete> · scope: <all|…>
Git snapshot: <repo→branch→sha per PR-stack row>

### Stage 1 — Format & hygiene   (verdict: PASS|FIXED|ISSUES)
### RV-<n> — <title>
- Stage: format | Severity: Critical|Important|Minor|Auto-fix | Status: OPEN|ADDRESSED|SANCTIONED|WONTFIX
- Location: <file:line | PR #N>
- Finding: … | Why it matters: … | Action taken (<date>): … | Verified-by: <artifact/cmd>

### Stage 2 — Goal alignment   (per-AC: VERIFIED / INSUFFICIENT / MISALIGNED)
### Stage 3 — Code review   (per-PR, from code-reviewer.md; last-reviewed SHA recorded)

## Round summary — overall verdict: READY | READY-WITH-FIXES | NOT-READY
```

Findings get stable IDs (`RV-1…`). A re-run **updates Status in place with a dated note**
(supersede, never rewrite); a finding re-seen in a later round references its prior `RV-id`, so
the audit trail shows the whole arc — this is how "comment addressed" is tracked. `REVIEW.md` is
a LIVING register: the round headers and finding history accrete; nothing is deleted.

### Edits to `maintain-workspace` (all additive)

- **Canonical Layout:** add the `REVIEW.md` row.
- **New short "Workspace Review" section:** one paragraph pointing to `reviewing-workspace`, no
  restatement of the pipeline (avoids the SDO trap of a workflow summary agents follow instead
  of the skill).
- **State-transition discipline:** add the advisory-gate line on the `inflight→complete` rename.
- **`templates.md`:** add the `REVIEW.md` template.
- **Common Mistakes:** 1–2 rows (e.g. "completed an instant without a review round";
  "review findings tracked in transcript, not `REVIEW.md`").

## Data flow

```
/review-workspace --base … [--instant …] [--scope …]
      │
      ▼
Stage 0  identify instant · read HANDOFF+CHARTER · open REVIEW.md round (git snapshot)
      │
      ▼
Stage 1  [dispatch: format reviewer] → findings(mechanical|judgment)
         orchestrator auto-fixes mechanical (→ ADDRESSED), flags judgment (→ OPEN)
      │  (gate: workspace normalized)
      ▼
Stage 2  [dispatch: alignment reviewer] → per-AC {VERIFIED|INSUFFICIENT|MISALIGNED} + chain
      │  (gate: alignment recorded)
      ▼
Stage 3  orchestrator computes delta PRs + last-reviewed SHA
         for each PR [dispatch: code-reviewer.md] → Strengths/Issues/Assessment
      │
      ▼
Stage 4  round summary + overall verdict · append HANDOFF session-log row (no rename)
```

## Error handling / edge cases

- **No `--base`** → stop, elicit in chat (never default to cwd).
- **No inflight instant** → report and ask which instant to review.
- **No `HANDOFF.md`/`CHARTER.md`** → stage-1 Critical (`OPEN`); the workspace is not a valid
  instant; pipeline still records the finding and stops before stages 2–3.
- **No PRs authored on this instant** → stage 3 records "no deliverable PRs; code review N/A" and
  the verdict rests on stages 1–2.
- **Fresh instant, first review** → last-reviewed SHA absent → review full base→head for each PR.
- **`--scope` single stage** → run only that stage; still open/close a round in `REVIEW.md`.

## Testing (technique skill → application scenario)

The example instant is a purpose-built fixture with two planted failures:
- **Stage 1** must flag+fold the stray `STATE.md` (invariant 3 / Common Mistakes).
- **Stage 2** must return `INSUFFICIENT` for `AC-4` (parked GitHub-CI + catalog), yielding an
  overall `NOT-READY`.

GREEN gate: run the pipeline against a **scratchpad copy** of the example instant (never mutate
the real operations workspace) and confirm both findings land in `REVIEW.md` with the correct
overall verdict.

## Deliverables

- `skills/reviewing-workspace/SKILL.md`
- `skills/reviewing-workspace/reviewers/format-reviewer.md`
- `skills/reviewing-workspace/reviewers/alignment-reviewer.md`
- `skills/reviewing-workspace/reviewers/README.md` (points at code-reviewer.md reuse for stage 3)
- `skills/reviewing-workspace/templates/REVIEW.md`
- `commands/review-workspace.md`
- edits to `skills/maintain-workspace/SKILL.md` + `skills/maintain-workspace/templates.md`
- validation evidence: a `REVIEW.md` produced against the scratchpad fixture
