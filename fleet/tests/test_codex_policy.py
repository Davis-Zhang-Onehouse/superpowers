"""FB-110 (D-45): every codex worker fleet launches or resumes runs with the operator's policy — approval=never, inside the
workspace-write sandbox, network on — from ONE place, and never with danger-full-access. Measured on codex-cli 0.156.1
(the instant's evidence/01-settle/settle.txt): `codex` and `codex resume` both take `-a`, `-s`, `-c` and `--add-dir`;
the sandbox makes `<root>/.git` read-only at the top of each writable root, so a linked-worktree slot can commit only with
its git common dir added; without GH_TOKEN `gh` acts as whatever account ~/.config/gh names.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from fleet.runtime import LaunchSettings, observe
from fleet.runtime_launch import (CODEX_POLICY, codex_policy_summary, git_writable_dirs, launch_argv, prepare,
                                  resume_argv)
from fleet.workspace import default_git
from tests.test_cli import Fleet
from tests.test_store import rec

SESSION_ID = '12345678-1234-1234-1234-123456789abc'
POLICY = ['-a', 'never', '-s', 'workspace-write', '-c', 'sandbox_workspace_write.network_access=true',
          '-c', 'check_for_update_on_startup=false']
FRAMES = Path(__file__).resolve().parents[1] / 'it/fixtures/runtime'


class PolicyArgvTests(unittest.TestCase):
    def test_launch_and_resume_carry_the_same_policy_before_the_roots_and_model(self):
        codex = LaunchSettings('codex', '/b/codex', '/cfg')
        self.assertEqual(list(CODEX_POLICY), POLICY)
        self.assertEqual(launch_argv(codex, 'P', ('/w',)), ['/b/codex', *POLICY, '--add-dir', '/w', '--', 'P'])
        self.assertEqual(resume_argv(codex, SESSION_ID, ('/w',)),
                         ['/b/codex', 'resume', *POLICY, '--add-dir', '/w', '--', SESSION_ID])
        modelled = LaunchSettings('codex', '/b/codex', '/cfg', 'gpt-x')
        self.assertEqual(launch_argv(modelled, 'P'), ['/b/codex', *POLICY, '-m', 'gpt-x', '--', 'P'])
        self.assertEqual(resume_argv(modelled, SESSION_ID), ['/b/codex', 'resume', *POLICY, '-m', 'gpt-x', '--', SESSION_ID])

    def test_no_codex_argv_can_carry_full_access_or_a_bypass(self):
        codex = LaunchSettings('codex', '/b/codex', '/cfg', 'gpt-x')
        for argv in (launch_argv(codex, 'P', ('/w', '/x')), resume_argv(codex, SESSION_ID, ('/w',))):
            joined = ' '.join(argv)
            self.assertNotIn('danger-full-access', joined)
            self.assertNotIn('dangerously', joined)
            self.assertNotIn('--approve-for-me', joined)
            self.assertEqual(argv.count('-a'), 1)
            self.assertEqual(argv.count('-s'), 1)

    def test_claude_argv_is_untouched(self):
        claude = LaunchSettings('claude', '/b/claude', '/cfg')
        self.assertEqual(launch_argv(claude, 'P'), ['/b/claude', '--permission-mode', 'auto', '--', 'P'])
        self.assertEqual(resume_argv(claude, SESSION_ID), ['/b/claude', '--permission-mode', 'auto', '--resume', SESSION_ID])

    def test_the_summary_names_the_policy_and_every_root(self):
        summary = codex_policy_summary(('/store', '/instants'))
        for needle in ('approval=never', 'sandbox=workspace-write', 'network=on', 'update-check=off',
                       'the slot (cwd)', '/store', '/instants'):
            self.assertIn(needle, summary)


def git(*args, cwd):
    subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', *args], cwd=cwd, check=True,
                   capture_output=True)


class GitRootsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='fb110 '))
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_a_linked_worktree_adds_its_common_dir_and_a_nested_clone_adds_its_own(self):
        main, slot = self.tmp / 'main', self.tmp / 'slot'
        main.mkdir()
        slot.mkdir()
        git('init', '-q', '.', cwd=main)
        git('commit', '-q', '--allow-empty', '-m', 'i', cwd=main)
        git('worktree', 'add', '-q', '--detach', str(slot / 'wt'), cwd=main)
        (slot / 'clone').mkdir()
        git('init', '-q', '.', cwd=slot / 'clone')
        (slot / 'plain').mkdir()
        (slot / 'deeper' / 'repo').mkdir(parents=True)
        git('init', '-q', '.', cwd=slot / 'deeper' / 'repo')           # two levels down: not a slot repo
        got = git_writable_dirs(slot, default_git())
        self.assertEqual(sorted(got), sorted([str((main / '.git').resolve()), str((slot / 'clone' / '.git').resolve())]))

    def test_a_slot_that_is_itself_a_repo_adds_its_own_git_dir(self):
        git('init', '-q', '.', cwd=self.tmp)
        self.assertEqual(git_writable_dirs(self.tmp, default_git()), (str((self.tmp / '.git').resolve()),))

    def test_no_repo_and_a_failing_git_add_nothing(self):
        self.assertEqual(git_writable_dirs(self.tmp, default_git()), ())
        (self.tmp / 'r').mkdir()
        (self.tmp / 'r' / '.git').mkdir()
        self.assertEqual(git_writable_dirs(self.tmp, lambda args, cwd: (128, '')), ())


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='fb110 prepare '))
        self.addCleanup(shutil.rmtree, self.root)
        self.binary = self.root / 'agent'
        self.binary.write_text('#!/usr/bin/env python3\nimport json,os,sys\n'
                               'print(json.dumps([sys.argv[1:], os.environ.get("GH_TOKEN")]))\n')
        self.binary.chmod(0o700)
        self.seed = self.root / 'child/.fleet/seed.txt'
        self.seed.parent.mkdir(parents=True)
        self.seed.write_text('task')
        (self.root / 'home').mkdir()
        (self.root / 'home' / '.gh-token-davis').write_text('tok-davis\n')
        self.config = self.root / 'davis_root' / '.codex'
        self.config.mkdir(parents=True)

    def run_launcher(self, runtime, session_id=None, extra=()):
        record = rec(child_instant=str(self.root / 'child'), runtime=runtime)
        settings = LaunchSettings(runtime, str(self.binary), str(self.config))
        environ = {'FLEET_HOME': str(self.root / 'store'), 'FLEET_INSTANTS': str(self.root / 'inst'),
                   'HOME': str(self.root / 'home')}
        launcher = prepare(settings, record, self.seed, environ, session_id=session_id, extra_writable=extra)
        env = {k: v for k, v in os.environ.items() if k != 'GH_TOKEN'}
        done = subprocess.run(['bash', str(launcher)], capture_output=True, text=True, check=True, env=env)
        return json.loads(done.stdout)

    def test_launch_and_resume_both_carry_the_policy_the_roots_and_the_git_dirs(self):
        for session_id in (None, SESSION_ID):
            with self.subTest(session_id=session_id):
                argv, _ = self.run_launcher('codex', session_id, extra=('/shared/.git',))
                self.assertEqual(argv[argv.index('-a'):argv.index('-a') + len(POLICY)], POLICY)
                roots = [argv[i + 1] for i, item in enumerate(argv) if item == '--add-dir']
                self.assertEqual(roots, [str((self.root / 'store').resolve()), str((self.root / 'inst').resolve()),
                                         '/shared/.git'])

    def test_codex_gets_the_same_gh_token_rule_as_claude(self):
        for runtime in ('claude', 'codex'):
            with self.subTest(runtime=runtime):
                _, token = self.run_launcher(runtime)
                self.assertEqual(token, 'tok-davis')


class VisibilityTests(unittest.TestCase):
    def setUp(self):
        self.f = Fleet()
        self.addCleanup(shutil.rmtree, self.f.tmp)

    def test_brief_shows_the_effective_codex_policy_and_claude_shows_none(self):
        path = self.f.worker('coder', slot='ws1', live=False)
        record = self.f.store.read(self.f.ids['coder'])
        record.runtime = 'codex'
        self.f.store.write(record)
        code, out, err = self.f.run(['brief', '--instant', str(path)])
        row = [line for line in out.splitlines() if line.startswith('runtime')]
        self.assertEqual(len(row), 1, out)
        self.assertIn('approval=never', row[0])
        self.assertIn('sandbox=workspace-write', row[0])
        record.runtime = 'claude'
        self.f.store.write(record)
        code, out, err = self.f.run(['brief', '--instant', str(path)])
        self.assertNotIn('approval=never', out)

    def test_a_codex_dispatch_prints_its_policy_and_records_no_new_field(self):
        from fleet.runtime_config import write_runtime
        write_runtime(self.f.home, 'codex')
        code, out, err = self.f.run(['dispatch', '--profile', str(self.f.profile()), '--title', 'codex task'])
        self.assertEqual(code, 0, err)
        rows = [line for line in out.splitlines() if 'codex_policy' in line]
        self.assertEqual(len(rows), 1, out)
        self.assertIn('approval=never', rows[0])
        record = self.f.store.all()[0]
        stored = json.loads((self.f.home / 'records' / f'{record.todo_id}.json').read_text())
        self.assertFalse(any('policy' in key or 'sandbox' in key for key in stored), stored)
        launcher = (Path(record.child_instant) / '.fleet/launch-worker.sh').read_text()
        self.assertIn('-a never -s workspace-write', launcher)


class DispatchRootsTests(unittest.TestCase):
    def test_a_codex_dispatch_into_a_worktree_slot_hands_the_common_dir_to_the_launcher(self):
        from fleet.runtime_config import write_runtime
        f = Fleet()
        self.addCleanup(shutil.rmtree, f.tmp)
        f.git = default_git()                                   # the real seam: this asks git, not a fake
        main = f.tmp / 'main'
        main.mkdir()
        git('init', '-q', '.', cwd=main)
        git('commit', '-q', '--allow-empty', '-m', 'i', cwd=main)
        slot = f.pool.slot_path('ws1')
        git('worktree', 'add', '-q', '--detach', str(slot / 'repo'), cwd=main)
        write_runtime(f.home, 'codex')
        code, out, err = f.run(['dispatch', '--profile', str(f.profile()), '--title', 'codex task', '--slot', 'ws1'])
        self.assertEqual(code, 0, err)
        common = str((main / '.git').resolve())
        record = f.store.all()[0]
        launcher = (Path(record.child_instant) / '.fleet/launch-worker.sh').read_text()
        self.assertIn('--add-dir ' + common, launcher)
        self.assertIn(common, [line for line in out.splitlines() if 'codex_policy' in line][0])


class ReviveTests(unittest.TestCase):
    """`revive` relaunches with the same policy, and its dry-run says so before anything starts."""

    def test_revive_dry_run_names_the_policy_and_the_resume_launcher_carries_it(self):
        from tests.test_runtime_revival import RevivalTests, SESSION_ID as REVIVE_ID
        fixture = RevivalTests('test_exact_uuid_and_recorded_configuration')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.f.git = default_git()                           # the real seam, over a worktree-shaped slot
        main = fixture.f.tmp / 'main'
        main.mkdir()
        git('init', '-q', '.', cwd=main)
        git('commit', '-q', '--allow-empty', '-m', 'i', cwd=main)
        git('worktree', 'add', '-q', '--detach', str(Path(fixture.record.golden) / 'repo'), cwd=main)
        common = str((main / '.git').resolve())
        args = fixture.args()
        code, out, err = fixture.f.run(args + ['--dry-run'])
        self.assertEqual(code, 0, err)
        rows = [line for line in out.splitlines() if line.startswith('codex_policy')]
        self.assertEqual(len(rows), 1, out)
        self.assertIn('approval=never', rows[0])
        code, out, err = fixture.f.run(args)
        self.assertEqual(code, 0, err)
        self.assertIn('approval=never', out)
        text = (Path(fixture.record.child_instant) / '.fleet/resume-worker.sh').read_text()
        self.assertIn('resume -a never -s workspace-write -c sandbox_workspace_write.network_access=true', text)
        self.assertIn(REVIVE_ID, text)
        self.assertIn('--add-dir ' + common, text)


class DialogRowTests(unittest.TestCase):
    """FB-105: codex 0.156's trust screen (and its update modal, same hint row) end `enter continue · esc …`,
    which pane-guard read as 14 unrecognized. Both frames are real captures from a 0.156.1 pane."""

    def test_0156_trust_screen_is_a_dialog(self):
        self.assertEqual(observe('codex', (FRAMES / 'codex-trust-0156.frame').read_text()).state, 'dialog')

    def test_0156_approval_prompt_stays_a_dialog(self):
        self.assertEqual(observe('codex', (FRAMES / 'codex-approval-0156.frame').read_text()).state, 'dialog')

    def test_prose_quoting_the_hint_mid_row_is_not_a_dialog(self):
        frame = (FRAMES / 'codex-idle.frame').read_text()
        self.assertNotEqual(observe('codex', frame).state, 'dialog')
        quoted = frame.replace('Ask Codex to do anything',
                               'the screen said: enter continue · esc quit', 1)
        self.assertNotEqual(observe('codex', quoted).state, 'dialog')


if __name__ == '__main__':
    unittest.main()
