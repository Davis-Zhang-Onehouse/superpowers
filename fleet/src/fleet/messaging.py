"""One literal insertion and one observed submission; ambiguous delivery is never retried."""
import time

from fleet.errors import BadInput, FleetError, Refused
from fleet.runtime_config import pane_lock


def validate_message(text):
    if not isinstance(text, str) or not text.strip():
        raise BadInput('A fleet message must contain text')
    if any((ord(c) < 32 and c != '\n') or 127 <= ord(c) <= 159 for c in text):
        raise BadInput('Fleet messages cannot contain terminal control characters')


def send(home, sessions, record, text, *, timeout_s=10.0, clock=time.monotonic,
         sleep=time.sleep, validate=None):
    validate_message(text)
    with pane_lock(home, sessions.socket, record.tmux):
        if validate:
            validate()
        if sessions.observe(record.tmux).state != 'idle':
            raise Refused('Message not sent: the worker must have an observed empty idle input')
        try:
            sessions.send_literal(record.tmux, text)
            deadline = clock() + timeout_s
            while True:
                observation = sessions.observe(record.tmux)
                if observation.state == 'queued' and observation.draft == text.strip():
                    break
                if observation.state not in ('idle', 'queued') or clock() >= deadline:
                    raise FleetError('Delivery uncertain after insertion; inspect the draft before retrying')
                sleep(0.02)
            sessions.submit(record.tmux)
            deadline = clock() + timeout_s
            while True:
                observation = sessions.observe(record.tmux)
                if observation.state in ('busy', 'idle') and not observation.draft:
                    return 'submitted'
                if observation.state in ('unknown', 'dialog') or clock() >= deadline:
                    raise FleetError('Delivery uncertain after Enter; inspect the worker before retrying')
                sleep(0.02)
        except FleetError:
            raise
        except Exception as exc:
            raise FleetError(f'Delivery uncertain; inspect the worker before retrying: {exc}') from exc
