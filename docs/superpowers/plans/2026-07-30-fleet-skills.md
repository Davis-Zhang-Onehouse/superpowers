# Fleet Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three `pdispatch`-era coordination skills with four skills built on `fleet`, each carrying tests that prove its factual claims.

**Architecture:** One shared lint tool (`lint-skill.py`) checks two properties of any skill — every `fleet <verb>` it names is a registered verb (V1), and every refusal it claims cites an integration case that passed (V2). Each skill gets a thin `tests/*.sh` wrapper that `bin/superpowers-selftest` already discovers. The coordinator skill additionally gets an executable walkthrough (V3) that runs its documented loop against a scratch store.

**Tech Stack:** Bash (skill tests, POSIX-ish, `set -uo pipefail`), Python 3 stdlib only (the lint tool and `fleet` itself), Markdown with YAML frontmatter (skills).

## Global Constraints

- **Two repositories.** Task 0 modifies `/home/ubuntu/davis_root/operations/tasks/metaOpt/00000000-07300312-inflight-append-fleetInfraRebuild` (the `fleet` repo, called `$FLEET` below). Tasks 1–6 modify `/home/ubuntu/davis_root/superpowers` (called `$SP`). Never commit one repo's change from the other.
- **`fleet` is python3-stdlib-only.** No third-party imports in `$FLEET/src/`.
- **A test suite's LAST stdout line must match `^PASS(:|[[:space:]]|$)`** or `bin/superpowers-selftest` records it as FAIL. Discovery glob: `skills/*/tests/*.sh`. Per-suite timeout 600s.
- **Never create, kill, or write a tmux session whose name starts with `dt-`** on the default tmux server. Any test that could start a session must export `FLEET_TMUX_SOCKET` to a private value first.
- **Never write to `~/.fleet`, `~/.claude-dispatch-board`, or `~/.claude-ws-pool`.** Every test exports `FLEET_HOME` and `FLEET_INSTANTS` explicitly to a temp directory.
- **Never pipe a control.** Use `if bash cmd; then` — a pipe through `tail`/`grep` discards the exit status.
- **`bin/`'s 21 `pdispatch` executables are NOT deleted** by this plan (spec: "Explicitly left alone").
- Existing skill frontmatter format is exactly two keys: `name` and `description`. Match it.

---

### Task 0: `fleet brief` — the dispatched instant's orientation verb

**Repo:** `$FLEET`

**Files:**
- Modify: `$FLEET/src/fleet/cli.py` (add `_do_brief`, register the verb, add a porcelain entry)
- Modify: `$FLEET/tests/test_cli.py` (add `TestBrief`, add an argv row)
- Modify: `$FLEET/tests/test_contracts.py` (add the same argv row)

**Interfaces:**
- Consumes: `origin_mod.read(instant) -> Origin | None` with fields `.coordinator`, `.milestone`, `.dispatched_at`; `Roadmap(path).milestone(id) -> Milestone` (fields `.id .title .status .deps .evidence .owner`); `Roadmap(path).blocker_of(id) -> str | None`; `Roadmap(path).proposals() -> list[Proposal]` (fields `.instant .milestone .status .evidence .at`); `Declarations(instant).phase() -> str | None`; `Declarations(instant).parked() -> str | None`; `Review(instant, now=...).gate(require_scope=None, harvest=False) -> Verdict` (fields `.allowed .guard .reason .clears_when .clears_who`); `_record_for(ctx, child) -> Record | None`; `_resolve_instant(ctx, path)`; `Row(kind, subject, detail, severity, clears_when, clears_who)`; `_emit(ctx, verb, rows)`; constants `INFO`, `ATTENTION`, `POPULATION`, `EXIT_OK`.
- Produces: verb `brief`, read-only, `checker=True`, one required flag `--instant`. Row kinds: `origin`, `milestone`, `phase`, `review`, `destination`, `outstanding`, plus a `population` row. Later tasks reference it only as the literal string `fleet brief --instant .`.

- [ ] **Step 1: Write the failing test**

Append to `$FLEET/tests/test_cli.py`:

```python
class TestBrief(CliCase):
    """`fleet brief` is the dispatched instant's first command.

    It exists because the alternative first instruction in a worker's skill was `cat .fleet/origin.json` —
    hand-parsing machine state, which is the thing the north star forbids. The row that earns the verb is
    `destination`: a worker can see WHERE its next report will land before it sends one, which is what makes
    a silently-local proposal impossible to walk into.
    """

    def test_brief_names_the_coordinator_the_milestone_and_the_destination(self):
        fleet = self.loaded()
        coordinator = fleet.paths["readyWorker"]
        child = fleet.paths["solo"]
        Roadmap(coordinator).add(Milestone(id="B1", title="the brief's milestone", status="blocked",
                                           deps=[], evidence=[]))
        origin_mod.write(child, Origin(coordinator=str(coordinator), dispatched_at=NOW, milestone="B1"))

        code, out, err = fleet.run(["brief", "--instant", str(child), "--porcelain"])

        self.assertEqual(0, code, err)
        kinds = {line.split("\t")[0] for line in out.splitlines()}
        self.assertLessEqual({"origin", "milestone", "destination", "outstanding", "population"}, kinds,
                             f"brief must answer every orientation question in its own row: {out}")
        self.assertIn(str(coordinator), out, "the worker must be told who its coordinator is")
        self.assertIn("B1", out, "and which milestone it was dispatched for")

    def test_brief_says_a_report_would_stay_local_when_there_is_no_origin(self):
        """The row that earns the verb. An instant with no coordinator is legitimate, and a worker must be
        able to SEE that its report would go nowhere a coordinator reads."""
        fleet = self.loaded()
        child = fleet.paths["solo"]
        self.assertIsNone(origin_mod.read(child), "this fixture is supposed to have no coordinator")

        code, out, err = fleet.run(["brief", "--instant", str(child), "--porcelain"])

        self.assertEqual(0, code, err)
        destination = [l for l in out.splitlines() if l.startswith("destination\t")]
        self.assertTrue(destination, "brief emitted no destination row")
        self.assertIn("LOCAL", destination[0],
                      "a worker whose report would stay local must be told so in that row")

    def test_brief_is_read_only(self):
        fleet = self.loaded()
        child = fleet.paths["solo"]
        before = fleet.record_state()

        code, out, err = fleet.run(["brief", "--instant", str(child), "--porcelain"])

        self.assertEqual(0, code, err)
        self.assertEqual(before, fleet.record_state(), "brief wrote to the record store")
```

Add the import if absent at the top of the file: `from fleet.origin import Origin`.

- [ ] **Step 2: Run it and confirm it fails for the right reason**

```bash
cd /home/ubuntu/davis_root/operations/tasks/metaOpt/00000000-07300312-inflight-append-fleetInfraRebuild
PYTHONPATH=src python3 -m unittest tests.test_cli.TestBrief -v
```

Expected: 3 errors, each `BadInput: unknown verb 'brief'` (or a usage error naming the verb). **If it fails with `KeyError: 'brief'` from `PORCELAIN_COLUMNS`, the verb was registered without a porcelain entry — that is Step 3's job, keep going.**

- [ ] **Step 3: Implement the handler**

Insert into `$FLEET/src/fleet/cli.py` immediately before `def _do_lint(`:

```python
def _do_brief(ctx: Ctx, parsed: Parsed) -> int:
    """What a dispatched instant needs to know about itself, in one screen. Read-only.

    The alternative first instruction in a worker's skill was `cat .fleet/origin.json`, which is hand-parsing
    machine state. Six questions, one row each, and the fifth is the one that earns the verb: WHERE the next
    `propose` will land. A worker that can see its report would stay local cannot walk into losing it.
    """
    child = _instant(ctx, parsed)
    recorded = origin_mod.read(child)
    rows = []

    if recorded is None:
        rows.append(Row(kind="origin", subject=child.name, severity=INFO,
                        detail=("no origin.json: this instant was not dispatched by a coordinator (it was "
                                "created by `init`, or it IS a coordinator)")))
    else:
        rows.append(Row(kind="origin", subject=child.name, severity=INFO,
                        detail=(f"dispatched by {recorded.coordinator} at {recorded.dispatched_at} for "
                                f"milestone {recorded.milestone or '(none)'}")))

    coordinator = None
    if recorded is not None:
        try:
            coordinator = _resolve_instant(ctx, recorded.coordinator)
        except BadInput as exc:
            rows.append(Row(kind="milestone", subject=recorded.milestone or "(none)", severity=ATTENTION,
                            detail=f"the coordinator no longer resolves: {exc}",
                            clears_when="the coordinator instant is present under the instants directory",
                            clears_who=COORDINATOR))
    if coordinator is not None and recorded.milestone:
        roadmap = Roadmap(coordinator)
        try:
            milestone = roadmap.milestone(recorded.milestone)
            blocker = roadmap.blocker_of(recorded.milestone)
            rows.append(Row(
                kind="milestone", subject=milestone.id, severity=INFO,
                detail=(f"{milestone.title!r}, status={milestone.status}, owner="
                        f"{milestone.owner or '(unowned)'}; "
                        + (f"NOT ready: {blocker}" if blocker else "ready")),
                clears_when=blocker or "", clears_who=COORDINATOR if blocker else ""))
        except BadInput as exc:
            rows.append(Row(kind="milestone", subject=recorded.milestone, severity=ATTENTION,
                            detail=f"not on the coordinator's roadmap: {exc}",
                            clears_when="the coordinator adds it with `fleet milestone`",
                            clears_who=COORDINATOR))

    declarations = Declarations(child)
    rows.append(Row(kind="phase", subject=child.name, severity=INFO,
                    detail=(f"phase={declarations.phase() or '(none declared)'}, "
                            f"parked={declarations.parked() or '(not parked)'}")))

    gate = Review(child, now=ctx.now).gate(require_scope="all")
    rows.append(Row(kind="review", subject=child.name,
                    severity=INFO if gate.allowed else ATTENTION,
                    detail=f"the gate would say {'ALLOW' if gate.allowed else 'REFUSE'}: {gate.reason}",
                    clears_when=gate.clears_when or "", clears_who=gate.clears_who or ""))

    #: THE row. `propose`'s destination resolution, reported before a proposal is written rather than after.
    if coordinator is not None:
        destination_detail = (f"a `fleet propose` with no --to will reach {coordinator} — read from "
                              f".fleet/{origin_mod.ORIGIN}, written by the dispatcher")
        severity = INFO
    else:
        destination_detail = ("LOCAL — a `fleet propose` with no --to stays in THIS instant's own inbox and "
                              "NO COORDINATOR WILL SEE IT. Correct for an instant with no coordinator; "
                              "wrong for a dispatched worker, and the reason to check before reporting")
        severity = INFO
    rows.append(Row(kind="destination", subject=child.name, severity=severity, detail=destination_detail))

    #: What stands between this instant and being closed out, so "am I done?" is answerable.
    record = _record_for(ctx, child)
    outstanding = []
    if recorded is not None and recorded.milestone and coordinator is not None:
        pending = [p for p in Roadmap(coordinator).proposals() if p.milestone == recorded.milestone]
        if not pending:
            outstanding.append(f"no proposal for {recorded.milestone} is pending at the coordinator")
    if not gate.allowed:
        outstanding.append("the review gate does not allow completion")
    if "-inflight-" in child.name:
        outstanding.append("the folder is still -inflight- (the rename IS the state transition)")
    if record is not None and record.lineage_base:
        outstanding.append(f"a lineage base is recorded ({record.lineage_base}); `fleet base-check --id "
                           f"{record.todo_id}` decides whether a claim of done will be refused")
    rows.append(Row(kind="outstanding", subject=child.name,
                    severity=ATTENTION if outstanding else INFO,
                    detail=("; ".join(outstanding) if outstanding
                            else "nothing outstanding that this verb can see")))

    rows.append(Row(kind=POPULATION, subject=child.name, severity=INFO,
                    detail=(f"{len(rows)} orientation row(s) for {child}; read-only, and every field is "
                            f"read through the same API the enforcing verb uses")))
    _emit(ctx, "brief", rows)
    return EXIT_OK


```

- [ ] **Step 4: Register the verb and its porcelain schema**

In `$FLEET/src/fleet/cli.py`, insert immediately before the line `    _verb("base-check", _do_base_check, True,`:

```python
    _verb("brief", _do_brief, True,
          "what a dispatched instant needs to know about itself: coordinator, milestone, phase, gate, "
          "where its next report will land, and what is outstanding",
          checker=True, flags=(
        Flag("--instant", True, True, "the instant to brief; use `.` from inside it"),
    )),
```

And insert immediately before the line `    "base-check": ROW_COLUMNS,`:

```python
    "brief": ROW_COLUMNS,
```

- [ ] **Step 5: Add the argv row to BOTH tables**

In `$FLEET/tests/test_cli.py` and `$FLEET/tests/test_contracts.py`, insert into the dict returned by `argv_for`, immediately before the line `            "base-check": ["--id", fleet.ids["solo"]],`:

```python
            "brief": ["--instant", ready],
```

- [ ] **Step 6: Run the new tests, then the whole suite**

```bash
cd /home/ubuntu/davis_root/operations/tasks/metaOpt/00000000-07300312-inflight-append-fleetInfraRebuild
PYTHONPATH=src python3 -m unittest tests.test_cli.TestBrief -v
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

Expected: `TestBrief` 3 passing; discover reports `Ran 817 tests` (814 + 3) and `OK`. If `test_the_argv_table_covers_every_verb` fails, an argv row is missing from one of the two tables — Step 5 covers both.

- [ ] **Step 7: Confirm it works against a real store, on a private tmux socket**

```bash
cd /home/ubuntu/davis_root/operations/tasks/metaOpt/00000000-07300312-inflight-append-fleetInfraRebuild
. evidence/04-integration/bin/adhoc-sandbox.sh
I=$(python3 -m fleet.cli init --base 00000000 --name briefProbe --porcelain | awk -F'\t' '$1=="path"{print $2}')
python3 -m fleet.cli brief --instant "$I"
tmux -L "$FLEET_TMUX_SOCKET" kill-server 2>/dev/null; rm -rf "$FLEET_ADHOC_BASE"
```

Expected: rows for `origin` (no origin.json), `phase`, `review`, `destination` containing `LOCAL`, `outstanding`, `population`. Exit 0.

- [ ] **Step 8: Verify the controls, then commit**

```bash
cd /home/ubuntu/davis_root/operations/tasks/metaOpt/00000000-07300312-inflight-append-fleetInfraRebuild
if bash evidence/04-integration/bin/lint-evidence-paths.sh >/dev/null; then echo "P-3 GREEN"; fi
git add src/fleet/cli.py tests/test_cli.py tests/test_contracts.py
git commit -m "fleet brief: what a dispatched instant needs to know about itself

Read-only, six rows. The alternative first instruction in a worker's skill was
\`cat .fleet/origin.json\`, which is hand-parsing machine state.

The row that earns the verb is \`destination\`: it reports where a \`propose\` with
no --to would land, BEFORE one is written. A worker that can see its report would
stay local cannot walk into losing it."
if bash evidence/04-integration/bin/assert-head-green.sh >/dev/null 2>&1; then echo "P-1 GREEN(HEAD)"; fi
```

Expected: `P-3 GREEN`, a commit, `P-1 GREEN(HEAD)`.

---

### Task 1: The shared skill lint (V1 + V2) and `using-fleet`

**Repo:** `$SP`

**Files:**
- Create: `$SP/skills/using-fleet/SKILL.md`
- Create: `$SP/skills/using-fleet/tools/lint-skill.py`
- Create: `$SP/skills/using-fleet/tests/lint-self.sh`
- Create: `$SP/skills/using-fleet/tools/tests/lint-skill-test.sh`
- Modify: `$SP/bin/superpowers-selftest:26` (print each suite's last line, so a SKIP is never silent)

**Interfaces:**
- Consumes: nothing from earlier tasks. Reads `fleet`'s verb list by importing `fleet.cli.VERBS` from `$FLEET_SRC`, and case verdicts from `$FLEET_RESULTS` (a TSV whose column 1 is a case id and column 2 a verdict).
- Produces: `tools/lint-skill.py <skill-dir>`, exit `0` clean / `1` findings / `2` bad input. Env: `FLEET_SRC` (default `/home/ubuntu/davis_root/operations/tasks/metaOpt/00000000-07300312-inflight-append-fleetInfraRebuild/src`), `FLEET_RESULTS` (default `<that>/../evidence/04-integration/RESULTS.tsv`). Marker syntax consumed from skill markdown: `<!-- v1-proposed: <verb> -->` and `<!-- v2-cite: <claim-slug> <CASE-ID> -->`. Later tasks call this script and use both marker forms.

- [ ] **Step 1: Fix the silent-skip hole in the runner first**

In `$SP/bin/superpowers-selftest`, replace this line:

```bash
    pass=$((pass+1)); printf '  PASS  %s\n' "$rel"
```

with:

```bash
    # Print the suite's LAST line even on success. A suite that skipped half its checks reports that in its
    # verdict line, and a runner that only shows output on failure would make the skip invisible — which is
    # "absence is never success" broken in the tool that reports success.
    pass=$((pass+1)); printf '  PASS  %s — %s\n' "$rel" "$(printf '%s' "$out" | tail -1)"
```

- [ ] **Step 2: Prove the runner change works**

```bash
cd /home/ubuntu/davis_root/superpowers
bash bin/superpowers-selftest 2>&1 | head -8
```

Expected: each `PASS` line now ends with ` — PASS...` (that suite's own last line). `VERDICT: GREEN`.

- [ ] **Step 3: Write the failing test for the lint tool**

Create `$SP/skills/using-fleet/tools/tests/lint-skill-test.sh`:

```bash
#!/usr/bin/env bash
# Tests for lint-skill.py — the V1/V2 checks every fleet skill runs against itself.
#
# Both directions, because a lint nobody has seen fire is decoration: each case builds a fixture skill that
# SHOULD trip the check and one that should not.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LINT="$HERE/../lint-skill.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fails=0
note() { printf '  %s\n' "$*"; }

mk() {                    # mk <name> <body>
  mkdir -p "$TMP/$1"
  printf '%s\n' "$2" > "$TMP/$1/SKILL.md"
  printf '%s' "$TMP/$1"
}

# --- V1: an unknown verb in a CODE SPAN is a finding -------------------------------------------------
d="$(mk badverb 'Run `fleet nosuchverb --instant .` to begin.')"
if python3 "$LINT" "$d" >"$TMP/badverb.out" 2>&1; then
  note "FAIL V1-detects: an unknown verb in a code span was not reported"; fails=1
else
  grep -q 'nosuchverb' "$TMP/badverb.out" || { note "FAIL V1-detects: finding did not name the verb"; fails=1; }
fi

# --- V1: the same token in PROSE is NOT a finding ----------------------------------------------------
d="$(mk proseonly 'The point is that fleet refuses it, so fleet state is authoritative.')"
if python3 "$LINT" "$d" >"$TMP/prose.out" 2>&1; then
  :
else
  note "FAIL V1-prose: prose containing the word fleet was treated as a command"; cat "$TMP/prose.out"; fails=1
fi

# --- V1: a real verb passes --------------------------------------------------------------------------
d="$(mk goodverb 'Run `fleet roadmap --instant .` to see readiness.')"
if python3 "$LINT" "$d" >"$TMP/good.out" 2>&1; then
  :
else
  note "FAIL V1-real-verb: a registered verb was reported as unknown"; cat "$TMP/good.out"; fails=1
fi

# --- V1: a MARKED proposed verb passes, and the marker is required -----------------------------------
d="$(mk markedverb 'Run `fleet brief --instant .` first.
<!-- v1-proposed: brief -->')"
if python3 "$LINT" "$d" >"$TMP/marked.out" 2>&1; then
  :
else
  note "FAIL V1-marker: a marked proposed verb was still reported"; cat "$TMP/marked.out"; fails=1
fi

# --- V2: a refusal claim with NO citation is a finding -----------------------------------------------
d="$(mk uncited 'Note that `fleet propose` refuses an empty evidence list.')"
if python3 "$LINT" "$d" >"$TMP/uncited.out" 2>&1; then
  note "FAIL V2-detects: an uncited refusal claim was not reported"; fails=1
else
  grep -qi 'refus' "$TMP/uncited.out" || { note "FAIL V2-detects: finding did not name the claim"; fails=1; }
fi

# --- V2: a citation naming a PASSING case clears it --------------------------------------------------
d="$(mk cited 'Note that `fleet propose` refuses an empty evidence list.
<!-- v2-cite: empty-evidence H4 -->')"
if python3 "$LINT" "$d" >"$TMP/cited.out" 2>&1; then
  :
else
  note "FAIL V2-clears: a citation to a passing case did not clear the claim"; cat "$TMP/cited.out"; fails=1
fi

# --- V2: a citation naming a case that does NOT exist is a finding -----------------------------------
d="$(mk fakecite 'Note that `fleet propose` refuses an empty evidence list.
<!-- v2-cite: empty-evidence NOSUCHCASE -->')"
if python3 "$LINT" "$d" >"$TMP/fake.out" 2>&1; then
  note "FAIL V2-fake: a citation to a non-existent case was accepted"; fails=1
else
  grep -q 'NOSUCHCASE' "$TMP/fake.out" || { note "FAIL V2-fake: finding did not name the bad case id"; fails=1; }
fi

if [ "$fails" = 0 ]; then
  echo "PASS: lint-skill.py detects unknown verbs and uncited refusal claims, ignores prose, honours the proposed-verb marker, and rejects a citation to a case that did not pass"
else
  echo "FAIL"
  exit 1
fi
```

- [ ] **Step 4: Run it and confirm it fails because the tool does not exist**

```bash
cd /home/ubuntu/davis_root/superpowers
bash skills/using-fleet/tools/tests/lint-skill-test.sh
```

Expected: last line `FAIL`, exit 1, with `can't open file .../lint-skill.py` in the output.

- [ ] **Step 5: Implement the lint tool**

Create `$SP/skills/using-fleet/tools/lint-skill.py`:

```python
#!/usr/bin/env python3
"""Check two factual properties of a fleet skill. Usage: lint-skill.py <skill-dir>

V1  every `fleet <verb>` named in a CODE SPAN is a registered verb, unless marked
    `<!-- v1-proposed: <verb> -->`.
V2  every sentence claiming a refusal cites an integration case that PASSED, via
    `<!-- v2-cite: <slug> <CASE-ID> -->`.

Exit 0 = clean, 1 = findings, 2 = bad input.

Why code spans only: a whole-document match for `fleet <word>` fires on ordinary prose — "fleet refuses
it", "fleet state is authoritative" — and a lint that reports its own author's sentences gets switched off.
Why a marker rather than tolerance: a skill may legitimately name a verb that is not built yet, and the
difference between a promise and a bug is that somebody wrote the promise down.
"""
import os
import pathlib
import re
import sys

DEFAULT_FLEET_SRC = ("/home/ubuntu/davis_root/operations/tasks/metaOpt/"
                     "00000000-07300312-inflight-append-fleetInfraRebuild/src")

#: A fenced block, or an inline span. Only these are searched for commands.
FENCE = re.compile(r"```.*?```", re.S)
SPAN = re.compile(r"`([^`\n]+)`")
COMMAND = re.compile(r"\bfleet\s+([a-z][a-z0-9-]*)")
PROPOSED = re.compile(r"<!--\s*v1-proposed:\s*([a-z][a-z0-9-]*)\s*-->")
CITE = re.compile(r"<!--\s*v2-cite:\s*(\S+)\s+(\S+)\s*-->")
#: A refusal claim. Deliberately narrow: the verbs a skill uses to promise the tool will stop you.
CLAIM = re.compile(r"^(?![ \t]*<!--).*\b(refuses?|refused|is refused|cannot|will not)\b.*$",
                   re.I | re.M)


def verbs_from(src: str) -> set:
    sys.path.insert(0, src)
    try:
        from fleet.cli import VERBS
    except Exception as exc:                       # noqa: BLE001 - reported, never guessed around
        raise SystemExit(f"lint-skill: cannot import fleet.cli from {src!r} ({exc}). "
                         f"Set FLEET_SRC to the fleet package's src directory.")
    return set(VERBS)


def passing_cases(results: pathlib.Path) -> set:
    if not results.is_file():
        raise SystemExit(f"lint-skill: no results file at {results}. Set FLEET_RESULTS to the "
                         f"integration RESULTS.tsv, or this lint cannot check a citation.")
    out = set()
    for line in results.read_text().splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].strip() == "PASS":
            out.add(parts[0].strip())
    return out


def code_regions(text: str) -> list:
    regions = [m.group(0) for m in FENCE.finditer(text)]
    stripped = FENCE.sub("", text)
    regions += [m.group(1) for m in SPAN.finditer(stripped)]
    return regions


def main(argv: list) -> int:
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    skill = pathlib.Path(argv[1])
    doc = skill / "SKILL.md"
    if not doc.is_file():
        print(f"lint-skill: no SKILL.md in {skill}", file=sys.stderr)
        return 2
    text = doc.read_text()
    findings = []

    known = verbs_from(os.environ.get("FLEET_SRC", DEFAULT_FLEET_SRC))
    proposed = set(PROPOSED.findall(text))
    named = set()
    for region in code_regions(text):
        named.update(COMMAND.findall(region))
    for verb in sorted(named - known - proposed):
        findings.append(f"V1: `fleet {verb}` is named in a code span and is not a registered verb. "
                        f"If it is deliberate, mark it: <!-- v1-proposed: {verb} -->")

    results = pathlib.Path(os.environ.get(
        "FLEET_RESULTS", str(pathlib.Path(os.environ.get("FLEET_SRC", DEFAULT_FLEET_SRC)).parent
                            / "evidence" / "04-integration" / "RESULTS.tsv")))
    passing = passing_cases(results)
    cited = {case for _slug, case in CITE.findall(text)}
    for case in sorted(cited - passing):
        findings.append(f"V2: cited case {case!r} is not PASS in {results}. A claim may only cite a case "
                        f"that actually passed.")
    claims = [m.group(0).strip() for m in CLAIM.finditer(text)]
    if claims and not cited:
        findings.append(f"V2: {len(claims)} sentence(s) claim a refusal and the file cites no case. "
                        f"Add <!-- v2-cite: <slug> <CASE-ID> --> for each. First: "
                        f"{claims[0][:110]!r}")

    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 6: Run the tool's tests to verify they pass**

```bash
cd /home/ubuntu/davis_root/superpowers
bash skills/using-fleet/tools/tests/lint-skill-test.sh
```

Expected: last line begins `PASS: lint-skill.py detects unknown verbs…`, exit 0.

- [ ] **Step 7: Write `using-fleet` SKILL.md**

Create `$SP/skills/using-fleet/SKILL.md` with frontmatter exactly:

```markdown
---
name: using-fleet
description: Use when running any `fleet` command — the verb surface, exit codes, porcelain output, and the store/socket environment. Triggers include "fleet dispatch", "fleet roadmap", "what fleet verb", "FLEET_HOME", "porcelain", "exit code 4", "which verbs are read-only".
---
```

Required sections, in this order. Content is prose the implementer writes; these are the sections V1/V2 and the reviewer check for:

1. **Overview** — one paragraph: `fleet` is python3-stdlib-only, `python3 -m fleet.cli`, state under an explicit `FLEET_HOME` plus per-instant `.fleet/`.
2. **The environment, always explicit** — `FLEET_HOME`, `FLEET_INSTANTS`, `FLEET_TMUX_SOCKET`. State that a mutating verb with no named store **refuses** rather than defaulting to `~/.fleet`, and cite it.
3. **The verb table** — every verb, marked read-only or mutating, one line each. Generate it, do not hand-type it:
   ```bash
   cd /home/ubuntu/davis_root/operations/tasks/metaOpt/00000000-07300312-inflight-append-fleetInfraRebuild
   PYTHONPATH=src python3 -c "
   from fleet.cli import VERBS
   for n, s in sorted(VERBS.items()):
       print(f'| \`{n}\` | {\"read-only\" if s.read_only else \"mutating\"} | {s.help} |')"
   ```
4. **Exit codes** — from `python3 -m fleet.cli --help`'s exit-code block, verbatim.
5. **Porcelain** — `--porcelain` emits tab-separated fields whose schema is declared data; parse columns, never prose.
6. **`--dry-run`** — every mutating verb has one, derived from `read_only`, and it is asserted to be zero-delta.

Include at least one `<!-- v2-cite: ... -->` for the refusal claim in section 2 (`SI-15` is proven by the hermetic class `TestAMutatingVerbNamesItsStore`; if no IT case covers it, cite `M13`, the selftest case, and say in prose that the proof is hermetic rather than integration).

- [ ] **Step 8: Write the skill's own lint suite**

Create `$SP/skills/using-fleet/tests/lint-self.sh`:

```bash
#!/usr/bin/env bash
# V1+V2 over this skill. Discovered by bin/superpowers-selftest.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SKILL="$HERE/.."
LINT="$SKILL/tools/lint-skill.py"

out="$(python3 "$LINT" "$SKILL" 2>&1)"
rc=$?
if [ "$rc" = 0 ]; then
  echo "PASS: every fleet verb named in a code span is registered, and every refusal claim cites a passing case"
  exit 0
fi
printf '%s\n' "$out"
echo "FAIL"
exit 1
```

- [ ] **Step 9: Run both suites through the real runner**

```bash
cd /home/ubuntu/davis_root/superpowers
chmod +x skills/using-fleet/tools/lint-skill.py
if bash bin/superpowers-selftest; then echo "SELFTEST GREEN"; else echo "SELFTEST RED"; fi
```

Expected: `SELFTEST GREEN`, and the output includes `PASS  skills/using-fleet/tests/lint-self.sh — PASS: every fleet verb…` and `PASS  skills/using-fleet/tools/tests/lint-skill-test.sh — PASS: lint-skill.py detects…`.

- [ ] **Step 10: Commit**

```bash
cd /home/ubuntu/davis_root/superpowers
git add bin/superpowers-selftest skills/using-fleet
git commit -m "using-fleet skill, and the shared V1/V2 skill lint

lint-skill.py checks two factual properties of any fleet skill: every \`fleet <verb>\`
named in a CODE SPAN is registered (V1), and every refusal claim cites an integration
case that passed (V2). Code spans only, because a whole-document match fires on the
author's own prose; a proposed verb needs an explicit marker, because the difference
between a promise and a bug is that somebody wrote the promise down.

superpowers-selftest now prints each suite's last line on success too, so a suite that
skips half its checks cannot report success silently."
```

---

### Task 2: The three profile templates

**Repo:** `$SP`

**Files:**
- Create: `$SP/skills/using-fleet/profiles/worker/{profile.json,charter.md,seed.txt}`
- Create: `$SP/skills/using-fleet/profiles/compaction/{profile.json,charter.md,seed.txt}`
- Create: `$SP/skills/using-fleet/profiles/coordinator/{profile.json,charter.md,seed.txt}`
- Create: `$SP/skills/using-fleet/tests/profiles-render.sh`

**Interfaces:**
- Consumes: `fleet.profiles.Profile.load(path)` and `.render(context: dict) -> dict` keyed by artifact stem (`charter`, `seed`); raises `BadInput` on any unresolved `{{TOKEN}}`. Substitutions `dispatch` supplies: `TITLE`, `INSTANT`, `SLOT`, `TODO_ID`, `BASE`, `PATH`, `MILESTONE`, `COORDINATOR`, `LINEAGE_BASE`, `LINEAGE_MODE`, `CHECKOUT`.
- Produces: three profile directories usable as `fleet dispatch --profile <dir>`. Task 4 and Task 5 reference `profiles/worker` and `profiles/coordinator` by path.

- [ ] **Step 1: Write the failing test**

Create `$SP/skills/using-fleet/tests/profiles-render.sh`:

```bash
#!/usr/bin/env bash
# Every shipped profile must DECLARE its kind and render with exactly the context `fleet dispatch` supplies.
#
# The kind is declared and never inferred: three of five profiles once silently became `worker` because it
# was read out of charter prose. And `Profile.render` refuses to emit an artifact containing a literal
# {{TOKEN}}, so an unresolved placeholder is a hard failure here rather than a charter a worker reads.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROFILES="$HERE/../profiles"
FLEET_SRC="${FLEET_SRC:-/home/ubuntu/davis_root/operations/tasks/metaOpt/00000000-07300312-inflight-append-fleetInfraRebuild/src}"

out="$(PYTHONPATH="$FLEET_SRC" python3 - "$PROFILES" <<'PY'
import json, pathlib, sys
from fleet.profiles import Profile

root = pathlib.Path(sys.argv[1])
want = {"worker": "worker", "compaction": "compaction", "coordinator": "coordinator"}
context = {"TITLE": "a title", "INSTANT": "00000000-07300001-inflight-append-probe", "SLOT": "ws1",
           "TODO_ID": "probe-07300001", "BASE": "00000000", "PATH": "/tmp/probe",
           "MILESTONE": "m1", "COORDINATOR": "/tmp/coord",
           "LINEAGE_BASE": "alpha=" + "a" * 40, "LINEAGE_MODE": "code",
           "CHECKOUT": "git -C alpha checkout --detach " + "a" * 40}
bad = 0
for name, kind in sorted(want.items()):
    d = root / name
    if not (d / "profile.json").is_file():
        print(f"MISSING: {d}/profile.json"); bad = 1; continue
    declared = json.loads((d / "profile.json").read_text()).get("kind")
    if declared != kind:
        print(f"KIND: {name} declares {declared!r}, expected {kind!r}"); bad = 1
    try:
        rendered = Profile.load(d).render(context)
    except Exception as exc:                       # noqa: BLE001 - the message is the finding
        print(f"RENDER: {name} did not render: {exc}"); bad = 1; continue
    for artifact in ("charter", "seed"):
        if artifact not in rendered:
            print(f"ARTIFACT: {name} produced no {artifact}"); bad = 1
        elif "{{" in rendered.get(artifact, ""):
            print(f"PLACEHOLDER: {name}/{artifact} still contains {{{{"); bad = 1
    if "{{CHECKOUT}}" not in (d / "seed.txt").read_text() and name == "worker":
        print("CHECKOUT: worker/seed.txt must reference {{CHECKOUT}} so the base instruction is generated")
        bad = 1
print("BAD" if bad else "OK")
PY
)"
printf '%s\n' "$out"
if printf '%s' "$out" | tail -1 | grep -qx OK; then
  echo "PASS: all three profiles declare their kind, render with dispatch's full context, leave no literal {{TOKEN}}, and the worker seed references {{CHECKOUT}}"
  exit 0
fi
echo "FAIL"
exit 1
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
cd /home/ubuntu/davis_root/superpowers
bash skills/using-fleet/tests/profiles-render.sh
```

Expected: three `MISSING: .../profile.json` lines, last line `FAIL`, exit 1.

- [ ] **Step 3: Create the worker profile**

`$SP/skills/using-fleet/profiles/worker/profile.json`:

```json
{
  "kind": "worker",
  "placeholders": ["TITLE", "BASE", "MILESTONE", "COORDINATOR", "CHECKOUT"],
  "requires_clauses": [],
  "invocation_templates": []
}
```

`$SP/skills/using-fleet/profiles/worker/seed.txt`:

```
You are a dispatched worker instant. Your workspace is {{PATH}}.

FIRST, orient yourself — do not guess any of this:
    fleet brief --instant .

You were dispatched for milestone {{MILESTONE}} by the coordinator at {{COORDINATOR}}.
Your CHARTER.md is authoritative for your scope.

=== POSITION YOUR WORKSPACE ===
{{CHECKOUT}}

Load the superpowers:working-as-a-dispatched-instant skill and follow it. It tells you what you
own, what you may never touch, and how to report. Load superpowers:using-fleet for the verb surface.

Report progress with `fleet propose`; every proposal needs evidence. If you are blocked on a decision
only the operator can make, `fleet park --question "..."` rather than stalling.
```

`$SP/skills/using-fleet/profiles/worker/charter.md`:

```markdown
# {{TITLE}}

- **Instant:** {{INSTANT}}
- **Slot:** {{SLOT}}   **Todo id:** {{TODO_ID}}   **Base:** {{BASE}}
- **Milestone:** {{MILESTONE}}   **Coordinator:** {{COORDINATOR}}
- **Lineage base ({{LINEAGE_MODE}}):** {{LINEAGE_BASE}}

## Scope

<!-- The coordinator replaces this section per milestone. This charter is authoritative for scope; the
     seed is generic to the profile. -->

## Acceptance criteria

<!-- One per line, each with the proof that would satisfy it. -->

## Positioning

{{CHECKOUT}}
```

- [ ] **Step 4: Create the compaction and coordinator profiles**

`profiles/compaction/profile.json` — identical shape, `"kind": "compaction"`.
`profiles/coordinator/profile.json` — identical shape, `"kind": "coordinator"`.

`profiles/compaction/seed.txt`:

```
You are a compaction instant. Your workspace is {{PATH}}.

    fleet brief --instant .

A compaction is EXCLUSIVE: while your folder reads -inflight-compact-, every dispatch in this effort
is refused. Finish or abort promptly, and remember the rename is what lifts the freeze.

Load superpowers:maintain-workspace and follow its Compaction section. Load superpowers:using-fleet
for the verb surface.

Base: {{BASE}}   Todo id: {{TODO_ID}}   Slot: {{SLOT}}
```

`profiles/coordinator/seed.txt`:

```
You are the coordinator instant for this effort. Your workspace is {{PATH}}.

    fleet roadmap --instant .
    fleet board
    fleet leases

Load superpowers:coordinating-instants and follow it. Load superpowers:using-fleet for the verb surface.

Your roadmap at .fleet/roadmap.json is the project-level registry. You are its only writer: workers
propose, you apply. Readiness is derived from dependencies, so do not maintain it by hand.

Base: {{BASE}}   Todo id: {{TODO_ID}}   Slot: {{SLOT}}
```

Both `charter.md` files: copy the worker charter above, dropping the `Milestone` / `Coordinator` /
`Lineage base` / `Positioning` lines from the coordinator one (a coordinator has no lineage base), and
dropping only `Milestone` / `Coordinator` from the compaction one.

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd /home/ubuntu/davis_root/superpowers
bash skills/using-fleet/tests/profiles-render.sh
```

Expected: `OK` then `PASS: all three profiles declare their kind…`, exit 0.

- [ ] **Step 6: Dispatch against the real worker profile once, on a private socket**

```bash
cd /home/ubuntu/davis_root/operations/tasks/metaOpt/00000000-07300312-inflight-append-fleetInfraRebuild
. evidence/04-integration/bin/adhoc-sandbox.sh
PATH="$PWD/evidence/04-integration/bin:$PATH"
mkdir -p "$FLEET_ADHOC_BASE/slots/ws1"
( cd "$FLEET_ADHOC_BASE/slots/ws1" && git init -q . && git commit -q --allow-empty -m base )
python3 -m fleet.cli set-golden --path "$FLEET_ADHOC_BASE/slots/ws1" >/dev/null
python3 -m fleet.cli enroll --slot "$FLEET_ADHOC_BASE/slots/ws1" >/dev/null
C=$(python3 -m fleet.cli init --base 00000000 --name coordProbe --porcelain | awk -F'\t' '$1=="path"{print $2}')
python3 -m fleet.cli milestone --instant "$C" --id m1 --title "probe" >/dev/null
W=$(python3 -m fleet.cli dispatch --profile /home/ubuntu/davis_root/superpowers/skills/using-fleet/profiles/worker \
      --title tmplProbe --base 00000000 --optype append --from "$C" --milestone m1 --porcelain \
      | awk -F'\t' '$1=="instant"{print $2}')
cat "$W/.fleet/seed.txt"
tmux -L "$FLEET_TMUX_SOCKET" kill-server 2>/dev/null; rm -rf "$FLEET_ADHOC_BASE"
```

Expected: the seed prints with `m1` and the coordinator's path substituted, and no literal `{{`. The
`{{CHECKOUT}}` block reads "No git lineage was recorded…" because no `--lineage-base` was passed — that is
correct and is the message for that case.

- [ ] **Step 7: Commit**

```bash
cd /home/ubuntu/davis_root/superpowers
git add skills/using-fleet/profiles skills/using-fleet/tests/profiles-render.sh
git commit -m "three fleet profile templates, one per declared kind

worker / compaction / coordinator, each declaring \`kind\` in profile.json — declared and
never inferred, because three of five profiles once silently became \`worker\` when the kind
was read out of charter prose.

The worker seed references {{CHECKOUT}}, so the positioning instruction is GENERATED from the
recorded lineage base and cannot drift from the field the gate checks."
```

---

### Task 3: `coordinating-instants`, rewritten

**Repo:** `$SP`

**Files:**
- Rewrite: `$SP/skills/coordinating-instants/SKILL.md`
- Delete: `$SP/skills/coordinating-instants/brief-contract.md`, `coordinator-registry.md`, `hard-won-lessons.md`
- Keep: `$SP/skills/coordinating-instants/tests/pressure-scenarios.md` (not a `.sh`, not discovered; it is reference material)
- Create: `$SP/skills/coordinating-instants/tests/lint-self.sh`
- Create: `$SP/skills/coordinating-instants/tests/loop.sh`
- Inspect before deleting: `$SP/skills/coordinating-instants/tools/`

**Interfaces:**
- Consumes: `skills/using-fleet/tools/lint-skill.py` (Task 1); `skills/using-fleet/profiles/*` (Task 2); `fleet brief` (Task 0).
- Produces: the coordinator skill. Task 4 links to it by name (`superpowers:coordinating-instants`).

- [ ] **Step 1: Record what the old support files contain before deleting them**

```bash
cd /home/ubuntu/davis_root/superpowers/skills/coordinating-instants
wc -l SKILL.md brief-contract.md coordinator-registry.md hard-won-lessons.md
ls tools/
grep -rn "pdispatch\|dispatch-board\|claude-ws-pool" . | wc -l
```

Expected: four files with line counts; a `tools/` listing; a non-zero count of `pdispatch` references
(these are what make the files obsolete). **If `tools/` contains an executable that nothing else
references, delete it in Step 6; if anything outside this skill references it, leave it and say so in the
commit message.**

- [ ] **Step 2: Write the lint suite (it will fail until the SKILL.md is rewritten)**

Create `$SP/skills/coordinating-instants/tests/lint-self.sh` — identical to
`skills/using-fleet/tests/lint-self.sh` from Task 1 Step 8, except `LINT` resolves across skills:

```bash
#!/usr/bin/env bash
# V1+V2 over this skill. Discovered by bin/superpowers-selftest.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SKILL="$HERE/.."
LINT="$SKILL/../using-fleet/tools/lint-skill.py"

out="$(python3 "$LINT" "$SKILL" 2>&1)"
rc=$?
if [ "$rc" = 0 ]; then
  echo "PASS: every fleet verb named in a code span is registered, and every refusal claim cites a passing case"
  exit 0
fi
printf '%s\n' "$out"
echo "FAIL"
exit 1
```

- [ ] **Step 3: Run it and confirm it fails against the OLD skill**

```bash
cd /home/ubuntu/davis_root/superpowers
bash skills/coordinating-instants/tests/lint-self.sh
```

Expected: `FAIL`, exit 1, with V1 findings naming `pdispatch`-era commands and/or a V2 finding that the
file claims refusals and cites no case. **This is the negative control for the whole lint: it must fail on
the skill as it stands today, or the lint is not measuring anything.** Record the output.

- [ ] **Step 4: Rewrite the SKILL.md**

Frontmatter exactly:

```markdown
---
name: coordinating-instants
description: Use when a Claude session is the standing coordinator of a multi-milestone effort executed by dispatched worker instants, or is resuming that role. Triggers include "you are the coordinator instant", "dispatch one instant per milestone", "what's the fleet status", "resume coordinating", "apply the workers' proposals", "harvest the finished worker".
---
```

Required sections, in this order:

1. **Overview** — the coordinator's roadmap at `.fleet/roadmap.json` is the project-level registry; the
   coordinator is its only writer; workers propose and the coordinator applies; readiness is derived.
2. **Announce at start** — `"I'm using the coordinating-instants skill to coordinate this effort."`
3. **The loop** — the nine-phase table from spec §3, verbatim in structure: Observe / Reconcile / Decide /
   Raise / Dispatch / Receive / Escalate / Abandon / Close out, each with the exact command.
4. **Two judgements the tool cannot make** — act on `attention`, report `info`; read porcelain, never prose.
5. **The endgame** — an item that outlives the effort needs BOTH a documented issue and
   `fleet milestone`. State that there is no reassignment and why.
6. **What the coordinator never does** — the four-item list from spec §3.
7. **What is measured and what is argued** — the honest paragraph: which properties have integration
   cases, and that `§P` has never run so a real dispatch against a real `claude` is unproven.
8. **Hard-won rules** — the table from spec §5, each row one line.

Every refusal claim needs a `<!-- v2-cite: <slug> <CASE-ID> -->` comment. Use these, all verified `PASS`:

```
<!-- v2-cite: worker-cannot-move-roadmap H2 -->
<!-- v2-cite: prose-is-not-state F3 -->
<!-- v2-cite: declaration-does-free-the-cap F2 -->
<!-- v2-cite: unclaimed-session-never-reaped J7 -->
<!-- v2-cite: close-refuses-queued-pane J8 -->
<!-- v2-cite: folder-compaction-freezes F11 -->
<!-- v2-cite: harvest-commits-whole J2 -->
<!-- v2-cite: carry-across-runs-on-fleet H9 -->
```

Mark the one proposed verb if you reference it: `<!-- v1-proposed: brief -->` is **not** needed once Task 0
has landed — `brief` is a real verb by then. Do not add the marker for it.

- [ ] **Step 5: Write the V3 walkthrough**

Create `$SP/skills/coordinating-instants/tests/loop.sh`:

```bash
#!/usr/bin/env bash
# V3 — the loop this skill documents must actually run.
#
# Against a scratch store on a PRIVATE tmux socket, because `fleet dispatch` starts a real session named
# dt-<name> and running that on the default server is the one act the operator's rules forbid outright.
# Dispatch here is --dry-run for the same reason: this suite proves the SEQUENCE is real, not that a worker
# can be launched, and the launch is covered by the fleet repo's own integration section.
set -uo pipefail
FLEET_SRC="${FLEET_SRC:-/home/ubuntu/davis_root/operations/tasks/metaOpt/00000000-07300312-inflight-append-fleetInfraRebuild/src}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PROFILE="$HERE/../../using-fleet/profiles/worker"
TMP="$(mktemp -d)"
trap 'tmux -L "itfleet-loop-$$" kill-server 2>/dev/null; rm -rf "$TMP"' EXIT

export FLEET_HOME="$TMP/home" FLEET_INSTANTS="$TMP/instants" FLEET_TMUX_SOCKET="itfleet-loop-$$"
export PYTHONPATH="$FLEET_SRC"
mkdir -p "$FLEET_HOME" "$FLEET_INSTANTS"
f() { python3 -m fleet.cli "$@"; }

fails=0
step() {                  # step <label> <expected-rc> <cmd...>
  local label="$1" want="$2"; shift 2
  "$@" > "$TMP/$label.out" 2>&1
  local rc=$?
  if [ "$rc" != "$want" ]; then
    printf '  STEP %s: exit %s, wanted %s\n' "$label" "$rc" "$want"
    sed 's/^/      /' "$TMP/$label.out" | tail -4
    fails=1
  fi
}

C="$(f init --base 00000000 --name loopCoord --porcelain | awk -F'\t' '$1=="path"{print $2}')"
[ -n "$C" ] || { echo "could not create the coordinator instant"; echo FAIL; exit 1; }

# Raise -> observe -> decide, exactly as the skill's loop table says.
step raise-m1     0 f milestone --instant "$C" --id m1 --title "the enabling work" --status done --evidence e/1
step raise-m2     0 f milestone --instant "$C" --id m2 --title "the real work" --dep m1
step raise-m3     0 f milestone --instant "$C" --id m3 --title "the tail" --dep m2
step roadmap      0 f roadmap --instant "$C" --porcelain
step board        0 f board --porcelain
step leases       0 f leases --porcelain
step reconcile    0 f reconcile --porcelain

# The DERIVED readiness the skill tells the coordinator to read rather than maintain.
ready="$(f roadmap --instant "$C" --porcelain | awk -F'\t' '$1=="not-ready"{print $2}' | sort | tr '\n' ' ')"
case "$ready" in
  *m3*) : ;;
  *) printf '  READINESS: m3 should be reported not-ready while m2 is unlanded; got %s\n' "$ready"; fails=1 ;;
esac

# A dep that does not exist is refused where the name is written.
step bad-dep      2 f milestone --instant "$C" --id m9 --title typo --dep nosuchdep
# Dispatch onto a NOT-READY milestone is refused; onto a ready one it is admissible (dry-run).
step dispatch-m3  4 f dispatch --profile "$PROFILE" --title tail --base 00000000 --optype append \
                       --from "$C" --milestone m3 --dry-run
step dispatch-m2  0 f dispatch --profile "$PROFILE" --title real --base 00000000 --optype append \
                       --from "$C" --milestone m2 --dry-run
# Receive: a proposal into this roadmap, then apply. Readiness must recompute.
step propose      0 f propose --instant "$C" --milestone m2 --status done --evidence e/2
step apply        0 f apply --instant "$C" --milestone m2
after="$(f roadmap --instant "$C" --porcelain | awk -F'\t' '$1=="not-ready"{print $2}' | tr '\n' ' ')"
case "$after" in
  *m3*) printf '  RECOMPUTE: m3 is still not-ready after its dep landed; got %s\n' "$after"; fails=1 ;;
esac
# Escalate and clear.
step park         0 f park --instant "$C" --question "which baseline is the ruler?"
step unpark       0 f unpark --instant "$C"

if [ "$fails" = 0 ]; then
  echo "PASS: the documented loop runs end to end — raise/observe/decide, a bad dep refused, dispatch refused onto an unready milestone and admissible onto a ready one, propose+apply moving the status, readiness recomputing, park/unpark"
  exit 0
fi
echo "FAIL"
exit 1
```

- [ ] **Step 6: Delete the obsolete support files and run everything**

```bash
cd /home/ubuntu/davis_root/superpowers
git rm -q skills/coordinating-instants/brief-contract.md \
          skills/coordinating-instants/coordinator-registry.md \
          skills/coordinating-instants/hard-won-lessons.md
bash skills/coordinating-instants/tests/lint-self.sh
bash skills/coordinating-instants/tests/loop.sh
if bash bin/superpowers-selftest; then echo "SELFTEST GREEN"; else echo "SELFTEST RED"; fi
```

Expected: both suites `PASS`, `SELFTEST GREEN`. If `loop.sh` fails on `dispatch-m3` with exit 0 instead of
4, the milestone was ready when it should not have been — check that `m2` had not already been applied by
an earlier run leaking into `$TMP` (it cannot; `$TMP` is fresh per run, so investigate the roadmap output
in `$TMP/roadmap.out`).

- [ ] **Step 7: Commit**

```bash
cd /home/ubuntu/davis_root/superpowers
git add skills/coordinating-instants
git commit -m "coordinating-instants: rewritten on fleet

345 lines describing pdispatch, most of it rules the coordinator had to remember —
don't over-dispatch, don't write a worker's status, check the board first. Every one of
those is now a refusal in fleet, so the skill states the command and moves on.

Three support files deleted (brief-contract, coordinator-registry, hard-won-lessons):
their mechanisms are fleet's roadmap, records and guards.

Two suites: lint-self.sh (V1+V2) and loop.sh (V3), which runs the documented loop against
a scratch store on a private tmux socket. lint-self.sh FAILED against the old SKILL.md
before the rewrite — recorded, because a lint nobody has seen fire is decoration."
```

---

### Task 4: `working-as-a-dispatched-instant`

**Repo:** `$SP`

**Files:**
- Create: `$SP/skills/working-as-a-dispatched-instant/SKILL.md`
- Create: `$SP/skills/working-as-a-dispatched-instant/tests/lint-self.sh`
- Create: `$SP/skills/working-as-a-dispatched-instant/tests/contract.sh`

**Interfaces:**
- Consumes: `lint-skill.py` (Task 1); `fleet brief` (Task 0); `fleet base-check`.
- Produces: the worker skill. `skills/using-fleet/profiles/worker/seed.txt` (Task 2) already names it, so
  this task's completion is what makes that seed line true.

- [ ] **Step 1: Write the contract suite first (it fails until the SKILL.md exists)**

Create `$SP/skills/working-as-a-dispatched-instant/tests/contract.sh`:

```bash
#!/usr/bin/env bash
# The worker's contract, asserted against the fleet surface rather than against prose.
#
# Each case is a claim this skill makes. If fleet stops refusing one of these, the skill is wrong and this
# suite says so — which is the point: the skill's promises and the tool's behaviour cannot drift apart
# silently.
set -uo pipefail
FLEET_SRC="${FLEET_SRC:-/home/ubuntu/davis_root/operations/tasks/metaOpt/00000000-07300312-inflight-append-fleetInfraRebuild/src}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export FLEET_HOME="$TMP/home" FLEET_INSTANTS="$TMP/instants" PYTHONPATH="$FLEET_SRC"
mkdir -p "$FLEET_HOME" "$FLEET_INSTANTS"
f() { python3 -m fleet.cli "$@"; }
fails=0
expect() {                # expect <label> <want-rc> <cmd...>
  local label="$1" want="$2"; shift 2
  "$@" > "$TMP/$label.out" 2>&1
  local rc=$?
  [ "$rc" = "$want" ] || { printf '  %s: exit %s, wanted %s\n' "$label" "$rc" "$want"
                           sed 's/^/      /' "$TMP/$label.out" | tail -3; fails=1; }
}

W="$(f init --base 00000000 --name contractWorker --porcelain | awk -F'\t' '$1=="path"{print $2}')"
[ -n "$W" ] || { echo "could not create the instant"; echo FAIL; exit 1; }
f milestone --instant "$W" --id c1 --title "the work" >/dev/null 2>&1

# CLAIM: the worker can orient itself with one read-only command.
expect brief 0 f brief --instant "$W" --porcelain
# CLAIM: evidence is mandatory — a proposal without it is a claim, not a report.
expect no-evidence 2 f propose --instant "$W" --milestone c1 --status running
# CLAIM: a worker cannot create a milestone on someone else's roadmap by proposing about it.
expect invented-milestone 2 f propose --instant "$W" --milestone neverAdded --status done --evidence e/1
# CLAIM: completing without a review round is refused, and the message says UNDECIDABLE not NOT-READY.
f complete --instant "$W" > "$TMP/no-review.out" 2>&1
if grep -qi 'undecidable' "$TMP/no-review.out"; then :; else
  printf '  no-review: complete did not refuse as UNDECIDABLE\n'; sed 's/^/      /' "$TMP/no-review.out" | tail -3; fails=1
fi
# CLAIM: park records a question; an empty one is not a park.
expect empty-park 2 f park --instant "$W" --question ""
expect real-park 0 f park --instant "$W" --question "which baseline is the ruler?"
expect unpark 0 f unpark --instant "$W"

if [ "$fails" = 0 ]; then
  echo "PASS: every contract this skill states is enforced by fleet — brief orients read-only, evidence is mandatory, an unknown milestone is refused, completing with no review round is UNDECIDABLE rather than not-ready, and an empty park is refused"
  exit 0
fi
echo "FAIL"
exit 1
```

- [ ] **Step 2: Run it and confirm which claims already hold**

```bash
cd /home/ubuntu/davis_root/superpowers
bash skills/working-as-a-dispatched-instant/tests/contract.sh
```

Expected: `PASS` — every claim is about `fleet` behaviour that Task 0 and the prerequisite work already
deliver. **If `brief` exits non-zero, Task 0 is not complete; stop and finish it.**

- [ ] **Step 3: Write the SKILL.md**

Frontmatter exactly:

```markdown
---
name: working-as-a-dispatched-instant
description: Use when this session IS a dispatched worker instant — created by `fleet dispatch`, working in a leased slot, reporting to a coordinator. Triggers include "you are a dispatched worker", "your CHARTER.md is authoritative", ".fleet/seed.txt", "propose your status", "which milestone am I on", resuming inside an instant folder.
---
```

Required sections, in this order:

1. **Overview** — you are one instant among several; your coordinator owns the roadmap; you report and it
   applies.
2. **Announce at start** — `"I'm using the working-as-a-dispatched-instant skill."`
3. **Your first two commands** — `fleet brief --instant .` (the six rows from spec §4) then
   `fleet base-check --id <your todo id>`, with the four-position table (at-base / descendant / present /
   absent) and why a descendant is fine.
4. **What you own, and what you may never touch** — the two-column table from spec §4.
5. **The three things you do** — Report / Get stuck / Finish, with the exact commands.
6. **Positioning your workspace** — the slot is a duplicate of the golden and nothing moved it; your seed
   printed the commands; `propose --status done` and `complete` refuse if you are not there.
7. **Hard-won rules** — the table from spec §5.
8. **Where your workspace contract comes from** — link `superpowers:maintain-workspace` for the Four
   Invariants. Do **not** restate them.

Citations, all verified `PASS`:

```
<!-- v2-cite: evidence-is-mandatory H4 -->
<!-- v2-cite: worker-cannot-move-roadmap H2 -->
<!-- v2-cite: done-from-wrong-base-refused LB2 -->
<!-- v2-cite: gate-opens-when-positioned LB3 -->
<!-- v2-cite: report-reaches-coordinator H10 -->
```

- [ ] **Step 4: Add the lint suite**

Create `$SP/skills/working-as-a-dispatched-instant/tests/lint-self.sh` — byte-identical to
`skills/coordinating-instants/tests/lint-self.sh` from Task 3 Step 2 (the `LINT` path is relative to the
skill and resolves the same way).

- [ ] **Step 5: Run both suites and the whole selftest**

```bash
cd /home/ubuntu/davis_root/superpowers
bash skills/working-as-a-dispatched-instant/tests/lint-self.sh
bash skills/working-as-a-dispatched-instant/tests/contract.sh
if bash bin/superpowers-selftest; then echo "SELFTEST GREEN"; else echo "SELFTEST RED"; fi
```

Expected: both `PASS`, `SELFTEST GREEN`.

- [ ] **Step 6: Commit**

```bash
cd /home/ubuntu/davis_root/superpowers
git add skills/working-as-a-dispatched-instant
git commit -m "working-as-a-dispatched-instant: the worker's contract as its own skill

A worker should not have to read the coordinator's role to learn its own. Its first two
commands are \`fleet brief\` and \`fleet base-check\`, both read-only, because the
alternative first instruction was hand-parsing .fleet/origin.json.

contract.sh asserts each promise against fleet itself rather than against prose, so the
skill's claims and the tool's behaviour cannot drift apart silently."
```

---

### Task 5: `dispatching-subagents`, and deleting `dispatchInstants`

**Repo:** `$SP`

**Files:**
- Rename: `$SP/skills/dispatching-parallel-agents/` → `$SP/skills/dispatching-subagents/`
- Rewrite: `$SP/skills/dispatching-subagents/SKILL.md` (frontmatter `name` must match the directory)
- Delete: `$SP/skills/dispatchInstants/` entirely, including `base-check.sh` and `tests/*.sh`
- Create: `$SP/skills/dispatching-subagents/tests/lint-self.sh`
- Grep-and-fix: every reference to the old skill names anywhere in `$SP`

**Interfaces:**
- Consumes: `lint-skill.py` (Task 1).
- Produces: nothing later tasks depend on. This is the last task.

- [ ] **Step 1: Find every inbound reference before moving anything**

```bash
cd /home/ubuntu/davis_root/superpowers
grep -rln "dispatching-parallel-agents\|dispatchInstants" \
  --include='*.md' --include='*.sh' --include='*.json' --include='*.py' . | sort
```

Expected: a file list. **Every one of these must be updated in Step 4 — a rename that leaves a dangling
skill reference makes the skill unloadable, and nothing in this repo would catch it.** Record the list.

- [ ] **Step 2: Do the rename with git so history follows**

```bash
cd /home/ubuntu/davis_root/superpowers
git mv skills/dispatching-parallel-agents skills/dispatching-subagents
git rm -r -q skills/dispatchInstants
git status --short | head -20
```

Expected: renames and deletions staged; no untracked leftovers under `skills/dispatchInstants`.

- [ ] **Step 3: Rewrite the SKILL.md**

Frontmatter exactly (the `name` MUST equal the directory name or the skill will not load):

```markdown
---
name: dispatching-subagents
description: Use when parallelising work across subagents INSIDE this session — independent research, fan-out review, or several small tasks with no shared files. Triggers include "dispatch subagents", "run these in parallel", "fan out", "one agent per file". For separate `claude` processes in leased workspaces, use coordinating-instants instead.
---
```

Required sections:

1. **Overview** — subagents live inside one session and share its context budget; they are not instants.
2. **The boundary, stated once** — a table contrasting subagents with instants:
   | | subagent | dispatched instant |
   |---|---|---|
   | lives in | this session | its own `claude` process |
   | workspace | this one | a leased slot |
   | state | none of its own | its own instant folder + `.fleet/` |
   | dispatched by | the Agent tool | `fleet dispatch` |
   | right for | fan-out reading, independent review, small parallel edits | a milestone of real work |
3. **When NOT to use subagents** — shared files, sequential dependencies, anything needing its own
   workspace or a review gate. Point at `superpowers:coordinating-instants`.
4. **How to dispatch them** — parallel tool calls in one message; one writer per file; declare ownership by
   function where a module is shared.
5. **Announce at start.**

This skill names no `fleet` verbs, so V1 has nothing to check and V2 has no refusal claims to cite — that is
a legitimate clean pass, not a vacuous one, because the lint distinguishes "no claims" from "claims without
citations".

- [ ] **Step 4: Update every inbound reference from Step 1**

For each file in Step 1's list, replace `dispatching-parallel-agents` → `dispatching-subagents`, and remove
or repoint references to `dispatchInstants` (its replacement is `coordinating-instants` for the coordinator
side and `working-as-a-dispatched-instant` for the worker side). Then confirm none remain:

```bash
cd /home/ubuntu/davis_root/superpowers
if grep -rn "dispatching-parallel-agents\|dispatchInstants" \
    --include='*.md' --include='*.sh' --include='*.json' --include='*.py' . ; then
  echo "STALE REFERENCES REMAIN — fix them before committing"
else
  echo "no stale references"
fi
```

Expected: `no stale references`.

- [ ] **Step 5: Add the lint suite and run the whole selftest**

Create `$SP/skills/dispatching-subagents/tests/lint-self.sh` — byte-identical to Task 3 Step 2's file.

```bash
cd /home/ubuntu/davis_root/superpowers
bash skills/dispatching-subagents/tests/lint-self.sh
if bash bin/superpowers-selftest; then echo "SELFTEST GREEN"; else echo "SELFTEST RED"; fi
```

Expected: `PASS`, `SELFTEST GREEN`. The suite count should have dropped by the three
`skills/dispatchInstants/tests/*.sh` files and risen by the new ones.

- [ ] **Step 6: Commit**

```bash
cd /home/ubuntu/davis_root/superpowers
git add -A skills/ commands/ docs/ README.md 2>/dev/null || git add -A
git commit -m "dispatching-subagents (renamed), and dispatchInstants deleted

Renamed dispatching-parallel-agents so the pair is obvious: dispatching-subagents is
inside one session; coordinating-instants is separate claude processes in leased
workspaces. The old name did not say which.

dispatchInstants deleted, base-check.sh included — its mechanism is \`fleet dispatch\` and
its base-check is \`fleet base-check\`, wired into a gate on propose/complete rather than
left as a script somebody has to remember to run.

bin/'s pdispatch executables are deliberately NOT deleted: they are outward state and
another effort may still invoke them."
```

---

### Task 6: Close the loop — the spec's own claims, verified

**Repo:** `$SP`

**Files:**
- Modify: `$SP/docs/superpowers/specs/2026-07-30-fleet-skills-design.md` (status line only)
- Create: `$SP/skills/using-fleet/tests/every-skill-linted.sh`

**Interfaces:**
- Consumes: every skill from Tasks 1, 3, 4, 5.
- Produces: nothing.

- [ ] **Step 1: Write the coverage suite**

Create `$SP/skills/using-fleet/tests/every-skill-linted.sh`:

```bash
#!/usr/bin/env bash
# Every fleet skill must carry a lint suite. Otherwise a skill can be added with no V1/V2 at all, and the
# absence of a finding would read as a clean bill of health — "absence is never success" applied to the
# coverage of the checks themselves rather than to their results.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SKILLS="$HERE/../.."
WANT="using-fleet coordinating-instants working-as-a-dispatched-instant dispatching-subagents"
missing=""
for s in $WANT; do
  [ -d "$SKILLS/$s" ] || { missing="$missing $s(absent)"; continue; }
  [ -f "$SKILLS/$s/tests/lint-self.sh" ] || missing="$missing $s(no-lint)"
done
if [ -n "$missing" ]; then
  printf 'skills without a lint suite:%s\n' "$missing"
  echo "FAIL"
  exit 1
fi
echo "PASS: all four fleet skills exist and each carries a tests/lint-self.sh, so none can be added or changed without V1+V2 running over it"
exit 0
```

- [ ] **Step 2: Run the full selftest one final time**

```bash
cd /home/ubuntu/davis_root/superpowers
bash bin/superpowers-selftest
```

Expected: `VERDICT: GREEN`, with every new suite's own verdict line visible (the Task 1 Step 1 change).
Record the suite count and the full output — this is the artifact behind "the skills are verified".

- [ ] **Step 3: Mark the spec implemented and commit**

In `$SP/docs/superpowers/specs/2026-07-30-fleet-skills-design.md`, change the status line:

```markdown
- **Status:** implemented 2026-07-30; V1–V3 green via `bin/superpowers-selftest`. `§P`/AC-11 (a real dispatch against a real `claude`) remains UNRUN, so behavioural validity is still an argument and not a measurement.
```

```bash
cd /home/ubuntu/davis_root/superpowers
git add docs/superpowers/specs/2026-07-30-fleet-skills-design.md \
        skills/using-fleet/tests/every-skill-linted.sh
git commit -m "every fleet skill carries a lint suite, and the spec records what is still unproven

every-skill-linted.sh fails if a fleet skill exists without tests/lint-self.sh — otherwise
a skill could be added with no V1/V2 and the absence of findings would read as clean.

The spec's status line now says plainly that §P/AC-11 has never run, so 'the skills work'
remains an argument. V1-V3 prove the commands exist, the refusals are real and the
documented loop executes; none of them proves a model reading the prose does the right thing."
```

---

## Self-Review

**1. Spec coverage.** Every spec section maps to a task: §0 the walkthrough → Task 3 §3 of the SKILL (the
loop table) and Task 4 (the worker half); §1 the skill set → Tasks 1, 3, 4, 5 plus Task 2's templates; §2
registry → Task 3 sections 1 and 5; §3 loop → Task 3 Step 4 sections 3–6 and Task 3's `loop.sh`; §4 worker
contract → Task 0 (`fleet brief`) and Task 4; §5 gaps and honesty rules → Task 3 sections 7–8 and Task 4
section 7; §6 verification → Task 1 (V1+V2 tool), Task 3 `loop.sh` (V3), Task 6 (coverage). The spec's
"Explicitly left alone" (`bin/` untouched) is honoured in Task 5's commit message and in the Global
Constraints. The spec's suggested five-phase order is followed, with `fleet brief` inserted as Task 0 per the
handoff instruction.

**2. Placeholder scan.** No `TBD`/`TODO`. Two places delegate prose to the implementer — Task 1 Step 7 and
Task 3 Step 4, Task 4 Step 3, Task 5 Step 3 — and each specifies the exact required sections, their order,
and the exact citation markers that must appear, with the V1/V2/V3 suites as the acceptance gate. That is a
specification, not a placeholder: the tests fail if the content is absent. Where a step changes code, the
code is present in full.

**3. Type consistency.** `lint-skill.py <skill-dir>` with env `FLEET_SRC` / `FLEET_RESULTS` and exits 0/1/2
is used identically in Tasks 1, 3, 4, 5. Marker syntax `<!-- v1-proposed: verb -->` and
`<!-- v2-cite: slug CASE-ID -->` is defined once in Task 1's Interfaces and used unchanged everywhere. The
`tests/lint-self.sh` wrapper is byte-identical across Tasks 3, 4, 5 and stated as such. `fleet brief`'s row
kinds (`origin`, `milestone`, `phase`, `review`, `destination`, `outstanding`, `population`) are asserted in
Task 0 Step 1 and referenced by the same names in Task 4 Step 3. Profile paths
`skills/using-fleet/profiles/{worker,compaction,coordinator}` are created in Task 2 and consumed by exact
path in Task 3's `loop.sh` and Task 2 Step 6.

**One gap found and fixed during review:** the original Task 3 had no negative control for the lint. Step 3
now runs `lint-self.sh` against the **old** SKILL.md and requires it to FAIL before the rewrite, because a
lint that has only ever been seen to pass is decoration.
