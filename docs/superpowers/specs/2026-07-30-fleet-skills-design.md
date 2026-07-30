# Coordinator and dispatch skills, rebuilt on `fleet` — design

- **Date:** 2026-07-30
- **Status:** design approved section by section; not yet implemented
- **Replaces:** `skills/coordinating-instants` (345 lines), `skills/dispatchInstants` (140),
  `skills/dispatching-parallel-agents` (167)
- **Depends on:** `fleet` at `operations/tasks/metaOpt/00000000-07300312-inflight-append-fleetInfraRebuild`,
  29 verbs, 814 hermetic tests, `RESULTS.tsv` 219 PASS / 0 FAIL / 9 SKIP / 5 NOT-RUN

## Why

The three existing skills describe `pdispatch` — 21 shell executables with state in
`~/.claude-dispatch-board` and `~/.claude-ws-pool`. That tooling has been replaced by `fleet`, a
python3-stdlib-only package whose state lives under an explicit `FLEET_HOME` plus per-instant `.fleet/`.
The skills therefore describe a system that no longer exists.

But the deeper reason to rewrite rather than port: **the old skills were mostly rules to remember.**
`coordinating-instants` is 345 lines, and the bulk of it is prose telling the coordinator not to
over-dispatch, not to write a worker's status, to check the board before assigning. Every one of those is
now a refusal in `fleet`. A skill that restates a mechanical refusal adds a second place for the rule to
live, and the two drift.

The governing rule for all four skills in this design: **if `fleet` refuses it, the skill states the command
and moves on.** Prose is reserved for judgement — things no mechanism can decide.

## §0 — How it works, end to end

```
  OPERATOR            COORDINATOR instant              fleet state                 WORKER instant
   │                        │                              │                            │
   │  "here's the roadmap"  │                              │                            │
   ├───────────────────────►│                              │                            │
   │   (conversation)       │  fleet milestone ×N           │                            │
   │                        ├─────────────────────────────►│ roadmap.json                │
   │                        │                              │  m1 done                    │
   │                        │  fleet roadmap               │  m2 ready  ◄── DERIVED      │
   │                        │◄─────────────────────────────┤  m3 blocked (dep m2)        │
   │                        │                              │                            │
   │                        │  fleet dispatch --from . --milestone m2 --lineage-base …   │
   │                        ├─────────────────────────────►│ lease + record + origin.json│
   │                        │                              ├───────────────────────────►│ born
   │                        │                              │  m2.owner = <worker>        │
   │                        │                              │                            │ works
   │                        │                              │  fleet propose (no --to)   │
   │                        │                              │◄───────────────────────────┤
   │                        │  fleet roadmap → inbox: 1     │ proposals.json @coordinator│
   │                        │◄─────────────────────────────┤                            │
   │                        │  fleet apply --milestone m2   │                            │
   │                        ├─────────────────────────────►│ m2 → done                   │
   │                        │                              │ m3 → ready  ◄── RECOMPUTED  │
   │                        │  fleet harvest --id …         │                            │
   │                        ├─────────────────────────────►│ slot freed, row off board  ─┤ ends
```

**Act 0 — the roadmap conversation.** The operator and the coordinator agree what the items are and what
depends on what. The coordinator then types one command per item: `fleet milestone --instant . --id m2
--title "…" --dep m1`. A `--dep` naming something that does not exist is refused there and then, because a
typo'd dep is not an error later — it is a milestone that reads as permanently in progress. Nothing is
"ready" because someone said so: readiness is derived from whether deps reached `done`, and every not-ready
row names its own blocker.

**Act 1 — dispatch.** The coordinator looks (`board`, `leases`, `reap --all`), picks from the `ready` rows,
and dispatches. One command claims a lease, creates the instant from a profile, renders `CHARTER.md` and
`.fleet/seed.txt`, writes `origin.json`, stores a record, starts a `dt-<name>` tmux session running `claude`,
and sets the milestone's owner. It refuses if the milestone is not ready, is already claimed, the WIP cap is
full, no slot is free, or a dispatch this minute already produced that folder.

**Act 2 — the worker works.** It wakes in its slot, reads its seed, positions its workspace onto the
recorded lineage base, and reports: `fleet propose --milestone m2 --status running --evidence <path>`.
Evidence is mandatory. No `--to` is needed — the destination is a fact in `origin.json`, written by the
dispatcher. Blocked on a decision only the operator can make: `fleet park --question "…"`.

**Act 3 — the worker finishes.** `fleet review --scope all --verdict READY` → `fleet propose --status done
--evidence …` → `fleet complete`. The **rename is the state transition** — the one signal a worker cannot
fake by writing a document saying it is done.

**Act 4 — reconciliation.** `fleet roadmap` shows the pending proposal, attributed to the worker that made
it. `fleet apply --instant . --milestone m2` is the only thing in the package that moves a status: it moves
it, carries the evidence onto the milestone, and consumes the proposal so replaying the inbox cannot apply it
twice. Readiness recomputes; `m3` becomes ready. `fleet harvest --id <todo>` then closes out: applies any
remaining proposals, kills the session, stamps the record, releases the slot, and **the row leaves the
board** — which is what makes an orphan unreachable rather than merely tidy.

**Act 5 — when it goes wrong.**

| What happened | What the coordinator does |
|---|---|
| worker process died | `fleet reap` reclaims the slot; `board`/`status` name the milestone, so the work to re-raise is identified |
| worker stuck on an operator decision | it is already `park`ed with a question; `fleet unpark` when answered |
| work unsalvageable | `fleet abort --instant <w> --reason <why>` — a reason is mandatory, and it releases the milestone's claim |
| work outlives the effort | a documented issue **plus** `fleet milestone`. No reassignment, ever |

### The one idea underneath

**Every fact lives in exactly one place, with exactly one writer, and everything else is derived.** Readiness
is computed from deps, so it cannot go stale. A status reaches the coordinator as an attributed proposal with
evidence, and only `apply` writes it. The join between a worker and its milestone is recorded at dispatch.
Capacity is a lease where `mkdir` **is** the lock.

## §1 — The skill set

| Skill | Disposition | Role |
|---|---|---|
| `coordinating-instants` | **rewritten** | the coordinator's loop (§3) |
| `working-as-a-dispatched-instant` | **new** | the worker's contract (§4); loaded by the seed |
| `using-fleet` | **new** | the shared verb reference both roles read |
| `dispatching-subagents` | **renamed** from `dispatching-parallel-agents`, rewritten | in-session subagents — the lighter-weight thing, unrelated to instants |
| `dispatchInstants` | **deleted**, including its `base-check.sh` | its mechanism is now `fleet dispatch`; its base-check is now `fleet base-check`, wired into a gate rather than left as a script to remember |

Plus three profile templates, one per `fleet` kind, each bearing a `profile.json` with a **declared** `kind`:
`worker`, `compaction`, `coordinator`. The kind is declared and never read out of charter prose — three of
five profiles once silently became `worker` because it was inferred from prose.

**Decisions taken during design:**

- **`fleet` only; accept the gaps.** No fallback to `pdispatch`, no dual-path prose. A skill that documents
  two mechanisms teaches neither.
- **`fleet`'s state IS the registry.** The skills do not describe a parallel board; there is no
  coordinator-maintained todo list to keep in sync.
- **The worker's contract is its own skill, loaded by the seed** — not a section of the coordinator's skill.
  A worker should not have to read the coordinator's role to learn its own.
- **Three generic templates, one per kind** — not per effort. Effort-specific content belongs in the charter.
- **Rename `dispatching-parallel-agents` → `dispatching-subagents`** so the pair `dispatching-subagents` /
  `coordinating-instants` makes the boundary obvious: subagents live inside one session; instants are
  separate `claude` processes in leased workspaces.

## §2 — `fleet`'s state is the registry

The project-level roadmap is **the coordinator instant's `.fleet/roadmap.json`**. Workers report into it and
the coordinator is its single writer. Two files, one writer each, and that split is the whole model:

| File | Writer | Contents |
|---|---|---|
| `<coordinator>/.fleet/roadmap.json` | the coordinator, via `milestone` / `claim` / `apply` | the milestone registry |
| `<coordinator>/.fleet/proposals.json` | any worker, via `propose` | the coordinator's inbox |

A worker's verb **physically cannot** produce a roadmap delta: `propose` returns a `Proposal` and appends it
to its own file. The reason this is structural rather than conventional is on record — a dispatch profile once
instructed *every* worker to update the canonical registry, and survived an entire effort that way, because
nothing in the mechanism could tell a worker's write from the coordinator's.

Three writers exist on the coordinator's side and the split between them is the invariant, not "one function
writes": `add` creates a milestone, `claim` records which instant is executing one, and **`apply` is the only
function in the package that changes a milestone's status.** `claim` deliberately does not touch status —
marking a dispatched milestone `running` would have made a second status writer out of a bookkeeping verb,
after which "who moved this to done" has two answers.

**Readiness is derived, never stored.** A stored `ready` flag is a second copy of a fact the deps already
carry, and the two drift the moment a dep slips. `ready()` recomputes from `LANDED`, and `report()` names the
blocker for everything that is not ready.

**Evidence is mandatory on every proposal**, refused at the producer for all three shapes of empty (`[]`,
`[""]`, whitespace). A proposal without evidence is a claim.

## §3 — The coordinator's loop

| Phase | What the coordinator types | Why it is not optional |
|---|---|---|
| **Observe** | `fleet board`, `fleet leases`, `fleet roadmap --instant . --porcelain` | three different questions — who holds a slot, what slots exist, what work exists. Reading one and inferring the others is how a worker gets dispatched onto an unlanded base |
| **Reconcile** | `fleet reconcile`, `fleet reap --all` | `reap` recovers a slot whose writer died; skipping it leaks capacity silently |
| **Decide** | *nothing* — read the `ready` rows | readiness is derived. A milestone labelled `ready` whose dep has not landed is not ready, and the row says so |
| **Raise** | `fleet milestone --instant . --id <x> --title <…> [--dep …]` | the only way work becomes dispatchable. An unresolvable `--dep` is refused where the name is first written |
| **Dispatch** | `fleet dispatch --profile <p> --title <…> --base <b> --optype <append\|compact> --from . --milestone <m> [--lineage-base "repo=sha,…"]` | the `WipCap` guard refuses an over-dispatch. The skill states the cap it wants; it does not police it |
| **Receive** | `fleet roadmap` shows pending proposals → `fleet apply --instant . --milestone <m>` | `apply` is the only status writer |
| **Escalate** | `fleet park --instant <w> --question <…>` / `fleet unpark` | a blocked worker becomes a named question, not a stalled pane |
| **Abandon** | `fleet abort --instant <w> --reason <why>` | a reason is mandatory; it also releases the milestone's claim |
| **Close out** | `fleet review …` → `fleet complete` → `fleet harvest --id <…>` | `review` gates `complete`; `harvest` is the transaction that frees the slot and clears the board row |

**Two things the skill must say explicitly, because they are judgement and not mechanism:**

1. **Act on `attention`, report `info`.** Every checker row carries a severity. A finished milestone and a
   legitimately empty population are `info`; treating them as alarms is how a green board reads as red and
   gets ignored.
2. **Read porcelain, never prose.** Every observation verb takes `--porcelain` and emits tab-separated fields
   whose schema is declared data. The coordinator parses columns; it never greps a sentence.

**The endgame.** An item that outlives the effort is carried by **two acts, both required**: a documented
issue in the workspace (where a resuming session already reads), and `fleet milestone` on the roadmap (which
makes it dispatchable). Neither alone suffices — the issue holds the *why*, the milestone holds the
*reachability*. A milestone names no owner it has to invent, so the failure that motivated the old
reassignment machinery (eight items reassigned by name to an instant that existed nowhere on the box) is
**unrepresentable** rather than detected.

**What the coordinator never does:** write another instant's `roadmap.json`; touch a `dt-` session belonging
to another effort; merge, publish or delete outward state; set a status without an applied proposal.

## §4 — The worker's contract (`working-as-a-dispatched-instant`)

### The worker's first two commands

**1. `fleet brief --instant .`** — *proposed, not yet built; see Prerequisites.* Read-only, one screen:

| It answers | From |
|---|---|
| who dispatched me, and for which milestone | `origin.json` |
| that milestone's title, status and blocker **as the coordinator sees it** | the coordinator's roadmap |
| my phase, my park state | `declare.json` |
| what the review gate would say **right now** | `review.json` |
| **where my next `propose` will land** | the same resolution `propose` uses |
| what is outstanding before I can be closed out | pending proposal at the coordinator? review round? folder renamed? |

The fifth row is the one that earns the verb: it makes the silent-loss failure impossible to walk into,
because the worker can *see* that its report would stay local **before** it sends one.

**2. `fleet base-check --id <my todo id>`** — am I positioned on the base my milestone builds on? A slot is a
duplicate of the golden checkout, and **nothing moves it forward**; a worker that never repositions builds on
the golden, which is a real, green, buildable commit. *"The failure mode is invisible: the build succeeds and
tests pass, so the whole milestone silently stacks on the pre-fix baseline. Two workers in the previous wave
hit exactly this."*

Three legitimate positions, not one — and this distinction is the whole design:

| | Position | Verdict |
|---|---|---|
| a | HEAD **is** the base | ok |
| b | HEAD is a **descendant** of the base | ok — commits on top is *the intended end state* |
| c | base **fetched but not checked out** | ok for `--lineage-mode analysis` (reading via refs keeps the native artifacts valid); a violation in `code` mode |
| d | the slot **does not have that commit** | violation |

A check demanding equality would refuse exactly the workers who did everything right.

### What the worker owns, and what it can never touch

| Owns | Never |
|---|---|
| its own instant: `CHARTER` / `HANDOFF` / `DECISIONS` / `ISSUES` / `ASSUMPTIONS` / `RUNBOOK` / `evidence` (maintain-workspace's Four Invariants) | the coordinator's roadmap — `apply` is the coordinator's verb and `propose` physically cannot write a milestone |
| its `declare` / `park` / `review` state, through verbs | creating a milestone — only the coordinator types `fleet milestone` |
| its own evidence, by relative path, never `/tmp` | `close` / `harvest` / `reap` — those release shared capacity |
| its own status *claims* | another instant's pane, session or folder |

Every one of those is a refusal in the tool, not a rule to remember.

### The three things it does

**Report** — `fleet propose --milestone <m> --status <s> --evidence <path>`. `running` → `awaiting-ci` →
`done`. Evidence mandatory; no `--to` needed.

**Get stuck** — `fleet park --question "…"`.

**Finish** — `fleet review --scope all --verdict READY --finding …` → `fleet propose --status done --evidence
…` → `fleet complete`. Proposing is not politeness: `harvest` refuses to close a worker whose report never
reached the coordinator, and `propose --status done` / `complete` refuse from the wrong lineage base.

## §5 — Gaps, failure, and honesty

### Gaps the skills name once, with the workaround, and do not repeat as warnings

- **`fleet brief` does not exist yet** (§4). Until it does, the worker's orientation step is reading
  `.fleet/origin.json` — the one hand-parse in the whole design, and named as such.
- **The coordinator can type the wrong lineage SHA.** Nothing checks that `repo=<sha>` is the *right* base
  for a milestone — only that the slot ends up there and that every document agrees. The predecessor's tip is
  recorded in its `HANDOFF.md` "PR / branch-stack table" and **retyped** into the next dispatch. The design
  that closes this is worked out and deferred (`SI-33`).
- **No `clone` verb**, and the declared golden is resolved only by `set-golden`'s own echo-back.
- **Five IT sections are partially covered** (`§F §G §I §J §O`); `§P` — the real dispatch against a real
  `claude` — has never run. The coordinator skill states which properties are measured and which are argued.
- **`fleet` infers no milestones from a goal.** Act 0 is a conversation, deliberately.

### The honesty rules that go into both skills, each earned

| Rule | What it cost |
|---|---|
| Absence is never success — a check that finds nothing says what it examined | *"no compaction of this effort is inflight"* was true about the wrong question |
| Never pipe a control | `tail` exits 0 regardless; a commit landed with a control red |
| A check over a resource the operator also uses must **attribute before it accuses** | a claude-addition check charged the operator's own session to a test section |
| The source pin is a shared resource — nothing edits `src/` while anything measures | one edit contaminated a whole section's measuring run |
| A total loss is usually a broken measurement | 48/48 turned out to be the fixture, not the product |
| For each thing your role must do, **what do you type?** | four capabilities existed, were tested, and could not be invoked |
| **Detect and prevent are different asks.** If the actor forgets the remedy, what happens? | a check you must remember to run fails the same way the thing it checks |
| Verify inherited claims; do not adopt them | a "green" claim was false within the hour |
| A refusal must name what clears it and who clears it | otherwise it gets forced blindly |

### Reporting discipline

The worker's `HANDOFF.md` and the coordinator's roadmap must never disagree, and **the roadmap is
authoritative** because its entries arrived as evidence. Prose is never state.

## §6 — How the skills themselves get verified

A skill is prose for a model and there is no test suite for prose. But most of what a skill *asserts* is
factual and mechanically checkable. Three tests per skill, in `skills/<name>/tests/`, where
`bin/superpowers-selftest` already discovers `skills/*/tests/*.sh` and prints one verdict.

**V1 — every command named exists.** Extract every `fleet <verb>` token from `SKILL.md` and assert it is a
registered verb. This catches, at authoring time, the failure family where a capability exists, is tested, and
cannot be invoked — four instances in the effort that produced this design.

Two refinements, both found by running V1 against **this spec** before writing it into a skill:

- **Extract from code spans and fenced blocks only, never from prose.** A naive `\bfleet [a-z-]+` match over
  the whole document produced two false positives here — `fleet refuses it` and `fleet`'s `state` — because
  the tool's name appears in ordinary sentences. A lint that fires on its own author's prose gets disabled.
- **A forward reference must be markable.** V1 correctly flagged `fleet brief`, which this design proposes and
  has not built. That is an honest instruction about a future verb, not a defect, so the lint needs an
  explicit marker (`<!-- v1-proposed: brief -->`) rather than an implicit tolerance. Marked is the point: an
  unmarked unknown verb is a bug, and a marked one is a promise somebody can grep for.

**V2 — every claimed refusal cites a case that passed.** Each "fleet refuses X" claim carries an IT case id,
and the test asserts that id is `PASS` in `RESULTS.tsv`:

| Claim in the skill | Cited case |
|---|---|
| a worker physically cannot move the roadmap | `H2` |
| prose in `HANDOFF.md` is not state | `F3` (+ `F2`, its positive half) |
| an unclaimed session is reported, never reaped | `J7` |
| `close` refuses a pane holding unsubmitted input | `J8` |
| a claim of done from the wrong base is refused | `LB2` (+ `LB3`, which proves the gate opens) |
| the carry-across runs on `fleet` alone | `H9` |
| a compaction present only as a folder still freezes dispatch | `F11` |
| the close-out transaction commits as a whole | `J2` |

An **uncited** refusal claim fails the lint — absence is never success, applied to the skill's own promises.
`RESULTS.tsv` lives in a different repository, so the test takes its path by environment variable and **SKIPs
with a stated reason** when it is unreachable, rather than passing quietly.

**V3 — the documented sequence runs.** `skills/coordinating-instants/tests/loop.sh` performs §3's loop
against a scratch store on a private tmux socket. If the sequence the skill documents does not execute, the
skill is wrong. This is `fleet verify`'s own principle — *execute every documented recipe in a sandbox* —
turned on the skills.

**What none of this verifies.** Whether a model *reading* the prose does the right thing. V1–V3 prove the
commands exist, the refusals are real and the sequence runs; they say nothing about whether the instructions
are followable. That is measurable only by dispatching a real worker against a real `claude`, which is `§P` /
AC-11 — one case, never run. **Until `§P` runs, "the skills work" is an argument and not a measurement**, and
the spec says so rather than implying otherwise.

## Prerequisites

Built during this design, because each replaced a prose instruction with a command:

| Change | Why it was needed for the skills |
|---|---|
| `fleet milestone` | the coordinator's "raise work" step had no verb, so §3's loop was unreachable |
| `dispatch --from --milestone`, `origin.json`, `Roadmap.claim`, the `harvest` report guard, a `milestone` column on `board` | the join between a worker and its milestone did not exist, and a worker's report could vanish with no error |
| `guards.blocking_compactions` over records ∪ disk | a compaction created as a folder — which is how `maintain-workspace` creates one — froze nothing |
| `harvest` stamps before releasing | a crash mid-close-out left a free slot with an in-flight record, invisible and unrecoverable |
| `dispatch --lineage-base/--lineage-mode`, `{{CHECKOUT}}`, `fleet base-check`, the gate on `propose --status done` / `complete` | §4's positioning step was a rule the worker had to remember |

**Still to build before implementation:** `fleet brief` (§4). Deferred with the design recorded: the
tip-chain that would let `dispatch` derive a lineage base from the predecessor's reported tips (`SI-33`).

## Explicitly left alone

`bin/`'s 21 `pdispatch` executables — `base-check`, `dispatch-board`, `wspool`, `ref-guard` and the rest —
are **not deleted by this design.** The skills stop referencing them; the files stay. Two reasons: they are
outward state relative to this work, and another effort may still invoke them directly. Removing them is a
separate decision that should be taken when nothing references them, not folded in here as a tidy-up.

## Suggested phasing for the implementation plan

Five phases, in dependency order, each independently reviewable:

1. `using-fleet` — the shared verb reference both roles read.
2. The three `profile.json`-bearing templates (worker / compaction / coordinator).
3. `coordinating-instants` (§3) + its V1–V3 tests.
4. `working-as-a-dispatched-instant` (§4) + its V1–V3 tests.
5. `dispatching-subagents` (renamed, rewritten) and the deletion of `dispatchInstants`.

## Out of scope

- Any `pdispatch` compatibility path.
- Rewriting `maintain-workspace`, `brainstorming`, or any other existing skill. `working-as-a-dispatched-instant`
  *references* `maintain-workspace`'s Four Invariants; it does not restate them.
- Asking a git remote anything. `fleet` has exactly three subprocess seams and states the count deliberately;
  verifying that a reported tip is actually the PR head would be a fourth, and is a separate decision.
- Multi-operator or multi-box coordination.
