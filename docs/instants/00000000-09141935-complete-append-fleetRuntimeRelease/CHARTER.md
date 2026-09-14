# Fleet runtime selection — review, rebase, release — CHARTER   (durable; edit deliberately)
Instant: 00000000-09141935-complete-append-fleetRuntimeRelease
Updated: 2026-09-14 by session 53ee129f-4b4a-4005-bdb6-dfab263001b1 | Status: DURABLE

## Goal (e2e)
Take the Codex-built `feat/fleet-runtime-selection` branch (fleet can run under Claude Code **or** Codex
CLI, selected once per fleet between runs) from "implemented, clean, not deployed" to **released**:
iterate code review until the branch is ready, rebase it onto the latest `live`, land it on `live`, and
cut → verify → promote → deploy a fleet release that carries it.

## First 3 raw prompts (verbatim)
1. `/model` — "Kept model as `Fable 5.1`" (harness command, no task content).
2. > The session is 01a0917b-b0d9-79b0-bf3e-69300a18a73c, from Sept 11.
   > Its local transcript is .codex/sessions/2026/09/11/rollout-2026-09-11T17-19-57-01a0917b-b0d9-79b0-bf3e-69300a18a73c.jsonl.
   > It implemented feat/fleet-runtime-selection at commit 71c69a2 in /home/ubuntu/davis_root/superpowers/.worktrees/fleet-runtime
   > previously I used codex to extend the fleet infra to allow us to switch between codex and claude, please read through the worktree, design doc, spec, and chat history to see where we are, then iterate on reviews to get the branch ready, rebase on the latest live branch and cut a release.
   > use maintain workspace skill track the work of an instant under /home/ubuntu/davis_root/superpowers/docs/instants folder
3. > resume

## Setup to begin with
- Base instant: `00000000` — the root (the skill text says `main`; `fleet review` refuses that spelling, see OI-4).
- Branches / checkouts at start:
  - `feat/fleet-runtime-selection` @ `71c69a2` in `/home/ubuntu/davis_root/superpowers/.worktrees/fleet-runtime` (8 commits on base `31f2c2b`; clean).
  - `live` @ `f15b585` (fleet v0.5.12 + 3 fixes) in `/home/ubuntu/davis_root/superpowers`; 44 commits ahead of the branch base.
  - Deployed release: whatever `fleet-releases/current` points at (record in HANDOFF at first check).
- Prior-session artifacts to trust as input (not re-derive): the design spec
  `docs/superpowers/specs/2026-09-11-fleet-runtime-selection-design.md`, the plan
  `docs/superpowers/plans/2026-09-11-fleet-runtime-selection.md`, and the validation report
  `docs/superpowers/specs/evidence/2026-09-11-fleet-runtime-validation.md` (all on the branch).

## Scope
- IN: code review of the branch diff (correctness, safety of the switch/lock/launch paths, skill edits);
  fixing findings; rebasing onto `live` and resolving conflicts; re-running the hermetic suite and the
  relevant IT sections; landing on `live`; the four-verb release chain plus preflight/postflight.
- OUT: new features (mixed-runtime fleets, model routing, Codex CI wake); an upstream PR to obra/superpowers;
  re-running the paid live-model lifecycles (Claude/Codex real dispatch) unless a review finding demands it.

## Acceptance criteria (NL → executable proof → self-review)

### AC-1 Branch reviewed and findings closed
- [x] Statement: the branch diff has had at least one code-review round; every Critical/High finding is
  fixed or explicitly sanctioned; the review ledger records each finding's disposition.
- Proof: `REVIEW.md` rounds with every Critical/Important finding applied or sanctioned (Minors may be carried, named in ISSUES); fix commits named in the PR table.
- Self-review: MET — R1 (22 findings) + R2 (10 findings), 0 open blocking; 3 Minor follow-ups open (RV-20, RV-21, RV-27); fixes in 8c421c1, 26aa9ae, b871a41, 384bb32.

### AC-2 Rebased onto latest live, hermetic suite green
- [x] Statement: `feat/fleet-runtime-selection` is rebased onto `live`'s tip with conflicts resolved and
  the full hermetic suite passes from the rebased tip.
- Proof: `git merge-base live <tip>` == `live` tip; `evidence/hermetic-<sha>.log` ending `OK` (count ≥ 1,849 pre-rebase baseline reconciled with live's additions).
- Self-review: MET — live fast-forwarded to 384bb32 (then e753110 docs, e99d7d4 cut); 1,903 tests OK on the tip (evidence #6) and again from the tag export in the gate (`release-0.6.0/hermetic-tail.txt`).

### AC-3 Relevant integration sections pass on the rebased tip
- [x] Statement: the runtime IT runner (`run-runtime.sh --stubs`) and the sections touching changed
  files (§A, group5 §L/§M/§N, §P if a skill/verb a skill names changed) pass on the rebased tip, using scratch `IT_RESULTS`.
- Proof: `evidence/it-*-<sha>.tsv` with 0 FAIL rows.
- Self-review: MET — runtime stubs, §A, group5, §F/G/H/I/J/O/LB all PASS on the tip (evidence #4-#8), then the whole full roster again in the gate: 0 FAIL rows (`release-0.6.0/it-fail-rows.txt`); §P run once on the deployed tip per D-7: P1-P4 PASS (`P-0.6.0/`).

### AC-4 Landed on live and released
- [x] Statement: the rebased branch is on `live`; a fleet release vX.Y.Z is cut from it, verified GREEN
  (or the gate outcome is recorded honestly), promoted, deployed, and postflight proves every root is on it.
- Proof: `fleet-releases/fleet-vX.Y.Z/.release/evidence/VERDICT.tsv` `verdict GREEN`; `release-postflight.sh X.Y.Z` exit 0; copies in `evidence/`.
- Self-review: MET — fleet 0.6.0 cut (e99d7d4, tag fleet/v0.6.0), gate GREEN on the FULL roster in 42 min, promoted, deployed (`current` → fleet-v0.6.0), postflight all OK (`evidence/release-0.6.0/`).

## Setup to end up with (the handoff)
- Deliverables: `live` @ e99d7d4 containing the runtime-selection commits; release tag `fleet/v0.6.0`; deployed
  `fleet-releases/current` → fleet-v0.6.0; REVIEW.md ledger (2 rounds); evidence/ with suite logs, IT registers, VERDICT copy.
- Reproducible stack: RUNBOOK.md (suite + IT + release chain commands); evidence/INDEX.md.

## Standing constraints / rules
- Release traps from `skills/releasing-fleet/SKILL.md` and `fleet/CLAUDE.md` apply: absolute `bin/fleet`
  path; never pipe a control; `setsid` the gate via `scripts/release-gate.sh`; **zero tool calls while
  the gate runs**; do not start a gate after ~02:45 UTC (03:30 sync cron); scratch `IT_RESULTS` for
  check runs; tree must be clean (incl. untracked) at cut.
- No upstream PR from this work (fork-only `live`). No changes to live fleet stores or credentials.
- `docs/instants/` is tracked — commit the instant before the cut or the cut refuses.

## Environment
- Box: AWS Linux 6.8, tmux 3.2a, python3 stdlib only. Claude Code 2.1.268 / Codex CLI 0.154.0 (as measured on 2026-09-11).
- Release area: `$FLEET_RELEASES` from `scripts/fleet-env.sh` (`/home/ubuntu/davis_root/fleet-releases`).
