# ISSUES   (durable; append-only; one sub-section per issue)

Every gap this instant exists to close has an **exhaustive, self-contained brief** under
`evidence/issues/`. The briefs are the record; the sections below are the index and carry only what a
brief cannot: the state, and anything learned AFTER the brief was written.

**Do not summarise a brief here.** Two copies of a finding is how `II-3` happened, and how `II-7` came to
describe a case that had passed.

| id | brief | state | blocked by |
|---|---|---|---|
| `G-1` | `evidence/issues/G-1-pane-delivery-verb.md` | OPEN, deferred `D-4` | operator decision |
| `G-2` | `evidence/issues/G-2-stall-loop-actuation.md` | OPEN | `G-1` for a clean fix |
| `G-3` | `evidence/issues/G-3-dispatch-scope-race.md` | OPEN, deferred `D-4` | needs a brainstorm |
| `G-4` | `evidence/issues/G-4-blocked-discriminator.md` | OPEN, deferred `D-4` | needs a brainstorm |
| `G-5` | `evidence/issues/G-5-every-case-can-fail.md` | OPEN, frame built | nothing |
| `G-6` | `evidence/issues/G-6-release-pipeline-undocumented.md` | **CLOSED `d07b4a2`** | — |
| `G-7` | `evidence/issues/G-7-refusal-names-no-route.md` | OPEN | nothing |
| `G-8` | `evidence/issues/G-8-no-status-closes-and-satisfies.md` | OPEN | interacts with `G-7` |
| `G-9` | this file, §"`G-9`" below | OPEN, found 2026-08-03 | nothing |
| `G-10` | this file, §"`G-10`" · RCA `investigations/g1-g2-stall-loop/analysis.md` | **FIXED `653ff90`** (control: `M-1`/`M-3` flipped to KILLED) | — |
| `G-12` | this file, §"`G-12`" | OPEN, found 2026-08-03 — pre-existing, out of scope here | the lint constant and both charters must change together |
| `G-11` | this file, §"`G-11`" | OPEN, found 2026-08-03 | an operator decision — it widens `ACTIONABLE_STATES` a third time |

## Ordering, and why
**See `PRIORITIES.md`** — impact analysis, effort, risk-of-fixing and a recommended sequence, with the
two non-negotiable sequencing constraints (`G-1` before `G-2`; never change `ACTIONABLE_STATES`
semantics twice without measuring in between).

Not repeated here. A second copy of a ranking is a second thing to drift.

## What is NOT here
Product defects found by monitoring the two quanton registers stay with the PARENT instant
(`00000000-08021753-inflight-append-quantonFeedbackAndReleases`), which keeps that standing duty. This
instant does not go looking for new findings; it closes six named ones.


## Added 2026-08-03 after re-reading the coordinator's register

It had been updated ~40 minutes earlier: 15 infra findings → 17. Both new ones landed on work shipped
that same night.

- **`G-7` (`FI-16`) corrects a false claim of mine.** `FI-10`'s premise — "no path exists to retire a
  milestone" — was wrong. `propose --to <self>` then `apply` works, and the reporter measured it. I
  reproduced `FI-10` with two probes, never tried the third, and shipped `milestone --retire` plus a
  commit message asserting the impossibility. The verb still matches what they asked for; the reasoning
  behind it did not survive.
- **`G-8` (`FI-17`) exposed a regression, now fixed.** `--retire` writes `dropped`, `dropped` is not
  `LANDED`, so retiring a milestone strands its dependents. And my `FI-2` fix filed that permanent block
  as INFO with an impossible `clears_when` — `FI-5`'s unclearable alarm, reintroduced by the fix for
  `FI-2`. Three of our own changes composing into a silent trap. Severity half fixed in `11f2f58`;
  the vocabulary gap is `G-8`.

**The lesson is one line and it is the third sighting:** *"I tried the two obvious things and neither
worked"* is not *"there is no way"* (`II-7`'s `A1a`, `FI-3`'s heading, now this).


## Added 2026-08-03 ~03:20Z by re-measuring the briefs before designing anything

`A-1` requires a re-measure before a gap is started. It is now `bin/reverify-briefs.sh` — one command, one
row per gap. Artifact: `evidence/2026-08-03-brief-reverification.txt`. It found two things.

### `A-2` is REFUTED, and it changes `G-1`'s scope — not just its wording
Full write-up in the brief (`evidence/issues/G-1-pane-delivery-verb.md` §6a) and the register entry
(`ASSUMPTIONS.md` `A-2`). In one line: **"`DA-2` enumerated six send paths" has no source.** `DA-2` is a
WITHDRAWN assumption about whether one script had defects; it enumerates nothing; every citation in this
tree traces back to the `cli.py:153` comment that cites it. Two in-repo implementations exist, both
test-harness, plus the external `claude-auto-retry`, which `DA-2` itself records as **still unread**.

The absence `G-1` is really about still holds — no send exists in the package. But the *de-duplication*
argument for the verb does not, and one of `G-1`'s closure criteria cannot be satisfied as written.
New assumption `A-4` covers the unread outside caller.

### `G-7`'s false premise is in the shipped source, not just the commit message
`Roadmap.retire`'s docstring (`roadmap.py:231`) argues its single-writer carve-out *from* "across 31 verbs
there was no way to do this … and no third one". A docstring is what the next person to touch the function
reads. Detail — including why this makes "should `--retire` become sugar?" a genuinely open call rather
than the foregone one the brief recommended — in `evidence/issues/G-7-refusal-names-no-route.md` §5a.

**Both are the same shape, and it is the fourth sighting: a claim repeated until it read as measured.**
`G-7` is that shape about a capability; `A-2` is that shape about a count. Neither survived one grep.

## `G-12` — both shipped charters instruct a command that EXITS 2, and the linter enforces the broken form
**Found 2026-08-03 by the Task-5 implementer, verified independently by its reviewer and again by the
controller.** Pre-existing (`FI-13`'s shape), untouched by this effort's changes, and deliberately left
unfixed by Task 5 because the fix spans the lint constant and both charters together.

**Symptom, executed:**
```
$ fleet declare phase awaiting-ci --instant <i> --watcher 1
declare: 'phase' is a bare argument, and declare declares no positionals.      # exit 2
```
`phase` is a stray positional and this parser accepts none — deliberately, because *"a bare token collected
into a field nobody read"* is a recorded defect (`cli.py`'s argv notes).

**Root cause — three documents, two forms, and the linter backs the wrong one:**
- `fleet/src/fleet/profiles.py:56` — `AWAITING_CI_CLAUSE = "fleet declare phase awaiting-ci"` (**broken**)
- `fleet/src/fleet/profiles.py:209` — **lints** that every shipped charter CONTAINS that literal, so the
  broken form is not merely documented, it is *required*. A charter carrying the working form would FAIL lint.
- `skills/using-fleet/profiles/worker/charter.md:26` and
  `skills/using-fleet/profiles/compaction/charter.md:20` — carry the broken form, as the lint demands.
- `skills/working-as-a-dispatched-instant/SKILL.md:106` — carries the **correct** form,
  `fleet declare --instant "$INSTANT" --phase awaiting-ci`.

**Blast radius.** A dispatched worker that follows its own charter literally **cannot declare `awaiting-ci`
at all**. Since the charter is the document the charter itself calls authoritative for scope, and since
`FI-13` shipped this clause in `0.3.1`, the phase has been undeclarable-from-the-charter for as long as the
clause has existed. A worker that does not declare it does not free the coordinator's WIP cap and decays to
`IDLE` after 30 minutes — so the visible symptom is a worker that looks stalled while legitimately waiting,
which is exactly the confusion `FI-13` was written to remove.

**It is also `G-7`'s class again, the fourth sighting.** The refusal states its rule (*"declare declares no
positionals"*) and does not name the route (`--phase`). A reader who trusts the charter over the skill has
been told the rule it broke and not the form that works.

**What a fix must do — all three together, or lint fights the fix:**
1. `AWAITING_CI_CLAUSE` becomes the working form (`fleet declare --phase awaiting-ci`, or a form that
   tolerates flag order).
2. Both charters updated to match.
3. Ideally the clause is checked by EXECUTION rather than by substring — a lint that greps for a command
   string cannot tell a runnable recipe from an unrunnable one, which is how this shipped. `fleet verify`
   already executes documented recipes; this clause is a candidate for it.

**Status:** OPEN, out of scope for the stall-loop plan. Not blocking it: nothing in `G-1`/`G-2`/`G-10`/`G-11`
depends on the charter's literal text, and `D-10`'s watcher requirement is enforced by the verb and by
`_live_state` regardless of which form a charter prints.

## `G-11` — a child's PARKED QUESTION reaches nobody: it is `FI-14`'s defect, one state over
**Found 2026-08-03 by the operator asking whether the `G-2` design would nudge a child that is legitimately
waiting on a coordinator's answer.** Probe: `bin/probe-nudge-eligibility.sh`. Artifact:
`evidence/2026-08-03-nudge-eligibility.txt`.

**Symptom, measured.** `fleet park --instant <i> --question "…"` is how a child says *"I cannot proceed
without a decision"* — and *"an empty park is not a park"*, so it is always a real question. Two situations,
both wrong:

| situation | state | `needs_a_human` | consequence |
|---|---|---|---|
| parked with a question, instant fresh | `PARKED` | **False** | **invisible.** The child is waiting on an answer and does not appear in the "N needs you" population at all |
| parked with a question, idle > 30min | `IDLE` | True | appears at last — but labelled `IDLE`, which reads *"it stopped"*, not *"it asked you something"*. The question survives only as a clause appended to the note |

**Root cause.** `PARKED` is not in `ACTIONABLE_STATES`. The state is computed correctly, rendered correctly,
carries the question in its note — and is excluded from the one predicate that decides whether a human is
needed. **That is `FI-14` exactly**: *"the detector, the threshold and the wording all existed; nothing read
them."* `FI-14` was that defect for `IDLE`; this is the same defect for `PARKED`, and arguably worse — `IDLE`
means "nobody knows why it stopped", while `PARKED` means "the child has explicitly asked you a question and
is blocked on the answer", which is the most actionable signal in the system.

`_live_state`'s park branch is careful that a park never MASKS an actionable state (*"an actionable state is
never masked by a standing note"*). Nobody made the park itself actionable.

**Action taken:** none yet. Recorded, with the probe, before designing around it.

**Status:** OPEN, and it needs an operator decision, because closing it means adding `PARKED` to
`ACTIONABLE_STATES` — **the third change to that tuple** (`FI-14` widened it 2026-08-02; `G-4` would change
it again). The standing constraint applies with full force: *never change `ACTIONABLE_STATES` semantics twice
without measuring the attention count in between.*

**Relationship to `G-2`:** independent, and it does not block the nudge work. `G-2`'s fix must simply not
nudge a parked child (`D-8`); making the question VISIBLE is this gap.

## `G-10` — `FI-14`'s IDLE DETECTOR is guarded by no test at all
**Found 2026-08-03 while reproducing `G-2`, not by looking for it.** Full RCA:
`investigations/g1-g2-stall-loop/analysis.md`. Artifacts: `evidence/2026-08-03-repro-g2.txt` PART 3,
`evidence/repro-g2/part3-mutations.tsv`.

**Symptom:** `_live_state`'s idle branch can be made permanently dead — no worker EVER classified `IDLE` —
and the full hermetic suite stays GREEN (1183 tests). Same for breaking the activity probe it depends on.
The mutation experiment carries a control: reverting `FI-14`'s actual shipped fix (dropping `IDLE` from
`ACTIONABLE_STATES`) IS killed, by `test_render.test_a_stalled_worker_is_counted_as_needing_a_human`. So the
harness can kill; it simply never looks at the detector.

**Root cause:** that flagship test hand-builds a subject already labeled `IDLE`
(`fleet/tests/test_render.py:176`) and asserts the banner counts it. It never invokes `reconcile`. It
asserts the VIEW of an idle subject, so it passes whether or not one can ever be produced. The note string
is even retyped by hand and truncated relative to the real one.

**Why it matters here:** this is the foundation `G-2`'s actuation was about to be built on. ("Actuator" = the
missing component that ACTS on the judgement rather than displaying it; today that component is the operator.
Defined with the whole control loop in the RCA's §"Terms used below".) An actuator over
an unguarded detector means a future regression in `_live_state` presents as *"the nudges stopped working"*,
with the detector the last place anyone looks — and M-1/M-3 prove nothing would flag it.

**Action taken:** reproduced with a control and recorded. `bin/repro-g2-stall-loop.sh` PART 1 already IS the
missing test; it needs to become a case in `fleet/tests/`. Sequenced as step 1 of the `G-1`+`G-2` fix
direction, before any actuator.

**Status: FIXED `653ff90`** (2026-08-03), and the fix is PROVEN rather than asserted. Three cases in
`test_reconcile.TestTheIdleDetectorIsProduced` drive the real join: a worker untouched past the threshold is
*produced* as `IDLE`, a busy pane is never `IDLE` however old its files, and the threshold is a boundary
rather than a hard-coded constant. 1183 → 1186 tests, green.

**The control is what makes this a closure and not a claim.** Re-running the mutation experiment,
`M-1` (threshold branch disabled) and `M-3` (activity probe always fresh) flipped **SURVIVED → KILLED**,
while `M-2` (the harness control) stayed KILLED. Verified by REASON, not by exit code: `mut1.out` and
`mut3.out` each name the two new tests as the failing cases, so neither is a kill-by-ImportError — the
distinction that once made four `M9` mutants false kills. `test_a_working_worker_is_never_idle_however_old_
the_instant` correctly does NOT fail under either mutation, because it asserts a busy pane stays `RUNNING`,
which the idle branch does not touch.

Artifacts: `evidence/repro-g2/part3-mutations-{BEFORE,AFTER}.tsv`, `mut1.out`, `mut3.out`, `baseline.out`.
Regenerate: `bash bin/repro-g2-stall-loop.sh`. Still counts as the first DEMONSTRATED entry in `G-5`'s frame
(`P-C`, eight sightings, one shipped as `SI-38`), so `G-5`'s population inherits it.

## `G-9` — `bin/reverify-briefs.sh` is a check with no control
**Symptom:** the script decides whether every gap's premise still holds, and its verdict is now cited by
`evidence/INDEX.md` as the proof for `A-1`. Nothing demonstrates that a row can go RED. A `HOLDS` row could
be vacuous — which is `P-C` ("green for the wrong reason"), the exact defect family `G-5` exists to
counter, reintroduced by a script written to serve `G-5`'s discipline.

**Root cause:** written as a measurement, adopted as a gate, and the charter's rule — *"every fix to a
check ships with a control proving the check still fails when it should"* — was not applied to it because
it did not look like a check when it was written.

**Two real risks, not hypothetical:** two of the ten rows are `grep -c … = 0` assertions over an ABSENCE
(`G-1`, `G-4`). An absence check passes when the path is wrong, the file is renamed, or the pattern stops
matching for an unrelated reason. Those are the two rows most likely to be vacuously green.

**Action taken:** none yet; recorded before use rather than after. The control is a `cp -r` of the tree
with each premise deliberately broken (collect `session_attached`; add a `send-keys` call to `fleet/src`;
widen `LANDED`), asserting the matching row flips to `MOVED` **and that the others do not** — the
`run-m9-mutation.sh` pattern, which is also what caught `QI-1`'s four mutants that died of the wrong
error. Cheap: an hour.

**Status:** OPEN. Blocks nothing, but the script's verdict should not be cited as proof of anything beyond
its own rows until it exists.
