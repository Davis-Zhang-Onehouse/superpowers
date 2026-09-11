# Fleet runtimes

One fleet uses one CLI runtime. Claude is the default for an existing store. Model choice remains in
that CLI's normal configuration; fleet does not translate model names or mix runtimes within a run.

```bash
. scripts/fleet-env.sh /absolute/path/to/instants
fleet runtime
fleet runtime --set codex
# Start a Codex coordinator in the fleet root, then dispatch normally:
fleet dispatch --profile "$PREPARED_PROFILE" --title "$TITLE" --seed-extra "$TASK_BRIEF"
```

Prepare the complete charter in the profile and any additional instructions in the task brief before
dispatch. Dispatch renders and delivers the seed itself. Remove the old fleet `claude` PATH shim:
`scripts/fleet-dispatch-launcher.sh` now reports that dispatch owns this operation.

When the run is finished, complete and harvest every worker, stop the coordinator, and switch from a
normal shell:

```bash
fleet runtime --set claude
```

A switch refuses while an unharvested record, held/interrupted lease, or live in-scope agent remains.
A crashed worker still owns unfinished work. Recover it or deliberately abort and close out its record;
do not delete store files to bypass the refusal. Read and dry-run commands do not create the setting.

## Setup

Install and authenticate the CLI you intend to use. The measured terminal fixtures were captured on
Codex CLI 0.154.0 and Claude Code 2.1.268, with tmux 3.2a at 100×35. Other terminal layouts may produce
an indeterminate observation, which refuses messaging rather than guessing input readiness.

Codex uses the dispatching shell's `CODEX_HOME`, or `$HOME/.codex` when unset. Claude uses the existing
`scripts/claude-config-dir.sh` workspace-owner mapping (`CLAUDE_OWNERS_MAP` can name an explicit map).
The selected configuration directory must exist. `FLEET_CODEX_BIN` and `FLEET_CLAUDE_BIN` can name the
actual executable; do not point them at a seed-delivery shim. Claude's existing `REAL_CLAUDE` override
remains supported. Executable, configuration directory and runtime are recorded for recovery; credentials
are never copied into fleet records or launchers.

Install the repository as a native plugin in the selected CLI, following its existing setup guide
([Codex](README.codex.md), [Claude Code](../README.md)). The Codex package includes
`hooks/hooks-codex.json` and `hooks/session-start-codex`. Enable native hooks in the CLI configuration,
review and trust the plugin hook when prompted, then start a fresh session. Its SessionStart hook loads
`using-superpowers` for startup, resume, clear and compact events. Merely putting skills on disk does
not prove this bootstrap ran. The exact acceptance prompt is `Let's make a react todo list`; verify
that brainstorming starts before code is written.

## Communication and recovery

```bash
fleet peers
fleet send --id "$ID" --message-file "$MESSAGE_FILE"
fleet revive --id "$ID" --session-id "$SESSION_UUID" --dry-run
fleet revive --id "$ID" --session-id "$SESSION_UUID"
```

`send` checks the record, lease, runtime and pane, observes an empty idle input, pastes once, waits for
the matching draft, presses Enter once, and observes consumption. A refusal types nothing; an uncertain
delivery requires inspection before retrying. It never clears another person's draft. Multiline input
is supported for the captured layouts; large or unfamiliar editor layouts can be refused.

`revive` requires the original lease and an unoccupied pane/workspace. It validates the explicit UUID
against a transcript in the recorded configuration and the original workspace. It never selects the
newest transcript or starts fresh as a fallback. `scripts/fleet-revive.sh` retains its `plan`,
`transcripts`, `launcher`, and `start` entry points. `fleet resume` still means adoption.

Codex has no verified background CI wake mechanism in this integration. `awaiting-ci` is refused even
with a watcher attestation, and that worker continues to consume capacity. Claude's watcher contract
is unchanged. Systematic debugging's evidence and phase requirements apply in either harness.

Use the updated fleet CLI for all operations on records containing runtime metadata. Older binaries
cannot safely operate on the extended records. This implementation is under validation; unit and stub
results alone do not establish a complete live lifecycle. See the runtime evidence reports before
promoting or deploying it.

## Repeating validation

`bash fleet/it/run-runtime.sh --stubs` tests dispatch and switch-back using attributed stand-ins.
For real model coverage, point `RT_LIVE_CONFIG` at a private, authenticated configuration where the
native plugin is installed, then explicitly select the runtime:

```bash
RT_LIVE_CONFIG=/absolute/private/config bash fleet/it/run-runtime.sh --live --runtime codex
```

The live runner starts a coordinator and two workers on a private `itfleet-RTL-` tmux server.
It prints the attachment command for inspecting ordinary trust and permission dialogs; it does not
accept those dialogs automatically. It waits up to 900 seconds per stage (`RT_LIVE_TIMEOUT` overrides).
Command results, terminal frames and worker artifacts remain in the printed attempt directory.
On failure, the server stops and unfinished leases remain for inspection. The real-session recovery
checks and before/after skill evaluations are recorded separately in the validation report.

Worker launchers preserve terminal color attributes even when the calling shell sets `NO_COLOR`;
the guards need those attributes to distinguish suggested prompts from actual drafts.
