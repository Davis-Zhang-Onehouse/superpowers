# {{TITLE}} — CHARTER   (durable; edit deliberately)
Instant: {{CHILD_NAME}}
Updated: {{TODAY}} | Status: DURABLE
Dispatched by parallelDispatch from base instant: {{BASE_NAME}}
Kind: **WORKER** — one milestone of the RESUMED Gluten+Velox ANSI effort. You do the dev.

## Goal (e2e)
{{TITLE}}

## Setup to begin with
- Base instant: {{BASE_CURR}}  (forked from {{BASE_NAME}})
- Workspace: {{WS}}  (slot {{SLOT}}, leased; duplicated from golden {{GOLDEN}} — pre-built, no rebuild)
- Your maven cache is already isolated to `{{WS}}/.m2` via `.mvn/maven.config` (OI-6/FC-12). Do not install
  into the shared `~/.m2`.

## LINEAGE BASE — what you inherit (never restart from the original baseline)
The bounded 8-gap ANSI rework is **DONE** and parked as ONE merge-ready stack per repo. Your milestone
stacks on that end-state:
- gluten `davis/glutenmain-ansirework-final` @ **e1e04c5f5** — PR onehouseinc/gluten-internal#441
- velox  `davis/glutenmain-velox-ansirework-final` @ **efd7800c1** — PR onehouseinc/velox-internal#156

All 8 non-slow ANSI gaps are closed there red→green **while offloaded**, green→red REAL = 0
(CI run 29742621077). Cut YOUR branch off those tips (naming in the brief); never push to them, and never
push to any shared branch. The coordinator restacks at the compaction.

## First raw prompt / brief (the dispatch — authoritative for scope)
{{BRIEF}}

## Evidence pointers from the base (start your RCA here)
{{EVIDENCE}}
## Acceptance criteria — the NON-NEGOTIABLE pipeline (do the phases IN ORDER)

### AC-0 POSITION YOUR WORKSPACE ON THE LINEAGE BASE — first command, before anything
- [ ] **Your slot is leased at the GOLDEN prebuild (gluten `4020d0715` / velox `8d62aac98`), NOT at your
      lineage base.** Nothing moves it forward for you, and forgetting is INVISIBLE: the build succeeds, the
      tests pass, and your whole milestone silently stacks on the pre-fix baseline. Two workers in the
      previous wave hit exactly this.
- [ ] Prove it mechanically: **`pdispatch basecheck <your-todo-id>`** (or
      `pdispatch basecheck --ws <your-ws> --expect "gluten-internal=<sha>,velox-internal=<sha>"`).
- [ ] Then either **reposition** (`git fetch --all && git checkout --detach <tip>`, then cut your branch) —
      noting that moving off the golden commit can invalidate the prebuilt native artifacts, so plan the
      rebuild — **or**, if you are an ANALYSIS-ONLY milestone, deliberately stay on golden and read
      everything via `git show <tip>:<path>` / `git diff <base>..<tip>`. **If you choose the second, say so
      explicitly in your report and in ISSUES** — otherwise a later `basecheck` reads as a real mismatch.
- [ ] Re-run `basecheck` after repositioning. A workspace on the wrong base invalidates every AC below it.

### AC-1 LOCAL REPRO first (before RCA, before any fix)
- [ ] Reproduce the target's failing behavior **locally** in this workspace (the exact test/suite CI runs),
      on the lineage base. Capture raw failing output into `evidence/` (NEVER /tmp) + the exact command into
      RUNBOOK.md so a cold reader can re-run it. If it will not repro locally, that IS the first RCA finding.
- [ ] For an analysis-only milestone: the equivalent is capturing the raw current-state artifacts you will
      reason from (GOLD `.sql.out` excerpts, surefire XMLs, source citations) before drawing any conclusion.

### AC-2 RCA via systematic-debugging (RCA-FIRST — before any fix)
- [ ] Run `superpowers:systematic-debugging`. `investigations/<topic>/analysis.md` documents the
      **Spark-Java (GOLD) vs Gluten-Velox (ACTUAL)** behavioral diff, every causal claim tied to a captured
      artifact under `evidence/` (not memory), with a reproducible repro.

### AC-3 FIX + local validation (branch on scope AFTER the RCA)
- [ ] Small/localized/clear → `superpowers:test-driven-development` (RED = the failing test → GREEN).
      Large/multi-file/ambiguous → `superpowers:brainstorming` → `writing-plans` → `subagent-driven-development`.
- [ ] Local validation GREEN proven via **surefire** (target passes; no regression in the touched suites).
- [ ] The fix is **maintainable, extensible, reliable, long-term — NOT an adhoc bandaid.**
- [ ] **NEGATIVE RESULTS ARE A VALID DELIVERABLE.** If the target does not close, say so EXPLICITLY with
      evidence and an RCA of why. Quietly redefining success is worse than a red run.

### AC-4 CI + the TWO-DIFF non-regression rule
- [ ] One effective GitHub CI run (Velox Backend ANSI Mode) on your pushed tip. **Truth = the downloaded
      surefire XMLs** — jobs run `--fail-never` and ALWAYS look green. Never cite the checkmark.
- [ ] `get-velox.sh` must point at YOUR velox branch if you changed velox; otherwise leave the `-final` pin.
- [ ] **Two diffs, not one** (`pdispatch regress`):
      (a) vs the fixed **M1 baseline** (runs 29618938212 non-slow + 29622614234 slow) — catches green→red;
      (b) vs the **lineage base** CI run **29742621077** — catches an already-CLOSED gap re-breaking, which
      is red→red against M1 and therefore INVISIBLE there. Diff (b) is not optional.
- [ ] **Every one of the 8 closed gaps re-asserted GREEN BY NAME** in your report (not "no new reds").
- [ ] Every previously-green test that flips red is RCA-classified: intended (now-throws / now-offloads /
      now-correct / irrelevant-noise) → a GOLD-cited, individually justified sanctioned-flip proposal; else
      it is a REGRESSION you must fix. Zero unresolved flips to finish.
- [ ] Caveat FC-15: `precise_diff` does NOT surface newly-ADDED red tests. Assert any suite you add or
      modify GREEN directly from its surefire XML, not only via the diff.
- [ ] **The bv40 dim has NO lineage-base surefire — use the PROXY and say so.** The lineage base's run
      29742621077 uploaded nothing for `spark-test-backends-velox-ansi-spark40` (that job died at "Prepare
      Spark Resources"), so diff (b) is structurally impossible for that dim. Use run **29738878247** (run 2 of
      the final compaction) as the bv40 lineage-base proxy, and **state the substitution wherever you rely on
      it**. A silent substitution becomes a false claim later.
- [ ] **A test that FAILS while no baseline covered it is invisible to every diff** — `regress` now reports it
      as **RED-NO-BASELINE** (fatal by default; `--allow-new-red` downgrades it only for residuals you have
      documented as intentionally red, and they stay listed). Real case: `AnsiErrorTranslatorValidateSuite`
      fails 5/5 on bv40 while every diff called the dim CLEAN.
      **Do NOT assume RED-NO-BASELINE means you broke it.** No results file can distinguish *"added by this
      stack"* from *"existed but was never measured"* — only the source history can, and it decides the owner.
      Check whether the test existed on the lineage base before you accept or route the blame.
      For any suite added or modified since the baseline, read its surefire XML DIRECTLY and assert pass/fail
      by name. **A clean `regress` output is not evidence for such a suite.**
- [ ] **ABSENCE OF A RESULT IS NOT A PASS.** A suite that never ran produces no red, and a diff of red-vs-green
      cannot see it — that is how a whole class of missing coverage stayed invisible (FC-21's hazard class; a
      census found 548 `enableSuite` entries against 193 suites with a surefire XML). For every gap/row you
      claim closed, assert its suite is **PRESENT in the results AND green** — cite the XML path, not the
      absence of a failure. If a suite you depend on has no XML, say so; that is a finding, not a pass.

### AC-5 Catalog — PROPOSE ONLY (single-writer rule)
- [ ] The coordinator is the ONLY writer of the canonical `catalog/CATALOG.md` + `catalog/sanctioned-flips.md`.
      Deliver a **proposed delta** in `investigations/catalog-delta.md` (+ in your report). **Never edit the
      canonical catalog or any file in the coordinator's instant other than your one report file.**

### AC-6 COMPLETION GATE (hard, blocking — no exceptions)
- [ ] Before renaming your folder, run `superpowers:review-workspace` (ALL stages, `--scope all`) on THIS
      instant and PASS: verdict **READY**, or **READY-WITH-FIXES with zero open Critical/Important**, every
      AC VERIFIED on evidence fresh at your delivered tip, recorded in `REVIEW.md`. If Important findings
      were fixed, re-run the affected stage and record a SECOND round. **No passing round = not complete.**

### AC-7 Report back + rename (this is how completion is detected)
- [ ] Write your report at the exact path given in the brief: AC results with evidence paths, gluten+velox
      branch tips and PR links, `get-velox.sh` state, the proposed catalog delta, the REVIEW.md verdict, open
      issues classified, and any operator forks.
- [ ] Then transition your OWN folder `-inflight-` → `-complete-`. The coordinator gates and harvests.

## NORTH STAR — the ANSI design philosophy (non-negotiable, applies to new AND existing code)
**Preserve Velox acceleration: keep the operator OFFLOADED, let Velox raise on the bad case, and TRANSLATE
the native error into the standard Spark exception at the upper stack.** A coarse fallback or offload-deny is
acceptable ONLY when offload+translate is genuinely complex AND the happy case is rare — and then only with a
written justification in DECISIONS. Keep-offload+native-raise for COMMON ops.
**Corollary:** closing a target INCLUDES lifting any pre-existing coarse fallback that already makes it "pass"
while defeating the goal — even if a test is green with it in place. Never scope ANSI off to make a test pass.

## Standing constraints / rules (NON-NEGOTIABLE)
- **Pipeline order:** LOCAL REPRO → systematic-debugging RCA → FIX + local validation → CI + two-diff.
  Never skip the local repro; never fix before the RCA.
- **Evidence:** raw artifacts into `evidence/` (NEVER /tmp); every causal claim cited to a captured artifact.
- **CI TRUTH = SUREFIRE.** `--fail-never` means the summary is always green. Download and parse the XMLs.
- **AQE hides offload:** when probing whether an operator really offloaded, disable AQE — `getExecutedPlan`
  under AQE can hide the real Velox offload.
- **Local parity:** anything CI runs, you must be able to run locally the same way.
- **GOLD spark path is SHARED + READ-ONLY:** `/home/ubuntu/davis_root/spark` @branch-4.1 is the GOLD
  Spark-Java reference — READ it and cite file:line. For ANY write op under it (build, `git checkout` another
  ref, patch, a test that writes) create a git worktree —
  `git -C /home/ubuntu/davis_root/spark worktree add {{WS}}/spark-wt <ref>` — and work there. NEVER mutate the
  shared checkout other instants depend on. Record the rule in your ASSUMPTIONS/RUNBOOK.
- **Branch discipline:** your own branch + your own draft PR. Never push `davis/glutenmain-ansirework-final`,
  `davis/glutenmain-velox-ansirework-final`, or any other shared branch. Never merge anything, ever — the
  merge of #441/#156 is the operator's decision alone.
- **Budget:** treat an effective CI run as expensive. Budget in the brief. A FAILED or STALE run is NOT
  evidence — if you must re-spend, do it and REPORT the overrun rather than lowering the evidence bar.
- **Document dev caveats** in RUNBOOK/ISSUES **and** save durable cross-effort lessons to memory.
- **maintain-workspace ALWAYS:** honest ASSUMPTIONS + ISSUES; keep HANDOFF/STATE current as you go.
- **Autonomous-first:** the operator may be away for many hours. Run autonomously. PARK only a genuine
  OPERATOR-ONLY fork under `## Parked decision` in HANDOFF.md and keep every other unblocked step moving —
  the coordinator answers the forks that are its to call and will read your park block each tick.

## Setup to end up with (the handoff)
Local repro + RCA (`investigations/`) + fix (TDD or plan+subagents) + local surefire green + ONE effective CI
with BOTH diffs + proposed catalog delta + a passing REVIEW.md round + the report at the brief's path +
your folder renamed to `-complete-`.
