"""Properties, GENERATED — one test method per member of the population, never one call per case.

This file is Plan 5 Task 16, written along`cli` because every case here is generated from `VERBS` and a
generator belongs next to the spec it reads. The eight properties are the ones a hand-written case list
gets wrong in the same way every time: it covers the instance that was fixed and not its counterpart.

* Every declared flag, passed last with no value, under the real `timeout` binary. `OI-8` was an
  **infinite loop**, and an in-process assertion about a loop that never returns never returns either.
* Every declared flag appears in `usage()` — `W2-20`, where `--profile` was mandatory and undocumented.
* Every mutating verb has `--dry-run` and it yields a zero delta across filesystem, records and pool.
* Every emitted marker is unique. *"A marker two things share is not a marker"* (`OBS-44`) — and `FI-1`
  is this build's own instance, where a checker's own words tripped the checker.
* Every module defines liveness at most once, **by AST and not by text** (`FI-12`): the text version of
  this check counted a docstring that explained the rule.
* Every exit path a failure matrix can reach returns a registered code (`NFR2-8`).
* Every checker emits a `population` row (§9: never silent about a population it could not cover).
* Every alarm-bearing verdict carries `clears_when` **and** `clears_who` (§9: escalation is permitted iff
  a clearing action exists and is named in the same output).

The generated methods are attached to the classes at import time, so an unkillable member of a population
shows up as a named failure rather than as one loop that stopped early.
"""
import ast
import io
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from fleet import EXIT_CODES
from fleet import cli
from fleet.guards import Context, evaluate_all, guards_for
from fleet.harvest import Harvest
from fleet.layout import validate as layout_validate
from fleet.pool import Pool
from fleet.profiles import Profile, lint as profiles_lint
from fleet.release import CANDIDATE, RELEASED, Releases, Version
from fleet.release_verify import GATE_ROSTER, GREEN, write_verdict
from fleet.review import Finding, Review
from fleet.roadmap import Milestone, Roadmap
from fleet.session import LiveSession, Probes, SessionLayer
from fleet.store import Record, Store

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PKG = SRC / "fleet"

NOW = "2026-07-30T12:00:00Z"
LONG_AGO = "2026-07-29T00:00:00Z"
OURS = "00000000-07300312-inflight-append-fleetInfraRebuild"
FRESH_BASE = "00000000-07300400-inflight-append-freshEffort"
#: `SI-29`. See the note beside the same constant in test_cli.py: `--base` takes the 8-digit base, and
#: passing a full instant name made a real dispatch over this row exit 2 before it could mutate.
FRESH_BASE_DIGITS = "07300400"
TIMEOUT_RC = 124

BUSY_PANE = "\n".join(["working", "  esc to interrupt"])
#: A quiet claude pane: the input box holds its placeholder, which is not a swallowed submit. `close`
#: refuses a busy pane, so the verb needs a pane it is ALLOWED to close or its generated cases assert a
#: refusal and nothing else.
IDLE_PANE = "\n".join(["done", "", '❯ try "fix the failing test"', "  ? for shortcuts"])
RUNBOOK = "# RUNBOOK\n\n```bash\necho verified\n```\n"

#: The release area every release verb's argv row is driven against: one RELEASED version, one CANDIDATE
#: carrying gate evidence, and the version a cut would add. `0.1.1` is what the promote row targets
#: because a patch bump is the one gate evidence alone may carry.
DEPLOYED_RELEASE = "0.1.0"
SEEDED_CANDIDATE = "0.1.1"
SEEDED_TAG = f"fleet/v{SEEDED_CANDIDATE}"
CUT_VERSION = "0.2.0"

#: A marker, for the purposes of the uniqueness property: a lowercase dashed token bound to an
#: UPPER_SNAKE module constant. Values with spaces, dots, slashes or capitals are prose, filenames or
#: state vocabularies and are not what `OBS-44` is about.
_MARKER = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_CONST = re.compile(r"^_?[A-Z][A-Z0-9_]*$")

#: The names a checker goes by in this package. Derived, so a checker added later is discovered rather
#: than forgotten — a hand-listed set is the second copy this whole build exists to delete.
CHECKER_NAMES = ("validate", "lint", "report")


def snapshot(root: pathlib.Path) -> dict:
    out = {}
    for path in sorted(root.rglob("*")):
        stat = path.stat()
        out[str(path)] = (path.is_dir(), stat.st_mtime_ns, stat.st_size if path.is_file() else 0)
    return out


class Fleet:
    """A synthetic fleet through injected probes only. Lean: the generated cases need a valid invocation
    per verb and the three halves of a delta, and nothing more."""

    def __init__(self, slots: int = 4):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-contracts-"))
        self.home = self.tmp / "fleethome"
        self.instants = self.tmp / "instants"
        self.instants.mkdir()
        self.slots_dir = self.tmp / "slots"
        self.slots_dir.mkdir()
        self.profiles_dir = self.tmp / "profiles"
        self.profiles_dir.mkdir()
        self.procs, self.panes, self.tmux_live = [], {}, set()
        self.started, self.killed = [], []
        probes = Probes(list_processes=lambda: list(self.procs),
                        capture_pane=lambda name: self.panes.get(name, ""),
                        has_session=lambda name: name in self.tmux_live,
                        start_session=lambda n, c, m: self.started.append(n),
                        kill_session=lambda n: self.killed.append(n))
        self.sessions = SessionLayer(probes)
        self.store = Store(self.home)
        self.pool = Pool(self.home, cwd_probe=lambda p: [], alive=self.sessions.alive)
        self.harvest = Harvest(self.home, now=lambda: NOW)
        self.runner = _Runner()
        self.git = _Git()
        for index in range(slots):
            slot = f"ws{index + 1}"
            (self.slots_dir / slot).mkdir()
            self.pool.enroll(self.slots_dir / slot)
        self._n = 0
        self.paths, self.ids = {}, {}

    def profile(self, kind="worker") -> pathlib.Path:
        path = self.profiles_dir / kind
        path.mkdir(exist_ok=True)
        (path / "profile.json").write_text(json.dumps({"kind": kind}))
        (path / "charter.md").write_text(
            "# {{TITLE}}\n\nRun `fleet declare --instant \"$INSTANT\" --phase awaiting-ci`.\n")
        (path / "seed.txt").write_text("Run `fleet declare --instant \"$INSTANT\" --phase awaiting-ci`.\n")
        return path

    def spare(self, name: str = "wsSpare") -> pathlib.Path:
        """A real directory that is NOT enrolled — what `enroll` is pointed at."""
        path = self.slots_dir / name
        path.mkdir(exist_ok=True)
        return path

    def worker(self, name, *, state="inflight", optype="append", slot=None, live=True,
               base=OURS, pane=BUSY_PANE) -> pathlib.Path:
        self._n += 1
        curr = f"0730{self._n:04d}"
        path = self.instants / f"00000000-{curr}-{state}-{optype}-{name}"
        path.mkdir()
        (path / "HANDOFF.md").write_text("Updated: now\n")
        (path / "RUNBOOK.md").write_text(RUNBOOK)
        todo_id, tmux = f"{name}-{curr}", f"dt-{name}"
        self.store.write(Record(todo_id=todo_id, child_instant=str(path), base_instant=base,
                                slot=slot or "", tmux=tmux, profile=str(self.profile()),
                                golden=str(self.slots_dir), lineage_base="", title=name,
                                dispatched_at=NOW, launched_at=NOW))
        if slot:
            self.pool.claim(todo_id=todo_id, tmux=tmux, base_instant=base,
                            child_instant=str(path), slot=slot)
        if live:
            self.procs.append(LiveSession(pid=2000 + self._n, cwd=path, name=tmux))
            self.panes[tmux] = pane
            self.tmux_live.add(tmux)
        self.paths[name] = path
        self.ids[name] = todo_id
        return path

    def orphan(self, name="orphanWork") -> pathlib.Path:
        self._n += 1
        path = self.instants / f"00000000-0730{self._n:04d}-inflight-append-{name}"
        path.mkdir()
        (path / "HANDOFF.md").write_text("Updated: now\n")
        (path / "RUNBOOK.md").write_text(RUNBOOK)
        self.paths[name] = path
        return path

    def register_stale_source(self) -> None:
        base_dir = self.instants / OURS
        base_dir.mkdir(exist_ok=True)
        register = base_dir / "ISSUES.md"
        register.write_text("## FI-1 the checker's own words tripped the checker\n")
        self.harvest.register(str(base_dir), str(register))
        data = json.loads(self.harvest.path.read_text())
        for entry in data["sources"]:
            entry["registered_at"], entry["last_run"] = LONG_AGO, LONG_AGO
        self.harvest.path.write_text(json.dumps(data, indent=2))

    def context(self):
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

    def record_state(self) -> dict:
        records = self.home / "records"
        if not records.is_dir():
            return {}
        return {p.name: p.read_text() for p in sorted(records.glob("*.json"))}

    def pool_state(self) -> dict:
        return {slot: (lambda h: h.to_json() if h else None)(self.pool.lease(slot))
                for slot in self.pool.slots()}


class _Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, cwd=None, env=None):
        self.calls.append((str(command), str(cwd) if cwd else None))
        return (0, "", "")


class _Git:
    """`(args, cwd) -> (rc, stdout)`. `tags` and `archive` are answered for the release verbs: a cut asks
    whether its predecessor's tag exists (it must) and whether its own does (it must not), and it cannot
    export from a fake — which is said with a non-zero code, the way git says it, so `Repo.export` raises
    its own diagnostic instead of the verb dying on a missing file."""

    def __init__(self, tags=(SEEDED_TAG,)):
        self.tags = set(tags)

    def __call__(self, args, cwd=None):
        args = list(args)
        if args[:2] == ["rev-parse", "HEAD"]:
            return 0, "0" * 40 + "\n"
        if args[:2] == ["tag", "-l"]:
            return 0, "".join(f"{name}\n" for name in sorted(self.tags) if name in args[2:])
        if args[0] == "archive":
            return 128, "this fixture describes a repository without being one"
        return 0, ""


def release_fixture(fleet) -> tuple:
    """`(repo, releases)` for the release verbs' rows, built once per fixture and never changed on a
    second call — `argv_for` runs before the dry-run snapshot is taken.

    The checkout carries the two things a cut checks at the edge: a `.git`, and the
    `fleet/src/fleet/__init__.py` whose `__version__` it stamps.
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
        # …so the rollback row has a target and its zero-delta case is a withheld mutation.
        releases.append_history(action="DEPLOY", version=SEEDED_CANDIDATE,
                                from_version=DEPLOYED_RELEASE, actor="fixture", host="fixture",
                                ts=NOW, reason="seeded so the rollback row has a target")
    return repo, releases.root


class Loaded(unittest.TestCase):
    """A fixture rich enough that every verb on the surface has a valid, ADMISSIBLE invocation."""

    def setUp(self):
        self.fleets = []

    def tearDown(self):
        for fleet in self.fleets:
            shutil.rmtree(fleet.tmp, ignore_errors=True)

    def loaded(self) -> Fleet:
        fleet = Fleet(slots=8)
        self.fleets.append(fleet)
        fleet.register_stale_source()
        fleet.spare()
        fleet.worker("doomed", slot="ws5")
        fleet.worker("closable", slot="ws6", pane=IDLE_PANE)
        fleet.worker("solo", slot="ws1")
        ready = fleet.worker("readyWorker", slot="ws2")
        Review(ready, now=lambda: NOW).add_round(
            "all", "READY", [Finding(id="F-1", severity="Minor", status="applied",
                                     location="src/fleet/cli.py", finding="derived", action="none")])
        roadmap = Roadmap(ready)
        roadmap.add(Milestone(id="M1", title="land the cli", status="blocked", deps=[], evidence=[],
                              owner="the worker"))
        roadmap.propose(ready, "M1", "running", ["evidence/02-acceptance/verify-acs.sh"])
        harvestable = fleet.worker("harvestable", state="complete", slot="ws3", live=False)
        Review(harvestable, now=lambda: NOW).add_round(
            "all", "READY", [Finding(id="F-2", severity="Nit", status="applied", location="x",
                                     finding="fine", action="none")])
        fleet.orphan()
        return fleet

    def argv_for(self, fleet: Fleet) -> dict:
        ready = str(fleet.paths["readyWorker"])
        repo, releases = release_fixture(fleet)
        return {
            "init": ["--name", "freshOne", "--base", "00000000"],
            "dispatch": ["--profile", str(fleet.profile()), "--title", "a fresh worker",
                         "--base", FRESH_BASE_DIGITS, "--optype", "append"],
            "resume": ["--instant", str(fleet.paths["orphanWork"]), "--slot", "ws4",
                       "--tmux", "dt-orphanWork"],
            "declare": ["--instant", ready, "--phase", "AWAITING-CI"],
            "park": ["--instant", ready, "--question", "which baseline is the ruler?"],
            "unpark": ["--instant", ready],
            #: `SI-26`. A fresh id, because `add` refuses a duplicate and the fixture pre-seeds `M1`.
            "milestone": ["--instant", ready, "--id", "M-contract", "--title", "added by the contract"],
            "propose": ["--instant", ready, "--milestone", "M1", "--status", "done",
                        "--evidence", "evidence/x.sh"],
            "apply": ["--instant", ready, "--milestone", "M1"],
            "review": ["--instant", ready, "--scope", "all", "--verdict", "READY"],
            "complete": ["--instant", ready],
            "harvest": ["--id", fleet.ids["harvestable"]],
            "board": [],
            "status": ["--id", fleet.ids["solo"]],
            "leases": [],
            #: Read-only and argument-free. It shells out to `claude agents --json`; where that binary
            #: is absent the verb REFUSES (`PeersUnavailable` -> `EXIT_ATTENTION`) rather than
            #: reporting an empty peer set, which is the fail-closed behaviour it exists to provide.
            "peers": [],
            "abort": ["--instant", str(fleet.paths["doomed"]),
                      "--reason", "the baseline moved under it"],
            "close": ["--id", fleet.ids["closable"]],
            #: A path that does NOT exist: `clone` refuses an existing target by design.
            "clone": ["--slot", str(fleet.tmp / "cloned-slot")],
            "enroll": ["--slot", str(fleet.spare())],
            "unenroll": ["--slot", "ws8"],
            "reap": ["--base", OURS],
            "set-golden": ["--path", str(fleet.slots_dir)],
            #: `SI-32`. A subject with no recorded lineage base — the verb must answer "nothing to check"
            #: rather than fail, because that is the state of most dispatches.
            "brief": ["--instant", ready],
            "base-check": ["--id", fleet.ids["solo"]],
            "roadmap": ["--instant", ready],
            "lint": ["--instant", ready],
            "verify": ["--instant", ready],
            "reconcile": [],
            "pane-guard": ["--pane", "dt-solo"],
            "seed-check": [],
            "compaction-status": [],
            "selftest": [],
            #: Every row names its repository and its release area. The generated cases drive these for
            #: REAL, and a release verb that inferred either from the working directory would tag the
            #: checkout the suite is running from.
            "release-cut": ["--version", CUT_VERSION, "--repo", str(repo), "--releases", str(releases)],
            "release-verify": ["--version", SEEDED_CANDIDATE, "--releases", str(releases)],
            "release-promote": ["--version", SEEDED_CANDIDATE, "--releases", str(releases)],
            "release-deploy": ["--version", DEPLOYED_RELEASE, "--releases", str(releases)],
            "release-rollback": ["--reason", "the generated matrix drives this row for real",
                                 "--releases", str(releases)],
            "release-status": ["--releases", str(releases)],
            "release-list": ["--releases", str(releases)],
            "release-history": ["--releases", str(releases)],
        }


class TestTheArgvTable(Loaded):
    """The one table in this file that is NOT derived from `VERBS`, because a valid invocation needs
    fixture paths. Task 14b found it the hard way: the seven verbs `FD-12` added were generated into
    `TestEveryExitPathIsRegistered` and `TestEveryMutatingVerbDryRuns` **automatically**, and then failed
    with `KeyError` — a hand-maintained second copy, discovered as a crash rather than as a finding."""

    def test_the_argv_table_covers_every_verb(self):
        fleet = self.loaded()
        self.assertEqual(set(self.argv_for(fleet)), set(cli.VERBS),
                         "the argv table and VERBS disagree; every generated case over the missing verb "
                         "then fails as a KeyError instead of as a property")


# --- property 1: every declared flag, passed last with no value, under `timeout` -------------------

_MATRIX = None


def trailing_flag_matrix() -> dict:
    """One `timeout`-wrapped subprocess per declared flag. Computed once and shared by the generated
    methods, so the property costs one process per flag and not one per assertion."""
    global _MATRIX
    if _MATRIX is not None:
        return _MATRIX
    rows, home = {}, pathlib.Path(tempfile.mkdtemp(prefix="fleet-contracts-flags-"))
    try:
        for verb, spec in sorted(cli.VERBS.items()):
            for flag in spec.flags:
                done = subprocess.run(
                    ["timeout", "10", sys.executable, "-m", "fleet.cli", verb, flag.name],
                    capture_output=True, text=True,
                    env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin",
                         "FLEET_HOME": str(home), "HOME": str(home),
                         # A suite IS running: `selftest` must not start another (SELFTEST_GUARD).
                         cli.SELFTEST_GUARD: "1"})
                rows[(verb, flag.name)] = (done.returncode, done.stdout, done.stderr)
    finally:
        shutil.rmtree(home, ignore_errors=True)
    _MATRIX = rows
    return rows


class TestEveryFlagLastWithNoValue(unittest.TestCase):
    """Generated over `VERBS`. `OI-8`, Critical: a trailing flag made the tool spin forever, and the
    pre-existing `--seed-file` had the identical defect one line away."""

    def check(self, verb, flag):
        rc, out, err = trailing_flag_matrix()[(verb, flag.name)]
        self.assertNotEqual(rc, TIMEOUT_RC, f"{verb} {flag.name} HUNG — this is OI-8 itself")
        if flag.takes_value:
            self.assertEqual(rc, 2, f"{verb} {flag.name} with no value returned {rc}, not 2")
            self.assertIn(cli.NEEDS_VALUE, err,
                          f"{verb} {flag.name} exited 2 with no value diagnostic: {err!r}")
            self.assertIn(flag.name, err, f"{verb} {flag.name}'s diagnostic does not name it")
        else:
            self.assertNotIn(cli.NEEDS_VALUE, err,
                             f"{verb} {flag.name} takes no value and was told it needs one")
            self.assertIn(rc, cli.EXIT_CODES_ALL, f"{verb} {flag.name} returned {rc}")


class TestEveryFlagInUsage(unittest.TestCase):
    """Generated over `VERBS`. `W2-20`: mandatory and undocumented, on a line with zero assertions."""

    def check(self, verb, flag):
        self.assertIn(flag.name, cli.usage(), f"{verb} {flag.name} is absent from usage()")
        self.assertIn(flag.name, cli.usage(verb), f"{verb} {flag.name} is absent from usage({verb!r})")


class TestEveryMutatingVerbDryRuns(Loaded):
    """Generated over the mutating verbs. `RI-32`/`OBS-70`: two actors created stray instants in another
    effort's tree probing a guard, one of them after reading and citing the warning against it."""

    def check(self, verb):
        self.assertIn(cli.DRY_RUN, {f.name for f in cli.VERBS[verb].flags},
                      f"the mutating verb {verb} has no {cli.DRY_RUN}")
        fleet = self.loaded()
        argv = self.argv_for(fleet)[verb]
        self.assertTrue(fleet.pool.free_slots(), "no free slot: the destructive path cannot fire")
        before_fs, before_rec, before_pool = (snapshot(fleet.tmp), fleet.record_state(),
                                             fleet.pool_state())
        fleet.run([verb, cli.DRY_RUN, *argv])
        self.assertEqual(fleet.record_state(), before_rec, f"{verb} --dry-run wrote a record")
        self.assertEqual(fleet.pool_state(), before_pool, f"{verb} --dry-run moved a lease")
        after = snapshot(fleet.tmp)
        self.assertEqual(sorted(after), sorted(before_fs), f"{verb} --dry-run created a path")
        self.assertEqual(after, before_fs, f"{verb} --dry-run touched the tree (mtimes included)")
        self.assertEqual(fleet.started, [], f"{verb} --dry-run started a session")


class TestEveryExitPathIsRegistered(Loaded):
    """Generated over `VERBS`. A tick that branches on an exit code must be told when a new one appears."""

    def check(self, verb):
        fleet = self.loaded()
        argv = self.argv_for(fleet)[verb]
        allowed = cli.registered_codes(verb)
        cells = [[verb, *argv], [verb, "--not-a-flag"], [verb, "--porcelain", *argv]]
        if any(flag.required for flag in cli.VERBS[verb].flags):
            cells.append([verb])
        for cell in cells:
            code, out, err = fleet.run(cell)
            self.assertIn(code, allowed,
                          f"{' '.join(cell)} returned {code}; {verb} may return {sorted(allowed)}")
            self.assertIn(code, cli.EXIT_CODES_ALL)
            if verb != cli.PANE_GUARD:
                # Every verb but the one FD-10 documents an extension for answers out of the ONE
                # registry in `fleet/__init__`, additive only.
                self.assertIn(code, EXIT_CODES,
                              f"{' '.join(cell)} returned {code}, which is not in the base registry")


# --- property 4: every emitted marker is unique ----------------------------------------------------


def markers_by_module() -> dict:
    """`{module: {value: {names}}}` for every UPPER_SNAKE module constant holding a marker literal."""
    out = {}
    for path in sorted(PKG.glob("*.py")):
        found = {}
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or not _CONST.match(target.id):
                continue
            if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
                continue
            value = node.value.value
            if not _MARKER.match(value):
                continue
            found.setdefault(value, set()).add(target.id)
        out[path.stem] = found
    return out


class TestMarkersAreUnique(unittest.TestCase):
    """`OBS-44`: *a marker two things share is not a marker.* `FI-1` is this build's own instance — the
    first run of the live-store check flagged the checker, because the banned strings were in its source.

    Generated per module, and then once across modules: within a module, one marker value may be bound to
    exactly one name; across modules, a shared value must be the SAME name (`POPULATION`/`INFO` are one
    vocabulary deliberately spelled twice, not two markers that collide)."""

    def check(self, module):
        for value, names in sorted(markers_by_module()[module].items()):
            self.assertEqual(len(names), 1,
                             f"{module}: the marker {value!r} is bound to {sorted(names)} — a marker "
                             "two things share is not a marker")

    def test_no_marker_value_carries_two_different_names_across_the_package(self):
        by_value = {}
        for module, found in markers_by_module().items():
            for value, names in found.items():
                by_value.setdefault(value, set()).update(names)
        collisions = {value: sorted(names) for value, names in by_value.items() if len(names) > 1}
        self.assertEqual(collisions, {},
                         f"one marker value, two constant names: {collisions}")


# --- property 5: one liveness implementation, by AST ----------------------------------------------


class TestOneLivenessPerModule(unittest.TestCase):
    """`FI-12`: the text version of this check counted a DOCSTRING that explained the rule, which is the
    third instance in this build of `OBS-44`'s family. Structure, not text."""

    def check(self, module):
        path = PKG / f"{module}.py"
        defs = [node.name for node in ast.walk(ast.parse(path.read_text()))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "alive"]
        self.assertLessEqual(len(defs), 1, f"{module} implements liveness {len(defs)} times")

    def test_the_package_defines_liveness_exactly_once(self):
        defs = []
        for path in sorted(PKG.glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "alive":
                    defs.append(path.stem)
        self.assertEqual(len(defs), 1, f"liveness is implemented in {defs}, not exactly once")


# --- property 7: every checker emits a population row ---------------------------------------------


def discovered_checkers() -> set:
    """`{module.function}` for every function in the package whose name is a checker's name."""
    out = set()
    for path in sorted(PKG.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.FunctionDef) and node.name in CHECKER_NAMES:
                out.add(f"{path.stem}.{node.name}")
    return out


class TestEveryCheckerReportsItsPopulation(Loaded):
    """§9: *never silent about a population it could not cover.* `OBS-49`: a check whose scope narrows
    silently reads as a pass. The checker set is DISCOVERED, so a checker added later fails this file
    rather than escaping it."""

    def rows_of(self, name, fleet):
        instant = fleet.paths["readyWorker"]
        if name == "layout.validate":
            return [(row.rule, row.detail) for row in layout_validate(instant)]
        if name == "profiles.lint":
            return [(row.rule, row.detail) for row in profiles_lint(Profile.load(fleet.profile()))]
        if name == "roadmap.report":
            return [(row.kind, row.detail) for row in Roadmap(instant).report()]
        if name == "harvest.lint":
            return [(row.rule, row.detail) for row in fleet.harvest.lint(fleet.store)]
        if name == "harvest.report":
            return [(row.kind, row.detail) for row in fleet.harvest.report(now=NOW)]
        self.fail(f"{name} is a discovered checker with no entry in this table: add one, because a "
                  "checker nobody exercises is a checker with no population row")

    def check(self, name):
        fleet = self.loaded()
        rows = self.rows_of(name, fleet)
        self.assertTrue(rows, f"{name} produced no rows at all")
        kinds = {kind for kind, _ in rows}
        self.assertIn("population", kinds, f"{name} emits no population row: {sorted(kinds)}")
        detail = next(detail for kind, detail in rows if kind == "population")
        self.assertRegex(detail, r"\d", f"{name}'s population row states no number: {detail!r}")

    def test_every_checker_verb_emits_a_population_row(self):
        fleet = self.loaded()
        argv = self.argv_for(fleet)
        self.assertTrue(cli.CHECKER_VERBS, "no verb is declared a checker")
        for verb in sorted(cli.CHECKER_VERBS):
            code, out, err = fleet.run([verb, "--porcelain", *argv[verb]])
            kinds = {line.split("\t")[0] for line in out.splitlines()}
            self.assertIn("population", kinds,
                          f"the checker verb {verb} emits no population row: {sorted(kinds)}")


# --- property 8: every alarm-bearing verdict carries both halves of the contract -------------------


class TestEveryAlarmNamesItsClearingConditionAndActor(Loaded):
    """§9: *escalation is permitted iff a clearing action exists and is named in the same output*, and
    *"not yours to clear" is a state, not a failure* — so the ACTOR is required as well as the condition.
    Derived from the alarm-bearing types in `guards`, `roadmap` and `review`, never hand-listed."""

    def refusals_of(self, module, fleet) -> list:
        instant = fleet.paths["readyWorker"]
        if module == "guards":
            # Every Guard subclass, forced to refuse: cap 0 refuses WipCap, a compaction refuses
            # exclusivity, a mismatched profile refuses agreement, a full pool refuses capacity.
            fleet.worker("foldTheStack", optype="compact", slot="ws4")
            ctx = Context(store=fleet.store, pool=fleet.pool, sessions=fleet.sessions,
                          instants_dir=fleet.instants, base=OURS, cap=0,
                          profile=str(fleet.profile("compaction")), optype="append")
            out = [guard.evaluate(ctx) for guard in guards_for(ctx)]
            out += [v for v in evaluate_all(ctx, "dispatch")]
            return [v for v in out if not v.allowed]
        if module == "roadmap":
            # A PENDING PROPOSAL is the attention-bearing row here, and it is the right fixture rather
            # than merely an available one: its `clears_who` is the coordinator, which is exactly the
            # "named actor" this contract is about, and it is central to the protocol instead of
            # incidental to it. The previous fixture used `reassign`, removed with the deferred-owner
            # machinery (`SD-5`) — a contract whose only way to produce an alarm is a feature nobody can
            # reach was one deletion away from asserting nothing.
            roadmap = Roadmap(instant)
            roadmap.add(Milestone(id="RI-99", title="an unstarted item", status="blocked",
                                  deps=[], evidence=[]))
            roadmap.propose(instant, "RI-99", "done", ["evidence/INDEX.md"])
            return [row for row in roadmap.report() if row.severity == "attention"]
        if module == "review":
            out = [Review(fleet.paths["solo"], now=lambda: NOW).gate()]          # undecidable
            out.append(Review(instant, now=lambda: NOW).gate(require_scope="all", harvest=True))
            blocked = fleet.worker("notReady", slot=None)
            Review(blocked, now=lambda: NOW).add_round(
                "code", "NOT-READY", [Finding(id="F-9", severity="Critical", status="open",
                                              location="src/fleet/cli.py",
                                              finding="a trailing flag hangs", action="fix the loop")])
            out.append(Review(blocked, now=lambda: NOW).gate())
            return [v for v in out if not v.allowed]
        self.fail(f"{module} is alarm-bearing with no entry in this table")

    def check(self, module):
        fleet = self.loaded()
        refusals = self.refusals_of(module, fleet)
        self.assertTrue(refusals, f"{module} produced no refusal: this assertion would be vacuous")
        for item in refusals:
            label = getattr(item, "guard", None) or getattr(item, "kind", "?")
            self.assertTrue((item.clears_when or "").strip(),
                            f"{module}'s {label} alarm names no clearing CONDITION: {item}")
            self.assertTrue((item.clears_who or "").strip(),
                            f"{module}'s {label} alarm names no clearing ACTOR: {item}")

    def test_the_alarm_bearing_modules_are_the_ones_declaring_the_two_fields(self):
        # Derived: a module whose types carry `clears_when` is alarm-bearing, so a fourth one added
        # later fails here instead of quietly shipping an unclearable alarm.
        bearing = set()
        for path in sorted(PKG.glob("*.py")):
            if "clears_when" in path.read_text():
                bearing.add(path.stem)
        self.assertTrue({"guards", "roadmap", "review"} <= bearing)
        # `errors`, `pool`, `harvest` raise or report their own alarms and are covered by their own
        # suites; `render` and `cli` only TRANSPORT the two fields. `release_verify` raises exactly one
        # `Refused` with both fields — the release that records no `source_repo`, so there is no
        # repository to take a verification worktree from (`II-7`) — and it is covered by
        # `test_release.VerifyCase`. The three producers of a `Verdict` or an attention `Row` are the
        # population this file generates over.
        carriers = {"errors", "pool", "harvest", "render", "cli", "release_verify"}
        self.assertEqual(bearing - {"guards", "roadmap", "review"} - carriers, set(),
                         "a module carries clears_when and is not covered by this file's table")


# --- property 9: every prescribed remedy names a verb that EXISTS ---------------------------------


#: A backticked `fleet <token>` anywhere in the package. Backticked, because that is how this package
#: quotes a command a reader is expected to type — prose about "the fleet infrastructure" is not a remedy.
_PRESCRIBED = re.compile(r"`fleet ([a-z][a-zA-Z-]*)")


def prescribed_verbs() -> dict:
    """`{module: {verb: [line numbers]}}` for every command this package tells a reader to run."""
    out = {}
    for path in sorted(PKG.glob("*.py")):
        found = {}
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            for verb in _PRESCRIBED.findall(line):
                found.setdefault(verb, []).append(lineno)
        out[path.stem] = found
    return out


class TestEveryPrescribedRemedyNamesADeclaredVerb(unittest.TestCase):
    """`FI-19a`/`W2-20`: `workspace.golden()` prescribed `fleet golden --set <path>` and there is no
    `golden` verb — the verb is `set-golden --path`. A message naming a non-existent remedy is the tool
    disagreeing with its own usage, and the operator's next command then fails for a second reason.

    Generated per module over the whole package, because the defect is not "this one message": every
    refusal in here quotes a command, and one hand-typed verb name is all it takes."""

    def check(self, module):
        found = prescribed_verbs()[module]
        for verb, lines in sorted(found.items()):
            if verb not in cli.VERBS:
                self.fail(f"{module}.py:{lines} prescribes `fleet {verb}`, which is not one of the "
                          f"{len(cli.VERBS)} declared verbs: {', '.join(sorted(cli.VERBS))}")

    def test_the_package_prescribes_commands_at_all(self):
        # The generated cases above are vacuous if nothing quotes a command anywhere.
        every = {verb for found in prescribed_verbs().values() for verb in found}
        self.assertGreaterEqual(len(every), 4,
                                f"only {sorted(every)} is prescribed anywhere: this property is vacuous")


# --- generation ------------------------------------------------------------------------------------


def _attach(cls, name, *args):
    def method(self, _args=args):
        self.check(*_args)
    method.__name__ = name
    method.__doc__ = f"{cls.__name__}: {name}"
    setattr(cls, name, method)


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_")


for _verb, _spec in sorted(cli.VERBS.items()):
    for _flag in _spec.flags:
        _tail = f"{_safe(_verb)}__{_safe(_flag.name)}"
        _attach(TestEveryFlagLastWithNoValue, f"test_last_with_no_value_{_tail}", _verb, _flag)
        _attach(TestEveryFlagInUsage, f"test_in_usage_{_tail}", _verb, _flag)
    _attach(TestEveryExitPathIsRegistered, f"test_exit_codes_of_{_safe(_verb)}", _verb)
    if not _spec.read_only:
        _attach(TestEveryMutatingVerbDryRuns, f"test_zero_delta_{_safe(_verb)}", _verb)

for _module in sorted(p.stem for p in PKG.glob("*.py") if p.stem != "__init__"):
    _attach(TestMarkersAreUnique, f"test_markers_unique_in_{_module}", _module)
    _attach(TestOneLivenessPerModule, f"test_one_liveness_in_{_module}", _module)
    _attach(TestEveryPrescribedRemedyNamesADeclaredVerb, f"test_prescribed_verbs_in_{_module}", _module)

for _checker in sorted(discovered_checkers()):
    _attach(TestEveryCheckerReportsItsPopulation, f"test_population_row_of_{_safe(_checker)}", _checker)

for _module in ("guards", "roadmap", "review"):
    _attach(TestEveryAlarmNamesItsClearingConditionAndActor,
            f"test_alarm_contract_of_{_module}", _module)


if __name__ == "__main__":
    unittest.main()


class TestEveryVerbIsDocumentedWhereUsersLook(unittest.TestCase):
    """`G-6` — eight release verbs shipped, four releases were promoted through them, and not one
    appeared in the document that carries the verb surface.

    `skills/using-fleet/SKILL.md` has a read-only table and a mutating table listing every other verb.
    `release-cut`, `-verify`, `-promote`, `-deploy`, `-rollback`, `-status`, `-list` and `-history` were
    in neither, nor in `fleet/CLAUDE.md`, nor in the root `CLAUDE.md`. The only writing about the
    pipeline was its design spec and implementation plan — artifacts that record what was DECIDED, not
    how to use it.

    This is `SI-19`'s shape, which this package already has a name for: a correct, tested, DEAD public
    surface. `SI-26` records the same thing happening to `Roadmap.add`, which *"had always existed, been
    locked and been tested; it had no verb, so from a command line the replacement was unreachable"*.
    Here it is one step worse than unreachable — it is reachable, it has shipped four releases, and the
    next person has to read the source to find it.

    Nothing checked this, which is why it went unnoticed. Derived from `cli.VERBS` so a verb added later
    cannot escape the documentation the way these eight did.
    """

    SKILL = pathlib.Path(__file__).resolve().parents[2] / "skills" / "using-fleet" / "SKILL.md"

    def test_every_verb_appears_in_the_using_fleet_verb_surface(self):
        from fleet.cli import VERBS
        self.assertTrue(self.SKILL.is_file(), f"the skill moved from {self.SKILL}")
        text = self.SKILL.read_text()
        missing = sorted(v for v in VERBS if f"`fleet {v}`" not in text)
        self.assertEqual(missing, [],
                         f"{len(missing)} verb(s) exist and are documented nowhere a user looks: "
                         f"{missing}. A shipped verb absent from the verb surface is SI-19's dead public "
                         f"surface — reachable, tested, and undiscoverable.")

    def test_the_skill_documents_no_verb_that_does_not_exist(self):
        """The other direction, and it is not symmetric decoration: a doc naming a verb the parser does
        not declare sends a reader to a refusal, which is exactly `FI-11` defect 1 — the close-out block
        told coordinators to run `close --instant`, a flag `close` does not have."""
        import re
        from fleet.cli import VERBS
        named = set(re.findall(r"`fleet ([a-z][a-z-]*)`", self.SKILL.read_text()))
        phantom = sorted(named - set(VERBS))
        self.assertEqual(phantom, [],
                         f"the skill documents verb(s) that do not exist: {phantom}")
