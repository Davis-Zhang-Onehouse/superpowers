"""The M9 mutation runner's anchors and its verdict rule, pinned without running the 45-minute gate.

`FB-108`: `atomic_write_if` gave M2's one-line anchor three matches, the runner's injection aborted after M1,
and the three mutations that were never written were reported SURVIVED. Nothing hermetic ran the anchors, so
the gate was the first thing to notice. These cases make both halves cheap: an anchor that drifts fails here,
and a mutation that does not apply can never be read as a surviving one.
"""
import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "it" / "m9_mutations.py"

_spec = importlib.util.spec_from_file_location("m9_mutations", MODULE)
m9 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m9)


class TestAnchorsAreUniqueInTheCurrentTree(unittest.TestCase):
    """The drift canary. Every mutation the runner injects must find its anchor exactly once in the tree
    the gate will copy; otherwise the runner reports NOT-APPLIED and the gate fails on a harness defect."""

    def test_every_anchor_occurs_exactly_once(self):
        self.assertEqual(sorted(m9.MUTATIONS), [1, 2, 3, 4])
        for n in m9.MUTATIONS:
            with self.subTest(mutation=n):
                self.assertEqual(m9.anchor_count(ROOT, n), 1,
                                 f"{m9.MUTATIONS[n]['label']}: anchor is not present-and-unique in "
                                 f"{m9.MUTATIONS[n]['rel']} — re-anchor it on text only that site carries")

    def test_every_mutation_applies_to_a_copy_and_changes_the_file(self):
        for n, m in m9.MUTATIONS.items():
            with self.subTest(mutation=n), tempfile.TemporaryDirectory() as tmp:
                copy = pathlib.Path(tmp) / m["rel"]
                copy.parent.mkdir(parents=True)
                shutil.copyfile(ROOT / m["rel"], copy)
                m9.inject(tmp, n)
                text = copy.read_text()
                self.assertNotEqual(text, (ROOT / m["rel"]).read_text())
                self.assertEqual(text.count(m["new"]), 1)


class TestAMutationThatDidNotApplyIsNeverAVerdictOnTheRule(unittest.TestCase):

    def _root_with(self, rel, text):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        path = pathlib.Path(tmp) / rel
        path.parent.mkdir(parents=True)
        path.write_text(text)
        return tmp, path

    def test_a_duplicated_anchor_is_refused_and_nothing_is_written(self):
        m = m9.MUTATIONS[2]
        before = f"a\n{m['old']}\nb\n{m['old']}\n"
        tmp, path = self._root_with(m["rel"], before)
        with self.assertRaisesRegex(m9.NotApplied, "2 times"):
            m9.inject(tmp, 2)
        self.assertEqual(path.read_text(), before)

    def test_an_absent_anchor_is_refused_and_nothing_is_written(self):
        tmp, path = self._root_with(m9.MUTATIONS[3]["rel"], "SCHEMA_VERSION = 2\n")
        with self.assertRaisesRegex(m9.NotApplied, "0 times"):
            m9.inject(tmp, 3)
        self.assertEqual(path.read_text(), "SCHEMA_VERSION = 2\n")

    def test_the_cli_exits_not_applied_so_the_runner_can_tell(self):
        m = m9.MUTATIONS[1]
        tmp, _ = self._root_with(m["rel"], f"{m['old']}\n{m['old']}\n")
        r = subprocess.run([sys.executable, str(MODULE), "inject", tmp, "1"], capture_output=True, text=True)
        self.assertEqual(r.returncode, m9.EXIT_NOT_APPLIED, r.stdout + r.stderr)
        self.assertIn("NOT APPLIED", r.stderr)
        self.assertNotIn("injected", r.stdout)

    def test_unapplied_is_never_survived_or_killed_whatever_the_audit_said(self):
        for n in m9.MUTATIONS:
            for audit_rc, output in ((0, ""), (1, m9.MUTATIONS[n]["why"]), (None, "")):
                with self.subTest(mutation=n, audit_rc=audit_rc):
                    self.assertEqual(m9.classify(n, False, audit_rc, output), ("FAIL", "NOT-APPLIED"))

    def test_applied_mutants_are_read_by_the_audit_outcome(self):
        why = m9.MUTATIONS[2]["why"]
        self.assertEqual(m9.classify(2, True, 0, ""), ("FAIL", "SURVIVED"))
        self.assertEqual(m9.classify(2, True, 1, f"... {why} ..."), ("PASS", "KILLED"))
        self.assertEqual(m9.classify(2, True, 1, "ModuleNotFoundError: fleet"), ("FAIL", "WRONG-REASON"))

    def test_the_classify_cli_prints_not_applied_with_no_audit(self):
        r = subprocess.run([sys.executable, str(MODULE), "classify", "3", "0", "-", "-"],
                           capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "FAIL NOT-APPLIED"), r.stderr)


if __name__ == "__main__":
    unittest.main()
