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
