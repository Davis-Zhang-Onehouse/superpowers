import os
from pathlib import Path
from fleet.roadmap import Milestone, Roadmap
road = Roadmap(Path(os.environ["A5_INST"]))
if not road.milestones():
    road.add(Milestone(id="M1", title="the A5 milestone", status="ready", deps=[], evidence=[]))
print("milestones:", [m.id for m in road.milestones()])
