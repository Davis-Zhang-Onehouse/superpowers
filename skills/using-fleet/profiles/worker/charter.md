# {{TITLE}}

- **Instant:** {{INSTANT}}
- **Slot:** {{SLOT}}   **Todo id:** {{TODO_ID}}   **Base:** {{BASE}}
- **Milestone:** {{MILESTONE}}   **Coordinator:** {{COORDINATOR}}
- **Lineage base ({{LINEAGE_MODE}}):** {{LINEAGE_BASE}}

## Scope

<!-- The coordinator replaces this per milestone. This charter is authoritative for scope; the seed is
     generic to the profile, so where they differ this file wins. -->

## Acceptance criteria

<!-- One per line, each naming the proof that would satisfy it. -->

## Positioning

{{CHECKOUT}}

## When you are waiting on CI

The moment your work is pushed and you are waiting on a CI run, declare it:

```bash
fleet declare --instant {{INSTANT}} --phase awaiting-ci
```

The phase is **structured state**, and it is what the coordinator's admission rules read. A line of
AWAITING-CI prose in `HANDOFF.md` is read by nothing: a worker that is blocked on CI but has not declared
it is indistinguishable, to every consumer, from a worker that has stalled — and the coordinator will
come and probe you to find out which. Declare it when you start waiting, and carry on when CI returns.
