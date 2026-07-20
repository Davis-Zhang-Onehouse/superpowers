# [<EPIC-TAG> <ref>] <one-line task, imperative or noun phrase>

**Epic:** <effort> · **Ref:** <catalog id / OI-n / gap #n> · **Type:** <gap|infra|hygiene|residual|scope|reconciliation> · **Status:** <MARKER> · **Priority:** <High|Medium|Low>

<!--
  Status MARKER must be a clean legend token so the index can bucket it — never prose like
  "mostly resolved". Use one of:
    ✅ DONE            🔵 running          ⏳ PENDING / blocked
    🅿 parked          🔲 / ⬜ OPEN         ⛔ superseded
  A short "— <qualifier>" after the marker is fine (e.g. "🔲 OPEN — hard blocker"); it shows in the board.
  `**Status:**` may live inline on the metadata line above OR on its own line — both parse.
-->

## Description

### Functional requirement (the GOLD)
What correct behavior is — the spec / reference the task is measured against. No project churn.

### Current gap
What is wrong *right now* (at the latest known state), one paragraph. Not the history of how it got here.

### Approach
The chosen disposition (port / rework / sanction / scope-out / accept) in a sentence or two.

## Status / verifications
Only the CURRENT proof — the latest state, not the journey:
- **PR / branch:** <link + tip sha>
- **CI:** <run> → <the one number that matters, e.g. red→green=N, green→red=0>
- **Review gate:** <READY / READY-WITH-FIXES>
- **Evidence:** <pointer into the owning instant's evidence/>
- Any residual this task spins off → link the residual/scope ticket.
