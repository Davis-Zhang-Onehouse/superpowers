# {{TITLE}}

- **Instant:** {{INSTANT}}
- **Slot:** {{SLOT}}   **Todo id:** {{TODO_ID}}   **Base:** {{BASE}}

## What is being folded

<!-- The instants being compacted, and the PR chain they become. -->

## Merged acceptance criteria

<!-- The union, each proven ON THE STACK rather than merely listed. -->

## When you are waiting on CI

A compaction restacks PRs, so it waits on CI more than most work does. The moment a push is up and you
are waiting on a run, declare it:

```bash
fleet declare phase awaiting-ci --instant {{INSTANT}} --watcher <pid>
```

The phase is **structured state** and it is what the coordinator's admission rules read. A line of
AWAITING-CI prose in `HANDOFF.md` is read by nothing — an undeclared wait is indistinguishable from a
stall, and a compaction holding every dispatch while it silently waits is the most expensive place for
that confusion to happen.

The `--watcher` pid is whatever will wake you when the wait ends — your `gh run watch`, your poll loop. It
is required, because this phase outranks both the busy check and the idle threshold: declared with nothing
watching, you become a wait that never ends and that no report shows, while also freeing the coordinator's
WIP cap. An unwatched declaration is disregarded and you will be reported IDLE.
