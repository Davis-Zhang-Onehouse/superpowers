# Reviewing-Workspace Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `superpowers:reviewing-workspace` — a fresh-eyes reviewer for a maintain-workspace effort instant, run as a sequential gated pipeline (format → alignment → PR code review), advisory, with an auditable `REVIEW.md` ledger.

**Architecture:** A skill + `/review-workspace` command. The main session orchestrates and is the only file-writer; each pipeline stage dispatches a read-only reviewer subagent (fresh context). Stage 1 auto-fixes mechanical workspace-format violations and flags judgment ones; stage 2 verifies the charter's setup→deliverable→evidence→goal chain per acceptance criterion; stage 3 reuses `requesting-code-review/code-reviewer.md` on delta PR diffs. Findings accrete into an append-only `REVIEW.md` register, a new canonical maintain-workspace file.

**Tech Stack:** Markdown skill files (SKILL.md + supporting prompt/template files), a command markdown file, graphviz-in-markdown flowcharts (per writing-skills conventions). Zero code dependencies (superpowers is zero-dep).

## Global Constraints

- Superpowers is **zero-dependency**; add no third-party deps.
- The reviewer's format checklist is **derived from** maintain-workspace's invariants — do NOT create a second, independently-worded copy of the invariants that can drift.
- All edits to `maintain-workspace` are **additive**; do not reword tuned behavior-shaping prose (Red Flags, philosophy, Common Mistakes wording beyond adding rows).
- Descriptions follow SDO: `description` = triggering conditions only, third person, no workflow summary.
- Cross-reference skills by name with requirement markers (`superpowers:requesting-code-review`); never `@`-link.
- Advisory only: the skill never blocks a completion and never renames an instant.
- Evidence/validation artifacts go under the scratchpad, never `/tmp`; never mutate the real operations workspace.

## File structure

- `skills/reviewing-workspace/SKILL.md` — the skill: overview, when-to-use, the pipeline, REVIEW.md discipline, common mistakes.
- `skills/reviewing-workspace/reviewers/format-reviewer.md` — stage-1 dispatch prompt (invariant/hygiene audit; returns mechanical|judgment findings).
- `skills/reviewing-workspace/reviewers/alignment-reviewer.md` — stage-2 dispatch prompt (charter chain verification; per-AC verdicts).
- `skills/reviewing-workspace/reviewers/README.md` — points stage 3 at `requesting-code-review/code-reviewer.md` and documents delta/SHA selection.
- `skills/reviewing-workspace/templates/REVIEW.md` — the ledger template.
- `commands/review-workspace.md` — the `/review-workspace` command.
- `skills/maintain-workspace/SKILL.md` — additive edits (layout row, pointer section, advisory-gate line, common-mistakes rows).
- `skills/maintain-workspace/templates.md` — add the REVIEW.md template.

---

### Task 1: `REVIEW.md` template + maintain-workspace layout/template wiring

**Files:**
- Create: `skills/reviewing-workspace/templates/REVIEW.md`
- Modify: `skills/maintain-workspace/templates.md` (append REVIEW.md template section)
- Modify: `skills/maintain-workspace/SKILL.md` (Canonical Layout: add REVIEW.md row)

**Interfaces:**
- Produces: the `REVIEW.md` on-disk contract that every stage writes into — round header, finding block fields (`RV-<n>`, Stage, Severity, Status, Location, Finding, Why, Action taken, Verified-by), round summary + overall verdict. Later tasks reference these exact field names.

- [ ] **Step 1: Write `skills/reviewing-workspace/templates/REVIEW.md`** with this exact content:

```markdown
# <Effort> — REVIEW   (append-only review ledger; never rewrite, supersede in place)
Updated: <date> by session <uuid>  |  Status: LIVING register

Records every review round for this instant: findings, their status, and the action taken —
the audit trail from "comment raised" to "comment addressed". Newest round on top.

## Round R<n> — <date> · trigger: <on-demand | pre-complete> · scope: <all | format | alignment | code>
Note: <why this round ran, from --note>
Git snapshot (from HANDOFF PR-stack table):
| Repo | Branch | Tip sha at review |
|------|--------|-------------------|
| <repo> | <branch> | <sha> |

### Stage 1 — Format & hygiene   (verdict: PASS | FIXED | ISSUES)

#### RV-<n> — <short title>
- Stage: format | Severity: Critical | Important | Minor | Auto-fix
- Status: OPEN | ADDRESSED | SANCTIONED | WONTFIX
- Location: <file:line | PR #N>
- Finding: <what is wrong>
- Why it matters: <the invariant/consequence>
- Action taken (<date>): <auto-fix applied / flagged for operator / sanctioned because …>
- Verified-by: <artifact path or command>

### Stage 2 — Goal alignment   (verdict: ALIGNED | GAPS)

Chain: setup-to-begin → deliverables → evidence → acceptance → goal. Per acceptance criterion:

#### AC-<id> — <name> : VERIFIED | INSUFFICIENT | MISALIGNED
- Evidence: <evidence/INDEX row + artifact, or "MISSING: <what is needed>">
- Note: <how it chains, or the misalignment vs a charter constraint/philosophy>
- (record any raised gap as an RV-<n> finding below with Stage: alignment)

### Stage 3 — Code review   (verdict: CLEAN | ISSUES | N/A)

Reviewed (delta since last round):
| PR | Base sha | Head sha (this round) | Prev-reviewed head | Verdict |
|----|----------|-----------------------|--------------------|---------|
| <#N link> | <sha> | <sha> | <sha or "first review"> | Yes/No/With-fixes |

Skipped (inherited from base instant, reviewed upstream): <PR list or "none">

#### RV-<n> — <short title>
- Stage: code | Severity: Critical | Important | Minor
- Status: OPEN | ADDRESSED | SANCTIONED | WONTFIX
- Location: <file:line in PR #N>
- Finding / Why it matters / Action taken (<date>) / Verified-by: <…>

## Round summary — overall verdict: READY | READY-WITH-FIXES | NOT-READY
- Stage verdicts: format=<…> · alignment=<…> · code=<…>
- Open findings: Critical <n> · Important <n> · Minor <n>
- Recommendation: <e.g. "resolve RV-3 (AC-4 evidence) before mv …-complete-…">
```

- [ ] **Step 2: Add the `REVIEW.md` row to maintain-workspace Canonical Layout.** In `skills/maintain-workspace/SKILL.md`, in the Canonical Layout code block, add after the `COMPACTED.md` line:

```
  REVIEW.md       ← append-only review ledger (superpowers:reviewing-workspace). One block per finding (RV-<n>): Stage/Severity/Status/Location/Finding/Why/Action-taken/Verified-by; one round per review; round summary + overall verdict READY|READY-WITH-FIXES|NOT-READY. Written by the reviewer, not hand-maintained.
```

- [ ] **Step 3: Append the REVIEW.md template to `skills/maintain-workspace/templates.md`** — a new `## REVIEW.md` section at the end whose body is: a one-line pointer ("Written by superpowers:reviewing-workspace; see `skills/reviewing-workspace/templates/REVIEW.md` for the full template") plus a note that it is append-only and bootstrapped on first review. Do not duplicate the full template body (one home).

- [ ] **Step 4: Verify the template is self-consistent.** Run:

```bash
grep -c "RV-<n>" skills/reviewing-workspace/templates/REVIEW.md
grep -nE "READY|READY-WITH-FIXES|NOT-READY" skills/reviewing-workspace/templates/REVIEW.md
```
Expected: `RV-<n>` appears in all three stages (≥3); the three verdict tokens present in the summary line.

- [ ] **Step 5: Commit**

```bash
git add skills/reviewing-workspace/templates/REVIEW.md skills/maintain-workspace/templates.md skills/maintain-workspace/SKILL.md
git commit -m "feat(reviewing-workspace): REVIEW.md ledger template + maintain-workspace layout wiring"
```

---

### Task 2: Stage-1 format reviewer dispatch prompt

**Files:**
- Create: `skills/reviewing-workspace/reviewers/format-reviewer.md`

**Interfaces:**
- Consumes: an instant folder path + the maintain-workspace invariants (referenced, not copied).
- Produces: a returned findings list where each finding is tagged `class: mechanical | judgment`, with `location` (file:line), `invariant` (which rule), `finding`, `why`, and for mechanical ones a concrete `fix` the orchestrator can apply. The SKILL.md orchestration (Task 5) consumes this shape.

- [ ] **Step 1: Write the prompt file.** It must contain, in a fenced dispatch block:
  - Role: "workspace format & hygiene auditor", read-only.
  - Input placeholders: `[INSTANT_PATH]`, `[MAINTAIN_WORKSPACE_INVARIANTS]` (the orchestrator pastes the Four Invariants + register rules + Common Mistakes + Canonical Layout text so the checklist has ONE source).
  - A checklist mapping each maintain-workspace rule to a check, e.g.: HANDOFF.md exists with both parts; PR-stack table present + every PR cell a full-URL link + every CI cell a checks-page link (no bare `#N`/run-id); no forbidden extra top-level doc (`STATE.md`/`CAPABILITIES.md`/`MODES.md`/`STATUS.md`/`BUILD.md`) — must be folded; DECISIONS is one-section-per-decision (not a table/rows); ISSUES is one-subsection-per-issue (not a table); no volatile state in CHARTER/DECISIONS/ISSUES; evidence in `evidence/` not `/tmp`, `evidence/INDEX.md` present with criterion→artifact→source→regenerate rows; every doc has an `Updated:/Status:` header; instant not still `…-inflight-…` if acceptance is met.
  - Classification rule: **mechanical** = deterministically fixable without judgment (fold a misnamed doc, rewrite bare id→URL, add a missing header/INDEX row, quarantine a run-id); **judgment** = needs a human/goal decision (missing evidence, contradictory decisions, an approach question).
  - Output format: a list; each item `class · severity(Critical|Important|Minor|Auto-fix) · location · invariant · finding · why · fix(if mechanical)`.
  - Read-only rule: do not mutate files; only report (the orchestrator applies fixes).

- [ ] **Step 2: Verify checklist covers the invariants.** Run:

```bash
grep -niE "STATE.md|bare|/tmp|INDEX|one section per|inflight" skills/reviewing-workspace/reviewers/format-reviewer.md
```
Expected: matches for the stray-doc, bare-id, /tmp, INDEX, decisions-register, and inflight checks (≥5 lines).

- [ ] **Step 3: Commit**

```bash
git add skills/reviewing-workspace/reviewers/format-reviewer.md
git commit -m "feat(reviewing-workspace): stage-1 format & hygiene reviewer prompt"
```

---

### Task 3: Stage-2 alignment reviewer dispatch prompt

**Files:**
- Create: `skills/reviewing-workspace/reviewers/alignment-reviewer.md`

**Interfaces:**
- Consumes: the normalized instant (CHARTER + HANDOFF + evidence/INDEX + DECISIONS/ISSUES).
- Produces: per acceptance criterion, exactly one verdict `VERIFIED | INSUFFICIENT | MISALIGNED` with a cited artifact or a named missing artifact, plus a chain narrative and an overall `ALIGNED | GAPS`. SKILL.md (Task 5) records this into REVIEW.md stage-2 + RV findings.

- [ ] **Step 1: Write the prompt file** with a fenced dispatch block:
  - Role: "charter alignment & evidence-chain verifier", read-only.
  - Input placeholders: `[INSTANT_PATH]`.
  - Method (the chain): (1) read CHARTER goal, setup-to-begin, acceptance (NL→proof→self-review), setup-to-end, standing constraints & design philosophy; (2) for EACH acceptance criterion, locate its proof in `evidence/INDEX.md`/`evidence/`, and decide `VERIFIED` (artifact present, sufficient, re-derivable), `INSUFFICIENT` (missing/weak — name exactly what evidence must be supplemented), or `MISALIGNED` (approach violates a stated constraint/philosophy — cite which); (3) verify the deliverables in setup-to-end are all present and chain from setup-to-begin to the goal; (4) OPTIONAL cheap spot-check: if RUNBOOK gives a one-command re-derivation, note whether it plausibly re-derives the claim (do not run heavy builds).
  - Explicit anti-rubber-stamp: a criterion whose only proof is prose assertion ("looks done") is `INSUFFICIENT`, not `VERIFIED`.
  - Output: per-AC verdict block + chain narrative + overall verdict + a list of raised gaps (each mappable to an RV finding).
  - Read-only rule.

- [ ] **Step 2: Verify the three verdicts and the anti-rubber-stamp rule are present.** Run:

```bash
grep -nE "VERIFIED|INSUFFICIENT|MISALIGNED|looks done|assertion" skills/reviewing-workspace/reviewers/alignment-reviewer.md
```
Expected: all three verdict tokens + the anti-assertion rule.

- [ ] **Step 3: Commit**

```bash
git add skills/reviewing-workspace/reviewers/alignment-reviewer.md
git commit -m "feat(reviewing-workspace): stage-2 goal-alignment / evidence-chain reviewer prompt"
```

---

### Task 4: Stage-3 code-review reuse README (delta + SHA selection)

**Files:**
- Create: `skills/reviewing-workspace/reviewers/README.md`

**Interfaces:**
- Produces: the documented procedure for how the orchestrator (Task 5) selects delta PRs and dispatches the reused code-reviewer.

- [ ] **Step 1: Write the README** documenting:
  - Stage 3 REUSES `superpowers:requesting-code-review`'s `code-reviewer.md` verbatim — do not fork it.
  - PR selection: read the HANDOFF PR-stack table; in-scope = PRs whose branch was authored on THIS instant (per the table's Contents/Branch columns and the instant's session log); inherited base-instant PRs are skipped and listed under "Skipped" in REVIEW.md.
  - Incremental: read the prior round's `Head sha (this round)` per PR from REVIEW.md; the new BASE for the reviewer = that prev-reviewed head (so only new commits are reviewed); first review uses the PR's merge-base as BASE. HEAD = current tip.
  - Placeholder mapping into code-reviewer.md: `[DESCRIPTION]` ← HANDOFF "where we are" + the PR's Contents cell; `[PLAN_OR_REQUIREMENTS]` ← CHARTER acceptance criteria; `[BASE_SHA]`/`[HEAD_SHA]` ← computed above.
  - Read-only on the checkout (code-reviewer.md already enforces this).

- [ ] **Step 2: Verify reuse + delta documented.** Run:

```bash
grep -nE "code-reviewer.md|delta|prev-reviewed|merge-base|Skipped" skills/reviewing-workspace/reviewers/README.md
```
Expected: reuse reference + delta/merge-base + skipped-inherited all present.

- [ ] **Step 3: Commit**

```bash
git add skills/reviewing-workspace/reviewers/README.md
git commit -m "feat(reviewing-workspace): stage-3 code-review reuse + delta-PR selection doc"
```

---

### Task 5: `SKILL.md` — the orchestrating skill

**Files:**
- Create: `skills/reviewing-workspace/SKILL.md`

**Interfaces:**
- Consumes: the three reviewer prompts (Tasks 2-4) and the REVIEW.md template (Task 1).
- Produces: the end-to-end pipeline an agent follows when `/review-workspace` runs.

- [ ] **Step 1: Write frontmatter.** `name: reviewing-workspace`; `description` third-person, triggers-only, no workflow summary — e.g.:

```yaml
---
name: reviewing-workspace
description: Use when an effort-workspace instant (superpowers:maintain-workspace) is about to be marked complete, or mid-effort to catch deviation early — reviews a workspace for format/invariant violations, whether the evidence chain actually satisfies the charter, and code review of newly-delivered PRs. Triggers on "review my workspace", "is this workspace ready to complete", "check the instant before I mark it done", "audit the effort workspace".
---
```

- [ ] **Step 2: Write the body sections** (keep < 500 words of prose beyond tables/blocks; use one flowchart only for the gated pipeline):
  - **Overview** — core principle: a fresh-eyes reviewer for a workspace instant, three lenses cheapest-first, advisory, findings into REVIEW.md.
  - **When to Use** — bullets with symptoms (about to `mv …-inflight-… …-complete-…`; mid-effort deviation check; "is this ready"). When NOT to use (single-session task with no instant).
  - **The pipeline** — a small dot flowchart (Stage 0→1→2→3→4, gated) + a per-stage list. Each stage: what it dispatches, what it returns, what the orchestrator does. Reference the reviewer prompt files by relative path and requirement markers; reference `superpowers:requesting-code-review` for stage 3.
  - **REVIEW.md discipline** — append-only; RV IDs; supersede-in-place with dated note; re-seen finding references prior RV id; overall verdict definitions (READY / READY-WITH-FIXES / NOT-READY).
  - **Advisory, never blocking** — the skill recommends; the operator decides; completing with OPEN Critical must be recorded as an override in REVIEW.md; the skill never renames the instant.
  - **Quick Reference** table (stage → lens → dispatch → output → orchestrator action).
  - **Common Mistakes** table (e.g. restating invariants instead of pasting maintain-workspace's; auto-fixing a judgment call; blocking completion; reviewing full stack every round; findings left in transcript not REVIEW.md).

- [ ] **Step 3: Verify structure.** Run:

```bash
grep -nE "^description:" skills/reviewing-workspace/SKILL.md   # triggers only, no "then"/"->" workflow summary
grep -c "Stage" skills/reviewing-workspace/SKILL.md            # pipeline present
python3 - <<'PY'
import re,sys
t=open('skills/reviewing-workspace/SKILL.md').read()
fm=re.search(r'^---\n(.*?)\n---',t,re.S).group(1)
assert len(fm)<=1024, f"frontmatter {len(fm)}>1024"
print("frontmatter chars:",len(fm))
PY
```
Expected: description is triggers-only; ≥4 "Stage" mentions; frontmatter ≤1024 chars.

- [ ] **Step 4: Commit**

```bash
git add skills/reviewing-workspace/SKILL.md
git commit -m "feat(reviewing-workspace): orchestrating SKILL.md (gated 3-stage review pipeline)"
```

---

### Task 6: `/review-workspace` command

**Files:**
- Create: `commands/review-workspace.md`

**Interfaces:**
- Consumes: the skill (Task 5). Mirrors `commands/maintain-workspace.md` conventions.

- [ ] **Step 1: Write the command file** with frontmatter (`description`, `argument-hint: --base <base-folder-path> [--instant <instant>] [--scope all|format|alignment|code] [--note "..."]`) and a body that: invokes `superpowers:reviewing-workspace`; parses `$ARGUMENTS`; enforces `--base` mandatory (stop + elicit if missing, never default to cwd); resolves `--instant` (default latest `…-inflight-…`); runs the scoped stages; opens/closes a REVIEW.md round. Mirror the structure/tone of `commands/maintain-workspace.md`.

- [ ] **Step 2: Verify.** Run:

```bash
grep -nE "reviewing-workspace|--base|--instant|--scope|elicit" commands/review-workspace.md
```
Expected: skill invocation + all three flags + the mandatory-base elicitation.

- [ ] **Step 3: Commit**

```bash
git add commands/review-workspace.md
git commit -m "feat(reviewing-workspace): /review-workspace command"
```

---

### Task 7: maintain-workspace advisory-gate + pointer + common-mistakes edits

**Files:**
- Modify: `skills/maintain-workspace/SKILL.md`

**Interfaces:**
- Consumes: the completed skill (for the pointer target).

- [ ] **Step 1: Add a short "Workspace Review" pointer section** (after "The Reviewer Contract"), one paragraph: a companion skill `superpowers:reviewing-workspace` (command `/review-workspace`) reviews an instant across format/alignment/code and records findings in `REVIEW.md`; run it mid-effort or before completing. Do NOT restate the pipeline (SDO trap).

- [ ] **Step 2: Add the advisory-gate line** to the "Transition state by renaming the instant" bullet under Maintenance Discipline: before `mv …-inflight-… …-complete-…`, you SHOULD run `/review-workspace`; completing with OPEN Critical findings is allowed but record it as an explicit override in `REVIEW.md`.

- [ ] **Step 3: Add two Common Mistakes rows:**

```
| Instant marked `…-complete-…` with no review round | Run superpowers:reviewing-workspace (advisory) before the rename; record the round in REVIEW.md. |
| Review findings tracked in the transcript, not REVIEW.md | Findings + status + action-taken live in REVIEW.md (append-only), so the audit trail survives the session. |
```

- [ ] **Step 4: Verify no tuned prose was reworded.** Run:

```bash
cd /home/ubuntu/davis_root/superpowers && git diff skills/maintain-workspace/SKILL.md | grep -E "^-" | grep -vE "^--- " | head
```
Expected: only additive `+` lines of substance; no removed behavior-shaping lines (a removed line here is a red flag to inspect).

- [ ] **Step 5: Commit**

```bash
git add skills/maintain-workspace/SKILL.md
git commit -m "feat(maintain-workspace): advisory workspace-review gate + reviewing-workspace pointer"
```

---

### Task 8: Acceptance validation against the example fixture (GREEN gate)

**Files:**
- Create: `<scratchpad>/review-fixture/` (a COPY of the example instant — never touch the real one)
- Create: validation notes under scratchpad

**Interfaces:**
- Consumes: the whole skill. This is the technique-skill application test.

- [ ] **Step 1: Copy the example instant into scratchpad.**

```bash
SP=/tmp/claude-1000/-home-ubuntu-davis-root-superpowers/2b77e082-c35f-4a53-bee5-04f990745eb4/scratchpad
SRC=/home/ubuntu/davis_root/operations/tasks/quantonOnSpark4/07182132-07182241-inflight-append-m11AnsiFullExposureCompleteness
mkdir -p "$SP/review-fixture" && cp -a "$SRC/." "$SP/review-fixture/"
ls "$SP/review-fixture"
```
Expected: the copy contains `STATE.md` (the planted format violation) and CHARTER with AC-4.

- [ ] **Step 2: Run the pipeline against the fixture** by following SKILL.md (dispatch the stage-1 and stage-2 reviewers against the fixture copy; stage 3 = N/A, no PRs authored here / verify-only branch). Let stage 1 auto-fix `STATE.md` (fold into HANDOFF) and stage 2 evaluate AC-1..AC-4.

- [ ] **Step 3: Verify the two planted findings landed.** Confirm in the fixture's generated `REVIEW.md`:
  - Stage 1 has an RV finding for `STATE.md` (forbidden extra top-level doc), Status `ADDRESSED (auto-fix)`, and `STATE.md` is gone / folded into HANDOFF in the fixture copy.
  - Stage 2 marks `AC-4` `INSUFFICIENT` (parked GitHub-CI + catalog), and the round summary overall verdict is `NOT-READY`.

```bash
SP=/tmp/claude-1000/-home-ubuntu-davis-root-superpowers/2b77e082-c35f-4a53-bee5-04f990745eb4/scratchpad
grep -nE "STATE.md|AC-4|INSUFFICIENT|NOT-READY|ADDRESSED" "$SP/review-fixture/REVIEW.md"
ls "$SP/review-fixture/STATE.md" 2>&1 | head -1   # expect: No such file (folded)
```
Expected: STATE.md finding + AC-4 INSUFFICIENT + NOT-READY present; STATE.md no longer exists in the copy.

- [ ] **Step 4: Copy the generated REVIEW.md into the repo as validation evidence** and record the run:

```bash
mkdir -p /home/ubuntu/davis_root/superpowers/docs/superpowers/specs/evidence
cp "$SP/review-fixture/REVIEW.md" /home/ubuntu/davis_root/superpowers/docs/superpowers/specs/evidence/2026-07-19-reviewing-workspace-fixture-REVIEW.md
```

- [ ] **Step 5: Commit**

```bash
cd /home/ubuntu/davis_root/superpowers
git add docs/superpowers/specs/evidence/2026-07-19-reviewing-workspace-fixture-REVIEW.md
git commit -m "test(reviewing-workspace): acceptance run against example instant fixture (STATE.md folded, AC-4 INSUFFICIENT -> NOT-READY)"
```

---

## Self-Review

**Spec coverage:** command (T6) · triggers/advisory-gate (T5,T7) · stage 1 format+autofix (T2,T5) · stage 2 chain (T3,T5) · stage 3 delta code review (T4,T5) · REVIEW.md register (T1) · maintain-workspace additive edits (T1,T7) · acceptance fixture (T8). All spec deliverables mapped.

**Placeholder scan:** template + reviewer content contracts are concrete; the only `<…>` are template placeholders (intended). No TBD/TODO.

**Type consistency:** finding fields (`RV-<n>`, Stage, Severity, Status, Location, Finding, Why, Action taken, Verified-by) and verdict tokens (`VERIFIED|INSUFFICIENT|MISALIGNED`, `READY|READY-WITH-FIXES|NOT-READY`, `mechanical|judgment`) are used identically across T1–T5, T8.
