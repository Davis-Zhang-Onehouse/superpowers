# ASSUMPTIONS   (the unverified-beliefs register; append, don't rewrite)
Updated: 2026-09-14 by session 53ee129f-4b4a-4005-bdb6-dfab263001b1 | Status: DURABLE
| ID | Assumption (believed, not yet proven) | Status | Evidence / next check |
|----|---------------------------------------|--------|-----------------------|
| AS-1 | The prior session's validation (1,849 hermetic green; real Claude/Codex lifecycles) holds for `71c69a2` as received | VERIFIED 09-14 | 1,849 tests OK in 117 s → evidence/hermetic-71c69a2.log |
| AS-2 | The release gate will run the suites (not EXEMPT) since `fleet/`, `scripts/`, `hooks/`, `skills/using-fleet/` all changed | VERIFIED 09-14 | dry-run listed `requiring` rows; the full roster ran (`roster full` in VERDICT.tsv) |
| AS-3 | No live fleet work on the box will contaminate the gate | SANCTIONED 09-14 | the other root's worker stayed live through the run; VERDICT notes `live-subject set CHANGED during the run` yet 0 FAIL rows, so the verdict is GREEN, not INCONCLUSIVE |
| AS-4 | The plan's file table lists `guards.py`/`render.py` as modified; they were never touched on the branch | VERIFIED 09-14 | core reviewer confirmed `git diff --stat` shows neither; plan inaccuracy only |
