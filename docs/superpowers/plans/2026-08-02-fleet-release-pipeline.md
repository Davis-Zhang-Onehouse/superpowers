# Fleet Release Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the fleet infrastructure versioned releases with a per-release changelog, one-command deploy and rollback recorded with a reason, and a promotion gate that no version passes until both test suites have run green against that exact artifact.

**Architecture:** A release is an immutable `git archive` export selected by a `current` symlink; the two consumers (`fleet-env.sh`'s PATH, the `superpowers-dev` marketplace path) follow the symlink and never the git checkout. Releases are cut as CANDIDATE and promoted only on green evidence produced by running the suites *against the frozen export*, which makes source contamination structurally impossible rather than procedurally discouraged. Deltas are computed by patch-id so the nightly upstream rebase cannot corrupt a changelog.

**Tech Stack:** Python 3 standard library only (no third-party imports — enforced by §A4). Bash for the IT harness. `git` and `tmux` as external binaries.

**Spec:** `docs/superpowers/specs/2026-08-02-fleet-release-pipeline-design.md`

## Global Constraints

- **Python: standard library only.** `fleet/src/fleet/*.py` may import stdlib or `fleet.*` and nothing else. §A4 enforces this by AST scan over every module including function-local imports, and separately forbids `importlib`, `__import__`, `pkgutil`, `pkg_resources`, `eval` and `exec` anywhere in `src/fleet`.
- **Exit codes come from the registry in `fleet/__init__.py`** — 0 ok, 1 attention, 2 bad input, 3 no capacity, 4 refused. Add no new codes. §A5 drives every verb and fails on any code not in `EXIT_CODES`.
- **No positionals.** `parse()` refuses bare tokens by design (`FI-19d`). Every input is a declared `Flag`.
- **A mutating verb with no named store refuses** rather than inventing one (`SI-15`). This now applies to `FLEET_RELEASES` exactly as it does to `FLEET_HOME`.
- **`atomic_write` / `atomic_update` / `held_for_update` from `fleet.atomic` are the only persistence primitives.** Do not hand-roll tmp-then-replace; `FI-20` records eight separate wrong implementations.
- **Never write to `~/.claude-dispatch-board` or `~/.claude-ws-pool`.** The IT harness hashes both to prove non-interference.
- **Never create, kill, or write a tmux session whose name starts with `dt-` on the default server.**
- **Every new hermetic test must be shown to FAIL with its implementation reverted** before it counts. This is the counter-measure for P-C (green for the wrong reason), which has six recorded sightings including one that shipped.
- Run hermetic tests with: `cd fleet && PYTHONPATH=src python3 -m unittest discover -s tests -q` (~45s).

---

## IT failure triage — read this before "fixing" a red section

Tasks 6 and 8 run real IT sections, and some will fail. **Sort every failure into one of two buckets
before touching anything**, because the cost of getting this wrong is asymmetric: a hasty fix to a harness
assertion is how a suite stops protecting anything, and P-C (green for the wrong reason) already has six
recorded sightings, one of which shipped.

**Bucket 1 — a trivial glitch: just fix it.** A path that moved, a missing `mkdir -p`, a `bash`-ism run
under `zsh`, a stale fixture filename, an evidence file written to the wrong relative path. Small, local,
obvious, and the fix does not change what any case asserts. Fix it, note it in the commit body, move on.

**Bucket 2 — anything else: do NOT fix it. Diagnose and propose.** Specifically, anything that is tricky,
that would change or reduce what a case measures, or that has a wide blast radius (`lib.sh`, the isolation
contract, a shared fixture, anything touching more than one section). For these:

1. **Use the `superpowers:systematic-debugging` skill.** Capture raw artifacts — the failing rows, the
   evidence files, the exact commands — and cite them. Do not assert a cause from memory or from reading
   the code; this codebase's own rule is that an RCA without raw artifacts is not an RCA.
2. Write the RCA and **proposals**, not a patch.
3. Record it in the IT-stabilisation instant (below), not in this plan and not in the fleet repo.

**Where that work lives.** IT stabilisation is a separate effort with its own lifecycle, so it gets its own
instant, created with the `superpowers:maintain-workspace` skill:

```
superpowers:maintain-workspace  new  --base /home/ubuntu/davis_root/operations/tasks/fleetItStabilisation
```

A new base folder, sibling to `metaOpt/`, because this is not a sub-task of the release pipeline — it is
follow-up work the operator intends to run as its own story. Create it at the moment the first Bucket-2
failure appears, not before: an instant created in advance of anything to put in it is the same
inventing-work failure recorded as **F-10**.

**Never** weaken an assertion to get a green. If a case cannot pass, it is reported as a case that cannot
pass, with its reason — the same rule `K6` already follows by SKIPping with a stated reason rather than
certifying a contract nothing enforces.

---

## Surface correction the spec did not anticipate

The spec writes the CLI as `fleet release cut <version>`. **That surface cannot exist.** `parse()` refuses positionals with a documented rationale, and `main()` dispatches on `argv[0]` against a flat `VERBS` dict with no sub-verb mechanism. Teaching the parser sub-verbs would also mean teaching §A5's and §M's generated matrices a second dimension — those derive their population from `cli.VERBS` and drive every verb through a real invocation.

**The surface is therefore eight flat, flag-only verbs:** `release-cut`, `release-verify`, `release-promote`, `release-deploy`, `release-rollback`, `release-status`, `release-list`, `release-history`. This is strictly better here: each one enrols automatically into §A5 (exit codes), §M1/M2/M4/M5/M14 (usage, undeclared flag, valueless flag, help) and §M8 (read-only zero-delta) with no new harness work.

**This creates one hazard that must be designed for, not discovered.** §A5 and §M drive every verb in `VERBS` through a *real* invocation. A `release-cut` that inferred its git repository from the current directory would tag the live repo during an IT run. So `--repo` is a **required** flag on every verb that touches git, and `FLEET_RELEASES` is refused-if-unset for every mutating release verb. Driven with no flags, these verbs exit 2 on the missing required flag — a registered code, nothing mutated.

Update the spec's verb table to match before starting Task 4.

---

## File Structure

| File | Responsibility |
|---|---|
| `fleet/src/fleet/release.py` (new) | The model: `Version` parsing and ordering, release-directory layout, `MANIFEST.tsv` / `STATE` read-write, `tree_sha`, history append, `current` resolution, the atomic flip, the mutation lock. No git, no subprocess. |
| `fleet/src/fleet/release_git.py` (new) | Every git call: dirty check, previous-tag selection, patch-id delta, changelog rendering, annotated tag, export. |
| `fleet/src/fleet/release_verify.py` (new) | Runs the two suites against an export, captures evidence, computes the verdict. |
| `fleet/src/fleet/cli.py` (modify) | The eight verb specs and their handlers. **One agent at a time on this file.** |
| `fleet/tests/test_release.py` (new) | Hermetic tests for all three modules plus the CLI refusals, against a temp git repo. |
| `fleet/it/lib.sh` (modify) | `it_assert_isolation` classifies the session delta instead of comparing it. |
| `fleet/it/run-all.sh` (modify) | Two rosters and a header that states the one it runs. |
| `fleet/it/run-Q.sh` (new) | §Q — the release lifecycle end to end against a throwaway repo and releases root. |
| `scripts/tests/it-lib-isolation.sh` (new) | Bash tests for the classification change, with a negative control. |
| `bin/fleet-view` (modify) | A `releases` view. Rendering only. |
| `bin/fleet` (modify) | `cd -P` so an invocation pins one physical release directory. |
| `scripts/fleet-env.sh` (modify) | Default `FLEET_RELEASES`; `PATH` via `current`. |

---

### Task 1: `release.py` — the model

**Files:**
- Create: `fleet/src/fleet/release.py`
- Test: `fleet/tests/test_release.py`

**Interfaces:**
- Consumes: `fleet.atomic.atomic_write`, `fleet.atomic.held_for_update`, `fleet.errors.BadInput`, `fleet.errors.Refused`
- Produces:
  - `Version` — frozen dataclass, `.major/.minor/.patch: int`, `Version.parse(str) -> Version`, `str(v) -> "0.3.0"`, orderable, `v.bump_kind(prev: Version) -> str` returning `"major"|"minor"|"patch"`
  - `CANDIDATE = "CANDIDATE"`, `RELEASED = "RELEASED"`, `DEV = "DEV"`
  - `Releases(root: Path)` with `.dir_for(v) -> Path`, `.manifest(v) -> dict`, `.write_manifest(v, dict)`, `.state(v) -> str`, `.set_state(v, str)`, `.versions() -> list[Version]` (ascending), `.previous(v) -> Version | None`, `.current_target() -> Path | None`, `.current_label() -> str` (`"0.3.0"` or `"DEV"` or `"none"`), `.point_current_at(path)`, `.append_history(**fields)`, `.history() -> list[dict]`, `.lock()` contextmanager
  - `tree_sha(root: Path) -> str`
  - `HISTORY_COLUMNS = ("ts", "action", "version", "from_version", "actor", "host", "reason", "evidence")`

**Design notes the implementer needs:**

*The lock.* Do not build a second lock mechanism. `fleet.atomic.held_for_update(path)` already takes a `mkdir` lock (`.<name>.lock` beside the path), already breaks a stale holder after `LOCK_TIMEOUT_S`, and is already tested. `Releases.lock()` wraps `held_for_update(self.root / ".releases-lock")` — a path used only for its lock, never read or written. The spec says `.lock/`; this is the same idea using the tested implementation instead of a new one.

*The flip must be atomic.* `os.symlink` to a temp name, then `os.replace` onto `current`. `os.replace` is an atomic rename even when the target is an existing symlink. Never `unlink` then `symlink` — that leaves a window with no `current`, and every `davis_root` shell's `PATH` points through it.

*`tree_sha` is computed from the filesystem, not from git*, because Task 3 must recompute it on a copy of the export and compare. Exclude `.release/` so a manifest cannot hash itself.

- [ ] **Step 1: Write the failing tests**

```python
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
        a, b = self._make("0.1.0"), self._make("0.2.0")
        self.rel.point_current_at(self.rel.dir_for(a))
        seen = []
        for _ in range(50):
            self.rel.point_current_at(self.rel.dir_for(b))
            seen.append((self.rel.root / "current").exists())
            self.rel.point_current_at(self.rel.dir_for(a))
            seen.append((self.rel.root / "current").exists())
        self.assertTrue(all(seen), "current vanished during a flip")

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/ubuntu/davis_root/superpowers/fleet && PYTHONPATH=src python3 -m unittest tests.test_release -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.release'`

- [ ] **Step 3: Write `fleet/src/fleet/release.py`**

```python
"""The release model: what a version is, where its artifact lives, and what is deployed right now.

Kept free of `git` and of subprocesses on purpose. The thing that decides which bytes are live must be
testable without a repository, and the module that answers "what is deployed" is read by `status` on every
shell -- so it may not depend on a working git.

The lock is `atomic.held_for_update` over a path used for nothing else. A second lock implementation was
the alternative, and `FI-20` is what eight hand-rolled copies of one primitive cost last time.
"""
import hashlib
import os
import re
import socket
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fleet.atomic import atomic_write, held_for_update
from fleet.errors import BadInput

__all__ = ["CANDIDATE", "DEV", "HISTORY_COLUMNS", "RELEASED", "Releases", "Version",
           "actor", "tree_sha", "utc_now"]

CANDIDATE = "CANDIDATE"
RELEASED = "RELEASED"
DEV = "DEV"

HISTORY_COLUMNS = ("ts", "action", "version", "from_version", "actor", "host", "reason", "evidence")

#: Everything under here describes the release; it is not part of the payload and must not be hashed into
#: `tree_sha`, or a manifest could never record a hash of the tree that contains it.
META_DIR = ".release"

_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    @staticmethod
    def parse(text) -> "Version":
        match = _SEMVER.match(str(text or "").strip())
        if not match:
            raise BadInput(
                f"{text!r} is not a version. Expected exactly three dot-separated numbers, e.g. 0.3.0 — "
                f"no leading 'v' (the TAG carries that), no fourth component, no leading zeroes. Refused "
                f"rather than coerced: a version that parses two ways sorts two ways, and `previous()` "
                f"picking the wrong predecessor writes a changelog covering the wrong commits.")
        return Version(*(int(part) for part in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def tag(self) -> str:
        return f"fleet/v{self}"

    @property
    def dirname(self) -> str:
        return f"fleet-v{self}"

    def bump_kind(self, prev: "Version") -> str:
        if self.major != prev.major:
            return "major"
        if self.minor != prev.minor:
            return "minor"
        return "patch"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def actor() -> str:
    """Who is acting. `CLAUDE_OWNER_EMAIL` first: this is a shared box, and the identity work exists
    because a dispatched session once ran under another operator's account."""
    return os.environ.get("CLAUDE_OWNER_EMAIL") or os.environ.get("USER") or "unknown"


def _clean(value) -> str:
    """One TSV field. A tab or newline in operator free text would shift every later column, and the
    result still parses -- into the wrong fields. Substituted, never rejected: refusing a rollback because
    its reason had a newline is worse than storing the reason on one line."""
    return re.sub(r"\s+", " ", str("-" if value is None else value)).strip() or "-"


def tree_sha(root) -> str:
    """A hash of the payload: sorted `mode path sha256`, one line per file, `META_DIR` excluded.

    Computed from the FILESYSTEM rather than from git, because `verify` recomputes it on a copy of the
    export to prove that what was tested is what shipped -- and a copy has no git object database.
    The executable bit is included: a launcher that lost `+x` is a broken artifact that hashes identically
    if you only hash content.
    """
    root = Path(root)
    lines = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] == META_DIR:
            continue
        if path.is_symlink():
            lines.append(f"120000 {rel} {hashlib.sha256(os.readlink(path).encode()).hexdigest()}")
            continue
        if not path.is_file():
            continue
        mode = "100755" if path.stat().st_mode & stat.S_IXUSR else "100644"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{mode} {rel} {digest}")
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


class Releases:
    """The release area on disk. One instance per `$FLEET_RELEASES`."""

    def __init__(self, root):
        self.root = Path(root)

    # --- layout ------------------------------------------------------------------------------------
    def dir_for(self, version: Version) -> Path:
        return self.root / version.dirname

    def _meta(self, version: Version) -> Path:
        return self.dir_for(version) / META_DIR

    def versions(self) -> list:
        found = []
        if not self.root.is_dir():
            return found
        for child in self.root.iterdir():
            if not child.is_dir() or not child.name.startswith("fleet-v"):
                continue
            try:
                found.append(Version.parse(child.name[len("fleet-v"):]))
            except BadInput:
                continue                      # not ours; a stray directory is not an error
        return sorted(found)

    def previous(self, version: Version):
        """The highest release BELOW this one -- by semver order, not by creation time. A tag cut out of
        order must not silently redefine what the next changelog covers."""
        below = [v for v in self.versions() if v < version]
        return below[-1] if below else None

    # --- manifest and state ------------------------------------------------------------------------
    def write_manifest(self, version: Version, fields: dict) -> None:
        body = "".join(f"{key}\t{_clean(value)}\n" for key, value in fields.items())
        atomic_write(self._meta(version) / "MANIFEST.tsv", body)

    def manifest(self, version: Version) -> dict:
        path = self._meta(version) / "MANIFEST.tsv"
        out = {}
        if not path.is_file():
            return out
        for line in path.read_text().splitlines():
            if "\t" in line:
                key, value = line.split("\t", 1)
                out[key] = value
        return out

    def state(self, version: Version) -> str:
        path = self._meta(version) / "STATE"
        return path.read_text().strip() if path.is_file() else CANDIDATE

    def set_state(self, version: Version, value: str) -> None:
        atomic_write(self._meta(version) / "STATE", value + "\n")

    # --- the pointer -------------------------------------------------------------------------------
    @property
    def current_link(self) -> Path:
        return self.root / "current"

    def current_target(self):
        try:
            return Path(os.readlink(self.current_link))
        except OSError:
            return None

    def current_label(self) -> str:
        """`"0.3.0"`, `DEV`, or `"none"`. DEV is anything outside the releases root: the pointer may aim
        at the git checkout, and then the deployed code is a moving target rather than a version."""
        target = self.current_target()
        if target is None:
            return "none"
        name = Path(target).name
        if Path(target).parent == self.root and name.startswith("fleet-v"):
            try:
                return str(Version.parse(name[len("fleet-v"):]))
            except BadInput:
                return DEV
        return DEV

    def point_current_at(self, target) -> None:
        """Flip atomically. `os.replace` renames over the existing symlink in one step; unlink-then-symlink
        would leave a window in which `current` does not exist, and every davis_root shell's PATH resolves
        through it."""
        self.root.mkdir(parents=True, exist_ok=True)
        staging = self.root / f".current.{os.getpid()}.tmp"
        if staging.is_symlink() or staging.exists():
            staging.unlink()
        os.symlink(str(target), staging)
        os.replace(staging, self.current_link)

    # --- the register ------------------------------------------------------------------------------
    @property
    def history_path(self) -> Path:
        return self.root / "RELEASE-HISTORY.tsv"

    def append_history(self, **fields) -> None:
        row = {name: _clean(fields.get(name)) for name in HISTORY_COLUMNS}
        row["ts"] = fields.get("ts") or utc_now()
        row["actor"] = fields.get("actor") or actor()
        row["host"] = fields.get("host") or socket.gethostname()
        line = "\t".join(row[name] for name in HISTORY_COLUMNS) + "\n"
        header = "\t".join(HISTORY_COLUMNS) + "\n"
        path = self.history_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with held_for_update(path):
            current = path.read_text() if path.is_file() else ""
            if not current.startswith(header):
                current = header + current
            atomic_write(path, current + line)

    def history(self) -> list:
        path = self.history_path
        if not path.is_file():
            return []
        rows = []
        for line in path.read_text().splitlines()[1:]:
            if not line.strip():
                continue
            parts = line.split("\t")
            parts += ["-"] * (len(HISTORY_COLUMNS) - len(parts))
            rows.append(dict(zip(HISTORY_COLUMNS, parts)))
        return rows

    # --- the mutation lock -------------------------------------------------------------------------
    @contextmanager
    def lock(self):
        """Serialise every mutating verb. `held_for_update` is reused rather than reimplemented: it is the
        same `mkdir` lock, it already breaks a holder that died, and it is already tested."""
        self.root.mkdir(parents=True, exist_ok=True)
        with held_for_update(self.root / ".releases-lock"):
            yield
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/ubuntu/davis_root/superpowers/fleet && PYTHONPATH=src python3 -m unittest tests.test_release -v`
Expected: PASS, 18 tests.

- [ ] **Step 5: Prove three of the tests are not vacuous**

This is the P-C counter-measure and it is not optional. For each, break the implementation, confirm the named test fails, then restore.

| Break | Must fail |
|---|---|
| `Version` — change `order=True` to `order=False` and add `__lt__` comparing `str(self) < str(other)` | `test_ordering_is_numeric_not_lexical` |
| `point_current_at` — replace the staging+`os.replace` body with `self.current_link.unlink(missing_ok=True); os.symlink(str(target), self.current_link)` | `test_the_flip_never_leaves_current_absent` |
| `_clean` — `return str(value)` | `test_a_reason_containing_a_tab_or_newline_cannot_break_the_register` |

Record the three observed failure messages in the commit body.

- [ ] **Step 6: Run the whole hermetic suite**

Run: `cd /home/ubuntu/davis_root/superpowers/fleet && PYTHONPATH=src python3 -m unittest discover -s tests -q`
Expected: OK. `test_structure` and `test_no_undefined_names` also run here; `release.py` imports only stdlib and `fleet.*`, so both must stay green.

- [ ] **Step 7: Commit**

```bash
cd /home/ubuntu/davis_root/superpowers
git add fleet/src/fleet/release.py fleet/tests/test_release.py
git commit -m "release: the model — versions, layout, the register, and an atomic flip"
```

---

### Task 2: `release_git.py` — the delta that survives a rebase

**Files:**
- Create: `fleet/src/fleet/release_git.py`
- Modify: `fleet/tests/test_release.py` (append a `GitCase`)

**Interfaces:**
- Consumes: `fleet.release.Version`, `fleet.errors.BadInput`, `fleet.errors.Refused`
- Produces:
  - `Repo(path: Path)` with `.dirty() -> list[str]`, `.head() -> str`, `.branch() -> str`, `.tag_exists(name) -> bool`, `.upstream_base() -> str`, `.is_ancestor(a, b) -> bool`, `.delta(prev_tag: str | None) -> list[tuple[str, str]]`, `.annotated_tag(name, message)`, `.export(tag, dest: Path)`, `.commit(paths, message)`
  - `changelog_section(version, head, branch, upstream_base, prev_tag, commits, rebased, when) -> str`

**Design notes:**

*Why `git cherry`.* `git log prev..HEAD` computes by ancestry. The 03:30 cron rebases `live` onto each upstream release, which rewrites every one of this fork's commits, after which a previous release's tag is no longer an ancestor and the ancestry answer is wrong without being empty. `git cherry -v <prev> HEAD` compares by **patch-id**, so a rewritten commit is still recognised as the same change. Verified on the live repo: of 272 commits over `v6.2.0`, `cherry` marks 270 `+` and 2 as already upstream — the comparison does real work.

*Output shape.* `git cherry -v` emits `+ <40-char sha> <subject>` for commits present in HEAD and absent from the reference, and `- <sha> <subject>` for those already there. Take only `+`.

- [ ] **Step 1: Write the failing tests (append to `fleet/tests/test_release.py`)**

```python
class GitCase(unittest.TestCase):
    """Against a real temporary repository. `git` is the thing under test here -- mocking it would assert
    that this module can spell the flags it was written with, which is not a property anyone needs."""

    def setUp(self):
        import shutil
        import subprocess
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.run = lambda *a: subprocess.run(["git", "-C", str(self.repo), *a], check=True,
                                             capture_output=True, text=True)
        self.run("init", "-q", "-b", "live")
        self.run("config", "user.email", "t@example.com")
        self.run("config", "user.name", "T")
        self.run("config", "commit.gpgsign", "false")

    def _commit(self, name, body="x"):
        (self.repo / name).write_text(body)
        self.run("add", name)
        self.run("commit", "-q", "-m", f"add {name}")
        return self.run("rev-parse", "HEAD").stdout.strip()

    def test_a_dirty_tree_is_reported_with_the_offending_paths(self):
        from fleet.release_git import Repo
        self._commit("a.txt")
        self.assertEqual(Repo(self.repo).dirty(), [])
        (self.repo / "a.txt").write_text("changed")
        self.assertTrue(any("a.txt" in p for p in Repo(self.repo).dirty()))

    def test_an_untracked_file_counts_as_dirty(self):
        # An export contains only committed content, so an untracked file is content the operator can see
        # and the artifact cannot. Silently excluding it is how you ship a version nobody can reproduce.
        from fleet.release_git import Repo
        self._commit("a.txt")
        (self.repo / "new.txt").write_text("hi")
        self.assertTrue(any("new.txt" in p for p in Repo(self.repo).dirty()))

    def test_the_first_release_has_no_predecessor_and_no_commit_list(self):
        from fleet.release_git import Repo
        self._commit("a.txt")
        self.assertEqual(Repo(self.repo).delta(None), [])

    def test_delta_lists_only_commits_after_the_previous_tag(self):
        from fleet.release_git import Repo
        self._commit("a.txt")
        self.run("tag", "-a", "fleet/v0.1.0", "-m", "r1")
        self._commit("b.txt")
        self._commit("c.txt")
        subjects = [s for _, s in Repo(self.repo).delta("fleet/v0.1.0")]
        self.assertEqual(sorted(subjects), ["add b.txt", "add c.txt"])

    def test_delta_survives_a_rebase_that_rewrites_every_hash(self):
        # THE case. `git log prev..HEAD` is wrong here in a way that is not empty and not obviously wrong,
        # which is why it has to be measured rather than reasoned about.
        from fleet.release_git import Repo
        self._commit("a.txt")
        self.run("tag", "-a", "fleet/v0.1.0", "-m", "r1")
        self._commit("b.txt")
        self._commit("c.txt")
        before = sorted(s for _, s in Repo(self.repo).delta("fleet/v0.1.0"))

        # An upstream release lands under our commits and `live` is rebased onto it, exactly as sync.sh does.
        self.run("checkout", "-q", "-b", "upstream", "fleet/v0.1.0")
        self._commit("upstream.txt")
        self.run("checkout", "-q", "live")
        self.run("rebase", "-q", "upstream")

        self.assertFalse(Repo(self.repo).is_ancestor("fleet/v0.1.0", "HEAD"),
                         "fixture is wrong: the rebase must have moved the tag off the branch")
        after = sorted(s for _, s in Repo(self.repo).delta("fleet/v0.1.0"))
        self.assertEqual(before, after, "the patch-id delta must not change when hashes are rewritten")

    def test_the_changelog_names_the_rebase_when_the_tag_left_the_branch(self):
        from fleet.release_git import changelog_section
        text = changelog_section(Version.parse("0.2.0"), head="abc1234", branch="live",
                                 upstream_base="v6.2.0", prev_tag="fleet/v0.1.0",
                                 commits=[("deadbee", "did a thing")], rebased=True,
                                 when="2026-08-02T00:00:00Z")
        self.assertIn("patch-id", text)
        self.assertIn("no longer an ancestor", text)
        self.assertIn("- deadbee did a thing", text)

    def test_the_changelog_of_a_first_release_records_the_commit_and_omits_the_list(self):
        from fleet.release_git import changelog_section
        text = changelog_section(Version.parse("0.1.0"), head="abc1234", branch="live",
                                 upstream_base="v6.2.0", prev_tag=None, commits=[], rebased=False,
                                 when="2026-08-02T00:00:00Z")
        self.assertIn("abc1234", text)
        self.assertIn("no predecessor", text)
        self.assertNotIn("\n- ", text)

    def test_export_writes_committed_content_only(self):
        from fleet.release_git import Repo
        self._commit("a.txt", "committed")
        self.run("tag", "-a", "fleet/v0.1.0", "-m", "r1")
        (self.repo / "untracked.txt").write_text("must not ship")
        dest = self.tmp / "out"
        Repo(self.repo).export("fleet/v0.1.0", dest)
        self.assertEqual((dest / "a.txt").read_text(), "committed")
        self.assertFalse((dest / "untracked.txt").exists())
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/ubuntu/davis_root/superpowers/fleet && PYTHONPATH=src python3 -m unittest tests.test_release.GitCase -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.release_git'`

- [ ] **Step 3: Write `fleet/src/fleet/release_git.py`**

```python
"""Every git call the release pipeline makes, in one place.

Isolated from `release.py` so that "what is deployed" never depends on a working repository, and so the
one genuinely subtle thing here -- computing a delta that survives a rebase -- has a single home.
"""
import subprocess
from pathlib import Path

from fleet.errors import BadInput, Refused
from fleet.release import Version

__all__ = ["Repo", "changelog_section"]


class Repo:
    def __init__(self, path):
        self.path = Path(path)
        if not (self.path / ".git").exists():
            raise BadInput(
                f"{self.path} is not a git repository (no .git). The repo is named explicitly and never "
                f"inferred from the working directory: these verbs create tags and commits, and a verb "
                f"that guesses its repository will eventually tag the wrong one.")

    def _git(self, *args, check=True) -> str:
        done = subprocess.run(["git", "-C", str(self.path), *args],
                              capture_output=True, text=True)
        if check and done.returncode != 0:
            raise BadInput(f"git {' '.join(args)} failed ({done.returncode}): "
                           f"{(done.stderr or done.stdout).strip()}")
        return done.stdout

    # --- state -------------------------------------------------------------------------------------
    def dirty(self) -> list:
        """Every path git considers changed, including untracked. An export carries committed content
        only, so anything here is content the operator can see and the artifact cannot."""
        return [line[3:].strip() for line in
                self._git("status", "--porcelain").splitlines() if line.strip()]

    def head(self) -> str:
        return self._git("rev-parse", "HEAD").strip()

    def branch(self) -> str:
        return self._git("rev-parse", "--abbrev-ref", "HEAD").strip()

    def tag_exists(self, name: str) -> bool:
        return bool(self._git("tag", "-l", name).strip())

    def upstream_base(self) -> str:
        """The most recent non-`fleet/` tag reachable from HEAD -- the upstream release this fork sits on.
        Recorded for provenance only; nothing branches on it."""
        out = self._git("describe", "--tags", "--abbrev=0", "--exclude", "fleet/*", check=False).strip()
        return out or "(none)"

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        done = subprocess.run(["git", "-C", str(self.path), "merge-base", "--is-ancestor",
                               ancestor, descendant], capture_output=True, text=True)
        return done.returncode == 0

    # --- the delta ---------------------------------------------------------------------------------
    def delta(self, prev_tag):
        """`[(sha, subject)]` for every commit on HEAD and not in `prev_tag`, compared BY PATCH-ID.

        `git log prev..HEAD` would compare by ancestry, and the 03:30 rebase rewrites every commit this
        fork carries -- after which the previous tag is no longer an ancestor and the ancestry answer is
        wrong without being empty. `git cherry` compares patch-ids, which a rebase preserves.
        """
        if prev_tag is None:
            return []
        out = self._git("cherry", "-v", prev_tag, "HEAD")
        commits = []
        for line in out.splitlines():
            if not line.startswith("+ "):
                continue                      # "- " means the change is already in the reference
            rest = line[2:]
            sha, _, subject = rest.partition(" ")
            commits.append((sha[:7], subject.strip()))
        return commits

    # --- mutation ----------------------------------------------------------------------------------
    def commit(self, paths, message: str) -> None:
        self._git("add", *[str(p) for p in paths])
        self._git("commit", "-q", "-m", message)

    def annotated_tag(self, name: str, message: str) -> None:
        if self.tag_exists(name):
            raise Refused(
                f"the tag {name} already exists. A release tag is never moved: it is what keeps the exact "
                f"tree recoverable after the nightly rebase rewrites its commits off the branch. Choose "
                f"the next version instead.")
        self._git("tag", "-a", name, "-m", message)

    def export(self, tag: str, dest) -> None:
        """`git archive` the tag into `dest`. Never a directory copy: the working tree carries ~66 MB of
        untracked IT output and `__pycache__` beside 4.9 MB of tracked files."""
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        archive = subprocess.Popen(["git", "-C", str(self.path), "archive", "--format=tar", tag],
                                   stdout=subprocess.PIPE)
        extract = subprocess.Popen(["tar", "-x", "-C", str(dest)], stdin=archive.stdout)
        archive.stdout.close()
        extract.communicate()
        if archive.wait() != 0 or extract.returncode != 0:
            raise BadInput(f"exporting {tag} into {dest} failed")


def changelog_section(version: Version, *, head: str, branch: str, upstream_base: str,
                      prev_tag, commits, rebased: bool, when: str) -> str:
    """One release's changelog section. The same text is prepended to `fleet/CHANGELOG.md` and written
    into the artifact, so a release always carries its own notes."""
    lines = [f"## {version.tag} — {when}"]
    if prev_tag is None:
        lines.append(f"Cut from {head[:7]} on `{branch}` (upstream base {upstream_base}). "
                     f"Initial release — no predecessor, so no commit range is listed.")
        return "\n".join(lines) + "\n"
    lines.append(f"Cut from {head[:7]} on `{branch}` (upstream base {upstream_base}). "
                 f"{len(commits)} commit(s) since {prev_tag}.")
    if rebased:
        lines.append("")
        lines.append(f"> {prev_tag} is no longer an ancestor of `{branch}` — an upstream rebase rewrote "
                     f"the commits between. This delta was computed by patch-id, not by ancestry.")
    lines.append("")
    lines.extend(f"- {sha} {subject}" for sha, subject in commits)
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd /home/ubuntu/davis_root/superpowers/fleet && PYTHONPATH=src python3 -m unittest tests.test_release.GitCase -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Prove the rebase test is not vacuous**

Change `delta` to use ancestry:

```python
out = self._git("log", "--format=+ %H %s", f"{prev_tag}..HEAD")
```

Run: `PYTHONPATH=src python3 -m unittest tests.test_release.GitCase.test_delta_survives_a_rebase_that_rewrites_every_hash -v`
Expected: FAIL — the post-rebase delta gains the rewritten duplicates. Restore `git cherry` and confirm PASS. This is the single most important assertion in the plan; if it passes both ways the fixture is not producing a real rebase.

- [ ] **Step 6: Commit**

```bash
git add fleet/src/fleet/release_git.py fleet/tests/test_release.py
git commit -m "release: a delta computed by patch-id, so the nightly rebase cannot corrupt a changelog"
```

---

### Task 3: `release_verify.py` — suites against the frozen export

**Files:**
- Create: `fleet/src/fleet/release_verify.py`
- Modify: `fleet/tests/test_release.py` (append a `VerifyCase`)

**Interfaces:**
- Consumes: `fleet.release.Releases`, `fleet.release.Version`, `fleet.release.tree_sha`
- Produces:
  - `GREEN = "GREEN"`, `RED = "RED"`, `INCONCLUSIVE = "INCONCLUSIVE"`
  - `GATE_ROSTER = "gate"`, `FULL_ROSTER = "full"`
  - `verdict_for(hermetic_ok: bool, it_ok: bool, activity_changed: bool) -> str`
  - `Verify(releases, version, runner=subprocess.run)` with `.run(full: bool) -> str`
  - `write_verdict(meta_dir, rows, roster) -> None`, `read_verdict(meta_dir) -> dict`

**Design notes:**

*`PYTHONDONTWRITEBYTECODE=1` is load-bearing.* The export is `chmod -R a-w`; without it, `unittest` tries to write `__pycache__` into our own read-only artifact.

*The IT suite cannot run inside a read-only export* — `run-all.sh` writes `RESULTS*.tsv` beside itself. Rather than teach twenty runner scripts an output directory, `verify` copies the export to scratch, runs there, copies results back, and recomputes `tree_sha` on the copy to prove what was tested is what shipped.

*Verdict logic is a pure function*, separated from the running, so the INCONCLUSIVE rule is testable without executing an 11-runner suite.

- [ ] **Step 1: Write the failing tests (append to `fleet/tests/test_release.py`)**

```python
class VerifyCase(unittest.TestCase):
    def test_green_only_when_both_suites_pass(self):
        from fleet.release_verify import GREEN, verdict_for
        self.assertEqual(verdict_for(True, True, False), GREEN)

    def test_a_failure_on_a_quiet_box_is_red(self):
        from fleet.release_verify import RED, verdict_for
        self.assertEqual(verdict_for(False, True, False), RED)
        self.assertEqual(verdict_for(True, False, False), RED)

    def test_a_failure_while_the_box_was_busy_is_inconclusive_not_red(self):
        # Contamination is never a verdict. This is the source-pin doctrine applied to the one baseline
        # the suite cannot own, and it is what stops a coordinator finishing mid-run from writing a
        # permanent false RED into a release's evidence.
        from fleet.release_verify import INCONCLUSIVE, verdict_for
        self.assertEqual(verdict_for(False, True, True), INCONCLUSIVE)
        self.assertEqual(verdict_for(True, False, True), INCONCLUSIVE)

    def test_activity_during_a_passing_run_is_still_green(self):
        # Without this, INCONCLUSIVE would swallow every busy-box run and nothing could ever promote.
        from fleet.release_verify import GREEN, verdict_for
        self.assertEqual(verdict_for(True, True, True), GREEN)

    def test_the_verdict_file_records_the_roster_that_actually_ran(self):
        from fleet.release_verify import GATE_ROSTER, read_verdict, write_verdict
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        write_verdict(tmp, [("hermetic", "GREEN", "hermetic.log", "864 tests"),
                            ("it", "GREEN", "it-RESULTS.tsv", "11 runners")], GATE_ROSTER)
        got = read_verdict(tmp)
        self.assertEqual(got["roster"], GATE_ROSTER)
        self.assertEqual(got["suites"]["hermetic"], "GREEN")
        self.assertEqual(got["suites"]["it"], "GREEN")

    def test_a_missing_verdict_file_reads_as_empty_rather_than_raising(self):
        from fleet.release_verify import read_verdict
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        self.assertEqual(read_verdict(tmp), {})

    def test_verify_refuses_when_the_scratch_copy_does_not_match_the_manifest(self):
        # The claim "what was tested is what shipped" is ASSERTED, not assumed. If the copy diverges the
        # run is meaningless, and reporting RED would blame the code for a harness fault.
        from fleet.errors import Refused
        from fleet.release import Releases, Version
        from fleet.release_verify import Verify
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        rel = Releases(tmp / "releases")
        v = Version.parse("0.1.0")
        (rel.dir_for(v) / ".release").mkdir(parents=True)
        (rel.dir_for(v) / "payload.txt").write_text("x")
        rel.write_manifest(v, {"version": "0.1.0", "tree_sha": "0" * 64})   # deliberately wrong
        with self.assertRaises(Refused):
            Verify(rel, v).check_copy_matches(rel.dir_for(v))
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/ubuntu/davis_root/superpowers/fleet && PYTHONPATH=src python3 -m unittest tests.test_release.VerifyCase -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.release_verify'`

- [ ] **Step 3: Write `fleet/src/fleet/release_verify.py`**

```python
"""Run both suites against a frozen export and say what happened.

Against the EXPORT and not the checkout, which is what makes contamination structural instead of
procedural: `run-all.sh` pins `src/*.py` before and after precisely because an edit mid-run invalidates
every verdict measured before it, and nothing can edit a read-only artifact.
"""
import os
import shutil
import subprocess
from pathlib import Path

from fleet.errors import Refused
from fleet.release import META_DIR, Releases, Version, tree_sha

__all__ = ["FULL_ROSTER", "GATE_ROSTER", "GREEN", "INCONCLUSIVE", "RED", "Verify",
           "read_verdict", "verdict_for", "write_verdict"]

GREEN = "GREEN"
RED = "RED"
INCONCLUSIVE = "INCONCLUSIVE"

GATE_ROSTER = "gate"
FULL_ROSTER = "full"

VERDICT_COLUMNS = ("suite", "verdict", "evidence", "note")


def verdict_for(hermetic_ok: bool, it_ok: bool, activity_changed: bool) -> str:
    """GREEN, RED or INCONCLUSIVE.

    A failure concurrent with operator activity is INCONCLUSIVE rather than RED. The IT suite baselines
    this box's live session set, so a coordinator starting or finishing mid-run can fail a section for
    reasons that have nothing to do with the release. Contamination is never a verdict: an INCONCLUSIVE
    costs a re-run, while a false RED is written into a release's evidence for good.

    Activity during a run that PASSED is not interesting -- nothing needs explaining.
    """
    if hermetic_ok and it_ok:
        return GREEN
    return INCONCLUSIVE if activity_changed else RED


def write_verdict(meta_dir, rows, roster: str) -> None:
    meta_dir = Path(meta_dir)
    (meta_dir / "evidence").mkdir(parents=True, exist_ok=True)
    body = ["\t".join(VERDICT_COLUMNS)]
    body.extend("\t".join(str(cell) for cell in row) for row in rows)
    body.append(f"roster\t{roster}\t-\tthe set of IT runners this verdict covers")
    (meta_dir / "evidence" / "VERDICT.tsv").write_text("\n".join(body) + "\n")


def read_verdict(meta_dir) -> dict:
    path = Path(meta_dir) / "evidence" / "VERDICT.tsv"
    if not path.is_file():
        return {}
    suites, roster = {}, None
    for line in path.read_text().splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        if parts[0] == "roster":
            roster = parts[1]
        else:
            suites[parts[0]] = parts[1]
    return {"suites": suites, "roster": roster}


class Verify:
    def __init__(self, releases: Releases, version: Version, runner=None):
        self.releases = releases
        self.version = version
        self.runner = runner or (lambda argv, **kw: subprocess.run(argv, **kw))

    @property
    def export(self) -> Path:
        return self.releases.dir_for(self.version)

    @property
    def meta(self) -> Path:
        return self.export / META_DIR

    def check_copy_matches(self, copy_root) -> None:
        recorded = self.releases.manifest(self.version).get("tree_sha")
        actual = tree_sha(copy_root)
        if recorded and recorded != actual:
            raise Refused(
                f"the tree being tested does not match the artifact: MANIFEST records {recorded[:12]}…, "
                f"the copy at {copy_root} hashes to {actual[:12]}…. Refused rather than reported as RED — "
                f"a mismatch here means the harness tested something other than the release, so the run "
                f"says nothing about the code.")

    def _live_subjects(self) -> str:
        done = self.runner(["fleet", "board", "--porcelain"], capture_output=True, text=True)
        return done.stdout if done.returncode == 0 else ""

    def run(self, full: bool = False) -> str:
        evidence = self.meta / "evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        roster = FULL_ROSTER if full else GATE_ROSTER

        before = self._live_subjects()
        (evidence / "live-subjects-before.tsv").write_text(before)

        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(self.export / "fleet" / "src"))
        hermetic = self.runner(
            ["python3", "-m", "unittest", "discover", "-s", "tests", "-q"],
            cwd=str(self.export / "fleet"), env=env, capture_output=True, text=True)
        (evidence / "hermetic.log").write_text((hermetic.stdout or "") + (hermetic.stderr or ""))

        # The IT suite writes RESULTS*.tsv beside itself and cannot run inside a read-only export.
        scratch = self.export.parent / f".verify-{self.version}"
        if scratch.exists():
            shutil.rmtree(scratch)
        shutil.copytree(self.export, scratch, symlinks=True)
        for path in scratch.rglob("*"):
            if path.is_file():
                path.chmod(path.stat().st_mode | 0o200)
        self.check_copy_matches(scratch)

        argv = ["bash", str(scratch / "fleet" / "it" / "run-all.sh")] + (["--full"] if full else [])
        it_run = self.runner(argv, cwd=str(scratch), capture_output=True, text=True)
        (evidence / "it-FULL-RUN.log").write_text((it_run.stdout or "") + (it_run.stderr or ""))
        merged = scratch / "fleet" / "it" / "RESULTS-closeout-all.tsv"
        if merged.is_file():
            shutil.copy(merged, evidence / "it-RESULTS.tsv")
        for pin in ("SOURCE-PIN-group5-before.txt", "SOURCE-PIN-group5-after.txt"):
            candidate = scratch / "fleet" / "it" / pin
            if candidate.is_file():
                shutil.copy(candidate, evidence / pin.replace("group5-", "").replace(".txt", ".txt"))
        shutil.rmtree(scratch, ignore_errors=True)

        after = self._live_subjects()
        (evidence / "live-subjects-after.tsv").write_text(after)
        activity_changed = before != after

        result = verdict_for(hermetic.returncode == 0, it_run.returncode == 0, activity_changed)
        write_verdict(self.meta, [
            ("hermetic", GREEN if hermetic.returncode == 0 else RED, "evidence/hermetic.log",
             f"exit {hermetic.returncode}"),
            ("it", GREEN if it_run.returncode == 0 else RED, "evidence/it-RESULTS.tsv",
             f"exit {it_run.returncode}; live-subject set "
             f"{'CHANGED during the run' if activity_changed else 'unchanged'}"),
        ], roster)
        return result
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd /home/ubuntu/davis_root/superpowers/fleet && PYTHONPATH=src python3 -m unittest tests.test_release.VerifyCase -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Prove the INCONCLUSIVE rule is not vacuous**

Change `verdict_for`'s last line to `return RED`. Run `tests.test_release.VerifyCase` — `test_a_failure_while_the_box_was_busy_is_inconclusive_not_red` must FAIL. Restore.

- [ ] **Step 6: Commit**

```bash
git add fleet/src/fleet/release_verify.py fleet/tests/test_release.py
git commit -m "release: verify against the frozen export, and never call contamination a verdict"
```

---

### Task 4: the eight verbs

**Files:**
- Modify: `fleet/src/fleet/cli.py` (**one agent at a time on this file**)
- Modify: `fleet/tests/test_release.py` (append a `CliCase`)

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: eight entries in `VERBS`.

**The surface:**

| Verb | Flags | read_only |
|---|---|---|
| `release-cut` | `--version`* `--repo`* `--releases` `--notes` | no |
| `release-verify` | `--version`* `--releases` `--full` | no |
| `release-promote` | `--version`* `--releases` | no |
| `release-deploy` | `--version` `--dev` `--releases` `--reason` `--force` | no |
| `release-rollback` | `--to` `--reason`* `--releases` | no |
| `release-status` | `--releases` | yes |
| `release-list` | `--releases` | yes |
| `release-history` | `--releases` `--limit` | yes |

`*` = required. `--releases` overrides `$FLEET_RELEASES`; a **mutating** verb refuses without one, a read-only verb defaults to `$HOME/.fleet-releases`, mirroring `FLEET_HOME` exactly.

**Two refusals carry the design:**

1. **A mutating verb refuses when its own package resolves inside `$FLEET_RELEASES`** (exit 4). The tool that manages `current` must not be the thing `current` points at, or rolling back to a version whose release code has a bug also rolls back the ability to roll forward. Read-only verbs work from anywhere.
2. **`--force` requires `--reason`.** Deploying an unverified candidate is exactly the event the history file exists to explain.

- [ ] **Step 1: Write the failing tests (append to `fleet/tests/test_release.py`)**

```python
class CliCase(unittest.TestCase):
    """The CLI's refusals. Driven through `main` so the exit code asserted is the one an operator sees."""

    def setUp(self):
        import io
        import shutil
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.releases = self.tmp / "releases"
        self.releases.mkdir()
        self.out, self.err = io.StringIO(), io.StringIO()

    def run_verb(self, *argv):
        from fleet.cli import main
        return main(list(argv), stdout=self.out, stderr=self.err)

    def test_a_mutating_release_verb_refuses_with_no_releases_root(self):
        from fleet import EXIT_BAD_INPUT
        import os
        old = os.environ.pop("FLEET_RELEASES", None)
        self.addCleanup(lambda: os.environ.__setitem__("FLEET_RELEASES", old) if old else None)
        code = self.run_verb("release-promote", "--version", "0.1.0", "--home", str(self.tmp))
        self.assertEqual(code, EXIT_BAD_INPUT)
        self.assertIn("FLEET_RELEASES", self.err.getvalue())

    def test_deploy_refuses_a_candidate_without_force(self):
        from fleet import EXIT_REFUSED
        from fleet.release import CANDIDATE, Releases, Version
        rel = Releases(self.releases)
        v = Version.parse("0.1.0")
        (rel.dir_for(v) / ".release").mkdir(parents=True)
        rel.set_state(v, CANDIDATE)
        code = self.run_verb("release-deploy", "--version", "0.1.0", "--releases", str(self.releases),
                             "--home", str(self.tmp))
        self.assertEqual(code, EXIT_REFUSED)
        self.assertIn("CANDIDATE", self.err.getvalue())

    def test_force_without_a_reason_is_refused(self):
        from fleet import EXIT_REFUSED
        from fleet.release import CANDIDATE, Releases, Version
        rel = Releases(self.releases)
        v = Version.parse("0.1.0")
        (rel.dir_for(v) / ".release").mkdir(parents=True)
        rel.set_state(v, CANDIDATE)
        code = self.run_verb("release-deploy", "--version", "0.1.0", "--releases", str(self.releases),
                             "--force", "--home", str(self.tmp))
        self.assertEqual(code, EXIT_REFUSED)
        self.assertIn("--reason", self.err.getvalue())

    def test_promote_refuses_without_green_evidence(self):
        from fleet import EXIT_REFUSED
        from fleet.release import Releases, Version
        from fleet.release_verify import GATE_ROSTER, RED, write_verdict
        rel = Releases(self.releases)
        v = Version.parse("0.1.0")
        meta = rel.dir_for(v) / ".release"
        meta.mkdir(parents=True)
        write_verdict(meta, [("hermetic", RED, "e", "n"), ("it", "GREEN", "e", "n")], GATE_ROSTER)
        code = self.run_verb("release-promote", "--version", "0.1.0", "--releases", str(self.releases),
                             "--home", str(self.tmp))
        self.assertEqual(code, EXIT_REFUSED)

    def test_promote_refuses_a_minor_bump_that_only_has_gate_evidence(self):
        from fleet import EXIT_REFUSED
        from fleet.release import Releases, Version
        from fleet.release_verify import GATE_ROSTER, GREEN, write_verdict
        rel = Releases(self.releases)
        for name in ("0.1.0", "0.2.0"):
            (rel.dir_for(Version.parse(name)) / ".release").mkdir(parents=True)
        write_verdict(rel.dir_for(Version.parse("0.2.0")) / ".release",
                      [("hermetic", GREEN, "e", "n"), ("it", GREEN, "e", "n")], GATE_ROSTER)
        code = self.run_verb("release-promote", "--version", "0.2.0", "--releases", str(self.releases),
                             "--home", str(self.tmp))
        self.assertEqual(code, EXIT_REFUSED)
        self.assertIn("--full", self.err.getvalue())

    def test_promote_accepts_a_patch_bump_on_gate_evidence(self):
        from fleet import EXIT_OK
        from fleet.release import RELEASED, Releases, Version
        from fleet.release_verify import GATE_ROSTER, GREEN, write_verdict
        rel = Releases(self.releases)
        for name in ("0.1.0", "0.1.1"):
            (rel.dir_for(Version.parse(name)) / ".release").mkdir(parents=True)
        write_verdict(rel.dir_for(Version.parse("0.1.1")) / ".release",
                      [("hermetic", GREEN, "e", "n"), ("it", GREEN, "e", "n")], GATE_ROSTER)
        code = self.run_verb("release-promote", "--version", "0.1.1", "--releases", str(self.releases),
                             "--home", str(self.tmp))
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(rel.state(Version.parse("0.1.1")), RELEASED)

    def test_rollback_defaults_its_target_to_the_previously_deployed_version(self):
        from fleet import EXIT_OK
        from fleet.release import RELEASED, Releases, Version
        rel = Releases(self.releases)
        for name in ("0.1.0", "0.2.0"):
            v = Version.parse(name)
            (rel.dir_for(v) / ".release").mkdir(parents=True)
            rel.set_state(v, RELEASED)
        rel.append_history(action="DEPLOY", version="0.2.0", from_version="0.1.0",
                           actor="a", host="b", reason="r", evidence="-")
        rel.point_current_at(rel.dir_for(Version.parse("0.2.0")))
        code = self.run_verb("release-rollback", "--reason", "harvest wedged",
                             "--releases", str(self.releases), "--home", str(self.tmp))
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(rel.current_label(), "0.1.0")
        last = rel.history()[-1]
        self.assertEqual(last["action"], "ROLLBACK")
        self.assertEqual(last["from_version"], "0.2.0")
        self.assertEqual(last["reason"], "harvest wedged")

    def test_status_is_read_only_and_works_with_no_releases_root_named(self):
        from fleet import EXIT_OK
        self.assertEqual(self.run_verb("release-status", "--releases", str(self.releases)), EXIT_OK)

    def test_every_release_verb_is_in_the_registry_with_a_help_string(self):
        from fleet.cli import VERBS
        for name in ("release-cut", "release-verify", "release-promote", "release-deploy",
                     "release-rollback", "release-status", "release-list", "release-history"):
            self.assertIn(name, VERBS)
            self.assertTrue(VERBS[name].help.strip(), f"{name} has no help text")
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/ubuntu/davis_root/superpowers/fleet && PYTHONPATH=src python3 -m unittest tests.test_release.CliCase -v`
Expected: FAIL — `release-promote` is not a declared verb, so `main` returns 2 with "unknown verb" for tests expecting 4/0.

- [ ] **Step 3: Add the handlers to `cli.py`**

Insert after the imports:

```python
from fleet.release import (CANDIDATE, DEV, RELEASED, Releases, Version, actor, tree_sha,
                           utc_now)
from fleet.release_git import Repo, changelog_section
from fleet.release_verify import (FULL_ROSTER, GATE_ROSTER, GREEN, Verify, read_verdict)
```

Insert before the `VERBS` assignment:

```python
# --- releases ---------------------------------------------------------------------------------------
#
# Flat verbs rather than `release <subverb>`: `parse` declares no positionals (`FI-19d`) and `main`
# dispatches on argv[0] against one flat table. Flat also means each of these enrols automatically into
# §A5's exit-code matrix and §M's flag matrices, which derive their population from `VERBS`.
#
# `--repo` is REQUIRED on every verb that touches git, and never inferred from the working directory.
# §A5 and §M drive every verb in this table through a REAL invocation; a verb that guessed its repository
# would tag the live one during an IT run.


def _releases(ctx: Ctx, parsed: Parsed) -> Releases:
    """The release area, named or refused. Same rule as `FLEET_HOME` (`SI-15`): a mutating verb that
    invents a destination is how shared state gets written by a command aimed somewhere else."""
    named = parsed.get("releases") or os.environ.get("FLEET_RELEASES")
    spec = VERBS.get(parsed.verb)
    if not named and spec is not None and not spec.read_only:
        raise BadInput(
            f"{parsed.verb!r} writes to a release area and none was named: pass `--releases <path>` or "
            f"export FLEET_RELEASES. There is no default for a write.")
    return Releases(Path(named or (Path.home() / ".fleet-releases")))


def _refuse_if_self_deployed(rel: Releases, parsed: Parsed) -> None:
    """A mutating release verb must not run from inside the release area it manages.

    Otherwise rolling back to a version whose release code has a bug also rolls back the ability to roll
    forward — the tool that moves `current` cannot be the thing `current` points at.
    """
    spec = VERBS.get(parsed.verb)
    if spec is not None and spec.read_only:
        return
    here = Path(__file__).resolve()
    root = rel.root.resolve()
    if root in here.parents:
        raise Refused(
            f"{parsed.verb!r} is running from {here}, which is inside the release area {root}. Run it "
            f"from the git checkout instead. The tool that manages `current` must not be the thing "
            f"`current` points at: a bad release would otherwise take the fix path down with it.")


def _do_release_cut(ctx: Ctx, parsed: Parsed) -> int:
    rel = _releases(ctx, parsed)
    _refuse_if_self_deployed(rel, parsed)
    version = Version.parse(parsed.get("version"))
    repo = Repo(parsed.get("repo"))
    with rel.lock():
        if rel.dir_for(version).exists():
            raise Refused(f"{version} already exists at {rel.dir_for(version)}. A release is immutable.")
        dirty = repo.dirty()
        if dirty:
            raise Refused(
                f"the tree at {repo.path} has {len(dirty)} uncommitted path(s): "
                f"{', '.join(dirty[:5])}{' …' if len(dirty) > 5 else ''}. An export carries committed "
                f"content only, so a dirty tree means the thing tested is not the thing you edited.")
        prev = rel.previous(version)
        prev_tag = prev.tag if prev else None
        rebased = bool(prev_tag) and not repo.is_ancestor(prev_tag, "HEAD")
        commits = repo.delta(prev_tag)
        when, head = utc_now(), repo.head()
        section = changelog_section(version, head=head, branch=repo.branch(),
                                    upstream_base=repo.upstream_base(), prev_tag=prev_tag,
                                    commits=commits, rebased=rebased, when=when)

        changelog = repo.path / "fleet" / "CHANGELOG.md"
        existing = changelog.read_text() if changelog.is_file() else "# fleet — changelog\n"
        head_line, _, rest = existing.partition("\n")
        changelog.write_text(f"{head_line}\n\n{section}\n{rest.lstrip()}")

        init_py = repo.path / "fleet" / "src" / "fleet" / "__init__.py"
        init_py.write_text(re.sub(r'__version__ = "[^"]*"', f'__version__ = "{version}"',
                                  init_py.read_text()))
        repo.commit([changelog, init_py], f"fleet v{version}")
        repo.annotated_tag(version.tag, section)
        repo.export(version.tag, rel.dir_for(version))

        rel.write_manifest(version, {
            "version": str(version), "tag": version.tag, "source_commit": repo.head(),
            "source_branch": repo.branch(), "upstream_base": repo.upstream_base(),
            "tree_sha": tree_sha(rel.dir_for(version)), "cut_at": when, "cut_by": actor(),
            "notes": parsed.get("notes") or "-"})
        rel.set_state(version, CANDIDATE)
        subprocess.run(["chmod", "-R", "a-w", str(rel.dir_for(version))], check=False)
    _write(ctx, f"cut {version} as CANDIDATE at {rel.dir_for(version)} "
                f"({len(commits)} commit(s) since {prev_tag or 'no predecessor'})")
    return EXIT_OK


def _do_release_verify(ctx: Ctx, parsed: Parsed) -> int:
    rel = _releases(ctx, parsed)
    _refuse_if_self_deployed(rel, parsed)
    version = Version.parse(parsed.get("version"))
    if not rel.dir_for(version).is_dir():
        raise BadInput(f"no release {version} at {rel.dir_for(version)}")
    if ctx.live_work_now():
        print("note: this box has live fleet work. The IT suite baselines the live session set, so a "
              "failure may be contamination rather than a defect — that is what INCONCLUSIVE records.",
              file=ctx.err)
    result = Verify(rel, version).run(full=parsed.on("full"))
    _write(ctx, f"{version}: {result}")
    return EXIT_OK if result == GREEN else EXIT_ATTENTION


def _do_release_promote(ctx: Ctx, parsed: Parsed) -> int:
    rel = _releases(ctx, parsed)
    _refuse_if_self_deployed(rel, parsed)
    version = Version.parse(parsed.get("version"))
    verdict = read_verdict(rel.dir_for(version) / ".release")
    suites = verdict.get("suites") or {}
    if not suites or any(value != GREEN for value in suites.values()):
        raise Refused(
            f"{version} has no GREEN evidence: {suites or 'no VERDICT.tsv at all'}. Run "
            f"`fleet release-verify --version {version}` first. `promote` never runs tests — it reads "
            f"what `verify` left, so a promotion always cites a measurement someone can go and look at.")
    prev = rel.previous(version)
    if prev is not None and version.bump_kind(prev) in ("minor", "major") \
            and verdict.get("roster") != FULL_ROSTER:
        raise Refused(
            f"{version} is a {version.bump_kind(prev)} bump over {prev}, and its evidence covers only the "
            f"gate roster. Re-run with `fleet release-verify --version {version} --full`.")
    with rel.lock():
        rel.set_state(version, RELEASED)
    _write(ctx, f"{version} is RELEASED")
    return EXIT_OK


def _deploy(ctx: Ctx, parsed: Parsed, rel: Releases, target_label: str, target_path: Path,
            action: str, reason: str) -> int:
    with rel.lock():
        before = rel.current_label()
        running = [s for s in ctx.subjects() if getattr(s, "state", "") == "RUNNING"]
        if running:
            print(f"note: {len(running)} subject(s) are RUNNING. Their next `fleet` call gets "
                  f"{target_label}; the one in flight keeps the release it started on.", file=ctx.err)
        rel.point_current_at(target_path)
        evidence = "-" if target_label == DEV else \
            f"{Path(target_path).name}/.release/evidence"
        rel.append_history(action=action, version=target_label, from_version=before,
                           reason=reason, evidence=evidence)
    _write(ctx, f"{before} -> {target_label}")
    return EXIT_OK


def _do_release_deploy(ctx: Ctx, parsed: Parsed) -> int:
    rel = _releases(ctx, parsed)
    _refuse_if_self_deployed(rel, parsed)
    reason = parsed.get("reason")
    if parsed.on("dev"):
        checkout = Path(__file__).resolve().parents[3]
        return _deploy(ctx, parsed, rel, DEV, checkout, DEV, reason or "developer mode")
    version = Version.parse(parsed.get("version"))
    if not rel.dir_for(version).is_dir():
        raise BadInput(f"no release {version} at {rel.dir_for(version)}")
    if rel.state(version) != RELEASED:
        if not parsed.on("force"):
            raise Refused(
                f"{version} is {rel.state(version)}, not RELEASED. Promote it, or pass `--force` WITH a "
                f"`--reason`.")
        if not reason:
            raise Refused(
                "`--force` requires `--reason`. Deploying an unverified candidate is exactly the event "
                "the history file exists to explain.")
    return _deploy(ctx, parsed, rel, str(version), rel.dir_for(version), "DEPLOY",
                   reason or f"deploy {version}")


def _do_release_rollback(ctx: Ctx, parsed: Parsed) -> int:
    rel = _releases(ctx, parsed)
    _refuse_if_self_deployed(rel, parsed)
    reason = parsed.get("reason")
    target = parsed.get("to")
    if target is None:
        rows = [r for r in rel.history() if r["action"] in ("DEPLOY", "ROLLBACK")]
        if not rows or rows[-1]["from_version"] in ("-", ""):
            raise BadInput(
                "no previous deployment is recorded, so there is nothing to roll back to. Name one with "
                "`--to <version>`.")
        target = rows[-1]["from_version"]
    if target == DEV:
        checkout = Path(__file__).resolve().parents[3]
        return _deploy(ctx, parsed, rel, DEV, checkout, "ROLLBACK", reason)
    version = Version.parse(target)
    if not rel.dir_for(version).is_dir():
        raise BadInput(f"no release {version} at {rel.dir_for(version)}")
    return _deploy(ctx, parsed, rel, str(version), rel.dir_for(version), "ROLLBACK", reason)


def _do_release_status(ctx: Ctx, parsed: Parsed) -> int:
    rel = _releases(ctx, parsed)
    label = rel.current_label()
    rows = [r for r in rel.history() if r["action"] in ("DEPLOY", "ROLLBACK", DEV)]
    last = rows[-1] if rows else None
    lines = [f"current\t{label}"]
    if label == DEV:
        # "DEV" alone is true about the pointer and misleading about the code: in dev mode what is live
        # is whatever the checkout says right now.
        checkout = rel.current_target()
        repo_head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "--short", "HEAD"],
                                   capture_output=True, text=True)
        status = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain"],
                                capture_output=True, text=True)
        lines.append(f"checkout\t{checkout}")
        lines.append(f"head\t{repo_head.stdout.strip() or 'unknown'}")
        lines.append(f"dirty\t{'yes' if status.stdout.strip() else 'no'}")
    elif label != "none":
        lines.append(f"state\t{rel.state(Version.parse(label))}")
    if last:
        lines.append(f"since\t{last['ts']}")
        lines.append(f"by\t{last['actor']}")
        lines.append(f"reason\t{last['reason']}")
    _write(ctx, "\n".join(lines))
    return EXIT_OK


def _do_release_list(ctx: Ctx, parsed: Parsed) -> int:
    rel = _releases(ctx, parsed)
    current = rel.current_label()
    lines = ["version\tstate\tcut_at\tcurrent"]
    for version in rel.versions():
        manifest = rel.manifest(version)
        lines.append(f"{version}\t{rel.state(version)}\t{manifest.get('cut_at', '-')}\t"
                     f"{'*' if str(version) == current else ''}")
    _write(ctx, "\n".join(lines))
    return EXIT_OK


def _do_release_history(ctx: Ctx, parsed: Parsed) -> int:
    rel = _releases(ctx, parsed)
    rows = rel.history()
    limit = parsed.get("limit")
    if limit is not None:
        try:
            rows = rows[-int(limit):]
        except ValueError:
            raise BadInput(f"--limit takes an integer; got {limit!r}")
    from fleet.release import HISTORY_COLUMNS
    lines = ["\t".join(HISTORY_COLUMNS)]
    lines.extend("\t".join(row[name] for name in HISTORY_COLUMNS) for row in rows)
    _write(ctx, "\n".join(lines))
    return EXIT_OK
```

Then add to the `VERBS` tuple:

```python
    _verb("release-cut", _do_release_cut, False,
          "export an immutable release from a tag and write its changelog", (
        Flag("--version", True, True, "the new version, X.Y.Z; the tag becomes fleet/vX.Y.Z"),
        Flag("--repo", True, True, "the git checkout to cut from; never inferred from the cwd"),
        Flag("--releases", True, False, "the release area; overrides $FLEET_RELEASES"),
        Flag("--notes", True, False, "a one-line note recorded in MANIFEST.tsv"),
    )),
    _verb("release-verify", _do_release_verify, False,
          "run both suites against a release's frozen export and record the verdict", (
        Flag("--version", True, True, "the release to verify"),
        Flag("--releases", True, False, "the release area; overrides $FLEET_RELEASES"),
        Flag("--full", False, False, "run all 19 IT runners, not just the gate roster"),
    )),
    _verb("release-promote", _do_release_promote, False,
          "mark a CANDIDATE as RELEASED; refuses without GREEN evidence", (
        Flag("--version", True, True, "the release to promote"),
        Flag("--releases", True, False, "the release area; overrides $FLEET_RELEASES"),
    )),
    _verb("release-deploy", _do_release_deploy, False,
          "point `current` at a release, or at the checkout with --dev", (
        Flag("--version", True, False, "the release to deploy"),
        Flag("--dev", False, False, "point `current` at the git checkout, restoring live editing"),
        Flag("--releases", True, False, "the release area; overrides $FLEET_RELEASES"),
        Flag("--reason", True, False, "recorded in the history; REQUIRED with --force"),
        Flag("--force", False, False, "deploy a CANDIDATE anyway; requires --reason"),
    )),
    _verb("release-rollback", _do_release_rollback, False,
          "point `current` back, recording why", (
        Flag("--to", True, False, "the version to return to; defaults to the previously deployed one"),
        Flag("--reason", True, True, "why — the reason is the whole point of the history file"),
        Flag("--releases", True, False, "the release area; overrides $FLEET_RELEASES"),
    )),
    _verb("release-status", _do_release_status, True,
          "what is deployed right now, since when, by whom and why", (
        Flag("--releases", True, False, "the release area; overrides $FLEET_RELEASES"),
    )),
    _verb("release-list", _do_release_list, True, "every release, its state and its cut time", (
        Flag("--releases", True, False, "the release area; overrides $FLEET_RELEASES"),
    )),
    _verb("release-history", _do_release_history, True, "the deploy/rollback register", (
        Flag("--releases", True, False, "the release area; overrides $FLEET_RELEASES"),
        Flag("--limit", True, False, "show only the last N rows"),
    )),
```

- [ ] **Step 4: Run the CLI tests**

Run: `cd /home/ubuntu/davis_root/superpowers/fleet && PYTHONPATH=src python3 -m unittest tests.test_release.CliCase -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Run the whole hermetic suite — the verb count moved**

Run: `cd /home/ubuntu/davis_root/superpowers/fleet && PYTHONPATH=src python3 -m unittest discover -s tests -q`

Expected: OK. Several tests derive their population from `cli.VERBS` and will now cover 8 more verbs. If `test_cli` or `test_contracts` asserts a hardcoded verb *count*, update the number — but read the assertion first: if it derives the count from `VERBS`, changing anything is wrong.

- [ ] **Step 6: Prove the self-deployed refusal is not vacuous**

Make `_refuse_if_self_deployed` return unconditionally, then run:

```bash
cd /home/ubuntu/davis_root/superpowers/fleet && PYTHONPATH=src python3 - <<'PY'
# A mutating verb whose package resolves inside the releases root must refuse.
import io, os, pathlib, shutil, sys, tempfile
tmp = pathlib.Path(tempfile.mkdtemp())
shutil.copytree("src/fleet", tmp / "releases" / "fleet-v0.1.0" / "fleet" / "src" / "fleet")
sys.path.insert(0, str(tmp / "releases" / "fleet-v0.1.0" / "fleet" / "src"))
from fleet.cli import main
err = io.StringIO()
code = main(["release-promote", "--version", "0.1.0", "--releases", str(tmp / "releases"),
             "--home", str(tmp)], stdout=io.StringIO(), stderr=err)
print("exit", code, "|", err.getvalue()[:120])
assert code == 4, f"expected refusal, got {code}"
PY
```

Expected with the guard removed: assertion error (not exit 4). Restore the guard and confirm exit 4.

- [ ] **Step 7: Commit**

```bash
git add fleet/src/fleet/cli.py fleet/tests/test_release.py
git commit -m "release: eight flat verbs, and the two refusals that keep the pipeline recoverable"
```

---

### Task 5: `it_assert_isolation` classifies instead of comparing

**Files:**
- Modify: `fleet/it/lib.sh:278-282`
- Create: `scripts/tests/it-lib-isolation.sh`

**Interfaces:** none — this is a harness change with no Python surface.

**The change, and the precedent it follows.** `lib.sh` already contains this exact pattern for the *other* baseline. `it_assert_no_new_claude` (lines 181–199) classifies rather than compares, citing `SI-25`: *"do not make the check cleverer about WHETHER a change is acceptable — make it attribute mechanically and report what it could not attribute."* The tmux half never received it. This task applies the file's own established argument to the baseline that was left behind.

**The asymmetry is deliberate and inverted from the claude check.** For `claude` pids the dangerous direction is an ADDITION (a section spawned a process it must not have). For tmux sessions the dangerous direction is a REMOVAL (the product killed live work). So:

| Observation | Treatment | Why |
|---|---|---|
| A session appeared matching `$TMUX_PREFIX` or `itfleet-*` | **hard FAIL** | The harness leaked onto the server it must never touch. |
| A session appeared, any other name | note | The operator started something. This is the observed false RED (`claude_mor_design_chinmay`). |
| A `dt-` session disappeared | **hard FAIL** | Live work vanished during our run and we cannot prove it was not us. |
| Any other session disappeared | note | The operator closed a shell; the product only ever kills `dt-` names. |

- [ ] **Step 1: Write the failing harness test**

Create `scripts/tests/it-lib-isolation.sh`:

```bash
#!/usr/bin/env bash
# `it_assert_isolation`'s session-delta classification, with a negative control.
#
# This function is what every other section's verdict rests on, so loosening it is exactly the change that
# could quietly stop protecting anything. The control is the first case below: if a leaked IT-prefixed
# session stops failing, the whole change is unfalsifiable and the rest of this file proves nothing.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fails=0
note() { printf '  %s\n' "$*"; }
check() { if [ "$2" = "$3" ]; then note "ok   $1"; else note "FAIL $1 — wanted [$2] got [$3]"; fails=1; fi; }

# Drive the classifier directly with a baseline and an "after" set, so no real tmux server is needed and
# the case cannot be perturbed by whatever is running on this box.
classify() {   # classify <baseline-lines> <after-lines> -> prints "verdict|detail"
  BASELINE="$1" AFTER="$2" TMUX_PREFIX="itfleet-B" bash -c '
    . "'"$REPO"'/fleet/it/lib.sh" 2>/dev/null || true
    it_classify_session_delta "$BASELINE" "$AFTER"
  '
}

# --- THE NEGATIVE CONTROL: a leaked harness session must still be a hard failure ---------------------
out="$(classify $'dt-live\nzsh' $'dt-live\nitfleet-B-worker\nzsh')"
check "an IT-prefixed session appearing is a LEAK" "FAIL" "${out%%|*}"
case "$out" in *itfleet-B-worker*) note "ok   the leak names the session" ;;
               *) note "FAIL the leak does not name the session: $out"; fails=1 ;; esac

# --- the observed false RED: another operator's session appearing is a note --------------------------
out="$(classify $'dt-live\nzsh' $'claude_mor_design_chinmay\ndt-live\nzsh')"
check "a foreign session appearing is a NOTE" "NOTE" "${out%%|*}"

# --- a dt- session disappearing is still a hard failure ----------------------------------------------
out="$(classify $'dt-live\nzsh' $'zsh')"
check "a dt- session disappearing is a FAIL" "FAIL" "${out%%|*}"

# --- a non-dt session disappearing is a note ---------------------------------------------------------
out="$(classify $'dt-live\nzsh' $'dt-live')"
check "a non-dt session disappearing is a NOTE" "NOTE" "${out%%|*}"

# --- no change at all is a clean pass ----------------------------------------------------------------
out="$(classify $'dt-live\nzsh' $'dt-live\nzsh')"
check "an unchanged set is OK" "OK" "${out%%|*}"

# --- a leak AND foreign activity together: the leak wins ---------------------------------------------
out="$(classify $'zsh' $'claude_other\nitfleet-B-x\nzsh')"
check "a leak alongside foreign activity still FAILs" "FAIL" "${out%%|*}"

if [ "$fails" = 0 ]; then
  echo "PASS: it_classify_session_delta fails on a harness leak and on a vanished dt- session, and reports foreign churn as a note"
  exit 0
fi
echo FAIL
exit 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `bash /home/ubuntu/davis_root/superpowers/scripts/tests/it-lib-isolation.sh`
Expected: FAIL — `it_classify_session_delta: command not found`, every check reporting an empty verdict.

- [ ] **Step 3: Add the classifier and use it**

In `fleet/it/lib.sh`, add above `it_assert_isolation`:

```bash
# Classify a live-session delta instead of comparing it for equality. Prints "<verdict>|<detail>", where
# verdict is OK, NOTE or FAIL.
#
# `it_assert_no_new_claude` already does exactly this for the OTHER baseline, and says why (`SI-25`): do
# not make the check cleverer about WHETHER a change is acceptable — attribute it mechanically and report
# what cannot be attributed. The tmux half never got that treatment, so a coordinator of the operator's
# finishing normally produced the same signal as this harness killing live work. Measured: §B's `B3`, a
# case that dispatches nothing and whose own checks report "§B launches no process at all", failed on
# `claude_mor_design_chinmay` appearing mid-run.
#
# The asymmetry is INVERTED from the claude check, and deliberately. There, an ADDITION is the violation
# (a section spawned a process). Here, a REMOVAL is (the product killed live work), while an addition can
# only be ours if it carries our own prefix.
it_classify_session_delta() {   # it_classify_session_delta <baseline> <after>
  local baseline="$1" after="$2" appeared vanished leaked killed
  appeared="$(comm -13 <(printf '%s\n' "$baseline" | sort) <(printf '%s\n' "$after" | sort) | grep -v '^$')"
  vanished="$(comm -23 <(printf '%s\n' "$baseline" | sort) <(printf '%s\n' "$after" | sort) | grep -v '^$')"

  leaked="$(printf '%s\n' "$appeared" | grep -E "^(${TMUX_PREFIX:-itfleet-}|itfleet-)" | tr '\n' ' ')"
  killed="$(printf '%s\n' "$vanished" | grep -E '^dt-' | tr '\n' ' ')"

  if [ -n "${leaked// /}" ]; then
    printf 'FAIL|a session THIS HARNESS could have created appeared on the LIVE server: %s. The harness works on socket %s and must never reach the default one.\n' \
      "$leaked" "${IT_TMUX_SOCKET:-?}"
    return 0
  fi
  if [ -n "${killed// /}" ]; then
    printf 'FAIL|a dt- session DISAPPEARED from the live server during this section: %s. Live work vanishing mid-run cannot be attributed to anyone else, so it is charged here.\n' \
      "$killed"
    return 0
  fi
  if [ -n "${appeared// /}" ] || [ -n "${vanished// /}" ]; then
    printf 'NOTE|operator activity, not this section: appeared=[%s] vanished=[%s]. Neither carries a harness prefix and no dt- session was lost, so this is the box being used while the suite ran.\n' \
      "$(printf '%s' "$appeared" | tr '\n' ' ')" "$(printf '%s' "$vanished" | tr '\n' ' ')"
    return 0
  fi
  printf 'OK|live tmux session set byte-identical\n'
}
```

Replace `lib.sh:278-282` (the `if [ "$sessions" != ... ]` block) with:

```bash
  local classified verdict detail
  classified="$(it_classify_session_delta "$(cat "$LIVE_TMUX_SNAPSHOT")" "$sessions")"
  verdict="${classified%%|*}"; detail="${classified#*|}"
  if [ "$verdict" = FAIL ]; then
    it_fail "ISOLATION-$tag" "fleet/it/live-tmux-sessions.txt" "${stores_note}${detail}"
    return 1
  fi
  if [ "$verdict" = NOTE ]; then
    # Recorded on the PASS row rather than swallowed: the run stays attributable, and `verify` reads this
    # to decide between RED and INCONCLUSIVE.
    it_pass "ISOLATION-$tag" "fleet/it/live-tmux-sessions.txt" "${stores_note}${detail}"
    return 0
  fi
```

- [ ] **Step 4: Run the harness test to verify it passes**

Run: `bash /home/ubuntu/davis_root/superpowers/scripts/tests/it-lib-isolation.sh`
Expected: `PASS: it_classify_session_delta fails on a harness leak and on a vanished dt- session…`

- [ ] **Step 5: Prove the negative control works**

Change the leak branch to `if false; then`. Re-run: the first two checks must FAIL. Restore and confirm PASS. **If the control does not fail here, stop — the rest of this task proves nothing.**

- [ ] **Step 6: Confirm a real section now survives operator churn**

Run: `cd /home/ubuntu/davis_root/superpowers && IT_RESULTS=/tmp/claude-1000/*/scratchpad/b3.tsv bash fleet/it/run-B.sh B3`
Expected: `B3 PASS`, and `ISOLATION-B-enter` / `ISOLATION-B-leave` now PASS with an operator-activity note rather than FAIL — assuming another operator's session appears, which is the normal state of this box. If nothing changed on the box during the run, the rows read `live tmux session set byte-identical`, which is also correct.

- [ ] **Step 7: Commit**

```bash
git add fleet/it/lib.sh scripts/tests/it-lib-isolation.sh
git commit -m "IT: classify the live-session delta instead of comparing it"
```

---

### Task 6: `run-all.sh` gets two rosters and a truthful header

**Files:**
- Modify: `fleet/it/run-all.sh`

**Interfaces:**
- Produces: `run-all.sh [--full]`. Task 3's `Verify.run` already passes `--full`.

**Context:** the header says *"ONE validation run: every runner, sequentially"* while `RUNNERS` holds 11 of the 19 on disk. Seven of the eight absentees have no prerequisites at all — they are later work that was run standalone and never added. §P is the one genuine exclusion: it needs a real `claude` and its header states *"Budget: one real claude, one task, polled to completion."*

- [ ] **Step 1: Rewrite the header's first sentence and add the second roster**

Replace the first two lines of `run-all.sh` with:

```bash
#!/usr/bin/env bash
# ONE validation run over a DECLARED roster, sequentially, each runner into its own results file, then
# merged by this script as the single writer.
#
# TWO rosters, because "every runner" was a claim this file did not keep: it ran 11 of the 19 on disk, and
# F, G, H, I, J, O, P and LB were absent with no comment saying why. They are later work — their headers
# say `COMPLETE: F1-F11`, `COMPLETE: J1-J9`, `Not in Plan 6` — each run standalone and never added here.
#
#   (default)  the GATE roster: everything that is safe and quick enough to run for every release.
#   --full     every runner, EXCEPT §P unless FLEET_IT_ALLOW_CLAUDE=1.
#
# §P is excluded from `--full` by default for BUDGET, not capability: it dispatches a real `claude` and
# spends the account's weekly allowance. A release gate that silently consumes that is a gate that gets
# switched off.
```

- [ ] **Step 2: Add roster selection**

After the existing `RUNNERS=( … )` array, add:

```bash
# The sections added after this orchestrator was written. No prerequisites — checked per runner: each
# carries the same plain `Run: bash fleet/it/run-X.sh` line as the eleven above.
FULL_EXTRA=(
  "F:bash $IT_ROOT/run-F.sh"
  "G:bash $IT_ROOT/run-G.sh"
  "H:bash $IT_ROOT/run-H.sh"
  "I:bash $IT_ROOT/run-I.sh"
  "J:bash $IT_ROOT/run-J.sh"
  "O:bash $IT_ROOT/run-O.sh"
  "LB:bash $IT_ROOT/run-lineage.sh"
)

IT_FULL=no
for arg in "$@"; do
  case "$arg" in
    --full) IT_FULL=yes ;;
    *) echo "run-all.sh: unknown argument '$arg' (only --full is declared)" >&2; exit 2 ;;
  esac
done

if [ "$IT_FULL" = yes ]; then
  RUNNERS+=("${FULL_EXTRA[@]}")
  if [ "${FLEET_IT_ALLOW_CLAUDE:-0}" = 1 ]; then
    RUNNERS+=("P:bash $IT_ROOT/run-P.sh")
  else
    say "§P SKIPPED: it dispatches a real claude and spends the weekly allowance. Set FLEET_IT_ALLOW_CLAUDE=1 to include it."
  fi
fi
say "roster: $IT_FULL full; ${#RUNNERS[@]} runner(s)"
```

Note: `say()` is defined above `RUNNERS` in the current file — verify the ordering when editing, and move this block below `say`'s definition if needed.

- [ ] **Step 3: Verify the roster selection without running the suites**

```bash
cd /home/ubuntu/davis_root/superpowers
bash -n fleet/it/run-all.sh && echo "syntax OK"
bash -c 'set -e; grep -c "^  \"" fleet/it/run-all.sh'   # runner entries present
bash fleet/it/run-all.sh --nope 2>&1 | head -2          # must exit 2 naming the argument
```
Expected: syntax OK; the bad argument is refused with exit 2.

- [ ] **Step 4: Run the gate roster end to end**

Run: `cd /home/ubuntu/davis_root/superpowers && bash fleet/it/run-all.sh 2>&1 | tail -25`

Expected: the 11 gate runners execute and `RESULTS-closeout-all.tsv` is written. **This takes a long time.** Record the wall-clock in the commit message — Task 9 and every future operator need to know what a gate run costs.

- [ ] **Step 5: Commit**

```bash
git add fleet/it/run-all.sh
git commit -m "IT: two rosters, and a header that describes the one it runs"
```

---

### Task 7: `fleet-view releases`

**Files:**
- Modify: `bin/fleet-view`
- Modify: `scripts/tests/fleet-view.sh`

**Interfaces:**
- Consumes: `fleet release-history --porcelain`, `fleet release-list --porcelain`, `fleet release-status --porcelain`.
- Produces: `fleet-view releases`.

**Constraint:** `fleet-view` computes nothing — it reads porcelain and lays it out. Its existing test asserts that it never disagrees with the product and never mutates anything. Render the history in **list** form, not a table, so a long `reason` is never truncated.

- [ ] **Step 1: Add a failing assertion to `scripts/tests/fleet-view.sh`**

Append before the final `if [ "$fails" = 0 ]`:

```bash
# --- the releases view renders, and never truncates a reason -----------------------------------------
RELDIR="$TMP/releases"
mkdir -p "$RELDIR/fleet-v0.1.0/.release"
printf 'version\t0.1.0\ncut_at\t2026-08-02T10:00:00Z\n' > "$RELDIR/fleet-v0.1.0/.release/MANIFEST.tsv"
printf 'RELEASED\n' > "$RELDIR/fleet-v0.1.0/.release/STATE"
LONG="harvest wedged on a leased slot and the coordinator could not clear it without a manual reap, so we went back"
printf 'ts\taction\tversion\tfrom_version\tactor\thost\treason\tevidence\n' > "$RELDIR/RELEASE-HISTORY.tsv"
printf '2026-08-02T11:00:00Z\tROLLBACK\t0.1.0\t0.2.0\tdavis@onehouse.ai\tbox\t%s\t-\n' "$LONG" \
  >> "$RELDIR/RELEASE-HISTORY.tsv"

rv="$(FLEET_RELEASES="$RELDIR" FLEET_VIEW_WIDTH=100 NO_COLOR=1 python3 "$VIEW" releases 2>&1)"; rc=$?
check "the releases view renders" "0" "$rc"
printf '%s' "$rv" | grep -q "0.1.0" || { note "FAIL the releases view omits the release"; fails=1; }
printf '%s' "$rv" | grep -q "manual reap" \
  || { note "FAIL a long reason was truncated — list form exists so it is not"; fails=1; }
```

- [ ] **Step 2: Run to verify it fails**

Run: `bash /home/ubuntu/davis_root/superpowers/scripts/tests/fleet-view.sh`
Expected: FAIL — `releases` is not a known view.

- [ ] **Step 3: Add the view to `bin/fleet-view`**

Add a `releases` branch that shells the three read-only verbs with `--porcelain` and renders with the existing `blocks()` helper (the one already used for subjects and roadmap, which wraps rather than truncates):

```python
def releases_view(width):
    """Reads porcelain, lays it out. Computes nothing — the same contract as every other view here.

    List form, not a table: `reason` is operator free text and a column would cut exactly the sentence
    somebody wrote down so it would not be lost.
    """
    status = _porcelain("release-status")
    listing = _porcelain("release-list")
    history = _porcelain("release-history", "--limit", "10")

    out = [_heading("DEPLOYED", width)]
    out.extend(f"  {row[0]:<10} {row[1]}" for row in status if len(row) >= 2)

    out.append("")
    out.append(_heading("RELEASES", width))
    out.extend(f"  {' '.join(row)}" for row in listing[1:])

    out.append("")
    out.append(_heading("HISTORY (most recent last)", width))
    columns = history[0] if history else []
    for row in history[1:]:
        record = dict(zip(columns, row))
        out.append(f"  {record.get('ts', '?')}  {record.get('action', '?')}  "
                   f"{record.get('from_version', '?')} -> {record.get('version', '?')}")
        out.extend(blocks_wrap(f"reason: {record.get('reason', '-')}", width - 4, indent="    "))
        out.append("")
    return "\n".join(out)
```

Wire `releases` into the view dispatch beside `board` and `leases`. Reuse the file's existing `_heading`, `_porcelain` and wrapping helpers rather than adding new ones — read the file first and match the names it actually uses; the names above are placeholders for whatever `fleet-view` already calls them.

- [ ] **Step 4: Run the view test**

Run: `bash /home/ubuntu/davis_root/superpowers/scripts/tests/fleet-view.sh`
Expected: PASS, including the existing assertions that colour does not change layout and that rendering writes nothing.

- [ ] **Step 5: Commit**

```bash
git add bin/fleet-view scripts/tests/fleet-view.sh
git commit -m "fleet-view: a releases view, in list form so a reason is never cut"
```

---

### Task 8: §Q — the lifecycle end to end

**Files:**
- Create: `fleet/it/run-Q.sh`
- Modify: `fleet/it/run-all.sh` (add `"Q:bash $IT_ROOT/run-Q.sh"` to `RUNNERS`, the gate roster)

**Interfaces:** none exported. Emits cases `Q1`–`Q6`.

**Constraint:** obey the isolation contract like every other section — `it_section Q` on entry, `it_assert_isolation Q-leave` on exit. Everything happens in a throwaway git repo and a throwaway releases root under the section's own evidence directory; the real `$FLEET_RELEASES` is never touched.

- [ ] **Step 1: Write `fleet/it/run-Q.sh`**

```bash
#!/usr/bin/env bash
# §Q — the release lifecycle, end to end, through the CLI only.
#
# Every other release assertion is hermetic and drives the modules directly. This one runs the verbs an
# operator types, against a real git repository and a real symlink, because the properties that matter
# here are the ones no unit test can reach: that the tag really lands, that `current` really moves, and
# that a rollback really returns the bytes on disk to the previous release.
#
# Its repo and its releases root are BOTH throwaway, inside this section's evidence tree. The real
# $FLEET_RELEASES is never named, so a bug here cannot move what is deployed on this box.
#
# Run: bash fleet/it/run-Q.sh
set -uo pipefail
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
it_own_cases 'Q[0-9]+[a-z]?|ISOLATION-Q-(enter|leave)'
it_section Q

OUT="$EV/out"; mkdir -p "$OUT"
REPO="$EV/repo"; RELEASES="$EV/releases"
mkdir -p "$REPO" "$RELEASES"
FLEET_BIN="$(cd "$IT_ROOT/../.." && pwd)/bin/fleet"

git -C "$REPO" init -q -b live
git -C "$REPO" config user.email "it@example.com"
git -C "$REPO" config user.name "IT"
git -C "$REPO" config commit.gpgsign false
mkdir -p "$REPO/fleet/src/fleet" "$REPO/bin"
printf '__version__ = "0.0.0"\n' > "$REPO/fleet/src/fleet/__init__.py"
printf '#!/bin/sh\necho stub\n' > "$REPO/bin/fleet"
chmod +x "$REPO/bin/fleet"
git -C "$REPO" add -A && git -C "$REPO" commit -q -m "initial import"

rel() { FLEET_RELEASES="$RELEASES" FLEET_HOME="$EV/home" "$FLEET_BIN" "$@"; }

# Q1 — GIVEN a clean throwaway repo, WHEN `release-cut` runs, THEN an immutable export, an annotated tag
#      and a CANDIDATE state all exist, and the export carries only committed content.
rel release-cut --version 0.1.0 --repo "$REPO" > "$OUT/Q1-cut.out" 2>&1; q1=$?
if [ "$q1" = 0 ] && [ -d "$RELEASES/fleet-v0.1.0" ] \
   && git -C "$REPO" tag -l 'fleet/v0.1.0' | grep -q . \
   && [ "$(cat "$RELEASES/fleet-v0.1.0/.release/STATE")" = CANDIDATE ]; then
  it_pass Q1 "fleet/it/Q/out/Q1-cut.out" \
    "cut 0.1.0: export present, annotated tag fleet/v0.1.0 created, STATE=CANDIDATE"
else
  it_fail Q1 "fleet/it/Q/out/Q1-cut.out" "cut failed (exit $q1) or left an incomplete release"
fi

# Q2 — GIVEN a dirty tree, WHEN `release-cut` runs, THEN it is REFUSED (exit 4) and nothing is created.
printf 'uncommitted\n' > "$REPO/dirty.txt"
before_dirs="$(ls "$RELEASES" | sort | tr '\n' ' ')"
rel release-cut --version 0.2.0 --repo "$REPO" > "$OUT/Q2-dirty.out" 2>&1; q2=$?
after_dirs="$(ls "$RELEASES" | sort | tr '\n' ' ')"
if [ "$q2" = 4 ] && [ "$before_dirs" = "$after_dirs" ]; then
  it_pass Q2 "fleet/it/Q/out/Q2-dirty.out" \
    "a dirty tree refused the cut with exit 4 and created nothing (releases unchanged: $after_dirs)"
else
  it_fail Q2 "fleet/it/Q/out/Q2-dirty.out" "want exit 4 and no new release; got exit $q2, dirs '$after_dirs'"
fi
rm -f "$REPO/dirty.txt"

# Q3 — GIVEN a CANDIDATE with no evidence, WHEN `release-deploy` runs without --force, THEN it REFUSES.
rel release-deploy --version 0.1.0 > "$OUT/Q3-deploy.out" 2>&1; q3=$?
if [ "$q3" = 4 ] && [ ! -e "$RELEASES/current" ]; then
  it_pass Q3 "fleet/it/Q/out/Q3-deploy.out" \
    "deploying a CANDIDATE was refused with exit 4 and `current` was never created"
else
  it_fail Q3 "fleet/it/Q/out/Q3-deploy.out" "want exit 4 and no current; got exit $q3"
fi

# Q4 — GIVEN a forced deploy WITH a reason, WHEN it runs, THEN `current` resolves to the release and the
#      history records a DEPLOY row carrying that reason.
rel release-deploy --version 0.1.0 --force --reason "IT forced deploy" > "$OUT/Q4.out" 2>&1; q4=$?
target="$(readlink "$RELEASES/current" 2>/dev/null)"
if [ "$q4" = 0 ] && [ "$(basename "${target:-}")" = "fleet-v0.1.0" ] \
   && grep -q 'DEPLOY' "$RELEASES/RELEASE-HISTORY.tsv" \
   && grep -q 'IT forced deploy' "$RELEASES/RELEASE-HISTORY.tsv"; then
  it_pass Q4 "fleet/it/Q/out/Q4.out" \
    "current -> fleet-v0.1.0 and the register carries a DEPLOY row with the stated reason"
else
  it_fail Q4 "fleet/it/Q/out/Q4.out" "want current -> fleet-v0.1.0 and a DEPLOY row; got exit $q4, target '$target'"
fi

# Q5 — GIVEN a second release deployed over the first, WHEN `release-rollback` runs with no --to, THEN it
#      returns to the PREVIOUSLY deployed version, read from the register rather than guessed.
git -C "$REPO" commit -q --allow-empty -m "second change"
rel release-cut --version 0.1.1 --repo "$REPO" > "$OUT/Q5-cut.out" 2>&1
rel release-deploy --version 0.1.1 --force --reason "second" > "$OUT/Q5-deploy.out" 2>&1
rel release-rollback --reason "IT rollback" > "$OUT/Q5-rollback.out" 2>&1; q5=$?
target="$(readlink "$RELEASES/current" 2>/dev/null)"
if [ "$q5" = 0 ] && [ "$(basename "${target:-}")" = "fleet-v0.1.0" ] \
   && tail -1 "$RELEASES/RELEASE-HISTORY.tsv" | grep -q 'ROLLBACK'; then
  it_pass Q5 "fleet/it/Q/out/Q5-rollback.out" \
    "rollback with no --to returned to 0.1.0, the version the register named as previous, and recorded a ROLLBACK row"
else
  it_fail Q5 "fleet/it/Q/out/Q5-rollback.out" "want current -> fleet-v0.1.0; got exit $q5, target '$target'"
fi

# Q6 — GIVEN a release cut after 0.1.0, WHEN its changelog is read, THEN it lists the delta commit and the
#      first release's changelog lists none. A release that cannot say what changed is not a release.
if grep -q 'second change' "$RELEASES/fleet-v0.1.1/.release/CHANGELOG.md" 2>/dev/null \
   && ! grep -q '^- ' "$RELEASES/fleet-v0.1.0/.release/CHANGELOG.md" 2>/dev/null; then
  it_pass Q6 "fleet/it/Q/out/Q5-cut.out" \
    "0.1.1's changelog names the commit added since 0.1.0, and 0.1.0's lists no commits because it has no predecessor"
else
  it_fail Q6 "fleet/it/Q/out/Q5-cut.out" "the changelogs do not describe the delta as expected"
fi

it_cleanup_tmux
it_assert_isolation Q-leave
exit "$IT_FAILED"
```

- [ ] **Step 2: Make it executable and syntax-check**

```bash
cd /home/ubuntu/davis_root/superpowers
chmod +x fleet/it/run-Q.sh
bash -n fleet/it/run-Q.sh && echo "syntax OK"
```

- [ ] **Step 3: Run §Q**

Run: `cd /home/ubuntu/davis_root/superpowers && IT_RESULTS=/tmp/q.tsv bash fleet/it/run-Q.sh`
Expected: `Q1`–`Q6` all PASS, `ISOLATION-Q-leave` PASS.

Note: `.release/CHANGELOG.md` must be written by `release-cut` into the export for Q6 to pass. If Q6 fails, that is a real gap in Task 4's `_do_release_cut` — the section writes the changelog into the repo and tags with it, but must also copy the section into `<export>/.release/CHANGELOG.md` after the export. Add that line rather than weakening Q6.

- [ ] **Step 4: Add §Q to the gate roster**

In `fleet/it/run-all.sh`, add `"Q:bash $IT_ROOT/run-Q.sh"` to `RUNNERS` after `"D:…"`. It is fast and has no external dependencies, so it belongs in the gate roster rather than in `--full`.

- [ ] **Step 5: Commit**

```bash
git add fleet/it/run-Q.sh fleet/it/run-all.sh
git commit -m "IT §Q: cut, refuse, deploy, roll back — through the CLI, against a real repo"
```

---

### Task 9: Bootstrap — point the box at `current`

**Files:**
- Modify: `bin/fleet`
- Modify: `scripts/fleet-env.sh`
- Modify: `/home/ubuntu/davis_root/.claude/settings.json` (**not** in the repo)
- Read: `/home/ubuntu/davis_root/.superpowers-sync/sync.sh`, `bootstrap.sh`

**Ordering matters.** `current` points at the git checkout FIRST, so repointing the consumers changes nothing observable. Only then is a real release cut. Every step is reversible by pointing `current` back.

- [ ] **Step 1: `bin/fleet` resolves its repo physically**

Change:

```bash
_fleet_repo="$(cd "$(dirname "$_fleet_self")/.." && pwd)"
```

to:

```bash
# `-P` and not plain `pwd`: with `current` on the path, a logical pwd yields `…/current`, which is
# re-resolved on every file open — so a symlink flip mid-invocation could hand ONE python process modules
# from two different releases. Resolving once pins each invocation to one physical release for its life.
_fleet_repo="$(cd -P "$(dirname "$_fleet_self")/.." && pwd)"
```

Verify: `fleet board --porcelain | head -2` still works, and `fleet --help` prints usage.

- [ ] **Step 2: Create the release area pointing at the checkout**

```bash
mkdir -p /home/ubuntu/davis_root/fleet-releases
cd /home/ubuntu/davis_root/fleet-releases
ln -s /home/ubuntu/davis_root/superpowers current.tmp && mv -T current.tmp current
ls -l current      # must resolve to the checkout
```

- [ ] **Step 3: `fleet-env.sh` defaults `FLEET_RELEASES` and puts `current/bin` on PATH**

Add after the `FLEET_TMUX_SOCKET` block:

```bash
# The release area. `current` is a symlink to the deployed export, or to this checkout in dev mode.
export FLEET_RELEASES="${FLEET_RELEASES:-/home/ubuntu/davis_root/fleet-releases}"
```

Replace the PATH block with:

```bash
# Through `current`, never the checkout directly: that pointer IS the deployment, and a shell that
# bypassed it would run a different version from every other shell on the box. Falls back to the checkout
# when no release area exists yet, so a fresh clone still has a working `fleet`.
_fleet_bin="$FLEET_RELEASES/current/bin"
[ -d "$_fleet_bin" ] || _fleet_bin="/home/ubuntu/davis_root/superpowers/bin"
case ":$PATH:" in
  *":$_fleet_bin:"*) ;;
  *) export PATH="$_fleet_bin:$PATH" ;;
esac
unset _fleet_bin
```

Verify in a fresh shell: `. /home/ubuntu/davis_root/superpowers/scripts/fleet-env.sh && command -v fleet && fleet release-status`

- [ ] **Step 4: Repoint the plugin marketplace**

Edit `/home/ubuntu/davis_root/.claude/settings.json`, changing `extraKnownMarketplaces.superpowers-dev.source.path` from `/home/ubuntu/davis_root/superpowers` to `/home/ubuntu/davis_root/fleet-releases/current`.

Verify by opening a **fresh** Claude session and confirming the skills still load — the plugin cache is a copy, so this only takes effect in a new session. If they do not, revert the one line; nothing else depends on it.

- [ ] **Step 5: Confirm the sync cron audit (already performed — verify, don't repeat)**

**Audited 2026-08-02; conclusion: no change needed.** Recorded here so it is not re-investigated:

- Nothing in `sync.sh`, `lib.sh`, `apply.sh`, `finish.sh` or `bootstrap.sh` writes `settings.json` or
  `extraKnownMarketplaces`. Step 4's edit will **not** be reverted overnight.
- The refresh is `SPSYNC_REFRESH_CMD` in `.superpowers-sync/config`, and it is
  `claude plugin marketplace update superpowers-dev` followed by uninstall/install. It re-reads whatever
  path `settings.json` declares, so after Step 4 it pulls from `current` on its own.
- `config:4` exports `CLAUDE_CONFIG_DIR=/home/ubuntu/davis_root/.claude`, so the 03:30 refresh targets the
  right config dir despite the cron line not setting it.

**One thing genuinely unverified, and it is the reason this step still exists.** `claude plugin marketplace
update` has never been pointed at a `directory` source that is a **symlink**. If it resolves and caches the
physical target rather than following the link on each refresh, a later `release-deploy` would not reach
Claude sessions until the next refresh. Verify during Step 4:

```bash
readlink /home/ubuntu/davis_root/fleet-releases/current
CLAUDE_CONFIG_DIR=/home/ubuntu/davis_root/.claude claude plugin marketplace update superpowers-dev
grep -rn "path" /home/ubuntu/davis_root/.claude/plugins/known_marketplaces.json
```

If the recorded path is the resolved physical directory rather than `…/fleet-releases/current`, that is a
finding: record it in the effort's `ISSUES.md` and keep `settings.json` pointing at `current` anyway — the
next refresh still re-reads it, so the worst case is a one-cycle delay, not a broken deploy.

- [ ] **Step 6: Cut, verify, promote and deploy the first real release**

```bash
cd /home/ubuntu/davis_root/superpowers
git status --short                  # must be empty; cut refuses a dirty tree
fleet release-cut --version 0.1.0 --repo /home/ubuntu/davis_root/superpowers \
  --notes "first release of the fleet infra"
fleet release-verify --version 0.1.0
fleet release-promote --version 0.1.0
fleet release-deploy --version 0.1.0 --reason "first real release"
fleet release-status
```

Expected: `current 0.1.0`, `state RELEASED`, with the reason recorded. If `verify` returns INCONCLUSIVE, re-run it when the box is quieter — that is the mechanism working, not a failure.

- [ ] **Step 7: Prove rollback works before you need it**

```bash
fleet release-deploy --dev --reason "verifying rollback"
fleet release-status                      # current DEV, plus the checkout's HEAD and dirty flag
fleet release-rollback --to 0.1.0 --reason "rollback rehearsal"
fleet release-status                      # current 0.1.0
fleet release-history --limit 5
```

A rollback path first exercised during an incident is a rollback path nobody knows works.

- [ ] **Step 8: Commit**

```bash
cd /home/ubuntu/davis_root/superpowers
git add bin/fleet scripts/fleet-env.sh
git commit -m "bootstrap: every consumer follows current, and an invocation pins one physical release"
```

Note that `settings.json` and the `fleet-releases/` directory live outside the repo and are not committed; record their state in the effort's `HANDOFF.md`.

---

## Self-Review

**Spec coverage.** Every section of the spec maps to a task: layout, `bin/fleet` fix and module decomposition → Tasks 1–3, 9; the cut ordering and MANIFEST → Task 1–2, 4; `verify` and the verdicts → Task 3; `promote`'s tier rule → Task 4; `deploy`/`rollback`/`--dev` → Task 4; the history file → Task 1; refusals and exit codes → Task 4; concurrency and the lock → Task 1; the classification change → Task 5; the two rosters → Task 6; `fleet-view releases` → Task 7; hermetic and §Q testing → Tasks 1–4, 8; bootstrap → Task 9. Accepted limitations need no task by definition.

**Two spec corrections this plan makes, both of which need folding back into the spec document:**

1. **The verb surface is eight flat verbs, not `fleet release <subverb>`.** `parse()` refuses positionals (`FI-19d`) and `main()` has no sub-verb mechanism. Consequence: `--repo` must be a required flag, because §A5 and §M drive every registered verb through a real invocation and a cwd-inferring `release-cut` would tag the live repo during an IT run.
2. **The lock is `atomic.held_for_update` over `.releases-lock`,** not a new `.lock/` mechanism. Same `mkdir` primitive, already handles a dead holder, already tested.

**One judgment call a reviewer should scrutinise.** The classification table in Task 5 treats a **vanished `dt-` session as a hard FAIL**, which will still fire when one of your coordinators finishes normally mid-run. I chose strictness in that direction because it is the catastrophic one — the product killing live work — and because the observed false RED was an *appearance*, not a disappearance. If it proves noisy in practice, the next move is not to relax it but to record the dt- set at section entry and only fail on a session the section could plausibly have reached. That needs its own evidence before it is worth building.

**Ordering.** Tasks 1–3 are independent of 5–7 and could run in parallel by different agents; Task 4 depends on 1–3; Task 8 depends on 4; Task 9 depends on everything. Respect the standing limit of **two concurrent agents**, and `cli.py` takes **one agent at a time**.
