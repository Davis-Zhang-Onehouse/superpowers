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
        """`main` looks `default_context` up by name at call time, `_releases` does the same for
        `resolve_releases`, and every marker read goes through `root.load` — wrapped anywhere else, the
        guard would watch a name nobody calls."""
        for seam in (root_mod.load, cli.default_context, cli.resolve_releases):
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

    def test_it_fires_on_a_live_release_area(self):
        with mock.patch.object(tests, "LIVE_RELEASES", frozenset({self.releases.resolve()})):
            with self.assertRaises(LiveFleetReached):
                self._promote("--root", str(self.root))

    def test_it_is_silent_on_a_fixture_s_own_root(self):
        """The same call with nothing marked live: the verb answers (a refusal — there is no release),
        so the guard is not what decides the outcome of a hermetic test."""
        self.assertEqual(self._promote("--root", str(self.root)), 4)

    def test_the_live_set_is_what_the_process_reaches_unaided(self):
        """The walk from the cwd under `$HOME`, plus what the environment names."""
        cwd = self.root / "deep" / "slot"
        cwd.mkdir(parents=True)
        roots, stores, releases = tests._live_destinations(
            {"HOME": str(self.home), "FLEET_HOME": str(self.tmp / "h"),
             "FLEET_RELEASES": str(self.tmp / "r")}, cwd)
        self.assertEqual(roots, {self.root.resolve()})
        self.assertEqual(stores, {self.root.resolve() / ".fleet", (self.tmp / "h").resolve()})
        self.assertEqual(releases, {self.root.resolve() / "fleet-releases", (self.tmp / "r").resolve()})

    def test_a_symlinked_store_or_release_area_is_compared_by_its_target(self):
        """The migration case `root.find` documents: a root's `.fleet` reached through a symlink. Every
        path the wrappers compare is resolved, so the live set must be resolved too or it never matches."""
        (self.tmp / "real-store").mkdir()
        (self.tmp / "real-releases").mkdir()
        (self.root / ".fleet").symlink_to(self.tmp / "real-store")
        (self.root / "fleet-releases").symlink_to(self.tmp / "real-releases")
        _, stores, releases = tests._live_destinations({"HOME": str(self.home)}, self.root)
        self.assertEqual(stores, {(self.tmp / "real-store").resolve()})
        self.assertEqual(releases, {(self.tmp / "real-releases").resolve()})

    def test_outside_home_with_nothing_exported_nothing_is_live(self):
        """`/tmp` is outside `$HOME`, so the walk (FI-417's bound) finds nothing there — which is why the
        suite from an export under `/tmp` could never reach a root, and could never pass a test that
        needed one."""
        self.assertEqual(tests._live_destinations({"HOME": str(self.home)}, self.tmp),
                         (frozenset(), frozenset(), frozenset()))


if __name__ == "__main__":
    unittest.main()
