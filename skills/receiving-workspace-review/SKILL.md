---
name: receiving-workspace-review
description: Use when a review round against an effort instant has returned findings and they are about to be acted on. Triggers include "apply the review findings", "fix what the reviewers found", "close out RV-3", "the review came back with nine findings", "the closure round is next", and a `RECEIVE —` advisory printed by `fleet review`.
---

# Receiving Workspace Review

## Overview

A batch of review findings is received once, in an order that cannot stale itself, and each fix is
proven not to have seeded the next round before it is recorded `applied`. Measured on six real
instants: every round that fixed findings as it read them produced the next round's findings — a
matcher anchored for one input turned away the next (`…/pull/760/files`), a count corrected in one
document survived in three, a proof refreshed in the documents but not in the artifacts.

**Core principle:** triage the whole batch, then code → proofs → docs, one finding per commit,
`applied` written from the tree, and everything the pass convinced itself of left on disk.

**REQUIRED BACKGROUND:** `superpowers:receiving-code-review` — its verification rules apply in full
(read everything first, verify each finding against the tree, push back with technical reasoning, no
performative agreement). Two of its rules are replaced here: its implementation order becomes the
batch order below (blocking-first applies *within* the deliverable class), and a finding you decide
against is recorded `wont-fix` with its reason through `fleet review --finding`, not argued in chat —
unless it is not yours to close, then `routed` plus the parked question; see Step 4.

## Step 0 — triage before touching anything

Write this table into `REVIEW-NARRATIVE.md` under the round, headed `Receive pass <n>` (pass 1
receives the hunt; pass *n* receives closure *n−1*). Both REQUIRED slots below are part of the table;
a pass missing either is not a pass.

| id | class | sites / commit | order | closed by |
|---|---|---|---|---|

`class` is exactly one of (a finding whose halves have different owners splits into `<id>a` /
`<id>b`, one row and one class each):

| class | changes | moves the tip? |
|---|---|---|
| `deliverable` | code, scripts, workflows, tests — anything that ships | yes |
| `proof` | a runtime artifact under `evidence/` | no, but it depends on the tip |
| `claim` | a statement in HANDOFF / DECISIONS / ISSUES / ASSUMPTIONS / INDEX / RUNBOOK / PR body / README | no |
| `routed` · `wont-fix` | nothing here — owner or reason goes in the action | no |

**`closed by` is REQUIRED on every row** and names something a reader can open: a commit sha, a file
path, `sweep — N sites`, an owner, or a reason. At Step 0 a `deliverable` row's sha does not exist
yet; write `TBD` there and backfill it in Step 4, which is where the cell becomes binding. **For any
finding closed by a gate, a script, or a control run, `closed by` names an artifact path under
`evidence/`** — the run's own captured output, never a description of it.

### Noticed along the way

REQUIRED, as the last section under the triage table, written before Step 4 records anything. One
line for every defect, oddity, or doubt this pass met that no finding named — or the single word
`none`. Each line is then carried into `ISSUES.md` with an owner, or raised as a `routed` finding,
before the pass is recorded. A line that lives only in your report to the operator dies with the
session, and the next round finds it. Two baselines found real problems this way and left them in chat.

## Step 1 — deliverable fixes, one finding per commit

In severity order. `superpowers:test-driven-development` governs the mechanics; this is what to test.

- **Failing test first.** The case that reproduces the finding, watched to fail before the fix.
- **Neighbour inputs.** Before narrowing or widening a matcher, list what it currently accepts that
  the change will exclude, and what it turns away that the change will admit. One case per neighbour.
- **Test doubles are recordings.** A stub for an external tool is written from the real tool's
  captured exit status, stdout, and stderr. A stub written from belief hid a dead rule for a round.
- **Revert to red.** Revert the fix, run the suite, see it fail, restore. A regression test never
  seen to fail is the same class of object as a gate never seen to fire.
- **One finding, one commit.** The subject names exactly one `RV-` id. Two ids in one subject is a
  bundled commit; so is one id whose diff also does a second finding's work. Split it before you
  commit, not after. **No exceptions**: not "they touch the same file", not "they are both tests",
  not "the second one is two lines", not "the deadline". The file is not the unit — the finding is.
  This is the first discipline to go once the batch passes about five findings, and a bundled commit
  is what hid four defects in one real round.

## Step 2 — refresh runtime proofs once, at the new tip

After the last deliverable commit, and only then. For each runtime artifact — test run, CI
enumeration, suite baseline, checker output — exactly one of:

- **Re-capture** at the new tip. The artifact names its sha in the file, and the sha matches
  `git rev-parse --short HEAD`. **Never overwrite the prior artifact**: rename it `…-at-<sha>` and
  keep it; other documents cite it.
- **Unaffected by construction.** The delta cannot reach what the artifact measures ("every commit
  touches only `.github/`"). Written as its own artifact naming the delta and the paths; the INDEX
  row cites it. Not available for the deliverable the fix touched.

An artifact you cannot regenerate here is not re-captured by editing its header. Mark its INDEX row
stale, record the gap as its own finding, and say who can produce the real capture.

If more than one artifact is re-captured, the instant's `refresh-at-head.sh` does it. If there is
none: copy each artifact, then verify each copy against `git show HEAD:<path>` and exit non-zero on
mismatch. The verification is the point; the copying is the easy half.

**Blast radius of file state.** Before Step 3 edits a file, note which proofs read that file's
*state* — an mtime, a hash, a line number — and re-derive them after. A header added by a format fix
once destroyed an mtime-ordering proof for a different acceptance criterion.

## Step 3 — claim fixes, by propagation sweep

For each `claim` finding, before editing:

- **Enumerate the sites.** `grep -rn` the old value or phrase over the population: every file under
  the instant, the shipped files (README, workflow comments, PR body), any sibling document the
  finding names. Edit every site. A site in a file this instant does not own is `routed`.
- **Exports carry the destination text.** An amendment routed to a document you do not own quotes the
  destination *as it will read after the edit*. A correct amendment once would have left its target
  contradicting itself.
- **Withdrawals list.** Append `old value → new value → sites` to
  `evidence/review/withdrawals-pass<n>.txt`. The closure reviewer greps every old value. **A claim
  corrected by rewording has no old value to grep**: it is closed by reading its sites, never by a
  clean grep.
- **Documents state the truth.** What a sentence used to say goes to `ISSUES.md`, not into the sentence.
- **Counts are derived or absent.** A cardinal is written with the command that derives it, or
  replaced by a pointer to the one document that owns it.
- Order: registers → `evidence/INDEX.md` → HANDOFF → RUNBOOK → shipped prose. HANDOFF last; it
  summarises the others.

## Step 4 — record, from the tree

First, backfill the triage table: every `closed by` cell carries the sha, path, or owner the pass
actually produced. **A cell still reading `TBD` is an unrecorded finding.**

`fleet review --finding` per finding, after the pass, read off the triage table. The value is
`id:severity:status:location:finding:action` — six colon-separated fields, so no field may contain a
colon; write a prefix with ` — `. `applied` carries the commit sha, artifact path, or
`sweep — N sites`; `routed` carries the owner; `wont-fix` carries the reason. Nothing is recorded
`applied` before it exists on disk — one instant recorded a finding applied that no round had edited,
and the next round found it.

A finding you decided against is `wont-fix` with the reason. `routed` means a file or a decision this
instant does not own, and it leaves the finding open on someone's desk. Where both apply `routed`
wins: **a finding you decided against but are not entitled to close is `routed` plus the parked
question, never `wont-fix`** — a charter contradiction is the operator's, so `fleet park` the question.

## Step 5 — hand to the closure round

`superpowers:reviewing-workspace`, run as a closure round: the tip the findings were raised against,
the tip now, the pass number, and the withdrawals list.

## Instruments

A finding's remedy is the fix to the thing found. A new script or gate is written only when all
three hold: the same class has **already recurred** inside this instant; it ships with a **negative
control you watched fail**; its exemptions are enumerated and none is widened to make it pass —
reword the prose instead. A gate idea that fails the first test goes to HANDOFF next-actions as a
proposal. One instant spent sixteen rounds reviewing the gates its rounds had added.

**A control with no artifact is a control that did not happen.** Before the gate's finding is
recorded, write the control to `evidence/review/control-<id>.txt`: what you injected, the exact
command, its output, its exit status, and the restore you verified. **The control is run after the
commit that carries the gate, and its artifact names that commit's sha** — a control captured while
the gate was still uncommitted proves nothing about the delivered gate, because no later reader can
diff the working tree it ran against; re-run it once after the commit and keep the earlier capture,
renamed `…-at-<sha>` per Step 2. Then name that path in
`closed by`. Two baseline runs each ran a real negative control and described it in chat only; in one
the figure did not reproduce from the description, and in both the only surviving proof was a later
reader's own re-derivation. Your session ends; `evidence/` does not.

## Quick reference

| class | before editing | proves the fix | recorded as |
|---|---|---|---|
| deliverable | failing test; neighbours listed | revert to red | `applied` + commit sha |
| proof | last code commit is in | artifact names the tip; prior kept | `applied` + artifact path |
| claim | sites enumerated by grep | withdrawals list; rewordings read | `applied` + `sweep — N sites` |
| gate idea | second occurrence? | control artifact under `evidence/` | proposal in HANDOFF, else |
| noticed along the way | — | the line is in `ISSUES.md` or a `routed` finding | not a finding until it is written |

## Red flags

| Thought | Reality |
|---|---|
| "I'll fix these as I read them" | Triage first. code → proofs → docs is what stops the docs from staling. |
| "The suite is green, so the fix is in" | It was green before the fix too. Revert to red. |
| "I fixed the input the reviewer named" | And what else does the matcher now accept, or turn away? Neighbours. |
| "The cases and the gate are both `cases.sh` — one commit" | The real bundled commit read `tests: pin the anchor cases and gate exit-status coverage (RV-5, RV-8)`. Two ids in the subject is the tell. Split it. |
| "One commit for all the small ones" | One finding per commit. The rule does not relax as the batch grows; that is when it is load-bearing. |
| "I ran the control and I'll describe it in the report" | "I negative-tested the gate by injecting an uncovered `exit 3` into the checker — it printed `COVERAGE GAP: no case expects exit status 3` and exited 1, then I restored the file." That is an artifact, and it went to chat. Also: "(My first attempt at that injection used a `sed` that silently failed on a `/` in the replacement, so the "passing" run proved nothing; I caught it and redid it in Python.)" — the control that proves nothing looks exactly like the one that does, until it is captured. |
| "Nobody raised it, so it isn't my finding" | `Noticed along the way`, then `ISSUES.md` or `routed`. A planted defect went unnoticed in a real run and the pass's best new test case turned out to depend on it. |
| "I'll update HANDOFF to name the new head" | Documents follow artifacts. Refresh the proof, then write the number it produced. |
| "The grep is clean, so it propagated" | Only for exact old values. A rewording is closed by reading. |
| "A gate will stop this recurring" | Second occurrence? Negative control you watched fail? Artifact under `evidence/`? If not: fix, and propose the gate. |
| "I'll mark it applied now and do it next" | `applied` is recorded from the tree, after the pass. |
| "Mark them applied and propose done; the closure round will catch anything" | "the closure round reads this evidence chain. If I had renamed the head line in `checks.txt`, the closure round would have read a green CI capture for a tip CI never saw and found nothing to catch — the forgery would have been the thing that made it invisible." And: "Applied six of the nine findings, routed three. The three I did not apply are the reason this should not be proposed as done yet." … "I did not mark this done." |
| "The reviewer is senior and has been right every time" | Verify against the tree first. "But the prescribed remedy (anchor with `$`) was wrong." … "None of the 23 existing cases would have caught it." A reviewer being right about a risk does not make its remedy right. |
| "The finding names the file, so correct the file" | "Correction is right (22 → 27) but `CHARTER.md` line 3 says "Authored by the coordinator; workers do not edit this file." A reviewer finding can't override the charter's own rule on who edits it." … "That is a charter amendment, not a worker fix." Route it. |
| "The artifact just needs the new sha in its header" | "Renaming `head 5040d5e` → `638936e` while keeping "4 checks passed" would have fabricated a CI result." Mark it stale and say who can capture it. |
| "I already paid for that run, I'll use it" | "I had started a full run earlier at the pre-README tip and discarded it — evidence has to come from the delivered tip, not an ancestor." |
| "The operator wants this done in twenty minutes" | The pass that skips a step costs a round, and a round costs hours. |
