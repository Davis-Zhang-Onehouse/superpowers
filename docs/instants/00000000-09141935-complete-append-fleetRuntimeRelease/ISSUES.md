# ISSUES   (durable; append-only; one sub-section per issue)
Updated: 2026-09-14 by session 53ee129f-4b4a-4005-bdb6-dfab263001b1 | Status: DURABLE

## OI-1 Rebase conflicts expected in 5 files
### Symptom
3-way `git merge-tree 31f2c2b live feat/fleet-runtime-selection` shows 8 conflict hunks: `fleet/src/fleet/cli.py` (3), `fleet/it/run-group5.sh` (2), `fleet/src/fleet/session.py` (1), `skills/using-fleet/SKILL.md` (1), `.codex-plugin/plugin.json` (1). Twelve files were edited on both sides in total.
### Root cause
`live` gained pane-guard code 15, the 0.5.8 issue batch, and the release mechanisation after the branch base.
### Action taken
Rebased on a scratch worktree (`.worktrees/fleet-runtime-rebase`, branch `feat/fleet-runtime-selection-rebased`).
Two commits stopped: `f2e6b32` (4 files) and `8f3e892` (cli.py). Resolutions: session.py keeps live's I-16
`_DIALOG_MARKERS` beside `asking()` while the busy/watcher/status-line markers stay moved to runtime.py (the
I-16 amendment paragraph was carried to runtime.py's `_BUSY_MARKERS`); cli.py keeps both sides' `Ctx` fields,
live's `_dispatch_render_context` plus the branch's launch-settings guard and `seed_cli_header` line, and both
abort helpers; run-group5.sh keeps live's `m_timeout` helper with selftest widened 300→600 s (D-3);
using-fleet SKILL keeps live's code-15 paragraph and the branch's "Selecting the runtime" section.
Rebased tip: `db0ba8d` (7 commits; the 8th, `31f2c2b`'s docs, was already on live as `72f4701`).
### Status
FIXED — the rebased tree (now `26aa9ae` after review round 1) passes 1,901 hermetic tests, run-runtime --stubs, §A, §M and group5 (evidence/2026-09-14-round1-checks-{a,b}.log)

## OI-2 Rebase merge artifact: `verdicts` referenced before assignment in dispatch
### Symptom
First hermetic run on the rebased tip `db0ba8d`: 2 failures + 52 errors, all `UnboundLocalError: local variable 'verdicts' referenced before assignment` at `_do_dispatch` (evidence/hermetic-db0ba8d.log).
### Root cause
Live moved `guards.evaluate_all` into the dry-run block after its placeholder-render check (F3/I-24c); the branch resolved launch settings from `verdicts` before the dry-run branch. Git dropped the branch's earlier evaluation while keeping the block that reads it — a clean textual merge, a broken program.
### Action taken
Placeholder render first (dry-run only), then one `evaluate_all`, then the launch-settings resolution, then the dry-run report. Folded into the rebased `feat: select Claude or Codex for fleet runs` commit. Suite green (evidence/hermetic-db0ba8d-plus-dispatch-fix.log, 1,896 OK).
### Status
FIXED

## OI-3 Review round 1 findings (three reviewers, 2026-09-14)
### Symptom
Core reviewer: No (1 Critical — the shared dialog predicate; after the rebase its 14 shadowed live's 15). Scripts/IT reviewer: With fixes (§P config resolution, dangling manifest evidence, weak rollback test). Skills/docs reviewer: With fixes (contradictory `fleet send` prose after rebase, dead link, code-12 help text, unbacked measurements).
### Root cause
Branch built on `31f2c2b`, before live's I-16 (pane-guard 15) and the 0.5.8 batch; plus a handful of genuine defects in the new code (single-fragment dialog rule, root-wide switch blockers, 5 s admission race, byte-exact draft match, PermissionError blinding read verbs).
### Action taken
Commits `8c421c1` (skills/docs) and `26aa9ae` (code + tests). Each finding's disposition is in REVIEW.md (round R1). Sanctioned rather than changed: the 600 s nested-selftest timeout (D-3) and the plan's guards.py/render.py listing (never modified — a plan inaccuracy, noted in HANDOFF).
### Status
FIXED — pending round-2 re-review of the delta
2026-09-14 21:10 UTC: round 2 done — REVIEW.md R2 (two Importants applied in b871a41).

## OI-4 `fleet review` refuses the maintain-workspace skill's `main-` base spelling
### Symptom
`fleet review --instant …/main-09141935-inflight-append-fleetRuntimeRelease --dry-run` → `InstantNameError: base_instant='main' is outside its declared domain. base/curr are 8 digits (00000000 is the root; `main` is deprecated)`.
### Root cause
`skills/maintain-workspace/SKILL.md` and `templates.md` still document `main` as the root base; the fleet CLI's `InstantName` grammar moved to `00000000` and deprecated `main`.
### Action taken
Renamed this instant to `00000000-09141935-inflight-append-fleetRuntimeRelease`. Skill text not changed here (out of scope for this release; a one-line doc fix for a later instant).
### Status
DOCUMENTED — follow-up: align maintain-workspace's grammar table with `InstantName`

## OI-5 J1 (§J harvest section) RED on live since 5dae469 — never run since the 0.5.4 gate
### Symptom
`run-J.sh` on the branch: `J1 FAIL failed_steps=2 declaration_read_back=1 folder_renamed=0`; `complete` refused with `complete-phase: the declared phase is still awaiting-ci`. Same failure on the untouched live checkout (evidence/it-RESULTS-live-f15b585-J.tsv).
### Root cause
5dae469 (2026-09-08) made `complete` refuse while the declared phase is awaiting-ci; J1 declared AWAITING-CI and never declared `done`. §J is only in the `--full` roster, last run for 0.5.4.
### Action taken
J1 declares `done` before `complete` (commit `384bb32`); §J 11 PASS on the branch. A `--full` gate for 0.6.0 would otherwise have been RED for a reason unrelated to this change.
### Status
FIXED

## OI-6 O4 (§O failure injection) read the store as changed after a permission-refused resume
### Symptom
`O4 FAIL no_traceback=1 names_permission=1 store_unchanged=0`.
### Root cause
The branch's admission lock is a stable inode every admitted verb opens; the first `resume` against O4's fresh store created it before the permission refusal. K9 had the same shape and already puts the inode in its baseline.
### Action taken
O4's baseline manifest includes `.runtime-admission.lock` (commit `384bb32`); §O 13 PASS.
### Status
FIXED

## OI-7 §P not exercised on the branch despite skill and run-P.sh changes
### Symptom
Workspace review R3: the gate's roster skips §P (`FLEET_IT_ALLOW_CLAUDE`), and the only P rows anywhere dated 2026-08-17; RV-10 changed `run-P.sh`'s config resolution and it had never run.
### Root cause
§P spends a real claude, so no automated roster includes it; AC-3's clause was not tracked as a step.
### Action taken
Run once on the deployed tip (D-7): P1-P4 PASS, config dir resolved to the operator's (evidence/P-0.6.0/).
### Status
FIXED

## OI-8 Review Minors carried out of the release (RV-20, RV-21, RV-27)
### Symptom
Three Minor findings left `open` in REVIEW.md: reconcile's `/proc/<pid>` cwd for an unreadable row; `_do_runtime` dry-run `would_set` on a no-op; an unused import; tab rejection in `validate_message`; `_do_peers` int(pid) before provenance; `transcripts` mtime hint; a vacuous negative poll window.
### Root cause
None changes behaviour a coordinator depends on; deferred to keep the release scoped.
### Action taken
Listed in HANDOFF Next action.
### Status
DEFERRED — REVIEW.md RV-20 / RV-21 / RV-27

## OI-9 Evidence-path lint nonpassing on 7 historical result tables
### Symptom
`fleet/it/bin/lint-evidence-paths.sh` fails on tracked historical/generated result tables carrying absolute paths (inherited from the original validation report; pre-dates this instant).
### Root cause
Older tracked `RESULTS.tsv` rows and the branch's `final-gate/` evidence contain absolute paths.
### Action taken
None here.
### Status
DEFERRED

## OI-10 D-3 partially superseded by D-4 without a status marker
### Symptom
R3 register cross-check: D-3 kept `_DIALOG_MARKERS` in session.py; D-4/RV-2 folded them into runtime.py, but D-3 still read ACTIVE.
### Root cause
D-4 was appended without amending D-3's status line.
### Action taken
D-3's status now reads SUPERSEDED in part by D-4 (the 600 s half stays ACTIVE).
### Status
FIXED

## OI-11 Historical Codex worktree and branch still present
### Symptom
`.worktrees/fleet-runtime` (71c69a2) and branch `feat/fleet-runtime-selection` remain after landing.
### Root cause
Left for the partner: deleting a branch is their call.
### Action taken
Named in HANDOFF (PR table row 2, Next action 3).
### Status
DEFERRED

## OI-12 Not re-evaluated: Claude watcher-positive `awaiting-ci`; Quorum skill evals
### Symptom
The original validation report states both limits; nothing in this instant re-ran them.
### Root cause
Out of scope (CHARTER Scope OUT); Quorum unavailable on this box.
### Action taken
None.
### Status
DEFERRED
