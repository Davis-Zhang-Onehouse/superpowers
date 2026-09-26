"""Claude folder-trust prediction and the trust-screen recognizers (V23-P, FB-126).

The layout cases are the MEASURED matrix, not an invented one: each `test_case_*` rebuilds the layout
`trust-matrix.sh` built in the v23ptrustscreen instant (`evidence/01-trust-rule/`), with REAL git, and asserts
the outcome Claude Code 2.1.282 actually showed there (`RESULT.tsv`, 12/12 AGREE). A `.claude.json` is only
ever written inside the test's own temporary directory; nothing here reads the operator's config.
"""
import tests  # noqa: F401 — installs the suite's host boundary when this module runs alone (FB-118)
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fleet import trust

FIXTURES = Path(__file__).resolve().parents[1] / "it/fixtures/runtime"


#: The repository-selecting variables a caller may have exported; each would point git at another repo.
_GIT_SCRUB = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_CEILING_DIRECTORIES",
              "GIT_DISCOVERY_ACROSS_FILESYSTEM")


def _git(*argv):
    env = {k: v for k, v in os.environ.items() if k not in _GIT_SCRUB}
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *argv], check=True, env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _in_git(d: Path) -> bool:
    """True when `d` is inside a git work tree, or under any `.git` entry (which `trust.git_layout` treats as
    "git failed to answer" rather than "outside git")."""
    if any(os.path.lexists(a / ".git") for a in (d, *d.parents)):
        return True
    env = {k: v for k, v in os.environ.items() if k not in _GIT_SCRUB}
    try:
        r = subprocess.run(["git", "-C", str(d), "rev-parse", "--is-inside-work-tree"], env=env,
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return True
    return r.returncode == 0 and r.stdout.strip() == "true"


def _outside_git_root() -> Path:
    """RV-26. A temp root verified to be outside every git work tree. The cases below assert what happens OUTSIDE
    git (a walk "up to /", `(None, None)`), which silently assumed the system temp dir is not inside a checkout.
    The system temp dir first; if TMPDIR (or a stray `.git` above it) puts it inside git, a fixed fallback; if
    none qualifies, the test is skipped with the reason rather than failed."""
    tried = []
    for candidate in (tempfile.gettempdir(), "/var/tmp", "/tmp", "/dev/shm"):
        d = Path(candidate).resolve()
        if d.is_dir() and os.access(d, os.W_OK) and not _in_git(d):
            return d
        tried.append(str(d))
    raise unittest.SkipTest(f"no writable temp root outside every git work tree (tried {', '.join(tried)})")


class _Layout:
    """The trust-matrix layout: g (git, one commit) with g/sub, a linked worktree wt of g, a clone c2 of g,
    plain/sub (no git), and nest/inner (a git root under a plain dir)."""

    def __init__(self, root: Path):
        self.root = root
        self.g, self.wt, self.c2 = root / "g", root / "wt", root / "c2"
        self.plain, self.nest = root / "plain", root / "nest"
        _git("init", "-q", str(self.g))
        _git("-C", str(self.g), "commit", "-q", "--allow-empty", "-m", "i")
        (self.g / "sub").mkdir()
        (self.plain / "sub").mkdir(parents=True)
        _git("-C", str(self.g), "worktree", "add", "-q", "--detach", str(self.wt), "HEAD")
        _git("clone", "-q", str(self.g), str(self.c2))
        self.nest.mkdir()
        _git("init", "-q", str(self.nest / "inner"))


class PredictClaudeMatrixCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(dir=_outside_git_root())
        #: resolved, because git reports real paths and so does the screen
        cls.L = _Layout(Path(cls._tmp.name).resolve())

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def predict(self, cwd: Path, *trusted: Path, environ=None):
        with tempfile.TemporaryDirectory() as cfg:
            projects = {str(p): {"hasTrustDialogAccepted": True} for p in trusted}
            (Path(cfg) / ".claude.json").write_text(json.dumps(
                {"hasCompletedOnboarding": True, "numStartups": 5, "projects": projects}))
            return trust.predict_claude(cfg, cwd, environ=environ or {})

    def assertTrusted(self, got, key: Path):
        self.assertEqual((got.state, got.key), (trust.TRUSTED, str(key)), got)

    def assertUntrusted(self, got, cwd: Path):
        self.assertEqual((got.state, got.key), (trust.UNTRUSTED, str(cwd)), got)

    def test_case_A_plain_sub_no_records_is_untrusted(self):
        got = self.predict(self.L.plain / "sub")
        self.assertUntrusted(got, self.L.plain / "sub")
        #: RV-26. Ends with: "up to /" is a PREFIX of "up to /tmp/..." (a walk bounded at a toplevel).
        self.assertTrue(got.detail.endswith("up to /"), got.detail)

    def test_case_B_plain_trusted_covers_plain_sub(self):
        self.assertTrusted(self.predict(self.L.plain / "sub", self.L.plain), self.L.plain)

    def test_case_B2_root_trusted_covers_plain_sub(self):
        self.assertTrusted(self.predict(self.L.plain / "sub", self.L.root), self.L.root)

    def test_case_C_git_root_does_not_inherit_its_parent(self):
        got = self.predict(self.L.g, self.L.root)
        self.assertUntrusted(got, self.L.g)
        self.assertIn(f"(git toplevel {self.L.g})", got.detail)

    def test_case_D_g_sub_inherits_g(self):
        self.assertTrusted(self.predict(self.L.g / "sub", self.L.g), self.L.g)

    def test_case_E_g_sub_trusted_itself(self):
        self.assertTrusted(self.predict(self.L.g / "sub", self.L.g / "sub"), self.L.g / "sub")

    def test_case_E2_g_sub_does_not_inherit_above_the_toplevel(self):
        self.assertUntrusted(self.predict(self.L.g / "sub", self.L.root), self.L.g / "sub")

    def test_case_F_linked_worktree_inherits_the_main_worktree(self):
        self.assertTrusted(self.predict(self.L.wt, self.L.g), self.L.g)

    def test_case_G_linked_worktree_does_not_inherit_its_parent(self):
        self.assertUntrusted(self.predict(self.L.wt, self.L.root), self.L.wt)

    def test_case_G2_linked_worktree_trusted_itself(self):
        self.assertTrusted(self.predict(self.L.wt, self.L.wt), self.L.wt)

    def test_case_H_a_clone_does_not_inherit_its_origin(self):
        self.assertUntrusted(self.predict(self.L.c2, self.L.g), self.L.c2)

    def test_case_I_nested_git_root_does_not_inherit_the_plain_dir_above(self):
        self.assertUntrusted(self.predict(self.L.nest / "inner", self.L.nest), self.L.nest / "inner")

    def test_git_layout_reports_toplevel_and_canonical_root(self):
        self.assertEqual(trust.git_layout(self.L.g / "sub"), (self.L.g, self.L.g))
        self.assertEqual(trust.git_layout(self.L.wt), (self.L.wt, self.L.g))
        self.assertEqual(trust.git_layout(self.L.c2), (self.L.c2, self.L.c2))
        self.assertEqual(trust.git_layout(self.L.plain / "sub"), (None, None))

    def test_an_exported_git_dir_does_not_change_the_layout(self):
        """M1: GIT_DIR exported to another repo made `git_layout(plain/sub)` report THAT repo."""
        with mock.patch.dict(os.environ, {"GIT_DIR": str(self.L.g / ".git"),
                                          "GIT_WORK_TREE": str(self.L.g)}):
            self.assertEqual(trust.git_layout(self.L.plain / "sub"), (None, None))
            self.assertEqual(trust.git_layout(self.L.wt), (self.L.wt, self.L.g))

    def test_a_dotdot_cwd_walks_its_normalised_parents(self):
        """M2: `g/../plain/sub` lexically has `g` as a parent; Claude's cwd is `plain/sub`."""
        got = self.predict(self.L.g / ".." / "plain" / "sub", self.L.g)
        self.assertUntrusted(got, self.L.plain / "sub")

    def test_git_failing_inside_a_work_tree_is_unknown_not_a_walk_to_root(self):
        """I1: with git unable to answer inside g/sub, a walk to `/` would reach the trusted root and say
        TRUSTED where Claude (bounded at g, case E2) shows the screen."""
        for name, run in (("rc 128", lambda argv: (128, "")), ("did not run", lambda argv: None)):
            with self.subTest(name), tempfile.TemporaryDirectory() as cfg:
                (Path(cfg) / ".claude.json").write_text(json.dumps(
                    {"projects": {str(self.L.root): {"hasTrustDialogAccepted": True}}}))
                got = trust.predict_claude(cfg, self.L.g / "sub", environ={},
                                           layout=lambda cwd: trust.git_layout(cwd, run=run))
                self.assertEqual((got.state, got.key), (trust.UNKNOWN, ""), got)


class OutsideGitRootCase(unittest.TestCase):
    """RV-26. The chooser of the root every layout above is built under."""

    def test_a_temp_root_inside_a_work_tree_is_passed_over(self):
        with tempfile.TemporaryDirectory(dir="/var/tmp") as tmp:
            repo = Path(tmp).resolve() / "repo"
            _git("init", "-q", str(repo))
            (repo / "t").mkdir()
            with mock.patch.object(tempfile, "gettempdir", return_value=str(repo / "t")):
                self.assertTrue(_in_git(repo / "t"))
                self.assertNotEqual(repo / "t", _outside_git_root())
                self.assertFalse(_in_git(_outside_git_root()))

    def test_a_stray_dot_git_above_the_temp_root_counts_as_inside(self):
        with tempfile.TemporaryDirectory(dir="/var/tmp") as tmp:
            (Path(tmp) / ".git").mkdir()
            (Path(tmp) / "t").mkdir()
            self.assertTrue(_in_git(Path(tmp) / "t"))

    def test_no_candidate_outside_git_skips_with_the_reason(self):
        with mock.patch(f"{__name__}._in_git", return_value=True):
            with self.assertRaises(unittest.SkipTest) as caught:
                _outside_git_root()
        self.assertIn("outside every git work tree", str(caught.exception))


class PredictClaudeConfigCase(unittest.TestCase):
    """The config file's own failure modes. No git: the layout is injected as outside-git."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=_outside_git_root())
        self.addCleanup(self._tmp.cleanup)
        self.cfg = Path(self._tmp.name) / "cfg"
        self.cfg.mkdir()
        self.cwd = Path(self._tmp.name).resolve() / "work"
        self.cwd.mkdir()

    def predict(self, environ=None):
        return trust.predict_claude(self.cfg, self.cwd, environ=environ or {}, layout=lambda _: (None, None))

    def write(self, text: str):
        (self.cfg / ".claude.json").write_text(text)

    def test_missing_file_is_untrusted(self):
        got = self.predict()
        self.assertEqual((got.state, got.key), (trust.UNTRUSTED, str(self.cwd)))

    def test_projects_not_a_dict_is_unknown(self):
        self.write('{"projects": []}')
        self.assertEqual(self.predict().state, trust.UNKNOWN)

    def test_top_level_not_a_dict_is_unknown(self):
        self.write('[]')
        self.assertEqual(self.predict().state, trust.UNKNOWN)

    def test_not_json_is_unknown(self):
        self.write("not json")
        got = self.predict()
        self.assertEqual((got.state, got.key), (trust.UNKNOWN, ""))
        self.assertTrue(got.detail)

    @unittest.skipIf(os.geteuid() == 0, "root reads a mode-000 file")
    def test_unreadable_file_is_unknown(self):
        self.write(json.dumps({"projects": {str(self.cwd): {"hasTrustDialogAccepted": True}}}))
        os.chmod(self.cfg / ".claude.json", 0)
        self.addCleanup(os.chmod, self.cfg / ".claude.json", 0o600)
        self.assertEqual(self.predict().state, trust.UNKNOWN)

    def test_accepted_must_be_true_not_truthy(self):
        self.write(json.dumps({"projects": {str(self.cwd): {"hasTrustDialogAccepted": "yes"}}}))
        self.assertEqual(self.predict().state, trust.UNTRUSTED)

    def test_accepted_true_on_cwd_is_trusted(self):
        self.write(json.dumps({"projects": {str(self.cwd): {"hasTrustDialogAccepted": True}}}))
        got = self.predict()
        self.assertEqual((got.state, got.key), (trust.TRUSTED, str(self.cwd)))

    def test_sandboxed_env_is_trusted_without_reading_the_file(self):
        self.write("not json")
        got = self.predict(environ={"CLAUDE_CODE_SANDBOXED": "1"})
        self.assertEqual((got.state, got.key), (trust.TRUSTED, ""))
        self.assertIn("CLAUDE_CODE_SANDBOXED", got.detail)

    def test_codex_is_not_predicted(self):
        got = trust.predict("codex", self.cfg, self.cwd, environ={}, layout=lambda _: (None, None))
        self.assertEqual(got.state, trust.NOT_PREDICTED)
        self.assertEqual(got.detail,
                         "codex keeps folder trust in CODEX_HOME/config.toml; fleet does not predict it")

    def test_predict_claude_dispatches(self):
        self.assertEqual(trust.predict("claude", self.cfg, self.cwd, environ={},
                                       layout=lambda _: (None, None)).state, trust.UNTRUSTED)

    def test_git_layout_uses_the_injected_runner(self):
        seen = []

        def run(argv):
            seen.append(argv)
            return 0, "/r/wt\n/r/g/.git\n"
        self.assertEqual(trust.git_layout(Path("/r/wt/x"), run=run), (Path("/r/wt"), Path("/r/g")))
        self.assertEqual(trust.git_layout(Path("/x"), run=lambda argv: (128, "")), (None, None))
        self.assertEqual(seen[0][0], "git")

    def _predict_with_runner(self, run, *trusted):
        self.write(json.dumps({"projects": {str(p): {"hasTrustDialogAccepted": True} for p in trusted}}))
        return trust.predict_claude(self.cfg, self.cwd, environ={},
                                    layout=lambda cwd: trust.git_layout(cwd, run=run))

    def test_rc_128_in_a_plain_dir_still_walks_to_root(self):
        root = Path(self._tmp.name).resolve()
        got = self._predict_with_runner(lambda argv: (128, ""), root)
        self.assertEqual((got.state, got.key), (trust.TRUSTED, str(root)))
        got = self._predict_with_runner(lambda argv: (128, ""))
        self.assertEqual(got.state, trust.UNTRUSTED)
        self.assertTrue(got.detail.endswith("up to /"), got.detail)

    def test_rc_128_under_a_dot_git_entry_is_unknown(self):
        """git answering rc≠0 while an ancestor holds `.git` (a dir, or a worktree's file) is git failing to
        answer — dubious ownership, a ceiling, a broken repo — not "outside git"."""
        root = Path(self._tmp.name).resolve()
        dotgit = root / ".git"
        for kind in ("dir", "file"):
            with self.subTest(kind):
                dotgit.mkdir() if kind == "dir" else dotgit.write_text("gitdir: /nowhere\n")
                try:
                    got = self._predict_with_runner(lambda argv: (128, ""), root)
                finally:
                    dotgit.rmdir() if kind == "dir" else dotgit.unlink()
                self.assertEqual(got.state, trust.UNKNOWN, got)

    def test_git_that_cannot_run_is_unknown_even_in_a_plain_dir(self):
        self.assertEqual(self._predict_with_runner(lambda argv: None).state, trust.UNKNOWN)


class TrustScreenCase(unittest.TestCase):
    def frame(self, name: str) -> str:
        return (FIXTURES / name).read_text()

    def test_claude_2_1_282_trust_screen(self):
        self.assertEqual(trust.trust_screen_path("claude", self.frame("claude-trust-2.1.282.frame")),
                         "/tmp/v23p-m.YM7x/plain/sub")

    def test_claude_wrapped_path_is_joined_without_a_separator(self):
        self.assertEqual(trust.trust_screen_path("claude", self.frame("claude-trust-wrapped-2.1.282.frame")),
                         "/tmp/v23p-wrap.WLO3/a-deliberately-long-slot-directory-name/"
                         "that-wraps-past-eighty-columns/on-the-trust-screen")

    def test_OR4_claude_trust_phrase_wrapped_across_rows_is_still_the_trust_screen(self):
        """OR-4 (v23-p review). SYNTHETIC: the real 2.1.282 frame with its "Quick safety check" paragraph re-wrapped
        at narrower widths, so the word-wrap falls inside "one you trust" (between "one you" and "trust?", and
        between "one" and "you trust?"). The screen is still the trust screen, and its path still reads."""
        rows = self.frame("claude-trust-2.1.282.frame").splitlines()
        at = next(i for i, row in enumerate(rows) if "one you trust" in row)
        paragraph = " ".join(" ".join(rows[at:at + 2]).split())
        for cut in ("one you", "one"):
            with self.subTest(cut=cut):
                head, tail = paragraph.split(cut + " ", 1)
                wrapped = [" " + head + cut, " " + tail[:60], " " + tail[60:]]
                self.assertFalse(any("one you trust" in row for row in wrapped))
                frame = "\n".join(rows[:at] + wrapped + rows[at + 2:])
                self.assertEqual(trust.trust_screen_path("claude", frame), "/tmp/v23p-m.YM7x/plain/sub")

    def test_claude_under_home_draws_the_absolute_path(self):
        """Final review I3: measured on 2.1.282 with the cwd under a scratch HOME — the screen shows the absolute
        path, never `~/slot`."""
        self.assertEqual(trust.trust_screen_path("claude", self.frame("claude-trust-under-home-2.1.282.frame")),
                         "/tmp/v23p-home.d2Kb/home/slot")

    def test_claude_tui_is_not_a_trust_screen(self):
        self.assertIsNone(trust.trust_screen_path("claude", self.frame("claude-tui-2.1.282.frame")))

    def test_claude_older_build_trust_screen(self):
        self.assertEqual(trust.trust_screen_path("claude", self.frame("claude-dialog.frame")),
                         "/tmp/fleet-runtime-probe-8x14rwii/claude/project")

    def test_prose_quoting_the_screen_without_the_hint_row_is_not_a_trust_screen(self):
        prose = "\n".join([
            "● The screen asks whether this is a project you created or one you trust.",
            "  Accessing workspace:",
            "",
            "❯ ",
        ])
        self.assertIsNone(trust.trust_screen_path("claude", prose))

    def test_codex_0156_trust_screen(self):
        self.assertEqual(trust.trust_screen_path("codex", self.frame("codex-trust-0156.frame")),
                         "/home/ubuntu/.fb110-trust.N3eo/untrusted")

    def test_RV28_codex_0156_wrapped_path_is_joined(self):
        """RV-28. SYNTHETIC: no real codex frame with a wrapped path is committed. This takes the real 0.156 frame
        (118 columns wide) and replaces its path row with a path longer than the frame, split at the frame width
        into two rows of the same shape. Joined without a separator, as Claude's measured wrap is."""
        long_path = ("/home/ubuntu/.fb110-trust.N3eo/" + "a-deliberately-long-slot-directory-name/" * 3
                     + "untrusted")
        width = 118
        first, rest = long_path[:width - 2], long_path[width - 2:]
        rows = self.frame("codex-trust-0156.frame").splitlines()
        self.assertIn("/home/ubuntu/.fb110-trust.N3eo/untrusted", rows[2])
        rows[2:3] = [f"  \x1b[2m{first}\x1b[0m\x1b[39m\x1b[49m", f"  \x1b[2m{rest}\x1b[0m\x1b[39m\x1b[49m"]
        self.assertEqual(len(trust._ANSI.sub("", rows[2])), width)
        self.assertEqual(trust.trust_screen_path("codex", "\n".join(rows)), long_path)

    def test_codex_older_trust_screen(self):
        self.assertEqual(trust.trust_screen_path("codex", self.frame("codex-trust.frame")),
                         "/tmp/fleet-runtime-probe-8x14rwii/coordinator-probe/slot2")

    def test_codex_idle_is_not_a_trust_screen(self):
        self.assertIsNone(trust.trust_screen_path("codex", self.frame("codex-idle.frame")))

    def rendered(self, name: str) -> list:
        """The frame's rows with tmux's bottom padding dropped, as they appear when scrolled into history."""
        rows = self.frame(name).splitlines()
        while rows and not trust._ANSI.sub("", rows[-1]).strip():
            rows.pop()
        return rows

    def test_RV24_quoted_claude_trust_screen_above_the_idle_tui_is_not_a_trust_screen(self):
        """RV-24. A resumed pane redraws history; a trust screen QUOTED there (hint row and all) sits above the
        live prompt, outside the dialog window, and must not be read as the screen."""
        frame = "\n".join([*self.rendered("claude-trust-2.1.282.frame"), "",
                           self.frame("claude-tui-2.1.282.frame")])
        self.assertIsNone(trust.trust_screen_path("claude", frame))

    def test_RV24_quoted_codex_trust_screen_above_the_idle_tui_is_not_a_trust_screen(self):
        for quoted in ("codex-trust-0156.frame", "codex-trust.frame"):
            with self.subTest(quoted):
                frame = "\n".join([*self.rendered(quoted), "", self.frame("codex-idle.frame")])
                self.assertIsNone(trust.trust_screen_path("codex", frame))

    def test_RV24_one_prose_line_above_the_codex_idle_tui_is_not_a_trust_screen(self):
        frame = "\n".join(["• codex asks Trust this folder? on first launch.", self.frame("codex-idle.frame")])
        self.assertIsNone(trust.trust_screen_path("codex", frame))
        frame = "\n".join(["• codex asks Do you trust the contents of this directory? there.",
                           self.frame("codex-idle.frame")])
        self.assertIsNone(trust.trust_screen_path("codex", frame))

    def test_RV24_codex_screen_text_without_its_hint_row_is_not_a_trust_screen(self):
        """Neighbour: the 0.156 screen's text with the hint row removed (a partial redraw)."""
        rows = [r for r in self.rendered("codex-trust-0156.frame") if "enter" not in trust._ANSI.sub("", r)]
        self.assertIsNone(trust.trust_screen_path("codex", "\n".join(rows)))

    def test_RV24_another_confirm_dialog_below_a_quoted_trust_phrase_is_not_a_trust_screen(self):
        """Neighbour: the phrase sits above the last header-to-hint span, so it belongs to history, not the
        dialog that owns the hint row."""
        frame = "\n".join([*self.rendered("claude-trust-2.1.282.frame"), "",
                           " Allow this edit to settings.json?", "", " ❯ Yes", "   No", "",
                           " Enter to confirm · Esc to cancel"])
        # the quoted screen's own hint row is now above the window; the live one ends a dialog with no header
        # or trust phrase of its own
        self.assertIsNone(trust.trust_screen_path("claude", frame))

    def test_RV24_a_real_screen_below_quoted_history_names_its_own_path(self):
        """Neighbour: a quoted screen ABOVE a real one. The real screen's path, not the quoted one's."""
        quoted = [r.replace("/tmp/v23p-m.YM7x/plain/sub", "/home/ubuntu/davis_root/ws10")
                  for r in self.rendered("claude-trust-2.1.282.frame")]
        frame = "\n".join([*quoted, "", self.frame("claude-trust-2.1.282.frame")])
        self.assertEqual(trust.trust_screen_path("claude", frame), "/tmp/v23p-m.YM7x/plain/sub")
        quoted = [r.replace("/home/ubuntu/.fb110-trust.N3eo/untrusted", "/elsewhere")
                  for r in self.rendered("codex-trust-0156.frame")]
        frame = "\n".join([*quoted, "", self.frame("codex-trust-0156.frame")])
        self.assertEqual(trust.trust_screen_path("codex", frame), "/home/ubuntu/.fb110-trust.N3eo/untrusted")

    def test_runtimes_do_not_cross(self):
        self.assertIsNone(trust.trust_screen_path("codex", self.frame("claude-trust-2.1.282.frame")))
        self.assertIsNone(trust.trust_screen_path("claude", self.frame("codex-trust-0156.frame")))


class TrustGitSeamCase(unittest.TestCase):
    """V23-P fix round 1 (F1). trust's git goes through `workspace.default_git`, the package's documented git
    seam (FI-27a keeps three spawn seams), with an OPT-IN scrub and timeout that leave other callers as they were."""

    def test_default_git_with_scrub_env_drops_the_variable(self):
        from fleet.workspace import default_git
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "r"
            _git("init", "-q", str(repo))
            with mock.patch.dict(os.environ, {"GIT_DIR": str(Path(tmp) / "no-such-repo")}):
                rc_plain, _ = default_git()(["rev-parse", "--git-dir"], repo)
                rc, out = default_git(scrub_env=("GIT_DIR",), timeout=5)(["rev-parse", "--absolute-git-dir"], repo)
        self.assertNotEqual(0, rc_plain, "without the scrub the exported GIT_DIR must still apply (unchanged)")
        self.assertEqual(0, rc)
        self.assertEqual((repo / ".git").resolve(), Path(out.strip()).resolve())

    def test_trust_spawns_nothing_itself(self):
        import ast
        tree = ast.parse(Path(trust.__file__).read_text())
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names} | {node.module for node in ast.walk(tree)
                                                if isinstance(node, ast.ImportFrom)}
        self.assertNotIn("subprocess", imported)

    def test_a_git_that_times_out_or_cannot_start_reads_as_none(self):
        for exc in (subprocess.TimeoutExpired(["git"], 5), FileNotFoundError("git"), NotADirectoryError("x")):
            def runner(args, cwd, exc=exc):
                raise exc
            with mock.patch("fleet.workspace.default_git", return_value=runner):
                self.assertIsNone(trust._run(["git", "-C", "/tmp", "rev-parse", "--show-toplevel"]))

    def test_the_run_adapter_strips_git_and_passes_the_args(self):
        seen = []
        with mock.patch("fleet.workspace.default_git",
                        return_value=lambda args, cwd: (seen.append((list(args), str(cwd))), (0, "x\n"))[1]):
            self.assertEqual((0, "x\n"), trust._run(["git", "-C", "/some/dir", "rev-parse"]))
        self.assertEqual(["-C", "/some/dir", "rev-parse"], seen[0][0])


if __name__ == "__main__":
    unittest.main()
