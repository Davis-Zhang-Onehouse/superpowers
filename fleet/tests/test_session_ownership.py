"""`V23-T` (RV-S1 / S5-I1). When several records name one tmux session, the live session belongs to ONE of them.

A re-dispatch of a title reuses `dt-<name>` (`cli._dispatch_collision`), so the store holds pairs: the live store has
six (b01harvestreadsworkerroadmap-09220003/-09220005, v2stackcoordinator-07310334/-07310348, and four more). The join
used to hand the session to the first record by todo_id and then read EVERY other record naming it as live too, so
an older, harvested record read the new worker's pane: COMPLETE-BUT-WORKING (counted against the WIP cap while the
board, which shows slot holders only, hid it) or COMPLETE carrying the new worker's pid, which
`scripts/fleet-finished-pids.sh` turns into "exclude from auto-resume".

The rule (`reconcile.session_owner`, DECISIONS D-1/D-4): the record with the latest START owns the session. A start
is its `launched_at`, which every successful start stamps. A start still in progress (unstamped, never launched,
holding its own lease) counts by its `dispatched_at`. Any other never-launched record ranks below every start. No start
is attempted while a same-named session is live (dispatch refuses before its claim, `revive` refuses an occupied pane,
`resume` refuses a session an open record claims). Every other record reads exactly as if the session were gone.
"""
import pathlib
import shutil
import tempfile
import time
import unittest

from fleet.errors import BadInput
from fleet import guards as G
from fleet.pool import Pool
from fleet import reconcile as R
from fleet.reconcile import COMPLETE, COMPLETE_BUT_WORKING, DEAD, PENDING_LAUNCH, RUNNING, reconcile
from fleet.session import LiveSession, Probes, SessionLayer
from fleet.store import Declarations, Record, Store
from tests.test_cli import BUSY_PANE, IDLE_PANE, Fleet

BUSY = "\n".join(["reading src/fleet/pool.py", "Thinking...", "  esc to interrupt"])
QUIET = "\n".join(["compiled 42 files", "wrote target/fleet.jar", "done"])
WATCHED = "\n".join(["gh run watch 1234 --exit-status", "", "  auto mode on · 1 monitor · ? for shortcuts"])


def ts(off):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + off))


class Pair:
    """A private store holding records that all name `dt-mile` on server `here`, and at most one live session."""

    def __init__(self, test, socket="here"):
        self.root = pathlib.Path(tempfile.mkdtemp())
        test.addCleanup(shutil.rmtree, self.root, True)
        self.home, self.instants, self.slots = self.root / "home", self.root / "instants", self.root / "slots"
        self.instants.mkdir(parents=True)
        self.procs, self.panes, self.alive = [], {}, set()
        probes = Probes(list_processes=lambda: list(self.procs), capture_pane=lambda n: self.panes.get(n, ""),
                        has_session=lambda n: n in self.alive, start_session=lambda *a: None,
                        kill_session=lambda n: None)
        probes.socket = socket
        self.sessions = SessionLayer(probes)
        self.store = Store(self.home)
        self.pool = Pool(self.home, cwd_probe=lambda p: [], alive=self.sessions.alive)
        for slot in ("ws1", "ws2"):
            (self.slots / slot).mkdir(parents=True)
            self.pool.enroll(self.slots / slot)

    def record(self, stamp, folder_state, slot, *, launched_at, lease, harvested=False, closed=False,
               socket="here", declare=None):
        folder = self.instants / f"00000000-{stamp}-{folder_state}-append-mile"
        folder.mkdir()
        (folder / "HANDOFF.md").write_text("x\n")
        if declare is not None:
            declare(Declarations(folder))
        rec = Record(todo_id=f"mile-{stamp}", child_instant=str(folder), base_instant="B", slot=slot,
                     tmux="dt-mile", profile="/p", golden="/g", lineage_base="", title="mile",
                     dispatched_at=launched_at or ts(-300), launched_at=launched_at)
        rec.tmux_socket = socket
        if harvested:
            rec.harvested_at = rec.closed_at = ts(-8e5)
        elif closed:
            rec.closed_at = ts(-8e5)
        self.store.write(rec)
        if lease:
            self.pool.claim(todo_id=rec.todo_id, tmux="dt-mile", base_instant="B", child_instant=str(folder),
                            slot=slot)
        return rec

    def launch(self, slot, pane, pid=5151, nested_pid=6161):
        self.procs.append(LiveSession(pid=pid, cwd=self.slots / slot, name="dt-mile"))
        self.procs.append(LiveSession(pid=nested_pid, cwd=self.slots / slot, name="dt-mile", nested=True))
        self.panes["dt-mile"] = pane
        self.alive.add("dt-mile")

    def reconcile(self, **kw):
        return {s.identity: s for s in reconcile(self.store, self.pool, self.sessions, self.instants, **kw)
                if s.kind == "worker"}


def counted(subjects):
    return sorted(s.identity for s in subjects.values() if s.state not in G.CAP_EXCLUDED_STATES)


def _pidless_attestation(d):
    (d.dir).mkdir(parents=True, exist_ok=True)
    d.set_phase("awaiting-ci", now=ts(-9e5))
    d.set_watchers("attested: Monitor b1e6x9hs6 polls gh pr checks 521")


class TheLiveSessionBelongsToTheLatestLaunch(unittest.TestCase):

    def _harvested_old_and_live_new(self, pane, declare=None):
        pair = Pair(self)
        pair.record("08262300", "complete", "ws1", launched_at=ts(-9e5), lease=False, harvested=True,
                    declare=declare)
        pair.record("09251200", "inflight", "ws2", launched_at=ts(-590), lease=True)
        pair.launch("ws2", pane)
        return pair.reconcile()

    def test_a_harvested_record_with_a_pidless_attestation_does_not_read_the_new_workers_pane(self):
        """RV-S1's repro, the live-store shape (x2ansilinearstack-08262300 carries such an attestation)."""
        subs = self._harvested_old_and_live_new(QUIET, declare=_pidless_attestation)
        old, new = subs["mile-08262300"], subs["mile-09251200"]
        self.assertEqual(old.state, COMPLETE, old.note)
        self.assertEqual(counted(subs), ["mile-09251200"], "one worker, counted once")
        self.assertEqual(old.evidence["liveness"], "none")
        self.assertEqual(new.state, RUNNING)
        self.assertEqual(new.evidence["liveness"], "process", "the owner is spoken for by its own process")

    def test_a_busy_pane_is_the_owners_work_not_the_harvested_records(self):
        subs = self._harvested_old_and_live_new(BUSY)
        self.assertEqual(subs["mile-08262300"].state, COMPLETE)
        self.assertEqual(counted(subs), ["mile-09251200"])

    def test_the_loser_carries_neither_the_owners_pid_nor_its_nested_pids(self):
        """SI-41's hazard through the session name rather than the slot: `fleet-finished-pids.sh` maps COMPLETE ->
        exclude-from-auto-resume BY PID, so a COMPLETE row carrying 5151 switches auto-resume off for a live worker."""
        subs = self._harvested_old_and_live_new(QUIET)
        old, new = subs["mile-08262300"], subs["mile-09251200"]
        self.assertEqual((old.evidence["pid"], old.evidence["nested"]), ("", ""))
        self.assertEqual(old.evidence["pane"], "")
        self.assertEqual((new.evidence["pid"], new.evidence["nested"]), ("5151", "6161"))

    def test_two_inflight_records_on_one_session_are_one_live_worker(self):
        """Not in S5's single-record table: an older `-inflight-` record nobody aborted, and a re-dispatch of the same
        title. Both read RUNNING on one pane and both counted. The older reads as its session reads alone: gone."""
        pair = Pair(self)
        pair.record("08262300", "inflight", "ws1", launched_at=ts(-9e5), lease=True)
        pair.record("09251200", "inflight", "ws2", launched_at=ts(-590), lease=True)
        pair.launch("ws2", QUIET)
        subs = pair.reconcile()
        self.assertEqual(subs["mile-08262300"].state, DEAD)
        self.assertEqual(subs["mile-08262300"].evidence["liveness"], "none")
        self.assertEqual(subs["mile-09251200"].state, RUNNING)

    def test_launch_order_decides_not_todo_id_order(self):
        """A revived record keeps its session: revive stamps `launched_at` (cli.py `_do_revive`), so a record whose
        todo_id sorts LATER but launched EARLIER does not own a session its sibling started after it."""
        pair = Pair(self)
        pair.record("08262300", "inflight", "ws1", launched_at=ts(-60), lease=True)     # revived a minute ago
        pair.record("09251200", "complete", "ws2", launched_at=ts(-590), lease=False, harvested=True)
        pair.launch("ws1", BUSY)
        subs = pair.reconcile()
        self.assertEqual(subs["mile-08262300"].state, RUNNING)
        self.assertEqual(subs["mile-08262300"].evidence["pid"], "5151")
        self.assertEqual(subs["mile-09251200"].state, COMPLETE)
        self.assertEqual(subs["mile-09251200"].evidence["pid"], "")

    def test_a_record_that_never_launched_does_not_take_the_live_session(self):
        """i16liveinstructionandregistercontrol-08081303's shape: `launched_at` null, unstamped. A start refused on the
        duplicate name leaves exactly this beside the record whose session is live."""
        pair = Pair(self)
        pair.record("08262300", "inflight", "ws1", launched_at=ts(-9e5), lease=True)
        #: The rollback of a start tmux refused gives the lease back (cli `_do_dispatch`, `started` False).
        pair.record("09251200", "inflight", "ws2", launched_at=None, lease=False)
        pair.launch("ws1", QUIET)
        subs = pair.reconcile()
        self.assertEqual(subs["mile-08262300"].state, RUNNING)
        self.assertEqual(subs["mile-09251200"].state, PENDING_LAUNCH)
        self.assertEqual(subs["mile-09251200"].evidence["liveness"], "none")

    def test_a_start_in_progress_owns_the_session_it_just_started(self):
        """RV-32. Dispatch starts `dt-<name>`, delivers the seed, and only then stamps `launched_at`; for those seconds the
        new record is unlaunched but unstamped and HOLDS ITS LEASE. It is the latest start, so it owns the session, and
        the dead record it replaces reads as gone rather than as RUNNING on the new worker's pid."""
        pair = Pair(self)
        pair.record("08262300", "inflight", "ws1", launched_at=ts(-9e5), lease=True)       # died, never closed
        pair.record("09251200", "inflight", "ws2", launched_at=None, lease=True)           # starting now
        pair.launch("ws2", QUIET)
        subs = pair.reconcile()
        old = subs["mile-08262300"]
        self.assertEqual((old.state, old.evidence["liveness"], old.evidence["pid"]), (DEAD, "none", ""))
        self.assertNotEqual(subs["mile-09251200"].evidence["liveness"], "none")

    def test_a_stamped_record_that_never_launched_does_not_own_the_session(self):
        """Neighbour: `close` stamped a never-launched record whose lease it did not release. Its start is over."""
        pair = Pair(self)
        pair.record("08262300", "inflight", "ws1", launched_at=ts(-9e5), lease=True)
        pair.record("09251200", "inflight", "ws2", launched_at=None, lease=True, closed=True)
        pair.launch("ws1", QUIET)
        subs = pair.reconcile()
        self.assertEqual(subs["mile-08262300"].state, RUNNING)
        self.assertEqual(subs["mile-09251200"].evidence["liveness"], "none")

    def test_a_stamped_record_alone_still_reads_its_live_session(self):
        """Control: with no sibling, a harvested record whose session survived still reads live (RV-C1 kept)."""
        pair = Pair(self)
        pair.record("08262300", "complete", "ws1", launched_at=ts(-9e5), lease=False, harvested=True)
        pair.launch("ws1", BUSY)
        subs = pair.reconcile()
        self.assertEqual(subs["mile-08262300"].state, COMPLETE_BUT_WORKING)
        self.assertEqual(subs["mile-08262300"].evidence["pid"], "5151")

    def test_records_on_another_server_are_owned_on_that_server(self):
        """Pass 2 asks a foreign record's OWN server (`layer_for`); ownership is per (server, name) there too."""
        pair = Pair(self, socket="here")
        pair.record("08262300", "complete", "ws1", launched_at=ts(-9e5), lease=False, harvested=True,
                    socket="other", declare=_pidless_attestation)
        pair.record("09251200", "inflight", "ws2", launched_at=ts(-590), lease=True, socket="other")
        other_alive = {"dt-mile"}
        other = SessionLayer(Probes(list_processes=lambda: [], capture_pane=lambda n: QUIET,
                                    has_session=lambda n: n in other_alive, start_session=lambda *a: None,
                                    kill_session=lambda n: None, socket="other"))
        subs = pair.reconcile(layer_for=lambda s: other)
        self.assertEqual(subs["mile-08262300"].state, COMPLETE, subs["mile-08262300"].note)
        self.assertEqual(subs["mile-08262300"].evidence["liveness"], "none")
        self.assertEqual(subs["mile-09251200"].evidence["liveness"], "session")

    def test_a_same_named_session_on_another_server_is_not_contested(self):
        """The key is (server, name): a record on `other` does not compete for `here`'s dt-mile."""
        pair = Pair(self, socket="here")
        pair.record("08262300", "inflight", "ws1", launched_at=ts(-9e5), lease=True, socket="here")
        pair.record("09251200", "inflight", "ws2", launched_at=ts(-590), lease=True, socket="other")
        pair.launch("ws1", QUIET)
        other = SessionLayer(Probes(list_processes=lambda: [], capture_pane=lambda n: "",
                                    has_session=lambda n: False, start_session=lambda *a: None,
                                    kill_session=lambda n: None, socket="other"))
        subs = pair.reconcile(layer_for=lambda s: other)
        self.assertEqual(subs["mile-08262300"].state, RUNNING)
        self.assertEqual(subs["mile-08262300"].evidence["pid"], "5151")


class TheOwnerRule(unittest.TestCase):
    """`session_owner` itself: the rule D-1 records, over records only (no probes)."""

    def _rec(self, tid, launched_at, *, socket="here", harvested=False):
        rec = Record(todo_id=tid, child_instant="/i/x", base_instant="B", slot="", tmux="dt-mile", profile="/p",
                     golden="/g", lineage_base="", title="mile", dispatched_at="2026-01-01T00:00:00Z",
                     launched_at=launched_at)
        rec.tmux_socket = socket
        if harvested:
            rec.harvested_at = "2026-09-01T00:00:00Z"
        return rec

    def test_latest_launch_wins_whatever_the_stamps(self):
        old = self._rec("mile-01", "2026-09-22T00:03:33Z")
        new = self._rec("mile-02", "2026-09-22T00:05:06Z", harvested=True)
        self.assertIs(R.session_owner([old, new], "here")[("here", "dt-mile")], new)

    def test_a_launched_record_outranks_one_never_launched(self):
        old = self._rec("mile-01", "2026-08-08T13:05:42Z")
        pending = self._rec("mile-02", None)
        self.assertIs(R.session_owner([pending, old], "here")[("here", "dt-mile")], old)

    def test_a_start_in_progress_ranks_by_its_dispatch(self):
        """RV-32. An unstamped, never-launched record that still holds its lease is a start in progress (or one whose
        rollback kill failed): it ranks by `dispatched_at`. Without its lease it was rolled back and ranks below all."""
        from fleet.pool import Pool
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        pool = Pool(tmp / "home", cwd_probe=lambda p: [], alive=lambda n: False)
        (tmp / "ws2").mkdir()
        pool.enroll(tmp / "ws2")
        old = self._rec("mile-01", "2026-09-22T00:03:33Z")
        new = self._rec("mile-02", None)
        new.slot, new.dispatched_at = "ws2", "2026-09-22T00:05:00Z"
        self.assertIs(R.session_owner([old, new], "here", pool)[("here", "dt-mile")], old, "no lease: rolled back")
        pool.claim(todo_id="mile-02", tmux="dt-mile", base_instant="B", child_instant="/i/x", slot="ws2")
        self.assertIs(R.session_owner([old, new], "here", pool)[("here", "dt-mile")], new, "lease held: starting")
        new.dispatched_at = "2026-09-22T00:03:00Z"
        self.assertIs(R.session_owner([old, new], "here", pool)[("here", "dt-mile")], old,
                      "a start dispatched before the rival's launch cannot own what the rival started later")
        new.dispatched_at = "2026-09-22T00:05:00Z"
        pool.release("ws2", force=True)
        pool.claim(todo_id="someone-else", tmux="dt-other", base_instant="B", child_instant="/i/y", slot="ws2")
        self.assertIs(R.session_owner([old, new], "here", pool)[("here", "dt-mile")], old,
                      "the slot it names is leased to another record: its own start is not in progress")

    def test_on_a_tie_the_unstamped_record_wins(self):
        a = self._rec("mile-02", "2026-09-22T00:05:06Z", harvested=True)
        b = self._rec("mile-01", "2026-09-22T00:05:06Z")
        self.assertIs(R.session_owner([a, b], "here")[("here", "dt-mile")], b)

    def test_a_record_naming_no_server_is_keyed_on_the_server_in_hand(self):
        """An empty `tmux_socket` is NOT MEASURED; the join already treats it as local (pass 1), so ownership does."""
        legacy = self._rec("mile-01", "2026-09-22T00:05:06Z", socket="")
        self.assertIs(R.session_owner([legacy], "here")[("here", "dt-mile")], legacy)


class TheTeardownVerbsLeaveASessionThatIsNotTheirs(unittest.TestCase):
    """The same missing rule on the KILL side (evidence/02-kill-verbs, measured at base ab2225b3): `close`, `harvest`
    and `abort` aimed at the OLD record called `kill(dt-<name>)` and ended the NEW worker's session, rc=0, whenever
    its pane was quiet, and whatever the pane showed under `--force`. Nothing asked whose session it was; the only
    thing that stopped it was the busy-pane guard, which is a judgement about a pane, not about ownership."""

    def _pair(self, old_state, *, old_closed=True, old_harvested=False, pane=None, reviewed=False):
        fleet = Fleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        old = fleet.worker("mile", state=old_state, live=False)
        old_id = fleet.ids["mile"]
        rec = fleet.store.read(old_id)
        rec.launched_at, rec.dispatched_at = "2026-07-29T09:00:00Z", "2026-07-29T09:00:00Z"
        if old_closed:
            rec.closed_at = "2026-07-29T10:00:00Z"
        if old_harvested:
            rec.harvested_at = "2026-07-29T10:00:00Z"
        fleet.store.write(rec)
        if reviewed:
            fleet.reviewed(old)
        fleet.worker("mile", slot="ws2", pane=pane if pane is not None else IDLE_PANE)   # the re-dispatch, live
        return fleet, old, old_id

    def _assert_left_alone(self, fleet, code, out, err):
        self.assertNotIn("dt-mile", fleet.killed, f"rc={code}\n{out}\n{err}")
        self.assertIn("dt-mile", fleet.tmux_live)

    def test_close_of_the_old_record_does_not_kill_the_new_workers_quiet_session(self):
        fleet, _, old_id = self._pair("abort")
        code, out, err = fleet.run(["close", "--id", old_id])
        self._assert_left_alone(fleet, code, out, err)
        self.assertEqual(code, 0, err)
        self.assertTrue(fleet.store.read(old_id).closed_at, "the old record is still stamped")

    def test_close_force_of_the_old_record_does_not_kill_a_busy_session_either(self):
        fleet, _, old_id = self._pair("abort", pane=BUSY_PANE)
        code, out, err = fleet.run(["close", "--id", old_id, "--force"])
        self._assert_left_alone(fleet, code, out, err)

    def test_close_does_not_refuse_the_old_record_over_the_new_workers_busy_pane(self):
        """The pane guard judges THIS record's pane. The old record has none: its session is the new worker's."""
        fleet, _, old_id = self._pair("abort", pane=BUSY_PANE)
        code, out, err = fleet.run(["close", "--id", old_id])
        self.assertEqual(code, 0, f"{out}\n{err}")
        self._assert_left_alone(fleet, code, out, err)

    def test_close_dry_run_says_it_would_not_close_the_session_and_whose_it_is(self):
        fleet, _, old_id = self._pair("abort")
        code, out, err = fleet.run(["close", "--dry-run", "--id", old_id])
        self.assertEqual(code, 0, err)
        self.assertIn(fleet.ids["mile"], out, "the row names the record that owns the session")
        self.assertNotIn("would-close  true", out)

    def test_harvest_of_the_old_record_does_not_kill_the_new_workers_session(self):
        fleet, _, old_id = self._pair("complete", old_closed=False, reviewed=True)
        code, out, err = fleet.run(["harvest", "--id", old_id])
        self._assert_left_alone(fleet, code, out, err)
        self.assertEqual(code, 0, err)
        self.assertTrue(fleet.store.read(old_id).harvested_at)

    def test_harvest_force_of_the_old_record_does_not_kill_the_new_workers_session(self):
        fleet, _, old_id = self._pair("complete", old_closed=False, reviewed=True)
        code, out, err = fleet.run(["harvest", "--id", old_id, "--force"])
        self._assert_left_alone(fleet, code, out, err)

    def test_abort_of_an_old_inflight_folder_does_not_kill_the_new_workers_session(self):
        fleet, old, _ = self._pair("inflight")
        code, out, err = fleet.run(["abort", "--instant", str(old), "--reason", "superseded by the re-dispatch"])
        self._assert_left_alone(fleet, code, out, err)
        self.assertEqual(code, 0, err)

    def test_harvest_is_not_refused_over_the_new_workers_busy_pane(self):
        """`_refuse_a_guarded_pane` (FB-88) judges the pane the verb would END; this verb ends none."""
        fleet, _, old_id = self._pair("complete", old_closed=False, reviewed=True, pane=BUSY_PANE)
        code, out, err = fleet.run(["harvest", "--id", old_id])
        self.assertEqual(code, 0, f"{out}\n{err}")
        self._assert_left_alone(fleet, code, out, err)

    def test_harvest_dry_run_says_it_would_leave_the_session_and_whose_it_is(self):
        fleet, _, old_id = self._pair("complete", old_closed=False, reviewed=True)
        code, out, err = fleet.run(["harvest", "--dry-run", "--id", old_id])
        self.assertEqual(code, 0, err)
        self.assertIn(f"leave dt-mile running (it is {fleet.ids['mile']}'s)", out)
        self.assertNotIn("close dt-mile", out)

    def test_abort_dry_run_says_it_would_not_close_the_session(self):
        fleet, old, _ = self._pair("inflight")
        code, out, err = fleet.run(["abort", "--dry-run", "--instant", str(old), "--reason", "superseded"])
        self.assertEqual(code, 0, err)
        self.assertIn(f"no — left dt-mile running: it belongs to {fleet.ids['mile']}", out)

    def test_close_is_not_refused_as_live_complete_work_over_the_new_workers_pane(self):
        """`_refuse_live_complete_watcher` is the board's predicate (`complete_work_is_live`) and must read the board's
        liveness: the harvested record's pid-less attestation is not live work once the session is not its own. At
        base it read the NEW worker's pane and refused `close` of a record the board shows COMPLETE."""
        fleet, old, old_id = self._pair("complete", old_harvested=True)
        d = Declarations(old)
        d.set_phase("awaiting-ci", now="2026-07-29T09:30:00Z")
        d.set_watchers("attested: Monitor b1e6x9hs6 polls gh pr checks 521")
        code, out, err = fleet.run(["close", "--id", old_id])
        self.assertEqual(code, 0, f"{out}\n{err}")
        self._assert_left_alone(fleet, code, out, err)

    def test_close_of_a_dead_record_does_not_kill_a_re_dispatch_that_is_still_starting(self):
        """RV-32 at the verb: B's dispatch has started `dt-mile` and holds ws2, but has not stamped `launched_at` yet."""
        fleet, _, old_id = self._pair("inflight", old_closed=False)
        rec = fleet.store.read(fleet.ids["mile"])
        rec.launched_at = None
        fleet.store.write(rec)
        code, out, err = fleet.run(["close", "--id", old_id, "--force"])
        self._assert_left_alone(fleet, code, out, err)

    def test_abort_is_refused_before_anything_when_a_holder_stays_in_the_old_slot(self):
        """RV-34. `_slot_gate_before_kill` read the owner's session as the old record's, so a holder in the old slot
        was judged against B's pane, and could pass as undecided when that pane's pids were unreadable. The abort then
        wrote its reason, killed nothing (the session is B's) and the release refused: the partial state the pre-kill
        gate exists to prevent. The old record's session is gone, so nothing this abort closes frees the slot."""
        fleet = Fleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        old = fleet.worker("mile", slot="ws1", live=False)
        rec = fleet.store.read(fleet.ids["mile"])
        rec.launched_at = "2026-07-29T09:00:00Z"
        fleet.store.write(rec)
        fleet.worker("mile", slot="ws2", pane=IDLE_PANE)
        fleet.hold_slot_cwd("ws1", 777)
        fleet.sessions.probes.pane_pid = lambda name: None          # the owner's pane pids cannot be read
        code, out, err = fleet.run(["abort", "--instant", str(old), "--reason", "superseded", "--force"])
        self.assertNotEqual(code, 0, out)
        self.assertTrue(old.exists(), "nothing was renamed")
        self.assertFalse((old / ".fleet" / "abort.json").exists(), "nothing was written")
        #: OR-2 (v23-t close review). `dt-mile` IS running — it is the re-dispatch's; the refusal said "is not running".
        owner = fleet.ids["mile"]
        self.assertIn(f"Session dt-mile is running but belongs to {owner}", err)
        self.assertIn(f"session dt-mile still running (owned by {owner}, left alone)", err)
        self.assertNotIn("is not running", err)
        self.assertNotIn("dt-mile not running", err)

    def test_the_left_running_note_reads_an_owner_that_is_still_starting(self):
        """RV-41 (closure 1). Under D-4 the owner may not have launched yet; the note said `launched None`."""
        fleet, _, old_id = self._pair("inflight", old_closed=False)
        rec = fleet.store.read(fleet.ids["mile"])
        rec.launched_at = None
        fleet.store.write(rec)
        code, out, err = fleet.run(["close", "--id", old_id, "--force"])
        self.assertNotIn("launched None", out + err)
        self.assertIn(f"starting, dispatched {rec.dispatched_at}", out + err)

    def test_close_of_the_owner_still_kills_its_own_session(self):
        """Control: the rule removes a kill only from a record that does not own the session."""
        fleet, _, _ = self._pair("abort")
        code, out, err = fleet.run(["close", "--id", fleet.ids["mile"], "--force"])
        self.assertEqual(code, 0, err)
        self.assertIn("dt-mile", fleet.killed)

    def test_close_of_a_lone_stamped_record_still_kills_its_surviving_session(self):
        """Control: with no sibling, a closed record whose session survived is still closable (idempotent close)."""
        fleet = Fleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        fleet.worker("lone", state="abort", pane=IDLE_PANE)
        rec = fleet.store.read(fleet.ids["lone"])
        rec.closed_at = "2026-07-29T10:00:00Z"
        fleet.store.write(rec)
        code, out, err = fleet.run(["close", "--id", fleet.ids["lone"]])
        self.assertEqual(code, 0, err)
        self.assertIn("dt-lone", fleet.killed)



class ReapAsksWhoseSessionALeaseNames(unittest.TestCase):
    """v23-t OR-3. `reap` judged a lease live by its session NAME alone, so an old, dead record's lease on ws1 read "its
    worker is still running" through the re-dispatch's live `dt-mile` on ws2 and was never freed while that ran."""

    def _dead_old_and_live_new(self):
        from tests.test_cli import OURS
        fleet = Fleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        fleet.worker("mile", slot="ws1", live=False)                        # A: open, DEAD, still leased
        rec = fleet.store.read(fleet.ids["mile"])
        old_id = rec.todo_id
        rec.launched_at = rec.dispatched_at = "2026-07-29T09:00:00Z"
        fleet.store.write(rec)
        fleet.worker("mile", slot="ws2", pane=IDLE_PANE)                    # B: the re-dispatch, live in dt-mile
        return fleet, old_id, OURS

    def test_reap_frees_the_dead_records_lease_and_keeps_the_owners(self):
        fleet, old_id, ours = self._dead_old_and_live_new()
        code, out, err = fleet.run(["reap", "--base", ours])
        self.assertEqual(code, 0, f"{out}\n{err}")
        self.assertIsNone(fleet.pool.lease("ws1"), f"A's lease read live through B's session\n{out}")
        self.assertEqual(fleet.pool.lease("ws2").todo_id, fleet.ids["mile"], "B's own lease is still live")
        self.assertIn("dt-mile", fleet.tmux_live)

    def test_the_dry_run_says_the_same(self):
        fleet, old_id, ours = self._dead_old_and_live_new()
        code, out, err = fleet.run(["reap", "--dry-run", "--base", ours])
        self.assertEqual(code, 0, f"{out}\n{err}")
        self.assertRegex(out, rf"ws1 .*leased to {old_id} .*a real reap frees it")
        self.assertRegex(out, rf"ws2 .*leased to {fleet.ids['mile']} .*its session is alive")


class ResumeDoesNotAdoptASessionAnotherRecordOwns(unittest.TestCase):
    """RV-21. `resume` stamps `launched_at=now` when the session it names is alive, which is how D-1 reads "this record
    started it". Resuming an OLD folder whose `dt-<name>` is a re-dispatch's live session therefore handed that session
    to the old record (and rebuilt the harvested record as open, evidence/02-kill-verbs/revive_resume_probe.out). The
    adoption is refused, naming the owner; resuming the owner is the recovery path and stays open (FD-9)."""

    def _pair(self, old_state="complete"):
        fleet = Fleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        old = fleet.worker("mile", state=old_state, live=False)
        old_id = fleet.ids["mile"]
        rec = fleet.store.read(old_id)
        rec.launched_at = "2026-07-29T09:00:00Z"
        rec.harvested_at = rec.closed_at = "2026-07-29T10:00:00Z"
        fleet.store.write(rec)
        new = fleet.worker("mile", slot="ws2", pane=IDLE_PANE)
        return fleet, old, old_id, new

    def test_resuming_the_old_folder_is_refused_and_writes_nothing(self):
        fleet, old, old_id, _ = self._pair()
        before = fleet.record_state()
        code, out, err = fleet.run(["resume", "--instant", str(old)])
        self.assertNotEqual(code, 0, out)
        self.assertIn(fleet.ids["mile"], err, "the refusal names the record that owns the session")
        self.assertEqual(fleet.record_state(), before, "no record was rewritten")
        self.assertTrue(fleet.store.read(old_id).harvested_at)

    def test_the_dry_run_answers_as_the_real_call_does(self):
        fleet, old, _, _ = self._pair()
        code, out, err = fleet.run(["resume", "--dry-run", "--instant", str(old)])
        self.assertNotEqual(code, 0, out)

    def test_an_unrecorded_folder_with_the_same_name_does_not_adopt_it_either(self):
        """Neighbour: no record of its own, the same `dt-<name>` by derivation."""
        fleet, _, _, _ = self._pair()
        orphan = fleet.orphan("mile")
        code, out, err = fleet.run(["resume", "--instant", str(orphan)])
        self.assertNotEqual(code, 0, out)

    def test_a_harvested_record_does_not_block_adopting_a_live_orphan(self):
        """RV-39 (closure 1). The refusal is for a LIVE claimant. A harvested record of the same title is over; the live
        `dt-mile` is the orphan folder's, which is exactly what resume exists to adopt (FD-9)."""
        fleet = Fleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        fleet.worker("mile", state="complete", live=False)
        rec = fleet.store.read(fleet.ids["mile"])
        rec.launched_at = "2026-07-29T09:00:00Z"
        rec.harvested_at = rec.closed_at = "2026-07-29T10:00:00Z"
        fleet.store.write(rec)
        orphan = fleet.orphan("mile")
        fleet.procs.append(LiveSession(pid=4242, cwd=orphan, name="dt-mile"))
        fleet.panes["dt-mile"] = IDLE_PANE
        fleet.tmux_live.add("dt-mile")
        code, out, err = fleet.run(["resume", "--instant", str(orphan)])
        self.assertEqual(code, 0, f"{out}{err}")

    def test_a_closed_only_record_does_not_block_adopting_a_live_orphan(self):
        """RV-46. The guard's closed half on its own: `fleet close` stamps `closed_at` and not `harvested_at`."""
        fleet = Fleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        fleet.worker("mile", state="complete", live=False)
        rec = fleet.store.read(fleet.ids["mile"])
        rec.launched_at = "2026-07-29T09:00:00Z"
        rec.closed_at = "2026-07-29T10:00:00Z"
        fleet.store.write(rec)
        orphan = fleet.orphan("mile")
        fleet.procs.append(LiveSession(pid=4242, cwd=orphan, name="dt-mile"))
        fleet.panes["dt-mile"] = IDLE_PANE
        fleet.tmux_live.add("dt-mile")
        code, out, err = fleet.run(["resume", "--instant", str(orphan)])
        self.assertEqual(code, 0, f"{out}{err}")

    def test_resuming_the_owner_still_adopts_its_session(self):
        """Control: the refusal is about another record's session, not about a live one."""
        fleet, _, _, new = self._pair()
        code, out, err = fleet.run(["resume", "--instant", str(new)])
        self.assertEqual(code, 0, err)


class SeedCheckAsksEachRecordOfItsOwnSession(unittest.TestCase):

    def test_a_dead_unstamped_record_is_not_checked_against_the_re_dispatchs_pane(self):
        """RV-33. seed-check skipped only stamped records, so a dead, never-closed record A was compared (seed, pid,
        argv) with the pane of B, the re-dispatch that owns `dt-mile`: a false FOREIGN verdict, or A's own delivery
        reported VERIFIED on B's pid. Here neither folder holds a seed, so each record it reads yields a row naming its
        own seed path, and A's must not appear."""
        fleet = Fleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        old = fleet.worker("mile", slot="ws1", live=False)
        rec = fleet.store.read(fleet.ids["mile"])
        rec.launched_at = "2026-07-29T09:00:00Z"
        fleet.store.write(rec)
        new = fleet.worker("mile", slot="ws2", pane=IDLE_PANE)
        code, out, err = fleet.run(["seed-check", "--porcelain"])
        self.assertNotIn(old.name, out + err, "the old record was checked against a session it does not own")
        self.assertIn(new.name, out + err, "the owner is still checked (the case is not vacuous)")


class EveryPerRecordReaderAsksWhoseSessionItIs(unittest.TestCase):
    """RV-35. Three more readers asked `alive(record.tmux)` of one record: the runtime-switch blocker, the watcher a
    `declare --phase awaiting-ci` records as observed, and `complete`'s awaiting-ci refusal. For a dead record whose
    `dt-<name>` a re-dispatch holds, each read the re-dispatch's session as the record's own."""

    def _pair(self, pane=IDLE_PANE):
        fleet = Fleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        old = fleet.worker("mile", slot="ws1", live=False)
        rec = fleet.store.read(fleet.ids["mile"])
        rec.launched_at = "2026-07-29T09:00:00Z"
        fleet.store.write(rec)
        old_id = fleet.ids["mile"]
        fleet.worker("mile", slot="ws2", pane=pane)
        return fleet, old, old_id

    def test_the_runtime_blocker_does_not_call_the_dead_record_running(self):
        fleet, _, old_id = self._pair()
        code, out, err = fleet.run(["runtime", "--set", "codex"])
        self.assertNotIn(f"running record {old_id}", out + err)
        self.assertIn(f"record {old_id} can still be resumed", out + err, "it is still named, truthfully")

    def test_a_claim_on_the_old_folder_does_not_record_the_new_workers_monitor(self):
        watched = "\n".join(["gh run watch 1234 --exit-status", "", "  auto mode on · 1 monitor · ? for shortcuts"])
        fleet, old, _ = self._pair(pane=watched)
        code, out, err = fleet.run(["declare", "--instant", str(old), "--phase", "awaiting-ci"])
        self.assertFalse(Declarations(old).watchers(), f"the re-dispatch's Monitor became this claim's watcher: {out}")

    def test_complete_does_not_describe_the_new_workers_watcher_as_this_instants(self):
        watched = "\n".join(["gh run watch 1234 --exit-status", "", "  auto mode on · 1 monitor · ? for shortcuts"])
        fleet, old, _ = self._pair(pane=watched)
        d = Declarations(old)
        d.set_phase("awaiting-ci", now="2026-07-29T09:30:00Z")
        code, out, err = fleet.run(["complete", "--instant", str(old)])
        self.assertNotEqual(code, 0)
        self.assertNotIn("with a live watcher", out + err)


class AnExecutedReviveOwnsItsSession(unittest.TestCase):

    def test_revive_makes_the_revived_record_the_owner(self):
        """RV-24. D-1 says a revived record keeps its session because `revive` stamps `launched_at`. Executed, not
        hand-set: A (`recoverable`, ws7) launched at 11.00; B, a later dispatch of the same title, launched at 11.30 and
        was harvested. B owns `dt-recoverable` until A is revived at NOW (12.00); then A does."""
        fleet = Fleet(slots=8)
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        args = fleet.revival_fixture()
        a_id = fleet.ids["recoverable"]
        rec = fleet.store.read(a_id)
        rec.launched_at = "2026-07-30T11:00:00Z"
        fleet.store.write(rec)
        fleet.worker("recoverable", state="complete", live=False)
        b = fleet.store.read(fleet.ids["recoverable"])
        b.launched_at = "2026-07-30T11:30:00Z"
        b.harvested_at = b.closed_at = "2026-07-30T11:45:00Z"
        fleet.store.write(b)
        self.assertEqual(R.session_owner(fleet.store.all(), fleet.socket)[(fleet.socket, "dt-recoverable")].todo_id,
                      b.todo_id, "precondition: before the revive the later launch owns the name")
        code, out, err = fleet.run(["revive", *args])
        self.assertEqual(code, 0, err)
        self.assertEqual([name for name, _, _ in fleet.started], ["dt-recoverable"])
        fleet.tmux_live.add("dt-recoverable")                       # what the real start leaves behind
        fleet.panes["dt-recoverable"] = IDLE_PANE
        code, out, err = fleet.run(["status", "--id", a_id, "--porcelain"])
        self.assertIn("evidence.liveness\tsession", out)
        code, out, err = fleet.run(["status", "--id", b.todo_id, "--porcelain"])
        self.assertIn("evidence.liveness\tnone", out)

    def _older_revivable_and_later_harvested(self, verified=True):
        """RV-24's pair: A (ws7, launched 11.00, holds its lease, DEAD) and B, a later dispatch of the same title
        (launched 11.30, harvested). `verified` is what revive's verification answers."""
        fleet = Fleet(slots=8)
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        args = fleet.revival_fixture()
        a_id = fleet.ids["recoverable"]
        rec = fleet.store.read(a_id)
        rec.launched_at = "2026-07-30T11:00:00Z"
        fleet.store.write(rec)
        fleet.worker("recoverable", state="complete", live=False)
        b = fleet.store.read(fleet.ids["recoverable"])
        b.launched_at = "2026-07-30T11:30:00Z"
        b.harvested_at = b.closed_at = "2026-07-30T11:45:00Z"
        fleet.store.write(b)
        original = fleet.context

        def context():
            build = original()

            def with_verdict(parsed, out, err):
                ctx = build(parsed, out, err)
                ctx.resume_verified = lambda record, session_id: verified
                return ctx
            return with_verdict
        fleet.context = context
        return fleet, args, a_id, b.todo_id

    def _owner(self, fleet):
        return R.session_owner(fleet.store.all(), fleet.socket, fleet.pool)[(fleet.socket, "dt-recoverable")].todo_id

    def _the_started_session_comes_up_busy(self, fleet):
        """What the real start leaves behind: a live session with a working agent in A's slot."""
        fleet.tmux_live.add("dt-recoverable")
        fleet.panes["dt-recoverable"] = BUSY_PANE
        fleet.procs.append(LiveSession(pid=5151, cwd=fleet.pool.slot_path("ws7"), name="dt-recoverable"))

    def test_the_revived_record_owns_its_session_from_the_moment_it_starts(self):
        """OR-1 (v23-t close review). Revive stamped `launched_at` only after its verify, so from `layer.start` until
        then A ranked by its OLD launch and the harvested B owned the session A had just started."""
        fleet, args, a_id, b_id = self._older_revivable_and_later_harvested()
        during = []
        original_start = fleet.sessions.probes.start_session
        fleet.sessions.probes.start_session = lambda name, cwd, cmd: (original_start(name, cwd, cmd),
                                                                      during.append(self._owner(fleet)))
        code, out, err = fleet.run(["revive", *args])
        self.assertEqual(code, 0, err)
        self.assertEqual(during, [a_id], "while the session starts it is the revived record's")
        self.assertEqual(self._owner(fleet), a_id, "and after the revive too")

    def test_a_revive_whose_verify_fails_still_owns_the_session_it_started(self):
        """OR-1. The verify failed, the session was left running and the lease retained — the session is A's. Before
        the fix the stamp was never written, so B (harvested) read COMPLETE-BUT-WORKING on A's pid and A UNREACHABLE."""
        fleet, args, a_id, b_id = self._older_revivable_and_later_harvested(verified=False)
        code, out, err = fleet.run(["revive", *args])
        self.assertNotEqual(code, 0, f"{out}{err}")
        self.assertIn("Resume not verified", err)
        self.assertEqual([name for name, _, _ in fleet.started], ["dt-recoverable"])
        self._the_started_session_comes_up_busy(fleet)
        self.assertEqual(self._owner(fleet), a_id)
        code, out, err = fleet.run(["status", "--id", a_id, "--porcelain"])
        self.assertIn("evidence.liveness\tprocess", out)
        code, out, err = fleet.run(["status", "--id", b_id, "--porcelain"])
        self.assertIn("evidence.liveness\tnone", out)
        self.assertNotIn(COMPLETE_BUT_WORKING, out)

    def test_a_revive_that_tmux_refuses_to_start_claims_no_session(self):
        """OR-1's rollback. The start is recorded before `layer.start`; when tmux refuses the start, the record goes
        back to its old launch, so it does not claim a session it does not have."""
        fleet, args, a_id, b_id = self._older_revivable_and_later_harvested()

        def refused(name, cwd, cmd):
            raise BadInput("tmux refused to start 'dt-recoverable': duplicate session: dt-recoverable")
        fleet.sessions.probes.start_session = refused
        code, out, err = fleet.run(["revive", *args])
        self.assertNotEqual(code, 0, f"{out}{err}")
        self.assertEqual(fleet.store.read(a_id).launched_at, "2026-07-30T11:00:00Z")
        self.assertEqual(self._owner(fleet), b_id, "the later launch still owns the name nobody started")


class DispatchDoesNotStartOverALiveSessionOfTheSameName(unittest.TestCase):
    """RV-40. Dispatch claimed its lease and wrote its record BEFORE `sessions.start`, and only tmux's duplicate-name
    refusal stopped a same-title dispatch while `dt-<name>` was live. Until the rollback ran (forever, if the dispatch
    died first or its release was refused) the new record was unlaunched, unstamped and held its own lease: exactly
    what D-4 reads as a start in progress, so it outranked the live worker and `abort` of it killed that worker. The
    dispatch now refuses before the claim, as SI-20 does, so that shape is never written."""

    def test_a_dispatch_is_refused_before_the_claim_while_the_session_name_is_live(self):
        fleet = Fleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        fleet.worker("mile", state="complete", pane=IDLE_PANE)             # its session survived the harvest
        rec = fleet.store.read(fleet.ids["mile"])
        rec.harvested_at = rec.closed_at = "2026-07-30T11:00:00Z"
        fleet.store.write(rec)
        before_records, before_leases = fleet.record_state(), fleet.pool_state()
        code, out, err = fleet.run(["dispatch", "--profile", str(fleet.profile("worker")), "--title", "mile",
                                    "--base", "00000000"])
        self.assertEqual(code, 4, f"{out}{err}")
        self.assertIn("dt-mile", err)
        self.assertEqual(fleet.record_state(), before_records, "no record was written")
        self.assertEqual(fleet.pool_state(), before_leases, "no lease was claimed")
        self.assertEqual((fleet.started, fleet.killed), ([], []), "no session was started or killed")

    def test_the_dry_run_refuses_the_same_way(self):
        fleet = Fleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        fleet.worker("mile", state="complete", pane=IDLE_PANE)
        rec = fleet.store.read(fleet.ids["mile"])
        rec.harvested_at = rec.closed_at = "2026-07-30T11:00:00Z"
        fleet.store.write(rec)
        code, out, err = fleet.run(["dispatch", "--dry-run", "--profile", str(fleet.profile("worker")),
                                    "--title", "mile", "--base", "00000000"])
        self.assertEqual(code, 4, f"{out}{err}")

    def test_the_refusal_names_an_open_launched_owner_and_how_to_end_it(self):
        """RV-47. The RV-40 scenario itself: the live `dt-mile` is an OPEN, launched worker's."""
        fleet = Fleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        fleet.worker("mile", slot="ws1", pane=IDLE_PANE)
        owner = fleet.ids["mile"]
        before_records, before_leases = fleet.record_state(), fleet.pool_state()
        code, out, err = fleet.run(["dispatch", "--profile", str(fleet.profile("worker")), "--title", "mile",
                                    "--base", "00000000"])
        self.assertEqual(code, 4, f"{out}{err}")
        self.assertIn(f"session dt-mile is live on this server and belongs to record {owner}", err)
        self.assertIn(f"fleet close --id {owner}", err)
        self.assertEqual((fleet.record_state(), fleet.pool_state()), (before_records, before_leases))
        self.assertEqual((fleet.started, fleet.killed), ([], []))

    def test_the_refusal_names_an_unrecorded_live_session(self):
        """RV-47. A live `dt-mile` no record claims: the refusal says so and routes to the title, not to `close`."""
        fleet = Fleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        fleet.tmux_live.add("dt-mile")
        code, out, err = fleet.run(["dispatch", "--profile", str(fleet.profile("worker")), "--title", "mile",
                                    "--base", "00000000"])
        self.assertEqual(code, 4, f"{out}{err}")
        self.assertIn("belongs to no record in this store (an unrecorded session)", err)
        self.assertIn("dt-mile is gone, or the title differs", err)
        self.assertNotIn("fleet close --id", err)
        self.assertEqual((fleet.started, fleet.killed), ([], []))

    def test_a_dispatch_whose_session_name_is_free_still_starts(self):
        """Neighbour: the same harvested record, its session gone."""
        fleet = Fleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        fleet.worker("mile", state="complete", live=False)
        rec = fleet.store.read(fleet.ids["mile"])
        rec.harvested_at = rec.closed_at = "2026-07-30T11:00:00Z"
        fleet.store.write(rec)
        code, out, err = fleet.run(["dispatch", "--profile", str(fleet.profile("worker")), "--title", "mile",
                                    "--base", "00000000"])
        self.assertEqual(code, 0, err)
        self.assertEqual([name for name, _, _ in fleet.started], ["dt-mile"])

class TheApplyWarningAsksTheProposersOwnSession(unittest.TestCase):

    def test_a_done_proposal_by_the_old_record_does_not_warn_about_the_new_workers_session(self):
        """`_live_session_warning` (FB-71) says the PROPOSER's session reads alive. The old record's is gone; the live
        `dt-<name>` is its re-dispatch's, which proposed nothing."""
        from fleet.roadmap import Milestone, Roadmap
        fleet = Fleet(slots=4)
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        coordinator = fleet.worker("coord", slot="ws1", live=False)
        Roadmap(coordinator).add(Milestone(id="m7", title="closing out", status="blocked", deps=[], evidence=[]))
        old = fleet.worker("mile", live=False)
        rec = fleet.store.read(fleet.ids["mile"])
        rec.launched_at = "2026-07-29T09:00:00Z"
        fleet.store.write(rec)
        code, _, err = fleet.run(["propose", "--instant", str(old), "--to", str(coordinator), "--milestone", "m7",
                                  "--status", "done", "--evidence", "evidence/INDEX.md"])
        self.assertEqual(code, 0, err)
        fleet.worker("mile", slot="ws2", pane=IDLE_PANE)                  # the re-dispatch, live
        code, out, err = fleet.run(["apply", "--instant", str(coordinator), "--milestone", "m7"])
        self.assertEqual(code, 0, err)
        self.assertNotIn("reads ALIVE", out + err)


if __name__ == "__main__":
    unittest.main()


class OneUnreadableRecordDoesNotStopATeardown(unittest.TestCase):
    """S6 RV-S6S-3 (pre-cut state review). `_session_taken_by` read `store.all()`, which refuses the whole store over one
    torn record, so close/abort/harvest/reap exited 2 for records that have nothing to do with it (0.6.15 did not read
    the store there). The readable records decide; an unreadable record can own only `dt-<its title>`, and when it
    could, nothing is killed and the lease is kept."""

    def _fleet(self, broken):
        fleet = Fleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        fleet.worker("solo", state="abort", slot="ws1", pane=IDLE_PANE)
        (fleet.home / "records" / f"{broken}.json").write_text("{ not json")
        return fleet

    def test_an_unrelated_unreadable_record_stops_neither_close_nor_reap(self):
        fleet = self._fleet("zzbroken-09999999")
        code, out, err = fleet.run(["close", "--id", fleet.ids["solo"]])
        self.assertEqual(code, 0, f"rc={code}\n{out}\n{err}")
        self.assertIn("dt-solo", fleet.killed)
        fleet = self._fleet("zzbroken-09999999")
        code, out, err = fleet.run(["reap", "--all"])
        self.assertEqual(code, 0, f"rc={code}\n{out}\n{err}")

    def test_an_unreadable_record_that_could_own_the_session_fails_closed(self):
        fleet = self._fleet("solo-09999999")                   # its title is `solo`: it could own dt-solo
        code, out, err = fleet.run(["close", "--id", fleet.ids["solo"]])
        self.assertEqual(code, 0, f"rc={code}\n{out}\n{err}")
        self.assertNotIn("dt-solo", fleet.killed, "a session an unreadable record may own was killed")
        self.assertIn("an unreadable record (solo-09999999.json)", out)
        fleet = self._fleet("solo-09999999")
        code, out, err = fleet.run(["reap", "--all"])
        self.assertEqual(code, 0, f"rc={code}\n{out}\n{err}")
        self.assertIsNotNone(fleet.pool.lease("ws1"), "a lease whose session an unreadable record may own was freed")
