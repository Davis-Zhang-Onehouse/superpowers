import pathlib, tempfile, unittest
from fleet.pool import Lease, Pool
from fleet.errors import BadInput, NoCapacity, Refused

class TestPool(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.holders: dict[str, list[int]] = {}
        self.live: set[str] = set()
        self.pool = Pool(self.home,
                         cwd_probe=lambda p: self.holders.get(str(p), []),
                         alive=lambda name: name in self.live)
        for n in ("ws1", "ws2"):
            d = self.tmp / n; d.mkdir(parents=True); self.pool.enroll(d)

    def claim(self, todo="t1", slot=None):
        return self.pool.claim(todo_id=todo, tmux=f"dt-{todo}", base_instant="/i/base",
                               child_instant="/i/child", slot=slot)

    def test_enrollment_is_opt_in(self):
        self.assertEqual(self.pool.slots(), ["ws1", "ws2"])
        self.assertNotIn("ws9", self.pool.slots())

    def test_claim_is_exclusive(self):
        first = self.claim("t1", slot="ws1")
        self.assertEqual(first.slot, "ws1")
        with self.assertRaises(NoCapacity):
            self.claim("t2", slot="ws1")

    def test_claim_without_a_slot_takes_a_free_one_then_runs_out(self):
        self.claim("t1"); self.claim("t2")
        with self.assertRaises(NoCapacity):
            self.claim("t3")

    def test_release_is_idempotent(self):
        self.claim("t1", slot="ws1")
        self.pool.release("ws1"); self.pool.release("ws1")
        self.assertIn("ws1", self.pool.free_slots())

    def test_release_refuses_while_a_live_process_holds_the_path_as_cwd(self):
        # OBS-48 measured TWO live processes holding ws3 simultaneously, because the slot had been
        # re-leased while an older worker still sat in it. Staleness is cwd-coupled, not "tmux gone" —
        # a session outliving its work never has a dead tmux.
        lease = self.claim("t1", slot="ws1")
        self.holders[str(lease.path)] = [4242]
        with self.assertRaises(Refused) as cm:
            self.pool.release("ws1")
        self.assertIn("4242", str(cm.exception))
        self.pool.release("ws1", force=True)
        self.assertIn("ws1", self.pool.free_slots())

    def test_reap_frees_a_dead_holder_and_keeps_a_live_one(self):
        self.claim("dead", slot="ws1"); self.claim("alive", slot="ws2")
        self.live.add("dt-alive")
        # `reap` answers with a REPORT now, not a bare list (`FI-22`): what this call freed, what it could
        # not free, and what it left to another owner are three different answers and a list can carry one.
        report = self.pool.reap(base_instant="/i/base")
        self.assertEqual(report.freed, ["ws1"])
        self.assertEqual(report.unfreed, [])
        self.assertEqual(list(report), ["ws1"], "iterating a report must still walk what it freed")
        self.assertIsNotNone(self.pool.lease("ws2"))

    def test_reap_refuses_a_foreign_lease_and_NAMES_THE_OWNER(self):
        # RI-31: the ownership guard refused correctly and it READ AS A BUG, because the refusal did not
        # say whose lease it was. "Not yours to clear" is a state, not a failure.
        self.pool.claim(todo_id="other", tmux="dt-other", base_instant="/i/OTHER",
                        child_instant="/i/c", slot="ws1")
        report = self.pool.reap(base_instant="/i/base")
        self.assertEqual(report.freed, [])
        self.assertEqual(report.skipped, [("ws1", "/i/OTHER")],
                         "a foreign stale lease is a STATE this report names, not an omission")
        with self.assertRaises(Refused) as cm:
            self.pool.reap(base_instant="/i/base", strict=True)
        self.assertIn("/i/OTHER", str(cm.exception))
        self.assertEqual(cm.exception.clears_who, "/i/OTHER")
        self.assertEqual(self.pool.reap(all_efforts=True).freed, ["ws1"])

    def test_unenroll_refuses_a_leased_slot_unless_forced(self):
        self.claim("t1", slot="ws1")
        with self.assertRaises(Refused):
            self.pool.unenroll("ws1")
        self.pool.unenroll("ws1", force=True)
        self.assertNotIn("ws1", self.pool.slots())

    def test_a_refusal_is_written_for_the_AUDIENCE_THAT_READS_IT_not_in_python_kwargs(self):
        # FI-19b: these refusals told a CLI caller to `pass force=True` and to `reap(all_efforts=True)` —
        # python, quoted at somebody typing a command. `cli` appends the real token (`--force`, `--all`),
        # but the kwarg phrasing rode along inside the transported message, so the message an operator
        # actually reads named two different languages. An override still has to be named, in words.
        self.claim("t1", slot="ws1")
        with self.assertRaises(Refused) as unenrolling:
            self.pool.unenroll("ws1")
        self.pool.claim(todo_id="other", tmux="dt-other", base_instant="/i/OTHER",
                        child_instant="/i/c", slot="ws2")
        with self.assertRaises(Refused) as reaping:
            self.pool.reap(base_instant="/i/base", strict=True)

        refusals = [unenrolling.exception, reaping.exception]
        for exc in refusals:
            for text in (str(exc), exc.clears_when or "", exc.clears_who or ""):
                self.assertNotRegex(text, r"\w+=(?:True|False)\b",
                                    f"a refusal quotes a python keyword argument at its reader: {text!r}")
                self.assertNotRegex(text, r"\w+\((?:\w+=|\))",
                                    f"a refusal quotes a python call at its reader: {text!r}")
            self.assertIn("override", str(exc).lower(),
                          f"the refusal names no way past itself at all: {str(exc)!r}")

    def test_enrolling_a_missing_path_is_bad_input(self):
        with self.assertRaises(BadInput):
            self.pool.enroll(self.tmp / "nope")


# --- concurrency ------------------------------------------------------------------------------------
# Module-level so the child processes can pickle them. The probes must be real functions, not lambdas.

def _no_holders(path):
    return []


def _never_alive(name):
    return False


def _race_claimant(args):
    """One claimant. Returns the slot it won, or None. Constructed inside the child because a Pool
    carrying closures is not picklable."""
    home, slot_dir, index, barrier = args
    import pathlib as _p
    from fleet.pool import Pool
    from fleet.errors import NoCapacity
    pool = Pool(_p.Path(home), cwd_probe=_no_holders, alive=_never_alive)
    barrier.wait()                      # every claimant races from the same instant
    try:
        return pool.claim(todo_id=f"t{index}", tmux=f"dt-t{index}",
                          base_instant="/i/base", child_instant="/i/child", slot="ws1").slot
    except NoCapacity:
        return None


class TestClaimIsAtomicUnderConcurrency(unittest.TestCase):
    """Kills mutation M-11 (check-then-mkdir instead of mkdir-as-the-lock).

    Atomicity is a property of CONCURRENT claimants, so no single-threaded case can observe it: a
    `if claim_dir.is_dir(): raise` followed by `mkdir(exist_ok=True)` satisfies every sequential
    exclusivity assertion exactly as the atomic version does. This gap was a defect in the PLAN — a
    mutation was specified whose failure no specified test could see, because the mutation list and the
    test list were written independently and never reconciled (filed as FI-13).

    The consequence of getting this wrong is not theoretical: it is OBS-48's measured hazard, two live
    processes holding one slot, one of them repositioned onto another effort's branch.
    """

    def test_exactly_one_of_many_racing_claimants_wins(self):
        import multiprocessing as mp
        tmp = pathlib.Path(tempfile.mkdtemp())
        home = tmp / "home"
        slot = tmp / "ws1"
        slot.mkdir(parents=True)
        Pool(home, cwd_probe=_no_holders, alive=_never_alive).enroll(slot)

        n = 6
        ctx = mp.get_context("fork")
        with ctx.Manager() as manager:
            barrier = manager.Barrier(n)
            with ctx.Pool(n) as procs:
                won = procs.map(_race_claimant, [(str(home), str(slot), i, barrier) for i in range(n)])

        winners = [w for w in won if w is not None]
        self.assertEqual(len(winners), 1,
                         f"{len(winners)} of {n} claimants won the same slot; mkdir is not the lock")
        self.assertEqual(winners[0], "ws1")


def _reaper(args):
    """One reaper process. Returns the slots IT freed and whether an exception escaped."""
    home, barrier = args
    import pathlib as _p
    from fleet.pool import Pool
    pool = Pool(_p.Path(home), cwd_probe=_no_holders, alive=_never_alive)
    barrier.wait()
    try:
        report = pool.reap(all_efforts=True, strict=True)
    except BaseException as exc:                       # noqa: BLE001 — the point is that none escapes
        return (None, f"{type(exc).__name__}: {exc}")
    return (report.freed, None)


class TestFreeingIsIdempotentUnderAConcurrentFreer(unittest.TestCase):
    """`FI-22`, and the two halves of it that a single-threaded case cannot separate.

    Measured at 10 of 10 iterations before the fix: two reapers enumerate the same stale set, the loser
    dies on `FileNotFoundError` out of `body.unlink()`, and the traceback reaches the operator instead of a
    row. *A lease already gone is the desired end state, not an error.*

    The second half is subtler and survives fixing the first: if each reaper derives "what I freed" by
    looking at what ended up free, both report every slot, so a slot freed once is announced twice.
    """

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.pool = Pool(self.home, cwd_probe=_no_holders, alive=_never_alive)
        self.slots = []
        for index in range(4):
            slot = self.tmp / f"ws{index + 1}"
            slot.mkdir()
            self.pool.enroll(slot)
            self.slots.append(slot.name)

    def stale_leases(self):
        for index, slot in enumerate(self.slots):
            self.pool.claim(todo_id=f"t{index}", tmux=f"dt-t{index}", base_instant="/i/base",
                            child_instant=f"/i/c{index}", slot=slot)

    def test_only_one_of_two_releasers_reports_having_freed_the_slot(self):
        self.stale_leases()
        did = [self.pool.release("ws1"), self.pool.release("ws1"), self.pool.release("ws1")]
        self.assertEqual(did, [True, False, False],
                         "the return value must say WHO freed it, or two reapers both claim the credit")
        self.assertIn("ws1", self.pool.free_slots())

    def test_releasing_a_slot_that_was_re_claimed_under_us_leaves_the_new_claim_alone(self):
        self.stale_leases()
        old = self.pool.lease("ws1").todo_id
        self.pool.release("ws1")
        fresh = self.pool.claim(todo_id="new", tmux="dt-new", base_instant="/i/base",
                                child_instant="/i/cnew", slot="ws1")
        self.assertFalse(self.pool.release("ws1", expect_todo=old),
                         "a stale releaser freed a lease that was not the one it read")
        self.assertEqual(self.pool.lease("ws1").todo_id, fresh.todo_id,
                         "a live worker lost its slot to a double free")

    def test_two_concurrent_reapers_free_every_slot_exactly_once_and_raise_nothing(self):
        import multiprocessing as mp
        self.stale_leases()
        ctx = mp.get_context("fork")
        with ctx.Manager() as manager:
            barrier = manager.Barrier(2)
            with ctx.Pool(2) as procs:
                got = procs.map(_reaper, [(str(self.home), barrier)] * 2)

        escaped = [why for _, why in got if why is not None]
        self.assertEqual(escaped, [], f"an exception escaped a concurrent reap: {escaped}")
        reported = [slot for freed, _ in got for slot in freed]
        self.assertEqual(sorted(reported), sorted(self.slots),
                         f"the two reapers between them did not report each slot once: {reported}")
        self.assertEqual(self.pool.free_slots(), self.slots, "a lease was left behind")


class TestClaimsAreOrdered(unittest.TestCase):
    """`FI-21`'s tiebreak. Admission has to be settled on the claim, and settling it needs ONE order that
    every racing claimant computes identically — otherwise each counts the others, all of them refuse, and
    a livelock replaces the over-admission."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, ignore_errors=True)
        self.pool = Pool(self.tmp / "home", cwd_probe=_no_holders, alive=_never_alive)
        for index in range(3):
            slot = self.tmp / f"ws{index + 1}"
            slot.mkdir()
            self.pool.enroll(slot)

    def test_claims_come_back_in_the_order_they_were_won(self):
        won = [self.pool.claim(todo_id=f"t{i}", tmux=f"dt-t{i}", base_instant="/i/base",
                               child_instant=f"/i/c{i}", slot=slot).todo_id
               for i, slot in enumerate(("ws3", "ws1", "ws2"))]
        self.assertEqual([lease.todo_id for lease in self.pool.claims()], won,
                         "claims are not ordered by when they were won, so two racers see two orders")

    def test_the_order_survives_a_round_trip_through_the_lease_body(self):
        lease = self.pool.claim(todo_id="t", tmux="dt-t", base_instant="/i/base",
                                child_instant="/i/c", slot="ws1")
        self.assertGreater(lease.claimed_ns, 0)
        self.assertEqual(self.pool.lease("ws1").rank, lease.rank,
                         "the rank is not persisted, so a second process cannot compute the same order")

    def test_a_claim_whose_body_has_not_landed_yet_is_waited_for(self):
        (self.pool.leases / "ws1").mkdir(parents=True)     # mkdir won; the body is still being written
        self.assertEqual(self.pool.claims(settle_s=0.05), [],
                         "a claim that never gets a body must not wedge the pool forever")
        self.pool.claim(todo_id="t", tmux="dt-t", base_instant="/i/base", child_instant="/i/c",
                        slot="ws2")
        self.assertEqual([lease.slot for lease in self.pool.claims(settle_s=0.05)], ["ws2"])


class TestAnInterruptedClaimIsReclaimableAndReported(unittest.TestCase):
    """`SI-7` — the defect this class exists for was **permanent**, not merely a leak.

    `mkdir` is the lock and `lease.json` is written INSIDE the directory it won, so a crash between that
    body's `write()` and its `rename()` leaves a claim directory holding only the staging file. From there,
    measured on the shipped build:

        leases / lease() / claims() / reap --all   ->  the slot is FREE   (they read the BODY)
        free_slots()                              ->  excludes it        (it tests the DIR)
        claim(slot=...)                            ->  NoCapacity, forever

    Two disagreeing notions of "free" in one pool, no verb able to reconcile them, and `reap` — named as
    the remedy in the very refusal the operator reads — returning exit 0 with `0 could not be freed`. Even
    the counter whose job is "I saw something I could not fix" stayed at zero.

    Note what is NOT changed here: `claims()` still refuses to count a bodiless claim for ADMISSION, and
    that direction is deliberate and correct — counting an unattributable claim would refuse on evidence
    nobody can act on. The defect was never the ordering; it was that the litter could not be cleared and
    was never mentioned.
    """

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        #: Injected: the fixtures below stage files carrying a fabricated pid, and whether that number
        #: happens to be a live process on this host must not decide a verdict. `self.live_pids` is what the
        #: pool believes is running.
        self.live_pids: set = set()
        self.pool = Pool(self.home, cwd_probe=lambda p: [], alive=lambda name: False,
                         pid_alive=lambda pid: pid in self.live_pids)
        for n in ("ws1", "ws2"):
            d = self.tmp / n; d.mkdir(parents=True); self.pool.enroll(d)

    def interrupt(self, slot="ws1", body=True, pid=999999):
        """Reproduce the crash: the claim dir exists and the body is still under its staging name.

        The staging name comes from the product's own `tmp_name`, not a hand-written guess — a fixture that
        invents the pattern would keep passing if the pattern changed.
        """
        from fleet.atomic import TMP_SUFFIX
        claim_dir = self.home / "pool" / "leases" / slot
        claim_dir.mkdir(parents=True)
        if body:
            # `tmp_name`'s exact shape, with the pid chosen so liveness is controlled by the test:
            # .<target>.<pid>.<monotonic_ns>.<rand48>.tmp
            staged = f".lease.json.{pid}.2058688195526785.f86993c7f39d{TMP_SUFFIX}"
            (claim_dir / staged).write_text('{"slot": "%s"}' % slot)
        return claim_dir

    def test_reap_RECLAIMS_the_interrupted_claim_and_names_it(self):
        claim_dir = self.interrupt("ws1")
        report = self.pool.reap(base_instant="/i/base", min_claim_age_s=0.0)
        self.assertEqual([s for s, _ in report.reclaimed], ["ws1"],
                         "reap did not reclaim the interrupted claim, so the slot is still lost")
        self.assertFalse(claim_dir.exists(), "the claim directory survived the reap")
        self.assertIn("ws1", self.pool.free_slots(),
                      "the slot is still not free after being reclaimed")

    def test_the_reclaim_is_REPORTED_separately_from_a_freed_lease(self):
        """Reclaiming litter and giving back a lease are different acts and a report that conflates them
        tells the operator a worker finished when in fact a process died mid-write."""
        self.interrupt("ws1")
        report = self.pool.reap(base_instant="/i/base", min_claim_age_s=0.0)
        self.assertEqual(report.freed, [], "an interrupted claim was reported as a freed lease")
        self.assertTrue(report.reclaimed[0][1], "the reclaim carries no reason a reader could act on")

    def test_the_slot_is_claimable_again_afterwards(self):
        """The whole point. Before the fix this raised NoCapacity for the life of the store."""
        self.interrupt("ws1")
        self.pool.reap(base_instant="/i/base", min_claim_age_s=0.0)
        lease = self.pool.claim(todo_id="t9", tmux="dt-t9", base_instant="/i/base",
                                child_instant="/i/child", slot="ws1")
        self.assertEqual(lease.slot, "ws1")

    def test_an_EMPTY_claim_younger_than_the_age_floor_is_left_alone(self):
        """The age floor, in the only domain it still governs.

        This case first asserted the floor over ANY young bodiless claim, which was right about the design it
        was written against and is wrong about this one: a staging file names its writer, so a DEAD writer now
        licenses an immediate reclaim whatever the age (see the pid cases below). Re-aimed rather than
        deleted — the invariant it was protecting, *never delete a claim that might be mid-birth*, is real and
        still needs a case; what changed is which evidence settles it.

        With no staging file there is no pid, so time is the only evidence there is, and the floor is what
        stands between a reap and a lease a live process is about to write.
        """
        claim_dir = self.interrupt("ws1", body=False)          # empty dir: nothing records the writer
        report = self.pool.reap(base_instant="/i/base", min_claim_age_s=3600.0)
        self.assertEqual(report.reclaimed, [],
                         "an empty claim younger than the floor was reclaimed, and nothing about it says "
                         "whether its writer is alive")
        self.assertTrue(claim_dir.exists())

    def test_an_interrupted_claim_is_not_reported_as_a_FREE_slot(self):
        """Half of the defect was that two readers disagreed. `lease()` still returns None -- there is no
        owner to report -- but the slot must not be described as free, because it cannot be claimed."""
        self.interrupt("ws1")
        self.assertNotIn("ws1", self.pool.free_slots())
        self.assertEqual([s for s, _ in self.pool.interrupted_claims(min_age_s=0.0)], ["ws1"])

    def test_claims_still_refuses_to_count_it_for_admission(self):
        """Deliberately unchanged (`FI-21`, `D-6`): an unattributable claim must not decide admission."""
        self.interrupt("ws1")
        self.assertEqual(self.pool.claims(settle_s=0.0), [])

    def test_the_refusal_names_the_condition_and_a_remedy_that_WORKS(self):
        """`FI-30a`'s family: a red light whose remedy does not exist is an unclearable alarm. The shipped
        message said 'already leased by an unnamed claim' and the exhausted-pool message sent the operator
        to `reap`, which was inert on exactly this."""
        self.interrupt("ws1")
        with self.assertRaises(NoCapacity) as caught:
            self.pool.claim(todo_id="t2", tmux="dt-t2", base_instant="/i/base",
                            child_instant="/i/child", slot="ws1")
        message = str(caught.exception)
        self.assertIn("interrupted", message.lower(),
                      f"the refusal does not say what is actually wrong: {message!r}")
        self.assertIn("reap", message.lower(),
                      f"the refusal names no remedy: {message!r}")

    def test_an_EMPTY_claim_dir_counts_too(self):
        """The crash can also land before the staging file exists. A fix keyed on 'has a .tmp file' would
        miss it and leave exactly the same permanent leak."""
        self.interrupt("ws2", body=False)
        report = self.pool.reap(base_instant="/i/base", min_claim_age_s=0.0)
        self.assertEqual([s for s, _ in report.reclaimed], ["ws2"])

    def test_a_claim_dir_holding_an_UNEXPECTED_file_is_reported_not_deleted(self):
        """A reclaim removes staging litter and nothing else. Anything unrecognised is somebody's data, so
        it is named in `unfreed` rather than swept -- `M9`'s rule, applied to my own new delete site."""
        claim_dir = self.interrupt("ws1")
        (claim_dir / "something-a-human-put-here.txt").write_text("keep me")
        report = self.pool.reap(base_instant="/i/base", min_claim_age_s=0.0)
        self.assertEqual(report.reclaimed, [])
        self.assertEqual([s for s, _ in report.unfreed], ["ws1"],
                         "an unrecognised file was neither reclaimed nor reported")
        self.assertTrue((claim_dir / "something-a-human-put-here.txt").is_file(),
                        "a reclaim deleted a file it did not recognise")

    def test_the_leases_VIEW_does_not_call_it_free(self):
        """The other half of `SI-7`'s disagreement, in the reporting layer. `leases` is the verb an operator
        reads to see capacity, and it labelled an unclaimable slot `free` because it asked `lease()`, which
        reads the body. Acting on that answer gets you `NoCapacity`."""
        from fleet import render
        self.interrupt("ws1")
        porcelain = render.leases(self.pool, porcelain=True)
        row = [l for l in porcelain.splitlines() if l.startswith("ws1\t")][0]
        self.assertEqual(row.split("\t")[1], "interrupted",
                         f"the leases view still describes an unclaimable slot as free: {row!r}")
        self.assertIn("INTERRUPTED", render.leases(self.pool),
                      "the human form does not mention it at all")
        # And the slot that really is free is still called free -- a fix that relabels everything is not a fix.
        free_row = [l for l in porcelain.splitlines() if l.startswith("ws2\t")][0]
        self.assertEqual(free_row.split("\t")[1], "free")

    def test_a_DEAD_writer_makes_the_claim_reclaimable_immediately_whatever_its_age(self):
        """The better discriminator, and the reason the age floor is a fallback rather than the rule.
        `atomic.tmp_name` puts the writer's pid in the staging file's name, so an unfinished write identifies
        its own author even though the body that would name an owner is exactly what is missing. A dead pid
        is a FACT that the claim will never be finished; elapsed time is only ever an inference.

        This matters concretely: `E9` SIGKILLs a dispatcher and reaps within seconds, so a rule keyed on a
        30-second floor would leave the slot stuck and the case red — the fix would not fix the failure that
        found it."""
        self.interrupt("ws1", pid=999999)           # not in self.live_pids => dead
        stuck = self.pool.interrupted_claims()      # SHIPPED default floor, deliberately not lowered
        self.assertEqual([s for s, _ in stuck], ["ws1"])
        self.assertIn("999999", stuck[0][1], "the report does not name the process it judged dead")
        report = self.pool.reap(base_instant="/i/base")
        self.assertEqual([s for s, _ in report.reclaimed], ["ws1"])

    def test_a_young_EMPTY_claim_is_reported_even_though_it_is_not_reclaimed(self):
        """`E9` mode 2, caught under load 2026-08-02.

        A SIGKILL between the `mkdir` and the staging write leaves the claim directory COMPLETELY empty —
        no body and no staging file, so no pid, so no evidence the writer is dead. Below the age floor
        `interrupted_claims` correctly declines it: *"a bodiless claim cannot be told apart from a claim
        mid-birth, and treating one as the other deletes a live worker's lease."* That decline is right
        and this test does not challenge it.

        What is wrong is the SILENCE. The slot is unclaimable RIGHT NOW, the condition is plainly
        observable, and `reap` — the remedy the capacity refusal names — emitted nothing at all: its whole
        report was `0 interrupted claim(s) reclaimed` while a third of the pool was blocked. The operator
        cannot tell a pool that is busy from a pool that is stuck, and `E9` could not tell "reap declined,
        and said so" from "reap never noticed".

        So: NOT reclaimed, NOT deleted, but REPORTED — with how long to wait.
        """
        claim = self.home / "pool" / "leases" / "ws1"
        claim.mkdir(parents=True)                    # empty: no body, no staging file, no pid anywhere
        self.assertEqual(self.pool.interrupted_claims(), [],
                         "a young empty claim must not be reclaimable — that direction deletes live work")

        report = self.pool.reap(base_instant="/i/base")
        self.assertEqual(report.reclaimed, [], "a young empty claim was CLEARED; the floor exists to stop that")
        self.assertTrue(claim.is_dir(), "the claim directory was deleted")
        self.assertEqual([s for s, _, _ in report.unattributable], ["ws1"],
                         "reap did not report the slot it is currently unable to attribute")
        slot, why, wait = report.unattributable[0]
        self.assertGreater(wait, 0, "the report does not say how long until it can be judged")
        self.assertLessEqual(wait, 30.0)
        self.assertIn("empty", why.lower(), f"the reason does not describe the state: {why}")

    def test_an_OLD_empty_claim_is_reclaimed_rather_than_merely_reported(self):
        """The floor is a delay, not a refusal. Once past it the empty claim IS cleared, so the new
        reporting bucket must not become a way for a stuck slot to be announced forever and never fixed."""
        import os, time
        claim = self.home / "pool" / "leases" / "ws1"
        claim.mkdir(parents=True)
        old = time.time() - 3600
        os.utime(claim, (old, old))
        report = self.pool.reap(base_instant="/i/base")
        self.assertEqual([s for s, _ in report.reclaimed], ["ws1"])
        self.assertEqual(report.unattributable, [],
                         "a claim that was reclaimed must not ALSO be reported as unattributable")

    def test_a_LIVE_writer_is_never_reclaimed_however_the_floor_is_set(self):
        """The expensive direction. A claim whose writer is still running is mid-birth, and deleting it hands
        the same slot to a second claimant while the first believes it holds the lease. No floor, however
        low, may override a live pid."""
        self.interrupt("ws1", pid=4242)
        self.live_pids.add(4242)
        self.assertEqual(self.pool.interrupted_claims(min_age_s=0.0), [],
                         "a claim whose writer is ALIVE was reported as litter")
        report = self.pool.reap(base_instant="/i/base", min_claim_age_s=0.0)
        self.assertEqual(report.reclaimed, [])
        self.assertTrue((self.home / "pool" / "leases" / "ws1").is_dir())

    def test_a_staging_name_that_is_not_ours_is_not_parsed_for_a_pid(self):
        """A wrong pid would be read as "some unrelated live process", which fails safe — but only if the
        parse REFUSES on an unfamiliar shape instead of improvising. Here the file looks like staging litter
        but carries no parseable pid, so the age floor is what decides."""
        from fleet.pool import _pid_in_staging_name
        self.assertIsNone(_pid_in_staging_name(".lease.json.tmp"))
        self.assertIsNone(_pid_in_staging_name(".lease.json.notapid.123.abcdef123456.tmp"))
        self.assertIsNone(_pid_in_staging_name("lease.json"))
        self.assertEqual(_pid_in_staging_name(".lease.json.777.2058688195526785.f86993c7f39d.tmp"), 777)
