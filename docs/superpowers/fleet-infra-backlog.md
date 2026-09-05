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
