"""The shell launchers beside `bin/fleet` — which binary they run, and whether they can be run at all.

Two defects, one per class below, and each class is the control that would have caught its own defect.

FB-56. `fleet dispatch` exports `FLEET_BIN` into every worker it starts (`runtime_launch.prepare`), naming
the fleet that ran dispatch, so the worker's own `"$FLEET_BIN"` resolves its dispatcher. Five launchers
read that same name as their test seam, so in any dispatched session they ran the DISPATCHER'S binary
instead of the one they ship beside. For a release worker that is the deployed copy, and `release-gate.sh`
would run `release-verify` from it. The seam is now `FLEET_LAUNCHER_TEST_BIN`, which nothing exports.

FB-31. `scripts/release-postflight.sh` was committed at mode 100644, so the documented
`scripts/release-postflight.sh X.Y.Z` failed with rc=126 for two release workers in a row. Nothing checked
the bit.
"""
import os
import pathlib
import runpy
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Every launcher that resolves a fleet binary, each driven down a path that reaches its first fleet call
#: from a private root. `(label, argv)` — argv is relative to REPO.
LAUNCHERS = (
    ("release-gate.sh", ["bash", "scripts/release-gate.sh", "9.9.9"]),
    ("release-preflight.sh", ["bash", "scripts/release-preflight.sh"]),
    ("fleet-revive.sh", ["bash", "scripts/fleet-revive.sh", "plan"]),
    ("fleet-finished-pids.sh", ["bash", "scripts/fleet-finished-pids.sh", "--finished-pids"]),
    ("fleet-view", ["python3", "bin/fleet-view", "board", "--no-color"]),
)


class LauncherBinaryCase(unittest.TestCase):
    """FB-56: an ambient `FLEET_BIN` is never executed; the named test seam still is."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-launchers-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ambient = self.decoy("ambient")
        self.named = self.decoy("named")
        self.home = self.tmp / "home"
        self.root = self.home / "root"
        (self.root / ".fleet").mkdir(parents=True)
        (self.root / ".fleet-root").write_text('{"name": "launcherprobe"}\n')
        (self.tmp / "rel" / "fleet-v9.9.9" / ".release" / "evidence").mkdir(parents=True)

    def decoy(self, name):
        """A fake `fleet` that records its argv and prints nothing. Returns (binary, calls file)."""
        calls = self.tmp / f"{name}.calls"
        binary = self.tmp / f"{name}-fleet"
        binary.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "{calls}"\nexit 0\n')
        binary.chmod(0o755)
        return binary, calls

    def run_launcher(self, argv, _repo=REPO, **extra):
        """Run one launcher from the private root and return `{decoy name: argv lines it recorded}`. The
        environment is BUILT, not inherited, so nothing the person running the suite exported (a dispatched
        session's FLEET_ROOT, FLEET_BIN …) can reach it."""
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.home),
               "FLEET_HOME": str(self.root / ".fleet"), "FLEET_RELEASES": str(self.tmp / "rel"),
               "FLEET_TMUX_SOCKET": "itfleet-launchers-nobody", "RELEASE_GATE_POLL": "0.05",
               "TMUX_TMPDIR": str(self.tmp),
               # preflight's own seam for the socket directories it scans; its default globs every
               # /tmp/tmux-*/ server on the box, which a test has no business listing
               "RELEASE_PREFLIGHT_TMUX_DIRS": str(self.tmp) + "/"}
        env.update(extra)
        for _, calls in (self.ambient, self.named):
            if calls.exists():
                calls.unlink()
        argv = [argv[0], str(_repo / argv[1]), *argv[2:]]
        subprocess.run(argv, cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        return {name: calls.read_text() if calls.exists() else ""
                for name, (_, calls) in (("ambient", self.ambient), ("named", self.named))}

    def test_an_ambient_fleet_bin_is_never_executed(self):
        """Both variables set, as in a dispatched session running a test: the ambient decoy must not run,
        and the named one must. The second half is the positive control. Without it this case would also
        pass for a launcher whose driven path never reaches a fleet call at all. It also means no case here
        ever runs a REAL fleet: for `release-gate.sh` that would be a detached `release-verify`."""
        for label, argv in LAUNCHERS:
            with self.subTest(launcher=label):
                ran = self.run_launcher(argv, FLEET_BIN=str(self.ambient[0]),
                                        FLEET_LAUNCHER_TEST_BIN=str(self.named[0]))
                self.assertEqual(ran["ambient"], "",
                                 f"{label} executed the ambient FLEET_BIN ({ran['ambient'].strip()!r}); a "
                                 f"dispatched session's FLEET_BIN names the dispatcher's fleet, not the one "
                                 f"this launcher ships beside")
                self.assertNotEqual(ran["named"], "",
                                    f"{label} never ran FLEET_LAUNCHER_TEST_BIN, so this driven path does "
                                    f"not reach a fleet call and the assertion above is vacuous")

    def test_with_only_an_ambient_fleet_bin_the_sibling_binary_acts(self):
        """The dispatched shape exactly: `FLEET_BIN` set, no seam. The binary that must act is the one the
        launcher ships beside, so each launcher runs from a scratch COPY of `scripts/` and `bin/fleet-view`
        whose `bin/fleet` is a recording decoy. Asserting only that the ambient decoy stayed silent would
        also pass for a default quietly changed to the deployed copy, or for a launcher that exits before
        any fleet call (RV-24). The copy also means `release-gate.sh` is safe to include here: its sibling
        is the decoy, not a real `release-verify`."""
        copy = self.tmp / "copy"
        shutil.copytree(REPO / "scripts", copy / "scripts", symlinks=True)
        (copy / "bin").mkdir()
        shutil.copy2(REPO / "bin" / "fleet-view", copy / "bin" / "fleet-view")
        sibling_calls = self.tmp / "sibling.calls"
        sibling = copy / "bin" / "fleet"
        sibling.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "{sibling_calls}"\nexit 0\n')
        sibling.chmod(0o755)
        for label, argv in LAUNCHERS:
            with self.subTest(launcher=label):
                if sibling_calls.exists():
                    sibling_calls.unlink()
                ran = self.run_launcher(argv, _repo=copy, FLEET_BIN=str(self.ambient[0]))
                self.assertEqual(ran["ambient"], "",
                                 f"{label} executed the ambient FLEET_BIN ({ran['ambient'].strip()!r})")
                self.assertNotEqual(sibling_calls.read_text() if sibling_calls.exists() else "", "",
                                    f"{label} never ran the bin/fleet it ships beside")


def tracked_files(prefixes):
    """`(relative path, index mode)` for every tracked regular file under `prefixes`, read from the git
    INDEX when there is one. The index is what a clone and a release export receive, so a mode that was
    only ever fixed on disk is still the defect. A copy with no git falls back to the filesystem."""
    git = shutil.which("git")
    if git and (REPO / ".git").exists():
        out = subprocess.run([git, "-C", str(REPO), "ls-files", "-s", "--", *prefixes],
                             capture_output=True, text=True, check=True).stdout
        for line in out.splitlines():
            meta, path = line.split("\t", 1)
            mode = meta.split()[0]
            if mode in ("100644", "100755"):
                yield path, mode
        return
    for prefix in prefixes:
        for path in sorted((REPO / prefix).rglob("*")):
            if path.is_file() and not path.is_symlink():
                yield str(path.relative_to(REPO)), "100755" if os.access(path, os.X_OK) else "100644"


class ExecutableBitCase(unittest.TestCase):
    """FB-31: a file under `scripts/` or `bin/` that starts with `#!` is meant to be run, so it is
    executable. The sourced-only helpers (`scripts/fleet-env.sh`, `scripts/sync/lib.sh`) carry no
    shebang, and this rule is how they are told apart."""

    def test_every_shebang_script_is_executable(self):
        seen, wrong = [], []
        for rel, mode in tracked_files(["scripts", "bin"]):
            with open(REPO / rel, "rb") as handle:
                if handle.read(2) != b"#!":
                    continue
            seen.append(rel)
            if mode != "100755":
                wrong.append(f"{rel} ({mode})")
        # Absence is not a pass: a census that found no scripts measured nothing.
        self.assertIn("scripts/release-postflight.sh", seen, "the census did not see the file FB-31 is about")
        self.assertEqual(wrong, [], f"{len(wrong)} of {len(seen)} shebang scripts are not executable in the "
                                    f"index; `git update-index --chmod=+x` them: {', '.join(wrong)}")


if __name__ == "__main__":
    unittest.main()


class TestFleetViewStates(unittest.TestCase):
    def test_complete_but_working_has_visible_glyph(self):
        styles = runpy.run_path(str(REPO / "bin" / "fleet-view"))["STATE_STYLE"]
        self.assertIn("COMPLETE-BUT-WORKING", styles)
        self.assertNotEqual(" ", styles["COMPLETE-BUT-WORKING"][1])
