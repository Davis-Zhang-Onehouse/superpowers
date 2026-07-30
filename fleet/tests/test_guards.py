"""Admission control, interrogated without being triggered.

Every case below names the finding it encodes, because the case list is the hard part here: each of these
was shipped the first time by an assertion weaker than the case intended.

The one that matters most is `test_evaluate_never_mutates_anything`. *"A guard you cannot interrogate
non-destructively gets interrogated destructively"* — twice, by two actors, one of whom had **read and
cited** the entry that declined to run that exact command. The probe's failure mode is *doing the thing
you were checking you could not do*, and it fires precisely when the freeze has lifted: a probe that
claims a lease to test capacity leaves no trace at all when the pool is full, and takes a slot the moment
one is free. So the fixture under that test deliberately has a free slot, and the assertion is a zero
delta across the filesystem, the record store AND the pool.

The whole fleet is built through the injected probes (`Probes`, `cwd_probe`, `alive`): nothing here starts
a process, a tmux or a repository, and nothing reads a `.md` file for a control signal.
"""
import json
import pathlib
import shutil
import tempfile
import unittest

from fleet import EXIT_NO_CAPACITY, EXIT_REFUSED
from fleet.errors import BadInput, FleetError, NoCapacity, Refused
from fleet.identity import InstantName
from fleet.guards import (DEFAULT_WIP_CAP, EXEMPT_FROM_ADMISSION, EXEMPTION_REASONS, MIS_TRIGGERS,
                          UNDER_TRIGGERS, CompactionExclusive, Context, PoolCapacity,
                          ProfileOpTypeAgreement, Verdict, WipCap, enforce_all, evaluate_all,
                          guards_for)
from fleet.pool import Pool
from fleet.profiles import Profile
from fleet.reconcile import reconcile
from fleet.session import LiveSession, Probes, SessionLayer
from fleet.store import Declarations, Record, Store

OURS = "/i/00000000-07300312-inflight-append-fleetInfraRebuild"
THEIRS = "/i/00000000-07290101-inflight-append-otherEffort"

#: A pane still offering a way to interrupt: the single-observation definition of "progressing".
BUSY_PANE = "\n".join(["reading src/fleet/pool.py", "Thinking...", "  esc to interrupt"])
#: A pane that is neither working nor waiting for a keystroke. The state a CI waiter's pane is really in
#: — and therefore the exact shape a guard must NOT read a phase out of (`M-46`).
QUIET_PANE = "\n".join(["compiled 42 files", "wrote target/fleet.jar", "done"])

#: Prose claiming the phase, with no declaration behind it. `RCF-9`: a worker declared `Phase:
#: AWAITING-CI` exactly as its brief worded it, a leading `## ` defeated the consumer's regex, and at a
#: cap of 1 that holds the effort's only dev slot for the length of a CI queue.
PROSE_HANDOFF = "## Phase: AWAITING-CI\n\n`Phase: AWAITING-CI` is declared above.\n"

#: States the cap excludes, written out as literals rather than imported from `reconcile`, so the
#: assertion is anchored to the rule and not to whatever the implementation currently exports.
CAP_EXCLUDED = ("AWAITING-CI", "COMPLETE")


def snapshot(root: pathlib.Path) -> dict:
    """Every path under `root` with its kind, mtime and size.

    This is the filesystem half of the dry-run diff (design §10, the Dry-run row). A guard that claims a
    lease and gives it back leaves the tree byte-identical, so the directory mtimes are load-bearing:
    `leases/` is touched by the mkdir that claims and again by the rmdir that releases.
    """
    out = {}
    for path in sorted(root.rglob("*")):
        stat = path.stat()
        out[str(path)] = (path.is_dir(), stat.st_mtime_ns, stat.st_size if path.is_file() else 0)
    return out


class Fleet:
    """A synthetic fleet, built through probes only, that a `Context` can be pointed at."""

    def __init__(self, slots: int = 2):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-guards-"))
        self.home = self.tmp / "fleethome"
        self.instants = self.tmp / "instants"
        self.instants.mkdir()
        self.slots_dir = self.tmp / "slots"
        self.slots_dir.mkdir()

        self.procs, self.panes, self.tmux_live, self.holders = [], {}, set(), {}
        probes = Probes(list_processes=lambda: list(self.procs),
                        capture_pane=lambda name: self.panes.get(name, ""),
                        has_session=lambda name: name in self.tmux_live,
                        start_session=lambda name, cwd, cmd: None,
                        kill_session=lambda name: None)
        self.sessions = SessionLayer(probes)
        self.store = Store(self.home)
        self.pool = Pool(self.home,
                         cwd_probe=lambda path: list(self.holders.get(str(path), [])),
                         alive=self.sessions.alive)
        for index in range(slots):
            slot = f"ws{index + 1}"
            (self.slots_dir / slot).mkdir()
            self.pool.enroll(self.slots_dir / slot)
        self._n = 0
        self.paths = {}

    # ---- fixture construction ---------------------------------------------------------------

    def worker(self, name, *, optype="append", state="inflight", phase=None, pane=BUSY_PANE,
               live=True, base=OURS, slot=None, launched=True, handoff="Updated: now\n"):
        """One dispatched subject: a folder, a record, optionally a lease, a process and a declaration."""
        self._n += 1
        curr = f"0730{self._n:04d}"
        folder = f"00000000-{curr}-{state}-{optype}-{name}"
        path = self.instants / folder
        path.mkdir()
        (path / "HANDOFF.md").write_text(handoff)
        todo_id, tmux = f"{name}-{curr}", f"dt-{name}"
        self.store.write(Record(
            todo_id=todo_id, child_instant=str(path), base_instant=base, slot=slot or "", tmux=tmux,
            profile="/p/worker", golden="/ws0", lineage_base="", title=name,
            dispatched_at="2026-07-30T03:12:00Z",
            launched_at="2026-07-30T03:13:00Z" if launched else None))
        if slot:
            self.pool.claim(todo_id=todo_id, tmux=tmux, base_instant=base,
                            child_instant=str(path), slot=slot)
        if phase:
            self.assertish(Declarations(path).set_phase(phase) == phase, "the declaration did not land")
        if live:
            cwd = self.slots_dir / slot if slot else path
            self.procs.append(LiveSession(pid=1000 + self._n, cwd=cwd, name=tmux))
            self.panes[tmux] = pane
            self.tmux_live.add(tmux)
        self.paths[name] = path
        return folder

    @staticmethod
    def assertish(ok, message):
        if not ok:
            raise AssertionError(message)

    def profile(self, kind: str) -> Profile:
        """A profile whose kind is DECLARED. `profiles.load` never reads it out of charter prose."""
        path = self.tmp / "profiles" / kind
        path.mkdir(parents=True, exist_ok=True)
        (path / "profile.json").write_text(json.dumps({"kind": kind}))
        (path / "charter.md").write_text("Run `fleet declare phase awaiting-ci` while CI runs.\n")
        return Profile.load(path)

    def ctx(self, **kw) -> Context:
        fields = dict(store=self.store, pool=self.pool, sessions=self.sessions,
                      instants_dir=self.instants, base=OURS)
        fields.update(kw)
        return Context(**fields)

    def subjects(self):
        return reconcile(self.store, self.pool, self.sessions, self.instants)

    def pool_state(self) -> dict:
        """Enrolment, every lease body, and what is free — the pool half of the dry-run diff."""
        return {
            "slots": list(self.pool.slots()),
            "free": list(self.pool.free_slots()),
            "leases": {slot: (self.pool.lease(slot).to_json() if self.pool.lease(slot) else None)
                       for slot in self.pool.slots()},
        }

    def record_state(self) -> list:
        return [json.dumps(rec.to_json(), sort_keys=True) for rec in self.store.all()]


class GuardCase(unittest.TestCase):
    def fleet(self, slots: int = 2) -> Fleet:
        made = Fleet(slots=slots)
        self.addCleanup(shutil.rmtree, made.tmp, ignore_errors=True)
        return made

    # ---- the rule, restated test-side ---------------------------------------------------------

    def active_dev(self, ctx) -> list:
        """The population the cap counts, re-derived here from the join's own output.

        Deliberately a second statement of the rule: `test_an_under_triggering_guard_has_no_false_refusal_mutant`
        needs a licence it did not get from the code under test.
        """
        return [s for s in reconcile(ctx.store, ctx.pool, ctx.sessions, ctx.instants_dir)
                if s.kind == "worker"
                and s.evidence.get("base") == ctx.base
                and s.state not in CAP_EXCLUDED]

    def verdict_of(self, verdicts, guard_name) -> Verdict:
        hits = [v for v in verdicts if v.guard == guard_name]
        self.assertEqual(len(hits), 1, f"expected exactly one {guard_name!r} verdict, got {verdicts}")
        return hits[0]

    def matrix(self) -> list:
        """`(label, ctx)` over every shape that has ever made these two rules disagree.

        Each cell is its own fleet, so a cell cannot be contaminated by the one before it.
        """
        cells = []

        idle = self.fleet()
        cells.append(("nothing running at all", idle.ctx()))

        one = self.fleet()
        one.worker("solo", slot="ws1")
        cells.append(("one active-dev worker, cap reached", one.ctx()))

        # THE cell `M-44` disagrees on: a re-derived count that forgets the exclusion refuses here.
        waiter = self.fleet()
        waiter.worker("ciWaiter", slot="ws1", phase="awaiting-ci", pane=QUIET_PANE)
        cells.append(("one DECLARED ci waiter, cap has room", waiter.ctx()))

        undeclared = self.fleet()
        undeclared.worker("proseClaimer", slot="ws1", pane=QUIET_PANE, handoff=PROSE_HANDOFF)
        cells.append(("one undeclared quiet worker, cap reached", undeclared.ctx()))

        running_compaction = self.fleet()
        running_compaction.worker("foldTheStack", optype="compact", slot="ws1")
        cells.append(("a compaction that is working", running_compaction.ctx()))

        # The unfoldable cell: the cap has room and the dispatch must still be refused.
        parked_compaction = self.fleet()
        parked_compaction.worker("foldTheStack", optype="compact", slot="ws1",
                                 phase="awaiting-ci", pane=QUIET_PANE)
        cells.append(("a compaction awaiting CI", parked_compaction.ctx()))

        completed_compaction = self.fleet()
        completed_compaction.worker("foldTheStack", optype="compact", state="complete", live=False)
        cells.append(("a compaction whose folder says complete", completed_compaction.ctx()))

        foreign = self.fleet()
        foreign.worker("theirWork", slot="ws1", base=THEIRS)
        cells.append(("another effort's worker", foreign.ctx()))

        full = self.fleet(slots=1)
        full.worker("ciWaiter", slot="ws1", phase="awaiting-ci", pane=QUIET_PANE)
        cells.append(("every enrolled slot leased", full.ctx()))

        disagree = self.fleet()
        cells.append(("a compact profile dispatched as append",
                      disagree.ctx(profile=disagree.profile("compaction"), optype="append")))

        agree = self.fleet()
        cells.append(("a compact profile dispatched as compact",
                      agree.ctx(profile=agree.profile("compaction"), optype="compact")))

        overridden = self.fleet()
        overridden.worker("foldTheStack", optype="compact", slot="ws1",
                          phase="awaiting-ci", pane=QUIET_PANE)
        cells.append(("a compaction, overridden with a stated reason",
                      overridden.ctx(override_reason="the rebase landed at 04:10; I checked the log")))

        raised = self.fleet()
        raised.worker("solo", slot="ws1")
        cells.append(("cap raised to two with one active", raised.ctx(cap=2)))

        return cells


class TestInterrogation(GuardCase):
    def test_evaluate_never_mutates_anything(self):
        # "A guard you cannot interrogate non-destructively gets interrogated destructively" — twice, by
        # two actors, one of whom had READ AND CITED the entry that declined to run that exact command.
        # The probe's failure mode is doing the thing you were checking you could not do.
        fleet = self.fleet(slots=3)
        fleet.worker("solo", slot="ws1")
        fleet.worker("ciWaiter", slot="ws2", phase="awaiting-ci", pane=QUIET_PANE)
        fleet.worker("foldTheStack", optype="compact", live=False, launched=False)
        ctx = fleet.ctx(profile=fleet.profile("compaction"), optype="append")

        # The probe under test only bites when the guard ALLOWS: `Pool.claim` on a full pool raises
        # before it touches the filesystem, so a full-pool fixture would make this assertion vacuous.
        # It fires precisely when the freeze has lifted.
        self.assertTrue(fleet.pool.free_slots(), "no free slot: the destructive probe cannot fire")

        before_fs = snapshot(fleet.tmp)
        before_records = fleet.record_state()
        before_pool = fleet.pool_state()

        verdicts = evaluate_all(ctx, "dispatch")
        self.assertTrue(verdicts, "nothing was interrogated, so nothing is being asserted")
        self.assertTrue(any(not v.allowed for v in verdicts), "no guard refused: not the interesting path")
        evaluate_all(ctx, "dispatch")
        evaluate_all(ctx, "resume")
        for guard in guards_for(ctx):
            guard.evaluate(ctx)
            guard.evaluate(ctx)
        PoolCapacity().evaluate(ctx)

        self.assertEqual(fleet.record_state(), before_records, "a probe wrote the record store")
        self.assertEqual(fleet.pool_state(), before_pool, "a probe took, moved or freed a lease")
        after_fs = snapshot(fleet.tmp)
        self.assertEqual(sorted(after_fs), sorted(before_fs), "a probe created or removed a path")
        self.assertEqual(after_fs, before_fs, "a probe changed a file: the interrogation was destructive")

    def test_enforce_raises_refused_with_the_blocker_named(self):
        # A refusal that does not name what blocks it cannot be acted on.
        fleet = self.fleet()
        folder = fleet.worker("foldTheStack", optype="compact", slot="ws1",
                              phase="awaiting-ci", pane=QUIET_PANE)
        ctx = fleet.ctx()

        with self.assertRaises(Refused) as caught:
            enforce_all(ctx, "dispatch")
        error = caught.exception
        self.assertEqual(error.blocker, folder, "the refusal does not name the compaction instant")
        self.assertIn(folder, str(error))
        self.assertTrue(error.clears_when and error.clears_when.strip(), "no clearing condition")
        self.assertTrue(error.clears_who and error.clears_who.strip(), "no clearing actor")
        self.assertEqual(error.exit_code, EXIT_REFUSED)

        # The same fact, non-destructively: the verdict carries the blocker too.
        verdict = self.verdict_of(evaluate_all(ctx, "dispatch"), "compaction-exclusive")
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.blocker, folder)

    def test_enforce_and_evaluate_never_disagree(self):
        # Two code paths for one rule is how they drift: `enforce` must CALL `evaluate`, not re-derive it.
        # The per-guard half below is the load-bearing one — `M-44` re-derives inside one guard's
        # `enforce` and disagrees on the declared-CI-waiter cell.
        cells = self.matrix()
        self.assertGreaterEqual(len(cells), 8, "a matrix this small is not a matrix")
        allowed_seen, refused_seen = 0, 0
        for label, ctx in cells:
            for guard in guards_for(ctx):
                verdict = guard.evaluate(ctx)
                raised = None
                try:
                    guard.enforce(ctx)
                except FleetError as exc:
                    raised = exc
                self.assertEqual(verdict.allowed, raised is None,
                                 f"{label}: {guard.name} evaluate says allowed={verdict.allowed} and "
                                 f"enforce {'raised ' + type(raised).__name__ if raised else 'did not raise'}")
                if raised is not None:
                    self.assertEqual(str(raised), verdict.reason,
                                     f"{label}: {guard.name} enforced a reason evaluate never gave")
                    refused_seen += 1
                else:
                    allowed_seen += 1

            # And at the gate level, where `enforce_all` must be a consumer of `evaluate_all`.
            verdicts = evaluate_all(ctx, "dispatch")
            blocked = [v for v in verdicts if not v.allowed]
            try:
                enforce_all(ctx, "dispatch")
                raised_all = None
            except FleetError as exc:
                raised_all = exc
            self.assertEqual(bool(blocked), raised_all is not None,
                             f"{label}: evaluate_all said {blocked} and enforce_all "
                             f"{'raised' if raised_all else 'passed'}")
        self.assertTrue(allowed_seen and refused_seen,
                        f"the matrix is one-sided: {allowed_seen} allow / {refused_seen} refuse")


class TestTheCap(GuardCase):
    def test_wip_cap_defaults_to_one(self):
        # MD-6. The default is 1, and there IS an override channel — otherwise "default" is a fiction.
        self.assertEqual(DEFAULT_WIP_CAP, 1)
        self.assertEqual(WipCap().cap, 1)
        fleet = self.fleet()
        fleet.worker("solo", slot="ws1")
        self.assertFalse(WipCap().evaluate(fleet.ctx()).allowed, "one active worker fills a cap of 1")
        self.assertTrue(WipCap().evaluate(fleet.ctx(cap=2)).allowed, "the cap cannot be raised")

    def test_awaiting_ci_does_not_count_against_the_cap(self):
        # The declaration is the whole bargain: at a cap of 1 an undeclared waiter holds the effort's
        # only dev slot for the length of a CI queue.
        fleet = self.fleet()
        fleet.worker("ciWaiter", slot="ws1", phase="awaiting-ci", pane=QUIET_PANE)
        path = fleet.paths["ciWaiter"]
        self.assertEqual(Declarations(path).phase(), "awaiting-ci")

        verdict = WipCap().evaluate(fleet.ctx())
        self.assertTrue(verdict.allowed, verdict.reason)
        enforce_all(fleet.ctx(), "dispatch")          # and the gate as a whole lets it through

        # Positive control from the same pipeline: withdraw the declaration and the slot is held again.
        Declarations(path).set_phase(None)
        self.assertIsNone(Declarations(path).phase())
        self.assertFalse(WipCap().evaluate(fleet.ctx()).allowed,
                         "the exclusion survived the withdrawal of the declaration that bought it")

    def test_an_UNDECLARED_worker_counts_against_the_cap(self):
        # THE STATED DIRECTION. Under-triggering, so the failure is a coordinator asking a question, not
        # a silent slot leak. The pane is quiet and the prose says AWAITING-CI: neither is a channel.
        fleet = self.fleet()
        fleet.worker("proseClaimer", slot="ws1", pane=QUIET_PANE, handoff=PROSE_HANDOFF)
        path = fleet.paths["proseClaimer"]
        self.assertIn("Phase: AWAITING-CI", (path / "HANDOFF.md").read_text())
        self.assertIsNone(Declarations(path).phase())

        verdict = WipCap().evaluate(fleet.ctx())
        self.assertFalse(verdict.allowed, "an undeclared worker was excluded from the cap")
        self.assertEqual(WipCap().direction, UNDER_TRIGGERS, "this is the direction being stated")
        with self.assertRaises(Refused):
            enforce_all(fleet.ctx(), "dispatch")

    def test_a_compaction_awaiting_ci_still_blocks_everything(self):
        # "Folding rule 2 into rule 1 gets exactly one of those two cases wrong, whichever way you fold
        # it." A compaction's cost is unfoldable rebase debt, not attention — so the cap, which counts
        # attention, has room, and the dispatch is refused anyway.
        fleet = self.fleet()
        folder = fleet.worker("foldTheStack", optype="compact", slot="ws1",
                              phase="awaiting-ci", pane=QUIET_PANE)
        ctx = fleet.ctx()

        cap = WipCap().evaluate(ctx)
        self.assertTrue(cap.allowed, f"the cap should have room: {cap.reason}")
        exclusive = CompactionExclusive().evaluate(ctx)
        self.assertFalse(exclusive.allowed, "an inflight compaction did not block")
        self.assertEqual(exclusive.blocker, folder)
        with self.assertRaises(Refused):
            enforce_all(ctx, "dispatch")

        # And it stops blocking when the compaction's own folder says the work is over.
        done = self.fleet()
        done.worker("foldTheStack", optype="compact", state="complete", live=False)
        self.assertTrue(CompactionExclusive().evaluate(done.ctx()).allowed,
                        "a completed compaction blocks forever: an unclearable alarm")

    def test_a_compaction_that_exists_only_as_a_folder_still_blocks_every_dispatch(self):
        """`SI-30`. The guard read only the reconciled join — records, leases, live processes — so a
        compaction that exists as a FOLDER WITH NO RECORD was invisible to it.

        Measured before the fix: `fleet init --optype compact` produced `…-inflight-compact-ondiskcompact`,
        the store held 0 records, the next `fleet dispatch` was **admitted at exit 0**, and
        `compaction-status` reported *"no compaction of this effort is inflight"*.

        That path is the documented one, not a hypothetical: `superpowers:maintain-workspace`'s compact
        operation says *"Create `<base>/main-<MMDDHHMM-now>-inflight-compact-<name>/`"* — a folder, no
        record. And it broke this guard's own promise: `direction` is `MIS_TRIGGERS` and the docstring says
        it will *"refuse a dispatch that would have been harmless rather than admit one that lands work
        under a compaction, because the second is unrepairable after the fact"*. Here it UNDER-triggered,
        toward the outcome it calls unrepairable.

        `base` is the 8-digit form because that is what `dispatch` passes; the fixture helper's full-instant
        `base_instant` is a different vocabulary from the folder name's `base` field, and conflating the two
        is how this test would silently stop exercising the disk at all.
        """
        fleet = self.fleet()
        folder = fleet.instants / "00000000-07300500-inflight-compact-foldTheStack"
        folder.mkdir()
        ctx = fleet.ctx(base="00000000")
        self.assertEqual([], [r for r in fleet.store.all()],
                         "this test is about an UNRECORDED compaction; the store must be empty")

        verdict = CompactionExclusive().evaluate(ctx)

        self.assertFalse(verdict.allowed,
                         f"a compaction present only on disk did not block a dispatch: {verdict.reason}")
        self.assertEqual(folder.name, verdict.blocker,
                         "the refusal must name the folder, or the operator cannot clear it")
        self.assertIn("renames its folder", verdict.clears_when or "")
        with self.assertRaises(Refused):
            enforce_all(ctx, "dispatch")

    def test_a_folder_compaction_stops_blocking_once_its_name_says_it_is_over(self):
        """The clearing action must actually clear, or the refusal is an unclearable alarm — the failure
        `test_a_compaction_awaiting_ci_still_blocks_everything` already guards for the recorded case."""
        fleet = self.fleet()
        #: `curr` is EIGHT DIGITS. The first version of this test built `0730050c` / `0730050a` from the
        #: state's initial, which `InstantName.parse` rejects — so both folders were skipped as non-instants
        #: and the test passed without ever reaching the state filter. Mutation A (delete the state filter)
        #: SURVIVED it, which is how the vacuity was found rather than assumed.
        for curr, state in (("07300501", "complete"), ("07300502", "abort")):
            folder = fleet.instants / f"00000000-{curr}-{state}-compact-foldTheStack"
            folder.mkdir()
            self.assertEqual(state, InstantName.parse(folder.name).state,
                             "the fixture name must parse, or this test asserts nothing")
        self.assertTrue(CompactionExclusive().evaluate(fleet.ctx(base="00000000")).allowed,
                        "a finished compaction blocks forever when it is read off the folder name")

    def test_another_efforts_folder_compaction_does_not_block_this_one(self):
        """Per-effort, matching the recorded path: *"another effort's compaction is that effort's rebase
        debt."* Without this the disk scan would freeze every dispatch on the box."""
        fleet = self.fleet()
        (fleet.instants / "07300400-07300500-inflight-compact-someoneElse").mkdir()
        self.assertTrue(CompactionExclusive().evaluate(fleet.ctx(base="00000000")).allowed,
                        "a compaction belonging to a different base blocked this effort's dispatch")

    def test_the_two_rules_are_independently_reportable(self):
        # "'The cap says I have room' is not an answer to 'may I dispatch?'"
        fleet = self.fleet()
        fleet.worker("foldTheStack", optype="compact", slot="ws1",
                     phase="awaiting-ci", pane=QUIET_PANE)
        verdicts = evaluate_all(fleet.ctx(), "dispatch")

        names = [v.guard for v in verdicts]
        self.assertEqual(len(names), len(set(names)), f"a guard reported twice: {names}")
        self.assertEqual(set(names), {"compaction-exclusive", "wip-cap", "profile-optype-agreement",
                                      "pool-capacity"})
        for verdict in verdicts:
            self.assertIsInstance(verdict, Verdict)
        self.assertTrue(self.verdict_of(verdicts, "wip-cap").allowed)
        self.assertFalse(self.verdict_of(verdicts, "compaction-exclusive").allowed)
        self.assertNotEqual(self.verdict_of(verdicts, "wip-cap").reason,
                            self.verdict_of(verdicts, "compaction-exclusive").reason)


class TestProfileAgreement(GuardCase):
    def test_a_compact_profile_with_optype_append_is_refused(self):
        # W2-13 / OBS-58: BOTH flags that make a compaction a compaction defaulted wrong, on a path taken
        # ONCE, at a cap of 1, unrepairable by rename afterwards.
        fleet = self.fleet()
        ctx = fleet.ctx(profile=fleet.profile("compaction"), optype="append")
        verdict = ProfileOpTypeAgreement().evaluate(ctx)
        self.assertFalse(verdict.allowed, "a compaction profile was dispatched as an append")
        self.assertIn("compact", verdict.reason)
        with self.assertRaises(Refused):
            enforce_all(ctx, "dispatch")
        # Positive control from the same pipeline: the agreeing pair passes.
        enforce_all(fleet.ctx(profile=fleet.profile("compaction"), optype="compact"), "dispatch")

    def test_a_fix_profile_with_optype_compact_is_refused(self):
        # The other direction. A fix profile declares kind `worker`; `compact` is not one of its opTypes.
        fleet = self.fleet()
        fix = fleet.profile("worker")
        self.assertEqual(fix.kind, "worker")
        ctx = fleet.ctx(profile=fix, optype="compact")
        verdict = ProfileOpTypeAgreement().evaluate(ctx)
        self.assertFalse(verdict.allowed, "a fix profile was dispatched as a compaction")
        with self.assertRaises(Refused):
            enforce_all(ctx, "dispatch")
        enforce_all(fleet.ctx(profile=fix, optype="append"), "dispatch")


class TestExemption(GuardCase):
    def test_resume_is_exempt_from_every_admission_guard(self):
        # OI-2 / MD-9.2 / FD-9: it is RESUME, not dispatch, and refusing a resume is its own outage — the
        # alarm that blocks the fix. Rev 1 of the design deleted this door entirely (FI-8).
        fleet = self.fleet()
        fleet.worker("foldTheStack", optype="compact", slot="ws1")
        ctx = fleet.ctx()

        # Positive control first: the door this one is exempt from is genuinely shut.
        with self.assertRaises(Refused):
            enforce_all(ctx, "dispatch")

        enforce_all(ctx, "resume")                      # must not raise
        self.assertIn("resume", EXEMPT_FROM_ADMISSION)
        self.assertTrue(all(v.allowed for v in evaluate_all(ctx, "resume")))
        reason = EXEMPTION_REASONS["resume"]
        self.assertTrue(reason and reason.strip(), "the exemption is recorded with no reason")
        self.assertIn("recovery", reason.lower())

    def test_an_override_requires_a_reason_and_a_set_but_empty_reason_is_bad_input(self):
        # OI-3's class on the override path: the ordinary refusal's remedy is "give a reason", which an
        # empty-reason caller just did — "telling someone to do the thing they already did sends them in
        # a circle". So "" is BAD INPUT (2) and absent is a REFUSAL (4); they are different answers.
        fleet = self.fleet()
        fleet.worker("foldTheStack", optype="compact", slot="ws1")

        with self.assertRaises(Refused) as refused:
            enforce_all(fleet.ctx(), "dispatch")
        self.assertEqual(refused.exception.exit_code, EXIT_REFUSED)

        for empty in ("", "   ", "\n"):
            with self.assertRaises(BadInput) as bad:
                enforce_all(fleet.ctx(override_reason=empty), "dispatch")
            self.assertEqual(bad.exception.exit_code, 2)
            self.assertNotIsInstance(bad.exception, Refused,
                                     "an empty reason came back as the refusal it was answering")
            with self.assertRaises(BadInput):
                evaluate_all(fleet.ctx(override_reason=empty), "dispatch")

        # A stated reason gets through, and the verdict still records what the rule said.
        stated = fleet.ctx(override_reason="the rebase landed at 04:10; I checked the log")
        enforce_all(stated, "dispatch")
        verdict = self.verdict_of(evaluate_all(stated, "dispatch"), "compaction-exclusive")
        self.assertTrue(verdict.allowed)
        self.assertIn("04:10", verdict.reason)


class TestDirectionAndCost(GuardCase):
    def test_every_guard_declares_its_direction_and_its_cost_on_pass(self):
        # FR2-11.6 / W2-27: a probe that is free while a guard is armed and a FULL DISPATCH the moment it
        # is not, with nothing in its text saying so.
        fleet = self.fleet()
        guards = guards_for(fleet.ctx())
        self.assertEqual(len(guards), 4, [g.name for g in guards])
        for guard in guards:
            self.assertTrue(guard.name and guard.name.strip(), f"{type(guard).__name__} has no name")
            self.assertIn(guard.direction, (UNDER_TRIGGERS, MIS_TRIGGERS),
                          f"{guard.name} declares direction={guard.direction!r}")
            self.assertTrue(guard.cost_on_pass and guard.cost_on_pass.strip(),
                            f"{guard.name} does not say what probing it costs when it allows")
            self.assertGreater(len(guard.cost_on_pass.split()), 5,
                               f"{guard.name}'s cost_on_pass is a label, not a statement")
        directions = {g.direction for g in guards}
        self.assertEqual(directions, {UNDER_TRIGGERS, MIS_TRIGGERS},
                         f"one direction covers every guard, which makes the field decorative: {directions}")

    def test_an_under_triggering_guard_has_no_false_refusal_mutant(self):
        # The stated direction must be TRUE, not decorative: an under-triggering guard never issues a
        # refusal its own rule does not license, over every context in the matrix.
        licences = {
            "wip-cap": lambda ctx: len(self.active_dev(ctx)) >= (DEFAULT_WIP_CAP if ctx.cap is None
                                                                 else ctx.cap),
            "pool-capacity": lambda ctx: not ctx.pool.free_slots(),
        }
        refusals = {}
        checked = 0
        for label, ctx in self.matrix():
            for guard in guards_for(ctx):
                if guard.direction != UNDER_TRIGGERS:
                    continue
                self.assertIn(guard.name, licences,
                              f"{guard.name} claims to under-trigger and states no licence here")
                checked += 1
                verdict = guard.evaluate(ctx)
                if not verdict.allowed:
                    refusals[guard.name] = refusals.get(guard.name, 0) + 1
                    self.assertTrue(licences[guard.name](ctx),
                                    f"{label}: {guard.name} refused with no licence: {verdict.reason}")
        self.assertTrue(checked, "no under-triggering guard was examined")
        self.assertEqual(set(refusals), set(licences),
                         f"an under-triggering guard never refused anywhere: {refusals}")


class TestExitCodes(GuardCase):
    def test_pool_capacity_reports_no_capacity_distinctly_from_refused(self):
        # A caller must tell a full pool from a policy refusal: 3 and 4 are different answers with
        # different remedies (reap or enroll, versus wait for the compaction).
        self.assertEqual((EXIT_NO_CAPACITY, EXIT_REFUSED), (3, 4))

        full = self.fleet(slots=1)
        full.worker("ciWaiter", slot="ws1", phase="awaiting-ci", pane=QUIET_PANE)
        self.assertEqual(full.pool.free_slots(), [])
        with self.assertRaises(NoCapacity) as no_capacity:
            enforce_all(full.ctx(), "dispatch")
        self.assertEqual(no_capacity.exception.exit_code, EXIT_NO_CAPACITY)
        self.assertNotIsInstance(no_capacity.exception, Refused,
                                 "a full pool arrived as a policy refusal")

        blocked = self.fleet(slots=2)
        blocked.worker("foldTheStack", optype="compact", slot="ws1",
                       phase="awaiting-ci", pane=QUIET_PANE)
        self.assertTrue(blocked.pool.free_slots(), "this fixture must have capacity to be about policy")
        with self.assertRaises(Refused) as refused:
            enforce_all(blocked.ctx(), "dispatch")
        self.assertEqual(refused.exception.exit_code, EXIT_REFUSED)
        self.assertNotIsInstance(refused.exception, NoCapacity,
                                 "a policy refusal arrived as a full pool")

        # And the two are reportable without being triggered, by name.
        self.assertFalse(self.verdict_of(evaluate_all(full.ctx(), "dispatch"), "pool-capacity").allowed)
        self.assertTrue(self.verdict_of(evaluate_all(blocked.ctx(), "dispatch"), "pool-capacity").allowed)


class TestTheCapUnderAClaim(GuardCase):
    """`FI-21`: the cap cannot be settled by a read, so it is settled on the claim.

    The record a records-derived cap counts is written *after* the gate. Five concurrent dispatchers all
    read "0 in active dev", all passed and all wrote — 20 of 20 iterations admitted the wrong number at
    `WIP_CAP=1`. The fix is not to let `evaluate` reserve anything (`M-43`, and `--dry-run`'s zero-delta
    contract, which exists because two actors damaged another effort's tree probing a guard); it is to ask
    again while holding the lease, which is the one artifact here that is already atomic.
    """

    def claims(self, fleet, *slots):
        """Won-but-unrecorded claims, exactly as a dispatcher leaves them between `pool.claim` and the
        record write. This is the state no records-derived population can see, and it is where five
        dispatchers all read "0 in active dev" and all passed (20 of 20 iterations)."""
        return [fleet.pool.claim(todo_id=f"claim{i}", tmux=f"dt-claim{i}", base_instant=OURS,
                                 child_instant=str(fleet.instants / f"00000000-07300{i:03d}-inflight-"
                                                                    f"append-claim{i}"),
                                 slot=slot)
                for i, slot in enumerate(slots)]

    def test_a_won_claim_is_invisible_to_the_records_pass_and_visible_holding_the_claim(self):
        fleet = self.fleet(slots=3)
        self.claims(fleet, "ws1", "ws2")
        advisory = self.verdict_of(evaluate_all(fleet.ctx(cap=1), "dispatch"), "wip-cap")
        self.assertTrue(advisory.allowed,
                        "the advisory pass counted something no record holds; `evaluate` must stay a "
                        "read of the records, or --dry-run's zero-delta contract is not what it says")
        held = self.verdict_of(evaluate_all(fleet.ctx(cap=1).under_claim("ws3"), "dispatch"), "wip-cap")
        self.assertFalse(held.allowed,
                         "holding a claim, the cap still could not see two claims ahead of it — this is "
                         "FI-21 restored")
        self.assertIn("claim0", held.reason, "the refusal does not NAME what is holding the cap")

    def test_exactly_cap_of_n_simultaneous_claimants_are_admitted(self):
        """The property E3 asserts, stated hermetically over the claim list.

        Both failure directions are live here. Counting nothing admits all five; counting every OTHER
        claimant symmetrically refuses all five, which is a livelock wearing a cap's clothes. Only an order
        every claimant computes identically admits exactly `cap`.
        """
        for cap in (1, 2, 3):
            fleet = self.fleet(slots=5)
            slots = [f"ws{i + 1}" for i in range(5)]
            self.claims(fleet, *slots)
            admitted = [slot for slot in slots
                        if self.verdict_of(evaluate_all(fleet.ctx(cap=cap).under_claim(slot),
                                                        "dispatch"), "wip-cap").allowed]
            self.assertEqual(len(admitted), cap,
                             f"at cap {cap}, {len(admitted)} of 5 simultaneous claimants were admitted "
                             f"({admitted})")

    def test_the_second_pass_does_not_refuse_a_caller_for_holding_the_slot_it_asked_about(self):
        # The pool is FULL once the last free slot has been claimed, and the claimant is the one holding
        # it. A rule that says "the pool is full" to a caller with the slot in its hand refuses a dispatch
        # for having succeeded at the very thing it was asking about.
        fleet = self.fleet(slots=1)
        self.claims(fleet, "ws1")
        self.assertEqual(fleet.pool.free_slots(), [])
        enforce_all(fleet.ctx(cap=5).under_claim("ws1"), "dispatch", under_claim=True)
        with self.assertRaises(NoCapacity):
            enforce_all(fleet.ctx(cap=5).under_claim("ws1"), "dispatch")

    def test_a_declared_ci_waiter_is_still_excluded_when_the_cap_is_asked_under_a_claim(self):
        # The exclusion is the whole bargain of the declaration (`RCF-9`), and the claim-aware population
        # is where it would silently be lost: an AWAITING-CI worker keeps its lease, so a population that
        # counted leases rather than deduplicating against records would count it again.
        fleet = self.fleet(slots=3)
        fleet.worker("ciWaiter", slot="ws1", phase="awaiting-ci", pane=QUIET_PANE)
        self.claims(fleet, "ws2")
        verdict = self.verdict_of(evaluate_all(fleet.ctx(cap=1).under_claim("ws2"), "dispatch"),
                                  "wip-cap")
        self.assertTrue(verdict.allowed,
                        f"a declared CI waiter was counted through its lease: {verdict.reason}")

    def test_another_efforts_claim_does_not_hold_this_efforts_cap(self):
        fleet = self.fleet(slots=3)
        fleet.pool.claim(todo_id="foreign", tmux="dt-foreign", base_instant=THEIRS,
                         child_instant="/i/foreign", slot="ws1")
        verdict = self.verdict_of(evaluate_all(fleet.ctx(cap=1).under_claim("ws2"), "dispatch"),
                                  "wip-cap")
        self.assertTrue(verdict.allowed,
                        f"another effort's claim was counted against this effort's cap: {verdict.reason}")

    def test_asking_under_a_claim_still_writes_nothing(self):
        # The second pass is the one that could most easily become a writer, since it exists to be asked
        # while a lease is held. `M-43` and --dry-run's zero-delta contract apply to it unchanged.
        fleet = self.fleet(slots=3)
        self.claims(fleet, "ws1")
        ctx = fleet.ctx(cap=1).under_claim("ws2")
        before_fs, before_records, before_pool = (snapshot(fleet.tmp), fleet.record_state(),
                                                  fleet.pool_state())
        evaluate_all(ctx, "dispatch")
        try:
            enforce_all(ctx, "dispatch", under_claim=True)
        except FleetError:
            pass
        self.assertEqual(fleet.record_state(), before_records, "the claim-held pass wrote a record")
        self.assertEqual(fleet.pool_state(), before_pool, "the claim-held pass touched a lease")
        self.assertEqual(snapshot(fleet.tmp), before_fs, "the claim-held pass changed a file")


if __name__ == "__main__":
    unittest.main()
