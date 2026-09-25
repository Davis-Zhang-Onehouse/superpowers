# fleet — changelog

## fleet/v0.6.15 — 2026-09-25T19:47:07Z
Cut from 2caf55e on `stack/0.6.15` (upstream base snapshot/2026-09-22-152849). 1 commit(s) since fleet/v0.6.14.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (2 files).

- 2caf55e S5 fix-up (gate 0.6.14 attempt 1, coordinator D-112): W1's decoy socket is short; M10's busy pane has its input box

## fleet/v0.6.14 — 2026-09-25T15:34:23Z
Cut from d39ee3b on `stack/0.6.14` (upstream base snapshot/2026-09-22-152849). 95 commit(s) since fleet/v0.6.13.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (75 files), skills (4 files), scripts (6 files), docs (1 file).
Skills changed: coordinating-instants, reviving-dead-panes, using-fleet, working-as-a-dispatched-instant.

- 4392426 fleet: _cadence resolves --instant/--from with the verb's own resolver (V23-O, FB-123)
- 793c41f fleet: the cadence walk's ceiling bounds only the ceiling's ancestors (V23-O RV-15)
- e32b62e fleet: _cadence returns before scoping when nothing is overdue (V23-O RV-17)
- b248db4 fleet tests: the contracts fixture runs verbs from its own tree (V23-O RV-14)
- c742c08 fleet tests: one run_from helper that refuses a cwd outside the fixture (V23-O RV-18)
- 98ef0c1 fleet tests: cadence cwd cases inside the fixture chdir for real (V23-O RV-16)
- 8fd27b6 fleet tests: the contracts fixture keeps a cwd already inside its tree (V23-O RV-39)
- 52146a0 fleet tests: the contracts fixture's cwd_ceiling is guarded under any TMPDIR (V23-O RV-38)
- 2dac909 fleet tests: Fleet.run's comment says how cwd cases are modelled now (V23-O RV-40)
- e0138e5 fleet/tests: the hermetic suite never execs a real runtime or reaches a tmux server it did not create (FB-118)
- e1bb4b9 fleet/it: lib.sh strips the caller's $TMUX and its live-session read names -L default (FB-118)
- 4ffb4d6 fleet: close and harvest of a codex worker sweep codex's sandbox mount residue from the store and instants tree (FB-117)
- 85b76d0 fleet/CLAUDE.md: the hermetic suite's host boundary and tripwire (FB-118)
- 5a07aa1 fleet/it: W1-4 and W1-5 prove blindness against a decoy server of their own, not the live one (FB-118)
- 2fe12ff fleet/tests: lib.sh's live-session read names -L default even if a runner re-exports $TMUX (FB-118)
- 4982f87 fleet/tests: a dry-run sweep never promises to remove a real repository (FB-117)
- 77a0b61 fleet/tests: the tripwire resolves a missing TMUX_TMPDIR to /tmp, as tmux does (RV-25)
- 0d963fb fleet/tests: the tripwire parses tmux's clustered short options as getopt does (RV-26)
- 66cb225 fleet/tests: a child reuses the suite's boundary only when it is really there (RV-27)
- 4d642d8 fleet/tests: the box's /tmp/tmux-<uid> is always foreign to the tripwire (RV-28)
- 9fa92e6 fleet/tests: children that run claude or codex by name reach the refusing stub (RV-29)
- 714271c fleet/tests: every test module installs the host boundary, even when run alone (RV-15)
- 97abf65 fleet/tests: the tripwire judges a relative socket path from the callee's cwd (RV-30)
- fc153a9 fleet/tests: a tripwire record written outside a test's run still fails something (RV-31)
- e051a4b fleet/tests: only the process that owns the suite directory tears it down at exit (RV-32)
- b3562ec fleet: the codex residue sweep asks again immediately before each rmdir (RV-33)
- 46284a1 fleet: codex holder detection fails closed on unreadable, nested and respelled cases (RV-34)
- e469dfa fleet: a codex record with no instant path never sweeps the caller's cwd (RV-35)
- 4170075 fleet: close and harvest wait briefly for the killed codex to exit before sweeping (RV-36)
- c85d44e fleet/it: run-w1 starts no decoy tmux unless its directory exists (RV-37)
- 1aed708 fleet/it: the FB-73 guardian kills nothing when its directory is gone (RV-38)
- 1fe0b16 fleet/it: A8a finds tmux kills inside quoted and heredoc code and accepts -S only with a private path (FB-119)
- bbe9412 scripts/tests: release-postflight's no-root case bounds the root walk itself (FB-120a)
- f4df50f scripts/tests: fleet-finished-pids renames the fixture's basename, not the first -inflight- in its path (FB-120b)
- b1e53b5 fleet/it: A8a judges the tmux invocation that kills, not the first tmux on the line (CL-1)
- 6536325 fleet/it: A8a judges -S on the normalised path and refuses an empty socket operand (CL-2)
- 6d3a952 fleet/it: A8a joins an embedded call whose brackets stay open across lines (CL-3)
- 54d7172 fleet/it: W1-5 runs no socketless probe when there is no decoy (CL-4)
- 5825d54 fleet: the post-close codex wait reads holder pids and stops when none is leaving (CL-5)
- c0dd9b7 fleet/tests: the tripwire's prose names /tmp/tmux-<uid> as always foreign (CL-6)
- 2987d50 fleet/CLAUDE.md: state the tripwire's absolute-path limit for child processes (CL-7)
- 0f6990b fleet/tests: a codex alive before the sweep is reported as alive, not as a late arrival (M12)
- c95b7bf fleet/it: A8a judges every kill on a line against the tmux that issues it (CL2-2)
- 442a1b1 fleet/it: A8a judges held text at every reset and at end of file instead of dropping it (CL2-1)
- fc3dde3 fleet/it: A8a never takes a socket operand for the tmux command, and reads clustered options (CL2-3)
- 3574e2e fleet/it: the A8a pass note names no absolute path, so §A stops exiting 1 on every run (CL2-5)
- 84c30a1 fleet/it: revert A8a's multi-line join (CL-3), per coordinator decision D-82
- f1d64ee S5 glue (v23-l x v23-n): the guardian's default-dir cases observe the victim instead of creating it
- fa078de Expose board addresses and preserve parked and nested state
- 0d69d76 Avoid inventing a socket for an unowned process without a pane
- ebe17ef Distinguish missing records from failed directory enumeration
- 41e15b1 RV-E-H1 Preserve foreign record slot holder evidence
- 73c74c9 RV-E-L2 Keep parked note stable across pane activity
- 1f67f9d RV-E-L3 Include progressing parked workers in fleet_running
- 0f8d450 RV-E-L4 Describe pane guard excerpts without width claim
- 71639d4 RV-E-N6a Count progressing parked workers during deploy
- eac08b5 RV-E-N6b Correct pane width comment
- e1d7ed2 RV-E-L3 Correct appended-column test positions and script mode
- e9a6b29 RV-E-N1 Read runtime from declared board column in IT
- 4b5a8cf Disregard an unhandled awaiting-ci attestation made before a relaunch (v2-10)
- 0738fdb Add a reasoned, expiring `holding` phase outside the WIP cap (v3-06c)
- 8fc8df9 Give an awaiting-ci claim a bounded grace after its declaration (v3-06a/b)
- 52391a1 Teach the awaiting-ci grace, fresh-watcher renewal and the holding phase
- 294680c Stamp a declaration from ctx.now, the clock hold_until uses (RV-22)
- 8f27ca7 Bound a hold and the grace where they are read, not only where declared (RV-20)
- 18da0f0 Make brief's phase row say what the board now does with a claim (RV-19)
- b7d8716 Let the V23-G test module run on the base so each case fails on behaviour (RV-12)
- 06def6d Teach the post-revive disregard, the GRACE row and HOLDING to both skills (RV-21)
- 9d16cd4 Give brief the board's own reason when a claim has no grace (CL-1)
- 2fc8a4a Qualify brief's promise that a live hold keeps a worker off the cap (CL-3)
- b6a74fd S5 glue (v23-g x v23-j): grace and holding count as live for COMPLETE-BUT-WORKING; terminal stamps still win
- ff26939 Allow queued sends to empty busy panes and report pane input accurately
- 2d11cd3 Limit capture placeholder labels to the current input box
- 098bd26 Clarify retry and annotated capture contracts
- c3f8893 Report conflicting pane hints as indeterminate
- 76e0afc Fix receive-pass-1 pane safety and delivery reporting
- 35ef5ca Correct stripped-terminal placeholder control for receive pass 1
- ae3a86c Correct empty-busy send doubles in runtime CLI tests
- 8804985 Read plain box text as a draft and refuse a busy claude pane with no caret
- bf103ee Record the Claude Code 2.1.282 frames in the runtime fixture manifest
- 0cd7b7e Read a draft whose first row is blank (RV-18)
- 98a0481 Refuse a claude pane whose input box cannot be located, idle or busy (RV-19)
- 0187987 Read a bordered draft down to its bottom border (RV-20)
- e9a8ad0 Label the claude capture box on the whole draft, as the guard decides (RV-22)
- f55a364 Name the fixture that shows the queued-message chrome (RV-21)
- 6445b7c Say that a send's outcome label reflects the pane at admission (RV-23)
- ce5036e Drop runtime helpers session.py imports but never uses (RV-24)
- aa091ba Name the 2.1.282 frame test by what it asserts (RV-16)
- 93998fe State in using-fleet that an unlocatable input box reads 14 idle or busy (RV-19)
- 4d81093 Scope the unlocatable-box rule in using-fleet to claude panes (RV-26)
- 3469256 S5 fix-up (v23-e doc nit, coordinator D-86): using-fleet says the board's working column carries a busy PARKED worker, not its note
- 989a5cb S5 receive (review RV-H1/H2/H3): a positive control for the guardian observation form; stale comments
- 66c7e37 S5 fix-up (review RV-F1, coordinator D-108): a busy pane that draws the paste late is still submitted
- 80abe79 S5 glue v2 (review RV-S2/RV-S3/RV-H5/RV-H6/RV-H7, coordinator D-108): one predicate for COMPLETE-BUT-WORKING
- d39ee3b S5 receive (delta review RV-D1/D2/D3, coordinator D-108): pin the refusal's launched_at, the live half of the stamped rule, complete's message

## fleet/v0.6.13 — 2026-09-25T09:19:55Z
Cut from 035b6d2 on `fix/rv-c1` (upstream base snapshot/2026-09-22-152849). 1 commit(s) since fleet/v0.6.12.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (2 files).

- 035b6d2 RV-C1 A stamped record with no live session does not resurrect as COMPLETE-BUT-WORKING

## fleet/v0.6.12 — 2026-09-25T05:53:38Z
Cut from 4a8489c on `stack/0.6.12` (upstream base snapshot/2026-09-22-152849). 36 commit(s) since fleet/v0.6.11.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (13 files), skills (2 files), scripts (2 files).
Skills changed: maintaining-a-roadmap, using-fleet.

- 63ef9e7 Stop counting harvested and closed historical records
- c661bcb RV-4 Preserve live evidence over terminal stamps
- 70f9d6d RV-5 Keep closed unfinished work in the cap
- 4d9640f RV-6 Stop harvested compactions blocking dispatch
- b23ea90 RV-7 Display historical terminal states clearly
- 73dca5a FB-121 A folderless harvested record on another server stops counting
- 2c51a86 Keep the IT guardian bound to its runner and socket
- 1aed862 Use namespace-independent guardian test socket names
- 794da82 RV-2 Share guardian generation across harness copies
- 6afd21b RV-3 Refuse guardian arms from subshells
- 0c28e01 RV-4 Verify guardian parent and detach in Python
- b329841 RV-5 Unlink owned default socket fixtures
- b58d666 RV-6 Wait for guardian exit in missing-dir cases
- 5db14ce RV-7a Refuse arm when token publication fails
- 047acaa RV-7b Resolve socket directory at arm time
- 5968d9e Revoke old IT guardian when its runner moves sockets
- a22f220 FB-122a Keep the IT guardian's last arm per socket, not per runner
- 7247ac1 Keep completing workers visible until live work ends
- 2a39002 RV-J1: refuse live complete watcher before close and harvest
- bc96b34 RV-J2: cover claimed milestone with no final report
- a085b64 RV-J3: cover observed watcher, applied report and Codex pane
- 927b200 RV-J4: share worker report selection across complete and harvest
- 591e09c RV-J5: give complete but working a visible fleet-view glyph
- 2dd9d3f RV-J6: name the complete report guard and its clearing command
- ed48d16 v23-j nit: guard the instant-name parse in the live-watcher teardown refusal
- 103c72f Add in-place milestone retitle with row history
- 81e8b18 RV-2 Share milestone title validation
- 76b7faa RV-3 Keep untouched roadmap rows backward readable
- 1a33829 RV-4 Route terminal and mixed milestone refusals
- f59c9f0 RV-5a Pin retire and disown field combinations
- 15e3d57 RV-6 Assert retitle leaves claim and inbox intact
- 096aeeb RV-7 Emit separate milestone history fields
- a76b799 RV-8a Pin normalized retitle reason echo
- 8e29935 RV-5b Document exclusive milestone operations
- 36f0dd7 RV-8b Explain the terminal reopen sequence
- 4a8489c v23-i nit (FB-124): make the terminal-retitle refusal's clearing command pasteable

## fleet/v0.6.11 — 2026-09-25T01:07:03Z
Cut from 829f147 on `stack/0.6.11` (upstream base snapshot/2026-09-22-152849). 45 commit(s) since fleet/v0.6.10.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (21 files), skills (2 files), docs (1 file).
Skills changed: dispatching-a-wave, using-fleet.

- 3cec243 fleet: observe each pane as the runtime of the agent that owns it (v23-k, FB-113)
- 2ea7ff8 fleet: codex spinner with a parenthesised or edge-cut status still reads busy (RV-21)
- 9dddd8f fleet tests: abort and harvest --id refuse a busy codex worker as mid-turn, not as a mismatch (RV-17)
- 195e286 fleet: a record's slot-holder pid is the worker, not its nested child (RV-23)
- 607af25 fleet tests: only tests that pass on the base are named control (RV-26)
- ae45a5d fleet tests: the v23-k module docstring says which tests fail structurally on the base (RV-27)
- d824101 fleet: a codex busy row cut just after its elapsed-time paren reads busy, not unknown (RV-29, S3 stack)
- 0f26972 fleet: key the WIP cap on the effort, not the base string (V23-D, v2-04)
- b16e5eb fleet: keep the compaction rule's record population base-wide (RV-C1)
- b382e01 fleet: a relative instants dir keeps the base-only cap population (RV-C2)
- 4d10da4 fleet: an unplaceable instant path counts instead of crashing the cap (RV-C3)
- 889a1c0 fleet: report foreign same-base claims as set aside too (RV-C4)
- d8bc6a9 fleet: folder: yes whenever the holder's folder is on disk (RV-C5)
- 266073e fleet/tests: pin the F2b holder grep against the bracketed holder text (RV-C6)
- 08c00cd skills: reflow dispatching-a-wave Step 3 and show a bracketed holder (RV-C7)
- e1bc150 fleet: set a foreign worker aside once, not once per record and lease (RV-X1)
- 07479a7 fleet: say which half of the compaction rule is effort-scoped (RV-O1)
- f3a46e6 Resolve instant operands before lookup and parsing
- de2039a RV-4 Restore bare instant name lookup
- 92e8ffd RV-6 Preserve symlinked instants directory paths
- ce741b6 RV-5 Explain both relative instant forms in refusals
- d8a6abc RV-7 Cover relative proposal destination
- 8c3be52 RV-8 Name both operand and parsed instant on grammar refusal
- e1ec4bd Scope cadence notices to the caller effort and collapse duplicate sources
- 0182410 RV-C-1 Preserve cadence alarm for nested and unnamed efforts
- 87afa34 RV-C-2 Make explicit-target exclusion assertion nonvacuous
- 348a291 RV-C-3 Explain relative register omission at notification time
- 17e9802 RV-C-4 Remove unused L7 stale-base export
- 61fef76 RV-C-1 Honor the nearest cwd instant with named directories
- e18642a fleet tests: v23-c's fixture cwd keeps a case's own chdir into its private tree (S3 stack glue, v23-a x v23-c)
- dfd70b0 fleet: dispatch says what it did on stdout, with exit 5 when a launch was rolled back (V23-B)
- 8489228 skills/using-fleet: dispatch's exit 5 not-started, its refused/error rows and title_as_used (V23-B)
- e59723f fleet: a render or slot-settings failure keeps the code its dry-run gives (V23-B, IT D5)
- 0c7eb26 fleet/it: D12 — a real tmux refusal after the claim exits 5 and says so on stdout (V23-B)
- 3509a30 fleet: a non-start's row kind follows the exit code the caller gets (RV-C1)
- febf470 fleet: a non-start's rows are bare values under left_* keys, with the prose in remedy (RV-C6)
- 6ead448 fleet: a rolled-back dispatch names its record as the store holds it (RV-C2)
- f18d52a fleet: a failure inside the dispatch rollback no longer masks the launch error (RV-C4)
- a80cfb3 fleet: an interrupt during the dispatch launch still rolls back, then stays an interrupt (RV-C5)
- 7f29c97 fleet: a dispatch refused by the argument parser prints its error row too (RV-C3)
- 85c9009 fleet: a refusing dry-run prints the same refused rows as its real call (RV-C7)
- dfcb1fa fleet: title_rewritten states camel's whole rule, including the x prefix and todo (RV-C8)
- 025aadb skills/using-fleet: name the non-start's left_* rows, the parser case and SIGINT (RV-C6)
- 14f0fa6 fleet: a flag in the --title position is not reported as the title used (RV-C9)
- 829f147 fleet: left_instant and left_record share one absent sentinel, none (RV-C10)

## fleet/v0.6.10 — 2026-09-24T21:02:21Z
Cut from c20d00b on `stack/0.6.9` (upstream base snapshot/2026-09-22-152849). 1 commit(s) since fleet/v0.6.9.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (1 file).

- c20d00b fleet/it: the FB-73 guardian kills its server as TMUX_TMPDIR=<dir> tmux -L <sock> (A8a, 0.6.9 gate RED)

## fleet/v0.6.9 — 2026-09-24T19:34:40Z
Cut from 66acc21 on `stack/0.6.9` (upstream base snapshot/2026-09-22-152849). 83 commit(s) since fleet/v0.6.8.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (46 files), skills (4 files), scripts (4 files), docs (2 files).
Skills changed: releasing-fleet, reviving-dead-panes, using-fleet, using-superpowers.

- ea9a0a7 fleet: codex_skills — what a CODEX_HOME can see of the superpowers skills, and a link that follows current (FB-111)
- fb66c74 scripts: fleet-codex-skills.sh installs or verifies a root's codex skills link (FB-111)
- dae7e3e fleet: codex_skills reports an unreadable CODEX_HOME as seeing nothing, and refuses a file where skills/ goes
- ad10c2b fleet: refuse a codex dispatch whose CODEX_HOME cannot see the superpowers skills; tell codex workers how to load one (FB-111)
- 194f125 release-postflight: assertion 6 verifies each root's codex skills link; docs and skills say how codex gets skills (FB-111)
- 50db8cb fleet/it: CXS — a real codex worker, dispatched by fleet, finds, reads and follows the superpowers skills (FB-111)
- 397ea1c fleet: final-review fixes for FB-111 — dangling pins, honest dry-run, an override seed that says "not installed"
- 07d69c9 fleet: codex_skills repoints a pin by shape only when it dangles; CXS reads local_shell_call and open(...,'w') writes
- 193a6f1 fleet/it: CXS shows the worker nothing inside the checkout; the RCA phase check accepts "Phases 1 and 2"
- b9a3961 fleet: codex_skills refuses (4) an unreadable or unwritable CODEX_HOME, and its dry run agrees (RV-27)
- 646b0dd fleet: the codex dispatch row and fleet brief say whether the skills follow the deployed current (RV-28)
- 9a3190c skills/releasing-fleet: name the codex refusal window between deploy and install, and say an assertion-6 MISMATCH is not a rollback (RV-20)
- 5e05e8c fleet: fleet-codex-skills.sh refuses a --codex-home that does not exist instead of creating it (RV-29)
- b1a9ff8 fleet: codex_skills repoints only links with the installer's own shape, never an operator's link to a dev checkout (RV-30)
- 52f8ec5 fleet: codex_skills prefers the installer's link over a sibling skills tree when naming skills_root (RV-31)
- 5ce9ef6 fleet/it: CXS keeps a partial verdict and the transcript when a run fails (RV-32)
- a99109a fleet/it: CXS's RCA check no longer accepts the generic phrase "root cause investigation" (RV-33)
- 40244b6 fleet/it: CXS records the fleet revision it drove and whether its own driver was dirty (RV-17)
- 93c1387 fleet/it: SENDC installs the superpowers skills link into its private CODEX_HOME (FB-111 gate)
- fc3db2b fleet/it: the wrapper is an executable, so timeout/env/exec cannot bypass the attribution register (B18)
- 5d4ffa3 fleet/it: every direct python3 -m fleet.cli site goes through bin/it-fleet; W1-13 proves a timeout-shaped mint is attributed (B18)
- 75a43c1 fleet/it: ownership is checked when a row is written, and a section is rewritten in place (FB-37, FB-76)
- ad813aa fleet tests: the repointed-register case expects the unclaimed row to survive
- 0b904e3 fleet/it: it_zero_delta judges the exit code; F10-status reads the todo id it was refusing (FB-38)
- d5749e9 fleet/it: F2b asserts that W1 is named as a holder of the cap, not only that a dispatch was refused (FB-75)
- ffbe721 fleet/it: lib.sh gives every non-interactive runner /dev/null as stdin; J5 pipes its heredoc (FB-99)
- eb30f18 fleet/it: a setsid guardian kills a section's private tmux server when its runner dies (FB-73)
- 9bf42c3 fleet/it: the M9 extractor takes the one anchored block or refuses; a failed injection is a FAIL row (B25)
- 8c05392 fleet: a release's it-RESULTS.tsv marks each row this-run:<runner> or carried-over (FB-81)
- d137208 fleet docs: the harness's controls in bin/ and the register's two new invariants
- 891c833 fleet/it: W1-13 must name the bypass folder in its own row; the wrapper tests compare streams byte for byte (B18, review)
- d74201f fleet/it: the mutation runner leaves SKIP rows for cases an abort never reached; the extractor refuses an unreadable caller (B25, review)
- b6285b6 fleet/it: F2b's holder match stops at the held list; the guardian retires its predecessor; rows insert after the last owned row (review)
- e6f96ca fleet tests: the hermetic harness tests strip $TMUX so their bare tmux calls never reach the live server (review)
- 943160a fleet/it: F9-zero-delta expects the inflight code; the M9 abort helper is defined before use; a targeted B5-B7 run owns all three rows (final review)
- 26d19a9 fleet tests: every tmux socket a harness test touches lives in a private per-process directory (re-review)
- 7529e19 fleet/it: the guardian kills by socket path and is re-armed where a runner moves its tmux directory (RV-34)
- 4486e42 fleet/it: the python-side product calls go through the wrapper too, and the lint sees their shapes (RV-35)
- 2ec62cc fleet/it: the register merge is a tested module, and an OWN- row is dropped only by the run that re-judged it (RV-36)
- 60ffdd0 fleet: a release's it-RESULTS.tsv marks this-run by the whole row, not by case id (RV-37)
- 155b85c fleet/it: F9's subshell hands its failure back to the runner (RV-38)
- 61a9e74 fleet/it: the ownership regex reaches every awk reader through ENVIRON (RV-39)
- d383cc5 fleet/it: the merge reads which sections ran from the runner names, never from row ids (RV-40)
- 4e16838 fleet tests: the merge tests sit above the module main guard (RV-42)
- 140f982 fleet tests: the bypass lint matches the module and launcher forms as tokens; run-Q.sh is exempt by name (RV-41, RV-43)
- d24e9ee fleet/it: stack glue — w2's M9 runner tests read w4's m9_mutations.py and its two abort paths (0.6.9 stack)
- 2db72ae fleet/it: stack glue — the runtime-choice and CXS drivers reach the product through bin/it-fleet (B18 lint, 0.6.9 stack)
- e12716d fleet: launch and revive codex workers with approval=never inside workspace-write (FB-110)
- b0fa5f3 fleet/it: CXP, a real codex worker proves the unattended policy (FB-110)
- 3dddcbf docs, skills: the codex worker policy, its roots, and the sandbox's process blindness (FB-110)
- ef03911 fleet: give a worktree slot's codex worker objects, refs, logs and its own git dir, never the common dir (RV-28)
- 6611e07 fleet: slot contents a codex worker can plant no longer choose its writable roots (RV-29)
- e685263 fleet/it: CXP2, the same escalation request at the base and at the fix (RV-14)
- e2104ac fleet/it: detect the escalation REQUEST in the rollout, with a positive control (RV-30)
- 5c3d087 fleet/it: CXP checks the argv against CODEX_POLICY itself (RV-31)
- 0035ba5 fleet: the codex_policy row says the operator config can add writable roots (RV-33)
- 4c5064a fleet/tests: pin the dispatch --dry-run codex_policy row (RV-36)
- 4f30842 fleet: the 0.156 dialog-row comment cites its update-modal source instead of asserting it (RV-32)
- 204356e skills/using-fleet: do not claim the codex update modal reads 15 (RV-18)
- 52e3fb4 docs, skills: name every census-dependent verb a codex worker might run, declare included (RV-19)
- 0036e9c docs, skills: state the census limit, not a role policy the operator has not ruled on (RV-24)
- 6868105 docs: restore the paragraph break the FB-110 codex paragraph swallowed (noticed in receive pass 1)
- d8451cc fleet/it: say in the CXP runner that the credential copy can rotate the source's refresh token (RV-34)
- 9c50e12 fleet/it: CXP's environment.json records config key names, not the operator's values (RV-35)
- 5365e97 fleet/it: CXP runs on the base tree again after RV-31's import (fix-introduced by 77ec7abc)
- 4198aa3 fleet/it: CXP2 asserts the refused write, not an escalation request codex never offers (fix-introduced by 52752439/866b6c55)
- 18b8cc5 fleet: take a worktree's common dir from its validated path, never from its writable commondir file (RV-37)
- 4e7c642 fleet: a git dir forged inside the slot chooses no codex root (RV-29)
- 4c3081d fleet: every codex git root is resolved, never a symlink, never outside the common dir (RV-38)
- 17ee022 fleet: docstrings stop restating withdrawn claims (RV-41)
- 88b3f46 docs, skills: list all 22 census-reaching verbs, release verbs included (RV-19)
- 1eb625c docs: cite the census method, not a path inside the FB-110 instant (RV-43)
- 5691f1a fleet: shipped comments describe the codex measurements instead of citing instant paths (RV-43)
- 87dee57 fleet: codex workers get no derived git roots, only the store and the instants directory (RV-46, D-51)
- 768a193 fleet: codex dispatch, revive and resume refuse a linked-worktree slot (RV-29, D-51)
- 6cd2d1f fleet/it: CXP runs in a clone-shaped slot and first shows codex refusing a worktree slot (D-51)
- e0cf08b docs, skills: codex workers run only in clone-shaped slots (D-51)
- 077a40c fleet/it: a CXP run finishes on a stable idle pane, not on the model's reply word
- 5affac9 fleet/it: CXP2 no longer requires the model to attempt the out-of-roots write
- cdbc4c1 fleet/tests: the codex policy module docstring states D-51, not the removed git roots (RV-47)
- d1a8434 fleet: the codex worktree-slot check fails closed instead of crashing (RV-52)
- c4e5a09 fleet: the codex worktree-slot refusal names --slot <a clone slot> (RV-53)
- 66acc21 fleet/it: stack glue — the CXP driver reaches the product through bin/it-fleet (B18 lint, 0.6.9 stack)

## fleet/v0.6.8 — 2026-09-24T05:16:15Z
Cut from d7a0529 on `stack/0.6.8` (upstream base snapshot/2026-09-22-152849). 55 commit(s) since fleet/v0.6.7.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (20 files), skills (3 files), scripts (2 files).
Skills changed: using-fleet.

- 81ea088 fleet/it: an M9 mutation that did not apply is NOT-APPLIED, never SURVIVED (FB-108)
- 5fc7741 fleet-revive.sh: report a dry-run refusal by its own sentence, not its route (PT2-I1)
- 3803c32 fleet/it, fleet-revive.sh: close the review's gaps in the applied check and the refusal parse
- d8e0a8c fleet-revive.sh: a refusal with no Type header is reported by its first line, not its usage (RV-18)
- a7dda6a fleet-revive.sh: a header-like message line does not displace the refusal's Type header (RV-19)
- 4045124 fleet-revive.sh: route-only verb output reads (no reason line), not the route twice (RV-23)
- c99910e fleet/it: the M9 copy identity check covers tests/ as well as src/ (RV-21)
- 5c0dcc8 fleet/it: an M9 mutation with no expected kill reason is NO-REASON, never KILLED (RV-22)
- 5002e89 fleet: send confirms a multi-line message through the paste placeholder and records every send (FB-27, B13)
- e516627 fleet/it: §SEND — a real multi-line send is submitted and recorded, on claude and codex panes
- 1b3a010 tests: the three runtime paste tests run — they sat under the __main__ guard, hiding a wrong assertion (RV-37)
- bb87e6a fleet: the delivery verdict wins over the send record — a raising recorder never turns a submitted message into an error (RV-38)
- b2e6916 fleet: read_sends is total — bad bytes, an unreadable log and wrong field types are BadInput, so brief reports a violation row instead of crashing (RV-39)
- 183c9c9 fleet/it: §SEND asserts HOW each send was confirmed — the five-line and over-length rows must say placeholder (RV-21)
- 136e7ae fleet/it: §SEND derives the codex over-length count from the message file, trailing newline included (RV-40)
- 6e9c0ab fleet/it: §SEND does not measure a case whose box the previous failure left full (RV-41)
- 07d5369 fleet/it: §SEND arms its teardown as soon as the fixture slot exists and names a setup step that fails (RV-42)
- 75333e2 fleet/it: §SEND removes its private codex home (a credential copy) at teardown (RV-43)
- bdbf0bb fleet/it: §SEND's record check reports a digest it could not re-derive, and its brief check can fail (RV-44)
- 9d9e35a fleet: send --dry-run emits the same row set as the real send, a confirmation row included (RV-45)
- 60adbe1 fleet: the send record's line count is newline-separated lines, the quantity the placeholder confirms (RV-46)
- 3ffa847 fleet: a single-line claude placeholder confirms as placeholder-uncounted, so the record says how weak it was (RV-47)
- 9368384 fleet: send --by refuses an empty or whitespace-only sender, and the login-user fallback is tested (RV-49)
- 2fd5e66 fleet: the sender identity falls back to FLEET_INSTANT alone, as D-3 documents (RV-30)
- 8a4e3a9 fleet: the sender identity is resolved before the pane is touched (RV-49)
- 47fd105 skills: using-fleet names every send outcome, the plain uncertain one included (RV-48)
- d3cca19 fleet: one enclosure-aware reader for the markdown fleet reads (B19)
- 12ef652 fleet: markdown reader follows CommonMark for comments; an unclosed inline opener is literal (B19)
- 1a7168a fleet: complete's pointer gate and lint's near-miss rule read prose only (B19)
- 2da0974 fleet: recipes_of reads fences through the shared markdown reader (B19)
- 8c47019 skills: lint-skill takes its fence regions from fleet.markdown (B19)
- 6d4b906 fleet: verify executes only recipes it can vouch for; the denylist is the first line, not the only one (B21)
- 36cfd6b fleet: pin the reader's stated limits and the gates' line numbers; lint-skill keeps a package main put on the path (B19 review sweep)
- ebd09ad fleet: verify's vouch rule reads a recipe the way bash does and judges what it used to discard (B21 review)
- 19a2476 fleet: verify's vouch rule decides operators on the quote-preserving token stream (B21 review, round 2)
- d74b58f fleet: verify vouches for a whitelist grammar it parses itself, not for a reading of bash (B21, D-6)
- b148e54 fleet: verify vouches for no glob, no git and no fleet verb that runs things; every argument is checked (B21, D-7)
- bd8fdb5 fleet: verify no longer vouches for fleet verbs; sort -T and file -C are refused (B21, D-8)
- 43b8881 fleet it: G8 pins that a quoted pointer or declaration is not a finding (B19)
- 30f80f9 fleet: verify refuses the shell-side options of its bash-builtin heads; the unvouched row promises nothing verify does not honour (B21, D-9)
- 8d9f9d4 fleet: verify judges a read redirection's target like a write's, so bash's /dev/tcp cannot fetch (RV-29)
- 8af13b6 fleet: verify's long-option blocklist matches a blocked name's longer aliases too (RV-30)
- d43cdf7 fleet tests: drop the duplicated vouched row (RV-36)
- dcda2aa fleet: the vouch block's comment states the grammar reads equal or stricter than bash, naming the fd-number case (RV-35)
- 89f632a fleet: the unvouched row says plainly that a relabelled recipe is checked by nothing (RV-32)
- bc800ee fleet: verify's population row counts the indented shell fences the reader did not examine (RV-31)
- 5c32965 skills: lint-skill reports a package without the markdown reader as bad input, not as findings (RV-33)
- d88e310 fleet: verify counts every shell fence the reader classed as prose, not only the 4-space form (RV-37)
- ed001d4 fleet: the indented-fence counter requires the language to end at whitespace, as recipes_of does (RV-38)
- 5bcbcc3 skills: lint-skill's other two bad-input paths exit 2 as its docstring says (RV-42)
- ed47b50 skills: lint-skill's test covers its three bad-input doors (RV-39)
- a9f31ef skills: lint-skill refuses a source path with no fleet package instead of importing whatever PYTHONPATH carries (RV-51)
- ee5dfb6 skills: lint-skill's bad-input cases scrub PYTHONPATH so the tool's own source setting is what they test (RV-45)
- bfc8e91 fleet: verify's population row names every fence shape it counts as unexamined (RV-46)
- d7a0529 fleet: the indented-fence counter's comment states the count is an upper bound (RV-47)

## fleet/v0.6.7 — 2026-09-24T00:16:08Z
Cut from 842d38f on `live` (upstream base snapshot/2026-09-22-152849). 93 commit(s) since fleet/v0.6.6.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (39 files), skills (4 files), scripts (2 files), docs (1 file).
Skills changed: coordinating-instants, dispatching-a-wave, reviving-dead-panes, using-fleet.

- 78a78be fleet: abort --dry-run evaluates the cwd-holder gate, and abort refuses before the kill (B10)
- 739aa5f fleet: abort's docstring states the B10 order (gate before the kill)
- d9694da fleet: dry-runs that returned above a refusal met after a side effect (B10 sweep)
- e40345b fleet: dry-runs ask the refusals the real call meets before its first write (B10 sweep, mild half)
- fdc99e1 skills/using-fleet: a dry run refuses as the real call does; name the three that still exit 0 (B10)
- 0c2c5f3 fleet: every pane of the session roots its own process tree, not only the first (RV-20)
- 6dec392 fleet: declare reads the review ledger before the dry-run return and before writing (RV-18)
- 4f0b56a fleet: harvest refuses a row apply would refuse, before applying anything and in the dry run (RV-19)
- 343ddd1 fleet: the slot gate refuses from the same scan it attributed, not a second one (RV-21)
- e46723e fleet: the slot gate's docstring says what each verb does after an undecided gate (RV-22)
- 08c880b fleet: unenroll --dry-run on a leased slot raises the real call's refusal, not a bare rc=4 (RV-23)
- 64796d2 fleet: harvest --id picks its branch by ctx.dry_run alone, never by the gate's return (RV-24)
- de29a9c fleet: Roadmap.add raises add_refusal's own refusal instead of a copy of it (RV-25)
- 42557cc fleet/it: S11 asserts its holder was seen under the pid it kills, and the EXIT trap kills it (RV-26)
- 0f0ca6b fleet/it: S11's control holds the slot with a child of a second pane, through the real parent walk (RV-27)
- 96cbf80 fleet: propose --dry-run asks status, evidence, then the inbox, as Roadmap.propose does (RV-28)
- 91a1ee7 fleet: init checks the registry with register's own parse, no stricter (RV-29)
- 7883331 fleet/tests: release_refusal's spare case reads the named pid list instead of slicing the message (RV-30)
- c97f73f fleet: the typing import sits in alphabetical order in review.py and roadmap.py (RV-31)
- 4a80be3 skills/using-fleet: name every case where a dry run can still pass a call that refuses (RV-11)
- bb56048 skills/using-fleet: an abort/harvest dry run can take the real call's 2s wait (RV-32)
- b3a237c fleet/it: S11 never signals its holder's pid again once it is reaped (RV-34)
- 04443ad fleet: the undecided-gate row and the skill say what abort and harvest each do after the kill (RV-33)
- fa556ec skills/using-fleet: the dry run's wait is a fixed 2s sleep and one re-scan (RV-35)
- 90397bf fleet/tests: the RV-19 case puts a valid row ahead of the refused one, so the mid-loop half is measured (RV-36)
- 189fbf1 fleet: every refusal names a route, and the route it names runs (B11, FB-74/86/87)
- 3e6b4db fleet: the claim route is chosen by the owner's record and folder state, and each case runs it (RV-20)
- c03b1e0 fleet: the runtime-switch refusal names the predicates that clear it, not a close (RV-21)
- 89039cb fleet: revive and resume name a runtime route that can run in the state they refuse (RV-22)
- e0ed244 fleet: close names reap, not harvest, for the slot of a record whose folder is gone (RV-15)
- 26c2eec fleet: the deleted-owner proofs run scenE2's whole sequence, reap included (RV-14)
- 183c58f fleet: a lost lease routes to a new worker, not to revive, which needs that lease (RV-23)
- 25c069d fleet: send --dry-run and the real send raise the one not-idle refusal (RV-24)
- 3fb5c1b fleet: the override-into-a-full-pool answer says no slot is free and names interrupted claims (RV-25)
- 5ca8852 fleet: an unreadable record does not replace the not-an-instant-on-disk refusal (RV-26)
- 7786e93 skills: using-fleet and dispatching-a-wave name close --id before --disown for a gone folder with an open record (RV-17)
- 6b83309 fleet/tests: the FB-87 case asserts the pending-left row names the proposer as it is now (RV-19)
- e0f3851 fleet: the codex awaiting-ci refusal names its actor as the worker, not a bare todo id (RV-27)
- 9fac555 fleet: guards.raise_for passes the route to every error class through the constructor (RV-28)
- ae4ab86 fleet/tests: the send-route case pins its refusal and route, not just the labels (RV-29)
- c801e8b fleet/tests: the deleted-owner case's docstring quotes scenE2's raw sequence, reap included (RV-16)
- ae8bfa9 fleet: the runtime-switch route says which records harvest clears, and its test runs harvest (RV-30)
- 722d12b fleet: the pool-capacity guard names a bodiless claim and its reap --all route instead of calling it leased (RV-25)
- 5b76d9c fleet: resume's foreign-session refusal names the recorded-runtime route when a record exists (RV-31)
- 48ba9bf fleet: an unreadable record does not replace the already-claimed refusal (RV-32)
- 5b8ee81 fleet: the override-into-a-full-pool answer does not call a young bodiless claim dead (RV-33)
- c160acc fleet: the runtime-switch route names review then harvest for aborted and unreviewed records (RV-35)
- fc85864 fleet: pool.claim's exhaustion names a bodiless claim without calling the pool leased or the writer dead (RV-25)
- c093ff1 fleet: resume's recorded-runtime route says the record itself blocks that switch until harvested (RV-36)
- 7479d4a fleet: the runtime-switch route names harvest only for a -complete- record and says FB-92 for the rest (RV-37)
- d22203b fleet/it: RESULTS.tsv E9-leak-d note matches run-e9-leak.sh's reworded pass note (RV-39)
- 438c416 fleet: RED tests for the teardown-safety bucket (FB-85, FB-88..FB-92)
- 92dc1e0 fleet: abort and harvest --id release only the lease they read (FB-89)
- af9e241 fleet: abort and harvest --id ask close's pane guard before any write or kill; --force overrides it (FB-88)
- d036a23 fleet: enroll and clone refuse a basename already enrolled at another path (FB-91)
- f70297e fleet: reap and reap --dry-run read one pure Pool.reap_plan; the dry-run exits 4 where the real call does (FB-85)
- 3b73ccc fleet: an unreadable cwd holder tied to the slot is undecided, not absent, and a teardown notes it before the kill (FB-90)
- 0e3a420 fleet: a record blocks runtime --set only while resume or revive could still act on it, and names the verb that clears it (FB-92)
- 3e7250f skills: using-fleet, coordinating-instants and the runtime guide teach the teardown-safety behaviour (FB-85, FB-88, FB-90, FB-92)
- ba3cae5 fleet/it: §S S13 (abort refuses a mid-turn pane before the kill, FB-88) and S14 (runtime --set over unresumable records, FB-92)
- 4fb92d2 fleet: a running -inflight- record's runtime-switch blocker names abort, the route that clears it (RV-17)
- 1546396 fleet: the lease note writes only into the claim it read, never resurrecting or overwriting one (RV-18)
- 371c2a6 fleet: an undecided cwd gate still notes the unreadable holders it saw before the kill (RV-19)
- b5ec1b4 fleet: an untagged record's runtime-switch route names reap --all, not an empty --base (RV-20)
- 91456c1 skills: reviving-dead-panes no longer sends the operator to a runtime switch the open record itself blocks (RV-27)
- 4dde319 fleet: FB-90's cases get a base-passing control and fail behaviourally on the pre-fix tree (RV-29)
- 05f1647 fleet: revive's runtime-mismatch refusal states the switch rule FB-92 now applies (RV-22)
- b671562 fleet: reap --dry-run names an unreadable holder as unread, not as holding the slot (RV-23)
- 44e7458 fleet: a malformed unreadable_holders note is BadInput, like every other lease-body problem (RV-24)
- 374a2df fleet: _cwd_holders skips the ancestry walk when no readable holder exists to tie to (RV-25)
- 439c7f4 fleet: harvest --force without --id is refused, not silently accepted (RV-26)
- ad4cb99 fleet: the conditional lease rewrite is atomic.atomic_write_if, not a staging copy of its own in pool (RV-18)
- 9af7c6e fleet: atomic_write_if removes its staging file when the staging write itself fails (RV-36)
- 2f0d0a2 fleet: close's slot row names reap --all for an untagged record, not an empty --base (RV-37)
- 085ba25 fleet: dispatch chooses each worker's runtime and model (--runtime/--model, profile fields), recorded and followed by revive/resume (pt2)
- 41c4192 fleet-revive.sh: revive each record under its own runtime and model, not the fleet selection (pt2)
- 47f8025 docs/skills: coordinators choose each worker's runtime and model at dispatch; revive follows the record (pt2)
- 979d0ae fleet/it: RT2 (stubs) and RTC (--choice-live, real CLIs) prove per-dispatch runtime/model choice on a claude box (pt2)
- 5a0dc9f fleet: state that a runtime_model record makes an older binary refuse the whole store, and pin the default record to the base schema (RV-27)
- d5b6112 fleet/it: the RTC harness never answers a folder-trust screen, whose answer persists into the shared CLI config (RV-19)
- c20f80c fleet: an empty --runtime is refused instead of falling back to the box runtime (RV-29)
- 0e3ac40 fleet: pane-guard --pane falls back to the fleet selection when the store is unreadable (RV-30)
- eeb5b17 fleet: brief reports an unactionable record as its runtime row instead of failing whole (RV-31)
- 67befb9 Revert RV-31's brief change: base brief already calls _record_for (cli.py line 4841 at 711dbdc6), so pt2 added no new failure mode (RV-31 wont-fix)
- 6842d8a fleet/it: RTC asserts worker (a)'s pane-guard codes, not only records them (RV-34)
- 49d2574 skills/dispatching-a-wave: literal runtime/model variants instead of a zsh-breaking conditional expansion (RV-28)
- 084a9b9 docs: an older fleet silently ignores the profile runtime/model fields; read the dry-run's runtime row (RV-32)
- bf9924d fleet/it: RTC runs codex in a PRIVATE CODEX_HOME (auth copy removed on exit, the root's top-level defaults, pre-trusted checkout) and asserts no -m means the root's configured model (RV-26, coordinator D-35)
- 3bf20d8 docs: --choice-live runs codex in a private CODEX_HOME and never answers a trust screen (RV-26)
- e36a326 fleet/it: RTC's private CODEX_HOME also trusts the main repository behind a git worktree, which is where codex keys trust (RV-26)
- f7da05a fleet/it: RTC comments say what the harness now does — never answers a trust screen; codex keys trust by the main repository (RV-35)
- 251daa7 fleet: the older-binary blast radius names the enumerating surface as examples, not a complete list (RV-36)
- 4818ee3 fleet/it: the RTC trust comment and its refusal text distinguish codex's private CODEX_HOME from claude's shared config (RV-41)

## fleet/v0.6.6 — 2026-09-23T10:32:17Z
Cut from 35d6173 on `live` (upstream base snapshot/2026-09-22-152849). 65 commit(s) since fleet/v0.6.5.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (27 files), skills (4 files), scripts (15 files), docs (1 file), other (1 file).
Skills changed: coordinating-instants, releasing-fleet, using-fleet, working-as-a-dispatched-instant.

- 2ac699e fleet tests: per-process selftest tmux server, retired in cleanup (FB-49)
- 7c64972 fleet tests: keep the selftest tmux server non-empty between cases (FB-5)
- 50b62ea fleet tests: FB-5 comment states the measured non-empty-server count
- 142cb28 fleet tests: pin the anchor that keeps the selftest server up between cases (RV-22)
- cff97b1 fleet tests: fixture sessions end with the suite process, comment states the measured bound (RV-23)
- 9371c26 fleet tests: the attachment case retires only a server of its own (RV-24)
- 35a722d fleet tests: the attachment fixture checks that its session landed (RV-25)
- 4af7448 fleet tests: state that the selftest server name is fixed per importing process (RV-26)
- c9723c9 fleet tests: retire only server names this module mints (RV-28)
- 58d609d fleet tests: the anchor pin asserts its own kill-session landed (RV-30)
- 9eb79ed fleet tests: the pid-loop comment states the measured bound (RV-31)
- e8ee5cc fix(launchers): stop running a dispatch-exported FLEET_BIN (FB-56)
- 0d39f9f fix(scripts): make every shebang script executable (FB-31)
- 74aaf72 fix(it): key the live-session baseline per run (FB-60, FB-34, FB-47)
- 2d928b4 test(launchers): never run a real fleet from the FB-56 cases
- 58d609c docs: launchers ignore FLEET_BIN; the IT live-session baseline is per run
- 2cd4e86 fix(it): untrack the live-tmux re-baseline log (RV-23)
- e70d7a1 test(launchers): assert the sibling bin/fleet acts under an ambient FLEET_BIN (RV-24)
- 6d8e1df fix(it): lib.sh no longer exports the run id; run-all.sh does (RV-25)
- 7baf9c1 fix(it): a leak seen at a checkout's first run FAILs and never enters the handover (RV-26)
- 0553b51 fix(it): A8's write census counts the handover and the per-run prune (RV-27)
- 1763dc1 fix(it): write the live-tmux handover atomically (RV-28)
- b2cd790 fix(it): ISOLATION rows cite the snapshot the comparison used (RV-29)
- 6bea8d4 test(runtime-helpers): drop a seam the dispatch launcher never reads (RV-30)
- e6d3014 fix(it): W1's negative controls repoint the handover too (RV-31)
- 7c1ff86 docs(fleet): the run id is exported by run-all.sh, not lib.sh (RV-25 follow-up)
- 7272bd5 fleet: pin FB-53/FB-54 — no per-pid condition refuses the process inventory, and an unreadable row is placed by its pane
- 12203d9 fleet: FB-53/FB-54 — report one unreadable pid instead of refusing the inventory, and attribute it through stat
- 64427c7 fleet: seed-check reads a claude whose argv is not UTF-8 as the worker it is (RV-23)
- 226ad75 fleet: seed-check's comm probe answers for a comm that is not UTF-8 instead of raising (RV-31)
- deee581 fleet: reconcile lets a record's readable process speak for it over an unreadable one in the same pane (RV-25)
- b60e184 fleet: peers refuses an unreadable row as unreadable, not as a dead or recycled pid (RV-26)
- 62966e8 fleet: send refuses a pane whose process is unreadable by saying so, not 'no matching process' (RV-27)
- 0dd49cb fleet: an unreadable row never takes a lease held by a record on another tmux server (RV-29)
- e6225f2 fleet: unreadable-row texts say a /proc read failed instead of naming exe/cwd (RV-24)
- cece2f8 fleet: say what is_claude_process/is_agent_process prove for an unreadable row (RV-28)
- d5c3f8b fleet: pin the runtime --set text for an unreadable row (RV-32)
- ba93d0d fleet identity: same_instant compares two recorded paths by stable key (B08)
- 9c54ada fleet: seed-check exits 1 on a non-pass; owner and legacy evidence follow the rename (B09, B08, FB-44, FB-45)
- 4c9186b fleet it: H13, the re-measure's scenA on a real dispatched worker (B09, B08, FB-44)
- d1866ce skills using-fleet: seed-check's exit code, milestone --evidence gate, owner where it is now
- 10337f0 fleet seed-check: an OSError or an undecodable seed is that session's unreadable row (RV-26)
- dc35369 fleet milestone --disown: a relative child_instant is anchored before the identity compare (RV-27)
- 63e6a7c fleet roadmap: claim and disown refusals name the owner where it is now (RV-24)
- 576e43e fleet roadmap: one read lists each owner folder once; milestone(id) resolves one owner (RV-25)
- f4b2007 fleet roadmap: apply stores a legacy item anchored where its proposer row locates it (RV-28)
- ab65392 fleet tests: dispatch's own seed check reads the delivery through the renamed folder (RV-29)
- 9b2f231 fleet seed-check: the NOT-DELIVERED comment agrees with the exit code (RV-23)
- 9fffbe1 fleet milestone --evidence: the refusal names the coordinator's folder as the anchor (RV-30)
- 284536e skills using-fleet: legacy evidence is anchored from applied or closed rows (RV-37)
- d19eb68 fleet reconcile: an awaiting-ci watcher is classified from what is true, not from what was recorded (B07, FB-58)
- 16e68a6 fleet declare/brief: an attestation may name pid:<n>; brief stops saying the board cannot tell (B07, FB-58)
- ad055b0 skills: the board labels and re-checks awaiting-ci watchers; attest with pid:<n> (B07, FB-58, NEW-4)
- 6e9d35c fleet/it: §F F2c/F2d - an attested pid that exits and an observed watcher that vanishes are disregarded (B07, FB-58)
- 4294c1d fleet reconcile: the pid statuses get marker values of their own (test_contracts one-marker-one-name)
- ad0f8f7 fleet declare: a pid handle followed by more bare pids is ambiguous and refused; the skill names $! and warns off pgrep -f (RV-C1)
- 37c9131 fleet reconcile: a malformed watcher_pid handle is NOT MEASURED instead of crashing the board (RV-C5)
- e51e560 fleet reconcile: the awaiting-ci note reuses the classification the state was decided on (RV-C2)
- 0af02e4 fleet reconcile/brief: an attestation without a recorded handle says so, not that it names no pid (RV-C3)
- 0ebcdfb fleet brief: an attested pid already GONE is disregarded now, said in the present (RV-C4)
- 12960cb fleet tests: PROC_ROOT is patched without create=True, and a comm holding ') Z' is pinned (RV-C6)
- 54d5cc7 fleet/it: §F's cleanup kills F2c's sleep if a run is interrupted before the inline kill (RV-C7)
- c7fc981 fleet/it + tests: F2d passes the frame path to the inner shell as an argument; the fake /proc trees are removed (RV-C8)
- ad49fb2 fleet tests: TestAwaitingCiNote's docstrings speak of the retired i45 warning in the past tense (RV-A3)
- 650203f fleet/it: F2c's assertions name the pid through F2C_WATCHED, since RV-C7 clears F2C_PID once reaped (RV-C7)

## fleet/v0.6.5 — 2026-09-23T03:45:38Z
Cut from 2d59609 on `live` (upstream base snapshot/2026-09-22-152849). 63 commit(s) since fleet/v0.6.4.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (27 files), skills (5 files).
Skills changed: auditing-a-dispatch-history, coordinating-instants, harvesting-an-instant, using-fleet, working-as-a-dispatched-instant.

- 5439a61 fleet reconcile: an operator dialog on the pane is BLOCKED (B06 fact 1)
- 59ffac8 fleet reconcile: a live worker whose instant folder is gone is BLOCKED (B06 fact 2)
- c9e754a fleet reconcile: a parked question asks for a human (B06 fact 3)
- 90c2a2d fleet reconcile: an awaiting-ci claim nothing watches is disregarded (B06 fact 4)
- 49763b5 fleet it + skills: a backed declaration frees the cap, an unbacked one does not (B06)
- 8ee1eb9 fleet it: K5's awaiting-ci declaration names its watcher (B06)
- a3e49f0 fleet it: F2b reads the board row by TODO ID and asserts positively (RV-40)
- ab12d43 fleet it: F5 declares a watcher and ASSERTS the cap half (RV-41)
- a8f065c fleet reconcile: a FAILED pane capture is NOT MEASURED, not an absent watcher (RV-42)
- 264cf38 fleet reconcile: the disregard note states the fact and predicts nothing (RV-43)
- 71c36c6 fleet tests: pin the codex term in the unwatched predicate (RV-45)
- 550b68b fleet tests: pin that a missing instant folder outranks a busy pane (RV-47)
- 099137c fleet tests: pin the child_instant gate on the missing-folder branch (RV-46)
- 2293ada fleet it: F2b judges the board's exit status and reads its own row's note (RV-48)
- 80b9a94 fleet: collect whether a human is attached to a session (B24, x2 G-4)
- 03fee8e fleet: a human attached and typing is not a worker waiting on one (B24)
- 186413d fleet it: §AT, a real attached client in front of a BLOCKED pane (B24)
- a223308 skills: a BLOCKED row with a human attached and typing is not in the count (B24)
- 89243e6 fleet: only a codex dialog fleet SAW is excused by an attached human (RV-25)
- dbbdc75 fleet tests: pin the BLOCKED sources an attached human never excuses (RV-26)
- 6664b43 fleet: a read-only or control-mode client is not a human at the pane (RV-28)
- a1f3b9b fleet: a malformed attachment answer is not measured, not a crash (RV-29)
- 4ccbd7b fleet: the unobserved-attachment note states only what is known (RV-27)
- 3e5d47b fleet: input stamped in the future is not a measurement (RV-33)
- ab8a884 fleet: one clock read per attachment, so note and evidence agree (RV-32)
- c1e51f9 fleet: say why _live_state's on_pane tail re-checks BLOCKED (RV-34)
- be3d2bb fleet it: AT8, a read-only client is not a human at the pane (RV-31)
- 114269f fleet: a non-finite attachment answer is not measured either (RV-35)
- 5ed4d0b fleet: read-only and control-mode clients are observers, never nobody (RV-36)
- c5a5ac6 fleet: two comments still named #{session_attached} as the fact read (RV-28)
- b1da20e fleet tests: the read-only/control-mode case names observers, not non-humans (RV-36)
- 588992f fleet: say only what was measured about a control-mode client's input (RV-40)
- 6badaf3 fleet: an evidence item is a location — one resolver (B03)
- 0c46e15 fleet: propose and apply resolve evidence; roadmap prints it (B03)
- 4c2afb5 fleet: propose's dry run and harvest judge evidence (B03)
- 3608e35 fleet: pin propose's dry-run form and apply's refusal order (B03 review)
- 4810450 fleet: IT fixtures cite files that exist; skills teach that evidence resolves (B03)
- 8d85c64 fleet: IT case H12 pins evidence resolution; skills cite it (B03 review)
- 24d0205 fleet: relative evidence walks renames too; admit matches apply (B03 final review)
- 4525d15 fleet: apply upgrades a legacy relative evidence item to the anchored one (RV-20)
- 4bfc977 fleet: apply re-anchors absolute evidence already on the milestone (RV-21)
- 7d0519a skills: the dispatch-history audit reads evidence from roadmap porcelain $9 (RV-21b)
- a7ccf7f fleet: a file:// evidence item is judged as the path it names (RV-22)
- 65efe62 fleet: an unreadable directory reads as evidence that does not resolve (RV-25)
- 924bc25 fleet: name the check-then-apply windows in apply and harvest (RV-24)
- d08fc71 fleet/it: align the H11 fixture comment (RV-27)
- eb08281 fleet/it: section H rows of RESULTS.tsv regenerated in place from the d08fc71d run (RV-28)
- e7bcad8 fleet: PromoteGateCase promotes in a root it wrote, not the caller's (FB-35)
- 800c9f1 fleet: TestANamedDestinationIsWholeNotHalf clears every fleet variable (FB-35)
- bf71a16 fleet: the hermetic suite fails any test that reaches the caller's fleet (FB-35/FB-40)
- 467b5d1 fleet: the guard resolves a root's store and release area before comparing (RV-C5)
- bfd53cb fleet: the guard refuses a live store before anything reads it (RV-C3)
- 62d0149 fleet: the guard covers the live instants tree (RV-C2)
- 1ad4af0 fleet: a case pins the live set the guard captures at import (RV-C1)
- ea5023b fleet: CLAUDE.md states when the live-fleet guard is installed (RV-C4)
- ed6d078 fleet: CLAUDE.md names what the live-fleet guard does not watch (RV-C6)
- f4d3402 fleet: CLAUDE.md lists the instants tree among what the guard watches (RV-A1)
- 2dcdfe8 fleet: the guard resolves each live store's instants directory (FI-1)
- 45c654f fleet: a process inventory survives a pid that exits mid-sample (FB-41)
- 04614dd fleet: say only what the vanishing-pid arm guarantees (RV-15)
- 4115fc1 fleet: pin that the exit flag is read after stat's last paren (RV-16)
- 46e4598 fleet: say why the reaped-after-stat clause stays (RV-18)
- 4410799 fleet: name the arm that still refuses the inventory (RV-33)

## fleet/v0.6.4 — 2026-09-22T15:41:27Z
Cut from b3e4074 on `live` (upstream base snapshot/2026-09-22-152849). 35 commit(s) since fleet/v0.6.3.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (5 files), skills (41 files), hooks (1 file), plugin-manifests (1 file), scripts (3 files), tests (11 files), docs (10 files), other (5 files).
Skills changed: brainstorming, diagnosing-superpowers, executing-plans, releasing-fleet, requesting-code-review, subagent-driven-development, systematic-debugging, test-driven-development, using-superpowers, writing-plans, writing-skills.

> fleet/v0.6.3 is no longer an ancestor of `live` — an upstream rebase rewrote the commits between. This delta was computed by patch-id, not by ancestry.

- 5bf4e78 Release v6.4.1: diagnosing-superpowers, Native plan execution, OpenCode 2.0 and Muse support (#2338)
- 3dbdf8d the four fleet skills, each carrying tests that prove its factual claims
- 2710152 fleet v0.3.8
- 8c1ba35 fleet v0.3.9
- 2e021ff fleet v0.3.10
- 8c6eea2 fleet v0.3.11
- 4aa3c52 fleet v0.3.12
- e0fbfd9 fleet v0.3.13
- 65d188a fleet v0.3.14
- 48feb9f fleet v0.3.15
- aecbd66 fleet v0.3.16
- d980ae4 fleet v0.3.17
- 501c408 fleet v0.3.18
- f540b3d fleet v0.4.0
- 6ff9f30 fleet v0.5.0
- 0ce3842 fleet v0.5.1
- c11b436 fleet v0.5.2
- 7851651 fleet v0.5.3
- 6a667ad fleet v0.5.4
- 69d51b8 fleet v0.5.5
- 79bf9b6 fleet v0.5.6
- 1b27369 fleet v0.5.7
- 7b56daa fleet v0.5.8
- 5c8a818 fleet v0.5.9
- b4fa570 fleet v0.5.10
- 21a817c fleet v0.5.11
- 1d3f8b7 fleet v0.5.12
- fd8c22e fleet v0.6.0
- d12c28f fleet v0.6.1
- 37eded5 fleet v0.6.2
- 5ea8ef4 fleet it: keep the release gate green and out of the live store (B18a)
- ea77e52 fleet it: A1e reads symlinked/slashed stores, sorts for comm; preflight seam slash-safe
- 6a5aa9d fleet it: lint-clean IT_ENV_UNNAMED; A1e watches the whole store to depth 4
- adf9073 fleet v0.6.3
- 22d8b4b fleet release_scope: CUT_MANIFESTS names upstream 6.4.1's .muse-plugin manifests

## fleet/v0.6.3 — 2026-09-22T07:18:59Z
Cut from 6128a59 on `live` (upstream base snapshot/2026-08-17-221146). 26 commit(s) since fleet/v0.6.2.

Every release ships the whole repository — all skills, `commands/`, `hooks/` and the plugin manifest, not only `fleet/`.
Payload: fleet (21 files), skills (10 files), scripts (2 files), docs (5 files).
Skills changed: coordinating-instants, dispatching-a-wave, harvesting-an-instant, maintaining-a-roadmap, using-fleet, working-as-a-dispatched-instant.

- 091c4ce docs: add Fleet bootstrap and first-coordinator quickstart
- d4ede12 docs: publish Fleet introduction and workflow visuals
- 7f48e7c harvest: apply the worker's report from the coordinator's inbox, and give back its claim
- b65fb94 harvesting-an-instant: a released claim does not by itself make an in-flight milestone dispatchable
- d1eb400 harvest: a report the coordinator already applied counts as arrived; dry run previews the claim release
- 976d477 harvest guard: an applied row counts only when it carries an outcome, not mid-flight progress
- e004074 harvest guard: judge the worker's LATEST applied report, and count everything but `running`
- 14ae5a7 harvest guard: judge the worker's last word however it arrived; refuse only `running`
- 7fa68c2 skills + test: a last `running` counts as no report; propose on the worker's behalf AS the worker
- c40edb3 harvesting-an-instant: keep the status list attached to its colon; the as-the-worker note becomes a parenthetical
- 7cde9f6 roadmap: the proposal queue gets its exits — newest-wins apply, superseded/withdrawn/retired, terminal guard
- 7b7415d cli: apply picks one row (--at, --reopen); withdraw verb; retire reports the rows it closed
- fdfbd99 harvest: apply the worker's last report per milestone; earlier rows close as superseded
- 0f7f537 queue: cut at the last copy of a twice-sent row; retire counts only its own rows
- 12dc271 skills + IT: teach the proposal queue's lifecycle; H11
- 6b5878f B02 review fixes: old no-note rows consumed; run-A recipe; SI-48 trap becomes a guarantee
- 0dc7fd3 IT M9: the declared delete site is roadmap._close now; worker skill names where the coordinator path comes from
- 85b3aeb B26: an empty or exiting tmux server is an empty population, not a dead fleet
- e542cdf B26 review fixes: confirm the exiting shape too, route only where it applies
- 37b4725 B26 review round 2: route only for a session-less server, count sessions by line, honest guard docstring, TE5 failure note names its cause
- 3f79724 IT TE7: harvest's observation tick is exercised in both server states
- 7e81e16 B04: the read surface names ready milestones and states its population
- 7ec7c3a B04 review round 1: population-aware first-row reads in run-D, footer-only view assertions, exact row-per-milestone wording, stranded-claim guidance, claimed case pinned in wave-sequence, unclaimed count in the roadmap banner
- 3e69173 B04 review round 2: stranded-claim rule joins the board's milestone column and excludes pending reports; population count read from the ready rows; docstring widths
- 1047bee fleet: a test drives reconcile to IDLE (G-10)
- 877cf8f fleet: the IDLE producer test covers a parked worker and ages .fleet/* for a reason

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

