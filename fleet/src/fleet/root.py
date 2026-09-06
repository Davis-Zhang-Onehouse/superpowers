"""Which fleet am I in? — the root marker and the walk that finds it.

A fleet is a property of a DIRECTORY, not of an exported variable. `~/davis_root` and `~/davis2_root` each
carry a `.fleet-root` marker, and every path `fleet` uses derives from whichever marker is found by walking
up from the working directory. Two roots on one box then share nothing: not a record, not a slot, not a
tmux server, not a release area.

**The name is DECLARED in the marker, never derived from the directory.** It is what the tmux socket is
built from. `FI-421` is why: a fix written to remove a dead path constant shipped WITH a silent fallback,
because it slugified a directory into a name using `replace("/", "-")` while the harness also maps `_` to
`-`, so `davis_root` and `davis-root` silently diverged. The function written to remove a silent fallback
had one. A declared name has no derivation to get wrong, and it does not move when somebody renames a
directory.

**The marker is `.fleet-root`; the store is `.fleet/`.** Two names on purpose. An instant carries its own
`<instant>/.fleet/` (`roadmap.py`), so a walk keyed on `.fleet` would stop at the first instant it passed
through and call it a root.

**The walk stops BELOW `$HOME`.** A marker at `$HOME` would make every root the same root — silently. It
would look exactly like this feature working and behave exactly like it absent, which is the worse of the
two failures available, so it is never honoured. `refusal` names it directly when it exists, because a
deliberate non-effect that the diagnostic does not explain reads as a bug.

**`discover` distinguishes "no root" from "a broken root".** Absent returns `None`, so a caller can fall
through to another tier; unreadable RAISES. Collapsing those two would let a corrupt marker silently select
a different store, which is the shape of every finding in this package's register that begins *absence is
never success*.

This module is a leaf: it imports `fleet.errors` and nothing else from the package, and it makes no decision
about precedence. Which tier wins is `cli`'s business, and keeping that out of here is what lets the whole
resolution chain be tested as a pure function of (flags, env, cwd, disk).
"""
import json
import pathlib
from dataclasses import dataclass

from fleet.errors import BadInput

#: The file that says "a fleet lives here". Distinct from the `.fleet/` store — see the module docstring.
MARKER = ".fleet-root"

#: A root name becomes `fleet-<name>` as a tmux socket. `tmux -L` treats a name containing `/` as a PATH
#: rather than a name — a different thing that silently works — so the character set is bounded here rather
#: than discovered at the first `tmux` call.
_NAME_OK = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")


@dataclass(frozen=True)
class Root:
    """A resolved root: where it is, and what it calls itself."""

    path: pathlib.Path
    name: str

    @property
    def store(self) -> pathlib.Path:
        """`$FLEET_HOME`: records, pool and harvest."""
        return self.path / ".fleet"

    @property
    def releases(self) -> pathlib.Path:
        """`$FLEET_RELEASES`: the deployed export and its `current` pointer."""
        return self.path / "fleet-releases"

    @property
    def socket(self) -> str:
        """`$FLEET_TMUX_SOCKET`: the tmux SERVER this root's sessions live on.

        Per-root because `close`, `abort` and `harvest` kill sessions BY NAME, and session names are
        `dt-<subject>` chosen by a coordinator — so two roots on one server can collide and the loser is
        killed with no diagnostic.
        """
        return f"fleet-{self.name}"


def find(start, home):
    """The directory holding the marker at or above `start`, or `None`.

    Both operands are resolved before comparison: during migration `~/.fleet` and `~/davis_root/.fleet` are
    the same directory reached two ways, and comparing unresolved paths would manufacture a difference out
    of a symlink.
    """
    start = pathlib.Path(start).resolve()
    home = pathlib.Path(home).resolve()
    for candidate in (start, *start.parents):
        #: At `$HOME`, or on a branch of the filesystem that does not pass through it. Either way there is
        #: nothing above worth testing, and the walk stops rather than climbing to `/`.
        if candidate == home or home not in candidate.parents:
            return None
        if (candidate / MARKER).is_file():
            return candidate
    return None


def load(root_dir) -> Root:
    """Parse the marker in `root_dir`. Every failure names the file, because the reader's next act is to
    open it."""
    root_dir = pathlib.Path(root_dir)
    marker = root_dir / MARKER
    try:
        body = json.loads(marker.read_text())
    except (OSError, ValueError) as exc:
        raise BadInput(
            f"{marker} is not readable as JSON ({exc}). The marker is a JSON object naming this root, for "
            f'example: {{"name": "davis"}}') from None
    if not isinstance(body, dict) or not str(body.get("name") or "").strip():
        raise BadInput(
            f'{marker} declares no name. It must be a JSON object with a non-empty "name", for example: '
            f'{{"name": "davis"}}. The name is DECLARED rather than derived from the directory because it '
            f"becomes this root's tmux socket, and a socket name must not change when somebody renames a "
            f"directory (FI-421).")
    name = str(body["name"]).strip()
    bad = sorted(set(name) - _NAME_OK)
    if bad:
        raise BadInput(
            f"{marker} declares name {name!r}, which contains {bad}. The name becomes the tmux socket "
            f"`fleet-{name}`, and `tmux -L` reads a name containing `/` as a PATH — a different thing that "
            f"silently works. Use letters, digits, `_`, `-` or `.`.")
    return Root(path=root_dir.resolve(), name=name)


def discover(cwd, home):
    """The root for a working directory, or `None` when there is no marker at or above it.

    A marker that exists and cannot be parsed RAISES rather than returning `None` — see the module
    docstring on why those two are not the same answer.
    """
    found = find(cwd, home)
    return None if found is None else load(found)


def refusal(cwd, home, verb: str) -> str:
    """Why no root could be resolved, and what clears it."""
    cwd = pathlib.Path(cwd).resolve()
    home = pathlib.Path(home).resolve()
    parts = [
        f"{verb!r} could not tell which fleet it belongs to: there is no {MARKER} at or above {cwd} "
        f"(searched up to, and excluding, {home}).",
        f"Clears when: create {MARKER} in this fleet's root directory — "
        f"""`echo '{{"name": "davis"}}' > {home}/davis_root/{MARKER}` — or name the destination """
        f"explicitly with `--root <path>` or `--home <path>`, or by exporting FLEET_ROOT or FLEET_HOME.",
    ]
    if (home / MARKER).is_file():
        parts.append(
            f"NOTE: there IS a {home / MARKER}, and it is deliberately not honoured — a marker at your "
            f"home directory makes every root the same root, which looks exactly like isolation working "
            f"and behaves exactly like isolation absent. Put it at {home}/<root>/{MARKER} instead.")
    return " ".join(parts)
