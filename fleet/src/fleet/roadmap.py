"""Milestones, readiness, and worker->coordinator proposals.

Two files, one writer each, and that split IS the module:

  <instant>/.fleet/roadmap.json     the milestone registry  — written by `add`, `claim` and `apply`,
                                    i.e. by the COORDINATOR and by nobody else
  <instant>/.fleet/proposals.json   the worker's inbox to the coordinator — appended by `propose`; a row
                                    leaves `pending` by being applied, superseded, withdrawn or retired
                                    (`B02`), and every exit is recorded, never deleted

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
#: `B04` / `SI-47`. A milestone whose deps have LANDED. It used to have no row at all — `report()` skipped
#: every milestone with no blocker — so the one state a coordinator acts on was the one it had to parse out
#: of the population row's prose.
READY = "ready"

#: `B02`. The ways a proposal leaves `pending` other than being applied. Each lands in the inbox's
#: `closed` list with the reason, so a report is never lost — only decided.
SUPERSEDED, WITHDRAWN, RETIRED = "superseded", "withdrawn", "retired"

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
    #: `FI-10`. Why this milestone was retired. Defaulted, because every `roadmap.json` already on disk
    #: has no such key and `milestones()` builds each entry with `Milestone(**d)` — a field without a
    #: default turns every existing roadmap into a TypeError. Empty for anything never retired.
    retired_reason: str = ""
    #: `SI-51`. Why the CURRENT lack of an owner happened, when it happened by release rather than by
    #: never having been claimed. Same defaulting argument as `retired_reason` and the same reason for
    #: existing: an owner that silently became `None` is indistinguishable, a week later, from one that
    #: was never claimed — and the nine hand-edits this field exists to replace were each performed
    #: because nothing on the roadmap could say what had happened to the claim.
    #:
    #: Cleared by `claim`, deliberately: a milestone carrying a sentence about why its CURRENT owner does
    #: not own it is worse than one carrying nothing.
    disowned_reason: str = ""


@dataclass(frozen=True)
class Proposal:
    """A worker's claim about a milestone. Immutable, attributed to the proposing instant, and stamped —
    so a proposal nobody applied is measurable rather than a feeling."""

    instant: str
    milestone: str
    status: str
    evidence: list
    at: str
    #: `I-2`. One line of narrative ABOUT the proposal. Defaulted, and the default matters more than the
    #: field: every proposal written before this existed has no `note` key, and `proposals()` builds each
    #: one with `Proposal(**d)` — so a field without a default turns a coordinator's whole existing inbox
    #: into a TypeError. A new optional field that breaks the inbox is not optional.
    #:
    #: It never substitutes for evidence. A worker reported that `--note` did not exist and worked around
    #: it by writing a file and citing it as `--evidence`, which is exactly the right instinct and exactly
    #: the wrong ergonomics: it makes every one-line summary a separate artifact. A status claim still
    #: stands or falls on the paths it cites; this is the sentence that says what to look at first.
    note: str = ""




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
    #: `B04` i22(a). The milestone's title and owner as FIELDS, on every row about a milestone. The owner
    #: used to reach a reader only as the ACTOR inside another milestone's blocker prose, so "what is
    #: dispatchable" was answered by hand-parsing `roadmap.json`. Empty (not None) when there is none, so
    #: `owner == ""` is the dispatchable test; None on the population row, which is about no milestone.
    title: str = None
    owner: str = None


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


def last_index(rows: list, row) -> int:
    """Where `row` sits in `rows`, counting from the END. Two byte-identical rows (a propose repeated inside
    one second) are one report sent twice; cutting at the LAST copy makes the earlier copy superseded rather
    than leaving it pending after its twin was applied. `select`, `_consume` and harvest's count all cut here."""
    return len(rows) - 1 - rows[::-1].index(row)


def _one_at(rows: list, at: str, milestone: str, where) -> list:
    """`B02`'s row selector: the ONE pending row (dict) for `milestone` stamped `at`. Zero or several
    matches are refused by name — `at` has one-second resolution, so two rows can share it."""
    matches = [r for r in rows if r["at"] == at]
    if len(matches) != 1:
        stamps = ", ".join(f"{r['status']} at {r['at']}" for r in rows) or "none"
        raise BadInput(f"--at {at} matches {len(matches)} pending row(s) for {milestone!r} in {where}, not "
                       f"exactly one; the {len(rows)} pending: {stamps}. With no --at the newest row is "
                       f"the one chosen.")
    return matches


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
        data = self._read(self.proposals_path,
                          {"schema_version": SCHEMA_VERSION, "pending": [], "applied": [], "closed": []})
        #: `B02`. Additive, so no schema bump: every inbox written before `closed` existed has no such key,
        #: and it reads as "nothing closed yet" rather than as a file this build refuses.
        data.setdefault("closed", [])
        #: `B02` (final review). A row written before `note` existed has no such key, and `Proposal(**d)`
        #: fills in `note=""`, so `asdict(proposal)` no longer equals the stored dict: `_consume` could not
        #: find the row it had just applied, left it pending and superseded nothing. The live quanton inbox
        #: holds 7 such pending rows. Normalised here, the one place every reader and writer loads from.
        for row in data["pending"] + data["applied"]:
            row.setdefault("note", "")
        return data

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

    def retire(self, milestone_id: str, reason: str) -> Milestone:
        """The COORDINATOR removes a superseded milestone from the population. `FI-10`.

        Across 31 verbs there was no way to do this. `add` refuses an id already present — *"refusing to
        shadow it"*, which is right, because silently reshaping a milestone loses its history — and
        `apply` refuses to invent a status without a worker's proposal, which is also right, and a
        superseded milestone has no worker and never will. Both doors correctly shut, and no third one.

        The cost is not cosmetic: once its deps land, a superseded milestone is derived READY forever,
        and `roadmap --porcelain` prints it as a `ready` row (`B04`) — a phantom dispatchable milestone
        until it is retired.

        **On the module's stated invariant.** The header says `apply` is the only function that changes a
        milestone's status. That is now stated more precisely, because this writes one too: `apply` is
        the only thing that ADVANCES a milestone on a worker's evidence, and `retire` is the coordinator
        removing one from the population by its own decision. The property the two-party protocol exists
        for is untouched — a worker still cannot move the roadmap by any path — and this can write
        exactly one value, `dropped`, onto a milestone that has not finished.

        The reason is REQUIRED. `dropped` and `done` are both terminal and read alike months later; a
        milestone that left the population with no recorded why is a decision nobody can reconstruct.

        `B02`: it also closes the milestone's pending proposals as `retired`, after the roadmap write. If the
        inbox cannot be read (e.g. a schema mismatch) the milestone is already dropped and the error names
        the inbox; the rows stay pending and `fleet withdraw` closes them once it is readable.
        """
        reason = " ".join(str(reason or "").split())
        if not reason:
            raise BadInput(
                f"retiring {milestone_id!r} needs a --reason. `dropped` and `done` are both terminal and "
                f"look alike to a later reader, so a milestone that left the population without a "
                f"recorded why is a decision nobody can reconstruct.")
        with held_for_update(self.path):
            data = self._load()
            for entry in data["milestones"]:
                if entry["id"] != milestone_id:
                    continue
                if entry["status"] in TERMINAL:
                    raise BadInput(
                        f"milestone {milestone_id!r} is already {entry['status']}, which is terminal. "
                        f"Retiring it would rewrite a finished record — the same thing `add` refuses "
                        f"when it declines to shadow an existing id.")
                entry["status"] = "dropped"
                entry["retired_reason"] = reason
                self._save(self.path, data)
                #: `B02`. The milestone's pending rows describe work the coordinator just wrote off, and
                #: `apply` now refuses to move a terminal milestone, so left pending they could never be
                #: decided — "len(pending) is not a work count". Closed, with the retire reason. Inside the
                #: roadmap lock, in apply's order (roadmap, then proposals).
                with held_for_update(self.proposals_path):
                    inbox = self._load_proposals()
                    doomed = [r for r in inbox["pending"] if r["milestone"] == milestone_id]
                    if doomed:
                        self._close(inbox, doomed, RETIRED, reason)
                        self._save(self.proposals_path, inbox)
                return Milestone(**entry)
        raise BadInput(f"no milestone {milestone_id!r} in {self.path}, so there is nothing to retire")

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
        """-> (blocker, clears_when, clears_who, severity); blocker is None iff the milestone is ready.

        **The severity is decided HERE, by the reason.** `FI-2`. It used to be decided by `report()` from
        `m.status` alone, which made every not-ready milestone `attention` — including the commonest and
        most benign case in the system, a stacked milestone waiting for its predecessor to finish. A
        healthy three-deep stack shouted three times, and `using-fleet` says *act on `violation`, report
        `info`*, so `attention` on a normal state leaves the reader nothing to do but learn to scroll
        past it. The `not-ready` row that DOES matter then scrolls past with it.

        This function is the only place that knows WHICH not-ready case applies, so it is the only place
        that can grade it. `report()` discarding that and re-deriving from a status it can see is the
        same shape as `FI-14` and `FI-12`: a judgement computed and then dropped.
        """
        if m.status in TERMINAL:
            return (f"status={m.status}: it is finished, so it is not pending work", None, None, INFO)
        if m.status not in PENDING:
            actor = m.owner or COORDINATOR
            #: Somebody is executing it. Nothing for a reader to do, so INFO.
            return (f"status={m.status}: it is already in flight, held by {actor}",
                    f"{actor} proposes the next status with evidence and the coordinator applies it",
                    actor, INFO)
        missing, unlanded = [], []
        for dep in m.deps:
            other = by_id.get(dep)
            if other is None:
                missing.append(dep)
            elif other.status not in LANDED:
                unlanded.append(other)
        if missing:
            names = ", ".join(repr(d) for d in missing)
            #: ATTENTION, and this is the case that keeps the tier meaningful. A dep that is not in the
            #: roadmap can NEVER land, so this milestone is permanently unready — `coordinating-instants`
            #: warns that a typo'd dependency "is not an error later; it is a milestone that reads as
            #: permanently in progress". Somebody must add the dep or remove it.
            return (f"dep(s) {names} are not in the roadmap at all, so their landing cannot be checked",
                    f"the missing dep(s) {names} are added to the roadmap or removed from {m.id!r}",
                    COORDINATOR, ATTENTION)
        if unlanded:
            detail = ", ".join(f"{d.id!r} has status={d.status}" for d in unlanded)
            actor = next((d.owner for d in unlanded if d.owner), COORDINATOR)
            #: A dep that can NEVER land is not the same as one that has not landed YET, and `FI-2`'s
            #: fix conflated them for one release. `LANDED` is `("done",)` and `TERMINAL` is
            #: `("done", "dropped")`, so a dep sitting at `dropped` is finished AND unlandable: its
            #: dependent is permanently unreachable. Reported as INFO — "waiting is the design" — that is
            #: a permanent block filed as news, and its `clears_when` told the reader to wait for
            #: `status=done`, which cannot happen. An alarm naming an impossible remedy is `FI-5`
            #: exactly, reintroduced by the fix for `FI-2`.
            #:
            #: `milestone --retire` (`FI-10`) makes it one command away: retire a milestone and every
            #: dependent silently becomes permanently unready.
            #:
            #: The question is not "has the dep landed" but "can it".
            stuck = [d for d in unlanded if d.status in TERMINAL]
            if stuck:
                names = ", ".join(f"{d.id!r} is {d.status}" for d in stuck)
                return (f"dep(s) can NEVER land: {names}. {LANDED[0]!r} is the only landing status and a "
                        f"terminal dep cannot reach it, so {m.id!r} is permanently unready — not waiting",
                        f"the dep is re-raised as new work, or {m.id!r} drops it from its deps, or "
                        f"{m.id!r} is itself retired. Waiting will not clear this",
                        COORDINATOR, ATTENTION)
            #: INFO. Every dep exists and is progressing; waiting for it is the design working, not a
            #: condition anybody can act on. This is the row a stacked roadmap emits most often.
            return (f"dep(s) exist but have not LANDED (landed means status in {LANDED}): {detail}",
                    "every dep reaches status=done through an applied proposal",
                    actor, INFO)
        return (None, None, None, INFO)

    def ready(self) -> list:
        """Milestones whose deps have LANDED — not merely exist."""
        return [m for m, blocker, _, _, _ in self._readiness() if blocker is None]

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
            blocker, _, _, _ = self._blocker(by_id[milestone_id], by_id)
            if blocker:
                raise BadInput(
                    f"milestone {milestone_id!r} is not ready, so nothing may be dispatched onto it: "
                    f"{blocker}")
            found["owner"] = str(owner)
            #: `SI-51`. The release reason belongs to the release, not to the milestone. Left in place it
            #: would sit beside a live owner explaining why that owner does not own it.
            found["disowned_reason"] = ""
            self._save(self.path, data)
            return Milestone(**found)

    def disown(self, milestone_id: str, expect_owner: str = None, reason: str = "") -> None:
        """Give a claim back. `SI-21`'s lesson (a rollback must not strand state it created) applied to the
        roadmap — and, since `SI-51`, the same function `abort` uses to release work that stopped.

        `expect_owner` is the caller SAYING whose claim it is releasing, and it is the difference between a
        repair and a second defect. `abort` acts on one instant and must never free a milestone a
        *different* instant is running; `dispatch`'s rollback made the claim itself moments earlier and has
        no second party to protect against, so it passes nothing and the check does not apply.

        Idempotent when the milestone has no owner: `abort` calls this after the folder has already been
        renamed, so a second pass — or an abort of an instant that claimed nothing — must be a no-op and
        not a failure that reports the abort as broken. Nothing is recorded in that case either: writing a
        release reason onto a milestone nobody claimed invents an event.
        """
        with held_for_update(self.path):
            data = self._load()
            for entry in data["milestones"]:
                if entry["id"] != milestone_id:
                    continue
                held = entry.get("owner")
                if not held:
                    return
                if expect_owner is not None and str(held) != str(expect_owner):
                    raise BadInput(
                        f"milestone {milestone_id!r} is claimed by {held!r}, not by {str(expect_owner)!r}, "
                        f"so this release would free work somebody else is running. Refused. If {held!r} "
                        f"is gone, release it with `fleet milestone --instant <coordinator> --id "
                        f"{milestone_id} --disown --reason <why>`, which checks whether that owner still "
                        f"has an open record before it clears anything.")
                entry["owner"] = None
                entry["disowned_reason"] = str(reason or "")
                self._save(self.path, data)
                return
            raise BadInput(f"no milestone {milestone_id!r} in {self.path}")

    def blocker_of(self, milestone_id: str) -> str:
        """Why this ONE milestone is not ready, or None if it is. Reads `_readiness`, deliberately: `ready`,
        `report` and this must never be able to disagree about the same milestone (`SI-26` needed a
        per-milestone answer at the moment one is added, and computing it a second way is how the coordinator
        ends up told a milestone is ready by one verb and blocked by another)."""
        for m, blocker, _, _, _ in self._readiness():
            if m.id == milestone_id:
                return blocker
        raise BadInput(f"no milestone {milestone_id!r} in {self.path}")

    # ------------------------------------------------------------------ propose / apply

    def propose(self, instant: Path, milestone: str, status: str,
                evidence: list, note: str = "") -> Proposal:
        """The WORKER's verb (UC-3). Writes `proposals.json` and NOTHING else — in particular it never
        opens `roadmap.json` for writing, which is why a worker cannot move the registry even by mistake.

        `note` is optional narrative (`I-2`) and is checked by nothing, deliberately: it is prose, and
        prose is not proof. `_check_evidence` still refuses an empty evidence list below, so a note
        cannot become the way to make an unevidenced claim.
        """
        self.milestone(milestone)          # an unknown milestone is refused at the producer
        proposal = Proposal(instant=str(Path(instant)), milestone=milestone,
                            status=_check_status(status),
                            evidence=_check_evidence(evidence, milestone), at=_now(),
                            note=" ".join(str(note or "").split()))
        with held_for_update(self.proposals_path):        # FI-30c
            data = self._load_proposals()
            data["pending"].append(asdict(proposal))
            self._save(self.proposals_path, data)
        return proposal

    def proposals(self) -> list:
        return [Proposal(**d) for d in self._load_proposals()["pending"]]

    def applied(self) -> list:
        """The proposals `apply` has consumed, oldest first. Read-only: `harvest`'s unreported-work guard
        needs "did this worker's report ARRIVE", and a report the coordinator already applied arrived."""
        return [Proposal(**d) for d in self._load_proposals()["applied"]]

    def closed(self) -> list:
        """`B02`. The proposals that left `pending` WITHOUT being applied, oldest first, as dicts: the
        proposal's fields plus `closed_as` (superseded/withdrawn/retired), `closed_at`, `closed_reason`
        and, for a superseded row, `superseded_by` = {instant, status, at}. Read-only."""
        return [dict(d) for d in self._load_proposals()["closed"]]

    @staticmethod
    def _close(inbox: dict, rows: list, closed_as: str, reason: str, by: dict = None) -> None:
        """Move `rows` (dicts, each in `inbox["pending"]`) to `closed`. The caller holds the lock and
        saves. One helper for the three exits, so the recorded shape cannot drift between them."""
        stamp = _now()
        for row in rows:
            inbox["pending"].remove(row)
            entry = dict(row, closed_as=closed_as, closed_at=stamp, closed_reason=str(reason))
            if by is not None:
                entry["superseded_by"] = {"instant": by["instant"], "status": by["status"], "at": by["at"]}
            inbox["closed"].append(entry)

    def _terminal_refusal(self, entry: dict, proposal: Proposal, reopen: bool):
        """The D-3 door, judged against a milestone entry the caller already loaded."""
        current = entry["status"]
        if reopen or current not in TERMINAL or proposal.status == current:
            return None
        return (f"milestone {proposal.milestone!r} is already {current}, which is terminal, and this row "
                f"({proposal.status} at {proposal.at}) would move it back out — the same finished record "
                f"`milestone --retire` refuses to rewrite"
                + (f" (retired: {entry.get('retired_reason')})" if entry.get("retired_reason") else "")
                + f". Refused, and the row stays pending. If it is residue, `fleet withdraw --instant "
                f"{self.instant} --milestone {proposal.milestone} --at {proposal.at} --reason "
                f"<why>` closes it; if re-opening the milestone is intended, apply it with `--reopen`.")

    def apply_refusal(self, proposal: Proposal, reopen: bool = False):
        """`B02`. Why `apply` would refuse this row, else None — the same judgement `apply` makes under its
        lock, exposed so a dry run evaluates the gate the real run enforces."""
        for entry in self._load()["milestones"]:
            if entry["id"] == proposal.milestone:
                return self._terminal_refusal(entry, proposal, reopen)
        return f"no milestone {proposal.milestone!r} in {self.path}; refusing to invent one"

    def apply(self, proposal: Proposal, reopen: bool = False) -> Milestone:
        """The COORDINATOR's verb and THE single writer of a milestone status.

        Validation happens here rather than only in `propose`, because a proposal can be hand-built or
        replayed from a file: a gate that only guards the polite path is not a gate.

        `B02`: it lands ONE row. Every EARLIER pending row for the same milestone is closed as superseded
        by it (`_consume`) — its status and evidence were never decided on, and applying them in file order
        is how a typo'd superseded path came to sit on a milestone. And it refuses to move a TERMINAL
        milestone to a different status unless `reopen` — the door `retire` already keeps shut, so residue
        can no longer resurrect a retired milestone. `reopen` out of `dropped` also clears
        `retired_reason`, which would otherwise explain why a live milestone is not live."""
        status = _check_status(proposal.status)
        evidence = _check_evidence(proposal.evidence, proposal.milestone)
        # FI-30c. `_consume` is called INSIDE this lock and takes its own on `proposals_path` — a
        # different file, and always in this order (roadmap then proposals), which is the only order any
        # path here uses. Two locks acquired in one order cannot deadlock against themselves.
        with held_for_update(self.path):
            data = self._load()
            for d in data["milestones"]:
                if d["id"] == proposal.milestone:
                    refusal = self._terminal_refusal(d, proposal, reopen)
                    if refusal:
                        raise BadInput(refusal)
                    if reopen and d["status"] == "dropped" and status != "dropped":
                        d["retired_reason"] = ""
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
        `report()` stops asking the coordinator for something it has already done.

        `B02`: so does every pending row for the same milestone that arrived BEFORE it — list order is
        arrival order, because `propose` appends under this same lock — closed as superseded by it. Rows
        that arrived after it are newer claims and stay pending. A hand-built proposal that is not in the
        inbox supersedes nothing: there is no position to be newer than."""
        with held_for_update(self.proposals_path):        # FI-30c
            data = self._load_proposals()
            body = asdict(proposal)
            pending = data["pending"]
            if body in pending:
                at = last_index(pending, body)
                earlier = [r for r in pending[:at] if r["milestone"] == body["milestone"]]
                del pending[at]
                data["applied"].append(body)
                if earlier:
                    self._close(data, earlier, SUPERSEDED,
                                f"a newer row for {body['milestone']} was applied", by=body)
                self._save(self.proposals_path, data)

    def select(self, milestone: str, at: str = None):
        """`B02`'s selector: -> (the row `apply` would land, the earlier rows it would supersede, the later
        rows it would leave pending), all `Proposal`s for `milestone`. The newest row unless `at` names
        one; refused when nothing is pending or `at` does not name exactly one row. A read — `apply` makes
        the same cut under its lock (`_consume`), so a dry run and the real run agree."""
        rows = [r for r in self._load_proposals()["pending"] if r["milestone"] == milestone]
        if not rows:
            raise BadInput(
                f"no pending proposal names milestone {milestone!r} in {self.proposals_path}, so there "
                "is nothing to apply or withdraw. `apply` applies a worker's proposal; it does not invent a "
                "status.")
        chosen = _one_at(rows, at, milestone, self.proposals_path)[0] if at is not None else rows[-1]
        cut = last_index(rows, chosen)
        return (Proposal(**chosen), [Proposal(**r) for r in rows[:cut]],
                [Proposal(**r) for r in rows[cut + 1:]])

    def withdraw(self, milestone: str, reason: str, at: str = None) -> list:
        """`B02`. Close pending rows for `milestone` WITHOUT applying them — all of them, or the one whose
        `at` is given — and return them. Writes `proposals.json` and nothing else: a withdrawn row never
        moved the roadmap, so withdrawing it cannot either.

        Refused with no reason (a report that vanished with no recorded why is the loss this list exists to
        prevent), for an unknown milestone, and when nothing matches. A stamp matching several rows selects
        none: `at` has one-second resolution, and picking one of two would be choosing for the caller."""
        reason = " ".join(str(reason or "").split())
        if not reason:
            raise BadInput(f"withdrawing a proposal for {milestone!r} needs a --reason; a report that left "
                           f"the inbox with no recorded why cannot be told apart from one that was lost")
        self.milestone(milestone)
        with held_for_update(self.proposals_path):
            data = self._load_proposals()
            rows = [r for r in data["pending"] if r["milestone"] == milestone]
            if at is not None:
                rows = _one_at(rows, at, milestone, self.proposals_path)
            if not rows:
                raise BadInput(f"no pending proposal names milestone {milestone!r} in "
                               f"{self.proposals_path}, so there is nothing to withdraw")
            self._close(data, rows, WITHDRAWN, reason)
            self._save(self.proposals_path, data)
        return [Proposal(**r) for r in rows]


    # ------------------------------------------------------------------ the report

    @staticmethod
    def _ready_row(m: Milestone) -> Row:
        """`B04`. A ready milestone, as a row. INFO: ready work is the healthy state of a roadmap, and an
        `attention` row on a normal state trains the reader to scroll past the one that matters (`FI-2`).

        A CLAIMED ready milestone is still `ready` — readiness is derived from deps alone and never reads
        the owner (`--owner`: "informational only") — so the row says which of the two it is and the
        `owner` field carries it for a machine: `kind == ready and owner == ""` is the dispatchable set."""
        if m.owner:
            state = f"claimed by {m.owner} — already dispatched, so not dispatchable"
            when, who = f"{m.owner} proposes its next status and the coordinator applies it", m.owner
        else:
            state = "unclaimed — dispatchable now"
            when, who = f"the coordinator dispatches it (`fleet dispatch … --milestone {m.id}`)", COORDINATOR
        deps = ", ".join(repr(d) for d in m.deps)
        why = f"every dep has LANDED ({deps})" if m.deps else "it has no deps"
        return Row(kind=READY, subject=m.id, severity=INFO,
                   detail=f"READY: {m.title!r} — {why}; status={m.status}; {state}",
                   clears_when=when, clears_who=who, title=m.title, owner=m.owner or "")

    def report(self) -> list:
        """Everything the coordinator has to act on, plus the population it was derived from.

        The population row is last and always present: a checker that narrows its scope silently reads as
        a pass (`OBS-49`), and a legitimately empty roadmap is reported rather than RED."""
        rows = []
        for m, blocker, clears_when, clears_who, severity in self._readiness():
            if blocker is None:
                rows.append(self._ready_row(m))
                continue
            #: `severity` comes from `_blocker`, which is the only thing that knows WHY (`FI-2`).
            rows.append(Row(kind=NOT_READY, subject=m.id, detail=blocker,
                            severity=severity,
                            clears_when=clears_when, clears_who=clears_who,
                            title=m.title, owner=m.owner or ""))

        milestones = self.milestones()
        by_id = {m.id: m for m in milestones}
        pending = self.proposals()
        #: `B02` (i26(b-2)). Which row `apply` would land for each milestone — the last one to arrive — so
        #: the others can SAY they are superseded instead of reading identically to the current one, and
        #: which of those `apply` would refuse (D-3). Still one row per pending proposal: this marks rows,
        #: it does not select them (B04 owns selection). The `proposes <id> -> <status> at <ts>` phrase is
        #: unchanged, because coordinator tooling parses it.
        newest = {p.milestone: p for p in pending}
        entries = {d["id"]: d for d in self._load()["milestones"]}
        #: Milestones whose newest row `apply` would refuse: their superseded rows cannot be closed by a plain
        #: apply, so their remedy must not promise one.
        stale_newest = {m for m, p in newest.items()
                        if m in entries and self._terminal_refusal(entries[m], p, reopen=False)}
        superseded = stale = 0
        for p in pending:
            base = (f"{_proposer(p.instant)} proposes {p.milestone} -> {p.status} at {p.at} with "
                    f"{len(p.evidence)} evidence item(s); the roadmap is UNCHANGED until the "
                    "coordinator applies it")
            #: The note goes FIRST when there is one (`I-2`). It is the proposer's one line about why this
            #: proposal exists, and a coordinator scanning an inbox reads the front of the row. Omitted
            #: entirely when empty rather than rendered as `""` — every proposal written before the field
            #: existed has none, and empty quotes on every existing row is noise added to the view this was
            #: meant to improve.
            note = f'"{p.note}" — ' if p.note else ""
            entry = entries.get(p.milestone)
            milestone = by_id.get(p.milestone)
            #: `B04`: which milestone this proposal is about, as fields — empty for one no longer on the roadmap.
            about = {"title": milestone.title if milestone else "",
                     "owner": (milestone.owner or "") if milestone else ""}
            withdraw = (f"`fleet withdraw --instant {self.instant} --milestone {p.milestone} --at {p.at} "
                        f"--reason <why>`")
            if newest[p.milestone] is not p:
                superseded += 1
                rows.append(Row(
                    kind=PENDING_PROPOSAL, subject=p.milestone,
                    detail=(f"SUPERSEDED by the row at {newest[p.milestone].at}: " + note + base),
                    severity=INFO,
                    clears_when=(f"the newer row is STALE, so no plain apply will close this one; {withdraw} "
                                 f"closes it" if p.milestone in stale_newest else
                                 f"closed as superseded when a newer row for {p.milestone} is applied; "
                                 f"{withdraw} closes it now"),
                    clears_who=COORDINATOR, **about))
            elif p.milestone in stale_newest:
                stale += 1
                rows.append(Row(
                    kind=PENDING_PROPOSAL, subject=p.milestone,
                    detail=(f"STALE: {p.milestone} is already {entry['status']}, and `apply` refuses to move "
                            f"a terminal milestone without --reopen: " + note + base),
                    severity=ATTENTION,
                    clears_when=(f"{withdraw} if it is residue, or `fleet apply --instant {self.instant} "
                                 f"--milestone {p.milestone} --reopen` if re-opening is intended"),
                    clears_who=COORDINATOR, **about))
            else:
                rows.append(Row(
                    kind=PENDING_PROPOSAL, subject=p.milestone, detail=note + base,
                    severity=ATTENTION,
                    clears_when="the coordinator applies the proposal (single writer)",
                    clears_who=COORDINATOR, **about))

        #: Counted from the `ready` rows already built (`B04`), so the number and the rows agree by construction.
        ready = sum(1 for r in rows if r.kind == READY)
        rows.append(Row(
            kind=POPULATION, subject=str(self.instant),
            detail=(f"examined {len(milestones)} milestone(s) of which {ready} ready, "
                    f"{len(pending)} pending proposal(s) ({superseded} superseded, {stale} against a "
                    f"terminal milestone), from {self.path}"),
            severity=INFO))
        return rows
