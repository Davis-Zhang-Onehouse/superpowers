"""One literal insertion and an observed submission (one retry for a confirmed stuck draft); ambiguous delivery is never retried — and every
attempt that reached the pane is written down (B13)."""
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from fleet.errors import BadInput, FleetError, Refused
from fleet.runtime import paste_placeholder
from fleet.runtime_config import pane_lock

#: `.fleet/sends.jsonl` in the WORKER's instant: one JSON object per line per attempt that touched the pane.
SENDS = "sends.jsonl"
SEND_SCHEMA_VERSION = 1
#: The outcomes a send can end in once it has pasted. A refusal BEFORE the paste is not one of these: it
#: wrote nothing into the pane, and the record is a record of what was written there.
SUBMITTED = "submitted"
QUEUED_BEHIND_TURN = "queued-behind-turn"
SUBMITTED_MID_TURN = "submitted-mid-turn"
INSERTED_NOT_SUBMITTED = "inserted-not-submitted"
UNCERTAIN_AFTER_INSERTION = "uncertain-after-insertion"
UNCERTAIN_AFTER_ENTER = "uncertain-after-enter"
UNCERTAIN = "uncertain"
#: HOW the draft was confirmed before Enter: the TEXT was read back (`draft`), or the TUI's count-summary
#: placeholder agreed with the message (`placeholder`, FB-27) — a weaker confirmation, and said so.
CONFIRMED_BY_DRAFT = "draft"
CONFIRMED_BY_PLACEHOLDER = "placeholder"
#: RV-47. Claude Code's single-line placeholder `[Pasted text #N]` states NO length — only that a paste
#: with no newline sits in the box, which any single-line message of 800+ characters would also produce.
#: It is accepted (the box was observed empty before this one paste) and recorded as the weakest kind.
CONFIRMED_BY_PLACEHOLDER_UNCOUNTED = "placeholder-uncounted"
#: FB-134. Claude Code's input box shows only its LAST rows once a message is taller than the box (measured on
#: 2.1.282 at 80 columns: every row at 24 lines, 5 rows at 20, 3 at 16 and 12), and no cursor key scrolls the
#: head back into view. The verb then read a strict suffix of its own paste, never confirmed it and never
#: pressed Enter, and every 380–510-char coordinator send to an 80-column worker ended uncertain. A tail that
#: ends at the message's last word and fills a scrolled box confirms, as its own weaker kind.
CONFIRMED_BY_DRAFT_TAIL = "draft-tail"
#: The smallest scrolled box measured. Fewer rows is a box that could have shown more, not a scrolled one.
TAIL_MIN_ROWS = 3
#: RV-9. How long a tail must hold still before Enter: over three times the 22-32 ms a measured draft took to render
#: after the paste. Two captures a few ms apart show the same frame and could not see a paste still arriving.
TAIL_SETTLE_S = 0.1


def validate_message(text):
    if not isinstance(text, str) or not text.strip():
        raise BadInput('A fleet message must contain text')
    if any((ord(c) < 32 and c != '\n') or 127 <= ord(c) <= 159 for c in text):
        raise BadInput('Fleet messages cannot contain terminal control characters')


def not_idle(record) -> Refused:
    """The one refusal for a pane without a known empty idle or busy input, raised by real and dry-run
    alike (RV-24): two copies had already drifted to different words and a different actor."""
    return Refused('Message not sent: the worker must have an observed empty input, idle or mid-turn; queued text, an operator dialog and an unreadable pane are refused',
                   clears_when=f'`fleet pane-guard --pane {record.tmux}` exits 0 (idle) or 11 (mid-turn), with an empty input, '
                               f'then `fleet send` is re-run',
                   clears_who=f'the owner of {record.tmux}, by resolving its draft or dialog or restoring a readable pane')


def _squash(text) -> str:
    """The draft as words: a line wider than the input box renders as two rows and `observe` joins them
    with a newline, so a byte-exact comparison never matched a soft-wrapped message and every such send
    ended as "uncertain" with the text left in the box. Whitespace is the only thing the TUI is free to
    rearrange; the words are not."""
    return " ".join(str(text or "").split())


def confirms(runtime, draft, text) -> Optional[str]:
    """How the observed `draft` confirms that `text` is what the box holds, or None when it does not.

    Two shapes confirm (FB-27). The draft IS the text, modulo the whitespace a TUI rearranges — the strong
    one. Or the draft is the TUI's paste PLACEHOLDER and every count it states is the count of `text`:
    Claude Code shows `[Pasted text #N +M lines]` for 4+ lines (M = newlines), codex `[Pasted Content C
    chars]` above ~1000 characters — measured, `runtime.paste_placeholder`. A placeholder whose counts
    disagree is somebody else's paste, or a concatenation, and confirms nothing.
    """
    if draft and _squash(draft) == _squash(text):
        return CONFIRMED_BY_DRAFT
    if runtime == "claude" and _is_scrolled_tail(draft, text):
        return CONFIRMED_BY_DRAFT_TAIL
    placeholder = paste_placeholder(runtime, draft)
    if placeholder is not None and placeholder.describes(text):
        if placeholder.chars is None and not placeholder.newlines:
            return CONFIRMED_BY_PLACEHOLDER_UNCOUNTED
        return CONFIRMED_BY_PLACEHOLDER
    return None


def _is_scrolled_tail(draft, text) -> bool:
    """Whether `draft` is what a scrolled claude box shows of `text`: at least `TAIL_MIN_ROWS` rows whose words
    are the message's LAST words, starting at a word boundary (claude wraps at words, so a scrolled view begins
    on one). Not a prefix: a paste still arriving shows its head, and a view that ends before our last word is
    not ours to submit. A VISIBLE draft longer than the message is refused. What the box hides above the view is not
    seen: that it holds exactly our head rests on the box being empty at admission and on one paste under
    `pane_lock` — `send` never inserts twice — which is why this kind is recorded apart from `draft`."""
    if not draft or draft.count("\n") + 1 < TAIL_MIN_ROWS:
        return False
    seen, whole = _squash(draft), _squash(text)
    #: A prefilter only: the row check below implies a strict, word-aligned suffix. It keeps a draft that is not one
    #: from paying for the wrap on every poll.
    if not (0 < len(seen) < len(whole) and whole.endswith(seen) and whole[-len(seen) - 1] == " "):
        return False
    #: RV-8. A suffix is not yet a SCROLLED view: a box that lost its head and re-wrapped what was left is a suffix too,
    #: and Enter would submit it truncated. A scrolled view shows the message's own last rows, so the visible rows
    #: must be exactly the last rows of the whole message wrapped at one width. Claude Code wraps greedily at word
    #: boundaries: every real scrolled frame re-wraps this way (80 columns -> width 76). Only a head lost in WHOLE
    #: rows still passes, and nothing in a frame can tell that from a scroll.
    rows = [" ".join(row.split()) for row in draft.split("\n")]
    #: RV-24. Each hard line wraps on its own (measured: a tall 2-line box shows its last line's rows), so the
    #: message's rows are its lines' rows, in order. A width past the longest line wraps nothing, so no wider one
    #: can draw anything new.
    lines = [line.split() for line in text.strip().split("\n")]
    longest = max(len(" ".join(line)) for line in lines)
    return any(_rows(lines, width)[-len(rows):] == rows for width in range(max(map(len, rows)), longest + 2))


def _rows(lines, width) -> list:
    """Every row of a message whose hard `lines` are each wrapped at `width`."""
    return [row for words in lines for row in _wrap(words, width)]


def _wrap(words, width) -> list:
    """`words` wrapped greedily at `width`, the way Claude Code draws a paste in its box."""
    rows, row = [], ""
    for word in words:
        if row and len(row) + 1 + len(word) > width:
            rows.append(row)
            row = word
        else:
            row = f"{row} {word}" if row else word
    return rows + [row]


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SendRecord:
    """What an actor wrote into a worker's pane, and what became of it. B13: before this, `fleet send`
    wrote nothing down, so "who wrote into this pane" and "claimed sends vs received prompts" had no subject
    to join. The message itself is identified by digest and located by path; its first line is kept so a
    reader can tell records apart without opening files."""
    at: str
    by: str
    todo_id: str
    tmux: str
    runtime: str
    message_file: str
    sha256: str
    chars: int
    lines: int
    head: str
    outcome: str
    confirmation: str
    schema_version: int = SEND_SCHEMA_VERSION


def sends_path(instant) -> Path:
    return Path(instant) / ".fleet" / SENDS


def line_count(text: str) -> int:
    """Newline-separated lines — the quantity the placeholder confirms (RV-46). Not `str.splitlines`, which
    also splits on CR, VT, FF and U+2028 and would record a count the TUI never showed."""
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def head_of(text: str, width: int = 80) -> str:
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first if len(first) <= width else first[:width - 1] + "…"


def record_send(instant, record: SendRecord) -> Path:
    """Append `record` to the worker's send log. Append-only: a send is an event, and two sends are two."""
    target = sends_path(instant)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
    return target


def read_sends(instant) -> list:
    """Every recorded send, oldest first; `[]` when nothing was recorded. A malformed line is REFUSED, not
    skipped, for `seedcheck.read_delivery`'s reason: 'unreadable' and 'absent' mean opposite things."""
    target = sends_path(instant)
    reroute = dict(clears_when="the line is repaired or removed", clears_who="the coordinator")
    if not target.exists():
        return []
    if not target.is_file():
        #: Something is there that is not a log. Absent means "nobody recorded a send"; this is not that.
        raise BadInput(f"{target} exists but is not a file; refusing to interpret the send log.",
                       clears_when="the entry is removed", clears_who="the coordinator")
    #: RV-39 (an FB-74 member). Bytes, decoded PER LINE under the same refusal: a torn append that split a
    #: multibyte sequence raised UnicodeDecodeError past `brief`'s `except BadInput` and took the whole
    #: briefing down, and so did an OSError from an unreadable log.
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise BadInput(f"{target} could not be read ({exc.strerror or exc}); refusing to interpret the send log.",
                       **reroute) from exc
    rows = []
    for number, chunk in enumerate(raw.splitlines(), 1):
        if not chunk.strip():
            continue
        try:
            data = json.loads(chunk.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise BadInput(f"{target} line {number} is not UTF-8 JSON ({exc}); refusing to interpret the send log.",
                           **reroute) from exc
        if not isinstance(data, dict) or data.get("schema_version") != SEND_SCHEMA_VERSION:
            raise BadInput(f"{target} line {number} has schema_version={data.get('schema_version') if isinstance(data, dict) else None!r}, "
                           f"this build knows {SEND_SCHEMA_VERSION}. Refusing to interpret it (FD-1).",
                           clears_when="the line is repaired or removed", clears_who="the coordinator")
        known = set(SendRecord.__dataclass_fields__)
        if set(data) - known or known - set(data):
            raise BadInput(f"{target} line {number} does not carry exactly the send-record keys; refusing to interpret it.",
                           **reroute)
        #: The TYPES too: a line with the right keys and `"sha256": 5` passed here and crashed `brief` at
        #: `sha256[:8]`. `bool` is an int to Python and is refused for the int fields on purpose.
        for name, spec in SendRecord.__dataclass_fields__.items():
            value = data[name]
            wanted = spec.type if isinstance(spec.type, type) else {"str": str, "int": int}[spec.type]
            if not isinstance(value, wanted) or isinstance(value, bool):
                raise BadInput(f"{target} line {number} field {name!r} is {type(value).__name__}, not "
                               f"{wanted.__name__}; refusing to interpret it.", **reroute)
        rows.append(SendRecord(**data))
    return rows


def send(home, sessions, record, text, *, timeout_s=10.0, clock=time.monotonic,
         sleep=time.sleep, validate=None, recorder=None, unrecorded=None):
    """-> `(outcome, confirmation)`; `outcome` is `SUBMITTED` on success, and every other outcome is raised
    as the `FleetError` it always was. `recorder(outcome, confirmation)` is called ONCE for every attempt
    that reached the pane, success or not, before the error propagates — a send that pasted and then could
    not confirm is exactly the record a later reader needs.

    **The delivery verdict always wins over the recording** (RV-38). A recorder that raises — an unwritable
    `.fleet`, a full disk, an instant renamed mid-send — must not turn a SUBMITTED message into a traceback:
    the operator would read a failure for a delivered message and retry, and the retry is the duplicate
    send FI-9/FI-15 exist to prevent. So the recorder's exception is handed to `unrecorded(exc)` and the
    verdict is returned or raised unchanged. With no `unrecorded` hook the failure is not swallowed: it is
    raised as a FleetError that NAMES the verdict it decorates, so nothing reads it as "not delivered"."""
    validate_message(text)
    runtime = getattr(sessions, "runtime", "claude")
    with pane_lock(home, sessions.socket, record.tmux):
        if validate:
            validate()
        before = sessions.observe(record.tmux)
        if before.state not in ('idle', 'busy') or before.draft:
            raise not_idle(record)
        outcome, confirmation = UNCERTAIN, ""
        failed_record = None
        try:
            sessions.send_literal(record.tmux, text)
            deadline = clock() + timeout_s
            while True:
                observation = sessions.observe(record.tmux)
                if observation.state in ('queued', 'busy'):
                    confirmation = confirms(runtime, observation.draft, text) or ""
                    if confirmation == CONFIRMED_BY_DRAFT_TAIL:
                        #: FB-134. The tail cannot show the head, so it must hold still: a frame taken
                        #: TAIL_SETTLE_S later has to show the SAME tail before any Enter. An exact draft needs no
                        #: second frame — a paste still arriving is a prefix, which never equals the message.
                        sleep(TAIL_SETTLE_S)
                        again = sessions.observe(record.tmux)
                        if again.state not in ('queued', 'busy') or again.draft != observation.draft:
                            confirmation = ""
                    if confirmation:
                        break
                # A TUI redraw can temporarily omit its prompt/footer, and a BUSY pane can still show its
                # empty or partly drawn box right after the paste (S5 RV-F1). Observe through the existing
                # deadline; only a dialog fails early. Never insert again or submit until the exact draft
                # is visible.
                if observation.state == 'dialog' or clock() >= deadline:
                    outcome = UNCERTAIN_AFTER_INSERTION
                    raise FleetError('Delivery uncertain after insertion; inspect the draft before retrying')
                sleep(0.02)
            sessions.submit(record.tmux)
            deadline = clock() + timeout_s
            retried = False
            #: RV-23. The outcome LABEL (queued-behind-turn / submitted-mid-turn vs submitted) is the pane's
            #: state at ADMISSION (`before`), not at Enter: a turn that ends, or starts, in the gap between the
            #: two is labelled by what was observed when the send was admitted. Delivery itself is decided
            #: below from the box emptying; only the label can lag. Re-observing before Enter would move the
            #: gap, not close it.
            while True:
                observation = sessions.observe(record.tmux)
                if observation.state in ('busy', 'idle') and not observation.draft:
                    outcome = (QUEUED_BEHIND_TURN if runtime == 'claude' else SUBMITTED_MID_TURN) if before.state == 'busy' else SUBMITTED
                    break
                if observation.state == 'dialog':
                    outcome = UNCERTAIN_AFTER_ENTER
                    raise FleetError('Delivery uncertain after Enter; inspect the worker before retrying')
                if clock() >= deadline:
                    if observation.draft and confirms(runtime, observation.draft, text):
                        if not retried:
                            # The first Enter may have landed during the wait. Check the pane
                            # again immediately before retrying; a dialog or another draft
                            # must never receive our Enter.
                            latest = sessions.observe(record.tmux)
                            if latest.state in ('busy', 'idle') and not latest.draft:
                                outcome = (QUEUED_BEHIND_TURN if runtime == 'claude' else SUBMITTED_MID_TURN) if before.state == 'busy' else SUBMITTED
                                break
                            kind = confirms(runtime, latest.draft, text)
                            #: RV-11. A tail cannot show the head, so the retry needs the SAME tail twice, as the
                            #: first Enter did; two different tails that each confirm are not that evidence.
                            if (latest.state not in ('queued', 'busy') or not kind
                                    or (kind == CONFIRMED_BY_DRAFT_TAIL and latest.draft != observation.draft)):
                                outcome = UNCERTAIN_AFTER_ENTER
                                raise FleetError('Delivery uncertain after Enter; retry refused because the input changed')
                            sessions.submit(record.tmux)
                            retried = True
                            deadline = clock() + timeout_s
                            continue
                        outcome = INSERTED_NOT_SUBMITTED
                        raise FleetError('Message inserted-not-submitted after two Enter attempts; the input box still holds it')
                    outcome = UNCERTAIN_AFTER_ENTER
                    raise FleetError('Delivery uncertain after Enter; inspect the worker before retrying')
                sleep(0.02)
        except FleetError:
            raise
        except Exception as exc:
            raise FleetError(f'Delivery uncertain; inspect the worker before retrying: {exc}') from exc
        finally:
            if recorder is not None:
                try:
                    recorder(outcome, confirmation)
                except Exception as exc:          # the verdict wins; see the docstring
                    failed_record = exc
                    if unrecorded is not None:
                        unrecorded(exc)
    if failed_record is not None and unrecorded is None:
        raise FleetError(f'Message {outcome} (confirmed by {confirmation or "nothing"}) but NOT recorded: '
                         f'{failed_record}') from failed_record
    return outcome, confirmation
