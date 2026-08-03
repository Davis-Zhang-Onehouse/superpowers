# Design — closing the stall loop (`G-1` + `G-2` + `G-10` + `G-11`)
Status: PROPOSED, awaiting operator approval · Written 2026-08-03 · Against `11f2f58`

Evidence this rests on: `../investigations/g1-g2-stall-loop/analysis.md` (RCA),
`../investigations/g1-g2-stall-loop/state-vocabulary.md` (exact state definitions),
`../evidence/INDEX.md` (every claim → artifact). Decisions: `D-7` … `D-11`.

---

## 0. The four questions, answered up front

The operator asked for these to be unambiguous, so they lead.

### WHO DETECTS that someone needs a nudge?
**`fleet nudge` detects.** It calls `reconcile()` — the same join `board` and `status` use — and applies the
nudge predicate to the result. It does **not** re-derive state from the folder, the record or the pane; a
second derivation of the same judgement is the failure this codebase keeps re-learning.

The watchdog does **not** detect. It supplies only the heartbeat (`D-7`): one call per `$INTERVAL`. Every
judgement stays inside the package, where it is under test — which is the half `G-10` proves matters.

### UNDER WHAT CONDITION is a subject nudged?
All six must hold. Any one failing means no send.

| # | condition | why |
|---|---|---|
| 1 | `kind == KIND_WORKER` (the JOIN's row kind — a *recorded* instant, worker or coordinator alike) | never an `unknown-session` or a `stale-lease` — *"some of those sessions are people's"*. Note this is `reconcile.KINDS`, NOT the profile kind; see `D-11` |
| 2 | `state == IDLE` | live · input box empty · pane not working · no *watched* `awaiting-ci` · >`idle_after_s` since anything in the instant changed |
| 3 | `not subject.evidence["parked"]` | a parked child needs an ANSWER, not a keystroke (`D-8`). The park is appended to the note and leaves the state `IDLE`, so a state-only filter would hit it — measured |
| 4 | the tmux session has **no human attached** | `#{session_attached} == 0`. A nudge must never land in a pane you are typing in |
| 5 | no nudge already recorded **for this episode** | one nudge per stall episode (`§4`) |
| 6 | `pane-send`'s own pre-gate passes at send time | `pane-guard == 0`. Re-checked at the moment of sending, not at reconcile time — the gap between them is where the box can fill |

**Explicitly NOT nudged, and why — this list is the design:**

| state | why no nudge | what it needs instead |
|---|---|---|
| `BLOCKED` | the box ALREADY holds text. Typing would concatenate onto it; a bare Enter would submit somebody's half-written sentence | a human to look |
| `PARKED` | the child asked a blocking question | the coordinator to answer — now visible, per `G-11` |
| `AWAITING-CI` **with a live watcher** | legitimately waiting on CI | nothing |
| `AWAITING-CI` **without a live watcher** | *this state no longer exists* (`D-10`) — it degrades to `RUNNING`/`IDLE`, so it becomes nudgeable if idle | exactly this fix |
| `COMPLETE` + `holds_slot` | needs a `harvest`, not a keystroke | `harvest --id` |
| `DEAD` · `UNREACHABLE` · `UNKNOWN-SESSION` · `STALE-LEASE` | not a keystroke problem; a banner nobody can answer trains people to ignore banners (`W2-14`) | a reap, or a socket fix |

### WHO is nudged?
The **stalled instant's own claude pane** — the tmux session named in its dispatch record (`rec.tmux`), on the
tmux server named by `FLEET_TMUX_SOCKET`.

**Workers AND coordinators** (`D-11`). A stalled coordinator gates every worker under it — it is the case the
original report actually described (*"coordinator is also not aware so the entire system stuck forever"*), so
it is the higher-consequence target, not an exception. The predicate is identical; only the TEXT differs, keyed
on the declared profile kind (§0 "what is sent"). Coordinators are reported first, since they gate others.

⚠️ **Only DISPATCHED instants are nudgeable, and this is a real limitation, not an oversight.** Nudging needs a
dispatch record. A **top-level** coordinator has none — `_do_init`'s own comment says so: *"at `init` time
there is no record"*. Such a session is either invisible to `reconcile` or classified `unknown-session`, which
the package reports and **never touches** (*"some of those sessions are people's"*). So an operator's
hand-started coordinator will NOT be nudged. Dispatched coordinators (the `v2stackcoordinator` shape) are
covered. If the top-level case ever needs covering, that is a records question — not something to solve by
loosening what the nudge is allowed to touch.

⚠️ **A dispatched worker IS a `dt-*` session** (`cli.py:812`: `tmux = f"dt-{name.name}"`), living on the
`fleet` socket. The standing rule is *"never create, kill or write a `dt-` session **on the default
server**"*. So the refusal is `dt-*` **AND default server**, not `dt-*` alone.
`live-pane.sh` refuses every `dt-` name unconditionally, which is correct for a test probe and would be
**catastrophic** copied into the product verb — it could then never nudge a single real worker. Called out
because the reference implementation is otherwise the model to copy.

### WHAT is actually sent to the target claude session?
One line of text, typed literally, then submitted — via `fleet pane-send`, so delivery is CONFIRMED rather
than assumed. **Two texts, chosen by the target's declared profile kind** (`D-11`).

**Worker / compaction:**
```
fleet: you look stalled — nothing has changed in your instant for over {idle}s and your pane is idle.
Use the superpowers:maintain-workspace skill to bring this instant's workspace up to date (HANDOFF.md
especially), then continue the next action. If you are BLOCKED on a decision, do not guess: run
`fleet park --instant <INSTANT> --question '<your question>'` so it reaches your coordinator.
```

**Coordinator:**
```
fleet: you look stalled — nothing has changed in your instant for over {idle}s and your pane is idle.
Use the superpowers:maintain-workspace skill to bring this instant's workspace up to date (HANDOFF.md
especially), then continue the next action.
Your next action is probably your workers: run `fleet board` and act on EVERY subject that needs you. A
PARKED child is waiting on your ANSWER, not on a nudge — answer its question, then `fleet unpark --instant
<child>`. If you are blocked on something only the operator can decide, park it yourself.
```

`--text` overrides both. The kind comes from `Profile.load(rec.profile).kind`, surfaced as
`evidence["profile_kind"]`; **never inferred** from the folder name, title or charter prose — `Profile.load`
raises rather than defaults, because a guessed kind once made five shipped profiles silently fall back to
`worker` (`OBS-5`). An unreadable kind uses the worker text and the report row says so.

Four deliberate properties:

1. **It names the observation, not a command.** "You look stalled, and here is the evidence" — an instant that
   was legitimately thinking can disregard it.
2. **It asks for the workspace to be reconciled first, via `maintain-workspace`.** This is what makes the
   nudge productive rather than merely noisy: the skill's own discipline is *"end every session by updating
   `HANDOFF.md`"*, so a stalled instant that runs it re-reads its own state, writes down where it actually got
   to, and recovers its next action from the document instead of from a memory it no longer has. A stall is
   precisely the moment the workspace is stale, and precisely the moment the instant needs it not to be.
3. **It points at the authoritative documents** rather than inviting improvisation. A nudge that just says
   "continue" invites the guessing failure `G-3` is about.
4. **It offers the escape hatch, and this is the important one.** A stalled child that is actually blocked is
   told how to *declare* that. So the nudge converts a silent stall into either progress or a `PARKED`
   question — and after `G-11` a `PARKED` question is visible in "N needs you". The coordinator's text closes
   the other half of that loop: it sends the coordinator to the parked population to ANSWER, which is the
   only thing that actually unblocks a parked child. Between them, the nudge teaches the protocol that makes
   the next stall unnecessary.

---

## 1. State-model changes

Two, both in `reconcile.py`, and both are semantic — so each ships with its own measurement.

### 1a. `PARKED` becomes actionable (`G-11`, `D-9`)
```python
ACTIONABLE_STATES = (BLOCKED, IDLE, PARKED)
```
A child's blocking question counts in "N needs you" the moment it is asked, instead of surfacing only after a
30-minute timeout that relabels it `IDLE`.

No circularity: `_live_state`'s park branch tests the state derived *before* the park is applied, and `PARKED`
is only ever assigned in that block's `else`. Adding it to the tuple cannot change which branch is taken.

**⚠️ GATE — this is the THIRD change to this tuple** (`FI-14` widened it 2026-08-02; `G-4` would change it
again). The standing constraint is not negotiable: **measure the attention count on a real board immediately
before and immediately after**, and record both. Without that, any regression in the counter is
unattributable — the failure this whole line of work keeps re-learning.

### 1b. `awaiting-ci` requires a live watcher (`D-10`)
- `Declarations` gains a watcher reference alongside `phase`. A run URL may be recorded beside it as evidence
  for a human, but liveness is checked against the **pid**, locally.
- **Producer:** `fleet declare phase awaiting-ci` refuses without one — the idiom of *"an empty park is not a
  park"* and `propose`'s mandatory evidence.
- **Consumer:** `_live_state` treats an `awaiting-ci` phase whose watcher is not alive as **absent**;
  derivation falls through to `busy`/idle as though nothing were declared.
- Liveness via the existing `_live_pid` shape (`/proc/<pid>`, injectable — no new platform assumption, no new
  subprocess seam).
- **Migration:** declarations already on disk have no watcher and are therefore unwatched. Nothing breaks;
  those states simply stop suppressing detection, which is the intended direction.

---

## 2. `fleet pane-send` — the delivery verb (`G-1`)

`fleet pane-send --pane <session> --text <text> [--timeout-s 10]`

```
1  pre-gate:  pane-guard(session)
      0            → proceed
      10           → REFUSE. Text is already in the box; typing would concatenate. (Someone else's.)
      11           → REFUSE. Mid-turn; the send would queue behind a turn in flight.
      12 | 13 | 14 → REFUSE. Not a claude pane, unknown, or the probe could not look.
2  type the text literally (send-keys -l), never with a trailing Enter
3  poll pane-guard until it returns 10, up to --timeout-s
      → 10 reached      : the text is IN THE BOX. Proceed.
      → timeout         : REFUSE to press Enter. Exit non-zero, distinct code, say so.
4  send bare Enter
5  confirm: pane-guard != 10  → delivered
```

**Code `10` is used in BOTH senses, one keystroke apart, and that is the trap.** Before typing it means
*"someone else's text is in the box — stop"*. After typing it means *"my text landed — go"*. The production
`claude-auto-retry` patch uses only the first sense; `live-pane.sh submit` uses only the second. The verb is
the first implementation that needs both, and inverting them is the likeliest way this goes wrong.

**Why poll instead of sleep — measured, not asserted** (`RA-1`, `../evidence/2026-08-03-ra1-send-race.txt`):
at gap=0 the Enter is dropped **1 time in 5**, and across 12 clean trials `pane-guard` after the type
predicted the outcome **12/12** — every trial reading `10` submitted, the single trial reading `0` dropped. So
the condition does not merely reduce the risk, it removes the failure mode by construction. A fixed delay buys
a probability; this buys a guarantee.

**Refusals, by explicit check rather than convention:**
- `dt-*` **on the default server** → refuse (see §0). On a named socket, `dt-*` is the intended target.
- a session `fleet` holds no record of → refuse. `pane-send` writes to panes; it may only write to ours.

**Seam discipline:** the tmux calls go through `session.default_probes`, so the package keeps its three
subprocess seams. §M9 enumerates spawn seams and delete sites — a *send* is arguably a new class of outward
act, so **verify what the audit actually counts rather than assuming it is unaffected**; if it flags the new
site, argue it in BOTH registries (`II-3`) rather than adding an allowlist entry.

**Then:** reimplement `live-pane.sh submit` on top of the verb, satisfying `G-1`'s closure criterion that two
implementations of one primitive collapse into one.

---

## 3. `fleet nudge` — the actuator (`G-2`)

`fleet nudge [--text <t>] [--dry-run] [--porcelain]`

1. `reconcile(...)` → subjects.
2. Filter by the six conditions in §0.
3. Resolve each survivor's **profile kind** (`Profile.load(rec.profile).kind` → `evidence["profile_kind"]`) and
   pick its text. A profile that will not load is reported, not guessed (`D-11`).
4. For each survivor, call the same code path `pane-send` exposes, and record the outcome.
5. Report one row per candidate — nudged, or skipped with the reason — **coordinators first**, since a stalled
   coordinator gates the workers beneath it. `--dry-run` does everything except step 4, so the decision and
   the chosen text can be inspected without a send.

A profile whose manifest is missing or malformed must NOT make `fleet nudge` fail: `reconcile` is behind every
view and `Profile.load` raises by design. The load is per-subject and its failure degrades that one row.

`NUDGEABLE_STATES = (IDLE,)` lives in `reconcile.py` beside `ACTIONABLE_STATES` so the state vocabulary keeps
one home — but **eligibility is not a membership test**, because conditions 3–6 are not state facts. The verb
must not be written as `state in NUDGEABLE_STATES`, and a test must cover parked-and-idle specifically: that
subject's state *looks* nudgeable, so a regression there is invisible by construction.

---

## 4. Back-off: one nudge per stall episode, with no timers

`D-7` puts the cadence in the watchdog's `$INTERVAL`, so the verb cannot know how often it is called. Back-off
therefore lives in the verb and must not be time-based.

**State:** `$FLEET_HOME/nudges.json`, written through `atomic_write` under `held_for_update` — the existing
registry pattern. Not in the dispatch record, which has a different writer and lifecycle.

**Per subject:** `{nudged_at, activity_mtime_at_nudge, delivered: bool}`.

**Episode rule, reusing the activity notion the detector already uses — no second definition of "progress":**
- `IDLE` and the instant's newest mtime **equals** the recorded one → already nudged this episode → skip.
- `IDLE` and the mtime **has moved** → the worker did something since → new episode → eligible again.

**Escalation.** A nudged-and-still-idle subject keeps state `IDLE` (so it stays in "N needs you") and gets its
note annotated — *"nudged at T; still idle"*, or *"nudge attempted at T and delivery FAILED"* when
`pane-send` refused. No new state, no second tuple change. The signal is not "look at the board", it is
*"fleet already tried the thing that usually works, so this one is genuinely yours."*

**Garbage:** an entry whose subject is no longer in the record set is dropped on write. Defined now because
new persistent state without a removal rule grows forever.

---

## 5. `G-10` — the detector test, with the mutation experiment as its control

`fleet nudge` actuates on `IDLE`, and **no test drives `reconcile` to produce `IDLE`** — disabling the
detector leaves all 1183 tests green (`../evidence/repro-g2/part3-mutations.tsv`). Fixing that is step 1, not
a follow-up: an actuator over an unguarded detector turns a future `_live_state` regression into *"the nudges
stopped working"*, with the detector the last place anyone looks.

- A `test_reconcile` case that a stalled worker is **produced** as `IDLE`, and a busy one is not — driving
  `reconcile`, not hand-building a subject with `state="IDLE"` (which is exactly how `FI-14`'s flagship test
  passes vacuously today).
- **The control already exists:** re-run `bin/repro-g2-stall-loop.sh`. `M-1` and `M-3` must flip
  `SURVIVED → KILLED` while `M-2` stays `KILLED`. That is red→green with a control, using the harness that
  found the gap.
- Same treatment for each new behaviour: a mutation that proves the new test can fail. Including for
  `D-10`'s watcher check and `D-8`'s parked exclusion.

---

## 6. Watchdog integration (`D-7`)

One call in `claude-watchdog.sh`'s existing `$INTERVAL` loop, **non-fatal by requirement** — a nudge bug must
never take auto-resume down:

```sh
run_fleet_nudge || true     # D-7. NOT this script's usual duty; see the comment below.
```

With a comment stating why a supervisor of node monitors also nudges, so a later reader does not tidy it away
as unrelated. It must run once per covered tmux server, the same way `run_car_all_servers` already does —
dispatched workers are not on the default server, and a nudge loop that only looks at one server would be
silently blind to every dispatched instant, which is the exact defect `CLAUDE_WATCHDOG_TMUX_SOCKETS` exists to
prevent.

---

## 7. Out of scope, deliberately

- **`claude-auto-retry`'s 150ms delay stays.** `A-5` is unmeasured (0/2 at loadavg 0.32 proves nothing), it is
  outside this repo, and it belongs to the parent instant's monitoring duty. The verb should be usable by it
  later.
- **`G-4`'s question is untouched.** We *collect* `#{session_attached}` and use it as a nudge filter; we do not
  split `BLOCKED` or change what it means. `G-4` stays deferred and open.
- **Detecting an UNDECLARED question.** A child that asks in its output and stops is indistinguishable from a
  stall — both `IDLE`, same branch, same note. The session transcript
  (`~/.claude/projects/<slug>/<uuid>.jsonl`) could answer it in principle and `fleet` reads nothing under
  `~/.claude`; it would be a new, heuristic dependency. Noted, not built. For those children a nudge is the
  right action anyway — and the nudge text teaches them to park.

## 8. Build order

1. `G-10`'s detector test → re-run the mutation control → `M-1`/`M-3` KILLED.
2. `#{session_attached}` collected in `session.default_probes`.
3. **Measure the attention count on a real board** (the `D-9` gate, "before").
4. `PARKED` into `ACTIONABLE_STATES`; measure again ("after"); record both.
5. `awaiting-ci` watcher: producer refusal + consumer fall-through + skill/template updates.
6. `fleet pane-send`; re-point `live-pane.sh submit` at it; check the §M9 seam audit.
7. `evidence["profile_kind"]` on the worker subject, read from the declared manifest (`D-11`).
8. `fleet nudge` + `nudges.json` + note annotation + the two texts.
9. The watchdog line, per server, non-fatal.
10. Release cut → `release-verify` → triage every FAIL row → promote (`AC-2`).

## 9. Risks

| risk | mitigation |
|---|---|
| `10`'s two senses get inverted in `pane-send` | the RCA and §2 both state it; a test for each sense — refuse-on-pre-gate-10 and proceed-on-post-type-10 |
| a blanket `dt-` refusal is copied from `live-pane.sh` | §0 states the rule; a test that a `dt-` session on a NAMED socket IS a legal target |
| the §M9 audit counts a send as a new outward site | verify before implementing; if flagged, argue in both registries, do not allowlist |
| the tuple changes twice without a measurement | step 3 and 4 of §8 are ordered for exactly this; `G-4` stays deferred |
| `nudges.json` grows forever | removal rule defined in §4 |
| the watchdog only nudges one server | iterate the same socket list `run_car_all_servers` uses |
| the profile kind gets INFERRED when the manifest will not load, silently making a coordinator a worker | `Profile.load` raises by design; the fallback is explicit and REPORTED (`D-11`). A test that an unloadable profile yields the worker text **and** a row saying the kind was unreadable |
| a coordinator's nudge is sent to a worker (or vice versa) | the two texts are selected from the declared manifest; one test per kind asserting which text was chosen |
| `fleet nudge` crashes on one bad profile and nudges nobody | the load is per-subject and its failure degrades that row only; a test with one unloadable profile among several good ones |
