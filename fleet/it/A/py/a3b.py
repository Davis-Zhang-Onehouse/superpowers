"""A3b — run a real verb from the second checkout and prove no module came from anywhere else."""
import os, sys
from fleet.cli import VERBS, main, registered_codes
co = os.path.realpath(os.environ["A3_CO"])
rc = main(["leases"])
assert rc in registered_codes("leases"), rc
loaded = {n: getattr(m, "__file__", None) for n, m in sorted(sys.modules.items())
          if n == "fleet" or n.startswith("fleet.")}
outside = {n: f for n, f in loaded.items() if f and not os.path.realpath(f).startswith(co)}
for n, f in loaded.items():
    print(f"{n:22} {f}")
print("modules:", len(loaded), "verbs:", len(VERBS), "leases_rc:", rc)
print("OUTSIDE_SECOND_CHECKOUT:", outside)
assert not outside, outside
print("OK A3b")
