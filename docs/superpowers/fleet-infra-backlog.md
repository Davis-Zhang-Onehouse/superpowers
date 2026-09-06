# Fleet infra backlog — `SI-*`

Structural issues in `fleet` that a skill or a routine has to work *around* rather than *with*. An entry
earns its place by having cost something real in a live effort, and by naming a decision a fix has to make.

`SI-*` ids are also cited inline in `fleet/src/**` and in `skills/**`, where the code or the prose has to
explain itself. This file is the standing register; the citation is the cross-reference.

**Deriving the next id: `grep -rhoE '\bSI-[0-9]+' . | sort -t- -k2 -n | tail -1`, BEFORE you append your
own section.** Run after, and your own text is the maximum you measure against — that mistake produced a
duplicate `FI-413` in a live register and cost a renumbering (`FI-421`).

**Verify before you inherit.** Two entries drafted for this register on 2026-09-05 were deleted before it
was committed, because measuring them showed both were already fixed:

- *"an unknown flag makes a verb print usage and exit 0"* (`FI-380`/`FI-401`) — measured at `0.3.18`,
  `fleet roadmap --bogus-flag` and `fleet propose --note-file` **both exit 2** with a refusal naming the
  declared flags. Fixed.
- *"the proposal `note` field has no consumer surface"* (`FI-409`) — `roadmap.py:520` puts the note
  **first** in the `pending-proposal` row's detail, cited `I-2`. Fixed. What remains is a reading habit,
  which is a skill's problem and not this file's.

A register that carries a closed issue as open is worse than one that omits it: it teaches a false fact to
everyone who greps it.

---

## SI-42 — a milestone has no `kind`, so an open question cannot be a first-class roadmap row

**Status:** OPEN. **Blocks:** `running-a-stacked-effort` (the unknowns registry), `maintaining-a-roadmap`.

**Measured 2026-09-05** at `fleet 0.3.18`. A milestone's fields are exactly
`id, title, status, deps, evidence, owner, retired_reason` (`fleet/src/fleet/roadmap.py`), and
`fleet milestone --help` declares no `--kind`. Every row is implicitly a unit of *delivery*.

**Why it matters.** A coordinator tracks three different things and the roadmap can only represent one:

| what it is | example from `quantonOnSpark4V2` | where it lives today |
|---|---|---|
| a delivery | close ANSI gap A6 | a roadmap row ✅ |
| a known unknown | does velox have a decimal remainder kernel? | prose in `ISSUES.md` + a roadmap row whose title is a paragraph |
| a probe | measure the `ansiFallback` default-flip blast radius | an "explorative" row indistinguishable from a delivery |

That effort kept 9 explorative rows under `D-336` specifically because they *"carry accounting obligations
the spec cannot supply"* — the coordinator knew they were a different kind and had no field to say so. The
cost shows up in readiness: a probe that is `done` means *we now know*, while a delivery that is `done`
means *the code is on the chain*, and `fleet roadmap` cannot tell a dependent row which of those it got.

**What a fix must decide.**
1. Is `kind` a closed enum (`delivery|question|probe`) or free text? A closed enum is checkable and is the
   reason to have the field at all; free text becomes a second title.
2. Does `kind` change **readiness semantics**, or is it purely descriptive? Recommended: descriptive first.
   Making a `question` row satisfy a dep differently is a second mechanism, and the field is worth having
   before that argument is settled.
3. Migration: existing roadmaps have no `kind`. Absent must read as `delivery`, not as invalid —
   `schema_version` refuses a roadmap it does not know, so this needs a bump with a default, not a break.

**Closed when:** `fleet milestone --kind` exists, `fleet roadmap --porcelain` emits it as a column, a
roadmap written before the field loads and reads `delivery`, and the integration suite covers the default.

---

## SI-43 — there is no chain manifest, so `--lineage-base` correctness is checked by nobody

**Status:** OPEN. **Subsumes `SI-33`** (a tip-chain letting `dispatch` derive a lineage base from the
predecessor's reported tips — *"worked out and deferred"*, `2026-07-30-fleet-skills-design.md:364`).
**Blocks:** `dispatching-a-wave`, `integrating-a-pr-stack`, and the chain-manifest half of the umbrella.

**The gap, in the skill's own words** (`skills/coordinating-instants/SKILL.md`, "Not checked at all"):
`fleet` verifies the slot *arrives* at the SHA you typed and that every document agrees. It never verifies
the SHA was the **right** base for that milestone. The coordinator reads the predecessor's tip out of a
prose table in `HANDOFF.md` and retypes it.

**What that has cost.** `FI-390`: a `done` milestone's code was **not reachable from every base** — 23
added paths present on one line and absent from two live workers' bases, found by an auditor asking a
question the coordinator had not asked itself. The effort's `RUNBOOK.md` §2 carries a hand-written
`git ls-remote` re-verification step for exactly this reason, and `PRIORITIES.md` rule 1 restates the
current base in prose at the top of the file because nothing else holds it.

**What a fix must decide.**
1. **Where the manifest lives.** In the coordinator's `.fleet/` beside `roadmap.json` (fleet owns it, gets
   the same single-writer and locking guarantees) or as an effort-root file (readable by workers, editable
   by hand). The single-writer property is the reason to prefer `.fleet/`.
2. **What a position records.** At minimum: ordinal, repo, branch, PR number, tip sha, parent position,
   and — the part a single-repo design would miss — **the pinned sha of each paired repo at that
   position**. `x4`'s AC-3 is precisely this: *"a chain position that builds against un-chained velox is
   the defect this milestone exists to prevent."*
3. **How much is derived vs stored.** Ancestry is derivable (`git merge-base --is-ancestor` pairwise) and
   should be checked, not stored. Grade state is *not* derivable after the fact once runs age out, so it
   is stored with the sha it graded.
4. **What `dispatch` does with it.** Deriving `--lineage-base` from the manifest tip removes the retype
   class entirely; refusing a dispatch whose typed base disagrees with the manifest is the weaker,
   cheaper version. Either is a large improvement on nothing.

**Closed when:** a dispatch can name a chain position instead of a SHA, a checker asserts pairwise ancestry
and pin-containment across repos, and `FI-390`'s question (*is every `done` milestone's code reachable from
this base?*) is answerable by one command.

---

## SI-44 — a milestone cannot be amended, so real sequencing constraints live in prose

**Status:** OPEN. **Blocks:** `maintaining-a-roadmap`. **Field id:** `FI-283`.

**Measured 2026-09-05.** `Roadmap.add` refuses an id already present — *"refusing to shadow it"*
(`roadmap.py:227`) — and the only other door is `retire`, which drops the row and requires a reason. There
is no `--amend`. So **a dependency discovered after a row is raised cannot be added to it.**

The refusal is defensible on its own terms: silently reshaping a milestone loses its history. But the
consequence is that the roadmap cannot represent a constraint learned later, which is when most real
constraints are learned.

**What that has cost.** From `PRIORITIES.md`, verbatim:

> ⚠️ **Cast-family ordering rule (D-360, from w27 I-1): `v9x` MUST land before `v9f`.** […] a `v9f`
> dispatched first ships map entries that never fire on those targets and can grade green. **FI-283 blocks
> adding the dep edge to the existing rows, so this file and the dispatch order carry it.**

A constraint whose violation produces a **green** result is exactly the kind that must be mechanical. It is
currently a paragraph, enforced by the coordinator remembering to read it — and the same file records a
second instance of the pattern (rule 1's lineage base, "enforced at dispatch time by the coordinator's
`--lineage-base`, not by the roadmap").

**What a fix must decide.**
1. **Amend, or supersede-with-lineage?** `--amend --dep` is the small fix. The alternative is making
   `retire` + raise carry an explicit `supersedes` edge so the history is preserved *and* the new row is a
   traceable continuation — which is what the effort does by hand today (`x1` → `x2`, `retired_reason`
   naming what the new row must keep).
2. **What may be amended.** Adding a `--dep` is monotonic and safe. Removing one, or editing a title, is
   how a title silently widens (`FI-420`: a `done` row asserting a scope its own worker declared
   undelivered). Recommended: allow adding deps and evidence; refuse title edits on a terminal row.
3. **Whether an amend is auditable.** If deps can change, `fleet roadmap` should be able to say when and
   why — otherwise a dependency that appears late is indistinguishable from one that was always there.

**Closed when:** a dependency learned after a row was raised can be recorded on that row (or on an
explicitly-superseding row) without losing history, and `PRIORITIES.md` no longer has to carry a "MUST land
before" rule in prose.

---

## SI-45 — an operator-authored profile cannot be linted by any command

**Status:** OPEN. **Blocks:** `dispatching-a-wave` (profile authoring is part of the routine).

**Measured 2026-09-05** at `fleet 0.3.18`. `fleet/src/fleet/profiles.py:190` defines `lint(profile)` with
six rules — `authoring-placeholder`, `static-sha`, `baseline-disagreement`, `awaiting-ci-clause`,
`required-clause`, `invocation-target-flag` — plus a `population` row so a narrowed scope cannot read as a
pass. It is a careful, well-designed check.

**Nothing on the CLI calls it.** `cli.py:74` imports `Profile` and not `lint`; the only importers in the
whole tree are `fleet/tests/test_contracts.py:40` and `fleet/tests/test_profiles.py:11`. The verb named
`lint` is `fleet lint --instant`, which checks *an instant's* layout matrix, watched-source registry and
near-miss rule — a different subject entirely. `fleet verify` executes an instant's documented recipes;
`fleet selftest` runs fleet's own suites. Neither reads a profile.

**Why it matters.** Authoring a profile is part of the coordinator's routine, not an internal fleet
concern: `quantonOnSpark4V2` carries three (`dispatch/profile-v2stack`, `dispatch/profile-fleetinfra`,
`profiles/ansi-gap-closure`). Its `PRIORITIES.md` describes the last of these as *"lint-clean, 14 required
clauses"* — and that claim, which is about a profile every subsequent worker is dispatched with, **is not
re-derivable by any command a coordinator can type.** The `requires_clauses` list really does hold 14
entries; there is simply no way to check them from outside the test suite.

This is the shape `SI-33`'s own design doc warns about under a different name: *"for each thing your role
must do, ask: what do I type?"* — four capabilities existed, were tested, and could not be invoked.

**What a fix must decide.**
1. A new verb (`fleet profile-lint --profile <dir>`) or a flag on an existing one? A new verb is clearer;
   the verb population is already 40-odd and `lint` is taken by a different subject.
2. Does `dispatch` lint the profile it is about to render, and refuse on a violation? That closes the gap
   without anyone remembering to run anything — the *detect vs prevent* distinction this codebase applies
   elsewhere. The cost is that a violation then blocks a dispatch, so the severity split has to be right.

**Closed when:** a coordinator can lint a profile they authored with one command, and the "lint-clean"
claim in an effort's own priorities file is a re-derivable measurement rather than an assertion.

---

## SI-46 — the placeholder detector cannot see the placeholder convention the profiles actually use

**Status:** OPEN. **Depends on `SI-45`** — while the lint is unreachable, this gap is unobservable.

**Measured 2026-09-05.** `profiles.py:81`:

```python
_AUTHORING = re.compile(r"the-[a-z][a-z-]*-in-your-[A-Z]{3,}|FILL-?ME|TODO-?FILL|<[A-Z_]{3,}>")
```

Run against the real `profiles/ansi-gap-closure/charter.md`: **0 hits.** That charter contains **2**
coordinator-authoring blocks, in the form the effort standardised on:

```
<!-- COORDINATOR: replace this comment with the requirement. One block per behavior in scope, each a
     GIVEN line (ANSI on; the table, the column types, the config), a WHEN line ... -->
```

So the profile lints clean on the `authoring-placeholder` rule while shipping a charter whose §1 Scope and
§3 acceptance criteria are placeholders.

**Why it matters — this is the structural half of `FI-387`.** `dispatch` writes the rendered charter
(`cli.py:1053`) and the launcher shim then waits up to 180s for a seed
(`scripts/fleet-dispatch-launcher.sh:128`, falling through at :133 to *"an interactive session rather than
a blank prompt"*). The coordinator fills the real scope into the child's `CHARTER.md` inside that window.
Measured in the field: a worker read a charter **growing under it**, 28,609 → 37,401 bytes, and filed a
decision on the premise that its scope and acceptance criteria were empty. They were mid-write.

The profile carries a §0 self-check telling the worker to `fleet park` if §1 has no `GIVEN` outside a
comment — a good mitigation, and a **worker-side** one. Nothing on the coordinator's side can see it.

**What a fix must decide — and the honest framing is that this may not be fleet's bug.**
1. Should the **profile** adopt a marker the existing regex already detects (`<COORDINATOR_SCOPE>` matches
   `<[A-Z_]{3,}>` today), or should the **detector** learn the HTML-comment convention? The first is a
   one-line change to each profile and needs no fleet release; the second makes every profile written this
   way safe by default.
2. Is "a rendered child charter still holds a placeholder" a *lint* question or a *gate* question? It is
   the second: the useful moment is between rendering the charter and releasing the seed, which is a state
   only the coordinator is in. That suggests a check on the **child instant**, not on the profile — which
   is `fleet lint --instant`'s subject, and it does not currently have this rule.

**Closed when:** a charter whose scope is still a placeholder cannot silently reach a worker — either
because the marker is detectable, or because a check between render and seed refuses it.

---

## SI-47 — the dispatchable frontier is not enumerable; `roadmap` prints every row EXCEPT the ready ones

**Status:** OPEN. **Blocks:** `dispatching-a-wave` (its first step is "which rows are ready?").

**Measured 2026-09-05** against a scratch store (`FLEET_HOME`/`FLEET_INSTANTS` under a scratchpad), with
three milestones raised: `m1` ready, `m2` ready, `m3` blocked on `m1`.

```
$ fleet roadmap --instant "$I" --porcelain
not-ready   m3   info  dep(s) exist but have not LANDED ...  'm1' has status=ready
population  ...  info  examined 3 milestone(s) of which 2 ready, 0 pending proposal(s), from ...
```

**`m1` and `m2` are named in no row.** Confirmed across the observation surface: piping
`brief --porcelain`, `board --porcelain` and `roadmap --porcelain` together and grepping for `m1` as a
whole field returns **0**.

`Roadmap.report()` (`roadmap.py:497`) emits exactly three kinds: `not-ready` (and only where a blocker
exists — `if blocker is None: continue`), `pending-proposal`, and one `population` row. A `Roadmap.ready()`
method exists and is called, but only to compute the **count** interpolated into the population row's
prose: `f"examined {len(milestones)} milestone(s) of which {len(self.ready())} ready"`.

**Why it matters.** The coordinator's whole job at the top of the loop is *dispatch the ready rows*, and
the skill's own standing rule is **"read columns, never prose."** To learn which rows are ready, the
coordinator must parse a number out of an English sentence and then re-derive the set by hand. That the
count is present makes it worse, not better: it is enough to make the answer feel available.

`quantonOnSpark4V2` hit this and recorded it in its `HANDOFF.md` as *"⛔ THE BOARD HIDES THE ENTIRE
DISPATCHABLE FRONTIER — set equality, re-derived"*. `roadmap.py`'s own `retire()` docstring names the same
mechanism from the other side, as the reason a superseded milestone becomes invisible: *"`roadmap
--porcelain` prints `not-ready` rows but not ready ones — so a superseded milestone is a phantom."* The
consequence was known at the point of writing; the row kind was never added.

**What a fix must decide.**
1. A `ready` row kind at `severity=info`, or a `--ready` filter? A row kind composes with the existing
   parse (`awk -F'\t' '$1=="ready"'`) and needs no new flag. Preferred.
2. Does a ready row carry the claim state? A row that is ready **and already claimed** by an inflight
   dispatch is not dispatchable, and that distinction is the one a coordinator acts on. It should be a
   field, not something the reader joins against `board` by hand.
3. Severity. `info` is right — a ready row is not an alarm — but it must survive the standing
   "act on `attention`, report `info`" filter, so the skill's guidance has to say the frontier is read,
   not alerted.

**Closed when:** `fleet roadmap --porcelain` names every ready-and-unclaimed milestone as its own row, and
the count in the population row is derivable from rows the same command emitted.

---

## SI-48 — `fleet apply` silently regresses a `done` milestone, and the readiness cascade goes with it

**Status:** OPEN. **Severity: highest in this register** — it un-lands landed work with rc=0.
**Blocks:** `harvesting-an-instant`. **Field id:** `FI-415`.

**Reproduced 2026-09-05** in a scratch store, start to finish:

```
propose m1 -> done      ; apply  =>  applied m1 -> done          rc=0
propose m1 -> awaiting-ci (a stale proposal from an earlier round)
apply                   =>  applied m1 -> awaiting-ci            rc=0     <-- no refusal, no warning
```

The roadmap afterwards reads `[('m1','awaiting-ci'), ('m2','ready'), ('m3','blocked')]`, and the damage is
not confined to the row that moved:

```
not-ready  m1  status=awaiting-ci: it is already in flight, held by the coordinator
not-ready  m3  dep(s) ... have not LANDED: 'm1' has status=awaiting-ci
population     examined 3 milestone(s) of which 1 ready        <-- was 2
```

**`m3` was ready and is now blocked.** Because readiness is derived, regressing one row silently
re-blocks every row that depends on it — correct behaviour given a wrong input, which is what makes the
missing input check matter.

**Root cause.** `Roadmap.apply` (`roadmap.py:458`) validates exactly two things: that the status is a
known name (`_check_status`) and that the evidence resolves (`_check_evidence`). There is **no
monotonicity rule** — nothing compares the incoming status to the one already on the row. The module
already has the vocabulary: `TERMINAL` is defined and used by `retire()` to refuse retiring a milestone
that has finished. `apply` does not consult it.

The docstring is the sharpest evidence that this is an oversight rather than a decision:

> *"Validation happens here rather than only in `propose`, because a proposal can be hand-built or
> **replayed from a file**: a gate that only guards the polite path is not a gate."*

A replayed proposal is precisely the case that regresses, and it is the one case not guarded.

**How it presents in the field.** `FI-415`: a coordinator found a pending proposal that had sat in the
inbox **13 days**, whose last row would have landed `awaiting-ci` on a milestone the roadmap already
carried as `done` — from an instant that had since completed. It was caught by reading the inbox by hand
before applying. Nothing would have stopped it.

**What a fix must decide.**
1. **Refuse, or require an override?** A regression is occasionally legitimate — work found to be wrong
   after landing. `--override <reason>` already exists on `dispatch` as the pattern for "the rule is right
   and this case is the exception", and it records the reason.
2. **Which transitions are regressions?** The cheap, defensible rule: refuse any apply onto a row whose
   current status is in `TERMINAL` unless overridden. Ordering the non-terminal states is a bigger
   argument and is not needed to close this.
3. **Should a stale proposal expire?** The 13-day proposal was stale by age *and* by origin — its instant
   had completed. Either signal could warrant a warning row on `roadmap` before anyone types `apply`,
   which is the detect-half that pairs with the prevent-half above.

**Closed when:** applying a proposal that would move a milestone out of a terminal status is refused with
a reason naming both statuses, an override path exists and records why, and the integration suite covers
the replay case.

---

## SI-49 — `releasing-fleet` ships unlinted, and the coverage test only guards four skills

**Status:** OPEN. **Blocks:** nothing today; it is a hole in the checks, not a defect a routine works around.

**Cost.** Nothing yet, which is the point: nobody has looked. Widening `lint-skill.py` to cover a skill's
whole shipped documentation surfaced that `skills/releasing-fleet/` carries no `tests/lint-self.sh`, so
neither V1 nor V2 has ever run over it. Pointing the lint at it by hand reports two V1 findings and ten
V2 claims with no citation.

**Both V1 findings are false positives, and that is the blocker.** `COMMAND` matches `fleet` followed by
whitespace and a lowercase word inside a code span. Two spans in that skill fit the shape without being
commands:

- `` `fleet vX.Y.Z` `` — a **git tag name**, read as the verb `v`.
- `` `<upstream core>+fleet.<fleet version>` `` — a **version-string template**, read as the verb `version`.

Marking them `<!-- v1-proposed: v -->` would be a lie: neither is a verb anybody intends to build. So
enabling the lint here means either tightening `COMMAND` (excluding a following uppercase letter or `>`)
or giving the lint a way to say *this span is not a command*.

**A second, quieter half.** `skills/using-fleet/tests/every-skill-linted.sh` names four skills in `WANT`
and asserts each carries a lint suite. Ten now do. Its own PASS line still says "all four fleet skills",
so the six added since are unguarded: delete one of their `lint-self.sh` files and nothing notices.

**What a fix must decide.**
1. **Tighten `COMMAND`, or add a span-level opt-out?** Tightening is invisible and risks a real verb
   stopping being seen. An opt-out marker is explicit but is one more thing to write.
2. **Should `WANT` be a hand-kept list at all?** The list exists to catch *deletion*, which a glob cannot
   do — a glob over skills that have suites is vacuously true. Some enumeration has to be maintained; the
   question is whether it is enumerated here or derived from a manifest.

**Closed when:** `releasing-fleet` carries `tests/lint-self.sh` and passes it, no citation in it is a
lie, and the coverage test names every fleet skill that carries a suite.

---

## SI-50 — the IT suite measures two things it never asserts on

**Status:** OPEN. **Blocks:** nothing; it weakens two cases in the release gate rather than any skill.

**Cost.** Found by clearing `SC2034` across the repo: an "unused variable" in a test is not dead code, it
is usually **a measurement nobody checks**, and all three here sit inside cases whose own wording claims
exactly what the unchecked value would have proved.

This nearly went wrong in the sweep that found it: `f3_instants` was first deleted as dead, and only a
re-read of F3's pass message caught that the sentence *"and no instant was created"* had no other source.
**An unused variable in a test is a claim looking for its assertion; deleting it deletes the evidence that
the assertion is missing.**

**`f5_cap_room` — `fleet/it/run-F.sh`.** F5 is titled *"the cap has room AND the dispatch is still
refused"*. It computes `f5_cap_room` from the guard's own output, then gates on `f5_declared` and
`f5_still_refused` and never reads it. The "cap has room" half is asserted only indirectly, via *the
compaction declared `awaiting-ci`* — which is the input the cap is supposed to respond to, not the cap's
answer. A change that broke the cap's accounting while leaving the declaration intact would pass F5.

**`f3_instants` — `fleet/it/run-F.sh`.** F3's pass message ends *"and no instant was created"*. The gate is `exit != 0 && output mentions cap|wip`. The instant count is measured on the line above and never read, so the second half of that sentence is asserted by nothing. A dispatch that refused with the right message *and still created the folder* would pass F3 and read, in the register, as proof that it had not.

**`A_READONLY` — `fleet/it/run-A.sh`.** A1 asserts every **mutating** verb refuses with `FLEET_HOME`
unset. `A_MUTATING` and `A_READONLY` are derived side by side from `VERBS`; only the first is used. The
symmetric claim — that a read-only verb is **not** refused — is never made, so a change that made every
verb refuse would leave A1 green.

Both are the shape this repo already has a name for: *absence is never success*. A value computed and not
compared reads, to anyone skimming, exactly like a value that was checked.

**What a fix must decide.**
1. **Assert, or delete?** Asserting is the point, but adding an assertion to a gate that currently passes
   can turn it red on the first run, and that has to be a deliberate act with someone watching — not a
   side effect of a lint sweep. That is why both were left in place with a citation rather than fixed here.
2. **Is the read-only half of A1 even true?** It needs measuring before it is asserted; a read-only verb
   with no store may legitimately refuse for a different reason.

**Closed when:** each of the three values is either read by the assertion whose wording depends on it, or
deleted together with the clause it was supposed to support — and F3's and F5's stated claims match what
F3 and F5 actually check.

---

## SI-51 — `abort` does not disown the milestone, and the refusal names a remedy that does not work

**Status:** **FIXED in `0.5.0`** — `abort` releases the claim it can prove is its own, and
`fleet milestone --disown` releases one stranded before that existed. **Field ids:** `FI-383`, `FI-393`.

**Measured 2026-09-06** at `0.4.0`. `Roadmap.disown` (`roadmap.py:410`) has exactly **one** caller in the
package — `cli.py:1337`, inside `dispatch`'s rollback. `_do_abort` (`cli.py:2114`) writes the reason, kills
the session, releases the lease, renames the folder and stamps the record. It never touches the roadmap.

So a milestone claimed by a dispatch that is later aborted stays owned by a folder that is now `-abort-`,
**permanently**. And `claim`'s own refusal says the opposite:

> *"if that owner is gone, its record is what says so (`fleet board`, `fleet status`), and the work is
> released by aborting it with a reason."* — `roadmap.py:395`

That sentence is the remedy the coordinator is sent to, and it is the one thing that does not clear the
claim. The measured exits: `--override` does not clear it (it overrides admission rules, not ownership),
`harvest` refuses an aborted instant, and `abort` refuses to run twice (`name.state != "inflight"`). The
only escape was editing `roadmap.json` by hand — the single thing `fleet apply` exists to prevent — and
the live coordinator did it **nine** times.

**What a fix must decide.**
1. **Where does `abort` learn the coordinator?** `origin.json` records both `coordinator` and `milestone`
   and is written by the dispatcher; `Record.milestone` records the id but not the roadmap that holds it.
   Origin is the authority, and absence there must stay a legitimate answer — an instant from `fleet init`
   has no coordinator and must abort normally.
2. **May `abort` clear a claim it does not own?** `disown` currently clears whatever it finds. An abort of
   instant A must not release a milestone owned by instant B; the owner recorded by `claim` is the child
   instant path, captured **before** the rename.
3. **Before or after the irreversible step?** `abort`'s stated order is *"reason, session, lease, rename,
   stamp"* — every fallible step before the irreversible one. A roadmap write is fallible and cannot be
   undone by the rename. `dispatch`'s rollback already answers this shape: do it, and if it fails, say so
   loudly and name what to clear, never mask the outcome that already happened.
4. **What clears the milestones already stranded?** `abort` refuses to run twice, so a fix to `abort`
   reaches none of the existing nine. That needs its own surface or those stay hand-edited.

**Closed when:** aborting an instant that claimed a milestone leaves that milestone unowned; aborting one
that claimed nothing is unchanged; an abort whose origin names a milestone owned by a *different* instant
refuses to clear it and says whose it is; a roadmap write that fails is reported rather than swallowed;
there is a first-class way to release a claim stranded before the fix; and `roadmap.py:395`'s sentence is
true.

---

## SI-52 — `seed-check` calls a healthy worker `foreign`, and the remedy it names is destructive

**Status:** **FIXED in `0.5.0`** — only a `claude` process may be the source of a delivered
briefing, and an unreadable identity degrades to `NOT-DELIVERED`. **Field id:** `FI-402`.

**Measured 2026-09-06** at `0.4.0`. `seedcheck.delivered_argv(pid, probes, depth=2)` walks one generation
of descendants and returns **the first process carrying any non-flag argument of ≥200 characters**
(`MIN_PAYLOAD_CHARS`). There is no assertion anywhere in the module that the process it lands on is the
worker: `grep -n comm fleet/src/fleet/seedcheck.py` matches **one line, a comment about subcommands**, and
`Probes` carries only `read_cmdline` and `children_of`.

A worker in `awaiting-ci` runs a CI waiter — a shell holding a long inline script — as a child of the
claude process. That is exactly the shape `payload()` is looking for. `carries()` is then false, so
`classify` returns **`FOREIGN`**, whose `clears_when` is *"the launcher … is corrected and the worker is
dispatched again"*. The check fires on the population it is most often pointed at, and the remedy it
prints throws away a healthy worker's session.

The asymmetry is the whole problem: `NOT_DELIVERED` is deliberately non-refusing because `fleet` does not
deliver seeds, while `FOREIGN` **kills the session inside `dispatch`** (`cli.py:1304`). An uncertain probe
must not be able to produce the destructive verdict.

**What a fix must decide.**
1. **What makes a candidate the worker?** `session.default_probes` already answers this with
   `pgrep -x claude` plus a cmdline containment check, one verb away in `fleet peers`. The check needs the
   same notion, not a second one.
2. **Which direction is fail-safe?** `FOREIGN` authorises a kill. A candidate whose identity cannot be
   read must therefore degrade to `NOT_DELIVERED` (unverifiable), never to `FOREIGN`.
3. **Does the narrowing defeat the original detection?** The 2026-08-07 misdelivery was a shim that
   `exec`d the real binary with a foreign seed in argv — the process holding the briefing **was** claude.
   A fix that only ever looks at claude processes must still see that, or it has traded one false answer
   for another.

**Closed when:** a live worker with a long-argv non-claude descendant reports `VERIFIED` (or
`NOT-DELIVERED`), never `FOREIGN`; a foreign briefing delivered *to the claude process itself* still
reports `FOREIGN`; and a candidate whose identity cannot be determined reports `NOT-DELIVERED`.

---

## SI-53 — there is no `--seed-extra`, so the seed window is a race the coordinator loses

**Status:** **FIXED in `0.5.0`** — `dispatch --seed-extra <file>` appends inside the transaction,
so the window is zero. **Field ids:** `FI-387`, `FI-367`, `FI-388`.

**Measured 2026-09-06** at `0.4.0`. `dispatch` declares eleven flags (`cli.py:4017`) and **none** of them
adds anything to the briefing. The seed is whatever `profile.render` produces (`cli.py:1239`), written to
`<child>/.fleet/seed.txt` and then delivered by a launcher `fleet` neither writes nor reads.

A coordinator routinely has one or two dispatch-specific sentences to add — the wave's base, a
just-discovered constraint, which sibling to coordinate with. Today the only way is to append to
`seed.txt` **after** `dispatch` returns and **before** the launcher reads it. Pre-writing is
*structurally impossible*: the `i2-dispatch-seed-integrity` control refuses a seed file that exists before
the dispatch that renders it, correctly — a pre-written seed cannot contain a seed that does not exist
yet. So the coordinator races a launcher on a ~180s timer, and `FI-387` lost it by about a second: the
worker started on the briefing without the addition, and nothing said so.

**What a fix must decide.**
1. **Append or template?** A template variable makes the profile responsible for placement and breaks
   every profile that lacks the placeholder. An append needs no profile change and is what the race is
   trying to achieve.
2. **Where in the transaction?** It has to land before `seed.txt` is written, so the seed-integrity
   comparison sees one seed and not two. That also makes the addition part of what
   `_verify_seed_delivery` requires the launcher to have delivered.
3. **File or inline string?** A file. A briefing addition with newlines typed through a shell argument is
   how quoting bugs enter a worker's contract, and a file is a thing the dispatch record can point at.
4. **When is a bad path caught?** Before the lease is claimed. A missing file discovered after the claim
   costs a slot to report a typo.

**Closed when:** `dispatch --seed-extra <file>` puts the file's text into the rendered seed before it is
written; the delivered-seed check compares against the combined text; a missing or unreadable file is
refused before anything is claimed; and dispatch without the flag renders exactly what it rendered before.

---

## SI-54 — `pane-guard` is the only verb keyed on `--pane`; everything else takes `--id`

**Status:** **FIXED in `0.5.0`** — `pane-guard --id <todo>` resolves the pane through the record,
and a record with no session is refused rather than answered `13`. **Field id:** `FI-396`.

**Measured 2026-09-06** at `0.4.0`. `pane-guard` declares exactly one flag,
`Flag("--pane", True, True, "the pane (session) name")` (`cli.py:4193`). Every neighbouring verb —
`close`, `harvest`, `status`, `seed-check` — takes `--id <todo>`. The two identifiers differ by a
timestamp suffix, so the natural transcription is wrong, and the answer to a wrong pane name is `rc=13`
whose detail reads *"no live process and no session answer"* — a sentence about a **healthy** worker that
reads as a dead one.

This is the verb an external monitor must call before every send (`FD-10`), so its argument is retyped
more often than any other, and its failure mode is the one that most looks like a real finding.

**What a fix must decide.**
1. **Add `--id`, or rename?** Rename breaks every existing monitor. `--id` as an alternative keys the
   guard the way the rest of the CLI is keyed while leaving `--pane` exactly as it is.
2. **What resolves `--id` to a pane?** The record's `tmux` field — the same join `close` uses. A record
   with no session is a different answer from a pane that does not exist, and must not collapse into
   `rc=13`.
3. **Both, neither, or exactly one?** Exactly one. Two identifiers that could disagree is a third failure
   mode, and neither is not a question.
4. **Does the exit-code interface change?** No. The codes are the contract (`FD-10`); this changes how the
   pane is named, nothing about what is answered.

**Closed when:** `pane-guard --id <todo>` answers about that record's session with the same codes;
`--pane` is unchanged; supplying both or neither is refused with rc=2; and a record that names no session
says so instead of answering `13`.

---

## SI-55 — a send-keys delivery has no positive channel, so a rescued worker reads `not-delivered` forever

**Status:** **FIXED in `0.5.0`** — `fleet seed-delivered` records what was sent, and `seed-check`
reports a fourth state, `ATTESTED`. **Field id:** `FI-388`.

**Measured 2026-09-06** at `0.4.0`. `seedcheck` has three states and the positive one is reachable by
exactly one route: the briefing must appear in `/proc/<pid>/cmdline`. A seed delivered by `send-keys` —
which is how a revived pane is re-briefed, and how several launchers work — never appears in argv at all.
`grep -c 'attest\|ATTESTED' fleet/src/fleet/*.py` is **0**: there is no surface by which the actor that
performed the delivery can record what it sent.

The result is a permanent asymmetry on one board. A worker rescued by `reviving-dead-panes` reads
`NOT-DELIVERED` for the life of the instant while its sibling, dispatched through a launcher, reads
`VERIFIED` — and `NOT-DELIVERED`'s own detail says, correctly, that it is *"not evidence that anything is
wrong, and not evidence that anything is right"*. A row that can never change is a row that stops being
read, which is `FI-402`'s shape: a permanently-red gate gets read past.

**What a fix must decide.**
1. **Attestation or evidence?** An unchecked *"I delivered it"* is a claim, and this register does not
   accept claims as measurements. What the deliverer can supply that IS evidence is **the bytes it sent**:
   `fleet` digests them itself and compares against what it rendered. That catches the misdelivery class —
   the launcher sent the wrong file — which is the class the module exists for.
2. **Does it collapse into `VERIFIED`?** No. Observed-in-argv and recorded-by-the-deliverer are different
   facts with different failure modes, and `FI-195` is the error of collapsing two states whose remedies
   differ. It needs its own state.
3. **Is the new state a pass?** For the checker, yes — otherwise the row stays permanently red and nothing
   changes. Its detail must name the channel, so no reader mistakes it for an argv observation.
4. **Who may write it, and when?** Only about an instant that has a rendered seed, and a mismatch must be
   refused at write time rather than stored as a bad attestation for a later reader to discover.

**Closed when:** the actor that delivers a seed by `send-keys` can record what it delivered; `seed-check`
reports a distinct positive state for it whose detail names the channel; a recorded delivery whose digest
does not match the rendered seed is refused; and `VERIFIED` still means, exactly, that the briefing was
observed in the worker's argv.

---

## SI-56 — `FLEET_INSTANTS` unset silently planted the child in `$FLEET_HOME/instants`

**Status:** **CLOSED in `0.4.0`** — the guard is `cli.require_named_instants` (`cli.py:548`), applied at
the two handlers that bootstrap an instant (`cli.py:919`, `cli.py:1102`), with an AST non-drift check
(`test_root_resolution.py`) so a third creating verb cannot skip it, and IT case `R6`. **Field id:**
`FI-382`.

**Kept in the register rather than deleted, because the correction is the useful part.** The isolation
spec claimed this closed "for free": delete the derived `$FLEET_HOME/instants` fallback and the stray
child has nowhere to go. That was wrong, and implementing it proved so. Under isolation the stray lands in
`$ROOT/.fleet/instants` — **the right root and still the wrong tree**, invisible until an endgame
compaction cannot find the worker. The harm was always intra-root, so it needed its own refusal.

The second correction: the refusal could not live in the resolver. Written there it refused `board`,
because `reconcile` and `guards.blocking_compactions` read the instants directory on the **read** path
too. Resolution and requirement are different questions, and only the creating verbs ask the second one.

**Closed when:** met — a verb that creates an instant with no instants directory named refuses, cites
`SI-56`, and creates nothing; the same call with `--instants-dir` succeeds.
