"""The one join, under a synthetic fleet that IS the specification.

Every case below names the finding it encodes, because the case list is the hard part here and a weaker
assertion than the case intends is how each of these was shipped the first time. Three independent bugs
in the predecessor had one shape — *a report that instructs action on a stale premise* — because three
views each computed state from a different subset of the facts, and **the one that was wrong was the one
everybody read**.

The whole fleet is built through the injected probes (`Probes`, `cwd_probe`, `alive`): `NFR2-3` exists so
a suite can describe a fleet without owning one. Nothing here starts a process, a tmux or a repository.
"""
import calendar
import io
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock
from dataclasses import fields as dataclass_fields
from types import SimpleNamespace

from fleet.guards import CAP_EXCLUDED_STATES, _counts_against_cap
from fleet.cli import Ctx, _do_board
from fleet.pool import Pool
from fleet.reconcile import (AWAITING_CI, BLOCKED, COMPLETE, DEAD, IDLE, KINDS, PARKED, RUNNING, STALE_WAIT_S, STATES,
                             UNKNOWN_SESSION, UNREACHABLE, Subject, _awaiting_note, _unknown_subject,
                             needs_a_human, reconcile)
from fleet.session import LiveSession, Probes, SessionLayer, default_probes
from fleet.store import Declarations, Record, Store
from tests.test_runtime_discovery import probe_unreadable

#: Every enrolled slot. `ws9` is enrolled and NOT leased — the harvested subject's slot, which is what
#: makes `holds_slot is False` a fact about the lease rather than about enrolment.
SLOTS = ("ws1", "ws2", "ws3", "ws4", "ws5", "ws6", "ws7", "ws8", "ws9")


class TestReadCensusBudget(unittest.TestCase):
    """Historical records must not repeatedly sample processes or tmux."""

    def test_thousand_harvested_records_share_one_census(self):
        calls = {"processes": 0, "has_session": 0, "names": 0}

        def processes():
            calls["processes"] += 1
            return []

        def has_session(name):
            calls["has_session"] += 1
            return False

        def names():
            calls["names"] += 1
            return set()

        probes = Probes(list_processes=processes, capture_pane=lambda name: "",
                        has_session=has_session, start_session=lambda *a: None,
                        kill_session=lambda *a: None)
        probes.list_session_names = names
        records = [_record(todo_id=f"old-{i}", tmux=f"dt-old-{i}",
                           harvested_at="2026-09-01T00:00:00Z")
                   for i in range(1000)]
        store = SimpleNamespace(all=lambda: records)
        pool = SimpleNamespace(slots=lambda: [], lease=lambda slot: None)
        seen = []

        def subjects():
            batch = reconcile(store, pool, SessionLayer(probes), pathlib.Path("/missing"))
            seen.extend(batch)
            return batch

        output = io.StringIO()
        ctx = SimpleNamespace(subjects=subjects, porcelain=True,
                              home=pathlib.Path("/private/store"), out=output)
        start = time.perf_counter()
        _do_board(ctx, None)
        elapsed = time.perf_counter() - start
        self.assertIn("examined 1000 subject(s)", output.getvalue())
        self.assertEqual(len(seen), 1000)
        self.assertTrue(all(s.state == "HARVESTED" for s in seen))
        self.assertLess(elapsed, 1.0)
        self.assertLessEqual(calls["processes"], 1)
        self.assertLessEqual(calls["has_session"], 1)
        self.assertLessEqual(calls["names"], 1)

    def test_real_probe_subprocesses_are_constant_at_thousand_records(self):
        records = [_record(todo_id=f"old-{i}", tmux=f"dt-old-{i}",
                           harvested_at="2026-09-01T00:00:00Z")
                   for i in range(1000)]
        store = SimpleNamespace(all=lambda: records)
        pool = SimpleNamespace(slots=lambda: [], lease=lambda slot: None)
        commands = []

        def run(argv, **kwargs):
            commands.append(argv)
            if argv[0] == "pgrep" or "has-session" in argv:
                return subprocess.CompletedProcess(argv, 1, "", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch("subprocess.run", side_effect=run):
            probes = default_probes(tmux_socket="it-census-test", both_runtimes=True)
            subjects = reconcile(store, pool, SessionLayer(probes), pathlib.Path("/missing"))
        self.assertEqual(len(subjects), 1000)
        self.assertTrue(all(s.state == "HARVESTED" for s in subjects))
        self.assertLessEqual(len(commands), 4)

    def test_bulk_list_failure_preserves_exact_session_fallback(self):
        record = _record(todo_id="tmux-only", tmux="dt-one")
        store = SimpleNamespace(all=lambda: [record])
        pool = SimpleNamespace(slots=lambda: [], lease=lambda slot: None)

        def run(argv, **kwargs):
            if argv[0] == "pgrep":
                return subprocess.CompletedProcess(argv, 1, "", "")
            if "list-sessions" in argv:
                return subprocess.CompletedProcess(argv, 1, "", "server exited unexpectedly")
            if "has-session" in argv:
                return subprocess.CompletedProcess(argv, 0, "", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch("subprocess.run", side_effect=run):
            probes = default_probes(tmux_socket="it-census-test", both_runtimes=True)
            subject, = reconcile(store, pool, SessionLayer(probes), pathlib.Path("/missing"))
        self.assertEqual(subject.state, RUNNING)

    def test_tmux_only_session_still_counts_as_live(self):
        probes = Probes(list_processes=lambda: [], capture_pane=lambda name: "quiet",
                        has_session=lambda name: False, start_session=lambda *a: None,
                        kill_session=lambda *a: None)
        probes.list_session_names = lambda: {"dt-here"}
        record = _record(todo_id="here", tmux="dt-here")
        store = SimpleNamespace(all=lambda: [record])
        pool = SimpleNamespace(slots=lambda: [], lease=lambda slot: None)
        subject, = reconcile(store, pool, SessionLayer(probes), pathlib.Path("/missing"))
        self.assertEqual(subject.state, RUNNING)
        self.assertEqual(subject.evidence["liveness"], "session")

    def test_the_one_liveness_method_accepts_a_read_snapshot(self):
        calls = {"processes": 0, "exact": 0}

        def processes():
            calls["processes"] += 1
            return []

        def exact(name):
            calls["exact"] += 1
            return False

        probes = Probes(list_processes=processes, capture_pane=lambda name: "",
                        has_session=exact, start_session=lambda *a: None,
                        kill_session=lambda *a: None)
        layer = SessionLayer(probes)
        self.assertTrue(layer.alive("dt-one", process_names=set(), session_names={"dt-one"}))
        self.assertEqual(calls, {"processes": 0, "exact": 0})

    def test_cadence_and_read_only_board_share_one_process_census(self):
        calls = {"processes": 0}

        def processes():
            calls["processes"] += 1
            return []

        probes = Probes(list_processes=processes, capture_pane=lambda name: "",
                        has_session=lambda name: False, start_session=lambda *a: None,
                        kill_session=lambda *a: None)
        probes.list_session_names = lambda: set()
        store = SimpleNamespace(all=lambda: [_record(todo_id="old", tmux="dt-old",
                                                     harvested_at="2026-09-01T00:00:00Z")])
        pool = SimpleNamespace(slots=lambda: [], lease=lambda slot: None)
        ctx = Ctx(home=pathlib.Path("/private/store"), instants_dir=pathlib.Path("/missing"),
                  store=store, pool=pool, sessions=SessionLayer(probes), harvest=None,
                  out=io.StringIO(), err=io.StringIO())
        ctx.share_read_census = True
        ctx.live_work_now()  # main's cadence check runs before the board handler
        self.assertEqual(len(ctx.subjects()), 1)
        self.assertEqual(calls["processes"], 1)

    def test_thousand_renamed_instants_resolve_within_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            records = []
            for i in range(1000):
                stem = f"00000000-{i:08d}"
                (root / f"{stem}-complete-append-job").mkdir()
                records.append(_record(todo_id=f"old-{i}", tmux=f"dt-old-{i}",
                                       child_instant=str(root / f"{stem}-inflight-append-job"),
                                       harvested_at="2026-09-01T00:00:00Z"))
            probes = Probes(list_processes=lambda: [], capture_pane=lambda name: "",
                            has_session=lambda name: False, start_session=lambda *a: None,
                            kill_session=lambda *a: None)
            probes.list_session_names = lambda: set()
            store = SimpleNamespace(all=lambda: records)
            pool = SimpleNamespace(slots=lambda: [], lease=lambda slot: None)
            start = time.perf_counter()
            subjects = reconcile(store, pool, SessionLayer(probes), root)
            elapsed = time.perf_counter() - start
            self.assertEqual(len(subjects), 1000)
            self.assertTrue(all(s.state == COMPLETE for s in subjects))
            self.assertLess(elapsed, 1.0)

    def test_foreign_servers_are_sampled_once_each_and_do_not_share_names(self):
        calls = {"local": 0, "a": 0, "b": 0}

        def layer(socket, names):
            def processes():
                calls[socket] += 1
                return []
            probes = Probes(list_processes=processes, capture_pane=lambda name: "quiet",
                            has_session=lambda name: False, start_session=lambda *a: None,
                            kill_session=lambda *a: None, socket=socket)
            probes.list_session_names = lambda: names
            return SessionLayer(probes)

        #: V23-V OR-3. Each record names its OWN session: v23-t gives a (server, name) one owner, so 20 records on one
        #: name would read as one live worker. The same 20 names on both servers keep the no-sharing check.
        local = layer("local", set())
        foreign = {"a": layer("a", {f"dt-w{i}" for i in range(20)}), "b": layer("b", set())}
        records = [_record(todo_id=f"a-{i}", tmux=f"dt-w{i}", tmux_socket="a")
                   for i in range(20)]
        records += [_record(todo_id=f"b-{i}", tmux=f"dt-w{i}", tmux_socket="b")
                    for i in range(20)]
        store = SimpleNamespace(all=lambda: records)
        pool = SimpleNamespace(slots=lambda: [], lease=lambda slot: None)
        subjects = reconcile(store, pool, local, pathlib.Path("/missing"),
                             layer_for=lambda socket: foreign[socket])
        states = {s.identity: s.state for s in subjects}
        self.assertTrue(all(states[f"a-{i}"] == RUNNING for i in range(20)))
        self.assertTrue(all(states[f"b-{i}"] == DEAD for i in range(20)))
        self.assertEqual(calls, {"local": 1, "a": 1, "b": 1})

OURS = "/i/00000000-07300312-inflight-append-fleetInfraRebuild"
THEIRS = "/i/00000000-07290101-inflight-append-otherEffort"


class TestUnknownAddressEvidence(unittest.TestCase):
    def test_process_without_a_pane_does_not_inherit_the_queried_server_or_other_children(self):
        outer = LiveSession(1, pathlib.Path('/slot/ws1'), None, runtime='codex')
        unrelated = LiveSession(2, pathlib.Path('/elsewhere'), None, runtime='claude', nested=True)
        subject = _unknown_subject(outer, 'ws1', [outer, unrelated], 'private-socket')
        self.assertEqual(subject.evidence['tmux_socket'], '')
        self.assertEqual(subject.evidence['nested'], '')

#: A pane that is neither working nor waiting for a keystroke.
QUIET_PANE = "\n".join(["compiled 42 files", "wrote target/fleet.jar", "done"])
#: A pane still offering a way to interrupt: the single-observation definition of "progressing".
BUSY_PANE = "\n".join(["reading src/fleet/pool.py", "Thinking...", "  esc to interrupt"])
#: A modal. The caret line holds text nobody submitted, so a human keystroke is the only way forward.
MODAL_PANE = "\n".join(["Edit file src/fleet/pool.py?",
                        "❯ 1. Yes",
                        "  2. No, tell Claude what to do differently"])

#: A quiet pane whose STATUS LINE shows an armed watcher, the shape `declare --phase awaiting-ci` accepts.
#: Not busy (no interrupt hint), so the watcher is the only thing that will wake the session.
WATCHED_PANE = "\n".join(["gh run watch 1234 --exit-status", "",
                          "  auto mode on · 1 monitor · ? for shortcuts"])

#: A codex pane that `runtime.observe` reads as `idle` — a bold caret above the model/path footer. A codex
#: pane that reads `unknown` returns BLOCKED from `_state_of` before `_live_state` is ever reached, so only
#: this shape exercises the codex branch inside `_live_state`.
CODEX_IDLE_PANE = "reading src/fleet/pool.py\n\x1b[0;1m\u203a \x1b[0m\ncodex gpt-5 \u00b7 /home/ubuntu/work"

#: `B24`. A human mid-sentence: text in the input box, nothing submitted, and the turn is over (no interrupt
#: hint) — byte-identical to a swallowed submit, which is the whole problem.
TYPING_PANE = "\n".join(["wrote target/fleet.jar", "done", "", "\u276f\u00a0also re-run the rebase check before you"])

PARK_BUSY_Q = "should the shim land before the rebase, or after?"
PARK_BLOCKED_Q = "is merging #441 mine to do?"


def _past_the_grace() -> str:
    """A claim stamp one hour old: past `reconcile.WATCHER_GRACE_S` (`V23-G`), so a case about a claim nothing
    backs measures the claim itself rather than the minutes after it, when a Monitor may still be arming."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))


def _record(**kw) -> Record:
    base = dict(todo_id="", child_instant="", base_instant=OURS, slot="", tmux="",
                profile="/p/worker", golden="/ws0", lineage_base="", title="a title",
                dispatched_at="2026-07-30T03:12:00Z", launched_at="2026-07-30T03:13:00Z")
    base.update(kw)
    return Record(**base)


def snapshot(root: pathlib.Path) -> dict:
    """Every path under `root` with its mtime and size. The purity assertion compares this before and
    after, because the predecessor's `health` back-filled `launched_at` *during a read* — which made a
    report a writer, and a writer that runs on every glance is a writer nobody audits."""
    out = {}
    for path in sorted(root.rglob("*")):
        stat = path.stat()
        out[str(path)] = (path.is_dir(), stat.st_mtime_ns, stat.st_size if path.is_file() else 0)
    return out


class SyntheticFleet:
    """The fleet the plan requires, built through probes only.

    Contains, at minimum and by name: a dead-but-recorded session · a **live-but-unrecorded** session ·
    a renamed instant · a stale lease owned by another base · an `abort-compact` instant.
    """

    def __init__(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.home = self.tmp / "fleethome"
        self.instants = self.tmp / "instants"
        self.instants.mkdir()
        self.slots_dir = self.tmp / "slots"
        self.slots_dir.mkdir()

        self.procs = []
        self.panes = {}
        self.tmux_live = set()
        self.holders = {}

        probes = Probes(list_processes=lambda: list(self.procs),
                        capture_pane=lambda name: self.panes.get(name, ""),
                        has_session=lambda name: name in self.tmux_live,
                        start_session=lambda name, cwd, cmd: None,
                        kill_session=lambda name: None)
        #: `B24`. Session name -> `(clients, last_input_epoch)` as tmux reports it; absent means
        #: NOT MEASURED. Assigned rather than passed, so the fixture also builds on a package that predates
        #: the field — which is what lets the new cases run RED against the base for a behavioural reason
        #: instead of a TypeError.
        self.attached = {}
        probes.attachment = lambda name: self.attached.get(name)
        self.sessions = SessionLayer(probes)
        self.store = Store(self.home)
        self.pool = Pool(self.home,
                         cwd_probe=lambda path: list(self.holders.get(str(path), [])),
                         alive=self.sessions.alive)
        for slot in SLOTS:
            (self.slots_dir / slot).mkdir()
            self.pool.enroll(self.slots_dir / slot)

        self.paths = {}
        self._build()

    # ---- fixture construction ------------------------------------------------------------

    def instant(self, folder: str, handoff: str = "Updated: now\nStatus: working\n") -> pathlib.Path:
        path = self.instants / folder
        path.mkdir()
        (path / "HANDOFF.md").write_text(handoff)
        return path

    def dispatch(self, todo_id, folder, slot, tmux, *, recorded_folder=None, lease=True,
                 handoff="Updated: now\nStatus: working\n", **kw) -> pathlib.Path:
        path = self.instant(folder, handoff=handoff)
        recorded = self.instants / (recorded_folder or folder)
        self.store.write(_record(todo_id=todo_id, child_instant=str(recorded), slot=slot,
                                 tmux=tmux, **kw))
        if lease:
            self.pool.claim(todo_id=todo_id, tmux=tmux, base_instant=OURS,
                            child_instant=str(recorded), slot=slot)
        self.paths[todo_id] = path
        return path

    def launch(self, tmux, pid, slot, pane):
        self.procs.append(LiveSession(pid=pid, cwd=self.slots_dir / slot, name=tmux))
        self.panes[tmux] = pane
        self.tmux_live.add(tmux)

    def age(self, todo_id, seconds):
        """Make an instant look untouched for `seconds`. `_idle_for` reads the instant directory, its
        direct children and `.fleet/*` — so all three are aged, and aged LAST, because writing a
        declaration refreshes the mtime of the file it writes."""
        instant = self.paths[todo_id]
        old = time.time() - seconds
        paths = [instant]
        for child in instant.iterdir():
            paths.append(child)
            if child.name == ".fleet" and child.is_dir():
                paths.extend(child.iterdir())
        for path in paths:
            os.utime(path, (old, old))

    def _build(self):
        # 1. Dead but recorded: a record, a lease, an `-inflight-` folder, and no process anywhere.
        # `board` rendered this PARKED and counted it in "N sessions need you" while `health` said DEAD
        # from the same records (W2-14 / OBS-57).
        self.dispatch("deadWorker-07300301", "00000000-07300301-inflight-append-deadWorker",
                      "ws1", "dt-deadWorker")

        # 2. Live but unrecorded, cwd outside every slot. OBS-48: a SCREEN session sat idle 8d20h,
        # invisible to every records-first sweep.
        outside = self.tmp / "outside" / "someonesShell"
        outside.mkdir(parents=True)
        self.procs.append(LiveSession(pid=4242, cwd=outside, name="screen-1"))

        # 3. Renamed instant: the record still says `-inflight-`, the disk says `-complete-`.
        self.dispatch("renamedWork-07300302", "00000000-07300302-complete-append-renamedWork",
                      "ws2", "dt-renamedWork",
                      recorded_folder="00000000-07300302-inflight-append-renamedWork")

        # 4. A stale lease owned by ANOTHER base, with no record in this store and no live process.
        # RI-31: the ownership guard refused correctly and read as a bug because it never said whose
        # lease it was.
        self.pool.claim(todo_id="theirWork-07290101", tmux="dt-theirWork", base_instant=THEIRS,
                        child_instant=THEIRS + "/child", slot="ws3")

        # 5. An `-abort-compact-` instant: the state W2-21's fix never reached.
        self.dispatch("foldTheStack-07300303", "00000000-07300303-abort-compact-foldTheStack",
                      "", "dt-foldTheStack", lease=False,
                      recorded_folder="00000000-07300303-inflight-compact-foldTheStack")

        # 6. A declared CI waiter. Read from STRUCTURED state, never from prose.
        ci = self.dispatch("ciWaiter-07300304", "00000000-07300304-inflight-append-ciWaiter",
                           "ws4", "dt-ciWaiter")
        # B06: with a watcher on its status line. A claim nothing watches is disregarded (tested in
        # `TestNeedsAHumanUsesKnownFacts`), so the fixture that means "a real CI wait" shows its watcher.
        Declarations(ci).set_phase("awaiting-ci")
        self.launch("dt-ciWaiter", 101, "ws4", WATCHED_PANE)

        # 7. PROSE claiming the same phase, with no declaration. RCF-9, made unreachable.
        self.dispatch("proseClaimer-07300305", "00000000-07300305-inflight-append-proseClaimer",
                      "ws5", "dt-proseClaimer",
                      handoff="## Phase: AWAITING-CI\n\n`Phase: AWAITING-CI` is declared above.\n")
        self.launch("dt-proseClaimer", 102, "ws5", QUIET_PANE)

        # 8. Parked, and progressing anyway. OBS-3: "a parked note while still working is just a note";
        # a permanently-red tick trains everyone to ignore red.
        busy = self.dispatch("parkedBusy-07300306", "00000000-07300306-inflight-append-parkedBusy",
                             "ws6", "dt-parkedBusy")
        Declarations(busy).park(PARK_BUSY_Q)
        self.launch("dt-parkedBusy", 103, "ws6", BUSY_PANE)

        # 9. Parked, with a modal on screen. OBS-7: a masked actionable state "sends you to the wrong
        # problem, and the wrong problem is one you cannot fix".
        blocked = self.dispatch("parkedBlocked-07300307",
                                "00000000-07300307-inflight-append-parkedBlocked",
                                "ws7", "dt-parkedBlocked")
        Declarations(blocked).park(PARK_BLOCKED_Q)
        self.launch("dt-parkedBlocked", 104, "ws7", MODAL_PANE)

        # 10. Harvested: complete on disk, lease released, slot ws9 free. FD-4 — this is what keeps the
        # board small enough to be read.
        self.dispatch("harvestedWork-07300308", "00000000-07300308-complete-append-harvestedWork",
                      "ws9", "dt-harvestedWork", lease=False,
                      recorded_folder="00000000-07300308-inflight-append-harvestedWork",
                      harvested_at="2026-07-30T04:00:00Z")

        # 11. Dispatched, never launched: `launched_at` is absent. Present so that back-filling a
        # missing field during the join has something to back-fill (see test_reconcile_is_pure).
        self.dispatch("pendingWork-07300309", "00000000-07300309-inflight-append-pendingWork",
                      "ws8", "dt-pendingWork", launched_at=None)

    # ---- queries -------------------------------------------------------------------------

    def reconcile(self):
        return reconcile(self.store, self.pool, self.sessions, self.instants)

    def leased_slots(self):
        return {slot for slot in self.pool.slots() if self.pool.lease(slot) is not None}


class TestReconcile(unittest.TestCase):
    def setUp(self):
        self.fleet = SyntheticFleet()
        self.subjects = self.fleet.reconcile()

    def subject(self, identity) -> Subject:
        hits = [s for s in self.subjects if s.identity == identity]
        self.assertEqual(len(hits), 1, f"expected exactly one subject {identity!r}, got {hits}")
        return hits[0]

    def of_kind(self, kind) -> list:
        return [s for s in self.subjects if s.kind == kind]

    # ---- the thirteen cases --------------------------------------------------------------

    def test_a_dead_but_recorded_session_is_DEAD_not_PARKED(self):
        # W2-14 / OBS-57: `board` said PARKED and counted it as needing a human; `health` said DEAD from
        # the same records. One join, one answer, and liveness is part of it.
        s = self.subject("deadWorker-07300301")
        self.assertEqual(s.state, "DEAD")
        self.assertTrue(s.holds_slot, "a dead worker still holds its slot until something releases it")

    def test_folderless_harvested_and_closed_records_do_not_count(self):
        for todo, stamp in (("harvestedGone-07300310", "harvested_at"),
                            ("closedGone-07300311", "closed_at")):
            rec = _record(todo_id=todo, child_instant=str(self.fleet.instants / f"missing-{todo}"),
                          slot="ws9", tmux=f"dt-{todo}",
                          launched_at=None if stamp == "closed_at" else "2026-07-30T03:13:00Z",
                          **{stamp: "2026-07-30T04:00:00Z"})
            self.fleet.store.write(rec)
        subjects = {s.identity: s for s in self.fleet.reconcile()}
        for todo, state in (("harvestedGone-07300310", "HARVESTED"),
                            ("closedGone-07300311", "CLOSED")):
            with self.subTest(todo=todo):
                subject = subjects[todo]
                self.assertEqual(subject.state, state)
                self.assertFalse(_counts_against_cap(subject))
                self.assertIn(todo, subjects, "the historical record must remain auditable")
        self.assertEqual(subjects["deadWorker-07300301"].state, DEAD)
        self.assertTrue(_counts_against_cap(subjects["deadWorker-07300301"]))

    def test_folderless_harvested_record_naming_another_server_does_not_count(self):
        """FB-121. A harvested record that names a different tmux server (e.g. the old `fleet`) is terminal: harvest
        released the lease and killed the session before it stamped. It must read HARVESTED, not UNREACHABLE. The
        unstamped control on the same server still reads UNREACHABLE and counts."""
        for todo, harvested in (("harvestedElsewhere-07300312", "2026-07-30T04:00:00Z"),
                                ("unstampedElsewhere-07300313", None)):
            self.fleet.store.write(_record(todo_id=todo, child_instant=str(self.fleet.instants / f"missing-{todo}"),
                                           slot="ws9", tmux=f"dt-{todo}", launched_at="2026-07-30T03:13:00Z",
                                           tmux_socket="fleet-not-this-one", harvested_at=harvested))
        subjects = {s.identity: s for s in self.fleet.reconcile()}
        self.assertEqual(subjects["harvestedElsewhere-07300312"].state, "HARVESTED")
        self.assertFalse(_counts_against_cap(subjects["harvestedElsewhere-07300312"]))
        self.assertEqual(subjects["unstampedElsewhere-07300313"].state, UNREACHABLE)
        self.assertTrue(_counts_against_cap(subjects["unstampedElsewhere-07300313"]))

    def test_terminal_stamp_does_not_hide_a_live_busy_session(self):
        self.fleet.launch("dt-deadWorker", 404, "ws1", BUSY_PANE)
        for stamp in ("closed_at", "harvested_at"):
            with self.subTest(stamp=stamp):
                rec = self.fleet.store.read("deadWorker-07300301")
                rec.closed_at = rec.harvested_at = None
                setattr(rec, stamp, "2026-07-30T04:00:00Z")
                self.fleet.store.write(rec)
                subject = next(s for s in self.fleet.reconcile() if s.identity == rec.todo_id)
                self.assertEqual(subject.state, RUNNING)
                self.assertTrue(_counts_against_cap(subject))
                self.assertTrue(subject.holds_slot)

    def test_terminal_stamp_does_not_hide_a_live_slot_holder_without_session(self):
        self.fleet.procs.append(LiveSession(pid=405, cwd=self.fleet.slots_dir / "ws1", name=None))
        for stamp in ("closed_at", "harvested_at"):
            with self.subTest(stamp=stamp):
                rec = self.fleet.store.read("deadWorker-07300301")
                rec.closed_at = rec.harvested_at = None
                setattr(rec, stamp, "2026-07-30T04:00:00Z")
                self.fleet.store.write(rec)
                subject = next(s for s in self.fleet.reconcile() if s.identity == rec.todo_id)
                self.assertEqual(subject.state, UNREACHABLE)
                self.assertIn("405", subject.note)
                self.assertTrue(_counts_against_cap(subject))

    def test_closed_record_with_inflight_folder_still_counts(self):
        rec = self.fleet.store.read("deadWorker-07300301")
        rec.closed_at = "2026-07-30T04:00:00Z"
        self.fleet.store.write(rec)
        subject = next(s for s in self.fleet.reconcile() if s.identity == rec.todo_id)
        self.assertEqual(subject.evidence["folder_state"], "inflight")
        self.assertTrue(subject.holds_slot)
        self.assertEqual(subject.state, DEAD)
        self.assertTrue(_counts_against_cap(subject))

    def test_a_live_process_with_no_record_is_reported_as_an_unknown(self):
        # OBS-48. A records-first join is structurally blind to this session; process-first is the only
        # direction that can see it.
        unknowns = self.of_kind("unknown-session")
        self.assertEqual(len(unknowns), 1, [s.identity for s in unknowns])
        self.assertEqual(unknowns[0].state, "UNKNOWN-SESSION")
        self.assertIn("4242", " ".join(unknowns[0].evidence.values()))

    def test_an_unknown_session_is_never_marked_reapable(self):
        # "Some of those sessions are people's" (D-6). A tool that can kill a session it does not
        # understand is a tool nobody leaves armed.
        unknown = self.of_kind("unknown-session")[0]
        names = {f.name for f in dataclass_fields(Subject)}
        self.assertEqual(names & {"reapable", "killable", "reap", "kill", "safe_to_kill",
                                  "disposable", "stale"}, set())
        blob = " ".join([unknown.note, unknown.state, unknown.kind]
                        + list(unknown.evidence.keys()) + list(unknown.evidence.values())).lower()
        for authorising in ("reap", "kill", "terminate", "safe to remove", "may be removed"):
            self.assertNotIn(authorising, blob, f"the report authorises {authorising!r}")

    def test_a_renamed_instant_is_followed(self):
        s = self.subject("renamedWork-07300302")
        self.assertEqual(s.state, "COMPLETE")
        self.assertIn("00000000-07300302-complete-append-renamedWork",
                      " ".join(s.evidence.values()))

    def test_a_stale_lease_owned_by_another_base_is_a_subject_naming_its_owner(self):
        # RI-31: "not yours to clear" is a state, not a failure — but only if the report says whose.
        stale = self.of_kind("stale-lease")
        self.assertEqual(len(stale), 1, [s.identity for s in stale])
        self.assertEqual(stale[0].state, "STALE-LEASE")
        self.assertTrue(stale[0].holds_slot)
        self.assertIn(THEIRS, stale[0].note)

    def test_an_abort_compact_instant_reconciles_without_error(self):
        # The state W2-21's fix never reached. setUp already ran the join; this asserts the subject is
        # present and that the abort folder is what the join actually read.
        s = self.subject("foldTheStack-07300303")
        self.assertIn(s.state, STATES)
        self.assertIn("abort", " ".join(s.evidence.values()) + " " + s.note)

    def test_a_declared_awaiting_ci_worker_is_AWAITING_CI(self):
        self.assertEqual(Declarations(self.fleet.paths["ciWaiter-07300304"]).phase(), "awaiting-ci")
        s = self.subject("ciWaiter-07300304")
        self.assertEqual(s.state, "AWAITING-CI")
        #: `_awaiting_note` re-observes the pane's own status line rather than trusting the declaration
        #: alone; asserting on `.state` only lets that branch be unwired and the suite stay green (I8).
        self.assertIn("declared awaiting-ci", s.note)
        self.assertIn("watcher observed (1 monitor)", s.note)

    def test_prose_claiming_a_phase_does_not_change_the_state(self):
        # RCF-9 made unreachable: the prose is right there, and it is not a control signal.
        handoff = (self.fleet.paths["proseClaimer-07300305"] / "HANDOFF.md").read_text()
        self.assertIn("Phase: AWAITING-CI", handoff)
        self.assertIsNone(Declarations(self.fleet.paths["proseClaimer-07300305"]).phase())
        self.assertEqual(self.subject("proseClaimer-07300305").state, "RUNNING")

    def test_a_parked_worker_that_is_progressing_stays_PARKED_with_working_flag(self):
        s = self.subject("parkedBusy-07300306")
        self.assertEqual(s.state, PARKED)
        self.assertEqual(s.evidence["working"], "true")
        self.assertTrue(s.note.strip(), "the park must survive as a note")
        self.assertIn(PARK_BUSY_Q, s.note)

    def test_parked_note_does_not_flap_when_pane_turns_idle(self):
        busy = self.subject("parkedBusy-07300306")
        self.fleet.panes["dt-parkedBusy"] = QUIET_PANE
        idle = next(s for s in self.fleet.reconcile() if s.identity == busy.identity)
        self.assertEqual((busy.state, idle.state), (PARKED, PARKED))
        self.assertEqual((busy.evidence["working"], idle.evidence["working"]), ("true", "false"))
        self.assertEqual(busy.note, idle.note)

    def test_an_actionable_state_is_never_masked_by_a_standing_note(self):
        s = self.subject("parkedBlocked-07300307")
        self.assertEqual(s.state, "BLOCKED")
        self.assertIn(PARK_BLOCKED_Q, s.note)

    def test_only_slot_holding_subjects_report_holds_slot(self):
        # FD-4. The board renders `holds_slot` subjects only, so a False here is what keeps it small.
        self.assertFalse(self.subject("harvestedWork-07300308").holds_slot)
        self.assertTrue(any(s.holds_slot for s in self.subjects), "not a vacuous assertion")
        leased = self.fleet.leased_slots()
        for s in self.subjects:
            if s.holds_slot:
                self.assertIn(s.evidence.get("slot", ""), leased,
                              f"{s.identity} claims a slot the pool does not lease to it")
            else:
                self.assertNotIn(s.evidence.get("slot", ""), leased,
                                 f"{s.identity} holds {s.evidence.get('slot')!r} and does not say so")

    def test_reconcile_is_pure(self):
        # The fleet is built FRESH here and snapshotted before the FIRST join, not this class's. A
        # back-fill fires once and is then invisible: snapshotting after a join has already run makes
        # the very defect this test exists for undetectable, which is how it shipped the first time.
        fleet = SyntheticFleet()
        before = snapshot(fleet.tmp)
        first = fleet.reconcile()
        second = fleet.reconcile()
        self.assertEqual(first, second)
        after = snapshot(fleet.tmp)
        self.assertEqual(sorted(after), sorted(before), "the join created or removed a path")
        self.assertEqual(after, before, "the join changed a file: a report became a writer")

    def test_every_subject_carries_machine_identity(self):
        # OBS-62: the shipped assertion anchored to a summary line and could never match. Identity is
        # machine-readable, present on every subject, and unique — a key, not a label.
        self.assertTrue(self.subjects)
        for s in self.subjects:
            self.assertTrue(s.identity and s.identity.strip(), f"{s} has no machine identity")
            self.assertIn(s.kind, KINDS)
            self.assertIn(s.state, STATES)
        ids = [s.identity for s in self.subjects]
        self.assertEqual(len(set(ids)), len(ids), f"identity is not unique: {ids}")


if __name__ == "__main__":
    unittest.main()


class TestUnreachableIsNotDead(unittest.TestCase):
    """`SI-39`. A record whose SLOT is held by a live process is not dead, whatever tmux says.

    Measured on live work: with `FLEET_TMUX_SOCKET` unset, `board` called both instants of a running
    effort DEAD -- "the work stopped without renaming its folder" -- while both processes were an hour
    into their tasks. DEAD is actionable (the response is `reap`), so a wrong DEAD invites a human to free
    a slot out from under running work.
    """

    def _worker(self, proc_cwd):
        """One recorded worker whose tmux name NOTHING answers for, plus an optional live process.

        `tmux_live` is left empty on purpose: that is what being pointed at the wrong tmux server looks
        like from inside the join -- the session is simply not there.
        """
        fleet = SyntheticFleet()
        # ws9 is the fixture's unleased slot. ws3 is pre-claimed by another effort, so a record naming it
        # does not HOLD it -- and since SI-41 gates the holder probe on holding, using ws3 here would make
        # this case vacuous. The first version of this test did exactly that and passed anyway.
        slot = fleet.slots_dir / "ws9"
        slot.mkdir(exist_ok=True)
        # `slot` is the NAME, as every real record stores it -- checked against the live store, because the
        # first version of this test stored a PATH here and so agreed with a bug instead of the product.
        rec = _record(todo_id="t1", child_instant="00000000-07310348-inflight-append-w",
                      slot="ws9", tmux="dt-w")
        fleet.store.write(rec)
        fleet.pool.claim(todo_id=rec.todo_id, tmux=rec.tmux, base_instant=rec.base_instant,
                         child_instant=rec.child_instant, slot="ws9")
        if proc_cwd is not None:
            fleet.procs.append(LiveSession(pid=99, cwd=proc_cwd(fleet), name=None))
        subs = reconcile(fleet.store, fleet.pool, fleet.sessions, fleet.instants)
        return [s for s in subs if s.identity == "t1"][0]

    def test_a_slot_held_by_a_live_process_is_UNREACHABLE_not_DEAD(self):
        worker = self._worker(lambda f: f.slots_dir / "ws9")
        self.assertEqual(worker.state, UNREACHABLE,
                         "tmux could not name the session, but a live process holds the slot")
        self.assertIn("99", worker.note)
        self.assertIn("FLEET_TMUX_SOCKET", worker.note,
                      "the note must name the remedy; the usual cause is the wrong tmux server")

    def test_the_holder_pid_is_reported_as_evidence(self):
        worker = self._worker(lambda f: f.slots_dir / "ws9")
        self.assertEqual(worker.evidence.get("pid"), "99",
                         "a state derived from a pid must show the pid, or nobody can check it")

    def test_nothing_holding_the_slot_is_still_DEAD(self):
        worker = self._worker(None)
        self.assertEqual(worker.state, DEAD,
                         "the fix must not make a genuinely dead record un-diagnosable")

    def test_a_process_in_a_DIFFERENT_directory_does_not_rescue_the_record(self):
        # ws3, i.e. NOT this record's slot (which is ws9). The point of the case is that only a process in
        # THIS record's slot is evidence about THIS record.
        worker = self._worker(lambda f: f.slots_dir / "ws3")
        self.assertEqual(worker.state, DEAD,
                         "only a process in THIS record's slot is evidence about THIS record")


class TestATerminatedRecordDoesNotInheritTheLiveHolder(unittest.TestCase):
    """`SI-41`. A record that no longer holds its slot must not report the new holder's pid.

    `rec.slot` is a NAME, and a terminated record keeps naming the slot it used. When that slot is
    re-leased -- routine, since re-dispatching after an abort reuses both the slot and the title -- the dead
    record and the live one both say `ws3`.

    Observed on the live effort, and it was not cosmetic: `scripts/fleet-finished-pids.sh` maps
    `COMPLETE -> exclude from auto-resume` BY PID, so an aborted coordinator carrying the live
    coordinator's pid switched auto-resume off for a session that was still working -- silently, because
    the watchdog only ever sees a list of pids.
    """

    def test_the_dead_record_reports_no_pid_and_the_live_one_does(self):
        fleet = SyntheticFleet()
        # ws9 is the fixture's deliberately-UNLEASED slot. ws3 is pre-claimed by another effort, which is
        # what this fixture exists to model -- using it here would have made `_holds_slot` false for the
        # live record too, and the test would have "passed" for the wrong reason.
        slot = fleet.slots_dir / "ws9"
        slot.mkdir(exist_ok=True)

        dead_dir = fleet.instants / "00000000-07310334-abort-append-coord"
        (dead_dir / ".fleet").mkdir(parents=True)
        live_dir = fleet.instants / "00000000-07310348-inflight-append-coord"
        (live_dir / ".fleet").mkdir(parents=True)

        # Both name ws9 and both name the same tmux session -- exactly what re-dispatching produces.
        dead = _record(todo_id="coord-334", child_instant=str(dead_dir), slot="ws9", tmux="dt-coord")
        live = _record(todo_id="coord-348", child_instant=str(live_dir), slot="ws9", tmux="dt-coord")
        fleet.store.write(dead)
        fleet.store.write(live)
        fleet.pool.claim(todo_id=live.todo_id, tmux=live.tmux, base_instant=live.base_instant,
                         child_instant=live.child_instant, slot="ws9")   # only the LIVE one holds it
        fleet.procs.append(LiveSession(pid=4242, cwd=slot, name=None))        # a live process in ws9

        subs = {s.identity: s for s in reconcile(fleet.store, fleet.pool, fleet.sessions, fleet.instants)}
        self.assertEqual(subs["coord-348"].evidence.get("pid"), "4242",
                         "the record that HOLDS the slot may report the holder")
        self.assertEqual(subs["coord-334"].evidence.get("pid"), "",
                         "a record that no longer holds the slot must NOT inherit the new holder's pid — "
                         "that pid is fed to the watchdog's exclude list")
        self.assertEqual(subs["coord-334"].state, COMPLETE,
                         "the aborted folder still decides its state; only the pid was wrong")


class _FakeWatcherSessions:
    """A minimal `sessions` stand-in for `_awaiting_note`. `watchers(pane_text)` returns whatever the
    test says is armed, keyed on the literal pane text handed in — the actual status-line parsing is
    `session.Sessions.watchers`'s job and is exercised in `test_session.py`, not here."""

    def __init__(self, by_pane: dict):
        self._by_pane = by_pane

    def watchers(self, pane_text: str) -> str:
        return self._by_pane.get(pane_text, "")


class TestAwaitingCiNote(unittest.TestCase):
    """`_awaiting_note` directly. `i45` owned this gap, which `working-as-a-dispatched-instant` used to name:
    `reconcile` rendered every `awaiting-ci` row as the SAME constant note regardless of whether anything
    was actually observed on the pane. Measured: a Monitor that emitted zero events for 7.7h and a
    self-matching wait shell that outlived its job both rendered as a healthy wait, and the cost was
    three operator `status?` pings in one session.

    Exercised directly rather than through the whole `reconcile` join — `_awaiting_note` is where the
    four renderings and the staleness math live, and driving the full pipeline for these cases would
    test the join, not the note.
    """

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.instant = self.tmp / "instant"
        self.instant.mkdir()

    def _write_declaration(self, attested, declared_at):
        fleet_dir = self.instant / ".fleet"
        fleet_dir.mkdir(exist_ok=True)
        data = {"phase": "awaiting-ci"}
        if attested is not None:
            data["watchers"] = attested
        if declared_at is not None:
            data["at"] = declared_at
        (fleet_dir / "declare.json").write_text(json.dumps(data))

    def note(self, *, phase="awaiting-ci", pane="", attested=None, declared_at=None, now=None,
             stale_after_s=STALE_WAIT_S) -> str:
        self._write_declaration(attested, declared_at)
        observed = "1 monitor" if "monitor" in pane else ""
        sessions = _FakeWatcherSessions({pane: observed})
        now_epoch = (calendar.timegm(time.strptime(now, "%Y-%m-%dT%H:%M:%SZ"))
                    if now is not None else None)
        return _awaiting_note(pane, sessions, self.instant, stale_after_s=stale_after_s, now=now_epoch)

    def test_awaiting_ci_distinguishes_observed_attested_and_absent_watchers(self):
        """`i45`: `fleet board` rendered an attested claim identically to an observed one, which
        `working-as-a-dispatched-instant` used to warn about. B07 made the board re-check both."""
        self.assertIn("watcher observed",
                      self.note(phase="awaiting-ci", pane="... 1 monitor ... esc to interrupt"))
        #: `B07`. The attestation carries `declare --watcher`'s prefix: stored BARE, a record means a watcher
        #: this tool OBSERVED at the claim, and this fixture used to depict an attestation in that shape —
        #: one `declare` never writes, and the reason the defect had no failing case.
        self.assertIn("ATTESTED, not observable",
                      self.note(phase="awaiting-ci", pane="no status line",
                                attested="attested: cron every 10m"))
        self.assertIn("NO WATCHER OBSERVABLE",
                      self.note(phase="awaiting-ci", pane="no status line"))
        self.assertIn("NO WATCHER OBSERVABLE",
                      self.note(phase="awaiting-ci", pane="no status line", attested="1 monitor"),
                      "a watcher observed at the claim and gone from the pane read as trusted")

    def test_a_wait_older_than_the_threshold_is_flagged_stale(self):
        note = self.note(phase="awaiting-ci", pane="... 1 monitor ...",
                         declared_at="2026-09-07T15:00:00Z", now="2026-09-07T21:00:00Z")
        self.assertIn("STALE-WAIT", note)

    def test_a_declaration_with_no_timestamp_is_never_stale(self):
        """Every declaration written before this change. Absence is NOT MEASURED."""
        note = self.note(phase="awaiting-ci", pane="... 1 monitor ...", declared_at=None,
                         now="2026-09-07T21:00:00Z")
        self.assertNotIn("STALE-WAIT", note)

    def test_a_float_now_does_not_crash_and_still_flags_stale(self):
        """`_awaiting_note`'s real caller passes `time.time()` — a float. Every other test in this class
        injects an integer `now` via `calendar.timegm`, which would NOT have caught the `:02d}` format
        crash a float `age` produces. A later "simplification" that dropped the `int(age)` cast would
        pass every one of those and still take `reconcile` down on the first real stale wait."""
        self._write_declaration(attested=None, declared_at="2026-09-07T15:00:00Z")
        declared_epoch = calendar.timegm(time.strptime("2026-09-07T15:00:00Z", "%Y-%m-%dT%H:%M:%SZ"))
        now_float = declared_epoch + 5 * 3600 + 0.5
        sessions = _FakeWatcherSessions({"... 1 monitor ...": "1 monitor"})
        note = _awaiting_note("... 1 monitor ...", sessions, self.instant, now=now_float)
        self.assertIn("STALE-WAIT (declared 5h00m ago)", note)

    def test_a_malformed_stamp_is_not_measured_rather_than_raising(self):
        """Controller ruling on the Minor from Task 9's review: a corrupted or hand-edited `at` is NOT
        MEASURED, not a `ValueError` that takes the whole board down for one bad field."""
        self._write_declaration(attested=None, declared_at="not-a-timestamp")
        sessions = _FakeWatcherSessions({"... 1 monitor ...": "1 monitor"})
        note = _awaiting_note("... 1 monitor ...", sessions, self.instant, now=time.time())
        self.assertNotIn("STALE-WAIT", note)


class TestTheIdleStateIsProduced(unittest.TestCase):
    """`G-10`. `FI-14` made `IDLE` actionable; nothing drove `reconcile` TO it.

    `test_render.test_a_stalled_worker_is_counted_as_needing_a_human` hand-builds a subject already
    labelled `IDLE` and asserts the view, so it passes whether or not the producer can ever emit one.
    Measured by mutation on dd2e4ce3: `_live_state`'s threshold branch made dead (`elif False and ...`) left
    all 2009 tests green, as did `_idle_for` always reporting fresh, while dropping `IDLE` from
    `ACTIONABLE_STATES` is killed in `test_render`. Both now die here, as does the over-eager `>= 0`. The harness
    could kill; it never looked at the producer. These cases drive the real join through a worker whose
    instant has been quiet past `idle_after_s`.
    """

    def setUp(self):
        self.fleet = SyntheticFleet()

    def subjects(self, idle_after_s=1800):
        return {s.identity: s for s in reconcile(
            self.fleet.store, self.fleet.pool, self.fleet.sessions,
            self.fleet.instants, idle_after_s=idle_after_s)}

    def quiet_worker(self, todo_id, tmux, pid, pane=QUIET_PANE):
        # ws9 is the fixture's only unleased slot; each case builds its own fleet and takes it once.
        stamp = todo_id.split("-")[1]
        self.fleet.dispatch(todo_id, f"00000000-{stamp}-inflight-append-{todo_id.split('-')[0]}",
                            "ws9", tmux)
        self.fleet.launch(tmux, pid, "ws9", pane)

    def test_a_worker_quiet_past_the_threshold_is_produced_as_idle(self):
        self.quiet_worker("stalled-07300401", "dt-stalled", 5101)
        self.fleet.age("stalled-07300401", 2700)

        subject = self.subjects()["stalled-07300401"]

        self.assertEqual(subject.state, IDLE,
                         f"a live worker with a quiet pane, untouched for 2700s against a 1800s "
                         f"threshold, is not IDLE: {subject.state} / {subject.note!r}")
        self.assertIn("1800", subject.note, "the IDLE note does not name the threshold it crossed")
        self.assertTrue(needs_a_human(subject),
                        "a stalled worker is not in the population a human is asked to act on")

    def test_a_worker_inside_the_threshold_is_running(self):
        """The control: the same worker, the same pane, touched recently. Without it, "IDLE" above is
        equally consistent with a producer that calls every quiet pane IDLE."""
        self.quiet_worker("fresh-07300402", "dt-fresh", 5102)
        self.fleet.age("fresh-07300402", 60)

        subject = self.subjects()["fresh-07300402"]

        self.assertEqual(subject.state, RUNNING,
                         f"a worker touched 60s ago was reported {subject.state}: {subject.note!r}")
        self.assertFalse(needs_a_human(subject), "a progressing worker needs nobody")

    def test_a_busy_pane_is_never_idle_however_old_the_instant(self):
        """A pane still offering a way to interrupt is progressing, whatever the filesystem says."""
        self.quiet_worker("busy-07300403", "dt-busy", 5103, pane=BUSY_PANE)
        self.fleet.age("busy-07300403", 999999)

        subject = self.subjects()["busy-07300403"]

        self.assertEqual(subject.state, RUNNING,
                         f"a busy pane was reported {subject.state} because its files are old")

    def test_the_threshold_is_the_parameter_not_a_constant(self):
        """A case that only ever tests 2700-vs-1800 cannot tell `idle_after_s` from a hard-coded 1800."""
        self.quiet_worker("edge-07300404", "dt-edge", 5104)
        self.fleet.age("edge-07300404", 600)

        self.assertEqual(self.subjects(idle_after_s=300)["edge-07300404"].state, IDLE,
                         "600s quiet against a 300s threshold is not IDLE")
        self.assertEqual(self.subjects(idle_after_s=1800)["edge-07300404"].state, RUNNING,
                         "600s quiet against an 1800s threshold was reported IDLE")

    def test_a_parked_worker_quiet_past_the_threshold_is_still_idle(self):
        """A declaration lives in `.fleet/`, which `_idle_for` reads — so a stalled worker that once parked a
        question is IDLE with the park appended, never masked as PARKED (OBS-7). This is also the case that
        makes `age()` walking `.fleet/*` load-bearing: an unaged `declare.json` reads as fresh activity."""
        self.quiet_worker("parked-07300405", "dt-parked", 5105)
        Declarations(self.fleet.paths["parked-07300405"]).park(PARK_BLOCKED_Q)
        self.fleet.age("parked-07300405", 2700)

        subject = self.subjects()["parked-07300405"]

        self.assertEqual(subject.state, IDLE,
                         f"a parked worker quiet for 2700s was reported {subject.state}: {subject.note!r}")
        self.assertIn(PARK_BLOCKED_Q, subject.note, "the standing park was dropped from the IDLE note")
        self.assertTrue(needs_a_human(subject), "a stalled parked worker is not asked of a human")


#: `FI-55`/`i51(b)`. The exact frame `pane-guard` answered `15 awaiting-operator` for while `board` and `status`
#: said RUNNING with an empty note (re-measure `scenC` C7): an `AskUserQuestion` selection, no caret row, no
#: interrupt hint. `unsubmitted` is None and `busy` is False here, which is the whole defect.
DIALOG_PANE = "\n".join(["Which of these should I keep?",
                         "  1. Drop it",
                         "  2. Keep it and carry the note",
                         "",
                         "Enter to select · Tab/Arrow keys to navigate · Esc to cancel",
                         ""])


class TestNeedsAHumanUsesKnownFacts(unittest.TestCase):
    """`B06`. Attention is decided in one place, and that place consulted fewer facts than the package had
    already computed. Each case drives the real join through `SyntheticFleet`, as `TestTheIdleStateIsProduced`
    does. A hand-built Subject would pass whether or not the producer can ever emit the state.

    Every positive case has a control beside it: the same worker with the one fact removed. Without the
    control, a new branch that fires on everything would pass.
    """

    def setUp(self):
        self.fleet = SyntheticFleet()

    def subjects(self, idle_after_s=1800):
        return {s.identity: s for s in reconcile(
            self.fleet.store, self.fleet.pool, self.fleet.sessions,
            self.fleet.instants, idle_after_s=idle_after_s)}

    def worker(self, todo_id, tmux, pid, pane=QUIET_PANE):
        # ws9 is the fixture's only unleased slot; each case builds its own fleet and takes it once.
        stamp = todo_id.split("-")[1]
        self.fleet.dispatch(todo_id, f"00000000-{stamp}-inflight-append-{todo_id.split('-')[0]}",
                            "ws9", tmux)
        self.fleet.launch(tmux, pid, "ws9", pane)
        return self.fleet.paths[todo_id]

    # --- fact 1: an operator dialog on the pane (`sessions.asking`, pane-guard 15) --------------------

    def test_a_pane_showing_an_operator_dialog_is_blocked(self):
        self.worker("asking-07300501", "dt-asking", 5201, pane=DIALOG_PANE)

        subject = self.subjects()["asking-07300501"]

        self.assertEqual(subject.state, BLOCKED,
                         f"a pane pane-guard calls awaiting-operator (15) was reported {subject.state}: "
                         f"{subject.note!r}")
        self.assertIn("dialog", subject.note, "the note does not say what the human is being asked for")
        self.assertTrue(needs_a_human(subject), "a worker blocked on a dialog is not asked of a human")

    def test_a_quiet_pane_with_no_dialog_is_running(self):
        """The control: same worker, same freshness, the dialog row gone."""
        self.worker("quietctl-07300502", "dt-quietctl", 5202)

        subject = self.subjects()["quietctl-07300502"]

        self.assertEqual(subject.state, RUNNING, f"{subject.state}: {subject.note!r}")
        self.assertFalse(needs_a_human(subject))

    def test_a_busy_pane_outranks_a_dialog_hint_in_its_tail(self):
        """pane-guard's ordering: busy before asking. A live turn keeps its stronger answer."""
        self.worker("busydlg-07300503", "dt-busydlg", 5203,
                    pane=DIALOG_PANE + "\n".join(["Thinking...", "  esc to interrupt"]))

        subject = self.subjects()["busydlg-07300503"]

        self.assertEqual(subject.state, RUNNING, f"{subject.state}: {subject.note!r}")

    def test_a_dialog_is_not_masked_by_a_standing_park(self):
        """OBS-7: an actionable state is never replaced by a standing declaration; the park is appended."""
        path = self.worker("dlgpark-07300504", "dt-dlgpark", 5204, pane=DIALOG_PANE)
        Declarations(path).park(PARK_BLOCKED_Q)

        subject = self.subjects()["dlgpark-07300504"]

        self.assertEqual(subject.state, BLOCKED, f"{subject.state}: {subject.note!r}")
        self.assertIn(PARK_BLOCKED_Q, subject.note)

    # --- fact 2: the instant folder the record names is gone, and the session is live ----------------

    def test_a_live_worker_whose_instant_folder_is_gone_is_blocked(self):
        """re-measure `scenD` D3: folder deleted; `seed-check`/`brief` rc=2; `board`/`status` RUNNING with
        an empty note. Every verb the worker would run to report or finish refuses, so it cannot get out
        on its own, and `_idle_for(None)` is 0, so it would never even age into IDLE."""
        path = self.worker("gone-07300511", "dt-gone", 5211)
        shutil.rmtree(path)

        subject = self.subjects()["gone-07300511"]

        self.assertEqual(subject.state, BLOCKED,
                         f"a live worker with no instant folder was reported {subject.state}: "
                         f"{subject.note!r}")
        self.assertIn(path.name, subject.note, "the note does not name the folder that is gone")
        self.assertTrue(needs_a_human(subject))

    def test_a_folder_gone_with_no_session_stays_dead(self):
        """Scope control. A record with no live session is DEAD, and DEAD needs a reap, not a keystroke
        (W2-14/OBS-57). The missing folder does not reopen that."""
        path = self.fleet.dispatch("gonedead-07300512", "00000000-07300512-inflight-append-gonedead",
                                   "ws9", "dt-gonedead")
        shutil.rmtree(path)

        subject = self.subjects()["gonedead-07300512"]

        self.assertEqual(subject.state, DEAD, f"{subject.state}: {subject.note!r}")
        self.assertFalse(needs_a_human(subject))

    # --- fact 3: a parked question ------------------------------------------------------------------

    def test_a_parked_question_asks_for_a_human(self):
        """x2 `G-11`: a child that parked a question rendered PARKED with the question, and the banner said
        `0 needs you`. `park --question ""` is refused, so a park always asks somebody something. Before
        this change it surfaced only by timing out into IDLE after 30 minutes, which turns a question into
        a stall."""
        path = self.worker("asks-07300521", "dt-asks", 5221)
        Declarations(path).park(PARK_BLOCKED_Q)

        subject = self.subjects()["asks-07300521"]

        self.assertEqual(subject.state, PARKED, f"{subject.state}: {subject.note!r}")
        self.assertIn(PARK_BLOCKED_Q, subject.note)
        self.assertTrue(needs_a_human(subject),
                        "a child blocked on a parked question is not in the population asked of a human")

    def test_a_parked_worker_still_progressing_needs_nobody(self):
        """The control, and OBS-3's carve-out: "a parked note while still working is just a note"."""
        path = self.worker("parkbusy-07300522", "dt-parkbusy", 5222, pane=BUSY_PANE)
        Declarations(path).park(PARK_BUSY_Q)

        subject = self.subjects()["parkbusy-07300522"]

        self.assertEqual(subject.state, PARKED, f"{subject.state}: {subject.note!r}")
        self.assertEqual(subject.evidence["working"], "true")
        self.assertFalse(needs_a_human(subject))

    # --- fact 4: an awaiting-ci claim with nothing watching ------------------------------------------

    def ci_worker(self, todo_id, tmux, pid, pane=QUIET_PANE, recorded=None):
        path = self.worker(todo_id, tmux, pid, pane=pane)
        Declarations(path).set_phase("awaiting-ci", now=_past_the_grace())
        if recorded is not None:
            Declarations(path).set_watchers(recorded)
        return path

    def test_an_unwatched_ci_claim_counts_against_the_cap(self):
        """x2 `M-3`/`D-10`, re-measure scenC. `awaiting-ci` is the one phase that outranks `busy` AND the idle
        threshold, and it takes the worker out of the WIP cap. Claimed with nothing observed on the pane and
        nothing recorded at the claim, it is an exemption nothing backs. The note already said "NO WATCHER
        OBSERVABLE", and the state stayed AWAITING-CI, so the claim kept its exemption."""
        self.ci_worker("unwatched-07300531", "dt-unwatched", 5231)

        subject = self.subjects()["unwatched-07300531"]

        self.assertNotEqual(subject.state, AWAITING_CI,
                            f"an awaiting-ci claim nothing watches kept its exemption: {subject.note!r}")
        self.assertNotIn(subject.state, CAP_EXCLUDED_STATES)
        self.assertIn("NO WATCHER OBSERVABLE", subject.note)
        self.assertIn("disregarded", subject.note, "the note does not say the declaration was set aside")

    def test_an_unwatched_ci_claim_ages_into_idle(self):
        """The half a human sees: nothing will wake it, so once the instant has been quiet past the
        threshold it is IDLE and asks for a human, like any undeclared worker in the same state."""
        self.ci_worker("unwatchedold-07300532", "dt-unwatchedold", 5232)
        self.fleet.age("unwatchedold-07300532", 2700)

        subject = self.subjects()["unwatchedold-07300532"]

        self.assertEqual(subject.state, IDLE, f"{subject.state}: {subject.note!r}")
        self.assertTrue(needs_a_human(subject))

    def test_a_watched_ci_claim_keeps_its_exemption_however_old(self):
        """Control: the watcher is on the status line now. The wait is real and it is excluded from the cap."""
        self.ci_worker("watched-07300533", "dt-watched", 5233, pane=WATCHED_PANE)
        self.fleet.age("watched-07300533", 2700)

        subject = self.subjects()["watched-07300533"]

        self.assertEqual(subject.state, AWAITING_CI, f"{subject.state}: {subject.note!r}")
        self.assertFalse(needs_a_human(subject))

    def test_an_attested_ci_claim_keeps_its_exemption(self):
        """Control: an attestation (`declare --watcher`) names a watcher this tool cannot see, such as a
        cron or a peer's monitor. It was accepted at the claim and is trusted, labelled ATTESTED. Telling a
        genuine attestation from an observed watcher that has since vanished is B07's, not this change's."""
        self.ci_worker("attested-07300534", "dt-attested", 5234,
                       recorded="attested: cron 0,30 * * * * gh-run-poll")
        self.fleet.age("attested-07300534", 2700)

        subject = self.subjects()["attested-07300534"]

        self.assertEqual(subject.state, AWAITING_CI, f"{subject.state}: {subject.note!r}")
        self.assertIn("ATTESTED", subject.note)

    def test_a_watched_claim_blocked_on_a_dialog_is_not_called_unwatched(self):
        """The disregard note is keyed on the watcher classification, never on "the state is not AWAITING-CI".
        A dialog outranks the phase, and the watcher is still there, so saying NO WATCHER here would be false."""
        self.ci_worker("dlgwatched-07300535", "dt-dlgwatched", 5235,
                       recorded="attested: cron 0,30 * * * * gh-run-poll", pane=DIALOG_PANE)

        subject = self.subjects()["dlgwatched-07300535"]

        self.assertEqual(subject.state, BLOCKED, f"{subject.state}: {subject.note!r}")
        self.assertNotIn("NO WATCHER", subject.note)

    def test_a_failed_pane_capture_is_not_read_as_an_absent_watcher(self):
        """`RV-42`/`FI-7`. `sessions.pane` flattens a FAILED capture to `""`, and a caller that BRANCHES on
        emptiness must not. A capture that failed is NOT MEASURED — nothing was observed about the pane, so
        nothing was observed about its watcher either — and reading it as "no watcher" would take a real CI
        waiter's cap exemption away on a tmux hiccup. Before this case the claim was disregarded and the
        note said NO WATCHER OBSERVABLE **on the pane**, about a pane that was never read."""
        self.ci_worker("capfail-07300541", "dt-capfail", 5241, pane=WATCHED_PANE)
        # the capture FAILS: the probe answers None, which is what a tmux that did not answer produces.
        self.fleet.panes["dt-capfail"] = None
        self.fleet.age("capfail-07300541", 2700)

        subject = self.subjects()["capfail-07300541"]

        self.assertEqual(subject.state, AWAITING_CI,
                         f"a failed capture was read as an absent watcher: {subject.state} / "
                         f"{subject.note!r}")
        self.assertNotIn("NO WATCHER OBSERVABLE", subject.note)
        self.assertIn("capture", subject.note.lower(),
                      "the note does not say the pane could not be read")

    def test_an_empty_pane_that_captured_cleanly_is_still_unwatched(self):
        """The control that keeps RV-42's fix from swallowing the defect it guards: an EMPTY capture is an
        observation, and an empty status line carries no watcher."""
        self.ci_worker("capempty-07300542", "dt-capempty", 5242, pane="")
        self.fleet.age("capempty-07300542", 2700)

        subject = self.subjects()["capempty-07300542"]

        self.assertEqual(subject.state, IDLE, f"{subject.state}: {subject.note!r}")
        self.assertIn("NO WATCHER OBSERVABLE", subject.note)

    def test_the_disregard_note_states_the_fact_and_predicts_nothing(self):
        """`RV-43`. The note is appended to whatever state the ordinary detector chose, so a prediction in
        it can be false: a busy pane is RUNNING and `elif busy` precedes the idle check, so that worker
        never ages into IDLE at all. A note that says something the state does not is the family this
        bucket exists to close, one sentence over."""
        self.ci_worker("busyunwatched-07300543", "dt-busyunwatched", 5243, pane=BUSY_PANE)

        subject = self.subjects()["busyunwatched-07300543"]

        self.assertEqual(subject.state, RUNNING, f"{subject.state}: {subject.note!r}")
        self.assertIn("disregarded", subject.note)
        self.assertNotIn("ages into IDLE", subject.note,
                         "the note predicts a future this state cannot reach")

    def test_a_codex_claim_is_blocked_and_never_called_unwatched(self):
        """`RV-45`. The `unwatched` predicate excludes codex on purpose — `_observe_codex` never populates a
        watcher, so every codex `awaiting-ci` claim would classify unwatched and collect a second sentence
        beside the codex BLOCKED note, which already says the whole truth ("this worker still consumes
        capacity"). Nothing pinned that term: deleting it left the suite green."""
        stamp = "07300544"
        self.fleet.dispatch("codexci-07300544", f"00000000-{stamp}-inflight-append-codexci",
                            "ws9", "dt-codexci", runtime="codex")
        # the live process is codex too; a claude process on a codex record is a different finding
        # (`_worker_subject`'s runtime-mismatch BLOCKED) and would mask this one.
        self.fleet.procs.append(LiveSession(pid=5244, cwd=self.fleet.slots_dir / "ws9",
                                            name="dt-codexci", runtime="codex"))
        self.fleet.panes["dt-codexci"] = CODEX_IDLE_PANE
        self.fleet.tmux_live.add("dt-codexci")
        Declarations(self.fleet.paths["codexci-07300544"]).set_phase("awaiting-ci")

        subject = self.subjects()["codexci-07300544"]

        self.assertEqual(subject.state, BLOCKED, f"{subject.state}: {subject.note!r}")
        self.assertIn("Codex has no verified CI wake mechanism", subject.note,
                      "this case must reach `_live_state`'s codex branch, not the earlier dialog return")
        self.assertNotIn("NO WATCHER", subject.note,
                         "a codex claim collected the disregard sentence beside the codex note")

    def test_a_missing_folder_outranks_a_busy_pane(self):
        """`RV-47`. The missing-folder branch is decided before `_live_state`, so it wins over `busy` — the
        opposite of the rule the same function applies to a park (`OBS-3`), and deliberately: a worker
        mid-turn whose instant folder is gone will still be refused by every verb it runs at the end of that
        turn, and the folder does not come back on its own. Fact 1 got exactly this control; fact 2 did not,
        and nothing pinned the ordering."""
        path = self.worker("goneBusy-07300545", "dt-goneBusy", 5245, pane=BUSY_PANE)
        shutil.rmtree(path)

        subject = self.subjects()["goneBusy-07300545"]

        self.assertEqual(subject.state, BLOCKED,
                         f"a busy pane hid a missing instant folder: {subject.state} / {subject.note!r}")
        self.assertIn(path.name, subject.note)

    def test_a_record_that_never_named_a_folder_is_untouched(self):
        """`RV-46`. The missing-folder branch is gated on `rec.child_instant`, and nothing pinned that gate:
        without it, a record that never named a folder would be reported BLOCKED with an empty folder name
        interpolated into the note. `dispatch` always writes the field, so this is a defensive gate — and a
        defensive gate with no case is indistinguishable from a dead one."""
        self.fleet.store.write(_record(todo_id="nofolder-07300546", child_instant="", slot="",
                                       tmux="dt-nofolder"))
        self.fleet.launch("dt-nofolder", 5246, "ws9", QUIET_PANE)

        subject = self.subjects()["nofolder-07300546"]

        self.assertEqual(subject.state, RUNNING,
                         f"a record with no recorded folder was reported {subject.state}: {subject.note!r}")
        self.assertEqual(subject.note, "", f"an empty folder name reached the note: {subject.note!r}")


def _fake_proc(root, pid, state="S", start="777", comm="release gate"):
    """A `/proc/<pid>/stat` in a private tree, so no case here starts or kills a process (module docstring).
    Twenty-two fields: `state` is field 3 and `starttime` field 22, the two `reconcile` reads."""
    d = pathlib.Path(root) / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    after_comm = [state] + ["0"] * 18 + [start, "0", "0"]      # index 0 is field 3, index 19 is field 22
    (d / "stat").write_text(f"{pid} ({comm}) " + " ".join(after_comm) + "\n")


def _declare_json(path, **fields):
    """Merge fields into an instant's `declare.json` directly: the shape a claim leaves on disk, so a case can
    describe it without depending on the writer under test (and fails on an ASSERTION where the reader is wrong)."""
    target = pathlib.Path(path) / ".fleet" / "declare.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(target.read_text()) if target.exists() else {}
    data.update(fields)
    target.write_text(json.dumps(data))


class TestTheWatcherIsClassifiedFromWhatIsTrue(unittest.TestCase):
    """`B07` + `FB-58`. An `awaiting-ci` claim's watcher was classified from what was RECORDED, not from what
    is TRUE. Re-measure scenC C5: a watcher OBSERVED at the claim is stored bare, `_watcher_of` read only
    whether anything was recorded, so once it vanished from the pane the row read *"watcher ATTESTED, not
    observable: 1 monitor"* — the trusted branch, keeping the WIP-cap exemption. `FB-58` (r3 release worker
    OI-10): an attestation outlived the harness task it named, and the claim stayed trusted until the worker
    re-declared by hand. Each case drives the real join; each positive has its control beside it."""

    def setUp(self):
        self.fleet = SyntheticFleet()
        scratch = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, scratch, True)
        self.proc = pathlib.Path(scratch) / "proc"
        self.proc.mkdir()
        patcher = mock.patch("fleet.reconcile.PROC_ROOT", self.proc)
        patcher.start()
        self.addCleanup(patcher.stop)

    def subjects(self, idle_after_s=1800):
        return {s.identity: s for s in reconcile(
            self.fleet.store, self.fleet.pool, self.fleet.sessions,
            self.fleet.instants, idle_after_s=idle_after_s)}

    def ci_worker(self, todo_id, tmux, pid, pane=QUIET_PANE, **declared):
        stamp = todo_id.split("-")[1]
        self.fleet.dispatch(todo_id, f"00000000-{stamp}-inflight-append-{todo_id.split('-')[0]}",
                            "ws9", tmux)
        self.fleet.launch(tmux, pid, "ws9", pane)
        path = self.fleet.paths[todo_id]
        Declarations(path).set_phase("awaiting-ci", now=_past_the_grace())
        _declare_json(path, **declared)
        return path

    # --- B07: an OBSERVED watcher is re-checked, never promoted to ATTESTED ---------------------------

    def test_an_observed_watcher_that_vanished_is_no_watcher(self):
        """scenC C5, the falsifier. Stored bare = OBSERVED at the claim; not on the pane now = gone."""
        self.ci_worker("vanished-07300601", "dt-vanished", 5301, watchers="1 monitor")

        subject = self.subjects()["vanished-07300601"]

        self.assertNotEqual(subject.state, AWAITING_CI,
                            f"an observed watcher that vanished kept the exemption: {subject.note!r}")
        self.assertNotIn(subject.state, CAP_EXCLUDED_STATES)
        self.assertIn("NO WATCHER OBSERVABLE", subject.note)
        self.assertIn("disregarded", subject.note)
        self.assertIn("1 monitor", subject.note, "the note does not say WHICH watcher is gone")
        self.assertNotIn("ATTESTED", subject.note,
                         "a watcher this tool observed was relabelled as the claimant's word")

    def test_an_observed_watcher_that_vanished_ages_into_idle(self):
        self.ci_worker("vanishedold-07300602", "dt-vanishedold", 5302, watchers="1 monitor")
        self.fleet.age("vanishedold-07300602", 2700)

        subject = self.subjects()["vanishedold-07300602"]

        self.assertEqual(subject.state, IDLE, f"{subject.state}: {subject.note!r}")
        self.assertTrue(needs_a_human(subject))

    def test_an_observed_watcher_still_on_the_pane_keeps_the_exemption(self):
        """Control: the same record, the watcher still drawn."""
        self.ci_worker("stillthere-07300603", "dt-stillthere", 5303, pane=WATCHED_PANE,
                       watchers="1 monitor")
        self.fleet.age("stillthere-07300603", 2700)

        subject = self.subjects()["stillthere-07300603"]

        self.assertEqual(subject.state, AWAITING_CI, f"{subject.state}: {subject.note!r}")
        self.assertIn("watcher observed", subject.note)

    def test_an_observed_record_with_a_failed_capture_is_not_measured(self):
        """Control (`RV-42`/`FI-7`): the pane was never read, so nothing says the watcher is gone."""
        self.ci_worker("obscapfail-07300604", "dt-obscapfail", 5304, pane=WATCHED_PANE,
                       watchers="1 monitor")
        self.fleet.panes["dt-obscapfail"] = None

        subject = self.subjects()["obscapfail-07300604"]

        self.assertEqual(subject.state, AWAITING_CI, f"{subject.state}: {subject.note!r}")
        self.assertIn("capture", subject.note.lower())
        self.assertNotIn("NO WATCHER", subject.note)

    # --- FB-58: an ATTESTED watcher with a checkable handle is checked ------------------------------

    def test_an_attested_watcher_whose_pid_is_gone_is_not_trusted(self):
        self.ci_worker("pidgone-07300611", "dt-pidgone", 5311,
                       watchers="attested: harness task running release-gate.sh pid:4242",
                       watcher_pid={"pid": 4242, "start": "777"})

        subject = self.subjects()["pidgone-07300611"]

        self.assertNotEqual(subject.state, AWAITING_CI,
                            f"an attested watcher whose pid exited kept the exemption: {subject.note!r}")
        self.assertIn("4242", subject.note)
        self.assertIn("GONE", subject.note)
        self.assertIn("disregarded", subject.note)

    def test_an_attested_pid_reused_by_another_process_is_gone(self):
        """A pid alone is recycled; the start time recorded at the claim is what names THAT process."""
        _fake_proc(self.proc, 4243, start="999")
        self.ci_worker("pidreused-07300612", "dt-pidreused", 5312,
                       watchers="attested: gate pid:4243", watcher_pid={"pid": 4243, "start": "777"})

        subject = self.subjects()["pidreused-07300612"]

        self.assertNotEqual(subject.state, AWAITING_CI, f"{subject.state}: {subject.note!r}")
        self.assertIn("GONE", subject.note)

    def test_an_attested_pid_that_is_a_zombie_is_gone(self):
        """Exited and not yet reaped: it watches nothing."""
        _fake_proc(self.proc, 4244, state="Z")
        self.ci_worker("pidzombie-07300613", "dt-pidzombie", 5313,
                       watchers="attested: gate pid:4244", watcher_pid={"pid": 4244, "start": "777"})

        subject = self.subjects()["pidzombie-07300613"]

        self.assertNotEqual(subject.state, AWAITING_CI, f"{subject.state}: {subject.note!r}")
        self.assertIn("GONE", subject.note)

    def test_an_attested_pid_still_running_keeps_the_exemption(self):
        """Control: the same record while the process named is the one that was attested."""
        _fake_proc(self.proc, 4245, start="777")
        self.ci_worker("pidalive-07300614", "dt-pidalive", 5314,
                       watchers="attested: gate pid:4245", watcher_pid={"pid": 4245, "start": "777"})
        self.fleet.age("pidalive-07300614", 2700)

        subject = self.subjects()["pidalive-07300614"]

        self.assertEqual(subject.state, AWAITING_CI, f"{subject.state}: {subject.note!r}")
        self.assertIn("ATTESTED", subject.note)
        self.assertIn("running", subject.note)

    def test_a_command_name_with_parentheses_and_spaces_is_parsed_after_the_last_paren(self):
        """`RV-C6`. The comm field is free text: `sleep) Z 1 (x` would put a fake `Z` where a first-`)` split
        reads the state, and call a running watcher a zombie."""
        _fake_proc(self.proc, 4249, start="777", comm="gate) Z 1 (x")
        self.ci_worker("parencomm-07300633", "dt-parencomm", 5333,
                       watchers="attested: gate pid:4249", watcher_pid={"pid": 4249, "start": "777"})

        subject = self.subjects()["parencomm-07300633"]

        self.assertEqual(subject.state, AWAITING_CI, f"{subject.state}: {subject.note!r}")
        self.assertIn("pid 4249 is running", subject.note)

    def test_an_unreadable_attested_pid_is_not_measured(self):
        """A read that FAILED is not a read that found nothing (`FI-7`): the attestation stands."""
        (self.proc / "4246" / "stat").mkdir(parents=True)          # reading it raises, and not ENOENT
        self.ci_worker("pidunread-07300615", "dt-pidunread", 5315,
                       watchers="attested: gate pid:4246", watcher_pid={"pid": 4246, "start": "777"})

        subject = self.subjects()["pidunread-07300615"]

        self.assertEqual(subject.state, AWAITING_CI, f"{subject.state}: {subject.note!r}")
        self.assertIn("could not be read", subject.note)

    def test_the_state_and_the_note_come_from_one_classification(self):
        """`RV-C2`. The state and the note each classified the watcher, so a pid exiting between the two `/proc`
        reads gave an AWAITING-CI row whose note said the watcher was GONE — a note contradicting its own state
        (`RV-43`). Simulated here by a classifier whose answer changes between calls."""
        self.ci_worker("race-07300631", "dt-race", 5331, watchers="attested: gate pid:4248",
                       watcher_pid={"pid": 4248, "start": "777"})
        import fleet.reconcile as reconcile_mod
        real = reconcile_mod._watcher_of
        answers = [("attested", "gate pid:4248 (its pid 4248 is running)"),
                   ("gone", "the attested watcher pid 4248 is GONE (it has exited since the claim)")]
        calls = []

        def racing(pane, sessions, instant, **kw):
            if instant is None or "race" not in str(instant):
                return real(pane, sessions, instant, **kw)
            calls.append(1)
            return answers[min(len(calls), len(answers)) - 1]

        with mock.patch("fleet.reconcile._watcher_of", side_effect=racing):
            subject = self.subjects()["race-07300631"]

        if subject.state == AWAITING_CI:
            self.assertNotIn("GONE", subject.note, f"the note contradicts its state: {subject.note!r}")
        else:
            self.assertIn("GONE", subject.note, f"{subject.state}: {subject.note!r}")

    def test_an_attestation_recorded_before_handles_is_not_told_it_names_no_pid(self):
        """`RV-C3`. A record written before `watcher_pid` existed can carry `pid=1234` in its TEXT with no handle
        beside it. "it names no pid", printed next to text that names one, is false; what is true is that no
        handle was RECORDED, so nothing re-checks it."""
        self.ci_worker("legacypid-07300632", "dt-legacypid", 5332, watchers="attested: gate pid=1234")

        subject = self.subjects()["legacypid-07300632"]

        self.assertEqual(subject.state, AWAITING_CI, f"{subject.state}: {subject.note!r}")
        self.assertNotIn("names no pid", subject.note)
        self.assertIn("no pid handle was recorded", subject.note)

    def test_a_malformed_pid_handle_is_not_measured_and_never_crashes_the_board(self):
        """`RV-C5`. `declare.json` is a file; one hand-edited or truncated `watcher_pid` raised TypeError out of
        `reconcile` and took down `fleet board` for EVERY row. A handle that cannot be read is NOT MEASURED."""
        for n, bad in enumerate(({"pid": None}, "pid:4247", {"pid": "x"}, ["pid"])):
            self.fleet = SyntheticFleet()                  # ws9 is taken once per fleet
            todo = f"pidbad{n}-0730062{n}"
            self.ci_worker(todo, f"dt-pidbad{n}", 5320 + n, watchers="attested: gate pid:4247",
                           watcher_pid=bad)

            subject = self.subjects()[todo]

            self.assertEqual(subject.state, AWAITING_CI, f"{bad!r}: {subject.state} {subject.note!r}")
            self.assertIn("could not be read", subject.note, f"{bad!r}: {subject.note!r}")

    def test_a_free_text_attestation_stays_attested_and_says_nothing_rechecks_it(self):
        """Control: a cron has no handle fleet can check. It stays trusted, and says it is unchecked."""
        self.ci_worker("freetext-07300616", "dt-freetext", 5316,
                       watchers="attested: cron 0,30 * * * * gh-run-poll")
        self.fleet.age("freetext-07300616", 2700)

        subject = self.subjects()["freetext-07300616"]

        self.assertEqual(subject.state, AWAITING_CI, f"{subject.state}: {subject.note!r}")
        self.assertIn("ATTESTED", subject.note)
        self.assertIn("no pid handle was recorded", subject.note)


class TestAnAttachedHumanIsNotAStuckWorker(unittest.TestCase):
    """`B24` (x2 `G-4`, `FI-9`). `BLOCKED` is actionable, and a pane showing unsubmitted text or a dialog
    reads the same whether a worker is stuck there or a HUMAN is attached and mid-sentence. Those demand
    opposite responses, and tmux knows which it is (which clients are attached, and when each last gave input);
    fleet never asked. It now asks per client (`list-clients`, RV-28).

    The state stays BLOCKED — the row still says what the pane shows (no new state, B16's fence), and the
    reporter's retracted remedy (narrow BLOCKED to `park.json`) is not taken: a worker at a permission modal
    has no `park.json` either. What changes is whether it is counted as waiting on somebody who is not there.

    Every positive has its control: the same pane with the one fact removed.
    """

    def setUp(self):
        self.fleet = SyntheticFleet()

    def subjects(self, idle_after_s=1800):
        return {s.identity: s for s in reconcile(
            self.fleet.store, self.fleet.pool, self.fleet.sessions,
            self.fleet.instants, idle_after_s=idle_after_s)}

    def worker(self, todo_id, tmux, pid, pane, attached=None):
        stamp = todo_id.split("-")[1]
        self.fleet.dispatch(todo_id, f"00000000-{stamp}-inflight-append-{todo_id.split('-')[0]}",
                            "ws9", tmux)
        self.fleet.launch(tmux, pid, "ws9", pane)
        if attached is not None:
            self.fleet.attached[tmux] = attached
        return self.fleet.paths[todo_id]

    def test_a_human_attached_and_mid_sentence_is_not_counted(self):
        """The defect. `evidence/50-cli-repro/base.txt` S1: `attention` for a human typing in the pane."""
        self.worker("typing-07300601", "dt-typing", 5301, TYPING_PANE, attached=(1, time.time() - 20))

        subject = self.subjects()["typing-07300601"]

        self.assertEqual(subject.state, BLOCKED, "the row must still say what the pane shows")
        self.assertFalse(needs_a_human(subject),
                         f"a human attached and typing was counted as needing a human: {subject.note!r}")
        self.assertIn("human is attached", subject.note)

    def test_the_same_text_with_nobody_attached_is_still_counted(self):
        """The control, and the reason BLOCKED exists: a swallowed submit with nobody at the pane."""
        self.worker("swallowed-07300602", "dt-swallowed", 5302, TYPING_PANE, attached=(0, time.time() - 20))

        subject = self.subjects()["swallowed-07300602"]

        self.assertEqual(subject.state, BLOCKED)
        self.assertTrue(needs_a_human(subject))
        self.assertNotIn("attached", subject.note, "a detached pane's note must read as it always did")

    def test_a_dialog_with_a_human_attached_is_theirs_to_answer(self):
        self.worker("dlgattached-07300603", "dt-dlgattached", 5303, DIALOG_PANE,
                    attached=(1, time.time() - 5))

        subject = self.subjects()["dlgattached-07300603"]

        self.assertEqual(subject.state, BLOCKED)
        self.assertFalse(needs_a_human(subject), subject.note)

    def test_a_dialog_with_nobody_attached_is_a_stuck_worker(self):
        """The case the retraction protects: a worker stopped at a permission modal, no park, no human."""
        self.worker("dlgstuck-07300604", "dt-dlgstuck", 5304, DIALOG_PANE, attached=(0, time.time() - 5))

        subject = self.subjects()["dlgstuck-07300604"]

        self.assertEqual(subject.state, BLOCKED)
        self.assertTrue(needs_a_human(subject))

    def test_a_client_attached_with_no_input_past_the_threshold_is_not_a_human_at_the_pane(self):
        """A terminal left attached overnight. Attachment alone would silence a stuck modal FOREVER — the
        counter's unrecoverable direction — so a stale attachment falls back to counted, and says why."""
        self.worker("forgotten-07300605", "dt-forgotten", 5305, DIALOG_PANE,
                    attached=(1, time.time() - 1801))

        subject = self.subjects(idle_after_s=1800)["forgotten-07300605"]

        self.assertEqual(subject.state, BLOCKED)
        self.assertTrue(needs_a_human(subject),
                        f"a client silent for longer than the idle threshold hid a stuck worker: {subject.note!r}")
        self.assertIn("no input", subject.note)

    def test_an_unobservable_attachment_is_counted(self):
        """Fails safe FOR THIS CONSUMER. Not measured is not "a human is here": the counter keeps today's
        answer. (An actuator's safe side is the opposite; `SessionLayer.attachment` leaves that to it.)"""
        self.worker("unasked-07300606", "dt-unasked", 5306, TYPING_PANE)   # no attachment fact at all

        subject = self.subjects()["unasked-07300606"]

        self.assertEqual(subject.state, BLOCKED)
        self.assertTrue(needs_a_human(subject))
        #: `RV-27`. None is also a probe that was never supplied, or a session tmux has no row for; the note
        #: states what is known and no cause it cannot know (`RV-43`'s family).
        self.assertIn("could not be observed", subject.note)
        self.assertNotIn("tmux did not answer", subject.note)

    def test_a_last_input_in_the_future_is_not_measured(self):
        """`RV-33`. A clock stepped backwards puts `last_input` in the future; clamping that age to 0 read it
        as "input 0s ago", i.e. attended. An age that cannot be true is not a measurement."""
        self.worker("future-07300611", "dt-future", 5311, DIALOG_PANE, attached=(1, time.time() + 600))

        subject = self.subjects()["future-07300611"]

        self.assertTrue(needs_a_human(subject), subject.note)
        self.assertIn("could not be observed", subject.note)

    def test_the_note_and_the_evidence_state_one_age(self):
        """`RV-32`. The note and `evidence.attached` each read the clock, so they could state two ages for one
        fact. Driven with a clock that advances one second per read, which makes a second read visible."""
        import re
        from unittest import mock
        import fleet.reconcile as rc
        start = time.time()
        ticks = iter(start + n for n in range(1000))
        self.worker("oneage-07300612", "dt-oneage", 5312, DIALOG_PANE, attached=(1, start - 100))

        with mock.patch.object(rc.time, "time", lambda: next(ticks)):
            subject = self.subjects()["oneage-07300612"]

        in_note = re.search(r"last input (\d+)s ago", subject.note).group(1)
        in_evidence = re.search(r"last input (\d+)s ago", subject.evidence["attached"]).group(1)
        self.assertEqual(in_note, in_evidence, f"{subject.note!r} vs {subject.evidence['attached']!r}")

    def test_a_dialog_with_only_a_non_interactive_client_is_counted_and_says_why(self):
        """`RV-36`. A read-only or control-mode client shows no recency fleet can see, so it does not excuse the
        pane — and the note says a client IS there, rather than reading like a detached pane."""
        self.worker("observed-07300613", "dt-observed", 5313, DIALOG_PANE, attached=(0, 0, 1))

        subject = self.subjects()["observed-07300613"]

        self.assertTrue(needs_a_human(subject), subject.note)
        self.assertIn("read-only or control-mode", subject.note)
        self.assertIn("read-only or control-mode", subject.evidence["attached"])
        self.assertNotEqual(subject.evidence["attached"], "no client")

    def test_attachment_alone_makes_nothing_actionable_or_blocked(self):
        self.worker("watched-07300607", "dt-watched", 5307, QUIET_PANE, attached=(2, time.time()))

        subject = self.subjects()["watched-07300607"]

        self.assertEqual(subject.state, RUNNING, subject.note)
        self.assertFalse(needs_a_human(subject))

    def test_a_missing_folder_is_not_excused_by_an_attached_human(self):
        """Only what is ON THE PANE belongs to the human at it. A deleted instant folder is not on their
        screen, and attaching does not bring it back."""
        path = self.worker("nofolder-07300608", "dt-nofolder", 5308, TYPING_PANE,
                           attached=(1, time.time()))
        shutil.rmtree(path)

        subject = self.subjects()["nofolder-07300608"]

        self.assertEqual(subject.state, BLOCKED)
        self.assertIn("not on disk", subject.note)
        self.assertTrue(needs_a_human(subject))

    def test_a_parked_question_is_not_excused_by_an_attached_human(self):
        """A park is addressed to the coordinator, not to whoever is at the pane, so it keeps counting."""
        path = self.worker("dlgparked-07300609", "dt-dlgparked", 5309, DIALOG_PANE,
                           attached=(1, time.time()))
        Declarations(path).park(PARK_BLOCKED_Q)

        subject = self.subjects()["dlgparked-07300609"]

        self.assertEqual(subject.state, BLOCKED)
        self.assertTrue(needs_a_human(subject), subject.note)

    def test_the_attachment_is_reported_as_evidence(self):
        self.worker("evid-07300610", "dt-evid", 5310, QUIET_PANE, attached=(1, time.time() - 40))

        evidence = self.subjects()["evid-07300610"].evidence

        self.assertIn("attached", evidence)
        self.assertTrue(evidence["attached"].startswith("1 client"), evidence["attached"])


class TestOnlyWhatWasSeenIsExcusedOnACodexPane(unittest.TestCase):
    """`RV-25`. A codex pane that could not be CAPTURED observes as `unknown`, and so does a frame the
    classifier does not recognise; both reach the codex BLOCKED. Marking that "on the pane" let an attached
    client excuse a pane fleet never saw — `FI-7`'s permissive default one step removed. Only an observed
    DIALOG is on the human's screen to answer."""

    def setUp(self):
        self.fleet = SyntheticFleet()

    def codex_worker(self, todo_id, tmux, pid, pane):
        stamp = todo_id.split("-")[1]
        self.fleet.dispatch(todo_id, f"00000000-{stamp}-inflight-append-{todo_id.split('-')[0]}",
                            "ws9", tmux, runtime="codex")
        self.fleet.procs.append(LiveSession(pid=pid, cwd=self.fleet.slots_dir / "ws9", name=tmux,
                                            runtime="codex"))
        self.fleet.panes[tmux] = pane          # None: the capture FAILED (`capture_pane` returns None)
        self.fleet.tmux_live.add(tmux)
        self.fleet.attached[tmux] = (1, time.time() - 5)
        return {s.identity: s for s in reconcile(self.fleet.store, self.fleet.pool, self.fleet.sessions,
                                                  self.fleet.instants)}[todo_id]

    def test_a_codex_pane_whose_capture_failed_is_counted(self):
        subject = self.codex_worker("cxfailed-07300701", "dt-cxfailed", 5401, None)

        self.assertEqual(subject.state, BLOCKED, subject.note)
        self.assertTrue(needs_a_human(subject),
                        f"a pane fleet could not capture was excused by an attached client: {subject.note!r}")

    def test_an_unrecognised_codex_frame_is_counted(self):
        subject = self.codex_worker("cxodd-07300702", "dt-cxodd", 5402, "something codex never draws")

        self.assertEqual(subject.state, BLOCKED, subject.note)
        self.assertTrue(needs_a_human(subject), subject.note)

    def test_an_observed_codex_dialog_with_a_human_attached_is_theirs(self):
        """The neighbour the narrowing must keep: a dialog fleet SAW, in front of an attached human."""
        #: Codex's measured approval row (`runtime._DIALOG_ROWS`); `observe("codex", ...)` reads it `dialog`.
        frame = "Run this command?\n  $ make test\n\n  1. Yes\n  2. No\n\nPress enter to confirm or esc to cancel\n"
        subject = self.codex_worker("cxdlg-07300703", "dt-cxdlg", 5403, frame)

        self.assertEqual(subject.state, BLOCKED, subject.note)
        self.assertFalse(needs_a_human(subject), subject.note)


class TestTheNonPaneBlockedSourcesAreNeverExcused(unittest.TestCase):
    """`RV-26`. DECISIONS D-3 names six BLOCKED producers and only the pane-level ones may be excused by an
    attached human. The dialog, the unsubmitted text, the missing folder and the park are pinned above;
    these pin the runtime mismatch (whose `on_pane = False` reset a mutation deleted with the suite green)
    and codex's unwatched awaiting-ci."""

    def setUp(self):
        self.fleet = SyntheticFleet()

    def subjects(self):
        return {s.identity: s for s in reconcile(self.fleet.store, self.fleet.pool, self.fleet.sessions,
                                                  self.fleet.instants)}

    def test_a_runtime_mismatch_on_a_dialog_pane_is_counted_even_with_a_human_attached(self):
        """The dialog would be excused on its own; the mismatch that REPLACES it is not on the pane."""
        self.fleet.dispatch("mismatch-07300801", "00000000-07300801-inflight-append-mismatch",
                            "ws9", "dt-mismatch")                     # a claude record ...
        self.fleet.procs.append(LiveSession(pid=5501, cwd=self.fleet.slots_dir / "ws9",
                                            name="dt-mismatch", runtime="codex"))   # ... a codex process
        self.fleet.panes["dt-mismatch"] = DIALOG_PANE
        self.fleet.tmux_live.add("dt-mismatch")
        self.fleet.attached["dt-mismatch"] = (1, time.time() - 5)

        subject = self.subjects()["mismatch-07300801"]

        self.assertEqual(subject.state, BLOCKED)
        self.assertIn("differs from record runtime", subject.note)
        self.assertTrue(needs_a_human(subject), subject.note)

    def test_a_codex_unwatched_awaiting_ci_is_counted_even_with_a_human_attached(self):
        self.fleet.dispatch("codexciat-07300802", "00000000-07300802-inflight-append-codexciat",
                            "ws9", "dt-codexciat", runtime="codex")
        self.fleet.procs.append(LiveSession(pid=5502, cwd=self.fleet.slots_dir / "ws9",
                                            name="dt-codexciat", runtime="codex"))
        self.fleet.panes["dt-codexciat"] = CODEX_IDLE_PANE
        self.fleet.tmux_live.add("dt-codexciat")
        self.fleet.attached["dt-codexciat"] = (1, time.time() - 5)
        Declarations(self.fleet.paths["codexciat-07300802"]).set_phase("awaiting-ci")

        subject = self.subjects()["codexciat-07300802"]

        self.assertEqual(subject.state, BLOCKED)
        self.assertIn("Codex has no verified CI wake mechanism", subject.note)
        self.assertTrue(needs_a_human(subject), subject.note)


class UnreadableRowAttributionTests(unittest.TestCase):
    """FB-54. A live pid whose `exe`/`cwd` refuse the read is still placed by its pane: `reconcile` must read it as the
    session it is, not as an unknown process outside every slot. The rows come from the REAL probe over a fake `/proc`
    (`probe_unreadable`), so these fail at the base for the reason FB-54 names: the row there carries no name."""

    def setUp(self):
        self.fleet = SyntheticFleet()
        self.addCleanup(shutil.rmtree, self.fleet.tmp, ignore_errors=True)
        self.proc = self.fleet.tmp / "proc"

    def subjects(self):
        return reconcile(self.fleet.store, self.fleet.pool, self.fleet.sessions, self.fleet.instants)

    def test_an_unreadable_process_in_a_records_pane_is_that_records_worker(self):
        fleet = self.fleet
        fleet.dispatch("unread-07300310", "00000000-07300310-inflight-append-unread", "ws9", "dt-unread")
        fleet.tmux_live.add("dt-unread")
        fleet.panes["dt-unread"] = QUIET_PANE
        fleet.procs.append(probe_unreadable(self.proc, 7002, 7001, "dt-unread"))
        subjects = self.subjects()
        self.assertEqual([s.identity for s in subjects if s.evidence.get("pid") == "7002"], ["unread-07300310"],
                         "the unreadable pid is this record's session, not an unknown one")
        worker = next(s for s in subjects if s.identity == "unread-07300310")
        self.assertEqual((worker.evidence["liveness"], worker.evidence["slot"]), ("process", "ws9"))
        self.assertEqual(worker.evidence.get("process"), "unreadable")
        self.assertIn("unreadable", worker.note)

    def test_the_texts_do_not_name_a_cause_nobody_observed(self):
        """RV-24. Since FB-53 an unreadable row also stands for a `comm`/`cmdline` read that failed (EIO, EINVAL, …) with
        `exe` and `cwd` perfectly readable, and the row does not keep which read failed. The notes say what is known."""
        fleet = self.fleet
        fleet.dispatch("unread-07300314", "00000000-07300314-inflight-append-unread", "ws9", "dt-unread")
        fleet.tmux_live.add("dt-unread")
        fleet.panes["dt-unread"] = QUIET_PANE
        fleet.procs.append(probe_unreadable(self.proc, 7002, 7001, "dt-unread"))
        fleet.procs.append(probe_unreadable(self.proc / "b", 7006, 7005, "nobody", owned=False))
        notes = [s.note for s in self.subjects() if s.evidence.get("pid") in ("7002", "7006")]
        self.assertEqual(len(notes), 2)
        for note in notes:
            self.assertIn("a /proc read of it failed", note)
            self.assertNotIn("exe/cwd", note)

    def test_a_readable_worker_in_the_same_pane_speaks_for_the_record(self):
        """RV-25. One record's pane holds a readable claude AND a lower-pid unreadable one (a descendant whose reads
        failed). The record is represented by the process it can actually read — `evidence.pid` feeds the watchdog's
        exclude list — and the unreadable pid, now named, must not take that place because `pgrep` listed it first."""
        fleet = self.fleet
        fleet.dispatch("unread-07300312", "00000000-07300312-inflight-append-unread", "ws9", "dt-both")
        fleet.tmux_live.add("dt-both")
        fleet.panes["dt-both"] = QUIET_PANE
        fleet.procs.append(probe_unreadable(self.proc, 7002, 7001, "dt-both"))
        fleet.procs.append(LiveSession(pid=7010, cwd=fleet.slots_dir / "ws9", name="dt-both"))
        worker = next(s for s in self.subjects() if s.identity == "unread-07300312")
        self.assertEqual((worker.evidence["pid"], worker.evidence["process"]), ("7010", ""))
        self.assertNotIn("unreadable", worker.note)

    def test_an_unreadable_process_in_an_unrecorded_leased_pane_holds_that_lease(self):
        """No record in this store, but a lease names the pane's session: the lease join falls back on the NAME, because
        the cwd it would normally compare was never read. One subject for the slot, holding it — not a pid-labelled
        unknown outside every slot beside a separate row for the lease."""
        fleet = self.fleet
        fleet.pool.claim(todo_id="foreign-07300311", tmux="dt-foreign", base_instant=OURS,
                         child_instant=OURS + "/foreign", slot="ws9")
        fleet.tmux_live.add("dt-foreign")
        fleet.procs.append(probe_unreadable(self.proc, 7004, 7003, "dt-foreign"))
        rows = [s for s in self.subjects() if s.evidence.get("slot") == "ws9"]
        self.assertEqual([(s.state, s.holds_slot, s.evidence.get("pid")) for s in rows],
                         [(UNKNOWN_SESSION, True, "7004")])
        self.assertIn("could not be read", rows[0].note)

    def test_a_same_named_pane_on_another_server_does_not_take_that_servers_lease(self):
        """RV-29. A lease names a tmux session, not a server. Record B lives on server `other` and leases ws9 for
        `dt-x`; THIS server has its own `dt-x` pane holding an unreadable claude. The name fallback must not hand
        B's slot to it — two subjects would then hold ws9."""
        fleet = self.fleet
        fleet.dispatch("elsewhere-07300313", "00000000-07300313-inflight-append-elsewhere", "ws9", "dt-x",
                       tmux_socket="other")
        fleet.procs.append(probe_unreadable(self.proc, 7008, 7007, "dt-x"))
        subjects = self.subjects()
        self.assertEqual([s.identity for s in subjects if s.holds_slot and s.evidence.get("slot") == "ws9"],
                         ["elsewhere-07300313"])
        unknown = next(s for s in subjects if s.evidence.get("pid") == "7008")
        self.assertEqual((unknown.state, unknown.holds_slot), (UNKNOWN_SESSION, False))

    def test_an_unreadable_process_no_pane_owns_is_reported_as_unplaceable(self):
        """A control on the other side: nothing names it, so it stays an unknown holding no slot — and says WHY."""
        fleet = self.fleet
        fleet.procs.append(probe_unreadable(self.proc, 7006, 7005, "no-such-pane", owned=False))
        rows = [s for s in self.subjects() if s.evidence.get("pid") == "7006"]
        self.assertEqual([(s.state, s.holds_slot, s.evidence["session"]) for s in rows], [(UNKNOWN_SESSION, False, "")])
        self.assertIn("could not be read", rows[0].note)
