"""Every git call the release pipeline makes, in one place.

Isolated from `release.py` so that "what is deployed" never depends on a working repository, and so the
one genuinely subtle thing here -- computing a delta that survives a rebase -- has a single home.

`git` is INJECTED, `(args, cwd) -> (rc, stdout)`, and the default runner is `workspace.default_git` --
the seam the package already declares and the outward-state audit already allows. This module therefore
spawns nothing of its own: the package's three declared, injectable spawn seams stay three, and a caller
that wants `Repo` without a repository underneath it can hand in its own runner.
"""
import sys
import tarfile
import tempfile
from pathlib import Path

from fleet.errors import BadInput, Refused
from fleet.release import Version
from fleet.workspace import default_git

__all__ = ["Repo", "changelog_section"]


class Repo:
    """One git repository, named explicitly by the caller.

    The repository is never inferred from the working directory. These operations create tags and
    rewrite nothing, but a verb that guesses its repository will eventually tag the wrong one -- and
    every release verb is driven through a real invocation by the generated matrices, from whatever
    directory the harness happens to be in.
    """

    def __init__(self, path, git=None):
        self.path = Path(path)
        self.git = default_git() if git is None else git
        if not (self.path / ".git").exists():
            raise BadInput(
                f"{self.path} is not a git repository (no .git). The repo is named explicitly and never "
                f"inferred from the working directory: these verbs create tags, and a verb that guesses "
                f"its repository will eventually tag the wrong one.")

    def _git(self, *args, check=True) -> str:
        """Run one git command in this repository and return its stdout.

        The injected runner yields `(rc, stdout)` and no stderr, so a failure is reported by naming the
        exact command and directory rather than by quoting git. That is the actionable half anyway: the
        operator can re-run the named command and read git's own words in full.
        """
        code, out = self.git(list(args), self.path)
        if check and code != 0:
            raise BadInput(f"`git {' '.join(args)}` failed in {self.path} (exit {code}). "
                           f"Re-run it there to see git's own message." + (f" Output: {out.strip()}"
                                                                          if out.strip() else ""))
        return out

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
        """Whether `ancestor` is reachable from `descendant`. False for a previous release tag is the
        signal that the nightly rebase rewrote the commits between, which is what `rebased` records."""
        code, _ = self.git(["merge-base", "--is-ancestor", ancestor, descendant], self.path)
        return code == 0

    # --- the delta ---------------------------------------------------------------------------------
    def delta(self, prev_tag):
        """`[(sha, subject)]` for every commit on HEAD and not in `prev_tag`, compared BY PATCH-ID.

        `git log prev..HEAD` would compare by ancestry, and the 03:30 rebase rewrites every commit this
        fork carries -- after which the previous tag is no longer an ancestor and the ancestry answer is
        wrong without being empty: it re-lists changes the previous release already shipped, under new
        hashes. `git cherry` compares patch-ids, which a rebase preserves, so a rewritten commit is
        still recognised as the same change and is reported once, in the release that first carried it.
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

    def file_at(self, ref: str, path: str) -> str:
        """One file's contents at one ref, or `""` if it is not there.

        Absence is not an error here: the caller is comparing the same path at two refs to decide whether
        anything but a version stamp moved, and "added" or "deleted" are answers to that question rather
        than failures of it.
        """
        code, out = self.git(["show", f"{ref}:{path}"], self.path)
        return out if code == 0 else ""

    def changed_paths(self, from_ref: str, to_ref: str) -> list:
        """Every repo-relative path differing between two refs, as `git diff --name-only` reports it.

        Compared by TREE, not by ancestry: `a..b` here is git's two-dot diff, which asks "how do these two
        trees differ". That is immune to the 03:30 rebase which rewrites this fork's commits, and it is
        the right question, because whether a release may skip its suites is a question about CONTENT, not
        about history. `delta()` above deliberately uses `git cherry` instead -- it is asking the other
        question, which changes this release has not shipped before.

        A missing ref surfaces as `BadInput` from `_git`, naming the command, rather than as an empty
        list: "nothing changed" and "I could not tell" must never be the same answer here.
        """
        out = self._git("diff", "--name-only", f"{from_ref}..{to_ref}")
        return [line.strip() for line in out.splitlines() if line.strip()]

    # --- mutation ----------------------------------------------------------------------------------
    def commit(self, paths, message: str) -> None:
        """Stage the named paths and record them. Used for the changelog the cut writes back."""
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
        untracked IT output and `__pycache__` beside 4.9 MB of tracked files.

        Written to an archive file and unpacked with `tarfile` rather than piped into the `tar` binary,
        because the injected runner hands back decoded text and a tar stream is not text -- and because
        one process is one thing that can fail instead of two.
        """
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="fleet-export-") as holder:
            archive = Path(holder) / "export.tar"
            code, out = self.git(["archive", "--format=tar", "-o", str(archive), tag], self.path)
            if code != 0:
                raise BadInput(f"exporting {tag} into {dest} failed: `git archive` exited {code} in "
                               f"{self.path}." + (f" Output: {out.strip()}" if out.strip() else ""))
            with tarfile.open(archive) as bundle:
                bundle.extractall(dest)

    # --- worktrees: the export's bytes, with a working `.git` (`II-7`) -------------------------------

    def worktree_add(self, tag: str, dest) -> Path:
        """A detached worktree at `tag`, for the IT suite to run in.

        The suite cannot judge an export. Several cases assume they are inside a git working copy and
        nothing declares the dependency, so each discovers it separately and fails in a way that looks
        like a product defect: `M13` asks `selftest` to notice a dirty path under `tests/`, which is a
        `git status --porcelain`, and `git archive` writes no `.git` by construction. `source-pin.sh`
        had the identical shape one layer down (`II-5`) and disabled the whole gate until it was fixed.

        A worktree is the same bytes with a working repository attached. `release.tree_sha` excludes the
        root `.git` precisely so a caller can prove that, and `Verify` does prove it against the
        MANIFEST before running anything -- so a release still certifies exactly what it ships. The only
        thing that changes is that the suite can run at all.

        DETACHED. Without `--detach` git creates a branch named after the tag's last path segment, and a
        second worktree at the same tag then collides with it: a re-verify would fail on repository
        bookkeeping, which reads as a defect in the release.
        """
        dest = Path(dest)
        code, out = self.git(["worktree", "add", "--detach", str(dest), tag], self.path)
        if code != 0:
            raise BadInput(
                f"creating a worktree for {tag} at {dest} failed: `git worktree add` exited {code} in "
                f"{self.path}." + (f" Output: {out.strip()}" if out.strip() else "") +
                " Verification runs the IT suite from a worktree because the suite cannot judge an "
                "export, so without one there is nothing to verify in.")
        return dest

    def worktree_remove(self, dest) -> None:
        """Remove the worktree and prune its registration.

        `--force` because the suite writes `RESULTS*.tsv` and its evidence into the tree it runs in, and
        `git worktree remove` refuses a dirty one. Everything worth keeping is copied into the release's
        evidence before this is called; what remains is litter by definition.

        The `prune` is not belt-and-braces. `remove` fails outright on a tree already gone from disk and
        leaves the registration behind either way, so without it the NEXT verify of the same version
        meets a path git still believes it owns -- and fails on bookkeeping, which again reads as a
        defect in the release. Neither call is checked: this is cleanup, and cleanup that raises turns a
        finished verification into an error.
        """
        dest = Path(dest)

        #: `QI-7`. The suite CUTS RELEASES inside the tree it runs in — §Q's fixture does exactly what a
        #: real cut does, ending in `chmod -R a-w` — and `git worktree remove --force` cannot delete a
        #: read-only directory. The remove failed, neither call is checked (below), and `prune` then
        #: tidied git's bookkeeping, so `git worktree list` read clean while the tree sat on disk. Five
        #: verifies in one day left 35 MB in five copies, growing without bound.
        #:
        #: Owner-write is restored across the worktree first. Scoped to `dest`, which this class created
        #: and named from `atomic.tmp_name`, and deepest-first so a directory is still traversable when
        #: its children are reached. Nothing outside the worktree is touched.
        for path in sorted(dest.rglob("*"), reverse=True) + [dest]:
            if path.is_symlink():
                continue
            try:
                path.chmod(path.stat().st_mode | 0o200)
            except OSError:
                pass                                   # best effort; the check below is what reports

        #: Unchecked, deliberately: cleanup that raises turns a finished verification into an error.
        self.git(["worktree", "remove", "--force", str(dest)], self.path)
        self.git(["worktree", "prune"], self.path)

        #: But NOT unnoticed. `QI-7` was invisible precisely because a silent failure here looks
        #: identical to success, and `git worktree list` agrees with the lie. Absence is never success:
        #: if the tree is still there, say so, on stderr, naming what to remove by hand.
        if dest.exists():
            print(f"fleet: the verification worktree at {dest} could not be removed and is still on "
                  f"disk ({sum(1 for _ in dest.rglob('*'))} entries). git's bookkeeping is clean, so "
                  f"`git worktree list` will not show it. Remove it by hand.", file=sys.stderr)


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
