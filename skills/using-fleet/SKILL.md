---
name: using-fleet
description: Use when running any `fleet` command — the verb surface, exit codes, porcelain output, and the store/socket environment. Triggers include "fleet dispatch", "fleet roadmap", "what fleet verb", "FLEET_HOME", "porcelain", "exit code 4", "which verbs are read-only".
---

# Using fleet

## Overview

`fleet` coordinates multi-instant efforts: it leases workspaces, dispatches worker instants, and carries their
reported status onto a roadmap. It is a python3-stdlib-only package with no third-party dependencies. `bin/fleet`
is on PATH in this repo, so every command below is typed as written.

State lives in two places and nowhere else:

| Where | What |
|---|---|
| `$FLEET_HOME` | the pool (`pool/enrolled`, `pool/leases`), dispatch records, the harvest registry, the declared golden |
| `<instant>/.fleet/` | that instant's own `roadmap.json`, `proposals.json`, `declare.json`, `review.json`, `origin.json`, `seed.txt` |

No `.md` file is ever read as state. `render` turns JSON into markdown, never the reverse.

**Announce at start:** "I'm using the using-fleet skill for the fleet command surface."

## The environment is always explicit

```bash
export FLEET_HOME=/path/to/store          # the pool and the records
export FLEET_INSTANTS=/path/to/instants   # where instant folders live
export FLEET_TMUX_SOCKET=itfleet-mine     # optional: a PRIVATE tmux server
```

A verb with neither `--home` nor `FLEET_HOME` resolves its store from the **`.fleet-root` marker** at or
above the working directory — the way `git` finds `.git` — and **refuses** when it finds none, naming the
directory it searched and what would clear it.
<!-- v2-cite: mutating-verb-names-its-store A1 -->

That refusal exists for a measured reason: before it, four mutating verbs wrote a real store under
`$HOME/.fleet` and exited 0 without mentioning it, and two of them renamed instants there.

⚠️ **Read-only verbs used to keep that `$HOME/.fleet` default**, on the ground that *"nothing is enrolled"*
is a real answer to a real question. **They no longer do.** Once a box runs more than one fleet, a
permissive read is not answering about no fleet — it is answering about a **different root's** fleet,
confidently and with a population row. So a read refuses too. The visible cost: `fleet board` in an
unmarked directory prints a refusal rather than an empty board.

Each root is one directory under `$HOME` carrying `.fleet-root`, whose declared name gives that root its
tmux server:

```
~/davis_root/.fleet-root      {"name": "davis"}     -> store ~/davis_root/.fleet,  socket fleet-davis
~/davis2_root/.fleet-root     {"name": "davis2"}    -> store ~/davis2_root/.fleet, socket fleet-davis2
```

Two roots share no record, no slot, no server and no release area. Enrolling a workspace that belongs to
another root is refused, and so is a dispatch whose instants directory points out of its own root.

**Where instants are created is still named, never derived.** `--instants-dir` or `FLEET_INSTANTS`, or the
verb refuses: `$FLEET_HOME/instants` used to be a default and it planted a dispatched child outside its
effort tree at rc=0 with every guard green, invisible until an endgame compaction could not find it.

`FLEET_TMUX_SOCKET` selects the tmux **server**. Set it before anything that could start a session:
`fleet dispatch` launches the selected Claude or Codex CLI in a session named `dt-<name>`, and on the default server that is
the one act you must never perform against somebody else's coordinator. Unset, commands see the real live
sessions — which is correct in production, because guarding a live pane is what several verbs are for.

## The verbs

Read-only. Safe to run at any time; they change nothing.

| Verb | What it answers |
|---|---|
| `fleet board` | every subject HOLDING A SLOT, and nothing else |
| `fleet status` | one subject in full, with the evidence behind its state |
| `fleet leases` | every enrolled slot and who holds it |
| `fleet peers` | which live agent sessions this fleet may address, and which are FOREIGN |
| `fleet roadmap` | milestones, readiness, blockers and pending proposals |
| `fleet brief` | what a dispatched instant needs to know about itself |
| `fleet base-check` | is this workspace positioned on the base its milestone builds on? |
| `fleet reconcile` | the arm set an external monitor reads, from the one join |
| `fleet compaction-status` | whether a compaction is holding every dispatch |
| `fleet pane-guard` | the pane contract every send and close branches on, as an exit code; keyed by `--id <todo>` or `--pane <session>` |
| `fleet seed-check` | is every live worker running the briefing that was rendered FOR it? |
| `fleet lint` | the layout matrix, the watched-source registry, the near-miss rule |
| `fleet verify` | EXECUTE every documented recipe in a sandbox |
| `fleet selftest` | discover and run every suite; the tree state is always stamped |
| `fleet release-status` | what is deployed right now, since when, by whom and why |
| `fleet release-list` | every release, its state and its cut time |
| `fleet release-history` | the deploy/rollback register |

Mutating. Each has `--dry-run`.

| Verb | What it does |
|---|---|
| `fleet runtime` | read the saved runtime; `--set claude` or `--set codex` changes it between completed runs |
| `fleet send` | deliver a message file to an owned worker after observing an empty idle input |
| `fleet revive` | resume an explicit session UUID using the record’s runtime, workspace and configuration |
| `fleet init` | bootstrap a new instant from the layout matrix |
| `fleet dispatch` | evaluate every gate, then dispatch one worker |
| `fleet resume` | adopt an existing conforming instant; evaluates NO admission rule |
| `fleet milestone` | the coordinator puts a milestone ON the roadmap — the only way work becomes dispatchable; `--retire` drops one, `--disown` releases a claim stranded by an instant that is gone |
| `fleet propose` | the worker's status proposal; never a roadmap write |
| `fleet apply` | the coordinator applies a proposal; the single writer of a status. Lands the NEWEST pending row for the milestone (`--at <stamp>` picks one) and closes the earlier ones as superseded; refuses to move a done/dropped milestone unless `--reopen` |
| `fleet withdraw` | close pending proposals without applying them (`--at` for one row, `--reason` required); writes the inbox, never the roadmap |
| `fleet declare` | declare a phase, and print what the consumer now reads; `awaiting-ci` is REFUSED unless a watcher is armed |
| `fleet park` / `fleet unpark` | record or clear a parked decision as structured state |
| `fleet review` | record a structured round and report the gate |
| `fleet complete` | pass the gate, then rename the folder `-complete-` |
| `fleet abort` | abandon an inflight instant, with a recorded reason; RELEASES the milestone it claimed |
| `fleet harvest` | the close-out transaction, plus the observation tick |
| `fleet close` | shut a pane this store owns and stamp the record |
| `fleet seed-delivered` | record what was actually sent to a worker's pane — the positive channel for a briefing delivered by hand into a pane (a resumed or manually started worker), which leaves nothing in argv; `fleet dispatch` puts the seed in argv itself |
| `fleet reap` | free every stale lease this base owns; name the ones it does not |
| `fleet root-init` | make a directory a fleet root: its `.fleet-root` marker, store skeleton and release area. Refuses anything that is not a directory strictly under `$HOME`, and anything already inside a root — the walk stops at `$HOME` and at the nearest marker, so either would be a root no verb could find. `--share-releases <dir>` points it at an existing release area so both roots resolve one `current` |
| `fleet enroll` / `fleet unenroll` | put an existing workspace into the pool, or take it out |
| `fleet set-golden` | declare the golden workspace; there is deliberately no fallback |
| `fleet clone` | duplicate the declared golden into a new slot and enrol it |
| `fleet release-cut` | export an immutable release from a tag and write its changelog |
| `fleet release-verify` | run both suites against a release and record the verdict |
| `fleet release-promote` | mark a CANDIDATE as RELEASED; refuses without GREEN evidence |
| `fleet release-deploy` | point `current` at a release, or at the checkout with `--dev` |
| `fleet release-rollback` | point `current` back, recording why |

Every verb's flags are on its own help, and the help is derived from the same table the parser uses — so it
cannot document one thing and accept another:

```bash
fleet dispatch --help
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | ok |
| 1 | needs attention / a check failed |
| 2 | bad input |
| 3 | no capacity |
| 4 | refused by an admission rule |

`4` is the one worth recognising: it means a rule *decided against you*, not that anything broke. The message
names the blocker, what clears it, and who clears it. `1` means a checker found something that needs a human.

`fleet pane-guard` has its own codes because it is a contract for an external monitor: `0` safe, `10`
queued-text, `11` mid-turn, `12` not-claude, `13` unknown-pane, `14` indeterminate, `15` awaiting-operator.
Branch on the code before any send.

`14` means the pane is alive and nothing about it could be READ — a failed observation, not a negative one.
Treat it as wait, never as permission: before a send everything but `0` waits anyway, but before a CLOSE the
difference is a live pane mid-turn being torn down (`FI-7`).

`15` means the pane is showing an operator dialog — `AskUserQuestion`, the folder-trust screen, or Codex's
approval prompt — blocked on YOU, not on a turn that
will finish by itself (`I-16`). It reads nothing like `10`/`11`/`14`: those clear with time, this one does
not, so a coordinator that sees `15` should stop polling and go answer the pane, not wait on it. Before
this code existed a dialog fell through to `0 safe`, the same answer an idle worker gets — a scheduled
poll saw a healthy quiet pane while the worker was blocked waiting on an operator.

### Selecting the runtime

`fleet runtime` reports the saved choice; an older store without a setting defaults to Claude.
From a normal shell, after harvesting every worker and stopping the coordinator:

```bash
fleet runtime --set codex
```

Start the matching coordinator CLI manually. Dispatches use this choice; model settings stay with that
CLI. Changing back uses `fleet runtime --set claude`. Open records, held leases and live in-scope
agents block a change, including a crashed worker with an unfinished record. Resolve that work first;
never delete a lease or edit `runtime.json` to bypass the refusal. The operator setup is in
`docs/README.fleet-runtimes.md`.

### Delivering text to a worker

Write the complete message to a file, then use the recorded worker ID:

```bash
fleet send --id "$ID" --message-file "$MESSAGE_FILE" --dry-run
fleet send --id "$ID" --message-file "$MESSAGE_FILE"
```

The command locks that pane, checks its ownership and empty idle input, pastes once, observes the exact
draft, sends Enter once, and observes consumption. Busy, queued, modal and unfamiliar panes refuse.
If delivery becomes uncertain, inspect the pane; do not retry automatically, clear a human's draft,
or send an extra Enter. Immediate text-plus-Enter can lose the Enter on a real TUI (`FI-15`).

`fleet peers` reports runtime and address transport in human output. Use `fleet send` for owned tmux
workers. A native messaging API is usable only when the current harness exposes it and peer discovery
supplies its address; a tmux session name is not a native agent ID. FOREIGN or unaddressable peers are
not message targets.

A known agent with an unfamiliar input returns `14 indeterminate`. Every positively identified operator
dialog — Claude's folder-trust screen or `AskUserQuestion`, Codex's approval prompt — returns `15
awaiting-operator` (above), on either CLI: the advice is the same for all of them, go answer the pane. `12 not-claude` retains its legacy label and means a positively identified
non-agent pane. Treat every nonzero guard code as wait
before sending. Codex has no verified CI wake mechanism here: `awaiting-ci` is refused, even with a
watcher attestation, and the worker continues to count against capacity.

## Releasing fleet

A release is an **immutable export of a tag**, plus a verdict from both suites, plus a `current` symlink
saying which one is live. Four states: cut → verified → promoted → deployed.

```bash
fleet release-cut     --version 0.4.0 --repo "$REPO" --releases "$FLEET_RELEASES" --notes "…"
fleet release-verify  --version 0.4.0 --releases "$FLEET_RELEASES"     # both suites; ~25 min
fleet release-promote --version 0.4.0 --releases "$FLEET_RELEASES"     # refuses without GREEN
fleet release-deploy  --version 0.4.0 --releases "$FLEET_RELEASES" --reason "…"
fleet release-rollback --reason "…"    --releases "$FLEET_RELEASES"    # --to, or the register decides
```

Seven things you cannot guess, each of which cost something to learn:

1. **A cut needs a CLEAN tree.** An export carries committed content only, so a dirty tree means the
   thing tested is not the thing you edited. Refused, with the paths named.
2. **`release-verify` needs a REPOSITORY, not just the artifact.** It runs the IT suite from a
   `git worktree` at the release's tag, because the suite cannot judge an export — several cases need a
   real `.git`, and `git archive` writes none. A cut records `source_repo`; an older release needs
   `--repo`. A release that records neither is **refused**, never quietly verified against the export.
3. **A CANDIDATE is not deployable, and a promote without GREEN evidence is refused** — exit `4`, a rule
   deciding against you, not a breakage.
4. **The verdict comes from the FAIL rows in this run's own registers**, never from `run-all.sh`'s exit
   status. That script reports; it is not a gate. A release once recorded GREEN over a suite with seven
   FAIL rows because something asked it (`SI-38`).
5. **To triage a RED, read the per-runner registers** — `.release/evidence/it-RESULTS-closeout-*.tsv` —
   and never the merged `it-RESULTS.tsv`, which keeps rows from runs that did not happen this time. The
   evidence a FAIL row cites is copied into `evidence/it-cited/`, because the worktree it lived in is
   deleted when the run ends.
6. **Retention is 10 releases.** The oldest beyond that are removed at the next cut — never the deployed
   one, however old. Nothing is lost: the TAG is the durable artifact and a cut rebuilds the export.
7. **`--dry-run` exists on every mutating verb here**, and on `release-cut` it tells you the commit, the
   tag and the commit count without writing anything.
8. **A release that changes nothing either suite reads is `EXEMPT`, and `verify` returns in seconds.** A
   release is a `git archive` of the WHOLE repo — it ships `skills/`, `docs/` and the plugin manifest, and
   the deployed export is the marketplace source Claude Code loads skills from — so a docs- or skills-only
   release otherwise pays ~24 minutes to prove that `fleet/`, which it did not touch, still works.
   `release-verify` computes this before it spawns anything, and `release-promote` accepts `EXEMPT`, so
   **no `--force` and no per-release judgement call**. Four things make it safe:
   - The classifier is an **allowlist** (`fleet/src/fleet/release_scope.py`): a path is inert only because
     it matches something declared. An unrecognised path — a new top-level directory, a new script — runs
     the suites. A denylist would be fail-open and the failure would ship invisibly.
   - **`skills/using-fleet/**` is NOT inert**, because two suite call-sites read it: `test_contracts.py`
     asserts verb parity against this file in both directions, and `fleet/it/run-P.sh` copies its
     `profiles/worker` fixture. "Outside `fleet/`" is not the same as "not covered by the suites".
   - The anchor is the newest release verified **GREEN**, never the immediate predecessor and never
     another `EXEMPT` one — so a chain of docs-only releases stays anchored to code a suite actually saw.
     No anchor, or a missing anchor tag, means run the suites (the missing tag is refused outright).
   - The verdict is spelled `EXEMPT`, never `GREEN`, and cites `evidence/EXEMPTION.tsv` listing every
     changed path with its classification — so "the suites passed" and "the suites were not required"
     stay distinguishable, and the decision is re-derivable with one `git diff --name-only`.

   `--full` never exempts, and an `EXEMPT` verdict cannot promote a **minor or major** bump: a bump that
   size claims substantive change while the exemption claims the opposite.

`release-status` answers "what is live right now"; `release-history` is the append-only register of every
deploy and rollback, with who, when and why.

## Porcelain

Every observation verb takes `--porcelain` and emits tab-separated fields whose column schema is declared
data, not a formatting accident:

```bash
# what can be dispatched right now: ready, and nobody holds it ($7 title, $8 owner)
fleet roadmap --instant . --porcelain | awk -F'\t' '$1=="ready" && $8==""{print $2, $7}'
# what is waiting, and on what
fleet roadmap --instant . --porcelain | awk -F'\t' '$1=="not-ready"{print $2, $4}'
```

**Parse columns; never grep a sentence.** Checker verbs emit `kind`, `subject`, `severity`, `detail`,
`clears_when`, `clears_who`; `roadmap` appends `title` and `owner`, filled on every row about a milestone
(empty on a proposal whose milestone is not on the roadmap). Every milestone gets exactly one `ready` row (its
deps have landed — `owner` empty means dispatchable, non-empty means already claimed) or one `not-ready` row
(the `detail` names the blocker), plus one `pending-proposal` row per proposal waiting on it. Act on
`severity=violation`; report `severity=info`. A finished milestone, a ready one and a legitimately empty
population are `info`, and treating them as alarms is how a healthy board comes to read as red and then gets
ignored.

**The last row of `board` and `leases` porcelain is `population`** — the store or pool that was read, with
the same counts the human banner shows (`board`: `kind`=`population`, `identity`=the store; `leases`:
`lease`=`population`, `slot`=the pool, counts in the appended `note` column). An empty fleet is therefore
one row, never zero bytes, and a script can tell it from a wrong `FLEET_HOME`. Count subjects or slots by
column (`$2=="held"`), never with `wc -l` over the whole output.

## `--dry-run`

Every mutating verb has one, derived from whether the verb is read-only rather than added per verb — so the
next mutating verb anybody writes gets an interrogable form whether or not they remembered to ask for one. A
dry run evaluates every gate and writes nothing: not a lease, not a record, not a file.

Use it to ask "would this be admitted?" A guard you cannot interrogate non-destructively gets interrogated
destructively — twice, by two actors, one of whom had read the entry that declined to run that exact command.

## Where the pieces live

```
fleet/src/fleet/      the package (31 verbs)
fleet/tests/          the hermetic suite
fleet/it/             the integration harness: run-*.sh, lib.sh, RESULTS.tsv, and four controls in bin/
bin/fleet             this launcher
```

`fleet/it/RESULTS.tsv` is the current verdict for every integration case — current state, not an append log.
Skills cite case ids from it, and `skills/using-fleet/tools/lint-skill.py` checks that every refusal a skill
claims names a case that actually passed.

## Related skills

- `superpowers:coordinating-instants` — you are the coordinator of an effort.
- `superpowers:working-as-a-dispatched-instant` — you ARE a dispatched worker.
- `superpowers:dispatching-subagents` — parallel work inside ONE session; not instants.
