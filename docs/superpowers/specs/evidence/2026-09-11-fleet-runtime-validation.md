# Runtime validation — work in progress

The implementation is in `feat/fleet-runtime-selection`, based on bootstrap commit `4d94241`.
This report distinguishes infrastructure checks from actual model behavior. Validation is ongoing;
the feature has not been promoted or deployed.

## Completed checks

- Full fleet unit suite: 1,842 tests passed before the executable-alias regression was added.
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
Further live behavior checks are pending.

## Behavior evaluation

See [the before/after report](2026-09-11-fleet-runtime-evals.md) for all twelve independent CLI reference
sessions and the exact native bootstrap acceptance transcripts. Quorum was unavailable; its missing
results are not replaced by unit or stub passes.
