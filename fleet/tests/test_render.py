"""The views — every one derived, every one identifiable, none of them computing a state.

Each case names the defect it encodes, because the case list is the hard part: every one of these was
shipped once with an assertion weaker than the case intended.

Two structural rules run through the whole file:

* **Nothing here is asserted from a model of the output.** `OBS-62` was an assertion anchored to a human
  summary line that *could never match* — *"I wrote the check from a model of the board's output rather
  than from its output"*. So every assertion parses what `render` actually returned, and where a column
  position is needed it comes from `render`'s own declared schema (`render.BOARD_COLUMNS`) plus a raw
  text-membership check that survives the schema being wrong.
* **The input subjects are the only source of a state value.** `reconcile` is the one producer; these
  tests treat its output as given and check that the views transport it unchanged.
"""
import ast
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

from fleet import render
from fleet.pool import Pool
from fleet.reconcile import (ACTIONABLE_STATES, KIND_STALE_LEASE, KIND_UNKNOWN, KIND_WORKER,
                             STATES, Subject)

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

OURS = "/i/00000000-07300312-inflight-append-fleetInfraRebuild"
THEIRS = "/i/00000000-07290101-inflight-append-otherEffort"


# --- fixture subjects. `Subject` is consumed verbatim; nothing here adds a field. ------------------


def worker(identity, state, holds_slot=True, slot="ws1", folder_state="inflight", note="", **extra):
    evidence = {
        "record": identity,
        "base": OURS,
        "instant": f"/i/00000000-07300301-{folder_state}-append-{identity.split('-')[0]}",
        "folder_state": folder_state,
        "liveness": "process" if state not in ("DEAD", "PENDING-LAUNCH") else "none",
        "tmux": f"dt-{identity.split('-')[0]}",
        "slot": slot if holds_slot else "",
        "lease": "held" if holds_slot else "released",
    }
    evidence.update(extra)
    return Subject(kind=KIND_WORKER, identity=identity, state=state, holds_slot=holds_slot,
                   evidence=evidence, note=note)


def unknown(pid=4242, session="screen-1", slot="ws2"):
    """A live session no record claims — `OBS-48`'s 8d20h stray, sitting in a leased slot."""
    return Subject(
        kind=KIND_UNKNOWN, identity=f"session:{session}:{pid}", state="UNKNOWN-SESSION",
        holds_slot=bool(slot),
        evidence={"pid": str(pid), "cwd": f"/slots/{slot}", "session": session,
                  "record": "none", "slot": slot},
        note=("no dispatch record claims this session; it is reported so a human can decide, and this "
              "tool does nothing to it"))


def stale_lease(slot="ws3"):
    return Subject(
        kind=KIND_STALE_LEASE, identity=f"lease:{slot}", state="STALE-LEASE", holds_slot=True,
        evidence={"slot": slot, "path": f"/slots/{slot}", "record": "none",
                  "lease_todo": "theirWork-07290101", "lease_owner": THEIRS, "tmux": "dt-theirWork",
                  "claimed_at": "2026-07-29T01:01:00Z"},
        note=f"slot {slot} holds a stale lease owned by {THEIRS}; its owner clears it")


DEAD = worker("deadWorker-07300301", "DEAD", slot="ws1", note="launched at 2026-07-30T03:13:00Z and "
              "no session is alive: the work stopped without renaming its folder")
BLOCKED = worker("modalWorker-07300307", "BLOCKED", slot="ws7",
                 note="the pane is waiting on a human: 'ship it'")
HARVESTED = worker("harvestedWork-07300308", "COMPLETE", holds_slot=False, slot="ws9",
                   folder_state="complete", note="the instant folder is `-complete-`; the work is over")


# --- parsing what was actually returned -----------------------------------------------------------


def porcelain_rows(text: str) -> list:
    """Split the machine form into records the way a consumer would: TSV, no commentary."""
    return [line.split("\t") for line in text.splitlines() if line]


def porcelain_dicts(text: str) -> list:
    return [dict(zip(render.BOARD_COLUMNS, fields)) for fields in porcelain_rows(text)]


def human_rows(text: str) -> list:
    """The human form's data rows: indented, columns separated by two or more spaces."""
    return [re.split(r"\s{2,}", line.strip())
            for line in text.splitlines() if line.startswith("  ") and line.strip()]


def pairs(text: str, identities) -> set:
    """(identity, state) from either form, found by MEMBERSHIP rather than by column position — the
    positional version is exactly the model-of-the-output mistake `OBS-62` records."""
    out = set()
    rows = human_rows(text) if not text.count("\t") else porcelain_rows(text)
    for fields in rows:
        found_id = [f for f in fields if f in identities]
        found_state = [f for f in fields if f in STATES]
        if found_id and found_state:
            out.add((found_id[0], found_state[0]))
    return out


class TestBoard(unittest.TestCase):
    def test_the_board_shows_ONLY_slot_holding_subjects(self):
        # FD-4 / operator Q6. One filter deletes four historical defects: the HARVESTED-forever row, the
        # 11 permanently-unclearable legacy rows, the `--base` scoping trap (an instant's own liveness
        # invisible from its own base) and the orphan concept. A small board is one people read.
        legacy = [worker(f"legacy{n}-072{n:05d}", "COMPLETE", holds_slot=False, slot=f"ws{n}",
                         folder_state="complete") for n in range(1, 12)]
        subjects = [DEAD, HARVESTED] + legacy
        for porcelain in (False, True):
            with self.subTest(porcelain=porcelain):
                text = render.board(subjects, porcelain=porcelain)
                self.assertIn(DEAD.identity, text, "the one slot-holding subject is not on the board")
                self.assertNotIn(HARVESTED.identity, text,
                                 "a harvested, slot-released subject is on the board")
                for row in legacy:
                    self.assertNotIn(row.identity, text)
        rows = porcelain_rows(render.board(subjects, porcelain=True))
        self.assertEqual(len(rows), 1, f"the board is not small: {rows}")

    def test_a_dead_session_is_never_rendered_as_parked(self):
        # W2-14 / OBS-57: `board` drew it `🅿 PARKED` and counted it in "N sessions need you" while
        # `health` said DEAD from the same records — and the one that was wrong was the one everybody
        # read. The folder is still `-inflight-`, which is what the PARKED derivation keyed on.
        for porcelain in (False, True):
            with self.subTest(porcelain=porcelain):
                text = render.board([DEAD], porcelain=porcelain)
                self.assertEqual(pairs(text, {DEAD.identity}), {(DEAD.identity, "DEAD")})
                self.assertNotIn("PARKED", text)

    def test_the_needs_you_count_excludes_dead_sessions(self):
        # The banner half of the same defect.
        #
        # This is a tripwire on `ACTIONABLE_STATES`'s membership, not on its size: it exists so that a
        # future widening of the tuple is *noticed here* rather than silently changing what the banner
        # counts. `PARKED` joined `{BLOCKED, IDLE}` for `G-11` (a parked child is waiting on a human's
        # ANSWER, same as `IDLE`'s stalled worker was waiting on a restart) — updated below, not deleted.
        def count(subjects):
            human = render.board(subjects)
            match = re.search(r"(\d+) needs you", human)
            self.assertIsNotNone(match, f"the board has no needs-you banner:\n{human}")
            return int(match.group(1))

        self.assertEqual(count([DEAD]), 0, "a dead session is counted as needing a human")
        self.assertEqual(count([DEAD, BLOCKED]), 1, "the banner does not count an actionable state")
        self.assertEqual(set(ACTIONABLE_STATES), {"BLOCKED", "IDLE", "PARKED"},
                         "the needs-you population is reconcile's, not render's")

    def test_a_stalled_worker_is_counted_as_needing_a_human(self):
        """`FI-14`, reported by a coordinator driving real workers.

        `fleet` DETECTS a stalled worker: `IDLE` is a first-class state on a 30-minute threshold
        (`reconcile.reconcile(..., idle_after_s=1800)`), and it renders exactly the right sentence —
        *"live, but nothing has changed in the instant for more than 1800s and the pane is not working."*
        Then it threw the signal away: `ACTIONABLE_STATES = (BLOCKED,)`, so a worker stopped for over
        half an hour never appeared in the "N needs you" count. The operator was personally noticing
        stalled workers and restarting them — the thing the banner exists to do.

        The inversion is the sharp part, and it is why this is a defect rather than a preference:
        `BLOCKED` IS actionable, and per `FI-9` `BLOCKED` is the state that fires when a human is
        attached and mid-sentence. So the banner called for attention on a human who was already there,
        and stayed silent on a worker that had stopped.
        """
        def count(subjects):
            match = re.search(r"(\d+) needs you", render.board(subjects))
            self.assertIsNotNone(match)
            return int(match.group(1))

        idle = worker("stalled-07310400", "IDLE",
                      note="live, but nothing has changed in the instant for more than 1800s")
        self.assertEqual(count([idle]), 1, "a worker stalled past the idle threshold is not counted")
        # Not a blanket widening: the states that need a REAP or nothing at all must stay out, or the
        # banner goes back to crying for attention on sessions nobody can answer (`W2-14`/`OBS-57`).
        self.assertEqual(count([DEAD, idle, BLOCKED]), 2)
        self.assertEqual(count([worker("running-07310400", "RUNNING")]), 0,
                         "a working worker needs nobody")

    def test_a_terminal_instant_still_holding_a_slot_needs_a_human(self):
        """`FI-12` — the leak that cost 11 slots.

        `fleet complete` renames the folder, and that rename is the WORKER's transition. Releasing the
        slot is a separate, coordinator-side act (`harvest --id`). Until it happens the instant is
        COMPLETE and still holding a workspace — the reporter measured one held for 22 HOURS while every
        row about it said `info`, including its own, which read *"the work is over"*.

        This is not a pure state predicate, which is why `ACTIONABLE_STATES` alone cannot express it: a
        COMPLETE instant that has been harvested holds nothing and needs nobody. The pair
        (terminal, still holding) is the alarm.
        """
        def count(subjects):
            match = re.search(r"(\d+) needs you", render.board(subjects))
            self.assertIsNotNone(match)
            return int(match.group(1))

        stranded = worker("done-07310613", "COMPLETE", holds_slot=True, folder_state="complete",
                          note="the instant folder is `-complete-`; the work is over")
        harvested = worker("done-07310614", "COMPLETE", holds_slot=False, folder_state="complete")
        self.assertEqual(count([stranded]), 1,
                         "a COMPLETE instant still holding a workspace is not counted")
        self.assertEqual(count([harvested]), 0,
                         "a COMPLETE instant that released its slot needs nobody — this must stay quiet")
        self.assertEqual(count([stranded, harvested, BLOCKED]), 2)

    def test_every_row_carries_the_subject_identity_in_the_porcelain_form(self):
        # OBS-62: the shipped assertion anchored to a human summary line and COULD NEVER MATCH.
        subjects = [DEAD, BLOCKED, unknown(), stale_lease(), HARVESTED]
        expected = {s.identity for s in subjects if s.holds_slot}
        text = render.board(subjects, porcelain=True)
        rows = porcelain_rows(text)
        self.assertEqual(len(rows), len(expected), rows)
        self.assertIn("identity", render.BOARD_COLUMNS)
        seen = set()
        for fields in rows:
            hits = [f for f in fields if f in expected]
            self.assertTrue(hits, f"row carries no subject identity: {fields}")
            seen.update(hits)
            self.assertEqual(len(fields), len(render.BOARD_COLUMNS), fields)
        self.assertEqual(seen, expected)
        for row in porcelain_dicts(text):
            self.assertIn(row["identity"], expected)

    def test_the_human_form_and_the_porcelain_form_report_the_same_states(self):
        # Two renderings that can disagree is how three views diverged.
        subjects = [DEAD, BLOCKED, unknown(), stale_lease(), HARVESTED]
        identities = {s.identity for s in subjects}
        human = pairs(render.board(subjects), identities)
        machine = pairs(render.board(subjects, porcelain=True), identities)
        self.assertTrue(machine, "the porcelain form reported no (identity, state) pair at all")
        self.assertEqual(human, machine)

    def test_labels_are_unique_across_the_fleet(self):
        # OBS-32: a 3-char label collapsed two distinct workers, so one's state could be read as the
        # other's. These two share a 10-char prefix and the first 7 characters exactly.
        seen = set()
        first = render.label("fleetInfraOne-07300301", seen)
        second = render.label("fleetInfraTwo-07300302", seen)
        self.assertNotEqual(first, second)

        subjects = [worker("fleetInfraOne-07300301", "RUNNING", slot="ws1"),
                    worker("fleetInfraTwo-07300302", "RUNNING", slot="ws2"),
                    worker("fleetInfraThree-07300303", "RUNNING", slot="ws3")]
        rows = porcelain_dicts(render.board(subjects, porcelain=True))
        labels = [row["label"] for row in rows]
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(set(labels)), 3, f"two subjects share a label: {labels}")
        human_labels = [fields[0] for fields in human_rows(render.board(subjects))]
        self.assertEqual(len(set(human_labels)), 3, f"the human board collapses labels: {human_labels}")

    def test_porcelain_is_parseable_with_stderr_discarded(self):
        # NFR2-7: stdout is machine-parseable data; commentary goes to stderr. Asserted through a real
        # process with stderr thrown away, because that is how a tick consumes it.
        script = (
            "import sys\n"
            "from fleet.render import board\n"
            "from fleet.reconcile import Subject\n"
            "subjects = [Subject(kind='worker', identity='a-07300301', state='DEAD', holds_slot=True,\n"
            "                    evidence={'slot': 'ws1'}, note='a  note\\nwith  breaks'),\n"
            "            Subject(kind='worker', identity='b-07300302', state='BLOCKED', holds_slot=True,\n"
            "                    evidence={'slot': 'ws2'}, note='')]\n"
            "sys.stderr.write('commentary nobody should have to parse\\n')\n"
            "sys.stdout.write(board(subjects, porcelain=True))\n"
        )
        proc = subprocess.run([sys.executable, "-c", script], cwd=str(ROOT),
                              env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"},
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
        self.assertEqual(proc.returncode, 0)
        out = proc.stdout.decode()
        rows = porcelain_rows(out)
        self.assertEqual(len(rows), 2, out)
        for fields in rows:
            self.assertEqual(len(fields), len(render.BOARD_COLUMNS), fields)
        self.assertNotIn("commentary", out)
        for line in out.splitlines():
            self.assertTrue(line.strip(), "a blank line in the machine form")
            self.assertFalse(line.startswith("#"), f"commentary on stdout: {line!r}")

    def test_render_computes_no_state(self):
        # "Nothing else in the package computes a state value" — the property `reconcile` exists to hold.
        # Three views computing their own state from their own inputs is exactly how they came to
        # disagree, and the one that was wrong was the one everybody read. Both fixtures sit in
        # `-inflight-` folders, so any folder-derived state would show up as a state the input never had.
        subjects = [DEAD, BLOCKED]
        allowed = {s.state for s in subjects}
        outputs = [render.board(subjects), render.board(subjects, porcelain=True)]
        for s in subjects:
            outputs += [render.status(s), render.status(s, porcelain=True)]
        blob = "\n".join(outputs)
        for state in STATES:
            if state in allowed:
                continue
            self.assertNotIn(state, blob,
                             f"render produced the state {state!r}, which no input subject had")
        # The vacuity guard comes second on purpose: when it runs first, a mutation that replaces EVERY
        # state fails here instead of on the assertion the case is about, and the kill evidence then
        # reads as "no state was rendered" rather than "render invented RUNNING".
        self.assertTrue(any(state in blob for state in allowed), "no state was rendered at all")

    def test_a_subject_with_no_record_renders_as_an_unknown_not_an_error(self):
        # OBS-48's 8d20h stray must be VISIBLE. It has no record, holds a slot, and is reported so a
        # human can decide — never dropped, and never acted on.
        stray = unknown()
        subjects = [DEAD, stray]
        for porcelain in (False, True):
            with self.subTest(porcelain=porcelain):
                text = render.board(subjects, porcelain=porcelain)
                self.assertIn(stray.identity, text, "a subject with no record was dropped")
                row = [fields for fields in
                       (porcelain_rows(text) if porcelain else human_rows(text))
                       if any(stray.identity == f for f in fields)]
                self.assertEqual(len(row), 1, text)
                self.assertIn("unknown", " ".join(row[0]).lower(),
                              "the row does not label it unknown")
        detail = render.status(stray)
        self.assertIn(stray.identity, detail)
        self.assertIn("none", detail, "the status view does not say the record is absent")


class TestLeaseView(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.pool = Pool(self.tmp / "home", cwd_probe=lambda p: [], alive=lambda n: False)
        for slot in ("ws1", "ws2"):
            (self.tmp / slot).mkdir()
            self.pool.enroll(self.tmp / slot)
        self.pool.claim(todo_id="deadWorker-07300301", tmux="dt-deadWorker", base_instant=OURS,
                        child_instant=OURS + "/child", slot="ws1")

    def test_the_lease_view_is_rendered_here_not_by_pool(self):
        # DA-6 0.3: three views printing their own state from their own inputs is how they diverged in
        # the first place. The lease view lives with the other views, for the same reason
        # `test_render_computes_no_state` exists.
        self.assertTrue(callable(getattr(render, "leases", None)), "render.leases does not exist")
        text = render.leases(self.pool)
        for needle in ("ws1", "ws2", "deadWorker-07300301", OURS):
            self.assertIn(needle, text)
        rows = porcelain_rows(render.leases(self.pool, porcelain=True))
        self.assertEqual(len(rows), 2, rows)
        for fields in rows:
            self.assertEqual(len(fields), len(render.LEASE_COLUMNS), fields)

        tree = ast.parse((SRC / "fleet" / "pool.py").read_text())
        defs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        renderers = [n for n in defs
                     if n in {"render", "board", "status", "leases", "view", "report", "show",
                              "porcelain", "human"}
                     or n.startswith(("render", "format_", "print"))]
        self.assertEqual(renderers, [], f"pool has a renderer: {renderers}")
        prints = [n for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print"]
        self.assertEqual(prints, [], "pool prints")


class TestRoadmapView(unittest.TestCase):
    """Beyond Task 13's ten cases, and deliberately thin: the interface block declares
    `roadmap_view`, and a public view with no assertion behind it is the class this build exists to
    delete. It renders rows `roadmap` already produced and derives nothing."""

    def setUp(self):
        from fleet.roadmap import Milestone, Roadmap
        self.instant = pathlib.Path(tempfile.mkdtemp())
        self.roadmap = Roadmap(self.instant)
        self.roadmap.add(Milestone(id="M-1", title="the join", status="ready", deps=[], evidence=[]))
        self.roadmap.add(Milestone(id="M-2", title="the views", status="blocked", deps=["M-1"],
                                   evidence=[]))

    def test_roadmap_view_renders_every_report_row_in_both_forms(self):
        expected = self.roadmap.report()
        self.assertTrue(expected)
        human = render.roadmap_view(self.roadmap)
        machine = render.roadmap_view(self.roadmap, porcelain=True)
        self.assertEqual(len(porcelain_rows(machine)), len(expected))
        for row in expected:
            self.assertIn(row.subject, machine)
            self.assertIn(row.subject, human)


if __name__ == "__main__":
    unittest.main()
