"""Discovery: the marker, the upward walk, and every refusal.

The walk is the whole of "which fleet am I in", so its boundaries are asserted rather than assumed —
especially the one that does NOT fire (a marker at `$HOME`), because a deliberate non-effect that nobody
tests is indistinguishable from a bug.
"""
import json
import pathlib
import tempfile
import unittest

from fleet import root as root_mod
from fleet.errors import BadInput


def _mark(d: pathlib.Path, name: str) -> pathlib.Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / root_mod.MARKER).write_text(json.dumps({"name": name}))
    return d


class TestFind(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()

    def test_finds_the_marker_in_the_directory_itself(self):
        r = _mark(self.home / "a_root", "a")
        self.assertEqual(root_mod.find(r, self.home), r)

    def test_finds_the_marker_several_levels_up(self):
        r = _mark(self.home / "a_root", "a")
        deep = r / "operations" / "tasks" / "eff" / "instants"
        deep.mkdir(parents=True)
        self.assertEqual(root_mod.find(deep, self.home), r)

    def test_nearest_marker_wins(self):
        outer = _mark(self.home / "a_root", "a")
        inner = _mark(outer / "nested", "inner")
        self.assertEqual(root_mod.find(inner / "x", self.home), inner)

    def test_a_marker_at_home_is_never_found(self):
        """A marker at `$HOME` would silently re-merge every root: it would look exactly like the feature
        working and behave exactly like the feature absent."""
        _mark(self.home, "everything")
        d = self.home / "a_root" / "deep"
        d.mkdir(parents=True)
        self.assertIsNone(root_mod.find(d, self.home))

    def test_no_marker_returns_none(self):
        d = self.home / "a_root" / "deep"
        d.mkdir(parents=True)
        self.assertIsNone(root_mod.find(d, self.home))

    def test_a_directory_outside_home_walks_nowhere(self):
        """Not to `/`. A path on another branch of the filesystem has no root above it by construction."""
        outside = self.tmp / "elsewhere" / "deep"
        outside.mkdir(parents=True)
        self.assertIsNone(root_mod.find(outside, self.home))

    def test_a_marker_that_is_a_directory_is_not_a_marker(self):
        d = self.home / "a_root"
        (d / root_mod.MARKER).mkdir(parents=True)
        self.assertIsNone(root_mod.find(d, self.home))

    def test_the_instant_store_directory_is_not_mistaken_for_a_root(self):
        """An instant carries its own `<instant>/.fleet/`. A walk keyed on `.fleet` would stop at the
        first instant it passed through and call it a root, which is why the marker has its own name."""
        r = _mark(self.home / "a_root", "a")
        instant = r / "operations" / "tasks" / "eff" / "instants" / "00000000-1-inflight-append-x"
        (instant / ".fleet").mkdir(parents=True)
        self.assertEqual(root_mod.find(instant / ".fleet", self.home), r)


class TestLoad(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve()

    def test_reads_the_declared_name(self):
        r = _mark(self.tmp / "davis_root", "davis")
        self.assertEqual(root_mod.load(r).name, "davis")

    def test_the_name_is_declared_not_derived_from_the_directory(self):
        """`FI-421`: a fix for a dead path constant shipped WITH a silent fallback because it slugified a
        directory into a name. A declared name has no derivation to get wrong."""
        r = _mark(self.tmp / "davis_root", "totally-different")
        self.assertEqual(root_mod.load(r).name, "totally-different")

    def test_derived_paths_hang_off_the_root(self):
        r = _mark(self.tmp / "davis_root", "davis")
        loaded = root_mod.load(r)
        self.assertEqual(loaded.store, r / ".fleet")
        self.assertEqual(loaded.releases, r / "fleet-releases")
        self.assertEqual(loaded.socket, "fleet-davis")

    def test_a_marker_that_is_not_json_is_refused(self):
        r = self.tmp / "r"
        r.mkdir()
        (r / root_mod.MARKER).write_text("davis")
        with self.assertRaises(BadInput) as cm:
            root_mod.load(r)
        self.assertIn(str(r / root_mod.MARKER), str(cm.exception))

    def test_a_marker_with_no_name_is_refused(self):
        r = self.tmp / "r"
        r.mkdir()
        (r / root_mod.MARKER).write_text(json.dumps({}))
        with self.assertRaises(BadInput):
            root_mod.load(r)

    def test_a_blank_name_is_refused(self):
        r = self.tmp / "r"
        r.mkdir()
        (r / root_mod.MARKER).write_text(json.dumps({"name": "   "}))
        with self.assertRaises(BadInput):
            root_mod.load(r)

    def test_a_name_that_cannot_be_a_tmux_socket_is_refused(self):
        """The name becomes `fleet-<name>` as a tmux socket, and `tmux -L` treats a name containing `/`
        as a PATH — a different thing that silently works."""
        r = self.tmp / "r"
        r.mkdir()
        (r / root_mod.MARKER).write_text(json.dumps({"name": "a/b"}))
        with self.assertRaises(BadInput) as cm:
            root_mod.load(r)
        self.assertIn("tmux", str(cm.exception))

    def test_a_missing_marker_is_refused_naming_the_file(self):
        r = self.tmp / "r"
        r.mkdir()
        with self.assertRaises(BadInput) as cm:
            root_mod.load(r)
        self.assertIn(str(r / root_mod.MARKER), str(cm.exception))


class TestDiscover(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()

    def test_walks_and_loads(self):
        r = _mark(self.home / "davis_root", "davis")
        deep = r / "ws1" / "src"
        deep.mkdir(parents=True)
        found = root_mod.discover(deep, self.home)
        self.assertEqual((found.path, found.name), (r, "davis"))

    def test_no_marker_is_none_rather_than_an_error(self):
        d = self.home / "bare"
        d.mkdir()
        self.assertIsNone(root_mod.discover(d, self.home))

    def test_a_bad_marker_is_an_error_rather_than_none(self):
        """Distinct from 'no root': a marker that exists and cannot be read is a defect the operator must
        see, not a reason to fall through to another tier."""
        r = self.home / "davis_root"
        r.mkdir()
        (r / root_mod.MARKER).write_text("{")
        with self.assertRaises(BadInput):
            root_mod.discover(r, self.home)


class TestRefusal(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()

    def test_names_the_cwd_it_searched_from(self):
        d = self.home / "x"
        d.mkdir()
        self.assertIn(str(d), root_mod.refusal(d, self.home, "board"))

    def test_names_the_verb(self):
        d = self.home / "x"
        d.mkdir()
        self.assertIn("board", root_mod.refusal(d, self.home, "board"))

    def test_states_what_clears_it(self):
        d = self.home / "x"
        d.mkdir()
        self.assertIn("Clears when", root_mod.refusal(d, self.home, "board"))

    def test_a_marker_at_home_is_called_out_by_name(self):
        """A deliberate non-effect that the refusal does not explain reads as a bug."""
        _mark(self.home, "everything")
        d = self.home / "x"
        d.mkdir()
        msg = root_mod.refusal(d, self.home, "board")
        self.assertIn(str(self.home / root_mod.MARKER), msg)
        self.assertIn("every root the same root", msg)

    def test_no_marker_at_home_means_no_note_about_one(self):
        d = self.home / "x"
        d.mkdir()
        self.assertNotIn("every root the same root", root_mod.refusal(d, self.home, "board"))


if __name__ == "__main__":
    unittest.main()
