"""The meta loop's observation mechanism — UC-1: *"meta loop being the observer to optimize away repeated
suboptimal routine."*

Three properties in here were each dropped once already by a design review, and each drop is why the case
below exists rather than a comment:

1. **The registry needs a WRITER, not just contents.** A source that is not on the list cannot be reported
   as silent. `OBS-68` hid 20 issues including a Critical for ~4h and its structure was *invisible because
   UNLISTED*, not invisible because quiet — so the dispatch transaction registers its own base, and a lint
   catches a record written any other way. Left manual, the registry is a hand-maintained copy of a fact the
   record store already holds.
2. **`ids_found` is a separate number from the new-count.** The extractor yields zero ids on a register that
   uses `###` headings or an id like `RI-9a`, and harvest then reports "0 new" — a false pass in the
   mechanism whose whole job is catching false passes. Zero ids from a NON-EMPTY register is an error; zero
   from an EMPTY register is reported and clean. Both halves: turning the second RED reinstates the
   always-red check `OBS-21` deliberately avoided.
3. **`repetitions` flags at TWO**, and every instance is cited. A repetition with no citation is an opinion.
"""
import pathlib
import tempfile
import unittest

from fleet import EXIT_OK
from fleet.errors import BadInput
from fleet.harvest import (EMPTY_REGISTER, NO_ISSUES_FILED, NO_MEMORY, POPULATION, REGISTER_NAME,
                           SOURCE, STALE, UNREADABLE, UNREGISTERED_BASE, VACUOUS, Harvest, Issue,
                           Repetition, Source, VacuousExtraction, exit_code)
from fleet.identity import InstantName
from fleet.layout import INFO, VIOLATION, bootstrap
from fleet.store import Record, Store

BASE = "00000000-07300312-inflight-append-fleetInfraRebuild"
OTHER = "00000000-07300400-inflight-append-otherEffort"

#: The three entries a primed register starts from. `RI-9` is deliberately LAST and never changes: OBS-11's
#: watcher keyed on the last heading, announced `RI-5` three times, and never saw `RI-8`/`RI-9` land.
BASELINE = (("RI-5", "the watcher announced the same id three times"),
            ("RI-8", "a lease outlived the session that held it"),
            ("RI-9", "the pane check read a stale capture"))

INSERTED = ("RI-6", "an inserted issue the last-heading watcher never sees")


class HarvestCase(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.home = self.root / "fleet-home"
        self.base = self.root / BASE
        self.base.mkdir(parents=True)
        self.store = Store(self.home)
        self.at = "2026-07-30T04:00:00Z"
        self.h = Harvest(self.home, now=lambda: self.at)

    # ---- fixture construction ---------------------------------------------------------------------

    def write_register(self, *entries, heading="##", instant=None, preamble=True):
        """An `ISSUES.md` in the shape the real ones have: a title, then one sub-section per issue."""
        path = (instant or self.base) / REGISTER_NAME
        lines = [f"# ISSUES — {path.parent.name}   (durable; append-only)", ""] if preamble else []
        for ident, title in entries:
            lines += [f"{heading} {ident} {title}", "", "Some detail nobody parses.", ""]
        path.write_text("\n".join(lines))
        return path

    def registered(self, instant=None):
        instant = instant or self.base
        return self.h.register(str(instant), str(instant / REGISTER_NAME))

    def record(self, base=None, todo_id="alphaWorker-07300400"):
        return Record(
            todo_id=todo_id, child_instant=str(self.root / OTHER), base_instant=base or str(self.base),
            slot="ws1", tmux=f"dt-{todo_id}", profile="/p/worker", golden="/ws0", lineage_base="",
            title="a dispatched worker", dispatched_at="2026-07-30T03:12:00Z")

    def rows(self, rows, kind):
        return [r for r in rows if r.kind == kind]

    def one(self, rows, kind):
        hits = self.rows(rows, kind)
        self.assertEqual(len(hits), 1, f"expected exactly one {kind} row, got {hits}")
        return hits[0]

    # ---- 1. the registry, and the two halves of its writer ----------------------------------------

    def test_register_is_idempotent(self):
        first = self.registered()
        second = self.registered()
        self.assertEqual([s.base for s in self.h.sources()], [str(self.base)])
        self.assertEqual(first.registered_at, second.registered_at)
        self.assertIsInstance(first, Source)

    def test_the_dispatch_transaction_registers_its_base_automatically(self):
        # Nothing below calls `register`. That is the whole assertion: rev 1 specified the registry's
        # CONTENTS and not its writer, and a source nobody put on the list cannot be reported as silent.
        self.assertEqual(self.h.sources(), [])
        rec = self.record()
        self.h.record_dispatch(self.store, rec)

        self.assertEqual([s.base for s in self.h.sources()], [str(self.base)],
                         "the dispatch transaction did not register its own base")
        self.assertEqual(self.h.sources()[0].issues_path, str(self.base / REGISTER_NAME))
        # One transaction, not a registration with a lost record: the record store holds it too.
        self.assertEqual(self.store.read(rec.todo_id).base_instant, str(self.base))
        # And the other half agrees — the lint that exists for hand-written records has nothing to say.
        self.assertEqual([v for v in self.h.lint(self.store) if v.rule == UNREGISTERED_BASE], [])

    def test_a_lint_flags_a_record_whose_base_is_not_registered(self):
        # A record written straight to the store, bypassing the transaction. This is exactly OBS-68's
        # shape: the effort is being worked and nothing is watching its register.
        self.store.write(self.record())
        found = [v for v in self.h.lint(self.store) if v.rule == UNREGISTERED_BASE]
        self.assertEqual(len(found), 1, "an unregistered base produced no violation")
        self.assertEqual(found[0].severity, VIOLATION)
        self.assertIn(str(self.base), found[0].path + found[0].detail,
                      "the violation does not name the base it is about")
        # The alarm names a clearing action, so perform it and assert it clears (§9).
        self.registered()
        self.assertEqual([v for v in self.h.lint(self.store) if v.rule == UNREGISTERED_BASE], [])
        self.assertTrue([v for v in self.h.lint(self.store) if v.rule == POPULATION],
                        "a lint with no population row narrows its scope silently (OBS-49)")

    # ---- 2. the report: silence is a result, and it is reported ------------------------------------

    def test_a_source_that_produced_nothing_is_reported_as_such(self):
        # "Even a perfectly disciplined tick, run every ten minutes, would have seen nothing." A source
        # that produced nothing is the observation, so it is a row and not an omission.
        self.write_register(*BASELINE)
        src = self.registered()
        self.h.prime(src)
        rows = self.h.report()
        row = self.one(rows, SOURCE)
        self.assertEqual(row.subject, str(self.base))
        self.assertEqual(row.new_count, 0)
        self.assertEqual(row.ids_found, 3)
        self.assertEqual(row.severity, INFO, "a quiet source is information, not an alarm")
        self.assertEqual(exit_code(rows), EXIT_OK)

    def test_prime_records_and_reports_its_count_and_reports_no_issues(self):
        # "A silent reset is worse." Prime says how much memory it just wrote, and announces nothing:
        # a prime that reported its ids would be indistinguishable from a tick that found them.
        self.write_register(*BASELINE)
        src = self.registered()
        recorded = self.h.prime(src)
        self.assertEqual(recorded, 3)
        self.assertIsInstance(recorded, int)
        self.assertNotIsInstance(recorded, (list, tuple))
        self.assertEqual([(i.id, i.title) for i in self.h.seen(src)], list(BASELINE))
        # Nothing was announced: the very next tick has zero new, because prime RECORDED rather than read.
        self.assertEqual(self.h.new_issues(src), [])

    def test_new_issues_diffs_the_SET_of_ids_not_a_count(self):
        # OBS-11: a register kept in numeric order grows by one while the LAST heading is unchanged.
        self.write_register(*BASELINE)
        src = self.registered()
        self.assertEqual(self.h.prime(src), 3)
        grown = (BASELINE[0], INSERTED, BASELINE[1], BASELINE[2])
        self.write_register(*grown)
        new = self.h.new_issues(src)
        self.assertEqual([(i.id, i.title) for i in new], [INSERTED],
                         "the diff followed the tail of the file instead of the set of ids")
        self.assertIsInstance(new[0], Issue)
        self.assertEqual(self.h.new_issues(src), [], "the same insertion was announced twice")

    def test_a_renumbered_prefix_is_not_N_false_alarms(self):
        entries = tuple((f"I-{n}", f"issue number {n} of the register") for n in range(1, 8))
        self.write_register(*entries)
        src = self.registered()
        self.assertEqual(self.h.prime(src), 7)
        self.write_register(*[(f"O{i}", t) for i, t in entries])
        self.assertEqual(self.h.new_issues(src), [],
                         "renumbering the register's prefix was reported as 7 new issues")

    def test_a_harvest_that_records_nothing_warns_loudly(self):
        # RI-28..31 were read with NO state file, so the diff had no memory of them — OBS-16 recurring on
        # the first tick of the loop that wrote the lesson. A tick with no memory is loud, then records.
        self.write_register(*BASELINE)
        src = self.registered()
        rows = self.h.report()
        warning = self.one(rows, NO_MEMORY)
        self.assertEqual(warning.severity, VIOLATION)
        self.assertEqual(warning.subject, str(self.base))
        self.assertNotEqual(exit_code(rows), EXIT_OK, "a memoryless harvest exited clean")
        # ...and it did not record nothing: the memory it lacked now exists.
        self.assertEqual([(i.id, i.title) for i in self.h.seen(src)], list(BASELINE))
        again = self.h.report()
        self.assertEqual(self.rows(again, NO_MEMORY), [])
        self.assertEqual(exit_code(again), EXIT_OK)

    # ---- 3. the population, and the two halves of the vacuity guard -------------------------------

    def test_ids_found_is_reported_separately_from_the_new_count(self):
        self.write_register(*BASELINE)
        src = self.registered()
        self.h.prime(src)
        self.write_register(*(BASELINE + (("RI-10", "a tenth issue"), ("RI-11", "an eleventh issue"))))
        rows = self.h.report()
        row = self.one(rows, SOURCE)
        self.assertEqual(row.ids_found, 5, "the population was reported as the new-count")
        self.assertEqual(row.new_count, 2)
        self.assertEqual(self.h.ids_found(src), 5,
                         "ids_found collapsed into the diff and can no longer detect a dead extractor")

    def test_zero_ids_from_a_NON_EMPTY_register_is_an_error(self):
        # First: the shapes the regex is accused of missing must actually parse, or this guard is only
        # testing a broken extractor. `###` headings and an id like `RI-9a`.
        self.write_register(("RI-9a", "an id with a letter suffix"), ("W2-14", "a two-part prefix"),
                            heading="###")
        src = self.registered()
        self.assertEqual(self.h.ids_found(src), 2)

        # Now a register with content and no ids at all: RCF-10's shape inside the mechanism whose job is
        # to catch it. Vacuous because the extractor failed is not "0 new".
        (self.base / REGISTER_NAME).write_text(
            "# ISSUES\n\n## Symptom\n\nsomething broke and nobody wrote an id for it\n\n## Root cause\n")
        with self.assertRaises(VacuousExtraction):
            self.h.ids_found(src)
        with self.assertRaises(VacuousExtraction):
            self.h.new_issues(src)
        rows = self.h.report()
        vacuous = self.one(rows, VACUOUS)
        self.assertEqual(vacuous.severity, VIOLATION)
        self.assertNotEqual(exit_code(rows), EXIT_OK, "a vacuous extraction reported a clean harvest")

    def test_zero_ids_from_an_EMPTY_register_is_reported_not_an_error(self):
        # "Vacuous because the extractor failed" is not "legitimately empty". Turning this one RED
        # reinstates the always-red check OBS-21 deliberately avoided.
        self.write_register(preamble=False)
        src = self.registered()
        self.assertEqual(self.h.prime(src), 0)
        self.assertEqual(self.h.ids_found(src), 0)
        rows = self.h.report()
        self.assertEqual(self.one(rows, SOURCE).ids_found, 0)
        self.assertEqual(self.one(rows, EMPTY_REGISTER).severity, INFO)
        self.assertEqual(self.rows(rows, VACUOUS), [])
        self.assertEqual(exit_code(rows), EXIT_OK, "an empty register was reported as a failure")

    def test_a_register_holding_only_the_layout_seed_is_no_issues_filed_yet(self):
        # FI-18, the emergent defect: `layout._seed` writes a header, `init` registers its own base, and
        # the vacuity guard is right — composed, a freshly `init`-ed effort was a violation on EVERY tick
        # until somebody filed its first issue. That is the fifth unclearable alarm and it is the exact
        # always-red check OBS-21 avoided. An empty-of-ISSUES register is not a broken extractor.
        name = InstantName.parse(self.base.name)
        bootstrap(self.base, name)
        src = self.registered()
        self.assertTrue((self.base / REGISTER_NAME).read_text().strip(),
                        "the seed wrote nothing, so this case would pass through the empty-register arm")

        self.assertEqual(self.h.ids_found(src), 0, "the layout seed's own header read as a dead extractor")
        rows = self.h.report()
        self.assertEqual(self.rows(rows, VACUOUS), [], "a freshly init-ed effort is RED on its first tick")
        filed = self.one(rows, NO_ISSUES_FILED)
        self.assertEqual(filed.severity, INFO)
        self.assertIn("no issues filed yet", filed.detail)
        self.assertEqual(self.one(rows, SOURCE).ids_found, 0)
        # The one violation left is the memoryless first tick, which clears by definition on the next one.
        self.assertEqual({r.kind for r in rows if r.severity == VIOLATION}, {NO_MEMORY})
        self.assertEqual(exit_code(self.h.report()), EXIT_OK,
                         "a freshly init-ed effort is still RED on the tick after its first")

    def test_a_POPULATED_but_unparseable_register_still_raises_beside_the_seed_header(self):
        # The vacuity guard is load-bearing and its absence is what made a coverage claim vacuous across
        # every harvest of a real effort (RCF-10). So the seed's shape is the ONLY thing excused: the same
        # seed header over entries the extractor cannot parse is a blind extractor, and it still raises.
        name = InstantName.parse(self.base.name)
        bootstrap(self.base, name)
        register = self.base / REGISTER_NAME
        register.write_text(register.read_text()
                           + "\n- FI-9 an issue filed as a BULLET, which the extractor cannot see\n"
                             "- FI-10 a second one, so the register is genuinely populated\n")
        src = self.registered()
        with self.assertRaises(VacuousExtraction):
            self.h.ids_found(src)
        with self.assertRaises(VacuousExtraction):
            self.h.new_issues(src)
        rows = self.h.report()
        self.assertEqual(self.one(rows, VACUOUS).severity, VIOLATION)
        self.assertEqual(self.rows(rows, NO_ISSUES_FILED), [],
                         "a populated register reported itself as having nothing filed yet")
        self.assertNotEqual(exit_code(rows), EXIT_OK)

    # ---- 4. the cadence trigger --------------------------------------------------------------------

    def test_stale_returns_a_source_whose_last_run_is_older_than_the_window_while_live_work_exists(self):
        self.write_register(*BASELINE)
        old = self.registered()
        self.h.prime(old)                                    # last_run = 04:00:00
        self.at = "2026-07-30T05:00:00Z"
        fresh_dir = self.root / OTHER
        fresh_dir.mkdir(exist_ok=True)
        self.write_register(*BASELINE, instant=fresh_dir)
        fresh = self.registered(fresh_dir)
        self.h.prime(fresh)                                  # last_run = 05:00:00

        stale = self.h.stale(now="2026-07-30T05:00:01Z", max_age_s=1800, live_work=True)
        self.assertEqual([s.base for s in stale], [old.base])
        rows = self.h.report(now="2026-07-30T05:00:01Z", max_age_s=1800, live_work=True)
        row = self.one(rows, STALE)
        self.assertEqual(row.subject, old.base)
        self.assertTrue(row.clears_when and row.clears_who, "a cadence alarm with no clearing actor")

    def test_stale_returns_nothing_when_there_is_no_live_work(self):
        # An alarm nobody can act on trains people to ignore it.
        self.write_register(*BASELINE)
        src = self.registered()
        self.h.prime(src)
        self.assertEqual(self.h.stale(now="2026-07-31T04:00:00Z", max_age_s=1800, live_work=False), [])
        rows = self.h.report(now="2026-07-31T04:00:00Z", max_age_s=1800, live_work=False)
        self.assertEqual(self.rows(rows, STALE), [])

    # ---- 5. the identity a rename cannot break, and the source that degrades -----------------------

    def test_a_register_whose_base_was_RENAMED_is_still_harvested(self):
        # FI-17: `register` keys sources by a rename-tolerant `_base_key` and stores the path LITERALLY,
        # and every base eventually renames (`abort`/`complete` are the rename). OI-16's shape surviving in
        # the one module that never adopted the resolver — `reconcile` resolves, this did not.
        self.write_register(*BASELINE)
        src = self.registered()
        self.assertEqual(self.h.prime(src), 3)

        renamed = self.base.with_name(self.base.name.replace("-inflight-", "-complete-"))
        self.base.rename(renamed)
        self.write_register(*(BASELINE + (("RI-12", "an issue filed after the effort completed"),)),
                            instant=renamed)

        self.assertEqual(self.h.ids_found(src), 4,
                         "the register was read at its recorded path and the rename was not followed")
        self.assertEqual([i.id for i in self.h.new_issues(src)], ["RI-12"])
        rows = self.h.report()
        self.assertEqual(self.rows(rows, UNREADABLE), [], "a resolvable rename was reported as unreadable")
        self.assertEqual(self.one(rows, SOURCE).ids_found, 4)
        self.assertEqual(exit_code(rows), EXIT_OK)

    def test_one_unreadable_source_is_a_ROW_and_does_not_take_the_tick_down(self):
        # The more important half, because the next unreadable cause will not be a rename. One source that
        # cannot be read degrades to a reported row; the tick still covers every other source and still
        # states the population it examined (OBS-49).
        self.write_register(*BASELINE)
        healthy = self.registered()
        self.h.prime(healthy)

        gone = self.root / OTHER
        gone.mkdir()
        self.write_register(*BASELINE, instant=gone)
        broken = self.registered(gone)
        (gone / REGISTER_NAME).unlink()
        gone.rmdir()                     # unresolvable: not a rename, just absent

        rows = self.h.report()           # must NOT raise: exiting here kills the WHOLE tick
        row = self.one(rows, UNREADABLE)
        self.assertEqual(row.subject, broken.base)
        self.assertEqual(row.severity, VIOLATION)
        self.assertTrue(row.clears_when and row.clears_who,
                        "an unreadable source is an alarm with no clearing actor (§9)")
        self.assertIn(str(gone / REGISTER_NAME), row.detail)
        self.assertEqual([r.subject for r in self.rows(rows, SOURCE)], [healthy.base],
                         "the healthy source was not harvested: one bad source took the tick down")
        self.assertTrue(self.rows(rows, POPULATION), "the tick reported no population")
        self.assertNotEqual(exit_code(rows), EXIT_OK, "an unreadable source reported a clean tick")

    # ---- 6. repetition — UC-1's actual ask --------------------------------------------------------

    def test_repetitions_flag_at_TWO(self):
        # "Two instances is a pattern; making the brief demand it means review no longer has to be the
        # first line of defence." Three is a threshold that only ever fires after the third time.
        corpus = {
            "ISSUES.md#FI-3": ("## FI-3 the prescribed re-derivation command is never executed\n"
                               "the recipe was cited in the handoff and never run\n"),
            "w2/ISSUES.md#W2-9": ("## W2-9 The prescribed re-derivation command is never executed\n"
                                  "same shape, a second effort, nine days later\n"),
            "DECISIONS.md#FD-4": "## FD-4 a small board is one that people actually read\n",
        }
        reps = self.h.repetitions(corpus)
        self.assertEqual([(r.subject, r.count) for r in reps],
                         [("the prescribed re-derivation command is never executed", 2)])
        self.assertIsInstance(reps[0], Repetition)

    def test_repetitions_name_where_each_instance_was_seen(self):
        corpus = {
            "ISSUES.md": ("## FI-3 the prescribed re-derivation command is never executed\n"
                          "unrelated line about something else entirely\n"
                          "## FI-9 The prescribed re-derivation command is never executed\n"),
            "w2/ISSUES.md": "## W2-9 the prescribed re-derivation command is never executed\n",
        }
        reps = self.h.repetitions(corpus)
        rep = reps[0]
        self.assertEqual(rep.count, 3)
        self.assertTrue(rep.where, "a repetition with no citation is an opinion")
        self.assertEqual(len(rep.where), rep.count)
        self.assertEqual(len(set(rep.where)), 3, "two instances were cited to the same place")
        self.assertEqual({w.split(":")[0] for w in rep.where}, {"ISSUES.md", "w2/ISSUES.md"})
        for where in rep.where:
            self.assertRegex(where, r":\d+$", "a citation with no line is not a citation")


class HarvestRefusalCase(unittest.TestCase):
    """The doors that stay shut, so the registry stays the list of record."""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.h = Harvest(self.root / "home")

    def test_an_unregistered_source_cannot_be_harvested(self):
        src = Source(base="/nowhere/instant", issues_path="/nowhere/instant/ISSUES.md",
                     registered_at="2026-07-30T04:00:00Z")
        with self.assertRaises(BadInput):
            self.h.new_issues(src)


if __name__ == "__main__":
    unittest.main()
