# Runtime validation — work in progress

The implementation is in `feat/fleet-runtime-selection`, with runtime implementation `f2e6b32` and terminal-attribute fix `59531ec`.
This report distinguishes infrastructure checks from actual model behavior. Validation is ongoing;
the feature has not been promoted or deployed.

## Completed checks

- Full fleet unit suite: 1,845 tests passed in 115.377 seconds, including the terminal-attribute and exited-process regressions.
- New multiprocessing cases: dispatch versus switch, two senders versus close, lock release after
  process death, and independent roots/panes passed.
- `run-runtime.sh --stubs`: Claude → Codex → Claude in one store, seed-byte attestation, early-switch
  refusal, WIP-cap refusal, Codex watcher refusal, review/abort/harvest and released leases passed.
  The stand-in is a real tmux process but is explicitly not a model.
- Existing integration sections A and S passed their runnable checks, with their recorded isolation
  skips. L/M/N was stopped before completion: the source was uncommitted, which violates M13's stated
  precondition, and two nested self-tests exceeded the old 120-second timeout. The full unit suite
  separately passed in 180.531 seconds during concurrent checks. The timeout now allows 600 seconds;
  the assertions remain unchanged. This interrupted run is not a green integration result.
- Hook JSON tests, Codex native-hook tests, marketplace/package tests, systematic-debugging's polluter
  test, fleet-view, fleet-env root derivation, and the Claude watchdog PID exclusion test passed.
- The exact-session helper test passed with paths containing spaces. Its generated launcher delegates
  to `fleet revive`. A separate check proved the Claude watchdog excludes only Claude workers.

## Real Codex session

Codex CLI 0.154.0 was dispatched with its own configuration and a private tmux socket. Fleet verified
its seed in the native worker's argv. The initial session required ordinary project and hook trust;
the plugin hook definition was inspected before trusting it. The resumed session received the full
3,271-character bootstrap context, recorded at `2026-09-11T19:20:29.444Z`.

`fleet send` submitted a multiline message once, and the worker replied `MESSAGE RECEIVED`. Runtime
switching refused while it was live, and again after its pane was killed with the lease retained.
A nonexistent transcript UUID refused. `fleet revive` resumed the explicit session
`01a091e8-948a-7842-8aa8-6d1a819c8de9`, and another guarded message received `RESUMED`.

A sleeping-shell watcher attestation was refused for Codex, and a subsequent dispatch at cap 1 was
refused with the existing worker still counted.

For a bounded debugging check, `calc.py` subtracted instead of adding. The worker received a request
to diagnose the failing test, without naming a skill in the prompt. It loaded systematic-debugging,
ran the test before editing, saved the failing output and original files, changed the operator, ran
the tests again (one passed), and reported `DEBUGGING DONE`. The coordinator then closed the observed
idle pane, recorded the review, completed and harvested the instant, and switched the store to Claude.
This was a single-worker check; it does not claim the full two-milestone acceptance matrix.

Artifacts: [session and tool exchanges](codex-live-session-2026-09-11.json),
[debugging evidence](codex-live-debugging/INDEX.md),
[before](codex-live-debugging/tests-before.log), [after](codex-live-debugging/tests-after.log).

## Real Claude finding

The first real dispatches failed seed verification because resolving the executable symlink changed
Claude's process name. Both launch forms were measured: the alias produced `comm=claude`, the versioned
path produced `comm=2.1.268`, and both pointed at the same native executable. Fleet retained the lease
while cleanup could still observe a process holding its cwd. The test attempts were explicitly aborted,
reviewed and harvested before retrying.

The new regression test failed on the resolved-path implementation and passed after preserving the
absolute executable alias. The next real Claude dispatch returned success and a launch timestamp.
Claude then accepted a multiline message, resumed exact UUID
`e26119ef-0f32-412e-b3b1-85695cae0e30`, and automatically invoked systematic-debugging for the
seeded addition failure. It captured the original failing test and source, fixed the operator, and
ran the test successfully. After review, completion, process exit and harvest, the same store switched
to Codex and back to Claude.

A second real finding was inherited `NO_COLOR=1` from Codex shell tools: Claude's suggested next prompt
lost its dim attribute and was conservatively classified as a draft. Launch and resume now unset that
variable in the worker only. The regression failed for both runtimes and both launch forms before the
fix, and passed afterward. A real resumed Claude rendered `commit this` dim; `pane-guard` returned 0.
An owned test draft remained intact while send and close both refused; the guard returned 10. One
intermediate guard call failed closed when a separate process disappeared during the census.

Artifacts: [session and tool exchanges](claude-live-session-2026-09-11.json),
[debugging evidence](claude-live-debugging/INDEX.md),
[dim suggestion](claude-color-response.frame), [preserved draft](claude-owned-draft-preserved.frame).

The full integration attempt against `f2e6b32` found W1-9's direct use of the seed-requiring dispatch
stand-in. W1-9 now uses a copy of sleep named `claude` for its cwd-attribution negative control.
The repeated W1 section passed, with its stated isolation skips. The interrupted full attempt is
not a green full-suite result.

## Behavior evaluation

See [the before/after report](2026-09-11-fleet-runtime-evals.md) for all twelve independent CLI reference
sessions and the exact native bootstrap acceptance transcripts. Quorum was unavailable; its missing
results are not replaced by unit or stub passes.

## Two-worker native lifecycle

The opt-in runner completed on both real CLIs against `59531ec`: one coordinator and two workers,
separate slots, cap refusal, early-switch refusal, guarded multiline sends, captured failing tests,
worker-produced reviews and proposals, completion, coordinator-side apply, observed process exit,
harvest, refusal to message retired workers, and switch-back. Both isolation assertions passed.
The driver issued apply/close/harvest; the native coordinators loaded their skills and read the roadmap.
This does not claim autonomous model dispatch-policy evaluation.

See [the recorded commands, transcripts and artifacts](runtime-waves/INDEX.md).
Earlier test-runner attempts failed because its custom store was mistaken for a marked fleet root,
it expected the wrong review/harvest exit codes, and it tried reading root-owned process cwd links.
Those were corrected in the runner. One earlier Codex input observation was indeterminate and stopped
without pressing Enter. Explicit-session recovery and a later fresh two-worker run both succeeded;
the original transient frame was not retained, so its cause is not asserted here.

Codex's login shell selected the older main-checkout fleet binary on PATH. The workers identified the
record-schema error and used the candidate checkout's absolute binary. Install/select the same updated
fleet CLI in worker shells as in the coordinator; an old binary cannot read runtime-bearing records.

A separate finite Linux fixture reproduced another closeout issue: an exited zombie still appeared in
pgrep but had neither exe nor cwd. Discovery now omits observed Z/X states while continuing to refuse
unreadable live processes. This refinement changes exit handling, not the completed native workflows.

## Remaining validation limits

The full integration attempt at `59531ec` passed runtime, W1, mutation/leak controls, A/B/C/D/Q/I7/RMW,
then failed K9 because the manifest counted creation of the persistent admission-lock inode as leaked
state. K9 now includes that inode in its baseline and still compares all contents/mtimes. The repeated
K section passed. The full run is being repeated on the subsequent committed revision.

The evidence-path lint fails on historical/generated IT result tables that contain absolute paths;
this is not a passing control. The older tracked RESULTS.tsv already contains such references.
Quorum remains unavailable. Claude's existing external watcher-positive behavior was not re-evaluated;
Codex's unsupported-watcher refusal and retained capacity were tested explicitly.
