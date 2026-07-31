"""The slot's CONTENTS, as distinct from its lease — four concerns `pool` deliberately does not own.

Split from `pool` because `pool` owns the lease and this owns what is inside it. Added in rev 2 of the
design: rev 1 omitted all four of these concerns, which is the second time the components with the fewest
filed defects got the least specification (FI-6).

1. **Golden resolution is a declared setting.** There is no golden marker on the real box today, so the
   predecessor survived only by inheriting one from the last dispatch record — a fallback silently doing
   load-bearing work (FR2-13.2 / MI-7). Here an undeclared golden is `BadInput` that names the fix.
2. **Build-cache isolation is APPLIED AT DISPATCH, not requested of the worker.** A worker cannot be
   relied on to pass a flag on every invocation; R5I-4 is the live instance — a stale `.m2-compact1` left
   in place and overridden on every command line instead of being wired into the tree once.
3. **A populated cache under any name is reused.** Pointing at a bare `.m2` that does not exist isolates
   the build with a COLD cache, which is its own failure (OI-6), so the target must exist before the
   config names it.
4. **`base-check` has three non-failing states, not one.** "The build succeeds, the tests pass, and the
   work is stacked on the pre-fix baseline" is the defect this exists to catch — two of five workers in
   one effort hit it — but the first version of the check false-alarmed on BOTH states a healthy worker
   occupies (OBS-12): at the base, and a descendant of it. `present` is advisory, because an analysis
   milestone parked on the golden and reading the base via `git show` is the better choice there.

`git` is INJECTED — `(args, cwd) -> (rc, stdout)`. `default_git()` is the only subprocess in this module.
"""
import shutil
from dataclasses import dataclass
from pathlib import Path

from fleet.atomic import atomic_write
from fleet.errors import BadInput

#: The declared golden lives in a file, not in a heuristic over prior records.
GOLDEN_FILE = "golden"

#: The one flag build-cache isolation is expressed as. Presence of this substring is what makes the
#: write idempotent, so re-running dispatch cannot stack duplicate lines.
REPO_LOCAL = "-Dmaven.repo.local="

#: `absent` is the only hard failure. `present` is advisory. Both `at-base` and `descendant` are states a
#: healthy worker legitimately occupies, and ranking them equal is the fix for OBS-12.
_SEVERITY = {"at-base": 0, "descendant": 0, "present": 1, "absent": 2}
_VERDICTS = ("ok", "advisory", "failed")


@dataclass(frozen=True)
class BaseCheck:
    repo: str
    expected: str
    actual: str | None
    verdict: str      # "at-base" | "descendant" | "present" | "absent"


def default_git():
    """The real git runner: `(args, cwd) -> (rc, stdout)`.

    This function is the ONLY place in this module that spawns a subprocess. Every caller may inject its
    own runner, so the whole of `base_check` is decidable without a repository underneath it.
    """
    import subprocess

    def run(args, cwd):
        done = subprocess.run(["git", *list(args)], cwd=str(cwd),
                              capture_output=True, text=True)
        return done.returncode, done.stdout

    return run


class Workspace:
    """What is inside a slot: the golden it was cloned from, its build cache, its lineage position."""

    def __init__(self, home: Path, git=None):
        self.home = Path(home)
        self.git = default_git() if git is None else git

    # ---- golden: a declared setting, never an inference -----------------------------------------

    @property
    def _golden_file(self) -> Path:
        return self.home / GOLDEN_FILE

    def golden(self) -> Path:
        text = self._golden_file.read_text().strip() if self._golden_file.is_file() else ""
        if not text:
            raise BadInput(
                f"no golden workspace is declared in {self._golden_file}. Declare it with "
                "`fleet set-golden --path <dir>` (in python: `set_golden(<path>)`) — the verb named here "
                "is the verb that exists, because a remedy nobody can run fails a second time (FI-19a). "
                "There is deliberately NO "
                "fallback: inheriting the golden from the most recent dispatch record is how the "
                "predecessor kept working with nothing declared, which made an unset setting "
                "indistinguishable from a correct one."
            )
        return Path(text)

    def set_golden(self, path: Path) -> None:
        path = Path(path)
        if not path.is_dir():
            raise BadInput(
                f"{path} is not an existing directory, so it cannot be the golden workspace. "
                "The golden is validated at SET time, because a golden that does not exist is "
                "discovered at clone time — inside a dispatch that has already claimed a slot."
            )
        atomic_write(self._golden_file, f"{path}\n")

    # ---- clone: growing the pool FROM the declared golden ----------------------------------------

    def clone(self, target: Path) -> dict:
        """Duplicate the declared golden into `target`. -> a report dict.  `SI-19`.

        The missing half of `SI-19`, and the reason the other half looked like a working feature: `set_golden`
        validated and stored a golden, and `golden()` had exactly ONE caller — `set-golden`'s own echo-back.
        The declared golden was write-only in practice, so a pool grew only by `enroll`ing directories somebody
        had duplicated by hand, outside the tool, with nothing checking they came from the golden at all.

        A filesystem copy, `shutil.copytree`, and NOT a git clone. That is the whole point of a golden: it
        carries prebuilt artifacts and a warm build cache, and a `git clone` would reproduce the source while
        throwing away the thing that makes a leased slot cheaper than a fresh checkout. It is also why this
        stays in stdlib and adds no subprocess seam — the module states its seam count deliberately.

        Refuses rather than overwrites. A clone onto an existing directory is either a mistake or a request to
        blow away somebody's leased workspace, and neither is worth guessing between.
        """
        golden = self.golden()
        target = Path(target)
        if not golden.is_dir():
            raise BadInput(
                f"the declared golden {golden} is not a directory, so there is nothing to clone. It is "
                f"validated at SET time for exactly this reason; something has moved or removed it since.")
        if target.exists():
            raise BadInput(
                f"{target} already exists. A clone never overwrites: the target is either a mistake or "
                f"somebody's leased workspace, and guessing between those is how a live slot gets erased. "
                f"Pick a fresh path, or remove that one by hand if you are sure.")
        if str(target).startswith(str(golden) + "/") or target == golden:
            raise BadInput(
                f"{target} is inside the golden {golden}. Cloning a directory into itself does not terminate.")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(golden, target, symlinks=True, ignore_dangling_symlinks=True)
        files = sum(1 for _ in target.rglob("*") if _.is_file())
        return {"golden": str(golden), "target": str(target), "files": files}

    def clone_parity(self, target: Path, repos) -> list:
        """-> [(repo, golden_head, clone_head, same)] for each repo present in BOTH.

        A clone nobody checked is a clone you hope worked. Parity is asserted on the git HEAD per repo rather
        than on a byte count, because HEAD is the thing a worker's lineage base is compared against — a copy
        that landed at a different commit would send every `base-check` in that slot to the wrong answer.
        """
        golden, target = self.golden(), Path(target)
        out = []
        for repo in sorted(repos):
            g, t = golden / repo, target / repo
            if not (g / ".git").exists() or not (t / ".git").exists():
                continue
            grc, ghead = self.git(["rev-parse", "HEAD"], g)
            trc, thead = self.git(["rev-parse", "HEAD"], t)
            gh = ghead.strip() if grc == 0 else None
            th = thead.strip() if trc == 0 else None
            out.append((repo, gh, th, bool(gh) and gh == th))
        return out

    # ---- build-cache isolation: applied here, not asked of the worker ---------------------------

    def _poms(self, slot: Path) -> list:
        """Every `pom.xml` at depth <= 2. A slot holds several sibling repos; each needs its own wiring."""
        found = set(slot.glob("pom.xml")) | set(slot.glob("*/pom.xml"))
        return sorted(found)

    def _cache_dir(self, slot: Path) -> Path:
        """An existing `.m2*` that actually CONTAINS a jar, else `<slot>/.m2`.

        Reuse is keyed on being populated, not on being named `.m2`: a cache directory that exists but
        holds nothing is a cold cache wearing the name of a warm one (OI-6), and the live instance
        (R5I-4) is populated under a non-canonical name.
        """
        for candidate in sorted(d for d in slot.glob(".m2*") if d.is_dir()):
            if next(candidate.rglob("*.jar"), None) is not None:
                return candidate
        return slot / ".m2"

    def isolate_build_cache(self, slot_path: Path) -> list:
        slot = Path(slot_path)
        cache = self._cache_dir(slot)
        cache.mkdir(parents=True, exist_ok=True)     # BEFORE anything names it
        line = f"{REPO_LOCAL}{cache}"
        written = []
        for pom in self._poms(slot):
            config = pom.parent / ".mvn" / "maven.config"
            existing = config.read_text() if config.is_file() else ""
            if REPO_LOCAL in existing:
                continue                              # already isolated; do not stack a second line
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(f"{existing}{line}\n" if existing else f"{line}\n")
            written.append(config)
        return written

    # ---- base-check: three states that are not failures ----------------------------------------

    def base_check(self, slot_path: Path, expected: dict) -> list:
        slot = Path(slot_path)
        out = []
        for repo in sorted(expected):
            want = expected[repo]
            cwd = slot / repo
            rc, stdout = self.git(["rev-parse", "HEAD"], cwd)
            actual = stdout.strip() if rc == 0 and stdout.strip() else None
            out.append(BaseCheck(repo, want, actual, self._position(cwd, want, actual)))
        return out

    def _position(self, cwd: Path, want: str, actual) -> str:
        if actual is None:
            return "absent"
        if actual == want:
            return "at-base"
        rc, _ = self.git(["merge-base", "--is-ancestor", want, "HEAD"], cwd)
        if rc == 0:
            return "descendant"
        rc, _ = self.git(["cat-file", "-t", want], cwd)
        if rc == 0:
            return "present"
        return "absent"

    def dirty(self, slot_path: Path, repos) -> list:
        """Repos with uncommitted changes. `SI-32`.

        A dirty tree means the code on disk is not the tip any CI proved, so a green run elsewhere says
        nothing about what is here — the same insight `P-1` rests on, where `assert-head-green.sh` verifies
        from a `git archive` EXPORT and never from the working tree.

        Reported, never failed: a worker mid-change is legitimately dirty, and this is consulted at the point
        it claims to be DONE, where the caller decides what a dirty tree means for its claim.
        """
        slot = Path(slot_path)
        out = []
        for repo in sorted(repos):
            rc, stdout = self.git(["status", "--porcelain"], slot / repo)
            if rc == 0 and stdout.strip():
                out.append(repo)
        return out

    def stale_native(self, slot_path: Path, golden_base: dict, current: dict) -> list:
        """-> [(repo, artifact_name)] whose prebuilt native artifacts predate the last checkout.  `SI-32`.

        THE check that actually fired in the real incident. A slot is leased from a pre-built golden image,
        so `libvelox.so` / `libgluten.so` are **files copied in**, not Maven products — from the build
        system's point of view they are inputs, so nothing invalidates them when the source is repositioned.
        The result is a test run exercising NEW source against OLD native code: a false green the build
        system cannot see. The record: *"basecheck additionally warned that the prebuilt native artifacts
        were still the GOLDEN ones — material here because this milestone is a velox change — so I rebuilt
        velox, relinked libvelox.so/libgluten.so, recopied into the test classpath."*

        A HEURISTIC, and it says so. Freshness is judged by mtime against `.git/HEAD`, which git rewrites on
        checkout: an artifact NEWER than the last checkout was built after repositioning, which is the remedy
        this warning asks for. Warning anyway would make it an alarm that can never be cleared, and an alarm
        that always fires gets ignored — `SD-4`'s rule applied to a warning rather than to a refusal.

        Only ever a WARNING. A JVM-only milestone is legitimately unaffected, and nothing here can tell
        whether this milestone touches native code.
        """
        slot = Path(slot_path)
        out = []
        for repo in sorted(golden_base):
            was, now = golden_base.get(repo), current.get(repo)
            if not was or not now or was == now:
                continue                      # still where the artifacts were built: nothing to say
            cwd = slot / repo
            artifacts = sorted(cwd.rglob("*.so")) if cwd.is_dir() else []
            if not artifacts:
                continue
            head = cwd / ".git" / "HEAD"
            if not head.exists():
                continue
            checkout_at = head.stat().st_mtime
            stale = [p for p in artifacts if p.stat().st_mtime <= checkout_at]
            if stale:
                out.append((repo, stale[0].name))
        return out

    def verdict(self, checks: list) -> str:
        """The WORST position across repos governs. A per-repo verdict reported alone is how a check
        whose scope narrows reads as a pass (OBS-49)."""
        if not checks:
            return "ok"
        return _VERDICTS[max(_SEVERITY[c.verdict] for c in checks)]
