"""Records and declarations — the machine state.

Two stores, both JSON, both written only through this module:

  <home>/records/<todo_id>.json   one dispatch record, carrying schema_version
  <instant>/.fleet/declare.json   the instant's own declarations (phase, parked question)

Why a schema version with no legacy to migrate: OBS-9 stated the lesson perfectly — a fix that changes
how state is INTERPRETED needs a migration path for state that already exists — and W2-5 is what
happened when the very next field shipped four hours later without one. A version makes "this record
predates field X" a fact the store knows rather than an inference each reader re-derives.

Why declarations are not in the markdown: RCF-9. A worker declared `Phase: AWAITING-CI` exactly as its
brief worded it, a leading `## ` defeated the consumer's regex, the declaration was a silent no-op, and
at a WIP cap of 1 that holds the whole effort's only dev slot for the length of a CI queue.
"""
import json
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from fleet.atomic import atomic_write
from fleet.errors import AmbiguousId, BadInput

SCHEMA_VERSION = 1


@dataclass
class Record:
    todo_id: str
    child_instant: str
    base_instant: str
    slot: str
    tmux: str
    profile: str
    golden: str
    lineage_base: str
    title: str
    dispatched_at: str
    #: `SI-32`. The GIT lineage, as `repo=sha,repo=sha` — distinct from `base_instant`, which is the
    #: INSTANT lineage (the 8-digit base in the folder name). Two different lineages; before SI-32 only the
    #: instant one was populated and this field was written empty at every call site.
    #:
    #: It is the SINGLE authority for "what do I build on top of". `OI-1` was two prose authorities
    #: disagreeing — a seed rendered once per wave said one base, a per-milestone charter said another — and
    #: the worker had to decide which was real. Rendered into both documents from here, they cannot.
    #: `SI-34`. WHY a refusing rule was overridden, persisted. An override is an AUDIT EVENT: somebody
    #: decided a guard was wrong for this one dispatch, and the only record of that judgement used to be the
    #: sentence the guard printed to a terminal. `F7` requires "the reason is in the record" and it was not:
    #: the value reached `guards.Context` and was never written anywhere. A refusal that was overridden with
    #: no durable reason is indistinguishable, a week later, from a rule that never fired.
    override_reason: str = ""
    lineage_mode: str = ""          # "code" | "analysis" | "" (no git lineage recorded)
    #: Each repo's HEAD at DISPATCH time, before the worker touched anything, as `repo=sha,...`. What the
    #: slot's prebuilt native artifacts were built from, and therefore the only way to answer "has the source
    #: moved out from under the .so files".
    golden_base: str = ""
    #: `SI-27`: WHICH milestone this instant was dispatched for. Optional because a dispatch need not be
    #: about a milestone (a coordinator or a compaction instant is dispatched for a role). Without it
    #: `board` could show N workers and `roadmap` N milestones with nothing connecting them.
    milestone: str | None = None
    #: `G1`. Which fleet ROOT this dispatch belongs to, resolved and absolute.
    #:
    #: Defaulted, and `SCHEMA_VERSION` deliberately NOT bumped: `from_json` refuses both a version
    #: mismatch and an unknown field, so a bump would refuse all 75 records in the live store on the first
    #: read — a migration nobody asked for, to add a field that has a default. An EMPTY root means
    #: "written before isolation", which is NOT MEASURED and never a mismatch: reading absence as an
    #: answer is `FI-417`, where a grep that could not see 15 issue sections reported zero and the zero
    #: was believed.
    root: str = ""
    #: `SI-59`. Which tmux SERVER this session was created on, by socket name. The record already carried
    #: `tmux` — a session NAME — and a name is not an address: every later reader resolved the server from
    #: whatever `$FLEET_TMUX_SOCKET` happened to be, so a record could be read from the wrong server and
    #: answered about anyway. Measured: `fleet close` against a live worker from a shell pointed at another
    #: server returned rc=0, reported `closed dt-<name>`, stamped `closed_at` and disarmed the monitor,
    #: while the session was still running.
    #:
    #: Defaulted and `SCHEMA_VERSION` NOT bumped, for the reason `root` states one field above: a bump
    #: would refuse every record already in the live store. EMPTY means "written before this field", which
    #: is NOT MEASURED — never "the default server" — because reading absence as an answer is `FI-417`,
    #: and the two records this was found on are exactly the ones that carry no value.
    tmux_socket: str = ""
    launched_at: str | None = None
    gate_verdict: str | None = None
    harvested_at: str | None = None
    closed_at: str | None = None
    schema_version: int = SCHEMA_VERSION

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> "Record":
        version = d.get("schema_version")
        if version != SCHEMA_VERSION:
            raise BadInput(
                f"record {d.get('todo_id')!r} has schema_version={version!r}, this build knows "
                f"{SCHEMA_VERSION}. Refusing to interpret it. There is no legacy tolerance by design "
                "(FD-1); prior state is preserved under evidence/00-preserved-state/."
            )
        known = {f.name for f in fields(cls)}
        unknown = set(d) - known
        if unknown:
            raise BadInput(f"record {d.get('todo_id')!r} has unknown field(s): {sorted(unknown)}")
        return cls(**d)


class Store:
    """The ONE writer. Readers are pure — `read` never mutates, so a reporting path cannot back-fill a
    field as a side effect of being looked at (the predecessor's `health` stamped `launched_at` during a
    read, which made a report a writer)."""

    def __init__(self, home: Path):
        self.home = Path(home)
        self.records = self.home / "records"

    def write(self, rec: Record) -> Path:
        # Through the ONE atomic write (FI-20). A reader never sees a half-written record, and — the half
        # eight hand-rolled copies of this line got wrong — two concurrent writers of one record cannot
        # share a staging path and publish each other's bytes.
        return atomic_write(self.records / f"{rec.todo_id}.json",
                            json.dumps(rec.to_json(), indent=2, ensure_ascii=False))

    def read(self, todo_id: str) -> Record:
        path = self.records / f"{todo_id}.json"
        if not path.is_file():
            raise BadInput(f"no record {todo_id!r} in {self.records}")
        return Record.from_json(_read_json(path, "record"))

    def all(self) -> list[Record]:
        if not self.records.is_dir():
            return []
        return [Record.from_json(_read_json(p, "record"))
                for p in sorted(self.records.glob("*.json"))]

    def resolve_id(self, partial: str) -> str:
        if (self.records / f"{partial}.json").is_file():
            return partial
        hits = [p.stem for p in sorted(self.records.glob("*.json")) if partial in p.stem]
        if not hits:
            raise BadInput(f"no record matching {partial!r}")
        if len(hits) > 1:
            raise AmbiguousId(f"{partial!r} matches {len(hits)}: {', '.join(hits)}. Refusing to guess.")
        return hits[0]


def _read_json(path: Path, what: str) -> dict:
    """Parse a store file, or refuse NAMING IT.  `SI-35`.

    Three call sites used a bare `json.loads` and one truncated file therefore raised `JSONDecodeError` out of
    `Store.all()` — which every view calls, so `board`, `status` and `reap` all died with a traceback instead of
    telling the operator which file to look at. `§O1` found it. These are the verbs you run when the store is
    already in a state you do not understand, so a traceback is the least useful thing they can do.

    Refused, never skipped. A record that cannot be parsed is not absent: pretending it is would make a
    dispatched worker invisible to the cap and to the board, which is strictly worse than stopping.
    """
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise BadInput(
            f"the {what} at {path} cannot be read ({exc}). It is refused rather than skipped: a record that "
            f"cannot be parsed is not the same as one that is absent, and treating it as absent would hide a "
            f"dispatched worker from the cap and from the board. Inspect or move the file by hand.") from exc


class Declarations:
    """An instant's own declarations. A declaration is a VERB's product, never prose, and `set_phase`
    returns what a consumer now reads — so the declarer cannot believe a declaration landed when it did
    not. Nothing here opens a `.md` file."""

    def __init__(self, instant: Path):
        self.dir = Path(instant) / ".fleet"
        self.path = self.dir / "declare.json"

    def _load(self) -> dict:
        if not self.path.is_file():
            return {}
        return _read_json(self.path, "declarations file")

    def _save(self, data: dict) -> None:
        atomic_write(self.path, json.dumps(data, indent=2, ensure_ascii=False))

    def phase(self) -> str | None:
        return self._load().get("phase")

    def set_phase(self, phase: str | None, now=None) -> str | None:
        data = self._load()
        if phase is None:
            data.pop("phase", None)
            data.pop("at", None)
        else:
            data["phase"] = phase
            #: `i45`. The MOMENT of the claim, so a consumer can compute how long it has stood — a
            #: declaration is a claim made at ONE instant, and without a stamp nothing can ever say a
            #: wait has gone stale. `now` is injectable because `Declarations` has no clock of its own.
            data["at"] = now if now is not None else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._save(data)
        return Declarations(self.dir.parent).phase()      # re-read THROUGH the consumer

    def declared_at(self) -> str | None:
        """When the phase was declared, or `None` for a declaration written before this field existed.

        `None` is NOT MEASURED: no age can be computed from it, so no staleness may ever be claimed.
        """
        return self._load().get("at")

    def watchers(self) -> str | None:
        """What was armed to wake this instant when it last declared a gated phase, or `None`.

        `FI-255`. The claim used to store `{"phase": "awaiting-ci"}` and nothing else, so a self-waking
        worker and one stopped for 1h28m were indistinguishable in the RECORD as well as on the board —
        every field was invariant across the event they were supposed to detect.
        """
        return self._load().get("watchers")

    def set_watchers(self, watchers: str | None) -> None:
        data = self._load()
        if watchers is None:
            #: Cleared, never left standing: a value from an EARLIER claim read as evidence about THIS one
            #: is the same lie in slower form, and the phase it described may since have changed.
            data.pop("watchers", None)
        else:
            data["watchers"] = watchers
        self._save(data)

    def parked(self) -> str | None:
        return self._load().get("parked")

    def park(self, question: str) -> None:
        if not question.strip():
            raise BadInput("a parked decision needs a question; an empty park is not a park")
        data = self._load(); data["parked"] = question; self._save(data)

    def unpark(self) -> None:
        data = self._load(); data.pop("parked", None); self._save(data)
