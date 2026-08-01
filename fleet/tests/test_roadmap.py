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
                if m.status in TERMINAL:
                    self.assertEqual(row.severity, INFO, "finished work is information, not an alarm")
                else:
                    self.assertEqual(row.severity, ATTENTION)
                    self.assertTrue(row.clears_when, "an alarm states its clearing condition")
                    self.assertTrue(row.clears_who, "an alarm states its clearing ACTOR (RI-31)")
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
