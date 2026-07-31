# fleet — developer guide

`fleet` is the coordination infrastructure the `using-fleet`, `coordinating-instants` and
`working-as-a-dispatched-instant` skills are built on. python3 **stdlib only** — no third-party imports, ever.

This file is scoped to `fleet/`. The repository root's `CLAUDE.md` is about contributing upstream to
obra/superpowers and does not apply to anything here.

```
fleet/src/fleet/     18 modules, 31 verbs, entry point `python3 -m fleet.cli`
fleet/tests/         the hermetic suite (864 tests) + fixtures/
fleet/it/            the integration harness: run-*.sh, lib.sh, RESULTS.tsv, controls in bin/
../bin/fleet         launcher, so you can type `fleet <verb>` from anywhere
```

## The three tiers, and what each one can and cannot prove

They are not redundant. Each answers a question the others structurally cannot, and knowing which is which
saves you from trusting the wrong green.

| Tier | Proves | Cannot prove |
|---|---|---|
| **hermetic** (`fleet/tests/`) | logic, per module, with every probe injected | anything about a real filesystem, a real tmux server, a real process, or a real crash |
| **integration** (`fleet/it/run-*.sh`) | behaviour against real sessions, real git repos, real kills | whether a *model* can follow the documented contract |
| **§P** (`fleet/it/run-P.sh`) | a real `claude`, dispatched from the shipped profile, completing the contract from its seed alone | nothing beyond the one task it was given |

## Running the hermetic suite

```bash
cd fleet
PYTHONPATH=src python3 -m unittest discover -s tests -q      # ~45s, 864 tests
PYTHONPATH=src python3 -m unittest tests.test_cli -v         # one module
PYTHONPATH=src python3 -m unittest tests.test_cli.TestBrief  # one class
```

Run this before every commit. It is fast and it is the only tier that will catch a logic regression in
seconds rather than minutes.

## Running the integration sections

Each `it/run-*.sh` is one section, self-contained, and safe to run individually. Every runner writes its
verdicts to `$IT_RESULTS`; point that at a per-run file and merge deliberately, never let two runners write
`RESULTS.tsv` at once.

```bash
cd fleet/it
R="$PWD/RESULTS-mine.tsv"; printf 'case\tverdict\tevidence\tnote\n' > "$R"
IT_RESULTS="$R" bash run-H.sh                  # §H, the roadmap section — ~20s
IT_RESULTS="$R" bash run-lineage.sh            # §LB, the git-lineage gate
IT_RESULTS="$R" bash run-group5.sh             # §L §M §N in one process — ~4min
```

| Runner | Section(s) |
|---|---|
| `run-A` | §A environment, isolation, exit codes |
| `run-B` `run-C` `run-D` | instant model / pool + workspace / dispatch + rollback |
| `run-F` | §F admission control, F1–F11 |
| `run-group3` | §E concurrency + §K compaction |
| `run-group5` | §L meta loop, §M CLI surface, §N real tmux lifecycle |
| `run-H` | §H roadmap, propose/apply, the carry-across |
| `run-G` | §G the roadmap/agent surface |
| `run-I` | §I the agent-facing contract |
| `run-J` | §J the harvest transaction, J1–J9 |
| `run-O` | §O failure injection, O1–O9 |
| `run-lineage` | §LB the lineage gate on `propose --status done` |
| `run-w1` | §W1 the private tmux server |
| `run-e9-leak` `run-m9-mutation` `run-rmw` | targeted regressions |
| `run-P` | §P the real dispatch — see below |

**`RESULTS.tsv` is current state, not an append log.** Each runner declares the case ids it owns via
`it_own_cases` and *replaces* those rows. That is what makes "zero NOT-RUN" expressible — and it is currently
**273 PASS / 0 FAIL / 9 SKIP / 0 NOT-RUN**. Every SKIP carries a stated reason; a partial pass must never read
as a full one, which is why the section-level `NOT-RUN` rows that used to stand in for §F §G §I §J §O were
replaced by real cases rather than deleted.

## Running §P — the real dispatch

```bash
cd fleet/it
R="$PWD/RESULTS-P.tsv"; printf 'case\tverdict\tevidence\tnote\n' > "$R"
IT_RESULTS="$R" bash run-P.sh                  # ~10-15min; spends one real claude
```

Optional: `P_REAL_CLAUDE=/path/to/claude` (default `/home/ubuntu/.local/bin/claude`),
`P_TIMEOUT=900` (how long to poll for the worker to finish).

What it does: builds a slot whose lineage base is on a **diverged sibling** branch, dispatches a real
`claude` from `skills/using-fleet/profiles/worker`, delivers the rendered seed, and polls until the worker
renames itself `-complete-`. Then it asserts the coordinator can close the loop.

| Case | Asserts |
|---|---|
| P1 | the pane is live and `pane-guard` classifies it as a claude pane (asked of the product, never a grep) |
| P2 | the send contract answers correctly against a live model |
| P3 | the worker followed the whole contract from the seed alone: report, review round, `propose` into the coordinator's inbox, self-rename |
| P4 | `apply` → wait on `pane-guard` → `close` → `harvest`, and the row leaves the board |

**Re-run §P whenever you change a skill or a verb a skill names.** In one pass it found four defects that V1,
V2 and V3 structurally could not: an invalid copy-paste `--finding` example that exited 2 in the exact block a
finishing worker pastes; a refusal whose remedy named a subcommand that never existed; `review --dry-run`
exiting 2 *silently* on valid input; and a `brief` row that stated a stored label and a derived fact as if one
contradicted the other. All four lived on paths the hermetic suite never asked about, because every test there
asserted the *recorded* path — nobody had asked what a worker sees when it does the responsible thing first.

It also reads the worker's own written report at
`fleet/it/P/instants/*-complete-append-prealworker/evidence/P-worker-report.md`. **Read it.** The task asks the
worker to be blunt about what was wrong, missing or unfollowable, and that prose is the actual deliverable —
the four PASS rows only say the mechanism held.

## Hard rules

**Never start a `dt-` session on the default tmux server.** `fleet dispatch` launches a real `claude` in a
session named `dt-<name>`, and a live coordinator may be attached to one. Export `FLEET_TMUX_SOCKET` first.
Every runner does this through `it_section`; a bare shell does not.

**Probing by hand? Source the sandbox.** It exports a scratch store and a private socket in one line:

```bash
. fleet/it/bin/adhoc-sandbox.sh
# FLEET_HOME / FLEET_INSTANTS / FLEET_TMUX_SOCKET / PYTHONPATH are set; it prints the teardown command
```

This exists because a hand-run `fleet dispatch` from a bare shell once put a real `claude` in `dt-probec` on
the live server. The harness was safe and the shell was not.

**Never touch `~/.claude-dispatch-board` or `~/.claude-ws-pool`.** Live operator state, read by a running
watchdog daemon. `FLEET_HOME` is always explicit.

**Never pipe a control.** `bash control.sh | tail` reports `tail`'s exit status, not the control's. Use
`if bash control.sh; then` — a commit once landed with `P-3` red for exactly this reason.

**Do not edit `src/` or `tests/` while anything is measuring.** `source-pin.sh` pins both around every section;
a changed pin means CONTAMINATED, which is not a verdict. The pin is a shared resource.

## The controls

```bash
bash fleet/it/bin/assert-head-green.sh     # P-1: green verified from a `git archive` EXPORT, never the worktree
bash fleet/it/bin/source-pin.sh before DIR # P-2: pin src/ + tests/ around a measurement
bash fleet/it/bin/lint-evidence-paths.sh   # P-3: no evidence cited by absolute path
```

`P-1` is the one that matters at commit time: it exports the commit, imports the package and runs the suite
from that export, because a suite run in your working tree cannot tell you what the commit contains.

## Adding a verb — the checklist

A verb list is *derived* from `VERBS`; several test fixtures are *hand-written*. Adding a verb therefore
breaks things that nothing reminds you about. This list is what three added verbs (`milestone`, `brief`,
`base-check`) actually broke:

1. `src/fleet/cli.py` — the handler, `_verb(...)` registration, and an entry in `PORCELAIN_COLUMNS`
   (omitting it raises `KeyError` at emit time).
2. `tests/test_cli.py` — `argv_for`'s dict. A coverage test asserts it matches `VERBS` exactly.
3. `tests/test_contracts.py` — **the same row again**, in its own `argv_for`. Two tables, both required.
4. `it/run-A.sh` — `a1_args`, or `A1b` reports your verb as one that "did not refuse".
5. `it/run-group5.sh` — **two** maps: §L7's and §M5's `m_args`.
6. If the verb is read-only, say so in `_verb(..., read_only=True)`; `--dry-run` is derived from that field,
   not typed per verb.

Then re-run §A, §L/§M (`run-group5.sh`) and §P. Steps 4 and 5 are the ones people miss, and the symptom is a
section failing for a reason that has nothing to do with your change.

## Adding a `board`/`status` column

`it/run-group3.sh`'s §E4 derives the expected field count from `PORCELAIN_COLUMNS["board"]`. It used to
hardcode `6`; adding the `milestone` column made all 50 iterations report a torn render. If you add a column
anywhere, check nothing counts fields by literal.

## The claude-watchdog daemon, and the one pdispatch file left

`scripts/claude-watchdog.sh` provides **auto-resume**: when a claude session hits its usage limit, a per-session
monitor scrapes its tmux pane and, once the limit resets, sends `"Continue where you left off." + Enter`. Zero
token cost while waiting; the daemon re-reconciles every 300s so new in-scope sessions get covered.

```bash
bash scripts/claude-watchdog.sh status      # daemon state + per-session coverage
bash scripts/claude-watchdog.sh arm         # start the daemon, arm in-scope sessions
bash scripts/claude-watchdog.sh disarm      # stop the daemon, kill in-scope monitors
```

`finished_dispatch_pids()` builds the list of pids that must NOT be armed, and **its default is now
`scripts/fleet-finished-pids.sh`** — the fleet-backed answer. The reason the exclusion matters is in the
watchdog itself: two workers nine days past the end of their effort still had live monitors, and on a
rate-limit banner a monitor types into a pane whose cwd may since have been **re-leased to a different
effort**. `CLAUDE_WATCHDOG_SESSIONS_TOOL` still overrides, so the old pdispatch tool is one variable away for
as long as it exists.

The mapping that matters, and it is easy to get backwards: exclude a **`worker` subject in `state COMPLETE`**,
never an `unarmed` row. `reconcile` marks every unmanaged session `unarmed` because nothing in the store
authorises acting on it — correct for reconcile's question, and catastrophic for this one, since it would
exclude every session on a box with no fleet records and silently switch auto-resume off.

`scripts/tests/fleet-finished-pids.sh` asserts both directions against a real store, a real tmux server and
three live processes — a finished worker IS printed, a working worker is not, and an unmanaged session is not:

```bash
bash scripts/tests/fleet-finished-pids.sh      # ~15s, spends no claude
```

It uses a copy of `/bin/sleep` named `claude`, because the CLI builds its probes with `default_probes()` and
`pgrep -x claude` is not overridable from outside. Run it if you touch either script.

**Which store the watchdog reads.** `FLEET_HOME` is now *stated* in the watchdog (`${FLEET_HOME:-$HOME/.fleet}`)
rather than inherited. `fleet`'s read-only verbs default to `$HOME/.fleet` anyway, so leaving it unset would
have worked — and would have meant a daemon that runs for weeks silently followed whatever `FLEET_HOME` was
exported into the shell that happened to arm it, which differs per effort.

**The exclusion announces its own state, and this is the part worth knowing.** `finished_dispatch_pids` treats
every failure as "exclude nothing" — right, because excluding a pid in error costs an auto-resume that should
have happened and there is no error channel back to a caller that only reads pids. But it makes a *broken*
exclusion and an *empty* one look identical, and on a box with no fleet store "exclude nothing" is permanent.
So the state is written to the log, and only when it changes (the daemon wakes every 300s; a line per pass is
how a log stops being read):

```bash
tail -5 "$DAVIS/.claude-auto-retry/watchdog-daemon.log"
cat "$DAVIS/.claude-auto-retry/watchdog-exclusion.state"
# INERT — no store at /home/ubuntu/.fleet/records, so there are no dispatch records to derive
#          finished workers from
```

`INERT` is the expected reading until a dispatch actually writes records into that store; it becomes `active`
on its own once one does. Note `CAR_DIR` is `$DAVIS/.claude-auto-retry` — the tool's `HOME` is `$DAVIS`, not
the operator's, so its state is NOT under `~`.

**Dispatched instants ARE covered now, and it needed a patch.** `claude-auto-retry` invokes `tmux` with no
server option, so it only ever saw the default server — and `fleet dispatch` deliberately uses a private one.
The result was silent: `reconcile` printed *"All live claude sessions already monitored"*, which is also what
it prints when everything is genuinely covered, while no dispatched instant had auto-resume at all.

```bash
bash patches/claude-auto-retry/verify.sh          # is the patch present AND behaving?
bash patches/claude-auto-retry/verify.sh --apply  # re-apply after an npm install reverts it
```

`CLAUDE_AUTO_RETRY_TMUX_SOCKET=<name>` now selects the server for every tmux call and for pane discovery; the
monitor inherits it through the environment, never argv, because `monitor.js <pane> <pid>` is parsed by a
regex in two places. `claude-watchdog.sh` sweeps every server in `CLAUDE_WATCHDOG_TMUX_SOCKETS` (default
`fleet`) — included by default rather than opt-in, since an opt-in list is one somebody forgets on the day it
matters. Verified against a pristine upstream v0.6.0: applies cleanly, 352/352 of the package's own tests
still pass, because the argv builders are untouched and the prefix goes on at the exec boundary.

**Run `verify.sh` after any npm install in `opt/car`.** The patch lives in `node_modules`.

**The bigger win is still not done.** The monitor sends `Continue…` on a rate-limit banner **without
consulting `fleet pane-guard`**, which is precisely the guard for that hazard (`0` safe / `10` queued-text /
`11` mid-turn / `12` not-claude / `13` unknown). Gating the send would need a change inside the vendored
`claude-auto-retry` monitor, not in this repo. `J8` proves `fleet close` refuses both dangerous pane shapes; the
monitor has no such gate. Note what the switch above did and did not buy: it fixed WHICH sessions get armed,
not what a monitor does once armed.

## Known gaps

- **Nothing delivers the seed to a worker.** `dispatch` writes `.fleet/seed.txt` into the *instant* and starts
  the process in the *slot*, with no prompt. Delivery is the caller's job, gated by `pane-guard`. §P's launcher
  does it; production has no verb for it.
- **A dispatched worker's cwd is its leased slot, not its instant folder.** The seeds export `$INSTANT` for
  this reason. `--instant .` is wrong for a worker.
- **The coordinator can type a wrong lineage SHA.** Nothing checks it is the *right* base for a milestone, only
  that the slot ends up there. The design that closes this (`propose --tip`, `dispatch --lineage-from`) is
  written up but not built.
- **§C10 is the one structural SKIP worth knowing about.** It needs a *succeeding* dispatch, which §C's own
  contract forbids, so it cannot be asserted there. Its second reason — "there is no clone to observe" — was
  removed by `fleet clone` (`SI-19`); the first still stands.
