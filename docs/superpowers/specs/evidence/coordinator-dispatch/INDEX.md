# Native coordinator dispatch and sandbox preflight

A real Codex coordinator loaded `coordinating-instants` and issued the prepared peer dispatch through
`FLEET_BIN` on an isolated server. This checks a model-issued dispatch separately from the driver-issued
two-worker lifecycle tests. It does not evaluate autonomous scheduling policy.

Before the fix, a sandbox-denied tmux call was treated as an empty server. Dispatch created a pending
record and lease; the normal approved retry then refused at cap 2. See session
`01a0921d-12f0-7990-998b-c039c0e31f04` and the unlaunched, subsequently harvested record in `final-records.json`.

Commit `b3516c7` refuses unreadable tmux inventory before record/lease creation, while preserving the
normal absent-server case. The repeated coordinator session `01a09222-993d-7f91-98f7-26a0d56389cf`
received the sandbox refusal, requested ordinary approval for the exact private dispatch, and succeeded
after one approval. `before-approval-records.json` contains only the active coordinator and the two
harvested records from the first attempt: there is no new pending peer. The peer session
`01a0922e-7952-7ff0-8d81-a691d202b8a0` replied `PEER READY` after project trust was accepted.
No global permission mode was changed.

`commands.jsonl` records the driver observations and cleanup. Sessions were deliberately aborted after
the probe, reviewed against its evidence, and harvested. An initial abort retained each lease while
its process was still exiting; retry after exit succeeded. `final-records.json` verifies all four
records were harvested. These aborts are test cleanup, not completed project work.

Session exports contain user/assistant exchanges and tool calls/results, excluding internal reasoning
and system/developer context. The unit suite passed 1,849 tests in 113.539 seconds before this fix was
committed, including denied-inventory and no-pending-record regressions.
