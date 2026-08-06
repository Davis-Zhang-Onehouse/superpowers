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
from fleet.release_scope import (CUT_MANIFESTS, CUT_STAMPED, Scope, classify, without_version_field,
                                 without_version_line)

__all__ = ["EXEMPT", "EXEMPT_ROSTER", "FULL_ROSTER", "GATE_ROSTER", "GREEN", "INCONCLUSIVE",
           "PROMOTABLE", "RED", "Verify", "archive_previous_attempt", "exemption_for", "last_green",
           "read_verdict", "verdict_for", "write_exemption", "write_verdict"]

GREEN = "GREEN"
RED = "RED"
INCONCLUSIVE = "INCONCLUSIVE"
#: The suites were not REQUIRED, which is a different claim from "they passed", and is never spelled
#: GREEN. `SI-38` is what a verdict whose evidence does not support it costs; recording a skipped run as a
#: pass would reproduce that in a new place. A reader must always be able to tell the two apart.
EXEMPT = "EXEMPT"

#: The verdicts `release-promote` accepts. A set rather than a comparison against GREEN, so adding a
#: fourth verdict later is a decision made here rather than an accident of an `!=` somewhere in the CLI.
PROMOTABLE = frozenset({GREEN, EXEMPT})

GATE_ROSTER = "gate"
FULL_ROSTER = "full"
EXEMPT_ROSTER = "exempt"

VERDICT_COLUMNS = ("suite", "verdict", "evidence", "note")

#: The row that carries the roster. A key rather than a header field, so a reader that does not know about
#: rosters still parses every suite row correctly.
ROSTER_KEY = "roster"

#: The row that carries the run's OVERALL verdict, which the per-suite rows cannot express.
#:
#: `RI-16`, measured on release `0.3.4`: its `it` row reads RED with the note "live-subject set CHANGED
#: during the run", so `verdict_for(True, False, True)` -- INCONCLUSIVE -- is what `run()` returned, while
#: the file it left is byte-identical to a genuine RED's. The verdict that exists precisely so a false RED
#: is never written into a release's evidence permanently had nowhere to be written.
#:
#: A key row like `ROSTER_KEY`, for the same reason: a reader that predates it still parses every suite row
#: correctly, and `read_verdict` keeps it out of `suites` so `promote` never gates on a value that is not a
#: suite's verdict.
VERDICT_KEY = "verdict"

#: Where a superseded attempt goes. The prefix is what `archive_previous_attempt` recognises as "already
#: archived", so it is named once here rather than spelled in three places that must agree.
ATTEMPT_PREFIX = "attempt-"

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


def write_verdict(meta_dir, rows, roster: str, result: str = None) -> None:
    """The verdict file, inside the artifact's metadata directory.

    Published through `atomic_write` like every other record in this package: `release-promote` reads this
    file to decide whether a version may ship, and a half-written verdict is a promotion gate that answers
    from a prefix.

    `result` is the run's OVERALL verdict (`VERDICT_KEY`) and is optional only so a caller with nothing to
    say -- a test writing suite rows in isolation -- is not forced to invent one. Every real writer passes
    it: without it an INCONCLUSIVE run is indistinguishable from a RED one, and the archive of a superseded
    attempt has no true name to take.
    """
    body = ["\t".join(VERDICT_COLUMNS)]
    body.extend("\t".join(_cell(cell) for cell in row) for row in rows)
    body.append(f"{ROSTER_KEY}\t{_cell(roster)}\t-\tthe set of IT runners this verdict covers")
    if result is not None:
        body.append(f"{VERDICT_KEY}\t{_cell(result)}\t-\tthe run's overall verdict, which the per-suite "
                    f"rows cannot express (an INCONCLUSIVE run leaves RED suite rows)")
    atomic_write(Path(meta_dir) / "evidence" / "VERDICT.tsv", "\n".join(body) + "\n")


def read_verdict(meta_dir) -> dict:
    """`{"suites": {name: verdict}, "roster": str, "result": str|None}`, or `{}` when nothing has been
    verified.

    Empty rather than raising: "this release has no verdict" is the ordinary state of a fresh candidate
    and every reader has to handle it, so making it an exception only moves the branch.

    `result` is `None` for every release cut before `VERDICT_KEY` existed. Absent is not a verdict, and a
    caller that needs a label for such an attempt says `unknown` rather than guessing one from the suite
    rows -- which is exactly how an INCONCLUSIVE run would acquire a permanent RED.
    """
    path = Path(meta_dir) / "evidence" / "VERDICT.tsv"
    if not path.is_file():
        return {}
    suites, roster, result = {}, None, None
    for line in path.read_text().splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        if parts[0] == ROSTER_KEY:
            roster = parts[1]
        elif parts[0] == VERDICT_KEY:
            result = parts[1]
        else:
            suites[parts[0]] = parts[1]
    return {"suites": suites, "roster": roster, "result": result}


def archive_previous_attempt(meta_dir):
    """Move whatever a previous attempt left in `evidence/` into `evidence/attempt-<n>-<verdict>/`.

    Returns the archive directory, or `None` when there was nothing to archive.

    `RI-9` and `RI-11`, which are one defect seen from two sides. The evidence directory is addressed by
    constant filenames -- `hermetic.log`, `it-RESULTS.tsv`, `VERDICT.tsv` -- so a second attempt overwrites
    the first WHERE THE TWO HAPPEN TO WRITE THE SAME FILE and inherits it everywhere else. Release `0.3.3`
    shipped RELEASED holding an `it-cited/` file stamped 05:10, an `it-FAILURES.txt` stamped 05:37 naming
    two failures, and a `VERDICT.tsv` stamped 06:07 recording `0 FAIL rows` -- three attempts in one
    directory, and the only file naming a failure thirty minutes older than the verdict denying it.

    Archiving FIRST is what makes both go away, and the second one goes away without a line of code:
    `it-FAILURES.txt` and `it-cited/` are written only on the failure path and cleared on neither, but a
    run that starts in an empty directory cannot inherit what is no longer there. A remembered `else:
    unlink` would be a second thing to keep correct; an empty directory is a property.

    Deliberately a MODULE-LEVEL function and not a step inside `Verify._evidence_dir`. The exempt path
    writes this same directory from the CLI without constructing a `Verify` at all, and release `0.3.6` --
    RELEASED, verdict EXEMPT -- ships a `hermetic.log` from an abandoned earlier attempt because of it
    (`RI-17`). A fix reachable from only one of the two writers would have looked complete and left the
    newer one destroying evidence.

    Nothing is deleted, here or anywhere downstream: this is a rename within one directory. The freeze a
    cut applies covers the payload and never `META_DIR` (`_freeze_payload`), but the mode is widened anyway
    for the same reason `_evidence_dir` does it -- restoring the invariant that the metadata half is
    writable, rather than assuming it.
    """
    evidence = Path(meta_dir) / "evidence"
    if not evidence.is_dir():
        return None
    evidence.chmod(evidence.stat().st_mode | 0o700)

    existing = sorted(evidence.iterdir(), key=lambda path: path.name)
    archives = [path for path in existing if path.is_dir() and path.name.startswith(ATTEMPT_PREFIX)]
    #: Everything that is NOT already an archive. Filtering by the prefix rather than by mtime or by a
    #: manifest is what stops the archive nesting: run three would otherwise move `attempt-1-RED/` inside
    #: `attempt-2-…/`, burying attempt one a directory deeper on every subsequent verify.
    loose = [path for path in existing if path not in archives]
    if not loose:
        return None

    verdict = (read_verdict(meta_dir).get("result") or "unknown")
    destination = evidence / f"{ATTEMPT_PREFIX}{len(archives) + 1}-{_cell(verdict)}"
    destination.mkdir(parents=True, exist_ok=True)
    for path in loose:
        path.rename(destination / path.name)
    return destination


def last_green(releases: Releases, version: Version):
    """The newest release below `version` whose recorded verdict is entirely GREEN, or None.

    The ANCHOR for an exemption. An `EXEMPT` release is deliberately not an anchor: chaining exemptions
    off each other would let a run of docs-only releases drift arbitrarily far from anything a suite ever
    saw. Anchoring each one to the last release that actually PASSED keeps the guarantee flat -- an exempt
    release's `fleet/` tree is byte-identical to verified code, however many exempt releases precede it.

    Nor is the immediate predecessor an anchor, which is the other tempting answer: `0.3.2` was a
    CANDIDATE that had been deployed with the gate skipped, and anchoring to it would have inherited
    exactly the unverified state this pipeline exists to prevent.
    """
    for candidate in reversed([v for v in releases.versions() if v < version]):
        suites = (read_verdict(releases.dir_for(candidate) / META_DIR).get("suites") or {})
        if suites and all(value == GREEN for value in suites.values()):
            return candidate
    return None


def exemption_for(releases: Releases, version: Version, repo, full: bool = False):
    """`(anchor, scope)` when the suites are not required for this release, else `None`.

    Returns None -- meaning "run them" -- for every uncertainty, never a guess:

      * `--full` was asked for. An operator who names the full roster gets the full roster.
      * no GREEN release exists to anchor against, so there is nothing to claim identity with.
      * the anchor's tag is gone from the checkout, so the diff cannot be computed. `changed_paths`
        raises rather than returning empty, and that refusal is allowed to propagate: a release skipping
        its suites because a git command quietly failed is the one outcome worth crashing over.
      * any changed path is not in the declared inert set (`release_scope`).
    """
    if full:
        return None
    anchor = last_green(releases, version)
    if anchor is None:
        return None
    anchor_tag = (releases.manifest(anchor).get("tag") or anchor.tag)
    this_tag = (releases.manifest(version).get("tag") or version.tag)
    if not repo.tag_exists(anchor_tag):
        raise Refused(
            f"the anchor for an exemption check is {anchor} and its tag {anchor_tag} is not in "
            f"{repo.path}. Whether {version} may skip the suites is decided by diffing those two tags, so "
            f"a missing one means the question cannot be answered -- and 'cannot answer' must never read "
            f"as 'nothing changed'.",
            clears_when=f"{anchor_tag} is back in the checkout (`git fetch --tags`), or the release is "
                        f"verified normally",
            clears_who="whoever is verifying")
    changed = repo.changed_paths(anchor_tag, this_tag)
    scope = classify(changed)

    #: `classify` reads the version-stamped `__init__.py` as inert because it cannot see contents -- the
    #: cut rewrites that file on EVERY release, so treating it as an ordinary `fleet/` path would make
    #: exemption unreachable. Contents are the other half of the question, and they are checked here,
    #: where the repository is. Anything in that file other than `__version__` moving puts it back in
    #: `requiring`, so an edit to the exit-code registry it also carries can never ride out on a stamp.
    #: One list of (path, how to strip its version) so the two families are checked by the same loop.
    #: `CUT_STAMPED` is a Python module whose version is an assignment; a `CUT_MANIFEST` is JSON whose
    #: version is a field. Everything else about the question is identical, and writing it twice is how
    #: the second family would later acquire a check the first has and the other does not.
    stamped = [(CUT_STAMPED, without_version_line)]
    stamped += [(path, without_version_field) for path in CUT_MANIFESTS]
    put_back = []
    for path, strip in stamped:
        if path not in scope.inert:
            continue
        if strip(repo.file_at(anchor_tag, path)) != strip(repo.file_at(this_tag, path)):
            put_back.append(path)
    if put_back:
        scope = Scope([p for p in scope.inert if p not in put_back],
                      list(scope.requiring) + put_back)
    return (anchor, scope) if scope.exempt else None


def write_exemption(meta_dir, version: Version, anchor: Version, anchor_tag: str, this_tag: str,
                    scope) -> None:
    """The evidence an exempt promotion cites, in place of a test run.

    The gate's rule is that a promotion always cites a measurement someone can go and look at. An
    exemption keeps that rule -- the measurement is the diff -- so every changed path is written out with
    its classification, and the two tags are named, so the decision can be re-derived by hand with one
    `git diff --name-only`.
    """
    rows = [f"key\tvalue",
            f"version\t{version}",
            f"anchor\t{anchor}",
            f"anchor_tag\t{anchor_tag}",
            f"compared\t{anchor_tag}..{this_tag}",
            f"paths_changed\t{len(scope.inert) + len(scope.requiring)}"]
    rows.extend(f"path\t{path}\tinert" for path in scope.inert)
    #: Empty by construction on this path -- written anyway, so the file's shape does not depend on the
    #: outcome and a reader never has to wonder whether the section was omitted or was genuinely empty.
    rows.extend(f"path\t{path}\trequiring" for path in scope.requiring)
    atomic_write(Path(meta_dir) / "evidence" / "EXEMPTION.tsv", "\n".join(rows) + "\n")


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
        #: BEFORE anything is written. `RI-9`/`RI-11`: this attempt has to start from an empty directory,
        #: or it overwrites the previous one where their filenames collide and inherits it where they do
        #: not -- which is how a GREEN release came to ship a failure manifest naming two failures.
        archive_previous_attempt(self.meta)
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
        ], roster, result=result)
        return result
