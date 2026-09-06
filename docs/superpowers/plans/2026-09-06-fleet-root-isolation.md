# Fleet Root Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a `fleet` a property of a root directory under `$HOME`, discovered by walking up from cwd to a `.fleet-root` marker, so `~/davis_root` and `~/davis2_root` run non-interfering fleets.

**Architecture:** A new leaf module `fleet/src/fleet/root.py` owns discovery — the walk, the marker, and the refusal text — and imports only `fleet.errors`. `cli.py` owns precedence across six tiers and is the only place that knows about flags and environment. Nothing else in the package learns what a root is; `session`, `pool` and `store` receive resolved values as they do today.

**Tech Stack:** Python 3 stdlib only (`fleet` is zero-dependency by design), bash for the IT section and the consumer scripts.

**Spec:** `docs/superpowers/specs/2026-09-06-fleet-root-isolation-design.md`

## Global Constraints

- **Zero third-party dependencies.** `fleet` imports stdlib only. `root.py` imports `pathlib`, `json` and `fleet.errors`.
- **`SCHEMA_VERSION` stays `1`.** `store.Record.from_json` refuses on a version mismatch *and* on unknown fields (`store.py:73-82`). Bumping it would refuse all 75 live records. The new `root` field is added with a `""` default at version 1.
- **An empty `root` on a record is NOT MEASURED, never a mismatch.** Pre-isolation records carry no root. Reading absence as an answer is `FI-417`.
- **Refusals name what clears them and who clears them.** Every new refusal states the cwd searched, the tiers tried, and the concrete fix.
- **G2 prints to stderr, never stdout.** `test_cli.py` asserts stdout parses to its declared column count and §A parses `--porcelain` byte-for-byte. The cadence line already establishes stderr as the channel for out-of-band context.
- **Tiers 1 and 3 must resolve exactly as they do today.** 1291 occurrences across 238 files name the store with `--home`/`FLEET_HOME`.
- **Run bash scripts under `bash`, never `zsh`.** zsh does not word-split unquoted expansions; this has cost two sessions already.
- **Never edit a script while it is executing.** bash reads scripts incrementally by byte offset.
- **`fleet/it/RESULTS.tsv` is tracked and is read by `lint-skill.py`.** Standalone IT runs must set `IT_RESULTS` to a scratch path or they clobber it.

---

## File Structure

| file | responsibility |
|---|---|
| `fleet/src/fleet/root.py` | **new.** The marker, the upward walk, the refusal text. A leaf: imports `fleet.errors` only. |
| `fleet/tests/test_root.py` | **new.** Table-driven cases for the walk, the marker, and every refusal. |
| `fleet/src/fleet/cli.py` | precedence across the six tiers; the stderr root line; dispatch containment |
| `fleet/src/fleet/store.py` | `Record.root` field, defaulted, at schema version 1 |
| `fleet/src/fleet/pool.py` | `Pool.enroll` refuses a workspace outside the root |
| `fleet/it/run-R.sh` | **new.** Two marked roots side by side, R1–R7 |
| `fleet/it/run-all.sh` | §R joins the gate roster |
| `fleet/it/lib.sh` | the stale comment at `:118-127`; the leak-watch list at `:481` |
| `scripts/fleet-env.sh` | derive from the marker; export no literal paths |
| `scripts/claude-watchdog.sh` | derive `DAVIS`; learn the per-root socket |
| `bin/fleet-view` | print the resolved root instead of `"defaults to ~/.fleet"` |
| `scripts/fleet-migrate-root.sh` | **new.** The one-shot migration, idempotent and reversible |

---

### Task 1: `root.py` — discovery

**Files:**
- Create: `fleet/src/fleet/root.py`
- Test: `fleet/tests/test_root.py`

**Interfaces:**
- Consumes: `fleet.errors.BadInput`
- Produces:
  - `MARKER = ".fleet-root"`
  - `@dataclass(frozen=True) class Root: path: pathlib.Path; name: str`
  - `find(start: Path, home: Path) -> Optional[Path]` — the directory holding the marker, or None
  - `load(root_dir: Path) -> Root` — parse the marker, raise `BadInput` on a bad one
  - `discover(cwd: Path, home: Path) -> Optional[Root]` — `find` then `load`
  - `refusal(cwd: Path, home: Path, verb: str) -> str` — the tier-6 message

- [ ] **Step 1: Write the failing test**

```python
# fleet/tests/test_root.py
import json
import pathlib
import unittest

from fleet import root as root_mod
from fleet.errors import BadInput


def _mark(d: pathlib.Path, name: str) -> pathlib.Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / root_mod.MARKER).write_text(json.dumps({"name": name}))
    return d


class TestFind(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = pathlib.Path(tempfile.mkdtemp())
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
        """A marker at $HOME would silently re-merge every root: it would look like the feature
        working and behave like the feature absent."""
        _mark(self.home, "everything")
        d = self.home / "a_root" / "deep"
        d.mkdir(parents=True)
        self.assertIsNone(root_mod.find(d, self.home))

    def test_no_marker_returns_none(self):
        d = self.home / "a_root" / "deep"
        d.mkdir(parents=True)
        self.assertIsNone(root_mod.find(d, self.home))

    def test_a_directory_outside_home_walks_nowhere(self):
        outside = self.tmp / "elsewhere" / "deep"
        outside.mkdir(parents=True)
        self.assertIsNone(root_mod.find(outside, self.home))


class TestLoad(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def test_reads_the_declared_name(self):
        r = _mark(self.tmp / "davis_root", "davis")
        self.assertEqual(root_mod.load(r).name, "davis")

    def test_the_name_is_declared_not_derived_from_the_directory(self):
        """FI-421: a fix for a dead path constant shipped with a silent fallback because it
        slugified a directory into a name. A declared name has no derivation to get wrong."""
        r = _mark(self.tmp / "davis_root", "totally-different")
        self.assertEqual(root_mod.load(r).name, "totally-different")

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

    def test_a_name_that_cannot_be_a_tmux_socket_is_refused(self):
        """The name becomes `fleet-<name>` as a tmux socket. A `/` in it would make the socket a
        path, which is a different thing that silently works."""
        r = self.tmp / "r"
        r.mkdir()
        (r / root_mod.MARKER).write_text(json.dumps({"name": "a/b"}))
        with self.assertRaises(BadInput):
            root_mod.load(r)


class TestRefusal(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.home.mkdir()

    def test_names_the_cwd_it_searched_from(self):
        d = self.home / "x"
        d.mkdir()
        self.assertIn(str(d), root_mod.refusal(d, self.home, "board"))

    def test_a_marker_at_home_is_called_out_by_name(self):
        _mark(self.home, "everything")
        d = self.home / "x"
        d.mkdir()
        msg = root_mod.refusal(d, self.home, "board")
        self.assertIn(str(self.home / root_mod.MARKER), msg)
        self.assertIn("every root the same root", msg)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd fleet && PYTHONPATH=src python3 -m pytest tests/test_root.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'fleet.root'`

- [ ] **Step 3: Write `root.py`**

```python
"""Which fleet am I in? — the root marker and the walk that finds it.

A fleet is a property of a DIRECTORY, not of an exported variable. `~/davis_root` and `~/davis2_root`
each carry a `.fleet-root` marker, and every path `fleet` uses derives from whichever marker is found by
walking up from the working directory. Two roots on one box then share nothing: not a record, not a slot,
not a tmux server, not a release area.

**The name is DECLARED in the marker, never derived from the directory.** It is what the tmux socket is
built from. `FI-421` is why: a fix written to remove a dead path constant shipped WITH a silent fallback,
because it slugified a directory into a name with `replace("/", "-")` while the harness also maps `_` to
`-`, so `davis_root` and `davis-root` silently diverged. The function written to remove a silent fallback
had one. A declared name has no derivation to get wrong, and it does not move when somebody renames a
directory.

**The marker is `.fleet-root`, and the store is `.fleet/`.** Two names on purpose: an instant carries its
own `<instant>/.fleet/` (`roadmap.py`), so a walk keyed on `.fleet` would stop at the first instant it
passed through and call it a root.

**The walk stops BELOW `$HOME`.** A marker at `$HOME` would make every root the same root — silently. It
would look exactly like this feature working and behave exactly like it absent, which is the worst of the
two failures available. So it is never honoured, and `refusal` names it directly when it exists, because a
refusal that does not explain a deliberate non-effect reads as a bug.

This module is a leaf: it imports `fleet.errors` and nothing else from the package. It performs exactly one
kind of I/O — testing for and reading the marker — and makes no decision about precedence. Which tier wins
is `cli`'s business, and keeping that out of here is what lets the whole resolution chain be tested as a
pure function of (flags, env, cwd, disk).
"""
import json
import pathlib
from dataclasses import dataclass

from fleet.errors import BadInput

#: The file that says "a fleet lives here". Distinct from the `.fleet/` store — see the module docstring.
MARKER = ".fleet-root"

#: A root name becomes `fleet-<name>` as a tmux socket name. `-L` with a `/` in it is a PATH rather than a
#: name, which is a different thing that silently works, so the characters are bounded here rather than
#: discovered at the first `tmux` call.
_NAME_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")


@dataclass(frozen=True)
class Root:
    """A resolved root: where it is, and what it calls itself."""

    path: pathlib.Path
    name: str

    @property
    def store(self) -> pathlib.Path:
        return self.path / ".fleet"

    @property
    def releases(self) -> pathlib.Path:
        return self.path / "fleet-releases"

    @property
    def socket(self) -> str:
        return f"fleet-{self.name}"


def find(start: pathlib.Path, home: pathlib.Path):
    """The directory holding the marker at or above `start`, or None.

    `start` and `home` are both resolved before comparison: during migration `~/.fleet` and
    `~/davis_root/.fleet` are the same directory reached two ways, and an unresolved comparison would
    manufacture a difference between them.
    """
    start = pathlib.Path(start).resolve()
    home = pathlib.Path(home).resolve()
    for candidate in [start, *start.parents]:
        if candidate == home or home not in candidate.parents:
            #: At or above $HOME. `home not in parents` also covers a path on a different branch of the
            #: filesystem entirely, which walks nowhere rather than to `/`.
            break
        if (candidate / MARKER).is_file():
            return candidate
    return None


def load(root_dir: pathlib.Path) -> Root:
    """Parse the marker in `root_dir`. Every failure names the file, because the reader's next act is to
    open it."""
    root_dir = pathlib.Path(root_dir)
    marker = root_dir / MARKER
    try:
        body = json.loads(marker.read_text())
    except (OSError, ValueError) as exc:
        raise BadInput(
            f"{marker} is not readable as JSON ({exc}). The marker is a JSON object naming this root, "
            f'for example: {{"name": "davis"}}') from None
    if not isinstance(body, dict) or not str(body.get("name") or "").strip():
        raise BadInput(
            f'{marker} declares no name. It must be a JSON object with a non-empty "name", for example: '
            f'{{"name": "davis"}}. The name is DECLARED rather than derived from the directory because it '
            f"becomes this root's tmux socket, and a socket name must not change when a directory is "
            f"renamed (FI-421).")
    name = str(body["name"]).strip()
    bad = sorted(set(name) - _NAME_OK)
    if bad:
        raise BadInput(
            f"{marker} declares name {name!r}, which contains {bad}. The name becomes the tmux socket "
            f"`fleet-{name}`, and `tmux -L` treats a name containing `/` as a PATH — a different thing "
            f"that silently works. Use letters, digits, `_`, `-` or `.`.")
    return Root(path=root_dir.resolve(), name=name)


def discover(cwd: pathlib.Path, home: pathlib.Path):
    """The root for a working directory, or None when there is no marker at or above it."""
    found = find(cwd, home)
    return None if found is None else load(found)


def refusal(cwd: pathlib.Path, home: pathlib.Path, verb: str) -> str:
    """Why no root could be resolved, and what clears it."""
    cwd = pathlib.Path(cwd).resolve()
    home = pathlib.Path(home).resolve()
    lines = [
        f"{verb!r} could not tell which fleet it belongs to: there is no {MARKER} at or above {cwd} "
        f"(searched up to, and excluding, {home}).",
        f"Clears when: create {MARKER} in this fleet's root directory, for example "
        f'`echo \'{{"name": "davis"}}\' > {home}/davis_root/{MARKER}` — or name the destination '
        f"explicitly with `--root <path>`, `--home <path>`, or by exporting FLEET_ROOT or FLEET_HOME.",
    ]
    if (home / MARKER).is_file():
        lines.append(
            f"NOTE: there IS a {MARKER} at {home / MARKER}, and it is deliberately not honoured — a "
            f"marker there makes every root the same root, which looks exactly like isolation working "
            f"and behaves exactly like isolation absent. Put it at {home}/<root>/{MARKER} instead.")
    return " ".join(lines)
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd fleet && PYTHONPATH=src python3 -m pytest tests/test_root.py -q`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add fleet/src/fleet/root.py fleet/tests/test_root.py
git commit -m "root: a fleet is a directory, found by walking up to its marker"
```

---

### Task 2: precedence in `cli.py`

**Files:**
- Modify: `fleet/src/fleet/cli.py:487-521` (`default_context`), `:3246-3258` (`_releases`), the `Flag` table for `--root`
- Test: `fleet/tests/test_root_resolution.py` (create)

**Interfaces:**
- Consumes: `root.discover`, `root.refusal`, `root.Root`
- Produces: `resolve_root(parsed, environ, cwd) -> Optional[Root]` in `cli.py`, used by `default_context` and `_releases`

- [ ] **Step 1: Write the failing test**

```python
# fleet/tests/test_root_resolution.py
"""The six-tier resolution chain, as a pure function of (flags, env, cwd, disk).

Every tier gets a case and so does the refusal. Tiers 1 and 3 are the regression half: 1291 occurrences
across 238 files name the store with --home or FLEET_HOME, and none of them may move.
"""
import json
import pathlib
import tempfile
import unittest

from fleet import cli
from fleet.root import MARKER


class ResolutionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.home = self.tmp / "home"
        self.root = self.home / "davis_root"
        self.root.mkdir(parents=True)
        (self.root / MARKER).write_text(json.dumps({"name": "davis"}))
        self.cwd = self.root / "ws1"
        self.cwd.mkdir()

    def resolve(self, argv, env=None, cwd=None):
        parsed = cli.parse(argv)
        return cli.resolve_root(parsed, dict(env or {}, HOME=str(self.home)), cwd or self.cwd)

    def test_tier5_marker_walk(self):
        r = self.resolve(["board"])
        self.assertEqual(r.path, self.root)
        self.assertEqual(r.name, "davis")

    def test_tier4_fleet_root_env_beats_the_marker(self):
        other = self.home / "davis2_root"
        other.mkdir()
        (other / MARKER).write_text(json.dumps({"name": "davis2"}))
        r = self.resolve(["board"], env={"FLEET_ROOT": str(other)})
        self.assertEqual(r.name, "davis2")

    def test_tier2_root_flag_beats_the_env(self):
        other = self.home / "davis2_root"
        other.mkdir()
        (other / MARKER).write_text(json.dumps({"name": "davis2"}))
        r = self.resolve(["board", "--root", str(other)], env={"FLEET_ROOT": str(self.root)})
        self.assertEqual(r.name, "davis2")

    def test_no_marker_and_no_naming_resolves_to_none(self):
        bare = self.tmp / "bare"
        bare.mkdir()
        self.assertIsNone(self.resolve(["board"], cwd=bare))


class HomeResolutionCase(ResolutionCase):
    def home_of(self, argv, env=None, cwd=None):
        parsed = cli.parse(argv)
        return cli.resolve_home(parsed, dict(env or {}, HOME=str(self.home)), cwd or self.cwd)

    def test_tier1_home_flag_wins_over_everything(self):
        """REGRESSION: 1291 explicit call sites depend on this and none may move."""
        named = self.tmp / "sandbox"
        h, _ = self.home_of(["board", "--home", str(named)],
                            env={"FLEET_HOME": "/nope", "FLEET_ROOT": str(self.root)})
        self.assertEqual(h, named)

    def test_tier3_fleet_home_env_wins_over_the_marker(self):
        """REGRESSION: this is how every IT section names its sandbox store."""
        named = self.tmp / "sandbox"
        h, _ = self.home_of(["board"], env={"FLEET_HOME": str(named)})
        self.assertEqual(h, named)

    def test_tier5_home_derives_from_the_marker(self):
        h, src = self.home_of(["board"])
        self.assertEqual(h, self.root / ".fleet")
        self.assertIn("marker", src)

    def test_tier6_refuses_a_read_not_only_a_write(self):
        """Revises SI-15. Under isolation a permissive read is not answering about no fleet, it is
        answering about a DIFFERENT ROOT's fleet, confidently, with a population line."""
        bare = self.tmp / "bare"
        bare.mkdir()
        from fleet.errors import BadInput
        with self.assertRaises(BadInput) as cm:
            self.home_of(["board"], cwd=bare)          # `board` is read-only
        self.assertIn(str(bare), str(cm.exception))

    def test_no_fallback_to_dollar_home_dot_fleet(self):
        """The old default. It is what made a read answer about a shared store."""
        legacy = self.home / ".fleet"
        legacy.mkdir()
        bare = self.tmp / "bare"
        bare.mkdir()
        from fleet.errors import BadInput
        with self.assertRaises(BadInput):
            self.home_of(["board"], cwd=bare)


class InstantsResolutionCase(ResolutionCase):
    def instants_of(self, argv, env=None, cwd=None):
        parsed = cli.parse(argv)
        env = dict(env or {}, HOME=str(self.home))
        return cli.resolve_instants(parsed, env, cwd or self.cwd)

    def test_an_explicit_home_still_implies_its_instants(self):
        """REGRESSION: `--home X` has always meant instants `X/instants`, and IT sections rely on it."""
        named = self.tmp / "sandbox"
        self.assertEqual(self.instants_of(["dispatch", "--home", str(named)]), named / "instants")

    def test_instants_dir_flag_wins(self):
        named = self.tmp / "elsewhere"
        self.assertEqual(
            self.instants_of(["dispatch", "--home", str(self.tmp / "s"), "--instants-dir", str(named)]),
            named)

    def test_fleet_instants_env_is_honoured(self):
        named = self.tmp / "elsewhere"
        self.assertEqual(self.instants_of(["dispatch"], env={"FLEET_INSTANTS": str(named)}), named)

    def test_a_derived_home_does_NOT_derive_instants(self):
        """SI-56 / FI-382: with FLEET_INSTANTS unset, dispatch planted a child in $FLEET_HOME/instants
        at rc=0 with all four guards green, and nothing downstream ever disagreed."""
        from fleet.errors import BadInput
        with self.assertRaises(BadInput) as cm:
            self.instants_of(["dispatch"])             # home comes from the marker; nothing names instants
        self.assertIn("FLEET_INSTANTS", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd fleet && PYTHONPATH=src python3 -m pytest tests/test_root_resolution.py -q`
Expected: `AttributeError: module 'fleet.cli' has no attribute 'resolve_root'`

- [ ] **Step 3: Add `--root` to the shared flag block and write the three resolvers**

In `cli.py`, add to the common flag list beside `--home` (`:137`):

```python
    Flag("--root", True, help="the fleet root; its marker supplies home, releases and the tmux socket"),
```

Then, above `default_context`:

```python
def resolve_root(parsed: Parsed, environ: dict, cwd) -> "root_mod.Root | None":
    """Which root, by tiers 2, 4 and 5. None when nothing names one and no marker is found.

    Tiers 1 and 3 name individual COMPONENTS and are handled by the component resolvers below — a caller
    who says `--home` has named a store without saying anything about a root, and inventing one for them
    is how `I2-11` happened in the other direction.
    """
    named = parsed.get("root") or environ.get("FLEET_ROOT")
    if named:
        return root_mod.load(pathlib.Path(named))
    home_dir = pathlib.Path(environ.get("HOME") or pathlib.Path.home())
    return root_mod.discover(pathlib.Path(cwd), home_dir)


def resolve_home(parsed: Parsed, environ: dict, cwd) -> tuple:
    """`(home, source)`. The source string is what G2 prints — see `_root_line`.

    `SI-15` used to let a READ-ONLY verb fall back to `$HOME/.fleet` on the ground that "nothing is
    enrolled" is a real answer to a real question. Under isolation that ground is gone: the fallback does
    not answer about no fleet, it answers about a DIFFERENT ROOT's fleet, confidently and with a
    population line. That is `FI-417`'s shape — a true sentence answering the wrong question — so the
    read refuses too, and the refusal names the directory it searched from.
    """
    if parsed.get("home"):
        return pathlib.Path(parsed.get("home")), "--home"
    if environ.get("FLEET_HOME"):
        return pathlib.Path(environ["FLEET_HOME"]), "$FLEET_HOME"
    resolved = resolve_root(parsed, environ, cwd)
    if resolved is not None:
        source = "--root" if parsed.get("root") else (
            "$FLEET_ROOT" if environ.get("FLEET_ROOT") else f"marker at {resolved.path / root_mod.MARKER}")
        return resolved.store, source
    home_dir = pathlib.Path(environ.get("HOME") or pathlib.Path.home())
    raise BadInput(root_mod.refusal(pathlib.Path(cwd), home_dir, parsed.verb))


def resolve_instants(parsed: Parsed, environ: dict, cwd) -> pathlib.Path:
    """Where NEW instants are created. Named, derived from an explicitly named home, or REFUSED.

    `SI-56` / `FI-382`: with `FLEET_INSTANTS` unset this derived `$FLEET_HOME/instants`, so a dispatch
    returned rc=0 with all four guards `allow` and planted the child outside the effort tree. Nothing
    downstream disagreed — every verb resolves the child through its record — so the damage surfaced only
    at endgame compaction, when the instant was not in the directory being enumerated.

    The `--home X` ⇒ `X/instants` implication is KEPT: it is explicit naming, and 1291 call sites use it.
    What is deleted is the derivation from a home that was itself derived.
    """
    if parsed.get("instants-dir"):
        return pathlib.Path(parsed.get("instants-dir"))
    if parsed.get("home"):
        return pathlib.Path(parsed.get("home")) / "instants"
    if environ.get("FLEET_INSTANTS"):
        return pathlib.Path(environ["FLEET_INSTANTS"])
    if environ.get("FLEET_HOME"):
        return pathlib.Path(environ["FLEET_HOME"]) / "instants"
    raise BadInput(
        f"{parsed.verb!r} needs to know where instants live and nothing named a directory. Pass "
        f"`--instants-dir <path>` or export FLEET_INSTANTS. There is deliberately no derived default: "
        f"`$FLEET_HOME/instants` used to be one, and it planted a dispatched child outside its effort "
        f"tree at rc=0 with every guard green, invisible until the endgame compaction could not find it "
        f"(SI-56).")
```

Rewrite the body of `default_context` from `named_home = ...` through `instants = ...` as:

```python
    environ = dict(os.environ)
    cwd = pathlib.Path.cwd()
    home, home_source = resolve_home(parsed, environ, cwd)
    instants = resolve_instants(parsed, environ, cwd)
```

and delete the now-superseded `SI-15` and `I2-11` comment blocks, replacing them with a one-line pointer
to `resolve_home` / `resolve_instants` so the reasoning has exactly one home.

In `_releases` (`:3252-3258`), replace the `Path.home() / ".fleet-releases"` default:

```python
    named = parsed.get("releases") or os.environ.get("FLEET_RELEASES")
    if named:
        return Releases(Path(named))
    resolved = resolve_root(parsed, dict(os.environ), Path.cwd())
    if resolved is not None:
        return Releases(resolved.releases)
    spec = VERBS.get(parsed.verb)
    if spec is not None and not spec.read_only:
        raise BadInput(
            f"{parsed.verb!r} writes to a release area and none was named: pass `--releases <path>`, "
            f"export FLEET_RELEASES, or run from inside a fleet root. There is no default for a write.")
    raise BadInput(root_mod.refusal(Path.cwd(), Path(os.environ.get("HOME") or Path.home()),
                                    parsed.verb))
```

Add `from fleet import root as root_mod` to the imports.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd fleet && PYTHONPATH=src python3 -m pytest tests/test_root_resolution.py -q`
Expected: 12 passed

- [ ] **Step 5: Run the whole hermetic suite — this is the regression gate**

Run: `cd fleet && PYTHONPATH=src python3 -m pytest tests/ -q`
Expected: all pass. Any failure here is a tier-1/tier-3 regression and must be fixed before proceeding, not deferred.

- [ ] **Step 6: Commit**

```bash
git add fleet/src/fleet/cli.py fleet/tests/test_root_resolution.py
git commit -m "cli: resolve home, instants and releases through the root, and refuse rather than default"
```

---

### Task 3: G2 — every verb says which root it used

**Files:**
- Modify: `fleet/src/fleet/cli.py` (the `Ctx` construction and the cadence-line emitter)
- Test: `fleet/tests/test_root_resolution.py` (append)

**Interfaces:**
- Consumes: the `(home, source)` pair from `resolve_home`
- Produces: one line on **stderr** per invocation: `root <path> (<source>)`

- [ ] **Step 1: Write the failing test**

```python
class RootLineCase(ResolutionCase):
    """FI-421's second defect — the function written to remove a silent fallback shipping WITH a silent
    fallback — was caught only by PRINTING the resolved path. Its own words: 'reading the code would not
    have shown it; printing the resolved path did.' A five-tier chain gets that from the start.

    On stderr, never stdout: test_cli asserts stdout parses to its declared column count and IT §A parses
    --porcelain byte-for-byte. The cadence line already established stderr as this channel.
    """

    def test_the_root_line_goes_to_stderr_and_names_its_source(self):
        import io
        out, err = io.StringIO(), io.StringIO()
        cli.main(["board", "--home", str(self.tmp / "s")], out=out, err=err)
        self.assertIn("root ", err.getvalue())
        self.assertIn("--home", err.getvalue())
        self.assertNotIn("root ", out.getvalue())
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd fleet && PYTHONPATH=src python3 -m pytest tests/test_root_resolution.py -k root_line -q`
Expected: FAIL — `'root ' not found in ''`

- [ ] **Step 3: Emit the line beside the cadence line**

In `default_context`, after `home, home_source = resolve_home(...)`:

```python
    #: `FI-421`. Its second defect — a function written to remove a silent fallback shipping WITH one —
    #: was caught only by printing the resolved path: "reading the code would not have shown it; printing
    #: the resolved path did." A chain with five tiers above a refusal prints where it landed, every call.
    #: On stderr, beside the cadence line, for the reason that line is there: stdout carries a column
    #: contract that `--porcelain` consumers parse byte-for-byte.
    print(f"root {home.parent if home.name == '.fleet' else home} ({home_source})", file=err)
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd fleet && PYTHONPATH=src python3 -m pytest tests/ -q`
Expected: all pass, including `test_every_verb_evaluates_cadence_staleness_and_prints_it_to_stderr` and the stdout column-count assertions.

- [ ] **Step 5: Commit**

```bash
git add fleet/src/fleet/cli.py fleet/tests/test_root_resolution.py
git commit -m "cli: print the resolved root and where it came from, on stderr"
```

---

### Task 4: G1 — a dispatch may not point outside its own root

**Files:**
- Modify: `fleet/src/fleet/store.py` (`Record.root`), `fleet/src/fleet/cli.py` (`_do_dispatch`, `_record_for`)
- Test: `fleet/tests/test_store.py` (append), `fleet/tests/test_root_resolution.py` (append)

**Interfaces:**
- Consumes: `resolve_root`
- Produces: `Record.root: str = ""` at `SCHEMA_VERSION = 1`

- [ ] **Step 1: Write the failing tests**

```python
# fleet/tests/test_store.py — append
class TestRecordRoot(unittest.TestCase):
    def test_a_record_written_before_isolation_still_loads(self):
        """SCHEMA_VERSION stays 1 deliberately. from_json refuses a version mismatch AND unknown fields,
        so bumping it would refuse all 75 records in the live store."""
        legacy = {f.name: "" for f in fields(Record) if f.name not in ("schema_version", "root")}
        legacy["schema_version"] = 1
        legacy["milestone"] = None
        for opt in ("launched_at", "gate_verdict", "harvested_at", "closed_at"):
            legacy[opt] = None
        rec = Record.from_json(legacy)
        self.assertEqual(rec.root, "")

    def test_an_absent_root_is_not_measured_rather_than_a_mismatch(self):
        """FI-417: a check that cannot see something must not report zero. A pre-isolation record carries
        no root, and reading that absence as 'a different root' would refuse every legacy record."""
        self.assertFalse(cli.root_mismatch(Record.from_json(_legacy()), "/home/ubuntu/davis_root"))
```

```python
# fleet/tests/test_root_resolution.py — append
class ContainmentCase(ResolutionCase):
    def test_instants_outside_the_root_are_refused_at_dispatch(self):
        """The real exposure. Records live INSIDE the store, so a verb in root A can never accidentally
        resolve root B's record — it would not find it. What it CAN do is write a record in A whose
        contents point into B, which is FI-382 one level out."""
        other = self.home / "davis2_root"
        (other / "instants").mkdir(parents=True)
        (other / MARKER).write_text(json.dumps({"name": "davis2"}))
        from fleet.errors import BadInput
        with self.assertRaises(BadInput) as cm:
            cli.assert_within_root(other / "instants", self.root, "instants directory")
        self.assertIn(str(self.root), str(cm.exception))
        self.assertIn(str(other / "instants"), str(cm.exception))

    def test_a_path_inside_the_root_is_accepted(self):
        cli.assert_within_root(self.root / "operations", self.root, "instants directory")
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd fleet && PYTHONPATH=src python3 -m pytest tests/test_store.py tests/test_root_resolution.py -q`
Expected: `AttributeError: module 'fleet.cli' has no attribute 'assert_within_root'`, and `TypeError` on the unexpected `root` field.

- [ ] **Step 3: Implement**

In `store.py`, beside `milestone`:

```python
    #: Which root this dispatch belongs to, resolved and absolute. Defaulted and left at
    #: `SCHEMA_VERSION = 1` on purpose: `from_json` refuses a version mismatch AND unknown fields, so
    #: bumping the version would refuse all 75 records in the live store on the first read. An EMPTY root
    #: means "written before isolation", which is NOT MEASURED and never a mismatch — reading absence as
    #: an answer is `FI-417`.
    root: str = ""
```

In `cli.py`:

```python
def assert_within_root(path, root_path, what: str) -> None:
    """Refuse a path that leaves its root, naming both. `G1`.

    Resolved on both sides: during migration `~/.fleet` and `~/davis_root/.fleet` are the same directory
    reached two ways, and comparing unresolved strings would manufacture a mismatch out of a symlink.
    """
    resolved = Path(path).resolve()
    root_path = Path(root_path).resolve()
    if root_path != resolved and root_path not in resolved.parents:
        raise BadInput(
            f"the {what} {resolved} is outside this fleet's root {root_path}. A dispatch that points out "
            f"of its own root is how one root's worker ends up in another root's tree — invisible to "
            f"every verb, because they all resolve the child through its record (SI-56). Clears when: "
            f"name a path under {root_path}, or run from the root that owns {resolved}.")


def root_mismatch(record, active_root: str) -> bool:
    """True only when the record NAMES a root and it differs. An empty root is NOT MEASURED."""
    if not record.root or not active_root:
        return False
    return Path(record.root).resolve() != Path(active_root).resolve()
```

In `_do_dispatch`, before the record is written and before any irreversible step, when a root resolved:

```python
    resolved_root = resolve_root(parsed, dict(os.environ), Path.cwd())
    if resolved_root is not None:
        assert_within_root(ctx.instants_dir, resolved_root.path, "instants directory")
        if slot_path is not None:
            assert_within_root(slot_path, resolved_root.path, "slot")
```

and set `root=str(resolved_root.path) if resolved_root else ""` on the `Record`.

In `_record_for`, after a record is loaded:

```python
    if resolved_root is not None and root_mismatch(record, str(resolved_root.path)):
        raise BadInput(
            f"record {record.todo_id!r} was written under root {record.root} and this call resolved "
            f"{resolved_root.path}. Refusing: a store reached from the wrong root reports another "
            f"fleet's work as this one's.")
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd fleet && PYTHONPATH=src python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add fleet/src/fleet/store.py fleet/src/fleet/cli.py fleet/tests/
git commit -m "dispatch: a record names its root, and may not point outside it"
```

---

### Task 5: G3 — the pool refuses a foreign slot

**Files:**
- Modify: `fleet/src/fleet/pool.py:222-259`
- Test: `fleet/tests/test_pool.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: `Pool(home, ..., root: Path = None)`; `enroll` refuses when `root` is set and the workspace is outside it

- [ ] **Step 1: Write the failing test**

```python
class TestEnrolmentIsRootScoped(unittest.TestCase):
    """Without this, isolation is a claim about how people will behave rather than something a command
    refuses to violate."""

    def test_a_workspace_outside_the_root_is_refused_by_name(self):
        root = self.tmp / "davis_root"
        (root / ".fleet").mkdir(parents=True)
        foreign = self.tmp / "davis2_root" / "ws1"
        foreign.mkdir(parents=True)
        pool = Pool(root / ".fleet", root=root)
        with self.assertRaises(BadInput) as cm:
            pool.enroll(foreign)
        self.assertIn(str(foreign), str(cm.exception))
        self.assertIn(str(root), str(cm.exception))

    def test_a_workspace_inside_the_root_is_enrolled(self):
        root = self.tmp / "davis_root"
        (root / ".fleet").mkdir(parents=True)
        ws = root / "ws1"
        ws.mkdir()
        pool = Pool(root / ".fleet", root=root)
        pool.enroll(ws)
        self.assertEqual([s for s in pool.slots()], ["ws1"])

    def test_no_root_means_no_containment_check(self):
        """REGRESSION: every IT section and every hermetic test builds a Pool with no root."""
        ws = self.tmp / "anywhere" / "ws1"
        ws.mkdir(parents=True)
        pool = Pool(self.tmp / "home")
        pool.enroll(ws)
        self.assertEqual([s for s in pool.slots()], ["ws1"])
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd fleet && PYTHONPATH=src python3 -m pytest tests/test_pool.py -k RootScoped -q`
Expected: `TypeError: __init__() got an unexpected keyword argument 'root'`

- [ ] **Step 3: Implement**

`Pool.__init__` gains `root: Path = None`, stored as `self.root`. In `enroll`, after the `is_dir` check:

```python
        #: `G3`. A slot outside its own root is how one root's worker gets leased into another root's
        #: workspace. Optional because the hermetic suite and every IT section build a Pool with no root
        #: and enrol sandbox directories that legitimately live anywhere.
        if self.root is not None:
            resolved, root = path.resolve(), Path(self.root).resolve()
            if root != resolved and root not in resolved.parents:
                raise BadInput(
                    f"{resolved} is outside this fleet's root {root}, so it cannot be enrolled here. A "
                    f"pool that can lease a workspace belonging to another root is the interference "
                    f"per-root isolation exists to remove. Enrol it from the root that owns it.")
```

In `cli.default_context`, pass `root=resolved_root.path if resolved_root else None` when building the `Pool`.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd fleet && PYTHONPATH=src python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add fleet/src/fleet/pool.py fleet/src/fleet/cli.py fleet/tests/test_pool.py
git commit -m "pool: a slot belongs to one root, and enrolling across roots is refused"
```

---

### Task 6: the socket derives from the root

**Files:**
- Modify: `fleet/src/fleet/cli.py` (the `SessionLayer` construction)
- Test: `fleet/tests/test_root_resolution.py` (append)

**Interfaces:**
- Consumes: `Root.socket`
- Produces: `$FLEET_TMUX_SOCKET` still wins; otherwise `fleet-<name>`; otherwise the default server

- [ ] **Step 1: Write the failing test**

```python
class SocketCase(ResolutionCase):
    def test_the_socket_derives_from_the_declared_name(self):
        self.assertEqual(cli.resolve_socket(cli.parse(["board"]),
                                            {"HOME": str(self.home)}, self.cwd), "fleet-davis")

    def test_an_explicit_socket_env_still_wins(self):
        """REGRESSION: it_section exports FLEET_TMUX_SOCKET for every IT section."""
        self.assertEqual(cli.resolve_socket(cli.parse(["board"]),
                                            {"HOME": str(self.home), "FLEET_TMUX_SOCKET": "itfleet-H"},
                                            self.cwd), "itfleet-H")

    def test_no_root_and_no_env_is_the_default_server(self):
        bare = self.tmp / "bare"
        bare.mkdir()
        self.assertIsNone(cli.resolve_socket(cli.parse(["board"]), {"HOME": str(self.home)}, bare))
```

- [ ] **Step 2: Run it and watch it fail**

Expected: `AttributeError: module 'fleet.cli' has no attribute 'resolve_socket'`

- [ ] **Step 3: Implement**

```python
def resolve_socket(parsed: Parsed, environ: dict, cwd):
    """The tmux SERVER. `$FLEET_TMUX_SOCKET` wins; otherwise `fleet-<root name>`; otherwise the default.

    Per-root, because `close`, `abort` and `harvest` kill sessions BY NAME and session names are
    `dt-<subject>` chosen by a coordinator. Two roots on one server can therefore collide, and the loser
    is killed with no diagnostic. `fleet-env.sh` already argues a private server over the default one for
    exactly this reason; this takes the argument one step further.
    """
    if environ.get(session.TMUX_SOCKET_ENV):
        return environ[session.TMUX_SOCKET_ENV]
    resolved = resolve_root(parsed, environ, cwd)
    return resolved.socket if resolved is not None else None
```

and pass it into `default_probes(tmux_socket=...)` in `default_context`.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd fleet && PYTHONPATH=src python3 -m pytest tests/ -q`

- [ ] **Step 5: Commit**

```bash
git add fleet/src/fleet/cli.py fleet/tests/test_root_resolution.py
git commit -m "session: each root gets its own tmux server, named by its marker"
```

---

### Task 7: §R — the end-to-end IT section

**Files:**
- Create: `fleet/it/run-R.sh`
- Modify: `fleet/it/run-all.sh` (the gate roster), `fleet/it/lib.sh:118-127` (a comment that will be stale), `:481` (the leak-watch list)

**Interfaces:**
- Consumes: `lib.sh` — `it_section`, `it_fresh_store`, `it_pass`, `it_fail`, `it_own_cases`, `it_assert_isolation`, `fleet`
- Produces: cases `R1`, `R2`, `R3a`, `R3b`, `R4`, `R5`, `R6`, `R7` in `RESULTS.tsv`

**Note for the implementer:** `run-A.sh`'s `A2c` audits that **every** `run-*.sh` reaches `it_assert_isolation`. `it_section` does that at entry; the section must also call `it_assert_isolation R-leave` at exit, like `run-H.sh:` does.

- [ ] **Step 1: Write §R with all eight cases, red first**

Build two marked roots under `$EV`, each with a `ws1`, and drive real `fleet` calls with `FLEET_HOME`,
`FLEET_INSTANTS` and `FLEET_TMUX_SOCKET` **unset** inside subshells so the marker walk is what resolves.
Structure each case exactly as `run-H.sh` does: run, capture to a file under `$OUT`, compute boolean flags,
then one `it_pass`/`it_fail` naming the artifact.

| case | what it drives | passes when |
|---|---|---|
| R1 | `fleet init` from inside each root, then compare the two stores | both stores exist under their own root, and neither root's `records/` contains the other's todo id |
| R2 | read the socket each root resolves | `fleet-davis` vs `fleet-davis2`, and `tmux -L fleet-davis ls` cannot see the other's session |
| R3a | `fleet dispatch --instants-dir <root B's tree>` from root A | rc≠0 and the message names **both** paths |
| R3b | copy a record from B's store into A's, then `fleet status --id` | rc≠0 naming both roots; and the same call against a record with an EMPTY root **succeeds** (the NOT-MEASURED half) |
| R4 | `fleet enroll --slot <root B's ws1>` from root A | rc≠0 naming both paths |
| R5 | `fleet board` from `$EV/unmarked` | rc≠0, message contains the cwd; and `$EV/unmarked/.fleet` was **not** created |
| R6 | `fleet dispatch` with a derived home and `FLEET_INSTANTS` unset | rc≠0, message names `FLEET_INSTANTS`; and no instant appeared under the derived store |
| R7 | `fleet board --home <sandbox>` and `FLEET_HOME=<sandbox> fleet board` from an **unmarked** cwd | both rc=0 — the 1291 explicit call sites are unmoved |

R3b's second half and R5's "was not created" clause are the ones that stop a vacuous pass: a refusal that
also happened to create the directory would satisfy a rc-only assertion.

- [ ] **Step 2: Run §R against the UNFIXED code first, if any task above is not yet done**

Run: `IT_RESULTS=/tmp/r.tsv bash fleet/it/run-R.sh`
Expected: R3a, R4, R5, R6 FAIL. If they pass before the fix exists, the case is vacuous and must be rewritten — that is `FI-303`'s rule and it is not optional.

- [ ] **Step 3: Fix the two `lib.sh` sites**

`:118-127` claims `export FLEET_INSTANTS="$FLEET_HOME/instants"` "makes the existing default explicit". After
Task 2 there is no such default. Rewrite the comment to say the line now **supplies** a value the product
refuses to invent, and cite `SI-56`. Leaving it is the class of defect this register keeps recording: a
comment naming a mechanism that moved.

`:481` watches `"$HOME/.fleet/instants"` as a leak destination. Add the derived root's store so the check
does not go vacuous after migration. `lib.sh:606-610` already refuses to report a pass over zero watched
trees — do not weaken it while editing.

- [ ] **Step 4: Add §R to the gate roster**

In `run-all.sh`, beside the other sections:

```bash
  "R:bash $IT_ROOT/run-R.sh"
```

- [ ] **Step 5: Run §R green, then §A (which audits every runner)**

```bash
IT_RESULTS=/tmp/r.tsv bash fleet/it/run-R.sh; echo "rc=$?"
IT_RESULTS=/tmp/a.tsv bash fleet/it/run-A.sh; echo "rc=$?"
```
Expected: both rc=0; §A's `A2c` counts `run-R.sh` among the compliant runners.

- [ ] **Step 6: Commit**

```bash
git add fleet/it/run-R.sh fleet/it/run-all.sh fleet/it/lib.sh
git commit -m "it: two roots side by side, and the four refusals that keep them apart"
```

---

### Task 8: the consumers

**Files:**
- Modify: `scripts/fleet-env.sh:21,30,34,41`, `scripts/claude-watchdog.sh:30,83,210`, `bin/fleet-view:408`
- Test: `scripts/tests/` — add `fleet-env-derives-root.sh`

- [ ] **Step 1: Write the failing test**

A bash test that sources `fleet-env.sh` from inside a temporary marked root with `FLEET_HOME` unset and
asserts `$FLEET_HOME` lands at `<root>/.fleet`, `$FLEET_TMUX_SOCKET` at `fleet-<name>`, and that no literal
`/home/ubuntu/davis_root` appears in the exported values.

- [ ] **Step 2: Run it and watch it fail**

Expected: `FLEET_HOME=/home/ubuntu/.fleet`, socket `fleet`.

- [ ] **Step 3: Rewrite the three consumers**

`fleet-env.sh`: walk up from `$PWD` for `.fleet-root`; export `FLEET_HOME`, `FLEET_RELEASES` and
`FLEET_TMUX_SOCKET` from it; export **nothing** when no marker is found, and say so on stderr rather than
silently defaulting. The `fleet_peek`/`fleet_attach` helpers already read `${FLEET_TMUX_SOCKET:-fleet}` —
change the fallback to a refusal, because attaching to the wrong server is exactly the collision §R R2 tests.

`claude-watchdog.sh`: derive `DAVIS` from the script's own location (`$(cd "$(dirname "$0")/../.." && pwd)`)
rather than the literal. **`:210`'s socket default must become the per-root socket** — its own comment says
the `fleet` socket is included by default because "an opt-in list is a list somebody forgets on the day it
matters", and renaming the socket under it turns that default into a list of one wrong name.

`bin/fleet-view:408`: print the resolved root and its source instead of `"(unset — defaults to ~/.fleet for
reads)"`.

- [ ] **Step 4: Run the shell suites**

```bash
bash scripts/tests/fleet-env-derives-root.sh
bash bin/superpowers-selftest
bash scripts/lint-shell.sh --all
```
Expected: all green; `lint-shell.sh --all` rc=0 (the baseline is zero findings as of `e5fa55a` and must stay there).

- [ ] **Step 5: Commit**

```bash
git add scripts/ bin/fleet-view
git commit -m "consumers: derive the root instead of naming davis_root as a constant"
```

---

### Task 9: migration

**Files:**
- Create: `scripts/fleet-migrate-root.sh`

- [ ] **Step 1: Write the script, idempotent and reversible**

```bash
#!/usr/bin/env bash
# Move a box-wide ~/.fleet into a root, and mark both roots. Idempotent: a second run is a no-op.
#
# Order matters and is not negotiable. The compatibility symlink is a NET, and while it exists a shell
# carrying a stale FLEET_HOME=~/.fleet with no marker above its cwd reaches davis_root's store through
# tier 3 — the exact interference this work removes, wearing the compatibility layer as a disguise. So
# fleet-env.sh must already have stopped exporting a literal FLEET_HOME (Task 8) before this runs.
set -euo pipefail
```

Steps: refuse if any lease is held; refuse if `fleet-env.sh` still exports a literal `FLEET_HOME`; `mv` the
store; symlink; write both markers; print the before/after of `records/`, `pool/enrolled/` and the resolved
socket for **both** roots.

- [ ] **Step 2: Dry-run it against a copy, not the live store**

```bash
cp -a ~/.fleet /tmp/fleet-migration-rehearsal
FLEET_MIGRATE_TARGET=/tmp/rehearsal-root bash scripts/fleet-migrate-root.sh --dry-run
```
Expected: prints the plan, writes nothing. Verify the record count it reports equals `ls ~/.fleet/records | wc -l` = 75.

- [ ] **Step 3: Run it for real, then verify from both roots**

```bash
bash scripts/fleet-migrate-root.sh
cd ~/davis_root  && fleet board --porcelain | head -3
cd ~/davis2_root && fleet board --porcelain | head -3
```
Expected: `davis_root` shows the 75-record fleet; `davis2_root` shows an empty one; the stderr root line
differs between them.

- [ ] **Step 4: Commit**

```bash
git add scripts/fleet-migrate-root.sh
git commit -m "migrate: move the box-wide store into davis_root and mark both roots"
```

---

### Task 10: the full gate

- [ ] **Step 1: Hermetic suite**

Run: `cd fleet && PYTHONPATH=src python3 -m pytest tests/ -q`

- [ ] **Step 2: Skill selftest and shell lint**

```bash
bash bin/superpowers-selftest
bash scripts/lint-shell.sh --all
```

- [ ] **Step 3: The IT gate roster, with results isolated**

Run: `IT_RESULTS=/tmp/it-full.tsv bash fleet/it/run-all.sh`
Expected: 0 FAIL across every section. **Do not edit any file while this is running** — bash reads scripts
incrementally by byte offset and an edit mid-run corrupts execution.

- [ ] **Step 4: Restore the tracked results file if any standalone run touched it**

```bash
git status --short fleet/it/RESULTS.tsv
```
`RESULTS.tsv` is tracked and `lint-skill.py` reads it to verify every V2 citation. If a standalone run
clobbered it, `git checkout -- fleet/it/RESULTS.tsv` and re-run with `IT_RESULTS` set.

- [ ] **Step 5: Cut a release**

```bash
fleet release-cut --repo "$PWD"
```

---

## Execution record — 2026-09-06

Executed inline. Every task landed; the deviations below are the ones a reader of this plan needs, because
each was a plan defect found by a test rather than by review.

| # | deviation | why |
|---|---|---|
| 2 | `resolve_instants` was split into a resolver plus `require_named_instants` at the two `layout.bootstrap` handlers | as planned it refused `board`: `reconcile` and `guards.blocking_compactions` read the instants directory on the READ path. An AST check now asserts every bootstrapping handler reaches the guard |
| 2 | `_releases` shipped one commit late | the commit message for the resolver work claimed it and the code did not do it. Corrected in `7d49110` rather than left standing |
| 4/5 | Task 5 was pulled ahead of Task 4 | `default_context` constructs the `Pool`, so `fleet_root=` had to exist before the context could be built. The plan sequenced them backwards |
| 5 | the parameter is `fleet_root`, not `root` | `Pool.root` already means the pool directory; reusing the name would have silently rebound it |
| 7 | R3b drives `base-check`, not `status`, and additionally asserts `board` still exits 0 | `status` reads through `subjects()` → `store.all()`, never `_record`. Pushing the refusal down there would let one stray record make the board permanently unreadable (`FI-402`), so the limit is tested rather than closed |
| 7 | `run-A.sh`'s `A1b` anchor was updated | it matched `SI-15`'s exact sentence, which tier 6 replaced. It now accepts either sentence — still two exact sentences, never the flag name (`II-10`) |
| 8 | `bin/fleet-view` gained a refusal path | it rendered `(no subjects)` over a non-zero `fleet`. Reachable before only via a bad `--home`; isolation makes it the default in any unmarked directory, and this tool's contract says it cannot hide a refusal |

**Three defects I introduced and the suite caught**, recorded because a fix's own bugs are the interesting
part: a string replace that moved `return record` outside its `if`, so `_record_for` returned the first
record in the store regardless of match (13 tests); the same guard raising `BadInput` inside
`except FleetError: continue`, where it would have been swallowed and read as installed while doing nothing;
and a test that passed before the fix existed because `parse` refuses a missing required flag first and
appends a usage dump containing the very string the assertion matched.

---

## Self-Review

**Spec coverage.** Marker + declared name → Task 1. The walk and its `$HOME` boundary → Task 1. Precedence
tiers 1–6 → Task 2. Tier 6 applying to reads → Task 2 (`test_tier6_refuses_a_read_not_only_a_write`).
Instants no longer derived → Task 2. G1 → Task 4. G2 → Task 3. G3 → Task 5. Socket → Task 6. Migration →
Task 9. Blast radius: `cli.py` Tasks 2/3/4, `session.py` Task 6, `pool.py` Task 5, `fleet-env.sh` and
`claude-watchdog.sh` and `bin/fleet-view` Task 8, `lib.sh` Task 7. Testing R1–R7 → Task 7.

**Gap found and closed:** the spec's blast-radius table lists `session.py:257-264` but the design text never
said what happens when a root resolves *and* `$FLEET_TMUX_SOCKET` is exported. Task 6 fixes the precedence
explicitly (env wins) and tests it, because `it_section` exports that variable for every IT section and
silently overriding it would break the whole suite.

**Placeholder scan:** none. Every code step carries the actual code; every test step carries the actual
assertions.

**Type consistency:** `resolve_root` returns `Root | None` and is used that way in Tasks 2, 4, 5 and 6.
`resolve_home` returns `(Path, str)` and both halves are consumed (Task 2 for the path, Task 3 for the
source). `assert_within_root(path, root_path, what)` and `root_mismatch(record, active_root)` have one
signature each, used identically in Task 4 and its tests. `Pool(home, ..., root=None)` matches the
`default_context` call site in Task 5.
