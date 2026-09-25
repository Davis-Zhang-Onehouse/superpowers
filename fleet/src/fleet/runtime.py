"""Runtime identities and pure terminal observations; no machine I/O."""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from fleet.errors import BadInput

RuntimeName = Literal["claude", "codex"]
PaneState = Literal["idle", "queued", "busy", "dialog", "unknown"]


@dataclass(frozen=True)
class LaunchSettings:
    runtime: RuntimeName
    executable: str
    config_dir: str
    #: pt2. The model this worker is launched with; "" passes NO model flag, so the CLI uses its own configured
    #: model (the slot's claude setting, codex's default) — exactly the launch before this field existed.
    model: str = ""


@dataclass(frozen=True)
class RuntimeChoice:
    """What one dispatch runs, and where each half came from (`flag` / `profile` / `box` / `default`)."""
    runtime: RuntimeName
    model: str
    runtime_source: str
    model_source: str


@dataclass(frozen=True)
class PaneObservation:
    state: PaneState
    draft: str | None = None
    watcher: str = ""


def validate_runtime(value: str) -> RuntimeName:
    if not isinstance(value, str) or value not in ("claude", "codex"):
        raise BadInput(f"Unknown fleet runtime {value!r}; expected claude or codex")
    return value


#: One argv token naming a model: `claude-fable-5-1`, `claude-opus-5-5[1m]`, `gpt-6-sol`, `openai/gpt-5.1:high`.
#: Never a leading `-`: the value is placed on the worker's argv, and `--model --dangerously-skip-permissions`
#: must be a refusal rather than a flag the worker was launched with.
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\[\]-]*")


def validate_model(value) -> str:
    if not isinstance(value, str) or not _MODEL.fullmatch(value):
        raise BadInput(f"Invalid model {value!r}; expected one model name such as claude-fable-5-1 or gpt-6-sol "
                       f"(letters, digits and . _ : / [ ] -, not starting with -). Omit it to use the CLI's "
                       f"configured default model")
    return value


def choose_runtime(box: RuntimeName, *, flag_runtime=None, flag_model=None,
                   profile_runtime=None, profile_model=None) -> RuntimeChoice:
    """pt2 (D-22/D-33). The runtime is `--runtime` > the profile's `runtime` > the box's saved selection; the
    model is `--model` > the profile's `model` > none. A profile's model belongs to the profile's runtime, so it
    applies only when that runtime is the one chosen: a `--runtime` override drops it rather than handing a
    claude model name to codex. "No model" is not a value — it is the absence of a model flag on the argv."""
    if flag_runtime is not None:
        runtime, runtime_source = validate_runtime(flag_runtime), "flag"
    elif profile_runtime:
        runtime, runtime_source = validate_runtime(profile_runtime), "profile"
    else:
        runtime, runtime_source = validate_runtime(box), "box"
    if flag_model is not None:
        model, model_source = validate_model(flag_model), "flag"
    elif profile_model and profile_runtime == runtime:
        model, model_source = validate_model(profile_model), "profile"
    else:
        model, model_source = "", "default"
    return RuntimeChoice(runtime, model, runtime_source, model_source)


def recognizes_process(runtime: RuntimeName, comm: str, executable: str, argv: list[str]) -> bool:
    """Native worker identity, never a prompt or a Node launcher mentioning it."""
    validate_runtime(runtime)
    if comm != runtime or not executable or not argv:
        return False
    path = Path(executable)
    if runtime == "codex":
        return path.name == "codex"
    return path.name == "claude" or (path.parent.name == "versions"
                                      and "claude" in path.parts)


def observe(runtime: RuntimeName, frame: str) -> PaneObservation:
    validate_runtime(runtime)
    rows = _rendered(frame)
    if not rows:
        return PaneObservation("unknown")
    visible = [plain(row).strip() for row in rows]
    if _dialog_row(runtime, visible):
        return PaneObservation("dialog")
    if runtime == "claude":
        caret = _claude_caret_index(rows)
        draft = _claude_draft(rows, frame)
        watcher = claude_watchers(frame)
        if claude_busy(frame):
            return PaneObservation("busy" if caret is not None else "unknown", draft, watcher)
        if draft:
            return PaneObservation("queued", draft, watcher)
        prompt = any(_caret_content(row) is not None for row in rows[-PROMPT_TAIL_LINES:])
        chrome = any(any(marker in row.lower() for marker in _STATUS_LINE_MARKERS)
                     for row in visible[-PROMPT_TAIL_LINES:])
        return PaneObservation("idle" if prompt and chrome else "unknown", watcher=watcher)
    return _observe_codex(rows, visible)


#: The rows that POSITIVELY identify an operator dialog — a pane that will not move until a human answers
#: it — per runtime. Each entry is a set of fragments that must ALL appear on ONE rendered row inside the
#: input-box window (`PROMPT_TAIL_LINES`), never a single fragment over a joined tail: an agent working in
#: this repository writes "esc to cancel" in its own prose constantly, and a one-fragment rule over eight
#: joined rows classified an idle pane whose last answer merely quoted that hint as `dialog` — which
#: `send` refuses, `close` refuses and `pane-guard` reports as blocked, none of which clears by waiting
#: (the `SI-37` incident shape, from the opposite direction). Every row here is measured, not reasoned:
#:  - Claude's folder-trust modal: "Enter to confirm · Esc to cancel" (`fixtures/runtime/claude-dialog.frame`).
#:  - Claude's `AskUserQuestion` dialog: "Enter to select · Tab/Arrow keys to navigate · Esc to cancel",
#:    three fragments on one row for the reason `I-16` records (`session.py`, the `SI-37` amendment).
#:  - Codex's approval prompt: "Press enter to confirm or esc to cancel" (`fixtures/runtime/codex-dialog.frame`).
#:  - Codex's directory-trust screen: "Press enter to continue" (`fixtures/runtime/codex-trust.frame`, from
#:    `coordinator-dispatch/commands.jsonl:22`, where the harness had to answer it with Enter). A worker
#:    parked here is blocked on a human exactly like the others; the review round that introduced measured
#:    rows dropped this one as unmeasured, and it was measured.
#:  - Codex 0.156's folder-trust screen: "enter continue · esc quit" (`fixtures/runtime/codex-trust-0156.frame`, a real
#:    0.156.1 pane). The pt2 harness recorded the same hint on 0.156.0's "Update available" modal (the comment above
#:    `SCREENS` in `fleet/it/runtime-choice-live.py`), but no frame of it is committed, and fleet turns the update check
#:    off on every codex argv (`runtime_launch.CODEX_POLICY`), so that modal is mitigated, not observed (FB-105). The row starts with its
#:    verb like the others, so prose quoting it mid-sentence is not matched. 0.156's approval prompt still ends
#:    "Press enter to confirm or esc to cancel" (`codex-approval-0156.frame`), which the first codex row already reads.
CLAUDE_DIALOG_ROWS = (
    ("enter to confirm", "esc to cancel"),
    ("enter to select", "tab/arrow keys to navigate", "esc to cancel"),
)
CODEX_DIALOG_ROWS = (
    ("press enter to confirm", "esc to cancel"),
    ("press enter to continue",),
    ("enter continue", "esc"),
)


def _dialog_row(runtime: RuntimeName, visible: list[str]) -> bool:
    """A measured dialog row inside the input-box window: it BEGINS with its first fragment and carries
    every other one. The row-start anchor is what separates the TUI's hint line from an agent's prose
    that quotes the same words mid-sentence ("the hint reads Esc to cancel, and Enter to confirm…") —
    every captured hint row starts with its verb, and prose almost never does."""
    rows = CLAUDE_DIALOG_ROWS if runtime == "claude" else CODEX_DIALOG_ROWS
    for row in visible[-PROMPT_TAIL_LINES:]:
        lowered = row.lower()
        for fragments in rows:
            if lowered.startswith(fragments[0]) and all(fragment in lowered for fragment in fragments[1:]):
                return True
    return False


def _claude_draft(rows, frame):
    index = _claude_caret_index(rows)
    draft = _caret_content(rows[index]) if index is not None else None
    if not draft:
        return None
    # The measured multiline editor has a caret row followed by indented
    # continuations, ending at the input border. Never include status chrome.
    content = [draft]
    for row in rows[index + 1:]:
        visible = plain(row)
        if (not visible.startswith('  ') or any(c in visible for c in '─━')
                or visible.lstrip().startswith(('⏵⏵', '? for shortcuts'))):
            break
        content.append(_undim(_cells(row)[2:]))
    draft = '\n'.join(content).strip()
    return None if _is_placeholder(draft) else draft


def _claude_caret_index(rows):
    """The row of the CURRENT input caret, or None.

    The current box is located from its lower border, walking up through any number of indented
    continuation rows (a tall or wrapped draft, v23-f), or by the last caret in a short borderless capture.

    The earlier bounded window was a correction of measured false answers (`FI-24`), and they fail in
    opposite directions:

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
    falling back to an earlier caret (falling back IS the `N4` defect); what an empty box renders (a dim
    suggestion, measured chrome) is filtered by `_caret_content` and `_is_placeholder`, not here.
    """
    border = next((i for i in range(len(rows) - 1, max(-1, len(rows) - PROMPT_TAIL_LINES - 1), -1)
                   if plain(rows[i]).strip().startswith(('────', '━━━━'))), None)
    if border is not None:
        index = border - 1
        while index >= 0 and (not plain(rows[index]).strip() or plain(rows[index]).startswith('  ')):
            index -= 1
        return index if index >= 0 and _caret_content(rows[index]) is not None else None
    for index in range(len(rows) - 1, max(-1, len(rows) - PROMPT_TAIL_LINES - 1), -1):
        if _caret_content(rows[index]) is not None:
            return index
    return None


def _observe_codex(rows: list[str], visible: list[str]) -> PaneObservation:
    # The current input is a bold, non-dim caret above the model/path footer.
    # Submitted prompts use a dim caret. A header alone can be stale scrollback.
    if not re.fullmatch(r"\S+\s+[^·]+ · (?:/|~)[^\n]*", visible[-1]):
        return PaneObservation("unknown")
    prompt = None
    for index in range(max(0, len(rows) - PROMPT_TAIL_LINES), len(rows) - 1):
        if _codex_caret_row(rows[index]):
            prompt = index
    if prompt is None:
        #: FB-27 (codex). An inline draft of 7+ lines puts the caret ABOVE the window while its continuation
        #: rows fill it — measured, `codex-tall-draft.frame`. Walk up from the footer through CONTIGUOUS
        #: continuation rows (two-space indented, or blank — the same rows the content loop below accepts)
        #: and take the BOLD caret directly above them; any other row ends the walk, so scrollback prose
        #: above an empty box is still `unknown`, and a submitted prompt's dim caret never qualifies.
        index = len(rows) - 2
        while index >= 0 and (not plain(rows[index]).strip() or plain(rows[index]).startswith("  ")):
            index -= 1
        if index >= 0 and _codex_caret_row(rows[index]):
            prompt = index
    if prompt is None:
        return PaneObservation("unknown")
    content = [_undim(_trim(_cells(rows[prompt]))[1:])]
    for row in rows[prompt + 1:-1]:
        if plain(row).strip():
            if not plain(row).startswith("  "):
                return PaneObservation("unknown")
            content.append(_undim(_cells(row)))
    draft = "\n".join(content).strip() or None
    spinner = _codex_spinner_above(rows, prompt)
    if spinner == "unknown":
        return PaneObservation("unknown", draft)
    return PaneObservation("busy" if spinner == "busy" else "queued" if draft else "idle", draft)


#: v23-k (FB-113). codex 0.156's live-turn row, measured (`it/fixtures/runtime/codex-busy-bgterm-0156.frame`,
#: `codex-waiting-bgterm-0156.frame`): the spinner glyph, a status, the elapsed time and the interrupt hint in one paren
#: group — `• Working (8s • esc to interrupt)`, `◦ Waiting for background terminal (35s • esc to interrupt)` — then, while
#: an exec session is open (every tool turn: even a foreground command runs as one), ` · 1 background terminal running ·
#: /ps to view…`, cut with `…` at the pane edge. Matched from the row START and anchored on the ELAPSED TIME in the paren,
#: so prose quoting the hint is not a spinner; the status before it is any text (codex writes reasoning titles there,
#: parentheses included — RV-21), and the tail after it is allowed, never required.
_CODEX_ELAPSED = r"\((?:\d+h )?(?:\d+m )?\d+s • esc to interrupt\)"
#: RV-29: the pane-edge cut can also land just after the closed paren (`…)…`, `…) …`, `…) ·…`); the elapsed time is whole.
_CODEX_SPINNER = re.compile(r"[◦•] \S.*" + _CODEX_ELAPSED + r"(?: · .*| ?·?…)?")
#: RV-21. Fleet now starts panes 200 columns wide, but existing and externally resized 80-column panes can still
#: cut the row with `…` at the edge. A long
#: status pushes the cut into the paren group: a paren that opens on a digit and never closes before the `…` is the elapsed
#: time cut short, and is still a turn.
_CODEX_SPINNER_CUT = re.compile(r"[◦•] \S.*\(\d[^()]*…")


def _codex_spinner_above(rows: list[str], prompt: int) -> Optional[str]:
    """`"busy"` when the current input sits under codex's live-turn row, `"unknown"` when the row above it is cut before
    anything could prove or rule out a turn, else None. Walks UP from the caret over blank rows and INDENTED detail rows —
    `  └ sleep 41` under "Waiting for background terminal" is one — and asks only of the first other row. Any other
    unindented row (the agent's answer, a finished `• Ran …`) ends the walk, so a spinner in scrollback is not a turn.
    Bounded by the input window, like every other codex predicate.

    The `"unknown"` answer is the fail-closed one (RV-21): a glyph row cut with `…` before any elapsed time may be a live
    turn whose status was too long for the pane, and reading it idle would be `0 safe` for a busy worker. In every 0.156
    frame captured for this change (the §OR frames, the pilot's) codex WRAPS an unindented transcript row and cuts only
    indented detail rows with `…`, so a finished answer is not expected to end this way; if one does, the cost is a 14."""
    for index in range(prompt - 1, max(-1, prompt - 1 - PROMPT_TAIL_LINES), -1):
        text = plain(rows[index])
        if not text.strip() or text.startswith("  "):
            continue
        row = text.strip()
        if _CODEX_SPINNER.fullmatch(row) or _CODEX_SPINNER_CUT.fullmatch(row):
            return "busy"
        if row.startswith(("• ", "◦ ")) and row.endswith("…"):
            return "unknown"
        return None
    return None


def _codex_caret_row(row: str) -> bool:
    cells = _trim(_cells(row))
    return bool(cells and cells[0] == ("›", False) and re.match(r"\s*\x1b\[(?:0;)?1m›", row))

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


#: What an EMPTY input box renders as PLAIN text: TUI chrome, matched as the WHOLE box, exactly, and nothing else.
#:
#: D-85. This was a regex list of suggestion shapes (`^try "`, `^ask\b`, `^new task?`, ...) used as a fallback
#: for a capture with no SGR, on the theory that such a capture came from a terminal that stripped attributes.
#: Measured false: real `capture-pane -e` frames of Claude Code often carry NO escape at all
#: (`claude-multiline.frame`, 2.1.268; `claude-queued-behind-turn-282.frame` and `claude-after-busy-enter-282.frame`,
#: 2.1.282), and fleet always captures with `-e`. On those frames a REAL draft whose first line was
#: "Ask him first:" or `Try "pytest -k foo" next` read as an empty box: pane-guard 0 or 11, and `send` typed onto
#: it. A model-generated suggestion is SGR-dim (`_undim` drops it); plain text in the box is somebody's draft.
#: The cost of dropping the fallback is the safe direction: an old-style plain suggestion reads `10`, a refusal.
#:
#: Only chrome MEASURED on a real frame belongs here: 2.1.282 draws "Press up to edit queued messages" in the
#: box while a message waits behind the turn (`claude-after-busy-enter-282.frame`).
_EMPTY_BOX_CHROME = (
    re.compile(r"press up to edit queued messages", re.I),
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
#:
#: **Amendment, `I-16`: that claim is measured FALSE for the `AskUserQuestion` selection dialog.** It is
#: true only for a modal whose selected row renders one of `_CARET`'s characters — the trust modal's
#: `> 1. Yes, I trust this folder` does. `AskUserQuestion` draws its options as plain numbered rows with no
#: caret glyph at all (see `DIALOG_PANE` / `test_pane_guard_does_not_call_a_blocked_question_dialog_safe`,
#: `tests/test_cli.py`), so `unsubmitted` finds no caret, returns `None`, and the pane falls through both
#: `busy` and `unsubmitted` to `0 safe` — the same code an idle worker gets, for a worker blocked on an
#: unanswered question. "Detects the modal's selected line" was never a property of every modal; it was a
#: property of every modal measured *so far*, and this is the modal that was not. `pane-guard`'s `15`
#: (`cli.PANE_AWAITING_OPERATOR`) exists to answer for the shape this paragraph could not; the dialog's
#: rows are `CLAUDE_DIALOG_ROWS` above, the one dialog predicate `SessionLayer.asking` delegates to.
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
      intensity character keeps it. The attribute alone decides (D-85 retired the `AC-6` text fallback:
      real captures with no SGR at all are common, and there it hid real drafts); the suggestion is
      model-generated prose, so no list of texts could ever have matched it.
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
    """Whether the WHOLE box content is measured empty-box chrome (`_EMPTY_BOX_CHROME`), whatever the SGR."""
    return any(pattern.fullmatch(content.strip()) for pattern in _EMPTY_BOX_CHROME)


def claude_unsubmitted(pane_text: str) -> Optional[str]:
    """The complete current draft, including continuation rows inside the input box."""
    return _claude_draft(_rendered(pane_text), pane_text)


def annotate_placeholders(frame: str) -> str:
    """Mark the current box when it holds only a dim suggestion or measured empty-box chrome."""
    annotated = []
    rows = frame.splitlines(keepends=True)
    rendered_count = len(_rendered(frame))
    current = _claude_caret_index(_rendered(frame))
    for index in range(max(0, rendered_count - PROMPT_TAIL_LINES), rendered_count):
        if _codex_caret_row(rows[index]):
            current = index
    for index, row in enumerate(rows):
        if index != current:
            annotated.append(row)
            continue
        cells = _trim(_cells(row))
        while cells and cells[0][0] in _GUTTER:
            cells = _trim(cells[1:])
        if cells and cells[0][0] in ('❯', '›'):
            body = _trim(cells[1:])
            if body and ((any(dim and not char.isspace() for char, dim in body) and not _undim(body))
                         or _is_placeholder(_caret_content(row) or '')):
                row = '[placeholder] ' + row
        annotated.append(row)
    return ''.join(annotated)


def claude_busy(pane_text: str) -> bool:
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


def claude_watchers(pane_text: str) -> str:
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

# --- paste placeholders (FB-27) ----------------------------------------------------------------------
#: What each TUI draws INSTEAD of a large bracketed paste. Measured on Claude Code 2.1.281 and codex 0.156.1
#: (w1sendrecords instant, `evidence/02-rca/*/summary.tsv`), through fleet's own `send_literal`:
#:  - Claude Code: a paste of 4+ lines, or of more than ~800 characters, renders as `[Pasted text #N +M lines]`
#:    where M is the number of NEWLINES in the paste (a 5-line message ending in a newline reads `+5 lines`)
#:    and the ` +M lines` suffix is absent when there is no newline; N is a per-session paste counter.
#:  - codex: a paste of more than ~1000 characters renders as `[Pasted Content C chars]`, C counted in
#:    characters (a 1014-char non-ASCII message, 1516 bytes, read `1014 chars`). Its line count is not shown.
#: Below the thresholds both TUIs draw the text itself and `observe` returns it as the draft.
#:
#: The placeholder is the TUI's own count-summary of the paste it HOLDS, so a send can confirm its message
#: against it — weaker than reading the text back, and recorded as such (`messaging.SendRecord.confirmation`).
#: Nothing here decides thresholds: a placeholder is recognised wherever it appears, and a draft that is neither
#: the text nor a count-consistent placeholder is never submitted.
_CLAUDE_PASTE = re.compile(r"^\[Pasted text #(\d+)(?: \+(\d+) lines)?\]$")
_CODEX_PASTE = re.compile(r"^\[Pasted Content (\d+) chars\]$")


@dataclass(frozen=True)
class PastePlaceholder:
    """A TUI's summary of a paste it holds: the counts it states, `None` where it states nothing."""
    runtime: RuntimeName
    newlines: Optional[int] = None
    chars: Optional[int] = None

    def describes(self, text: str) -> bool:
        """Whether every count the TUI stated is the count of `text`. A placeholder stating nothing that
        can be checked (neither) describes nothing: it is never a confirmation."""
        checks = []
        if self.newlines is not None:
            checks.append(self.newlines == text.count("\n"))
        if self.chars is not None:
            checks.append(self.chars == len(text))
        return bool(checks) and all(checks)


def paste_placeholder(runtime: RuntimeName, draft) -> Optional[PastePlaceholder]:
    """The placeholder `draft` is, or None when the draft is text (or nothing)."""
    validate_runtime(runtime)
    if not draft or "\n" in draft.strip():
        return None
    body = " ".join(draft.split())
    if runtime == "claude":
        match = _CLAUDE_PASTE.match(body)
        if match:
            return PastePlaceholder("claude", newlines=int(match.group(2) or 0))
        return None
    match = _CODEX_PASTE.match(body)
    return PastePlaceholder("codex", chars=int(match.group(1))) if match else None


# --- control -----------------------------------------------------------------------------
