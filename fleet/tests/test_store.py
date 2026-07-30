import json, pathlib, tempfile, unittest
from fleet.store import SCHEMA_VERSION, Record, Store, Declarations
from fleet.errors import AmbiguousId, BadInput

def rec(**kw):
    base = dict(todo_id="fooBar-07300312", child_instant="/i/00000000-07300312-inflight-append-fooBar",
                base_instant="/i/00000000-07300000-inflight-append-root", slot="ws1", tmux="dt-fooBar",
                profile="/p/worker", golden="/ws0", lineage_base="", title="foo bar",
                dispatched_at="2026-07-30T03:12:00Z")
    base.update(kw)
    return Record(**base)

class TestRecord(unittest.TestCase):
    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp())
        self.store = Store(self.home)

    def test_write_then_read_round_trips_and_stamps_the_version(self):
        self.store.write(rec())
        got = self.store.read("fooBar-07300312")
        self.assertEqual(got.schema_version, SCHEMA_VERSION)
        self.assertEqual(got.slot, "ws1")

    def test_an_unknown_schema_version_is_refused_not_guessed(self):
        # OBS-9 -> W2-5: `launched_at` then `harvested_at` each shipped with no migration path, and 11
        # records ended up demanding attention forever. A version the code does not know is BAD INPUT,
        # not a record to interpret optimistically.
        p = self.home / "records" / "future.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"todo_id": "future", "schema_version": SCHEMA_VERSION + 1}))
        with self.assertRaises(BadInput):
            self.store.read("future")

    def test_read_never_writes(self):
        path = self.store.write(rec())
        before = path.read_bytes(), path.stat().st_mtime_ns
        self.store.read("fooBar-07300312")
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_resolve_id_accepts_a_unique_prefix_and_refuses_ambiguity(self):
        self.store.write(rec(todo_id="alphaOne-07300312"))
        self.store.write(rec(todo_id="alphaTwo-07300312"))
        self.store.write(rec(todo_id="betaOne-07300313"))
        self.assertEqual(self.store.resolve_id("betaOne"), "betaOne-07300313")
        with self.assertRaises(AmbiguousId):
            self.store.resolve_id("alpha")
        with self.assertRaises(BadInput):
            self.store.resolve_id("nosuch")

class TestDeclarations(unittest.TestCase):
    def setUp(self):
        self.instant = pathlib.Path(tempfile.mkdtemp())
        self.d = Declarations(self.instant)

    def test_phase_is_absent_until_declared(self):
        self.assertIsNone(self.d.phase())

    def test_set_phase_returns_what_a_CONSUMER_reads(self):
        # RCF-9: a worker wrote the declaration exactly as the brief worded it and it had NO effect,
        # because a `## ` heading defeated the consumer's regex — and the tool reported success either
        # way. The acknowledgement is the fix: set_phase re-reads through the consumer.
        self.assertEqual(self.d.set_phase("awaiting-ci"), "awaiting-ci")
        self.assertEqual(Declarations(self.instant).phase(), "awaiting-ci")

    def test_clearing_a_phase_is_explicit_and_acknowledged(self):
        self.d.set_phase("awaiting-ci")
        self.assertIsNone(self.d.set_phase(None))
        self.assertIsNone(Declarations(self.instant).phase())

    def test_prose_in_markdown_has_no_effect_on_the_declaration(self):
        # The whole point of FD-3. A HANDOFF that TALKS about a phase — including a correct retraction,
        # which is what would have made a prose lint fire on 5 of 5 live instants — changes nothing.
        (self.instant / "HANDOFF.md").write_text(
            "## Phase: AWAITING-CI\n\n`Phase: AWAITING-CI` was declared and is now REMOVED\n")
        self.assertIsNone(self.d.phase())

    def test_park_and_unpark_round_trip(self):
        self.assertIsNone(self.d.parked())
        self.d.park("merge #441 is yours alone")
        self.assertEqual(Declarations(self.instant).parked(), "merge #441 is yours alone")
        self.d.unpark()
        self.assertIsNone(Declarations(self.instant).parked())

    def test_a_none_marker_in_prose_is_not_a_parked_decision(self):
        # OBS-2/OBS-10/RCF-9: five patches to one regex over `<none>` and its trailing prose, the fifth
        # still wrong. No regex here — the block is not read at all.
        (self.instant / "HANDOFF.md").write_text("## Parked decision\n<none> — nothing has arisen.\n")
        self.assertIsNone(self.d.parked())

    def test_set_phase_return_value_comes_from_the_consumer_not_the_argument(self):
        """Kills mutation M-9 (`set_phase` returns its argument).

        M-9 is an EQUIVALENT MUTANT against the rest of this class: for any `str | None` a JSON round
        trip returns the argument unchanged, so `return phase` and `return <re-read>` are
        observationally identical — no black-box test over the declared signature can separate them.
        The RCF-9 *class* is covered either way, because every other case re-reads through an
        independent consumer. What was uncovered is the PROVENANCE of the return value, and that is
        what this asserts: inject a lossy write channel (the shape of RCF-9's real defect, a `## `
        prefix reaching the store) and require the return value to carry the loss.
        """
        class LossyChannel(Declarations):
            def _save(self, data):
                if "phase" in data:
                    data = dict(data, phase="## " + data["phase"])
                super()._save(data)

        self.assertEqual(LossyChannel(self.instant).set_phase("awaiting-ci"), "## awaiting-ci")
