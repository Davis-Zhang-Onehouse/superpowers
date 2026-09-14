# REVIEW — 00000000-09141935-inflight-append-fleetRuntimeRelease

<!-- GENERATED from .fleet/review.json. This file is a VIEW: it is regenerated in full on
     every render, hand edits are discarded, and NOTHING reads it for a control signal.
     Two READY workers were once blocked by a regex over prose exactly like this. -->

**Gate:** ALLOWED (`review-verdict`)

round 2 (scope code) recorded READY-WITH-FIXES at 2026-09-14T21:10:43Z with 0 open blocking findings. population: 2 round(s) [code, code]; scopes covered: code; 32 finding(s), 0 open blocking; ledger /home/ubuntu/davis_root/superpowers/docs/instants/00000000-09141935-inflight-append-fleetRuntimeRelease/.fleet/review.json

## Round 1 — scope `code` — verdict `READY-WITH-FIXES` — 2026-09-14T20:50:20Z

| id | severity | status | location | finding | action |
|---|---|---|---|---|---|
| RV-1 | Critical | applied | fleet/src/fleet/runtime.py observe | dialog detection was a single esc-to-cancel fragment over eight joined rows and fired on ordinary agent prose; send/close/pane-guard then refuse and nothing clears by waiting | per-runtime measured dialog rows anchored to row start inside the input-box window (26aa9ae); regression test test_a_dialog_is_a_measured_row_not_a_quoted_hint |
| RV-2 | Critical | applied | fleet/src/fleet/cli.py _do_pane_guard and _pane_refusal | after the rebase the branch dialog→14 branch shadowed live I-16 code 15; the suite could not see it | dialog→15 awaiting-operator on either runtime, unknown→14; SessionLayer.asking delegates to observe; session._DIALOG_MARKERS folded into runtime.CLAUDE_DIALOG_ROWS (26aa9ae, D-4) |
| RV-3 | Critical | applied | skills/coordinating-instants/SKILL.md ~110 | after the rebase the skill said both use fleet send and no fleet verb sends a pane message | paragraph rewritten — fleet send is the verb; the harness-classifier lesson kept as the reason the substance stays in the file (8c421c1) |
| RV-4 | Important | applied | fleet/src/fleet/cli.py runtime_blockers | any live agent anywhere under the root blocked runtime --set, including an unrelated interactive session | blocks only attributable sessions — a record tmux name, an enrolled slot, the instants dir — plus unreadable rows (26aa9ae, D-5) |
| RV-5 | Important | applied | fleet/src/fleet/session.py list_processes | a PermissionError on /proc/pid/exe raised FleetError for every verb until that process exited | LiveSession.unreadable row, unattributed; blocks a switch, does not blind board/status/close; test_an_unreadable_process_blocks_the_switch_but_not_the_read_verbs |
| RV-6 | Important | applied | fleet/src/fleet/cli.py main admission lock | dispatch held the admission lock through the seed poll with a 5 s contender timeout so concurrent dispatches refused each other | ADMISSION_WAIT_S=60 for admitted verbs; runtime --set keeps the 5 s bounded refusal (D-5) |
| RV-7 | Important | applied | fleet/src/fleet/cli.py _do_dispatch seed failure | free text written into record.gate_verdict, a guard name harvest reads | write removed; rollback message already names the stranded PENDING-LAUNCH record and the abort remedy; asserted in the rollback test |
| RV-8 | Important | applied | fleet/src/fleet/messaging.py send | byte-exact draft compare never matched a soft-wrapped line so every such send ended uncertain | _squash whitespace-normalised compare; test_a_soft_wrapped_draft_is_the_same_message |
| RV-9 | Important | applied | fleet/src/fleet/cli.py _do_pane_guard and _pane_refusal | three to four process censuses per guard decision, read at different instants | one live() snapshot passed to is_agent_process and _is_claude |
| RV-10 | Important | applied | fleet/it/run-P.sh | it_section maps every section to an empty test-ownership config; the one section launching the real CLI resolved to a login screen unless P_CLAUDE_OWNERS_MAP was set | defaults to the resolver map; resolved config dir recorded in P-config-dir.txt |
| RV-11 | Important | applied | fleet/it/fixtures/runtime/manifest.json | every evidence citation pointed at gitignored .private-journal captures and 8 of 10 entries omitted the producing action | source captures tracked under docs/superpowers/specs/evidence/runtime-frames; action per entry |
| RV-12 | Important | applied | fleet/tests/test_cli.py rollback test | asserted only the kill and launched_at; no lease state, no failing-kill path | asserts lease released once the process is gone; new test retains the lease while the process is still observable |
| RV-13 | Important | wont-fix | fleet/it/run-group5.sh m_timeout | 600 s nested-selftest timeout means a real hang costs ten minutes per verb | sanctioned (D-3) — a false timeout costs a whole 45-minute gate run, which is what 65f2d4e paid; the suite is 1,901 tests at 120-180 s |
| RV-14 | Important | applied | docs/README.fleet-runtimes.md 53 | dead link README.codex.md | links README.md#codex-cli |
| RV-15 | Important | applied | fleet/src/fleet/cli.py pane-guard help and code registry comment; seedcheck.py 418 | code 12 still documented as not-claude and the not-found message named claude for a Codex record | help and comment say observed non-agent pane (legacy label); Probes.process_name |
| RV-16 | Important | applied | docs/superpowers/specs/evidence/2026-09-11-fleet-runtime-validation.md 10,19,54 | three measurements cited with no retained artifact | reworded to say the log was not retained and point at the tracked artifact or regression test |
| RV-17 | Important | applied | skills/dispatching-a-wave/SKILL.md step 5 | a still-true fact (nothing lints a placeholder scope, SI-45/SI-46) was deleted with the old mechanism | sentence restored |
| RV-18 | Minor | applied | fleet/it/run-runtime.sh; fleet/it/bin/claude; scripts/fleet-revive.sh; tests/codex/test-marketplace-manifest.sh; file modes | dead socket check; inherited PYTHONPATH and a fixed timestamp in the stand-in; ambient FLEET_ROOT; deleted rationale comment; two files 644 | all applied in 26aa9ae; fork start method pinned in test_runtime_concurrency |
| RV-19 | Minor | applied | skills/reviving-dead-panes/SKILL.md; skills/using-fleet/SKILL.md 82,111; docs/README.fleet-runtimes.md 14 | trap numbering started at 2; legacy send-keys vocabulary; dispatch example omitted the worker flags | renumbered 1-4 with the resume-menu trap scoped to a hand --resume; vocabulary updated; example points at dispatching-a-wave |
| RV-20 | Minor | open | fleet/src/fleet/cli.py _do_runtime dry-run; session.py unused import re; reconcile.py 321 second capture; _watcher_for_claim double _record_for; messaging.validate_message rejects tabs; _do_peers int(pid) before provenance; store.py runtime validated before schema_version | core reviewer minors not taken this round | carried as follow-ups; none changes behaviour a coordinator depends on |
| RV-21 | Minor | open | scripts/fleet-revive.sh transcripts; fleet/it/runtime-checks.py 519; test_runtime_concurrency negative poll windows | mtime hint dropped from transcripts output; per-call timeout uncaught; a negative window passes vacuously if the contender is slow to start | carried as follow-ups |
| RV-22 | Nit | wont-fix | branch commit organisation; evidence paths; coordinating-instants 61 | skill edits spread over four commits; ~945 absolute worktree paths in evidence; one sentence of history says claude process | history is left as delivered; paths are not secrets; harmless |

## Round 2 — scope `code` — verdict `READY-WITH-FIXES` — 2026-09-14T21:10:43Z

| id | severity | status | location | finding | action |
|---|---|---|---|---|---|
| RV-23 | Important | applied | fleet/src/fleet/runtime.py CODEX_DIALOG_ROWS | the Codex directory-trust screen (Press enter to continue) is captured in-tree (coordinator-dispatch/commands.jsonl 22) and the round-1 rows dropped it; a worker parked there read 14 wait instead of 15 | row added; capture promoted to fixtures/runtime/codex-trust.frame with a manifest entry; asserted in test_runtime (b871a41) |
| RV-24 | Important | applied | fleet/src/fleet/cli.py _do_pane_guard and _pane_refusal | the dialog check ran first on the attributed path and last on the glyph path — two orderings for one predicate, and the fixed path was untested | one ordering on both paths, after busy and before unsubmitted; test covers attributed AskUserQuestion, attributed and unattributed trust modal (15) and a busy pane with a stale hint row (11) |
| RV-25 | Minor | applied | fleet/src/fleet/cli.py dispatch rollback retained-lease path | re-raised before the stranded PENDING-LAUNCH sentence, so that operator was told nothing about the record | stranded note computed once and printed on both paths |
| RV-26 | Minor | applied | fleet/tests/test_runtime_cli.py | no regression test for the root-prefix case that motivated the blocker change | test_a_process_elsewhere_under_the_root_does_not_block |
| RV-27 | Minor | open | fleet/src/fleet/reconcile.py 454-462 | an unreadable row lands on the board as UNKNOWN-SESSION with cwd /proc/pid, a placeholder printed as evidence; the unreadable flag also turns live_work_now on | follow-up; fail-safe direction |
| RV-28 | Minor | applied | fleet/it/run-P.sh 114 | duplicated the resolver default map path | unsets CLAUDE_OWNERS_MAP when P_CLAUDE_OWNERS_MAP is empty |
| RV-29 | Minor | applied | skills/coordinating-instants/SKILL.md 61-63; skills/reviving-dead-panes/SKILL.md 96-100 | 15 described narrower than the code; the resume-menu measurement predates the dialog rows | wording widened; measurement dated |
| RV-30 | Minor | applied | fleet/src/fleet/cli.py _do_close docstring | said three refusals while _pane_refusal returns four | reworded |
| RV-31 | Important | applied | fleet/it/run-J.sh J1 | pre-existing on live since 5dae469 — complete refuses a still-declared awaiting-ci phase and J1 never declared done; §J had not run since the 0.5.4 gate (evidence it-RESULTS-live-f15b585-J.tsv) | J1 declares done before completing; §J 11 PASS on the branch |
| RV-32 | Important | applied | fleet/it/run-O.sh O4 | the branch admission lock is a stable inode every admitted verb opens, so a permission-refused resume created it and O4 read the store as changed | lock inode in O4 baseline as §K9 does; §O 13 PASS |

