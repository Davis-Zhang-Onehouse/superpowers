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

#: SGR — the "select graphic rendition" escape, the ONLY thing `capture-pane -e` adds to a capture. It is
#: also the whole of `FI-208`: an empty Claude Code box is not blank, it is drawn holding a model-generated
#: ghost SUGGESTION in **SGR 2 (DIM/faint)**, and a capture taken WITHOUT `-e` throws that attribute away
#: one layer below every consumer. `pane-guard` then reported `10 queued-text` for a box nobody had typed
#: into, `close` refused naming a clearing condition of *"the text is submitted or cleared"* — a remedy
#: that cannot be performed, because there is no text — and the question "who typed that?" (`FI-43`) was
#: chased for days over a string that had no author.
_SGR = re.compile(r"\x1b\[([0-9;]*)m")
#: Any OTHER escape `-e` or a TUI may emit. Stripped, never interpreted — this module reasons about
#: VISIBLE characters plus one attribute, and a sequence it does not understand must not become text.
_ESC_OTHER = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;:?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")

#: The SGR parameters that turn DIM on and off, compared AFTER leading zeros are stripped — so `0` and a
#: bare `\x1b[m` both arrive here as `""`. `2` is faint; `0`/`""` reset everything; `22` is the targeted
#: "normal intensity" that ends bold AND faint. Nothing else touches it.
_SGR_DIM_ON = "2"
_SGR_DIM_OFF = ("", "22")

#: SGR parameters that SWALLOW the parameters after them: `38` (foreground), `48` (background) and `58`
#: (underline colour) introduce an extended colour, and the value that follows selects its form —
#: `5;<n>` is a 256-colour index (one more parameter), `2;<r>;<g>;<b>` is truecolor (three more).
#:
#: This is not pedantry about a spec. **`\x1b[38;2;136;192;208m` contains a `2`**, and read parameter-by
#: -parameter that `2` is SGR 2 = DIM. My first version of `_cells` did exactly that, and the consequence
#: was measured: `_caret_content` returned `''` for `❯ ` + truecolor + `REAL-TYPED-TEXT-GAMMA`, so a
#: truecolor-styled input box makes REAL TYPED TEXT VANISH — `unsubmitted` None, `pane-guard 0 safe`, and
#: a `send-keys` concatenates onto somebody's live draft. That is the exact false-safe `AC-5` forbids and
#: `FI-169` exists to prevent, reintroduced by the fix for `FI-208`. `38;5;2` (256-colour index 2) failed
#: the same way; `38;5;99` did not, which is what a partial fix looks like from the outside.
_SGR_EXTENDED_COLOUR = ("38", "48", "58")
#: How many parameters each extended-colour FORM consumes after its selector.
_SGR_COLOUR_FORM = {"5": 1, "2": 3}


def plain(text: str) -> str:
    """`text` with every escape removed — the VISIBLE characters, and nothing else.

    Public because `capture()` now returns what tmux drew *including* attributes, and a caller matching
    UI chrome (`cli.CLAUDE_MARKERS`) must match on what a human would read. Matching a marker against raw
    capture output works right up until tmux happens to split the phrase across a colour change, and then
    it fails silently in the direction that reports a live claude pane as `12 not-claude`.
    """
    return _ESC_OTHER.sub("", _SGR.sub("", text))


def _cells(line: str) -> list:
    """`line` as `[(visible character, is it DIM), …]`.

    The pair is the point. Every predicate below wants the characters; exactly one of them —
    `_caret_content` — also wants the attribute, and it is the one bit that separates *a human typed
    this* from *the TUI is suggesting this*. Carrying them together means no layer can drop the second
    while keeping the first, which is precisely how `FI-208` happened.
    """
    out, dim, i = [], False, 0
    while i < len(line):
        match = _SGR.match(line, i)
        if match:
            params = match.group(1).split(";")
            index = 0
            while index < len(params):
                param = params[index].lstrip("0")          # `2`, `02` and `002` are all SGR 2
                index += 1
                if param in _SGR_EXTENDED_COLOUR:
                    #: Skip the selector AND its arguments, so the `2` inside `38;2;R;G;B` is a colour
                    #: component and never SGR 2. An unknown selector consumes only itself, which stops a
                    #: malformed sequence eating the rest of the line.
                    selector = params[index].lstrip("0") if index < len(params) else ""
                    index += 1 + _SGR_COLOUR_FORM.get(selector or "0", 0)
                elif param == _SGR_DIM_ON:
                    dim = True
                elif param in _SGR_DIM_OFF:
                    dim = False
            i = match.end()
            continue
        match = _ESC_OTHER.match(line, i)
        if match:
            i = match.end()
            continue
        out.append((line[i], dim))
        i += 1
    return out


def _undim(cells: list) -> str:
    """The characters a human actually typed: the cells left once the DIM ones are dropped.

    **Not** "empty if any cell is dim". A box can hold typed text AND a dim completion hint at once, and
    calling that whole body a placeholder would blind the guard to real queued text — the `FI-180` shape,
    where a fix stops a failure being visible instead of fixing it. Dropping only the dim cells answers
    both directions from one rule: an all-dim body collapses to `''` (an empty box), and a body with any
    non-dim character keeps exactly that character as the queued text.
    """
    return "".join(char for char, dim in cells if not dim).strip()


#: Shapes an EMPTY input box renders. None of these is a swallowed submit, and alarming on them is a
#: false positive on every idle session in the fleet at once.
#:
#: These are the FALLBACK, not the primary signal (`FI-208`). They are five fixed legacy strings and the
#: thing they need to catch today is *model-generated prose* — a denylist of suggestion texts can never be
#: completed, so the attribute decides first and these only answer for a terminal that stripped it.
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

#: `FI-255`/`i39`. What the harness draws when something is armed that will RE-INVOKE this session with no
#: human in the loop: a `Monitor` renders `1 monitor`, a background shell renders `1 shell`, and both
#: together render `1 shell, 1 monitor`. Measured on a live pane, both arms, in `i39`'s evidence.
#:
#: A COUNTED NOUN, not a bare word, and matched on the STATUS LINE alone rather than the busy window. Both
#: halves of that are load-bearing and both were measured, not reasoned:
#:
#:  - the bare word fails because `BUSY_TAIL_LINES` is 15 rows and an agent's own prose lives in them. The
#:    capture taken while authoring this change has "monitors" inside that window purely because the agent
#:    was WRITING ABOUT monitors. `"monitor" in window` therefore reports a watcher for a session that
#:    merely discussed one — a guard that admits everything, which is indistinguishable from a guard that
#:    works and is the exact failure `i39`'s charter names.
#:  - the status line is where the harness draws this indicator, and `_rendered` already discards tmux's
#:    bottom padding, so its last row IS that line.
_WATCHER_MARKER = re.compile(r"\b\d+\s+(?:monitor|shell)s?\b")

#: What identifies the row as the harness's STATUS LINE rather than any other row on screen. The watcher
#: indicator shares this row, so requiring both on one line is what separates "the harness is telling me a
#: watcher is armed" from "the agent typed the word monitor".
_STATUS_LINE_MARKERS = _BUSY_MARKERS + ("auto mode on", "? for shortcuts", "for agents")


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

    Blankness is judged on the VISIBLE characters (`plain`), which is not cosmetic now that the capture
    carries attributes: a padding row that tmux emits as `\\x1b[39m\\x1b[49m` is blank to a reader and
    NON-blank to `str.strip`, so trimming on the raw row stops at the padding and re-opens `FI-24` with
    the window anchored below the content. Measured before the fix: a two-row frame with two styled-blank
    padding rows kept **4** rows where the plain equivalent keeps 2.
    """
    rows = text.splitlines()
    while rows and not plain(rows[-1]).strip():
        rows.pop()
    return rows


def _tail(text: str, count: int) -> list:
    return _rendered(text)[-count:]


def _trim(cells: list) -> list:
    """`cells` with leading and trailing whitespace dropped, attributes kept alongside."""
    start, end = 0, len(cells)
    while start < end and cells[start][0].isspace():
        start += 1
    while end > start and cells[end - 1][0].isspace():
        end -= 1
    return cells[start:end]


def _caret_content(line: str) -> Optional[str]:
    """The text a caret line carries **that a human typed**, or None when the line has no caret.

    Tolerates the box-drawing gutter a real pane draws around its input box, and — since `FI-208` — the
    SGR attributes the capture now carries.

    Both halves of the attribute handling are load-bearing and they fail in OPPOSITE directions:

    * **Finding the caret at all.** The live `w22` box row is `\\x1b[39m❯\\xa0`: the caret is preceded by a
      colour escape. Under the old text-only rule `line.strip()[0]` is `ESC`, so the caret is not found,
      `unsubmitted` reports None, and `pane-guard` answers `0 safe` **for a box holding real typed text**.
      Adding `-e` to the capture *without* this is therefore not a fix — it is a false-safe, and a worse
      defect than the one it was meant to close. Measured before the change: `_caret_content` returned
      `None` for that exact live row.
    * **Deciding what the body IS.** `_undim` drops the DIM cells, so a body drawn entirely in SGR 2 —
      Claude Code's ghost suggestion in an EMPTY box — collapses to `''` and a body with any normal-
      intensity character keeps it. Attribute first, `_PLACEHOLDERS` only as the fallback for a terminal
      that stripped attributes (`AC-6`): the suggestion is model-generated prose, so no list of texts
      could ever have matched it.
    """
    cells = _trim(_cells(line))
    while cells and cells[0][0] in _GUTTER:
        cells = _trim(cells[1:])
    for caret in _CARET:
        if "".join(char for char, _ in cells[:len(caret)]) == caret:
            body = _trim(cells[len(caret):])
            while body and body[-1][0] in _GUTTER:
                body = _trim(body[:-1])
            return _undim(body)
    return None


def _is_placeholder(content: str) -> bool:
    return any(pattern.search(content) for pattern in _PLACEHOLDERS)


class SessionLayer:
    """Liveness, pane state and session control — the whole outside world in one object."""

    def __init__(self, probes: Probes):
        self.probes = probes

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
        direction that lands a send in the middle of a turn.

        Matched on the VISIBLE characters (`plain`). The capture carries attributes now, and a marker is a
        PHRASE: the moment tmux emits a colour change inside `esc to interrupt` — which it does whenever
        the TUI styles part of a hint — a raw substring match stops finding it and a mid-turn pane reads
        idle. Stripping first makes the match test what a human would read."""
        window = plain("\n".join(_tail(pane_text, BUSY_TAIL_LINES))).lower()
        return any(marker in window for marker in _BUSY_MARKERS)

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

    def watchers(self, pane_text: str) -> str:
        """What the status line says is armed — `"1 shell, 1 monitor"` — or `""` when nothing is.

        The TEXT and not just the boolean, because the claim RECORDS what it observed. `FI-255`'s harm was
        that nothing distinguishable was written down at claim time: two opposite states produced one
        byte-identical row, so the record could not answer the question afterwards. A stored `true` would
        repeat that mistake one field along.
        """
        for row in reversed(_tail(pane_text, BUSY_TAIL_LINES)):
            #: The status line is found by its SIGNATURE, not by its position, and both halves of that
            #: matter. Position alone (`rows[-1]`) was the first implementation and it has a measured false
            #: positive: anything drawn BELOW the status line — a tool-approval prompt, a notification —
            #: displaces it, and a genuinely watched session is then refused. That direction is safe but it
            #: lands on somebody who did nothing wrong.
            #:
            #: The marker and the signature must appear on the SAME row, which is what keeps this immune to
            #: the contamination a bare window scan suffers: an agent writing *about* monitors puts the
            #: word in the window, but not onto a row that is also drawing the interrupt hint.
            plain_row = plain(row).lower()
            if not any(marker in plain_row for marker in _STATUS_LINE_MARKERS):
                continue
            return ", ".join(match.group(0) for match in _WATCHER_MARKER.finditer(plain_row))
        return ""

    # --- control -----------------------------------------------------------------------------

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

    return Probes(list_processes=list_processes, socket=tmux_socket or "",
                  session_servers=session_servers,
                  capture_pane=capture_pane,
                  has_session=has_session,
                  start_session=start_session,
                  kill_session=kill_session,
                  pane_pid=pane_pid)
