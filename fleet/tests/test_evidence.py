"""`B03` — an evidence item is a LOCATION, not a string.

A proposal's evidence was checked for "non-empty" and nothing else, so a typo'd path was accepted at `propose`
and copied onto the milestone at `apply`, and an absolute `-inflight-` path dangled one rename later. These
cases pin the one resolver every stage now asks: a URL passes untouched, a relative item means the PROPOSING
instant's folder (re-resolved through the rename), and an absolute item re-resolves every instant folder it
names that was renamed.
"""
import tests  # noqa: F401 — installs the suite's host boundary when this module runs alone (FB-118)
import os
import pathlib
import shutil
import tempfile
import unittest

from fleet import evidence
from fleet.errors import BadInput

WORKER = "00000000-07300400-inflight-append-workerOne"
DONE = "00000000-07300400-complete-append-workerOne"
URL = "https://app.clickup.com/t/86e2zdgqu"


class EvidenceCase(unittest.TestCase):
    def setUp(self):
        self.tasks = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tasks, ignore_errors=True)
        self.worker = self.tasks / WORKER
        (self.worker / "evidence").mkdir(parents=True)
        (self.worker / "evidence" / "proof.log").write_text("the artifact\n")
        (self.worker / "HANDOFF.md").write_text("# handoff\n")

    def complete(self) -> pathlib.Path:
        """The worker's completion signal: its own folder is renamed."""
        return self.worker.rename(self.tasks / DONE)


class TestUrl(EvidenceCase):
    def test_a_url_is_recognised_and_never_statted(self):
        self.assertTrue(evidence.is_url(URL))
        self.assertTrue(evidence.is_url("git+ssh://example/repo"))
        self.assertFalse(evidence.is_url("evidence/proof.log"))
        self.assertFalse(evidence.is_url("/abs/path"))
        self.assertIsNone(evidence.locate(URL, self.worker))
        self.assertEqual([], evidence.dangling([URL], self.worker))

    def test_a_url_is_admitted_and_anchored_verbatim(self):
        self.assertEqual([URL], evidence.admit([URL], self.worker))
        self.assertEqual(URL, evidence.anchored(URL, self.worker))
        self.assertEqual(URL, evidence.describe(URL, self.worker))


class TestAdmit(EvidenceCase):
    def test_a_file_url_is_a_path_not_a_url(self):
        """RV-22. `file://` names a path on this box, so it is judged like one: a typo'd one is refused, a real
        one is admitted in its stored path form. Every other scheme is still a URL nobody here can stat."""
        self.assertFalse(evidence.is_url("file:///no/such/thing"))
        with self.assertRaises(BadInput):
            evidence.admit(["file:///no/such/thing"], self.worker)
        self.assertEqual(["evidence/proof.log"],
                         evidence.admit([f"file://{self.worker}/evidence/proof.log"], self.worker))
        self.assertEqual(self.worker / "evidence" / "proof.log",
                         evidence.locate(f"file://{self.worker}/evidence/proof.log", None))
        self.assertTrue(evidence.is_url("git+ssh://example/repo"))

    def test_a_relative_item_that_exists_is_stored_verbatim(self):
        self.assertEqual(["evidence/proof.log"], evidence.admit(["evidence/proof.log"], self.worker))

    def test_a_relative_typo_is_refused_naming_where_it_was_looked_for(self):
        with self.assertRaises(BadInput) as caught:
            evidence.admit(["evidence/nope-typo.log"], self.worker)
        self.assertIn("evidence/nope-typo.log", str(caught.exception))
        self.assertIn(str(self.worker), str(caught.exception))

    def test_an_absolute_path_that_never_existed_is_refused(self):
        with self.assertRaises(BadInput):
            evidence.admit([str(self.worker / "evidence" / "also-nope.log")], self.worker)

    def test_every_unresolvable_item_is_named_in_one_refusal(self):
        with self.assertRaises(BadInput) as caught:
            evidence.admit(["evidence/proof.log", "evidence/a.log", "/no/such/b.log"], self.worker)
        message = str(caught.exception)
        self.assertIn("evidence/a.log", message)
        self.assertIn("/no/such/b.log", message)
        self.assertIn("2 evidence item(s)", message)

    def test_an_absolute_self_path_is_stored_relative_so_it_survives_the_rename(self):
        stored = evidence.admit([str(self.worker / "evidence" / "proof.log"), str(self.worker / "HANDOFF.md")],
                                self.worker)
        self.assertEqual(["evidence/proof.log", "HANDOFF.md"], stored)

    def test_an_absolute_path_outside_the_proposer_is_stored_verbatim(self):
        other = self.tasks / "elsewhere.txt"
        other.write_text("x")
        self.assertEqual([str(other)], evidence.admit([str(other)], self.worker))

    def test_a_proposer_that_does_not_resolve_cannot_anchor_a_relative_item(self):
        with self.assertRaises(BadInput):
            evidence.admit(["evidence/proof.log"], self.tasks / "00000000-07300401-inflight-append-ghost")


class TestThroughTheRename(EvidenceCase):
    def test_a_relative_item_anchored_at_the_old_inflight_path_resolves_after_complete(self):
        done = self.complete()
        self.assertEqual(done / "evidence" / "proof.log", evidence.locate("evidence/proof.log", self.worker))
        self.assertEqual([], evidence.dangling(["evidence/proof.log"], self.worker))

    def test_an_absolute_inflight_path_resolves_after_complete(self):
        stale = str(self.worker / "evidence" / "proof.log")
        done = self.complete()
        self.assertEqual(done / "evidence" / "proof.log", evidence.locate(stale, None))
        self.assertEqual(str(done / "evidence" / "proof.log"), evidence.anchored(stale, None))

    def test_the_deepest_instant_folder_is_the_one_re_resolved(self):
        inner_old = self.worker / "evidence" / "00000000-07300500-inflight-append-inner"
        inner_old.mkdir()
        (inner_old / "r.txt").write_text("r")
        stale = str(inner_old / "r.txt")
        inner_new = inner_old.rename(inner_old.parent / "00000000-07300500-complete-append-inner")
        self.assertEqual(inner_new / "r.txt", evidence.locate(stale, None))

    def test_an_outer_instant_renamed_while_the_inner_kept_its_name_still_resolves(self):
        inner = self.worker / "evidence" / "00000000-07300500-inflight-append-inner"
        inner.mkdir()
        (inner / "r.txt").write_text("r")
        stale = str(inner / "r.txt")
        done = self.complete()
        self.assertEqual(done / "evidence" / inner.name / "r.txt", evidence.locate(stale, None))

    def test_a_directory_and_a_dotdot_item_that_resolve_are_admitted(self):
        (self.tasks / "shared.txt").write_text("s")
        self.assertEqual(["evidence", "../shared.txt"], evidence.admit(["evidence", "../shared.txt"], self.worker))

    def test_a_relative_item_through_a_renamed_nested_instant_still_resolves(self):
        """Final review Minor-1: the tail of a RELATIVE item is walked through renames too, not only its anchor."""
        child = self.worker / "00000000-07300401-inflight-append-child"
        (child / "evidence").mkdir(parents=True)
        (child / "evidence" / "x.log").write_text("x")
        self.assertEqual([f"{child.name}/evidence/x.log"], evidence.admit([f"{child.name}/evidence/x.log"], self.worker))
        renamed = child.rename(self.worker / "00000000-07300401-complete-append-child")
        self.assertEqual(renamed / "evidence" / "x.log", evidence.locate(f"{child.name}/evidence/x.log", self.worker))

    def test_a_stale_absolute_path_that_resolves_through_the_rename_is_admitted(self):
        """Final review Minor-2: the coordinator re-proposing on a completed worker's behalf pastes its old path."""
        stale = str(self.worker / "evidence" / "proof.log")
        coordinator = self.tasks / "00000000-07300300-inflight-append-coord"
        coordinator.mkdir()
        done = self.complete()
        self.assertEqual([str(done / "evidence" / "proof.log")], evidence.admit([stale], coordinator))
        self.assertEqual(["evidence/proof.log"], evidence.admit([stale], self.worker), "inside the proposer: relative")

    def test_a_dotdot_item_is_located_normalised(self):
        """Final review Minor-4: no `..` (and so no proposer name) survives into the anchored form."""
        (self.tasks / "shared.txt").write_text("s")
        self.assertEqual(str(self.tasks / "shared.txt"), evidence.anchored("../shared.txt", self.worker))
        self.assertEqual(evidence.locate("evidence/proof.log", self.worker),
                         evidence.locate("evidence/../evidence/proof.log", self.worker))

    def test_a_file_deleted_after_propose_dangles(self):
        (self.worker / "evidence" / "proof.log").unlink()
        self.assertEqual(["evidence/proof.log"], evidence.dangling(["evidence/proof.log"], self.worker))

    @unittest.skipIf(os.geteuid() == 0, "root reads a mode-000 directory anyway")
    def test_an_unreadable_directory_reads_as_not_resolving_not_a_traceback(self):
        """RV-25. `exists()`/`iterdir()` raise PermissionError under a directory this user cannot read, which
        would take down `fleet roadmap` and every refusal that names an item."""
        locked = self.tasks / "locked"
        (locked / "00000000-07300402-complete-append-deep").mkdir(parents=True)
        stale = str(locked / "00000000-07300402-inflight-append-deep" / "x.log")
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        self.assertIsNone(evidence.locate(stale, None))
        self.assertIsNone(evidence.locate("x.log", locked / "00000000-07300402-inflight-append-deep"))
        self.assertEqual([stale], evidence.dangling([stale], None))
        with self.assertRaises(BadInput):
            evidence.admit([stale], self.worker)

    def test_two_folders_sharing_a_stable_key_resolve_to_nothing_not_a_traceback(self):
        done = self.complete()
        shutil.copytree(done, self.tasks / "00000000-07300400-abort-append-workerOne")
        self.assertIsNone(evidence.locate("evidence/proof.log", self.worker))
        self.assertIsNone(evidence.locate(str(self.worker / "evidence" / "proof.log"), None))


class TestAnchoredAndDescribe(EvidenceCase):
    def test_a_relative_item_is_anchored_at_the_proposers_current_folder(self):
        done = self.complete()
        self.assertEqual(str(done / "evidence" / "proof.log"), evidence.anchored("evidence/proof.log", self.worker))

    def test_describe_prints_where_it_is_now_or_says_it_does_not_resolve(self):
        done = self.complete()
        self.assertEqual(str(done / "evidence" / "proof.log"), evidence.describe("evidence/proof.log", self.worker))
        self.assertEqual("evidence/proof.log", evidence.describe("evidence/proof.log", self.worker, short=True))
        self.assertEqual("evidence/gone.log (does not resolve)", evidence.describe("evidence/gone.log", self.worker))
        self.assertEqual("evidence/proof.log (does not resolve)", evidence.describe("evidence/proof.log", None))

    def test_describe_short_prints_an_absolute_item_where_it_is_now(self):
        stale = str(self.worker / "HANDOFF.md")
        done = self.complete()
        self.assertEqual(str(done / "HANDOFF.md"), evidence.describe(stale, None, short=True))


if __name__ == "__main__":
    unittest.main()
