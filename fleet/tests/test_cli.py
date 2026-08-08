"""The verb surface — one flag spec per verb, and the cadence trigger every verb pulls.

Fourteen cases, each named for the defect it encodes. Four carry most of the weight and each of those
four is written as a property of the SPEC rather than as a per-verb call, because the defects they close
were all "the same bug one line away from the one that was fixed":

* `test_every_flag_passed_last_with_no_value_exits_2_under_timeout` is **generated from
  `Flag.takes_value`** and wrapped in the real `timeout(1)` binary. `OI-8`: a trailing flag made the tool
  spin forever (`shift 2` shifts nothing and returns 1), and the pre-existing `--seed-file` had the
  identical defect one line away. A per-flag hand-written case would have covered the one that was fixed.
* `test_dry_run_produces_a_zero_delta` runs **per mutating verb** and diffs the filesystem *with directory
  mtimes*, the record store and the pool. The mtimes are load-bearing: the `guards` implementer measured
  that a byte-for-byte claim-then-release still moves `leases/`'s mtime, so a `--dry-run` that claims and
  tidies up after itself is caught by the mtime and never by the net content.
* `test_every_verb_evaluates_cadence_staleness_and_prints_it_to_stderr` runs over **all twenty verbs**.
  Cadence as pure state means the alarm fires only if somebody runs the very verb they had stopped
  running; the observed failure was 19 hours of silence from a stalled actor. Both halves are asserted —
  on stderr (`M-86`) and *not* on stdout, with stdout still parsing to its declared column count
  (`M-87`).
* `test_verify_executes_every_runbook_command_in_a_sandbox` asserts against the **runner's own record of
  what it was asked to run**, not against a parse. Three of F-14's four instances were destructive or
  false-green, including a restore step that would have reverted three commits of shipped work.

Nothing here starts a process, a tmux, a repository or a `claude`: the whole fleet is described through
the injected `Probes`, an injected git and an injected command runner, and every assertion parses what
`cli` actually wrote to the streams it was handed (`OBS-62` — never a model of the output).
"""
import ast
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from fleet import (EXIT_ATTENTION, EXIT_BAD_INPUT, EXIT_CODES, EXIT_NO_CAPACITY, EXIT_OK,
                   EXIT_REFUSED)
from fleet import cli
from fleet.harvest import NO_ISSUES_FILED, REGISTER_NAME, UNREADABLE, VACUOUS, Harvest
from fleet.identity import InstantName
from fleet.layout import validate as layout_validate
from fleet.pool import Pool
from fleet.release import CANDIDATE, RELEASED, Releases, Version
from fleet.release_verify import GATE_ROSTER, GREEN, write_verdict
from fleet.review import Finding, Review
from fleet import origin as origin_mod
from fleet.origin import Origin
from fleet.review import Review
from fleet.roadmap import Milestone, Roadmap
from fleet.session import LiveSession, Probes, SessionLayer
from fleet.store import Declarations, Record, Store
from fleet.workspace import Workspace

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

#: The frozen clock. Every stamp the fixture writes and every stamp `cli` reads comes from here, so two
#: runs of one fixture are comparable byte-for-byte (`NFR2-3`).
NOW = "2026-07-30T12:00:00Z"
#: Well outside any cadence window, so the registered source is overdue for every verb.
LONG_AGO = "2026-07-29T00:00:00Z"

OURS = "00000000-07300312-inflight-append-fleetInfraRebuild"
#: A base with no records at all, so `dispatch` is genuinely ADMISSIBLE in the fixture. If the WIP cap
#: refused first, a `--dry-run` that claims a lease would never reach the claim and `M-84` would be
#: unkillable — the fixture has to let the destructive path fire.
FRESH_BASE = "00000000-07300400-inflight-append-freshEffort"
#: An 8-digit base with no active work. `SI-29`: this row used `FRESH_BASE`, a FULL instant name, and
#: `--base` takes the 8-digit base alone — so a real (non-dry-run) dispatch over this row died in
#: `InstantName.new` at exit 2 before touching anything. The argv table's own docstring promises every
#: mutating row is ADMISSIBLE precisely so a mutated `--dry-run` reaches the side effect it must not
#: perform; for the most destructive verb in the package that promise was false, and the zero-delta
#: contract passed because nothing could have mutated either way.
FRESH_BASE_DIGITS = "07300400"
#: SOMEBODY ELSE's effort. `reap` is ownership-safe by default, and `RI-31` is the defect where the guard
#: refused *correctly* and read as a bug purely because it never said whose lease it was — so the fixture
#: needs a lease this base does not own, and the string has to be recognisable in a refusal.
FOREIGN_BASE = "00000000-07300500-inflight-append-someoneElsesEffort"

#: A pane still offering a way to interrupt: "the agent is mid-turn".
BUSY_PANE = "\n".join(["editing src/fleet/cli.py", "Thinking...", "  esc to interrupt"])
#: Text sitting in the input box that nobody submitted, with nothing working: "queued text".
QUEUED_PANE = "\n".join(["wrote tests/test_cli.py", "", "❯ now run the suite again"])
#: An idle claude pane: the input box renders its placeholder, which is NOT a swallowed submit.
IDLE_PANE = "\n".join(["done", "", '❯ try "fix the failing test"', "  ? for shortcuts"])
#: A plain shell. Nothing here is claude, and sending keys to it is a different mistake.
SHELL_PANE = "\n".join(["ubuntu@box:~$ ls", "src  tests", "ubuntu@box:~$ "])

RUNBOOK_OK = "echo verified"
RUNBOOK_ALSO_OK = "python3 -c 'print(1)'"
#: A recipe that writes outside the sandbox. `FI-3`/F-14: the real instance was a `RUNBOOK §4` restore
#: step that would have reverted three commits of shipped work, so this one is REFUSED BEFORE it runs —
#: you cannot find out safely by trying.
RUNBOOK_OUTWARD = "rm -rf /home/ubuntu/davis_root/operations/tasks"

RUNBOOK = (
    "# RUNBOOK — fixture\n\n"
    "## Recipes\n"
    "```bash\n"
    f"{RUNBOOK_OK}\n"
    f"{RUNBOOK_ALSO_OK}\n"
    f"{RUNBOOK_OUTWARD}\n"
    "```\n"
)

#: A declaration-shaped line in prose with no declaration behind it. DA-6 drop 3: the shipped profiles
#: still *instruct* the worker to write this into `HANDOFF.md`, and `AC-9` only ever asserted the line has
#: no effect — never that nobody is TOLD to write it.
PROSE_PHASE_LINE = "Phase: AWAITING-CI"
PROSE_HANDOFF = f"# HANDOFF\n\n## Current state\n{PROSE_PHASE_LINE}\n\nstill working.\n"


#: The release area the eight release verbs' argv rows are driven against: one RELEASED version, one
#: CANDIDATE with gate evidence, and the version a cut would add. Named, because the fixture's tags, its
#: seeded directories and the argv rows all have to agree — and `0.2.0` over `0.1.1` is a MINOR bump, so
#: the promote row deliberately targets the patch bump, which gate evidence is allowed to carry.
DEPLOYED_RELEASE = "0.1.0"
SEEDED_CANDIDATE = "0.1.1"
SEEDED_TAG = f"fleet/v{SEEDED_CANDIDATE}"
CUT_VERSION = "0.2.0"


def release_fixture(fleet) -> tuple:
    """`(repo, releases)` for the release verbs' rows. Idempotent: `argv_for` is called per test, and in
    the dry-run cases it is called BEFORE the snapshot, so it may create fixture state but must not
    change any of it on a second call.

    The checkout is shaped like the real one — `Repo` refuses a directory with no `.git` at the edge, and
    a cut refuses one with no `fleet/src/fleet/__init__.py`, because that is the file whose `__version__`
    it stamps. No git runs here: `FakeGit` answers every query, which is what keeps this file's promise
    that nothing in it starts a process, a tmux or a repository.
    """
    repo = fleet.tmp / "checkout"
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    (repo / "fleet" / "src" / "fleet").mkdir(parents=True, exist_ok=True)
    stamped = repo / "fleet" / "src" / "fleet" / "__init__.py"
    if not stamped.is_file():
        stamped.write_text('__version__ = "0.0.1"\n')
    releases = Releases(fleet.tmp / "releases")
    if not releases.versions():
        for name, state in ((DEPLOYED_RELEASE, RELEASED), (SEEDED_CANDIDATE, CANDIDATE)):
            version = Version.parse(name)
            (releases.dir_for(version) / ".release").mkdir(parents=True)
            releases.write_manifest(version, {"version": name, "cut_at": NOW})
            releases.set_state(version, state)
            write_verdict(releases.dir_for(version) / ".release",
                          [("hermetic", GREEN, "e", "n"), ("it", GREEN, "e", "n")], GATE_ROSTER)
        # …so `release-rollback` with no `--to` has somewhere to return to. Without it that row refuses
        # before touching anything and its zero-delta case asserts nothing.
        releases.append_history(action="DEPLOY", version=SEEDED_CANDIDATE,
                                from_version=DEPLOYED_RELEASE, actor="fixture", host="fixture",
                                ts=NOW, reason="seeded so the rollback row has a target")
    return repo, releases.root


def snapshot(root: pathlib.Path) -> dict:
    """Every path under `root` with its kind, mtime and size.

    Directory mtimes are deliberately included. A `--dry-run` that claims a lease and gives it back
    leaves the tree byte-identical — the `guards` implementer measured exactly that — so `leases/`'s
    mtime is the only witness of the transient claim, and net content alone would let `M-84` through.
    """
    out = {}
    for path in sorted(root.rglob("*")):
        stat = path.stat()
        out[str(path)] = (path.is_dir(), stat.st_mtime_ns, stat.st_size if path.is_file() else 0)
    return out


class FakeRunner:
    """The command runner `verify` and `selftest` are handed. It RECORDS what it was asked to run.

    This is the anchor for `M-90`: a `verify` that parses recipes without running them leaves this list
    empty, and no amount of well-formed report prose can fake an entry in it.
    """

    def __init__(self, rc: int = 0):
        self.calls = []
        self.rc = rc

    def __call__(self, command, cwd=None, env=None):
        self.calls.append((str(command), str(cwd) if cwd is not None else None))
        return (self.rc, f"ran {command}\n", "")

    def commands(self) -> list:
        return [command for command, _ in self.calls]


class FakeGit:
    """`(args, cwd) -> (rc, stdout)`; `selftest` stamps the tree state through this and nothing else.

    `tags` and `archive` are answered for the release verbs. A cut asks whether its own tag exists (it
    must not) and whether its predecessor's does (it must), so one blanket "" would refuse every cut for
    a missing predecessor and never reach the destructive path a `--dry-run` row has to withhold.
    """

    def __init__(self, dirty=(), tags=()):
        self.dirty = list(dirty)
        self.tags = set(tags)
        self.calls = []

    def __call__(self, args, cwd=None):
        args = list(args)
        self.calls.append(tuple(args))
        if args[:2] == ["rev-parse", "HEAD"]:
            return 0, "0123456789abcdef0123456789abcdef01234567\n"
        if args[0] == "status":
            return 0, "".join(f" M {path}\n" for path in self.dirty)
        if args[:2] == ["tag", "-l"]:
            return 0, "".join(f"{name}\n" for name in sorted(self.tags) if name in args[2:])
        if args[0] == "archive":
            # This fake DESCRIBES a repository; it cannot produce a tar, and it says so the way git says
            # it — non-zero with a message. `Repo.export` then raises its own BadInput naming the tag, so
            # a real cut over the argv row stops at exit 2 with a sentence instead of dying on a missing
            # file. Everything before the export really runs, which is what makes the `--dry-run` row's
            # zero delta a withheld mutation rather than a refusal that arrived first.
            return 128, "this fixture describes a repository without being one; it has no object database"
        return 0, ""


class Fleet:
    """A synthetic fleet, built entirely through injected probes, that `cli` can be pointed at."""

    def __init__(self, slots: int = 4):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-cli-"))
        self.home = self.tmp / "fleethome"
        self.instants = self.tmp / "instants"
        self.instants.mkdir()
        self.slots_dir = self.tmp / "slots"
        self.slots_dir.mkdir()
        self.profiles_dir = self.tmp / "profiles"
        self.profiles_dir.mkdir()

        self.procs, self.panes, self.tmux_live, self.holders = [], {}, set(), {}
        self.started, self.killed = [], []
        #: `FI-7`. The PROBE FAILING is a distinct state from the probe finding nothing, and the real
        #: probes cannot tell them apart — `list_processes` returns `[]` when pgrep exits non-zero and
        #: `capture_pane` returns `""` when tmux does. This switch reproduces the first half; an empty
        #: string in `self.panes` reproduces the second.
        self.live_sessions_fail = False
        #: `FI-7`: a FAILED capture is `None`; a genuinely EMPTY pane is `""`. The fixture has to be able
        #: to express both, or a case cannot tell which one it is testing — which is the defect itself.
        self.capture_fails = set()
        probes = Probes(
            list_processes=lambda: [] if self.live_sessions_fail else list(self.procs),
            capture_pane=lambda name: None if name in self.capture_fails else self.panes.get(name, ""),
            has_session=lambda name: name in self.tmux_live,
            start_session=lambda name, cwd, cmd: self.started.append((name, str(cwd), cmd)),
            kill_session=self._kill)
        self.sessions = SessionLayer(probes)
        self.store = Store(self.home)
        self.pool = Pool(self.home,
                         cwd_probe=lambda path: list(self.holders.get(str(path), [])),
                         alive=self.sessions.alive)
        self.harvest = Harvest(self.home, now=lambda: NOW)
        self.runner = FakeRunner()
        #: The predecessor of the version `release-cut`'s argv row cuts. See `release_fixture`.
        self.git = FakeGit(tags=[SEEDED_TAG])
        for index in range(slots):
            slot = f"ws{index + 1}"
            (self.slots_dir / slot).mkdir()
            self.pool.enroll(self.slots_dir / slot)
        self._n = 0
        self.paths, self.ids = {}, {}

    # ---- fixture construction ---------------------------------------------------------------------

    def _kill(self, name: str) -> None:
        """Killing a session really ENDS its liveness here.

        Recording the call and leaving the session alive would make "the monitor is disarmed" unfalsifiable:
        `close` is only observable through the join, and a probe that still reports the pane alive after a
        kill describes a fleet in which no session ever ends (`OBS-48`'s shape from the other side).
        """
        self.killed.append(name)
        self.tmux_live.discard(name)
        self.procs = [proc for proc in self.procs if proc.name != name]
        self.panes.pop(name, None)

    def spare(self, name: str = "wsSpare") -> pathlib.Path:
        """A real workspace directory that is NOT enrolled. Enrolment is opt-in, so the un-enrolled
        directory is half of what `enroll` has to be tested against."""
        path = self.slots_dir / name
        path.mkdir(exist_ok=True)
        return path

    def profile(self, kind: str = "worker") -> pathlib.Path:
        path = self.profiles_dir / kind
        path.mkdir(exist_ok=True)
        (path / "profile.json").write_text(json.dumps({"kind": kind}))
        (path / "charter.md").write_text(
            "# {{TITLE}}\n\nRun `fleet declare phase awaiting-ci` when CI is queued.\n")
        (path / "seed.txt").write_text("Read CHARTER.md. Run `fleet declare phase awaiting-ci`.\n")
        return path

    def worker(self, name, *, optype="append", state="inflight", pane=BUSY_PANE, live=True,
               base=OURS, slot=None, launched=True, runbook=RUNBOOK, handoff="Updated: now\n"):
        self._n += 1
        curr = f"0730{self._n:04d}"
        folder = f"00000000-{curr}-{state}-{optype}-{name}"
        path = self.instants / folder
        path.mkdir()
        (path / "HANDOFF.md").write_text(handoff)
        (path / "RUNBOOK.md").write_text(runbook)
        todo_id, tmux = f"{name}-{curr}", f"dt-{name}"
        self.store.write(Record(
            todo_id=todo_id, child_instant=str(path), base_instant=base, slot=slot or "", tmux=tmux,
            profile=str(self.profile()), golden=str(self.slots_dir), lineage_base="", title=name,
            dispatched_at=NOW, launched_at=NOW if launched else None))
        if slot:
            self.pool.claim(todo_id=todo_id, tmux=tmux, base_instant=base,
                            child_instant=str(path), slot=slot)
        if live:
            self.procs.append(LiveSession(pid=1000 + self._n, cwd=path, name=tmux))
            self.panes[tmux] = pane
            self.tmux_live.add(tmux)
        self.paths[name] = path
        self.ids[name] = todo_id
        return path

    def orphan(self, name="orphanWork") -> pathlib.Path:
        """A conforming instant with NO record — the thing `resume` adopts (FD-9)."""
        self._n += 1
        path = self.instants / f"00000000-0730{self._n:04d}-inflight-append-{name}"
        path.mkdir()
        (path / "HANDOFF.md").write_text("Updated: now\n")
        (path / "RUNBOOK.md").write_text(RUNBOOK)
        self.paths[name] = path
        return path

    def reviewed(self, path: pathlib.Path, verdict: str = "READY") -> None:
        Review(path, now=lambda: NOW).add_round(
            "all", verdict,
            [Finding(id="F-1", severity="Minor", status="applied", location="src/fleet/cli.py",
                     finding="usage is derived", action="none")])

    def with_roadmap(self, path: pathlib.Path) -> Roadmap:
        roadmap = Roadmap(path)
        roadmap.add(Milestone(id="M1", title="land the cli", status="blocked", deps=[],
                              evidence=[], owner="the worker"))
        roadmap.propose(path, "M1", "running", ["evidence/02-acceptance/verify-acs.sh"])
        return roadmap

    def register_stale_source(self) -> None:
        """A watched source whose `last_run` is a day old, so cadence has something to say to EVERY verb."""
        base_dir = self.instants / OURS
        base_dir.mkdir(exist_ok=True)
        register = base_dir / "ISSUES.md"
        register.write_text("## FI-1 the checker's own words tripped the checker\n")
        self.harvest.register(str(base_dir), str(register))
        data = json.loads(self.harvest.path.read_text())
        for entry in data["sources"]:
            entry["registered_at"] = LONG_AGO
            entry["last_run"] = LONG_AGO
        self.harvest.path.write_text(json.dumps(data, indent=2))

    # ---- driving the cli --------------------------------------------------------------------------

    def context(self):
        """The `context` hook `main` accepts, wired to this fixture's fakes and its frozen clock."""

        def build(parsed, out, err):
            return cli.Ctx(home=self.home, instants_dir=self.instants, store=self.store,
                           pool=self.pool, sessions=self.sessions, harvest=self.harvest,
                           out=out, err=err, dry_run=parsed.on("dry-run"),
                           porcelain=parsed.on("porcelain"), now=lambda: NOW,
                           git=self.git, runner=self.runner, live_work=True)

        return build

    def run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(list(argv), stdout=out, stderr=err, context=self.context())
        return code, out.getvalue(), err.getvalue()

    # ---- the three halves of a delta --------------------------------------------------------------

    def record_state(self) -> dict:
        records = self.home / "records"
        if not records.is_dir():
            return {}
        return {p.name: p.read_text() for p in sorted(records.glob("*.json"))}

    def pool_state(self) -> dict:
        return {slot: (lambda held: held.to_json() if held else None)(self.pool.lease(slot))
                for slot in self.pool.slots()}


class CliCase(unittest.TestCase):
    """Base: one fixture per test, torn down, plus the per-verb argv table derived from it."""

    def setUp(self):
        self.fleets = []

    def tearDown(self):
        for fleet in self.fleets:
            shutil.rmtree(fleet.tmp, ignore_errors=True)

    def fleet(self, **kwargs) -> Fleet:
        made = Fleet(**kwargs)
        self.fleets.append(made)
        return made

    def loaded(self) -> Fleet:
        """One fixture rich enough that EVERY verb on the surface has a valid invocation.

        `doomed` and `closable` are their OWN instants rather than another use of `readyWorker`: `abort`
        and `close` are terminal transactions, and a matrix that drives them over the instant the other
        cells read would be testing a cascade instead of a verb.
        """
        fleet = self.fleet(slots=8)
        fleet.register_stale_source()
        fleet.worker("solo", slot="ws1")
        ready = fleet.worker("readyWorker", slot="ws2")
        fleet.reviewed(ready)
        fleet.with_roadmap(ready)
        harvestable = fleet.worker("harvestable", state="complete", slot="ws3", live=False)
        fleet.reviewed(harvestable)
        fleet.worker("doomed", slot="ws5")
        fleet.worker("closable", slot="ws6", pane=IDLE_PANE)
        fleet.orphan()
        fleet.profile("worker")
        fleet.spare()
        return fleet

    def argv_for(self, fleet: Fleet) -> dict:
        """A valid argv per verb, over `fleet`. Every mutating verb's row is ADMISSIBLE, so a mutated
        `--dry-run` genuinely reaches the side effect it must not perform."""
        ready = str(fleet.paths["readyWorker"])
        orphan = str(fleet.paths["orphanWork"])
        profile = str(fleet.profile("worker"))
        repo, releases = release_fixture(fleet)
        return {
            "init": ["--name", "freshOne", "--base", "00000000"],
            "dispatch": ["--profile", profile, "--title", "a fresh worker",
                         "--base", FRESH_BASE_DIGITS, "--optype", "append"],
            "resume": ["--instant", orphan, "--slot", "ws4", "--tmux", "dt-orphanWork"],
            "declare": ["--instant", ready, "--phase", "AWAITING-CI"],
            "park": ["--instant", ready, "--question", "which baseline is the ruler?"],
            "unpark": ["--instant", ready],
            #: A fresh id: `add` refuses a duplicate, and `loaded()` pre-seeds `M1`. No `--dep`, so the row
            #: stays admissible however the fixture's roadmap changes.
            "milestone": ["--instant", ready, "--id", "M-matrix", "--title", "added by the verb matrix"],
            "propose": ["--instant", ready, "--milestone", "M1", "--status", "done",
                        "--evidence", "evidence/02-acceptance/verify-acs.sh"],
            "apply": ["--instant", ready, "--milestone", "M1"],
            "review": ["--instant", ready, "--scope", "all", "--verdict", "READY"],
            "complete": ["--instant", ready],
            "abort": ["--instant", str(fleet.paths["doomed"]),
                      "--reason", "the baseline moved under it and the work is unstackable"],
            "close": ["--id", fleet.ids["closable"]],
            "harvest": ["--id", fleet.ids["harvestable"]],
            #: A path that does NOT exist: `clone` refuses an existing target by design.
            "clone": ["--slot", str(fleet.tmp / "cloned-slot")],
            "enroll": ["--slot", str(fleet.spare())],
            "unenroll": ["--slot", "ws8"],
            "reap": ["--base", OURS],
            "set-golden": ["--path", str(fleet.slots_dir)],
            "board": [],
            "status": ["--id", fleet.ids["solo"]],
            "leases": [],
            #: `SI-32`. A subject with no recorded lineage base — the verb must answer "nothing to check"
            #: rather than fail, because that is the state of most dispatches.
            "brief": ["--instant", ready],
            "base-check": ["--id", fleet.ids["solo"]],
            "roadmap": ["--instant", ready],
            "lint": ["--instant", ready],
            "verify": ["--instant", ready],
            "reconcile": [],
            "pane-guard": ["--pane", "dt-solo"],
            #: No flags: the interesting population is "every live worker", and `--id` only narrows it.
            #: An empty row also drives the empty-population branch, which must report that it examined
            #: NOTHING rather than reporting clean.
            "seed-check": [],
            "compaction-status": [],
            "selftest": [],
            #: `--repo` and `--releases` are on every row that needs them, and that is the point rather
            #: than a convenience: these rows are driven for REAL by the matrices below, and a release
            #: verb that inferred either from the working directory would tag this checkout.
            "release-cut": ["--version", CUT_VERSION, "--repo", str(repo), "--releases", str(releases)],
            "release-verify": ["--version", SEEDED_CANDIDATE, "--releases", str(releases)],
            "release-promote": ["--version", SEEDED_CANDIDATE, "--releases", str(releases)],
            "release-deploy": ["--version", DEPLOYED_RELEASE, "--releases", str(releases)],
            "release-rollback": ["--reason", "the matrix drives this row for real",
                                 "--releases", str(releases)],
            "release-status": ["--releases", str(releases)],
            "release-list": ["--releases", str(releases)],
            "release-history": ["--releases", str(releases)],
        }



class TestTheFlagSpec(CliCase):
    """The spec is the single copy. Usage, parsing and `--dry-run` are all read off it."""

    def test_usage_is_derived_from_the_flag_spec(self):
        # `W2-20`: `--profile` was MANDATORY and absent from usage; that line printed source code twice,
        # had ZERO assertions until its third fix, and this was its fourth issue. So the assertion is
        # over the whole product of verbs and flags, not over a sample.
        text = cli.usage()
        self.assertTrue(cli.VERBS, "no verb is declared: this assertion would be vacuous")
        for name, spec in sorted(cli.VERBS.items()):
            self.assertIn(name, text, f"verb {name} is missing from usage()")
            self.assertTrue(spec.flags, f"verb {name} declares no flags at all")
            for flag in spec.flags:
                self.assertIn(flag.name, text,
                              f"{name}'s declared flag {flag.name} is absent from usage()")
                per_verb = cli.usage(name)
                self.assertIn(flag.name, per_verb,
                              f"{name}'s declared flag {flag.name} is absent from usage({name!r})")
                if flag.required:
                    self.assertRegex(
                        per_verb, re.escape(flag.name) + r"[^\n]*required",
                        f"{name} {flag.name} is required and usage does not say so (W2-20)")

    def test_every_verb_answers_help_with_its_derived_usage_and_exit_0(self):
        """`FI-26`: `<verb> --help` exited **2** for all 27 verbs. The parser was right — it refuses what no
        spec declares — but `--help` was simply absent from `COMMON_FLAGS`, so the one flag every operator
        types first was the one flag that was an error.

        Generated over every verb, and the two halves are asserted together because each alone passes
        vacuously: exit 0 with nothing on stdout is not help, and usage on stdout with exit 2 is what the
        defect already did (to stderr). Verbs with REQUIRED flags are the point of the third assertion —
        asking for help is not a way of supplying them, so `--help` has to be answered before the
        required-flag check or the verbs whose usage is most needed are the ones that refuse.
        """
        fleet = self.loaded()
        self.assertTrue(cli.VERBS, "no verb is declared: this assertion would be vacuous")
        with_required = 0
        for name, spec in sorted(cli.VERBS.items()):
            code, out, err = fleet.run([name, cli.HELP])
            self.assertEqual(code, EXIT_OK, f"{name} {cli.HELP} exited {code}: {err!r}")
            self.assertEqual(out, cli.usage(name) + "\n",
                             f"{name} {cli.HELP} did not print its derived usage to STDOUT")
            for flag in spec.flags:
                self.assertIn(flag.name, out, f"{name} {cli.HELP} omits its flag {flag.name}")
            # `M14`'s other half, which held all along and must keep holding: help is derived from the
            # spec, so no path prints source code.
            self.assertNotRegex(out, r"(?m)^\s*(def |import |class |return |raise )",
                                f"{name} {cli.HELP} printed source code")
            if any(flag.required for flag in spec.flags):
                with_required += 1
        self.assertGreater(with_required, 0,
                           "no verb declares a required flag, so the ordering half of FI-26 is untested")

    def test_no_flag_exists_outside_a_verb_spec(self):
        # A hand-maintained second copy is the class. The strong half is the CROSS-verb probe: a flag
        # that exists on some other verb is exactly the flag a hand-rolled parser leaks.
        fleet = self.loaded()
        argv = self.argv_for(fleet)
        universe = {flag.name for spec in cli.VERBS.values() for flag in spec.flags}
        self.assertGreater(len(universe), 5, "a flag universe this small is not a universe")

        for verb, spec in sorted(cli.VERBS.items()):
            declared = {flag.name for flag in spec.flags}
            for name in sorted(universe - declared) + ["--not-a-flag", "-x", "--profile-file"]:
                code, out, err = fleet.run([verb, *argv[verb], name])
                self.assertEqual(code, EXIT_BAD_INPUT,
                                 f"{verb} accepted the undeclared flag {name}")
                self.assertIn(name, err, f"{verb}'s refusal of {name} does not name it")
            for flag in spec.flags:
                self.assertIn(flag.name, cli.usage(verb))

    def test_no_undeclared_POSITIONAL_survives_either(self):
        # FI-19d: the parser refused an undeclared FLAG and silently swallowed an undeclared POSITIONAL,
        # so `fleet board wat` exited 0. Same family, opposite treatment — and the lenient half is the one
        # that hides a typo'd argument, because a positional is exactly what a mistyped value looks like.
        # Generated over every verb: the leniency was a property of the parser, not of one verb.
        fleet = self.loaded()
        argv = self.argv_for(fleet)
        self.assertTrue(cli.VERBS, "no verb is declared: this assertion would be vacuous")

        for verb in sorted(cli.VERBS):
            for stray in ("wat", "--", "ws1"):
                code, out, err = fleet.run([verb, *argv[verb], stray])
                self.assertEqual(code, EXIT_BAD_INPUT,
                                 f"{verb} accepted the undeclared positional {stray!r}: {out}{err}")
                self.assertIn(stray, err, f"{verb}'s refusal of {stray!r} does not name it")
            # …and the same argv with nothing stray on it is still parseable, or the case above is
            # asserting that the verb is broken rather than that the positional was refused.
            cli.parse(cli.VERBS[verb], argv[verb])

    def test_a_checker_is_DECLARED_a_checker_not_classified_by_a_shared_tuple(self):
        # FI-19c / OBS-44: `CHECKER_VERBS` was derived from `columns == ROW_COLUMNS`, and `roadmap` fell
        # into the set only because `render.ROADMAP_COLUMNS` happens to be tuple-equal to it. A property
        # that holds because two things share a value is not a property — either tuple changing silently
        # re-classifies a verb, and the classification is what §9's population rule is applied to.
        self.assertIn("roadmap", cli.CHECKER_VERBS)
        self.assertTrue(cli.VERBS["roadmap"].checker,
                        "roadmap is in the checker set without declaring that it is one")
        self.assertEqual(cli.CHECKER_VERBS, cli.checker_verbs(), "the declared set is not what is exported")

        handler = lambda ctx, parsed: EXIT_OK                              # noqa: E731
        # A declared checker whose porcelain columns are its OWN tuple: a column-derived classification
        # cannot see this verb at all, which is precisely how `roadmap` was classified by accident.
        faux = cli._verb("fauxChecker", handler, True, "a checker with its own columns", checker=True)
        self.assertIn("fauxChecker", cli.checker_verbs({**cli.VERBS, "fauxChecker": faux}),
                      "the checker set is still derived from the columns, not from the declaration")
        plain = cli._verb("fauxPlain", handler, True, "not a checker")
        self.assertNotIn("fauxPlain", cli.checker_verbs({**cli.VERBS, "fauxPlain": plain}))
        # The declaration still has to be answerable in porcelain: a checker whose schema cannot carry a
        # row's kind and severity cannot print the population row §9 requires of it.
        for verb in cli.CHECKER_VERBS:
            self.assertLessEqual({"kind", "severity", "detail"}, set(cli.PORCELAIN_COLUMNS[verb]),
                                 f"the checker {verb} has no column to report a population row in")

    def test_every_flag_passed_last_with_no_value_exits_2_under_timeout(self):
        # OI-8, Critical. A trailing flag made the tool spin FOREVER — `shift 2` shifts nothing and
        # returns 1 — and the pre-existing `--seed-file` had the identical defect ONE LINE AWAY. So this
        # is generated from `Flag.takes_value` over every verb, runs the real `timeout` binary, and
        # asserts the diagnostic NAMES the flag: "exit 2" alone passes vacuously whenever another
        # required flag is also missing.
        rows = trailing_flag_matrix()
        self.assertGreater(len(rows), 30, "a generated matrix this small is not the property")
        value_flags = [row for row in rows if row["takes_value"]]
        self.assertTrue(value_flags, "no value-taking flag: the OI-8 property would be vacuous")

        for row in rows:
            where = f"{row['verb']} … {row['flag']}"
            self.assertNotEqual(row["rc"], TIMEOUT_RC, f"{where} HUNG: this is OI-8 itself")
            if row["takes_value"]:
                self.assertEqual(row["rc"], EXIT_BAD_INPUT, f"{where} did not exit 2 (rc={row['rc']})")
                self.assertIn(cli.NEEDS_VALUE, row["stderr"],
                              f"{where} exited 2 without saying a value is missing — vacuous")
                self.assertIn(row["flag"], row["stderr"], f"{where} did not name the flag")
            else:
                self.assertNotIn(cli.NEEDS_VALUE, row["stderr"],
                                 f"{where} takes no value and was told it needs one")
                self.assertIn(row["rc"], cli.EXIT_CODES_ALL,
                              f"{where} returned the unregistered code {row['rc']}")

    def test_every_mutating_verb_has_dry_run(self):
        mutating = [name for name, spec in cli.VERBS.items() if not spec.read_only]
        self.assertGreaterEqual(len(mutating), 8, "too few mutating verbs to be the lifecycle")
        for name in sorted(mutating):
            flags = {flag.name for flag in cli.VERBS[name].flags}
            self.assertIn(cli.DRY_RUN, flags, f"the mutating verb {name} has no {cli.DRY_RUN}")
        for name, spec in sorted(cli.VERBS.items()):
            if spec.read_only:
                self.assertNotIn(cli.DRY_RUN, {flag.name for flag in spec.flags},
                                 f"the read-only verb {name} advertises a dry run it cannot need")


class TestDryRun(CliCase):
    """`RI-32`/`OBS-70`: two actors created stray instants in another effort's tree probing a guard, one
    of them AFTER reading and citing the warning against it. A guard you cannot interrogate
    non-destructively gets interrogated destructively."""

    def test_dry_run_produces_a_zero_delta(self):
        mutating = sorted(name for name, spec in cli.VERBS.items() if not spec.read_only)
        self.assertTrue(mutating, "no mutating verb: nothing is being asserted")
        for verb in mutating:
            with self.subTest(verb=verb):
                fleet = self.loaded()
                argv = self.argv_for(fleet)[verb]
                # The probe only bites when the verb would ALLOW: a refused dispatch never reaches the
                # claim, so a full pool would make this vacuous exactly the way it was vacuous before.
                self.assertTrue(fleet.pool.free_slots(),
                                "no free slot: the destructive path cannot fire")

                before_fs = snapshot(fleet.tmp)
                before_records = fleet.record_state()
                before_pool = fleet.pool_state()

                code, out, err = fleet.run([verb, cli.DRY_RUN, *argv])

                self.assertIn(code, cli.EXIT_CODES_ALL, f"{verb} --dry-run returned {code}")
                self.assertTrue(out.strip() or err.strip(),
                                f"{verb} --dry-run said nothing: an uninterrogable guard")
                self.assertEqual(fleet.record_state(), before_records,
                                 f"{verb} --dry-run wrote the record store")
                self.assertEqual(fleet.pool_state(), before_pool,
                                 f"{verb} --dry-run took, moved or freed a lease")
                after_fs = snapshot(fleet.tmp)
                self.assertEqual(sorted(after_fs), sorted(before_fs),
                                 f"{verb} --dry-run created or removed a path")
                # The mtime half. A claim-then-release is byte-identical and still moves `leases/`.
                self.assertEqual(after_fs, before_fs,
                                 f"{verb} --dry-run touched the tree: the guard was triggered, "
                                 "not interrogated")
                self.assertEqual(fleet.started, [], f"{verb} --dry-run started a session")
                self.assertEqual(fleet.killed, [], f"{verb} --dry-run killed a session")


class TestExitCodes(CliCase):
    """`NFR2-8`: a tick that branches on an exit code must be told when a new one appears."""

    def failure_matrix(self, fleet: Fleet) -> list:
        argv = self.argv_for(fleet)
        cells = [(verb, [verb, *argv[verb]]) for verb in sorted(cli.VERBS)]
        for verb, spec in sorted(cli.VERBS.items()):
            required = [flag for flag in spec.flags if flag.required]
            if required:
                cells.append((verb, [verb]))                                # a required flag missing
            cells.append((verb, [verb, "--not-a-flag"]))                    # an undeclared flag
            for flag in spec.flags:
                if flag.takes_value:
                    cells.append((verb, [verb, *argv[verb], flag.name]))    # OI-8's shape
        cells += [
            ("status", ["status", "--id", "nothing-matches-this"]),          # bad input
            ("roadmap", ["roadmap", "--instant", str(fleet.tmp / "nope")]),  # bad input
            ("review", ["review", "--instant", str(fleet.paths["solo"])]),   # undecidable
            ("complete", ["complete", "--instant", str(fleet.paths["solo"])]),  # gate refuses
            ("harvest", ["harvest", "--id", fleet.ids["solo"]]),             # not renamed yet
            ("pane-guard", ["pane-guard", "--pane", "no-such-pane"]),
        ]
        return cells

    def test_every_exit_code_is_in_the_registry(self):
        fleet = self.loaded()
        # The registry itself: `fleet/__init__` stays the base and the only extension is pane-guard's
        # documented contract (FD-10), declared here and nowhere else.
        self.assertEqual(set(EXIT_CODES), {0, 1, 2, 3, 4})
        self.assertTrue(set(EXIT_CODES) < set(cli.EXIT_CODES_ALL))
        self.assertEqual(set(cli.EXIT_CODES_ALL) - set(EXIT_CODES),
                         set(cli.PANE_GUARD_CODES) - set(EXIT_CODES),
                         "cli extends the registry with something other than FD-10's contract")
        self.assertEqual(set(cli.PANE_GUARD_CODES) - set(EXIT_CODES), {10, 11, 12, 13, 14},
                         "the pane-guard extension is not the documented contract")
        #: `14` was added for `FI-7` and is pinned here BY NUMBER on purpose: it is the code that must
        #: stay OUTSIDE the set `coordinating-instants` treats as "the pane can go" (`0`, `12`, `13`).
        #: A future edit that renumbered it into that set would silently restore the defect — a
        #: transient probe failure authorising the teardown of a live mid-turn pane.
        self.assertNotIn(cli.PANE_INDETERMINATE, (cli.PANE_SAFE, cli.PANE_NOT_CLAUDE, cli.PANE_UNKNOWN))

        seen, verbs_hit = set(), set()
        for verb, argv in self.failure_matrix(fleet):
            code, out, err = fleet.run(argv)
            allowed = cli.registered_codes(verb)
            self.assertIn(code, allowed,
                          f"{' '.join(argv)} returned {code}, which {verb} may not return "
                          f"(registered: {sorted(allowed)})")
            seen.add(code)
            verbs_hit.add(verb)
        self.assertEqual(verbs_hit, set(cli.VERBS),
                         "the matrix does not exercise every verb, so M-85 could hide in the rest")

        # The two codes the generic cells never reach. A full pool (3) and a policy refusal (4) are
        # different answers with different remedies, and `OI-3` showed a test cannot tell them apart when
        # both collapse into one non-zero class — so each is produced deliberately and named.
        profile = str(fleet.profile("worker"))
        refused, out, err = fleet.run(["dispatch", "--profile", profile, "--title", "one over the cap",
                                       "--base", OURS])
        self.assertEqual(refused, EXIT_REFUSED,
                         f"a dispatch over the WIP cap is not a policy refusal: {err}")
        for slot in list(fleet.pool.free_slots()):
            fleet.pool.claim(todo_id=f"filler-{slot}", tmux=f"dt-{slot}", base_instant=OURS,
                             child_instant=f"/filler/{slot}", slot=slot)
        self.assertEqual(fleet.pool.free_slots(), [],
                         "the pool is not full, so no-capacity is unreachable and this cell is vacuous")
        full, out, err = fleet.run(["dispatch", "--profile", profile, "--title", "nowhere to put it",
                                    "--base", FRESH_BASE])
        self.assertEqual(full, EXIT_NO_CAPACITY,
                         f"a dispatch into a full pool is not a capacity answer: {err}")
        seen |= {refused, full}

        for code in (EXIT_OK, EXIT_ATTENTION, EXIT_BAD_INPUT, EXIT_NO_CAPACITY, EXIT_REFUSED):
            self.assertIn(code, seen, f"the matrix never produced {code}: it is not a failure matrix")

    def test_unknown_verb_exits_2_with_the_map(self):
        fleet = self.fleet()
        code, out, err = fleet.run(["frobnicate", "--wat"])
        self.assertEqual(code, EXIT_BAD_INPUT)
        self.assertIn("frobnicate", err)
        for name in cli.VERBS:
            self.assertIn(name, err, f"the unknown-verb diagnostic omits {name}")
        code, out, err = fleet.run([])
        self.assertEqual(code, EXIT_BAD_INPUT)
        for name in cli.VERBS:
            self.assertIn(name, err, f"the bare-invocation map omits {name}")


#: Every call site in the PACKAGE whose tail name is one of `cli.FORBIDDEN_CALLS`, and what each one
#: actually is. `FI-27b`: the previous audit walked only bare-name calls defined inside `cli.py`, so it
#: could not observe a single one of the cross-module deletes it nominally forbade — the vacuous-check
#: family. Package-wide, the tail-name vocabulary matches eight sites, and the honest verdict is not "none"
#: but "these, for these reasons".
#:
#: The table is EXACT, not a floor, for the same reason `killers` is: the audit is over the population, so
#: a ninth site anywhere in the package fails here and has to be argued for in writing. Two of the eight
#: are not what the vocabulary thinks they are — `list.remove` and `Harvest.run` share a tail with
#: `os.remove` and `subprocess.run`, which is `OBS-44`'s family (*a marker two things share is not a
#: marker*) — and saying so here is cheaper and more honest than teaching the matcher to guess a receiver's
#: type.
OUTWARD_CALL_SITES = {
    # --- filesystem deletes, all of them inside a tree the caller OWNS ------------------------------
    ("atomic", "atomic_write"): (
        "os.unlink of its OWN uniquely-named tmp, on the failure path only. Removing the litter of a "
        "write that published nothing is the third property of FI-20's contract; not removing it leaves "
        "a partial file for the next reader"),
    ("atomic", "atomic_symlink"): (
        "os.unlink of its OWN uniquely-named staging symlink, on the failure path only — the same "
        "contract as atomic_write one entry above, for the one thing that primitive cannot publish. A "
        "pointer selecting which release is live is a symlink, and os.symlink refuses an existing name, "
        "so the alternatives were unlink-then-symlink (which leaves a window with no `current` at all, on "
        "the path every davis_root shell resolves through — measured at 238160 sightings by a concurrent "
        "reader over 300 flips) or a second publish implementation in a caller, which is FI-20's ninth "
        "copy. Neither the link nor its target is touched on the success path: os.replace renames the "
        "staging link over the old one"),
    ("atomic", "_break"): (
        "rmdir of the package's OWN advisory lock directory, and only after the holder has been shown "
        "dead. Not breaking a dead holder's lock is a permanent hang; the OSError is swallowed because "
        "another writer having broken it first is the same desired end state"),
    ("pool", "release"): (
        "unlink of a lease body and rmdir of the claim directory, both under FLEET_HOME/pool. Releasing "
        "a lease IS deleting its record — the alternative is a lease store that only grows"),
    ("pool", "unenroll"): (
        "unlink of one enrolled-slot record under FLEET_HOME/pool, after the guarded refusal that "
        "protects a slot somebody still holds"),
    ("pool", "_reclaim"): (
        "unlink of STAGING files and rmdir of one claim directory under FLEET_HOME/pool, and only for a "
        "claim whose lease body never landed and which has been bodiless longer than "
        "INTERRUPTED_CLAIM_AGE_S. SI-7: such a claim made the slot permanently unclaimable — free to every "
        "body-reader, taken to every claimant, invisible to reap. The ceiling is narrow on purpose: only "
        "names matching atomic.tmp_name's shape are removed, and ANY other entry makes the whole reclaim "
        "raise Refused naming that entry rather than sweeping it, so a recovery cannot become a data loss. "
        "The rmdir then fails safe, because rmdir cannot empty a directory"),
    ("release", "prune"): (
        "rmtree of a RELEASE DIRECTORY under $FLEET_RELEASES, beyond the 10-release ceiling, chosen by "
        "semver order from `versions()` — which only ever returns directories this package named "
        "`fleet-v<semver>` itself. The DEPLOYED release is skipped however old, because `current` is what "
        "every davis_root shell resolves through and deleting its target breaks the box. Nothing is lost "
        "that matters: the TAG is the durable artifact and a cut can rebuild any export from it, so this "
        "deletes a convenience copy and not a record. Owner-write is restored first because a cut ends in "
        "`chmod -R a-w` and rmtree cannot delete a read-only tree — the same mistake QI-7 left in the "
        "verification worktrees, one directory over"),
    ("roadmap", "_consume"): (
        "list.remove of a dict from a LOCAL list built by `list(data['pending'])` — an in-memory element, "
        "not a path. Nothing is deleted; the list is then written back through atomic_write"),
    # --- the three subprocess seams, enumerated (FI-27a) --------------------------------------------
    ("cli", "_default_runner"): "spawn seam: the command runner every handler is handed, injected in tests",
    ("session", "default_probes"): "spawn seam: pgrep and tmux, injected in tests as `Probes`",
    ("workspace", "default_git"): "spawn seam: git, injected in tests as a `(args, cwd) -> (rc, out)`",
    ("harvest", "report"): (
        "`self.run(src)` is `Harvest.run`, a method of this package that runs a harvest SOURCE. It shares "
        "its tail with subprocess.run and spawns nothing"),
    ("cli", "_do_release_verify"): (
        "`Verify(rel, version, ctx.runner).run(full=…)` is `release_verify.Verify.run`, a method of this "
        "package, sharing its tail with subprocess.run exactly as `harvest.report`'s `self.run` does — "
        "OBS-44's family, a marker two things share. It spawns nothing of its own: `Verify` takes the "
        "command runner as a REQUIRED constructor argument and this handler hands it `ctx.runner`, the "
        "seam the CLI already owns and the suite already injects. That is what lets `release-verify` run "
        "both suites for real while the package's injectable spawn seams stay three"),
}

#: The three entries above that really do spawn a process. Kept separate so the count is derived from the
#: table rather than written twice, and so `session.py`'s corrected docstring can be checked against it
#: (`FI-27a`: the docstring used to claim `default_probes` was the ONLY one, which was false the day it
#: was written).
SPAWN_SEAMS = {("cli", "_default_runner"), ("session", "default_probes"), ("workspace", "default_git")}

#: Sites whose ONLY match on the spawn vocabulary is a tail name: a method of this package called `run`.
#: Enumerated one by one and deliberately NOT derived from `OUTWARD_CALL_SITES` — deriving it would excuse
#: every future site the moment somebody wrote a sentence about it, and the point of the count below is
#: that a fourth real seam cannot be added without being argued for HERE, in the file that counts them.
TAIL_ONLY_RUN = {("harvest", "report"), ("cli", "_do_release_verify")}


def package_functions() -> dict:
    """`{(module, name): FunctionDef}` for every top-level function and method in `fleet`.

    Nested functions are NOT separate entries: they are walked as part of the enclosing definition, so the
    seam a reader would name — `default_probes`, not the six closures inside it — is the unit the audit
    reports. `errors` is included; there is no reason for it to be exempt.
    """
    out = {}
    for path in sorted((SRC / "fleet").glob("*.py")):
        if path.stem == "__init__":
            continue
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.FunctionDef):
                out[(path.stem, node.name)] = node
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef):
                        out[(path.stem, sub.name)] = sub
    return out


def fleet_imports() -> tuple:
    """Per module: `{name: module}` for `from fleet.X import name`, and `{alias: module}` for a module
    imported as a whole. Both forms are used in this package and each is an edge the old audit could not
    follow."""
    named, moduled = {}, {}
    for path in sorted((SRC / "fleet").glob("*.py")):
        if path.stem == "__init__":
            continue
        named[path.stem], moduled[path.stem] = {}, {}
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("fleet"):
                parts = node.module.split(".")
                for alias in node.names:
                    if len(parts) > 1:
                        named[path.stem][alias.asname or alias.name] = parts[1]
                    else:
                        moduled[path.stem][alias.asname or alias.name] = alias.name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("fleet."):
                        moduled[path.stem][alias.asname or alias.name.split(".")[-1]] = \
                            alias.name.split(".")[1]
    return named, moduled


def dotted(node) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


class TestOutwardState(CliCase):
    """Operator-only, permanently. Audited rather than asserted per verb, because the next verb added is
    the one a per-verb list forgets — and audited PACKAGE-WIDE, because the next delete added is in the
    module the old audit could not see into (`FI-27b`).
    """

    def setUp(self):
        super().setUp()
        self.functions = package_functions()
        self.named, self.moduled = fleet_imports()
        self.by_name = {}
        for module, name in self.functions:
            self.by_name.setdefault(name, set()).add((module, name))

    # ---- the call graph, across module boundaries ---------------------------------------------

    def callees(self, site) -> set:
        """Every package function `site` might call. Deliberately an OVER-approximation on method calls:
        `ctx.pool.release(...)` is resolved by the attribute name alone, because a static reader cannot
        know what `ctx.pool` is. An audit may only err towards reaching too much — the failure mode of
        erring the other way is the one being fixed, a closure that reached nothing outside one file.
        """
        module, _ = site
        out = set()
        for node in ast.walk(self.functions[site]):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                if (module, func.id) in self.functions:
                    out.add((module, func.id))
                elif (self.named[module].get(func.id), func.id) in self.functions:
                    out.add((self.named[module][func.id], func.id))
                else:
                    out |= self.by_name.get(func.id, set())
            elif isinstance(func, ast.Attribute):
                receiver = func.value
                target = (self.moduled[module].get(receiver.id)
                          if isinstance(receiver, ast.Name) else None)
                if target is not None and (target, func.attr) in self.functions:
                    out.add((target, func.attr))
                else:
                    out |= self.by_name.get(func.attr, set())
        return out

    def closure(self, site) -> set:
        found, todo = set(), [site]
        while todo:
            current = todo.pop()
            if current in found or current not in self.functions:
                continue
            found.add(current)
            todo.extend(self.callees(current))
        return found

    def forbidden_calls_in(self, site) -> list:
        out = []
        for node in ast.walk(self.functions[site]):
            if isinstance(node, ast.Call):
                call = dotted(node.func)
                if call.rsplit(".", 1)[-1] in cli.FORBIDDEN_CALLS:
                    out.append(call)
        return out

    # ---- the assertions ------------------------------------------------------------------------

    def test_the_audit_reaches_across_module_boundaries_at_all(self):
        """The vacuity check on the audit itself, and the one that would have caught `FI-27b`. The old
        closure followed bare-name calls inside `cli.py` only, so it could not reach `pool.release` — a
        delete it nominally forbade — from any handler. If this fails, every assertion below is describing
        one file and calling it a package.
        """
        handler = cli.VERBS["harvest"].handler.__name__
        reached = self.closure(("cli", handler))
        self.assertIn(("pool", "release"), reached,
                      "the closure from `harvest` cannot see pool.release(), so the audit is blind to "
                      "exactly the cross-module deletes it forbids (FI-27b)")
        modules = {module for module, _ in reached}
        self.assertGreater(len(modules), 1,
                           f"the closure never left cli.py: {sorted(modules)}")

    def test_every_forbidden_call_in_the_package_is_declared_and_justified(self):
        found = {site: calls for site in sorted(self.functions)
                 if (calls := self.forbidden_calls_in(site))}
        undeclared = {site: calls for site, calls in found.items() if site not in OUTWARD_CALL_SITES}
        self.assertEqual(undeclared, {},
                         "a delete, publish, merge or spawn was added to the package and is not in "
                         "OUTWARD_CALL_SITES. Every one of these has to be argued for in writing before "
                         "it is allowed — that argument IS the audit")
        stale = sorted(set(OUTWARD_CALL_SITES) - set(found))
        self.assertEqual(stale, [],
                         f"OUTWARD_CALL_SITES still allows {stale}, which no longer contains such a call: "
                         "an allowance nobody needs is an allowance nobody re-reads")
        for site, reason in OUTWARD_CALL_SITES.items():
            # A reason, not a label. "legitimate" is not an argument; the table is only worth reading if
            # each entry says what the call touches and why that is the caller's to touch.
            self.assertGreaterEqual(len(reason.split()), 10,
                                    f"{site} is allowed with no stated reason: {reason!r}")

    def test_no_verb_reaches_a_forbidden_call_it_was_not_declared_to_reach(self):
        handlers = {}
        for name, spec in cli.VERBS.items():
            handler = getattr(spec.handler, "__name__", "")
            self.assertIn(("cli", handler), self.functions,
                          f"{name}'s handler {handler!r} is not defined in cli.py")
            handlers[name] = handler
        reached_any = set()
        for verb, handler in sorted(handlers.items()):
            reached = self.closure(("cli", handler))
            self.assertIn(("cli", handler), reached)
            reached_any |= reached
            for site in sorted(reached):
                for call in self.forbidden_calls_in(site):
                    self.assertIn(site, OUTWARD_CALL_SITES,
                                  f"{verb} reaches {site[0]}.{site[1]}() which calls {call}: a verb may "
                                  "not delete, publish or merge outward state")
        # Non-vacuity in the other direction: a verb HAS to reach at least one of the declared deletes,
        # or the declarations are describing dead code and the audit proves nothing about the verbs.
        self.assertTrue(reached_any & {("pool", "release"), ("pool", "unenroll")},
                        "no verb reaches the pool's lease deletes, so the allowance is unexercised")

    def test_the_three_spawn_seams_are_three_and_session_py_names_all_of_them(self):
        """`FI-27a`. `session.py`'s docstring claimed `default_probes` was *the only place in the package
        that spawns a subprocess*, which was false on the day it was written: `cli._default_runner` and
        `workspace.default_git` are the other two. A false isolation claim in the module whose job IS
        isolating the environment is worse than no claim, so the count is derived here and the docstring
        is required to name every seam — a fourth seam fails this and cannot be added in silence.
        """
        spawning = {site for site in self.functions
                    if any(call.rsplit(".", 1)[-1] in cli.SPAWN_CALLS
                           for call in self.forbidden_calls_in(site))}
        # `harvest.report` and `cli._do_release_verify` match the vocabulary on a `.run` whose receiver is
        # a class in this package, and spawn nothing; OUTWARD_CALL_SITES argues each one and
        # `TAIL_ONLY_RUN` names them, so SPAWN_SEAMS is what remains.
        self.assertEqual(spawning - TAIL_ONLY_RUN, SPAWN_SEAMS,
                         f"the package's spawn seams are {sorted(spawning)}, not the three that are "
                         "documented and injected")
        import fleet.session as session_module
        doc = session_module.__doc__ or ""
        for _, seam in sorted(SPAWN_SEAMS):
            self.assertIn(seam, doc, f"session.py's docstring does not name the spawn seam {seam!r}")
        # The false claim itself, as TEXT — there is no other way to check a claim. Normalised first,
        # because the original wrapped mid-phrase and carried markdown emphasis, and a checker that only
        # matches one layout is a checker the next reflow defeats. Note the docstring deliberately QUOTES
        # the retracted words in its explanation; the needle is the whole claim, which the short quote
        # cannot contain — the same care `test_structure` takes not to trip over its own prose (FI-1).
        flat = " ".join(doc.replace("*", " ").split())
        self.assertNotIn("is the only place in the package that spawns a subprocess", flat,
                         "session.py claims to hold the ONLY spawn seam again, which is FI-27a verbatim")

    def test_no_module_in_the_package_contains_an_outward_command(self):
        """Also widened. The old grep read `cli.py` alone, so a `git push` in `workspace.py` — the module
        that actually holds a git handle — was outside the check that forbids it."""
        checked = 0
        for path in sorted((SRC / "fleet").glob("*.py")):
            source = path.read_text()
            checked += 1
            for banned in cli.FORBIDDEN_COMMANDS:
                self.assertNotIn(banned, source,
                                 f"{path.name} contains the outward command {banned!r}")
        self.assertGreater(checked, 1, "the grep read one file, which is FI-27b again")

    def test_only_the_three_lifecycle_transactions_and_dispatch_rollback_end_a_session(self):
        """Ending our OWN dispatched session belongs to the three LIFECYCLE TRANSACTIONS — `harvest` (the
        delta landed), `abort` (the work is being abandoned, with a reason) and `close` (the pane is being
        shut, guarded and overridable) — **and to `dispatch`'s own rollback, which is the fourth and is
        different in kind.** FD-5 — *"no code path leaves a session alive with no work"* — is why the set
        is not smaller; *"some of those sessions are people's"* (D-6) is why it is exact rather than a
        floor. A FIFTH caller fails here, which is the property: the audit is over the population, not
        over the instance.

        **Why `_do_dispatch` was admitted, stated rather than assumed, because widening an exact invariant
        is how exact invariants stop being exact.**

        D-6's concern is ending a session that might be SOMEBODY'S. Every other killer acts on a session
        that has existed independently — for minutes or days, possibly with a human attached. `dispatch`'s
        rollback acts only on the session `dispatch` itself created seconds earlier, inside the same call,
        which it is in the middle of undoing: the lease is being given back and the milestone disowned. It
        cannot be anybody's, because nobody has been told it exists.

        The alternative is worse in FD-5's own terms. Leaving it alive is *precisely* "a session alive with
        no work": the record is rolled back, the lease released, the milestone disowned — and a claude keeps
        running on the wrong instant's briefing, which is the one state seed-misdelivery makes dangerous
        (the 2026-08-05 `r1` misdelivery would have made it a SECOND WRITER on a live `roadmap.json`). The
        rule exists to stop a session being destroyed carelessly, not to require that a mis-seeded worker
        be left running.

        The admission is narrow on purpose: `_do_dispatch` may kill only on the FOREIGN verdict, and the
        NOT-DELIVERED verdict — the far commoner one — deliberately does not kill.
        """
        killers = {site for site, node in self.functions.items()
                   if any(isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                          and child.func.attr == "kill" for child in ast.walk(node))}
        expected = {("cli", cli.VERBS[verb].handler.__name__)
                    for verb in ("harvest", "abort", "close", "dispatch")}
        self.assertEqual(killers, expected,
                         f"session.kill() is called from {sorted(killers)}, which is not exactly the "
                         "three lifecycle transactions plus dispatch's own rollback")

    def test_dispatch_kills_only_on_a_foreign_seed_and_never_on_an_unverifiable_one(self):
        """The narrowness of the admission above, asserted rather than promised.

        `NOT-DELIVERED` is what a correct send-keys delivery looks like from inside `dispatch`, because
        `fleet` renders the seed and does not deliver it. If that verdict could kill, every dispatch on the
        box would be torn down to fix one — the shape where a safety check becomes the outage.
        """
        import inspect, textwrap
        source = textwrap.dedent(inspect.getsource(cli._do_dispatch))
        tree = ast.parse(source)

        # STRUCTURAL, over EVERY kill in the function — not a prefix of its source text.
        #
        # The first version of this case did `source.split("ctx.sessions.kill(")[0]` and asserted over the
        # text BEFORE THE FIRST kill. A reviewer found the hole: a SECOND `ctx.sessions.kill(...)` added
        # anywhere later in `_do_dispatch` is invisible to that check, and the package-wide AST test above
        # records only WHICH functions call kill, never how many times. So the admission would have been
        # narrow by convention rather than by construction — exactly the next-editor move this milestone
        # exists to anticipate.
        kills = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "kill"]
        self.assertEqual(len(kills), 1,
                         f"_do_dispatch may end exactly ONE session — its own, on a FOREIGN seed — and "
                         f"{len(kills)} kill call(s) were found. A second one is a new outward action "
                         f"hiding inside an admission granted for one.")

        # ...and that one kill must sit inside a branch testing FOREIGN, never NOT_DELIVERED.
        def guarded(node) -> bool:
            for branch in ast.walk(tree):
                if not isinstance(branch, ast.If):
                    continue
                if any(k is node for k in ast.walk(branch)) and not any(
                        k is node for k in ast.walk(ast.Module(body=[branch.test], type_ignores=[]))):
                    names = {n.attr for n in ast.walk(branch.test) if isinstance(n, ast.Attribute)}
                    if "FOREIGN" in names:
                        return True
            return False

        self.assertTrue(guarded(kills[0]),
                        "the kill must sit inside a branch whose test references seedcheck.FOREIGN")
        killing_branch = source.split("ctx.sessions.kill(")[0]
        self.assertNotIn("seedcheck.NOT_DELIVERED", killing_branch,
                         "NOT-DELIVERED must not be able to reach the kill: it is the ordinary state of a "
                         "send-keys delivery, not a misdelivery")


class TestCadence(CliCase):
    """DA-6 drop 1, Critical. *A cadence that is pure state is a cadence nobody reads*: rev 1 named no
    evaluator, so the alarm fired only if somebody ran the very verb they had stopped running. The
    observed failure was 19 hours of silence from an actor who had stalled. This is `git gc --auto`'s
    shape and needs no daemon."""

    def test_every_verb_evaluates_cadence_staleness_and_prints_it_to_stderr(self):
        # The two halves are asserted in SEPARATE subTests, and the stdout half goes first. That order
        # is load-bearing and was found by mutation: with the stderr assertion first, "cadence not
        # evaluated" (`M-86`) and "cadence evaluated but printed to stdout" (`M-87`) produced the
        # IDENTICAL failure — `'cadence:' not found in ''` — because a stdout-bound line is missing from
        # stderr too, and the stdout-parseable half that `M-87` names never ran. The plan split those two
        # mutations apart precisely because they are different defects; a case that cannot tell them
        # apart is the "one assertion, two bugs" shape this whole build exists to delete.
        for verb in sorted(cli.VERBS):
            fleet = self.loaded()
            argv = self.argv_for(fleet)[verb]
            stale = fleet.harvest.stale(NOW, cli.DEFAULT_MAX_AGE_S, True)
            self.assertTrue(stale, "the fixture has no overdue source: this would be vacuous")

            code, out, err = fleet.run([verb, "--porcelain", *argv])

            with self.subTest(verb=verb, half="stdout-stays-data"):
                # M-87. stdout is machine-parseable data; commentary goes to stderr (NFR2-7).
                self.assertNotIn(cli.CADENCE_PREFIX, out,
                                 f"{verb} printed the cadence alarm to stdout; stdout is data")
                columns = len(cli.PORCELAIN_COLUMNS[verb])
                for line in out.splitlines():
                    self.assertNotEqual(line.strip(), "", f"{verb} emitted a blank stdout line")
                    self.assertEqual(
                        len(line.split("\t")), columns,
                        f"{verb}'s porcelain line {line!r} is not {columns} tab-separated fields")

            with self.subTest(verb=verb, half="alarm-reaches-stderr"):
                # M-86. The alarm fires for THIS verb, whatever the verb was.
                self.assertIn(cli.CADENCE_PREFIX, err,
                              f"{verb} evaluated no cadence: the alarm fires only for whoever "
                              "happens to run the right verb")
                for source in stale:
                    self.assertIn(source.base, err,
                                  f"{verb}'s cadence line does not name the silent source")
                self.assertRegex(err, cli.CADENCE_PREFIX + r"[^\n]*clears when",
                                 f"{verb}'s cadence alarm names no clearing condition (§9)")


class TestDeclare(CliCase):
    """`RCF-9`'s acknowledgement, end to end: a worker declared the phase exactly as its brief worded it,
    a leading `## ` defeated the consumer's regex, and at a cap of 1 that held the effort's only dev slot
    for the length of a CI queue."""

    def test_declare_prints_what_the_consumer_reads(self):
        fleet = self.loaded()
        instant = fleet.paths["readyWorker"]
        asked = "AWAITING-CI"

        code, out, err = fleet.run(["declare", "--porcelain", "--instant", str(instant),
                                    "--phase", asked])
        self.assertEqual(code, EXIT_OK, err)

        consumer = Declarations(instant).phase()
        self.assertIsNotNone(consumer, "nothing was declared")
        printed = dict(line.split("\t", 1) for line in out.splitlines())
        self.assertIn("phase", printed, f"declare printed no phase row: {out!r}")
        self.assertEqual(printed["phase"], consumer,
                         "declare printed something other than what the consumer now reads")
        # The load-bearing half: an ECHO of the argument is a different string from what the consumer
        # reads, because the consumer compares the normalised token and nothing else.
        self.assertNotEqual(printed["phase"], asked,
                            "declare echoed its argument; the acknowledgement is the RE-READ")
        self.assertEqual(consumer, asked.lower())
        # And the join that actually gates on it agrees.
        code, out, err = fleet.run(["status", "--porcelain", "--id", fleet.ids["readyWorker"]])
        self.assertEqual(code, EXIT_OK, err)
        self.assertIn(f"evidence.declared_phase\t{consumer}", out)


class TestLint(CliCase):
    """DA-6 drop 3. Rev 1 scoped the near-miss lint to *"anything still carried in prose"*, which the
    no-prose ruling makes vacuous BY ITS OWN SCOPING — while the failure survives, because the shipped
    profiles still INSTRUCT the worker to write the line into `HANDOFF.md`. `AC-9` asserted no-effect and
    never that anyone is TOLD."""

    def test_a_declaration_shaped_line_in_markdown_with_no_declaration_is_flagged_by_lint(self):
        fleet = self.loaded()
        instant = fleet.worker("proseClaimer", slot="ws4", handoff=PROSE_HANDOFF)
        self.assertIsNone(Declarations(instant).phase(), "the fixture declared it after all")

        code, out, err = fleet.run(["lint", "--porcelain", "--instant", str(instant)])
        self.assertEqual(code, EXIT_ATTENTION, f"a near-miss declaration is not a clean lint: {out}")
        rows = [line.split("\t") for line in out.splitlines()]
        rules = {row[0] for row in rows}
        self.assertIn(cli.NEAR_MISS, rules, f"no near-miss row in {rows}")
        near = [row for row in rows if row[0] == cli.NEAR_MISS]
        self.assertTrue(any(PROSE_PHASE_LINE.lower() in row[3].lower() for row in near),
                        f"the near-miss row does not quote the line it found: {near}")
        self.assertTrue(any("HANDOFF.md" in row[1] for row in near),
                        f"the near-miss row does not name the file: {near}")
        self.assertIn("population", rules, "lint reports no population (§9)")

        # And the other direction, which is what makes the rule a rule rather than a grep: the same
        # line with a real declaration behind it is NOT a finding.
        Declarations(instant).set_phase("awaiting-ci")
        code, out, err = fleet.run(["lint", "--porcelain", "--instant", str(instant)])
        rules = {line.split("\t")[0] for line in out.splitlines()}
        self.assertNotIn(cli.NEAR_MISS, rules,
                         "the line is flagged even with a declaration behind it: that is a grep, "
                         "and a permanently-red lint trains everyone to ignore red")


class TestVerify(CliCase):
    """**F-14 / `FI-3`.** Four instances of a prescribed re-derivation command nobody ever ran; three of
    the four were destructive or false-green, including a `RUNBOOK §4` restore step that WOULD HAVE
    REVERTED THREE COMMITS of shipped work. A recipe that has never been executed is a violation."""

    def test_verify_executes_every_runbook_command_in_a_sandbox(self):
        fleet = self.loaded()
        instant = fleet.paths["readyWorker"]

        code, out, err = fleet.run(["verify", "--porcelain", "--instant", str(instant)])

        recipes = cli.recipes_of(instant / "RUNBOOK.md")
        self.assertEqual([r.command for r in recipes], [RUNBOOK_OK, RUNBOOK_ALSO_OK, RUNBOOK_OUTWARD],
                         "the fixture's recipes are not being read as three commands")

        # M-90's anchor: the RUNNER's own record. A verify that only parses leaves this empty, and no
        # amount of well-formed report prose can put an entry in it.
        ran = fleet.runner.commands()
        self.assertEqual(ran, [RUNBOOK_OK, RUNBOOK_ALSO_OK],
                         "verify did not EXECUTE every safe recipe (a parse is not an execution)")
        for command, cwd in fleet.runner.calls:
            self.assertIsNotNone(cwd, f"{command} ran with no sandbox")
            self.assertNotIn(str(instant), cwd, f"{command} ran inside the instant, not a sandbox")
            self.assertTrue(pathlib.Path(cwd).is_dir(), f"{command}'s sandbox {cwd} does not exist")

        rows = [line.split("\t") for line in out.splitlines()]
        kinds = {row[0] for row in rows}
        self.assertIn(cli.NEVER_EXECUTED, kinds,
                      f"the recipe that never ran is not reported as a violation: {rows}")
        never = [row for row in rows if row[0] == cli.NEVER_EXECUTED]
        self.assertTrue(any(RUNBOOK_OUTWARD in row[3] for row in never),
                        f"the never-executed row does not name the recipe: {never}")
        self.assertIn("population", kinds, "verify reports no population (§9)")
        self.assertEqual(code, EXIT_ATTENTION, "a never-executed recipe is a violation")

        # The safe recipes are reported as executed, by name — the other half of "each runs".
        executed = {row[1] for row in rows if row[0] == cli.EXECUTED}
        self.assertEqual(executed, {RUNBOOK_OK, RUNBOOK_ALSO_OK},
                         f"verify does not report which recipes it ran: {rows}")

    def test_verify_refuses_a_recipe_that_mutates_outside_the_sandbox(self):
        fleet = self.loaded()
        instant = fleet.paths["readyWorker"]
        (instant / "RUNBOOK.md").write_text(
            "# RUNBOOK\n\n```bash\n" + RUNBOOK_OUTWARD + "\n```\n")

        before = snapshot(fleet.tmp)
        code, out, err = fleet.run(["verify", "--porcelain", "--instant", str(instant)])

        self.assertEqual(fleet.runner.commands(), [],
                         "the outward recipe was EXECUTED to find out whether it mutates outwards — "
                         "which is the destructive interrogation this refusal exists to remove")
        rows = [line.split("\t") for line in out.splitlines()]
        kinds = {row[0] for row in rows}
        self.assertIn(cli.OUTSIDE_SANDBOX, kinds, f"the recipe was not refused: {rows}")
        refused = [row for row in rows if row[0] == cli.OUTSIDE_SANDBOX]
        self.assertTrue(any(RUNBOOK_OUTWARD in row[3] for row in refused))
        self.assertTrue(all(row[4].strip() for row in refused),
                        f"the refusal names no clearing condition: {refused}")
        self.assertTrue(all(row[5].strip() for row in refused),
                        f"the refusal names no clearing actor: {refused}")
        self.assertEqual(code, EXIT_ATTENTION)
        self.assertEqual(snapshot(fleet.tmp), before, "verify itself mutated the tree")


class TestPaneGuard(CliCase):
    """FD-10: the external watcher is REQUIRED to call this before any send-keys, and DA-2 enumerated
    SIX send paths — so the guard sits at the choke point and its codes are a contract."""

    def test_pane_guard_returns_the_documented_codes(self):
        fleet = self.loaded()
        fleet.panes["dt-solo"] = IDLE_PANE
        fleet.worker("queued", slot="ws4", pane=QUEUED_PANE)
        fleet.worker("midTurn", pane=BUSY_PANE)
        fleet.tmux_live.add("dt-shell")
        fleet.panes["dt-shell"] = SHELL_PANE

        expected = {
            "dt-solo": cli.PANE_SAFE,
            "dt-queued": cli.PANE_QUEUED_TEXT,
            "dt-midTurn": cli.PANE_MID_TURN,
            "dt-shell": cli.PANE_NOT_CLAUDE,
            "dt-nobody": cli.PANE_UNKNOWN,
        }
        self.assertEqual(sorted(expected.values()), [0, 10, 11, 12, 13],
                         "the documented code set is not the one being asserted")
        for pane, code in sorted(expected.items()):
            got, out, err = fleet.run(["pane-guard", "--porcelain", "--pane", pane])
            self.assertEqual(got, code, f"pane-guard {pane} returned {got}, not {code}: {out}{err}")
            printed = dict(line.split("\t", 1) for line in out.splitlines())
            self.assertEqual(printed.get("code"), str(code),
                             f"pane-guard {pane} does not print its own code: {out!r}")
            self.assertEqual(printed.get("verdict"), cli.PANE_GUARD_CODES[code],
                             f"pane-guard {pane} does not name its verdict: {out!r}")
        self.assertEqual(cli.PANE_GUARD_CODES[cli.PANE_SAFE], "safe")

    def test_a_pane_whose_evidence_could_not_be_READ_is_never_reported_not_claude(self):
        """`FI-7` — the transient `12` that authorises destroying a live pane.

        Measured in the field: one poll in ~118 against a live mid-turn claude returned `12 not-claude`,
        with `11` on the polls either side. That code is safe before a SEND (everything but `0` means
        wait) and unsafe before a CLOSE: `coordinating-instants` states *"`0`, `12` or `13` mean the pane
        can go"*, so a transient `12` authorises closing a pane mid-turn — destroying exactly what
        `close`'s queued-pane refusal exists to protect.

        The mechanism, reproduced deterministically because both probes are injectable:
        `capture_pane` returns `""` when tmux exits non-zero and `list_processes` returns `[]` when pgrep
        does, so **"I looked and it is not claude" and "I could not look" are the same value**. Both
        probes failing in one poll is all it takes, and load is what makes that coincide.

        A guard whose failure mode is "go ahead" is not a guard. Absence of evidence must not be reported
        as evidence of absence — the pane is ALIVE, so something is there; we simply could not see it.
        """
        fleet = self.loaded()
        pane = "dt-solo"
        fleet.panes[pane] = IDLE_PANE
        # The pane is alive by the session probe, and BOTH evidence probes fail: no process attributed,
        # and an empty capture. Exactly the field case.
        fleet.live_sessions_fail = True
        fleet.capture_fails.add(pane)          # tmux did not answer — NOT an empty pane

        code, out, err = fleet.run(["pane-guard", "--porcelain", "--pane", pane])
        self.assertNotEqual(code, cli.PANE_NOT_CLAUDE,
                            "an unreadable pane is reported as NOT-CLAUDE, which authorises teardown")
        self.assertNotEqual(code, cli.PANE_SAFE, "an unreadable pane is reported as safe to send to")
        self.assertEqual(code, cli.PANE_INDETERMINATE,
                         f"expected the indeterminate code; got {code}: {out}{err}")
        printed = dict(line.split("\t", 1) for line in out.splitlines())
        detail = printed.get("detail", "").lower()
        self.assertIn("nothing about it could be read", detail,
                      f"the row does not say the evidence was unreadable: {out!r}")
        self.assertIn("failed observation", detail,
                      "the row does not distinguish a failed observation from a negative one")
        self.assertIn("do not close", detail,
                      "the row does not tell the close-out caller what to do, which is the whole finding")

    def test_a_genuinely_EMPTY_pane_is_still_not_claude(self):
        """The over-reach guard, and §M10 caught its absence within one gate run.

        My first fix tested `not text.strip()`, which cannot tell a FAILED capture from an EMPTY pane —
        the exact conflation `FI-7` is about, reintroduced one layer up. A real shell pane running
        `sleep 900` produces no output and is genuinely not claude; it was reported `14 indeterminate`,
        which blocks a legitimate teardown forever. An empty pane that captured CLEANLY is `12`.
        """
        fleet = self.loaded()
        pane = "dt-emptyshell"
        fleet.tmux_live.add(pane)
        fleet.panes[pane] = ""                 # captured fine; there is simply nothing on screen
        code, out, err = fleet.run(["pane-guard", "--porcelain", "--pane", pane])
        self.assertEqual(code, cli.PANE_NOT_CLAUDE,
                         f"an empty pane that captured cleanly is not reported not-claude: {out}{err}")

    def test_the_indeterminate_code_is_not_one_that_authorises_teardown(self):
        """The contract half. `close` may act on 0/12/13; the new code must be outside that set, or the
        fix relabels the defect instead of removing it."""
        self.assertNotIn(cli.PANE_INDETERMINATE, (cli.PANE_SAFE, cli.PANE_NOT_CLAUDE, cli.PANE_UNKNOWN))
        self.assertIn(cli.PANE_INDETERMINATE, cli.PANE_GUARD_CODES)
        self.assertIn(cli.PANE_INDETERMINATE, cli.registered_codes(cli.PANE_GUARD),
                      "the code is not in the verb's registry, so §M1 will call it unregistered")


class TestTheArgvTable(CliCase):
    """The table is the ONE thing in this file that is not derived from `VERBS`, because a valid
    invocation needs fixture paths. The gap is therefore ASSERTED rather than discovered as a `KeyError`
    inside twenty generated cases: a verb added with no row is a named failure."""

    def test_every_verb_has_a_row_in_the_argv_table(self):
        fleet = self.loaded()
        self.assertEqual(set(self.argv_for(fleet)), set(cli.VERBS),
                         "the argv table and VERBS disagree: a hand-maintained second copy of the verb "
                         "list is the class this whole build exists to delete")


class TestAbort(CliCase):
    """FD-12's sharpest hole. `abort` was in `identity.STATES`, had three cells in `layout.REQUIREMENTS`,
    was in `reconcile.TERMINAL_FOLDER_STATES` and Plan 6 §K8 *requires* an `abort-compact` instant — and
    **no verb could produce an `-abort-` folder.** A state the model knows and the surface cannot reach is
    a state that gets reached by hand, which is how a rename becomes an untracked mutation."""

    def test_abort_renames_inflight_to_abort_and_records_the_reason(self):
        fleet = self.loaded()
        instant = fleet.paths["doomed"]
        reason = "the baseline moved under it; the stack is unfoldable"

        code, out, err = fleet.run(["abort", "--porcelain", "--instant", str(instant),
                                    "--reason", reason])

        self.assertEqual(code, EXIT_OK, err)
        target = instant.parent / instant.name.replace("-inflight-", "-abort-")
        self.assertTrue(target.is_dir(),
                        "no -abort- folder exists: "
                        f"{sorted(p.name for p in fleet.instants.iterdir())}")
        self.assertFalse(instant.exists(), "the -inflight- folder survived the rename")
        self.assertEqual(InstantName.parse(target.name).state, "abort")
        # The reason is STRUCTURED STATE inside the instant, not a sentence in somebody's document.
        body = json.loads((target / ".fleet" / cli.ABORT_FILE).read_text())
        self.assertEqual(body["reason"], reason,
                         f"the reason was not recorded in the instant: {body}")
        printed = dict(line.split("\t", 1) for line in out.splitlines())
        self.assertEqual(printed.get("reason"), reason,
                         f"abort does not report the reason it recorded: {out!r}")
        # The state the matrix always knew about is now REACHABLE, so the checkers that were written for
        # it can finally see one: `layout` has a row for this cell, and `lint` runs over it rather than
        # refusing a folder it cannot classify.
        population = [row.detail for row in layout_validate(target) if row.rule == "population"]
        self.assertTrue(any("(abort, append)" in detail for detail in population),
                        f"the layout matrix did not classify the aborted instant: {population}")
        code, out, err = fleet.run(["lint", "--porcelain", "--instant", str(target)])
        self.assertIn(code, EXIT_CODES, f"lint could not answer for an -abort- instant: {err}")

    def test_abort_refuses_an_empty_reason(self):
        # M-92's killer. An abort with no reason is a deletion with a nicer name (FD-12), and `--reason ""`
        # is the shape `F7` names: exit 2, and a message that does NOT tell the caller to do what they
        # just did.
        for reason in ("", "   "):
            with self.subTest(reason=reason):
                fleet = self.loaded()
                instant = fleet.paths["doomed"]
                before = snapshot(fleet.tmp)

                code, out, err = fleet.run(["abort", "--instant", str(instant), "--reason", reason])

                self.assertEqual(code, EXIT_BAD_INPUT,
                                 f"abort accepted the reason {reason!r} (code {code}): {out}{err}")
                self.assertTrue(instant.is_dir(), "the folder was renamed by a reasonless abort")
                self.assertIsNotNone(fleet.pool.lease("ws5"), "the lease was released anyway")
                self.assertEqual(fleet.killed, [], "the session was closed anyway")
                self.assertEqual(snapshot(fleet.tmp), before,
                                 "a reasonless abort mutated the tree")
                self.assertRegex(err, r"reason[^\n]*(empty|blank|whitespace)",
                                 f"the refusal does not say the REASON was the empty thing: {err!r}")
                self.assertNotIn("were not supplied", err,
                                 "the refusal tells the caller to supply the flag they just supplied "
                                 "(F7: a message that asks for what was already given)")

    def test_abort_releases_the_lease_and_closes_the_session_in_one_transaction(self):
        # M-93's killer. FD-5: no code path leaves a session alive with no work, and no code path leaves a
        # slot leased to work that has stopped. `abort` is a completion transaction with a different name.
        fleet = self.loaded()
        instant, todo = fleet.paths["doomed"], fleet.ids["doomed"]
        self.assertIsNotNone(fleet.pool.lease("ws5"), "the fixture holds no lease: this is vacuous")
        self.assertTrue(fleet.sessions.alive("dt-doomed"), "the fixture has no live session")

        code, out, err = fleet.run(["abort", "--instant", str(instant), "--reason", "unfoldable"])

        self.assertEqual(code, EXIT_OK, err)
        self.assertIsNone(fleet.pool.lease("ws5"),
                          "abort left the lease held: an aborted worker leaks its slot forever (FD-5)")
        self.assertIn("dt-doomed", fleet.killed,
                      "abort left the session alive with no work (FD-5)")
        self.assertIsNotNone(fleet.store.read(todo).closed_at, "the record was not stamped")
        code, board, err = fleet.run(["board", "--porcelain"])
        self.assertEqual(code, EXIT_OK, err)
        self.assertNotIn(todo, board, "an aborted worker is still on the board (FD-4)")

    def test_abort_refuses_an_instant_that_is_not_inflight(self):
        fleet = self.loaded()
        instant = fleet.paths["harvestable"]              # already -complete-
        before = snapshot(fleet.tmp)
        code, out, err = fleet.run(["abort", "--instant", str(instant), "--reason", "too late"])
        self.assertEqual(code, EXIT_BAD_INPUT, f"a completed instant was aborted: {out}")
        self.assertIn("complete", err)
        self.assertEqual(snapshot(fleet.tmp), before, "the refused abort still mutated the tree")


class TestClose(CliCase):
    """FD-10: the external monitor is required to call `pane-guard` before any send-keys, and `close`
    disarms it. Plan 6 §J8/§N5: a busy pane and a pane holding unsubmitted input are both refused, and
    **each refusal names its override** — a refusal with no override is a wall."""

    def test_close_refuses_a_busy_pane_and_a_pane_holding_unsubmitted_input(self):
        fleet = self.loaded()
        fleet.worker("midTurnWorker", pane=BUSY_PANE)
        fleet.worker("queuedWorker", pane=QUEUED_PANE)

        for name in ("midTurnWorker", "queuedWorker"):
            with self.subTest(worker=name):
                code, out, err = fleet.run(["close", "--id", fleet.ids[name]])
                self.assertEqual(code, EXIT_REFUSED,
                                 f"close did not refuse {name} (code {code}): {out}{err}")
                self.assertIn("--force", out + err,
                              f"close's refusal of {name} names no override: {out}{err}")
                self.assertIn("clears when", err, "the refusal names no clearing condition (§9)")
                self.assertIn("clears who", err, "the refusal names no clearing actor (§9)")
                self.assertEqual(fleet.killed, [], "close killed the pane it had just refused")

        code, out, err = fleet.run(["close", "--id", fleet.ids["midTurnWorker"], "--force"])
        self.assertEqual(code, EXIT_OK, err)
        self.assertIn("dt-midTurnWorker", fleet.killed,
                      "the override named by the refusal does not work: the alarm cannot be cleared by "
                      "doing what it asked")

    def test_close_disarms_the_monitor_and_names_the_lease_it_leaves_behind(self):
        fleet = self.loaded()
        todo = fleet.ids["closable"]

        code, out, err = fleet.run(["reconcile", "--porcelain"])
        self.assertEqual(code, EXIT_OK, err)
        self.assertIn(todo, self.armed(out), f"the live worker is not armed: this is vacuous\n{out}")

        code, out, err = fleet.run(["close", "--porcelain", "--id", todo])
        self.assertEqual(code, EXIT_OK, err)
        printed = dict(line.split("\t", 1) for line in out.splitlines())
        self.assertIn("dt-closable", fleet.killed, "close did not close the session")
        self.assertIsNotNone(fleet.store.read(todo).closed_at, "close did not stamp the record")
        # FD-14's shape: what it did not do is NAMED, by slot, rather than left to be discovered.
        self.assertIn("ws6", " ".join(printed.values()),
                      f"close does not name the lease it left held: {out!r}")
        self.assertIsNotNone(fleet.pool.lease("ws6"),
                             "close released a lease: releasing is `harvest`'s or `reap`'s transaction, "
                             "and a verb that quietly does a neighbour's job is how two writers appear")

        code, out, err = fleet.run(["reconcile", "--porcelain"])
        self.assertNotIn(todo, self.armed(out),
                         f"the monitor is still armed on a closed pane: {out}")

    def armed(self, porcelain: str) -> set:
        return {line.split("\t")[1] for line in porcelain.splitlines()
                if line.split("\t")[0] == cli.ARMED}


class TestReconcile(CliCase):
    """FD-10: *`fleet reconcile` computes the arm set, deleting the watchdog's second reconciler.* It is
    read-only, and the arm set is derived from the ONE join rather than from `/proc` a second time."""

    def test_reconcile_renders_the_arm_set_and_mutates_nothing(self):
        fleet = self.loaded()
        before = snapshot(fleet.tmp)

        code, out, err = fleet.run(["reconcile", "--porcelain"])

        self.assertEqual(code, EXIT_OK, err)
        rows = [line.split("\t") for line in out.splitlines()]
        kinds = {row[0] for row in rows}
        self.assertIn(cli.ARMED, kinds, f"nothing is armed in a fleet with live workers: {rows}")
        self.assertIn(cli.POPULATION, kinds, "reconcile reports no population (§9)")
        armed = {row[1] for row in rows if row[0] == cli.ARMED}
        self.assertIn(fleet.ids["solo"], armed, "a live worker is not in the arm set")
        self.assertIn(cli.PANE_GUARD, out,
                      "the arm set does not name the predicate its consumer is REQUIRED to call before a "
                      "send (FD-10): a contract in a prose row is the family this loop removes")
        self.assertEqual(snapshot(fleet.tmp), before, "reconcile mutated the tree")

    def test_a_terminal_instant_still_holding_a_slot_is_reported_at_attention(self):
        """`FI-12` — the row half. The banner half is in `test_render`.

        Measured by the reporter: an instant whose own row said *"the work is over"* held `ws6` for
        twenty-two hours, and `reconcile --porcelain | cut -f3 | sort -u` returned exactly one value,
        `info`. Eleven slots leaked this way once.

        The root cause was wider than the finding: `severity` was the LITERAL `INFO` on every row, so
        this verb could not report attention for anything, ever. The stranded lease is simply the case
        that noticed a column that was a constant.

        `loaded()` already contains the subject — `harvestable` is `complete` and holds `ws3` — which is
        why this can be asserted against the ordinary fixture rather than a special one.
        """
        fleet = self.loaded()
        code, out, err = fleet.run(["reconcile", "--porcelain"])
        self.assertEqual(code, EXIT_OK, err)
        rows = [line.split("\t") for line in out.splitlines()]
        by_subject = {row[1]: row for row in rows}
        stranded = by_subject.get(fleet.ids["harvestable"])
        self.assertIsNotNone(stranded, f"the harvestable worker is not in the arm set: {rows}")
        self.assertEqual(stranded[2], "attention",
                         "a COMPLETE instant still holding a workspace is reported at info")
        self.assertIn("harvest", " ".join(stranded).lower(),
                      "the row does not name the verb that releases the slot")

        # And the column is DERIVED, not flipped to attention wholesale: an ordinary live worker with
        # nothing wrong must still be info, or the fix trades one useless constant for another.
        live = by_subject.get(fleet.ids["solo"])
        self.assertIsNotNone(live)
        self.assertEqual(live[2], "info", "an ordinary live worker is reported at attention")

    def test_a_session_no_record_claims_is_never_armed(self):
        # D-6: *"a tool that can kill a session it does not understand is a tool nobody will leave armed,
        # and some of those sessions are people's."* An unknown is REPORTED, never armed.
        fleet = self.loaded()
        fleet.procs.append(LiveSession(pid=9999, cwd=fleet.tmp, name="someones-own-shell"))
        fleet.tmux_live.add("someones-own-shell")
        fleet.panes["someones-own-shell"] = SHELL_PANE

        code, out, err = fleet.run(["reconcile", "--porcelain"])

        self.assertEqual(code, EXIT_OK, err)
        rows = [line.split("\t") for line in out.splitlines()]
        unknown = [row for row in rows if "someones-own-shell" in row[1]]
        self.assertTrue(unknown, f"the unknown session is not reported at all: {rows}")
        self.assertTrue(all(row[0] == cli.UNARMED for row in unknown),
                        f"a session no record claims was armed: {unknown}")


class TestEnrolment(CliCase):
    """Plan 6 §C1/§C2 and Task 20 were unrunnable: `pool.enroll`/`unenroll` were public API with no verb.
    Enrolment is OPT-IN — a pool never claims a workspace nobody put in it."""

    def test_enroll_adds_an_existing_directory_and_refuses_a_missing_one(self):
        fleet = self.loaded()
        spare = fleet.spare()
        self.assertNotIn(spare.name, fleet.pool.slots(), "the spare is already enrolled: vacuous")

        code, out, err = fleet.run(["enroll", "--porcelain", "--slot", str(spare)])

        self.assertEqual(code, EXIT_OK, err)
        self.assertIn(spare.name, fleet.pool.slots(), f"the slot was not enrolled: {out}")
        code, leases, err = fleet.run(["leases", "--porcelain"])
        self.assertIn(spare.name, leases, "the newly enrolled slot is absent from `leases`")

        missing = fleet.tmp / "nowhere" / "wsGhost"
        code, out, err = fleet.run(["enroll", "--slot", str(missing)])
        self.assertEqual(code, EXIT_BAD_INPUT, f"a missing path was enrolled: {out}")
        self.assertIn(str(missing), err, "the refusal does not name the path it could not find")
        self.assertNotIn("wsGhost", fleet.pool.slots())

    def test_unenroll_refuses_a_leased_slot_without_force(self):
        fleet = self.loaded()
        self.assertIsNotNone(fleet.pool.lease("ws1"), "ws1 is not leased: this is vacuous")

        code, out, err = fleet.run(["unenroll", "--slot", "ws1"])

        self.assertEqual(code, EXIT_REFUSED, f"a leased slot was unenrolled (code {code}): {out}{err}")
        self.assertIn("ws1", fleet.pool.slots(), "the slot left the pool anyway")
        self.assertIn("--force", out + err, "the refusal names no override")
        self.assertIn(fleet.ids["solo"], out + err,
                      "the refusal does not name the work it would strand")

        code, out, err = fleet.run(["unenroll", "--slot", "ws1", "--force"])
        self.assertEqual(code, EXIT_OK, err)
        self.assertNotIn("ws1", fleet.pool.slots(), "the override does not work")

        code, out, err = fleet.run(["unenroll", "--slot", "ws1"])
        self.assertEqual(code, EXIT_BAD_INPUT, "unenrolling a slot that is not enrolled is not an answer")


class TestReap(CliCase):
    """`RI-31`: the ownership guard refused **correctly** and read as a bug purely because it never said
    whose lease it was. *"Not yours to clear" is a state, not a failure* — and a state has to be legible."""

    def foreign_lease(self, fleet: Fleet, slot: str = "ws7") -> None:
        fleet.pool.claim(todo_id="someoneElse-07300500", tmux="dt-someoneElse",
                         base_instant=FOREIGN_BASE, child_instant="/not/ours", slot=slot)

    def test_reap_frees_only_the_stale_lease_its_base_owns(self):
        # M-94's killer. `harvestable` holds ws3 with a dead session and OUR base; the foreign lease on
        # ws7 is equally stale and is NOT ours to clear.
        fleet = self.loaded()
        self.foreign_lease(fleet)
        self.assertIsNotNone(fleet.pool.lease("ws3"))
        self.assertFalse(fleet.sessions.alive("dt-harvestable"), "ws3's lease is not stale: vacuous")

        code, out, err = fleet.run(["reap", "--porcelain", "--base", OURS])

        self.assertIsNone(fleet.pool.lease("ws3"),
                          f"reap did not free the stale lease its own base holds: {out}{err}")
        self.assertIsNotNone(fleet.pool.lease("ws7"),
                             "reap freed a lease belonging to another effort: ownership-safe by default "
                             "means the foreign lease is left alone")
        freed = {row[1] for row in (line.split("\t") for line in out.splitlines())
                 if row[0] == cli.REAPED}
        self.assertEqual(freed, {"ws3"}, f"reap reports the wrong freed set: {out}")

    def test_the_reap_refusal_names_the_owning_base(self):
        # M-95's killer. The refusal is not the defect; the anonymous refusal is.
        fleet = self.loaded()
        self.foreign_lease(fleet)

        code, out, err = fleet.run(["reap", "--porcelain", "--base", OURS])

        self.assertEqual(code, EXIT_REFUSED, f"a foreign stale lease is not a refusal: {out}{err}")
        rows = [line.split("\t") for line in out.splitlines()]
        refusals = [row for row in rows if row[0] == cli.REAP_REFUSED]
        self.assertTrue(refusals, f"nothing reports the lease that was left alone: {rows}")
        for row in refusals:
            self.assertIn(FOREIGN_BASE, "\t".join(row),
                          f"the refusal does not name the owning base (RI-31): {row}")
            self.assertTrue(row[4].strip(), f"the refusal names no clearing condition: {row}")
            self.assertTrue(row[5].strip(), f"the refusal names no clearing actor: {row}")
        self.assertIn("--all", out, "the refusal does not name the override that clears it")
        self.assertIn(cli.POPULATION, {row[0] for row in rows}, "reap reports no population (§9)")

        # The alarm clears by doing what it says.
        code, out, err = fleet.run(["reap", "--porcelain", "--all"])
        self.assertEqual(code, EXIT_OK, f"--all does not clear the refusal: {out}{err}")
        self.assertIsNone(fleet.pool.lease("ws7"), "--all did not free the foreign stale lease")

    def test_reap_leaves_a_live_lease_alone(self):
        fleet = self.loaded()
        code, out, err = fleet.run(["reap", "--porcelain", "--base", OURS])
        self.assertEqual(code, EXIT_OK, err)
        self.assertIsNotNone(fleet.pool.lease("ws1"),
                             "reap freed the slot of a worker whose session is alive (OBS-48)")


class TestSetGolden(CliCase):
    """FD-10 / Plan 6 §C9–C10's prerequisite: `workspace.set_golden` was public API with no verb, so the
    golden could only be declared by writing the file by hand. An undeclared golden is deliberately NOT
    inferred from the last dispatch record — a fallback silently doing load-bearing work (`MI-7`)."""

    def test_set_golden_declares_the_golden_and_re_reads_it_through_the_consumer(self):
        fleet = self.loaded()
        workspace = Workspace(fleet.home, git=fleet.git)
        with self.assertRaises(Exception):
            workspace.golden()                       # undeclared: the state §C9 asserts exits 2

        code, out, err = fleet.run(["set-golden", "--porcelain", "--path", str(fleet.slots_dir)])

        self.assertEqual(code, EXIT_OK, err)
        self.assertEqual(Workspace(fleet.home, git=fleet.git).golden(), fleet.slots_dir,
                         "the golden a fresh consumer reads is not the one that was set")
        printed = dict(line.split("\t", 1) for line in out.splitlines())
        self.assertEqual(printed.get("golden"), str(fleet.slots_dir),
                         f"set-golden prints something other than what the consumer reads: {out!r}")

    def test_set_golden_refuses_a_path_that_is_not_a_directory(self):
        fleet = self.loaded()
        missing = fleet.tmp / "no-such-golden"
        code, out, err = fleet.run(["set-golden", "--path", str(missing)])
        self.assertEqual(code, EXIT_BAD_INPUT, f"a nonexistent golden was declared: {out}")
        self.assertIn(str(missing), err)
        self.assertFalse((fleet.home / "golden").exists(), "the refused golden was written anyway")


class TestInitRegistersItsBase(CliCase):
    """`OBS-68`'s exact structure at a verb §8 never considered: an `init`-ed effort was invisible to
    `harvest` until somebody dispatched from it, because §8 put registration in the *dispatch*
    transaction. `lint`'s unregistered-base rule cannot catch it either — there is no record yet."""

    def test_init_registers_the_effort_it_creates_as_a_watched_source(self):
        # M-96's killer. Invisible because UNLISTED, not because quiet.
        fleet = self.loaded()
        before = {source.base for source in fleet.harvest.sources()}

        code, out, err = fleet.run(["init", "--porcelain", "--name", "brandNewEffort"])

        self.assertEqual(code, EXIT_OK, err)
        created = pathlib.Path(dict(line.split("\t", 1) for line in out.splitlines())["path"])
        self.assertTrue(created.is_dir(), f"init created no instant: {out}")
        after = {source.base for source in fleet.harvest.sources()}
        self.assertEqual(after - before, {str(created)},
                         "init registered no watched source: an init-ed effort is invisible to harvest "
                         "until somebody dispatches from it (OBS-68)")
        source = next(s for s in fleet.harvest.sources() if s.base == str(created))
        self.assertEqual(source.issues_path, str(created / REGISTER_NAME))
        self.assertTrue(pathlib.Path(source.issues_path).is_file(),
                        "the registered register does not exist, so the source cannot be harvested")

        # The property, not the mechanism: the tick can now SEE this effort.
        (created / REGISTER_NAME).write_text("## FI-20 an init-ed effort was invisible to the tick\n")
        code, out, err = fleet.run(["harvest", "--porcelain"])
        self.assertIn(str(created), out,
                      f"the harvest tick does not report the newly created effort: {out}")
        self.assertIn("FI-20", out, "the tick does not read the register it was told to watch")

    def test_init_dry_run_registers_nothing(self):
        fleet = self.loaded()
        before = [source.base for source in fleet.harvest.sources()]
        code, out, err = fleet.run(["init", cli.DRY_RUN, "--name", "notYetBorn"])
        self.assertEqual(code, EXIT_OK, err)
        self.assertEqual([source.base for source in fleet.harvest.sources()], before,
                         "a dry run put a source on the watched list")


class TestSelftestUnderItsOwnReentrancyGuard(CliCase):
    """`FI-25`: two shipped guarantees were mutually exclusive, and both are load-bearing.

    `selftest` runs the suite with `FLEET_SELFTEST=1` because the suite invokes every verb — including
    `selftest` — so without the mark the recursion is unbounded (found by the generated last-with-no-value
    matrix hitting the `timeout` wall, i.e. the hang check caught a different infinite loop than the one it
    was written for). But under the mark `selftest` emitted ONLY a `not-recursing` row, so §9's population
    rule failed, so the suite `selftest` had just started exited 1, so `selftest`'s own `suite` row was
    always a violation and the verb **could never return 0** — 612 tests OK without the guard, FAILED with
    it. Resolved by emitting the population row in the guard branch too: nothing was deleted to make the
    other work.

    Asserted here with the mark set EXPLICITLY, not inherited. That is the second half of the same defect:
    the guard branch was only ever reached when somebody happened to have `FLEET_SELFTEST` in their
    environment, which made the hermetic suite red for them and left this branch untested for everybody
    else.
    """

    def rows_of(self, out) -> dict:
        return {line.split("\t")[0]: line.split("\t")[3] for line in out.splitlines() if line}

    def test_the_guard_branch_refuses_to_recurse_AND_states_its_population(self):
        fleet = self.loaded()
        previous = os.environ.get(cli.SELFTEST_GUARD)
        os.environ[cli.SELFTEST_GUARD] = "1"
        try:
            code, out, err = fleet.run(["selftest", "--porcelain"])
        finally:
            if previous is None:
                os.environ.pop(cli.SELFTEST_GUARD, None)
            else:
                os.environ[cli.SELFTEST_GUARD] = previous
        rows = self.rows_of(out)
        self.assertEqual(code, EXIT_OK, f"refusing to recurse is not a fault: {err!r}")
        self.assertIn("not-recursing", rows, f"the re-entrancy guard did not fire: {sorted(rows)}")
        self.assertIn(cli.POPULATION, rows,
                      f"the guard branch is silent about the population it could not cover: "
                      f"{sorted(rows)} — this is FI-25, and it made selftest permanently non-green")
        self.assertRegex(rows[cli.POPULATION], r"\d",
                         f"the population row states no number: {rows[cli.POPULATION]!r}")
        self.assertEqual(fleet.runner.commands(), [],
                         "the guard branch started a suite run, which is the unbounded recursion")

    def test_without_the_guard_the_suite_is_actually_run(self):
        """The other side, so the branch above cannot be satisfied by never running anything. `FLEET_SELFTEST`
        is REMOVED from the environment here rather than assumed absent — the whole point of FI-25's side
        effect is that it may be inherited."""
        fleet = self.loaded()
        previous = os.environ.pop(cli.SELFTEST_GUARD, None)
        try:
            code, out, err = fleet.run(["selftest", "--porcelain"])
        finally:
            if previous is not None:
                os.environ[cli.SELFTEST_GUARD] = previous
        rows = self.rows_of(out)
        self.assertIn("suite", rows, f"no suite was run and no suite row was emitted: {sorted(rows)}")
        self.assertIn(cli.POPULATION, rows)
        self.assertNotIn("not-recursing", rows)
        self.assertIn(cli.SELFTEST_COMMAND, fleet.runner.commands(),
                      f"the suite command was never handed to the runner: "
                      f"{fleet.runner.commands()!r}")


class TestHarvestSurvivesItsSources(CliCase):
    """`FI-17`/`FI-18`, both found by composing modules and both reproduced HERE, at the surface an
    operator actually runs — no unit test of `harvest`, `layout` or `init` alone shows either one."""

    def kinds(self, out: str) -> set:
        return {line.split("\t")[0] for line in out.splitlines() if line.strip()}

    def test_a_renamed_watched_base_does_not_take_the_whole_tick_down(self):
        # FI-17: `register` keys sources by a rename-tolerant key and stores the path LITERALLY, and every
        # base eventually renames (`complete`/`abort` ARE the rename). `reconcile` resolves through
        # `identity.resolve`; harvest was the one module that never adopted it, so the tick exited 2.
        fleet = self.loaded()
        base_dir = fleet.instants / OURS
        self.assertTrue((base_dir / REGISTER_NAME).is_file(), "the fixture's watched register is missing")

        code, out, err = fleet.run(["init", "--porcelain", "--name", "secondEffort"])
        self.assertEqual(code, EXIT_OK, err)
        second = pathlib.Path(dict(line.split("\t", 1) for line in out.splitlines())["path"])
        (second / REGISTER_NAME).write_text("## FI-21 a second effort, so a dead tick is distinguishable\n")

        renamed = base_dir.with_name(OURS.replace("-inflight-", "-complete-"))
        base_dir.rename(renamed)                       # what a worker's own completion signal does

        code, out, err = fleet.run(["harvest", "--porcelain"])

        self.assertNotEqual(code, EXIT_BAD_INPUT,
                            f"the whole tick died on ONE renamed base: {out}{err}")
        subjects = {line.split("\t")[1] for line in out.splitlines() if line.startswith("source\t")}
        self.assertEqual(subjects, {str(base_dir), str(second)},
                         f"the tick did not cover every watched source: {out}")
        self.assertIn("FI-1", out, "the renamed effort's register was not read through the resolver")
        self.assertIn("FI-21", out, "the healthy source was not harvested")
        self.assertNotIn(UNREADABLE, self.kinds(out), f"a resolvable rename was reported unreadable: {out}")

    def test_one_unreadable_source_leaves_a_row_and_the_rest_of_the_tick_intact(self):
        # The half that matters more, because the next unreadable-source cause will not be a rename.
        fleet = self.loaded()
        code, out, err = fleet.run(["init", "--porcelain", "--name", "doomedEffort"])
        self.assertEqual(code, EXIT_OK, err)
        doomed = pathlib.Path(dict(line.split("\t", 1) for line in out.splitlines())["path"])
        shutil.rmtree(doomed)                          # not a rename: simply gone

        code, out, err = fleet.run(["harvest", "--porcelain"])

        self.assertEqual(code, EXIT_ATTENTION, f"an unreadable source did not degrade to a row: {out}{err}")
        rows = [line.split("\t") for line in out.splitlines()]
        broken = [row for row in rows if row[0] == UNREADABLE]
        self.assertEqual(len(broken), 1, f"expected one {UNREADABLE} row: {out}")
        self.assertEqual(broken[0][1], str(doomed))
        self.assertTrue(broken[0][4] and broken[0][5], "the row is an alarm with no clearing actor (§9)")
        self.assertIn(str(fleet.instants / OURS),
                      {row[1] for row in rows if row[0] == "source"},
                      f"the healthy source was skipped: one bad source took the tick down: {out}")
        self.assertIn("population", self.kinds(out), "the tick reported no population (OBS-49)")

    def test_a_freshly_init_ed_effort_is_not_a_permanently_RED_harvest(self):
        # FI-18, the emergent one: the layout seed writes a header, `init` registers its own base, and the
        # vacuity guard is right — composed, `harvest` was a violation on EVERY tick of a brand-new effort
        # until somebody filed its first issue. A fifth unclearable alarm, and exactly the always-red
        # check OBS-21 deliberately avoided.
        fleet = self.fleet()                           # no other source, so the verdict is about this one
        code, out, err = fleet.run(["init", "--porcelain", "--name", "freshOne"])
        self.assertEqual(code, EXIT_OK, err)
        created = pathlib.Path(dict(line.split("\t", 1) for line in out.splitlines())["path"])
        self.assertTrue((created / REGISTER_NAME).read_text().strip(),
                        "the seeded register is empty, so this case never reaches the seed-shape arm")

        code, first, err = fleet.run(["harvest", "--porcelain"])
        self.assertNotIn(VACUOUS, self.kinds(first),
                         f"a freshly init-ed effort reads as a broken extractor: {first}")
        self.assertIn(NO_ISSUES_FILED, self.kinds(first), f"no row says why the register is quiet: {first}")

        # The second tick is the one that proves it CLEARS: the first carries the memoryless-tick
        # violation, which clears by definition once the state file it wrote exists.
        code, second, err = fleet.run(["harvest", "--porcelain"])
        self.assertEqual(code, EXIT_OK, f"a fresh effort is permanently RED: {second}{err}")
        self.assertIn(NO_ISSUES_FILED, self.kinds(second))
        self.assertNotIn(VACUOUS, self.kinds(second))

        # …and the guard is NOT gone: the same register with issues the extractor cannot parse is still a
        # violation, which is the property FI-18's fix had to preserve (RCF-10).
        register = created / REGISTER_NAME
        register.write_text(register.read_text() + "\n- FI-22 filed as a bullet, which nothing parses\n")
        code, third, err = fleet.run(["harvest", "--porcelain"])
        self.assertEqual(code, EXIT_ATTENTION,
                         f"a populated-but-unparseable register reported a clean tick: {third}{err}")
        self.assertIn(VACUOUS, self.kinds(third), f"the vacuity guard was weakened, not narrowed: {third}")


# --- the generated trailing-flag matrix ------------------------------------------------------------
#
# Computed once and shared, because it spawns one real `timeout`-wrapped process per declared flag. The
# subprocess is not decoration: `OI-8` was an infinite loop, and an in-process assertion about a loop
# that never returns never returns either.

TIMEOUT_RC = 124
_MATRIX = None


def trailing_flag_matrix() -> list:
    global _MATRIX
    if _MATRIX is not None:
        return _MATRIX
    rows = []
    home = pathlib.Path(tempfile.mkdtemp(prefix="fleet-cli-flags-"))
    try:
        for verb, spec in sorted(cli.VERBS.items()):
            for flag in spec.flags:
                argv = ["timeout", "10", sys.executable, "-m", "fleet.cli", verb, flag.name]
                done = subprocess.run(
                    argv, capture_output=True, text=True,
                    env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin",
                         "FLEET_HOME": str(home), "HOME": str(home),
                         # A suite IS running: `selftest` must not start another (SELFTEST_GUARD).
                         cli.SELFTEST_GUARD: "1"})
                rows.append({"verb": verb, "flag": flag.name, "takes_value": flag.takes_value,
                             "rc": done.returncode, "stdout": done.stdout, "stderr": done.stderr})
    finally:
        shutil.rmtree(home, ignore_errors=True)
    _MATRIX = rows
    return rows


if __name__ == "__main__":
    unittest.main()


class TestProposeTakesTwoInstants(CliCase):
    """`SI-23`. `propose` has a PROPOSER and a DESTINATION roadmap, and this handler passed the same value
    for both — so a worker could not propose at all (the milestone was looked up in its own empty roadmap)
    and every proposal was attributed to the roadmap's own instant, losing who asked.

    The library was never wrong: `Roadmap.propose(instant, …)` has always taken the proposer separately and
    `TestSingleWriter` has always asserted `proposal.instant == worker`. Only the wiring was, which is why
    the hermetic suite stayed green while the protocol was unusable — and why the case that caught it is an
    INTEGRATION one (`H2`) that had never been run. This class is the cheap guard: the same defect costs
    0.1s to catch here and a full §H run to catch there.
    """

    def _seed_milestone(self, instant, milestone="m1"):
        from fleet.roadmap import Milestone, Roadmap
        Roadmap(instant).add(Milestone(id=milestone, title="t", status="blocked", deps=[], evidence=[]))

    def test_a_worker_proposes_into_the_coordinators_roadmap_and_is_the_one_attributed(self):
        fleet = self.loaded()
        coordinator, worker = fleet.paths["readyWorker"], fleet.paths["doomed"]
        self._seed_milestone(coordinator)

        code, out, err = fleet.run(["propose", "--porcelain",
                                    "--instant", str(worker),        # the PROPOSER
                                    "--to", str(coordinator),        # the DESTINATION roadmap
                                    "--milestone", "m1", "--status", "done",
                                    "--evidence", "evidence/INDEX.md"])
        self.assertEqual(code, EXIT_OK, err)

        from fleet.roadmap import Roadmap
        #: Filtered to the milestone this test created: `loaded()` pre-seeds a roadmap and an inbox, and a
        #: whole-list assertion would couple this test to that fixture's internals.
        mine = [p for p in Roadmap(coordinator).proposals() if p.milestone == "m1"]
        self.assertEqual([(p.milestone, p.status) for p in mine], [("m1", "done")],
                         "the proposal did not land in the DESTINATION's inbox")
        self.assertEqual(mine[0].instant, str(worker),
                         "the proposal is attributed to the roadmap's own instant, so the coordinator's "
                         "inbox cannot say who asked — that is the whole defect")
        self.assertEqual([p for p in Roadmap(worker).proposals() if p.milestone == "m1"], [],
                         "the proposal was written into the PROPOSER's inbox, where no coordinator reads")

    def test_the_destination_defaults_to_the_proposer_so_the_single_instant_form_is_unchanged(self):
        """A coordinator recording its own milestone passes one instant and no `--to`. That form predates
        the fix and every existing caller uses it, so it must behave exactly as before."""
        fleet = self.loaded()
        instant = fleet.paths["readyWorker"]
        self._seed_milestone(instant, "solo")

        code, _, err = fleet.run(["propose", "--porcelain", "--instant", str(instant),
                                  "--milestone", "solo", "--status", "done",
                                  "--evidence", "evidence/INDEX.md"])
        self.assertEqual(code, EXIT_OK, err)
        from fleet.roadmap import Roadmap
        mine = [p for p in Roadmap(instant).proposals() if p.milestone == "solo"]
        self.assertEqual([p.milestone for p in mine], ["solo"])
        self.assertEqual(mine[0].instant, str(instant),
                         "with no --to the proposer IS the destination, so it attributes to itself")

    def test_the_milestone_is_still_refused_at_the_producer_against_the_DESTINATION(self):
        """The producer-side check is deliberate (`Roadmap.propose`: "an unknown milestone is refused at the
        producer"). It must now validate against the DESTINATION — validating against the proposer is the
        bug, and dropping the check entirely would be the other way to 'fix' it."""
        fleet = self.loaded()
        coordinator, worker = fleet.paths["readyWorker"], fleet.paths["doomed"]
        self._seed_milestone(coordinator, "exists")

        code, _, err = fleet.run(["propose", "--instant", str(worker), "--to", str(coordinator),
                                  "--milestone", "nosuch", "--status", "done",
                                  "--evidence", "evidence/INDEX.md"])
        self.assertEqual(code, EXIT_BAD_INPUT, "an unknown milestone must be refused at the producer")
        self.assertIn("nosuch", err)

    def test_a_bad_destination_is_refused_the_same_way_a_bad_instant_is(self):
        """`--to` resolves through the same rename-tolerant resolver as `--instant` (`OI-16`). The first
        attempt at this fix reconstructed a `Parsed` to reuse that resolver and got the keying wrong
        silently — `values` is keyed `--instant` and holds a list — so `--to` became a no-op that fell back
        to the proposer. A shared resolver is what makes that impossible."""
        fleet = self.loaded()
        worker = fleet.paths["doomed"]
        code, _, err = fleet.run(["propose", "--instant", str(worker), "--to", "not-an-instant-at-all",
                                  "--milestone", "m1", "--status", "done",
                                  "--evidence", "evidence/INDEX.md"])
        self.assertEqual(code, EXIT_BAD_INPUT)
        self.assertIn("not an instant on disk", err)


class TestMilestoneHasAVerb(CliCase):
    """`SI-26`. `SD-5` removed reassignment and made a milestone the thing that carries an item across an
    effort boundary. `Roadmap.add` was already correct, locked and tested — and had **no verb**, so the
    replacement was unreachable from a command line in the same commit that made it load-bearing.

    That is the third instance of one shape: `SI-19` (`base-check` has no verb), `SI-24` (`reassign` has no
    verb), and now the thing `SI-24`'s deletion pointed at. `run-H.sh` even names it in passing — its seed
    helper is commented *"a library driver; §C's precedent for verbs that do not exist."* A register cannot
    tell a working feature from a correct dead one, so the guard is a test that USES the command line.
    """

    def test_a_milestone_can_be_created_from_the_command_line(self):
        fleet = self.loaded()
        ready = str(fleet.paths["readyWorker"])

        code, out, err = fleet.run(["milestone", "--instant", ready, "--id", "carried",
                                    "--title", "an item that outlived its effort"])

        self.assertEqual(0, code, err)
        after = {m.id for m in Roadmap(fleet.paths["readyWorker"]).milestones()}
        self.assertIn("carried", after,
                      "the verb reported success and the roadmap does not hold the milestone")

    def test_a_dep_that_does_not_exist_is_refused_at_the_point_the_name_is_written(self):
        """`FI-7`'s failure was a dependency naming something that existed nowhere. A typo'd dep is not an
        error later — it is a milestone that is permanently not-ready, reported as blocked-on-a-thing-nobody-
        can-find, which reads as work in progress rather than as a mistake."""
        fleet = self.loaded()
        ready = str(fleet.paths["readyWorker"])

        code, out, err = fleet.run(["milestone", "--instant", ready, "--id", "typo",
                                    "--title", "depends on a ghost", "--dep", "M1", "--dep", "M-nope"])

        self.assertEqual(2, code, "an unresolvable dep must be refused, not stored")
        self.assertIn("M-nope", err, "the refusal must name WHICH dep could not be found")
        self.assertIn("M1", err, "and it must list what IS available, or the caller cannot self-correct")
        self.assertNotIn("typo", {m.id for m in Roadmap(fleet.paths["readyWorker"]).milestones()},
                         "the milestone was stored despite the refusal")

    def test_readiness_is_reported_from_the_derivation_not_from_the_status_passed_in(self):
        """A milestone added `ready` whose deps have not landed is NOT ready. The verb answers with the
        derived fact, because the alternative is the coordinator finding out at dispatch."""
        fleet = self.loaded()
        ready = str(fleet.paths["readyWorker"])
        roadmap = Roadmap(fleet.paths["readyWorker"])
        base = roadmap.milestone("M1")
        self.assertNotIn(base.status, ("done",),
                         "this test needs an UNLANDED dep to be meaningful; M1 already landed")

        code, out, err = fleet.run(["milestone", "--instant", ready, "--id", "hopeful",
                                    "--title", "claims to be ready", "--status", "ready", "--dep", "M1"])

        self.assertEqual(0, code, err)
        self.assertIn("ready-now", out)
        self.assertRegex(out, r"ready-now\s+no", "it was added `ready` with an unlanded dep and the verb "
                                                 "agreed with the label instead of the deps")
        self.assertNotIn("hopeful", [m.id for m in roadmap.ready()])

    def test_dry_run_reaches_the_write_and_does_not_perform_it(self):
        fleet = self.loaded()
        ready = str(fleet.paths["readyWorker"])
        before = {m.id for m in Roadmap(fleet.paths["readyWorker"]).milestones()}

        code, out, err = fleet.run(["milestone", "--instant", ready, "--id", "phantom",
                                    "--title", "must not land", "--dry-run"])

        self.assertEqual(0, code, err)
        self.assertEqual(before, {m.id for m in Roadmap(fleet.paths["readyWorker"]).milestones()},
                         "--dry-run wrote to the roadmap")

    def test_the_worker_verb_and_the_coordinator_verb_stay_on_opposite_sides(self):
        """`propose` must remain unable to create a milestone. If a worker could name a new id and have it
        appear, the single-writer split that IS this module would be gone — and the failure it guards is on
        record: a dispatch profile once told every worker to update the canonical registry."""
        fleet = self.loaded()
        ready = str(fleet.paths["readyWorker"])

        code, out, err = fleet.run(["propose", "--instant", ready, "--milestone", "invented",
                                    "--status", "done", "--evidence", "evidence/INDEX.md"])

        self.assertEqual(2, code, "propose accepted an unknown milestone id")
        self.assertNotIn("invented", {m.id for m in Roadmap(fleet.paths["readyWorker"]).milestones()})


class TestTheDispatchMilestoneJoin(CliCase):
    """`SI-27`. The project-level roadmap worked and the join to it did not.

    Three facts, measured while designing the coordinator's loop rather than found by any check:
      * `dispatch` recorded no milestone, `Record` had no field for one and `Milestone.owner` was documented
        *"informational only"* — so `board` could show N workers and `roadmap` N milestones with nothing
        connecting them, and a dead worker could not be mapped back to the work to re-raise;
      * `propose` defaulted its destination to the PROPOSER, so a worker that did not name `--to` wrote into
        its own inbox — **coordinator 0 pending, worker 1 pending**, no error; and
      * `harvest` then applied that proposal into the worker's own roadmap and closed the folder, making the
        loss unrecoverable and invisible.

    The alternative was a line in a skill saying *"always pass `--to`"*. These tests exist because that is a
    documented warning where a mechanical fix was available, and it fails precisely when the seed is written
    by someone who has not read the warning.
    """

    def _coordinator_with(self, fleet, milestone_id="M9", status="blocked", deps=()):
        coordinator = fleet.paths["readyWorker"]
        Roadmap(coordinator).add(Milestone(id=milestone_id, title="carried work", status=status,
                                           deps=list(deps), evidence=[]))
        return coordinator

    def _finished(self, fleet, child):
        """Rename inflight -> complete and record a passing review round.

        `harvest`'s review gate refuses an unreviewed or still-inflight worker BEFORE the unreported-work
        guard is consulted, which is the right order and worth stating: the guard is not about a worker that
        failed, it is about one that **finished properly and still never reported**. Reaching it therefore
        costs this setup, and a test that skipped it would have been asserting the review gate instead.
        """
        renamed = child.parent / child.name.replace("-inflight-", "-complete-")
        child.rename(renamed)
        fleet.reviewed(renamed)
        return renamed

    def _dispatch(self, fleet, coordinator, milestone=None, title="joined", **kw):
        #: `--porcelain` because every assertion below reads a NAMED FIELD out of the output. The human form
        #: is padded columns, and parsing those is how an assertion comes to depend on formatting.
        argv = ["dispatch", "--porcelain", "--profile", str(fleet.profile("worker")), "--title", title,
                "--base", "00000000", "--optype", "append"]
        if coordinator is not None:
            argv += ["--from", str(coordinator)]
        if milestone is not None:
            argv += ["--milestone", milestone]
        return fleet.run(argv + list(kw.get("extra", [])))

    # ---- the join is recorded ----------------------------------------------------------------------

    def test_the_record_the_origin_and_the_claim_all_name_the_same_milestone(self):
        fleet = self.loaded()
        coordinator = self._coordinator_with(fleet)

        code, out, err = self._dispatch(fleet, coordinator, milestone="M9")

        self.assertEqual(0, code, err)
        child = [line.split("\t")[1] for line in out.splitlines()
                 if line.startswith("instant\t")][0]
        record = [r for r in fleet.store.all() if r.child_instant == child][0]
        self.assertEqual("M9", record.milestone, "the record does not name the milestone it was for")
        recorded = origin_mod.read(pathlib.Path(child))
        self.assertIsNotNone(recorded, "the child has no origin.json, so its propose will stay local")
        self.assertEqual("M9", recorded.milestone)
        self.assertEqual(str(coordinator), recorded.coordinator)
        self.assertEqual(child, Roadmap(coordinator).milestone("M9").owner,
                         "the milestone does not name the instant executing it")

    def test_the_claim_sets_owner_and_leaves_status_alone(self):
        """`apply` must remain the ONLY function that changes a status. Marking a dispatched milestone
        `running` here would have been convenient and would have given "who moved this milestone" two
        answers; the worker's own first proposal moves it, through the same two-party path as everything
        else."""
        fleet = self.loaded()
        coordinator = self._coordinator_with(fleet, status="blocked")

        code, out, err = self._dispatch(fleet, coordinator, milestone="M9")

        self.assertEqual(0, code, err)
        self.assertEqual("blocked", Roadmap(coordinator).milestone("M9").status,
                         "dispatch changed a milestone's STATUS; only `apply` may do that")

    def test_board_names_the_milestone_as_a_column(self):
        fleet = self.loaded()
        coordinator = self._coordinator_with(fleet)
        self._dispatch(fleet, coordinator, milestone="M9")

        code, out, err = fleet.run(["board", "--porcelain"])

        self.assertEqual(0, code, err)
        self.assertIn("milestone", cli.PORCELAIN_COLUMNS["board"],
                      "the milestone must be a COLUMN, not folded into a prose note")
        column = cli.PORCELAIN_COLUMNS["board"].index("milestone")
        milestones = {line.split("\t")[column] for line in out.splitlines()}
        self.assertIn("M9", milestones, f"board does not name M9 in its milestone column: {out}")

    # ---- the two refusals -------------------------------------------------------------------------

    def test_a_milestone_without_a_roadmap_to_resolve_it_against_is_refused(self):
        """Refused rather than ignored: dropping it would record the join nowhere while the caller believed
        it had been recorded, which is the failure mode this whole issue is about."""
        fleet = self.loaded()
        self._coordinator_with(fleet)

        code, out, err = self._dispatch(fleet, None, milestone="M9")

        self.assertEqual(2, code, "--milestone with no --from was accepted")
        self.assertIn("--from", err, "the refusal must say what to pass")

    def test_dispatch_onto_an_unready_milestone_is_refused_before_anything_is_claimed(self):
        fleet = self.loaded()
        coordinator = fleet.paths["readyWorker"]
        roadmap = Roadmap(coordinator)
        roadmap.add(Milestone(id="dep", title="has not landed", status="blocked", deps=[], evidence=[]))
        roadmap.add(Milestone(id="M9", title="needs dep", status="blocked", deps=["dep"], evidence=[]))
        #: `pool.leases` is the lease DIRECTORY — `mkdir` is the lock, so a held slot is a subdirectory.
        held_before = sorted(d.name for d in fleet.pool.leases.iterdir())

        code, out, err = self._dispatch(fleet, coordinator, milestone="M9")

        self.assertEqual(EXIT_REFUSED, code, f"an unready milestone was dispatched onto: {out} {err}")
        self.assertIn("not ready", err)
        self.assertEqual(held_before, sorted(d.name for d in fleet.pool.leases.iterdir()),
                         "a refused dispatch left a slot claimed; the check must precede the claim")
        self.assertIsNone(Roadmap(coordinator).milestone("M9").owner)

    def test_two_instants_cannot_take_one_milestone(self):
        fleet = self.loaded()
        coordinator = self._coordinator_with(fleet)
        first, out, err = self._dispatch(fleet, coordinator, milestone="M9", title="firstOne")
        self.assertEqual(0, first, err)

        code, out2, err2 = self._dispatch(fleet, coordinator, milestone="M9", title="secondOne",
                                          extra=["--cap", "5"])

        self.assertEqual(EXIT_REFUSED, code, f"two instants were dispatched onto one milestone: {out2}")
        self.assertIn("already claimed", err2)

    # ---- where a proposal goes --------------------------------------------------------------------

    def test_a_dispatched_worker_proposing_with_no_destination_reaches_its_coordinator(self):
        """THE regression test. Measured before the fix: coordinator 0 pending, worker 1 pending."""
        fleet = self.loaded()
        coordinator = self._coordinator_with(fleet)
        code, out, err = self._dispatch(fleet, coordinator, milestone="M9")
        self.assertEqual(0, code, err)
        child = [line.split("\t")[1] for line in out.splitlines() if line.startswith("instant\t")][0]

        code, out, err = fleet.run(["propose", "--instant", child, "--milestone", "M9",
                                    "--status", "done", "--evidence", "evidence/INDEX.md"])

        self.assertEqual(0, code, err)
        #: Filtered to M9: `loaded()` pre-seeds a proposal so `apply`'s own argv row is admissible, and a
        #: bare count would be asserting the fixture.
        mine = [p for p in Roadmap(coordinator).proposals() if p.milestone == "M9"]
        self.assertEqual(1, len(mine),
                         "the coordinator's inbox holds no proposal for M9; the worker's report went "
                         "nowhere it can see")
        self.assertEqual(0, len(Roadmap(pathlib.Path(child)).proposals()),
                         "the proposal stayed in the worker's own inbox, which `harvest` would bury")
        self.assertEqual(child, mine[0].instant, "the coordinator's inbox cannot say who asked")

    def test_an_instant_with_no_coordinator_proposes_locally_and_says_so(self):
        """The legitimate case — a coordinator proposing on its own roadmap — must keep working. What
        changes is that it is now LOUD: a lost report was previously indistinguishable from a delivered one.
        """
        fleet = self.loaded()
        solo = str(fleet.paths["readyWorker"])
        self.assertIsNone(origin_mod.read(fleet.paths["readyWorker"]),
                          "this fixture is supposed to have no coordinator")

        code, out, err = fleet.run(["propose", "--instant", solo, "--milestone", "M1",
                                    "--status", "done", "--evidence", "evidence/INDEX.md"])

        self.assertEqual(0, code, err)
        self.assertIn("destination-chosen", out)
        self.assertIn("LOCAL", out, "a proposal that no coordinator will see must say so")

    # ---- and the loss is refused ------------------------------------------------------------------

    def test_harvest_refuses_to_close_a_worker_whose_report_never_reached_the_coordinator(self):
        fleet = self.loaded()
        coordinator = self._coordinator_with(fleet)
        code, out, err = self._dispatch(fleet, coordinator, milestone="M9")
        self.assertEqual(0, code, err)
        todo = [line.split("\t")[1] for line in out.splitlines() if line.startswith("todo_id\t")][0]
        child = [line.split("\t")[1] for line in out.splitlines() if line.startswith("instant\t")][0]
        self._finished(fleet, pathlib.Path(child))

        code, out, err = fleet.run(["harvest", "--id", todo, "--porcelain"])

        self.assertIn("harvest-refused", out,
                      f"harvest closed a worker whose milestone the coordinator still knows nothing "
                      f"about: {out}")
        self.assertIn("M9", out, "the refusal must name the milestone whose report would be lost")

    def test_harvest_is_not_blocked_once_the_report_has_arrived(self):
        """The guard must fire ONLY on the genuine loss. A pending proposal means the report arrived and is
        merely unapplied — which is what `harvest` itself is about to do."""
        fleet = self.loaded()
        coordinator = self._coordinator_with(fleet)
        code, out, err = self._dispatch(fleet, coordinator, milestone="M9")
        child = [line.split("\t")[1] for line in out.splitlines() if line.startswith("instant\t")][0]
        todo = [line.split("\t")[1] for line in out.splitlines() if line.startswith("todo_id\t")][0]
        fleet.run(["propose", "--instant", child, "--milestone", "M9", "--status", "done",
                   "--evidence", "evidence/INDEX.md"])
        self._finished(fleet, pathlib.Path(child))

        code, out, err = fleet.run(["harvest", "--id", todo, "--porcelain"])

        self.assertNotIn("this instant was dispatched for milestone", out,
                         f"the unreported-work guard fired even though the report had arrived: {out}")

class PositionedGit:
    """A git runner that can express each of `base_check`'s four positions.  `SI-32`.

    `FakeGit` cannot: it answers `merge-base --is-ancestor` with rc 0 unconditionally, so every repo reads as
    a DESCENDANT and every lineage gate passes. A fake that can only produce the allowed answer would have
    made this whole test class vacuous — which is the shape that let `SI-9`'s "32/32" and `SI-29`'s dry-run
    contract pass while proving nothing.

    `position` is one of at-base | descendant | present | absent.
    """

    def __init__(self, position="at-base", head="a" * 40, dirty=()):
        self.position = position
        self.head = head
        self.dirty = list(dirty)
        self.calls = []

    def __call__(self, args, cwd=None):
        args = list(args)
        self.calls.append(tuple(args))
        if args[:2] == ["rev-parse", "HEAD"]:
            if self.position == "absent" and self.head is None:
                return 1, ""
            return 0, f"{self.head}\n"
        if args[0] == "status":
            return 0, "".join(f" M {path}\n" for path in self.dirty)
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return (0, "") if self.position == "descendant" else (1, "")
        if args[0] == "cat-file":
            return (0, "commit\n") if self.position in ("present", "descendant") else (1, "")
        return 0, ""


class TestTheLineageGate(CliCase):
    """`SI-32`, mechanism B: a claim of DONE from the wrong base is refused.

    The failure is on record twice in one worker's register:
      * `OI-2` — *"ws3 arrived at gluten 4020d0715 / velox 8d62aac98 — the golden prebuild — not at my
        lineage base … nothing moves a slot forward to a milestone's own base. The failure mode is invisible:
        the build succeeds and tests pass, so the whole milestone silently stacks on the pre-fix baseline.
        **Two workers in the previous wave hit exactly this.**"*
      * `OI-1` — a seed rendered once per wave named one base and a per-milestone charter named another, so
        the worker had to arbitrate between two prose authorities.

    Why a GATE and not a check the worker runs: a check you must remember to run fails the same way the
    checkout does. `OI-3` is the proof — the verb existed, the worker ran it, and the id did not resolve. This
    gate cannot be skipped, because since `SI-27` `harvest` refuses to close a worker whose report never
    reached the coordinator, so every worker must pass through `propose --status done`.
    """

    BASE = "b" * 40

    def _dispatched(self, fleet, position, mode=None, lineage=None):
        """A record with a recorded lineage base, and a git runner in the given position."""
        child = fleet.paths["readyWorker"]
        record = fleet.store.read(fleet.ids["readyWorker"])
        record.lineage_base = lineage if lineage is not None else f"alpha={self.BASE}"
        record.lineage_mode = mode or ""
        record.golden = str(fleet.slots_dir)
        fleet.store.write(record)
        fleet.git = PositionedGit(position=position,
                                 head=self.BASE if position == "at-base" else "c" * 40)
        Roadmap(child).add(Milestone(id="L1", title="the lift", status="blocked", deps=[], evidence=[]))
        return child, record

    # ---- refused --------------------------------------------------------------------------------

    def test_done_is_refused_when_the_base_is_present_but_not_checked_out(self):
        """The incident's exact state: the slot is at the golden, the base is fetched, nothing repositioned."""
        fleet = self.loaded()
        child, record = self._dispatched(fleet, "present", mode="code")

        code, out, err = fleet.run(["propose", "--instant", str(child), "--milestone", "L1",
                                    "--status", "done", "--evidence", "evidence/INDEX.md"])

        self.assertEqual(EXIT_REFUSED, code, f"a claim of done from the wrong base was accepted: {out}")
        self.assertIn("NOT checked out", err)
        self.assertIn(self.BASE[:12], err, "the refusal must name the base it expected")
        self.assertIn("base-check", err, "and how to get the per-repo detail")
        #: Filtered to L1: `loaded()` pre-seeds a proposal for M1 so `apply`'s own argv row is admissible,
        #: and a bare emptiness check would be asserting the fixture rather than the refusal.
        self.assertEqual([], [x for x in Roadmap(child).proposals() if x.milestone == "L1"],
                         "the proposal was written despite the refusal")

    def test_done_is_refused_when_the_base_is_absent_entirely(self):
        fleet = self.loaded()
        child, record = self._dispatched(fleet, "absent", mode="code")

        code, out, err = fleet.run(["propose", "--instant", str(child), "--milestone", "L1",
                                    "--status", "done", "--evidence", "evidence/INDEX.md"])

        self.assertEqual(EXIT_REFUSED, code)
        self.assertIn("does not have", err)

    def test_complete_is_gated_too(self):
        """The rename IS the state transition, so a completed instant on the wrong base is the artefact
        everything downstream trusts."""
        fleet = self.loaded()
        child, record = self._dispatched(fleet, "present", mode="code")
        before = child.name

        code, out, err = fleet.run(["complete", "--instant", str(child)])

        self.assertEqual(EXIT_REFUSED, code, f"complete accepted the wrong base: {out}")
        self.assertTrue((child.parent / before).is_dir(), "the folder was renamed despite the refusal")

    # ---- allowed, and each for its own reason ---------------------------------------------------

    def test_running_is_not_gated(self):
        """A worker reports `running` from wherever it happens to be while it works. Gating that would make
        the mechanism fire on every worker before it had done anything."""
        fleet = self.loaded()
        child, record = self._dispatched(fleet, "present", mode="code")

        code, out, err = fleet.run(["propose", "--instant", str(child), "--milestone", "L1",
                                    "--status", "running", "--evidence", "evidence/INDEX.md"])

        self.assertEqual(0, code, err)

    def test_a_descendant_is_allowed_because_it_is_the_intended_end_state(self):
        """THE mis-trigger this must not have. A code milestone that has committed work on top of its base is
        a DESCENDANT, not at-base — and a check demanding equality would refuse exactly the workers who did
        everything right."""
        fleet = self.loaded()
        child, record = self._dispatched(fleet, "descendant", mode="code")

        code, out, err = fleet.run(["propose", "--instant", str(child), "--milestone", "L1",
                                    "--status", "done", "--evidence", "evidence/INDEX.md"])

        self.assertEqual(0, code, f"a descendant of the base was refused: {err}")

    def test_at_base_is_allowed(self):
        fleet = self.loaded()
        child, record = self._dispatched(fleet, "at-base", mode="code")

        code, out, err = fleet.run(["propose", "--instant", str(child), "--milestone", "L1",
                                    "--status", "done", "--evidence", "evidence/INDEX.md"])

        self.assertEqual(0, code, err)

    def test_analysis_mode_allows_the_base_to_be_fetched_but_not_checked_out(self):
        """The third legitimate position: reading via refs keeps the prebuilt native artifacts valid, which
        is the whole reason a slot is leased from a golden image."""
        fleet = self.loaded()
        child, record = self._dispatched(fleet, "present", mode="analysis")

        code, out, err = fleet.run(["propose", "--instant", str(child), "--milestone", "L1",
                                    "--status", "done", "--evidence", "evidence/INDEX.md"])

        self.assertEqual(0, code, f"analysis mode refused a legitimately-parked workspace: {err}")

    def test_no_recorded_lineage_means_no_gate(self):
        """Absence of a recorded base is not a failure — it is most dispatches, and every coordinator and
        compaction. A gate that fired on them would be an alarm nobody could clear."""
        fleet = self.loaded()
        child, record = self._dispatched(fleet, "absent", mode="", lineage="")

        code, out, err = fleet.run(["propose", "--instant", str(child), "--milestone", "L1",
                                    "--status", "done", "--evidence", "evidence/INDEX.md"])

        self.assertEqual(0, code, err)

    # ---- the flags refuse rather than half-work -------------------------------------------------

    def test_a_mode_with_no_base_is_refused(self):
        fleet = self.loaded()
        code, out, err = fleet.run(["dispatch", "--profile", str(fleet.profile("worker")),
                                    "--title", "modeOnly", "--base", "00000000", "--optype", "append",
                                    "--lineage-mode", "code"])
        self.assertEqual(2, code, "a mode with nothing to check was accepted")
        self.assertIn("--lineage-base", err)

    def test_a_malformed_pair_is_refused(self):
        fleet = self.loaded()
        code, out, err = fleet.run(["dispatch", "--profile", str(fleet.profile("worker")),
                                    "--title", "badPair", "--base", "00000000", "--optype", "append",
                                    "--lineage-base", "justasha"])
        self.assertEqual(2, code)
        self.assertIn("repo=sha", err)

    def test_the_checkout_instruction_is_generated_from_the_recorded_base(self):
        """`OI-1`'s fix. Two prose authorities disagreed about the base; an instruction GENERATED from the
        recorded field cannot drift from the field the gate checks, which is the only reason to generate it
        rather than write it into the profile by hand."""
        instruction = cli._checkout_instruction({"alpha": self.BASE, "beta": "d" * 40}, "code")

        self.assertIn(f"git -C alpha checkout --detach {self.BASE}", instruction)
        self.assertIn("git -C beta fetch --all", instruction)
        self.assertIn("REFUSE", instruction, "the worker must be told the gate exists")
        analysis = cli._checkout_instruction({"alpha": self.BASE}, "analysis")
        self.assertIn("do NOT", analysis, "analysis mode must not tell the worker to check out")
        self.assertNotIn("checkout --detach", analysis)


class TestBrief(CliCase):
    """`fleet brief` is the dispatched instant's first command.

    It exists because the alternative first instruction in a worker's skill was `cat .fleet/origin.json` —
    hand-parsing machine state, which is the thing the north star forbids. The row that earns the verb is
    `destination`: a worker can see WHERE its next report will land before it sends one, which is what makes
    a silently-local proposal impossible to walk into.
    """

    def test_brief_names_the_coordinator_the_milestone_and_the_destination(self):
        fleet = self.loaded()
        coordinator = fleet.paths["readyWorker"]
        child = fleet.paths["solo"]
        Roadmap(coordinator).add(Milestone(id="B1", title="the brief's milestone", status="blocked",
                                           deps=[], evidence=[]))
        origin_mod.write(child, Origin(coordinator=str(coordinator), dispatched_at=NOW, milestone="B1"))

        code, out, err = fleet.run(["brief", "--instant", str(child), "--porcelain"])

        self.assertEqual(0, code, err)
        kinds = {line.split("\t")[0] for line in out.splitlines()}
        self.assertLessEqual({"origin", "milestone", "destination", "outstanding", "population"}, kinds,
                             f"brief must answer every orientation question in its own row: {out}")
        self.assertIn(str(coordinator), out, "the worker must be told who its coordinator is")
        self.assertIn("B1", out, "and which milestone it was dispatched for")

    def test_brief_says_a_report_would_stay_local_when_there_is_no_origin(self):
        """The row that earns the verb. An instant with no coordinator is legitimate, and a worker must be
        able to SEE that its report would go nowhere a coordinator reads."""
        fleet = self.loaded()
        child = fleet.paths["solo"]
        self.assertIsNone(origin_mod.read(child), "this fixture is supposed to have no coordinator")

        code, out, err = fleet.run(["brief", "--instant", str(child), "--porcelain"])

        self.assertEqual(0, code, err)
        destination = [l for l in out.splitlines() if l.startswith("destination\t")]
        self.assertTrue(destination, "brief emitted no destination row")
        self.assertIn("LOCAL", destination[0],
                      "a worker whose report would stay local must be told so in that row")

    def test_brief_is_read_only(self):
        fleet = self.loaded()
        child = fleet.paths["solo"]
        before = fleet.record_state()

        code, out, err = fleet.run(["brief", "--instant", str(child), "--porcelain"])

        self.assertEqual(0, code, err)
        self.assertEqual(before, fleet.record_state(), "brief wrote to the record store")


class TestFoundByARealWorker(CliCase):
    """Three defects a real dispatched `claude` found in `§P` by following the skills literally.

    None was reachable from the hermetic suite as it stood, and the reason is worth recording: every existing
    test asserted the RECORDED path. Nobody had asked what a worker sees when it does the responsible thing
    first — interrogate the gate with `--dry-run`, read the remedy string a refusal hands you, read a status
    row before acting on it. That is what a real worker does, and it is where all three lived.
    """

    def test_review_dry_run_exits_zero_on_valid_input(self):
        """`--dry-run` answers "would this be admitted?", not "what does the pre-existing ledger say?".

        Before: a valid FIRST round with `--dry-run` returned the gate's code, and the gate saw a ledger
        without the round being proposed — so it read UNDECIDABLE and the verb exited 2 with NOTHING on
        stderr while stdout said "would record …". The worker's report: *"a worker doing the responsible
        thing gets a bare failure code with no explanation and would reasonably conclude their finding
        string is malformed and start editing a string that was already correct. I nearly did."*
        """
        fleet = self.loaded()
        fresh = fleet.worker("dryRunReview")
        self.assertEqual([], Review(fresh, now=lambda: NOW).rounds(),
                         "this test needs a ledger with NO prior round, or it cannot reproduce")

        code, out, err = fleet.run(["review", "--instant", str(fresh), "--scope", "all",
                                    "--verdict", "READY",
                                    "--finding", "P-1:Minor:applied:evidence/INDEX.md:the report:none",
                                    "--dry-run"])

        self.assertEqual(0, code,
                         f"a valid first round with --dry-run must exit 0; stderr was {err!r}")
        self.assertEqual([], Review(fresh, now=lambda: NOW).rounds(), "--dry-run wrote to the ledger")

    def test_a_malformed_finding_is_still_refused_under_dry_run(self):
        """The other half: making the dry run exit 0 must not make it accept anything. `_finding_of` refuses
        a malformed finding before the gate is ever consulted, and that has to keep happening."""
        fleet = self.loaded()
        fresh = fleet.worker("dryRunBadFinding")

        code, out, err = fleet.run(["review", "--instant", str(fresh), "--scope", "all",
                                    "--verdict", "READY", "--finding", "not-six-fields", "--dry-run"])

        self.assertEqual(2, code, "a malformed finding must still be refused under --dry-run")

    def test_the_review_gates_remedy_names_a_command_that_exists(self):
        """A refusal must name what clears it — and naming it WRONG is worse than naming nothing, because a
        worker who trusts the remedy over the skill gets a second exit 2. The gate said the round is recorded
        by `review add-round <scope> ...`; there has never been an `add-round` subcommand, and `review`
        declares no positionals at all."""
        fleet = self.loaded()
        fresh = fleet.worker("remedyString")

        code, out, err = fleet.run(["review", "--instant", str(fresh), "--porcelain"])

        remedy = [line for line in out.splitlines() if line.startswith("gate\t")]
        self.assertTrue(remedy, f"no gate row: {out}")
        self.assertNotIn("add-round", remedy[0],
                         "the gate's clears_when names a subcommand that does not exist")
        self.assertIn("--verdict", remedy[0],
                      "the remedy must name the real flag form, or a worker cannot act on it")

    def test_briefs_milestone_row_does_not_state_blocked_and_ready_together(self):
        """The worker's report: *"says status=blocked AND ready on the same row, with no blocker named. I
        could not tell from the row whether something was actually blocking me."* The stored status is a
        label; readiness is derived. Two facts, so the row must not run them together as if one contradicts
        the other."""
        fleet = self.loaded()
        coordinator = fleet.paths["readyWorker"]
        child = fleet.paths["solo"]
        Roadmap(coordinator).add(Milestone(id="R1", title="stale label", status="blocked",
                                           deps=[], evidence=[]))
        origin_mod.write(child, Origin(coordinator=str(coordinator), dispatched_at=NOW, milestone="R1"))

        code, out, err = fleet.run(["brief", "--instant", str(child), "--porcelain"])

        self.assertEqual(0, code, err)
        row = [line for line in out.splitlines() if line.startswith("milestone\t")][0]
        self.assertIn("stored status", row,
                      "the row must mark the status as a STORED LABEL, not present it as the live answer")
        self.assertIn("READY to start", row, "and it must say plainly whether the worker may begin")
        self.assertIn("DERIVED", row, "and say where readiness comes from, so a stale label is not confusing")


class TestAnOverrideIsAudited(CliCase):
    """`SI-34`. An override is a judgement that a guard was WRONG for one dispatch, and the only record of it
    was the sentence the guard printed to a terminal.

    Plan 6's `F7` requires "with a reason ⇒ exit 0 and the reason is in the record". It was not: the value
    reached `guards.Context`, decided admission, and was never written anywhere. A week later an overridden
    refusal is indistinguishable from a rule that never fired.
    """

    def test_the_override_reason_is_written_to_the_record(self):
        fleet = self.loaded()
        reason = "the compaction is stalled on CI and this milestone does not touch its tree"

        code, out, err = fleet.run(["dispatch", "--porcelain", "--profile", str(fleet.profile("worker")),
                                    "--title", "overridden", "--base", FRESH_BASE_DIGITS,
                                    "--optype", "append", "--cap", "9", "--override", reason])

        self.assertEqual(0, code, err)
        todo = [l.split("\t")[1] for l in out.splitlines() if l.startswith("todo_id\t")][0]
        record = [r for r in fleet.store.all() if r.todo_id == todo][0]
        self.assertEqual(reason, record.override_reason,
                         "the override reason is not on the record, so the audit trail is terminal scrollback")

    def test_a_dispatch_with_no_override_records_an_empty_reason(self):
        """The field must not acquire a value nobody asked for: an unset override is empty, not a placeholder
        that later reads as a decision somebody made."""
        fleet = self.loaded()

        code, out, err = fleet.run(["dispatch", "--porcelain", "--profile", str(fleet.profile("worker")),
                                    "--title", "notOverridden", "--base", FRESH_BASE_DIGITS,
                                    "--optype", "append"])

        self.assertEqual(0, code, err)
        todo = [l.split("\t")[1] for l in out.splitlines() if l.startswith("todo_id\t")][0]
        record = [r for r in fleet.store.all() if r.todo_id == todo][0]
        self.assertEqual("", record.override_reason)


class TestADeclarationIsNeverEmpty(CliCase):
    """`SI-36`, found by `§G6`. `declare --phase ""` exited 0 and silently cleared the phase — and did
    something worse than that.

    `_normalise_phase("")` returns `""`, which is not `None`, so `set_phase` stored it and the handler's own
    guard (`if value is None`) never fired. The consequence was not merely a wrong exit code: `near_miss_rows`
    skipped every line while a phase was stored, so an empty declaration bought SILENCE FROM THE RCF-9 LINT
    while buying no exclusion from the cap, which still compares against `awaiting-ci`.
    """

    def test_an_empty_phase_is_refused(self):
        fleet = self.loaded()
        ready = str(fleet.paths["readyWorker"])
        fleet.run(["declare", "--instant", ready, "--phase", "AWAITING-CI"])
        before = Declarations(fleet.paths["readyWorker"]).phase()
        self.assertEqual("awaiting-ci", before, "this test needs a standing declaration to be meaningful")

        code, out, err = fleet.run(["declare", "--instant", ready, "--phase", ""])

        self.assertEqual(2, code, "an empty phase was accepted")
        self.assertEqual(before, Declarations(fleet.paths["readyWorker"]).phase(),
                         "the standing declaration was cleared by an empty one")

    def test_whitespace_only_is_refused_too(self):
        """`_normalise_phase` collapses whitespace, so `"   "` also normalises to nothing — and a check that
        only tested `""` would miss the shape a human actually types."""
        fleet = self.loaded()
        code, out, err = fleet.run(["declare", "--instant", str(fleet.paths["readyWorker"]),
                                    "--phase", "   "])
        self.assertEqual(2, code)

    def test_a_stored_empty_phase_cannot_suppress_the_near_miss_rule(self):
        """The second door. `declare` now refuses an empty phase, but a store written by an older build can
        still carry one, and the rule must not go quiet because of it."""
        fleet = self.loaded()
        child = fleet.paths["readyWorker"]
        Declarations(child).set_phase("")
        (child / "HANDOFF.md").write_text("Updated: now\n\n## Phase: AWAITING-CI\n")

        code, out, err = fleet.run(["lint", "--instant", str(child), "--porcelain"])

        self.assertIn(cli.NEAR_MISS, out,
                      "a stored EMPTY phase suppressed the near-miss rule; only a real phase may do that")


class TestTheNearMissRuleReadsShapeAndRetraction(CliCase):
    """`§G3`. The rule flagged 2 of 4 declaration shapes: emphasis was permitted only BEFORE the word, and
    the value was anchored at end of line.

    Closing the trailing-prose gap alone would have broken `G4`, whose fixture — a retraction — is also
    value-then-prose. A shape-only rule cannot separate them, so the rule reads the tail for retraction
    language. That is a heuristic and is documented as one; the cheaper error is exempting a retraction
    wrongly, because a lint that cries wolf over every retraction gets switched off.
    """

    def _lint(self, fleet, body):
        child = fleet.paths["readyWorker"]
        (child / "HANDOFF.md").write_text("Updated: now\n\n" + body + "\n")
        return fleet.run(["lint", "--instant", str(child), "--porcelain"])

    def test_all_four_declaration_shapes_are_flagged(self):
        fleet = self.loaded()
        for shape in ("## Phase: AWAITING-CI",
                      "    Phase: AWAITING-CI",
                      "## **Phase:** AWAITING-CI",
                      "- **Phase**: AWAITING-CI",
                      "## Phase: AWAITING-CI — waiting on the CI queue"):
            with self.subTest(shape=shape):
                code, out, err = self._lint(fleet, shape)
                self.assertIn(cli.NEAR_MISS, out,
                              f"the shape {shape!r} was not flagged; an author who writes it is not told")

    def test_a_retraction_is_not_flagged(self):
        """`G4`'s fixture, and the reason the rule cannot be shape-only."""
        fleet = self.loaded()
        for retraction in ("Phase: AWAITING-CI was declared and is now REMOVED",
                           "`Phase: AWAITING-CI` — retracted, no longer in effect"):
            with self.subTest(retraction=retraction):
                code, out, err = self._lint(fleet, retraction)
                self.assertNotIn(cli.NEAR_MISS, out,
                                 f"the retraction {retraction!r} was flagged; a naive version of this rule "
                                 f"fired on 5 of 5 live instants for exactly this reason")

    def test_a_real_declaration_silences_the_rule(self):
        """It is a RULE, not a grep: the same line with a declaration behind it is not a near miss."""
        fleet = self.loaded()
        child = fleet.paths["readyWorker"]
        fleet.run(["declare", "--instant", str(child), "--phase", "AWAITING-CI"])

        code, out, err = self._lint(fleet, "## Phase: AWAITING-CI")

        self.assertNotIn(cli.NEAR_MISS, out)


class TestCloneMakesTheGoldenAnInput(CliCase):
    """`SI-19`'s remaining half. `FI-6` recorded `clone` as implemented in Plan 2; it did not exist, and the
    consequence was quieter than a missing feature: `Workspace.golden()` had exactly ONE caller —
    `set-golden`'s own echo-back — so the declared golden was write-only, and a pool grew only by `enroll`ing
    directories somebody had duplicated by hand with nothing checking they came from the golden at all.

    A filesystem copy and NOT a git clone, deliberately: a golden carries prebuilt artifacts and a warm build
    cache, which is the entire reason leasing a slot beats a fresh checkout, and `git clone` would reproduce
    the source while discarding exactly that.
    """

    def _golden(self, fleet, repos=("alpha",)):
        golden = fleet.tmp / "golden"
        for repo in repos:
            (golden / repo).mkdir(parents=True)
            (golden / repo / "f.txt").write_text("content\n")
            (golden / repo / ".git").mkdir()
        (golden / ".m2").mkdir()
        (golden / ".m2" / "warm.jar").write_text("cache\n")
        fleet.run(["set-golden", "--path", str(golden)])
        return golden

    def test_clone_copies_the_golden_and_enrols_the_result(self):
        fleet = self.loaded()
        self._golden(fleet)
        target = fleet.tmp / "grown-slot"

        code, out, err = fleet.run(["clone", "--slot", str(target), "--porcelain"])

        self.assertEqual(0, code, err)
        self.assertTrue((target / "alpha" / "f.txt").is_file(), "the golden's content did not arrive")
        self.assertTrue((target / ".m2" / "warm.jar").is_file(),
                        "the build cache did not arrive — which is the whole reason this is a copy and not a "
                        "git clone")
        self.assertIn(target.name, [str(p) for p in fleet.pool.slots()],
                      "the clone was not enrolled, so the pool cannot lease it")

    def test_clone_refuses_an_existing_target(self):
        """A clone onto an existing directory is either a mistake or a request to erase somebody's leased
        workspace, and guessing between those is how a live slot is destroyed."""
        fleet = self.loaded()
        self._golden(fleet)
        target = fleet.tmp / "already-there"
        target.mkdir()

        code, out, err = fleet.run(["clone", "--slot", str(target)])

        self.assertEqual(2, code)
        self.assertIn("never overwrites", err)

    def test_clone_refuses_when_no_golden_is_declared(self):
        """`MI-7`: there is deliberately no fallback. A clone that invented a source would put a worker in a
        workspace nobody declared."""
        fleet = self.fleet(slots=2)

        code, out, err = fleet.run(["clone", "--slot", str(fleet.tmp / "nope")])

        self.assertEqual(2, code)

    def test_a_parity_mismatch_leaves_the_slot_UNENROLLED(self):
        """The order is the safety property: copy, verify, THEN enrol. Enrolment is the moment a slot becomes
        leasable — `mkdir` is the lock — so a slot enrolled before it was verified can be leased while it is
        still wrong, and every `base-check` in it would compare against the wrong commit.

        The git seam is pointed at a runner that reports a DIFFERENT head for the clone than for the golden,
        which is the only way to reach this branch without corrupting a real repository.
        """
        fleet = self.loaded()
        golden = self._golden(fleet)
        target = fleet.tmp / "mismatched"
        heads = iter(["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
                      "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"])

        def divergent(args, cwd=None):
            if list(args)[:2] == ["rev-parse", "HEAD"]:
                return 0, next(heads, "cccccccccccccccccccccccccccccccccccccccc\n")
            return 0, ""

        fleet.git = divergent

        code, out, err = fleet.run(["clone", "--slot", str(target), "--verify-repos", "alpha"])

        self.assertEqual(EXIT_REFUSED, code, f"a parity mismatch was accepted: {out}")
        self.assertIn("UNENROLLED", err)
        self.assertTrue(target.is_dir(),
                        "the mismatched clone was DELETED; no verb here deletes outward state, and a copy "
                        "somebody can inspect beats one the tool tidied away")
        self.assertNotIn(target.name, [str(p) for p in fleet.pool.slots()],
                         "a clone that failed parity was enrolled anyway")

    def test_parity_is_checked_only_on_repos_the_caller_names(self):
        """Parity over "whatever looked like a repo" would report a green it did not measure for the repo that
        mattered, so the population is named and the output says when it is empty."""
        fleet = self.loaded()
        self._golden(fleet)
        target = fleet.tmp / "unverified"

        code, out, err = fleet.run(["clone", "--slot", str(target), "--porcelain"])

        self.assertEqual(0, code, err)
        self.assertIn("this clone is unverified", out,
                      "a clone with no --verify-repos must SAY it was not verified")
