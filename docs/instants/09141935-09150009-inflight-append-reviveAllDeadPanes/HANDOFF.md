# Revive all dead panes — HANDOFF   (read me first)
Updated: 2026-09-15 by session 53ee129f-4b4a-4005-bdb6-dfab263001b1  |  Status: LIVE

# ===== PART A · CURRENT STATE =====

## Where we are (one paragraph)
Implemented on `live`: 6609648 (script, test, skill, README) + 96a29bb (review round 1: two Critical matcher findings fixed — Codex injected user blocks, whole-seed identity — plus last-written tiebreak, duplicate-session refusal, error-vs-no-match, outside-HOME parity, 35-check test). AC-1..AC-3 MET (evidence #1-#7, regenerated on 96a29bb). Round 2 (verification pass) found one Important residual (a traceback read as an undelivered seed) and four minors, all applied in c88cf04; 37 test checks. Next: the patch release 0.6.1 (AC-4).

## Live snapshot (volatile — dated)
- In flight: release 0.6.1 (cut → standard gate → promote → deploy → postflight).
- Blockers: none.

## PR / branch stack
| Repo | Branch | Tip githash | PR (full-URL link) | CI | Contents |
|------|--------|-------------|--------------------|----|----------|
| superpowers (local) | live | c88cf04 | branch only (no PR; landed directly on `live`) | local gate (pending) | 6609648 script + test + skill + README; 96a29bb round 1 fixes; c88cf04 round 2 fixes |

## How each artifact was built & tested (REVIEWER GUIDE)
### `scripts/fleet-revive.sh` (plan | revive)
- **What it is / vs baseline:** the operator surface of the reviving-dead-panes skill; baseline (0.6.0) took a todo-id per call and listed transcripts for the operator to pick.
- **Built by:** hand, on `live`; **Tested by:** `scripts/tests/fleet-revive.sh` (evidence #1), two real roots (#2-#4), the live matcher (#5), an end-to-end run through the real verb (#6).
- **Caveats:** the Codex seed rule is measured against a fixture shaped like a real davis rollout, not a dispatched Codex worker (AS-1); a legacy Claude record resolves its configuration through `claude-config-dir.sh`, untested against a live legacy record here.

## Working set
- superpowers: `live`@350a661 in `/home/ubuntu/davis_root/superpowers`.

# ===== PART B · HANDOFF (pickup guide) =====

## Resume here
- Workspace folder: `/home/ubuntu/davis_root/superpowers`
- Resume the latest session: `cd /home/ubuntu/davis_root/superpowers && claude --resume 53ee129f-4b4a-4005-bdb6-dfab263001b1`

## Next action (the very next thing to do)
1. RUNBOOK § Release chain for 0.6.1.

## Setup you end up with
- see CHARTER § Setup to end up with (filled at completion).

## Session log
| Date | Workspace | Resume cmd | Did what |
|------|-----------|------------|----------|
| 2026-09-15 | superpowers | `claude --resume 53ee129f-…` | measured transcript identity; created instant; designing |

## Index
- Scope / acceptance → CHARTER.md · Decisions → DECISIONS.md · Issues → ISSUES.md · Assumptions → ASSUMPTIONS.md · Commands → RUNBOOK.md · Proof → evidence/INDEX.md
