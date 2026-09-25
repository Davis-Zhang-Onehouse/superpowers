"""FB-117: a fleet-launched codex worker leaves no sandbox mount-point residue in the store or the instants tree.

Measured with the real codex-cli 0.156.1 sandbox (v23-n evidence/01-red/repro-fb117-codex-mount-residue.*): every
writable root gets read-only mounts at `.agents`, `.codex` and `.git`, and when the path does not exist codex makes an
EMPTY host directory as the mount target. It removes them when the sandboxed command ends cleanly. After a SIGKILL of
the command's group they stay, and the next clean run forgets them, so they are permanent. fleet passes `$FLEET_HOME`
and the instants tree as writable roots, and ends a codex worker by killing its tmux session.

So `close` and `harvest --id` of a CODEX record sweep what they can PROVE is that residue — exactly those three names,
a real directory, empty, not a mount point — and only when no codex whose argv names that root is alive. Everything
else is kept and said.
"""
import json
import os
import pathlib
import shutil
import tempfile
import unittest

from tests.test_cli import Fleet

RESIDUE = (".agents", ".codex", ".git")


def plant(root: pathlib.Path) -> None:
    for name in RESIDUE:
        (root / name).mkdir(parents=True, exist_ok=True)


def left(root: pathlib.Path) -> list:
    return sorted(name for name in RESIDUE if os.path.lexists(root / name))


def fake_process(proc: pathlib.Path, pid: int, *argv: str) -> None:
    (proc / str(pid)).mkdir(parents=True, exist_ok=True)
    (proc / str(pid) / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")


class SweepCase(unittest.TestCase):
    """The sweep itself, over a real filesystem and a fixture /proc."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-residue-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "instants"
        self.root.mkdir()
        self.proc = self.tmp / "proc"
        fake_process(self.proc, 1, "/sbin/init")

    def sweep(self, *roots, dry_run=False):
        from fleet.runtime_launch import sweep_mount_residue
        return sweep_mount_residue(roots or (self.root,), proc_root=self.proc, dry_run=dry_run)

    def test_empty_mount_targets_are_removed_and_said(self):
        plant(self.root)
        rows = self.sweep()
        self.assertEqual(left(self.root), [])
        self.assertEqual(sorted(pathlib.Path(p).name for p, v in rows if v.startswith("removed")), sorted(RESIDUE), rows)

    def test_nothing_but_the_three_names_is_touched(self):
        plant(self.root)
        (self.root / "other").mkdir()
        (self.root / ".gitignore").write_text("x\n")
        self.sweep()
        self.assertTrue((self.root / "other").is_dir())
        self.assertTrue((self.root / ".gitignore").is_file())

    def test_a_real_repository_a_non_empty_dir_a_file_and_a_symlink_are_kept(self):
        (self.root / ".git").mkdir()
        (self.root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        (self.root / ".codex").mkdir()
        (self.root / ".codex" / "config.toml").write_text("")
        (self.root / ".agents").symlink_to(self.tmp)            # an EMPTY-looking target is not the point: it is a link
        #: The dry run first: rmdir would refuse a non-empty directory anyway, so the emptiness check is what keeps
        #: the dry run from promising to remove a real repository.
        planned = self.sweep(dry_run=True)
        self.assertFalse(any(v.startswith("would remove") for _, v in planned), planned)
        rows = self.sweep()
        self.assertEqual(left(self.root), sorted(RESIDUE))
        self.assertTrue((self.root / ".git" / "HEAD").exists())
        self.assertFalse(any(v.startswith("removed") for _, v in rows), rows)
        (self.root / ".agents").unlink()
        (self.root / ".agents").write_text("")
        self.sweep()
        self.assertTrue((self.root / ".agents").is_file())

    def test_a_live_codex_under_the_root_keeps_everything_in_each_argv_shape(self):
        root = str(self.root.resolve())
        shapes = {
            "tui": ("node", "/x/bin/codex", "-a", "never", "-s", "workspace-write", "--add-dir", root),
            "native": ("/x/vendor/codex", "resume", "--add-dir", root, "--", "sid"),
            "helper": ("codex-linux-sandbox", "--permission-profile",
                       json.dumps({"entries": [{"path": {"type": "path", "path": root}}]})),
            "bwrap": ("bwrap", "--ro-bind", "/", "/", "--bind", root, root, "--", "sleep", "9"),
        }
        for n, (shape, argv) in enumerate(shapes.items()):
            with self.subTest(shape=shape):
                shutil.rmtree(self.proc)
                fake_process(self.proc, 1, "/sbin/init")
                fake_process(self.proc, 4000 + n, *argv)
                plant(self.root)
                rows = self.sweep()
                self.assertEqual(left(self.root), sorted(RESIDUE), f"{shape}: swept under a live codex: {rows}")
                self.assertTrue(any(str(4000 + n) in v for _, v in rows), rows)

    def test_a_codex_under_ANOTHER_root_or_a_non_codex_naming_this_one_does_not_block(self):
        fake_process(self.proc, 4100, "node", "/x/bin/codex", "--add-dir", str(self.tmp / "elsewhere"))
        fake_process(self.proc, 4101, "vim", str(self.root.resolve()))
        plant(self.root)
        self.sweep()
        self.assertEqual(left(self.root), [])

    def test_a_codex_that_starts_between_the_census_and_the_rmdir_keeps_the_rest(self):
        """RV-33. The census is repeated immediately before each rmdir: a sandbox that starts after the first look has
        just made these directories its live mount targets."""
        from unittest import mock
        from fleet import runtime_launch
        plant(self.root)
        answers = iter([[], [], [4300], [4300]])
        with mock.patch.object(runtime_launch, "codex_sandboxes_under", side_effect=lambda *a, **k: next(answers)):
            rows = self.sweep()
        self.assertEqual(len(left(self.root)), 2, rows)
        self.assertEqual(sum(v.startswith("kept") and "4300" in v for _, v in rows), 2, rows)

    def test_holder_detection_fails_closed_on_the_edges(self):
        """RV-34. An unreadable cmdline (hidepid, another user) is not an exited process; a census taken inside a nested
        PID namespace sees only that namespace; `--add-dir=<root>` and `<root>/` name the root too."""
        root = str(self.root.resolve())
        cases = {
            "unreadable cmdline": lambda: (fake_process(self.proc, 4400, "x"), (self.proc / "4400" / "cmdline").chmod(0)),
            "nested pid namespace": lambda: ((self.proc / "self").mkdir(),
                                             (self.proc / "self" / "status").write_text("Name:\tpython3\nNSpid:\t77\t3\n")),
            "--add-dir=<root>": lambda: fake_process(self.proc, 4401, "node", "/x/bin/codex", f"--add-dir={root}"),
            "<root>/ spelling": lambda: fake_process(self.proc, 4402, "/x/codex", "--add-dir", root + "/"),
        }
        for label, arrange in cases.items():
            with self.subTest(label):
                shutil.rmtree(self.proc)
                fake_process(self.proc, 1, "/sbin/init")
                arrange()
                plant(self.root)
                rows = self.sweep()
                self.assertEqual(left(self.root), sorted(RESIDUE), f"{label}: {rows}")

    def test_an_unreadable_process_table_keeps_everything(self):
        plant(self.root)
        from fleet.runtime_launch import sweep_mount_residue
        rows = sweep_mount_residue((self.root,), proc_root=self.tmp / "no-such-proc")
        self.assertEqual(left(self.root), sorted(RESIDUE), rows)

    def test_a_caller_inside_a_codex_sandbox_keeps_everything(self):
        """A codex caller's /proc is its sandbox's PID namespace — measured on 0.156.1: pid 1 is `codex-linux-sandbox`
        and four pids are visible — so no other worker can be seen, and an empty answer would prove nothing."""
        fake_process(self.proc, 1, "codex-linux-sandbox", "--sandbox-policy-cwd", "/slot", "--command-cwd", "/slot")
        plant(self.root)
        rows = self.sweep()
        self.assertEqual(left(self.root), sorted(RESIDUE), rows)

    def test_a_dry_run_removes_nothing_and_says_what_it_would(self):
        plant(self.root)
        rows = self.sweep(dry_run=True)
        self.assertEqual(left(self.root), sorted(RESIDUE))
        self.assertEqual(len([v for _, v in rows if v.startswith("would remove")]), 3, rows)

    def test_a_clean_root_is_reported_as_examined(self):
        rows = self.sweep()
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("examined", rows[0][1])


class VerbCase(unittest.TestCase):
    """`close` and `harvest --id` run the sweep over the store and the instants root for a codex record."""

    def setUp(self):
        self.f = Fleet()
        self.addCleanup(shutil.rmtree, self.f.tmp, True)
        self.proc = self.f.tmp / "proc"
        fake_process(self.proc, 1, "/sbin/init")
        build = self.f.context

        def context():
            inner = build()

            def ctx(parsed, out, err):
                made = inner(parsed, out, err)
                made.proc_root = self.proc
                return made
            return ctx
        self.f.context = context

    def codex_worker(self, name, **kw):
        path = self.f.worker(name, live=False, **kw)
        record = self.f.store.read(self.f.ids[name])
        record.runtime = "codex"
        self.f.store.write(record)
        return path

    def roots(self):
        return (self.f.home, self.f.instants)

    def test_close_of_a_codex_worker_sweeps_the_store_and_the_instants_root(self):
        self.codex_worker("cx")
        for root in self.roots():
            plant(root)
        code, out, err = self.f.run(["close", "--id", self.f.ids["cx"]])
        self.assertEqual(code, 0, err)
        for root in self.roots():
            self.assertEqual(left(root), [], f"{root}: {out}")
        self.assertIn("codex", out)

    def test_close_leaves_residue_while_another_codex_names_the_root(self):
        self.codex_worker("cx")
        plant(self.f.instants)
        fake_process(self.proc, 4200, "node", "/x/bin/codex", "--add-dir", str(self.f.instants.resolve()))
        code, out, err = self.f.run(["close", "--id", self.f.ids["cx"]])
        self.assertEqual(code, 0, err)
        self.assertEqual(left(self.f.instants), sorted(RESIDUE), out)
        self.assertIn("4200", out)

    def test_close_of_a_claude_worker_does_not_sweep(self):
        self.f.worker("cl", live=False)
        plant(self.f.instants)
        self.assertEqual(self.f.run(["close", "--id", self.f.ids["cl"]])[0], 0)
        self.assertEqual(left(self.f.instants), sorted(RESIDUE))

    def test_a_dry_run_close_sweeps_nothing(self):
        self.codex_worker("cx")
        plant(self.f.instants)
        code, out, err = self.f.run(["close", "--id", self.f.ids["cx"], "--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertEqual(left(self.f.instants), sorted(RESIDUE), out)

    def test_harvest_of_a_codex_worker_sweeps(self):
        path = self.codex_worker("cxh", state="complete", slot="ws1")
        self.f.reviewed(path)
        plant(self.f.instants)
        code, out, err = self.f.run(["harvest", "--id", self.f.ids["cxh"]])
        self.assertTrue(self.f.store.read(self.f.ids["cxh"]).harvested_at, f"harvest did not run: {out}{err}")
        self.assertEqual(left(self.f.instants), [], out)


if __name__ == "__main__":
    unittest.main()
