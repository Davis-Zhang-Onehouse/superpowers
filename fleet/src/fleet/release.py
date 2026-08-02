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

from fleet.atomic import atomic_write, held_for_update, tmp_name
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
        through it.

        The staging name comes from `atomic.tmp_name`, not from the pid. A pid-derived name is shared by
        every writer INSIDE one process, which is `FI-20`'s defect with a different receiver: two threads
        flipping at once both write one staging path, the first `os.replace` publishes the second's target
        and the second raises `FileNotFoundError` finding its staging gone. `tmp_name` is pid ∧
        monotonic_ns ∧ 48 random bits, so no two writers can produce it and no pre-clean is needed.

        This cannot go through `atomic_write`: that primitive publishes TEXT at a path, and what is being
        published here is a symlink. The `os.replace` is the same publish step for a different object.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        staging = self.root / tmp_name("current")
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
