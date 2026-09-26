"""The IT harness as an instrument (B18 / B25 / FB-37 / FB-38 / FB-73 / FB-75 / FB-76 / FB-99).

Hermetic: a throwaway `fleet/it` holding only lib.sh, facts.env and bin/, with src/ symlinked, run from a tmp
cwd with every FLEET_* destination unset. Nothing here reads or writes the live store, the default tmux
server or the tracked RESULTS.tsv. Each class names the defect it pins and the RED it was written against
(the w2itharness instant's evidence/01-red/).
"""
import tests  # noqa: F401 — installs the suite's host boundary when this module runs alone (FB-118)
import atexit
import fcntl
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

REPO = pathlib.Path(__file__).resolve().parents[2]
IT = REPO / "fleet" / "it"
FLEET_DESTINATIONS = ("FLEET_HOME", "FLEET_INSTANTS", "FLEET_ROOT", "FLEET_INSTANT", "FLEET_RELEASES",
                      "FLEET_TMUX_SOCKET",              # the product's `-L`: inherited, it names the operator's server
                      "IT_ASKED_NAMES", "IT_RESULTS", "IT_TMUX_REAL",  # an IT section runs this suite (M13)
                      "TMUX", "TMUX_PANE")              # a bare `tmux` inside a pane follows $TMUX, not TMUX_TMPDIR
#: One private tmux directory per test process for ordinary cases. ServerGuardian's missing-directory
#: regression cases start no server outside it: they observe, through the suite's tripwire (FB-118), that the
#: guardian makes no tmux call aimed at the box's default directory (S5 glue, v23-l x v23-n).
#: (`tempfile.gettempdir()` would be /tmp, which IS tmux's default — found in review.)
PRIVATE_TMUX_DIR = tempfile.mkdtemp(prefix="itf-", dir="/tmp")
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
    env = {k: v for k, v in os.environ.items()
           if k not in FLEET_DESTINATIONS and not k.startswith("IT_TMUX_AUDIT_")}
    env["PATH"] = tests._ambient_path()
    env["TMUX_TMPDIR"] = PRIVATE_TMUX_DIR
    if home is not None:
        env["HOME"] = str(home)
    env.update(extra or {})
    return env


def run_bash(script: str, cwd: pathlib.Path, env=None, stdin=subprocess.DEVNULL, timeout=120, home=None):
    return subprocess.run(["bash", "-c", script], cwd=cwd, env=clean_env(env, home=home), stdin=stdin,
                          capture_output=True, text=True, timeout=timeout)


class LiveStoreSnapshot(unittest.TestCase):
    """A prior lessee's ignored snapshot must not become this run's baseline."""

    def test_per_run_snapshot_is_gitignored(self):
        #: S6 (0.6.16 gate, coordinator D-141). Asked of the REPO's own .gitignore in a scratch git repo: the gate runs
        #: this suite in the release export, which has no .git, and `git -C <export> check-ignore` answered 128 there.
        #: RV-33/RV-39: only the repo's own rule may answer — a global core.excludesFile, or git's DEFAULT excludes file
        #: ($XDG_CONFIG_HOME/git/ignore, ~/.config/git/ignore), listing *.sha256 made the positive assert pass without it, and an
        #: inherited GIT_DIR/GIT_WORK_TREE would redirect the scratch repo. No global/system config, no excludes file, no GIT_*.
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_COUNT="1",
                   GIT_CONFIG_KEY_0="core.excludesFile", GIT_CONFIG_VALUE_0="/dev/null")
        with tempfile.TemporaryDirectory(prefix="itf-ignore-", dir="/tmp") as tmp_name:
            tmp = pathlib.Path(tmp_name)
            subprocess.run(["git", "init", "-q", str(tmp)], check=True, capture_output=True, env=env)
            shutil.copyfile(REPO / ".gitignore", tmp / ".gitignore")
            candidate = "fleet/it/live-stores-run-example.sha256"
            result = subprocess.run(["git", "-C", str(tmp), "check-ignore", "-q", candidate], capture_output=True, env=env)
            self.assertEqual(result.returncode, 0, "a normal IT run dirties the slot with a snapshot")
            control = subprocess.run(["git", "-C", str(tmp), "check-ignore", "-q", "fleet/it/run-A.sh"], capture_output=True,
                                     env=env)
            self.assertEqual(control.returncode, 1, "the check must be able to say NOT ignored (a runner is tracked)")

    def test_stale_snapshot_is_not_compared_on_new_run(self):
        with tempfile.TemporaryDirectory(prefix="itf-", dir="/tmp") as tmp_name:
            tmp = pathlib.Path(tmp_name)
            it = harness_copy(tmp)
            (it / "live-stores.sha256").write_text("stale prior lessee\n")
            result = run_bash(f'. "{it}/lib.sh"\nit_section SNAP\nprintf "snapshot=%s\\n" '
                              '"$LIVE_SNAPSHOT"', tmp,
                              env={"IT_RESULTS": str(tmp / "results.tsv")}, home=tmp / "home")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("THE LIVE STORES CHANGED", (tmp / "results.tsv").read_text())
            self.assertNotEqual((it / "live-stores.sha256").resolve(),
                                pathlib.Path(result.stdout.split("snapshot=")[-1].strip()).resolve())


class MFixtureLifetime(unittest.TestCase):
    """The §M pane fixture lives until the section tears its server down."""

    def test_m_worker_does_not_expire_when_sleep_returns(self):
        source = (IT / "run-group5.sh").read_text()
        line = next(line for line in source.splitlines()
                    if line.strip().startswith('it_tmux_new "itfleet-M-worker" '))
        with tempfile.TemporaryDirectory(prefix="itf-", dir="/tmp") as tmp_name:
            tmp = pathlib.Path(tmp_name)
            sleep = tmp / "sleep"
            sleep.write_text("#!/bin/sh\nexit 0\n")
            sleep.chmod(0o755)
            extract = subprocess.run(["bash", "-c", 'it_tmux_new() { printf "%s" "$2"; }; ' + line],
                                     capture_output=True, text=True, check=True)
            env = clean_env({"PATH": f"{tmp}:{os.environ['PATH']}"})
            fixture = subprocess.Popen(["sh", "-c", extract.stdout], env=env, start_new_session=True,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
            try:
                time.sleep(0.3)
                self.assertIsNone(fixture.poll(), "§M fixture ended before section teardown")
            finally:
                try:
                    os.killpg(fixture.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                fixture.wait(timeout=5)


class WrapperExecutable(unittest.TestCase):
    """B18. The wrapper must be reachable from the harness's own idioms — `timeout`, `env -u`, `exec` — which
    cannot invoke a bash function, and it must be the harness's one SUBPROCESS route to the product. RED:
    evidence/01-red/b18-classifier-bypass-base.txt (a bypassed mint charged to the operator, PASS) beside
    b18-classifier-wrapped-base.txt (the same mint through the wrapper, FAIL)."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="itf-", dir="/tmp"))
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
        #: `leases`, not `board` (FB-118, D-4 of v23-n): `board` counts the HOST's processes even on an empty
        #: store, so two back-to-back runs read 7 and 8 subjects with nothing changed in fleet. Pass-through is
        #: the property here, and it needs a verb whose output this case owns.
        for argv in (["notaverb", "--porcelain"], ["init", "--help"],
                     ["leases", "--home", str(self.tmp / "store"), "--porcelain"]):
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
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="itf-", dir="/tmp"))
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


class HarnessTmuxBoundary(unittest.TestCase):
    """FB-118 (v23-k OI-4). `lib.sh` is sourced from worker panes, where `$TMUX` names the live fleet server, and its
    live-session reads were a bare `tmux ls`, which follows `$TMUX`: §OR run 1 baselined fleet-davis's `dt-`
    sessions that way. Here a decoy server this case creates stands in for the pane's, so even the RED run
    reads nothing but the decoy. RED: evidence/01-red/it-harness-tmux-at-base.out."""

    def setUp(self):
        if shutil.which("tmux") is None:
            self.skipTest("tmux is not on PATH")
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="itf-", dir="/tmp"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.it = harness_copy(self.tmp)
        self.decoy = self.tmp / "pane-server"
        self.tmpdir = self.tmp / "tmuxdir"
        self.default = self.tmpdir / f"tmux-{os.getuid()}" / "default"
        for sock, name in ((self.decoy, "dt-decoy-live"), (self.default, "leaked-here")):
            sock.parent.mkdir(parents=True, exist_ok=True)
            sock.parent.chmod(0o700)            # tmux refuses a `-L` socket directory any looser than this
            made = subprocess.run(["tmux", "-S", str(sock), "new-session", "-d", "-s", name],
                                  capture_output=True, text=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            self.addCleanup(subprocess.run, ["tmux", "-S", str(sock), "kill-server"], capture_output=True)

    def lib(self, body):
        return run_bash(f'. "{self.it}/lib.sh"\n{body}', self.tmp,
                        env={"TMUX": f"{self.decoy},1,0", "TMUX_PANE": "%9", "TMUX_TMPDIR": str(self.tmpdir)},
                        home=self.tmp / "home")

    def test_sourcing_lib_sh_strips_the_callers_tmux_handles(self):
        out = self.lib('printf "%s|%s\\n" "${TMUX-unset}" "${TMUX_PANE-unset}"')
        self.assertEqual(out.stdout.strip(), "unset|unset", out.stderr)

    def test_the_live_session_read_never_follows_the_callers_TMUX(self):
        out = self.lib("it_live_tmux_sessions")
        self.assertNotIn("dt-decoy-live", out.stdout, "it_live_tmux_sessions read the server $TMUX names")

    def test_the_live_session_read_names_its_server_even_if_TMUX_comes_back(self):
        """The read names `-L default` rather than trusting the `unset` above it: a runner that exports `$TMUX`
        again after sourcing lib.sh must not redirect the isolation check to that server."""
        out = self.lib(f'export TMUX="{self.decoy},1,0"\nit_live_tmux_sessions')
        self.assertEqual(out.stdout.split(), ["leaked-here"], out.stderr)

    def test_the_live_session_read_still_watches_where_a_socketless_call_lands(self):
        """The control: stripping $TMUX must not blind the check. A socket-less tmux call from a section lands on
        `default` under TMUX_TMPDIR, and that is the server the read must still see."""
        out = self.lib("it_live_tmux_sessions")
        self.assertEqual(out.stdout.split(), ["leaked-here"], out.stderr)


class ZeroDelta(unittest.TestCase):
    """FB-38. A zero delta over a verb that never ran (exit 2) is a control that cannot fail. RED:
    evidence/01-red/fb38-zero-delta-rc-base.txt (P-refused PASS on a status call that exited 2)."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="itf-", dir="/tmp"))
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
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="itf-", dir="/tmp"))
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


class A8KillSiteAudit(unittest.TestCase):
    """FB-119. run-A's A8a audit lexes each shell line and masks string literals before looking for
    `tmux … kill-server`, so a kill issued from code INSIDE a string — a multi-line `python3 -c '…'`, a
    `bash -c "…"`, a heredoc body — was neither counted nor judged. And it accepted only `tmux -L`/`it_tmux`,
    so the safe absolute-path `tmux -S <dir>/tmux-<uid>/<sock>` that v23-l's guardian uses read as unsafe.
    The audit is lifted out of run-A.sh exactly as run-A writes it, and run over fixture harness files."""

    ANCHOR = 'cat > "$PY_DIR/a8audit.py" <<\'PY\'\n'

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="itf-", dir="/tmp"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        src = pathlib.Path(os.environ.get("A8_AUDIT_SOURCE", IT / "run-A.sh")).read_text()
        self.assertEqual(src.count(self.ANCHOR), 1, "the A8 audit block is not uniquely anchored in run-A.sh")
        body = src.split(self.ANCHOR, 1)[1].split("\nPY\n", 1)[0]
        (self.tmp / "a8audit.py").write_text(body + "\n")

    def audit(self, **files):
        paths = []
        for name, text in files.items():
            (self.tmp / name).write_text(text)
            paths.append(str(self.tmp / name))
        done = subprocess.run([sys.executable, str(self.tmp / "a8audit.py"), *paths], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        counts = json.loads(next(l for l in done.stdout.splitlines() if l.startswith("COUNTS "))[7:])
        return counts, done.stdout

    V23L_GUARDIAN = (
        "it_guard_server() {\n"
        "  python3 -c '\n"
        "import os, subprocess, sys\n"
        "sock, directory = sys.argv[1:3]\n"
        "subprocess.run([\"tmux\", \"-S\", os.path.join(directory, \"tmux-\" + str(os.getuid()), sock), \"kill-server\"],\n"
        "               stdin=subprocess.DEVNULL)\n"
        "  ' it-guardian \"$sock\" \"$dir\" &\n"
        "}\n")

    def test_a_python_embedded_absolute_S_kill_is_counted_and_safe(self):
        counts, out = self.audit(**{"run-X.sh": self.V23L_GUARDIAN})
        self.assertEqual(counts["kill_all"], 1, out)
        self.assertEqual(counts["kill_unsafe"], 0, out)

    def test_an_embedded_default_socket_kill_is_flagged(self):
        for label, text in {
            "python -c list": "python3 -c 'import subprocess; subprocess.run([\"tmux\", \"kill-server\"])'\n",
            "bash -c string": "bash -c \"tmux kill-server\"\n",
            "heredoc body": "python3 - <<'PY'\nimport subprocess\nsubprocess.run(['tmux', 'kill-session', '-t', 'x'])\nPY\n",
            "-L default": "tmux -L default kill-server\n",
            "CL-1 shell: an earlier tmux names a socket, the killing one does not":
                "tmux -L priv has-session -t x && tmux kill-server\n",
            "CL-1 embedded: same, inside python":
                "python3 -c 'import subprocess; subprocess.run([\"tmux\", \"-L\", \"x\", \"ls\"]); subprocess.run([\"tmux\", \"kill-server\"])'\n",
        }.items():
            with self.subTest(label):
                counts, out = self.audit(**{"run-X.sh": text})
                self.assertEqual((counts["kill_all"], counts["kill_unsafe"]), (1, 1), out)

    def test_S_is_accepted_only_with_an_absolute_private_path(self):
        for label, (text, unsafe) in {
            "absolute literal": ("tmux -S /var/tmp/it/sock kill-server\n", 0),
            "variable-rooted": ("tmux -S \"$DECOY_DIR/tmux-1000/d\" kill-server\n", 0),
            "relative literal": ("tmux -S sock kill-server\n", 1),
            "the operator's directory": ("tmux -S /tmp/tmux-1000/fleet-davis kill-server\n", 1),
            "CL-2 doubled slash": ("tmux -S /tmp//tmux-1000/default kill-server\n", 1),
            "CL-2 dot-dot respelling": ("tmux -S /var/../tmp/tmux-1000/default kill-server\n", 1),
            "CL-2 empty -L": ("tmux -L \"\" kill-server\n", 1),
            "CL2-3 variable-rooted socket named .../tmux": ("tmux -S \"$IT_DIR/tmux\" kill-server\n", 0),
            "CL2-3 absolute socket named .../tmux": ("tmux -S /var/tmp/x/tmux kill-server\n", 0),
            "CL2-3 clustered -uS .../tmux": ("tmux -uS /var/tmp/x/tmux kill-server\n", 0),
            "python relative": ("python3 -c 'import subprocess; subprocess.run([\"tmux\", \"-S\", \"sock\", \"kill-server\"])'\n", 1),
        }.items():
            with self.subTest(label):
                counts, out = self.audit(**{"run-X.sh": text})
                self.assertEqual((counts["kill_all"], counts["kill_unsafe"]), (1, unsafe), out)

    def test_a_call_split_across_lines_is_a_stated_limit_not_a_silent_pass(self):
        """The CL-3 join was reverted (coordinator D-82) after it opened new gaps; a kill whose argv list continues on the
        next line is not seen (ISSUES I-11). Pinned here so the limit cannot change unnoticed in either direction."""
        counts, out = self.audit(**{"run-X.sh": "python3 - <<'PY'\nimport subprocess\nsubprocess.run([\"tmux\",\n"
                                                "                \"kill-server\"])\nPY\n"})
        self.assertEqual((counts["kill_all"], counts["kill_unsafe"]), (0, 0), out)

    def test_held_text_is_judged_at_every_reset_and_at_end_of_file(self):
        """CL2-1's shapes (a kill on a line with an unbalanced bracket, at a heredoc end, at end of file, before a shell
        kill line). With the CL-3 join reverted each line is judged as it stands, so none of them is dropped."""
        held = 'subprocess.run([\"tmux\", \"kill-server\"]); print(\"(\")'
        for label, (text, want) in {
            "heredoc end": (f"python3 - <<'PY'\nimport subprocess\n{held.replace(chr(92), '')}\nPY\n", (1, 1)),
            "end of file": (f"python3 -c 'import subprocess; {held}'", (1, 1)),
            "before a shell-level kill line": (f"python3 -c 'import subprocess; {held}'\ntmux -L priv kill-server\n",
                                               (2, 1)),
        }.items():
            with self.subTest(label):
                counts, out = self.audit(**{"run-X.sh": text})
                self.assertEqual((counts["kill_all"], counts["kill_unsafe"]), want, out)

    def test_every_kill_on_a_line_is_judged_against_its_own_tmux(self):
        """CL2-2. Only the first kill word on a line (or joined call) was judged, so a private kill followed by a bare one
        passed. Each kill is a site of its own, judged against the nearest tmux before it."""
        for label, text in {
            "shell ;": "tmux -L x kill-session -t a; tmux kill-server\n",
            "shell &&": "tmux -L x kill-server && tmux kill-session -t y\n",
            "shell, no spaces around ;": "tmux -L x kill-session -t a;tmux kill-server;\n",
            "embedded, one line": ("python3 - <<'PY'\nimport subprocess\nsubprocess.run([\"tmux\", \"-L\", \"x\", "
                                   "\"kill-server\"]); subprocess.run([\"tmux\", \"kill-server\"])\nPY\n"),
        }.items():
            with self.subTest(label):
                counts, out = self.audit(**{"run-X.sh": text})
                self.assertEqual((counts["kill_all"], counts["kill_unsafe"]), (2, 1), out)

    def test_bash_c_operand_does_not_hide_a_later_tmux_kill(self):
        counts, out = self.audit(**{"run-X.sh":
            'tmux -L x has-session -t s && bash -c "tmux kill-server"\n'})
        self.assertEqual((counts["kill_all"], counts["kill_unsafe"]), (1, 1), out)

    def test_bash_c_inside_command_substitution_does_not_hide_kill(self):
        for text in ('tmux -L x has-session -t s $(bash -c "tmux kill-server")\n',
                     'tmux -L x has-session -t s "$(bash -c \'tmux kill-server\')"\n'):
            with self.subTest(text=text):
                counts, out = self.audit(**{"run-X.sh": text})
                self.assertEqual((counts["kill_all"], counts["kill_unsafe"]), (1, 1), out)

    def test_any_program_c_does_not_borrow_tmux_option_scope(self):
        counts, out = self.audit(**{"run-X.sh":
            'tmux -L x has-session -t s $(fish -c "tmux kill-server")\n'})
        self.assertEqual((counts["kill_all"], counts["kill_unsafe"]), (1, 1), out)
        counts, out = self.audit(**{"run-X.sh": 'tmux -L x -c tmux kill-server\n'})
        self.assertEqual((counts["kill_all"], counts["kill_unsafe"]), (1, 0), out)

    def test_colon_before_kill_word_fails_closed_without_crashing(self):
        counts, out = self.audit(**{"run-X.sh": 'bash -c "tmux a:kill-server"\n'})
        self.assertEqual((counts["kill_all"], counts["kill_unsafe"]), (1, 1), out)

    def test_prose_and_the_audits_own_patterns_are_not_sites(self):
        text = ("# the guardian runs `tmux kill-server` on its socket\n"
                "echo 'never a bare tmux kill-server here'\n"
                "python3 - <<'PY'\nKILL = re.compile(r\"tmux[^;&|]*kill-(server|session)\")\n"
                "# a comment: tmux kill-server\nPY\n")
        counts, out = self.audit(**{"run-X.sh": text})
        self.assertEqual(counts["kill_all"], 0, out)

    def test_the_A8a_notes_carry_no_path_the_register_check_reads_as_leaked(self):
        """CL2-5. run-A's last check fails the RUNNER (exit 1) on any absolute /tmp|/home|/var|/root path in its register,
        and FB-119's A8a pass note said `outside /tmp/tmux-<uid>` — every §A run since exited 1 with every row PASS."""
        leaked = re.compile(r"""(^|[\s"'(])/(tmp|home|var|root)/""")
        notes = [line for line in (IT / "run-A.sh").read_text().splitlines() if re.search(r"a_(pass|fail) A8a\b", line)]
        self.assertEqual(len(notes), 2, notes)
        for line in notes:
            self.assertIsNone(leaked.search(line), line[:200])

    def test_the_real_harness_has_no_unsafe_kill_site(self):
        files = [str(IT / "lib.sh")] + sorted(str(p) for p in IT.glob("run-*.sh"))
        done = subprocess.run([sys.executable, str(self.tmp / "a8audit.py"), *files], capture_output=True, text=True)
        counts = json.loads(next(l for l in done.stdout.splitlines() if l.startswith("COUNTS "))[7:])
        self.assertEqual(counts["kill_unsafe"], 0, done.stdout)
        self.assertGreater(counts["kill_all"], 0, done.stdout)


class RuntimeTmuxKillAudit(unittest.TestCase):
    """The PATH command must refuse dangerous kills before invoking real tmux."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="it-kill-audit-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.private = self.tmp / "private"
        self.private.mkdir()
        self.ledger = self.tmp / "calls.jsonl"
        self.real = shutil.which("tmux", path=os.environ.get("FLEET_SUITE_AMBIENT_PATH", os.environ["PATH"]))
        self.assertTrue(self.real)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("IT_TMUX_AUDIT_")}
        self.env.update(IT_TMUX_AUDIT_LEDGER=str(self.ledger),
                        IT_TMUX_AUDIT_PRIVATE_DIRS=str(self.private), IT_TMUX_REAL=self.real,
                        TMUX_TMPDIR=str(self.private), TMUX="")
        self.shim = pathlib.Path(os.environ.get("IT_TMUX_AUDIT_SHIM", IT / "bin" / "tmux"))
        self.assertTrue(self.shim.is_file(), "runtime tmux audit shim is missing")

    def tmux(self, *args, env=None):
        return subprocess.run([str(self.shim), *args], env=env or self.env, text=True, capture_output=True)

    def recording_tmux(self):
        """A fake real-tmux that records argv and never contacts a tmux server."""
        fake = self.tmp / "recording-tmux"
        calls = self.tmp / "recorded-argv.jsonl"
        fake.write_text('#!/usr/bin/env python3\nimport json, os, sys, time\n'
                        'with open(os.environ["FAKE_TMUX_RECORD"], "a") as f:\n'
                        '    f.write(json.dumps(sys.argv[1:]) + "\\n")\n'
                        'if os.environ.get("FAKE_TMUX_SLOW_COMMAND") in sys.argv[1:]: time.sleep(2)\n')
        fake.chmod(0o755)
        return dict(self.env, IT_TMUX_REAL=str(fake), FAKE_TMUX_RECORD=str(calls)), calls

    def stateful_recording_tmux(self):
        """A fake real-tmux with a socket lifecycle; it never invokes tmux."""
        env, calls = self.recording_tmux()
        fake = self.tmp / "stateful-tmux"
        fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
if args[0] == '-S':
    socket, command, rest = pathlib.Path(args[1]), args[2], args[3:]
else:
    socket = pathlib.Path(os.environ['TMUX_TMPDIR']) / ('tmux-' + str(os.getuid())) / args[1]
    command, rest = args[2], args[3:]
if command == 'display-message':
    stale = os.environ.get('FAKE_TMUX_STALE_MARKER')
    if stale and not pathlib.Path(stale).exists(): sys.exit(1)
    if socket.exists(): print('777'); sys.exit(0)
    sys.exit(1)
if command == 'list-sessions':
    session = os.environ.get('FAKE_TMUX_SESSION_MARKER')
    if socket.exists():
        if not session or pathlib.Path(session).exists(): print('mine\\t$1')
        sys.exit(0)
    sys.exit(1)
with open(os.environ['FAKE_TMUX_RECORD'], 'a') as out:
    out.write(json.dumps(args) + '\\n')
if command == 'new-session':
    socket.parent.mkdir(parents=True, exist_ok=True)
    socket.touch()
    if os.environ.get('FAKE_TMUX_STALE_MARKER'):
        pathlib.Path(os.environ['FAKE_TMUX_STALE_MARKER']).touch()
    if os.environ.get('FAKE_TMUX_SESSION_MARKER'):
        pathlib.Path(os.environ['FAKE_TMUX_SESSION_MARKER']).touch()
    sys.exit(0)
if command == 'kill-session':
    session = os.environ.get('FAKE_TMUX_SESSION_MARKER')
    if session and pathlib.Path(session).exists():
        pathlib.Path(session).unlink()
        sys.exit(0)
    sys.exit(1)
if command == 'kill-server':
    if socket.exists():
        if os.environ.get('FAKE_TMUX_LEAVE_STALE'):
            stale = os.environ.get('FAKE_TMUX_STALE_MARKER')
            if stale and pathlib.Path(stale).exists(): pathlib.Path(stale).unlink()
        else:
            socket.unlink()
        sys.exit(0)
    sys.exit(1)
sys.exit(0)
''')
        fake.chmod(0o755)
        return dict(env, IT_TMUX_REAL=str(fake)), calls

    def test_repeat_owned_server_kill_is_noop_and_row_stays_pass(self):
        env, calls = self.stateful_recording_tmux()
        results = self.tmp / "results.tsv"
        results.write_text("case\tverdict\tevidence\tnote\n"
                           "KILL-AUDIT-X\tPASS\tfleet/it/X/tmux-audit.jsonl\t0 kill(s): (none)\n")
        env.update(IT_TMUX_AUDIT_RESULTS=str(results), IT_TMUX_AUDIT_SECTION="X")
        self.assertEqual(self.tmux("-L", "own", "new-session", "-d", "-s", "mine", env=env).returncode, 0)
        self.assertEqual(self.tmux("-L", "own", "kill-server", env=env).returncode, 0)
        first_count = len(calls.read_text().splitlines())
        repeated = self.tmux("-L", "own", "kill-server", env=env)
        self.assertEqual(repeated.returncode, 1, repeated.stderr)
        self.assertEqual(len(calls.read_text().splitlines()), first_count)
        self.assertIn("KILL-AUDIT-X\tPASS", results.read_text())
        rows = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertEqual(rows[-1]["decision"], "noop")

    def test_section_can_replace_its_own_stale_unanswered_socket(self):
        env, calls = self.stateful_recording_tmux()
        socket = self.private / f"tmux-{os.getuid()}" / "own"
        socket.parent.mkdir()
        socket.touch()
        inode = [socket.stat().st_dev, socket.stat().st_ino]
        self.ledger.write_text(json.dumps({"socket": str(socket), "created": True,
                                           "socket_inode": inode, "server_pid": "777",
                                           "session_ids": {}}) + "\n")
        env["FAKE_TMUX_STALE_MARKER"] = str(self.tmp / "server-alive")
        made = self.tmux("-L", "own", "new-session", "-d", "-s", "mine", env=env)
        self.assertEqual(made.returncode, 0, made.stderr)
        rows = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertTrue(rows[-1].get("created"), rows[-1])
        self.assertEqual(self.tmux("-L", "own", "kill-server", env=env).returncode, 0)
        self.assertEqual(json.loads(calls.read_text().splitlines()[-1])[-1], "kill-server")

    def test_repeat_owned_exact_session_kill_is_noop(self):
        env, calls = self.stateful_recording_tmux()
        env["FAKE_TMUX_SESSION_MARKER"] = str(self.tmp / "session-alive")
        results = self.tmp / "results.tsv"
        results.write_text("case\tverdict\tevidence\tnote\n"
                           "KILL-AUDIT-X\tPASS\tfleet/it/X/tmux-audit.jsonl\t0 kill(s): (none)\n")
        env.update(IT_TMUX_AUDIT_RESULTS=str(results), IT_TMUX_AUDIT_SECTION="X")
        self.assertEqual(self.tmux("-L", "own", "new-session", "-d", "-s", "mine", env=env).returncode, 0)
        self.assertEqual(self.tmux("-L", "own", "kill-session", "-t", "=mine", env=env).returncode, 0)
        count = len(calls.read_text().splitlines())
        repeated = self.tmux("-L", "own", "kill-session", "-t", "=mine", env=env)
        self.assertEqual(repeated.returncode, 1, repeated.stderr)
        self.assertEqual(len(calls.read_text().splitlines()), count)
        self.assertIn("KILL-AUDIT-X\tPASS", results.read_text())
        rows = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertEqual(rows[-1]["decision"], "noop")

    def test_repeat_server_kill_with_stale_socket_is_noop(self):
        env, calls = self.stateful_recording_tmux()
        env.update(FAKE_TMUX_STALE_MARKER=str(self.tmp / "server-alive"), FAKE_TMUX_LEAVE_STALE="1")
        results = self.tmp / "results.tsv"
        results.write_text("case\tverdict\tevidence\tnote\n"
                           "KILL-AUDIT-X\tPASS\tfleet/it/X/tmux-audit.jsonl\t0 kill(s): (none)\n")
        env.update(IT_TMUX_AUDIT_RESULTS=str(results), IT_TMUX_AUDIT_SECTION="X")
        self.assertEqual(self.tmux("-L", "own", "new-session", "-d", "-s", "mine", env=env).returncode, 0)
        self.assertEqual(self.tmux("-L", "own", "kill-server", env=env).returncode, 0)
        count = len(calls.read_text().splitlines())
        repeated = self.tmux("-L", "own", "kill-server", env=env)
        self.assertEqual(repeated.returncode, 1, repeated.stderr)
        self.assertEqual(len(calls.read_text().splitlines()), count)
        self.assertIn("KILL-AUDIT-X\tPASS", results.read_text())
        rows = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertEqual(rows[-1]["decision"], "noop")

    def test_nonprivate_socket_passes_only_explicit_reads(self):
        env, calls = self.recording_tmux()
        for command in (("kill-pane", "-a"), ("kill-window",), ("respawn-pane", "-k"),
                        ("send-keys", "C-c"), ("set-option", "-s", "command-alias[99]", "zz=kill-server"),
                        ("zz",), ("new-window",), ("display-message", "hello"),
                        ("capture-pane", "-S", "-100")):
            with self.subTest(command=command):
                self.assertEqual(self.tmux("-L", "default", *command, env=env).returncode, 97)
        self.assertFalse(calls.exists(), "a non-read reached fake real-tmux")
        for command in (("has-session",), ("list-sessions",), ("show-options",),
                        ("display-message", "-p", "#{pid}"), ("capture-pane", "-p")):
            with self.subTest(command=command):
                self.assertEqual(self.tmux("-L", "default", *command, env=env).returncode, 0)

    def test_display_alias_is_a_read_and_not_a_dispatcher(self):
        env, calls = self.recording_tmux()
        result = self.tmux("-L", "own", "display", "-p", "#{pane_current_path}", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(["-L", "own", "display", "-p", "#{pane_current_path}"],
                      [json.loads(line) for line in calls.read_text().splitlines()])

    def test_popup_and_menu_aliases_cannot_dispatch_commands(self):
        env, calls = self.recording_tmux()
        for alias, argument in (("popup", "printf should-not-run"),
                                ("menu", "kill-server")):
            with self.subTest(alias=alias):
                result = self.tmux("-L", "own", alias, "-E", argument, env=env)
                self.assertEqual(result.returncode, 97, result.stderr)
        self.assertFalse(calls.exists(), "a dispatcher alias reached fake real-tmux")

    def test_audit_summary_counts_a_refused_nonkill_command(self):
        tmp = self.tmp / "audit-summary"
        it = harness_copy(tmp)
        ledger = self.tmp / "nonkill.jsonl"
        ledger.write_text(json.dumps({"command": "display", "socket": str(self.private / "own"),
                                      "target": None, "decision": "deny"}) + "\n")
        results = self.tmp / "summary.tsv"
        results.write_text("case\tverdict\tevidence\tnote\n")
        script = (f'. "{it}/lib.sh"\n'
                  f'SECTION=X RESULTS="{results}" IT_TMUX_AUDIT_LEDGER="{ledger}" IT_FAILED=0\n'
                  f'it_kill_audit_result\n')
        completed = run_bash(script, tmp, home=self.tmp / "home")
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertIn("KILL-AUDIT-X\tFAIL", results.read_text())
        self.assertIn("1 non-kill deny", results.read_text())

    def test_audit_rewrite_tolerates_an_ownership_seed_without_decision(self):
        env, _ = self.stateful_recording_tmux()
        socket = self.private / f"tmux-{os.getuid()}" / "own"
        socket.parent.mkdir()
        socket.touch()
        self.ledger.write_text(json.dumps({"socket": str(socket), "created": True,
                                           "socket_inode": [socket.stat().st_dev, socket.stat().st_ino],
                                           "server_pid": "777", "session_ids": {}}) + "\n")
        results = self.tmp / "legacy-results.tsv"
        results.write_text("case\tverdict\tevidence\tnote\n"
                           "KILL-AUDIT-X\tPASS\tfleet/it/X/tmux-audit.jsonl\t0 kill(s): (none)\n")
        env.update(IT_TMUX_AUDIT_RESULTS=str(results), IT_TMUX_AUDIT_SECTION="X")
        created = self.tmux("-L", "own", "new-session", "-d", "-s", "mine", env=env)
        self.assertEqual(created.returncode, 0, created.stderr)
        killed = self.tmux("-L", "own", "kill-server", env=env)
        self.assertEqual(killed.returncode, 0, killed.stderr)
        self.assertIn("KILL-AUDIT-X\tPASS", results.read_text())

    def test_control_mode_is_refused_on_foreign_socket(self):
        env, calls = self.recording_tmux()
        for flag in ("-C", "-CC"):
            with self.subTest(flag=flag):
                result = self.tmux("-L", "default", flag, "list-sessions", env=env)
                self.assertEqual(result.returncode, 97, result.stderr)
        self.assertFalse(calls.exists(), "control mode reached fake real-tmux")

    def test_nonprivate_print_flag_must_be_an_option_not_a_target_value(self):
        env, calls = self.recording_tmux()
        for command in (("display-message", "-t=people", "hello"),
                        ("capture-pane", "-tpeople")):
            with self.subTest(command=command):
                self.assertEqual(self.tmux("-L", "default", *command, env=env).returncode, 97)
        self.assertFalse(calls.exists(), "a non-printing command reached fake real-tmux")
        self.assertEqual(self.tmux("-L", "default", "display-message", "-p", "#{pid}", env=env).returncode, 0)

    def test_nonprivate_read_cannot_evaluate_shell_command_format(self):
        env, calls = self.recording_tmux()
        for prefix, command in (("default", ("list-sessions", "-F", "#(/usr/bin/tmux kill-server)")),
                                ("default", ("display-message", "-p", "#(/usr/bin/tmux kill-session)")),
                                ("private", ("list-sessions", "-F", "#(/usr/bin/tmux kill-server)"))):
            with self.subTest(prefix=prefix, command=command):
                self.assertEqual(self.tmux("-L", prefix, *command, env=env).returncode, 97)
        self.assertFalse(calls.exists(), "a shell format reached fake real-tmux")
        self.assertEqual(self.tmux("-L", "default", "list-sessions", "-F", "#{session_name}",
                                   env=env).returncode, 0)

    def test_tmux_handle_and_component_boundary_cannot_relabel_foreign_socket(self):
        env, calls = self.recording_tmux()
        outside = self.tmp / "outside"
        outside.mkdir()
        link = self.private / "linked"
        link.symlink_to(outside, target_is_directory=True)
        prefix = self.tmp / "private-evil"
        prefix.mkdir()
        for args, overrides in (
                (("kill-server",), {"TMUX": str(outside / "live") + ",1,0"}),
                (("-2Ldefault", "kill-server"), {}),
                (("-uS", str(link / "live"), "kill-server"), {}),
                (("-S", str(prefix / "live"), "kill-server"), {}),
                (("-S", str(prefix / "new"), "new-session", "-d", "-s", "mine"), {})):
            with self.subTest(args=args):
                self.assertEqual(self.tmux(*args, env=dict(env, **overrides)).returncode, 97)
        self.assertFalse(calls.exists(), "a foreign kill reached fake real-tmux")

    def test_real_tmux_cannot_resolve_to_the_shim(self):
        env, calls = self.recording_tmux()
        env["IT_TMUX_REAL"] = str(self.shim)
        result = subprocess.run([str(self.shim), "-L", "own", "list-sessions"], env=env,
                                capture_output=True, text=True, timeout=1)
        self.assertEqual(result.returncode, 97, result.stderr)
        self.assertFalse(calls.exists())

    def test_global_shell_command_option_is_refused(self):
        env, calls = self.recording_tmux()
        for args in (("-c", "tmux kill-server", "list-sessions"),
                     ("-2c/usr/bin/tmux kill-server", "list-sessions")):
            with self.subTest(args=args):
                self.assertEqual(self.tmux(*args, env=env).returncode, 97)
        self.assertFalse(calls.exists(), "-c reached fake real-tmux")

    def test_slow_real_tmux_does_not_hold_the_ledger_lock(self):
        env, calls = self.recording_tmux()
        env["FAKE_TMUX_SLOW_COMMAND"] = "list-clients"
        slow = subprocess.Popen([str(self.shim), "-L", "own", "list-clients"], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(0.1)
            fast = subprocess.run([str(self.shim), "-L", "own", "list-sessions"], env=env,
                                  capture_output=True, text=True, timeout=0.8)
            self.assertEqual(fast.returncode, 0, fast.stderr)
        finally:
            slow.wait(timeout=4)

    def test_parallel_new_sessions_merge_owned_session_ids(self):
        fake = self.tmp / "parallel-tmux"
        started = self.tmp / "a-started"
        fake.write_text('''#!/usr/bin/env python3
import os, pathlib, sys, time
args = sys.argv[1:]
socket = pathlib.Path(args[1]) if args[0] == '-S' else pathlib.Path(os.environ['TMUX_TMPDIR']) / ('tmux-' + str(os.getuid())) / args[1]
command = args[2]
if command == 'display-message': print('777'); sys.exit(0)
if command == 'list-sessions':
    for name in ('base', 'a', 'b'):
        if pathlib.Path(os.environ['FAKE_STATE'] + '-' + name).exists(): print(name + '\\t$' + name)
    sys.exit(0)
if command == 'new-session':
    name = args[args.index('-s') + 1]
    if name == 'a':
        pathlib.Path(os.environ['FAKE_STARTED']).touch()
        time.sleep(0.6)
    pathlib.Path(os.environ['FAKE_STATE'] + '-' + name).touch()
    sys.exit(0)
sys.exit(0)
''')
        fake.chmod(0o755)
        socket = self.private / f"tmux-{os.getuid()}" / "own"
        socket.parent.mkdir()
        socket.touch()
        state = str(self.tmp / "session")
        pathlib.Path(state + "-base").touch()
        self.ledger.write_text(json.dumps({"socket": str(socket), "created": True,
                                           "socket_inode": [socket.stat().st_dev, socket.stat().st_ino],
                                           "server_pid": "777", "session_ids": {"base": "$base"}}) + "\n")
        env = dict(self.env, IT_TMUX_REAL=str(fake), FAKE_STATE=state, FAKE_STARTED=str(started))
        slow = subprocess.Popen([str(self.shim), "-L", "own", "new-session", "-d", "-s", "a"], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                if started.exists(): break
                time.sleep(0.01)
            self.assertTrue(started.exists())
            fast = self.tmux("-L", "own", "new-session", "-d", "-s", "b", env=env)
            self.assertEqual(fast.returncode, 0, fast.stderr)
        finally:
            _, stderr = slow.communicate(timeout=3)
        self.assertEqual(slow.returncode, 0, stderr.decode())
        row = json.loads(self.ledger.read_text().splitlines()[-1])
        self.assertEqual(set(row["session_ids"]), {"base", "a", "b"})

    def test_guardian_removes_generated_section_socket_directory(self):
        env, calls = self.stateful_recording_tmux()
        tmp = self.tmp / "harness"
        it = harness_copy(tmp)
        marker = self.tmp / "socket-dir"
        script = (f'. "{it}/lib.sh"\n'
                  f'it_section X\n'
                  f'it_tmux new-session -d -s mine\n'
                  f'printf "%s\\n" "$TMUX_TMPDIR" > "{marker}"\n')
        finished = run_bash(script, tmp, env={"IT_TMUX_REAL": env["IT_TMUX_REAL"],
                                               "FAKE_TMUX_RECORD": str(calls),
                                               "FLEET_SUITE_TRIPWIRE": ""}, home=self.tmp / "home")
        self.assertEqual(finished.returncode, 0, finished.stderr)
        directory = pathlib.Path(marker.read_text().strip())
        self.assertTrue(directory.name.startswith("itk-X."), directory)
        for _ in range(50):
            if not directory.exists():
                break
            time.sleep(0.1)
        self.assertFalse(directory.exists(), directory)

    def test_guardian_without_server_removes_directory_and_keeps_audit_pass(self):
        env, calls = self.recording_tmux()
        tmp = self.tmp / "harness-never-created"
        it = harness_copy(tmp)
        marker = self.tmp / "never-created-socket-dir"
        results = self.tmp / "never-created-results.tsv"
        results.write_text("case\tverdict\tevidence\tnote\n")
        script = (f'. "{it}/lib.sh"\n'
                  f'RESULTS="{results}"\n'
                  f'it_section X\n'
                  f'printf "%s\\n" "$TMUX_TMPDIR" > "{marker}"\n'
                  f'it_kill_audit_result\n')
        finished = run_bash(script, tmp, env={"IT_TMUX_REAL": env["IT_TMUX_REAL"],
                                               "FAKE_TMUX_RECORD": str(calls),
                                               "FLEET_SUITE_TRIPWIRE": ""}, home=self.tmp / "home")
        self.assertEqual(finished.returncode, 0, finished.stderr)
        directory = pathlib.Path(marker.read_text().strip())
        for _ in range(50):
            if not directory.exists():
                break
            time.sleep(0.1)
        self.assertFalse(directory.exists(), directory)
        self.assertIn("KILL-AUDIT-X\tPASS", results.read_text())
        forwarded = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
        self.assertFalse(any("kill-server" in argv for argv in forwarded),
                         "guardian called real tmux for a server never created")

    def test_guardian_keeps_socket_directory_after_refused_kill(self):
        env, calls = self.recording_tmux()
        tmp = self.tmp / "harness-denied"
        it = harness_copy(tmp)
        marker = self.tmp / "denied-socket-dir"
        script = (f'. "{it}/lib.sh"\n'
                  f'it_section X\n'
                  f': > "$TMUX_TMPDIR/tmux-$(id -u)/$IT_TMUX_SOCKET"\n'
                  f'printf "%s\\n" "$TMUX_TMPDIR" > "{marker}"\n')
        finished = run_bash(script, tmp, env={"IT_TMUX_REAL": env["IT_TMUX_REAL"],
                                               "FAKE_TMUX_RECORD": str(calls),
                                               "FLEET_SUITE_TRIPWIRE": ""}, home=self.tmp / "home")
        self.assertEqual(finished.returncode, 0, finished.stderr)
        directory = pathlib.Path(marker.read_text().strip())
        time.sleep(2.5)
        self.assertTrue(directory.exists(), "guardian removed a directory after the shim refused its kill")

    def test_case_supersession_waits_for_results_rewrite_lock(self):
        env, calls = self.recording_tmux()
        tmp = self.tmp / "harness"
        it = harness_copy(tmp)
        results = self.tmp / "results.tsv"
        results.write_text("case\tverdict\tevidence\tnote\nX\tPASS\t\told\n")
        script = f'. "{it}/lib.sh"\nRESULTS="{results}"\nit_own_cases "X"\n'
        with open(str(results) + ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            child = subprocess.Popen(["bash", "-c", script], cwd=tmp,
                                     env=clean_env({"IT_TMUX_REAL": env["IT_TMUX_REAL"],
                                                    "FAKE_TMUX_RECORD": str(calls)}, home=self.tmp / "home"),
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                time.sleep(0.2)
                self.assertIsNone(child.poll(), "case rewrite ignored the shared result lock")
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
                stdout, stderr = child.communicate(timeout=5)
        self.assertEqual(child.returncode, 0, stderr.decode())

    def test_end_of_options_and_combined_socket_flags_cannot_hide_a_kill(self):
        env, calls = self.recording_tmux()
        for args in (("-L", "default", "--", "kill-server"), ("--", "kill-server"),
                     ("-Lfleet", "--", "kill-ser"), ("-2L", "default", "--", "kill-session"),
                     ("-uS", str(self.tmp / "outside"), "--", "kill-server"),
                     ("-L", "own", "-S", str(self.tmp / "outside"), "--", "kill-server")):
            with self.subTest(args=args):
                self.assertEqual(self.tmux(*args, env=env).returncode, 97)
        self.assertFalse(calls.exists(), "a kill reached fake real-tmux")

    def test_shell_semicolon_is_data_but_tmux_separator_is_classified(self):
        env, calls = self.recording_tmux()
        benign = self.tmux("-L", "own", "new-session", "-d", "-s", "mine",
                           "bash -c 'cat x; exec sleep 100000'", env=env)
        self.assertEqual(benign.returncode, 0, benign.stderr)
        self.assertTrue(any(json.loads(line)[-1] == "bash -c 'cat x; exec sleep 100000'"
                            for line in calls.read_text().splitlines()))
        count = len(calls.read_text().splitlines())
        for separator in (";",):
            with self.subTest(separator=separator):
                denied = self.tmux("-L", "own", "list-sessions", separator,
                                   "kill-server", env=env)
                self.assertEqual(denied.returncode, 97, denied.stderr)
                self.assertEqual(len(calls.read_text().splitlines()), count)
        allowed = self.tmux("-L", "own", "list-sessions", ";", "has-session", env=env)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        literal = self.tmux("-L", "own", "list-sessions", r"\;", "kill-server", env=env)
        self.assertEqual(literal.returncode, 0, literal.stderr)

    def test_trailing_separator_cannot_hide_a_foreign_kill(self):
        env, calls = self.recording_tmux()
        for args in (("-L", "default", "list-sessions;", "kill-server"),
                     ("-L", "default", "has-session", "-t", "x;", "kill-server"),
                     ("-L", "default", "ls", "x;", "kill-server")):
            with self.subTest(args=args):
                result = self.tmux(*args, env=env)
                self.assertEqual(result.returncode, 97, result.stderr)
        self.assertFalse(calls.exists(), "a hidden kill reached fake real-tmux")

    def test_trailing_separator_on_owned_kill_is_classified_as_kill(self):
        env, calls = self.stateful_recording_tmux()
        self.assertEqual(self.tmux("-L", "own", "new-session", "-d", "-s", "mine", env=env).returncode, 0)
        before = len(calls.read_text().splitlines())
        result = self.tmux("-L", "own", "kill-server;", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls.read_text().splitlines()), before + 1)
        row = json.loads(self.ledger.read_text().splitlines()[-1])
        self.assertEqual(row["command"], "kill-server")
        self.assertEqual(row["decision"], "allow")

    def test_shell_operand_trailing_semicolon_and_escaped_semicolon_are_data(self):
        env, calls = self.recording_tmux()
        shell = self.tmux("-L", "own", "new-session", "-d", "-s", "mine", "echo hi;", env=env)
        self.assertEqual(shell.returncode, 0, shell.stderr)
        escaped = self.tmux("-L", "default", "ls", r"x\;", "kill-server", env=env)
        self.assertEqual(escaped.returncode, 0, escaped.stderr)
        forwarded = [json.loads(line) for line in calls.read_text().splitlines()]
        self.assertIn(["-L", "own", "new-session", "-d", "-s", "mine", "echo hi;"], forwarded)
        self.assertIn(["-L", "default", "ls", r"x\;", "kill-server"], forwarded)

    def test_leading_tmux_separator_cannot_hide_a_kill(self):
        env, calls = self.recording_tmux()
        for separator in (";", "\\;"):
            with self.subTest(separator=separator):
                result = self.tmux("-S", str(self.private / "unborn"),
                                   separator, "kill-server", env=env)
                self.assertEqual(result.returncode, 97, result.stderr)
        self.assertFalse(calls.exists(), "a leading separator reached fake real-tmux")

    def test_own_server_and_exact_session_kills_are_logged_and_allowed(self):
        started = self.tmux("-L", "own", "new-session", "-d", "-s", "mine", "sleep 30")
        self.assertEqual(started.returncode, 0, started.stderr)
        killed = self.tmux("-L", "own", "kill-session", "-t", "=mine")
        self.assertEqual(killed.returncode, 0, killed.stderr + self.ledger.read_text())
        rows = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertEqual([r["command"] for r in rows], ["new-session", "kill-session"])
        self.assertEqual(rows[-1]["decision"], "allow")
        self.assertEqual(rows[-1]["socket"], str(self.private / f"tmux-{os.getuid()}" / "own"))

    def test_foreign_server_kill_is_denied_before_real_tmux(self):
        for args in (("kill-server",), ("-L", "default", "kill-server"),
                     ("-S", str(self.tmp / "other" / "fleet-davis"), "kill-server")):
            with self.subTest(args=args):
                result = self.tmux(*args)
                self.assertEqual(result.returncode, 97, result.stderr)
        rows = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertEqual([r["decision"] for r in rows], ["deny"] * 3)

    def test_private_socket_that_section_did_not_create_is_denied(self):
        result = self.tmux("-L", "unborn", "kill-server")
        self.assertEqual(result.returncode, 97, result.stderr)

    def test_preexisting_private_server_is_not_section_owned(self):
        socket = self.private / f"tmux-{os.getuid()}" / "foreign"
        socket.parent.mkdir(mode=0o700)
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "new-session", "-d", "-s", "mine", "sleep 30"],
                                        capture_output=True).returncode, 0)
        self.addCleanup(subprocess.run, [self.real, "-S", str(socket), "kill-server"], capture_output=True)
        self.assertEqual(self.tmux("-L", "foreign", "kill-server").returncode, 97)
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "has-session"],
                                        capture_output=True).returncode, 0)

    def test_missing_recorded_server_pid_refuses_kill(self):
        socket = self.private / f"tmux-{os.getuid()}" / "own"
        self.assertEqual(self.tmux("-L", "own", "new-session", "-d", "-s", "mine", "sleep 30").returncode, 0)
        self.addCleanup(subprocess.run, [self.real, "-S", str(socket), "kill-server"], capture_output=True)
        rows = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertTrue(rows[0].get("server_pid"), rows)
        rows[0]["server_pid"] = None
        self.ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
        result = self.tmux("-L", "own", "kill-server")
        self.assertEqual(result.returncode, 97, result.stderr)
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "has-session"],
                                        capture_output=True).returncode, 0)

    def test_unreadable_current_server_pid_refuses_kill(self):
        socket = self.private / f"tmux-{os.getuid()}" / "own"
        self.assertEqual(self.tmux("-L", "own", "new-session", "-d", "-s", "mine", "sleep 30").returncode, 0)
        self.addCleanup(subprocess.run, [self.real, "-S", str(socket), "kill-server"], capture_output=True)
        wrapper = self.tmp / "tmux-without-pid"
        wrapper.write_text(f'#!/bin/sh\ncase "$*" in *display-message*) exit 1;; esac\nexec "{self.real}" "$@"\n')
        wrapper.chmod(0o755)
        result = self.tmux("-L", "own", "kill-server", env=dict(self.env, IT_TMUX_REAL=str(wrapper)))
        self.assertEqual(result.returncode, 97, result.stderr)
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "has-session"],
                                        capture_output=True).returncode, 0)

    def test_unverified_existing_server_does_not_gain_ownership_from_new_session(self):
        socket = self.private / f"tmux-{os.getuid()}" / "own"
        self.assertEqual(self.tmux("-L", "own", "new-session", "-d", "-s", "mine", "sleep 30").returncode, 0)
        self.addCleanup(subprocess.run, [self.real, "-S", str(socket), "kill-server"], capture_output=True)
        rows = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        rows[0]["server_pid"] = "not-the-recorded-server"
        self.ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
        counter = self.tmp / "pid-queries"
        wrapper = self.tmp / "tmux-one-missing-pid"
        wrapper.write_text(f'#!/bin/sh\ncase "$*" in *display-message*) '
                           f'if [ ! -e "{counter}" ]; then : > "{counter}"; exit 1; fi;; esac\n'
                           f'exec "{self.real}" "$@"\n')
        wrapper.chmod(0o755)
        created = self.tmux("-L", "own", "new-session", "-d", "-s", "second", "sleep 30",
                            env=dict(self.env, IT_TMUX_REAL=str(wrapper)))
        self.assertEqual(created.returncode, 0, created.stderr)
        killed = self.tmux("-L", "own", "kill-server")
        self.assertEqual(killed.returncode, 97, killed.stderr)
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "has-session"],
                                        capture_output=True).returncode, 0)

    def test_compound_command_cannot_hide_a_server_kill(self):
        socket = self.private / f"tmux-{os.getuid()}" / "foreign"
        socket.parent.mkdir(mode=0o700)
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "new-session", "-d", "-s", "mine", "sleep 30"],
                                        capture_output=True).returncode, 0)
        self.addCleanup(subprocess.run, [self.real, "-S", str(socket), "kill-server"], capture_output=True)
        result = self.tmux("-L", "foreign", "list-sessions", ";", "kill-server")
        self.assertEqual(result.returncode, 97, result.stderr)
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "has-session"],
                                        capture_output=True).returncode, 0)
        rows = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertTrue(any(r["command"] == "kill-server" and r["decision"] == "deny" for r in rows), rows)

    def test_server_side_dispatch_cannot_hide_a_server_kill(self):
        socket = self.private / f"tmux-{os.getuid()}" / "foreign"
        socket.parent.mkdir(mode=0o700)
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "new-session", "-d", "-s", "mine", "sleep 30"],
                                        capture_output=True).returncode, 0)
        self.addCleanup(subprocess.run, [self.real, "-S", str(socket), "kill-server"], capture_output=True)
        result = self.tmux("-L", "foreign", "if-shell", "-F", "1", "kill-server")
        self.assertEqual(result.returncode, 97, result.stderr)
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "has-session"],
                                        capture_output=True).returncode, 0)
        rows = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertTrue(any(r["command"] == "kill-server" and r["decision"] == "deny" for r in rows), rows)

    def test_foreign_session_on_owned_server_is_not_registered_by_a_read(self):
        socket = self.private / f"tmux-{os.getuid()}" / "own"
        self.assertEqual(self.tmux("-L", "own", "new-session", "-d", "-s", "mine", "sleep 30").returncode, 0)
        self.addCleanup(self.tmux, "-L", "own", "kill-server")
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "new-session", "-d", "-s", "foreign", "sleep 30"],
                                        capture_output=True).returncode, 0)
        self.assertEqual(self.tmux("-L", "own", "list-sessions").returncode, 0)
        result = self.tmux("-L", "own", "kill-session", "-t", "=foreign")
        self.assertEqual(result.returncode, 97, result.stderr)
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "has-session", "-t", "=foreign"],
                                        capture_output=True).returncode, 0)

    def test_kill_session_all_other_sessions_is_refused(self):
        socket = self.private / f"tmux-{os.getuid()}" / "own"
        self.assertEqual(self.tmux("-L", "own", "new-session", "-d", "-s", "mine", "sleep 30").returncode, 0)
        self.addCleanup(subprocess.run, [self.real, "-S", str(socket), "kill-server"], capture_output=True)
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "new-session", "-d", "-s", "foreign", "sleep 30"],
                                        capture_output=True).returncode, 0)
        result = self.tmux("-L", "own", "kill-session", "-a", "-t", "=mine")
        self.assertEqual(result.returncode, 97, result.stderr)
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "has-session", "-t", "=foreign"],
                                        capture_output=True).returncode, 0)
        rows = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertEqual(rows[-1]["decision"], "deny")

    def test_replaced_session_name_is_not_still_owned(self):
        socket = self.private / f"tmux-{os.getuid()}" / "own"
        for name in ("mine", "stay"):
            self.assertEqual(self.tmux("-L", "own", "new-session", "-d", "-s", name, "sleep 30").returncode, 0)
        self.addCleanup(self.tmux, "-L", "own", "kill-server")
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "kill-session", "-t", "=mine"],
                                        capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "new-session", "-d", "-s", "mine", "sleep 30"],
                                        capture_output=True).returncode, 0)
        result = self.tmux("-L", "own", "kill-session", "-t", "=mine")
        self.assertEqual(result.returncode, 97, result.stderr)
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "has-session", "-t", "=mine"],
                                        capture_output=True).returncode, 0)

    def test_renamed_created_session_keeps_its_identity(self):
        self.assertEqual(self.tmux("-L", "own", "new-session", "-d", "-s", "mine", "sleep 30").returncode, 0)
        self.addCleanup(self.tmux, "-L", "own", "kill-server")
        renamed = self.tmux("-L", "own", "rename-session", "-t", "=mine", "renamed")
        self.assertEqual(renamed.returncode, 0, renamed.stderr)
        killed = self.tmux("-L", "own", "kill-session", "-t", "=renamed")
        self.assertEqual(killed.returncode, 0, killed.stderr)

    def test_missing_ledger_fails_closed(self):
        env = dict(self.env)
        env.pop("IT_TMUX_AUDIT_LEDGER")
        result = self.tmux("-L", "unborn", "kill-server", env=env)
        self.assertEqual(result.returncode, 97, result.stderr)

    def test_session_kill_requires_exact_created_target(self):
        started = self.tmux("-L", "own", "new-session", "-d", "-s", "mine", "sleep 30")
        self.assertEqual(started.returncode, 0, started.stderr)
        self.addCleanup(self.tmux, "-L", "own", "kill-server")
        for target in ("mine", "=other"):
            with self.subTest(target=target):
                result = self.tmux("-L", "own", "kill-session", "-t", target)
                self.assertEqual(result.returncode, 97, result.stderr)

    def test_replaced_socket_is_not_still_owned(self):
        socket = self.private / f"tmux-{os.getuid()}" / "own"
        self.assertEqual(self.tmux("-L", "own", "new-session", "-d", "-s", "mine", "sleep 30").returncode, 0)
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "kill-server"],
                                        capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "new-session", "-d", "-s", "foreign", "sleep 30"],
                                        capture_output=True).returncode, 0)
        self.addCleanup(subprocess.run, [self.real, "-S", str(socket), "kill-server"], capture_output=True)
        result = self.tmux("-L", "own", "kill-server")
        self.assertEqual(result.returncode, 97, result.stderr)

    def test_tmux_kill_command_abbreviation_is_also_guarded(self):
        socket = self.private / f"tmux-{os.getuid()}" / "foreign"
        socket.parent.mkdir(mode=0o700)
        self.assertEqual(subprocess.run([self.real, "-S", str(socket), "new-session", "-d", "-s", "mine", "sleep 30"],
                                        capture_output=True).returncode, 0)
        first_probe = subprocess.run([self.real, "-S", str(socket), "has-session"], capture_output=True, text=True)
        self.assertEqual(first_probe.returncode, 0, f"real={self.real}; {first_probe.stderr}")
        self.addCleanup(subprocess.run, [self.real, "-S", str(socket), "kill-server"], capture_output=True)
        result = self.tmux("-L", "foreign", "kill-ser")
        self.assertEqual(result.returncode, 97, result.stderr)
        probe = subprocess.run([self.real, "-S", str(socket), "has-session"], capture_output=True, text=True)
        self.assertEqual(probe.returncode, 0, f"{result.stderr}; probe={probe.stderr}; ledger={self.ledger.read_text()}")

    def test_unregistered_directory_is_denied_even_if_server_was_created(self):
        other = self.tmp / "other"
        other.mkdir()
        self.addCleanup(subprocess.run, [self.real, "-S", str(other / f"tmux-{os.getuid()}" / "other"),
                                         "kill-server"], capture_output=True)
        env = dict(self.env, TMUX_TMPDIR=str(other))
        started = self.tmux("-L", "other", "new-session", "-d", "-s", "mine", "sleep 30", env=env)
        self.assertEqual(started.returncode, 97, started.stderr)
        self.assertEqual(self.tmux("-L", "other", "kill-server", env=env).returncode, 97)

    def test_kill_after_leave_refreshes_the_existing_result_row(self):
        results = self.tmp / "results.tsv"
        results.write_text("case\tverdict\tevidence\tnote\n"
                           "KILL-AUDIT-X\tPASS\tfleet/it/X/tmux-audit.jsonl\t0 kill(s): (none)\n")
        env = dict(self.env, IT_TMUX_AUDIT_RESULTS=str(results), IT_TMUX_AUDIT_SECTION="X")
        self.assertEqual(self.tmux("-L", "own", "new-session", "-d", "-s", "mine", "sleep 30", env=env).returncode, 0)
        self.assertEqual(self.tmux("-L", "own", "kill-server", env=env).returncode, 0)
        self.assertIn("kill-server@own[allow]", results.read_text())

    def test_attached_client_does_not_hold_ledger_lock(self):
        fake = self.tmp / "slow-tmux"
        fake.write_text("#!/bin/sh\ncase \"$*\" in *attach*) sleep 3;; esac\nexit 0\n")
        fake.chmod(0o755)
        env = dict(self.env, IT_TMUX_REAL=str(fake))
        attached = subprocess.Popen([str(self.shim), "-L", "own", "attach"], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(0.1)
            try:
                probe = subprocess.run([str(self.shim), "-L", "own", "list-clients"], env=env,
                                       capture_output=True, timeout=0.5)
            except subprocess.TimeoutExpired:
                self.fail("an attached client held the ledger lock across its lifetime")
            self.assertEqual(probe.returncode, 0, probe.stderr)
        finally:
            attached.terminate()
            attached.wait(timeout=5)


class NestedSelftestTmuxBoundary(unittest.TestCase):
    def test_nested_suite_excludes_outer_it_shim_from_real_tmux_path(self):
        before = dict(os.environ)
        try:
            os.environ["PATH"] = "/outer/it/bin:/usr/bin"
            os.environ["IT_TMUX_AUDIT_BIN"] = "/outer/it/bin"
            self.assertEqual(tests._ambient_path(), "/usr/bin")
        finally:
            os.environ.clear()
            os.environ.update(before)

    def test_harness_fixture_excludes_outer_it_audit_environment(self):
        before = dict(os.environ)
        try:
            os.environ["PATH"] = "/outer/it/bin:/usr/bin"
            os.environ["IT_TMUX_AUDIT_BIN"] = "/outer/it/bin"
            os.environ["IT_TMUX_AUDIT_LEDGER"] = "/outer/calls.jsonl"
            os.environ["IT_TMUX_AUDIT_CASE_SECTION"] = "OUTER"
            os.environ["IT_TMUX_REAL"] = "/usr/bin/tmux"
            env = clean_env()
            self.assertEqual(env["PATH"], "/usr/bin")
            self.assertFalse(any(k.startswith("IT_TMUX_AUDIT_") for k in env))
            self.assertFalse("IT_TMUX_REAL" in env)
        finally:
            os.environ.clear()
            os.environ.update(before)

    def test_section_refuses_when_runtime_shim_is_missing(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="it-missing-shim-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        it = harness_copy(tmp)
        (it / "bin" / "tmux").unlink()
        result = run_bash(f'. "{it}/lib.sh"\nit_section X', tmp, home=tmp / "home")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dynamic_section_rerun_replaces_its_kill_audit_row(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="it-audit-rerun-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        it = harness_copy(tmp)
        results = tmp / "results.tsv"
        results.write_text("case\tverdict\tevidence\tnote\n")
        for section in ("X-101", "X-202"):
            body = (f'. "{it}/lib.sh"\nit_own_cases "ISOLATION-X-.*"\n'
                    f'it_section {section}\nit_assert_isolation X-leave\n')
            result = run_bash(body, tmp, env={"IT_RESULTS": str(results)}, home=tmp / "home")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = [line for line in results.read_text().splitlines() if line.startswith("KILL-AUDIT-")]
        self.assertEqual(len(rows), 1, rows)

    def test_fresh_results_file_claims_its_kill_audit_row(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="it-audit-fresh-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        it = harness_copy(tmp)
        results = tmp / "new-results.tsv"
        body = (f'. "{it}/lib.sh"\nIT_FAILED=0\nit_own_cases "ISOLATION-X-.*"\n'
                'it_section X\nit_assert_isolation X-leave\ntest "$IT_FAILED" = 0\n')
        result = run_bash(body, tmp, env={"IT_RESULTS": str(results)}, home=tmp / "home")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr + results.read_text())
        rows = results.read_text()
        self.assertIn("KILL-AUDIT-X\tPASS", rows)
        self.assertNotIn("OWN-KILL-AUDIT-X", rows)

    def test_deep_checkout_uses_short_private_socket_root(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="it-deep-audit-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        deep = tmp / ("nested" * 15) / "owner"
        deep.mkdir(parents=True)
        it = harness_copy(deep)
        short = tmp / "short"
        short.mkdir()
        body = (f'. "{it}/lib.sh"\nit_section X\n'
                'it_tmux new-session -d -s mine "sleep 30"\n'
                'it_tmux kill-server\n')
        result = run_bash(body, deep, env={"FLEET_SUITE_TRIPWIRE": "", "TMUX_TMPDIR": "",
                                           "IT_TMUX_AUDIT_SHORT_ROOT": str(short)}, home=tmp / "home")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        ledgers = list((it / "X").glob("tmux-audit.jsonl"))
        self.assertEqual(len(ledgers), 1)
        rows = [json.loads(line) for line in ledgers[0].read_text().splitlines()]
        self.assertTrue(all(row["socket"].startswith(str(short)) for row in rows
                            if row["command"] in ("new-session", "kill-server")), rows)


class ServerGuardian(unittest.TestCase):
    """FB-73. A runner's EXIT trap cannot run when the shell tree is SIGKILLed (what TaskStop does); its
    private server must still go away. All socket names are unique to this process; the fallback cases
    observe the guardian's tmux calls through the suite's tripwire rather than creating a server under the
    real default directory (S5 glue). RED:
    evidence/01-red/fb73-kill9-base.txt (the server still up 10 s after kill -9)."""

    def setUp(self):
        if shutil.which("tmux") is None:
            self.skipTest("tmux is not on PATH, so the guardian cannot be exercised here")
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="itf-", dir="/tmp"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.it = harness_copy(self.tmp)
        # A sandbox may map every test process to the same small PID, so the socket name stays unique
        # across pid namespaces: a same-named server anywhere else is never this test's.
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

    def test_a_guardian_whose_directory_is_gone_touches_no_other_server(self):
        """RV-38. A guardian whose <dir> is gone first (a hermetic test's tmp removed before the 2 s poll notices the
        runner died) must not fall back to /tmp. v23-n's own guardian killed `TMUX_TMPDIR=<dir> tmux -L <sock>`,
        which falls back to `/tmp/tmux-<uid>/<sock>`; v23-l's (the one in the tree) kills `tmux -S <dir>/tmux-<uid>/<sock>`
        and exits first when <dir> is gone. Either way, no tmux call may reach another directory."""
        sockdir = self.tmp / "sockdir"
        sockdir.mkdir()
        self.env["TMUX_TMPDIR"] = str(sockdir)
        #: setUp's kill-server cleanup shares this dict; point it back before it runs, not at the removed directory.
        self.addCleanup(self.env.__setitem__, "TMUX_TMPDIR", str(self.tmp))
        with tests.expect_tripwire() as seen:
            p = self.start_runner()
            guardian = int((self.it / ".guardians" / f"{self.socket}.pid").read_text())
            subprocess.run(["tmux", "-L", self.socket, "kill-server"], capture_output=True, env=self.env)
            shutil.rmtree(sockdir)
            p.kill()
            p.wait()
            for _ in range(100):                      # the guardian polls every 2 s, then acts and exits
                if not pathlib.Path(f"/proc/{guardian}").exists():
                    break
                time.sleep(0.1)
            self.assertFalse(pathlib.Path(f"/proc/{guardian}").exists(), "the guardian never finished")
        self.assertEqual(seen, [], "the guardian ran tmux against a server in another directory")

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

    def _assert_rearm_revokes_old_directory(self, valid_move):
        old_dir = self.tmp / "old-sockets"
        old_dir.mkdir()
        new_dir = self.tmp / "new-sockets"
        if valid_move:
            new_dir.mkdir()
        old_env = dict(self.env, TMUX_TMPDIR=str(old_dir))
        new_env = dict(self.env, TMUX_TMPDIR=str(new_dir))
        self.addCleanup(subprocess.run, ["tmux", "-L", self.socket, "kill-server"],
                        capture_output=True, env=old_env)
        if valid_move:
            self.addCleanup(subprocess.run, ["tmux", "-L", self.socket, "kill-server"],
                            capture_output=True, env=new_env)
        ready = self.tmp / "rearmed"
        sleeper = self.tmp / "rearmed-sleep.pid"
        old_guardian = self.tmp / "old-guardian.pid"
        new_guardian = self.tmp / "new-guardian.pid"
        script = (f'. "{self.it}/lib.sh"\n'
                  f'it_section {self.section} >/dev/null 2>&1\n'
                  'sleep 0.3\n'
                  f'cat "{self.it}/.guardians/{self.socket}.pid" > "{old_guardian}"\n'
                  f'it_move_tmux_tmpdir "{new_dir}"\n')
        if valid_move:
            script += f'cat "{self.it}/.guardians/{self.socket}.pid" > "{new_guardian}"\n'
            script += f'it_tmux new-session -d -s {self.socket}-owned "sleep 300"\n'
        script += f'touch "{ready}"\nsleep 300 & echo $! > "{sleeper}"; wait\n'
        (self.tmp / "move-runner.sh").write_text(script)
        runner = subprocess.Popen(["bash", str(self.tmp / "move-runner.sh")], cwd=self.tmp,
                                  env=old_env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (runner.kill(), runner.wait()))
        self.addCleanup(lambda: subprocess.run(
            ["bash", "-c", f'kill "$(cat "{sleeper}" 2>/dev/null)" 2>/dev/null; true'],
            capture_output=True))
        for _ in range(100):
            if ready.exists():
                break
            time.sleep(0.1)
        self.assertTrue(ready.exists(), "runner did not re-arm")
        started = subprocess.run(["tmux", "-L", self.socket, "new-session", "-d", "-s", "foreign"],
                                 capture_output=True, env=old_env)
        self.assertEqual(started.returncode, 0, started.stderr)
        if valid_move:
            self.assertEqual(subprocess.run(["tmux", "-L", self.socket, "ls"],
                                            capture_output=True, env=new_env).returncode, 0)
        runner.kill()
        runner.wait()
        for pidfile in ([old_guardian, new_guardian] if valid_move else [old_guardian]):
            pid = int(pidfile.read_text())
            deadline = time.monotonic() + 10
            while pathlib.Path(f"/proc/{pid}").exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertFalse(pathlib.Path(f"/proc/{pid}").exists(),
                             f"guardian {pid} did not exit")
        self.assertEqual(subprocess.run(["tmux", "-L", self.socket, "ls"],
                                        capture_output=True, env=old_env).returncode, 0,
                         "old guardian killed a foreign same-named server")
        if valid_move:
            self.assertNotEqual(subprocess.run(["tmux", "-L", self.socket, "ls"],
                                              capture_output=True, env=new_env).returncode, 0,
                                "new guardian did not reap the runner's server")

    def test_rearm_in_new_directory_revokes_old_guardian(self):
        self._assert_rearm_revokes_old_directory(valid_move=True)

    def test_failed_rearm_still_revokes_old_guardian(self):
        self._assert_rearm_revokes_old_directory(valid_move=False)

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

    def test_second_section_does_not_revoke_the_first_sections_guardian(self):
        """FB-122a. One runner arms several sections (run-group5 L/M/N, group3 E/K). Revocation is per SOCKET:
        arming the second section's guardian must leave the first section's armed, so a SIGKILL reaps both."""
        second = f"{self.section[:-1]}h"
        second_socket = f"itfleet-{second}"
        self.addCleanup(subprocess.run, ["tmux", "-L", second_socket, "kill-server"], capture_output=True,
                        env=self.env)
        started = self.tmp / "started"
        script = (f'. "{self.it}/lib.sh"\n'
                  f'it_section {self.section} >/dev/null 2>&1\n'
                  f'it_tmux new-session -d -s {self.socket}-victim "sleep 300"\n'
                  f'it_section {second} >/dev/null 2>&1\n'
                  f'it_tmux new-session -d -s {second_socket}-victim "sleep 300"\n'
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
        self.assertTrue(started.exists(), "runner did not reach its second section")
        up = lambda sock: subprocess.run(["tmux", "-L", sock, "ls"], capture_output=True,
                                         env=self.env).returncode == 0
        self.assertTrue(up(self.socket) and up(second_socket), "both sections' servers must be up")
        p.kill()
        p.wait()
        for _ in range(100):          # the guardians poll every 2 s
            if not up(self.socket) and not up(second_socket):
                break
            time.sleep(0.1)
        self.assertFalse(up(second_socket), "the second section's server survived its runner's SIGKILL")
        self.assertFalse(up(self.socket), "arming the second section revoked the first section's guardian")

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

    def _assert_missing_armed_dir_preserves_default_server(self, move):
        """FB-73 / v23-l: a guardian whose armed directory was deleted or moved must not fall back to the box's
        default directory and kill a same-named server there.

        S5 glue (v23-l x v23-n): this case used to START a real same-named server in `/tmp/tmux-<uid>` and check it
        survived. Under v23-n's host boundary (FB-118) the hermetic suite may not reach the operator's default tmux
        directory at all, so the victim is now observed rather than created, as v23-n's RV-38 case does: the
        guardian runs `tmux` by name, the suite's PATH shim records every call it makes, and any call aimed at a
        server outside this test (the default directory included) fails the case."""
        armed = self.tmp / "armed"
        armed.mkdir()
        with tests.expect_tripwire() as seen:
            p = self._start_guarded_runner(armed)
            if move:
                armed.rename(self.tmp / "renamed")
            else:
                shutil.rmtree(armed)
            p.kill()
            p.wait()
            guardian_pid = int((self.it / ".guardians" / f"{self.socket}.pid").read_text())
            deadline = time.monotonic() + 10
            while pathlib.Path(f"/proc/{guardian_pid}").exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertFalse(pathlib.Path(f"/proc/{guardian_pid}").exists(), "guardian did not exit")
        self.assertEqual(seen, [], "the guardian ran tmux against a server outside this test's directory")

    def test_deleted_armed_directory_does_not_kill_default_server(self):
        self._assert_missing_armed_dir_preserves_default_server(move=False)

    def test_moved_armed_directory_does_not_kill_default_server(self):
        self._assert_missing_armed_dir_preserves_default_server(move=True)

    def test_missing_dir_case_waits_for_guardian_exit(self):
        start = self._start_guarded_runner
        paused = []
        def pause_guardian(armed_dir):
            runner = start(armed_dir)
            pid = int((self.it / ".guardians" / f"{self.socket}.pid").read_text())
            os.kill(pid, signal.SIGSTOP)
            paused.append(pid)
            return runner
        self._start_guarded_runner = pause_guardian
        try:
            with self.assertRaisesRegex(AssertionError, "guardian did not exit"):
                self._assert_missing_armed_dir_preserves_default_server(move=False)
        finally:
            for pid in paused:
                os.kill(pid, signal.SIGCONT)

    def test_the_tripwire_observes_the_guardians_tmux_calls(self):
        """Positive control for the observation form above (S5 review RV-H1/H2): the fallback cases can only see the
        guardian's calls if the guardian runs `tmux` by NAME through PATH. A recording `tmux` placed first on the
        runner's PATH must see the ordinary kill, `-S <dir>/tmux-<uid>/<sock> kill-server`, after a SIGKILL."""
        bin_dir = self.tmp / "record-bin"
        bin_dir.mkdir()
        log = self.tmp / "tmux-calls.log"
        recorder = bin_dir / "tmux"
        recorder.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\n'
                            f'PATH="{self.env["PATH"]}" exec tmux "$@"\n')
        recorder.chmod(0o755)
        self.env["PATH"] = f"{bin_dir}:{self.env['PATH']}"
        runner = self.start_runner()
        guardian = int((self.it / ".guardians" / f"{self.socket}.pid").read_text())
        runner.kill()
        runner.wait()
        deadline = time.monotonic() + 10
        while pathlib.Path(f"/proc/{guardian}").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertFalse(pathlib.Path(f"/proc/{guardian}").exists(), "the guardian never finished")
        calls = log.read_text().splitlines() if log.exists() else []
        expected = f"-S {self.tmp}/tmux-{os.getuid()}/{self.socket} kill-server"
        self.assertIn(expected, calls, f"the guardian's kill never went through PATH: {calls}")

    def test_mismatched_runner_pid_fails_safe(self):
        """A caller whose claimed pid is not the guardian's parent cannot authorize a kill."""
        p = self._start_guarded_runner(self.tmp, runner_pid="1")
        started = subprocess.run(["tmux", "-L", self.socket, "new-session", "-d", "-s", "victim"],
                                 capture_output=True, env=self.env)
        self.assertEqual(started.returncode, 0, started.stderr)
        p.kill()
        p.wait()
        time.sleep(3)
        self.assertTrue(self.server_up(), "guardian killed with an unverified runner pid")

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
        tokenfile = armed / f"tmux-{os.getuid()}" / f".{self.socket}.guard"
        self.assertTrue(tokenfile.exists(), "old guardian removed the successor's token")

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

    def test_failed_token_move_does_not_arm(self):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        fake_mv = bin_dir / "mv"
        fake_mv.write_text("#!/bin/sh\nexit 1\n")
        fake_mv.chmod(0o755)
        env = dict(self.env, PATH=f"{bin_dir}:{os.environ['PATH']}")
        script = (f'. "{self.it}/lib.sh"\n'
                  f'it_guard_server "$$" "{self.socket}"\n'
                  'echo "arm-status=$?"\n')
        result = subprocess.run(["bash", "-c", script], capture_output=True, env=env, cwd=self.tmp)
        self.assertIn(b"arm-status=1", result.stdout)
        self.assertFalse((self.it / ".guardians" / f"{self.socket}.pid").exists())

    def test_relative_socket_directory_is_resolved_when_armed(self):
        (self.tmp / "relative").mkdir()
        self._start_guarded_runner("relative")
        guardian_pid = int((self.it / ".guardians" / f"{self.socket}.pid").read_text())
        argv = pathlib.Path(f"/proc/{guardian_pid}/cmdline").read_bytes().split(b"\0")
        directory = argv[argv.index(b"it-guardian") + 2]
        self.assertTrue(os.path.isabs(directory), directory)

    def test_symlink_socket_directory_uses_real_path(self):
        real_dir = self.tmp / "real-sockets"
        real_dir.mkdir()
        link_dir = self.tmp / "linked-sockets"
        link_dir.symlink_to(real_dir, target_is_directory=True)
        self._start_guarded_runner(link_dir)
        guardian_pid = int((self.it / ".guardians" / f"{self.socket}.pid").read_text())
        argv = pathlib.Path(f"/proc/{guardian_pid}/cmdline").read_bytes().split(b"\0")
        directory = argv[argv.index(b"it-guardian") + 2].decode()
        self.assertEqual(directory, str(real_dir))

    def test_guardian_unlinks_its_token_after_runner_exits(self):
        runner = self.start_runner()
        tokenfile = self.tmp / f"tmux-{os.getuid()}" / f".{self.socket}.guard"
        self.assertTrue(tokenfile.exists(), "the runner did not publish a token")
        runner.kill()
        runner.wait()
        deadline = time.monotonic() + 10
        while tokenfile.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertFalse(tokenfile.exists(), "guardian left its own token behind")


if __name__ == "__main__":
    unittest.main()
