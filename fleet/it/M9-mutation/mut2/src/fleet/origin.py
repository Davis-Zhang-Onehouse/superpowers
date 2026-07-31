"""Who dispatched this instant, and for what.

One file, `<instant>/.fleet/origin.json`, written once by `dispatch` and never again. It answers two
questions a dispatched instant could not previously ask about itself:

  * **which instant is my coordinator** — so `propose` has a destination without being told one; and
  * **which milestone was I dispatched for** — so a report can be joined back to the work it is about.

Why this file exists at all (`SI-27`). `propose --to` defaults to `--instant`, so a worker that did not
name a destination wrote a proposal into *its own* `proposals.json`; `harvest` then applied that proposal
into the worker's own roadmap, killed the session, released the slot and closed the record. Measured: the
coordinator's inbox held **0 pending** and the worker's own held **1**. Nothing errored. The project-level
roadmap simply never learned, and the only trace was inside a folder that had just been closed out.

The old fix would have been a line in a skill — *"always pass `--to <coordinator>`"*. That is a documented
warning where a mechanical fix is available, and it fails exactly when the seed is written by someone who
has not read the warning. Here the destination is a **fact recorded at dispatch by the dispatcher**, so the
worker cannot get it wrong by omission: it does not supply the answer, it reads it.

Absence is meaningful and is NOT an error. An instant created by `fleet init`, or a coordinator working on
its own roadmap, has no origin — `read` returns `None`, and `propose` then keeps its old local behaviour
while SAYING SO in its output. A verb that silently did the local thing is what this module exists to stop;
a verb that refuses would break the single-instant case that legitimately has no coordinator.

There is deliberately no writer but `dispatch` and no mutator at all. The coordinator of an instant is a
historical fact about how it came to exist, and a fact that can be edited is a fact two views can disagree
about.
"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from fleet.atomic import atomic_write
from fleet.errors import BadInput
from fleet.store import SCHEMA_VERSION

#: The filename, beside `roadmap.json` and `proposals.json` in the same private directory.
ORIGIN = "origin.json"


@dataclass(frozen=True)
class Origin:
    """Immutable. `milestone` is optional because a dispatch need not be about a milestone — a coordinator
    or a compaction instant is dispatched for a role, not for a roadmap row."""

    coordinator: str
    dispatched_at: str
    milestone: str = None
    schema_version: int = SCHEMA_VERSION


def path_of(instant: Path) -> Path:
    return Path(instant) / ".fleet" / ORIGIN


def write(instant: Path, origin: Origin) -> Path:
    """Write it once. Refuses to overwrite: a second write would mean an instant changed coordinators, and
    the caller that wants that is a bug rather than a use case."""
    target = path_of(instant)
    if target.exists():
        raise BadInput(
            f"{target} already exists, so this instant already records a coordinator. Refusing to "
            f"overwrite it — an instant's origin is how it came to exist, and rewriting it would make two "
            f"views of the same dispatch disagree.")
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, json.dumps(asdict(origin), indent=2, ensure_ascii=False))
    return target


def read(instant: Path):
    """-> Origin, or None when the instant has no coordinator. `None` is a legitimate answer, not a
    failure; a malformed or wrong-version file IS a failure and is refused rather than treated as absent,
    because "unreadable" and "absent" mean opposite things to `propose`."""
    target = path_of(instant)
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text())
    except (OSError, ValueError) as exc:
        raise BadInput(
            f"{target} exists but could not be read as JSON ({exc}). It is refused rather than treated as "
            f"absent: absent means 'no coordinator, propose locally', and guessing that for a file that IS "
            f"there would send a worker's report into its own folder.") from exc
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise BadInput(
            f"{target} has schema_version={version!r}, this build knows {SCHEMA_VERSION}. Refusing to "
            f"interpret it (FD-1).")
    known = {"coordinator", "dispatched_at", "milestone", "schema_version"}
    unknown = set(data) - known
    if unknown:
        raise BadInput(f"{target} carries unknown key(s) {sorted(unknown)}; refusing to interpret it.")
    if not data.get("coordinator"):
        raise BadInput(f"{target} names no coordinator, which is the one thing it exists to record.")
    return Origin(**data)
