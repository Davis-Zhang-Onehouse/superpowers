# dispatchInstants — retired

Not a skill. Not a toolkit. **Two files, kept alive for one reason**, and that reason is named below so
whoever finishes the job does not have to rediscover it.

## What was removed

The skill (`SKILL.md`, `docs/`, `tests/`) and every `pdispatch` executable: `base-check`, `dispatch-adopt`,
`dispatch-alive`, `dispatch-board`, `dispatch-close`, `dispatch-health`, `dispatch-launch`, `dispatch-send`,
`dispatch-todo`, `install-branch-guard`, `profile-check`, `ref-guard`, `wspool`, `pdispatch` itself, and the
profile templates. The `bin/` symlinks to all of them went with them.

Replaced by:

| For | Use |
|---|---|
| the coordinator's role | `superpowers:coordinating-instants` |
| being a dispatched worker | `superpowers:working-as-a-dispatched-instant` |
| the command surface | `superpowers:using-fleet` |
| `base-check.sh` | `fleet base-check`, wired into a gate on `propose --status done` / `complete` rather than a script somebody has to remember to run |
| `dispatch-board.sh`, `dispatch-todo.sh` | `fleet board`, `fleet roadmap` |
| `wspool.sh` | `fleet enroll` / `fleet leases` / `fleet reap` |
| `dispatch-close.sh` | `fleet close`, plus `fleet pane-guard` for the send contract |

## Why these two files are still here

`scripts/claude-watchdog.sh` — **which is running right now**, as a `setsid` daemon, and which provides
auto-resume for this box's claude sessions after a usage limit — calls
`dispatch-sessions.sh --finished-pids` every interval. `dispatch-sessions.sh` sources `lib/dispatch-lib.sh`
and reads `$HOME/.claude-dispatch-board/records`. Nothing else here is referenced by anything.

**Repointing the watchdog at `fleet` is a migration, not a cleanup, and that is why it was not done here.**
`fleet reconcile` is the right replacement in principle — its whole purpose is "the arm set the external
monitor reads, from the one join", and `J7` proves it reports sessions no record claims and never reaps them.
But the live sessions the watchdog covers have records in the OLD board, not in any `FLEET_HOME`. Point the
watchdog at `fleet reconcile` today and it sees no records, classifies every live session as unclaimed,
returns nothing from `--finished-pids`, and **silently stops reaping finished monitors**. A cleanup that
quietly disables a running safety net is worse than the mess it tidied.

Finishing it needs, in this order:
1. the sessions the watchdog covers represented in a `FLEET_HOME` (via `fleet resume`, which evaluates no
   admission rule precisely so a recovery path cannot be refused);
2. `claude-watchdog.sh` repointed at `fleet reconcile --porcelain`, branching on the `armed`/`unarmed` rows
   instead of on `--finished-pids`;
3. these two files, and `bin/dispatch-sessions`, deleted.

## What was deliberately NOT touched

`~/.claude-dispatch-board` and `~/.claude-ws-pool` — the operator's live stores. They hold the records the
running watchdog reads, and no verb in this repository deletes outward state.
