"""The slot pool — atomic leases, cwd-coupled staleness, ownership-scoped reaping.

Three design commitments, each traceable to a measured defect:

**`mkdir` IS the lock.** A claim is `mkdir(<leases>/<slot>)` with `exist_ok=False`. That single syscall is
atomic on every POSIX filesystem, so two claimants racing for one slot cannot both win: the loser gets
`FileExistsError` and is told `NoCapacity`. There is no lockfile, no flock, and above all no
check-then-create — "is it free? then take it" is two operations with a window between them, and the
predecessor's pool had exactly that window.

**The lease body lives INSIDE the claimed directory.** `<leases>/<slot>/lease.json` is written after the
mkdir that won the slot, so a slot is never *recorded* as held without being held.

The converse is **not** true, and this docstring used to claim it was — *"there is no state in which a slot is
held with no owner recorded"*. There is: the write that publishes the body is itself two steps, and a process
that dies between them leaves the directory won and the body still under its staging name. `SI-7` is what
that cost. Every body-reader then called the slot free, `free_slots` (which tests the directory) called it
taken, `claim` refused it forever, and `reap` — the remedy the refusal named — exited 0 reporting `0 could
not be freed`. A permanently lost workspace with no alarm anywhere.

That state now has a name (`interrupted_claims`), a label in the `leases` view, a row kind of its own in a
reap, and a sentence in the refusal that names it. It is decided on the writer's **liveness**, recovered from
the pid in the staging file's own name, rather than on elapsed time. The lesson is the one `FI-27a` already
recorded once in this package: an invariant asserted in the docstring of the module responsible for it is
what a reader checks *instead of* the code, so a false one there is worse than none.

**Staleness is cwd-coupled, not "tmux gone".** `OBS-48` measured two live processes holding `ws3`
simultaneously, because the slot was re-leased while an older worker still sat in it. A session that
outlives its work never has a dead tmux, so tmux liveness alone cannot answer "is this slot really free?".
`release` refuses while any live process holds the slot path as its cwd, and **names the pids** — a refusal
a human cannot act on is a refusal that gets forced blindly.

**A claim is ORDERED, and freeing is idempotent.** Two additions the first real-concurrency run paid for.
`claimed_ns` gives the claims a total order every racing claimant computes identically from the lease bodies,
which is what lets a cap admit exactly `cap` of N simultaneous claimants instead of all of them or none of
them (`FI-21`); admission is then a property of a won lease rather than of a read. And `release` treats a
lease that is already gone as the end state it was asked for rather than an error, returning whether **this**
call did the freeing — because two reapers enumerate the same stale set, and a reap that derives its report
by diffing announces one free twice (`FI-22`).

**Ownership-safe by default.** `reap(base_instant=...)` frees only leases tagged with that base, plus
untagged legacy ones; freeing across efforts requires `all_efforts=True` said out loud. A foreign lease is
left alone, and in `strict=True` mode the refusal **names the owning base** (`RI-31`: the guard refused
*correctly* and read as a bug purely because it never said whose lease it was). "Not yours to clear" is a
state, not a failure.

Liveness and cwd-holding arrive as injected callables, so this module spawns no subprocess and the suite can
describe a whole fleet without owning one. `pool` is a leaf: it imports only `fleet.errors`.
"""
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from fleet.atomic import TMP_SUFFIX, atomic_write
from fleet.errors import BadInput, NoCapacity, Refused

_LEASE_BODY = "lease.json"

#: How long a reader waits for the body of a claim it can SEE to appear. `mkdir` wins the slot and the body
#: is written inside it microseconds later, so a claim directory with no body is almost always a claim
#: mid-birth rather than a claim that failed to be born. `FI-21` turns on reading that window correctly:
#: admission is decided from the ordered claim list, and a claim that is invisible to one racer and visible
#: to another is two racers computing two different orders — which is how two of them both admit.
SETTLE_S = 0.5
_SETTLE_POLL_S = 0.005

#: How old a BODILESS claim must be before `reap` treats it as an interrupted claim rather than a claim
#: mid-birth. `SI-7`: a crash between the body's `write()` and its `rename()` leaves a claim directory the
#: `mkdir` won, with the body still under its staging name — and before this that state was PERMANENT. Every
#: body-reader called the slot free, `free_slots` (which tests the directory) called it taken, `claim`
#: refused it forever, and `reap` exited 0 reporting `0 could not be freed`.
#:
#: This is the FALLBACK discriminator, used only when the claim directory is empty — the crash landed before
#: a staging file existed, so nothing records who was writing and time is the only evidence there is. When a
#: staging file IS present its name carries the writer's pid, and a dead writer licenses an immediate reclaim
#: at any age: a fact rather than an inference, and the same principle `release` already applies when it
#: refuses while a live process holds the slot path.
#:
#: The floor is deliberately generous, because the two directions cost very differently. Leaving litter for
#: 30s delays a recovery; reclaiming a claim mid-birth deletes a lease a live process is about to write, and
#: hands the same slot to a second claimant while the first believes it holds it. It is tuned against the
#: direction where being wrong is expensive — which is also why a live pid overrides it in the other
#: direction and no floor, however low, can reclaim a claim whose writer is still running.
INTERRUPTED_CLAIM_AGE_S = 30.0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pid_in_staging_name(name: str):
    """The writing process's pid out of an `atomic.tmp_name` staging file, or None.

    `tmp_name` builds `.<target>.<pid>.<monotonic_ns>.<rand48>.tmp`, so the artifact of an unfinished write
    identifies its own author even though the body that would name an owner is exactly what is missing. That
    is what lets `interrupted_claims` decide on **liveness** instead of on elapsed time (`SI-7`).

    Returns None rather than guessing on any shape that does not match — a wrong pid here would be read as
    "some unrelated live process", which fails safe (the claim is left alone), but only if the parse refuses
    rather than improvises.
    """
    if not (name.startswith(".") and name.endswith(TMP_SUFFIX)):
        return None
    parts = name[: -len(TMP_SUFFIX)].split(".")
    if len(parts) < 4:
        return None
    #: …<pid>.<monotonic_ns>.<rand48>  — the pid is third from the end, and all three must be the shape
    #: `tmp_name` writes, or this is not one of ours.
    pid, ns, rand = parts[-3], parts[-2], parts[-1]
    if not (pid.isdigit() and ns.isdigit() and len(rand) == 12):
        return None
    return int(pid)


def _live_pid(pid: int) -> bool:
    """Whether a pid is running, read from `/proc`.

    Deliberately NOT `os.kill(pid, 0)`, which is the usual idiom: this package's audit asserts that only the
    three lifecycle transactions end a session, and it reads `os.kill` as ending one. Signal 0 ends nothing,
    so the audit is over-broad here — but the right response is not to widen a guard that protects
    `close`/`abort`/`harvest` from acquiring a fourth caller. `/proc` is what `session.default_probes`
    already reads for every process's cwd and cmdline, so this adds no new platform assumption; it just
    stops using the one call the audit cannot distinguish from a kill.
    """
    return (Path("/proc") / str(pid)).exists()


@dataclass
class Lease:
    slot: str
    path: Path
    todo_id: str
    tmux: str
    base_instant: str
    child_instant: str
    claimed_at: str
    #: When the claim was WON, in nanoseconds. `claimed_at` is seconds, which is far too coarse to order
    #: claims that raced: five dispatchers released by one barrier all record the same second. This field
    #: exists to be an ORDER, not a time — it is what makes `rank` a total order over simultaneous
    #: claimants, and so what lets exactly `cap` of them admit instead of all or none (`FI-21`).
    claimed_ns: int = 0

    def to_json(self) -> dict:
        return {
            "slot": self.slot,
            "path": str(self.path),
            "todo_id": self.todo_id,
            "tmux": self.tmux,
            "base_instant": self.base_instant,
            "child_instant": self.child_instant,
            "claimed_at": self.claimed_at,
            "claimed_ns": self.claimed_ns,
        }

    @classmethod
    def from_json(cls, d: dict) -> "Lease":
        try:
            return cls(slot=d["slot"], path=Path(d["path"]), todo_id=d["todo_id"],
                       tmux=d["tmux"], base_instant=d.get("base_instant", ""),
                       child_instant=d.get("child_instant", ""), claimed_at=d.get("claimed_at", ""),
                       claimed_ns=int(d.get("claimed_ns", 0) or 0))
        except KeyError as exc:
            raise BadInput(f"lease body is missing the field {exc.args[0]!r}") from exc

    @property
    def rank(self) -> tuple:
        """This claim's place in the total order every racer computes identically.

        Read from the lease bodies themselves, so it is the same order for every reader — which is the
        property that matters. It does not need to be an accurate clock; it needs to be one order.
        """
        return (self.claimed_ns, self.slot)


@dataclass
class ReapReport:
    """What one reap did, in four lists — and each one being separate is the point.

    `freed` is what **this call** gave back, not what ended up free: under a concurrent reaper those are
    different sets, and reporting the second makes one free look like two (`FI-22`).

    `unfreed` is a stale lease this caller owns and could not free, named with why. *"Absence is never
    success"* — a reap that quietly omits what it failed to free reports a clean sweep it did not perform.

    `skipped` is somebody else's stale lease, left alone. Not a failure — a state (`RI-31`).

    `reclaimed` is the fourth and it is `SI-7`'s: an INTERRUPTED claim — a directory a `mkdir` won whose
    lease body never landed — cleared and **named**. Deliberately not folded into `freed`, because
    reclaiming litter left by a dead writer and giving back a lease a worker finished with are different
    events, and a report that conflates them tells the operator a worker completed when a process died
    mid-write. Before this existed such a slot was lost permanently and appeared in **none** of the other
    three lists — which is precisely the omission the `unfreed` paragraph above already forbade, sitting
    undetected in the same docstring that forbade it.
    """

    freed: list = field(default_factory=list)      # [slot]
    unfreed: list = field(default_factory=list)    # [(slot, why)]
    skipped: list = field(default_factory=list)    # [(slot, owning base)]
    reclaimed: list = field(default_factory=list)  # [(slot, what was cleared)]
    #: `E9` mode 2. A bodiless claim this call could NOT attribute and therefore did not touch: no lease
    #: body and no staging file, so no pid, so no evidence its writer is dead — and younger than the age
    #: floor, which is the only other evidence available. Declining is correct; saying nothing was not.
    #: The slot is unclaimable right now and `reap` is the remedy the capacity refusal names, so a report
    #: that omits it lets an operator read a stuck pool as a busy one. Nothing here is deleted.
    unattributable: list = field(default_factory=list)  # [(slot, why, seconds until it can be judged)]

    def __iter__(self):
        """Iterating a report walks the slots it freed, so `for slot in reap(...)` still reads the way it
        did when this returned a bare list."""
        return iter(self.freed)

    def __len__(self) -> int:
        return len(self.freed)


class Pool:
    """Enrolment is opt-in; a claim is a directory that either exists or does not.

    Layout under `home`:

        <home>/pool/enrolled/<slot>.json    the slot is a member of the pool, and where it lives
        <home>/pool/leases/<slot>/          THE LOCK — its existence is the claim
        <home>/pool/leases/<slot>/lease.json  who holds it, written inside the claim
    """

    def __init__(self, home: Path,
                 cwd_probe: Callable[[Path], list] = None,
                 alive: Callable[[str], bool] = None,
                 pid_alive: Callable[[int], bool] = None,
                 fleet_root: Path = None):
        self.home = Path(home)
        #: `G3`. The FLEET root this pool belongs to, when there is one — not to be confused with
        #: `self.root` two lines down, which is this pool's own directory. Optional because the hermetic
        #: suite and every IT section build a pool with no fleet root and enrol sandbox directories that
        #: legitimately live anywhere on the filesystem.
        self.fleet_root = None if fleet_root is None else Path(fleet_root)
        self.root = self.home / "pool"
        self.enrolled = self.root / "enrolled"
        self.leases = self.root / "leases"
        self._cwd_probe = cwd_probe if cwd_probe is not None else (lambda p: [])
        self._alive = alive if alive is not None else (lambda name: False)
        #: Unlike the other two seams this one defaults to the REAL check rather than to "nothing is alive".
        #: A default of False here would mean a pool constructed without a probe treats every claim mid-birth
        #: as litter and deletes a live worker's lease — so the safe default is the true answer, and a test
        #: that wants determinism injects one (`SI-7`).
        self._pid_alive = pid_alive if pid_alive is not None else _live_pid

    # ---- enrolment -------------------------------------------------------------------------

    def enroll(self, path: Path) -> None:
        path = Path(path)
        if not path.is_dir():
            raise BadInput(
                f"{path} is not an existing directory; a slot is enrolled by pointing at the workspace "
                "that already exists. Enrolment never creates the workspace."
            )
        #: `G3`. A slot outside its own root is how one root's worker gets leased into another root's
        #: workspace — the interference per-root isolation exists to remove. A PATH comparison rather than
        #: a prefix test, because `/x/davis_root2` starts with `/x/davis_root`.
        if self.fleet_root is not None:
            resolved, owner = path.resolve(), self.fleet_root.resolve()
            if owner != resolved and owner not in resolved.parents:
                raise BadInput(
                    f"{resolved} is outside this fleet's root {owner}, so it cannot be enrolled here. A "
                    f"pool that can lease a workspace belonging to another root is exactly the "
                    f"interference per-root isolation exists to remove. Enrol it from the root that owns "
                    f"it.")
        slot = path.name
        if not slot or "/" in slot:
            raise BadInput(f"{path} has no usable slot name (the slot name is the directory's basename)")
        atomic_write(self.enrolled / f"{slot}.json",
                     json.dumps({"slot": slot, "path": str(path.resolve())}, indent=2))

    def unenroll(self, slot: str, force: bool = False) -> None:
        record = self.enrolled / f"{slot}.json"
        if not record.is_file():
            raise BadInput(f"slot {slot!r} is not enrolled in {self.enrolled}")
        held = self.lease(slot)
        if held is not None and not force:
            # The refusal says an override EXISTS and never spells it as a python kwarg: this message is
            # transported verbatim to whoever typed a command, and `cli` appends the exact token they type
            # (`FI-19b` — an error written for the wrong audience names a remedy in the wrong language).
            raise Refused(
                f"slot {slot!r} is leased by todo {held.todo_id!r} (tmux {held.tmux!r}) for effort "
                f"{held.base_instant!r}; unenrolling it would strand that work. Release it first, or say "
                "the override out loud.",
                clears_when=f"the lease on {slot!r} is released",
                clears_who=held.base_instant or None,
            )
        if held is not None:
            self.release(slot, force=True)
        record.unlink()

    def slots(self) -> list:
        if not self.enrolled.is_dir():
            return []
        return sorted(p.stem for p in self.enrolled.glob("*.json"))

    def slot_path(self, slot: str) -> Path:
        record = self.enrolled / f"{slot}.json"
        if not record.is_file():
            raise BadInput(f"slot {slot!r} is not enrolled in {self.enrolled}")
        return Path(json.loads(record.read_text())["path"])

    # ---- leases ----------------------------------------------------------------------------

    def lease(self, slot: str) -> Optional[Lease]:
        """The claim on `slot`, or None when there is none.

        `SI-35`. An unreadable lease body used to raise `JSONDecodeError` straight out of here, and `reap`
        builds its view with a dict comprehension over every slot — so one corrupt file took the whole verb
        down with a traceback, and `reap` is the verb you run precisely when the pool is already in a state
        you do not understand. `§O5` found it.

        Refused as `BadInput` NAMING THE FILE, not swallowed to None. The distinction matters: None means
        "no claim", and a slot whose claim exists but cannot be read is not free — treating it as free is how
        a second worker gets leased into a directory somebody is still in. `free_slots` already draws that
        line the same way, on the claim DIRECTORY rather than on a readable body.
        """
        body = self.leases / slot / _LEASE_BODY
        if not body.is_file():
            return None
        try:
            data = json.loads(body.read_text())
        except FileNotFoundError:
            #: VANISHED between the `is_file()` above and this read, which is not corruption — it is the
            #: concurrent-freer race, and "the body is gone" already has an answer three lines up: there is no
            #: lease. `tests/test_pool.py::TestFreeingIsIdempotentUnderAConcurrentFreer` caught the first
            #: version of this guard refusing here, and it was right to: two reapers freeing the same slot is
            #: normal, and one of them losing the read must not raise at the other.
            return None
        except (OSError, ValueError) as exc:
            raise BadInput(
                f"the lease body {body} cannot be read ({exc}). The slot is NOT free — its claim directory "
                f"exists, so something holds it — but who holds it cannot be determined from this file. "
                f"Inspect it by hand; a slot treated as free here is how a second worker is leased into a "
                f"directory somebody is still in.") from exc
        return Lease.from_json(data)

    def free_slots(self) -> list:
        """Slots with no claim DIRECTORY. Deliberately not "slots with no lease body": the directory is the
        lock, so a slot whose claim dir exists is taken whether or not anybody can read who took it. An
        interrupted claim therefore does not appear here, and that is correct — it cannot be claimed. What
        was wrong before `SI-7` is that nothing else reported it either, so the capacity vanished silently.
        """
        return [s for s in self.slots() if not (self.leases / s).is_dir()]

    def _claim_age_s(self, slot: str) -> float:
        """Seconds since the claim directory for `slot` was last touched, or 0 if it is gone.

        Read from the same `st_mtime` `interrupted_claims` judges by, so the "wait N more seconds" a
        report gives an operator is derived from the clock the decision was actually made on rather than
        from a second, independently-drifting one.
        """
        try:
            return max(0.0, time.time() - (self.leases / slot).stat().st_mtime)
        except OSError:
            return 0.0

    def interrupted_claims(self, min_age_s: float = INTERRUPTED_CLAIM_AGE_S) -> list:
        """Claim directories a `mkdir` won whose lease body never landed: `[(slot, why)]`.

        This is the state `SI-7` names. It is reported as its own thing rather than as a lease with missing
        fields, because there is genuinely no owner to report — the body that would have said whose it is is
        the thing that did not get written.

        **Two discriminators, and the first is far better than the second.**

        1. **The writer's pid is dead.** `atomic.tmp_name` puts the writing process's pid in the staging
           file's name, so the artifact identifies its own author even though the body does not. A staging
           file whose pid is gone is a claim that will never be finished — a *fact*, not an inference — and
           it is reclaimable immediately, however young. This is the same move the module already makes for
           leases: `release` refuses while a live process holds the path, so liveness, not time, is what
           licenses a delete.
        2. **Age**, for the case where there is no staging file at all — the crash landed between the
           `mkdir` and the write, so nothing records who was writing. Here time is the only evidence there
           is, and `min_age_s` is a floor rather than a convenience: below it a bodiless claim cannot be
           told apart from a claim mid-birth, and treating one as the other deletes a live worker's lease.

        A live pid pins the claim as mid-birth and it is never reported, whatever its age — the direction
        where being wrong is expensive.
        """
        if not self.leases.is_dir():
            return []
        now, out = time.time(), []
        for slot in self.slots():
            claim_dir = self.leases / slot
            if not claim_dir.is_dir():
                continue
            if (claim_dir / _LEASE_BODY).is_file():
                continue                       # a real lease: somebody's, and not this method's business
            try:
                # `litter`, not `staging`: these are names READ off disk, left by a write that never
                # published. Nothing here builds a staging path — `FI-20`'s guard flagged my first name for
                # this variable and it was right to, because the name claimed the opposite of what the code
                # does. `atomic_write` remains the only thing in the package that constructs one.
                litter = [e.name for e in claim_dir.iterdir()
                          if e.name.startswith(".") and e.name.endswith(TMP_SUFFIX)]
                age = max(0.0, now - claim_dir.stat().st_mtime)
            except OSError:
                continue                       # vanished under us; nothing to report
            pids = [pid for pid in (_pid_in_staging_name(n) for n in litter) if pid is not None]
            if pids:
                if any(self._pid_alive(pid) for pid in pids):
                    continue                   # its writer is alive: this is a claim mid-birth, not litter
                out.append((slot, f"the writing process ({', '.join(str(p) for p in sorted(pids))}) is "
                                  f"gone and the lease body was never renamed into place; bodiless for "
                                  f"{age:.0f}s"))
                continue
            if age >= max(0.0, min_age_s):
                out.append((slot, f"the claim directory has been empty for {age:.0f}s — the writer died "
                                  f"before it staged a body, so nothing records who it was"))
        return sorted(out)

    def _reclaim(self, slot: str) -> str:
        """Clear one interrupted claim. Returns what was cleared, or raises `Refused` naming what stopped it.

        Removes ONLY staging files — the `.<name>.<pid>.<ns>.<rand>.tmp` shape `atomic.tmp_name` produces —
        and then the directory. Anything else in there is somebody's data and is **reported, not swept**:
        that is `M9`'s rule about delete sites applied to a delete site of my own, and the reason this
        method names a ceiling instead of calling `rmtree`.

        Tolerates the artifact vanishing under it, like `release` does: two reapers enumerate the same set,
        and a claim already gone is the end state this call wanted (`FI-22`).
        """
        claim_dir = self.leases / slot
        cleared = []
        try:
            entries = list(claim_dir.iterdir())
        except FileNotFoundError:
            return ""                                     # a concurrent reaper got there first
        for entry in entries:
            if entry.is_file() and entry.name.startswith(".") and entry.name.endswith(TMP_SUFFIX):
                try:
                    entry.unlink()
                    cleared.append(entry.name)
                except FileNotFoundError:
                    pass
            else:
                raise Refused(
                    f"the interrupted claim on slot {slot!r} holds {entry.name!r}, which is not a staging "
                    f"file this reap recognises. Left exactly as it is — clearing a file nobody can "
                    f"account for is how a recovery becomes a data loss. Look at {claim_dir}, then remove "
                    f"the directory by hand if it really is litter.",
                    clears_when=f"{entry.name!r} is accounted for and {claim_dir} is removed by hand",
                )
        try:
            claim_dir.rmdir()
        except FileNotFoundError:
            return ""
        except OSError as exc:
            raise Refused(
                f"slot {slot!r}'s interrupted claim could not be removed after clearing "
                f"{len(cleared)} staging file(s): {type(exc).__name__}: {exc}",
                clears_when=f"{claim_dir} can be removed",
            )
        return (f"cleared {len(cleared)} staging file(s) left by a writer that died between the lease "
                f"body's write and its rename" if cleared else
                "removed an empty claim directory whose writer died before the body was staged")

    def claims(self, settle_s: float = SETTLE_S) -> list:
        """Every lease the pool holds right now, IN ORDER, waiting out claims that are mid-birth.

        This is the artifact admission is decided from (`FI-21`). A slot claim is `mkdir` and its body is
        written inside it immediately after, so there is a window — microseconds wide — in which a claim
        exists and cannot be read. A reader that skips such a claim and a reader that sees it compute two
        different orders, and two racers with two different orders both think they came first. So a visible
        claim with no readable body is WAITED for.

        A claim still bodiless after `settle_s` is not counted, and that direction is deliberate: it means a
        process died inside a microsecond window, leaving litter no reader can attribute to any effort.
        Counting an unattributable claim would refuse on evidence nobody can act on (`D-6`), which is the
        one thing every guard in this package is forbidden to do.
        """
        if not self.leases.is_dir():
            return []
        held = []
        for slot in self.slots():
            claim_dir = self.leases / slot
            if not claim_dir.is_dir():
                continue
            lease = self._settled(slot, settle_s)
            if lease is not None:
                held.append(lease)
        return sorted(held, key=lambda held_lease: held_lease.rank)

    def _settled(self, slot: str, settle_s: float):
        deadline = time.monotonic() + max(0.0, settle_s)
        while True:
            lease = self.lease(slot)
            if lease is not None:
                return lease
            if not (self.leases / slot).is_dir():
                return None                # released while we waited: there is no claim to order
            if time.monotonic() >= deadline:
                return None
            time.sleep(_SETTLE_POLL_S)

    def claim(self, todo_id, tmux, base_instant, child_instant, slot=None) -> Lease:
        """Take a slot. `mkdir` is the lock: whoever's mkdir succeeds owns the slot, and the body is then
        written inside what was just won. No check-then-create window exists to lose."""
        if slot is not None:
            candidates = [slot]
            if slot not in self.slots():
                raise BadInput(
                    f"slot {slot!r} is not enrolled; enrolled slots are {self.slots()}. A pool never "
                    "claims a workspace nobody put in it."
                )
        else:
            candidates = self.free_slots()
            if not candidates:
                # `SI-7`: this message told the operator to `reap` while an interrupted claim was invisible
                # to `reap` — the remedy it named could not clear the condition it reported. It can now, and
                # the count is stated so an exhausted pool does not read the same whether the slots are
                # doing work or merely lost.
                interrupted = self.interrupted_claims(min_age_s=0.0)
                detail = ""
                if interrupted:
                    detail = (f" {len(interrupted)} of them hold an INTERRUPTED claim with no lease body — "
                              f"{', '.join(repr(s) for s, _ in interrupted)} — which is a dead writer and "
                              f"not work in progress; a reap clears those and names them.")
                raise NoCapacity(
                    f"every enrolled slot is leased ({', '.join(self.slots()) or 'none enrolled'}).{detail} "
                    "Release or reap one, or enroll another workspace."
                )
        self.leases.mkdir(parents=True, exist_ok=True)
        for candidate in candidates:
            claim_dir = self.leases / candidate
            try:
                claim_dir.mkdir()          # THE LOCK — atomic; exist_ok is deliberately not set
            except FileExistsError:
                continue
            held = Lease(slot=candidate, path=self.slot_path(candidate), todo_id=todo_id, tmux=tmux,
                         base_instant=base_instant, child_instant=child_instant, claimed_at=_now(),
                         claimed_ns=time.time_ns())
            atomic_write(claim_dir / _LEASE_BODY, json.dumps(held.to_json(), indent=2))
            return held
        if slot is not None:
            existing = self.lease(slot)
            if existing is not None:
                raise NoCapacity(
                    f"slot {slot!r} is already leased by todo {existing.todo_id!r} "
                    f"(tmux {existing.tmux!r})")
            # No body. Either a claim is being born microseconds from now, or a writer died between the
            # body's write and its rename — and the shipped message called both "an unnamed claim", which
            # named neither the condition nor anything the reader could do. `SI-7`: the second case used to
            # be permanent, so this refusal was the last thing the operator saw before losing the slot.
            why = dict(self.interrupted_claims(min_age_s=0.0)).get(slot)
            if why is None:
                raise NoCapacity(
                    f"slot {slot!r} was claimed by another process while this call was choosing, and that "
                    f"writer is still running. Nothing is wrong: try again, or let the pool pick a slot.")
            raise NoCapacity(
                f"slot {slot!r} holds an INTERRUPTED claim — the directory that wins the slot exists, but "
                f"the lease body inside it was never finished, so there is no owner to name: {why}. "
                f"`reap` clears it and says what it cleared.")
        raise NoCapacity("every enrolled slot was taken while claiming; nothing free to hand out")

    def release(self, slot: str, force: bool = False, expect_todo: str = None) -> bool:
        """Give a slot back. Returns True when THIS call is the one that removed the claim.

        Refuses while a live process holds the slot path as its cwd, and NAMES THE PIDS. `OBS-48`: tmux
        liveness cannot see a session that outlived its work, so "the tmux is gone" is not freedom.

        **Idempotent under a concurrent freer** (`FI-22`). Two reapers enumerate the same stale set, so
        every step here has to tolerate the artifact having vanished under it: *a lease that is already gone
        is the desired end state, not an error*. Measured before the fix at 10 of 10 iterations, where the
        second reaper died on `FileNotFoundError` out of `body.unlink()` and the traceback reached the
        operator instead of a row.

        The return value, and not the absence of an exception, is what says who did the freeing — which is
        the other half of the same defect. Deriving "what I freed" by diffing the pool before and after
        makes both reapers report every slot, so a slot freed once is announced twice.

        `expect_todo` closes the last window: if the slot has been RE-CLAIMED since the caller read it, the
        lease it asked to free is already gone and the new claim is somebody else's work. Freeing that would
        be a genuine double free — the destructive one, where a live worker loses its slot.
        """
        claim_dir = self.leases / slot
        held = self.lease(slot)
        if not claim_dir.is_dir():
            return False                   # already given back: the end state the caller asked for
        if expect_todo is not None and held is not None and held.todo_id != expect_todo:
            return False                   # re-claimed under us; the lease we were asked to free is gone
        if held is not None and not force:
            pids = list(self._cwd_probe(held.path))
            if pids:
                raise Refused(
                    f"slot {slot!r} ({held.path}) is held as cwd by live pid(s) "
                    f"{', '.join(str(p) for p in pids)}; releasing it would let a second worker be "
                    f"leased into a directory somebody is still working in (OBS-48). Lease is todo "
                    f"{held.todo_id!r} for effort {held.base_instant!r}.",
                    clears_when=f"pid(s) {', '.join(str(p) for p in pids)} exit {held.path}",
                    clears_who=held.base_instant or None,
                )
        (claim_dir / _LEASE_BODY).unlink(missing_ok=True)
        try:
            for leftover in sorted(claim_dir.iterdir()):
                if leftover.is_file():
                    leftover.unlink(missing_ok=True)
            claim_dir.rmdir()              # releasing the lock is the same one syscall, in reverse
        except FileNotFoundError:
            return False                   # a concurrent freer got there first — the same end state
        except OSError as exc:
            # Not "already free" and not this call's to force: something appeared inside the claim after it
            # was scanned. Raised NAMING the slot so `reap` can report it rather than skip it silently.
            raise Refused(
                f"slot {slot!r} still has a claim directory that could not be removed: {exc}. The lease "
                "body is gone, so nothing holds the slot logically, but the lock directory remains.",
                clears_when=f"{claim_dir} is empty and can be removed",
                clears_who=(held.base_instant if held is not None else None) or None,
            ) from None
        return True

    # ---- reaping ---------------------------------------------------------------------------

    def reap(self, base_instant=None, all_efforts: bool = False, strict: bool = False,
             min_claim_age_s: float = INTERRUPTED_CLAIM_AGE_S) -> "ReapReport":
        """Free every stale lease this caller OWNS, and report what it freed AND what it could not.

        A lease is stale when its tmux is not alive AND no live process holds its path as cwd. It is
        this caller's to free when `all_efforts` is set, or when the lease carries no base (legacy,
        untagged), or when its base equals `base_instant`.

        Non-strict: a foreign stale lease is skipped and reported by omission — the common case, where
        several efforts share one pool and each reaps its own. Strict: raise `Refused` NAMING the owning
        base, because a refusal that does not say whose lease it was reads as a bug (`RI-31`). The report
        rides on that exception too, because the owned leases have already been given back by then and an
        exception that drops them hides work this call really did.

        Two reapers may run at once, and `FI-22` is what that cost: `reap` returns only the slots **this**
        call freed, never every slot that ended up free, so a slot freed once is announced once. And a slot
        it could not free is named in `unfreed` rather than raised — the whole point of a reap is the report.
        """
        freed, unfreed, skipped, reclaimed = [], [], [], []

        # `SI-7` first, and it is FIRST on purpose: an interrupted claim makes a slot unclaimable, so
        # clearing it is the difference between a pool that recovers and a pool that has lost a workspace
        # for good. An interrupted claim carries no base — the body that would name one is what failed to be
        # written — so it falls under the rule this method already applies to an untagged lease: nobody
        # owns it, therefore it is this caller's to clear. That is why `--all` is not required; the operator
        # is told to `reap` by the very refusal they hit, and a remedy that needs a second, undocumented
        # flag is the unclearable alarm again (`FI-30a`).
        # `E9` mode 2: what this call can SEE but cannot yet judge. Computed before the reclaim loop and
        # from the same predicate at a zero floor, so the two cannot disagree about which claims exist —
        # the difference between the lists is exactly the age floor, which is the thing being reported.
        reclaimable = {slot for slot, _ in self.interrupted_claims(min_age_s=min_claim_age_s)}
        unattributable = []
        for slot, why in self.interrupted_claims(min_age_s=0.0):
            if slot in reclaimable:
                continue                                # this call is about to clear it; not a report
            unattributable.append((slot, why, max(0.0, min_claim_age_s - self._claim_age_s(slot))))

        for slot, why in self.interrupted_claims(min_age_s=min_claim_age_s):
            try:
                what = self._reclaim(slot)
                if what:
                    reclaimed.append((slot, f"{what}. Judged interrupted because {why}"))
                # else: a concurrent reaper cleared it. Its call reports it, not this one (`FI-22`).
            except Refused as exc:
                unfreed.append((slot, str(exc)))
            except OSError as exc:
                unfreed.append((slot, f"{type(exc).__name__}: {exc}"))

        for slot in self.slots():
            held = self.lease(slot)
            if held is None:
                continue
            owner = held.base_instant or ""
            mine = all_efforts or owner == "" or owner == base_instant
            if self._alive(held.tmux):
                continue                                    # its worker is still running
            if list(self._cwd_probe(held.path)):
                continue                                    # somebody is still sitting in it (OBS-48)
            if not mine:
                skipped.append((slot, owner, held))
                continue
            try:
                if self.release(slot, expect_todo=held.todo_id):
                    freed.append(slot)
                # else: a concurrent reaper freed it first. That is the end state this call wanted, and
                # reporting it anyway is how one free gets announced twice (FI-22).
            except Refused as exc:
                unfreed.append((slot, str(exc)))
            except OSError as exc:
                unfreed.append((slot, f"{type(exc).__name__}: {exc}"))
        #: Recomputed against what was ACTUALLY reclaimed, not against the pre-loop prediction: a
        #: concurrent reaper may have cleared one between the two, and reporting a slot as "stuck, wait
        #: 29s" when it is already free is the same class of lie as omitting it.
        cleared = {slot for slot, _ in reclaimed}
        report = ReapReport(freed=sorted(freed), unfreed=sorted(unfreed),
                            skipped=sorted((slot, owner) for slot, owner, _ in skipped),
                            reclaimed=sorted(reclaimed),
                            unattributable=sorted((s, w, r) for s, w, r in unattributable
                                                  if s not in cleared
                                                  and (self.leases / s).is_dir()))
        if strict and skipped:
            slot, owner, held = skipped[0]
            others = "".join(f"; {s} is {o}" for s, o, _ in skipped[1:])
            # Named in words, not in kwargs, for the same reason as `unenroll` above: `cli` quotes the
            # `--all` token, and this sentence is read by whoever typed the command (`FI-19b`).
            refusal = Refused(
                f"slot {slot!r} holds a stale lease owned by {owner} (todo {held.todo_id!r}, tmux "
                f"{held.tmux!r}), not by {base_instant!r}{others}. Not yours to clear — that is a "
                "state, not a failure. The owner reaps it, or the every-effort override is said out loud.",
                clears_when=f"{owner} reaps {slot!r}, or a reap across every effort is said out loud",
                clears_who=owner,
            )
            refusal.report = report
            raise refusal
        return report
