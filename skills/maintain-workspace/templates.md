# Effort Workspace — File Templates

Copy these when bootstrapping an effort folder. Fill the angle-bracket placeholders.
See `SKILL.md` for the invariants, layout, and resume contract these templates serve.

---

## `HANDOFF.md` — the entry point (current state + handoff; the only doc allowed to rot)

Two clearly-headed parts in one file: **(A) Current state** (what-code-where + how-built — absorbs the old STATE.md) and **(B) Handoff** (the explicit pickup guide). One reconciled doc, so "status" and "how to pick up" can't drift apart.

```markdown
# <Effort> — HANDOFF   (read me first)
Updated: <date> by session <latest-uuid>  |  Status: LIVE (current state + handoff; rots — reconcile to DECISIONS)

# ===== PART A · CURRENT STATE =====

## Where we are (one paragraph)
<2-4 sentences: what's delivered, what's in flight, the single next action.>

## Live snapshot (volatile — dated)
- In flight: <CI run id / build / watcher> — expected: <green-set / criterion>
- Blockers: <…>

## PR / branch stack   (REQUIRED slot — must exist even for a single PR; the ONE home for the stack)
| Repo | Branch | Tip githash | PR (full-URL link) | CI (PR checks page → latest run) | Contents |
|------|--------|-------------|--------------------|----------------------------------|----------|
| gluten-internal | mor_productionization | c879c42da | [#360](https://github.com/<org>/gluten-internal/pull/360) | [#360 checks](https://github.com/<org>/gluten-internal/pull/360/checks) — green 2026-06-15 ([run 27443719426](https://github.com/<org>/gluten-internal/actions/runs/27443719426)) | … |
| velox-internal  | mor_productionization | …         | [#128](https://github.com/<org>/velox-internal/pull/128) | [#128 checks](https://github.com/<org>/velox-internal/pull/128/checks) — pending | … |

**REQUIRED cell format — a bare id is INCOMPLETE:** PR = full-URL link `[#N](…/pull/N)` (branch with no PR yet → `branch only (no PR yet)`, never blank/bare `#N`); CI = the PR's **checks page** `[#N checks](…/pull/N/checks)` + dated conclusion (+ optional `[run <id>](…/actions/runs/<id>)`), never a bare run-id.

## How each artifact was built & tested (REVIEWER GUIDE — note steps as you dev, distil over time)
The narrative a reviewer needs — NOT the commands (those are RUNBOOK; link to them). One entry per artifact:
### <artifact, e.g. the fixed operator image>
- **What it is / vs baseline:** `<tag@digest>` = `<derivation>`; baseline (unfixed) = `<tag@digest>` (the RED/before run).
- **Built by:** `<automated step>` → `<where published>`. Needs: `<preconditions>`.
- **Provenance:** `<run/job link>` @ `<commit>` → `<exact version>` (`<digest>`) — the audit chain.
- **Assembled by:** `<script/one-command>` (→ RUNBOOK §… for the command).
- **Tested by / used where:** `<milestone/test that used this exact version>` → proof in `evidence/INDEX.md` #<n>.
- **Caveats:** `<lineage / arch / not-run-here notes>`.

## Working set (what to check out to get the latest)
- gluten: <branch@sha>   velox: <branch@sha>   …    ## Published artifacts: <codeartifact pkg @ version>

# ===== PART B · HANDOFF (pickup guide) =====

## Resume here
- Workspace folder (where the code is checked out): `~/ws2`   # which of ~/ws1·ws2·ws3·…
- Resume the latest session:  `cd ~/ws2 && claude --resume <latest-uuid>`
- Repo checkouts used: gluten=`~/ws2/gluten-internal` · velox=`~/ws2/velox-internal` · …

## Next action (the very next thing to do)
1. <concrete step + the command or PR to look at>

## Setup you end up with (delivered handoff — point, don't duplicate)
- **PR stack:** see the PR/branch table in Part A (don't re-paste it).
- **Artifacts + how they were built:** see Part A § "How each artifact was built & tested".
- **Play with it:** <one-command scripts> → see RUNBOOK.md § <section> (don't re-paste commands here).
- **Proof each acceptance criterion is met:** AC-1 → evidence/INDEX #<n> · AC-2 → #<n> · … (INDEX maps criterion→artifact→source→regenerate).

## Session log  (append one row per session — so ANY past session is resumable)
| Date | Workspace | Resume cmd | Did what |
|------|-----------|------------|----------|
| 2026-06-15 | ~/ws2 | `cd ~/ws2 && claude --resume f223d878-…` | libstdc++ fix shipped green ([#360](https://github.com/<org>/gluten-internal/pull/360)); wrote routine |
| 2026-06-12 | ~/ws2 | `cd ~/ws2 && claude --resume c801b58c-…` | M1 concluded; M2 x86 baseline captured |

## Index (where each thing lives — click through, don't duplicate)
- Scope / acceptance / constraints → CHARTER.md
- PR & branch stack + **how each artifact was built & tested** → Part A above
- Runnable commands to rebuild / rerun tests / repro → RUNBOOK.md
- Decisions → DECISIONS.md · Issues → ISSUES.md · Unverified assumptions → ASSUMPTIONS.md
- Deep dives → investigations/<topic>/
```

**Why both the folder AND the uuid:** the same effort is worked from different checkouts across sessions (ws1/ws2/ws3 may run concurrently), and `claude --resume <uuid>` only attaches the conversation — it does NOT restore the working directory. You must `cd` into the recorded workspace first or the resumed session operates on the wrong tree. The session log keeps every past session resumable (a single "Resume:" line loses all but the latest). Claude transcripts live under `~/.claude/projects/-home-ubuntu-ws<N>…/` — the dir name encodes the workspace folder, which is why recording the folder matters.

---

## `CHARTER.md` — durable, the anti-re-paste card (organized as the instant lifecycle)

```markdown
# <Effort> — CHARTER   (durable; edit deliberately)
Instant: <base_instant>-<curr_instant>-<state>-<opType>-<instantName>

## Goal (e2e)
<the end state, in your partner's words>

## Setup to begin with
<the starting state this instant forks from>
- Base instant: <main | parent curr_instant>   # mirrors base_instant in the folder name
- Branches / checkouts at start: <Empty | e.g. gluten=mor_prod@c879c42, velox=mor_prod@…>

## First 3 raw prompts (verbatim — the partner's original framing)
1. > <first prompt, exactly as sent>
2. > <second prompt>
3. > <third prompt>

## Scope
- IN:  <e.g. Hudi MOR v9, commit-time ordering, schema-on-write only>
- OUT: <e.g. schema-on-read, position-based, python/datafusion, ARM dims>

## Acceptance criteria (NL → executable proof → self-review)
Each criterion is proven by the CODE ITSELF put to execution — a green test run, a
script that greps for a beacon runtime log, or a GitHub CI run — not by assertion.
Brainstorm (superpowers:brainstorming) to sharpen any vague criterion. Keep the
self-review current as evidence accrues.

### AC-1 <short name>
- [ ] Statement (NL): <what must be true, in plain language>
- Proof (executable): <green test X | `grep 'read_file_slice returned OK' <log>` | [CI run](…/actions/runs/<id>)>
- Self-review: <does the evidence in evidence/INDEX.md actually fulfill this yet? gaps?>

### AC-2 <short name>
- [ ] Statement (NL): <…>
- Proof (executable): <…>
- Self-review: <…>

## Setup to end up with (the handoff)
- Deliverables: <PRs (links); test-run links showing the beacon log; images; jars + where
  to fetch them; code-investigation summary; RCA doc (link)>
- Reproducible stack (trivial to run — a few cmds + grep, at most):
  <PR stack; build scripts; scripts that exercise the requirements; artifacts + their
  location — all pointered from RUNBOOK.md / evidence/INDEX.md>

## Standing constraints / rules
- <e.g. M1 must stay green>
- <e.g. use ≤16 cores: taskset -c 0-15 / -j16 / -T 8>
- <e.g. detection from table-config only>
- <e.g. don't ask permission; subagent-driven mode>

## Environment
- Box: <cores/mem>; Images: <build/runtime tags>; Toolchain: <…>
- Credentials bootstrap: <how to get creds — a pointer, NOT the secret>
```

---

## `DECISIONS.md` — the decision register (one section per decision, the authoritative timeline)

Append-only. Each decision is its own section with rationale subsections — NOT a one-line row. A superseded
decision is never deleted or rewritten: set its Status to `SUPERSEDED by D-<n>` and add the new section. This
register is the **tie-breaker** when the living docs (HANDOFF/RUNBOOK) disagree — the latest ACTIVE entry wins.

```markdown
# DECISIONS   (durable; append-only register; the authoritative decision timeline / tie-breaker)

## D-1 — <short imperative title>   (<date>, ACTIVE)
### Context
<the situation/problem that forced a choice — what was ambiguous or blocked, the constraints in play.>
### Decision
<what we chose, stated so a cold reader can act on it — exact ref/flag/path where relevant.>
### Rationale
<why this option; the key evidence or principle. Name the alternatives considered and why they lost.>
### Consequences
<what this changes downstream — new work enabled/blocked, follow-ups, risks accepted. Link ISSUES if it opened one.>

## D-2 — <next decision>   (<date>, SUPERSEDED by D-5 2026-07-18)
### Context
<…>
### Decision
<the choice as originally made — left intact for the record.>
### Rationale
<…>
### Consequences
<…>
```

**Status vocabulary:** `ACTIVE` · `SUPERSEDED by D-<n> (<date>)`. Keep volatile state (CI run-ids, "in progress") OUT — that belongs in HANDOFF's current-state snapshot.

---

## `RUNBOOK.md` — how to play with it (commands live here, not in prose)

RUNBOOK is a LIVING doc: keep exactly ONE current recipe per task. When the recipe changes, edit it in place
and move the old one under a `## Superseded (HISTORICAL — do NOT run)` heading with a one-line reason + the
DECISIONS ref — never leave two co-equal recipes for a resumer to pick wrong from.

````markdown
# <Effort> — RUNBOOK
## Build (exact, copy-paste; the recipe you keep re-pasting)
```bash
WS=$(pwd); cargo build -p hudi-cpp …; <build velox>; <build gluten>; <mvn package>
```
## Run validation
```bash
prompts/runJavaTests.sh … ; prompts/runScalaTests.sh … ; prompts/runschemaEvo.sh …
```
## Prove it actually ran (not a fallback)
- grep the surefire `*.dumpstream` for: `read_file_slice returned OK`, `arrowStream=`,
  `Building HiveHudiMORSplit`.
## Reproduce the known gap / repro env
- <docker image + flags that match CI exactly>; logs land in evidence/.
````

---

## `ISSUES.md` — one sub-section per issue (prose, NOT a table)

Tables are hostile to the bulk text an issue needs (multi-line symptoms, a real RCA).
Each issue is its own sub-section with a stable ID; the register starts empty and
appends as you go — never rewrite history, add follow-up under the same issue.

```markdown
# ISSUES   (durable; append-only; one sub-section per issue)

## OI-11 gcc-toolset-11 cxx Slice element_type
### Symptom
<what was observed — error text, failing test, the surprising behavior. Bulk text OK.>
### Root cause
<the underlying cause. If deep, keep this to a line and link the full RCA:
see investigations/slice-elementtype/analysis.md>
### Action taken
<what was done: workaround, patch (PR link), config change, or "none yet">
### Status
DEFERRED — tracked as [ENG-43030](https://…/ENG-43030)

## OI-12 <next issue title>
### Symptom
<…>
### Root cause
<…>
### Action taken
<…>
### Status
OPEN — unchecked
```

**Status vocabulary:** `OPEN` (seen, unchecked) · `FIXED` · `DEFERRED` (won't tackle now, tracked) · `DOCUMENTED` (known, accepted). Link the ticket as a full URL, never a bare id.

---

## `ASSUMPTIONS.md` — the unverified-beliefs register (stable IDs + status)

```markdown
# ASSUMPTIONS   (the unverified-beliefs register; append, don't rewrite)
| ID | Assumption (believed, not yet proven) | Status | Evidence / next check |
|----|---------------------------------------|--------|-----------------------|
| AS-1 | "ship our own libstdc++.so.6" is possible on centos-7 | REFUTED 06-12 | devtoolset ships only static archives → evidence/2026-06-12-local-validation-findings.md |
| AS-3 | testSecondaryIndexCreation failure is pre-existing | VERIFIED 06-11 | also fails vanilla (no gluten) |
```

**Status vocabulary:** `OPEN` (believed, unchecked) · `VERIFIED` · `REFUTED` · `SANCTIONED` (known risk, accepted by your partner) · `DEFERRED` (won't check now, tracked).

---

## `evidence/INDEX.md` — proof, indexed (every "it's green" cites a row here)

```markdown
# Evidence index — acceptance criteria → artifact → source
Updated: <date>

| # | Criterion | Artifact (this folder) | What it shows | Source (job/run/commit — link, not bare id) |
|---|-----------|------------------------|---------------|---------------------------------------------|
| 1 | <criterion 1> | `<file>` | <one line> | [run <id>](https://github.com/<org>/<repo>/actions/runs/<id>) |
| 2 | <criterion 2> | `<file>` | <one line> | <command @ commit> |

## How to regenerate each artifact
- `<file>`: `<one-line command that re-produces it>`
- `<proof>`: re-run <mode> (see ../RUNBOOK.md modes matrix), then `scripts/validate_<x>.sh <logdir>`.
```

The full raw run/job records (params, logs, repro) are the primary data points — link them from here;
bulky raw logs may be gitignored if the index says how to re-pull them while they still exist upstream.

---

## Multi-mode? Add a modes matrix to `RUNBOOK.md` (NOT a new `CAPABILITIES.md`)

When the deliverable has more than one mode/config, RUNBOOK gains a small table near the top — it's
still "how to run it", just made multi-mode. One fact, one home (invariant 3).

```markdown
## Modes (one harness, selected by profile/flag)
| Mode | Select | Key config | Proven by (job / run, linked) → evidence |
|------|--------|------------|------------------------------------------|
| <default> | `<profile/command>`        | <…> | [run <id>](…/actions/runs/<id>) → `evidence/<file>` |
| <variant> | `<profile/command + flag>` | <…> | [run <id>](…/actions/runs/<id>) → `evidence/<file>` |
```

Then the per-mode copy/paste commands and the "reproduce any past run" one-liner go in RUNBOOK's
existing Build/Run sections — not a separate doc.

---

## `COMPACTED.md` — metadata for a `…-compact-…` instant (compact instants ONLY)

Written by `/maintain-workspace compact`. The full compaction recipe **and** the
`COMPACTED.md` template (with its four required slots — stacked PR chain · merged
acceptance all-MET · evidence disposition · lingering-issue reconciliation) live in
**`compaction.md`** in this skill directory. Copy the template from there — it is
kept in one home so the recipe and its slots never drift.

---

## `REVIEW.md` — the review ledger (append-only; written by the reviewer, not by hand)

Bootstrapped on the first review round and appended to thereafter by
**`superpowers:reviewing-workspace`** (command `/review-workspace`). It is the audit
trail of every review round — findings, their status, and the action taken. The full
template lives in **`../reviewing-workspace/templates/REVIEW.md`** (one home, so the
ledger format and the reviewer that writes it never drift). Copy it from there. Never
rewrite a past finding — supersede its `Status` in place with a dated note.
