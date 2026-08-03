# G-2 — fleet DETECTS an idle worker and nothing ACTS on it

**Origin:** `QI-10` (fleetInfraOps parent), raised by the operator 2026-08-03.
**State:** OPEN, never tracked before 2026-08-03. **The operator is currently the mitigation.**
**Depends on:** `G-1` — a clean fix needs a verb that owns pane delivery.

---

## 1. The operator's report, verbatim

> *"in coordinator instant, I spotted that it could miss dispatched instants becoming idle, where the
> child instant is not waiting ci or doing work locally, claiming sth to be done and just stop there.
> coordinator is also not aware so the entire system stuck forever until I send messages waking folks up.
> I asked coordinator to do mitigation by explicitly polling manually and add watchdog nudging child from
> time to time, which is not ideal."*

An earlier report of the same stall, from the coordinator's own register (`FI-14`):

> *"the dispatched instants constantly do something and then just stop until I probe and ask it to
> proceed, otherwise it is not waiting CI or doing local works, it just completely stalled."*

## 2. What is ALREADY fixed — do not re-fix it

| half | finding | state |
|---|---|---|
| the worker stalls and nothing NOTICES | `FI-14` | **FIXED**, released `0.2.3`. `ACTIONABLE_STATES = ('BLOCKED', 'IDLE')` |
| the coordinator polls too rarely, reads idleness charitably | `VI-4` | the coordinator's own process finding; not code |
| a nudge, once sent, may not be DELIVERED | `FI-15` | contract FIXED and documented; the verb is `G-1` |
| **something ACTS on a detected stall** | — | **THIS ISSUE** |

`FI-14`'s detail, because it explains why the detection half was silent for so long: `fleet` already had
`IDLE` as a first-class state on a 30-minute threshold (`reconcile.reconcile(..., idle_after_s=1800)`)
and already rendered the right sentence — *"live, but nothing has changed in the instant for more than
1800s and the pane is not working."* The only consumer of that judgement was
`ACTIONABLE_STATES = (BLOCKED,)`, and `IDLE` was not in it. Verified live after the fix:

```
$ python3 -c "from fleet.reconcile import ACTIONABLE_STATES; print(ACTIONABLE_STATES)"
('BLOCKED', 'IDLE')
```

**The inversion is the tell, and it is worth keeping in mind while designing this:** `BLOCKED` — which
per `G-4` fires when a human is attached and mid-sentence — WAS actionable, while a worker stopped for
half an hour was not. The counter called for attention on somebody already present and stayed silent on
the thing that had stopped.

## 3. The gap, measured

```
$ grep -rl "needs_a_human\|ACTIONABLE_STATES" fleet/src scripts skills
fleet/src/fleet/reconcile.py      # produces the judgement
fleet/src/fleet/render.py         # displays it  ("N needs you")
fleet/src/fleet/cli.py            # displays it  (reconcile rows)
```

**Three files, all inside the package. No consumer outside fleet reads it, and nothing anywhere acts on
it.** So `fleet board` now says a worker needs a human — to whoever runs `fleet board`.

### The existing daemon does NOT cover this
`scripts/claude-watchdog.sh` is the only daemon on the box. It solves a different problem:

> *"the Claude CLI has no built-in auto-resume; a session that hits its usage/token limit halts until
> manual input. claude-auto-retry watches the session's tmux pane (zero token cost while waiting) and,
> once the limit resets, sends-keys a 'continue'."*

It watches for the **usage-limit banner**. It has no notion of `IDLE`, never calls `reconcile`, and would
not nudge a worker that stalled for any other reason. It does own a poll loop, a pane and a send — which
makes it the natural host for the fix, not a competitor to it.

## 4. Why this is NOT a re-open of FI-14
`FI-14` was "the judgement is computed and discarded" — `F-14`'s class — and is genuinely closed: the
signal now reaches a view. This is the next link. **A signal that reaches a VIEW still needs a reader,
and the reader is a human who has to remember to look.** Different defect, different fix. Folding it back
into `FI-14` would let a closed finding carry an open problem.

## 5. Proposals (from `QI-10`, unchanged)
1. **Teach the existing watchdog the actionable set.** Every `$INTERVAL`, run `fleet reconcile
   --porcelain`; for each subject the PACKAGE calls actionable, nudge it through the gated send. Smallest
   change that closes the loop, and it keeps the decision in `fleet` where it is tested rather than in
   the daemon. Needs `G-1`, or the daemon re-implements the send — `DA-2`'s seventh path.
2. **A `fleet nudge` verb**, gated on `pane-guard`, that the watchdog or cron calls. Same as (1) with the
   primitive named. This is `G-1` with a concrete first consumer.
3. **Report only, louder** — surface the actionable count in the cadence banner. Cheapest, and it does
   NOT close the loop.

**Recommend (2) then (1). (3) alone repeats `FI-14`'s mistake one level up:** making a signal more visible
to somebody who is not watching is not the same as acting on it.

## 6. Design questions a fix must answer
1. **What is a nudge?** The literal text matters — a wrong nudge is a turn spent on nothing. The
   watchdog's existing one is *"Continue where you left off."*
2. **How often, and does it back off?** A worker idle for 30 minutes may be legitimately thinking. A
   nudge every interval forever is a new kind of noise, and the pane is a shared resource.
3. **Never a `dt-` session on the default server.** Standing constraint for this whole line of work.
4. **What if the nudge does not land?** `FI-15` says the send can silently fail. The gated send reports
   it; the caller must do something with that report rather than assume delivery.
5. **Who is exempt?** A pane a HUMAN is attached to must not be nudged — which is `G-4`, and is why
   these two interact.

## 6a. REPRODUCED 2026-08-03 at `11f2f58` — and one correction to §3

Full RCA: `../../investigations/g1-g2-stall-loop/analysis.md`. Repro:
`bash bin/repro-g2-stall-loop.sh` (~6 min, costs nothing). Artifact: `../2026-08-03-repro-g2.txt`.

**Confirmed, with artifacts:**
- The **detector works.** A worker untouched for 2700s with a non-working pane is classified `IDLE` with
  `needs_a_human() == True`, and an otherwise-identical busy worker beside it is `RUNNING`. So this gap is
  *not* a broken detector — everything missing is downstream. (PART 1.)
- **Every consumer is a view.** Outside the producing module, the only readers of the judgement are
  `render.py:133,170` (the banner) and `cli.py:1930` (a reconcile row). Both display; neither acts. (PART 2.)

**Correction to §3.** This brief says the watchdog *"has no notion of `IDLE`, never calls `reconcile`"*. The
second half is misleading: `claude-watchdog.sh` contains the word `reconcile` 14 times and has its own
`cmd_reconcile`. **The word names two different things on this box** — fleet's `reconcile` computes a
judgement about subjects; the watchdog's means *"ensure a `claude-auto-retry` monitor is attached to every
in-scope pane"* (`rebuild_exclude` + `reap_monitors` + `run_car_all_servers`). It never calls **fleet's**.
Artifact: `../repro-g1/watchdog-reconcile.sh.txt`.

That matters for proposal (1): the watchdog is a **supervisor of monitors**, not a poller of fleet state, and
the send it would need is not even in it — it is inside the vendored node package the monitors run. Hosting
the actuator there is a bigger change than §5 implies.

**And the finding that was not in any brief: the detection half `FI-14` shipped is protected by NO test.**
Disabling the idle branch entirely leaves the full 1183-test suite GREEN; so does breaking the activity probe
it reads. The control — reverting `FI-14`'s actual one-line fix — IS killed, which is what makes those two
survivals a measurement. Filed as `G-10` in `../../ISSUES.md`. **It is step 1 of this work:** an actuator
built over an unguarded detector turns any future regression in `_live_state` into *"the nudges stopped
working"*, with the detector the last place anyone would look.

## 7. How to know it is closed
- A stalled worker is nudged without the operator doing anything.
- The nudge is gated (`pane-guard`) and its delivery is CONFIRMED, not assumed.
- A human-attached pane is never nudged (needs `G-4`, or an interim `#{session_attached}` check).
- There is a test that a stalled worker produces a nudge and a working one does not.
- The operator stops being the mitigation. That is the actual acceptance test.

## 8. Files
- `fleet/src/fleet/reconcile.py` — `IDLE`, `ACTIONABLE_STATES`, `needs_a_human`
- `fleet/src/fleet/render.py` — `_needs_a_human`, the "N needs you" banner
- `scripts/claude-watchdog.sh` — the existing poll/pane/send daemon
- `fleet/it/bin/live-pane.sh` — `cmd_submit`, the gated send that works
