"""Relative instant operands are interpreted from the caller's working directory."""
import json
import os
from pathlib import Path
import re
from unittest import mock

from fleet import cli
from fleet.origin import Origin, write as write_origin
from fleet.roadmap import Milestone, Roadmap
from tests.test_cli import FRESH_BASE, LONG_AGO, NOW, OURS, CliCase


class TestInstantPaths(CliCase):
    def run_in(self, fleet, cwd, argv):
        """Run a verb FROM `cwd`, which must lie inside the fixture's tree (`Fleet.run` keeps it then)."""
        previous = Path.cwd()
        try:
            os.chdir(cwd)
            return fleet.run(argv)
        finally:
            os.chdir(previous)

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

    def test_every_instant_verb_smokes_a_cwd_relative_path(self):
        # The output comparison proves path selection for verbs that print the subject.
        # declare, park, unpark, apply, withdraw, complete and abort print no subject
        # path on their normal fixture branch; for those seven this is smoke coverage.
        # V23-O (FB-123). The relative path is computed from the cwd the VERB runs in. It was computed from
        # the runner's cwd while `Fleet.run` chdirs into the fixture's tmp, so it only passed from a checkout
        # deep enough for the surplus `..` to collapse at `/`.
        fleet = self.loaded()
        arguments = self.argv_for(fleet)
        verb_cwd = fleet.paths['solo']
        for name, spec in cli.VERBS.items():
            if not any(flag.name == '--instant' for flag in spec.flags):
                continue
            absolute = list(arguments[name])
            argv = list(absolute)
            index = argv.index('--instant') + 1
            argv[index] = os.path.relpath(argv[index], verb_cwd)
            self.assertEqual(os.path.normpath(verb_cwd / argv[index]), absolute[index])
            if not spec.read_only:
                argv.append('--dry-run')
                absolute.append('--dry-run')
            with self.subTest(verb=name):
                expected_code, expected_out, expected_err = self.run_in(fleet, verb_cwd, [name, *absolute])
                code, out, err = self.run_in(fleet, verb_cwd, [name, *argv])
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
        verb_cwd = fleet.paths['solo']
        base = ['dispatch', *self.argv_for(fleet)['dispatch'], '--dry-run']
        expected = self.run_in(fleet, verb_cwd, [*base, '--from', str(coordinator)])
        argv = [*base, '--from', os.path.relpath(coordinator, verb_cwd)]
        code, out, err = self.run_in(fleet, verb_cwd, argv)
        self.assertEqual((code, out, err), expected)

    def test_propose_to_relative_path_reaches_the_destination_inbox(self):
        fleet = self.loaded()
        coordinator = fleet.paths['readyWorker']
        proposer = fleet.paths['doomed']
        previous = Path.cwd()
        try:
            os.chdir(proposer)
            code, out, err = fleet.run(['propose', '--instant', str(proposer),
                                        '--to', '../' + coordinator.name,
                                        '--milestone', 'M1', '--status', 'running',
                                        '--evidence', 'evidence/INDEX.md'])
        finally:
            os.chdir(previous)
        self.assertEqual(code, 0, err)
        mine = [p for p in Roadmap(coordinator).proposals() if p.milestone == 'M1'
                and p.instant == str(proposer)]
        self.assertEqual(len(mine), 1)
        self.assertEqual(Roadmap(proposer).proposals(), [])

    def test_refusal_names_resolved_bad_path(self):
        fleet = self.loaded()
        bad = './not-an-instant'
        previous = Path.cwd()
        try:
            os.chdir(fleet.tmp)
            code, out, err = fleet.run(['roadmap', '--instant', bad])
            expected = str((Path.cwd() / bad).resolve())
        finally:
            os.chdir(previous)
        self.assertEqual(code, 2)
        self.assertIn(expected, err)

    def test_missing_path_refusal_explains_both_relative_forms(self):
        fleet = self.loaded()
        for operand in ('./missing-instant', 'missing-instant'):
            with self.subTest(operand=operand):
                code, out, err = fleet.run(['roadmap', '--instant', operand])
                self.assertEqual(code, 2)
                self.assertIn('relative path from the current directory', err)
                self.assertIn('bare name from the instants directory', err)

    def test_malformed_existing_folder_names_input_and_parsed_path(self):
        fleet = self.loaded()
        malformed = fleet.tmp / 'malformed-instant-folder'
        malformed.mkdir()
        code, out, err = fleet.run(['roadmap', '--instant', str(malformed)])
        self.assertEqual(code, 2)
        self.assertIn(f'resolved input {malformed}', err)
        self.assertIn(f'parsed instant {malformed}', err)


class TestCadenceResolvesTheOperandLikeTheVerb(CliCase):
    """V23-O (FB-123). `_cadence` scopes its alarm to the effort of the instant a verb was pointed at. It
    joined a relative `--instant`/`--from` onto the instants directory while the verb itself resolved the
    same operand from cwd, so `--instant .` inside a foreign effort nagged OURS and dropped the foreign
    one. Both halves now go through `_resolve_instant`."""

    def overdue_foreign(self, fleet):
        """A second effort beside ours, with BOTH efforts' registers overdue."""
        foreign = fleet.tmp / "other-effort" / FRESH_BASE
        foreign.mkdir(parents=True)
        register = foreign / "ISSUES.md"
        register.write_text("## Other-1 overdue\n")
        fleet.harvest.register(str(foreign), str(register))
        data = json.loads(fleet.harvest.path.read_text())
        for source in data["sources"]:
            source["registered_at"] = LONG_AGO
            source["last_run"] = LONG_AGO
        fleet.harvest.path.write_text(json.dumps(data))
        return foreign

    def run_from(self, fleet, cwd, argv):
        previous = Path.cwd()
        try:
            os.chdir(cwd)
            return fleet.run(argv)
        finally:
            os.chdir(previous)

    def assert_nags_only(self, err, foreign, fleet):
        self.assertIn(f"{cli.CADENCE_PREFIX} {foreign}", err)
        self.assertNotIn(str(fleet.instants / OURS), err)

    def test_dot_inside_a_foreign_effort_nags_that_effort(self):
        fleet = self.loaded()
        foreign = self.overdue_foreign(fleet)
        code, out, err = self.run_from(fleet, foreign, ['roadmap', '--porcelain', '--instant', '.'])
        self.assert_nags_only(err, foreign, fleet)
        self.assertNotIn(cli.CADENCE_PREFIX, out)

    def test_parent_relative_operand_to_a_foreign_effort_nags_that_effort(self):
        fleet = self.loaded()
        foreign = self.overdue_foreign(fleet)
        ours = fleet.paths['readyWorker']
        relative = os.path.relpath(foreign, ours)
        self.assertTrue(relative.startswith('..'), relative)
        code, out, err = self.run_from(fleet, ours, ['roadmap', '--porcelain', '--instant', relative])
        self.assert_nags_only(err, foreign, fleet)

    def test_dispatch_from_relative_foreign_coordinator_nags_that_effort(self):
        fleet = self.loaded()
        foreign = self.overdue_foreign(fleet)
        ours = fleet.paths['readyWorker']
        base = ['dispatch', '--porcelain', *self.argv_for(fleet)['dispatch'], '--dry-run']
        code, out, err = self.run_from(fleet, ours,
                                       [*base, '--from', os.path.relpath(foreign, ours)])
        self.assert_nags_only(err, foreign, fleet)

    def test_unresolvable_operand_falls_back_to_the_callers_effort_and_the_verb_still_refuses(self):
        # A path that names nothing cannot scope the alarm; the verb refuses it (exit 2), and the alarm
        # is scoped as if no operand were named — never silenced, never a crash.
        fleet = self.loaded()
        foreign = self.overdue_foreign(fleet)
        code, out, err = self.run_from(fleet, foreign,
                                       ['roadmap', '--porcelain', '--instant', './missing-instant'])
        self.assertEqual(code, 2, err)
        self.assertIn('not an instant on disk', err)
        self.assert_nags_only(err, foreign, fleet)

    def test_nothing_overdue_resolves_the_operand_only_for_the_verb(self):
        # V23-O RV-17. With no overdue source the alarm has nothing to scope, so `_cadence` must not resolve the
        # operand a second time (a refused operand costs a full store read inside the resolver).
        fleet = self.loaded()
        data = json.loads(fleet.harvest.path.read_text())
        for source in data["sources"]:
            source["last_run"] = NOW
        fleet.harvest.path.write_text(json.dumps(data))
        with mock.patch.object(cli, '_resolve_instant', wraps=cli._resolve_instant) as spy:
            code, out, err = self.run_from(fleet, fleet.tmp, ['roadmap', '--instant', './missing-instant'])
        self.assertEqual(code, 2, err)
        self.assertNotIn(cli.CADENCE_PREFIX, err)
        self.assertEqual(spy.call_count, 1, spy.call_args_list)
