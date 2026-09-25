"""Attribution of slot holders to the instant being torn down — `V23-H` (v2-16).

A completed worker's harness watchers (`zsh -c '… tail -n0 -F $INSTANT/… | ugrep …'`) run in their OWN session with no
tty, so `tmux kill-session` never reaches them; `close` orphaned them to init and `harvest` then refused, listing their
pids, with nothing able to end them. Measured: `investigations/RCA-v23h.md` in the v23-h instant.

This module decides, from facts about each holder, which are the torn-down instant's own. It is pure: facts arrive as
a callable, signals as a callable, time as a callable. `pool` knows WHICH pids hold the slot; this module knows WHOSE.

**The unit is the in-slot tree** (D-1). A pipeline is three processes and only one of them names the path — the
wrapper's argv carries `$INSTANT` unexpanded and the grep stage names nothing — so a holder is judged together with
the holders it descends from, up to the topmost one (the ROOT).

**A unit is a CLOSED, DETACHED session** (D-8). Members are grouped only with an in-slot parent in the same Linux
session, and a unit is reapable only when no member has a live child outside it, so ending it ends nothing else. The
first version grouped by parentage alone, and its reviewer showed the hole: a tmux server started from inside the slot
(ppid 1) with one pane running `less <instant>/…` would have been reaped whole — every session on that server with it.
The harness's watcher is exactly the shape this admits: `setsid`, no controlling tty, a closed pipeline (measured,
`evidence/01-repro/harness-shape.txt` in the v23-h instant).

**A unit is REAPED** when it is closed and either its root is a process the recorded session owned before this call
killed it (same pid, same start time), or its root is ORPHANED (ppid 1), leads its own session with no controlling
tty, STARTED AFTER the worker was launched, and some member's argv names the instant (D-2, D-9). The start bound is
what keeps a childless tmux or screen server out: fleet's own servers carry the first dispatch's command line — which
names that instant — and have ppid 1, their own session and no tty, but every one of them started before the
`launched_at` of any session on it, because `launched_at` is stamped only after the session started and its seed was
seen delivered. And the root must carry the worker's PROVENANCE (D-10): `FLEET_INSTANT` in its environment names this
instant — the launcher exports it (`runtime_launch.prepare`) and every process the worker's harness starts inherits
it, while an operator's or coordinator's server started from the slot carries another instant or none. The start
bound alone left exactly that server reapable when it started after the launch (Task-3 review). **NAMED** — a kill
command printed, nothing signalled — when a member names the instant but the root has a live parent: an operator's
shell running `tail -F <instant>/…` from inside the slot is exactly that. **REFUSED** otherwise, and always for an
unreadable holder, a holder whose facts cannot be read, and any unit containing the caller or one of its ancestors.
A false positive signals somebody else's process; a false negative only leaves today's refusal standing.
"""
import signal as _signal
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from fleet.identity import STATES, InstantName

INIT_PID = 1
REAP, NAME, REFUSE = "reap", "name", "refuse"
#: How long TERM gets before KILL. Watchers exit on TERM at once; the bound is for one that ignores it.
REAP_TERM_WAIT_S = 3.0
#: Terminal multiplexers: a server of one is a detached, tty-less orphan whose sessions are other processes' — never
#: ended by name (RV-32). Read from argv[0] only, so `tmux: server (…)` counts and a watcher that merely mentions tmux
#: in its arguments does not.
_MULTIPLEXERS = frozenset({"tmux", "screen", "dtach", "abduco", "zellij"})
#: What may sit either side of a path for the text to be that path and not a longer one (`…-orphanw2`, `/x…`).
_PATH_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~-")


@dataclass(frozen=True)
class Proc:
    """What `/proc/<pid>/{stat,cmdline,task/*/children}` says about one live process. `start` is stat field 22: pid +
    start names one process, so a recycled pid is never read as the one attributed. `sid` and `tty` are stat fields 6
    and 7; `children` every live child pid. `None` for any of them is NOT OBSERVED, and fails closed."""
    pid: int
    ppid: int
    start: str
    argv: tuple
    sid: Optional[int] = None
    tty: int = 0
    children: Optional[tuple] = None
    #: Epoch seconds the process started (boot time + stat field 22 / CLK_TCK), None when unread.
    started_at: Optional[float] = None
    #: `FLEET_INSTANT` from `/proc/<pid>/environ`: the instant whose launch this process descends from. None when it
    #: is absent or the environment cannot be read (another uid, a non-dumpable process).
    fleet_instant: Optional[str] = None


@dataclass(frozen=True)
class Unit:
    root: int
    members: tuple
    verdict: str
    why: str

    def kill_command(self) -> str:
        return f"kill -TERM {' '.join(str(p) for p in self.members)}  # {self.why}"


@dataclass
class Attribution:
    units: list
    procs: dict

    def of(self, verdict: str) -> list:
        return [unit for unit in self.units if unit.verdict == verdict]

    def pids(self, verdict: str) -> list:
        return sorted(pid for unit in self.of(verdict) for pid in unit.members)


def instant_spellings(*paths) -> tuple:
    """Every absolute spelling of the instant's folder in every state (`complete` renames it, and a watcher armed
    before the rename names the `-inflight-` path), as given and resolved."""
    out = set()
    for raw in paths:
        if not raw:
            continue
        for path in {Path(str(raw)), Path(str(raw)).resolve()}:
            if str(path) in ("", "/"):
                continue
            out.add(str(path))
            try:
                name = InstantName.parse(path.name)
            except Exception:                        # not an instant name: the literal path is the only spelling
                continue
            for state in STATES:
                out.add(str(path.parent / name.with_state(state).format()))
    return tuple(sorted(out))


def names_instant(argv, spellings) -> Optional[str]:
    """The spelling some argv element names at a path boundary, or None."""
    for arg in argv:
        for spelled in spellings:
            start = arg.find(spelled)
            while start >= 0:
                end = start + len(spelled)
                before = arg[start - 1] if start else ""
                after = arg[end] if end < len(arg) else ""
                if (not before or (before not in _PATH_CHARS and before != "/")) and \
                        (not after or after not in _PATH_CHARS):
                    return spelled
                start = arg.find(spelled, start + 1)
    return None


def _readable(holders, facts):
    from fleet.pool import UnreadableHolder
    procs, blind = {}, []
    for pid in holders:
        fact = None if isinstance(pid, UnreadableHolder) else facts(int(pid))
        if fact is None:
            blind.append(int(pid))
        else:
            procs[int(pid)] = fact
    return procs, blind


def attribute(holders, facts: Callable, spellings, *, session_own=None, exclude=(), not_before=None) -> Attribution:
    """`not_before` is the epoch second a by-name root must have started at or after (the caller passes the record's
    `launched_at` plus a margin); None — no launch recorded — means nothing is reaped by name."""
    procs, blind = _readable(holders, facts)
    units = [Unit(pid, (pid,), REFUSE, f"pid {pid}'s process facts could not be read, so nothing ties it to this "
                                       f"instant") for pid in blind]
    groups = {}
    for pid in procs:
        root, steps = pid, 0
        while steps < 256:
            parent = procs.get(procs[root].ppid)
            if parent is None or parent.pid == root or parent.sid is None or parent.sid != procs[root].sid:
                break
            root, steps = parent.pid, steps + 1
        groups.setdefault(root, []).append(pid)
    own = dict(session_own or {})
    lineage = set(exclude)
    for root, members in sorted(groups.items()):
        members = tuple(sorted(members))
        head = procs[root]
        named = next(((pid, spelled) for pid in members
                      if (spelled := names_instant(procs[pid].argv, spellings))), None)
        outside = _outside_children(members, procs)
        detached = head.ppid == INIT_PID and head.sid == root and head.tty == 0
        owned = own.get(root) is not None and own.get(root) == head.start
        late = not_before is not None and head.started_at is not None and head.started_at >= not_before
        ours = head.fleet_instant is not None and head.fleet_instant in set(spellings)
        if lineage & set(members):
            units.append(Unit(root, members, REFUSE, "the unit contains the process running this command or one of "
                                                     "its ancestors"))
        elif outside is None and (named or owned):
            units.append(Unit(root, members, NAME, f"its children could not be read, so ending it might end processes "
                                                   f"nothing attributed; not ended automatically"))
        elif outside and (named or owned):
            units.append(Unit(root, members, NAME, f"it has live children outside the unit ({_pids(outside)}), which "
                                                   f"ending it would take down too; not ended automatically"))
        elif owned:
            units.append(Unit(root, members, REAP, f"pid {root} was the recorded session's own process before the "
                                                   f"kill and survived it"))
        elif named and detached and not late:
            units.append(Unit(root, members, NAME, f"pid {named[0]}'s argv names {named[1]}, but pid {root} did not "
                                                   f"start after this worker was launched (a server or daemon that "
                                                   f"predates it looks exactly like this), so it is not ended "
                                                   f"automatically"))
        elif named and detached and _multiplexer(head.argv):
            units.append(Unit(root, members, NAME, f"pid {root} is a terminal multiplexer ({head.argv[0][:40]!r}); "
                                                   f"ending it would end every session on it, so it is not ended "
                                                   f"automatically"))
        elif named and detached and not ours:
            units.append(Unit(root, members, NAME, f"pid {named[0]}'s argv names {named[1]}, but pid {root}'s "
                                                   f"environment does not say it was started by this worker "
                                                   f"(FLEET_INSTANT is {head.fleet_instant or 'absent or unreadable'}), "
                                                   f"so it is not ended automatically"))
        elif named and detached:
            units.append(Unit(root, members, REAP, f"orphaned (pid {root}'s parent is init, it leads its own session "
                                                   f"with no terminal) and pid {named[0]}'s argv names {named[1]}"))
        elif named:
            units.append(Unit(root, members, NAME, f"pid {named[0]}'s argv names {named[1]}, but pid {root} is not a "
                                                   f"detached orphan (parent {head.ppid}, session {head.sid}, tty "
                                                   f"{head.tty}), so it is not ended automatically"))
        else:
            units.append(Unit(root, members, REFUSE, "nothing ties it to this instant"))
    return Attribution(units=units, procs=procs)


def _multiplexer(argv) -> bool:
    """Whether argv[0] is a terminal multiplexer (`tmux`, `/usr/bin/screen`, `SCREEN`, `tmux: server (…)`)."""
    if not argv or not argv[0].split():
        return False
    return Path(argv[0].split()[0]).name.rstrip(":").lower() in _MULTIPLEXERS


def _pids(pids) -> str:
    return ", ".join(str(pid) for pid in sorted(pids))


def _outside_children(members, procs) -> Optional[set]:
    """Live children of any member that are not members; None when any member's children were not observed."""
    inside, outside = set(members), set()
    for pid in members:
        children = procs[pid].children
        if children is None:
            return None
        outside |= set(children) - inside
    return outside


def naming_holders(holders, facts: Callable, spellings, *, exclude=()) -> list:
    """The readable holders whose own argv names the instant, outside the caller's lineage — `complete`'s warning."""
    procs, _ = _readable(holders, facts)
    return [procs[pid] for pid in sorted(procs)
            if pid not in set(exclude) and names_instant(procs[pid].argv, spellings)]


def reap(units, procs: dict, facts: Callable, signal_pid: Callable, sleep: Callable, *,
         wait_s: float = REAP_TERM_WAIT_S, step_s: float = 0.1) -> list:
    """End every member of `units`: TERM, wait up to `wait_s`, KILL what is left. Each signal first re-reads the pid
    and skips it unless it is still the same process (pid + start). Returns `(pid, outcome, unit)` per member:
    TERM, KILL, gone (exited or recycled before the signal), unsignalled (delivery failed) or survived."""
    def same(pid):
        now = facts(pid)
        return now is not None and now.start == procs[pid].start

    outcome, unit_of = {}, {}
    for unit in units:
        for pid in unit.members:
            unit_of[pid] = unit
            if not same(pid):
                outcome[pid] = "gone"
            elif signal_pid(pid, _signal.SIGTERM):
                outcome[pid] = "TERM"
            else:
                outcome[pid] = "unsignalled"            # the process is there, the signal was not delivered
    waited = 0.0
    while waited < wait_s - 1e-9 and any(how == "TERM" and same(pid) for pid, how in outcome.items()):
        sleep(step_s)
        waited += step_s
    for pid, how in list(outcome.items()):
        if how == "TERM" and same(pid):
            outcome[pid] = "KILL" if signal_pid(pid, _signal.SIGKILL) else "survived"
    waited = 0.0
    while waited < 1.0 - 1e-9 and any(how == "KILL" and same(pid) for pid, how in outcome.items()):
        sleep(step_s)
        waited += step_s
    for pid, how in list(outcome.items()):
        if how == "KILL" and same(pid):
            outcome[pid] = "survived"
    return [(pid, outcome[pid], unit_of[pid]) for pid in sorted(outcome)]
