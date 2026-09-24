"""B25: the mutation runner's extractor takes the ONE anchored block or refuses, and every injection anchor
is unique in the tree it targets. RED: the w2itharness instant's evidence/01-red/b25-decoy-*-base.txt (a
1-line decoy certified as the audit; mutants 3/4 SURVIVED without being injected)."""
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
IT = REPO / "fleet" / "it"
ANCHOR = 'cat > "$PY_DIR/m9.py" <<\'PY\'\n'


class MutationExtractor(unittest.TestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="it-m9-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.extractor = IT / "bin" / "extract-m9.py"

    def extract(self, caller):
        out = self.tmp / "m9.py"
        r = subprocess.run(["python3", str(self.extractor), str(caller), str(out)], capture_output=True, text=True)
        return r, out

    def test_the_real_caller_yields_the_audit(self):
        r, out = self.extract(IT / "run-group5.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("M9", out.read_text()[:200])
        self.assertGreater(len(out.read_text().splitlines()), 100)

    def test_a_decoy_block_above_the_real_one_is_refused(self):
        src = (IT / "run-group5.sh").read_text()
        self.assertEqual(src.count(ANCHOR), 1)
        decoy = self.tmp / "run-group5-decoy.sh"
        decoy.write_text(src.replace(ANCHOR, ANCHOR + 'print("DECOY AUDIT: I pass everything")\nPY\n' + ANCHOR, 1))
        r, out = self.extract(decoy)
        self.assertEqual(r.returncode, 2)
        self.assertIn("occurs 2 times", r.stderr)
        self.assertFalse(out.exists())

    def test_a_caller_with_no_anchor_is_refused(self):
        r, out = self.extract(IT / "lib.sh")
        self.assertEqual(r.returncode, 2)
        self.assertIn("occurs 0 times", r.stderr)
        self.assertFalse(out.exists())

    def test_the_runner_owns_extract_and_inject_rows_and_uses_the_extractor(self):
        text = (IT / "run-m9-mutation.sh").read_text()
        self.assertIn("bin/extract-m9.py", text)
        self.assertRegex(text, r"it_own_cases 'M9-mut-\(baseline\|extract\|inject\|1\|2\|3\|4\)")
        self.assertNotIn("src.index(", text)
        self.assertIn("M9-mut-inject", text)

    def test_the_unreached_helper_is_defined_before_every_use_and_every_abort_uses_it(self):
        """An abort must leave SKIP rows for the cases it never reached; a helper called before its definition
        is `command not found` and writes none (found in the final review)."""
        text = (IT / "run-m9-mutation.sh").read_text()
        defined = text.index("m9_unreached() {")
        uses = [m.start() for m in re.finditer(r"^\s*m9_unreached ", text, re.M)]
        self.assertGreaterEqual(len(uses), 3, "extract-refused, baseline-red and inject-failed aborts")
        self.assertTrue(all(u > defined for u in uses), "m9_unreached is used before it is defined")
        self.assertEqual(text.count("\n  exit 1\n"), 3, "three abort paths")
        self.assertEqual(len(uses), 3, "one m9_unreached call per abort path")

    def test_every_injection_anchor_is_unique_in_the_base_tree(self):
        """The anchors in run-m9-mutation.sh's inject() calls must each occur once in the file they target —
        M2's bare `os.unlink(tmp)` occurred three times in atomic.py since RV-18/RV-36 (ISSUES I-2)."""
        text = (IT / "run-m9-mutation.sh").read_text()
        calls = re.findall(r'inject\("mut\d/src/fleet/(\w+\.py)",\s*("(?:[^"\\]|\\.)*")', text)
        self.assertEqual(len(calls), 4, calls)
        for rel, quoted in calls:
            anchor = eval(quoted)  # a python string literal, from our own runner
            n = (REPO / "fleet" / "src" / "fleet" / rel).read_text().count(anchor)
            self.assertEqual(n, 1, f"{rel}: anchor {anchor!r} occurs {n} times")


if __name__ == "__main__":
    unittest.main()


class MergeResults(unittest.TestCase):
    """run-all.sh's merge (bin/merge-results.py): sections that ran replace their rows; an OWN-<case> row is
    dropped only when this run re-judged its case or its section (found in review: a default-roster run
    used to erase a standalone §F's OWN-F… FAIL while the stale twin it flagged stayed)."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="it-merge-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "RESULTS.tsv").write_text(
            "case\tverdict\tevidence\tnote\n"
            "B1\tPASS\t\told b1\nOWN-B1\tFAIL\t\tstale own\n"
            "F1\tPASS\t\told f1\nF9-zero-delta\tPASS\t\tstale twin\nOWN-F9-zero-delta\tFAIL\t\tflagged\n"
            "§F\tNOT-RUN\t\t\n")
        (self.tmp / "RESULTS-closeout-B.tsv").write_text("case\tverdict\tevidence\tnote\nB1\tPASS\t\tnew b1\n")

    def merge(self, *names):
        r = subprocess.run(["python3", str(IT / "bin" / "merge-results.py"), str(self.tmp), *names],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return {l.split("\t")[0]: l.split("\t")[3] for l in (self.tmp / "RESULTS.tsv").read_text().splitlines()[1:]}

    def test_a_ran_section_replaces_its_rows_and_its_own_rows(self):
        out = self.merge("B")
        self.assertEqual(out["B1"], "new b1")
        self.assertNotIn("OWN-B1", out)

    def test_an_own_row_of_a_section_this_run_did_not_execute_is_kept(self):
        out = self.merge("B")
        self.assertIn("OWN-F9-zero-delta", out)
        self.assertIn("F9-zero-delta", out)
        self.assertIn("§F", out)

    def test_a_ran_section_also_drops_its_not_run_row(self):
        (self.tmp / "RESULTS-closeout-F.tsv").write_text("case\tverdict\tevidence\tnote\nF1\tPASS\t\tnew f1\n")
        out = self.merge("B", "F")
        self.assertNotIn("§F", out)
        self.assertNotIn("OWN-F9-zero-delta", out)

    def test_run_all_calls_the_module(self):
        text = (IT / "run-all.sh").read_text()
        self.assertIn('bin/merge-results.py" "$IT_ROOT" all', text)
        self.assertNotIn("kept = [r for r in existing", text)
