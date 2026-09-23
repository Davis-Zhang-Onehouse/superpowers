"""The teardown-safety bucket (FB-85, FB-88..FB-92): the verbs that END a record — `abort`, `harvest --id`,
`reap`, and the runtime switch that waits on them — kill, release and count with the same checks their siblings
already make. Each class is one member; every case was RED on the lineage base 4564667a before its fix."""

import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

from fleet import EXIT_OK, EXIT_REFUSED
from fleet import cli
from fleet.pool import Pool
from tests.test_cli import (BUSY_PANE, DIALOG_PANE, IDLE_PANE, QUEUED_PANE, CliCase, FOREIGN_BASE, OURS,
                            snapshot)


class PaneGuardOnTeardown(CliCase):
    """FB-88. `close` refuses a busy / queued-text / awaiting-operator pane and names `--force`; `abort` and
    `harvest --id` killed the same pane without asking. Both now ask `_pane_refusal` — the same predicate —
    before any write or kill, dry-run and real alike, and `--force` overrides only that guard."""

    def _abort(self, fleet, name, pane, *extra):
        instant = fleet.worker(name, slot="ws1", pane=pane)
        argv = ["abort", "--instant", str(instant), "--reason", "superseded", *extra]
        return instant, argv

    def _refused_before_anything(self, fleet, instant, argv, clause):
        todo = fleet.ids[instant.name.rsplit("-", 1)[-1]]
        before = (snapshot(fleet.tmp), fleet.pool_state(), fleet.record_state())
        dry = fleet.run(argv[:1] + ["--dry-run"] + argv[1:])
        self.assertEqual((snapshot(fleet.tmp), fleet.pool_state(), fleet.record_state()), before,
                         "the dry-run changed state")
        real = fleet.run(argv)
        self.assertEqual(real[0], EXIT_REFUSED, f"{argv[0]} went through a guarded pane: {real}")
        self.assertEqual((dry[0], dry[2]), (real[0], real[2]), "dry-run and real call disagree")
        self.assertIn(clause, real[2])
        self.assertIn("--force", real[2], "the refusal does not name its override")
        self.assertEqual(fleet.killed, [], "the pane was killed on a refusing path")
        self.assertIsNotNone(fleet.pool.lease("ws1"), "the slot was released on a refusing path")
        self.assertIsNone(fleet.store.read(todo).closed_at, "the record was stamped on a refusing path")
        return real

    def test_abort_refuses_a_busy_pane(self):
        fleet = self.fleet()
        instant, argv = self._abort(fleet, "busyOne", BUSY_PANE)
        self._refused_before_anything(fleet, instant, argv, "mid-turn")
        self.assertTrue(instant.exists())
        self.assertFalse((instant / ".fleet" / "abort.json").exists())

    def test_abort_refuses_queued_text(self):
        fleet = self.fleet()
        instant, argv = self._abort(fleet, "queuedOne", QUEUED_PANE)
        self._refused_before_anything(fleet, instant, argv, "unsubmitted text")

    def test_abort_refuses_a_pane_awaiting_the_operator(self):
        fleet = self.fleet()
        instant, argv = self._abort(fleet, "askingOne", DIALOG_PANE)
        self._refused_before_anything(fleet, instant, argv, "operator dialog")

    def test_the_refusal_names_the_abort_override_not_close(self):
        fleet = self.fleet()
        instant, argv = self._abort(fleet, "whichVerb", BUSY_PANE)
        code, _, err = fleet.run(argv)
        self.assertEqual(code, EXIT_REFUSED, err)
        self.assertIn(f"fleet abort --instant {instant}", err)
        self.assertNotIn("fleet close --id", err, "abort's refusal routed the caller to a different verb")

    def test_abort_force_overrides_the_pane_guard_and_nothing_else(self):
        fleet = self.fleet()
        instant, argv = self._abort(fleet, "forced", BUSY_PANE, "--force")
        code, out, err = fleet.run(argv)
        self.assertEqual(code, EXIT_OK, f"{out}{err}")
        self.assertIn("dt-forced", fleet.killed)
        self.assertIsNone(fleet.pool.lease("ws1"))

    def test_abort_force_does_not_override_the_cwd_holder_gate(self):
        """B10's gate is not a judgement about work in progress; `--force` never reaches it."""
        fleet = self.fleet()
        instant, argv = self._abort(fleet, "forcedHeld", BUSY_PANE, "--force")
        fleet.hold_slot_cwd("ws1", pid=93001)
        fleet.sessions.probes.pane_pid = lambda name: 7000 if name in fleet.tmux_live else None
        fleet.sessions.probes.parent_of = lambda pid: 1
        code, _, err = fleet.run(argv)
        self.assertEqual(code, EXIT_REFUSED, err)
        self.assertIn("93001", err)
        self.assertEqual(fleet.killed, [])

    def test_control_an_idle_pane_aborts(self):
        fleet = self.fleet()
        instant, argv = self._abort(fleet, "idleOne", IDLE_PANE)
        code, out, err = fleet.run(argv)
        self.assertEqual(code, EXIT_OK, f"{out}{err}")
        self.assertIn("dt-idleOne", fleet.killed)

    def test_control_a_dead_session_aborts(self):
        fleet = self.fleet()
        instant = fleet.worker("deadOne", slot="ws1", live=False)
        code, out, err = fleet.run(["abort", "--instant", str(instant), "--reason", "gone"])
        self.assertEqual(code, EXIT_OK, f"{out}{err}")

    def _harvestable(self, fleet, name, pane):
        path = fleet.worker(name, state="complete", slot="ws1", pane=pane)
        fleet.reviewed(path)
        return path

    def test_harvest_refuses_a_busy_pane_before_applying_anything(self):
        fleet = self.fleet()
        self._harvestable(fleet, "busyDone", BUSY_PANE)
        todo = fleet.ids["busyDone"]
        argv = ["harvest", "--id", todo]
        before = (snapshot(fleet.tmp), fleet.pool_state(), fleet.record_state())
        dry = fleet.run(argv[:1] + ["--dry-run"] + argv[1:])
        self.assertEqual((snapshot(fleet.tmp), fleet.pool_state(), fleet.record_state()), before)
        real = fleet.run(argv)
        self.assertNotEqual(real[0], EXIT_OK, f"harvest killed a mid-turn pane: {real}")
        self.assertEqual(dry[0], real[0], f"dry-run {dry} vs real {real}")
        self.assertIn("mid-turn", real[1] + real[2])
        self.assertIn("fleet harvest --id", real[1] + real[2])
        self.assertEqual(fleet.killed, [])
        self.assertIsNone(fleet.store.read(todo).harvested_at)
        self.assertIsNotNone(fleet.pool.lease("ws1"))

    def test_harvest_force_overrides_the_pane_guard(self):
        fleet = self.fleet()
        self._harvestable(fleet, "forcedDone", BUSY_PANE)
        code, out, err = fleet.run(["harvest", "--id", fleet.ids["forcedDone"], "--force"])
        self.assertTrue(fleet.store.read(fleet.ids["forcedDone"]).harvested_at, f"{code}{out}{err}")
        self.assertIn("dt-forcedDone", fleet.killed)

    def test_control_harvest_of_an_idle_pane(self):
        fleet = self.fleet()
        self._harvestable(fleet, "idleDone", IDLE_PANE)
        code, out, err = fleet.run(["harvest", "--id", fleet.ids["idleDone"]])
        self.assertTrue(fleet.store.read(fleet.ids["idleDone"]).harvested_at, f"{code}{out}{err}")


class ReleaseNamesTheLeaseItRead(CliCase):
    """FB-89. `abort` and `harvest --id` read the record's slot, then (after the kill) released it with no
    `expect_todo`: a slot re-claimed in between had the NEW claim freed. The seam: the kill itself hands the slot
    to an intruder, deterministically, between the read and the release."""

    def _reclaim_on_kill(self, fleet, slot):
        kill = fleet.sessions.probes.kill_session

        def kill_then_someone_claims(name):
            kill(name)
            fleet.pool.release(slot, force=True)
            fleet.pool.claim(todo_id="intruder-0001", tmux="dt-intruder", base_instant=FOREIGN_BASE,
                             child_instant="/elsewhere", slot=slot)
        fleet.sessions.probes.kill_session = kill_then_someone_claims

    def test_abort_does_not_free_a_claim_made_after_it_read_the_slot(self):
        fleet = self.fleet()
        instant = fleet.worker("racedAbort", slot="ws1", pane=IDLE_PANE)
        self._reclaim_on_kill(fleet, "ws1")
        code, out, err = fleet.run(["abort", "--instant", str(instant), "--reason", "raced"])
        held = fleet.pool.lease("ws1")
        self.assertIsNotNone(held, f"abort freed the intruder's claim: {out}{err}")
        self.assertEqual(held.todo_id, "intruder-0001")
        self.assertEqual(code, EXIT_OK, f"{out}{err}")
        self.assertIn("intruder-0001", out, "the abort did not say the slot was no longer this record's")

    def test_harvest_does_not_free_a_claim_made_after_it_read_the_slot(self):
        fleet = self.fleet()
        path = fleet.worker("racedHarvest", state="complete", slot="ws1", pane=IDLE_PANE)
        fleet.reviewed(path)
        self._reclaim_on_kill(fleet, "ws1")
        code, out, err = fleet.run(["harvest", "--id", fleet.ids["racedHarvest"]])
        held = fleet.pool.lease("ws1")
        self.assertIsNotNone(held, f"harvest freed the intruder's claim: {out}{err}")
        self.assertEqual(held.todo_id, "intruder-0001")
        self.assertIn("intruder-0001", out)

    def test_control_an_unraced_abort_releases_its_own_lease(self):
        fleet = self.fleet()
        instant = fleet.worker("plainAbort", slot="ws1", pane=IDLE_PANE)
        self.assertEqual(fleet.run(["abort", "--instant", str(instant), "--reason", "x"])[0], EXIT_OK)
        self.assertIsNone(fleet.pool.lease("ws1"))


def _spawn_unreadable_holder(slot: Path):
    """A REAL same-uid process whose cwd is `slot` and whose `/proc/<pid>/cwd` this user cannot read: python
    marks itself non-dumpable (`prctl(PR_SET_DUMPABLE, 0)`), and the kernel then refuses the readlink with EACCES
    while `stat` stays world-readable (FB-69's shape, no second uid needed). Its parent is a readable bash that
    sits in the slot too, so world-readable ancestry ties it to the slot. Returns (bash, child pid)."""
    code = "import ctypes,time; ctypes.CDLL(None).prctl(4, 0, 0, 0, 0); print(flush=True); time.sleep(60)"
    shell = subprocess.Popen(["bash", "-c", f'{sys.executable} -c "{code}" & echo $!; wait'],
                             cwd=str(slot), stdout=subprocess.PIPE, text=True)
    child = int(shell.stdout.readline())
    shell.stdout.readline()                      # the child's own line: prctl has run
    return shell, child


class UnreadableCwdHolder(unittest.TestCase):
    """FB-90. `_cwd_holders` caught OSError per pid and moved on, so a holder whose cwd cannot be read was
    invisible to the OBS-48 gate: unobservable read as absent."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="fleet-fb90-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.slot = self.tmp / "ws1"
        self.slot.mkdir()
        self.shell, self.child = _spawn_unreadable_holder(self.slot)

        def stop():
            for pid in (self.child, self.shell.pid):
                try:
                    os.kill(pid, 9)
                except ProcessLookupError:
                    pass
            self.shell.wait(timeout=10)
            self.shell.stdout.close()
        self.addCleanup(stop)

    def test_the_fixture_really_is_unreadable(self):
        with self.assertRaises(PermissionError):
            Path(f"/proc/{self.child}/cwd").resolve()
        self.assertEqual(Path(f"/proc/{self.shell.pid}/cwd").resolve(), self.slot.resolve())

    def test_an_unreadable_holder_tied_to_the_slot_is_reported(self):
        holders = cli._cwd_holders(self.slot)
        self.assertIn(self.shell.pid, holders, "control: the readable holder was not found")
        self.assertIn(self.child, holders, "the unreadable holder was skipped as if absent")

    def test_control_a_readable_holder_alone_refuses(self):
        """RV-29. The control that passes before and after FB-90: the readable parent, not spared, refuses."""
        pool = Pool(self.tmp / "home", cwd_probe=cli._cwd_holders)
        pool.enroll(self.slot)
        pool.claim(todo_id="t-1", tmux="dt-t", base_instant=OURS, child_instant="/x", slot="ws1")
        refusal = pool.release_refusal("ws1")
        self.assertIsNotNone(refusal)
        self.assertIn(str(self.shell.pid), str(refusal))

    def test_the_release_refusal_names_it_undecided(self):
        pool = Pool(self.tmp / "home", cwd_probe=cli._cwd_holders)
        pool.enroll(self.slot)
        pool.claim(todo_id="t-1", tmux="dt-t", base_instant=OURS, child_instant="/x", slot="ws1")
        refusal = pool.release_refusal("ws1", spare=[self.shell.pid])
        self.assertIsNotNone(refusal, "sparing the readable parent left the unreadable child invisible")
        self.assertIn(str(self.child), str(refusal))
        self.assertIn("could not be read", str(refusal))


class UnreadableHolderSurvivesTheKill(CliCase):
    """FB-90, through the verbs. An unreadable process tied to the slot only through the session being torn down
    is spared by the gate (the kill should end it) — and if it survives the kill it is reparented and no world-
    readable fact ties it to the slot any more. The teardown notes it in the lease first, so `abort`, its re-run
    and `reap` all still count it while that same process lives."""

    PANE, CHILD = 7000, 7005

    def _setup(self, fleet):
        try:
            from fleet.pool import UnreadableHolder
        except ImportError:
            #: RV-29. Before FB-90 the type did not exist; a plain int keeps the scenario RUNNABLE on that tree, so
            #: the case fails there on its assertion (the slot released under the orphan), not on an import.
            UnreadableHolder = int
        instant = fleet.worker("blindChild", slot="ws1", pane=IDLE_PANE)
        path = str(fleet.pool.slot_path("ws1"))
        fleet.holders[path] = [self.PANE, UnreadableHolder(self.CHILD)]
        fleet.sessions.probes.pane_pid = lambda name: self.PANE if name in fleet.tmux_live else None
        fleet.sessions.probes.parent_of = lambda pid: {self.CHILD: self.PANE}.get(pid, 1)
        self.alive = {self.CHILD}
        fleet.pool._pid_start = lambda pid: "4242" if pid in self.alive else None
        kill = fleet.sessions.probes.kill_session

        def kill_orphans_the_child(name):
            kill(name)
            fleet.holders[path] = []           # the pane is gone; the orphan is no longer tied by ancestry
        fleet.sessions.probes.kill_session = kill_orphans_the_child
        return instant

    def test_a_surviving_unreadable_child_keeps_the_slot_held(self):
        fleet = self.fleet()
        instant = self._setup(fleet)
        argv = ["abort", "--instant", str(instant), "--reason", "stuck"]
        before = fleet.pool_state()
        self.assertEqual(fleet.run(argv[:1] + ["--dry-run"] + argv[1:])[0], EXIT_OK)
        self.assertEqual(fleet.pool_state(), before, "the dry-run wrote the note")

        code, out, err = fleet.run(argv)
        self.assertEqual(code, EXIT_REFUSED, f"the slot was released under a live unreadable holder: {out}{err}")
        self.assertIn(str(self.CHILD), err)
        self.assertIn("could not be read", err)
        self.assertIsNotNone(fleet.pool.lease("ws1"))
        self.assertTrue(instant.exists(), "renamed on a refusing path")

        self.assertEqual(fleet.run(["reap", "--base", OURS])[0], EXIT_OK)
        self.assertIsNotNone(fleet.pool.lease("ws1"), "reap freed a slot a noted unreadable process still holds")
        self.assertEqual(fleet.run(argv)[0], EXIT_REFUSED, "the documented re-run released it anyway")

        self.alive.clear()                      # the process exits
        code, out, err = fleet.run(argv)
        self.assertEqual(code, EXIT_OK, f"{out}{err}")
        self.assertIsNone(fleet.pool.lease("ws1"))

    def test_control_an_unreadable_child_the_kill_ends_is_no_obstacle(self):
        fleet = self.fleet()
        instant = self._setup(fleet)
        kill = fleet.sessions.probes.kill_session
        fleet.sessions.probes.kill_session = lambda name: (kill(name), self.alive.clear())
        code, out, err = fleet.run(["abort", "--instant", str(instant), "--reason", "done"])
        self.assertEqual(code, EXIT_OK, f"{out}{err}")
        self.assertIsNone(fleet.pool.lease("ws1"))

    def test_an_undecided_gate_still_notes_the_unreadable_holders(self):
        """RV-19. With no pane pid to attribute holders, the gate is UNDECIDED and passes — and it used to note
        nothing, so the orphan it could see before the kill was read as absent after it."""
        fleet = self.fleet()
        instant = self._setup(fleet)
        fleet.sessions.probes.pane_pid = None             # attribution unobservable: the undecided branch
        fleet.sessions.probes.pane_pids = None
        code, out, err = fleet.run(["abort", "--instant", str(instant), "--reason", "stuck"])
        self.assertEqual(code, EXIT_REFUSED, f"released under a live unreadable holder: {out}{err}")
        self.assertIn(str(self.CHILD), err)
        self.assertIsNotNone(fleet.pool.lease("ws1"))

    def test_a_recycled_pid_is_not_the_noted_process(self):
        fleet = self.fleet()
        self._setup(fleet)
        fleet.pool.note_unreadable("ws1", [__import__("fleet.pool", fromlist=["x"]).UnreadableHolder(self.CHILD)],
                                   expect_todo=fleet.ids["blindChild"])
        fleet.holders[str(fleet.pool.slot_path("ws1"))] = []
        self.assertIn(self.CHILD, fleet.pool.cwd_holders("ws1"))
        fleet.pool._pid_start = lambda pid: "9999"          # same pid, a different process
        self.assertEqual(fleet.pool.cwd_holders("ws1"), [])


class NoteDoesNotResurrectOrClobber(unittest.TestCase):
    """RV-18. `note_unreadable` read the lease, then wrote the body with `atomic_write`, which creates missing
    parents: a release between the two recreated the claim directory (a phantom lease), and a re-claim had its
    body overwritten with the old todo. The seam is the start-time probe, which runs between the read and the
    write."""

    def setUp(self):
        import tempfile
        from fleet.pool import UnreadableHolder
        self.tmp = Path(tempfile.mkdtemp(prefix="fleet-rv18-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "ws1").mkdir()
        self.pool = Pool(self.tmp / "home")
        self.pool.enroll(self.tmp / "ws1")
        self.pool.claim(todo_id="old-1", tmux="dt-old", base_instant=OURS, child_instant="/x", slot="ws1")
        self.pids = [UnreadableHolder(4242)]

    def test_a_release_in_between_is_not_undone(self):
        def released_meanwhile(pid):
            self.pool.release("ws1", force=True)
            return "77"
        self.pool._pid_start = released_meanwhile
        self.assertEqual(self.pool.note_unreadable("ws1", self.pids, expect_todo="old-1"), [])
        self.assertFalse((self.pool.leases / "ws1").exists(), "the note recreated a released claim")

    def test_a_reclaim_in_between_is_not_overwritten(self):
        def reclaimed_meanwhile(pid):
            self.pool.release("ws1", force=True)
            self.pool.claim(todo_id="new-2", tmux="dt-new", base_instant=OURS, child_instant="/y", slot="ws1")
            return "77"
        self.pool._pid_start = reclaimed_meanwhile
        self.assertEqual(self.pool.note_unreadable("ws1", self.pids, expect_todo="old-1"), [])
        held = self.pool.lease("ws1")
        self.assertEqual((held.todo_id, held.unreadable_holders), ("new-2", []))

    def test_control_an_undisturbed_note_is_written(self):
        self.pool._pid_start = lambda pid: "77"
        self.assertEqual(self.pool.note_unreadable("ws1", self.pids, expect_todo="old-1"), [[4242, "77"]])
        self.assertEqual(self.pool.lease("ws1").unreadable_holders, [[4242, "77"]])
        self.assertEqual(sorted(p.name for p in (self.pool.leases / "ws1").iterdir()), ["lease.json"])


class EnrollDoesNotRepoint(CliCase):
    """FB-91. `Pool.enroll` wrote enrolled/<basename>.json unconditionally, so enrolling (or cloning to) a second
    directory with the same basename silently re-pointed the existing slot."""

    def test_enroll_of_a_same_basename_elsewhere_is_refused(self):
        fleet = self.fleet()
        original = fleet.pool.slot_path("ws1")
        other = fleet.tmp / "elsewhere" / "ws1"
        other.mkdir(parents=True)
        code, out, err = fleet.run(["enroll", "--slot", str(other)])
        self.assertEqual(fleet.pool.slot_path("ws1"), original, f"ws1 was re-pointed: {out}{err}")
        self.assertEqual(code, EXIT_REFUSED, err)
        self.assertIn(str(original), err)
        self.assertIn("fleet unenroll --slot ws1", err)
        dry = fleet.run(["enroll", "--dry-run", "--slot", str(other)])
        self.assertEqual((dry[0], dry[2]), (code, err))

    def test_clone_to_a_same_basename_elsewhere_is_refused_before_copying(self):
        fleet = self.fleet()
        golden = fleet.tmp / "golden"
        (golden / "alpha").mkdir(parents=True)
        self.assertEqual(fleet.run(["set-golden", "--path", str(golden)])[0], EXIT_OK)
        original = fleet.pool.slot_path("ws2")
        target = fleet.tmp / "elsewhere" / "ws2"
        target.parent.mkdir(parents=True)
        code, out, err = fleet.run(["clone", "--slot", str(target)])
        self.assertEqual(fleet.pool.slot_path("ws2"), original, f"ws2 was re-pointed: {out}{err}")
        self.assertEqual(code, EXIT_REFUSED, err)
        self.assertFalse(target.exists(), "the golden was copied before the refusal")

    def test_control_re_enrolling_the_same_path_is_idempotent(self):
        fleet = self.fleet()
        code, out, err = fleet.run(["enroll", "--slot", str(fleet.pool.slot_path("ws1"))])
        self.assertEqual(code, EXIT_OK, f"{out}{err}")


class ReapDryRunAnswersLikeTheRealCall(CliCase):
    """FB-85. `reap --dry-run` answered rc=0 where the real call exits 4, and judged staleness by session
    liveness alone. It now reads the same pure `Pool.reap_plan` the real reap executes."""

    def test_a_foreign_stale_lease(self):
        fleet = self.fleet()
        fleet.worker("foreignDead", slot="ws2", live=False, base=FOREIGN_BASE)
        argv = ["reap", "--base", OURS]
        before = (fleet.pool_state(), snapshot(fleet.tmp))
        dry = fleet.run(argv[:1] + ["--dry-run"] + argv[1:])
        self.assertEqual((fleet.pool_state(), snapshot(fleet.tmp)), before, "the dry-run changed state")
        real = fleet.run(argv)
        self.assertEqual(real[0], EXIT_REFUSED, f"control: the real reap no longer refuses: {real}")
        self.assertEqual(dry[0], real[0], f"dry-run {dry[0]} vs real {real[0]}: {dry[1]}")
        self.assertIn(FOREIGN_BASE, dry[1])

    def test_a_cwd_held_lease_is_not_reported_as_reapable(self):
        fleet = self.fleet()
        fleet.worker("heldDead", slot="ws2", live=False)
        fleet.hold_slot_cwd("ws2", pid=94001)
        code, out, err = fleet.run(["reap", "--dry-run", "--base", OURS])
        self.assertEqual(code, EXIT_OK, f"{out}{err}")
        ws2 = [line for line in out.splitlines() if "ws2" in line]
        self.assertTrue(ws2, out)
        self.assertIn("94001", "".join(ws2), f"the dry-run hid the holder that keeps ws2: {out}")
        self.assertEqual(fleet.run(["reap", "--base", OURS])[0], EXIT_OK)
        self.assertIsNotNone(fleet.pool.lease("ws2"), "control: the real reap freed a held slot")

    def test_control_an_owned_stale_lease_is_freed_by_both(self):
        fleet = self.fleet()
        fleet.worker("ownDead", slot="ws2", live=False)
        dry = fleet.run(["reap", "--dry-run", "--base", OURS])
        self.assertEqual(dry[0], EXIT_OK, dry)
        self.assertIsNotNone(fleet.pool.lease("ws2"))
        self.assertEqual(fleet.run(["reap", "--base", OURS])[0], EXIT_OK)
        self.assertIsNone(fleet.pool.lease("ws2"))


class RuntimeSwitchOverUnresumableRecords(CliCase):
    """FB-92 (coordinator D-30). `runtime_blockers` counted every record without `harvested_at`, so a record no
    verb could resume or revive blocked `runtime --set` forever, or cleared only after a fabricated review. A
    record now blocks only while `revive` or `resume` could still act on it; every blocker names the verb that
    clears it, and each test RUNS that verb."""

    def _switch(self, fleet):
        return fleet.run(["runtime", "--set", "codex"])

    def test_an_aborted_record_does_not_block(self):
        fleet = self.fleet()
        path = fleet.worker("dropped", slot="ws1", live=False)
        self.assertEqual(fleet.run(["abort", "--instant", str(path), "--reason", "abandoned"])[0], EXIT_OK)
        code, _, err = self._switch(fleet)
        self.assertEqual(code, EXIT_OK, err)

    def test_a_gone_folder_record_clears_by_reap_with_no_review(self):
        fleet = self.fleet()
        path = fleet.worker("gone", slot="ws1", live=False)
        shutil.rmtree(path)
        code, _, err = self._switch(fleet)
        self.assertEqual(code, EXIT_REFUSED, err)                 # its lease is still held
        self.assertIn("fleet reap", err)
        self.assertEqual(fleet.run(["reap", "--base", OURS])[0], EXIT_OK)
        code, _, err = self._switch(fleet)
        self.assertEqual(code, EXIT_OK, f"a record no verb can resume still blocks: {err}")

    def test_a_closed_unreviewed_complete_record_needs_no_review(self):
        fleet = self.fleet()
        fleet.worker("unreviewed", state="complete", slot="ws1", live=False)
        self.assertEqual(fleet.run(["close", "--id", fleet.ids["unreviewed"]])[0], EXIT_OK)
        self.assertEqual(fleet.run(["reap", "--base", OURS])[0], EXIT_OK)
        code, _, err = self._switch(fleet)
        self.assertEqual(code, EXIT_OK, f"only a fabricated review would clear it: {err}")

    def test_a_closed_inflight_record_still_blocks_and_abort_clears_it(self):
        """`resume` can still adopt an -inflight- folder, so it blocks; the route it names is `abort`, and it runs."""
        fleet = self.fleet()
        path = fleet.worker("halfway", slot="ws1", live=False)
        self.assertEqual(fleet.run(["close", "--id", fleet.ids["halfway"]])[0], EXIT_OK)
        code, _, err = self._switch(fleet)
        self.assertEqual(code, EXIT_REFUSED, err)
        self.assertIn(f"fleet abort --instant {path}", err)
        self.assertNotIn("FB-92", err, "the refusal still calls this a known gap")
        self.assertEqual(fleet.run(["abort", "--instant", str(path), "--reason", "switching runtime"])[0], EXIT_OK)
        code, _, err = self._switch(fleet)
        self.assertEqual(code, EXIT_OK, f"the named route ran and the switch is still refused: {err}")

    def test_an_untagged_record_names_a_reap_that_runs(self):
        """RV-20. A legacy record with no base printed `fleet reap --base ` with nothing after it."""
        fleet = self.fleet()
        fleet.worker("legacy", state="complete", slot="ws1", live=False, base="")
        todo = fleet.ids["legacy"]
        code, _, err = self._switch(fleet)
        self.assertEqual(code, EXIT_REFUSED, err)
        self.assertNotIn("fleet reap --base `", err)
        self.assertIn("fleet reap --all", err)
        self.assertEqual(fleet.run(["close", "--id", todo])[0], EXIT_OK)
        self.assertEqual(fleet.run(["reap", "--all"])[0], EXIT_OK)
        code, _, err = self._switch(fleet)
        self.assertEqual(code, EXIT_OK, err)

    def test_control_an_open_live_record_blocks(self):
        fleet = self.fleet()
        fleet.worker("running", slot="ws1", pane=IDLE_PANE)
        code, _, err = self._switch(fleet)
        self.assertEqual(code, EXIT_REFUSED, err)
        self.assertIn("running", err)

    def test_a_running_inflight_record_names_abort_and_abort_clears_it(self):
        """RV-17. The route named for a LIVE -inflight- worker is FOLLOWED here: `close` alone left it blocking as
        resumable, so the route is `abort` (which asks the pane guard), and after it the switch runs."""
        fleet = self.fleet()
        path = fleet.worker("liveInflight", slot="ws1", pane=IDLE_PANE)
        code, _, err = self._switch(fleet)
        self.assertEqual(code, EXIT_REFUSED, err)
        self.assertIn(f"fleet abort --instant {path}", err)
        self.assertNotIn(f"`fleet close --id {fleet.ids['liveInflight']}` ends it", err)
        self.assertEqual(fleet.run(["abort", "--instant", str(path), "--reason", "switching"])[0], EXIT_OK)
        code, _, err = self._switch(fleet)
        self.assertEqual(code, EXIT_OK, f"the named route ran and the switch is still refused: {err}")

    def test_a_running_complete_record_names_close_then_reap_and_it_clears(self):
        """RV-17's neighbour: a live worker whose folder is already -complete-. `close` then `reap` is named, and
        followed, with no review."""
        fleet = self.fleet()
        fleet.worker("liveDone", state="complete", slot="ws1", pane=IDLE_PANE)
        todo = fleet.ids["liveDone"]
        code, _, err = self._switch(fleet)
        self.assertEqual(code, EXIT_REFUSED, err)
        self.assertIn(f"fleet close --id {todo}", err)
        self.assertIn("fleet reap --base", err)
        self.assertEqual(fleet.run(["close", "--id", todo])[0], EXIT_OK)
        self.assertEqual(fleet.run(["reap", "--base", OURS])[0], EXIT_OK)
        code, _, err = self._switch(fleet)
        self.assertEqual(code, EXIT_OK, f"the named route ran and the switch is still refused: {err}")

if __name__ == "__main__":
    unittest.main()
