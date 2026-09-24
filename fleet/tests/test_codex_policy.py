"""FB-110 (D-45): every codex worker fleet launches or resumes runs with the operator's policy — approval=never, inside the
workspace-write sandbox, network on — from ONE place, and never with danger-full-access. Measured on codex-cli 0.156.1
(`codex exec` in a private CODEX_HOME, FB-110): `codex` and `codex resume` both take `-a`, `-s`, `-c` and `--add-dir`;
the sandbox makes `<root>/.git` read-only at the top of each writable root, so a linked-worktree slot can commit only with
its common dir's objects, refs and logs and its own git dir added (never the whole common dir); without GH_TOKEN `gh` acts as whatever account ~/.config/gh names.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from fleet.runtime import LaunchSettings, observe
from fleet.runtime_launch import (CODEX_POLICY, codex_policy_summary, launch_argv, linked_worktrees, prepare,
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
        #: RV-33: `[sandbox_workspace_write] writable_roots` in CODEX_HOME/config.toml still ADDS roots the argv cannot
        #: see, so the row must not read as the whole set.
        self.assertIn('plus any [sandbox_workspace_write] writable_roots in CODEX_HOME/config.toml', summary)


def git(*args, cwd):
    subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', *args], cwd=cwd, check=True,
                   capture_output=True)


def worktree_into(slot, tmp, name='repo'):
    """A linked worktree of a repository outside `slot`, at `slot/name` — ws5's shape."""
    main = tmp / ('main-' + slot.name)
    main.mkdir()
    git('init', '-q', '.', cwd=main)
    git('commit', '-q', '--allow-empty', '-m', 'i', cwd=main)
    git('worktree', 'add', '-q', '--detach', str(slot / name), cwd=main)
    return main


class WorktreeSlotTests(unittest.TestCase):
    """RV-29 / D-51: codex runs only in CLONE slots. A slot whose checkout is a linked worktree could only commit with git
    roots derived from state the worker can touch, which review showed forgeable, so dispatch, revive and resume refuse it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='fb110 wt '))
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_linked_worktrees_finds_a_git_file_at_the_slot_root_or_one_level_down(self):
        slot = self.tmp / 'slot'
        slot.mkdir()
        self.assertEqual(linked_worktrees(slot), ())
        (slot / 'clone').mkdir()
        git('init', '-q', '.', cwd=slot / 'clone')                       # a clone: `.git` is a directory
        (slot / 'deeper' / 'x').mkdir(parents=True)
        (slot / 'deeper' / 'x' / '.git').write_text('gitdir: /elsewhere\n')   # two levels down: not a slot checkout
        self.assertEqual(linked_worktrees(slot), ())
        worktree_into(slot, self.tmp)
        self.assertEqual(linked_worktrees(slot), (str(slot / 'repo'),))
        root_wt = self.tmp / 'rootwt'
        (root_wt).mkdir()
        (root_wt / '.git').write_text('gitdir: /elsewhere\n')             # the slot itself is a worktree
        self.assertEqual(linked_worktrees(root_wt), (str(root_wt),))

    def dispatch(self, f, runtime, *extra):
        from fleet.runtime_config import write_runtime
        write_runtime(f.home, runtime)
        return f.run(['dispatch', '--profile', str(f.profile()), '--title', f'{runtime} task', '--slot', 'ws1', *extra])

    def test_codex_dispatch_into_a_worktree_slot_is_refused_before_any_claim_dry_run_too(self):
        f = Fleet()
        self.addCleanup(shutil.rmtree, f.tmp)
        worktree_into(f.pool.slot_path('ws1'), f.tmp)
        for extra in (['--dry-run'], []):
            with self.subTest(extra=extra):
                code, out, err = self.dispatch(f, 'codex', *extra)
                self.assertEqual(code, 4, out + err)
                self.assertIn('linked git worktree', err)
                self.assertIn('clone', err)                              # clears_when names a clone slot
                self.assertEqual(f.store.all(), [])
                self.assertIsNone(f.pool.lease('ws1'))
                self.assertEqual(f.started, [])

    def test_claude_into_a_worktree_slot_and_codex_into_a_clone_slot_are_admitted(self):
        f = Fleet()
        self.addCleanup(shutil.rmtree, f.tmp)
        worktree_into(f.pool.slot_path('ws1'), f.tmp)
        code, out, err = self.dispatch(f, 'claude', '--dry-run')
        self.assertEqual(code, 0, out + err)
        g = Fleet()
        self.addCleanup(shutil.rmtree, g.tmp)
        (g.pool.slot_path('ws1') / 'repo').mkdir()
        git('init', '-q', '.', cwd=g.pool.slot_path('ws1') / 'repo')
        code, out, err = self.dispatch(g, 'codex')
        self.assertEqual(code, 0, out + err)

    def test_codex_revive_and_resume_in_a_worktree_slot_are_refused(self):
        from tests.test_runtime_revival import RevivalTests
        fixture = RevivalTests('test_exact_uuid_and_recorded_configuration')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        worktree_into(Path(fixture.record.golden), fixture.f.tmp)
        for extra in (['--dry-run'], []):
            with self.subTest(verb='revive', extra=extra):
                code, out, err = fixture.f.run(fixture.args() + extra)
                self.assertEqual(code, 4, out + err)
                self.assertIn('linked git worktree', err)
        self.assertFalse((Path(fixture.record.child_instant) / '.fleet/resume-worker.sh').exists())
        for extra in (['--dry-run'], []):
            with self.subTest(verb='resume', extra=extra):
                code, out, err = fixture.f.run(['resume', '--instant', fixture.record.child_instant, *extra])
                self.assertEqual(code, 4, out + err)
                self.assertIn('linked git worktree', err)


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

    def run_launcher(self, runtime, session_id=None):
        record = rec(child_instant=str(self.root / 'child'), runtime=runtime)
        settings = LaunchSettings(runtime, str(self.binary), str(self.config))
        environ = {'FLEET_HOME': str(self.root / 'store'), 'FLEET_INSTANTS': str(self.root / 'inst'),
                   'HOME': str(self.root / 'home')}
        launcher = prepare(settings, record, self.seed, environ, session_id=session_id)
        env = {k: v for k, v in os.environ.items() if k != 'GH_TOKEN'}
        done = subprocess.run(['bash', str(launcher)], capture_output=True, text=True, check=True, env=env)
        return json.loads(done.stdout)

    def test_launch_and_resume_carry_the_policy_and_only_the_store_and_instants_roots(self):
        """RV-46 / D-51: no git root is ever derived. The slot is the sandbox cwd, and the only added roots are the store
        and the instants directory."""
        for session_id in (None, SESSION_ID):
            with self.subTest(session_id=session_id):
                argv, _ = self.run_launcher('codex', session_id)
                self.assertEqual(argv[argv.index('-a'):argv.index('-a') + len(POLICY)], POLICY)
                roots = [argv[i + 1] for i, item in enumerate(argv) if item == '--add-dir']
                self.assertEqual(roots, [str((self.root / 'store').resolve()), str((self.root / 'inst').resolve())])

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


class DryRunTests(unittest.TestCase):
    def test_a_codex_dispatch_dry_run_names_the_policy_and_claude_prints_none(self):
        """RV-36. The dry-run answers the same question as the real call, before a slot is claimed."""
        from fleet.runtime_config import write_runtime
        f = Fleet()
        self.addCleanup(shutil.rmtree, f.tmp)
        for runtime, expected in (('codex', 1), ('claude', 0)):
            with self.subTest(runtime=runtime):
                write_runtime(f.home, runtime)
                code, out, err = f.run(['dispatch', '--profile', str(f.profile()), '--title', 'dry task', '--dry-run'])
                self.assertEqual(code, 0, err)
                rows = [line for line in out.splitlines() if line.startswith('codex_policy')]
                self.assertEqual(len(rows), expected, out)
                if expected:
                    self.assertIn('approval=never', rows[0])
                self.assertEqual(f.store.all(), [])


class ReviveTests(unittest.TestCase):
    """`revive` relaunches with the same policy, and its dry-run says so before anything starts."""

    def test_revive_dry_run_names_the_policy_and_the_resume_launcher_carries_it(self):
        from tests.test_runtime_revival import RevivalTests, SESSION_ID as REVIVE_ID
        fixture = RevivalTests('test_exact_uuid_and_recorded_configuration')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        clone = Path(fixture.record.golden) / 'repo'                 # D-51: codex slots are CLONE-shaped
        clone.mkdir()
        git('init', '-q', '.', cwd=clone)
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
        self.assertEqual(text.count('--add-dir'), 2, text)          # RV-46: the store and the instants dir, nothing else


class DialogRowTests(unittest.TestCase):
    """FB-105: codex 0.156's trust screen ends `enter continue · esc quit`, which pane-guard read as 14 unrecognized.
    The trust and approval frames are real captures from a 0.156.1 pane; the update modal has none (DEC-9)."""

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
