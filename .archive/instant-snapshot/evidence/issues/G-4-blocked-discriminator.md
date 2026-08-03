# G-4 — `BLOCKED` cannot tell a stuck worker from a human who is mid-sentence

**Origin:** `QI-12` here / `FI-9` in the quanton v2stackcoordinator register.
**State:** OPEN. Deferred 2026-08-03 by operator decision `D-4`.

> ⚠️ **Read the CORRECTED text only.** The operator refuted two of the reporter's three original claims
> on 2026-07-31, and the reporter RETRACTED their own proposed remedy. This brief carries the kernel that
> survived and the retraction, because the operator says they nearly implemented the wrong version.

---

## 1. The kernel — this part is real

`BLOCKED` is in `ACTIONABLE_STATES`, so it drives `board`'s **"N needs you"** counter. It **cannot
distinguish**:

- a dispatched worker that hit a permission modal and is stuck, from
- a human attached to that pane, mid-sentence.

For a monitor-facing verb those demand OPPOSITE responses: the first needs intervention, the second needs
to be left alone.

**The discriminator exists and `fleet` does not collect it:** `tmux ls -F '#{session_attached}'`.

## 2. The remedy that must NOT be implemented

The reporter originally proposed:

> *"derive `BLOCKED` only from `park.json` / `declare.json` — asserted state, single-writer."*

and then retracted it in their own register:

> **That would delete a real signal.** A dispatched worker stuck at a permission modal has **no
> `park.json` either** — the modal is *precisely* the case `BLOCKED` exists to catch, and my "fix" would
> have made it invisible. The correct direction is to *add* the attachment discriminator, not to narrow
> the source. Recording the retraction explicitly because the operator says they nearly acted on my
> version as written.

**Do not narrow the source. Add the discriminator.**

## 3. What was WRONG in the original report, so nobody re-derives it
The reporter's own correction table records that their claim *"`board` and `status` contradict each other
about one subject at one instant"* is **false — they cannot.** Both call `render._row_state(subject)`,
which is a lookup and not a derivation, deliberately: *"a second derivation from the folder name, the
record or the lease is precisely how three views came to disagree."* Do not go looking for that
contradiction; it is not there.

## 4. Why it was deferred
It changes what an EXISTING state MEANS, mid-effort, on the state that drives the attention counter.
That is the operator's call, not a repair.

## 5. ⚠️ Sequencing — this is the part that will bite
**`FI-14` added `IDLE` to `ACTIONABLE_STATES` on 2026-08-02** (released `0.2.3`). If `BLOCKED` now splits
into "stuck" and "human attached", the attention count changes TWICE, and the second change lands on a
population the first one just altered.

- Do them in sequence, not together.
- Re-measure the attention count between them, on a real board.
- A regression in the counter after two simultaneous semantic changes is unattributable, which is the
  failure mode this whole line of work keeps hitting.

Current state of the tuple, for the record:
```
ACTIONABLE_STATES = ('BLOCKED', 'IDLE')
needs_a_human(subject) = state in ACTIONABLE_STATES  or  (COMPLETE and holds_slot)
```
The second clause is `FI-12`'s — a terminal instant still holding a workspace.

## 6. Interaction with G-2
`G-2` wants to NUDGE actionable subjects automatically. **A human-attached pane must never be nudged.**
So either `G-4` lands first, or `G-2` carries an interim `#{session_attached}` check of its own — which
would be a second implementation of this discriminator and should be recorded as temporary if taken.

## 7. How to know it is closed
- `fleet` collects `#{session_attached}` and a state distinguishes stuck-worker from human-attached.
- The attention counter's population is re-measured and the change is stated.
- A pane with a human attached is excluded from anything automated (`G-2`).
- The retracted remedy is still recorded, so it is not re-proposed.

## 8. Files
- `fleet/src/fleet/reconcile.py` — `BLOCKED`, `ACTIONABLE_STATES`, `needs_a_human`, `_live_state`
- `fleet/src/fleet/session.py` — `default_probes`, where `#{session_attached}` would be collected
- `fleet/src/fleet/render.py` — `_row_state` (the single lookup), `_needs_a_human`
