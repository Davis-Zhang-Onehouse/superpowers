"""The six-tier resolution chain, as a pure function of (flags, env, cwd, disk).

Every tier gets a case and so does the refusal. Tiers 1 and 3 are the REGRESSION half and are marked as
such: 1291 occurrences across 238 files name the store with `--home` or `FLEET_HOME`, and none of them may
move. A change here that breaks one of those is not a test failure, it is the whole IT suite going dark.
"""
import io
import json
import pathlib
import tempfile
import unittest

from fleet import cli
from fleet.errors import BadInput
from fleet.root import MARKER


def _mark(d: pathlib.Path, name: str) -> pathlib.Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / MARKER).write_text(json.dumps({"name": name}))
    return d


class ResolutionCase(unittest.TestCase):
    """A `$HOME` with one marked root, `davis_root`, whose `ws1` is the working directory."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.root = _mark(self.home / "davis_root", "davis")
        self.cwd = self.root / "ws1"
        self.cwd.mkdir()

    def env(self, **over) -> dict:
        return dict({"HOME": str(self.home)}, **over)

    def parsed(self, verb: str, *flags):
        return cli.parse(cli.VERBS[verb], list(flags))

    def other_root(self, name="davis2"):
        return _mark(self.home / f"{name}_root", name)


class TestRootTier(ResolutionCase):
    def test_tier5_marker_walk(self):
        found = cli.resolve_root(self.parsed("board"), self.env(), self.cwd)
        self.assertEqual((found.path, found.name), (self.root, "davis"))

    def test_tier4_fleet_root_env_beats_the_marker(self):
        other = self.other_root()
        found = cli.resolve_root(self.parsed("board"), self.env(FLEET_ROOT=str(other)), self.cwd)
        self.assertEqual(found.name, "davis2")

    def test_tier2_root_flag_beats_the_env(self):
        other = self.other_root()
        found = cli.resolve_root(self.parsed("board", "--root", str(other)),
                                 self.env(FLEET_ROOT=str(self.root)), self.cwd)
        self.assertEqual(found.name, "davis2")

    def test_no_marker_and_no_naming_resolves_to_none(self):
        bare = self.tmp / "bare"
        bare.mkdir()
        self.assertIsNone(cli.resolve_root(self.parsed("board"), self.env(), bare))

    def test_a_named_root_with_no_marker_is_refused_rather_than_ignored(self):
        empty = self.home / "not_a_root"
        empty.mkdir()
        with self.assertRaises(BadInput):
            cli.resolve_root(self.parsed("board"), self.env(FLEET_ROOT=str(empty)), self.cwd)


class TestHomeTier(ResolutionCase):
    def home_of(self, parsed, env=None, cwd=None):
        return cli.resolve_home(parsed, env or self.env(), cwd or self.cwd)

    def test_tier1_home_flag_wins_over_everything(self):
        """REGRESSION: 1291 explicit call sites depend on this and none may move."""
        named = self.tmp / "sandbox"
        home, source = self.home_of(self.parsed("board", "--home", str(named)),
                                    self.env(FLEET_HOME="/nope", FLEET_ROOT=str(self.root)))
        self.assertEqual(home, named)
        self.assertEqual(source, "--home")

    def test_tier3_fleet_home_env_wins_over_the_marker(self):
        """REGRESSION: this is how every IT section names its sandbox store (`lib.sh` it_section)."""
        named = self.tmp / "sandbox"
        home, source = self.home_of(self.parsed("board"), self.env(FLEET_HOME=str(named)))
        self.assertEqual(home, named)
        self.assertEqual(source, "$FLEET_HOME")

    def test_tier5_home_derives_from_the_marker(self):
        home, source = self.home_of(self.parsed("board"))
        self.assertEqual(home, self.root / ".fleet")
        self.assertIn("marker at", source)

    def test_tier6_refuses_a_read_not_only_a_write(self):
        """Revises `SI-15`. Under isolation a permissive read does not answer about no fleet — it answers
        about a DIFFERENT ROOT's fleet, confidently, with a population line. `FI-417`'s shape."""
        bare = self.tmp / "bare"
        bare.mkdir()
        self.assertTrue(cli.VERBS["board"].read_only, "board must be read-only or this case is vacuous")
        with self.assertRaises(BadInput) as cm:
            self.home_of(self.parsed("board"), cwd=bare)
        self.assertIn(str(bare), str(cm.exception))

    def test_no_fallback_to_dollar_home_dot_fleet(self):
        """The old default, and what made a read answer about a shared store."""
        (self.home / ".fleet" / "records").mkdir(parents=True)
        bare = self.tmp / "bare"
        bare.mkdir()
        with self.assertRaises(BadInput):
            self.home_of(self.parsed("board"), cwd=bare)

    def test_the_refusal_does_not_create_anything(self):
        """A refusal that also created the store would satisfy an rc-only assertion while defeating the
        point of refusing."""
        bare = self.tmp / "bare"
        bare.mkdir()
        with self.assertRaises(BadInput):
            self.home_of(self.parsed("board"), cwd=bare)
        self.assertEqual(list(bare.iterdir()), [])


class TestInstantsTier(ResolutionCase):
    #: `dispatch`'s required flags. Supplied on EVERY case here, because `parse` refuses a missing
    #: required flag before any resolver runs and appends the usage dump — which contains
    #: `--instants-dir ... overrides $FLEET_INSTANTS`. Written without them, the SI-56 case passed before
    #: the fix existed, matching the usage text rather than the refusal.
    DISPATCH_REQ = ("--profile", "/p", "--title", "t")

    def instants_of(self, parsed, env=None, cwd=None):
        return cli.resolve_instants(parsed, env or self.env(), cwd or self.cwd)

    def test_an_explicit_home_still_implies_its_instants(self):
        """REGRESSION: `--home X` has always meant instants `X/instants`, and IT sections rely on it."""
        named = self.tmp / "sandbox"
        self.assertEqual(self.instants_of(self.parsed("dispatch", *self.DISPATCH_REQ, "--home", str(named))),
                         named / "instants")

    def test_instants_dir_flag_wins(self):
        named = self.tmp / "elsewhere"
        self.assertEqual(
            self.instants_of(self.parsed("dispatch", *self.DISPATCH_REQ, "--home", str(self.tmp / "s"),
                                         "--instants-dir", str(named))),
            named)

    def test_fleet_instants_env_is_honoured(self):
        named = self.tmp / "elsewhere"
        self.assertEqual(self.instants_of(self.parsed("dispatch", *self.DISPATCH_REQ),
                                          self.env(FLEET_INSTANTS=str(named))), named)

    def test_fleet_home_env_still_implies_its_instants(self):
        """REGRESSION: `it_section` exports both, but three IT runners export only FLEET_HOME."""
        named = self.tmp / "sandbox"
        self.assertEqual(self.instants_of(self.parsed("dispatch", *self.DISPATCH_REQ),
                                          self.env(FLEET_HOME=str(named))), named / "instants")

    def test_a_derived_home_DOES_derive_instants_for_a_read(self):
        """The resolver always answers. `reconcile` and `guards.blocking_compactions` read this on the
        READ path, so refusing here would refuse `board` — and a read that enumerates an empty derived
        directory harms nobody. The refusal belongs at the CREATE sites; see below."""
        self.assertEqual(self.instants_of(self.parsed("board")), self.root / ".fleet" / "instants")

    def test_creating_an_instant_in_a_directory_nobody_named_is_refused(self):
        """`SI-56` / `FI-382`: with `FLEET_INSTANTS` unset, dispatch planted a child in
        `$FLEET_HOME/instants` at rc=0 with all four guards green. Nothing downstream ever disagreed —
        every verb resolves the child through its record — so the damage surfaced only at the endgame
        compaction, when the instant was not in the directory being enumerated.

        NOT fixed by isolation, which the spec's shorthand got wrong: under isolation the stray lands at
        `$ROOT/.fleet/instants`, the right root and still the wrong tree. The harm was always intra-root.

        The required flags are supplied deliberately. Written without them this case PASSED before the fix
        existed: `parse` refuses the missing `--profile`/`--title` first and appends the usage dump, which
        contains `--instants-dir ... overrides $FLEET_INSTANTS` — so the assertion matched the usage text
        rather than the refusal. A true assertion answering the wrong question, caught only by running it
        red.
        """
        parsed = self.parsed("dispatch", *self.DISPATCH_REQ)
        with self.assertRaises(BadInput) as cm:
            cli.require_named_instants(parsed, self.env())
        self.assertIn("SI-56", str(cm.exception),
                      "must be the guard's refusal, not a usage dump that happens to name the flag")

    def test_naming_the_instants_directory_clears_the_create_guard(self):
        parsed = self.parsed("dispatch", *self.DISPATCH_REQ, "--instants-dir", str(self.tmp / "i"))
        cli.require_named_instants(parsed, self.env())

    def test_every_handler_that_bootstraps_an_instant_reaches_the_guard(self):
        """Non-drift, in the shape this package already uses for DELETE_ALLOWLIST: derived from the AST,
        so a THIRD creating verb cannot be added without the guard. The `fleet/CLAUDE.md` add-a-verb
        checklist exists because hand-maintained parallel lists drift, and this is one more of them."""
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(cli))
        creators, guarded = set(), set()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.FunctionDef) and node.name.startswith("_do_")):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    name = getattr(sub.func, "attr", getattr(sub.func, "id", ""))
                    if name == "bootstrap":
                        creators.add(node.name)
                    if name == "require_named_instants":
                        guarded.add(node.name)
        self.assertTrue(creators, "found no handler calling layout.bootstrap — this check went blind")
        self.assertEqual(creators - guarded, set(),
                         "these handlers create an instant without require_named_instants")


class TestSocketTier(ResolutionCase):
    def socket_of(self, parsed, env=None, cwd=None):
        return cli.resolve_socket(parsed, env or self.env(), cwd or self.cwd)

    def test_the_socket_derives_from_the_declared_name(self):
        self.assertEqual(self.socket_of(self.parsed("board")), "fleet-davis")

    def test_an_explicit_socket_env_still_wins(self):
        """REGRESSION: `it_section` exports FLEET_TMUX_SOCKET for every IT section, and silently
        overriding it would point the whole suite at one server."""
        self.assertEqual(self.socket_of(self.parsed("board"), self.env(FLEET_TMUX_SOCKET="itfleet-H")),
                         "itfleet-H")

    def test_no_root_and_no_env_is_the_default_server(self):
        bare = self.tmp / "bare"
        bare.mkdir()
        self.assertIsNone(self.socket_of(self.parsed("board"), cwd=bare))

    def test_two_roots_get_two_sockets(self):
        other = self.other_root()
        self.assertNotEqual(self.socket_of(self.parsed("board")),
                            self.socket_of(self.parsed("board"), self.env(FLEET_ROOT=str(other))))


class TestRootLine(ResolutionCase):
    """`FI-421`'s second defect — a function written to remove a silent fallback shipping WITH one — was
    caught only by PRINTING the resolved path. Its own words: *"reading the code would not have shown it;
    printing the resolved path did."* A chain with five tiers above a refusal prints where it landed.

    On stderr, never stdout: `test_cli` asserts stdout parses to its declared column count and IT §A parses
    `--porcelain` byte-for-byte. The cadence line already established stderr as this channel.

    `main` reads the REAL `os.environ` and the REAL cwd — it takes neither as an argument — so these cases
    patch both. Written without that they measured the developer's own exported `FLEET_HOME` and reported
    `root /home/ubuntu ($FLEET_HOME)`, which is a true line about the wrong fleet.
    """

    def setUp(self):
        super().setUp()
        import os
        from unittest import mock
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("FLEET_HOME", "FLEET_INSTANTS", "FLEET_ROOT", "FLEET_TMUX_SOCKET")}
        clean["HOME"] = str(self.home)
        patcher = mock.patch.dict(os.environ, clean, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        here = os.getcwd()
        self.addCleanup(os.chdir, here)

    def run_main(self, argv, cwd=None):
        import os
        os.chdir(cwd or self.cwd)
        out, err = io.StringIO(), io.StringIO()
        cli.main(argv, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_the_root_line_goes_to_stderr_and_names_its_source(self):
        _, err = self.run_main(["board", "--home", str(self.tmp / "s")])
        self.assertIn("root ", err)
        self.assertIn("--home", err)

    def test_the_root_line_is_absent_from_stdout(self):
        """An accept-direction assertion cannot be red first, so it is paired with a non-emptiness check.
        Human mode deliberately, not `--porcelain`: an empty store emits ZERO porcelain rows, so the
        `--porcelain` form of this case would pass on empty stdout and prove nothing."""
        out, err = self.run_main(["board", "--home", str(self.tmp / "s")])
        self.assertTrue(out.strip(), "stdout is empty, so 'no root line on stdout' is vacuous")
        self.assertNotIn("root ", out)
        self.assertIn("root ", err)

    def test_a_derived_root_prints_the_marker_it_came_from(self):
        _, err = self.run_main(["board"])
        self.assertIn(str(self.root / MARKER), err)

    def test_an_unmarked_directory_refuses_and_says_so(self):
        bare = self.tmp / "bare"
        bare.mkdir()
        import os
        os.chdir(bare)
        out, err = io.StringIO(), io.StringIO()
        rc = cli.main(["board"], stdout=out, stderr=err)
        self.assertEqual(rc, 2)
        self.assertIn(str(bare), err.getvalue())


class TestContainment(ResolutionCase):
    """`G1`. The obvious form of this guard would be vacuous and it is worth saying why: records live
    INSIDE the store, so a verb run in root A can never accidentally resolve root B's record — it would not
    find it. What it CAN do is write a record in A whose CONTENTS point into B, which is `FI-382` one level
    out."""

    def test_a_path_outside_the_root_is_refused_naming_both(self):
        other = self.other_root()
        foreign = other / "instants"
        foreign.mkdir()
        with self.assertRaises(BadInput) as cm:
            cli.assert_within_root(foreign, self.root, "instants directory")
        self.assertIn(str(self.root), str(cm.exception))
        self.assertIn(str(foreign), str(cm.exception))

    def test_a_path_inside_the_root_is_accepted(self):
        inside = self.root / "operations"
        inside.mkdir()
        cli.assert_within_root(inside, self.root, "instants directory")

    def test_the_root_itself_is_inside_itself(self):
        cli.assert_within_root(self.root, self.root, "instants directory")

    def test_a_sibling_with_a_shared_prefix_is_outside(self):
        """String containment is not path containment: `/x/davis_root2` starts with `/x/davis_root`."""
        sibling = self.home / "davis_root2"
        sibling.mkdir()
        with self.assertRaises(BadInput):
            cli.assert_within_root(sibling, self.root, "instants directory")


if __name__ == "__main__":
    unittest.main()


class TestReleasesTier(ResolutionCase):
    """The release area. Its old read-only default was `~/.fleet-releases`, a path that does not exist on
    this box — the real one is `<root>/fleet-releases`. So root derivation replaces a PHANTOM default with
    a correct one, rather than merely moving a working one.
    """

    def releases_of(self, parsed, env=None, cwd=None):
        return cli.resolve_releases(parsed, env or self.env(), cwd or self.cwd)

    def test_the_flag_wins(self):
        named = self.tmp / "rel"
        self.assertEqual(self.releases_of(self.parsed("release-status", "--releases", str(named))).root,
                         named)

    def test_the_env_wins_over_the_marker(self):
        """REGRESSION: `fleet-env.sh` exports FLEET_RELEASES for every davis_root shell today."""
        named = self.tmp / "rel"
        self.assertEqual(
            self.releases_of(self.parsed("release-status"), self.env(FLEET_RELEASES=str(named))).root,
            named)

    def test_it_derives_from_the_marker(self):
        self.assertEqual(self.releases_of(self.parsed("release-status")).root,
                         self.root / "fleet-releases")

    def test_no_fallback_to_the_phantom_home_default(self):
        bare = self.tmp / "bare"
        bare.mkdir()
        with self.assertRaises(BadInput) as cm:
            self.releases_of(self.parsed("release-status"), cwd=bare)
        self.assertIn(str(bare), str(cm.exception))

    def test_a_mutating_verb_with_no_root_still_says_there_is_no_default_for_a_write(self):
        bare = self.tmp / "bare"
        bare.mkdir()
        self.assertFalse(cli.VERBS["release-promote"].read_only, "or this case is vacuous")
        #: `--version` supplied because `parse` refuses a missing required flag BEFORE any resolver runs,
        #: and appends a usage dump that names `--releases ... overrides $FLEET_RELEASES`. Third instance
        #: of that trap in this file; each one made an assertion match the usage text rather than the code.
        with self.assertRaises(BadInput) as cm:
            self.releases_of(self.parsed("release-promote", "--version", "v0.0.1"), cwd=bare)
        self.assertIn("no default for a write", str(cm.exception))
