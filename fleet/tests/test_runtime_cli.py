import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from fleet.runtime_config import admission_lock, read_runtime, write_runtime
from fleet.session import LiveSession, SessionLayer, default_probes
from tests.test_cli import Fleet, snapshot
from tests.test_runtime_discovery import probe_unreadable


class RuntimeCliTests(unittest.TestCase):
    def setUp(self):
        self.f = Fleet()
        self.addCleanup(shutil.rmtree, self.f.tmp)

    def test_read_and_dry_run_change_nothing(self):
        for args in (['runtime'], ['runtime', '--set', 'codex', '--dry-run']):
            before = snapshot(self.f.tmp)
            code, out, err = self.f.run(args)
            self.assertEqual(code, 0, err)
            self.assertIn('runtime', out)
            self.assertEqual(snapshot(self.f.tmp), before)

    def test_switch_round_trip(self):
        for name in ('codex', 'claude'):
            code, out, err = self.f.run(['runtime', '--set', name])
            self.assertEqual(code, 0, err)
            self.assertEqual(read_runtime(self.f.home), (name, 'saved'))

    def test_unharvested_worker_blocks_even_when_dead(self):
        self.f.worker('active', slot='ws1', live=False)
        with admission_lock(self.f.home):
            pass
        before = snapshot(self.f.home)
        code, out, err = self.f.run(['runtime', '--set', 'codex'])
        self.assertEqual(code, 4, err)
        self.assertEqual(snapshot(self.f.home), before)

    def test_a_closed_complete_record_is_not_a_blocker_and_its_lease_names_reap(self):
        """RV-21 / RV-30, re-decided by FB-92 (D-30). A record closed after it completed can be neither revived
        (closed) nor resumed (-complete-), so it no longer blocks; the lease `close` leaves held still does, and
        the route it names — `fleet reap` — is RUN here, with no harvest and no review."""
        done = self.f.worker('shut', state='complete', slot='ws1', live=False)
        self.f.reviewed(done)
        code, _, err = self.f.run(['close', '--id', self.f.ids['shut']])
        self.assertEqual(code, 0, err)
        code, _, err = self.f.run(['runtime', '--set', 'codex'])
        self.assertEqual(code, 4, err)
        self.assertNotIn(self.f.ids['shut'], err.split('clears when:', 1)[0], err)
        self.assertIn('held lease ws1', err)
        self.assertIn('fleet reap', err.split('clears when:', 1)[-1], err)
        code, _, err = self.f.run(['reap', '--base', self.f.store.read(self.f.ids['shut']).base_instant])
        self.assertEqual(code, 0, err)
        code, _, err = self.f.run(['runtime', '--set', 'codex'])
        self.assertEqual(code, 0, f"the named route ran and the switch is still refused: {err}")

    def test_an_open_complete_record_with_its_lease_names_harvest_and_close_then_reap(self):
        """RV-35 / D-31 / FB-92. Open, its lease held, folder -complete-: `revive` could still act, so it blocks,
        and the text names both doors. Each is RUN: review -> harvest on one record, close -> reap on another."""
        for name in ('viaHarvest', 'viaClose'):
            self.f.worker(name, state='complete', slot='ws1' if name == 'viaHarvest' else 'ws2', live=False)
        code, _, err = self.f.run(['runtime', '--set', 'codex'])
        self.assertEqual(code, 4, err)
        for clause in (f"fleet harvest --id {self.f.ids['viaHarvest']}", f"fleet close --id {self.f.ids['viaClose']}",
                       'fleet reap --base'):
            self.assertIn(clause, err)
        path = self.f.paths['viaHarvest']
        code, _, err = self.f.run(['review', '--instant', str(path), '--scope', 'all', '--verdict', 'READY'])
        self.assertIn(code, (0, 1), err)                 # 1 = the gate's own exit when it has something to say
        code, out, err = self.f.run(['harvest', '--id', self.f.ids['viaHarvest']])
        self.assertTrue(self.f.store.read(self.f.ids['viaHarvest']).harvested_at, f"harvest did not run: {out}{err}")
        self.assertEqual(self.f.run(['close', '--id', self.f.ids['viaClose']])[0], 0)
        base = self.f.store.read(self.f.ids['viaClose']).base_instant
        self.assertEqual(self.f.run(['reap', '--base', base])[0], 0)
        code, _, err = self.f.run(['runtime', '--set', 'codex'])
        self.assertEqual(code, 0, f"both named routes ran and the switch is still refused: {err}")

    def test_an_inflight_closed_record_names_abort_and_abort_clears_it(self):
        """RV-37 / D-31 / FB-92. Closed while `-inflight-`: `resume` can still adopt it, so it blocks — and the
        route is `abort`, which is RUN."""
        path = self.f.worker('halfway', slot='ws1', live=False)
        self.assertEqual(self.f.run(['close', '--id', self.f.ids['halfway']])[0], 0)
        code, _, err = self.f.run(['runtime', '--set', 'codex'])
        self.assertEqual(code, 4, err)
        self.assertIn(f'fleet abort --instant {path}', err)
        self.assertNotIn('no single verb clears it today', err)
        self.assertEqual(self.f.run(['abort', '--instant', str(path), '--reason', 'switching'])[0], 0)
        code, _, err = self.f.run(['runtime', '--set', 'codex'])
        self.assertEqual(code, 0, err)

    def test_an_aborted_record_does_not_block(self):
        path = self.f.worker('dropped', slot='ws1', live=False)
        self.assertEqual(self.f.run(['abort', '--instant', str(path), '--reason', 'abandoned for the test'])[0], 0)
        code, _, err = self.f.run(['runtime', '--set', 'codex'])
        self.assertEqual(code, 0, err)

    def test_a_gone_folder_record_needs_only_its_lease_reaped(self):
        """RV-35 / FB-92. Harvest still exits 2 on a folder that resolves to nothing, and it no longer has to run:
        the record cannot be resumed or revived, so only its lease blocks, and `reap` frees it."""
        path = self.f.worker('gone', slot='ws1', live=False)
        self.assertEqual(self.f.run(['close', '--id', self.f.ids['gone']])[0], 0)
        shutil.rmtree(path)
        code, _, err = self.f.run(['runtime', '--set', 'codex'])
        self.assertEqual(code, 4, err)
        self.assertNotIn(self.f.ids['gone'], err.split('clears when:', 1)[0])
        self.assertEqual(self.f.run(['harvest', '--id', self.f.ids['gone']])[0], 2)
        self.assertEqual(self.f.run(['reap', '--base', self.f.store.read(self.f.ids['gone']).base_instant])[0], 0)
        self.assertEqual(self.f.run(['runtime', '--set', 'codex'])[0], 0)

    def test_an_unreadable_folder_is_undecided_and_blocks(self):
        """FB-53's rule for the new predicate: a folder that cannot be read is not a folder that is gone."""
        path = self.f.worker('sealed', state='complete', slot='ws1', live=False)
        self.assertEqual(self.f.run(['close', '--id', self.f.ids['sealed']])[0], 0)
        self.assertEqual(self.f.run(['reap', '--base', self.f.store.read(self.f.ids['sealed']).base_instant])[0], 0)
        with patch('fleet.cli.resolve', side_effect=PermissionError(13, 'Permission denied')):
            code, _, err = self.f.run(['runtime', '--set', 'codex'])
        self.assertEqual(code, 4, err)
        self.assertIn('could not be read', err)
        self.assertIn(self.f.ids['sealed'], err)

    def test_same_runtime_is_noop_with_work(self):
        self.f.worker('active', slot='ws1')
        before = snapshot(self.f.home)
        code, out, err = self.f.run(['runtime', '--set', 'claude'])
        self.assertEqual(code, 0, err)
        self.assertEqual(snapshot(self.f.home), before)

    def test_foreign_process_does_not_block_but_unclaimed_slot_process_does(self):
        self.f.procs.append(LiveSession(777, Path('/another/fleet'), 'foreign', 'codex'))
        self.assertEqual(self.f.run(['runtime', '--set', 'codex'])[0], 0)
        self.f.procs.append(LiveSession(778, self.f.pool.slot_path('ws1'), None, 'claude'))
        code, _, err = self.f.run(['runtime', '--set', 'claude'])
        self.assertEqual(code, 4, err)

    def test_a_process_elsewhere_under_the_root_does_not_block(self):
        """The store lives at <root>/.fleet; an interactive session in a sibling project under that root is
        not this fleet's, and used to forbid every switch."""
        other = Path(self.f.tmp) / 'other-project'; other.mkdir(exist_ok=True)
        self.f.procs.append(LiveSession(780, other, None, 'claude'))
        self.assertEqual(self.f.run(['runtime', '--set', 'codex'])[0], 0)

    def test_an_unreadable_process_blocks_the_switch_but_not_the_read_verbs(self):
        """A process whose `/proc` refused the read cannot be placed, so it is not proof of emptiness for
        a switch — and it is not a reason for `board` to exit 1 either."""
        self.f.procs.append(LiveSession(779, Path('/proc/779'), None, 'codex', unreadable=True))
        code, _, err = self.f.run(['runtime', '--set', 'codex'])
        self.assertEqual(code, 4, err)
        self.assertIn('unreadable', err)
        self.assertEqual(self.f.run(['board', '--porcelain'])[0], 0)

    def test_an_unreadable_process_ATTRIBUTED_to_a_pane_still_blocks_the_switch(self):
        """FB-54 keeps this consumer honest: naming the pane an unreadable pid lives in does not make its binary or its
        cwd known, so it is still no proof of emptiness. The refusal names the session it was placed in."""
        self.f.procs.append(probe_unreadable(self.f.tmp / 'proc', 781, 780, 'dt-someone', runtime='codex'))
        code, _, err = self.f.run(['runtime', '--set', 'codex'])
        self.assertEqual(code, 4, err)
        self.assertIn('unreadable codex process 781', err)
        self.assertIn('dt-someone', err)
        # RV-32: the row does not keep WHICH /proc read failed, so the text names no cause it did not observe.
        self.assertIn('a /proc read of it failed', err)
        self.assertNotIn('cwd unreadable', err)

    def test_invalid_selection_is_not_overwritten(self):
        self.f.home.mkdir(exist_ok=True)
        path = self.f.home / 'runtime.json'
        path.write_text('{broken')
        before = snapshot(self.f.home)
        self.assertEqual(self.f.run(['runtime', '--set', 'codex'])[0], 2)
        self.assertEqual(snapshot(self.f.home), before)

    def test_codex_dispatch_records_direct_launch_settings(self):
        write_runtime(self.f.home, 'codex')
        code, out, err = self.f.run(['dispatch', '--profile', str(self.f.profile()), '--title', 'codex task'])
        self.assertEqual(code, 0, err)
        record = self.f.store.all()[0]
        self.assertEqual(record.runtime, 'codex')
        self.assertEqual(record.runtime_executable, '/test/bin/codex')
        seed = (Path(record.child_instant) / '.fleet/seed.txt').read_text()
        self.assertIn('"$FLEET_BIN"', seed)
        self.assertIn(str(Path(__file__).resolve().parents[2] / 'bin/fleet'), seed)
        launcher = Path(record.child_instant) / '.fleet/launch-worker.sh'
        self.assertIn(str(launcher), self.f.started[0][2])
        self.assertIn('/test/bin/codex', launcher.read_text())

    def test_tmux_permission_failure_does_not_create_pending_worker(self):
        original = self.f.context
        def context():
            build = original()
            def candidate(parsed, out, err):
                ctx = build(parsed, out, err)
                ctx.sessions = SessionLayer(default_probes(tmux_socket='private', both_runtimes=True))
                return ctx
            return candidate
        self.f.context = context
        denied = subprocess.CompletedProcess([], 1, '',
                    'error connecting to /tmp/tmux-1000/private (Operation not permitted)')
        with patch('subprocess.run', return_value=denied):
            code, _, err = self.f.run(['dispatch', '--profile', str(self.f.profile()), '--title', 'denied'])
        self.assertEqual(code, 1, err)
        self.assertIn('Operation not permitted', err)
        self.assertEqual(self.f.store.all(), [])
        self.assertIsNone(self.f.pool.lease('ws1'))
        self.assertIsNone(self.f.pool.lease('ws2'))
        self.assertEqual(self.f.started, [])

    def test_send_checks_the_record_and_delivers_once(self):
        self.f.worker('active', slot='ws1', pane='❯ \n? for shortcuts')
        message = self.f.tmp / 'message.txt'
        message.write_text('hello')
        events = []
        def insert(name, text):
            events.append(('literal',text))
            self.f.panes[name] = '❯ ' + text + '\n? for shortcuts'
        def submit(name):
            events.append(('submit',None))
            self.f.panes[name] = 'esc to interrupt'
        self.f.sessions.probes.send_literal = insert
        self.f.sessions.probes.submit = submit
        args = ['send', '--id', self.f.ids['active'], '--message-file', str(message)]
        before = snapshot(self.f.home)
        self.assertEqual(self.f.run(args + ['--dry-run'])[0], 0)
        self.assertEqual(events, [])
        self.assertEqual(snapshot(self.f.home), before)
        code, out, err = self.f.run(args)
        self.assertEqual(code, 0, err)
        self.assertEqual(events, [('literal','hello'),('submit',None)])

    def test_known_codex_with_unknown_frame_is_indeterminate(self):
        self.f.worker('codex', slot='ws1', pane='unfamiliar screen')
        record=self.f.store.read(self.f.ids['codex'])
        record.runtime='codex'
        self.f.store.write(record)
        self.f.procs[0].runtime='codex'
        code, _, err=self.f.run(['pane-guard','--id',record.todo_id])
        self.assertEqual(code,14,err)

    def test_send_refuses_wrong_runtime_or_workspace(self):
        self.f.worker('target', slot='ws1', pane='❯ \n? for shortcuts')
        path = self.f.tmp / 'message'
        path.write_text('hello')
        args = ['send', '--id', self.f.ids['target'], '--message-file', str(path)]
        self.f.procs[0].runtime = 'codex'
        self.assertEqual(self.f.run(args)[0], 4)
        self.assertEqual(self.f.run(['pane-guard', '--id', self.f.ids['target']])[0], 14)
        self.assertEqual(self.f.run(['close', '--id', self.f.ids['target']])[0], 4)
        self.f.procs[0].runtime = 'claude'
        self.f.procs[0].cwd = Path('/another/fleet')
        self.assertEqual(self.f.run(args)[0], 4)
        self.assertEqual(self.f.killed, [])

    def test_send_to_a_pane_whose_process_is_unreadable_refuses_naming_that_cause(self):
        """RV-27 (ISSUES OI-1). The pane's claude is alive and attributed to it, but its cwd was never read, so its
        ownership cannot be verified: refusing is right, and "no matching live process" is the wrong reason —
        `revive` on the same pane says it is occupied."""
        self.f.worker('target', slot='ws1', pane='❯ \n? for shortcuts')
        self.f.procs[:] = [probe_unreadable(self.f.tmp / 'proc', 7202, 7201, 'dt-target')]
        path = self.f.tmp / 'message'
        path.write_text('hello')
        code, _, err = self.f.run(['send', '--id', self.f.ids['target'], '--message-file', str(path)])
        self.assertEqual(code, 4, err)
        self.assertIn('process 7202', err)
        self.assertIn('could not be read', err)
        self.assertNotIn('No matching live runtime process', err)

    def test_dry_dispatch_validates_runtime_configuration_without_claiming(self):
        from fleet.errors import BadInput
        original = self.f.context
        def build():
            factory = original()
            def context(parsed, out, err):
                ctx = factory(parsed, out, err)
                def unavailable(runtime, slot):
                    raise BadInput('configuration unavailable')
                ctx.launch_settings = unavailable
                return ctx
            return context
        self.f.context = build
        profile = self.f.profile()
        before = snapshot(self.f.tmp)
        code, _, err = self.f.run(['dispatch', '--profile', str(profile), '--title', 'test', '--dry-run'])
        self.assertEqual(code, 2, err)
        self.assertEqual(snapshot(self.f.tmp), before)

    def test_a_foreign_runtime_session_names_the_route_that_runs(self):
        """RV-22. Adopting a session whose runtime is not the fleet's named `fleet runtime --set <its runtime>`,
        which that very session blocks (its cwd is in the instants dir). The route is the session exiting,
        and then the same resume runs."""
        orphan = self.f.orphan()
        self.f.procs.append(LiveSession(pid=4321, cwd=orphan, name='dt-orphanWork', runtime='codex'))
        self.f.tmux_live.add('dt-orphanWork')
        code, _, err = self.f.run(['resume', '--instant', str(orphan), '--slot', 'ws1'])
        self.assertEqual(code, 4, err)
        route = err.split('clears when:', 1)[-1]
        self.assertNotIn('`fleet runtime --set', route, err)
        self.assertEqual(self.f.run(['runtime', '--set', 'codex'])[0], 4, 'the old route ran after all')
        self.f.procs.clear()
        self.f.tmux_live.discard('dt-orphanWork')
        code, _, err = self.f.run(['resume', '--instant', str(orphan), '--slot', 'ws1'])
        self.assertEqual(code, 0, f"the named route does not run: {err}")

    def test_a_live_session_matching_its_record_is_adopted_whatever_the_box_says(self):
        """pt2 (D-22/D-33) replaces RV-31: the record's runtime is the one an adopted session must be. A live claude
        session over a claude record adopts on a codex box; the record keeps its runtime."""
        path = self.f.worker('original', slot='ws1', live=True)          # record + live session, runtime claude
        write_runtime(self.f.home, 'codex')
        code, _, err = self.f.run(['resume', '--instant', str(path)])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.f.store.read(self.f.ids['original']).runtime, 'claude')

    def test_adoption_cannot_relabel_an_existing_runtime(self):
        self.f.worker('original', slot='ws1', live=False)
        write_runtime(self.f.home, 'codex')
        code, _, err = self.f.run(['resume', '--instant', str(self.f.paths['original'])])
        #: pt2: adopted under its RECORD's runtime rather than refused; the box selection still cannot relabel it.
        self.assertEqual(code, 0, err)
        self.assertEqual(self.f.store.read(self.f.ids['original']).runtime, 'claude')

    def test_a_live_session_of_another_runtime_than_its_record_names_the_route_that_runs(self):
        """B11 for the refusal pt2 keeps: the session exiting is the route, and then the same resume runs."""
        path = self.f.worker('original', slot='ws1', live=False)
        record = self.f.store.read(self.f.ids['original'])
        self.f.procs.append(LiveSession(pid=4321, cwd=path, name=record.tmux, runtime='codex'))
        self.f.tmux_live.add(record.tmux)
        code, _, err = self.f.run(['resume', '--instant', str(path)])
        self.assertEqual(code, 4, err)
        route = err.split('clears when:', 1)[-1]
        self.assertIn('has exited', route, err)
        self.assertNotIn('`fleet runtime --set', route, err)
        self.f.procs.clear()
        self.f.tmux_live.discard(record.tmux)
        code, _, err = self.f.run(['resume', '--instant', str(path)])
        self.assertEqual(code, 0, f"the named route does not run: {err}")
        self.assertEqual(self.f.store.read(record.todo_id).runtime, 'claude')
