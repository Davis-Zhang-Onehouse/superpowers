"""What a release SAYS about itself: the version a user reads, and the payload it actually ships.

Two defects, one theme — a release describes itself with a number and a commit list, and both describe
something other than what is in the artifact.

`RI-12` The cut rewrites `fleet/src/fleet/__init__.py` and nothing else, while seven manifest files
declare the version Claude Code reports. Measured: `claude plugin list` prints `Version: 6.2.0` on a box
deployed at fleet 0.3.7, and `plugin.json` reads `6.2.0` at every one of the fifteen release tags ever cut.

`RI-13` A release is a `git archive` of the whole repository — 23 skills, `commands/`, `hooks/` and the
plugin manifest — and the changelog files every commit under a `fleet/vX.Y.Z` heading with no mention of
which of those moved. Three releases (0.2.3, 0.3.2, 0.3.4) changed `skills/`; nothing in their notes says so.

The trap this file exists to hold shut is in `CutFootprintCase`. Stamping the manifests puts seven more
paths into EVERY release's diff, and the exemption gate classifies unrecognised paths as requiring — so a
careless fix for `RI-12` makes the feature `0.3.7` shipped unreachable again, which is `SI-19`'s exact
shape and is invisible to any test that feeds `classify` a hand-written list.
"""
import json
import pathlib
import shutil
import tempfile
import unittest

from fleet.errors import BadInput
from fleet.release_scope import areas, classify, without_version_field
from fleet.release_stamp import (VERSION_CONFIG, core_of, declared_version_files, plugin_version,
                                 stamp_plugin_version)

from tests.test_release import ReleaseCliFixture


MANIFESTS = {
    "package.json": {"name": "superpowers", "version": "6.2.0", "type": "module"},
    ".claude-plugin/plugin.json": {"name": "superpowers", "version": "6.2.0", "license": "MIT"},
    ".claude-plugin/marketplace.json": {"name": "superpowers-dev",
                                        "plugins": [{"name": "superpowers", "version": "6.2.0",
                                                     "source": "./"}]},
    "gemini-extension.json": {"name": "superpowers", "version": "6.2.0"},
}

CONFIG = {"files": [{"path": "package.json", "field": "version"},
                    {"path": ".claude-plugin/plugin.json", "field": "version"},
                    {"path": ".claude-plugin/marketplace.json", "field": "plugins.0.version"},
                    {"path": "gemini-extension.json", "field": "version"}]}


def seed_manifests(root):
    """The declared version files and the config that declares them, as this repository has them."""
    root = pathlib.Path(root)
    (root / VERSION_CONFIG).write_text(json.dumps(CONFIG, indent=2) + "\n")
    for relative, body in MANIFESTS.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, indent=2) + "\n")
    return root


class PluginVersionCase(unittest.TestCase):
    """The version arithmetic, on strings alone."""

    def test_the_fleet_version_rides_as_build_metadata(self):
        self.assertEqual(plugin_version("6.2.0", "0.3.8"), "6.2.0+fleet.0.3.8")

    def test_the_upstream_core_is_preserved_not_replaced(self):
        """`D-5`. Writing `0.3.8` over `6.2.0` is a version DECREASE — any consumer comparing versions
        reads it as a downgrade — and it erases the fork's upstream lineage."""
        self.assertTrue(plugin_version("6.2.0", "0.3.8").startswith("6.2.0"))

    def test_stamping_twice_does_not_accumulate_build_metadata(self):
        """The second release of the day must not produce `6.2.0+fleet.0.3.8+fleet.0.3.9`."""
        once = plugin_version("6.2.0", "0.3.8")
        self.assertEqual(plugin_version(once, "0.3.9"), "6.2.0+fleet.0.3.9")

    def test_the_core_of_a_plain_version_is_itself(self):
        self.assertEqual(core_of("6.2.0"), "6.2.0")

    def test_the_core_ignores_everything_after_the_plus(self):
        self.assertEqual(core_of("6.2.0+fleet.0.3.8"), "6.2.0")

    def test_an_upstream_bump_survives_the_next_fleet_release(self):
        """Upstream moving to 6.3.0 must be carried forward, not clobbered back to 6.2.0."""
        self.assertEqual(plugin_version("6.3.0", "0.3.9"), "6.3.0+fleet.0.3.9")


class StampingCase(unittest.TestCase):
    """Rewriting the declared files on disk."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-stamp-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        seed_manifests(self.tmp)

    def test_the_declared_files_come_from_the_repositorys_own_config(self):
        """`.version-bump.json` is already the declaration of which files carry the version. Reading it
        means a manifest added later is stamped without touching the pipeline."""
        declared = dict(declared_version_files(self.tmp))
        self.assertEqual(sorted(declared), sorted(MANIFESTS))
        self.assertEqual(declared[".claude-plugin/marketplace.json"], "plugins.0.version")

    def test_a_repository_with_no_config_declares_nothing(self):
        """The fixture checkouts in `test_release` have no manifests. Absent is not an error."""
        (self.tmp / VERSION_CONFIG).unlink()
        self.assertEqual(declared_version_files(self.tmp), ())

    def test_every_declared_file_is_stamped(self):
        changed = stamp_plugin_version(self.tmp, "0.3.8")
        self.assertEqual(sorted(path for path, _, _ in changed), sorted(MANIFESTS))
        for relative in MANIFESTS:
            self.assertIn("+fleet.0.3.8", (self.tmp / relative).read_text(),
                          f"{relative} was not stamped")

    def test_a_nested_field_is_stamped_in_place(self):
        stamp_plugin_version(self.tmp, "0.3.8")
        body = json.loads((self.tmp / ".claude-plugin" / "marketplace.json").read_text())
        self.assertEqual(body["plugins"][0]["version"], "6.2.0+fleet.0.3.8")

    def test_nothing_else_in_the_file_moves(self):
        """These are hand-maintained files. A stamp that reserialises them would rewrite formatting the
        author chose and bury the one real change in diff noise."""
        before = (self.tmp / "package.json").read_text()
        stamp_plugin_version(self.tmp, "0.3.8")
        after = (self.tmp / "package.json").read_text()
        self.assertEqual(before.replace("6.2.0", "6.2.0+fleet.0.3.8"), after)

    def test_stamping_is_idempotent_for_one_version(self):
        stamp_plugin_version(self.tmp, "0.3.8")
        first = (self.tmp / "package.json").read_text()
        self.assertEqual(stamp_plugin_version(self.tmp, "0.3.8"), [])
        self.assertEqual((self.tmp / "package.json").read_text(), first)

    def test_an_ambiguous_version_field_is_refused_rather_than_guessed(self):
        """Two fields spelled `"version"` with the same value: which one the pipeline meant cannot be
        decided from the file, and picking the first would silently stamp the wrong one."""
        path = self.tmp / "package.json"
        path.write_text(json.dumps({"version": "6.2.0", "engines": {"version": "6.2.0"}}, indent=2))
        with self.assertRaises(BadInput) as caught:
            stamp_plugin_version(self.tmp, "0.3.8")
        self.assertIn("package.json", str(caught.exception))

    def test_a_declared_file_that_is_absent_is_reported_not_skipped_silently(self):
        (self.tmp / "gemini-extension.json").unlink()
        changed = stamp_plugin_version(self.tmp, "0.3.8")
        self.assertNotIn("gemini-extension.json", [path for path, _, _ in changed])
        self.assertEqual(len(changed), 3)


class CutFootprintCase(unittest.TestCase):
    """The trap. Stamping seven more files on every cut must not kill the exemption gate.

    `SI-19`'s shape, one layer over: `fleet/CHANGELOG.md` and `fleet/src/fleet/__init__.py` had to be
    carved out for exactly this reason in 0.3.7, and the unit tests all passed while the feature was dead
    because they fed `classify` hand-written path lists rather than a real cut's diff.
    """

    def test_the_manifests_the_cut_stamps_are_inert_as_PATHS(self):
        for path in sorted(MANIFESTS):
            with self.subTest(path=path):
                self.assertTrue(classify([path]).exempt,
                                f"{path} is stamped by every cut; treating it as an ordinary path makes "
                                f"exemption unreachable for every release that will ever exist")

    def test_a_realistic_skills_only_release_diff_is_still_exempt(self):
        """What the diff of a skills-only release looks like once the cut stamps the manifests."""
        scope = classify(["skills/releasing-fleet/SKILL.md",
                          "fleet/CHANGELOG.md", "fleet/src/fleet/__init__.py",
                          "package.json", ".claude-plugin/plugin.json",
                          ".claude-plugin/marketplace.json", "gemini-extension.json"])
        self.assertTrue(scope.exempt,
                        f"a skills-only release must still be exempt; requiring={scope.requiring}")

    def test_the_version_config_itself_still_requires_verification(self):
        """`.version-bump.json` declares WHICH files are stamped; the cut never rewrites it, so an edit
        to it is an author's change like any other."""
        self.assertFalse(classify([VERSION_CONFIG]).exempt)

    def test_only_the_version_field_is_stripped_when_comparing_two_stamps(self):
        before = '{\n  "name": "x",\n  "version": "6.2.0+fleet.0.3.7"\n}\n'
        after = '{\n  "name": "x",\n  "version": "6.2.0+fleet.0.3.8"\n}\n'
        self.assertEqual(without_version_field(before), without_version_field(after))

    def test_a_real_edit_to_a_manifest_still_shows_through(self):
        """The other half of the carve-out. `classify` sees paths; the CONTENT check in `exemption_for`
        is what stops an author's edit to `plugin.json` riding out on a version stamp."""
        before = '{\n  "name": "superpowers",\n  "version": "6.2.0+fleet.0.3.7"\n}\n'
        after = '{\n  "name": "renamed",\n  "version": "6.2.0+fleet.0.3.8"\n}\n'
        self.assertNotEqual(without_version_field(before), without_version_field(after))


class AreasCase(unittest.TestCase):
    """`RI-13`. Naming the payload is a DESCRIPTION, not a gate, and the two have opposite safe defaults."""

    def test_a_changeset_is_bucketed_by_area(self):
        got = dict(areas(["fleet/src/fleet/cli.py", "skills/a/SKILL.md", "fleet/tests/test_x.py"]))
        self.assertEqual(got["fleet"], ("fleet/src/fleet/cli.py", "fleet/tests/test_x.py"))
        self.assertEqual(got["skills"], ("skills/a/SKILL.md",))

    def test_only_areas_that_actually_changed_are_reported(self):
        self.assertEqual([name for name, _ in areas(["docs/a.md"])], ["docs"])

    def test_an_unrecognised_path_is_named_rather_than_hidden(self):
        """`D-6`. `classify` is an allowlist because its failure mode must be a needless test run. This
        one describes, and nothing branches on it, so an unknown path is named under `other` — hiding it
        is the only outcome that would be wrong."""
        got = dict(areas(["something-invented-tomorrow/thing.py"]))
        self.assertEqual(got["other"], ("something-invented-tomorrow/thing.py",))

    def test_describing_a_path_never_makes_it_exempt(self):
        """The two classifiers stay independent. If `areas` ever fed `classify`, an `other` bucket would
        become a hole in the gate."""
        for path in ("something-invented-tomorrow/thing.py", "fleet/src/fleet/cli.py", "bin/fleet"):
            with self.subTest(path=path):
                self.assertTrue(areas([path]))
                self.assertFalse(classify([path]).exempt)

    def test_the_skills_area_names_the_skills_and_not_the_files(self):
        """What a reader wants is `releasing-fleet`, not four paths under it."""
        from fleet.release_scope import skills_changed
        self.assertEqual(skills_changed(["skills/releasing-fleet/SKILL.md",
                                         "skills/releasing-fleet/references/x.md",
                                         "skills/using-fleet/SKILL.md"]),
                         ("releasing-fleet", "using-fleet"))

    def test_areas_are_reported_in_a_declared_order_not_in_diff_order(self):
        """So two releases' notes are comparable at a glance."""
        first = [name for name, _ in areas(["skills/a/SKILL.md", "fleet/x.py"])]
        second = [name for name, _ in areas(["fleet/x.py", "skills/a/SKILL.md"])]
        self.assertEqual(first, second)

    def test_the_cuts_own_two_files_are_not_payload(self):
        """A release's payload description must not be dominated by the release's own bookkeeping."""
        got = dict(areas(["fleet/CHANGELOG.md", "fleet/src/fleet/__init__.py",
                          "skills/a/SKILL.md"]))
        self.assertNotIn("fleet", got)
        self.assertEqual(got["skills"], ("skills/a/SKILL.md",))


class ChangelogPayloadCase(unittest.TestCase):
    """The section a reader actually opens."""

    def _section(self, changed):
        from fleet.release import Version
        from fleet.release_git import changelog_section
        return changelog_section(Version.parse("0.3.8"), head="abc1234", branch="live",
                                 upstream_base="base", prev_tag="fleet/v0.3.7",
                                 commits=[("abc1234", "a change")], rebased=False,
                                 when="2026-08-06T00:00:00Z", changed_paths=changed)

    def test_the_section_names_the_areas_the_release_touches(self):
        section = self._section(["fleet/src/fleet/cli.py", "skills/a/SKILL.md"])
        self.assertIn("fleet", section)
        self.assertIn("skills", section)

    def test_a_skills_only_release_is_distinguishable_from_a_cli_release(self):
        """`AC-4`, stated as the two documents a reader would compare."""
        skills_only = self._section(["skills/releasing-fleet/SKILL.md", "fleet/CHANGELOG.md",
                                     "fleet/src/fleet/__init__.py", "package.json"])
        cli_release = self._section(["fleet/src/fleet/cli.py", "fleet/CHANGELOG.md",
                                     "fleet/src/fleet/__init__.py", "package.json"])
        self.assertNotEqual(skills_only, cli_release)
        self.assertIn("releasing-fleet", skills_only,
                      "a skills-only release must name the skills it changed")
        self.assertNotIn("releasing-fleet", cli_release)

    def test_a_release_with_no_path_information_still_renders(self):
        """`changed_paths` is optional: an initial release has no predecessor to diff against."""
        from fleet.release import Version
        from fleet.release_git import changelog_section
        section = changelog_section(Version.parse("0.1.0"), head="abc1234", branch="live",
                                    upstream_base="base", prev_tag=None, commits=[],
                                    rebased=False, when="2026-08-06T00:00:00Z")
        self.assertIn("Initial release", section)

    def test_the_payload_line_states_that_a_release_ships_the_whole_repository(self):
        """The fact behind the defect: a reader who thinks "fleet release" means "the CLI" is wrong, and
        the notes are where that gets corrected."""
        self.assertIn("skills", self._section(["fleet/src/fleet/cli.py"]).lower())


class CutPayloadCase(ReleaseCliFixture, unittest.TestCase):
    """End to end, through a real `release-cut` on a real throwaway checkout."""

    def repo(self):
        repo = super().repo()
        seed_manifests(repo)
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", "the manifests")
        return repo

    def _cut(self, repo, version, *extra):
        return self.run_verb("release-cut", "--version", version, "--repo", str(repo),
                             "--releases", str(self.releases), *extra)

    def test_a_cut_stamps_the_manifests_with_the_fleet_version(self):
        from fleet import EXIT_OK
        repo = self.repo()
        self.assertEqual(self._cut(repo, "0.1.0"), EXIT_OK, self.err.getvalue())
        body = json.loads((repo / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(body["version"], "6.2.0+fleet.0.1.0")

    def test_the_export_carries_the_stamped_manifest(self):
        """The export is a `git archive` of the tag, and the tag is made after the stamp commit — so if
        the stamp is not committed before the tag, the artifact ships the old number."""
        from fleet.release import Releases, Version
        repo = self.repo()
        self._cut(repo, "0.1.0")
        export = Releases(self.releases).dir_for(Version.parse("0.1.0"))
        body = json.loads((export / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(body["version"], "6.2.0+fleet.0.1.0")

    def test_a_cut_writes_a_payload_register_naming_what_changed(self):
        from fleet.release import META_DIR, Releases, Version
        repo = self.repo()
        self._cut(repo, "0.1.0")
        (repo / "skills" / "demo").mkdir(parents=True)
        (repo / "skills" / "demo" / "SKILL.md").write_text("---\nname: demo\n---\nbody\n")
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", "a skill")
        self._cut(repo, "0.1.1")

        payload = (Releases(self.releases).dir_for(Version.parse("0.1.1")) / META_DIR / "PAYLOAD.tsv")
        self.assertTrue(payload.is_file(), "the cut wrote no payload register")
        text = payload.read_text()
        self.assertIn("skills", text)
        self.assertIn("demo", text)

    def test_the_payload_register_never_lists_the_cuts_own_files(self):
        """`AS-6`. The diff is taken BEFORE the changelog and stamp commit, so the release's own
        bookkeeping cannot masquerade as its payload."""
        from fleet.release import META_DIR, Releases, Version
        repo = self.repo()
        self._cut(repo, "0.1.0")
        (repo / "docs").mkdir(exist_ok=True)
        (repo / "docs" / "note.md").write_text("note\n")
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", "a doc")
        self._cut(repo, "0.1.1")

        text = (Releases(self.releases).dir_for(Version.parse("0.1.1"))
                / META_DIR / "PAYLOAD.tsv").read_text()
        self.assertNotIn("fleet/CHANGELOG.md", text)
        self.assertNotIn("fleet/src/fleet/__init__.py", text)
        self.assertNotIn("package.json", text)

    def test_a_dry_run_previews_the_payload_and_the_stamps(self):
        """A dry run whose only unknown is "what will this actually ship" answers the easy half. The
        payload is the half an operator gets wrong, because "fleet release" reads as "the CLI"."""
        repo = self.repo()
        self._cut(repo, "0.1.0")
        (repo / "skills" / "demo").mkdir(parents=True)
        (repo / "skills" / "demo" / "SKILL.md").write_text("---\nname: demo\n---\nbody\n")
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", "a skill")
        self.out.truncate(0), self.out.seek(0)
        self._cut(repo, "0.1.1", "--dry-run")
        printed = self.out.getvalue()
        self.assertIn("would-ship-skill-names", printed, printed)
        self.assertEqual(len([r for r in printed.splitlines()
                              if r.startswith("would-ship-skills ")]), 1,
                         "two rows under one key is a report nobody can parse")
        self.assertIn("demo", printed)
        self.assertIn("would-stamp", printed)

    def test_a_dry_run_still_writes_nothing(self):
        """The stamp preview reads the manifests; it must not touch them."""
        repo = self.repo()
        self._cut(repo, "0.1.0")
        before = self.snapshot()
        self._cut(repo, "0.1.1", "--dry-run")
        self.assertEqual(self.snapshot(), before)

    def test_an_unstampable_manifest_refuses_before_the_changelog_is_written(self):
        """`release-cut` already refuses a checkout missing `__init__.py` AT THE EDGE, because "the
        alternative is a failure half way through, after the changelog has been written". The manifests
        the cut also stamps get the same treatment, or `RI-12`'s fix introduces exactly that failure."""
        from fleet import EXIT_BAD_INPUT
        repo = self.repo()
        (repo / "package.json").write_text('{"name": "x"}\n')          # declared field is gone
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", "lost the version field")
        before = (repo / "fleet" / "CHANGELOG.md").is_file()
        self.assertEqual(self._cut(repo, "0.1.0"), EXIT_BAD_INPUT, self.err.getvalue())
        self.assertEqual((repo / "fleet" / "CHANGELOG.md").is_file(), before,
                         "the changelog was written before the manifest check refused")
        self.assertEqual(self._git(repo, "status", "--porcelain"), "",
                         "the operator's checkout was left dirty by a refused cut")

    def test_release_status_names_the_payload_of_the_deployed_release(self):
        """`AC-4`'s second reader: someone with the box and no repository."""
        from fleet.release import RELEASED, Releases, Version
        repo = self.repo()
        self._cut(repo, "0.1.0")
        (repo / "skills" / "demo").mkdir(parents=True)
        (repo / "skills" / "demo" / "SKILL.md").write_text("---\nname: demo\n---\nbody\n")
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", "a skill")
        self._cut(repo, "0.1.1")

        rel = Releases(self.releases)
        version = Version.parse("0.1.1")
        rel.set_state(version, RELEASED)
        rel.point_current_at(rel.dir_for(version))
        rel.append_history(action="DEPLOY", version="0.1.1", from_version="0.1.0",
                           reason="test", evidence="-")
        self.out.truncate(0), self.out.seek(0)
        self.run_verb("release-status", "--releases", str(self.releases), "--porcelain")
        printed = self.out.getvalue()
        self.assertIn("payload", printed, f"release-status says nothing about the payload:\n{printed}")
        self.assertIn("skills", printed)


if __name__ == "__main__":                                   # pragma: no cover
    unittest.main()
