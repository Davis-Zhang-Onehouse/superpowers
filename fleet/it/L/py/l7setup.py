import os
from pathlib import Path
from fleet.harvest import Harvest
from fleet.roadmap import Milestone, Roadmap
home, inst = Path(os.environ["L7H"]), Path(os.environ["INSTP"])
stale_base = Path(os.environ["EV"]) / "reg" / "l7stale"
stale_base.mkdir(parents=True, exist_ok=True)
(stale_base / "ISSUES.md").write_text("# stale register\n## SS-1 — one issue nobody has harvested\n")
src = Harvest(home, now=lambda: "2020-01-01T00:00:00Z").register(str(stale_base),
                                                                str(stale_base / "ISSUES.md"))
print("stale source:", src.base, src.registered_at, src.last_run)
road = Roadmap(inst)
road.add(Milestone(id="M1", title="the probe milestone", status="ready", deps=[], evidence=[]))
print("milestones:", [m.id for m in road.milestones()])
