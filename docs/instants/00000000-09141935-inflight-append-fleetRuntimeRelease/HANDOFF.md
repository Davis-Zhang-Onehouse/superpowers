# Fleet runtime selection — review, rebase, release — HANDOFF   (read me first)
Updated: 2026-09-14 21:14 UTC by session 53ee129f-4b4a-4005-bdb6-dfab263001b1  |  Status: LIVE (current state + handoff; rots — reconcile to DECISIONS)

# ===== PART A · CURRENT STATE =====

## Where we are (one paragraph)
The branch is rebased onto `live` (f15b585) as `feat/fleet-runtime-selection-rebased` @ `384bb32` (11 commits:
the 7 Codex commits re-applied, one merge artifact folded in, two review-round-1 commits, one round-2 commit,
and one integration-runner fix). `live` is fast-forwarded to it. Review round
1 (three reviewers) found one Critical in the new code (a prose-matching dialog predicate that also shadowed
live's pane-guard 15 after the rebase), eight Importants and a set of minors; all Critical/Important are
applied or sanctioned (REVIEW.md R1). Verification on the tip: 1,901 hermetic tests OK; runtime stubs, §A,
§M, group5, hooks, Codex packaging and script tests PASS. Round 2 (one reviewer over the delta) found two Importants (a measured Codex trust dialog dropped; dialog
ordering differed by path), both applied; §J/§O exposed a pre-existing J1 failure and an O4 baseline gap, both
fixed (OI-5, OI-6). Full roster green on the tip. Next action: the release chain for 0.6.0.

## Live snapshot (volatile — dated 2026-09-14 20:52 UTC)
- In flight: release chain 0.6.0 (see RUNBOOK) — preflight → cut → gate --full → promote → deploy → postflight.
- Box: preflight at 19:36 UTC saw one live dt- session on another root's socket (fleet-davis2) — residual risk for the gate.
- Blockers: none

## PR / branch stack   (REQUIRED — the ONE home for the stack; fork-only, no GitHub PR)
| Repo | Branch | Tip githash | PR (full-URL link) | CI (PR checks page → latest run) | Contents |
|------|--------|-------------|--------------------|----------------------------------|----------|
| Davis-Zhang-Onehouse/superpowers | `live` = `feat/fleet-runtime-selection-rebased` (worktree `.worktrees/fleet-runtime-rebase`) | `384bb32` | branch only (no PR — fork-internal, lands on `live`) | local: hermetic 1,901 OK + IT sections PASS (evidence/INDEX #4-5); release gate not yet run | the 7 Codex commits rebased on live + `8c421c1` + `26aa9ae` (round 1) + `b871a41` (round 2) + `384bb32` (J1/O4 runners) |
| Davis-Zhang-Onehouse/superpowers | `feat/fleet-runtime-selection` (worktree `.worktrees/fleet-runtime`) | `71c69a2` | HISTORICAL — the branch as Codex left it; superseded by the rebased branch | baseline: hermetic 1,849 OK (evidence #1) | untouched; delete the worktree after landing |
| Davis-Zhang-Onehouse/superpowers | `live` (before landing) | `f15b585` | — | last release: fleet v0.5.12 (`a518d27`) | HISTORICAL target state |

## How each artifact was built & tested (REVIEWER GUIDE)
### The branch (as received)
- **What it is:** 8 commits `31f2c2b..71c69a2`, implementing `docs/superpowers/specs/2026-09-11-fleet-runtime-selection-design.md` per the plan.
- **Built by:** Codex CLI session `01a0917b-b0d9-79b0-bf3e-69300a18a73c` (transcript `~/davis_root/.codex/sessions/2026/09/11/rollout-2026-09-11T17-19-57-*.jsonl`).
- **Tested by (prior session, trusted as input):** 1,849 hermetic tests green from an export of `b3516c7`; default IT batch 250 PASS / 1 FAIL (E1, test-only expectation, corrected + 20-iter retest green) / 10 SKIP on `b3516c7`; real Claude and Codex two-worker lifecycles; see `docs/superpowers/specs/evidence/2026-09-11-fleet-runtime-validation.md`.
- **Caveats:** Codex CI wake unsupported (refuses; documented). Quorum evals unavailable. Evidence-path lint nonpassing on 7 historical result tables.

## Working set
- Rebased branch worktree: `/home/ubuntu/davis_root/superpowers/.worktrees/fleet-runtime-rebase` (feat/fleet-runtime-selection-rebased @ 26aa9ae) — THE tree to land
- Original branch worktree: `/home/ubuntu/davis_root/superpowers/.worktrees/fleet-runtime` (71c69a2) — historical
- Main checkout: `/home/ubuntu/davis_root/superpowers` (live @ f15b585)

### How the rebased branch was built & tested (reviewer guide)
- **Rebase:** `git rebase live` on a scratch worktree; two commits stopped (5 files, 8 hunks) — resolutions in ISSUES OI-1 / DECISIONS D-3; one clean-merge artifact (OI-2) folded into the feature commit.
- **Review round 1:** three parallel read-only reviewers (core src / scripts+IT+tests / skills+docs+spec traceability) over `31f2c2b..71c69a2`; findings and dispositions in REVIEW.md R1; fixes in `8c421c1` + `26aa9ae` (D-4, D-5).
- **Tested by:** RUNBOOK § Hermetic + § Integration sections on the tip → evidence/INDEX #4-5.

# ===== PART B · HANDOFF (pickup guide) =====

## Resume here
- Workspace folder: `/home/ubuntu/davis_root/superpowers` (main checkout, live) — branch work in `.worktrees/fleet-runtime`
- Resume the latest session: `cd /home/ubuntu/davis_root/superpowers && claude --resume 53ee129f-4b4a-4005-bdb6-dfab263001b1`

## Next action
1. Release (RUNBOOK § Release chain): preflight → `release-cut --version 0.6.0 --dry-run` → cut → `release-gate.sh 0.6.0 --full` (~1 h, silent, zero tool calls) → promote → deploy → postflight. Record the verdict here and copy VERDICT.tsv into evidence/.

## Setup you end up with (delivered handoff — point, don't duplicate)
- **PR stack:** Part A table. **Artifacts:** Part A reviewer guide. **Commands:** RUNBOOK.md.
- **Proof per AC:** AC-1 → REVIEW.md · AC-2/3/4 → evidence/INDEX.md.

## Session log
| Date | Workspace | Resume cmd | Did what |
|------|-----------|------------|----------|
| 2026-09-14 | ~/davis_root/superpowers | `cd /home/ubuntu/davis_root/superpowers && claude --resume 53ee129f-4b4a-4005-bdb6-dfab263001b1` | created instant; read spec/plan/validation/Codex transcript; hermetic baseline; rebased onto live (OI-1, OI-2); review round 1 (REVIEW.md R1, 22 findings) and fixes; suite + IT sections green on 26aa9ae; instant renamed to fleet's `00000000-` root spelling (OI-4) |

## Index
- Scope / acceptance → CHARTER.md · Commands → RUNBOOK.md · Decisions → DECISIONS.md · Issues → ISSUES.md · Assumptions → ASSUMPTIONS.md · Proofs → evidence/INDEX.md · Review ledger → REVIEW.md
