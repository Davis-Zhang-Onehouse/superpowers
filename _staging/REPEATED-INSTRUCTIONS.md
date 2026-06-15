# Repeated Standing Instructions — davis@onehouse.ai (Hudi MOR offload effort)

Mined 2026-06-15 from ~70 Claude sessions (past week) across the 3 task workspaces
(`~/ws1`/`ws2`/`ws3`) **and** the per-repo session dirs for `hudi-internal` and
`hudi-rs`/`hudi-rs-internal`. These are the user's repeated *directives about how to
work* — process/behavior/convention commands he had to re-issue, not info-questions
(those are in `WORKSPACE-AND-HANDOFF-ROUTINE.md` Part I.2).

> **STAGING NOTE:** Raw material for later processing into a new skill / CLAUDE.md
> revisions. Each rule lists: the signal (how many independent sessions/repos it
> recurred in), 2-3 verbatim quotes with `source = <dir>/<8-char-session-id>`, and a
> suggested durable home. The crispest drop-in form is consolidated in §10.

**Method/caveats:** counts are distinct *sessions* (the durable signal); re-quotes inside
the compaction/retrospective transcripts (`ws2/c801b58c`, `62eccd9a`, `f223d878`) were
treated as corroboration, not independent hits. A few conventions (JDK 11/17 split, "fix
broken scripts," the build recipe) had most raw occurrences just before the 06-08 window
but were re-surfaced this week — kept. The `hudi-internal` repo sessions run 06-01→06-06
(still within the past week) so that corpus was mined in full. Skill-template boilerplate
the user pasted (writing-plans/systematic-debugging bodies) was excluded.

---

## 1. Autonomy — don't ask for approval; decide, document, proceed
**Signal: very high — all 3 minings, ~8+ sessions.**
- "don't ask me for design, execution plan approval or any clarification questions, I give clear acceptance critierion, you follow the procedure and carry them out." — `ws2/62eccd9a`, `ws2/c801b58c`
- "You make decisions, document them and progresses, issues spotted, fixed, deferred over time, never ask me for anything." — `ws2/3967dd59`
- "Make your own decisions, don't ask clarification questions, keep iterating until you split out the PRs and acceptance critierion are met." — `ws3-hudi-rs-internal/fc50aebd`
- "don't block on my approval … iterate until all tests are green or we need a redesign." — `ws1-hudi-rs/8948bff2`
→ **Durable home:** CLAUDE.md behavior rule. (Caveat: keep the brainstorming design-approval gate for genuinely new work; autonomy applies once acceptance criteria are given.)

## 2. Default workflow — superpowers brainstorm → write-plan → subagent execution, loop to green
**Signal: very high — all 3 minings, ~9 sessions.**
- "can we use super power brain storm -> write plan -> subagent execution to do the work?" — `ws2/62eccd9a`, `ws2/c801b58c`
- "do brain storm -> plan writing -> sub agent execution -> update the PR change stack -> monitor CI status" — `ws3-hudi-rs-internal/389e6397`
- "Please start with super power brain storm -> write plan -> subagent execution mode and keep looping until acceptance critierion are met." — `ws2/3967dd59`
→ **Durable home:** a workflow skill / CLAUDE.md default execution mode for non-trivial tasks; execute end-to-end without "should I continue?" pauses (stop only on real BLOCKED).

## 3. Keep the designated workspace/tracking doc + PR-stack links current as you go
**Signal: highest frequency — ~13 sessions; historically the most-violated.**
- "update the PR links in the workspace folder in status report as you go" — `ws1/a52923e0`
- "keep your progress, status, PR links and gaps, changes tldr tracked in …/0611glutenveloxcleanup" — `ws2/7389eccc`
- "keep status updated in …/tasks/0606-1-productquality/ and put all adhoc doc, artifacts, scripting there." — `ws1-hudi-rs/8948bff2`
- "update relevant tracking doc please about my questions we discussed and action taken" — `ws2/c801b58c`
→ **Durable home:** the `WORKSPACE-AND-HANDOFF-ROUTINE.md` (sibling doc) + a CLAUDE.md rule: all adhoc docs/artifacts/scripts/progress/PR-links live under `operations/tasks/quantonMORScanSupport/tasks/<date-slug>/`, updated continuously.

## 4. PR descriptions — fixed template: What changed / How tested / Out-of-Scope
**Signal: ~3-4 sessions (hudi-rs).**
- "please revise the 2 PR description - what's the change - how it is tested" — `ws2-hudi-rs-internal/c72512a0`
- "in the PR description please have a section 'Out of Scope' mentioning the work done in the checkpoint." — `ws1-hudi-rs-internal/4e927612`
- "update the PR description about the data type coverage … share the hudi branch name + test name" — `ws3-hudi-rs-internal/468ab00b`
→ **Durable home:** a PR-description template (skill or repo `.github/PULL_REQUEST_TEMPLATE`).

## 5. RCA rigor — pinpoint the EXACT code, raw logs only, zero hand-waving, root cause before fix
**Signal: very high — all 3 minings; once enforced via a session Stop hook.**
- "pinpoint the exact unmerged code causing this please" / "must pinpoint the exact code change … why main branch does not hit the issue but the feature branch needs workaround" (Stop-hook) — `ws1/ab86868b`
- "compile a RCA report where I only expect script/test/github CI raw logs, raw code pieces analysis with zero hand waving / unverified assumptions." — `ws2/3967dd59`, `ws2/62eccd9a`
- "you should only rely on log to walk through the code, no assumption involved" — `ws3-hudi-internal/39b6d4d7`, `9cde38b8`
- "ALWAYS find root cause before attempting fixes." — `ws1/1b3643d6`
→ **Durable home:** the RCA routine (`ANALYSIS-process-retrospective.md`) + memory `rca-guidelines-measure-dont-theorize`. Conclude RCA with a UT reproducing the same log pattern where possible.

## 6. Reproduce in the real / CI-identical container before theorizing; green CI ≠ root cause
**Signal: high — ~9 sessions + hudi-internal.**
- "Always start with setting up the same env and repro locally." — `ws2/62eccd9a`, `ws2/c801b58c`, `ws2/3967dd59`
- "could you tests these as much as possible locally setting up a similar env" — `ws2/f223d878`
- "can we run in a docker container the same where the gluten velox c++ is built? I'm worried about the mismatch between … compiled v.s. execution" — `ws2-hudi-internal/386b80d7`
- "use ~/ws1 and ~/ws3, you can mount docker containers … (clear the existing build artifacts first)" — `ws2/62eccd9a`
→ **Durable home:** CLAUDE.md RCA tactic; matches `rca-guidelines-measure-dont-theorize` (G1/G7).

## 7. Isolate pre-existing vs. introduced — toggle the feature flag OFF / baseline on vanilla
**Signal: high — ~12 sessions (often "MOR=OFF" / "feature OFF" / "vanilla Java").**
- "turn off enable mor scan so hudi rs code and related velox integration code are not compiled at all … confirm it compiles and no hudi-rs/velox integration compiled" — `ws2/62eccd9a`, `c801b58c`
- "get a green run using hudi java no gluten" — `ws2-hudi-internal/2ac7b9b2`
- "Run new test suite on vanilla Java Hudi" (to isolate pre-existing) — `ws3-hudi-internal/26ecbb7f`
→ **Durable home:** CLAUDE.md RCA tactic + the minimum-diff A/B pattern in the RCA routine.

## 8. Parallelize fix exploration — raise multiple PRs and let runners race; don't serialize
**Signal: ~7 sessions.**
- "If you have multiple fix ideas … try them in parallel by raising multiple PRs and let github runners to run them." — `ws2/3967dd59`, `62eccd9a`, `c801b58c`
- "could you fire a parallel PR that also include dim3 fixes, so we don't wait on dim2 fix alone" — `ws1/ab86868b`
- "You can raise multiple PRs to run github CI exploring multiple configs in parallel, don't serialize." — `ws2/f223d878`
→ **Durable home:** CLAUDE.md tactic ("≥2 hypotheses → a PR each; race them on CI").

## 9. Run tests through the canonical `prompts/` scripts — never hand-roll mvn
**Signal: very high in hudi-internal/hudi-rs — ~9+ turns, every session.**
- "if it is scala test …/prompts/runhudiscala if it is java test …/prompts/runHudiJava" — `ws3-hudi-internal/9cde38b8`
- "refer …/runHudiJava …/runhudiscala to run with java instead of gluten velox, don't add -Dgluten.bundle.jar" — `ws3-hudi-internal/2ad75246`
- "fix and run …/prompts/runschemaEvo.sh so that it runs all the target tests effectively and all green" — `ws2-hudi-rs-internal/2ac7b9b2`
- "Moving forward when I ask about the test coverage, I mean the tests exercised in hudi rs UTs and those in these scripts runJavaTests.sh / runScalaTests.sh / runschemaEvo.sh" — `ws3-hudi-rs-internal/174ff128`, `468ab00b`
→ **Durable home:** CLAUDE.md rule. Gluten mode = pass the bundle jar; Java/vanilla = OMIT `-Dgluten.bundle.jar`. Scripts run async → **poll the log files** for BUILD SUCCESS/FAILURE, don't race process exit.

## 10. Prove the offload actually ran — hudi-rs log/dumpstream markers; negative test for no-offload
**Signal: ~4 sessions + standing memory.**
- "when you run the hudi e2e tests, make sure you find hudi rs related logs to prove the offload did happen." — `ws2/c9e53fee`
- "functional wise the functional tests should pass and properly offload hudi scan to hudi rs by checking the rs log" — `ws2/bf724092`
- negative test: `useJavaReader=true` → "validate scan is not offloaded to hudi rs" — `ws2/bf724092`
→ **Durable home:** verification step in the functional-test flow; matches memory `hudi-rs-offload-proof-markers`. A passing test that silently fell back to the JVM reader is **not** acceptance.

## 11. Definition of done — PR comments addressed + local functional green + required CI dims + all UTs green
**Signal: very high — ~12 sessions (gluten/velox) + ~7 (hudi-rs).**
- "Keep iterating until PR comments are addressed, local hudi functional tests are green, and github CI required test dimensions are cleared." — `ws2/62eccd9a`, `bf724092`, `c801b58c`
- "green CI and locally all hudi core and fg reader and C++ fg read API related tests should be all green." — `ws3-hudi-rs-internal/fc50aebd`
- "just make sure 32-34 PR CIs are all green." — `ws3-hudi-rs/1f0c2cc0`
→ **Durable home:** a "definition of done" checklist in the workspace `CHARTER`/acceptance doc.

## 12. Code review before push — code-review superpower + self-review vs `codeQuality/guide.md`
**Signal: ~7 sessions.**
- "trigger code review superpower, self review the code and address comments, then update remote branches" — `ws2/28a28034`, `c2f7699c`, `bf724092`
- "use code review superpower + …/0606-1-productquality/codeQuality/guide.md." — `ws2/7389eccc`
- "make sure you run code review super power skills, trim verbose comments, rebuild and run the same functional validation" — `ws2/bf724092`
→ **Durable home:** CLAUDE.md rule; review priority = **CLAUDE.md code quality > hudi-internal gold parity > general heuristics** (`ws2-hudi-rs-internal/b0f963f1`).

## 13. Gold parity — hudi-internal Java is the source of truth; divergence = bug (fix+test) or documented
**Signal: ~5 sessions (hudi-rs) + design rule (hudi-internal).**
- "refer hudi-internal and check code changes … strictly aligned with the java implementations" — `ws2-hudi-rs-internal/b0f963f1`, `e86bebd9`
- "let's fix this difference and add test coverage" / "add test and document what's gold validation would be different" — `ws2-hudi-rs-internal/b0f963f1`
- design: "explicitly callout what are the deviations we will end up with against gold. Each deviation should have an example schema evo walk through" — `ws3-hudi-internal/8937e4e7`
→ **Durable home:** CLAUDE.md / review-skill rule.

## 14. Coverage claims must be evidence-rooted — concrete fixture/test, type present in the LOG block, full-space gap report
**Signal: ~4 sessions (a re-asked verbatim across two).**
- "root our type coverage claim on concrete type / test validations … then compare against all possible types … and report what's missing" — `ws3-hudi-rs-internal/468ab00b`
- "be clear on if we have the data type in any of the LOG files (not just the final merge result)" — `ws3-hudi-rs-internal/174ff128`
- "unpack each log file and ensure we cover the target data types … compile me a summary … revise the test to fix gaps" — `ws3-hudi-internal/26ecbb7f`
→ **Durable home:** a coverage-audit checklist. Exclude types gold fixtures can't produce; e2e fixtures come from real gold-Java-generated file groups.

## 15. Silent correctness drops must ERROR, never no-op (filters / projection / precombine)
**Signal: ~2 sessions (multiple sub-items).**
- "do close up review of all pushdown drop cases and we should error out for all of them … could lead to correctness issues." — `ws3-hudi-rs-internal/709b70c7`
- "Composite (multi-field) precombine silently uses only the first field — should raise ERROR" — `ws3-hudi-rs-internal/709b70c7`
→ **Durable home:** CLAUDE.md correctness rule.

## 16. Branch & PR-stack hygiene — branch off stable, commit local-first, push on instruction; split by DAG, rebase downstream
**Signal: ~6 sessions (push policy) + ~5 (stack hygiene).**
- "work on a separate branch on top until you verified everything all green before touching the stable mor_productionization base branch." — `ws2/3967dd59`
- "Don't push to remote." ↔ "just commit and push to remote branch. I will verify them later" — `ws2/c801b58c`, `f223d878` ↔ `ws2/bf724092`
- "figure out the dependency DAG of the new code and gradually introduce classes from leaf to parent." — `ws3-hudi-rs-internal/389e6397`
- "break #34 into smaller ones while upstream/downstream PRs are intact … Make sure downstream PRs are rebased on the new PR stack" — `ws3-hudi-rs-internal/fc50aebd`
→ **Durable home:** CLAUDE.md + PR-stack convention. (Consistent with harness default "push only when asked.")

## 17. Keep the 5-repo branch tuple aligned to the clean-run tuple; land on the named feature branch, not the production base
**Signal: ~4 sessions (esp. ws2-hudi-internal/386b80d7).**
- "use the same gluten, velox, hudi rs branch as locally where we got the clean run. Ensure CI use the right dependency …" — `ws2-hudi-internal/386b80d7`
- "restore ENG-24823-production-base back to the old state - land the ci change on the rebased feat/schema-on-write-evo branch" — `ws2-hudi-internal/386b80d7`
→ **Durable home:** the workspace `STATE.md` (branch tuple) + a CLAUDE.md rule; rebase onto latest parent before validating.

## 18. Toolchain & build recipe — JDK 11 build / JDK 17 run; offline maven `-o`; cap cores
**Signal: ~2 sessions this week + standing memory.**
- "hudi internal build with java 11, run it with java 17 as runJavaTests.sh showed" — quoted in `ws2/f223d878`
- offline `mvn … -o` against populated `~/.m2`; `taskset -c 0-15 mvn -T 8 …` — `ws2/c801b58c`, memory `gluten-hudi-module-build-cmd`
→ **Durable home:** consolidate into one build-recipe block (CLAUDE.md / RUNBOOK); matches memories `gluten-hudi-module-build-cmd`, `gluten-native-logs-dumpstream`.

## 19. Test infra — GlutenTestUtils for SparkContext+configs; persistent table path for debug; fix broken scripts
**Signal: ~4 sessions each (hudi-internal).**
- "the spark context used we should apply GlutenTestUtils" / put `parquet.avro.write-old-list-structure=false` there — `ws3-hudi-internal/2ad75246`, `26ecbb7f`
- "create hudi table under a designated path, so it is not cleaned up … rerun only that test and get the test log specific to that test run" — `ws3-hudi-internal/39b6d4d7`, `9cde38b8`
- "If you find the test script not working properly, you should always fix it" — quoted in `ws2/f223d878`
→ **Durable home:** test-harness conventions doc / RUNBOOK.

## 20. Scope guards (project-specific)
**Signal: high but project-bound — several sessions per guard.**
- **Supported matrix:** "we only care v9, MOR, commit time ordering" + schema-on-**write** backward-compatible on the gluten side (`ws3-hudi-internal/8937e4e7`); the hudi-rs `HoodieFileGroupReader` path is scoped to "MOR v9, commit time ordering, **schema-on-read support**, parquet base file + avro log + c++ binding" (`ws3-hudi-rs-internal/709b70c7`). *(Note the deliberate split: gluten offload = schema-on-write; the rs reader supports schema-on-read internally. Keep both, don't conflate.)* Coerce or skip non-conforming test tables.
- **Don't re-flag sanctioned gaps:** bootstrap, non-COMMIT_TIME merge modes, position-based merge, spillable map, partial/CDC/HFile blocks, lazy-iterator — "all gated loudly or deferred." — `ws2-hudi-rs-internal/c72512a0`
- **x86 only; ARM out of scope.** — `ws2/62eccd9a`, `c801b58c`
- **Architecture:** "gluten should not have hudi 1.x dependencies except gluten hudi-1.x module"; "We should not fallback for COW"; fallback detection from **table properties + active timeline only — checking data files is banned**. — `ws2/7389eccc`
- **arrow-rs fork:** reuse-first, "only very minimum exposure of extra arrow-rs internal classes." — `ws1-hudi-rs/8948bff2`
→ **Durable home:** the per-effort `CHARTER.md` (scope IN/OUT + sanctioned-gaps list); the architectural invariants belong in a **project CLAUDE.md**.

## 21. Autonomous-session etiquette + tooling housekeeping
- Autonomous session = open/push PRs but **never self-merge**; leave OPEN for human review. — `ws3-hudi-rs/1f0c2cc0`
- Python tooling in a venv under `~/python/`; group helper scripts in a documented subfolder with a README; fold working commands back into `prompts/`. — `ws3-hudi-internal/26ecbb7f`
- Recurring environmental friction (candidates for a bootstrap doc, not yet a rule): AWS CodeArtifact creds were re-pasted ~8×; keeping sessions alive across SSH via `screen`.

---

## §10 — Candidate always/never rules (drop-in for a skill or CLAUDE.md)

- ALWAYS operate autonomously given acceptance criteria; NEVER pause for design/plan/clarification approval (keep the new-work design gate only).
- ALWAYS run non-trivial work as superpowers **brainstorm → writing-plans → subagent-driven execution**, looping to acceptance; execute end-to-end, no "should I continue?" pauses.
- ALWAYS keep the designated `operations/tasks/quantonMORScanSupport/tasks/<slug>/` workspace current as you go: progress, decisions, repro, gaps, PR-stack links.
- ALWAYS write PR descriptions as **What changed / How tested (cite hudi branch + test names) / Out of Scope**.
- NEVER propose a fix before a log-based RCA that pinpoints the EXACT file/commit/line, backed by raw logs/code — NEVER hand-wave to "environmental"/"toolchain"/"emergent"; green CI ≠ root cause.
- ALWAYS reproduce in the real / CI-identical container first (use `~/ws1`/`~/ws3` docker mounts for alt toolchains; clear artifacts first).
- ALWAYS isolate pre-existing vs. introduced by toggling the feature/MOR flag OFF (or baselining on vanilla Java) before attributing blame.
- When you have ≥2 fix hypotheses, raise a PR per idea and race them on CI — NEVER serialize.
- ALWAYS run Hudi tests through the `prompts/` scripts (runHudiJava, runhudiscala, runschemaEvo.sh, runJavaTests.sh, runScalaTests.sh); NEVER hand-roll mvn. Gluten mode passes the bundle jar; vanilla OMITS `-Dgluten.bundle.jar`. Poll the log files for SUCCESS/FAILURE (scripts are async).
- ALWAYS prove the native MOR offload ran via hudi-rs log/dumpstream markers; for `useJavaReader=true`, prove it did NOT offload. Silent JVM fallback is not acceptance.
- DONE = PR comments addressed AND local functional green AND required CI dims cleared AND hudi-core + fg-reader + C++ FG-read API UTs green (locally and on CI).
- ALWAYS run code-review superpower + self-review vs `codeQuality/guide.md` before push; trim verbose comments; rebuild + revalidate. Review priority: CLAUDE.md code quality > hudi-internal gold parity > general heuristics.
- ALWAYS treat hudi-internal Java as gold; any divergence is a bug — fix + add a test, or document why gold differs (with a worked schema-evo example in design).
- NEVER claim coverage abstractly — cite the fixture/test, prove the type is in the LOG block (not just merged output), enumerate the full type space, report the gap (excluding gold-unproducible cases).
- NEVER let an unsupported filter/projection/precombine case silently no-op — raise an explicit ERROR.
- ALWAYS branch off the stable base, commit local-first, and push ONLY when told or when a green batch is ready; NEVER touch the stable base until verified green.
- ALWAYS split large PRs by dependency DAG (leaf→parent), one concern per PR; rebase the entire downstream stack and force-push; keep the stack contiguous.
- ALWAYS pin the gluten/velox/hudi-rs/hudi-internal/arrow-rs branch tuple to the clean-run tuple; land on the named feature branch (never the production base); rebase onto latest parent before validating.
- Build Hudi with JDK 11, run tests with JDK 17; use offline maven (`-o`) against `~/.m2`; cap cores (`taskset -c 0-15 … -T 8`).
- Route the test SparkContext through GlutenTestUtils; for debugging, write the table to a persistent path and run only the failing test, then revert to auto-temp. Fix broken test/build scripts rather than working around them.
- SCOPE: MOR v9 + commit-time ordering + (gluten) schema-on-write / (hudi-rs reader) schema-on-read + parquet base + avro log + C++ binding only; coerce or skip the rest. NEVER re-flag sanctioned gaps. x86 only (ARM out of scope). No hudi-1.x deps outside `gluten-hudi-1x`; no COW fallback; fallback detection from table properties + active timeline only (data-file checks banned). arrow-rs: reuse-first, minimal new exposure.
- Autonomous session: open/push PRs but NEVER self-merge — leave OPEN for human review.
- Put Python tooling in a venv under `~/python/`, grouped in a documented subfolder; fold working commands back into the `prompts/` scripts.

---

## Conflicts / nuances to resolve when turning these into rules
- **Push policy is conditional**, not absolute: default is commit-local-first + push-when-told; the user sometimes says "just push, I'll verify later" and sometimes "don't push." Encode as "push only on explicit instruction or an agreed green-batch," not a hard always/never.
- **schema-on-write vs schema-on-read** is a deliberate split (gluten offload side vs. the rs FileGroupReader's internal support) — do not collapse into one statement.
- **Local-vs-CI test loop** (rule 6 vs. the occasional "don't verify locally, just launch a PR"): pick by failure class — build/linkage/toolchain → local container; true multi-process/JVM-runtime teardown → CI (matches RCA routine G7).
