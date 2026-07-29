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

## LINEAGE BASE — read your BRIEF for YOUR base; this section is only the effort-wide default
⚠️ **YOUR base is whatever the "Base + lineage" section of the brief below names — that is per-milestone and it
WINS.** Some milestones deliberately stack on a **sibling's delivered tips** rather than on the effort's
terminal base, because a sibling's work is a hard prerequisite (e.g. lift-01 stacks on R2's tips: R2's
parameterised-target-type translator work must exist before more casts are made to raise). This section, the
seed, and the brief are three renderings of the same thing and the first two are effort-wide boilerplate — **if
any of them disagree with the brief, the BRIEF is authoritative and you tell the coordinator** (lift-01's OI-1:
it hit exactly this and adjudicated it correctly, but should not have had to).

**Effort-wide default, used only when the brief names nothing more specific** — the bounded 8-gap ANSI rework
is DONE and parked as ONE merge-ready stack per repo:
- gluten `davis/glutenmain-ansirework-final` @ **e1e04c5f5** — PR onehouseinc/gluten-internal#441
- velox  `davis/glutenmain-velox-ansirework-final` @ **efd7800c1** — PR onehouseinc/velox-internal#156

All 8 non-slow ANSI gaps are closed there red→green **while offloaded**, green→red REAL = 0
(CI run 29742621077). Cut YOUR branch off whichever tips your brief names; never push to them, and never push
to any shared branch. The coordinator restacks at the compaction.

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
- [ ] Prove it mechanically: **`pdispatch basecheck <your-todo-id>`**. A **short id now resolves**
      (`pdispatch basecheck lift01`) and an **ambiguous prefix is refused rather than guessed**, so you can use
      the short form or the full slug from your `.dispatch/` record. The registry label your coordinator uses
      may differ from the record key — if a short form is rejected, take the exact id from `.dispatch/` or
      `pdispatch board`. (Or `pdispatch basecheck --ws <your-ws> --expect "repo=<sha>,repo=<sha>"`.)
      It also reports whether the **native artifacts were rebuilt after the last checkout**, so a stale-artifact
      warning clears itself once you rebuild instead of nagging forever.
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
- [ ] ⚠️ **A ZERO-TEST RUN EXITS GREEN — always read `Total number of tests run`.**
      `-Dsuites='<Class> -z "<substring>"'` prints `Expected test count is: 0`, `No tests were executed.`, and
      then **`BUILD SUCCESS`**: the scalatest-maven-plugin never applies the Spark-docs-style `-z` filter, so
      nothing matches and the empty run passes. Correct form is space-separated with no `-z`:
      `-Dsuites='org.apache.spark.sql.GlutenSQLQueryTestSuite typeCoercion/native/concat.sql'`.
      **A targeted local run is the easiest place in the entire evidence chain to prove nothing while looking
      green** — cite the executed count, never just the build result.
- [ ] The fix is **maintainable, extensible, reliable, long-term — NOT an adhoc bandaid.** *(Amended
      2026-07-27 after R5's RV-20 correctly showed the original wording was an opinion criterion that could be
      neither passed nor failed on evidence. The intent stays; here is what a reviewer can actually check —
      answer each in the report:)*
      · **Layer:** is the change at the layer where the defect ORIGINATES, or is it a downstream patch that
        leaves the cause in place? Name the layer and why.
      · **Generality:** does it cover the whole family, or only the observed input? List the sibling cases it
        also fixes — and for any it does not, say why the boundary is principled rather than incidental.
      · **No per-shape special-casing:** count the branches you added that key on a specific literal, type or
        query shape. More than zero needs a justification.
      · **No new escape hatch:** you did not add a config flag, scoped-off test, or `try_`-style bypass that
        makes the symptom disappear without fixing it.
      · **Withdrawal is evidence of rigour, not failure:** if you proposed a fix and then withdrew it on
        evidence, say so — that is a stronger signal of non-bandaid work than any adjective.
- [ ] **NEGATIVE RESULTS ARE A VALID DELIVERABLE.** If the target does not close, say so EXPLICITLY with
      evidence and an RCA of why. Quietly redefining success is worse than a red run.

### AC-3b IF YOU ADD OR CHANGE AN ERROR/RAISE PATH — the degenerate-input and happy-path ACs are MANDATORY
Two instances across two efforts, both caught by review and neither by the implementer, make this a pattern
rather than a nit: **a guard that fires when there is nothing to guard.** MR4's aggregate over-raised at
`count==0`; R3's eager `In` path over-raised on a **zero-row** input. **An over-raise is worse than a missing
raise — it breaks queries that work today.** So, whenever your change makes something raise:
- [ ] **Name and test the degenerate inputs as explicit ACs: EMPTY input · ZERO rows · ALL-NULL input.**
      State what Spark does for each (cite GOLD) and prove you match it. "No rows were projected, so nothing
      should raise" is a *test*, not an assumption.
- [ ] ⚠️ **ZERO ROWS IS NECESSARY BUT NOT SUFFICIENT — add a PARTIALLY-SELECTIVE FILTER case** (lift-01's OI-11,
      which found this blind spot in the rule as originally written). A zero-row filter **cannot** detect
      *evaluate-then-mask*, because Velox may skip the projection entirely when nothing survives the filter — so
      an eager evaluation that raises on rows Spark never evaluates looks clean. You need a filter where **some
      rows pass and some do not**, with the bad value among the filtered-out rows: Spark raises nothing, and an
      eager implementation raises anyway. That topology is the only one that catches the failure mode.
- [ ] **Cover every FAMILY you newly cause to raise, not one representative** — unless you prove the machinery is
      shared. lift-01 found ARRAY / MAP / ROW containers do **not** share machinery (`applyMap` rebuilds its
      sizes buffer under a condition), so "representative family + implicit generalisation" would have left two
      containers with raise-only coverage. **Land the coverage rather than arguing the generalisation.**
- [ ] **Pin the HAPPY path as still taking the accelerated route.** Proving the error is not the job; proving
      the error *without losing offload* is. An errorClass-only assertion proves the raise and leaves the fast
      path unproven — the same vacuous shape as an AC that would pass by evaluating on vanilla Spark.
      Assert the offloaded operator in the plan, **with AQE disabled** (`withSQLConf(adaptive.enabled=false)`),
      because `WholeStageTransformerSuite.sparkConf` does NOT disable it and Spark 4.x defaults it ON.
- [ ] If you deliberately leave a degenerate-input divergence unfixed, that is allowed — but it must be
      **named, bounded (which configs / which inputs), and recorded in your catalog delta**, never left silent.

### AC-4 CI + the TWO-DIFF non-regression rule
- [ ] **DECLARE `Phase: AWAITING-CI` IN YOUR HANDOFF the moment local validation is done and you are only
      waiting on GitHub CI** — and clear it when the run lands. This is not bookkeeping: the coordinator holds a
      **WIP cap of 1 worker in ACTIVE DEV**, and `pdispatch health --active-dev` **excludes** AWAITING-CI. If
      you sit on a finished local tree without declaring it, you occupy a dev slot nobody can use while you do
      nothing but poll a URL. Declare it, then keep polling.
- [ ] One effective GitHub CI run (Velox Backend ANSI Mode) on your pushed tip. **Truth = the downloaded
      surefire XMLs** — jobs run `--fail-never` and ALWAYS look green. Never cite the checkmark.
- [ ] `get-velox.sh` must point at YOUR velox branch if you changed velox; otherwise leave the `-final` pin.
- [ ] **SHARED TOOLING CHANGES UNDER YOU MID-FLIGHT — read the changelog before interpreting any non-zero
      exit.** `pdispatch` tools are invoked from the repo, so a change reaches you immediately. Newest-first,
      with the exit-code impact per change:
      `/home/ubuntu/davis_root/operations/tasks/metaOpt/main-07270637-inflight-append-systemMetaOptimizationLoop/TOOLING-CHANGES.md`
      Re-read it if a tool behaves differently from what this charter describes — the charter is a snapshot,
      the changelog is live. **The one that bites hardest: `RED-NO-BASELINE` is FATAL BY DEFAULT in `regress`.
      A non-zero exit there is NOT evidence you broke something** — the tool cannot distinguish "added by this
      stack" from "existed but was never measured", and only the source history decides the owner.
- [ ] **Do NOT hand-roll a surefire parser.** Use **`pdispatch surefire <report-dirs> --dim <label>`** to
      produce `regress`'s input, one invocation per CI dimension with a distinct `--dim`. It parses XML as XML,
      drops skipped tests, makes FAIL beat PASS within a dim, and dim-qualifies every name so dimensions cannot
      be collapsed. (A hand-written regex captured the container `hostname` as the suite name and produced a
      confident, wholly wrong diff; a hand-rolled "FAIL anywhere wins" collapse then manufactured 5 phantom
      regressions from failures that existed on one dim only.)
- [ ] **CROSS-CHECK ANY NEW EXTRACTION AGAINST A KNOWN-GOOD NUMBER BEFORE YOU BELIEVE IT.** Pick a figure
      already recorded in the evidence chain — e.g. the lineage base's `new red=43` in `COMPACTED.md` — and
      confirm your extraction reproduces it. Plausible-looking totals prove nothing, and a tool can print
      `coverage: complete` over a comparison in which nothing matched at all.
- [ ] **CITE THE SEMANTICS VERSION next to every recorded diff, and treat cross-version results as
      INCOMPARABLE.** `pdispatch regress` stamps its version into text and JSON and answers `--version`
      (current: `semantics v3 (2026-07-27)` — red-no-baseline fatal by default, bidirectional coverage,
      zero-overlap input mismatch fatal). Shared tools change under a running fleet, so a diff recorded this
      morning and one recorded this afternoon may not mean the same thing. **Do not reconcile results from
      different semantics versions** — record which version produced each and treat the older as SUPERSEDED by
      a re-run under the current one. A changelog cannot repair a number already written down.
- [ ] **Read the adapter's SKIPPED line.** `pdispatch surefire` now counts and NAMES the files it did not read
      (`--all-xml` takes everything). If it names anything, every number derived from that extraction is
      provisional until re-derived. Both a bespoke parser and the shared adapter have silently dropped rows in
      this effort — the difference is that the adapter now tells you.
- [ ] **If you need a shape the shared adapter does not produce, route it to the coordinator as a TOOL GAP —
      do NOT hand-roll a parser.** Two bespoke parsers were written in this effort in one day and both lost
      data silently (a `hostname` attribute captured as a suite name; a substring filter dropping 43 rows per
      dim). A parser is exactly the code where a plausible output is indistinguishable from a correct one.
- [ ] Read `regress`'s **overlap** line and quote it. Zero overlap is a fatal input mismatch (your adapter, not
      your code); low overlap means the two runs are not comparing what you think. And do **not** read
      `coverage: complete` as proof every dim was compared — verify the dim list yourself (RI-17).
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
