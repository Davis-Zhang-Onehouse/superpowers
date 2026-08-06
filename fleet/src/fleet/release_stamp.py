"""The version lines a release stamps, and the one it must not overwrite.

`RI-12`. `release-cut` rewrote exactly one file -- `fleet/src/fleet/__init__.py` -- while SEVEN manifest
files declare the version a user actually reads. Measured: `claude plugin list` prints `Version: 6.2.0` on
a box deployed at fleet 0.3.7, and `.claude-plugin/plugin.json` reads `6.2.0` at every one of the fifteen
release tags ever cut. Fifteen releases; the number a user is shown never moved once.

**The two lineages are real and must both survive** (`D-5`). This repository is a fork of upstream
`superpowers` at `6.2.0`; the manifests describe the skills library and their provenance is upstream's.
The fleet CLI versions independently at `0.x`. Making the two numbers EQUAL -- writing `0.3.8` over
`6.2.0`, which is the obvious reading of "the plugin version should track the fleet version" -- is a
version DECREASE that any consumer comparing versions reads as a downgrade, and it erases the fork point.

So the fleet version rides as semver BUILD METADATA: `6.2.0+fleet.0.3.8`. Build metadata never affects
precedence, so the number cannot decrease; it names both facts exactly; and it changes on every release,
which is the property the frozen `6.2.0` lacked. `claude plugin validate` was run against
`6.2.0+fleet.0.3.8` before this was chosen, and passed.

WHICH files carry the version is not decided here. `.version-bump.json` already declares that set for
`scripts/bump-version.sh`, so this module READS it -- a manifest added later is stamped without anyone
touching the pipeline, and there is no second list to drift out of sync with the first.

A leaf: `json`, `re` and `pathlib`, plus `errors`. No git, no subprocess, no other package module.
"""
import json
import re
from pathlib import Path

from fleet.errors import BadInput

__all__ = ["BUILD_TAG", "VERSION_CONFIG", "core_of", "declared_version_files", "plugin_version",
           "stamp_plugin_version"]

#: The repository's own declaration of which files carry the version, and in which field. Shared with
#: `scripts/bump-version.sh`, which is the point.
VERSION_CONFIG = ".version-bump.json"

#: The build-metadata identifier. `6.2.0+fleet.0.3.8` reads as "upstream 6.2.0, fleet 0.3.8" to a human
#: and as "6.2.0" to anything that compares versions.
BUILD_TAG = "fleet"


def core_of(version: str) -> str:
    """The version with any build metadata removed.

    Stamping reads the CURRENT value and replaces only the metadata, so a second release on the same day
    produces `6.2.0+fleet.0.3.9` rather than `6.2.0+fleet.0.3.8+fleet.0.3.9` -- and an upstream bump to
    `6.3.0` is carried forward rather than clobbered back.
    """
    return (version or "").split("+", 1)[0]


def plugin_version(current: str, fleet_version) -> str:
    """`<upstream core>+fleet.<fleet version>`."""
    return f"{core_of(current)}+{BUILD_TAG}.{fleet_version}"


def declared_version_files(repo_path) -> tuple:
    """`((relative path, dotted field), …)` from `.version-bump.json`, or `()` when there is none.

    Absent is not an error: the throwaway checkouts the release suite builds carry no manifests, and a
    repository that declares no version files simply has none to stamp. A MALFORMED config is a different
    thing and does raise -- "I could not read the declaration" must never be indistinguishable from
    "nothing is declared", which is the same rule `changed_paths` follows one module over.
    """
    config = Path(repo_path) / VERSION_CONFIG
    if not config.is_file():
        return ()
    try:
        body = json.loads(config.read_text())
    except ValueError as broken:
        raise BadInput(f"{config} is not readable as JSON ({broken}). It declares which files carry the "
                       f"version, so a cut cannot stamp them without it — and skipping them silently "
                       f"would ship a release whose manifests name the previous one.")
    return tuple((entry["path"], entry["field"]) for entry in body.get("files", []))


def _read_field(body: dict, field: str):
    """One dotted field path (`plugins.0.version`) out of a parsed document, or None."""
    cursor = body
    for part in field.split("."):
        if isinstance(cursor, list):
            if not part.isdigit() or int(part) >= len(cursor):
                return None
            cursor = cursor[int(part)]
        elif isinstance(cursor, dict):
            if part not in cursor:
                return None
            cursor = cursor[part]
        else:
            return None
    return cursor if isinstance(cursor, str) else None


def _rewrite(path: Path, field: str, old: str, new: str, dry_run: bool = False) -> None:
    """Replace one `"leaf": "old"` occurrence in the raw text, preserving every other byte.

    Not `json.dump`. These are hand-maintained files with an author's formatting, and reserialising them
    would rewrite indentation, key spacing and trailing newlines on every release -- burying the one real
    change in diff noise, in files whose diff is how an operator checks what a cut did.

    Exactly one occurrence, or REFUSED. Two fields spelled the same with the same value cannot be told
    apart from the text, and stamping the first would silently rewrite the wrong one.
    """
    leaf = field.rsplit(".", 1)[-1]
    pattern = re.compile(rf'("{re.escape(leaf)}"\s*:\s*)"{re.escape(old)}"')
    text = path.read_text()
    found = pattern.findall(text)
    if len(found) != 1:
        raise BadInput(
            f"{path} has {len(found)} field(s) spelled \"{leaf}\" with the value {old!r}; a cut stamps "
            f"exactly one. Which one was meant cannot be decided from the file, and stamping the first "
            f"would rewrite the wrong line without saying so.")
    if dry_run:
        return
    path.write_text(pattern.sub(lambda match: f'{match.group(1)}"{new}"', text, count=1))


def stamp_plugin_version(repo_path, fleet_version, dry_run: bool = False) -> list:
    """Stamp every declared manifest with `<core>+fleet.<fleet_version>`.

    Returns `[(relative path, old, new)]` for the files that MOVED -- the cut adds exactly those to its
    commit, so a release whose manifests were already correct does not carry an empty change.

    `dry_run` does every check and writes nothing. The cut calls it that way AT THE EDGE, before it takes
    the lock, for the reason it already checks `__init__.py` by name there: "the alternative is a failure
    half way through, after the changelog has been written". A malformed manifest must refuse the release
    while the operator's checkout is still untouched, not between the changelog write and the tag.

    A declared file that is not on disk is skipped rather than refused: `.version-bump.json` lists the
    manifests of every harness this repository has ever shipped for, and one being absent on a given
    branch is ordinary. The skip is visible in the returned list by omission, which is what the cut
    reports.
    """
    root = Path(repo_path)
    changed = []
    for relative, field in declared_version_files(root):
        path = root / relative
        if not path.is_file():
            continue
        try:
            body = json.loads(path.read_text())
        except ValueError as broken:
            raise BadInput(f"{path} declares a version field but is not readable as JSON ({broken}).")
        old = _read_field(body, field)
        if old is None:
            raise BadInput(f"{path} does not carry the field {field!r} that {VERSION_CONFIG} declares "
                           f"for it. Refused rather than skipped: a declared file that has quietly lost "
                           f"its version field is how a release ships a manifest naming its predecessor.")
        new = plugin_version(old, fleet_version)
        if new == old:
            continue
        #: The ambiguity check lives inside `_rewrite`, so a dry run has to reach it — otherwise the edge
        #: check would pass on exactly the file that later refuses under the lock, which is the failure
        #: mode `dry_run` exists to prevent.
        _rewrite(path, field, old, new, dry_run=dry_run)
        changed.append((relative, old, new))
    return changed
