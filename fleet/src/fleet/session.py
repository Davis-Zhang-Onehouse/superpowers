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

from fleet.errors import BadInput, FleetError

from fleet.runtime import (
    PROMPT_TAIL_LINES, BUSY_TAIL_LINES, plain, _cells, _undim, _caret_content,
    _rendered, _tail, _trim, _is_placeholder, claude_unsubmitted, claude_busy,
    claude_watchers, observe, validate_runtime, PaneObservation, recognizes_process,
)

#: `I-16`. The `AskUserQuestion` selection dialog's own hint line, quoted VERBATIM from the register:
#: "Enter to select · Tab/Arrow keys to navigate · Esc to cancel". Neither `_BUSY_MARKERS` nor `_CARET`
#: fires for this dialog (see the `SI-37` amendment above), which is the whole defect — the pane fell
#: through to `0 safe`.
#:
#: THREE fragments, not one, and required TOGETHER on a single row — `_WATCHER_MARKER`'s lesson applied
#: here on purpose. `"esc to cancel"` alone is the exact phrase `SI-37` measured firing on an unrelated
#: modal, and it is also a phrase this module's OWN comments now contain (this one included) — a
#: single-fragment match against a multi-line window would risk exactly the false positive `SI-37` spent a
#: production incident correcting, from the opposite direction: an agent's transcript merely discussing
#: this dialog, or reviewing this change, contains the words "select", "navigate" and "cancel" too.
#:
#: **Correction, measured rather than assumed:** this module once claimed no agent's own prose renders all
#: three EXACT fragments concatenated onto one row. That is false, and in-tree — `SessionLayer.asking()`
#: run over this module's OWN source lines 215-222 returns `True`. Four one-row occurrences exist right
#: here: the hint-line comment eight lines above this one (`session.py:219`), `DIALOG_PANE`'s own last
#: line in both `tests/test_session.py:496` and `tests/test_cli.py:106`, and the design spec that recorded
#: this finding. The three-fragment one-row shape is overwhelmingly the harness's, but not exclusively —
#: so co-occurrence on one line is a near-certain anchor, not a guaranteed one, the same role the
#: counted-noun-on-the-status-line pairing plays for `_WATCHER_MARKER`. The residual exposure is honest,
#: not absent: text that quotes the banner verbatim, on one rendered row, inside this bounded tail window
#: classifies as `15 PANE_AWAITING_OPERATOR`. That is fail-safe — a pane reads as blocked rather than
#: idle, never the reverse — and `--force` clears it, so a false positive here costs one refusal, not a
#: wrong send.
_DIALOG_MARKERS = ("enter to select", "tab/arrow keys to navigate", "esc to cancel")


@dataclass
class LiveSession:
    """A process that is actually running, whether or not anything recorded it."""

    pid: int
    cwd: Path
    name: Optional[str]
    runtime: str = "claude"


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

    def is_agent_process(self, name: str) -> bool:
        return bool(name) and any(item.name == name and item.runtime == self.runtime
                                  for item in self.live())

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
        return any(session.name == name and session.runtime == "claude" for session in self.live())

    def busy(self, pane_text: str):
        if self.runtime == "claude":
            return claude_busy(pane_text)
        return observe(self.runtime, pane_text).state == "busy"

    def asking(self, pane_text: str) -> bool:
        """Whether the pane is blocked at an `AskUserQuestion` selection dialog, waiting on an operator's
        answer. `I-16`.

        Callers check this AFTER `busy` and `unsubmitted` (`cli._do_pane_guard`), so a pane that is
        genuinely mid-turn or genuinely holding typed text keeps its existing, stronger answer — this is
        the last resort for the one shape neither of those already covers (the `SI-37` amendment above
        records why neither one does).

        Anchored to `PROMPT_TAIL_LINES` — the same bounded window `unsubmitted` scans for the input box —
        rather than the wider `BUSY_TAIL_LINES` or the whole pane: the dialog's hint line renders where the
        input box would, and bounding the search is what keeps a long turn's SCROLLED-PAST output (which
        may well discuss this exact dialog) out of view by the time the turn ends and this predicate is
        even reached. Matched on `plain` text for the same reason as `busy` — the TUI is free to colour
        part of the hint, and a raw substring match stops finding it the moment it does.
        """
        for line in _tail(pane_text, PROMPT_TAIL_LINES):
            row = plain(line).lower()
            if all(marker in row for marker in _DIALOG_MARKERS):
                return True
        return False

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
            stat = (Path(proc_root) / str(pid) / "stat").read_text()
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
            error = done.stderr.strip()
            if (error.startswith("no server running on ") or
                    error.endswith("(No such file or directory)")):
                return owners
            raise FleetError(f"Cannot inspect tmux server: {error or 'list-panes failed'}")
        for line in done.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0].isdigit():
                owners[int(parts[0])] = parts[1].strip()
        return owners

    def list_processes() -> list:
        owners = pane_owners()
        out = []
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
                    comm = (proc / "comm").read_text().strip()
                    executable = os.readlink(proc / "exe")
                    argv = (proc / "cmdline").read_text().rstrip("\0").split("\0")
                    cwd = os.readlink(proc / "cwd")
                except FileNotFoundError:
                    # Zombies remain in pgrep and /proc until their parent reaps
                    # them, but have no executable or cwd and hold no workspace.
                    try:
                        state = (proc / "stat").read_text().rsplit(")", 1)[1].split()[0]
                    except (OSError, UnicodeError, IndexError):
                        state = None
                    if state in ("Z", "X") or not proc.exists():
                        continue  # Exited while inventory was sampled.
                    raise FleetError(f"Cannot inspect live {runtime} process {pid}")
                except (OSError, UnicodeError) as exc:
                    raise FleetError(f"Cannot inspect {runtime} process {pid}: {exc}") from exc
                if not recognizes_process(runtime, comm, executable, argv):
                    continue
                name, walker, hops = None, pid, 0
                while walker > 1 and hops < 32:
                    if walker in owners:
                        name = owners[walker]
                        break
                    walker = parent_of(walker)
                    hops += 1
                out.append(LiveSession(pid=pid, cwd=Path(cwd), name=name, runtime=runtime))
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
        done = run(tmux + ["new-session", "-d", "-s", name, "-c", str(cwd), command])
        if done.returncode != 0:
            raise BadInput(f"tmux refused to start {name!r}: {done.stderr.strip()}")

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
                  pane_pid=pane_pid)
