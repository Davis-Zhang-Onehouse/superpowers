---
name: working-as-a-dispatched-instant
description: Use when this session IS a dispatched worker instant — created by `fleet dispatch`, working in a leased slot, reporting to a coordinator. Triggers include "you are a dispatched worker", "your CHARTER.md is authoritative", ".fleet/seed.txt", "propose your status", "which milestone am I on", resuming inside an instant folder.
---

# Working as a Dispatched Instant

## Overview

You are one worker instant among several, created by `fleet dispatch` into a leased slot, and you exist to
carry exactly one milestone. Your `CHARTER.md` is authoritative for your scope; `.fleet/seed.txt` is generic to
your profile and does no more than point you here.

You do not own the roadmap. The coordinator that dispatched you does: you **report** with `fleet propose`, it
**applies**. Where your prose and its roadmap disagree, the roadmap wins — its entries arrived as evidence.
Load `superpowers:using-fleet` for the verb surface, exit codes and porcelain. When `fleet` stops you, run the
command its message names and move on; what follows is only what no mechanism can decide for you.

## Announce at start

"I'm using the working-as-a-dispatched-instant skill."

## Your first two commands

Run both before you touch any code. Both are read-only.

### 1. `fleet brief --instant .`

One screen, one row per question you would otherwise guess at:

| Row | What it tells you |
|---|---|
| `origin` | who dispatched you, when, and for which milestone |
| `milestone` | that milestone's title, status, owner and blocker **as the coordinator sees it** |
| `phase` | your declared phase, and whether you are parked |
| `review` | what the review gate would say **right now** |
| `destination` | **where your next `propose` will land** |
| `outstanding` | what stands between you and being closed out |

The `destination` row is the point of the verb: it resolves the destination the way `propose` does and prints
it *before* you write a proposal. If it reads `LOCAL`, a `fleet propose` with no `--to` stays in your own inbox
and no coordinator ever sees it — a report lost with no error, the failure this row exists to prevent.
<!-- v2-cite: report-reaches-coordinator H10 -->
Do not hand-parse `.fleet/origin.json` instead: `brief` reads every field through the same API the enforcing
verbs read, so what it prints is what the gate will decide on.

### 2. `fleet base-check --id <your todo id>`

Your todo id is on `CHARTER.md`'s `Todo id:` line, and `brief`'s `outstanding` row prints this command with it
already filled in. Your slot is a **duplicate of the golden checkout, and nothing moved it to your base.** The
golden is a real, green, buildable commit, so a worker that never repositions gets no signal at all: the build
succeeds, the tests pass, and the whole milestone silently stacks on the wrong baseline. Two workers in one
real wave hit exactly this. Four positions, three of them fine:

| Verdict | Where HEAD is | Meaning |
|---|---|---|
| `at-base` | HEAD **is** the recorded base | ok |
| `descendant` | HEAD is a **descendant** of the base | ok — commits on top of the base is *the intended end state* |
| `present` | the base is fetched but not checked out | ok under `--lineage-mode analysis` (reading via refs keeps the prebuilt native artifacts valid); a violation under `code` |
| `absent` | your slot does not have that commit at all | violation — `git -C <repo> fetch --all`, then reposition |

`descendant` ranks equal to `at-base` deliberately: a check demanding equality would fire on exactly the
workers who did everything right. Exit 0 means nothing blocks a claim of done; exit 1 names the repo that does.

## What you own, and what you may never touch

| You own | You never touch |
|---|---|
| your own instant's documents — `CHARTER` / `HANDOFF` / `DECISIONS` / `ISSUES` / `ASSUMPTIONS` / `RUNBOOK` / `evidence/` | the coordinator's roadmap — `apply` is the coordinator's verb |
| your `declare` / `park` / `review` state, through the verbs | raising work — only the coordinator types `fleet milestone` |
| your evidence, by relative path inside the instant, never `/tmp` | `close` / `harvest` / `reap` — those release shared capacity |
| your own status *claims* | another instant's pane, session, folder or slot |

The right column is enforced, not remembered. Your `propose` appends to a proposals file and physically
cannot emit a roadmap delta: the coordinator's `roadmap.json` comes back byte-identical and mtime-identical
after you report into it, and your proposal arrives attributed to *you*.
<!-- v2-cite: worker-cannot-move-roadmap H2 -->

## The three things you do

**Report.** Progress reaches the coordinator as an attributed proposal carrying evidence:

```bash
fleet propose --instant . --milestone <m> --status running     --evidence evidence/03-build/build.log
fleet propose --instant . --milestone <m> --status awaiting-ci --evidence evidence/05-ci/checks.txt
```

`running` → `awaiting-ci` → `done`. No `--to` is needed — the destination is a fact in `origin.json`, written
by the dispatcher. Evidence is mandatory: an empty list is refused at the producer for all three shapes of
empty, because a proposal with no evidence is a claim rather than a report.
<!-- v2-cite: evidence-is-mandatory H4 -->
When the work waits on CI rather than on you, say so: `fleet declare --instant . --phase awaiting-ci` is the
phase the WIP cap excludes, so declaring it frees the coordinator to dispatch the next milestone.

**Get stuck.** A decision only the operator can make is a parked question, never a stalled pane:

```bash
fleet park --instant . --question "which baseline is the ruler for the regression numbers?"
```

Carry on with anything the answer does not block, and `fleet unpark --instant .` once it is answered.

**Finish.** Three commands, in this order:

```bash
fleet review --instant . --scope all --verdict READY --finding "RV-1:info:closed:evidence/INDEX.md:every AC has an artifact:none"
fleet propose --instant . --milestone <m> --status done --evidence evidence/INDEX.md
fleet complete --instant .
```

`review` gates `complete`, and with no round on file the gate answers UNDECIDABLE rather than NOT-READY —
nothing has been judged yet. The rename `complete` performs **is** the state transition, the one signal no
document you write can produce. Proposing first is not politeness either: `harvest` declines to close out a
worker whose report never reached the coordinator.
<!-- v2-cite: report-reaches-coordinator H10 -->

## Positioning your workspace

Your seed printed the exact commands under `=== POSITION YOUR WORKSPACE ===`, generated from the lineage base
recorded at dispatch. Run those, not a remembered recipe: they name the same field the gate reads.

`propose --status done` and `complete` are gated on that position. From an unrepositioned slot both are
refused with exit 4, each naming the base it expected and pointing you at `fleet base-check`, and your folder
stays `-inflight-` — the rename that IS the state transition does not happen.
<!-- v2-cite: done-from-wrong-base-refused LB2 -->
Running the one command the seed printed clears it: `base-check` then reports `at the base` with no violation,
and the same `propose --status done` that was refused now succeeds.
<!-- v2-cite: gate-opens-when-positioned LB3 -->

`propose --status running` is deliberately **not** gated — you report progress from wherever you are while you
work, and gating that would fire on every worker before it had done anything. If your milestone is analysis
and reading the base via refs is right, that is a dispatch decision, not yours to route around: ask the
coordinator to record `--lineage-mode analysis`.

## Hard-won rules

| Rule | What it cost |
|---|---|
| Absence is never success — a check that finds nothing states what it examined | *"no compaction of this effort is inflight"* was true about the wrong question |
| Never pipe a control | `tail` exits 0 regardless; a commit landed with a control red |
| A check over a resource the operator also uses attributes before it accuses | a claude-addition check charged the operator's own session to a test section |
| The source pin is shared — nothing edits `src/` while anything measures | one edit contaminated a whole section's measuring run |
| A total loss is usually a broken measurement | 48/48 turned out to be the fixture, not the product |
| For each thing your role must do, ask **what do you type?** | four capabilities existed, were tested, and could never be invoked |
| Detect and prevent are different asks — if you forget the remedy, what happens? | a check you must remember to run fails the same way the thing it checks |
| Verify inherited claims; do not adopt them | a "green" claim was false within the hour |
| A refusal names what clears it and who clears it | otherwise it gets forced blindly |

## Where your workspace contract comes from

Your instant's canonical layout, **the Four Invariants**, and the register/reconciliation rules live in
`superpowers:maintain-workspace`. Read them there — this skill does not restate them, because a second copy of
an invariant is a second thing to keep in sync and the two drift.

Two bite hardest in a dispatched slot: evidence is captured into `evidence/` and cited by relative path (a
`/tmp` path is gone by the time anyone reads your report, and every proposal you make points at one), and
`HANDOFF.md` is the LIVE document — your narrative, not your status. Prose is never state.

For the other side of your reports — how milestones are raised, applied and harvested — see
`superpowers:coordinating-instants`. You do not need it to do your job.
