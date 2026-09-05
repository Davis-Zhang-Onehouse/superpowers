# Worker charter — {{TITLE}}

Pinned commit: a1b2c3d4e5f6a7 — a static sha in a shared profile goes stale silently.
Baseline run id: 29618938212 — an all-digit CI run id, which the brief contract requires be pinned.

## Phase declarations
When CI is dispatched and you are waiting on it, run `fleet declare --instant "$INSTANT" --phase awaiting-ci`.
