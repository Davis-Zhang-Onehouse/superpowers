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
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from fleet.errors import BadInput

#: How much of the pane is "now", counted UP FROM THE LAST NON-BLANK ROW. A caret above this window is
#: scrollback, not a queued message. Counted from the last non-blank row rather than from the last raw
#: capture line because tmux pads a capture to the pane height (`_rendered`, `FI-24`).
PROMPT_TAIL_LINES = 8
#: Busy indicators sit a little further up than the input box (spinner line, token counter, hints).
BUSY_TAIL_LINES = 15

#: The characters a pane may render an input caret with.
_CARET = ("❯", ">")
#: Box-drawing gutter around the input box, stripped before the caret is looked for.
_GUTTER = "│┃|"

#: Shapes an EMPTY input box renders. None of these is a swallowed submit, and alarming on them is a
#: false positive on every idle session in the fleet at once.
_PLACEHOLDERS = (
    re.compile(r'^try\s+["“]', re.I),
    re.compile(r"^ask\b", re.I),
    re.compile(r"^/\s*for\s+commands\b", re.I),
    re.compile(r"^#\s*for\s+memory\b", re.I),
    re.compile(r"^new\s+task\?", re.I),
)

#: A pane is busy when it is still offering a way to interrupt the work.
#: What a pane shows while it is WORKING. `SI-37`: "esc to cancel" was here and is not that — it is what a
#: MODAL offers while it waits for a human to choose. The two read alike and mean opposite things: one says
#: "a turn is in flight, your send will queue behind it", the other says "nothing will happen until somebody
#: answers me".
#:
#: The cost was measured on the first production dispatch. A fresh claude in an untrusted directory shows
#: "Is this a project you created or one you trust?" with "Enter to confirm · Esc to cancel". `busy` matched,
#: so `pane-guard` said `11 mid-turn` and `reconcile` said RUNNING — for a session that had not started and
#: never would. A coordinator following the documented loop waits forever on a pane needing one keystroke.
#:
#: Removing it costs nothing, because `unsubmitted` ALREADY detects the modal's selected line as text in the
#: input position. With `busy` no longer firing, the guard reaches its queued-text branch and `_live_state`
#: reaches BLOCKED — "the pane is waiting on a human", which is exactly what a trust modal is. It stays in
#: `CLAUDE_MARKERS`: a modal is still a claude pane, it is just not a busy one.
_BUSY_MARKERS = (
    "esc to interrupt",
    "ctrl+c to stop",
)


@dataclass
class LiveSession:
    """A process that is actually running, whether or not anything recorded it."""

    pid: int
    cwd: Path
    name: Optional[str]


@dataclass
class Probes:
    """The seam between this module and the machine. Injected, so a test never needs a real tmux."""

    list_processes: Callable[[], list]
    #: `FI-7`: returns None when the capture FAILED, `''` for a genuinely empty pane.
    capture_pane: Callable[[str], Optional[str]]
    has_session: Callable[[str], bool]
    start_session: Callable[[str, Path, str], None]
    kill_session: Callable[[str], None]
    #: `G-2`. Session names a human is attached to, or None when tmux could not be asked. Set-valued so
    #: one tmux call answers for the whole fleet: a per-name probe would mean one subprocess per subject
    #: on every nudge pass. Defaulted, because every existing construction of `Probes` predates it and a
    #: required field here would break every caller and every fixture at once.
    attached_sessions: Callable[[], Optional[set]] = lambda: set()


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


def _rendered(text: str) -> list:
    """The rows the pane is actually SHOWING, with tmux's bottom padding removed.

    `capture-pane` pads its output to the PANE HEIGHT. `M11b` measured an input box holding
    `draft message` at capture line 2 with 31 blank rows beneath it, so every window counted in raw
    lines put the box outside itself and the predicate answered *safe* with text in the box — a
    false-safe, the dangerous direction. The last non-blank row is the bottom of the content; the
    window is anchored there.
    """
    rows = text.splitlines()
    while rows and not rows[-1].strip():
        rows.pop()
    return rows


def _tail(text: str, count: int) -> list:
    return _rendered(text)[-count:]


def _caret_content(line: str) -> Optional[str]:
    """The text a caret line carries, or None when the line has no caret.

    Tolerates the box-drawing gutter a real pane draws around its input box.
    """
    stripped = line.strip()
    while stripped and stripped[0] in _GUTTER:
        stripped = stripped[1:].strip()
    for caret in _CARET:
        if stripped.startswith(caret):
            body = stripped[len(caret):]
            return body.strip().rstrip(_GUTTER).strip()
    return None


def _is_placeholder(content: str) -> bool:
    return any(pattern.search(content) for pattern in _PLACEHOLDERS)


class SessionLayer:
    """Liveness, pane state and session control — the whole outside world in one object."""

    def __init__(self, probes: Probes):
        self.probes = probes

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

    def attached(self, name: str) -> bool:
        """Whether a HUMAN is attached to this session's client.

        FAILS SAFE: an unanswerable probe reports True. The consumer is `nudge`, which types into a pane,
        and "I could not tell whether somebody is sitting there" must mean "leave it alone". A guard whose
        failure mode is 'go ahead' is not a guard — the same reasoning that keeps `pane-guard`'s `14`
        outside the can-go set.

        This collects the fact `G-4` needs and deliberately does NOT use it to change any state's
        meaning. `BLOCKED` still cannot distinguish a stuck worker from an attached human; that is `G-4`
        and it stays open.
        """
        if not name:
            return False
        attached = self.probes.attached_sessions()
        if attached is None:
            return True
        return name in attached

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

    def unsubmitted(self, pane_text: str) -> Optional[str]:
        """Text sitting in the input box that was never submitted, or None.

        The input box is identified STRUCTURALLY: it is the **last** caret among the rendered rows,
        within `PROMPT_TAIL_LINES` of the last non-blank one. Both halves are corrections of measured
        false answers (`FI-24`), and they fail in opposite directions:

        * **The last caret, not the first.** A real shell — and Claude's own transcript — leaves the
          *submitted* prompt on screen and draws the new empty box BELOW it. `N4` submitted its
          message and the predicate still reported `draft message`, read off the echo above the new
          box, so `pane-guard` stayed at 10 and `status` at BLOCKED: an alarm that cannot be cleared
          by doing the thing it asks for, for the sixth time in this build. The first caret in a
          window is not the box; it is the most recent thing the box FINISHED with.
        * **Anchored to the last non-blank row, not to a raw line index.** See `_rendered` — `M11b`'s
          box sat 31 blank padding rows above the bottom of the capture and read as safe.

        `N8` — a stale caret with output below it and an empty box at the bottom — is safe under this
        rule because the empty box is the LAST caret, which is why it holds at 13 rows up and at 3.
        Under the previous rule it held only because 13 > 8: an eight-line accident, not a property,
        and the 3-row fixture is the one that says so.

        An empty box is not a swallowed submit: an empty caret answers None outright rather than
        falling back to an earlier caret (falling back IS the `N4` defect), and the placeholder shapes
        a pane renders when the box is empty are filtered out rather than reported.
        """
        box = None
        for line in _tail(pane_text, PROMPT_TAIL_LINES):
            content = _caret_content(line)
            if content is not None:
                box = content              # keep going: the LAST caret in the window is the box
        if not box or _is_placeholder(box):
            return None
        return box

    def is_claude_process(self, name: str) -> bool:
        """Whether a live CLAUDE PROCESS is attributed to this session.

        `SI-38`. Process evidence, not screen scraping. `live()` comes from `pgrep -x claude` joined to
        tmux pane ownership, so a True here means a real claude is running in that session — a fact no
        amount of scrollback can change.

        This exists because the glyph test cannot answer it. A pane's markers ("esc to interrupt",
        "? for shortcuts", …) are UI chrome that scrolls away: a long answer followed by an idle prompt
        contains none of them, and a claude idle for twenty minutes was classified `12 not-claude` on a
        live coordinator whose pid was verified alive in the same breath. `12` is one of the codes the
        close-out contract treats as "the pane can go", and its own text says "a send here goes to
        somebody else's shell" — both false, in the dangerous direction.
        """
        if not name:
            return False
        return any(session.name == name for session in self.live())

    def busy(self, pane_text: str) -> bool:
        """Whether the pane is still working. Anchored to the tail for the same reason as above — an
        interrupt hint from an hour ago is not evidence of current work — and to the tail of the
        RENDERED rows for the same reason as `unsubmitted`: padding that pushed an input box out of its
        window pushes an interrupt hint out of this one too, and a mid-turn pane reading idle is the
        direction that lands a send in the middle of a turn."""
        window = "\n".join(_tail(pane_text, BUSY_TAIL_LINES)).lower()
        return any(marker in window for marker in _BUSY_MARKERS)

    # --- control -----------------------------------------------------------------------------

    def start(self, name: str, cwd: Path, command: str) -> None:
        if not name:
            raise BadInput("a session needs a name")
        self.probes.start_session(name, Path(cwd), command)

    def kill(self, name: str) -> None:
        if not name:
            raise BadInput("a session needs a name to be killed")
        self.probes.kill_session(name)


def default_probes(process_name: str = "claude", tmux_socket=_FROM_ENV) -> Probes:
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
    import subprocess

    if tmux_socket is _FROM_ENV:
        tmux_socket = os.environ.get(TMUX_SOCKET_ENV) or None

    #: Every tmux argv is built from this, so a site cannot be added later that skips the socket. `-L` is
    #: a SERVER option: tmux requires it before the subcommand, not after.
    tmux = ["tmux"] + (["-L", tmux_socket] if tmux_socket else [])

    def run(argv: list) -> "subprocess.CompletedProcess":
        return subprocess.run(argv, capture_output=True, text=True)

    def proc_field(pid: int, field: str) -> str:
        try:
            path = Path("/proc") / str(pid) / field
            if field == "cwd":
                return str(path.resolve())
            return path.read_text()
        except OSError:
            return ""

    def parent_of(pid: int) -> int:
        try:
            stat = (Path("/proc") / str(pid) / "stat").read_text()
        except OSError:
            return 0
        # comm may contain spaces and parentheses; ppid is the field after the closing paren + state.
        tail = stat.rsplit(")", 1)[-1].split()
        try:
            return int(tail[1])
        except (IndexError, ValueError):
            return 0

    def pane_owners() -> dict:
        """pane pid -> tmux session name, for attributing a process to its session."""
        done = run(tmux + ["list-panes", "-a", "-F", "#{pane_pid} #{session_name}"])
        owners = {}
        if done.returncode != 0:
            return owners
        for line in done.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0].isdigit():
                owners[int(parts[0])] = parts[1].strip()
        return owners

    def list_processes() -> list:
        done = run(["pgrep", "-x", process_name])
        if done.returncode != 0:
            return []
        owners = pane_owners()
        out = []
        for token in done.stdout.split():
            if not token.isdigit():
                continue
            pid = int(token)
            cmdline = proc_field(pid, "cmdline")
            if cmdline and process_name not in cmdline.replace("\0", " "):
                continue
            cwd = proc_field(pid, "cwd")
            name, walker, hops = None, pid, 0
            while walker > 1 and hops < 32:
                if walker in owners:
                    name = owners[walker]
                    break
                walker = parent_of(walker)
                hops += 1
            out.append(LiveSession(pid=pid, cwd=Path(cwd or "/"), name=name))
        return out

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
        """
        done = run(tmux + ["capture-pane", "-p", "-t", exact_pane_target(name)])
        return done.stdout if done.returncode == 0 else None

    def has_session(name: str) -> bool:
        return run(tmux + ["has-session", "-t", exact_session_target(name)]).returncode == 0

    def start_session(name: str, cwd: Path, command: str) -> None:
        done = run(tmux + ["new-session", "-d", "-s", name, "-c", str(cwd), command])
        if done.returncode != 0:
            raise BadInput(f"tmux refused to start {name!r}: {done.stderr.strip()}")

    def kill_session(name: str) -> None:
        run(tmux + ["kill-session", "-t", exact_session_target(name)])

    def attached_sessions():
        #: `#{session_attached}` is a COUNT of attached clients, not a bool: >0 means somebody is looking.
        #: A tmux that answers non-zero (no server, no sessions) returns None — "could not ask" — which
        #: `SessionLayer.attached` reads as attached, not as free.
        done = run(tmux + ["list-sessions", "-F", "#{session_name} #{session_attached}"])
        if done.returncode != 0:
            return None
        names = set()
        for line in (done.stdout or "").splitlines():
            parts = line.rsplit(" ", 1)
            if len(parts) == 2 and parts[1].strip() not in ("", "0"):
                names.add(parts[0].strip())
        return names

    return Probes(list_processes=list_processes,
                  capture_pane=capture_pane,
                  has_session=has_session,
                  start_session=start_session,
                  kill_session=kill_session,
                  attached_sessions=attached_sessions)
