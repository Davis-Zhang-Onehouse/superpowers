import os
from pathlib import Path
from fleet.harvest import Harvest
EV = Path(os.environ["EV"])
base = EV / "reg" / "l8"; base.mkdir(parents=True, exist_ok=True)
(base / "ISSUES.md").write_text("# l8\n## L8-1 — first\n## L8-2 — second\n")
src = Harvest(Path(os.environ["L8H"])).register(str(base), str(base / "ISSUES.md"))
print("registered", src.base, "seen dir exists:",
      (Path(os.environ["L8H"]) / "harvest" / "seen").is_dir())
