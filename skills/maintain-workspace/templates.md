# Effort Workspace — File Templates

Copy these when bootstrapping an effort folder. Fill the angle-bracket placeholders.
See `SKILL.md` for the invariants, layout, and resume contract these templates serve.

---

## `HANDOFF.md` — the entry point (the only doc allowed to rot)

```markdown
# <Effort> — HANDOFF   (read me first)

## Resume here
- Workspace folder (where the code is checked out): `~/ws2`   # which of ~/ws1·ws2·ws3·…
- Resume the latest session:  `cd ~/ws2 && claude --resume <latest-uuid>`
- Repo checkouts used: gluten=`~/ws2/gluten-internal` · velox=`~/ws2/velox-internal` · …
Updated: <date> by session <latest-uuid>  |  Status: LIVE SNAPSHOT (rots — verify against STATE/CI)

## Where we are (one paragraph)
<2-4 sentences: what's delivered, what's in flight, the single next action.>

## Next action (the very next thing to do)
1. <concrete step + the command or PR to look at>

## Live snapshot (volatile — dated)
- In flight: <CI run id / build / watcher> — expected: <green-set / criterion>
- Blockers: <…>

## Session log  (append one row per session — so ANY past session is resumable)
| Date | Workspace | Resume cmd | Did what |
|------|-----------|------------|----------|
| 2026-06-15 | ~/ws2 | `cd ~/ws2 && claude --resume f223d878-…` | libstdc++ fix shipped green ([#360](https://github.com/<org>/gluten-internal/pull/360)); wrote routine |
| 2026-06-12 | ~/ws2 | `cd ~/ws2 && claude --resume c801b58c-…` | M1 concluded; M2 x86 baseline captured |

## Index (where each thing lives — click through, don't duplicate)
- Scope / acceptance / constraints → CHARTER.md
- PR & branch stack (the table you keep asking for) → STATE.md
- How to rebuild / rerun tests / repro → RUNBOOK.md
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

## `STATE.md` — single source of truth for "what code, where"

```markdown
# <Effort> — STATE   (the PR/branch stack; one home for this fact)
Updated: <date>

| Repo | Branch | Tip githash | PR (full URL) | CI status (as of) | Contents |
|------|--------|-------------|---------------|-------------------|----------|
| gluten-internal | mor_productionization | c879c42da | [#360](https://github.com/<org>/gluten-internal/pull/360) | green 2026-06-15 ([run 27443719426](https://github.com/<org>/gluten-internal/actions/runs/27443719426)) | … |
| velox-internal  | mor_productionization | … | [#128](https://github.com/<org>/velox-internal/pull/128) | … | … |

Record every external reference as a **full URL** (markdown link) — the PR `[#360](…/pull/360)`, the CI
run `[run 27443719426](…/actions/runs/27443719426)` — never a bare `#360` or bare run-id. The stack
spans repos, so a bare number is ambiguous and isn't clickable when a cold session resumes.

## Working set (what to check out to get the latest)
- gluten: <branch@sha>   velox: <branch@sha>   hudi-rs: <…>
## Published artifacts
- <codeartifact pkg @ version>
```

---

## `RUNBOOK.md` — how to play with it (commands live here, not in prose)

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

Written by `/maintain-workspace compact`. It makes the fold auditable: what was
folded in, every promise the compact now owns, and the single stack that re-proves them.

```markdown
# <name> — COMPACTED   (fold record for main-<curr_instant>-complete-compact-<name>)
Updated: <date>

## Included instants (folded into this one; originals kept on disk)
- 07181613-07191011-complete-append-addfeature1
- 07181613-07191013-complete-append-addfeature2
- 07181613-07191016-complete-append-addfeature3

## Merged acceptance criteria (union of the above; see CHARTER.md for proof + self-review)
- [ ] AC-1 <from addfeature1>
- [ ] AC-2 <from addfeature2>
- [ ] AC-3 <from addfeature3>

## Compacted "Setup to end up with"
- Consolidated deliverables: <the merged PR stack, images, jars — links; superseding the
  per-feature handoffs>
- Single reproducible stack: <one build + one validation run (see RUNBOOK.md) that
  re-derives ALL evidence for the merged criteria — a few cmds + grep, at most>
- Evidence: every merged criterion has a row in evidence/INDEX.md pointing at the
  consolidated artifact and how to regenerate it.
```

The merged criteria default to the **union** of the inputs'. If the partner narrows or
supersedes some, note which and why in DECISIONS.md — don't silently drop a promise.
