"""L1 — register the dummy ISSUES.md; prime reports its COUNT and reports no issues."""
import os
from pathlib import Path
from fleet.harvest import Harvest, exit_code
EV, DUMMY = Path(os.environ["EV"]), Path(os.environ["DUMMY"])
h = Harvest(EV / "home-l1")
src = h.register(str(DUMMY), str(DUMMY / "ISSUES.md"))
count = h.prime(src)
assert isinstance(count, int) and not isinstance(count, bool), f"prime returned {type(count)}"
found = h.ids_found(src)
print("prime count:", count, "ids_found:", found)
assert count == 3, f"prime recorded {count}, expected the register's 3 ids"
assert found == 3, f"ids_found={found}"
rows = h.run(src)
for r in rows:
    print("row:", r.kind, r.severity, r.ids_found, r.new_count, r.detail[:120])
kinds = [r.kind for r in rows]
assert kinds == ["source"], f"a primed source reported {kinds}; expected the source row alone"
assert rows[0].new_count == 0, f"new_count={rows[0].new_count} after prime"
assert rows[0].ids_found == 3
assert "produced nothing" in rows[0].detail
assert exit_code(rows) == 0, "a primed clean source is not clean"
print("OK L1: prime reported the count (3) as a number and reported no issue ids; the next tick is 0 new")
