# `IDLE` · `PARKED` · `AWAITING-CI` — exact definitions, and where each fact comes from
Updated: 2026-08-03 | Read from source at `11f2f58` | Asked by the operator while designing `G-1`+`G-2`

All three are produced by one function, `reconcile._live_state` (`fleet/src/fleet/reconcile.py:291-319`).
Reading it in order matters more than reading any one state, because the states are decided by an if/elif
chain and **the order IS the semantics**.

## The chain, verbatim in structure

```python
def _live_state(phase, parked, pane, sessions, instant, idle_after_s):
    waiting = sessions.unsubmitted(pane)      # text in the input box, or None
    busy    = sessions.busy(pane)             # the pane is still offering a way to interrupt

 1  if waiting and not busy:      BLOCKED,     f"the pane is waiting on a human: {waiting!r}"
 2  elif phase == "awaiting-ci":  AWAITING_CI, "declared awaiting-ci; not consuming attention"
 3  elif busy:                    RUNNING
 4  elif _idle_for(instant) > idle_after_s:
                                  IDLE,        "live, but nothing has changed in the instant for more
                                                than {idle_after_s}s and the pane is not working"
 5  else:                         RUNNING

    if parked:
 6      if state in ACTIONABLE_STATES:   note += f"; parked decision stands: {parked}"   # STATE KEPT
 7      elif busy:                       RUNNING, "declared parked and progressing anyway — a parked
                                                   note while still working is just a note"
 8      else:                            PARKED,  f"parked decision: {parked}"
```

Reached only for a subject already established as live (a record with a launch, and either a `claude`
process attributed to its tmux name or a live session). Not-live subjects resolve earlier to `DEAD`,
`UNREACHABLE`, `PENDING-LAUNCH`, `COMPLETE`, etc.

## Exact definitions

### `IDLE` — "live, but nothing has changed and the pane is not working"
**Definition.** ALL of:
- the pane's input box is **empty** — `unsubmitted(pane) is None` (branch 1 not taken), AND
- the pane is **not working** — `busy(pane) is False` (branch 3 not taken), AND
- the declared phase is **not** `awaiting-ci` (branch 2 not taken), AND
- `_idle_for(instant) > idle_after_s`, default **1800s**, where `_idle_for` is
  `now − max(st_mtime)` over: the instant directory itself, each of its **direct** children, and each
  child of `.fleet/` if present (`reconcile.py:433-463`, shallow by design).

**Where the facts come from:** 100% **OBSERVED**, from two independent sources — the tmux pane text and
the filesystem. The child does not participate and cannot suppress it.

### `PARKED` — "the child asked a blocking question and is waiting"
**Definition.** `Declarations(instant).parked()` is non-empty AND the derived state is neither actionable
nor busy (branch 8).
- Written by `fleet park --instant <i> --question "…"` into `<instant>/.fleet/declare.json`, key
  `"parked"`. `Declarations.park()` refuses an empty question — *"an empty park is not a park"*
  (`store.py:174-181`). Cleared by `fleet unpark`.
- **Precedence is the subtle part.** A park never *masks* an actionable state (branch 6): if the pane is
  BLOCKED or the instant is IDLE, the state stays BLOCKED/IDLE and the park is only **appended to the
  note**. So `PARKED` as a *state* appears only while the instant is still fresh — after
  `idle_after_s` the same parked child reports `IDLE`. Measured:
  `../../evidence/2026-08-03-nudge-eligibility.txt`.

**Where the facts come from:** 100% **DECLARED** — a self-report. Nothing observes it. A child that does
not run the verb is not parked, however blocked it is.

### `AWAITING-CI` — "declared waiting on CI; not consuming attention"
**Definition.** `Declarations(instant).phase() == "awaiting-ci"`, AND the input box is empty (branch 1
still wins over it).
- Written by `fleet declare phase awaiting-ci` into the same `declare.json`, key `"phase"`.
- **It outranks both `busy` and the idle threshold** (branch 2 precedes 3 and 4), so a declared CI wait
  never decays into `IDLE` no matter how long it lasts. That is deliberate: a CI wait is a legitimate long
  silence.

**Where the facts come from:** **DECLARED**. Same file, same trust model as `PARKED`.

## The two pane predicates these rest on

Both read a **capture of the pane's visible rows**, anchored to the last non-blank row rather than a raw
line index (`FI-24`), never the scrollback:

| predicate | window | rule |
|---|---|---|
| `unsubmitted(pane)` | last **8** rendered rows (`PROMPT_TAIL_LINES`) | the **last** caret (`❯` or `>`, gutter `│┃|` stripped) in the window is the input box. Its content is the answer — unless it matches a `_PLACEHOLDERS` pattern (`try "`, `ask `, `/ for commands`, `# for memory`, `new task?`), which are the shapes an EMPTY box renders. The *last* caret, not the first, because a submitted prompt stays on screen with the new empty box drawn below it (`N4`). |
| `busy(pane)` | last **15** rendered rows (`BUSY_TAIL_LINES`) | substring match for `"esc to interrupt"` or `"ctrl+c to stop"`. Deliberately **not** `"esc to cancel"` — that is what a MODAL offers while waiting for a human, and the two read alike but mean opposite things (`SI-37`; it caused a never-started session to report RUNNING). |

Liveness itself is **process** evidence, not screen scraping: `pgrep -x claude` joined to tmux pane
ownership (`is_claude_process`, `SI-38`) — because a claude idle for twenty minutes shows none of the UI
chrome and was once classified `12 not-claude` while verifiably alive.

## Answering the question directly: observed vs. declared

| state | source | can `fleet` derive it without the child's cooperation? |
|---|---|---|
| `IDLE` | pane text + file mtimes | **Yes, fully.** |
| `BLOCKED` | pane text (input box non-empty) | **Yes, fully.** |
| `RUNNING` | pane text (`busy` markers) | **Yes, fully.** |
| `PARKED` | `.fleet/declare.json` | **No.** Exists only if the child ran `fleet park`. |
| `AWAITING-CI` | `.fleet/declare.json` | **No.** Exists only if the child ran `fleet declare phase`. |

### The consequence that matters for the nudge design
**A child that asks a question in its output and stops, without calling `fleet park`, is
indistinguishable from a child that simply stalled.** Both are `IDLE`, by the same branch, with the same
note. `unsubmitted` cannot see it: it inspects only the **input box**, never the assistant's output. So the
"child asked, coordinator answers" flow depends entirely on the child having declared — it is a
**cooperative** protocol, not a detected one.

### What is available but NOT collected today
- **The claude session transcript.** `~/.claude/projects/<slug>/<uuid>.jsonl` holds the actual message
  objects, so "the last assistant message is a question" is answerable in principle. **`fleet` reads
  nothing under `~/.claude`** — verified: `grep -rn "\.claude/projects\|jsonl" fleet/src/fleet/*.py`
  returns nothing. Adding it would mean a new, heuristic dependency ("is this a *blocking* question?" is a
  judgement), so it is noted as available, not recommended.
- **`#{session_attached}`** — the `G-4` discriminator. `fleet` collects exactly one tmux format string
  today, `#{pane_pid} #{session_name}` (`session.py:367`). Nothing else.
