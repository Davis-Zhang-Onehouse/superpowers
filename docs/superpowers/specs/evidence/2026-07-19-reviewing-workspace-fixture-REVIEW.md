# m1.1 ansi full exposure completeness — REVIEW   (append-only review ledger; never rewrite, supersede in place)
Updated: 2026-07-19 by session <reviewing-workspace-acceptance-run>  |  Status: LIVING register

Records every review round for this instant: findings, their status, and the action taken —
the audit trail from "comment raised" to "comment addressed". Newest round on top.

## Round R1 — 2026-07-19 · trigger: on-demand · scope: all
Note: acceptance run of superpowers:reviewing-workspace against the example instant fixture.
Git snapshot (from HANDOFF PR-stack table):
| Repo | Branch | Tip sha at review |
|------|--------|-------------------|
| gluten-internal (ws5) | davis/m11-float-c3-verify | 4020d0715 + C3 (local) |
| gluten-internal (base) | davis/glutenmain-rc-base | 4020d0715 |
| velox-internal (ws5) | davis/glutenmain-velox-rc-base | 8d62aac98 |

### Stage 1 — Format & hygiene   (verdict: FIXED — 13 mechanical, 3 judgment; mechanical auto-applied)

#### RV-1 — Forbidden top-level STATE.md
- Stage: format | Severity: Critical | Status: ADDRESSED (auto-fix)
- Location: STATE.md (whole file)
- Finding: A separate STATE.md held the PR/branch-stack table + a "Setup to end up with" block.
- Why it matters: Invariant 3 — state and the PR stack must live only in HANDOFF's current-state part; a separate STATE.md drifts.
- Action taken (2026-07-19): Folded the PR/branch-stack table into HANDOFF's current-state part; deleted STATE.md.
- Verified-by: `ls STATE.md` → absent; HANDOFF now carries the "PR / branch stack" table.

#### RV-2 — PR/branch-stack table absent from HANDOFF
- Stage: format | Severity: Critical | Status: ADDRESSED (auto-fix)
- Location: HANDOFF.md (current-state part)
- Finding: The REQUIRED PR/branch-stack table existed only in the forbidden STATE.md.
- Why it matters: Invariant 3 — a resumer reading HANDOFF could not see repo/branch/tip/PR/CI state.
- Action taken (2026-07-19): Inserted the table into HANDOFF's current-state part (folded from STATE.md).
- Verified-by: HANDOFF "## PR / branch stack" section present.

#### RV-3 — Bare CI run-id in the stack table
- Stage: format | Severity: Minor | Status: ADDRESSED (auto-fix)
- Location: (former) STATE.md:7 → now HANDOFF PR-stack table
- Finding: CI cell read the bare run-id "M1 slow CI 29622614234".
- Why it matters: Invariant 3 — a bare run-id is INCOMPLETE and not clickable.
- Action taken (2026-07-19): Rendered as `[M1 slow CI run 29622614234](https://github.com/onehouseinc/gluten-internal/actions/runs/29622614234)` when folding.
- Verified-by: `grep actions/runs/29622614234 HANDOFF.md` → present.

#### RV-4 — Volatile "in progress" state in a durable register
- Stage: format | Severity: Important | Status: OPEN
- Location: ISSUES.md:46 (ISSUE-1 Status)
- Finding: ISSUE-1 Status = "GREEN verification in progress …" — live/volatile state in a durable register, and stale (HANDOFF reports GREEN captured / DONE).
- Why it matters: Invariant 2 — durable docs carry no volatile state; this one also contradicts HANDOFF.
- Action taken (2026-07-19): Flagged (mechanical fix available: set durable "RESOLVED via C3"; kept OPEN pending operator confirmation of true state — see RV-8).
- Verified-by: —

#### RV-5 — Live snapshot embedded in a durable decision
- Stage: format | Severity: Minor | Status: OPEN
- Location: DECISIONS.md:59
- Finding: "the translate path, running in ws4 right now" embeds a live snapshot in a durable decision.
- Why it matters: Invariant 2 — durable docs must not encode "right now" state.
- Action taken (2026-07-19): Flagged; recommend rewording to durable form.
- Verified-by: —

#### RV-6 — Missing `Status:` field in doc headers
- Stage: format | Severity: Auto-fix | Status: ADDRESSED (auto-fix)
- Location: DECISIONS.md:2, ISSUES.md:2, ASSUMPTIONS.md:2, RUNBOOK.md:2, evidence/INDEX.md:2, investigations/float-cast-invalid/analysis.md:2
- Finding: Headers had `Updated:` but no `Status: DURABLE|LIVE`.
- Why it matters: Header rule — every doc declares durable-vs-live.
- Action taken (2026-07-19): Recorded as auto-fixable (add `| Status: DURABLE`); batch header normalization applied by the orchestrator.
- Verified-by: reviewer checklist (header rule).

#### RV-7 — DECISIONS sections missing per-decision Status subfield
- Stage: format | Severity: Minor | Status: OPEN
- Location: DECISIONS.md D-1/D-2/D-3
- Finding: Decisions are correctly sectioned (not a table) but none carries the required `Status:` subfield.
- Why it matters: Register rule — one-section-per-decision includes Status(ACTIVE|SUPERSEDED).
- Action taken (2026-07-19): Flagged; append `**Status:** ACTIVE` (D-1 note F-1 RESOLVED).
- Verified-by: —

#### RV-8 — Contradiction: verify-branch committed vs uncommitted
- Stage: format | Severity: Important | Status: OPEN (judgment)
- Location: (former) STATE.md:6 vs HANDOFF.md
- Finding: STATE said C3 patch "applied (uncommitted)"; HANDOFF says verify branch "committed 06ce4d707".
- Why it matters: Invariant 2/3 — durable state contradicts the live snapshot; a resumer can't tell if the branch is committed.
- Action taken (2026-07-19): Flagged for operator; not auto-fixable (true state unknown).
- Verified-by: —

#### RV-9 — ASSUMPTIONS register empty despite AS-1/AS-2 cited elsewhere
- Stage: format | Severity: Important | Status: OPEN (judgment)
- Location: ASSUMPTIONS.md:4-6
- Finding: ASSUMPTIONS.md is an empty table though AS-1 (DECISIONS.md:15) and AS-2 (analysis.md:91-100) are cited.
- Why it matters: Assumptions referenced across the instant are not recorded in their register.
- Action taken (2026-07-19): Flagged; backfill AS-1/AS-2 (text not deterministically recoverable → judgment).
- Verified-by: —

#### RV-10 — Instant still named `…-inflight-…`
- Stage: format | Severity: Minor | Status: OPEN (judgment)
- Location: instant folder name / HANDOFF.md
- Finding: Folder is `…-inflight-…` while HANDOFF declares "DONE (except parked CI)"; AC-4 is unmet, so inflight may be justified.
- Why it matters: Naming rule — a finished instant must not stay `…-inflight-…`.
- Action taken (2026-07-19): Flagged; the transition decision is coupled to AC-4 (RV-12).
- Verified-by: —

### Stage 2 — Goal alignment   (verdict: GAPS)

Chain: setup-to-begin → deliverables → evidence → acceptance → goal.

#### AC-1 LOCAL REPRO : VERIFIED
- Evidence: evidence/INDEX row 6 → evidence/02-local-repro/RED-summary.txt + surefire-RED-*.xml (tests=4, failures=2).
- Note: float4/8 FAIL on rc-base@4020d0715, ANSI-on, spark-4.1; signature matches catalog F-1. Executed proof, re-derivable via RUNBOOK Steps 0-2.

#### AC-2 RCA (systematic-debugging) : VERIFIED
- Evidence: investigations/float-cast-invalid/analysis.md; INDEX rows 1-4 (gold source + velox-cast-path + gluten-error-surface).
- Note: GOLD-vs-ACTUAL framing explicit; each causal node tied to a cited real source (SparkCastExpr.cpp:30-46 etc.). Re-derivable.

#### AC-3 FIX + local GREEN : VERIFIED (two caveats → RV-11, RV-13)
- Evidence: INDEX rows 5,8,9 → C3-662e26bf2.patch, GREEN-summary.txt, surefire-GREEN-*.xml (tests=4, failures=1).
- Note: GREEN surefire proves F-1 closed (float4 PASS; float8 first-mismatch moved #15→#33, so #15 now raises). Caveats: fix is borrowed sibling-M2 C3 (not authored here — defensible per D-2); "no regression" only asserted (2 of 332 .sql files run).

#### AC-4 GitHub CI + CATALOG + velox counterpart : INSUFFICIENT
- Evidence: CATALOG.md present (F-1 reclassified). MISSING: any downloaded surefire from a Velox Backend ANSI Mode CI run.
- Note: AC-4 is PARKED (HANDOFF "## Parked decision"). Charter's non-negotiable "CI TRUTH = downloaded surefire ONLY" + "authoritative catalog from amd64 in-container CI (ARM not interchangeable)" are unmet; all green is ARM-local. To reach VERIFIED: land the C3-bearing ANSI slow-dim CI run, download the surefire showing float4/8 red→green + no regression, diff vs run 29622614234.

#### RV-11 — Goal not achieved: scope reduced from "0 hidden ANSI gaps" to one gap
- Stage: alignment | Severity: Critical | Status: OPEN
- Finding: The e2e Goal (T1-T6 completeness: masking audit, fallback census, enablement coverage, removal integrity, consolidated catalog) was reframed to a single item (F-1); CATALOG states "Remaining needs-RCA tail after F-1: 20 (unchanged)"; T2 fallback-census (the designated deepest-miss centerpiece) not performed.
- Why it matters: The instant cannot claim "full exposure completeness" — the goal-defining links are absent.
- Action taken (2026-07-19): Flagged. Action: either re-scope charter/HANDOFF to declare F-1 the true deliverable (completeness OUT), or execute T1-T6 before claiming completeness.
- Verified-by: CATALOG.md bookkeeping line; charter T1-T6.

#### RV-12 — AC-4 CI proof missing (authoritative artifact absent)
- Stage: alignment | Severity: Critical | Status: OPEN
- Finding: No downloaded surefire from an ANSI-mode CI run exists; all proof is ARM-local, which the charter declares non-authoritative.
- Why it matters: The load-bearing "Setup to end up with" deliverable (effective CI diff) is unmet; blocks a legitimate inflight→complete transition.
- Action taken (2026-07-19): Flagged. Action: land C3-bearing CI (operator option A/B), download slow-dim surefire, confirm red→green + no regression, diff vs 29622614234.
- Verified-by: —

#### RV-13 — AC-3 "no regression" unproven
- Stage: alignment | Severity: Important | Status: OPEN
- Finding: Local GREEN ran only float4/float8 (2 of 332 files); C3 alters global VeloxValidatorApi.doExprValidate.
- Why it matters: A global-validator change with a 2-file local proof leaves regression risk unquantified.
- Action taken (2026-07-19): Flagged. Action: run CastAnsiValidateSuite + touched suites locally with captured surefire, or rely on the CI report (RV-12).
- Verified-by: —

#### RV-14 — ANSI design-philosophy justification not recorded
- Stage: alignment | Severity: Important | Status: OPEN
- Finding: D-1 calls cast a COMMON op (philosophy → keep-offload+translate) yet the accepted C3 denies offload of ALL ANSI string→numeric casts (valid inputs included), costing Velox acceleration; deferred to sibling ownership without the written justification the charter's "offload-deny only for RARE ops" rule demands.
- Why it matters: A standing-constraint / design-philosophy deviation without the required written justification.
- Action taken (2026-07-19): Flagged. Action: record in DECISIONS the acceleration-cost justification (or the Mr1 translate-path handoff).
- Verified-by: —

### Stage 3 — Code review   (verdict: N/A)

Reviewed (delta since last round): none.
Skipped (inherited from base instant, reviewed upstream): base PRs carried from m1CatalogFactRevision.
Note: No PR was authored on this instant (verify-only branch `davis/m11-float-c3-verify`, no PR; C3 owned by sibling M2). Stage 3 is N/A; the round verdict rests on Stages 1-2.

## Round summary — overall verdict: NOT-READY
- Stage verdicts: format=FIXED (3 mechanical auto-applied here + header batch; 6 judgment/deferred OPEN) · alignment=GAPS · code=N/A
- Open findings: Critical 2 (RV-11 goal-scope, RV-12 AC-4 CI) · Important 4 (RV-4, RV-8, RV-9, RV-13, RV-14) · Minor 3 (RV-5, RV-7, RV-10)
- Recommendation: Do NOT `mv …-inflight-… …-complete-…`. Resolve RV-12 (land the authoritative ANSI CI surefire diff) and decide RV-11 (re-scope to F-1, or execute the T1-T6 completeness proof) before completing. RV-10 (folder transition) is gated on those.
