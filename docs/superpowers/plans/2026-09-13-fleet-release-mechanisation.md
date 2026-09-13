# Fleet Release Mechanisation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the fleet release traps that are mechanically checkable into checks — a live `EXEMPT` path, three verb fixes, and three scripts — and leave the rest as prose on purpose.

**Architecture:** Every fact the verb can see becomes a refusal or a printed row inside the verb (F1–F4). Only what lives outside the verb's world — how the operator assembled the command, the box's other roots, the deployed symlink topology — becomes a wrapper script (F5–F8). Scripts are bash in `scripts/`, each with a test in `scripts/tests/`, matching `fleet-view.sh` and `fleet-finished-pids.sh`.

**Tech Stack:** python3 stdlib only (`fleet/`), bash (`scripts/`), `unittest` (`fleet/tests/`).

**Spec:** `docs/superpowers/specs/2026-09-13-fleet-release-mechanisation-design.md` — read it first; every task below argues from a numbered section of it.

## Global Constraints

- `fleet/` is **python3 stdlib only**. No third-party import, ever, including in tests.
- `release_scope.py` is a **leaf with no filesystem** — a pure function of a list of strings. F1's change is a regex and must not make the module read a file.
- Scripts are bash, must pass `bash scripts/lint-shell.sh <file>`, and each gets a test under `scripts/tests/`.
- Citation comments (`SI-`, `FI-`, `RI-`, `MI-`, `OBS-`, `MD-`) are load-bearing. **A comment a change falsifies is amended with the measurement, never deleted.**
- No script may mutate a release, move `current`, or delete anything outside the `.fleet-v*.tmp` name pattern.
- Porcelain columns are a contract: **append** new columns, never insert, so `cut -fN` keeps meaning what it meant.
- `scripts/` is not in the inert allowlist, so this release runs the full gate. Correct; not to be "fixed".
- Run hermetic tests with `cd fleet && python3 -m unittest discover -s tests -t . -q`.
- Never pipe a control (`fleet/CLAUDE.md:173-174`): a pipeline's exit status is the last stage's.

---

### Task 1: The exemption stripper must match what the stamper writes

**Spec:** F1. This is the highest-value item — the `EXEMPT` path has never fired in ten releases.

**Files:**
- Modify: `fleet/src/fleet/release_scope.py:81-83` (`_VERSION_FIELD`) and the docstring of `without_version_field:95-104`
- Test: `fleet/tests/test_release_payload.py` (add the round-trip test near the existing `without_version_field` cases at `:212`/`:219`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `without_version_field(text: str) -> str` — unchanged signature, widened behaviour. `exemption_for` in `release_verify.py:280` already calls it for every `CUT_MANIFESTS` entry; **do not change that call site.**

- [ ] **Step 1: Write the failing test**

Add to `fleet/tests/test_release_payload.py`. This is a round trip over the whole family, not a YAML test — a future manifest with a spelling the stripper does not understand must fail on the day it is added to `.version-bump.json`:

```python
    def test_every_stamped_manifest_survives_its_own_stamp(self):
        """`exemption_for` asks each CUT_MANIFEST "did anything OTHER than the version change", and it
        asks by stripping. A stripper that does not understand a manifest's spelling answers "yes" on
        every release, which makes EXEMPT unreachable -- SI-19's shape, and what the JSON-only
        `_VERSION_FIELD` did to `.hermes-plugin/plugin.yaml` for ten releases (0.5.2..0.5.11 have no
        EXEMPTION.tsv between them). Asserted over the FAMILY so the next manifest cannot repeat it."""
        repo = Path(__file__).resolve().parents[2]
        for relative in CUT_MANIFESTS:
            path = repo / relative
            if not path.is_file():
                continue  # `.version-bump.json` lists every harness ever shipped for; absence is ordinary
            with self.subTest(manifest=relative):
                scratch = Path(self.tmp) / relative
                scratch.parent.mkdir(parents=True, exist_ok=True)
                scratch.write_text(path.read_text())
                before = scratch.read_text()
                moved = stamp_plugin_version(self.tmp, "9.9.9")
                self.assertTrue(any(row[0] == relative for row in moved),
                                f"{relative} was not stamped, so this asserts nothing")
                after = scratch.read_text()
                self.assertNotEqual(before, after, f"{relative} did not move")
                self.assertEqual(without_version_field(before), without_version_field(after),
                                 f"{relative}: the stripper cannot undo the stamper, so every release "
                                 f"puts this file back into `requiring` and EXEMPT is unreachable")
```

Set up `self.tmp` in `setUp` as a `tempfile.TemporaryDirectory()` holding a copy of the repo's `.version-bump.json` (the stamper reads it via `declared_version_files(root)`), and import `CUT_MANIFESTS`, `without_version_field` from `fleet.release_scope` and `stamp_plugin_version` from `fleet.release_stamp`.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd fleet && python3 -m unittest tests.test_release_payload -v 2>&1 | tail -20`
Expected: FAIL on `manifest='.hermes-plugin/plugin.yaml'` with "the stripper cannot undo the stamper".

- [ ] **Step 3: Widen the regex to mirror the stamper**

Replace `_VERSION_FIELD` at `release_scope.py:81-83`. The comment must record *why* this shape, because the shape is copied from another module:

```python
#: `version: …` as a whole line, however the manifest spells it. Mirrors `release_stamp._rewrite`'s
#: pattern deliberately: the quotes are optional and the closing one is back-referenced to the opening
#: one, so `"version": "6.2.0"` and a YAML `version: 6.2.0` are both matched and a half-quoted value by
#: neither. That module is the WRITE half of this question and had it right from the start; this one was
#: JSON-only, so `.hermes-plugin/plugin.yaml` (a CUT_MANIFEST since upstream 6.3.0) was put back into
#: `requiring` on every cut and no release from 0.5.2 to 0.5.11 could be EXEMPT. Kept as ONE pattern
#: rather than a per-suffix dispatch: a dispatch is a second place for the manifest list to acquire a
#: family the other half does not know about, which is the defect being fixed.
_VERSION_FIELD = re.compile(
    r'^[ \t]*"?version"?[ \t]*:[ \t]*(?P<q>["\']?)[^"\']*(?P=q)[ \t]*,?[ \t]*$', re.MULTILINE)
```

Amend `without_version_field`'s docstring: it says "one JSON manifest" and "The JSON counterpart"; both are now false. Say it handles any manifest whose version is a whole `version:` line, and keep the reason sentence.

- [ ] **Step 4: Run the test to verify it passes, then the full hermetic suite**

Run: `cd fleet && python3 -m unittest tests.test_release_payload tests.test_release_scope tests.test_release_exemption -v 2>&1 | tail -20`
Expected: PASS.
Then: `cd fleet && python3 -m unittest discover -s tests -t . -q 2>&1 | tail -5`
Expected: `OK`. **If any test fails, stop and report** — a widened regex that strips a line it should not is a release that skips its gate wrongly.

- [ ] **Step 5: Prove the defect is actually gone end to end**

Run, from the repo root:
```bash
python3 - <<'EOF'
import sys; sys.path.insert(0, "fleet/src")
from pathlib import Path
from fleet.release_scope import CUT_MANIFESTS, without_version_field
for rel in CUT_MANIFESTS:
    p = Path(rel)
    if not p.is_file(): continue
    line = [l for l in p.read_text().splitlines() if "version" in l][:1]
    print(rel, "->", "STRIPPED" if without_version_field("\n".join(line)).strip() == "" else "KEPT " + repr(line))
EOF
```
Expected: every manifest prints `STRIPPED`. Paste the output into your report.

- [ ] **Step 6: Commit**

```bash
git add fleet/src/fleet/release_scope.py fleet/tests/test_release_payload.py
git commit -m "fix: the exemption stripper must match what the cut's stamper writes"
```

---

### Task 2: `release-verify --dry-run` reports the exemption decision

**Spec:** F2.

**Files:**
- Modify: `fleet/src/fleet/cli.py:4508-4548` (`_do_release_verify`)
- Test: `fleet/tests/test_release_exemption.py`

**Interfaces:**
- Consumes: Task 1's widened stripper (a dry run on a skills-only release must now print `would-exempt`, which is only reachable once Task 1 lands).
- Produces: two new dry-run row shapes on the `release-verify` KV emit — `("would-exempt", str(anchor))` and `("requiring", path)` (one row per path). `would-verify` and `dry-run` rows are unchanged.

- [ ] **Step 1: Write the failing tests**

Two cases in `fleet/tests/test_release_exemption.py`, following the fixture style already there:

```python
    def test_dry_run_names_the_paths_that_force_the_suites(self):
        """The dry run's only job is to report the decision, and `would-run the gate roster` prints
        identically for an exempt release -- which is how a skills-only 0.5.11 cost a 45-minute run
        before anyone learned it was `.hermes-plugin/plugin.yaml` that forced it."""
        out = self.verify_dry_run(changed=["fleet/src/fleet/cli.py", "docs/x.md"])
        self.assertIn(("would-run", "the gate roster"), out)
        self.assertIn(("requiring", "fleet/src/fleet/cli.py"), out)
        self.assertNotIn(("requiring", "docs/x.md"), out)

    def test_dry_run_names_the_anchor_when_it_would_exempt(self):
        out = self.verify_dry_run(changed=["docs/x.md"])
        self.assertIn(("would-exempt", str(self.anchor)), out)
        self.assertNotIn(("would-run", "the gate roster"), out)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd fleet && python3 -m unittest tests.test_release_exemption -v 2>&1 | tail -20`
Expected: FAIL — the dry run returns before `exemption_for` is reached.

- [ ] **Step 3: Hoist the exemption check above the dry-run block**

In `_do_release_verify`, move the `scope_repo = …` / `exempted = exemption_for(…)` pair (currently `cli.py:4541-4543`) to **before** `if ctx.dry_run:`, and replace the dry-run emit with:

```python
    #: The exemption decision is computed BEFORE the dry-run return, because reporting it is the one
    #: thing a dry run is asked for and `would-run the gate roster` prints identically either way --
    #: which is how 0.5.11 read the roster line as a decision and went looking in `release_scope` by
    #: hand. Pure with respect to the release area: a `git diff --name-only` between two tags plus a
    #: `git show` on at most ten files, no spawns and no writes, so a dry run stays a dry run.
    #: A `Refused` from `exemption_for` PROPAGATES here on purpose -- a dry run that swallowed the
    #: missing-anchor refusal would report a release as verifiable when the question cannot be asked.
    if ctx.dry_run:
        rows = [("dry-run", "no suite was run and no evidence was written"),
                ("would-verify", f"{version} at {export}")]
        if exempted is not None:
            anchor, scope = exempted
            rows.append(("would-exempt", str(anchor)))
            rows += [("inert", path) for path in scope.inert]
        else:
            rows.append(("would-run", f"the {roster} roster"))
            rows += [("requiring", path) for path in _requiring_paths(rel, version, scope_repo, parsed)]
        _emit(ctx, "release-verify", rows)
        return EXIT_OK
```

Rather than a second helper that recomputes the diff, have `exemption_for` remain the single source: capture the `Scope` it built. Simplest honest shape — return the scope alongside the decision from a small local:

```python
def _exemption_and_scope(rel, version, repo, full: bool):
    """`(exempted, scope)` — the decision and the scope it was decided from.

    `exemption_for` answers only the decision, and the dry run needs the REASON: which paths landed in
    `requiring`. Computing the scope twice would be two `git diff`s that could disagree.
    """
```
Put it in `release_verify.py` beside `exemption_for`, export it, and have `exemption_for` delegate to it so there is exactly one classifier call. Do **not** duplicate the classify logic.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd fleet && python3 -m unittest tests.test_release_exemption tests.test_cli -v 2>&1 | tail -20`
Expected: PASS.
Then the full hermetic suite: `cd fleet && python3 -m unittest discover -s tests -t . -q 2>&1 | tail -5` → `OK`.

- [ ] **Step 5: Commit**

```bash
git add fleet/src/fleet/cli.py fleet/src/fleet/release_verify.py fleet/tests/test_release_exemption.py
git commit -m "fix: release-verify --dry-run reports the exemption decision it already computes"
```

---

### Task 3: `release-list` carries the verdict; `release-cut` warns on live box work

**Spec:** F3 and F4. Two small verb changes, one commit each.

**Files:**
- Modify: `fleet/src/fleet/cli.py:274` (`RELEASE_COLUMNS`), `:4760-4766` (`_do_release_list`), `:5143` (the verb's one-line description), `:4370…` (`_do_release_cut`)
- Test: `fleet/tests/test_release.py` and `fleet/tests/test_cli.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `RELEASE_COLUMNS = ("version", "state", "cut_at", "current", "verdict")` — **appended, never inserted**, so `cut -f1..4` keeps meaning what it meant.

- [ ] **Step 1: Write the failing test for the verdict column**

```python
    def test_release_list_tells_an_abandoned_candidate_from_an_unverified_one(self):
        """Four situations collapse into the word CANDIDATE -- cut and abandoned RED, cut and never
        verified, GREEN awaiting promote, and a verify killed mid-flight. 0.5.9 (RED) and 0.5.11 (no
        VERDICT.tsv at all) were indistinguishable on this box, which is what a stale-candidate report
        would have existed to say; the column says it instead."""
        ...  # cut two releases, write a RED verdict for one, leave the other without one
        rows = self.run_porcelain("release-list")
        self.assertEqual(self.cell(rows, "0.5.9", "verdict"), "RED")
        self.assertEqual(self.cell(rows, "0.5.11", "verdict"), "-")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd fleet && python3 -m unittest tests.test_release -v 2>&1 | tail -20`
Expected: FAIL — there is no `verdict` column.

- [ ] **Step 3: Add the column**

`RELEASE_COLUMNS = ("version", "state", "cut_at", "current", "verdict")`, and in `_do_release_list`:

```python
         (str(version), rel.state(version), rel.manifest(version).get("cut_at", "-"),
          "*" if str(version) == current else "",
          read_verdict(rel.dir_for(version) / META_DIR).get("result") or "-")
```

`read_verdict` is already imported in `cli.py` (used at `:4580`). Update the verb's description at `:5143` from "every release, its state and its cut time" to include the verdict.

- [ ] **Step 4: Run to verify it passes**

Run: `cd fleet && python3 -m unittest tests.test_release tests.test_cli -q 2>&1 | tail -5`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add fleet/src/fleet/cli.py fleet/tests/test_release.py
git commit -m "feat: release-list carries each release's verdict"
```

- [ ] **Step 6: Write the failing test for the cut's live-work note**

```python
    def test_release_cut_says_when_the_box_has_live_work(self):
        """`ctx.live_work_now()` was called in exactly one place, `_do_release_verify`. The CUT is the
        earlier and more expensive decision -- a cut you regret costs a version number and a tag that is
        never moved -- and it asked nobody. A NOTE, not a refusal: other roots' sessions are an
        uncontrollable residual on a shared box and refusing on them would make releases impossible."""
        ctx = self.ctx_with_live_work()
        rc = self.cut(ctx, version="0.9.9")
        self.assertEqual(rc, EXIT_OK)
        self.assertIn("live fleet work", ctx.err.getvalue())
```

- [ ] **Step 7: Run to verify it fails, then add the note**

In `_do_release_cut`, before the cut proceeds, emit the same note `_do_release_verify` emits at `cli.py:4522` — same text, same `ctx.err`. Factor the two into one small helper (`_note_live_work(ctx)`) so the wording cannot drift between the two call sites; give it the reason as a comment.

- [ ] **Step 8: Run the full hermetic suite and commit**

Run: `cd fleet && python3 -m unittest discover -s tests -t . -q 2>&1 | tail -5` → `OK`

```bash
git add fleet/src/fleet/cli.py fleet/tests/test_release.py
git commit -m "feat: release-cut warns when the box has live fleet work"
```

---

### Task 4: `scripts/release-gate.sh` — launch and wait, correctly, once

**Spec:** F5. Four incidents in one session; three destroyed a gate run.

**Files:**
- Create: `scripts/release-gate.sh`
- Test: `scripts/tests/release-gate.sh`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: exit 0 GREEN/EXEMPT, 1 RED/INCONCLUSIVE, 2 usage/environment, 3 did-not-finish.

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
#
# Run the release gate for one version, once, and report its verdict.
#
# Usage:  scripts/release-gate.sh <version> [--full]
#
# Exists because four separate gate runs were lost or misread in one session, and not one of them was a
# property of the gate:
#   * `release-verify … | tail -40` reported EXIT 0 for a run that never wrote a VERDICT.tsv -- a
#     pipeline's exit status is the last stage's (fleet/CLAUDE.md "never pipe a control"), so a dead run
#     became indistinguishable from a finished gate.
#   * a waiter with a fixed iteration cap reported "NO VERDICT FILE" over a run that was healthy and
#     mid-flight. The gate measures ~45 min here, against the ~24 the skill used to quote.
#   * `nohup … &` inside a harness background task stays in that task's process group, so stopping the
#     task signalled the group and took the run with it. `setsid` is what detaches.
#   * `timeout 300` was a guess about a duration the operator did not know. rc=124.
#
# It runs the gate ONCE. Re-running is a separate human invocation, on purpose: a gate you retry until
# it passes is not a gate.
set -uo pipefail
```

Body requirements, each traceable to an incident:

- resolve `REPO` from `$0`, source `scripts/fleet-env.sh`, and use `"$REPO/bin/fleet"` by absolute path (never `$PATH`, never `current/bin/fleet`);
- refuse with exit 2 if `$1` is missing, if `$REPO/bin/fleet` is not executable, or if the release directory for the version does not exist;
- launch **exactly**:
  ```bash
  setsid nohup "$FLEET" release-verify --version "$V" --releases "$R" $FULL \
      > "$LOG" 2>&1 < /dev/null &
  pid=$!
  echo "$pid" > "$PIDFILE"
  ```
  No pipe anywhere in that line. No `timeout`.
- wait on the **disjunction, unbounded**:
  ```bash
  while [ ! -f "$EV/VERDICT.tsv" ] && kill -0 "$pid" 2>/dev/null; do sleep 30; done
  ```
- classify three outcomes:
  - `VERDICT.tsv` exists → print the `verdict` row, then FAIL rows from the **per-runner** files:
    ```bash
    awk -F'\t' '$2=="FAIL"{print FILENAME" :: "$1" :: "$4}' "$EV"/it-RESULTS-closeout-*.tsv
    ```
    (never the merged `it-RESULTS.tsv` — it does not carry the runner). Exit 0 for `GREEN`/`EXEMPT`, 1 otherwise.
  - pid gone, no verdict → print `hermetic.log`'s size and mtime and the last 20 lines of `$LOG`, then **exit 3**. That is Trap 8's checklist executed rather than remembered.
- print the log path and pid on launch so a detached run is findable.

- [ ] **Step 2: Write the test**

`scripts/tests/release-gate.sh`, house pattern (`set -uo pipefail`, `HERE`/`REPO`, `check`, `fails`). Assert the properties that would make the script's argument false — **using a stub `fleet` on `PATH`-free absolute override**, never a real 45-minute gate:

- a verdict of `GREEN` → exit 0; `RED` → exit 1; **no `VERDICT.tsv` and the stub exits → exit 3** (this is the one the pipe hid);
- FAIL rows are read from `it-RESULTS-closeout-*.tsv` and a FAIL present only in a merged `it-RESULTS.tsv` is **not** reported;
- `grep -c '|' scripts/release-gate.sh` finds no pipe on the launch line — assert directly that the line containing `release-verify` contains no `|`;
- the launch line contains `setsid`;
- a missing version argument exits 2.

- [ ] **Step 3: Run the test and the linter**

Run: `bash scripts/tests/release-gate.sh` → every line `ok`, no `FAIL`.
Run: `bash scripts/lint-shell.sh scripts/release-gate.sh scripts/tests/release-gate.sh` → clean.

- [ ] **Step 4: Commit**

```bash
git add scripts/release-gate.sh scripts/tests/release-gate.sh
git commit -m "feat: scripts/release-gate.sh — launch the gate detached, unpiped, and wait on the verdict"
```

---

### Task 5: `scripts/release-preflight.sh` — the box, through the derived socket, plus the orphan reaper

**Spec:** F6 and F7. 156 MB of orphaned worktrees exist on this box right now.

**Files:**
- Create: `scripts/release-preflight.sh`
- Test: `scripts/tests/release-preflight.sh`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: exit 0 with `WARN:` lines (advisory), exit 2 for the one hard refusal.

- [ ] **Step 1: Write the script**

Header comment must carry the measurement, because the mistake it prevents looked exactly like success:

```bash
#!/usr/bin/env bash
#
# Report what would make this a bad moment to cut a release. Advisory: exit 0 with WARN lines.
#
# Usage:  scripts/release-preflight.sh [--reap]
#
# The check this replaces was `tmux -L fleet ls; tmux ls`, which printed "error connecting to
# /tmp/tmux-1000/fleet" and was read as a quiet box. It was not quiet: `release-verify` printed "this box
# has live fleet work" on all three of its runs that day, and the live session was on `fleet-davis2`.
# The socket is DERIVED PER ROOT (`fleet-env.sh`: FLEET_TMUX_SOCKET=fleet-$name) and that file
# deliberately UNSETS a socket named literally `fleet` -- so `-L fleet` can never be a fleet socket, and
# its failure is spelled the same as an empty server. A wrong guess and a quiet box look identical.
set -uo pipefail
```

Checks, all reporting:

1. **This root:** `tmux -L "$FLEET_TMUX_SOCKET" ls` — count `dt-` sessions.
2. **Every other root:** for each `/tmp/tmux-*/fleet-*` socket, `tmux -L "$(basename "$s")" ls` and its `dt-` count. This is the half the session missed.
3. **Slots:** `"$REPO/bin/fleet" board --porcelain` rows in state `COMPLETE` still holding a slot.
4. **Cron window:** `date -u` against the `30 3 * * *` sync line from `crontab -l`, using a **45-minute** gate duration. Warn if a gate started now would straddle it.
5. **Orphans (F7):** for each `"$FLEET_RELEASES"/.fleet-v*.tmp`, parse field 3 of the name as a pid — the name is `.{dirname}.{pid}.{monotonic_ns}.{rand}.tmp`, which is why this is cheap. Print `LIVE` if **both** `kill -0 <pid>` succeeds **and** `/proc/<pid>/cmdline` contains `release-verify`; otherwise `ORPHAN <path> <size> <mtime>`.

**Both halves of the liveness test are required.** Pids are reused; reaping a live run's worktree mid-suite produces a failure with no honest explanation. Say that in a comment.

`--reap` removes only `ORPHAN` directories, only those whose name matches `^\.fleet-v.*\.[0-9]+\.[0-9]+\.[0-9a-f]+\.tmp$` exactly, then runs `git -C "$REPO" worktree prune`. Anything not matching is refused, not guessed at.

**The one hard refusal, exit 2:** `FLEET_TMUX_SOCKET` unset or equal to `fleet`. That means the environment was not derived and every count the script could print would be a lie. A preflight that reports confidently from a broken environment is worse than none.

- [ ] **Step 2: Write the test**

`scripts/tests/release-preflight.sh`:
- with `FLEET_TMUX_SOCKET=fleet` → exit 2, and the message names the derivation;
- with `FLEET_TMUX_SOCKET` unset → exit 2;
- a fabricated `.fleet-v0.0.1.999999.1.abc.tmp` whose pid is not running → reported `ORPHAN`; with `--reap` → removed;
- a fabricated tmp dir whose pid **is** this test's own shell but whose cmdline is not `release-verify` → still `ORPHAN` (asserts both halves of the liveness test);
- a directory named `.fleet-v0.0.1.tmp` (not matching the full pattern) → **not** removed by `--reap`;
- normal run with a derived socket → exit 0 even with warnings present.

Use a scratch `FLEET_RELEASES` under `mktemp -d`; never touch the real release area.

- [ ] **Step 3: Run the test and the linter**

Run: `bash scripts/tests/release-preflight.sh` → no `FAIL`.
Run: `bash scripts/lint-shell.sh scripts/release-preflight.sh scripts/tests/release-preflight.sh` → clean.

- [ ] **Step 4: Reap this box's real orphans and report the number**

Run: `bash scripts/release-preflight.sh` then `bash scripts/release-preflight.sh --reap`, then `git worktree list`.
Expected: the five `.fleet-v*.tmp` directories gone, `git worktree list` showing only the checkout and `.worktrees/fleet-runtime`. Report the reclaimed size.

- [ ] **Step 5: Commit**

```bash
git add scripts/release-preflight.sh scripts/tests/release-preflight.sh
git commit -m "feat: scripts/release-preflight.sh — box quietness through the derived socket, and an orphan reaper"
```

---

### Task 6: `scripts/release-postflight.sh` — prove the deployment, without asking fleet

**Spec:** F8.

**Files:**
- Create: `scripts/release-postflight.sh`
- Test: `scripts/tests/release-postflight.sh`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: exit 0 all-OK, 1 on any mismatch.

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
#
# Prove a deployment reached every root that shares this release area.
#
# Usage:  scripts/release-postflight.sh <version>
#
# Invokes `fleet` NOT AT ALL, on purpose. `release-status` reports relative to the FLEET_HOME it is
# handed, and davis2_root/fleet-releases is a SYMLINK to davis_root/fleet-releases -- so running it from
# the second root printed "current DEV / head unknown" for a deployment that was perfectly correct, and
# cost a paragraph of reasoning to discount. The state was right; the presentation is root-relative while
# the question is box-relative. readlink answers the box-relative question directly.
set -uo pipefail
```

Assertions, one `OK`/`MISMATCH` line each, naming both sides on a mismatch:

1. `readlink -f "$FLEET_RELEASES/current"` ends in `fleet-v<version>`.
2. For each `/home/ubuntu/*_root` whose `fleet-releases` resolves to the **same** release area (that is the correct scoping — other roots have their own), `readlink -f "<root>/fleet-releases/current"` equals it. This *proves* the symlink topology rather than assuming it.
3. For each such root, the `.claude/settings.json` marketplace path, `readlink -f`'d, equals it.
4. Every file named in `current/.version-bump.json` carries `+fleet.<version>` — this is the only check that covers `.hermes-plugin/plugin.yaml`, the file Task 1 shows nothing else was checking.
5. `awk -F'\t' '$1=="verdict"' current/.release/evidence/VERDICT.tsv` is `GREEN` or `EXEMPT`.

- [ ] **Step 2: Write the test**

Build a fake box under `mktemp -d`: two fake roots, one real release dir with a `current` symlink, a `.version-bump.json`, stamped manifests, a `VERDICT.tsv`. Assert exit 0. Then, one at a time, break each of the five and assert exit 1 with the right assertion named. Include one case where a **second root's `current` points at the previous version** — the exact failure this script exists to catch.

- [ ] **Step 3: Run the test and the linter**

Run: `bash scripts/tests/release-postflight.sh` → no `FAIL`.
Run: `bash scripts/lint-shell.sh scripts/release-postflight.sh scripts/tests/release-postflight.sh` → clean.

- [ ] **Step 4: Commit**

```bash
git add scripts/release-postflight.sh scripts/tests/release-postflight.sh
git commit -m "feat: scripts/release-postflight.sh — prove the deployment reached every root"
```

---

### Task 7: The docs stop being the control

**Spec:** F9.

**Files:**
- Modify: `skills/releasing-fleet/SKILL.md`
- Modify: `fleet/CLAUDE.md` (the script list, beside `fleet-view.sh` at `:150` and `fleet-finished-pids.sh` at `:238`)

- [ ] **Step 1: Wire each mechanised trap to its script**

For every trap now enforced, keep the **explanation** — an operator who knows only "run the script" cannot diagnose the script — and add the one line naming the script. Traps 1, 2 and the clean-tree rule keep their prose and gain a note that the verb already refuses (spec S2), so nobody adds a redundant check later.

- [ ] **Step 2: Correct the two known-wrong facts**

1. The suites table says `~24 min`. Measured on this box: **2080 s and 2800 s**. Change to `~24–45 min (Trap 3)`, matching what the traps section already says.
2. **Withdraw** the claim that the pipe killed the first 0.5.9 run. The transcript retracts it: *"Forty-five minutes, no verdict, same two lines — so my pipe theory was wrong and something else is stopping it."* Replace with what was measured: **the pipe made a dead run report exit 0**, which is reason enough to never pipe a control.

This is a citation amendment, not a deletion — state the measurement that replaces the claim.

- [ ] **Step 3: Add a trap for the exemption path now being live**

`EXEMPT` has never fired before. Say that it now can, what it means (no suites ran; the evidence is `EXEMPTION.tsv`, not a test log), and that `release-verify --dry-run` will now tell you the decision and the paths forcing it before you spend 45 minutes.

- [ ] **Step 4: Add the three scripts to `fleet/CLAUDE.md`**

Beside the existing entries, with how to run each test, matching the `bash scripts/tests/fleet-finished-pids.sh   # ~15s, spends no claude` form.

- [ ] **Step 5: Commit**

```bash
git add skills/releasing-fleet/SKILL.md fleet/CLAUDE.md
git commit -m "docs: point each mechanised trap at the script that now enforces it"
```

---

## Self-review notes

- **Spec coverage:** F1→T1, F2→T2, F3/F4→T3, F5→T4, F6/F7→T5, F8→T6, F9→T7. S1–S8 are sanctions — deliberately no task; T7 records S2's "the verb already refuses" so the deleted checks are not re-proposed.
- **Ordering:** T2 depends on T1 (the `would-exempt` assertion is unreachable until the stripper works). T3–T7 are independent of each other and of T1/T2.
- **Type consistency:** `without_version_field` keeps its signature; `RELEASE_COLUMNS` appends; the three scripts share exit-code conventions (2 = usage/environment) and none shares a function with another.
