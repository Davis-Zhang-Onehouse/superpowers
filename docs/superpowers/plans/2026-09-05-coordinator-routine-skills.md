# Coordinator Routine Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship six new skills that carry the coordinator routine a five-week PR-stack effort evolved — the project arc, wave dispatch, stack integration, harvest, roadmap maintenance, and the audit trail — each linting clean and discovered by `superpowers-selftest`.

**Architecture:** Six new `skills/<name>/` directories, each with a `SKILL.md` and a `tests/lint-self.sh` that runs the existing `skills/using-fleet/tools/lint-skill.py` (V1 + V2) over it. Two skills additionally get a V3-style runnable suite that performs their documented sequence against a scratch `FLEET_HOME` on a private tmux socket, following `skills/coordinating-instants/tests/loop.sh`. `coordinating-instants` is modified only to add a routing pointer.

**Tech Stack:** Markdown skills; bash test harnesses; `python3` for the linter; `fleet` 0.3.18 from `bin/fleet`; `bin/superpowers-selftest` for discovery.

**Spec:** `docs/superpowers/specs/2026-09-05-coordinator-routine-skills-design.md` — read it alongside this plan. Every task below names the spec section that supplies its content; the spec's tables are the content, not a summary of it.

## Global Constraints

- **Zero new dependencies.** `CLAUDE.md` — superpowers is zero-dependency by design. Bash + `python3` stdlib + `fleet` only.
- **V1: every `fleet <verb>` written inside a code span must be a registered verb.** Unregistered verbs need `<!-- v1-proposed: <verb> -->`. The linter imports `VERBS` from `fleet.cli`.
- **V2: every sentence containing `refuses`, `refused`, `will refuse`, `cannot`, or `may not` must be accompanied by `<!-- v2-cite: <slug> <CASE-ID> -->`**, where `<CASE-ID>` is PASS in `fleet/it/RESULTS.tsv`. 303 cases currently pass. Find candidates with:
  `awk -F'\t' '$2=="PASS"' fleet/it/RESULTS.tsv | grep -i <topic>`
  V2 does **not** check relevance — verify the pairing with `python3 skills/using-fleet/tools/lint-skill.py <skill> --show`.
- **No line-number citations in any SKILL.md.** Cite by symbol (`Roadmap.apply`), never `roadmap.py:458`. This is `FI-403`: a rule written to fix a hard-coded-line-number bug prescribed `sed -n '93,$p'`, drifted, and truncated every brief for days.
- **Do not modify any `SI-*` behaviour in `fleet/`.** The skills document the workaround and name it as one. Fixing the infra is separate work, tracked in `docs/superpowers/fleet-infra-backlog.md`.
- **Never run the fleet IT suites** (`fleet/it/run-*.sh`) during this work. They snapshot a `claude` process count at section boundaries and any tool call an agent makes perturbs it.
- **Frontmatter is exactly two keys**, `name` and `description`, matching the directory name.
- **Skills are auto-discovered.** No manifest edit is needed; `.claude-plugin/plugin.json` does not enumerate skills.

## File Structure

| Path | Responsibility |
|---|---|
| `skills/running-a-stacked-effort/SKILL.md` | the project arc: chartering, the registries, the unknowns ledger, the cycle, the endgame |
| `skills/running-a-stacked-effort/references/chartering.md` | goal → "done means all N" → AC table shape, worked from the source charter |
| `skills/running-a-stacked-effort/references/chain-manifest.md` | the manifest format, what a position records, how ancestry is checked |
| `skills/running-a-stacked-effort/tests/lint-self.sh` | V1+V2 over this skill |
| `skills/dispatching-a-wave/SKILL.md` | admit *k* workers onto one shared base |
| `skills/dispatching-a-wave/tests/lint-self.sh` | V1+V2 |
| `skills/dispatching-a-wave/tests/wave-sequence.sh` | V3: the documented sequence runs against a scratch store |
| `skills/integrating-a-pr-stack/SKILL.md` | N siblings → one linear chain per repo |
| `skills/integrating-a-pr-stack/references/pinned-multi-repo.md` | pin-moves-with-position, the gluten/velox worked example |
| `skills/integrating-a-pr-stack/tests/lint-self.sh` | V1+V2 |
| `skills/harvesting-an-instant/SKILL.md` | gate, close, and carry the knowledge up |
| `skills/harvesting-an-instant/tests/lint-self.sh` | V1+V2 |
| `skills/harvesting-an-instant/tests/regression-trap.sh` | V3: reproduces the `SI-48` apply-regression the skill warns about |
| `skills/maintaining-a-roadmap/SKILL.md` | title width, deps, readiness, retirement, ranking |
| `skills/maintaining-a-roadmap/tests/lint-self.sh` | V1+V2 |
| `skills/auditing-a-dispatch-history/SKILL.md` | forward and backward audit |
| `skills/auditing-a-dispatch-history/tests/lint-self.sh` | V1+V2 |
| `skills/coordinating-instants/SKILL.md` | **modify**: add the routing section |

---

### Task 1: `running-a-stacked-effort` — the umbrella

**Files:**
- Create: `skills/running-a-stacked-effort/SKILL.md`
- Create: `skills/running-a-stacked-effort/references/chartering.md`
- Create: `skills/running-a-stacked-effort/references/chain-manifest.md`
- Test: `skills/running-a-stacked-effort/tests/lint-self.sh`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: the skill name `running-a-stacked-effort`, referenced by name from Task 9's routing section; the spine table, which Tasks 2–8 treat as settled; the term **chain manifest**, whose format `references/chain-manifest.md` defines and which Tasks 2 and 4 read and write.

**Content source:** spec §"The shared spine" and §1.

- [x] **Step 1: Write the failing test**

Create `skills/running-a-stacked-effort/tests/lint-self.sh`:

```bash
#!/usr/bin/env bash
# V1+V2 over this skill. Discovered by bin/superpowers-selftest.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SKILL="$HERE/.."
LINT="$SKILL/../using-fleet/tools/lint-skill.py"

out="$(python3 "$LINT" "$SKILL" 2>&1)"
if [ $? = 0 ]; then
  echo "PASS: every fleet verb named in a code span is registered, and every refusal claim cites a passing case"
  exit 0
fi
printf '%s\n' "$out"
echo "FAIL"
exit 1
```

Then `chmod +x skills/running-a-stacked-effort/tests/lint-self.sh`.

- [x] **Step 2: Run test to verify it fails**

Run: `bash skills/running-a-stacked-effort/tests/lint-self.sh`
Expected: FAIL — the linter exits 2 because the skill directory has no `SKILL.md`.

- [x] **Step 3: Write the skill**

`skills/running-a-stacked-effort/SKILL.md`, frontmatter verbatim:

```markdown
---
name: running-a-stacked-effort
description: Use when standing up or resuming a multi-milestone effort that delivers a stacked chain of PRs across one or more pinned repos - owns the project goal, the milestone registry, the known and unknown unknowns, and the cycle that dispatches waves and integrates their output. Triggers include "you are the coordinator for this effort", "let's start this project", "what is the state of the project", resuming into an effort root.
---
```

Body sections, in order — write each from spec §1, which carries the full text:

1. **Overview** — the role, and the three registries.
2. **Chartering** — goal plus *"done means all N, and I do not get to soften any of them"*; ACs as NL → executable proof → running self-review. Point to `references/chartering.md`.
3. **Preserving the operator's framing** — first three raw prompts verbatim; strike superseded lines in place with the reason.
4. **The registries and who writes them** — the spine table from spec §"The shared spine", including the `HANDOFF.md`-is-narrative rule.
5. **The unknowns ledger** — `kind=delivery|question|probe`; note `SI-42` is not implemented, so today the distinction lives in the title's first token and the skill says so plainly.
6. **The cycle** — rank → wave → integrate → harvest → re-rank, naming the four routine skills as load-when-you-get-there.
7. **The endgame** — an item outliving the effort needs both a documented issue and a `fleet milestone`.
8. **Red flags** — the five-row table from spec §1 verbatim.

Cite `H9` for the carry-across claim and `H1` for derived readiness. Every "cannot/refuses" sentence needs its `<!-- v2-cite: -->` marker on the same line or the line above.

Write `references/chartering.md` (the AC table shape, worked from the source effort's nine ACs) and `references/chain-manifest.md` (what a position records: ordinal, repo, branch, PR number, tip sha, parent, and **each paired repo's pinned sha**; ancestry checked with `git merge-base --is-ancestor`, never stored; grade state stored with the sha it graded, because it is not derivable later).

- [x] **Step 4: Run test to verify it passes**

Run: `bash skills/running-a-stacked-effort/tests/lint-self.sh`
Expected: `PASS: every fleet verb named in a code span is registered, and every refusal claim cites a passing case`

Then check citation relevance:
Run: `python3 skills/using-fleet/tools/lint-skill.py skills/running-a-stacked-effort --show`
Expected: each `slug -> CASE-ID` prints beside the case's own note; confirm the note is about the claim.

- [x] **Step 5: Run the whole selftest**

Run: `bin/superpowers-selftest`
Expected: `VERDICT: GREEN — every discovered suite passed`, with the discovered count one higher than before.

- [x] **Step 6: Commit**

```bash
git add skills/running-a-stacked-effort
git commit -m "skills: running-a-stacked-effort, the coordinator's project arc"
```

---

### Task 2: `dispatching-a-wave` — the skill

**Files:**
- Create: `skills/dispatching-a-wave/SKILL.md`
- Test: `skills/dispatching-a-wave/tests/lint-self.sh`

**Interfaces:**
- Consumes: the chain manifest format from Task 1's `references/chain-manifest.md` (reads the tip to derive `--lineage-base`).
- Produces: the skill name `dispatching-a-wave`; the six-step routine table that Task 3's suite executes step-for-step.

**Content source:** spec §2.

- [x] **Step 1: Write the failing test**

Create `skills/dispatching-a-wave/tests/lint-self.sh` with the same content as Task 1 Step 1 (the script is location-independent; it derives `SKILL` from its own path). `chmod +x` it.

- [x] **Step 2: Run test to verify it fails**

Run: `bash skills/dispatching-a-wave/tests/lint-self.sh`
Expected: FAIL — no `SKILL.md` yet.

- [x] **Step 3: Write the skill**

Frontmatter verbatim:

```markdown
---
name: dispatching-a-wave
description: Use when putting several worker instants in parallel onto one shared base - deriving the cap from the guard rather than a formula, taking the lineage base from the chain manifest rather than prose, and writing each worker's scope before releasing its seed. Triggers include "dispatch the next wave", "two rows are ready on the same base", "put three workers on this", "dispatch these milestones in parallel".
---
```

Body: the six-step routine table from spec §2 verbatim, then the two expanded sections the spec marks — **step 3** (ask the guard; the formula is a remembered number, and is wrong for an `init`-created coordinator, which has no record) and **step 5** (dispatch → write scope → release the seed; the 180s window; `SI-46` means nothing catches a placeholder scope today). Then the four-row Red Flags table.

Required citations: `F1` for the cap refusal, `F2`/`F3` for declaration-versus-prose freeing the cap, `F4` for the compaction freeze, `LB2` for a done-claim from the wrong base. Mark any verb you name that does not exist with `<!-- v1-proposed: -->`.

- [x] **Step 4: Run test to verify it passes**

Run: `bash skills/dispatching-a-wave/tests/lint-self.sh`
Expected: PASS.

Run: `python3 skills/using-fleet/tools/lint-skill.py skills/dispatching-a-wave --show`
Expected: `F1` prints a note about a second dispatch exiting 4 under the default cap — confirm it sits beside the cap claim, not beside something else.

- [x] **Step 5: Commit**

```bash
git add skills/dispatching-a-wave
git commit -m "skills: dispatching-a-wave, k workers onto one shared base"
```

---

### Task 3: `dispatching-a-wave` — the runnable sequence suite

**Files:**
- Create: `skills/dispatching-a-wave/tests/wave-sequence.sh`

**Interfaces:**
- Consumes: the routine table written in Task 2 — this suite performs it.
- Produces: nothing consumed by later tasks.

**Why this task is separate:** the lint proves the skill names real verbs; it cannot prove the *sequence* works. A skill can name only real verbs and still order them impossibly. This is the same reason `coordinating-instants` has both `lint-self.sh` and `loop.sh`.

- [x] **Step 1: Write the failing test**

Create `skills/dispatching-a-wave/tests/wave-sequence.sh`:

```bash
#!/usr/bin/env bash
# V3 — the wave sequence this skill documents must actually RUN.
#
# On a PRIVATE tmux socket, and `dispatch` is --dry-run: a real dispatch launches a claude session, which
# this suite has no business doing. What is under test is the ORDER and the derivations.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
FLEET="$REPO/bin/fleet"
PROFILE="$REPO/skills/using-fleet/profiles/worker"
SOCK="wave-seq-$$"
TMP="$(mktemp -d)"
trap 'tmux -L "$SOCK" kill-server 2>/dev/null; rm -rf "$TMP"' EXIT

export FLEET_HOME="$TMP/home" FLEET_INSTANTS="$TMP/instants" FLEET_TMUX_SOCKET="$SOCK"
mkdir -p "$FLEET_HOME" "$FLEET_INSTANTS" "$TMP/slotA" "$TMP/slotB"

fails=0
note() { printf '  %s\n' "$*"; }
check() { # check <label> <expected-rc> <actual-rc>
  if [ "$2" = "$3" ]; then note "ok   $1"; else note "FAIL $1 (want rc=$2, got rc=$3)"; fails=$((fails+1)); fi
}

I="$("$FLEET" init --name waveCoord --base 00000000 --optype append --porcelain \
      | awk -F'\t' '$1=="path"{print $2}')"
[ -n "$I" ] || { echo "FAIL: init produced no path"; exit 1; }
"$FLEET" enroll --slot "$TMP/slotA" >/dev/null 2>&1
"$FLEET" enroll --slot "$TMP/slotB" >/dev/null 2>&1

# Step 1 of the routine: the ready set. SI-47 — no row names it, so the skill tells you to re-derive.
# This suite asserts the GAP, so that when SI-47 is fixed this test fails and the skill gets updated.
"$FLEET" milestone --instant "$I" --id m1 --title "wave member one" --status ready >/dev/null 2>&1
"$FLEET" milestone --instant "$I" --id m2 --title "wave member two" --status ready >/dev/null 2>&1
named="$("$FLEET" roadmap --instant "$I" --porcelain 2>/dev/null | awk -F'\t' '$2=="m1"' | wc -l)"
check "SI-47 still open: no roadmap row names a ready milestone" 0 "$named"

# Step 3 of the routine: the cap comes from the guard, not a formula.
"$FLEET" dispatch --profile "$PROFILE" --title waveOne --base 00000000 --optype append \
  --from "$I" --milestone m1 --slot slotA --cap 1 --dry-run --porcelain >"$TMP/dry.txt" 2>&1
check "dry-run dispatch evaluates every gate" 0 $?
grep -q 'guard.wip-cap' "$TMP/dry.txt"
check "the wip-cap guard reports its count and population" 0 $?
grep -q 'dry-run' "$TMP/dry.txt"
check "dry-run states that nothing was claimed or created" 0 $?

# The zero-delta contract the routine depends on: a dry run must leave no instant behind.
count="$(find "$FLEET_INSTANTS" -maxdepth 1 -mindepth 1 -type d | wc -l)"
check "dry-run created no child instant (only the coordinator remains)" 1 "$count"

if [ "$fails" = 0 ]; then echo "PASS: the wave sequence runs in the documented order"; exit 0; fi
echo "FAIL: $fails check(s) failed"; exit 1
```

Then `chmod +x skills/dispatching-a-wave/tests/wave-sequence.sh`.

- [x] **Step 2: Run it and read the result**

Run: `bash skills/dispatching-a-wave/tests/wave-sequence.sh`
Expected: `PASS: the wave sequence runs in the documented order`.

If the `SI-47` check fails, that means `roadmap` now names ready rows — the gap is closed. Do not "fix" the test: update `dispatching-a-wave/SKILL.md` step 1 to read the row directly, then update this assertion to match, and note the change in `docs/superpowers/fleet-infra-backlog.md` by marking `SI-47` closed.

- [x] **Step 3: Confirm discovery**

Run: `bin/superpowers-selftest`
Expected: GREEN, discovered count one higher than after Task 2.

- [x] **Step 4: Commit**

```bash
git add skills/dispatching-a-wave/tests/wave-sequence.sh
git commit -m "skills: prove the wave sequence runs, and pin SI-47 while it is open"
```

---

### Task 4: `integrating-a-pr-stack`

**Files:**
- Create: `skills/integrating-a-pr-stack/SKILL.md`
- Create: `skills/integrating-a-pr-stack/references/pinned-multi-repo.md`
- Test: `skills/integrating-a-pr-stack/tests/lint-self.sh`

**Interfaces:**
- Consumes: the chain manifest format from Task 1 (writes the new tip back to it).
- Produces: the skill name `integrating-a-pr-stack`.

**Content source:** spec §3.

- [x] **Step 1: Write the failing test**

Create `skills/integrating-a-pr-stack/tests/lint-self.sh` with the Task 1 Step 1 content. `chmod +x` it.

- [x] **Step 2: Run test to verify it fails**

Run: `bash skills/integrating-a-pr-stack/tests/lint-self.sh`
Expected: FAIL — no `SKILL.md`.

- [x] **Step 3: Write the skill**

Frontmatter verbatim:

```markdown
---
name: integrating-a-pr-stack
description: Use when several sibling branches delivered on a shared base must become one linear PR chain per repo - reusing the existing PRs, moving each paired repo's pin with the position it belongs to, and grading the resulting tip. Triggers include "restack the wave", "make these siblings one chain", "linearize the PRs", "the four wave branches all sit on the same base".
---
```

Body: the eight-step table from spec §3 verbatim; then the two expanded sections the spec marks — **step 4** (pins move with position; this is the multi-repo core and the half that fails silently, because the chain still builds against the wrong native code) and **step 7** (a restack is the first time these changes share a tree, so it can produce a defect no member instant could have found — `FI-410`). Then the four-row Red Flags table.

`references/pinned-multi-repo.md` carries the gluten/velox worked example: `get-velox.sh` as the pin site, the `-enhanced` twin lineage, retargeting with `gh pr edit --base`, and the before/after `git ls-remote` snapshot as the proof that only granted refs moved.

This skill names mostly `git` and `gh` commands rather than `fleet` verbs, so V1 has little to check — that is expected. V2 still applies to any "cannot/refuses" sentence.

- [x] **Step 4: Run test to verify it passes**

Run: `bash skills/integrating-a-pr-stack/tests/lint-self.sh`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add skills/integrating-a-pr-stack
git commit -m "skills: integrating-a-pr-stack, siblings into one chain with the pins"
```

---

### Task 5: `harvesting-an-instant` — the skill

**Files:**
- Create: `skills/harvesting-an-instant/SKILL.md`
- Test: `skills/harvesting-an-instant/tests/lint-self.sh`

**Interfaces:**
- Consumes: nothing from earlier tasks beyond the spine.
- Produces: the skill name `harvesting-an-instant`; the five-item "carry the knowledge up" list that Task 6's suite pins item 2 of.

**Content source:** spec §4.

- [x] **Step 1: Write the failing test**

Create `skills/harvesting-an-instant/tests/lint-self.sh` with the Task 1 Step 1 content. `chmod +x` it.

- [x] **Step 2: Run test to verify it fails**

Run: `bash skills/harvesting-an-instant/tests/lint-self.sh`
Expected: FAIL — no `SKILL.md`.

- [x] **Step 3: Write the skill**

Frontmatter verbatim:

```markdown
---
name: harvesting-an-instant
description: Use when a worker instant has finished and must be gated, closed, and emptied of everything it learned - reading the proposal's note rather than only its status, checking the inbox for a proposal that would regress a landed milestone, and re-homing findings that would otherwise die with the instant. Triggers include "the worker is done", "harvest x4", "close it out", "apply its proposal".
---
```

Body, two halves, per spec §4:

**Half one — close out.** `apply` (dry-run first) → `fleet review` gate → the worker's own `fleet complete` → three consecutive non-wait `fleet pane-guard` samples plus an attachment check → `fleet close` → wait for the cwd-holding pid → `fleet harvest`. State plainly that `close && harvest` chained is the shape that produces a confusing exit 4, and that `harvest` exiting 1 is expected — read the `harvested … info` row, not the status.

Include the exact `fleet review` grammar, because two refusals cost a round each in the field: `--finding` is `id:severity:status:location:finding:action`, severity ∈ `Critical|Important|Minor|Nit`, status ∈ `open|applied|wont-fix`, verdict ∈ `READY|READY-WITH-FIXES|NOT-READY`, and there is no `--note`. Add the rule that a coordinator's own follow-up is never filed as a finding against the worker — an `Important:open` finding holds the worker's gate hostage to the coordinator's future action.

**Half two — carry the knowledge up.** The five numbered items from spec §4 verbatim, with item 2 (`SI-48`, the regressing proposal) marked as the one nothing refuses today.

Then the five-row Red Flags table.

Required citations: `H3` for apply carrying evidence and consuming the proposal, `H4` for empty evidence being refused at both doors, `G7` for a phase and a parked question surviving the rename.

- [x] **Step 4: Run test to verify it passes**

Run: `bash skills/harvesting-an-instant/tests/lint-self.sh`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add skills/harvesting-an-instant
git commit -m "skills: harvesting-an-instant, close out and carry the knowledge up"
```

---

### Task 6: `harvesting-an-instant` — the regression-trap suite

**Files:**
- Create: `skills/harvesting-an-instant/tests/regression-trap.sh`

**Interfaces:**
- Consumes: the half-two item 2 written in Task 5.
- Produces: nothing consumed later.

**Why this task is separate:** the skill tells a coordinator to check the inbox before applying, because nothing else will. That instruction is only worth carrying while it is true. This suite asserts the hazard still exists, so the day `SI-48` is fixed the suite fails and the skill gets corrected instead of quietly over-warning.

- [x] **Step 1: Write the test**

Create `skills/harvesting-an-instant/tests/regression-trap.sh`:

```bash
#!/usr/bin/env bash
# SI-48 — a stale proposal can regress a `done` milestone, and the readiness cascade goes with it.
#
# This suite asserts a HAZARD, not a guarantee. It passes while the hazard exists. When `apply` learns to
# refuse a regression, this suite FAILS — and that failure is the signal to update
# harvesting-an-instant/SKILL.md and mark SI-48 closed in docs/superpowers/fleet-infra-backlog.md.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
FLEET="$REPO/bin/fleet"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export FLEET_HOME="$TMP/home" FLEET_INSTANTS="$TMP/instants" FLEET_TMUX_SOCKET="regr-trap-$$"
mkdir -p "$FLEET_HOME" "$FLEET_INSTANTS"

I="$("$FLEET" init --name trapCoord --base 00000000 --optype append --porcelain \
      | awk -F'\t' '$1=="path"{print $2}')"
[ -n "$I" ] || { echo "FAIL: init produced no path"; exit 1; }
mkdir -p "$I/evidence"; echo proof > "$I/evidence/p.txt"

"$FLEET" milestone --instant "$I" --id m1 --title "the landed one" --status ready >/dev/null 2>&1
"$FLEET" milestone --instant "$I" --id m2 --title "depends on m1" --dep m1      >/dev/null 2>&1

status_of() { python3 -c "
import json,sys
d=json.load(open(sys.argv[1]))
print(next(m['status'] for m in d['milestones'] if m['id']==sys.argv[2]))" "$I/.fleet/roadmap.json" "$1"; }

"$FLEET" propose --instant "$I" --milestone m1 --status done \
  --evidence "$I/evidence/p.txt" --note "the real report" >/dev/null 2>&1
"$FLEET" apply --instant "$I" --milestone m1 >/dev/null 2>&1
[ "$(status_of m1)" = "done" ] || { echo "FAIL: setup did not land m1"; exit 1; }

# The trap: a stale proposal from an earlier round, applied without reading it.
"$FLEET" propose --instant "$I" --milestone m1 --status awaiting-ci \
  --evidence "$I/evidence/p.txt" --note "stale, from an earlier round" >/dev/null 2>&1
"$FLEET" apply --instant "$I" --milestone m1 >/dev/null 2>&1

after="$(status_of m1)"
if [ "$after" = "done" ]; then
  echo "SI-48 IS FIXED: apply held m1 at done. Update harvesting-an-instant/SKILL.md half two item 2,"
  echo "and mark SI-48 closed in docs/superpowers/fleet-infra-backlog.md."
  echo "FAIL"
  exit 1
fi

blocked="$("$FLEET" roadmap --instant "$I" --porcelain 2>/dev/null | awk -F'\t' '$1=="not-ready" && $2=="m2"' | wc -l)"
if [ "$blocked" -lt 1 ]; then
  echo "FAIL: m1 regressed to '$after' but m2 did not go back to not-ready — the cascade claim is wrong"
  exit 1
fi

echo "PASS: the hazard is live — m1 regressed done -> $after at rc=0, and m2 went back to not-ready"
exit 0
```

Then `chmod +x skills/harvesting-an-instant/tests/regression-trap.sh`.

- [x] **Step 2: Run it**

Run: `bash skills/harvesting-an-instant/tests/regression-trap.sh`
Expected: `PASS: the hazard is live — m1 regressed done -> awaiting-ci at rc=0, and m2 went back to not-ready`

- [x] **Step 3: Confirm discovery**

Run: `bin/superpowers-selftest`
Expected: GREEN.

- [x] **Step 4: Commit**

```bash
git add skills/harvesting-an-instant/tests/regression-trap.sh
git commit -m "skills: pin the SI-48 apply-regression hazard the harvest skill warns about"
```

---

### Task 7: `maintaining-a-roadmap`

**Files:**
- Create: `skills/maintaining-a-roadmap/SKILL.md`
- Test: `skills/maintaining-a-roadmap/tests/lint-self.sh`

**Interfaces:**
- Consumes: the unknowns-ledger vocabulary (`kind=delivery|question|probe`) from Task 1.
- Produces: the skill name `maintaining-a-roadmap`.

**Content source:** spec §5.

- [x] **Step 1: Write the failing test**

Create `skills/maintaining-a-roadmap/tests/lint-self.sh` with the Task 1 Step 1 content. `chmod +x` it.

- [x] **Step 2: Run test to verify it fails**

Run: `bash skills/maintaining-a-roadmap/tests/lint-self.sh`
Expected: FAIL — no `SKILL.md`.

- [x] **Step 3: Write the skill**

Frontmatter verbatim:

```markdown
---
name: maintaining-a-roadmap
description: Use when putting work on the milestone registry or changing what is already there - writing a title exactly as wide as the finding it carries, adding dependencies that must exist when typed, retiring superseded rows with a reason the successor needs, and ranking the ready population without overriding a blocker. Triggers include "raise a milestone", "a finding just landed", "re-rank the priorities", "retire that row", "the roadmap is out of date".
---
```

Body, the six numbered rules from spec §5, with rule 1 (title width) first and expanded — both failure directions, and why too broad is worse than too narrow. Rule 4 documents the `SI-44` workaround and names it as a workaround, quoting the live instance whose violation grades green. Then the four-row Red Flags table.

Required citations: `H1` for derived readiness, `H9` for carry-across running on `fleet milestone`.

- [x] **Step 4: Run test to verify it passes**

Run: `bash skills/maintaining-a-roadmap/tests/lint-self.sh`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add skills/maintaining-a-roadmap
git commit -m "skills: maintaining-a-roadmap, keep the registry exactly as wide as the truth"
```

---

### Task 8: `auditing-a-dispatch-history`

**Files:**
- Create: `skills/auditing-a-dispatch-history/SKILL.md`
- Test: `skills/auditing-a-dispatch-history/tests/lint-self.sh`

**Interfaces:**
- Consumes: the audit-trail obligations stated by Tasks 2 and 5 (what a dispatch and a harvest each leave behind).
- Produces: the skill name `auditing-a-dispatch-history`.

**Content source:** spec §6.

- [x] **Step 1: Write the failing test**

Create `skills/auditing-a-dispatch-history/tests/lint-self.sh` with the Task 1 Step 1 content. `chmod +x` it.

- [x] **Step 2: Run test to verify it fails**

Run: `bash skills/auditing-a-dispatch-history/tests/lint-self.sh`
Expected: FAIL — no `SKILL.md`.

- [x] **Step 3: Write the skill**

Frontmatter verbatim:

```markdown
---
name: auditing-a-dispatch-history
description: Use when making a dispatch auditable as it happens, or reconstructing afterwards what a dispatch contributed to a milestone - joining milestones to the instants that moved them, their evidence, and the PR positions that carry the result. Triggers include "what did that instant contribute", "is anything unaccounted for", "show me the dispatch history", "reconcile the completed instants".
---
```

Body, per spec §6: the forward direction (what every dispatch leaves, in one place), the backward direction (milestone → instants → evidence → PR positions), a pointer handing the human-facing board to `superpowers:rendering-task-board`, and the two rules the audit machinery itself must obey — a check that returns zero states what it examined, and a long delegation produces incremental artifacts. Then the three-row Red Flags table.

- [x] **Step 4: Run test to verify it passes**

Run: `bash skills/auditing-a-dispatch-history/tests/lint-self.sh`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add skills/auditing-a-dispatch-history
git commit -m "skills: auditing-a-dispatch-history, both directions of the trail"
```

---

### Task 9: Route from `coordinating-instants`, and prove the set is discovered

**Files:**
- Modify: `skills/coordinating-instants/SKILL.md` — insert a routing section after "The loop"

**Interfaces:**
- Consumes: all six skill names from Tasks 1–8.
- Produces: nothing further.

- [x] **Step 1: Add the routing section**

Insert after the loop table in `skills/coordinating-instants/SKILL.md`, before "Two judgements the tool cannot make":

```markdown
## When a phase has a routine

The loop above is the mechanism. Four of its phases have a worked routine of their own, and a
multi-milestone effort delivering a stacked chain of PRs should be run from the umbrella rather than
from this table alone:

| You are about to | Load |
|---|---|
| stand up or resume the whole effort | `superpowers:running-a-stacked-effort` |
| put several workers on one shared base | `superpowers:dispatching-a-wave` |
| turn the wave's siblings into one PR chain | `superpowers:integrating-a-pr-stack` |
| gate, close and empty a finished worker | `superpowers:harvesting-an-instant` |
| raise, retire or re-rank milestones | `superpowers:maintaining-a-roadmap` |
| reconstruct what a dispatch contributed | `superpowers:auditing-a-dispatch-history` |

This skill stays the authority on the verbs, the refusals and the nine phases; the routines above are
what those phases look like when the effort is large enough to have waves.
```

- [x] **Step 2: Verify the modified skill still lints**

Run: `bash skills/coordinating-instants/tests/lint-self.sh`
Expected: PASS. The new section names no `fleet` verb in a code span and makes no refusal claim, so neither V1 nor V2 should have new work.

- [x] **Step 3: Verify every new skill is discovered and green**

Run: `bin/superpowers-selftest`
Expected: `VERDICT: GREEN` and `19 passed, 0 failed, of 19 discovered`.

The baseline measured 2026-09-05 is **11 discovered suites**; this plan adds **8** (6 × `lint-self.sh` +
`wave-sequence.sh` + `regression-trap.sh`). If the baseline has moved because other work landed, the
invariant to check is +8, not the literal 19.

- [x] **Step 4: Verify the frontmatter of all six parses**

Run:
```bash
for s in running-a-stacked-effort dispatching-a-wave integrating-a-pr-stack \
         harvesting-an-instant maintaining-a-roadmap auditing-a-dispatch-history; do
  printf '%-32s ' "$s"
  awk '/^name:/{n=$2} /^description:/{d=1} END{print (n && d) ? "ok" : "MISSING"}' "skills/$s/SKILL.md"
done
```
Expected: `ok` on all six, and each `name:` matching its directory.

- [x] **Step 5: Commit**

```bash
git add skills/coordinating-instants/SKILL.md
git commit -m "coordinating-instants: route to the six routine skills"
```

---

## Self-review notes

- **Spec coverage.** Spec §"shared spine" → Task 1 step 3 section 4. §1 → Task 1. §2 → Tasks 2–3. §3 → Task 4. §4 → Tasks 5–6. §5 → Task 7. §6 → Task 8. §"How these skills get verified" → the `lint-self.sh` in every task, the two V3 suites, and the Global Constraints' cite-by-symbol rule. §"Infra dependencies" → not implemented by design; Tasks 3 and 6 pin two of them so the skills self-correct when they are fixed.
- **Naming consistency.** `lint-self.sh` is the same script in six places by design — it derives its own skill path, so it is genuinely identical, not near-duplicated. The two V3 suites have distinct names (`wave-sequence.sh`, `regression-trap.sh`) because `superpowers-selftest` discovers by path glob and prints the filename in its verdict.
- **The two hazard-pinning suites are deliberately inverted tests.** They pass while a defect exists and fail when it is fixed. Each prints, on failure, the exact remedial edit and the file to mark. This is unusual and is called out in both scripts so a future reader does not "repair" them.

---

## Execution record — 2026-09-05

All nine tasks executed inline (`superpowers:executing-plans`), on `live`. Final state:
**`19 passed, 0 failed, of 19 discovered` — VERDICT: GREEN**, matching the predicted 11 + 8.

**Deviation.** The five remaining `tests/lint-self.sh` harnesses were created in one batch after Task 1
rather than one per task. The red half of each task was still observed individually (each reported
`lint-skill: no SKILL.md`), but `bin/superpowers-selftest` was legitimately RED between Tasks 3 and 9,
because four skills had a discovered suite and no `SKILL.md` yet. Task 3's step 3 expected GREEN and got
RED for that reason. No behaviour changed; the intermediate signal was noisier than the plan described.

**Three corrections the lint forced**, each caught before the work was called done:

1. `integrating-a-pr-stack` — a prose sentence used "cannot" and tripped V2 with no `fleet` refusal to
   cite. Reworded rather than cited: attaching an unrelated passing case is the "green and irrelevant"
   pairing `lint-skill.py`'s own docstring warns it cannot detect.
2. `harvesting-an-instant` — `H4` (empty evidence refused) was cited beside a claim about an open finding
   blocking a `READY` verdict. Replaced with `I2`, which is that claim exactly.
3. `maintaining-a-roadmap` — `H10` was cited for milestone-id uniqueness and is about the
   milestone↔instant join. No integration case covers id uniqueness, so the citation was removed and the
   sentence now says where the guarantee actually is proven (`fleet`'s hermetic suite). The file-level V2
   check would have passed on the other two citations; that is the loophole, not a licence.

**Both inverted suites pass, meaning both hazards are still live:**

- `wave-sequence.sh` — 7/7, including "SI-47 still open: no roadmap row names a ready milestone" and
  "an init-created coordinator does not count against the cap".
- `regression-trap.sh` — "the hazard is live — m1 regressed done -> awaiting-ci at exit 0, and m2 went
  back to not-ready".
