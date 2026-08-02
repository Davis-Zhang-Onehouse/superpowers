"""THE atomic write. One implementation, used by every persistence site in the package.

Why this module exists at all is `FI-20`, and it is the build's sharpest self-indictment. Atomic write is
the most safety-critical primitive here, and it had been implemented **eight** times — in `store` (twice),
`pool`, `workspace`, `review`, `roadmap` and `harvest` (twice) — by seven different implementers, each
reproducing the same flaw:

    tmp = path.with_suffix(".json.tmp")     # DERIVED FROM THE TARGET
    tmp.write_text(...)
    tmp.replace(path)

The `tmp`-then-`replace` idiom is correct. *Deriving the tmp name from the target* is what makes it unsafe:
two concurrent writers to one logical file share one tmp path, so A writes tmp, B overwrites tmp, A
`replace`s (publishing B's bytes or a truncated prefix of them) and B `replace`s (finding the tmp gone and
raising `FileNotFoundError` out of the middle of a dispatch transaction). Measured, not theorised: §E of the
integration plan ran nine real-concurrency cases against real processes and this single defect accounted for
five of the eight failures, most at a rate of 100%.

Three properties are the contract:

1. **The tmp name is unique per writer, never derived from the target.** pid ∧ monotonic ns ∧ random bits:
   the pid separates processes, the monotonic clock separates two writes inside one process, and the random
   bits separate two processes that were forked at the same instant on the same pid namespace. Any one of
   the three alone has a collision story; the three together do not.
2. **It is a leaf.** Nothing in the package is imported here, so every layer — including `store` and `pool`,
   which are leaves themselves — can use it without an import edge. `test_structure` treats `atomic` the
   same way it treats `errors`: a shared zero-dependency primitive, not a dependency.
3. **A failed write publishes nothing and leaves no litter.** The tmp is removed on any exception, so a
   crash mid-write cannot leave a `*.tmp` behind for a later reader to trip over, and `os.replace` is never
   reached with a partial file.

The tmp lives in the target's own directory, because `os.replace` is only atomic within one filesystem.
It is named with a leading dot and a `.tmp` tail so that no consumer's glob (`*.json`, `*.tsv`) can see it.

**`atomic_write` is not enough on its own, and the difference is its own class of defect.** It makes one
publish indivisible; it cannot make a *read-modify-write* indivisible. Two writers that each read a
registry, each append their own entry and each publish leave **one** entry, with no torn byte anywhere to
show for it — which is precisely what §E's E7 measured (two concurrent dispatches for different bases, 20
of 20 iterations ending with one base watched and the other silently unwatched). So this module ships the
second primitive too, `atomic_update`, and the two are here together because a caller that reaches for the
wrong one has a lost update rather than a visible failure.
"""
import os
import random
import time
from pathlib import Path
from contextlib import contextmanager

__all__ = ["atomic_symlink", "atomic_write", "atomic_update", "held_for_update", "tmp_name"]

#: The tail every staged file carries. Named here so the structural test and the writer agree by
#: construction rather than by two people remembering the same string.
TMP_SUFFIX = ".tmp"

#: How long `atomic_update` waits for another updater of the same file before it treats the holder as
#: dead. These updates are microseconds of work, so a lock held for seconds is a crashed process, not a
#: slow one — and a lock that is never broken turns one dead writer into a permanently wedged registry.
LOCK_TIMEOUT_S = 10.0
_LOCK_POLL_S = 0.005


def tmp_name(name: str) -> str:
    """A staging name no other writer of the same target can produce.

    Unique per writer, and deliberately NOT a function of the target alone — that is the whole defect this
    module replaces. `monotonic_ns` is not comparable across hosts and does not need to be: this is an
    identity, never an ordering.
    """
    unique = f"{os.getpid()}.{time.monotonic_ns()}.{random.getrandbits(48):012x}"
    return f".{name}.{unique}{TMP_SUFFIX}"


def atomic_write(path, text: str, encoding: str = "utf-8") -> Path:
    """Publish `text` at `path` in one indivisible step, safely under concurrent writers.

    A reader either sees the previous contents or these; never a prefix, never a mixture of two writers'
    bytes, and never a missing file. Returns `path`, so a caller can keep writing in one expression.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / tmp_name(path.name)
    try:
        with open(tmp, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())      # the bytes are on disk BEFORE the name points at them
        os.replace(tmp, path)              # atomic within the filesystem: the rename IS the publish
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass                           # a staging file that is already gone needs no removing
        raise
    return path


def atomic_symlink(target, link) -> Path:
    """Publish `link` as a symlink to `target` in one indivisible step.

    The sibling of `atomic_write`, for the one thing that primitive cannot carry. `atomic_write` publishes
    TEXT at a path; a pointer that selects which tree is live is a symlink, and there is no way to move a
    symlink in place — `os.symlink` refuses an existing name, so the obvious `unlink` then `symlink` leaves
    a window in which the link does not exist at all. For a pointer that every shell's `PATH` resolves
    through, that window is the outage.

    It lives HERE, beside `atomic_write`, rather than in the module that needs it, because "there is
    exactly one implementation of atomic publish in this package" is the `FI-20` invariant, and a second
    publish sitting in a caller makes that invariant nearly-true instead of true. `test_structure`'s
    ninth-copy guard skips this module for precisely that reason: the exemption is for the primitive, not
    for whoever fancies writing one.

    The staging name is `tmp_name`, never derived from the link — same rule and the same reason as
    `atomic_write`. A pid-derived staging name would be shared by every writer inside one process, so two
    threads flipping at once would race on one path: the first `os.replace` publishes the second's target,
    and the second raises `FileNotFoundError` finding its staging gone.

    A reader resolving `link` sees the old target or the new one, never a missing path. Returns `link`.
    """
    link = Path(link)
    link.parent.mkdir(parents=True, exist_ok=True)
    staging = link.parent / tmp_name(link.name)
    try:
        os.symlink(str(target), staging)
        os.replace(staging, link)          # atomic rename, even over an existing symlink
    except BaseException:
        try:
            os.unlink(staging)
        except OSError:
            pass                           # a staging link that is already gone needs no removing
        raise
    return link


def _lock_dir(path: Path) -> Path:
    return path.parent / f".{path.name}.lock"


def _acquire(lock: Path, timeout_s: float) -> None:
    """`mkdir` IS the lock, for the same reason it is in `pool`: one atomic syscall on every POSIX
    filesystem, so two updaters racing for one file cannot both win and there is no check-then-create
    window to lose. A holder older than the timeout is treated as dead and broken exactly once — a lock
    nobody may break converts one crashed writer into a registry no process can ever update again.
    """
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    broken = False
    while True:
        try:
            lock.mkdir()
            return
        except FileExistsError:
            pass
        if time.monotonic() >= deadline:
            age = _age_of(lock)
            if broken or age is None or age < timeout_s:
                raise TimeoutError(
                    f"waited {timeout_s}s for another process to finish updating {lock.parent}; the "
                    f"lock {lock} is held and is {age if age is not None else 'unknown'}s old. This is "
                    "reported rather than forced: breaking a lock a live writer holds is the lost update "
                    "the lock exists to prevent.")
            _break(lock)                   # the holder is dead: its lock is litter, not a claim
            broken, deadline = True, time.monotonic() + timeout_s
        time.sleep(_LOCK_POLL_S)


def _age_of(lock: Path):
    try:
        return max(0.0, time.time() - lock.stat().st_mtime)
    except OSError:
        return None                        # already gone — the next mkdir will win it


def _break(lock: Path) -> None:
    try:
        lock.rmdir()
    except OSError:
        pass                               # somebody else broke or released it first; either is fine


def _release(lock: Path) -> None:
    _break(lock)


@contextmanager
def held_for_update(path, timeout_s: float = LOCK_TIMEOUT_S):
    """Hold the update lock for `path` across a read-modify-write the caller performs itself.

    `atomic_update` is the right tool when the whole mutation fits in one callback over the file's TEXT.
    Some read-modify-writes do not: `roadmap` and `review` load a registry, validate against its current
    contents, raise typed refusals, and only then write — and threading that through a text callback would
    move validation logic into a lambda for no gain. This exposes the SAME lock so the sequence becomes one
    step, with no second mechanism to reason about (`FI-30c`).

    The publish inside still goes through `atomic_write`, so a READER never takes this lock and never
    blocks: it sees either the previous contents or the new ones. Only writers serialise, which is what
    keeps a registry read on the hot path free — the same property `atomic_update` documents.

    Measured, not assumed: 6 concurrent writers on one instant left **1 of 6** entries in every one of 8
    iterations before this, on both `roadmap` and `review`. That is last-writer-wins, and `FI-30c` had it
    right; what was missing was a case that observed it.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_dir(path)
    _acquire(lock, timeout_s)
    try:
        yield path
    finally:
        _release(lock)


def atomic_update(path, mutate, timeout_s: float = LOCK_TIMEOUT_S, encoding: str = "utf-8"):
    """Read-modify-write one file as one indivisible step. Returns whatever `mutate` returned.

    `mutate` is called with the file's current text, or `None` when the file does not exist yet, and
    returns `(new_text, result)`. Returning `None` for `new_text` means "nothing to publish" — the file is
    left exactly as it was, which is how an idempotent update reports that it already held the answer.

    The publish still goes through `atomic_write`, so a *reader* never needs the lock and never blocks: it
    sees either the previous contents or the new ones. The lock serialises writers against each other and
    nothing else, which is what keeps a registry read on the hot path free.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_dir(path)
    _acquire(lock, timeout_s)
    try:
        try:
            current = path.read_text(encoding=encoding)
        except FileNotFoundError:
            current = None
        new_text, result = mutate(current)
        if new_text is not None:
            atomic_write(path, new_text, encoding=encoding)
        return result
    finally:
        _release(lock)
