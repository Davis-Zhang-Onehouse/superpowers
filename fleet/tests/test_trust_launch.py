"""V23-P (FB-126): `dispatch` and `revive` predict, watch and report a launch that stops at Claude Code's
folder-trust screen.

At base both verbs verified the launch by the worker's ARGV, which is right the moment the process execs — while
the pane itself sits at the trust screen waiting for a human. The output was plain success. These cases drive the
hermetic `Fleet` fixture (no tmux, no claude, no real sleep) with an injected `ctx.launch_watch`, and drive
`_watch_launch` itself over the real 2.1.282 trust frame.
"""
import io
import json
import os
import pathlib
import unittest
from unittest import mock

from fleet import cli
from fleet.runtime import LaunchSettings
from tests.test_cli import FRESH_BASE_DIGITS, CliCase, hermetic_environment

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "it" / "fixtures" / "runtime"
TRUST_FRAME = (FIXTURES / "claude-trust-2.1.282.frame").read_text()
TRUST_FRAME_PATH = "/tmp/v23p-m.YM7x/plain/sub"


def rows_of(out: str) -> dict:
    rows = {}
    for line in out.splitlines():
        key, _, value = line.partition("\t")
        rows.setdefault(key, value)
    return rows


class Watch:
    """An injected `ctx.launch_watch`: records each call and answers with `answer(tmux, runtime)`."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, tmux, runtime):
        self.calls.append((tmux, runtime))
        return self.answer(tmux, runtime)


def inject(fleet, watch=None, config_dir=None):
    """Wrap the fixture's `context()` builder: set `ctx.launch_watch`, and optionally the config dir."""
    base = type(fleet).context(fleet)

    def build(parsed, out, err):
        ctx = base(parsed, out, err)
        if watch is not None:
            ctx.launch_watch = watch
        if config_dir is not None:
            ctx.launch_settings = lambda runtime, slot: LaunchSettings(runtime, "/test/bin/" + runtime,
                                                                       str(config_dir))
        return ctx

    fleet.context = lambda: build


def run_interrupted(case, fleet, argv):
    """`Fleet.run`, but for a verb that must RAISE KeyboardInterrupt: the stdout written before the raise is kept."""
    out, err = io.StringIO(), io.StringIO()
    with hermetic_environment(fleet.instants, home=fleet.tmp):
        prior_cwd = os.getcwd()
        os.chdir(fleet.tmp)
        try:
            with case.assertRaises(KeyboardInterrupt):
                cli.main(list(argv), stdout=out, stderr=err, context=fleet.context())
        finally:
            os.chdir(prior_cwd)
    return out.getvalue(), err.getvalue()


def interrupting(tmux, runtime):
    raise KeyboardInterrupt


def dispatch_argv(fleet, title, *extra):
    return ["dispatch", "--porcelain", "--profile", str(fleet.profile("worker")), "--title", title,
            "--base", FRESH_BASE_DIGITS, "--optype", "append", "--slot", "ws4", *extra]


class TestDispatchReportsTheTrustScreen(CliCase):

    def test_a_launch_at_the_trust_screen_naming_the_slot_exits_0_and_says_so(self):
        fleet = self.loaded()
        slot = str(fleet.pool.slot_path("ws4"))
        inject(fleet, Watch(lambda tmux, runtime: cli.LaunchWatch("trust-screen", path=slot)))
        code, out, err = fleet.run(dispatch_argv(fleet, "trustScreen"))
        self.assertEqual(0, code, out + err)
        rows = rows_of(out)
        self.assertTrue(rows["trust_screen"].startswith("observed"), rows)
        #: The session name is the camel-folded title (`title_as_used`), not --title as typed.
        self.assertIn("dt-trustscreen", rows["trust_screen"])
        self.assertEqual(slot, rows["trust_screen_path"])
        self.assertEqual("yes", rows["trust_screen_is_slot"])
        self.assertIn("dt-trustscreen", err)
        self.assertIn("folder-trust screen", err)
        keys = [line.split("\t")[0] for line in out.splitlines()]
        self.assertLess(keys.index("launched_at"), keys.index("trust"))
        self.assertLess(keys.index("trust"), keys.index("trust_screen"))

    def test_the_claude_remedy_says_the_coordinator_or_operator_answers_it(self):
        """Final review: whoever reads the row may be the coordinator, so the row names both."""
        fleet = self.loaded()
        slot = str(fleet.pool.slot_path("ws4"))
        inject(fleet, Watch(lambda tmux, runtime: cli.LaunchWatch("trust-screen", path=slot)))
        code, out, err = fleet.run(dispatch_argv(fleet, "claudeRemedy"))
        self.assertEqual(0, code, out + err)
        rows = rows_of(out)
        self.assertIn("the coordinator or operator answers it once on the pane", rows["trust_screen"])
        self.assertIn('press Down to "Yes, I trust this folder"', rows["trust_screen"])
        self.assertIn("the coordinator or operator answers it once on the pane", rows["trust"])

    def test_a_codex_trust_screen_gets_the_codex_remedy_and_never_down(self):
        """Final review I1: on codex the first option (trust and continue) is already selected; Down+Enter QUITS."""
        fleet = self.loaded()
        slot = str(fleet.pool.slot_path("ws4"))
        watch = Watch(lambda tmux, runtime: cli.LaunchWatch("trust-screen", path=slot))
        inject(fleet, watch)
        code, out, err = fleet.run(dispatch_argv(fleet, "codexScreen", "--runtime", "codex"))
        self.assertEqual(0, code, out + err)
        self.assertEqual("codex", watch.calls[0][1])
        rows = rows_of(out)
        remedy = rows["trust_screen"]
        self.assertTrue(remedy.startswith("observed — the slot's folder is not trusted by codex"), remedy)
        self.assertIn("the first option (trust and continue) is already selected", remedy)
        self.assertIn("CODEX_HOME/config.toml", remedy)
        self.assertIn("the coordinator or operator answers it once on the pane", remedy)
        self.assertNotIn("Down", remedy)
        self.assertNotIn("Claude", remedy)
        self.assertEqual("yes", rows["trust_screen_is_slot"])
        self.assertNotIn("Claude Code", err)

    def test_an_interrupted_watch_still_prints_the_launch_and_reraises(self):
        """Final review I2 (RV-C5): the launch is recorded and the milestone claimed before the watch, so an
        interrupt there must still print todo_id — its absence means nothing started."""
        fleet = self.loaded()
        inject(fleet, Watch(interrupting))
        out, err = run_interrupted(self, fleet, dispatch_argv(fleet, "watchInterrupted"))
        rows = rows_of(out)
        self.assertIn("todo_id", rows, out + err)
        self.assertIn("instant", rows)
        self.assertTrue(rows["trust_screen"].startswith("unobserved — the watch was interrupted"), rows)
        self.assertIn("fleet pane-guard --pane", rows["trust_screen"])
        self.assertIn("trust", rows)
        self.assertTrue(any(r.title == "watchInterrupted" and r.launched_at for r in fleet.store.all()))

    def test_a_trust_screen_naming_another_folder_says_NO(self):
        fleet = self.loaded()
        inject(fleet, Watch(lambda tmux, runtime: cli.LaunchWatch("trust-screen", path="/somewhere/else")))
        code, out, err = fleet.run(dispatch_argv(fleet, "elsewhereScreen"))
        self.assertEqual(0, code, out + err)
        self.assertTrue(rows_of(out)["trust_screen_is_slot"].startswith("NO"), out)
        self.assertIn("/somewhere/else", rows_of(out)["trust_screen_is_slot"])

    def test_a_ready_launch_reports_none_and_no_path(self):
        fleet = self.loaded()
        inject(fleet, Watch(lambda tmux, runtime: cli.LaunchWatch("ready")))
        code, out, err = fleet.run(dispatch_argv(fleet, "readyLaunch"))
        self.assertEqual(0, code, out + err)
        rows = rows_of(out)
        self.assertTrue(rows["trust_screen"].startswith("none"), rows)
        self.assertNotIn("trust_screen_path", rows)
        self.assertNotIn("folder-trust screen", err)

    def test_another_dialog_is_named_as_a_launch_dialog(self):
        fleet = self.loaded()
        inject(fleet, Watch(lambda tmux, runtime: cli.LaunchWatch("dialog")))
        code, out, err = fleet.run(dispatch_argv(fleet, "dialogLaunch"))
        self.assertEqual(0, code, out + err)
        rows = rows_of(out)
        self.assertTrue(rows["trust_screen"].startswith("none — but"), rows)
        self.assertEqual("observed", rows["launch_dialog"])

    def test_a_watch_that_raises_is_unobserved_and_the_launch_stands(self):
        fleet = self.loaded()

        def boom(tmux, runtime):
            raise OSError("capture exploded")

        inject(fleet, Watch(boom))
        code, out, err = fleet.run(dispatch_argv(fleet, "watchRaises"))
        self.assertEqual(0, code, out + err)
        self.assertTrue(rows_of(out)["trust_screen"].startswith("unobserved"), out)
        self.assertIn("capture exploded", rows_of(out)["trust_screen"])
        self.assertTrue(any(r.title == "watchRaises" and r.launched_at for r in fleet.store.all()))

    def test_the_prediction_is_made_before_the_pane_starts_with_the_launchers_env(self):
        """Fix round 1 (F3): predicted before `sessions.start`, from the environment the launcher gets."""
        fleet = self.loaded()
        inject(fleet, Watch(lambda tmux, runtime: cli.LaunchWatch("ready")))
        seen = []
        real = cli._predict_trust

        def spy(ctx, settings, cwd, environ=None):
            seen.append((len(fleet.started), dict(environ or {})))
            return real(ctx, settings, cwd, environ=environ)

        with mock.patch.object(cli, "_predict_trust", spy):
            code, out, err = fleet.run(dispatch_argv(fleet, "predictFirst"))
        self.assertEqual(0, code, out + err)
        self.assertEqual(1, len(seen))
        started_before, environ = seen[0]
        self.assertEqual(0, started_before, "the prediction ran after the pane was started")
        self.assertEqual(str(fleet.home), environ.get("FLEET_HOME"), "not the launcher's environment")
        self.assertIn("trust", rows_of(out))

    def test_the_dry_run_prints_a_trust_row_and_never_watches(self):
        fleet = self.loaded()
        watch = Watch(lambda tmux, runtime: cli.LaunchWatch("ready"))
        inject(fleet, watch)
        code, out, err = fleet.run(dispatch_argv(fleet, "dryTrust", "--dry-run"))
        self.assertEqual(0, code, out + err)
        self.assertIn("trust", rows_of(out))
        self.assertTrue(rows_of(out)["trust"].startswith("untrusted"), out)
        self.assertNotIn("trust_screen", rows_of(out))
        self.assertEqual(0, len(watch.calls))

    def test_the_trust_row_reads_the_real_config(self):
        fleet = self.loaded()
        slot = str(fleet.pool.slot_path("ws4"))
        config = fleet.tmp / "claude-config"
        config.mkdir()
        (config / ".claude.json").write_text(json.dumps({"projects": {slot: {"hasTrustDialogAccepted": True}}}))
        inject(fleet, Watch(lambda tmux, runtime: cli.LaunchWatch("ready")), config_dir=config)
        code, out, err = fleet.run(dispatch_argv(fleet, "trustedSlot"))
        self.assertEqual(0, code, out + err)
        self.assertTrue(rows_of(out)["trust"].startswith("trusted"), out)
        self.assertIn(slot, rows_of(out)["trust"])

        fleet = self.loaded()     # a fresh fleet: the dispatch above holds the WIP cap
        empty = fleet.tmp / "claude-config-empty"
        empty.mkdir()
        inject(fleet, Watch(lambda tmux, runtime: cli.LaunchWatch("ready")), config_dir=empty)
        code, out, err = fleet.run(dispatch_argv(fleet, "untrustedSlot", "--dry-run"))
        self.assertEqual(0, code, out + err)
        self.assertTrue(rows_of(out)["trust"].startswith("untrusted"), out)
        self.assertIn("the coordinator or operator answers it once on the pane", rows_of(out)["trust"])
        self.assertIn("folder-trust screen", rows_of(out)["trust"])


def admission_held(home) -> bool:
    """RV-25. A non-blocking attempt at the store's admission lock, through runtime_config's own API: flock is
    per open file, so a second open in this process is refused while main's `with admission_lock` holds it."""
    from fleet.errors import Refused
    from fleet.runtime_config import admission_lock
    try:
        with admission_lock(home, timeout_s=0):
            return False
    except Refused:
        return True


class TestTheWatchRunsOutsideTheAdmissionLock(CliCase):
    """RV-25. The post-launch watch (up to FLEET_TRUST_WATCH_SECONDS) ran inside main's box-wide admission lock,
    so a wave of slow launches could refuse a healthy dispatch at ADMISSION_WAIT_S."""

    def probe(self, fleet, answer):
        seen = []

        def watch(tmux, runtime):
            seen.append(admission_held(fleet.home))
            return answer
        return seen, watch

    def test_the_probe_sees_the_lock_when_it_is_held(self):
        from fleet.runtime_config import admission_lock
        fleet = self.loaded()
        fleet.home.mkdir(parents=True, exist_ok=True)
        with admission_lock(fleet.home):
            self.assertTrue(admission_held(fleet.home))
        self.assertFalse(admission_held(fleet.home))

    def test_the_dispatch_watch_runs_after_the_admission_lock_is_released(self):
        fleet = self.loaded()
        seen, watch = self.probe(fleet, cli.LaunchWatch("ready"))
        inject(fleet, watch)
        code, out, err = fleet.run(dispatch_argv(fleet, "outsideLock"))
        self.assertEqual(0, code, out + err)
        self.assertEqual([False], seen, "the watch ran while the admission lock was held")
        self.assertTrue(rows_of(out)["trust_screen"].startswith("none"), out)

    def test_the_revive_watch_runs_after_the_admission_lock_is_released(self):
        fleet = self.loaded()
        argv = fleet.revival_fixture()
        seen, watch = self.probe(fleet, cli.LaunchWatch("ready"))
        inject(fleet, watch)
        code, out, err = fleet.run(["revive", "--porcelain", *argv])
        self.assertEqual(0, code, out + err)
        self.assertEqual([False], seen, "the revive watch ran while the admission lock was held")

    def test_a_handler_run_without_main_still_watches_and_emits_inline(self):
        ctx = type("C", (), {"after_admission": None})()
        self.assertEqual(7, cli._after_admission(ctx, lambda: 7))
        ctx.after_admission = []
        self.assertEqual(cli.EXIT_OK, cli._after_admission(ctx, lambda: 7))
        self.assertEqual(7, ctx.after_admission[0]())


class TestTheSandboxVariableIsTheLaunchers(unittest.TestCase):
    """RV-27. The pane's environment is the tmux server's plus what the launcher exports, so a
    CLAUDE_CODE_SANDBOXED that only fleet's own process carries says nothing about the pane."""

    REASON = "CLAUDE_CODE_SANDBOXED is set in fleet's environment; the pane's is the tmux server's"

    def setUp(self):
        import shutil
        import tempfile
        self.cfg = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cfg, True)
        self.settings = LaunchSettings("claude", "/test/bin/claude", str(self.cfg))
        self.ctx = type("C", (), {"launch_environment": None})()

    def predict(self, os_env, overlay):
        with mock.patch.dict(os.environ, os_env, clear=False):
            if "CLAUDE_CODE_SANDBOXED" not in os_env:
                os.environ.pop("CLAUDE_CODE_SANDBOXED", None)
            return cli._predict_trust(self.ctx, self.settings, str(self.cfg), environ=overlay)

    def test_set_only_in_fleets_environment_is_unknown(self):
        got = self.predict({"CLAUDE_CODE_SANDBOXED": "1"}, {"FLEET_HOME": "/h"})
        self.assertEqual((cli.trust.UNKNOWN, "", self.REASON), (got.state, got.key, got.detail))

    def test_inherited_into_the_overlay_but_not_exported_by_the_launcher_is_unknown(self):
        """The production shape: `launch_environment` is a copy of os.environ, and the launcher exports only
        its allowlist, which does not carry the variable."""
        got = self.predict({"CLAUDE_CODE_SANDBOXED": "1"}, {"CLAUDE_CODE_SANDBOXED": "1", "FLEET_HOME": "/h"})
        self.assertEqual((cli.trust.UNKNOWN, self.REASON), (got.state, got.detail))

    def test_exported_by_the_launcher_is_trusted(self):
        from fleet import runtime_launch
        with mock.patch.object(runtime_launch, "EXPORTED_FROM_ENVIRON",
                               (*runtime_launch.EXPORTED_FROM_ENVIRON, "CLAUDE_CODE_SANDBOXED")):
            got = self.predict({}, {"CLAUDE_CODE_SANDBOXED": "1"})
        self.assertEqual(cli.trust.TRUSTED, got.state, got)

    def test_unset_everywhere_reads_the_config_as_before(self):
        got = self.predict({}, {"FLEET_HOME": "/h"})
        self.assertEqual(cli.trust.UNTRUSTED, got.state, got)

    def test_codex_is_still_not_predicted(self):
        settings = LaunchSettings("codex", "/test/bin/codex", str(self.cfg))
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SANDBOXED": "1"}):
            got = cli._predict_trust(self.ctx, settings, str(self.cfg), environ={})
        self.assertEqual(cli.trust.NOT_PREDICTED, got.state)

    def test_the_launcher_exports_exactly_its_allowlist_from_the_environment(self):
        """The constant the rule reads is the one `prepare` uses."""
        from fleet import runtime_launch
        import inspect
        self.assertIn("EXPORTED_FROM_ENVIRON", inspect.getsource(runtime_launch.prepare))
        self.assertNotIn("CLAUDE_CODE_SANDBOXED", runtime_launch.EXPORTED_FROM_ENVIRON)


class TestReviveReportsTheTrustScreen(CliCase):

    def test_a_revive_at_the_trust_screen_says_observed(self):
        fleet = self.loaded()
        argv = fleet.revival_fixture()
        slot = str(fleet.pool.slot_path("ws7"))
        watch = Watch(lambda tmux, runtime: cli.LaunchWatch("trust-screen", path=slot))
        inject(fleet, watch)
        code, out, err = fleet.run(["revive", "--porcelain", *argv])
        self.assertEqual(0, code, out + err)
        rows = rows_of(out)
        self.assertIn("trust", rows)
        self.assertTrue(rows["trust_screen"].startswith("observed"), rows)
        self.assertEqual("yes", rows["trust_screen_is_slot"])
        self.assertEqual(1, len(watch.calls))

    def test_an_interrupted_revive_watch_still_prints_the_revive_and_reraises(self):
        fleet = self.loaded()
        argv = fleet.revival_fixture()
        inject(fleet, Watch(interrupting))
        out, err = run_interrupted(self, fleet, ["revive", "--porcelain", *argv])
        rows = rows_of(out)
        self.assertIn("todo_id", rows, out + err)
        self.assertTrue(rows["trust_screen"].startswith("unobserved — the watch was interrupted"), rows)

    def test_the_revive_dry_run_prints_a_trust_row_and_never_watches(self):
        fleet = self.loaded()
        argv = fleet.revival_fixture()
        watch = Watch(lambda tmux, runtime: cli.LaunchWatch("ready"))
        inject(fleet, watch)
        code, out, err = fleet.run(["revive", "--porcelain", "--dry-run", *argv])
        self.assertEqual(0, code, out + err)
        self.assertIn("trust", rows_of(out))
        self.assertNotIn("trust_screen", rows_of(out))
        self.assertEqual(0, len(watch.calls))


class FakeLayer:
    def __init__(self, frames):
        self.frames, self.captured = list(frames), []

    def capture(self, name):
        self.captured.append(name)
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]


class FakeCtx:
    def __init__(self):
        self.launch_watch, self.slept = None, []
        self.sleep = self.slept.append


class TestTheWatchLoop(unittest.TestCase):

    def test_the_real_trust_frame_is_recognised_after_one_step(self):
        ctx = FakeCtx()
        with mock.patch("time.sleep", side_effect=AssertionError("a real sleep")):
            watch = cli._watch_launch(ctx, FakeLayer(["", TRUST_FRAME]), "dt-x", "claude")
        self.assertEqual("trust-screen", watch.outcome)
        self.assertEqual(TRUST_FRAME_PATH, watch.path)
        self.assertEqual([0.25], ctx.slept)

    def test_a_frame_that_never_decides_is_unobserved_at_the_window(self):
        ctx = FakeCtx()
        with mock.patch.dict(os.environ, {cli.TRUST_WATCH_SECONDS: "1"}), \
                mock.patch("time.sleep", side_effect=AssertionError("a real sleep")):
            watch = cli._watch_launch(ctx, FakeLayer(["Starting up..."]), "dt-x", "claude")
        self.assertEqual("unobserved", watch.outcome)
        self.assertEqual([0.25] * 4, ctx.slept)
        self.assertEqual(1.0, sum(ctx.slept))

    def test_a_capture_that_raises_is_unobserved_with_the_reason(self):
        class Broken:
            def capture(self, name):
                raise OSError("tmux went away")

        watch = cli._watch_launch(FakeCtx(), Broken(), "dt-x", "claude")
        self.assertEqual("unobserved", watch.outcome)
        self.assertIn("tmux went away", watch.detail)

    def test_the_idle_tui_is_ready_and_an_injected_watch_wins(self):
        idle = (FIXTURES / "claude-tui-2.1.282.frame").read_text()
        self.assertEqual("ready", cli._watch_launch(FakeCtx(), FakeLayer([idle]), "dt-x", "claude").outcome)
        ctx = FakeCtx()
        ctx.launch_watch = lambda tmux, runtime: cli.LaunchWatch("dialog")
        self.assertEqual("dialog", cli._watch_launch(ctx, FakeLayer([idle]), "dt-x", "claude").outcome)

    @staticmethod
    def _history(name):
        rows = (FIXTURES / name).read_text().splitlines()
        while rows and not cli.trust._ANSI.sub("", rows[-1]).strip():
            rows.pop()
        return rows

    def test_RV24_quoted_trust_screen_above_an_idle_tui_is_ready(self):
        """RV-24. A revived pane redraws history quoting the screen; the live prompt below it is `ready`."""
        for runtime, quoted, idle in (("claude", "claude-trust-2.1.282.frame", "claude-tui-2.1.282.frame"),
                                      ("codex", "codex-trust-0156.frame", "codex-idle.frame"),
                                      ("codex", "codex-trust.frame", "codex-idle.frame")):
            with self.subTest(quoted):
                frame = "\n".join([*self._history(quoted), "", (FIXTURES / idle).read_text()])
                self.assertEqual("ready", cli._watch_launch(FakeCtx(), FakeLayer([frame]), "dt-x", runtime).outcome)

    def test_RV24_the_watch_asks_observe_before_believing_the_recognizer(self):
        """RV-24. Even a recognizer that answers a path is not believed unless `observe` says dialog."""
        idle = (FIXTURES / "claude-tui-2.1.282.frame").read_text()
        with mock.patch.object(cli.trust, "trust_screen_path", return_value="/home/ubuntu/davis_root/ws10"):
            self.assertEqual("ready", cli._watch_launch(FakeCtx(), FakeLayer([idle]), "dt-x", "claude").outcome)

    def test_RV24_the_real_trust_frames_are_still_trust_screens(self):
        for runtime, name, path in (("claude", "claude-trust-2.1.282.frame", TRUST_FRAME_PATH),
                                    ("codex", "codex-trust-0156.frame", "/home/ubuntu/.fb110-trust.N3eo/untrusted"),
                                    ("codex", "codex-trust.frame",
                                     "/tmp/fleet-runtime-probe-8x14rwii/coordinator-probe/slot2")):
            with self.subTest(name):
                watch = cli._watch_launch(FakeCtx(), FakeLayer([(FIXTURES / name).read_text()]), "dt-x", runtime)
                self.assertEqual(("trust-screen", path), (watch.outcome, watch.path))

    def test_a_tilde_screen_path_is_expanded_before_the_slot_comparison(self):
        """Final review I3: 2.1.282 draws the absolute path even under HOME (claude-trust-under-home-2.1.282.frame);
        a `~` path is expanded anyway, as a defence."""
        import shutil
        import tempfile
        home = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        (home / "slot").mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            rows = dict(cli._watch_rows(cli.LaunchWatch("trust-screen", path="~/slot"), "dt-x", str(home / "slot"),
                                        "claude"))
        self.assertEqual("yes", rows["trust_screen_is_slot"])

    def test_the_window_reads_like_the_seed_window(self):
        self.assertEqual(cli.TRUST_WATCH_DEFAULT_S, cli._trust_watch_window({}))
        self.assertEqual(0.0, cli._trust_watch_window({cli.TRUST_WATCH_SECONDS: "0"}))
        self.assertEqual(cli.TRUST_WATCH_DEFAULT_S, cli._trust_watch_window({cli.TRUST_WATCH_SECONDS: "-1"}))
        self.assertEqual(cli.TRUST_WATCH_DEFAULT_S, cli._trust_watch_window({cli.TRUST_WATCH_SECONDS: "x"}))

    def test_an_infinite_or_nan_window_falls_back_to_the_default(self):
        """Fix round 1 (F2): `float("inf")` parses, and an unbounded watch would hang a dispatch."""
        for raw in ("inf", "-inf", "nan", "Infinity", "1e999"):
            self.assertEqual(cli.TRUST_WATCH_DEFAULT_S, cli._trust_watch_window({cli.TRUST_WATCH_SECONDS: raw}), raw)


if __name__ == "__main__":
    unittest.main()
