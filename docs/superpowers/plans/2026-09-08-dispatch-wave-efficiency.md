# Dispatch Wave Efficiency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the ~1,080 minutes per five-instant wave that go to CI waves that should not have been run, waits that look alive and are not, and close-out churn — by gating the wrong move in `fleet` where a gate is possible and fixing the skill and profile text that produced the rest.

**Architecture:** Three independent lanes. Lane A adds one new fact (`Round.heads`) and four refusals to `fleet`, all sitting beside gates that already exist at the same call sites. Lane B edits five skills. Lane C edits the effort-local `ansi-gap-closure` profile, which ships outside any release. Nothing in Lane A changes a schema version: every new field is added with a default and an absent value reads as NOT MEASURED, never as a mismatch.

**Tech Stack:** Python 3 stdlib only (`fleet` is zero-dependency by design), `unittest`, bash for the IT section, Markdown for lanes B and C.

**Spec:** `docs/superpowers/specs/2026-09-08-dispatch-wave-efficiency-design.md`

## Global Constraints

- **Zero third-party dependencies.** `fleet` imports stdlib only.
- **`review.SCHEMA_VERSION` stays `1` and `layout.SPEC_VERSION` stays `1`.** `Review.rounds()` refuses on a version mismatch (`review.py:171-183`); bumping it would refuse every live ledger in the effort.
- **An absent `heads` or `at` is NOT MEASURED, never a mismatch.** Rounds and declarations written before this change carry neither. Reading absence as an answer is the `FI-417` failure.
- **`Round.to_json` emits `heads` only when non-empty.** `test_review` compares rendered ledgers; an always-present empty key changes bytes for every existing fixture.
- **Refusals name what clears them and who clears them.** Every new refusal states what it observed, what it expected, and the exact command that clears it.
- **Porcelain is tab-separated with no banner.** New rows go through `_emit`/`Row` like every other row; never `print`.
- **Run bash scripts under `bash`, never `zsh`.** zsh does not word-split unquoted expansions — the defect this plan exists partly to fix.
- **Test command:** `cd fleet && PYTHONPATH=src python3 -m unittest discover -s tests -q` (~90 s, 1706 tests at the start commit).
- **Pre-flight corrections live in the SDD ledger** (`.superpowers/sdd/2026-09-08-dispatch-wave-efficiency/progress.md`, rulings R1–R8): `Refused` takes no `guard=`/`reason=`; record/slot/workspace come from `_record_for`/`_slot_of`/`Workspace(ctx.home, git=ctx.git)`; `Declarations` is in `store.py`; the IT section is `RH`/`run-reviewhead.sh`; tests use the existing `CliCase`/`Fleet` fixture. Each task brief carries the correction that binds it. Single module: `PYTHONPATH=src python3 -m unittest tests.test_review -v`.
- **`fleet/it/RESULTS.tsv` is tracked and read by `skills/using-fleet/tools/lint-skill.py`.** Standalone IT runs must set `IT_RESULTS` to a scratch path or they clobber it. Note that script is `using-fleet`'s claim-citation checker, **not** a general `SKILL.md` linter — this repo has none, and `superpowers:writing-skills` governs skill edits instead.
- **Skill-content changes need eval evidence per the repo `CLAUDE.md`, and `evals/` is not cloned in this checkout.** Task 12 resolves this before any Lane B task lands.

---

## File Structure

| file | responsibility |
|---|---|
| `fleet/src/fleet/workspace.py` | gains `heads()` — the repo→sha snapshot, mirroring `dirty()` |
| `fleet/src/fleet/review.py` | `Round.heads`; `FINDING_STATUSES` gains `routed` |
| `fleet/src/fleet/session.py` | `Declarations` records `at` on `set_phase` |
| `fleet/src/fleet/reconcile.py` | `_live_state` re-observes the watcher and flags a stale wait |
| `fleet/src/fleet/cli.py` | `review` records heads; `propose --status done` and `complete` gain refusals; `declare` gains an advisory |
| `fleet/src/fleet/layout.py` | `_seed` writes a compliant register header |
| `fleet/tests/test_workspace.py` | new — `heads()` cases |
| `fleet/tests/test_review.py` | `heads` round-trip, `routed` status |
| `fleet/tests/test_reconcile.py` | watcher re-observation, stale wait |
| `fleet/tests/test_cli.py` | the three new refusals and the one advisory |
| `fleet/tests/test_layout.py` | seeded header shape |
| `fleet/it/S/run-S.sh` | new — the round-to-head binding across a real push |
| `skills/working-as-a-dispatched-instant/SKILL.md` | close-out contract; scratch rule; watcher recipe |
| `skills/subagent-driven-development/SKILL.md` | waiting rule; implementer Monitor rule; inline execution |
| `skills/reviewing-workspace/SKILL.md` | prose home; pre-complete timing |
| `skills/requesting-code-review/SKILL.md` | comment-only findings are riders |
| `operations/…/profiles/ansi-gap-closure/seed.txt` | native paragraph; skill list; pre-push checklist |
| `operations/…/profiles/ansi-gap-closure/charter.md` | CI latency profile; runbook stub; prior-instant pointers |

---

## Phase 1 — Lane A, the fleet gates

### Task 1: `Workspace.heads()`

**Files:**
- Modify: `fleet/src/fleet/workspace.py` (after `dirty`, ~line 223)
- Test: `fleet/tests/test_workspace.py` (create)

**Interfaces:**
- Produces: `Workspace.heads(slot_path: Path, repos) -> dict` — repo name to 40-hex sha. A repo whose `rev-parse` fails is **omitted**, never recorded as empty.

- [ ] **Step 1: Write the failing test**

```python
"""Repo HEAD snapshots. A repo that cannot answer is omitted, never recorded as empty:
an empty string would read as a measured answer downstream (FI-417)."""
import pathlib
import tempfile
import unittest

from fleet.workspace import Workspace


class FakeGit:
    def __init__(self, answers):
        self.answers = answers

    def __call__(self, args, cwd):
        return self.answers.get(pathlib.Path(cwd).name, (1, ""))


class TestHeads(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def test_heads_maps_each_repo_to_its_sha(self):
        ws = Workspace()
        ws.git = FakeGit({"gluten-internal": (0, "a" * 40 + "\n"),
                          "velox-internal": (0, "b" * 40 + "\n")})
        self.assertEqual(ws.heads(self.tmp, ["velox-internal", "gluten-internal"]),
                         {"gluten-internal": "a" * 40, "velox-internal": "b" * 40})

    def test_a_repo_that_cannot_answer_is_omitted_not_empty(self):
        ws = Workspace()
        ws.git = FakeGit({"gluten-internal": (0, "a" * 40 + "\n"), "velox-internal": (128, "")})
        self.assertEqual(ws.heads(self.tmp, ["gluten-internal", "velox-internal"]),
                         {"gluten-internal": "a" * 40})
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_workspace -v`
Expected: FAIL with `AttributeError: 'Workspace' object has no attribute 'heads'`

- [ ] **Step 3: Implement the minimal code**

Add to `workspace.py`, directly after `dirty`:

```python
    def heads(self, slot_path: Path, repos) -> dict:
        """Each repo's current HEAD, for binding a review round to the code it reviewed.

        A repo that cannot answer is OMITTED rather than recorded as empty: an empty sha would compare
        unequal to every real sha and turn a slot this tool could not read into a false mismatch. Absence
        is read downstream as NOT MEASURED (`FI-417`).
        """
        slot = Path(slot_path)
        out = {}
        for repo in sorted(repos):
            rc, stdout = self.git(["rev-parse", "HEAD"], slot / repo)
            if rc == 0 and stdout.strip():
                out[repo] = stdout.strip()
        return out
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_workspace -v`
Expected: PASS, 2 tests

- [ ] **Step 5: Commit**

```bash
git add fleet/src/fleet/workspace.py fleet/tests/test_workspace.py
git commit -m "workspace: heads() snapshots each repo's HEAD, omitting what it cannot read"
```

---

### Task 2: `Round.heads`, carried through the ledger

**Files:**
- Modify: `fleet/src/fleet/review.py:110-140` (the `Round` dataclass)
- Test: `fleet/tests/test_review.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Round(number, scope, verdict, findings, at, heads={})`; `Round.to_json()` emits `"heads"` only when non-empty; `Round.from_json` reads `d.get("heads", {})`. `Review.add_round(scope, verdict, findings, heads=None)`.

- [ ] **Step 1: Write the failing test**

Add to `fleet/tests/test_review.py`:

```python
    def test_heads_round_trip_and_absent_stays_absent(self):
        """A round carries the code it reviewed. A ledger written before this field keeps validating,
        and its rounds report {} — NOT MEASURED, which no gate may read as a mismatch."""
        made = Round(number=1, scope="code", verdict="READY", findings=[], at=TICKS[0],
                     heads={"gluten-internal": "a" * 40})
        self.assertEqual(made.to_json()["heads"], {"gluten-internal": "a" * 40})
        self.assertEqual(Round.from_json(made.to_json()).heads, {"gluten-internal": "a" * 40})

    def test_a_round_with_no_heads_emits_no_key(self):
        made = Round(number=1, scope="code", verdict="READY", findings=[], at=TICKS[0])
        self.assertNotIn("heads", made.to_json())
        self.assertEqual(Round.from_json({"number": 1, "scope": "code", "verdict": "READY",
                                          "at": TICKS[0], "findings": []}).heads, {})
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_review -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'heads'`

- [ ] **Step 3: Implement the minimal code**

In `review.py`, add the import and change `Round`:

```python
from dataclasses import dataclass, field
```

```python
@dataclass(frozen=True)
class Round:
    """One review pass: what it looked at, what it concluded, what it saw, and the code it saw it in."""

    number: int
    scope: str
    verdict: str
    findings: list
    at: str
    #: repo -> sha at the moment the round was recorded. Empty means the slot could not be read, which
    #: is NOT MEASURED and never a mismatch — every round written before this field carries it empty.
    heads: dict = field(default_factory=dict)

    def thin(self) -> bool:
        return not self.findings

    def to_json(self) -> dict:
        out = {"number": self.number, "scope": self.scope, "verdict": self.verdict, "at": self.at,
               "findings": [f.to_json() for f in self.findings]}
        #: Emitted only when populated, so every ledger written before this field renders byte-identically.
        if self.heads:
            out["heads"] = dict(sorted(self.heads.items()))
        return out

    @classmethod
    def from_json(cls, d: dict) -> "Round":
        return cls(number=d["number"], scope=d["scope"], verdict=d["verdict"], at=d["at"],
                   findings=[Finding.from_json(f) for f in d["findings"]],
                   heads=dict(d.get("heads", {})))
```

And thread it through `add_round` (`review.py:184-207`):

```python
    def add_round(self, scope: str, verdict: str, findings: list, heads=None) -> Round:
```

then inside the `held_for_update` block:

```python
            made = Round(number=len(existing) + 1, scope=scope, verdict=verdict, findings=findings,
                         at=self._now(), heads=dict(heads or {}))
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_review -v`
Expected: PASS, including every pre-existing case

- [ ] **Step 5: Commit**

```bash
git add fleet/src/fleet/review.py fleet/tests/test_review.py
git commit -m "review: a round records the repo HEADs it reviewed; absent stays NOT MEASURED"
```

---

### Task 3: `fleet review` records the heads it reviewed

**Files:**
- Modify: `fleet/src/fleet/cli.py` (`_do_review`)
- Test: `fleet/tests/test_cli.py`

**Interfaces:**
- Consumes: `Workspace.heads` (Task 1), `Review.add_round(..., heads=)` (Task 2).
- Produces: a recorded round whose `heads` is the slot's HEADs for the repos named in the record's `lineage_base`. No record, no lineage, or no slot leaves `heads` empty.

- [ ] **Step 1: Write the failing test**

Add to `fleet/tests/test_cli.py`:

```python
    def test_review_records_the_slot_heads_for_the_lineage_repos(self):
        """The round is bound to the code it reviewed. Without the binding, 'a review happened' and
        'the graded code was reviewed' are different facts nothing connects."""
        env = self.effort_with_worker(lineage_base="gluten-internal=" + "a" * 40)
        self.write_repo_head(env.slot / "gluten-internal", "b" * 40)
        rc = self.run_cli(["review", "--instant", str(env.instant), "--scope", "code",
                           "--verdict", "READY",
                           "--finding", "RV-1:Minor:applied:SPEC.md:the arm table is complete:none"])
        self.assertEqual(rc, EXIT_OK)
        ledger = json.loads((env.instant / ".fleet" / "review.json").read_text())
        self.assertEqual(ledger["rounds"][0]["heads"], {"gluten-internal": "b" * 40})

    def test_review_without_a_readable_slot_records_no_heads(self):
        env = self.effort_with_worker(lineage_base="")
        rc = self.run_cli(["review", "--instant", str(env.instant), "--scope", "code",
                           "--verdict", "READY",
                           "--finding", "RV-1:Minor:applied:SPEC.md:nothing to bind:none"])
        self.assertEqual(rc, EXIT_OK)
        ledger = json.loads((env.instant / ".fleet" / "review.json").read_text())
        self.assertNotIn("heads", ledger["rounds"][0])
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_cli -v -k heads`
Expected: FAIL — `KeyError: 'heads'`

- [ ] **Step 3: Implement the minimal code**

Add a helper next to `_do_review` in `cli.py`:

```python
def _reviewed_heads(ctx: Ctx, child: Path) -> dict:
    """The slot's HEADs for the repos this instant's lineage names, or `{}` when they cannot be read.

    Empty is the honest answer for an analysis instant, a released slot, or a record this tool cannot
    find — and empty is read downstream as NOT MEASURED, never as a mismatch.
    """
    record = ctx.store.record_for_instant(child)
    if record is None or not record.lineage_base or not record.golden:
        return {}
    repos = _lineage_pairs(record.lineage_base, "--lineage-base")
    return ctx.workspace.heads(Path(record.golden), repos)
```

Then in `_do_review`, change the recording call:

```python
        made = review.add_round(parsed.get("scope", "all"), verdict_asked, findings,
                                heads=_reviewed_heads(ctx, child))
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_cli -v -k heads`
Expected: PASS, 2 tests

- [ ] **Step 5: Commit**

```bash
git add fleet/src/fleet/cli.py fleet/tests/test_cli.py
git commit -m "review: bind each recorded round to the slot HEADs it reviewed"
```

---

### Task 4: `propose --status done` refuses a head no round has seen

**Files:**
- Modify: `fleet/src/fleet/cli.py` (`_do_propose`)
- Test: `fleet/tests/test_cli.py`

**Interfaces:**
- Consumes: `Round.heads`, `Workspace.heads`.
- Produces: exit 4 with guard `review-head` when the newest round carrying heads disagrees with the slot's current HEADs.

- [ ] **Step 1: Write the failing test**

```python
    def test_propose_done_refuses_a_head_the_newest_round_never_reviewed(self):
        """trypmod, unaryminus and try-subtree each pushed, then reviewed, then pushed the fixes —
        a second 3.3 h CI wave each time. Grading a head no round has seen is the moment that is
        visible to this tool."""
        env = self.effort_with_worker(lineage_base="gluten-internal=" + "a" * 40)
        self.write_repo_head(env.slot / "gluten-internal", "b" * 40)
        self.run_cli(["review", "--instant", str(env.instant), "--scope", "all", "--verdict", "READY",
                      "--finding", "RV-1:Minor:applied:SPEC.md:reviewed at b:none"])
        self.write_repo_head(env.slot / "gluten-internal", "c" * 40)
        rc = self.run_cli(["propose", "--instant", str(env.instant), "--milestone", "m1",
                           "--status", "done", "--evidence", "evidence/INDEX.md"])
        self.assertEqual(rc, EXIT_REFUSED)
        self.assertIn("review-head", self.stderr())
        self.assertIn("c" * 40, self.stderr())

    def test_propose_done_allows_a_head_the_newest_round_reviewed(self):
        env = self.effort_with_worker(lineage_base="gluten-internal=" + "a" * 40)
        self.write_repo_head(env.slot / "gluten-internal", "b" * 40)
        self.run_cli(["review", "--instant", str(env.instant), "--scope", "all", "--verdict", "READY",
                      "--finding", "RV-1:Minor:applied:SPEC.md:reviewed at b:none"])
        rc = self.run_cli(["propose", "--instant", str(env.instant), "--milestone", "m1",
                           "--status", "done", "--evidence", "evidence/INDEX.md"])
        self.assertEqual(rc, EXIT_OK)

    def test_propose_done_is_not_gated_when_no_round_carries_heads(self):
        """Every ledger written before this field. Absence is NOT MEASURED, never a mismatch."""
        env = self.effort_with_worker(lineage_base="gluten-internal=" + "a" * 40)
        self.write_legacy_round(env.instant, scope="all", verdict="READY")
        rc = self.run_cli(["propose", "--instant", str(env.instant), "--milestone", "m1",
                           "--status", "done", "--evidence", "evidence/INDEX.md"])
        self.assertEqual(rc, EXIT_OK)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_cli -v -k propose_done`
Expected: FAIL — the first case exits 0 instead of 4

- [ ] **Step 3: Implement the minimal code**

Add to `cli.py` beside the other gates:

```python
GUARD_REVIEW_HEAD = "review-head"


def _review_head_gate(ctx: Ctx, child: Path) -> None:
    """Refuse to claim done on a head no review round has seen.

    Measured across five instants: reviewing AFTER the push cost a second heavy CI wave four times, at
    3.3 h a wave, and once the late review found a real defect (six suite pins that would have reddened
    the ANSI dim) — so the review was already worth running first. This gate fires at the moment the
    tool can see it: the claim of done.

    A round with no recorded heads is NOT MEASURED and never a mismatch.
    """
    rounds = [r for r in Review(child, now=ctx.now).rounds() if r.heads]
    if not rounds:
        return
    newest = rounds[-1]
    current = _reviewed_heads(ctx, child)
    if not current or current == newest.heads:
        return
    moved = sorted(repo for repo in set(newest.heads) | set(current)
                   if newest.heads.get(repo) != current.get(repo))
    raise Refused(
        guard=GUARD_REVIEW_HEAD,
        reason=(f"round {newest.number} reviewed "
                + ", ".join(f"{repo}={newest.heads.get(repo, '(absent)')}" for repo in moved)
                + " and the slot is now at "
                + ", ".join(f"{repo}={current.get(repo, '(absent)')}" for repo in moved)
                + ". The head being graded carries commits no review round has seen, so a finding in "
                  "them costs another full CI wave to fix."),
        clears_when=(f"review the current head — `fleet review --instant {child} --scope code "
                     f"--verdict <v> --finding ...` — then propose again"),
        clears_who="this worker")
```

Call it in `_do_propose`, only for the terminal claim, beside the existing lineage gate:

```python
    if parsed.get("status") == "done":
        _lineage_gate(ctx, child, "propose --status done")
        _review_head_gate(ctx, child)
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_cli -v -k propose_done`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add fleet/src/fleet/cli.py fleet/tests/test_cli.py
git commit -m "propose: refuse --status done on a head no review round has seen"
```

---

### Task 5: `declare --phase awaiting-ci` says whether this head was reviewed

**Files:**
- Modify: `fleet/src/fleet/cli.py` (`_do_declare`)
- Test: `fleet/tests/test_cli.py`

**Interfaces:**
- Consumes: `_reviewed_heads`, `Round.heads`.
- Produces: one extra `Row` on `declare`. **Advisory, never a refusal** — by declare time the push has already happened, and refusing would strand the worker with a running wave it may not abandon.

- [ ] **Step 1: Write the failing test**

```python
    def test_declare_awaiting_ci_reports_an_unreviewed_head(self):
        env = self.effort_with_worker(lineage_base="gluten-internal=" + "a" * 40, watched=True)
        self.write_repo_head(env.slot / "gluten-internal", "b" * 40)
        rc = self.run_cli(["declare", "--instant", str(env.instant), "--phase", "awaiting-ci"])
        self.assertEqual(rc, EXIT_OK)
        self.assertIn("no review round has seen this head", self.stdout())
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_cli -v -k declare_awaiting_ci_reports`
Expected: FAIL — the phrase is absent

- [ ] **Step 3: Implement the minimal code**

In `_do_declare`, after the watcher rows are assembled and before `_emit`:

```python
    review_row = []
    if phase == PHASE_AWAITING_CI:
        rounds = [r for r in Review(child, now=ctx.now).rounds() if r.heads]
        current = _reviewed_heads(ctx, child)
        if current and (not rounds or rounds[-1].heads != current):
            review_row = [("review", "no review round has seen this head; a finding now costs another "
                                     "full CI wave. Converge the review before the next push")]
```

and add `+ review_row` to the `_emit` row list.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_cli -v -k declare`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fleet/src/fleet/cli.py fleet/tests/test_cli.py
git commit -m "declare: awaiting-ci reports whether a review round has seen this head"
```

---

### Task 6: a `routed` finding status

**Files:**
- Modify: `fleet/src/fleet/review.py:54-57`, and the `Finding.__post_init__` message
- Test: `fleet/tests/test_review.py`

**Interfaces:**
- Produces: `FINDING_STATUSES = ("open", "applied", "wont-fix", "routed")`. Only `open` blocks, so `routed` is non-blocking by construction.

- [ ] **Step 1: Write the failing test**

```python
    def test_routed_records_an_owner_and_never_blocks(self):
        """try-subtree recorded an Important finding against the coordinator-authored CHARTER.md — a file
        a worker may never edit. With no `routed` status it sat `open`, the gate refused READY, and the
        worker cleared it by editing the coordinator's charter. A missing enum value forced an ownership
        violation."""
        review = Review(self.instant, now=self.tick)
        review.add_round("all", "READY", [Finding("RV-8", "Important", "routed", "CHARTER.md",
                                                  "the charter has no Updated|Status header",
                                                  "coordinator fixes it at the template")])
        self.assertEqual(review.open_blocking(), [])
        self.assertTrue(review.gate(require_scope="all").allowed)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_review -v -k routed`
Expected: FAIL with `BadInput: finding status='routed' is outside its declared domain`

- [ ] **Step 3: Implement the minimal code**

```python
#: A finding's disposition. `wont-fix` is a recorded decision and not a loophole, because `action` is
#: required to be non-empty on every finding — declining a Critical therefore costs a written reason.
#: `routed` is the same bargain for a finding this instant does not OWN: its `action` names who does.
#: Without it, a finding against a coordinator-owned file could only sit `open`, and an `open` blocking
#: finding refuses the gate — which once made a worker edit the coordinator's charter to clear its own
#: gate. Only `open` blocks, so `routed` is non-blocking by construction.
OPEN = "open"
FINDING_STATUSES = (OPEN, "applied", "wont-fix", "routed")
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_review -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fleet/src/fleet/review.py fleet/tests/test_review.py
git commit -m "review: a routed finding names its owner and does not block this worker's gate"
```

---

### Task 7: `complete` refuses pointers the rename is about to break

**Files:**
- Modify: `fleet/src/fleet/cli.py:2342` (`_do_complete`)
- Test: `fleet/tests/test_cli.py`

**Interfaces:**
- Produces: exit 4 with guard `complete-pointers`, listing `file:line` per broken pointer.

- [ ] **Step 1: Write the failing test**

```python
    def test_complete_refuses_a_pointer_the_rename_will_break(self):
        """complete IS the rename, so at gate time every -inflight- path still resolves. Checking
        'does this path exist' passes and then breaks one millisecond later. The question is whether
        the pointer SURVIVES the rename."""
        env = self.ready_to_complete()
        (env.instant / "HANDOFF.md").write_text(
            "## Resume\n\nRead " + str(env.instant) + "/evidence/INDEX.md first.\n")
        rc = self.run_cli(["complete", "--instant", str(env.instant)])
        self.assertEqual(rc, EXIT_REFUSED)
        self.assertIn("complete-pointers", self.stderr())
        self.assertIn("HANDOFF.md:3", self.stderr())
        self.assertTrue(env.instant.exists(), "refused, so the folder was NOT renamed")

    def test_complete_allows_an_instant_relative_pointer(self):
        env = self.ready_to_complete()
        (env.instant / "HANDOFF.md").write_text("## Resume\n\nRead `evidence/INDEX.md` first.\n")
        self.assertEqual(self.run_cli(["complete", "--instant", str(env.instant)]), EXIT_OK)

    def test_complete_refuses_while_the_phase_is_still_awaiting_ci(self):
        env = self.ready_to_complete()
        Declarations(env.instant).set_phase("awaiting-ci")
        rc = self.run_cli(["complete", "--instant", str(env.instant)])
        self.assertEqual(rc, EXIT_REFUSED)
        self.assertIn("fleet declare --phase done", self.stderr())
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_cli -v -k complete_refuses`
Expected: FAIL — both cases exit 0 and the folder is renamed

- [ ] **Step 3: Implement the minimal code**

```python
GUARD_COMPLETE_POINTERS = "complete-pointers"

#: The two documents a resuming reader and the coordinator actually navigate from. CHARTER.md and
#: .fleet/seed.txt also carry the folder name and are deliberately NOT scanned: they are rendered by the
#: dispatcher, so a refusal on them would land on somebody who cannot fix it.
_POINTER_DOCS = ("HANDOFF.md", "evidence/INDEX.md")


def _pointer_gate(ctx: Ctx, child: Path) -> None:
    """Refuse to rename out from under this instant's own pointers.

    Measured in three instants: `complete` succeeded while HANDOFF still named the `-inflight-` path and
    an INDEX row still read `*pending*`, and each cost an operator round trip to discover.
    """
    offenders = []
    for rel in _POINTER_DOCS:
        path = child / rel
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if child.name in line:
                offenders.append(f"{rel}:{number}")
    if not offenders:
        return
    raise Refused(
        guard=GUARD_COMPLETE_POINTERS,
        reason=(f"{len(offenders)} pointer(s) name this instant's own folder, which `complete` is about "
                f"to rename: {', '.join(offenders)}. They resolve now and will not resolve in one "
                f"millisecond."),
        clears_when=("cite paths RELATIVE to the instant (`evidence/INDEX.md`, not the absolute path) — "
                     "the maintain-workspace rule — then complete again"),
        clears_who="this worker")
```

In `_do_complete`, immediately after `_lineage_gate(ctx, child, "complete")`:

```python
    _pointer_gate(ctx, child)
    if Declarations(child).phase() == PHASE_AWAITING_CI:
        raise Refused(
            guard=GUARD_COMPLETE_POINTERS,
            reason="the declared phase is still awaiting-ci, and an instant that is completing is not "
                   "waiting on CI. A stale claim outlives the watcher that justified it.",
            clears_when=f"fleet declare --instant {child} --phase done",
            clears_who="this worker")
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_cli -v -k complete`
Expected: PASS, including every pre-existing `complete` case

- [ ] **Step 5: Commit**

```bash
git add fleet/src/fleet/cli.py fleet/tests/test_cli.py
git commit -m "complete: refuse to rename out from under this instant's own pointers"
```

---

### Task 8: `fleet.layout` seeds a compliant register header

**Files:**
- Modify: `fleet/src/fleet/layout.py:166-176` (`_seed`)
- Test: `fleet/tests/test_layout.py`

**Interfaces:**
- Produces: seeded registers carrying `Updated: <YYYY-MM-DD>` and `Status: DURABLE`.

- [ ] **Step 1: Write the failing test**

```python
    def test_seeded_registers_satisfy_the_header_rule_they_are_reviewed_against(self):
        """13 of one instant's 27 workspace-review findings were this header. The template a worker is
        given must pass the checklist that worker is held to (RCF-11)."""
        bootstrap(self.instant, name=self.name)
        for register in ("DECISIONS.md", "ISSUES.md", "ASSUMPTIONS.md", "RUNBOOK.md"):
            text = (self.instant / register).read_text()
            self.assertRegex(text, r"Updated: \d{4}-\d{2}-\d{2}", register)
            self.assertIn("Status: DURABLE", text, register)
            self.assertNotIn("seeded by fleet.layout", text, register)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_layout -v -k header_rule`
Expected: FAIL — `Status: seeded by fleet.layout (spec-version 1)`

- [ ] **Step 3: Implement the minimal code**

```python
def _seed(entry: str, name: InstantName, today: str = "") -> str:
    """A minimal document carrying the two header fields every consumer of these files reads.

    The header must satisfy the maintain-workspace rule the workspace reviewer enforces, because the
    template a worker is handed is the template that worker is graded on: seeding `Status: seeded by
    fleet.layout` made every instant fail its own first review on a line no worker wrote (`RCF-11`).
    Recognition is on the heading TEXT alone (`seed_headings`), so the header body is free to change.
    """
    stamp = today or time.strftime("%Y-%m-%d", time.gmtime())
    return (
        "".join(f"# {heading}\n" for heading in seed_headings(entry, name))
        + f"\nUpdated: {stamp}\n"
        "Status: DURABLE\n\n"
        f"{_TEMPLATES.get(entry, '')}"
    )
```

Add `import time` at the top of `layout.py`.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_layout -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fleet/src/fleet/layout.py fleet/tests/test_layout.py
git commit -m "layout: seed the register header the workspace reviewer enforces"
```

---

### Task 9: reconcile re-observes the watcher and flags a stale wait

**Files:**
- Modify: `fleet/src/fleet/session.py` (`Declarations.set_phase` records `at`), `fleet/src/fleet/reconcile.py:355-356`
- Test: `fleet/tests/test_reconcile.py`

**Interfaces:**
- Consumes: `Sessions.watchers(pane_text)` — note `_live_state` already receives pane **text**, so it drops straight in.
- Produces: four distinguishable `awaiting-ci` notes, and `Declarations.declared_at()` returning `None` when the declaration predates this change.

- [ ] **Step 1: Write the failing test**

```python
    def test_awaiting_ci_distinguishes_observed_attested_and_absent_watchers(self):
        """working-as-a-dispatched-instant already warns that `fleet board` renders an attested claim
        identically to an observed one, and names i45 as the owner. This is i45."""
        self.assertIn("watcher observed",
                      self.note(phase="awaiting-ci", pane="... 1 monitor ... esc to interrupt"))
        self.assertIn("ATTESTED, not observable",
                      self.note(phase="awaiting-ci", pane="no status line", attested="cron every 10m"))
        self.assertIn("NO WATCHER OBSERVABLE",
                      self.note(phase="awaiting-ci", pane="no status line"))

    def test_a_wait_older_than_the_threshold_is_flagged_stale(self):
        note = self.note(phase="awaiting-ci", pane="... 1 monitor ...",
                         declared_at="2026-09-07T15:00:00Z", now="2026-09-07T21:00:00Z")
        self.assertIn("STALE-WAIT", note)

    def test_a_declaration_with_no_timestamp_is_never_stale(self):
        """Every declaration written before this change. Absence is NOT MEASURED."""
        note = self.note(phase="awaiting-ci", pane="... 1 monitor ...", declared_at=None,
                         now="2026-09-07T21:00:00Z")
        self.assertNotIn("STALE-WAIT", note)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_reconcile -v -k watcher`
Expected: FAIL — the note is the constant `declared awaiting-ci; not consuming attention`

- [ ] **Step 3: Implement the minimal code**

In `session.py`, have `set_phase` also stamp `at`, and add the reader:

```python
    def declared_at(self):
        """When the phase was declared, or None for a declaration written before this field existed.
        None is NOT MEASURED: no age can be computed, so no staleness may be claimed."""
        return self._read().get("at")
```

In `reconcile.py`, replace the `awaiting-ci` branch of `_live_state`:

```python
    elif phase == PHASE_AWAITING_CI:
        state, note = AWAITING_CI, _awaiting_note(pane, sessions, instant, stale_after_s)
```

and add:

```python
#: 4 h. The slowest required pair in the source effort is 3 h 20 m, so a shorter threshold would flag
#: every healthy wait and a flag that fires on correct work gets ignored.
STALE_WAIT_S = 4 * 60 * 60


def _awaiting_note(pane, sessions, instant, stale_after_s=STALE_WAIT_S) -> str:
    """What the board says about a worker that claims to be waiting on CI.

    The declaration is a claim made at ONE moment; nothing re-reads it. A Monitor that emitted zero
    events for 7.7 h and a self-matching wait shell that outlived its job both rendered here as a
    healthy wait, and the cost was three operator `status?` pings in one session.
    """
    observed = sessions.watchers(pane)
    attested = Declarations(instant).watchers()
    if observed:
        note = f"declared awaiting-ci; watcher observed ({observed})"
    elif attested:
        note = f"declared awaiting-ci; watcher ATTESTED, not observable: {attested}"
    else:
        note = "declared awaiting-ci; NO WATCHER OBSERVABLE on the pane"
    age = _declared_age_s(instant)
    if age is not None and age > stale_after_s:
        note += f"; STALE-WAIT (declared {age // 3600}h{age % 3600 // 60:02d}m ago)"
    return note
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest tests.test_reconcile -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fleet/src/fleet/session.py fleet/src/fleet/reconcile.py fleet/tests/test_reconcile.py
git commit -m "reconcile: re-observe the watcher and flag a stale awaiting-ci (i45)"
```

---

### Task 10: the IT section for the round-to-head binding

**Files:**
- Create: `fleet/it/S/run-S.sh`
- Modify: `fleet/it/run-all.sh` (add §S to the roster)

- [ ] **Step 1: Write the IT section**

```bash
#!/usr/bin/env bash
# §S — a review round is bound to the code it reviewed, end to end against real git repos.
# S1 review at HEAD, then propose done          -> 0
# S2 commit after the round, then propose done  -> 4, guard review-head
# S3 review again at the new head, propose done -> 0
# S4 a ledger with no heads (legacy)            -> 0, NOT MEASURED
set -euo pipefail
. "$(dirname "$0")/../lib.sh"
it_begin S "review rounds bind to the head they reviewed"

slot="$(it_slot_with_repo gluten-internal)"
instant="$(it_worker_instant --lineage-base "gluten-internal=$(it_head "$slot/gluten-internal")")"

it_case S1 "propose done is admitted at the reviewed head" <<'EOF'
fleet review --instant "$instant" --scope all --verdict READY \
  --finding "RV-1:Minor:applied:SPEC.md:reviewed here:none"
fleet propose --instant "$instant" --milestone m1 --status done --evidence evidence/INDEX.md
EOF
it_expect_rc 0

it_case S2 "a commit after the round refuses the claim" <<'EOF'
git -C "$slot/gluten-internal" commit --allow-empty -qm "post-review fix"
fleet propose --instant "$instant" --milestone m1 --status done --evidence evidence/INDEX.md
EOF
it_expect_rc 4
it_expect_stderr "review-head"

it_case S3 "reviewing the new head clears it" <<'EOF'
fleet review --instant "$instant" --scope code --verdict READY \
  --finding "RV-2:Minor:applied:SPEC.md:re-reviewed at the new head:none"
fleet propose --instant "$instant" --milestone m1 --status done --evidence evidence/INDEX.md
EOF
it_expect_rc 0

it_end
```

- [ ] **Step 2: Run it**

Run: `cd fleet/it && IT_RESULTS=/tmp/it-S.tsv bash S/run-S.sh`
Expected: 3 cases pass

- [ ] **Step 3: Add §S to the gate roster**

Add `S` to the section list in `fleet/it/run-all.sh`, in alphabetical position.

- [ ] **Step 4: Run the full unit suite**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest discover -s tests -q`
Expected: PASS, 864+ tests

- [ ] **Step 5: Commit**

```bash
git add fleet/it/S/run-S.sh fleet/it/run-all.sh
git commit -m "it: §S proves the round-to-head binding across a real commit"
```

---

## Phase 2 — Lane B, the skills

### Task 11: resolve the eval-harness prerequisite

**Files:**
- Read: `CLAUDE.md`, `evals/README.md` (absent in this checkout)

The repo `CLAUDE.md` requires adversarial pressure testing and before/after eval results for skill-content
changes. `evals/` is not cloned here. This task is a decision, not code.

- [ ] **Step 1: Confirm the harness is absent**

Run: `ls evals 2>&1`
Expected: no such directory

- [ ] **Step 2: Put the fork to the operator**

Three options, with the recommendation first:

1. **Clone `superpowers-evals` into `evals/` and run before/after on the four changed skills.** Highest
   confidence, and the changes in Task 12–14 are behaviour-shaping text of exactly the kind
   `CLAUDE.md` names.
2. **Ship the additive changes only** — the close-out contract, the scratch rule, the watcher recipe —
   and hold the three edits that *replace* tuned text (the SDD waiting rule, the fan-out mandate, the
   reviewing-workspace prose home) until the harness exists.
3. **Ship all of it against the transcript evidence alone**, recording in each skill's commit which
   measured failure it answers.

- [ ] **Step 3: Record the answer**

Append the decision and its reason to the spec's "Testing" section, then proceed to Task 12.

---

### Task 12: `working-as-a-dispatched-instant` — close-out, scratch, watchers

**Files:**
- Modify: `skills/working-as-a-dispatched-instant/SKILL.md`

**Interfaces:**
- Produces: prose that mirrors Task 7's gate exactly. If the gate refuses it, the skill must already have said not to do it.

- [ ] **Step 1: Add the close-out contract after the "Finish" section**

```markdown
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
```

- [ ] **Step 2: Add the watcher recipe beside the awaiting-ci gate**

```markdown
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
```

- [ ] **Step 3: Verify the frontmatter is untouched and the graphs still render**

There is no skill linter in this repo; `superpowers:writing-skills` governs skill edits per `CLAUDE.md`.

```bash
head -5 skills/working-as-a-dispatched-instant/SKILL.md   # name: and description: unchanged
bash tests/writing-skills/test-render-graphs.sh
```
Expected: frontmatter identical to `git show HEAD:skills/working-as-a-dispatched-instant/SKILL.md | head -5`; render test PASS

- [ ] **Step 4: Commit**

```bash
git add skills/working-as-a-dispatched-instant/SKILL.md
git commit -m "dispatched-instant: close-out contract, scratch rule, and two measured watcher traps"
```

---

### Task 13: `subagent-driven-development` — waiting, monitors, inline execution

**Files:**
- Modify: `skills/subagent-driven-development/SKILL.md:236-245`

- [ ] **Step 1: Replace the "Waiting on dispatched subagents" paragraph**

Replace lines 236-245 with:

```markdown
**Waiting on dispatched subagents:** while you have local work — ledger updates, packaging the next
review, reading reports — keep working; child results arrive on their own. When you are genuinely idle,
**end the turn.** The completion notification re-invokes you, and a turn that has ended is one an
operator can interrupt.

Do not sleep-poll. Measured: a controller that followed a "wait in bounded stretches" rule literally ran
37 sleep loops totalling 286 minutes, of which 29 minutes were pure added latency on the critical path —
each child's completion notification sat in the queue until the current loop returned. The same session
was told verbatim by its harness "keep working, do not poll or sleep" and polled anyway for 3 h 20 m,
during which it was indistinguishable from a hung session and delayed its operator's message by
5.8 minutes.

If a loop is genuinely unavoidable, give it an **exit condition** — a report file, an agent state — never
a fixed `seq`. A loop that cannot end early is a timer, not a wait.

**An implementer never ends its turn on a `Monitor`.** This is the single most expensive defect measured
in the source wave: an implementer started a build, was blocked from `sleep`, armed a `Monitor` instead,
and ended its turn waiting for it. The build finished in 10 minutes; the event reached the parent's queue
and was never delivered; the parent wrote "waiting on Task 4" twice and stopped. **268 minutes**, ended
by an operator saying "I saw u are idle". Run the build in the foreground with a long timeout, or have
the parent watch the artefact — never hand a child a wake-up the parent cannot receive.
```

- [ ] **Step 2: Add the inline-execution allowance to the Task Loop section**

```markdown
**Inline execution is first-class on a single sequential slot.** Fan-out buys parallelism, and there is
none to buy when every task builds in the same leased workspace: a fresh implementer per task would
re-derive slot state each time for no overlap. Three workers in one wave reached that conclusion
independently and the coordinator ratified it twice, once retroactively. Execute the steps inline and
keep the review loop — the independent reviewer is what the method is actually for. Record the choice in
`DECISIONS.md` so it reads as a decision and not a shortcut.
```

- [ ] **Step 3: Verify the frontmatter is untouched and the graphs still render**

```bash
head -5 skills/subagent-driven-development/SKILL.md
bash tests/writing-skills/test-render-graphs.sh
```
Expected: frontmatter unchanged; render test PASS

- [ ] **Step 4: Commit**

```bash
git add skills/subagent-driven-development/SKILL.md
git commit -m "sdd: end the turn instead of polling; an implementer never waits on a Monitor"
```

---

### Task 14: `reviewing-workspace` and `requesting-code-review`

**Files:**
- Modify: `skills/reviewing-workspace/SKILL.md` (the "REVIEW.md Discipline" section)
- Modify: `skills/requesting-code-review/SKILL.md`

- [ ] **Step 1: Fix the prose-home contradiction in `reviewing-workspace`**

Add to "REVIEW.md Discipline":

```markdown
**`REVIEW.md` is a generated view, and `fleet review` rewrites it in full.** Findings go into the ledger
through `fleet review --finding`; reasoning goes into `REVIEW-NARRATIVE.md`, which nothing regenerates.
Two workers in one wave wrote their round narrative into `REVIEW.md`, lost it to the next render — about
15 findings in one case, 119 lines in the other — and both then invented `REVIEW-NARRATIVE.md`
independently. The file's own banner warns about this, and it only exists after the first render, so it
cannot warn the person who needs it.

A finding against a file this instant does not own — a coordinator-authored `CHARTER.md`, a sibling's
suite — is recorded `routed` with an owner in its `action`, never `open`. An `open` blocking finding
refuses this worker's gate, and one worker cleared such a gate by editing the coordinator's charter.
```

- [ ] **Step 2: Fix the round's timing**

In "When to Use", make the pre-complete gate the default rather than an option:

```markdown
Run the round **before** `fleet complete`, not after. The skill's own gate is pre-complete, and in the
source wave no worker ran it unprompted: two were told to by an operator, and one ran it 7 minutes after
completing, which is 7 minutes in which the answer could not change anything.
```

- [ ] **Step 3: Add the re-push rule to `requesting-code-review`**

```markdown
**A comment-only finding does not earn a new CI wave.** When the branch already has a labeled run in
flight, applying a docstring or comment fix means a new head, which cancels that run and starts the clock
again. Measured: one worker paid 24 CI-minutes for three comment nits, and another shipped two
comment-only commits into a live wave. Route them as riders for the next restack, and say so in the
review record. Findings that change behaviour are a different question and are worth the wave.
```

- [ ] **Step 4: Verify both**

`reviewing-workspace` carries a `dot` pipeline graph, so the render test is load-bearing here.

```bash
head -5 skills/reviewing-workspace/SKILL.md
head -5 skills/requesting-code-review/SKILL.md
bash tests/writing-skills/test-render-graphs.sh
```
Expected: both frontmatters unchanged; render test PASS

- [ ] **Step 5: Commit**

```bash
git add skills/reviewing-workspace/SKILL.md skills/requesting-code-review/SKILL.md
git commit -m "review skills: narrative has a durable home; comment-only findings ride, never re-push"
```

---

## Phase 3 — Lane C, the profile

### Task 15: `ansi-gap-closure` seed and charter

**Files:**
- Modify: `operations/tasks/quantonOnSpark4V2/profiles/ansi-gap-closure/seed.txt`
- Modify: `operations/tasks/quantonOnSpark4V2/profiles/ansi-gap-closure/charter.md`

This lane is effort-local and ships without a release. It is not covered by the fleet test suite; its
verification is the next dispatched wave.

- [ ] **Step 1: Fix the native contradiction in `seed.txt`**

The `=== POSITION YOUR WORKSPACE ===` block ends with "If you touch native code … Rebuild them after
repositioning." Every charter in this effort says the opposite (I-52), and `base-check` then warns
falsely. Replace with:

```
If you touch native code: your charter's slot note is authoritative about whether this slot can rebuild.
Several cannot (I-52), and there the charter names a frozen pair to copy and md5-verify instead. Do not
rebuild because this seed said so; do what §1's slot note says.
```

- [ ] **Step 2: Trim the mandated skill list in `seed.txt` and `charter.md` §4**

`test-driven-development`, `executing-plans` and `verification-before-completion` were loaded by no
worker across five instants, and every practice they carry was followed anyway because the charter and
the plan demanded it. Keep them named as the standard the charter holds you to; stop ordering them
loaded.

- [ ] **Step 3: Add the pre-push checklist to `charter.md` §7**

```markdown
### Before you push

- **Grep the test tree for any message string you delete.** A sibling's suite may pin it BY NAME. One
  worker deleted a deny whose message `IntervalArithmeticFallbackPinSuite` pinned; the red arrived
  2 h 49 m later and cost a third heavy wave for a 4.5-minute fix.
- **A push cancels the in-flight runs at the old head, and that is fine.** Only the FINAL head is
  graded. One worker held a finished push back for 125 minutes waiting for the previous head to finish
  grading a baseline no acceptance criterion required.
- **Converge the review before you push, not while you wait.** Reviewing after the push cost a second
  full wave in three instants. In the fourth, the late review found six suite pins that would have
  reddened the ANSI dim — so the review was already earning its place, just too late to save the wave.
- **Let the PR settle before labelling, then read the guard's own line.** A `ci-heavy` label applied
  8 seconds after `gh pr create` produced four heavy workflows that concluded `success` having run
  NOTHING. `gh run view <id> --log | grep "FINAL DECISION"` must say `is_top=true`.
```

- [ ] **Step 4: Add the CI latency profile and the runbook stub to `charter.md` §5**

```markdown
**What the wait actually costs.** A labeled heavy wave is about 3 h 20 m end to end, and the pair that
sets it is x86 `spark-test-spark41`. Plan the wait; one worker estimated "roughly 90 minutes" for a wait
that took 197. The ANSI dim lands around 1 h 50 m and ARM around 30 m.

**Recipes every instant on this profile has re-derived.** Private hardlinked `.m2`; `-Dtest=none
-DfailIfNoTests=false` on every single-suite run; `SPARK_ANSI_SQL_MODE=false` literally in the
environment for the plain dim, or the ANSI dim's `-DargLine`, without which a local run reds wholesale
and reads exactly like a regression; the CI artifact is `spark-test-backends-velox-ansi-report`, not the
job name; `grade.py` refuses a short sha; `required-green.txt` lives in the coordinator's `evidence/`;
clean `shims/`, `shims/common` and `shims/spark3x` before EVERY profile switch, in either direction.
```

- [ ] **Step 5: Point at the prior instant's registers, not only its SPEC**

In the §1 authoring guidance, where a charter says "read the predecessor's records first", name
`DECISIONS.md` and `evidence/…/GRADE.md` explicitly. Two of one worker's four escalated questions were
answered verbatim in a sibling's `DEC-5` and `GRADE.md`, in the same slot, unopened.

- [ ] **Step 6: Move the charter review before dispatch**

Add to the profile's authoring notes: the coordinator's charter-review round runs BEFORE the seed is
delivered. In the source wave three workers received corrections 9 to 29 minutes after their seed, two
of them late because delivery was gated on an idle pane. All three happened to be already satisfied; had
one changed scope, the whole red/green cycle would have been redone.

- [ ] **Step 7: Commit**

```bash
cd /home/ubuntu/davis_root/operations
git add tasks/quantonOnSpark4V2/profiles/ansi-gap-closure/
git commit -m "ansi-gap-closure: pre-push checklist, real CI latencies, runbook stub, native fix"
```

---

## Phase 4 — release

### Task 16: cut and verify the fleet release

**Files:**
- Modify: `fleet/CHANGELOG.md`, version via `scripts/bump-version.sh`

- [ ] **Step 1: Run the full gate**

Run: `cd fleet && PYTHONPATH=src python3 -m unittest discover -s tests -q`
Expected: PASS, 870+ tests

- [ ] **Step 2: Run the IT roster including §S**

Run: `cd fleet/it && bash run-all.sh`
Expected: every section green, §S included

- [ ] **Step 3: Follow `superpowers:releasing-fleet`**

The four-verb chain, in order. Do not hand-roll the version bump.

- [ ] **Step 4: Confirm the deployed plugin carries the change**

The running plugin is served from `fleet-releases/current`, not from this branch. Verify
`fleet-releases/current/skills/working-as-a-dispatched-instant/SKILL.md` carries the close-out contract
after promotion, or the workers keep reading the old text.

---

## Self-Review

**Spec coverage.** A1 → Tasks 1-5. A2 → Task 7. A3 → Task 6. A4 → Task 8. A5 → Task 9. Lane B's five
skill rows → Tasks 12-14, gated by Task 11. Lane C's six rows → Task 15. Testing section → Tasks 10, 16.

**One spec requirement has no task, deliberately:** the spec's success criteria are measured on the next
wave, not by this plan.

**Type consistency.** `Workspace.heads(slot_path, repos) -> dict` is defined in Task 1 and consumed under
that exact name in Tasks 3, 4 and 5. `Review.add_round(scope, verdict, findings, heads=None)` is defined
in Task 2 and called in Task 3. `_reviewed_heads(ctx, child)` is defined in Task 3 and reused in Tasks 4
and 5. `Round.heads` is a `dict` everywhere. `GUARD_REVIEW_HEAD` and `GUARD_COMPLETE_POINTERS` are each
defined once.

**Known gap carried deliberately.** Task 4's gate fires at the claim of done, which is after the wave has
been spent. Nothing in `fleet` sees the push itself, so this is the earliest observable moment; the
prevention lives in Lane B and Lane C text. Stated in the spec rather than papered over.
