"""Which changed paths oblige a release to run the suites, and which do not.

A release is a `git archive` of the WHOLE repository -- it ships `skills/`, `commands/`, `hooks/` and
`docs/` alongside `fleet/`, and the deployed export IS the plugin marketplace source every session on the
box loads from. A release that only edits documentation therefore pays a ~24 minute gate to prove that
code it did not touch still works. The alternative in use before this module was `release-deploy --force`,
which is not a decision but an override: it discards the gate and records the release UNVERIFIED, which is
how `0.3.2` came to be deployed without evidence.

This module is the one place that rule lives, and it is an ALLOWLIST on purpose. A path is inert only
because it MATCHES something declared here -- never because it failed to match `fleet/`. A denylist would
be fail-open: a new top-level directory, or a suite that later reads a new script, would become silently
exempt and the failure would ship invisibly. This way the failure mode is a needless test run.

The carve-out is the subtle part and the reason "outside `fleet/`" is not a usable rule. Two suite
call-sites read `skills/using-fleet/`:

  * `fleet/tests/test_contracts.py` asserts, in both directions, that `skills/using-fleet/SKILL.md` names
    exactly the verbs `cli.VERBS` declares.
  * `fleet/it/run-P.sh` copies `skills/using-fleet/profiles/worker` into a live IT fixture.

So that one skill is covered by the suites while every other skill is not.

A leaf: no imports from the package, no git, no filesystem, no subprocess. The decision that gates a
release is a pure function of a list of strings, so it can be tested exhaustively without a repository.
"""

import re

__all__ = ["CUT_CHANGELOG", "CUT_MANIFESTS", "CUT_STAMPED", "INERT_DIRS", "INERT_ROOT_FILES",
           "OTHER_AREA", "PAYLOAD_AREAS", "REQUIRING_SKILLS", "SKILLS_DIR", "Scope", "areas",
           "classify", "skills_changed", "without_version_field", "without_version_line"]

#: Directory trees whose contents cannot affect either suite. Trailing slash is load-bearing: it makes
#: these path-segment prefixes, so `docs/` never matches a sibling named `docsomething.md`.
INERT_DIRS = ("docs/", "assets/")

#: Repository-root files that are documentation. Declared exhaustively rather than by extension: a new
#: root `.md` is not inert by analogy, because nothing says a future root file is only prose.
INERT_ROOT_FILES = frozenset({
    "README.md", "LICENSE", "CODE_OF_CONDUCT.md", "RELEASE-NOTES.md",
    "AGENTS.md", "GEMINI.md", "CLAUDE.md",
})

SKILLS_DIR = "skills/"

#: The two files `release-cut` writes ITSELF, under its lock, before it tags -- so they differ between
#: EVERY pair of release tags no matter what the author changed. Treating them as ordinary `fleet/` paths
#: made this whole feature unreachable: a documentation-only release still showed them changed, so nothing
#: could ever be exempt. That is `SI-19`'s shape -- correct, tested, dead -- and it was invisible to unit
#: tests because they fed hand-written path lists rather than a real cut's diff.
#:
#: `CUT_CHANGELOG` is pure documentation and is simply inert. `CUT_STAMPED` is NOT: it also carries the
#: exit-code registry, so it is inert only when the two blobs are identical once the `__version__` line is
#: removed. `classify` cannot make that distinction -- it sees paths, not contents -- so it treats the path
#: as inert and `exemption_for` puts it back if anything other than the version moved.
CUT_CHANGELOG = "fleet/CHANGELOG.md"
CUT_STAMPED = "fleet/src/fleet/__init__.py"

#: The manifests `release-cut` stamps with the plugin version (`RI-12`, `release_stamp`). Same problem as
#: `CUT_STAMPED` and the same answer: they now differ between EVERY pair of release tags, so treating them
#: as ordinary paths would make exemption unreachable for every release that will ever exist -- which is
#: `SI-19`'s shape, and is exactly what `0.3.7` had just finished fixing one file over.
#:
#: Inert as PATHS only. `exemption_for` re-checks each on CONTENT with `without_version_field`, so an
#: author's edit to `plugin.json` can never ride out on a version stamp.
#:
#: Mirrors `.version-bump.json`, which this module cannot read: it is a leaf with no filesystem, by
#: design, because the decision that gates a release must be a pure function of a list of strings.
#: `test_release_payload` asserts the two agree, so the duplication cannot drift in silence.
CUT_MANIFESTS = ("package.json", ".claude-plugin/plugin.json", ".cursor-plugin/plugin.json",
                 ".codex-plugin/plugin.json", ".kimi-plugin/plugin.json",
                 ".claude-plugin/marketplace.json", "gemini-extension.json")

#: `__version__ = "X.Y.Z"`, however it is spaced or quoted. Matched rather than parsed, because the only
#: thing that must be recognised is the line `release-cut` rewrites with `re.sub`.
_VERSION_LINE = re.compile(r'^\s*__version__\s*=\s*["\'][^"\']*["\']\s*$', re.MULTILINE)

#: `"version": "…"` in a JSON manifest, as a whole line. The same question as `_VERSION_LINE` asks of a
#: Python module, for the seven files a cut stamps.
_VERSION_FIELD = re.compile(r'^\s*"version"\s*:\s*"[^"]*"\s*,?\s*$', re.MULTILINE)


def without_version_line(text: str) -> str:
    """`text` with the `__version__` assignment removed, for comparing two stamps of one file.

    The question this answers is "did anything OTHER than the version change here", and it has to be
    answered on content because the path alone cannot distinguish a release stamp from someone editing
    `EXIT_CODES` in the same file.
    """
    return _VERSION_LINE.sub("", text or "")


def without_version_field(text: str) -> str:
    """`text` with any `"version": "…"` line removed, for comparing two stamps of one JSON manifest.

    The JSON counterpart of `without_version_line`, and it exists for the identical reason: `classify`
    treats `CUT_MANIFESTS` as inert because the cut rewrites them on every release, and something has to
    tell that rewrite apart from an author renaming the plugin in the same file.
    """
    return _VERSION_FIELD.sub("", text or "")


#: How a release DESCRIBES its payload (`RI-13`). Ordered, because a declared order makes two releases'
#: notes comparable at a glance where diff order would not.
#:
#: Deliberately a SECOND classifier rather than a widening of `classify` (`D-6`). The two answer different
#: questions and have opposite safe defaults: a gate must fail towards running the suites, so `classify`
#: is an allowlist and an unrecognised path is `requiring`; a description must fail towards naming the
#: path anyway, so this one has an explicit `other` bucket. Folding them would put a describe-only bucket
#: inside the function that decides whether a release skips its gate, which is how an allowlist quietly
#: becomes a denylist.
PAYLOAD_AREAS = (
    ("fleet", ("fleet/",)),
    ("skills", (SKILLS_DIR,)),
    ("commands", ("commands/",)),
    ("hooks", ("hooks/",)),
    ("plugin-manifests", (".claude-plugin/", ".cursor-plugin/", ".codex-plugin/", ".kimi-plugin/",
                          "package.json", "gemini-extension.json", ".version-bump.json")),
    ("scripts", ("scripts/", "bin/")),
    ("tests", ("tests/",)),
    ("docs", ("docs/", "assets/") + tuple(sorted(INERT_ROOT_FILES))),
)

#: Everything the declaration above does not recognise. Named, never hidden — nothing branches on this
#: answer, so the only outcome that would be wrong is a payload a reader cannot see.
OTHER_AREA = "other"

#: The cut's own bookkeeping, excluded from the payload description. A release's notes must not be
#: dominated by the two files the release wrote about itself.
_NOT_PAYLOAD = (CUT_CHANGELOG, CUT_STAMPED) + CUT_MANIFESTS


def _area_of(path: str) -> str:
    for name, prefixes in PAYLOAD_AREAS:
        for prefix in prefixes:
            if path == prefix.rstrip("/") or path.startswith(prefix) or path == prefix:
                return name
    return OTHER_AREA


def areas(paths) -> tuple:
    """`((area, (path, …)), …)` for a changeset, in `PAYLOAD_AREAS` order, skipping empty areas.

    Descriptive only. `classify` decides whether the suites run; this decides what the changelog and
    `release-status` say a release contains, and the two never consult each other.
    """
    buckets, seen = {}, set()
    for raw in paths or ():
        path = _normalise(raw)
        if not path or path in seen or path in _NOT_PAYLOAD:
            continue
        seen.add(path)
        buckets.setdefault(_area_of(path), []).append(path)
    ordered = [name for name, _ in PAYLOAD_AREAS] + [OTHER_AREA]
    return tuple((name, tuple(buckets[name])) for name in ordered if buckets.get(name))


def skills_changed(paths) -> tuple:
    """The NAMES of the skills a changeset touches, de-duplicated and sorted.

    What a reader wants from a skills release is `releasing-fleet`, not four paths beneath it — and
    naming them is the one thing that makes a skills-only release legible without exporting two versions
    and diffing them.
    """
    names = set()
    for raw in paths or ():
        path = _normalise(raw)
        if not path.startswith(SKILLS_DIR):
            continue
        rest = path[len(SKILLS_DIR):].split("/")
        if rest and rest[0]:
            names.add(rest[0])
    return tuple(sorted(names))

#: Skills the suites actually read. Everything else under `skills/` is inert. Keep this narrow, and never
#: widen it to silence a failing test -- check whether the call-sites named in the module docstring still
#: exist first.
REQUIRING_SKILLS = ("skills/using-fleet/",)


class Scope:
    """The classification of one changeset.

    `exempt` is deliberately derived from `requiring` being empty rather than stored, so there is no way
    to construct a Scope whose verdict disagrees with its own path lists.
    """

    __slots__ = ("inert", "requiring")

    def __init__(self, inert, requiring):
        self.inert = tuple(inert)
        self.requiring = tuple(requiring)

    @property
    def exempt(self) -> bool:
        """True when nothing changed that either suite could observe.

        An empty changeset is exempt: the tree is identical to the anchor, which passed.
        """
        return not self.requiring

    def __repr__(self) -> str:
        return f"Scope(inert={len(self.inert)}, requiring={len(self.requiring)}, exempt={self.exempt})"


def _normalise(path: str) -> str:
    """One repo-relative, slash-separated spelling, or `""` for something to ignore.

    `git diff --name-only` already emits this form; normalising anyway because the caller is not the only
    possible source, and a path that reaches the inert branch through a spelling quirk is the one bug
    class this module cannot afford.
    """
    path = (path or "").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path.strip("/") if path not in ("", ".") else ""


def _is_inert(path: str) -> bool:
    """Whether one already-normalised path is safe to skip the suites for.

    Order matters: the `skills/using-fleet/` carve-out is tested BEFORE the general `skills/` rule, so the
    narrower statement wins. Written as an explicit early return rather than a clever predicate because
    the consequence of getting the precedence wrong is shipping an unverified release.
    """
    #: A traversal cannot be reasoned about as a prefix at all -- `docs/../fleet/...` starts with `docs/`
    #: and is a fleet path. Refuse to call it inert rather than resolve it: this module has no filesystem.
    if ".." in path.split("/"):
        return False

    for prefix in REQUIRING_SKILLS:
        #: The bare directory itself (`skills/using-fleet`) counts too -- a rename or deletion of it is
        #: exactly the change the suites would catch.
        if path == prefix.rstrip("/") or path.startswith(prefix):
            return False

    #: The cut's own footprint. See CUT_CHANGELOG / CUT_STAMPED / CUT_MANIFESTS: these differ between
    #: every pair of release tags by construction, so counting them as ordinary paths makes exemption
    #: unreachable. CUT_STAMPED and every CUT_MANIFEST are re-checked on CONTENT by `exemption_for`.
    if path in (CUT_CHANGELOG, CUT_STAMPED) or path in CUT_MANIFESTS:
        return True

    if path.startswith(SKILLS_DIR):
        return True
    if any(path.startswith(prefix) for prefix in INERT_DIRS):
        return True
    return path in INERT_ROOT_FILES


def classify(paths) -> Scope:
    """Split changed paths into (inert, requiring), preserving input order and de-duplicating.

    Order is kept because the result is written verbatim into the release's `EXEMPTION.tsv`, and an
    operator checking the decision by hand should see the diff in the order git reported it.
    """
    inert, requiring, seen = [], [], set()
    for raw in paths or ():
        path = _normalise(raw)
        if not path or path in seen:
            continue
        seen.add(path)
        (inert if _is_inert(path) else requiring).append(path)
    return Scope(inert, requiring)
