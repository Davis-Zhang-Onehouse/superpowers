"""Strict fleet selection and stable advisory locks for admissions and pane writes."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import time

from fleet.atomic import atomic_write
from fleet.errors import BadInput, Refused
from fleet.runtime import RuntimeName, validate_runtime


def read_runtime(home: Path) -> tuple[RuntimeName, str]:
    path = Path(home) / 'runtime.json'
    try:
        raw = path.read_text()
    except FileNotFoundError:
        if path.is_symlink():
            raise BadInput(f'Broken runtime configuration link at {path}')
        return 'claude', 'legacy-default'
    except (OSError, UnicodeError) as exc:
        raise BadInput(f'Cannot read {path}: {exc}') from exc
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise BadInput(f'Invalid runtime JSON at {path}: {exc}') from exc
    if (not isinstance(body, dict) or set(body) != {'schema_version', 'runtime'}
            or type(body['schema_version']) is not int or body['schema_version'] != 1):
        raise BadInput(f'Unsupported runtime configuration at {path}')
    return validate_runtime(body['runtime']), 'saved'


def write_runtime(home: Path, name: RuntimeName) -> None:
    """Caller must hold admission_lock; reads never initialize this file."""
    atomic_write(Path(home) / 'runtime.json', json.dumps({
        'schema_version': 1, 'runtime': validate_runtime(name),
    }, indent=2) + '\n')


@contextmanager
def _lock(path: Path, timeout_s: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as handle:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise Refused(f'Another operation holds {path}; retry when it finishes')
                time.sleep(0.02)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def admission_lock(home: Path, timeout_s=5.0):
    return _lock(Path(home) / '.runtime-admission.lock', timeout_s)


def pane_lock(home: Path, socket: str, session: str, timeout_s=5.0):
    address = json.dumps([socket, session], ensure_ascii=False).encode('utf-8')
    digest = hashlib.sha256(address).hexdigest()
    return _lock(Path(home) / 'pane-locks' / (digest + '.lock'), timeout_s)
