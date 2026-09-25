"""`V23-T` (RV-S1 / S5-I1). When several records name one tmux session, the live session belongs to ONE of them.

A re-dispatch of a title reuses `dt-<name>` (`cli._dispatch_collision`), so the store holds pairs: the live store has
six (b01harvestreadsworkerroadmap-09220003/-09220005, v2stackcoordinator-07310334/-07310348, and four more). The join
used to hand the session to the first record by todo_id and then read EVERY other record naming it as live too, so
an older, harvested record read the new worker's pane: COMPLETE-BUT-WORKING (counted against the WIP cap while the
board, which shows slot holders only, hid it) or COMPLETE carrying the new worker's pid, which
`scripts/fleet-finished-pids.sh` turns into "exclude from auto-resume".

The rule (`reconcile.session_owner`): the record with the latest `launched_at` owns the session, because every
successful start stamps it and no start succeeds while a same-named session is live. A never-launched record ranks
below every launched one. Every other record reads exactly as if the session were gone.
"""
import pathlib
import shutil
import tempfile
import time
import unittest

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
        pair.record("09251200", "inflight", "ws2", launched_at=None, lease=True)
        pair.launch("ws1", QUIET)
        subs = pair.reconcile()
        self.assertEqual(subs["mile-08262300"].state, RUNNING)
        self.assertEqual(subs["mile-09251200"].state, PENDING_LAUNCH)
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
