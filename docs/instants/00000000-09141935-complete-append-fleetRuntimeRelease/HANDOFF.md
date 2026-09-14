# Fleet runtime selection — review, rebase, release — HANDOFF   (read me first)
Updated: 2026-09-14 22:12 UTC by session 53ee129f-4b4a-4005-bdb6-dfab263001b1  |  Status: LIVE (current state + handoff; rots — reconcile to DECISIONS)

# ===== PART A · CURRENT STATE =====

## Where we are (one paragraph)
DELIVERED. fleet 0.6.0 carries the runtime-selection feature (Claude Code or Codex CLI per fleet): the Codex
branch was rebased onto `live`, reviewed in two rounds (32 findings, 0 open blocking, 3 Minor follow-ups),
landed by fast-forward, cut as `fleet/v0.6.0` (e99d7d4), gated GREEN on the FULL roster (329 PASS / 11 SKIP
/ 0 FAIL, 1,903 hermetic), promoted, deployed (`fleet-releases/current` → fleet-v0.6.0) and postflight-verified
on every manifest and root. Nothing is in flight. Remaining work is optional follow-ups (below).

## Live snapshot (volatile — dated 2026-09-14 22:02 UTC)
- In flight: nothing.
- Deployed: fleet 0.6.0 (`release-status` in evidence/release-0.6.0/). The second root (davis2) shares the release area and is on it (postflight OK); its worker shells must use the 0.6.0 binary — old binaries cannot read runtime-bearing records.
- Blockers: none.

## PR / branch stack   (REQUIRED — the ONE home for the stack; fork-only, no GitHub PR)
| Repo | Branch | Tip githash | PR (full-URL link) | CI (PR checks page → latest run) | Contents |
|------|--------|-------------|--------------------|----------------------------------|----------|
| Davis-Zhang-Onehouse/superpowers | `live` | `e99d7d4` (`fleet v0.6.0`; feature tip `384bb32`, instant docs `e753110`) | branch only (no PR — fork-internal; the rebase worktree and its branch were removed after landing) | release gate: GREEN, full roster, 2026-09-14 21:54 UTC (evidence/release-0.6.0/VERDICT.tsv); deployed as `current` | the 7 Codex commits rebased on live + `8c421c1` + `26aa9ae` (round 1) + `b871a41` (round 2) + `384bb32` (J1/O4 runners) |
| Davis-Zhang-Onehouse/superpowers | `feat/fleet-runtime-selection` (worktree `.worktrees/fleet-runtime`) | `71c69a2` | branch only (no PR — HISTORICAL, the branch as Codex left it; superseded by what landed) | hermetic 1,849 OK, 2026-09-14 19:40 UTC (evidence/hermetic-71c69a2.log) | left in place for the partner to delete (`git worktree remove .worktrees/fleet-runtime && git branch -D feat/fleet-runtime-selection`) |
| Davis-Zhang-Onehouse/superpowers | `live` (before landing) | `f15b585` | n/a (starting state) | deployed v0.5.12 GREEN, as of 2026-09-14 19:36 UTC (`fleet release-list`, evidence/release-0.6.0/release-status.txt shows the successor) | HISTORICAL target state |

## How each artifact was built & tested (REVIEWER GUIDE)
### The branch (as received)
- **What it is:** 8 commits `31f2c2b..71c69a2`, implementing `docs/superpowers/specs/2026-09-11-fleet-runtime-selection-design.md` per the plan.
- **Built by:** Codex CLI session `01a0917b-b0d9-79b0-bf3e-69300a18a73c` (transcript `~/davis_root/.codex/sessions/2026/09/11/rollout-2026-09-11T17-19-57-*.jsonl`).
- **Tested by (prior session, trusted as input):** 1,849 hermetic tests green from an export of `b3516c7`; default IT batch 250 PASS / 1 FAIL (E1, test-only expectation, corrected + 20-iter retest green) / 10 SKIP on `b3516c7`; real Claude and Codex two-worker lifecycles; see `docs/superpowers/specs/evidence/2026-09-11-fleet-runtime-validation.md`.
- **Caveats:** Codex CI wake unsupported (refuses; documented). Quorum evals unavailable. Evidence-path lint nonpassing on 7 historical result tables.

### The rebased branch (what landed on `live`)
- **What it is:** the 7 Codex commits re-applied on `f15b585` + `8c421c1`, `26aa9ae` (round 1), `b871a41` (round 2), `384bb32` (J1/O4 runners) — tip `384bb32`, now an ancestor of `live`.
- **Built by:** this session (53ee129f-4b4a-4005-bdb6-dfab263001b1), on a scratch worktree since removed.
- **Provenance:** `git log f15b585..384bb32` on `live`; each review commit's message names the finding ids it closes (REVIEW.md R1/R2).
- **Rebase:** `git rebase live` on a scratch worktree; two commits stopped (5 files, 8 hunks) — resolutions in ISSUES OI-1 / DECISIONS D-3; one clean-merge artifact (OI-2) folded into the feature commit.
- **Review round 1:** three parallel read-only reviewers (core src / scripts+IT+tests / skills+docs+spec traceability) over `31f2c2b..71c69a2`; findings and dispositions in REVIEW.md R1; fixes in `8c421c1` + `26aa9ae` (D-4, D-5).
- **Review round 2:** one reviewer over the delta + rebase resolutions; two Importants applied in `b871a41`; §J/§O then exposed OI-5/OI-6, fixed in `384bb32`.
- **Tested by:** RUNBOOK § Hermetic + § Integration sections on the tip → evidence/INDEX #4-8; the release gate on the tag export → INDEX #9-10; §P (real claude) on the deployed tip → INDEX #11.

### The release (fleet 0.6.0)
- **What it is:** `git archive` of tag `fleet/v0.6.0` at `/home/ubuntu/davis_root/fleet-releases/fleet-v0.6.0`; stamps `6.3.0+fleet.0.6.0` on every plugin manifest. Payload areas: fleet, skills (6), scripts, hooks, docs, tests.
- **Built by:** `fleet release-cut --version 0.6.0` (D-6: minor bump). **Verified by:** `scripts/release-gate.sh 0.6.0 --full` → GREEN (INDEX #9). **Deployed by:** `release-promote` + `release-deploy --reason …`; `release-postflight.sh 0.6.0` OK (INDEX #10).

## Working set
- Main checkout: `/home/ubuntu/davis_root/superpowers` (live @ e99d7d4) — the delivered tree
- Original Codex worktree: `/home/ubuntu/davis_root/superpowers/.worktrees/fleet-runtime` (71c69a2) — historical only
- Release area: `/home/ubuntu/davis_root/fleet-releases/fleet-v0.6.0` (`current`)

# ===== PART B · HANDOFF (pickup guide) =====

## Resume here
- Workspace folder: `/home/ubuntu/davis_root/superpowers` (main checkout, live) — branch work in `.worktrees/fleet-runtime`
- Resume the latest session: `cd /home/ubuntu/davis_root/superpowers && claude --resume 53ee129f-4b4a-4005-bdb6-dfab263001b1`

## Next action
None required — the instant is complete. Optional follow-ups, each small and none release-blocking:
1. REVIEW.md RV-20 / RV-21 / RV-27 (core and IT minors: reconcile's `/proc/<pid>` cwd for an unreadable row, `_do_runtime` dry-run `would_set` on a no-op, an unused import, tab rejection in `validate_message`, `transcripts` mtime hint).
2. OI-4: align `skills/maintain-workspace` grammar text (`main`) with fleet's `InstantName` (`00000000`).
3. Delete the historical Codex worktree/branch (PR table row 2).
4. Not re-evaluated here and still open from the original validation (OI-9, OI-12): the evidence-path lint on 7 historical tables; Claude's external watcher-positive `awaiting-ci` path; Quorum skill evals (unavailable).

## Setup you end up with (delivered handoff — point, don't duplicate)
- **PR stack:** Part A table. **Artifacts:** Part A reviewer guide. **Commands:** RUNBOOK.md.
- **Proof per AC:** AC-1 → REVIEW.md · AC-2/3/4 → evidence/INDEX.md.

## Session log
| Date | Workspace | Resume cmd | Did what |
|------|-----------|------------|----------|
| 2026-09-14 | ~/davis_root/superpowers | `cd /home/ubuntu/davis_root/superpowers && claude --resume 53ee129f-4b4a-4005-bdb6-dfab263001b1` | created instant; read spec/plan/validation/Codex transcript; hermetic baseline; rebased onto live (OI-1, OI-2); review rounds 1 and 2 (REVIEW.md, 32 findings) and fixes; full roster green on the tip (OI-5, OI-6 fixed); landed on live; cut/gated (GREEN, full)/promoted/deployed fleet 0.6.0; postflight OK; §P on the tip PASS; workspace review R3; instant completed |

## Index
- Scope / acceptance → CHARTER.md · Commands → RUNBOOK.md · Decisions → DECISIONS.md · Issues → ISSUES.md · Assumptions → ASSUMPTIONS.md · Proofs → evidence/INDEX.md · Review ledger → REVIEW.md
