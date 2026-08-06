"""The classification that decides whether a release may skip the suites.

This is the highest-consequence pure function in the package: a wrong `True` here ships an unverified
release to `current`, which is the plugin marketplace source every session on the box loads its skills
from. So the rule is fail-safe by construction — a path is inert only if it MATCHES something declared,
never merely because it failed to match `fleet/`.
"""
import unittest

from fleet.release_scope import classify


class TestInertPathsAreRecognised(unittest.TestCase):
    """The whole point: a docs- or skills-only release should not pay a 24-minute gate to prove that
    `fleet/` — which it did not touch — still works."""

    def test_documentation_only_change_is_exempt(self):
        scope = classify(["docs/superpowers/specs/2026-08-06-foo.md", "README.md"])
        self.assertEqual(scope.requiring, ())
        self.assertTrue(scope.exempt)

    def test_every_declared_inert_root_file_is_inert(self):
        for name in ("README.md", "LICENSE", "CODE_OF_CONDUCT.md", "RELEASE-NOTES.md",
                     "AGENTS.md", "GEMINI.md", "CLAUDE.md"):
            with self.subTest(name=name):
                self.assertTrue(classify([name]).exempt, f"{name} should be inert")

    def test_assets_and_docs_trees_are_inert(self):
        self.assertTrue(classify(["docs/a/b/c.md", "assets/logo.png"]).exempt)

    def test_an_ordinary_skill_edit_is_exempt(self):
        """The motivating case. Editing `brainstorming` cannot affect a suite that tests `fleet/`."""
        scope = classify(["skills/brainstorming/SKILL.md",
                          "skills/writing-plans/SKILL.md"])
        self.assertTrue(scope.exempt)
        self.assertEqual(len(scope.inert), 2)

    def test_no_changed_paths_at_all_is_exempt(self):
        """An empty delta means the tree is identical to the anchor, which passed. Nothing to re-prove."""
        self.assertTrue(classify([]).exempt)


class TestTheUsingFleetCarveOut(unittest.TestCase):
    """`skills/using-fleet/**` is NOT inert, and this is the single most important assertion in the file.

    Two suite call-sites read it, so "outside `fleet/`" and "not covered by the suites" are different
    statements:

    * `fleet/tests/test_contracts.py` — `TestEveryVerbIsDocumentedWhereUsersLook` asserts in BOTH
      directions that `skills/using-fleet/SKILL.md` names exactly the verbs `cli.VERBS` declares. Rename
      a verb mention there and the hermetic suite goes red.
    * `fleet/it/run-P.sh:76` — `cp -r "$IT_ROOT/../../skills/using-fleet/profiles/worker" "$PROFILE"`.
      The IT suite builds a live fixture out of that directory.

    Delete this carve-out and a release editing that skill skips the gate and ships the break to
    `current`. If this test ever fails, do not "fix" it by widening the inert set — check whether those
    two call-sites still exist first.
    """

    def test_the_using_fleet_skill_doc_requires_verification(self):
        scope = classify(["skills/using-fleet/SKILL.md"])
        self.assertEqual(scope.inert, ())
        self.assertFalse(scope.exempt)

    def test_the_using_fleet_worker_profile_requires_verification(self):
        self.assertFalse(classify(["skills/using-fleet/profiles/worker/profile.json"]).exempt)

    def test_the_carve_out_beats_the_general_skills_rule(self):
        """Order matters: `skills/` is inert and `skills/using-fleet/` is not, so a mixed changeset must
        come back requiring — the narrower rule wins."""
        scope = classify(["skills/brainstorming/SKILL.md", "skills/using-fleet/SKILL.md"])
        self.assertFalse(scope.exempt)
        self.assertEqual(scope.inert, ("skills/brainstorming/SKILL.md",))
        self.assertEqual(scope.requiring, ("skills/using-fleet/SKILL.md",))

    def test_a_lookalike_sibling_is_still_inert(self):
        """`skills/using-fleet-notes/` is a different directory; the carve-out must match on the path
        SEGMENT, not on a bare string prefix, or an unrelated skill inherits the gate."""
        self.assertTrue(classify(["skills/using-fleet-notes/SKILL.md"]).exempt)


class TestUnknownPathsFailSafe(unittest.TestCase):
    """The design decision this module exists to enforce: an ALLOWLIST, not a denylist.

    A denylist ("verify only if `fleet/**` changed") is fail-open — a new top-level directory, or a
    suite that later reads a new script, becomes silently exempt and the failure ships invisibly. The
    allowlist's failure mode is a needless 24-minute run, which is merely annoying.
    """

    def test_fleet_itself_requires_verification(self):
        self.assertFalse(classify(["fleet/src/fleet/cli.py"]).exempt)

    def test_a_brand_new_top_level_directory_requires_verification(self):
        """Nobody will remember to update this module when they add a directory. They do not have to."""
        self.assertFalse(classify(["something-invented-tomorrow/thing.py"]).exempt)

    def test_infrastructure_paths_require_verification(self):
        for path in ("scripts/sync/lib.sh", "hooks/session-start", "bin/fleet",
                     "tests/test_x.py", "package.json", ".claude-plugin/plugin.json",
                     "patches/p.diff", "_staging/x", "gemini-extension.json"):
            with self.subTest(path=path):
                self.assertFalse(classify([path]).exempt, f"{path} must require verification")

    def test_one_requiring_path_taints_an_otherwise_inert_changeset(self):
        scope = classify(["docs/a.md", "README.md", "fleet/src/fleet/release.py"])
        self.assertFalse(scope.exempt)
        self.assertEqual(scope.requiring, ("fleet/src/fleet/release.py",))

    def test_a_root_markdown_file_that_is_not_declared_requires_verification(self):
        """`CLAUDE.md` is declared inert; an undeclared root doc is not inert by analogy."""
        self.assertFalse(classify(["SECURITY.md"]).exempt)


class TestTheCutsOwnFootprint(unittest.TestCase):
    """`release-cut` writes two files ITSELF, on every cut, before it tags.

    This is what made the first implementation of this feature DEAD ON ARRIVAL. The diff between two
    release tags is never just the author's change: under its lock the cut prepends a section to
    `fleet/CHANGELOG.md` and rewrites `__version__` in `fleet/src/fleet/__init__.py`, then commits both as
    `fleet vX.Y.Z` and tags THAT commit. So a documentation-only release still shows two `fleet/**` paths
    changed, and a naive classifier answers "verify required" for every release that will ever exist —
    a correct, tested, unreachable feature, which is `SI-19`'s exact shape.

    Measured, not reasoned about: `git diff --name-only fleet/v0.3.5..fleet/v0.3.6` on a commit that
    touched one spec file returned

        docs/superpowers/specs/2026-08-06-release-test-exemption-design.md
        fleet/CHANGELOG.md
        fleet/src/fleet/__init__.py

    The unit tests all passed while this was true, because they fed `classify` hand-written path lists and
    never a real cut's diff. That gap is what these cases close.
    """

    def test_the_changelog_the_cut_writes_is_inert(self):
        """Pure documentation, and the cut appends to it on every single release."""
        self.assertTrue(classify(["fleet/CHANGELOG.md"]).exempt)

    def test_a_realistic_docs_only_release_diff_is_exempt(self):
        """The exact shape above. If this fails, the feature is unreachable again."""
        scope = classify(["docs/superpowers/specs/2026-08-06-release-test-exemption-design.md",
                          "fleet/CHANGELOG.md",
                          "fleet/src/fleet/__init__.py"])
        self.assertTrue(scope.exempt,
                        f"a docs-only release must be exempt; requiring={scope.requiring}")

    def test_the_stamped_init_is_inert_only_as_a_PATH(self):
        """`classify` sees paths, not contents, so it cannot tell a version stamp from a real edit to that
        file — `exemption_for` compares the two blobs with the `__version__` line stripped and puts the
        path back if anything else moved. That split is deliberate: this module stays pure, and the
        content check lives where the repository is available. See `test_release_exemption`."""
        self.assertTrue(classify(["fleet/src/fleet/__init__.py"]).exempt)

    def test_no_other_fleet_source_file_is_inert(self):
        """The carve-out is exactly two paths. Nothing else under `fleet/src/` inherits it."""
        for path in ("fleet/src/fleet/cli.py", "fleet/src/fleet/release.py",
                     "fleet/src/fleet/release_scope.py", "fleet/src/fleet/__main__.py",
                     "fleet/tests/test_cli.py", "fleet/it/run-A.sh", "fleet/CLAUDE.md"):
            with self.subTest(path=path):
                self.assertFalse(classify([path]).exempt, f"{path} must require verification")


class TestVersionLineStripping(unittest.TestCase):
    """`without_version_line` is how a version stamp is told apart from a real edit to the same file."""

    def test_only_the_version_assignment_is_removed(self):
        from fleet.release_scope import without_version_line
        before = '"""doc"""\n__version__ = "0.3.5"\n\nEXIT_OK = 0\n'
        after = '"""doc"""\n__version__ = "0.3.6"\n\nEXIT_OK = 0\n'
        self.assertEqual(without_version_line(before), without_version_line(after))

    def test_a_real_edit_still_shows_through(self):
        from fleet.release_scope import without_version_line
        before = '__version__ = "0.3.5"\nEXIT_OK = 0\n'
        after = '__version__ = "0.3.6"\nEXIT_OK = 9\n'
        self.assertNotEqual(without_version_line(before), without_version_line(after))

    def test_an_edit_that_only_reformats_the_version_line_is_still_equal(self):
        from fleet.release_scope import without_version_line
        self.assertEqual(without_version_line('__version__="1.0.0"\nX = 1\n'),
                         without_version_line('__version__ = "2.0.0"\nX = 1\n'))


class TestNormalisation(unittest.TestCase):
    """`git diff --name-only` output is repo-relative and slash-separated, but the module is fed by a
    caller and must not be tricked by trivial spellings into reading a requiring path as inert."""

    def test_leading_dot_slash_is_stripped(self):
        self.assertFalse(classify(["./fleet/src/fleet/cli.py"]).exempt)

    def test_blank_entries_are_ignored_not_treated_as_inert(self):
        scope = classify(["", "   ", "docs/a.md"])
        self.assertTrue(scope.exempt)
        self.assertEqual(scope.inert, ("docs/a.md",))

    def test_a_parent_traversal_requires_verification(self):
        self.assertFalse(classify(["docs/../fleet/src/fleet/cli.py"]).exempt)

    def test_the_bare_carve_out_directory_requires_verification(self):
        self.assertFalse(classify(["skills/using-fleet"]).exempt)

    def test_results_preserve_input_order_and_deduplicate(self):
        scope = classify(["docs/b.md", "docs/a.md", "docs/b.md"])
        self.assertEqual(scope.inert, ("docs/b.md", "docs/a.md"))


if __name__ == "__main__":
    unittest.main()
