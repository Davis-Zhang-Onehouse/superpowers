"""The properties the injected-probe suite cannot see, asserted at the VERB level.

`NFR2-3` makes every probe injectable so a suite can describe a fleet without owning one. That is why 612
hermetic tests were green while §E's nine real-concurrency cases failed eight — a suite with no processes
has no races. These cases keep the injected probes (nothing here starts a tmux, a `claude` or a repository)
and instead reconstruct, by hand, the *intermediate states* concurrency produces: a slot claimed whose record
is not written yet, and a lease freed underneath a second freer.

They exist because of one specific gap. `FI-21`'s fix is an ORDERING inside `_do_dispatch` — gate, claim,
**gate again holding the claim** — and an ordering is exactly the kind of thing a refactor drops silently.
`tests/test_guards.py` pins the rule; this pins the wiring, which is the half a guard test cannot reach.
"""
import io
import json
import pathlib
import shutil
import tempfile
import unittest

from fleet import EXIT_OK, EXIT_REFUSED
from fleet import cli
from fleet.harvest import Harvest
from fleet.pool import Pool
from fleet.session import Probes, SessionLayer
from fleet.store import Store

NOW = "2026-07-30T12:00:00Z"
#: `--base` is the 8-digit base id the instant-name grammar declares, not a folder name.
BASE = "00000000"
OTHER_BASE = "00000009"


class Fixture:
    """A fleet through injected probes only, plus the verb surface pointed at it."""

    def __init__(self, slots: int = 5):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-conc-"))
        self.home = self.tmp / "fleethome"
        self.instants = self.tmp / "instants"
        self.slots_dir = self.tmp / "slots"
        for path in (self.instants, self.slots_dir):
            path.mkdir(parents=True)
        self.started, self.killed, self.live = [], [], set()
        probes = Probes(list_processes=lambda: [],
                        capture_pane=lambda name: "",
                        has_session=lambda name: name in self.live,
                        start_session=lambda name, cwd, cmd: self.started.append(name),
                        kill_session=self.killed.append)
        self.sessions = SessionLayer(probes)
        self.store = Store(self.home)
        self.pool = Pool(self.home, cwd_probe=lambda path: [], alive=self.sessions.alive)
        self.harvest = Harvest(self.home, now=lambda: NOW)
        for index in range(slots):
            slot = self.slots_dir / f"ws{index + 1}"
            slot.mkdir()
            self.pool.enroll(slot)
        self.profile_dir = self.tmp / "profiles" / "worker"
        self.profile_dir.mkdir(parents=True)
        (self.profile_dir / "profile.json").write_text(json.dumps({"kind": "worker"}))
        (self.profile_dir / "charter.md").write_text(
            "# {{TITLE}}\n\nRun `fleet declare --instant \"$INSTANT\" --phase awaiting-ci`.\n")
        (self.profile_dir / "seed.txt").write_text("Read CHARTER.md.\n")

    def context(self):
        def build(parsed, out, err):
            return cli.Ctx(home=self.home, instants_dir=self.instants, store=self.store,
                           pool=self.pool, sessions=self.sessions, harvest=self.harvest,
                           out=out, err=err, dry_run=parsed.on("dry-run"),
                           porcelain=parsed.on("porcelain"), now=lambda: NOW,
                           git=lambda args, cwd=None: (0, ""), runner=None, live_work=True)

        return build

    def run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(list(argv), stdout=out, stderr=err, context=self.context())
        return code, out.getvalue(), err.getvalue()

    def dispatch(self, title, *, cap, base=BASE, slot=None):
        argv = ["dispatch", "--profile", str(self.profile_dir), "--title", title,
                "--base", base, "--cap", str(cap)]
        if slot:
            argv += ["--slot", slot]
        return self.run(argv)

    def claim_in_flight(self, slot, *, base=BASE, todo="inFlight"):
        """A dispatcher that has WON a slot and has not written its record yet.

        This is not a contrivance: it is the state every dispatch passes through, and the one a
        records-derived cap cannot see. Five dispatchers sitting here simultaneously all read "0 in active
        dev" and all passed the gate — 20 of 20 iterations (`FI-21`).
        """
        child = self.instants / f"00000000-07309999-inflight-append-{todo}"
        return self.pool.claim(todo_id=f"{todo}-07309999", tmux=f"dt-{todo}", base_instant=base,
                               child_instant=str(child), slot=slot)

    def held(self):
        return [slot for slot in self.pool.slots() if self.pool.lease(slot) is not None]


class _RacingPool:
    """A pool with a SECOND reaper inside it.

    It delegates everything, and the first time `reap` is called it first gives `frees` back — which is
    precisely the interleaving two concurrent reapers produce and the only one in which the defect is
    visible: the verb has already read the leases, so a report derived by diffing still names a slot this
    call did not free.
    """

    def __init__(self, inner, frees: str):
        self._inner = inner
        self._frees = frees
        self.raced = False

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def reap(self, *args, **kwargs):
        if not self.raced:
            self.raced = True
            self._inner.release(self._frees, force=True)      # the other reaper wins this one
        return self._inner.reap(*args, **kwargs)


class TestDispatchVerifiesTheCapWhileHoldingTheClaim(unittest.TestCase):
    def fixture(self, **kw) -> Fixture:
        made = Fixture(**kw)
        self.addCleanup(shutil.rmtree, made.tmp, ignore_errors=True)
        return made

    def test_a_dispatch_is_refused_by_a_claim_no_record_covers_yet(self):
        fleet = self.fixture()
        ahead = fleet.claim_in_flight("ws1")
        self.assertEqual(list(fleet.store.all()), [],
                         "the fixture must have NO record: a cap that can be settled by a read is not "
                         "the case under test")

        code, out, err = fleet.dispatch("second at cap one", cap=1)
        self.assertEqual(code, EXIT_REFUSED,
                         f"a second dispatch was admitted at cap 1 while {ahead.slot} was claimed — the "
                         f"gate is being settled by a read again (FI-21).\nout={out}\nerr={err}")
        self.assertIn("WIP cap", out + err, "the refusal does not name the cap")

    def test_the_refused_dispatch_gives_its_own_claim_straight_back(self):
        # The claim is taken BEFORE the rule is re-asked, so a refusal that kept it would leak a slot on
        # every refused dispatch — a silent slot leak, which is the failure the cap exists to prevent.
        fleet = self.fixture()
        fleet.claim_in_flight("ws1")
        before = fleet.held()
        code, _, _ = fleet.dispatch("refused", cap=1)
        self.assertEqual(code, EXIT_REFUSED)
        self.assertEqual(fleet.held(), before, "a refused dispatch kept the slot it had claimed")
        self.assertEqual(fleet.started, [], "a refused dispatch started a session")
        self.assertEqual(list(fleet.store.all()), [], "a refused dispatch wrote a record")

    def test_a_dispatch_under_the_cap_still_succeeds_with_claims_in_flight(self):
        # The other direction, and the one a lazy fix breaks: if every claimant counted every other
        # claimant, nobody would ever be admitted. Room under the cap must still be room.
        fleet = self.fixture()
        fleet.claim_in_flight("ws1")
        code, out, err = fleet.dispatch("room for two", cap=2)
        self.assertEqual(code, EXIT_OK, f"a dispatch with room under the cap was refused\n{out}{err}")
        self.assertEqual(len(list(fleet.store.all())), 1)

    def test_another_efforts_in_flight_claim_does_not_refuse_this_one(self):
        fleet = self.fixture()
        fleet.claim_in_flight("ws1", base=OTHER_BASE, todo="foreign")
        code, out, err = fleet.dispatch("mine", cap=1)
        self.assertEqual(code, EXIT_OK,
                         f"another effort's claim refused this effort's dispatch\n{out}{err}")

    def test_dry_run_is_unchanged_by_the_second_gate(self):
        # `--dry-run`'s zero-delta contract is what the whole shape of this fix defers to: `evaluate` may
        # not reserve anything, which is why admission had to move onto the lease instead. A dry run must
        # therefore never reach the claim at all.
        fleet = self.fixture()
        fleet.claim_in_flight("ws1")
        before = fleet.held()
        code, out, err = fleet.run(["dispatch", "--profile", str(fleet.profile_dir), "--title", "probe",
                                    "--base", BASE, "--cap", "1", "--dry-run"])
        self.assertIn(code, (EXIT_OK, EXIT_REFUSED), f"{out}{err}")
        self.assertEqual(fleet.held(), before, "a dry run claimed a slot")
        self.assertIn("dry-run", out, "a dry run did not say it was one")


class TestReapReportsWhatItFreedAndWhatItCouldNot(unittest.TestCase):
    def fixture(self, **kw) -> Fixture:
        made = Fixture(**kw)
        self.addCleanup(shutil.rmtree, made.tmp, ignore_errors=True)
        return made

    def stale(self, fleet, *slots):
        for index, slot in enumerate(slots):
            fleet.pool.claim(todo_id=f"stale{index}", tmux=f"dt-stale{index}", base_instant=BASE,
                             child_instant=str(fleet.instants / f"c{index}"), slot=slot)

    def reaped(self, out):
        return [row.split("\t")[1] for row in out.splitlines()
                if row.split("\t")[:1] == [cli.REAPED]]

    def test_a_slot_another_reaper_already_freed_is_not_reported_again(self):
        """`FI-22`'s second half, which survives fixing the exception.

        Deriving the freed set by diffing the pool before and after answers "what ended up free", which
        under a concurrent reaper is every slot — so one free is announced twice. The report has to be what
        THIS call did.

        The interleaving is what makes this observable, and it has to be reconstructed exactly: the other
        reaper's release must land AFTER this verb has read the leases and BEFORE it has finished freeing.
        Releasing beforehand proves nothing — the slot is simply not in the population any more, and a
        diff-derived report passes. That version of this case was written first, and the mutation walked
        straight through it.
        """
        fleet = self.fixture(slots=3)
        self.stale(fleet, "ws1", "ws2")
        fleet.pool = _RacingPool(fleet.pool, frees="ws1")

        code, out, err = fleet.run(["reap", "--porcelain", "--base", BASE])
        self.assertEqual(code, EXIT_OK, f"{out}{err}")
        self.assertTrue(fleet.pool.raced, "the fixture never interleaved: this case asserts nothing")
        self.assertEqual(self.reaped(out), ["ws2"],
                         f"reap reported a slot the OTHER reaper freed: {self.reaped(out)}")

    def test_a_lease_that_cannot_be_freed_is_NAMED_rather_than_raised(self):
        fleet = self.fixture(slots=2)
        self.stale(fleet, "ws1")
        # A leftover subdirectory inside the claim: the lock cannot be removed. Before FI-22 the OSError
        # travelled out of `reap` as a traceback, and "absence is never success" — a reap that omits what
        # it failed to free reports a clean sweep it did not perform.
        (fleet.pool.leases / "ws1" / "leftover").mkdir()

        code, out, err = fleet.run(["reap", "--porcelain", "--base", BASE])
        self.assertNotIn("Traceback", out + err, "an exception escaped reap")
        self.assertEqual(code, EXIT_REFUSED, f"a reap that freed nothing it was asked to reported ok\n{out}")
        rows = [row.split("\t") for row in out.splitlines()]
        unfreed = [row[1] for row in rows if row[0] == cli.REAP_UNFREED]
        self.assertEqual(unfreed, ["ws1"], f"the slot it could not free is not named: {out}")
        self.assertEqual(self.reaped(out), [], "a slot it could not free was reported as freed")


if __name__ == "__main__":
    unittest.main()
