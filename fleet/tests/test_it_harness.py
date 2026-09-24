"""The IT harness as an instrument (B18 / B25 / FB-37 / FB-38 / FB-73 / FB-75 / FB-76 / FB-99).

Hermetic: a throwaway `fleet/it` holding only lib.sh, facts.env and bin/, with src/ symlinked, run from a tmp
cwd with every FLEET_* destination unset. Nothing here reads or writes the live store, the default tmux
server or the tracked RESULTS.tsv. Each class names the defect it pins and the RED it was written against
(the w2itharness instant's evidence/01-red/).
"""
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
IT = REPO / "fleet" / "it"
FLEET_DESTINATIONS = ("FLEET_HOME", "FLEET_INSTANTS", "FLEET_ROOT", "FLEET_INSTANT", "FLEET_RELEASES")


def harness_copy(tmp: pathlib.Path) -> pathlib.Path:
    """<tmp>/fleet/it with lib.sh, facts.env and bin/ copied and src/ symlinked; returns the it dir."""
    it = tmp / "fleet" / "it"
    it.mkdir(parents=True)
    for name in ("lib.sh", "facts.env"):
        shutil.copy(IT / name, it / name)
    shutil.copytree(IT / "bin", it / "bin")
    os.symlink(REPO / "fleet" / "src", tmp / "fleet" / "src")
    return it


def clean_env(extra=None) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in FLEET_DESTINATIONS}
    env.update(extra or {})
    return env


def run_bash(script: str, cwd: pathlib.Path, env=None, stdin=subprocess.DEVNULL, timeout=120):
    return subprocess.run(["bash", "-c", script], cwd=cwd, env=clean_env(env), stdin=stdin,
                          capture_output=True, text=True, timeout=timeout)


class WrapperExecutable(unittest.TestCase):
    """B18. The wrapper must be reachable from the harness's own idioms — `timeout`, `env -u`, `exec` — which
    cannot invoke a bash function, and it must be the ONLY route to the product. RED:
    evidence/01-red/b18-classifier-bypass-base.txt (a bypassed mint charged to the operator, PASS) beside
    b18-classifier-wrapped-base.txt (the same mint through the wrapper, FAIL)."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="it-harness-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.it = harness_copy(self.tmp)

    def test_it_fleet_records_names_behind_timeout_env_and_exec(self):
        reg = self.tmp / "asked.txt"
        script = f"""
        . "{self.it}/lib.sh"
        export IT_ASKED_NAMES="{reg}"; : > "$IT_ASKED_NAMES"
        timeout 30 "$IT_FLEET" init --name viaTimeout --dry-run >/dev/null 2>&1
        env -u FLEET_HOME "$IT_FLEET" dispatch --title viaEnv --dry-run >/dev/null 2>&1
        ( exec "$IT_FLEET" milestone --title viaExec ) >/dev/null 2>&1
        fleet init --name viaFunction >/dev/null 2>&1
        "$IT_FLEET" board --porcelain >/dev/null 2>&1
        """
        run_bash(script, self.tmp)
        self.assertEqual(reg.read_text().split(), ["viaTimeout", "viaEnv", "viaExec", "viaFunction"])

    def test_it_fleet_passes_argv_streams_and_exit_code_through(self):
        out = run_bash(f'. "{self.it}/lib.sh"; "$IT_FLEET" notaverb --porcelain; echo "rc=$?"', self.tmp)
        self.assertIn("rc=2", out.stdout)
        out = run_bash(f'. "{self.it}/lib.sh"; "$IT_FLEET" init --help >/dev/null; echo "rc=$?"', self.tmp)
        self.assertIn("rc=0", out.stdout)

    def test_it_fleet_is_a_no_op_recorder_without_a_register(self):
        out = run_bash(f'. "{self.it}/lib.sh"; unset IT_ASKED_NAMES; '
                       f'"$IT_FLEET" init --name nobody --dry-run >/dev/null 2>&1; echo rc=$?', self.tmp)
        self.assertRegex(out.stdout, r"rc=\d")

    def test_it_fleet_supplies_pythonpath_when_the_caller_stripped_it(self):
        out = run_bash(f'. "{self.it}/lib.sh"; env -u PYTHONPATH "$IT_FLEET" init --help >/dev/null; echo "rc=$?"',
                       self.tmp)
        self.assertIn("rc=0", out.stdout)

    def test_no_direct_python_m_fleet_cli_outside_the_wrapper(self):
        """The lint: every executed `python3 -m fleet.cli` in the harness is inside bin/it-fleet. A line
        whose first non-blank character is `#` is a comment (run-C.sh carries two)."""
        hits = []
        files = sorted(list(IT.glob("*.sh")) + [p for p in (IT / "bin").iterdir() if p.is_file()])
        self.assertGreater(len(files), 30)
        for path in files:
            if path.name == "it-fleet":
                continue
            for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                if "python3 -m fleet.cli" in line and not line.lstrip().startswith("#"):
                    hits.append(f"{path.relative_to(REPO)}:{n}")
        self.assertEqual(hits, [], "direct sites bypass the attribution register (B18): " + ", ".join(hits))


class RowOwnership(unittest.TestCase):
    """FB-37/FB-76. A runner declares what it owns; the writer must FAIL when the runner writes a row outside
    that declaration (a stale twin would survive every re-run), and a section's fresh rows must land where
    its old rows stood, not at the end of the file. RED: evidence/01-red/fb37-regex-base.txt and
    fb75-76-sectionF-real-base.txt (nine duplicate ids, the section moved from line 117 to 335)."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="it-harness-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.it = harness_copy(self.tmp)
        self.results = self.tmp / "RESULTS.tsv"
        self.results.write_text("case\tverdict\tevidence\tnote\n"
                                "A1\tPASS\t\ta\nF1\tPASS\t\told f1\nF9-zero-delta\tPASS\t\tstale\n"
                                "G1\tPASS\t\tg\nF2\tFAIL\t\told f2\nZ9\tPASS\t\tz\n")

    def rows(self):
        return [l.split("\t") for l in self.results.read_text().splitlines()[1:]]

    def run_lib(self, body):
        return run_bash(f'. "{self.it}/lib.sh"\n{body}', self.tmp, env={"IT_RESULTS": str(self.results)})

    def test_a_row_outside_the_declared_regex_is_a_fail(self):
        out = self.run_lib("it_own_cases 'F[0-9]+'\nit_pass F9-zero-delta '' 'fresh'\necho IT_FAILED=$IT_FAILED")
        ids = [r[0] for r in self.rows()]
        self.assertIn("OWN-F9-zero-delta", ids)
        own = next(r for r in self.rows() if r[0] == "OWN-F9-zero-delta")
        self.assertEqual(own[1], "FAIL")
        self.assertIn("F[0-9]+", own[3])
        self.assertIn("IT_FAILED=1", out.stdout)

    def test_the_fixed_regex_claims_f9_and_f10_rows(self):
        re_f = re.search(r"^it_own_cases '([^']*)'", (IT / "run-F.sh").read_text(), re.M).group(1)
        self.run_lib(f"it_own_cases '{re_f}'\nit_pass F9-zero-delta '' 'fresh'\nit_pass F10-status '' 'fresh'")
        ids = [r[0] for r in self.rows()]
        self.assertEqual(ids.count("F9-zero-delta"), 1)
        self.assertNotIn("OWN-F9-zero-delta", ids)
        self.assertNotIn("OWN-F10-status", ids)

    def test_fresh_rows_are_written_where_the_old_ones_stood(self):
        self.run_lib("it_own_cases 'F[0-9]+(-[A-Za-z0-9-]+)?'\nit_pass F1 '' 'new f1'\nit_fail F2 '' 'new f2'\n"
                     "it_pass F9-zero-delta '' 'new'")
        ids = [r[0] for r in self.rows()]
        self.assertEqual(ids, ["A1", "F1", "F2", "F9-zero-delta", "G1", "Z9"])
        self.assertEqual(next(r for r in self.rows() if r[0] == "F1")[3], "new f1")

    def test_a_runner_with_no_prior_rows_appends(self):
        self.run_lib("it_own_cases 'Q[0-9]+'\nit_pass Q1 '' 'q'")
        self.assertEqual([r[0] for r in self.rows()][-1], "Q1")

    def test_writing_before_own_cases_appends_and_does_not_crash(self):
        out = self.run_lib("it_pass ISOLATION-ALL-enter '' 'x'; echo done=$?")
        self.assertIn("done=0", out.stdout)
        self.assertEqual([r[0] for r in self.rows()][-1], "ISOLATION-ALL-enter")

    def test_notes_with_backslashes_and_percent_survive_in_place(self):
        note = r"a\tb %s \\n 100%"
        self.run_lib(f"it_own_cases 'F[0-9]+'\nit_pass F1 '' '{note}'")
        self.assertEqual(next(r for r in self.rows() if r[0] == "F1")[3], note)

    def test_it_last_verdict_names_the_row_just_written(self):
        out = self.run_lib("it_own_cases 'F[0-9]+'\nit_fail F1 '' x; echo v=$IT_LAST_VERDICT; "
                           "it_pass F2 '' y; echo v=$IT_LAST_VERDICT")
        self.assertEqual(re.findall(r"^v=(\w+)$", out.stdout, re.M), ["FAIL", "PASS"])

    def test_own_fail_rows_are_dropped_on_the_next_owned_run(self):
        self.run_lib("it_own_cases 'F[0-9]+'\nit_pass F9-zero-delta '' 'fresh'")
        self.run_lib("it_own_cases 'F[0-9]+(-[A-Za-z0-9-]+)?'\nit_pass F9-zero-delta '' 'fresh2'")
        ids = [r[0] for r in self.rows()]
        self.assertNotIn("OWN-F9-zero-delta", ids)
        self.assertEqual(ids.count("F9-zero-delta"), 1)

    def test_every_literal_regex_claims_the_isolation_rows_its_runner_writes(self):
        """FB-37's class in two more runners (run-e9-leak, run-rmw): the ISOLATION-<tag> rows a runner's
        top-level it_assert_isolation calls write must match its own regex. Top-level (column 0) only: a
        negative control calls it inside a subshell, indented, with RESULTS repointed at a private file,
        and those rows never reach the register."""
        bad, seen = [], 0
        for path in sorted(IT.glob("run-*.sh")):
            text = path.read_text(errors="replace")
            m = re.search(r"^it_own_cases '([^']*)'", text, re.M)   # the runner's own, top-level declaration
            if not m:
                continue
            rx = re.compile("^(OWN-)?(" + m.group(1) + ")$")
            for tag in re.findall(r"^it_assert_isolation ([A-Za-z0-9-]+)", text, re.M):
                seen += 1
                if not rx.match("ISOLATION-" + tag):
                    bad.append(f"{path.name}: ISOLATION-{tag} not in '{m.group(1)}'")
        self.assertGreater(seen, 10)
        self.assertEqual(bad, [])

    def test_a_repointed_register_is_appended_to_and_never_judged(self):
        """A negative control repoints RESULTS inside a subshell: no OWN row, no in-place index."""
        neg = self.tmp / "neg.tsv"
        out = self.run_lib(f"it_own_cases 'F[0-9]+'\n( RESULTS='{neg}'; : > \"$RESULTS\"; it_pass X-neg '' 'n'; it_pass Y-neg '' 'm' )\n"
                           "it_pass F1 '' 'shared'; echo IT_FAILED=${IT_FAILED:-0}")
        self.assertEqual([l.split("\t")[0] for l in neg.read_text().splitlines()], ["X-neg", "Y-neg"])
        self.assertIn("IT_FAILED=0", out.stdout)
        self.assertEqual([r[0] for r in self.rows()], ["A1", "F1", "G1", "Z9"])

    def test_group5_claims_its_coverage_rows(self):
        """Found by the plan's pre-flight scan: run-group5.sh writes L7-coverage and M5-coverage."""
        text = (IT / "run-group5.sh").read_text()
        l_re = re.search(r'L\) own="\$own\|([^"]*)"', text).group(1)
        m_re = re.search(r'M\) own="\$own\|([^"]*)"', text).group(1)
        self.assertRegex("L7-coverage", "^(" + l_re + ")$")
        self.assertRegex("M5-coverage", "^(" + m_re + ")$")
        self.assertRegex("M8-release-history", "^(" + m_re + ")$")
        self.assertRegex("M11b", "^(" + m_re + ")$")


if __name__ == "__main__":
    unittest.main()
