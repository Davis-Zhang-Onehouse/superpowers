# ASSUMPTIONS   (the unverified-beliefs register; append, don't rewrite)
| ID | Assumption (believed, not yet proven) | Status | Evidence / next check |
|----|---------------------------------------|--------|-----------------------|
| AS-1 | A Codex worker's rollout carries the seed as its first non-environment user `response_item` | REFUTED 09-15 | review round 1: 4 of 6 rollouts here open with `<recommended_plugins>` or an AGENTS.md user block; the rule now scans the first five user blocks and is measured against two real rollouts (evidence #5) |
| AS-2 | `claude --resume <uuid>` continues the same transcript file (same uuid) rather than forking a new one | OPEN | the 2026-09-08 revival of `995a2a6a` shows no timestamped rows after the launcher; the next session in that slot carried a different seed |
