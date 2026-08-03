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
fleet declare phase awaiting-ci --instant {{INSTANT}} --watcher <pid>
```

The phase is **structured state**, and it is what the coordinator's admission rules read. A line of
AWAITING-CI prose in `HANDOFF.md` is read by nothing: a worker that is blocked on CI but has not declared
it is indistinguishable, to every consumer, from a worker that has stalled — and the coordinator will
come and probe you to find out which. Declare it when you start waiting, and carry on when CI returns.

The `--watcher` pid is whatever will wake you when the wait ends — your `gh run watch`, your poll loop. It
is required, because this phase outranks both the busy check and the idle threshold: declared with nothing
watching, you become a wait that never ends and that no report shows, while also freeing the coordinator's
WIP cap. An unwatched declaration is disregarded and you will be reported IDLE.
