"""Shared fixture support for the hermetic suite.

One helper lives here, and it exists because the suite was measured NOT being hermetic. `cli.main` reads
`os.environ` at parse time — `require_named_instants` asks whether the caller named where instants go —
while a fixture states the same fact by handing `Ctx` an `instants_dir`. Those are two different tiers,
and nothing made them agree: 33 tests passed only because the operator's shell happened to export
`FLEET_HOME`, and the same tests failed inside `release-verify`, which runs with `env -u FLEET_HOME`.

A test that passes because of what the person running it exported is not measuring the product.
"""
import atexit
import contextlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

#: Every variable `cli` reads. Cleared as a SET rather than one at a time: the failure this file exists
#: to stop was one unlisted variable reaching a test, and a hand-maintained partial list is that failure
#: waiting to happen again.
FLEET_ENV = ("FLEET_HOME", "FLEET_INSTANTS", "FLEET_RELEASES", "FLEET_TMUX_SOCKET", "FLEET_ROOT",
             "FLEET_CODEX_BIN", "FLEET_CLAUDE_BIN", "CODEX_HOME", "CLAUDE_CONFIG_DIR",
             "REAL_CLAUDE", "CLAUDE_OWNERS_MAP", "FLEET_SEED_CHECK_SECONDS")


@contextlib.contextmanager
def hermetic_environment(instants, home=None):
    """The environment a fixture-driven `cli.main` sees: this fixture's instants directory, and NOTHING
    the operator happened to export.

    It SETS `FLEET_INSTANTS` rather than merely clearing the rest, and that is the honest form: a real
    caller must name where instants are created, so a fixture that drives `dispatch` has to say it too.
    Saying it here — at the tier the guard actually reads — is what makes the fixture's `Ctx.instants_dir`
    and the parse-time check agree.

    `mock.patch.dict` restores deletions as well as assignments, so the operator's own environment is
    intact after the call.
    """
    with mock.patch.dict(os.environ, {}, clear=False):
        for name in FLEET_ENV:
            os.environ.pop(name, None)
        os.environ["FLEET_INSTANTS"] = str(instants)
        #: `$HOME` too, when the fixture has one to offer. It is not a `FLEET_` variable, but it decides
        #: the same kind of answer: `root.find` walks up to it and `root-init` refuses outside it, so a
        #: test that leaves it pointing at the operator's real home is measuring their box. The variable
        #: is only SET when a fixture names one, because most cases have no notion of a home directory and
        #: inventing one for them would be this file's own failure in the other direction.
        if home is not None:
            os.environ["HOME"] = str(home)
        #: FB-118. Cleared is not the same as absent: `peers` falls through an unset FLEET_CLAUDE_BIN to the box's
        #: real claude, and `resolve_settings` to PATH. Inside a fixture both name the refusing stub; a case
        #: that needs a runtime to answer sets its own stub over this.
        for name in RUNTIME_BINS:
            os.environ[name] = NO_REAL_RUNTIME
        yield


# --- the live-fleet guard --------------------------------------------------------------------------
#
# `hermetic_environment` is opt-in, and opting out cost nothing you could see: `PromoteGateCase` drove
# `cli.main` with no root named and passed ONLY because the suite happened to run inside the operator's
# fleet root — where it read that root's marker, its store and its tmux server — while the same nine tests
# failed from an export under `/tmp`, so P-1 (`it/bin/assert-head-green.sh`) was RED at every tree
# (FB-30/FB-35/FB-40). A test that passes because of where it was started is measuring the box.
#
# So the suite now refuses to reach the fleet the PROCESS could reach on its own. Those destinations are
# captured once, when this package is imported — which `unittest discover` does while importing the test
# modules, before any test runs — from the real `$HOME`, the real cwd and the real environment. Any test
# that then resolves one of them fails with `LiveFleetReached`, inside a root and outside one alike.
# An `AssertionError` on purpose: `cli.main` turns `FleetError` and `OSError` into exit codes, and a
# guard a handler can swallow would be one more control that cannot fail.


class LiveFleetReached(AssertionError):
    """A test resolved a fleet destination it did not create."""


def _resolved(path):
    try:
        return pathlib.Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        return None


def _live_destinations(environ, cwd):
    """`(roots, stores, release_areas, instants_dirs)` this process reaches with nothing named: the
    marker the walk finds from `cwd` under `$HOME`, whatever `FLEET_ROOT` / `FLEET_HOME` /
    `FLEET_RELEASES` / `FLEET_INSTANTS` name, and each live store's derived `instants/`. The last is
    where `dispatch` and `init` CREATE folders — a dispatched session exports the operator's effort
    tree as `FLEET_INSTANTS`, so it is the one destination here a stray test would write into."""
    from fleet import root as root_mod

    roots = set()
    try:
        found = root_mod.find(cwd, environ.get("HOME") or pathlib.Path.home())
    except Exception:                                   # an unreadable tree is not a live fleet
        found = None
    for candidate in (found, environ.get("FLEET_ROOT")):
        if candidate:
            roots.add(_resolved(candidate))
    roots.discard(None)
    stores = {_resolved(r / ".fleet") for r in roots}
    releases = {_resolved(r / "fleet-releases") for r in roots}
    if environ.get("FLEET_HOME"):
        stores.add(_resolved(environ["FLEET_HOME"]))
    if environ.get("FLEET_RELEASES"):
        releases.add(_resolved(environ["FLEET_RELEASES"]))
    stores.discard(None)
    instants = {_resolved(store / "instants") for store in stores}
    if environ.get("FLEET_INSTANTS"):
        instants.add(_resolved(environ["FLEET_INSTANTS"]))
    return (frozenset(roots), frozenset(stores), frozenset(releases - {None}),
            frozenset(instants - {None}))


LIVE_ROOTS, LIVE_STORES, LIVE_RELEASES, LIVE_INSTANTS = _live_destinations(dict(os.environ),
                                                                             pathlib.Path.cwd())


def _refuse(kind, path, how):
    raise LiveFleetReached(
        f"this test resolved the {kind} {path} through {how}. That is a fleet this test process could reach "
        f"without the test creating it — the operator's, when the suite runs inside a fleet root or from a "
        f"dispatched session. Name a private one: `hermetic_environment(instants, home=<tmp>)` and a "
        f"`--root`/`--home` the fixture wrote.")


def _install_live_fleet_guard():
    from fleet import cli, root as root_mod

    if getattr(root_mod.load, "live_fleet_guard", False):
        return
    real_load = root_mod.load
    real_home = cli.resolve_home
    real_instants = cli.resolve_instants
    real_releases = cli.resolve_releases

    def load(root_dir):
        if _resolved(root_dir) in LIVE_ROOTS:
            _refuse("fleet root", root_dir, "its .fleet-root marker")
        return real_load(root_dir)

    #: `resolve_home`, not `default_context`: the context reads the store's `runtime.json` as soon as it
    #: has a home, so a check on the finished context would object only after the live store was read.
    def resolve_home(parsed, environ, cwd):
        home, source = real_home(parsed, environ, cwd)
        if _resolved(home) in LIVE_STORES:
            _refuse("store", home, f"`{parsed.verb}`'s {source}")
        return home, source

    def resolve_instants(parsed, environ, cwd):
        instants = real_instants(parsed, environ, cwd)
        if _resolved(instants) in LIVE_INSTANTS:
            _refuse("instants directory", instants, f"`{parsed.verb}`'s instants resolution")
        return instants

    def resolve_releases(parsed, environ, cwd):
        rel = real_releases(parsed, environ, cwd)
        if _resolved(rel.root) in LIVE_RELEASES:
            _refuse("release area", rel.root, f"`{parsed.verb}`'s release resolution")
        return rel

    for wrapper in (load, resolve_home, resolve_instants, resolve_releases):
        wrapper.live_fleet_guard = True
    root_mod.load = load
    cli.resolve_home = resolve_home
    cli.resolve_instants = resolve_instants
    cli.resolve_releases = resolve_releases


_install_live_fleet_guard()


# --- the host boundary: no real runtime, no tmux server the suite did not create (FB-118) ---------------
#
# Measured at 74bea441 from a worker pane: every suite run exec'd the box's real `claude agents --json` four
# times (peers, with FLEET_CLAUDE_BIN cleared and nothing in its place), answered two bare `tmux` calls from
# the pane's `$TMUX` server (fleet-davis), sent seventeen `tmux -L fleet-davis` calls from tests that inherited
# the pane's FLEET_TMUX_SOCKET, and created the suite's own servers in /tmp/tmux-<uid> beside the live ones.
# Read-only today; a test that can read the live server can one day write to it.
#
# So, for the whole process and everything it starts, before any test runs:
#   * the caller's tmux handles are gone (`TMUX`, `TMUX_PANE`, `FLEET_TMUX_SOCKET`) and `TMUX_TMPDIR` is a
#     directory of this suite, so a bare or `-L` tmux can only name a server that lives here;
#   * FLEET_CLAUDE_BIN / FLEET_CODEX_BIN name `fixtures/bin/no-real-runtime`, which runs nothing;
#   * THE TRIPWIRE: an audit hook refuses an in-process exec of a real runtime binary or of a tmux call aimed at
#     a FOREIGN server (the caller's tmux directory or `$TMUX` server); `fixtures/tripwire-path/`, first on PATH
#     with `tmux`, `claude` and `codex`, refuses the same for child processes; both, like the stub, append to one
#     log. A test whose run grew that log FAILS, even if the product swallowed the refusal. `expect_tripwire()` is how a case that
#     trips it on purpose takes its records back.
#
# A child that inherits this environment reuses it (the log, the foreign set) instead of minting its own, so a
# suite run from inside the suite still charges the right process.


class HostReached(LiveFleetReached):
    """A test exec'd a real runtime, or a tmux call aimed at a server the suite did not create."""


_FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
NO_REAL_RUNTIME = str(_FIXTURES / "bin" / "no-real-runtime")
#: A claude that answers `claude agents --json` with no sessions — for a fixture whose verbs reach `peers`.
CLAUDE_AGENTS_STUB = str(_FIXTURES / "bin" / "claude-agents-stub")
_TRIPWIRE_PATH_DIR = str(_FIXTURES / "tripwire-path")
RUNTIME_BINS = ("FLEET_CLAUDE_BIN", "FLEET_CODEX_BIN")
TMUX_HANDLES = ("TMUX", "TMUX_PANE", "FLEET_TMUX_SOCKET")


def _inherits_a_live_boundary(environ) -> bool:
    """RV-27. Reuse the parent suite's boundary only when it is really there: its log exists, its foreign set is
    non-empty, and TMUX_TMPDIR is an existing directory beside that log. A marker alone (leaked into a shell or a
    tmux server's global environment) would otherwise leave nothing foreign, no log to charge, and a TMUX_TMPDIR
    that tmux replaces with /tmp."""
    log, tmpdir = environ.get("FLEET_SUITE_TRIPWIRE", ""), environ.get("TMUX_TMPDIR", "")
    return bool(log and os.path.isfile(log) and environ.get("FLEET_SUITE_FOREIGN_TMUX") and tmpdir
                and os.path.isdir(tmpdir)
                and os.path.dirname(os.path.realpath(tmpdir)) == os.path.dirname(os.path.realpath(log)))


_OWNER = not _inherits_a_live_boundary(os.environ)


def _ambient_path():
    return os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep) if p != _TRIPWIRE_PATH_DIR)


def _real_runtimes(path):
    """Every binary a real claude or codex resolves to on this box, resolved: PATH's, peers' hard-coded default,
    and whatever the caller exported. Captured before this module replaces any of them."""
    from fleet import peers

    found = {shutil.which("claude", path=path), shutil.which("codex", path=path), peers.DEFAULT_CLAUDE_BIN,
             os.environ.get("REAL_CLAUDE")}
    found |= {os.environ.get(name) for name in RUNTIME_BINS}
    return frozenset(os.path.realpath(p) for p in found if p and p != NO_REAL_RUNTIME and os.path.exists(p))


if _OWNER:
    AMBIENT_PATH = _ambient_path()
    REAL_TMUX = shutil.which("tmux", path=AMBIENT_PATH) or "/usr/bin/tmux"
    #: The operator's servers: the box's default tmux directory ALWAYS (RV-28: a caller that exports its own
    #: TMUX_TMPDIR does not move the live servers), the directory the caller's shell resolves, and `$TMUX`'s server.
    FOREIGN_TMUX = tuple(dict.fromkeys(filter(None, (
        str(pathlib.Path("/tmp").resolve() / f"tmux-{os.getuid()}"),
        str(pathlib.Path(os.environ.get("TMUX_TMPDIR") or "/tmp").resolve() / f"tmux-{os.getuid()}"),
        os.environ.get("TMUX", "").split(",")[0]))))
    REAL_RUNTIMES = _real_runtimes(AMBIENT_PATH)
    SUITE_DIR = tempfile.mkdtemp(prefix="fleet-suite-")
    SUITE_TMUX_TMPDIR = os.path.join(SUITE_DIR, "tmux")
    os.mkdir(SUITE_TMUX_TMPDIR)
    TRIPWIRE_LOG = os.path.join(SUITE_DIR, "tripwire.log")
    open(TRIPWIRE_LOG, "a").close()
    os.environ.update(FLEET_SUITE_TRIPWIRE=TRIPWIRE_LOG, FLEET_SUITE_FOREIGN_TMUX=":".join(FOREIGN_TMUX),
                      FLEET_SUITE_REAL_TMUX=REAL_TMUX, FLEET_SUITE_AMBIENT_PATH=AMBIENT_PATH,
                      FLEET_SUITE_REAL_RUNTIMES=":".join(sorted(REAL_RUNTIMES)))
else:
    AMBIENT_PATH = os.environ.get("FLEET_SUITE_AMBIENT_PATH", _ambient_path())
    REAL_TMUX = os.environ.get("FLEET_SUITE_REAL_TMUX") or "/usr/bin/tmux"
    FOREIGN_TMUX = tuple(filter(None, os.environ.get("FLEET_SUITE_FOREIGN_TMUX", "").split(":")))
    REAL_RUNTIMES = frozenset(filter(None, os.environ.get("FLEET_SUITE_REAL_RUNTIMES", "").split(":")))
    TRIPWIRE_LOG = os.environ["FLEET_SUITE_TRIPWIRE"]
    SUITE_TMUX_TMPDIR = os.environ.get("TMUX_TMPDIR") or os.path.join(os.path.dirname(TRIPWIRE_LOG), "tmux")

for _name in TMUX_HANDLES:
    os.environ.pop(_name, None)
os.environ["TMUX_TMPDIR"] = SUITE_TMUX_TMPDIR
for _name in RUNTIME_BINS:
    os.environ[_name] = NO_REAL_RUNTIME
if not os.environ.get("PATH", "").startswith(_TRIPWIRE_PATH_DIR + os.pathsep):
    os.environ["PATH"] = _TRIPWIRE_PATH_DIR + os.pathsep + AMBIENT_PATH


def tmux_server(argv, env, cwd=None):
    """The socket a tmux argv reaches under `env`, resolved the way tmux resolves it — relative paths from `cwd`,
    the directory the call runs in (RV-30), not this process's."""
    here = os.fsdecode(cwd) if cwd else os.getcwd()
    server = name = None
    args = list(argv[1:])
    while args:
        arg = args.pop(0)
        if arg in ("--", "-") or not arg.startswith("-"):
            break
        #: RV-26. A getopt cluster: `-uS path`, `-uSpath`, `-2L name`. The first of c/f/L/S/T takes the rest of
        #: the cluster, or the next argument, as its value and ends the cluster.
        for i, flag in enumerate(arg[1:], start=1):
            if flag in "cfLST":
                value = arg[i + 1:] or (args.pop(0) if args else "")
                server = value if flag == "S" else server
                name = value if flag == "L" else name
                break
    if server is None:
        #: RV-25. tmux uses TMUX_TMPDIR only when it names an existing directory, and /tmp otherwise.
        tmpdir = os.path.join(here, env["TMUX_TMPDIR"]) if env.get("TMUX_TMPDIR") else ""
        base = pathlib.Path(tmpdir if tmpdir and os.path.isdir(tmpdir) else "/tmp") / f"tmux-{os.getuid()}"
        if name is not None:
            server = base / name
        elif env.get("TMUX"):
            server = env["TMUX"].split(",")[0]
        else:
            server = base / "default"
    return os.path.realpath(os.path.join(here, server))


def _is_foreign(server):
    for foreign in FOREIGN_TMUX:
        foreign = os.path.realpath(foreign)
        if server == foreign or os.path.dirname(server) == foreign:
            return True
    return False


def _trip(kind, what, argv):
    with open(TRIPWIRE_LOG, "a") as log:
        log.write(f"{kind}\t{what}\t{' '.join(map(str, argv))}\n")
    raise HostReached(f"this test exec'd {' '.join(map(str, argv))!r}: {what}. The hermetic suite reaches neither a "
                      f"real claude/codex nor a tmux server it did not create (FB-118). Give the test its own "
                      f"stub (tests/fixtures/bin/claude-agents-stub) or its own server (-S <tmp path>).")


def _exec_guard(event, args):
    if event == "subprocess.Popen":
        executable, argv, cwd, env = args
    elif event in ("os.exec", "os.posix_spawn"):          # RV-29: os.execv*/os.posix_spawn* raise these
        (executable, argv, env), cwd = args, None
    else:
        return
    if isinstance(argv, (str, bytes)):
        argv = [argv]
    argv = [os.fsdecode(a) for a in argv] if argv else []
    first = os.fsdecode(executable) if executable else (argv[0] if argv else "")
    if not first:
        return
    env = os.environ if env is None else {os.fsdecode(k): os.fsdecode(v) for k, v in env.items()}
    path = first if os.sep in first else shutil.which(first, path=env.get("PATH"))
    resolved = os.path.realpath(path) if path else None
    if resolved in REAL_RUNTIMES:
        _trip("runtime", f"{resolved} is the box's real runtime", argv)
    if os.path.basename(first) == "tmux" or (resolved and resolved == os.path.realpath(REAL_TMUX)):
        server = tmux_server(argv or [first], env, cwd)
        if _is_foreign(server):
            _trip("tmux", f"it would reach {server}, a server this suite did not create", argv)


def _log_size():
    try:
        return os.path.getsize(TRIPWIRE_LOG)
    except OSError:
        return 0


def _read_from(offset):
    try:
        with open(TRIPWIRE_LOG) as log:
            log.seek(offset)
            return [line.rstrip("\n") for line in log if line.strip()]
    except OSError:
        return []


@contextlib.contextmanager
def expect_tripwire():
    """For a case that trips the tripwire ON PURPOSE: yields the list of records written inside the block,
    and takes them back off the log so the case is not failed for them."""
    offset, seen = _log_size(), []
    try:
        yield seen
    finally:
        seen.extend(_read_from(offset))
        with open(TRIPWIRE_LOG, "r+") as log:
            log.truncate(offset)


def _install_host_tripwire():
    if getattr(unittest.TestCase.run, "host_tripwire", False):
        return
    sys.addaudithook(_exec_guard)
    real_run = unittest.TestCase.run

    def run(self, result=None):
        offset = _log_size()
        outcome = real_run(self, result)
        tripped = _read_from(offset)
        if tripped:
            #: Taken back off the log once charged, so the NEXT test starts clean and nothing is charged twice.
            with open(TRIPWIRE_LOG, "r+") as log:
                log.truncate(offset)
            target = result if result is not None else outcome
            try:
                raise HostReached("the host tripwire recorded, during this test: " + " | ".join(tripped))
            except HostReached:
                if target is not None:
                    target.addFailure(self, sys.exc_info())
        return outcome

    run.host_tripwire = True
    unittest.TestCase.run = run


def _remove_suite_dir():
    """The suite's own tmux servers, then its directory. Only the process that made the directory does this."""
    sockets = pathlib.Path(SUITE_TMUX_TMPDIR) / f"tmux-{os.getuid()}"
    for sock in (sockets.iterdir() if sockets.is_dir() else ()):
        subprocess.run([REAL_TMUX, "-S", str(sock), "kill-server"], capture_output=True)
    shutil.rmtree(SUITE_DIR, ignore_errors=True)


_install_host_tripwire()
if _OWNER:
    atexit.register(_remove_suite_dir)
