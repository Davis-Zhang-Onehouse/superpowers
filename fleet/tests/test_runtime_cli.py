import shutil
import unittest
from pathlib import Path

from fleet.runtime_config import admission_lock, read_runtime, write_runtime
from fleet.session import LiveSession
from tests.test_cli import Fleet, snapshot


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
        launcher = Path(record.child_instant) / '.fleet/launch-worker.sh'
        self.assertIn(str(launcher), self.f.started[0][2])
        self.assertIn('/test/bin/codex', launcher.read_text())

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

    def test_adoption_cannot_relabel_an_existing_runtime(self):
        self.f.worker('original', slot='ws1', live=False)
        write_runtime(self.f.home, 'codex')
        code, _, err = self.f.run(['resume', '--instant', str(self.f.paths['original'])])
        self.assertEqual(code, 4, err)
        self.assertEqual(self.f.store.read(self.f.ids['original']).runtime, 'claude')
