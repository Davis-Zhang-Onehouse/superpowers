"""`B03`. An evidence item as a LOCATION — the ONE place an item is turned into a path.

A proposal's evidence used to be an opaque string at every stage: `propose` checked "non-empty", `apply` copied
the string onto the milestone, and `fleet roadmap` printed a count. So a typo'd path that never existed was
accepted and landed on the milestone with exit 0, and an absolute `-inflight-` path dangled one rename later —
while the SAME row's proposer path was re-resolved through that rename (`roadmap._proposer`). Nothing could check
an item, because nothing knew what an item meant.

What an item means, one rule per shape:

* a URL (`scheme://…`) is evidence nobody here can stat — 71 ClickUp links sit on real roadmaps — so it passes
  untouched and is never reported as dangling;
* a RELATIVE item means the PROPOSING instant's folder — the convention the skills teach and ~95% of real items
  follow — re-resolved through `identity.resolve`, so it survives the proposer's own `-inflight-` →
  `-complete-` rename. Never the cwd: a worker's cwd is its slot, a different directory;
* an ABSOLUTE item is itself if it exists, else every path component that is an instant name and no longer
  exists is re-resolved the same way, root first — the case of a coordinator citing a worker's file, or of a
  milestone path written while its instant was still `-inflight-`.

An instant MOVED to another parent folder is not a rename and does not resolve; it is reported as not
resolving rather than guessed at.
"""
import os
import re
from pathlib import Path

from fleet.errors import AmbiguousId, BadInput, InstantNameError
from fleet.identity import InstantName, resolve

_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")

#: Appended to an item `describe` could not locate. One spelling, so a reader can grep for it.
DOES_NOT_RESOLVE = "(does not resolve)"


#: RV-22. `file://` names a path on this box: it is judged as that path, so a typo spelled as one is refused.
_FILE_URL = "file://"


def is_url(item) -> bool:
    return bool(_URL.match(str(item))) and not str(item).startswith(_FILE_URL)


def _plain(item) -> str:
    """The item with a `file://` prefix stripped — the path it names."""
    item = str(item)
    return item[len(_FILE_URL):] if item.startswith(_FILE_URL) else item


def _folder(instant):
    """The instant's folder NOW, or None. Two folders sharing a stable key is not a location either: the
    resolver refuses to guess, and so does every caller here."""
    if instant is None:
        return None
    try:
        return resolve(Path(instant))
    except (AmbiguousId, OSError):
        #: RV-25. OSError: a directory this user cannot read is not a location either.
        return None


def _through_rename(path: Path):
    """`path`, walked from the root: each component that does not exist and is an instant name is
    re-resolved inside its (already resolved) parent. Every instant component, not only the deepest, so a
    nested instant whose OUTER folder completed first still resolves."""
    if path.exists():
        return path
    current = Path(path.parts[0])
    for part in path.parts[1:]:
        candidate = current / part
        if not candidate.exists():
            try:
                InstantName.parse(part)
            except InstantNameError:
                return None
            candidate = _folder(candidate)
            if candidate is None:
                return None
        current = candidate
    return current


def locate(item, anchor):
    """Where `item` is NOW, or None. `anchor` is the proposing instant (its recorded path; a stale
    `-inflight-` path is fine). A URL has no location here and returns None — ask `is_url` first."""
    if is_url(item):
        return None
    path = Path(_plain(item))
    if not path.is_absolute():
        folder = _folder(anchor)
        if folder is None:
            return None
        path = folder / path
    #: Normalised first, so `a/../a/x` and `a/x` are one location and no `..` (with the proposer's folder name in
    #: front of it) survives into an anchored item; then walked, so a RELATIVE item's own instant components
    #: follow a rename exactly as an absolute item's do.
    try:
        return _through_rename(Path(os.path.normpath(path)))
    except OSError:
        #: RV-25. An unreadable directory on the way reads as "does not resolve", never a traceback out of
        #: `fleet roadmap` or out of a refusal that names the item.
        return None


def dangling(items, anchor) -> list:
    """The items that are neither a URL nor anywhere on disk."""
    return [str(e) for e in items if not is_url(e) and locate(e, anchor) is None]


def _inside(path: Path, folder):
    """`path` relative to `folder` when it lies inside it, else None. Lexical, on normalised paths: the
    question is whether the string names the proposer's folder, which is what a rename breaks."""
    if folder is None:
        return None
    try:
        return str(Path(os.path.normpath(path)).relative_to(os.path.normpath(folder)))
    except ValueError:
        return None


def admit(items, proposer, nothing: str = "Nothing was proposed.",
          anchor_is: str = "the proposing instant's folder") -> list:
    """The PROPOSE-time gate: the stored form of each item, or `BadInput` naming every item that does not
    resolve NOW. The producer is the party that can fix a typo in seconds; the coordinator meets it hours
    later with nobody left to ask.

    An absolute path inside the proposer's own folder is STORED RELATIVE. It resolves and its intent is
    unambiguous, so refusing it would tax a correct claim to teach a style; stored verbatim, it is the path
    that dangles one rename later (`i21(a)`).

    FB-44: `milestone --evidence` admits through here too, with the coordinator as the "proposer"; `nothing`
    is the refusal's closing sentence, so it names what the refused verb did not write, and `anchor_is` names
    what a relative item resolves against (RV-30)."""
    folder = _folder(proposer)
    stored, missing = [], []
    for item in (_plain(e) for e in items):
        if is_url(item):
            stored.append(item)
            continue
        path = Path(item)
        if not path.is_absolute():
            if folder is not None and locate(item, folder) is not None:
                stored.append(item)
            else:
                missing.append(f"{item!r} (relative, so looked for at {folder}/{item})" if folder is not None
                               else f"{item!r} (relative, but the proposing instant {proposer} does not "
                                    f"resolve, so there is no folder to look in)")
            continue
        #: Through the rename, like `apply`: the coordinator re-proposing on a completed worker's behalf pastes
        #: the worker's old `-inflight-` path, and refusing what `apply` would accept is a stricter producer
        #: than consumer for no gain. Stored where it is NOW — relative when that is inside the proposer.
        found = locate(item, None)
        if found is None:
            missing.append(f"{item!r} (absolute; no such file or directory, even through an instant rename)")
            continue
        relative = _inside(found, folder)
        stored.append(relative if relative is not None else str(found))
    if missing:
        raise BadInput(
            f"{len(missing)} evidence item(s) do not resolve: {'; '.join(missing)}. Evidence is a path a "
            f"reader can open: a RELATIVE path resolves against {anchor_is} "
            f"({folder or proposer}), an absolute path must exist, and a URL is accepted as-is. {nothing}")
    return stored


def anchored(item, anchor) -> str:
    """The APPLY-time stored form: a URL verbatim, anything else where it is now — so a milestone's item
    names its folder even after the proposal that carried it is gone. Callers pass only items `dangling`
    did not return; one that no longer resolves is kept as written rather than invented."""
    if is_url(item):
        return str(item)
    found = locate(item, anchor)
    return str(found) if found is not None else str(item)


def describe(item, anchor, short: bool = False) -> str:
    """An item as a reader should see it today. `short` keeps a relative item relative (its row already
    names the proposer it is relative to); an item that does not resolve says so."""
    if is_url(item):
        return str(item)
    found = locate(item, anchor)
    if found is None:
        return f"{item} {DOES_NOT_RESOLVE}"
    if short and not Path(str(item)).is_absolute():
        return str(item)
    return str(found)
