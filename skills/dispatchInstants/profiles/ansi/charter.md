# {{TITLE}} — CHARTER   (durable; edit deliberately)
Instant: {{CHILD_NAME}}
Updated: {{TODAY}} | Status: DURABLE
Dispatched by parallelDispatch from base instant: {{BASE_NAME}}

## Goal (e2e)
{{TITLE}}

## Setup to begin with
- Base instant: {{BASE_CURR}}  (forked from {{BASE_NAME}})
- Workspace: {{WS}}  (slot {{SLOT}}, leased; duplicated from golden {{GOLDEN}} — pre-built, no rebuild)

## First raw prompt / brief (the dispatch)
{{BRIEF}}

## Evidence pointers from the base (start your RCA here)
{{EVIDENCE}}
## Acceptance criteria — the NON-NEGOTIABLE pipeline (do the phases IN ORDER)

### AC-1 LOCAL REPRO first (before RCA, before any fix)
- [ ] Reproduce the target ANSI gap's failing gluten Spark UT **locally** in this workspace (the exact
      test/suite that CI runs). Capture the raw failing output into evidence/ (NOT /tmp) + the exact
      command in RUNBOOK.md. A cold reader can re-run it. (If it won't repro locally, that itself is the
      first RCA finding — pursue it; every CI-runnable test MUST be runnable locally doing the same thing.)

### AC-2 RCA via systematic-debugging (RCA-FIRST — before any fix)
- [ ] Run superpowers:systematic-debugging. investigations/<topic>/analysis.md documents the **Spark-Java
      (gold) vs Gluten-Velox (actual)** behavioral diff, with cited real artifacts in evidence/ (NOT /tmp),
      every causal claim tied to a captured artifact (not memory), and a reproducible repro. Deliver the
      RCA artifacts exactly as the skill requires.

### AC-3 FIX + local validation (branch on scope AFTER the RCA)
- [ ] Small/localized/clear → superpowers:test-driven-development (RED = the failing ANSI test → GREEN).
      Large/multi-file/ambiguous → superpowers:brainstorming → writing-plans → subagent-driven-development.
- [ ] Local validation GREEN proven via **surefire** (the fixed gap passes; no regression in the touched suites).
      The fix is **maintainable, extensible, reliable, long-term — NOT an adhoc bandaid.**

### AC-4 GitHub CI + catalog.md + velox counterpart
- [ ] Effective GitHub CI run (Velox Backend ANSI Mode). **Truth = downloaded surefire report** (jobs run
      --fail-never, always green). Diff vs the M1 baseline (ansi-ci-diff-catalog skill): red→green for this
      gap + NO regression. **Ensure gluten checks out the proper velox counterpart in get_velox.sh** (the
      branch/commit matching this fix's velox side). Deliver a **PROPOSED catalog delta** for this gap
      (which tests → closed / open / sanctioned-flip, with the CI evidence) — **never edit the canonical
      CATALOG.md yourself**: the coordinator is its single writer and applies your delta on harvest.

### AC-5 Completion gate + report-back (the coordinator's two signals)
- [ ] **Before renaming this instant**, run `superpowers:review-workspace` (ALL stages) on it and PASS:
      a recorded REVIEW.md round of READY, or READY-WITH-FIXES with **no open Critical/Important**, every
      AC verified on fresh evidence. No passing round = not complete.
- [ ] Write your report to the base instant's `dispatch/<MR>-REPORT.md`: AC results with evidence paths,
      branch tips, the proposed catalog delta, the REVIEW verdict, and any operator forks. **Then**
      transition your folder `-inflight-` → `-complete-`. Those two are how the coordinator detects you.

## Setup to end up with (the handoff)
- Deliverables: local repro + RCA (investigations/) + fix (TDD or plan+subagent execution) + local surefire
  green + effective CI diff + a PROPOSED catalog delta (not a catalog edit); evidence/INDEX.md rows; **dev caveats documented in the
  workspace AND saved to memory**.
- Report-back: transition this instant's folder state (inflight→complete/abort) at session end;
  if you need the operator, park under a '## Parked decision' block in HANDOFF.md (do NOT block — the
  operator may be away; continue any other unblocked work while parked).

## Standing constraints / rules (NON-NEGOTIABLE)
- **Pipeline order:** LOCAL REPRO → systematic-debugging RCA (Spark-Java=GOLD vs Gluten-Velox=ACTUAL) →
  FIX+local-validation → CI+catalog. Never skip local repro; never fix before the RCA.
- **Two-node skills:** systematic-debugging = the RCA node; test-driven-development = the FIX node
  (small/clear). Large → brainstorming → writing-plans → subagent-driven-development.
- **Evidence:** raw artifacts into evidence/ (NEVER /tmp); every causal claim cited to a captured artifact.
- **CI TRUTH = SUREFIRE:** CI runs --fail-never and always shows green — download & parse the surefire report.
- **Local parity:** everything CI can run, you must be able to run locally doing the same thing.
- **get_velox.sh:** ensure gluten checks out the proper velox counterpart (matching branch/commit) for the fix.
- **GOLD spark path is SHARED + READ-ONLY:** `/home/ubuntu/davis_root/spark` @branch-4.1 is the GOLD Spark-Java
  reference — READ it to cite expected behavior (file:line). It is shared across ALL instants. For ANY write op
  under it (build there, `git checkout` a different ref, apply a patch, run a test that writes), create a **git
  worktree** — `git -C /home/ubuntu/davis_root/spark worktree add <your-ws>/spark-wt <ref>` — and work in the
  worktree; NEVER mutate the shared checkout other instants depend on. Record it in your workspace (ASSUMPTIONS/RUNBOOK).
- **Long-term fix, not bandaid:** maintainable, extensible, reliable. No adhoc hacks.
- **ANSI DESIGN PHILOSOPHY (north star — preserve Velox acceleration):** avoid a big-hammer fallback that
  loses Velox acceleration of other cases. Fallback is acceptable ONLY when there is no acceleration cost.
  Otherwise OFFLOAD to Velox (happy case accelerated) → Velox catches the bad case + populates the error →
  TRANSLATE to the standard Spark exception at the upper stack. Offload-deny is sanctioned ONLY if
  offload+translate is complex AND the happy case is rare — with written justification. Corollary:
  keep-offload+native-raise for COMMON ops; offload-deny only for RARE ops. Record strategy + justification in DECISIONS.
- **Document dev caveats** in the workspace (RUNBOOK/ISSUES) AND save them to memory for future instants.
- **maintain-workspace ALWAYS:** reproducible, reviewable, honest ASSUMPTIONS + ISSUES; keep HANDOFF/STATE current.
- **Autonomous-first:** run as far as you can without the operator (who may be away up to 20h); PARK only a
  genuine fork, and keep working other unblocked steps meanwhile.
