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
import shlex
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from fleet import EXIT_ATTENTION, EXIT_BAD_INPUT, EXIT_CODES, EXIT_OK, EXIT_REFUSED, __version__
from fleet import guards, layout, peers as peers_mod, render, seedcheck
from fleet.atomic import atomic_symlink, atomic_write
from fleet.errors import BadInput, FleetError, Refused
from fleet.harvest import DEFAULT_MAX_AGE_S, REGISTER_NAME, Harvest
from fleet.identity import ROOT_BASE, InstantName, resolve
from fleet.layout import INFO, VIOLATION
from fleet.pool import Pool, ReapReport
from fleet.profiles import Profile
from fleet import root as root_mod
from fleet.reconcile import (COMPLETE, KIND_WORKER, PHASE_AWAITING_CI, RUNNING, needs_a_human,
                             reconcile)
from fleet.release import (CANDIDATE, DEV, HISTORY_COLUMNS, META_DIR, RELEASE_RETENTION, RELEASED, Releases, Version,
                           actor, tree_sha, utc_now)
from fleet.release_git import Repo, changelog_section
from fleet.release_scope import areas, skills_changed
from fleet.release_stamp import stamp_plugin_version
from fleet.release_verify import (EXEMPT, EXEMPT_ROSTER, FULL_ROSTER, GATE_ROSTER, GREEN, PROMOTABLE,
                                  Verify, archive_previous_attempt, exemption_for, read_verdict,
                                  write_exemption, write_verdict)
from fleet.review import Finding, Review, exit_code_for
from fleet import origin as origin_mod
from fleet.origin import Origin
from fleet.roadmap import ATTENTION, COORDINATOR, TERMINAL, Milestone, Roadmap
from fleet.session import (TMUX_SOCKET_ENV, SessionLayer, default_probes,
                           plain as pane_plain)
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
    #: DECLARED, like `checker` and for the same reason. `root-init` creates the directory a store will
    #: live in, so it is the one verb that must be answerable where `resolve_home` has no tier left —
    #: otherwise the only root it could ever create is the SECOND one. Said here beside the handler rather
    #: than inferred from a name in `default_context`, so the exemption is visible to the audits that read
    #: this registry.
    needs_store: bool = True


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
    Flag("--root", True, help="the fleet root; its marker supplies home, releases and the tmux socket"),
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
#: `FI-7`. The pane is ALIVE but no evidence about it could be read: the process probe attributed nothing
#: AND the capture came back empty. That is "I could not look", which is a different fact from "I looked
#: and it is not claude" — and the two were the same value, because `capture_pane` returns `""` when tmux
#: exits non-zero and `list_processes` returns `[]` when pgrep does.
#:
#: It needs its own code because of what the consumers do. Before a SEND, everything but `0` means wait,
#: so a wrong `12` costs one more poll. Before a CLOSE, `coordinating-instants` states "`0`, `12` or `13`
#: mean the pane can go" — so a transient `12` AUTHORISES tearing down a pane that is mid-turn, which is
#: precisely what `close`'s queued-pane refusal exists to prevent. Measured in the field at one poll in
#: ~118 against a live claude, with `11` either side.
#:
#: 14 is deliberately OUTSIDE the can-go set. A guard whose failure mode is "go ahead" is not a guard.
PANE_INDETERMINATE = 14

PANE_GUARD_CODES = {
    PANE_SAFE: "safe",
    PANE_QUEUED_TEXT: "queued-text",
    PANE_MID_TURN: "mid-turn",
    PANE_NOT_CLAUDE: "not-claude",
    PANE_INDETERMINATE: "indeterminate",
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
REAP_UNATTRIBUTABLE = "reap-unattributable"

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

#: The release area, named on every release verb. Declared once with its help text, because eight verbs
#: repeating one flag by hand is eight chances for the help to disagree with itself (`W2-20`).
RELEASES = "--releases"
RELEASES_HELP = "the release area; overrides $FLEET_RELEASES"

KV_COLUMNS = ("field", "value")
ROW_COLUMNS = ("kind", "subject", "severity", "detail", "clears_when", "clears_who")
#: `release-list`'s schema. Its own tuple rather than a reuse: the columns describe releases, and
#: `OBS-44` is what borrowing a tuple because it happens to be the right length costs.
RELEASE_COLUMNS = ("version", "state", "cut_at", "current")


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


def resolve_root(parsed: Parsed, environ: dict, cwd):
    """Which root, by tiers 2, 4 and 5 — `--root`, `$FLEET_ROOT`, then the marker walk. `None` when
    nothing names one and no marker is found.

    Tiers 1 and 3 name individual COMPONENTS and are handled by the component resolvers below. A caller
    who says `--home` has named a store without saying anything about a root, and inventing one for them
    is `I2-11` in the other direction — a value the caller never mentioned deciding a destination they
    typed out.

    A root that IS named and has no readable marker is refused rather than skipped: falling through to
    another tier would silently select a different store than the one the caller asked for.
    """
    named = parsed.get("root") or environ.get("FLEET_ROOT")
    if named:
        return root_mod.load(Path(named))
    return root_mod.discover(Path(cwd), Path(environ.get("HOME") or Path.home()))


def _root_source(parsed: Parsed, environ: dict, resolved) -> str:
    """Where a derived value came from, for the line `G2` prints."""
    if parsed.get("root"):
        return "--root"
    if environ.get("FLEET_ROOT"):
        return "$FLEET_ROOT"
    return f"marker at {resolved.path / root_mod.MARKER}"


def resolve_home(parsed: Parsed, environ: dict, cwd) -> tuple:
    """`(home, source)` — the record/pool store, and where the answer came from.

    `SI-15` used to let a READ-ONLY verb fall back to `$HOME/.fleet`, on the ground that *"nothing is
    enrolled" is a real answer to a real question*. Under per-root isolation that ground is gone: the
    fallback does not answer about no fleet, it answers about a **different root's** fleet — confidently,
    with a population row and everything. That is `FI-417`'s shape, a true sentence answering the wrong
    question, so the read refuses too and the refusal names the directory it searched from.

    The cost is real and is accepted deliberately: `fleet board` in an unmarked directory no longer prints
    an empty board, it prints a refusal that says what would fix it.
    """
    if parsed.get("home"):
        return Path(parsed.get("home")), "--home"
    if environ.get("FLEET_HOME"):
        return Path(environ["FLEET_HOME"]), "$FLEET_HOME"
    resolved = resolve_root(parsed, environ, cwd)
    if resolved is not None:
        return resolved.store, _root_source(parsed, environ, resolved)
    raise BadInput(root_mod.refusal(Path(cwd), Path(environ.get("HOME") or Path.home()), parsed.verb))


def instants_were_named(parsed: Parsed, environ: dict) -> bool:
    """Did the caller SAY where instants live, for THIS invocation?

    Three ways, and the one that is missing is the point. `--instants-dir` and `FLEET_INSTANTS` name the
    directory outright. `--home` names the store in the command somebody typed, and `--home X => instants
    X/instants` is a documented, relied-on implication.

    ⚠️ An exported **`FLEET_HOME` does NOT count**, and this asymmetry is a fix rather than an oversight.
    The guard shipped in `0.4.0` accepting it, and `FI-382`'s live configuration is precisely a shell with
    `FLEET_HOME` exported by `scripts/fleet-env.sh` and no `FLEET_INSTANTS` — so the control could not
    fire on the defect that motivated it (`FI-303`), and `dispatch` measured at `0.5.0` still returned
    rc=0 planting the child in `$FLEET_HOME/instants`.

    The inference "you named the store, so you named the instants directory" IS the default `SI-56`
    deleted. Reading it out of an ambient variable instead of out of the resolver does not turn it into a
    statement the caller made — `I2-11`: a value the caller never typed must not out-rank one they did.
    A flag is typed for this invocation; an export was made by a shell rc nobody re-reads.

    `resolve_instants` still derives from `$FLEET_HOME` and is unchanged: reads must always answer, and a
    read that enumerates a derived directory harms nobody. Only CREATING there is refused.
    """
    return bool(parsed.get("instants-dir") or parsed.get("home") or environ.get("FLEET_INSTANTS"))


def resolve_instants(parsed: Parsed, environ: dict, cwd) -> Path:
    """Where instants live. Named, or derived from the store.

    Every verb needs this resolvable — `reconcile` and `guards.blocking_compactions` read it on the READ
    path too — so it always answers. What it does NOT do is let a verb CREATE an instant somewhere nobody
    named; that refusal is `require_named_instants`, applied at the two sites that create, because
    refusing here would refuse `board` as well and a read that enumerates an empty derived directory
    harms nobody.
    """
    if parsed.get("instants-dir"):
        return Path(parsed.get("instants-dir"))
    if parsed.get("home"):
        return Path(parsed.get("home")) / "instants"
    if environ.get("FLEET_INSTANTS"):
        return Path(environ["FLEET_INSTANTS"])
    if environ.get("FLEET_HOME"):
        return Path(environ["FLEET_HOME"]) / "instants"
    home, _ = resolve_home(parsed, environ, cwd)
    return home / "instants"


def require_named_instants(parsed: Parsed, environ: dict = None) -> None:
    """Refuse to CREATE an instant in a directory nobody named. `SI-56` / `FI-382`.

    With `FLEET_INSTANTS` unset, `dispatch` derived `$FLEET_HOME/instants` and planted the child there
    instead of the effort tree — rc=0, all four guards `allow`. Nothing downstream disagreed, because
    every verb resolves the child through its record, so the damage was invisible until the endgame
    compaction enumerated the instants directory and the worker was not in it.

    Note this is NOT fixed by per-root isolation, and the spec's shorthand is worth correcting here: under
    isolation the stray lands at `$ROOT/.fleet/instants`, which is the RIGHT root and still the WRONG
    tree. The harm was always intra-root. Only refusing to invent a destination closes it.

    Applied at the creation sites rather than in the resolver, because the resolver also answers for
    `board`, and a READ that enumerates a derived directory harms nobody. `test_root_resolution` asserts
    this guard is reached by every handler that calls `layout.bootstrap`, so a third creating verb cannot
    be added without it.
    """
    environ = os.environ if environ is None else environ
    if instants_were_named(parsed, environ):
        return
    raise BadInput(
        f"{parsed.verb!r} creates an instant and nothing named the directory to create it in. Pass "
        f"`--instants-dir <path>` or export FLEET_INSTANTS. There is deliberately no derived default for "
        f"a CREATE: `$FLEET_HOME/instants` used to be one, and it planted a dispatched child outside its "
        f"effort tree at rc=0 with every guard green — invisible to every verb, because they all resolve "
        f"the child through its record, until the endgame compaction could not find it (SI-56).")


def resolve_socket(parsed: Parsed, environ: dict, cwd):
    """The tmux SERVER: `$FLEET_TMUX_SOCKET`, else `fleet-<root name>`, else the default server.

    Per-root because `close`, `abort` and `harvest` kill sessions BY NAME and session names are
    `dt-<subject>` chosen by a coordinator, so two roots on one server can collide and the loser dies with
    no diagnostic. `fleet-env.sh` already argues a private server over the default one for exactly this
    reason; this takes the argument one step further.

    The environment still wins, and that is load-bearing rather than a courtesy: `it_section` exports this
    variable for every IT section, and silently overriding it would point the whole suite at one server.
    """
    if environ.get(TMUX_SOCKET_ENV):
        return environ[TMUX_SOCKET_ENV]
    resolved = resolve_root(parsed, environ, cwd)
    return resolved.socket if resolved is not None else None


def active_root(parsed: Parsed):
    """The root this invocation resolved, or `None`. The handler-side companion to `resolve_root`, which
    takes its environment and cwd as arguments so it stays testable."""
    return resolve_root(parsed, dict(os.environ), Path.cwd())


def active_root_str(parsed: Parsed) -> str:
    """The active root as a string for `Record.root`, or `""` when there is none."""
    resolved = active_root(parsed)
    return "" if resolved is None else str(resolved.path)


def assert_within_root(path, root_path, what: str) -> None:
    """Refuse a path that leaves its root, naming BOTH. `G1`.

    Resolved on both sides. During migration `~/.fleet` and `~/davis_root/.fleet` are the same directory
    reached two ways, and comparing unresolved strings would manufacture a mismatch out of a symlink. It
    is a PATH comparison rather than a prefix test, because `/x/davis_root2` starts with `/x/davis_root`.
    """
    resolved = Path(path).resolve()
    root_path = Path(root_path).resolve()
    if root_path != resolved and root_path not in resolved.parents:
        raise BadInput(
            f"the {what} {resolved} is outside this fleet's root {root_path}. A dispatch that points out "
            f"of its own root is how one root's worker ends up in another root's tree, and it is "
            f"invisible afterwards because every verb resolves the child through its record (SI-56). "
            f"Clears when: name a path under {root_path}, or run from the root that owns {resolved}.")


def root_mismatch(record, active_root: str) -> bool:
    """True only when the record NAMES a root and it differs from the active one.

    An EMPTY root is NOT MEASURED, never a mismatch. Records written before isolation carry none, and
    reading that absence as "a different root" would refuse every one of them — `FI-417`'s rule, which is
    that a check unable to see something must not report an answer about it.
    """
    if not record.root or not active_root:
        return False
    return Path(record.root).resolve() != Path(active_root).resolve()


def default_context(parsed: Parsed, out, err) -> Ctx:
    """The real context: the live probes, the real git, a real command runner.

    Nothing in this function is reachable from a handler, which is what lets the outward-state audit hold
    while `verify` and `selftest` still run real commands: a handler calls `ctx.runner`, never a spawner.

    Every destination is resolved by the six-tier chain in `resolve_home` / `resolve_instants` /
    `resolve_socket`, which is where the reasoning lives. It is spelled once, there, so `SI-15`'s revision
    and `SI-56`'s deletion cannot drift out of step with each other.
    """
    environ = dict(os.environ)
    cwd = Path.cwd()
    #: The refusal `resolve_home` raises is correct for every verb but one. `root-init` exists to create
    #: the directory a store will live in, and the first root on a box is made by somebody standing where
    #: there is no root — so refusing here would leave that verb able to create only the SECOND root. The
    #: exemption is read off the DECLARED `needs_store`, never off the verb's name, and it is the failure
    #: to resolve that is tolerated: when a root IS resolvable the verb gets a full context like any other.
    spec = VERBS.get(parsed.verb)
    try:
        home, home_source = resolve_home(parsed, environ, cwd)
    except BadInput:
        if spec is None or spec.needs_store:
            raise
        return Ctx(home=None, instants_dir=None, store=None, pool=None, sessions=None, harvest=None,
                   out=out, err=err, dry_run=parsed.on("dry-run"), porcelain=parsed.on("porcelain"),
                   git=default_git(), runner=_default_runner())
    instants = resolve_instants(parsed, environ, cwd)
    resolved_root = resolve_root(parsed, environ, cwd)

    #: `G2`, and `FI-421` is why it is unconditional. That finding's SECOND defect — a function written to
    #: remove a silent fallback shipping WITH one — was caught only by printing the resolved path: "reading
    #: the code would not have shown it; printing the resolved path did." A chain with five tiers above a
    #: refusal says where it landed, every call.
    #:
    #: On stderr, beside the cadence line, for the reason that line is there: stdout carries a column
    #: contract that `--porcelain` consumers parse byte-for-byte.
    #: SUPPRESSED under `--porcelain`, and this is the contract rather than a concession: that flag is
    #: declared as "machine form on stdout: tab-separated, NO BANNER", and a resolved-root line is banner
    #: content. Measured after shipping it unconditionally: 102 porcelain call sites in the IT harness
    #: merge stderr into the same file with `2>&1`, and `§C1` counts that file's rows with `grep -c .` —
    #: so an unconditional line became a third lease row and failed the case. One site noticed; 88 more
    #: redirect the same way and simply did not happen to count.
    #:
    #: The human path keeps it, which is where `FI-421`'s lesson actually applies: its second defect — a
    #: function written to remove a silent fallback shipping WITH one — was caught only by PRINTING the
    #: resolved path. A machine consumer reads the store it named; a person needs to be told which one
    #: five tiers chose.
    if not parsed.on("porcelain"):
        shown = home.parent if home.name == ".fleet" else home
        print(f"root {shown} ({home_source})", file=err)

    sessions = SessionLayer(default_probes(tmux_socket=resolve_socket(parsed, environ, cwd)))

    #: `G3` binds the pool to a root ONLY when this store IS that root's store. The same rule as the
    #: dispatch containment check, for the same reason and found by the same failure: a caller who named
    #: some other store (`--home /tmp/sandbox`, an IT section's `FLEET_HOME`, a skill's own suite) has
    #: named a destination out loud, and constraining THEIR pool by a root they never mentioned is a
    #: value the caller did not type out-ranking one they did (`I2-11` in reverse).
    #:
    #: Measured: without this, `enroll --slot /tmp/.../slotA` was refused on any marked box, so
    #: `wave-sequence.sh`'s dispatch then failed with `pool-capacity: none is enrolled` — a refusal three
    #: steps downstream of its cause, which is the expensive kind.
    owning_root = (resolved_root.path if resolved_root is not None
                   and Path(home).resolve() == resolved_root.store.resolve() else None)
    pool = Pool(home, cwd_probe=_cwd_holders, alive=sessions.alive, fleet_root=owning_root)
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


def _one_line(value) -> str:
    """Any message flattened to ONE line, for use as a FIELD in an emitted row.

    `_emit`'s porcelain form is `"\t".join(cells)` per row, so a value carrying a newline becomes a
    second row and a value carrying a tab shifts every column after it — and a caller's `cut -f4` then
    reads the wrong field with nothing anywhere reporting an error. The values that need this are
    exception messages: a refusal in this package is written as a paragraph, deliberately, because it is
    read by a human.
    """
    return " ".join(str(value).split())


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


def _refuse_foreign_root(record: Record, parsed: Parsed = None) -> Record:
    """`G1`'s secondary half, applied wherever a verb ACTS on one named record.

    Deliberately NOT applied on the read path (`store.all()`, which `board`, `status` and `reconcile`
    enumerate through). A single stray record would make the board refuse outright, and a gate that is
    permanently red is one that gets read past — taking the genuine alarm beside it down too (`FI-402`).
    A record naming another root is surfaced there as a row, and refused only when something is about to
    act on it.

    The state is reachable only by COPYING a store between roots: containment at dispatch and `G3` at
    enrolment prevent it being created. So this is cheap insurance, and saying so is the point — a guard
    described as a live defence when it is not is how a reader stops checking the ones that are.
    """
    resolved = active_root(parsed if parsed is not None else Parsed(verb=""))
    if resolved is not None and root_mismatch(record, str(resolved.path)):
        raise BadInput(
            f"record {record.todo_id!r} was written under root {record.root} and this call resolved "
            f"{resolved.path}. Refusing: a store reached from the wrong root reports another fleet's "
            f"work as this one's. Clears when: run from {record.root}, or pass `--root {record.root}`.")
    return record


def _record(ctx: Ctx, parsed: Parsed) -> Record:
    record = ctx.store.read(ctx.store.resolve_id(parsed.get("id")))
    return _refuse_foreign_root(record, parsed)


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
            matches = InstantName.parse(Path(record.child_instant).name).stable_key() == want
        except FleetError:
            continue
        #: OUTSIDE the try, and that placement is the whole point: `_refuse_foreign_root` raises
        #: `BadInput`, which IS a `FleetError`, so raising it one line up would be caught by the
        #: `continue` that exists to skip an unparseable record — and the guard would silently do
        #: nothing while reading as installed. Found by asking what the except clause catches.
        if matches:
            return _refuse_foreign_root(record)
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
    #: `SI-56`. Before anything is created, and before any irreversible step.
    require_named_instants(parsed)
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


# --- seed-delivery integrity ----------------------------------------------------------------------

#: How long `dispatch` waits for a briefing to appear in the worker's argv before concluding it cannot see
#: one. Bounded and small on purpose: a STALE launcher already holds a non-empty seed file and execs at
#: once, so the dangerous case is visible almost immediately, while a CORRECT launcher waits for the caller
#: to write a seed — which happens after `dispatch` has returned, and therefore can never be observed from
#: here however long we wait. Waiting longer would add latency to every dispatch and catch nothing extra.
SEED_CHECK_SECONDS = "FLEET_SEED_CHECK_SECONDS"
SEED_CHECK_DEFAULT_S = 5.0


def _seed_check_window(env=None) -> float:
    raw = (env if env is not None else os.environ).get(SEED_CHECK_SECONDS, "")
    try:
        window = float(raw)
    except (TypeError, ValueError):
        return SEED_CHECK_DEFAULT_S
    #: Zero DISABLES the wait but not the check — one look, then decide. Negative is meaningless input and
    #: falls back rather than silently disabling a safety check.
    return window if window >= 0 else SEED_CHECK_DEFAULT_S


def _verify_seed_delivery(ctx: Ctx, tmux: str, rendered_seed: str, probes=None, sleep=None):
    """What was this session actually started with? `None` when it cannot be asked at all.

    `None` is returned only when the pane pid is unobservable — an injected `Probes` with no `pane_pid`,
    or a tmux that did not answer. It is NOT a verdict, and the caller must not read it as one: the three
    verdicts are `seedcheck`'s, and "I could not look" is a fourth thing.
    """
    import time

    pid = ctx.sessions.pane_pid(tmux)
    if not pid:
        return None
    probes = probes or seedcheck.default_probes()
    sleep = sleep or time.sleep
    deadline = _seed_check_window()
    waited, step = 0.0, 0.25
    verdict = seedcheck.check_session(tmux, pid, rendered_seed, probes)
    #: Poll only while the answer is "nothing delivered yet". A launcher that execs takes a moment, and a
    #: check that read once would report NOT-DELIVERED for a delivery that was milliseconds away —
    #: reporting the dangerous case as the benign one. VERIFIED and FOREIGN are final the instant they are
    #: observed: argv does not change after exec.
    while verdict.state == seedcheck.NOT_DELIVERED and waited < deadline:
        sleep(step)
        waited += step
        verdict = seedcheck.check_session(tmux, pid, rendered_seed, probes)
    return verdict


def _do_seed_delivered(ctx: Ctx, parsed: Parsed) -> int:
    """Record what was ACTUALLY delivered to a worker's pane. `SI-55`.

    `fleet` renders the seed and does not deliver it. A launcher that `exec`s the binary leaves the
    briefing in `/proc/<pid>/cmdline`, where `seed-check` can read it — but `send-keys`, which is how
    `reviving-dead-panes` re-briefs a rescued worker, leaves nothing in argv at all. Those workers read
    `NOT-DELIVERED` for the life of the instant while a sibling reads `VERIFIED`, and a row that can never
    change is a row that stops being read (`FI-402`).

    **This records evidence, not a claim.** The caller hands over the bytes it sent; `fleet` digests them
    itself and compares against the seed it rendered. A launcher that sent the wrong file — the class this
    whole module exists for — records the wrong file, and the mismatch is refused HERE rather than stored
    for a later reader to discover. What it cannot prove is that the caller sent what it says it sent,
    which is why the verdict is `ATTESTED` and not `VERIFIED`, and why its detail names the channel.

    Containment, not equality, for the same reason the argv path uses containment: a caller may
    legitimately prepend ("your slot is …"). What must never happen is a DIFFERENT briefing.

    Overwritable, unlike `origin.json`: a rescued worker is legitimately briefed again, and the latest
    delivery is the one that describes the pane.
    """
    record = _record(ctx, parsed)
    child = _child_of(ctx, record)
    seed_file = child / ".fleet" / "seed.txt"
    if not seed_file.is_file():
        raise BadInput(
            f"{seed_file} does not exist, so there is nothing to compare a delivery against. A recorded "
            f"delivery is a COMPARISON against the seed `fleet` rendered; without one this would be an "
            f"unchecked assertion, which is the thing `seed-check` exists not to accept.")
    source = Path(parsed.get("delivered"))
    try:
        delivered = source.read_text()
    except OSError as exc:
        raise BadInput(f"--delivered {str(source)!r} could not be read ({exc.strerror or exc}).") from exc
    rendered = seed_file.read_text()
    if not seedcheck.carries(rendered, [delivered]):
        raise BadInput(
            f"the text in {source} does NOT carry the seed rendered for {record.todo_id!r}: delivered "
            f"md5 {seedcheck.digest(delivered)} ({len(delivered)} chars) against rendered md5 "
            f"{seedcheck.digest(rendered)} ({len(rendered)} chars) at {seed_file}. Refused rather than "
            f"recorded: a stored attestation that disagrees with the seed is a wrong answer waiting for a "
            f"reader, and this mismatch is exactly the misdelivery class the check exists for. A preamble "
            f"is fine — the rendered seed must appear WHOLE somewhere in what was sent.")
    delivery = seedcheck.Delivery(
        at=ctx.now(), by=parsed.get("by") or record.tmux or record.todo_id,
        channel=parsed.get("channel") or "send-keys",
        delivered_chars=len(delivered), delivered_md5=seedcheck.digest(delivered),
        rendered_md5=seedcheck.digest(rendered))
    if ctx.dry_run:
        _emit(ctx, "seed-delivered", [
            ("dry-run", "nothing was recorded"),
            ("would-record", str(seedcheck.delivery_path(child))),
            ("channel", delivery.channel), ("delivered_md5", delivery.delivered_md5),
            ("rendered_md5", delivery.rendered_md5)])
        return EXIT_OK
    written = seedcheck.write_delivery(child, delivery)
    _emit(ctx, "seed-delivered", [
        ("record", record.todo_id), ("session", record.tmux or "(none)"),
        ("channel", delivery.channel), ("by", delivery.by),
        ("delivered_chars", str(delivery.delivered_chars)),
        ("delivered_md5", delivery.delivered_md5), ("rendered_md5", delivery.rendered_md5),
        ("recorded_in", str(written)),
        ("reads_as", f"`fleet seed-check` now reports {seedcheck.ATTESTED} for this session instead of "
                     f"{seedcheck.NOT_DELIVERED} — a POSITIVE state, and a weaker one than "
                     f"{seedcheck.VERIFIED}, which means the briefing was seen in the worker's own argv")])
    return EXIT_OK


def _do_seed_check(ctx: Ctx, parsed: Parsed) -> int:
    """Is every live worker running the briefing that was rendered for it?

    The standing form of the dispatch-time assertion, and the one that would have caught the 2026-08-07
    incident: it can be run at ANY time, so it sees deliveries that settled long after `dispatch` returned.
    Read-only — it reads `.fleet/seed.txt` and `/proc/<pid>/cmdline` and writes nothing.

    Two independent signals, deliberately, because they fail in different ways:
      * per session, the delivered argv against that instant's own rendered seed;
      * across sessions, whether any two were started with a BYTE-IDENTICAL briefing — which needs no
        knowledge of what any seed should have been, and so survives every way the first signal can be
        defeated (a missing seed file, an instant folder that has been renamed, a profile that changed).
    """
    wanted = parsed.get("id", "")
    verdicts, unreadable, rows = [], [], []
    #: The clearing contract for a misdelivery, stated once and attached to every row that alarms: an
    #: alarm whose remedy the reader has to invent gets ignored (§9).
    clears = ("the launcher that delivers the seed is corrected — usually a stale `claude` shim first on "
              "the tmux SERVER's PATH holding a hardcoded seed file — and the worker is dispatched again")
    clears_who = "the coordinator that dispatched it, with whoever owns the tmux server's PATH"
    for record in ctx.store.all():
        if record.harvested_at or record.closed_at:
            continue
        if wanted and wanted not in record.todo_id:
            continue
        session = record.tmux
        if not ctx.sessions.alive(session):
            continue
        seed_file = Path(record.child_instant) / ".fleet" / "seed.txt"
        if not seed_file.is_file():
            unreadable.append((session, f"no rendered seed at {seed_file} to compare against. This is NOT "
                                        f"a pass — it is a check that could not run"))
            continue
        pid = ctx.sessions.pane_pid(session)
        if not pid:
            unreadable.append((session, "the pane pid could not be read, so nothing about this session's "
                                        "delivery was observed. This is NOT a pass"))
            continue
        #: `SI-55`. A recorded delivery is consulted only where argv says nothing — `classify` enforces
        #: that order, and it matters: a FOREIGN briefing visible in argv must never be suppressed by an
        #: attestation. An unreadable delivery file is refused by `read_delivery` rather than treated as
        #: absent, and that refusal is reported per session instead of failing the whole sweep.
        try:
            delivery = seedcheck.read_delivery(Path(record.child_instant))
        except FleetError as exc:
            unreadable.append((session, f"a delivery record exists and could not be read: "
                                        f"{_one_line(exc)}"))
            continue
        verdict = seedcheck.check_session(session, pid, seed_file.read_text(),
                                          seedcheck.default_probes(), delivery=delivery)
        verdicts.append(verdict)
        #: Only FOREIGN is a VIOLATION. NOT-DELIVERED is reported at INFO because `fleet` renders the seed
        #: and does not deliver it, so it is the ordinary appearance of a send-keys delivery — but its
        #: DETAIL says so in words, because a severity alone would let it read as clean.
        rows.append(Row(kind=verdict.state.lower(), subject=session,
                        severity=VIOLATION if verdict.state == seedcheck.FOREIGN else INFO,
                        detail=(f"pid={verdict.pid} todo={record.todo_id} "
                                f"rendered_md5={verdict.rendered_md5} "
                                f"delivered_md5={verdict.delivered_md5 or '(none)'} :: {verdict.detail}"),
                        clears_when=clears if verdict.state == seedcheck.FOREIGN else "",
                        clears_who=clears_who if verdict.state == seedcheck.FOREIGN else ""))

    for session, why in unreadable:
        rows.append(Row(kind="unreadable", subject=session, severity=INFO, detail=why))

    collided = seedcheck.collisions(verdicts)
    for md5, names in collided:
        rows.append(Row(kind="collision", subject=", ".join(names), severity=VIOLATION,
                        detail=(f"{len(names)} live sessions were started with a BYTE-IDENTICAL briefing "
                                f"(md5 {md5}). Two instants dispatched for two milestones must never have "
                                f"been given one briefing"),
                        clears_when=clears, clears_who=clears_who))

    #: The POPULATION, always, even when nothing is wrong, and NAMED rather than counted. A check that
    #: prints only its hits cannot be told apart from one that examined nothing — and this entire defect
    #: class is checks that examined nothing while reading as clean.
    examined = len(verdicts) + len(unreadable)
    foreign = [v.session for v in verdicts if v.state == seedcheck.FOREIGN]
    unverified = [v.session for v in verdicts if v.state == seedcheck.NOT_DELIVERED]
    verified = [v.session for v in verdicts if v.state == seedcheck.VERIFIED]
    attested = [v.session for v in verdicts if v.state == seedcheck.ATTESTED]
    rows.append(Row(kind=POPULATION, subject=wanted or "(every live dispatched session)", severity=INFO,
                    detail=(f"{examined} live session(s) examined: "
                            f"{len(verified)} verified {verified or '[]'}; "
                            f"{len(attested)} attested {attested or '[]'}; "
                            f"{len(foreign)} FOREIGN {foreign or '[]'}; "
                            f"{len(unverified)} unverifiable {unverified or '[]'}; "
                            f"{len(unreadable)} unreadable {[s for s, _ in unreadable] or '[]'}. "
                            f"'verified' means the briefing was seen in the worker's own argv; "
                            f"'attested' means the actor that delivered it RECORDED what it sent and that "
                            f"text carries the rendered seed (`SI-55`) — a positive answer through a "
                            f"weaker channel, which is why it is counted separately")))
    if examined == 0:
        rows.append(Row(kind="empty-population", subject=wanted or "(every live dispatched session)",
                        severity=INFO,
                        detail=("no live dispatched session matched, so this run examined NOTHING. That "
                                "is not a clean result, it is an empty population: an exit 0 here says "
                                "the check found nothing to look at, not that delivery is correct")))
    _emit(ctx, "seed-check", rows)
    return EXIT_ATTENTION if (foreign or collided) else EXIT_OK


# --- dispatch -------------------------------------------------------------------------------------


def _read_seed_extra(path) -> str:
    """The text `--seed-extra` names, stripped of trailing whitespace; `""` when the flag was not passed.

    `SI-53`. Every refusal here happens before `dispatch` claims anything, which is the point of reading it
    this early: a missing file discovered after the claim costs a slot to report a typo.

    An EMPTY file is refused rather than treated as "no addition". A caller who passed the flag believes
    something was added, and quietly adding nothing is the same silence — a dispatch that reads as
    carrying the sentence and does not — that this flag exists to end.
    """
    if not path:
        return ""
    source = Path(path)
    try:
        text = source.read_text()
    except OSError as exc:
        raise BadInput(
            f"--seed-extra {path!r} could not be read ({exc.strerror or exc}). Refused before anything "
            f"was claimed. It names the file whose text is appended to this dispatch's seed, so a path "
            f"that is not there would mean the worker is briefed WITHOUT the sentence you meant to add "
            f"— which is the exact failure this flag replaces.") from exc
    if not text.strip():
        raise BadInput(
            f"--seed-extra {path!r} is empty (or only whitespace). Passing the flag says an addition was "
            f"meant; appending nothing would leave the dispatch reading as though it carried one.")
    return text.strip()


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
    #: `SI-56`. Before anything is created, and before any irreversible step.
    require_named_instants(parsed)
    #: `G1`. The instants directory must be inside this root, or one root's worker lands in another
    #: root's tree — invisible afterwards, because every verb resolves the child through its record.
    #:
    #: Applied ONLY when the store in use IS this root's own store. A caller who named some other store
    #: — `--home /tmp/sandbox`, or an IT section's `FLEET_HOME` — has named a destination out loud, and
    #: measuring their instants directory against a root they never mentioned is `I2-11` in reverse: a
    #: value the caller did not type out-ranking one they did. Found by `wave-sequence.sh`, which exports
    #: a sandbox store and ran from inside a marked root; without this the guard refused every explicit
    #: sandbox on a marked box, which is most of the suite.
    #:
    #: Note this is STRICTER than "skip the check when --home was named": a caller who says
    #: `--home <root>/.fleet --instants-dir <other-root>/instants` still names this root's store, so the
    #: comparison still runs and still refuses.
    #:
    #: The SLOT needs no check here: `G3` refuses to ENROL a workspace outside the root, which is
    #: strictly earlier and cheaper than refusing a lease, so a leased slot cannot be foreign.
    _dispatch_root = active_root(parsed)
    if _dispatch_root is not None and Path(ctx.home).resolve() == _dispatch_root.store.resolve():
        assert_within_root(ctx.instants_dir, _dispatch_root.path, "instants directory")
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

    #: `SI-53`. Read BEFORE anything is claimed, so a typo'd path costs a refusal and not a slot. The
    #: content is carried to the render below rather than written here: the seed is ONE artifact, and a
    #: second writer appending to `seed.txt` after `dispatch` wrote it is precisely the race this replaces.
    seed_extra = _read_seed_extra(parsed.get("seed-extra"))

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
                 ("lineage_mode", lineage_mode or "(none)"),
                 ("seed_extra", (f"{parsed.get('seed-extra')} ({len(seed_extra)} chars would be appended "
                                 f"to the rendered seed)") if seed_extra else
                  "(none — the seed is exactly what the profile renders)")]
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
        #: `SI-53`. Appended HERE, before the seed is written and before the delivery check reads it, so
        #: there is one seed and not two: `seed.txt`, `_verify_seed_delivery` and `seed-check` all compare
        #: against the same combined text. Marked with its source path because a worker reading two
        #: paragraphs that disagree has to know which one was written for it specifically.
        if seed_extra:
            rendered["seed"] = (f"{rendered['seed'].rstrip()}\n\n"
                                f"--- dispatch-specific briefing, from {parsed.get('seed-extra')} ---\n\n"
                                f"{seed_extra}\n")
        record = Record(todo_id=todo_id, child_instant=str(child), base_instant=base,
                        slot=lease.slot, tmux=tmux, profile=str(profile.path),
                        golden=str(lease.path), lineage_base=parsed.get("lineage-base") or "",
                        lineage_mode=lineage_mode, title=title,
                        #: `SI-34`. Persisted, not merely evaluated: an override is a judgement that a guard
                        #: was wrong here, and it has to outlive the terminal it was typed into.
                        override_reason=parsed.get("override") or "",
                        milestone=milestone_id, root=active_root_str(parsed),
                        dispatched_at=ctx.now())
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
        #: POST-LAUNCH SEED INTEGRITY — the control this class was missing.
        #:
        #: `dispatch` renders the seed above and starts the worker with the bare string "claude". tmux
        #: resolves that against the SERVER's PATH, not this process's, so WHAT gets started is decided by
        #: an environment no dispatcher controls. On 2026-08-07 that handed a fleet-infra worker the
        #: v2stack COORDINATOR's briefing, byte for byte, and every gate passed because nothing compared
        #: the seed rendered here to the seed actually delivered. `FI-78` checks the seed FILE; it has
        #: never checked what was DELIVERED.
        #:
        #: A FOREIGN briefing REFUSES: the raise falls into the rollback path below, which gives the lease
        #: back and disowns the milestone. The session is killed FIRST and deliberately — a worker holding
        #: another instant's briefing acts on it, and the one instance of this we have was harmless only
        #: because that worker happened to notice by itself.
        #:
        #: NOT-DELIVERED does NOT refuse, and that asymmetry is the point. `fleet` delivers no seed, so
        #: every caller that delivers by send-keys legitimately shows nothing in argv at this moment, and
        #: refusing there would break every dispatch on the box to fix one. It is reported instead —
        #: loudly, and never as a pass (`seedcheck.Verdict.ok` is VERIFIED only).
        seed_verdict = _verify_seed_delivery(ctx, tmux, rendered["seed"])
        if seed_verdict is not None and seed_verdict.state == seedcheck.FOREIGN:
            ctx.sessions.kill(tmux)
            raise Refused(
                f"SEED MISDELIVERY — {tmux} was started with a briefing that is NOT the one rendered for "
                f"{child}. {seed_verdict.detail}. The session has been KILLED and this dispatch is "
                f"rolled back, because a worker holding another instant's briefing acts on it. The usual "
                f"cause is a stale `claude` shim first on the TMUX SERVER's PATH holding a hardcoded seed "
                f"file: read it with `tmux -L <socket> show-environment -g | grep '^PATH='`, then "
                f"regenerate or remove that launcher and dispatch again.",
                clears_when="the launcher that delivers the seed is corrected, or removed from the tmux "
                            "server's PATH",
                clears_who="whoever owns the tmux server that dispatch starts sessions on")
        if seed_verdict is not None and seed_verdict.state == seedcheck.NOT_DELIVERED:
            print(f"WARNING: seed delivery to {tmux} could NOT be verified. {seed_verdict.detail}. "
                  f"`fleet` renders the seed but does not deliver it, so this is also what a correct "
                  f"send-keys delivery looks like from here — it is not evidence that anything is wrong, "
                  f"and it is not evidence that anything is right. Re-check once delivery has settled: "
                  f"`fleet seed-check --id {todo_id}`.", file=ctx.err)
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
                    title=name.name, root=active_root_str(parsed),
                    dispatched_at=existing.dispatched_at if existing else ctx.now(),
                    launched_at=ctx.now() if ctx.sessions.alive(tmux) else
                    (existing.launched_at if existing else None))
    source = ctx.harvest.record_dispatch(ctx.store, record)
    _emit(ctx, "resume", [("todo_id", todo_id), ("instant", str(child)), ("slot", slot or ""),
                          ("tmux", tmux), ("claimed", "true" if lease else "false"),
                          ("watched_source", source.base),
                          ("exemption", verdicts[0].guard if verdicts else "")])
    return EXIT_OK


# --- declare / park / unpark ----------------------------------------------------------------------


def _watcher_for_claim(ctx: Ctx, child: Path, attested=None) -> tuple:
    """What is armed to wake this instant, as `(watchers, ungated_because)`. Raises `Refused` when nothing is.

    `FI-255`, raised by the operator: *"instants can claim AWAITING-CI while not armed with any watchers
    monitoring the CI"*. Measured — two workers in the IDENTICAL declared phase rendered byte-identically as
    `declared awaiting-ci; not consuming attention` while one was mid-turn with its own monitor and the other
    had been stopped for 1h28m with nothing that would ever restart it. `awaiting-ci` establishes only *"stop
    counting me against the cap"* and was silently also read as *"somebody is watching"*, which nothing
    established.

    The check sits AT THE MOMENT OF THE CLAIM and not in a sweep somebody has to remember to run, which is
    the operator's framing and the better one: *"a check you must remember to run fails the same way as the
    thing it checks"*. Only the exact phase `awaiting-ci` is gated, and the WIP cap's treatment of it is
    untouched — that is load-bearing elsewhere and is not the bug.

    Four outcomes, and the last two are the ones that took the thinking:

      - a claude pane with an indicator     -> the watchers, allowed
      - a claude pane with none             -> `Refused`; the reported defect
      - the capture FAILED                  -> `Refused`, and a DIFFERENT sentence. `FI-7`: a failed
        observation is not a negative observation, and a guard whose failure mode is "go ahead" is not a
        guard. This is the direction that authorised tearing down a live pane once already.
      - no record, no session, or not claude -> ALLOWED, with the reason RETURNED so the caller can print
        it. The gate has no subject here (an instant that was never dispatched into a session, a test
        store, a shell pane), and refusing would fire on every legitimate non-dispatched use. It is stated
        rather than silent because *a scope that narrows in silence reads as a pass* (`OBS-49`) — the
        caller emits an `ungated` row, so a claim that skipped the gate never looks like one that passed it.
    """
    #: THE ESCAPE HATCH, and it is here rather than absent because a guard with no override is routed
    #: around, and routing around this one is trivial: `declare.json` is a file, and `--phase` takes free
    #: text, so a worker meeting a refusal it believes is wrong can write the phase directly or invent a
    #: spelling. Both leave NO record that a judgement was made. This flag makes the override the cheapest
    #: honest path and the only one that writes down who claimed what.
    #:
    #: It is not a hole, because it does not buy silence: the attestation is stored verbatim, `fleet brief`
    #: reports it, and `--watcher ""` is refused the way `park --question ""` is. The predicate genuinely
    #: cannot see a cron, a `ScheduleWakeup`, an external watchdog or a peer session watching on this
    #: instant's behalf — those are REAL watchers, and refusing them would be a false positive landing on a
    #: stranger who did nothing wrong.
    #:
    #: ⛔ THE REQUIRED TEXT IS THE CONTROL. DO NOT REPLACE THIS WITH A BARE `--force` OR `--no-watcher`.
    #: Measured in the field on w17, the first real worker to meet this gate. It was refused, it had the
    #: flag available, and it did NOT use it — because using it meant typing a sentence it knew to be
    #: false: *"nothing is watching me, because there is nothing left to watch. Passing it would have
    #: recorded a true-looking attestation that was FALSE, to buy a cap exclusion I am not entitled to."*
    #: Its own conclusion: *"the refusal only worked because the hatch required me to type a sentence I
    #: knew to be untrue. A hatch that took a flag with no attestation text would have been used."*
    #:
    #: So the friction is not ceremony to be optimised away — it is the whole mechanism. A bare override
    #: costs one word and would be typed reflexively; naming a watcher that does not exist requires an
    #: assertion the claimant has to knowingly falsify, and that is a much higher bar than any check this
    #: tool could run. The audit that deletes this as boilerplate removes the guard, not the paperwork.
    if attested is not None:
        if not str(attested).strip():
            raise BadInput(
                "--watcher names the watcher this tool cannot see; an empty attestation is not an "
                "attestation. Give the mechanism — 'cron 0,30 * * * * gh-run-poll', 'coordinator "
                "child-watchdog.sh' — or arm a Monitor and drop the flag.")
        return f"attested: {' '.join(str(attested).split())}", ""
    record = _record_for(ctx, child)
    pane = getattr(record, "tmux", None) if record else None
    if not pane:
        return "", ("no dispatch record names a session for this instant, so there is no pane to read; "
                    "an instant that was never dispatched into a session is outside this gate's subject")
    if not ctx.sessions.alive(pane):
        return "", (f"no live session {pane!r}; this gate reads a running pane and there is not one")
    captured = ctx.sessions.capture(pane)
    text = captured or ""
    if captured is None and not ctx.sessions.is_claude_process(pane):
        raise Refused(
            f"{pane} is alive but nothing about it could be read: the capture FAILED and no live claude "
            f"process is attributed to it. That is a FAILED OBSERVATION, not an observation that nothing "
            f"is watching — and this claim is refused rather than allowed on it, because a guard that "
            f"treats 'I could not look' as 'go ahead' is not a guard (FI-7).",
            clears_when="the pane can be read again — re-run the same command, and if it persists check "
                        "FLEET_TMUX_SOCKET names the server the instant was dispatched on",
            clears_who="the declaring instant")
    if not _is_claude(ctx.sessions, text, pane):
        return "", (f"{pane} is alive and is not a claude pane, so there is no status line to read and no "
                    f"harness watcher to arm; outside this gate's subject")
    watchers = ctx.sessions.watchers(text)
    if watchers:
        return watchers, ""
    raise Refused(
        f"nothing is armed to wake {pane}, so declaring awaiting-ci here would mean 'stop counting me "
        f"against the WIP cap' and nothing else. Its status line shows no monitor and no background shell, "
        f"so when CI finishes NOTHING re-invokes this session: the run completes, the pane stays stopped, "
        f"and the milestone waits on a worker that will never be woken. That is FI-255, measured on a "
        f"worker stopped 1h28m in exactly this state. Note that being mid-turn is NOT a watcher — `declare` "
        f"runs inside the claiming turn, so every claimant is mid-turn and it distinguishes nothing.",
        clears_when="arm something that re-invokes this session and declare again — a Monitor on the run "
                    "(`gh run watch`/`gh pr checks` emitting a line per terminal state), or a background "
                    "shell that exits when the run does. Either draws `1 monitor`/`1 shell` on the status "
                    "line, which is what this gate reads. If the wait is NOT on CI, declare the phase it "
                    "actually is: any other phase counts against the cap and is not gated. And if the "
                    "watcher is REAL but this tool cannot see it — a cron, an external watchdog, a peer "
                    "session — name it with `--watcher '<what it is>'`, which records your attestation "
                    "instead of refusing rather than making you route around the gate",
        clears_who="the declaring instant")


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
    #: `FI-255`/`i39`. Gated BEFORE `--dry-run` returns, so `--dry-run` answers the question a caller asks
    #: it — "would this be accepted?" — rather than reporting `would-declare` on a claim the real call
    #: refuses. `--dry-run` disagreeing with the real call is a documented trap of this CLI already
    #: (`fleet milestone` exits 0 on a dry run where the real call exits 2); reproducing it in a NEW gate,
    #: whose whole purpose is to be consulted before acting, would be inexcusable.
    watchers, ungated_because = "", ""
    if phase == PHASE_AWAITING_CI:
        watchers, ungated_because = _watcher_for_claim(ctx, child, parsed.get("watcher"))
    elif parsed.get("watcher") is not None:
        #: Refused, not ignored. `awaiting-ci` is the only gated phase, so an attestation anywhere else
        #: answers a question nobody asked — and silently dropping it would let a worker believe it had
        #: recorded a watcher when nothing stored one. This package refuses undeclared input for the same
        #: reason it refuses an undeclared flag: accepting what nothing reads is how a caller comes to
        #: rely on a no-op.
        raise BadInput(
            f"--watcher attests to a watcher, and only `--phase awaiting-ci` is gated on one. Declaring "
            f"{phase!r} needs no attestation and nothing would read it, so it is refused rather than "
            f"stored where it would look like a fact. Drop the flag.")
    if ctx.dry_run:
        _emit(ctx, "declare", [("dry-run", "nothing was declared"), ("would-declare", phase),
                               ("asked", asked)]
                              + ([("watchers", watchers)] if watchers else [])
                              + ([("ungated", ungated_because)] if ungated_because else []))
        return EXIT_OK
    Declarations(child).set_phase(phase)
    #: Recorded, so the question can be answered AFTER the fact. FI-255's defect was not only that the claim
    #: was unchecked — it was that the store kept `{"phase": "awaiting-ci"}` and nothing else, so a stopped
    #: worker and a self-waking one were indistinguishable in the record as well as on the board.
    Declarations(child).set_watchers(watchers or None)
    consumer = Declarations(child)                       # a FRESH consumer, not the writer's return
    value = consumer.phase()
    if value is None:
        raise BadInput(
            f"the declaration did not land: {consumer.path} reports no phase after writing {phase!r}. "
            "The acknowledgement is the re-read, so a declaration that cannot be read back is a failure "
            "and not a success with a caveat.")
    _emit(ctx, "declare", [("phase", value), ("asked", asked), ("consumer", str(consumer.path)),
                           ("instant", str(child))]
                          + ([("watchers", watchers)] if watchers else [])
                          + ([("ungated", ungated_because)] if ungated_because else []))
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

    #: `FI-10`. Retiring is a different act from raising, so it is a flag on the coordinator's verb
    #: rather than a new verb: same actor, same file, same authority, and one more verb is one more row
    #: in three IT fixture matrices (`II-4`). It writes exactly `dropped`, only onto a milestone that has
    #: not finished, and only with a reason — see `Roadmap.retire`.
    if parsed.on("retire"):
        if not parsed.get("reason"):
            raise BadInput(
                f"`--retire` needs `--reason`. `dropped` and `done` are both terminal and look alike to "
                f"a later reader, so a milestone that left the population without a recorded why is a "
                f"decision nobody can reconstruct.")
        if ctx.dry_run:
            _emit(ctx, "milestone", [("dry-run", "the roadmap was not written"),
                                     ("would-retire", parsed.get("id")),
                                     ("reason", parsed.get("reason"))])
            return EXIT_OK
        retired = roadmap.retire(parsed.get("id"), parsed.get("reason"))
        _emit(ctx, "milestone", [
            ("milestone", retired.id), ("status", retired.status),
            ("retired-reason", retired.retired_reason),
            ("dispatchable", "no — a retired milestone leaves the ready population, which is the point: "
                             "once its deps land a superseded one is derived READY forever and no report "
                             "prints ready rows")])
        return EXIT_OK

    #: `SI-51`. The repair door for a claim stranded BEFORE `abort` learned to release one. Fixing `abort`
    #: reaches none of those: `abort` refuses to run twice, so an instant already renamed `-abort-` has no
    #: second pass, and the escape actually used on the live effort was editing `roadmap.json` by hand
    #: nine times.
    #:
    #: It writes `owner`, never `status`. `apply` remains the only writer of a status, which is the
    #: invariant the two-party protocol exists for, and a repair verb that also moved statuses would be a
    #: second writer wearing a repair's name.
    if parsed.on("disown"):
        target = parsed.get("id")
        current = roadmap.milestone(target)
        if current is None:
            raise BadInput(f"no milestone {target!r} on {roadmap.path}")
        if not current.owner:
            raise BadInput(
                f"milestone {target!r} has NO owner, so there is no claim to release. Said rather than "
                f"passed over: a release that reported success for a milestone nobody claimed would read, "
                f"in a transcript, exactly like the repair this flag exists to perform.")
        if not (parsed.get("reason") or "").strip():
            raise BadInput(
                f"`--disown` needs `--reason`. An owner that silently became `None` is indistinguishable, "
                f"a week later, from one that was never claimed — which is the confusion this whole repair "
                f"exists to end, and it would be reintroduced by the repair itself.")
        #: THE safety, and the reason this is not simply `Roadmap.disown` behind a flag. `claim` refuses
        #: two instants on one milestone; a release that ignored a live owner would put the second one
        #: there by another door. "Open" is the record's own answer — neither harvested nor closed — so
        #: this asks the store rather than looking for a session, which would call a worker gone whenever
        #: tmux could not be reached.
        holder = next((r for r in ctx.store.all()
                       if r.child_instant == current.owner and not r.harvested_at and not r.closed_at),
                      None)
        if holder is not None:
            raise Refused(
                f"milestone {target!r} is claimed by {current.owner}, and that instant still has an OPEN "
                f"record (todo {holder.todo_id!r}): it has been neither harvested nor closed. Releasing "
                f"the claim now would let a second instant be dispatched onto work that is still running.",
                clears_when=f"`fleet abort --instant {current.owner} --reason <why>` (which now releases "
                            f"the claim itself), or `fleet harvest --id {holder.todo_id}`",
                clears_who=holder.todo_id)
        if ctx.dry_run:
            _emit(ctx, "milestone", [("dry-run", "the roadmap was not written"),
                                     ("would-disown", target), ("owner", current.owner),
                                     ("reason", parsed.get("reason"))])
            return EXIT_OK
        roadmap.disown(target, expect_owner=current.owner, reason=parsed.get("reason"))
        _emit(ctx, "milestone", [
            ("milestone", target), ("released-from", current.owner),
            ("reason", parsed.get("reason")),
            ("status", roadmap.milestone(target).status),
            ("dispatchable", "if its deps have landed — releasing a claim returns the milestone to the "
                             "population `dispatch --milestone` may take; it does NOT change its status")])
        return EXIT_OK

    #: The check the parser used to make. Kept word-for-word in force: `--title` went optional ONLY so
    #: `--retire` could run without one, and an add path that quietly accepts an untitled milestone is a
    #: worse defect than the one being fixed.
    if not (parsed.get("title") or "").strip():
        raise BadInput(
            "raising a milestone needs --title: an untitled milestone cannot be dispatched, because the "
            "title is what a worker's charter is rendered from. (`--retire` does not need one — it names "
            "a milestone that already exists.)")

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
    proposal = roadmap.propose(proposer, milestone, status, evidence, note=parsed.get("note") or "")
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

    **`SI-51`: the milestone goes back too, and it goes back LAST.** `abort` released the session, the
    lease and the record and left the roadmap alone, so a milestone claimed by a dispatch that was later
    aborted stayed owned by an `-abort-` folder permanently — while `claim`'s own refusal named aborting as
    the remedy. The roadmap write is the one fallible step that is deliberately AFTER the rename, because
    it is the only one whose failure cannot invalidate the abort: the folder is already `-abort-`, the
    worker is already gone, and refusing at that point would strand the instant to protect a field. So it
    follows `dispatch`'s rollback exactly — do it, and if it fails, say so loudly and name what stayed
    claimed rather than masking an outcome that has already happened.

    It releases the claim it can PROVE is its own: the owner `claim` recorded is this instant's
    `-inflight-` path, captured before the rename. An abort of instant A must never free a milestone
    instant B is running, and when the roadmap says somebody else holds it, the abort completes and reports
    whose it is.
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

    #: `SI-51`. WHICH milestone this abort releases, and on whose roadmap — read from the fact `dispatch`
    #: recorded in the instant rather than retyped by the caller. Absence is a legitimate answer: an
    #: instant from `fleet init`, or one dispatched for a ROLE rather than a milestone, has nothing to
    #: release and aborts exactly as it did before.
    #:
    #: An UNREADABLE origin is not allowed to fail the abort. `origin.read` refuses a malformed file
    #: rather than calling it absent, which is right for `propose` — but here it would mean an instant
    #: could not be abandoned because a JSON file beside it was corrupt, which is a worse outcome than the
    #: one the refusal protects. It is carried to the report instead.
    claim_owner, origin_problem = str(child), ""
    try:
        origin = origin_mod.read(child)
    except FleetError as exc:
        origin, origin_problem = None, _one_line(exc)
    milestone_id = origin.milestone if origin is not None else None
    coordinator = Path(origin.coordinator) if (origin is not None and milestone_id) else None

    if ctx.dry_run:
        _emit(ctx, "abort", [
            ("dry-run", "nothing was renamed, released, closed or written"),
            ("would-rename", f"{child.name} -> {target.name}"),
            ("would-record", f"{ABORT_FILE}: {reason}"),
            ("would-close", (record.tmux if record is not None and record.tmux else "(no session)")),
            ("would-release", (record.slot if record is not None and record.slot else "(no slot)")),
            ("milestone", milestone_id or "(none)"),
            ("would-disown", (f"{milestone_id} on {coordinator}" if coordinator is not None
                              else "(nothing claimed)"))])
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

    #: `SI-51`, and the LAST thing this transaction does — see the docstring on why this one fallible step
    #: follows the irreversible one.
    if coordinator is None:
        released = ("(nothing claimed)" if not origin_problem
                    else f"no — this instant's origin could not be read: {origin_problem}")
    else:
        try:
            Roadmap(coordinator).disown(milestone_id, expect_owner=claim_owner, reason=reason)
            released = f"yes — {milestone_id} on {coordinator} is unowned again"
        except Exception as exc:  # noqa: BLE001 - the abort has already happened; never mask it
            released = f"no — {_one_line(exc)}"
            print(f"WARNING: {child.name} was aborted, but milestone {milestone_id!r} on {coordinator} "
                  f"could NOT be released ({_one_line(exc)}). It stays claimed by an instant that no "
                  f"longer exists, so nothing may be dispatched onto it until the claim is cleared: "
                  f"`fleet milestone --instant {coordinator} --id {milestone_id} --disown --reason "
                  f"<why>`.", file=ctx.err)
    if origin_problem and coordinator is not None:
        print(f"WARNING: {origin_mod.path_of(target)} could not be read ({origin_problem}).",
              file=ctx.err)

    _emit(ctx, "abort", [
        ("from", child.name), ("to", target.name), ("path", str(target)),
        ("reason", reason), ("recorded_in", str(target / ".fleet" / ABORT_FILE)),
        ("closed", (record.tmux if record is not None and record.tmux else "(no session)")),
        ("released", (record.slot if record is not None and record.slot else "(no slot)")),
        ("record", (record.todo_id if record is not None else "(none in this store)")),
        ("milestone", milestone_id or "(none)"),
        ("milestone_released", released)])
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


def _do_peers(ctx: Ctx, parsed: Parsed) -> int:
    """Every live local Claude session, classified by PROVENANCE into addressable and not.

    Cross-session messaging made "never touch another effort's session" a matter of discipline where
    it used to be a matter of impossibility. This verb is the mechanism that replaces the discipline:
    it resolves each peer's `cwd` against this store's OPEN leases, so ownership is derived from what
    the runtime and the lease records say rather than from a name a reader has to interpret.

    It is deliberately READ-ONLY and it does not send anything. Deciding who may be addressed and
    actually addressing them are separate powers, and a verb that did both would be one mistake away
    from messaging a stranger.
    """
    rows = peers_mod.load_peers()
    leases = peers_mod.load_leases(str(ctx.home / "records"))
    results = peers_mod.classify(rows, leases)
    only = parsed.on("addressable-only")
    if ctx.porcelain:
        # `porcelain()` already terminates EVERY row including the last: `wc -l` and `while read`
        # both drop an unterminated final line, and which peer that silently loses depends only on
        # listing order -- under --addressable-only it can be the sole OURS row.
        _write(ctx, peers_mod.porcelain(results, addressable_only=only))
    else:
        _write(ctx, peers_mod.render(results, addressable_only=only))
        _write(ctx, "\n" + peers_mod.summary(results) + "\n")
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
        #: `FI-12`. `severity` was the LITERAL `INFO` on every row, so this verb could not report
        #: attention for anything — not a stranded lease, not a stalled worker, not anything, ever. The
        #: finding was "a terminal instant holding a lease raises no alarm"; the truth was that the
        #: column was a constant and the stranded lease is simply the case that noticed. Measured:
        #: `reconcile --porcelain | cut -f3 | sort -u` returned exactly one value.
        #:
        #: Derived from `reconcile.needs_a_human`, the same predicate the board's banner uses, so the
        #: verb a coordinator runs and the banner they read first cannot disagree about who is waiting.
        wants_you = needs_a_human(subject)
        stranded = subject.state == COMPLETE and subject.holds_slot
        rows.append(Row(
            kind=UNARMED if why else ARMED, subject=subject.identity,
            severity=ATTENTION if wants_you else INFO,
            clears_when=("`fleet harvest --id <id>` applies the remaining delta, kills the session and "
                         "RELEASES the slot — the rename was the worker's transition, this is the "
                         "coordinator's" if stranded else None),
            clears_who=("the coordinator that dispatched it" if stranded else None),
            detail=(f"state {subject.state}, session {subject.evidence.get('tmux', '') or '(none)'}, "
                    + (f"HOLDING {subject.evidence.get('slot') or 'a slot'} while terminal: the work is "
                       f"over and the workspace is not back. " if stranded else "")
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
    # `E9` mode 2. A bodiless claim this call could see and could not yet judge. It is NOT cleared — no
    # staging file means no pid, so nothing says its writer is dead, and below the age floor a bodiless
    # claim cannot be told from one being born. Deleting it would hand a live worker's slot to a second
    # claimant. But the slot IS unclaimable right now, and reap is the remedy the capacity refusal names,
    # so a report that omits it lets a stuck pool read as a busy one — measured: reap emitted one row,
    # `0 interrupted claim(s) reclaimed`, while a third of the pool was blocked.
    for slot, why, wait in report.unattributable:
        rows.append(Row(
            kind=REAP_UNATTRIBUTABLE, subject=slot, severity=INFO,
            detail=(f"the slot is held by a claim directory with no lease body and no staging file, so "
                    f"nothing records who was writing: {why}. NOT cleared — below the age floor a "
                    f"bodiless claim cannot be told from one being born, and clearing it would take a "
                    f"live worker's slot. The slot is unclaimable until it is"),
            clears_when=(f"`fleet reap` is run again in about {wait:.0f}s, by which point the claim is "
                         f"old enough to judge and will be reclaimed"),
            clears_who=base or ALL_EFFORTS))
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
                clears_when=("the worker runs `fleet declare --instant <instant> --phase <value>`, or the line is deleted from "
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
    #: `watchers` is on this row because a stored field NOTHING reads is not a record — it is a write-only
    #: comfort, and `FI-255` is precisely the failure of believing a state was captured when no reader
    #: could reach it. An audit found this exact shape one field along: the value was written at claim
    #: time and had ZERO production readers.
    #:
    #: `brief` is the honest home for it and NOT a complete fix, which the wording says out loud. This verb
    #: answers "one row per question you would otherwise guess at", and *"was this claim observed or
    #: merely asserted?"* is such a question. But `fleet board` — where a COORDINATOR actually looks —
    #: still renders both identically, because that is `reconcile`'s to change and out of `i39`'s charter.
    #: `i45` owns it. Saying so here is the difference between a scoped limitation and a silent one.
    watchers = declarations.watchers()
    if watchers:
        seen = ("ATTESTED by the claimant, NOT observed by this tool"
                if watchers.startswith("attested:") else "OBSERVED on the pane at claim time")
        detail = (f"phase={declarations.phase() or '(none declared)'}, "
                  f"parked={declarations.parked() or '(not parked)'}, "
                  f"watcher={watchers} — {seen}. `fleet board` does NOT yet show this distinction (i45), "
                  f"so a coordinator reading the board alone cannot tell the two apart")
    else:
        detail = (f"phase={declarations.phase() or '(none declared)'}, "
                  f"parked={declarations.parked() or '(not parked)'}")
    rows.append(Row(kind="phase", subject=child.name, severity=INFO, detail=detail))

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
#:
#: `shift+tab to cycle` is `FI-208`'s, and it is here to stop that fix introducing a defect of its own.
#: MEASURED on two live Claude Code panes on 2026-08-08 (`i7` evidence `01-red/01-w22-capture-WITH-e.raw`
#: and `04-own-pane-WITH-e.raw`): an IDLE modern pane matches **none** of the eight markers above — its
#: footer reads `⏵⏵ auto mode on (shift+tab to cycle) · ← for agents`. So the glyph fallback had already
#: rotted, and the only reason such a pane still classified as claude was that `unsubmitted` was reporting
#: the DIM ghost as text. Take the ghost away — which is the whole of `FI-208` — and the fallback answers
#: `12 not-claude`, the one code the close-out contract treats as permission to tear the pane down.
#: A fix that trades a false `10` for a false `12` has moved the error into the dangerous direction, which
#: is `FI-180`'s rule; this marker is the replacement visibility, and it is measured, not guessed.
CLAUDE_MARKERS = ("esc to interrupt", "esc to cancel", "? for shortcuts", "/ for commands",
                  "# for memory", "bypass permissions", "new task?", "claude code",
                  "shift+tab to cycle")


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
    #: `pane_plain`, because the capture carries SGR attributes since `FI-208`. A marker is a PHRASE and
    #: the TUI styles its hints: one colour change inside `esc to interrupt` and a raw substring match
    #: stops finding it. That direction reports a live claude as `12 not-claude`, the one code the
    #: close-out contract treats as permission to tear the pane down — so the strip is a safety property,
    #: not tidiness.
    lowered = pane_plain(str(text)).lower()
    if any(marker in lowered for marker in CLAUDE_MARKERS):
        return True
    return sessions.busy(text) or sessions.unsubmitted(text) is not None


def _pane_subject(ctx: Ctx, parsed: Parsed) -> str:
    """WHICH pane `pane-guard` is being asked about — `SI-54`.

    This was the only verb on the surface keyed on `--pane <session>` while `close`, `harvest`, `status`
    and `seed-check` all take `--id <todo>`. The two identifiers differ by a timestamp suffix, so the
    natural transcription is wrong, and the answer to a wrong pane name is `13`, whose detail reads *"no
    live process and no session answer"* — a sentence about a HEALTHY worker that reads as a dead one.
    This is the verb an external monitor must call before every send (`FD-10`), so its argument is retyped
    more often than any other and its failure mode is the one that most looks like a real finding.

    Exactly one, and both refusals are the point. Two identifiers that could disagree is a third failure
    mode; neither is not a question. Neither refusal returns a pane-guard CODE: a caller branching on the
    number must never read "you did not say what to look at" as an observation of a pane.
    """
    named_pane, named_id = parsed.get("pane"), parsed.get("id")
    if named_pane and named_id:
        raise BadInput(
            f"`--pane {named_pane!r}` and `--id {named_id!r}` both name the subject, and they can "
            f"disagree. Pass one: `--id` when you have the record (it resolves the session the same way "
            f"`close` does), `--pane` when you have only the session name.")
    if not named_pane and not named_id:
        raise BadInput(
            "pane-guard needs a subject: `--id <todo>` (the key every other verb takes) or "
            "`--pane <session>`.")
    if named_pane:
        return named_pane
    record = _record(ctx, parsed)
    if not record.tmux:
        raise BadInput(
            f"record {record.todo_id!r} names no tmux session, so there is no pane to guard. Refused "
            f"rather than answered `{PANE_UNKNOWN} {PANE_GUARD_CODES[PANE_UNKNOWN]}`: that code means "
            f"*this pane does not exist*, and a record that never had one is a different fact with a "
            f"different remedy — `fleet resume --instant <instant> --tmux <session>` attaches one.")
    return record.tmux


def _do_pane_guard(ctx: Ctx, parsed: Parsed) -> int:
    """The contract the external monitor is REQUIRED to call before any send-keys (FD-10).

    DA-2 enumerated **six** send paths today, so this sits at the choke point rather than being restated
    per path: a requirement phrased per-path would fix one and leave five. The codes are the interface —
    `0` safe · `10` queued text · `11` mid-turn · `12` not-claude · `13` unknown pane — and a caller
    branches on the number, never on the sentence.
    """
    pane = _pane_subject(ctx, parsed)
    if not ctx.sessions.alive(pane):
        code, detail = PANE_UNKNOWN, (f"no live process and no session answer for {pane!r}; sending keys "
                                      "to a pane nobody can name is the send with no target")
    else:
        #: `FI-7`. Absence of evidence, before absence of claude. The pane answered `alive`, so SOMETHING
        #: is there; if on top of that the capture FAILED and the process probe attributed nothing, we
        #: did not observe a non-claude pane — we failed to observe anything. Reporting that as
        #: `12 not-claude` hands a caller the one answer that authorises destroying it.
        #:
        #: `capture()`, not `pane()`, and that is the whole correction. My first version tested
        #: `not text.strip()`, which cannot tell a FAILED capture from a genuinely EMPTY pane — the exact
        #: conflation this finding is about, reintroduced one layer up. §M10 caught it immediately: a
        #: real shell pane running `sleep 900` produces no output, is genuinely not claude, and was
        #: reported `14 indeterminate` — blocking a legitimate teardown forever. The probe now returns
        #: None on failure and `""` for an empty pane, so this asks the question that was always meant.
        captured = ctx.sessions.capture(pane)
        text = captured or ""
        if captured is None and not ctx.sessions.is_claude_process(pane):
            code, detail = PANE_INDETERMINATE, (
                f"{pane} is alive but nothing about it could be read: no live claude process is "
                f"attributed to it and the pane capture FAILED — tmux did not answer. That is a failed "
                f"observation, not an observation of a non-claude pane; an empty pane that captured "
                f"cleanly is reported {PANE_NOT_CLAUDE}, not this. WAIT and re-poll; do not send, and "
                f"do not close")
        elif not _is_claude(ctx.sessions, text, pane):
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
    #: `queued_text` is a FIELD, not a sentence to be parsed back out of `detail`.
    #:
    #: Every external monitor that wants the box text has had to re-extract it from the pane, and the
    #: coordinator's `child-watchdog.sh` did exactly that with `grep '^\xe2\x9d\xaf'` — a literal-string
    #: match inside single quotes, which in BRE is the twelve characters `^xe2x9dxaf` and matches nothing
    #: any pane has ever drawn. Measured on the live log: `UNSIGNED-BOX-TEXT` fired 0 times across 218
    #: `rc=10` rows, so the FI-103 protection it guarded had never once run.
    #:
    #: The extraction being duplicated already lives in `session.unsubmitted`, which handles the caret
    #: forms, the box-drawing gutter, the placeholder shapes and the tail window, and is covered by this
    #: suite. Exported as data so there is ONE implementation: parsing machine-consumed state back out of
    #: prose is precisely what this package exists not to do.
    #:
    #: Empty for every code but `10`, and that is not a hedge — no other code asserts anything about the
    #: box, and emitting a best guess there would invent a fact.
    queued = ctx.sessions.unsubmitted(text) if code == PANE_QUEUED_TEXT else None
    _emit(ctx, PANE_GUARD, [("code", str(code)), ("verdict", PANE_GUARD_CODES[code]),
                            ("pane", pane), ("queued_text", queued or ""), ("detail", detail)])
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


# --- releases ---------------------------------------------------------------------------------------
#
# Flat verbs rather than `release <subverb>`: `parse` declares no positionals (`FI-19d`) and `main`
# dispatches on argv[0] against one flat table. Flat also means each of these enrols automatically into
# §A5's exit-code matrix and §M's flag matrices, which derive their population from `VERBS`.
#
# `--repo` is REQUIRED on every verb that touches git, and never inferred from the working directory.
# §A5 and §M drive every verb in this table through a REAL invocation; a verb that guessed its repository
# would tag the live one during an IT run. For the same reason `FLEET_RELEASES` is refused-if-unset for
# every mutating verb here: driven with no flags, these verbs exit 2 and mutate nothing.


def resolve_releases(parsed: Parsed, environ: dict, cwd) -> Releases:
    """The release area: `--releases`, `$FLEET_RELEASES`, the root's own, or refused.

    `SI-15`'s rule for a WRITE is unchanged — a mutating verb that invents a destination is how shared
    state gets written by a command aimed somewhere else. What changed is the READ default. It used to be
    `~/.fleet-releases`, **a path that does not exist on this box**: the real area is
    `<root>/fleet-releases`, named only by an export in `fleet-env.sh`. So deriving it from the marker
    replaces a phantom default with a correct one rather than merely relocating a working one.
    """
    named = parsed.get("releases") or environ.get("FLEET_RELEASES")
    if named:
        return Releases(Path(named))
    resolved = resolve_root(parsed, environ, cwd)
    if resolved is not None:
        return Releases(resolved.releases)
    spec = VERBS.get(parsed.verb)
    if spec is not None and not spec.read_only:
        raise BadInput(
            f"{parsed.verb!r} writes to a release area and none was named: pass `--releases <path>`, "
            f"export FLEET_RELEASES, or run from inside a fleet root. There is no default for a write.")
    raise BadInput(root_mod.refusal(Path(cwd), Path(environ.get("HOME") or Path.home()), parsed.verb))


def _releases(ctx: Ctx, parsed: Parsed) -> Releases:
    return resolve_releases(parsed, dict(os.environ), Path.cwd())


def _refuse_if_self_deployed(rel: Releases, parsed: Parsed) -> None:
    """A mutating release verb must not run from inside the release area it manages.

    Otherwise rolling back to a version whose release code has a bug also rolls back the ability to roll
    forward — the tool that moves `current` cannot be the thing `current` points at. Read-only verbs are
    exempt deliberately: `status` is how an operator finds out what is deployed, and it has to answer from
    the deployed copy itself.
    """
    spec = VERBS.get(parsed.verb)
    if spec is not None and spec.read_only:
        return
    here = Path(__file__).resolve()
    root = rel.root.resolve()
    if root in here.parents:
        raise Refused(
            f"{parsed.verb!r} is running from {here}, which is inside the release area {root}. Run it "
            f"from the git checkout instead. The tool that manages `current` must not be the thing "
            f"`current` points at: a bad release would otherwise take the fix path down with it.",
            clears_when="the verb is run from a checkout outside the release area",
            clears_who="whoever is running it")


def _refuse_an_existing_release(rel: Releases, version: Version) -> None:
    """Checked before the changelog is written AND again under the lock, because those are two different
    guarantees: the first refuses without touching the operator's checkout, the second is the one two
    concurrent cuts of one version actually collide on."""
    if rel.dir_for(version).exists():
        raise Refused(
            f"{version} already exists at {rel.dir_for(version)}. A release is immutable — cut the next "
            f"version instead.",
            clears_when="a version nothing has been cut for is named",
            clears_who="whoever is cutting")


def _freeze_payload(export: Path) -> None:
    """Drop every write bit on the release — the PAYLOAD only, never `META_DIR`.

    Freezing the whole directory is the obvious implementation and it is wrong: `promote` writes
    `.release/STATE` and `verify` writes `.release/evidence/`, so a release frozen whole is a release
    that can never be promoted or verified. `META_DIR` is already excluded from `tree_sha` for exactly
    this reason — it describes the release rather than being part of it — so it is the mutable half of
    the artifact and the freeze leaves it alone.

    Directories are frozen too, and that is the load-bearing half: a read-only file in a writable
    directory can still be replaced. Symlinks are skipped because `chmod` would follow them to a target
    that may not be ours.
    """
    frozen = [export] + [path for path in export.rglob("*")
                         if not path.is_symlink() and path.relative_to(export).parts[0] != META_DIR]
    for path in sorted(frozen, reverse=True):
        path.chmod(path.stat().st_mode & ~0o222)


PAYLOAD_FILE = "PAYLOAD.tsv"


def _write_payload(meta: Path, version: Version, prev_tag, changed_paths) -> None:
    """What this release actually ships, as fields rather than prose (`RI-13`).

    Shaped like `EXEMPTION.tsv`: a `key value` header, then one row per fact, so an operator can read it
    with `awk` and a reader can see the whole answer without a parser. Written for EVERY release including
    one with nothing to describe -- the file's SHAPE must not depend on the outcome, or a reader can never
    tell an empty payload from an omitted section, which is the same rule `write_exemption` follows.
    """
    buckets = areas(changed_paths or ())
    rows = ["key\tvalue",
            f"version\t{version}",
            f"compared\t{(prev_tag + '..HEAD') if prev_tag else '(no predecessor)'}",
            f"files\t{sum(len(paths) for _, paths in buckets)}"]
    rows.extend(f"area\t{name}\t{len(paths)}" for name, paths in buckets)
    rows.extend(f"skill\t{name}" for name in skills_changed(changed_paths or ()))
    rows.extend(f"path\t{name}\t{path}" for name, paths in buckets for path in paths)
    atomic_write(meta / PAYLOAD_FILE, "\n".join(rows) + "\n")


def _read_payload(meta: Path) -> dict:
    """`{"areas": [(name, count)], "skills": [name]}` for a release, or `{}` when it predates the file."""
    path = Path(meta) / PAYLOAD_FILE
    if not path.is_file():
        return {}
    found, skills = [], []
    for line in path.read_text().splitlines()[1:]:
        cells = line.split("\t")
        if cells[0] == "area" and len(cells) >= 3:
            found.append((cells[1], cells[2]))
        elif cells[0] == "skill" and len(cells) >= 2:
            skills.append(cells[1])
    return {"areas": found, "skills": skills}


def _do_release_cut(ctx: Ctx, parsed: Parsed) -> int:
    rel = _releases(ctx, parsed)
    _refuse_if_self_deployed(rel, parsed)
    version = Version.parse(parsed.get("version"))
    repo = Repo(parsed.get("repo"), git=ctx.git)
    stamped = repo.path / "fleet" / "src" / "fleet" / "__init__.py"
    if not stamped.is_file():
        raise BadInput(
            f"{repo.path} is a git repository but not the fleet checkout: {stamped} is not there, and a "
            f"cut rewrites that file's `__version__` before it tags. Refused at the edge and by name — "
            f"the alternative is a failure half way through, after the changelog has been written.")
    #: The same edge check for the OTHER files a cut stamps (`RI-12`). Writes nothing: a manifest that is
    #: unparseable or has lost its declared field must refuse while the operator's checkout is untouched,
    #: not between the changelog write and the tag — which is the reason the line above exists.
    stamp_plugin_version(repo.path, version, dry_run=True)
    _refuse_an_existing_release(rel, version)
    if repo.tag_exists(version.tag):
        raise Refused(
            f"the tag {version.tag} already exists in {repo.path}. A release tag is never moved: it is "
            f"what keeps the exact tree recoverable after the nightly rebase rewrites its commits off "
            f"the branch. Choose the next version instead.",
            clears_when="an untagged version is named", clears_who="whoever is cutting")
    dirty = repo.dirty()
    if dirty:
        raise Refused(
            f"the tree at {repo.path} has {len(dirty)} uncommitted path(s): "
            f"{', '.join(dirty[:5])}{' …' if len(dirty) > 5 else ''}. An export carries committed "
            f"content only, so a dirty tree means the thing tested is not the thing you edited.",
            clears_when="the listed paths are committed or reverted",
            clears_who="whoever is mid-edit")

    prev = rel.previous(version)
    prev_tag = prev.tag if prev else None
    if prev_tag is not None and not repo.tag_exists(prev_tag):
        # Refused rather than treated as "no predecessor". The delta is computed against this tag, so a
        # missing one does not mean "nothing shipped before" — it means the range cannot be computed, and
        # the changelog would silently re-list everything the previous release already carried.
        raise Refused(
            f"the release area's predecessor of {version} is {prev}, and its tag {prev_tag} is not in "
            f"{repo.path}. The delta is computed against that tag, so cutting now would write a "
            f"changelog covering commits {prev} already shipped.",
            clears_when=f"{prev_tag} is back in the checkout (`git fetch --tags`, or the repo the "
                        f"release area was cut from is the one named)",
            clears_who="whoever is cutting")
    rebased = bool(prev_tag) and not repo.is_ancestor(prev_tag, "HEAD")
    commits = repo.delta(prev_tag)
    when, head = utc_now(), repo.head()
    #: `RI-13`. Taken HERE, before the lock rewrites the changelog and the version stamps, so a release's
    #: payload description is the author's change and never the release's own bookkeeping (`AS-6`).
    #: Two-dot, like `exemption_for`'s: whether a path is in the payload is a question about CONTENT.
    payload = repo.changed_paths(prev_tag, "HEAD") if prev_tag is not None else None
    section = changelog_section(version, head=head, branch=repo.branch(),
                                upstream_base=repo.upstream_base(), prev_tag=prev_tag,
                                commits=commits, rebased=rebased, when=when, changed_paths=payload)
    since = prev_tag or "(no predecessor)"

    if ctx.dry_run:
        rows = [("dry-run", "nothing was written, committed, tagged or exported"),
                ("would-cut", f"{version} from {head[:7]} on {repo.branch()}"),
                ("would-tag", version.tag),
                ("would-export", str(rel.dir_for(version))),
                ("commits", f"{len(commits)} since {since}")]
        #: The payload and the stamps, PREVIEWED. A dry run whose only unknown is "what will this actually
        #: ship" is a dry run that answers the easy half of the question -- and the payload is the half an
        #: operator gets wrong, because "fleet release" reads as "the CLI" (`RI-13`).
        rows.extend((f"would-ship-{name}", f"{len(paths)} file(s)") for name, paths in areas(payload or ()))
        #: `-names`, not `would-ship-skills`, which is already the area's file count. A key-value report
        #: with two rows under one key is one an operator cannot read and a script cannot parse.
        if payload and (named := skills_changed(payload)):
            rows.append(("would-ship-skill-names", ", ".join(named)))
        rows.extend((f"would-stamp-{path}", f"{old} -> {new}")
                    for path, old, new in stamp_plugin_version(repo.path, version, dry_run=True))
        _emit(ctx, "release-cut", rows)
        return EXIT_OK

    with rel.lock():
        _refuse_an_existing_release(rel, version)
        changelog = repo.path / "fleet" / "CHANGELOG.md"
        existing = changelog.read_text() if changelog.is_file() else "# fleet — changelog\n"
        head_line, _, rest = existing.partition("\n")
        changelog.write_text(f"{head_line}\n\n{section}\n{rest.lstrip()}")
        stamped.write_text(re.sub(r'__version__ = "[^"]*"', f'__version__ = "{version}"',
                                  stamped.read_text()))
        #: `RI-12`. The version a user READS lives in the plugin manifests, not in `__init__.py`:
        #: `claude plugin list` printed `Version: 6.2.0` on a box running fleet 0.3.7, and did so at all
        #: fifteen release tags. Stamped INSIDE the lock and BEFORE the tag, or the export -- a
        #: `git archive` of that tag -- ships manifests naming the previous release.
        stamped_manifests = stamp_plugin_version(repo.path, version)
        repo.commit([changelog, stamped] + [repo.path / path for path, _, _ in stamped_manifests],
                    f"fleet v{version}")
        repo.annotated_tag(version.tag, section)

        export = rel.dir_for(version)
        repo.export(version.tag, export)
        # THIS release's section, in the release's own metadata. The payload does carry the running
        # `fleet/CHANGELOG.md` — the tag is made after the commit, so the export has it — but that file
        # is the whole history, and "what changed in the version I am holding" is a different question
        # that the holder of one artifact should not have to answer by diffing two of them.
        atomic_write(export / META_DIR / "CHANGELOG.md", section)
        #: `RI-13`, for the reader who has the box and not the repository. The changelog says it in prose;
        #: this says it in fields, so `release-status` can answer "what is deployed" with what is IN it.
        _write_payload(export / META_DIR, version, prev_tag, payload)
        rel.write_manifest(version, {
            "version": str(version), "tag": version.tag, "source_commit": repo.head(),
            "source_branch": repo.branch(), "upstream_base": repo.upstream_base(),
            # `II-7`. WHERE it was cut from, not just what. `release-verify` runs the IT suite in a
            # worktree at this release's tag, because the suite cannot judge an export, and a worktree
            # needs a repository. Recording it here means verifying is one command; without it the
            # operator has to remember months later which checkout a tag lives in, and `--repo` is the
            # only way to say so.
            "source_repo": str(repo.path),
            "tree_sha": tree_sha(export), "cut_at": when, "cut_by": actor(),
            "notes": parsed.get("notes") or "-"})
        rel.set_state(version, CANDIDATE)
        _freeze_payload(export)
        #: Inside the lock and AFTER the new release has landed, so a prune can never leave the area
        #: below the ceiling by removing something while this cut is still half-written. A release is
        #: ~5 MB frozen and the cadence is a release per few fixes; without a ceiling the area grows
        #: without bound. The DEPLOYED release is never removed however old — see `Releases.prune`.
        pruned = rel.prune()

    rows = [("version", str(version)), ("state", CANDIDATE), ("tag", version.tag),
            ("path", str(rel.dir_for(version))), ("commits", f"{len(commits)} since {since}")]
    #: Reported, never silent. A release area that deletes artifacts without saying so is one an operator
    #: cannot reconcile against `release-list` — and "absence is never success" is the rule the reap
    #: report already follows for the same reason.
    for gone, why in pruned:
        rows.append((f"pruned-{gone}", why))
    if pruned:
        rows.append(("retention", f"{RELEASE_RETENTION} releases kept; {len(pruned)} removed. Every one "
                                  f"is still recoverable from its tag"))
    _emit(ctx, "release-cut", rows)
    return EXIT_OK


def _do_release_verify(ctx: Ctx, parsed: Parsed) -> int:
    rel = _releases(ctx, parsed)
    _refuse_if_self_deployed(rel, parsed)
    version = Version.parse(parsed.get("version"))
    export = rel.dir_for(version)
    if not export.is_dir():
        raise BadInput(f"no release {version} at {export}. `release-list` shows what has been cut.")
    roster = FULL_ROSTER if parsed.on("full") else GATE_ROSTER

    if ctx.dry_run:
        _emit(ctx, "release-verify", [
            ("dry-run", "no suite was run and no evidence was written"),
            ("would-verify", f"{version} at {export}"),
            ("would-run", f"the {roster} roster")])
        return EXIT_OK

    if ctx.live_work_now():
        print("note: this box has live fleet work. The IT suite baselines the live session set, so a "
              "failure may be contamination rather than a defect — that is what INCONCLUSIVE records.",
              file=ctx.err)
    # `ctx.runner` is the seam every handler is handed, and `Verify` REQUIRES it: a `subprocess` default
    # inside `release_verify` would be a fourth spawn site in the package (`FI-27a`).
    #
    # `--repo` is optional and overrides the MANIFEST's `source_repo` (`II-7`). The suite runs in a
    # worktree at the release's tag because it cannot judge an export, so a repository is needed; a
    # release cut after that field existed carries its own, and one cut before it must be told.
    repo = Repo(parsed.get("repo"), git=ctx.git) if parsed.get("repo") else None

    #: The exemption check, BEFORE anything is spawned. A release is a `git archive` of the whole
    #: repository, so a docs- or skills-only release otherwise pays ~24 minutes to prove that `fleet/` --
    #: which it did not touch -- still works. The alternative in use before this was
    #: `release-deploy --force`, which is not a decision but an override: it discards the gate and records
    #: the release UNVERIFIED, which is how `0.3.2` came to be deployed without evidence.
    #:
    #: Fail-safe: `exemption_for` answers None -- run them -- for every uncertainty, and the classifier
    #: is an allowlist, so an unrecognised path can never skip the gate. The repository is resolved the
    #: same way the suites resolve it, because the diff needs the anchor's tag.
    scope_repo = repo or Verify(rel, version, ctx.runner).repo()
    exempted = exemption_for(rel, version, scope_repo, full=parsed.on("full"))
    if exempted is not None:
        anchor, scope = exempted
        anchor_tag = rel.manifest(anchor).get("tag") or anchor.tag
        this_tag = rel.manifest(version).get("tag") or version.tag
        meta = export / META_DIR
        #: `RI-17`. This path writes the evidence directory without ever constructing a `Verify`, so it
        #: needs the archive as much as the suite path does — and it is the path that PROVED it: release
        #: `0.3.6` shipped RELEASED and EXEMPT carrying a `hermetic.log` and a `live-subjects-before.tsv`
        #: from an abandoned earlier attempt, which the exempt branch writes neither of. A release whose
        #: evidence says "no suite was required" was shipping a suite log.
        archive_previous_attempt(meta)
        write_exemption(meta, version, anchor, anchor_tag, this_tag, scope)
        note = (f"not required: {len(scope.inert)} changed path(s) since {anchor}, none of which either "
                f"suite reads")
        write_verdict(meta, [("hermetic", EXEMPT, "evidence/EXEMPTION.tsv", note),
                             ("it", EXEMPT, "evidence/EXEMPTION.tsv", note)], EXEMPT_ROSTER,
                      result=EXEMPT)
        _emit(ctx, "release-verify", [
            ("version", str(version)), ("verdict", EXEMPT), ("roster", EXEMPT_ROSTER),
            ("anchor", f"{anchor} ({anchor_tag}) — the newest release verified GREEN"),
            ("compared", f"{anchor_tag}..{this_tag}"),
            ("paths", f"{len(scope.inert)} changed, all inert"),
            ("evidence", str(meta / "evidence"))])
        return EXIT_OK

    result = Verify(rel, version, ctx.runner, repo=repo).run(full=parsed.on("full"))
    _emit(ctx, "release-verify", [
        ("version", str(version)), ("verdict", result), ("roster", roster),
        ("evidence", str(export / META_DIR / "evidence"))])
    return EXIT_OK if result == GREEN else EXIT_ATTENTION


def _do_release_promote(ctx: Ctx, parsed: Parsed) -> int:
    rel = _releases(ctx, parsed)
    _refuse_if_self_deployed(rel, parsed)
    version = Version.parse(parsed.get("version"))
    verdict = read_verdict(rel.dir_for(version) / META_DIR)
    suites = verdict.get("suites") or {}
    if not suites or any(value not in PROMOTABLE for value in suites.values()):
        raise Refused(
            f"{version} has no promotable evidence: {suites or 'no VERDICT.tsv at all'}. Run "
            f"`fleet release-verify --version {version}` first. `promote` never runs tests — it reads "
            f"what `verify` left, so a promotion always cites a measurement someone can go and look at. "
            f"An EXEMPT verdict is promotable too, and it cites the diff that earned it "
            f"(`evidence/EXEMPTION.tsv`) rather than a test run.",
            clears_when=f"`fleet release-verify --version {version}` records a GREEN or EXEMPT verdict",
            clears_who="whoever is releasing")
    prev = rel.previous(version)
    #: An exemption says "nothing either suite reads has changed". A minor or major bump asserts the
    #: opposite in the version number, and the two cannot both be true: whichever is wrong, the operator
    #: should find out from a suite rather than from production. Cheap insurance -- a patch release is the
    #: shape a documentation change actually has.
    if prev is not None and version.bump_kind(prev) in ("minor", "major") \
            and any(value == EXEMPT for value in suites.values()):
        raise Refused(
            f"{version} is a {version.bump_kind(prev)} bump over {prev}, and its evidence is EXEMPT — no "
            f"suite ran. A bump of that size claims substantive change while the exemption claims nothing "
            f"either suite reads was touched; they cannot both hold.",
            clears_when=f"`fleet release-verify --version {version} --full` records a GREEN verdict "
                        f"(`--full` never exempts), or the version is cut as a patch",
            clears_who="whoever is releasing")
    if prev is not None and version.bump_kind(prev) in ("minor", "major") \
            and verdict.get("roster") != FULL_ROSTER:
        raise Refused(
            f"{version} is a {version.bump_kind(prev)} bump over {prev}, and its evidence covers only "
            f"the {verdict.get('roster')} roster. Re-run with "
            f"`fleet release-verify --version {version} --full`.",
            clears_when=f"a --full verify of {version} records a GREEN verdict",
            clears_who="whoever is releasing")

    if ctx.dry_run:
        _emit(ctx, "release-promote", [
            ("dry-run", "the state file was not written"),
            ("would-promote", f"{version}: {rel.state(version)} -> {RELEASED}"),
            #: Names the verdicts rather than asserting GREEN: an EXEMPT promotion reported as
            #: "2 suite(s) GREEN" would be the same lie about evidence that `SI-38` cost.
            ("evidence", f"{verdict.get('roster')} roster, "
                         f"{', '.join(f'{name}={value}' for name, value in sorted(suites.items()))}")])
        return EXIT_OK

    with rel.lock():
        rel.set_state(version, RELEASED)
    _emit(ctx, "release-promote", [
        ("version", str(version)), ("state", RELEASED),
        ("evidence", str(rel.dir_for(version) / META_DIR / "evidence" / "VERDICT.tsv"))])
    return EXIT_OK


def _deploy(ctx: Ctx, parsed: Parsed, rel: Releases, target_label: str, target_path: Path,
            action: str, reason: str) -> int:
    """The one place `current` moves. `deploy` and `rollback` differ in how they choose their target and
    in the row they leave behind, and in nothing else — two copies of a symlink flip is how the two of
    them would end up disagreeing about what gets recorded."""
    before = rel.current_label()
    if ctx.dry_run:
        _emit(ctx, parsed.verb, [
            ("dry-run", "`current` was not moved and no history row was written"),
            ("would-point", f"{before} -> {target_label}"),
            ("would-target", str(target_path)),
            ("would-record", f"{action}: {reason}")])
        return EXIT_OK

    with rel.lock():
        before = rel.current_label()
        running = [subject for subject in ctx.subjects() if subject.state == RUNNING]
        if running:
            print(f"note: {len(running)} subject(s) are RUNNING. Their next `fleet` call gets "
                  f"{target_label}; the one in flight keeps the release it started on.", file=ctx.err)
        rel.point_current_at(target_path)
        evidence = "-" if target_label == DEV else f"{Path(target_path).name}/{META_DIR}/evidence"
        rel.append_history(action=action, version=target_label, from_version=before,
                           reason=reason, evidence=evidence)
    _emit(ctx, parsed.verb, [
        ("action", action), ("from", before), ("current", target_label),
        ("path", str(target_path)), ("reason", reason)])
    return EXIT_OK


def _checkout_of_this_package() -> Path:
    """The git checkout this module was loaded from — what `--dev` points `current` at.

    `parents[3]` is `<checkout>` for `<checkout>/fleet/src/fleet/cli.py`, which is the same shape an
    export has: the release directory holds `fleet/` at its top, so both ends of the symlink are resolved
    the same way by every consumer.
    """
    return Path(__file__).resolve().parents[3]


def _do_release_deploy(ctx: Ctx, parsed: Parsed) -> int:
    rel = _releases(ctx, parsed)
    _refuse_if_self_deployed(rel, parsed)
    reason = parsed.get("reason")
    if parsed.on("dev"):
        return _deploy(ctx, parsed, rel, DEV, _checkout_of_this_package(), DEV,
                       reason or "developer mode")
    version = Version.parse(parsed.get("version"))
    if not rel.dir_for(version).is_dir():
        raise BadInput(f"no release {version} at {rel.dir_for(version)}. `release-list` shows what has "
                       f"been cut.")
    if rel.state(version) != RELEASED:
        if not parsed.on(FORCE):
            raise Refused(
                f"{version} is {rel.state(version)}, not {RELEASED}. Promote it, or pass `{FORCE}` WITH "
                f"a `--reason`.",
                clears_when=f"`fleet release-promote --version {version}` succeeds, or {FORCE} is passed "
                            f"with a reason",
                clears_who="whoever is deploying")
        if not reason:
            raise Refused(
                f"`{FORCE}` requires `--reason`. Deploying an unverified candidate is exactly the event "
                f"the history file exists to explain.",
                clears_when="a reason is supplied", clears_who="whoever is deploying")
    return _deploy(ctx, parsed, rel, str(version), rel.dir_for(version), "DEPLOY",
                   reason or f"deploy {version}")


def _do_release_rollback(ctx: Ctx, parsed: Parsed) -> int:
    rel = _releases(ctx, parsed)
    _refuse_if_self_deployed(rel, parsed)
    reason = parsed.get("reason")
    target = parsed.get("to")
    if target is None:
        rows = [row for row in rel.history() if row["action"] in ("DEPLOY", "ROLLBACK")]
        # `"none"` is what `Releases.current_label` answers when nothing is deployed, so it is what the
        # FIRST deploy records as the thing it came from — a label, and not a version to return to.
        if not rows or rows[-1]["from_version"] in ("-", "", "none"):
            raise BadInput(
                "no previous deployment is recorded, so there is nothing to roll back to. Name one with "
                "`--to <version>`.")
        target = rows[-1]["from_version"]
    if target == DEV:
        return _deploy(ctx, parsed, rel, DEV, _checkout_of_this_package(), "ROLLBACK", reason)
    version = Version.parse(target)
    if not rel.dir_for(version).is_dir():
        raise BadInput(f"no release {version} at {rel.dir_for(version)}. `release-list` shows what has "
                       f"been cut.")
    return _deploy(ctx, parsed, rel, str(version), rel.dir_for(version), "ROLLBACK", reason)


def _do_release_status(ctx: Ctx, parsed: Parsed) -> int:
    rel = _releases(ctx, parsed)
    label = rel.current_label()
    rows = [row for row in rel.history() if row["action"] in ("DEPLOY", "ROLLBACK", DEV)]
    last = rows[-1] if rows else None
    out = [("current", label)]
    if label == DEV:
        # `DEV` alone is true about the pointer and misleading about the code: in dev mode what is live is
        # whatever the checkout says right now. Asked through `ctx.runner` — the injected seam every
        # handler gets — because a handler calls the runner and never a spawner.
        checkout = rel.current_target()
        where = shlex.quote(str(checkout))
        head_code, head_out, _ = ctx.runner(f"git -C {where} rev-parse --short HEAD")
        dirty_code, dirty_out, _ = ctx.runner(f"git -C {where} status --porcelain")
        out.append(("checkout", str(checkout)))
        out.append(("head", head_out.strip() if head_code == 0 and head_out.strip() else "unknown"))
        out.append(("dirty", "yes" if (dirty_code == 0 and dirty_out.strip()) else "no"))
    elif label != "none":
        version = Version.parse(label)
        out.append(("state", rel.state(version)))
        #: `RI-13`. "What is deployed" is a question about CONTENT as much as about a version number, and
        #: `fleet-releases/current` is the marketplace source every session on this box loads from — so
        #: "which skills does the thing I am running carry" is answerable here or nowhere.
        payload = _read_payload(rel.dir_for(version) / META_DIR)
        if payload.get("areas"):
            out.append(("payload", ", ".join(f"{name} ({count})"
                                             for name, count in payload["areas"])))
        if payload.get("skills"):
            out.append(("skills", ", ".join(payload["skills"])))
    if last:
        out.append(("since", last["ts"]))
        out.append(("by", last["actor"]))
        out.append(("reason", last["reason"]))
    _emit(ctx, "release-status", out)
    return EXIT_OK


def _do_release_list(ctx: Ctx, parsed: Parsed) -> int:
    rel = _releases(ctx, parsed)
    current = rel.current_label()
    _emit(ctx, "release-list", [
        (str(version), rel.state(version), rel.manifest(version).get("cut_at", "-"),
         "*" if str(version) == current else "")
        for version in rel.versions()])
    return EXIT_OK


def _do_release_history(ctx: Ctx, parsed: Parsed) -> int:
    rel = _releases(ctx, parsed)
    rows = rel.history()
    limit = parsed.get("limit")
    if limit is not None:
        try:
            count = int(limit)
        except (TypeError, ValueError):
            raise BadInput(f"--limit takes an integer number of rows; got {limit!r}")
        if count < 0:
            raise BadInput(f"--limit takes a number of rows to show; got {limit!r}")
        rows = rows[len(rows) - count:] if count else []
    _emit(ctx, "release-history", [tuple(row[name] for name in HISTORY_COLUMNS) for row in rows])
    return EXIT_OK


# --- the registry ---------------------------------------------------------------------------------


def _do_root_init(ctx: Ctx, parsed: Parsed) -> int:
    """Make a directory a fleet root: the marker, the store skeleton, and a release area.

    The whole verb is `root.check_new_root` followed by four writes, and that split is deliberate — the
    rules for what MAY become a root belong beside `find` and `load`, because a creator with its own
    definition writes markers the finder cannot honour.

    **The marker is written LAST, and nothing is rolled back.** Both halves are the same decision. Until
    the marker exists the directory is not a root: `find` walks past it, no store resolves to it, and the
    `.fleet/` and `fleet-releases/` it may already contain are inert. So a failure part-way leaves litter
    rather than a half-built root, and the litter is what a re-run reuses — every directory here is
    created with `exist_ok`. `SI-21` asks that a rollback not strand state it created; the answer here is
    that there is no state to strand, which is a better answer than a delete path this verb would
    otherwise be the only caller of.

    **`instants/` is deliberately absent.** `$FLEET_HOME/instants` is the directory `FI-382` planted a
    stray child in for two releases and `SI-56` spent three corrections refusing. Creating it in every new
    root would hand that trap a home; a dispatch names where instants go, or it is refused.
    """
    home = Path(os.environ.get("HOME") or Path.home())
    target = root_mod.check_new_root(parsed.get("path"), home)
    name = root_mod.check_name(parsed.get("name"), f"--name for {target}")

    releases = target / "fleet-releases"
    share = parsed.get("share-releases")
    shared = None
    if share is not None:
        shared = Path(share)
        if not shared.is_dir():
            raise BadInput(
                f"--share-releases {shared} is not an existing directory. Sharing a release area means "
                f"pointing this root at ANOTHER root's, so that both resolve one `current` and always run "
                f"the same version; there is nothing to point at yet.")
        if releases.exists() or releases.is_symlink():
            raise BadInput(
                f"{releases} already exists, so it cannot be made a link to {shared}. Move it aside if "
                f"this root should share {shared} instead of owning its own release area.")

    store = target / ".fleet"
    plan = [("root", str(target)), ("name", name), ("marker", str(target / root_mod.MARKER)),
            ("store", str(store)), ("socket", f"fleet-{name}"),
            ("releases", str(releases) + ("" if shared is None else f" -> {shared}")),
            ("instants", "(not created — a dispatch names where instants go; SI-56)")]

    if ctx.dry_run:
        _emit(ctx, "root-init", plan + [("created", "no — --dry-run")])
        return EXIT_OK

    for part in ("records", "pool", "harvest"):
        (store / part).mkdir(parents=True, exist_ok=True)
    if shared is None:
        releases.mkdir(exist_ok=True)
    else:
        atomic_symlink(shared, releases)
    #: Last, and this is the ordering the docstring argues for: this write is what turns the directory
    #: above from litter into a root.
    atomic_write(target / root_mod.MARKER, json.dumps({"name": name}) + "\n")

    _emit(ctx, "root-init", plan + [("created", "yes")])
    return EXIT_OK


def _verb(name: str, handler: Callable, read_only: bool, help_text: str, flags=(),
          checker: bool = False, needs_store: bool = True) -> VerbSpec:
    """Build one spec. `--dry-run` is APPENDED FROM `read_only`, never typed per verb: the next mutating
    verb somebody adds gets an interrogable form whether or not they remembered to ask for one.

    `checker` is passed through and never inferred: §9's population rule is applied to whatever this says,
    so it is said here beside the handler rather than read off a column tuple two modules away (`FI-19c`).
    """
    declared = tuple(flags) + COMMON_FLAGS + (() if read_only else (DRY_RUN_FLAG,))
    return VerbSpec(name=name, flags=declared, handler=handler, read_only=read_only, help=help_text,
                    checker=checker, needs_store=needs_store)


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
        #: `SI-53`. A FILE, not an inline string: a briefing addition with newlines typed through a shell
        #: argument is how quoting bugs enter a worker's contract.
        Flag("--seed-extra", True, False,
             "a file whose text is appended to this dispatch's rendered seed, inside the transaction. "
             "For the sentence that is specific to THIS dispatch; the alternative was editing seed.txt "
             "in the window between dispatch returning and the launcher reading it"),
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
        Flag("--watcher", True, False,
             "NAME what is watching, when it is real but this tool cannot see it (a cron, an external "
             "watchdog, a peer session). The test is whether you can TRUTHFULLY name it — not whether "
             "the refusal feels wrong. Records your attestation verbatim in declare.json and reports it "
             "on `fleet brief`; `fleet board` does NOT yet distinguish an attested claim from an "
             "observed one (i45)"),
    )),
    _verb("park", _do_park, False, "record a parked decision as structured state", (
        Flag("--instant", True, True, "the instant"),
        Flag("--question", True, True, "the question; an empty park is not a park"),
    )),
    _verb("unpark", _do_unpark, False, "clear a parked decision", (
        Flag("--instant", True, True, "the instant"),
    )),
    _verb("milestone", _do_milestone, False,
          "the COORDINATOR puts a milestone ON the roadmap, or retires a superseded one", (
        Flag("--instant", True, True, "the instant holding the roadmap"),
        Flag("--id", True, True, "the milestone id, unique within the roadmap"),
        #: NOT parser-required, because `--retire` names an EXISTING milestone and inventing a title to
        #: delete something is absurd. The parser cannot say "required unless --retire", so the ADD path
        #: enforces it in the handler — with the same refusal it always gave, because a title that
        #: became silently optional is how untitled milestones start appearing (`FI-10`).
        Flag("--title", True, False,
             "what the milestone is; required when RAISING one — an untitled milestone cannot be "
             "dispatched. Not needed with --retire, which names an existing milestone"),
        #: `SI-51`. Beside `--retire` for the same reason it is: same actor, same file, same authority.
        Flag("--disown", False, False,
             "release the CLAIM on --id, leaving its status alone. For a milestone stranded by an instant "
             "that is gone; refused while that instant still has an open record. Needs --reason"),
        Flag("--status", True, False, "blocked|ready|running|awaiting-ci|done|dropped (default: blocked)"),
        Flag("--dep", True, False, "a milestone id this one depends on; repeatable, and each must EXIST"),
        Flag("--evidence", True, False, "an evidence path; repeatable"),
        Flag("--owner", True, False, "informational only — readiness never reads it"),
        Flag("--retire", False, False,
             "retire an EXISTING milestone: sets it dropped and removes it from the ready population"),
        Flag("--reason", True, False, "why it was retired; required with --retire"),
    )),
    _verb("propose", _do_propose, False, "the WORKER's status proposal; never a roadmap write", (
        Flag("--instant", True, True, "the PROPOSING instant — its id is what attributes the proposal"),
        Flag("--to", True, False, "the instant holding the roadmap to propose INTO; defaults to --instant"),
        Flag("--milestone", True, True, "the milestone id"),
        Flag("--status", True, True, "blocked|ready|running|awaiting-ci|done|dropped"),
        Flag("--evidence", True, True, "an evidence path; repeatable, and at least one is required"),
        #: `I-2`. One line ABOUT the proposal, never instead of the evidence — a worker reported
        #: that evidence paths were its only narrative channel, and worked around it by writing a
        #: file purely to cite it. Optional, and matches `abort --reason` / `park --question`.
        Flag("--note", True, False, "one line of narrative about the proposal; never replaces --evidence"),
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
    _verb("root-init", _do_root_init, False,
          "make a directory a fleet root: its marker, store and release area", (
        Flag("--path", True, True, "the directory to mark; must be an existing directory under $HOME"),
        Flag("--name", True, True,
             "this root's declared name; becomes the tmux socket `fleet-<name>`. Declared rather than "
             "derived from the directory, because a derived name moves when somebody renames a folder "
             "and takes every running session's server with it (FI-421)"),
        Flag("--share-releases", True, False,
             "point this root's `fleet-releases` at an existing release area instead of creating one, so "
             "both roots resolve a single `current` and always run the same version"),
    ), needs_store=False),
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
    _verb("peers", _do_peers, True,
          "live local Claude sessions, classified by provenance into addressable and FOREIGN",
          flags=(
        Flag("--addressable-only", False, help="print only the peers this fleet owns"),
    )),
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
    _verb("seed-delivered", _do_seed_delivered, False,
          "record what was actually delivered to a worker's pane; for send-keys, which leaves no argv", (
        Flag("--id", True, True, "the record whose worker was briefed"),
        Flag("--delivered", True, True,
             "a file holding exactly the text that was sent. Compared against the rendered seed and "
             "REFUSED on a mismatch; a preamble is fine, a different briefing is not"),
        Flag("--channel", True, False, "how it was delivered (default: send-keys)"),
        Flag("--by", True, False, "who delivered it (default: the record's session)"),
    )),
    _verb("seed-check", _do_seed_check, True,
          "is every live worker running the briefing that was rendered FOR it? (seed misdelivery)",
          checker=True, flags=(
        Flag("--id", True, False, "restrict to one todo id, or a unique substring of it"),
    )),
    _verb(PANE_GUARD, _do_pane_guard, True,
          "the send-keys contract: 0 safe / 10 queued / 11 mid-turn / 12 not-claude / 13 unknown / "
          "14 indeterminate (could not read; wait)", (
        #: `SI-54`. Neither is parser-required and exactly one is required by the handler: the parser can
        #: say "required" but not "exactly one of", and `--pane` staying mandatory would make `--id`
        #: unreachable. Both name the same subject, so accepting both is refused rather than resolved.
        Flag("--pane", True, False, "the pane (session) name"),
        Flag("--id", True, False,
             "the record whose session to ask about — the same key `close`, `harvest` and `status` take. "
             "Resolved through the record's `tmux` field; use it instead of retyping a session name that "
             "differs from the todo id by a timestamp suffix"),
    )),
    _verb("compaction-status", _do_compaction_status, True,
          "whether a compaction is holding every dispatch", checker=True, flags=(
        Flag("--base", True, False, "restrict to one base"),
    )),
    _verb("selftest", _do_selftest, True,
          "discover and run every suite; the tree state is ALWAYS stamped (AC-10)", checker=True),
    _verb("release-cut", _do_release_cut, False,
          "export an immutable release from a tag and write its changelog", (
        Flag("--version", True, True, "the new version, X.Y.Z; the tag becomes fleet/vX.Y.Z"),
        Flag("--repo", True, True, "the git checkout to cut from; never inferred from the cwd"),
        Flag(RELEASES, True, False, RELEASES_HELP),
        Flag("--notes", True, False, "a one-line note recorded in MANIFEST.tsv"),
    )),
    _verb("release-verify", _do_release_verify, False,
          "run both suites against a release's frozen export and record the verdict", (
        Flag("--version", True, True, "the release to verify"),
        Flag(RELEASES, True, False, RELEASES_HELP),
        Flag("--repo", True, False,
             "the checkout holding this release's tag; defaults to the MANIFEST's source_repo"),
        Flag("--full", False, False, "run every IT runner, not just the gate roster"),
    )),
    _verb("release-promote", _do_release_promote, False,
          "mark a CANDIDATE as RELEASED; refuses without GREEN evidence", (
        Flag("--version", True, True, "the release to promote"),
        Flag(RELEASES, True, False, RELEASES_HELP),
    )),
    _verb("release-deploy", _do_release_deploy, False,
          "point `current` at a release, or at the checkout with --dev", (
        Flag("--version", True, False, "the release to deploy"),
        Flag("--dev", False, False, "point `current` at the git checkout, restoring live editing"),
        Flag(RELEASES, True, False, RELEASES_HELP),
        Flag("--reason", True, False, "recorded in the history; REQUIRED with --force"),
        Flag(FORCE, False, False, "deploy a CANDIDATE anyway; requires --reason"),
    )),
    _verb("release-rollback", _do_release_rollback, False,
          "point `current` back, recording why", (
        Flag("--to", True, False, "the version to return to; defaults to the previously deployed one"),
        Flag("--reason", True, True, "why — the reason is the whole point of the history file"),
        Flag(RELEASES, True, False, RELEASES_HELP),
    )),
    _verb("release-status", _do_release_status, True,
          "what is deployed right now, since when, by whom and why", (
        Flag(RELEASES, True, False, RELEASES_HELP),
    )),
    _verb("release-list", _do_release_list, True, "every release, its state and its cut time", (
        Flag(RELEASES, True, False, RELEASES_HELP),
    )),
    _verb("release-history", _do_release_history, True, "the deploy/rollback register", (
        Flag(RELEASES, True, False, RELEASES_HELP),
        Flag("--limit", True, False, "show only the last N rows"),
    )),
)}

#: The porcelain schema per verb, declared as data so a consumer and a test read the column count off the
#: surface rather than off a comment that can go stale (`W2-20`'s class).
PORCELAIN_COLUMNS = {
    "peers": peers_mod.PEER_COLUMNS,
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
    "root-init": KV_COLUMNS,
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
    "seed-check": ROW_COLUMNS,
    "seed-delivered": KV_COLUMNS,
    "compaction-status": ROW_COLUMNS,
    "selftest": ROW_COLUMNS,
    "brief": ROW_COLUMNS,
    "base-check": ROW_COLUMNS,
    "board": render.BOARD_COLUMNS,
    "status": render.STATUS_COLUMNS,
    "leases": render.LEASE_COLUMNS,
    "roadmap": render.ROADMAP_COLUMNS,
    "release-cut": KV_COLUMNS,
    "release-verify": KV_COLUMNS,
    "release-promote": KV_COLUMNS,
    "release-deploy": KV_COLUMNS,
    "release-rollback": KV_COLUMNS,
    "release-status": KV_COLUMNS,
    "release-list": RELEASE_COLUMNS,
    "release-history": HISTORY_COLUMNS,
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
    if ctx.harvest is None:
        #: No store resolved, so there is no watched-source registry to be stale. Silence is right here
        #: and nowhere else: the `except` below reports a registry it could not READ, which is a different
        #: fact from a verb that legitimately has none (`root-init`, before its root exists).
        return []
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
