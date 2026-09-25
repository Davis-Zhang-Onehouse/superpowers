"""FB-130 (v23-q). `close`, `abort` and `harvest --id` end a pane, and they read an UNATTRIBUTED pane — one whose agent
process the census missed, about one poll in a hundred — without `runtime.observe`. A claude pane whose input box
could not be located was then closed without `--force`, while `pane-guard` answered `14 indeterminate` for the same
capture. Every teardown now asks `_box_unproven`, the predicate `pane-guard` asks, whether or not an agent is
attributed; the three shapes that stay closeable are named and pinned here (DECISIONS D-3).

Frames are the real Claude Code 2.1.268 / 2.1.282 captures in `it/fixtures/runtime/` (v23-f), with the input box made
unlocatable the way a mid-redraw or clipped capture draws it. Every refusal case here was RED at ab2225b3."""

import pathlib
import unittest

from fleet import EXIT_OK, EXIT_REFUSED
from fleet import cli
from fleet.runtime import plain
from tests.test_cli import CliCase

FRAMES = pathlib.Path(__file__).resolve().parents[1] / "it" / "fixtures" / "runtime"
CARET = "❯"
BORDER = "─" * 40


def _frame(name: str) -> str:
    return (FRAMES / name).read_text()


def _caret_row_replaced(name: str, row: str) -> str:
    """A real frame whose CURRENT caret row is redrawn as `row`: the box is there, its caret is not."""
    lines = _frame(name).splitlines()
    caret = max(i for i, line in enumerate(lines) if plain(line).startswith(CARET))
    lines[caret] = row
    return "\n".join(lines) + "\n"


def _footer_clipped(name: str) -> str:
    """A real idle frame with its status line cut off: a caret, but no chrome under it to say it is the box."""
    lines = [line for line in _frame(name).splitlines() if line.strip()]
    return "\n".join(lines[:-1]) + "\n"


#: The unlocatable-box shapes, each a real 2.1.x capture. `pane-guard` reads every one 14 attributed or not.
UNLOCATABLE = {
    "idle-2.1.268-caret-redrawn": _caret_row_replaced("claude-idle.frame", "· editor redraw in progress"),
    "idle-2.1.268-footer-clipped": _footer_clipped("claude-idle.frame"),
    "transcript-over-unrecognised-box": "\n".join([CARET + " earlier prompt", "", "● Done.", "", BORDER,
                                                    "· unrecognised box row", BORDER, "  ? for shortcuts"]),
}

#: What already refused an unattributed pane at base, and must keep doing so (controls).
REFUSED_ALREADY = {
    "queued-2.1.268": (_frame("claude-queued.frame"), "unsubmitted text"),
    "multiline-2.1.268": (_frame("claude-multiline.frame"), "unsubmitted text"),
    "busy-2.1.268": (_frame("claude-busy.frame"), "mid-turn"),
    "queued-behind-turn-2.1.282": (_frame("claude-queued-behind-turn-282.frame"), "mid-turn"),
    "dialog-2.1.268": (_frame("claude-dialog.frame"), "operator dialog"),
}


class _Teardown(CliCase):
    def _worker(self, fleet, name, pane, *, attributed, state="inflight"):
        path = fleet.worker(name, slot="ws1", pane=pane, state=state)
        if not attributed:
            #: The attribution miss: the session answers and the capture is the agent's, but the process census
            #: attributes no agent to it (`is_agent_process` False) — the one poll in a hundred.
            fleet.procs[:] = [proc for proc in fleet.procs if proc.name != f"dt-{name}"]
        if state == "complete":
            fleet.reviewed(path)
        return path

    def _close(self, fleet, name):
        return fleet.run(["close", "--id", fleet.ids[name]])

    def _abort(self, fleet, name):
        return fleet.run(["abort", "--instant", str(fleet.paths[name]), "--reason", "superseded"])

    def _harvest(self, fleet, name):
        return fleet.run(["harvest", "--id", fleet.ids[name]])

    def _pane_guard(self, fleet, name):
        return fleet.run(["pane-guard", "--porcelain", "--id", fleet.ids[name]])[0]


class UnattributedUnlocatableBoxIsRefused(_Teardown):
    """The defect. Each verb, each frame: refused 4 before any kill, naming the verb's own `--force`, and pane-guard
    says 14 about the same capture."""

    def _assert_refused(self, fleet, name, result, verb_override):
        code, out, err = result
        self.assertEqual(code, EXIT_REFUSED, f"torn down an unattributed pane whose box is unproven: {out}{err}")
        self.assertIn("input state cannot be established", out + err)
        self.assertIn(verb_override, out + err)
        self.assertEqual(fleet.killed, [], "the pane was killed on a refusing path")
        self.assertIsNotNone(fleet.pool.lease("ws1"), "the slot was released on a refusing path")

    def test_close_refuses(self):
        for label, frame in UNLOCATABLE.items():
            with self.subTest(frame=label):
                fleet = self.fleet()
                self._worker(fleet, "loose", frame, attributed=False)
                self.assertEqual(self._pane_guard(fleet, "loose"), cli.PANE_INDETERMINATE)
                self._assert_refused(fleet, "loose", self._close(fleet, "loose"), "--force")
                self.assertIsNone(fleet.store.read(fleet.ids["loose"]).closed_at)

    def test_abort_refuses(self):
        for label, frame in UNLOCATABLE.items():
            with self.subTest(frame=label):
                fleet = self.fleet()
                self._worker(fleet, "loose", frame, attributed=False)
                self._assert_refused(fleet, "loose", self._abort(fleet, "loose"), "fleet abort --instant")
                self.assertTrue(fleet.paths["loose"].exists(), "renamed on a refusing path")

    def test_harvest_id_refuses(self):
        for label, frame in UNLOCATABLE.items():
            with self.subTest(frame=label):
                fleet = self.fleet()
                self._worker(fleet, "loose", frame, attributed=False, state="complete")
                code, out, err = self._harvest(fleet, "loose")
                self.assertNotEqual(code, EXIT_OK, f"harvest closed an unproven pane: {out}{err}")
                self.assertIn("input state cannot be established", out + err)
                self.assertIn("fleet harvest --id", out + err)
                self.assertEqual(fleet.killed, [])
                self.assertIsNone(fleet.store.read(fleet.ids["loose"]).harvested_at)

    def test_force_still_overrides(self):
        fleet = self.fleet()
        self._worker(fleet, "forced", UNLOCATABLE["idle-2.1.268-caret-redrawn"], attributed=False)
        code, out, err = fleet.run(["close", "--id", fleet.ids["forced"], "--force"])
        self.assertEqual(code, EXIT_OK, f"{out}{err}")
        self.assertIn("dt-forced", fleet.killed)

    def test_attributed_twin_was_and_is_refused(self):
        """Control: the same frames with the agent attributed were refused at base too; attribution changes nothing."""
        for label, frame in UNLOCATABLE.items():
            with self.subTest(frame=label):
                fleet = self.fleet()
                self._worker(fleet, "owned", frame, attributed=True)
                self.assertEqual(self._close(fleet, "owned")[0], EXIT_REFUSED)


class ControlsStillHold(_Teardown):
    """What must not move: draft/turn/dialog refused unattributed (they were at base), an idle 2.1.268 box closes."""

    def test_unattributed_draft_turn_and_dialog_stay_refused(self):
        for label, (frame, clause) in REFUSED_ALREADY.items():
            with self.subTest(frame=label):
                fleet = self.fleet()
                self._worker(fleet, "held", frame, attributed=False)
                code, out, err = self._close(fleet, "held")
                self.assertEqual(code, EXIT_REFUSED, f"{out}{err}")
                self.assertIn(clause, out + err)

    def test_an_unattributed_idle_box_that_is_proven_empty_closes(self):
        fleet = self.fleet()
        self._worker(fleet, "quiet", _frame("claude-idle.frame"), attributed=False)
        self.assertEqual(self._pane_guard(fleet, "quiet"), cli.PANE_SAFE)
        code, out, err = self._close(fleet, "quiet")
        self.assertEqual(code, EXIT_OK, f"{out}{err}")
        self.assertIn("dt-quiet", fleet.killed)


class ReallyDeadPanesStayCloseable(_Teardown):
    """DECISIONS D-3: failing closed must not make a pane with no process at all un-closeable."""

    def test_no_session_closes(self):
        """Shape 1: no process and no session answer — what an exited fleet worker leaves (its launcher `exec`s)."""
        fleet = self.fleet()
        fleet.worker("gone", slot="ws1", live=False)
        code, out, err = self._close(fleet, "gone")
        self.assertEqual(code, EXIT_OK, f"{out}{err}")

    def test_a_dead_pane_whose_last_frame_is_unprovable_closes(self):
        """Shape 2: remain-on-exit. The session answers, every pane reports tmux `pane_dead`, and the screen still
        holds claude's last frame with a box nobody can locate. No process can submit anything, so nothing is lost."""
        for label, frame in UNLOCATABLE.items():
            with self.subTest(frame=label):
                fleet = self.fleet()
                self._worker(fleet, "dead", frame + "Pane is dead (status 0, Fri Sep 25 21:34:50 2026)\n",
                             attributed=False)
                fleet.sessions.probes.panes_dead = lambda name: True if name in fleet.tmux_live else None
                code, out, err = self._close(fleet, "dead")
                self.assertEqual(code, EXIT_OK, f"a dead pane was refused: {out}{err}")
                self.assertIn("dt-dead", fleet.killed)

    def test_the_dead_banner_alone_is_not_death(self):
        """The `Pane is dead` line is screen text any agent can print; only tmux's own `pane_dead` counts."""
        for dead in (False, None):
            with self.subTest(panes_dead=dead):
                fleet = self.fleet()
                self._worker(fleet, "liar", UNLOCATABLE["idle-2.1.268-caret-redrawn"] +
                             "Pane is dead (status 0, Fri Sep 25 21:34:50 2026)\n", attributed=False)
                fleet.sessions.probes.panes_dead = lambda name, dead=dead: dead
                self.assertEqual(self._close(fleet, "liar")[0], EXIT_REFUSED)

    def test_a_live_non_agent_pane_closes(self):
        """Shape 3: alive, nothing attributed, nothing claude on screen — pane-guard 12, closeable as before."""
        for label, frame in (("empty", ""), ("shell", "ubuntu@host:~$ sleep 900\n")):
            with self.subTest(frame=label):
                fleet = self.fleet()
                self._worker(fleet, "shell", frame, attributed=False)
                self.assertEqual(self._pane_guard(fleet, "shell"), cli.PANE_NOT_CLAUDE)
                code, out, err = self._close(fleet, "shell")
                self.assertEqual(code, EXIT_OK, f"{out}{err}")


class PaneGuardCodesUnchanged(_Teardown):
    """D-2 collapsed pane-guard's two 14 branches into one `_box_unproven` call. This pins the whole matrix measured
    at ab2225b3 (`evidence/01-remeasure/matrix-at-base-ab2225b3.txt`), so the collapse is shown behaviour-preserving."""

    EXPECTED = {
        ("claude-idle.frame", True): cli.PANE_SAFE, ("claude-idle.frame", False): cli.PANE_SAFE,
        ("claude-queued.frame", True): cli.PANE_QUEUED_TEXT, ("claude-queued.frame", False): cli.PANE_QUEUED_TEXT,
        ("claude-busy.frame", True): cli.PANE_MID_TURN, ("claude-busy.frame", False): cli.PANE_MID_TURN,
        ("claude-dialog.frame", True): cli.PANE_AWAITING_OPERATOR,
        ("claude-dialog.frame", False): cli.PANE_AWAITING_OPERATOR,
    }

    def test_matrix(self):
        for (name, attributed), code in self.EXPECTED.items():
            with self.subTest(frame=name, attributed=attributed):
                fleet = self.fleet()
                self._worker(fleet, "m", _frame(name), attributed=attributed)
                self.assertEqual(self._pane_guard(fleet, "m"), code)
        for label, frame in UNLOCATABLE.items():
            for attributed in (True, False):
                with self.subTest(frame=label, attributed=attributed):
                    fleet = self.fleet()
                    self._worker(fleet, "m", frame, attributed=attributed)
                    self.assertEqual(self._pane_guard(fleet, "m"), cli.PANE_INDETERMINATE)


if __name__ == "__main__":
    unittest.main()
