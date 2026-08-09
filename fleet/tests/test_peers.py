"""Behavioural coverage for `fleet peers` — the provenance whitelist that bounds cross-session sends.

WHY THIS FILE EXISTS, and it is the point rather than boilerplate.

The verb shipped with a control suite and a six-mutant gate — both of which lived in an effort
instant's `investigations/` directory that nothing ever runs, and whose folder is renamed at
completion. The 1368-test suite contained exactly two references to `peers`, both argv-table stubs.
So the release gate would have passed a `peers.py` with every one of its known fail-opens
reintroduced. A control no sweep invokes is the same "absence reads as pass" defect the verb's own
review kept finding.

Every case below is a REGRESSION of a defect that was actually shipped and caught in review, named
in its docstring. They are hermetic: no `claude` binary, no real `/proc`, no live sessions — the
liveness probe is pointed at a synthetic tree, so the suite cannot depend on what happens to be
running on the box.
"""

import json
import os
import shutil
import tempfile
import unittest

from fleet import peers


def _proc(root, pid, cwd=None):
    """Create <root>/<pid>, and a `cwd` symlink to <cwd> when given (absent = unreadable)."""
    d = os.path.join(root, str(pid))
    os.makedirs(d, exist_ok=True)
    if cwd is not None:
        link = os.path.join(d, "cwd")
        if not os.path.exists(link):
            os.symlink(cwd, link)
    return d


def _row(pid, cwd, name="peer", status="idle"):
    return {"name": name, "pid": pid, "cwd": cwd, "status": status, "sessionId": f"s{pid}"}


def _lease(slot, **kw):
    base = {"golden": slot, "child_instant": "/instants/child", "milestone": "M1",
            "tmux": "dt-child", "todo_id": "child-1", "closed_at": None, "harvested_at": None}
    base.update(kw)
    return base


class PeersFailClosed(unittest.TestCase):
    """`load_peers` must refuse anything it cannot establish provenance from."""

    def test_a_degenerate_cwd_is_refused_rather_than_resolved_against_our_own_cwd(self):
        """SHIPPED FAIL-OPEN. `realpath("")` and `realpath(".")` return the CALLING process's cwd —
        and the verb runs from inside a leased slot — so an empty cwd inherited our own lease and a
        FOREIGN peer was classified OURS, stamped with our milestone. Reproduced on a live peer."""
        for bad in ("", "   ", ".", "relative/path", None, ["/tmp"]):
            with self.subTest(cwd=bad):
                with self.assertRaises(peers.PeersUnavailable):
                    peers.load_peers(json_text=json.dumps([_row(1, "/x") | {"cwd": bad}]))

    def test_a_degenerate_pid_is_refused(self):
        for bad in ("abc", None, 0, -1):
            with self.subTest(pid=bad):
                with self.assertRaises(peers.PeersUnavailable):
                    peers.load_peers(json_text=json.dumps([_row(1, "/x") | {"pid": bad}]))

    def test_a_nul_byte_or_non_string_field_refuses_instead_of_raising_a_traceback(self):
        """These reached `os.path.realpath` / a format spec and escaped as ValueError/TypeError —
        not FleetError, so the CLI printed a traceback instead of a refusal anyone could act on."""
        for row in (_row(1, "/x\x00evil"), _row(1, "/x") | {"name": None},
                    _row(1, "/x") | {"status": ["idle"]}):
            with self.subTest(row=row):
                with self.assertRaises(peers.PeersUnavailable):
                    peers.load_peers(json_text=json.dumps(row and [row]))

    def test_malformed_envelopes_refuse(self):
        for text in ("not json", json.dumps({"sessions": []}), json.dumps(["a string row"])):
            with self.subTest(text=text[:20]):
                with self.assertRaises(peers.PeersUnavailable):
                    peers.load_peers(json_text=text)

    def test_the_unmutated_shape_is_ACCEPTED_so_the_refusals_above_discriminate(self):
        """Without this, every refusal above would pass on a `load_peers` that refused everything."""
        rows = peers.load_peers(json_text=json.dumps([_row(1, "/x")]))
        self.assertEqual(len(rows), 1)


class PeersOwnership(unittest.TestCase):
    """Only an OPEN lease on the peer's exact cwd confers OURS."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t_peers.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.slot = os.path.join(self.tmp, "ws1")
        os.makedirs(self.slot, exist_ok=True)
        self.proc = os.path.join(self.tmp, "proc")
        _proc(self.proc, 100, self.slot)
        self.rows = [_row(100, self.slot)]

    def _verdict(self, leases, proc_root=None):
        got = peers.classify(self.rows, leases, self_pid=-1, proc_root=proc_root or self.proc)
        return got[0]["verdict"]

    def test_an_open_lease_on_the_slot_confers_OURS(self):
        self.assertEqual(self._verdict([_lease(self.slot)]), peers.OURS)

    def test_a_CLOSED_lease_does_not_confer_OURS(self):
        """Slots are RE-LEASED — one slot hosted three milestones — so matching on slot alone would
        attribute a live session to whichever record sorted first, quite possibly a closed one."""
        for closer in ("closed_at", "harvested_at"):
            with self.subTest(closer=closer):
                self.assertEqual(self._verdict([_lease(self.slot, **{closer: "2026-01-01T00:00:00Z"})]),
                                 peers.FOREIGN)

    def test_two_open_leases_on_one_slot_refuse_rather_than_pick_one(self):
        self.assertEqual(self._verdict([_lease(self.slot), _lease(self.slot, todo_id="impostor")]),
                         peers.FOREIGN)

    def test_a_near_miss_path_does_not_inherit_the_slot(self):
        """Guards against a future `startswith`/prefix "simplification"."""
        for cwd in (os.path.dirname(self.slot), os.path.join(self.slot, "sub"), self.slot + "x"):
            with self.subTest(cwd=cwd):
                os.makedirs(cwd, exist_ok=True)
                proc = os.path.join(self.tmp, "proc-" + os.path.basename(cwd))
                _proc(proc, 100, cwd)
                got = peers.classify([_row(100, cwd)], [_lease(self.slot)], self_pid=-1, proc_root=proc)
                self.assertEqual(got[0]["verdict"], peers.FOREIGN)

    def test_a_non_normalised_path_still_resolves_to_the_slot(self):
        proc = os.path.join(self.tmp, "proc-norm")
        _proc(proc, 100, self.slot)
        got = peers.classify([_row(100, self.slot + "/./")], [_lease(self.slot)],
                             self_pid=-1, proc_root=proc)
        self.assertEqual(got[0]["verdict"], peers.OURS)

    def test_a_second_LIVE_session_in_one_slot_makes_both_unaddressable(self):
        """SHIPPED FAIL-OPEN. Ownership was keyed on the slot DIRECTORY, and nothing tied a row to
        the session the lease was issued for — so `cd ws1 && claude`, which a human might simply do,
        was classified OURS and misattributed to that milestone."""
        _proc(self.proc, 101, self.slot)
        rows = [_row(100, self.slot), _row(101, self.slot, name="co-tenant")]
        got = peers.classify(rows, [_lease(self.slot)], self_pid=-1, proc_root=self.proc)
        self.assertEqual({r["verdict"] for r in got}, {peers.FOREIGN})
        self.assertEqual(peers.porcelain(got, addressable_only=True), "")
        # SHIPPED DEFECT, and the assertion that locks it. Lease columns were attached BEFORE the
        # verdict, so a FOREIGN co-tenant was rendered carrying OUR milestone and OUR tmux name
        # beside a stranger's row -- a human acting on it sends keys to our worker believing they
        # reach that peer. Without this line the fix reverts silently.
        self.assertEqual({(r["milestone"], r["tmux"], r["instant"]) for r in got}, {("", "", "")})

    def test_two_rows_sharing_one_pid_cannot_launder_the_cwd_cross_check(self):
        """SHIPPED FAIL-OPEN, introduced while fixing another. Liveness was sampled into a dict keyed
        by PID, so with two rows on one pid the LAST decided for BOTH -- a stale row claiming our
        slot inherited the truthful row's liveness and classified OURS. Two rows on one pid is
        exactly the recycled-pid case the cross-check exists for."""
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(elsewhere, exist_ok=True)
        proc = os.path.join(self.tmp, "proc-shared")
        _proc(proc, 88, elsewhere)                     # pid 88 REALLY lives in `elsewhere`
        rows = [_row(88, self.slot, name="EVIL"),       # the lie, listed FIRST
                _row(88, elsewhere, name="truthful")]  # the truth, listed LAST
        got = peers.classify(rows, [_lease(self.slot)], self_pid=-1, proc_root=proc)
        by_name = {r["name"]: r["verdict"] for r in got}
        self.assertNotEqual(by_name["EVIL"], peers.OURS)
        self.assertEqual(peers.porcelain(got, addressable_only=True), "")

    def test_liveness_is_sampled_exactly_once_per_row(self):
        """Re-probing inside the verdict loop lets a peer that exits mid-run count as live for
        `contested` and dead for its own verdict — one invocation returning a self-inconsistent
        answer. Comparing two deterministic runs cannot see that; counting the probes can."""
        _proc(self.proc, 101, self.slot)
        rows = [_row(100, self.slot), _row(101, self.slot, name="co-tenant")]
        calls = []
        real = peers._is_live

        def counting(pid, cwd, proc_root="/proc"):
            calls.append((pid, cwd))
            return real(pid, cwd, proc_root=proc_root)

        peers._is_live = counting
        try:
            peers.classify(rows, [_lease(self.slot)], self_pid=-1, proc_root=self.proc)
        finally:
            peers._is_live = real
        self.assertEqual(len(calls), len(rows),
                         f"liveness probed {len(calls)} times for {len(rows)} rows -- "
                         "re-sampling lets contested and the verdict disagree")


class PeersLiveness(unittest.TestCase):
    """Liveness is a pid whose ACTUAL cwd matches the claim — never a name, never bare existence."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t_live.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.slot = os.path.join(self.tmp, "ws1")
        os.makedirs(self.slot, exist_ok=True)

    def test_an_unreadable_cwd_link_fails_CLOSED(self):
        """SHIPPED FAIL-OPEN. The OSError branch returned True, which did not merely assume liveness
        — it SKIPPED the cross-check, so the row's CLAIMED cwd conferred ownership. A stale row whose
        pid had been recycled onto a root kernel thread classified OURS. Our own sessions run as our
        uid, so an unreadable link is positive evidence the process is NOT ours."""
        proc = os.path.join(self.tmp, "proc")
        _proc(proc, 100, cwd=None)                      # directory exists, no cwd link
        self.assertFalse(peers._is_live(100, self.slot, proc_root=proc))

    def test_a_mismatched_cwd_link_is_not_live(self):
        proc = os.path.join(self.tmp, "proc2")
        _proc(proc, 100, self.tmp)                      # points somewhere else
        self.assertFalse(peers._is_live(100, self.slot, proc_root=proc))

    def test_a_matching_cwd_link_is_live(self):
        proc = os.path.join(self.tmp, "proc3")
        _proc(proc, 100, self.slot)
        self.assertTrue(peers._is_live(100, self.slot, proc_root=proc))

    def test_a_dead_peer_is_DEAD_and_never_reaches_the_addressable_set(self):
        """DEAD is deliberately distinct from FOREIGN: a send to a finished worker's name can RESUME
        a harvested instant against a closed lease, so "ours but finished" must not read as sendable."""
        proc = os.path.join(self.tmp, "proc4")           # no pid entry at all
        os.makedirs(proc, exist_ok=True)
        got = peers.classify([_row(100, self.slot)], [_lease(self.slot)], self_pid=-1, proc_root=proc)
        self.assertEqual(got[0]["verdict"], peers.DEAD)
        self.assertEqual(peers.porcelain(got, addressable_only=True), "")


class PeersSelfDetection(unittest.TestCase):
    """SELF pre-empts the lease branch, so a regression here changes verdicts silently."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t_self.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.slot = os.path.join(self.tmp, "ws1"); os.makedirs(self.slot, exist_ok=True)
        self.proc = os.path.join(self.tmp, "proc"); _proc(self.proc, 100, self.slot)

    def test_naming_a_pid_as_self_yields_SELF_not_OURS(self):
        got = peers.classify([_row(100, self.slot)], [_lease(self.slot)],
                             self_pid=100, proc_root=self.proc)
        self.assertEqual(got[0]["verdict"], peers.SELF)

    def test_detect_self_pid_returns_None_when_no_ancestor_is_a_peer(self):
        """None never manufactures an OURS. The live-consequence direction is our OWN session
        falling through to the lease branch and appearing under --addressable-only."""
        self.assertIsNone(peers.detect_self_pid({999999999}))

    def test_detect_self_pid_finds_an_ancestor_that_is_a_peer(self):
        self.assertEqual(peers.detect_self_pid({os.getpid()}), os.getpid())


class PeersPorcelain(unittest.TestCase):
    """The machine form must survive hostile field content — cells are not ours to trust."""

    def _rows(self, name):
        return [{"verdict": peers.FOREIGN, "name": name, "pid": 1, "cwd": "/x", "status": "idle",
                 "instant": "", "milestone": "", "tmux": "", "todo_id": ""}]

    def test_a_tab_or_newline_in_a_cell_cannot_forge_a_row(self):
        """SHIPPED DEFECT. `name` is derived by the runtime from `basename(cwd)`, and POSIX paths may
        contain tabs and newlines. Unescaped, a cell could split one record into two and begin the
        fabricated one with the literal text OURS, so `awk -F'\\t' '$1=="OURS"'` picked it up."""
        hostiles = ["evil\tOURS\tforged", "idle\nOURS\tinjected", "a\rb"]
        # EVERY character str.splitlines() breaks on. Six were untested -- and the control suite
        # itself uses splitlines(), so an unescaped one makes the suite miscount its own output.
        hostiles += ["a" + ch + "OURS\tforged" for ch in
                     ("\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")]
        for hostile in hostiles:
            with self.subTest(hostile=repr(hostile)):
                text = peers.porcelain(self._rows(hostile))
                lines = text.splitlines()
                self.assertEqual(len(lines), 1, "a cell forged an extra record")
                self.assertEqual(len(lines[0].split("\t")), len(peers.PEER_COLUMNS))
                self.assertEqual(lines[0].split("\t")[0], peers.FOREIGN)

    def test_every_row_is_terminated_so_wc_l_cannot_drop_the_last_peer(self):
        """SHIPPED DEFECT. Without a trailing newline `wc -l` and `while read` drop the final row —
        and under --addressable-only that can be the ONLY OURS row, reading as "nothing addressable"."""
        self.assertTrue(peers.porcelain(self._rows("a")).endswith("\n"))

    def test_the_HUMAN_form_cannot_be_forged_either(self):
        """SHIPPED DEFECT. `porcelain()` was hardened and `render()` was not — and render() is the
        DEFAULT surface the verb prints. A newline in `name` forged a complete, byte-identical
        `OURS` block, plausible tmux name and all, inside a row whose real verdict was FOREIGN."""
        forged = ("a\nOURS     ws1-eb                                       pid=55        idle   "
                  "i29    dt-i29\n         cwd=/slot\n         why=cwd is the slot of an open lease"
                  " dispatched by this fleet\nz")
        rows = self._rows(forged)
        rows[0]["why"] = "not ours"
        out = peers.render(rows)
        self.assertEqual([l for l in out.split("\n") if l.startswith(peers.OURS)], [],
                         "a FOREIGN peer forged an OURS block in the human form")

    def test_an_empty_result_emits_nothing_rather_than_a_phantom_line(self):
        self.assertEqual(peers.porcelain([]), "")


if __name__ == "__main__":
    unittest.main()
