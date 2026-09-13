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
        """A repo that can also answer "what did this file look like at that ref".

        Models `Repo.file_at`'s two-part answer, `(code, contents)`. A blob that is not declared comes
        back as `(128, "")`, which is what `git show` does for a path that is not at that ref -- and the
        point of carrying the code is that the caller can tell that apart from a read that FAILED, which
        looks identical in the text alone.
        """

        def __init__(self, changed=(), tags=(), blobs=None, fail=()):
            super().__init__(changed, tags)
            self.blobs = dict(blobs or {})
            #: `(ref, path)` pairs where `git show` FAILS, as distinct from the file being absent.
            self.fail = set(fail)

        def file_at(self, ref, path):
            if (ref, path) in self.fail:
                return (128, "")
            if (ref, path) in self.blobs:
                return (0, self.blobs[(ref, path)])
            return (128, "")

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

    def _manifest_cut_shaped(self, blobs):
        """A release diff as it looks once the cut ALSO stamps the plugin manifests (`RI-12`)."""
        return self.BlobRepo(
            changed=["skills/releasing-fleet/SKILL.md", "fleet/CHANGELOG.md",
                     "fleet/src/fleet/__init__.py", ".claude-plugin/plugin.json"],
            tags=["fleet/v0.1.0", "fleet/v0.1.1"], blobs=blobs)

    def test_a_skills_release_is_exempt_despite_the_cuts_manifest_stamp(self):
        """`RI-12`'s trap, held shut where it would actually spring.

        Stamping the manifests puts seven more paths into every release's diff. If they are not carved out
        the way `__init__.py` is, the exemption feature 0.3.7 shipped becomes unreachable again -- and the
        unit tests over `classify` alone would not notice, because they feed hand-written path lists.
        """
        self._release("0.1.0", GREEN)
        target = self._release("0.1.1")
        repo = self._manifest_cut_shaped({
            ("fleet/v0.1.0", "fleet/src/fleet/__init__.py"): '__version__ = "0.1.0"\nEXIT_OK = 0\n',
            ("fleet/v0.1.1", "fleet/src/fleet/__init__.py"): '__version__ = "0.1.1"\nEXIT_OK = 0\n',
            ("fleet/v0.1.0", ".claude-plugin/plugin.json"):
                '{\n  "name": "superpowers",\n  "version": "6.2.0+fleet.0.1.0"\n}\n',
            ("fleet/v0.1.1", ".claude-plugin/plugin.json"):
                '{\n  "name": "superpowers",\n  "version": "6.2.0+fleet.0.1.1"\n}\n'})
        result = exemption_for(self.rel, target, repo)
        self.assertIsNotNone(result, "a skills-only release must stay exempt once the cut stamps the "
                                     "plugin manifests")

    def test_a_real_edit_to_a_manifest_still_requires_verification(self):
        """The other half, and the reason the carve-out is by PATH only. `plugin.json` carries the plugin
        name, the hook wiring and the marketplace entry beside its version; an edit to any of those riding
        out on a version stamp would be an unverified release of the thing sessions load skills from."""
        self._release("0.1.0", GREEN)
        target = self._release("0.1.1")
        repo = self._manifest_cut_shaped({
            ("fleet/v0.1.0", "fleet/src/fleet/__init__.py"): '__version__ = "0.1.0"\n',
            ("fleet/v0.1.1", "fleet/src/fleet/__init__.py"): '__version__ = "0.1.1"\n',
            ("fleet/v0.1.0", ".claude-plugin/plugin.json"):
                '{\n  "name": "superpowers",\n  "version": "6.2.0+fleet.0.1.0"\n}\n',
            ("fleet/v0.1.1", ".claude-plugin/plugin.json"):
                '{\n  "name": "renamed",\n  "version": "6.2.0+fleet.0.1.1"\n}\n'})
        self.assertIsNone(exemption_for(self.rel, target, repo),
                          "a rename in plugin.json must not ride out on a version stamp")

    def test_a_git_show_that_fails_on_BOTH_refs_must_not_read_as_unchanged(self):
        """`file_at` used to return `""` for a failed read and for an absent file alike, so a `git show`
        that failed on both refs of the same manifest compared `"" == ""`, the path stayed inert, and the
        release skipped its entire gate because a git command quietly failed.

        Every other uncertainty on this path answers "run the suites": `changed_paths` raises rather than
        returning empty, and a missing anchor tag is a `Refused`. This one answered "exempt" -- low
        probability, wrong direction, and the highest-stakes code in the package now that EXEMPT is
        reachable. The path only reaches the content re-check because `changed_paths` said it DIFFERS
        between the two refs, so it cannot legitimately be absent at both.
        """
        self._release("0.1.0", GREEN)
        target = self._release("0.1.1")
        repo = self._manifest_cut_shaped({
            ("fleet/v0.1.0", "fleet/src/fleet/__init__.py"): '__version__ = "0.1.0"\n',
            ("fleet/v0.1.1", "fleet/src/fleet/__init__.py"): '__version__ = "0.1.1"\n'})
        repo.fail = {("fleet/v0.1.0", ".claude-plugin/plugin.json"),
                     ("fleet/v0.1.1", ".claude-plugin/plugin.json")}
        result = exemption_for(self.rel, target, repo)
        self.assertIsNone(result, "a manifest whose blob could not be read at EITHER ref must put the "
                                  "path back into `requiring`, never ride out as unchanged")

    def test_a_git_show_that_fails_on_ONE_ref_also_requires_verification(self):
        """The asymmetric half. One readable side and one unreadable side is still "I could not tell",
        and it must answer the same way."""
        self._release("0.1.0", GREEN)
        target = self._release("0.1.1")
        repo = self._manifest_cut_shaped({
            ("fleet/v0.1.0", "fleet/src/fleet/__init__.py"): '__version__ = "0.1.0"\n',
            ("fleet/v0.1.1", "fleet/src/fleet/__init__.py"): '__version__ = "0.1.1"\n',
            ("fleet/v0.1.0", ".claude-plugin/plugin.json"):
                '{\n  "name": "superpowers",\n  "version": "6.2.0+fleet.0.1.0"\n}\n'})
        repo.fail = {("fleet/v0.1.1", ".claude-plugin/plugin.json")}
        self.assertIsNone(exemption_for(self.rel, target, repo),
                          "one unreadable side is still 'I could not tell', which must run the suites")

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


class DryRunCase(unittest.TestCase):
    """`release-verify --dry-run` reports the exemption decision, driven through the real `main`.

    `Repo` still enforces its own contract -- a real `.git` marker on disk, `tag_exists`,
    `changed_paths` raising on a bad ref -- so this exercises the same wiring `_do_release_verify` runs
    in production. Only the git PROCESS is faked, at the seam `Repo` already takes (`git`): the same
    reasoning `GitCase` (`test_release.py`) gives for using real git elsewhere applies in reverse here --
    the interesting behaviour is what the dry run does with the decision, not whether `Repo` can spell
    its own flags, so the diff is declared rather than produced.
    """

    def setUp(self):
        import shutil
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-dryrun-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.rel = Releases(self.tmp / "releases")
        self.repo_path = self.tmp / "repo"
        (self.repo_path / ".git").mkdir(parents=True)
        self.anchor = Version.parse("0.1.0")
        self.target = Version.parse("0.1.1")
        (self.rel.dir_for(self.anchor) / META_DIR).mkdir(parents=True)
        self.rel.write_manifest(self.anchor, {"version": "0.1.0", "tag": "fleet/v0.1.0"})
        write_verdict(self.rel.dir_for(self.anchor) / META_DIR,
                      [("hermetic", GREEN, "e", "-"), ("it", GREEN, "e", "-")], GATE_ROSTER)
        (self.rel.dir_for(self.target) / META_DIR).mkdir(parents=True)
        self.rel.write_manifest(self.target, {"version": "0.1.1", "tag": "fleet/v0.1.1"})

    #: `main` converts a `Refused` into this exit code (`errors.EXIT_REFUSED`); named here the way
    #: `PromoteGateCase.REFUSED` already does, so a regression shows as the wrong CODE, not a caught
    #: exception nobody asserted on.
    REFUSED = 4

    def _fake_git(self, changed, tags):
        """`(args, cwd) -> (rc, stdout)` -- `Repo`'s injected seam, answering only what the exemption
        path asks: whether a tag exists, and the diff between two of them."""
        def git(args, cwd):
            if args[0] == "tag" and args[1] == "-l":
                return (0, args[2] + "\n") if args[2] in tags else (0, "")
            if args[0] == "diff" and args[1] == "--name-only":
                return (0, "\n".join(changed))
            if args[0] == "show":
                return (0, "")
            raise AssertionError(f"DryRunCase's fake git received an unexpected call: {args}")
        return git

    def _ctx(self, changed, tags, parsed, out, err):
        from fleet.cli import Ctx
        from fleet.harvest import Harvest
        from fleet.pool import Pool
        from fleet.session import Probes, SessionLayer
        from fleet.store import Store
        home = self.tmp / "home"
        sessions = SessionLayer(Probes(list_processes=lambda: [], capture_pane=lambda name: "",
                                       has_session=lambda name: False,
                                       start_session=lambda name, cwd, cmd: None,
                                       kill_session=lambda name: None))
        return Ctx(home=home, instants_dir=home / "instants", store=Store(home),
                   pool=Pool(home, cwd_probe=lambda path: [], alive=sessions.alive),
                   sessions=sessions, harvest=Harvest(home), out=out, err=err,
                   dry_run=parsed.on("dry-run"), porcelain=parsed.on("porcelain"),
                   git=self._fake_git(changed, tags), runner=None, live_work=False)

    def _run(self, changed, tags=("fleet/v0.1.0", "fleet/v0.1.1"), repo_flag=True):
        """Drive `release-verify --dry-run` through the real `main`. Returns `(code, stdout, stderr)`.

        `repo_flag=False` omits `--repo` entirely, and the target release's MANIFEST (built in `setUp`)
        never records `source_repo` either -- so `Verify.repo()` has nothing to resolve, the same state
        a release cut before that field existed is in.
        """
        import io

        from fleet.cli import main
        argv = ["release-verify", "--dry-run", "--porcelain", "--version", "0.1.1",
                "--releases", str(self.rel.root)]
        if repo_flag:
            argv += ["--repo", str(self.repo_path)]
        out, err = io.StringIO(), io.StringIO()
        code = main(argv, stdout=out, stderr=err,
                    context=lambda parsed, o, e: self._ctx(changed, tags, parsed, o, e))
        return code, out.getvalue(), err.getvalue()

    def verify_dry_run(self, changed, tags=("fleet/v0.1.0", "fleet/v0.1.1")):
        """Like `_run`, but for the two ordinary cases: asserts the run exited clean and returns its
        porcelain rows as `(field, value)` tuples."""
        code, out, err = self._run(changed, tags)
        self.assertEqual(code, 0, err)
        return [tuple(line.split("\t", 1)) for line in out.splitlines()]

    def test_dry_run_names_the_paths_that_force_the_suites(self):
        """The dry run's only job is to report the decision, and `would-run the gate roster` prints
        identically for an exempt release -- which is how a skills-only 0.5.11 cost a 45-minute run
        before anyone learned it was `.hermes-plugin/plugin.yaml` that forced it."""
        out = self.verify_dry_run(changed=["fleet/src/fleet/cli.py", "docs/x.md"])
        self.assertIn(("would-run", "the gate roster"), out)
        self.assertIn(("requiring", "fleet/src/fleet/cli.py"), out)
        self.assertNotIn(("requiring", "docs/x.md"), out)

    def test_dry_run_names_the_anchor_when_it_would_exempt(self):
        out = self.verify_dry_run(changed=["docs/x.md"])
        self.assertIn(("would-exempt", str(self.anchor)), out)
        self.assertNotIn(("would-run", "the gate roster"), out)

    def test_dry_run_propagates_refused_when_the_anchor_tag_is_missing(self):
        """The failure a dry run must never swallow: `exemption_for`'s `Refused` when the anchor's tag is
        gone from the checkout. A dry run that answered exit 0 here would report a release as verifiable
        when the question of whether it may skip the suites could not even be asked -- see
        `test_a_missing_anchor_tag_is_refused_not_treated_as_no_change` above, the non-dry-run half of the
        same guarantee."""
        code, out, err = self._run(changed=["docs/x.md"], tags=("fleet/v0.1.1",))    # anchor tag absent
        self.assertEqual(code, self.REFUSED)
        self.assertEqual(out, "", "a refused dry run must print nothing, not a fabricated decision")
        self.assertIn("fleet/v0.1.0", err)

    def test_dry_run_reports_a_refusal_instead_of_a_fabricated_would_run(self):
        """The narrower repeat of this task's own bug. With no `--repo` and no `source_repo` in the
        MANIFEST, `Verify.repo()` refuses -- there is not even a repository to diff, so the exemption
        question cannot be asked any more than the anchor-tag case can. But this refusal is caught (dry
        run only) so the `RI-32`/`OBS-70` invariant holds; the risk is that the caught refusal reads as an
        ordinary, computed `would-run` -- textually identical to a release for which the roster really
        was determined necessary. It must not: the real run refuses at this exact point before ever
        reaching the roster (`test_a_real_run_refuses_before_spawning_anything_when_no_repo_is_known`
        proves the other half), so a dry run that said `would-run` here would be reporting a decision
        nobody made."""
        code, out, err = self._run(changed=["docs/x.md"], repo_flag=False)
        self.assertEqual(code, 0, err)
        rows = [tuple(line.split("\t", 1)) for line in out.splitlines()]
        self.assertNotIn(("would-run", "the gate roster"), rows,
                         "a dry run must never print the same would-run line for a genuinely-determined "
                         "roster and for a question it could not ask at all")
        refusals = [value for field, value in rows if field == "would-refuse"]
        self.assertEqual(len(refusals), 1, rows)
        self.assertIn("does not record the checkout", refusals[0])

    def test_a_real_run_refuses_before_spawning_anything_when_no_repo_is_known(self):
        """The other half of the case above: the REAL run must still fail fast, uncaught, before
        `Verify.run()` ever spawns the hermetic suite -- swallowing `Verify.repo()`'s refusal is a
        dry-run-only affordance, never a real-run one."""
        code, out, err = self._run(changed=["docs/x.md"], repo_flag=False)     # dry run, for the fixture
        self.assertEqual(code, 0)                                             # sanity: dry run is clean
        import io

        from fleet.cli import main
        out2, err2 = io.StringIO(), io.StringIO()
        code2 = main(["release-verify", "--porcelain", "--version", "0.1.1",
                     "--releases", str(self.rel.root)],
                    stdout=out2, stderr=err2,
                    context=lambda parsed, o, e: self._ctx(["docs/x.md"], (), parsed, o, e))
        self.assertEqual(code2, self.REFUSED)
        self.assertIn("does not record the checkout", err2.getvalue())


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
