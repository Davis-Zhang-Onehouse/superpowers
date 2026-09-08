# Dispatch wave efficiency — design

**Date:** 2026-09-08
**Status:** design approved in brainstorm; implementation plan to follow
**Source effort:** `operations/tasks/quantonOnSpark4V2` — the seventh dispatch (three siblings) and the
sixth (two siblings), plus their coordinator

## Why

Five dispatched worker instants were audited end to end from their Claude session transcripts, their
instant folders, and the coordinator's `DECISIONS.md` D-369 through D-378:

| instant | slot | wall clock | CI wait | productive |
|---|---|---|---|---|
| `trypmod-remainder-underraise` | ws1 | 8.6 h | 6.5 h | 2.0 h |
| `velox-unaryminus-ansi-checked-kernel` | ws3 | 8.4 h | 5.6 h | 2.1 h |
| `try-subtree-oversuppression-all-checked-kernels` | ws1 | 6.5 h | 3.3 h | 1.7 h |
| `a1-narrow-abs-offload-restore-translator` | ws2 | 5.6 h | 3.4 h | 1.3 h |
| `i38fu-decimal-div-offload-restore-typecarry` | ws3 | 22.9 h | 7.0 h | 4.7 h |

**52 hours of elapsed time produced about 12 hours of work.** Every milestone landed, every grade was
reproduced by the coordinator, and no work was wrong. The loss is entirely in the gaps.

About 1,080 minutes of that gap is addressable by changes to `fleet`, to the skills, and to the
`ansi-gap-closure` profile. It falls into three clusters.

### Cluster 1 — waves that should not have been run (≈560 min)

One heavy CI wave is 3.3 hours, because the x86 `spark-test-spark41` pair is the last to land in four of
the five instants. Every extra wave costs that in full.

| what happened | cost | instant |
|---|---|---|
| review ran after the push, its fixes forced a second wave | 120 min | trypmod |
| same, plus the operator's "review while you wait" instruction made it policy | ~120 min | unaryminus |
| the final whole-branch review was dispatched *after* the label; 3 comment nits redrew the wave | 24 min | try-subtree |
| push 2 held back until push 1 finished grading, on a head the charter never required graded | 125 min | i38fu |
| a deleted deny message was pinned by name in a sibling's suite; push 2 went red | 168 min | i38fu |

The trypmod case is the sharpest, because the late review found a real defect: six
`MathFunctionsValidateSuite` pins that would have reddened the ANSI dim. Reviewing first does not merely
save a wave, it was already saving one.

### Cluster 2 — waits that looked alive and were not (≈380 min)

| what happened | cost |
|---|---|
| an SDD implementer ended its turn on a `Monitor`; the event reached the parent's queue at 17:23:44 and was never delivered (`remove` at 22:03:25). The build had finished in 10 minutes | 268 min |
| `until ! pgrep -f "maven"` matched the waiting shell's own command line; the shell lived 7 h 55 m and poisoned every later `pgrep -f "[m]aven"` wait, nine of which hit the 600 s timeout for jobs that took 24–42 s | 68 min |
| a `Monitor` looping `for r in $RUNS` over a space-joined string: under the harness shell that iterates **once** over the whole string, so `gh api …/runs/34046575956 34046575958 …` failed silently every poll. Three monitors emitted zero events in 7.7 h | 29 min + 3 operator pings |
| 21 foreground sleep loops totalling 192.6 min *while a `Monitor` was armed and the harness had said "keep working, do not poll or sleep"*; the operator's message sat queued 5.8 min and the worker was indistinguishable from a hung one for 147 min | 29 min critical path |

The wall-clock number understates this cluster. Its real cost is that a busy-waiting worker is
**invisible**: three of the eight operator messages in the trypmod session were `status?` pings that
existed only because a watcher was dead.

### Cluster 3 — close-out and tooling churn (≈140 min plus review noise)

`fleet complete` succeeded in three instants while `HANDOFF.md` still named the `-inflight-` path, an
`evidence/INDEX.md` row still read `*pending*`, the declared phase was still `awaiting-ci`, and seven
waiter shells were still alive. Each needed an operator round trip. One slot was left holding 22 GB of
scratch for 76 minutes.

Separately, the review rounds are noisy for reasons that are the tooling's fault, not the worker's:
13 of try-subtree's 27 workspace-review findings, and a comparable share in the others, are the register
headers `fleet.layout` itself seeds. `fleet review` regenerates `REVIEW.md` from `review.json` and
discarded hand-written narrative twice, costing ~15 findings in one instant and 119 lines in another;
both workers independently invented `REVIEW-NARRATIVE.md` to escape it.

## What this design is built from

Five session transcripts read in full (3,843 / 2,057 / 1,547 / 1,306 / 2,955 records), their instant
folders, the coordinator's D-369 to D-378, `PRIORITIES.md`, the `ansi-gap-closure` profile's `seed.txt`
and `charter.md`, and the six skills the workers loaded.

**Every mechanical claim about `fleet` below was measured against the source in this repo, not inherited
from the audits.** That discipline changed the design twice:

- `review.json` records `number`, `scope`, `verdict`, `at` and `findings`. It records **no head sha**. The
  gate this design most wants therefore needs a schema field first; it is not free.
- `layout.py:155-162` documents that register recognition is on the heading text alone, *precisely so*
  that editing `Updated:` cannot unregister a file. Reseeding the header body is therefore safe, which is
  what makes the cheapest fix in this design legal.

Three claims from the audits were re-derived here rather than relayed: the queue records for the
undelivered `Monitor` event, the `for r in $RUNS` word-split (reproduced in this shell), and the
`pgrep` self-match (confirmed from the transcript's own diagnosis at 17:49:03).

## Scope

Three lanes, shipping independently.

| lane | where | ships via |
|---|---|---|
| A — fleet gates | `fleet/src/fleet/` | version bump + release drill |
| B — skill text | `skills/` | rides the same release |
| C — profile | `operations/tasks/quantonOnSpark4V2/profiles/ansi-gap-closure/` | effort-local, no release |

**Enforcement principle:** gate it in `fleet` wherever a gate is possible, and let prose carry only what
no gate can decide. The audits show three separate cases where the worker had the correct guidance in
hand and did the wrong thing anyway — the unaryminus worker diagnosed its own `pgrep` self-match and then
wrote two more of the same loops; the narrow-abs worker was told verbatim by the harness "keep working,
do not poll or sleep" and then ran 21 sleep loops over three hours. Advisory text alone has a measured
failure rate here.

### Explicitly out of scope

- **Session survival.** The systemd user session was torn down at 07:29:37 on 2026-09-08, 29 minutes
  after the last SSH disconnect, taking the fleet tmux server and every worker with it (`Linger=no`).
  That cost i38fu 404 minutes. The operator has ruled this accepted operational cost: the machine needs
  to restart, and the operator revives dead panes on startup using `superpowers:reviving-dead-panes`.
  No prevention, no auto-revive, and no `linger` change is in this design.
- **`brainstorming`'s human-partner gate.** All five workers self-approved through it and recorded a
  decision justifying it. Left exactly as is, by operator ruling.
- **The `required-green` pair set.** The slow x86 pair stays mandatory and stays on the worker. The
  evidence supports this: i38fu's push-2 red appeared on x86 *and* ANSI Mode, and both were JVM-only
  edits. All the saving comes from wave count, not from grading less.

## Lane A — fleet gates

### A1. Bind a review round to the head it reviewed

**The problem.** Nothing connects "a review happened" to "the code that was graded". A worker can push,
review, fix, and push again, and every artefact reads as correct.

**The change.** `Round` gains `heads`, a repo→sha map captured when the round is recorded, resolved from
the record's slot the way `base-check` already resolves repos. Added with a `{}` default at
`schema_version` 1, following the precedent set by `Record.root` in the fleet-root-isolation spec: an
empty `heads` is **NOT MEASURED, never a mismatch**, so every existing round keeps validating and no
already-complete instant becomes retroactively ungradable.

Two consumers:

- `declare --phase awaiting-ci` prints an advisory row: whether a recorded round's `heads` match the
  slot's current HEADs. It does **not** refuse. By the time a worker declares, the push has happened and
  refusing would only strand it.
- `propose --status done` **refuses** when the newest round's `heads` are not the slot's current HEADs,
  naming both. Grading a head no review round has seen is the failure this closes.

**The behaviour change this implies.** Code-review waves must be recorded through `fleet review --scope
code`, not only in the subagent ledger. That is independently correct: narrow-abs's `OI-4` records six
triaged Minors that existed only in `ws2/gluten-internal/.superpowers/sdd/…/progress.md`, a git-ignored
directory that dies with the slot lease.

### A2. `complete` refuses a workspace whose own pointers are stale

**The change, and the subtlety that shapes it.** `complete` *is* the rename, so at gate time every
`-inflight-` path still resolves. Checking "does this path exist" would pass and then break one
millisecond later. The gate must ask instead: **will these pointers survive the rename?**

Before renaming, `complete` scans `HANDOFF.md` and `evidence/INDEX.md` for any path citing the instant's
own folder name. Every such citation is a pointer the rename is about to break, so each is a refusal
naming file and line, with the remedy: cite paths **relative to the instant**, which is already the
`maintain-workspace` rule. It also refuses while the declared phase is still `awaiting-ci`, naming
`fleet declare --phase done` — an instant that is completing is not waiting on CI.

**Why the instant's own name and not a `-inflight-` grep.** A `HANDOFF.md` session-log row legitimately
contains the string while *describing* the rename — trypmod hit exactly this and had to reason about it
by hand. Keying on a path that embeds this instant's folder name catches the pointer and leaves the
narrative alone; keying on the state token alone does not.

This sits beside the existing `_lineage_gate(ctx, child, "complete")` and the `require_scope="all"` review
gate at `cli.py:2342`, in the same before-the-rename position.

### A3. A `routed` finding status

`FINDING_STATUSES` becomes `(open, applied, wont-fix, routed)`. Only `open` is blocking, so `routed` is
non-blocking by construction. `routed` requires `action` to name an owner, the way `wont-fix` already
requires a recorded reason.

**Why.** try-subtree recorded `RV-8` against the coordinator-authored `CHARTER.md`, which is
coordinator-owned and which a worker may never touch. With no `routed` status the finding sat `open`, the
gate refused `READY`, and the worker resolved it by **editing the coordinator's charter** — a real
ownership violation forced by a missing enum value.

### A4. `fleet.layout` seeds a compliant register header

`_seed` at `layout.py:166-176` writes `Updated: {name.curr}` and
`Status: seeded by fleet.layout (spec-version N)`. Both violate the `maintain-workspace` header contract
the workspace reviewer is held to, so every instant generates the same findings on its first review.

Seed `Updated: <ISO date>` and `Status: DURABLE`, plus the canonical sub-section skeleton for the
append-only registers. Safe by `layout.py:155-162`: recognition is on heading text alone.

### A5. Re-observe the watcher, and flag a stale wait

`reconcile.py:356` renders `declared awaiting-ci; not consuming attention` from the stored declaration and
never looks again. `session.watchers()` reads the live pane and is already available.

For a row in `awaiting-ci`, re-observe:

| observation | rendered |
|---|---|
| watcher observable on the live pane | `awaiting-ci; watcher observed` |
| declaration was attested (`--watcher`) | `awaiting-ci; watcher ATTESTED, not observable` |
| pane alive, no watcher on the status line | `awaiting-ci; NO WATCHER OBSERVABLE` |
| declared longer ago than `--stale-after` (default 4 h) | `+ STALE-WAIT (declared <age> ago)` |

This closes the gap `working-as-a-dispatched-instant` already names as owned by `i45`: *"`fleet board`
does not yet show that distinction — a coordinator reading the board alone cannot tell an attested claim
from an observed one."* 4 hours is chosen because the slowest known pair is 3 h 20 m.

The three `status?` pings in the trypmod session are the measured cost of not having this.

## Lane B — skill text

| skill | change | evidence |
|---|---|---|
| `working-as-a-dispatched-instant` | a **close-out contract**: resume pointers resolve, phase declared `done`, your own waiter shells killed, slot scratch deleted once copied into evidence. Mirrors A2 so gate and prose agree | 3 operator round trips; 22 GB left in ws2 for 76 min |
| `working-as-a-dispatched-instant` | **durable findings never live in scratch** | i38fu's round 3 went in short because the restart wiped `scratchpad/wr-findings.txt` |
| `working-as-a-dispatched-instant` | one **tested watcher recipe**, carrying two traps with teeth: never poll by process name, because `pgrep -f` matches the waiting shell's own command line; and never rely on `for x in $VAR` word-splitting under the harness shell | 97 min plus three pings |
| `subagent-driven-development` | replace *"wait in bounded stretches (five to ten minutes)"*: when a watcher is armed, or nothing is independent of the child, **end the turn** — the completion notification re-invokes you. A loop that must exist needs an exit condition, never a fixed `seq` | 286 min of blocked foreground in one instant |
| `subagent-driven-development` | **an implementer never ends its turn on a `Monitor`.** Run the build in the foreground with a long timeout, or have the parent watch the artefact | the single 268-minute item |
| `subagent-driven-development` | inline execution is **first-class** when the plan's tasks are strictly sequential on one leased slot; record the choice | three workers chose it independently; the coordinator ratified it twice, once retroactively |
| `reviewing-workspace` | the prose home is `REVIEW-NARRATIVE.md`; the ledger is `fleet review --finding`. Stop directing authors into a file the verb regenerates | two workers lost narrative, then both invented the same file |
| `reviewing-workspace` | run the advisory round **before** `fleet complete`, as the skill's own text already says | no worker did; two needed an operator prompt |
| `requesting-code-review` | comment-only findings become riders, never a re-push | try-subtree paid 24 CI-minutes for three comment nits; narrow-abs made two comment-only commits |

`CLAUDE.md` requires eval evidence for skill-content changes, and `evals/` is not cloned in this
checkout. The implementation plan treats that as a prerequisite decision rather than assuming it away.

## Lane C — profile seed and charter

| change | evidence |
|---|---|
| drop or condition the "rebuild them after repositioning" paragraph | contradicts the charter's I-52 rule in every instant; made `base-check` warn falsely in two |
| trim the mandated skill list | `test-driven-development`, `executing-plans` and `verification-before-completion` were loaded by **nobody** across five instants, and every one of those practices was still followed because the charter and the plan demanded them |
| add the pre-push checklist: grep the test tree for any message string you delete; a push cancels in-flight runs at the old head and **only the final head is graded**; label after the PR settles and read the guard's `FINAL DECISION` line | 168 min (sibling pin), 125 min (serialised push), 9 min (vacuous label runs) |
| state the real CI latency profile | the try-subtree worker estimated "roughly 90 minutes" for a wait that took 197 |
| a profile RUNBOOK stub: private `.m2` hardlink recipe, `-Dtest=none -DfailIfNoTests=false`, `SPARK_ANSI_SQL_MODE=false` for the plain dim, artifact names per workflow, `grade.py`'s 40-hex contract and `required-green.txt`'s absolute path, the bidirectional shim clean | each re-derived in three to five instants, 2–8 min a time |
| point at the prior instant's `DECISIONS.md` and `GRADE.md`, not only its `SPEC.md` | two of try-subtree's four escalated questions were answered verbatim in trypmod's `DEC-5` and `GRADE.md`, in the same slot |
| charter review runs **before** dispatch, and charters name the outcome rather than the mechanism | three workers got corrections 9–29 min after their seed, two delivered late by idle-gated pollers; i38fu's chartered mechanism was refuted by the worker's own proof and dropped by D-375 |

## Testing

- **Lane A:** table-driven unit cases per changed module, plus an IT section covering the round-to-head
  binding across a push, the `complete` refusal on a stale pointer, and the reconcile re-observation with
  a pane that has gone away. `SCHEMA_VERSION` stays 1; a fixture of existing `review.json` files must keep
  validating with `heads` absent.
- **Lane B:** pressure-test each changed skill against the transcript situation that motivated it. Gated
  on the eval-harness decision above.
- **Lane C:** no automated test. Verified by the next dispatched wave.

## Success criteria

Measured on the next wave of comparable size, against these five as the baseline:

1. One heavy CI wave per milestone, or a recorded decision naming why a second was spent.
2. No operator `status?` ping that a live board could have answered.
3. No `fleet complete` followed by an operator asking for a workspace sweep.
4. First-review findings that are register-header noise fall to near zero.
5. No worker turn ends inside a sleep loop while a watcher is armed.
