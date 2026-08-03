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
| `fleet release-status` | what is deployed right now, since when, by whom and why |
| `fleet release-list` | every release, its state and its cut time |
| `fleet release-history` | the deploy/rollback register |

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
| `fleet pane-send` | deliver text to a pane and CONFIRM it submitted — type, poll for `10`, then Enter |
| `fleet reap` | free every stale lease this base owns; name the ones it does not |
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
queued-text, `11` mid-turn, `12` not-claude, `13` unknown-pane, `14` indeterminate. Branch on the code
before any send.

`fleet pane-send` answers in the SAME vocabulary — its refusals are the guard's own classification, so
there is nothing to translate — plus one code of its own: `15` text-lost. `15` means the text was typed and
the box never came to hold it, so **Enter was not pressed**. It is the one code that must never be read as
success: an Enter into an empty box submits nothing and looks exactly like it worked.

`14` means the pane is alive and nothing about it could be READ — a failed observation, not a negative one.
Treat it as wait, never as permission: before a send everything but `0` waits anyway, but before a CLOSE the
difference is a live pane mid-turn being torn down (`FI-7`).

### Delivering text to a pane: type, WAIT, then Enter

`tmux send-keys <text>` immediately followed by `send-keys Enter` **loses the Enter**. The TUI has not
processed the text yet, so the keystroke reaches a widget that is not ready for it and is discarded. The
text then sits in the box unsubmitted and the worker looks like it simply stopped — which is exactly how
it looks to an operator, and why this went undiagnosed for days (`FI-15`).

Measured on a real pane, one session, varying only the gap:

| gap between text and Enter | result |
|---|---|
| none | **Enter dropped** — `pane-guard` still `10`, text queued, nothing submitted |
| 50ms and above | submitted |

The rule is therefore a **condition, not a delay** — and you do not implement it, because
`fleet pane-send` owns it:

```bash
fleet pane-send --pane "$SESSION" --text "$TEXT"     # type, poll pane-guard for 10, then Enter
```

It exits `0` only after re-reading the box and finding the text GONE, which is the difference between
"a keystroke was sent" and "a message was delivered". Anything else means nothing was submitted: `10`/`11`
are the pre-gate refusing (somebody else's text in the box, or a turn in flight — poll again), and `15`
means the channel took the text and lost it.

What it does, so nobody re-derives it:

```bash
fleet pane-guard --pane "$SESSION"                            # must be 0 FIRST: see the warning below
tmux -L "$SOCKET" send-keys -t "=$SESSION:" -l "$TEXT"        # -l: literally, and never with an Enter
until fleet pane-guard --pane "$SESSION"; [ $? = 10 ]; do sleep 0.2; done   # the box HAS the text
tmux -L "$SOCKET" send-keys -t "=$SESSION:" Enter
```

⚠️ **`10` means opposite things either side of the type.** BEFORE typing it is *somebody else's* text — an
operator half-way through a sentence — and a send there produces `<their unfinished sentence><yours>` and
then submits it, so it must REFUSE. AFTER typing it is *your* text, and it is the go signal. A caller using
only one of the two senses has half a contract.

`pane-guard`'s `10` means precisely *"there is text in the box"*, so it is the gate. No `sleep` constant
is right on a box under load. `fleet/it/bin/live-pane.sh submit` is a thin wrapper over the verb, so there
is one implementation and not two.

You will see the advice *"send a space before Enter"*. It works, and it works for the wrong reason — the
extra round-trip buys the milliseconds. Treating that as the mechanism leaves the channel one scheduling
hiccup from dropping instructions again, with a space keystroke as the charm that was meant to prevent it.

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

`release-status` answers "what is live right now"; `release-history` is the append-only register of every
deploy and rollback, with who, when and why.

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
