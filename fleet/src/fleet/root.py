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
    return Root(path=root_dir.resolve(), name=check_name(str(body["name"]).strip(), marker))


def check_name(name: str, where) -> str:
    """The charset rule, shared by the reader and the creator.

    Extracted so `root-init` refuses a name BEFORE writing it rather than writing a marker that `load`
    will then reject — a root that exists on disk and cannot be loaded is the one state neither side has
    a remedy for.
    """
    name = str(name).strip()
    bad = sorted(set(name) - _NAME_OK)
    if bad:
        raise BadInput(
            f"{where} declares name {name!r}, which contains {bad}. The name becomes the tmux socket "
            f"`fleet-{name}`, and `tmux -L` reads a name containing `/` as a PATH — a different thing that "
            f"silently works. Use letters, digits, `_`, `-` or `.`.")
    return name


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


def check_new_root(path, home) -> pathlib.Path:
    """Every reason `path` cannot become a root, refused BEFORE anything is written. Returns it resolved.

    The rules are here rather than in the handler because they are the same rules `find` and `load` read
    the other way round, and a creator that does not share the finder's definition of a root will happily
    write a marker the finder can never honour. That is the failure this function exists to make
    impossible, so each refusal below names the `find` behaviour it mirrors.
    """
    path = pathlib.Path(path)
    home = pathlib.Path(home).resolve()
    if not path.is_dir():
        raise BadInput(
            f"{path} is not an existing directory. `root-init` MARKS a directory; it does not create one, "
            f"because a path that is not there is far more often a typo than an intention. `mkdir -p "
            f"{path}` first.")
    resolved = path.resolve()

    #: The `$HOME` rule, and it is a refusal rather than a warning because `find` stops AT `$HOME`: a
    #: marker written here is never read, so the verb would report success over a root that does not
    #: exist as far as every other verb is concerned.
    if resolved == home:
        raise BadInput(
            f"{resolved} is your home directory, and a marker there is never honoured — the walk that "
            f"finds a root stops at $HOME. A root there would make every root the same root, which looks "
            f"exactly like isolation working and behaves exactly like isolation absent. Put the root in a "
            f"subdirectory: {home}/<name>_root.")
    #: Resolved on BOTH sides before comparing, because a symlink under `$HOME` pointing outside it is the
    #: interesting case and comparing the unresolved paths would call it contained. `find` resolves for
    #: the same reason.
    if home not in resolved.parents:
        raise BadInput(
            f"{resolved} is not inside {home}. A root is found by walking UP from a working directory to "
            f"$HOME, so a marker outside $HOME is never reached and the root would be invisible to every "
            f"verb." + (f" ({path} resolves to {resolved}.)" if resolved != path.resolve(strict=False)
                        or str(path) != str(resolved) else ""))

    if (resolved / MARKER).is_file():
        try:
            existing = load(resolved).name
        except BadInput:
            existing = "an unreadable marker"
        raise BadInput(
            f"{resolved / MARKER} already exists and declares {existing!r}. This directory is already a "
            f"root. Edit the marker by hand to rename it — renaming is not this verb's job, because the "
            f"name IS the tmux socket and moving it strands every session already on the old one.")

    #: An ancestor that is already a root. Nested roots are not refused by anything else — `find` returns
    #: the NEAREST marker, so a `cd` deeper would silently pick the inner root while the slots, records
    #: and sessions of the work already running there belong to the outer one.
    above = find(resolved.parent, home) if resolved.parent != home else None
    if above is not None:
        raise BadInput(
            f"{resolved} is inside {above}, which is already a fleet root ({above / MARKER}). Roots do not "
            f"nest: the walk stops at the NEAREST marker, so work started from inside {resolved} would "
            f"use a different store, pool and tmux server than the same work started one directory up — "
            f"with nothing to say why. Put the new root beside {above}, not under it.")
    return resolved
