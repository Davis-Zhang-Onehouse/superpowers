# {{TITLE}} — CHARTER   (durable; edit deliberately)
Instant: {{CHILD_NAME}}
Updated: {{TODAY}} | Status: DURABLE
Dispatched by parallelDispatch from base instant: {{BASE_NAME}}

## Goal (e2e — in one sentence)
Deliver the **same deliverable shape as the ANSI baseline** (a healthy RC gold workspace + a Spark-4.x ANSI CI
run + a classified ANSI-gap `CATALOG.md`) **but make it provably COMPLETE**: prove that **no ANSI fallback
survives and no ANSI gap stays hidden**, correct the catalog with whatever that surfaces, and hand a catalog
that is a *provably-exhaustive* base for downstream ANSI-offload fix work.

## THIS INSTANT'S JOB IS EXPOSURE / COMPLETENESS — **NOT** FIXING GAPS
> Read this before anything else. Do **NOT** fix ANSI gaps here. You EXPOSE them, PROVE the exposure is
> complete, and CLASSIFY them. Closing a gap (offload/translate a native op, change gluten/velox behavior so a
> failing ANSI test goes green) is the job of the **downstream fix workers**, not you. If you find yourself
> writing a fix to make a red ANSI test green, STOP — that is out of scope. The one exception: instrumenting
> the build/tests purely to *observe* fallback (AC-3) is IN scope; changing product ANSI behavior is OUT.

## Two failure modes you must close (the governing frame — everything below serves these)
- **FM-A · Masking:** a code path runs with ANSI *off*, so a latent gap never triggers (suite bases; per-test
  `withSQLConf(ANSI_ENABLED->"false")`; the `nonansi/` `.sql` dir in `GlutenSQLQueryTestSuite`).
- **FM-B · Silent offload:** a path runs ANSI *on* but the op falls back to Spark for an unrelated validation
  reason, runs correctly under Spark's own ANSI, and the gap is never observed. This SURVIVES the fallback-rule
  removal and is invisible to any config audit — it is the deepest miss.
- **Principle:** convert both from *silent* to *loud* — instrument/enumerate so ANSI-off and ANSI-fallback
  become detectable signals; never conclude "no gap here" from a green run alone.

## Setup to begin with
- Base instant: {{BASE_CURR}}  (forked from {{BASE_NAME}} — the bulletin board; report back onto it).
- Workspace: {{WS}}  (slot {{SLOT}}, leased; a no-rebuild duplicate of golden {{GOLDEN}}).
  **Read ISSUES.md first** for any workspace caveat carried in at dispatch (e.g. a duplicate runpath note).
- The ANSI-fallback rule is `FallbackOnANSIMode` (`gluten-substrait/.../columnar/FallbackRules.scala`); its
  velox injection lives in `backends-velox/.../VeloxRuleApi.scala`; ANSI is forced on in the central test
  `SparkConf` bases (`WholeStageTransformerSuite`, `GlutenSQLTestsBaseTrait`); fallback observability =
  `GlutenFallbackReporter` / `GlutenExplainUtils` + the fallback-reason reporter config in `GlutenConfig`.
- GOLD Spark-Java reference source: `/home/ubuntu/davis_root/spark` — cite it for expected behavior
  (Spark-Java = GOLD vs Gluten-Velox = ACTUAL).

## Dispatch ask (context — the specifics for THIS run)
{{BRIEF}}

## Evidence pointers (start here)
{{EVIDENCE}}

## Scope
- **IN:** (AC-1) prove the fallback rule is dead+un-re-enableable on the velox path for all Spark-4.x shims;
  (AC-2) enumerate+classify every ANSI-off masking site; (AC-3) census every ANSI-mode fallback + prove none
  is ANSI-semantics-related; (AC-4) prove every spark-4.x velox suite runs ANSI-on; (AC-5) resolve the base
  catalog's needs-RCA tail to {gap|sanctioned|non-ANSI}; (AC-6) consolidate into ONE authoritative "0 hidden
  gaps" catalog, diffed vs the baseline; keep the baseline-shape deliverable (gold healthy + CI `--fail-never`
  + classified CATALOG).
- **OUT:** *fixing / closing* any ANSI gap (downstream fix workers own that); merging any PR (operator gate);
  ARM↔amd64 artifact interchange; non-ANSI functional gaps already ruled out; changing product ANSI behavior.

## Acceptance criteria (NL statement → executable proof → self-review). Critical path: AC-1 → {AC-2,AC-4} → AC-3 → AC-5 → AC-6.

### AC-1 — Removal integrity: the ANSI fallback is provably dead on the velox path
- [ ] Statement (NL): the `FallbackOnANSIMode` injection is removed and **un-re-enableable** on the velox path
      for **every** Spark-4.x shim; no other rule tags a plan for ANSI reasons; the ansi-fallback config is
      inert on velox (no live reader). Any non-velox backend that retains the injection is noted out-of-scope.
- Proof (executable): grep enumeration showing exactly one (removed) velox injection site + no live
      ansi-fallback-config reader on the velox path; a shim-diff showing the shims compile the same
      `VeloxRuleApi`. Cite file:line in `investigations/removal-integrity/analysis.md`.
- Self-review: _(worker fills — MET / partial, with evidence link)_

### AC-2 — Masking audit complete: every ANSI-off site enumerated + classified (closes FM-A)
- [ ] Statement (NL): every `ANSI_ENABLED->false` / `ansi.enabled=false` site in the `gluten-ut/spark4x` +
      `backends-velox` test trees is enumerated and classified `{sanctioned (ANSI-off by design) | hides-gap}`;
      **zero unclassified**; every hides-gap is promoted to a gap row. (Port the prior full-exposure
      hidden-gap-audit methodology — see evidence pointers.)
- Proof (executable): a `site (file:line) → what it disables → disposition` table in
      `investigations/masking-audit/analysis.md`, backed by the grep enumeration; ambiguous sites re-run
      locally ANSI-on to decide.
- Self-review: _(worker fills)_

### AC-3 — Fallback census: no ANSI-relevant fallback goes unaccounted (closes FM-B — the centerpiece)
- [ ] Statement (NL): across all spark-4.x dims, every plan node that fell back under ANSI is enumerated with
      its reason, and **no fallback reason is ANSI-semantics-related** (every fallback is a genuine
      unsupported-op, not an ANSI dodge). Any ANSI-relevant fallback found becomes a gap row.
- Proof (executable): a fallback census (built via `GlutenFallbackReporter` / `GlutenExplainUtils`
      `getFallbackSummary` + the fallback-reason reporter config) captured to evidence/;
      `investigations/fallback-census/analysis.md`. Start observational (post-run census); escalate to a strict
      "fail on ANSI-relevant expression fallback" hook on the arithmetic/cast/datetime suites where gaps
      concentrate. (Instrumenting to *observe* is IN scope; changing ANSI behavior is OUT.)
- Self-review: _(worker fills)_

### AC-4 — Enablement-coverage proof: every spark-4.x velox suite runs ANSI-on (hardens FM-A)
- [ ] Statement (NL): every spark-4.x velox test suite is mapped to an ANSI-on source (a base trait, the
      `.sql` self-enable, or a **verified** reliance on the Spark-4.x default — the default must be confirmed
      true in the shim, not assumed); zero suite runs ANSI-off unintentionally.
- Proof (executable): the inheritance sweep + the confirmed shim default in
      `investigations/enablement-coverage/analysis.md`; orphan suites (extending neither base) flagged and resolved.
- Self-review: _(worker fills)_

### AC-5 — needs-RCA tail resolved
- [ ] Statement (NL): every needs-RCA row carried from the base catalog (see the dispatch ask / evidence) is
      resolved to `{genuine ANSI gap (family) | sanctioned | non-ANSI}`, each with a cited artifact
      (systematic-debugging: Spark-Java=GOLD vs Gluten-Velox=ACTUAL); **zero** rows left needs-RCA.
- Proof (executable): per-item verdict + artifact in `investigations/needs-rca-tail/analysis.md`; local repro
      per item captured to evidence/ (NOT /tmp).
- Self-review: _(worker fills)_

### AC-6 — ONE authoritative "0 hidden ANSI gaps" catalog (the deliverable)
- [ ] Statement (NL): AC-1..AC-5 converge into a single `evidence/ansi-gap-catalog/CATALOG.md` = full
      family-classified gap set + sanctioned set (with reasons) + fallback-census summary + coverage proof +
      an explicit, linked statement **"no ANSI-off site and no ANSI-relevant fallback is unaccounted for."**
      Deliverable keeps the baseline shape: RC gold healthy + a Spark-4.x CI run (`--fail-never`, truth =
      downloaded surefire) + the classified catalog, **diffed vs the baseline** (ansi-ci-diff-catalog skill).
- Proof (executable): the catalog + its "Changes vs baseline" section + the CI run link (PR draft, **DO NOT MERGE**).
- Self-review: _(worker fills)_

## Standing constraints / rules
- **EXPOSURE ONLY — do not fix gaps** (see the boxed note above). Fixes belong to downstream fix workers.
- **RCA-for-classification:** use superpowers:systematic-debugging when deciding whether a masking site /
  fallback / needs-RCA row hides a real gap — Spark-Java=GOLD vs Gluten-Velox=ACTUAL, every causal claim tied
  to a **captured artifact** (evidence/, NEVER /tmp), not memory.
- **CI is rigged always-green (`--fail-never`) — truth = the downloaded surefire report ONLY.**
- **ARM:** audits (AC-1/AC-2/AC-4) are code/test-level (arch-agnostic); verification runs (AC-3/AC-5) are
  ARM-local for triage, but the **authoritative catalog comes from the amd64 in-container CI run** (ARM
  artifacts are NOT CI-interchangeable). Mind any ISSUES workspace caveat if a native rebuild is needed.
- **Do NOT merge PRs or close the effort without the operator** — park a `## Parked decision` block in HANDOFF.
- Maintain this instant per superpowers:maintain-workspace throughout (evidence in evidence/, not /tmp).
- Fact-grounded only: every verdict cites a raw artifact; every inference is labeled an assumption.
- **Autonomous-first:** run as far as you can (operator may be away up to 20h); park only at a genuine fork and
  keep working other unblocked ACs meanwhile.

## Setup to end up with (the handoff)
- Deliverables: the five audit docs (removal-integrity, masking-audit, fallback-census, enablement-coverage,
  needs-rca-tail) + the ONE authoritative catalog with the "0 hidden gaps" assertion + the CI run link (draft
  PR, not merged) + evidence/INDEX.md mapping each AC → artifact → source → regenerate.
- Reproducible: RUNBOOK has the audit grep one-liners, the local-repro commands, and the CI harvest.
- Report-back: transition this instant's folder state (inflight→complete/abort) at session end.

## Environment
- Box: aarch64 EC2. Spark 4.x → java-17 + scala-2.13. CI runner `arc-16-cores-ondemand-staging`.
- Golden: {{GOLDEN}}. JDK 17 = `/usr/lib/jvm/java-17-openjdk-amd64`.
