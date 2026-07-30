# tests/test_identity.py
import pathlib, tempfile, unittest
from fleet.identity import InstantName, camel, resolve, ROOT_BASE
from fleet.errors import InstantNameError, AmbiguousId

GOOD = "00000000-07300312-inflight-append-fleetInfraRebuild"

class TestParse(unittest.TestCase):
    def test_round_trip(self):
        n = InstantName.parse(GOOD)
        self.assertEqual((n.base, n.curr, n.state, n.optype, n.name),
                         (ROOT_BASE, "07300312", "inflight", "append", "fleetInfraRebuild"))
        self.assertEqual(n.format(), GOOD)

    def test_every_legal_state_and_optype(self):
        for state in ("inflight", "complete", "abort"):
            for optype in ("append", "compact"):
                s = f"00000000-07300312-{state}-{optype}-x"
                self.assertEqual(InstantName.parse(s).format(), s)

    def test_main_is_refused(self):
        # FD-2: `main` is deprecated. The old grammar allowed it and two parsers hardcoded \d{8}-\d{8},
        # so every root instant was unresolvable through a rename (OI-16). Refusing it deletes the class.
        with self.assertRaises(InstantNameError):
            InstantName.parse("main-07300312-inflight-append-x")

    def test_four_digit_base_is_refused(self):
        # A live instant with a 4-digit base exists in the old tree; lint accepted it and the resolver
        # rejected it. The producer must validate the field domain (third instance of OI-16's class).
        with self.assertRaises(InstantNameError):
            InstantName.parse("0715-07152254-complete-append-x")

    def test_malformed_fields_are_refused(self):
        for bad in ("00000000-07300312-running-append-x",     # state not in domain
                    "00000000-07300312-inflight-merge-x",     # optype not in domain
                    "00000000-07300312-inflight-append-With-Dash",  # name must be dashless
                    "00000000-07300312-inflight-append-9lead", # name must start lowercase alpha
                    "00000000-07300312-inflight-append",       # four fields
                    "00000000-07300312-inflight-append-a-b"):  # six fields
            with self.subTest(bad=bad):
                with self.assertRaises(InstantNameError):
                    InstantName.parse(bad)

class TestStableKey(unittest.TestCase):
    def test_state_is_omitted_so_a_rename_does_not_orphan_derived_state(self):
        a = InstantName.parse(GOOD)
        b = a.with_state("complete")
        self.assertEqual(a.stable_key(), b.stable_key())
        self.assertNotEqual(a.format(), b.format())

    def test_same_minute_siblings_have_distinct_stable_keys(self):
        # OBS-14: r2 and r3 were BOTH 07270639-07270656. base-curr is not a key; the whole name minus
        # state is. This test is the one that finally failed when made adversarial.
        x = InstantName.parse("07270639-07270656-complete-append-r2Velox")
        y = InstantName.parse("07270639-07270656-complete-append-r3Incon")
        self.assertNotEqual(x.stable_key(), y.stable_key())

class TestCamel(unittest.TestCase):
    def test_titles_become_dashless_camel(self):
        self.assertEqual(camel("Close ANSI gap: int4 overflow"), "closeAnsiGapInt4Overflow")
        self.assertEqual(camel("  multiple   spaces "), "multipleSpaces")
    def test_result_always_parses_as_a_name_field(self):
        for title in ("a", "9 leading digit", "--- ---", "ALLCAPS"):
            with self.subTest(title=title):
                s = f"00000000-07300312-inflight-append-{camel(title)}"
                InstantName.parse(s)   # must not raise

class TestResolve(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
    def test_existing_path_returns_itself(self):
        p = self.tmp / GOOD; p.mkdir()
        self.assertEqual(resolve(p), p)
    def test_follows_a_state_rename(self):
        renamed = self.tmp / InstantName.parse(GOOD).with_state("complete").format()
        renamed.mkdir()
        self.assertEqual(resolve(self.tmp / GOOD), renamed)
    def test_missing_returns_none(self):
        self.assertIsNone(resolve(self.tmp / GOOD))
    def test_adversarial_sibling_is_never_chosen(self):
        # `abort` sorts before `complete`. Keying on base-curr alone would resolve to the SIBLING —
        # the exact bug OBS-14 records, which passed every test until made adversarial.
        (self.tmp / "07270639-07270656-abort-append-r3Incon").mkdir()
        target = self.tmp / "07270639-07270656-complete-append-r2Velox"
        target.mkdir()
        self.assertEqual(resolve(self.tmp / "07270639-07270656-inflight-append-r2Velox"), target)
    def test_ambiguity_is_refused_not_resolved(self):
        for st in ("complete", "abort"):
            (self.tmp / f"00000000-07300312-{st}-append-fleetInfraRebuild").mkdir()
        with self.assertRaises(AmbiguousId):
            resolve(self.tmp / GOOD)
