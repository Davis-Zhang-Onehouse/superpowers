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
