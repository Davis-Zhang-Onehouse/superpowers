# Dispatch session lifetime — design

Date: 2026-07-28 | Status: APPROVED (implementing)

## Problem

`dispatch-launch` creates a tmux session and stamps `launched_at` on the dispatch record.
**Nothing ever writes the closing half of that lifecycle.** There is no `closed_at` and no close verb.

Measured consequence on 2026-07-28: four dispatched sessions were alive with no work left to do, two of
them for **9 days and 3 hours**, belonging to an effort that finished on 2026-07-20. Two live processes
held `~/ws3` as their cwd simultaneously — a 9-day-old worker and a current one — because the slot had
been re-leased and repositioned onto another effort's branch while the old session still pointed at it.

Every related defect is downstream of the missing verb:

| Defect | Why it exists |
|---|---|
| Harvest never closes the session | there is no close verb for it to call |
| `health --orphans` detects but by design never escalates | with nothing to call, escalation would be an alarm that cannot clear |
| `claude-watchdog.sh` re-arms an auto-retry monitor on a finished dispatch forever | "finished" is not a fact the daemon can read |
| `wspool release` frees a slot a live process still occupies | staleness is defined as "tmux session gone", and the session outlives the work |
| A swallowed submit is invisible | nothing has ever inspected the pane's input buffer |

### Two corrections to the prior record

1. **Idle sessions do not consume token budget.** `health --orphans` asserts they compete for
   account-wide budget. Measured: 28m of CPU across 9 days, blocked in `ep_poll`, no child processes, no
   conversational turn in the transcript for 8 days. The cost is ~1.5 GB RSS on a 123 GB box. The claim
   that drove the 2026-07-27 teardown of seven harvested workers was never measured.
2. **Teardown is far less irreversible than assumed.** Session transcripts persist under
   `~/.claude/projects/<cwd-slug>/*.jsonl`; a torn-down session is recoverable with `claude --resume
   <session-id>`. Killing a pane costs loaded context, not history.

The hazards that *are* real, and that justify the work: a stale session pointed at another effort's
checkout, and a live `claude-auto-retry` monitor able to type into it.

## Non-goals

- Killing sessions the dispatch board cannot account for. Unclaimed sessions are reported, never reaped.
- Changing how work is dispatched, gated, or harvested. Only the session's end-of-life is in scope.
- Reclaiming disk or pruning transcripts. Transcript persistence is what makes teardown safe; it stays.

## Architecture

One new record field set, one new verb, three integrations, two independent hazard fixes.

**Record gains:** `closed_at` (ISO8601 Z), `closed_by` (`harvest` | `ttl` | `manual`),
`keep_session_reason` (set only when teardown was deliberately skipped).

### ① `bin/dispatch-close` → `pdispatch close <id>`

The counterpart to `dispatch-launch`, deliberately symmetric: launch stamps `launched_at`, close stamps
`closed_at`.

- Resolves a unique id **prefix or substring**; refuses an ambiguous one rather than taking whichever
  sorts first.
- **Refuses** (exit 1) unless the worker is finished — `harvested_at` present, or the resolved instant
  folder is `-complete-`/`-abort-`. `--force` overrides.
- **Refuses** if the pane is mid-turn (`esc to interrupt`, `Cooking…`-class spinner). Killing a working
  session is not cleanup.
- **Refuses** if the pane's input box holds unsubmitted text, naming the text. Teardown must never
  silently discard a queued instruction.
- Captures the pane tail to `<instant>/evidence/session-close/<id>-<ts>.txt` **before** killing.
- `tmux kill-session`, then stamps `closed_at`/`closed_by`.
- Releases the wspool lease **iff** its meta names this todo.
- Kills the `claude-auto-retry` monitor whose target pid was this session.
- Prints the `claude --resume` recovery route at the moment of destruction, not in a doc nobody rereads.
- Idempotent: closing an already-dead session stamps and exits 0.

Exit: `0` closed or already closed · `1` refused (state / busy / unsubmitted input) · `2` bad input.

### ② Harvest closes the session

`workspace-gate --harvest --record` calls close on a passing gate. `--keep-session <reason>` skips it and
persists `keep_session_reason`. Keeping becomes the thing that requires justification, not tearing down.

**A failed close never fails the harvest.** The gate verdict is about the worker's ledger; coupling it to
teardown would let a busy pane block a legitimate harvest.

### ③ `bin/dispatch-sessions` → `pdispatch sessions [--reap] [--base <i>] [--json]`

Enumeration **inverted**. `--orphans` walks records and asks "do you have a session?", so anything
without a record is structurally invisible — which is how an 8-day-old stray under GNU screen went
unseen. This walks live claude processes (`pgrep -x claude`, covering tmux and screen alike) and asks the
board "does a record claim you?".

Classification:

| Class | Meaning | `--reap` behaviour |
|---|---|---|
| `ACTIVE` | record exists, work not finished | never touched |
| `FINISHED` | record has `harvested_at`, or its instant folder is `-complete-`/`-abort-` | reaped once older than `SESSION_TTL_MIN` |
| `UNCLAIMED` | no dispatch record claims this pid | **listed, never reaped** |

`SESSION_TTL_MIN` defaults to **360** (6h). Harvest closes immediately, so the TTL only ever catches
escapes; it can be short without being twitchy.

**It escalates.** Exit `1` when at least one FINISHED session is past its TTL, `0` otherwise. This is safe
precisely because it is clearable — `--reap` in the same tick removes the condition. An alarm that can be
cleared may escalate; one that cannot, may not.

### ④ `wspool` becomes cwd-coupled

A slot whose path is the cwd of a live process is not free, whatever the lease file says.

- `release` refuses (exit 1) while a live process holds the slot path as cwd, naming the pids. `--force`
  overrides.
- `claim` skips such a slot when choosing a free one.

This removes the double-occupancy hazard structurally rather than by ordering discipline.

### ⑤ `claude-watchdog.sh` learns what "finished" means

`rebuild_exclude` additionally excludes any claude pid whose dispatch record is FINISHED, so the existing
`reap_monitors` path removes its auto-retry monitor. A finished dispatch stops having a keystroke
injector aimed at it even when teardown is deferred.

### ⑥ `dispatch-health` detects unsubmitted input

Pane is IDLE **and** the `❯` input box is non-empty → note on the row, and the row needs attention.

Gated on *idle* deliberately: a human mid-typing is not a stuck submit. Reporting sustained state rather
than instantaneous state is the rule the monitor-spam defect already paid for.

### ⑦ `--orphans` stops asserting something untrue

It delegates to ③ for its data and states the two measured hazards (stale cwd, live monitor) instead of
the budget claim, and it names transcript persistence so the next reader weighs teardown correctly.

## Data flow

```
dispatch-todo ──► record{dispatched_at}
       │
dispatch-launch ──► tmux new-session ──► record{launched_at}
       │
       ▼
   (worker works, renames its folder -complete-)
       │
workspace-gate --harvest --record ──► record{gate_verdict, harvested_at}
       │                                        │
       │                                        └──► dispatch-close ──► record{closed_at, closed_by=harvest}
       │                                                     │
       │                                                     ├─► pane captured to evidence/
       │                                                     ├─► tmux kill-session
       │                                                     ├─► wspool release (iff ours)
       │                                                     └─► auto-retry monitor killed
       ▼
dispatch-sessions --reap  (tick + watchdog daemon, every 300s)
       └──► any FINISHED past TTL that escaped the above ──► dispatch-close --force=no, closed_by=ttl
```

## Error handling

- **Every refusal names the specific condition** and the flag that overrides it. A refusal a reader
  cannot act on is a stall.
- **Close failure is never fatal to its caller.** Harvest reports and continues; the TTL sweep reports the
  session it could not close and leaves it listed, so it reappears next tick rather than being silently
  dropped.
- **No silent skips.** `sessions` prints the count it examined and the count it could not classify.
- **Missing board / missing tmux** exit 2 with the path that was looked for.

## Testing

New hermetic suite `skills/dispatchInstants/tests/session-lifetime.sh`, following the existing
`fleet-tools-test.sh` pattern: stub `tmux` on PATH, isolated `BOARD_DIR` and `POOL_DIR`, no real
processes. A stub cwd-resolver (`WSPOOL_CWD_PIDS`) makes the cwd coupling testable hermetically.

Written RED before each implementation:

1. close refuses an unfinished worker
2. close closes a harvested worker: stamps `closed_at`, kills the session
3. close releases the wspool lease when its meta names this todo, and leaves another todo's lease alone
4. close refuses when the pane holds unsubmitted input, naming the text
5. `--force` overrides the unsubmitted-input refusal
6. close refuses a mid-turn pane
7. close captures the pane to evidence before killing
8. close is idempotent on an already-dead session (exit 0, still stamps)
9. close refuses an ambiguous id prefix, resolves a unique one
10. `sessions` classifies ACTIVE / FINISHED / UNCLAIMED correctly
11. `sessions --reap` reaps only FINISHED past TTL; never UNCLAIMED
12. `sessions` exits 1 when something is reapable and 0 after reaping (escalates *and* clears)
13. `wspool release` refuses under a live cwd; `--force` overrides
14. `wspool claim` skips a slot occupied by a live cwd
15. health flags unsubmitted input on an IDLE pane
16. health does **not** flag an empty input box (the false-alarm direction, pinned)
17. harvest `--record` closes the session
18. harvest `--keep-session <reason>` skips teardown and records the reason

`superpowers-selftest` must go 10/10 → 11/11 GREEN before anything is pushed.
`TOOLING-CHANGES.md` records the two exit-code-affecting changes: ③'s new non-zero exit and ④'s new
refusal.
