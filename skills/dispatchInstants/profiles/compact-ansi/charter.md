# {{TITLE}} — CHARTER   (durable; edit deliberately)
Instant: {{CHILD_NAME}}
Updated: {{TODAY}} | Status: DURABLE | Kind: COMPACTION (stacks existing completed work — NOT new feature dev)
Dispatched by parallelDispatch from base instant: {{BASE_NAME}}

## Goal (e2e)
{{TITLE}} — fold the listed COMPLETED input instants into ONE reviewed, validated PR stack per repo, proving
the union of their acceptance criteria together on the stack with the SAME CI and ZERO regressions vs the
orchestrator's canonical catalog. This is a **compaction** (per superpowers:maintain-workspace Compaction +
the orchestrator's D-10/D-11 + RUNBOOK §4), not a gap fix.

## Setup to begin with
- Base instant: {{BASE_CURR}}  (forked from {{BASE_NAME}})
- Workspace: {{WS}}  (slot {{SLOT}}, leased; duplicated from golden {{GOLDEN}} — pre-built)

## First raw prompt / brief (the dispatch — lists the input instants + their branches)
{{BRIEF}}

## Evidence pointers from the base (start here)
{{EVIDENCE}}

## Acceptance criteria — the COMPACTION CONTRACT (do the phases IN ORDER)

### AC-1 One PR stack per repo (restack the inputs' per-MR branches into a single chain)
- [ ] Restack each input's per-MR branch into ONE chain per repo — gluten (`ansirework → …mr2 → …mr4 → …`)
      and velox (`rc-base → …mr4-velox → …`) as the brief specifies. Record the restack base + every rebase
      fix-up in STATE.md/HANDOFF (a cold reader can reproduce the chain). Push the compacted branches; raise/refresh ONE draft PR per repo.

### AC-2 Merged acceptance criteria — each RE-PROVEN on the compacted stack
- [ ] Enumerate the UNION of the input instants' ACs (list them). Each must be **re-proven on the compacted
      stack**, not just carried over — the fixes must all hold TOGETHER (no fix regresses another).

### AC-3 Proper LOCAL validation GREEN (surefire) on the compacted stack
- [ ] Build the compacted stack (per-repo) and run the target suites LOCALLY — every gap the inputs closed is
      GREEN together; captured surefire in evidence/ (NEVER /tmp) + exact commands in RUNBOOK. `-Dmaven.repo.local`
      per-instant (OI-6). Velox rebuild if the stack includes velox changes; get-velox.sh → the compacted velox branch.

### AC-4 SAME effective Velox ANSI CI + ZERO regressions vs the canonical catalog
- [ ] Run the SAME effective Velox Backend ANSI CI on the compacted stack (truth = downloaded surefire;
      `--fail-never`). `precise_diff` vs M1 (baselines 29618938212 / 29622614234). **Compare against the
      orchestrator's canonical `catalog/CATALOG.md`:** every gap the inputs marked 🟩 stays GREEN on the stack;
      **ZERO new green→red** beyond the already-sanctioned set; classify any flip per §1.5. Deliver a
      **consolidated PROPOSED catalog delta** (do NOT edit the canonical catalog — the orchestrator applies it).

### AC-5 ISSUES due-diligence (nothing dropped)
- [ ] Go over EVERY compacted input instant's `ISSUES.md`. Each open concern → **remains-open | addressed |
      transformed** (origin noted), carried into this instant's ISSUES.md + COMPACTED.md. No open concern is lost.

### AC-5b DECLARE `Phase: AWAITING-CI` the moment local validation is done
- [ ] The instant your local proof (AC-3) is GREEN and you are only waiting on GitHub CI (AC-4), write
      **`Phase: AWAITING-CI`** in your HANDOFF — and REMOVE it if you resume editing. The coordinator runs a
      **WIP cap of 1 worker in ACTIVE DEV**, and `pdispatch health --active-dev` can only exclude a CI-waiter
      that DECLARES the phase — **nothing infers it**. At a cap of 1 an undeclared CI-waiter holds the entire
      effort's only dev slot hostage to your CI queue. (Added 2026-07-29: `951a107` added this obligation to
      the `ansi-resume` profile only; a compaction waits on CI at least as long, so it belongs here too.)

### AC-6 COMPACTED.md + maintain-workspace + review gate
- [ ] Write `COMPACTED.md` (the four-part contract: ① stacked PR chain · ② merged ACs each proven · ③ evidence
      disposition REGENERATED|CARRIED-OVER-with-justification · ④ lingering-issue reconciliation). Keep
      HANDOFF/STATE/RUNBOOK/evidence-INDEX self-contained (one build + one CI re-derives all merged evidence).

## Setup to end up with (the handoff — the new lineage base)
- **One draft PR stack per repo** (gluten + velox), local-green + CI-green (no regressions vs catalog), COMPACTED.md,
  reconciled ISSUES, consolidated PROPOSED catalog delta. This instant's end-state is the **base for the next wave** (D-11).
- Report-back: write the orchestrator's `dispatch/<THIS>-REPORT.md` (stack tips, merged-AC proof, CI/precise_diff,
  consolidated catalog delta, ISSUES reconciliation, review verdict), then transition inflight→complete.

## Standing constraints / rules (NON-NEGOTIABLE)
- **Compaction stacks EXISTING work — it is NOT new feature dev.** Do not re-open the fixes' design; restack,
  re-prove, reconcile. If a fix genuinely conflicts on restack, record it (STATE + ISSUES) and resolve minimally.
- **CI TRUTH = SUREFIRE** (`--fail-never` → always green; download + parse). Local parity: everything CI runs, run locally.
- **Catalog = PROPOSE ONLY.** The orchestrator is the single writer of `catalog/CATALOG.md` + `sanctioned-flips.md`;
  deliver a consolidated proposed delta, never edit the canonical files.
- **GOLD spark path is SHARED + READ-ONLY:** `/home/ubuntu/davis_root/spark` @branch-4.1 — read to cite GOLD; for
  ANY write op under it, create a **git worktree** (`git -C /home/ubuntu/davis_root/spark worktree add <ws>/spark-wt <ref>`),
  never mutate the shared checkout other instants depend on. (D-12.)
- **maintain-workspace ALWAYS** (honest ASSUMPTIONS + ISSUES; reproducible, reviewable).
- **COMPLETION GATE (hard):** run **`superpowers:review-workspace`** (`workspace review --all`, ALL stages) on
  THIS instant and PASS (READY / READY-WITH-FIXES, no open Critical/Important, every merged AC VERIFIED on fresh
  evidence) recorded in REVIEW.md BEFORE inflight→complete. No passing round = not complete.
- **Autonomous-first:** operator may be away ~20h; run autonomously, PARK only a genuine fork.
