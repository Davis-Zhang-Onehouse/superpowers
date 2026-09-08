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
import dataclasses
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from fleet import (EXIT_ATTENTION, EXIT_BAD_INPUT, EXIT_CODES, EXIT_NO_CAPACITY, EXIT_OK,
                   EXIT_REFUSED)
from fleet import cli
from tests import hermetic_environment
from fleet import seedcheck
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

#: `FI-255`/`i39`. A busy claude pane with a `Monitor` armed. The status line is TRANSCRIBED FROM A LIVE
#: CAPTURE (`i39` `evidence/02-red/pane-AFTER-monitor.txt`) and not composed here: a decoy invented at
#: authoring time tests the author's imagination, and this one exists to keep matching what the harness
#: actually draws. Note that `BUSY_PANE` above is deliberately NOT watched — busy and watched are
#: independent, `declare` runs inside the claimant's own turn so every claimant is busy, and a fixture
#: that conflated them would make the gate untestable.
WATCHED_PANE = "\n".join([
    "editing src/fleet/cli.py", "Thinking...",
    "  ⏵⏵ auto mode on · 1 monitor · esc to interrupt · ← for agents · ↓ to manage"])
#: The other shape the indicator takes: a background shell rather than a monitor.
WATCHED_PANE_SHELL = "\n".join([
    "running the build", "Thinking...",
    "  ⏵⏵ auto mode on · 1 shell · esc to interrupt · ← for agents · ↓ to manage"])

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


class HeadsFakeGit(FakeGit):
    """`FakeGit` whose `rev-parse HEAD` answer is keyed by the repo directory's basename and may be changed
    mid-test, so a review round and a later "commit" can be told apart."""

    def __init__(self, heads=None, **kw):
        super().__init__(**kw)
        self.heads = dict(heads or {})

    def __call__(self, args, cwd=None):
        args = list(args)
        if args[:2] == ["rev-parse", "HEAD"] and cwd is not None:
            sha = self.heads.get(pathlib.Path(cwd).name)
            if sha is None:
                return 128, ""
            return 0, sha + "\n"
        return super().__call__(args, cwd)


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
        #: `SI-59`. `socket` is which server this fixture's probes speak for; `elsewhere` maps another
        #: server's socket name to the sessions living on it, and is empty unless a case says otherwise.
        self.socket = "fixture-server"
        #: socket -> {session name: (pid, cwd, pane)}. Rich enough to BE a server: a reader that follows a
        #: record to another server has to get liveness and a pane back from it, not just a yes/no.
        self.elsewhere = {}
        self.killed_elsewhere = []
        probes = Probes(
            list_processes=lambda: [] if self.live_sessions_fail else list(self.procs),
            capture_pane=lambda name: None if name in self.capture_fails else self.panes.get(name, ""),
            has_session=lambda name: name in self.tmux_live,
            start_session=lambda name, cwd, cmd: self.started.append((name, str(cwd), cmd)),
            kill_session=self._kill,
            #: `SI-59`. The fixture IS a server, and it has a name — `elsewhere` is the fixture's model of
            #: another one. A session on this server answers with this socket; a session the fixture has
            #: put `elsewhere` answers with that socket and with nothing on this one, which is exactly the
            #: shape a record dispatched before a socket rename has.
            socket=self.socket,
            session_servers=lambda name: ([self.socket] if name in self.tmux_live else [])
                                         + sorted(s for s, names in self.elsewhere.items()
                                                  if name in names))
        self.layer_for = self._layer_for
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

    def new_root(self, name: str = "freshRoot") -> pathlib.Path:
        """A directory under this fixture's `$HOME` that is not yet a root. `root-init` marks it."""
        made = self.tmp / name
        made.mkdir(exist_ok=True)
        return made

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
            "# {{TITLE}}\n\nRun `fleet declare --instant \"$INSTANT\" --phase awaiting-ci` when CI is queued.\n")
        (path / "seed.txt").write_text(
            "Read CHARTER.md. Run `fleet declare --instant \"$INSTANT\" --phase awaiting-ci`.\n")
        return path

    def _layer_for(self, socket):
        """A `SessionLayer` speaking for one of the fixture's OTHER servers.

        The real factory builds `default_probes(tmux_socket=…)`; this builds the same shape over
        `self.elsewhere`, so a case can assert what a reader learns by following a record to the server it
        names — which is a different question from whether the session exists somewhere.
        """
        if socket == self.socket or not socket:
            return self.sessions
        living = self.elsewhere.get(socket, {})
        return SessionLayer(Probes(
            list_processes=lambda: [LiveSession(pid=pid, cwd=cwd, name=n)
                                    for n, (pid, cwd, _) in sorted(living.items())],
            capture_pane=lambda n: living[n][2] if n in living else None,
            has_session=lambda n: n in living,
            start_session=lambda n, cwd, cmd: None,
            #: A REAL kill: it records where the kill landed and removes the session. A no-op here would
            #: let "close acted on the right server" pass on a fixture where nothing can be acted on.
            kill_session=lambda n: (self.killed_elsewhere.append((socket, n)), living.pop(n, None))[1],
            socket=socket,
            session_servers=lambda n: [socket] if n in living else []))

    def worker(self, name, *, optype="append", state="inflight", pane=BUSY_PANE, live=True,
               base=OURS, slot=None, launched=True, runbook=RUNBOOK, handoff="Updated: now\n",
               server=None):
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
            tmux_socket=server or "", dispatched_at=NOW, launched_at=NOW if launched else None))
        if slot:
            self.pool.claim(todo_id=todo_id, tmux=tmux, base_instant=base,
                            child_instant=str(path), slot=slot)
        if server is not None:
            #: `SI-59`. Dispatched on ANOTHER tmux server: the process is running and visible to `pgrep`,
            #: and its session answers on that server and on no other. Nothing here is on THIS server —
            #: which is the whole point, and the state a record dispatched before a socket rename is in.
            self.elsewhere.setdefault(server, {})[tmux] = (1000 + self._n, path, pane)
            #: NOT in `procs` either, and that is the machine's own behaviour rather than a simplification:
            #: `list_processes` joins `pgrep` to tmux PANE OWNERSHIP, and pane ownership can only be read
            #: from the server the pane is on. Pointed at the wrong one, a live worker is invisible to the
            #: liveness probe as well as to `has-session` — which is how a running worker gets reported
            #: DEAD rather than merely unreachable.
        elif live:
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
                           git=self.git, runner=self.runner, live_work=True,
                           #: `SI-59`. The fixture models a box with more than one tmux server, so the
                           #: context it builds has to know how to reach the others — otherwise a case
                           #: about following a record's address measures a context that cannot.
                           layer_for=self.layer_for)

        return build

    def run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        #: The environment is the fixture's, never the operator's. `cli.main` reads `os.environ` at parse
        #: time, so without this the suite measured whatever the person running it had exported — 33 cases
        #: passed on an ambient `FLEET_HOME` and failed inside `release-verify`, which runs with it unset.
        with hermetic_environment(self.instants, home=self.tmp):
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
        #: `SI-55`. `seed-delivered` compares what was sent against the seed `dispatch` rendered, so its
        #: row needs BOTH to exist — created here rather than assumed, because every mutating row in this
        #: table has to be admissible or `--dry-run`'s zero-delta case never reaches a side effect.
        rendered_seed = fleet.paths["solo"] / ".fleet" / "seed.txt"
        rendered_seed.parent.mkdir(parents=True, exist_ok=True)
        rendered_seed.write_text("Read CHARTER.md. This is the matrix row's rendered briefing.\n")
        was_sent = fleet.tmp / "matrix-delivered.txt"
        was_sent.write_text(rendered_seed.read_text())
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
            #: A fresh directory under the fixture's `$HOME` — which the fixture sets to its own tmp, so
            #: this drives the verb for REAL rather than tripping its "outside $HOME" refusal. Nothing
            #: else in the table needs a home directory; this verb is defined in terms of one.
            "root-init": ["--path", str(fleet.new_root()), "--name", "fixtureRoot"],
            "enroll": ["--slot", str(fleet.spare())],
            "unenroll": ["--slot", "ws8"],
            "reap": ["--base", OURS],
            "set-golden": ["--path", str(fleet.slots_dir)],
            "board": [],
            "status": ["--id", fleet.ids["solo"]],
            "leases": [],
            #: Read-only and argument-free. It shells out to `claude agents --json`; where that binary
            #: is absent the verb REFUSES (`PeersUnavailable` -> `EXIT_ATTENTION`) rather than
            #: reporting an empty peer set, which is the fail-closed behaviour it exists to provide.
            "peers": [],
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
            "seed-delivered": ["--id", fleet.ids["solo"], "--delivered", str(was_sent)],
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



class TestTheSuiteDoesNotReadTheOPERATORsEnvironment(CliCase):
    """The suite was measured NOT being hermetic, and the way it was measured is the reason this class
    exists rather than a comment.

    `cli.main` reads `os.environ` at parse time — `require_named_instants` asks whether the caller named
    where instants are created — while the fixture states the same fact by handing `Ctx` an
    `instants_dir`. Nothing made those two tiers agree. 33 cases passed on this box because the operator's
    shell exported `FLEET_HOME`, and the SAME 33 failed inside `release-verify`, which runs the suite with
    `env -u FLEET_HOME`. A green suite and a red release gate over one tree.

    A test that passes because of what the person running it exported is not measuring the product.
    """

    def test_a_creating_verb_works_with_a_HOSTILE_ambient_environment(self):
        """Every `FLEET_*` set to somewhere that must never be written. If any of them reached the verb,
        the dispatch would either be admitted for the wrong reason or plant a child outside the fixture."""
        fleet = self.loaded()
        poison = pathlib.Path("/nonexistent-fleet-store-that-must-never-be-touched")
        hostile = {"FLEET_HOME": str(poison), "FLEET_INSTANTS": str(poison / "instants"),
                   "FLEET_RELEASES": str(poison / "releases"), "FLEET_TMUX_SOCKET": "not-our-server",
                   "FLEET_ROOT": str(poison)}

        with mock.patch.dict(os.environ, hostile):
            code, out, err = fleet.run(["dispatch", "--porcelain", "--profile",
                                        str(fleet.profile("worker")), "--title", "hostileEnvWorker",
                                        "--base", "00000000", "--optype", "append"])

        self.assertEqual(EXIT_OK, code, f"an ambient environment changed the verdict: {err}")
        child = [line.split("\t")[1] for line in out.splitlines() if line.startswith("instant\t")][0]
        self.assertTrue(str(child).startswith(str(fleet.instants)),
                        f"the child landed outside the fixture's instants directory: {child}")
        self.assertFalse(poison.exists(), "the ambient store was reached")

    def test_a_creating_verb_works_with_NO_fleet_variables_at_all(self):
        """The other direction, and the one `release-verify` runs: nothing exported anywhere."""
        fleet = self.loaded()
        with mock.patch.dict(os.environ, {}, clear=False):
            for name in ("FLEET_HOME", "FLEET_INSTANTS", "FLEET_RELEASES", "FLEET_TMUX_SOCKET",
                         "FLEET_ROOT"):
                os.environ.pop(name, None)
            code, out, err = fleet.run(["dispatch", "--porcelain", "--profile",
                                        str(fleet.profile("worker")), "--title", "bareEnvWorker",
                                        "--base", "00000000", "--optype", "append"])

        self.assertEqual(EXIT_OK, code, f"the suite needs a variable the release gate does not set: {err}")

    def test_the_helper_clears_every_variable_it_lists(self):
        """`FLEET_ENV` is a hand-written list and the defect it guards was ONE unlisted variable reaching
        a test. Derived here from the module's own constant so the list and the clearing cannot drift."""
        from tests import FLEET_ENV
        fleet = self.loaded()
        with mock.patch.dict(os.environ, {name: "leaked" for name in FLEET_ENV}):
            with hermetic_environment(fleet.instants):
                left = {name: os.environ.get(name) for name in FLEET_ENV
                        if os.environ.get(name) == "leaked"}
        self.assertEqual({}, left, f"these variables survived into the fixture's environment: {left}")


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
        #: This case is about the ECHO, not the watcher gate — so it arms one rather than sidestepping the
        #: gate, and states why. `awaiting-ci` is the phase whose normalisation this test exists to check.
        fleet.panes["dt-readyWorker"] = WATCHED_PANE

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

    # ---- `SI-54`: keyed the way every other verb is keyed ------------------------------------------

    def test_pane_guard_answers_about_a_RECORD_when_given_one(self):
        """`SI-54`. This was the only verb on the surface keyed on `--pane <session>`; `close`, `harvest`,
        `status` and `seed-check` all take `--id <todo>`. The two differ by a timestamp suffix, so the
        natural transcription is wrong — and the answer to a wrong pane name is `13`, whose detail reads
        *"no live process and no session answer"*: a sentence about a HEALTHY worker that reads as a dead
        one. This is the verb an external monitor calls before every send (`FD-10`), so its argument is
        retyped more often than any other and its failure mode is the one that most looks like a finding.
        """
        fleet = self.loaded()
        fleet.panes["dt-solo"] = IDLE_PANE

        by_id, out, err = fleet.run(["pane-guard", "--porcelain", "--id", fleet.ids["solo"]])
        by_pane, out2, _ = fleet.run(["pane-guard", "--porcelain", "--pane", "dt-solo"])

        self.assertEqual(cli.PANE_SAFE, by_id, f"--id did not reach the record's pane: {out}{err}")
        self.assertEqual(by_pane, by_id, "the same pane answers differently by --id and by --pane")
        printed = dict(line.split("\t", 1) for line in out.splitlines())
        self.assertEqual("dt-solo", printed.get("pane"),
                         f"the answer does not name the pane it resolved to: {out!r}")

    def test_pane_guard_by_id_reports_the_same_non_safe_codes(self):
        """The codes are the contract (`FD-10`); only how the pane is NAMED changes."""
        fleet = self.loaded()
        fleet.worker("queuedById", slot="ws4", pane=QUEUED_PANE)

        code, out, err = fleet.run(["pane-guard", "--porcelain", "--id", fleet.ids["queuedById"]])

        self.assertEqual(cli.PANE_QUEUED_TEXT, code, f"{out}{err}")
        printed = dict(line.split("\t", 1) for line in out.splitlines())
        self.assertTrue(printed.get("queued_text"),
                        f"the queued text field is empty on the --id path: {out!r}")

    def test_a_record_that_names_no_session_says_so_instead_of_answering_13(self):
        """`13` means *this pane does not exist*. A record with no session at all is a different fact with
        a different remedy, and collapsing them is how a healthy fleet reads as a dead one."""
        fleet = self.loaded()
        fleet.worker("noSession", live=False)
        record = fleet.store.read(fleet.ids["noSession"])
        record.tmux = ""
        fleet.store.write(record)

        code, out, err = fleet.run(["pane-guard", "--id", fleet.ids["noSession"]])

        self.assertEqual(EXIT_BAD_INPUT, code,
                         f"a record with no session was answered with a pane code: {out}{err}")
        #: `parse` refuses an undeclared flag with the same exit code, so without this the case passes
        #: before `--id` exists at all.
        self.assertNotIn("is not a flag", err, f"vacuous: --id is undeclared: {err!r}")
        self.assertNotIn(str(cli.PANE_UNKNOWN), out,
                         f"the unknown-pane code was reported for a record that names no pane: {out!r}")

    def test_naming_both_a_pane_and_a_record_is_refused(self):
        """Two identifiers that could disagree is a third failure mode. Neither is not a question."""
        fleet = self.loaded()

        code, out, err = fleet.run(["pane-guard", "--pane", "dt-solo", "--id", fleet.ids["solo"]])

        self.assertEqual(EXIT_BAD_INPUT, code, f"both identifiers were accepted: {out}")
        self.assertNotIn("is not a flag", err, f"vacuous: --id is undeclared: {err!r}")
        self.assertIn("--id", err)
        self.assertIn("--pane", err)

    def test_naming_neither_is_refused_and_the_refusal_names_both_flags(self):
        fleet = self.loaded()

        code, out, err = fleet.run(["pane-guard"])

        self.assertEqual(EXIT_BAD_INPUT, code, f"pane-guard ran with no subject: {out}")
        self.assertIn("--pane", err)
        self.assertIn("--id", err)

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


class TestRecordingASendKeysDelivery(CliCase):
    """`SI-55`. The positive verdict was reachable by exactly one route — the briefing appearing in
    `/proc/<pid>/cmdline` — and a seed delivered by `send-keys` never appears in argv at all.

    So a worker rescued by `reviving-dead-panes` read `NOT-DELIVERED` for the life of its instant while a
    sibling dispatched through a launcher read `VERIFIED`, and `NOT-DELIVERED`'s own detail says, truly,
    that it is neither evidence of a problem nor evidence of correctness. A row that can never change is a
    row that stops being read (`FI-402`).

    What the deliverer can supply that is EVIDENCE and not a claim is the bytes it sent. `fleet` digests
    them and compares against what it rendered, which catches the class this module exists for — the
    launcher sent the wrong file.
    """

    SEED = ("Read CHARTER.md before anything else. " * 12) + "\nThen run `fleet brief`.\n"

    def _briefed(self, fleet, name="solo"):
        instant = fleet.paths[name]
        seed = instant / ".fleet" / "seed.txt"
        seed.parent.mkdir(parents=True, exist_ok=True)
        seed.write_text(self.SEED)
        return instant, seed

    def _sent(self, fleet, text):
        path = fleet.tmp / "sent.txt"
        path.write_text(text)
        return path

    def test_a_recorded_delivery_is_stored_in_the_instant(self):
        fleet = self.loaded()
        instant, _ = self._briefed(fleet)
        sent = self._sent(fleet, self.SEED)

        code, out, err = fleet.run(["seed-delivered", "--porcelain", "--id", fleet.ids["solo"],
                                    "--delivered", str(sent)])

        self.assertEqual(EXIT_OK, code, err)
        recorded = seedcheck.read_delivery(instant)
        self.assertIsNotNone(recorded, "nothing was written into the instant")
        self.assertEqual(seedcheck.digest(self.SEED), recorded.rendered_md5)
        self.assertEqual("send-keys", recorded.channel)

    def test_seed_check_reports_the_recorded_delivery_as_its_own_positive_state(self):
        fleet = self.loaded()
        self._briefed(fleet)
        sent = self._sent(fleet, self.SEED)
        code, _, err = fleet.run(["seed-delivered", "--id", fleet.ids["solo"], "--delivered", str(sent)])
        self.assertEqual(EXIT_OK, code, err)
        #: The pane pid has to be observable or `seed-check` reports `unreadable` and never classifies —
        #: and the argv it reads must be a claude process carrying NO briefing, which is exactly what a
        #: send-keys delivery leaves behind.
        fleet.sessions.probes.pane_pid = lambda name: 4242 if name in fleet.tmux_live else None
        fake = seedcheck.Probes(read_cmdline=lambda pid: b"claude\0--permission-mode\0auto",
                                comm_of=lambda pid: "claude", children_of=lambda pid: [])

        with mock.patch.object(cli.seedcheck, "default_probes", lambda: fake):
            code, out, err = fleet.run(["seed-check", "--porcelain"])

        self.assertIn(code, EXIT_CODES, err)
        rows = [line.split("\t") for line in out.splitlines()]
        attested = [r for r in rows if r[0] == seedcheck.ATTESTED.lower()]
        self.assertTrue(attested,
                        f"seed-check does not report the recorded delivery at all: {out!r}")
        detail = "\t".join(attested[0])
        self.assertIn("send-keys", detail,
                      f"the row does not name the channel, so it reads like an argv observation: {out!r}")
        self.assertNotIn("not-delivered", [r[0] for r in rows],
                         f"the same session is also reported unverifiable: {out!r}")

    def test_a_delivery_that_does_not_carry_the_rendered_seed_is_REFUSED(self):
        """Compared, not believed. A launcher that sent the wrong file records the wrong file's digest,
        and that is the whole class this check exists for."""
        fleet = self.loaded()
        instant, _ = self._briefed(fleet)
        sent = self._sent(fleet, "some other instant's briefing entirely. " * 12)

        code, out, err = fleet.run(["seed-delivered", "--id", fleet.ids["solo"], "--delivered", str(sent)])

        self.assertEqual(EXIT_BAD_INPUT, code, f"a mismatched delivery was recorded: {out}")
        #: Without this the case passes before the verb exists: an unknown verb exits 2 too.
        self.assertNotIn("is not a fleet verb", err, f"vacuous: the verb is undeclared: {err[:120]!r}")
        self.assertRegex(err, r"(?i)(md5|digest|does not (contain|carry))",
                         f"the refusal does not say the delivered text disagreed: {err!r}")
        self.assertIsNone(seedcheck.read_delivery(instant),
                          "a refused delivery was written anyway, leaving a bad attestation for a later "
                          "reader to discover")

    def test_a_delivery_that_PREPENDS_to_the_seed_is_accepted(self):
        """The same containment rule the argv path uses: a caller may legitimately add a preamble, and
        what must never happen is a DIFFERENT briefing."""
        fleet = self.loaded()
        self._briefed(fleet)
        sent = self._sent(fleet, "Your slot is ws1 and your instant is <path>.\n\n" + self.SEED)

        code, out, err = fleet.run(["seed-delivered", "--id", fleet.ids["solo"], "--delivered", str(sent)])

        self.assertEqual(EXIT_OK, code, err)

    def test_recording_a_delivery_for_an_instant_with_no_rendered_seed_is_refused(self):
        fleet = self.loaded()
        sent = self._sent(fleet, self.SEED)

        code, out, err = fleet.run(["seed-delivered", "--id", fleet.ids["solo"], "--delivered", str(sent)])

        self.assertEqual(EXIT_BAD_INPUT, code,
                         f"a delivery was recorded against nothing to compare it to: {out}")
        self.assertNotIn("is not a fleet verb", err, f"vacuous: the verb is undeclared: {err[:120]!r}")
        self.assertIn("seed.txt", err, f"the refusal does not say what is missing: {err!r}")

    def test_a_re_brief_replaces_the_previous_record(self):
        """`reviving-dead-panes` briefs a rescued worker again; the latest delivery is the one that
        describes the pane. Unlike origin.json, this is not written once."""
        fleet = self.loaded()
        instant, seed = self._briefed(fleet)
        sent = self._sent(fleet, self.SEED)
        self.assertEqual(EXIT_OK, fleet.run(
            ["seed-delivered", "--id", fleet.ids["solo"], "--delivered", str(sent)])[0])
        again = fleet.tmp / "sent2.txt"
        again.write_text("Rescued. Resume where you were.\n\n" + self.SEED)

        code, out, err = fleet.run(["seed-delivered", "--id", fleet.ids["solo"], "--delivered", str(again)])

        self.assertEqual(EXIT_OK, code, err)
        self.assertEqual(seedcheck.digest(again.read_text()),
                         seedcheck.read_delivery(instant).delivered_md5,
                         "the second delivery was not recorded")

    def test_dry_run_records_nothing(self):
        fleet = self.loaded()
        instant, _ = self._briefed(fleet)
        sent = self._sent(fleet, self.SEED)

        code, out, err = fleet.run(["seed-delivered", "--dry-run", "--id", fleet.ids["solo"],
                                    "--delivered", str(sent)])

        self.assertEqual(EXIT_OK, code, err)
        self.assertIsNone(seedcheck.read_delivery(instant), "--dry-run wrote the record")


class TestSeedExtra(CliCase):
    """`SI-53`. The seed window was a race the coordinator kept losing.

    `dispatch` renders the seed, writes it, and starts the worker; the launcher reads it on a ~180s timer.
    A coordinator with one dispatch-specific sentence to add had exactly one place to put it: `seed.txt`,
    AFTER `dispatch` returned and BEFORE the launcher read. Pre-writing is structurally impossible — the
    `i2-dispatch-seed-integrity` control refuses a seed file that exists before the dispatch that renders
    it, correctly, since a pre-written seed cannot contain a seed that does not exist yet.

    `FI-387` lost that race by about a second: the worker started on the briefing without the addition,
    and nothing said so. Putting the addition INSIDE the transaction makes the window zero.
    """

    def _dispatch(self, fleet, *extra, title="extraWorker"):
        return fleet.run(["dispatch", "--porcelain", "--profile", str(fleet.profile("worker")),
                          "--title", title, "--base", "00000000", "--optype", "append", *extra])

    def _seed_of(self, out):
        child = [line.split("\t")[1] for line in out.splitlines() if line.startswith("instant\t")][0]
        return pathlib.Path(child) / ".fleet" / "seed.txt"

    def test_the_addition_is_in_the_seed_the_worker_is_briefed_from(self):
        fleet = self.loaded()
        extra = fleet.tmp / "extra.md"
        extra.write_text("Coordinate with dt-solo before touching the shared fixture.\n")

        code, out, err = self._dispatch(fleet, "--seed-extra", str(extra))

        self.assertEqual(EXIT_OK, code, err)
        seed = self._seed_of(out).read_text()
        self.assertIn("Coordinate with dt-solo", seed,
                      f"the addition never reached the seed the worker is briefed from: {seed!r}")
        self.assertIn("Read CHARTER.md", seed,
                      "the addition REPLACED the profile's seed instead of extending it")

    def test_the_seed_says_where_the_addition_came_from(self):
        """A worker reading two paragraphs that disagree needs to know which one is specific to it."""
        fleet = self.loaded()
        extra = fleet.tmp / "extra.md"
        extra.write_text("Build on the q6d tip, not main.\n")

        code, out, err = self._dispatch(fleet, "--seed-extra", str(extra))

        self.assertEqual(EXIT_OK, code, err)
        seed = self._seed_of(out).read_text()
        self.assertIn(str(extra), seed,
                      f"the seed does not name the file the addition came from: {seed!r}")

    def test_the_delivered_seed_check_compares_the_COMBINED_text(self):
        """Otherwise `--seed-extra` would make every dispatch report NOT-DELIVERED against a seed that no
        longer matches the file — the addition would defeat the integrity control it rides inside."""
        fleet = self.loaded()
        extra = fleet.tmp / "extra.md"
        extra.write_text("Coordinate with dt-solo before touching the shared fixture.\n")
        seen = []

        with mock.patch.object(cli, "_verify_seed_delivery",
                               side_effect=lambda ctx, tmux, seed, **kw: seen.append(seed)):
            code, out, err = self._dispatch(fleet, "--seed-extra", str(extra))

        self.assertEqual(EXIT_OK, code, err)
        self.assertEqual(1, len(seen), "the delivery check was not reached at all: this is vacuous")
        self.assertIn("Coordinate with dt-solo", seen[0],
                      "the delivery check compares against the seed WITHOUT the addition, so a correct "
                      "delivery of the combined briefing would be reported as unverified")
        self.assertEqual(self._seed_of(out).read_text(), seen[0],
                         "the file written and the text checked are not the same seed")

    def test_a_missing_file_is_refused_BEFORE_anything_is_claimed(self):
        fleet = self.loaded()
        held_before = sorted(d.name for d in fleet.pool.leases.iterdir())
        instants_before = sorted(p.name for p in fleet.instants.iterdir())

        code, out, err = self._dispatch(fleet, "--seed-extra", str(fleet.tmp / "nope.md"))

        self.assertEqual(EXIT_BAD_INPUT, code, f"a missing seed addition was accepted: {out}")
        self.assertNotIn("is not a flag", err,
                         f"this passed because --seed-extra is undeclared, not because the file is "
                         f"missing: {err!r}")
        self.assertIn("nope.md", err, f"the refusal does not name the file it could not read: {err!r}")
        self.assertEqual(held_before, sorted(d.name for d in fleet.pool.leases.iterdir()),
                         "a refused dispatch left a slot claimed")
        self.assertEqual(instants_before, sorted(p.name for p in fleet.instants.iterdir()),
                         "a refused dispatch created an instant")

    def test_an_empty_file_is_refused(self):
        """An empty addition is a caller believing something was added. Silence there is the whole defect
        class this flag exists inside."""
        fleet = self.loaded()
        extra = fleet.tmp / "blank.md"
        extra.write_text("   \n\n")

        code, out, err = self._dispatch(fleet, "--seed-extra", str(extra))

        self.assertEqual(EXIT_BAD_INPUT, code, f"an empty seed addition was accepted: {out}")
        self.assertNotIn("is not a flag", err, f"vacuous: --seed-extra is undeclared: {err!r}")

    def test_without_the_flag_the_seed_is_byte_for_byte_what_it_was(self):
        fleet = self.loaded()

        code, out, err = self._dispatch(fleet)

        self.assertEqual(EXIT_OK, code, err)
        seed = self._seed_of(out).read_text()
        self.assertEqual((fleet.profile("worker") / "seed.txt").read_text(), seed,
                         "dispatch without --seed-extra no longer renders what it rendered before")

    def test_dry_run_reports_the_addition_and_writes_nothing(self):
        fleet = self.loaded()
        extra = fleet.tmp / "extra.md"
        extra.write_text("Build on the q6d tip.\n")
        #: Not `snapshot(fleet.tmp)`: the fixture's own `profile()` helper rewrites the profile directory
        #: every time it is called, so a whole-tree snapshot would fail on the harness rather than on the
        #: verb. The tree this verb must not touch is the instants directory, the records and the pool.
        before = snapshot(fleet.instants)
        records, pool = fleet.record_state(), fleet.pool_state()

        code, out, err = self._dispatch(fleet, "--dry-run", "--seed-extra", str(extra))

        self.assertIn(code, EXIT_CODES, err)
        printed = dict(line.split("\t", 1) for line in out.splitlines())
        self.assertIn(str(extra), printed.get("seed_extra", ""),
                      f"--dry-run does not report the addition it would make: {out!r}")
        self.assertEqual(before, snapshot(fleet.instants), "--dry-run created or changed an instant")
        self.assertEqual(records, fleet.record_state(), "--dry-run wrote a record")
        self.assertEqual(pool, fleet.pool_state(), "--dry-run claimed a slot")


class TestAbortReleasesTheClaim(CliCase):
    """`SI-51`. `abort` did everything a completion transaction does except the one thing the roadmap
    needed: it never gave the milestone back.

    `Roadmap.disown` existed, was correct and had exactly one caller — `dispatch`'s rollback — so a
    milestone claimed by a dispatch that was later aborted stayed owned by an `-abort-` folder forever.
    Every documented escape was measured and none worked: `--override` overrides admission rules and not
    ownership, `harvest` refuses an aborted instant, and `abort` refuses to run twice. `claim`'s own
    refusal sent the reader to the remedy that did not work — *"the work is released by aborting it with a
    reason"* — and the live coordinator ended up editing `roadmap.json` by hand nine times, which is the
    single act the two-party protocol exists to prevent.
    """

    def _dispatched_onto(self, fleet, milestone="M9", title="claimant"):
        """Dispatch a real worker onto a real milestone, and hand back (coordinator, child path)."""
        coordinator = fleet.paths["readyWorker"]
        Roadmap(coordinator).add(Milestone(id=milestone, title="carried work", status="blocked",
                                           deps=[], evidence=[]))
        code, out, err = fleet.run(["dispatch", "--porcelain", "--profile", str(fleet.profile("worker")),
                                    "--title", title, "--base", "00000000", "--optype", "append",
                                    "--from", str(coordinator), "--milestone", milestone])
        self.assertEqual(0, code, err)
        child = [line.split("\t")[1] for line in out.splitlines() if line.startswith("instant\t")][0]
        self.assertEqual(child, Roadmap(coordinator).milestone(milestone).owner,
                         "the fixture did not claim the milestone: every assertion below is vacuous")
        return coordinator, pathlib.Path(child)

    def test_aborting_a_claimed_milestone_gives_the_claim_back(self):
        fleet = self.loaded()
        coordinator, child = self._dispatched_onto(fleet)

        code, out, err = fleet.run(["abort", "--porcelain", "--instant", str(child),
                                    "--reason", "the baseline moved under it"])

        self.assertEqual(EXIT_OK, code, err)
        back = Roadmap(coordinator).milestone("M9")
        self.assertIsNone(back.owner,
                          "the aborted instant still owns the milestone: it is now claimed by an "
                          "`-abort-` folder and no verb can release it")
        self.assertIn("the baseline moved under it", back.disowned_reason,
                      f"the release recorded no reason, so the roadmap cannot say what happened: {back}")
        printed = dict(line.split("\t", 1) for line in out.splitlines())
        self.assertEqual("M9", printed.get("milestone"),
                         f"abort does not report the milestone it acted on: {out!r}")
        self.assertTrue((printed.get("milestone_released") or "").startswith("yes"),
                        f"abort does not report that it released the claim: {out!r}")

    def test_abort_leaves_a_milestone_claimed_by_a_DIFFERENT_instant_alone(self):
        """The hazard of putting a roadmap write on `abort`. The origin says M9; the roadmap says M9 is
        being run by somebody else. The abort must still complete — refusing would strand the instant it
        was asked to abandon — and it must not free work a live sibling is doing."""
        fleet = self.loaded()
        coordinator, child = self._dispatched_onto(fleet)
        sibling = str(fleet.paths["solo"])
        roadmap = Roadmap(coordinator)
        roadmap.disown("M9")
        roadmap.claim("M9", sibling)

        code, out, err = fleet.run(["abort", "--porcelain", "--instant", str(child),
                                    "--reason", "wrong worker"])

        self.assertEqual(EXIT_OK, code, f"the abort itself was refused, stranding the instant: {err}")
        self.assertFalse(child.exists(), "the instant was not aborted")
        self.assertEqual(sibling, Roadmap(coordinator).milestone("M9").owner,
                         "abort freed a milestone a different instant is running")
        printed = dict(line.split("\t", 1) for line in out.splitlines())
        released = printed.get("milestone_released", "")
        self.assertTrue(released.startswith("no"),
                        f"abort reported a release it did not perform: {out!r}")
        self.assertIn(sibling, released,
                      f"abort does not say WHOSE claim it left alone, so the reader cannot tell which of "
                      f"the two is stale: {out!r}")

    def test_aborting_an_instant_with_no_coordinator_is_unchanged(self):
        """`fleet init` produces instants with no origin at all, and they must abort exactly as before."""
        fleet = self.loaded()
        instant = fleet.paths["doomed"]
        self.assertIsNone(origin_mod.read(instant), "this fixture is supposed to have no coordinator")

        code, out, err = fleet.run(["abort", "--porcelain", "--instant", str(instant),
                                    "--reason", "unfoldable"])

        self.assertEqual(EXIT_OK, code, err)
        printed = dict(line.split("\t", 1) for line in out.splitlines())
        self.assertEqual("(none)", printed.get("milestone"),
                         f"abort invented a milestone for an instant that has no coordinator: {out!r}")

    def test_a_roadmap_write_that_fails_is_REPORTED_and_the_abort_still_completes(self):
        """`dispatch`'s rollback already answers this shape: never mask the outcome that already happened,
        and name what has to be cleared by hand. The rename is irreversible and has already run."""
        fleet = self.loaded()
        coordinator, child = self._dispatched_onto(fleet)
        (coordinator / ".fleet" / "roadmap.json").write_text("{ not json")

        code, out, err = fleet.run(["abort", "--porcelain", "--instant", str(child),
                                    "--reason", "the roadmap is broken too"])

        self.assertEqual(EXIT_OK, code,
                         f"a failed roadmap write turned the abort itself into a failure: {err}")
        self.assertFalse(child.exists(), "the instant was not aborted")
        self.assertIn("M9", err, f"the milestone that stayed claimed is not named: {err!r}")
        self.assertRegex(err, r"(?i)warn", f"the failure was swallowed rather than reported: {err!r}")


class TestReleasingAStrandedClaim(CliCase):
    """`SI-51`, the other half. Fixing `abort` reaches none of the milestones stranded BEFORE the fix —
    `abort` refuses to run twice, so those instants are already `-abort-` and there is no second pass.

    `--disown` is the repair, and it is on the coordinator's own verb beside `--retire` for the same
    reason: same actor, same file, same authority, and one more verb is one more row in three IT fixture
    matrices (`II-4`).
    """

    def _stranded(self, fleet, owner, milestone="M9"):
        coordinator = fleet.paths["readyWorker"]
        roadmap = Roadmap(coordinator)
        roadmap.add(Milestone(id=milestone, title="carried work", status="blocked", deps=[], evidence=[]))
        roadmap.claim(milestone, str(owner))
        return coordinator

    def test_a_claim_whose_owner_is_gone_can_be_released(self):
        fleet = self.loaded()
        gone = fleet.instants / "00000000-07300099-abort-append-longGone"
        coordinator = self._stranded(fleet, gone)

        code, out, err = fleet.run(["milestone", "--porcelain", "--instant", str(coordinator),
                                    "--id", "M9", "--disown",
                                    "--reason", "aborted before abort released claims"])

        self.assertEqual(EXIT_OK, code, err)
        back = Roadmap(coordinator).milestone("M9")
        self.assertIsNone(back.owner, "the stranded claim was not released")
        self.assertIn("aborted before abort", back.disowned_reason)

    def test_releasing_a_claim_held_by_a_worker_that_is_still_OPEN_is_refused(self):
        """The safety. `claim` refuses two instants on one milestone; a `--disown` that ignored a live
        owner would put the second one there by another door."""
        fleet = self.loaded()
        live = fleet.paths["solo"]
        coordinator = self._stranded(fleet, live)

        code, out, err = fleet.run(["milestone", "--instant", str(coordinator), "--id", "M9",
                                    "--disown", "--reason", "I want the slot"])

        self.assertEqual(EXIT_REFUSED, code, f"a live worker's milestone was released: {out}")
        self.assertIn(str(live), err, f"the refusal does not name the owner it protected: {err!r}")
        self.assertEqual(str(live), Roadmap(coordinator).milestone("M9").owner)

    def test_disown_needs_a_reason(self):
        fleet = self.loaded()
        gone = fleet.instants / "00000000-07300098-abort-append-alsoGone"
        coordinator = self._stranded(fleet, gone)

        code, out, err = fleet.run(["milestone", "--instant", str(coordinator), "--id", "M9", "--disown"])

        self.assertEqual(EXIT_BAD_INPUT, code, f"a reasonless release was accepted: {out}")
        #: `parse` refuses an undeclared flag with the same exit code and appends a usage dump, so the
        #: code alone would pass this test before `--disown` existed at all. The refusal has to be ABOUT
        #: the reason.
        self.assertNotIn("is not a flag", err,
                         f"this passed because --disown is undeclared, not because a reason is required: "
                         f"{err!r}")
        self.assertRegex(err, r"(?i)reason", f"the refusal does not name the missing reason: {err!r}")
        self.assertEqual(str(gone), Roadmap(coordinator).milestone("M9").owner)

    def test_disowning_a_milestone_nobody_claimed_says_so_rather_than_reporting_a_release(self):
        fleet = self.loaded()
        coordinator = fleet.paths["readyWorker"]
        Roadmap(coordinator).add(Milestone(id="M9", title="unclaimed", status="blocked", deps=[],
                                           evidence=[]))

        code, out, err = fleet.run(["milestone", "--instant", str(coordinator), "--id", "M9",
                                    "--disown", "--reason", "tidying"])

        self.assertEqual(EXIT_BAD_INPUT, code,
                         f"releasing a claim that does not exist reported success: {out}")
        self.assertRegex(err + out, r"(?i)(no owner|not claimed|nobody)",
                         f"the answer does not say the milestone was already unowned: {err!r}")

    def test_disown_does_not_write_under_dry_run(self):
        fleet = self.loaded()
        gone = fleet.instants / "00000000-07300097-abort-append-dryGone"
        coordinator = self._stranded(fleet, gone)

        code, out, err = fleet.run(["milestone", "--dry-run", "--instant", str(coordinator), "--id", "M9",
                                    "--disown", "--reason", "rehearsal"])

        self.assertEqual(EXIT_OK, code, err)
        self.assertEqual(str(gone), Roadmap(coordinator).milestone("M9").owner,
                         "--dry-run released the claim")


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


class TestCompleteRefusesBrokenPointers(CliCase):
    """`complete` IS the rename: at gate time every `-inflight-` path still resolves, so checking "does
    this path exist" passes and then breaks one millisecond later. The question the gate must ask is
    whether a pointer SURVIVES the rename, which it answers by refusing any citation of the instant's own
    (about-to-be-renamed) folder name in the two worker-owned navigation documents.

    Measured in three audited instants: `complete` succeeded while `HANDOFF.md` still named the absolute
    `-inflight-` path and `evidence/INDEX.md` still had `*pending*` rows, and each cost an operator round
    trip to discover.
    """

    def ready_to_complete(self, milestone="M9", title="claimant"):
        """Dispatch a real worker onto a real milestone and record a READY review round over it, so the
        pre-existing review gate admits `complete` and the only thing left to trip is the one under test."""
        fleet = self.loaded()
        coordinator = fleet.paths["readyWorker"]
        Roadmap(coordinator).add(Milestone(id=milestone, title="carried work", status="blocked",
                                           deps=[], evidence=[]))
        code, out, err = fleet.run(["dispatch", "--porcelain", "--profile", str(fleet.profile("worker")),
                                    "--title", title, "--base", "00000000", "--optype", "append",
                                    "--from", str(coordinator), "--milestone", milestone])
        self.assertEqual(0, code, err)
        child = pathlib.Path(
            [line.split("\t")[1] for line in out.splitlines() if line.startswith("instant\t")][0])
        code, out, err = fleet.run(["review", "--instant", str(child), "--scope", "all",
                                    "--verdict", "READY",
                                    "--finding", "RV-1:Minor:applied:evidence/INDEX.md:baseline:none"])
        self.assertEqual(EXIT_OK, code, err)
        return types.SimpleNamespace(fleet=fleet, instant=child)

    def test_complete_refuses_a_pointer_the_rename_will_break(self):
        """complete IS the rename, so at gate time every -inflight- path still resolves. Checking 'does
        this path exist' passes and then breaks one millisecond later. The question is whether the
        pointer SURVIVES the rename."""
        env = self.ready_to_complete()
        (env.instant / "HANDOFF.md").write_text(
            "## Resume\n\nRead " + str(env.instant) + "/evidence/INDEX.md first.\n")

        code, out, err = env.fleet.run(["complete", "--instant", str(env.instant)])

        self.assertEqual(EXIT_REFUSED, code, f"complete accepted a pointer naming its own folder: {out}")
        self.assertIn("complete-pointers", err)
        self.assertIn("HANDOFF.md:3", err)
        self.assertTrue(env.instant.exists(), "refused, so the folder was NOT renamed")

    def test_complete_allows_an_instant_relative_pointer(self):
        env = self.ready_to_complete()
        (env.instant / "HANDOFF.md").write_text("## Resume\n\nRead `evidence/INDEX.md` first.\n")

        code, out, err = env.fleet.run(["complete", "--instant", str(env.instant)])

        self.assertEqual(EXIT_OK, code, err)

    def test_complete_refuses_while_the_phase_is_still_awaiting_ci(self):
        env = self.ready_to_complete()
        Declarations(env.instant).set_phase("awaiting-ci")

        code, out, err = env.fleet.run(["complete", "--instant", str(env.instant)])

        self.assertEqual(EXIT_REFUSED, code)
        self.assertIn("fleet declare --phase done", err)


class TestReviewRecordsTheHeadsItReviewed(CliCase):
    """`_reviewed_heads`: a recorded round is bound to the slot HEADs for the repos the record's
    `--lineage-base` names. Without the binding, "a review happened" and "the graded code was reviewed"
    are different facts nothing connects."""

    def _dispatched(self, fleet, lineage_base, milestone="M9", title="claimant"):
        """Dispatch a real worker, optionally with a lineage base, and hand back its instant path.

        Copies `_dispatched_onto`'s argv rather than reusing it, because that helper never passes
        `--lineage-base` and these tests are exactly about the case where it is (and is not) given.
        """
        coordinator = fleet.paths["readyWorker"]
        Roadmap(coordinator).add(Milestone(id=milestone, title="carried work", status="blocked",
                                           deps=[], evidence=[]))
        argv = ["dispatch", "--porcelain", "--profile", str(fleet.profile("worker")),
                "--title", title, "--base", "00000000", "--optype", "append",
                "--from", str(coordinator), "--milestone", milestone]
        if lineage_base:
            argv += ["--lineage-base", lineage_base]
        code, out, err = fleet.run(argv)
        self.assertEqual(0, code, err)
        child = [line.split("\t")[1] for line in out.splitlines() if line.startswith("instant\t")][0]
        return pathlib.Path(child)

    def test_review_records_the_slot_heads_for_the_lineage_repos(self):
        fleet = self.loaded()
        fleet.git = HeadsFakeGit({"alpha": "b" * 40})
        child = self._dispatched(fleet, "alpha=" + "a" * 40)

        rc, out, err = fleet.run(["review", "--instant", str(child), "--scope", "code",
                                  "--verdict", "READY",
                                  "--finding", "RV-1:Minor:applied:SPEC.md:the arm table is complete:none"])

        self.assertEqual(EXIT_OK, rc, err)
        ledger = json.loads((child / ".fleet" / "review.json").read_text())
        self.assertEqual({"alpha": "b" * 40}, ledger["rounds"][0]["heads"])

    def test_review_without_a_readable_slot_records_no_heads(self):
        fleet = self.loaded()
        child = self._dispatched(fleet, "")

        rc, out, err = fleet.run(["review", "--instant", str(child), "--scope", "code",
                                  "--verdict", "READY",
                                  "--finding", "RV-1:Minor:applied:SPEC.md:nothing to bind:none"])

        self.assertEqual(EXIT_OK, rc, err)
        ledger = json.loads((child / ".fleet" / "review.json").read_text())
        self.assertNotIn("heads", ledger["rounds"][0])


class TestProposeDoneRefusesAnUnreviewedHead(CliCase):
    """`propose --status done` refuses when the newest round carrying `heads` disagrees with the slot's
    current HEADs. Measured across five audited workers: four pushed, reviewed, then pushed the fixes —
    a second 3.3h CI wave each time. This gate fires at the earliest moment the tool can see it: the
    claim of done."""

    def _dispatched(self, fleet, lineage_base, milestone="m1", title="claimant"):
        """Dispatch a real worker, optionally with a lineage base, and hand back its instant path.

        Copies `TestReviewRecordsTheHeadsItReviewed._dispatched`'s argv rather than `_dispatched_onto`,
        which never passes `--lineage-base`.
        """
        coordinator = fleet.paths["readyWorker"]
        Roadmap(coordinator).add(Milestone(id=milestone, title="carried work", status="blocked",
                                           deps=[], evidence=[]))
        argv = ["dispatch", "--porcelain", "--profile", str(fleet.profile("worker")),
                "--title", title, "--base", "00000000", "--optype", "append",
                "--from", str(coordinator), "--milestone", milestone]
        if lineage_base:
            argv += ["--lineage-base", lineage_base]
        code, out, err = fleet.run(argv)
        self.assertEqual(0, code, err)
        child = [line.split("\t")[1] for line in out.splitlines() if line.startswith("instant\t")][0]
        return pathlib.Path(child)

    def test_propose_done_refuses_a_head_the_newest_round_never_reviewed(self):
        """trypmod, unaryminus and try-subtree each pushed, then reviewed, then pushed the fixes — a
        second 3.3 h CI wave each time. Grading a head no round has seen is the moment that is visible
        to this tool."""
        fleet = self.loaded()
        fleet.git = HeadsFakeGit({"gluten-internal": "b" * 40})
        child = self._dispatched(fleet, "gluten-internal=" + "a" * 40)

        rc, out, err = fleet.run(["review", "--instant", str(child), "--scope", "all",
                                  "--verdict", "READY",
                                  "--finding", "RV-1:Minor:applied:SPEC.md:reviewed at b:none"])
        self.assertEqual(EXIT_OK, rc, err)

        fleet.git.heads["gluten-internal"] = "c" * 40
        code, out, err = fleet.run(["propose", "--instant", str(child), "--milestone", "m1",
                                    "--status", "done", "--evidence", "evidence/INDEX.md"])

        self.assertEqual(EXIT_REFUSED, code, f"a head no round reviewed was accepted: {out}")
        self.assertIn("review-head", err)
        self.assertIn("c" * 40, err)

    def test_propose_done_allows_a_head_the_newest_round_reviewed(self):
        fleet = self.loaded()
        fleet.git = HeadsFakeGit({"gluten-internal": "b" * 40})
        child = self._dispatched(fleet, "gluten-internal=" + "a" * 40)

        rc, out, err = fleet.run(["review", "--instant", str(child), "--scope", "all",
                                  "--verdict", "READY",
                                  "--finding", "RV-1:Minor:applied:SPEC.md:reviewed at b:none"])
        self.assertEqual(EXIT_OK, rc, err)

        code, out, err = fleet.run(["propose", "--instant", str(child), "--milestone", "m1",
                                    "--status", "done", "--evidence", "evidence/INDEX.md"])

        self.assertEqual(EXIT_OK, code, err)

    def test_propose_done_is_not_gated_when_no_round_carries_heads(self):
        """Every ledger written before this field carries no `heads` key at all. Absence is NOT
        MEASURED, never a mismatch."""
        fleet = self.loaded()
        child = self._dispatched(fleet, "gluten-internal=" + "a" * 40)
        (child / ".fleet" / "review.json").write_text(json.dumps({
            "schema_version": 1,
            "rounds": [{"number": 1, "scope": "all", "verdict": "READY",
                        "at": "2026-07-30T01:00:00Z", "findings": []}],
        }))

        code, out, err = fleet.run(["propose", "--instant", str(child), "--milestone", "m1",
                                    "--status", "done", "--evidence", "evidence/INDEX.md"])

        self.assertEqual(EXIT_OK, code, err)


class TestDeclareAwaitingCiReportsAnUnreviewedHead(CliCase):
    """`declare --phase awaiting-ci` is ADVISORY, never a `Refused` — by declare time the push has already
    happened, and refusing would strand the worker with a running wave it may not abandon. The row exists
    so the worker converges its review BEFORE the next push, not so it is blocked from declaring."""

    def _dispatched(self, fleet, lineage_base, milestone="m1", title="claimant"):
        """Copies `TestProposeDoneRefusesAnUnreviewedHead._dispatched`'s argv: a real dispatch, so the
        record carries a real `--lineage-base` for `_reviewed_heads` to read back."""
        coordinator = fleet.paths["readyWorker"]
        Roadmap(coordinator).add(Milestone(id=milestone, title="carried work", status="blocked",
                                           deps=[], evidence=[]))
        argv = ["dispatch", "--porcelain", "--profile", str(fleet.profile("worker")),
                "--title", title, "--base", "00000000", "--optype", "append",
                "--from", str(coordinator), "--milestone", milestone]
        if lineage_base:
            argv += ["--lineage-base", lineage_base]
        code, out, err = fleet.run(argv)
        self.assertEqual(0, code, err)
        child = [line.split("\t")[1] for line in out.splitlines() if line.startswith("instant\t")][0]
        return pathlib.Path(child)

    def test_declare_awaiting_ci_reports_an_unreviewed_head(self):
        fleet = self.loaded()
        fleet.git = HeadsFakeGit({"alpha": "b" * 40})
        child = self._dispatched(fleet, "alpha=" + "a" * 40)
        #: The declare gate for `awaiting-ci` needs a watched, LIVE pane, or it refuses before reaching the
        #: advisory this test is about. A real `dispatch` records the session name but does not itself
        #: register it as live (`Fleet.worker()`'s fixture path does that; the CLI's own `dispatch` verb
        #: does not start a real session here) — so both `tmux_live` and `panes` need arming by hand.
        fleet.tmux_live.add("dt-claimant")
        fleet.panes["dt-claimant"] = WATCHED_PANE

        code, out, err = fleet.run(["declare", "--porcelain", "--instant", str(child),
                                    "--phase", "awaiting-ci"])

        self.assertEqual(EXIT_OK, code, err)
        self.assertIn("no review round has seen this head", out)

    def test_declare_awaiting_ci_reports_a_legacy_round_as_undetermined_not_unreviewed(self):
        """Fix round 1: a round exists but predates head tracking (`heads` absent, not `{}` differing from
        current). That is NOT MEASURED, and NOT MEASURED must never be read as an answer — a legacy round
        may well have reviewed this exact head, so the row says 'cannot determine', never 'no round has
        seen this head'."""
        fleet = self.loaded()
        fleet.git = HeadsFakeGit({"alpha": "b" * 40})
        child = self._dispatched(fleet, "alpha=" + "a" * 40)
        (child / ".fleet" / "review.json").write_text(json.dumps({
            "schema_version": 1,
            "rounds": [{"number": 1, "scope": "all", "verdict": "READY",
                        "at": "2026-07-30T01:00:00Z", "findings": []}],
        }))
        fleet.tmux_live.add("dt-claimant")
        fleet.panes["dt-claimant"] = WATCHED_PANE

        code, out, err = fleet.run(["declare", "--porcelain", "--instant", str(child),
                                    "--phase", "awaiting-ci"])

        self.assertEqual(EXIT_OK, code, err)
        self.assertIn("cannot determine whether this head was reviewed", out)
        self.assertNotIn("no review round has seen this head", out)


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
        fleet.panes["dt-readyWorker"] = WATCHED_PANE    # the standing declaration below is gated (i39)
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
        fleet.panes["dt-readyWorker"] = WATCHED_PANE    # the declaration below is gated (i39)
        code, _, err = fleet.run(["declare", "--instant", str(child), "--phase", "AWAITING-CI"])
        #: The setup is ASSERTED, not assumed. Without this the gate could start refusing the declaration
        #: and the case would still pass — a silenced rule and a rule with nothing to fire on look
        #: identical from here, and this test would have gone quietly vacuous.
        self.assertEqual(EXIT_OK, code, f"the standing declaration this case needs did not land: {err}")

        code, out, err = self._lint(fleet, "## Phase: AWAITING-CI")

        self.assertNotIn(cli.NEAR_MISS, out)


class TestAwaitingCiRequiresALiveWatcher(CliCase):
    """`FI-255`/`i39`. Claiming `awaiting-ci` while NOTHING will ever wake you.

    The operator: *"instants can claim AWAITING-CI while not armed with any watchers monitoring the CI.
    Can we ... ensure there is at least 1 watcher active. Otherwise it will give informative guidance."*

    Measured before the gate existed: two workers in the IDENTICAL declared phase rendered byte-identically
    as `declared awaiting-ci; not consuming attention` while one was mid-turn with its own monitor and the
    other had been stopped for 1h28m with nothing that would ever restart it. Phase, board row and park
    field were ALL invariant across the event they are supposed to detect — CI completing.

    The check is at the MOMENT OF THE CLAIM rather than in a sweep, because a check somebody has to
    remember to run fails the same way as the thing it checks.
    """

    def _ready(self, fleet, pane):
        fleet.panes["dt-readyWorker"] = pane
        return str(fleet.paths["readyWorker"])

    # --- the two arms, which only mean anything together -------------------------------------------

    def test_a_claim_with_nothing_armed_is_refused(self):
        """The negative arm: the reported defect."""
        fleet = self.loaded()
        ready = self._ready(fleet, BUSY_PANE)          # busy, and NOT watched

        code, out, err = fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci"])

        self.assertEqual(EXIT_REFUSED, code, f"an unwatched claim was accepted: {out!r}")
        self.assertIsNone(Declarations(fleet.paths["readyWorker"]).phase(),
                          "the refusal still stored the phase")

    def test_a_claim_with_a_monitor_armed_succeeds(self):
        """The positive arm, and it is the one that matters: a guard that refuses everything is
        indistinguishable from a guard that works."""
        fleet = self.loaded()
        ready = self._ready(fleet, WATCHED_PANE)

        code, out, err = fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci"])

        self.assertEqual(EXIT_OK, code, err)
        self.assertEqual("awaiting-ci", Declarations(fleet.paths["readyWorker"]).phase())

    def test_a_background_shell_is_a_watcher_too(self):
        """The other shape the indicator takes. Both re-invoke the session with no human in the loop."""
        fleet = self.loaded()
        ready = self._ready(fleet, WATCHED_PANE_SHELL)

        code, out, err = fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci"])

        self.assertEqual(EXIT_OK, code, err)

    # --- the trap that makes a naive implementation admit everything -------------------------------

    def test_the_agents_own_prose_about_monitors_is_not_a_watcher(self):
        """THE decoy, and it is derived from live input rather than imagined.

        The capture taken while authoring this gate had the word "monitors" inside `busy`'s 15-row window
        purely because the agent was WRITING ABOUT monitors. Match the busy window instead of the status
        line — the obvious implementation — and a session that merely DISCUSSED a watcher reports one.
        That is a guard that admits everything, which is exactly what it is supposed to detect.

        This case fails the moment anyone widens the match back to the window.
        """
        talking = "\n".join([
            "I armed 1 monitor on the CI run earlier and it emitted 2 monitors worth of events",
            "Let me check whether 1 shell is still running",
            "Thinking...",
            "  ⏵⏵ auto mode on · esc to interrupt · ← for agents"])   # <- status line: nothing armed
        fleet = self.loaded()
        ready = self._ready(fleet, talking)

        code, out, err = fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci"])

        self.assertEqual(EXIT_REFUSED, code,
                         "prose about monitors was accepted as a watcher; the match is reading the busy "
                         "window rather than the status line")

    def test_a_prompt_drawn_below_the_status_line_does_not_hide_the_watcher(self):
        """The false-positive arm, found by measuring rather than by reasoning.

        The first implementation read the LAST rendered row. Anything the harness draws beneath the status
        line — a tool-approval prompt, a notification — displaces it, so a genuinely watched session was
        refused. Safe direction, but it lands on somebody who did nothing wrong, and a guard that
        misfires on the innocent is the one people learn to route around.

        The status line is therefore found by its SIGNATURE, and the marker must share that row.
        """
        displaced = "\n".join([
            "working", "Thinking...",
            "  ⏵⏵ auto mode on · 1 monitor · esc to interrupt · ← for agents",
            "  ! approve this tool call?"])
        fleet = self.loaded()
        ready = self._ready(fleet, displaced)

        code, out, err = fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci"])

        self.assertEqual(EXIT_OK, code,
                         f"an armed watcher was missed because a prompt was drawn below it: {err}")

    def test_being_mid_turn_is_not_a_watcher(self):
        """`busy` is VACUOUS here and keying on it would admit 100% of claims: `declare` runs as a
        subprocess of the claiming agent's own turn, so every claimant is mid-turn by construction.
        Measured on the pane that authored this change — `esc to interrupt` present in BOTH arms."""
        fleet = self.loaded()
        ready = self._ready(fleet, BUSY_PANE)
        self.assertTrue(fleet.sessions.busy(BUSY_PANE), "this case needs a pane that reads BUSY")

        code, out, err = fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci"])

        self.assertEqual(EXIT_REFUSED, code, "a mid-turn pane was treated as a watched one")

    # --- the refusal has to be usable --------------------------------------------------------------

    def test_the_refusal_names_what_clears_it_and_who(self):
        """A bare non-zero exit is a fail by the charter's own words: the operator asked for *informative
        guidance*, and this package's convention is that a refusal names what is wrong, what clears it and
        who clears it."""
        fleet = self.loaded()
        ready = self._ready(fleet, BUSY_PANE)

        code, out, err = fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci"])
        said = (out + err).lower()

        self.assertEqual(EXIT_REFUSED, code)
        self.assertIn("clears when", said, "the refusal does not say what clears it")
        self.assertIn("clears who", said, "the refusal does not say who clears it")
        self.assertIn("monitor", said, "the refusal does not name the remedy it expects")

    # --- FI-7: a failed observation is not a negative observation -----------------------------------

    def test_a_failed_capture_refuses_and_does_not_read_as_absence(self):
        """`FI-7`, one layer along. `capture_pane` returns `None` when tmux fails and `""` when the pane is
        genuinely empty, and a guard whose failure mode is 'go ahead' is not a guard. The refusal must also
        be DISTINGUISHABLE from the unwatched one, or the remedy it names is the wrong remedy."""
        fleet = self.loaded()
        ready = str(fleet.paths["readyWorker"])
        fleet.capture_fails.add("dt-readyWorker")
        fleet.procs[:] = [p for p in fleet.procs if p.name != "dt-readyWorker"]   # nothing attributable

        code, out, err = fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci"])
        said = (out + err).lower()

        self.assertEqual(EXIT_REFUSED, code, "a FAILED observation was read as permission")
        self.assertIn("failed observation", said,
                      "the failed-capture refusal is worded as though nothing were armed, which sends the "
                      "reader to the wrong remedy")

    # --- scope: what this gate does NOT govern, said out loud --------------------------------------

    def test_only_awaiting_ci_is_gated(self):
        """The cap's treatment of `awaiting-ci` is load-bearing elsewhere and is NOT the bug; no other
        phase is gated, so a worker can always describe what it is really doing."""
        fleet = self.loaded()
        ready = self._ready(fleet, BUSY_PANE)

        code, out, err = fleet.run(["declare", "--instant", ready, "--phase", "running"])

        self.assertEqual(EXIT_OK, code, err)

    def test_an_instant_with_no_session_is_ungated_and_says_so(self):
        """A scope that narrows in silence reads as a pass (`OBS-49`). An instant that was never dispatched
        into a session has no pane to read, so the gate has no subject — and the claim must say that rather
        than look like one that passed the gate."""
        fleet = self.loaded()
        child = fleet.worker("neverLaunched", live=False)

        code, out, err = fleet.run(["declare", "--instant", str(child), "--phase", "awaiting-ci"])

        self.assertEqual(EXIT_OK, code, err)
        self.assertIn("ungated", (out + err).lower(),
                      "the claim skipped the gate silently, which is indistinguishable from passing it")

    # --- what the claim writes down ----------------------------------------------------------------

    def test_the_claim_records_what_was_observed(self):
        """FI-255's harm was not only the unchecked claim: the store kept `{"phase": "awaiting-ci"}` and
        nothing else, so a stopped worker and a self-waking one were indistinguishable in the RECORD too."""
        fleet = self.loaded()
        ready = self._ready(fleet, WATCHED_PANE)

        fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci"])

        self.assertEqual("1 monitor", Declarations(fleet.paths["readyWorker"]).watchers())

    def test_a_stale_watcher_record_does_not_outlive_its_claim(self):
        """A watcher record that survives into an ungated phase is the same lie in slower form."""
        fleet = self.loaded()
        ready = self._ready(fleet, WATCHED_PANE)
        fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci"])

        fleet.run(["declare", "--instant", ready, "--phase", "running"])

        self.assertIsNone(Declarations(fleet.paths["readyWorker"]).watchers())

    # --- the escape hatch: real watchers this tool cannot see --------------------------------------

    def test_a_named_watcher_this_tool_cannot_see_is_accepted(self):
        """A cron, an external watchdog and a peer session watching on this instant's behalf are REAL
        watchers that no pane shows. Refusing them is a false positive landing on somebody who did nothing
        wrong — and a guard with no override is routed around, which is worse than the original defect
        because routing around leaves no record that a judgement was made."""
        fleet = self.loaded()
        ready = self._ready(fleet, BUSY_PANE)          # nothing visible on the status line

        code, out, err = fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci",
                                    "--watcher", "cron */10 * * * * gh-run-poll --pr 4211"])

        self.assertEqual(EXIT_OK, code, err)
        self.assertEqual("awaiting-ci", Declarations(fleet.paths["readyWorker"]).phase())

    def test_the_watcher_record_has_a_production_reader(self):
        """A stored field nothing reads is not a record, it is a write-only comfort.

        This is `FI-255`'s own failure one field along, and an audit found it in the first version of this
        change: `Declarations.watchers()` was written at claim time and had ZERO readers in `fleet/src` —
        asserted only by tests. So an attested claim and an observed one were byte-identical to every
        consumer, which is exactly the indistinguishability the milestone exists to remove.
        """
        fleet = self.loaded()
        ready = self._ready(fleet, BUSY_PANE)
        fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci",
                   "--watcher", "cron gh-run-poll"])

        code, out, err = fleet.run(["brief", "--instant", ready])

        self.assertIn("cron gh-run-poll", out, "no production surface reports the watcher record")
        self.assertIn("ATTESTED", out, "brief does not distinguish an attested claim from an observed one")

    def test_brief_admits_the_board_cannot_show_this(self):
        """A scoped limitation must be STATED, or it is a silent one. `fleet board` renders an attested
        claim identically to an observed one — that is `reconcile`'s to fix and out of this charter (i45).
        The surface that CAN see the difference is the one that has to say the other cannot."""
        fleet = self.loaded()
        ready = self._ready(fleet, BUSY_PANE)
        fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci", "--watcher", "cron x"])

        code, out, err = fleet.run(["brief", "--instant", ready])

        self.assertIn("i45", out, "the limitation is not named where a reader would meet it")

    def test_the_hatch_buys_permission_and_NOT_silence(self):
        """The whole reason the hatch is safe. It must be impossible to tell a claim apart from one that
        passed the gate ONLY if the record says the same thing for both — so the attestation is stored
        verbatim and labelled, and a reader can always separate ATTESTED from OBSERVED."""
        fleet = self.loaded()
        ready = self._ready(fleet, BUSY_PANE)

        fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci",
                   "--watcher", "coordinator child-watchdog.sh"])

        recorded = Declarations(fleet.paths["readyWorker"]).watchers()
        self.assertIn("attested", recorded,
                      "an attested claim is indistinguishable from an observed one in the record")
        self.assertIn("child-watchdog.sh", recorded, "the attestation was not kept verbatim")

    def test_an_empty_attestation_is_not_an_attestation(self):
        """`park --question ""` draws the same line. An override that accepts nothing is a bypass with a
        flag name, and it would become the thing everyone types."""
        fleet = self.loaded()
        ready = self._ready(fleet, BUSY_PANE)

        code, out, err = fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci",
                                    "--watcher", "   "])

        self.assertEqual(EXIT_BAD_INPUT, code, "an empty attestation was accepted as a watcher")

    def test_the_refusal_tells_you_the_hatch_exists(self):
        """A remedy nobody can find is not a remedy: the refusal is where a stranger meets this gate, and
        if it does not name the override they will route around the gate instead."""
        fleet = self.loaded()
        ready = self._ready(fleet, BUSY_PANE)

        code, out, err = fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci"])

        self.assertIn("--watcher", out + err, "the refusal never mentions the escape hatch")

    # --- the pre-flight must agree with the real call ----------------------------------------------

    def test_dry_run_answers_the_question_it_is_asked(self):
        """`--dry-run` is consulted precisely to find out whether a claim would be accepted, so a dry run
        that reports `would-declare` on a claim the real call refuses is worse than no dry run. This CLI
        already has one verb where the two disagree (`milestone`); a NEW gate must not add another."""
        fleet = self.loaded()
        ready = self._ready(fleet, BUSY_PANE)

        dry, _, _ = fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci", "--dry-run"])
        real, _, _ = fleet.run(["declare", "--instant", ready, "--phase", "awaiting-ci"])

        self.assertEqual(dry, real, "--dry-run and the real call disagree about the same claim")


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


class TestAnIdleClaudePaneIsStillAClaudePane(unittest.TestCase):
    """`FI-208`/`OI-2` — `_is_claude`'s glyph fallback, and the half of the fix that had no control.

    `pane-guard`'s `12 not-claude` says *"a send here goes to somebody else's shell"*, and the close-out
    contract treats it as permission to tear the pane down. `_is_claude` reaches it by falling through
    process evidence, then the marker list, then `busy() or unsubmitted() is not None`.

    **MEASURED on two live Claude Code panes on 2026-08-08** (`i7` evidence `01-red/01-…` and `04-…`): an
    IDLE modern pane matches **none** of the eight original markers. Its footer is
    `⏵⏵ auto mode on (shift+tab to cycle) · ← for agents`. So before `FI-208` the only thing keeping such
    a pane out of `12` was `unsubmitted()` returning the DIM ghost — and fixing `FI-208` removes exactly
    that. Trading a false `10` for a false `12` moves the error into the direction that destroys work.

    These two cases are what stop the replacement marker being deleted by someone who cannot see why it
    is there. Without them, `cli.py`'s half of the fix has no failing control at all.
    """

    #: Copied byte-for-byte from `evidence/01-red/01-w22-capture-WITH-e.raw`, an idle live pane.
    IDLE_FOOTER = ("\x1b[39m  \x1b[93m⏵⏵ auto mode on\x1b[37m (shift+tab to cycle) · "
                   "← for agents\x1b[39m                       \x1b[96m/rc\x1b[39m")

    def sessions(self):
        from fleet.session import Probes, SessionLayer
        return SessionLayer(Probes(list_processes=lambda: [], capture_pane=lambda n: "",
                                   has_session=lambda n: False, start_session=lambda *a: None,
                                   kill_session=lambda n: None))

    def test_a_live_IDLE_footer_is_recognised_as_claude_with_no_process_and_an_empty_box(self):
        pane = "\n".join(["some finished answer", "\x1b[39m❯\xa0", self.IDLE_FOOTER])
        self.assertTrue(
            cli._is_claude(self.sessions(), pane, "dt-someworker"),
            "an idle Claude Code pane with an EMPTY box and no attributable process must still be a "
            "claude pane. Answering 12 not-claude here authorises tearing down a live worker, and it is "
            "reachable the moment the DIM ghost stops being miscounted as queued text (FI-208)")

    def test_a_marker_split_by_a_colour_change_is_still_found(self):
        """`auto mode on (shift+tab to cycle)` is ONE phrase interrupted by `\\x1b[37m` in the live
        capture. The capture carries attributes now, so matching the raw text is one styling change away
        from reporting a live pane as somebody else's shell."""
        self.assertNotIn("auto mode on (shift+tab to cycle)", self.IDLE_FOOTER,
                         "if the raw footer already held the whole phrase this case would prove nothing")
        pane = "\n".join(["output", "\x1b[39m❯\xa0", self.IDLE_FOOTER])
        self.assertTrue(cli._is_claude(self.sessions(), pane, "dt-x"))

    def test_a_genuinely_foreign_pane_is_still_NOT_claude(self):
        """The twin. A fallback widened until everything matches is not a fallback — `12` has to stay
        reachable, or `close`/`reap` can never tidy a real shell."""
        pane = "\n".join(["$ tail -f /var/log/syslog", "Aug  8 02:31:02 host sshd[1]: ok", "$ "])
        self.assertFalse(cli._is_claude(self.sessions(), pane, "some-shell"))


class TestANamedDestinationIsWholeNotHalf(unittest.TestCase):
    """`FI-2xx`/`I2-11` — a caller who names its store explicitly must not have its INSTANT written into a
    tree it never mentioned.

    Measured on 2026-08-08 against the working tree (`evidence/10-red/red-worktree.txt`): with
    `FLEET_INSTANTS` pointing at the coordinator's live effort tree — which is the value the SHARED tmux
    server exports, so every seeded shell on this box inherits it — `fleet init --home <sandbox>` printed
    `path .../quantonOnSpark4V2/instants/...` and exited **0**. Ten stray folders reached a live effort
    tree that way, and one of them (`FI-196`) came up believing it WAS the coordinator.

    The root cause is not "the flag loses" — `--instants-dir` already wins, and a change that only made it
    win would be a green proving nothing. It is that `default_context` collapsed `--home` and `$FLEET_HOME`
    into one value BEFORE resolving the instants directory, discarding the fact that one was typed by the
    caller and the other merely inherited. Precedence is therefore ordered here by **how specifically the
    caller named the destination**, flags before environment, and these four cases pin all four rungs.

    The severe consumer is `guards.blocking_compactions()`, which reads `ctx.instants_dir` DIRECTLY and
    counts record-less `*-inflight-compact-*` folders: one stray of that shape refuses every dispatch in an
    effort while `subjects()` stays clean.
    """

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-nameddest-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "sandbox-home"
        self.ambient = self.tmp / "someone-elses-live-effort-tree"
        self.flagged = self.tmp / "flagged-instants"
        for path in (self.home, self.ambient, self.flagged):
            path.mkdir(parents=True)

    def _instants(self, argv, env):
        """`default_context`'s answer for one argv under one environment, and nothing else."""
        parsed = cli.parse(cli.VERBS["init"], list(argv))
        keep = {name: os.environ.get(name) for name in ("FLEET_HOME", "FLEET_INSTANTS")}

        def restore():
            for name, was in keep.items():
                if was is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = was

        self.addCleanup(restore)
        for name in keep:
            os.environ.pop(name, None)
        os.environ.update(env)
        return cli.default_context(parsed, io.StringIO(), io.StringIO()).instants_dir

    def test_an_explicit_home_flag_outranks_an_inherited_FLEET_INSTANTS(self):
        """THE KNOWN-BAD INPUT. This is the case that minted the ten strays, and the only one of the four
        that was failing before the fix."""
        got = self._instants(["--name", "x", "--home", str(self.home)],
                             {"FLEET_INSTANTS": str(self.ambient)})
        self.assertEqual(self.home / "instants", got,
                         "`--home` was TYPED and `$FLEET_INSTANTS` was merely inherited from the shared "
                         "tmux server, so the instant belongs under the named home. Resolving to "
                         f"{self.ambient} writes a folder into a tree the caller never mentioned, at "
                         "exit 0, and that is FI-196")

    def test_an_explicit_instants_dir_still_outranks_everything(self):
        """The previously-passing case, and it must stay passing: a caller that genuinely wants its store
        and its instants apart says so, and that is the remedy for the case above."""
        got = self._instants(["--name", "x", "--home", str(self.home),
                              "--instants-dir", str(self.flagged)],
                             {"FLEET_INSTANTS": str(self.ambient)})
        self.assertEqual(self.flagged, got)

    def test_with_no_flag_the_environment_still_names_the_instants_directory(self):
        """The twin that stops the fix becoming "ignore `$FLEET_INSTANTS`". Eleven IT runners and every
        script in the coordinator's `tools/` name it that way and nothing else; breaking it would trade
        this defect for a larger one."""
        got = self._instants(["--name", "x"],
                             {"FLEET_HOME": str(self.home), "FLEET_INSTANTS": str(self.ambient)})
        self.assertEqual(self.ambient, got)

    def test_with_nothing_named_it_derives_from_the_home_that_won(self):
        got = self._instants(["--name", "x"], {"FLEET_HOME": str(self.home)})
        self.assertEqual(self.home / "instants", got)


#: A socket name that appears nowhere else in any output. `"fleet"` — the real one — is also this tool's
#: own name, so asserting on it would pass on almost anything the CLI prints.
OTHER_SERVER = "someOtherTmuxServer"


class TestAVerbThatActsOnASessionOnAnotherServer(CliCase):
    """`SI-59`. A record carries `tmux` — a session NAME — and a name is not an address.

    Measured on the live box before any of this existed: `fleet close --id <live worker>` from a shell
    pointed at a different tmux server returned **rc=0**, printed `closed dt-<name>`, stamped `closed_at`
    and reported the monitor disarmed — while `tmux -L <other> ls` still listed the session. It did not
    fail to find the pane. It reported success for a pane it never touched.

    The rule that came out of it has two halves, and they are not the same half:

    * the record NAMES a server — act **there**. That is doing what was asked. The first fix refused
      instead, and refusing turned out to be its own trap: it forced a coordinator to keep an old socket
      pinned in its runbook to stay able to close its own workers, and that pin then put the NEXT worker
      on the wrong server. A guard that makes people write down a workaround has moved the defect.
    * the record names NOTHING and the session turns up elsewhere — **refuse**. That is the pre-fix
      record, where acting would mean guessing which of several servers is the right one.
    """

    def test_a_record_that_NAMES_a_server_is_acted_on_THERE(self):
        fleet = self.loaded()
        fleet.worker("addressedWorker", server=OTHER_SERVER, pane=IDLE_PANE)
        code, out, err = fleet.run(["close", "--id", fleet.ids["addressedWorker"]])
        self.assertEqual(code, EXIT_OK, f"close refused a record that says exactly where its pane is: "
                                       f"{out}{err}")
        self.assertIsNotNone(fleet.store.read(fleet.ids["addressedWorker"]).closed_at,
                             "close reported success without stamping the record")
        self.assertNotIn("dt-addressedWorker", fleet.killed,
                         "the kill went to THIS server, which is the false-green this exists to stop")
        self.assertIn((OTHER_SERVER, "dt-addressedWorker"), fleet.killed_elsewhere,
                      "the kill never reached the server the record names, so nothing was closed")

    def test_a_record_naming_NO_server_whose_session_is_elsewhere_is_refused(self):
        """The pre-fix records — the two this defect was found on — carry no socket and never will. Here
        the tool would have to GUESS which server is meant, and a guess that acts is the original bug."""
        fleet = self.loaded()
        fleet.worker("strandedWorker", server=OTHER_SERVER)
        record = fleet.store.read(fleet.ids["strandedWorker"])
        record.tmux_socket = ""                      # written before the field existed
        fleet.store.write(record)
        code, out, err = fleet.run(["close", "--id", fleet.ids["strandedWorker"]])
        self.assertNotEqual(code, EXIT_OK, f"close acted on a session it could only have guessed at: {out}")
        self.assertIn(OTHER_SERVER, out + err, "the refusal does not name the server the session is on")
        self.assertIn("fixture-server", out + err, "the refusal does not name the server it looked on")
        self.assertEqual(fleet.killed, [], "close killed something while refusing")
        self.assertIsNone(fleet.store.read(fleet.ids["strandedWorker"]).closed_at,
                          "close stamped closed_at for a pane it never touched")

    def test_abort_on_an_unaddressed_session_elsewhere_leaves_the_folder_alone(self):
        fleet = self.loaded()
        fleet.worker("strandedAbort", server=OTHER_SERVER)
        record = fleet.store.read(fleet.ids["strandedAbort"])
        record.tmux_socket = ""
        fleet.store.write(record)
        before = sorted(p.name for p in fleet.instants.iterdir())
        code, out, err = fleet.run(["abort", "--instant", str(fleet.paths["strandedAbort"]),
                                    "--reason", "assumed dead"])
        self.assertNotEqual(code, EXIT_OK, f"abort proceeded against a live session elsewhere: {out}")
        self.assertEqual(sorted(p.name for p in fleet.instants.iterdir()), before,
                         "abort renamed the instant folder of a worker that is still running")

    def test_a_session_that_is_on_NO_server_is_still_closable(self):
        """The guard must not turn every genuinely finished worker into a refusal. Paired with the cases
        above so a rule that refused everything would fail here rather than look like a pass."""
        fleet = self.loaded()
        fleet.worker("finishedWorker", live=False)
        code, out, err = fleet.run(["close", "--id", fleet.ids["finishedWorker"]])
        self.assertEqual(code, EXIT_OK, f"close refused a session no server has: {out}{err}")

    def test_an_UNOBSERVABLE_search_does_not_refuse(self):
        """`servers_with` returns None when no probe was supplied, and None is not the empty list. A
        caller that cannot look must not act as though it looked and found something — in either
        direction. `FI-417` cuts both ways here."""
        fleet = self.loaded()
        fleet.worker("blindWorker", live=False)
        fleet.sessions.probes = dataclasses.replace(fleet.sessions.probes, session_servers=None)
        code, out, err = fleet.run(["close", "--id", fleet.ids["blindWorker"]])
        self.assertEqual(code, EXIT_OK, f"close refused because it could not search: {out}{err}")


class TestTheRecordNamesItsServer(CliCase):
    """`SI-59`. The fix underneath the guard: write the server down, so no later reader has to guess."""

    def test_dispatch_records_the_socket_it_created_the_session_on(self):
        fleet = self.loaded()
        code, out, err = fleet.run(["dispatch", "--profile", str(fleet.profile()),
                                    "--title", "socketRecorded", "--base", FRESH_BASE_DIGITS,
                                    "--optype", "append"])
        self.assertEqual(code, EXIT_OK, f"{out}{err}")
        written = [r for r in fleet.store.all() if r.title == "socketRecorded"]
        self.assertEqual(len(written), 1, f"expected one record, got {written}")
        self.assertEqual(written[0].tmux_socket, "fixture-server",
                         "the dispatch recorded no server, so every later reader has to guess again")

    def test_an_EMPTY_socket_is_not_measured_and_not_the_default_server(self):
        """The two records this was found on carry no socket and never will. Absence has to stay absence:
        reading it as "the default server" would manufacture a fact and put the false DEAD back."""
        fleet = self.loaded()
        fleet.worker("preFixWorker")
        self.assertEqual(fleet.store.read(fleet.ids["preFixWorker"]).tmux_socket, "")


class TestNotClaimingDEADAboutAnotherServer(CliCase):
    """`SI-59`, the reporting half. `SI-39` gave a live-pid holder its own state because DEAD is an
    ACTIONABLE claim and a wrong one invites a human to reap a running worker. A record that NAMES a
    different server is the same claim with a cheaper proof: no probe is needed, the record says so."""

    def test_a_record_naming_another_server_is_not_reported_DEAD(self):
        fleet = self.loaded()
        fleet.worker("otherServerWorker", server=OTHER_SERVER)
        code, out, err = fleet.run(["status", "--id", fleet.ids["otherServerWorker"], "--porcelain"])
        rows = dict(line.split("\t")[:2] for line in out.splitlines() if "\t" in line)
        self.assertNotEqual(rows.get("state"), "DEAD",
                            f"reported DEAD about a session on a server it never looked at: {out}")

    def test_the_note_names_the_server_the_record_was_dispatched_on(self):
        fleet = self.loaded()
        fleet.worker("otherServerNoted", server=OTHER_SERVER)
        code, out, err = fleet.run(["status", "--id", fleet.ids["otherServerNoted"]])
        self.assertIn(OTHER_SERVER, out + err, "the report does not name the server to look on")


class TestFollowingARecordToItsOwnServer(CliCase):
    """`SI-59`, second correction. Recording the server was not enough: the reader HAD the address and
    still refused to use it.

    Measured the morning after `0.5.3` deployed. A worker dispatched at 00:34 recorded
    `tmux_socket: 'fleet'` — the field worked — and `fleet status` from a correctly configured shell still
    answered:

        state    UNREACHABLE
        note     pid 2227342 is live and holds this record's slot, but no session answers for
                 dt-x7stackfifthwaveprs … Usually the wrong tmux server: export FLEET_TMUX_SOCKET …
        evidence.tmux_socket   fleet
        evidence.asked_server  fleet-davis

    The report printed the server it should have asked and the server it did ask, on adjacent lines, and
    asked the wrong one anyway. Telling a reader to go and look is not the same as looking.

    Reads follow the record; WRITES still do not. `close` and `abort` keep refusing across servers,
    because acting on a server the caller never named is a different thing from answering about one.
    """

    def test_a_worker_on_the_server_its_record_names_is_reported_live(self):
        fleet = self.loaded()
        fleet.worker("followedWorker", server=OTHER_SERVER, pane=BUSY_PANE)
        code, out, err = fleet.run(["status", "--id", fleet.ids["followedWorker"], "--porcelain"])
        rows = dict(line.split("\t")[:2] for line in out.splitlines() if "\t" in line)
        self.assertNotEqual(rows.get("state"), "UNREACHABLE",
                            f"still unreachable with the address in hand: {out}")
        self.assertEqual(rows.get("evidence.liveness"), "session",
                         f"the reader did not follow the record to its own server: {out}")

    def test_the_report_names_the_server_it_ACTUALLY_asked(self):
        """`asked_server` is the honesty field. If the reader follows the record, it has to say so, or the
        next person debugging this reads a true state beside a false claim about where it came from."""
        fleet = self.loaded()
        fleet.worker("askedWorker", server=OTHER_SERVER)
        code, out, err = fleet.run(["status", "--id", fleet.ids["askedWorker"], "--porcelain"])
        rows = dict(line.split("\t")[:2] for line in out.splitlines() if "\t" in line)
        self.assertEqual(rows.get("evidence.asked_server"), OTHER_SERVER, out)

    def test_a_record_naming_a_server_that_has_nothing_is_still_unreachable_and_says_which(self):
        """The negative control. Following the address must not manufacture liveness when the address is
        empty — and the note has to name the server that was asked, not the generic advice."""
        fleet = self.loaded()
        fleet.worker("goneWorker", live=False)
        record = fleet.store.read(fleet.ids["goneWorker"])
        record.tmux_socket = "aServerWithNothingOnIt"
        fleet.store.write(record)
        code, out, err = fleet.run(["status", "--id", fleet.ids["goneWorker"]])
        self.assertIn("aServerWithNothingOnIt", out + err,
                      f"the report does not name the server it asked: {out}{err}")

    def test_a_record_with_NO_recorded_server_is_read_exactly_as_before(self):
        """The pre-fix records — the ones that motivated all of this — carry no socket. Absence must not
        send the reader hunting: it is not measured, and a search over every server for every record is
        the cost `reconcile` refuses on a healthy board."""
        fleet = self.loaded()
        fleet.worker("plainWorker", pane=BUSY_PANE)
        code, out, err = fleet.run(["status", "--id", fleet.ids["plainWorker"], "--porcelain"])
        rows = dict(line.split("\t")[:2] for line in out.splitlines() if "\t" in line)
        self.assertEqual(rows.get("evidence.asked_server"), "fixture-server", out)
        self.assertEqual(rows.get("evidence.tmux_socket"), "", out)


class TestPaneGuardFollowsTheRecordToo(CliCase):
    """`SI-59`, third instance. `pane-guard` was the one verb left asking the ambient server.

    Measured on `0.5.4`, one record, one shell, two verbs:

        status     --id …  ->  state RUNNING, asked_server 'pg-other', liveness session
        pane-guard --id …  ->  verdict unknown-pane
                               "no live process and no session answer for 'dt-pgsubject'"

    It fails CLOSED — `13` is not `0`, so a monitor holding the `FD-10` contract will not send — so this
    is wrong rather than dangerous. But it is the verb that gate is built on, and the one
    `reviving-dead-panes` tells an operator to trust when checking whether a revived pane came back. A
    guard that reports *this pane does not exist* about a pane the next verb along can see is the sentence
    `SI-54` already rewrote once for reading like a dead worker.

    `--pane` keeps asking the ambient server, and that asymmetry is the rule rather than an omission: a
    bare session NAME carries no address, so there is nothing to follow.
    """

    def test_id_resolves_the_pane_on_the_server_the_record_names(self):
        fleet = self.loaded()
        fleet.worker("guardedElsewhere", server=OTHER_SERVER, pane=BUSY_PANE)
        code, out, err = fleet.run(["pane-guard", "--id", fleet.ids["guardedElsewhere"], "--porcelain"])
        rows = dict(line.split("\t")[:2] for line in out.splitlines() if "\t" in line)
        self.assertNotEqual(rows.get("verdict"), "unknown-pane",
                            f"pane-guard says the pane does not exist while status can see it: {out}")
        self.assertEqual(code, cli.PANE_MID_TURN,
                         f"the busy pane on the record's own server was not read: {out}{err}")

    def test_a_bare_pane_NAME_still_asks_the_ambient_server(self):
        """The asymmetry, asserted rather than assumed. `--pane` is for when you have only the session
        name, and a name with no record behind it names no server either — following one would mean
        picking a server for the caller."""
        fleet = self.loaded()
        fleet.worker("guardedNamed", server=OTHER_SERVER, pane=BUSY_PANE)
        code, out, err = fleet.run(["pane-guard", "--pane", "dt-guardedNamed", "--porcelain"])
        rows = dict(line.split("\t")[:2] for line in out.splitlines() if "\t" in line)
        self.assertEqual(rows.get("verdict"), "unknown-pane",
                         f"--pane followed an address a bare session name does not carry: {out}")

    def test_a_record_whose_server_really_does_not_have_it_is_still_unknown(self):
        """The negative control. Following the address must not manufacture a pane."""
        fleet = self.loaded()
        fleet.worker("guardedGone", live=False)
        record = fleet.store.read(fleet.ids["guardedGone"])
        record.tmux_socket = "aServerWithNothingOnIt"
        fleet.store.write(record)
        code, out, err = fleet.run(["pane-guard", "--id", fleet.ids["guardedGone"], "--porcelain"])
        rows = dict(line.split("\t")[:2] for line in out.splitlines() if "\t" in line)
        self.assertEqual(rows.get("verdict"), "unknown-pane", out)
