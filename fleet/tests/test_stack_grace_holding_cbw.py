"""S5 stack glue (fleet 0.6.14): v23-g's awaiting-ci GRACE and `holding` phase meet v23-j's COMPLETE-BUT-WORKING.

v23-j decides "is work still live on a `-complete-` folder" in two places: the board state (`_worker_subject`, and so
the WIP cap) and the close/harvest refusal (`_refuse_live_complete_watcher`). Both now ask ONE predicate,
`reconcile.complete_work_is_live`, under the coordinator's ruling D-108 (it supersedes D-90's "expired or not"):
- a claim inside its 5-minute grace counts as live, like an observed or attested watcher;
- `holding` counts only while the hold stands (`_hold_of`);
- a harvested or closed record with no live session is OVER, whatever its stale claim says (RV-C1);
- a claim made before the record's (re)launch is not live (v2-10).
Each case sits beside its control, on the fixtures j's and RV-C1's own cases use.
"""
import io
import json
import pathlib
import time
import types
import unittest

import tests  # noqa: F401 — installs the hermetic host boundary (v23-n, FB-118)
from tests import test_cli
from tests.test_cli import EXIT_OK, EXIT_REFUSED
from tests.test_guards import GuardCase, QUIET_PANE
from fleet import cli
from fleet.errors import Refused
from fleet.guards import WipCap
from fleet.store import ATTESTED_PREFIX, Declarations


def _stamp(seconds_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))


def _declare(path, **fields):
    """The declaration as `declare` leaves it on disk, written directly so each shape is exact."""
    target = pathlib.Path(path) / ".fleet" / "declare.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(target.read_text()) if target.exists() else {}
    data.update(fields)
    target.write_text(json.dumps(data))


#: Each shape: the fields of declare.json. `age` is how long ago the claim was made.
def grace(age=60):
    return {"phase": "awaiting-ci", "at": _stamp(age)}


def standing_hold(age=60):
    return {"phase": "holding", "at": _stamp(age), "hold_reason": "told to wait for the gate",
            "hold_until": _stamp(age - 3600)}


def expired_hold(age=2 * 3600):
    return {"phase": "holding", "at": _stamp(age), "hold_reason": "told to wait for the gate",
            "hold_until": _stamp(age - 3600)}


def unbounded_hold(age=60):
    return {"phase": "holding", "at": _stamp(age), "hold_reason": "no expiry recorded"}


def pidless_attested(age=3600):
    return {"phase": "awaiting-ci", "at": _stamp(age), "watchers": ATTESTED_PREFIX + "a monitor, no pid handle"}


class TestTheBoardOnACompleteFolder(GuardCase):
    def subject_for(self, fields, *, stamp=None, live=False, launched_at=None):
        fleet = self.fleet()
        fleet.worker("glue", state="complete", slot="ws1", pane=QUIET_PANE, live=live)
        _declare(fleet.paths["glue"], **fields)
        record = fleet.store.all()[0]
        if stamp:
            setattr(record, stamp, "2026-08-12T01:36:49Z")
        if launched_at:
            record.launched_at = launched_at
        fleet.store.write(record)
        return fleet, fleet.subjects()[0]

    def assertWorking(self, fleet, subject, words):
        self.assertEqual("COMPLETE-BUT-WORKING", subject.state, subject.note)
        self.assertIn(words, subject.note)
        self.assertFalse(WipCap().evaluate(fleet.ctx()).allowed, "live work on a complete folder left the cap")

    def assertOver(self, fleet, subject):
        self.assertEqual("COMPLETE", subject.state, subject.note)
        self.assertTrue(WipCap().evaluate(fleet.ctx()).allowed, f"finished work held the cap: {subject.note}")

    def test_a_claim_inside_its_grace_is_live_work(self):
        for live in (False, True):
            with self.subTest(live=live):
                self.assertWorking(*self.subject_for(grace(), live=live), "GRACE")

    def test_control_a_claim_past_its_grace_is_over(self):
        self.assertOver(*self.subject_for(grace(age=301)))

    def test_a_standing_hold_is_live_work(self):
        self.assertWorking(*self.subject_for(standing_hold()), "holding")

    def test_an_expired_or_unbounded_hold_is_over(self):
        """D-108: a hold counts only while it stands. D-90's "expired or not" made an expired hold on a complete folder
        with no session a phantom cap holder forever (review RV-S3)."""
        for name, fields in (("expired", expired_hold()), ("unbounded", unbounded_hold())):
            with self.subTest(hold=name):
                self.assertOver(*self.subject_for(fields))

    def test_control_a_done_phase_is_over(self):
        self.assertOver(*self.subject_for({"phase": "done", "at": _stamp(60)}))

    def test_nothing_resurrects_a_stamped_record_with_no_live_session(self):
        """RV-C1, extended by D-108 to every claim: a harvested or closed record with no live session is over."""
        shapes = {"grace": grace(), "standing hold": standing_hold(), "expired hold": expired_hold(),
                  "pidless attested": pidless_attested()}
        for stamp in ("harvested_at", "closed_at"):
            for name, fields in shapes.items():
                with self.subTest(stamp=stamp, shape=name):
                    self.assertOver(*self.subject_for(fields, stamp=stamp))

    def test_a_stamped_record_with_a_live_session_still_works(self):
        """Delta review RV-D2: the stamped rule is "stamped AND no live session". With the session live (quiet, not busy), a
        standing hold or an in-grace claim is still live work."""
        for stamp in ("harvested_at", "closed_at"):
            for name, fields, words in (("standing hold", standing_hold(), "holding"), ("grace", grace(), "GRACE")):
                with self.subTest(stamp=stamp, shape=name):
                    self.assertWorking(*self.subject_for(fields, stamp=stamp, live=True), words)

    def test_a_claim_made_before_the_relaunch_is_not_live(self):
        """Review RV-H5: `launched_at` reaches both CBW sites. A claim older than the record's (re)launch was an earlier
        session's: a pid-less attestation and a claim still inside its grace are both disregarded."""
        for name, fields in (("pidless attested", pidless_attested(age=120)), ("grace", grace(age=120))):
            with self.subTest(shape=name):
                self.assertOver(*self.subject_for(fields, launched_at=_stamp(30)))
            with self.subTest(shape=name, control="launched before the claim"):
                self.assertWorking(*self.subject_for(fields, launched_at=_stamp(3600)), "")


class TestCloseAndHarvestAskTheSamePredicate(test_cli.TestCompleteRefusesBrokenPointers):
    """close and harvest refuse exactly what the board reads as live work on a `-complete-` folder, and nothing else."""

    def completed(self):
        env = self.ready_to_complete()
        record = next(r for r in env.fleet.store.all() if pathlib.Path(r.child_instant) == env.instant)
        code, _, err = env.fleet.run(["complete", "--instant", str(env.instant)])
        self.assertEqual(EXIT_OK, code, err)
        return env, record, env.instant.with_name(env.instant.name.replace("-inflight-", "-complete-"))

    def test_grace_and_a_standing_hold_block_close_and_harvest(self):
        for name, fields in (("grace", grace()), ("standing hold", standing_hold())):
            for verb in ("close", "harvest"):
                with self.subTest(shape=name, verb=verb):
                    env, record, child = self.completed()
                    _declare(child, **fields)
                    code, out, err = env.fleet.run([verb, "--id", record.todo_id])
                    self.assertEqual(EXIT_REFUSED, code, out + err)
                    self.assertIn("COMPLETE-BUT-WORKING", out + err)
                    self.assertIn("fleet declare --phase done", out + err)
                    self.assertEqual([], env.fleet.killed)
                    Declarations(child).set_phase("done")
                    code, out, err = env.fleet.run([verb, "--id", record.todo_id])
                    self.assertNotEqual(EXIT_REFUSED, code, out + err)
                    self.assertIn(record.tmux, env.fleet.killed)

    def test_control_past_grace_and_an_expired_hold_allow_close_and_harvest(self):
        for name, fields in (("past grace", grace(age=301)), ("expired hold", expired_hold())):
            for verb in ("close", "harvest"):
                with self.subTest(shape=name, verb=verb):
                    env, record, child = self.completed()
                    _declare(child, **fields)
                    code, out, err = env.fleet.run([verb, "--id", record.todo_id])
                    self.assertNotEqual(EXIT_REFUSED, code, out + err)
                    self.assertIn(record.tmux, env.fleet.killed)

    @staticmethod
    def ctx_of(env):
        """The Ctx `cli.main` would build over this fixture (its `context` hook), for asking the refusal directly."""
        return env.fleet.context()(types.SimpleNamespace(on=lambda _flag: False), io.StringIO(), io.StringIO())

    def test_the_refusal_passes_a_stamped_record_with_no_live_session(self):
        """Review RV-S2/RV-H6: the board reads such a record COMPLETE, so the refusal must not call it COMPLETE-BUT-WORKING.
        Asked of the refusal itself, for every claim shape, with the record's session gone."""
        shapes = {"grace": grace(), "standing hold": standing_hold(), "pidless attested": pidless_attested()}
        for stamp in ("harvested_at", "closed_at"):
            for name, fields in shapes.items():
                with self.subTest(stamp=stamp, shape=name):
                    env, record, child = self.completed()
                    _declare(child, **fields)
                    env.fleet.tmux_live.discard(record.tmux)
                    setattr(record, stamp, "2026-08-12T01:36:49Z")
                    self.assertIsNone(cli._refuse_live_complete_watcher(self.ctx_of(env), record, child, "harvest"))
                    setattr(record, stamp, None)
                    with self.assertRaises(Refused, msg="control: the unstamped record is refused"):
                        cli._refuse_live_complete_watcher(self.ctx_of(env), record, child, "harvest")


    def test_a_claim_made_before_the_relaunch_is_admitted(self):
        """Delta review RV-D1: the refusal passes `launched_at`. A claim older than the record's (re)launch is not live."""
        for name, fields in (("pidless attested", pidless_attested(age=120)), ("grace", grace(age=120))):
            with self.subTest(shape=name):
                env, record, child = self.completed()
                _declare(child, **fields)
                record.launched_at = _stamp(30)
                self.assertIsNone(cli._refuse_live_complete_watcher(self.ctx_of(env), record, child, "close"))
                record.launched_at = _stamp(3600)
                with self.assertRaises(Refused, msg="control: launched before the claim"):
                    cli._refuse_live_complete_watcher(self.ctx_of(env), record, child, "close")

    def test_a_stamped_record_with_a_live_session_is_refused(self):
        """Delta review RV-D2: a stamp does not end work whose session is still live."""
        for stamp in ("harvested_at", "closed_at"):
            with self.subTest(stamp=stamp):
                env, record, child = self.completed()
                _declare(child, **standing_hold())
                env.fleet.tmux_live.add(record.tmux)           # the record's session is live, and its pane quiet
                env.fleet.panes[record.tmux] = QUIET_PANE
                setattr(record, stamp, "2026-08-12T01:36:49Z")
                with self.assertRaises(Refused):
                    cli._refuse_live_complete_watcher(self.ctx_of(env), record, child, "harvest")

    def test_completes_awaiting_ci_message_classifies_like_the_board(self):
        """Delta review RV-D3: `complete` refuses a standing awaiting-ci claim either way; its message says "with a live
        watcher" for a claim inside its grace, and not for a pid-less attestation made before the relaunch."""
        for name, fields, launched, live in (("grace", grace(), _stamp(3600), True),
                                             ("pre-relaunch pidless", pidless_attested(age=120), _stamp(30), False)):
            with self.subTest(shape=name):
                env = self.ready_to_complete()
                record = next(r for r in env.fleet.store.all() if pathlib.Path(r.child_instant) == env.instant)
                record.launched_at = launched
                env.fleet.store.write(record)
                _declare(env.instant, **fields)
                code, out, err = env.fleet.run(["complete", "--instant", str(env.instant)])
                self.assertEqual(EXIT_REFUSED, code, out + err)
                self.assertEqual(live, "with a live watcher" in err, err)


# The inherited cases of TestCompleteRefusesBrokenPointers run in test_cli; this module runs only its own.
for _name in [n for n in dir(test_cli.TestCompleteRefusesBrokenPointers) if n.startswith("test_")]:
    if _name not in TestCloseAndHarvestAskTheSamePredicate.__dict__:
        setattr(TestCloseAndHarvestAskTheSamePredicate, _name, None)


if __name__ == "__main__":
    unittest.main()
