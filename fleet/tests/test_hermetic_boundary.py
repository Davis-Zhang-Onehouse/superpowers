"""FB-118: the hermetic suite never execs a real runtime and never reaches a tmux server it did not create.

Measured at base 74bea441 from a worker pane: four real `claude agents --json` per run (peers with
`FLEET_CLAUDE_BIN` unset), bare `tmux` calls answered by the pane's `$TMUX` server (fleet-davis), and seventeen
`tmux -L fleet-davis` calls from tests that inherited the pane's `FLEET_TMUX_SOCKET`. The boundary that stops it
lives in `tests/__init__.py`; these cases pin the boundary AND the tripwire behind it, each against a decoy the
case creates itself, so a broken tripwire can only ever reach the decoy.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import tests
from tests import hermetic_environment

from fleet import peers

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def host_claudes():
    """Every path the host's own claude answers to, resolved — what `peers` fell through to at the base."""
    found = {peers.DEFAULT_CLAUDE_BIN, shutil.which("claude", path=getattr(tests, "AMBIENT_PATH", os.environ.get("PATH"))) or ""}
    return {os.path.realpath(p) for p in found if p and os.path.exists(p)}


class TheSuiteBoundary(unittest.TestCase):
    """What every test in this process inherits, whoever started the suite and from where."""

    def test_no_tmux_handle_of_the_caller_reaches_a_test(self):
        for name in ("TMUX", "TMUX_PANE", "FLEET_TMUX_SOCKET"):
            #: `assertFalse`, not `assertNotIn(name, os.environ)`: the latter prints the whole environment.
            self.assertFalse(name in os.environ,
                             f"{name} is inherited by every test: a bare tmux follows $TMUX to the caller's server, "
                             f"and FLEET_TMUX_SOCKET names it outright (17 `-L fleet-davis` calls at the base)")

    def test_every_tmux_socket_a_test_names_lands_in_a_directory_of_the_suite(self):
        tmpdir = os.environ.get("TMUX_TMPDIR")
        self.assertTrue(tmpdir, "TMUX_TMPDIR is unset, so `tmux -L <name>` resolves under /tmp/tmux-<uid>, "
                                "the directory the operator's live servers are in")
        here = pathlib.Path(tmpdir).resolve() / f"tmux-{os.getuid()}"
        for foreign in tests.FOREIGN_TMUX:
            self.assertNotEqual(here, pathlib.Path(foreign).resolve())

    def test_an_unset_FLEET_CLAUDE_BIN_never_resolves_to_the_hosts_claude(self):
        with tempfile.TemporaryDirectory() as tmp, hermetic_environment(tmp, home=tmp):
            resolved = os.path.realpath(peers._claude_bin())
        self.assertNotIn(resolved, host_claudes(),
                         "with FLEET_CLAUDE_BIN cleared, peers resolves the box's real claude and runs it")

    def test_an_unset_runtime_binary_is_the_refusing_stub_in_and_out_of_a_fixture(self):
        with tempfile.TemporaryDirectory() as tmp, hermetic_environment(tmp, home=tmp):
            inside = {name: os.environ.get(name) for name in ("FLEET_CLAUDE_BIN", "FLEET_CODEX_BIN")}
        outside = {name: os.environ.get(name) for name in ("FLEET_CLAUDE_BIN", "FLEET_CODEX_BIN")}
        for where, env in (("inside hermetic_environment", inside), ("in the suite process", outside)):
            for name, value in env.items():
                self.assertEqual(value, str(FIXTURES / "bin" / "no-real-runtime"), f"{name} {where}")


class EveryModuleInstallsTheBoundary(unittest.TestCase):
    """RV-15. The boundary is installed when the `tests` package is imported. `discover -s tests -p <one module>`
    without `-t .` imports the module as a top-level name, so a module that never imports `tests` ran with none —
    and test_root_resolution's fixture root `davis` derives the socket `fleet-davis`, the live server's name."""

    def test_every_test_module_imports_the_tests_package_at_top_level(self):
        import ast
        missing = []
        for path in sorted(FIXTURES.parent.glob("test_*.py")):
            tree = ast.parse(path.read_text())
            imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
            if not any((isinstance(n, ast.Import) and any(a.name == "tests" or a.name.startswith("tests.")
                                                         for a in n.names))
                       or (isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "tests")
                       for n in imports):
                missing.append(path.name)
        self.assertEqual(missing, [], "these modules run with no host boundary when run alone")


class TheBoundaryInAChild(unittest.TestCase):
    """RV-27. A child that inherits the suite's environment reuses it; one that inherits only a stale marker (a leaked
    FLEET_SUITE_TRIPWIRE, say from a tmux server's global environment) must build its own boundary, not trust it."""

    PROBE = ("import json, os, tests; print(json.dumps({'owner': tests._OWNER, 'log': tests.TRIPWIRE_LOG, "
             "'foreign': list(tests.FOREIGN_TMUX), 'tmpdir': os.environ['TMUX_TMPDIR'], "
             "'tmpdir_exists': os.path.isdir(os.environ['TMUX_TMPDIR'])}))")

    def probe(self, env):
        import json
        done = subprocess.run([sys.executable, "-c", self.PROBE], env=env, cwd=FIXTURES.parent.parent,
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_a_child_of_the_suite_reuses_its_boundary(self):
        got = self.probe(dict(os.environ))
        self.assertFalse(got["owner"])
        self.assertEqual(got["log"], tests.TRIPWIRE_LOG)

    def test_a_stale_marker_is_not_trusted(self):
        env = dict(os.environ, FLEET_SUITE_TRIPWIRE="/nonexistent-v23n/tripwire.log", FLEET_SUITE_FOREIGN_TMUX="",
                   TMUX_TMPDIR="/nonexistent-v23n/tmux")
        got = self.probe(env)
        self.assertTrue(got["owner"], got)
        self.assertTrue(got["foreign"], got)
        self.assertTrue(got["tmpdir_exists"], got)
        self.assertNotEqual(got["log"], "/nonexistent-v23n/tripwire.log")


    def test_the_boxs_default_tmux_dir_is_foreign_even_when_the_caller_exports_TMUX_TMPDIR(self):
        """RV-28. A runner in the FB-73 guardian style exports its own TMUX_TMPDIR; the live servers still sit in
        /tmp/tmux-<uid>, and a `-S /tmp/tmux-<uid>/fleet-davis` must stay foreign."""
        with tempfile.TemporaryDirectory() as caller_dir:
            env = {k: v for k, v in os.environ.items() if not k.startswith("FLEET_SUITE_")}
            env["TMUX_TMPDIR"] = caller_dir
            got = self.probe(env)
        self.assertIn(os.path.realpath(f"/tmp/tmux-{os.getuid()}"), [os.path.realpath(f) for f in got["foreign"]], got)


class TheTripwire(unittest.TestCase):
    """The tripwire refuses and RECORDS; the record fails the test that caused it. Every case aims it at a
    decoy server this case created, so if the tripwire were broken the call would reach only the decoy."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-tripwire-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.decoy_dir = self.tmp / "decoy-tmux"
        self.decoy_dir.mkdir()
        self.decoy = self.decoy_dir / "live"
        if shutil.which("tmux") is None:
            self.skipTest("tmux is not on PATH")
        made = subprocess.run([tests.REAL_TMUX, "-S", str(self.decoy), "new-session", "-d", "-s", "decoy-live"],
                              capture_output=True, text=True)
        self.assertEqual(made.returncode, 0, made.stderr)
        self.addCleanup(subprocess.run, [tests.REAL_TMUX, "-S", str(self.decoy), "kill-server"],
                        capture_output=True)
        patcher = mock.patch.object(tests, "FOREIGN_TMUX", (str(self.decoy_dir),))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.child_env = dict(os.environ, FLEET_SUITE_FOREIGN_TMUX=str(self.decoy_dir))

    def test_an_in_process_tmux_call_at_a_foreign_server_is_refused_before_it_runs(self):
        with tests.expect_tripwire() as seen:
            with self.assertRaises(tests.HostReached):
                subprocess.run(["tmux", "-S", str(self.decoy), "ls"], capture_output=True)
        self.assertEqual(len(seen), 1, seen)
        self.assertIn(str(self.decoy), seen[0])

    def test_a_child_tmux_call_at_a_foreign_server_is_refused_by_the_path_shim(self):
        with tests.expect_tripwire() as seen:
            done = subprocess.run(["bash", "-c", f"tmux -S '{self.decoy}' ls"], env=self.child_env,
                                  capture_output=True, text=True)
        self.assertEqual(done.returncode, 97, done.stderr)
        self.assertNotIn("decoy-live", done.stdout, "the shim let the call reach the decoy server")
        self.assertEqual(len(seen), 1, seen)

    def test_a_bare_child_tmux_follows_TMUX_and_is_refused(self):
        env = dict(self.child_env, TMUX=f"{self.decoy},1,0")
        with tests.expect_tripwire() as seen:
            done = subprocess.run(["bash", "-c", "tmux ls -F '#{session_name}'"], env=env,
                                  capture_output=True, text=True)
        self.assertEqual(done.returncode, 97, done.stdout + done.stderr)
        self.assertEqual(len(seen), 1, seen)

    def test_a_server_of_the_tests_own_is_allowed_in_and_out_of_process(self):
        own = self.tmp / "own"
        with tests.expect_tripwire() as seen:
            made = subprocess.run(["tmux", "-S", str(own), "new-session", "-d", "-s", "mine"],
                                  capture_output=True, text=True)
            listed = subprocess.run(["bash", "-c", f"tmux -S '{own}' ls -F '#{{session_name}}'"],
                                    env=self.child_env, capture_output=True, text=True)
            subprocess.run(["tmux", "-S", str(own), "kill-server"], capture_output=True)
        self.assertEqual(made.returncode, 0, made.stderr)
        self.assertEqual(listed.stdout.strip(), "mine", listed.stderr)
        self.assertEqual(seen, [], "the tripwire fired on a server the test created itself")

    def test_an_in_process_exec_of_a_real_runtime_is_refused(self):
        fake_host = self.tmp / "claude"
        fake_host.write_text("#!/bin/sh\necho reached > \"$0.reached\"\n")
        fake_host.chmod(0o755)
        with mock.patch.object(tests, "REAL_RUNTIMES", frozenset({os.path.realpath(fake_host)})), \
                tests.expect_tripwire() as seen:
            with self.assertRaises(tests.HostReached):
                subprocess.run([str(fake_host), "agents", "--json"], capture_output=True)
        self.assertFalse((self.tmp / "claude.reached").exists(), "the 'real' runtime ran")
        self.assertEqual(len(seen), 1, seen)

    def test_a_relative_socket_path_is_judged_from_the_callees_cwd(self):
        """RV-30. `subprocess.run(["tmux", "-S", "live", ...], cwd=<dir>)` reaches <dir>/live; judging the relative path
        from the TEST's cwd would call a foreign server private."""
        self.assertEqual(tests.tmux_server(["tmux", "-S", "live", "ls"], {}, cwd=str(self.decoy_dir)),
                         os.path.realpath(self.decoy))
        with tests.expect_tripwire() as seen:
            with self.assertRaises(tests.HostReached):
                subprocess.run([tests.REAL_TMUX, "-S", "live", "ls"], cwd=self.decoy_dir, capture_output=True)
        self.assertEqual(len(seen), 1, seen)

    def test_a_child_that_runs_claude_or_codex_by_name_reaches_the_stub(self):
        """RV-29. FLEET_CLAUDE_BIN covers fleet's own resolution; a child that runs `claude`/`codex` by NAME — a
        script, `env`, `timeout`, `bash -c` — resolves PATH, and the tripwire's PATH directory answers first."""
        with tests.expect_tripwire() as seen:
            for line in ("claude agents --json", "env codex --version", "timeout 5 claude --version"):
                done = subprocess.run(["bash", "-c", line], capture_output=True, text=True)
                self.assertEqual(done.returncode, 97, line + " " + done.stderr)
        self.assertEqual(len(seen), 3, seen)
        self.assertTrue(all(record.startswith("runtime\t") for record in seen), seen)

    def test_an_in_process_posix_spawn_of_a_real_runtime_is_refused(self):
        fake_host = self.tmp / "codex"
        fake_host.write_text("#!/bin/sh\necho reached > \"$0.reached\"\n")
        fake_host.chmod(0o755)
        with mock.patch.object(tests, "REAL_RUNTIMES", frozenset({os.path.realpath(fake_host)})), \
                tests.expect_tripwire() as seen:
            with self.assertRaises(tests.HostReached):
                os.posix_spawn(str(fake_host), [str(fake_host)], dict(os.environ))
        self.assertFalse((self.tmp / "codex.reached").exists(), "the 'real' runtime ran")
        self.assertEqual(len(seen), 1, seen)

    def test_the_stub_an_unset_runtime_resolves_to_records_and_refuses(self):
        with tests.expect_tripwire() as seen:
            done = subprocess.run([os.environ["FLEET_CLAUDE_BIN"], "agents", "--json"], capture_output=True,
                                  text=True)
        self.assertEqual(done.returncode, 97)
        self.assertEqual(len(seen), 1, seen)
        self.assertTrue(seen[0].startswith("runtime\t"), seen)

    def test_a_missing_TMUX_TMPDIR_resolves_where_tmux_falls_back_to(self):
        """RV-25. tmux ignores a TMUX_TMPDIR that does not exist and uses /tmp — measured on 3.2a — so a model that
        resolves under the missing directory would call a live `-L` socket private."""
        live = os.path.realpath(f"/tmp/tmux-{os.getuid()}/v23n-no-such-server")
        for tmpdir in ("/nonexistent-v23n-dir", ""):
            with self.subTest(TMUX_TMPDIR=tmpdir):
                self.assertEqual(tests.tmux_server(["tmux", "-L", "v23n-no-such-server", "ls"],
                                                   {"TMUX_TMPDIR": tmpdir}), live)
        env = dict(self.child_env, TMUX_TMPDIR="/nonexistent-v23n-dir",
                   FLEET_SUITE_FOREIGN_TMUX=f"/tmp/tmux-{os.getuid()}")
        with tests.expect_tripwire() as seen:
            done = subprocess.run(["bash", "-c", "tmux -L v23n-no-such-server ls"], env=env,
                                  capture_output=True, text=True)
        self.assertEqual(done.returncode, 97, done.stderr)
        self.assertEqual(len(seen), 1, seen)

    def test_clustered_short_options_are_parsed_as_getopt_does(self):
        """RV-26. `-uS path`, `-uSpath` and `-2L name` are one cluster to tmux's getopt; a parser that stops at the
        cluster reads the socket path as the command and resolves the default server instead."""
        env = {"TMUX_TMPDIR": str(self.decoy_dir.parent)}
        by_name = os.path.realpath(self.decoy_dir.parent / f"tmux-{os.getuid()}" / "named")
        for argv, want in ((["tmux", "-uS", str(self.decoy), "ls"], str(self.decoy)),
                           (["tmux", f"-uS{self.decoy}", "ls"], str(self.decoy)),
                           (["tmux", "-2L", "named", "ls"], by_name),
                           (["tmux", "-2uLnamed", "ls"], by_name),
                           (["tmux", "-2", "-S", str(self.decoy), "ls"], str(self.decoy))):
            with self.subTest(argv=argv[1:3]):
                self.assertEqual(tests.tmux_server(argv, env), os.path.realpath(want))
        with tests.expect_tripwire() as seen:
            with self.assertRaises(tests.HostReached):
                subprocess.run(["tmux", "-uS", str(self.decoy), "ls"], capture_output=True)
            for cluster in (f"-uS '{self.decoy}'", f"-2uS'{self.decoy}'"):
                done = subprocess.run(["bash", "-c", f"tmux {cluster} ls"], env=self.child_env,
                                      capture_output=True, text=True)
                self.assertEqual(done.returncode, 97, cluster + " " + done.stderr)
                self.assertNotIn("decoy-live", done.stdout)
        self.assertEqual(len(seen), 3, seen)

    def test_the_test_whose_run_grew_the_tripwire_log_fails(self):
        """The record is what makes a SWALLOWED refusal still fail: a product that catches the non-zero exit
        and carries on would otherwise turn the refusal into a pass."""
        stub = os.environ["FLEET_CLAUDE_BIN"]

        class Swallows(unittest.TestCase):
            def test_it(self):
                subprocess.run([stub, "agents", "--json"], capture_output=True)   # rc ignored on purpose

            def test_clean(self):
                pass

        result = unittest.TestResult()
        with tests.expect_tripwire():
            unittest.defaultTestLoader.loadTestsFromTestCase(Swallows).run(result)
        self.assertEqual(result.testsRun, 2)
        self.assertEqual([t.id().rsplit(".", 1)[-1] for t, _ in result.failures], ["test_it"], result.failures)
        self.assertIn("tripwire", result.failures[0][1])


if __name__ == "__main__":
    unittest.main()
