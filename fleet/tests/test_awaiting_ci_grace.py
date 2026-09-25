"""`V23-G` (v3-06, v2-10): what an `awaiting-ci` claim is worth across a watcher gap and across a revive.

Kept in its own module on purpose: `test_reconcile.py` and `test_cli.py` are edited by several parallel buckets,
and every case here is about one question — does the WIP-cap exemption stand for exactly as long as something
backs it? Each positive has its control beside it, and each guard has a named mutation it kills.
"""
import json
import pathlib
import shutil
import unittest

from tests.test_cli import Fleet, WATCHED_PANE
from tests.test_reconcile import SyntheticFleet
from fleet.reconcile import AWAITING_CI, reconcile
from fleet.session import LiveSession

#: The pane the revived session shows: a claude frame with nothing armed on its status line.
QUIET_PANE = "\n".join(["compiled 42 files", "wrote target/fleet.jar", "done"])


def _declare(path, **fields):
    """The claim as `declare` leaves it on disk, written directly so the case does not depend on the writer."""
    target = pathlib.Path(path) / ".fleet" / "declare.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(target.read_text()) if target.exists() else {}
    data.update(fields)
    target.write_text(json.dumps(data))


class TestADeclarationIsRevalidatedAfterRevive(unittest.TestCase):
    """v2-10. The box rebooted, every `dt-*` session was recreated by the revive path, and whatever watcher the
    worker had armed or attested for `awaiting-ci` no longer existed. Does the claim still take the worker out
    of the cap? Driven through the real `revive` verb on a private store, then the real `board`."""

    def setUp(self):
        self.f = Fleet(slots=8)
        self.addCleanup(shutil.rmtree, self.f.tmp, True)
        self.args = self.f.revival_fixture()
        self.todo = self.f.ids['recoverable']
        self.path = self.f.paths['recoverable']

    def revive_into(self, pane):
        code, out, err = self.f.run(['revive', *self.args])
        self.assertEqual(code, 0, err)
        record = self.f.store.read(self.todo)
        #: The fixture's `start_session` only records the call; the revived session is made live here, in
        #: the slot it was started in, showing `pane`.
        self.f.procs.append(LiveSession(pid=4900, cwd=self.f.pool.slot_path('ws7'), name=record.tmux))
        self.f.panes[record.tmux] = pane
        self.f.tmux_live.add(record.tmux)
        return record

    def row(self):
        code, out, err = self.f.run(['board', '--porcelain'])
        self.assertEqual(code, 0, err)
        for line in out.splitlines():
            cells = line.split('\t')
            if cells[0] == self.todo:
                return cells[2], cells[6]
        self.fail(f"no board row for {self.todo}:\n{out}")

    def test_an_observed_watcher_from_before_the_revive_is_gone(self):
        """B07 holds across a revive: the monitor that backed the claim died with the old session."""
        _declare(self.path, phase='awaiting-ci', at='2026-07-30T10:00:00Z', watchers='1 monitor')
        self.revive_into(QUIET_PANE)
        state, note = self.row()
        self.assertNotEqual(state, 'AWAITING-CI', note)
        self.assertIn('disregarded', note)

    def test_an_attested_pid_that_died_in_the_reboot_is_gone(self):
        """FB-58 holds across a revive: a pid that is not running is GONE (pid 2**22+7 exceeds pid_max)."""
        _declare(self.path, phase='awaiting-ci', at='2026-07-30T10:00:00Z',
                 watchers='attested: gate pid:4194311', watcher_pid={'pid': 4194311, 'start': '777'})
        self.revive_into(QUIET_PANE)
        state, note = self.row()
        self.assertNotEqual(state, 'AWAITING-CI', note)
        self.assertIn('GONE', note)

    def test_an_unhandled_attestation_made_before_the_revive_is_not_trusted_after_it(self):
        """The residue v2-10 asked about. An attestation with no pid handle was the claimant's word about the
        session that made it; that session was relaunched after the claim, and nothing can re-check the word
        across the relaunch. It must not keep the worker out of the cap on its own."""
        _declare(self.path, phase='awaiting-ci', at='2026-07-30T10:00:00Z',
                 watchers='attested: a peer session watching the release gate')
        self.revive_into(QUIET_PANE)
        state, note = self.row()
        self.assertNotEqual(state, 'AWAITING-CI', note)
        self.assertIn('relaunched', note)
        self.assertIn('disregarded', note)

    def test_an_unhandled_attestation_made_after_the_revive_stands(self):
        """Control: the same attestation, re-declared by the revived session, is this session's word."""
        self.revive_into(QUIET_PANE)
        _declare(self.path, phase='awaiting-ci', at='2026-07-30T12:30:00Z',
                 watchers='attested: a peer session watching the release gate')
        state, note = self.row()
        self.assertEqual(state, 'AWAITING-CI', note)
        self.assertIn('ATTESTED', note)

    def test_a_watcher_observed_on_the_revived_pane_renews_the_claim(self):
        """Control, and v3-06(b): a fresh watcher on the pane backs the old declaration without a re-declare."""
        _declare(self.path, phase='awaiting-ci', at='2026-07-30T10:00:00Z',
                 watchers='attested: a peer session watching the release gate')
        self.revive_into(WATCHED_PANE)
        state, note = self.row()
        self.assertEqual(state, 'AWAITING-CI', note)
        self.assertIn('watcher observed', note)


class TestTheRelaunchBoundary(unittest.TestCase):
    """v2-10 at the join, one field at a time: only a claim STRICTLY older than the launch is an earlier
    session's word, and a stamp that cannot be read is NOT MEASURED (`FI-7`)."""

    def subject(self, at, launched_at):
        fleet = SyntheticFleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        fleet.dispatch("relaunch-07300701", "00000000-07300701-inflight-append-relaunch", "ws9",
                       "dt-relaunch", launched_at=launched_at)
        fleet.launch("dt-relaunch", 5401, "ws9", QUIET_PANE)
        fields = {"phase": "awaiting-ci", "watchers": "attested: a peer session watching"}
        if at is not None:
            fields["at"] = at
        _declare(fleet.paths["relaunch-07300701"], **fields)
        return {s.identity: s for s in reconcile(fleet.store, fleet.pool, fleet.sessions,
                                                 fleet.instants)}["relaunch-07300701"]

    def test_one_second_older_than_the_launch_is_disregarded(self):
        s = self.subject("2026-07-30T03:12:59Z", "2026-07-30T03:13:00Z")
        self.assertNotEqual(s.state, AWAITING_CI, s.note)
        self.assertIn("relaunched at 2026-07-30T03:13:00Z", s.note)

    def test_the_same_second_as_the_launch_stands(self):
        s = self.subject("2026-07-30T03:13:00Z", "2026-07-30T03:13:00Z")
        self.assertEqual(s.state, AWAITING_CI, s.note)

    def test_a_claim_with_no_stamp_is_not_measured_and_stands(self):
        s = self.subject(None, "2026-07-30T03:13:00Z")
        self.assertEqual(s.state, AWAITING_CI, s.note)

    def test_an_unreadable_launch_stamp_is_not_measured_and_stands(self):
        for bad in ("yesterday", "", None):
            with self.subTest(launched_at=bad):
                s = self.subject("2026-07-30T03:12:00Z", bad)
                self.assertEqual(s.state, AWAITING_CI, s.note)


if __name__ == '__main__':
    unittest.main()
