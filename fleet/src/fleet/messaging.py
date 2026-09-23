"""One literal insertion and one observed submission; ambiguous delivery is never retried."""
import time

from fleet.errors import BadInput, FleetError, Refused
from fleet.runtime_config import pane_lock


def validate_message(text):
    if not isinstance(text, str) or not text.strip():
        raise BadInput('A fleet message must contain text')
    if any((ord(c) < 32 and c != '\n') or 127 <= ord(c) <= 159 for c in text):
        raise BadInput('Fleet messages cannot contain terminal control characters')


def not_idle(record) -> Refused:
    """The one refusal for a pane that is not observed idle, raised by the real send and by `send --dry-run`
    alike (RV-24): two copies had already drifted to different words and a different actor."""
    return Refused('Message not sent: the worker must have an observed empty idle input',
                   clears_when=f'`fleet pane-guard --pane {record.tmux}` exits 0 (idle, empty input), '
                               f'then `fleet send` is re-run',
                   clears_who=f'the worker in {record.tmux}, by finishing its turn')


def _squash(text) -> str:
    """The draft as words: a line wider than the input box renders as two rows and `observe` joins them
    with a newline, so a byte-exact comparison never matched a soft-wrapped message and every such send
    ended as "uncertain" with the text left in the box. Whitespace is the only thing the TUI is free to
    rearrange; the words are not."""
    return " ".join(str(text or "").split())


def send(home, sessions, record, text, *, timeout_s=10.0, clock=time.monotonic,
         sleep=time.sleep, validate=None):
    validate_message(text)
    with pane_lock(home, sessions.socket, record.tmux):
        if validate:
            validate()
        if sessions.observe(record.tmux).state != 'idle':
            raise not_idle(record)
        try:
            sessions.send_literal(record.tmux, text)
            deadline = clock() + timeout_s
            while True:
                observation = sessions.observe(record.tmux)
                if observation.state == 'queued' and _squash(observation.draft) == _squash(text):
                    break
                # A TUI redraw can temporarily omit its prompt/footer. Observe
                # through the existing deadline; never insert again or submit
                # until the exact draft is visible.
                if observation.state not in ('idle', 'queued', 'unknown') or clock() >= deadline:
                    raise FleetError('Delivery uncertain after insertion; inspect the draft before retrying')
                sleep(0.02)
            sessions.submit(record.tmux)
            deadline = clock() + timeout_s
            while True:
                observation = sessions.observe(record.tmux)
                if observation.state in ('busy', 'idle') and not observation.draft:
                    return 'submitted'
                if observation.state == 'dialog' or clock() >= deadline:
                    raise FleetError('Delivery uncertain after Enter; inspect the worker before retrying')
                sleep(0.02)
        except FleetError:
            raise
        except Exception as exc:
            raise FleetError(f'Delivery uncertain; inspect the worker before retrying: {exc}') from exc
