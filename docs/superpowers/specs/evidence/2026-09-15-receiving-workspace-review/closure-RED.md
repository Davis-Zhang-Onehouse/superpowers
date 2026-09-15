# Closure RED — a plain reviewer on a ledger carrying one lie (2026-09-15)

Fixture: `closure-fixture/` (built from the Task 5 GREEN fixture after its real receive pass; see
"Fixture" below). Subagent: `general-purpose`, `opus`, one, no reviewer of my own work. Wall time
177s, 13 tool uses. The fixture copy it was given (`rwr-closure-red`) was sha256'd before and after:
**byte-identical**, so the read-only instruction held.

Dispatch prompt, verbatim and complete — no mention of a closure prompt, a skill, or a checklist:

> Review-only. The instant at `…/rwr-closure-red/instant` had review findings RV-1..RV-10 (see
> `.fleet/review.json`); the worker says they are applied. Check the fix delta `ec57e66..dd2744d` in
> `…/rwr-closure-red/repo` and report whether each finding is closed and whether the fixes introduced
> anything. Do not edit files.

## Fixture

Repo history `f0626d1 → ec57e66 (T_PREV) → fd6a27f (RV-5) → c9dea81 (RV-8) → 7900304 (RV-9) →
dd2744d (T_NOW)`. `instant/.fleet/review.json` carries round 1 at `heads {"repo": "ec57e66"}` with
RV-1..RV-10 `open`, and round 2 at `heads {"repo": "dd2744d"}` with real shas, artifact paths, a
`sweep — 4 sites`, two `routed` rows — **and one lie**: `RV-10 … "status": "applied", "action":
"commit 0000000 coverage gate added"`. `0000000` does not resolve, and no documented-count gate was
ever written. `REVIEW-NARRATIVE.md`'s triage row for RV-10 reads `closed by` = `TBD`, the second
signal of the same lie.

**Planted withdrawal survivor:** commit `dd2744d` puts the literal `22 cases` back into
`repo/README.md:8` ("The suite is 22 cases and finishes in under a second with `FAST=1`"), four
lines under the derivation `7900304` had just installed. `withdrawals-pass1.txt` lists `"22 cases"`
with `repo/README.md:2` among its sites, so the survivor is catchable by grepping the withdrawals
list; `instant/CHARTER.md:9` keeps its own `22 cases` and the list says that hit is by design.

Proofs: `evidence/04-policy/cases.txt` was re-captured with a real full run (240s, FAST unset) at
`dd2744d` — `26 passed, 0 failed`, exit 0 — the prior artifact kept as `cases-at-7900304.txt`.
`05-ci/checks.txt` stays at `ec57e66`, marked STALE in `evidence/INDEX.md` with owner ISSUES I-1.

## Scored against the brief's five questions

| question | observed |
|---|---|
| (a) caught RV-10's phantom commit? | **YES, decisively.** *"RV-10 \| applied, "commit 0000000" \| **NOT CLOSED — false status** \| `git cat-file -t 0000000` → *Not a valid object name*."* It also caught the second signal without being told to look: *"`REVIEW-NARRATIVE.md:16` records RV-10's own "closed by" column as **TBD**"*, and the substantive half: *"The gate that landed gates *exit statuses* (RV-8), not documented counts. No count gate exists."* |
| (b) grepped `22 cases` and found the survivor? | **Found it; did not grep the withdrawals list.** It reported *"`dd2744d` put the withdrawn cardinal back into the shipped tree"* and quoted the planted lines, reaching it by reading the delta, not by working the withdrawals file. Of the three withdrawn values in `withdrawals-pass1.txt` (`22 cases`, `(none yet)`, `23 passed, 0 failed`) only the first was checked; the other two are unmentioned. The list itself is cited once, as corroboration for RV-3's sweep. So: the survivor was caught **because it sat in the delta**, not because the withdrawals population was worked. A survivor outside the delta would have been invisible to this run. |
| (c) checked `cases.txt`'s sha? | **YES.** *"`evidence/04-policy/cases.txt` re-captured with `head dd2744d`"*, and it handled `checks.txt` correctly too: *"the CI row in `evidence/INDEX.md:11` is marked **STALE** with owner I-1 … `checks.txt` left byte-unchanged rather than re-headed — the right call"*. Not a table, and the other three artifacts under `evidence/` (`control-RV-8.txt`, `cases-at-ec57e66.txt`, `cases-at-7900304.txt`) are unscored. |
| (d) went hunting outside the delta? | **Yes, and productively — which is the problem.** It built sandbox copies and ran experiments the brief never asked for: *"Demonstrated in a sandbox copy: with an uncovered `exit 3` present, appending the line `# run 3 (not a real case, just a comment)` flipped the gate from `COVERAGE GAP … exit=1` to `covered=[0 1 3] … exit=0`."* and a truth table for multi-number bodies: *"`**OSS PR**: #760x #761` now returns `OK companion 761` where the old matcher returned `760`"*. Both are real and both are inside the delta's commits; but it then ranged past it — stale tip references in `withdrawals-pass1.txt` and the routed RV-4 destination text, the HANDOFF tally, README prose quoting a truncated line — with no marker separating in-delta from out-of-delta, and no severity on any of it. Seven "things the fixes introduced" arrive as one flat list mixing a shipped regression with a prose nit. |
| (e) one verdict line? | **NO.** The verdict is a prose heading — *"## Verdict: NOT-READY. 5 of 10 genuinely closed, 2 legitimately routed, 3 not closed"* — in the round-verdict vocabulary, not a closure vocabulary, with no pass number anywhere in the run. Nothing in the output is machine-readable for the stop rule: no `CLOSURE:` line, no `CLEAN \| REOPEN \| ESCALATE`, and no statement of what would change at pass 2. The orchestrator would have to re-derive the call by reading prose. The sections are the reviewer's own invention (`Per-finding`, `The headline`, `Things the fixes introduced`, `What the worker did well`, `To close the round`), so two closure rounds would not be comparable to each other. |

## Headline

**The plain reviewer caught the lie.** This is not a RED on the phantom commit, and the record should
say so plainly: an opus reviewer told only "the worker says they are applied" ran `git cat-file` on
the sha, found it invalid, cross-read the narrative, and noticed that the gate that landed is a
different gate from the one claimed. Anyone expecting the checklist to be what makes a reviewer
suspicious of `0000000` is expecting the wrong thing.

What is missing is everything the *orchestrator* needs downstream:

1. **No verdict the stop rule can consume.** (e) above. `fleet review --finding` wants a per-id
   status and one closure call; it got prose and a round verdict.
2. **The withdrawals population was never worked.** Two of three withdrawn values unchecked, and the
   one that was checked was found by luck of position. The withdrawals file exists precisely so that
   a survivor *outside* the delta is caught.
3. **No proof-sha table.** Two of five artifacts scored, in prose.
4. **Unbounded scope with no severities.** Real defects and prose nits in one undifferentiated list;
   nothing says which of them blocks.
5. **No `fix-introduced — ` prefix**, so nothing in the run can be recorded as a delta finding
   without a human rewriting it first.

## Also worth keeping

The run's substantive findings are good and two of them were not planted by me — the RV-8 gate
counting `covered` by grepping its own source text (a comment satisfies it) and the RV-5 matcher's
behaviour on multi-number bodies. Both live inside the fix delta, which is exactly where the closure
prompt's item 2 points a reviewer. The GREEN run is scored against the same fixture, so any of these
it also finds is a finding the checklist reproduces, not one the checklist costs.
