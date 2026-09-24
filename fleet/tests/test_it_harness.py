"""The IT harness as an instrument (B18 / B25 / FB-37 / FB-38 / FB-73 / FB-75 / FB-76 / FB-99).

Hermetic: a throwaway `fleet/it` holding only lib.sh, facts.env and bin/, with src/ symlinked, run from a tmp
cwd with every FLEET_* destination unset. Nothing here reads or writes the live store, the default tmux
server or the tracked RESULTS.tsv. Each class names the defect it pins and the RED it was written against
(the w2itharness instant's evidence/01-red/).
"""
import atexit
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid

REPO = pathlib.Path(__file__).resolve().parents[2]
IT = REPO / "fleet" / "it"
FLEET_DESTINATIONS = ("FLEET_HOME", "FLEET_INSTANTS", "FLEET_ROOT", "FLEET_INSTANT", "FLEET_RELEASES",
                      "FLEET_TMUX_SOCKET",              # the product's `-L`: inherited, it names the operator's server
                      "IT_ASKED_NAMES", "IT_RESULTS",   # an IT section runs this suite (M13)
                      "TMUX", "TMUX_PANE")              # a bare `tmux` inside a pane follows $TMUX, not TMUX_TMPDIR
#: One private tmux directory per test process for ordinary cases. ServerGuardian's missing-directory
#: regression cases use a uniquely named server under tmux's real default directory to prove that a
#: fallback cannot kill it; each registers an explicit kill-server cleanup for only that fixture.
#: (`tempfile.gettempdir()` would be /tmp, which IS tmux's default — found in review.)
PRIVATE_TMUX_DIR = tempfile.mkdtemp(prefix="it-harness-tmux-")
atexit.register(shutil.rmtree, PRIVATE_TMUX_DIR, True)


def harness_copy(tmp: pathlib.Path) -> pathlib.Path:
    """<tmp>/fleet/it with lib.sh, facts.env and bin/ copied and src/ symlinked; returns the it dir."""
    it = tmp / "fleet" / "it"
    it.mkdir(parents=True)
    for name in ("lib.sh", "facts.env"):
        shutil.copy(IT / name, it / name)
    shutil.copytree(IT / "bin", it / "bin")
    os.symlink(REPO / "fleet" / "src", tmp / "fleet" / "src")
    return it


def clean_env(extra=None, home=None) -> dict:
    """The operator's environment minus every fleet destination and tmux handle; `home` (a tmp dir) replaces
    HOME for callers that reach it_section, whose isolation check lists $HOME/.fleet/instants and hashes
    $HOME/.claude-* files — read-only, and still not this suite's to read."""
    env = {k: v for k, v in os.environ.items() if k not in FLEET_DESTINATIONS}
    env["TMUX_TMPDIR"] = PRIVATE_TMUX_DIR
    if home is not None:
        env["HOME"] = str(home)
    env.update(extra or {})
    return env


def run_bash(script: str, cwd: pathlib.Path, env=None, stdin=subprocess.DEVNULL, timeout=120, home=None):
    return subprocess.run(["bash", "-c", script], cwd=cwd, env=clean_env(env, home=home), stdin=stdin,
                          capture_output=True, text=True, timeout=timeout)


class WrapperExecutable(unittest.TestCase):
    """B18. The wrapper must be reachable from the harness's own idioms — `timeout`, `env -u`, `exec` — which
    cannot invoke a bash function, and it must be the harness's one SUBPROCESS route to the product. RED:
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
        timeout 30 "$IT_FLEET" init --home "{self.tmp}/store" --name viaTimeout --dry-run >/dev/null 2>&1
        env -u FLEET_HOME "$IT_FLEET" dispatch --home "{self.tmp}/store" --title viaEnv --dry-run >/dev/null 2>&1
        ( exec "$IT_FLEET" milestone --home "{self.tmp}/store" --title viaExec ) >/dev/null 2>&1
        fleet init --home "{self.tmp}/store" --name viaFunction --dry-run >/dev/null 2>&1
        "$IT_FLEET" board --home "{self.tmp}/store" --porcelain >/dev/null 2>&1
        """
        run_bash(script, self.tmp)
        self.assertEqual(reg.read_text().split(), ["viaTimeout", "viaEnv", "viaExec", "viaFunction"])

    def _direct_and_wrapped(self, *argv):
        """(direct, wrapped): the product run as `python3 -m fleet.cli`, and through the wrapper, same argv,
        same environment. Byte-equal streams and an equal code are the pass-through contract."""
        env = {"PYTHONPATH": str(REPO / "fleet" / "src")}
        direct = subprocess.run(["python3", "-m", "fleet.cli", *argv], cwd=self.tmp, env=clean_env(env),
                                stdin=subprocess.DEVNULL, capture_output=True, text=True)
        wrapped = subprocess.run([str(self.it / "bin" / "it-fleet"), *argv], cwd=self.tmp, env=clean_env(env),
                                 stdin=subprocess.DEVNULL, capture_output=True, text=True)
        return direct, wrapped

    def test_it_fleet_passes_argv_streams_and_exit_code_through(self):
        for argv in (["notaverb", "--porcelain"], ["init", "--help"],
                     ["board", "--home", str(self.tmp / "store"), "--porcelain"]):
            direct, wrapped = self._direct_and_wrapped(*argv)
            self.assertEqual((wrapped.returncode, wrapped.stdout, wrapped.stderr),
                             (direct.returncode, direct.stdout, direct.stderr), argv)
        self.assertEqual(self._direct_and_wrapped("notaverb", "--porcelain")[0].returncode, 2)
        self.assertEqual(self._direct_and_wrapped("init", "--help")[0].returncode, 0)

    def test_it_fleet_is_a_no_op_recorder_without_a_register(self):
        direct, wrapped = self._direct_and_wrapped("init", "--name", "nobody", "--dry-run")
        self.assertNotIn("unbound variable", wrapped.stderr)
        self.assertNotIn("it-fleet", wrapped.stderr)
        self.assertEqual((wrapped.returncode, wrapped.stdout, wrapped.stderr),
                         (direct.returncode, direct.stdout, direct.stderr))

    def test_the_lint_tokens_catch_the_split_and_joined_forms(self):
        """The shapes closure 1 showed slipping past a literal match."""
        for line in ('cmd = [sys.executable, "-m","fleet.cli", verb]', "cmd = [sys.executable, '-m', 'fleet.cli']",
                     "subprocess.run([str(repo / 'bin/fleet'), *args])", 'subprocess.run([str(repo / "bin" / "fleet")])',
                     'timeout 60 python3 -m fleet.cli init', '"$REPO/bin/fleet" board'):
            self.assertTrue(self.MODULE_FORM.search(line) or self.LAUNCHER_FORM.search(line), line)
        for line in ("from fleet.cli import VERBS", "exec python3 -m fleet_cli_stub", 'printf "editing src/fleet/cli.py"'):
            self.assertFalse(self.MODULE_FORM.search(line) or self.LAUNCHER_FORM.search(line), line)

    def test_it_fleet_supplies_pythonpath_when_the_caller_stripped_it(self):
        out = run_bash(f'. "{self.it}/lib.sh"; env -u PYTHONPATH "$IT_FLEET" init --help >/dev/null; echo "rc=$?"',
                       self.tmp)
        self.assertIn("rc=0", out.stdout)

    #: The shapes a product subprocess takes in this harness, as TOKENS (found in closure: literals let mixed
    #: quotes and `"bin" / "fleet"` slip through): the module form `-m fleet.cli` however it is quoted or
    #: split, and the launcher `bin/fleet` however the path is joined. run-Q.sh is exempt BY NAME for the
    #: launcher form only: it is the section that tests the launcher itself, and its verbs cannot mint. An
    #: in-process `from fleet.cli import …` is not a subprocess and is not matched. A line whose first
    #: non-blank character is `#` is a comment (run-C.sh carries two).
    MODULE_FORM = re.compile(r"""-m['"]?\s*,?\s*['"]?\s*fleet\.cli""")
    LAUNCHER_FORM = re.compile(r"""\bbin['"]?\s*/\s*['"]?fleet\b""")
    LAUNCHER_EXEMPT = {"run-Q.sh"}

    def test_no_direct_python_m_fleet_cli_outside_the_wrapper(self):
        """The lint: every product subprocess in the harness goes through bin/it-fleet — the shell form
        `python3 -m fleet.cli`, and in the embedded/standalone python the `"-m", "fleet.cli"` and
        `bin/fleet` forms (found in review: run-D, run-group5 and runtime-*.py minted through them)."""
        hits = []
        files = sorted(list(IT.glob("*.sh")) + list(IT.glob("*.py")) + [p for p in (IT / "bin").iterdir() if p.is_file()])
        self.assertGreater(len(files), 32)
        for path in files:
            if path.name == "it-fleet":
                continue
            for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if self.MODULE_FORM.search(line) or (path.name not in self.LAUNCHER_EXEMPT and self.LAUNCHER_FORM.search(line)):
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

    def test_a_row_written_in_a_subshell_keeps_the_section_in_order(self):
        """F9-zero-delta is written inside `( … )`: a counter would advance only there, and every later row
        would land BEFORE it. The insertion point is re-derived from the file instead."""
        self.run_lib("it_own_cases 'F[0-9]+(-[A-Za-z0-9-]+)?'\nit_pass F1 '' a\n( it_pass F9-zero-delta '' b )\nit_pass F10 '' c\nit_pass F11 '' d")
        self.assertEqual([r[0] for r in self.rows()], ["A1", "F1", "F9-zero-delta", "F10", "F11", "G1", "Z9"])

    def test_a_regex_with_a_backslash_is_read_alike_by_the_drop_and_the_ownership_check(self):
        """awk -v processes escapes and grep -E does not; both readers now take the regex through ENVIRON."""
        self.results.write_text("case\tverdict\tevidence\tnote\nX.1\tPASS\t\told\nXa1\tPASS\t\tnot ours\n")
        self.run_lib("it_own_cases 'X\\.[0-9]+'\nit_pass X.1 '' 'new'")
        ids = [r[0] for r in self.rows()]
        self.assertEqual(ids, ["X.1", "Xa1"])
        self.assertNotIn("OWN-X.1", ids)

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
        self.run_lib(f"it_own_cases 'F[0-9]+'\n( RESULTS='{neg}'; : > \"$RESULTS\"; it_pass X-neg '' 'n'; it_pass Y-neg '' 'm' )\n"
                     "it_pass F1 '' 'shared'")
        self.assertEqual([l.split("\t")[0] for l in neg.read_text().splitlines()], ["X-neg", "Y-neg"])
        self.assertNotIn("OWN-", neg.read_text())
        # F9-zero-delta is NOT claimed by F[0-9]+, so it survives; F1's fresh row took its old line.
        self.assertEqual([r[0] for r in self.rows()], ["A1", "F1", "F9-zero-delta", "G1", "Z9"])

    def test_run_b_targeted_b5_b6_b7_owns_all_three(self):
        """B5, B6 and B7 share one case body and are written together; a targeted run of one must own all."""
        text = (IT / "run-B.sh").read_text()
        m = re.search(r"^b_owned_cases\(\) \{.*?^\}", text, re.S | re.M)
        self.assertIsNotNone(m)
        out = subprocess.run(["bash", "-c", m.group(0) + '\nb_owned_cases B6'], capture_output=True, text=True)
        rx = re.compile("^(" + out.stdout.strip() + ")$")
        for case in ("B5", "B6", "B7", "ISOLATION-B-enter"):
            self.assertRegex(case, rx)

    def test_every_runner_that_moves_its_tmux_directory_re_arms_the_guardian(self):
        """A bare `export TMUX_TMPDIR=` in a runner leaves the guardian on the wrong directory."""
        bare = [f"{p.name}:{n}" for p in sorted(IT.glob("run-*.sh"))
                for n, line in enumerate(p.read_text(errors="replace").splitlines(), 1)
                if re.match(r"^\s*export TMUX_TMPDIR=", line)]
        self.assertEqual(bare, [])
        movers = [p.name for p in sorted(IT.glob("run-*.sh")) if "it_move_tmux_tmpdir" in p.read_text(errors="replace")]
        self.assertEqual(movers, ["run-B.sh", "run-C.sh", "run-D.sh", "run-group3.sh"])

    def test_f9s_subshell_propagates_its_failure(self):
        """F9-zero-delta is written inside `( … )`; a FAIL there (or an OWN- row) must reach IT_FAILED."""
        text = (IT / "run-F.sh").read_text()
        self.assertRegex(text, r'F9-zero-delta fleet compaction-status --porcelain\n\s*exit "\$\{IT_FAILED:-0\}" \) \|\| IT_FAILED=1')

    def test_group5_claims_its_coverage_rows(self):
        """Found by the plan's pre-flight scan: run-group5.sh writes L7-coverage and M5-coverage."""
        text = (IT / "run-group5.sh").read_text()
        l_re = re.search(r'L\) own="\$own\|([^"]*)"', text).group(1)
        m_re = re.search(r'M\) own="\$own\|([^"]*)"', text).group(1)
        self.assertRegex("L7-coverage", "^(" + l_re + ")$")
        self.assertRegex("M5-coverage", "^(" + m_re + ")$")
        self.assertRegex("M8-release-history", "^(" + m_re + ")$")
        self.assertRegex("M11b", "^(" + m_re + ")$")


class ZeroDelta(unittest.TestCase):
    """FB-38. A zero delta over a verb that never ran (exit 2) is a control that cannot fail. RED:
    evidence/01-red/fb38-zero-delta-rc-base.txt (P-refused PASS on a status call that exited 2)."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="it-harness-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.it = harness_copy(self.tmp)
        self.results = self.tmp / "RESULTS.tsv"
        self.results.write_text("case\tverdict\tevidence\tnote\n")

    def run_lib(self, body):
        # TMUX_TMPDIR under the test's tmp: it_section's isolation check reads the "default" tmux server, and
        # a hermetic test must not read the operator's — this makes that server an empty private one.
        return run_bash(f'. "{self.it}/lib.sh"\nit_section zd >/dev/null 2>&1; it_fresh_store\n{body}',
                        self.tmp, env={"IT_RESULTS": str(self.results), "TMUX_TMPDIR": str(self.tmp)},
                        home=self.tmp / "home")

    def row(self, case):
        return next(l.split("\t") for l in self.results.read_text().splitlines()[1:] if l.startswith(case + "\t"))

    def test_no_subprocess_of_this_module_names_an_operator_tmux_socket(self):
        """clean_env: no FLEET_TMUX_SOCKET, no $TMUX, and TMUX_TMPDIR is this module's private dir — so the
        product's `-L <socket>` and any bare tmux resolve under it (found in review: the inherited
        FLEET_TMUX_SOCKET steered `board` at the operator's server)."""
        env = clean_env()
        self.assertNotIn("FLEET_TMUX_SOCKET", env)
        self.assertNotIn("TMUX", env)
        self.assertEqual(env["TMUX_TMPDIR"], PRIVATE_TMUX_DIR)
        self.assertNotEqual(PRIVATE_TMUX_DIR, tempfile.gettempdir())

    def test_the_default_tmux_server_these_tests_read_is_private(self):
        """it_section's isolation check runs a bare `tmux ls`. Under this class's env that must be an empty
        server of its own: TMUX_TMPDIR points into the tmp dir and $TMUX (which would override it inside a
        pane) is stripped. Found in review: with $TMUX set, TMUX_TMPDIR alone still reached the live server."""
        if shutil.which("tmux") is None:
            self.skipTest("tmux is not on PATH")
        out = subprocess.run(["tmux", "ls"], env=clean_env({"TMUX_TMPDIR": str(self.tmp)}),
                             capture_output=True, text=True)
        self.assertNotEqual(out.returncode, 0, f"a live server answered a bare tmux ls: {out.stdout[:200]}")
        self.assertNotIn("TMUX", clean_env())

    def test_a_refused_read_fails_even_with_a_zero_delta(self):
        self.run_lib("it_zero_delta P-refused fleet status --id 00000000-00000000-inflight-append-nosuch --porcelain")
        r = self.row("P-refused")
        self.assertEqual(r[1], "FAIL")
        self.assertIn("exited 2", r[3])

    def test_a_read_that_ran_and_changed_nothing_passes(self):
        self.run_lib("it_zero_delta P-control fleet board --porcelain")
        self.assertEqual(self.row("P-control")[1], "PASS")

    def test_want_names_a_deliberate_refusal(self):
        self.run_lib("it_zero_delta --want 2 P-want fleet status --id 00000000-00000000-inflight-append-nosuch --porcelain")
        self.assertEqual(self.row("P-want")[1], "PASS")

    def test_a_write_fails_on_the_delta_not_only_the_code(self):
        self.run_lib("it_zero_delta P-write fleet init --name zdprobe --base 00000000 --porcelain")
        r = self.row("P-write")
        self.assertEqual(r[1], "FAIL")
        self.assertIn("delta", r[3])


class F2bHolderPattern(unittest.TestCase):
    """FB-75. The refusal line names the held list AND, after a full stop, the population with the EXCLUDED
    subjects; F2b's pattern must match the real product's line and not the mutant's. Both lines are the
    measured ones (evidence/01-red/sectionF-{real,mutant}-base/F2b-dispatch.out)."""
    REAL = ("hold it: 00000000-09240005-inflight-append-capholder, 00000000-09240005-inflight-append-secondc. "
            "examined 2 subject(s) of 00000000; 2 counted, 0 excluded")
    MUTANT = ("hold it: 00000000-09240007-inflight-append-secondc. examined 2 subject(s) of 00000000; "
              "1 counted, 1 excluded (00000000-09240007-inflight-append-capholder (RUNNING))")

    #: V23-D (RV-C6). The holder text now carries `[folder …, session …, age …]`. REAL is the line measured by §F at
    #: fix/v23-d (v23dwipcapeffort evidence/05-it/real-refusal-lines.txt); MUTANT is the same shape with capholder
    #: only in the excluded list.
    REAL_V23D = ("hold it: 00000000-09242212-inflight-append-capholder [folder: yes, session: yes, age: 2s], "
                 "00000000-09242212-inflight-append-secondc [folder: yes, session: yes, age: 1s]. examined 2 "
                 "subject(s) of 00000000 in /it/F/instants; 2 counted, 0 excluded")
    MUTANT_V23D = ("hold it: 00000000-09242212-inflight-append-secondc [folder: yes, session: yes, age: 1s]. examined 2 "
                   "subject(s) of 00000000 in /it/F/instants; 1 counted, 1 excluded "
                   "(00000000-09242212-inflight-append-capholder (RUNNING))")

    def pattern(self):
        m = re.search(r"command grep -E '([^']+)' \"\$OUT/F2b-dispatch.out\"", (IT / "run-F.sh").read_text())
        self.assertIsNotNone(m, "F2b's holder grep is missing from run-F.sh")
        return m.group(1)

    def test_pattern_matches_the_real_refusal_and_not_the_mutants(self):
        pat = self.pattern()
        real = subprocess.run(["grep", "-E", pat], input=self.REAL + "\n", capture_output=True, text=True)
        mutant = subprocess.run(["grep", "-E", pat], input=self.MUTANT + "\n", capture_output=True, text=True)
        self.assertEqual(real.returncode, 0, pat)
        self.assertEqual(mutant.returncode, 1, f"{pat!r} still matches the mutant's refusal (capholder is only in the EXCLUDED list)")

    def test_pattern_matches_the_bracketed_holder_format_and_not_its_mutant(self):
        pat = self.pattern()
        real = subprocess.run(["grep", "-E", pat], input=self.REAL_V23D + "\n", capture_output=True, text=True)
        mutant = subprocess.run(["grep", "-E", pat], input=self.MUTANT_V23D + "\n", capture_output=True, text=True)
        self.assertEqual(real.returncode, 0, pat)
        self.assertEqual(mutant.returncode, 1, f"{pat!r} matches the bracketed mutant (capholder only EXCLUDED)")


class StdinImmunity(unittest.TestCase):
    """FB-99. A runner sourcing lib.sh must never block on its stdin: a bare command after a heredoc read the
    harness's pipe forever (J5). RED: evidence/01-red/fb99-stdin-base.txt (rc 124 under a pipe)."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="it-harness-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.it = harness_copy(self.tmp)
        (self.tmp / "inner.sh").write_text(
            f'. "{self.it}/lib.sh"\nx="$(python3 - <<\'PY\'\nprint("b")\nprint("a")\nPY\nsort)"\n'
            'echo "x=[$x] stdin=$(readlink /proc/$$/fd/0)"\n')

    def _with_open_pipe(self, argv):
        r, w = os.pipe()
        try:
            return subprocess.run(argv, cwd=self.tmp, env=clean_env(), stdin=r, capture_output=True,
                                  text=True, timeout=15)
        finally:
            os.close(r)
            os.close(w)

    def test_j5_shape_returns_with_an_open_pipe_on_stdin(self):
        out = self._with_open_pipe(["bash", str(self.tmp / "inner.sh")])
        self.assertIn("stdin=/dev/null", out.stdout)

    def test_an_interactive_shell_keeps_its_stdin(self):
        out = self._with_open_pipe(["bash", "--norc", "-i", "-c", f'. "{self.it}/lib.sh"; readlink /proc/$$/fd/0'])
        self.assertIn("pipe:", out.stdout)

    def test_j5_site_pipes_its_heredoc(self):
        text = (IT / "run-J.sh").read_text()
        self.assertNotRegex(text, r"\nPY\nsort\)\"",
                            "J5 still runs `sort` as a separate command reading the runner's stdin")
        self.assertIn("<<'PY' | sort", text)


class ServerGuardian(unittest.TestCase):
    """FB-73. A runner's EXIT trap cannot run when the shell tree is SIGKILLed (what TaskStop does); its
    private server must still go away. All socket names are unique to this process; the fallback cases
    create and clean up only their own same-named server under the real default directory. RED:
    evidence/01-red/fb73-kill9-base.txt (the server still up 10 s after kill -9)."""

    def setUp(self):
        if shutil.which("tmux") is None:
            self.skipTest("tmux is not on PATH, so the guardian cannot be exercised here")
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="it-harness-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.it = harness_copy(self.tmp)
        # A sandbox may map every test process to the same small PID. The default-dir regression
        # cases use a host-visible tmux socket, so its name must remain unique across pid namespaces.
        self.section = f"selftest{uuid.uuid4().hex[:10]}g"
        self.socket = f"itfleet-{self.section}"
        # Every tmux socket of this test — the section's private one AND the "default" server the isolation
        # check reads — lives under the test's tmp via TMUX_TMPDIR, so nothing here touches the operator's.
        self.env = clean_env({"TMUX_TMPDIR": str(self.tmp)}, home=self.tmp / "home")
        self.addCleanup(subprocess.run, ["tmux", "-L", self.socket, "kill-server"], capture_output=True,
                        env=self.env)

    def server_up(self):
        return subprocess.run(["tmux", "-L", self.socket, "ls"], capture_output=True, env=self.env).returncode == 0

    def start_runner(self):
        started = self.tmp / "started"
        script = (f'. "{self.it}/lib.sh"\nit_section {self.section} >/dev/null 2>&1\n'
                  f'it_tmux new-session -d -s {self.socket}-victim "sleep 300"\n'
                  f'touch "{started}"\nsleep 300 & echo $! > "{self.tmp}/sleep.pid"; wait\n')
        (self.tmp / "runner.sh").write_text(script)
        p = subprocess.Popen(["bash", str(self.tmp / "runner.sh")], cwd=self.tmp, env=self.env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (p.kill(), p.wait()))
        self.addCleanup(lambda: subprocess.run(
            ["bash", "-c", f'kill "$(cat "{self.tmp}/sleep.pid" 2>/dev/null)" 2>/dev/null; true']))
        for _ in range(100):
            if started.exists():
                break
            time.sleep(0.1)
        self.assertTrue(started.exists(), "runner did not reach its section")
        return p

    def test_server_is_reaped_after_the_runner_is_sigkilled(self):
        p = self.start_runner()
        self.assertTrue(self.server_up())
        p.kill()
        p.wait()
        for _ in range(100):          # the guardian polls every 2 s
            if not self.server_up():
                break
            time.sleep(0.1)
        self.assertFalse(self.server_up(), "private server survived its runner's SIGKILL")

    def test_server_is_not_reaped_while_the_runner_lives(self):
        self.start_runner()
        time.sleep(5)
        self.assertTrue(self.server_up())

    def test_server_moved_by_the_runner_is_still_reaped(self):
        """§B/§C/§D/group3 move their tmux directory AFTER it_section (through it_move_tmux_tmpdir); the
        guardian must reap the server where the runner put it, not a same-named one under the directory
        it inherited (found in review)."""
        moved = self.tmp / "moved"
        moved.mkdir()
        started = self.tmp / "started"
        script = (f'. "{self.it}/lib.sh"\nit_section {self.section} >/dev/null 2>&1\n'
                  f'it_move_tmux_tmpdir "{moved}"\n'
                  f'it_tmux new-session -d -s {self.socket}-victim "sleep 300"\n'
                  f'touch "{started}"\nsleep 300 & echo $! > "{self.tmp}/sleep.pid"; wait\n')
        (self.tmp / "runner.sh").write_text(script)
        p = subprocess.Popen(["bash", str(self.tmp / "runner.sh")], cwd=self.tmp, env=self.env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (p.kill(), p.wait()))
        self.addCleanup(lambda: subprocess.run(
            ["bash", "-c", f'kill "$(cat "{self.tmp}/sleep.pid" 2>/dev/null)" 2>/dev/null; true']))
        moved_env = dict(self.env, TMUX_TMPDIR=str(moved))
        self.addCleanup(subprocess.run, ["tmux", "-L", self.socket, "kill-server"], capture_output=True, env=moved_env)
        for _ in range(100):
            if started.exists():
                break
            time.sleep(0.1)
        self.assertTrue(started.exists())
        up = lambda: subprocess.run(["tmux", "-L", self.socket, "ls"], capture_output=True, env=moved_env).returncode == 0
        self.assertTrue(up(), "the moved server did not start")
        time.sleep(3)                 # the guardian re-armed by it_move_tmux_tmpdir has started polling
        p.kill()
        p.wait()
        for _ in range(100):
            if not up():
                break
            time.sleep(0.1)
        self.assertFalse(up(), "the server under the runner's own TMUX_TMPDIR survived its runner's SIGKILL")

    def test_a_back_to_back_rerun_keeps_its_server(self):
        """The first runner's guardian is inside its 2 s poll window when the second runner of the same
        section starts; it must not kill the second runner's server (found in review)."""
        p = self.start_runner()
        p.kill()
        p.wait()
        (self.tmp / "started").unlink()
        self.start_runner()               # immediately: within the old guardian's window
        time.sleep(6)                      # past that window
        self.assertTrue(self.server_up(), "the predecessor's guardian killed the successor's server")

    def _start_guarded_runner(self, armed_dir, runner_pid='"$$"'):
        started = self.tmp / "started"
        script = (f'. "{self.it}/lib.sh"\n'
                  f'export TMUX_TMPDIR="{armed_dir}"\n'
                  f'it_guard_server {runner_pid} "{self.socket}"\n'
                  f'touch "{started}"\n'
                  f'sleep 300 & echo $! > "{self.tmp}/sleep.pid"; wait\n')
        (self.tmp / "runner.sh").write_text(script)
        p = subprocess.Popen(["bash", str(self.tmp / "runner.sh")], cwd=self.tmp, env=self.env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (p.kill(), p.wait()))
        self.addCleanup(lambda: subprocess.run(
            ["bash", "-c", f'kill "$(cat "{self.tmp}/sleep.pid" 2>/dev/null)" 2>/dev/null; true'],
            capture_output=True))
        pidfile = self.it / ".guardians" / f"{self.socket}.pid"
        def stop_our_guardian():
            if pidfile.exists():
                try:
                    guardian_pid = int(pidfile.read_text().strip())
                    argv = pathlib.Path(f"/proc/{guardian_pid}/cmdline").read_bytes()
                    if f"it-guardian\0{self.socket}\0".encode() in argv:
                        os.kill(guardian_pid, 15)
                except (FileNotFoundError, ProcessLookupError, ValueError):
                    pass
        self.addCleanup(stop_our_guardian)
        for _ in range(100):
            if started.exists():
                break
            time.sleep(0.1)
        self.assertTrue(started.exists(), "guardian was not armed")
        return p

    def _default_server_up(self):
        env = dict(self.env)
        env.pop("TMUX_TMPDIR")
        return subprocess.run(["tmux", "-L", self.socket, "ls"], capture_output=True, env=env).returncode == 0

    def _assert_missing_armed_dir_preserves_default_server(self, move):
        armed = self.tmp / "armed"
        armed.mkdir()
        p = self._start_guarded_runner(armed)
        if move:
            armed.rename(self.tmp / "renamed")
        else:
            armed.rmdir()
        env = dict(self.env)
        env.pop("TMUX_TMPDIR")
        self.addCleanup(subprocess.run, ["tmux", "-L", self.socket, "kill-server"],
                        capture_output=True, env=env)
        started = subprocess.run(["tmux", "-L", self.socket, "new-session", "-d", "-s", "victim"],
                                 capture_output=True, env=env)
        self.assertEqual(started.returncode, 0, started.stderr)
        p.kill()
        p.wait()
        time.sleep(3)
        self.assertTrue(self._default_server_up(), "guardian killed a same-named default-dir server")

    def test_deleted_armed_directory_does_not_kill_default_server(self):
        self._assert_missing_armed_dir_preserves_default_server(move=False)

    def test_moved_armed_directory_does_not_kill_default_server(self):
        self._assert_missing_armed_dir_preserves_default_server(move=True)

    def test_foreign_namespace_pid_does_not_keep_guardian_alive(self):
        """PID 1 stands in for a runner PID that resolves to a different, still-live process."""
        p = self._start_guarded_runner(self.tmp, runner_pid="1")
        started = subprocess.run(["tmux", "-L", self.socket, "new-session", "-d", "-s", "victim"],
                                 capture_output=True, env=self.env)
        self.assertEqual(started.returncode, 0, started.stderr)
        p.kill()
        p.wait()
        for _ in range(100):
            if not self.server_up():
                break
            time.sleep(0.1)
        self.assertFalse(self.server_up(), "foreign PID kept the guardian waiting after runner exit")

    def test_rearm_does_not_signal_a_pidfile_impostor(self):
        """A numeric pid and matching argv in the pidfile cannot authorize a signal."""
        pidfile = self.it / ".guardians" / f"{self.socket}.pid"
        pidfile.parent.mkdir()
        impostor = subprocess.Popen(["bash", "-c", f'exec -a "it-guardian {self.socket} impostor" sleep 300'],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (impostor.kill(), impostor.wait()))
        pidfile.write_text(str(impostor.pid))
        time.sleep(0.1)
        runner = self._start_guarded_runner(self.tmp)
        self.assertIsNone(impostor.poll(), "rearm signalled a process identified only by pidfile and argv")
        runner.kill()
        runner.wait()

    def test_new_arm_in_another_harness_copy_keeps_its_server(self):
        """Two leased slots can run the same section on the same default socket directory."""
        peer_it = harness_copy(self.tmp / "peer")
        armed = self.tmp / "shared-sockets"
        armed.mkdir()
        env = dict(self.env, TMUX_TMPDIR=str(armed))
        self.addCleanup(subprocess.run, ["tmux", "-L", self.socket, "kill-server"],
                        capture_output=True, env=env)

        def runner(it, label):
            ready = self.tmp / f"{label}.ready"
            sleeper = self.tmp / f"{label}.sleep.pid"
            script = (f'. "{it}/lib.sh"\n'
                      f'it_guard_server "$$" "{self.socket}"\n'
                      f'touch "{ready}"\n'
                      f'sleep 300 & echo $! > "{sleeper}"; wait\n')
            proc = subprocess.Popen(["bash", "-c", script], cwd=self.tmp, env=env,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            self.addCleanup(lambda: (proc.kill(), proc.wait()))
            self.addCleanup(lambda: subprocess.run(
                ["bash", "-c", f'kill "$(cat "{sleeper}" 2>/dev/null)" 2>/dev/null; true'],
                capture_output=True))
            for _ in range(100):
                if ready.exists():
                    break
                time.sleep(0.1)
            self.assertTrue(ready.exists(), f"{label} did not arm")
            return proc

        first = runner(self.it, "first")
        started = subprocess.run(["tmux", "-L", self.socket, "new-session", "-d", "-s", "victim"],
                                 capture_output=True, env=env)
        self.assertEqual(started.returncode, 0, started.stderr)
        second = runner(peer_it, "second")
        first.kill()
        first.wait()
        time.sleep(3)
        self.assertIsNone(second.poll(), "second runner did not remain alive")
        self.assertEqual(subprocess.run(["tmux", "-L", self.socket, "ls"],
                                        capture_output=True, env=env).returncode, 0,
                         "first copy's guardian killed the second copy's server")

    def test_command_substitution_cannot_arm_a_guardian(self):
        started = subprocess.run(["tmux", "-L", self.socket, "new-session", "-d", "-s", "victim"],
                                 capture_output=True, env=self.env)
        self.assertEqual(started.returncode, 0, started.stderr)
        script = (f'. "{self.it}/lib.sh"\n'
                  f'x=$(it_guard_server "$$" "{self.socket}"; sleep 0.5)\n'
                  f'echo "$x" >/dev/null\n')
        result = subprocess.run(["bash", "-c", script], capture_output=True, env=self.env,
                                cwd=self.tmp)
        self.assertIn(b"call from the runner's top-level shell", result.stderr)
        time.sleep(3)
        self.assertTrue(self.server_up(), "subshell guardian killed the live server")


if __name__ == "__main__":
    unittest.main()
