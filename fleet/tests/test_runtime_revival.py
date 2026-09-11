import json
from pathlib import Path
import shutil
import unittest

from fleet.runtime_config import write_runtime
from tests.test_cli import Fleet, snapshot

SESSION_ID = '12345678-1234-1234-1234-123456789abc'


class RevivalTests(unittest.TestCase):
    def setUp(self):
        self.f = Fleet()
        self.addCleanup(shutil.rmtree, self.f.tmp)
        self.f.worker('recover', slot='ws1', live=False)
        self.record = self.f.store.read(self.f.ids['recover'])
        self.record.runtime = 'codex'
        self.record.golden = str(self.f.pool.slot_path('ws1'))
        self.record.runtime_config_dir = str(self.f.tmp / 'codex-config')
        self.record.runtime_executable = '/bin/true'
        config = Path(self.record.runtime_config_dir) / 'sessions'
        config.mkdir(parents=True)
        self.transcript = config / ('rollout-' + SESSION_ID + '.jsonl')
        self.transcript.write_text(json.dumps(dict(type='session_meta',payload=dict(id=SESSION_ID,cwd=self.record.golden)))+'\n')
        self.f.store.write(self.record)
        write_runtime(self.f.home, 'codex')
        original = self.f.context
        def context():
            build = original()
            def candidate(parsed, out, err):
                ctx = build(parsed, out, err)
                ctx.resume_verified = lambda record, session_id: True
                return ctx
            return candidate
        self.f.context = context

    def args(self):
        return ['revive','--id',self.record.todo_id,'--session-id',SESSION_ID]

    def test_exact_uuid_and_recorded_configuration(self):
        before=snapshot(self.f.tmp)
        code, out, err=self.f.run(self.args()+['--dry-run'])
        self.assertEqual(code,0,err)
        self.assertEqual(snapshot(self.f.tmp),before)
        code,out,err=self.f.run(self.args())
        self.assertEqual(code,0,err)
        launcher=Path(self.record.child_instant)/'.fleet/resume-worker.sh'
        text=launcher.read_text()
        self.assertIn(SESSION_ID,text)
        self.assertIn(self.record.runtime_config_dir,text)
        self.assertNotIn('--last',text)

    def test_wrong_workspace_transcript_refuses_without_launch(self):
        self.transcript.write_text(json.dumps(dict(type='session_meta',payload=dict(id=SESSION_ID,cwd='/another/workspace')))+'\n')
        code,_,err=self.f.run(self.args())
        self.assertEqual(code,4,err)
        self.assertEqual(self.f.started,[])

    def test_missing_transcript_never_starts_fresh(self):
        self.transcript.unlink()
        self.assertEqual(self.f.run(self.args())[0],4)
        self.assertEqual(self.f.started,[])

    def test_runtime_mismatch_refuses(self):
        write_runtime(self.f.home,'claude')
        self.assertEqual(self.f.run(self.args())[0],4)
        self.assertEqual(self.f.started,[])

    def test_occupied_pane_never_starts_another_worker(self):
        self.f.tmux_live.add(self.record.tmux)
        self.assertEqual(self.f.run(self.args())[0], 4)
        self.assertEqual(self.f.started, [])

    def test_closed_worker_cannot_be_revived(self):
        self.record.closed_at = '2026-09-11T00:00:00Z'
        self.f.store.write(self.record)
        self.assertEqual(self.f.run(self.args())[0], 4)
        self.assertEqual(self.f.started, [])
