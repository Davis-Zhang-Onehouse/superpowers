"""Relative instant operands are interpreted from the caller's working directory."""
import os
from pathlib import Path
import re

from fleet import cli
from tests.test_cli import CliCase


class TestInstantPaths(CliCase):
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
        bad = 'not-an-instant'
        code, out, err = fleet.run(['roadmap', '--instant', bad])
        self.assertEqual(code, 2)
        self.assertIn(str((Path.cwd() / bad).resolve()), err)
