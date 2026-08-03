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
import shutil
import socket
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fleet.atomic import atomic_symlink, atomic_write, held_for_update, tmp_name
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

#: How many releases the area keeps. Beyond this the OLDEST are removed at the next cut.
#:
#: A release is ~5 MB frozen and the cadence is a release per few fixes, so without a ceiling the area
#: grows without bound — one day of work took it to 77 MB. Nothing is lost that matters: the TAG is the
#: durable artifact and `release-cut` can rebuild any export from it; the directory is a convenience.
RELEASE_RETENTION = 10

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
    """A hash of the payload: sorted `mode path sha256`, one line per file.

    Two entries are excluded, and only at the ROOT: `META_DIR`, which describes the release rather than
    being part of it, and `.git`, which is repository metadata and never shipped content.

    Computed from the FILESYSTEM rather than from git, because `verify` recomputes it on a tree that may
    have no git object database at all. The executable bit is included: a launcher that lost `+x` is a
    broken artifact that hashes identically if you only hash content.

    `.git` is excluded for `II-7`. Verification runs the IT suite from `git worktree add <scratch> <tag>`
    rather than from the export, because several cases need a real working copy -- `M13` asks `selftest`
    to notice a dirty covered path, which is a `git status`, and an export has no `.git` by construction.
    This hash is what proves the worktree IS the artifact, and a worktree carries a `.git` FILE at its
    root pointing back at the parent repository. Without the exclusion the comparison could never
    succeed and the approach is unavailable. It is a no-op for an export: `git archive` writes no `.git`.

    The exclusion is the root entry named exactly `.git`, NOT any path containing "git". `.gitignore`,
    `.gitattributes` and `bin/git-helper` are shipped content and stay in the hash.
    """
    root = Path(root)
    lines = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] in (META_DIR, ".git"):
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
        """Flip the pointer atomically.

        Delegated to `atomic.atomic_symlink`, which is the package's ONE atomic publish for a symlink, for
        the same reason `atomic_write` is its one atomic publish for text. Doing it inline here would have
        been a second implementation of the primitive `FI-20` exists to keep singular — and it tripped
        `test_structure`'s ninth-copy guard, which was right to fire.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_symlink(target, self.current_link)

    # --- the register ------------------------------------------------------------------------------
    @property
    def history_path(self) -> Path:
        return self.root / "RELEASE-HISTORY.tsv"

    def prune(self, keep: int = RELEASE_RETENTION) -> list:
        """Remove the oldest releases beyond `keep`. Returns `[(version, why)]`, newest-removed first.

        Ordered by SEMVER, never by mtime: cutting `0.2.0` after `0.10.0` is legal, and a timestamp would
        then delete the newer of the two.

        The DEPLOYED release is never removed, however old — and it is precisely the one most likely to
        be old, because it stays deployed while newer versions are cut. `current` is what every
        `davis_root` shell resolves through, so deleting its target breaks the box. It is skipped and the
        NEXT-oldest goes instead, so the ceiling is still honoured.

        A cut ends in `chmod -R a-w`, and `rmtree` cannot delete a read-only tree, so owner-write is
        restored first. That is the same mistake `QI-7` left in the verification worktrees, one directory
        over; it is written out here rather than discovered again.
        """
        versions = self.versions()
        if len(versions) <= keep:
            return []
        deployed = None
        try:
            target = (self.root / "current").resolve()
            deployed = next((v for v in versions if self.dir_for(v).resolve() == target), None)
        except OSError:
            pass
        removed = []
        # Oldest first, stopping as soon as the count is within the ceiling.
        for version in list(versions):
            if len(versions) - len(removed) <= keep:
                break
            if version == deployed:
                continue                    # never the live one; the next-oldest goes instead
            root = self.dir_for(version)
            for path in sorted(root.rglob("*"), reverse=True) + [root]:
                if not path.is_symlink():
                    try:
                        path.chmod(path.stat().st_mode | 0o200)
                    except OSError:
                        pass
            shutil.rmtree(root, ignore_errors=True)
            removed.append((version, f"beyond the {keep}-release ceiling; the tag {version.tag} still "
                                     f"has it and `release-cut` can rebuild the export from that"))
        return removed

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
