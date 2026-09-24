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


if __name__ == "__main__":
    unittest.main()
