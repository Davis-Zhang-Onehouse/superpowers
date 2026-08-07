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


class TestDeliveredArgv(unittest.TestCase):
    def _probes(self, table, kids=None):
        kids = kids or {}
        return seedcheck.Probes(
            read_cmdline=lambda pid: table.get(pid),
            children_of=lambda pid: kids.get(pid, []),
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
