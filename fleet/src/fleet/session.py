"""Sessions — process-first enumeration and pane predicates behind injectable probes.

Three rules this module exists to enforce, each of them a defect the predecessor shipped twice:

1. **One `alive()`.** The predecessor carried two near-identical liveness checks with slightly
   different semantics, which is how `OI-16` became two defects instead of one. There is exactly one
   implementation here, and `tests/test_structure.py` asserts the package defines liveness at most
   once. (That assertion counts occurrences of the definition line as TEXT, so this docstring
   deliberately does not spell the phrase out — the same class as FI-1, where a checker's own words
   tripped the checker.)
2. **Enumeration starts at the PROCESS.** `OBS-48` found a `SCREEN` session with no dispatch record
   idle for 8d20h — invisible to every records-first sweep, because a sweep that iterates records
   cannot see a session nobody wrote down. `live()` therefore reports what the process probe reports,
   record or no record.
3. **Pane predicates are anchored to the TAIL of what the pane is SHOWING.** A prompt earlier in the
   buffer is scrollback. Treating history as current state is how a watcher re-alarms its whole past
   on every restart, and it is why the window here is a constant of the predicate rather than a
   caller's choice. "Tail" means *tail of the rendered rows* — see `_rendered`: `capture-pane` pads
   its output to the pane height, so a raw line index is a position in the terminal and not a
   position in the content (`FI-24`).
4. **Every tmux target is EXACT.** tmux resolves a bare `-t name` by PREFIX, so one shared character
   was enough for liveness, capture and **kill** to land on a different worker's session
   (`FI-23`). Targets are built by `exact_session_target` / `exact_pane_target` and nowhere else.
5. **Which tmux SERVER is a parameter, and it is one place.** Every tmux argv is built from a single
   prefix list (`TMUX_SOCKET_ENV`, `SD-1`) so no site can be added that skips it. An exact target stops
   a command resolving to the wrong session **on a server**; a private server stops the wrong session
   being reachable **at all**. These are different guarantees and the module wants both — the default
   socket is a shared namespace where an IT group, the suite and a live coordinator all met.

Everything that touches the outside world goes through `Probes`, so the suite can describe a fleet
without owning one (FD-6, `NFR2-1`). `default_probes()` builds the real ones and is **one of the
three** places in the package that spawns a subprocess — the others being `cli._default_runner`
(the command runner every handler is handed) and `workspace.default_git`. The claim here used to read
"the only place", which was false on the day it was written: three seams existed, and a false
isolation claim in the module whose job IS isolating the environment is worse than no claim
(`FI-27a`). The seams are enumerable on purpose — that is what makes "injected everywhere else" a
fact a reader can check rather than a promise.
"""
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from fleet.errors import BadInput, FleetError

from fleet.runtime import (
    PROMPT_TAIL_LINES, BUSY_TAIL_LINES, plain, _cells, _undim, _caret_content,
    _rendered, _tail, _trim, _is_placeholder, claude_unsubmitted, claude_busy,
    claude_watchers, observe, validate_runtime, PaneObservation, recognizes_process,
)



@dataclass
class LiveSession:
    """A process that is actually running, whether or not anything recorded it."""

    pid: int
    cwd: Path
    name: Optional[str]
    runtime: str = "claude"
    #: `/proc/<pid>/exe` or `cwd` refused the read (another user's process, a non-dumpable one, or any other
    #: per-pid failure — FB-53). The row is kept, with `cwd` left at `/proc/<pid>` because the real one was never
    #: read. `name` is still attributed (FB-54): `stat` is world-readable, so the parent walk a readable row uses
    #: can name the tmux session whose pane owns it, and then `reconcile` reads it as THAT session — this
    #: record's session, unreadable — rather than as an unmanaged one. With no owning pane it stays `None`.
    #: `runtime --set` treats it as a blocker either way — naming its pane does not make its binary or cwd
    #: known, and an agent that cannot be read is not proof of emptiness. Raising instead blinded every read
    #: verb for as long as that process lived.
    unreadable: bool = False
    #: v23-k (FB-113). Another inventoried agent sits between this process and its pane root: it is that agent's CHILD,
    #: not the pane's agent. The hermetic suite and `fleet peers` run the real `claude agents --json`, so a codex
    #: worker's pane briefly holds a genuine claude, and `board` read it as "live runtime claude differs from record
    #: runtime codex". The row is kept — it is a real process holding a real cwd — and only the readers that ask WHICH
    #: RUNTIME OWNS THE PANE skip it (`outer`). Default False: a hand-built row is the pane's own agent, as before.
    nested: bool = False


def outer(sessions, name: str) -> list:
    """The inventory rows that are `name`'s own agent — attributed to it and not nested under another agent.

    Every "is this pane the runtime its record says" question reads these and nothing else (v23-k): a claude that a
    codex worker started is not a claude pane."""
    return [item for item in sessions if item.name == name and not getattr(item, "nested", False)]


@dataclass
class Probes:
    """The seam between this module and the machine. Injected, so a test never needs a real tmux."""

    list_processes: Callable[[], list]
    #: `FI-7`: returns None when the capture FAILED, `''` for a genuinely empty pane.
    capture_pane: Callable[[str], Optional[str]]
    has_session: Callable[[str], bool]
    start_session: Callable[[str, Path, str], None]
    kill_session: Callable[[str], None]
    #: The pid tmux itself started in this session's pane, or None.
    #:
    #: Deliberately NOT derived from `list_processes`, which is `pgrep -x claude` joined to pane ownership
    #: and therefore answers only for processes NAMED claude. Seed-delivery integrity (`seedcheck`) must
    #: read the argv of whatever was ACTUALLY started — a launcher, a wrapper, a stub under test — and a
    #: probe that first requires the process to be the thing we are trying to confirm cannot do that. tmux
    #: knows the pane pid for certain and does not care what it is called.
    #:
    #: Defaulted so every existing construction of `Probes` — the suite builds several by hand — keeps
    #: working. A caller that does not supply it gets None, which `SessionLayer.pane_pid` reports as "not
    #: observable" rather than as "no process", because those are different facts.
    pane_pid: Optional[Callable[[str], Optional[int]]] = None
    #: `SI-59`. The socket these probes talk to, or `""` for the default server. Carried as DATA because
    #: a reader has to be able to say which server it looked on: "no session is alive" and "no session is
    #: alive HERE" are different claims, and only the second one is true when the record names another.
    socket: str = ""
    #: `SI-59`. Every tmux server on this box that has a session by this name, or `None` when the caller
    #: supplied no probe. `None` is NOT the empty list, and the distinction is the whole point: a missing
    #: probe means UNOBSERVED, and reporting "found nowhere" for it would be `FI-417` — the same shape as
    #: the DEAD this field exists to stop being claimed.
    session_servers: Optional[Callable[[str], list]] = None
    send_literal: Optional[Callable[[str, str], None]] = None
    submit: Optional[Callable[[str], None]] = None
    #: `B24` (x2 `G-4`). `(interactive_clients, last_input_epoch)` for one session — from tmux's per-client
    #: `#{client_readonly}`, `#{client_control_mode}` and `#{client_activity}` — or `None` when it could not
    #: be observed. Defaulted like `pane_pid`, so every
    #: hand-built `Probes` keeps working and reads as NOT MEASURED rather than as "nobody attached".
    attachment: Optional[Callable[[str], Optional[tuple]]] = None
    #: `B10`. A pid's parent pid, `0` when it cannot be read. With `pane_pid` it answers "is this process
    #: one of this session's own" — what `abort` needs to know before a kill it cannot take back. Defaulted
    #: like `pane_pid`, and absence reads as NOT OBSERVABLE, never as "nobody's".
    parent_of: Optional[Callable[[int], int]] = None
    #: `RV-20`. Every pane pid of the session — every window, every pane — or None when unobservable.
    #: `kill-session` ends all of them, so each one roots the session's own process tree; `pane_pid` above
    #: answers for the first pane of the current window only. Defaulted like the fields above.
    pane_pids: Optional[Callable[[str], Optional[list]]] = None


@dataclass(frozen=True)
class Attachment:
    """`B24`. INTERACTIVE clients attached to a session and the epoch of the last input one of them gave it,
    plus `observers`: clients that are read-only or control-mode (`RV-36`) — attached, so somebody may be
    there, but showing no input fleet can see."""
    clients: int
    last_input: float
    observers: int = 0


#: tmux's exact-match marker. A BARE target is resolved by PREFIX: with only `itfleet-N-pre-ab` alive,
#: `has-session -t itfleet-N-pre-a` exits 0 and `kill-session -t itfleet-N-pre-a` DESTROYS it
#: (`evidence/04-integration/N/N7-tmux-target.txt`, `N7c-tmux-kill-prefix.txt`).
_EXACT = "="

#: Which tmux SERVER to talk to, named by socket. Unset or empty means the default server — the shipped
#: behaviour, because `pane-guard` and a real dispatch exist to see the operator's own sessions and a tool
#: hard-wired to a test server would be blind to them (`SD-1`).
#:
#: The default socket is a shared namespace, and everything that has ever landed on it landed on it
#: together: §M's `itfleet-M-worker`, the hermetic suite's `itfleet-selftest-*` and the live coordinator's
#: `dt-…`. §E's server-wide isolation assertion failed on exactly that and was right to. `-L` gives each
#: group a namespace of its own, which is the only form of tmux isolation that a prefix accident cannot
#: defeat — an EXACT target (`_EXACT`) prevents resolving to the wrong session on one server; a private
#: server prevents the wrong session from being reachable at all. Both, not either.
TMUX_SOCKET_ENV = "FLEET_TMUX_SOCKET"

#: Distinguishes "the caller did not say" from "the caller said: the default server". Without it an
#: explicit `tmux_socket=None` would be re-read from an inherited environment variable, silently
#: redirecting a caller that had asked for the live server.
_FROM_ENV = object()


def exact_session_target(name: str) -> str:
    """The `-t` argument for a command taking a target-SESSION (`has-session`, `kill-session`)."""
    return f"{_EXACT}{name}"


def exact_pane_target(name: str) -> str:
    """The `-t` argument for a command taking a target-PANE (`capture-pane`).

    The trailing colon is not decoration and it is not symmetry-for-its-own-sake. Measured on tmux 3.2a:
    `capture-pane -t =itfleet-N-pre-ab` fails with *can't find pane* even for a session that EXISTS,
    because a pane target is parsed as `session:window.pane` and `=name` alone is not a session part.
    `=name:` resolves exactly, and `=prefix:` does not resolve at all
    (`evidence/04-integration/N/N7b-tmux-target-forms.txt`).

    Getting this wrong is the failure mode that would have passed the prefix test *vacuously*: with
    `=name` (no colon) both `pane(long)` and `pane(prefix)` return "", so "the prefix did not return the
    longer session's screen" would hold because NOTHING returned a screen.
    """
    return f"{_EXACT}{name}:"


class SessionLayer:
    """Liveness, pane state and session control — the whole outside world in one object."""

    def __init__(self, probes: Probes, runtime="claude"):
        self.probes = probes
        self.runtime = validate_runtime(runtime)

    @property
    def socket(self) -> str:
        """Which tmux SERVER this layer talks to; `""` is the default server."""
        return getattr(self.probes, "socket", "") or ""

    def servers_with(self, name: str):
        """Every server on this box holding a session called `name`, or `None` when unobservable.

        `SI-59`. Called only when a session did NOT answer on this server, which is the only time the
        answer changes anything and keeps the cost — one `has-session` per server — off the healthy path.

        The `None` return is load-bearing. A caller that cannot distinguish "looked everywhere and found
        nothing" from "could not look" will state the first while meaning the second, which is the exact
        false claim this whole field exists to remove.
        """
        if self.probes.session_servers is None or not name:
            return None
        return list(self.probes.session_servers(name))

    # --- enumeration -------------------------------------------------------------------------

    def live(self) -> list:
        """Every live session the PROCESS probe can see.

        Process-first is a requirement, not an implementation detail: a session with no dispatch
        record is exactly the case a records-first sweep is structurally unable to report (OBS-48),
        and it is the case that costs the most when missed.
        """
        return list(self.probes.list_processes())

    def alive(self, name: str) -> bool:
        """THE one liveness implementation.

        Prefers the live process — a real process holding a real cwd is the strongest evidence — and
        falls back to the session probe, which still answers for a session whose process the probe
        cannot attribute.
        """
        if not name:
            return False
        for session in self.live():
            if session.name == name:
                return True
        return bool(self.probes.has_session(name))

    def attachment(self, name: str) -> Optional[Attachment]:
        """Whether a HUMAN is at this session: its attached-client count and when a client last gave it
        input — or `None` when that could not be observed (no probe, no name, tmux did not answer).

        `B24` (x2 `G-4`). `BLOCKED` could not tell a worker stuck at a modal from a human attached and
        mid-sentence, because this fact was never collected. "Clients" means INTERACTIVE clients (`RV-28`); a
        read-only or control-mode client is an OBSERVER (`RV-36`): somebody may be there — a control-mode client
        can `send-keys`, which is how iTerm2 `-CC` types — but its `#{client_activity}` does not move when it
        does, so it can never show that a human was at the pane recently. An actuator must treat observers as
        occupied too. It is deliberately returned RAW and tri-state, because its two consumers fail safe in
        OPPOSITE directions:

        - the attention count (`reconcile`) treats `None` as "not a human" — it keeps counting, which is
          what it did before this fact existed, so a tmux hiccup cannot hide a stuck worker;
        - anything that TYPES into a pane (a nudge, `B12`) must treat `None` as "occupied": "I could not
          tell whether somebody is sitting there" has to mean leave it alone.

        `last_input` moves on an interactive client's attach and keystroke, and NOT on `send-keys`,
        `paste-buffer`, pane output, resize or SIGWINCH (B24 instant, `evidence/20-red/`), so neither fleet's
        own delivery nor a busy pane can make a session look attended.
        """
        if not name or self.probes.attachment is None:
            return None
        answer = self.probes.attachment(name)
        if answer is None:
            return None
        #: `RV-29`. The probe is an injectable field and this runs inside `reconcile`, so an answer of the
        #: wrong shape is NOT MEASURED rather than an exception that takes the whole board down with it.
        #: `RV-35`: and a non-finite number is not a measurement either — `inf`/`nan` pass `float()` (or
        #: overflow `int()`) here and would crash the age arithmetic in `reconcile` instead.
        #: The two-count form `(clients, last_input)` predates `observers` (`RV-36`) and reads as none.
        try:
            clients, last_input, *rest = answer
            if len(rest) > 1:
                return None
            observers = int(rest[0]) if rest else 0
            clients, last_input = int(clients), float(last_input)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(last_input):
            return None
        return Attachment(clients=clients, last_input=last_input, observers=observers)

    # --- pane --------------------------------------------------------------------------------

    def capture(self, name: str):
        """The pane's text, or None if the capture failed. `FI-7`.

        The ONLY way to distinguish "tmux could not answer" from "the pane is empty". Everything that
        merely wants text should use `pane()`; anything DECIDING on absence must use this, because on
        this distinction rests whether a live pane may be destroyed.
        """
        if not name:
            raise BadInput("a pane capture needs a session name")
        return self.probes.capture_pane(name)

    def pane(self, name: str) -> str:
        """The pane's text, with a failed capture flattened to `""`.

        Kept for every reader that just wants something to scan. A caller that BRANCHES on emptiness
        must use `capture()` instead — see `FI-7`.
        """
        return self.capture(name) or ""

    def observe(self, name: str) -> PaneObservation:
        frame = self.capture(name)
        return PaneObservation("unknown") if frame is None else observe(self.runtime, frame)

    def is_agent_process(self, name: str, live: Optional[list] = None) -> bool:
        """Whether a live process of THIS layer's runtime is attributed to `name`.

        For an `unreadable` row the runtime is `comm` alone (RV-28; see `is_claude_process`).

        `live` is an optional census snapshot: a guard decision that asks three questions of one pane
        must ask them of ONE inventory, not three taken at different instants (and not pay three
        `pgrep` + `/proc` walks for one answer).
        """
        items = self.live() if live is None else live
        return bool(name) and any(item.name == name and item.runtime == self.runtime for item in items)

    def send_literal(self, name: str, text: str):
        if self.probes.send_literal is None:
            raise BadInput('Literal delivery probe is unavailable')
        self.probes.send_literal(name, text)

    def submit(self, name: str):
        if self.probes.submit is None:
            raise BadInput('Submission probe is unavailable')
        self.probes.submit(name)

    def unsubmitted(self, pane_text: str):
        if self.runtime == "claude":
            return claude_unsubmitted(pane_text)
        return observe(self.runtime, pane_text).draft

    def is_claude_process(self, name: str, live: Optional[list] = None) -> bool:
        """Whether a live CLAUDE PROCESS is attributed to this session.

        `SI-38`. Process evidence, not screen scraping. `live()` comes from `pgrep -x claude` joined to
        tmux pane ownership, so a True here means a real claude is running in that session — a fact no
        amount of scrollback can change. One weaker case (RV-28): an `unreadable` row is attributed through
        `stat` alone, so for it the evidence is `comm` (what `pgrep -x` matched) and pane ownership — its
        binary was never read, and `recognizes_process` never judged it. Every caller reads True as "treat
        this pane as occupied by an agent", which is the conservative direction for that weaker evidence.

        This exists because the glyph test cannot answer it. A pane's markers ("esc to interrupt",
        "? for shortcuts", …) are UI chrome that scrolls away: a long answer followed by an idle prompt
        contains none of them, and a claude idle for twenty minutes was classified `12 not-claude` on a
        live coordinator whose pid was verified alive in the same breath. `12` is one of the codes the
        close-out contract treats as "the pane can go", and its own text says "a send here goes to
        somebody else's shell" — both false, in the dangerous direction.
        """
        if not name:
            return False
        items = self.live() if live is None else live
        return any(session.name == name and session.runtime == "claude" for session in items)

    def busy(self, pane_text: str):
        if self.runtime == "claude":
            return claude_busy(pane_text)
        return observe(self.runtime, pane_text).state == "busy"

    def asking(self, pane_text: str) -> bool:
        """Whether the pane is blocked at an operator dialog — `AskUserQuestion`, the folder-trust modal,
        Codex's approval prompt — waiting on a human's answer. `I-16`.

        `cli._do_pane_guard` checks this before busy and unsubmitted; `_pane_refusal` checks
        busy and asking separately, and refuses either. A dialog must never be typed into, and
        the trust modal's caret row is a dialog before it is
        anybody's typed text. ONE dialog
        predicate: this delegates to `runtime.observe`, whose per-runtime rows (`CLAUDE_DIALOG_ROWS`,
        `CODEX_DIALOG_ROWS`) are measured captures matched as several fragments on one row inside the
        input-box window — the `_WATCHER_MARKER` lesson, and the reason a single "esc to cancel" over a
        joined tail is not a dialog test (an agent's own prose quotes that hint constantly).
        """
        return observe(self.runtime, pane_text).state == "dialog"

    def watching(self, pane_text: str) -> bool:
        """Whether something is armed that will RE-INVOKE this session with no human in the loop.

        `FI-255`. `awaiting-ci` was taken to mean "somebody is watching" while establishing only "stop
        counting me against the cap". Two workers in the identical declared phase rendered byte-identically
        while one was self-waking and the other had been stopped for 1h28m with nothing that would ever
        restart it — so the phase string, the board row and the park field are ALL invariant across the
        event they are supposed to detect.

        Anchored to the STATUS LINE — one row — and not to `busy`'s 15-row window, because that window
        contains the agent's own output and an agent discussing monitors would otherwise report one. See
        `_WATCHER_MARKER`, where the measurement is recorded.

        Deliberately NOT keyed on `busy`: `declare` runs as a subprocess of the claiming agent's own turn,
        so `esc to interrupt` is present for EVERY claimant by construction. A guard keyed on it admits
        100% of claims — measured, both arms, on the pane that authored this change.

        This answers *"will this session wake up?"*, which is the property whose absence FI-255 measured. It
        does NOT answer *"is the watcher watching CI?"* — a background shell running a build satisfies the
        first and not the second, and that is not decidable from a pane. Callers must not overclaim it.
        """
        return bool(self.watchers(pane_text))

    def watchers(self, pane_text: str):
        if self.runtime == "claude":
            return claude_watchers(pane_text)
        return observe(self.runtime, pane_text).watcher

    def start(self, name: str, cwd: Path, command: str) -> None:
        if not name:
            raise BadInput("a session needs a name")
        self.probes.start_session(name, Path(cwd), command)

    def kill(self, name: str) -> None:
        if not name:
            raise BadInput("a session needs a name to be killed")
        self.probes.kill_session(name)

    def own_processes(self, name: str, pids) -> Optional[set]:
        """The subset of `pids` that belong to session `name` — one of its pane pids or a descendant of one
        — or None when that cannot be observed (no pane pids, or no parent walk). Every pane counts
        (`RV-20`): the kill ends every pane, not only the first.

        `B10`. These are the processes a kill of `name` ends, so they are NOT a reason to expect a slot
        to stay held after the kill. A process that left the tree (double-forked, reparented to init) is
        not counted: it survives the kill, which is exactly why it is not the session's to spare.
        """
        if self.probes.pane_pids is not None:
            listed = self.probes.pane_pids(name) if name else None
            roots = set(listed) if listed else None
        else:
            first = self.pane_pid(name)
            roots = None if first is None else {first}
        walk = self.probes.parent_of
        if roots is None or walk is None:
            return None
        own = set()
        for pid in pids:
            current, steps = pid, 0
            while current and current > 1 and steps < 256:     # bounded: a /proc race cannot loop us
                if current in roots:
                    own.add(pid)
                    break
                current, steps = walk(current), steps + 1
        return own

    def pane_pid(self, name: str) -> Optional[int]:
        """The pid tmux started in this session's pane, or None if it cannot be observed.

        None is "not observable", not "nothing is running" — the probe may be absent (an injected `Probes`
        that predates it) or tmux may not answer. Every caller here must treat it as the former, because
        the alternative reading turns an unreadable probe into a clean bill of health, which is the
        `FI-7` conflation one layer up.
        """
        if not name or self.probes.pane_pid is None:
            return None
        return self.probes.pane_pid(name)


def default_probes(process_name: str = "claude", tmux_socket=_FROM_ENV, *,
                   both_runtimes=False, proc_root=Path("/proc")) -> Probes:
    """The real probes: `pgrep -x <process_name>`, `/proc/<pid>/{cwd,cmdline}` and `tmux`.

    One of the package's THREE subprocess seams — the others are `cli._default_runner` and
    `workspace.default_git`, and the module docstring says why the count is stated instead of rounded
    down to one (`FI-27a`). Every other module receives a `Probes` and therefore stays testable
    without a machine underneath it.

    `tmux_socket` selects the tmux SERVER (see `TMUX_SOCKET_ENV`). Omitted, it comes from the
    environment, which is how a harness reaches a `python3 -m fleet.cli` subprocess whose probes it does
    not construct — the same contract `FLEET_HOME` already has. Passed explicitly, the argument wins:
    `None` is "the default server" and is not re-read from an inherited variable.
    """
    import os
    import shlex
    import subprocess

    if tmux_socket is _FROM_ENV:
        tmux_socket = os.environ.get(TMUX_SOCKET_ENV) or None

    #: Every tmux argv is built from this, so a site cannot be added later that skips the socket. `-L` is
    #: a SERVER option: tmux requires it before the subcommand, not after.
    tmux = ["tmux"] + (["-L", tmux_socket] if tmux_socket else [])

    def run(argv: list, **kwargs) -> "subprocess.CompletedProcess":
        return subprocess.run(argv, capture_output=True, text=True, **kwargs)

    def proc_field(pid: int, field: str) -> str:
        try:
            path = Path(proc_root) / str(pid) / field
            if field == "cwd":
                return str(path.resolve())
            return path.read_text()
        except OSError:
            return ""

    def parent_of(pid: int) -> int:
        try:
            # FB-53: `comm` inside `stat` is free bytes too, and a parent named in Latin-1 must not refuse the walk.
            stat = (Path(proc_root) / str(pid) / "stat").read_text(encoding="utf-8", errors="surrogateescape")
        except OSError:
            return 0
        # comm may contain spaces and parentheses; ppid is the field after the closing paren + state.
        tail = stat.rsplit(")", 1)[-1].split()
        try:
            return int(tail[1])
        except (IndexError, ValueError):
            return 0

    #: `PF_EXITING` in `/proc/<pid>/stat`'s flags field: set by `do_exit()` before it drops `exe` and `cwd`.
    pf_exiting = 0x4

    def exited_or_exiting(proc: Path) -> bool:
        try:
            fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
        except (OSError, UnicodeError, IndexError):
            return not proc.exists()
        try:
            flags = int(fields[6])
        except (IndexError, ValueError):
            flags = 0
        # The last clause is a race, not a redundancy: a pid reaped after its `stat` was read is gone, and
        # reporting it `unreadable` would put a phantom blocker in front of dispatch.
        return fields[:1] in (["Z"], ["X"]) or bool(flags & pf_exiting) or not proc.exists()

    where = f"socket {tmux_socket!r}" if tmux_socket else "the default socket"
    #: The route a human can take when this server cannot answer, named in every refusal about it (B26).
    held_route = (f"a tmux client stopped or wedged on {where} can hold that server up after its sessions "
                  f"are gone; `ps -o pid,stat,args -C tmux` names it (state T is stopped), and resuming "
                  f"or ending that client lets the server exit")

    def _no_server(error: str) -> bool:
        return error.startswith("no server running on ") or error.endswith("(No such file or directory)")

    def pane_owners() -> dict:
        """pane pid -> tmux session name, for attributing a process to its session.

        Three failures mean "this server holds no pane to attribute", and read as an empty population.
        Every other failure refuses — `Operation not permitted` is NOT an empty server. B26, measured on
        tmux 3.2a (`evidence/01-red/state-A.txt`, `state-B.txt` in the B26 instant):

        * no server on the socket (`no server running on …` / `… (No such file or directory)`);
        * a live server with ZERO sessions: `list-panes -a` still needs a current session and answers
          `no current target`. Not trusted as a string — `list-sessions` must positively list nothing;
        * a server that is exiting while a stopped client holds it: every command answers `server exited
          unexpectedly`, and `kill-server` has already destroyed its sessions. Also confirmed by a second
          command, so one crashed call does not read a live fleet as empty.
        """
        argv = tmux + ["list-panes", "-a", "-F", "#{pane_pid} #{session_name}"]
        done = run(argv)
        owners = {}
        if done.returncode != 0:
            error = done.stderr.strip()
            if _no_server(error):
                return owners
            confirm, route = "", ""
            if error in ("no current target", "server exited unexpectedly"):
                # Neither string is trusted alone: a second, different command must agree that there is
                # no session — rc=0 with zero rows (A), or no server answering it either (B).
                listed = run(tmux + ["list-sessions", "-F", "#{session_name}"])
                answer = listed.stderr.strip()
                if listed.returncode == 0 and not listed.stdout.strip():
                    return owners
                if listed.returncode != 0 and (_no_server(answer) or answer == "server exited unexpectedly"):
                    return owners
                rows = len(listed.stdout.splitlines()) if listed.returncode == 0 else 0
                confirm = (f"; `{shlex.join(tmux + ['list-sessions'])}` then exited {listed.returncode}"
                           + (f": {answer}" if answer else f" listing {rows} session(s)"))
                # The held-client route explains a server with NO sessions; when sessions were listed it
                # would send the reader after a client that is not the cause.
                route = "" if rows else f" ({held_route})"
            else:
                route = ""
            raise FleetError(
                f"Cannot inspect tmux server on {where}: `{shlex.join(argv[:-2])}` exited {done.returncode}: "
                f"{error or 'no message'}{confirm} · clears when: `{shlex.join(tmux + ['list-panes', '-a'])}` "
                f"answers, or no server runs on that socket{route} · clears who: the operator")
        for line in done.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0].isdigit():
                owners[int(parts[0])] = parts[1].strip()
        return owners

    def pane_of(pid: int, owners: dict) -> Optional[str]:
        """The tmux session whose pane pid is `pid` or one of its ancestors, through the world-readable `stat`."""
        walker, hops = pid, 0
        while walker > 1 and hops < 32:
            if walker in owners:
                return owners[walker]
            walker = parent_of(walker)
            hops += 1
        return None

    def list_processes() -> list:
        """Every live `claude`/`codex` process, attributed to its session where a pane owns it.

        Only the ENUMERATION refuses — `pgrep` failing or answering something that is not a pid list, or the
        pane listing refusing (`pane_owners`). No condition of ONE pid raises out of here (FB-53): that pid is
        skipped when the kernel says it is exiting, and otherwise reported as an `unreadable` row."""
        owners = pane_owners()
        out = []

        def unreadable(pid: int, runtime: str) -> LiveSession:
            # FB-54. Placed through the pane walk, which needs only `stat` — readable by anyone — so an unreadable
            # row is attributed exactly as a readable one would be. Its cwd was never read, and is not invented.
            return LiveSession(pid=pid, cwd=Path(f"/proc/{pid}"), name=pane_of(pid, owners), runtime=runtime,
                               unreadable=True)

        for runtime in (("claude", "codex") if both_runtimes else (process_name,)):
            done = run(["pgrep", "-x", runtime])
            if done.returncode == 1:
                continue
            if done.returncode != 0:
                raise FleetError(f"Cannot enumerate {runtime} processes: {done.stderr.strip()}")
            for token in done.stdout.split():
                if not token.isdigit():
                    raise FleetError(f"Invalid process inventory for {runtime}")
                pid = int(token)
                proc = Path(proc_root) / str(pid)
                try:
                    # FB-53. `comm` and `cmdline` are whatever bytes the process was started with; decoded strictly,
                    # one argv holding byte 0xe9 refused the whole inventory. Undecodable bytes are kept as
                    # surrogates, and identity is judged on `comm` and `exe` below — never on the prompt.
                    comm = (proc / "comm").read_text(encoding="utf-8", errors="surrogateescape").strip()
                    executable = os.readlink(proc / "exe")
                    argv = (proc / "cmdline").read_text(encoding="utf-8",
                                                        errors="surrogateescape").rstrip("\0").split("\0")
                    cwd = os.readlink(proc / "cwd")
                except (FileNotFoundError, ProcessLookupError):
                    # FB-41. The pid exited while the inventory was sampled, which the kernel says in three
                    # ways, all measured: a zombie (`Z`/`X`) or a task inside `do_exit()` — state still `R`/`D`
                    # but `PF_EXITING` set, `exe` and `cwd` already unlinked — or a pid reaped between open and
                    # read, whose directory is gone and whose read answered ESRCH. None holds a workspace.
                    # Anything else is reported `unreadable` like a denied read: a skip rests on what the
                    # kernel said, never on what it did not say, and a VANISHING pid never refuses the whole
                    # inventory.
                    if exited_or_exiting(proc):
                        continue
                    out.append(unreadable(pid, runtime))
                    continue
                except (OSError, UnicodeError):
                    # FB-53. A denied read (another uid, a non-dumpable process) and every other per-pid failure —
                    # an errno nobody measured, a decode that surrogateescape somehow did not absorb — report
                    # THIS pid and leave the rest of the inventory standing. They used to raise `Cannot inspect
                    # … process`, which took board, status, reconcile, dispatch and pane-guard down together.
                    out.append(unreadable(pid, runtime))
                    continue
                if not recognizes_process(runtime, comm, executable, argv):
                    continue
                out.append(LiveSession(pid=pid, cwd=Path(cwd), name=pane_of(pid, owners), runtime=runtime))
        agents = {item.pid for item in out}
        for item in out:
            item.nested = nested_under(item.pid, agents, owners)
        return out

    def nested_under(pid: int, agents: set, owners: dict) -> bool:
        """v23-k. Whether an inventoried agent is an ancestor of `pid` BELOW `pid`'s own pane root (the pane root
        itself counts: a codex that a claude pane started is nested). A pane root is never nested, whoever started
        its server. Bounded like `pane_of`, through the same world-readable `stat`."""
        if pid in owners:
            return False
        walker, hops = parent_of(pid), 0
        while walker > 1 and hops < 32:
            if walker in agents:
                return True
            if walker in owners:
                return False
            walker, hops = parent_of(walker), hops + 1
        return False

    # Every `-t` below is EXACT (`FI-23`). `new-session -s` is not a target and needs no marker: it
    # NAMES the session being created rather than resolving an existing one.
    def capture_pane(name: str):
        """The pane's text, or **None if the capture FAILED**.

        `FI-7`. This returned `""` on failure, so "tmux could not answer" and "the pane is empty" were
        the same value — and every caller then read the same falsy thing and drew the permissive
        conclusion. `pane-guard` answered `12 not-claude`, which the close-out contract treats as
        permission to tear the pane down.

        `None` and `""` are now different facts, which is the only way a caller can tell them apart. Any
        probe that can fail must be able to SAY it failed; a falsy default is a caller-visible lie.

        **`-e` IS PART OF THE CONTRACT, not a formatting preference (`FI-208`).** Without it tmux strips
        the SGR attributes, and the one bit that distinguishes *text a human typed* from *the TUI's own
        DIM ghost suggestion in an empty box* is discarded HERE — one layer below `unsubmitted`, below
        `pane-guard`, below `close`'s refusal and below every external monitor. Nothing above this line
        can recover it, and for ten and a half hours nothing above this line knew it was missing: every
        box alarm in a live effort was a false positive, and `close` refused a finished worker naming a
        clearing CONDITION of *"the text is submitted or cleared"* for a box that held nothing to clear —
        a remedy nobody could perform, which turns a guard into a toll.

        (The clearing-condition phrase above is deliberately not spelled as the field name `cli` and
        `guards` use. `tests/test_contracts.py` decides which modules are alarm-bearing by looking for
        that identifier as TEXT, and this module raises no such refusal — so writing it here would enrol
        `session` in a table it does not belong in. Same class as `FI-1`, and as the note at the top of
        this file about the liveness checker: a checker's own words tripping the checker.)

        Every consumer in this module reads the capture through `plain`/`_cells`, so the attributes are
        interpreted in exactly one place and are text nowhere. `tests/test_session.py` asserts this argv
        still carries `-e`, because the failure mode of losing it again is silent.
        """
        done = run(tmux + ["capture-pane", "-p", "-e", "-t", exact_pane_target(name)])
        return done.stdout if done.returncode == 0 else None

    def has_session(name: str) -> bool:
        return run(tmux + ["has-session", "-t", exact_session_target(name)]).returncode == 0

    def start_session(name: str, cwd: Path, command: str) -> None:
        done = run(tmux + ["new-session", "-d", "-x", "200", "-y", "50", "-s", name,
                           "-c", str(cwd), command])
        if done.returncode != 0:
            error = done.stderr.strip()
            route = ""
            if error == "server exited unexpectedly":
                route = (f" · clears when: the tmux server on {where} finishes exiting ({held_route}) · "
                         f"clears who: the operator")
            raise BadInput(f"tmux refused to start {name!r}: {error}{route}")

    def kill_session(name: str) -> None:
        run(tmux + ["kill-session", "-t", exact_session_target(name)])

    def pane_pid(name: str):
        """`list-panes` on an EXACT pane target — the same target form `capture_pane` uses, and for the
        same measured reason (`exact_pane_target`: a session-exact `=name` is not a pane target)."""
        done = run(tmux + ["list-panes", "-t", exact_pane_target(name), "-F", "#{pane_pid}"])
        if done.returncode != 0:
            return None
        for token in done.stdout.split():
            if token.isdigit():
                return int(token)
        return None

    def pane_pids(name: str):
        """`RV-20`. Every pane pid of the session: `list-panes -s` spans every window, not only the current."""
        done = run(tmux + ["list-panes", "-s", "-t", exact_session_target(name), "-F", "#{pane_pid}"])
        if done.returncode != 0:
            return None
        return [int(token) for token in done.stdout.split() if token.isdigit()] or None

    def session_servers(name: str) -> list:
        """Every tmux server on this box with a session called `name`, socket names, sorted.

        `SI-59`. tmux keeps one socket file per server under `$TMUX_TMPDIR|/tmp`/`tmux-<uid>`, so the
        candidates are simply readable — the same enumeration `bin/fleet-view` was doing on its own, moved
        in here so the verbs that ACT on a session can ask it too. A view that finds the session while
        `close` cannot is not a working diagnostic; it is one of two implementations disagreeing.

        The default server is included, spelled `""`, because a record can name it and a caller can be
        pointed away from it.
        """
        directory = os.path.join(os.environ.get("TMUX_TMPDIR") or "/tmp", f"tmux-{os.getuid()}")
        try:
            candidates = sorted(os.listdir(directory))
        except OSError:
            #: No socket directory at all means no server has ever run for this uid. That IS an
            #: observation — an empty list — and not the unobservable case `servers_with` returns None for.
            return []
        found = []
        for candidate in candidates:
            probe = ["tmux", "-L", candidate, "has-session", "-t", exact_session_target(name)]
            if run(probe).returncode == 0:
                found.append(candidate)
        return found

    def attachment(name: str):
        """`(interactive_clients, last_input_epoch, observers)` for the session named EXACTLY `name`, or None
        when unobserved. No client at all is `(0, 0, 0)`; `observers` counts read-only and control-mode clients.

        Read per CLIENT (`RV-28`), because `#{session_attached}` counts read-only (`attach -r`) and
        control-mode (`-C`) clients, and a read-only client's keystroke — dropped before it reaches the pane —
        still moves `#{session_activity}`. A read-only client cannot type into the pane; a control-mode client
        can (`send-keys`), but its `#{client_activity}` does NOT move when it does (`RV-36`,
        `evidence/20-red/tmux-control-mode-client-probe.txt`). Neither can show a human typed recently, so only
        interactive clients count and last input is the newest `#{client_activity}` among them; the others are
        returned as `observers`, never dropped, because "nobody attached" would be false. On tmux 3.2a that moves
        on the client's attach and its own keystroke, not on pane output, resize or SIGWINCH (B24 instant,
        `evidence/20-red/tmux-client-activity-probe.txt`).

        `list-clients -t =<name>`: tmux resolves the EXACT session and fails (rc=1, `can't find session` or
        `no server running`) when it cannot, so "not measured" never reads as "no client"
        (`evidence/20-red/list-clients-target-probe.txt`). Not `display-message`, which exits 0 with an
        empty format for a missing session (`display-message-missing-session.txt`) — `FI-7`'s falsy default.
        """
        done = run(tmux + ["list-clients", "-t", exact_session_target(name), "-F",
                           "#{client_session}\t#{client_readonly}\t#{client_control_mode}\t#{client_activity}"])
        if done.returncode != 0:
            return None
        clients, last_input, observers = 0, 0, 0
        for line in (done.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) != 4 or parts[1] not in ("0", "1") or parts[2] not in ("0", "1"):
                return None
            try:
                activity = int(parts[3])
            except ValueError:
                return None
            if parts[1] == "0" and parts[2] == "0":
                clients += 1
                last_input = max(last_input, activity)
            else:
                observers += 1
        return clients, last_input, observers

    def send_literal(name, text):
        import uuid
        buffer_name = 'fleet-' + uuid.uuid4().hex
        loaded = run(tmux + ['load-buffer', '-b', buffer_name, '-'], input=text)
        if loaded.returncode:
            raise FleetError(f'Cannot load tmux message: {loaded.stderr.strip()}')
        pasted = run(tmux + ['paste-buffer', '-p', '-d', '-b', buffer_name,
                             '-t', exact_pane_target(name)])
        if pasted.returncode:
            run(tmux + ['delete-buffer', '-b', buffer_name])
            raise FleetError(f'Cannot paste tmux message: {pasted.stderr.strip()}')

    def submit(name):
        done = run(tmux + ['send-keys', '-t', exact_pane_target(name), 'Enter'])
        if done.returncode:
            raise FleetError(f'Cannot submit tmux message: {done.stderr.strip()}')

    return Probes(list_processes=list_processes, socket=tmux_socket or "",
                  send_literal=send_literal, submit=submit,
                  session_servers=session_servers,
                  capture_pane=capture_pane,
                  has_session=has_session,
                  start_session=start_session,
                  kill_session=kill_session,
                  pane_pid=pane_pid,
                  pane_pids=pane_pids,
                  parent_of=parent_of,
                  attachment=attachment)
