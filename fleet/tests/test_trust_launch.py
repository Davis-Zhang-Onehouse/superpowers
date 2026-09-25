"""V23-P (FB-126): `dispatch` and `revive` predict, watch and report a launch that stops at Claude Code's
folder-trust screen.

At base both verbs verified the launch by the worker's ARGV, which is right the moment the process execs — while
the pane itself sits at the trust screen waiting for a human. The output was plain success. These cases drive the
hermetic `Fleet` fixture (no tmux, no claude, no real sleep) with an injected `ctx.launch_watch`, and drive
`_watch_launch` itself over the real 2.1.282 trust frame.
"""
import json
import os
import pathlib
import unittest
from unittest import mock

from fleet import cli
from fleet.runtime import LaunchSettings
from tests.test_cli import FRESH_BASE_DIGITS, CliCase

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
        self.assertIn("folder-trust screen", rows_of(out)["trust"])


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

    def test_the_window_reads_like_the_seed_window(self):
        self.assertEqual(cli.TRUST_WATCH_DEFAULT_S, cli._trust_watch_window({}))
        self.assertEqual(0.0, cli._trust_watch_window({cli.TRUST_WATCH_SECONDS: "0"}))
        self.assertEqual(cli.TRUST_WATCH_DEFAULT_S, cli._trust_watch_window({cli.TRUST_WATCH_SECONDS: "-1"}))
        self.assertEqual(cli.TRUST_WATCH_DEFAULT_S, cli._trust_watch_window({cli.TRUST_WATCH_SECONDS: "x"}))


if __name__ == "__main__":
    unittest.main()
