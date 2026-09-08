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

### 1. `fleet brief --instant "$INSTANT"`

**Your cwd is the leased SLOT, not your instant folder.** `fleet dispatch` starts you in the workspace it
leased — that is the point of a pool, you land in prebuilt code — while your instant folder (`CHARTER.md`,
`HANDOFF.md`, `evidence/`, `.fleet/`) lives elsewhere. So `--instant .` names the slot and every verb refuses
it. Your seed exports the right path as `$INSTANT`; if it is not set, read it from `.fleet/seed.txt`.

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

**Note the flag: `--id`, not `--instant`.** This is the one verb whose subject is your *todo id* rather than
your instant path, because it asks about the SLOT your record points at rather than about the instant folder.
`fleet brief` prints the whole command with your id already filled in, and `CHARTER.md` carries it on its
`Todo id:` line.

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
fleet propose --instant "$INSTANT" --milestone <m> --status running     --evidence evidence/03-build/build.log
fleet propose --instant "$INSTANT" --milestone <m> --status awaiting-ci --evidence evidence/05-ci/checks.txt
```

`running` → `awaiting-ci` → `done`. No `--to` is needed — the destination is a fact in `origin.json`, written
by the dispatcher. Evidence is mandatory: an empty list is refused at the producer for all three shapes of
empty, because a proposal with no evidence is a claim rather than a report.
<!-- v2-cite: evidence-is-mandatory H4 -->
When the work waits on CI rather than on you, say so: `fleet declare --instant "$INSTANT" --phase awaiting-ci` is the
phase the WIP cap excludes, so declaring it frees the coordinator to dispatch the next milestone.

**Arm the watcher BEFORE you declare it, because the claim is gated on one.** `awaiting-ci` says *"stop
counting me against the cap"*, and it was silently also read as *"somebody is watching"* — which nothing
established. Measured: two workers in the identical declared phase rendered byte-identically while one was
self-waking and the other had been stopped for **1h28m** with nothing that would ever restart it. So the
claim now REFUSES unless something is armed that will re-invoke this session with no human in the loop:

```bash
# a Monitor over the run — one event per terminal state, and it must match failures too, or a crashloop
# is indistinguishable from "still running"
Monitor: gh pr checks <pr> --watch   → status line shows `1 monitor`
# or a background shell that exits when the run does      → status line shows `1 shell`
```

Three things worth knowing before you argue with it:

- **Being mid-turn is NOT a watcher.** `declare` runs inside your own turn, so every claimant is mid-turn and
  it distinguishes nothing.
- **"The coordinator will notice" is not a watcher either** — that is the exact state this gate exists to stop.
- If the wait is genuinely not on CI, **declare the phase it actually is**. Every other phase is ungated; it
  simply counts against the cap, which is the honest trade.

**When the watcher is real but this tool cannot see it** — a cron, an external watchdog, a peer session
watching for you — name it instead of routing around the gate:

```bash
fleet declare --instant "$INSTANT" --phase awaiting-ci --watcher "cron */10 * * * * gh-run-poll --pr 4211"
```

**The test is whether you can truthfully name what is watching — not whether the refusal feels wrong for
your situation.** Those are different questions, and only the first one is yours to answer. If nothing is
watching because there is nothing left to watch, the honest move is a different phase, not an attestation.

Your attestation is stored verbatim and `fleet brief` reports it, labelled ATTESTED rather than observed.
⚠️ **`fleet board` does not yet show that distinction** — a coordinator reading the board alone cannot tell
an attested claim from an observed one (`i45` owns that). So the attestation is only as good as your
honesty, and nothing downstream will catch it if it is false.

Do not reach for it to skip arming a monitor you could have armed. The flag exists so a *correct* claim the
predicate cannot see stays cheap and honest — and so nobody is tempted to write `declare.json` by hand,
which records no judgement at all.

**If your attestation stops being true, say so.** It is a statement about the moment you made it; a cron or
a peer's monitor can die afterwards, and nothing re-reads your claim to notice.

**Two ways a watcher looks armed and is not.** Both were measured in one wave, and both cost hours.

- **Never poll by process name.** `until ! pgrep -f "maven"` matches the waiting shell's OWN command
  line, so it never exits. One such shell lived 7 h 55 m and poisoned every later `pgrep -f "[m]aven"`
  wait in that slot; nine of those hit the 600 s timeout for jobs that had finished in 24 to 42 seconds.
  Wait on a PID or on a sentinel line in the log, never on a pattern your own command line carries.
- **Do not rely on word-splitting.** `for r in $RUNS` over a space-joined string iterates ONCE over the
  whole string under the harness shell, so `gh api …/runs/<id> <id> <id>` failed silently on every poll.
  Three monitors built that way emitted zero events in 7.7 hours while the board read them as healthy.

**After you arm a watcher and declare the phase, end your turn.** The notification re-invokes you. A
worker that sleep-polls instead is indistinguishable from a hung one — one ran 21 loops over 3 h 20 m,
delayed its operator's message by 5.8 minutes, and was asked "status?" three times in a session where
nothing was wrong.

`--dry-run` answers the same question the real call does, so you can check before you commit to it. The
refusal names what clears it and who clears it; a claim that skipped the gate says `ungated` and why, so it
never looks like one that passed.

**Get stuck.** A decision only the operator can make is a parked question, never a stalled pane:

```bash
fleet park --instant "$INSTANT" --question "which baseline is the ruler for the regression numbers?"
```

Carry on with anything the answer does not block, and `fleet unpark --instant "$INSTANT"` once it is answered.

**Finish.** Three commands, in this order:

```bash
fleet review --instant "$INSTANT" --scope all --verdict READY \
  --finding "RV-1:Minor:applied:evidence/INDEX.md:every AC has an artifact:none"
```

`--finding` is six colon-separated fields — `id:severity:status:location:finding:action` — and every one is
required, because a finding with no location is a feeling and a finding with no action asks the reader to
invent the remedy. **Two of them are closed domains and a value outside them is refused with exit 2:**

| Field | Allowed |
|---|---|
| `severity` | `Critical` · `Important` · `Minor` · `Nit` — capitalised |
| `status` | `open` · `applied` · `wont-fix` |
| `--verdict` | `READY` · `READY-WITH-FIXES` · `NOT-READY` |
| `--scope` | `format` · `alignment` · `code` · `all` |

Interrogate it first if you are unsure — `fleet review … --dry-run` validates the input, writes nothing, and
exits 0 when the round would be recorded. The gate row it prints reflects the ledger *without* your round, so
a first round reads `UNDECIDABLE` there; that is the current state, not a verdict on what you typed.

```
fleet propose --instant "$INSTANT" --milestone <m> --status done --evidence evidence/INDEX.md
fleet complete --instant "$INSTANT"
```

`review` gates `complete`, and with no round on file the gate answers UNDECIDABLE rather than NOT-READY —
nothing has been judged yet. The rename `complete` performs **is** the state transition, the one signal no
document you write can produce. Proposing first is not politeness either: `harvest` declines to close out a
worker whose report never reached the coordinator.
<!-- v2-cite: report-reaches-coordinator H10 -->

### Finishing is five steps, and the last one is not the rename

`fleet complete` renames the folder, and that rename is the state transition. It is not the end of your
turn. Three workers in one wave ended there, and each needed an operator to come back and ask for the
sweep:

- **Every pointer you leave must survive the rename.** Cite paths RELATIVE to the instant. `complete`
  refuses an absolute path naming your own folder, because it resolves at gate time and not one
  millisecond later.
- **Declare the phase you are actually in.** An instant that has completed is not `awaiting-ci`; a stale
  claim outlives the watcher that justified it, and `complete` refuses while it stands.
- **Kill the waiters you armed.** One worker left seven wait shells alive, one of which had been
  self-matching for 7 h 55 m.
- **Empty the slot of scratch** once its scripts are copied into `evidence/`. A private `.m2` is 22 GB,
  and the next lessee inherits it.

**Durable findings never live in scratch.** A review findings list under `/tmp` is gone when the session
restarts, and one worker's round went into the ledger short for exactly that reason. Anything you would
need after a restart lives under the instant.

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
| End the turn when a watcher is armed | 21 sleep loops over 3 h 20 m; the operator asked "status?" three times in a session where nothing was wrong |

## Where your workspace contract comes from

Your instant's canonical layout, **the Four Invariants**, and the register/reconciliation rules live in
`superpowers:maintain-workspace`. Read them there — this skill does not restate them, because a second copy of
an invariant is a second thing to keep in sync and the two drift.

Two bite hardest in a dispatched slot: evidence is captured into `evidence/` and cited by relative path (a
`/tmp` path is gone by the time anyone reads your report, and every proposal you make points at one), and
`HANDOFF.md` is the LIVE document — your narrative, not your status. Prose is never state.

For the other side of your reports — how milestones are raised, applied and harvested — see
`superpowers:coordinating-instants`. You do not need it to do your job.
