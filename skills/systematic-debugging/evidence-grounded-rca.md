# Evidence-Grounded RCA

## Overview

An RCA is only as trustworthy as the artifacts behind it. A causal chain built from memory, from reading a file once, or from "this probably happens" is a story — it reads convincingly and is wrong often enough to send fixes at the wrong layer.

**Core principle:** the symptom is a *captured artifact*, every link from symptom to root cause is either a **FACT** (cites a captured artifact by path + locator) or a flagged **ASSUMPTION** (belief + justification + how to verify), and the whole chain plus its artifacts is archived to a durable folder — never left in the chat transcript.

This is the technique behind Phase 1 of `systematic-debugging`. Use it for every RCA.

## Step 1 — Open the evidence store (decide location first)

Decide *where artifacts land before you capture the first one*. Two cases:

**A. An effort workspace is in use** (see `superpowers:maintain-workspace` — your partner pointed you at an instant folder; it has a `HANDOFF.md`). Use the instant's existing structure — do not invent a new one:

```
<instant>/evidence/               ← raw artifacts land here (invariant 4: never /tmp)
<instant>/evidence/INDEX.md        ← claim → artifact → source → how-to-regenerate
<instant>/investigations/<symptom>/analysis.md   ← the RCA report itself
```

Then add a sub-section to the instant's `ISSUES.md` (Symptom / Root cause / Action taken / Status) linking the RCA doc.

**B. No workspace** — archive to a dedicated folder (not scattered `/tmp` files that vanish on resume):

```bash
RCA_DIR=$(mktemp -d "${TMPDIR:-/tmp}/rca-<short-symptom-slug>-XXXXXX")
mkdir -p "$RCA_DIR/evidence"
echo "RCA workspace: $RCA_DIR"   # tell your partner the path
```

RCA report → `$RCA_DIR/analysis.md`; artifacts → `$RCA_DIR/evidence/`; index → `$RCA_DIR/evidence/INDEX.md`.

## Step 2 — Anchor the symptom to a raw artifact

The RCA starts from a symptom you can *point at*, not a paraphrase. Capture the artifact that defines the symptom, then quote the exact line.

```bash
# CI failure → capture the raw log, don't screenshot or paraphrase
gh run view 27443719426 --log-failed > "$EVID/ci-run-27443719426.log"   # provenance = run URL
# local test failure
./gradlew :mod:test 2>&1 | tee "$EVID/testrun-$(date +%Y%m%d-%H%M).log"
```

Symptom statement: `NullPointerException at resolveBasePath` — `evidence/ci-run-27443719426.log:6`.

## Step 3 — Capture every artifact as you touch it (with provenance)

**Reading an artifact is not capturing it.** If a claim will lean on something, copy that something into `evidence/` and record where it came from. An artifact with no provenance is a dead end on resume.

| Artifact type | Capture command | Provenance to record |
|---|---|---|
| GitHub CI / workflow logs | `gh run view <id> --log[-failed] > evidence/ci-<id>.log` | run URL |
| Test-run logs | `<test cmd> 2>&1 \| tee evidence/testrun-<date>.log` | command + commit |
| S3 objects / remote files | `aws s3 cp s3://… evidence/s3-<name>.json` | full URI + fetch date |
| Raw code pieces | `sed -n '200,230p' path > evidence/<file>-200-230.<ext>` | repo path + `git rev-parse HEAD` |
| Config / workflow yaml | copy the file into `evidence/` | repo path + commit |
| DB / API state | dump the query + its output to a file | query + timestamp |

Every captured artifact gets a row in `evidence/INDEX.md`:

```markdown
| Backs claim | Artifact | Source / provenance | Regenerate |
|---|---|---|---|
| symptom: NPE in resolveBasePath | evidence/ci-run-27443719426.log | [run 27443719426](https://…/actions/runs/27443719426) | `gh run view 27443719426 --log-failed` |
| S3 conf missing base.path key | evidence/s3-bootstrap-conf.json | `s3://hudi-ci-artifacts/${RUN_ID}/bootstrap-conf.json`, fetched 2026-07-14 | `aws s3 cp s3://… -` |
```

## Step 4 — Build the why-chain, one grounded node at a time

Five whys and more — keep asking "why" until a why lands on something you'd actually change. **Each node is exactly one of two shapes.** Nothing else is allowed in the chain.

```
Symptom  [FACT: evidence/ci-run-27443719426.log:6 — "NPE ... resolveBasePath(BootstrapConfig.java:214)"]
  └ Why 1: props.get("hoodie.bootstrap.base.path") returned null
      [FACT: evidence/BootstrapConfig-200-230.java:5 — `props.get(BASE_PATH_KEY).trim()`, no null guard]
    └ Why 2: the staged S3 conf has no base.path key
        [FACT: evidence/s3-bootstrap-conf.json — only scheme/mode/parallelism present]
      └ Why 3: the render step dropped it because it rendered empty
          [ASSUMPTION: the jq `select(.value != "")` compaction dropped an empty value.
           Justification: nightly-s3.yml shows that filter; key is absent not empty.
           VERIFY: capture the stage-conf job's rendered.json (before jq) from the run.  Status: OPEN]
        └ Why 4: BOOTSTRAP_BASE_PATH rendered empty because the repo variable was deleted
            [FACT: evidence/nightly-s3.yml:… — audit note: var deleted 2026-07-13 by svc-ci-admin]
  Root cause: deletion of repo variable BOOTSTRAP_BASE_PATH → empty render → key dropped → null → NPE.
```

**FACT node:** `[FACT: evidence/<file>:<locator> — "<quoted snippet>"]`. The artifact is captured (Step 3), cited by path + line/locator, and quoted. If you can't cite it, it is not a fact.

**ASSUMPTION node:** `[ASSUMPTION: <belief>. Justification: <why plausible>. VERIFY: <artifact/command that would confirm or refute>. Status: OPEN|CONFIRMED|REFUTED]`. State assumptions out loud — a justified, labeled assumption is legitimate; an unlabeled guess wearing a fact's clothes is the failure this technique exists to prevent. Convert to FACT by capturing the verifying artifact whenever the cost is reasonable; if you ship the RCA with it still OPEN, it must appear under Open Assumptions.

## Step 5 — Write the grounded RCA report

Write it to the durable location from Step 1 (`analysis.md`). Structure:

```markdown
# RCA: <symptom> (<run/date>)
Updated: <date> | Evidence: ./evidence/  (INDEX.md)

## Symptom        — the anchoring artifact + exact quote (evidence/…:line)
## Impact/scope   — what's broken, since when (cite the artifact showing "since when")
## Evidence index — link ./evidence/INDEX.md (claim → artifact → source → regenerate)
## Causal chain   — the Step-4 why-chain; every node FACT-cited or ASSUMPTION-flagged
## Root cause     — one statement, resting on the chain's terminal FACT(s)
## Open assumptions — every node still Status: OPEN, and what would close it
## Fix            — root-cause fix (→ systematic-debugging Phase 4); note rejected symptom fixes and why
```

The test: a cold reader opens `analysis.md`, follows each citation to a file in `evidence/`, and re-derives every claim without you in the room. If a claim has no artifact and isn't flagged as an assumption, the RCA is not done.

## Red flags

- About to write "the root cause is…" and no artifact is captured yet → capture first.
- A "why" you're stating from memory or from having read a file once → cite the captured artifact or flag it ASSUMPTION.
- "Reproduction/verification not needed, the artifacts explain it" — for any link you did NOT capture, that link is an assumption; label it, don't assert it.
- Artifacts read but `evidence/` is empty → you read, you didn't capture.
- The RCA lives only in your chat reply → write it to the durable folder.
