"""The instant name as a type — the ONE place a name is parsed, formatted or resolved.

Why a type and not a regex per caller: the predecessor parsed this string at ten call sites with
divergent rules. Two hardcoded `^\\d{8}-\\d{8}`, so no root instant resolved through a rename (OI-16);
one hardcoded a VALUE of the opType field, so every correct compaction rendered `(missing)` from the
moment of dispatch (OI-17); and `base-curr` was used as a unique key in three tools when two instants
dispatched in the same minute share it (OBS-14).
"""
import re
from dataclasses import dataclass
from pathlib import Path

from fleet.errors import AmbiguousId, InstantNameError

ROOT_BASE = "00000000"
STATES = ("inflight", "complete", "abort")
OPTYPES = ("append", "compact")

_TS = re.compile(r"^\d{8}$")
_NAME = re.compile(r"^[a-z][A-Za-z0-9]*$")


@dataclass(frozen=True)
class InstantName:
    base: str
    curr: str
    state: str
    optype: str
    name: str

    def __post_init__(self):
        for field, value, ok in (
            ("base_instant", self.base, _TS.match(self.base)),
            ("curr_instant", self.curr, _TS.match(self.curr)),
            ("state", self.state, self.state in STATES),
            ("opType", self.optype, self.optype in OPTYPES),
            ("instantName", self.name, _NAME.match(self.name)),
        ):
            if not ok:
                raise InstantNameError(
                    f"{field}={value!r} is outside its declared domain. "
                    f"base/curr are 8 digits ({ROOT_BASE} is the root; `main` is deprecated), "
                    f"state in {STATES}, opType in {OPTYPES}, instantName is dashless camelCase."
                )

    @classmethod
    def parse(cls, text: str) -> "InstantName":
        parts = text.split("-")
        if len(parts) != 5:
            raise InstantNameError(
                f"{text!r} has {len(parts)} dash-separated fields; the grammar has exactly 5: "
                "<base>-<curr>-<state>-<opType>-<instantName>. instantName must be dashless."
            )
        return cls(*parts)

    @classmethod
    def new(cls, base: str, now: str, optype: str, title: str) -> "InstantName":
        return cls(base=base, curr=now, state="inflight", optype=optype, name=camel(title))

    def format(self) -> str:
        return "-".join((self.base, self.curr, self.state, self.optype, self.name))

    def with_state(self, state: str) -> "InstantName":
        return InstantName(self.base, self.curr, state, self.optype, self.name)

    def stable_key(self) -> str:
        """Identity that a lifecycle transition cannot change. `state` is omitted; every other field is
        included, because base-curr alone is NOT unique (OBS-14) — two instants dispatched in the same
        minute share it, and keying on it can resolve to a sibling."""
        return "-".join((self.base, self.curr, self.optype, self.name))


def camel(title: str) -> str:
    """A title becomes a dashless camelCase instantName. The result is always a legal name field, so a
    dispatch cannot produce an ungrammatical instant from an awkward title.

    Case is FOLDED before it is re-applied — `ANSI` becomes `Ansi`, not `ANSI`. Both forms satisfy the
    name grammar, so the grammar cannot arbitrate; what matters is that one title has exactly one
    rendering. Preserving the interior case of every word but the first (as the plan's draft did) makes
    the head word's normalisation an exception rather than a rule, and a name field feeds `stable_key`,
    where two renderings of one title are two identities.
    """
    words = [w for w in re.split(r"[^A-Za-z0-9]+", title) if w]
    if not words:
        return "todo"
    head = words[0].lower()
    out = head + "".join(w[:1].upper() + w[1:].lower() for w in words[1:])
    if not _NAME.match(out):
        out = "x" + out
    return out


def resolve(recorded: Path) -> Path | None:
    """Follow a recorded instant path through a state rename.

    A worker renames its own folder as its completion signal, so the path recorded at dispatch time goes
    stale. Matching is on the FULL stable key with only `state` varying — never on a prefix.
    """
    if recorded.exists():
        return recorded
    try:
        want = InstantName.parse(recorded.name).stable_key()
    except InstantNameError:
        return None
    parent = recorded.parent
    if not parent.is_dir():
        return None
    matches = []
    for candidate in sorted(parent.iterdir()):
        if not candidate.is_dir():
            continue
        try:
            if InstantName.parse(candidate.name).stable_key() == want:
                matches.append(candidate)
        except InstantNameError:
            continue
    if not matches:
        return None
    if len(matches) > 1:
        raise AmbiguousId(
            f"{len(matches)} instants share the stable key {want!r}: "
            + ", ".join(m.name for m in matches)
            + ". Refusing to guess; an instant may hold only one state."
        )
    return matches[0]
