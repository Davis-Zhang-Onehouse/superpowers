# Revive all dead panes — HANDOFF   (read me first)
Updated: 2026-09-15 by session 53ee129f-4b4a-4005-bdb6-dfab263001b1  |  Status: DELIVERED

# ===== PART A · CURRENT STATE =====

## Where we are (one paragraph)
Implemented on `live`: 6609648 (script, test, skill, README) + 96a29bb (review round 1: two Critical matcher findings fixed — Codex injected user blocks, whole-seed identity — plus last-written tiebreak, duplicate-session refusal, error-vs-no-match, outside-HOME parity, 35-check test). AC-1..AC-3 MET (evidence #1-#7, regenerated on 96a29bb). Round 2 (verification pass) found one Important residual and four minors, all applied in c88cf04; 37 test checks. **DELIVERED:** fleet 0.6.1 cut, gate GREEN (standard roster, 39 min), promoted, deployed and postflight-clean on both roots on 2026-09-15; all four ACs MET. Nothing is in flight.

## Live snapshot (volatile — dated)
- In flight: nothing. Deployed: `fleet-releases/current → fleet-v0.6.1` (2026-09-15 ~01:30 UTC).
- Blockers: none.

## PR / branch stack
| Repo | Branch | Tip githash | PR (full-URL link) | CI | Contents |
|------|--------|-------------|--------------------|----|----------|
| superpowers (local) | live | f85dee3 | branch only (no PR; landed directly on `live`) | local gate GREEN 2026-09-15 (`evidence/release-0.6.1/VERDICT.tsv`) | 6609648 script + test + skill + README; 96a29bb round 1 fixes; c88cf04 round 2 fixes; ce7a866 instant; f85dee3 fleet v0.6.1 |

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
None required — the instant is complete. Optional follow-ups: REVIEW.md V7 (a marker-without-name test case); OI-3's board states remain untestable hermetically; AS-2 (does `claude --resume` keep the uuid) is still unmeasured and only affects which of two printed candidates is chosen.

## Setup you end up with
- **Commits:** Part A table. **Use:** RUNBOOK § Use (from inside a root: `bash "$FLEET_RELEASES/current/scripts/fleet-revive.sh" plan|revive`). **Proof per AC:** AC-1 → evidence #1-#4 · AC-2 → #1, #6 · AC-3 → #1, #5 · AC-4 → #9-#12; reviews → REVIEW.md (2 rounds, 21 findings, 0 open blocking).

## Session log
| Date | Workspace | Resume cmd | Did what |
|------|-----------|------------|----------|
| 2026-09-15 | superpowers | `claude --resume 53ee129f-…` | measured transcript identity; designed; implemented script/test/skill; two review rounds; released and deployed fleet 0.6.1; instant complete |

## Index
- Scope / acceptance → CHARTER.md · Decisions → DECISIONS.md · Issues → ISSUES.md · Assumptions → ASSUMPTIONS.md · Commands → RUNBOOK.md · Proof → evidence/INDEX.md
