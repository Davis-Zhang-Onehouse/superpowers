"""The verb surface — one declarative flag spec per verb, and the cadence trigger every verb pulls.

`cli` is the only module that imports every other one, and nothing imports `cli` (asserted by
`tests/test_structure.py`). Five properties here are requirements rather than implementation choices, and
each is a defect somebody paid for:

**1. `VERBS` is the single copy.** Parsing, `usage()`, `--dry-run` and the generated test matrices are all
read off `VerbSpec`/`Flag`. `W2-20` shipped a `--profile` that was **mandatory and absent from usage** on a
line that printed source code twice, had zero assertions until its third fix, and was on its fourth issue.
A second hand-maintained copy of a flag list is the class, so there is exactly one and `usage()` is derived
from it — never written out.

**2. A trailing flag exits 2, with a diagnostic, and cannot hang.** `OI-8`, Critical: the predecessor's
`shift 2` shifted nothing and returned 1, so a flag passed last spun **forever** — and the pre-existing
`--seed-file` had the identical defect one line away. The loop below advances its index on **every** branch
and advances by two only where a value was actually consumed, so "hang" is not a reachable state; and
`Flag.takes_value` is the one fact both usage and the check read, so the two cannot disagree.

**3. `--dry-run` creates nothing, and every mutating verb has one.** `RI-32`/`OBS-70`: two actors created
stray instants in another effort's tree probing a guard, one of them *after reading and citing* the warning
against it. *A guard you cannot interrogate non-destructively gets interrogated destructively.* Every
dry-run path here evaluates the gates and returns before the first `mkdir`, and the suite diffs the
filesystem (with directory mtimes), the record store and the pool around each one.

**4. Every verb evaluates cadence staleness and prints it to stderr.** DA-6 drop 1, Critical: rev 1 made
cadence pure state and named no evaluator, so *the alarm fired only if somebody ran the very verb they had
stopped running* — and the observed failure was 19 hours of silence from an actor who had stalled. The
evaluation therefore lives in `main`, not in `harvest`'s handler, and it goes to **stderr** so stdout stays
data (`NFR2-7`). This is `git gc --auto`'s shape; it needs no daemon.

**5. No verb changes outward state.** No verb publishes, merges or deletes; that is operator-only,
permanently, and it is audited by a test over every handler's call graph rather than trusted. The
consequence is visible in `dispatch`: the profile is rendered **before** the child folder exists, so a
failure that would once have needed a rollback-by-deletion leaves nothing to roll back. Rollback releases
the lease it took and reports what it left, by path.

**6. A state the model knows, the surface can reach (FD-12).** The first pass to enumerate all the verbs
as a *population* found that §7's lifecycle named transitions no verb could perform — sharpest of all,
that **nothing could produce an `-abort-` folder** while `identity`, `layout` and `reconcile` all knew the
state and Plan 6 §K8 required an instant in it. A state only reachable by a hand `mv` is a rename that
becomes an untracked mutation, so `abort`, `close`, `enroll`, `unenroll`, `reap`, `set-golden` and
`reconcile` are here, and `init` registers the effort it creates as a watched source — the `OBS-68`
structure (invisible because *unlisted*) at a verb §8 never considered, which `lint`'s unregistered-base
rule cannot catch because at `init` time there is no record to lint.

`declare` re-reads through the consumer and prints what the consumer now sees — `RCF-9`'s acknowledgement:
a worker declared the phase exactly as its brief worded it, a leading `## ` defeated the consumer's regex,
and at a WIP cap of 1 that held the effort's only dev slot for the length of a CI queue.

**The `.md` files this module opens, and why AC-2 is satisfied.** `lint`'s near-miss rule reads
`HANDOFF.md` and `verify` reads `RUNBOOK.md`. Neither derives a *control signal* from prose — that is FD-8's
precise wording. `lint` reads the markdown as the **text under lint** (the standing `profiles` already has
for `charter.md`) and takes the phase itself from `.fleet/declare.json`; `verify` reads `RUNBOOK.md` as the
**recipe list it executes**. No phase, verdict, state or capacity decision in this module comes out of prose.
"""
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from fleet import EXIT_ATTENTION, EXIT_BAD_INPUT, EXIT_CODES, EXIT_OK, EXIT_REFUSED, __version__
from fleet import guards, layout, render
from fleet.errors import BadInput, FleetError, Refused
from fleet.harvest import DEFAULT_MAX_AGE_S, REGISTER_NAME, Harvest
from fleet.identity import ROOT_BASE, InstantName, resolve
from fleet.layout import INFO, VIOLATION
from fleet.pool import Pool, ReapReport
from fleet.profiles import Profile
from fleet.reconcile import COMPLETE, KIND_WORKER, reconcile
from fleet.review import Finding, Review, exit_code_for
from fleet import origin as origin_mod
from fleet.origin import Origin
from fleet.roadmap import COORDINATOR, TERMINAL, Milestone, Roadmap
from fleet.session import SessionLayer, default_probes
from fleet.store import Declarations, Record, Store
from fleet.workspace import GOLDEN_FILE, Workspace, default_git

# --- the flag spec ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Flag:
    """One declared flag. `takes_value` is the fact that drives BOTH usage and the last-with-no-value
    check, so a flag cannot be documented one way and parsed the other (`W2-20`/`OI-8`)."""

    name: str
    takes_value: bool
    required: bool = False
    help: str = ""


@dataclass(frozen=True)
class VerbSpec:
    """One verb. `read_only` is what makes `--dry-run` derived rather than remembered: a verb that can
    change state gets the flag whether or not anybody thought to add it.

    `checker` is DECLARED, for the same reason and one lesson later. It was derived from
    `columns == ROW_COLUMNS`, which put `roadmap` in the checker set only because `render.ROADMAP_COLUMNS`
    happens to be tuple-equal to `ROW_COLUMNS` — `OBS-44`'s family, *a property that holds because two
    things share a value is not a property*. Either tuple changing would have silently re-classified a
    verb, and what is applied to the classification is §9's population rule (`FI-19c`).
    """

    name: str
    flags: tuple
    handler: Callable
    read_only: bool
    help: str
    checker: bool = False


#: The flag every verb carries. Declared here once so `--home` is not re-typed twenty times, and declared
#: as data so the parser and usage still read it off the spec like any other flag.
#: `--help` is DECLARED like every other flag rather than special-cased in the parser, because the parser
#: refuses what no spec declares — which is correct, and which made `<verb> --help` exit 2 for all 27 verbs
#: while the usage text it printed went to stderr (`FI-26`). Declaring it means `usage()` documents it, the
#: generated flag matrix exercises it, and the answer to "how do I use this verb" is not an error.
HELP = "--help"
HELP_FLAG = Flag(HELP, False, help="print this verb's derived usage and exit 0")

COMMON_FLAGS = (
    Flag("--home", True, help="the record/pool store root; overrides $FLEET_HOME"),
    Flag("--instants-dir", True, help="where instants live; overrides $FLEET_INSTANTS"),
    Flag("--porcelain", False, help="machine form on stdout: tab-separated, no banner (NFR2-7)"),
    HELP_FLAG,
)

DRY_RUN = "--dry-run"
DRY_RUN_FLAG = Flag(DRY_RUN, False,
                    help="evaluate every gate and CREATE NOTHING; the delta is asserted to be zero")

#: The diagnostic a value-taking flag with nothing after it prints. A constant because the generated check
#: asserts on it: "exit 2" alone passes vacuously whenever another required flag is also missing.
NEEDS_VALUE = "needs a value"

#: The stderr prefix every cadence line carries. On stderr, never stdout — stdout is data.
CADENCE_PREFIX = "cadence:"

# --- exit codes -----------------------------------------------------------------------------------
#
# `fleet/__init__.EXIT_CODES` stays the ONE registry for the general codes. FD-10 documents four more for
# `pane-guard` alone — `0` safe · `10` queued text · `11` mid-turn · `12` not-claude · `13` unknown pane —
# because the external monitor branches on them before every send-keys and DA-2 enumerated SIX send paths.
# They are declared here, next to the only verb allowed to return them, rather than folded into the base
# registry: a code that means "the pane has text in its box" is not an answer to "did the verb succeed",
# and `registered_codes()` is what every caller and the suite ask.

PANE_SAFE = EXIT_OK
PANE_QUEUED_TEXT = 10
PANE_MID_TURN = 11
PANE_NOT_CLAUDE = 12
PANE_UNKNOWN = 13

PANE_GUARD_CODES = {
    PANE_SAFE: "safe",
    PANE_QUEUED_TEXT: "queued-text",
    PANE_MID_TURN: "mid-turn",
    PANE_NOT_CLAUDE: "not-claude",
    PANE_UNKNOWN: "unknown-pane",
}

#: Every code any verb in this package may return, base registry first.
EXIT_CODES_ALL = {**EXIT_CODES, **{code: name for code, name in PANE_GUARD_CODES.items()
                                   if code not in EXIT_CODES}}

PANE_GUARD = "pane-guard"


def registered_codes(verb: str) -> frozenset:
    """The codes `verb` is permitted to return. A verb returning anything else fails the suite (§9)."""
    if verb == PANE_GUARD:
        return frozenset(PANE_GUARD_CODES) | {EXIT_BAD_INPUT}
    return frozenset(EXIT_CODES)


# --- report rows ----------------------------------------------------------------------------------

POPULATION = "population"
NEAR_MISS = "near-miss-declaration"
EXECUTED = "executed"
NEVER_EXECUTED = "never-executed"
OUTSIDE_SANDBOX = "outside-sandbox"
REAPED = "reaped"
REAP_REFUSED = "reap-refused"
#: A stale lease this base OWNS and could not give back. Distinct from `reap-refused`, which is somebody
#: else's lease left alone deliberately: this one is a failure to do the thing, and `FI-22` is what it cost
#: to have no row for it — the failure surfaced as a traceback instead.
REAP_UNFREED = "reap-unfreed"
#: An INTERRUPTED claim cleared (`SI-7`): a claim directory a `mkdir` won whose lease body never landed, so
#: there is no owner to name. Its own kind rather than a `reaped` row, because a consumer branching on the
#: kind must be able to tell "a worker's stale lease was given back" from "a writer died mid-write and left
#: a slot nobody could claim" — those call for different human follow-up. Before this kind existed the
#: condition produced NO row, and the population line counted the lost slot as leased.
REAP_RECLAIMED = "reap-reclaimed"

#: `reconcile`'s two answers. The monitor branches on the KIND, never on the sentence — and the sentence
#: still says why, because a watcher operator who cannot see why a pane is unarmed disarms the watcher.
ARMED = "armed"
UNARMED = "unarmed"

#: Where an abort's reason lives: structured state inside the instant, written by the verb (FD-3). A
#: reason in a document is a reason no consumer can read, and an abort with no reason is a deletion with
#: a nicer name (FD-12).
ABORT_FILE = "abort.json"

#: The two overrides this surface offers, named as data so a refusal quotes the exact token a caller must
#: type. `RI-31`/`OBS-70`: a refusal a human cannot act on is a refusal that gets forced blindly.
FORCE = "--force"
ALL_EFFORTS = "--all"

KV_COLUMNS = ("field", "value")
ROW_COLUMNS = ("kind", "subject", "severity", "detail", "clears_when", "clears_who")


@dataclass(frozen=True)
class Row:
    """One reported finding. `clears_when`/`clears_who` are the alarm contract (§9) and they are fields
    rather than sentences, because an assertion anchored to prose is `OBS-62`."""

    kind: str
    subject: str
    severity: str
    detail: str
    clears_when: str = ""
    clears_who: str = ""


# --- parsing --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Parsed:
    """What one argv meant, keyed on the declared flag names and nothing else.

    There is no `positional` field, and its absence is the fix rather than a simplification. Every verb on
    this surface is flag-driven; the field existed, collected whatever bare token an argv carried, and was
    read by nothing — so `fleet board wat` and `fleet abort --instant X --reason Y wat` both succeeded
    silently while `--wat` was refused (`FI-19d`). A parser cannot both accept a token and have nowhere to
    put it: the token is refused in the parser, so no handler can inherit a bag of arguments nobody
    declared.
    """

    verb: str
    values: dict = field(default_factory=dict)
    switches: frozenset = frozenset()

    @staticmethod
    def _key(name: str) -> str:
        return name if name.startswith("--") else f"--{name}"

    def on(self, name: str) -> bool:
        return self._key(name) in self.switches

    def get(self, name: str, default=None):
        found = self.values.get(self._key(name))
        return found[-1] if found else default

    def all(self, name: str) -> list:
        return list(self.values.get(self._key(name), ()))


def parse(spec: VerbSpec, argv: list) -> Parsed:
    """Read one argv against one spec. Accepts nothing the spec does not declare — including positionals.

    The index advances on every branch, and by two **only** where a value was actually consumed. That is
    the whole of the `OI-8` fix: the predecessor's `shift 2` shifted nothing at the end of the argv and
    returned 1, so the surrounding loop never terminated — and the flag one line above it had the same
    defect, which is why this is a property of the parser rather than a check per flag.

    **Both halves of "undeclared" are refused, and the second half is the one that mattered.** An
    undeclared flag was refused from the start; a bare token was collected into a field nobody read, so
    `fleet board wat` exited 0 and — worse — `fleet abort --instant X --reason Y wat` performed the abort
    without a word about the argument the operator got wrong. A positional is exactly what a mistyped value
    looks like once its flag has been dropped, so the lenient half is the half that hides the typo
    (`FI-19d`).
    """
    by_name = {flag.name: flag for flag in spec.flags}
    values, switches = {}, set()
    index = 0
    while index < len(argv):
        token = argv[index]
        if token.startswith("-"):
            flag = by_name.get(token)
            if flag is None:
                raise BadInput(
                    f"{spec.name}: {token!r} is not a flag {spec.name} declares. Declared: "
                    + (", ".join(sorted(by_name)) or "(none)")
                    + ". Refused, not ignored: a parser that accepts what no spec declares is a second, "
                    "hand-maintained copy of the flag list.")
            if flag.takes_value:
                following = argv[index + 1] if index + 1 < len(argv) else None
                if following is None or following in by_name:
                    raise BadInput(
                        f"{spec.name}: {token} {NEEDS_VALUE} and "
                        + ("nothing followed it" if following is None
                           else f"the next token {following!r} is itself a declared flag")
                        + f". Usage:\n{_verb_usage(spec)}")
                values.setdefault(token, []).append(following)
                index += 2                     # by two ONLY because a value was consumed (OI-8)
                continue
            switches.add(token)
            index += 1
            continue
        raise BadInput(
            f"{spec.name}: {token!r} is a bare argument, and {spec.name} declares no positionals. "
            f"Every input is a named flag, so a bare token is a mistyped value whose flag was dropped "
            f"— refusing rather than collecting it into a field nobody reads.\nUsage:\n{_verb_usage(spec)}")

    if HELP in switches:
        # BEFORE the required-flag check, and that ordering is the whole of `FI-26`'s second half: the
        # verbs whose usage an operator most needs are the ones with required flags, and asking for help
        # is not a way of supplying them. `fleet init --help` must answer, not refuse.
        return Parsed(verb=spec.name, values=values, switches=frozenset(switches))

    missing = [flag.name for flag in spec.flags
               if flag.required and flag.name not in values and flag.name not in switches]
    if missing:
        raise BadInput(
            f"{spec.name}: the required flag(s) {', '.join(missing)} were not supplied. A mandatory flag "
            f"absent from the command is the other half of W2-20.\nUsage:\n{_verb_usage(spec)}")
    return Parsed(verb=spec.name, values=values, switches=frozenset(switches))


# --- usage, DERIVED -------------------------------------------------------------------------------


def _form(flag: Flag) -> str:
    return f"{flag.name} <value>" if flag.takes_value else flag.name


def _flag_lines(spec: VerbSpec) -> list:
    """One line per declared flag, from the spec. Never written out: `W2-20`'s `--profile` was mandatory
    and absent from a hand-written usage line, and that line was on its fourth issue."""
    out = []
    for flag in spec.flags:
        marker = "(required) " if flag.required else ""
        out.append(f"    {_form(flag):<28} {marker}{flag.help}".rstrip())
    return out


def _verb_usage(spec: VerbSpec) -> str:
    head = f"fleet {spec.name}" + "".join(
        f" {_form(flag)}" for flag in spec.flags if flag.required)
    return "\n".join([head, f"    {spec.help}"] + _flag_lines(spec)) + "\n"


def _codes_block() -> str:
    lines = ["exit codes:"]
    for code in sorted(EXIT_CODES):
        lines.append(f"    {code}  {EXIT_CODES[code]}")
    lines.append(f"    {PANE_GUARD} only (FD-10):")
    for code in sorted(PANE_GUARD_CODES):
        lines.append(f"    {code:<3}{PANE_GUARD_CODES[code]}")
    return "\n".join(lines) + "\n"


def usage(verb: str = None) -> str:
    """The whole surface, derived from `VERBS`. Never hand-written, for any verb."""
    if verb is not None:
        spec = VERBS.get(verb)
        if spec is None:
            raise BadInput(_unknown_verb(verb))
        return _verb_usage(spec) + "\n" + _codes_block()
    lines = [f"fleet <verb> [flags]                          v{__version__}", "", "verbs:"]
    for name in sorted(VERBS):
        lines.append(f"    {name:<20} {VERBS[name].help}")
    lines.append("")
    body = "\n".join(lines) + "\n"
    return body + "\n".join(_verb_usage(VERBS[name]) for name in sorted(VERBS)) + "\n" + _codes_block()


def _unknown_verb(verb: str) -> str:
    # The COUNT is derived. It was spelled as a word here, and FD-12 then added seven verbs — a number in
    # prose beside the list it counts is the smallest possible instance of the second-copy class, and it
    # is the one that had already gone stale.
    return (f"{verb!r} is not a fleet verb. The {len(VERBS)} verbs are: "
            + ", ".join(sorted(VERBS)) + ".")


# --- the context every handler is handed ----------------------------------------------------------


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp(now: str) -> str:
    """`MMDDHHMM` — the eight-digit `curr` field every instant on the box uses (FD-2)."""
    return f"{now[5:7]}{now[8:10]}{now[11:13]}{now[14:16]}"


@dataclass
class Ctx:
    """Everything a handler may touch. Every outside-world edge arrives injected (FD-6), so the suite
    describes a whole fleet — processes, tmux, git and a command runner — without owning one."""

    home: Path
    instants_dir: Path
    store: object
    pool: object
    sessions: object
    harvest: object
    out: object
    err: object
    dry_run: bool = False
    porcelain: bool = False
    now: Callable = _utc_now
    git: object = None
    runner: object = None
    #: `None` means "derive it"; a bool says it out loud. The cadence alarm is silent for an idle fleet,
    #: because an alarm nobody can act on trains people to ignore it.
    live_work: object = None
    max_age_s: int = DEFAULT_MAX_AGE_S

    def live_work_now(self) -> bool:
        if self.live_work is not None:
            return bool(self.live_work)
        if list(self.sessions.live()):
            return True
        return any(record.harvested_at is None for record in self.store.all())

    def subjects(self) -> list:
        return reconcile(self.store, self.pool, self.sessions, self.instants_dir)

    def guard_ctx(self, parsed: Parsed, **over) -> guards.Context:
        return guards.Context(store=self.store, pool=self.pool, sessions=self.sessions,
                              instants_dir=self.instants_dir, **over)


def default_context(parsed: Parsed, out, err) -> Ctx:
    """The real context: the live probes, the real git, a real command runner.

    Nothing in this function is reachable from a handler, which is what lets the outward-state audit hold
    while `verify` and `selftest` still run real commands: a handler calls `ctx.runner`, never a spawner.
    """
    # `SI-15`. A MUTATING verb with neither `--home` nor `FLEET_HOME` REFUSES rather than inventing a
    # destination. Measured before this over all 17 mutating verbs: 4 wrote a real store under
    # `$HOME/.fleet` and exited 0 — `enroll`, `init`, `resume`, `set-golden` — `complete` and `abort`
    # RENAMED instants there, and **not one of the 17** mentioned `FLEET_HOME` or `--home` in any
    # diagnostic. Plan 6's `A1` states the stakes exactly: *"a default that silently writes shared state is
    # how the live stores get touched."*
    #
    # A READ-ONLY verb keeps the default, deliberately. "Nothing is enrolled" is a real answer to a real
    # question, and refusing it would make discovery impossible for someone who has not yet chosen a store —
    # a read of a store that does not exist costs nothing, while a WRITE to one nobody named is the defect.
    # `read_only` is the same flag that already makes `--dry-run` derived rather than remembered, so this
    # rule cannot drift out of step with the verb table.
    named_home = parsed.get("home") or os.environ.get("FLEET_HOME")
    spec = VERBS.get(parsed.verb)
    if not named_home and spec is not None and not spec.read_only:
        raise BadInput(
            f"{parsed.verb!r} writes to a store and no store was named: pass `--home <path>` or export "
            f"FLEET_HOME. There is no default for a write. Falling back to {Path.home() / '.fleet'} is how "
            f"a fleet's real state gets touched by a command that meant to work somewhere else, so it is "
            f"refused rather than guessed.")
    home = Path(named_home or (Path.home() / ".fleet"))
    instants = Path(parsed.get("instants-dir") or os.environ.get("FLEET_INSTANTS")
                    or (home / "instants"))
    sessions = SessionLayer(default_probes())
    pool = Pool(home, cwd_probe=_cwd_holders, alive=sessions.alive)
    return Ctx(home=home, instants_dir=instants, store=Store(home), pool=pool, sessions=sessions,
               harvest=Harvest(home), out=out, err=err, dry_run=parsed.on("dry-run"),
               porcelain=parsed.on("porcelain"), git=default_git(), runner=_default_runner())


def _cwd_holders(path) -> list:
    """Live pids holding `path` as their cwd. `OBS-48`: tmux liveness cannot see a session that outlived
    its work, so "the tmux is gone" is not freedom."""
    holders = []
    proc = Path("/proc")
    if not proc.is_dir():
        return holders
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if (entry / "cwd").resolve() == Path(path).resolve():
                holders.append(int(entry.name))
        except OSError:
            continue
    return holders


def _default_runner():
    """`(command, cwd, env) -> (rc, stdout, stderr)`. The only spawner in this module, and it is
    referenced by `default_context` alone — never from a handler."""
    import subprocess

    def _spawn(command, cwd=None, env=None):
        done = subprocess.run(["bash", "-c", str(command)], cwd=None if cwd is None else str(cwd),
                              env=env, capture_output=True, text=True)
        return done.returncode, done.stdout, done.stderr

    return _spawn


# --- output ---------------------------------------------------------------------------------------


def _oneline(value) -> str:
    """One record, one line. A detail with a newline in it would split a TSV record in two."""
    return re.sub(r"\s+", " ", str("" if value is None else value)).strip()


def _cells(row, columns: tuple) -> list:
    if isinstance(row, tuple):
        values = list(row) + [""] * (len(columns) - len(row))
    else:
        values = [getattr(row, column, "") for column in columns]
    return [_oneline(value) for value in values[:len(columns)]]


def _emit(ctx: Ctx, verb: str, rows: list) -> None:
    """stdout is data. The porcelain form is exactly `PORCELAIN_COLUMNS[verb]` tab-separated fields per
    line with no banner and no blank lines, so `2>/dev/null | cut -f1` is supported (`NFR2-7`)."""
    columns = PORCELAIN_COLUMNS[verb]
    cells = [_cells(row, columns) for row in rows]
    if ctx.porcelain:
        for cell in cells:
            print("\t".join(cell), file=ctx.out)
        return
    widths = [max((len(cell[index]) for cell in cells), default=0) for index in range(len(columns))]
    for cell in cells:
        line = "  ".join(value.ljust(widths[index]) for index, value in enumerate(cell))
        print(line.rstrip(), file=ctx.out)


def _write(ctx: Ctx, text: str) -> None:
    ctx.out.write(text)


def _rows_of(items) -> list:
    """`layout.Violation` / `harvest.Row` / `roadmap.Row` -> this module's `Row`. One shape on stdout."""
    out = []
    for item in items:
        out.append(Row(kind=getattr(item, "rule", None) or getattr(item, "kind", ""),
                       subject=item.subject if hasattr(item, "subject") else item.path,
                       severity=item.severity, detail=item.detail,
                       clears_when=getattr(item, "clears_when", "") or "",
                       clears_who=getattr(item, "clears_who", "") or ""))
    return out


def _code_of(rows: list) -> int:
    return EXIT_ATTENTION if any(row.severity == VIOLATION for row in rows) else EXIT_OK


# --- shared handler helpers -----------------------------------------------------------------------


def _instant(ctx: Ctx, parsed: Parsed) -> Path:
    """The instant a verb was pointed at, followed through any rename the argument predates (`OI-16`)."""
    return _resolve_instant(ctx, parsed.get("instant"))


def _resolve_instant(ctx: Ctx, raw) -> Path:
    """Resolve ONE raw instant argument. Extracted so a verb taking a SECOND instant resolves it exactly
    as it resolves its first — `propose --to` is the case, and reconstructing a `Parsed` to reuse
    `_instant` got the keying wrong silently (`Parsed.values` is keyed `--instant` and holds a list), which
    made `--to` a no-op that fell back to the proposer. A shared resolver cannot drift the way two copies
    of this logic would."""
    path = Path(raw)
    if not path.is_absolute():
        path = ctx.instants_dir / raw
    found = resolve(path)
    if found is None:
        raise BadInput(
            f"{path} is not an instant on disk. A recorded path goes stale when the worker renames its "
            "own folder, so resolution follows the full stable key with only `state` varying — and a "
            "path that resolves to nothing is refused rather than invented (FD-1).")
    InstantName.parse(found.name)            # refused, not judged: a non-instant is not an instant
    return found


def _record(ctx: Ctx, parsed: Parsed) -> Record:
    return ctx.store.read(ctx.store.resolve_id(parsed.get("id")))


def _child_of(ctx: Ctx, record: Record) -> Path:
    path = Path(record.child_instant)
    if not path.is_absolute():
        path = ctx.instants_dir / path
    found = resolve(path)
    if found is None:
        raise BadInput(f"record {record.todo_id!r} names {path}, which resolves to no instant on disk")
    return found


def _record_for(ctx: Ctx, child: Path) -> Record:
    """The record whose child instant IS this folder, or `None`.

    Matched on `stable_key()` — every field but `state` — for the same reason `identity.resolve` is:
    the recorded path predates the worker's own rename, and `base-curr` alone is not unique (`OBS-14`).
    `None` is a legitimate answer: an instant that was never dispatched through this store still has a
    lifecycle, and refusing to act on it would make the surface unable to reach a state the model knows.
    """
    try:
        want = InstantName.parse(child.name).stable_key()
    except FleetError:
        return None
    for record in ctx.store.all():
        if not record.child_instant:
            continue
        try:
            if InstantName.parse(Path(record.child_instant).name).stable_key() == want:
                return record
        except FleetError:
            continue
    return None


def _verdict_rows(verdicts: list) -> list:
    return [Row(kind="guard", subject=verdict.guard,
                severity=INFO if verdict.allowed else VIOLATION,
                detail=("allowed: " if verdict.allowed else "refused: ") + verdict.reason,
                clears_when=verdict.clears_when or "", clears_who=verdict.clears_who or "")
            for verdict in verdicts]


def _verdict_kv(verdicts: list) -> list:
    return [(f"guard.{verdict.guard}",
             ("allow" if verdict.allowed else "refuse") + f": {verdict.reason}")
            for verdict in verdicts]


def _guard_code(ctx: Ctx, verdicts: list, gctx) -> int:
    """The code the real run would have returned, derived without triggering anything.

    A full pool (`3`) and a policy refusal (`4`) are different answers with different remedies, and a
    caller that cannot tell them apart takes the wrong action (`OI-3`), so the code comes from the guard's
    own declared `raises` rather than from a merged boolean.
    """
    by_name = {guard.name: guard for guard in guards.guards_for(gctx)}
    for verdict in verdicts:
        if verdict.allowed:
            continue
        raises = getattr(by_name.get(verdict.guard), "raises", Refused)
        return getattr(raises, "exit_code", EXIT_REFUSED)
    return EXIT_OK


def _normalise_phase(text: str) -> str:
    """The token the consumer compares. `reconcile` reads `awaiting-ci` and nothing else, so the verb
    normalises once, here, rather than leaving every reader to guess at case and spacing."""
    return " ".join(str(text).split()).lower()


# --- init -----------------------------------------------------------------------------------------


def _do_init(ctx: Ctx, parsed: Parsed) -> int:
    """Bootstrap the instant, AND put the effort it starts on the watched list (FD-12).

    The registration is not a courtesy. §8 put registration in the *dispatch* transaction, so an
    `init`-ed effort was invisible to `harvest` until somebody dispatched from it — `OBS-68`'s exact
    structure, where 20 issues including a Critical stayed invisible for ~4h because the register was
    *unlisted* rather than quiet. `lint`'s unregistered-base rule cannot cover this case either: it is
    derived from records, and at `init` time there is no record. The effort's own base is the instant just
    created, because "dispatching from it" is what the missing registration was waiting for.

    Registration comes AFTER the bootstrap, in that order, because the bootstrap is what creates the
    register the registry points at — a source whose register does not exist is a broken registration,
    which is a different (and worse) failure than an empty one.
    """
    base = parsed.get("base", ROOT_BASE)
    optype = parsed.get("optype", "append")
    name = InstantName.new(base=base, now=_stamp(ctx.now()), optype=optype,
                           title=parsed.get("name"))
    target = ctx.instants_dir / name.format()
    register = target / REGISTER_NAME
    if ctx.dry_run:
        _emit(ctx, "init", [("dry-run", "nothing was created and nothing was registered"),
                            ("would-create", str(target)),
                            ("would-register", str(register)),
                            ("instant", name.format())])
        return EXIT_OK
    if target.exists():
        raise BadInput(f"{target} already exists; `init` never overwrites an instant")
    created = layout.bootstrap(target, name)
    source = ctx.harvest.register(str(target), str(register))
    rows = [("instant", name.format()), ("path", str(target)), ("created", str(len(created))),
            ("watched_source", source.base), ("register", source.issues_path)]
    rows += [("file", str(path)) for path in created]
    _emit(ctx, "init", rows)
    return EXIT_OK


# --- dispatch -------------------------------------------------------------------------------------


def _do_dispatch(ctx: Ctx, parsed: Parsed) -> int:
    """Gates → claim → **gates again, holding the claim** → render → write the tree → record → launch.

    The render comes **before** the child folder exists on purpose. §7's rollback is "undo everything on
    any failure", and the only failure that used to need a deletion was an unresolved placeholder found
    after the folder was built (`SR-C10-2`). Rendering first means the fallible steps happen while there is
    nothing to undo, which is how this verb satisfies "no verb deletes" without losing the rollback.

    The second gate is `FI-21`. The first one is a read, and a read cannot settle the cap: the record it
    counts is written at the *end* of this function, so five concurrent dispatchers all read "0 in active
    dev", all pass and all proceed — 20 of 20 iterations admitted the wrong number at `WIP_CAP=1`. The fix
    is not to make the gate write; `evaluate` staying pure is what `--dry-run`'s zero-delta contract rests
    on, and that contract exists because two actors damaged another effort's tree probing a guard. So the
    lease — the one artifact here that is already atomic — is claimed FIRST, and the rules are asked again
    while it is held. Admission becomes a property of a won claim rather than of a read, and a refusal at
    that point gives the claim straight back.
    """
    profile = Profile.load(Path(parsed.get("profile")))
    optype = parsed.get("optype", "append")
    base = parsed.get("base", ROOT_BASE)
    title = parsed.get("title")
    cap = int(parsed.get("cap")) if parsed.get("cap") is not None else None

    # `SI-27`. The dispatching coordinator and the milestone this dispatch is FOR.
    #
    # Both optional, because not every dispatch is about a roadmap row — a coordinator or a compaction
    # instant is dispatched for a role. But `--milestone` without `--from` is refused rather than ignored:
    # a milestone id is meaningless without the roadmap it lives on, and silently dropping it would record
    # the join nowhere while the caller believed it had been recorded.
    coordinator = _resolve_instant(ctx, parsed.get("from")) if parsed.get("from") else None
    milestone_id = parsed.get("milestone")
    if milestone_id and coordinator is None:
        raise BadInput(
            f"--milestone {milestone_id!r} names a row on a roadmap, and no roadmap was named. Pass "
            f"`--from <the coordinator's instant>` so the milestone can be resolved, claimed and reported "
            f"against. Refused rather than ignored: dropping it would leave the caller believing the join "
            f"was recorded.")
    if milestone_id is not None:
        # Fast-fail on the two conditions `Roadmap.claim` enforces, BEFORE a slot is claimed — the `SI-20`
        # pattern. `claim` re-checks under the lock and is the authority; this only avoids claiming a slot
        # and starting a session for a dispatch that was never going to be admissible.
        blocker = Roadmap(coordinator).blocker_of(milestone_id)
        if blocker:
            raise Refused(
                f"milestone {milestone_id!r} is not ready, so nothing may be dispatched onto it: "
                f"{blocker}. Refused before anything was claimed.",
                clears_when="the milestone's dependencies have LANDED (status=done via an applied "
                            "proposal)")
        owned = Roadmap(coordinator).milestone(milestone_id).owner
        if owned:
            raise Refused(
                f"milestone {milestone_id!r} is already claimed by {owned!r}, and two instants on one "
                f"milestone is not a race the roadmap can resolve. Refused before anything was claimed.",
                clears_when=f"the claim on {milestone_id!r} is given back, which `fleet abort --instant "
                            f"{owned} --reason <why>` does when that work is being abandoned")

    # `SI-32`. Parsed before anything is claimed, so a malformed pair is refused with nothing to roll back.
    lineage = _lineage_pairs(parsed.get("lineage-base"), "--lineage-base")
    lineage_mode = parsed.get("lineage-mode") or ("code" if lineage else "")
    if lineage_mode and lineage_mode not in LINEAGE_MODES:
        raise BadInput(f"--lineage-mode must be one of {LINEAGE_MODES}; got {lineage_mode!r}")
    if lineage_mode and not lineage:
        raise BadInput(
            f"--lineage-mode {lineage_mode!r} says how a lineage base will be checked and no base was "
            f"given. Pass --lineage-base 'repo=sha,...' — refused rather than ignored, because a mode "
            f"recorded with nothing to check reads like a base that is being enforced.")

    gctx = ctx.guard_ctx(parsed, base=base, cap=cap, profile=profile, optype=optype,
                         override_reason=parsed.get("override"))
    verdicts = guards.evaluate_all(gctx, "dispatch")

    if ctx.dry_run:
        rows = [("dry-run", "every gate evaluated; nothing was claimed, created or started")]
        rows += [("coordinator", str(coordinator) if coordinator else
                  "(none — the child will have no origin.json and `propose` will stay LOCAL)"),
                 ("milestone", milestone_id or "(none — this dispatch is not about a roadmap row)"),
                 ("lineage_base", parsed.get("lineage-base") or "(none — no git lineage is recorded, so "
                                                                "nothing gates a claim of done)"),
                 ("lineage_mode", lineage_mode or "(none)")]
        rows += _verdict_kv(verdicts)
        _emit(ctx, "dispatch", rows)
        return _guard_code(ctx, verdicts, gctx)

    guards.enforce_all(gctx, "dispatch")

    name = InstantName.new(base=base, now=_stamp(ctx.now()), optype=optype, title=title)
    child = ctx.instants_dir / name.format()
    todo_id, tmux = f"{name.name}-{name.curr}", f"dt-{name.name}"

    # `SI-20`, and it is refused BEFORE the claim so there is nothing to roll back.
    #
    # The child path, the `todo_id` and the tmux name all derive from `(base, MMDDHHMM, camel(title))` and
    # nothing else — the non-uniqueness `identity.stable_key`'s own docstring records as `OBS-14`. Two
    # dispatches of the same title in one UTC minute therefore collide, and measured with a LIVE worker in
    # the first slot the second one:
    #   * overwrote `CHARTER.md` and `.fleet/seed.txt` unconditionally, destroying the running worker's own
    #     charter edits — `layout.bootstrap` is non-clobbering, but the two writes after it were not;
    #   * overwrote the record by `todo_id`, so the surviving record named the SECOND slot with
    #     `launched_at=null` while the FIRST slot was the one actually held;
    #   * then failed at `sessions.start` on the duplicate session name and rolled back only its OWN lease.
    # Net: `board` — "every subject holding a slot" — showed ZERO rows while a live pane held a slot, and
    # that slot was held by a lease no record named. None of it appeared in the rollback sentence.
    #
    # A collision is refused rather than uniquified: silently appending a suffix would hand the operator a
    # second instant they did not ask for and cannot distinguish, which is a worse outcome than being told
    # to wait a minute or change the title. `resolve` is not used here — the question is not "does some
    # instant of this identity exist in any state" but the narrower "would this dispatch write over
    # something", so the exact path and the exact `todo_id` are what get checked.
    if child.exists():
        raise Refused(
            f"a dispatch this minute already produced {child}, so this one would write over it: the child "
            f"path, the todo id and the session name all derive from (base, minute, title) and nothing "
            f"else. Refused before anything was claimed. Change the title, or wait for the next minute.",
            clears_when=f"{child} no longer exists, or the title or minute differs")
    if any(r.todo_id == todo_id for r in ctx.store.all()):
        raise Refused(
            f"a record already exists for todo {todo_id!r}, and a dispatch writes records by todo id — so "
            f"this one would overwrite the record of work that may still be running. Refused before "
            f"anything was claimed. Change the title, or wait for the next minute.",
            clears_when=f"no record is stored under todo {todo_id!r}")

    workspace = Workspace(ctx.home, git=ctx.git)
    claimed_milestone = None
    lease = ctx.pool.claim(todo_id=todo_id, tmux=tmux, base_instant=base,
                           child_instant=str(child), slot=parsed.get("slot"))
    try:
        # Claim-then-verify (FI-21). Nothing but the claim exists yet, so a refusal here gives back the
        # lease and stops — no tree to name, no rollback narrative to print, and the caller sees the cap's
        # own sentence and exit 4.
        guards.enforce_all(gctx.under_claim(lease.slot), "dispatch", under_claim=True)
    except BaseException:
        ctx.pool.release(lease.slot, force=True)
        raise
    try:
        rendered = profile.render({"TITLE": title, "INSTANT": name.format(), "SLOT": lease.slot,
                                   "TODO_ID": todo_id, "BASE": base, "PATH": str(child),
                                   # `SI-27`: a profile's seed can now name the worker's own milestone and
                                   # coordinator, so the contract a worker reads first is specific to it.
                                   "MILESTONE": milestone_id or "",
                                   "COORDINATOR": str(coordinator) if coordinator else "",
                                   # `SI-32`/`OI-1`: ONE datum, rendered into every document. A seed and a
                                   # charter that both say `{{LINEAGE_BASE}}` cannot disagree about the base;
                                   # two hand-written prose statements did, and the worker had to arbitrate.
                                   "LINEAGE_BASE": parsed.get("lineage-base") or "",
                                   "LINEAGE_MODE": lineage_mode or "",
                                   "CHECKOUT": _checkout_instruction(lineage, lineage_mode)})
        record = Record(todo_id=todo_id, child_instant=str(child), base_instant=base,
                        slot=lease.slot, tmux=tmux, profile=str(profile.path),
                        golden=str(lease.path), lineage_base=parsed.get("lineage-base") or "",
                        lineage_mode=lineage_mode, title=title,
                        #: `SI-34`. Persisted, not merely evaluated: an override is a judgement that a guard
                        #: was wrong here, and it has to outlive the terminal it was typed into.
                        override_reason=parsed.get("override") or "",
                        milestone=milestone_id, dispatched_at=ctx.now())
        # `SI-32`. Each repo's HEAD as the slot was leased — read-only, and read BEFORE the worker exists.
        # This is what the prebuilt native artifacts were built from, and the only way to answer later
        # whether the source has moved out from under them. `dispatch` performs no checkout: mechanism B is
        # the gate on a claim of done, not repositioning, so this verb stays read-only against git.
        if lineage:
            workspace_probe = Workspace(ctx.home, git=ctx.git)
            observed = workspace_probe.base_check(lease.path, lineage)
            record.golden_base = ",".join(f"{c.repo}={c.actual}" for c in observed if c.actual)
        layout.bootstrap(child, name)
        (child / "CHARTER.md").write_text(rendered["charter"])
        seed = child / ".fleet" / "seed.txt"
        seed.parent.mkdir(parents=True, exist_ok=True)
        seed.write_text(rendered["seed"])
        # `SI-27`. Written by the DISPATCHER, so the worker reads its coordinator instead of being told one
        # in prose it may not have been given. This is what stops `propose` defaulting to the worker itself
        # and `harvest` then burying the report in a folder it is about to close.
        if coordinator is not None:
            origin_mod.write(child, Origin(coordinator=str(coordinator), dispatched_at=ctx.now(),
                                           milestone=milestone_id))
        workspace.isolate_build_cache(lease.path)
        # The registry's WRITER: the base is registered and THEN the record is written, one call, in that
        # order. A record whose effort nobody watches is `OBS-68` — invisible because unlisted.
        source = ctx.harvest.record_dispatch(ctx.store, record)
        ctx.sessions.start(tmux, lease.path, "claude")
        record.launched_at = ctx.now()
        ctx.store.write(record)
        # The claim is the LAST mutation, so every earlier failure leaves the roadmap untouched and there is
        # nothing to compensate for. It is still inside the try, because losing the claim race here must
        # roll the dispatch back rather than leave a worker running on a milestone somebody else owns.
        if milestone_id is not None:
            Roadmap(coordinator).claim(milestone_id, str(child))
            claimed_milestone = milestone_id
    except Exception:
        ctx.pool.release(lease.slot, force=True)
        # `SI-21` applied to the roadmap: a rollback must not strand state it created. If the claim landed
        # and something after it failed, the milestone would read as owned by an instant that is being
        # rolled back — so it is given back here, and the failure to give it back is reported rather than
        # masking the original error.
        if claimed_milestone is not None:
            try:
                Roadmap(coordinator).disown(claimed_milestone)
            except Exception as exc:  # noqa: BLE001 - never mask the original failure
                print(f"WARNING: milestone {claimed_milestone!r} was claimed by {child} and the claim "
                      f"could NOT be given back ({exc}). It will read as owned by an instant that was "
                      f"rolled back; clear it before dispatching that milestone again.", file=ctx.err)
        # `SI-21`: the record is named too, and with the verb that clears it.
        #
        # `record_dispatch` writes the record BEFORE `sessions.start`, so a launch failure left a stored
        # record with `launched_at=None` reading PENDING-LAUNCH — a state `CAP_EXCLUDED_STATES` does not
        # exclude, so it consumed a WIP-cap slot indefinitely, and the rollback sentence mentioned only the
        # child folder. An alarm nobody is told about is worse than a loud one: the operator saw a lease
        # given back and had no way to know the cap had quietly lost a slot.
        #
        # The record is still not DELETED here — "no verb deletes outward state" holds, and a dispatch that
        # tidied away its own record would also erase the only evidence that the attempt happened. It is
        # named, and so is the verb that resolves it.
        stranded = any(r.todo_id == todo_id for r in ctx.store.all())
        print(f"dispatch rolled back: the lease on {lease.slot!r} was given back. Anything already "
              f"written under {child} is left in place and named here rather than removed — no verb "
              f"deletes outward state."
              + (f" A RECORD for todo {todo_id!r} was already written and is left in place: it reads "
                 f"PENDING-LAUNCH and counts against the WIP cap until it is resolved. Clear it with "
                 f"`fleet abort --instant {child} --reason <why>`." if stranded else ""),
              file=ctx.err)
        raise
    _emit(ctx, "dispatch", [("todo_id", todo_id), ("instant", str(child)), ("slot", lease.slot),
                            ("tmux", tmux), ("watched_source", source.base),
                            ("milestone", milestone_id or "(none)"),
                            ("override_reason", record.override_reason or "(none — no rule was overridden)"),
                            ("lineage_base", record.lineage_base or "(none)"),
                            ("lineage_mode", record.lineage_mode or "(none)"),
                            ("golden_base", record.golden_base or "(none recorded)"),
                            ("coordinator", str(coordinator) if coordinator else
                             "(none — this child has no origin.json, so its `propose` stays LOCAL)"),
                            ("launched_at", record.launched_at)])
    return EXIT_OK


# --- resume ---------------------------------------------------------------------------------------


def _do_resume(ctx: Ctx, parsed: Parsed) -> int:
    """Adopt an existing conforming instant, evaluating NO admission rule (FD-9).

    *"Not every door that can dispatch should refuse. The test is whether refusing blocks a recovery path,
    and for resume it does"* — refusing a resume is its own outage, which is the alarm that blocks the fix.
    Idempotent: resuming twice updates one record rather than claiming a second slot.
    """
    child = _instant(ctx, parsed)
    name = InstantName.parse(child.name)
    gctx = ctx.guard_ctx(parsed, base=name.base)
    verdicts = guards.evaluate_all(gctx, "resume")
    todo_id = f"{name.name}-{name.curr}"
    tmux = parsed.get("tmux", f"dt-{name.name}")
    existing = None
    try:
        existing = ctx.store.read(todo_id)
    except BadInput:
        existing = None

    if ctx.dry_run:
        rows = [("dry-run", "nothing was adopted, claimed or written"),
                ("instant", str(child)), ("todo_id", todo_id),
                ("already_recorded", "true" if existing else "false")]
        rows += _verdict_kv(verdicts)
        _emit(ctx, "resume", rows)
        return EXIT_OK

    slot = parsed.get("slot")
    lease = None
    if existing is not None and existing.slot:
        slot = existing.slot
    if slot and ctx.pool.lease(slot) is None:
        lease = ctx.pool.claim(todo_id=todo_id, tmux=tmux, base_instant=name.base,
                               child_instant=str(child), slot=slot)
    held = ctx.pool.lease(slot) if slot else None
    record = Record(todo_id=todo_id, child_instant=str(child), base_instant=name.base,
                    slot=slot or "", tmux=tmux,
                    profile=parsed.get("profile", existing.profile if existing else ""),
                    golden=str(held.path) if held else (existing.golden if existing else ""),
                    lineage_base=existing.lineage_base if existing else "",
                    lineage_mode=existing.lineage_mode if existing else "",
                    override_reason=existing.override_reason if existing else "",
                    golden_base=existing.golden_base if existing else "",
                    title=name.name, dispatched_at=existing.dispatched_at if existing else ctx.now(),
                    launched_at=ctx.now() if ctx.sessions.alive(tmux) else
                    (existing.launched_at if existing else None))
    source = ctx.harvest.record_dispatch(ctx.store, record)
    _emit(ctx, "resume", [("todo_id", todo_id), ("instant", str(child)), ("slot", slot or ""),
                          ("tmux", tmux), ("claimed", "true" if lease else "false"),
                          ("watched_source", source.base),
                          ("exemption", verdicts[0].guard if verdicts else "")])
    return EXIT_OK


# --- declare / park / unpark ----------------------------------------------------------------------


def _do_declare(ctx: Ctx, parsed: Parsed) -> int:
    """Write the declaration, then RE-READ IT THROUGH THE CONSUMER and print what the consumer sees.

    That re-read is the acknowledgement, and it is the whole verb. `RCF-9`: a worker declared the phase
    exactly as its brief worded it, a leading `## ` defeated the consumer's regex, the declaration was a
    silent no-op, and at a WIP cap of 1 that held the effort's only dev slot for the length of a CI queue.
    Echoing the argument back would reproduce the failure exactly — the argument is what the declarer
    already believed.
    """
    child = _instant(ctx, parsed)
    asked = parsed.get("phase")
    phase = _normalise_phase(asked)
    #: `SI-36`. An empty phase is BAD INPUT, not a silent clear. `_normalise_phase("")` returns `""`, which is
    #: not `None`, so `set_phase` stored it and this handler's own guard — `if value is None`, the one check
    #: meant to catch a declaration that did not land — never fired. `declare --phase ""` therefore exited 0,
    #: cleared the phase, and did something worse: `near_miss_rows` skipped every line while a phase was
    #: stored, so it ALSO switched the RCF-9 lint off. Silence from the control, and no exclusion from the cap,
    #: which still compares against `awaiting-ci`. `§G6` measured it.
    #:
    #: Refused rather than treated as a clear, and `park --question ""` already draws the line the same way:
    #: an empty park is not a park. Clearing is `unpark`'s job there and has no counterpart here by design —
    #: a phase is declared or it is not.
    if not phase:
        raise BadInput(
            f"--phase {asked!r} normalises to nothing, and an empty phase is not a declaration. It is refused "
            f"rather than stored, because a stored empty phase reads as '(none declared)' to every consumer "
            f"while still suppressing the near-miss lint — silence from the control and no exclusion from the "
            f"cap. Declare a real phase, or leave the instant undeclared.")
    if ctx.dry_run:
        _emit(ctx, "declare", [("dry-run", "nothing was declared"), ("would-declare", phase),
                               ("asked", asked)])
        return EXIT_OK
    Declarations(child).set_phase(phase)
    consumer = Declarations(child)                       # a FRESH consumer, not the writer's return
    value = consumer.phase()
    if value is None:
        raise BadInput(
            f"the declaration did not land: {consumer.path} reports no phase after writing {phase!r}. "
            "The acknowledgement is the re-read, so a declaration that cannot be read back is a failure "
            "and not a success with a caveat.")
    _emit(ctx, "declare", [("phase", value), ("asked", asked), ("consumer", str(consumer.path)),
                           ("instant", str(child))])
    return EXIT_OK


def _do_park(ctx: Ctx, parsed: Parsed) -> int:
    child = _instant(ctx, parsed)
    question = parsed.get("question")
    if ctx.dry_run:
        _emit(ctx, "park", [("dry-run", "nothing was parked"), ("would-park", question)])
        return EXIT_OK
    Declarations(child).park(question)
    _emit(ctx, "park", [("parked", Declarations(child).parked() or ""), ("instant", str(child))])
    return EXIT_OK


def _do_unpark(ctx: Ctx, parsed: Parsed) -> int:
    child = _instant(ctx, parsed)
    standing = Declarations(child).parked()
    if ctx.dry_run:
        _emit(ctx, "unpark", [("dry-run", "nothing was cleared"), ("standing", standing or "")])
        return EXIT_OK
    Declarations(child).unpark()
    _emit(ctx, "unpark", [("cleared", standing or ""),
                          ("parked", Declarations(child).parked() or ""),
                          ("instant", str(child))])
    return EXIT_OK


# --- the git lineage: what to build on top of, and whether the slot is there ------------------------
#
# `SI-32`. Two failures, one datum. The first is `OI-1`: a dispatch SEED rendered once per wave named one
# lineage base while a per-milestone CHARTER named another, and the worker had to decide which was
# authoritative. Prose cannot fix that — the fix is that both documents RENDER from one recorded field. The
# second is `OI-2`: a slot is leased from a pre-built golden image and *nothing moves it forward*, so a worker
# that never repositions builds on the golden — a real, green, buildable commit — and *"the failure mode is
# invisible: the build succeeds and tests pass, so the whole milestone silently stacks on the pre-fix
# baseline. Two workers in the previous wave hit exactly this."*
#
# The mechanism here is deliberately the GATE and not the repositioning. `dispatch` stays read-only against
# git; what changes is that a worker cannot REPORT from the wrong base. That is chosen over a check the worker
# runs, because a check you must remember to run fails the same way the checkout does — `OI-3` is the proof:
# the verb existed, the worker tried to run it, and the id did not even resolve.

LINEAGE_MODES = ("code", "analysis")

#: The positions `base_check` can return, and what each means for a claim of DONE. `at-base` and `descendant`
#: are both fine — a descendant IS the intended end state for a code milestone, and a check that demanded
#: equality would mis-trigger on exactly the workers who did everything right.
_LINEAGE_FATAL = ("absent",)


def _lineage_pairs(text: str, flag: str) -> dict:
    """`repo=sha,repo=sha` -> {repo: sha}. Refused rather than half-parsed."""
    out = {}
    for chunk in str(text or "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise BadInput(
                f"{flag} takes `repo=sha` pairs separated by commas; got {chunk!r}. A slot holds several "
                f"sibling repos and each needs its own base, so the repo name is not optional.")
        repo, sha = chunk.split("=", 1)
        repo, sha = repo.strip(), sha.strip()
        if not repo or not sha:
            raise BadInput(f"{flag} pair {chunk!r} is missing a repo or a sha")
        out[repo] = sha
    return out


def _checkout_instruction(lineage: dict, mode: str) -> str:
    """The literal commands a worker must run before it writes a line of code.  `SI-32`.

    Rendered into the seed and the charter as `{{CHECKOUT}}`, from the same dict that becomes
    `Record.lineage_base`. The point is not politeness: `OI-1` was a worker handed TWO prose statements of its
    base that disagreed, and `OI-2` was a worker never told to reposition at all, after which *"the build
    succeeds and tests pass, so the whole milestone silently stacks on the pre-fix baseline."*

    An instruction generated from the recorded field cannot drift from the field the gate checks — which is
    the only reason to generate it rather than write it by hand in the profile.
    """
    if not lineage:
        return ("No git lineage was recorded for this dispatch, so nothing is enforced about where you "
                "build. If that is wrong, stop and ask the coordinator for your lineage base.")
    mode = mode or "code"
    lines = [
        "BEFORE YOU WRITE ANY CODE, position your workspace. Your slot was leased from a pre-built golden "
        "image and NOTHING has moved it to your base — a slot that is still at the golden builds and tests "
        "GREEN while stacking your whole milestone on the wrong baseline.",
        "",
        f"Your lineage base (lineage-mode={mode}), one line per repo in your slot:",
    ]
    for repo in sorted(lineage):
        sha = lineage[repo]
        lines.append(f"    git -C {repo} fetch --all")
        if mode == "code":
            lines.append(f"    git -C {repo} checkout --detach {sha}")
        else:
            lines.append(f"    git -C {repo} cat-file -e {sha}^{{commit}}   # readable via refs; do NOT "
                         f"check out")
    lines += [
        "",
        "A detached HEAD is enough: `base-check` is satisfied by it, and it is satisfied equally by a branch "
        "you cut from it, because commits on top of the base are the intended end state. Cut one if you need "
        "to commit; the gate does not require it and imposes no naming convention. (The instruction used to "
        "end '# then cut your own branch' without saying whether to, what to call it, or whether the gate "
        "cared — a real worker in §P flagged exactly that.)",
        "",
        "Then prove it, do not assume it:",
        "    fleet base-check --id <your todo id>",
        "",
        "`fleet propose --status done` and `fleet complete` REFUSE if your workspace is not on this base, so "
        "this is not advice you can skip.",
    ]
    if mode == "code":
        lines.append(
            "If you touch native code: the .so files in your slot were built from the GOLDEN commit, not "
            "from your base. Rebuild them after repositioning, or a test run exercises new source against "
            "old native code — `base-check` warns when it can tell.")
    return "\n".join(lines)


def _slot_of(ctx: Ctx, record: Record) -> Path:
    """The workspace this record was given. `Record.golden` holds the slot path — confusingly named, and
    what `_do_dispatch` actually writes there (`SI-19` noted it)."""
    if record.golden:
        return Path(record.golden)
    lease = ctx.pool.lease(record.slot) if record.slot else None
    return lease.path if lease is not None else None


def _lineage_rows(ctx: Ctx, record: Record) -> tuple:
    """-> (rows, fatal_repos). Empty rows when no git lineage was recorded, which is NOT a failure: a
    coordinator, a compaction, or any dispatch with no `--lineage-base` has none to check."""
    expected = _lineage_pairs(record.lineage_base, "--lineage-base")
    if not expected:
        return [], []
    slot = _slot_of(ctx, record)
    if slot is None or not Path(slot).is_dir():
        return [Row(kind="lineage", subject=record.todo_id, severity=VIOLATION,
                    detail=(f"a lineage base is recorded ({record.lineage_base}) and the workspace "
                            f"{slot} does not exist, so it cannot be checked"),
                    clears_when="the slot is present, or the record's lineage base is cleared",
                    clears_who=COORDINATOR)], list(expected)
    workspace = Workspace(ctx.home, git=ctx.git)
    checks = workspace.base_check(slot, expected)
    mode = record.lineage_mode or "code"
    rows, fatal = [], []
    for check in checks:
        bad = check.verdict in _LINEAGE_FATAL or (mode == "code" and check.verdict == "present")
        if bad:
            fatal.append(check.repo)
        if check.verdict == "absent":
            detail = (f"the workspace does not have {check.expected[:12]} AT ALL (HEAD "
                      f"{(check.actual or 'unknown')[:12]}), so it can neither build on it nor read it")
            clears = f"git -C {Path(slot) / check.repo} fetch --all"
        elif check.verdict == "present":
            detail = (f"{check.expected[:12]} is present but NOT checked out (HEAD "
                      f"{(check.actual or 'unknown')[:12]}). Legitimate for an ANALYSIS milestone reading "
                      f"via refs — and it keeps the prebuilt native artifacts valid — but this dispatch is "
                      f"lineage-mode={mode}")
            clears = f"git -C {Path(slot) / check.repo} checkout --detach {check.expected}"
        elif check.verdict == "descendant":
            detail = (f"HEAD {(check.actual or '')[:12]} is a DESCENDANT of {check.expected[:12]} — work "
                      f"committed on top, which is the intended end state")
            clears = ""
        else:
            detail = f"at the base, {check.expected[:12]}"
            clears = ""
        rows.append(Row(kind="lineage", subject=f"{record.todo_id}:{check.repo}",
                        severity=VIOLATION if bad else INFO, detail=detail,
                        clears_when=clears, clears_who="the dispatched instant" if clears else ""))
    #: A dirty tree, and stale native artifacts. Both INFO — see `Workspace.stale_native` on why an
    #: unclearable alarm is worse than none.
    for repo in workspace.dirty(slot, expected):
        rows.append(Row(kind="lineage", subject=f"{record.todo_id}:{repo}", severity=INFO,
                        detail=("UNCOMMITTED changes: the working tree is not the tip any CI proved, so a "
                                "green run elsewhere says nothing about the code here"),
                        clears_when="the changes are committed or stashed", clears_who="the dispatched instant"))
    current = {c.repo: c.actual for c in checks if c.actual}
    for repo, artifact in workspace.stale_native(slot, _lineage_pairs(record.golden_base, "golden_base"),
                                                 current):
        rows.append(Row(
            kind="lineage", subject=f"{record.todo_id}:{repo}", severity=INFO,
            detail=(f"STALE NATIVE ARTIFACTS: the source has moved off the commit this slot was leased at, "
                    f"and {artifact} predates the last checkout — a test run here exercises NEW source "
                    f"against OLD native code, which is a false green the build system cannot see. Judged by "
                    f"mtime, so a rebuild clears it; a JVM-only milestone is legitimately unaffected"),
            clears_when="the native side is rebuilt, or the milestone is confirmed to touch no native code",
            clears_who="the dispatched instant"))
    return rows, fatal


def _lineage_gate(ctx: Ctx, child: Path, verb: str) -> None:
    """Refuse a claim of DONE made from the wrong base.  `SI-32`, and this is mechanism B.

    Placed here rather than left to the worker because *a check you must remember to run fails the same way
    the checkout does*. This one cannot be skipped: since `SI-27`, `harvest` refuses to close a worker whose
    report never reached the coordinator, so a worker MUST pass through `propose --status done` to be closed
    out — which means it must pass through here.

    Silent when no lineage was recorded. Absence of a recorded base is not a failure; it is most dispatches.
    """
    record = _record_for(ctx, child)
    if record is None:
        return
    rows, fatal = _lineage_rows(ctx, record)
    if not fatal:
        return
    detail = "; ".join(row.detail for row in rows if row.severity == VIOLATION)
    raise Refused(
        f"{verb} refused: this instant was dispatched to build on {record.lineage_base} "
        f"(lineage-mode={record.lineage_mode or 'code'}) and its workspace is not there — {detail}. A claim "
        f"of done from the wrong base is the failure this gate exists for: the build succeeds and the tests "
        f"pass, so the work silently stacks on the wrong baseline and nothing downstream can see it. Run "
        f"`fleet base-check --id {record.todo_id}` for the per-repo detail.",
        clears_when=("the workspace is repositioned onto the recorded lineage base (or, for an analysis "
                     "milestone, the dispatch is recorded with --lineage-mode analysis)"),
        clears_who="the dispatched instant")


# --- propose / apply ------------------------------------------------------------------------------


def _do_milestone(ctx: Ctx, parsed: Parsed) -> int:
    """The COORDINATOR's verb: put a milestone ON the roadmap.

    `SI-26`. `SD-5` removed reassignment and made a milestone the thing that carries an item across an
    effort boundary — *"an item that outlives its effort becomes a documented issue in the workspace plus a
    milestone on the roadmap; the coordinator dispatches it later like any other."* `Roadmap.add` has always
    existed, been locked (`FI-30c`) and been tested; it had **no verb**, so from a command line the
    replacement was unreachable and the roadmap could only ever be seeded from python. `reassign` was
    deleted for having a correct, tested, dead public surface (`SI-19`'s lesson, `SI-24`'s shape) and the
    replacement inherited the same defect in the same commit.

    Two doors, not one: `add` refuses a duplicate id and an out-of-domain status. This handler adds the one
    check that only the CLI can make — that a named dep EXISTS. A milestone whose dep is a typo is
    permanently not-ready and `_blocker` reports it as blocked-on-a-thing-nobody-can-find, which reads as
    work in progress rather than as a mistake. `FI-7`'s failure was exactly a dependency naming something
    that existed nowhere, so the check goes where the name is first written.
    """
    child = _instant(ctx, parsed)
    roadmap = Roadmap(child)
    deps = parsed.all("dep")
    known = {m.id for m in roadmap.milestones()}
    unknown = [d for d in deps if d not in known]
    if unknown:
        raise BadInput(
            f"--dep names {', '.join(repr(u) for u in unknown)}, which is not on {roadmap.path}. A "
            f"milestone can only depend on one that already exists — add the dependency first. Known: "
            f"{', '.join(sorted(known)) or '(the roadmap is empty)'}.")
    m = Milestone(id=parsed.get("id"), title=parsed.get("title"),
                  status=parsed.get("status") or "blocked", deps=deps,
                  evidence=parsed.all("evidence"), owner=parsed.get("owner"))
    if ctx.dry_run:
        _emit(ctx, "milestone", [("dry-run", "the roadmap was not written"), ("id", m.id),
                                 ("title", m.title), ("status", m.status),
                                 ("deps", ", ".join(m.deps) or "(none)"), ("roadmap", str(roadmap.path))])
        return EXIT_OK
    roadmap.add(m)
    #: Readiness is DERIVED, so it is reported back rather than accepted from the caller: a milestone added
    #: as `ready` whose deps have not landed is NOT ready, and saying so here is cheaper than the
    #: coordinator discovering it at dispatch.
    ready = [x.id for x in roadmap.ready()]
    _emit(ctx, "milestone", [("added", m.id), ("title", m.title), ("status", m.status),
                            ("deps", ", ".join(m.deps) or "(none)"),
                            ("evidence", ", ".join(m.evidence) or "(none yet)"),
                            ("roadmap", str(roadmap.path)),
                            ("ready-now", "yes" if m.id in ready else
                             f"no — {roadmap.blocker_of(m.id)}")])
    return EXIT_OK


def _do_propose(ctx: Ctx, parsed: Parsed) -> int:
    """The WORKER's verb. It writes `proposals.json` and physically cannot move the roadmap.

    TWO instants, and conflating them was `SI-23`. A proposal has a **proposer** (`--instant`, whose id is
    what makes the coordinator's inbox attributable) and a **destination roadmap** (`--to`, the instant that
    holds `roadmap.json` — normally the coordinator's). `Roadmap.propose(instant, …)` has always taken them
    separately and `tests/test_roadmap.py::TestSingleWriter` has always asserted
    `proposal.instant == worker`; this handler passed the same value for both, so:

      * a worker could not propose AT ALL — the milestone was looked up in the worker's own empty roadmap
        and refused, which is `H2`, the case Plan 6 specified for exactly this and which had never run; and
      * every proposal was attributed to the roadmap's own instant, so the inbox could not say who asked.

    `--to` defaults to `--instant`, so the single-instant form a coordinator uses on itself is unchanged.
    """
    proposer = _instant(ctx, parsed)
    #: The destination roadmap, in a fixed order of authority, and WHICH ONE WON is reported. `SI-27`.
    #:
    #: The old rule was "`--to`, else self", and self is the answer that loses data: the proposal landed in
    #: the worker's own inbox, `harvest` applied it into the worker's own roadmap and closed the folder, and
    #: the coordinator's inbox held nothing. Measured at 0 pending against the coordinator and 1 against the
    #: worker, with no error anywhere.
    #:
    #: So `origin.json` — written by the DISPATCHER, not by the worker — sits between them. A worker no
    #: longer has to be told its destination in seed prose; it reads a fact recorded when it was created.
    #: Self remains the last resort because a coordinator proposing on its own roadmap is legitimate and has
    #: no origin — but that case now SAYS it is local, so a lost report is loud instead of silent.
    #: Resolved through the same rename-tolerant path as any other instant argument (`OI-16`), because a
    #: coordinator renames its own folder too.
    #: Read ONCE: the destination and the dispatched-for note are two questions about the same file, and
    #: reading it twice is how the two answers come to disagree about a file that changed in between.
    recorded = origin_mod.read(proposer)
    if parsed.get("to"):
        destination = _resolve_instant(ctx, parsed.get("to"))
        chosen = "named explicitly with --to"
    else:
        if recorded is not None:
            destination = _resolve_instant(ctx, recorded.coordinator)
            chosen = f"read from .fleet/{origin_mod.ORIGIN}, written by the dispatcher"
        else:
            destination = proposer
            chosen = ("LOCAL — no --to and no origin.json, so this proposal stays in this instant's own "
                      "inbox and NO COORDINATOR WILL SEE IT. Correct for an instant with no coordinator; "
                      "wrong for a dispatched worker")
    roadmap = Roadmap(destination)
    milestone, status = parsed.get("milestone"), parsed.get("status")
    evidence = parsed.all("evidence")
    #: Refused at the PRODUCER, against the DESTINATION's roadmap — the check `Roadmap.propose` documents.
    #: It only became reachable for a worker once the destination stopped being the worker itself.
    roadmap.milestone(milestone)
    #: `SI-32`, mechanism B. A claim of DONE from the wrong base is refused; anything else passes, because a
    #: worker legitimately reports `running` from wherever it happens to be while it works.
    if status == "done":
        _lineage_gate(ctx, proposer, "propose --status done")
    #: A worker proposing about a milestone it was not dispatched for is REPORTED, not refused. It could be
    #: wrong and it could be legitimate, and nothing here can tell which — refusing on a guess is `SI-25`
    #: again, a check that accuses before it can attribute. The coordinator sees this at `apply`.
    dispatched_for = None
    if recorded is not None and recorded.milestone and recorded.milestone != milestone:
        dispatched_for = (f"NOTE: this instant was dispatched for milestone {recorded.milestone!r} and is "
                          f"proposing about {milestone!r}. Reported, not refused — it may be deliberate.")
    extra = [("dispatched-for", dispatched_for)] if dispatched_for else []
    if ctx.dry_run:
        _emit(ctx, "propose", [("dry-run", "no proposal was written"), ("milestone", milestone),
                               ("status", status), ("proposer", str(proposer)),
                               ("roadmap", str(destination)), ("destination-chosen", chosen),
                               ("evidence", ", ".join(evidence))] + extra)
        return EXIT_OK
    proposal = roadmap.propose(proposer, milestone, status, evidence)
    _emit(ctx, "propose", [("milestone", proposal.milestone), ("status", proposal.status),
                           ("at", proposal.at), ("proposer", proposal.instant),
                           ("roadmap", str(destination)), ("destination-chosen", chosen),
                           ("evidence", ", ".join(proposal.evidence))] + extra
          + [("applied", "false — the roadmap is UNCHANGED until the coordinator applies "
                         "it (single writer)")])
    return EXIT_OK


def _do_apply(ctx: Ctx, parsed: Parsed) -> int:
    """The COORDINATOR's verb and the only path that changes a milestone status."""
    child = _instant(ctx, parsed)
    roadmap = Roadmap(child)
    milestone = parsed.get("milestone")
    pending = [proposal for proposal in roadmap.proposals() if proposal.milestone == milestone]
    if not pending:
        raise BadInput(
            f"no pending proposal names milestone {milestone!r} in {roadmap.proposals_path}. `apply` "
            "applies a worker's proposal; it does not invent a status.")
    if ctx.dry_run:
        rows = [("dry-run", "the roadmap was not written")]
        rows += [("would-apply", f"{p.milestone} -> {p.status} ({p.instant})") for p in pending]
        _emit(ctx, "apply", rows)
        return EXIT_OK
    rows = []
    for proposal in pending:
        applied = roadmap.apply(proposal)
        rows.append(("applied", f"{applied.id} -> {applied.status}"))
        rows.append(("evidence", ", ".join(applied.evidence)))
    _emit(ctx, "apply", rows)
    return EXIT_OK


# --- review / complete ----------------------------------------------------------------------------


def _finding_of(text: str) -> Finding:
    parts = str(text).split(":", 5)
    if len(parts) != 6:
        raise BadInput(
            "--finding takes `id:severity:status:location:finding:action`, six colon-separated fields; "
            f"got {text!r}. Every field is required: a finding with no location is a feeling and a "
            "finding with no action asks the reader to invent the remedy.")
    return Finding(id=parts[0], severity=parts[1], status=parts[2], location=parts[3],
                   finding=parts[4], action=parts[5])


def _do_review(ctx: Ctx, parsed: Parsed) -> int:
    """Record a structured round, then report the gate — decided from `review.json` and never from
    `REVIEW.md`, which this verb writes and no verb reads."""
    child = _instant(ctx, parsed)
    review = Review(child, now=ctx.now)
    verdict_asked = parsed.get("verdict")
    findings = [_finding_of(text) for text in parsed.all("finding")]
    rows = []
    if verdict_asked and not ctx.dry_run:
        made = review.add_round(parsed.get("scope", "all"), verdict_asked, findings)
        review.render()
        rows.append(Row(kind="round", subject=str(made.number), severity=INFO,
                        detail=f"scope {made.scope}, verdict {made.verdict}, "
                               f"{len(made.findings)} finding(s) at {made.at}"))
    elif verdict_asked:
        rows.append(Row(kind="round", subject="dry-run", severity=INFO,
                        detail=f"would record scope {parsed.get('scope', 'all')}, verdict "
                               f"{verdict_asked}, {len(findings)} finding(s); no ledger was written and "
                               f"{review.view_path()} was not rendered. The gate row below reflects the "
                               f"ledger WITHOUT this round, so it will read UNDECIDABLE for a first round — "
                               f"that is the current state, not a verdict on this input"))
    gate = review.gate(require_scope=parsed.get("require-scope"))
    rows.append(Row(kind="gate", subject=gate.guard,
                    severity=INFO if gate.allowed else VIOLATION, detail=gate.reason,
                    clears_when=gate.clears_when or "", clears_who=gate.clears_who or ""))
    for note in review.advisories():
        rows.append(Row(kind="advisory", subject=str(child), severity=INFO, detail=note))
    population = review.population()
    rows.append(Row(kind=POPULATION, subject=population["ledger"], severity=INFO,
                    detail=(f"examined {population['rounds']} round(s) "
                            f"[{', '.join(population['round_scopes']) or 'none'}], scopes covered "
                            f"{', '.join(population['scopes_covered']) or 'none'}, "
                            f"{population['findings']} finding(s), "
                            f"{len(population['open_blocking'])} open blocking")))
    _emit(ctx, "review", rows)
    #: A DRY RUN's exit code answers "would this action be admitted?", never "what does the pre-existing
    #: ledger say?". It used to return the gate's code — and on a dry run the round is not recorded, so the
    #: gate saw a ledger without it and a valid FIRST round always exited 2 (UNDECIDABLE) with NOTHING on
    #: stderr while stdout reported "would record ...". A worker doing the responsible thing — interrogating
    #: the gate non-destructively, which is exactly what `--dry-run` is for — got a bare failure code for
    #: input that was correct, and would reasonably start editing a finding string that was already fine.
    #: Found by a real dispatched worker in `§P`, which is the only place it could have been found: every
    #: hermetic test asserted the recorded path.
    #:
    #: The findings were parsed above (`_finding_of` refuses a malformed one at exit 2 before this point), so
    #: reaching here on a dry run means the input IS valid and the round WOULD be recorded.
    if ctx.dry_run and verdict_asked:
        return EXIT_OK
    return exit_code_for(gate)


def _do_complete(ctx: Ctx, parsed: Parsed) -> int:
    """The gate, then the rename. The rename IS the state transition, and it is the one signal a worker
    cannot produce by writing a document about being finished."""
    child = _instant(ctx, parsed)
    #: `SI-32`. Before the review gate, because the rename is the state transition and a completed instant on
    #: the wrong base is the artefact everything downstream trusts.
    _lineage_gate(ctx, child, "complete")
    review = Review(child, now=ctx.now)
    gate = review.gate(require_scope="all")
    name = InstantName.parse(child.name)
    target = child.parent / name.with_state("complete").format()
    if not gate.allowed:
        _emit(ctx, "complete", [("gate", gate.guard), ("allowed", "false"), ("reason", gate.reason),
                                ("clears_when", gate.clears_when or ""),
                                ("clears_who", gate.clears_who or "")])
        return exit_code_for(gate)
    if ctx.dry_run:
        _emit(ctx, "complete", [("dry-run", "the folder was not renamed"), ("gate", gate.guard),
                                ("allowed", "true"), ("would-rename", f"{child.name} -> {target.name}")])
        return EXIT_OK
    if target.exists():
        raise BadInput(f"{target} already exists; an instant may hold only one state (OBS-14)")
    child.rename(target)
    _emit(ctx, "complete", [("gate", gate.guard), ("from", child.name), ("to", target.name),
                            ("path", str(target))])
    return EXIT_OK


# --- abort ----------------------------------------------------------------------------------------
#
# FD-12's sharpest hole. `abort` was in `identity.STATES`, had three cells in `layout.REQUIREMENTS`, was
# in `reconcile.TERMINAL_FOLDER_STATES` and Plan 6 §K8 *requires* an `abort-compact` instant — and no verb
# could produce the folder. A state the model knows and the surface cannot reach is a state that gets
# reached by hand, which is how a rename becomes an untracked mutation.


def _do_abort(ctx: Ctx, parsed: Parsed) -> int:
    """Abandon an inflight instant, WITH A RECORDED REASON, as one transaction.

    Two properties carry this verb:

    **The reason is mandatory and recorded.** An abort with no reason is a deletion with a nicer name
    (FD-12) — the folder stops being work and nothing says why, which is the state a successor cannot
    read. It is written as structured state inside the instant (FD-3), never as a sentence in a document.
    An empty `--reason` is refused with a message that does NOT ask for the flag that was just supplied:
    `F7` is the shape where the diagnostic tells the caller to do what they have already done.

    **The order is: reason, session, lease, rename, stamp.** Every fallible step happens BEFORE the
    irreversible one, which is FD-14's rule applied to the other end of the lifecycle: a `release` refused
    because a live pid still sits in the slot (`OBS-48`) leaves an instant that is still `-inflight-` and a
    command that can simply be re-run, instead of an `-abort-` folder whose slot is still leased.
    """
    child = _instant(ctx, parsed)
    name = InstantName.parse(child.name)
    reason = str(parsed.get("reason") or "")
    if not reason.strip():
        raise BadInput(
            f"abort: the reason is empty (got {reason!r}). It is mandatory and it is recorded: an abort "
            "with no reason is a deletion with a nicer name (FD-12), and the successor who finds an "
            "`-abort-` folder has no other way to learn why the work stopped. State the reason in words "
            "a reader who was not here can act on — what changed, and what it invalidated.")
    if name.state != "inflight":
        raise BadInput(
            f"{child.name} is already `-{name.state}-`, and `abort` renames an inflight instant. An "
            "instant may hold only one state (OBS-14); re-aborting a terminal instant would either "
            "collide with the folder that exists or silently rewrite a recorded outcome.")
    target = child.parent / name.with_state("abort").format()
    if target.exists():
        raise BadInput(f"{target} already exists; an instant may hold only one state (OBS-14)")
    record = _record_for(ctx, child)
    body = {"reason": reason, "at": ctx.now(), "from": child.name, "to": target.name,
            "todo_id": record.todo_id if record is not None else ""}

    if ctx.dry_run:
        _emit(ctx, "abort", [
            ("dry-run", "nothing was renamed, released, closed or written"),
            ("would-rename", f"{child.name} -> {target.name}"),
            ("would-record", f"{ABORT_FILE}: {reason}"),
            ("would-close", (record.tmux if record is not None and record.tmux else "(no session)")),
            ("would-release", (record.slot if record is not None and record.slot else "(no slot)"))])
        return EXIT_OK

    reason_path = child / ".fleet" / ABORT_FILE
    reason_path.parent.mkdir(parents=True, exist_ok=True)
    reason_path.write_text(json.dumps(body, indent=2, ensure_ascii=False))
    if record is not None and record.tmux:
        ctx.sessions.kill(record.tmux)
    if record is not None and record.slot:
        ctx.pool.release(record.slot)
    child.rename(target)                       # THE state transition, and the last irreversible step
    if record is not None:
        record.closed_at = ctx.now()
        ctx.store.write(record)
    _emit(ctx, "abort", [
        ("from", child.name), ("to", target.name), ("path", str(target)),
        ("reason", reason), ("recorded_in", str(target / ".fleet" / ABORT_FILE)),
        ("closed", (record.tmux if record is not None and record.tmux else "(no session)")),
        ("released", (record.slot if record is not None and record.slot else "(no slot)")),
        ("record", (record.todo_id if record is not None else "(none in this store)"))])
    return EXIT_OK


# --- close ----------------------------------------------------------------------------------------


def _pane_refusal(ctx: Ctx, record: Record):
    """Why this pane must not be closed, as `(guard, reason, clears_when, clears_who)`, or `None`.

    The predicates are `session`'s and `pane-guard`'s — the SAME two, not a third copy. DA-2 enumerated
    six send paths, and a predicate restated per caller is how five of them keep the old behaviour.
    """
    tmux = record.tmux
    if not tmux or not ctx.sessions.alive(tmux):
        return None
    text = ctx.sessions.pane(tmux)
    if ctx.sessions.busy(text):
        return (PANE_GUARD_CODES[PANE_MID_TURN],
                f"{tmux} is still offering a way to interrupt, so it is mid-turn: closing it now ends a "
                f"turn in progress and whatever that turn had not yet written down",
                f"the turn finishes, or `fleet close --id {record.todo_id} {FORCE}` is said out loud",
                record.base_instant or record.todo_id)
    queued = ctx.sessions.unsubmitted(text)
    if queued is not None:
        return (PANE_GUARD_CODES[PANE_QUEUED_TEXT],
                f"{tmux} holds unsubmitted text in its input box ({queued!r}): closing it discards a "
                f"message somebody typed and never sent",
                f"the text is submitted or cleared, or `fleet close --id {record.todo_id} {FORCE}` is "
                f"said out loud",
                record.base_instant or record.todo_id)
    return None


def _do_close(ctx: Ctx, parsed: Parsed) -> int:
    """Shut a pane this store owns, and disarm the monitor by doing it (FD-10).

    `close` ends the session and stamps the record. It does **not** release the lease and does not apply a
    delta: those belong to `harvest` (the delta landed) and `reap` (nobody is in the slot any more), and a
    verb that quietly does a neighbour's job is how two writers appear. What it left behind is therefore
    NAMED, by slot — FD-14's rule, that a transaction which stops short says what it left rather than
    leaving it to be discovered.

    The two refusals are `pane-guard`'s own two non-safe answers for a live pane, and **each names its
    override**: a refusal a human cannot act on is a refusal that gets forced blindly (`OBS-48`), while a
    guard with no override is an alarm that blocks the fix (FD-9).
    """
    record = _record(ctx, parsed)
    refusal = None if parsed.on("force") else _pane_refusal(ctx, record)

    if ctx.dry_run:
        rows = [("dry-run", "nothing was closed, stamped or released"),
                ("record", record.todo_id),
                ("session", record.tmux or "(none)"),
                ("would-close", "false — refused" if refusal else "true")]
        if refusal:
            rows += [("refused", refusal[0]), ("reason", refusal[1]),
                     ("clears_when", refusal[2]), ("clears_who", refusal[3] or "the operator")]
        _emit(ctx, "close", rows)
        return EXIT_REFUSED if refusal else EXIT_OK

    if refusal:
        raise Refused(f"close: {refusal[0]} — {refusal[1]}. Override: {FORCE}.",
                      clears_when=refusal[2], clears_who=refusal[3] or "the operator")

    if record.tmux:
        ctx.sessions.kill(record.tmux)
    record.closed_at = ctx.now()
    ctx.store.write(record)
    _emit(ctx, "close", [
        ("record", record.todo_id),
        ("closed", record.tmux or "(no session)"),
        ("closed_at", record.closed_at),
        ("forced", "true" if parsed.on("force") else "false"),
        ("slot_still_held", (f"{record.slot} — released by `fleet harvest --id {record.todo_id}` when "
                             f"the delta lands, or by `fleet reap --base {record.base_instant}` once "
                             f"nothing is sitting in it") if record.slot else "(no slot)"),
        ("disarmed", "the monitor's arm set is recomputed from the join; this pane is no longer in it")])
    return EXIT_OK


# --- harvest --------------------------------------------------------------------------------------


def _unreported_to_coordinator(ctx: Ctx, child: Path):
    """-> a sentence if closing `child` would lose its report, else None.  `SI-27`.

    THE silent-loss case, and the one measured while designing the coordinator's loop: a worker was
    dispatched for a milestone, never got its status onto the coordinator's roadmap, and `harvest` then
    closed the session, released the slot and stamped the record. The worker looked finished, the board went
    quiet, and the project-level roadmap still read `blocked` on the work that was actually done. Nothing
    errored, because nothing was in a position to compare the two.

    All four conditions are required, and each one removes a legitimate case rather than a hypothetical:
      * the child records an origin WITH a milestone — otherwise this dispatch was not about roadmap work;
      * the coordinator still resolves — a coordinator that is gone is a different problem and not this
        check's to diagnose;
      * that milestone is NOT terminal at the coordinator — if it already reads done or dropped, the report
        arrived or the work was written off, and either way nothing is being lost;
      * and no proposal for it is PENDING there — a pending proposal means the report DID arrive and is
        merely unapplied, which `harvest` itself is about to do for the coordinator.

    So the refusal fires only when the report exists nowhere. It is a refusal rather than a warning because
    `harvest` is the step that makes the loss unrecoverable: after it the slot is gone, the session is dead
    and the record is stamped.
    """
    recorded = origin_mod.read(child)
    if recorded is None or not recorded.milestone:
        return None
    try:
        coordinator = _resolve_instant(ctx, recorded.coordinator)
    except BadInput:
        return None
    roadmap = Roadmap(coordinator)
    try:
        milestone = roadmap.milestone(recorded.milestone)
    except BadInput:
        return None
    if milestone.status in TERMINAL:
        return None
    if any(proposal.milestone == recorded.milestone for proposal in roadmap.proposals()):
        return None
    return (f"this instant was dispatched for milestone {recorded.milestone!r} on {coordinator}, and that "
            f"milestone still reads status={milestone.status!r} there with NO proposal pending. Harvesting "
            f"now would kill the session, release the slot and stamp the record while the project-level "
            f"roadmap never learns what happened — and after that the loss is unrecoverable.")


def _do_harvest(ctx: Ctx, parsed: Parsed) -> int:
    """The coordinator's transaction, plus the observation tick.

    With `--id` it is ONE transaction (§7): gate PASS ∧ folder renamed → apply the proposed roadmap delta
    (single writer) → close the session → release the slot → stamp the record → **and the row leaves the
    board**, which is what makes an orphan unreachable (FD-5). Without `--id` it is the tick alone.
    """
    rows = []
    if parsed.get("id"):
        record = _record(ctx, parsed)
        child = _child_of(ctx, record)
        review = Review(child, now=ctx.now)
        gate = review.gate(harvest=True)
        unreported = _unreported_to_coordinator(ctx, child)
        if not gate.allowed:
            rows.append(Row(kind="harvest-refused", subject=record.todo_id, severity=VIOLATION,
                            detail=gate.reason, clears_when=gate.clears_when or "",
                            clears_who=gate.clears_who or ""))
        elif unreported:
            rows.append(Row(
                kind="harvest-refused", subject=record.todo_id, severity=VIOLATION, detail=unreported,
                clears_when=("the worker proposes its final status — `fleet propose --milestone <m> "
                             "--status <s> --evidence <path>` from inside the instant, which now reaches "
                             "the coordinator by default — or the work is written off with `fleet abort "
                             "--instant <this> --reason <why>`"),
                clears_who="the dispatched instant, or the coordinator if it is abandoning the work"))
        elif ctx.dry_run:
            rows.append(Row(kind="would-harvest", subject=record.todo_id, severity=INFO,
                            detail=(f"the gate allows ({gate.guard}) and the folder is {child.name}; a "
                                    f"real run would apply "
                                    f"{len(Roadmap(child).proposals())} proposal(s), close {record.tmux}, "
                                    f"release {record.slot or '(no slot)'} and stamp the record. "
                                    f"Nothing was changed.")))
        else:
            roadmap = Roadmap(child)
            applied = []
            for proposal in roadmap.proposals():
                applied.append(roadmap.apply(proposal).id)
            if record.tmux:
                ctx.sessions.kill(record.tmux)
            # `SI-31`. STAMP BEFORE RELEASING. The order used to be release-then-stamp, and `J9` measured
            # what that costs: `SIGKILL` between the two left `slot_held: False` with `harvested_at: None` —
            # a FREE slot and a record that still reads in-flight. That state is both invisible and
            # unrecoverable: `board` shows a worker holding a slot it does not hold, the WIP cap counts it
            # forever, and there is no lease left for `reap` to reclaim, so nothing can ever clear it. It is
            # `SI-21`'s leaked-cap-slot arrived at by crash instead of by exception.
            #
            # True atomicity across a filesystem, a tmux server and a lease directory would need a journal.
            # The achievable property — and the one asserted — is that NO crash window leaves an
            # unrecoverable or invisible state, and ordering alone buys it:
            #
            #   crash before the stamp  -> session dead, record in-flight, slot STILL HELD. `status` reads
            #                              DEAD and `reap` reclaims the slot, because the writer is gone.
            #   crash after the stamp   -> record harvested, slot still held. Same recovery, and the cap no
            #                              longer counts a closed record.
            #   crash after the release -> fully committed.
            #
            # Every window is visible in `board`/`status` and cleared by a verb that already exists. The one
            # ordering that was NOT recoverable is the one that was in place.
            record.gate_verdict = gate.guard
            record.harvested_at = ctx.now()
            record.closed_at = ctx.now()
            ctx.store.write(record)
            if record.slot:
                ctx.pool.release(record.slot)
            rows.append(Row(kind="harvested", subject=record.todo_id, severity=INFO,
                            detail=(f"delta applied ({', '.join(applied) or 'none pending'}), session "
                                    f"{record.tmux} closed, slot {record.slot or '(none)'} released, "
                                    f"record stamped at {record.harvested_at}; the row has left the "
                                    f"board (FD-5)")))

    if ctx.dry_run:
        sources = ctx.harvest.sources()
        overdue = ctx.harvest.stale(ctx.now(), ctx.max_age_s, ctx.live_work_now())
        for source in sources:
            rows.append(Row(kind="source", subject=source.base, severity=INFO,
                            detail=(f"watched since {source.registered_at}, last run "
                                    f"{source.last_run or 'never'}; a dry run reads the registry and "
                                    f"records nothing, so no `last_run` was stamped")))
        rows.append(Row(kind=POPULATION, subject=str(ctx.harvest.path), severity=INFO,
                        detail=(f"examined {len(sources)} watched source(s), {len(overdue)} past the "
                                f"{ctx.max_age_s}s cadence window; dry run, nothing recorded")))
    else:
        rows += _rows_of(ctx.harvest.report(now=ctx.now(), max_age_s=ctx.max_age_s,
                                            live_work=ctx.live_work_now()))
    _emit(ctx, "harvest", rows)
    return _code_of(rows)


# --- the views ------------------------------------------------------------------------------------


def _do_board(ctx: Ctx, parsed: Parsed) -> int:
    _write(ctx, render.board(ctx.subjects(), porcelain=ctx.porcelain))
    return EXIT_OK


def _do_status(ctx: Ctx, parsed: Parsed) -> int:
    wanted = parsed.get("id")
    subjects = ctx.subjects()
    matches = [subject for subject in subjects if subject.identity == wanted]
    if not matches:
        matches = [subject for subject in subjects if wanted in subject.identity]
    if not matches:
        raise BadInput(
            f"no subject in the fleet has an identity matching {wanted!r}. Identities present: "
            + (", ".join(sorted(subject.identity for subject in subjects)) or "(none)"))
    if len(matches) > 1:
        raise BadInput(
            f"{wanted!r} matches {len(matches)} subjects: "
            + ", ".join(sorted(subject.identity for subject in matches))
            + ". Refusing to guess; every time this toolkit picked a winner from an ambiguous key it "
            "eventually picked a sibling's record (OBS-14).")
    _write(ctx, render.status(matches[0], porcelain=ctx.porcelain))
    return EXIT_OK


def _do_leases(ctx: Ctx, parsed: Parsed) -> int:
    _write(ctx, render.leases(ctx.pool, porcelain=ctx.porcelain))
    return EXIT_OK


def _do_roadmap(ctx: Ctx, parsed: Parsed) -> int:
    child = _instant(ctx, parsed)
    _write(ctx, render.roadmap_view(Roadmap(child), porcelain=ctx.porcelain))
    return EXIT_OK


# --- reconcile — the external monitor's entry point ------------------------------------------------
#
# FD-10: *`fleet reconcile` computes the arm set, deleting the watchdog's second reconciler.* The deleted
# one computed state from `/proc` and a hardcoded path to a tool this rebuild removes; this one asks the
# ONE join (`reconcile.reconcile`) and derives nothing of its own, which is the whole point — three views
# each deriving state from a different subset of the facts is how `board` called a session PARKED while
# `health` called the same records DEAD, *"and the one that is wrong is the one everybody reads."*


def _arm_refusal(subject) -> str:
    """Why the monitor may not act on this subject, or `""` when it may.

    An unknown session is NEVER armed. `D-6`: *"a tool that can kill a session it does not understand is a
    tool nobody will leave armed, and some of those sessions are people's"* — and `OBS-48` found one idle
    8d20h, which is exactly the shape that would be armed by a rule phrased as "everything alive".
    """
    if subject.kind != KIND_WORKER:
        return (f"{subject.kind}: no dispatch record in this store claims it, so nothing here is "
                "authorised to send it a keystroke — it is reported for a human to decide (D-6)")
    if subject.state == COMPLETE:
        return "the instant folder is terminal (`-complete-` or `-abort-`); the work is over"
    if subject.evidence.get("liveness", "none") == "none":
        return f"no live process and no session answers for {subject.evidence.get('tmux') or 'it'}"
    return ""


def _do_reconcile(ctx: Ctx, parsed: Parsed) -> int:
    """The arm set, read-only. One row per subject, armed or not, and the reason either way."""
    base = parsed.get("base", "")
    subjects = [subject for subject in ctx.subjects()
                if not base or subject.evidence.get("base") == base]
    rows, armed = [], []
    for subject in sorted(subjects, key=lambda item: item.identity):
        why = _arm_refusal(subject)
        if not why:
            armed.append(subject.identity)
        rows.append(Row(
            kind=UNARMED if why else ARMED, subject=subject.identity, severity=INFO,
            detail=(f"state {subject.state}, session {subject.evidence.get('tmux', '') or '(none)'}, "
                    + (f"not armed: {why}" if why else
                       f"armed: the monitor MUST call `fleet {PANE_GUARD} --pane "
                       f"{subject.evidence.get('tmux', '') or subject.identity}` and branch on the code "
                       f"before any send"))))
    rows.append(Row(
        kind=POPULATION, subject=base or "every base", severity=INFO,
        detail=(f"examined {len(subjects)} subject(s) from the one join, {len(armed)} armed "
                f"({', '.join(armed) or 'none'}); every send is gated on `{PANE_GUARD}` at the single "
                f"choke point, because DA-2 enumerated six send paths and a requirement phrased per-path "
                f"fixes one and leaves five")))
    _emit(ctx, "reconcile", rows)
    return EXIT_OK


# --- the pool: enrol, unenrol, reap ----------------------------------------------------------------
#
# `pool.enroll`/`unenroll`/`reap` and `workspace.set_golden` were public API with NO verb (FD-12), which
# made Plan 6 §C (slot enrolment) and §C9/C10 (the golden) unrunnable and left the pool adjustable only by
# editing its store by hand.


def _do_clone(ctx: Ctx, parsed: Parsed) -> int:
    """Grow the pool FROM the declared golden, then enrol the result.  `SI-19`.

    The verb that makes the declared golden an INPUT. Before this, `golden()` had one caller — `set-golden`'s
    own echo-back — so the golden was write-only and a pool grew only by `enroll`ing directories somebody had
    duplicated by hand, outside the tool, with nothing checking they came from the golden at all. That is the
    half of `SI-19` that was reported as implemented and did not exist.

    Two steps in one transaction, and the ORDER is the safety property: copy, verify HEAD parity, and only
    then enrol. A slot enrolled before it was verified is a slot a dispatch can lease while it is still being
    written, and the pool's own rule is that `mkdir` IS the lock — enrolment is the moment it becomes takeable.
    A parity failure therefore leaves an unenrolled directory NAMED in the output rather than a leased one:
    nothing deletes it, because no verb here deletes outward state, and a copy somebody can inspect beats a
    copy the tool tidied away.
    """
    workspace = Workspace(ctx.home, git=ctx.git)
    target = Path(parsed.get("slot"))
    #: A comma list of repo NAMES, not `repo=sha` pairs: parity is golden-vs-clone, so there is no expected
    #: sha to state — the golden's own HEAD is the expectation.
    repos = [r.strip() for r in str(parsed.get("verify-repos") or "").split(",") if r.strip()]

    if ctx.dry_run:
        golden = workspace.golden()
        _emit(ctx, "clone", [("dry-run", "nothing was copied or enrolled"), ("golden", str(golden)),
                             ("target", str(target)),
                             ("target_exists", "true — a real run would REFUSE" if target.exists()
                              else "false"),
                             ("verify_repos", ", ".join(sorted(repos)) or "(none named)")])
        return EXIT_OK

    report = workspace.clone(target)
    rows = [("golden", report["golden"]), ("target", report["target"]),
            ("files_copied", str(report["files"]))]

    #: Parity is checked on the repos the caller NAMES. Nothing is inferred from the tree: a clone whose
    #: parity was checked over "whatever looked like a repo" would report a green it did not measure for the
    #: repo that mattered.
    mismatched = []
    if repos:
        for repo, gold_head, clone_head, same in workspace.clone_parity(target, repos):
            rows.append((f"parity.{repo}",
                         f"{(clone_head or 'unreadable')[:12]} vs golden {(gold_head or 'unreadable')[:12]}"
                         f" — {'same' if same else 'DIFFERENT'}"))
            if not same:
                mismatched.append(repo)
    else:
        rows.append(("parity", "not checked: no --verify-repos named, so this clone is unverified"))

    if mismatched:
        raise Refused(
            f"the clone at {target} does NOT match the golden for {', '.join(mismatched)}, so it was left "
            f"UNENROLLED — a slot enrolled before it is verified can be leased while it is still wrong, and "
            f"every `base-check` in it would then compare against the wrong commit. The directory is left in "
            f"place and named here rather than removed; inspect it, then enrol it by hand or delete it.",
            clears_when=f"{target} matches the golden for {', '.join(mismatched)}, or is removed")

    ctx.pool.enroll(target)
    rows.append(("enrolled", str(target)))
    rows.append(("order", "copied, then verified, THEN enrolled — enrolment is the moment a slot becomes "
                          "leasable, so it comes last"))
    _emit(ctx, "clone", rows)
    return EXIT_OK


def _do_enroll(ctx: Ctx, parsed: Parsed) -> int:
    """Put an EXISTING workspace directory into the pool. Opt-in, always.

    Enrolment never creates the workspace: a pool that mkdir's its own slots hands out an empty tree with
    a cold cache and calls it a workspace (`OI-6`). A path that is not a directory is refused by
    `pool.enroll`, whose message names the fix — this verb does not keep a second copy of that validator.
    """
    path = Path(parsed.get("slot"))
    if ctx.dry_run:
        _emit(ctx, "enroll", [
            ("dry-run", "nothing was enrolled"),
            ("would-enroll", str(path)),
            ("slot", path.name or "(no basename)"),
            ("directory-exists", "true" if path.is_dir() else "false"),
            ("note", "the real run validates through pool.enroll, which owns that message")])
        return EXIT_OK
    ctx.pool.enroll(path)
    _emit(ctx, "enroll", [("slot", path.name), ("path", str(path.resolve())),
                          ("enrolled", str(len(ctx.pool.slots()))),
                          ("slots", ", ".join(ctx.pool.slots()))])
    return EXIT_OK


def _do_unenroll(ctx: Ctx, parsed: Parsed) -> int:
    """Take a slot out of the pool. A leased slot is refused unless `--force` is said out loud."""
    slot = parsed.get("slot")
    forced = parsed.on("force")
    held = ctx.pool.lease(slot)

    if ctx.dry_run:
        rows = [("dry-run", "nothing was unenrolled"), ("slot", slot),
                ("leased", f"{held.todo_id} for {held.base_instant}" if held else "false"),
                ("would-unenroll", "false — refused" if (held and not forced) else "true")]
        _emit(ctx, "unenroll", rows)
        return EXIT_REFUSED if (held and not forced) else EXIT_OK

    try:
        ctx.pool.unenroll(slot, force=forced)
    except Refused as exc:
        # The pool's message names the work it would strand and says an override exists; this adds the
        # exact token a CALLER types. The two halves are split on purpose — the pool cannot know it was
        # reached from a command line, so it never spells the override in a language it cannot verify
        # (`FI-19b`: it used to say `pass force=True`, which is python quoted at an operator).
        raise Refused(f"{exc} Override: `fleet unenroll --slot {slot} {FORCE}`.",
                      clears_when=exc.clears_when, clears_who=exc.clears_who) from None
    _emit(ctx, "unenroll", [("slot", slot), ("forced", "true" if forced else "false"),
                            ("released", held.todo_id if held else "(was free)"),
                            ("enrolled", str(len(ctx.pool.slots()))),
                            ("slots", ", ".join(ctx.pool.slots()) or "(none)")])
    return EXIT_OK


def _do_reap(ctx: Ctx, parsed: Parsed) -> int:
    """Free every stale lease this base OWNS, and report the ones it does not.

    `RI-31`: the ownership guard refused **correctly** and read as a bug purely because it never said whose
    lease it was. So the refusal names the owning base, the clearing actor is that owner, and `--all` is
    quoted as the override — *"not yours to clear" is a state, not a failure*, and a state has to be
    legible or it gets forced.

    The freed set comes from the reap's own report, and used to be derived by DIFFING the leases before and
    after. `FI-22`: with two reapers running, the diff answers "what ended up free", which is every slot —
    so a slot freed once by the other process is announced by both. `ReapReport.freed` is what THIS call
    gave back. The report rides on the strict refusal too, because that refusal is raised after the owned
    leases have already been given back and reporting only what the exception carries would hide real work.

    `unfreed` is the other half: a stale lease this base owns that could not be given back is named, with
    why, rather than escaping as a traceback. *Absence is never success* — a reap that omits what it failed
    to free is reporting a clean sweep it did not perform.
    """
    base = parsed.get("base")
    every = parsed.on("all")
    before = {slot: ctx.pool.lease(slot) for slot in ctx.pool.slots()}
    before = {slot: lease for slot, lease in before.items() if lease is not None}

    if ctx.dry_run:
        rows = []
        for slot, lease in sorted(before.items()):
            mine = every or not lease.base_instant or lease.base_instant == base
            rows.append(Row(
                kind=REAPED if mine else REAP_REFUSED, subject=slot, severity=INFO,
                detail=(f"dry run: leased to {lease.todo_id} (tmux {lease.tmux}) by "
                        f"{lease.base_instant or 'an untagged (legacy) claim'}; session alive: "
                        f"{'yes' if ctx.sessions.alive(lease.tmux) else 'no'}; "
                        + ("this base's to clear" if mine else
                           f"NOT this base's to clear — {base!r} is not its owner"))))
        rows.append(Row(
            kind=POPULATION, subject=base or ALL_EFFORTS, severity=INFO,
            detail=(f"dry run over {len(ctx.pool.slots())} enrolled slot(s), {len(before)} leased; "
                    f"nothing was released. Staleness here is by SESSION liveness only — the cwd-holder "
                    f"half (OBS-48) is evaluated by the real run, and it can only make this set smaller, "
                    f"never larger")))
        _emit(ctx, "reap", rows)
        return EXIT_OK

    refusal = None
    try:
        report = ctx.pool.reap(base_instant=base, all_efforts=every, strict=True)
    except Refused as exc:
        refusal = exc
        report = getattr(exc, "report", None) or ReapReport()
    freed = list(report.freed)

    rows = []
    for slot in freed:
        was = before.get(slot)
        rows.append(Row(
            kind=REAPED, subject=slot, severity=INFO,
            detail=(f"the lease held by {was.todo_id if was else 'an unread claim'} (tmux "
                    f"{was.tmux if was else '?'}, effort "
                    f"{(was.base_instant if was else '') or 'untagged'}) was stale — no live session and "
                    f"nothing holding {was.path if was else slot} as its cwd — and has been given back "
                    f"BY THIS CALL")))
    for slot, why in report.unfreed:
        was = before.get(slot)
        rows.append(Row(
            kind=REAP_UNFREED, subject=slot, severity=VIOLATION,
            detail=(f"a stale lease this base owns could not be given back, and is named rather than "
                    f"omitted: {why}"
                    + (f" Lease was todo {was.todo_id} (tmux {was.tmux})." if was else "")),
            clears_when=f"the claim directory for {slot!r} can be removed",
            clears_who=base or ALL_EFFORTS))
    # `SI-7`. An interrupted claim gets its OWN row and its own kind, never a `REAPED` row: a reader who
    # sees "the lease held by … was stale … and has been given back" concludes a worker finished, when in
    # fact a process died between the lease body's write and its rename. The distinction is the whole
    # reason `ReapReport` carries a fourth list. Before this, such a slot produced no row at all and the
    # population line counted it as leased — an exit 0 over a permanently lost workspace.
    for slot, what in report.reclaimed:
        rows.append(Row(
            kind=REAP_RECLAIMED, subject=slot, severity=INFO,
            detail=(f"an INTERRUPTED claim was cleared BY THIS CALL: the directory that wins the slot "
                    f"existed with no lease body inside it, so no owner could be named — {what}. The slot "
                    f"is claimable again. This is a dead writer, not work that finished")))
    if refusal is not None:
        owner = refusal.clears_who or "an untagged (legacy) claim"
        rows.append(Row(
            kind=REAP_REFUSED, subject=owner, severity=VIOLATION,
            detail=(f"a stale lease here is owned by {owner}, not by {base!r}, so it was left alone: "
                    f"{refusal}. Override: `fleet reap {ALL_EFFORTS}`, said out loud."),
            clears_when=refusal.clears_when or f"{owner} reaps it, or `fleet reap {ALL_EFFORTS}` is run",
            clears_who=owner))
    rows.append(Row(
        kind=POPULATION, subject=base or ALL_EFFORTS, severity=INFO,
        detail=(f"examined {len(ctx.pool.slots())} enrolled slot(s), {len(before)} of them leased; "
                f"{len(freed)} freed by this call, {len(report.reclaimed)} interrupted claim(s) reclaimed, "
                f"{len(report.unfreed)} could not be freed, "
                f"{len(report.skipped)} left to their owners; "
                f"scope {'every effort' if every else repr(base)}")))
    _emit(ctx, "reap", rows)
    return EXIT_REFUSED if (refusal is not None or report.unfreed) else EXIT_OK


# --- set-golden -----------------------------------------------------------------------------------


def _do_set_golden(ctx: Ctx, parsed: Parsed) -> int:
    """Declare the golden workspace, then RE-READ IT THROUGH THE CONSUMER (`declare`'s shape).

    There is deliberately no fallback to the most recent dispatch record: inheriting the golden that way
    is how the predecessor kept working with nothing declared, which made an unset setting
    indistinguishable from a correct one (`FR2-13.2`/`MI-7`). The path is validated at SET time by
    `workspace.set_golden`, because a golden that does not exist is otherwise discovered at clone time —
    inside a dispatch that has already claimed a slot.
    """
    path = Path(parsed.get("path"))
    workspace = Workspace(ctx.home, git=ctx.git)
    if ctx.dry_run:
        _emit(ctx, "set-golden", [("dry-run", "the golden was not declared"),
                                  ("would-set", str(path)),
                                  ("directory-exists", "true" if path.is_dir() else "false")])
        return EXIT_OK
    workspace.set_golden(path)
    value = Workspace(ctx.home, git=ctx.git).golden()       # a FRESH consumer, not the writer's return
    _emit(ctx, "set-golden", [("golden", str(value)), ("asked", str(path)),
                              ("declared_in", str(ctx.home / GOLDEN_FILE))])
    return EXIT_OK


# --- lint -----------------------------------------------------------------------------------------

#: The one file where a declaration-shaped line is a NEAR MISS rather than a mention. DA-6 drop 3: rev 1
#: scoped this rule to *"anything still carried in prose"*, which the no-prose ruling makes vacuous by its
#: own scoping — while the failure survives, because the shipped profiles still INSTRUCT the worker to
#: write the line into this exact file. `AC-9` asserted the line has no effect and never that anybody is
#: TOLD to write it. Scoping it here is also what keeps a register that DISCUSSES the defect (this
#: instant's own `ISSUES.md`) out of the population — a permanently-red lint trains everyone to ignore red.
NEAR_MISS_FILES = ("HANDOFF.md",)

#: A line whose shape a consumer was once expected to read a phase out of: an optional heading, bullet or
#: emphasis run, the word, a separator, a value. Assembled as a pattern rather than spelled as an example
#: so this module's own source is not a member of the population it checks (`FI-1`).
_DECLARATION_SHAPED = re.compile(
    #: Emphasis may sit on EITHER side of the separator — `**Phase**:` and `Phase:**` both occur, and a
    #: pattern that allowed it only before the colon still missed `## **Phase:** AWAITING-CI`.
    r"^[\s>*_#`|-]*" + "phase" + r"[\s*_`]*[:=][\s*_`]*(?P<value>[A-Za-z][A-Za-z0-9._/-]*)"
    r"[*_`]*\s*(?P<tail>.*)$",
    re.IGNORECASE)

#: A line that RETRACTS a declaration is not a near miss, and this is the only thing that lets `G3` and `G4`
#: both hold. `§G3` measured the old rule flagging 2 of 4 shapes: emphasis was permitted only BEFORE the word,
#: so `**Phase:** AWAITING-CI` slipped through, and the value was anchored at end of line, so
#: `## Phase: AWAITING-CI — waiting on the CI queue` slipped through too.
#:
#: Closing the trailing-prose gap by itself would have broken `G4`, whose fixture — *"Phase: AWAITING-CI was
#: declared and is now REMOVED"* — is ALSO value-then-prose. A shape-only rule cannot separate them, and `G4`
#: exists because a naive version of this lint fired on 5 of 5 live instants. So the rule reads the tail:
#: retraction language exempts the line.
#:
#: STATED AS A HEURISTIC, because it is one. It can be fooled — *"Phase: AWAITING-CI, and the removal is
#: pending"* would be exempted wrongly. That is the cheaper error: this rule's whole purpose is that *the
#: author must be TOLD, not merely ignored*, and a lint that cries wolf over every retraction gets switched
#: off, after which it tells nobody anything.
_RETRACTION = re.compile(
    r"\b(remov|retract|rescind|withdraw|no longer|cleared|superseded|obsolete)", re.IGNORECASE)


def near_miss_rows(child: Path) -> list:
    """Declaration-shaped prose with no declaration behind it, plus the population examined.

    This reads a `.md` file and derives no control signal from it: the phase comes from
    `.fleet/declare.json` through `store.Declarations`, and the markdown is the **text under lint** — the
    standing `profiles` already has for `charter.md` (AC-2 as FD-8 made it precise).
    """
    declared = Declarations(child).phase()
    rows, scanned, shaped = [], 0, 0
    for name in NEAR_MISS_FILES:
        path = Path(child) / name
        if not path.is_file():
            continue
        scanned += 1
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if _DECLARATION_SHAPED.match(line) is None:
                continue
            if _RETRACTION.search(line):
                #: Counted nowhere: a retraction is not a near miss, so it is not part of the population this
                #: rule reports over either.
                continue
            shaped += 1
            #: Truthiness, not `is not None`. A STORED EMPTY phase used to satisfy this and suppress the rule
            #: entirely — see `SI-36`. `declare` now refuses an empty phase, and this is the second door,
            #: because a store written by an older build can still carry one.
            if declared:
                continue
            rows.append(Row(
                kind=NEAR_MISS, subject=f"{path}:{number}", severity=VIOLATION,
                detail=(f"{name}:{number} carries the declaration-shaped line {line.strip()!r} and "
                        f"{Declarations(child).path} declares no phase, so the line is read by NOTHING. "
                        "RCF-9: a worker wrote exactly this, exactly as its brief worded it, and at a WIP "
                        "cap of 1 it held the effort's only dev slot for the length of a CI queue."),
                clears_when=("the worker runs `fleet declare phase <value>`, or the line is deleted from "
                             "the document"),
                clears_who="the worker that wrote the line"))
    rows.append(Row(
        kind=POPULATION, subject=str(child), severity=INFO,
        detail=(f"examined {scanned} of {len(NEAR_MISS_FILES)} near-miss file(s) "
                f"({', '.join(NEAR_MISS_FILES)}); {shaped} declaration-shaped line(s) found; the "
                f"declared phase is {declared!r}")))
    return rows


def _do_brief(ctx: Ctx, parsed: Parsed) -> int:
    """What a dispatched instant needs to know about itself, in one screen. Read-only.

    The alternative first instruction in a worker's skill was `cat .fleet/origin.json`, which is hand-parsing
    machine state — the one thing the north star forbids. Six questions, one row each, and the fifth is what
    earns the verb: WHERE the next `propose` will land. A worker that can see its report would stay local
    cannot walk into losing it, which is `SI-27`'s failure closed from the worker's side.

    Every field is read through the SAME API the enforcing verb uses — `origin_mod.read` as `propose` does,
    `Review.gate` as `complete` does, `Roadmap.blocker_of` as `dispatch` does. A briefing computed a second
    way is a briefing that can disagree with the gate it is preparing you for.
    """
    child = _instant(ctx, parsed)
    recorded = origin_mod.read(child)
    rows = []

    if recorded is None:
        rows.append(Row(kind="origin", subject=child.name, severity=INFO,
                        detail=("no origin.json: this instant was not dispatched by a coordinator (it was "
                                "created by `init`, or it IS a coordinator)")))
    else:
        rows.append(Row(kind="origin", subject=child.name, severity=INFO,
                        detail=(f"dispatched by {recorded.coordinator} at {recorded.dispatched_at} for "
                                f"milestone {recorded.milestone or '(none)'}")))

    coordinator = None
    if recorded is not None:
        try:
            coordinator = _resolve_instant(ctx, recorded.coordinator)
        except BadInput as exc:
            rows.append(Row(kind="milestone", subject=recorded.milestone or "(none)", severity=VIOLATION,
                            detail=f"the coordinator no longer resolves: {exc}",
                            clears_when="the coordinator instant is present under the instants directory",
                            clears_who=COORDINATOR))
    if coordinator is not None and recorded.milestone:
        roadmap = Roadmap(coordinator)
        try:
            milestone = roadmap.milestone(recorded.milestone)
            blocker = roadmap.blocker_of(recorded.milestone)
            #: The stored status and the derived readiness are DIFFERENT FACTS and the row must not run them
            #: together. It used to read `status=blocked, owner=…; ready`, and a real worker in `§P` reported
            #: exactly that: *"says status=blocked AND ready on the same row, with no blocker named. I could
            #: not tell from the row whether something was actually blocking me."* Nothing was. The stored
            #: status is a LABEL a coordinator set; readiness is recomputed from whether the deps landed, so a
            #: `blocked` milestone whose deps have all landed IS ready and the label is simply stale.
            rows.append(Row(
                kind="milestone", subject=milestone.id, severity=INFO,
                detail=(f"{milestone.title!r}; owner={milestone.owner or '(unowned)'}; "
                        f"stored status={milestone.status} (a label the coordinator set) — "
                        + (f"and NOT READY to start: {blocker}" if blocker else
                           "and READY to start: readiness is DERIVED from whether its deps landed, so a "
                           "stale 'blocked' label does not block you")),
                clears_when=blocker or "", clears_who=COORDINATOR if blocker else ""))
        except BadInput as exc:
            rows.append(Row(kind="milestone", subject=recorded.milestone, severity=VIOLATION,
                            detail=f"not on the coordinator's roadmap: {exc}",
                            clears_when="the coordinator adds it with `fleet milestone`",
                            clears_who=COORDINATOR))

    declarations = Declarations(child)
    rows.append(Row(kind="phase", subject=child.name, severity=INFO,
                    detail=(f"phase={declarations.phase() or '(none declared)'}, "
                            f"parked={declarations.parked() or '(not parked)'}")))

    gate = Review(child, now=ctx.now).gate(require_scope="all")
    #: INFO even when the gate would refuse: at the start of the work it always would, and a verb that
    #: reports that as a violation exits non-zero for every healthy worker. The WORD is in the detail.
    rows.append(Row(kind="review", subject=child.name, severity=INFO,
                    detail=f"the gate would say {'ALLOW' if gate.allowed else 'REFUSE'}: {gate.reason}",
                    clears_when=gate.clears_when or "", clears_who=gate.clears_who or ""))

    #: THE row. `propose`'s destination resolution, reported BEFORE a proposal is written rather than after.
    if coordinator is not None:
        destination_detail = (f"a `fleet propose` with no --to will reach {coordinator} — read from "
                              f".fleet/{origin_mod.ORIGIN}, written by the dispatcher")
    else:
        destination_detail = ("LOCAL — a `fleet propose` with no --to stays in THIS instant's own inbox and "
                              "NO COORDINATOR WILL SEE IT. Correct for an instant with no coordinator; "
                              "wrong for a dispatched worker, and the reason to check before reporting")
    rows.append(Row(kind="destination", subject=child.name, severity=INFO, detail=destination_detail))

    #: What stands between this instant and being closed out, so "am I done?" is answerable from a command.
    record = _record_for(ctx, child)
    outstanding = []
    if recorded is not None and recorded.milestone and coordinator is not None:
        pending = [p for p in Roadmap(coordinator).proposals() if p.milestone == recorded.milestone]
        if not pending:
            outstanding.append(f"no proposal for {recorded.milestone} is pending at the coordinator")
    if not gate.allowed:
        outstanding.append("the review gate does not allow completion")
    if "-inflight-" in child.name:
        outstanding.append("the folder is still -inflight- (the rename IS the state transition)")
    if record is not None and record.lineage_base:
        outstanding.append(f"a lineage base is recorded ({record.lineage_base}); `fleet base-check --id "
                           f"{record.todo_id}` decides whether a claim of done will be refused")
    #: Outstanding work is information by definition — this verb is read at the START of a job.
    rows.append(Row(kind="outstanding", subject=child.name, severity=INFO,
                    detail=("; ".join(outstanding) if outstanding
                            else "nothing outstanding that this verb can see")))

    rows.append(Row(kind=POPULATION, subject=child.name, severity=INFO,
                    detail=(f"{len(rows)} orientation row(s) for {child}; read-only, and every field is "
                            f"read through the same API the enforcing verb uses")))
    _emit(ctx, "brief", rows)
    return EXIT_OK


def _do_base_check(ctx: Ctx, parsed: Parsed) -> int:
    """Is this workspace positioned on the base its milestone builds on?  `SI-32`.

    Read-only, and the verb `SI-19` said was missing: `Workspace.base_check` has existed, correct and tested,
    with **zero callers anywhere** — the fourth instance in this lineage of a capability that could not be
    invoked. It is what `propose --status done` and `complete` consult, so running it by hand answers the
    same question the gate will.
    """
    record = _record(ctx, parsed)
    rows, fatal = _lineage_rows(ctx, record)
    if not rows:
        rows = [Row(kind="lineage", subject=record.todo_id, severity=INFO,
                    detail=("no git lineage is recorded for this dispatch, so there is nothing to check and "
                            "nothing gates a claim of done. That is correct for a coordinator, a compaction, "
                            "or any dispatch made without --lineage-base"))]
    rows.append(Row(kind=POPULATION, subject=record.todo_id, severity=INFO,
                    detail=(f"expected {record.lineage_base or '(nothing)'} in {_slot_of(ctx, record)}, "
                            f"lineage-mode={record.lineage_mode or '(none)'}, "
                            f"{len(fatal)} repo(s) blocking a claim of done")))
    _emit(ctx, "base-check", rows)
    return EXIT_ATTENTION if fatal else EXIT_OK


def _do_lint(ctx: Ctx, parsed: Parsed) -> int:
    child = _instant(ctx, parsed)
    rows = _rows_of(layout.validate(child))
    rows += near_miss_rows(child)
    rows += _rows_of(ctx.harvest.lint(ctx.store))
    _emit(ctx, "lint", rows)
    return _code_of(rows)


# --- verify ---------------------------------------------------------------------------------------
#
# F-14 / `FI-3`. Four instances of a prescribed re-derivation command that nobody ever ran, and **three of
# the four were destructive or false-green** — including a `RUNBOOK §4` restore step that would have
# reverted three commits of shipped work, and a prescribed post-dispatch assertion that could never pass.
# `RUNBOOK.md` is specified as *"runnable commands only"* with nothing that ever runs them, so a recipe
# that has never been executed is a violation here.

#: The shapes a recipe uses to change something the sandbox does not own. **Assembled from parts** so this
#: module's source does not contain the strings it bans: `FI-1` is this build's own instance of a checker
#: tripped by its own words, and it has now been authored twice.
_OUTWARD_SHAPES = (
    ("rm" + " -", "it deletes"),
    ("git" + " push", "it publishes"),
    ("git" + " merge", "it merges"),
    ("git" + " commit", "it writes history"),
    ("git" + " reset", "it rewrites history"),
    ("git" + " clean", "it deletes"),
    ("gh" + " pr merge", "it merges"),
    ("gh" + " pr create", "it publishes"),
    ("gh" + " release", "it publishes"),
    ("sudo", "it escalates out of the sandbox"),
    ("mv ", "it moves something"),
    ("truncate", "it truncates"),
    ("> /", "it redirects to an absolute path"),
    (">> /", "it appends to an absolute path"),
)

#: The subset the outward-state audit greps this module's own source for. Same assembly, same reason.
FORBIDDEN_COMMANDS = ("git" + " push", "git" + " merge", "git" + " commit", "gh" + " pr merge",
                      "gh" + " release", "rm" + " -rf", "rm" + " -fr")

#: The in-process ways to delete something.
DELETE_CALLS = frozenset({"rmtree", "remove", "removedirs", "unlink", "rmdir"})
#: Every way to spawn a process behind a handler's back. Split from the deletes because the audit's two
#: verdicts are different: a delete has to be inside a tree its caller owns, while a spawn has to be one of
#: the three declared, injectable seams (`FI-27a`).
SPAWN_CALLS = frozenset({
    "run", "Popen", "call", "check_call", "check_output", "system", "execv", "execvp", "spawn",
})

#: Calls no handler may reach. Publishing and merging are shell shapes and are covered above.
FORBIDDEN_CALLS = DELETE_CALLS | SPAWN_CALLS

#: Fences whose contents are recipes. A fence with no language is prose in a box.
_FENCE = re.compile(r"^\s*```+\s*(?P<lang>[A-Za-z0-9_+-]*)\s*$")
_RECIPE_LANGS = ("bash", "sh", "shell", "zsh", "console")


@dataclass(frozen=True)
class Recipe:
    command: str
    line: int
    source: str


def recipes_of(path: Path) -> list:
    """Every runnable command in a document's shell fences, in file order.

    Continuations are joined, comments and blank lines are dropped, and a fence with no language is left
    alone. `RUNBOOK.md` is read here as the **recipe list**, never for a control signal (AC-2 / FD-8).
    """
    path = Path(path)
    if not path.is_file():
        return []
    out, inside, pending, start = [], False, "", 0
    for number, raw in enumerate(path.read_text().splitlines(), start=1):
        fence = _FENCE.match(raw)
        if fence is not None:
            inside = fence.group("lang").lower() in _RECIPE_LANGS if not inside else False
            pending = ""
            continue
        if not inside:
            continue
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not pending:
            start = number
        if line.endswith("\\"):
            pending = f"{pending}{line[:-1].strip()} "
            continue
        out.append(Recipe(command=f"{pending}{line}".strip(), line=start, source=str(path)))
        pending = ""
    return out


def outward_reason(command: str, sandbox: Path) -> str:
    """Why this recipe must not be run, or `""`.

    Refused **before** execution, deliberately: the failure mode of finding out by trying is doing the
    thing you were checking you could not do, and the real instance was a restore step that would have
    reverted three commits of shipped work.
    """
    lowered = str(command).lower()
    for shape, why in _OUTWARD_SHAPES:
        if shape in lowered:
            return f"{why} — the recipe contains the shape {shape!r}"
    for token in re.findall(r"(?<![\w/=])/[^\s'\";|&)]*", str(command)):
        if not token.startswith(str(sandbox)) and _redirects_to(command, token):
            return f"it writes to {token}, which is outside the sandbox"
    return ""


def _redirects_to(command: str, token: str) -> bool:
    return bool(re.search(r"(?:>>?|\btee\b)\s*" + re.escape(token), str(command)))


def _sandbox_env(sandbox: Path) -> dict:
    return {"HOME": str(sandbox), "TMPDIR": str(sandbox), "PWD": str(sandbox),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}


def _do_verify(ctx: Ctx, parsed: Parsed) -> int:
    child = _instant(ctx, parsed)
    documents = [child / "RUNBOOK.md", child / "evidence" / "INDEX.md"]
    recipes = [recipe for document in documents for recipe in recipes_of(document)]
    sandbox = Path(tempfile.mkdtemp(prefix="fleet-verify-"))
    rows, executed = [], []
    for recipe in recipes:
        reason = outward_reason(recipe.command, sandbox)
        if reason:
            rows.append(Row(
                kind=OUTSIDE_SANDBOX, subject=recipe.command, severity=VIOLATION,
                detail=(f"{recipe.source}:{recipe.line} — refused BEFORE execution: {reason}. The "
                        f"recipe {recipe.command!r} was not run, because finding out by running it is "
                        f"the mistake F-14 measured four times."),
                clears_when="the recipe is rewritten to touch only paths the sandbox owns",
                clears_who="the author of that document"))
            continue
        code, out, err = ctx.runner(recipe.command, cwd=sandbox, env=_sandbox_env(sandbox))
        executed.append(recipe.command)
        rows.append(Row(
            kind=EXECUTED, subject=recipe.command, severity=INFO if code == 0 else VIOLATION,
            detail=(f"{recipe.source}:{recipe.line} ran in {sandbox} and exited {code}"
                    + (f": {_oneline(err) or _oneline(out)}" if code else "")),
            clears_when="" if code == 0 else "the recipe runs clean in a sandbox",
            clears_who="" if code == 0 else "the author of that document"))
    for recipe in recipes:
        if recipe.command in executed:
            continue
        rows.append(Row(
            kind=NEVER_EXECUTED, subject=str(child), severity=VIOLATION,
            detail=(f"the recipe {recipe.command!r} at {recipe.source}:{recipe.line} has NEVER been "
                    f"executed. A recipe nobody runs is prose with a shell prompt, and its failure mode "
                    f"is discovered by the successor who depends on it (F-14: three of four instances "
                    f"were destructive or false-green)."),
            clears_when="the recipe is made runnable in a sandbox and this verb executes it",
            clears_who="the author of that document"))
    rows.append(Row(
        kind=POPULATION, subject=str(child), severity=INFO,
        detail=(f"examined {len(recipes)} recipe(s) from "
                f"{', '.join(document.name for document in documents if document.is_file()) or 'nothing'}; "
                f"{len(executed)} executed, {len(recipes) - len(executed)} refused or unexecuted; "
                f"sandbox {sandbox} (left in place for inspection)")))
    _emit(ctx, "verify", rows)
    return _code_of(rows)


# --- pane-guard -----------------------------------------------------------------------------------

#: What a claude pane renders when it is idle and not busy. Needed because an idle pane offers neither an
#: interrupt hint nor unsubmitted text, and "no evidence of claude" must not read as "safe to send".
CLAUDE_MARKERS = ("esc to interrupt", "esc to cancel", "? for shortcuts", "/ for commands",
                  "# for memory", "bypass permissions", "new task?", "claude code")


def _is_claude(sessions, text: str, name: str = "") -> bool:
    """Is this pane a claude? PROCESS FIRST, then the screen.

    `SI-38`. The glyph test alone answers "does the visible tail contain UI chrome", which is a different
    question and drifts from it the moment a long answer scrolls the chrome away. Asking whether a live
    claude process is attributed to the session is evidence; the markers are a fallback for the case the
    process probe cannot attribute (a claude the pane owns indirectly, or a pane on a server we can see
    but whose processes we cannot).
    """
    if sessions.is_claude_process(name):
        return True
    lowered = str(text).lower()
    if any(marker in lowered for marker in CLAUDE_MARKERS):
        return True
    return sessions.busy(text) or sessions.unsubmitted(text) is not None


def _do_pane_guard(ctx: Ctx, parsed: Parsed) -> int:
    """The contract the external monitor is REQUIRED to call before any send-keys (FD-10).

    DA-2 enumerated **six** send paths today, so this sits at the choke point rather than being restated
    per path: a requirement phrased per-path would fix one and leave five. The codes are the interface —
    `0` safe · `10` queued text · `11` mid-turn · `12` not-claude · `13` unknown pane — and a caller
    branches on the number, never on the sentence.
    """
    pane = parsed.get("pane")
    if not ctx.sessions.alive(pane):
        code, detail = PANE_UNKNOWN, (f"no live process and no session answer for {pane!r}; sending keys "
                                      "to a pane nobody can name is the send with no target")
    else:
        text = ctx.sessions.pane(pane)
        if not _is_claude(ctx.sessions, text, pane):
            code, detail = PANE_NOT_CLAUDE, (f"{pane} is alive and nothing in its tail is claude; a send "
                                             "here goes to somebody else's shell")
        elif ctx.sessions.busy(text):
            code, detail = PANE_MID_TURN, (f"{pane} is still offering a way to interrupt, so it is "
                                           "mid-turn; a send now is queued behind the current turn")
        elif ctx.sessions.unsubmitted(text) is not None:
            queued = ctx.sessions.unsubmitted(text)
            code, detail = PANE_QUEUED_TEXT, (f"{pane} holds unsubmitted text in its input box "
                                              f"({queued!r}); a send would concatenate onto it")
        else:
            code, detail = PANE_SAFE, f"{pane} is a quiet claude pane with an empty input box"
    _emit(ctx, PANE_GUARD, [("code", str(code)), ("verdict", PANE_GUARD_CODES[code]),
                            ("pane", pane), ("detail", detail)])
    return code


# --- compaction-status ----------------------------------------------------------------------------


def _do_compaction_status(ctx: Ctx, parsed: Parsed) -> int:
    """Is a compaction holding the effort? Kept as its own verb because a compaction is exclusive for a
    different reason than the cap is full — unfoldable rebase debt, not attention."""
    base = parsed.get("base", "")
    subjects = [subject for subject in ctx.subjects()
                if subject.kind == KIND_WORKER and (not base
                                                    or subject.evidence.get("base") == base)]
    #: `SI-30`. The SAME derivation the guard uses — records UNION the instants directory. This verb read
    #: only the reconciled subjects, so a compaction that existed as a folder with no record was reported as
    #: "no compaction of this effort is inflight" while `dispatch` was, correctly for that reading and
    #: catastrophically in fact, admitting work under it. A status verb and the guard it reports on must not
    #: be able to disagree, which is why this is one function and not two loops.
    blocking_names = guards.blocking_compactions(ctx.guard_ctx(parsed, base=base))
    rows, inflight = [], list(blocking_names)
    for subject in subjects:
        name = Path(subject.evidence.get("instant", "").replace(" (missing)", "")).name
        try:
            parsed_name = InstantName.parse(name)
        except FleetError:
            continue
        if parsed_name.optype != "compact":
            continue
        blocking = name in blocking_names
        rows.append(Row(kind="compaction", subject=name,
                        severity=VIOLATION if blocking else INFO,
                        detail=(f"state {subject.state}; "
                                + ("inflight, and a compaction is EXCLUSIVE: every dispatch waits, even "
                                   "at zero active-dev work" if blocking else "finished")),
                        clears_when=(f"{name} renames its folder to `-complete-` or `-abort-`"
                                     if blocking else ""),
                        clears_who=name if blocking else ""))
    #: `SI-30`. A blocking compaction with NO record gets its own row rather than only moving the exit code:
    #: it is the case the whole issue was about, and a freeze that is in force but unnamed is a refusal the
    #: operator cannot act on. `reported` is what the loop above already covered.
    reported = {row.subject for row in rows}
    for name in blocking_names:
        if name in reported:
            continue
        rows.append(Row(
            kind="compaction", subject=name, severity=VIOLATION,
            detail=("inflight ON DISK with no record of its own, and a compaction is EXCLUSIVE: every "
                    "dispatch waits. This is the shape that was invisible before SI-30 — a compaction "
                    "instant created as a folder (which is how maintain-workspace's compact op creates "
                    "one) has no record for the reconciled join to find"),
            clears_when=f"{name} renames its folder to `-complete-` or `-abort-`",
            clears_who=name))
    compaction_rows = [row for row in rows if row.kind == "compaction"]
    gctx = ctx.guard_ctx(parsed, base=base)
    verdict = guards.CompactionExclusive().evaluate(gctx)
    rows.append(Row(kind="admission", subject=verdict.guard,
                    severity=INFO if verdict.allowed else VIOLATION, detail=verdict.reason,
                    clears_when=verdict.clears_when or "", clears_who=verdict.clears_who or ""))
    rows.append(Row(kind=POPULATION, subject=base or "every base", severity=INFO,
                    detail=(f"examined {len(subjects)} recorded subject(s) AND the instants directory; "
                            f"{len(compaction_rows)} compaction(s) seen, {len(inflight)} inflight")))
    _emit(ctx, "compaction-status", rows)
    return EXIT_ATTENTION if inflight else EXIT_OK


# --- selftest -------------------------------------------------------------------------------------

SELFTEST_COMMAND = "python3 -m unittest discover -s tests"

#: The paths the suite actually covers. `AC-10`: the tree state is ALWAYS stamped, and the suite refuses
#: **only** when the dirt is inside these — refuse-on-dirty alone blocks a legitimate push whenever a
#: concurrent writer is mid-edit, which is the alarm that blocks the fix (rev 1 kept the stamp and dropped
#: the refusal half).
COVERED_PATHS = ("src/", "tests/")

#: The environment mark that says "a suite is already running". `selftest` runs the suite, and the suite
#: contains generated cases that invoke every verb — including this one — so without a re-entrancy guard
#: `selftest` recurses without bound. Found by the generated last-with-no-value matrix, which hit the
#: `timeout` wall on `selftest --porcelain`: the check for a hang caught a different infinite loop than the
#: one it was written for, which is the best possible outcome for that check.
SELFTEST_GUARD = "FLEET_SELFTEST"


def _package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _do_selftest(ctx: Ctx, parsed: Parsed) -> int:
    root = _package_root()
    if os.environ.get(SELFTEST_GUARD):
        # `FI-25`: the re-entrancy guard and §9's population rule were mutually exclusive as written, and
        # both are load-bearing. The guard prevents an unbounded recursion; the population rule exists
        # because *a check whose scope narrows silently reads as a pass* (`OBS-49`) — and a verb that
        # covered NOTHING is the extreme case of a narrowed scope, so it is the case the rule most needs
        # to hold for. Refusing to recurse is a real answer, but "0 of the population" is part of that
        # answer and was being left unsaid. Both rows, one branch: nothing is deleted to make the other
        # work. The consequence was worse than a red test — the suite `selftest` runs failed the contract,
        # so the `suite` row below was ALWAYS a violation and `selftest` could never exit 0.
        _emit(ctx, "selftest", [
            Row(kind="not-recursing", subject=str(root), severity=INFO,
                detail=(f"{SELFTEST_GUARD} is set, so a suite run is already in progress and this verb "
                        f"did not start another. `selftest` runs the suite and the suite invokes every "
                        f"verb, so recursing here is unbounded — reported, not failed, because refusing "
                        f"to recurse is the correct answer and not a fault.")),
            Row(kind=POPULATION, subject=str(root), severity=INFO,
                detail=(f"examined 0 subject(s): the suite was not run and 0 of {len(COVERED_PATHS)} "
                        f"covered prefix(es) ({', '.join(COVERED_PATHS)}) were checked, because "
                        f"{SELFTEST_GUARD} is set. This verdict covers NOTHING and says so — a scope "
                        f"that narrows to zero in silence reads as a pass (OBS-49).")),
        ])
        return EXIT_OK
    code, out, err = ctx.runner(SELFTEST_COMMAND, cwd=root,
                               env={**os.environ, "PYTHONPATH": str(root / "src"),
                                    SELFTEST_GUARD: "1"})
    rows = [Row(kind="suite", subject=SELFTEST_COMMAND,
                severity=INFO if code == 0 else VIOLATION,
                detail=f"exited {code}: {_oneline(err) or _oneline(out) or 'no output'}",
                clears_when="" if code == 0 else "the suite is green",
                clears_who="" if code == 0 else "whoever last changed a covered path")]
    _, head = ctx.git(["rev-parse", "HEAD"], root)
    _, status = ctx.git(["status", "--porcelain"], root)
    dirty = [line[3:].strip() for line in str(status).splitlines() if line.strip()]
    #: `git status --porcelain` reports paths relative to the REPOSITORY ROOT, not to the directory it was run
    #: in — so once this package became a SUBDIRECTORY of its repo, every path arrived as `fleet/src/...` and
    #: nothing matched `COVERED_PATHS`. The dirty-inside-coverage refusal silently stopped firing, which is the
    #: worst shape of failure available to a control: it kept reporting, and reported clean. `M13` caught it.
    #:
    #: `rev-parse --show-prefix` is the package's own path within the repo (empty when they coincide), so
    #: stripping it makes every path package-relative. A path OUTSIDE the package keeps its repo-relative form
    #: and therefore correctly fails to match a covered prefix.
    _, prefix = ctx.git(["rev-parse", "--show-prefix"], root)
    prefix = str(prefix).strip()
    if prefix:
        dirty = [path[len(prefix):] if path.startswith(prefix) else path for path in dirty]
    inside = sorted(path for path in dirty if any(path.startswith(p) for p in COVERED_PATHS))
    # The stamp is unconditional. A verdict with no tree state behind it cannot be re-derived later.
    rows.append(Row(kind="tree", subject=_oneline(head) or "(no commit)", severity=INFO,
                    detail=(f"{len(dirty)} modified path(s), {len(inside)} of them inside the covered "
                            f"paths ({', '.join(COVERED_PATHS)}): "
                            f"{', '.join(inside) or 'none'}")))
    if inside:
        rows.append(Row(kind="dirty-inside-coverage", subject=", ".join(inside), severity=VIOLATION,
                        detail=("the suite covers these paths and they are modified, so this verdict "
                                "does not describe what is on disk"),
                        clears_when="the covered paths are committed or reverted, then selftest re-runs",
                        clears_who="whoever is mid-edit"))
    rows.append(Row(kind=POPULATION, subject=str(root), severity=INFO,
                    detail=(f"ran {SELFTEST_COMMAND} from {root}; examined {len(dirty)} modified "
                            f"path(s) against {len(COVERED_PATHS)} covered prefix(es)")))
    _emit(ctx, "selftest", rows)
    return EXIT_ATTENTION if (code != 0 or inside) else EXIT_OK


# --- the registry ---------------------------------------------------------------------------------


def _verb(name: str, handler: Callable, read_only: bool, help_text: str, flags=(),
          checker: bool = False) -> VerbSpec:
    """Build one spec. `--dry-run` is APPENDED FROM `read_only`, never typed per verb: the next mutating
    verb somebody adds gets an interrogable form whether or not they remembered to ask for one.

    `checker` is passed through and never inferred: §9's population rule is applied to whatever this says,
    so it is said here beside the handler rather than read off a column tuple two modules away (`FI-19c`).
    """
    declared = tuple(flags) + COMMON_FLAGS + (() if read_only else (DRY_RUN_FLAG,))
    return VerbSpec(name=name, flags=declared, handler=handler, read_only=read_only, help=help_text,
                    checker=checker)


VERBS = {spec.name: spec for spec in (
    _verb("init", _do_init, False, "bootstrap a new instant from the layout matrix", (
        Flag("--name", True, True, "the instantName, dashless camelCase after normalisation"),
        Flag("--base", True, False, f"the base instant ({ROOT_BASE} is the root)"),
        Flag("--optype", True, False, "append | compact"),
    )),
    _verb("dispatch", _do_dispatch, False, "evaluate every gate, then dispatch one worker", (
        Flag("--profile", True, True, "the profile directory; its kind is DECLARED in profile.json"),
        Flag("--title", True, True, "the worker's title; becomes the instantName"),
        Flag("--base", True, False, "the dispatching base instant"),
        Flag("--optype", True, False, "append | compact; must agree with the profile's kind"),
        Flag("--from", True, False,
             "the DISPATCHING instant. Recorded in the child's .fleet/origin.json so the child's `propose` "
             "reaches THIS roadmap instead of its own; required with --milestone"),
        Flag("--milestone", True, False,
             "the milestone on --from's roadmap this dispatch is for. Refused unless it is READY and "
             "unclaimed; claimed on success, so two instants cannot take one milestone"),
        Flag("--lineage-base", True, False,
             "the GIT base to build on, as `repo=sha,repo=sha`. The single authority: rendered into the "
             "seed and charter, and `propose --status done`/`complete` refuse if the slot is not there"),
        Flag("--lineage-mode", True, False,
             "code (must be AT or DESCENDED FROM the base) | analysis (base fetched but not checked out is "
             "fine, and keeps the prebuilt native artifacts valid). Defaults to code"),
        Flag("--slot", True, False, "a specific enrolled slot instead of the first free one"),
        Flag("--cap", True, False, "the WIP cap, said out loud"),
        Flag("--override", True, False, "override the refusing rules WITH A STATED REASON"),
    )),
    _verb("resume", _do_resume, False, "adopt an existing conforming instant; NO admission rule (FD-9)", (
        Flag("--instant", True, True, "the instant to adopt"),
        Flag("--slot", True, False, "the slot it occupies"),
        Flag("--tmux", True, False, "its session name"),
        Flag("--profile", True, False, "the profile it was rendered from"),
    )),
    _verb("declare", _do_declare, False, "declare a phase and print what the CONSUMER now reads", (
        Flag("--instant", True, True, "the declaring instant"),
        Flag("--phase", True, True, "the phase; awaiting-ci is the one the WIP cap excludes"),
    )),
    _verb("park", _do_park, False, "record a parked decision as structured state", (
        Flag("--instant", True, True, "the instant"),
        Flag("--question", True, True, "the question; an empty park is not a park"),
    )),
    _verb("unpark", _do_unpark, False, "clear a parked decision", (
        Flag("--instant", True, True, "the instant"),
    )),
    _verb("milestone", _do_milestone, False,
          "the COORDINATOR puts a milestone ON the roadmap; the only way work becomes dispatchable", (
        Flag("--instant", True, True, "the instant holding the roadmap"),
        Flag("--id", True, True, "the milestone id, unique within the roadmap"),
        Flag("--title", True, True, "what the milestone is; an untitled milestone cannot be dispatched"),
        Flag("--status", True, False, "blocked|ready|running|awaiting-ci|done|dropped (default: blocked)"),
        Flag("--dep", True, False, "a milestone id this one depends on; repeatable, and each must EXIST"),
        Flag("--evidence", True, False, "an evidence path; repeatable"),
        Flag("--owner", True, False, "informational only — readiness never reads it"),
    )),
    _verb("propose", _do_propose, False, "the WORKER's status proposal; never a roadmap write", (
        Flag("--instant", True, True, "the PROPOSING instant — its id is what attributes the proposal"),
        Flag("--to", True, False, "the instant holding the roadmap to propose INTO; defaults to --instant"),
        Flag("--milestone", True, True, "the milestone id"),
        Flag("--status", True, True, "blocked|ready|running|awaiting-ci|done|dropped"),
        Flag("--evidence", True, True, "an evidence path; repeatable, and at least one is required"),
    )),
    _verb("apply", _do_apply, False, "the COORDINATOR applies a proposal; the single writer", (
        Flag("--instant", True, True, "the instant holding the roadmap"),
        Flag("--milestone", True, True, "the milestone id"),
    )),
    _verb("review", _do_review, False, "record a structured round and report the gate", checker=True,
          flags=(
        Flag("--instant", True, True, "the instant under review"),
        Flag("--scope", True, False, "format|alignment|code|all"),
        Flag("--verdict", True, False, "READY|READY-WITH-FIXES|NOT-READY"),
        Flag("--finding", True, False, "id:severity:status:location:finding:action; repeatable"),
        Flag("--require-scope", True, False, "the scope the gate demands across ALL rounds"),
    )),
    _verb("complete", _do_complete, False, "pass the gate, then rename the folder -complete-", (
        Flag("--instant", True, True, "the instant"),
    )),
    _verb("abort", _do_abort, False,
          "abandon an inflight instant: rename it -abort- WITH A RECORDED REASON (FD-12)", (
        Flag("--instant", True, True, "the instant to abandon"),
        Flag("--reason", True, True,
             "why the work stopped; mandatory and recorded — an abort with no reason is a deletion "
             "with a nicer name"),
    )),
    _verb("close", _do_close, False,
          "shut a pane this store owns and stamp the record; disarms the monitor (FD-10)", (
        Flag("--id", True, True, "the record whose session is being closed"),
        Flag(FORCE, False, False, "close a mid-turn pane or one holding unsubmitted text anyway"),
    )),
    _verb("harvest", _do_harvest, False, "the harvest transaction, plus the observation tick",
          checker=True, flags=(
        Flag("--id", True, False, "the record to harvest; omit for the tick alone"),
        Flag("--max-age", True, False, f"the cadence window in seconds (default {DEFAULT_MAX_AGE_S})"),
    )),
    _verb("clone", _do_clone, False,
          "duplicate the declared golden into a new slot and enrol it; the verb that makes the golden an "
          "INPUT rather than a declaration nothing reads (SI-19)", (
        Flag("--slot", True, True, "the path to create; refused if it already exists"),
        Flag("--verify-repos", True, False,
             "repos to check HEAD parity on, as `alpha,beta` — named, never inferred, because parity over "
             "'whatever looked like a repo' reports a green it did not measure"),
    )),
    _verb("enroll", _do_enroll, False, "put an EXISTING workspace directory into the pool; opt-in", (
        Flag("--slot", True, True, "the workspace directory; its basename becomes the slot name"),
    )),
    _verb("unenroll", _do_unenroll, False, "take a slot out of the pool", (
        Flag("--slot", True, True, "the slot name"),
        Flag(FORCE, False, False, "unenroll a slot that is currently leased, stranding that work"),
    )),
    _verb("reap", _do_reap, False, "free every stale lease this base OWNS; name the ones it does not",
          checker=True, flags=(
        Flag("--base", True, False, "the base whose leases are this caller's to clear"),
        Flag(ALL_EFFORTS, False, False, "reap across every effort — said out loud, never a default"),
    )),
    _verb("set-golden", _do_set_golden, False,
          "declare the golden workspace; there is deliberately no fallback (MI-7)", (
        Flag("--path", True, True, "the golden workspace directory; validated at SET time"),
    )),
    _verb("board", _do_board, True, "every subject HOLDING A SLOT, and nothing else (FD-4)"),
    _verb("status", _do_status, True, "one subject in full, with the evidence behind its state", (
        Flag("--id", True, True, "the subject identity, or a unique substring of it"),
    )),
    _verb("leases", _do_leases, True, "every enrolled slot and who holds it"),
    _verb("roadmap", _do_roadmap, True, "milestones, readiness, blockers and pending proposals",
          checker=True, flags=(
        Flag("--instant", True, True, "the instant holding the roadmap"),
    )),
    _verb("reconcile", _do_reconcile, True,
          "the ARM SET the external monitor reads, from the one join (FD-10); read-only",
          checker=True, flags=(
        Flag("--base", True, False, "restrict to one base"),
    )),
    _verb("brief", _do_brief, True,
          "what a dispatched instant needs to know about itself: coordinator, milestone, phase, gate, "
          "where its next report will land, and what is outstanding",
          checker=True, flags=(
        Flag("--instant", True, True, "the instant to brief; use `.` from inside it"),
    )),
    _verb("base-check", _do_base_check, True,
          "is this workspace positioned on the base its milestone builds on? (SI-19/SI-32)",
          checker=True, flags=(
        Flag("--id", True, True, "the subject identity, or a unique substring of it"),
    )),
    _verb("lint", _do_lint, True, "the layout matrix, the watched-source registry, the near-miss rule",
          checker=True, flags=(
        Flag("--instant", True, True, "the instant to check"),
    )),
    _verb("verify", _do_verify, True, "EXECUTE every documented recipe in a sandbox (F-14)",
          checker=True, flags=(
        Flag("--instant", True, True, "the instant whose recipes are checked"),
    )),
    _verb(PANE_GUARD, _do_pane_guard, True,
          "the send-keys contract: 0 safe / 10 queued / 11 mid-turn / 12 not-claude / 13 unknown", (
        Flag("--pane", True, True, "the pane (session) name"),
    )),
    _verb("compaction-status", _do_compaction_status, True,
          "whether a compaction is holding every dispatch", checker=True, flags=(
        Flag("--base", True, False, "restrict to one base"),
    )),
    _verb("selftest", _do_selftest, True,
          "discover and run every suite; the tree state is ALWAYS stamped (AC-10)", checker=True),
)}

#: The porcelain schema per verb, declared as data so a consumer and a test read the column count off the
#: surface rather than off a comment that can go stale (`W2-20`'s class).
PORCELAIN_COLUMNS = {
    "init": KV_COLUMNS,
    "dispatch": KV_COLUMNS,
    "resume": KV_COLUMNS,
    "declare": KV_COLUMNS,
    "park": KV_COLUMNS,
    "unpark": KV_COLUMNS,
    "milestone": KV_COLUMNS,
    "propose": KV_COLUMNS,
    "apply": KV_COLUMNS,
    "complete": KV_COLUMNS,
    "abort": KV_COLUMNS,
    "close": KV_COLUMNS,
    "clone": KV_COLUMNS,
    "enroll": KV_COLUMNS,
    "unenroll": KV_COLUMNS,
    "set-golden": KV_COLUMNS,
    PANE_GUARD: KV_COLUMNS,
    "review": ROW_COLUMNS,
    "harvest": ROW_COLUMNS,
    "lint": ROW_COLUMNS,
    "verify": ROW_COLUMNS,
    "reap": ROW_COLUMNS,
    "reconcile": ROW_COLUMNS,
    "compaction-status": ROW_COLUMNS,
    "selftest": ROW_COLUMNS,
    "brief": ROW_COLUMNS,
    "base-check": ROW_COLUMNS,
    "board": render.BOARD_COLUMNS,
    "status": render.STATUS_COLUMNS,
    "leases": render.LEASE_COLUMNS,
    "roadmap": render.ROADMAP_COLUMNS,
}

def checker_verbs(verbs: dict = None) -> tuple:
    """The verbs that report findings, read off `VerbSpec.checker` — a DECLARATION, not a coincidence.

    Each one emits a `population` row: §9 is *never silent about a population it could not cover*, and
    `OBS-49` is a check whose scope narrowed silently and therefore read as a pass.

    This used to be `columns == ROW_COLUMNS` over `PORCELAIN_COLUMNS`, which classified `roadmap` correctly
    **by accident**: `render.ROADMAP_COLUMNS` is a different tuple object that happens to hold the same six
    names. `OBS-44`: a property that holds because two things share a value is not a property — add a
    column to either tuple and a checker silently stops being one, taking §9's population rule with it.
    The table is a parameter so the derivation can be exercised over a verb table this module does not
    export; a classification nobody can probe is a classification nobody can falsify (`FI-19c`).
    """
    return tuple(sorted(name for name, spec in (VERBS if verbs is None else verbs).items()
                        if spec.checker))


CHECKER_VERBS = checker_verbs()


# --- the cadence trigger --------------------------------------------------------------------------


def _cadence(ctx: Ctx, verb: str) -> list:
    """Evaluate cadence staleness and print every overdue obligation to STDERR.

    Called from `main` for **every** verb, which is the whole point. DA-6 drop 1, Critical: rev 1 made
    cadence pure state and named no evaluator, so the alarm fired only if somebody ran the very verb they
    had stopped running — *a cadence that is pure state is a cadence nobody reads* — and the observed
    failure was 19 hours of silence from an actor who had stalled. `git gc --auto`'s shape; no daemon.

    stderr, never stdout: stdout is machine-parseable data and commentary goes to stderr (`NFR2-7`), so a
    tick piping a porcelain form through `cut` is not broken by an alarm firing behind it.
    """
    try:
        overdue = ctx.harvest.stale(ctx.now(), ctx.max_age_s, ctx.live_work_now())
    except Exception as exc:                       # a broken registry must not break the verb
        print(f"{CADENCE_PREFIX} could not be evaluated during {verb!r}: {exc} · clears when: the "
              f"watched-source registry is readable · clears who: the coordinator", file=ctx.err)
        return []
    for source in overdue:
        since = source.last_run or source.registered_at
        print(f"{CADENCE_PREFIX} {source.base} was last harvested at {since}, past the "
              f"{ctx.max_age_s}s window, while work is live — a register nobody reads is the silent "
              f"source OBS-68 was · clears when: `fleet harvest` runs against {source.issues_path} · "
              f"clears who: the coordinator of that effort, or this loop's own tick", file=ctx.err)
    return overdue


def _report_error(exc: BaseException, err) -> None:
    print(f"{type(exc).__name__}: {exc}", file=err)
    for label, attribute in (("blocker", "blocker"), ("clears when", "clears_when"),
                             ("clears who", "clears_who")):
        value = getattr(exc, attribute, None)
        if value:
            print(f"  {label}: {value}", file=err)


def main(argv: list, *, stdout=None, stderr=None, context=None) -> int:
    """Run one verb. Returns a code from the registry, always.

    The handler's code is returned UNCHANGED. Coercing an unregistered code here would hide exactly the
    defect the suite exists to catch — a verb answering with a number no caller was told about — so the
    enforcement is the generated check over the failure matrix and not a clamp in this function.
    """
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    argv = list(argv)
    verb = argv[0] if argv else ""
    spec = VERBS.get(verb)
    try:
        if spec is None:
            raise BadInput(_unknown_verb(verb))
        parsed = parse(spec, argv[1:])
    except BadInput as exc:
        print(str(exc), file=err)
        print(usage(verb if spec is not None else None), file=err)
        return EXIT_BAD_INPUT

    if parsed.on(HELP):
        # On STDOUT and exiting 0: help that was asked for is the answer, not a diagnostic. Answered here,
        # before `default_context` — a request for usage must not need a readable `FLEET_HOME` — and before
        # `_cadence`, because printing usage is not a run of the verb and must not stamp anything. The text
        # is `usage(verb)`, i.e. derived from the spec: no verb has a help string to go stale, and nothing
        # here can print source code (`M14`'s other half).
        print(usage(verb), file=out)
        return EXIT_OK

    try:
        ctx = (default_context if context is None else context)(parsed, out, err)
    except FleetError as exc:
        _report_error(exc, err)
        return exc.exit_code

    if parsed.get("max-age") is not None:
        try:
            ctx.max_age_s = int(parsed.get("max-age"))
        except (TypeError, ValueError):
            print(f"--max-age takes an integer number of seconds; got {parsed.get('max-age')!r}",
                  file=err)
            return EXIT_BAD_INPUT

    # BEFORE the handler, for every verb. Staleness is asked before it can be answered: `harvest` stamps
    # `last_run` as it runs, so evaluating afterwards would make the cadence check pass forever — which is
    # the same ordering trap `harvest.report` documents inside itself.
    _cadence(ctx, verb)

    try:
        code = spec.handler(ctx, parsed)
    except FleetError as exc:
        _report_error(exc, err)
        code = exc.exit_code
    except OSError as exc:
        # `SI-22`. A real filesystem failure — `PermissionError` on an unreadable slot, `FileExistsError` on
        # a path a concurrent actor created — is not a `FleetError`, so it used to escape `main` entirely:
        # the handler's rollback sentence printed, and then a full Python traceback, exit 1. §D measured
        # both (`D9b`, `D10a`). The exit code was fine, since 1 is registered — but §9's contract is that an
        # operator gets a sentence they can act on, and a traceback is the shape that contract exists to
        # forbid. `FI-19b`'s lesson, one layer out: the message is read by whoever typed the command.
        #
        # Caught HERE rather than per handler so no handler can grow a path that forgets it, and reported
        # with the errno text intact — the useful part is which path and which permission, and paraphrasing
        # that would lose the only detail worth having.
        print(f"{type(exc).__name__}: {exc}", file=err)
        print(f"The filesystem refused an operation {verb!r} needed. This is the machine's answer, not a "
              f"refusal by a fleet rule: nothing above this line was rolled back by this handler unless it "
              f"said so. Check the path named above — its permissions, whether it already exists, and "
              f"whether another actor created it.", file=err)
        code = EXIT_ATTENTION
    return code


if __name__ == "__main__":                                  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
