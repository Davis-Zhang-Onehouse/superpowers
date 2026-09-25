"""`V23-G` (v3-06, v2-10): what an `awaiting-ci` claim is worth across a watcher gap and across a revive.

Kept in its own module on purpose: `test_reconcile.py` and `test_cli.py` are edited by several parallel buckets,
and every case here is about one question — does the WIP-cap exemption stand for exactly as long as something
backs it? Each positive has its control beside it, and each guard has a named mutation it kills.
"""
import calendar
import json
import pathlib
import shutil
import time
import unittest
from unittest import mock

from tests.test_cli import DIALOG_PANE, Fleet, IDLE_PANE, NOW, WATCHED_PANE
from tests.test_guards import Fleet as GuardFleet
from fleet.guards import CAP_EXCLUDED_STATES, WipCap
from tests.test_reconcile import SyntheticFleet
from fleet.reconcile import AWAITING_CI, needs_a_human, reconcile
#: RV-12. Every name this bucket adds is imported under a guard with the value it has here, so the module runs
#: on the base (1a2842f2) and each case fails there on BEHAVIOUR (a state, a note, an exit code), never on an
#: ImportError that would fail every case for one reason and prove nothing about any of them.
try:
    from fleet.reconcile import WATCHER_GRACE_S
except ImportError:
    WATCHER_GRACE_S = 300
try:
    from fleet.reconcile import HOLD_DEFAULT_S, HOLD_MAX_S, HOLDING
except ImportError:
    HOLD_DEFAULT_S, HOLD_MAX_S, HOLDING = 60 * 60, 4 * 60 * 60, "HOLDING"
from fleet.store import Declarations
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



def _epoch(stamp):
    return calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))


class TestTheHoldingPhase(unittest.TestCase):
    """v3-06(c). A worker told to hold, with nothing to watch, used to have two choices: declare awaiting-ci
    and be disregarded (no watcher), or count against the cap. `holding` is the honest third: it needs no
    watcher, it is excluded from the cap, and it needs a REASON and an EXPIRY so it cannot become a
    permanent cap escape (D-3)."""

    def setUp(self):
        self.f = Fleet()
        self.addCleanup(shutil.rmtree, self.f.tmp, True)
        self.path = self.f.worker('holder', slot='ws1', pane=IDLE_PANE)
        self.todo = self.f.ids['holder']

    def declare(self, *extra):
        return self.f.run(['declare', '--instant', str(self.path), '--phase', 'holding', *extra,
                           '--porcelain'])

    def row(self, at=None):
        clock = _epoch(at or NOW)
        with mock.patch('fleet.reconcile.time.time', return_value=clock):
            code, out, err = self.f.run(['board', '--porcelain'])
        self.assertEqual(code, 0, err)
        for line in out.splitlines():
            cells = line.split('\t')
            if cells[0] == self.todo:
                return cells[2], cells[6]
        self.fail(f"no row for {self.todo}:\n{out}")

    def test_a_hold_with_a_reason_is_holding_and_off_the_cap(self):
        code, out, err = self.declare('--reason', 'operator said hold until the S4 stack lands')
        self.assertEqual(code, 0, err)
        self.assertIn('hold_until\t2026-07-30T13:00:00Z', out, 'the default expiry is one hour from now')
        state, note = self.row()
        self.assertEqual(state, HOLDING, note)
        self.assertIn('operator said hold until the S4 stack lands', note)
        self.assertIn('2026-07-30T13:00:00Z', note)
        self.assertIn(HOLDING, CAP_EXCLUDED_STATES)

    def test_the_claim_stamp_and_the_expiry_come_from_one_clock(self):
        """RV-22. `at` and `hold_until` are compared by the join, so both are read off `ctx.now` — the verb's
        one clock seam — never one from the wall clock and one from the seam."""
        self.assertEqual(self.declare('--reason', 'r', '--for', '30m')[0], 0)
        stored = json.loads((self.path / '.fleet' / 'declare.json').read_text())
        self.assertEqual(stored['at'], NOW)
        self.assertEqual(stored['hold_until'], '2026-07-30T12:30:00Z')

    def test_a_hold_without_a_reason_is_refused(self):
        for extra in ((), ('--reason', ''), ('--reason', '   ')):
            with self.subTest(extra=extra):
                code, out, err = self.declare(*extra)
                self.assertEqual(code, 2, out + err)
                self.assertIsNone(Declarations(self.path).phase(), 'a refused hold was stored')

    def test_an_expiry_beyond_the_maximum_is_refused(self):
        code, out, err = self.declare('--reason', 'r', '--for', f'{HOLD_MAX_S + 1}s')
        self.assertEqual(code, 2, out + err)
        self.assertIsNone(Declarations(self.path).phase())
        code, out, err = self.declare('--reason', 'r', '--for', f'{HOLD_MAX_S // 3600}h')
        self.assertEqual(code, 0, err)

    def test_a_malformed_expiry_is_refused(self):
        for bad in ('', '0m', '-5m', '30', 'soon', '1d', '1h30m'):
            with self.subTest(expiry=bad):
                code, out, err = self.declare('--reason', 'r', '--for', bad)
                self.assertEqual(code, 2, out + err)

    def test_reason_and_expiry_belong_to_holding_only(self):
        for extra in (('--reason', 'r'), ('--for', '30m')):
            with self.subTest(extra=extra):
                code, out, err = self.f.run(['declare', '--instant', str(self.path), '--phase', 'reviewing',
                                             *extra])
                self.assertEqual(code, 2, out + err)

    def test_the_hold_expires_at_its_boundary(self):
        """One second before `hold_until` the hold stands; at it, it is disregarded and counts again."""
        self.assertEqual(self.declare('--reason', 'waiting for the operator', '--for', '30m')[0], 0)
        state, note = self.row('2026-07-30T12:29:59Z')
        self.assertEqual(state, HOLDING, note)
        state, note = self.row('2026-07-30T12:30:00Z')
        self.assertNotIn(state, CAP_EXCLUDED_STATES, note)
        self.assertIn('HOLD EXPIRED', note)
        self.assertIn('disregarded', note)

    def test_a_hand_written_far_future_hold_is_bounded_by_the_maximum(self):
        """RV-20. The 4 h bound is enforced where the hold is READ, not only where `declare` writes it: a
        `hold_until` edited to 2099 stands only until `at + HOLD_MAX_S`, like any declared hold."""
        _declare(self.path, phase='holding', at='2026-07-30T11:00:00Z', hold_reason='edited by hand',
                 hold_until='2099-01-01T00:00:00Z')
        state, note = self.row('2026-07-30T14:59:59Z')
        self.assertEqual(state, HOLDING, note)
        state, note = self.row('2026-07-30T15:00:00Z')
        self.assertNotIn(state, CAP_EXCLUDED_STATES, note)
        self.assertIn('disregarded', note)

    def test_a_hold_with_no_claim_stamp_is_disregarded(self):
        """RV-20. Without `at` nothing bounds `hold_until`, so the hold backs nothing."""
        _declare(self.path, phase='holding', hold_reason='r', hold_until='2026-07-30T12:30:00Z')
        state, note = self.row()
        self.assertNotIn(state, CAP_EXCLUDED_STATES, note)
        self.assertIn('disregarded', note)

    def test_a_hold_within_the_maximum_is_untouched_by_the_bound(self):
        """Neighbour: exactly `at + HOLD_MAX_S` is a legal declared hold and stands until then."""
        _declare(self.path, phase='holding', at='2026-07-30T11:00:00Z', hold_reason='r',
                 hold_until='2026-07-30T15:00:00Z')
        state, note = self.row('2026-07-30T14:59:59Z')
        self.assertEqual(state, HOLDING, note)

    def test_a_hand_written_hold_with_no_expiry_is_disregarded(self):
        """No new REQUIRED field, and no escape by editing the file: `phase: holding` alone backs nothing."""
        _declare(self.path, phase='holding', at='2026-07-30T11:59:00Z')
        state, note = self.row()
        self.assertNotIn(state, CAP_EXCLUDED_STATES, note)
        self.assertIn('disregarded', note)

    def test_a_dialog_outranks_the_hold(self):
        self.assertEqual(self.declare('--reason', 'r')[0], 0)
        self.f.panes['dt-holder'] = DIALOG_PANE
        state, note = self.row()
        self.assertEqual(state, 'BLOCKED', note)

    def test_redeclaring_another_phase_clears_the_hold(self):
        self.assertEqual(self.declare('--reason', 'r')[0], 0)
        code, out, err = self.f.run(['declare', '--instant', str(self.path), '--phase', 'reviewing'])
        self.assertEqual(code, 0, err)
        stored = json.loads((self.path / '.fleet' / 'declare.json').read_text())
        self.assertNotIn('hold_until', stored)
        self.assertNotIn('hold_reason', stored)

    def test_complete_refuses_while_holding(self):
        self.assertEqual(self.declare('--reason', 'r')[0], 0)
        code, out, err = self.f.run(['complete', '--instant', str(self.path)])
        self.assertNotEqual(code, 0, out)
        self.assertIn('holding', out + err)
        self.assertTrue(self.path.exists(), 'the folder was renamed while holding')

    def test_a_hold_is_not_a_question_for_a_human(self):
        self.assertEqual(self.declare('--reason', 'r')[0], 0)
        with mock.patch('fleet.reconcile.time.time', return_value=_epoch(NOW)):
            subject = [s for s in reconcile(self.f.store, self.f.pool, self.f.sessions, self.f.instants)
                       if s.identity == self.todo][0]
        self.assertEqual(subject.state, HOLDING, subject.note)
        self.assertFalse(needs_a_human(subject))


class TestAHoldFreesTheCap(unittest.TestCase):
    """The cap itself, at 1: a live hold frees it, an expired one holds it again."""

    def test_the_cap(self):
        fleet = GuardFleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        fleet.worker("holder", slot="ws1", pane=QUIET_PANE)
        path = fleet.paths["holder"]
        self.assertFalse(WipCap().evaluate(fleet.ctx()).allowed, "precondition: the worker holds the cap")
        now = time.time()
        until = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 600))
        _declare(path, phase="holding", at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                 hold_reason="told to hold", hold_until=until)
        self.assertTrue(WipCap().evaluate(fleet.ctx()).allowed, "a live hold did not free the cap")
        with mock.patch('fleet.reconcile.time.time', return_value=now + 601):
            self.assertFalse(WipCap().evaluate(fleet.ctx()).allowed, "an expired hold kept the cap free")



class TestTheGraceAfterTheClaim(unittest.TestCase):
    """v3-06(a), as the coordinator decided it (D-90, option B): the join never writes, so the only moment a
    grace can be anchored to is the declaration's own `at`. For `WATCHER_GRACE_S` after the claim, a watcher
    missing from the pane does not void it (a Monitor being armed or re-armed); from then on it is voided
    exactly as before. A dead watcher can therefore never keep a record out of the cap past `at + grace`."""

    AT = "2026-07-30T12:00:00Z"

    def subject(self, seconds_after, watchers="1 monitor", pane=QUIET_PANE, launched_at="2026-07-30T03:13:00Z",
                at=AT, **extra):
        fleet = SyntheticFleet()
        self.addCleanup(shutil.rmtree, fleet.tmp, True)
        fleet.dispatch("grace-07300801", "00000000-07300801-inflight-append-grace", "ws9", "dt-grace",
                       launched_at=launched_at)
        fleet.launch("dt-grace", 5501, "ws9", pane)
        fields = {"phase": "awaiting-ci", **extra}
        if at is not None:
            fields["at"] = at
        if watchers is not None:
            fields["watchers"] = watchers
        _declare(fleet.paths["grace-07300801"], **fields)
        with mock.patch("fleet.reconcile.time.time", return_value=_epoch(self.AT) + seconds_after):
            return {s.identity: s for s in reconcile(fleet.store, fleet.pool, fleet.sessions,
                                                     fleet.instants)}["grace-07300801"]

    def test_a_watcher_gone_inside_the_grace_keeps_the_claim(self):
        s = self.subject(WATCHER_GRACE_S - 1)
        self.assertEqual(s.state, AWAITING_CI, s.note)
        self.assertIn("GRACE", s.note)
        self.assertIn("2026-07-30T12:05:00Z", s.note, "the note does not say when the grace ends")

    def test_the_grace_ends_at_its_boundary(self):
        s = self.subject(WATCHER_GRACE_S)
        self.assertNotEqual(s.state, AWAITING_CI, s.note)
        self.assertIn("disregarded", s.note)

    def test_a_dead_watcher_never_outlives_the_grace(self):
        """The fence the dispatch set: however old, a gone watcher is voided once the grace has passed."""
        for later in (WATCHER_GRACE_S + 1, 3600, 30 * 3600):
            with self.subTest(seconds_after=later):
                s = self.subject(later)
                self.assertNotEqual(s.state, AWAITING_CI, s.note)

    def test_a_claim_with_no_stamp_gets_no_grace(self):
        """An exemption needs a bound; a claim with no `at` has none, so it gets exactly today's treatment."""
        s = self.subject(1, at=None)
        self.assertNotEqual(s.state, AWAITING_CI, s.note)

    def test_a_pid_that_exited_gets_no_grace(self):
        """Grace is for a watcher on the PANE being armed. An attested pid that exited is a measured end."""
        s = self.subject(1, watchers="attested: gate pid:4194311",
                         watcher_pid={"pid": 4194311, "start": "777"})
        self.assertNotEqual(s.state, AWAITING_CI, s.note)

    def test_a_claim_from_before_a_relaunch_gets_no_grace(self):
        s = self.subject(1, launched_at="2026-07-30T12:00:01Z", watchers="attested: a peer session")
        self.assertNotEqual(s.state, AWAITING_CI, s.note)
        s = self.subject(1, launched_at="2026-07-30T12:00:01Z")
        self.assertNotEqual(s.state, AWAITING_CI, s.note)

    def test_a_claim_stamped_in_the_future_gets_no_grace(self):
        """RV-20. A future `at` (hand edit, or a clock stepped back) would stretch the grace by the skew."""
        s = self.subject(-600, at="2026-07-30T12:00:00Z")
        self.assertNotEqual(s.state, AWAITING_CI, s.note)

    def test_a_fresh_watcher_renews_after_the_grace(self):
        """v3-06(b): the re-arm gap closes itself — a new Monitor on the pane backs the old claim, no re-declare."""
        s = self.subject(3600, pane=WATCHED_PANE)
        self.assertEqual(s.state, AWAITING_CI, s.note)
        self.assertIn("watcher observed", s.note)



class TestBriefSaysWhatTheBoardDoes(unittest.TestCase):
    """RV-19. `brief` is how a worker checks itself; its phase row explains what `board` does with the claim.
    After this bucket the board disregards a pre-relaunch attestation, tolerates a missing watcher for the
    grace, and bounds a hold — and the row must say so, or a revived worker is told it is trusted."""

    def setUp(self):
        self.f = Fleet()
        self.addCleanup(shutil.rmtree, self.f.tmp, True)
        self.path = self.f.worker('briefed', slot='ws1', pane=IDLE_PANE)

    def phase_row(self, at_clock=NOW):
        with mock.patch('fleet.reconcile.time.time', return_value=_epoch(at_clock)):
            code, out, err = self.f.run(['brief', '--instant', str(self.path), '--porcelain'])
        self.assertEqual(code, 0, err)
        rows = [line for line in out.splitlines() if line.startswith('phase\t')]
        self.assertEqual(len(rows), 1, out)
        return rows[0]

    def test_a_pre_relaunch_attestation_is_said_to_be_disregarded(self):
        _declare(self.path, phase='awaiting-ci', at='2026-07-30T10:00:00Z',
                 watchers='attested: a peer session watching')
        row = self.phase_row()
        self.assertIn('relaunched', row)
        self.assertIn('disregards the claim now', row)
        self.assertNotIn('trusts it', row)

    def test_an_attestation_made_after_the_launch_is_still_trusted(self):
        """Control: the same attestation made by this session."""
        _declare(self.path, phase='awaiting-ci', at='2026-07-30T12:00:00Z',
                 watchers='attested: a peer session watching')
        row = self.phase_row()
        self.assertIn('trusts it', row)
        self.assertNotIn('relaunched at', row)

    def test_an_observed_claim_names_its_grace(self):
        _declare(self.path, phase='awaiting-ci', at='2026-07-30T12:00:00Z', watchers='1 monitor')
        row = self.phase_row('2026-07-30T12:01:00Z')
        self.assertIn('GRACE', row)
        self.assertIn('2026-07-30T12:05:00Z', row)
        self.assertIn('fresh watcher', row)

    def test_a_hold_is_shown_with_its_expiry_and_reason(self):
        _declare(self.path, phase='holding', at='2026-07-30T12:00:00Z', hold_reason='told to wait',
                 hold_until='2026-07-30T12:30:00Z')
        row = self.phase_row()
        self.assertIn('held until 2026-07-30T12:30:00Z', row)
        self.assertIn('told to wait', row)
        row = self.phase_row('2026-07-30T12:30:00Z')
        self.assertIn('HOLD EXPIRED', row)
        self.assertIn('counts against the WIP cap', row)


if __name__ == '__main__':
    unittest.main()
