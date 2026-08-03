"""The one join, under a synthetic fleet that IS the specification.

Every case below names the finding it encodes, because the case list is the hard part here and a weaker
assertion than the case intends is how each of these was shipped the first time. Three independent bugs
in the predecessor had one shape — *a report that instructs action on a stale premise* — because three
views each computed state from a different subset of the facts, and **the one that was wrong was the one
everybody read**.

The whole fleet is built through the injected probes (`Probes`, `cwd_probe`, `alive`): `NFR2-3` exists so
a suite can describe a fleet without owning one. Nothing here starts a process, a tmux or a repository.
"""
import os
import pathlib
import tempfile
import time
import unittest
from dataclasses import fields as dataclass_fields

from fleet.pool import Pool
from fleet.reconcile import (ACTIONABLE_STATES, AWAITING_CI, COMPLETE, DEAD, IDLE, KINDS, PARKED,
                             RUNNING, STATES, UNREACHABLE, Subject, needs_a_human, reconcile)
from fleet.session import LiveSession, Probes, SessionLayer
from fleet.store import Declarations, Record, Store

#: Every enrolled slot. `ws9` is enrolled and NOT leased — the harvested subject's slot, which is what
#: makes `holds_slot is False` a fact about the lease rather than about enrolment.
SLOTS = ("ws1", "ws2", "ws3", "ws4", "ws5", "ws6", "ws7", "ws8", "ws9")

OURS = "/i/00000000-07300312-inflight-append-fleetInfraRebuild"
THEIRS = "/i/00000000-07290101-inflight-append-otherEffort"

#: A pane that is neither working nor waiting for a keystroke.
QUIET_PANE = "\n".join(["compiled 42 files", "wrote target/fleet.jar", "done"])
#: A pane still offering a way to interrupt: the single-observation definition of "progressing".
BUSY_PANE = "\n".join(["reading src/fleet/pool.py", "Thinking...", "  esc to interrupt"])
#: A modal. The caret line holds text nobody submitted, so a human keystroke is the only way forward.
MODAL_PANE = "\n".join(["Edit file src/fleet/pool.py?",
                        "❯ 1. Yes",
                        "  2. No, tell Claude what to do differently"])

PARK_BUSY_Q = "should the shim land before the rebase, or after?"
PARK_BLOCKED_Q = "is merging #441 mine to do?"


def _record(**kw) -> Record:
    base = dict(todo_id="", child_instant="", base_instant=OURS, slot="", tmux="",
                profile="/p/worker", golden="/ws0", lineage_base="", title="a title",
                dispatched_at="2026-07-30T03:12:00Z", launched_at="2026-07-30T03:13:00Z")
    base.update(kw)
    return Record(**base)


def snapshot(root: pathlib.Path) -> dict:
    """Every path under `root` with its mtime and size. The purity assertion compares this before and
    after, because the predecessor's `health` back-filled `launched_at` *during a read* — which made a
    report a writer, and a writer that runs on every glance is a writer nobody audits."""
    out = {}
    for path in sorted(root.rglob("*")):
        stat = path.stat()
        out[str(path)] = (path.is_dir(), stat.st_mtime_ns, stat.st_size if path.is_file() else 0)
    return out


class SyntheticFleet:
    """The fleet the plan requires, built through probes only.

    Contains, at minimum and by name: a dead-but-recorded session · a **live-but-unrecorded** session ·
    a renamed instant · a stale lease owned by another base · an `abort-compact` instant.
    """

    def __init__(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.home = self.tmp / "fleethome"
        self.instants = self.tmp / "instants"
        self.instants.mkdir()
        self.slots_dir = self.tmp / "slots"
        self.slots_dir.mkdir()

        self.procs = []
        self.panes = {}
        self.tmux_live = set()
        self.holders = {}

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
        for slot in SLOTS:
            (self.slots_dir / slot).mkdir()
            self.pool.enroll(self.slots_dir / slot)

        self.paths = {}
        self._build()

    # ---- fixture construction ------------------------------------------------------------

    def instant(self, folder: str, handoff: str = "Updated: now\nStatus: working\n") -> pathlib.Path:
        path = self.instants / folder
        path.mkdir()
        (path / "HANDOFF.md").write_text(handoff)
        return path

    def dispatch(self, todo_id, folder, slot, tmux, *, recorded_folder=None, lease=True,
                 handoff="Updated: now\nStatus: working\n", **kw) -> pathlib.Path:
        path = self.instant(folder, handoff=handoff)
        recorded = self.instants / (recorded_folder or folder)
        self.store.write(_record(todo_id=todo_id, child_instant=str(recorded), slot=slot,
                                 tmux=tmux, **kw))
        if lease:
            self.pool.claim(todo_id=todo_id, tmux=tmux, base_instant=OURS,
                            child_instant=str(recorded), slot=slot)
        self.paths[todo_id] = path
        return path

    def launch(self, tmux, pid, slot, pane):
        self.procs.append(LiveSession(pid=pid, cwd=self.slots_dir / slot, name=tmux))
        self.panes[tmux] = pane
        self.tmux_live.add(tmux)

    def age(self, todo_id, seconds):
        """Make an instant look untouched for `seconds`. `_idle_for` reads the instant directory, its
        direct children and `.fleet/*` — so all three must be aged, and aged LAST, because writing a
        declaration refreshes the mtime of the file it writes."""
        instant = self.paths[todo_id]
        old = time.time() - seconds
        paths = [instant] + list(instant.iterdir())
        for child in list(instant.iterdir()):
            if child.name == ".fleet" and child.is_dir():
                paths += list(child.iterdir())
        for path in paths:
            os.utime(path, (old, old))

    def _build(self):
        # 1. Dead but recorded: a record, a lease, an `-inflight-` folder, and no process anywhere.
        # `board` rendered this PARKED and counted it in "N sessions need you" while `health` said DEAD
        # from the same records (W2-14 / OBS-57).
        self.dispatch("deadWorker-07300301", "00000000-07300301-inflight-append-deadWorker",
                      "ws1", "dt-deadWorker")

        # 2. Live but unrecorded, cwd outside every slot. OBS-48: a SCREEN session sat idle 8d20h,
        # invisible to every records-first sweep.
        outside = self.tmp / "outside" / "someonesShell"
        outside.mkdir(parents=True)
        self.procs.append(LiveSession(pid=4242, cwd=outside, name="screen-1"))

        # 3. Renamed instant: the record still says `-inflight-`, the disk says `-complete-`.
        self.dispatch("renamedWork-07300302", "00000000-07300302-complete-append-renamedWork",
                      "ws2", "dt-renamedWork",
                      recorded_folder="00000000-07300302-inflight-append-renamedWork")

        # 4. A stale lease owned by ANOTHER base, with no record in this store and no live process.
        # RI-31: the ownership guard refused correctly and read as a bug because it never said whose
        # lease it was.
        self.pool.claim(todo_id="theirWork-07290101", tmux="dt-theirWork", base_instant=THEIRS,
                        child_instant=THEIRS + "/child", slot="ws3")

        # 5. An `-abort-compact-` instant: the state W2-21's fix never reached.
        self.dispatch("foldTheStack-07300303", "00000000-07300303-abort-compact-foldTheStack",
                      "", "dt-foldTheStack", lease=False,
                      recorded_folder="00000000-07300303-inflight-compact-foldTheStack")

        # 6. A declared CI waiter. Read from STRUCTURED state, never from prose.
        ci = self.dispatch("ciWaiter-07300304", "00000000-07300304-inflight-append-ciWaiter",
                           "ws4", "dt-ciWaiter")
        Declarations(ci).set_phase("awaiting-ci")
        self.launch("dt-ciWaiter", 101, "ws4", QUIET_PANE)

        # 7. PROSE claiming the same phase, with no declaration. RCF-9, made unreachable.
        self.dispatch("proseClaimer-07300305", "00000000-07300305-inflight-append-proseClaimer",
                      "ws5", "dt-proseClaimer",
                      handoff="## Phase: AWAITING-CI\n\n`Phase: AWAITING-CI` is declared above.\n")
        self.launch("dt-proseClaimer", 102, "ws5", QUIET_PANE)

        # 8. Parked, and progressing anyway. OBS-3: "a parked note while still working is just a note";
        # a permanently-red tick trains everyone to ignore red.
        busy = self.dispatch("parkedBusy-07300306", "00000000-07300306-inflight-append-parkedBusy",
                             "ws6", "dt-parkedBusy")
        Declarations(busy).park(PARK_BUSY_Q)
        self.launch("dt-parkedBusy", 103, "ws6", BUSY_PANE)

        # 9. Parked, with a modal on screen. OBS-7: a masked actionable state "sends you to the wrong
        # problem, and the wrong problem is one you cannot fix".
        blocked = self.dispatch("parkedBlocked-07300307",
                                "00000000-07300307-inflight-append-parkedBlocked",
                                "ws7", "dt-parkedBlocked")
        Declarations(blocked).park(PARK_BLOCKED_Q)
        self.launch("dt-parkedBlocked", 104, "ws7", MODAL_PANE)

        # 10. Harvested: complete on disk, lease released, slot ws9 free. FD-4 — this is what keeps the
        # board small enough to be read.
        self.dispatch("harvestedWork-07300308", "00000000-07300308-complete-append-harvestedWork",
                      "ws9", "dt-harvestedWork", lease=False,
                      recorded_folder="00000000-07300308-inflight-append-harvestedWork",
                      harvested_at="2026-07-30T04:00:00Z")

        # 11. Dispatched, never launched: `launched_at` is absent. Present so that back-filling a
        # missing field during the join has something to back-fill (see test_reconcile_is_pure).
        self.dispatch("pendingWork-07300309", "00000000-07300309-inflight-append-pendingWork",
                      "ws8", "dt-pendingWork", launched_at=None)

    # ---- queries -------------------------------------------------------------------------

    def reconcile(self):
        return reconcile(self.store, self.pool, self.sessions, self.instants)

    def leased_slots(self):
        return {slot for slot in self.pool.slots() if self.pool.lease(slot) is not None}


class TestReconcile(unittest.TestCase):
    def setUp(self):
        self.fleet = SyntheticFleet()
        self.subjects = self.fleet.reconcile()

    def subject(self, identity) -> Subject:
        hits = [s for s in self.subjects if s.identity == identity]
        self.assertEqual(len(hits), 1, f"expected exactly one subject {identity!r}, got {hits}")
        return hits[0]

    def of_kind(self, kind) -> list:
        return [s for s in self.subjects if s.kind == kind]

    # ---- the thirteen cases --------------------------------------------------------------

    def test_a_dead_but_recorded_session_is_DEAD_not_PARKED(self):
        # W2-14 / OBS-57: `board` said PARKED and counted it as needing a human; `health` said DEAD from
        # the same records. One join, one answer, and liveness is part of it.
        s = self.subject("deadWorker-07300301")
        self.assertEqual(s.state, "DEAD")
        self.assertTrue(s.holds_slot, "a dead worker still holds its slot until something releases it")

    def test_a_live_process_with_no_record_is_reported_as_an_unknown(self):
        # OBS-48. A records-first join is structurally blind to this session; process-first is the only
        # direction that can see it.
        unknowns = self.of_kind("unknown-session")
        self.assertEqual(len(unknowns), 1, [s.identity for s in unknowns])
        self.assertEqual(unknowns[0].state, "UNKNOWN-SESSION")
        self.assertIn("4242", " ".join(unknowns[0].evidence.values()))

    def test_an_unknown_session_is_never_marked_reapable(self):
        # "Some of those sessions are people's" (D-6). A tool that can kill a session it does not
        # understand is a tool nobody leaves armed.
        unknown = self.of_kind("unknown-session")[0]
        names = {f.name for f in dataclass_fields(Subject)}
        self.assertEqual(names & {"reapable", "killable", "reap", "kill", "safe_to_kill",
                                  "disposable", "stale"}, set())
        blob = " ".join([unknown.note, unknown.state, unknown.kind]
                        + list(unknown.evidence.keys()) + list(unknown.evidence.values())).lower()
        for authorising in ("reap", "kill", "terminate", "safe to remove", "may be removed"):
            self.assertNotIn(authorising, blob, f"the report authorises {authorising!r}")

    def test_a_renamed_instant_is_followed(self):
        s = self.subject("renamedWork-07300302")
        self.assertEqual(s.state, "COMPLETE")
        self.assertIn("00000000-07300302-complete-append-renamedWork",
                      " ".join(s.evidence.values()))

    def test_a_stale_lease_owned_by_another_base_is_a_subject_naming_its_owner(self):
        # RI-31: "not yours to clear" is a state, not a failure — but only if the report says whose.
        stale = self.of_kind("stale-lease")
        self.assertEqual(len(stale), 1, [s.identity for s in stale])
        self.assertEqual(stale[0].state, "STALE-LEASE")
        self.assertTrue(stale[0].holds_slot)
        self.assertIn(THEIRS, stale[0].note)

    def test_an_abort_compact_instant_reconciles_without_error(self):
        # The state W2-21's fix never reached. setUp already ran the join; this asserts the subject is
        # present and that the abort folder is what the join actually read.
        s = self.subject("foldTheStack-07300303")
        self.assertIn(s.state, STATES)
        self.assertIn("abort", " ".join(s.evidence.values()) + " " + s.note)

    def test_a_declared_awaiting_ci_worker_is_AWAITING_CI(self):
        self.assertEqual(Declarations(self.fleet.paths["ciWaiter-07300304"]).phase(), "awaiting-ci")
        self.assertEqual(self.subject("ciWaiter-07300304").state, "AWAITING-CI")

    def test_prose_claiming_a_phase_does_not_change_the_state(self):
        # RCF-9 made unreachable: the prose is right there, and it is not a control signal.
        handoff = (self.fleet.paths["proseClaimer-07300305"] / "HANDOFF.md").read_text()
        self.assertIn("Phase: AWAITING-CI", handoff)
        self.assertIsNone(Declarations(self.fleet.paths["proseClaimer-07300305"]).phase())
        self.assertEqual(self.subject("proseClaimer-07300305").state, "RUNNING")

    def test_a_parked_worker_that_is_progressing_is_RUNNING_with_a_note(self):
        s = self.subject("parkedBusy-07300306")
        self.assertEqual(s.state, "RUNNING")
        self.assertTrue(s.note.strip(), "the park must survive as a note")
        self.assertIn(PARK_BUSY_Q, s.note)

    def test_an_actionable_state_is_never_masked_by_a_standing_note(self):
        s = self.subject("parkedBlocked-07300307")
        self.assertEqual(s.state, "BLOCKED")
        self.assertIn(PARK_BLOCKED_Q, s.note)

    def test_only_slot_holding_subjects_report_holds_slot(self):
        # FD-4. The board renders `holds_slot` subjects only, so a False here is what keeps it small.
        self.assertFalse(self.subject("harvestedWork-07300308").holds_slot)
        self.assertTrue(any(s.holds_slot for s in self.subjects), "not a vacuous assertion")
        leased = self.fleet.leased_slots()
        for s in self.subjects:
            if s.holds_slot:
                self.assertIn(s.evidence.get("slot", ""), leased,
                              f"{s.identity} claims a slot the pool does not lease to it")
            else:
                self.assertNotIn(s.evidence.get("slot", ""), leased,
                                 f"{s.identity} holds {s.evidence.get('slot')!r} and does not say so")

    def test_reconcile_is_pure(self):
        # The fleet is built FRESH here and snapshotted before the FIRST join, not this class's. A
        # back-fill fires once and is then invisible: snapshotting after a join has already run makes
        # the very defect this test exists for undetectable, which is how it shipped the first time.
        fleet = SyntheticFleet()
        before = snapshot(fleet.tmp)
        first = fleet.reconcile()
        second = fleet.reconcile()
        self.assertEqual(first, second)
        after = snapshot(fleet.tmp)
        self.assertEqual(sorted(after), sorted(before), "the join created or removed a path")
        self.assertEqual(after, before, "the join changed a file: a report became a writer")

    def test_every_subject_carries_machine_identity(self):
        # OBS-62: the shipped assertion anchored to a summary line and could never match. Identity is
        # machine-readable, present on every subject, and unique — a key, not a label.
        self.assertTrue(self.subjects)
        for s in self.subjects:
            self.assertTrue(s.identity and s.identity.strip(), f"{s} has no machine identity")
            self.assertIn(s.kind, KINDS)
            self.assertIn(s.state, STATES)
        ids = [s.identity for s in self.subjects]
        self.assertEqual(len(set(ids)), len(ids), f"identity is not unique: {ids}")


if __name__ == "__main__":
    unittest.main()


class TestUnreachableIsNotDead(unittest.TestCase):
    """`SI-39`. A record whose SLOT is held by a live process is not dead, whatever tmux says.

    Measured on live work: with `FLEET_TMUX_SOCKET` unset, `board` called both instants of a running
    effort DEAD -- "the work stopped without renaming its folder" -- while both processes were an hour
    into their tasks. DEAD is actionable (the response is `reap`), so a wrong DEAD invites a human to free
    a slot out from under running work.
    """

    def _worker(self, proc_cwd):
        """One recorded worker whose tmux name NOTHING answers for, plus an optional live process.

        `tmux_live` is left empty on purpose: that is what being pointed at the wrong tmux server looks
        like from inside the join -- the session is simply not there.
        """
        fleet = SyntheticFleet()
        # ws9 is the fixture's unleased slot. ws3 is pre-claimed by another effort, so a record naming it
        # does not HOLD it -- and since SI-41 gates the holder probe on holding, using ws3 here would make
        # this case vacuous. The first version of this test did exactly that and passed anyway.
        slot = fleet.slots_dir / "ws9"
        slot.mkdir(exist_ok=True)
        # `slot` is the NAME, as every real record stores it -- checked against the live store, because the
        # first version of this test stored a PATH here and so agreed with a bug instead of the product.
        rec = _record(todo_id="t1", child_instant="00000000-07310348-inflight-append-w",
                      slot="ws9", tmux="dt-w")
        fleet.store.write(rec)
        fleet.pool.claim(todo_id=rec.todo_id, tmux=rec.tmux, base_instant=rec.base_instant,
                         child_instant=rec.child_instant, slot="ws9")
        if proc_cwd is not None:
            fleet.procs.append(LiveSession(pid=99, cwd=proc_cwd(fleet), name=None))
        subs = reconcile(fleet.store, fleet.pool, fleet.sessions, fleet.instants)
        return [s for s in subs if s.identity == "t1"][0]

    def test_a_slot_held_by_a_live_process_is_UNREACHABLE_not_DEAD(self):
        worker = self._worker(lambda f: f.slots_dir / "ws9")
        self.assertEqual(worker.state, UNREACHABLE,
                         "tmux could not name the session, but a live process holds the slot")
        self.assertIn("99", worker.note)
        self.assertIn("FLEET_TMUX_SOCKET", worker.note,
                      "the note must name the remedy; the usual cause is the wrong tmux server")

    def test_the_holder_pid_is_reported_as_evidence(self):
        worker = self._worker(lambda f: f.slots_dir / "ws9")
        self.assertEqual(worker.evidence.get("pid"), "99",
                         "a state derived from a pid must show the pid, or nobody can check it")

    def test_nothing_holding_the_slot_is_still_DEAD(self):
        worker = self._worker(None)
        self.assertEqual(worker.state, DEAD,
                         "the fix must not make a genuinely dead record un-diagnosable")

    def test_a_process_in_a_DIFFERENT_directory_does_not_rescue_the_record(self):
        # ws3, i.e. NOT this record's slot (which is ws9). The point of the case is that only a process in
        # THIS record's slot is evidence about THIS record.
        worker = self._worker(lambda f: f.slots_dir / "ws3")
        self.assertEqual(worker.state, DEAD,
                         "only a process in THIS record's slot is evidence about THIS record")


class TestATerminatedRecordDoesNotInheritTheLiveHolder(unittest.TestCase):
    """`SI-41`. A record that no longer holds its slot must not report the new holder's pid.

    `rec.slot` is a NAME, and a terminated record keeps naming the slot it used. When that slot is
    re-leased -- routine, since re-dispatching after an abort reuses both the slot and the title -- the dead
    record and the live one both say `ws3`.

    Observed on the live effort, and it was not cosmetic: `scripts/fleet-finished-pids.sh` maps
    `COMPLETE -> exclude from auto-resume` BY PID, so an aborted coordinator carrying the live
    coordinator's pid switched auto-resume off for a session that was still working -- silently, because
    the watchdog only ever sees a list of pids.
    """

    def test_the_dead_record_reports_no_pid_and_the_live_one_does(self):
        fleet = SyntheticFleet()
        # ws9 is the fixture's deliberately-UNLEASED slot. ws3 is pre-claimed by another effort, which is
        # what this fixture exists to model -- using it here would have made `_holds_slot` false for the
        # live record too, and the test would have "passed" for the wrong reason.
        slot = fleet.slots_dir / "ws9"
        slot.mkdir(exist_ok=True)

        dead_dir = fleet.instants / "00000000-07310334-abort-append-coord"
        (dead_dir / ".fleet").mkdir(parents=True)
        live_dir = fleet.instants / "00000000-07310348-inflight-append-coord"
        (live_dir / ".fleet").mkdir(parents=True)

        # Both name ws9 and both name the same tmux session -- exactly what re-dispatching produces.
        dead = _record(todo_id="coord-334", child_instant=str(dead_dir), slot="ws9", tmux="dt-coord")
        live = _record(todo_id="coord-348", child_instant=str(live_dir), slot="ws9", tmux="dt-coord")
        fleet.store.write(dead)
        fleet.store.write(live)
        fleet.pool.claim(todo_id=live.todo_id, tmux=live.tmux, base_instant=live.base_instant,
                         child_instant=live.child_instant, slot="ws9")   # only the LIVE one holds it
        fleet.procs.append(LiveSession(pid=4242, cwd=slot, name=None))        # a live process in ws9

        subs = {s.identity: s for s in reconcile(fleet.store, fleet.pool, fleet.sessions, fleet.instants)}
        self.assertEqual(subs["coord-348"].evidence.get("pid"), "4242",
                         "the record that HOLDS the slot may report the holder")
        self.assertEqual(subs["coord-334"].evidence.get("pid"), "",
                         "a record that no longer holds the slot must NOT inherit the new holder's pid — "
                         "that pid is fed to the watchdog's exclude list")
        self.assertEqual(subs["coord-334"].state, COMPLETE,
                         "the aborted folder still decides its state; only the pid was wrong")


class TestTheIdleDetectorIsProduced(unittest.TestCase):
    """`G-10`. `FI-14` made `IDLE` actionable and shipped; nothing ever drove `reconcile` TO it.

    Its flagship test (`test_render.test_a_stalled_worker_is_counted_as_needing_a_human`) hand-builds a
    subject already labelled `IDLE` and asserts the banner counts it — so it passes whether or not the
    detector can ever produce one. Measured by mutation: disabling `_live_state`'s threshold branch, or
    making `_idle_for` always report fresh, leaves the whole suite green. The control that says the
    harness CAN kill is reverting `FI-14` itself, which dies in `test_render`.

    These cases drive the real join, so the detector has a guard for the first time.
    """

    def setUp(self):
        self.fleet = SyntheticFleet()

    def subjects(self, idle_after_s=1800):
        return {s.identity: s for s in reconcile(
            self.fleet.store, self.fleet.pool, self.fleet.sessions,
            self.fleet.instants, idle_after_s=idle_after_s)}

    def test_a_worker_untouched_past_the_threshold_is_produced_as_idle(self):
        self.fleet.dispatch("stalled-07300401", "00000000-07300401-inflight-append-stalled",
                            "ws9", "dt-stalled")
        self.fleet.launch("dt-stalled", 5101, "ws9", QUIET_PANE)
        self.fleet.age("stalled-07300401", 2700)

        subject = self.subjects()["stalled-07300401"]

        self.assertEqual(subject.state, IDLE,
                         f"a live worker with a quiet pane, untouched for 2700s against a 1800s "
                         f"threshold, is not IDLE: {subject.state} / {subject.note!r}")
        self.assertIn("1800", subject.note,
                      "the IDLE note does not name the threshold it crossed")
        self.assertTrue(needs_a_human(subject),
                        "a stalled worker is not in the population a human is asked to act on")

    def test_a_working_worker_is_never_idle_however_old_the_instant(self):
        """The other half, and the one that stops the fix being "call everything IDLE". A pane still
        offering a way to interrupt is progressing, whatever the filesystem says."""
        self.fleet.dispatch("busy-07300402", "00000000-07300402-inflight-append-busy",
                            "ws9", "dt-busy")
        self.fleet.launch("dt-busy", 5102, "ws9", BUSY_PANE)
        self.fleet.age("busy-07300402", 999999)

        subject = self.subjects()["busy-07300402"]

        self.assertEqual(subject.state, RUNNING,
                         f"a busy pane was reported {subject.state} because its files are old")
        self.assertFalse(needs_a_human(subject), "a working worker needs nobody")

    def test_the_threshold_is_the_boundary_not_a_suggestion(self):
        """`idle_after_s` is a parameter and the comparison is strict. A case that only ever tests
        2700-vs-1800 cannot tell a working threshold from a hard-coded one."""
        self.fleet.dispatch("edge-07300403", "00000000-07300403-inflight-append-edge",
                            "ws9", "dt-edge")
        self.fleet.launch("dt-edge", 5103, "ws9", QUIET_PANE)
        self.fleet.age("edge-07300403", 600)

        self.assertEqual(self.subjects(idle_after_s=300)["edge-07300403"].state, IDLE,
                         "600s idle against a 300s threshold is not IDLE")
        self.assertEqual(self.subjects(idle_after_s=1800)["edge-07300403"].state, RUNNING,
                         "600s idle against a 1800s threshold was reported IDLE")


class TestAParkedQuestionAsksForAHuman(unittest.TestCase):
    """`G-11`. `fleet park --question` is how a child says "I cannot proceed without a decision", and
    *an empty park is not a park* — so a park is always a real question. It was not in
    `ACTIONABLE_STATES`, so `needs_a_human` said False and the child never entered the "N needs you"
    population. It surfaced only by timing out into `IDLE` after 30 minutes, which relabels a question
    as a stall.

    That is `FI-14` one state over: computed correctly, rendered correctly, read by nothing. Worse than
    `FI-14`, arguably — `IDLE` means "nobody knows why it stopped", `PARKED` means "your child is
    blocked on YOU specifically".
    """

    def test_a_parked_child_needs_a_human_immediately(self):
        fleet = SyntheticFleet()
        # ws9 is the one slot a fresh SyntheticFleet() leaves free (the harvested subject's slot,
        # released not leased) -- every other slot is claimed by the canonical fixture in `_build`,
        # matching the convention already used by the other post-canonical-fixture test classes below.
        fleet.dispatch("asked-07300404", "00000000-07300404-inflight-append-asked", "ws9", "dt-asked")
        fleet.launch("dt-asked", 5201, "ws9", QUIET_PANE)
        Declarations(fleet.paths["asked-07300404"]).park(PARK_BLOCKED_Q)

        subject = {s.identity: s for s in reconcile(
            fleet.store, fleet.pool, fleet.sessions, fleet.instants)}["asked-07300404"]

        self.assertEqual(subject.state, PARKED, f"expected PARKED, got {subject.state}")
        self.assertTrue(needs_a_human(subject),
                        "a child waiting on its coordinator's ANSWER is not in the needs-you population")
        self.assertIn(PARK_BLOCKED_Q, subject.note, "the note does not carry the question")

    def test_the_widening_is_exactly_one_state(self):
        """A blanket widening is the defect `W2-14`/`OBS-57` recorded — a banner nobody can answer
        trains people to ignore the banner. AWAITING-CI and the terminal states stay out."""
        self.assertEqual(set(ACTIONABLE_STATES), {"BLOCKED", "IDLE", "PARKED"},
                         f"ACTIONABLE_STATES is {ACTIONABLE_STATES}")
        for state in (AWAITING_CI, DEAD, COMPLETE, RUNNING, UNREACHABLE):
            self.assertNotIn(state, ACTIONABLE_STATES,
                             f"{state} became actionable; nobody can answer it with a keystroke")
