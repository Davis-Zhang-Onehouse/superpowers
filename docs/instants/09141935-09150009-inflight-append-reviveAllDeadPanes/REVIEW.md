# REVIEW — 09141935-09150009-inflight-append-reviveAllDeadPanes

<!-- GENERATED from .fleet/review.json. This file is a VIEW: it is regenerated in full on
     every render, hand edits are discarded, and NOTHING reads it for a control signal.
     Two READY workers were once blocked by a regex over prose exactly like this. -->

**Gate:** ALLOWED (`review-verdict`)

round 2 (scope code) recorded READY-WITH-FIXES at 2026-09-15T00:47:20Z with 0 open blocking findings. population: 2 round(s) [code, code]; scopes covered: code; 21 finding(s), 0 open blocking; ledger /home/ubuntu/davis_root/superpowers/docs/instants/09141935-09150009-inflight-append-reviveAllDeadPanes/.fleet/review.json

## Round 1 — scope `code` — verdict `READY-WITH-FIXES` — 2026-09-15T00:36:49Z

| id | severity | status | location | finding | action |
|---|---|---|---|---|---|
| C1 | Critical | applied | scripts/fleet-revive.sh matcher codex_meta | Codex rollouts inject user-role blocks (recommended_plugins, AGENTS.md preamble) ahead of the prompt, 4 of 6 rollouts on this box; the matcher stopped at the first user block so no transcript matched and the whole run was refused | inspect the first five user blocks on either runtime (96a29bb); measured against two real rollouts |
| C2 | Critical | applied | scripts/fleet-revive.sh matcher seed comparison | only the first 200 squashed characters of the seed were compared; 28 characters of margin before the instant path fell outside the window, after which every worker of an effort in a slot compared equal (silent wrong revival) | compare the whole squashed seed and refuse when two records resolve to one transcript (96a29bb) |
| I3 | Important | applied | scripts/fleet-revive.sh matcher tiebreak | the tiebreak keyed on the first row timestamp, which a replayed fork keeps, so a fork and its origin tied | choose the transcript last written to (mtime) and print all candidates with their write times (96a29bb) |
| I4 | Important | applied | scripts/fleet-revive.sh header and banner | FLEET_BIN is read from the environment while the header said nothing is; the binary acting was never printed | header corrected; the banner prints fleet binary (96a29bb) |
| I5 | Important | applied | scripts/fleet-revive.sh matcher exit codes | a matcher crash was reported as no transcript carries this seed | exit 1 for no match, 3 for an error; the shell branches on rc and shows the last stderr line (96a29bb) |
| I6 | Important | applied | scripts/tests/fleet-revive.sh | fixtures too idealised to see C1; the failure path, the legacy configuration path, the verb refusal and an outside-HOME cwd were untested | realistic Codex rollout shape, a leading caveat row, a same-start fork, a failing shim, owners-map legacy record, the verb dry-run refusal, duplicate session and outside-HOME added, 35 checks (96a29bb); UNREACHABLE, PENDING-LAUNCH and released-lease rows are not fixturable hermetically and a released lease never reaches the board as DEAD, see OI-3 |
| I7 | Important | applied | scripts/fleet-revive.sh resolve_root | the shell walk accepted a cwd outside HOME that fleet.root.find refuses | the walk refuses a cwd not under HOME with the reason (96a29bb) |
| M1 | Minor | applied | scripts/fleet-revive.sh UNREACHABLE count | counted without the worker filter the DEAD selection applies | filtered (96a29bb) |
| M2 | Minor | wont-fix | scripts/fleet-revive.sh runtime compare | compares the defaulted runtime rather than the raw field | evidence.runtime is never empty for a record the current binary reads (the dataclass defaults it), and the dry-run repeats the verb check |
| M3 | Minor | applied | skills/reviving-dead-panes/SKILL.md | the documented command uses FLEET_RELEASES which the script then reports as ignored | one clause says the lines are information, not an error (96a29bb) |
| M4 | Minor | applied | scripts/fleet-revive.sh pane-guard line | the immediate poll reads 14 or 10 on a booting pane and looked like a verdict | labelled first poll, read the pane (96a29bb) |
| M5 | Minor | applied | scripts/tests/fleet-runtime-helpers.sh | dead fixture and unused imports after the revive assertions moved | trimmed (96a29bb) |
| M6 | Minor | wont-fix | scripts/fleet-revive.sh awk -v id | backslash escapes processed in the value | unreachable with the todo-id charset; revisit if the id shape widens |
| M7 | Minor | applied | docs/superpowers/fleet-infra-backlog.md | described the removed plan transcripts launcher start shape | one sentence names the 0.6.1 shape (96a29bb) |

## Round 2 — scope `code` — verdict `READY-WITH-FIXES` — 2026-09-15T00:47:20Z

| id | severity | status | location | finding | action |
|---|---|---|---|---|---|
| V1 | Important | applied | scripts/fleet-revive.sh matcher exit codes | the no-match exit was 1, which is also an uncaught exception exit, so a traceback was reported as an undelivered seed and its text discarded (residual of I5) | no match exits 4, an exact write-time tie exits 5 and refuses with both candidates printed, anything else is an error shown with its last line; tests for the tie and for an unopenable transcript path (round 2 commit) |
| V2 | Minor | applied | scripts/fleet-revive.sh matcher per-file errors | one transcript vanishing or unreadable between the listing and the read aborted the whole search | FileNotFoundError and PermissionError skip the file; a malformed cwd is skipped; other OSError still exits 3 (round 2 commit) |
| V3 | Minor | applied | scripts/fleet-revive.sh header | the environment claim named only FLEET_BIN while HOME and CLAUDE_OWNERS_MAP are read | all three named (round 2 commit) |
| V4 | Minor | applied | scripts/fleet-revive.sh tiebreak | equal write times were broken silently by string order while the note said last written was chosen | an exact tie refuses (V1) (round 2 commit) |
| V5 | Minor | applied | scripts/fleet-revive.sh duplicate-session loop | one shared transcript reported as two problems | reported once per pair, naming both (round 2 commit) |
| V6 | Nit | applied | scripts/fleet-revive.sh USER_BLOCKS comment | the margin of five user blocks was not explained against the measured positions (1 for Claude, 2 for Codex, up to 8 after pre-seed slash commands) | a comment states the measured positions and that the rule degrades to a refusal, never a wrong choice (round 2 commit) |
| V7 | Minor | routed | scripts/tests/fleet-revive.sh | no case for a marker without a name and none for the rc-3 branch beyond the unopenable path | marker-without-name is refused by the same python the root walk and fleet-env share; left for a later instant |

