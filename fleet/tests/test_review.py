"""Structured review rounds in, markdown out — and the markdown is never read back.

Every case below names the finding it encodes, because the case list is the hard part and a weaker
assertion than the case intends is how each of these shipped the first time.

The one property this module exists for: **the ledger is `.fleet/review.json`; `REVIEW.md` is a view.**
In the predecessor the markdown was the *input*, and a regex over idiomatic markdown blocked two
genuinely-READY workers in a row (`OBS-15`, `OBS-19`) — one for writing its verdict in bold, one for
disambiguating a two-round summary heading. That is the worst direction for a gate to be wrong in: it
blocks correct work, and the message blamed a MISSING line, so the reader went hunting for the wrong
problem. `test_gate_never_reads_review_md` is what makes that class unreachable rather than patched, and
it is asserted three ways — the file deleted, the file contradicting the ledger, and the file replaced by
a DIRECTORY so that any read at all raises.

Nothing here writes outside a fresh temporary directory, and the only clock is injected, so `render()`
is byte-comparable across calls without a freeze.
"""
import pathlib
import shutil
import tempfile
import unittest

from fleet import EXIT_ATTENTION, EXIT_BAD_INPUT, EXIT_OK
from fleet.errors import BadInput
from fleet.guards import Verdict
from fleet.review import (
    GUARD_HARVEST,
    GUARD_SCOPE,
    GUARD_UNDECIDABLE,
    GUARD_VERDICT,
    Finding,
    Review,
    Round,
    exit_code_for,
)

#: The injected clock. One tick per recorded round, so the ledger — and therefore the rendered view —
#: is identical on every run of the suite.
TICKS = [f"2026-07-30T0{n}:00:00Z" for n in range(1, 9)]


def finding(id_="F1", severity="Important", status="open",
            location="src/fleet/review.py:12",
            text="the gate parsed REVIEW.md for its verdict",
            action="read `.fleet/review.json` instead; the markdown is a view") -> Finding:
    return Finding(id=id_, severity=severity, status=status, location=location,
                   finding=text, action=action)


class ReviewCase(unittest.TestCase):
    """One temporary instants directory per test, with one grammatical `-inflight-` instant in it."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.instants = self.tmp / "instants"
        self.instants.mkdir()
        self.instant = self.instants / "00000000-07300312-inflight-append-someWorker"
        self.instant.mkdir()
        self.ticks = iter(TICKS)
        self._minted = 0

    def other_instant(self) -> pathlib.Path:
        """A second, independently-named instant. Two `Review`s over ONE folder share ONE ledger — which
        is correct, and is why every "and now a different review" case needs its own folder."""
        self._minted += 1
        path = self.instants / f"00000000-0730031{self._minted}-inflight-append-otherWorker"
        path.mkdir()
        return path

    def review(self, instant=None) -> Review:
        return Review(instant if instant is not None else self.instant, now=lambda: next(self.ticks))

    def ready(self, instant=None) -> Review:
        """A review whose single round is an evidenced READY — the ordinary happy ledger."""
        rev = self.review(instant)
        rev.add_round("all", "READY", [finding("F1", "Nit", "applied",
                                               text="a stray blank line",
                                               action="removed")])
        return rev


# --- the gate's decision table ---------------------------------------------------------------------


class TestGateVerdicts(ReviewCase):
    def test_a_ready_round_passes_the_gate(self):
        verdict = self.ready().gate()
        self.assertIsInstance(verdict, Verdict)          # ONE shape for "may I proceed" (guards.Verdict)
        self.assertTrue(verdict.allowed, verdict.reason)
        self.assertEqual(exit_code_for(verdict), EXIT_OK)

    def test_ready_with_fixes_and_zero_open_critical_or_important_passes(self):
        # The bar, exactly: READY-WITH-FIXES is a PASS when nothing blocking is still open. Minor and
        # Nit findings may sit open all day; that is what makes them Minor and Nit.
        rev = self.review()
        rev.add_round("all", "READY-WITH-FIXES", [
            finding("F1", "Critical", "applied"),
            finding("F2", "Important", "applied"),
            finding("F3", "Minor", "open"),
            finding("F4", "Nit", "open"),
        ])
        verdict = rev.gate()
        self.assertTrue(verdict.allowed, verdict.reason)
        self.assertEqual(exit_code_for(verdict), EXIT_OK)

    def test_ready_with_fixes_and_an_open_important_fails(self):
        rev = self.review()
        rev.add_round("all", "READY-WITH-FIXES", [
            finding("F1", "Important", "open"),
            finding("F2", "Critical", "applied"),
        ])
        verdict = rev.gate()
        self.assertFalse(verdict.allowed)
        self.assertIn("1 open blocking", verdict.reason)      # the reason names the COUNT
        self.assertIn("F1", verdict.reason)                   # and which one
        self.assertIn("Important", verdict.reason)
        self.assertEqual(verdict.guard, GUARD_VERDICT)
        self.assertEqual(exit_code_for(verdict), EXIT_ATTENTION)

    def test_not_ready_fails(self):
        rev = self.review()
        rev.add_round("all", "NOT-READY", [finding("F1", "Critical", "open")])
        verdict = rev.gate()
        self.assertFalse(verdict.allowed)
        self.assertIn("NOT-READY", verdict.reason)
        self.assertEqual(verdict.guard, GUARD_VERDICT)
        self.assertEqual(exit_code_for(verdict), EXIT_ATTENTION)
        self.assertTrue(verdict.clears_when, "a refusal with no clearing condition is not actionable")
        self.assertTrue(verdict.clears_who)

    def test_no_round_at_all_is_UNDECIDABLE_and_fails_closed(self):
        # exit 2 vs 1. "Cannot decide" must not read as "decided no" — they send the reader to two
        # different problems, and sending a reader to the wrong problem is the whole cost.
        empty = self.review().gate()
        self.assertFalse(empty.allowed, "an undecidable gate must fail CLOSED")

        decided_no = self.review(self.other_instant())
        decided_no.add_round("all", "NOT-READY", [finding("F1", "Critical", "open")])
        decided_no = decided_no.gate()

        # Machine-readable first: the distinction cannot rest on wording, or a caller re-derives it by
        # grepping prose — which is the very defect family this module exists to close.
        self.assertNotEqual(empty.guard, decided_no.guard)
        self.assertEqual(empty.guard, GUARD_UNDECIDABLE)
        self.assertEqual(exit_code_for(empty), EXIT_BAD_INPUT)          # 2
        self.assertEqual(exit_code_for(decided_no), EXIT_ATTENTION)     # 1
        self.assertNotEqual(exit_code_for(empty), exit_code_for(decided_no))

        # And the prose agrees with the code, because a human reads this line.
        lowered = empty.reason.lower()
        self.assertIn("undecidable", lowered)
        self.assertIn("no review round", lowered)
        self.assertNotIn("not-ready", lowered)
        self.assertTrue(empty.clears_when)
        self.assertTrue(empty.clears_who)

    def test_the_newest_round_governs_the_verdict(self):
        rev = self.review()
        rev.add_round("all", "NOT-READY", [finding("F1", "Critical", "open")])
        rev.add_round("all", "READY", [finding("F1", "Critical", "applied")])
        verdict = rev.gate()
        self.assertTrue(verdict.allowed, verdict.reason)
        self.assertIn("round 2", verdict.reason)

        back = self.review(self.other_instant())
        back.add_round("all", "READY", [finding("F1", "Nit", "applied")])
        back.add_round("all", "NOT-READY", [finding("F2", "Critical", "open")])
        later = back.gate()
        self.assertFalse(later.allowed)
        self.assertIn("round 2", later.reason)

    def test_a_later_round_marking_a_finding_applied_clears_it(self):
        # Beyond the plan's table, and required by the rule above: open-ness is the LATEST status
        # recorded for a finding id, not the first. Without this, a round-1 Critical could never be
        # cleared except by a reviewer who never raised it.
        rev = self.review()
        rev.add_round("all", "NOT-READY", [finding("F1", "Critical", "open")])
        self.assertFalse(rev.gate().allowed)
        rev.add_round("code", "READY-WITH-FIXES", [finding("F1", "Critical", "applied")])
        self.assertTrue(rev.gate().allowed, rev.gate().reason)
        self.assertEqual([f.id for f in rev.open_blocking()], [])


# --- scope accumulation ----------------------------------------------------------------------------


class TestScopes(ReviewCase):
    def test_scopes_accumulate_ACROSS_rounds(self):
        # OBS-30. Judging only the newest round would have REJECTED a correctly-reviewed worker: it was
        # fully reviewed in round 1 and re-checked narrowly in round 2. Found by pointing the tool at
        # production instants *after* every fixture passed, which is why fixtures are not enough.
        rev = self.review()
        rev.add_round("all", "READY-WITH-FIXES", [finding("F1", "Important", "applied")])
        rev.add_round("code", "READY", [finding("F2", "Nit", "applied")])

        self.assertEqual(rev.scopes_covered() & {"all", "code"}, {"all", "code"})
        verdict = rev.gate(require_scope="all")
        self.assertTrue(verdict.allowed, verdict.reason)

        # The control, so the assertion above is not vacuous: a review that really only ever looked at
        # the code does NOT satisfy require_scope="all".
        narrow = self.review(self.other_instant())
        narrow.add_round("code", "READY", [finding("F1", "Nit", "applied")])
        refused = narrow.gate(require_scope="all")
        self.assertFalse(refused.allowed)
        self.assertEqual(refused.guard, GUARD_SCOPE)
        self.assertIn("all", refused.reason)

    def test_three_narrow_rounds_together_cover_all(self):
        # Beyond the plan's table; the same OBS-30 property from the other side. Three single-scope
        # rounds have collectively reviewed everything, and telling that worker it was never fully
        # reviewed is the same false refusal.
        rev = self.review()
        rev.add_round("format", "READY", [finding("F1", "Nit", "applied")])
        rev.add_round("alignment", "READY", [finding("F2", "Nit", "applied")])
        rev.add_round("code", "READY", [finding("F3", "Nit", "applied")])
        self.assertIn("all", rev.scopes_covered())
        self.assertTrue(rev.gate(require_scope="all").allowed)

    def test_an_unknown_scope_or_verdict_is_refused_as_BadInput(self):
        # Beyond the plan's table. FD-1: non-conforming input is refused, never coerced — a scope
        # nobody defined must not silently satisfy or silently fail a gate.
        rev = self.review()
        with self.assertRaises(BadInput):
            rev.add_round("everything", "READY", [])
        with self.assertRaises(BadInput):
            rev.add_round("all", "ready", [])
        with self.assertRaises(BadInput):
            Finding(id="F1", severity="Blocker", status="open", location="x", finding="y", action="z")
        with self.assertRaises(BadInput):
            Finding(id="F1", severity="Critical", status="open", location="x", finding="y", action="")
        rev.add_round("all", "READY", [finding()])
        with self.assertRaises(BadInput):
            rev.gate(require_scope="everything")


# --- harvest: two completion signals ---------------------------------------------------------------


class TestHarvest(ReviewCase):
    def test_harvest_additionally_requires_the_folder_rename(self):
        # TWO signals, not one: "a report file is not a completion signal". The worker's own rename is
        # the second, and it is the one the worker cannot fake by writing a document.
        rev = self.ready()
        self.assertTrue(rev.gate().allowed, "the review itself is READY")

        refused = rev.gate(harvest=True)
        self.assertFalse(refused.allowed)
        self.assertEqual(refused.guard, GUARD_HARVEST)
        self.assertIn("inflight", refused.reason)
        self.assertTrue(refused.clears_when)
        self.assertTrue(refused.clears_who)

        # Now the worker does the thing the refusal asks for. The Review still holds the PRE-rename
        # path — following the rename is the point (a recorded path always predates it).
        renamed = self.instants / "00000000-07300312-complete-append-someWorker"
        self.instant.rename(renamed)
        self.assertFalse(self.instant.exists())
        cleared = rev.gate(harvest=True)
        self.assertTrue(cleared.allowed, cleared.reason)


# --- render: the view, and the ONLY writer of it ---------------------------------------------------


class TestRender(ReviewCase):
    def test_render_produces_markdown_and_is_byte_reproducible(self):
        rev = self.review()
        rev.add_round("all", "READY-WITH-FIXES", [
            finding("F1", "Critical", "applied"),
            finding("F2", "Important", "applied", text="a table cell with a | pipe in it",
                    action="escape it"),
        ])
        rev.add_round("code", "READY", [finding("F3", "Minor", "open")])

        path = self.instant / "REVIEW.md"
        first = rev.render()
        first_bytes = path.read_bytes()
        second = rev.render()
        second_bytes = path.read_bytes()

        self.assertEqual(first, second)
        self.assertEqual(first_bytes, second_bytes)          # kills "append instead of regenerate"
        self.assertEqual(first, path.read_text(encoding="utf-8"),
                         "the returned view and the file on disk are the same view")
        self.assertIn("# REVIEW", first)
        self.assertIn("Round 1", first)
        self.assertIn("Round 2", first)
        self.assertIn("F3", first)

    def test_render_is_the_ONLY_writer_of_review_md(self):
        rev = self.review()
        rev.add_round("all", "READY", [finding("F1", "Nit", "applied")])
        path = self.instant / "REVIEW.md"
        canonical = rev.render()
        before = rev.gate()

        # The hand edit is the exact shape that blocked two READY workers: a verdict written in bold,
        # and a summary heading disambiguated by a human being helpful.
        path.write_text("# Review of this instant\n\n**Verdict: NOT-READY**\n\n"
                        "## Round 2 of 2 (final) — summary\n", encoding="utf-8")

        after = rev.gate()
        self.assertEqual((after.allowed, after.guard, after.reason),
                         (before.allowed, before.guard, before.reason),
                         "a hand edit to a VIEW cannot change a decision")
        self.assertTrue(after.allowed)

        restored = rev.render()
        self.assertEqual(restored, canonical)
        self.assertEqual(path.read_text(encoding="utf-8"), canonical)
        self.assertNotIn("**Verdict: NOT-READY**", path.read_text(encoding="utf-8"))

    def test_gate_never_reads_review_md(self):
        rev = self.review()
        rev.add_round("all", "READY", [finding("F1", "Nit", "applied")])
        expected = rev.gate()
        self.assertTrue(expected.allowed)
        path = self.instant / "REVIEW.md"
        rev.render()

        # (a) the view is DELETED. The gate still decides, identically.
        path.unlink()
        self.assertFalse(path.exists())
        gone = rev.gate()
        self.assertEqual((gone.allowed, gone.guard, gone.reason),
                         (expected.allowed, expected.guard, expected.reason))

        # (b) the view CONTRADICTS the ledger. The ledger wins; it is the ledger.
        path.write_text("no verdict line here at all, and NOT-READY appears in a sentence\n",
                        encoding="utf-8")
        contradicted = rev.gate()
        self.assertTrue(contradicted.allowed)
        self.assertEqual(contradicted.reason, expected.reason)

        # (c) the view is not even a file. Any read at all — even a "supplementary" one — raises here,
        # so this closes the door on reading the markdown as well as on believing it.
        path.unlink()
        path.mkdir()
        trapped = rev.gate()
        self.assertEqual((trapped.allowed, trapped.guard, trapped.reason),
                         (expected.allowed, expected.guard, expected.reason))


# --- the thin ledger, and the population -----------------------------------------------------------


class TestAdvisoryAndPopulation(ReviewCase):
    def test_a_round_with_a_verdict_but_no_findings_and_no_stages_is_flagged_thin(self):
        thin = self.review()
        thin.add_round("all", "READY", [])
        verdict = thin.gate()

        self.assertTrue(verdict.allowed, "the advisory is advisory: the ledger stays the arbiter")
        self.assertIn("thin", verdict.reason.lower())
        self.assertIn("round 1", verdict.reason.lower())
        self.assertEqual(len(thin.advisories()), 1)

        evidenced = self.ready(self.other_instant())
        evidenced_verdict = evidenced.gate()
        self.assertEqual(evidenced.advisories(), [])
        self.assertEqual(evidenced_verdict.allowed, verdict.allowed)
        self.assertNotEqual(evidenced_verdict.reason, verdict.reason,
                            "a verdict with no visible basis must not READ identically to an "
                            "evidenced one")
        self.assertNotIn("thin", evidenced_verdict.reason.lower())

    def test_the_gate_reports_the_population_it_examined(self):
        rev = self.review()
        rev.add_round("all", "READY-WITH-FIXES", [
            finding("F1", "Critical", "applied"),
            finding("F2", "Important", "open"),
        ])
        rev.add_round("code", "READY-WITH-FIXES", [finding("F3", "Minor", "open")])

        population = rev.population()
        self.assertEqual(population["rounds"], 2)
        self.assertEqual(population["round_scopes"], ["all", "code"])
        self.assertEqual(population["findings"], 3)
        self.assertEqual(population["open_blocking"], ["F2"])
        self.assertIn("all", population["scopes_covered"])

        reason = rev.gate().reason
        self.assertIn("population:", reason)
        self.assertIn("2 round(s)", reason)
        self.assertIn("3 finding(s)", reason)


# --- the ledger itself -----------------------------------------------------------------------------


class TestLedger(ReviewCase):
    def test_rounds_round_trip_through_the_json_ledger(self):
        # Beyond the plan's table: the ledger is the arbiter, so it must survive a fresh reader.
        rev = self.review()
        made = rev.add_round("all", "READY-WITH-FIXES", [finding("F1", "Critical", "applied")])
        self.assertIsInstance(made, Round)
        self.assertEqual((made.number, made.scope, made.at), (1, "all", TICKS[0]))

        fresh = Review(self.instant)
        self.assertEqual([r.number for r in fresh.rounds()], [1])
        self.assertEqual(fresh.rounds()[0].findings[0].id, "F1")
        self.assertTrue((self.instant / ".fleet" / "review.json").is_file())
        self.assertFalse((self.instant / "REVIEW.md").exists(),
                         "recording a round is not rendering a view")

    def test_heads_round_trip_and_absent_stays_absent(self):
        """A round carries the code it reviewed. A ledger written before this field keeps validating,
        and its rounds report {} — NOT MEASURED, which no gate may read as a mismatch."""
        made = Round(number=1, scope="code", verdict="READY", findings=[], at=TICKS[0],
                     heads={"gluten-internal": "a" * 40})
        self.assertEqual(made.to_json()["heads"], {"gluten-internal": "a" * 40})
        self.assertEqual(Round.from_json(made.to_json()).heads, {"gluten-internal": "a" * 40})

    def test_a_round_with_no_heads_emits_no_key(self):
        made = Round(number=1, scope="code", verdict="READY", findings=[], at=TICKS[0])
        self.assertNotIn("heads", made.to_json())
        self.assertEqual(Round.from_json({"number": 1, "scope": "code", "verdict": "READY",
                                          "at": TICKS[0], "findings": []}).heads, {})


if __name__ == "__main__":
    unittest.main()
