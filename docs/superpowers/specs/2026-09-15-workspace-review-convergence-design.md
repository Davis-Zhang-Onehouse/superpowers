# Design: workspace review that converges — hunt once, receive with discipline, close by rule

Date: 2026-09-15
Status: Approved (brainstorming, approach A); revised after one subagent design review; pending implementation

## The problem, measured

Six completed instants of the `hudiOSSBranchBackPortToInternal` effort ran the
`superpowers:reviewing-workspace` pipeline before `fleet complete`. Two were named by the operator
as oscillating — each round's fixes seeded the next round's findings — and the other four were
checked for new patterns. Their ledgers (`.fleet/review.json`; "slot heads" is the repo HEAD the
verb recorded at each round, a proxy for the reviewed tip — see §4):

| instant | rounds / findings | distinct slot heads | shape |
|---|---|---|---|
| githubciinventoryandreleaseproof | 10 / 78 | 5 | format×2 → code×3 → alignment×2 → all×3; every stage found the tip had moved under the previous stage's runtime proofs (OI-9, OI-15) |
| prcompliancepolicygate | 6 / 39 | 5 | every round moved the tip; R2, R3, R4 each found a defect **introduced by the previous round's fix** (OI-11) |
| readerdepsalignmentdiffstudy | 17 / 118 | 0 recorded | 59 self-inflicted issues; ~20 are "the correction reached k of N sites"; each round added a gate and the next round reviewed the gate — "the REVIEWING became the deliverable" (CV-5) |
| trowportingandcdcalignment | 9 / 56 | 4 | three stages + two CI-settle closures + an operator ruling round (RV-43) + coordinator; RV-38 "four stale numbers introduced by the fix pass" |
| prstacklinearisationandgreenci | 6 / 51 | 2 | operator ruled "ONE round"; three stages + closure + coordinator — converged (CV-9) |
| ossstacksplitandinternalrefork | 2 / 31 | 1 | all three lenses in **one wave against a frozen final tree**; fixes were doc-only — converged in one pass |

Five oscillation mechanisms, each with a named instance:

1. **Fix-introduced regression in the deliverable.** prcompliance: R1's `infra_fail` called `exit 2`
   inside `$( )` → R2 (RV-9); R2's URL anchoring refused `/pull/760/files` → R3 (RV-16); R3's
   classifier read only stdout while `gh pr view` reports on stderr → R4 (RV-21); R4's coverage
   gate hard-coded exit statuses `0 1 2` → R5 (RV-29). OI-11's root causes: fix written then a test
   that passes it; only the input being fixed was tested, never its neighbours; a test stub kinder
   than the real tool; 3–10 changes per commit.
2. **Delta-only review cannot see the original surface, and scope alone does not fix it.** The
   greedy title-header regex (RV-25, a bypass present since the first commit) survived four rounds.
   R1 *had* code-reviewed the whole of that commit and missed it; what found it in R5 was the
   framing — the reviewer was handed the earlier defects "as a family, and told to assume the next
   one was still present". Delta review is nevertheless *exactly* what catches mechanism 1 — the two
   lenses belong to different rounds, not the same one.
3. **Every fix moves the tip; every tip move stales every runtime proof.** githubci re-captured both
   release-path runs twice (OI-9) and five artifacts went stale behind a moving tip (OI-15).
   prcompliance RV-22: the staleness defect "recurred inside RV-17's own close-out" — documents were
   updated to name the new head while the artifacts stayed at the old one. Both instants wrote their
   own `refresh-at-head.sh`.
4. **Correction non-propagation.** A claim lives in N sites; the fix reaches k<N; the next round finds
   the rest; the summary layer ("four rounds ran", "58 cases", "fourteen defects") goes stale on every
   round by construction. readerdeps I-10/11/14/25/41/46/54/57/58/59; prcompliance RV-18/20/23/36;
   githubci RV-49/58/60. The ledger side of the same defect: `applied` recorded, tree unchanged
   (prcompliance RV-17; readerdeps I-7/9/10 "FIXED prematurely").
5. **Instrument spiral.** A finding's remedy becomes a new gate; the gate has its own defect (a
   negative control never seen to fail, an exemption that matched the corrected text, a scan of a
   directory it could not read); the next round reviews the gate. readerdeps went sixteen rounds this
   way and its 59 issues are all defects in instruments, none a wrong conclusion about the code. Its
   round-4 withdrawal gate would have passed every "responsible instrument" test and still shipped
   with the registers outside its scope (I-11) — a rule about *how* to build gates bounds this
   mechanism; only a stop rule breaks it.

Round accounting inflates the counts — a round is one `fleet review` call, so a stage split over two
calls or a one-finding CI-settle closure each count as a round — but the oscillation is real
underneath it: two instants recorded five distinct heads each, and each head's round raised new
blocking findings.

What converged, and why: one wave of three lenses against a frozen tip (ossstacksplit); a
whole-artifact pass with the defect family named (prcompliance R5); "revert each fix and confirm the
suite goes red" (prcompliance R2 onward); and an operator's "one round" ruling that the worker read
as a rule about what rounds may *do*, not their count (prstack).

The current skill has none of this. It has no concept of a closure round distinct from a hunt, no
fix discipline (findings → "auto-fix mechanical, flag judgment", then the next stage), no stop
rule, its Stage 3 is delta-since-last-round *by design*, and its Stage 1 auto-fixes in line — which
moved the tree under the other lenses and once destroyed an mtime-based proof (readerdeps I-4).

## Goal

A review that finds what it can find in one whole-tree pass, receives those findings in a way that
does not seed the next pass, closes by a bounded rule, and stops — with the tool naming the pattern
when it sees it and the skill owning the judgment.

## Non-goals

- Changing what the format and alignment reviewers *look for*. Their prompts are tuned and their
  findings were real; the defect is in the loop around them.
- A `--kind hunt|closure` field on `fleet review`, or an explicit reviewed-tip argument. The tool's
  signal stays the slot HEAD it already records; the kind lives in the narrative.
- A refusal in `fleet review`. Measured on the six ledgers, a head-epoch refusal fires on githubci's
  first-ever alignment round (R6) — a false positive — and refusing to *record* a round leaves the
  completion gate reading the previous, cleaner round. Advisories only.
- An admission check that an `applied` finding's `action` names a commit, path or sweep. Measured:
  486 of 758 real `applied` findings would fail it, most legitimately terse ("dropped the parameter",
  "doc corrected"). Whether an action names what closed it is the closure reviewer's reading.
- A shipped `refresh-at-head.sh` skeleton. Artifact conventions differ per instant; the skill carries
  the four-line pattern (copy, then verify against `git show HEAD:<path>`, exit non-zero) and the rule.
- Touching the coordinator's `CV-` verification rounds or the harvest gate.

## Decisions from brainstorming and review

1. Skills, plus one small `fleet review` change: two advisory rows, no refusal (the brainstorm chose
   "advisory + refusal"; the design review showed the refusal's only measured non-oscillating target
   was a first-lens round, and that its `--override` would be typed by the worker it polices).
2. Stop rule: hunt once; every later round is a closure round; a closure that finds a
   fix-introduced blocking defect is allowed once; a second stops the loop and routes to the operator.
   Counted in **receive passes**, which the worker performs and records — not in ledger rounds,
   which the tool cannot classify.
3. The fix-phase discipline is a **new sibling skill**, `superpowers:receiving-workspace-review`,
   mirroring the `requesting-code-review` / `receiving-code-review` pair. `reviewing-workspace` is
   rewritten around hunt/closure and keeps its reviewer prompts.
4. Instruments: a finding's remedy is the fix. A new gate is written only when the same class has
   recurred inside this instant, ships with a negative control the author watched fail, and an
   exemption is never widened to make a gate pass. Instruments are not deliverables unless the
   charter names them. This bounds mechanism 5; the stop rule breaks it.
5. Approach A over B (two-wave hunt ordered by invalidation) and C (bolt-on): A gets B's benefit by
   ordering the receive phase code → proofs → docs instead of splitting the hunt.

## §1 — Round model and ledger semantics

Two kinds of round. `fleet review --scope` keeps its four values; the kind is declared in
`REVIEW-NARRATIVE.md` and enforced by what the round is allowed to contain.

| | Hunt | Closure |
|---|---|---|
| when | once per review, at a frozen sha `T0` written into `REVIEW-NARRATIVE.md` before any reviewer is dispatched. A pre-complete review and an optional mid-effort review are separate reviews, each with its own `T0` | after every receive pass |
| who | three read-only reviewers in **one wave** (three = the charters' fan-out cap): format, alignment, code — all told `T0` | one read-only closure reviewer |
| looks at | the whole instant; the code lens reviews this instant's whole authored delta `merge-base(T0, target)..T0` **with the defect-family framing** (§3) | the ledger's findings, the fix delta `T_{n-1}..T_n`, the withdrawals list, the recorded sha of every runtime proof |
| may raise | anything | (a) a restatement of an earlier id carrying its closure verdict; (b) a new finding inside the fix delta, its `finding` text prefixed `fix-introduced — `; (c) a new finding **outside** the delta, recorded `open` like any other — it blocks the gate and the stop rule decides what happens next. `routed` keeps its one meaning: a file this instant does not own |
| recorded as | one call per reviewer at the same head, each carrying that lens's own `--scope` (`format`, `alignment`, `code`); scopes accumulate across rounds, so the gate's `all` is the union (a session that dies mid-wave loses one reviewer's findings, not three). The verb has no `--note`; the kind goes in the narrative | one call |

**Frozen tip.** Before the hunt the worker captures every runtime proof at `T0` — the charters'
existing "proof captured after the final commit, on a clean worktree" rule — and does not commit
again until the hunt returns. Reviewers are handed the sha, never a branch name. **Reviewers are
read-only; every fix, mechanical or not, goes through receive.**

**No colon in a finding's text.** `--finding` is split on the first five colons, so a colon inside
`location` or `finding` silently truncates the finding and swallows the rest into `action`
(`cli.py` `_finding_of`; the charters' trap 7). Locations are written `file line N`, prefixes with
an em dash. Zero of the 373 real findings carry a colon; the skill keeps it that way.

**`applied` names what closed it.** The four statuses stay. An `applied` finding's `action` names a
commit sha (repo change), an artifact path (evidence change) or `sweep — N sites` (claim fix). The
closure reviewer records an `applied` whose action names nothing it can check as `NOT-CLOSED`;
prcompliance RV-17 was exactly this. (Not a tool refusal — see Non-goals.)

**Closure verdict per finding**, in the restated finding's `action`:
`CLOSED — <what was checked>` · `NOT-CLOSED — <what is still wrong>` (status back to `open`) ·
`REGRESSED — <new id>` (the regression is its own `fix-introduced — ` finding).

**Stop rule**, counted in receive passes (pass 1 receives the hunt; pass *n* receives closure *n−1*).
The worker writes the pass number at the top of each pass's triage table in the narrative and
hands it to the closure reviewer.
1. A closure with no `NOT-CLOSED`, `REGRESSED`, `fix-introduced` or outside-the-delta blocking
   finding → verdict `READY` (`READY-WITH-FIXES` if only Minor/Nit remain). Done.
2. Closure after pass 1 found blocking work → pass 2, then closure 2.
3. Any Critical/Important item still standing after pass 2 — a `NOT-CLOSED`, a `REGRESSED`, a
   **fix-introduced** or an outside-the-delta item — or an outside-the-delta item that needs new
   deliverable work at any pass → stop. Record the round `NOT-READY` (which refuses
   `fleet complete`), name the defect family in HANDOFF next-actions, `fleet park` with the
   question. No third receive pass on the worker's own authority.
4. The worker never opens a second hunt against the same review. Only an operator instruction
   does; `/review-workspace` (the default kind) is how it is invoked, and the narrative records who
   asked.

**What blocks, stated plainly.** `fleet complete` runs the review gate: a newest round `NOT-READY`,
or any `open` Critical/Important, refuses the rename. `fleet propose --status done` refuses a head no
round has seen (`review-head`). Nothing else blocks; `routed`, `wont-fix` and Minor/Nit never do.
The old "advisory, never blocks" sentence is deleted from the skill.

**Coordinator rounds** (`CV-` ids, recorded at the same head) are unchanged; the detector excludes
`CV-` ids from its raising test (§4).

## §2 — `superpowers:receiving-workspace-review` (new skill)

**Trigger:** a hunt or closure round has returned findings and the worker is about to act on them.
Also: "apply the review findings", "fix what the reviewers found", "close out RV-…",
"the review came back with N findings". The tool nudges too: recording a round with blocking
findings prints an advisory naming this skill (§4).

**Core principle:** a batch of findings is received once, in an order that cannot stale itself,
and each fix is proven not to have seeded the next round before it is recorded `applied`.

**Relation to `superpowers:receiving-code-review`.** Its verification rules apply in full — read
everything first, verify each finding against the tree, push back with technical reasoning, no
performative agreement. Two of its rules are **replaced** here: its implementation order
(blocking → simple → complex) becomes the batch order below, with blocking-first applying *within*
the deliverable class; and a refused finding is recorded `wont-fix` with the reason through
`fleet review --finding` rather than argued in chat.

Target length: the sibling's (~200 lines). The triage table is the artifact the worker fills; the
steps are what the columns mean.

### Step 0 — triage the whole batch before touching anything

Write the triage table into `REVIEW-NARRATIVE.md` under the round, headed by the pass number:

| id | class | sites / commit | order | closed by |
|---|---|---|---|---|

`class` is exactly one of:

| class | what it changes | moves the tip? |
|---|---|---|
| `deliverable` | code, scripts, workflows, tests — anything that ships | yes |
| `proof` | a runtime artifact under `evidence/` | no, but depends on the tip |
| `claim` | a statement in a document: HANDOFF/DECISIONS/ISSUES/ASSUMPTIONS/INDEX/RUNBOOK/PR body/README prose | no |
| `routed` / `wont-fix` | nothing here | no |

### Step 1 — deliverable fixes, one finding per commit

In severity order:
- **Failing test first** — the case that reproduces the finding, watched to fail (OI-11 cause 1).
- **Neighbour inputs** — before narrowing or widening a matcher, list what it currently accepts that
  the change excludes and what it rejects that the change admits; one case per neighbour (OI-11
  cause 2: `/pull/760/files`).
- **Test doubles are recordings** — a stub for an external tool is written from the real tool's
  captured exit status, stdout and stderr (OI-11 cause 3; RV-28).
- **Revert to red** — revert the fix, run the suite, see it fail, restore.
- **One finding, one commit**, subject naming the `RV-` id.

`superpowers:test-driven-development` governs the mechanics.

### Step 2 — refresh runtime proofs once, at the new tip

After the last deliverable commit, and only then. For each runtime artifact (test run, CI
enumeration, suite baseline, checker output), one of:
- **Re-capture** at `T_n`. The artifact names its sha in the file. **Never overwrite the prior
  artifact**: rename it `…-at-<sha>` and keep it (githubci RV-65 lost a cited success log; trow
  RV-17/34 kept superseded bench runs and was better for it).
- **Unaffected by construction** — the delta cannot reach what the artifact measures (prcompliance
  OI-9: "every commit here touches only `.github/`"). The argument is written as its own artifact
  naming the delta and the paths, and the INDEX row cites it. Not available for the deliverable the
  fix touched.
If more than one artifact is re-captured, the instant's `refresh-at-head.sh` does it (write one if
absent: copy, then verify each copy against `git show HEAD:<path>` and exit non-zero on mismatch —
the verification is the point).

**Blast radius of file state.** Before Step 3 edits a file, note which proofs read that file's
*state* — an mtime, a hash, a line number — and re-derive them after (readerdeps I-4: a header
added by a format fix destroyed an mtime-ordering proof).

### Step 3 — claim fixes, by propagation sweep

For each `claim` finding, before editing:
- **Enumerate the sites.** `grep -rn` the old value or phrase over the population: every file under
  the instant, the shipped files the finding names (README, workflow comments, PR body), and any
  sibling document named. Edit every site. A site in a file this instant does not own is `routed`.
- **Exports carry the destination text.** An amendment routed to a document this instant does not
  own quotes the destination *as it will read after the edit* — readerdeps I-30: the amendment was
  right and applying it would have left the target self-contradictory.
- **Withdrawals list.** Append `old value → new value → sites` to
  `evidence/review/withdrawals-pass<n>.txt`. The closure reviewer greps every old value. **A claim
  corrected by rewording has no old value to grep** and is closed by reading the sites, never by a
  clean grep (readerdeps I-58).
- **Documents state the truth.** History of what a sentence used to say goes to `ISSUES.md`, not into
  the sentence (trow RV-43, an operator ruling).
- **Counts are derived or absent.** A cardinal is written with the command that derives it or
  replaced by a pointer to the document that owns it (readerdeps I-14/I-25).
- Order: registers → `evidence/INDEX.md` → HANDOFF → RUNBOOK → shipped prose. HANDOFF last, because
  it summarises the others.

### Step 4 — record

`fleet review --finding` per finding: `applied` with the commit / artifact / `sweep — N sites` in
`action`; `routed` with the owner; `wont-fix` with the reason. **Nothing is recorded `applied`
before it exists on disk** — the record is written after the pass, from the triage table, against
the tree (prcompliance RV-17).

### Step 5 — hand to the closure round

`superpowers:reviewing-workspace` with `--closure`, giving `T_{n-1}`, `T_n`, the pass number and
the withdrawals list.

### Instruments

A finding's remedy is the fix to the thing found. A new script or gate is written only when all
three hold: the same class has already recurred inside this instant; it ships with a negative
control the author watched fail; its exemptions are enumerated and none is widened to make it pass
(reword the prose instead — readerdeps I-14). A gate idea that fails the first test goes to HANDOFF
next-actions as a proposal.

### Red flags

| Thought | Reality |
|---|---|
| "I'll fix these as I read them" | Triage first. code → proofs → docs is what stops the docs from staling. |
| "The suite is green, so the fix is in" | It was green before the fix too. Revert to red. |
| "I fixed the input the reviewer named" | And what else does the matcher now accept or refuse? Neighbours. |
| "I'll update HANDOFF to name the new head" | Documents follow artifacts. Refresh the proof, then write the number it produced. |
| "One commit for all the small ones" | One finding per commit. Bundling hid four defects in one round. |
| "A gate will stop this recurring" | Second occurrence? Negative control you watched fail? If not: fix, and propose the gate. |
| "I'll mark it applied now and do it next" | `applied` is recorded from the tree, after the pass. |
| "The grep is clean, so it propagated" | Only for exact old values. A rewording is closed by reading. |

## §3 — `superpowers:reviewing-workspace` rewritten around hunt and closure

Kept: `reviewers/format-reviewer.md` and `reviewers/alignment-reviewer.md` (each gains: "review
the tree at `[REVIEW_TIP]`; a runtime proof whose recorded sha is not `[REVIEW_TIP]` is stale; you
are read-only — report, never fix"); the ledger-discipline section; the routed-vs-open rule.

Changed:

- **Pipeline.** Stage 0 freeze (`T0` into the narrative; proofs captured at `T0`; no further commits)
  → Stage 1 hunt (three reviewers, one wave) → Stage 2 receive
  (`superpowers:receiving-workspace-review`) → Stage 3 closure (one reviewer) → stop rule → Stage 4
  close (narrative, HANDOFF session-log row). The lenses run together because fixes between them
  are what moved the tip under each next lens; Stage 1's in-line auto-fix is gone.
- **Code lens at the hunt.** `reviewers/README.md`'s delta section is replaced: the base is the PR's
  merge-base with its target on every hunt; the prompt carries a **defect-family list** — the
  charter's traps, the classes in this and the parent instants' `ISSUES.md`, and the effort's
  standing rules — with the instruction to assume the family's next member is present in the
  unchanged code (prcompliance R5 is the evidence; whole scope alone missed RV-25 in R1). The
  previous round's `heads` are used only by the closure reviewer, as `T_{n-1}`.
- **New `reviewers/closure-reviewer.md`.** Placeholders: `[INSTANT_PATH]`, `[REPO_PATHS]`,
  `[T_PREV]`, `[T_NOW]`, `[PASS_NUMBER]`, `[WITHDRAWALS_PATH]`, `[DEFECT_FAMILY]`. It reads
  `.fleet/review.json` itself. Checklist:
  1. every finding not `routed`/`wont-fix`: open the location; check the action's named commit /
     artifact / sweep exists and does what it says → `CLOSED | NOT-CLOSED`;
  2. `git diff [T_PREV]..[T_NOW]` — the fix delta only, with `[DEFECT_FAMILY]` and "assume the next
     member is in this delta"; a defect → a `fix-introduced — ` finding located in the delta;
  3. grep every old value in the withdrawals list over the population → a hit is `NOT-CLOSED`
     against the finding that withdrew it; reworded claims are checked by reading their listed sites;
  4. every runtime artifact under `evidence/` names a sha equal to `[T_NOW]`, or its INDEX row cites
     an unaffected-by-construction or point-in-time artifact;
  5. anything found outside the delta is reported under *outside the delta* with a severity; the
     orchestrator records it `open`;
  6. output: the per-finding table, the delta findings, the withdrawal hits, the proof-sha table,
     the outside-the-delta list, and one line `CLOSURE: CLEAN | REOPEN | ESCALATE` computed from
     what it found and `[PASS_NUMBER]` by the §1 stop rule.
  Read-only; no subagents; no hunt.
- **Kind selection.** `/review-workspace` is a hunt by default — pre-complete and mid-effort alike.
  `--closure` marks a closure round and requires `T_{n-1}`, `T_n`, the pass number and the
  withdrawals path. `--note` is dropped (the verb has none; harvest's doc already says so).
- **`templates/REVIEW.md`** is deleted (the verb renders `REVIEW.md` in its own shape and discards
  it) and replaced by `templates/REVIEW-NARRATIVE.md`: `T0`, kind, reviewer wave, the triage table
  per pass, the stop-rule outcome.
- **Quick Reference and Common Mistakes** rewritten. New rows: reviewing a branch name instead of a
  sha; a second hunt on the worker's own authority; a closure round that "also had a look around"
  (record it `open`, then the stop rule); an in-line fix by a reviewer; `routed` used for a finding
  in a file this instant owns.

## §4 — `fleet review`: two advisories

Both are `Review.advisories()` rows: non-vetoing by construction, printed by every `fleet review`
call, computed from the ledger alone.

**A. `OSCILLATING`.** Group consecutive rounds into *head epochs*: a round joins the current epoch
when its `heads` equal the previous round's and opens a new one when they differ; empty `heads`
(NOT MEASURED) join the current epoch. An epoch *raises* when any of its rounds carries a finding
id first seen in that epoch, severity Critical or Important, **id not prefixed `CV-`**. The streak is
the number of trailing consecutive raising epochs. Advisory at streak ≥ 3:
`OSCILLATING — <n> consecutive head-moving epochs each raised new Critical/Important findings
(rounds …). Under superpowers:reviewing-workspace a closure round that raises is allowed once; the
next stops the loop and routes to the operator.` The signal is the slot HEAD at record time, which
is not always the reviewed tip (ossstacksplit's narrative names `a79c9ab`; its ledger records
`aaa084dd`); it is a proxy, said so in the row, and it is why this is an advisory.

Calibration on the six real ledgers (recomputed independently by the design reviewer; kept as
fixtures):

| instant | epochs | streak | advisory (≥3)? |
|---|---|---|---|
| githubci | 5 (`49ed1b36` R1–2, `6be46706` R3–4, `f849a826` R5, `856dca25` R6–7, `b3adac91` R8–10) | 5 | yes, from R5 (epoch 3) |
| prcompliance | 5 (`bba773b8`, `99e1a94b`, `b43c7542`, `196ae708`, `2fe762f6` R5–6) | 5 | yes, from R3 (epoch 3) |
| readerdeps | 1 (no heads recorded) | 1 | no — doc-only oscillation is the skill's to stop |
| trow | 4 (`7e5fa144`, `e4de1e2c` R2–3, `fc0126c5` R4–5, `aaa084dd` R6–9) | 4 | yes, from R4 (epoch 3) |
| prstack | 2 | 2 (CV- excluded: still 2 — R3–5 raise RV-27/37/40) | no |
| ossstacksplit | 1 | 1 | no |

**B. `RECEIVE`.** When the round just recorded carries any finding with blocking severity and status
`open` or `applied`: `<n> blocking finding(s) recorded — apply them with
superpowers:receiving-workspace-review: triage, then code → proofs → docs, one finding per commit,
applied only from the tree.` This is the one part of the receive discipline the tool can carry;
OI-11 records a worker that had `receiving-code-review` and did not apply it.

**Unchanged:** the gate, `add_round`, `--dry-run` (advisories already reflect the ledger without the
dry-run round; the row says so), the `--finding` grammar.

**Tests** (`fleet/tests/test_review.py`, fixtures under `fleet/tests/fixtures/review-ledgers/` as the
six real ledgers reduced to `number/scope/verdict/heads/findings[id,severity,status]`): epoch
grouping with empty heads joining; the calibration table, exactly; a `CV-` Critical at a new head
does not raise; a head-moving round with only restated ids or Minor/Nit does not raise; advisory
text at streak 3 and silence at 2; `RECEIVE` fires on an applied Important and not on a Minor or a
`routed` Critical.

## §5 — edits to neighbouring skills and docs (against the files as they are)

- `skills/maintain-workspace/SKILL.md` line 105 (`REVIEW.md` layout row: "append-only review
  ledger" → generated view of `.fleet/review.json`; reasoning in `REVIEW-NARRATIVE.md`), line 132
  and 187 (pre-complete: "one hunt, receive, closure by rule"; names both skills), line 219.
- `skills/working-as-a-dispatched-instant/SKILL.md` around the `fleet review` example (line ~183):
  one sentence — the round is the hunt; findings go through `superpowers:receiving-workspace-review`;
  the closure round is recorded before `propose`. The "Finishing is five steps" list is not touched.
- `skills/harvesting-an-instant/SKILL.md` "The review gate, exactly": add `routed` to the status
  list (it is missing); one sentence on reading an `OSCILLATING` row.
- `commands/review-workspace.md`: `--closure`, drop `--note`, describe hunt-by-default.
- `RELEASE-NOTES.md` and `fleet/CHANGELOG.md`.
- No edit to `skills/using-fleet/profiles/worker/charter.md` (it carries no review rule) or the
  `using-fleet` verb table (no new flags).

## §6 — patterns from the four verification instants, and where the design accounts for them

| instant | pattern | accounted for by |
|---|---|---|
| readerdeps | doc-only oscillation invisible to repo heads; the instrument spiral; the summary layer under-counting itself three times | §1 stop rule (skill-owned; §4 says the tool is blind here and why); §2 Instruments bounds, stop rule 3 breaks; §2 Step 3 "counts are derived or absent" |
| readerdeps I-30 | an amendment exported to a *completed* milestone was right and would have made its target self-contradictory | §2 Step 3 "exports carry the destination text" |
| readerdeps I-11/27/34/46/55/58 | the withdrawals register itself failed five ways: scope excluded the registers, no completeness check, proximity rules, a hand-maintained whitelist, rewordings with no phrase to catch | §2 Step 3 states the population and the limit (rewordings closed by reading); §3 closure item 3 greps the population, not a file list |
| readerdeps I-4 | a *mechanical* format fix destroyed an mtime-based proof | §1 reviewers read-only; §2 Step 2 blast radius of file state |
| trow | CI-settle rounds recorded per poll; superseded bench runs kept as raw artifacts (RV-17/34); corrections must read true, not narrate (RV-43); OI-9's "delta provably nil" | closure waits for the `awaiting-ci` phase to clear; §2 Step 2 never-overwrite and unaffected-by-construction; §2 Step 3 "documents state the truth" |
| prstack | "one round" read as three scopes of one pipeline; routed-vs-open keeping the gate honest; guard scripts that could not fail (RV-27/28) | §1 hunt = one wave (calls per reviewer allowed); routed keeps one meaning; §2 Instruments negative control |
| ossstacksplit | run the hunt while the last CI wave is in flight so a finding costs at most one wave; one code reviewer over a 23-PR stack pointed at what the milestone authored | §1 hunt at a frozen tip; §3 code lens = whole authored delta with the family framing |
| githubci OI-16/OI-17 | a false "measured fact" found at R8 in no fix delta; an upstream regression reddening the lineage mid-review | §1 closure may raise outside the delta as `open`; stop rule 3 routes it |

## Testing

- `fleet/tests/test_review.py` as in §4, with the six reduced ledgers as fixtures.
- `skills/reviewing-workspace/tests/lint-self.sh` and
  `skills/receiving-workspace-review/tests/lint-self.sh` (house pattern: every fleet verb named in a
  code span is registered).
- Per `superpowers:writing-skills`, RED before GREEN for the receive skill: a subagent is given a
  synthetic instant and a batch of three findings — a matcher-narrowing fix with a known neighbour, a
  count claim living in three documents, and a finding whose obvious remedy is a new gate — **without
  the skill**, and its rationalisations are recorded verbatim; then the skill is written against
  them and the scenario re-run. Pass: neighbour case written; three sites swept into a withdrawals
  list; gate declined with the recurrence reason; `applied` recorded after the edits. The same for
  the closure reviewer prompt: a fixture ledger with one `applied` finding whose action names a
  commit that does not exist must come back `NOT-CLOSED`.

## Rollout

One fleet release carries the skills and the advisories (the running plugin is served from
`fleet-releases/current`). The advisories cannot refuse anything, so a worker holding old skill
text meets nothing new at the tool. The first users are the four inflight
`09141745-…-reviewfixes…` instants, which have no ledger yet and are doing receive-pass work now:
their first round under the new skill is a hunt at a frozen tip, and their ledgers are the first
data for the calibration table.

## Deliverables

1. `skills/receiving-workspace-review/SKILL.md` + `tests/lint-self.sh`; RED/GREEN evidence under
   `docs/superpowers/specs/evidence/2026-09-15-receiving-workspace-review/`.
2. `skills/reviewing-workspace/SKILL.md` rewritten; `reviewers/closure-reviewer.md` new;
   `reviewers/README.md` and both reviewer prompts amended; `templates/REVIEW.md` → 
   `templates/REVIEW-NARRATIVE.md`; `commands/review-workspace.md`.
3. `fleet/src/fleet/review.py`: `oscillation_streak()` and the two advisory rows; tests and fixtures.
4. §5 edits.
5. A fleet release (`superpowers:releasing-fleet`).
