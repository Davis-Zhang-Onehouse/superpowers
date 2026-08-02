"""Run both suites against a frozen export and say what happened.

Against the EXPORT and not the checkout, which is what makes contamination structural instead of
procedural: the IT orchestrator pins `src/*.py` before and after precisely because an edit mid-run
invalidates every verdict measured before it, and nothing can edit a read-only artifact.

This module spawns nothing. The command runner is a REQUIRED constructor argument of the same shape the
CLI already hands every handler -- `(command, cwd, env) -> (rc, stdout, stderr)` -- so the package's three
declared, injectable spawn seams stay three. A defaulted `subprocess.run` here would be a fourth, in the
one module whose job is to run things, and the outward-state audit asserts the count exactly.

Two invariants are worth stating out loud because they are easy to lose:

*`PYTHONDONTWRITEBYTECODE=1` is load-bearing.* The export is `chmod -R a-w`; without it `unittest` tries
to write `__pycache__` into our own read-only artifact and the hermetic run fails for a reason that has
nothing to do with the code.

*The IT suite cannot run inside the export at all* -- and for two reasons, only one of which was obvious.
The export is read-only while the orchestrator writes `RESULTS*.tsv` beside itself; and, `II-7`, several
cases assume they are inside a git working copy, which an export is not by construction. `M13` asks
`selftest` to notice a dirty path under `tests/`, which is a `git status --porcelain`. Nothing declared
that dependency, so each case discovered it separately and failed in a way indistinguishable from a
product defect.

So the suite runs in a `git worktree` at the release's tag: the same bytes, with a working repository.
`tree_sha` is recomputed there and compared with the MANIFEST, so "what was tested is what shipped" stays
asserted rather than assumed -- it is the same guarantee the writable copy carried, over a tree that can
actually run the suite. The hermetic suite still runs in the export itself, read-only, because it can.
"""
import os
import shlex
import shutil
from pathlib import Path

from fleet.atomic import atomic_write, tmp_name
from fleet.errors import Refused
from fleet.release import META_DIR, Releases, Version, tree_sha

__all__ = ["FULL_ROSTER", "GATE_ROSTER", "GREEN", "INCONCLUSIVE", "RED", "Verify",
           "read_verdict", "verdict_for", "write_verdict"]

GREEN = "GREEN"
RED = "RED"
INCONCLUSIVE = "INCONCLUSIVE"

GATE_ROSTER = "gate"
FULL_ROSTER = "full"

VERDICT_COLUMNS = ("suite", "verdict", "evidence", "note")

#: The row that carries the roster. A key rather than a header field, so a reader that does not know about
#: rosters still parses every suite row correctly.
ROSTER_KEY = "roster"

#: The live-subject probe. A command string, because that is what the injected runner takes.
BOARD_COMMAND = "fleet board --porcelain"

#: The two suites, as the working copy sees them.
HERMETIC_COMMAND = "python3 -m unittest discover -s tests -q"
IT_SCRIPT = ("fleet", "it", "run-all.sh")
#: The MERGED register — what a reader wants when a release cites "the IT evidence".
#: `RESULTS-closeout-all.tsv` holds ONLY the batch's own two ISOLATION rows, so citing that file shipped a
#: release whose proof was two lines about tmux and nothing about the 180 cases that ran.
IT_RESULTS = ("fleet", "it", "RESULTS.tsv")

#: Files the IT orchestrator leaves in the working copy that are worth keeping. Copied out BEFORE the copy
#: is removed, or the verdict cites evidence that no longer exists.
IT_ARTEFACTS = ("RESULTS-closeout-all.tsv", "SOURCE-PIN-group5-before.txt",
                "SOURCE-PIN-group5-after.txt", "FULL-RUN-closeout.log")


def verdict_for(hermetic_ok: bool, it_ok: bool, activity_changed: bool) -> str:
    """GREEN, RED or INCONCLUSIVE.

    A failure concurrent with operator activity is INCONCLUSIVE rather than RED. The IT suite baselines
    this box's live session set, so a coordinator starting or finishing mid-run can fail a section for
    reasons that have nothing to do with the release. Contamination is never a verdict: an INCONCLUSIVE
    costs a re-run, while a false RED is written into a release's evidence for good.

    Activity during a run that PASSED is not interesting -- nothing needs explaining.
    """
    if hermetic_ok and it_ok:
        return GREEN
    return INCONCLUSIVE if activity_changed else RED


def _cell(value) -> str:
    """One TSV field. A note quotes a suite's own output, which this module does not get to trust: one
    tab in it shifts every later column and the file still parses, into the wrong fields."""
    return " ".join(str("-" if value is None else value).split()) or "-"


def write_verdict(meta_dir, rows, roster: str) -> None:
    """The verdict file, inside the artifact's metadata directory.

    Published through `atomic_write` like every other record in this package: `release-promote` reads this
    file to decide whether a version may ship, and a half-written verdict is a promotion gate that answers
    from a prefix.
    """
    body = ["\t".join(VERDICT_COLUMNS)]
    body.extend("\t".join(_cell(cell) for cell in row) for row in rows)
    body.append(f"{ROSTER_KEY}\t{_cell(roster)}\t-\tthe set of IT runners this verdict covers")
    atomic_write(Path(meta_dir) / "evidence" / "VERDICT.tsv", "\n".join(body) + "\n")


def read_verdict(meta_dir) -> dict:
    """`{"suites": {name: verdict}, "roster": str}`, or `{}` when nothing has been verified.

    Empty rather than raising: "this release has no verdict" is the ordinary state of a fresh candidate
    and every reader has to handle it, so making it an exception only moves the branch.
    """
    path = Path(meta_dir) / "evidence" / "VERDICT.tsv"
    if not path.is_file():
        return {}
    suites, roster = {}, None
    for line in path.read_text().splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        if parts[0] == ROSTER_KEY:
            roster = parts[1]
        else:
            suites[parts[0]] = parts[1]
    return {"suites": suites, "roster": roster}


class Verify:
    """One verification of one release.

    `runner` is required and takes `(command, cwd, env) -> (rc, stdout, stderr)` -- `ctx.runner`, the seam
    the CLI already owns. There is deliberately no default: a module-level fallback would spawn processes
    from inside the package, which is the thing the injection exists to prevent.
    """

    def __init__(self, releases: Releases, version: Version, runner, repo=None):
        self.releases = releases
        self.version = version
        self.runner = runner
        self._repo_obj = repo

    # --- the repository the worktree comes from -------------------------------------------------------

    def repo(self):
        """The checkout to take the verification worktree from.

        `II-7`. The IT suite cannot judge an export: several cases assume a git working copy and nothing
        declares the dependency, so each discovers it separately and fails in a way indistinguishable
        from a product defect. `M13` asks `selftest` to notice a dirty path under `tests/`, which is a
        `git status --porcelain`; `git archive` writes no `.git`. So the suite runs in a worktree at the
        release's tag, and `check_copy_matches` proves that worktree is the artifact byte for byte.

        Resolution: whatever the caller injected, else `source_repo` from the MANIFEST. There is no
        fallback to the export and no inference from the working directory -- a release cut on this box
        records where it came from, and one cut before that field existed has to be told. REFUSED rather
        than quietly verified against the export, because verifying the export is exactly the state that
        produced a red `M13` and looked like a defect in `selftest`.
        """
        if self._repo_obj is None:
            from fleet.release_git import Repo
            recorded = self.releases.manifest(self.version).get("source_repo")
            if not recorded:
                raise Refused(
                    f"{self.version} does not record the checkout it was cut from, so there is nothing "
                    f"to take a verification worktree from. The IT suite cannot run against the export "
                    f"itself — several cases need a real `.git` — so verifying without a repository "
                    f"would certify a run that could never pass.",
                    clears_when="`release-verify --repo <checkout>` names the repository the tag lives "
                                "in, or the release is re-cut (a cut now records `source_repo`)",
                    clears_who="whoever is verifying")
            self._repo_obj = Repo(recorded)
        return self._repo_obj

    @property
    def export(self) -> Path:
        return self.releases.dir_for(self.version)

    @property
    def meta(self) -> Path:
        return self.export / META_DIR

    # --- the claim that what was tested is what shipped ---------------------------------------------

    def check_copy_matches(self, copy_root) -> None:
        """Refuse unless the tree about to be tested hashes to what the MANIFEST records."""
        recorded = self.releases.manifest(self.version).get("tree_sha")
        actual = tree_sha(copy_root)
        if recorded and recorded != actual:
            raise Refused(
                f"the tree being tested does not match the artifact: MANIFEST records {recorded[:12]}…, "
                f"the copy at {copy_root} hashes to {actual[:12]}…. Refused rather than reported as RED — "
                f"a mismatch here means the harness tested something other than the release, so the run "
                f"says nothing about the code.")

    # --- the pieces ----------------------------------------------------------------------------------

    def _evidence_dir(self) -> Path:
        """The evidence directory, made writable first.

        A cut freezes the whole release directory with `chmod -R a-w`, and `META_DIR` is inside it. That
        directory is deliberately excluded from `tree_sha` — it describes the release rather than being
        part of it — so it is the MUTABLE half of the artifact, and verdicts, state and evidence all land
        here after the payload is frozen. Widening it back is therefore restoring an invariant, not
        breaking one; the payload is never touched.
        """
        for path in (self.meta, self.meta / "evidence"):
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(path.stat().st_mode | 0o700)
        return self.meta / "evidence"

    def _live_subjects(self) -> str:
        """This box's live subject set, as text. Sampled either side of the run: if it moved, a failure
        may be somebody else's session rather than this release's defect."""
        code, out, _ = self.runner(BOARD_COMMAND)
        return out if code == 0 else ""

    def _worktree(self) -> Path:
        """A git worktree at the release's tag, under the releases root, at a name no other writer can
        produce.

        `II-7`. This replaced a writable `copytree` of the export. The copy had the right bytes and no
        `.git`, so every case that needs a working repository failed inside it and the failures were
        reported against the product. A worktree has both, and `check_copy_matches` proves the bytes.

        The name comes from `atomic.tmp_name` and NOT from the version. A staging path that is a function
        of the target alone is shared by every concurrent writer of that target, which is `FI-20`
        exactly: two verifies of one release would collide on the same worktree path, and git would
        refuse the second for a reason that reads as a defect in the release.

        The tag comes from the MANIFEST rather than from `version.tag`, so a release verifies against the
        tag it actually recorded even if the naming scheme changes later.
        """
        dest = self.releases.root / tmp_name(self.version.dirname)
        tag = self.releases.manifest(self.version).get("tag") or self.version.tag
        self.repo().worktree_add(tag, dest)
        return dest

    def _run_hermetic(self, evidence: Path) -> int:
        """The hermetic suite, in the export itself. Read-only is fine here and is the point: the suite
        that guards this package runs against bytes nothing can edit."""
        code, out, err = self.runner(
            HERMETIC_COMMAND,
            cwd=self.export / "fleet",
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                     PYTHONPATH=str(self.export / "fleet" / "src")))
        (evidence / "hermetic.log").write_text((out or "") + (err or ""))
        return code

    @staticmethod
    def _carry_cited_evidence(copy_root: Path, evidence: Path) -> list:
        """Copy every file a FAIL row CITES out of the worktree, before the worktree is removed.

        `QI-5`. A release carries the proof of every claim it makes, and a RED row is a claim. Release
        0.2.2's one FAIL row cited `it/E/out/E9-per-iteration.tsv` -- the table naming WHICH of twenty
        SIGKILL iterations leaked a lease -- and the release kept only the `RESULTS-*.tsv` registers. The
        worktree went, the file went with it, and the artifact recorded a failure while discarding the
        only thing that said what failed. The sole remaining route to a diagnosis was "re-run the suite
        and hope the flake recurs", which for a 1-in-20 defect is not a route.

        Same family as `SI-38`/`II-6`: a verdict whose cited evidence does not support it. There because
        nobody had opened the file; here because the file is gone.

        Only what FAILING rows cite, and only paths that resolve inside the worktree. Copying the whole
        tree would drag ~66 MB of IT output into every release, and following an absolute or `..` path
        would let a register's contents decide what this reads -- so both are refused, and refusing is
        reported rather than skipped.
        """
        it_dir = copy_root / IT_SCRIPT[0] / IT_SCRIPT[1]
        cited, carried = [], []
        for register in sorted(it_dir.glob("RESULTS-closeout-*.tsv")):
            for line in register.read_text(errors="replace").splitlines()[1:]:
                cells = line.split("\t")
                if len(cells) >= 3 and cells[1] == "FAIL" and cells[2].strip() not in ("", "-"):
                    cited.append(cells[2].strip())
        if not cited:
            return []
        root = copy_root.resolve()
        target = evidence / "it-cited"
        for rel in dict.fromkeys(cited):                 # de-duplicated, order kept
            #: The registers are relativised to the instant root by `sed` at the end of each runner, so a
            #: citation is `it/E/out/…` under `<root>/fleet`. Both spellings are tried and neither is
            #: allowed to escape.
            for base in (copy_root / IT_SCRIPT[0], copy_root):
                source = (base / rel)
                try:
                    resolved = source.resolve()
                except OSError:
                    continue
                if not str(resolved).startswith(str(root) + os.sep) or not resolved.is_file():
                    continue
                destination = target / resolved.relative_to(root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(resolved, destination)
                carried.append(str(resolved.relative_to(root)))
                break
        if carried:
            (evidence / "it-cited-INDEX.txt").write_text(
                "Evidence cited by a FAIL row, copied out of the verification worktree before it was\n"
                "removed (QI-5). Paths are relative to the worktree root, under it-cited/.\n\n"
                + "\n".join(carried) + "\n")
        return carried

    @staticmethod
    def it_failures(copy_root: Path) -> list:
        """Every FAIL row THIS run produced, read from the per-runner registers.

        Not from `run-all.sh`'s exit status. That script has no final `exit`: it prints its tallies and
        then falls off the end, so its status is whatever the last `say` returned — 0, always, however
        many sections failed. It is a REPORTING orchestrator, and a gate wired to its status reads GREEN
        over a suite with failures. Measured, on this pipeline's first real use: release 0.1.1 recorded
        GREEN while §A had 2 FAIL, group5 had 4 and m9mut had 1.

        Not from the merged `RESULTS.tsv` either, which KEEPS rows from the committed baseline for
        sections this roster did not run. Counting those would charge a release with another run's
        history. The `RESULTS-closeout-*.tsv` files are exactly what this invocation produced.
        """
        it_dir = copy_root / IT_SCRIPT[0] / IT_SCRIPT[1]
        failures = []
        for path in sorted(it_dir.glob("RESULTS-closeout-*.tsv")):
            for line in path.read_text(errors="replace").splitlines()[1:]:
                cells = line.split("\t")
                if len(cells) >= 2 and cells[1] == "FAIL":
                    failures.append(f"{cells[0]}[{path.stem.replace('RESULTS-closeout-', '')}]")
        return failures

    def _run_it(self, copy_root: Path, evidence: Path, full: bool) -> int:
        """The IT roster, in the working copy, with everything it produces copied back.

        Returns 0 only when the orchestrator exited 0 AND the run produced no FAIL row.
        """
        script = copy_root.joinpath(*IT_SCRIPT)
        command = f"bash {shlex.quote(str(script))}" + (" --full" if full else "")
        code, out, err = self.runner(
            command, cwd=copy_root,
            # PYTHONPATH is set rather than inherited. An inherited one aimed at the git checkout is the
            # one contamination the copy does not prevent by itself: the suite would run the copy's
            # scripts against the checkout's modules.
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                     PYTHONPATH=str(copy_root / "fleet" / "src")))
        (evidence / "it-FULL-RUN.log").write_text((out or "") + (err or ""))
        merged = copy_root.joinpath(*IT_RESULTS)
        if merged.is_file():
            shutil.copy(merged, evidence / "it-RESULTS.tsv")
        for name in IT_ARTEFACTS:
            candidate = copy_root / IT_SCRIPT[0] / IT_SCRIPT[1] / name
            if candidate.is_file():
                shutil.copy(candidate, evidence / f"it-{name}")
        # Every per-runner register, so a reader can see WHICH section failed without re-running anything.
        for path in sorted((copy_root / IT_SCRIPT[0] / IT_SCRIPT[1]).glob("RESULTS-closeout-*.tsv")):
            shutil.copy(path, evidence / f"it-{path.name}")

        failures = self.it_failures(copy_root)
        if failures:
            # `QI-5`. Before the worktree goes, take what the failures point at.
            self._carry_cited_evidence(copy_root, evidence)
            (evidence / "it-FAILURES.txt").write_text("\n".join(failures) + "\n")
            self._it_failures_seen = failures
            return code or 1
        self._it_failures_seen = []
        return code

    # --- the run -------------------------------------------------------------------------------------

    def run(self, full: bool = False) -> str:
        """Both suites, then the verdict. Returns GREEN, RED or INCONCLUSIVE."""
        evidence = self._evidence_dir()
        roster = FULL_ROSTER if full else GATE_ROSTER

        before = self._live_subjects()
        (evidence / "live-subjects-before.tsv").write_text(before)

        hermetic_code = self._run_hermetic(evidence)

        worktree = self._worktree()
        try:
            self.check_copy_matches(worktree)
            it_code = self._run_it(worktree, evidence, full)
        finally:
            # In a `finally` because the failure path — a tree that does not match the manifest — is the
            # path that fires when something is actually wrong, and leaving a registered worktree behind
            # exactly then blocks the NEXT verify of this version on git bookkeeping.
            #
            # This module no longer deletes anything itself: `git worktree remove` does the removal,
            # through the declared git seam. The `release_verify.run` entries in test_cli's
            # OUTWARD_CALL_SITES and run-group5.sh's DELETE_ALLOWLIST were removed with the copytree,
            # and §M9 now cross-checks both registries so dropping only one of them would fail (`II-3`).
            self.repo().worktree_remove(worktree)

        after = self._live_subjects()
        (evidence / "live-subjects-after.tsv").write_text(after)
        activity_changed = before != after

        result = verdict_for(hermetic_code == 0, it_code == 0, activity_changed)
        write_verdict(self.meta, [
            ("hermetic", GREEN if hermetic_code == 0 else RED, "evidence/hermetic.log",
             f"exit {hermetic_code}"),
            ("it", GREEN if it_code == 0 else RED, "evidence/it-RESULTS.tsv",
             f"exit {it_code}; "
             + (f"{len(self._it_failures_seen)} FAIL row(s): "
                f"{', '.join(self._it_failures_seen[:8])}"
                f"{' …' if len(self._it_failures_seen) > 8 else ''}; "
                if getattr(self, "_it_failures_seen", None) else "0 FAIL rows; ")
             + f"live-subject set "
             f"{'CHANGED during the run' if activity_changed else 'unchanged'}"),
        ], roster)
        return result
