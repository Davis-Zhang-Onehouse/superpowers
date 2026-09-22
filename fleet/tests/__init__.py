"""Shared fixture support for the hermetic suite.

One helper lives here, and it exists because the suite was measured NOT being hermetic. `cli.main` reads
`os.environ` at parse time — `require_named_instants` asks whether the caller named where instants go —
while a fixture states the same fact by handing `Ctx` an `instants_dir`. Those are two different tiers,
and nothing made them agree: 33 tests passed only because the operator's shell happened to export
`FLEET_HOME`, and the same tests failed inside `release-verify`, which runs with `env -u FLEET_HOME`.

A test that passes because of what the person running it exported is not measuring the product.
"""
import contextlib
import os
import pathlib
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
    """`(roots, stores, release_areas)` this process reaches with nothing named: the marker the walk
    finds from `cwd` under `$HOME`, and whatever `FLEET_ROOT` / `FLEET_HOME` / `FLEET_RELEASES` name."""
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
    return frozenset(roots), frozenset(stores - {None}), frozenset(releases - {None})


LIVE_ROOTS, LIVE_STORES, LIVE_RELEASES = _live_destinations(dict(os.environ), pathlib.Path.cwd())


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

    def resolve_releases(parsed, environ, cwd):
        rel = real_releases(parsed, environ, cwd)
        if _resolved(rel.root) in LIVE_RELEASES:
            _refuse("release area", rel.root, f"`{parsed.verb}`'s release resolution")
        return rel

    for wrapper in (load, resolve_home, resolve_releases):
        wrapper.live_fleet_guard = True
    root_mod.load = load
    cli.resolve_home = resolve_home
    cli.resolve_releases = resolve_releases


_install_live_fleet_guard()
