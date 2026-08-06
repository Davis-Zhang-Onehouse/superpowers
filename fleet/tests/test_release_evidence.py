"""The evidence directory's LIFECYCLE: one directory, many attempts, nothing lost and nothing inherited.

`test_release.py`'s `VerifyCase` proves what ONE run writes. This file proves what happens when a release
is verified more than once, which is the ordinary case -- an `INCONCLUSIVE` verdict's whole purpose is to
ask for a re-run -- and which had no coverage at all.

Three measured artefacts are the reason it exists, all captured in the effort workspace
(`operations/tasks/metaOpt/fleetInfraOps/…-releasePipelineGaps/evidence/`):

  * `RI-9`  release 0.3.3 shipped RELEASED with residue from three attempts in one directory: an
    `it-cited/` file stamped 05:10, an `it-FAILURES.txt` stamped 05:37, a `VERDICT.tsv` stamped 06:07.
  * `RI-11` that same release's verdict says `0 FAIL rows` while the `it-FAILURES.txt` beside it names two
    failures -- because that file is written only on the failure path (`if failures:`) and cleared on
    neither. Every one of its 13 shipped per-runner registers has 0 FAIL rows, so the verdict is the true
    one and the manifest is the lie.
  * `RI-17` release 0.3.6, RELEASED and EXEMPT, ships a `hermetic.log` from an abandoned earlier attempt.
    The exempt path writes no such file: it bypasses `Verify` entirely and writes straight into the
    metadata directory. A fix that only touched `Verify` would have left this path destroying evidence.

The rule the cases below hold the pipeline to is one sentence: **an attempt writes into an empty directory,
and what was there before is still readable under a name that says which attempt it was.** RI-11 is then
not a second fix -- a run that starts empty cannot inherit a manifest that is no longer there.
"""
import pathlib
import shutil
import tempfile
import unittest

from fleet.release import META_DIR, Releases, Version
from fleet.release_verify import (EXEMPT, GATE_ROSTER, GREEN, INCONCLUSIVE, RED,
                                  archive_previous_attempt, read_verdict, write_verdict)


class ArchiveCase(unittest.TestCase):
    """`archive_previous_attempt` on its own: a pure directory operation over a real filesystem."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-archive-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.meta = self.tmp / META_DIR
        self.evidence = self.meta / "evidence"

    def _attempt(self, verdict=None, files=("hermetic.log", "it-RESULTS.tsv"), roster=GATE_ROSTER):
        """Write what one attempt leaves behind, optionally with a recorded verdict."""
        self.evidence.mkdir(parents=True, exist_ok=True)
        for name in files:
            (self.evidence / name).write_text(f"contents of {name}\n")
        if verdict is not None:
            write_verdict(self.meta, [("hermetic", GREEN, "e", "-"),
                                      ("it", GREEN if verdict == GREEN else RED, "e", "-")],
                          roster, result=verdict)

    def _attempt_dirs(self):
        return sorted(p.name for p in self.evidence.iterdir() if p.is_dir()
                      and p.name.startswith("attempt-"))

    def test_nothing_to_archive_when_the_release_has_never_been_verified(self):
        """The ordinary first run. No directory, nothing moved, and no empty `attempt-1-*` left behind to
        make a reader think an attempt happened."""
        self.assertIsNone(archive_previous_attempt(self.meta))
        self.assertFalse(self.evidence.exists() and any(self.evidence.iterdir()))

    def test_the_previous_attempt_is_moved_aside_whole(self):
        """`RI-9`. Every file of attempt 1 stays readable, together, under one name."""
        self._attempt(GREEN)
        archived = archive_previous_attempt(self.meta)
        self.assertIsNotNone(archived, "an existing attempt was not archived")
        self.assertEqual(self._attempt_dirs(), ["attempt-1-GREEN"])
        for name in ("hermetic.log", "it-RESULTS.tsv", "VERDICT.tsv"):
            self.assertTrue((archived / name).is_file(),
                            f"{name} did not survive the archive; {archived} holds "
                            f"{sorted(p.name for p in archived.iterdir())}")

    def test_the_directory_the_next_attempt_writes_into_is_empty(self):
        """The property the whole fix rests on, asserted directly rather than through a consequence."""
        self._attempt(GREEN, files=("hermetic.log", "it-FAILURES.txt", "it-cited-INDEX.txt"))
        archive_previous_attempt(self.meta)
        left = sorted(p.name for p in self.evidence.iterdir() if not p.name.startswith("attempt-"))
        self.assertEqual(left, [], f"the next attempt would start beside {left}")

    def test_a_nested_directory_of_cited_evidence_moves_with_it(self):
        """`it-cited/` is a tree, not a file. Release 0.3.3's held a file from an attempt TWO runs older
        than the verdict shipped beside it."""
        self._attempt(RED)
        cited = self.evidence / "it-cited" / "fleet" / "it" / "B" / "out"
        cited.mkdir(parents=True)
        (cited / "claude-count-after.txt").write_text("11\n")
        archived = archive_previous_attempt(self.meta)
        self.assertTrue((archived / "it-cited" / "fleet" / "it" / "B" / "out"
                         / "claude-count-after.txt").is_file())
        self.assertFalse((self.evidence / "it-cited").exists())

    def test_attempts_accumulate_and_are_numbered_in_order(self):
        """Three attempts, three directories. The number is what makes the sequence readable a month
        later; a bare `previous/` holds only the most recent one and silently drops the rest."""
        self._attempt(RED)
        archive_previous_attempt(self.meta)
        self._attempt(INCONCLUSIVE)
        archive_previous_attempt(self.meta)
        self._attempt(GREEN)
        archive_previous_attempt(self.meta)
        self.assertEqual(self._attempt_dirs(),
                         ["attempt-1-RED", "attempt-2-INCONCLUSIVE", "attempt-3-GREEN"])

    def test_an_already_archived_attempt_is_never_archived_again(self):
        """Archiving must not nest. Moving `attempt-1-RED/` inside `attempt-2-…/` would bury the first
        attempt one level deeper on every subsequent run."""
        self._attempt(RED)
        archive_previous_attempt(self.meta)
        self.assertIsNone(archive_previous_attempt(self.meta),
                          "a directory holding only archived attempts had something left to archive")
        self.assertEqual(self._attempt_dirs(), ["attempt-1-RED"])
        self.assertFalse((self.evidence / "attempt-1-RED" / "attempt-1-RED").exists())

    def test_an_attempt_with_no_recorded_verdict_is_archived_as_unknown(self):
        """A release cut before the verdict row existed, or a run that died before writing one. It is
        still archived -- `unknown` is a true statement about the artefact, and dropping the attempt to
        avoid an awkward name is the behaviour being fixed."""
        self._attempt(None)
        archive_previous_attempt(self.meta)
        self.assertEqual(self._attempt_dirs(), ["attempt-1-unknown"])

    def test_an_exempt_attempt_keeps_its_own_verdict_in_the_name(self):
        """`EXEMPT` is not a pass and must not archive as one -- the same distinction the verdict itself
        is careful about."""
        self._attempt(EXEMPT, files=("EXEMPTION.tsv",))
        archive_previous_attempt(self.meta)
        self.assertEqual(self._attempt_dirs(), ["attempt-1-EXEMPT"])


class OverallVerdictCase(unittest.TestCase):
    """`RI-16`. The run's overall verdict has to be IN the artefact, or an archive cannot name it.

    Release 0.3.4 is the measured instance: its `it` row reads RED with the note `live-subject set CHANGED
    during the run`, so `verdict_for(True, False, True)` -- INCONCLUSIVE -- is what the run returned, while
    the file records a verdict indistinguishable from a genuine RED.
    """

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-verdictrow-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.meta = self.tmp / META_DIR

    def test_the_overall_verdict_is_recorded_and_read_back(self):
        write_verdict(self.meta, [("hermetic", GREEN, "e", "-"), ("it", RED, "e", "-")],
                      GATE_ROSTER, result=INCONCLUSIVE)
        self.assertEqual(read_verdict(self.meta).get("result"), INCONCLUSIVE)

    def test_an_inconclusive_run_is_distinguishable_from_a_red_one(self):
        """The whole point. Two runs with identical suite rows, told apart by the file."""
        rows = [("hermetic", GREEN, "e", "-"), ("it", RED, "e", "-")]
        write_verdict(self.meta, rows, GATE_ROSTER, result=INCONCLUSIVE)
        inconclusive = (self.meta / "evidence" / "VERDICT.tsv").read_text()
        write_verdict(self.meta, rows, GATE_ROSTER, result=RED)
        self.assertNotEqual(inconclusive, (self.meta / "evidence" / "VERDICT.tsv").read_text())

    def test_the_verdict_row_is_not_mistaken_for_a_suite(self):
        """`promote` gates on `suites`. A key row leaking in would make it decide on a value that is not
        a suite's verdict -- the roster row has the same requirement and the same reason."""
        write_verdict(self.meta, [("hermetic", GREEN, "e", "-"), ("it", GREEN, "e", "-")],
                      GATE_ROSTER, result=GREEN)
        self.assertEqual(sorted(read_verdict(self.meta)["suites"]), ["hermetic", "it"])

    def test_a_release_cut_before_the_verdict_row_existed_reads_as_none(self):
        """Every release on this box today. Absent is not an error and must not be read as a verdict."""
        write_verdict(self.meta, [("hermetic", GREEN, "e", "-")], GATE_ROSTER)
        self.assertIsNone(read_verdict(self.meta).get("result"))
        self.assertEqual(read_verdict(self.meta)["suites"], {"hermetic": GREEN})


class ReverifyCase(unittest.TestCase):
    """The end-to-end claim, through `Verify.run` with a fake runner: verify twice, lose nothing, inherit
    nothing."""

    class Runner:
        def __init__(self, watcher=None, codes=()):
            self.calls, self.watcher, self.codes = [], watcher, list(codes)

        def __call__(self, command, cwd=None, env=None):
            command = str(command)
            self.calls.append((command, None if cwd is None else str(cwd)))
            if self.watcher is not None:
                self.watcher(command, None if cwd is None else str(cwd))
            for needle, code in self.codes:
                if needle in command:
                    return code, f"stdout of {needle}", ""
            return 0, "stdout", ""

    class FakeRepo:
        def __init__(self, source):
            self.source = pathlib.Path(source)

        def worktree_add(self, tag, dest):
            dest = pathlib.Path(dest)
            shutil.copytree(self.source, dest, symlinks=True)
            for path in [dest] + sorted(dest.rglob("*")):
                if not path.is_symlink():
                    path.chmod(path.stat().st_mode | 0o200)
            (dest / ".git").write_text("gitdir: /fake/.git/worktrees/scratch\n")
            return dest

        def worktree_remove(self, dest):
            shutil.rmtree(dest, ignore_errors=True)

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-reverify-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _export(self, version="0.1.0"):
        from fleet.release import tree_sha
        rel = Releases(self.tmp / "releases")
        v = Version.parse(version)
        root = rel.dir_for(v)
        (root / "fleet" / "it").mkdir(parents=True)
        (root / "fleet" / "src" / "fleet").mkdir(parents=True)
        (root / "fleet" / "it" / "run-all.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
        (root / "fleet" / "src" / "fleet" / "__init__.py").write_text('__version__ = "0.1.0"\n')
        (root / META_DIR).mkdir(parents=True)
        rel.write_manifest(v, {"version": version, "tag": f"fleet/v{version}",
                               "tree_sha": tree_sha(root)})
        return rel, v

    @staticmethod
    def _passing(command, where):
        if "run-all.sh" in command and where:
            it = pathlib.Path(where) / "fleet" / "it"
            (it / "RESULTS.tsv").write_text("case\tverdict\tevidence\tnote\nQ1\tPASS\tev\tnote\n")
            (it / "RESULTS-closeout-Q.tsv").write_text(
                "case\tverdict\tevidence\tnote\nQ1\tPASS\tev\tnote\n")

    @staticmethod
    def _failing(command, where):
        if "run-all.sh" in command and where:
            it = pathlib.Path(where) / "fleet" / "it"
            (it / "B" / "out").mkdir(parents=True, exist_ok=True)
            (it / "B" / "out" / "claude-count-after.txt").write_text("11\n")
            (it / "RESULTS.tsv").write_text("case\tverdict\tevidence\tnote\n")
            (it / "RESULTS-closeout-B.tsv").write_text(
                "case\tverdict\tevidence\tnote\n"
                "ISOLATION-B-claude-count\tFAIL\tit/B/out/claude-count-after.txt\tcount moved\n")

    def _evidence(self, rel, v):
        return rel.dir_for(v) / META_DIR / "evidence"

    def test_a_second_verify_preserves_the_first_attempts_verdict_and_artefacts(self):
        """`RI-9`, end to end. This is the case release 0.3.3 needed and did not have."""
        from fleet.release_verify import Verify
        rel, v = self._export()
        Verify(rel, v, self.Runner(watcher=self._failing), repo=self.FakeRepo(rel.dir_for(v))).run()
        first = (self._evidence(rel, v) / "VERDICT.tsv").read_text()

        Verify(rel, v, self.Runner(watcher=self._passing), repo=self.FakeRepo(rel.dir_for(v))).run()

        archived = sorted(p for p in self._evidence(rel, v).iterdir()
                          if p.is_dir() and p.name.startswith("attempt-"))
        self.assertEqual(len(archived), 1, f"attempt 1 was not preserved; the directory holds "
                                           f"{sorted(p.name for p in self._evidence(rel, v).iterdir())}")
        self.assertEqual((archived[0] / "VERDICT.tsv").read_text(), first,
                         "attempt 1's verdict was not preserved byte for byte")
        self.assertTrue((archived[0] / "it-FAILURES.txt").is_file(),
                        "attempt 1's failure manifest was destroyed by the re-run that its own "
                        "INCONCLUSIVE/RED verdict asked for")

    def test_a_green_run_after_a_failing_one_ships_no_failure_manifest(self):
        """`RI-11`, exactly as release 0.3.3 shipped it: a GREEN verdict beside a stale `it-FAILURES.txt`
        naming two failures, and an `it-cited/` tree supporting them."""
        from fleet.release_verify import Verify
        rel, v = self._export()
        Verify(rel, v, self.Runner(watcher=self._failing), repo=self.FakeRepo(rel.dir_for(v))).run()
        self.assertTrue((self._evidence(rel, v) / "it-FAILURES.txt").is_file(),
                        "the fixture never produced a failing attempt, so this case proves nothing")

        result = Verify(rel, v, self.Runner(watcher=self._passing),
                        repo=self.FakeRepo(rel.dir_for(v))).run()

        self.assertEqual(result, GREEN)
        self.assertFalse((self._evidence(rel, v) / "it-FAILURES.txt").exists(),
                         "a GREEN release ships a failure manifest from an earlier attempt")
        self.assertFalse((self._evidence(rel, v) / "it-cited").exists(),
                         "a GREEN release ships the evidence an earlier attempt's FAIL row cited")
        self.assertFalse((self._evidence(rel, v) / "it-cited-INDEX.txt").exists())

    def test_the_run_records_its_own_overall_verdict(self):
        """So the NEXT run can name the archive after it -- and so a reader of a released artefact can
        tell an INCONCLUSIVE from a RED without re-deriving it from a note."""
        from fleet.release_verify import Verify
        rel, v = self._export()
        Verify(rel, v, self.Runner(watcher=self._passing), repo=self.FakeRepo(rel.dir_for(v))).run()
        self.assertEqual(read_verdict(rel.dir_for(v) / META_DIR).get("result"), GREEN)

    def test_the_archive_of_a_contaminated_attempt_is_not_named_red(self):
        """`RI-16` where it bites: a run failing while the box moved is INCONCLUSIVE, and stamping RED on
        its archive would write the false RED that verdict exists to prevent."""
        from fleet.release_verify import Verify

        class Moving(ReverifyCase.Runner):
            def __call__(self, command, cwd=None, env=None):
                if "board" in str(command):
                    self.calls.append((str(command), None))
                    return 0, f"subject-{len(self.calls)}", ""
                return super().__call__(command, cwd=cwd, env=env)

        rel, v = self._export()
        result = Verify(rel, v, Moving(watcher=self._failing),
                        repo=self.FakeRepo(rel.dir_for(v))).run()
        self.assertEqual(result, INCONCLUSIVE, "the fixture did not produce a contaminated run")

        Verify(rel, v, self.Runner(watcher=self._passing), repo=self.FakeRepo(rel.dir_for(v))).run()
        archived = sorted(p.name for p in self._evidence(rel, v).iterdir()
                          if p.is_dir() and p.name.startswith("attempt-"))
        self.assertEqual(archived, ["attempt-1-INCONCLUSIVE"])


if __name__ == "__main__":                                   # pragma: no cover
    unittest.main()
