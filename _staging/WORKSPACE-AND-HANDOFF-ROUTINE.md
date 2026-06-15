# Workspace & Handover Routine — for long-running, multi-session efforts

A reusable spec for how to lay out an **effort folder** so that work survives across
sessions, forks, rewinds, and SSH drops — and so a fresh session can be pointed at the
folder and resume cold in ~60 seconds without re-eliciting state.

Crystallized 2026-06-15 from a retrospective of the Hudi-MOR-offload effort (folders
`0604` … `0612analysisvalidation`; ~70 Claude sessions across `~/ws1`/`ws2`/`ws3`).
Sibling process doc (co-located here in `_staging/`): `ANALYSIS-process-retrospective.md`
(the RCA routine). Its evidence docs stay at the source:
`/home/ubuntu/operations/tasks/quantonMORScanSupport/tasks/0611glutenveloxcleanup/m2/githubCI/symbols-map/{RAW-TIMELINE.md,RCA-COMPREHENSIVE.md}`.

> **STAGING NOTE (2026-06-15):** This doc and `ANALYSIS-process-retrospective.md` were moved
> into `~/superpowers/_staging/` to be merged later into a new skill / to revise existing
> skills. They are not yet skills. A companion `REPEATED-INSTRUCTIONS.md` (standing user
> directives mined from the same sessions) also lives here for the same processing.

---

## 0. Why this exists (the three stated goals)

The user stated the purpose verbatim (session f223d878, 2026-06-15):

> "we work on the same issue over multiple sessions and each we do something up to some
> scope, along the way we find extra scope, unverified assumptions, and design docs,
> progress tracking, decision making, etc. The goal of doing all these are
> - **tracking progress of execution** … what we have done so far, where are we w.r.t.
>   the e2e delivery goal
> - what are the **hiccups / surprises / unverified assumptions** we spotted along the
>   way, are they deferred, fixed, or sanctioned.
> - a **handover doc** just summarizing the latest status, what are still remaining,
>   what are delivered, **how to play with the current things to repro gaps / rerun
>   validation** on what is delivered and **PR stack links**.
> next time when I resume the effort, I can just point claude to the old workspace folder
> and it knows what were the starting points, where we left over, what's remaining, and
> how to resume the effort."

That is the acceptance test for this routine: **point a new session at the folder → it
knows starting point, current state, what's left, and how to resume — with no re-asking.**

---

# PART I — Retrospective: what went wrong, with evidence

## I.1 Current-state inventory (what the effort folders actually contain)

Every folder improvised its own handover docs with **inconsistent names and overlapping
scope**. Across three folders alone:

| Folder | "status/handover" docs present |
|---|---|
| `0607-productquality-gv` | `TRACKING.md` ("authoritative index"), `progress.md` ("Progress Board / RESUME HERE"), `pr-status.md` ("live tracker"), `DECISIONS-autonomous.md`, `old-issues.md`, `design.md` |
| `0608-glutenCI` | `DELIVERABLES-pr-stack.md`, `STATUS.md`, `CHECKPOINT.md`, `00-investigation.md`, per-dimension `0N-*.md` |
| `0611glutenveloxcleanup` | `TRACKING.md`, `STATUS-0612.md`, `README.md`, `SESSION-0612-*.md`, `HANDOFF.md` (ARM only), per-topic `analysis/validation/callstack.md` |

**Patterns worth keeping** (already good — standardize them):
- Stable-ID **issue register** (`OI-1..12`, `GAP-*`) with `FIXED / DEFERRED / DOCUMENTED`
  status + ClickUp/ENG links.
- **One folder per investigation** (`topic1-5`, `Dim-1/2/3`) split into
  `analysis / validation / callstack`.
- **Verdict / one-line-summary tables** at the top of review docs.
- **Resume command at the top** of `TRACKING.md` (`claude --resume <uuid>` + `cd ~/ws2`).

**Structural failures** (the cause of the recurring asks in I.2):
1. **No single canonical entry point.** 3+ docs each claim to be "the" status; they
   drift (ws1 `TRACKING.md` dated 06-08 vs `progress.md` 06-07). A cold session can't
   tell which to open, or which is current.
2. **Volatile mixed with durable.** "watcher b4go0e5iu", "run … IN PROGRESS", CI colors
   sit beside durable RCA conclusions and decisions. On resume you can't tell what rotted.
3. **Evidence lives in `/tmp`.** `/tmp/m2-e2e-summary-0607.log`, surefire dumpstreams,
   watcher logs — cited as proof, gone on resume.
4. **Repro/build commands buried in prose** or only in scattered `prompts/*` files — never
   surfaced as a runbook.
5. **No durable charter.** Goal, scope, acceptance criteria, and standing constraints were
   re-pasted by the user almost every session instead of living in one place.
6. **No standing "unverified assumptions" register** distinct from issues (goal #2).

## I.2 The recurring user-ask categories (empirical; 3-way transcript mining)

Mined from **~1,300 genuine user turns across ~70 sessions** in ws1/ws2/ws3. Each
category is a question the user had to **re-ask because no durable doc answered it**.
Counts are approximate totals across the three workspaces.

| # | Recurring ask | ~count | Verbatim examples |
|---|---|---|---|
| **A** | **PR / branch / githash / CI links & the stack** | **70+** | "PR link please"; "show me PR stack links?"; "get me PR links for gluten and velox and hudi rs" *(twice, one session)*; "please update the … PR and head commit to me"; **"which doc I can find these info plus the PR stack deliverables"** |
| **B** | **Status / where are we / done vs left / milestones** | **55+** *(plus ~60 bare "continue"/"status?")* | "where are we in the entire plan of 2 milestones?"; "status?" *(×3 in one session)*; "is it done?"; "what are the remaining steps towards full closure?"; "what are the milestones done and what are still pending / explicitly deferred?" |
| **C** | **Repro / rerun / how-to-build / how-to-play** | **40+** | the full `cargo build -p hudi-cpp … runJavaTests.sh` block **re-pasted into 3 sessions**; "show me cmds you used … dump to prompts/runschemaEvo"; "iterate faster via local repro of the exact same env"; "how do we package libhudi.so into the jar?" |
| **D** | **Scope / acceptance criteria / standing constraints** | **40+** | "let's be clear we only care table version 9, commit time ordering with backward-compatible schema evolution (schema on write)"; "we don't need PositionBased"; "we don't care python, data fusion"; "don't ask for permission … always go with subagent driven" *(restated 3× in one session)* |
| **E** | **Did you actually verify / prove offload ran / is it green?** | **30+** | "make sure you find hudi rs related logs to prove the offload did happen"; "have u verified all ut green for hudi core locally?"; "does the functional tests … throw exceptions on unexpected fallbacks?" *(verbatim in 2 sessions)* |
| **F** | **TLDR / formal RCA of an already-investigated finding** | **20+** | "what's the real root cause and what's the fix applied? Give a tldr"; "please give formal RCA of the issue"; lost to rewinds: "I accidentally rewound … you lost your findings" |
| **G** | **Decisions / surprises / deferred-scope log** | requested explicitly | "ensure in your workspace we have … new issues we fixed along the way - important decisions we made"; "update relevant tracking doc … about my questions we discussed and action taken" |
| **H** | **Coverage matrices re-asked verbatim** (a verification sub-case) | 44 hits | "what are the data types covered … be clear if we have the data type in any of the LOG files" *(near-identical in 2 sessions)*; "what are the data types we covered and what we still need to cover" |
| **I** | **Environmental bootstrap** (creds, session survival, forks) | recurring | AWS CodeArtifact `export AWS_ACCESS_KEY_ID=…` **re-pasted 8×**; "how can we move them to a screen session"; forked Q&A sessions asking the **same question at the same minute** in two transcripts |

### The smoking-gun meta-signals
- **"which doc I can find these info"** — the info *existed*; it just wasn't locatable.
  The layout, not the work, was the failure.
- The user **escalated** from *asking* (early) → *commanding* "keep it updated in the
  workspace folder" → **enforcing via a Stop hook** ("This RCA is not optional but a hard
  blocker"). Rising tooling against the same missing-context problem.
- **Forks prove it.** When state lives only in a session, every parallel/forked session
  re-asks it — we observed identical questions at the same timestamp in two files. The
  workspace docs are *the* interface between concurrent and future sessions.

---

# PART II — The routine: canonical layout + discipline

## II.1 Design principles

1. **One entry point, fixed name.** Every effort folder has a `HANDOFF.md` at its root.
   It is *the* first (and often only) file a resuming session must read. Everything else
   hangs off it via links.
2. **Durable vs. live, never mixed.** A doc is either DURABLE (rarely changes; no CI
   colors, no "in progress") or LIVE (a dated snapshot that is understood to rot). Mark
   each doc's header. Volatile state (CI run IDs, "watcher …", build-in-flight) lives
   **only** in `HANDOFF.md`'s dated status snapshot — never in durable docs.
3. **One fact, one home.** The PR-stack table lives in exactly one file (`STATE.md`).
   Everywhere else *links* to it. No copy-paste — copies drift.
4. **Capture evidence into the folder, not `/tmp`.** Logs that prove a claim go to
   `evidence/<date>-<name>.log` and are referenced by relative path.
5. **Registers append, not rewrite.** Decisions, issues, and assumptions accrete with
   stable IDs and dates; you add rows, you don't overwrite history.
6. **The charter is sacred and durable.** Goal, scope, acceptance, and standing
   constraints are written once and only edited deliberately — so the user never
   re-pastes them.

## II.2 Canonical file set (fixed names at the effort root)

```
<effort>/
  HANDOFF.md        ← ENTRY POINT. workspace folder + resume cmd + session log + live snapshot + index
  CHARTER.md        ← DURABLE. goal · scope(in/out) · acceptance criteria · standing rules · env
  STATE.md          ← single source of truth: repo → branch → tip githash → PR link → CI status
  RUNBOOK.md        ← how to build / run tests / repro the gap / rerun validation / proof markers
  DECISIONS.md      ← DURABLE. dated decision log w/ rationale (D-1, D-2, …)
  ISSUES.md         ← DURABLE. stable-ID issue register: OPEN/FIXED/DEFERRED/DOCUMENTED + tickets
  ASSUMPTIONS.md    ← DURABLE. unverified assumptions: OPEN/VERIFIED/REFUTED/SANCTIONED/DEFERRED
  investigations/   ← one subfolder per deep dive: <topic>/{analysis,validation,callstack}.md
  evidence/         ← captured logs/artifacts referenced as proof (NOT /tmp)
  plans/ specs/     ← superpowers plan & spec docs (existing convention)
```

Small efforts may fold `STATE`+`RUNBOOK` into `HANDOFF`, and `ASSUMPTIONS` into `ISSUES`
— but keep `HANDOFF.md` and `CHARTER.md` always. Never invent a new name for an existing
role (no `progress.md` *and* `TRACKING.md` *and* `STATUS.md`).

## II.3 File templates

### `HANDOFF.md` — the entry point (the only doc that is allowed to rot)
```markdown
# <Effort> — HANDOFF   (read me first)

## Resume here
- Workspace folder (where the code is checked out): `~/ws2`   # which of ~/ws1·ws2·ws3·…
- Resume the latest session:  `cd ~/ws2 && claude --resume <latest-uuid>`
- Repo checkouts used: gluten=`~/ws2/gluten-internal` · velox=`~/ws2/velox-internal` · …
Updated: 2026-06-15 by session <latest-uuid>  |  Status: LIVE SNAPSHOT (rots — verify against STATE/CI)

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
| 2026-06-11 | ~/ws2 | `cd ~/ws2 && claude --resume 7389eccc-…` | gluten gates + adapter wave; velox link-fix |

## Index (where each thing lives — click through, don't duplicate)
- Scope / acceptance / constraints → CHARTER.md
- PR & branch stack (the table you keep asking for) → STATE.md
- How to rebuild / rerun tests / repro → RUNBOOK.md
- Decisions → DECISIONS.md · Issues → ISSUES.md · Unverified assumptions → ASSUMPTIONS.md
- Deep dives → investigations/<topic>/
```
> **Why both the folder AND the uuid:** the same effort is worked from different `~/ws`
> checkouts across sessions (ws1/ws2/ws3 run concurrently), and `claude --resume <uuid>`
> only attaches the conversation — it does NOT restore the working directory. You must
> `cd` into the recorded workspace first or the resumed session operates on the wrong
> tree. The **session log** keeps every past session resumable (a single "Resume:" line
> loses all but the latest); find the uuid for "the session that did X" and re-attach it.
> (Claude session transcripts live in `~/.claude/projects/-home-ubuntu-ws<N>...` — the
> dir name encodes the workspace folder, which is why recording the folder matters.)

### `CHARTER.md` — durable, the anti-re-paste card
```markdown
# <Effort> — CHARTER   (durable; edit deliberately)

## Goal (e2e)
<the end state, in the user's words>

## Scope
- IN:  <e.g. Hudi MOR v9, commit-time ordering, schema-on-write only>
- OUT: <e.g. schema-on-read, position-based, python/datafusion, ARM dims>

## Acceptance criteria
- [ ] <criterion 1, measurable>            ## Standing constraints / rules
- [ ] <criterion 2>                        - <e.g. M1 must stay green>
                                           - <e.g. use ≤16 cores: taskset -c 0-15 / -j16 / -T 8>
                                           - <e.g. detection from table-config only>
                                           - <e.g. don't ask permission; subagent-driven mode>

## Environment
- Box: <cores/mem>; Images: <build/runtime tags>; Toolchain: <…>
- Credentials bootstrap: <how to get AWS CodeArtifact creds — pointer, not the secret>
```

### `STATE.md` — single source of truth for "what code, where"
```markdown
# <Effort> — STATE   (the PR/branch stack; one home for this fact)
Updated: 2026-06-15

| Repo | Branch | Tip githash | PR | CI status (as of) | Contents |
|------|--------|-------------|----|-------------------|----------|
| gluten-internal | mor_productionization | c879c42da | #360 | green 2026-06-15 (run 27443719426) | … |
| velox-internal  | mor_productionization | … | #128 | … | … |

## Working set (what to check out to get the latest)
- gluten: <branch@sha>   velox: <branch@sha>   hudi-rs: <…>   hudi-internal: <…>
## Published artifacts
- <codeartifact pkg @ version>
```

### `RUNBOOK.md` — how to play with it (commands live here, not in prose)
```markdown
# <Effort> — RUNBOOK
## Build (exact, copy-paste; the recipe you keep re-pasting)
```bash
WS=$(pwd); cargo build -p hudi-cpp …; <build velox>; <build gluten>; <mvn package>
```
## Run validation
```bash
prompts/runJavaTests.sh … ; prompts/runScalaTests.sh … ; prompts/runschemaEvo.sh …
```
## Prove the offload actually ran (not JVM fallback)
- grep the surefire `*.dumpstream` for: `read_file_slice returned OK`, `arrowStream=`,
  `Building HiveHudiMORSplit`.
## Reproduce the known gap / repro env
- <docker image + flags that match CI exactly>; logs land in evidence/.
```

### `ISSUES.md` / `ASSUMPTIONS.md` — registers with stable IDs + status
```markdown
# ISSUES
| ID | Issue | Status | Fix / ticket |
|----|-------|--------|--------------|
| OI-11 | gcc-toolset-11 cxx Slice element_type | DEFERRED | ENG-43030 |

# ASSUMPTIONS  (the goal-#2 register)
| ID | Assumption (what we believe, not yet proven) | Status | Evidence / next check |
|----|----------------------------------------------|--------|-----------------------|
| AS-1 | "ship our own libstdc++.so.6" is possible on centos-7 | REFUTED 06-12 | devtoolset ships only static archives → 2026-06-12-local-validation-findings.md |
| AS-2 | conditional symbols.map is safe (ON/OFF never co-occur) | REFUTED | toy `both` case proved co-occurrence |
| AS-3 | testSecondaryIndexCreation failure is pre-existing | VERIFIED 06-11 | also fails vanilla (no gluten) |
```
Status vocabulary: **OPEN** (believed, unchecked) · **VERIFIED** · **REFUTED** ·
**SANCTIONED** (known risk, accepted by user) · **DEFERRED** (won't check now, tracked).

## II.4 Maintenance discipline (the invariants)

- **End every session by updating `HANDOFF.md`**: the one-paragraph "where we are", the
  next action, the live snapshot, the "Resume here" header (workspace folder + latest
  uuid), AND **append a row to the session log** (`date | workspace | resume cmd | did
  what`). This is the last action before stopping — treat it like a commit. The current
  session's uuid is the transcript filename under `~/.claude/projects/-home-ubuntu-ws<N>…/`;
  the workspace folder is the `cd` you started from. Recording both is mandatory — the
  uuid alone resumes the conversation onto the wrong tree if the folder isn't restored.
- **Write the fact to its home, then link.** New PR → add a row to `STATE.md`; reference
  it from `HANDOFF.md` by link. Never paste the table twice.
- **A new surprise → a row in `ISSUES.md` or `ASSUMPTIONS.md`** the moment it's spotted,
  with a status — even "OPEN, unchecked". This is how "hiccups/surprises/unverified
  assumptions" get tracked instead of lost (goal #2).
- **A decision → a dated `DECISIONS.md` row** with the rationale, the moment it's made.
- **Evidence → `evidence/`**, never `/tmp`. A claim of "green" cites a file in the folder.
- **Durable docs carry no volatile state.** If you're tempted to write a CI run ID into
  `CHARTER`/`DECISIONS`/`ISSUES`, it belongs in `HANDOFF`'s snapshot or `STATE`'s CI column.
- **Header every doc**: `Updated: <date> by <uuid> | Status: DURABLE | LIVE`.

## II.5 The resume contract (what a cold session does in 60s)

1. Read `HANDOFF.md` → workspace folder + resume command(s), the session log (which past
   session did what, and how to re-attach it), where-we-are, next action, index.
2. Read `CHARTER.md` → don't go out of scope, don't re-ask the criteria/constraints.
3. Skim `STATE.md` → know the working set; no need to re-elicit branches/PRs.
4. Open `RUNBOOK.md` → rebuild + rerun validation without re-pasting commands.
5. Glance `ASSUMPTIONS.md` + `ISSUES.md` → know the open risks and what's deferred.
6. Only then dive into `investigations/` for the specific task.

If those six files can't carry a fresh session from cold to productive, the layout failed.

---

# PART III — Dry run: cold-resuming THIS effort under the routine

Assume the routine had been in force and a brand-new session is pointed at
`tasks/0611glutenveloxcleanup/`. Walk the resume contract and watch each recurring ask
(Part I.2) get answered by a file instead of a question to the user.

**Step 1 — `HANDOFF.md`.** Reads: `cd ~/ws2 && claude --resume <uuid>`; "M1 concluded
green; M2 libstdc++ `free()` fix shipped green on PR #360 run 27443719426; next action:
none open — effort at a clean stopping point." → answers **B** (status/where/done-vs-left)
and **F** (TLDR) with zero asks. The old failure mode — "I accidentally rewound, you lost
your findings" — can't happen; the finding is on disk.

**Step 2 — `CHARTER.md`.** Reads scope (IN: Hudi MOR v9 CTO schema-on-write; OUT:
schema-on-read, position-based, python/datafusion, ARM dims) and constraints (M1 stays
green; x86 only; ≤16 cores; detection from table-config only; don't ask permission,
subagent-driven). → answers **D**; the session won't re-ask the criteria or wander
out of scope, and the user doesn't re-paste the preamble (which happened in 3+ sessions).

**Step 3 — `STATE.md`.** The repo→branch→tip→PR→CI table is right there. → answers **A**
("which doc I can find the PR stack" — *this* doc) and the "what branch/githash is current"
re-asks. No hand-typed `| Repo | branch | tip |` table in the prompt.

**Step 4 — `RUNBOOK.md`.** The exact `cargo build -p hudi-cpp …` + `runJavaTests.sh`
recipe and the dumpstream proof-markers (`read_file_slice returned OK`, `arrowStream=`).
→ answers **C** (re-pasted into 3 sessions before) and **E**/**H** (how to *prove* offload
ran; where the coverage matrix lives) — the session re-validates instead of re-deriving.

**Step 5 — `ASSUMPTIONS.md` + `ISSUES.md`.** AS-1 "ship our own libstdc++" = REFUTED with
the local-validation evidence link; AS-2 "conditional symbols.map safe" = REFUTED by the
toy `both` case; OI-11 = DEFERRED/ENG-43030. → answers **G** and, crucially, **stops the
RCA dead-ends from recurring**: a fresh session reading AS-1/AS-2 will not re-propose
ship-a-lib or the knife-edge conditional. (This is the link to the RCA routine — the
assumptions register is where "green ≠ root-caused" gets recorded so it isn't re-learned.)

**Step 6 — `investigations/symbols-map/`.** The full RCA + timeline for the one task that
needs depth.

**Environmental (`I`).** `CHARTER.md` → "Environment" gives the creds-bootstrap pointer
(re-pasted 8× before) and the screen/session-survival note. Forked Q&A sessions read the
same files, so two concurrent sessions stop asking the same question at the same minute.

### Net effect
Of the nine recurring-ask categories, **A–H are answered by reading the six canonical
files**; the session reaches "productive on the next action" without a single
status/scope/PR/repro question to the user. The user's stated acceptance test — *"point
claude to the old workspace folder and it knows the starting point, where we left off,
what's remaining, and how to resume"* — is met by construction.

### What this routine deliberately does NOT change
- It doesn't replace the strong existing patterns (stable-ID issue register, one-folder-
  per-investigation, verdict tables) — it **standardizes their names and homes**.
- It doesn't add ceremony to trivial efforts — `HANDOFF.md` + `CHARTER.md` is the floor;
  the rest scales with the work.
- It doesn't try to keep volatile CI state "correct" — it **quarantines** it to one dated
  snapshot so the durable knowledge around it stays trustworthy.
