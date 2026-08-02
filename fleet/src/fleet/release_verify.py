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

*The IT suite cannot run inside a read-only export* -- the orchestrator writes `RESULTS*.tsv` beside
itself. Rather than teach twenty runner scripts an output directory, the suite runs in a WORKING COPY, the
results are copied back into the artifact's evidence, and `tree_sha` is recomputed on the copy so that
"what was tested is what shipped" is asserted rather than assumed.
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

    def __init__(self, releases: Releases, version: Version, runner):
        self.releases = releases
        self.version = version
        self.runner = runner

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

    def _working_copy(self) -> Path:
        """A writable copy of the export, under the releases root, at a name no other writer can produce.

        The name comes from `atomic.tmp_name` and NOT from the version. A staging path that is a function
        of the target alone is shared by every concurrent writer of that target, which is `FI-20` exactly:
        two verifies of one release would collide, and the first to finish would delete the tree the
        second is still testing in.
        """
        copy_root = self.releases.root / tmp_name(self.version.dirname)
        shutil.copytree(self.export, copy_root, symlinks=True)
        # The export is a-w, and `copytree` preserves that — including on DIRECTORIES, which is what
        # actually stops the orchestrator writing RESULTS beside itself. Owner-write is added back to
        # every entry; the executable bit is untouched, so `tree_sha` still agrees with the manifest.
        for path in [copy_root] + sorted(copy_root.rglob("*")):
            if not path.is_symlink():
                path.chmod(path.stat().st_mode | 0o200)
        return copy_root

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

        copy_root = self._working_copy()
        try:
            self.check_copy_matches(copy_root)
            it_code = self._run_it(copy_root, evidence, full)
        finally:
            # The one delete in this module, registered in test_cli's OUTWARD_CALL_SITES. It is in a
            # `finally` because the failure path — a copy that does not match the manifest — is the path
            # that fires when something is actually wrong, and leaving a full copy of the release behind
            # exactly then is how a releases root fills a disk.
            shutil.rmtree(copy_root, ignore_errors=True)

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
