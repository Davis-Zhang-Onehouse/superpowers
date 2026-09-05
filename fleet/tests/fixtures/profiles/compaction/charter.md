# Compaction charter — {{TITLE}}

Read HANDOFF.md before anything else. Fold the instant stack; write COMPACTED.md in the last phase.

## Phase declarations
When CI is dispatched and you are waiting on it, run `fleet declare --instant "$INSTANT" --phase awaiting-ci`. The phase is structured
state; it is never a line of prose in this file.
