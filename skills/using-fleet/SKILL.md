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

A **mutating** verb with neither `--home` nor `FLEET_HOME` refuses rather than inventing a destination, and
says which flag to pass. Read-only verbs keep a default, because "nothing is enrolled" is a real answer to a
real question.
<!-- v2-cite: mutating-verb-names-its-store A1 -->

That refusal exists for a measured reason: before it, four mutating verbs wrote a real store under
`$HOME/.fleet` and exited 0 without mentioning it, and two of them renamed instants there.

`FLEET_TMUX_SOCKET` selects the tmux **server**. Set it before anything that could start a session:
`fleet dispatch` launches a real `claude` in a session named `dt-<name>`, and on the default server that is
the one act you must never perform against somebody else's coordinator. Unset, commands see the real live
sessions — which is correct in production, because guarding a live pane is what several verbs are for.

## The verbs

Read-only. Safe to run at any time; they change nothing.

| Verb | What it answers |
|---|---|
| `fleet board` | every subject HOLDING A SLOT, and nothing else |
| `fleet status` | one subject in full, with the evidence behind its state |
| `fleet leases` | every enrolled slot and who holds it |
| `fleet roadmap` | milestones, readiness, blockers and pending proposals |
| `fleet brief` | what a dispatched instant needs to know about itself |
| `fleet base-check` | is this workspace positioned on the base its milestone builds on? |
| `fleet reconcile` | the arm set an external monitor reads, from the one join |
| `fleet compaction-status` | whether a compaction is holding every dispatch |
| `fleet pane-guard` | the send-keys contract, as an exit code |
| `fleet lint` | the layout matrix, the watched-source registry, the near-miss rule |
| `fleet verify` | EXECUTE every documented recipe in a sandbox |
| `fleet selftest` | discover and run every suite; the tree state is always stamped |

Mutating. Each has `--dry-run`.

| Verb | What it does |
|---|---|
| `fleet init` | bootstrap a new instant from the layout matrix |
| `fleet dispatch` | evaluate every gate, then dispatch one worker |
| `fleet resume` | adopt an existing conforming instant; evaluates NO admission rule |
| `fleet milestone` | the coordinator puts a milestone ON the roadmap — the only way work becomes dispatchable |
| `fleet propose` | the worker's status proposal; never a roadmap write |
| `fleet apply` | the coordinator applies a proposal; the single writer of a status |
| `fleet declare` | declare a phase, and print what the consumer now reads |
| `fleet park` / `fleet unpark` | record or clear a parked decision as structured state |
| `fleet review` | record a structured round and report the gate |
| `fleet complete` | pass the gate, then rename the folder `-complete-` |
| `fleet abort` | abandon an inflight instant, with a recorded reason |
| `fleet harvest` | the close-out transaction, plus the observation tick |
| `fleet close` | shut a pane this store owns and stamp the record |
| `fleet reap` | free every stale lease this base owns; name the ones it does not |
| `fleet enroll` / `fleet unenroll` | put an existing workspace into the pool, or take it out |
| `fleet set-golden` | declare the golden workspace; there is deliberately no fallback |

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
queued-text, `11` mid-turn, `12` not-claude, `13` unknown-pane. Branch on the code before any send.

## Porcelain

Every observation verb takes `--porcelain` and emits tab-separated fields whose column schema is declared
data, not a formatting accident:

```bash
fleet roadmap --instant . --porcelain | awk -F'\t' '$1=="not-ready"{print $2, $4}'
```

**Parse columns; never grep a sentence.** Checker verbs emit `kind`, `subject`, `severity`, `detail`,
`clears_when`, `clears_who`. Act on `severity=violation`; report `severity=info`. A finished milestone and a
legitimately empty population are `info`, and treating them as alarms is how a healthy board comes to read as
red and then gets ignored.

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
