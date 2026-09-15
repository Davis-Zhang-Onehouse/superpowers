# fleet — changelog

## fleet/v0.6.2 — 2026-09-15T22:22:02Z
Cut from becc426 on `live` (upstream base snapshot/2026-08-17-221146). 22 commit(s) since fleet/v0.6.1.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (11 files), skills (14 files), commands (1 file), docs (67 files).
Skills changed: harvesting-an-instant, maintain-workspace, receiving-workspace-review, reviewing-workspace, working-as-a-dispatched-instant.

- 86b12d3 docs: instant 09141935-09150009 complete — fleet 0.6.1 released (revive every dead pane, either runtime, from the root)
- ec3b19b design: workspace review that converges — hunt once, receive with discipline, close by rule
- 93c8173 plan: workspace review convergence — nine tasks, RED/GREEN for both skills, advisory-only fleet change
- b2db3e0 plan: the fixture harness reports 23 cases so the stated 22 is a real claim defect
- 15be907 fleet: six real review ledgers reduced as calibration fixtures
- 8ac3506 fleet review: head epochs and the oscillation streak, calibrated on six real ledgers
- 3f4f1f6 fleet review: OSCILLATING and RECEIVE advisories — the tool names the pattern, the skill owns the call
- ab045a4 receiving-workspace-review: RED baseline — the fix pass without the skill
- bda32f6 receiving-workspace-review: RED v2 — the fix pass under a real-shaped batch
- c1204f6 receiving-workspace-review: the fix pass that does not seed the next round (RED/GREEN evidence attached)
- b152bee receiving-workspace-review: make closed-by satisfiable at write time, score the instrument rule honestly, and commit the fixture artifacts
- a4dc56a reviewing-workspace: closure reviewer — verifies closure, reviews the fix delta, never hunts
- d1ce7d5 reviewing-workspace: closure reviewer — carve the audit trail out of the withdrawals grep, make the control check a diff, and give routed rows a verdict the orchestrator can record
- 206a3f9 receiving-workspace-review + closure reviewer: a negative control is run after the commit that carries its gate, and the closure check names the files it ran
- f948dc0 reviewing-workspace: hunt once at a frozen tip, receive, close by rule
- e811c1e design: the advisories print on fleet review, not fleet brief
- 843f877 reviewing-workspace: per-lens scopes, round verdicts, and the receive route for register findings
- 07923bd skills: point maintain-workspace, the worker and the harvester at the hunt/receive/closure loop
- a5a3e98 worker: a hunt is one review call per lens, and routed is in the status domain
- aa4a48c review: name the epoch semantics and pin the OSCILLATING boundary at three
- 3515152 review skills: a closure closes what the pass acted on, under the scope the hunt covered
- becc426 closure reviewer: scope the triage check by what the pass recorded, not by what the table lists

## fleet/v0.6.1 — 2026-09-15T00:48:06Z
Cut from ce7a866 on `live` (upstream base snapshot/2026-08-17-221146). 5 commit(s) since fleet/v0.6.0.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: skills (1 file), scripts (3 files), docs (80 files).
Skills changed: reviving-dead-panes.

- 350a661 docs: instant 00000000-09141935 complete — fleet 0.6.0 released (runtime selection)
- 6609648 reviving-dead-panes: one root-scoped script revives every DEAD record on either runtime
- 96a29bb review round 1: the whole seed among the first five user blocks, last-written tiebreak, one transcript per record
- c88cf04 review round 2: a matcher traceback is never read as an undelivered seed; a write-time tie refuses
- ce7a866 docs: instant 09141935-09150009 — revive-all dead panes: design, two review rounds, evidence

## fleet/v0.6.0 — 2026-09-14T21:11:51Z
Cut from e753110 on `live` (upstream base snapshot/2026-08-17-221146). 14 commit(s) since fleet/v0.5.12.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (52 files), skills (7 files), hooks (2 files), scripts (8 files), tests (3 files), docs (237 files).
Skills changed: coordinating-instants, dispatching-a-wave, harvesting-an-instant, reviving-dead-panes, using-fleet, working-as-a-dispatched-instant.

- 9056c70 fix: release-gate.sh passes --repo through, and locates the earlier attempt honestly
- f15b585 fix: --reap's name-pattern refusal counts as a reap failure
- 9f55aa1 feat: bootstrap fleet skills in Codex sessions
- 4de441c feat: select Claude or Codex for fleet runs
- 6cbeaf0 fix: preserve worker terminal attributes for fleet guards
- af38887 test: verify native fleet lifecycles and handle exited workers
- c185b72 fix: pin fleet commands and observe terminal redraws
- eb7bfa4 fix: refuse inaccessible tmux before leasing a worker
- ef0ef84 test: verify bounded fleet admission and record runtime evidence
- 8c421c1 review round 1: reconcile the skills with live's pane-guard 15, and fix the docs findings
- 26aa9ae review round 1: one measured dialog predicate, code 15 on either runtime, and the census/lock/messaging findings
- b871a41 review round 2: the Codex directory-trust screen is a measured dialog, and one dialog ordering on both guard paths
- 384bb32 it: J1 declares done before completing; O4's baseline includes the admission-lock inode
- e753110 docs: instant 00000000-09141935 — review, rebase and release of fleet runtime selection

## fleet/v0.5.12 — 2026-09-13T18:34:17Z
Cut from 0eac6da on `live` (upstream base snapshot/2026-08-17-221146). 22 commit(s) since fleet/v0.5.11.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (8 files), skills (1 file), scripts (6 files), docs (2 files).
Skills changed: releasing-fleet.

- ee98590 spec: mechanise the fleet release traps that still cost a run on 0.5.9-0.5.11
- a4caa42 plan: fleet release mechanisation, 7 tasks
- 629c9b7 fix: the exemption stripper must match what the cut's stamper writes
- 69ff32e fix: bound the unquoted branch of _VERSION_FIELD like the stamper does
- 3c4e780 feat: scripts/release-gate.sh — launch the gate detached, unpiped, and wait on the verdict
- 548e40e fix: release-verify --dry-run reports the exemption decision it already computes
- 01c5072 feat: scripts/release-preflight.sh — box quietness through the derived socket, and an orphan reaper
- fe81000 fix: scripts/release-gate.sh — stop leaking $1 into fleet-env.sh, and give the wait loop a poll seam
- 0ad3099 fix: release-verify --dry-run must not fabricate would-run over a refusal it swallowed
- 7bdf678 fix: release-preflight --reap must verify removal before claiming reaped
- 12e853d feat: release-list carries each release's verdict
- 999bab3 feat: release-cut warns when the box has live fleet work
- 9148323 feat: scripts/release-postflight.sh — prove the deployment reached every root
- aea915e fix: release-postflight.sh — drop the PyYAML import, match release_stamp.py's textual read
- ff221c0 docs: point each mechanised trap at the script that now enforces it
- 7efb313 fix: release-gate.sh must wait for THIS run's verdict, not a previous attempt's
- c834f27 fix: changed_paths must name BOTH sides of a rename, or EXEMPT skips real code removal
- 3814fe4 fix: release-postflight.sh must not let an assertion pass by asserting nothing
- fa67324 test: guard the multiplicity `_VERSION_FIELD` cannot see, and state the mechanism that makes it safe
- 2360250 fix: --reap must refuse a symlink orphan, and must not prune after a partial failure
- e3ce31f fix: a failed `git show` must answer "run the suites", not "exempt"
- 0eac6da docs: fleet/CLAUDE.md — the gate waits for THIS run's verdict

## fleet/v0.5.11 — 2026-09-13T15:41:51Z
Cut from de0ccd9 on `live` (upstream base snapshot/2026-08-17-221146). 1 commit(s) since fleet/v0.5.10.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: skills (1 file).
Skills changed: releasing-fleet.

- de0ccd9 releasing-fleet: the four things that cost a gate run on 0.5.9/0.5.10

## fleet/v0.5.10 — 2026-09-13T06:22:50Z
Cut from 65f2d4e on `live` (upstream base snapshot/2026-08-17-221146). 1 commit(s) since fleet/v0.5.9.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (2 files).

- 65f2d4e fix: restore B13's first-tick id announcement; widen selftest's harness timeout (gate RED)

## fleet/v0.5.9 — 2026-09-13T03:37:19Z
Cut from 93b685a on `live` (upstream base snapshot/2026-08-17-221146). 18 commit(s) since fleet/v0.5.8.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (10 files), skills (3 files), docs (4 files).
Skills changed: coordinating-instants, harvesting-an-instant, using-fleet.

- 31f2c2b docs: specify fleet runtime selection for Claude and Codex
- 72f4701 docs: land the fleet runtime selection plan and mark its spec approved
- b9a586b Design: the 0.5.8 dogfooding issue batch, seven fixes and six sanctions
- 86e9a62 Plan: the 0.5.8 issue batch, eight tasks
- 41ed7e4 harvest: a first tick's count reads as a population, not a surge (I-25)
- a4029e4 harvest: registration resolves a bare base id to an absolute register path (I-18, I-9)
- fe040a1 dispatch: --dry-run catches an undeclared placeholder, not the real dispatch (I-24c)
- 29ef78f dispatch: fix review findings on the F3 dry-run placeholder check
- b461c79 abort: a refused slot release names the partial state and the re-run that completes it (I-27)
- 882927f apply: say so when the milestone's worker session is still alive (I-10)
- 661d943 pane-guard: a pane blocked at a selection dialog is not a quiet pane (I-16)
- bde54e2 pane-guard: --capture preserves the evidence behind a verdict (I-21, I-26); close refuses a pane awaiting an operator (I-16)
- cb959ab pane-guard: review fixes for --capture (I-21, I-26) -- guard the write, cover code 14
- 837bf12 the 0.5.8 rulings: --retire, --base and init say their grammar out loud (I-24a, I-24b, I-1, I-26)
- 83d1456 fix: scope the --base path hint to base/curr, not any path-shaped value (review)
- 16c0ab4 it/run-P.sh: accept pane-guard 15 in P1/P2, stop-and-report it in P4
- d3dc809 fix pane-guard code-set docs/comments now stale after code 15 landed
- 93b685a CLAUDE.md: say what J8 actually proves; carry the unbuilt §O case in the spec

## fleet/v0.5.8 — 2026-09-09T01:35:04Z
Cut from df52db1 on `live` (upstream base snapshot/2026-08-17-221146). 2 commit(s) since fleet/v0.5.7.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: skills (5 files).
Skills changed: reviewing-workspace.

- 8030f59 reviewing-workspace: stop routing hand-written SHAs into REVIEW.md
- df52db1 reviewing-workspace: the reviewers record findings through the ledger too

## fleet/v0.5.7 — 2026-09-08T23:22:29Z
Cut from eddd027 on `live` (upstream base snapshot/2026-08-17-221146). 1 commit(s) since fleet/v0.5.6.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (2 files).

- eddd027 it: fix 0.5.6 gate RED — K7 stale awaiting-ci, M9 mut3/mut4 injector crash

## fleet/v0.5.6 — 2026-09-08T22:13:47Z
Cut from 5dae469 on `live` (upstream base snapshot/2026-08-17-221146). 24 commit(s) since fleet/v0.5.5.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (13 files), skills (7 files), scripts (1 file), docs (2 files).
Skills changed: requesting-code-review, reviewing-workspace, reviving-dead-panes, subagent-driven-development, working-as-a-dispatched-instant.

- 48cf965 reviving-dead-panes: fix the fleet_peek advice testing proved wrong
- 129cdf1 Design: dispatch wave efficiency, from the five-instant friction audit
- 10d4ff8 Plan: dispatch wave efficiency, 16 tasks across three lanes
- 7941f81 plan: point at the pre-flight corrections; baseline is 1706 tests
- e1e98f5 workspace: heads() snapshots each repo's HEAD, omitting what it cannot read
- 7cc47f3 review: a round records the repo HEADs it reviewed; absent stays NOT MEASURED
- 6cde101 review: bind each recorded round to the slot HEADs it reviewed
- 4a4a127 propose: refuse --status done on a head no review round has seen
- 6886a8f declare: awaiting-ci reports whether a review round has seen this head
- 5b8ffab declare: a legacy ledger reads as could-not-determine, never as unreviewed
- ad0704c review: a routed finding names its owner and does not block this worker's gate
- 475b2ae complete: refuse to rename out from under this instant's own pointers
- 4b684c7 layout: seed the register header the workspace reviewer enforces
- 105f741 reconcile: re-observe the watcher and flag a stale awaiting-ci (i45)
- 33a1cb6 reconcile: the float clock and a malformed stamp are both covered
- 1998fcb it: §RH proves the round-to-head binding across a real commit
- 1ca46b1 dispatched-instant: close-out contract, scratch rule, and two measured watcher traps
- b3fb438 sdd: end the turn instead of polling; an implementer never waits on a Monitor
- 6d2dcca sdd: the no-Monitor rule rides in the implementer template, where it can be read
- 8170c74 review skills: narrative has a durable home; comment-only findings ride, never re-push
- 07e1e19 reviewing-workspace: every finding path now goes through the ledger, not the view
- 155c79b reviewing-workspace: the REVIEW.md template stops calling itself an append-only ledger
- bc99aeb dispatch: the seed's native-rebuild note defers to the charter's slot note
- 5dae469 Fix wave: unmeasured repo read as moved head, complete refuses a mandated HANDOFF row

## fleet/v0.5.5 — 2026-09-07T15:04:41Z
Cut from 79e61e0 on `live` (upstream base snapshot/2026-08-17-221146). 1 commit(s) since fleet/v0.5.4.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (3 files), skills (1 file), scripts (1 file), docs (1 file).
Skills changed: reviving-dead-panes.

- 79e61e0 pane-guard follows the record too; revive-dead-panes rebuilt on 0.5.x

## fleet/v0.5.4 — 2026-09-07T05:44:32Z
Cut from c5c6ecf on `live` (upstream base snapshot/2026-08-17-221146). 1 commit(s) since fleet/v0.5.3.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (4 files), docs (1 file).

- c5c6ecf SI-59: follow the address the record carries, for reads and for writes

## fleet/v0.5.3 — 2026-09-06T17:17:06Z
Cut from f535cfb on `live` (upstream base snapshot/2026-08-17-221146). 4 commit(s) since fleet/v0.5.2.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (13 files), skills (1 file), scripts (2 files), docs (1 file).
Skills changed: using-fleet.

- ccbde10 register: SI-57 and SI-58, both found while provisioning the second root
- 09df8a3 SI-57: a cd between roots no longer keeps the first root's store and socket
- 787fcbe fleet root-init: make a directory a fleet root, under $HOME and nowhere else
- f535cfb SI-59: a record names its tmux server, and no verb acts across servers

## fleet/v0.5.2 — 2026-09-06T06:03:15Z
Cut from 0073be5 on `live` (upstream base snapshot/2026-08-17-221146). 1 commit(s) since fleet/v0.5.1.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (1 file), docs (1 file).

- 0073be5 M9: import the hermetic registry as a package member, not a loose module

## fleet/v0.5.1 — 2026-09-06T05:12:04Z
Cut from 53d7dbf on `live` (upstream base snapshot/2026-08-17-221146). 1 commit(s) since fleet/v0.5.0.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (9 files), docs (1 file).

- 53d7dbf SI-56: an exported store does not say where instants go, and the suite stops reading the operator's shell

## fleet/v0.5.0 — 2026-09-06T04:04:29Z
Cut from 0500c7a on `live` (upstream base snapshot/2026-08-17-221146). 6 commit(s) since fleet/v0.4.0.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (9 files), skills (1 file), docs (1 file).
Skills changed: using-fleet.

- cf39f6c docs: the six SI items the coordinator's register earned, written down
- f3b92ba abort: give the milestone back, and open a door for the ones already stranded
- 3a402e5 seedcheck: only the worker can be the source of a delivered briefing
- 679a80a dispatch --seed-extra, and pane-guard keyed the way every other verb is
- da071a2 seed-check: a positive channel for a delivery that leaves no argv
- 0500c7a it: §S, the SI-51..SI-55 batch, run RED against 0.4.0 first

## fleet/v0.4.0 — 2026-09-06T02:55:29Z
Cut from 6759d19 on `live` (upstream base snapshot/2026-08-17-221146). 36 commit(s) since fleet/v0.3.18.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (28 files), skills (24 files), scripts (12 files), tests (21 files), docs (5 files), other (1 file).
Skills changed: auditing-a-dispatch-history, coordinating-instants, dispatchInstants, dispatching-a-wave, harvesting-an-instant, integrating-a-pr-stack, maintaining-a-roadmap, running-a-stacked-effort, using-fleet, working-as-a-dispatched-instant.

- fa36305 docs: a standing register for the infra fleet skills have to work around
- 3155125 docs: two more infra gaps, both measured while verifying the wave routine
- 425303a docs: SI-47 — the roadmap prints every row except the ready ones
- 28be6b0 docs: SI-48 — apply silently regresses a done milestone, cascade and all
- 3885813 docs: design for six coordinator routine skills
- cb727d7 docs: implementation plan for the six coordinator routine skills
- 19233dd skills: running-a-stacked-effort, the coordinator's project arc
- 8001acb skills: dispatching-a-wave, k workers onto one shared base
- 1e07ff1 skills: prove the wave sequence runs, and pin SI-47 while it is open
- 2c594e6 skills: integrating-a-pr-stack, siblings into one chain with the pins
- dfa0c15 skills: harvesting-an-instant, close out and carry the knowledge up
- 59acd82 skills: pin the SI-48 apply-regression hazard the harvest skill warns about
- 96d5816 skills: maintaining-a-roadmap, keep the registry exactly as wide as the truth
- 58d03d9 skills: auditing-a-dispatch-history, both directions of the trail
- d7f2554 coordinating-instants: route to the six routine skills
- 4374b92 docs: mark the coordinator-skills plan executed, with its deviation and corrections
- e21c0b0 regression-trap: quote 'done' so shellcheck stops reading it as a loop keyword
- d9932ac test-render-graphs: report a missing Graphviz as SKIP, not as five failures
- ef3d547 lint-skill: reach references/, and stop matching the word "cannot" as a claim
- e5fa55a lint-shell: take the repo baseline from 79 findings to zero
- 85427cd docs: design for per-root fleet isolation, discovered by a marker walk
- 50200bf docs: implementation plan for per-root fleet isolation
- e76cadc root: a fleet is a directory, found by walking up to its marker
- e903b85 cli: resolve home, socket and releases through the root, and refuse rather than default
- 7d49110 releases: derive the release area from the root, replacing a phantom default
- 163c9f0 dispatch: a record names its root, and may not point outside it
- dfac6b3 it: two roots side by side, and the guards that keep them apart
- 0d6e5f4 consumers: derive the root instead of naming davis_root as a constant
- 7397850 migrate: move the box-wide store into davis_root and mark both roots
- 08094fa cli: share the foreign-root guard, and keep it out of the swallowing except
- 98061d1 docs: correct the spec where the implementation refuted it, and record the deviations
- 7941ac1 docs: the read-only default is gone, and two files still promised it
- 9f1cd86 guards: a root constrains its OWN store, not every store named from inside it
- d6e6e9d cli: the resolved-root line is banner content, so --porcelain suppresses it
- 988cdb5 it: §R belongs in the default roster, and RESULTS.tsv records the full run
- 6759d19 fleet 0.4.0

## fleet/v0.3.18 — 2026-09-05T16:56:55Z
Cut from e1af9a6 on `live` (upstream base snapshot/2026-08-17-221146). 1 commit(s) since fleet/v0.3.17.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (16 files), skills (2 files).
Skills changed: using-fleet.

- e1af9a6 profiles: the awaiting-ci clause taught a command `parse` refuses

## fleet/v0.3.17 — 2026-08-27T20:46:17Z
Cut from b4c66cf on `live` (upstream base snapshot/2026-08-17-221146). 2 commit(s) since fleet/v0.3.16.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: skills (3 files).
Skills changed: maintain-workspace, reviving-dead-panes.

- 75ee3b4 skills: reviving a dead pane had no procedure, and every session on the box died at once
- b4c66cf maintain-workspace: drop the first-3-raw-prompts capture from CHARTER

## fleet/v0.3.16 — 2026-08-17T22:12:48Z
Cut from 3845d27 on `live` (upstream base snapshot/2026-08-17-221146). 19 commit(s) since fleet/v0.3.15.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (3 files), skills (13 files), plugin-manifests (1 file), scripts (5 files), tests (10 files), docs (6 files), other (2 files).
Skills changed: brainstorming, finishing-a-development-branch, requesting-code-review, subagent-driven-development, using-superpowers, writing-plans, writing-skills.

> fleet/v0.3.15 is no longer an ancestor of `live` — an upstream rebase rewrote the commits between. This delta was computed by patch-id, not by ancestry.

- 44c9b2d docs: remove the "We're Hiring" section from the README
- b36e082 Release v6.3.0: Devin CLI and Hermes Agent support, brainstorming three-path router, SDD/Codex efficiency fixes (#2125)
- 287c51f import fleet into this repo: the coordination infrastructure the new skills are built on
- e0581a7 fleet fixture: archive the dummy-project repos, and stop baking an absolute path into facts.env
- 4f56d8a harness: establish box-local baselines on first run, and give §H a virgin store
- a02be37 the four fleet skills, each carrying tests that prove its factual claims
- 1582e13 IT sweep complete in the new home: 221 PASS / 0 FAIL across every runner
- 693f95a fleet v0.3.8
- 218bd6f fleet v0.3.9
- 11e4a15 fleet v0.3.10
- dfa0ff5 it: §i7's rows never reached the closeout register, and the pins dirty every cut
- 15e917b fleet v0.3.11
- 2d31536 fleet+it: a named destination is whole, and the isolation check can see the instants directory
- f553fab fleet v0.3.12
- 639b79f fleet v0.3.13
- 1c08983 fleet v0.3.14
- 4ef1781 fleet v0.3.15
- 54d023f sync: the refresh ran from the worktree it had just deleted, and a merge on live replayed itself
- 3845d27 release-cut: upstream 6.3.0 brought a YAML manifest, and the stamp only knew JSON

## fleet/v0.3.15 — 2026-08-09T17:54:24Z
Cut from 16fa45c on `live` (upstream base pre-merge-fleet-skills-20260731). 4 commit(s) since fleet/v0.3.14.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (6 files), skills (3 files).
Skills changed: coordinating-instants, using-fleet, working-as-a-dispatched-instant.

- f026ef2 tests: behavioural coverage for `fleet peers`, so its gate is not a folder nobody runs
- d6a00ac peers: close the fail-open review round 3 found, and lock every fix with an assertion
- 9cdc31a peers: escape control characters by CATEGORY, and stop a vacuous ancestry test
- 16fa45c fleet declare: awaiting-ci refuses when nothing is armed to wake the claimant

## fleet/v0.3.14 — 2026-08-08T22:13:03Z
Cut from f40676b on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.3.13.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (1 file).

- f40676b it: give `peers` an argv recipe in L7 and M5, and stub its claude call

## fleet/v0.3.13 — 2026-08-08T21:22:34Z
Cut from 40a1013 on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.3.12.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (4 files), skills (1 file).
Skills changed: using-fleet.

- 40a1013 fleet peers: a mechanical provenance whitelist for cross-session messaging

## fleet/v0.3.12 — 2026-08-08T06:43:42Z
Cut from 2b55013 on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.3.11.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (4 files), other (1 file).

- 2b55013 fleet+it: a named destination is whole, and the isolation check can see the instants directory

## fleet/v0.3.11 — 2026-08-08T04:17:35Z
Cut from fba0038 on `live` (upstream base pre-merge-fleet-skills-20260731). 4 commit(s) since fleet/v0.3.10.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (12 files), skills (1 file), other (1 file).
Skills changed: releasing-fleet.

- 07b07bc it: the dispatch-kill narrowing must be structural, not a source-text prefix
- e2f5fda session: the pane capture must keep the attribute that says who typed the text
- 2912184 it: §i7's rows never reached the closeout register, and the pins dirty every cut
- fba0038 skills: an IT run dirties the tree, and the pre-cut step must be written down

## fleet/v0.3.10 — 2026-08-07T23:25:03Z
Cut from 0df31d2 on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.3.9.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (1 file).

- 0df31d2 it: seed-check needs an argv recipe, or §L7 and §M5 say nothing about it

## fleet/v0.3.9 — 2026-08-07T22:08:46Z
Cut from 84355ef on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.3.8.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (6 files), skills (1 file).
Skills changed: using-fleet.

- 84355ef fleet: dispatch asserts the seed it rendered is the seed that was delivered

## fleet/v0.3.8 — 2026-08-06T15:01:17Z
Cut from 6626405 on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.3.7.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (10 files), skills (1 file).
Skills changed: releasing-fleet.

- 6626405 fleet: the release's evidence, version and payload all describe the release

## fleet/v0.3.7 — 2026-08-06T06:49:18Z
Cut from b8dc466 on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.3.6.

- b8dc466 fleet: the exemption was unreachable — release-cut's own stamp is in every diff

## fleet/v0.3.6 — 2026-08-06T06:41:24Z
Cut from 10147f1 on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.3.5.

- 10147f1 docs: record the exemption design's outcome and the gate fix it forced

## fleet/v0.3.5 — 2026-08-06T06:13:23Z
Cut from 926fcdd on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.3.4.

- 926fcdd it: a claude-count check must attribute an addition, not just detect one

## fleet/v0.3.4 — 2026-08-06T05:11:24Z
Cut from 9833dd9 on `live` (upstream base pre-merge-fleet-skills-20260731). 3 commit(s) since fleet/v0.3.3.

- 54d1eb5 docs: design for release test exemption
- 0368435 fleet: a release that changes nothing the suites read is EXEMPT, not forced
- 9833dd9 skills: the release chain, and the traps that cost a gate run

## fleet/v0.3.3 — 2026-08-05T04:45:58Z
Cut from 3150f5a on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.3.2.

- 3150f5a fleet: a release drill marker, so v0.3.3 has a delta to carry

## fleet/v0.3.2 — 2026-08-04T20:08:12Z
Cut from 11f2f58 on `live` (upstream base pre-merge-fleet-skills-20260731). 3 commit(s) since fleet/v0.3.1.

- b9b0a08 skills: the close-out has a FIFTH step, and it is a second wait (FI-11)
- d07b4a2 skills: the release pipeline is documented where users look (G-6)
- 11f2f58 fleet: a dep that can NEVER land is actionable, not information

## fleet/v0.3.1 — 2026-08-03T01:32:45Z
Cut from c4a729a on `live` (upstream base pre-merge-fleet-skills-20260731). 4 commit(s) since fleet/v0.3.0.

- c8d44f0 fleet: the profiles fleet ships now pass fleet's own lint (FI-13)
- 11b2d13 fleet: a not-ready milestone's severity follows the REASON (FI-2)
- bd69a7f fleet: the coordinator can retire a superseded milestone (FI-10)
- c4a729a fleet: capture_pane can say it FAILED, fixing FI-7 at the source

## fleet/v0.3.0 — 2026-08-03T01:07:53Z
Cut from d73a528 on `live` (upstream base pre-merge-fleet-skills-20260731). 4 commit(s) since fleet/v0.2.4.

- 8f1323b it: a runner's exit status is a verdict, not a failure count
- 448c663 release: the worktree cleanup unfreezes, and the area keeps 10 releases
- b44891e fleet: one authority on whether a source can be harvested at all (FI-5)
- d73a528 fleet: a failed observation is not a negative one (FI-7)

## fleet/v0.2.4 — 2026-08-02T22:06:08Z
Cut from 4ab0270 on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.2.3.

- 4ab0270 fleet: reap reports the claim it cannot yet judge (E9, both modes)

## fleet/v0.2.3 — 2026-08-02T19:31:09Z
Cut from 8fd20d9 on `live` (upstream base pre-merge-fleet-skills-20260731). 3 commit(s) since fleet/v0.2.2.

- 9767679 fleet: reconcile derives a severity, and a stranded slot is one
- ecae22c release: a release carries the evidence its FAIL rows cite
- 8fd20d9 fleet: the send contract is a condition, not a delay (FI-15 refuted and fixed)

## fleet/v0.2.2 — 2026-08-02T18:45:51Z
Cut from 956d168 on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.2.1.

- 956d168 fleet: a stalled worker is actionable, and a proposal can carry a note

## fleet/v0.2.1 — 2026-08-02T18:14:30Z
Cut from b836240 on `live` (upstream base pre-merge-fleet-skills-20260731). 1 commit(s) since fleet/v0.2.0.

- b836240 it: mutant trees carry tests/, which the II-3 registry import needs

## fleet/v0.2.0 — 2026-08-02T17:50:04Z
Cut from 1944d67 on `live` (upstream base pre-merge-fleet-skills-20260731). 8 commit(s) since fleet/v0.1.1.

- 6f047c5 verify: the IT verdict comes from FAIL rows, not from an exit code
- b7b18a5 it: M9 resolves a call's receiver structurally, not by bare name
- 17b8c83 it: A1's aggregate names the sub-assertions that failed
- 80153b2 it: a missing argv fixture is a coverage gap, not a product defect
- b7c92c5 it: run-all.sh ends with a verdict, and group5 propagates its failures
- b3c9dde it: one implementation of the isolation contract, plus the part it cannot see
- dfb44de it: M9 reads the hermetic registry instead of restating it
- 1944d67 release: verify from a git worktree at the tag, not from the export

## fleet/v0.1.1 — 2026-08-02T08:22:50Z
Cut from f757d00 on `live` (upstream base pre-merge-fleet-skills-20260731). 2 commit(s) since fleet/v0.1.0.

- 7c489c4 plan: repoint the marketplace by file edit, never by the plugin CLI
- f757d00 P-2: pin the source without requiring a git repo it never consults

## fleet/v0.1.0 — 2026-08-02T07:57:30Z
Cut from e87d546 on `live` (upstream base pre-merge-fleet-skills-20260731). Initial release — no predecessor, so no commit range is listed.

