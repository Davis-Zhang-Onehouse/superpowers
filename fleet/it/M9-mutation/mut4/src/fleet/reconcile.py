"""The ONE join: record ∧ liveness ∧ disk ∧ lease ∧ pane → exactly one state per subject.

**Nothing else in this package computes a state value.** Three independent bugs in the predecessor had
one shape — *a report that instructs action on a stale premise* — because three views each derived state
from a different subset of the facts. `board` called a dead session PARKED and counted it in "N sessions
need you" while `health` called the same records DEAD (`W2-14`/`OBS-57`); and *"the one that is wrong is
the one everybody reads."* One join removes the possibility of disagreement rather than fixing an
instance of it.

Three properties here are requirements, not implementation details:

1. **Enumeration is process-first.** It starts at `sessions.live()` and joins records onto processes,
   not the other way round. A records-first join is *structurally* unable to see a session nobody wrote
   down, and `OBS-48` measured one sitting idle 8d20h. A process with no record is still a subject; a
   record with no process is still a subject.
2. **This module never writes anything.** Not a record, not a declaration, not a lease. The
   predecessor's `health` back-filled `launched_at` *during a read*, which made a report a writer — and
   a writer that runs on every glance is a writer nobody audits. `PENDING-LAUNCH` is therefore *read*
   from an absent `launched_at`; it is never stamped.
3. **Only slot-holding subjects report `holds_slot`.** FD-4: the board renders those and nothing else,
   which is what keeps it small enough to be read.

Every control signal comes from structured state. The phase is read through `store.Declarations`, so a
`HANDOFF.md` that *talks* about `Phase: AWAITING-CI` changes nothing (`RCF-9`, made unreachable rather
than patched). No `.md` file is opened here at all.
"""
import time
from dataclasses import dataclass
from pathlib import Path

from fleet.identity import InstantName, resolve
from fleet.store import Declarations

# --- the state vocabulary. This tuple is the whole domain; a value outside it is a bug. -----------
PENDING_LAUNCH = "PENDING-LAUNCH"
RUNNING = "RUNNING"
IDLE = "IDLE"
BLOCKED = "BLOCKED"
PARKED = "PARKED"
AWAITING_CI = "AWAITING-CI"
COMPLETE = "COMPLETE"
DEAD = "DEAD"
UNKNOWN_SESSION = "UNKNOWN-SESSION"
STALE_LEASE = "STALE-LEASE"

STATES = (PENDING_LAUNCH, RUNNING, IDLE, BLOCKED, PARKED, AWAITING_CI, COMPLETE, DEAD,
          UNKNOWN_SESSION, STALE_LEASE)

KIND_WORKER = "worker"
KIND_UNKNOWN = "unknown-session"
KIND_STALE_LEASE = "stale-lease"
KINDS = (KIND_WORKER, KIND_UNKNOWN, KIND_STALE_LEASE)

#: States a human can act on right now. A standing declaration may annotate one of these and may never
#: replace it: masking an actionable state "sends you to the wrong problem, and the wrong problem is one
#: you cannot fix" (`OBS-7`).
ACTIONABLE_STATES = (BLOCKED,)

#: Folder states that mean the work is over. The instant's own rename is the completion signal, so disk
#: outranks the record here — the record's path is what goes stale, never the folder.
TERMINAL_FOLDER_STATES = ("complete", "abort")

#: The declared phase that means "not consuming attention, waiting on CI".
PHASE_AWAITING_CI = "awaiting-ci"


@dataclass(frozen=True)
class Subject:
    """One thing in the fleet, with exactly one state and the evidence that produced it.

    `identity` is machine-readable and unique across the returned list — `OBS-62` was an assertion
    anchored to a rendered summary line, which could never match. There is deliberately no `reapable`
    field: what may be killed is a policy decision, and an unknown session is reported and never
    touched, because *"some of those sessions are people's"* (D-6).
    """

    kind: str
    identity: str
    state: str
    holds_slot: bool
    evidence: dict
    note: str


def reconcile(store, pool, sessions, instants_dir: Path, idle_after_s: int = 1800) -> list:
    """Join every fact about the fleet into one subject list.

    Order is the join order: live processes first, then records nothing live matched, then leases no
    subject accounts for. Pure — it reads `store`, `pool`, `sessions` and the filesystem, and writes
    nothing to any of them.
    """
    instants_dir = Path(instants_dir)
    records = list(store.all())
    record_by_tmux = {}
    for rec in records:
        if rec.tmux:
            record_by_tmux.setdefault(rec.tmux, rec)

    live_sessions = list(sessions.live())
    subjects, seen_records, accounted_slots = [], set(), set()

    # --- pass 1: PROCESS-FIRST. Start from what is running, whatever the records say. -------------
    for sess in live_sessions:
        rec = record_by_tmux.get(sess.name) if sess.name else None
        if rec is not None:
            if rec.todo_id in seen_records:
                continue                     # one record, one subject, even with two processes on it
            seen_records.add(rec.todo_id)
            subject = _worker_subject(rec, pool, sessions, instants_dir, idle_after_s,
                                      live=True, sess=sess)
            if subject.holds_slot:
                accounted_slots.add(rec.slot)
            subjects.append(subject)
        else:
            slot = _slot_holding(pool, sess.cwd)
            if slot:
                accounted_slots.add(slot)
            subjects.append(_unknown_subject(sess, slot))

    # --- pass 2: records with no live process. Still subjects — that is the point of the join. ----
    for rec in sorted(records, key=lambda r: r.todo_id):
        if rec.todo_id in seen_records:
            continue
        seen_records.add(rec.todo_id)
        subject = _worker_subject(rec, pool, sessions, instants_dir, idle_after_s,
                                  live=sessions.alive(rec.tmux), sess=None)
        if subject.holds_slot:
            accounted_slots.add(rec.slot)
        subjects.append(subject)

    # --- pass 3: leases no subject above accounts for. -------------------------------------------
    for slot in pool.slots():
        lease = pool.lease(slot)
        if lease is None or slot in accounted_slots or lease.todo_id in seen_records:
            continue
        subjects.append(_lease_subject(slot, lease, sessions, live_sessions))

    return subjects


# --- workers ---------------------------------------------------------------------------------------


def _worker_subject(rec, pool, sessions, instants_dir: Path, idle_after_s: int, live: bool, sess):
    instant = _instant_on_disk(rec, instants_dir)
    folder_state = _folder_state(instant)
    declared = Declarations(instant) if instant is not None else None
    phase = declared.phase() if declared is not None else None
    parked = declared.parked() if declared is not None else None
    pane = sessions.pane(rec.tmux) if (live and rec.tmux) else ""

    state, note = _state_of(rec, folder_state, live, phase, parked, pane, sessions,
                            instant, idle_after_s)
    holds = _holds_slot(pool, rec)
    evidence = {
        "record": rec.todo_id,
        "base": rec.base_instant,
        "instant": str(instant) if instant is not None else f"{rec.child_instant} (missing)",
        "folder_state": folder_state or "missing",
        "liveness": "process" if sess is not None else ("session" if live else "none"),
        "tmux": rec.tmux,
        "pid": str(sess.pid) if sess is not None else "",
        "slot": rec.slot if holds else "",
        #: `SI-27`. Joined here rather than looked up per view, so `board` and `status` cannot disagree
        #: about which milestone an instant is on.
        "milestone": rec.milestone or "",
        "lease": "held" if holds else "released",
        "declared_phase": phase or "",
        "parked": parked or "",
        "pane": _pane_summary(sessions, pane) if live else "",
    }
    return Subject(kind=KIND_WORKER, identity=rec.todo_id, state=state, holds_slot=holds,
                   evidence=evidence, note=note)


def _state_of(rec, folder_state, live, phase, parked, pane, sessions, instant, idle_after_s):
    """The single state decision. Every branch is reachable from one join of all five fact sources."""
    if folder_state in TERMINAL_FOLDER_STATES:
        # The worker's own rename is the completion signal, and it outranks the recorded path — that is
        # what "a renamed instant is followed" means. `abort` is terminal too: W2-21's fix reached
        # inflight and complete and never abort, and abort is legal.
        return COMPLETE, f"the instant folder is `-{folder_state}-`; the work is over"
    if not live:
        if rec.launched_at is None:
            # READ from an absent field, never stamped. Back-filling it here is exactly the defect that
            # made the predecessor's report a writer.
            return PENDING_LAUNCH, "dispatched, with no launch recorded and no live session"
        return DEAD, (f"launched at {rec.launched_at} and no session is alive: the work stopped "
                      "without renaming its folder")
    return _live_state(phase, parked, pane, sessions, instant, idle_after_s)


def _live_state(phase, parked, pane, sessions, instant, idle_after_s):
    waiting = sessions.unsubmitted(pane)
    busy = sessions.busy(pane)
    if waiting and not busy:
        # A pane holding text nobody submitted needs a keystroke: a modal, or a swallowed submit. Text
        # queued while the agent is still working is not blocked — it is queued, and it will be sent.
        state, note = BLOCKED, f"the pane is waiting on a human: {waiting!r}"
    elif phase == PHASE_AWAITING_CI:
        state, note = AWAITING_CI, "declared awaiting-ci; not consuming attention"
    elif busy:
        state, note = RUNNING, ""
    elif _idle_for(instant) > idle_after_s:
        state, note = IDLE, (f"live, but nothing has changed in the instant for more than "
                             f"{idle_after_s}s and the pane is not working")
    else:
        state, note = RUNNING, ""

    if parked:
        if state in ACTIONABLE_STATES:
            # An actionable state is never masked by a standing note; the park is APPENDED.
            note = f"{note}; parked decision stands: {parked}"
        elif busy:
            # OBS-3: "a parked note while still working is just a note". A permanently-red tick trains
            # everyone to ignore red.
            state, note = RUNNING, (f"declared parked and progressing anyway — a parked note while "
                                    f"still working is just a note: {parked}")
        else:
            state, note = PARKED, f"parked decision: {parked}"
    return state, note


def _holds_slot(pool, rec) -> bool:
    """True only when the pool leases this subject's slot TO THIS SUBJECT (FD-4).

    A harvested record names the slot it used and no longer holds it; reporting that as held is how the
    board filled with rows nobody could clear.
    """
    if not rec.slot:
        return False
    lease = pool.lease(rec.slot)
    return lease is not None and lease.todo_id == rec.todo_id


# --- unknown sessions ------------------------------------------------------------------------------


def _unknown_subject(sess, slot: str):
    """A live session no record claims. Reported, never acted on.

    `OBS-48` found one idle 8d20h, invisible to every records-first sweep. It carries no authorisation
    to end it, deliberately: *"a tool that can kill a session it does not understand is a tool nobody
    will leave armed, and some of those sessions are people's"* (D-6).
    """
    label = sess.name or f"pid{sess.pid}"
    evidence = {
        "pid": str(sess.pid),
        "cwd": str(sess.cwd),
        "session": sess.name or "",
        "record": "none",
        "slot": slot or "",
    }
    note = ("no dispatch record claims this session; it is reported so a human can decide, and this "
            "tool does nothing to it")
    return Subject(kind=KIND_UNKNOWN, identity=f"session:{label}:{sess.pid}",
                   state=UNKNOWN_SESSION, holds_slot=bool(slot), evidence=evidence, note=note)


def _slot_holding(pool, cwd: Path) -> str:
    """The leased slot a live cwd sits inside, or "". Joins a process to a lease without a record."""
    cwd = Path(cwd)
    for slot in pool.slots():
        lease = pool.lease(slot)
        if lease is None:
            continue
        path = Path(lease.path)
        if cwd == path or path in cwd.parents:
            return slot
    return ""


# --- leases nothing else accounts for --------------------------------------------------------------


def _lease_subject(slot: str, lease, sessions, live_sessions: list):
    """A lease with no record in this store.

    Live: an unknown holding a slot. Not live: a stale lease, and the note NAMES ITS OWNER — `RI-31`'s
    ownership guard refused *correctly* and read as a bug purely because it never said whose lease it
    was. "Not yours to clear" is a state, not a failure.
    """
    owner = lease.base_instant or "an untagged (legacy) claim"
    evidence = {
        "slot": slot,
        "path": str(lease.path),
        "record": "none",
        "lease_todo": lease.todo_id,
        "lease_owner": lease.base_instant or "",
        "tmux": lease.tmux,
        "claimed_at": lease.claimed_at,
    }
    if sessions.alive(lease.tmux) or any(Path(s.cwd) == Path(lease.path) for s in live_sessions):
        return Subject(kind=KIND_UNKNOWN, identity=f"lease:{slot}", state=UNKNOWN_SESSION,
                       holds_slot=True, evidence=evidence,
                       note=(f"slot {slot} is leased to {lease.todo_id} by {owner} with no record in "
                             "this store, and something is still alive in it"))
    return Subject(kind=KIND_STALE_LEASE, identity=f"lease:{slot}", state=STALE_LEASE,
                   holds_slot=True, evidence=evidence,
                   note=(f"slot {slot} holds a stale lease owned by {owner} (todo "
                         f"{lease.todo_id}, tmux {lease.tmux}); its owner clears it"))


# --- disk ------------------------------------------------------------------------------------------


def _instant_on_disk(rec, instants_dir: Path):
    """The instant's CURRENT folder, following the rename the recorded path predates.

    Resolution goes through `identity.resolve`, which matches on the full stable key with only `state`
    varying and refuses an ambiguous match rather than picking a sibling (`OBS-14`).
    """
    if not rec.child_instant:
        return None
    recorded = Path(rec.child_instant)
    if not recorded.is_absolute():
        recorded = instants_dir / recorded
    found = resolve(recorded)
    if found is None and recorded.parent != instants_dir:
        found = resolve(instants_dir / recorded.name)
    return found


def _folder_state(instant):
    """The `<state>` field of the folder name, or None. The name is parsed by `identity` and nowhere
    else; a folder that is not an instant contributes no state."""
    if instant is None:
        return None
    try:
        return InstantName.parse(instant.name).state
    except Exception:
        return None


def _idle_for(instant) -> float:
    """Seconds since anything in the instant last changed. Read-only, and shallow on purpose: the
    instant root, its files and `.fleet/` are where a working worker leaves marks."""
    if instant is None:
        return 0.0
    newest = 0.0
    for path in _activity_paths(instant):
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    if not newest:
        return 0.0
    return max(0.0, time.time() - newest)


def _activity_paths(instant):
    yield instant
    try:
        children = list(instant.iterdir())
    except OSError:
        return
    for child in children:
        yield child
        if child.name == ".fleet" and child.is_dir():
            try:
                for grandchild in child.iterdir():
                    yield grandchild
            except OSError:
                continue


def _pane_summary(sessions, pane: str) -> str:
    if sessions.busy(pane):
        return "working"
    if sessions.unsubmitted(pane):
        return "waiting on a human"
    return "quiet"
