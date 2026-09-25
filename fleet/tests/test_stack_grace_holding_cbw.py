"""S5 stack glue (fleet 0.6.14): v23-g's awaiting-ci GRACE and `holding` phase meet v23-j's COMPLETE-BUT-WORKING.

v23-j decides "is work still live on a `-complete-` folder" in two places — the board state (`_worker_subject`) and
the close/harvest refusal (`_refuse_live_complete_watcher`) — both keyed on an OBSERVED or ATTESTED watcher. v23-g adds
a third live watcher kind (a claim inside its 5-minute grace) and a `holding` phase. The coordinator's ruling (D-90,
fail safe): a claim inside its grace, or any `holding` phase, counts as LIVE for j. And v23-m's terminal stamps
(RV-C1, 0.6.13) still win: a harvested or closed record with no live session is over, grace or holding notwithstanding.
Each case sits beside its control, on the real fixtures j's and RV-C1's own cases use.
"""
import json
import pathlib
import time
import unittest

import tests  # noqa: F401 — installs the hermetic host boundary (v23-n, FB-118)
from tests import test_cli
from tests.test_cli import EXIT_OK, EXIT_REFUSED
from tests.test_guards import GuardCase, QUIET_PANE
from fleet.guards import WipCap
from fleet.store import Declarations


def _age_the_claim(path, seconds):
    """Move the declaration's `at` into the past, as `_grace_of` measures it (the claim's own stamp, D-90)."""
    target = pathlib.Path(path) / ".fleet" / "declare.json"
    data = json.loads(target.read_text())
    data["at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds))
    target.write_text(json.dumps(data))


class TestGraceAndHoldingOnACompleteFolder(GuardCase):
    def subject_for(self, phase, *, age=0, stamp=None, live=False):
        fleet = self.fleet()
        fleet.worker("glue", state="complete", slot="ws1", pane=QUIET_PANE, phase=phase, live=live)
        if age:
            _age_the_claim(fleet.paths["glue"], age)
        if stamp:
            record = fleet.store.all()[0]
            setattr(record, stamp, "2026-08-12T01:36:49Z")
            fleet.store.write(record)
        return fleet, fleet.subjects()[0]

    def test_a_claim_inside_its_grace_keeps_a_complete_folder_working(self):
        for live in (False, True):
            with self.subTest(live=live):
                fleet, subject = self.subject_for("awaiting-ci", age=60, live=live)
                self.assertEqual("COMPLETE-BUT-WORKING", subject.state, subject.note)
                self.assertIn("GRACE", subject.note)
                self.assertFalse(WipCap().evaluate(fleet.ctx()).allowed)

    def test_control_a_claim_past_its_grace_is_complete(self):
        fleet, subject = self.subject_for("awaiting-ci", age=301)
        self.assertEqual("COMPLETE", subject.state, subject.note)
        self.assertTrue(WipCap().evaluate(fleet.ctx()).allowed)

    def test_a_holding_phase_keeps_a_complete_folder_working(self):
        for age in (0, 5 * 60 * 60):          # a standing hold, and one past HOLD_MAX_S: both count (D-90, fail safe)
            with self.subTest(age=age):
                fleet, subject = self.subject_for("holding", age=age)
                self.assertEqual("COMPLETE-BUT-WORKING", subject.state, subject.note)
                self.assertIn("holding", subject.note)
                self.assertFalse(WipCap().evaluate(fleet.ctx()).allowed)

    def test_control_a_done_phase_is_complete(self):
        fleet, subject = self.subject_for("done")
        self.assertEqual("COMPLETE", subject.state, subject.note)
        self.assertTrue(WipCap().evaluate(fleet.ctx()).allowed)

    def test_neither_grace_nor_holding_resurrects_a_stamped_record(self):
        """RV-C1's rule, extended: a harvested or closed record with no live session is over."""
        for phase in ("awaiting-ci", "holding"):
            for stamp in ("harvested_at", "closed_at"):
                with self.subTest(phase=phase, stamp=stamp):
                    fleet, subject = self.subject_for(phase, age=60, stamp=stamp)
                    self.assertEqual("COMPLETE", subject.state, subject.note)
                    self.assertTrue(WipCap().evaluate(fleet.ctx()).allowed,
                                    f"a {stamp} record's {phase} claim held the cap")


class TestCloseAndHarvestRefuseGraceAndHolding(test_cli.TestCompleteRefusesBrokenPointers):
    """The same composition at j's refusal: close and harvest must not tear down a `-complete-` worker whose claim is
    inside its grace or which is holding. `declare --phase done` clears it, as for j's live watcher."""

    def completed(self):
        env = self.ready_to_complete()
        record = next(r for r in env.fleet.store.all() if pathlib.Path(r.child_instant) == env.instant)
        code, _, err = env.fleet.run(["complete", "--instant", str(env.instant)])
        self.assertEqual(EXIT_OK, code, err)
        return env, record, env.instant.with_name(env.instant.name.replace("-inflight-", "-complete-"))

    def test_grace_and_holding_block_close_and_harvest(self):
        for phase in ("awaiting-ci", "holding"):
            for verb in ("close", "harvest"):
                with self.subTest(phase=phase, verb=verb):
                    env, record, child = self.completed()
                    declaration = Declarations(child)
                    declaration.set_phase(phase)
                    code, out, err = env.fleet.run([verb, "--id", record.todo_id])
                    self.assertEqual(EXIT_REFUSED, code, out + err)
                    self.assertIn("COMPLETE-BUT-WORKING", out + err)
                    self.assertIn("fleet declare --phase done", out + err)
                    self.assertEqual([], env.fleet.killed)
                    declaration.set_phase("done")
                    code, out, err = env.fleet.run([verb, "--id", record.todo_id])
                    self.assertNotEqual(EXIT_REFUSED, code, out + err)
                    self.assertIn(record.tmux, env.fleet.killed)

    def test_control_a_claim_past_its_grace_allows_close_and_harvest(self):
        for verb in ("close", "harvest"):
            with self.subTest(verb=verb):
                env, record, child = self.completed()
                Declarations(child).set_phase("awaiting-ci")
                _age_the_claim(child, 301)
                code, out, err = env.fleet.run([verb, "--id", record.todo_id])
                self.assertNotEqual(EXIT_REFUSED, code, out + err)
                self.assertIn(record.tmux, env.fleet.killed)


# The inherited cases of TestCompleteRefusesBrokenPointers run in test_cli; this module runs only its own.
for _name in [n for n in dir(test_cli.TestCompleteRefusesBrokenPointers) if n.startswith("test_")]:
    if _name not in TestCloseAndHarvestRefuseGraceAndHolding.__dict__:
        setattr(TestCloseAndHarvestRefuseGraceAndHolding, _name, None)


if __name__ == "__main__":
    unittest.main()
