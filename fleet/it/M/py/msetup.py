import os
from pathlib import Path
from fleet.roadmap import Milestone, Roadmap
road = Roadmap(Path(os.environ["INSTP"]))
if not road.milestones():
    road.add(Milestone(id="M1", title="the probe milestone", status="ready", deps=[], evidence=[]))
print("milestones:", [m.id for m in road.milestones()])
