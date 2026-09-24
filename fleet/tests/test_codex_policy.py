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
        #: RV-33: `[sandbox_workspace_write] writable_roots` in CODEX_HOME/config.toml still ADDS roots the argv cannot
        #: see, so the row must not read as the whole set.
        self.assertIn('plus any [sandbox_workspace_write] writable_roots in CODEX_HOME/config.toml', summary)


def git(*args, cwd):
    subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', *args], cwd=cwd, check=True,
                   capture_output=True)


def worktree_roots(main, name):
    """RV-28. What a linked worktree must write to commit, fetch and branch, measured on codex-cli 0.156.1
    (measured in a private CODEX_HOME, FB-110), and nothing else: never the common dir itself, whose hooks/
    and config would let a sandboxed worker plant code the next unsandboxed git run executes (R1: both ALLOWED)."""
    common = (main / '.git').resolve()
    return [str(common / 'objects'), str(common / 'refs'), str(common / 'logs'), str(common / 'worktrees' / name)]


class GitRootsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='fb110 '))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.main, self.slot = self.tmp / 'main', self.tmp / 'slot'
        self.main.mkdir()
        self.slot.mkdir()
        git('init', '-q', '.', cwd=self.main)
        git('commit', '-q', '--allow-empty', '-m', 'i', cwd=self.main)

    def test_a_linked_worktree_adds_only_what_a_commit_writes_and_never_hooks_or_config(self):
        git('worktree', 'add', '-q', '--detach', str(self.slot / 'wt'), cwd=self.main)
        (self.slot / 'clone').mkdir()
        git('init', '-q', '.', cwd=self.slot / 'clone')                 # nested clone: commits inside the cwd already
        (self.slot / 'plain').mkdir()
        (self.slot / 'deeper' / 'repo').mkdir(parents=True)
        git('init', '-q', '.', cwd=self.slot / 'deeper' / 'repo')       # two levels down: not a slot repo
        got = git_writable_dirs(self.slot, default_git())
        self.assertEqual(sorted(got), sorted(worktree_roots(self.main, 'wt')))
        common = str((self.main / '.git').resolve())
        self.assertNotIn(common, got)
        self.assertFalse(any(root.endswith(('/hooks', '/config')) for root in got), got)

    def test_a_slot_that_is_itself_a_repo_or_a_clone_adds_nothing(self):
        """Its `.git` sits in the cwd: codex protects a TOP-level `.git` for the same hooks reason, and a slot that is
        itself a repo is not a fleet shape today (ws5 is a worktree, ws8-10 hold nested clones)."""
        git('init', '-q', '.', cwd=self.slot)
        self.assertEqual(git_writable_dirs(self.slot, default_git()), ())

    def test_slot_contents_a_worker_can_plant_choose_no_root(self):
        """RV-29. The slot is writable by the worker, and roots are re-derived at every revive and dispatch, so nothing
        a worker can create there may name a root: a symlink to someone else's worktree, or a `.git` file pointing at
        another repository or at another worktree's git dir. Git's own back-link (`<git dir>/gitdir` naming this
        `.git`) is the proof a worktree is really this one. For ANOTHER repository only that repository can write it;
        a git dir forged inside the slot is refused separately (the common dir must lie outside the slot)."""
        other = self.tmp / 'other'
        other.mkdir()
        git('init', '-q', '.', cwd=other)
        git('commit', '-q', '--allow-empty', '-m', 'i', cwd=other)
        git('worktree', 'add', '-q', '--detach', str(self.tmp / 'elsewhere' / 'wt'), cwd=other)
        (self.slot / 'link').symlink_to(self.tmp / 'elsewhere' / 'wt', target_is_directory=True)
        (self.slot / 'planted-repo').mkdir()
        (self.slot / 'planted-repo' / '.git').write_text(f'gitdir: {other / ".git"}\n')
        (self.slot / 'planted-wt').mkdir()
        (self.slot / 'planted-wt' / '.git').write_text(f'gitdir: {other / ".git" / "worktrees" / "wt"}\n')
        self.assertEqual(git_writable_dirs(self.slot, default_git()), ())
        git('worktree', 'add', '-q', '--detach', str(self.slot / 'mine'), cwd=self.main)    # the neighbour still counts
        self.assertEqual(sorted(git_writable_dirs(self.slot, default_git())), sorted(worktree_roots(self.main, 'mine')))

    def test_a_git_dir_forged_inside_the_slot_chooses_no_root(self):
        """RV-29 (closure 1). A worker can write a whole fake git dir inside its own slot, back-link included, so a
        back-link proves nothing when it lives there. The common dir must lie OUTSIDE the slot."""
        other = self.tmp / 'other'
        other.mkdir()
        git('init', '-q', '.', cwd=other)
        forged = {'evil': self.slot / 'fg',                                       # closure 1's probe: commondir -> other
                  'evil2': self.slot / 'x' / 'worktrees' / 'fg'}                  # and the worktree-shaped variant
        for name, gitdir in forged.items():
            (self.slot / name).mkdir()
            gitdir.mkdir(parents=True)
            (self.slot / name / '.git').write_text(f'gitdir: {gitdir}\n')
            (gitdir / 'gitdir').write_text(str(self.slot / name / '.git') + '\n')
            (gitdir / 'commondir').write_text(str((other / '.git').resolve()) + '\n')
            (gitdir / 'HEAD').write_text('0' * 40 + '\n')
        for sub in ('objects', 'refs', 'logs'):
            (self.slot / 'x' / sub).mkdir(parents=True)
        self.assertEqual(git_writable_dirs(self.slot, default_git()), ())

    def test_a_symlinked_root_is_never_added(self):
        """RV-38 (closure 1). `is_dir()` follows symlinks, so `<common>/logs -> /anywhere` would have made /anywhere a
        root. Every root is resolved, and one that is a symlink or leaves the common dir is dropped."""
        git('worktree', 'add', '-q', '--detach', str(self.slot / 'wt'), cwd=self.main)
        elsewhere = self.tmp / 'elsewhere'
        elsewhere.mkdir()
        logs = self.main / '.git' / 'logs'
        shutil.rmtree(logs)
        logs.symlink_to(elsewhere, target_is_directory=True)
        got = git_writable_dirs(self.slot, default_git())
        self.assertNotIn(str(elsewhere.resolve()), got)
        self.assertNotIn(str(logs), got)
        self.assertEqual(sorted(got), sorted(r for r in worktree_roots(self.main, 'wt') if not r.endswith('/logs')))

    def test_a_rewritten_commondir_does_not_move_the_roots(self):
        """RV-37. `<common>/worktrees/<name>` is itself a writable root, so its `commondir` file is the worker's to
        rewrite; roots re-derived at the next revive must not follow it to another repository."""
        other = self.tmp / 'other'
        other.mkdir()
        git('init', '-q', '.', cwd=other)
        git('worktree', 'add', '-q', '--detach', str(self.slot / 'wt'), cwd=self.main)
        own = (self.main / '.git' / 'worktrees' / 'wt')
        (own / 'commondir').write_text(str((other / '.git').resolve()) + '\n')
        self.assertEqual(sorted(git_writable_dirs(self.slot, default_git())), sorted(worktree_roots(self.main, 'wt')))

    def test_no_repo_and_a_failing_git_add_nothing(self):
        self.assertEqual(git_writable_dirs(self.slot, default_git()), ())
        git('worktree', 'add', '-q', '--detach', str(self.slot / 'wt'), cwd=self.main)
        self.assertEqual(git_writable_dirs(self.slot, lambda args, cwd: (128, '')), ())


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


class DispatchRootsTests(unittest.TestCase):
    def test_a_codex_dispatch_into_a_worktree_slot_hands_the_worktree_roots_to_the_launcher(self):
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
        record = f.store.all()[0]
        launcher = (Path(record.child_instant) / '.fleet/launch-worker.sh').read_text()
        row = [line for line in out.splitlines() if 'codex_policy' in line][0]
        for root in worktree_roots(main, 'repo'):
            self.assertIn('--add-dir ' + root, launcher)
            self.assertIn(root, row)
        self.assertNotIn('--add-dir ' + str((main / '.git').resolve()) + ' ', launcher)


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
        for root in worktree_roots(main, 'repo'):
            self.assertIn('--add-dir ' + root, text)
        self.assertNotIn('--add-dir ' + str((main / '.git').resolve()) + ' ', text)


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
