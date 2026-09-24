"""Relative instant operands are interpreted from the caller's working directory."""
import os
from pathlib import Path
import re

from fleet import cli
from fleet.origin import Origin, write as write_origin
from fleet.roadmap import Milestone, Roadmap
from tests.test_cli import CliCase, NOW


class TestInstantPaths(CliCase):
    def test_symlinked_instants_dir_preserves_open_owner_route(self):
        fleet = self.loaded()
        coordinator = fleet.paths['readyWorker']
        owner = fleet.paths['solo']
        roadmap = Roadmap(coordinator)
        roadmap.add(Milestone(id='M-symlink', title='symlinked owner', status='blocked',
                              deps=[], evidence=[]))
        roadmap.claim('M-symlink', str(owner))
        write_origin(owner, Origin(coordinator=str(coordinator), dispatched_at=NOW,
                                   milestone='M-symlink'))
        physical = fleet.tmp / 'physical-instants'
        fleet.instants.rename(physical)
        fleet.instants.symlink_to(physical, target_is_directory=True)

        code, out, err = fleet.run(['milestone', '--instant', str(coordinator),
                                    '--id', 'M-symlink', '--disown', '--reason', 'probe'])

        self.assertEqual(code, 4, err)
        self.assertIn(f'fleet abort --instant {owner}', err)
        self.assertEqual(str(owner), Roadmap(coordinator).milestone('M-symlink').owner)

    def test_bare_name_reaches_instants_dir_from_unrelated_cwd(self):
        fleet = self.loaded()
        target = fleet.paths['readyWorker']
        previous = Path.cwd()
        try:
            os.chdir(fleet.tmp)
            code, out, err = fleet.run(['milestone', '--instant', target.name,
                                        '--id', 'bare-name', '--title', 'Bare name', '--dry-run'])
        finally:
            os.chdir(previous)
        self.assertEqual(code, 0, err)
        self.assertIn('bare-name', out)

    def test_dot_reaches_the_current_instant_for_milestone(self):
        fleet = self.loaded()
        target = fleet.paths['readyWorker']
        previous = Path.cwd()
        try:
            os.chdir(target)
            code, out, err = fleet.run(['milestone', '--instant', '.', '--id', 'relative-dot',
                                        '--title', 'Relative dot', '--dry-run'])
        finally:
            os.chdir(previous)
        self.assertEqual(code, 0, err)
        self.assertIn('relative-dot', out)

    def test_parent_relative_path_reaches_sibling_for_review(self):
        fleet = self.loaded()
        target = fleet.paths['readyWorker']
        previous = Path.cwd()
        try:
            os.chdir(fleet.paths['solo'])
            code, out, err = fleet.run(['review', '--instant', '../' + target.name,
                                        '--scope', 'all', '--verdict', 'READY', '--dry-run'])
        finally:
            os.chdir(previous)
        self.assertNotIn('not an instant on disk', err)
        self.assertIn('would record scope all', out)

    def test_every_instant_verb_accepts_a_cwd_relative_path(self):
        fleet = self.loaded()
        arguments = self.argv_for(fleet)
        for name, spec in cli.VERBS.items():
            if not any(flag.name == '--instant' for flag in spec.flags):
                continue
            absolute = list(arguments[name])
            argv = list(absolute)
            index = argv.index('--instant') + 1
            argv[index] = os.path.relpath(argv[index], Path.cwd())
            if not spec.read_only:
                argv.append('--dry-run')
                absolute.append('--dry-run')
            with self.subTest(verb=name):
                expected_code, expected_out, expected_err = fleet.run([name, *absolute])
                code, out, err = fleet.run([name, *argv])
                self.assertEqual(code, expected_code, err)
                if name == 'verify':
                    # Each run owns a fresh sandbox; its random directory is reported.
                    out = re.sub(r'fleet-verify-[A-Za-z0-9_]+', 'fleet-verify-TMP', out)
                    expected_out = re.sub(r'fleet-verify-[A-Za-z0-9_]+',
                                          'fleet-verify-TMP', expected_out)
                self.assertEqual(out, expected_out)
                self.assertEqual(err, expected_err)

    def test_dispatch_from_accepts_a_cwd_relative_path(self):
        fleet = self.loaded()
        coordinator = fleet.paths['readyWorker']
        base = ['dispatch', *self.argv_for(fleet)['dispatch'], '--dry-run']
        expected = fleet.run([*base, '--from', str(coordinator)])
        argv = [*base, '--from', os.path.relpath(coordinator, Path.cwd())]
        code, out, err = fleet.run(argv)
        self.assertEqual((code, out, err), expected)

    def test_refusal_names_resolved_bad_path(self):
        fleet = self.loaded()
        bad = './not-an-instant'
        code, out, err = fleet.run(['roadmap', '--instant', bad])
        self.assertEqual(code, 2)
        self.assertIn(str((Path.cwd() / bad).resolve()), err)

    def test_missing_path_refusal_explains_both_relative_forms(self):
        fleet = self.loaded()
        for operand in ('./missing-instant', 'missing-instant'):
            with self.subTest(operand=operand):
                code, out, err = fleet.run(['roadmap', '--instant', operand])
                self.assertEqual(code, 2)
                self.assertIn('relative path from the current directory', err)
                self.assertIn('bare name from the instants directory', err)
