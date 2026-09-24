"""FB-111. A `--runtime codex` dispatch whose CODEX_HOME cannot see the superpowers skills is refused, and a codex
worker is told how to load a skill on codex: in its seed and in `fleet brief`.

The fixture's launch settings name `/test/config`, which does not exist, so every case states what that
CODEX_HOME can see by setting `Fleet.codex_skills`, the same way it injects every other probe.
"""
from pathlib import Path
import shutil
import unittest

from fleet import runtime_launch
from fleet.codex_skills import CORE_SKILLS, Visibility
from tests.test_cli import Fleet, snapshot


def missing(home):
    return Visibility(home, {}, CORE_SKILLS, '')


def refuses_to_be_asked(home):
    raise AssertionError(f'a claude dispatch asked what CODEX_HOME {home} can see')


class CodexSkillsDispatchTests(unittest.TestCase):
    def setUp(self):
        self.f = Fleet()
        self.addCleanup(shutil.rmtree, self.f.tmp)
        #: Built here, not per call: the refusal cases snapshot the tree before dispatching.
        self.profile = self.f.profile()

    def dispatch(self, *extra):
        return self.f.run(['dispatch', '--profile', str(self.profile), '--title', 'skills task', *extra])

    def seed(self):
        record = self.f.store.all()[0]
        return record, (Path(record.child_instant) / '.fleet' / 'seed.txt').read_text()

    def test_a_codex_home_without_the_skills_is_refused_before_anything_is_claimed(self):
        self.f.codex_skills = missing
        #: Not a whole-tree snapshot: a real dispatch holds the runtime admission lock (`.runtime-admission.lock`)
        #: before any gate, and that lock is not a claim. What must not exist is a lease, a record, a child
        #: folder or a session.
        instants_before = sorted(p.name for p in self.f.instants.iterdir())
        code, out, err = self.dispatch('--runtime', 'codex')
        self.assertEqual(code, 4, out + err)
        self.assertIn('systematic-debugging', err)
        self.assertIn('/test/config', err)
        self.assertIn('fleet-codex-skills.sh', err)
        self.assertIn('--override', err)
        self.assertEqual(self.f.store.all(), [])
        self.assertIsNone(self.f.pool.lease('ws1'))
        self.assertEqual(self.f.started, [])
        self.assertEqual(sorted(p.name for p in self.f.instants.iterdir()), instants_before)

    def test_the_dry_run_gives_the_same_refusal(self):
        self.f.codex_skills = missing
        before = snapshot(self.f.tmp)
        code, out, err = self.dispatch('--runtime', 'codex', '--dry-run')
        self.assertEqual(code, 4, out + err)
        self.assertIn('fleet-codex-skills.sh', err)
        self.assertEqual(snapshot(self.f.tmp), before)

    def test_an_override_launches_without_them_and_is_recorded(self):
        self.f.codex_skills = missing
        code, out, err = self.dispatch('--runtime', 'codex', '--override', 'a bare codex is the point of this probe')
        self.assertEqual(code, 0, out + err)
        record, seed = self.seed()
        self.assertEqual(record.override_reason, 'a bare codex is the point of this probe')
        self.assertIn('MISSING', out)

    def test_a_codex_seed_says_how_to_load_a_skill(self):
        code, out, err = self.dispatch('--runtime', 'codex')
        self.assertEqual(code, 0, out + err)
        _, seed = self.seed()
        self.assertTrue(seed.startswith(runtime_launch.seed_cli_header()), seed[:400])
        self.assertIn('superpowers:<name>', seed)
        self.assertIn('superpowers:using-superpowers', seed)
        self.assertIn('using-superpowers/references/codex-tools.md', seed)
        self.assertIn('SKILL.md', seed)
        self.assertIn('codex_skills', out)

    def test_the_dry_run_names_what_the_codex_home_can_see(self):
        code, out, err = self.dispatch('--runtime', 'codex', '--dry-run')
        self.assertEqual(code, 0, out + err)
        row = [line for line in out.splitlines() if line.startswith('codex_skills')]
        self.assertEqual(len(row), 1, out)
        self.assertIn(f'{len(CORE_SKILLS)} skill(s)', row[0])

    def test_a_claude_dispatch_never_asks_and_its_seed_is_unchanged(self):
        self.f.codex_skills = refuses_to_be_asked
        code, out, err = self.dispatch('--runtime', 'claude')
        self.assertEqual(code, 0, out + err)
        _, seed = self.seed()
        header = runtime_launch.seed_cli_header()
        self.assertTrue(seed.startswith(header))
        self.assertNotIn('codex-tools.md', seed)
        self.assertNotIn('Superpowers skills on codex', seed)
        self.assertNotIn('codex_skills', out)

    def test_the_claude_header_is_byte_identical_to_the_base(self):
        base = (f'Fleet CLI for this dispatch: {runtime_launch.fleet_executable()}\n'
                'The launcher exports this path as FLEET_BIN. For every fleet command in the task,\n'
                'charter, or skills, invoke "$FLEET_BIN" instead of the bare fleet command.\n'
                'Login shells may put an older fleet installation first on PATH.\n\n')
        self.assertEqual(runtime_launch.seed_cli_header(), base)
        self.assertEqual(runtime_launch.seed_cli_header('claude'), base)

    def brief_rows(self, runtime):
        path = self.f.worker('coder', slot='ws1', live=False)
        record = self.f.store.read(self.f.ids['coder'])
        record.runtime, record.runtime_config_dir = runtime, '/test/config'
        self.f.store.write(record)
        code, out, err = self.f.run(['brief', '--instant', str(path)])
        return code, [line for line in out.splitlines() if line.startswith('skills')], out + err

    def test_brief_tells_a_codex_worker_how_to_load_a_skill(self):
        code, rows, text = self.brief_rows('codex')
        self.assertEqual(len(rows), 1, text)
        self.assertIn('info', rows[0])
        self.assertIn('codex-tools.md', rows[0])

    def test_brief_flags_a_codex_worker_that_cannot_see_the_skills(self):
        self.f.codex_skills = missing
        code, rows, text = self.brief_rows('codex')
        self.assertEqual(len(rows), 1, text)
        self.assertNotIn(' info ', rows[0])
        self.assertIn('systematic-debugging', rows[0])
        self.assertIn('fleet-codex-skills.sh', text)

    def test_brief_says_nothing_about_codex_skills_to_a_claude_worker(self):
        self.f.codex_skills = refuses_to_be_asked
        code, rows, text = self.brief_rows('claude')
        self.assertEqual(rows, [], text)


if __name__ == '__main__':
    unittest.main()
