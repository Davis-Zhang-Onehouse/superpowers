# Worker charter — {{TITLE}}

## Phase declarations
When CI is dispatched and you are waiting on it, run `fleet declare --instant "$INSTANT" --phase awaiting-ci`. Do not write the phase
into HANDOFF.md: nothing reads prose.
