"""L5 — three halves, in this order:
  (a) a register using ### headings and an id RI-9a ⇒ ids_found NON-ZERO (the extractor really parses it)
  (b) a NON-EMPTY register yielding zero ids ⇒ ERROR (VacuousExtraction / violation row / exit 1)
  (c) an EMPTY register ⇒ clean, with an info row
Without (a), (b) would only be testing a broken regex."""
import os
from pathlib import Path
from fleet.harvest import Harvest, VacuousExtraction, extract, exit_code, EMPTY_REGISTER, VACUOUS
EV = Path(os.environ["EV"])

# (a) --------------------------------------------------------------------------------------------
a = EV / "reg" / "l5a"; a.mkdir(parents=True, exist_ok=True)
(a / "ISSUES.md").write_text(
    "# Register with third-level ids\n"
    "### RI-9a — an id with a letter suffix\n"
    "#### Status\n"
    "OPEN\n"
    "### W2-14 — a digit inside the prefix\n"
    "### RCF-B-8 — a middle segment\n"
    "### A third-level heading that is not an id\n")
h = Harvest(EV / "home-l5a")
src_a = h.register(str(a), str(a / "ISSUES.md"))
ids = [i.id for i in extract((a / "ISSUES.md").read_text())]
found = h.ids_found(src_a)
print("(a) ids parsed:", ids, "ids_found:", found)
assert found != 0, "ids_found is ZERO on a ### register — the extractor is blind and (b) would be vacuous"
assert "RI-9a" in ids, f"RI-9a not parsed: {ids}"
assert found == 3, f"ids_found={found}, expected 3 (RI-9a, W2-14, RCF-B-8)"

# (b) --------------------------------------------------------------------------------------------
b = EV / "reg" / "l5b"; b.mkdir(parents=True, exist_ok=True)
(b / "ISSUES.md").write_text(
    "This register has content and no ids.\n\n"
    "- a bullet about a problem\n"
    "# Notes\n"
    "## Something that is not an id\n"
    "Some more prose.\n")
hb = Harvest(EV / "home-l5b")
src_b = hb.register(str(b), str(b / "ISSUES.md"))
raised = None
try:
    hb.ids_found(src_b)
except VacuousExtraction as exc:
    raised = exc
print("(b) VacuousExtraction:", type(raised).__name__ if raised else None)
assert raised is not None, "a non-empty register yielding zero ids did NOT raise"
assert raised.exit_code == 1, f"VacuousExtraction.exit_code={raised.exit_code}"
rows_b = hb.run(src_b)
print("(b) rows:", [(r.kind, r.severity) for r in rows_b])
assert [r.kind for r in rows_b] == [VACUOUS], f"expected a vacuous-extraction row, got {rows_b}"
assert rows_b[0].severity == "violation"
assert exit_code(rows_b) == 1, "a vacuous extraction did not report non-zero"

# (c) --------------------------------------------------------------------------------------------
c = EV / "reg" / "l5c"; c.mkdir(parents=True, exist_ok=True)
(c / "ISSUES.md").write_text("")
hc = Harvest(EV / "home-l5c")
src_c = hc.register(str(c), str(c / "ISSUES.md"))
print("(c) primed:", hc.prime(src_c))
rows_c = hc.run(src_c)
print("(c) rows:", [(r.kind, r.severity, r.ids_found) for r in rows_c])
kinds = [r.kind for r in rows_c]
assert EMPTY_REGISTER in kinds, f"an empty register reported no info row: {kinds}"
assert all(r.severity == "info" for r in rows_c), f"an empty register went RED: {rows_c}"
assert exit_code(rows_c) == 0
print("OK L5: (a) ids_found=3 incl RI-9a from ### headings · (b) non-empty/zero-ids raises "
      "VacuousExtraction and reports exit 1 · (c) empty register is clean with an empty-register info row")
