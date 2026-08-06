---
name: releasing-fleet
description: Use when cutting, verifying, promoting or deploying a fleet release — the four-verb chain, the traps that cost a gate run, and when the suites can be skipped. Triggers include "cut a release", "release fleet", "deploy 0.3.x", "release-verify came back INCONCLUSIVE", "do I need to run the suites", "promote refused", "ship the skills change".
---

# Releasing fleet

## Overview

A release is an **immutable export of a tag**, plus a verdict, plus a `current` symlink saying which one
is live. Four states: cut → verified → promoted → deployed.

Two facts decide almost every question below, and neither is guessable:

1. **A release is the WHOLE repository, not `fleet/`.** `git archive` ships `skills/`, `commands/`,
   `hooks/`, `docs/` and the plugin manifest. The deployed export **is** the marketplace source Claude
   Code loads skills from (`extraKnownMarketplaces` → `fleet-releases/current`). Deploying changes
   everyone's skills, not just the CLI.
2. **The gate is a local two-suite run, not CI.** There is no GitHub CI on this repo. `release-verify` is
   the only thing standing between a bad tree and every session on the box.

**Announce at start:** "I'm using the releasing-fleet skill for the release chain."

## The chain

```bash
. /path/to/superpowers/scripts/fleet-env.sh
REPO=/path/to/superpowers
FLEET=$REPO/bin/fleet          # NOT a bare `fleet` — see Trap 1

$FLEET release-cut     --version X.Y.Z --repo "$REPO" --releases "$FLEET_RELEASES" --notes "…"
$FLEET release-verify  --version X.Y.Z --releases "$FLEET_RELEASES"
$FLEET release-promote --version X.Y.Z --releases "$FLEET_RELEASES"
$FLEET release-deploy  --version X.Y.Z --releases "$FLEET_RELEASES" --reason "…"
```

`--dry-run` exists on every mutating verb. Use it on `release-cut` — it names the commit, the tag and the
commit count without writing anything.

## Do the suites need to run?

Usually you do not have to care: `release-verify` decides and returns in ~2 seconds when they are not
needed, recording verdict **`EXEMPT`**. `release-promote` accepts `EXEMPT`, so there is **no `--force` and
no per-release judgement call**.

| Changed since the last GREEN release | Verdict | Time |
|---|---|---|
| only `docs/`, `assets/`, root docs, or skills **other than** `using-fleet` | `EXEMPT` | seconds |
| anything else — `fleet/`, `scripts/`, `hooks/`, `bin/`, `tests/`, `skills/using-fleet/`, a new directory | suites run | ~24 min |

**`skills/using-fleet/**` is deliberately NOT exempt.** Two suite call-sites read it: `test_contracts.py`
asserts verb parity against its `SKILL.md` in both directions, and `fleet/it/run-P.sh` copies its
`profiles/worker` fixture. "Outside `fleet/`" is not the same as "not covered by the suites".

The classifier is an allowlist (`fleet/src/fleet/release_scope.py`) — an unrecognised path runs the
suites. Never widen it to make a release faster; the whole value is that it cannot be wrong in the
dangerous direction. `--full` never exempts, and an `EXEMPT` verdict cannot promote a minor/major bump.

Read `evidence/EXEMPTION.tsv` to check the decision by hand — it names both tags and every changed path.

## The traps

Each of these cost a real gate run or a blocked release.

**Trap 1 — `PATH` resolves `fleet` to the DEPLOYED copy, which mutating release verbs refuse.**
`fleet-env.sh` deliberately puts `$FLEET_RELEASES/current/bin` first ("through `current`, never the
checkout"). But `_refuse_if_self_deployed` rejects every *mutating* release verb whose module lives inside
the release area — the tool that moves `current` must not be the thing `current` points at. **Call the
checkout's binary by absolute path.** Read-only verbs (`release-status`, `-list`, `-history`) are exempt
and may come from either.

**Trap 2 — the cut creates the tag; do not pre-create it.** `release-cut --help` says "the tag becomes
`fleet/vX.Y.Z`", which reads like a precondition. It is not. Under its lock the cut writes the changelog
section, rewrites `__version__`, commits `fleet vX.Y.Z`, then makes the **annotated** tag — and
`annotated_tag` *refuses* if it already exists. Pre-creating it hard-blocks the release. Make only your
ordinary content commits; touch neither `fleet/CHANGELOG.md` nor `__version__` (a dirty tree is refused
too).

**Trap 3 — be SILENT while the gate runs.** `pgrep -x claude` matches on `comm`, and a forked child
carries its parent's `comm` until it execs — so **every tool call an agent session makes creates a process
named `claude` for ~600 ms**. The IT suite's `A6` and `ISOLATION-*-claude-count` cases snapshot that count
at each section boundary and require equality. Polling a run you are driving fails it. Start the verify in
the background and make **zero** tool calls until it reports; a background shell that already exec'd is
safe, because its own forks are `comm=bash`.

**Trap 4 — quiet the box first.** A **COMPLETE** worker still holding a slot with a live pane is a
scheduled contamination event: it exits mid-run, moving both the board and the claude count. Harvest
finished workers before cutting. Other people's live sessions are an uncontrollable residual risk — a gate
run here is not reliably repeatable.

**Trap 5 — a re-verify archives the previous attempt FOR you; read the archive, don't recreate it.**
Since 0.3.8 both `release-verify` paths (the suites and `EXEMPT`) move everything already in
`<release>/.release/evidence/` into `evidence/attempt-<n>-<verdict>/` before writing, so every attempt
starts from an empty directory. Nothing to copy by hand — and a GREEN run can no longer inherit an earlier
attempt's `it-FAILURES.txt` or `it-cited/`. **Do this instead:** after a re-run, `ls` the evidence dir.
`attempt-1-INCONCLUSIVE/` beside a current GREEN is the record of *why* you re-ran, and it is the first
thing to read when a gate took two goes.

> Releases below 0.3.8 carry the mixed state this rule used to guard by hand: `0.3.3` ships a GREEN verdict
> beside an `it-FAILURES.txt` naming two failures, and `0.3.6` ships an `EXEMPT` verdict beside a
> `hermetic.log` from an abandoned attempt. Check mtimes before believing the evidence of any of them.

**Trap 6 — the documented hermetic command is not runnable as written.**
`HERMETIC_COMMAND = "python3 -m unittest discover -s tests -q"` needs an env the constant does not
mention. From `$REPO/fleet`:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO/fleet/src" python3 -m unittest discover -s tests -q
```

**Trap 7 — do not start a release near 03:30 UTC.** A cron rebases `live` onto upstream then, rewriting
every commit the fork carries. The pipeline is tag-based for exactly this reason, but a run straddling it
is asking for trouble.

## Reading the verdict

**Never trust `run-all.sh`'s exit status.** It has no final `exit`, so it returns 0 however many sections
failed — release `0.1.1` recorded GREEN over 7 FAIL rows that way (`SI-38`). **Never read the merged
`it-RESULTS.tsv`** either; it keeps rows from runs that did not happen this time.

Read the FAIL rows of **this run's own** per-runner registers:

```bash
EV="$FLEET_RELEASES/fleet-vX.Y.Z/.release/evidence"
awk -F'\t' '$2=="FAIL"{print FILENAME" :: "$1" :: "$4}' "$EV"/it-RESULTS-closeout-*.tsv
```

| Verdict | Meaning | What to do |
|---|---|---|
| `GREEN` | both suites passed | promote |
| `EXEMPT` | not required — nothing either suite reads changed | promote |
| `RED` | a suite failed and the live-subject set did **not** move | a real defect; fix it |
| `INCONCLUSIVE` | a suite failed **and** the box moved during the run | contamination; re-run (Trap 5) |

`INCONCLUSIVE` exists so a false RED is never written into a release's evidence permanently. Diff
`live-subjects-before.tsv` against `live-subjects-after.tsv` to see what moved.

**The overall verdict is in the file, from 0.3.8 on** — `awk -F'\t' '$1=="verdict"{print $2}' "$EV/VERDICT.tsv"`.
Before that only per-suite `GREEN`/`RED` rows were written, so an INCONCLUSIVE run left evidence
byte-identical to a genuine RED: release `0.3.4` is the instance, recorded RED with `live-subject set
CHANGED during the run` in the note. A release below 0.3.8 has no `verdict` row and its archive, if any,
is named `attempt-<n>-unknown`.

**Do not re-roll until green.** Re-run only when you have *identified* the contaminating cause and
removed it. If you cannot, leave the release at CANDIDATE and hand back a documented blocker — a gate you
retry until it passes is not a gate.

## What the release says about itself

A cut stamps **two** version lineages and writes down what it ships:

- `fleet/src/fleet/__init__.py` gets the fleet version (`0.3.8`).
- The seven manifests in `.version-bump.json` get `<upstream core>+fleet.<fleet version>` —
  `6.2.0+fleet.0.3.8`. Build metadata, so the number never decreases and the upstream fork point survives.
  This is what `claude plugin list` reports; before 0.3.8 it read `6.2.0` at every release ever cut.
- `<release>/.release/PAYLOAD.tsv` records which areas the release actually moves, and the changelog
  section says the same in prose, naming the individual skills. `release-status` reports it for the
  deployed release, so "which skills am I running" is answerable from the box alone:

```bash
$FLEET release-status --releases "$FLEET_RELEASES" --porcelain    # payload / skills rows
awk -F'\t' '$1=="area"' "$FLEET_RELEASES/fleet-vX.Y.Z/.release/PAYLOAD.tsv"
```

## Choosing the version

Patch for anything ordinary. A minor/major bump requires a `--full` roster verify to promote, and cannot
be `EXEMPT` at all. Retention is 10 releases: the oldest is pruned at the next cut, never the deployed
one — the tag is the durable artifact and a cut rebuilds the export.

## Rolling back

```bash
$FLEET release-rollback --releases "$FLEET_RELEASES" --reason "…"   # --to, or the register decides
```

`release-status` answers "what is live right now"; `release-history` is the append-only register of every
deploy and rollback, with who, when and why. Every deploy and rollback needs a real `--reason` — it is
what the next person reads when they ask why `current` moved.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| `fleet release-cut …` straight from `PATH` | Absolute path to the **checkout's** `bin/fleet` (Trap 1) |
| Creating `fleet/vX.Y.Z` before cutting | The cut makes it; pre-creating refuses (Trap 2) |
| Hand-editing `CHANGELOG.md` / `__version__` / a plugin manifest before a cut | The cut writes all of them; the edit only makes the tree dirty, which is refused |
| Polling the gate run from the session driving it | Silence protocol (Trap 3) |
| Copying the evidence out by hand before re-verifying | The tool archives it: `evidence/attempt-<n>-<verdict>/` (Trap 5) |
| Reading the verdict off `run-all.sh` or `it-RESULTS.tsv` | Per-runner `it-RESULTS-closeout-*.tsv` FAIL rows |
| `release-deploy --force` to skip a slow gate | That is what `EXEMPT` is for; `--force` records the release UNVERIFIED |
| Treating `INCONCLUSIVE` as RED, or as "just retry" | Identify the mover, remove it, then re-run |
| Widening the inert set to make a release exempt | The allowlist's narrowness IS the safety property |
| Assuming a release only ships the CLI | It ships every skill; deploying changes what sessions load |
