# RCA: a stalled worker stays stalled until the operator nudges it (G-1 + G-2)
Updated: 2026-08-03 by session e7426760-8dc2-481c-a368-b80f1bce54eb | Evidence: `../../evidence/` ([INDEX](../../evidence/INDEX.md))

Scope: the `G-1` + `G-2` loop, taken as one piece of work by operator decision 2026-08-03. `G-7` is parked.

## Terms used below

**"Actuator"** is this document's word for **the missing component**, not anything in the codebase. The
framing is a control loop, and naming the parts is what makes the gap precise:

| part | what it does | exists today? |
|---|---|---|
| sensor | reads the world — pane text, process list, instant mtimes | yes — `session.default_probes` |
| judgement | decides *"this worker is stalled and needs a person"* | yes — `reconcile` → `IDLE`, `needs_a_human` |
| **actuator** | **acts on the judgement — changes the world** | **NO. That absence is `G-2`.** |
| display | shows the judgement to a human | yes — `board`'s "N needs you" banner |

The loop today runs sensor → judgement → display → **the operator**. *The operator is the actuator.* That is
what *"the entire system stuck forever until I send messages waking folks up"* describes: not a broken loop,
a loop whose final link is a person remembering to look.

So "could the actuator send the nudge itself?" (Why 4) means: *when the missing component is built, can it
just call `tmux send-keys`?* No — see Why 5 through Why 7. Not because sending is hard, but because a naive
send fails **silently**, which is `G-1`.

## Symptom

The operator, verbatim (`../../evidence/issues/G-2-stall-loop-actuation.md` §1):

> *"in coordinator instant, I spotted that it could miss dispatched instants becoming idle … coordinator is
> also not aware so **the entire system stuck forever until I send messages waking folks up**. I asked
> coordinator to do mitigation by explicitly polling manually and add watchdog nudging child from time to
> time, which is not ideal."*

This symptom is a **capability absence**, so it cannot be anchored to a crash log. It is anchored instead to
three reproduced facts, each with its own artifact — the detector's output, the consumer census, and a
mutation experiment.

Reproduce all three: `bash bin/repro-g2-stall-loop.sh` (~6 min, costs nothing, no tmux/claude/network).
Captured run: `../../evidence/2026-08-03-repro-g2.txt`.

## Impact / scope

- Recurring, and paid in the scarcest resource here: the operator's attention. The mitigation (manual
  polling + asking the coordinator to nudge) exists and works, which is why this is a **tax, not a fire**.
- The cost **grows with fleet size** — one stalled worker is a nudge; five concurrent efforts stalling
  independently is a polling job. Every other open gap's cost is flat.
- Live since `0.2.3` (2026-08-02) for the actuation half. The *detection* half was silent from whenever
  `IDLE` was introduced until `FI-14` fixed it in `0.2.3`.

## Causal chain

```
SYMPTOM  a worker stops; nothing wakes it; the operator does
  [FACT: evidence/issues/G-2-stall-loop-actuation.md §1 — the quote above]

└ Why 1: does `fleet` even KNOW the worker stalled?  YES — the detector works.
    [FACT: evidence/2026-08-03-repro-g2.txt PART 1 — a worker untouched 2700s with a non-working pane:
     "stalled-07300001  state=IDLE  needs_a_human=True  note='live, but nothing has changed in the
     instant for more than 1800s and the pane is not working'"; the control worker beside it, same
     fixture, busy pane, is RUNNING / needs_a_human=False]

  └ Why 2: so who ACTS on that judgement?  Nobody. Every consumer is a VIEW.
      [FACT: evidence/repro-g2/part2-consumers.txt — the only consumers of `needs_a_human` /
       `ACTIONABLE_STATES` outside the producing module are `render.py:133,170` (the "N needs you"
       banner) and `cli.py:1930` (a reconcile row). Both display. Neither acts.]

    └ Why 3: the box HAS a daemon with a poll loop, a pane and a send. Why doesn't it?
        Because it is a supervisor of monitors, and its "reconcile" is a different verb than fleet's.
        [FACT: evidence/repro-g1/watchdog-reconcile.sh.txt — `cmd_reconcile()` = `rebuild_exclude` +
         `reap_monitors` + `run_car_all_servers`; i.e. "ensure a claude-auto-retry monitor is attached
         to every in-scope pane". It never calls `fleet reconcile` and has no notion of IDLE.]
        [NOTE: the word "reconcile" names two different things on this box. G-2's brief §3 says the
         watchdog "never calls reconcile", which reads as if the word were absent; it is present 14
         times and means monitor lifecycle. Corrected in the brief.]

      └ Why 4: could the actuator simply send the nudge itself?  Not safely — no `fleet` verb can send.
          [FACT: evidence/2026-08-03-brief-reverification.txt row G-1 — no `send-keys` invocation
           exists anywhere in `fleet/src`; the package gates a send it cannot perform. The two textual
           hits are prose.]

        └ Why 5: and delivery is not a one-liner, because a naive send silently fails.
            [FACT: evidence/issues/G-1-pane-delivery-verb.md §2 — measured on a real claude pane
             2026-08-02 (claude 2.1.220), varying ONLY the gap between text and Enter:
             gap=0 → Enter DROPPED (pane-guard 0 after type: the text had not landed);
             gap=0.05s/0.5s/3s → submitted. So bare Enter submits fine; what fails is a RACE.
             CARRIED-OVER artifact: measured in the parent instant, not regenerated here — see
             Open Assumptions.]

          └ Why 6: the correct contract is a CONDITION, and it is implemented — in a test script.
              [FACT: evidence/repro-g1/live-pane-submit.sh.txt — `cmd_submit`: type, then poll
               `pane-guard` up to 50 × 0.2s for code 10, and REFUSE to press Enter if it never
               arrives, "because an Enter into an empty box submits nothing and looks like it worked".]

            └ Why 7: meanwhile the ONE production send path uses a fixed delay, not the condition.
                [FACT: evidence/repro-g1/car-tmux-send.js.txt — `claude-auto-retry/src/tmux.js:87-92`:
                 `sendKeys()` = send text `-l`, `await setTimeout(150)`, send Enter. And line 37:
                 `SUBMIT_DELAY_MS = 150` — "150ms is empirically reliable across Linux + macOS".]
                [FACT: same artifact, lines 99-140 — a local patch DOES shell out to `fleet pane-guard`,
                 but as a PRE-SEND gate: it checks for code 10 BEFORE typing, to avoid concatenating
                 onto an operator's half-typed sentence. It does not poll AFTER typing.]

ROOT CAUSE (two, and they are one loop):
  R1 (G-2)  `fleet` produces a correct, actionable judgement about a stalled worker and NO component
            consumes it as anything but text on a screen. The loop ends at a human's eyes.
  R2 (G-1)  The one primitive an actuator would need — deliver text to a pane and CONFIRM it landed —
            has no owner in the package. It exists correctly once, in a test harness, and approximately
            once, on a 150ms timer, in a vendored node package.
```

## The finding that was not in any brief

**`FI-14`'s detection half — the thing `G-2` is built on top of — is not protected by any test.**

Mutation experiment, `../../evidence/2026-08-03-repro-g2.txt` PART 3, raw rows in
`../../evidence/repro-g2/part3-mutations.tsv`. Baseline GREEN first (1183 tests, 70s), each mutant a
`cp -r` with its anchor asserted present-and-unique, each death checked for its REASON:

| mutation | result | what it means |
|---|---|---|
| **M-1** disable the IDLE detector (`_live_state`'s threshold branch never fires) | **SURVIVED** — suite fully GREEN | no test drives `reconcile` to *produce* IDLE |
| **M-2** CONTROL: revert `FI-14` (drop `IDLE` from `ACTIONABLE_STATES`) | **KILLED**, naming `test_a_stalled_worker_is_counted_as_needing_a_human` | the harness *can* kill; the tuple *is* asserted |
| **M-3** activity probe always reports "fresh" (`_idle_for` → 0.0) | **SURVIVED** — suite fully GREEN | the threshold input is unguarded too |

The control is what makes M-1 a measurement rather than a complaint about the runner.

**Why it slipped:** `FI-14`'s flagship test hand-builds a subject that is *already* labeled `IDLE` and
asserts the banner counts it — `fleet/tests/test_render.py:176`, `worker("stalled-07310400", "IDLE",
note="live, but nothing has changed in the instant for more than 1800s")`. It never invokes `reconcile`. It
even retypes the note by hand, truncated (the real note ends `"…and the pane is not working"`). The test
asserts the *view* of an IDLE subject; nothing asserts that one is ever produced.

This is `P-C` — "green for the wrong reason", eight recorded sightings, one shipped (`SI-38`) — sitting
directly under the gap we were about to build on. It is also the first entry in `G-5`'s frame that has been
demonstrated rather than suspected, found without looking for it.

## Design consequences (facts, so they belong here, not in the brainstorm)

1. **`G-1` must be a VERB, not a library call.** `G-1` §5.1 left this open. The only production consumer is
   a **node** package, which can reach python only through a subprocess — and it already does exactly that
   for `pane-guard` (`car-tmux-send.js.txt:118-132`, `FLEET_BIN … execFileAsync`). The precedent, the
   pattern and the sole caller all say verb.
2. **Code `10` means opposite things on either side of the type, and a naive implementation will invert
   them.** *Before* typing, `10` = "someone else's text is in the box" → **stop**. *After* typing, `10` =
   "my text landed" → **go**. The production patch uses the first sense; the correct submit contract needs
   the second. Any verb that reuses the patch's logic unexamined gets this backwards.
3. **The nudge target must not be a pane a human is attached to** (`G-4`), and `#{session_attached}` is
   collected nowhere (`brief-reverification` row `G-4`). Either `G-4` lands first or `G-2` carries an
   interim check recorded as temporary.
4. **`claude-auto-retry`'s 150ms is above the one measured failure threshold** (which was between 0 and
   50ms) but is a timing assumption on a box that runs 12 concurrent IT runners. Whether it actually fails
   under load is UNMEASURED — see Open Assumptions. It is not this gap's job to fix, but the verb should be
   usable by it.
5. **Fix the detector's test before adding the actuator.** An actuator built on an unguarded detector means
   a silent regression in `_live_state` presents as "the nudges stopped working", with the detector the last
   place anyone would look — and `M-1`/`M-3` prove nothing would flag it.

## Open assumptions

| id | assumption | why plausible | how to close | status |
|---|---|---|---|---|
| `RA-1` | the type→Enter race measured 2026-08-02 still behaves that way | one measurement, one claude version (2.1.220), one session; carried over from the parent instant rather than regenerated | done — `bin/probe-ra1-send-race.sh`, 12 clean trials on a real pane | **CONFIRMED + REFINED 2026-08-03** — see below |
| `RA-2` | `claude-auto-retry`'s 150ms delay does fail under load on this box | the measured threshold was <50ms so 150ms has margin; but the failure is silent and the box runs 12 concurrent runners | instrument the monitor to log `pane-guard` after its Enter, or replay the gap sweep under load | OPEN — do NOT assert this as a live defect until measured |
| `RA-3` | no consumer outside the four greps reads the judgement | the census covers `fleet/src`, `scripts`, `skills`, `bin` by content, not just by name | widen to the operations tree if an external nudger is ever suspected | OPEN, low risk |

### `RA-1` closed 2026-08-03 — and it strengthens Why 5/6 rather than merely confirming them

Operator authorised the allowance. 12 clean trials, same claude (2.1.220), each from an ASSERTED
idle-and-empty pane. Artifacts: `../../evidence/2026-08-03-ra1-send-race.txt` + `.tsv`.

- **gap=0 drops the Enter 1 time in 5** — intermittent, not deterministic. The 2026-08-02 measurement showed
  one failure and read as a rule; it is a rate. A race, confirmed as a race.
- **`pane-guard` after the type predicted the outcome in 12 of 12 trials.** The one drop is the one trial
  reading `0`; all eleven reading `10` submitted. The Why-6 contract is therefore not just *safer* than a
  delay — it is **sufficient**: the failure mode *is* "text not yet in the box", and `10` answers exactly
  that. Upgrade Why 6 from "the correct contract" to "a contract measured to be decisive".
- **The original's conclusion survived its own flawed method.** Its trials 2-4 ran with the dropped text
  still in the box, so their `guard_after_type=10` was uninformative and their Enter submitted a
  concatenation. Re-measured cleanly, "50ms and above submits" holds anyway (0/6). Both facts belong in the
  record: the finding was right, the method was not, and only re-running it showed which.
- **150ms — `claude-auto-retry`'s exact value — scored 0/2 at loadavg 0.32.** Not a rate. `RA-2` stays OPEN.

`RA-2` matters for honesty: it is tempting to write "production sends blind and that is why workers stall."
The captured facts do not support that. The patch gates before typing, and 150ms exceeded the measured
threshold. What is established is that the production path relies on a **delay rather than a condition**,
which is a weaker contract than the one the project already knows how to write — not that it is currently
dropping nudges.

## Fix direction (Phase 4 — not started; brainstorm pending)

Root-cause fixes, in the order the chain implies:

1. **Close the detector's test gap** (kills M-1 and M-3) — a reconcile-level case that a stalled worker is
   *produced* as `IDLE`, plus one that a busy one is not. `bin/repro-g2-stall-loop.sh` PART 1 is already
   the test; it needs to become a case in `fleet/tests/`.
2. **`G-1`: a verb that owns delivery** — type, poll `pane-guard` for `10`, Enter; refuse rather than press
   blind; refuse a `dt-` target by explicit check; route tmux through `session.default_probes` so §M9's
   spawn-seam count stays 3.
3. **`G-2`: something calls it** on the subjects `needs_a_human` already names, excluding human-attached
   panes, with delivery CONFIRMED rather than assumed and a back-off so a legitimately-thinking worker is
   not nudged every interval.

**Symptom fixes rejected:** (a) *make the banner louder* — `G-2` §5.3; this is `FI-14`'s own mistake one
level up, making a signal more visible to somebody who is not watching. (b) *have the coordinator poll on a
schedule* — that is today's mitigation, and the operator's report names it as the thing to remove.

## Reproduce

```bash
bash bin/reverify-briefs.sh          # premises still hold (exit 1 expected: A-2 REFUTED, recorded)
bash bin/repro-g2-stall-loop.sh      # ~6 min: detector works · nobody consumes · detector unguarded
```
