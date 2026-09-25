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
import calendar
import time
from dataclasses import dataclass
from pathlib import Path

from fleet.identity import InstantName, resolve
from fleet.store import ATTESTED_PREFIX, Declarations
from fleet.session import SessionLayer

# --- the state vocabulary. This tuple is the whole domain; a value outside it is a bug. -----------
PENDING_LAUNCH = "PENDING-LAUNCH"
RUNNING = "RUNNING"
IDLE = "IDLE"
BLOCKED = "BLOCKED"
PARKED = "PARKED"
AWAITING_CI = "AWAITING-CI"
COMPLETE = "COMPLETE"
COMPLETE_BUT_WORKING = "COMPLETE-BUT-WORKING"
HARVESTED = "HARVESTED"
CLOSED = "CLOSED"
DEAD = "DEAD"
#: `SI-39`. A live process holds this record's SLOT, but no session answers for its tmux name. The work is
#: running; what is missing is our ability to reach its session — almost always because the caller is
#: pointed at the wrong tmux SERVER (`FLEET_TMUX_SOCKET`).
#:
#: This is emphatically not DEAD, and the difference was measured on live work: with the socket unset,
#: `board` reported both instants of a running effort as *"launched at ... and no session is alive: the
#: work stopped without renaming its folder"* while both processes were an hour into their tasks. DEAD is
#: an ACTIONABLE claim — the response to it is `reap` — so a wrong DEAD invites a human to free a slot out
#: from under running work. (`reap` itself refuses, because its cwd-holder half reads `/proc` and never
#: asks tmux; this state gives the REPORT the same independence the safety net already had.)
UNREACHABLE = "UNREACHABLE"
UNKNOWN_SESSION = "UNKNOWN-SESSION"
STALE_LEASE = "STALE-LEASE"

STATES = (PENDING_LAUNCH, RUNNING, IDLE, BLOCKED, PARKED, AWAITING_CI, COMPLETE, COMPLETE_BUT_WORKING, HARVESTED, CLOSED,
          DEAD, UNREACHABLE, UNKNOWN_SESSION, STALE_LEASE)

KIND_WORKER = "worker"
KIND_UNKNOWN = "unknown-session"
KIND_STALE_LEASE = "stale-lease"
KINDS = (KIND_WORKER, KIND_UNKNOWN, KIND_STALE_LEASE)

#: States a human can act on right now. A standing declaration may annotate one of these and may never
#: replace it: masking an actionable state "sends you to the wrong problem, and the wrong problem is one
#: you cannot fix" (`OBS-7`).
#:
#: `IDLE` added for `FI-14`, reported by a coordinator driving real workers. This package DETECTS a
#: stalled worker — `IDLE` is a first-class state on a 30-minute threshold (`idle_after_s`) and it
#: renders exactly the right sentence, *"live, but nothing has changed in the instant for more than
#: 1800s and the pane is not working"* — and then threw the judgement away, because the only consumer of
#: it is this tuple and `IDLE` was not in it. A worker stopped for over half an hour never appeared in
#: the "N needs you" count, so the OPERATOR was the thing noticing stalled workers and restarting them.
#: The detector, the threshold and the wording all existed; nothing read them.
#:
#: The inversion is what makes this a defect rather than a preference. `BLOCKED` was already here, and
#: per `FI-9` `BLOCKED` is the state that fires when a human is attached and mid-sentence — so the banner
#: called for attention on a human who was already present, and stayed silent on a worker that had
#: stopped. Exactly backwards.
#:
#: `B24` (x2 `G-4`) closed the other half of that inversion. `BLOCKED` stays here — a worker stopped at a
#: permission modal has no `park.json`, so narrowing its source would delete the very signal it exists for
#: (the reporter's retracted remedy) — and the subject carries `attended` when the pane's own BLOCKED is in
#: front of a human who is attached and typing. `needs_a_human` does not count that one.
#:
#: Deliberately still narrow. `DEAD` needs a reap, not a keystroke, and counting it here is the defect
#: `W2-14`/`OBS-57` recorded: a banner that cries for attention on a session nobody can answer trains
#: people to ignore the banner. That is the same failure this fix is curing, so widening past what a
#: human can actually DO would trade one silence for one more thing to tune out.
#:
#: `PARKED` added for `B06` (x2 `G-11`; prior art 4933291, on a branch that was never deployed). `fleet
#: park --question` is a child saying "I cannot proceed without a decision", and an empty question is refused,
#: so a park always asks somebody something. Excluded, a parked child rendered its question on the board
#: beside `0 needs you`, and it surfaced only by timing out into `IDLE` after 30 minutes, which turns a
#: question into a stall. The remedy is an answer, which a human can give, so this stays inside "what a
#: human can actually DO". A parked worker whose pane is still busy stays PARKED with `working=true`;
#: `needs_a_human` excludes that case, so progressing work does not make the banner shout.
ACTIONABLE_STATES = (BLOCKED, IDLE, PARKED)


def needs_a_human(subject) -> bool:
    """Whether this subject is waiting on a person RIGHT NOW. The one authority; views transport it.

    `ACTIONABLE_STATES` covers the cases a state alone decides. This exists because `FI-12` is not one of
    them: a COMPLETE instant that still holds a workspace needs a `harvest`, and a COMPLETE instant that
    has been harvested needs nobody — same state, opposite answers, and the difference is `holds_slot`.
    Expressing that by adding COMPLETE to the tuple would have made every finished instant on the board
    shout forever.

    `FI-12`'s measurement: an instant whose own row read *"the work is over"* held `ws6` for TWENTY-TWO
    HOURS while `reconcile` reported thirteen `info` rows and nothing else. Eleven slots leaked this way
    once. The rename is the WORKER's transition; releasing the slot is a separate coordinator-side act,
    and nothing connected the two.

    Kept to what a human can actually DO. `DEAD` needs a reap, not a keystroke, and counting it is the
    defect `W2-14`/`OBS-57` recorded — a banner nobody can answer is a banner people learn to ignore,
    which is the same failure `FI-14` and `FI-12` are both instances of.
    """
    if subject.state in ACTIONABLE_STATES:
        if subject.state == PARKED and subject.evidence.get("working") == "true":
            return False
        #: `B24`. A pane-level BLOCKED with a human attached and giving it input is that human's to finish;
        #: `attended` is only ever set for that case (see `_attended`), so every other state is untouched.
        return not subject.attended
    return subject.state == COMPLETE and subject.holds_slot

#: Folder states that mean the work is over. The instant's own rename is the completion signal, so disk
#: outranks the record here — the record's path is what goes stale, never the folder.
TERMINAL_FOLDER_STATES = ("complete", "abort")

#: The declared phase that means "not consuming attention, waiting on CI".
PHASE_AWAITING_CI = "awaiting-ci"

#: 4 h. The slowest required pair in the source effort is 3 h 20 m, so a shorter threshold would flag
#: every healthy wait and a flag that fires on correct work gets ignored.
STALE_WAIT_S = 4 * 60 * 60


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
    #: `B24`. True only for a BLOCKED read off the PANE (a dialog, unsubmitted text, codex's modal input)
    #: while a human is attached to that session and has given it input within the idle threshold: the
    #: thing on the pane is in front of somebody already. Not a state — the row still says BLOCKED and what
    #: the pane shows (B16's fence: add no state) — only the answer to "is somebody NOT here needed".
    attended: bool = False


def reconcile(store, pool, sessions, instants_dir: Path, idle_after_s: int = 1800,
              layer_for=None) -> list:
    """Join every fact about the fleet into one subject list.

    Order is the join order: live processes first, then records nothing live matched, then leases no
    subject accounts for. Pure — it reads `store`, `pool`, `sessions` and the filesystem, and writes
    nothing to any of them.

    `layer_for(socket) -> SessionLayer` lets a record be answered ON THE SERVER IT NAMES. `SI-59` shipped
    the field and then read past it: a worker whose record said `tmux_socket: fleet` was reported
    UNREACHABLE from a shell on `fleet-davis`, with the server it should have asked and the server it did
    ask printed on adjacent lines. Telling a reader to go and look is not looking.

    Optional, and `None` keeps the old single-server behaviour, because `reconcile` is called by tests and
    by callers that legitimately have one server. Consulted ONLY for a record that names a server other
    than the one in hand — never for a record with no socket, which is not measured and would turn every
    healthy board into a search over every server on the box.
    """
    instants_dir = Path(instants_dir)
    #: One layer per distinct foreign socket, built at most once. The cost of following an address is a
    #: probe set per SERVER, not per record, and that is what makes this affordable on a board where a
    #: whole wave was dispatched somewhere else.
    layers = {}

    def layer_of(socket):
        here = getattr(sessions, "socket", "") or ""
        if not socket or socket == here or layer_for is None:
            return sessions
        if socket not in layers:
            layers[socket] = layer_for(socket)
        return layers[socket]

    records = list(store.all())
    record_by_tmux = {}
    for rec in records:
        if rec.tmux and (not rec.tmux_socket or rec.tmux_socket == sessions.socket):
            record_by_tmux.setdefault(rec.tmux, rec)

    live_sessions = list(sessions.live())
    subjects, seen_records, accounted_slots = [], set(), set()
    #: RV-29. Records dispatched on ANOTHER tmux server: a same-named pane here is not theirs, and neither is their lease.
    elsewhere = {rec.todo_id for rec in records if rec.tmux_socket and rec.tmux_socket != sessions.socket}

    # --- pass 1: PROCESS-FIRST. Start from what is running, whatever the records say. -------------
    #: RV-25. Readable rows first (a stable sort, so their own order is kept): when one record's pane holds both, the
    #: process whose binary and cwd were read speaks for the record — not whichever pid `pgrep` happened to list first.
    #: v23-k: and the pane's OWN agent before any agent it started (`LiveSession.nested`). `pgrep` lists claude before
    #: codex, so a codex worker running `claude agents --json` was spoken for by that child — BLOCKED as a mismatch —
    #: and a claude record whose pane agent is codex was spoken for by a claude child and read RUNNING.
    for sess in sorted(live_sessions, key=lambda s: (bool(getattr(s, "nested", False)),
                                                     bool(getattr(s, "unreadable", False)))):
        rec = record_by_tmux.get(sess.name) if sess.name else None
        if rec is not None:
            if rec.todo_id in seen_records:
                continue                     # one record, one subject, even with two processes on it
            seen_records.add(rec.todo_id)
            subject = _worker_subject(rec, pool, sessions, instants_dir, idle_after_s,
                                      live=True, sess=sess, live_sessions=live_sessions)
            if subject.holds_slot:
                accounted_slots.add(rec.slot)
            subjects.append(subject)
        else:
            slot = _slot_holding(pool, sess.cwd) or _slot_leased_to_pane(pool, sess, elsewhere)
            if slot:
                accounted_slots.add(slot)
            subjects.append(_unknown_subject(sess, slot, live_sessions, sessions.socket))

    # --- pass 2: records with no live process. Still subjects — that is the point of the join. ----
    for rec in sorted(records, key=lambda r: r.todo_id):
        if rec.todo_id in seen_records:
            continue
        seen_records.add(rec.todo_id)
        #: The record's OWN server, when it names one. Everything else about this subject stays as it
        #: was: the slot holder is process evidence and deliberately not re-asked, since `/proc` does not
        #: care which tmux server anybody is pointed at.
        layer = layer_of(rec.tmux_socket)
        subject = _worker_subject(rec, pool, layer, instants_dir, idle_after_s,
                                  live=layer.alive(rec.tmux), sess=None,
                                  live_sessions=live_sessions if layer is sessions else ())
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


def _worker_subject(rec, pool, sessions, instants_dir: Path, idle_after_s: int, live: bool, sess,
                    live_sessions=()):
    if sessions.runtime != rec.runtime:
        sessions = SessionLayer(sessions.probes, rec.runtime)
    instant = _instant_on_disk(rec, instants_dir)
    folder_state = _folder_state(instant)
    declared = Declarations(instant) if instant is not None else None
    phase = declared.phase() if declared is not None else None
    parked = declared.parked() if declared is not None else None
    #: `RV-42`/`FI-7`. `capture()`, not `pane()`: a FAILED capture returns `None` and an EMPTY pane returns
    #: `""`, and anything that BRANCHES on absence has to tell them apart. `pane` keeps the flattened text
    #: for the readers that only scan it; `capture_failed` is what the watcher decision below consults.
    captured = sessions.capture(rec.tmux) if (live and rec.tmux) else ""
    pane = captured or ""

    #: The slot holder is PROCESS evidence and never touches tmux, so it survives being pointed at the
    #: wrong server — which is exactly when the tmux answer is the one that misleads.
    #:
    #: `SI-41`. Gated on `holds`, and that gate is the whole correctness of it. `rec.slot` is a slot NAME,
    #: and a TERMINATED record keeps naming the slot it used — so when that slot is re-leased, the dead
    #: record and the live one name the same `ws3`. Without this check the dead record inherits the live
    #: process's pid, and `evidence.pid` on a `COMPLETE` subject becomes the pid of somebody still working.
    #: That is not cosmetic: `scripts/fleet-finished-pids.sh` maps COMPLETE -> exclude-from-auto-resume by
    #: pid, so it silently switched auto-resume OFF for a live coordinator. Observed on the live effort.
    holds = _holds_slot(pool, rec)
    holder = _slot_holder_pid(rec, pool, live_sessions) if holds else None
    state, note, on_pane = _state_of(rec, folder_state, live, phase, parked, pane, sessions,
                                     instant, idle_after_s, holder, capture_failed=captured is None)
    if folder_state == "complete":
        watcher_kind, watcher_text = _watcher_of(pane, sessions, instant,
                                                 capture_failed=captured is None)
        busy = live and sessions.busy(pane)
        #: RV-C1. A harvested or closed record with no live session is over: its stale `awaiting-ci` claim (often a
        #: pid-less attestation nothing ever re-checks) must not resurrect it into the cap. Live evidence still wins.
        stamped_and_gone = bool(rec.harvested_at or rec.closed_at) and not live
        if busy or (phase == PHASE_AWAITING_CI and not stamped_and_gone and watcher_kind in
                    (WATCHER_OBSERVED, WATCHER_ATTESTED)):
            state = COMPLETE_BUT_WORKING
            note = ("the instant folder is `-complete-` but its pane is busy" if busy
                    else f"the instant folder is `-complete-` but its watcher is alive: {watcher_text}")
    if sess is not None and sess.runtime != rec.runtime:
        state, note = BLOCKED, f'live runtime {sess.runtime} differs from record runtime {rec.runtime}'
        on_pane = False
    unreadable = sess is not None and getattr(sess, "unreadable", False)
    if unreadable:
        #: FB-54. This record's session, placed by its pane through `stat`; that `/proc` failed is said, not hidden. Which
        #: read failed is not kept on the row, so the text does not guess (RV-24).
        note = (f"{note}; " if note else "") + (f"this record's session, unreadable: its process {sess.pid} could "
                                                f"not be read (a /proc read of it failed), and was placed by the "
                                                f"pane that owns it")
    attachment = sessions.attachment(rec.tmux) if (live and rec.tmux) else None
    #: `RV-32`. ONE clock read for the attachment, so the note and `evidence.attached` state one age.
    now = time.time()
    if attachment is not None and attachment.clients > 0 and attachment.last_input > now + 1:
        #: `RV-33`. Input stamped in the future means the clock stepped backwards; an age that cannot be true
        #: is not a measurement, and clamping it to 0 would have read it as "input 0s ago" — attended.
        attachment = None
    attended = False
    if state == BLOCKED and on_pane and not parked:
        attended, why = _attended(attachment, idle_after_s, now)
        if why:
            note = f"{note}; {why}"
    evidence = {
        "record": rec.todo_id,
        "runtime": rec.runtime,
        "runtime_executable": rec.runtime_executable,
        "runtime_config_dir": rec.runtime_config_dir,
        #: pt2. The model chosen at dispatch; "" = the CLI's configured default.
        "runtime_model": rec.runtime_model,
        "base": rec.base_instant,
        "instant": str(instant) if instant is not None else f"{rec.child_instant} (missing)",
        "folder_state": folder_state or "missing",
        "liveness": "process" if sess is not None else ("session" if live else "none"),
        "tmux": rec.tmux,
        #: `SI-59`. The SERVER beside the session name, because a name is not an address. Empty means the
        #: record predates the field — NOT MEASURED, never "the default server" — and the reader is told
        #: which server this command was talking to either way, so "no session answers" can be read as the
        #: local claim it is.
        "tmux_socket": rec.tmux_socket,
        "nested": ",".join(str(item.pid) for item in live_sessions
                            if item.name == rec.tmux and getattr(item, "nested", False)
                            and (not rec.tmux_socket or rec.tmux_socket == sessions.socket)),
        "working": "true" if parked and state == PARKED and sessions.busy(pane) else "false",
        "asked_server": getattr(sessions, "socket", "") or "",
        "pid": str(sess.pid) if sess is not None else (str(holder) if holder else ""),
        #: FB-54. `unreadable` when a `/proc` read of the process holding this record's pane failed; "" otherwise.
        "process": "unreadable" if unreadable else "",
        "slot": rec.slot if holds else "",
        #: `SI-27`. Joined here rather than looked up per view, so `board` and `status` cannot disagree
        #: about which milestone an instant is on.
        "milestone": rec.milestone or "",
        "lease": "held" if holds else "released",
        "declared_phase": phase or "",
        "parked": parked or "",
        "pane": _pane_summary(sessions, pane) if live else "",
        #: `B24`. Reported for every live worker, not only the BLOCKED ones, because the next consumer is an
        #: actuator (B12) that must not type into a pane a human is at, whatever its state.
        "attached": _attachment_summary(attachment, now) if live else "",
    }
    return Subject(kind=KIND_WORKER, identity=rec.todo_id, state=state, holds_slot=holds,
                   evidence=evidence, note=note, attended=attended)


def _attended(attachment, idle_after_s, now):
    """`(attended, why)` for a BLOCKED read off the pane. `B24`, x2 `G-4`.

    Attended means a client is attached AND has given the session input within `idle_after_s` — the same
    threshold that turns a quiet worker IDLE, so no new knob. Attachment alone is not enough: a terminal
    left attached overnight would otherwise silence a genuinely stuck modal forever, and nothing would
    ever surface it again. Unobserved is not attended: the count keeps the answer it gave before this fact
    was collected, so a tmux hiccup cannot hide a stuck worker. `why` is empty when nobody is attached, so
    a detached pane's note reads exactly as it always did.
    """
    if attachment is None:
        return False, "whether a human is attached could not be observed, so this is counted as waiting on one"
    if attachment.clients < 1:
        if attachment.observers:
            #: `RV-36`. Somebody may be there, but a read-only client cannot type into the pane and a
            #: control-mode client's `send-keys` does not move its `client_activity`, so nothing shows a human was
            #: at it recently.
            return False, ("a read-only or control-mode client is attached, which shows no input fleet can see, "
                           "so this is counted as waiting on a human")
        return False, ""
    quiet = max(0, int(now - attachment.last_input))
    clients = f"{attachment.clients} client{'s' if attachment.clients != 1 else ''}"
    if quiet > idle_after_s:
        return False, (f"{clients} attached but no input for {quiet}s (over {idle_after_s}s), so that is not "
                       f"taken as a human at the pane")
    return True, (f"a human is attached ({clients}, last input {quiet}s ago), so this is theirs to finish "
                  f"and is not counted as needing you")


def _attachment_summary(attachment, now) -> str:
    if attachment is None:
        return "not observed"
    #: `RV-36`. Never "no client" while an observer is attached: the next consumer is an actuator (B12).
    observed = (f"{attachment.observers} read-only or control-mode client"
                f"{'s' if attachment.observers != 1 else ''} (input not observable)") if attachment.observers else ""
    if attachment.clients < 1:
        return observed or "no client"
    interactive = (f"{attachment.clients} client{'s' if attachment.clients != 1 else ''}, last input "
                   f"{max(0, int(now - attachment.last_input))}s ago")
    return f"{interactive}; {observed}" if observed else interactive


def _slot_holder_pid(rec, pool, live_sessions):
    """The pid of a live process sitting in THIS record's slot, or None.

    `SI-39`. Two independent liveness derivations, and this is the one that does not go through tmux:
    a session lookup answers only for the server we happen to be pointed at, while a process holding a
    directory is true regardless. `pool.reap` has consulted both since `OBS-48`; `reconcile` consulted
    only the first, which is how a report could say DEAD about work that `reap` would refuse to free.

    Membership is delegated to `_slot_holding` rather than compared here. `rec.slot` is a slot NAME
    (`ws3`) and a session carries a PATH, so the two are never equal and a hand-rolled comparison is
    silently always-false — which is exactly the bug the first draft of this function shipped, and its
    test agreed with it because the fixture stored a path where the product stores a name. Reusing the
    existing rule also inherits its subtlety for free: a worker that has `cd`-ed into a subdirectory of
    its slot still holds it.
    """
    if not rec.slot:
        return None
    #: RV-23 (v23-k). The worker before any agent it started: `pgrep` lists claude first, and a codex worker's `claude
    #: agents --json` child sits in the same slot. `scripts/fleet-finished-pids.sh` keys auto-resume exclusion on this pid.
    for session in sorted(live_sessions or (), key=lambda s: bool(getattr(s, "nested", False))):
        try:
            if _slot_holding(pool, session.cwd) == rec.slot:
                return session.pid
        except Exception:
            continue
    return None


def _state_of(rec, folder_state, live, phase, parked, pane, sessions, instant, idle_after_s,
              slot_holder=None, capture_failed=False):
    """The single state decision. Every branch is reachable from one join of all five fact sources.

    Returns `(state, note, on_pane)`. `on_pane` (`B24`) is True only when the state is a BLOCKED read off
    what the PANE shows — the thing a human attached to it would be looking at — and it is decided here, at
    the branch that produced the state, rather than re-derived by a caller in a second copy of this order.
    """
    if folder_state in TERMINAL_FOLDER_STATES:
        # The worker's own rename is the completion signal, and it outranks the recorded path — that is
        # what "a renamed instant is followed" means. `abort` is terminal too: W2-21's fix reached
        # inflight and complete and never abort, and abort is legal.
        return COMPLETE, f"the instant folder is `-{folder_state}-`; the work is over", False
    observed = sessions.observe(rec.tmux).state if (live and rec.runtime == 'codex') else None
    if observed in ('unknown', 'dialog'):
        #: `RV-25`. Only a dialog fleet SAW is on the pane for an attached human to answer. `unknown` is
        #: also what a FAILED capture observes as (`SessionLayer.observe`), and an unrecognised frame is
        #: not known to be in front of anyone — excusing either would be `FI-7`'s permissive default.
        return BLOCKED, 'Codex input is modal or unrecognized; inspect before acting', observed == 'dialog'

    if not live:
        if slot_holder is not None:
            # Alive by the probe that does not need tmux. Say what is missing rather than inventing a
            # death: the remedy is a server, not a recovery.
            asked = getattr(sessions, "socket", "") or "the default server"
            return UNREACHABLE, (
                f"pid {slot_holder} is live and holds this record's slot, but no session answers for "
                f"{rec.tmux or 'it'} on tmux server {asked!r} — the process is running and its SESSION is "
                f"unreachable from there. "
                + (f"The record names {rec.tmux_socket!r}, which was asked and did not have it: the "
                   f"session may have been killed while the process lives on."
                   if rec.tmux_socket else
                   "This record predates the server field, so nothing says where to look: usually the "
                   "wrong tmux server, and `export FLEET_TMUX_SOCKET` to the one it was dispatched on.")), False
        #: FB-121. Harvest kills the session, stamps, then releases the lease, so a harvested record with no live slot
        #: holder is over wherever it was dispatched — including a server we are not talking to.
        if rec.harvested_at:
            return HARVESTED, f"record harvested at {rec.harvested_at}; the work is over", False
        #: `SI-59`. The record NAMES a server, and it is not the one we looked on. `SI-39` gave this
        #: situation its own state because DEAD is an ACTIONABLE claim — the response is `reap` — and a
        #: wrong DEAD invites a human to free a slot out from under running work. That state needed a live
        #: pid holding the slot to fire; this needs nothing but the record, because the record already
        #: says where to look. No probe is run here on purpose: `reconcile` visits every record, and one
        #: `has-session` per server per record would put dozens of subprocesses in front of a healthy
        #: board. The verbs that ACT do search, which is where the cost buys something.
        if rec.tmux_socket and rec.tmux_socket != getattr(sessions, "socket", ""):
            return UNREACHABLE, (
                f"no session answers for {rec.tmux or 'it'} HERE, and this record was dispatched on tmux "
                f"server {rec.tmux_socket!r} while this command is talking to "
                f"{getattr(sessions, 'socket', '') or 'the default server'!r}. Nothing has been observed "
                f"about whether the work is alive: export FLEET_TMUX_SOCKET={rec.tmux_socket} and ask "
                f"again."), False
        if rec.closed_at and instant is None:
            return CLOSED, f"record closed at {rec.closed_at}; the session was intentionally closed", False
        if rec.launched_at is None:
            # READ from an absent field, never stamped. Back-filling it here is exactly the defect that
            # made the predecessor's report a writer.
            return PENDING_LAUNCH, "dispatched, with no launch recorded and no live session", False
        #: Names the server, because that is what makes DEAD an honest claim rather than a local one. It
        #: is reached only after the record's OWN server was asked, when it names one.
        asked = getattr(sessions, "socket", "") or "the default server"
        return DEAD, (f"launched at {rec.launched_at} and no session is alive on tmux server {asked!r}: "
                      "the work stopped without renaming its folder"), False
    if instant is None and rec.child_instant:
        #: `B06`, re-measure `scenD` D3. The record names an instant and nothing on disk answers for it,
        #: while the session is live. Every verb this worker would run to report or finish (`brief`,
        #: `seed-check`, `propose`, `complete`) refuses with rc=2, so it cannot get out on its own. Before
        #: this branch it was RUNNING with an empty note forever, because `_idle_for(None)` is 0 and so it
        #: never even aged into IDLE. Gated on `child_instant`: a record that never named a folder has
        #: lost nothing.
        #:
        #: `RV-47`. Decided here, BEFORE `_live_state`, so it outranks `busy` — the opposite of the park's
        #: `OBS-3` rule one function down, and meant: a worker mid-turn whose folder is gone will be refused
        #: by every verb it runs at the end of that turn, and a folder does not come back on its own. Pinned
        #: by `test_a_missing_folder_outranks_a_busy_pane`.
        return BLOCKED, (f"the instant folder this record names, {rec.child_instant}, is not on disk "
                         f"(deleted, or moved outside {Path(rec.child_instant).parent}); the session is "
                         f"live, and every fleet verb it would run to report or finish refuses"), False
    return _live_state(phase, parked, pane, sessions, instant, idle_after_s,
                       capture_failed=capture_failed)


def _live_state(phase, parked, pane, sessions, instant, idle_after_s, capture_failed=False):
    waiting = sessions.unsubmitted(pane)
    busy = sessions.busy(pane)
    watcher_kind, watcher_text = (
        _watcher_of(pane, sessions, instant, capture_failed=capture_failed)
        if phase == PHASE_AWAITING_CI and sessions.runtime != 'codex' else (None, ""))
    unwatched = watcher_kind in WATCHER_UNBACKED
    on_pane = False
    if not busy and sessions.asking(pane):
        #: `B06`/`FI-55`. `pane-guard` has answered `15 awaiting-operator` for this frame since `I-16`, and
        #: this join still said RUNNING with an empty note: an `AskUserQuestion` selection carries no caret
        #: row, so `unsubmitted` is None, and nothing else here asked. It is the same predicate in the same
        #: order `cli._do_pane_guard` uses (busy, then asking, then unsubmitted), so the guard and the board
        #: cannot disagree about one frame. Waiting will not clear a dialog, and only an answer will.
        state, note = BLOCKED, ("the pane is showing an operator dialog (a selection question, a trust "
                                "screen or an approval prompt) and nothing moves until a human answers it")
        on_pane = True
    elif waiting and not busy:
        # A pane holding text nobody submitted needs a keystroke: a modal, or a swallowed submit. Text
        # queued while the agent is still working is not blocked — it is queued, and it will be sent.
        state, note = BLOCKED, f"the pane is waiting on a human: {waiting!r}"
        on_pane = True
    elif phase == PHASE_AWAITING_CI and sessions.runtime == 'codex':
        state, note = BLOCKED, 'Codex has no verified CI wake mechanism; this worker still consumes capacity'
    elif phase == PHASE_AWAITING_CI and not unwatched:
        state, note = AWAITING_CI, _awaiting_note(pane, sessions, instant,
                                                  capture_failed=capture_failed,
                                                  watcher=(watcher_kind, watcher_text))
    elif busy:
        state, note = RUNNING, ""
    elif _idle_for(instant) > idle_after_s:
        state, note = IDLE, (f"live, but nothing has changed in the instant for more than "
                             f"{idle_after_s}s and the pane is not working")
    else:
        state, note = RUNNING, ""

    if unwatched:
        #: `B06` (x2 `M-3`, the design `D-10` shipped on a branch that was never deployed). `awaiting-ci` is
        #: the one phase that outranks both `busy` and the idle threshold, and it takes the worker out of the
        #: WIP cap. With nothing observed on the pane and nothing recorded at the claim, that exemption is
        #: backed by nothing. The note already said so and the state kept the exemption. So the claim is
        #: DISREGARDED here and the ordinary detector decides, exactly as for an undeclared worker: it counts
        #: against the cap, and it ages into IDLE once nothing has moved. Disregarded rather than cleaned
        #: up, because this module never writes (property 2), and a stale claim stops lying without a sweep.
        #: The phase stays visible in `evidence.declared_phase`.
        #: `RV-43`. States what IS, and predicts nothing. The first wording promised the worker "ages into
        #: IDLE like any other" — false whenever the chosen state is RUNNING on a busy pane (`elif busy`
        #: precedes the idle check) or BLOCKED on a dialog. A note that says something its own state does
        #: not is exactly the defect family this bucket closes.
        #: `B07`/`FB-58`: a claim whose watcher is GONE is disregarded for the same reason, and the note
        #: names what was there and why it no longer counts rather than saying nothing was recorded.
        why = (f"NO WATCHER OBSERVABLE: {watcher_text}" if watcher_kind == WATCHER_GONE else
               "NO WATCHER OBSERVABLE on the pane and none recorded at the claim")
        disregarded = (f"declared {PHASE_AWAITING_CI}; {why}, so the declaration is disregarded and the "
                       f"ordinary detector decides this row — which means the worker counts against the WIP "
                       f"cap again")
        note = f"{note}; {disregarded}" if note else disregarded

    if parked:
        if state in ACTIONABLE_STATES:
            # An actionable state is never masked by a standing note; the park is APPENDED.
            note = f"{note}; parked decision stands: {parked}"
        elif busy:
            state, note = PARKED, f"parked decision stands while work progresses: {parked}"
        else:
            state, note = PARKED, f"parked decision: {parked}"
    #: `and state == BLOCKED` is belt-and-braces, not load-bearing today: `on_pane` is only set beside a
    #: BLOCKED, and the park rewrite above leaves an actionable state alone. It keeps `on_pane` meaning "a
    #: BLOCKED read off the pane" if a later branch ever rewrites the state after it is set (`RV-34`).
    return state, note, on_pane and state == BLOCKED


def _declared_age_s(instant, now):
    """Seconds since the phase was declared, or None when the declaration predates the `at` field or the
    stamp cannot be parsed — NOT MEASURED, so no staleness may be claimed from it."""
    stamp = Declarations(instant).declared_at() if instant is not None else None
    if not stamp:
        return None
    try:
        return now - calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return None


#: What stands behind an `awaiting-ci` claim, as `_watcher_of` classifies it. `UNREADABLE` is NOT MEASURED
#: and deliberately not `NONE`: the two are the same on screen and opposite in what they license. `GONE` is
#: `B07`/`FB-58`: something DID back the claim, and it is provably no longer there — an observed watcher no
#: longer on the pane, or an attested pid that has exited. It licenses what `NONE` does, with a reason.
WATCHER_OBSERVED = "observed"
WATCHER_ATTESTED = "attested"
WATCHER_UNREADABLE = "unreadable"
WATCHER_GONE = "gone"
WATCHER_NONE = "none"

#: The kinds that leave nothing backing the claim, so `_live_state` disregards it.
WATCHER_UNBACKED = (WATCHER_NONE, WATCHER_GONE)

#: Where a pid named by an attestation is looked up. A module constant so the hermetic suite can point it at
#: a private tree instead of starting and killing processes.
PROC_ROOT = Path("/proc")

#: What `/proc` says about an attested pid. Values distinct from the watcher kinds above: one marker, one name.
PID_RUNNING = "pid-running"
PID_GONE = "pid-gone"
PID_UNREADABLE = "pid-unreadable"


def pid_start(pid) -> tuple:
    """`(status, start)` for a pid, read from `/proc/<pid>/stat`: status is `PID_RUNNING`, `PID_GONE` or
    `PID_UNREADABLE`, and `start` is field 22 (`starttime`) when running.

    `FB-58`. A zombie (`Z`) or a dead task (`X`) has exited and watches nothing, so it is GONE. Only a
    missing entry is GONE otherwise; any other failed read is UNREADABLE — NOT MEASURED (`FI-7`), because
    reading "I could not look" as "it is gone" would take a real waiter's exemption away on a hiccup.
    Read-only: `/proc`, never a signal (`pool._live_pid` records why not even signal 0)."""
    try:
        raw = (Path(PROC_ROOT) / str(int(pid)) / "stat").read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return PID_GONE, ""
    except (OSError, ValueError, TypeError):
        return PID_UNREADABLE, ""
    #: The command name is parenthesised and may itself contain spaces or `)`, so split after the LAST `)`.
    fields = raw.rpartition(")")[2].split()
    if len(fields) < 20:
        return PID_UNREADABLE, ""
    if fields[0] in ("Z", "X"):
        return PID_GONE, ""
    return PID_RUNNING, fields[19]


def attested_pid_status(handle) -> tuple:
    """`(status, sentence)` for an attestation's recorded pid handle (`Declarations.watcher_pid`), or
    `(None, "")` when it named none. A pid that is running but started at a different moment from the one
    recorded at the claim is a RECYCLED pid, and the watcher it named is GONE."""
    if not handle:
        return None, ""
    #: `RV-C5`. `declare.json` is a file anyone can edit; a handle of the wrong shape raised TypeError out of
    #: here and took `fleet board` down for every row. It cannot be read, so it is NOT MEASURED.
    if not isinstance(handle, dict) or not isinstance(handle.get("pid"), int) or isinstance(handle["pid"], bool):
        return PID_UNREADABLE, (f"its recorded pid handle {handle!r} is malformed and could not be read — NOT "
                                f"MEASURED, so the attestation stands")
    pid = handle["pid"]
    status, start = pid_start(pid)
    if status == PID_RUNNING and handle.get("start") and start != str(handle["start"]):
        return PID_GONE, (f"the attested watcher pid {pid} is GONE — that pid now belongs to a different "
                          f"process (started at tick {start}, not {handle['start']})")
    if status == PID_GONE:
        return PID_GONE, f"the attested watcher pid {pid} is GONE (it has exited since the claim)"
    if status == PID_UNREADABLE:
        return PID_UNREADABLE, (f"its pid {pid} could not be read — NOT MEASURED, so the attestation "
                                f"stands")
    return PID_RUNNING, f"its pid {pid} is running"


def _watcher_of(pane, sessions, instant, capture_failed=False) -> tuple:
    """`(kind, text)`: what backs an `awaiting-ci` claim right now. OBSERVED is on the pane's status line
    at this moment; ATTESTED is the claimant's word recorded in `declare.json`; GONE is a watcher that
    backed the claim and provably no longer does; NONE is nothing either way.

    ONE classification per row: `_live_state` decides the state on it and hands the same `(kind, text)` to
    `_awaiting_note` (`RV-C2`), so the two cannot disagree about one worker.

    `B07`. A watcher OBSERVED at the claim is stored bare and one ATTESTED is stored with
    `store.ATTESTED_PREFIX`; this used to test only whether SOMETHING was recorded, so an observed watcher
    that had since vanished classified ATTESTED — the trusted branch (re-measure scenC C5). An observation
    is re-checkable, and re-checking it is the point: not on the pane now means GONE. Only a genuine
    attestation — a watcher this tool cannot see — keeps the claimant's word as its backing, and when that
    word carries a pid (`FB-58`) the pid is checked too.
    """
    observed = sessions.watchers(pane)
    if observed:
        return WATCHER_OBSERVED, observed
    declarations = Declarations(instant) if instant is not None else None
    recorded = declarations.watchers() if declarations is not None else None
    if recorded and declarations.watcher_attested():
        said = recorded[len(ATTESTED_PREFIX):]
        status, sentence = attested_pid_status(declarations.watcher_pid())
        if status == PID_GONE:
            return WATCHER_GONE, f"{sentence}; it was attested as: {said}"
        if status is None:
            return WATCHER_ATTESTED, (f"{said} (no pid handle was recorded at the claim, so nothing re-checks it: the claimant "
                                      f"must re-declare when it ends)")
        return WATCHER_ATTESTED, f"{said} ({sentence})"
    #: `RV-42`/`FI-7`. The capture FAILED, so the pane was never read and nothing was observed about a
    #: watcher either way. A failed observation is not a negative observation: reported as NOT MEASURED,
    #: which leaves the declaration standing, because withdrawing a cap exemption on a tmux hiccup is a
    #: guard whose failure mode is to punish the innocent. Before the bare-record branch below, for the
    #: same reason: a watcher observed at the claim cannot be called gone from a pane nobody read.
    if capture_failed:
        return WATCHER_UNREADABLE, ""
    if recorded:
        return WATCHER_GONE, (f"the watcher OBSERVED on the pane at the claim ({recorded}) is no longer "
                              f"on it")
    return WATCHER_NONE, ""


def _awaiting_note(pane, sessions, instant, stale_after_s=STALE_WAIT_S, now=None,
                   capture_failed=False, watcher=None) -> str:
    """What the board says about a worker that claims to be waiting on CI.

    The declaration is a claim made at ONE moment; nothing re-reads it. A Monitor that emitted zero
    events for 7.7 h and a self-matching wait shell that outlived its job both rendered here as a
    healthy wait, and the cost was three operator `status?` pings in one session. This re-observes the
    pane's own status line (`sessions.watchers`) rather than trusting the declaration alone, and — when a
    live observation is not possible — falls back to what was ATTESTED at claim time, distinguishably
    from what is actually OBSERVED now.
    """
    #: `RV-C2`. `_live_state` passes the classification it decided the STATE on. Classifying again here reads
    #: the pane and `/proc` a second time, and a pid exiting between the two reads gave an AWAITING-CI row
    #: whose note said the watcher was GONE.
    kind, watcher = watcher if watcher is not None else _watcher_of(pane, sessions, instant,
                                                                     capture_failed=capture_failed)
    if kind == WATCHER_OBSERVED:
        note = f"declared awaiting-ci; watcher observed ({watcher})"
    elif kind == WATCHER_ATTESTED:
        note = f"declared awaiting-ci; watcher ATTESTED, not observable: {watcher}"
    elif kind == WATCHER_UNREADABLE:
        note = ("declared awaiting-ci; the pane CAPTURE FAILED, so nothing was observed about a watcher "
                "either way — NOT MEASURED, and the declaration stands until a pane can be read")
    elif kind == WATCHER_GONE:
        note = f"declared awaiting-ci; NO WATCHER OBSERVABLE: {watcher}"
    else:
        note = "declared awaiting-ci; NO WATCHER OBSERVABLE on the pane"
    age = _declared_age_s(instant, now if now is not None else time.time())
    if age is not None and age > stale_after_s:
        note += f"; STALE-WAIT (declared {int(age) // 3600}h{int(age) % 3600 // 60:02d}m ago)"
    return note


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


def _unknown_subject(sess, slot: str, live_sessions=(), server=""):
    """A live session no record claims. Reported, never acted on.

    `OBS-48` found one idle 8d20h, invisible to every records-first sweep. It carries no authorisation
    to end it, deliberately: *"a tool that can kill a session it does not understand is a tool nobody
    will leave armed, and some of those sessions are people's"* (D-6).
    """
    label = sess.name or f"pid{sess.pid}"
    unreadable = getattr(sess, "unreadable", False)
    evidence = {
        "pid": str(sess.pid),
        "cwd": str(sess.cwd),
        "runtime": sess.runtime,
        "session": sess.name or "",
        "tmux_socket": server,
        "nested": ("true" if getattr(sess, "nested", False) else
                   ",".join(str(item.pid) for item in live_sessions
                            if item.name == sess.name and getattr(item, "nested", False))),
        "record": "none",
        "slot": slot or "",
        "process": "unreadable" if unreadable else "",
    }
    note = ("no dispatch record claims this session; it is reported so a human can decide, and this "
            "tool does nothing to it")
    if unreadable:
        #: FB-54. Say WHY it cannot be placed further, so "no record claims it" is not read as "nothing is there".
        where = (f"placed by the tmux pane of session {sess.name}" if sess.name
                 else "no tmux pane on this server owns it or any ancestor, so it cannot be placed")
        note = (f"its process {sess.pid} could not be read (a /proc read of it failed) and is {where}; " + note)
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


def _slot_leased_to_pane(pool, sess, elsewhere=frozenset()) -> str:
    """FB-54. The slot whose lease names this session's tmux pane — for an UNREADABLE row only, "" otherwise.

    An unreadable process carries no cwd (`/proc/<pid>` stands in for the one the kernel refused), so the cwd
    join above cannot place it; the pane walk still named its session through `stat`. A readable row is never
    placed this way: its cwd is the stronger fact, and a process that left its slot has left it. A lease names a
    session but not a server, so a lease held by a record on another server (`elsewhere`, todo ids) is never
    matched: a same-named pane here is somebody else's (RV-29)."""
    if not getattr(sess, "unreadable", False) or not sess.name:
        return ""
    for slot in pool.slots():
        lease = pool.lease(slot)
        if lease is not None and lease.tmux == sess.name and lease.todo_id not in elsewhere:
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
