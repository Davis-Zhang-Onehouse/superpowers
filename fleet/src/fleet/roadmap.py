"""Milestones, readiness, and worker->coordinator proposals.

Two files, one writer each, and that split IS the module:

  <instant>/.fleet/roadmap.json     the milestone registry  — written by `add`, `claim` and `apply`,
                                    i.e. by the COORDINATOR and by nobody else
  <instant>/.fleet/proposals.json   the worker's inbox to the coordinator — written by `propose`

Why the writers are separated by FILE and not by convention: *"I'll let the worker update the shared
registry to save a step"* is a row on the STOP table, and a dispatch profile once instructed **every**
worker to update the canonical registry — and survived an entire effort that way, because nothing in the
mechanism could tell a worker's write from the coordinator's. Here a worker's verb physically cannot
produce a roadmap delta: `propose` returns a `Proposal` and appends it to its own file.

Three coordinator writers, and the split between them is the invariant — not "one function writes".
`add` creates a milestone, `claim` records WHICH INSTANT is executing one, and **`apply` is the only
function in the package that changes a milestone's STATUS.** `claim` deliberately does not touch status:
it was tempting to mark a dispatched milestone `running` and be done, and that would have made a second
status writer out of a verb whose job is bookkeeping — after which "who moved this milestone to done" has
two answers. The worker's first `propose --status running` moves it, through the same two-party path as
every other transition, so there is exactly one story for how a status changes.

Why readiness is DERIVED rather than a status somebody maintains: *"READY = disposition assigned, ACs
written, and its dependencies have LANDED."* A stored `ready` flag is a second copy of a fact the deps
already carry, and the two drift the moment a dep slips. `ready()` recomputes from `LANDED`, and
`report()` names the blocker for everything that is not ready — because a worker sitting "done" for hours
is the coordinator's failure to notice, not the operator's job.

**There is no reassignment, and that is deliberate** (`SD-5`; the concept and its `DeferredOwner`
machinery were removed, not merely left unused). The failure it was built for is real: `FI-7` records
eight items across `RCF-5/6/7/12/B-6/B-7` and `RV-19/RV-24` *"reassigned by name to the next effort's S-1
instant"* — **an instant that existed nowhere on the box** — so any lint resolving "reassigned to X" over
that population either went permanently RED or passed vacuously.

A reassignment naming a future owner is a *forward reference to a thing that does not exist*, and the
whole `DeferredOwner` apparatus — creation conditions, unclaimed populations, claim-to-clear — existed to
make that reference safe. The model here removes the reference instead: an item that outlives its effort
becomes **a documented issue in the workspace plus a MILESTONE on this roadmap**, and a milestone names no
owner it has to invent. The coordinator dispatches it later like any other. `FI-7`'s failure is then not
detected but *unrepresentable*, which is the stronger of the two, and it costs one concept instead of five.

What carries the item across the gap is the workspace, not this file: the issue is written up where a
resuming session reads it, and the milestone is what makes it dispatchable.

Nothing here reads a `.md` file. The registry is JSON; `render` turns it into markdown, never back.
"""
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from fleet.atomic import atomic_write, held_for_update
from fleet.errors import BadInput
from fleet.identity import resolve
from fleet.store import SCHEMA_VERSION

#: The status domain. A value outside it is refused at the producer, never coerced (FD-1).
STATUSES = ("blocked", "ready", "running", "awaiting-ci", "done", "dropped")

#: What LANDED means, and it is one status. `running` and `awaiting-ci` are dependencies that EXIST;
#: neither is a dependency that landed, and treating them as landed is how a worker is dispatched onto a
#: milestone whose base has not merged yet.
LANDED = ("done",)

#: Finished, by landing or by decision. Reported as information — a dropped milestone is not an alarm,
#: and *"a milestone that was dropped and re-raised must not read as new work"*.
TERMINAL = ("done", "dropped")

#: Statuses a milestone can become ready FROM. `blocked` is included deliberately: the stored status is a
#: label, the deps are the fact, so a `blocked` milestone whose deps have all landed IS ready and the
#: label is simply stale.
PENDING = ("blocked", "ready")

def _proposer(recorded) -> str:
    """Where the proposing instant is NOW, not where it was when it proposed.

    `SI-40`. A proposal records the instant's path at propose time, and a worker's completion signal is
    RENAMING ITS OWN FOLDER — so by the time a coordinator reads its inbox, the most important proposals
    (the `done` ones) are precisely the ones whose recorded path no longer exists. Observed on the first
    production effort: every pending row cited
    `…-07310400-inflight-append-splitproposaldigestrcompact` while the folder on disk was `-complete-`.

    Nothing was broken by it — `p.instant` is used ONLY in this string, and `apply` re-resolves through
    the stable key like everything else. But this row is what a human reads before deciding to apply, and
    handing them a path that does not resolve, in a protocol whose premise is "evidence, with a path behind
    it", teaches them the paths are decorative.

    The recorded value is still in the proposal JSON, so nothing is lost for forensics. When the folder
    cannot be found at all the recorded path is shown and SAID to be missing — a resolver that silently
    substitutes its input is worse than one that admits it failed.
    """
    recorded = Path(recorded)
    found = resolve(recorded)
    if found is None:
        return f"{recorded} (no longer on disk)"
    return str(found)


NOT_READY, PENDING_PROPOSAL, POPULATION = "not-ready", "pending-proposal", "population"

ATTENTION, INFO = "attention", "info"


COORDINATOR = "the coordinator"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Milestone:
    id: str
    title: str
    status: str
    deps: list
    evidence: list
    owner: str = None


@dataclass(frozen=True)
class Proposal:
    """A worker's claim about a milestone. Immutable, attributed to the proposing instant, and stamped —
    so a proposal nobody applied is measurable rather than a feeling."""

    instant: str
    milestone: str
    status: str
    evidence: list
    at: str




@dataclass(frozen=True)
class Row:
    """One line of `report()`. `severity` separates *information* from *attention* so that finished work
    and a legitimately empty population are reported without being RED (§9)."""

    kind: str
    subject: str
    detail: str
    severity: str
    clears_when: str = None
    clears_who: str = None


def _check_status(status: str) -> str:
    if status not in STATUSES:
        raise BadInput(f"status {status!r} is outside the domain {STATUSES}; it is refused, not coerced")
    return status


def _check_evidence(evidence, milestone: str) -> list:
    """The one gate, called by both writers. A status change with no evidence is the claim without the
    artifact, and the reason this is a refusal rather than a warning is that the warning was ignored."""
    items = [e for e in (evidence or []) if str(e).strip()]
    if not items:
        raise BadInput(
            f"a status change for {milestone!r} needs at least one evidence path; a claim with no "
            "artifact is not a status change")
    return [str(e) for e in items]


class Roadmap:
    def __init__(self, instant: Path):
        self.instant = Path(instant)
        self.dir = self.instant / ".fleet"
        self.path = self.dir / "roadmap.json"
        self.proposals_path = self.dir / "proposals.json"

    # ------------------------------------------------------------------ persistence

    def _read(self, path: Path, empty: dict) -> dict:
        if not path.is_file():
            return empty
        data = json.loads(path.read_text())
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise BadInput(
                f"{path} has schema_version={version!r}, this build knows {SCHEMA_VERSION}. Refusing to "
                "interpret it — a fix that changes how state is READ needs a migration path for state "
                "that already exists (OBS-9 -> W2-5).")
        return data

    def _load(self) -> dict:
        return self._read(self.path, {"schema_version": SCHEMA_VERSION, "milestones": []})

    def _load_proposals(self) -> dict:
        return self._read(self.proposals_path,
                          {"schema_version": SCHEMA_VERSION, "pending": [], "applied": []})

    def _save(self, path: Path, data: dict) -> None:
        data["schema_version"] = SCHEMA_VERSION
        # Through the ONE atomic write (FI-20): a reader never sees a half-written registry, and two
        # writers cannot share a staging path. As in `review`, this does not make the surrounding
        # read-modify-write indivisible; that is `atomic.atomic_update`, and it is reported as an open gap
        # rather than applied to a path §E never measured.
        atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False))

    # ------------------------------------------------------------------ milestones

    def add(self, m: Milestone) -> None:
        if not m.id or not m.id.strip():
            raise BadInput("a milestone needs an id")
        _check_status(m.status)
        # FI-30c: the load/validate/append/write below is ONE step. Six concurrent adds left 1 of 6
        # milestones in every one of 8 iterations before this — the duplicate check also read stale state,
        # so two writers could each pass it for the same id.
        with held_for_update(self.path):
            data = self._load()
            if any(d["id"] == m.id for d in data["milestones"]):
                raise BadInput(f"milestone {m.id!r} is already in the roadmap; refusing to shadow it")
            data["milestones"].append(asdict(m))
            self._save(self.path, data)

    def milestones(self) -> list:
        return [Milestone(**d) for d in self._load()["milestones"]]

    def milestone(self, milestone_id: str) -> Milestone:
        for m in self.milestones():
            if m.id == milestone_id:
                return m
        raise BadInput(f"no milestone {milestone_id!r} in {self.path}")

    def _readiness(self) -> list:
        """The ONE readiness derivation. `ready()` and `report()` both read it, so "may I start this?" and
        "why can I not start this?" cannot disagree — two code paths for one rule is how they drift."""
        by_id = {m.id: m for m in self.milestones()}
        out = []
        for m in by_id.values():
            out.append((m,) + self._blocker(m, by_id))
        return out

    def _blocker(self, m: Milestone, by_id: dict):
        """-> (blocker, clears_when, clears_who); blocker is None iff the milestone is ready."""
        if m.status in TERMINAL:
            return (f"status={m.status}: it is finished, so it is not pending work", None, None)
        if m.status not in PENDING:
            actor = m.owner or COORDINATOR
            return (f"status={m.status}: it is already in flight, held by {actor}",
                    f"{actor} proposes the next status with evidence and the coordinator applies it",
                    actor)
        missing, unlanded = [], []
        for dep in m.deps:
            other = by_id.get(dep)
            if other is None:
                missing.append(dep)
            elif other.status not in LANDED:
                unlanded.append(other)
        if missing:
            names = ", ".join(repr(d) for d in missing)
            return (f"dep(s) {names} are not in the roadmap at all, so their landing cannot be checked",
                    f"the missing dep(s) {names} are added to the roadmap or removed from {m.id!r}",
                    COORDINATOR)
        if unlanded:
            detail = ", ".join(f"{d.id!r} has status={d.status}" for d in unlanded)
            actor = next((d.owner for d in unlanded if d.owner), COORDINATOR)
            return (f"dep(s) exist but have not LANDED (landed means status in {LANDED}): {detail}",
                    "every dep reaches status=done through an applied proposal",
                    actor)
        return (None, None, None)

    def ready(self) -> list:
        """Milestones whose deps have LANDED — not merely exist."""
        return [m for m, blocker, _, _ in self._readiness() if blocker is None]

    def claim(self, milestone_id: str, owner: str) -> "Milestone":
        """Record that `owner` is executing this milestone. `SI-27`.

        Sets **`owner` and nothing else** — see the header on why this is not a status write.

        Two refusals, and both are the point of the function:
          * a milestone that is NOT READY cannot be claimed, so a worker cannot be dispatched onto work
            whose dependencies have not landed. That was previously possible and invisible: `dispatch` did
            not know what milestone it was for, so nothing was in a position to check.
          * a milestone that ALREADY has an owner cannot be claimed, so two workers cannot be put on one
            milestone. Without the join there was no way to notice — `board` showed two workers, `roadmap`
            showed one milestone, and nothing connected them.

        Re-checked under the lock rather than trusting a caller's earlier read: `dispatch` fast-fails on the
        same conditions before claiming a slot, but two concurrent dispatchers can both pass a read. This is
        the authoritative check, which is `FI-21`'s claim-then-verify applied to the roadmap.
        """
        if not owner or not str(owner).strip():
            raise BadInput("a claim needs an owner; an unowned claim records nothing")
        with held_for_update(self.path):
            data = self._load()
            found = None
            for entry in data["milestones"]:
                if entry["id"] == milestone_id:
                    found = entry
                    break
            if found is None:
                raise BadInput(f"no milestone {milestone_id!r} in {self.path}")
            if found.get("owner"):
                raise BadInput(
                    f"milestone {milestone_id!r} is already claimed by {found['owner']!r}. Two instants on "
                    f"one milestone is not a race the roadmap can resolve — if that owner is gone, its "
                    f"record is what says so (`fleet board`, `fleet status`), and the work is released by "
                    f"aborting it with a reason.")
            #: Readiness is derived from the CURRENT file, which is the one held open here.
            by_id = {m["id"]: Milestone(**m) for m in data["milestones"]}
            blocker, _, _ = self._blocker(by_id[milestone_id], by_id)
            if blocker:
                raise BadInput(
                    f"milestone {milestone_id!r} is not ready, so nothing may be dispatched onto it: "
                    f"{blocker}")
            found["owner"] = str(owner)
            self._save(self.path, data)
            return Milestone(**found)

    def disown(self, milestone_id: str) -> None:
        """Give a claim back. Called only from `dispatch`'s rollback, so a dispatch that failed after
        claiming does not leave a milestone owned by an instant that was never launched — `SI-21`'s lesson
        (a rollback must not strand state it created) applied to the roadmap."""
        with held_for_update(self.path):
            data = self._load()
            for entry in data["milestones"]:
                if entry["id"] == milestone_id:
                    entry["owner"] = None
                    self._save(self.path, data)
                    return
            raise BadInput(f"no milestone {milestone_id!r} in {self.path}")

    def blocker_of(self, milestone_id: str) -> str:
        """Why this ONE milestone is not ready, or None if it is. Reads `_readiness`, deliberately: `ready`,
        `report` and this must never be able to disagree about the same milestone (`SI-26` needed a
        per-milestone answer at the moment one is added, and computing it a second way is how the coordinator
        ends up told a milestone is ready by one verb and blocked by another)."""
        for m, blocker, _, _ in self._readiness():
            if m.id == milestone_id:
                return blocker
        raise BadInput(f"no milestone {milestone_id!r} in {self.path}")

    # ------------------------------------------------------------------ propose / apply

    def propose(self, instant: Path, milestone: str, status: str,
                evidence: list) -> Proposal:
        """The WORKER's verb (UC-3). Writes `proposals.json` and NOTHING else — in particular it never
        opens `roadmap.json` for writing, which is why a worker cannot move the registry even by mistake."""
        self.milestone(milestone)          # an unknown milestone is refused at the producer
        proposal = Proposal(instant=str(Path(instant)), milestone=milestone,
                            status=_check_status(status),
                            evidence=_check_evidence(evidence, milestone), at=_now())
        with held_for_update(self.proposals_path):        # FI-30c
            data = self._load_proposals()
            data["pending"].append(asdict(proposal))
            self._save(self.proposals_path, data)
        return proposal

    def proposals(self) -> list:
        return [Proposal(**d) for d in self._load_proposals()["pending"]]

    def apply(self, proposal: Proposal) -> Milestone:
        """The COORDINATOR's verb and THE single writer of a milestone status.

        Validation happens here rather than only in `propose`, because a proposal can be hand-built or
        replayed from a file: a gate that only guards the polite path is not a gate."""
        status = _check_status(proposal.status)
        evidence = _check_evidence(proposal.evidence, proposal.milestone)
        # FI-30c. `_consume` is called INSIDE this lock and takes its own on `proposals_path` — a
        # different file, and always in this order (roadmap then proposals), which is the only order any
        # path here uses. Two locks acquired in one order cannot deadlock against themselves.
        with held_for_update(self.path):
            data = self._load()
            for d in data["milestones"]:
                if d["id"] == proposal.milestone:
                    d["status"] = status
                    for item in evidence:
                        if item not in d["evidence"]:
                            d["evidence"].append(item)
                    self._save(self.path, data)
                    self._consume(proposal)
                    return Milestone(**d)
        raise BadInput(f"no milestone {proposal.milestone!r} in {self.path}; refusing to invent one")

    def _consume(self, proposal: Proposal) -> None:
        """An applied proposal leaves the pending inbox, so replaying the inbox cannot apply it twice and
        `report()` stops asking the coordinator for something it has already done."""
        with held_for_update(self.proposals_path):        # FI-30c
            data = self._load_proposals()
            body = asdict(proposal)
            pending = list(data["pending"])
            if body in pending:
                pending.remove(body)
                data["pending"] = pending
                data["applied"].append(body)
                self._save(self.proposals_path, data)


    # ------------------------------------------------------------------ the report

    def report(self) -> list:
        """Everything the coordinator has to act on, plus the population it was derived from.

        The population row is last and always present: a checker that narrows its scope silently reads as
        a pass (`OBS-49`), and a legitimately empty roadmap is reported rather than RED."""
        rows = []
        for m, blocker, clears_when, clears_who in self._readiness():
            if blocker is None:
                continue
            rows.append(Row(kind=NOT_READY, subject=m.id, detail=blocker,
                            severity=INFO if m.status in TERMINAL else ATTENTION,
                            clears_when=clears_when, clears_who=clears_who))

        pending = self.proposals()
        for p in pending:
            rows.append(Row(
                kind=PENDING_PROPOSAL, subject=p.milestone,
                detail=(f"{_proposer(p.instant)} proposes {p.milestone} -> {p.status} at {p.at} with "
                        f"{len(p.evidence)} evidence item(s); the roadmap is UNCHANGED until the "
                        "coordinator applies it"),
                severity=ATTENTION,
                clears_when="the coordinator applies the proposal (single writer)",
                clears_who=COORDINATOR))

        milestones = self.milestones()
        rows.append(Row(
            kind=POPULATION, subject=str(self.instant),
            detail=(f"examined {len(milestones)} milestone(s) of which {len(self.ready())} ready, "
                    f"{len(pending)} pending proposal(s), from {self.path}"),
            severity=INFO))
        return rows
