"""The live-fleet guard in `tests/__init__.py` (FB-30/FB-35/FB-40).

A guard nobody tests is a guard that can be silently absent — installed on a name nobody calls, or keyed
on a set that is always empty. So these cases prove the three things it has to be: installed on the seams
`cli` actually calls, firing on each kind of destination, and silent on a fixture's own private one.
"""
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import tests
from fleet import cli
from fleet import root as root_mod
from fleet.root import MARKER
from tests import LiveFleetReached, hermetic_environment


class LiveFleetGuardCase(unittest.TestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="fleet-liveguard-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.root = self.home / "someroot"
        self.root.mkdir(parents=True)
        (self.root / MARKER).write_text(json.dumps({"name": f"liveguard-{os.getpid()}"}))
        self.releases = self.tmp / "releases"
        self.releases.mkdir()

    def _promote(self, *named):
        with hermetic_environment(self.tmp / "instants", home=self.home):
            return cli.main(["release-promote", "--version", "0.1.0", "--releases", str(self.releases),
                             *named], stdout=io.StringIO(), stderr=io.StringIO())

    def test_it_is_installed_on_the_seams_cli_calls(self):
        """`default_context` looks `resolve_home` up by name at call time, `_releases` does the same for
        `resolve_releases`, and every marker read goes through `root.load` — wrapped anywhere else, the
        guard would watch a name nobody calls."""
        for seam in (root_mod.load, cli.resolve_home, cli.resolve_instants, cli.resolve_releases):
            self.assertTrue(getattr(seam, "live_fleet_guard", False), f"{seam!r} is not the guard")

    def test_it_fires_on_a_live_root(self):
        with mock.patch.object(tests, "LIVE_ROOTS", frozenset({self.root.resolve()})):
            with self.assertRaises(LiveFleetReached):
                self._promote("--root", str(self.root))

    def test_it_fires_on_a_live_store_reached_with_no_marker(self):
        store = self.tmp / "store"
        with mock.patch.object(tests, "LIVE_STORES", frozenset({store.resolve()})):
            with self.assertRaises(LiveFleetReached):
                self._promote("--home", str(store))

    def test_a_live_store_is_refused_before_anything_reads_it(self):
        """Refuse-before-touching, not read-then-object: `default_context` reads the store's
        `runtime.json` as soon as it has a home, so a check after it returns has already read the live
        store."""
        store = self.tmp / "store"
        with mock.patch.object(tests, "LIVE_STORES", frozenset({store.resolve()})), \
                mock.patch.object(cli, "read_runtime", wraps=cli.read_runtime) as read:
            with self.assertRaises(LiveFleetReached):
                self._promote("--home", str(store))
        self.assertEqual(read.call_count, 0, "the live store was read before the guard refused it")

    def test_it_fires_on_a_live_release_area(self):
        with mock.patch.object(tests, "LIVE_RELEASES", frozenset({self.releases.resolve()})):
            with self.assertRaises(LiveFleetReached):
                self._promote("--root", str(self.root))

    def _promote_with_ambient_instants(self):
        """A private store named by `FLEET_HOME` beside an INHERITED `FLEET_INSTANTS` — the shape of every
        dispatched session, whose `FLEET_INSTANTS` is the operator's live effort tree."""
        with hermetic_environment(self.tmp / "instants", home=self.home):
            os.environ["FLEET_HOME"] = str(self.tmp / "store")
            return cli.main(["release-promote", "--version", "0.1.0", "--releases", str(self.releases)],
                            stdout=io.StringIO(), stderr=io.StringIO())

    def test_it_fires_on_a_live_instants_tree(self):
        with mock.patch.object(tests, "LIVE_INSTANTS", frozenset({(self.tmp / "instants").resolve()})):
            with self.assertRaises(LiveFleetReached):
                self._promote_with_ambient_instants()

    def test_it_is_silent_on_a_fixture_s_own_instants_tree(self):
        self.assertEqual(self._promote_with_ambient_instants(), 4)

    def test_it_is_silent_on_a_fixture_s_own_root(self):
        """The same call with nothing marked live: the verb answers (a refusal — there is no release),
        so the guard is not what decides the outcome of a hermetic test."""
        self.assertEqual(self._promote("--root", str(self.root)), 4)

    def test_the_live_set_is_what_the_process_reaches_unaided(self):
        """The walk from the cwd under `$HOME`, plus what the environment names."""
        cwd = self.root / "deep" / "slot"
        cwd.mkdir(parents=True)
        roots, stores, releases, instants = tests._live_destinations(
            {"HOME": str(self.home), "FLEET_HOME": str(self.tmp / "h"),
             "FLEET_RELEASES": str(self.tmp / "r"), "FLEET_INSTANTS": str(self.tmp / "i")}, cwd)
        self.assertEqual(roots, {self.root.resolve()})
        self.assertEqual(stores, {self.root.resolve() / ".fleet", (self.tmp / "h").resolve()})
        self.assertEqual(releases, {self.root.resolve() / "fleet-releases", (self.tmp / "r").resolve()})
        self.assertEqual(instants, {self.root.resolve() / ".fleet" / "instants",
                                    (self.tmp / "h").resolve() / "instants", (self.tmp / "i").resolve()})

    def test_a_symlinked_store_or_release_area_is_compared_by_its_target(self):
        """The migration case `root.find` documents: a root's `.fleet` reached through a symlink. Every
        path the wrappers compare is resolved, so the live set must be resolved too or it never matches."""
        (self.tmp / "real-store").mkdir()
        (self.tmp / "real-releases").mkdir()
        (self.tmp / "real-instants").mkdir()
        (self.root / ".fleet").symlink_to(self.tmp / "real-store")
        (self.root / "fleet-releases").symlink_to(self.tmp / "real-releases")
        (self.tmp / "real-store" / "instants").symlink_to(self.tmp / "real-instants")
        _, stores, releases, instants = tests._live_destinations({"HOME": str(self.home)}, self.root)
        self.assertEqual(stores, {(self.tmp / "real-store").resolve()})
        self.assertEqual(releases, {(self.tmp / "real-releases").resolve()})
        self.assertEqual(instants, {(self.tmp / "real-instants").resolve()})

    def test_the_import_captures_the_live_set_from_the_real_process(self):
        """The call site itself, not `_live_destinations` with arguments a test chose: every other case
        here either passes its own arguments or patches `LIVE_*`, so a regression in what the package
        hands that function at import (the wrong cwd, an emptied environment) turned the guard off with
        the whole suite still green (RV-C1, mutation M3). A fresh interpreter imports `tests` from a cwd
        inside a fixture root, with every fleet variable naming a fixture path, and reports what it
        captured."""
        cwd = self.root / "slot"
        cwd.mkdir()
        fleet_dir = pathlib.Path(tests.__file__).resolve().parents[1]
        env = {name: value for name, value in os.environ.items() if name not in tests.FLEET_ENV}
        env.update(HOME=str(self.home), PYTHONPATH=f"{fleet_dir}{os.pathsep}{fleet_dir / 'src'}",
                   FLEET_HOME=str(self.tmp / "h"), FLEET_RELEASES=str(self.tmp / "r"),
                   FLEET_INSTANTS=str(self.tmp / "i"))
        report = ("import json, tests; print(json.dumps({name: sorted(map(str, getattr(tests, name))) "
                  "for name in ('LIVE_ROOTS', 'LIVE_STORES', 'LIVE_RELEASES', 'LIVE_INSTANTS')}))")
        done = subprocess.run([sys.executable, "-c", report], cwd=cwd, env=env, capture_output=True,
                              text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        root = self.root.resolve()
        h, r, i = ((self.tmp / name).resolve() for name in "hri")
        self.assertEqual(json.loads(done.stdout), {
            "LIVE_ROOTS": [str(root)],
            "LIVE_STORES": sorted([str(root / ".fleet"), str(h)]),
            "LIVE_RELEASES": sorted([str(root / "fleet-releases"), str(r)]),
            "LIVE_INSTANTS": sorted([str(root / ".fleet" / "instants"), str(h / "instants"), str(i)]),
        })

    def test_outside_home_with_nothing_exported_nothing_is_live(self):
        """`/tmp` is outside `$HOME`, so the walk (FI-417's bound) finds nothing there — which is why the
        suite from an export under `/tmp` could never reach a root, and could never pass a test that
        needed one."""
        self.assertEqual(tests._live_destinations({"HOME": str(self.home)}, self.tmp),
                         (frozenset(), frozenset(), frozenset(), frozenset()))


if __name__ == "__main__":
    unittest.main()
