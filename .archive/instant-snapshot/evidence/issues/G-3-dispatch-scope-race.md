# G-3 — `dispatch` renders the charter and launches in one call, so the worker races its own scope

**Origin:** `QI-11` here / `FI-1` in the quanton v2stackcoordinator register.
**State:** OPEN. Deferred 2026-08-03 by operator decision `D-4` ("document it for now").

---

## 1. The observable (reporter's, verbatim)

> `fleet dispatch` renders the worker's `CHARTER.md` from the profile template and **starts the `claude`
> session in the same call**. The rendered charter's scope section is a comment addressed to *me*.

Re-check it with (`A-1` — do this before starting):

```bash
sed -n '/^## Scope/,/^## Positioning/p' \
    /home/ubuntu/davis_root/superpowers/skills/using-fleet/profiles/worker/charter.md
grep -n "sessions.start\|render" /home/ubuntu/davis_root/superpowers/fleet/src/fleet/cli.py \
    | sed -n '/_do_dispatch/,+20p'
```

Measured 2026-08-03 at `0.3.1`, the template it renders
(`skills/using-fleet/profiles/worker/charter.md`):

```markdown
## Scope

<!-- The coordinator replaces this per milestone. This charter is authoritative for scope; the seed is
     generic to the profile, so where they differ this file wins. -->

## Acceptance criteria

<!-- One per line, each naming the proof that would satisfy it. -->
```

So at the instant the worker starts reading, its charter's scope section is an instruction addressed to
the coordinator, and its acceptance criteria are empty. The coordinator is racing to fill them in before
the worker acts on what it found.

Note the charter's own claim — *"This charter is authoritative for scope"* — which is true and is exactly
what makes the empty state dangerous: the authoritative document is empty at boot.

## 2. Why it matters
A worker that boots with no scope does one of two things, and both cost a turn: it asks (best case, and
`park` exists for this), or it infers from the seed and the milestone title and starts on the wrong
thing. The reporter's context was a split proposal where inferring wrong would have meant splitting the
wrong branch.

## 3. Why it was deferred
It is a design change to the CORE dispatch flow, not a repair. Splitting render from launch means a
two-phase dispatch, which changes:
- the verb's contract (every dispatch on the box uses the single-call form),
- what a half-completed dispatch looks like to `reconcile`,
- the profile templates, which currently assume they are rendered once.

Nothing about it can be settled by reproduction, which is the method the rest of this line of work relies
on. The operator chose to document it.

## 4. What a fix has to decide
1. **Two verbs, or one verb with `--no-launch` plus a follow-up?** A half-dispatched instant is a new
   state and `reconcile` needs an answer for it. **`PENDING_LAUNCH` already exists** — `reconcile.py`
   returns it for *"dispatched, with no launch recorded and no live session"* — and may be exactly the
   state a two-phase dispatch wants, which would make this much cheaper than it looks.
2. **Where does scope come from?** Three candidates:
   - a `--scope` flag (simplest, but a paragraph on a command line);
   - a file the coordinator writes before launching (matches how charters already work);
   - **the milestone's own title and acceptance criteria** — most attractive, because the roadmap already
     holds exactly this and it would remove the duplication entirely. Also the biggest change.
3. **Backwards compatibility.** Every existing dispatch is single-call. Does the old form stay, warn, or
   go?
4. **What does the worker do if scope is still empty at boot?** Today: nothing stops it. A refusal at the
   worker's end (`brief` reports it, or the charter render refuses) may be the cheaper half of the fix
   and could be done independently of the two-phase split.

## 5. Interaction with other gaps
- `G-6`: the profiles are already being touched for documentation reasons; if a scope mechanism changes
  the templates, sequence them.
- The `awaiting-ci` clause was just added to both worker-facing profiles (`FI-13`, released `0.3.1`), so
  the templates are freshly edited — check git log before assuming their content.

## 6. How to know it is closed
- A dispatched worker cannot begin with an unfilled scope section, either because the scope is delivered
  before launch or because something refuses.
- `reconcile` has a defined, tested answer for a half-dispatched instant.
- The existing single-call form is either preserved or its removal is deliberate and documented.

## 7. Files
- `fleet/src/fleet/cli.py` — `_do_dispatch`
- `fleet/src/fleet/profiles.py` — render, `WORKER_FACING`, `ARTIFACTS`
- `skills/using-fleet/profiles/worker/charter.md` — the template with the comment
- `fleet/src/fleet/reconcile.py` — `PENDING_LAUNCH`, the state a two-phase dispatch would use
