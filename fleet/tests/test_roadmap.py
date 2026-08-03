"""The milestone registry — one writer and derived readiness.

This is UC-3's half of the lifecycle: *"worker does individual dev work, self reviews and talks to the
coordinator about updating roadmap status."* Three properties carry the weight and each is an incident:

1. **Single writer.** `propose` is the worker's verb and it never touches `roadmap.json`; `apply` is the
   coordinator's and it is the only writer. *"I'll let the worker update the shared registry to save a
   step"* is a STOP-table row, and a dispatch profile once told **every** worker to update the canonical
   registry and survived a whole effort.
2. **Readiness is derived, and every non-ready milestone names its blocker.** *"READY = disposition
   assigned, ACs written, and its dependencies have LANDED."* A dep that merely exists is not a dep that
   landed, and a worker sitting "done" for hours is the coordinator's failure to notice, not the
   operator's.
3. **The deferred-owner registry (`FI-7`).** Eight real items were *"reassigned by name to the next
   effort's S-1 instant"* — an instant that exists nowhere on the box. A lint over that population
   either goes permanently RED (a fifth unclearable alarm) or passes vacuously, so a reassignment names
   either an existing register **or** a declared future owner with a creation condition; an unclaimed
   deferred owner is *reported with its clearing actor*, and claiming it clears the report.
"""
import json
import pathlib
import shutil
import tempfile
import unittest

from fleet.errors import BadInput
from fleet.roadmap import (ATTENTION, INFO, LANDED, NOT_READY, PENDING_PROPOSAL,
                           POPULATION, STATUSES, TERMINAL, Milestone, Proposal,
                           Roadmap)

COORD = "00000000-07300312-inflight-append-fleetInfraRebuild"
WORKER = "00000000-07300400-inflight-append-workerOne"
NEXT = "00000000-07310800-inflight-append-nextEffortScope01"

#: Every status that is NOT landed, spelled out. Deliberately hand-listed rather than derived from
#: `LANDED`: a list computed from the constant under test passes vacuously the moment the constant is the
#: thing that is wrong (M-51 injected as `LANDED = ("done", "running")`). The next assertion below keeps
#: the hand-list honest against `STATUSES`, so it cannot silently narrow either.
NOT_LANDED = ("blocked", "ready", "running", "awaiting-ci", "dropped")


def ms(mid, status="blocked", deps=(), evidence=(), owner=None):
    return Milestone(id=mid, title=f"milestone {mid}", status=status,
                     deps=list(deps), evidence=list(evidence), owner=owner)


class RoadmapCase(unittest.TestCase):
    def setUp(self):
        self.tasks = pathlib.Path(tempfile.mkdtemp())
        self.instant = self.tasks / COORD
        self.instant.mkdir()
        self.worker = self.tasks / WORKER
        self.worker.mkdir()
        self.rm = Roadmap(self.instant)

    def fresh(self, name="00000000-07300500-inflight-append-otherEffort"):
        """A second roadmap in its own instant, for cases that need two populations."""
        inst = self.tasks / name
        inst.mkdir()
        return Roadmap(inst)

    def rows(self, kind, roadmap=None):
        return [r for r in (roadmap or self.rm).report() if r.kind == kind]


class TestReadiness(RoadmapCase):
    def test_ready_requires_deps_to_have_LANDED_not_merely_exist(self):
        # "READY = disposition assigned, ACs written, and its dependencies have LANDED"; anything else is
        # BLOCKED with the blocker named. A dep that is `running` — or `awaiting-ci`, which is the case
        # this effort actually hit — is present in the roadmap and has not landed.
        self.assertEqual(set(NOT_LANDED) | set(LANDED), set(STATUSES),
                         "the hand-listed non-landed statuses no longer cover STATUSES")
        self.assertEqual(tuple(LANDED), ("done",), "`done` is the only status that means LANDED")

        for i, status in enumerate(NOT_LANDED):
            with self.subTest(dep_status=status):
                rm = self.fresh(f"00000000-0730060{i}-inflight-append-depIs{status.replace('-', '')}")
                rm.add(ms("m1", status=status))
                rm.add(ms("m2", deps=["m1"]))
                self.assertNotIn("m2", [m.id for m in rm.ready()],
                                 f"a dep with status={status} is not landed and cannot make m2 ready")
                blocked = {r.subject: r for r in rm.report() if r.kind == NOT_READY}
                self.assertIn("m1", blocked["m2"].detail, "the blocker must be named")
                self.assertIn(status, blocked["m2"].detail)

        # The same roadmap, once the dep actually lands through the coordinator's single writer.
        rm = self.fresh("00000000-07300610-inflight-append-depLands")
        rm.add(ms("m1", status="running"))
        rm.add(ms("m2", deps=["m1"]))
        rm.apply(rm.propose(self.worker, "m1", "done", ["evidence/02-acceptance/m1.log"]))
        self.assertEqual([m.id for m in rm.ready()], ["m2"])

    def test_ready_names_the_blocker_for_everything_not_ready(self):
        # A worker sitting "done" for hours is the coordinator's failure, not the operator's job to
        # notice: nothing is left off the report, and everything actionable names its clearing actor.
        self.rm.add(ms("landed", status="done", evidence=["evidence/x"]))
        self.rm.add(ms("inflight", status="running", owner=WORKER))
        self.rm.add(ms("waiting", status="awaiting-ci", owner=WORKER))
        self.rm.add(ms("downstream", deps=["inflight"]))
        self.rm.add(ms("phantom", deps=["nosuchMilestone"]))
        self.rm.add(ms("gone", status="dropped"))
        self.rm.add(ms("go", status="ready", deps=["landed"]))

        ready = {m.id for m in self.rm.ready()}
        self.assertEqual(ready, {"go"})
        reported = {r.subject: r for r in self.rows(NOT_READY)}
        for m in self.rm.milestones():
            with self.subTest(milestone=m.id):
                if m.id in ready:
                    self.assertNotIn(m.id, reported, "a ready milestone is not reported as blocked")
                    continue
                self.assertIn(m.id, reported, "every non-ready milestone carries a blocker")
                row = reported[m.id]
                self.assertTrue(row.detail.strip(), "an empty blocker names nothing")
                #: `FI-2` changed this rule, and the change is a NARROWING of what shouts, not a
                #: weakening of what is checked. It used to be "terminal is INFO, everything else is
                #: ATTENTION", which made the commonest healthy state in the system — a stacked
                #: milestone waiting for its predecessor — an alarm. Now the severity follows the
                #: REASON: only a dep that is not in the roadmap at all is actionable, because only that
                #: one can never land on its own.
                if m.status in TERMINAL:
                    self.assertEqual(row.severity, INFO, "finished work is information, not an alarm")
                elif "not in the roadmap" in row.detail:
                    self.assertEqual(row.severity, ATTENTION,
                                     "a dep that can never land must still be actionable")
                else:
                    self.assertEqual(row.severity, INFO,
                                     f"a normally-blocked milestone is shouting: {row.detail}")
                if m.status not in TERMINAL:
                    #: Asserted for EVERY non-terminal row regardless of severity — an info row that
                    #: names no way forward is as useless as an alarm that names none, and dropping this
                    #: with the severity change is exactly how a narrowing becomes a weakening.
                    self.assertTrue(row.clears_when, "the row states its clearing condition")
                    self.assertTrue(row.clears_who, "the row states its clearing ACTOR (RI-31)")
        self.assertIn("nosuchMilestone", reported["phantom"].detail,
                      "a dep that is not in the roadmap is named, never silently satisfied")
        self.assertIn(WORKER, reported["inflight"].clears_who,
                      "the actor is the owner who is holding it, when there is one")


class TestSingleWriter(RoadmapCase):
    def test_a_worker_proposes_and_the_proposal_does_not_change_the_roadmap(self):
        # THE single-writer property. "I'll let the worker update the shared registry to save a step" is a
        # STOP-table row, and a dispatch profile once told every worker to update the canonical registry
        # and survived a whole effort.
        self.rm.add(ms("m1", status="running", owner=WORKER))
        before_milestones = self.rm.milestones()
        before_bytes = self.rm.path.read_bytes()
        before_mtime = self.rm.path.stat().st_mtime_ns

        proposal = self.rm.propose(self.worker, "m1", "done", ["evidence/02-acceptance/ci.log"])

        self.assertEqual(self.rm.milestones(), before_milestones)
        self.assertEqual(self.rm.path.read_bytes(), before_bytes)
        self.assertEqual(self.rm.path.stat().st_mtime_ns, before_mtime,
                         "propose must not even rewrite roadmap.json with identical bytes")
        self.assertEqual(Roadmap(self.instant).milestones(), before_milestones)

        # The proposal is durable, attributed, and visible to the coordinator as work awaiting IT.
        pending = self.rm.proposals()
        self.assertEqual([(p.milestone, p.status, p.instant) for p in pending],
                         [("m1", "done", str(self.worker))])
        self.assertEqual(pending, Roadmap(self.instant).proposals())
        self.assertTrue(proposal.at, "a proposal is stamped, so a stalled one is measurable")
        row = self.rows(PENDING_PROPOSAL)
        self.assertEqual([r.subject for r in row], ["m1"])
        self.assertIn(str(self.worker), row[0].detail)
        self.assertEqual(row[0].severity, ATTENTION)
        self.assertIn("coordinator", row[0].clears_who)

    def test_only_apply_mutates_the_roadmap(self):
        self.rm.add(ms("m1", status="running", owner=WORKER))
        proposal = self.rm.propose(self.worker, "m1", "done", ["evidence/02-acceptance/ci.log"])
        applied = self.rm.apply(proposal)

        self.assertEqual(applied.status, "done")
        self.assertEqual(Roadmap(self.instant).milestone("m1").status, "done")
        self.assertIn("evidence/02-acceptance/ci.log", Roadmap(self.instant).milestone("m1").evidence,
                      "the evidence that justified the status change lands with it")
        self.assertEqual(self.rm.proposals(), [],
                         "an applied proposal stops being pending, so it cannot be applied twice")
        self.assertEqual(self.rows(PENDING_PROPOSAL), [])

    def test_apply_refuses_a_proposal_whose_evidence_list_is_empty(self):
        # A status change with no evidence is the claim without the artifact. The gate lives on the
        # WRITER, so a hand-built proposal cannot walk around it — which is why this case constructs one
        # directly instead of going through `propose`.
        self.rm.add(ms("m1", status="running"))
        hand_built = Proposal(instant=str(self.worker), milestone="m1", status="done",
                              evidence=[], at="2026-07-30T04:00:00Z")
        with self.assertRaises(BadInput):
            self.rm.apply(hand_built)
        self.assertEqual(Roadmap(self.instant).milestone("m1").status, "running",
                         "a refused apply changes nothing")
        with self.assertRaises(BadInput):
            self.rm.propose(self.worker, "m1", "done", [])
        self.assertEqual(self.rm.proposals(), [])


#: `TestDeferredOwners` lived here — five tests over `reassign`, `deferred_owners`,
#: `unclaimed_deferred_owners` and `claim_deferred_owner`. The whole concept was REMOVED (`SD-5`), so the
#: tests went with it rather than being adapted: a test for a deleted feature is the clearest possible
#: dead surface, and this corpus already learned that lesson twice (`SI-19`: a correct, tested, dead
#: public API reads exactly like a working feature).
#:
#: What replaced it is not another test here but a different model — an item that outlives its effort
#: becomes a documented issue in the workspace plus a MILESTONE, which `TestReadiness` already covers.
#: `FI-7`'s failure (a reassignment naming an instant that exists nowhere) is now unrepresentable rather
#: than detected, so there is nothing left to assert about it.

class TestPopulation(RoadmapCase):
    def test_roadmap_reports_the_population_it_examined(self):
        # FR2-8.3 / OBS-49: a checker states what it looked at, so a scope that narrows cannot read as a
        # pass — and a legitimately empty population is REPORTED, never RED and never silent.
        self.rm.add(ms("m1", status="done", evidence=["evidence/x"]))
        self.rm.add(ms("m2", deps=["m1"]))
        self.rm.add(ms("m3", status="running"))
        self.rm.propose(self.worker, "m3", "awaiting-ci", ["evidence/y"])

        report = self.rm.report()
        population = [r for r in report if r.kind == POPULATION]
        self.assertEqual(len(population), 1)
        self.assertIs(report[-1], population[0], "the population row is the last word of the report")
        self.assertEqual(population[0].severity, INFO)
        detail = population[0].detail
        #: The counted population is milestones and proposals. It used to also count deferred owners and
        #: reassignments; both concepts were removed (`SD-5`), and a population row that still counted them
        #: would report a dimension that cannot be non-zero — which is the same false-completeness this
        #: assertion exists to catch, pointed the other way.
        for token in ("3 milestone", "1 pending proposal"):
            self.assertIn(token, detail)
        for gone in ("deferred owner", "reassignment"):
            self.assertNotIn(gone, detail,
                             f"the population still counts {gone!r}, a dimension that no longer exists")

        empty = [r for r in self.fresh().report() if r.kind == POPULATION]
        self.assertEqual(len(empty), 1)
        self.assertIn("0 milestone", empty[0].detail)


if __name__ == "__main__":
    unittest.main()


class TestProposalCitesTheCurrentFolder(unittest.TestCase):
    """`SI-40`. A pending-proposal row must name where the proposer is NOW.

    A worker's completion signal is renaming its own folder, so the `done` proposals -- the ones a
    coordinator most needs to act on -- are exactly the ones whose recorded path has gone stale.
    """

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.coord = self.tmp / "00000000-07310348-inflight-append-coord"
        (self.coord / ".fleet").mkdir(parents=True)
        self.worker = self.tmp / "00000000-07310400-inflight-append-w"
        (self.worker / ".fleet").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _row(self):
        r = Roadmap(self.coord)
        r.add(Milestone(id="m1", title="a milestone", status="blocked", deps=[], evidence=[]))
        r.propose(self.worker, "m1", "done", ["evidence/INDEX.md"])
        return [row for row in r.report() if row.kind == PENDING_PROPOSAL][0]

    def test_the_row_follows_the_workers_rename(self):
        renamed = self.tmp / "00000000-07310400-complete-append-w"
        self.worker.rename(renamed)
        detail = self._row().detail
        self.assertIn("-complete-append-w", detail,
                      "the row must cite the folder that exists, not the one recorded at propose time")
        self.assertNotIn("-inflight-append-w ", detail + " ")

    def test_an_unrenamed_proposer_is_unchanged(self):
        self.assertIn("-inflight-append-w", self._row().detail,
                      "resolution must be a no-op when nothing moved")

    def test_a_vanished_proposer_is_named_AND_flagged(self):
        shutil.rmtree(self.worker)
        detail = self._row().detail
        self.assertIn("-inflight-append-w", detail, "the recorded path is still shown")
        self.assertIn("no longer on disk", detail,
                      "a resolver that silently substitutes its input is worse than one that admits it failed")


class TestProposalNote(unittest.TestCase):
    """`I-2` — a worker can attach one line of narrative to a proposal.

    Reported by a real worker: `fleet propose --note …` exited 2, `'--note' is not a flag propose
    declares`, and nothing was written. Their workaround was to write a file and cite it as `--evidence`,
    which works and is recorded in their RUNBOOK — but it makes every one-line summary a separate
    artifact, and evidence paths were the ONLY narrative channel a worker had.

    `--note` matches what the rest of the surface already does: `abort --reason`, `park --question`,
    `milestone --title`. It is one line ABOUT the proposal, and it never replaces evidence — a status
    claim still stands or falls on the paths it cites.
    """

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.road = Roadmap(self.tmp)
        self.road.add(Milestone(id="M1", title="m", status="ready", deps=[], evidence=[]))
        self.ev = self.tmp / "e.txt"
        self.ev.write_text("x")

    def test_a_proposal_carries_its_note_through_the_round_trip(self):
        self.road.propose(self.tmp, "M1", "done", [str(self.ev)], note="the split landed; see §3")
        [back] = self.road.proposals()
        self.assertEqual(back.note, "the split landed; see §3",
                         "the note did not survive being written and read back")

    def test_a_proposal_without_a_note_is_still_valid(self):
        """Every proposal written before this field existed has no `note` key. Loading one must not
        raise — a new optional field that breaks the existing inbox is not an optional field."""
        self.road.propose(self.tmp, "M1", "done", [str(self.ev)])
        [back] = self.road.proposals()
        self.assertEqual(back.note, "")

    def test_an_old_proposal_on_disk_loads_without_the_key(self):
        """The migration case, asserted against a file rather than against a model: a `proposals.json`
        written by the previous version has no `note` key at all."""
        import json
        self.road.propose(self.tmp, "M1", "done", [str(self.ev)])
        data = json.loads(self.road.proposals_path.read_text())
        for entry in data["pending"]:
            entry.pop("note", None)
        self.road.proposals_path.write_text(json.dumps(data))
        [back] = self.road.proposals()
        self.assertEqual(back.note, "")
        self.assertEqual(back.milestone, "M1")

    def test_a_note_does_not_substitute_for_evidence(self):
        """A note is prose and prose is not proof. `_check_evidence` must still refuse an empty
        evidence list, or `--note` becomes the way to make an unevidenced claim."""
        with self.assertRaises(BadInput):
            self.road.propose(self.tmp, "M1", "done", [], note="trust me")

    def test_the_note_reaches_the_coordinators_inbox(self):
        """A note nobody reads is a note that does not exist.

        This is `FI-14`'s lesson applied to `I-2` before it can become the same defect: fleet already
        had one field it DETECTED and then dropped because nothing consumed it. Adding `--note` and not
        rendering it would have shipped a second. The pending-proposal row is the coordinator's only
        view of an unapplied proposal, so that is where the note has to appear.
        """
        self.road.propose(self.tmp, "M1", "done", [str(self.ev)], note="the split landed; see §3")
        rows = [r for r in self.road.report() if r.kind == PENDING_PROPOSAL]
        self.assertEqual(len(rows), 1)
        self.assertIn("the split landed; see §3", rows[0].detail)

    def test_a_proposal_without_a_note_renders_no_empty_quotes(self):
        """The absence has to be invisible, not rendered as `""`. Every proposal on disk today has no
        note, and a row that ends in empty quotes is noise on every existing inbox."""
        self.road.propose(self.tmp, "M1", "done", [str(self.ev)])
        [row] = [r for r in self.road.report() if r.kind == PENDING_PROPOSAL]
        self.assertNotIn('""', row.detail)
        self.assertNotIn("''", row.detail)
        self.assertIn("evidence item(s)", row.detail, "the row lost its normal content")


class TestNotReadySeverityReflectsWHY(RoadmapCase):
    """`FI-2` — a milestone merely waiting on its dependency was reported at `severity=attention`.

    A stacked roadmap produces that row constantly and it is the system working: `p1` waits on `s1`,
    `s1` is in progress, nobody needs to do anything. But `using-fleet` says *act on `violation`, report
    `info`*, which leaves `attention` in a third category the guidance does not cover — on the row type a
    healthy roadmap emits most often. An alarm that fires when nothing is wrong is one people learn to
    scroll past, and then the `not-ready` row that DOES matter scrolls past with it.

    `_blocker` already distinguishes the cases; `report()` derived severity from `m.status` alone and
    discarded that. The severity now comes from the reason:

      * deps exist and have not landed yet  -> INFO      (normal; waiting is the design)
      * a dep is NOT IN THE ROADMAP at all  -> ATTENTION (a typo'd dep never lands; the skill warns of
                                                          "a milestone that reads as permanently in
                                                          progress")
      * already in flight, held by somebody -> INFO      (somebody is on it)
      * terminal                            -> INFO      (already the case)
    """

    def rows_for(self, kind):
        return [r for r in self.rm.report() if r.kind == kind]

    def test_waiting_on_an_unlanded_dep_is_INFO(self):
        self.rm.add(Milestone(id="s1", title="the dep", status="running", deps=[], evidence=[]))
        self.rm.add(Milestone(id="p1", title="waits", status="ready", deps=["s1"], evidence=[]))
        [row] = [r for r in self.rows_for(NOT_READY) if r.subject == "p1"]
        self.assertEqual(row.severity, INFO,
                         "a milestone waiting on a dep that is progressing is reported as attention")
        self.assertIn("have not LANDED", row.detail, "the row stopped explaining itself")

    def test_a_dep_that_is_NOT_IN_THE_ROADMAP_is_still_ATTENTION(self):
        """The expensive direction, and the reason this is not a blanket downgrade. A typo'd dep can
        never land, so the milestone is permanently unready and nothing will ever clear it."""
        self.rm.add(Milestone(id="p1", title="waits", status="ready", deps=["s1-typo"], evidence=[]))
        [row] = [r for r in self.rows_for(NOT_READY) if r.subject == "p1"]
        self.assertEqual(row.severity, ATTENTION,
                         "a dep that is not in the roadmap at all was downgraded to info")
        self.assertIn("not in the roadmap", row.detail)

    def test_a_milestone_already_in_flight_is_INFO(self):
        self.rm.add(Milestone(id="p1", title="in flight", status="running", deps=[], evidence=[]))
        [row] = [r for r in self.rows_for(NOT_READY) if r.subject == "p1"]
        self.assertEqual(row.severity, INFO, "a milestone somebody is executing needs no attention")

    def test_a_healthy_stacked_roadmap_raises_NO_attention_at_all(self):
        """The whole point, stated as the property rather than per-row: three milestones stacked on each
        other, all legitimate, must produce no attention row anywhere."""
        self.rm.add(Milestone(id="s1", title="first", status="running", deps=[], evidence=[]))
        self.rm.add(Milestone(id="s2", title="second", status="ready", deps=["s1"], evidence=[]))
        self.rm.add(Milestone(id="s3", title="third", status="ready", deps=["s2"], evidence=[]))
        loud = [(r.kind, r.subject, r.severity) for r in self.rm.report() if r.severity == ATTENTION]
        self.assertEqual(loud, [], "a healthy stacked roadmap is shouting")


class TestRetiringASupersededMilestone(RoadmapCase):
    """`FI-10` — across 31 verbs there was no path to retire a milestone.

    A milestone raised early and then superseded by a re-plan cannot be removed from the population:
    `milestone` refuses an id already in the roadmap (*"refusing to shadow it"*) and `apply` refuses to
    invent a status without a worker's proposal — and a superseded milestone has no worker and never
    will. Both refusals are individually CORRECT, which is why this went unnoticed: nothing is broken,
    there is simply no door.

    The consequence is not cosmetic. Once its deps land, a superseded milestone is derived READY forever,
    and `roadmap --porcelain` prints `not-ready` rows but not ready ones — so it is a phantom dispatchable
    milestone that no report shows. `coordinating-instants` warns of the mirror case, a typo'd dep that
    "reads as permanently in progress"; this is the same failure from the other end.

    `retire` is the coordinator's own decision and can write exactly ONE status. A worker still cannot
    move the roadmap by any path, which is the invariant the two-party protocol exists for.
    """

    def test_a_superseded_milestone_can_be_retired_with_a_reason(self):
        self.rm.add(ms("p1", status="ready"))
        self.rm.retire("p1", reason="superseded by the s1 split; v1..v14 replace this layer")
        [back] = [m for m in self.rm.milestones() if m.id == "p1"]
        self.assertEqual(back.status, "dropped")
        self.assertIn("superseded by the s1 split", back.retired_reason)

    def test_a_retired_milestone_leaves_the_ready_population(self):
        """The whole point. A phantom READY milestone is dispatchable and invisible."""
        self.rm.add(ms("landed", status="done"))
        self.rm.add(ms("p1", status="ready", deps=["landed"]))
        self.assertIn("p1", {m.id for m in self.rm.ready()})
        self.rm.retire("p1", reason="superseded")
        self.assertNotIn("p1", {m.id for m in self.rm.ready()},
                         "a retired milestone is still dispatchable")

    def test_retiring_REQUIRES_a_reason(self):
        """A milestone that vanished from the population with no recorded why is a decision nobody can
        reconstruct — and `dropped` is indistinguishable from `done` to a reader who was not there."""
        self.rm.add(ms("p1", status="ready"))
        with self.assertRaises(BadInput):
            self.rm.retire("p1", reason="   ")

    def test_an_ALREADY_terminal_milestone_is_refused(self):
        """Retiring something finished would rewrite history — the exact thing `milestone`'s
        refuse-to-shadow protects, arriving through the new door."""
        self.rm.add(ms("done1", status="done"))
        with self.assertRaises(BadInput):
            self.rm.retire("done1", reason="tidying up")

    def test_an_unknown_milestone_is_refused_by_name(self):
        with self.assertRaises(BadInput) as caught:
            self.rm.retire("nosuch", reason="whatever")
        self.assertIn("nosuch", str(caught.exception))

    def test_a_retired_milestone_is_reported_as_INFO_not_an_alarm(self):
        """`dropped` is TERMINAL, so `FI-2`'s grading already covers it — asserted here so the two
        changes cannot drift apart."""
        self.rm.add(ms("p1", status="ready"))
        self.rm.retire("p1", reason="superseded")
        [row] = [r for r in self.rows(NOT_READY) if r.subject == "p1"]
        self.assertEqual(row.severity, INFO)


class TestADepThatCanNEVERLandIsActionable(RoadmapCase):
    """A regression I shipped in `0.3.1` with the `FI-2` fix, surfaced by `FI-17`.

    `FI-2` said a milestone waiting on an unlanded dep should be INFO, because waiting is the design and
    a healthy stacked roadmap emits that row constantly. True — for a dep that is PROGRESSING.

    It is false for a dep that is TERMINAL. `LANDED = ("done",)`, so a dep sitting at `dropped` can never
    land, and its dependent is permanently unreachable. Before `FI-2` that row was ATTENTION; after it,
    INFO — and its `clears_when` still read *"every dep reaches status=done through an applied
    proposal"*, which for a dropped dep is impossible. **That is `FI-5`'s unclearable alarm, reintroduced
    by the fix for `FI-2`.**

    `milestone --retire` (`FI-10`, same release) makes this reachable in one command: retire a milestone
    and every dependent silently becomes permanently unready, reported as information.

    The distinction is not "is the dep done" but "can it ever be".
    """

    def rows_for(self, kind):
        return [r for r in self.rm.report() if r.kind == kind]

    def test_a_dep_stuck_at_a_TERMINAL_status_is_attention_not_info(self):
        self.rm.add(ms("p1", status="ready"))
        self.rm.add(ms("q5", status="ready", deps=["p1"]))
        self.rm.retire("p1", reason="superseded by the v0..v3 split")
        [row] = [r for r in self.rows_for(NOT_READY) if r.subject == "q5"]
        self.assertEqual(row.severity, ATTENTION,
                         "a dependent whose dep can NEVER land is reported as information")

    def test_its_clears_when_does_not_prescribe_the_impossible(self):
        """`FI-5`'s rule: an alarm may not name a remedy that cannot happen. `dropped` is terminal, so
        'reaches status=done' is not a route — the route is to re-scope or re-raise."""
        self.rm.add(ms("p1", status="ready"))
        self.rm.add(ms("q5", status="ready", deps=["p1"]))
        self.rm.retire("p1", reason="superseded")
        [row] = [r for r in self.rows_for(NOT_READY) if r.subject == "q5"]
        self.assertNotIn("reaches status=done", row.clears_when,
                         "the row tells the reader to wait for something that can never happen")
        self.assertTrue(row.clears_when, "the row states no route at all")
        self.assertIn("p1", row.detail, "the row does not name the dep that can never land")

    def test_a_dep_still_PROGRESSING_stays_info(self):
        """`FI-2` unchanged for the case it was about — this must stay a narrowing, not a revert."""
        self.rm.add(ms("s1", status="running"))
        self.rm.add(ms("s2", status="ready", deps=["s1"]))
        [row] = [r for r in self.rows_for(NOT_READY) if r.subject == "s2"]
        self.assertEqual(row.severity, INFO, "FI-2 was reverted; a progressing dep is not an alarm")

    def test_a_dep_at_DONE_is_not_a_blocker_at_all(self):
        self.rm.add(ms("s1", status="done"))
        self.rm.add(ms("s2", status="ready", deps=["s1"]))
        self.assertIn("s2", {m.id for m in self.rm.ready()})
