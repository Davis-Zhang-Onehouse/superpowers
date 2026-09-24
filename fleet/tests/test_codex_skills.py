"""FB-111. What a CODEX_HOME can see of the superpowers skills, and the one link that follows a deploy.

Every case builds its own releases area and CODEX_HOME under a temporary directory. The shape mirrors the
real box: `<releases>/current` is an absolute symlink to `<releases>/fleet-vX`, and the link the installer
writes names `current`, never the version it resolves to today.
"""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest

from fleet import codex_skills
from fleet.codex_skills import CORE_SKILLS, Visibility


def _tree(root: Path) -> list:
    """Every path under `root` with its link target or file content, so "nothing changed" is a diff."""
    rows = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in sorted(dirnames + filenames):
            p = Path(dirpath) / name
            if p.is_symlink():
                rows.append((str(p), 'link', os.readlink(p)))
            elif p.is_file():
                rows.append((str(p), 'file', p.read_text()))
            else:
                rows.append((str(p), 'dir', ''))
    return sorted(rows)


class CodexSkillsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.rel = self.tmp / 'fleet-releases'
        for version, extra in (('fleet-v1', ()), ('fleet-v2', ('new-in-v2',))):
            for name in CORE_SKILLS + extra:
                skill = self.rel / version / 'skills' / name
                skill.mkdir(parents=True)
                (skill / 'SKILL.md').write_text(f'---\nname: {name}\n---\n{version}\n')
        (self.rel / 'current').symlink_to(self.rel / 'fleet-v1')
        self.home = self.tmp / 'codex-home'
        self.home.mkdir()
        self.link = self.home / 'skills' / 'superpowers'

    def tearDown(self):
        self._tmp.cleanup()

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = codex_skills.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def args(self, *extra):
        return ('--codex-home', str(self.home), '--releases', str(self.rel), *extra)

    def flip_current(self, version):
        tmp = self.rel / 'current.tmp'
        tmp.symlink_to(self.rel / version)
        os.replace(tmp, self.rel / 'current')

    # 1
    def test_an_empty_codex_home_sees_no_core_skill_and_fails_the_check(self):
        vis = codex_skills.visible_skills(self.home)
        self.assertFalse(vis.ok)
        self.assertEqual(vis.missing, CORE_SKILLS)
        self.assertEqual(self.main(*self.args('--check'))[0], 1)

    def test_a_missing_codex_home_is_reported_not_raised(self):
        vis = codex_skills.visible_skills(self.tmp / 'nowhere')
        self.assertFalse(vis.ok)
        self.assertEqual(vis.found, {})

    # 2
    def test_dry_run_writes_nothing(self):
        before = _tree(self.home)
        code, out, _ = self.main(*self.args('--dry-run'))
        self.assertEqual(code, 0)
        self.assertIn('would-create', out)
        self.assertEqual(_tree(self.home), before)

    # 3
    def test_install_writes_one_literal_link_to_current(self):
        code, out, err = self.main(*self.args())
        self.assertEqual(code, 0, out + err)
        self.assertTrue(self.link.is_symlink())
        self.assertEqual(os.readlink(self.link), str(self.rel / 'current' / 'skills'))
        self.assertEqual(self.main(*self.args('--check'))[0], 0)
        vis = codex_skills.visible_skills(self.home)
        self.assertTrue(vis.ok)
        self.assertEqual(set(CORE_SKILLS) - set(vis.found), set())
        self.assertEqual(vis.found['systematic-debugging'],
                         str(self.link / 'systematic-debugging' / 'SKILL.md'))
        self.assertEqual(vis.link_target, str(self.rel / 'current' / 'skills'))
        self.assertEqual(vis.skills_root, str(self.link))

    def test_install_twice_is_a_no_op(self):
        self.assertEqual(self.main(*self.args())[0], 0)
        before = _tree(self.home)
        code, out, _ = self.main(*self.args())
        self.assertEqual(code, 0)
        self.assertIn('already follows', out)
        self.assertEqual(_tree(self.home), before)

    # 4
    def test_a_deploy_moves_codex_with_no_reinstall(self):
        self.assertEqual(self.main(*self.args())[0], 0)
        self.assertNotIn('new-in-v2', codex_skills.visible_skills(self.home).found)
        self.flip_current('fleet-v2')
        self.assertEqual(self.main(*self.args('--check'))[0], 0)
        vis = codex_skills.visible_skills(self.home)
        self.assertIn('new-in-v2', vis.found)
        self.assertIn('fleet-v2', (self.link / 'systematic-debugging' / 'SKILL.md').read_text())

    # 5
    def test_a_link_pinned_to_one_release_fails_the_check_and_install_repoints_it(self):
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to(self.rel / 'fleet-v1' / 'skills')
        self.assertTrue(codex_skills.visible_skills(self.home).ok, 'a pinned link still shows skills today')
        ok, reason = codex_skills.follows_current(self.home, self.rel)
        self.assertFalse(ok)
        self.assertIn('pinned', reason)
        code, out, err = self.main(*self.args('--check'))
        self.assertEqual(code, 1)
        self.assertIn('pinned', out + err)
        before = _tree(self.home)
        code, out, _ = self.main(*self.args('--dry-run'))
        self.assertEqual(code, 0)
        self.assertIn('would-repoint', out)
        self.assertEqual(_tree(self.home), before)
        self.assertEqual(self.main(*self.args())[0], 0)
        self.assertEqual(os.readlink(self.link), str(self.rel / 'current' / 'skills'))

    # 6
    def test_a_real_directory_in_the_way_is_refused_and_left_untouched(self):
        self.link.mkdir(parents=True)
        (self.link / 'mine.txt').write_text('operator data')
        before = _tree(self.home)
        code, out, err = self.main(*self.args())
        self.assertEqual(code, 4)
        self.assertIn(str(self.link), out + err)
        self.assertEqual(_tree(self.home), before)
        self.assertEqual(self.main(*self.args('--dry-run'))[0], 4)
        self.assertEqual(_tree(self.home), before)

    # 7
    def test_a_foreign_link_is_refused_and_left_untouched(self):
        elsewhere = self.tmp / 'elsewhere'
        elsewhere.mkdir()
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to(elsewhere)
        before = _tree(self.home)
        self.assertEqual(self.main(*self.args())[0], 4)
        self.assertEqual(_tree(self.home), before)

    def test_a_releases_area_without_current_skills_is_refused(self):
        (self.rel / 'current').unlink()
        code, out, err = self.main(*self.args())
        self.assertEqual(code, 4)
        self.assertIn('current', out + err)
        self.assertFalse(self.link.exists() or self.link.is_symlink())

    # 8
    def test_codex_home_is_required(self):
        self.assertEqual(self.main('--releases', str(self.rel))[0], 2)

    def test_releases_falls_back_to_the_environment_and_is_otherwise_required(self):
        env = dict(os.environ)
        try:
            os.environ.pop('FLEET_RELEASES', None)
            self.assertEqual(self.main('--codex-home', str(self.home))[0], 2)
            os.environ['FLEET_RELEASES'] = str(self.rel)
            self.assertEqual(self.main('--codex-home', str(self.home))[0], 0)
        finally:
            os.environ.clear()
            os.environ.update(env)
        self.assertEqual(os.readlink(self.link), str(self.rel / 'current' / 'skills'))

    # 9
    def test_skills_from_a_plugin_install_count(self):
        for name in CORE_SKILLS:
            skill = self.home / 'plugins' / 'cache' / 'mkt' / 'superpowers' / '1.0' / 'skills' / name
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('x')
        vis = codex_skills.visible_skills(self.home)
        self.assertTrue(vis.ok)
        self.assertEqual(vis.link_target, '')

    # 10
    def test_codex_system_skills_do_not_count(self):
        skill = self.home / 'skills' / '.system' / 'systematic-debugging'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('x')
        self.assertNotIn('systematic-debugging', codex_skills.visible_skills(self.home).found)

    # 11
    def test_the_load_instruction_names_the_reference_and_the_count(self):
        self.assertEqual(self.main(*self.args())[0], 0)
        vis = codex_skills.visible_skills(self.home)
        text = codex_skills.load_instruction(vis)
        self.assertIn(str(self.link / 'using-superpowers' / 'references' / 'codex-tools.md'), text)
        self.assertIn(f'{len(vis.found)} skill(s)', text)
        self.assertIn('superpowers:using-superpowers', text)
        self.assertIn('SKILL.md', text)

    def test_install_command_names_the_script_and_the_home(self):
        text = codex_skills.install_command(str(self.home))
        self.assertIn('scripts/fleet-codex-skills.sh', text)
        self.assertIn(str(self.home), text)
        self.assertTrue(Path(text.split()[0]).is_absolute())

    def test_visibility_ok_is_derived_from_missing(self):
        self.assertTrue(Visibility('/h', {}, (), '').ok)
        self.assertFalse(Visibility('/h', {}, ('x',), '').ok)


if __name__ == '__main__':
    unittest.main()
