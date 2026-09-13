# Fleet release mechanisation — design

**Status:** binding for the release that follows it.
**Source:** a transcript audit of session `067e3243` (fleet 0.5.9 → 0.5.10 → 0.5.11), commissioned
because four documented prose traps still cost time during that release.

## The problem this solves

The `releasing-fleet` skill has ten traps. Every one of them is a thing a human must remember at the
moment it matters. The operator preference this spec serves is stated directly in the fleet infra
ledger (`MD-2`): *"I prefer scripts / fixing actual issues once and for all instead of watching out
for it everytime."*

So the question asked of every trap was not "is this good advice" but **"is this mechanically
checkable?"** Where it is, the deliverable is the check. Where it is not, it stays prose and this
spec says so out loud.

A second question was asked of each check: **does it belong inside the verb, or in a wrapper
script?** A refusal inside the verb is strictly better — it binds every caller, including a caller
who has never read the skill. A wrapper only binds the caller who runs the wrapper. So the rule is:
*the verb refuses where the verb can see the fact; a script covers only what is outside the verb's
world* (the operator's shell, the box's other roots, how the command was assembled).

---

## F1 — the exemption path has never once fired, and cannot

**Measured.** Of the ten retained releases (0.5.2 … 0.5.11) **not one** has an `EXEMPTION.tsv` or an
`EXEMPT` verdict. There is no `EXEMPTION.tsv` anywhere in the release area. The `EXEMPT` path has
been dead since it was written.

**Mechanism.** `exemption_for` (`release_verify.py:279-281`) re-checks each `CUT_MANIFEST` on
content, stripping the version stamp so an author's real edit cannot ride out on a cut's rewrite:

```python
stamped  = [(CUT_STAMPED, without_version_line)]
stamped += [(path, without_version_field) for path in CUT_MANIFESTS]
```

`without_version_field` is `_VERSION_FIELD = ^\s*"version"\s*:\s*"[^"]*"\s*,?\s*$` — quotes
mandatory, i.e. JSON only. But `CUT_MANIFESTS` has carried `.hermes-plugin/plugin.yaml` since
upstream `b36e082` (v6.3.0, 2026-08-12), and that file's line is unquoted YAML:

```yaml
version: 6.3.0+fleet.0.5.11
```

The regex misses it, the two stamps differ, the file is pushed back into `requiring`, and
`scope.exempt` is False. Because `release-cut` stamps every declared manifest on **every** cut, that
file is in **every** release diff. Therefore `exemption_for` returns `None` for every release that
will ever exist.

This is `SI-19`'s shape a second time, and `release_scope.py:60-63` says so in its own words —
*"treating them as ordinary paths would make exemption unreachable for every release that will ever
exist"*. The list was extended; the stripper was not.

**The asymmetry is the bug, and it is precise.** The *stamper* is already YAML-aware.
`release_stamp._rewrite:141-143` builds its pattern with the quotes **optional** and the closing
quote back-referenced to the opening one, and its comment says exactly why: *"`"version": "6.2.0"`
and a YAML `version: 6.2.0` are both matched by one pattern — and a half-quoted value by neither."*
So the repository already contains the right answer to this question, written for the write half and
not carried across to the read half.

**Ruling: relax the one stripper rather than add a second function.**

`_VERSION_FIELD` becomes, mirroring `_rewrite`'s pattern:

```python
_VERSION_FIELD = re.compile(
    r'^[ \t]*"?version"?[ \t]*:[ \t]*(?P<q>["\']?)[^"\']*(?P=q)[ \t]*,?[ \t]*$', re.MULTILINE)
```

Whole-line anchored, key literally `version` (optionally quoted), value's quoting symmetric or
absent. A half-quoted value matches neither — the same latitude `_rewrite` already takes, and the
same refusal.

*Deviation recorded:* the audit proposed a second function, `without_version_yaml`, selected per
path by suffix. Rejected. A per-suffix dispatch is a second place for the manifest list to acquire a
family the other half does not know about — which is the exact failure being fixed. One pattern that
matches what the stamper writes cannot drift from the stamper by construction.

**The test that keeps it fixed** is not a YAML test. It is the round trip, over the whole family:
for **every** path in `CUT_MANIFESTS` plus `CUT_STAMPED`, take the repository's real file, stamp it
to a different version through the real stamper, and assert the stripper cannot tell the two apart.
Any future manifest whose spelling the stripper does not understand fails this test on the day it is
added to `.version-bump.json`.

The existing tests could not see the defect: `test_release_scope.py:178-185` asserts only that
`CUT_MANIFESTS` and `.version-bump.json` name the same *paths*, and `test_release_payload.py:212/219`
exercises `without_version_field` on JSON only. Both are true and both are blind.

**Consequence to state plainly:** this makes the `EXEMPT` path live for the first time. A docs- or
skills-only release will now skip the suites. The fail-safe direction is unchanged — `classify` is
an allowlist and every uncertainty still answers "run them" — but the round-trip test is what stands
between that path and a release that skips its gate wrongly, so it is not optional.

---

## F2 — `release-verify --dry-run` cannot answer the only question it is asked

**What happened.** After F1's defect cost a 45-minute run on a skills-only release, the operator did
the right thing and asked the tool rather than guessing:

```
$ fleet release-verify --dry-run --version 0.5.11
dry-run       no suite was run and no evidence was written
would-verify  0.5.11 at …/fleet-v0.5.11
would-run     the gate roster
```

That was read as the tool's exemption decision. It is not one.

**Mechanism.** The dry-run block (`cli.py:4513-4518`) returns **before** `exemption_for` is called
(`cli.py:4543`). `roster` is just `FULL_ROSTER if --full else GATE_ROSTER`. The line
`would-run the gate roster` prints identically for an exempt release. The verb's dry run is
structurally incapable of reporting the most expensive decision the verb makes.

**Fix.** Hoist the `exemption_for` call above the dry-run block — it is pure with respect to the
release area (a `git diff --name-only` between two tags plus `git show` on at most ten files; no
spawns, no writes) — and have the dry run emit the decision:

- exempt: `would-exempt <anchor>` and the `inert` rows `write_exemption` already formats.
- not exempt: `would-run the gate roster`, **plus one `requiring <path>` row per path that forced
  it**.

That single added row would have printed `requiring .hermes-plugin/plugin.yaml` and turned F1 from a
45-minute mystery into a ten-second diagnosis.

`Refused` from `exemption_for` (the missing-anchor-tag case) must still propagate from a dry run — a
dry run that swallows a refusal reports a release as verifiable when it is not.

---

## F3 — a `CANDIDATE` row cannot be told apart from an abandoned one

**Measured, right now:** `0.5.9` is `CANDIDATE` and RED; `0.5.11` is `CANDIDATE` with no
`VERDICT.tsv` at all because its run was aborted. `release-list` renders both identically.

**Mechanism.** `_do_release_list` (`cli.py:4760-4766`) emits `version / state / cut_at /
current-marker`. Four distinct situations — cut and abandoned RED, cut and never verified, verified
GREEN awaiting promote, verify killed mid-flight — collapse into one word.

**Fix.** A fourth column carrying the recorded verdict, `-` when there is none. Cheapest item in
this spec and it retires the audit's "stale-CANDIDATE report" proposal entirely: with the column,
the report is `release-list`.

---

## F4 — `release-cut` never asks whether the box is busy

**Mechanism.** `ctx.live_work_now()` appears exactly once in the CLI: `cli.py:4522`, inside
`_do_release_verify`, which prints the *"this box has live fleet work"* note. `_do_release_cut` never
calls it. The cut is the **earlier and more expensive** decision point — a cut you regret costs a
version number and a tag that must never be moved.

**Fix.** The same call and the same note, in `_do_release_cut`, before the cut proceeds.

**A note, never a refusal.** Other roots' sessions are an uncontrollable residual on a shared box;
refusing on them would make releases impossible here. The point is that the operator learns an
`INCONCLUSIVE` is on the table before spending the 45 minutes, not that the tool decides for them.

---

## F5 — `scripts/release-gate.sh`: the sanctioned way to launch and wait

**Four incidents in one session, three of which destroyed a gate run.** None was a property of the
gate; all four were properties of how the command was assembled:

| # | What was run | What happened | Mechanism |
|---|---|---|---|
| 1 | `release-verify … 2>&1 \| tail -40`, backgrounded | task reported **exit 0**; no `VERDICT.tsv` was ever written and the run had stopped after the hermetic half | a pipeline's exit status is the last stage's (`fleet/CLAUDE.md:173-174`), so `tail` reported for the verb. A dead run became indistinguishable from a finished gate. |
| 2 | waiter `until [ -f VERDICT.tsv ] \|\| [ $n -ge 60 ]; sleep 45` | reported `waited 2700s … NO VERDICT FILE` while the run was **healthy and mid-flight** | a fixed iteration cap conflates "slow" with "dead". The gate measures ~45 min here (2080 s, 2800 s), against the ~24 the skill quoted. Produced a false diagnosis and a second wait. |
| 3 | `nohup … & ; while kill -0 $VPID` inside a harness background task | task `killed`; whole run lost | `nohup &` stays in the task's process group, so stopping the task signals the group. `setsid` is what detaches. |
| 4 | `timeout 300 release-verify …` | `rc=124` | an ad-hoc timeout is a guess about a duration the operator does not know. |

**Correction to the received account.** The skill currently attributes incident 1's death to the
pipe. The transcript retracts that: *"Forty-five minutes, no verdict, same two lines — so my pipe
theory was wrong and something else is stopping it."* The pipe's proven harm is the **false exit 0**,
which is reason enough. The skill's wording is amended accordingly under F9; a trap that overstates
its evidence teaches the next reader to discount it.

**Fix — a driver, because the verb cannot make its caller stop piping it.**

`scripts/release-gate.sh <version>`:

- resolves the release area via `scripts/fleet-env.sh` and the **checkout's** `bin/fleet` by absolute
  path;
- launches exactly
  `setsid nohup "$FLEET" release-verify --version "$V" --releases "$R" > "$LOG" 2>&1 < /dev/null &`
  — no pipe anywhere, no `timeout` — and writes a pidfile beside the log;
- waits on a **disjunction, unbounded**: `until [ -f "$EV/VERDICT.tsv" ] || ! kill -0 "$pid"; do
  sleep 30; done`;
- classifies **three** outcomes, not two:
  - verdict present → print the `verdict` row and the FAIL rows from the **per-runner**
    `it-RESULTS-closeout-*.tsv`, never the merged `it-RESULTS.tsv`; exit 0 on GREEN/EXEMPT, 1 on
    RED/INCONCLUSIVE;
  - pid gone, no verdict → **exit 3**, and print `hermetic.log`'s size and mtime — Trap 8's
    checklist, executed rather than remembered;
  - still running is unreachable by construction.

It also satisfies the silence protocol *structurally*: the script's own forks are `comm=bash`, so the
waiting is done by something that cannot inflate the `claude` process count the IT suite samples at
section boundaries. That property currently depends on an agent's restraint.

---

## F6 — `scripts/release-preflight.sh`: the box, seen through the derived socket

**What happened.** Immediately before the cut, box quietness was checked with
`tmux -L fleet ls; tmux ls`. Both printed `error connecting to /tmp/tmux-1000/…` and the box was read
as quiet. It was not: `release-verify` printed *"this box has live fleet work"* on all three of its
runs, and the live session — `dt-githubciinventoryandreleaseproof` on socket `fleet-davis2` — was
alive throughout and still alive twelve hours later.

**Mechanism.** The socket is **derived per root**: `fleet-env.sh:104` sets
`FLEET_TMUX_SOCKET="${FLEET_TMUX_SOCKET:-fleet-$_fleet_name}"` — `fleet-davis` here — and
`fleet-env.sh:85` *deliberately unsets a socket named literally `fleet`*. So a hand-typed `-L fleet`
can never be a fleet socket, and its failure is spelled the same as an empty server. A wrong guess
and a quiet box are indistinguishable on screen.

**Fix.** `scripts/release-preflight.sh` sources `fleet-env.sh` and **reports, never guesses**:

- `tmux -L "$FLEET_TMUX_SOCKET" ls` — this root;
- every `/tmp/tmux-*/fleet-*` socket on the box with its `dt-` session count — the other roots, which
  this root's env cannot otherwise reach;
- `board --porcelain` rows in state `COMPLETE` still holding a slot;
- `date -u` against the crontab's `30 3 * * *` sync line, using the **measured** ~45 min gate
  duration;
- the orphan report of F7.

**Exit discipline:** `WARN:` per finding and **exit 0** — these are all advisory. Exactly one hard
refusal, **exit 2**: if `FLEET_TMUX_SOCKET` is unset or equals `fleet`. That means the environment
was not derived, and every session count the script could then print would be a lie. A preflight
that reports confidently from a broken environment is worse than no preflight.

**Three checks the audit proposed here are deleted, not implemented:** clean tree, tag-already-exists,
and self-deployed binary. See S2 — all three are already refusals inside the verbs, none of them bit
in the session, and re-implementing a working refusal in a wrapper creates a second place for the
rule to rot.

---

## F7 — orphaned verify worktrees: 156 MB and four stale registrations, right now

**Measured in the checkout as this spec is written:**

```
8.2M  .fleet-v0.4.0.1049049.….tmp    (2026-09-06, predates the session)
63M   .fleet-v0.5.9.1476877.….tmp    (the run that "exited 0")
33M   .fleet-v0.5.10.2035239.….tmp   (the run killed with its background task)
20M   .fleet-v0.5.11.173330.….tmp    (the timeout-300 run, rc=124)
32M   .fleet-v0.5.11.187006.….tmp    (the aborted run)
```

and `git worktree list` shows four of them still registered as detached-HEAD worktrees.

**Mechanism.** `Verify._worktree()` (`release_verify.py:404-422`) creates
`releases.root / tmp_name(version.dirname)` and registers a worktree; teardown is on the normal path
only. A signal to the process group skips it. Nothing ever revisits the directory, and there is no
reaper because the name is deliberately **not** a function of the version (`atomic.tmp_name`,
`FI-20`) — so no later run can recognise "its" leftovers by name. The successful 0.5.10 run cleaned
up after itself, which confirms the mechanism is specifically abnormal termination.

**Fix.** The name is `.{dirname}.{pid}.{monotonic_ns}.{rand}.tmp` — **the creating pid is in the
name**, which makes a safe reaper trivial and is the whole reason this is cheap.

`release-preflight.sh`, reporting by default and reaping under `--reap`: for each
`"$FLEET_RELEASES"/.fleet-v*.tmp`, parse field 3 as a pid. If `kill -0 <pid>` succeeds **and**
`/proc/<pid>/cmdline` contains `release-verify`, print `LIVE` and leave it alone. Otherwise print
`ORPHAN <path> <size> <mtime>`. `--reap` removes the directory and then runs
`git -C "$REPO" worktree prune` so the registration goes with it. Anything whose name does not match
the pattern exactly is refused, not guessed at.

Both halves of the liveness test are required. The pid alone is not enough: pids are reused, and
reaping a live run's worktree mid-suite would produce a failure with no honest explanation.

---

## F8 — `scripts/release-postflight.sh`

**What happened.** "Are both roots on the new release" was answered by four hand-written commands.
All passed — but `release-status`, run from `davis2_root`, printed `current DEV / head unknown`,
which reads as a broken deployment and is not.

**Mechanism.** `release-status` reports relative to the `FLEET_HOME`/`--releases` it is handed, and
`davis2_root/fleet-releases` is a **symlink** to `davis_root/fleet-releases` — so the second
invocation is the same release area under a second name, with an env that makes it look like a dev
checkout. The state was correct; the presentation is root-relative while the question is box-relative.

**Fix.** `scripts/release-postflight.sh <version>` asserts, **without invoking `fleet` at all** — so
it cannot inherit the `DEV` artifact that caused the confusion:

- `readlink -f "$FLEET_RELEASES/current"` ends in `fleet-v<version>`;
- for each root on the box, `readlink -f "<root>/fleet-releases/current"` resolves to that same path
  — which *proves* the symlink topology instead of assuming it;
- each root's `.claude/settings.json` marketplace path, `readlink -f`'d, equals it;
- every file named in `.version-bump.json`, read from `current/`, carries `+fleet.<version>` — which
  also covers `.hermes-plugin/plugin.yaml`, the file F1 shows nothing else checks;
- `current/.release/evidence/VERDICT.tsv`'s `verdict` row is `GREEN` or `EXEMPT`.

One `OK`/`MISMATCH` line per assertion; exit 1 on any mismatch, naming both sides.

---

## F9 — the skill stops carrying what the scripts now enforce

`skills/releasing-fleet/SKILL.md` keeps every trap's **explanation** — an operator who knows only
"run the script" cannot diagnose the script — but each mechanised trap gains the one line naming the
script that now enforces it, and the prose stops being the primary control.

Two corrections of fact, both load-bearing:

1. The suites table still says `~24 min`. Measured here: 2080 s and 2800 s. It becomes
   `~24–45 min (Trap 3)`, matching what the traps section already says.
2. The attribution of the first 0.5.9 run's death to the pipe is **withdrawn** and replaced with what
   was actually measured: the pipe made a dead run report exit 0.

`fleet/CLAUDE.md` gains the three new scripts in the list beside `fleet-view.sh` and
`fleet-finished-pids.sh`, with how to run their tests.

---

## Sanctions — proposed and deliberately not built

**S1 — `scripts/it-section.sh` (run one IT section with `IT_RESULTS` at scratch). NOT BUILT.**
The audit's claim that this was hand-rolled during the session is wrong. The recipe was written into
the implementing subagent's brief, the subagent complied, its report said *"Tree clean: yes"*, and
the session's final `git status --short` was empty. **The prose worked.** Building a script for a
control with a zero failure rate is how a scripts directory acquires things nobody runs. Revisit
when it actually bites.

**S2 — clean-tree, tag-exists and self-deployed preflight checks. NOT BUILT.**
Each is already a refusal: `cli.py:4392-4399` with `Repo.dirty()` = `git status --porcelain` (so
untracked rows already count); `cli.py:4385-4390` with the "a release tag is never moved" message;
and `_refuse_if_self_deployed` (`cli.py:4280`) wired into all five mutating verbs. None bit in the
session — every mutating invocation used the checkout's binary. Duplicating a working refusal into a
wrapper makes two places for it to rot, and the wrapper is the one that binds nobody.

**S3 — the 03:30 UTC cron window is reported, never refused.**
It cost ~37 minutes of *correct waiting* and zero errors: the operator checked `date -u`, read the
crontab, and waited it out unprompted. A refusal there would only ever be in the way.

**S4 — live box work warns, never refuses.** See F4.

**S5 — the gate is never auto-retried.**
Three of the four F5 incidents ended in a re-run, so a driver that re-launches on a missing
`VERDICT.tsv` is one edit away from re-launching on RED. *A gate you retry until it passes is not a
gate.* `release-gate.sh` runs the gate **once** and exits with the verdict; running it again is a
separate human invocation. The distinction was honoured in the session and must stay: the 0.5.9
re-runs were re-launches of a run that never produced a verdict, and 0.5.10 was a **new version from
a fixed tree**, not a re-verify of a RED.

**S6 — RED vs INCONCLUSIVE is never decided by a script.**
The session's `it RED … live-subject set unchanged` was real (B13, a genuine regression). A box with
another root's session live throughout could equally have produced a false RED. The
`live-subjects-before/after` diff is an **input to** that judgment, not the judgment. A script that
auto-labelled contamination would, in the convenient direction, ship an unverified release.

**S7 — the inert allowlist is not widened.**
F1 is the strongest possible temptation to do this — "0.5.11 was skills-only, just add a rule". That
would be the wrong fix and a dangerous one. `release_scope.py:10-14` is an allowlist precisely so
that its failure mode is a needless test run. F1 makes the **content** check honest about a spelling
it already writes; it narrows nothing.

**S8 — the version number, and supersede-vs-re-cut, stay human.**
A script may *report* that a tag predates HEAD by N commits. It must not pick. Deleting a published
tag to reclaim a number is destructive and buys only tidiness. Likewise `--reason` / `--notes`: a
generated reason is a reason nobody wrote, and it is what the next person reads when they ask why
`current` moved.

---

## Global constraints

- `fleet/` is **python3 stdlib only**. No third-party import, ever, including in tests.
- `release_scope.py` is a **leaf with no filesystem** — a pure function of a list of strings. F1's
  change is a regex; it must not make the module read a file.
- Scripts are bash, must pass `scripts/lint-shell.sh`, and each gets a test under `scripts/tests/`,
  which is the house pattern (`fleet-view.sh`, `fleet-finished-pids.sh`, `fleet-env-derives-root.sh`).
- Citation comments (`SI-`, `FI-`, `RI-`, `MI-`, `OBS-`) are load-bearing. A comment falsified by a
  change is **amended with the measurement**, never deleted.
- No script may mutate a release, move `current`, or delete anything outside the
  `.fleet-v*.tmp` pattern.
- `scripts/` is not in the inert allowlist, so this release runs the full gate. That is correct and
  is not to be "fixed".
