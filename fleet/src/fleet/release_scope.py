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

__all__ = ["INERT_DIRS", "INERT_ROOT_FILES", "REQUIRING_SKILLS", "SKILLS_DIR", "Scope", "classify"]

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
