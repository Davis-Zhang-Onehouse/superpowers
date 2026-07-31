"""Structured review rounds in, markdown out — and the markdown is never read back in.

**The ledger is `<instant>/.fleet/review.json`. `REVIEW.md` is a VIEW of it.** That single sentence is
why this module exists. In the predecessor the markdown was the *input*: a gate regex over idiomatic
markdown blocked two genuinely-READY workers in a row (`OBS-15`, `OBS-19`) — one because it wrote its
verdict in bold, one because it disambiguated a two-round summary heading. That is the worst direction
for a gate to be wrong in. It blocks correct work, and the diagnostic blamed a *missing* line, so the
reader went hunting for a problem that was not there. Patching the regex would have left the class
intact; reading structured state instead makes the class unreachable.

So: `gate()` opens exactly one file, `review.json`, and `render()` is the only writer of `REVIEW.md`. A
hand edit to the view is discarded by the next render and cannot move a decision. Nothing here reads a
`.md` file at all (AC-2).

Three further properties are requirements rather than implementation details:

1. **Scopes accumulate ACROSS rounds** (`OBS-30`). A worker fully reviewed in round 1 and re-checked
   narrowly in round 2 has been fully reviewed. Judging coverage on the newest round alone would have
   rejected a correctly-reviewed worker — and that defect was found by pointing the tool at production
   instants *after* every fixture passed, which is the whole argument for the production sweep.
2. **"Cannot decide" is not "decided no"** (exit 2 vs exit 1). An empty ledger fails *closed*, but it
   fails closed as UNDECIDABLE, with its own guard id, its own exit code and its own sentence, because
   the two states send a reader to two different problems.
3. **The verdict of the newest round governs, and the ledger is the arbiter.** A round with no findings
   is *flagged* thin and still counted: "a verdict with no visible basis must not read identically to an
   evidenced one" — but an advisory that could veto a verdict would be a second decision procedure, and
   two decision procedures for one rule is how they drift apart.
"""
import json
import time
from dataclasses import dataclass
from pathlib import Path

from fleet import EXIT_ATTENTION, EXIT_BAD_INPUT, EXIT_OK
from fleet.atomic import atomic_write, held_for_update
from fleet.errors import BadInput, InstantNameError
from fleet.guards import Verdict
from fleet.identity import InstantName, resolve
from fleet.reconcile import TERMINAL_FOLDER_STATES

#: The reviewer's verdict for a round. The whole domain; a value outside it is refused, not coerced.
VERDICTS = ("READY", "READY-WITH-FIXES", "NOT-READY")

#: What a round looked at. `all` is not a fourth kind of look — it is the three atoms at once, which is
#: what lets a single `all` round satisfy `require_scope="all"` for every later narrow round.
ATOMIC_SCOPES = ("format", "alignment", "code")
ALL = "all"
SCOPES = ATOMIC_SCOPES + (ALL,)

#: Finding severities, worst first. Only the first two can block a gate.
SEVERITIES = ("Critical", "Important", "Minor", "Nit")
BLOCKING_SEVERITIES = ("Critical", "Important")

#: A finding's disposition. `wont-fix` is a recorded decision and not a loophole, because `action` is
#: required to be non-empty on every finding — declining a Critical therefore costs a written reason.
OPEN = "open"
FINDING_STATUSES = (OPEN, "applied", "wont-fix")

#: Guard ids. These are the machine-readable part of a verdict: a caller distinguishes "undecidable"
#: from "decided no" by comparing these, never by grepping the sentence. `RCF-9` is what grepping the
#: sentence costs.
GUARD_UNDECIDABLE = "review-undecidable"
GUARD_VERDICT = "review-verdict"
GUARD_SCOPE = "review-scope"
GUARD_HARVEST = "review-harvest"

SCHEMA_VERSION = 1

REVIEWER = "the reviewing instant"


@dataclass(frozen=True)
class Finding:
    """One reviewed observation. Every field is required and non-empty: a finding with no location is a
    feeling, and a finding with no action asks the reader to invent the remedy."""

    id: str
    severity: str
    status: str
    location: str
    finding: str
    action: str

    def __post_init__(self):
        for field, value, ok in (
            ("id", self.id, bool(str(self.id).strip())),
            ("severity", self.severity, self.severity in SEVERITIES),
            ("status", self.status, self.status in FINDING_STATUSES),
            ("location", self.location, bool(str(self.location).strip())),
            ("finding", self.finding, bool(str(self.finding).strip())),
            ("action", self.action, bool(str(self.action).strip())),
        ):
            if not ok:
                raise BadInput(
                    f"finding {field}={value!r} is outside its declared domain. severity in "
                    f"{SEVERITIES}, status in {FINDING_STATUSES}, and id/location/finding/action are "
                    "each non-empty — an unactionable finding is not a finding."
                )

    def blocking(self) -> bool:
        return self.severity in BLOCKING_SEVERITIES

    def to_json(self) -> dict:
        return {"id": self.id, "severity": self.severity, "status": self.status,
                "location": self.location, "finding": self.finding, "action": self.action}

    @classmethod
    def from_json(cls, d: dict) -> "Finding":
        return cls(id=d["id"], severity=d["severity"], status=d["status"],
                   location=d["location"], finding=d["finding"], action=d["action"])


@dataclass(frozen=True)
class Round:
    """One review pass: what it looked at, what it concluded, what it saw."""

    number: int
    scope: str
    verdict: str
    findings: list
    at: str

    def thin(self) -> bool:
        """True when the round records a verdict with no visible basis.

        `scope` alone is a claim about what was looked at, not evidence of having looked; the findings
        are the evidence. A thin round is reported and still counted (see the module docstring).
        """
        return not self.findings

    def to_json(self) -> dict:
        return {"number": self.number, "scope": self.scope, "verdict": self.verdict, "at": self.at,
                "findings": [f.to_json() for f in self.findings]}

    @classmethod
    def from_json(cls, d: dict) -> "Round":
        return cls(number=d["number"], scope=d["scope"], verdict=d["verdict"], at=d["at"],
                   findings=[Finding.from_json(f) for f in d["findings"]])


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Review:
    """The review ledger for one instant, and the gate verdict derived from it.

    The clock is injected so a suite can compare two renders byte-for-byte without freezing time
    (`NFR2-3`): the only timestamps in the view come from the ledger, never from the render.
    """

    def __init__(self, instant, now=_utc_now):
        self.instant = Path(instant)
        self._now = now

    # --- where things live. Both follow the instant's own rename, because the recorded path is the
    # --- thing that goes stale and a folder is never wrong about itself.

    def _current(self) -> Path:
        found = resolve(self.instant)
        return found if found is not None else self.instant

    def _ledger_path(self) -> Path:
        return self._current() / ".fleet" / "review.json"

    def view_path(self) -> Path:
        return self._current() / "REVIEW.md"

    # --- the ledger ------------------------------------------------------------------------------

    def rounds(self) -> list:
        path = self._ledger_path()
        if not path.is_file():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise BadInput(
                f"{path} has schema_version={version!r}; this build knows {SCHEMA_VERSION}. Refusing "
                "to interpret it — there is no legacy tolerance by design (FD-1)."
            )
        return [Round.from_json(entry) for entry in data.get("rounds", [])]

    def add_round(self, scope: str, verdict: str, findings: list) -> Round:
        if scope not in SCOPES:
            raise BadInput(f"scope={scope!r} is outside {SCOPES}; a scope nobody defined can neither "
                           "satisfy nor fail a gate, so it is refused rather than coerced.")
        if verdict not in VERDICTS:
            raise BadInput(f"verdict={verdict!r} is outside {VERDICTS}. Case and spelling are part of "
                           "the domain: this value is compared, never parsed out of prose.")
        findings = list(findings)
        ids = [f.id for f in findings]
        if len(set(ids)) != len(ids):
            raise BadInput(f"round findings repeat an id within one round: {sorted(ids)}. A later "
                           "ROUND restates a finding to change its status; a round does not argue "
                           "with itself.")
        # FI-30c: read, number, append and write as ONE step. The round NUMBER is derived from the
        # existing ledger, so this was worse than a lost append — two concurrent rounds each read n
        # rounds, each called itself n+1, and the survivor's numbering silently skipped. Measured before
        # this: 6 concurrent rounds left 1, in every one of 8 iterations.
        with held_for_update(self._ledger_path()):
            existing = self.rounds()
            made = Round(number=len(existing) + 1, scope=scope, verdict=verdict, findings=findings,
                         at=self._now())
            self._save(existing + [made])
        return made

    def _save(self, entries: list) -> None:
        payload = {"schema_version": SCHEMA_VERSION, "rounds": [e.to_json() for e in entries]}
        # Through the ONE atomic write (FI-20): a reader never sees half a ledger, and two writers cannot
        # share a staging path. This alone still does not make the surrounding read-modify-write
        # indivisible — `add_round` holds `atomic.held_for_update` for that (`FI-30c`), which is why this
        # method may stay a plain publish and readers never take a lock.
        atomic_write(self._ledger_path(), json.dumps(payload, indent=2, ensure_ascii=False))

    # --- derived facts ----------------------------------------------------------------------------

    def scopes_covered(self) -> set:
        """Every scope any round has covered — the union, not the newest round's.

        `OBS-30`: a worker reviewed in full in round 1 and re-checked narrowly in round 2 has been
        reviewed in full. Reading only the newest round rejects it, which is a false refusal of correct
        work. Three narrow rounds that together cover the atoms also cover `all`, for the same reason.
        """
        covered = set()
        for a_round in self.rounds():
            covered.add(a_round.scope)
            if a_round.scope == ALL:
                covered.update(ATOMIC_SCOPES)
        if set(ATOMIC_SCOPES) <= covered:
            covered.add(ALL)
        return covered

    def latest_findings(self) -> list:
        """One entry per finding id, carrying the status the MOST RECENT round gave it.

        Restating a finding is how a later round resolves it. Keying on the first-seen status instead
        would make a round-1 Critical unclearable except by the reviewer who never raised it.
        """
        latest = {}
        for a_round in self.rounds():
            for item in a_round.findings:
                latest[item.id] = item
        return list(latest.values())

    def open_blocking(self) -> list:
        return [f for f in self.latest_findings() if f.status == OPEN and f.blocking()]

    def advisories(self) -> list:
        """Non-vetoing observations about the ledger itself. Advisory by construction: an advisory that
        could change a verdict would be a second decision procedure for one rule."""
        out = []
        for a_round in self.rounds():
            if a_round.thin():
                out.append(
                    f"THIN LEDGER — round {a_round.number} (scope {a_round.scope}) records verdict "
                    f"{a_round.verdict} with no findings. A verdict with no visible basis must not "
                    "read identically to an evidenced one; the ledger remains the arbiter."
                )
        return out

    def population(self) -> dict:
        """The population this gate examined (`FR2-8.3`). A report that does not say what it looked at
        cannot be told apart from one that looked at nothing."""
        entries = self.rounds()
        return {
            "rounds": len(entries),
            "round_scopes": [e.scope for e in entries],
            "scopes_covered": sorted(self.scopes_covered()),
            "findings": sum(len(e.findings) for e in entries),
            "open_blocking": [f.id for f in self.open_blocking()],
            "ledger": str(self._ledger_path()),
        }

    def _population_row(self) -> str:
        pop = self.population()
        return (f"population: {pop['rounds']} round(s) [{', '.join(pop['round_scopes']) or 'none'}]; "
                f"scopes covered: {', '.join(pop['scopes_covered']) or 'none'}; "
                f"{pop['findings']} finding(s), {len(pop['open_blocking'])} open blocking; "
                f"ledger {pop['ledger']}")

    # --- the gate ---------------------------------------------------------------------------------

    def gate(self, require_scope=None, harvest: bool = False) -> Verdict:
        """May this instant proceed? Decided from `review.json` and the folder name — never from
        `REVIEW.md`, which this method does not open."""
        if require_scope is not None and require_scope not in SCOPES:
            raise BadInput(f"require_scope={require_scope!r} is outside {SCOPES}.")
        ledger = self.rounds()
        population = self._population_row()
        advisory = "".join(f" advisory: {note}" for note in self.advisories())

        if not ledger:
            # UNDECIDABLE, not NOT-READY. Both fail closed; they are different exit codes because they
            # are different problems, and sending a reader to the wrong one is the cost.
            return Verdict(
                allowed=False,
                guard=GUARD_UNDECIDABLE,
                reason=("UNDECIDABLE: no review round has been recorded, so this gate cannot decide. "
                        "That is not the same as deciding against it — nothing has been judged. "
                        f"Failing closed. {population}"),
                clears_when="a review round is recorded in the ledger (`review add-round <scope> ...`)",
                clears_who=REVIEWER,
                blocker="no review round exists",
            )

        newest = ledger[-1]

        if require_scope is not None and require_scope not in self.scopes_covered():
            missing = sorted(set(ATOMIC_SCOPES if require_scope == ALL else (require_scope,))
                             - self.scopes_covered())
            return Verdict(
                allowed=False,
                guard=GUARD_SCOPE,
                reason=(f"required scope {require_scope!r} is not covered by any round. Covered across "
                        f"all {len(ledger)} round(s): {', '.join(sorted(self.scopes_covered()))}; "
                        f"missing: {', '.join(missing)}. {population}{advisory}"),
                clears_when=f"a round covering {', '.join(missing)} is recorded",
                clears_who=REVIEWER,
                blocker=f"scope not covered: {', '.join(missing)}",
            )

        if newest.verdict == "NOT-READY":
            open_ids = ", ".join(f.id for f in self.open_blocking()) or "none recorded"
            return Verdict(
                allowed=False,
                guard=GUARD_VERDICT,
                reason=(f"round {newest.number} (scope {newest.scope}) recorded verdict NOT-READY at "
                        f"{newest.at}; open blocking findings: {open_ids}. {population}{advisory}"),
                clears_when="the findings are addressed and a later round records READY or "
                            "READY-WITH-FIXES",
                clears_who=REVIEWER,
                blocker=f"round {newest.number}: NOT-READY",
            )

        blocking = self.open_blocking()
        if blocking:
            named = ", ".join(f"{f.id} ({f.severity}, {f.location})" for f in blocking)
            return Verdict(
                allowed=False,
                guard=GUARD_VERDICT,
                reason=(f"round {newest.number} (scope {newest.scope}) recorded {newest.verdict}, but "
                        f"{len(blocking)} open blocking finding(s) remain of severity "
                        f"{'/'.join(BLOCKING_SEVERITIES)}: {named}. {population}{advisory}"),
                clears_when="each finding is recorded applied or wont-fix (with its reason) in a later "
                            "round",
                clears_who=REVIEWER,
                blocker=named,
            )

        if harvest:
            refusal = self._harvest_refusal(population, advisory)
            if refusal is not None:
                return refusal

        return Verdict(
            allowed=True,
            guard=GUARD_VERDICT,
            reason=(f"round {newest.number} (scope {newest.scope}) recorded {newest.verdict} at "
                    f"{newest.at} with 0 open blocking findings. {population}{advisory}"),
        )

    def _harvest_refusal(self, population: str, advisory: str):
        """Harvest needs TWO completion signals: this gate AND the instant's own folder rename.

        A report file is not a completion signal — a worker can write a document about being finished
        without being finished, and the predecessor believed several who did. The rename is the signal a
        worker cannot produce by writing prose, so harvest requires both or neither.
        """
        current = self._current()
        try:
            state = InstantName.parse(current.name).state
        except InstantNameError:
            return Verdict(
                allowed=False,
                guard=GUARD_HARVEST,
                reason=(f"harvest cannot confirm the second completion signal: {current.name!r} is not "
                        f"a grammatical instant name, so it has no state field to read. {population}"
                        f"{advisory}"),
                clears_when="the instant folder carries a five-field name ending in a terminal state",
                clears_who=REVIEWER,
                blocker=f"ungrammatical folder name: {current.name}",
            )
        if state in TERMINAL_FOLDER_STATES:
            return None
        return Verdict(
            allowed=False,
            guard=GUARD_HARVEST,
            reason=(f"harvest needs TWO completion signals: the gate verdict AND the instant's own "
                    f"folder rename. The gate passes, but the folder is still `-{state}-` "
                    f"({current.name}) — a report file is not a completion signal. {population}"
                    f"{advisory}"),
            clears_when=f"the instant renames itself to one of {TERMINAL_FOLDER_STATES}",
            clears_who=REVIEWER,
            blocker=f"folder state is `{state}`, not one of {TERMINAL_FOLDER_STATES}",
        )

    # --- the view ---------------------------------------------------------------------------------

    def render(self) -> str:
        """Regenerate `REVIEW.md` from the ledger and return exactly what was written.

        The ONLY writer of that file, and a full regeneration every time: appending would make the file
        a history whose newest section a reader has to find, and a derived view is regenerated, never
        accumulated (`NFR2-10`). Every timestamp comes from the ledger, so two renders of one ledger
        are byte-identical.
        """
        markdown = self._markdown()
        path = self.view_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            handle.write(markdown)
        return markdown

    def _markdown(self) -> str:
        current = self._current()
        verdict = self.gate()
        lines = [
            f"# REVIEW — {current.name}",
            "",
            "<!-- GENERATED from .fleet/review.json. This file is a VIEW: it is regenerated in full on",
            "     every render, hand edits are discarded, and NOTHING reads it for a control signal.",
            "     Two READY workers were once blocked by a regex over prose exactly like this. -->",
            "",
            f"**Gate:** {'ALLOWED' if verdict.allowed else 'REFUSED'} (`{verdict.guard}`)",
            "",
            verdict.reason,
            "",
        ]
        if verdict.blocker:
            lines += [f"**Blocker:** {verdict.blocker}", ""]
        if verdict.clears_when:
            lines += [f"**Clears when:** {verdict.clears_when} · **Cleared by:** {verdict.clears_who}",
                      ""]
        entries = self.rounds()
        if not entries:
            lines += ["_No round has been recorded._", ""]
        for entry in entries:
            lines += [
                f"## Round {entry.number} — scope `{entry.scope}` — verdict `{entry.verdict}` — "
                f"{entry.at}",
                "",
            ]
            if entry.findings:
                lines += ["| id | severity | status | location | finding | action |",
                          "|---|---|---|---|---|---|"]
                for item in entry.findings:
                    lines.append("| " + " | ".join(_cell(v) for v in (
                        item.id, item.severity, item.status, item.location, item.finding, item.action
                    )) + " |")
            else:
                lines.append("_No findings recorded in this round._")
            lines.append("")
        return "\n".join(lines) + "\n"


def _cell(value: str) -> str:
    """A table cell that cannot break the table. Pipes are escaped and newlines folded, because a
    finding is free text and a broken table is a view nobody trusts."""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def exit_code_for(verdict: Verdict) -> int:
    """The registered exit code for a gate verdict — defined here so no caller re-derives it.

    UNDECIDABLE maps to 2 (bad input: the gate was asked to judge something nobody reviewed) and a real
    refusal maps to 1 (the check failed). Collapsing them into one non-zero class is exactly what `OI-3`
    showed a test cannot see through.
    """
    if verdict.allowed:
        return EXIT_OK
    if verdict.guard == GUARD_UNDECIDABLE:
        return EXIT_BAD_INPUT
    return EXIT_ATTENTION
