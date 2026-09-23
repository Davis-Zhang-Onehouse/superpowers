"""pt2 (coordinator D-22/D-33): the coordinator chooses each worker's runtime and model AT DISPATCH.

The box's saved runtime (`fleet runtime --set`) and the slot's own CLI configuration are only DEFAULTS. A dispatch
flag wins over a profile field, a profile field over the box, and with neither the launch is exactly today's —
asserted here on the literal `exec` line, not on the absence of a flag. The chosen runtime and model live on the
record, so `revive` relaunches the same pair and `resume` adopts under the record's runtime, whatever the box says.
"""
import json
from pathlib import Path
import shutil
import unittest

from fleet.errors import BadInput
from fleet.profiles import Profile
from fleet.runtime import LaunchSettings, choose_runtime, validate_model
from fleet.runtime_config import read_runtime, write_runtime
from fleet.runtime_launch import launch_argv, resume_argv
from fleet.session import LiveSession
from fleet.store import Record
from tests.test_cli import Fleet
from tests.test_store import rec

SESSION_ID = '12345678-1234-1234-1234-123456789abc'


class ResolutionTests(unittest.TestCase):
    """flag > profile > box for the runtime; flag > profile (same runtime only) > none for the model."""

    def test_neither_given_is_the_box_and_no_model(self):
        for box in ('claude', 'codex'):
            choice = choose_runtime(box)
            self.assertEqual((choice.runtime, choice.model), (box, ''))
            self.assertEqual((choice.runtime_source, choice.model_source), ('box', 'default'))

    def test_the_flag_wins_over_profile_and_box(self):
        choice = choose_runtime('claude', flag_runtime='codex', profile_runtime='claude')
        self.assertEqual((choice.runtime, choice.runtime_source), ('codex', 'flag'))
        choice = choose_runtime('codex', flag_model='claude-fable-5-1', flag_runtime='claude')
        self.assertEqual((choice.runtime, choice.model, choice.model_source), ('claude', 'claude-fable-5-1', 'flag'))

    def test_the_profile_wins_over_the_box(self):
        choice = choose_runtime('claude', profile_runtime='codex', profile_model='gpt-x')
        self.assertEqual((choice.runtime, choice.model), ('codex', 'gpt-x'))
        self.assertEqual((choice.runtime_source, choice.model_source), ('profile', 'profile'))

    def test_a_profile_model_never_crosses_a_runtime_override(self):
        """A model name belongs to one CLI: `claude-opus-…` handed to codex is a launch that dies."""
        choice = choose_runtime('claude', flag_runtime='codex', profile_runtime='claude', profile_model='opus')
        self.assertEqual((choice.runtime, choice.model, choice.model_source), ('codex', '', 'default'))

    def test_a_flag_model_applies_to_whatever_runtime_resolved(self):
        choice = choose_runtime('claude', flag_model='fable')
        self.assertEqual((choice.runtime, choice.model, choice.model_source), ('claude', 'fable', 'flag'))

    def test_bad_values_are_refused(self):
        with self.assertRaises(BadInput):
            choose_runtime('claude', flag_runtime='gemini')
        for bad in ('', ' ', '-m', '--dangerously-skip-permissions', 'a b', 'x;y', 'a\nb'):
            with self.subTest(model=bad), self.assertRaises(BadInput):
                validate_model(bad)
        for good in ('claude-fable-5-1', 'claude-opus-5-5[1m]', 'gpt-6-sol', 'o3', 'openai/gpt-5.1:high'):
            self.assertEqual(validate_model(good), good)


class ArgvTests(unittest.TestCase):
    def test_default_argv_is_byte_identical_to_the_base(self):
        """(c). The exact lists the base emitted, typed out — a missing flag is not the same claim."""
        claude = LaunchSettings('claude', '/b/claude', '/cfg')
        codex = LaunchSettings('codex', '/b/codex', '/cfg')
        self.assertEqual(launch_argv(claude, 'P'), ['/b/claude', '--permission-mode', 'auto', '--', 'P'])
        self.assertEqual(launch_argv(codex, 'P', ('/w',)), ['/b/codex', '--add-dir', '/w', '--', 'P'])
        self.assertEqual(resume_argv(claude, SESSION_ID),
                         ['/b/claude', '--permission-mode', 'auto', '--resume', SESSION_ID])
        self.assertEqual(resume_argv(codex, SESSION_ID, ('/w',)), ['/b/codex', 'resume', '--add-dir', '/w', '--', SESSION_ID])

    def test_a_model_reaches_the_argv_of_launch_and_resume(self):
        claude = LaunchSettings('claude', '/b/claude', '/cfg', 'claude-fable-5-1')
        codex = LaunchSettings('codex', '/b/codex', '/cfg', 'gpt-x')
        self.assertEqual(launch_argv(claude, 'P'),
                         ['/b/claude', '--permission-mode', 'auto', '--model', 'claude-fable-5-1', '--', 'P'])
        self.assertEqual(launch_argv(codex, 'P', ('/w',)), ['/b/codex', '--add-dir', '/w', '-m', 'gpt-x', '--', 'P'])
        self.assertEqual(resume_argv(claude, SESSION_ID),
                         ['/b/claude', '--permission-mode', 'auto', '--model', 'claude-fable-5-1',
                          '--resume', SESSION_ID])
        self.assertEqual(resume_argv(codex, SESSION_ID, ('/w',)),
                         ['/b/codex', 'resume', '--add-dir', '/w', '-m', 'gpt-x', '--', SESSION_ID])


class RecordTests(unittest.TestCase):
    def test_an_empty_model_is_not_written_so_an_older_binary_still_reads_the_record(self):
        record = rec()
        self.assertNotIn('runtime_model', record.to_json())
        self.assertEqual(Record.from_json(record.to_json()).runtime_model, '')

    def test_a_default_record_has_exactly_the_base_schema(self):
        """RV-27. A record carrying `runtime_model` makes an older binary refuse the WHOLE store (its `Store.all()`
        raises on the unknown key), so the one thing that must never happen is a DEFAULT dispatch writing it. The
        base's key set is typed out here, not derived, so a new always-written field fails this test."""
        base_keys = {'todo_id', 'child_instant', 'base_instant', 'slot', 'tmux', 'profile', 'golden', 'lineage_base',
                     'lineage_mode', 'golden_base', 'title', 'override_reason', 'milestone', 'root', 'dispatched_at',
                     'tmux_socket', 'runtime', 'runtime_executable', 'runtime_config_dir', 'launched_at',
                     'gate_verdict', 'harvested_at', 'closed_at', 'schema_version'}
        self.assertEqual(set(rec().to_json()), base_keys)
        self.assertEqual(set(rec(runtime_model='gpt-x').to_json()) - base_keys, {'runtime_model'})

    def test_a_model_round_trips(self):
        record = rec(runtime='codex', runtime_model='gpt-x')
        self.assertEqual(Record.from_json(json.loads(json.dumps(record.to_json()))).runtime_model, 'gpt-x')

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.f = Fleet()
        self.addCleanup(shutil.rmtree, self.f.tmp)

    def manifest(self, **fields):
        path = self.f.profile()
        (path / 'profile.json').write_text(json.dumps(dict(kind='worker', **fields)))
        return path

    def test_profile_fields_load(self):
        profile = Profile.load(self.manifest(runtime='codex', model='gpt-x'))
        self.assertEqual((profile.runtime, profile.model), ('codex', 'gpt-x'))
        profile = Profile.load(self.f.profile())
        self.assertEqual((profile.runtime, profile.model), ('', ''))

    def test_a_profile_model_without_its_runtime_is_refused(self):
        with self.assertRaises(BadInput) as caught:
            Profile.load(self.manifest(model='opus'))
        self.assertIn('runtime', str(caught.exception))

    def test_bad_profile_values_are_refused(self):
        for fields in (dict(runtime='gemini'), dict(runtime='claude', model='-x'), dict(runtime=3)):
            with self.subTest(fields=fields), self.assertRaises(BadInput):
                Profile.load(self.manifest(**fields))


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.f = Fleet()
        self.addCleanup(shutil.rmtree, self.f.tmp)

    def dispatch(self, *extra, profile=None, code=0):
        got, out, err = self.f.run(['dispatch', '--profile', str(profile or self.f.profile()),
                                    '--title', 'choice task', *extra])
        self.assertEqual(got, code, err)
        return out, err

    def launched(self):
        record = self.f.store.all()[0]
        return record, (Path(record.child_instant) / '.fleet/launch-worker.sh').read_text()

    def exec_line(self, text):
        return [line for line in text.splitlines() if line.startswith('exec ')][0]

    def test_default_dispatch_launches_exactly_as_the_base_did(self):
        """(c). The box runtime, no model flag, and the base's exec line character for character."""
        self.dispatch()
        record, text = self.launched()
        self.assertEqual((record.runtime, record.runtime_model), ('claude', ''))
        self.assertNotIn('runtime_model', json.loads((self.f.home / 'records' / f'{record.todo_id}.json').read_text()))
        self.assertEqual(self.exec_line(text),
                         f"exec /test/bin/claude --permission-mode auto --remote-control {record.tmux} -- "
                         f"\"$(cat -- \"$seed_file\")\"")
        self.assertEqual(read_runtime(self.f.home), ('claude', 'legacy-default'))

    def test_a_codex_dispatch_on_a_claude_box_is_admitted_and_launched_as_codex(self):
        """(b)/(3). The box stays claude; the record and the launcher are codex; the box file is never written."""
        write_runtime(self.f.home, 'claude')
        box = (self.f.home / 'runtime.json').read_bytes()
        out, _ = self.dispatch('--runtime', 'codex')
        record, text = self.launched()
        self.assertEqual((record.runtime, record.runtime_executable, record.runtime_model),
                         ('codex', '/test/bin/codex', ''))
        self.assertIn('exec /test/bin/codex ', text)
        self.assertIn('CODEX_HOME=', text)
        self.assertNotIn(' -m ', self.exec_line(text))
        self.assertEqual((self.f.home / 'runtime.json').read_bytes(), box)
        self.assertIn('codex', out)

    def test_a_model_is_launched_and_recorded(self):
        """(a). `--model` reaches the worker's argv and the record; no slot config is touched."""
        self.dispatch('--model', 'claude-fable-5-1')
        record, text = self.launched()
        self.assertEqual((record.runtime, record.runtime_model), ('claude', 'claude-fable-5-1'))
        self.assertIn('--model claude-fable-5-1', self.exec_line(text))

    def test_profile_fields_are_the_default_and_the_flags_win(self):
        profile = self.f.profile()
        (profile / 'profile.json').write_text(json.dumps(dict(kind='worker', runtime='codex', model='gpt-x')))
        self.dispatch(profile=profile)
        record, text = self.launched()
        self.assertEqual((record.runtime, record.runtime_model), ('codex', 'gpt-x'))
        self.assertIn('-m gpt-x', self.exec_line(text))

    def test_a_runtime_flag_drops_the_profiles_model(self):
        profile = self.f.profile()
        (profile / 'profile.json').write_text(json.dumps(dict(kind='worker', runtime='codex', model='gpt-x')))
        self.dispatch('--runtime', 'claude', profile=profile)
        record, text = self.launched()
        self.assertEqual((record.runtime, record.runtime_model), ('claude', ''))
        self.assertNotIn('gpt-x', text)

    def test_the_dry_run_names_the_choice_and_its_source(self):
        out, _ = self.dispatch('--runtime', 'codex', '--model', 'gpt-x', '--dry-run')
        self.assertIn('codex (flag)', out)
        self.assertIn('gpt-x (flag)', out)
        self.assertEqual(self.f.store.all(), [])
        out, _ = self.dispatch('--dry-run')
        self.assertIn('claude (box', out)
        self.assertIn('(none', out)

    def test_bad_flags_are_refused_before_anything_is_claimed(self):
        for extra in (('--runtime', 'gemini'), ('--model', '--dangerously-skip-permissions')):
            with self.subTest(extra=extra):
                self.dispatch(*extra, code=2)
                self.assertEqual(self.f.store.all(), [])
                self.assertIsNone(self.f.pool.lease('ws1'))

    def test_seed_delivery_is_probed_as_the_chosen_runtime(self):
        """At base the dispatch's own delivery check probed with the BOX runtime, so a codex worker on a claude box
        was looked for as `claude` and read NOT-DELIVERED — the dispatch rolled back."""
        from fleet import cli
        seen = []
        original = self.f.context
        def context():
            build = original()
            def candidate(parsed, out, err):
                ctx = build(parsed, out, err)
                ctx.seed_delivery = None
                return ctx
            return candidate
        self.f.context = context
        from unittest import mock
        from fleet import seedcheck
        def verify(ctx, tmux, seed, probes=None, sleep=None, runtime=None):
            seen.append(runtime)
            return seedcheck.Verdict(seedcheck.ATTESTED, detail='fixture')
        with mock.patch.object(cli, '_verify_seed_delivery', verify):
            self.dispatch('--runtime', 'codex')
        self.assertEqual(seen, ['codex'])


class RecoveryTests(unittest.TestCase):
    """(3)/(d). revive and resume follow the RECORD's runtime and model, not the box."""

    def setUp(self):
        self.f = Fleet()
        self.addCleanup(shutil.rmtree, self.f.tmp)

    def revivable(self, runtime, model=''):
        self.f.worker('recover', slot='ws1', live=False)
        record = self.f.store.read(self.f.ids['recover'])
        record.runtime, record.runtime_model = runtime, model
        record.golden = str(self.f.pool.slot_path('ws1'))
        record.runtime_config_dir = str(self.f.tmp / (runtime + '-config'))
        record.runtime_executable = '/bin/true'
        if runtime == 'codex':
            where = Path(record.runtime_config_dir) / 'sessions'
            where.mkdir(parents=True)
            (where / ('rollout-' + SESSION_ID + '.jsonl')).write_text(json.dumps(dict(
                type='session_meta', payload=dict(id=SESSION_ID, cwd=record.golden))) + '\n')
        else:
            where = Path(record.runtime_config_dir) / 'projects' / 'slot'
            where.mkdir(parents=True)
            (where / (SESSION_ID + '.jsonl')).write_text(json.dumps(dict(sessionId=SESSION_ID, cwd=record.golden)) + '\n')
        self.f.store.write(record)
        return record

    def revive(self, record):
        return self.f.run(['revive', '--id', record.todo_id, '--session-id', SESSION_ID])

    def test_a_codex_record_revives_as_codex_on_a_claude_box(self):
        write_runtime(self.f.home, 'claude')
        record = self.revivable('codex')
        code, out, err = self.revive(record)
        self.assertEqual(code, 0, err)
        text = (Path(record.child_instant) / '.fleet/resume-worker.sh').read_text()
        self.assertIn(f'exec /bin/true resume', text)
        self.assertIn('CODEX_HOME=', text)
        self.assertEqual(read_runtime(self.f.home), ('claude', 'saved'))

    def test_a_revive_relaunches_the_recorded_model(self):
        """(d)."""
        record = self.revivable('claude', 'claude-fable-5-1')
        code, out, err = self.revive(record)
        self.assertEqual(code, 0, err)
        text = (Path(record.child_instant) / '.fleet/resume-worker.sh').read_text()
        self.assertIn(f'--model claude-fable-5-1 --resume {SESSION_ID}', text)
        self.assertIn('claude-fable-5-1', out)
        self.assertEqual(self.f.store.read(record.todo_id).runtime_model, 'claude-fable-5-1')

    def test_a_malformed_recorded_model_never_reaches_an_argv(self):
        record = self.revivable('claude', '--dangerously-skip-permissions')
        code, _, err = self.revive(record)
        self.assertEqual(code, 2, err)
        self.assertEqual(self.f.started, [])

    def test_resume_adopts_under_the_records_runtime(self):
        self.f.worker('original', slot='ws1', live=False)
        record = self.f.store.read(self.f.ids['original'])
        record.runtime, record.runtime_model = 'codex', 'gpt-x'
        self.f.store.write(record)
        code, _, err = self.f.run(['resume', '--instant', str(self.f.paths['original'])])
        self.assertEqual(code, 0, err)
        again = self.f.store.read(record.todo_id)
        self.assertEqual((again.runtime, again.runtime_model), ('codex', 'gpt-x'))

    def test_resume_still_refuses_a_live_session_of_another_runtime_than_its_record(self):
        path = self.f.worker('original', slot='ws1', live=False)
        record = self.f.store.read(self.f.ids['original'])
        record.runtime = 'codex'
        self.f.store.write(record)
        self.f.procs.append(LiveSession(pid=4321, cwd=path, name=record.tmux, runtime='claude'))
        self.f.tmux_live.add(record.tmux)
        code, _, err = self.f.run(['resume', '--instant', str(path)])
        self.assertEqual(code, 4, err)


class SurfaceTests(unittest.TestCase):
    def setUp(self):
        self.f = Fleet()
        self.addCleanup(shutil.rmtree, self.f.tmp)

    def test_pane_guard_by_session_name_observes_a_codex_record_as_codex_on_a_claude_box(self):
        """(4). `--pane` used the box layer, so a codex worker read `14 runtime differs`; `--id` never did."""
        path = self.f.worker('coder', slot='ws1', live=False)
        record = self.f.store.read(self.f.ids['coder'])
        record.runtime = 'codex'
        self.f.store.write(record)
        self.f.procs.append(LiveSession(pid=4400, cwd=path, name=record.tmux, runtime='codex'))
        self.f.tmux_live.add(record.tmux)
        frames = Path(__file__).resolve().parents[1] / 'it/fixtures/runtime'
        self.f.panes[record.tmux] = (frames / 'codex-idle.frame').read_text()
        by_id = self.f.run(['pane-guard', '--id', record.todo_id])
        by_pane = self.f.run(['pane-guard', '--pane', record.tmux])
        self.assertEqual(by_id[0], 0, by_id)
        self.assertEqual(by_pane[0], 0, by_pane)

    def test_brief_names_the_runtime_and_model_the_instant_runs_on(self):
        path = self.f.worker('coder', slot='ws1', live=False)
        record = self.f.store.read(self.f.ids['coder'])
        record.runtime, record.runtime_model = 'codex', 'gpt-x'
        self.f.store.write(record)
        code, out, err = self.f.run(['brief', '--instant', str(path)])
        row = [line for line in out.splitlines() if line.startswith('runtime')]
        self.assertEqual(len(row), 1, out)
        self.assertIn('runtime=codex model=gpt-x', row[0])

    def test_status_evidence_carries_the_model(self):
        self.f.worker('coder', slot='ws1', live=False)
        record = self.f.store.read(self.f.ids['coder'])
        record.runtime, record.runtime_model = 'codex', 'gpt-x'
        self.f.store.write(record)
        code, out, err = self.f.run(['status', '--id', record.todo_id])
        self.assertIn('gpt-x', out + err)
        code, out, err = self.f.run(['board'])
        self.assertIn('gpt-x', out)


if __name__ == '__main__':
    unittest.main()
