"""Anchor selection, the exemption decision, and the promote gate that accepts it.

`test_release_scope` proves the classifier in isolation. This file proves the parts that decide WHICH
two trees get classified, and what a release may do with the answer -- the places where a correct
classifier could still be wired into an incorrect skip.
"""
import pathlib
import tempfile
import unittest

from fleet.errors import Refused
from fleet.release import META_DIR, Releases, Version
from fleet.release_verify import (EXEMPT, EXEMPT_ROSTER, FULL_ROSTER, GATE_ROSTER, GREEN,
                                  exemption_for, last_green, read_verdict, write_exemption,
                                  write_verdict)


class ExemptionCase(unittest.TestCase):

    class FakeRepo:
        """The two `Repo` methods the exemption path uses, and nothing else.

        Real git is exercised in `GitCase`; here the interesting behaviour is what the decision does with
        the diff it is handed, so the diff is declared rather than produced.
        """

        def __init__(self, changed=(), tags=()):
            self.path = pathlib.Path("/fake/repo")
            self.changed = list(changed)
            self.tags = set(tags)
            self.asked = []

        def tag_exists(self, name):
            return name in self.tags

        def changed_paths(self, from_ref, to_ref):
            self.asked.append((from_ref, to_ref))
            return list(self.changed)

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-exempt-"))
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.rel = Releases(self.tmp / "releases")

    def _release(self, version, verdict=None, roster=GATE_ROSTER):
        """A release directory with a MANIFEST and, optionally, a recorded verdict."""
        v = Version.parse(version)
        (self.rel.dir_for(v) / META_DIR).mkdir(parents=True)
        self.rel.write_manifest(v, {"version": version, "tag": f"fleet/v{version}"})
        if verdict is not None:
            write_verdict(self.rel.dir_for(v) / META_DIR,
                          [("hermetic", verdict, "e", "-"), ("it", verdict, "e", "-")], roster)
        return v

    # --- the anchor -----------------------------------------------------------------------------------

    def test_the_anchor_is_the_newest_green_release_below_this_one(self):
        self._release("0.1.0", GREEN)
        self._release("0.2.0", GREEN)
        self._release("0.3.0", "RED")
        target = self._release("0.4.0")
        self.assertEqual(str(last_green(self.rel, target)), "0.2.0")

    def test_an_exempt_release_is_never_an_anchor(self):
        """The guarantee has to stay flat. If an EXEMPT release could anchor the next one, a run of
        docs-only releases would drift arbitrarily far from any tree a suite has actually seen, each
        one certified only against its equally-uncertified predecessor."""
        self._release("0.1.0", GREEN)
        self._release("0.2.0", EXEMPT, EXEMPT_ROSTER)
        self._release("0.3.0", EXEMPT, EXEMPT_ROSTER)
        target = self._release("0.4.0")
        self.assertEqual(str(last_green(self.rel, target)), "0.1.0")

    def test_no_green_release_at_all_has_no_anchor(self):
        self._release("0.1.0", "INCONCLUSIVE")
        self.assertIsNone(last_green(self.rel, self._release("0.2.0")))

    def test_a_release_with_no_verdict_file_is_not_an_anchor(self):
        """The ordinary state of a fresh candidate. Absence of evidence is not GREEN."""
        self._release("0.1.0")
        self.assertIsNone(last_green(self.rel, self._release("0.2.0")))

    def test_the_anchor_is_chosen_by_semver_not_by_creation_order(self):
        self._release("0.10.0", GREEN)
        self._release("0.9.0", GREEN)
        self.assertEqual(str(last_green(self.rel, self._release("0.11.0"))), "0.10.0")

    # --- the decision ---------------------------------------------------------------------------------

    def test_an_inert_diff_against_a_green_anchor_is_exempt(self):
        anchor = self._release("0.1.0", GREEN)
        target = self._release("0.1.1")
        repo = self.FakeRepo(changed=["docs/a.md", "skills/brainstorming/SKILL.md"],
                             tags=["fleet/v0.1.0", "fleet/v0.1.1"])
        result = exemption_for(self.rel, target, repo)
        self.assertIsNotNone(result)
        found_anchor, scope = result
        self.assertEqual(found_anchor, anchor)
        self.assertTrue(scope.exempt)
        self.assertEqual(repo.asked, [("fleet/v0.1.0", "fleet/v0.1.1")],
                         "the diff must be anchor..this, taken from the recorded tags")

    def test_a_diff_touching_fleet_is_not_exempt(self):
        self._release("0.1.0", GREEN)
        target = self._release("0.1.1")
        repo = self.FakeRepo(changed=["docs/a.md", "fleet/src/fleet/cli.py"],
                             tags=["fleet/v0.1.0", "fleet/v0.1.1"])
        self.assertIsNone(exemption_for(self.rel, target, repo))

    def test_a_diff_touching_the_using_fleet_skill_is_not_exempt(self):
        """The carve-out, reaching all the way through the wiring: `test_contracts` asserts verb parity
        against that file and `run-P.sh` copies its worker profile, so editing it is a change a suite can
        observe even though it lives outside `fleet/`."""
        self._release("0.1.0", GREEN)
        target = self._release("0.1.1")
        repo = self.FakeRepo(changed=["skills/using-fleet/SKILL.md"],
                             tags=["fleet/v0.1.0", "fleet/v0.1.1"])
        self.assertIsNone(exemption_for(self.rel, target, repo))

    def test_full_never_exempts(self):
        """An operator who names the full roster gets the full roster. `--full` is also the documented
        escape hatch when someone wants the suites run regardless."""
        self._release("0.1.0", GREEN)
        target = self._release("0.1.1")
        repo = self.FakeRepo(changed=["docs/a.md"], tags=["fleet/v0.1.0", "fleet/v0.1.1"])
        self.assertIsNone(exemption_for(self.rel, target, repo, full=True))

    def test_no_anchor_means_run_the_suites(self):
        """Nothing to claim identity with, so there is no exemption to be had -- even for a pure docs
        diff. This is the state a release area is in before its first GREEN."""
        self._release("0.1.0")
        target = self._release("0.1.1")
        repo = self.FakeRepo(changed=["docs/a.md"], tags=["fleet/v0.1.0", "fleet/v0.1.1"])
        self.assertIsNone(exemption_for(self.rel, target, repo))

    def test_a_missing_anchor_tag_is_refused_not_treated_as_no_change(self):
        """The failure that would otherwise be silent and catastrophic: `git diff` against a tag that is
        not there. 'I cannot tell' must never resolve to 'nothing changed'."""
        self._release("0.1.0", GREEN)
        target = self._release("0.1.1")
        repo = self.FakeRepo(changed=[], tags=["fleet/v0.1.1"])       # anchor tag absent
        with self.assertRaises(Refused) as caught:
            exemption_for(self.rel, target, repo)
        self.assertIn("fleet/v0.1.0", str(caught.exception))

    def test_an_empty_diff_is_exempt(self):
        """Identical trees. There is nothing a suite could measure that the anchor did not already."""
        self._release("0.1.0", GREEN)
        target = self._release("0.1.1")
        repo = self.FakeRepo(changed=[], tags=["fleet/v0.1.0", "fleet/v0.1.1"])
        self.assertIsNotNone(exemption_for(self.rel, target, repo))

    # --- the cut's own footprint ----------------------------------------------------------------------

    class BlobRepo(FakeRepo):
        """A repo that can also answer "what did this file look like at that ref"."""

        def __init__(self, changed=(), tags=(), blobs=None):
            super().__init__(changed, tags)
            self.blobs = dict(blobs or {})

        def file_at(self, ref, path):
            return self.blobs.get((ref, path), "")

    def _cut_shaped(self, blobs):
        """A realistic release diff: the author's file plus the two the cut writes itself."""
        return self.BlobRepo(
            changed=["docs/a.md", "fleet/CHANGELOG.md", "fleet/src/fleet/__init__.py"],
            tags=["fleet/v0.1.0", "fleet/v0.1.1"], blobs=blobs)

    def test_a_real_docs_release_is_exempt_despite_the_cuts_own_stamp(self):
        """The case that made the first implementation DEAD ON ARRIVAL.

        `release-cut` prepends to `fleet/CHANGELOG.md` and rewrites `__version__` before it tags, so EVERY
        pair of release tags differs by those two `fleet/**` paths. Measured on the real thing:
        `git diff --name-only fleet/v0.3.5..fleet/v0.3.6`, for a commit touching one spec file, returned
        exactly the three paths below. Nothing could ever have been exempt.
        """
        self._release("0.1.0", GREEN)
        target = self._release("0.1.1")
        repo = self._cut_shaped({
            ("fleet/v0.1.0", "fleet/src/fleet/__init__.py"): '__version__ = "0.1.0"\nEXIT_OK = 0\n',
            ("fleet/v0.1.1", "fleet/src/fleet/__init__.py"): '__version__ = "0.1.1"\nEXIT_OK = 0\n'})
        result = exemption_for(self.rel, target, repo)
        self.assertIsNotNone(result, "a docs-only release must be exempt despite the cut's own stamp")
        self.assertTrue(result[1].exempt)

    def test_a_real_edit_to_the_stamped_file_still_requires_verification(self):
        """The safety hole the fix above could have opened. `__init__.py` also carries the exit-code
        registry, so it is inert ONLY when nothing but `__version__` moved. An edit to `EXIT_OK` riding
        out on a version stamp would be a genuinely unverified release."""
        self._release("0.1.0", GREEN)
        target = self._release("0.1.1")
        repo = self._cut_shaped({
            ("fleet/v0.1.0", "fleet/src/fleet/__init__.py"): '__version__ = "0.1.0"\nEXIT_OK = 0\n',
            ("fleet/v0.1.1", "fleet/src/fleet/__init__.py"): '__version__ = "0.1.1"\nEXIT_OK = 9\n'})
        result = exemption_for(self.rel, target, repo)
        self.assertIsNone(result, "an edit to the exit-code registry must not ride out on a version stamp")

    def test_the_stamped_file_is_named_in_requiring_when_it_really_changed(self):
        """Not merely 'not exempt' — the path has to come back in `requiring`, because that list is what
        `EXEMPTION.tsv` and any future diagnostic report."""
        from fleet.release_scope import CUT_STAMPED, Scope, classify, without_version_line
        scope = classify(["docs/a.md", CUT_STAMPED])
        self.assertIn(CUT_STAMPED, scope.inert)
        moved = Scope([p for p in scope.inert if p != CUT_STAMPED],
                      list(scope.requiring) + [CUT_STAMPED])
        self.assertEqual(moved.requiring, (CUT_STAMPED,))
        self.assertFalse(moved.exempt)
        self.assertNotEqual(without_version_line('__version__ = "1"\nA = 1\n'),
                            without_version_line('__version__ = "2"\nA = 2\n'))

    # --- the evidence ---------------------------------------------------------------------------------

    def test_the_exemption_file_records_every_path_and_both_tags(self):
        """An exempt promotion still cites a measurement someone can go and look at; the measurement is
        the diff. It has to be re-derivable by hand from what is written down."""
        from fleet.release_scope import classify
        anchor = self._release("0.1.0", GREEN)
        target = self._release("0.1.1")
        meta = self.rel.dir_for(target) / META_DIR
        scope = classify(["docs/a.md", "README.md"])
        write_exemption(meta, target, anchor, "fleet/v0.1.0", "fleet/v0.1.1", scope)
        body = (meta / "evidence" / "EXEMPTION.tsv").read_text()
        self.assertIn("anchor\t0.1.0", body)
        self.assertIn("compared\tfleet/v0.1.0..fleet/v0.1.1", body)
        self.assertIn("path\tdocs/a.md\tinert", body)
        self.assertIn("path\tREADME.md\tinert", body)
        self.assertIn("paths_changed\t2", body)

    def test_an_exempt_verdict_is_not_spelled_green(self):
        """`SI-38` is what a verdict whose evidence does not support it costs. A reader must be able to
        tell 'the suites passed' from 'the suites were not required'."""
        target = self._release("0.1.1")
        meta = self.rel.dir_for(target) / META_DIR
        write_verdict(meta, [("hermetic", EXEMPT, "evidence/EXEMPTION.tsv", "not required"),
                             ("it", EXEMPT, "evidence/EXEMPTION.tsv", "not required")], EXEMPT_ROSTER)
        verdict = read_verdict(meta)
        self.assertEqual(set(verdict["suites"].values()), {EXEMPT})
        self.assertNotIn(GREEN, verdict["suites"].values())
        self.assertEqual(verdict["roster"], EXEMPT_ROSTER)


class PromoteGateCase(unittest.TestCase):
    """`release-promote` reads what `verify` left. These are the admission rules over that file."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-promotegate-"))
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.rel = Releases(self.tmp / "releases")

    def _release(self, version, verdict=None, roster=GATE_ROSTER):
        v = Version.parse(version)
        (self.rel.dir_for(v) / META_DIR).mkdir(parents=True)
        self.rel.write_manifest(v, {"version": version, "tag": f"fleet/v{version}"})
        if verdict is not None:
            write_verdict(self.rel.dir_for(v) / META_DIR,
                          [("hermetic", verdict, "e", "-"), ("it", verdict, "e", "-")], roster)
        return v

    #: `main` returns the registered exit code rather than propagating; a refusal is `4`. Asserting on
    #: the CODE and the printed sentence is the right level here -- that pair is what an operator and a
    #: script actually see, and a gate that refused with the wrong number would still pass a test that
    #: only caught the exception type.
    REFUSED = 4

    def _promote(self, version):
        """Drive the real handler through the real parser, so the gate under test is the shipped one."""
        import io

        from fleet.cli import main
        err = io.StringIO()
        code = main(["release-promote", "--version", str(version),
                     "--releases", str(self.rel.root)], stdout=io.StringIO(), stderr=err)
        return code, err.getvalue()

    def test_an_exempt_release_promotes(self):
        """The point of the whole mechanism: no `--force`, no manual judgement, exit 0."""
        self._release("0.1.0", GREEN)
        v = self._release("0.1.1", EXEMPT, EXEMPT_ROSTER)
        self.assertEqual(self._promote(v)[0], 0)
        self.assertEqual(self.rel.state(v), "RELEASED")

    def test_a_green_release_still_promotes(self):
        v = self._release("0.1.0", GREEN)
        self.assertEqual(self._promote(v)[0], 0)
        self.assertEqual(self.rel.state(v), "RELEASED")

    def test_a_red_release_is_still_refused(self):
        v = self._release("0.1.0", "RED")
        code, _ = self._promote(v)
        self.assertEqual(code, self.REFUSED)
        self.assertEqual(self.rel.state(v), "CANDIDATE")

    def test_an_inconclusive_release_is_still_refused(self):
        """The verdict this drill hit twice. Contamination is not evidence."""
        v = self._release("0.1.0", "INCONCLUSIVE")
        code, _ = self._promote(v)
        self.assertEqual(code, self.REFUSED)
        self.assertEqual(self.rel.state(v), "CANDIDATE")

    def test_a_release_with_no_verdict_is_still_refused(self):
        v = self._release("0.1.0")
        self.assertEqual(self._promote(v)[0], self.REFUSED)

    def test_a_half_exempt_verdict_is_refused(self):
        """One suite EXEMPT and the other RED is not promotable, and the `all values in PROMOTABLE` rule
        is what makes that true without anyone enumerating the combinations."""
        v = Version.parse("0.1.0")
        (self.rel.dir_for(v) / META_DIR).mkdir(parents=True)
        self.rel.write_manifest(v, {"version": "0.1.0", "tag": "fleet/v0.1.0"})
        write_verdict(self.rel.dir_for(v) / META_DIR,
                      [("hermetic", EXEMPT, "e", "-"), ("it", "RED", "e", "-")], EXEMPT_ROSTER)
        self.assertEqual(self._promote(v)[0], self.REFUSED)

    def test_an_exempt_minor_bump_is_refused(self):
        """A minor bump claims substantive change; an exemption claims nothing either suite reads was
        touched. Both cannot hold, and the operator should learn which from a suite rather than from
        production."""
        self._release("0.1.0", GREEN)
        v = self._release("0.2.0", EXEMPT, EXEMPT_ROSTER)
        code, message = self._promote(v)
        self.assertEqual(code, self.REFUSED)
        self.assertIn("EXEMPT", message)
        self.assertIn("--full", message, "the refusal must name the way out")

    def test_an_exempt_patch_bump_is_fine(self):
        self._release("0.1.0", GREEN)
        v = self._release("0.1.1", EXEMPT, EXEMPT_ROSTER)
        self.assertEqual(self._promote(v)[0], 0)

    def test_a_green_minor_bump_still_needs_the_full_roster(self):
        """The pre-existing rule, asserted here so the new EXEMPT branch cannot be seen to have
        displaced it."""
        self._release("0.1.0", GREEN)
        v = self._release("0.2.0", GREEN, GATE_ROSTER)
        self.assertEqual(self._promote(v)[0], self.REFUSED)
        self._release("0.3.0", GREEN, FULL_ROSTER)
        self.assertEqual(self._promote(Version.parse("0.3.0"))[0], 0)


if __name__ == "__main__":
    unittest.main()
