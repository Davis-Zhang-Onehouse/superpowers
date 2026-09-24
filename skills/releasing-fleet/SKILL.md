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

After a deploy, `scripts/release-postflight.sh <version>` proves it actually reached every root that
shares this release area — `current`'s target, each root's marketplace path, every `.version-bump.json`
manifest, and the deployed evidence's own verdict — **without invoking `fleet` at all**. That is
deliberate: on this box `davis2_root/fleet-releases` is a symlink alias of this release area, and
`fleet release-status` run from that second root reports relative to whichever `FLEET_HOME` it was
handed, which once printed a misleading `current DEV / head unknown` for a deployment that was perfectly
correct. Postflight answers the box-relative question directly instead of inheriting the artifact that
caused the confusion, and it is read-only — it proves a deployment, it never performs one.

**Codex workers follow the deploy too, once each root is set up (FB-111).** A codex worker gets the superpowers
skills through one link, `<root>/.codex/skills/superpowers -> $FLEET_RELEASES/current/skills`. Because it names
`current`, a deploy moves codex and claude together and there is nothing to refresh. Each root that runs codex
workers needs it installed once (it is the operator's config, so do a dry run first):

```bash
bash "$REPO/scripts/fleet-codex-skills.sh" --codex-home <root>/.codex --releases "$FLEET_RELEASES" --dry-run
bash "$REPO/scripts/fleet-codex-skills.sh" --codex-home <root>/.codex --releases "$FLEET_RELEASES"
```

Postflight's assertion 6 checks the link on every root that has a `.codex`. A missing link or one pinned to a
single `fleet-vX` is a MISMATCH that prints this command. A root with no `.codex` is a SKIP. The first deploy
that ships this check reads MISMATCH until the install has run; that is the correct reading, not a failed deploy.
Nothing in the chain rolls back on it (`release-rollback` is always a deliberate call). Do not roll back for an
assertion-6-only MISMATCH: run the install and re-run postflight.

**Mind the refusal window.** From the deploy that first ships the dispatch refusal until the install runs,
every `fleet dispatch --runtime codex` on that root exits 4 ("cannot see the superpowers skills"). Run the
install as part of the deploy step, before postflight, so the window is seconds rather than however long it
takes someone to read the MISMATCH. `--override "<reason>"` launches a codex worker without skills in the
meantime.

## Do the suites need to run?

Usually you do not have to care: `release-verify` decides and returns in ~2 seconds when they are not
needed, recording verdict **`EXEMPT`**. `release-promote` accepts `EXEMPT`, so there is **no `--force` and
no per-release judgement call**.

| Changed since the last GREEN release | Verdict | Time |
|---|---|---|
| only `docs/`, `assets/`, root docs, or skills **other than** `using-fleet` | `EXEMPT` | seconds |
| anything else — `fleet/`, `scripts/`, `hooks/`, `bin/`, `tests/`, `skills/using-fleet/`, a new directory | suites run | ~24–45 min (Trap 3) |

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

This refusal is already inside the verb layer (`_refuse_if_self_deployed`), not something a wrapper needs
to re-check — running a deployed binary against itself is settled. The only remaining discipline is
remembering which binary you called.

**Trap 2 — the cut creates the tag; do not pre-create it.** `release-cut --help` says "the tag becomes
`fleet/vX.Y.Z`", which reads like a precondition. It is not. Under its lock the cut writes the changelog
section, rewrites `__version__`, commits `fleet vX.Y.Z`, then makes the **annotated** tag — and
`annotated_tag` *refuses* if it already exists. Pre-creating it hard-blocks the release. Make only your
ordinary content commits; touch neither `fleet/CHANGELOG.md` nor `__version__` (a dirty tree is refused
too).

Both refusals here are already inside `release-cut` itself — an existing tag (`_refuse_an_existing_release`)
and a dirty tree, **including untracked files** (`Repo.dirty()`) — so neither needs a wrapper check written
around it; the only open question when the cut refuses is which of the two you hit.

**Trap 3 — be SILENT while the gate runs.** `pgrep -x claude` matches on `comm`, and a forked child
carries its parent's `comm` until it execs — so **every tool call an agent session makes creates a process
named `claude` for ~600 ms**. The IT suite's `A6` and `ISOLATION-*-claude-count` cases snapshot that count
at each section boundary and require equality. Polling a run you are driving fails it. Start the verify in
the background and make **zero** tool calls until it reports; a background shell that already exec'd is
safe, because its own forks are `comm=bash`.

**Two things "in the background" does not say, and each cost a run on 2026-09-13 (0.5.9/0.5.10):**

- **Never pipe the control.** `release-verify … | tail` reports *`tail`'s* exit status, not the verb's —
  the hard rule `fleet/CLAUDE.md` states for every control, and it applies here. What this provably did
  to the 0.5.9 run: a piped, backgrounded attempt reported exit `0` although it had written no
  `VERDICT.tsv` and had stopped after the hermetic half — a pipeline's exit status is the last stage's,
  so a dead run read as a finished gate. The giveaway was the evidence directory: `hermetic.log` and
  nothing else. **What killed that run is a separate, still-open question — earlier notes here blamed the
  pipe for the death itself, and that claim is withdrawn:** a later, unpiped attempt at the same version
  died the identical way ("Forty-five minutes, no verdict, same two lines — so my pipe theory was wrong
  and something else is stopping it"). Read this trap as "the pipe turns a dead run into a false success,"
  not "the pipe kills runs."
- **Launch it with `setsid`,** so the run does not sit in your session's process group. A background task
  that is stopped — by an interrupt, a teardown, or your own cleanup — takes the whole group with it,
  leaving a CANDIDATE with no `VERDICT.tsv` and no error anywhere. This happened twice before the cause
  was obvious.

```bash
setsid nohup "$FLEET" release-verify --version X.Y.Z --releases "$FLEET_RELEASES" \
  > /tmp/verify-X.Y.Z.log 2>&1 < /dev/null &
```

Then wait on a **condition** — `VERDICT.tsv` appearing, or the pid exiting — never on a fixed sleep. One
background shell doing that loop is safe: its own forks are `comm=bash`.

**`scripts/release-gate.sh <version>` does all of the above for you — use it instead of typing the launch
by hand.** `setsid`, no pipe, no `timeout`, and an unbounded wait on the same condition. It reports one of
three outcomes: a verdict → exit 0 (`GREEN`/`EXEMPT`) or exit 1 (anything else), with the per-runner FAIL
rows already printed; the pid gone with no verdict **from this run** → **exit 3**, running Trap 8's
checklist for you (`hermetic.log`'s size and mtime, then the log's tail); "still running" is unreachable by
construction — the script does not return until one of the other two is true. It runs the gate **once**;
re-running it is a separate, deliberate invocation you make, never something the script does for you.
It runs the `bin/fleet` **it ships beside** and prints that path on its launch line. It never runs the
`FLEET_BIN` a dispatched session carries, which names the dispatcher's fleet (FB-56). So `env -u FLEET_BIN`
is no longer needed, and the checkout whose script you invoke is the checkout that gets verified.

**"From this run" is load-bearing, and it is what a re-verify depends on.** A version that has already been
verified still has the previous attempt's `VERDICT.tsv` on disk — `fleet-v0.5.9` and `fleet-v0.5.6` are
CANDIDATE with RED ones right now — and `Verify.run()` does not move it aside (`archive_previous_attempt`)
until after fork, arg parsing, `_refuse_if_self_deployed` and the whole exemption diff. A wait that tested
mere presence lost that race essentially always: measured against a stub of that shape, the gate printed
the *previous* attempt's `verdict RED` and exited 1 in under a second, leaving a real ~45-minute run
detached with nobody waiting on it. The script now snapshots the file's `(inode, mtime)` before launching
and waits for a VERDICT.tsv that is present **and** is not that one, so re-verifying after an
`INCONCLUSIVE` — the workflow this skill prescribes — reports the run you just started.

**The run prints nothing between its header and its verdict.** Two runs measured on this box
(2026-09-13, 0.5.9/0.5.10) took 2080 s (~35 min) and 2800 s (~47 min, one other root's worker live on the
box) — both well past the old `~24 min` figure the table above used to quote on its own. Neither
measurement is 24 minutes; the table now reads `~24–45 min` to keep the old, unverified low estimate
rather than discard it, against the ~45 minutes actually measured. This is also why `release-gate.sh`
waits unbounded instead of guessing a timeout. An apparently idle gate is the normal shape; do not read it
as a hang.

**Trap 3b — AN IT RUN DIRTIES THE TREE, AND `release cut` REFUSES ON ANY DIRTY ROW.**
The refusal itself is already enforced — `Repo.dirty()` counts **untracked** rows too, so a single `??`
refuses the cut, and nobody needs to write a pre-cut check for it. What is NOT enforced, and is the actual
trap: running any IT runner in the checkout rewrites tracked registers — `fleet/it/RESULTS.tsv` via the
merge step, and historically the
SOURCE PIN scratch. **Before any cut, the register is either COMMITTED — when the run you just did is the
run you are releasing — or REVERTED, when it was a scratch run.** Decide which; do not leave it.

`RESULTS.tsv` stays TRACKED deliberately: `it_own_cases` makes it the CURRENT state of every case with
history left to git, so a diff of it is evidence. Untracking it would trade a visible recurring cost for
an invisible permanent one — a register you cannot diff is a claim, not a record. The recurring cost is
this paragraph, which exists because "detect and prevent are different asks: if the actor forgets the
remedy, what happens?" An unwritten pre-cut step is exactly that shape, and it cost a refused cut on
`0.3.10` (`SOURCE-PIN-group5-{before,after}.txt`, since gitignored) before it was written down.

⚠️ **Do not clear this refusal by `git add`-ing the offending scratch file.** Somebody did that once for
the group5 pins, which is why they then showed `M` on every run forever and each new refusal tempted the
next person to add one more. Per-run scratch gets a `.gitignore` entry; a register gets committed.

**To re-run one section without dirtying anything** — which is what you want when checking a fix for a
RED — point `IT_RESULTS` at a scratch file. The runner replaces its rows there and the tracked
`fleet/it/RESULTS.tsv` is never written:

```bash
cd fleet/it
R="$PWD/RESULTS-scratch-$$.tsv"; printf 'case\tverdict\tevidence\tnote\n' > "$R"
IT_RESULTS="$R" bash run-B.sh
IT_RESULTS="$R" bash run-group5.sh L M N
```

Delete the scratch file when done, and run `git status --short` regardless — a section can still touch
something you did not expect, and you need the tree clean for the cut either way.

**Trap 4 — quiet the box first.** A **COMPLETE** worker still holding a slot with a live pane is a
scheduled contamination event: it exits mid-run, moving both the board and the claude count. Harvest
finished workers before cutting. Other people's live sessions are an uncontrollable residual risk — a gate
run here is not reliably repeatable.

**Run `scripts/release-preflight.sh` before cutting** — it reports exactly this, through the environment's
own **derived** socket (`FLEET_TMUX_SOCKET`, set by `fleet-env.sh`; never a bare `-L fleet`, whose failure
looks identical to a quiet box whether the box is quiet or the environment was simply never sourced): this
root's live `dt-` sessions, every *other* root's socket — `fleet-*` **and a socket named literally `fleet`**,
which a root on an older installation still serves on (0.6.3's preflight missed three live workers there),
each listed with its `dt-` count so a quiet socket reads as looked-at rather than missed (an uncontrollable
residual, reported but never refused — this box has more than one root), any `board` subject still
`COMPLETE` and holding a slot, the sync-cron window (Trap 7), and orphaned `.fleet-v*.tmp` verify worktrees left by a run that terminated
abnormally (`--reap` removes them — restoring write access to a read-only §Q export first, and refusing to
touch anything whose name does not match the orphan pattern exactly). Every finding is a `WARN:` at exit 0
— advisory, because none of it is this root's business to refuse on — except one hard refusal at exit 2
when `FLEET_TMUX_SOCKET` is unset or literally `fleet`: reporting confidently from a broken environment is
worse than refusing, because the two read identically on screen. `release-cut` and `release-verify` also
print a one-line note of their own when the box has live work, so the same fact surfaces even if
preflight is skipped.

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
is asking for trouble. The job is real and checkable — `crontab -l` shows
`30 3 * * * … .superpowers-sync/sync.sh`. Since the gate runs ~45 minutes (Trap 3), anything started after
about 02:45 UTC straddles it; wait the window out rather than racing it. `scripts/release-preflight.sh`
(Trap 4) checks this window against the real `crontab -l` line rather than a hardcoded time, so it stays
right if the cron ever moves.

**Trap 8 — an absent `VERDICT.tsv` is not a verdict.** The file is written at the end, so its absence
means the run *did not finish* — killed, crashed, or piped into something that swallowed its status. That
is not RED, and the exit status will not tell you which (Trap 3). Check in this order: the file, then the
pid, then `hermetic.log`'s mtime to see how far it got. A directory holding only `hermetic.log` and an
empty `live-subjects-before.tsv` never reached the IT suite at all. `scripts/release-gate.sh` runs exactly
this order for you and reports it as **exit 3** — the pid gone, no `VERDICT.tsv`.

**Trap 9 — fixing a RED does not fix the artifact you already cut.** The export and the tag are taken at
cut time, so a commit landed to clear a RED is **not in them**, and `release-cut` has no `--force` and
refuses an existing tag (Trap 2). Cut the next patch version from the fixed tree and let the failed one
stand as a CANDIDATE that never shipped — that is exactly what the state means, and `release-list` is the
honest record of it: its `verdict` column means a RED CANDIDATE and a version nothing has verified at all
no longer print the same row. Deleting a published tag to reuse its number is the destructive option and
buys nothing but a tidier number. (`0.5.9` is the worked example: cut, RED, fixed, superseded by `0.5.10`.)

**Trap 10 — `EXEMPT` has never actually fired before, and now it can.** A stripper bug meant the version
field in `.hermes-plugin/plugin.yaml` (a bare-YAML `version:` key) never matched the JSON-only pattern
checking whether a cut's own stamp was the only thing that changed — so every cut's stamp looked like a
real change, `requiring` was never empty, and no release from **0.5.2 to 0.5.11 could ever be `EXEMPT`**,
no matter how docs-only the diff was. Now that the stripper matches the YAML key too, a docs- or
non-`using-fleet`-skill-only release really can skip the suites, and when it does: **no suite ran at all**
— the evidence is `evidence/EXEMPTION.tsv` (the anchor release, both tags, every changed path), never a
test log, and there is no `hermetic.log` or `it-RESULTS-closeout-*.tsv` to go looking for (that absence
means EXEMPT here, not Trap 8's "the run did not finish"). Before spending 45 minutes finding out, ask
first — `release-verify --dry-run` answers in seconds:

```bash
$FLEET release-verify --version X.Y.Z --releases "$FLEET_RELEASES" --dry-run
```

It prints `would-exempt` and names the anchor release it diffed against when the release qualifies, or
`would-run` plus a `requiring` row for every path that forced the suites when it does not — so you know
which of the two you are about to get before you commit to the run.

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
| `release-verify … \| tail` | Never pipe a control — the pipe's exit status is not the verb's (Trap 3) |
| Backgrounding the gate inside the session's process group | `setsid`, or a stopped task kills the run with it (Trap 3) |
| Reading a missing `VERDICT.tsv` as RED, or as a hang | Absent means the run did not finish; the gate is also silent for ~45 min (Traps 3, 8) |
| Re-verifying the same version after fixing a RED | The tag predates the fix; cut the next patch version (Trap 9) |
| Running a section to check a fix, then finding the cut refused | `IT_RESULTS=<scratch>` keeps `RESULTS.tsv` clean (Trap 3b) |
| Copying the evidence out by hand before re-verifying | The tool archives it: `evidence/attempt-<n>-<verdict>/` (Trap 5) |
| Reading the verdict off `run-all.sh` or `it-RESULTS.tsv` | Per-runner `it-RESULTS-closeout-*.tsv` FAIL rows |
| `release-deploy --force` to skip a slow gate | That is what `EXEMPT` is for; `--force` records the release UNVERIFIED |
| Treating `INCONCLUSIVE` as RED, or as "just retry" | Identify the mover, remove it, then re-run |
| Widening the inert set to make a release exempt | The allowlist's narrowness IS the safety property |
| Assuming a release only ships the CLI | It ships every skill; deploying changes what sessions load |
| Running `fleet release-status` from a second root to confirm a deploy reached it | Root-relative and can mislead ("The chain" section's postflight note); `scripts/release-postflight.sh` answers box-relative and never calls `fleet` |
| Spending 45 minutes to find out a docs-only release could have skipped the suites | `release-verify --dry-run` reports `would-exempt`/`would-run` in seconds (Trap 10) |
