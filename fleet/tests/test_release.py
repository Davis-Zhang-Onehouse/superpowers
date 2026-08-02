"""The release model: versions, layout, the history register, and the atomic flip."""
import os
import pathlib
import tempfile
import unittest

from fleet.release import (CANDIDATE, DEV, HISTORY_COLUMNS, RELEASED, Releases,
                           Version, tree_sha)
from fleet.errors import BadInput


class VersionCase(unittest.TestCase):
    def test_parse_and_render_round_trip(self):
        self.assertEqual(str(Version.parse("0.3.0")), "0.3.0")
        self.assertEqual(Version.parse("1.12.5"), Version(1, 12, 5))

    def test_a_malformed_version_is_bad_input(self):
        for bad in ("v0.3.0", "0.3", "0.3.0.1", "0.3.x", "", "latest"):
            with self.assertRaises(BadInput, msg=bad):
                Version.parse(bad)

    def test_ordering_is_numeric_not_lexical(self):
        # The bug this forbids: "0.10.0" < "0.9.0" under string sort, so `previous()` would pick the
        # wrong predecessor and the changelog would cover the wrong range.
        self.assertLess(Version.parse("0.9.0"), Version.parse("0.10.0"))
        self.assertEqual(max([Version.parse("0.9.0"), Version.parse("0.10.0")]), Version(0, 10, 0))

    def test_bump_kind_classifies_against_the_predecessor(self):
        prev = Version.parse("1.2.3")
        self.assertEqual(Version.parse("1.2.4").bump_kind(prev), "patch")
        self.assertEqual(Version.parse("1.3.0").bump_kind(prev), "minor")
        self.assertEqual(Version.parse("2.0.0").bump_kind(prev), "major")


class ReleasesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.rel = Releases(self.tmp / "releases")

    def _make(self, ver, state=CANDIDATE):
        v = Version.parse(ver)
        d = self.rel.dir_for(v)
        (d / ".release").mkdir(parents=True, exist_ok=True)
        self.rel.write_manifest(v, {"version": ver, "tag": f"fleet/v{ver}"})
        self.rel.set_state(v, state)
        return v

    def test_versions_are_discovered_and_ordered(self):
        self._make("0.9.0")
        self._make("0.10.0")
        self.assertEqual([str(v) for v in self.rel.versions()], ["0.9.0", "0.10.0"])

    def test_previous_is_the_highest_below_not_the_newest_directory(self):
        self._make("0.10.0")
        self._make("0.9.0")            # created LATER, lower version
        self.assertEqual(str(self.rel.previous(Version.parse("0.11.0"))), "0.10.0")

    def test_previous_of_the_first_release_is_none(self):
        v = self._make("0.1.0")
        self.assertIsNone(self.rel.previous(v))

    def test_manifest_round_trips_as_tab_separated_pairs(self):
        v = self._make("0.1.0")
        self.rel.write_manifest(v, {"version": "0.1.0", "notes": "first cut"})
        self.assertEqual(self.rel.manifest(v)["notes"], "first cut")
        raw = (self.rel.dir_for(v) / ".release" / "MANIFEST.tsv").read_text()
        self.assertIn("notes\tfirst cut", raw)

    def test_state_defaults_to_candidate_and_is_writable(self):
        v = self._make("0.1.0")
        self.assertEqual(self.rel.state(v), CANDIDATE)
        self.rel.set_state(v, RELEASED)
        self.assertEqual(self.rel.state(v), RELEASED)

    def test_current_label_reports_the_version_the_symlink_points_at(self):
        v = self._make("0.1.0")
        self.rel.point_current_at(self.rel.dir_for(v))
        self.assertEqual(self.rel.current_label(), "0.1.0")

    def test_current_label_says_DEV_when_it_points_outside_the_releases_root(self):
        checkout = self.tmp / "checkout"
        checkout.mkdir()
        self.rel.point_current_at(checkout)
        self.assertEqual(self.rel.current_label(), DEV)

    def test_current_label_is_none_when_nothing_is_deployed(self):
        self.rel.root.mkdir(parents=True, exist_ok=True)
        self.assertEqual(self.rel.current_label(), "none")

    def test_the_flip_never_leaves_current_absent(self):
        # The property, asserted the only way it can be: `current` must resolve at every instant, so a
        # reader interleaved with the flip sees the old target or the new one and never a missing path.
        #
        # The observer runs in ANOTHER THREAD, and that is the whole test. Sampling `current` after each
        # flip RETURNS -- which is how this case was first written -- passes for `unlink`-then-`symlink`
        # too, because by the time the call returns the link is back. The absent window exists only
        # *during* the flip, so nothing that looks between flips can ever see it, and a case that cannot
        # fail is not evidence (P-C).
        #
        # Measured both ways before trusting it: against `unlink`-then-`symlink`, 20 runs out of 20 saw
        # the gap, 13k-590k sightings per run. Against the `os.replace` flip, zero sightings in 20 runs.
        import threading
        a, b = self._make("0.1.0"), self._make("0.2.0")
        link = self.rel.root / "current"
        self.rel.point_current_at(self.rel.dir_for(a))
        stop = threading.Event()
        absent = []

        def watch():
            while not stop.is_set():
                if not link.exists():
                    absent.append(1)        # list.append is atomic under the GIL; this is just a counter

        reader = threading.Thread(target=watch)
        reader.start()
        try:
            for _ in range(200):
                self.rel.point_current_at(self.rel.dir_for(b))
                self.rel.point_current_at(self.rel.dir_for(a))
        finally:
            stop.set()
            reader.join()
        self.assertEqual(len(absent), 0,
                         f"current vanished during a flip: a concurrent reader saw it missing "
                         f"{len(absent)} times, and every davis_root shell's PATH resolves through it")

    def test_history_appends_a_well_formed_row_with_a_header(self):
        self.rel.append_history(action="DEPLOY", version="0.1.0", from_version="DEV",
                                actor="davis@onehouse.ai", host="box", reason="first", evidence="-")
        text = (self.rel.root / "RELEASE-HISTORY.tsv").read_text()
        self.assertTrue(text.startswith("\t".join(HISTORY_COLUMNS)))
        rows = self.rel.history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "DEPLOY")
        self.assertEqual(rows[0]["from_version"], "DEV")

    def test_a_reason_containing_a_tab_or_newline_cannot_break_the_register(self):
        # A free-text reason is operator input. One stray tab would shift every later column, and the
        # corruption is silent -- the file still parses, into the wrong fields.
        self.rel.append_history(action="ROLLBACK", version="0.1.0", from_version="0.2.0",
                                actor="a", host="b", reason="broke\ton\nharvest", evidence="-")
        rows = self.rel.history()
        self.assertEqual(len(rows), 1)
        self.assertNotIn("\t", rows[0]["reason"])
        self.assertIn("broke", rows[0]["reason"])

    def test_concurrent_appends_produce_two_whole_rows(self):
        import threading
        threads = [threading.Thread(target=self.rel.append_history, kwargs=dict(
            action="DEPLOY", version=f"0.0.{i}", from_version="-", actor="a", host="b",
            reason=f"r{i}", evidence="-")) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        rows = self.rel.history()
        self.assertEqual(len(rows), 8)
        self.assertEqual(len({r["version"] for r in rows}), 8)

    def test_tree_sha_is_stable_across_a_copy_and_ignores_the_release_dir(self):
        import shutil
        src = self.tmp / "exp"
        (src / "bin").mkdir(parents=True)
        (src / "bin" / "fleet").write_text("#!/bin/sh\n")
        (src / ".release").mkdir()
        (src / ".release" / "STATE").write_text(CANDIDATE)
        dst = self.tmp / "copy"
        shutil.copytree(src, dst)
        (dst / ".release" / "STATE").write_text(RELEASED)     # metadata differs, payload does not
        self.assertEqual(tree_sha(src), tree_sha(dst))

    def test_tree_sha_changes_when_a_payload_file_changes(self):
        # Without this the previous test passes for a tree_sha that returns a constant.
        src = self.tmp / "exp2"
        (src / "bin").mkdir(parents=True)
        (src / "bin" / "fleet").write_text("#!/bin/sh\n")
        before = tree_sha(src)
        (src / "bin" / "fleet").write_text("#!/bin/sh\necho hi\n")
        self.assertNotEqual(before, tree_sha(src))

    def test_tree_sha_notices_a_mode_change(self):
        src = self.tmp / "exp3"
        src.mkdir()
        f = src / "run.sh"
        f.write_text("x")
        before = tree_sha(src)
        f.chmod(0o755)
        self.assertNotEqual(before, tree_sha(src),
                            "an executable bit is part of the artifact; a launcher that lost +x is broken")
