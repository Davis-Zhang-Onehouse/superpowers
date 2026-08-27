---
name: reviving-dead-panes
description: Use when a dispatched worker's tmux session is gone but its instant is not finished — after a machine reboot, an OOM kill, or a tmux server exit. Triggers include "the board says DEAD", "all my sessions died after the reboot", "revive the worker", "resume x2 in the right tmux session", "no session is alive", "error connecting to /tmp/tmux-1000".
---

# Reviving Dead Panes

## Overview

A reboot takes the tmux **server** with it. Every dispatched worker's session is gone at once, every
lease is still held, and `fleet board` reads `DEAD` for each one:

> *launched at 2026-08-26T23:00:31Z and no session is alive: the work stopped without renaming its folder*

**`DEAD` is a statement about the process, not about the work.** The instant folder, its `.fleet/` state,
its roadmap claim and the worker's own transcript all survive. Nothing is lost; a pane is missing.

**No verb revives one.** `fleet resume` adopts an existing *record* and starts nothing. `fleet dispatch`
is the only verb that starts a session, and it would mint a new instant, claim a fresh lease and
re-render the seed — that is a replacement, not a resume, and it discards everything the worker learned.
So revival is done by hand. This skill is the hand procedure and the four traps in it.

**Announce at start:** "I'm using the reviving-dead-panes skill to bring the worker's session back."

**REQUIRED BACKGROUND:** superpowers:using-fleet owns the verb surface, the `pane-guard` contract and the
send-keys rule this skill builds on.

## Decide first: revive, or abandon?

```dot
digraph revive {
    "Board says DEAD" [shape=diamond];
    "Is the milestone still wanted?" [shape=diamond];
    "Revive the pane" [shape=box];
    "fleet abort --reason" [shape=box];

    "Board says DEAD" -> "Is the milestone still wanted?";
    "Is the milestone still wanted?" -> "Revive the pane" [label="yes"];
    "Is the milestone still wanted?" -> "fleet abort --reason" [label="no"];
}
```

Read the instant's `HANDOFF.md` and its `.fleet/` before choosing. A worker that already recorded an
`abort.json` whose rename never completed is **not** a revival candidate — finish the abort instead;
re-running `fleet abort` over an already-recorded reason completes the rename, the pane close and the
lease release in one call.

## The procedure

```bash
SOCKET=fleet
SESSION=dt-<name>                      # from `fleet leases`, never invented
SLOT=/path/to/slot                     # from `fleet leases`, never invented
tmux -L "$SOCKET" new-session -d -s "$SESSION" -c "$SLOT" /abs/path/to/launch.sh
```

### 1. `new-session` runs the command through `/bin/sh -c`, so a `claude` shell FUNCTION is not there

Where `claude` is a shell function that selects `CLAUDE_CONFIG_DIR` per user before exec'ing the real
binary — the usual arrangement on a shared box — `sh -c` sees only the binary on `PATH`, with
`CLAUDE_CONFIG_DIR` **unset**. The revived worker then reads a different config directory and
`--resume <id>` finds nothing — while the transcript it should have read sits untouched in the
directory it never opened.

Put the exports in a launcher script and give `new-session` that script's absolute path:

```bash
#!/bin/bash
export CLAUDE_CONFIG_DIR=/home/<user>_root/.claude   # the trap: sh -c will not derive this
export FLEET_HOME=… FLEET_INSTANTS=… FLEET_TMUX_SOCKET=…
export INSTANT=/abs/path/to/the/instant
export PATH="…"                                      # the server's PATH is not your PATH
cd "$SLOT"
exec claude --resume <transcript-id>
```

**Do not name that script `claude` and do not put it on the tmux server's PATH.** That is precisely the
stale-shim shape `dispatch`'s seed-integrity check exists to catch — one such shim once handed a worker
another instant's briefing byte for byte.

### 2. Revive by transcript id, not `--continue`

A slot is re-leased across efforts, so the newest transcript in the slot's project directory is not
reliably the worker you are reviving. One slot here held three, from three occupants weeks apart.

```bash
SLUG=$(echo "$SLOT" | tr '/_' '--')     # /home/u/davis_root/ws2 → -home-u-davis-root-ws2
ls -lat "$CLAUDE_CONFIG_DIR/projects/$SLUG"/*.jsonl
```

Pick the id whose mtime matches the death, and pass it to `--resume` explicitly.

### 3. A resumed session opens a MENU, and `pane-guard` reads that menu as unsubmitted text

Past a size threshold the TUI asks how to resume — *Resume from summary / Resume full session as-is /
Don't ask me again* — before it is ready for input. Measured on a 435k-token session: **twelve
consecutive `pane-guard` polls, five seconds apart, all returned `10 queued-text`** while the pane was
showing that menu.

`10` there does **not** mean a human left something in the box. Two consequences:

- **Read the pane before you believe the code.** `10` is not evidence of a boot that finished.
- **The `until … [ $? = 10 ]` submit gate from superpowers:using-fleet falls straight through here.** It
  is designed to wait for text to land in a box; on a booting pane it passes immediately and the `Enter`
  it releases lands on the menu, silently choosing whatever option was highlighted.

### 4. `capture-pane -t "=$SESSION"` fails on a session that EXISTS

A pane target parses as `session:window.pane`, and `=name` alone is not a session part. Measured on tmux
3.2a against one live session:

| target | result |
|---|---|
| `dt-x2ansilinearstack` | rc 0 |
| `=dt-x2ansilinearstack` | rc 1 — **can't find pane** |
| `=dt-x2ansilinearstack:` | rc 0 |

`session.exact_pane_target` appends the colon for exactly this reason and the send-keys recipe inherits
it. An operator typing `capture-pane` by hand reaches for `=name`, gets *can't find pane*, and concludes
the revival failed when it did not.

## Never send a navigation key on spec

Capture the pane and confirm the menu is actually on screen before sending `Down`, `Up` or `Enter`. A
`Down` sent after the menu had already resolved landed in the input box instead and opened the
slash-command completer on **`/compact`** — one `Enter` away from compacting the very session being
revived. `Escape` clears it.

The general rule: a keystroke aimed at a widget that is not there does not vanish, it hits whatever is.

## Verify, and write nothing

Liveness is **derived**, so the board corrects itself once the process is up — no verb is needed and none
should be run:

```bash
fleet pane-guard --pane "$SESSION"    # 0 = safe
fleet board                           # DEAD → the declared phase, by itself
```

Measured: a worker went `DEAD` → `AWAITING-CI` with no fleet command run against it. If you find yourself
reaching for `fleet resume` to "re-register" a revived pane, stop — the record never stopped being
correct. Check the board first.

## Common mistakes

| Mistake | Reality |
|---|---|
| `fleet resume` to bring a pane back | It adopts a record and starts no process. The pane is yours to start. |
| `fleet dispatch` to "re-run" the worker | Mints a NEW instant and lease; abandons the transcript. That is replacement. |
| Reading `DEAD` as "the work failed" | It means no session is alive. The folder, `.fleet/` and transcript are intact. |
| Bare `claude` in `new-session` | `sh -c` misses the shell function, so `CLAUDE_CONFIG_DIR` is wrong and `--resume` finds nothing. |
| `claude --continue` | Picks the newest transcript in the cwd, which may belong to a previous occupant of the slot. |
| Trusting `pane-guard 10` during boot | The resume menu reads as queued text. Capture the pane. |
| `capture-pane -t "=$SESSION"` | Not a pane target. Use `=$SESSION:`. |
| Sending `Down`/`Enter` blind | Lands in the input box if the menu is gone; `/compact` is one Enter away. |

## Related skills

- superpowers:using-fleet — the verb surface, `pane-guard` codes, and the send-keys contract.
- superpowers:coordinating-instants — you are the coordinator deciding revive-vs-abort.
- superpowers:working-as-a-dispatched-instant — you ARE the worker that just came back.
