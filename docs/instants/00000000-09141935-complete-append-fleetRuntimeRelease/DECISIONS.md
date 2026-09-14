# DECISIONS   (durable; append-only register; the authoritative decision timeline / tie-breaker)
Updated: 2026-09-14 by session 53ee129f-4b4a-4005-bdb6-dfab263001b1 | Status: DURABLE

## D-1 — Land by rebasing the feature branch onto `live`, then fast-forward `live`; no upstream PR   (2026-09-14, ACTIVE)
### Context
The branch was built on `31f2c2b`; `live` is 44 commits ahead. The partner asked to "rebase on the latest live branch and cut a release". This repo's `live` is a fork branch; upstream PRs are a separate, explicitly out-of-scope action (plan §Global Constraints).
### Decision
Rebase `feat/fleet-runtime-selection` onto `live`, resolve conflicts in the worktree, verify, then fast-forward `live` to the rebased tip and cut the release from `live`.
### Rationale
Keeps linear history the release pipeline expects (tag-based, cut from `live`); avoids a merge commit that the 03:30 UTC upstream-sync rebase would have to replay.
### Consequences
Rebased commits get new SHAs; the validation report's source pins (`b3516c7`, `8f3e892`) remain historical references to the pre-rebase measurements and are cited as such, not re-attributed.

## D-2 — The instant folder is committed to `live` before the cut   (2026-09-14, ACTIVE)
### Context
`docs/instants/` is not gitignored; `release-cut` refuses any dirty row including untracked files.
### Decision
Commit the instant docs on `live` as an ordinary docs commit before cutting. Post-cut HANDOFF updates are committed as follow-up docs commits.
### Rationale
Docs-only paths never force the suites, and the alternative (gitignoring the partner's requested tracking folder) hides the record.
### Consequences
The release payload ships `docs/instants/`. Harmless; it is documentation.

## D-3 — Rebase resolutions: dialog markers stay in session.py; selftest timeout 600 s   (2026-09-14, SUPERSEDED in part by D-4 2026-09-14 — the dialog-marker half; the 600 s half stays ACTIVE)
### Context
Live added `_DIALOG_MARKERS`/`asking()`/pane-guard code 15 (I-16) in `session.py`; the branch moved Claude's busy/watcher/status-line markers into `runtime.py`. Live's `run-group5.sh` introduced a per-verb `m_timeout` (selftest 300 s); the branch had raised the flat timeout to 600 s after measuring 180 s under load with 1,849 tests.
### Decision
Keep `asking()` and `_DIALOG_MARKERS` in `session.py` (unchanged from live), do not fold dialog detection into `runtime.observe` during the rebase. Keep live's `m_timeout` structure and set selftest to 600 s.
### Rationale
Minimal, behaviour-preserving resolution: code 15 keeps working for Claude exactly as on live; Codex frames never match the AskUserQuestion strings, so nothing changes for Codex. Whether dialog detection belongs inside the runtime boundary is a review question, not a rebase question. 600 s keeps live's per-verb shape while honouring the branch's measurement.
### Consequences
`runtime.observe` still has its own coarse "dialog" detection (`esc to cancel` in the 8-row tail) that live's SI-37 note warns is a false-positive source; carried to review round 1 as a question for the reviewers' findings.

## D-4 — Every positively identified operator dialog is pane-guard `15` on either runtime   (2026-09-14, ACTIVE)
### Context
Live's I-16 defined `15 awaiting-operator` for Claude's `AskUserQuestion` dialog; the branch mapped any `dialog` observation to `14 indeterminate` ahead of that check, so after the rebase a dialog answered "wait and re-poll" where live had ruled "no amount of waiting clears this". The trust modal was `10` on live (its selected row has a caret) and `dialog` on the branch.
### Decision
`runtime.observe` recognises three measured dialog rows (Claude trust modal, Claude AskUserQuestion, Codex approval prompt), each matched as a row that begins with its first fragment and carries the rest, inside the input-box window. `pane-guard` and `close` map `dialog` → `15`, `unknown` → `14`. `SessionLayer.asking` delegates to `observe` — one predicate.
### Rationale
The advice is identical for all three shapes ("go answer the pane"), and a row-start anchor is what separates the TUI's hint line from prose quoting the same words. Superseding the trust modal's `10` with `15` says the true thing ("blocked on a human") instead of "somebody typed something".
### Consequences
`coordinating-instants`' can-go set (`0`, `12`, `13`) is unchanged. Skills updated (`using-fleet`, `harvesting-an-instant`). Reconcile still reads BLOCKED for both.

## D-5 — Launch verbs wait 60 s for the admission lock; `runtime --set` keeps the 5 s refusal; switch blockers are attributable sessions only   (2026-09-14, ACTIVE)
### Context
A dispatch holds the admission lock through executable resolution, the tmux start and the seed-delivery poll (up to 5 s); a second concurrent dispatch lost a 5 s race and exited 4 with a lock refusal unrelated to capacity — the shape the E1 integration case had been rewritten to tolerate. Separately `runtime_blockers` treated every live agent under `<root>` as a blocker, which forbade a switch whenever any interactive session ran anywhere under the root.
### Decision
`ADMISSION_WAIT_S = 60` for dispatch/resume/revive; `runtime --set` keeps `admission_lock`'s 5 s default. A live agent blocks a switch only if its tmux name is an unharvested record's, or its cwd is inside an enrolled slot or the instants dir; an unreadable `/proc` entry blocks (cannot be placed) but no longer raises for the read verbs.
### Rationale
The spec's "bounded refusal on a slow holder" is about the switch, not about launches refusing each other; "foreign fleets never block" read one level closer means the root prefix is too wide.
### Consequences
E1's tolerance of the named lock refusal stays valid but should no longer trigger. Alternative not taken: releasing the lock right after the record write — a larger restructure of `main()`'s lock scope for the same effect.

## D-6 — Release as fleet 0.6.0 (minor), verified with the full roster   (2026-09-14, ACTIVE)
### Context
The change adds three verbs, a saved runtime setting, and `runtime` fields on dispatch records that an older fleet binary cannot read (the spec documents the compatibility limit). `releasing-fleet` says patch for the ordinary and that a minor bump requires `--full` (every IT runner except §P) and can never be EXEMPT. The full roster adds §F, §G, §H, §I, §J, §O and the lineage gate over the default 17; their last tracked verdicts on live are all PASS.
### Decision
Cut `0.6.0` from `live` after fast-forwarding it to the rebased tip; run `scripts/release-gate.sh 0.6.0 --full`. Before cutting, run the seven extra runners on the rebased tip with scratch `IT_RESULTS` so a pre-existing failure there is known before an hour-long gate is spent.
### Rationale
A record-schema compatibility break is not "ordinary"; the wider roster is what a change touching dispatch, close, harvest, peers, reconcile and seedcheck deserves, and the version number tells the operator of the second root that the fleet binary must be updated in step.
### Consequences
Gate time above the ~45-minute default (budget ~1 h+). If the gate comes back RED for a reason unrelated to this change, the fallback is Trap 9: fix, cut `0.6.1`, never re-verify the same tag.

## D-7 — Run §P once on the deployed tip rather than sanction its skip   (2026-09-14, ACTIVE)
### Context
AC-3 requires §P when a skill or a verb a skill names changes (`fleet/CLAUDE.md`'s rule); seven skill files and `run-P.sh` itself changed (RV-10, RV-28), and the release gate skips §P by design (`FLEET_IT_ALLOW_CLAUDE`). Scope OUT excluded paid live-model runs "unless a review finding demands it"; the workspace review (R3) demanded it.
### Decision
Run `run-P.sh` once on the deployed tip with scratch `IT_RESULTS`; file its register, log, config-dir record and the worker's own report under `evidence/P-0.6.0/`.
### Rationale
A `run-P.sh` fix that has never executed is not a fix; one real dispatch costs minutes and answers it. The release was already deployed, so this validates, it does not gate.
### Consequences
P1-P4 PASS at 22:04 UTC; the real CLI resolved `/home/ubuntu/davis_root/.claude` (INDEX #11). The worker report's "what was wrong" section is the actual deliverable of §P and is filed for the next skill round; it was not acted on in this instant.
