"""L2 append two ⇒ both named · L3 insert BEFORE the last heading ⇒ detected · L4 renumber ⇒ zero new."""
import os, shutil, sys
from pathlib import Path
from fleet.harvest import Harvest
EV, DUMMY = Path(os.environ["EV"]), Path(os.environ["DUMMY"])
case = sys.argv[1]
base = EV / "reg" / case
base.mkdir(parents=True, exist_ok=True)
reg = base / "ISSUES.md"
shutil.copyfile(DUMMY / "ISSUES.md", reg)
h = Harvest(EV / f"home-{case}")
src = h.register(str(base), str(reg))
print("primed:", h.prime(src))

if case == "l2":
    reg.write_text(reg.read_text() + "## RI-40 — an appended issue\n## RI-41 — a second appended issue\n")
    want = ["RI-40", "RI-41"]
elif case == "l3":
    lines = reg.read_text().splitlines(keepends=True)
    last = max(i for i, line in enumerate(lines) if line.startswith("## "))
    lines.insert(last, "## RI-50 — inserted BEFORE the last heading (OBS-11's shape)\n")
    reg.write_text("".join(lines))
    print("inserted at line", last + 1, "of", len(lines), "; last heading is now line",
          max(i for i, l in enumerate(reg.read_text().splitlines(), start=1) if l.startswith("## ")))
    want = ["RI-50"]
else:  # l4 — renumber the whole register's PREFIX
    reg.write_text(reg.read_text().replace("## RI-", "## QQ-"))
    want = []

new = h.new_issues(src)
got = [i.id for i in new]
print("new ids:", got, "expected:", want)
assert got == want, f"{case}: new={got}, expected {want}"
if case == "l4":
    print("register now:", [l for l in reg.read_text().splitlines() if l.startswith("## ")])
print(f"OK {case.upper()}: new={got or 'none'} (expected {want or 'zero new'})")
