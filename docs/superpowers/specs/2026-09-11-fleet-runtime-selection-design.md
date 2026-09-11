# Fleet runtime selection: Claude Code and Codex CLI

Date: 2026-09-11
Status: Design direction approved in conversation; written spec awaiting review.

## Purpose and agreed scope

The human partner wants to use this fleet through either Claude Code or Codex CLI,
including dispatch, cross-process communication, capacity management, coordinator
and worker skills, systematic debugging, harvest, and recovery. Their priority is
"Simple and reliably working". They approved one saved runtime choice and switching
between runs. Mixed fleets and switching unfinished workers between runtimes are
not required.

This is runtime selection, not a model-routing system. Each CLI uses its configured
model. Fleet does not add model tiers, per-worker overrides, an API client, or a
new orchestration service. The existing Python standard-library and tmux architecture
remains the foundation.

## Evidence from the current checkout

These are code observations, not results from an end-to-end Codex fleet test:

| Area | Current implementation |
| --- | --- |
| Dispatch | `fleet/src/fleet/cli.py`, `_do_dispatch`, starts the literal command `claude`. |
| Briefing | Dispatch writes `seed.txt`; `scripts/fleet-dispatch-launcher.sh` supplies a separate PATH shim that waits for a caller to deliver the seed. |
| Detection | `fleet/src/fleet/session.py` enumerates Claude processes and interprets Claude terminal indicators. |
| Seed verification | `fleet/src/fleet/seedcheck.py` fixes `WORKER_COMM` to `claude`. |
| Recovery | `scripts/fleet-revive.sh` resolves Claude configuration and transcripts. |
| Skills | `.codex-plugin/plugin.json` declares skills and an empty hooks object; `hooks/hooks.json` references `CLAUDE_PLUGIN_ROOT`. This does not establish that Codex bootstrap loading works. |
| Retired tools | `skills/dispatchInstants/README.md` redirects users to the current fleet skills. Its remaining scripts serve a legacy Claude watchdog. |
| CLI grammar | `Parsed` and `parse` in `cli.py` deliberately reject positional arguments after a verb. |

The installed `codex-cli 0.154.0` exposes interactive prompts, `resume`, and `queue`
in its help. Those surfaces have not been exercised against real dispatched sessions
in this investigation. The optional queue transport is not needed for this design.

Official documentation describes plugin skills and lifecycle hooks, including hook
trust requirements. Installation alone is not our acceptance criterion; a real
session must demonstrate bootstrap and skill execution.
Sources: [Plugins](https://learn.chatgpt.com/docs/plugins),
[Hooks](https://learn.chatgpt.com/docs/hooks).

## User interface and persistence

Proposed commands:

```bash
fleet runtime                   # show runtime, setting source, and resolved store
fleet runtime --set codex        # select Codex for the next run
fleet runtime --set claude       # select Claude for the next run
fleet runtime --set codex --dry-run
```

The `--set` spelling follows the current parser instead of adding positional
argument support for this feature. Existing dispatch commands need no new flags.

Store the selection in `<resolved FLEET_HOME>/runtime.json`:

```json
{"schema_version": 1, "runtime": "codex"}
```

All processes resolve the store using the existing root/home rules and read this
same file. There is no runtime environment override or separate coordinator setting.
An absent file means `claude`, explicitly reported as the legacy default; an invalid
or unreadable file is an error, never a fallback. Reads do not create the file.
Use the existing atomic-write primitive. Re-selecting the current runtime is an
idempotent no-op. Runtime selection does not install a CLI or change its credentials.

The command supports the usual porcelain output. Invalid input returns 2;
an unsafe switch returns 4 and names the blocking records, leases, or sessions.
A read and a dry run leave the store unchanged.

## Switching contract

An operator switches from a normal shell after finishing workers, harvesting their
leases, and stopping the old coordinator. They then start the coordinator in the
selected CLI. Fleet dispatches of a coordinator use the same runtime as workers.
A manually started coordinator follows the documented startup procedure; this
setting does not transform an already running agent process.

A change to the selection is refused while any dispatch record is unharvested,
any lease is held, or a live agent is attributable to this fleet's managed sessions
or enrolled slots. A crashed worker still needs recovery or abort/harvest before a
switch. Unclaimed in-scope agents and failed observations block the switch and are
reported; foreign fleets do not block it and are never modified. Pending roadmap
milestones alone do not prevent switching after the old run is closed out.

Serialize setting changes with dispatch admission, adoption (`fleet resume`), and
revival admission using one store-scoped OS advisory lock. On the current Linux
platform, Python's standard-library `fcntl.flock` suffices and releases on process
exit. Keep that lock file stable; do not unlink or steal it based on age. Hold it
until a launch has durable ownership state, or has rolled back. A slow live holder
causes a bounded refusal, not lock stealing. Atomic file replacement alone does not
protect this check-then-launch boundary.

## Runtime boundary

Use one small built-in runtime module with two implementations. It owns executable
resolution, launch/resume arguments and environment, process recognition, terminal
state interpretation, and watcher evidence. It does not own pool leases, roadmap
updates, completion rules, or harvest transactions.

`SessionLayer` remains the interface to tmux and process probes. Select its runtime
behavior through this module, and preserve the existing injectable probes for tests.
Recognize both CLIs during ownership discovery so an unexpected agent cannot become
invisible to a switch or slot-release check. An unexpected runtime is reported as a
mismatch, not accepted as a mixed fleet.

Record `runtime` on each new dispatch; records without that field retain the historic
Claude interpretation. Status exposes the recorded runtime. Historical inspection
uses that value rather than today's selection. Revival of an old runtime under a
different selection is refused. Unknown runtime values are errors.

The current record reader rejects unknown fields. The updated reader can read old
records using the default, but an old fleet binary cannot read new records containing
`runtime`. Document this compatibility limit: switching back to Claude uses the
updated fleet binary; it is not a downgrade to an older fleet release.

## Dispatch and briefing delivery

Fleet owns the whole launch: render the seed, write ownership state, and launch the
resolved executable with the rendered prompt in the leased workspace. Use an
argument vector or correctly quoted tmux command; never interpolate raw briefing
text as shell code. Do not depend on a shim named `claude` or `codex` or the tmux
server's inherited PATH to choose the executable.

Pass the runtime's intended configuration environment explicitly. Preserve Claude's
operator-specific config resolution. Codex uses the dispatching operator's resolved
Codex configuration, not a Claude config path. Resolve it before tmux launch and
carry it into recovery. Fleet does not copy credentials into records or scripts.
Keep approval policies runtime-specific and preserve the configured security boundary;
Codex must be able to reach the leased workspace, instant evidence, and permitted
fleet state without defaulting to an unrestricted sandbox.

Bootstrap comes from the installed plugin's session-start integration; the seed
supplies the role, instant path, lineage, and coordinator origin. Both are required.
Missing executable or required configuration fails before allocating a slot where
possible. A failed launch uses the existing rollback rules. A session that cannot
be confirmed as correctly briefed is never reported as ready for work.

Adapt seed verification to identify the actual runtime process, not a launcher
shell. Preserve the distinctions between observed delivery, attested delivery,
missing evidence, and a foreign briefing. Account for asynchronous process startup
with a bounded wait. Resume retains its separate re-briefing/attestation path rather
than assuming the original seed remains visible in resumed argv.

## Communication, capacity, and close-out

Keep structured worker-to-coordinator reporting through `fleet propose` and
`fleet apply`. Keep tmux for interactive messages and operator visibility. Both
runtimes use the existing condition-based send sequence: establish an idle input,
insert literal text, observe it queued, then submit. Do not replace observation with
a fixed sleep. Serialize fleet senders targeting the same pane and recheck before
insertion. No automatic resend after ambiguous submission; inspect before retrying.

Normalize terminal observations to the existing guard meanings: idle, queued,
busy, non-agent, missing, and indeterminate. Busy includes a live turn; approval,
trust, authentication, and rate-limit dialogs must never be mistaken for idle input.
Preserve numeric exit codes. Keep legacy porcelain labels compatible where required,
but define code 12 as an observed non-agent terminal, never simply "not Claude".
Update first-party callers and documentation to use that meaning.

Capture real Codex terminal frames for these states. Text in scrollback or a model's
answer is not a reliable status indicator. Failed or unfamiliar observations return
indeterminate; they never authorize sending, closing, or releasing a slot.

The existing capacity policy remains shared. In particular, `awaiting-ci` only
frees active capacity when fleet has evidence of a watcher that will actually wake
the worker. Implement runtime-specific evidence checks and test a real completion
wakeup. When such evidence is unavailable, refuse the declaration and continue to
count the worker. Do not claim that a generic background process is a wakeup mechanism.

Harvest continues to require completion/review evidence, a safe terminal, process
exit, and transactional lease release. Board, peers, reconcile, seed-check, close,
reap, fleet-view, and the active launcher/revive helpers all use the same runtime
boundary. Legacy Claude-only watchdog support stays explicitly Claude-only; this
feature does not revive retired dispatch tools or promise automatic Codex quota retry.

Recovery resumes the exact runtime session selected from that worker's evidence,
in its recorded slot/configuration/socket. Never choose the newest session globally.
If the exact session cannot be established, report the missing evidence and require
explicit identification through the existing recovery workflow.

## Skills and automatic loading

Support `using-fleet`, `coordinating-instants`, `working-as-a-dispatched-instant`,
`dispatching-a-wave`, `harvesting-an-instant`, and `reviving-dead-panes` through shared
fleet commands and small runtime-specific references where needed. Include their
umbrella workflows in the caller audit. Keep systematic debugging's evidence and
root-cause requirements intact and prove their use under Codex.

Wire the Codex plugin's native lifecycle integration to load `using-superpowers`
at session start and restore the needed guidance after compaction/resume. Confirm
the supported hook payload and trust setup on the installed CLI before editing the
integration. A manual skill request, copied skill directory, or briefing that tells
the test agent to invoke brainstorming does not satisfy the bootstrap acceptance test.

For any skill-content edits, use `superpowers:writing-skills` and collect before/after
adversarial session evaluations as required by the contributor guidelines. Do not
rewrite tuned behavior tables merely to replace terminology. The `evals/` checkout
was absent during this investigation; its setup is a validation prerequisite, not
evidence that evaluations have run.

## Validation and completion criteria

This document specifies future validation; no runtime integration has been tested yet.

1. Test setting persistence, legacy default, corrupt config, dry runs, separate fleet
   roots, old records, and refusal with unharvested work, leases, or unknown sessions.
2. Exercise concurrent switch versus dispatch/adopt/revive, including process death
   while holding the admission lock. Neither ordering may create a mismatched worker.
3. Test launch arguments/environment and seed integrity, including multiline prompts,
   shell metacharacters, missing binaries, failed startup, and wrong briefings.
4. Replay real terminal frames for both runtimes: idle, busy, queued input, suggestion
   text, dialogs, scrollback lookalikes, missing panes, and capture failures. Verify
   no unsafe send/close, no duplicate submission, and exact socket/session targeting.
5. Run isolated real tmux sessions under each CLI: coordinator startup, two workers,
   capacity enforcement, interactive message and reply, proposals and apply, a
   systematic-debugging task with captured evidence, completion, close, and harvest.
6. Exercise a real CI-wait wakeup where supported, and verify refusal without watcher
   evidence. Kill and revive a test worker using its exact session. Confirm that its
   lease is retained until close-out and that no other session receives its briefing.
7. From a clean installed-plugin session, send exactly `Let's make a react todo list`.
   Capture the complete transcript showing brainstorming starts before code is written.
   Repeat skill-loading checks after compaction/resume and record both CLI versions.
8. Run existing fleet unit/infrastructure suites and relevant hook, packaging, script,
   and skill-behavior checks. Capture before/after eval results for changed skills.
9. Finish the Claude test fleet, switch to Codex and complete the same workflow, then
   switch back. Historical records remain readable and each slot is released once.

Use private test sockets and temporary fleet stores throughout. Release readiness
requires the real lifecycle evidence as well as infrastructure tests. If Codex's
terminal or wakeup behavior prevents these guarantees, report that limitation before
expanding the architecture to a different transport.

## Delivery boundary

Implement this as one feature, proving Codex's terminal/bootstrap behavior first,
then wiring the shared lifecycle, then updating and evaluating skills. A settings
flag alone is not completion. Mixed-runtime scheduling, central model selection,
live runtime conversion, new daemons, and restoration of retired tools remain outside
this first version. PR submission, deployment, and changes to live fleet state are
separate actions from preparing and testing this change.
