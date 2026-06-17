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
| 2026-06-15 | ~/ws2 | `cd ~/ws2 && claude --resume f223d878-…` | libstdc++ fix shipped green (PR #360); wrote routine |
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

## `CHARTER.md` — durable, the anti-re-paste card

```markdown
# <Effort> — CHARTER   (durable; edit deliberately)

## Goal (e2e)
<the end state, in your partner's words>

## Scope
- IN:  <e.g. Hudi MOR v9, commit-time ordering, schema-on-write only>
- OUT: <e.g. schema-on-read, position-based, python/datafusion, ARM dims>

## Acceptance criteria
- [ ] <criterion 1, measurable>
- [ ] <criterion 2>

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

| Repo | Branch | Tip githash | PR | CI status (as of) | Contents |
|------|--------|-------------|----|-------------------|----------|
| gluten-internal | mor_productionization | c879c42da | #360 | green 2026-06-15 (run 27443719426) | … |
| velox-internal  | mor_productionization | … | #128 | … | … |

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

## `ISSUES.md` / `ASSUMPTIONS.md` — registers with stable IDs + status

```markdown
# ISSUES   (durable; append, don't rewrite)
| ID | Issue | Status | Fix / ticket |
|----|-------|--------|--------------|
| OI-11 | gcc-toolset-11 cxx Slice element_type | DEFERRED | ENG-43030 |

# ASSUMPTIONS   (the unverified-beliefs register)
| ID | Assumption (believed, not yet proven) | Status | Evidence / next check |
|----|---------------------------------------|--------|-----------------------|
| AS-1 | "ship our own libstdc++.so.6" is possible on centos-7 | REFUTED 06-12 | devtoolset ships only static archives → evidence/2026-06-12-local-validation-findings.md |
| AS-3 | testSecondaryIndexCreation failure is pre-existing | VERIFIED 06-11 | also fails vanilla (no gluten) |
```

**Status vocabulary:** `OPEN` (believed, unchecked) · `VERIFIED` · `REFUTED` · `SANCTIONED` (known risk, accepted by your partner) · `DEFERRED` (won't check now, tracked). Issues also use `FIXED` / `DOCUMENTED`.

---

## `evidence/INDEX.md` — proof, indexed (every "it's green" cites a row here)

```markdown
# Evidence index — acceptance criteria → artifact → source
Updated: <date>

| # | Criterion | Artifact (this folder) | What it shows | Source (job/run/commit) |
|---|-----------|------------------------|---------------|-------------------------|
| 1 | <criterion 1> | `<file>` | <one line> | job `<id>` / `runs/<ts>` |
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
| Mode | Select | Key config | Proven by (job / run) → evidence |
|------|--------|------------|----------------------------------|
| <default> | `<profile/command>`        | <…> | `<job-id>` / `runs/<ts>` → `evidence/<file>` |
| <variant> | `<profile/command + flag>` | <…> | `<job-id>` / `runs/<ts>` → `evidence/<file>` |
```

Then the per-mode copy/paste commands and the "reproduce any past run" one-liner go in RUNBOOK's
existing Build/Run sections — not a separate doc.
