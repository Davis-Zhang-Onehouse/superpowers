# dispatchInstants — no longer a skill

The **skill** was deleted: its `SKILL.md`, `docs/` and `tests/` are gone, so nothing here is loadable as
guidance and nothing here contributes suites to `bin/superpowers-selftest`. What it taught — dispatching
instants through `pdispatch` with state in `~/.claude-dispatch-board` and `~/.claude-ws-pool` — is replaced by:

| For | Use |
|---|---|
| the coordinator's role | `superpowers:coordinating-instants` |
| being a dispatched worker | `superpowers:working-as-a-dispatched-instant` |
| the command surface | `superpowers:using-fleet` |
| `base-check.sh` | `fleet base-check`, wired into a gate on `propose --status done`/`complete` rather than left as a script to remember to run |

**The executables in this directory deliberately remain.** Every one of them is `bin/`'s target: `bin/base-check`,
`bin/dispatch-close`, `bin/wspool` and eighteen more are SYMLINKS into this folder, and `scripts/claude-watchdog.sh`
invokes `dispatch-sessions.sh` by path. Deleting the directory would break all of that silently, which is why the
skill surface and the executables were separated rather than removed together.

Removing the executables is a separate decision, to be taken when nothing references them — not folded into a
skill rewrite as a tidy-up.
