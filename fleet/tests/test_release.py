"""The release model: versions, layout, the history register, and the atomic flip."""
import os
import pathlib
import tempfile
import unittest

from fleet.release import (CANDIDATE, DEV, HISTORY_COLUMNS, RELEASED, Releases,
                           Version, tree_sha)
from fleet.errors import BadInput


class VersionCase(unittest.TestCase):
    def test_parse_and_render_round_trip(self):
        self.assertEqual(str(Version.parse("0.3.0")), "0.3.0")
        self.assertEqual(Version.parse("1.12.5"), Version(1, 12, 5))

    def test_a_malformed_version_is_bad_input(self):
        for bad in ("v0.3.0", "0.3", "0.3.0.1", "0.3.x", "", "latest"):
            with self.assertRaises(BadInput, msg=bad):
                Version.parse(bad)

    def test_ordering_is_numeric_not_lexical(self):
        # The bug this forbids: "0.10.0" < "0.9.0" under string sort, so `previous()` would pick the
        # wrong predecessor and the changelog would cover the wrong range.
        self.assertLess(Version.parse("0.9.0"), Version.parse("0.10.0"))
        self.assertEqual(max([Version.parse("0.9.0"), Version.parse("0.10.0")]), Version(0, 10, 0))

    def test_bump_kind_classifies_against_the_predecessor(self):
        prev = Version.parse("1.2.3")
        self.assertEqual(Version.parse("1.2.4").bump_kind(prev), "patch")
        self.assertEqual(Version.parse("1.3.0").bump_kind(prev), "minor")
        self.assertEqual(Version.parse("2.0.0").bump_kind(prev), "major")


class ReleasesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.rel = Releases(self.tmp / "releases")

    def _make(self, ver, state=CANDIDATE):
        v = Version.parse(ver)
        d = self.rel.dir_for(v)
        (d / ".release").mkdir(parents=True, exist_ok=True)
        self.rel.write_manifest(v, {"version": ver, "tag": f"fleet/v{ver}"})
        self.rel.set_state(v, state)
        return v

    def test_versions_are_discovered_and_ordered(self):
        self._make("0.9.0")
        self._make("0.10.0")
        self.assertEqual([str(v) for v in self.rel.versions()], ["0.9.0", "0.10.0"])

    def test_previous_is_the_highest_below_not_the_newest_directory(self):
        self._make("0.10.0")
        self._make("0.9.0")            # created LATER, lower version
        self.assertEqual(str(self.rel.previous(Version.parse("0.11.0"))), "0.10.0")

    def test_previous_of_the_first_release_is_none(self):
        v = self._make("0.1.0")
        self.assertIsNone(self.rel.previous(v))

    def test_manifest_round_trips_as_tab_separated_pairs(self):
        v = self._make("0.1.0")
        self.rel.write_manifest(v, {"version": "0.1.0", "notes": "first cut"})
        self.assertEqual(self.rel.manifest(v)["notes"], "first cut")
        raw = (self.rel.dir_for(v) / ".release" / "MANIFEST.tsv").read_text()
        self.assertIn("notes\tfirst cut", raw)

    def test_state_defaults_to_candidate_and_is_writable(self):
        v = self._make("0.1.0")
        self.assertEqual(self.rel.state(v), CANDIDATE)
        self.rel.set_state(v, RELEASED)
        self.assertEqual(self.rel.state(v), RELEASED)

    def test_current_label_reports_the_version_the_symlink_points_at(self):
        v = self._make("0.1.0")
        self.rel.point_current_at(self.rel.dir_for(v))
        self.assertEqual(self.rel.current_label(), "0.1.0")

    def test_current_label_says_DEV_when_it_points_outside_the_releases_root(self):
        checkout = self.tmp / "checkout"
        checkout.mkdir()
        self.rel.point_current_at(checkout)
        self.assertEqual(self.rel.current_label(), DEV)

    def test_current_label_is_none_when_nothing_is_deployed(self):
        self.rel.root.mkdir(parents=True, exist_ok=True)
        self.assertEqual(self.rel.current_label(), "none")

    def test_the_flip_never_leaves_current_absent(self):
        # The property, asserted the only way it can be: `current` must resolve at every instant, so a
        # reader interleaved with the flip sees the old target or the new one and never a missing path.
        #
        # The observer runs in ANOTHER THREAD, and that is the whole test. Sampling `current` after each
        # flip RETURNS -- which is how this case was first written -- passes for `unlink`-then-`symlink`
        # too, because by the time the call returns the link is back. The absent window exists only
        # *during* the flip, so nothing that looks between flips can ever see it, and a case that cannot
        # fail is not evidence (P-C).
        #
        # Measured both ways before trusting it: against `unlink`-then-`symlink`, 20 runs out of 20 saw
        # the gap, 13k-590k sightings per run. Against the `os.replace` flip, zero sightings in 20 runs.
        import threading
        a, b = self._make("0.1.0"), self._make("0.2.0")
        link = self.rel.root / "current"
        self.rel.point_current_at(self.rel.dir_for(a))
        stop = threading.Event()
        absent = []

        def watch():
            while not stop.is_set():
                if not link.exists():
                    absent.append(1)        # list.append is atomic under the GIL; this is just a counter

        reader = threading.Thread(target=watch)
        reader.start()
        try:
            for _ in range(200):
                self.rel.point_current_at(self.rel.dir_for(b))
                self.rel.point_current_at(self.rel.dir_for(a))
        finally:
            stop.set()
            reader.join()
        self.assertEqual(len(absent), 0,
                         f"current vanished during a flip: a concurrent reader saw it missing "
                         f"{len(absent)} times, and every davis_root shell's PATH resolves through it")

    def test_history_appends_a_well_formed_row_with_a_header(self):
        self.rel.append_history(action="DEPLOY", version="0.1.0", from_version="DEV",
                                actor="davis@onehouse.ai", host="box", reason="first", evidence="-")
        text = (self.rel.root / "RELEASE-HISTORY.tsv").read_text()
        self.assertTrue(text.startswith("\t".join(HISTORY_COLUMNS)))
        rows = self.rel.history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "DEPLOY")
        self.assertEqual(rows[0]["from_version"], "DEV")

    def test_a_reason_containing_a_tab_or_newline_cannot_break_the_register(self):
        # A free-text reason is operator input. One stray tab would shift every later column, and the
        # corruption is silent -- the file still parses, into the wrong fields.
        self.rel.append_history(action="ROLLBACK", version="0.1.0", from_version="0.2.0",
                                actor="a", host="b", reason="broke\ton\nharvest", evidence="-")
        rows = self.rel.history()
        self.assertEqual(len(rows), 1)
        self.assertNotIn("\t", rows[0]["reason"])
        self.assertIn("broke", rows[0]["reason"])

    def test_concurrent_appends_produce_two_whole_rows(self):
        import threading
        threads = [threading.Thread(target=self.rel.append_history, kwargs=dict(
            action="DEPLOY", version=f"0.0.{i}", from_version="-", actor="a", host="b",
            reason=f"r{i}", evidence="-")) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        rows = self.rel.history()
        self.assertEqual(len(rows), 8)
        self.assertEqual(len({r["version"] for r in rows}), 8)

    def test_tree_sha_is_stable_across_a_copy_and_ignores_the_release_dir(self):
        import shutil
        src = self.tmp / "exp"
        (src / "bin").mkdir(parents=True)
        (src / "bin" / "fleet").write_text("#!/bin/sh\n")
        (src / ".release").mkdir()
        (src / ".release" / "STATE").write_text(CANDIDATE)
        dst = self.tmp / "copy"
        shutil.copytree(src, dst)
        (dst / ".release" / "STATE").write_text(RELEASED)     # metadata differs, payload does not
        self.assertEqual(tree_sha(src), tree_sha(dst))

    def test_tree_sha_changes_when_a_payload_file_changes(self):
        # Without this the previous test passes for a tree_sha that returns a constant.
        src = self.tmp / "exp2"
        (src / "bin").mkdir(parents=True)
        (src / "bin" / "fleet").write_text("#!/bin/sh\n")
        before = tree_sha(src)
        (src / "bin" / "fleet").write_text("#!/bin/sh\necho hi\n")
        self.assertNotEqual(before, tree_sha(src))

    def test_tree_sha_notices_a_mode_change(self):
        src = self.tmp / "exp3"
        src.mkdir()
        f = src / "run.sh"
        f.write_text("x")
        before = tree_sha(src)
        f.chmod(0o755)
        self.assertNotEqual(before, tree_sha(src),
                            "an executable bit is part of the artifact; a launcher that lost +x is broken")


class GitCase(unittest.TestCase):
    """Against a real temporary repository. `git` is the thing under test here -- mocking it would assert
    that this module can spell the flags it was written with, which is not a property anyone needs."""

    def setUp(self):
        import shutil
        import subprocess
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.run = lambda *a: subprocess.run(["git", "-C", str(self.repo), *a], check=True,
                                             capture_output=True, text=True)
        self.run("init", "-q", "-b", "live")
        self.run("config", "user.email", "t@example.com")
        self.run("config", "user.name", "T")
        self.run("config", "commit.gpgsign", "false")

    def _commit(self, name, body="x"):
        (self.repo / name).write_text(body)
        self.run("add", name)
        self.run("commit", "-q", "-m", f"add {name}")
        return self.run("rev-parse", "HEAD").stdout.strip()

    def test_a_dirty_tree_is_reported_with_the_offending_paths(self):
        from fleet.release_git import Repo
        self._commit("a.txt")
        self.assertEqual(Repo(self.repo).dirty(), [])
        (self.repo / "a.txt").write_text("changed")
        self.assertTrue(any("a.txt" in p for p in Repo(self.repo).dirty()))

    def test_an_untracked_file_counts_as_dirty(self):
        # An export contains only committed content, so an untracked file is content the operator can see
        # and the artifact cannot. Silently excluding it is how you ship a version nobody can reproduce.
        from fleet.release_git import Repo
        self._commit("a.txt")
        (self.repo / "new.txt").write_text("hi")
        self.assertTrue(any("new.txt" in p for p in Repo(self.repo).dirty()))

    def test_a_directory_that_is_not_a_repository_is_refused_by_name(self):
        # The repo is a required flag on every git-touching verb precisely so this can be answered at the
        # edge. A Repo built over a non-repository must say so, not fail later inside a tag.
        from fleet.release_git import Repo
        with self.assertRaises(BadInput) as caught:
            Repo(self.tmp / "not-a-repo")
        self.assertIn("not a git repository", str(caught.exception))

    def test_head_and_branch_report_the_checkout(self):
        from fleet.release_git import Repo
        sha = self._commit("a.txt")
        self.assertEqual(Repo(self.repo).head(), sha)
        self.assertEqual(Repo(self.repo).branch(), "live")

    def test_a_release_tag_is_never_moved(self):
        from fleet.errors import Refused
        from fleet.release_git import Repo
        self._commit("a.txt")
        repo = Repo(self.repo)
        self.assertFalse(repo.tag_exists("fleet/v0.1.0"))
        repo.annotated_tag("fleet/v0.1.0", "r1")
        self.assertTrue(repo.tag_exists("fleet/v0.1.0"))
        self._commit("b.txt")
        with self.assertRaises(Refused):
            repo.annotated_tag("fleet/v0.1.0", "r1 again")
        # And it still names the tree it named before, which is the whole point of refusing.
        self.assertEqual(self.run("rev-list", "-n1", "fleet/v0.1.0").stdout.strip(),
                         self.run("rev-list", "-n1", "HEAD~1").stdout.strip())

    def test_the_upstream_base_is_the_nearest_non_fleet_tag(self):
        from fleet.release_git import Repo
        self._commit("a.txt")
        self.assertEqual(Repo(self.repo).upstream_base(), "(none)")
        self.run("tag", "-a", "v6.2.0", "-m", "upstream")
        self._commit("b.txt")
        self.run("tag", "-a", "fleet/v0.1.0", "-m", "r1")
        self.assertEqual(Repo(self.repo).upstream_base(), "v6.2.0")

    def test_the_first_release_has_no_predecessor_and_no_commit_list(self):
        from fleet.release_git import Repo
        self._commit("a.txt")
        self.assertEqual(Repo(self.repo).delta(None), [])

    def test_delta_lists_only_commits_after_the_previous_tag(self):
        from fleet.release_git import Repo
        self._commit("a.txt")
        self.run("tag", "-a", "fleet/v0.1.0", "-m", "r1")
        self._commit("b.txt")
        self._commit("c.txt")
        subjects = [s for _, s in Repo(self.repo).delta("fleet/v0.1.0")]
        self.assertEqual(sorted(subjects), ["add b.txt", "add c.txt"])

    def test_delta_survives_a_rebase_that_rewrites_every_hash(self):
        # THE case. `git log prev..HEAD` is wrong here in a way that is not empty and not obviously wrong,
        # which is why it has to be measured rather than reasoned about.
        #
        # The fixture matters more than the assertion. The plan's version branched `upstream` FROM
        # `fleet/v0.1.0`, which leaves the tagged commit in HEAD's history after the rebase -- the tag is
        # still an ancestor, nothing was rewritten off the branch, and `cherry` and `log` return the same
        # three commits. Measured: `merge-base --is-ancestor` said TRUE, so the guard below failed and the
        # delta comparison was never reached. `upstream` has to fork from BEFORE the tagged commit, the
        # way the real fork does -- our commits sit on top of an upstream release, and the 03:30 cron
        # replays them onto the next one.
        from fleet.release_git import Repo
        self._commit("base.txt")                    # the upstream release both lines share
        self.run("branch", "upstream")
        self._commit("a.txt")                       # ours, and shipped in v0.1.0
        self.run("tag", "-a", "fleet/v0.1.0", "-m", "r1")
        self._commit("b.txt")
        self._commit("c.txt")
        before = sorted(s for _, s in Repo(self.repo).delta("fleet/v0.1.0"))
        self.assertEqual(before, ["add b.txt", "add c.txt"])

        # An upstream release lands under our commits and `live` is rebased onto it, exactly as sync.sh
        # does. Every commit of ours -- including the one the tag points at -- is rewritten.
        self.run("checkout", "-q", "upstream")
        self._commit("upstream.txt")
        self.run("checkout", "-q", "live")
        self.run("rebase", "-q", "upstream")

        self.assertFalse(Repo(self.repo).is_ancestor("fleet/v0.1.0", "HEAD"),
                         "fixture is wrong: the rebase must have moved the tag off the branch")
        after = sorted(s for _, s in Repo(self.repo).delta("fleet/v0.1.0"))
        # The defect, stated as the thing that must not happen: `add a.txt` shipped in v0.1.0, its hash
        # was rewritten, and an ancestry delta re-lists it in v0.2.0's changelog. A patch-id delta does
        # not, because a rebase preserves the patch-id.
        self.assertNotIn("add a.txt", after,
                         "a commit already shipped in fleet/v0.1.0 reappeared in the next delta after "
                         "its hash was rewritten -- this is the ancestry answer, not the patch-id one")
        # And nothing our side lost or gained: the two unreleased commits, plus the upstream commit the
        # rebase genuinely brought under us, which IS new between the two releases.
        self.assertEqual(after, sorted(before + ["add upstream.txt"]),
                         "the patch-id delta must carry exactly the unreleased commits, whatever the "
                         "rebase did to their hashes")

    def test_the_changelog_names_the_rebase_when_the_tag_left_the_branch(self):
        from fleet.release_git import changelog_section
        text = changelog_section(Version.parse("0.2.0"), head="abc1234", branch="live",
                                 upstream_base="v6.2.0", prev_tag="fleet/v0.1.0",
                                 commits=[("deadbee", "did a thing")], rebased=True,
                                 when="2026-08-02T00:00:00Z")
        self.assertIn("patch-id", text)
        self.assertIn("no longer an ancestor", text)
        self.assertIn("- deadbee did a thing", text)

    def test_the_changelog_stays_quiet_about_a_rebase_that_did_not_happen(self):
        # Without this the note above could be unconditional, which would make every changelog claim a
        # rewrite and the claim would stop meaning anything.
        from fleet.release_git import changelog_section
        text = changelog_section(Version.parse("0.2.0"), head="abc1234", branch="live",
                                 upstream_base="v6.2.0", prev_tag="fleet/v0.1.0",
                                 commits=[("deadbee", "did a thing")], rebased=False,
                                 when="2026-08-02T00:00:00Z")
        self.assertNotIn("no longer an ancestor", text)
        self.assertIn("- deadbee did a thing", text)
        self.assertIn("1 commit(s) since fleet/v0.1.0", text)

    def test_the_changelog_of_a_first_release_records_the_commit_and_omits_the_list(self):
        from fleet.release_git import changelog_section
        text = changelog_section(Version.parse("0.1.0"), head="abc1234", branch="live",
                                 upstream_base="v6.2.0", prev_tag=None, commits=[], rebased=False,
                                 when="2026-08-02T00:00:00Z")
        self.assertIn("abc1234", text)
        self.assertIn("no predecessor", text)
        self.assertNotIn("\n- ", text)

    def test_export_writes_committed_content_only(self):
        from fleet.release_git import Repo
        self._commit("a.txt", "committed")
        self.run("tag", "-a", "fleet/v0.1.0", "-m", "r1")
        (self.repo / "untracked.txt").write_text("must not ship")
        dest = self.tmp / "out"
        Repo(self.repo).export("fleet/v0.1.0", dest)
        self.assertEqual((dest / "a.txt").read_text(), "committed")
        self.assertFalse((dest / "untracked.txt").exists())

    def test_export_carries_the_tagged_tree_not_the_working_tree(self):
        # An export named by tag must be the tag's bytes even when the branch has moved on, or a promoted
        # release would not be the thing that was verified.
        from fleet.release_git import Repo
        self._commit("a.txt", "at the tag")
        self.run("tag", "-a", "fleet/v0.1.0", "-m", "r1")
        (self.repo / "a.txt").write_text("after the tag")
        self.run("add", "a.txt")
        self.run("commit", "-q", "-m", "move on")
        dest = self.tmp / "out2"
        Repo(self.repo).export("fleet/v0.1.0", dest)
        self.assertEqual((dest / "a.txt").read_text(), "at the tag")

    def test_export_preserves_the_executable_bit(self):
        # `tree_sha` hashes the mode, and `bin/fleet` is only a launcher while it is +x. An extraction
        # that flattens modes ships a release nobody can run.
        from fleet.release_git import Repo
        (self.repo / "run.sh").write_text("#!/bin/sh\n")
        (self.repo / "run.sh").chmod(0o755)
        self.run("add", "run.sh")
        self.run("commit", "-q", "-m", "add run.sh")
        self.run("tag", "-a", "fleet/v0.1.0", "-m", "r1")
        dest = self.tmp / "out3"
        Repo(self.repo).export("fleet/v0.1.0", dest)
        self.assertTrue(os.access(dest / "run.sh", os.X_OK))

    def test_a_failing_git_command_names_the_command_and_the_repository(self):
        # The injected runner hands back `(rc, stdout)` and no stderr, so the refusal has to be
        # actionable on its own: it names what was run and where, which the operator can re-run.
        from fleet.release_git import Repo
        self._commit("a.txt")
        with self.assertRaises(BadInput) as caught:
            Repo(self.repo).delta("fleet/v9.9.9")
        message = str(caught.exception)
        self.assertIn("cherry", message)
        self.assertIn(str(self.repo), message)


class VerifyCase(unittest.TestCase):
    """`verify`, driven end to end by a FAKE runner.

    Nothing here executes a suite. The real thing spawns an 11-runner IT roster; a unit test that waited
    for it would take minutes and would be measuring `run-all.sh`, not this module. The runner is INJECTED
    and REQUIRED (`Verify(releases, version, runner)`), so the seam that would otherwise be a fourth
    `subprocess` call site in the package is the same seam every handler already gets from `ctx.runner` --
    `(command, cwd, env) -> (rc, stdout, stderr)`.

    Two cases below observe the run FROM INSIDE the runner rather than from the end state. That is
    deliberate: the copy `verify` tests in is deleted before `run` returns, so anything sampling afterwards
    cannot tell a run that used the copy from a run that used the export, and would pass against the very
    defect it names. Both were measured against a deliberately broken implementation before being trusted.
    """

    class Runner:
        """`(command, cwd, env) -> (rc, stdout, stderr)`, recording every call as it happens.

        `codes` is `[(needle, rc)]`: the first needle found in the command decides the exit code, so a
        case can fail one suite and pass the other without knowing how either is spelled.
        """

        def __init__(self, codes=(), watcher=None):
            self.calls = []
            self.codes = list(codes)
            self.watcher = watcher

        def __call__(self, command, cwd=None, env=None):
            command = str(command)
            where = None if cwd is None else str(cwd)
            self.calls.append((command, where, dict(env or {})))
            if self.watcher is not None:
                self.watcher(command, where)
            for needle, code in self.codes:
                if needle in command:
                    return code, f"stdout of {needle}", f"stderr of {needle}"
            return 0, "stdout", ""

        def commands(self):
            return [command for command, _, _ in self.calls]

        def call_matching(self, needle):
            for call in self.calls:
                if needle in call[0]:
                    return call
            raise AssertionError(f"the runner was never handed a command containing {needle!r}; it saw "
                                 f"{self.commands()}")

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-verifycase-"))
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)

    # --- fixtures ------------------------------------------------------------------------------------

    def _export(self, version="0.1.0", recorded_sha=None):
        """A release directory shaped like a real export, with a MANIFEST that agrees with it."""
        from fleet.release import META_DIR, Releases, Version, tree_sha
        rel = Releases(self.tmp / "releases")
        v = Version.parse(version)
        root = rel.dir_for(v)
        (root / "fleet" / "it").mkdir(parents=True)
        (root / "fleet" / "tests").mkdir(parents=True)
        (root / "fleet" / "src" / "fleet").mkdir(parents=True)
        (root / "fleet" / "it" / "run-all.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
        (root / "fleet" / "src" / "fleet" / "__init__.py").write_text('__version__ = "0.1.0"\n')
        (root / META_DIR).mkdir(parents=True)
        rel.write_manifest(v, {"version": version, "tree_sha": recorded_sha or tree_sha(root)})
        return rel, v

    def _freeze(self, root):
        """`chmod -R a-w`, which is what a cut leaves behind. Restored on teardown so the temp tree can
        be removed -- and so a failure here does not litter /tmp with unreadable directories."""
        paths = [root] + sorted(p for p in root.rglob("*") if not p.is_symlink())
        def thaw():
            for path in paths:
                if path.exists():
                    path.chmod(path.stat().st_mode | 0o700)
        self.addCleanup(thaw)
        for path in reversed(paths):
            path.chmod(path.stat().st_mode & ~0o222)

    @staticmethod
    def _emit_results(command, where):
        """Stand in for `run-all.sh`: write the merged results file beside itself, which is the whole
        reason the suite cannot run inside a read-only export."""
        if "run-all.sh" in command and where:
            out = pathlib.Path(where) / "fleet" / "it" / "RESULTS-closeout-all.tsv"
            out.write_text("section\tid\tverdict\nQ\tQ1\tPASS\n")

    def _copies_under(self, rel):
        """Every directory in the releases root that is not a release. `verify`'s working copy lives
        here, so this is how a case sees whether one was left behind."""
        return sorted(p.name for p in rel.root.iterdir()
                      if p.is_dir() and not p.name.startswith("fleet-v"))

    # --- the verdict rule, which is a pure function --------------------------------------------------

    def test_green_only_when_both_suites_pass(self):
        from fleet.release_verify import GREEN, verdict_for
        self.assertEqual(verdict_for(True, True, False), GREEN)

    def test_a_failure_on_a_quiet_box_is_red(self):
        from fleet.release_verify import RED, verdict_for
        self.assertEqual(verdict_for(False, True, False), RED)
        self.assertEqual(verdict_for(True, False, False), RED)

    def test_a_failure_while_the_box_was_busy_is_inconclusive_not_red(self):
        # Contamination is never a verdict. This is the source-pin doctrine applied to the one baseline
        # the suite cannot own, and it is what stops a coordinator finishing mid-run from writing a
        # permanent false RED into a release's evidence.
        from fleet.release_verify import INCONCLUSIVE, verdict_for
        self.assertEqual(verdict_for(False, True, True), INCONCLUSIVE)
        self.assertEqual(verdict_for(True, False, True), INCONCLUSIVE)

    def test_activity_during_a_passing_run_is_still_green(self):
        # Without this, INCONCLUSIVE would swallow every busy-box run and nothing could ever promote.
        from fleet.release_verify import GREEN, verdict_for
        self.assertEqual(verdict_for(True, True, True), GREEN)

    # --- the verdict file ----------------------------------------------------------------------------

    def test_the_verdict_file_records_the_roster_that_actually_ran(self):
        from fleet.release_verify import GATE_ROSTER, read_verdict, write_verdict
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        write_verdict(tmp, [("hermetic", "GREEN", "hermetic.log", "927 tests"),
                            ("it", "GREEN", "it-RESULTS.tsv", "11 runners")], GATE_ROSTER)
        got = read_verdict(tmp)
        self.assertEqual(got["roster"], GATE_ROSTER)
        self.assertEqual(got["suites"]["hermetic"], "GREEN")
        self.assertEqual(got["suites"]["it"], "GREEN")

    def test_the_two_rosters_are_told_apart_in_the_file(self):
        # Without this, `roster` could be a constant and a gate-roster verdict would read as full
        # coverage -- a scope that narrowed in silence, which reads as a pass (OBS-49).
        from fleet.release_verify import FULL_ROSTER, GATE_ROSTER, read_verdict, write_verdict
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        write_verdict(tmp, [("it", "GREEN", "it-RESULTS.tsv", "-")], FULL_ROSTER)
        self.assertEqual(read_verdict(tmp)["roster"], FULL_ROSTER)
        self.assertNotEqual(FULL_ROSTER, GATE_ROSTER)

    def test_a_missing_verdict_file_reads_as_empty_rather_than_raising(self):
        from fleet.release_verify import read_verdict
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        self.assertEqual(read_verdict(tmp), {})

    def test_a_note_containing_a_tab_cannot_shift_the_verdict_columns(self):
        # Same defect the history register was hardened against: the file still parses, into the wrong
        # fields. A note here quotes a suite's own output, which is not this module's to trust.
        from fleet.release_verify import GATE_ROSTER, read_verdict, write_verdict
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        write_verdict(tmp, [("hermetic", "RED", "hermetic.log", "exit 1\tFAILED\n(errors=2)")],
                      GATE_ROSTER)
        got = read_verdict(tmp)
        self.assertEqual(got["suites"]["hermetic"], "RED")
        self.assertEqual(got["roster"], GATE_ROSTER)

    # --- the runner is a required seam ---------------------------------------------------------------

    def test_the_runner_is_required_and_has_no_subprocess_default(self):
        # Correction 6 of the plan, asserted here as well as by test_cli's AST scan: a defaulted
        # `subprocess.run` in this module would be a FOURTH spawn seam in a package whose audit asserts
        # there are exactly three. Required means a caller must hand over `ctx.runner`, which is the one
        # the audit already allows.
        from fleet.release_verify import Verify
        rel, v = self._export()
        with self.assertRaises(TypeError):
            Verify(rel, v)

    # --- the copy, and the claim that what was tested is what shipped --------------------------------

    def test_verify_refuses_when_the_copy_does_not_match_the_manifest(self):
        # The claim "what was tested is what shipped" is ASSERTED, not assumed. If the copy diverges the
        # run is meaningless, and reporting RED would blame the code for a harness fault.
        from fleet.errors import Refused
        from fleet.release_verify import Verify
        rel, v = self._export(recorded_sha="0" * 64)          # deliberately wrong
        with self.assertRaises(Refused):
            Verify(rel, v, self.Runner()).check_copy_matches(rel.dir_for(v))

    def test_a_copy_that_does_match_the_manifest_is_accepted(self):
        # Without this the refusal above passes for a check_copy_matches that raises unconditionally.
        from fleet.release_verify import Verify
        rel, v = self._export()
        Verify(rel, v, self.Runner()).check_copy_matches(rel.dir_for(v))

    def test_the_it_suite_runs_in_a_writable_copy_and_never_in_the_export(self):
        # OBSERVED DURING THE RUN, from inside the runner, and that is the whole case. The copy is deleted
        # before `run` returns, so a case sampling the end state passes just as happily against an
        # implementation that ran the suite in the export itself -- plan correction 1's vacuity, exactly.
        #
        # Measured before being trusted: against an implementation handed `cwd=str(self.export)` this
        # case fails on the writability probe (the export is a-w) and on the prefix assertion; against
        # the copy it passes. The end-state cases in this class do NOT fail against that break.
        from fleet.release import tree_sha
        from fleet.release_verify import Verify
        rel, v = self._export()
        export = rel.dir_for(v)
        frozen = tree_sha(export)
        self._freeze(export)
        seen = []

        def watch(command, where):
            if "run-all.sh" not in command:
                return
            here = pathlib.Path(where)
            # Writable AT THIS INSTANT: `run-all.sh` writes RESULTS beside itself, and this is the one
            # moment at which that either works or does not.
            (here / "fleet" / "it" / "RESULTS-closeout-all.tsv").write_text("section\tid\tverdict\n")
            seen.append((command, str(here.resolve())))

        runner = self.Runner(watcher=watch)
        Verify(rel, v, runner).run()

        self.assertEqual(len(seen), 1, f"the IT suite ran {len(seen)} times, not once")
        command, where = seen[0]
        self.assertFalse(where.startswith(str(export.resolve())),
                         f"the IT suite ran at {where}, inside the read-only export {export} -- the "
                         f"suite writes RESULTS beside itself and would either fail or mutate the "
                         f"artifact it is supposed to be measuring")
        self.assertNotIn(str(export), command,
                         f"the IT runner invoked was the export's own script: {command}")
        self.assertEqual(tree_sha(export), frozen,
                         "the export's payload changed during its own verification")

    def test_the_working_copy_is_gone_when_the_run_ends(self):
        from fleet.release_verify import Verify
        rel, v = self._export()
        Verify(rel, v, self.Runner(watcher=self._emit_results)).run()
        self.assertEqual(self._copies_under(rel), [],
                         "a full copy of the release was left in the releases root: at ~5 MB an export "
                         "and one copy per verified version, this is how a releases root fills a disk")

    def test_the_working_copy_is_gone_even_when_the_run_refuses(self):
        # The plan's own code leaks here: `check_copy_matches` raises AFTER the copytree and the only
        # rmtree is on the line below, so the failure path -- the one that fires when something is
        # actually wrong -- is the path that leaves the copy behind.
        from fleet.errors import Refused
        from fleet.release_verify import Verify
        rel, v = self._export(recorded_sha="0" * 64)
        with self.assertRaises(Refused):
            Verify(rel, v, self.Runner()).run()
        self.assertEqual(self._copies_under(rel), [],
                         "the refusal path left its working copy behind")

    def test_two_verifies_of_one_version_do_not_share_a_working_copy_name(self):
        # FI-20's shape: a staging path that is a function of the target alone is shared by every writer
        # of that target. The plan named the copy `.verify-<version>`, which two concurrent verifies of
        # one release collide on -- one deletes the tree the other is testing in.
        from fleet.release_verify import Verify
        rel, v = self._export()
        names = []
        runner = self.Runner(watcher=lambda command, where: (
            names.append(where) if "run-all.sh" in command else None))
        Verify(rel, v, runner).run()
        Verify(rel, v, runner).run()
        self.assertEqual(len(names), 2)
        self.assertNotEqual(names[0], names[1],
                            f"both runs used the working copy {names[0]}, which is a staging path "
                            f"derived from the target alone -- FI-20 with a different receiver")

    # --- what the run actually drives ----------------------------------------------------------------

    def test_the_hermetic_suite_runs_against_the_export_with_bytecode_writing_off(self):
        from fleet.release_verify import Verify
        rel, v = self._export()
        export = rel.dir_for(v)
        runner = self.Runner(watcher=self._emit_results)
        Verify(rel, v, runner).run()
        command, where, env = runner.call_matching("unittest")
        self.assertIn("discover -s tests", command)
        self.assertEqual(where, str(export / "fleet"))
        self.assertEqual(env.get("PYTHONDONTWRITEBYTECODE"), "1",
                         "without this, unittest writes __pycache__ into a read-only artifact")
        self.assertEqual(env.get("PYTHONPATH"), str(export / "fleet" / "src"),
                         "the hermetic suite must import the EXPORT's fleet, not this checkout's")

    def test_the_it_run_does_not_inherit_this_checkouts_pythonpath(self):
        # The one contamination the copy does not prevent by itself: an inherited PYTHONPATH aimed at the
        # git checkout makes `import fleet` resolve to source nobody froze.
        from fleet.release_verify import Verify
        rel, v = self._export()
        runner = self.Runner(watcher=self._emit_results)
        Verify(rel, v, runner).run()
        _, where, env = runner.call_matching("run-all.sh")
        self.assertEqual(env.get("PYTHONPATH"), str(pathlib.Path(where) / "fleet" / "src"))

    def test_the_gate_roster_is_the_default_and_full_is_asked_for(self):
        from fleet.release_verify import FULL_ROSTER, GATE_ROSTER, Verify, read_verdict
        rel, v = self._export()
        gate = self.Runner(watcher=self._emit_results)
        Verify(rel, v, gate).run()
        self.assertNotIn("--full", gate.call_matching("run-all.sh")[0])
        self.assertEqual(read_verdict(rel.dir_for(v) / ".release")["roster"], GATE_ROSTER)

        full = self.Runner(watcher=self._emit_results)
        Verify(rel, v, full).run(full=True)
        self.assertIn("--full", full.call_matching("run-all.sh")[0])
        self.assertEqual(read_verdict(rel.dir_for(v) / ".release")["roster"], FULL_ROSTER)

    def test_a_green_run_writes_a_green_verdict_and_keeps_the_evidence(self):
        from fleet.release_verify import GREEN, Verify, read_verdict
        rel, v = self._export()
        export = rel.dir_for(v)
        self._freeze(export)
        self.assertEqual(Verify(rel, v, self.Runner(watcher=self._emit_results)).run(), GREEN)
        evidence = export / ".release" / "evidence"
        self.assertEqual(read_verdict(export / ".release")["suites"], {"hermetic": GREEN, "it": GREEN})
        self.assertTrue((evidence / "hermetic.log").is_file())
        self.assertTrue((evidence / "it-RESULTS.tsv").is_file(),
                        "the merged IT results were not copied out of the working copy before it was "
                        "deleted, so the verdict cites evidence that no longer exists")
        self.assertIn("Q1", (evidence / "it-RESULTS.tsv").read_text())

    def test_a_failing_it_suite_on_a_quiet_box_is_recorded_red(self):
        from fleet.release_verify import GREEN, RED, Verify, read_verdict
        rel, v = self._export()
        runner = self.Runner(codes=[("run-all.sh", 1)], watcher=self._emit_results)
        self.assertEqual(Verify(rel, v, runner).run(), RED)
        suites = read_verdict(rel.dir_for(v) / ".release")["suites"]
        self.assertEqual(suites, {"hermetic": GREEN, "it": RED})

    def test_a_failure_beside_a_changing_live_subject_set_is_recorded_inconclusive(self):
        # The live-subject set is sampled by running a command, so the fake runner is what makes it move.
        from fleet.release_verify import INCONCLUSIVE, Verify
        rel, v = self._export()
        board = []

        class Moving(self.Runner):
            def __call__(self, command, cwd=None, env=None):
                code, out, err = super().__call__(command, cwd, env)
                if "board" in command:
                    board.append(len(board))
                    return 0, f"subject-{len(board)}\n", ""
                return code, out, err

        self.assertEqual(Verify(rel, v, Moving(codes=[("run-all.sh", 1)],
                                               watcher=self._emit_results)).run(), INCONCLUSIVE)
        self.assertEqual(len(board), 2, "the live-subject set must be sampled before AND after the run")
