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
* an ABSOLUTE item is itself if it exists, else the deepest path component that is an instant name is
  re-resolved the same way and the tail re-joined — the case of a coordinator citing a worker's file, or of
  a milestone path written while its instant was still `-inflight-`.

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


def is_url(item) -> bool:
    return bool(_URL.match(str(item)))


def _folder(instant):
    """The instant's folder NOW, or None. Two folders sharing a stable key is not a location either: the
    resolver refuses to guess, and so does every caller here."""
    if instant is None:
        return None
    try:
        return resolve(Path(instant))
    except AmbiguousId:
        return None


def _through_rename(path: Path):
    if path.exists():
        return path
    parts = path.parts
    for i in range(len(parts) - 1, 0, -1):
        try:
            InstantName.parse(parts[i])
        except InstantNameError:
            continue
        folder = _folder(Path(*parts[:i + 1]))
        if folder is None:
            return None
        found = folder.joinpath(*parts[i + 1:])
        return found if found.exists() else None
    return None


def locate(item, anchor):
    """Where `item` is NOW, or None. `anchor` is the proposing instant (its recorded path; a stale
    `-inflight-` path is fine). A URL has no location here and returns None — ask `is_url` first."""
    if is_url(item):
        return None
    path = Path(str(item))
    if path.is_absolute():
        return _through_rename(path)
    folder = _folder(anchor)
    if folder is None:
        return None
    found = folder / path
    return found if found.exists() else None


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


def admit(items, proposer) -> list:
    """The PROPOSE-time gate: the stored form of each item, or `BadInput` naming every item that does not
    resolve NOW. The producer is the party that can fix a typo in seconds; the coordinator meets it hours
    later with nobody left to ask.

    An absolute path inside the proposer's own folder is STORED RELATIVE. It resolves and its intent is
    unambiguous, so refusing it would tax a correct claim to teach a style; stored verbatim, it is the path
    that dangles one rename later (`i21(a)`)."""
    folder = _folder(proposer)
    stored, missing = [], []
    for item in (str(e) for e in items):
        if is_url(item):
            stored.append(item)
            continue
        path = Path(item)
        if not path.is_absolute():
            if folder is not None and (folder / path).exists():
                stored.append(item)
            else:
                missing.append(f"{item!r} (relative, so looked for at {folder or proposer}/{item})")
            continue
        if not path.exists():
            missing.append(f"{item!r} (absolute; no such file or directory)")
            continue
        relative = _inside(path, folder)
        stored.append(relative if relative is not None else item)
    if missing:
        raise BadInput(
            f"{len(missing)} evidence item(s) do not resolve: {'; '.join(missing)}. Evidence is a path a "
            f"reader can open: a RELATIVE path resolves against the proposing instant's folder "
            f"({folder or proposer}), an absolute path must exist, and a URL is accepted as-is. Nothing was "
            f"proposed.")
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
