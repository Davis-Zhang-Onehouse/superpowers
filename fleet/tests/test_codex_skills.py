"""FB-111. What a CODEX_HOME can see of the superpowers skills, and the one link that follows a deploy.

Every case builds its own releases area and CODEX_HOME under a temporary directory. The shape mirrors the
real box: `<releases>/current` is an absolute symlink to `<releases>/fleet-vX`, and the link the installer
writes names `current`, never the version it resolves to today.
"""
import contextlib
import io
import os
from pathlib import Path
import shutil
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

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root reads a mode-000 directory anyway')
    def test_an_unreadable_codex_home_is_reported_not_raised(self):
        (self.home / 'skills').mkdir()
        (self.home / 'plugins').mkdir()
        self.home.chmod(0)
        try:
            vis = codex_skills.visible_skills(self.home)
            code = self.main(*self.args('--check'))[0]
        finally:
            self.home.chmod(0o755)
        self.assertEqual(vis.found, {})
        self.assertEqual(vis.missing, CORE_SKILLS)
        self.assertEqual(code, 1)

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root writes a mode-000 directory anyway')
    def test_an_unreadable_codex_home_is_refused_not_a_traceback_and_dry_run_agrees(self):
        """RV-27: the install and dry-run path met EACCES with raising calls (traceback, exit 1) while --dry-run said
        would-create. Both now refuse (4), and --check says the link cannot be read rather than that it is absent."""
        self.home.chmod(0)
        try:
            install = self.main(*self.args())
            dry = self.main(*self.args('--dry-run'))
            check = self.main(*self.args('--check'))
        finally:
            self.home.chmod(0o755)
        self.assertEqual(install[0], 4, install)
        self.assertNotIn('Traceback', install[1] + install[2])
        self.assertEqual(dry[0], 4, dry)
        self.assertEqual(check[0], 1, check)
        self.assertIn('cannot be read', check[1] + check[2])

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root writes a mode-555 directory anyway')
    def test_an_unwritable_skills_directory_is_refused_and_dry_run_agrees(self):
        (self.home / 'skills').mkdir()
        (self.home / 'skills').chmod(0o555)
        try:
            install = self.main(*self.args())
            dry = self.main(*self.args('--dry-run'))
        finally:
            (self.home / 'skills').chmod(0o755)
        self.assertEqual(install[0], 4, install)
        self.assertNotIn('Traceback', install[1] + install[2])
        self.assertEqual(dry[0], 4, dry)
        self.assertFalse(os.path.lexists(self.link))

    def test_a_file_where_the_skills_directory_goes_is_refused(self):
        (self.home / 'skills').write_text('not a directory')
        before = _tree(self.home)
        self.assertEqual(self.main(*self.args())[0], 4)
        self.assertEqual(self.main(*self.args('--dry-run'))[0], 4)
        self.assertEqual(_tree(self.home), before)

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

    def test_a_pin_left_dangling_by_a_pruned_release_is_repointed_not_refused(self):
        """Final review minor 2: after `release.prune` removes the release a pin named, the pin dangles. It is still
        this installer's own link (`<releases>/fleet-vN/skills`), so the install postflight prints must repoint it."""
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to(self.rel / 'fleet-v0' / 'skills')     # a release that no longer exists
        code, out, err = self.main(*self.args())
        self.assertEqual(code, 0, out + err)
        self.assertEqual(os.readlink(self.link), str(self.rel / 'current' / 'skills'))

    def test_a_live_link_to_a_dev_checkouts_skills_is_refused_not_repointed(self):
        """RV-30: a link the operator made on purpose to a superpowers DEV checkout resolves to a superpowers tree, but its
        target is not the installer's shape (<releases>/current/skills or <releases>/fleet-vN/skills). Refused, untouched."""
        dev = self.tmp / 'dev-checkout' / 'skills'
        for name in CORE_SKILLS:
            (dev / name).mkdir(parents=True)
            (dev / name / 'SKILL.md').write_text('dev')
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to(dev)
        before = _tree(self.home)
        self.assertEqual(self.main(*self.args())[0], 4)
        self.assertEqual(self.main(*self.args('--dry-run'))[0], 4)
        self.assertEqual(_tree(self.home), before)

    def test_a_live_link_to_another_tools_current_skills_is_still_foreign(self):
        """Re-review residual: only a DANGLING `.../current/skills` or `.../fleet-vN/skills` pin is ours by shape."""
        other = self.tmp / 'othertool' / 'current' / 'skills'
        other.mkdir(parents=True)
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to(other)
        before = _tree(self.home)
        self.assertEqual(self.main(*self.args())[0], 4)
        self.assertEqual(_tree(self.home), before)

    def test_dry_run_fails_when_the_deployed_release_lacks_a_core_skill(self):
        """Final review minor 5: --dry-run exits 0 only when the real run would succeed."""
        shutil.rmtree(self.rel / 'fleet-v1' / 'skills' / 'using-fleet')
        code, out, err = self.main(*self.args('--dry-run'))
        self.assertEqual(code, 1, out + err)
        self.assertIn('using-fleet', out + err)
        self.assertEqual(self.main(*self.args())[0], 1)

    def test_the_load_instruction_for_a_home_that_sees_nothing_says_not_to_improvise(self):
        """Final review minor 3: an --override launch must not tell the worker to read a skill it cannot see."""
        text = codex_skills.load_instruction(codex_skills.visible_skills(self.home))
        self.assertNotIn('Read superpowers:using-superpowers first', text)
        self.assertNotIn('codex-tools.md', text)
        self.assertIn('not installed', text)
        self.assertIn('improvise', text)

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

    def test_a_codex_home_that_does_not_exist_is_refused_not_created(self):
        """RV-29: --codex-home is required so a wrong guess never writes into someone else's config; a TYPO must not quietly
        create a new config tree and report ok either."""
        typo = self.tmp / 'nowhere' / '.codx'
        for extra in ((), ('--dry-run',)):
            code, out, err = self.main('--codex-home', str(typo), '--releases', str(self.rel), *extra)
            self.assertEqual(code, 4, out + err)
            self.assertIn('does not exist', out + err)
        self.assertFalse(os.path.lexists(self.tmp / 'nowhere'))

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
