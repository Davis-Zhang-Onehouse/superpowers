"""Observation — the watched-source registry, the issue set-diff, the cadence trigger and repetition.

This is the meta loop's half of UC-1: *"meta loop being the observer to optimize away repeated suboptimal
routine."* Three properties carry the weight, and each was **dropped once already** by a review of the
design rev, which is why each is stated here next to the code that implements it rather than left in a plan.

**1. The registry has a WRITER, not just contents.** `record_dispatch` is the dispatch transaction's
harvest half: it registers the base and *then* writes the record, in one call, so a dispatch cannot produce
a record whose effort nobody is watching. And `lint` catches a record written any other way. Rev 1
specified the registry's *contents* and named no writer — but **a source that is not on the list cannot be
reported as silent**, which is `OBS-68`'s exact structure: 20 issues including a Critical stayed invisible
for ~4h because the register was *unlisted*, not because it was quiet. A hand-maintained registry is a
second copy of a fact the record store already holds, and the two copies diverge at the first dispatch
somebody makes in a hurry.

**2. `ids_found` is a separate NUMBER from the new-count.** The extractor is a regex over headings, and a
regex silently yields zero on a register that uses `###` or an id like `RI-9a` — after which harvest
reports "0 new" and the tick reads as a pass. That is `RCF-10`'s shape *inside the mechanism whose whole job
is catching false passes*, so the population is reported as its own number and never derived from the diff.
Both halves of the guard are load-bearing: **zero ids from a NON-EMPTY register raises**
`VacuousExtraction`; **zero ids from an EMPTY register is reported and clean.** Turning the second one RED
reinstates exactly the always-red check `OBS-21` deliberately avoided — *"vacuous because the extractor
failed"* is not *"legitimately empty"*.

**3. `repetitions` flags at TWO, with a citation per instance.** *"Two instances is a pattern; making the
brief demand it means review no longer has to be the first line of defence."* A threshold of three only
ever fires after the third time, which is one repetition too late to have been worth observing. Every
instance carries where it was seen, because a repetition with no citation is an opinion — `Repetition`
cannot be constructed without one.

**Memory is written, always.** `RI-28..31` were read with **no state file**, so the diff had no memory of
them and the next tick found them "new" again — `OBS-16` recurring on the first tick of the loop that wrote
the lesson. So a tick with no prior memory is REPORTED as a violation (loudly, once) and then records; and
`prime` writes its state file even when it records zero, because an empty state file is memory and a
missing one is not.

**The `.md` exemption.** This is one of the two sanctioned exemptions to *"no module reads a `.md` file for
a control signal"* (AC-2): it reads issue **ids** out of an `ISSUES.md`, and nothing else. No phase, no
verdict, no state and no capacity decision comes out of prose here — the register is a population to count,
and every id it yields is reported with the population it came from.
"""
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fleet import EXIT_ATTENTION, EXIT_OK
from fleet.atomic import atomic_update, atomic_write
from fleet.errors import BadInput, FleetError
from fleet.identity import ROOT_BASE, InstantName, resolve
from fleet.layout import INFO, VIOLATION, Violation, seed_headings
from fleet.store import SCHEMA_VERSION

#: The register a base instant carries. One name, in one place: the dispatch transaction derives the path
#: it registers from this, so the registry cannot point somewhere the effort does not keep its issues.
REGISTER_NAME = "ISSUES.md"

#: Report row kinds. `SOURCE` is emitted for EVERY watched source, including the ones that produced
#: nothing — *"even a perfectly disciplined tick, run every ten minutes, would have seen nothing"*, and
#: that sentence is only checkable if silence is a row.
SOURCE = "source"
NO_MEMORY = "no-prior-state"
VACUOUS = "vacuous-extraction"
EMPTY_REGISTER = "empty-register"
NO_ISSUES_FILED = "no-issues-filed"
UNREADABLE = "unreadable-source"
STALE = "stale-source"
POPULATION = "population"

#: The lint rule name for a record whose base no source covers. Half two of property 1.
UNREGISTERED_BASE = "unregistered-base"

#: The default cadence window. Ten minutes was the observed *intended* tick; thirty is the point at which
#: silence is worth a row, and the caller says so out loud in `report`/`stale` either way.
DEFAULT_MAX_AGE_S = 1800

#: A line shorter than this is not a subject. Noise control for `repetitions`, said out loud because a
#: silent filter is a silent narrowing of the population (`OBS-49`): "Status", "Symptom" and "---" repeat
#: in every register ever written and are not a repeated routine.
MIN_SUBJECT_CHARS = 12

_STAMP = "%Y-%m-%dT%H:%M:%SZ"

#: A markdown heading of any depth. `#{1,6}` deliberately, not `##`: the extractor going blind on a
#: register that uses `###` is half of what property 2 exists to prevent.
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(?P<rest>\S.*)$")

#: An issue id, as the register writes it. Shapes that must parse, taken from the real registers: `FI-1`,
#: `OI-17`, `RI-9a` (letter suffix), `W2-14` (a digit inside the prefix), `RCF-B-8` (a middle segment).
_ID_PATTERN = r"[A-Za-z][A-Za-z0-9]{0,7}(?:-[A-Za-z]{1,3})?-\d+[a-z]?"

#: An id at the head of a heading, then its title. The separator class eats a `:`, a dot, a dash or an
#: em-dash between the two.
_ID = re.compile(rf"^(?P<id>{_ID_PATTERN})\b[\s:.–—-]*(?P<title>.*)$")

#: A leading id, stripped when a line is normalised into a repetition subject: `RI-5 flaky rebase` and
#: `OI-9 flaky rebase` are one routine seen twice, not two routines.
_LEADING_ID = re.compile(rf"^{_ID_PATTERN}\b[\s:.–—-]*")

#: An id-shaped token ANYWHERE in a register, heading or not. This is the second half of the
#: seeded-register test: a file whose headings are only the layout seed's own but which mentions an id in
#: a bullet, a table row or a paragraph is a POPULATED register the extractor could not read, and that is
#: the vacuous extraction `RCF-10` exists to catch. Only a register with the seed's headings and no id
#: anywhere is "nothing filed yet".
_ANY_ID = re.compile(rf"\b{_ID_PATTERN}\b")

_MARKUP = re.compile(r"[`*_>]+")
_BULLET = re.compile(r"^\s{0,6}(?:[-*+]|\d+[.)])\s+")


class VacuousExtraction(FleetError):
    """Zero ids out of a register that has content — the extractor is broken, not the register empty.

    A `FleetError` and therefore exit 1, *"needs attention / check failed"*: this is a failed check and not
    bad input from a caller. It is raised rather than logged because the alternative — reporting "0 new" —
    is a false pass produced by the one mechanism that exists to catch false passes.
    """


@dataclass(frozen=True)
class Source:
    """One watched register. `last_run` is the cadence clock, and `None` means "never run since it was
    registered", in which case `registered_at` is what staleness is measured from — a source registered a
    minute ago is not yet overdue."""

    base: str
    issues_path: str
    registered_at: str
    last_run: str = None


@dataclass(frozen=True)
class Issue:
    id: str
    title: str


@dataclass(frozen=True)
class Repetition:
    """A subject seen more than once, with one citation per instance.

    `__post_init__` refuses a repetition whose citations do not account for its count. That is the type
    doing the work of a review comment: *a repetition with no citation is an opinion*, and an opinion with
    a number in front of it is worse than one without.
    """

    subject: str
    count: int
    where: list

    def __post_init__(self):
        if not self.where:
            raise BadInput(
                f"the repetition {self.subject!r} cites nowhere. A repetition with no citation is an "
                "opinion; every instance names where it was seen or the finding is not reportable.")
        if self.count != len(self.where):
            raise BadInput(
                f"the repetition {self.subject!r} claims {self.count} instance(s) and cites "
                f"{len(self.where)}. The count IS the citations.")


@dataclass(frozen=True)
class Row:
    """One line of `report()`.

    `severity` uses `layout`'s vocabulary (`violation` / `info`) rather than a third copy of it, so a
    reader that aggregates lints and harvest rows does not have to translate. `clears_when`/`clears_who`
    are the alarm contract (§9) — a cadence alarm nobody is named to clear is an alarm that gets ignored.

    `ids_found` and `new_count` are two fields on purpose. Rendering them from one number is the defect
    property 2 exists to prevent, and a string detail alone would leave the assertion anchored to prose
    (`OBS-62`).
    """

    kind: str
    subject: str
    detail: str
    severity: str
    clears_when: str = None
    clears_who: str = None
    ids_found: int = None
    new_count: int = None


def exit_code(rows) -> int:
    """The code a caller returns for a set of report rows. From the ONE registry in `fleet/__init__`."""
    return EXIT_ATTENTION if any(r.severity == VIOLATION for r in rows) else EXIT_OK


def _now() -> str:
    return datetime.now(timezone.utc).strftime(_STAMP)


def _parse(stamp: str, what: str) -> datetime:
    try:
        return datetime.strptime(stamp, _STAMP).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise BadInput(f"{what}={stamp!r} is not a {_STAMP} timestamp; refusing to guess a clock") from None


def extract(text: str) -> list:
    """Every issue id and title in a register, in file order.

    Headings only, any depth, and the id must actually look like an id — which is what makes the vacuity
    guard meaningful: a register whose entries are not ids yields nothing and says so, rather than yielding
    a "0 new" that reads as a clean tick.
    """
    out = []
    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading is None:
            continue
        found = _ID.match(heading.group("rest").strip())
        if found is None:
            continue
        out.append(Issue(id=found.group("id"),
                         title=" ".join(found.group("title").replace("\t", " ").split())))
    return out


def headings(text: str) -> list:
    """Every markdown heading in a register, heading text only, in file order."""
    out = []
    for line in text.splitlines():
        found = _HEADING.match(line)
        if found is not None:
            out.append(found.group("rest").strip())
    return out


def unfiled(text: str, base: str) -> bool:
    """Is this register one the layout seed created and nobody has filed an issue in yet?

    **This is a narrowing of the vacuity guard, never a weakening of it.** `FI-18` is the emergent defect:
    `layout._seed` writes a header (a canonical file needs one), `init` registers its own base (`OBS-68` —
    unlisted is invisible), and zero ids from a non-empty register is a violation (`RCF-10` — that is how
    an extractor failure reads as a clean pass). No single decision is wrong; composed, they made every
    tick of a brand-new effort RED until somebody filed its first issue, which is the always-red alarm
    `OBS-21` deliberately avoided and the fifth instance of that family.

    So the ONE excused shape is the seed's own, and it is recognised on two facts at once:

      * every heading in the file is one `layout.seed_headings` writes for this very base — not a
        pattern that resembles it, the actual string, derived from the seed
      * no id-shaped token appears ANYWHERE in the file, so a register whose entries are bullets, table
        rows or prose is populated-and-unparseable and still raises

    A base that is not an instant name is not seeded by this layout and gets no excuse at all.
    """
    try:
        name = InstantName.parse(Path(base).name)
    except FleetError:
        return False
    seeded = set(seed_headings(REGISTER_NAME, name))
    found = headings(text)
    if not found or any(heading not in seeded for heading in found):
        return False
    return _ANY_ID.search(text) is None


def _norm(title: str) -> str:
    return " ".join(_MARKUP.sub("", title).lower().split()).strip(" .,:;—–-")


def _key(issue) -> tuple:
    """The identity a diff compares: the id's NUMBER plus the normalised title.

    The register's alphabetic prefix is bookkeeping — `I-1..I-7` becoming `OI-1..OI-7` is one renumbering,
    not seven new issues — so it is not part of the key. The number stays, because two entries with the
    same title and different numbers are two entries.
    """
    return (issue.id.rsplit("-", 1)[-1].lower(), _norm(issue.title))


def _base_key(base: str) -> str:
    """A base identity a folder rename cannot change.

    An effort's base folder renames `-inflight-` to `-complete-`, and comparing raw strings would make the
    unregistered-base lint fire on every completed effort — `OI-16`'s shape, where a path recorded at
    dispatch time went stale and a hardcoded match never followed it. Names that are not instants compare
    as themselves.
    """
    try:
        return InstantName.parse(Path(base).name).stable_key()
    except FleetError:
        return str(base)


class Harvest:
    """The watched-source registry and everything derived from it.

    Two files under `<home>/harvest/`:

      `sources.json`      the list of watched registers, written by `register` — and by the dispatch
                          transaction, which is the point
      `seen/<key>.tsv`    one file per source: the ids this loop has already announced, id and title,
                          tab-separated

    Memory is a TSV rather than JSON for one reason: it is the artifact a human reads when the diff says
    something surprising, and a line-diff over it is legible.
    """

    def __init__(self, home, now=_now):
        self.home = Path(home)
        self.dir = self.home / "harvest"
        self.path = self.dir / "sources.json"
        self.seen_dir = self.dir / "seen"
        self._clock = now

    # ---- the registry ------------------------------------------------------------------------------

    def _load(self) -> dict:
        if not self.path.is_file():
            return self._registry(None)
        return self._registry(self.path.read_text())

    def _registry(self, text) -> dict:
        """The registry, from its bytes. Split out from `_load` so the read-modify-write path parses the
        text it read UNDER THE LOCK rather than re-reading the file it is about to replace."""
        if text is None or not text.strip():
            return {"schema_version": SCHEMA_VERSION, "sources": []}
        data = json.loads(text)
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise BadInput(
                f"{self.path} has schema_version={version!r}, this build knows {SCHEMA_VERSION}. "
                "Refusing to interpret it; there is no legacy tolerance by design (FD-1).")
        return data

    def _dump(self, data: dict) -> str:
        return json.dumps(data, indent=2, ensure_ascii=False)

    def register(self, base: str, issues_path: str) -> Source:
        """Put a base's register on the watched list. Idempotent.

        Registering twice is one source: `registered_at` is preserved (it is when watching STARTED, and a
        re-register is not a new start), and so is `last_run`, because forgetting the cadence clock on a
        harmless second call is how a source silently becomes fresh forever.

        **One indivisible read-modify-write** (`FI-20`/E7). This is the registry's writer and it is on the
        dispatch transaction's critical path, so two coordinators dispatching different efforts at once run
        it concurrently by design. Read-then-write is not enough there and the failure is invisible: each
        reads an empty list, each appends its own base, and the effort that lost is not corrupted — it is
        simply *unwatched*, which is `OBS-68`'s exact structure (20 issues including a Critical invisible
        for ~4h because the register was unlisted rather than quiet). Measured at 20 of 20 iterations.
        """
        base, issues_path = str(base).strip(), str(issues_path).strip()
        if not base or not issues_path:
            raise BadInput("a watched source needs a base and a register path; neither may be empty")

        def mutate(current):
            data = self._registry(current)
            for entry in data["sources"]:
                if _base_key(entry["base"]) == _base_key(base):
                    entry["issues_path"] = issues_path   # the path may move; the start time does not
                    return self._dump(data), Source(**entry)
            entry = asdict(Source(base=base, issues_path=issues_path, registered_at=self._clock()))
            data["sources"].append(entry)
            return self._dump(data), Source(**entry)

        return atomic_update(self.path, mutate)

    def sources(self) -> list:
        return [Source(**e) for e in sorted(self._load()["sources"], key=lambda e: e["base"])]

    def _lookup(self, source) -> Source:
        """The registry's copy of a source. Harvesting something that is not on the list is refused —
        the list is the list, and a caller that can bypass it has re-created the invisible source."""
        base = source.base if isinstance(source, Source) else str(source)
        for entry in self.sources():
            if _base_key(entry.base) == _base_key(base):
                return entry
        raise BadInput(
            f"{base!r} is not a watched source. Register it (or dispatch through the transaction, which "
            "registers it) — a source that is not on the list cannot be reported as silent (OBS-68).")

    def _stamp(self, source) -> Source:
        """The cadence clock, stamped indivisibly. Same file and same hazard as `register`: two ticks that
        each read, each stamp their own source and each publish drop one source's `last_run`, which makes
        that source silently fresh forever — the very failure the comment on `register` warns about."""

        def mutate(current):
            data = self._registry(current)
            for entry in data["sources"]:
                if _base_key(entry["base"]) == _base_key(source.base):
                    entry["last_run"] = self._clock()
                    return self._dump(data), Source(**entry)
            raise BadInput(f"{source.base!r} left the registry mid-run")

        return atomic_update(self.path, mutate)

    # ---- the dispatch transaction, and the lint that backs it up -----------------------------------

    def record_dispatch(self, store, rec) -> Source:
        """THE dispatch transaction's harvest half: register the base, then write the record.

        One call, in this order. Registration first means a failed record write leaves a watched source
        with nothing to harvest yet (harmless and self-correcting), while the reverse leaves a record whose
        effort nobody watches — which is the failure `OBS-68` actually was. A caller physically cannot use
        this and forget the registry, and `lint` catches the callers that did not use it.
        """
        if not str(rec.base_instant).strip():
            raise BadInput(
                f"record {rec.todo_id!r} names no base instant, so there is nothing to watch. A dispatch "
                "with no base is not a dispatch (FD-2).")
        source = self.register(str(rec.base_instant), str(Path(rec.base_instant) / REGISTER_NAME))
        store.write(rec)
        return source

    def lint(self, store) -> list:
        """Every recorded base that no watched source covers, one violation per base.

        The other half of the registry's writer. A record written straight to the store — by a hand-rolled
        script, an older build, or a verb that grew its own path — is an effort being worked with nobody
        watching its register, and that is reported by base (the thing to act on) rather than by record.
        """
        registered = {_base_key(s.base) for s in self.sources()}
        records = list(store.all())
        bases = {_base_key(str(r.base_instant)) for r in records}
        out, seen = [], set()
        for rec in records:
            base = str(rec.base_instant)
            key = _base_key(base)
            if key in registered or key in seen:
                continue
            seen.add(key)
            covered = sorted(r.todo_id for r in records if _base_key(str(r.base_instant)) == key)
            out.append(Violation(
                path=base, rule=UNREGISTERED_BASE,
                detail=(f"{len(covered)} record(s) name base {base} and it is on no watched source: "
                        f"{', '.join(covered)}. A source that is not on the list cannot be reported as "
                        f"silent — OBS-68 hid 20 issues, one of them Critical, for ~4h that way. Clears "
                        f"when: the base is registered against {Path(base) / REGISTER_NAME}, which the "
                        f"dispatch transaction does by itself. Clears who: the coordinator that "
                        f"dispatched these records."),
                severity=VIOLATION))
        out.append(Violation(
            path=str(self.path), rule=POPULATION,
            detail=(f"examined {len(records)} record(s) over {len(bases)} base(s) against "
                    f"{len(registered)} watched source(s)"),
            severity=INFO))
        return out

    # ---- the register: population first, then the diff ---------------------------------------------

    def register_path(self, source) -> Path:
        """Where a source's register is NOW, resolved through `identity.resolve`.

        The registry stores the path a source was registered at, and `abort`/`complete` rename the base
        folder — so the recorded path goes stale on the day the effort ends, and `_base_key` making the
        *key* rename-tolerant did nothing for the *path*. `FI-17`: this module was the one that never
        adopted the resolver `reconcile` has always used, so a single renamed base exited 2 and took the
        whole tick with it. Resolution is on the full stable key with only `state` varying (`OI-16`).
        """
        path = Path(source.issues_path)
        if path.is_file():
            return path
        found = resolve(path.parent)               # may raise AmbiguousId — refused, never guessed
        if found is not None:
            return found / path.name
        return path

    def _read(self, source) -> str:
        path = self.register_path(source)
        if not path.is_file():
            raise BadInput(
                f"the register {source.issues_path} does not exist, and no rename of its base resolves to "
                f"one ({path} was the last place looked). An absent register is not an empty one — the "
                "first is a broken registration, the second is news.")
        return path.read_text()

    def _scan(self, source) -> tuple:
        """`(text, issues)` for one register, with the vacuity guard applied.

        The guard is the whole of property 2: content and no ids means the extractor is blind, and a blind
        extractor reporting "0 new" is a false pass. An empty register means there is nothing to find yet,
        which is news and not a fault — and so is a register the layout seed created that nobody has filed
        in yet (`unfiled`, which is a narrowing of this guard and not a hole in it).

        The text is returned beside the issues so a caller can say WHICH kind of nothing it found. Reading
        the file twice to answer that would be two reads of one register in one tick, and the second could
        disagree with the first.
        """
        text = self._read(source)
        issues = extract(text)
        if not issues and text.strip() and not unfiled(text, source.base):
            raise VacuousExtraction(
                f"{source.issues_path} has {len(text.strip().splitlines())} non-empty line(s) and yielded "
                f"ZERO issue ids. The extractor is blind to this register's shape (a heading depth or an "
                f"id form it does not match) — it is not looking at an empty register. Reporting '0 new' "
                f"here would be a false pass by the one mechanism that exists to catch false passes "
                f"(RCF-10). Clears when: the register's entries are headings whose first token is an id, "
                f"or the extractor learns this shape. Clears who: the owner of that register.")
        return text, issues

    def _issues(self, source) -> list:
        return self._scan(source)[1]

    def ids_found(self, source) -> int:
        """The POPULATION: how many ids the register holds, whatever the diff says.

        Never `len(new_issues(...))`. That collapse is the defect: the two numbers agree only on a first
        tick, and when they are one number a dead extractor is indistinguishable from a quiet effort.
        """
        return len(self._issues(self._lookup(source)))

    def _seen_path(self, source) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(source.base).name or "source")
        digest = hashlib.sha1(str(source.base).encode()).hexdigest()[:8]
        return self.seen_dir / f"{safe}-{digest}.tsv"

    def seen(self, source) -> list:
        """The ids this loop has already announced for a source. Empty list when it has no memory."""
        path = self._seen_path(self._lookup(source))
        if not path.is_file():
            return []
        out = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            ident, _, title = line.partition("\t")
            out.append(Issue(id=ident, title=title))
        return out

    def _record(self, source, issues) -> int:
        """Write the memory. Deduplicated by key, ALWAYS written — even when it records zero.

        An empty state file is memory; a missing one is not, and `RI-28..31` is what the difference costs.
        """
        keep, keys = [], set()
        for issue in issues:
            key = _key(issue)
            if key in keys:
                continue
            keys.add(key)
            keep.append(issue)
        atomic_write(self._seen_path(source), "".join(f"{i.id}\t{i.title}\n" for i in keep))
        return len(keep)

    def prime(self, source) -> int:
        """Adopt the register's current contents as already-seen. Returns the COUNT it recorded.

        It never returns the issues, and that is not a style choice: a prime that reported its ids is
        indistinguishable from a tick that found them, and every consumer downstream would announce a
        reset as news. *"A silent reset is worse"* — so the count is loud and the ids stay unreported.
        """
        src = self._lookup(source)
        recorded = self._record(src, self._issues(src))
        self._stamp(src)
        return recorded

    def new_issues(self, source) -> list:
        """The ids in the register that this loop has not announced yet, as a SET difference.

        `OBS-11`: a register kept in numeric order grows by one **in the middle** while the last heading is
        unchanged — the watcher announced `RI-5` three times and never saw `RI-8`/`RI-9` land. A count, a
        tail offset or a last-heading marker all reproduce that; only a set difference does not. Memory is
        the union of what it held and what it just saw, so an entry deleted from a register is not
        re-announced if it comes back.
        """
        src = self._lookup(source)
        issues = self._issues(src)
        remembered = self.seen(src)
        known = {_key(i) for i in remembered}
        new = [i for i in issues if _key(i) not in known]
        self._record(src, remembered + new)
        self._stamp(src)
        return new

    # ---- the cadence trigger ------------------------------------------------------------------------

    def stale(self, now: str, max_age_s: int, live_work: bool) -> list:
        """Watched sources nobody has harvested inside the window — but ONLY while work is live.

        `live_work` is a parameter and not a nicety. An alarm nobody can act on trains people to ignore
        it, and *this* alarm's action is "go look at a register", which is not an action when the fleet is
        idle. Reported for a live fleet, silent for a quiet one.
        """
        if not live_work:
            return []
        cutoff = _parse(now, "now") - timedelta(seconds=max(0, int(max_age_s)))
        return [s for s in self.sources()
                if _parse(s.last_run or s.registered_at, f"{s.base} last_run") < cutoff]

    # ---- the report ---------------------------------------------------------------------------------

    def run(self, source) -> list:
        """Harvest one source: its population, its new ids, and every warning the tick earned.

        **One source that cannot be read degrades to a reported ROW; it never ends the tick.** `FI-17` was
        reported as a rename, and the rename is now resolved — but the important half is this one, because
        the next cause of an unreadable register will not be a rename (a permission, a deleted folder, a
        register that is a directory, two instants sharing a stable key). A tick that dies on its first bad
        source reports NOTHING about the good ones, which is `OBS-49`'s failure with an exception in place
        of a narrowed scope.
        """
        src = self._lookup(source)
        had_memory = self._seen_path(src).is_file()
        try:
            text, issues = self._scan(src)
        except VacuousExtraction as exc:
            return [Row(kind=VACUOUS, subject=src.base, detail=str(exc), severity=VIOLATION,
                        clears_when="the register's shape or the extractor is fixed",
                        clears_who="the owner of that register",
                        ids_found=0, new_count=0)]
        except (FleetError, OSError, UnicodeDecodeError) as exc:
            # `SI-16`. The ROOT base is SYNTHETIC — `identity.ROOT_BASE` is the string `00000000` and there
            # is no folder anywhere that is the root, so `Path("00000000")/ISSUES.md` can never resolve. A
            # dispatch from the root registers it anyway (`record_dispatch` takes the base verbatim), and
            # every tick afterwards reported a VIOLATION that no action could ever clear: measured as
            # permanent from the first `resume --base 00000000` onward, on all 27 verbs via `_cadence`.
            #
            # That is the unclearable alarm this module's own comments cite `OBS-21`/`FI-18` for avoiding,
            # and the parent met it from the other side — `FI-30a` fixed E6's CASE to admit exit 1 and pin
            # the kind, which left the product behaviour intact behind a passing test.
            #
            # An INFO row, not a muted violation, and only for the root: there is nothing to be wrong about
            # when the register was never supposed to exist. Any OTHER base that will not resolve is still a
            # violation, because there something really is broken — a real effort nobody can read.
            if str(src.base) == ROOT_BASE:
                return [Row(
                    kind=SOURCE, subject=src.base,
                    detail=(f"the root base {ROOT_BASE!r} is synthetic and has no register of its own, so "
                            f"there is nothing to harvest from it. Recorded so the source is not silently "
                            f"absent from the tick, and INFO rather than a violation because no action "
                            f"could clear it: {src.issues_path} is a path no rename can make exist."),
                    severity=INFO, ids_found=0, new_count=0)]
            return [Row(
                kind=UNREADABLE, subject=src.base,
                detail=(f"{src.issues_path} could not be read, so this source contributed nothing to the "
                        f"tick: {exc} Reported as a row and not raised: the rest of the tick is still "
                        f"worth having, and a tick that dies on one source reports nothing about the "
                        f"others."),
                severity=VIOLATION,
                clears_when=(f"a readable register exists at {src.issues_path}, or the source is "
                             f"re-registered against where it lives now"),
                clears_who="the owner of that effort, or the coordinator that registered it",
                ids_found=0, new_count=0)]
        new = self.new_issues(src)
        rows = [Row(
            kind=SOURCE, subject=src.base,
            detail=(f"{len(issues)} id(s) in {src.issues_path}, {len(new)} new"
                    + (f": {', '.join(i.id for i in new)}" if new else
                       " — this source produced nothing, which is the observation and not an omission")),
            severity=INFO, ids_found=len(issues), new_count=len(new))]
        if not issues and unfiled(text, src.base):
            rows.append(Row(
                kind=NO_ISSUES_FILED, subject=src.base,
                detail=(f"{src.issues_path} holds nothing but the header fleet.layout seeded, so there are "
                        f"no issues filed yet. Reported as info, not failed: an empty-of-issues register is "
                        f"not a broken extractor, and a brand-new effort that is RED on every tick until "
                        f"somebody files its first issue is the always-red alarm OBS-21 avoided (FI-18)."),
                severity=INFO, ids_found=0, new_count=0))
        elif not issues:
            rows.append(Row(
                kind=EMPTY_REGISTER, subject=src.base,
                detail=(f"{src.issues_path} is empty and legitimately yielded no ids. Reported, not "
                        "failed: an empty register is news, and a check that goes RED for it is the "
                        "always-red alarm OBS-21 avoided."),
                severity=INFO, ids_found=0, new_count=0))
        if not had_memory:
            rows.append(Row(
                kind=NO_MEMORY, subject=src.base,
                detail=(f"this tick had NO state file for {src.base}, so its diff had no memory and "
                        f"{len(new)} of {len(issues)} id(s) read as new. RI-28..31 were harvested exactly "
                        f"this way, on the first tick of the loop that wrote the lesson. The memory has "
                        f"now been written, so the NEXT tick is trustworthy — this one is not."),
                severity=VIOLATION,
                clears_when="the next tick runs against the state file this one wrote",
                clears_who="this loop, on its next tick",
                ids_found=len(issues), new_count=len(new)))
        return rows

    def report(self, now: str = None, max_age_s: int = DEFAULT_MAX_AGE_S,
               live_work: bool = False) -> list:
        """The whole tick: every source, every warning, the cadence, and the population it examined.

        Staleness is computed BEFORE the runs, because the runs stamp `last_run` — asking the cadence
        question after answering it is how a cadence check comes to pass forever.

        The population row is last and unconditional: a checker whose scope narrows silently reads as a
        pass (`OBS-49`), and a registry that is legitimately empty is reported rather than RED.
        """
        now = now or self._clock()
        sources = self.sources()
        overdue = self.stale(now, max_age_s, live_work)

        rows = []
        for src in sources:
            rows.extend(self.run(src))
        for src in overdue:
            since = src.last_run or src.registered_at
            rows.append(Row(
                kind=STALE, subject=src.base,
                detail=(f"{src.base} was last harvested at {since} and it is now {now}, past the "
                        f"{max_age_s}s window, while work is live. A register nobody reads is the silent "
                        f"source OBS-68 was."),
                severity=VIOLATION,
                clears_when=f"a harvest tick runs against {src.issues_path}",
                clears_who="the coordinator of that effort, or this loop's own tick"))
        rows.append(Row(
            kind=POPULATION, subject=str(self.path),
            detail=(f"examined {len(sources)} watched source(s) at {now}, {len(overdue)} of them past a "
                    f"{max_age_s}s cadence window (live_work={live_work}), from {self.path}"),
            severity=INFO))
        return rows

    # ---- repetition — UC-1's actual ask ------------------------------------------------------------

    def repetitions(self, corpus: dict, min_count: int = 2) -> list:
        """Subjects that appear at least `min_count` times across a corpus, each instance cited.

        **The threshold is two.** *"Two instances is a pattern; making the brief demand it means review no
        longer has to be the first line of defence."* Three fires only after the third time, by which
        point the routine has been paid for twice and the observation is a post-mortem.

        `corpus` maps a citation key (a path, a register, a section) to its text; `where` carries
        `<key>:<line>` per instance, so two instances inside one document are two distinct citations. The
        subject is the NORMALISED line — leading id, heading marker, bullet, emphasis and case removed —
        because the whole point is that `RI-5 flaky rebase` and `OI-9 flaky rebase` are one routine.
        """
        if min_count < 2:
            raise BadInput(
                f"min_count={min_count!r} is below two, and a 'repetition' of one instance is an "
                "observation. Two instances is the corpus's own bar.")
        counts, where = {}, {}
        for key in sorted(corpus):
            for lineno, line in enumerate(str(corpus[key]).splitlines(), start=1):
                subject = _subject(line)
                if subject is None:
                    continue
                counts[subject] = counts.get(subject, 0) + 1
                where.setdefault(subject, []).append(f"{key}:{lineno}")
        out = [Repetition(subject=subject, count=count, where=where[subject])
               for subject, count in counts.items() if count >= min_count]
        return sorted(out, key=lambda r: (-r.count, r.subject))


def _subject(line: str) -> str:
    """One line as a repetition subject, or `None` when it is not one.

    Normalisation is the mechanism: two renderings of one routine must be one subject, or every count is
    one and the check never fires.
    """
    text = line.strip()
    if not text:
        return None
    heading = _HEADING.match(line)
    if heading is not None:
        text = heading.group("rest").strip()
    text = _BULLET.sub("", text)
    text = _LEADING_ID.sub("", text)
    subject = _norm(text)
    if len(subject) < MIN_SUBJECT_CHARS:
        return None
    return subject
