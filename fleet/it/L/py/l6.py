"""L6 — a registered source that produced NOTHING is reported as such, not omitted."""
import os
from pathlib import Path
from fleet.harvest import Harvest, SOURCE
EV, DUMMY = Path(os.environ["EV"]), Path(os.environ["DUMMY"])
h = Harvest(EV / "home-l6")
quiet = EV / "reg" / "l6quiet"; quiet.mkdir(parents=True, exist_ok=True)
(quiet / "ISSUES.md").write_text("# quiet register\n## RI-1 — the only issue, already known\n")
s1 = h.register(str(DUMMY), str(DUMMY / "ISSUES.md"))
s2 = h.register(str(quiet), str(quiet / "ISSUES.md"))
h.prime(s1); h.prime(s2)                      # both now have memory: both will produce nothing
rows = h.report(live_work=False)
for r in rows:
    print("row:", r.kind, r.subject, r.severity, "|", r.detail[:110])
source_rows = [r for r in rows if r.kind == SOURCE]
assert len(source_rows) == 2, f"{len(source_rows)} source row(s) for 2 registered sources — one was omitted"
for r in source_rows:
    assert r.new_count == 0
    assert "produced nothing" in r.detail, f"a silent source did not say so: {r.detail}"
pops = [r for r in rows if r.kind == "population"]
assert len(pops) == 1 and "2 watched source(s)" in pops[0].detail, pops
print("OK L6: both silent sources are rows that say 'produced nothing'; the population row counts 2")
