# ASSUMPTIONS   (the unverified-beliefs register; append, don't rewrite)
| ID | Assumption (believed, not yet proven) | Status | Evidence / next check |
|----|---------------------------------------|--------|-----------------------|
| AS-1 | The prior session's validation (1,849 hermetic green; real Claude/Codex lifecycles) holds for `71c69a2` as received | VERIFIED 09-14 | 1,849 tests OK in 117 s → evidence/hermetic-71c69a2.log |
| AS-2 | The release gate will run the suites (not EXEMPT) since `fleet/`, `scripts/`, `hooks/`, `skills/using-fleet/` all changed | OPEN | `release-verify --dry-run` before the gate |
| AS-3 | No live fleet work on the box will contaminate the gate | OPEN | preflight 19:36 UTC: one live dt- session on another root's socket (fleet-davis2) — an uncontrollable residual, reported not refused; re-check before the cut |
| AS-4 | The plan's file table lists `guards.py`/`render.py` as modified; they were never touched on the branch | VERIFIED 09-14 | core reviewer confirmed `git diff --stat` shows neither; plan inaccuracy only |
