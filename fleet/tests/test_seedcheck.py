"""Seed-delivery integrity.

Every fixture here is DERIVED FROM THE LIVE INCIDENT rather than invented: the misdelivered shape is the
one `dt-i1selfcertifyingcontrols` actually carried (a coordinator briefing, in a worker's argv, with the
worker's own seed absent), and the legitimate shapes are the ones the live fleet and §P actually produce
(a bare seed, and a seed with a caller's preamble prepended). A decoy frozen at authoring time tests the
author's imagination; one derived from the live input tests the code.

The two measurement errors that inverted the answer while this was being written are each pinned by a case
below — `test_argv_is_split_on_nul_not_newline` and `test_not_delivered_is_not_a_pass` — because both read
exactly like "no defect" and both were believed for a while.
"""
import pathlib
import shutil
import unittest

from fleet import seedcheck


#: The shipped worker profile renders to ~1210 chars. Long enough to be a real payload, and it is the
#: instant path inside it that makes two seeds distinguishable.
def _seed(instant: str, milestone: str) -> str:
    return (
        f"You are a dispatched worker instant. Your workspace is {instant}.\n"
        "\n"
        "FIRST, orient yourself. Do not guess any of this:\n"
        f"    export INSTANT={instant}          # your cwd is the leased SLOT, not your instant folder\n"
        '    fleet brief --instant "$INSTANT"\n'
        "\n"
        f"You were dispatched for milestone {milestone} by the coordinator.\n"
        "Your CHARTER.md is authoritative for your scope.\n"
        + ("padding that makes this the size of a real briefing. " * 20)
    )


WORKER_INSTANT = "/home/ubuntu/davis_root/operations/tasks/metaOpt/fleetInfraOps/00000000-08072017-inflight-append-i1selfcertifyingcontrols"
COORD_INSTANT = "/home/ubuntu/davis_root/operations/tasks/quantonOnSpark4V2/instants/00000000-07310348-inflight-append-v2stackcoordinator"

OWN_SEED = _seed(WORKER_INSTANT, "i1-self-certifying-controls")
COORD_SEED = _seed(COORD_INSTANT, "(the coordinator's own bootstrap briefing)")

CLAUDE = "/home/ubuntu/.local/bin/claude"


class TestPayload(unittest.TestCase):
    def test_flags_are_never_the_payload(self):
        argv = [CLAUDE, "--permission-mode", "auto", OWN_SEED]
        self.assertEqual(seedcheck.payload(argv), OWN_SEED)

    def test_a_bare_claude_has_no_payload(self):
        self.assertIsNone(seedcheck.payload([CLAUDE]))
        self.assertIsNone(seedcheck.payload([CLAUDE, "--permission-mode", "auto"]))

    def test_a_short_positional_is_not_a_briefing(self):
        self.assertIsNone(seedcheck.payload([CLAUDE, "--continue", "resume the last session"]))

    def test_the_longest_candidate_wins(self):
        short = "x" * (seedcheck.MIN_PAYLOAD_CHARS + 1)
        self.assertEqual(seedcheck.payload([CLAUDE, short, OWN_SEED]), OWN_SEED)


class TestSplitArgv(unittest.TestCase):
    def test_argv_is_split_on_nul_not_newline(self):
        """The measurement error that produced a FALSE NEGATIVE on the live incident.

        A seed contains newlines. Splitting on them turns one argument into hundreds and makes the last
        "argument" the seed's last LINE, which matches nothing — so the misdelivered session was reported
        as carrying "some other prompt". Here the whole seed must survive as ONE element.
        """
        raw = b"\0".join([CLAUDE.encode(), b"--permission-mode", b"auto", OWN_SEED.encode()]) + b"\0"
        argv = seedcheck.split_argv(raw)
        self.assertEqual(len(argv), 4)
        self.assertEqual(argv[-1], OWN_SEED)
        self.assertIn("\n", argv[-1], "the seed's own newlines must stay inside one argument")

    def test_trailing_nul_does_not_produce_an_empty_argument(self):
        self.assertEqual(seedcheck.split_argv(b"claude\0"), ["claude"])
        self.assertEqual(seedcheck.split_argv(b"claude"), ["claude"])


class TestClassify(unittest.TestCase):
    def test_the_good_case_verifies(self):
        argv = [CLAUDE, "--permission-mode", "auto", OWN_SEED]
        self.assertEqual(seedcheck.classify(OWN_SEED, argv).state, seedcheck.VERIFIED)

    def test_a_caller_preamble_still_verifies(self):
        """§P's wrapper and the live i2 dispatch both PREPEND to the seed. That is delivery, not misdelivery."""
        delivered = f"Your instant folder is {WORKER_INSTANT} and your leased slot is /ws1.\n\n{OWN_SEED}"
        argv = [CLAUDE, "--permission-mode", "auto", delivered]
        self.assertEqual(seedcheck.classify(OWN_SEED, argv).state, seedcheck.VERIFIED)

    def test_trailing_whitespace_is_not_a_misdelivery(self):
        argv = [CLAUDE, "--permission-mode", "auto", OWN_SEED.rstrip() + "\n\n\n"]
        self.assertEqual(seedcheck.classify(OWN_SEED, argv).state, seedcheck.VERIFIED)

    def test_THE_INCIDENT_a_coordinator_briefing_in_a_workers_argv_is_FOREIGN(self):
        """The known-bad input: what `dt-i1selfcertifyingcontrols` was actually started with."""
        argv = [CLAUDE, "--permission-mode", "auto", COORD_SEED]
        verdict = seedcheck.classify(OWN_SEED, argv, session="dt-i1selfcertifyingcontrols", pid=2005207)
        self.assertEqual(verdict.state, seedcheck.FOREIGN)
        self.assertFalse(verdict.ok)
        self.assertIn(COORD_INSTANT, verdict.detail,
                      "a FOREIGN verdict must NAME whose briefing arrived, or the reader has to start over")

    def test_not_delivered_is_not_a_pass(self):
        """`FI-195`'s shape. 'I cannot see what was delivered' must never read as 'it was correct'."""
        verdict = seedcheck.classify(OWN_SEED, [CLAUDE, "--permission-mode", "auto"])
        self.assertEqual(verdict.state, seedcheck.NOT_DELIVERED)
        self.assertFalse(verdict.ok, "NOT-DELIVERED must not be ok")
        self.assertNotEqual(verdict.state, seedcheck.VERIFIED)

    def test_the_three_states_are_distinct(self):
        """Collapsing FOREIGN and NOT-DELIVERED sends the reader to the wrong remedy."""
        states = {
            seedcheck.classify(OWN_SEED, [CLAUDE, "--permission-mode", "auto", OWN_SEED]).state,
            seedcheck.classify(OWN_SEED, [CLAUDE, "--permission-mode", "auto", COORD_SEED]).state,
            seedcheck.classify(OWN_SEED, [CLAUDE]).state,
        }
        self.assertEqual(states, {seedcheck.VERIFIED, seedcheck.FOREIGN, seedcheck.NOT_DELIVERED})

    def test_a_truncated_seed_is_foreign_not_verified(self):
        """The permissive direction is the dangerous one: half a briefing is not the briefing."""
        argv = [CLAUDE, "--permission-mode", "auto", OWN_SEED[:len(OWN_SEED) // 2]]
        self.assertEqual(seedcheck.classify(OWN_SEED, argv).state, seedcheck.FOREIGN)


#: A CI waiter, as `awaiting-ci` workers actually run one: a shell holding a long inline script. It is a
#: NON-flag argument well over `MIN_PAYLOAD_CHARS`, which is precisely the shape `payload()` is looking
#: for — and it is a CHILD of the claude process, which is precisely where `delivered_argv` looks next.
CI_WAITER = [
    "/bin/bash", "-c",
    "while true; do "
    "  status=$(gh run list --branch \"$BRANCH\" --limit 1 --json status,conclusion --jq '.[0].status'); "
    "  if [ \"$status\" = completed ]; then gh run view --log-failed | tail -200; break; fi; "
    "  sleep 30; "
    "done  # keep this long enough to clear MIN_PAYLOAD_CHARS the way a real waiter does, which is "
    "the entire point of the fixture: it is not contrived, it is the shortest honest form of the thing.",
]


class TestDeliveredArgv(unittest.TestCase):
    def _probes(self, table, kids=None, comms=None):
        kids, comms = kids or {}, comms or {}
        return seedcheck.Probes(
            read_cmdline=lambda pid: table.get(pid),
            children_of=lambda pid: kids.get(pid, []),
            #: `SI-52`. Default `claude` so a case that is not ABOUT identity keeps testing what it was
            #: written to test; the cases that are about it say so.
            comm_of=lambda pid: comms.get(pid, "claude"),
        )

    def test_reads_the_pane_process_when_the_launcher_execd(self):
        raw = b"\0".join([CLAUDE.encode(), b"--permission-mode", b"auto", OWN_SEED.encode()])
        pid, argv = seedcheck.delivered_argv(42, self._probes({42: raw}))
        self.assertEqual(pid, 42)
        self.assertEqual(argv[-1], OWN_SEED)

    def test_reaches_one_generation_down_when_the_launcher_forked(self):
        parent = b"\0".join([b"/bin/sh", b"-c", b"claude"])
        child = b"\0".join([CLAUDE.encode(), b"--permission-mode", b"auto", OWN_SEED.encode()])
        pid, argv = seedcheck.delivered_argv(1, self._probes({1: parent, 7: child}, {1: [7]}))
        self.assertEqual(pid, 7)
        self.assertEqual(argv[-1], OWN_SEED)

    def test_an_unreadable_process_yields_no_argv_rather_than_raising(self):
        pid, argv = seedcheck.delivered_argv(99, self._probes({}))
        self.assertEqual(argv, [])
        self.assertEqual(seedcheck.classify(OWN_SEED, argv).state, seedcheck.NOT_DELIVERED)

    def test_check_session_classifies_the_incident_end_to_end(self):
        raw = b"\0".join([CLAUDE.encode(), b"--permission-mode", b"auto", COORD_SEED.encode()])
        verdict = seedcheck.check_session("dt-i1", 2005207, OWN_SEED, self._probes({2005207: raw}))
        self.assertEqual(verdict.state, seedcheck.FOREIGN)
        self.assertEqual(verdict.pid, 2005207)


class TestCollisions(unittest.TestCase):
    def test_two_dispatches_with_one_briefing_are_reported(self):
        """The live signal, and it needs no knowledge of what either seed SHOULD have been."""
        shared = seedcheck.digest(COORD_SEED)
        verdicts = [
            seedcheck.Verdict(state=seedcheck.FOREIGN, session="dt-i1selfcertifyingcontrols", delivered_md5=shared),
            seedcheck.Verdict(state=seedcheck.VERIFIED, session="dt-v2stackcoordinator", delivered_md5=shared),
            seedcheck.Verdict(state=seedcheck.VERIFIED, session="dt-w22", delivered_md5=seedcheck.digest(OWN_SEED)),
        ]
        found = seedcheck.collisions(verdicts)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][1], ["dt-i1selfcertifyingcontrols", "dt-v2stackcoordinator"])

    def test_distinct_briefings_collide_with_nothing(self):
        verdicts = [
            seedcheck.Verdict(state=seedcheck.VERIFIED, session="a", delivered_md5=seedcheck.digest(OWN_SEED)),
            seedcheck.Verdict(state=seedcheck.VERIFIED, session="b", delivered_md5=seedcheck.digest(COORD_SEED)),
        ]
        self.assertEqual(seedcheck.collisions(verdicts), [])

    def test_sessions_with_nothing_delivered_do_not_collide_with_each_other(self):
        """Otherwise every send-keys dispatch on the box would 'collide' on the empty payload."""
        verdicts = [
            seedcheck.Verdict(state=seedcheck.NOT_DELIVERED, session="a", delivered_md5=""),
            seedcheck.Verdict(state=seedcheck.NOT_DELIVERED, session="b", delivered_md5=""),
        ]
        self.assertEqual(seedcheck.collisions(verdicts), [])


if __name__ == "__main__":
    unittest.main()


class TestOnlyTheWorkerCarriesTheBriefing(unittest.TestCase):
    """`SI-52`. The walk returned the first process at or below the pane holding ANY long positional, and
    nothing in this module ever asked whether that process was the worker.

    A worker in `awaiting-ci` runs a CI waiter — a shell holding a long inline script — as a child of the
    claude process. That is exactly the shape `payload()` looks for, so `carries()` was false and
    `classify` returned **FOREIGN**, whose remedy is *"the worker is dispatched again"*. The check fired
    on the population it is most often pointed at, and told the reader to throw away a healthy worker.

    The asymmetry is why this matters more than a wrong label: `NOT_DELIVERED` is deliberately
    non-refusing, while `FOREIGN` KILLS the session inside `dispatch`. An uncertain probe must not be able
    to reach the destructive verdict.
    """

    def _probes(self, table, kids=None, comms=None):
        kids, comms = kids or {}, comms or {}
        return seedcheck.Probes(read_cmdline=lambda pid: table.get(pid),
                                children_of=lambda pid: kids.get(pid, []),
                                comm_of=lambda pid: comms.get(pid))

    @staticmethod
    def _raw(argv):
        return b"\0".join(a.encode() for a in argv)

    def test_a_ci_waiter_under_a_healthy_worker_is_not_read_as_a_briefing(self):
        """The live defect, in its live shape: a send-keys delivery (nothing in claude's argv) plus a
        waiter child. The old walk returned the waiter and the answer was FOREIGN."""
        table = {100: self._raw([CLAUDE, "--permission-mode", "auto"]),
                 200: self._raw(CI_WAITER)}
        probes = self._probes(table, kids={100: [200]}, comms={100: "claude", 200: "bash"})

        verdict = seedcheck.check_session("dt-worker", 100, OWN_SEED, probes)

        self.assertNotEqual(seedcheck.FOREIGN, verdict.state,
                            f"a healthy worker's CI waiter was read as a foreign briefing, and the "
                            f"remedy printed for that is to dispatch the worker again: {verdict.detail}")
        self.assertEqual(seedcheck.NOT_DELIVERED, verdict.state, verdict.detail)

    def test_a_foreign_briefing_delivered_to_the_CLAUDE_process_is_still_foreign(self):
        """The narrowing must not trade one false answer for another. The 2026-08-07 misdelivery was a
        shim that `exec`d the real binary with somebody else's seed in argv — the process holding the
        briefing WAS claude, so it is still visible and still refuses."""
        table = {100: self._raw([CLAUDE, "--permission-mode", "auto", COORD_SEED])}
        probes = self._probes(table, comms={100: "claude"})

        verdict = seedcheck.check_session("dt-worker", 100, OWN_SEED, probes)

        self.assertEqual(seedcheck.FOREIGN, verdict.state, verdict.detail)
        self.assertIn(COORD_INSTANT, verdict.detail,
                      "the alarm does not say whose briefing arrived")

    def test_a_forked_claude_child_is_still_reached(self):
        table = {1: self._raw(["/bin/sh", "-c", "claude"]),
                 7: self._raw([CLAUDE, "--permission-mode", "auto", OWN_SEED])}
        probes = self._probes(table, kids={1: [7]}, comms={1: "sh", 7: "claude"})

        verdict = seedcheck.check_session("dt-worker", 1, OWN_SEED, probes)

        self.assertEqual(seedcheck.VERIFIED, verdict.state, verdict.detail)
        self.assertEqual(7, verdict.pid, "the verdict names the wrong process")

    def test_a_process_whose_identity_cannot_be_read_is_not_treated_as_the_worker(self):
        """Fail-safe direction. `FOREIGN` authorises a kill, so 'I could not tell what this is' must
        degrade to unverifiable and never to the destructive verdict."""
        table = {100: self._raw(["/bin/bash", "-c", CI_WAITER[2]])}
        probes = self._probes(table, comms={})            # comm_of answers None for every pid

        verdict = seedcheck.check_session("dt-worker", 100, OWN_SEED, probes)

        self.assertEqual(seedcheck.NOT_DELIVERED, verdict.state, verdict.detail)

    def test_the_detail_says_no_worker_process_was_found_rather_than_implying_one_was_looked_at(self):
        table = {100: self._raw(["/bin/bash", "-c", CI_WAITER[2]])}
        probes = self._probes(table, comms={100: "bash"})

        verdict = seedcheck.check_session("dt-worker", 100, OWN_SEED, probes)

        self.assertRegex(verdict.detail, r"(?i)claude",
                         f"the reader cannot tell that NOTHING was examined: {verdict.detail!r}")

    def test_the_real_probes_answer_comm_for_this_very_process(self):
        """The injected seam is only as good as the real one behind it. `default_probes` is what every
        caller in the package actually gets, and a `comm_of` that always answered None would make every
        session unverifiable while every test above stayed green."""
        import os

        self.assertTrue(seedcheck.default_probes().comm_of(os.getpid()),
                        "the real comm probe answers nothing for a process that certainly exists")
        self.assertIsNone(seedcheck.default_probes().comm_of(0),
                          "the real comm probe invented an answer for a pid that cannot be read")


class TestAnAttestedDelivery(unittest.TestCase):
    """`SI-55`. The positive state was reachable by exactly one route — the briefing appearing in
    `/proc/<pid>/cmdline` — and a seed delivered by `send-keys` never appears in argv at all.

    So a worker rescued by `reviving-dead-panes`, or briefed by any send-keys launcher, read
    `NOT-DELIVERED` for the life of the instant while its sibling read `VERIFIED`. `NOT-DELIVERED`'s own
    detail says, correctly, that it is *"not evidence that anything is wrong, and not evidence that
    anything is right"* — and a row that can never change is a row that stops being read, which is
    `FI-402`'s shape.

    What the deliverer can supply that is EVIDENCE rather than a claim is the bytes it sent: `fleet`
    digests them itself and compares against what it rendered, which catches the class the module exists
    for — the launcher sent the wrong file. It is a DISTINCT state, because observed-in-argv and
    recorded-by-the-deliverer have different failure modes and collapsing two states whose remedies differ
    is the `FI-195` error.
    """

    def _delivery(self, text, channel="send-keys"):
        return seedcheck.Delivery(at="2026-09-06T00:00:00Z", by="dt-worker", channel=channel,
                                  delivered_chars=len(text), delivered_md5=seedcheck.digest(text),
                                  rendered_md5=seedcheck.digest(OWN_SEED))

    def test_a_recorded_delivery_of_this_seed_is_a_distinct_positive_state(self):
        verdict = seedcheck.classify(OWN_SEED, [CLAUDE], delivery=self._delivery(OWN_SEED))

        self.assertEqual(seedcheck.ATTESTED, verdict.state, verdict.detail)
        self.assertNotEqual(seedcheck.VERIFIED, verdict.state,
                            "an attestation was collapsed into VERIFIED; the two have different failure "
                            "modes and a reader must be able to tell which one they have")

    def test_attested_is_a_pass_and_not_delivered_still_is_not(self):
        self.assertTrue(seedcheck.classify(OWN_SEED, [CLAUDE],
                                           delivery=self._delivery(OWN_SEED)).ok)
        self.assertFalse(seedcheck.classify(OWN_SEED, [CLAUDE]).ok,
                         "NOT-DELIVERED became a pass")

    def test_the_detail_names_the_channel_rather_than_implying_argv(self):
        verdict = seedcheck.classify(OWN_SEED, [CLAUDE], delivery=self._delivery(OWN_SEED))

        self.assertIn("send-keys", verdict.detail)
        self.assertRegex(verdict.detail, r"(?i)record",
                         f"the detail does not say this was RECORDED rather than observed: "
                         f"{verdict.detail!r}")

    def test_an_attestation_never_suppresses_a_foreign_observation(self):
        """The dangerous direction. A briefing visible in argv that is NOT this instant's is the incident
        this module exists for, and a recorded delivery must not be able to hide it."""
        verdict = seedcheck.classify(OWN_SEED, [CLAUDE, COORD_SEED], delivery=self._delivery(OWN_SEED))

        self.assertEqual(seedcheck.FOREIGN, verdict.state, verdict.detail)

    def test_a_recorded_delivery_of_a_DIFFERENT_seed_is_not_a_pass(self):
        """The attestation is compared, not believed."""
        stale = seedcheck.Delivery(at="2026-09-06T00:00:00Z", by="dt-worker", channel="send-keys",
                                   delivered_chars=len(COORD_SEED),
                                   delivered_md5=seedcheck.digest(COORD_SEED),
                                   rendered_md5=seedcheck.digest(COORD_SEED))

        verdict = seedcheck.classify(OWN_SEED, [CLAUDE], delivery=stale)

        self.assertEqual(seedcheck.NOT_DELIVERED, verdict.state, verdict.detail)
        self.assertFalse(verdict.ok)

    def test_argv_evidence_still_wins_when_both_agree(self):
        verdict = seedcheck.classify(OWN_SEED, [CLAUDE, OWN_SEED], delivery=self._delivery(OWN_SEED))

        self.assertEqual(seedcheck.VERIFIED, verdict.state,
                         "the weaker channel outranked the stronger one")

    def test_a_delivery_round_trips_through_the_instant(self):
        import tempfile
        instant = pathlib.Path(tempfile.mkdtemp())
        try:
            self.assertIsNone(seedcheck.read_delivery(instant),
                              "an instant with no recorded delivery must answer None, not raise")
            written = self._delivery(OWN_SEED)
            seedcheck.write_delivery(instant, written)
            self.assertEqual(written, seedcheck.read_delivery(instant))
        finally:
            shutil.rmtree(instant, ignore_errors=True)
