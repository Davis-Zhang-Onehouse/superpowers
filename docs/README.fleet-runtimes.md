# Fleet runtimes

The box's saved runtime (`fleet runtime`) is the DEFAULT CLI for a dispatch; Claude is the default for an
existing store. Each dispatch may choose its own runtime and model instead, so one fleet can run claude and codex
workers side by side:

```bash
fleet dispatch --profile "$P" --title "$T" --runtime codex                          # codex's default model
fleet dispatch --profile "$P" --title "$T" --runtime claude --model claude-fable-5-1
```

Resolution: runtime = `--runtime` > the profile's `"runtime"` (profile.json) > `fleet runtime`; model = `--model`
> the profile's `"model"` (applied only when the profile's `"runtime"` is the one chosen; a profile `"model"`
without a `"runtime"` is refused) > none. A fleet older than the release carrying these fields ignores a profile's
`"runtime"`/`"model"` silently and dispatches on the box runtime, so check `fleet dispatch --dry-run`'s `runtime` row. No model means no model flag on the argv, so the CLI uses its own
configured model — the launch is then byte-identical to the one before these flags existed. A model reaches the
worker as `claude --model <m>` or `codex -m <m>` (also on `codex resume`); fleet never edits a slot's
`.claude/settings*.json` or `CODEX_HOME/config.toml`, and does not translate model names. The chosen runtime and
model are recorded (`runtime`, `runtime_model`): `board` shows them in its `runtime` column, `brief` in a `runtime`
row, `revive` relaunches the same pair and `resume` adopts under the record's runtime regardless of the box.
A record carrying a model is an unknown field to an older fleet binary, and that binary then refuses the WHOLE store
(everything that enumerates records, which is most of the surface — `board`, `status`, `brief`, `seed-check`,
`dispatch`, `harvest`, `milestone`, `reap`, `runtime`, …), not just that record. Once any
`--model` dispatch exists in a store, do not operate on it with, or roll back to, a fleet older than the release that
introduced `runtime_model`. Default dispatches write no such field and stay readable.
Run these commands from the updated checkout. `fleet-env.sh` normally selects the root's deployed
release, so the next line selects this checkout's CLI for this shell.

```bash
. scripts/fleet-env.sh /absolute/path/to/instants
export PATH="$PWD/bin:$PATH"
fleet runtime
fleet runtime --set codex
# Start a Codex coordinator in the fleet root, then dispatch normally (a worker on a milestone also takes
# --from, --milestone and --lineage-base; the full form is in skills/dispatching-a-wave):
fleet dispatch --profile "$PREPARED_PROFILE" --title "$TITLE" --seed-extra "$TASK_BRIEF"
```

Prepare the complete charter in the profile and any additional instructions in the task brief before
dispatch. Dispatch renders and delivers the seed itself. It exports `FLEET_BIN` for the matching fleet CLI;
the seed tells workers to use `"$FLEET_BIN"` so login-shell PATH changes cannot select an older binary. The repository's
launchers (`scripts/release-gate.sh`, `release-preflight.sh`, `fleet-revive.sh`, `fleet-finished-pids.sh`, `bin/fleet-view`)
deliberately do NOT read it: each runs the `bin/fleet` it ships beside, and its test seam is `FLEET_LAUNCHER_TEST_BIN` (FB-56).
Remove the old fleet `claude` PATH shim:
`scripts/fleet-dispatch-launcher.sh` now reports that dispatch owns this operation.

When the run is finished, complete and harvest every worker, stop the coordinator, and switch from a
normal shell:

```bash
fleet runtime --set claude
```

`fleet runtime --set` changes only that default. A switch still refuses while a record `resume` or `revive` could still act on (an `-inflight-` folder, or an open
record holding its lease or session), a held/interrupted lease, or a live in-scope agent remains. Each blocker
names the verb that clears it. A crashed worker still owns unfinished work: recover it, or deliberately
`fleet abort` it. An aborted record, or one closed after it completed, no longer blocks. Do not delete store
files to bypass the refusal. Read and dry-run commands do not create the setting.
Admission commands wait up to five seconds for another admission to finish. A named lock-timeout
refusal starts no worker; retry after the holder finishes.

## Setup

For a fresh machine or a new project, start with the [Fleet quickstart](../README.md#fleet-quickstart).
It covers root creation, this fork's native plugin installation, workspace-owner configuration,
the golden workspace and worker pool, and launching a coordinator. This page covers runtime-specific
behavior after that bootstrap.

Install and authenticate the CLI you intend to use. The measured terminal fixtures were captured on
Codex CLI 0.154.0 and Claude Code 2.1.268, with tmux 3.2a at 100×35. Other terminal layouts may produce
an indeterminate observation, which refuses messaging rather than guessing input readiness.

Codex uses the dispatching shell's `CODEX_HOME`, or `$HOME/.codex` when unset. Claude uses the existing
`scripts/claude-config-dir.sh` workspace-owner mapping (`CLAUDE_OWNERS_MAP` can name an explicit map).
The selected configuration directory must exist. A codex session YOU start (a coordinator) runs under your own
configuration and may ask for approval to run fleet commands outside its sandbox. Approve the specific fleet
command through the CLI. Denied tmux access fails before dispatch creates a worker record or lease, so an approved
retry does not consume capacity twice.

**Codex WORKERS that fleet launches or revives run unattended (FB-110, operator decision D-45).** Their launch and
resume argv always carry `-a never -s workspace-write -c sandbox_workspace_write.network_access=true
-c check_for_update_on_startup=false`, plus `--add-dir` for FLEET_HOME (the store), FLEET_INSTANTS and, for each
linked worktree at the slot root or one level below, its common dir's `objects`, `refs` and `logs` plus its own
per-worktree git dir. That is how a linked-worktree slot commits, branches and fetches, since codex makes `<root>/.git`
read-only. It is never the whole common dir, whose `hooks/` and `config` would then be writable from the sandbox. The slot itself is the sandbox cwd. No prompt ever appears. A command
the sandbox refuses fails back to the model (a write outside those roots reads `Read-only file system`). Never
danger-full-access, and no knob loosens it; the argv outranks `CODEX_HOME/config.toml`, which fleet never edits.
`dispatch`, `revive` (and its `--dry-run`) print a `codex_policy` row, and `brief`'s `runtime` row carries the same
text. Roots listed under `[sandbox_workspace_write] writable_roots` in `CODEX_HOME/config.toml` still apply on top, and
the row says so because fleet does not read that file. The launcher exports GH_TOKEN from `~/.gh-token-<root>` for codex as for claude. Without it, `gh` in the
sandbox acts as whatever account `~/.config/gh` names.
Known limit (measured on 0.156.1): the sandbox runs each command in its own PID namespace, so `pgrep`/`/proc` see
only the sandbox. Verbs whose cli.py reach includes a process or pane probe (`board`, `pane-guard`, `close`,
`harvest`, `reap`, `abort`, `resume`, `revive`, `send`, `status`, `runtime`, `declare`'s pane check, `seed-check`,
`dispatch`) cannot see host processes when a codex worker runs them (static map in the FB-110 instant,
evidence/01-settle/census-verbs.txt). The verbs a fix worker reports and finishes with (`brief`, `propose`, `review`,
`park`, `complete`, `base-check`) reach none, but it is a reason to keep coordinator, stack and release instants
on claude. tmux works inside the sandbox only because the network is on. `FLEET_CODEX_BIN` and `FLEET_CLAUDE_BIN` can name the actual executable; do not point them at
a seed-delivery shim. Claude's existing `REAL_CLAUDE` override
remains supported. Executable, configuration directory and runtime are recorded for recovery; credentials
are never copied into fleet records or launchers.

**Codex skills (FB-111).** A codex worker gets the superpowers skills through one link in its `CODEX_HOME`:
`scripts/fleet-codex-skills.sh --codex-home <dir> --releases "$FLEET_RELEASES"` (`--dry-run` first, `--check` to
verify) writes `<dir>/skills/superpowers -> $FLEET_RELEASES/current/skills`. codex-cli 0.156 scans `CODEX_HOME/skills`
and follows links, so it lists every skill as `superpowers:<name>`, and every deploy moves them, the way the claude
marketplace entry moves claude's. Measured on 0.156.1: `codex plugin marketplace add` records the release `current`
resolves to today, and `codex plugin add` git-clones and copies a snapshot, so neither follows a deploy.
`fleet dispatch --runtime codex` refuses (exit 4) a `CODEX_HOME` that cannot see the core skills, and names this
command; `--override "<reason>"` launches without them. The codex seed and `fleet brief` tell the worker how to load
a skill: read its `SKILL.md` with the shell, starting with `superpowers:using-superpowers`, and use
`using-superpowers/references/codex-tools.md` for tool names. The seed stands in for the plugin's SessionStart
hook, which the link route does not install. `scripts/release-postflight.sh` verifies the link at `<root>/.codex` on every root that
has one. A `CODEX_HOME` elsewhere is covered only by the dispatch refusal.

For the plugin route (a root that runs from a checkout, or an interactive codex outside fleet), install **this fork** as a native plugin in the selected CLI, following the quickstart's
[runtime installation](../README.md#2-install-the-fork-in-your-runtime), not the upstream marketplace instructions. The Codex package includes
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
the matching draft, presses Enter once, and observes consumption. Temporary redraws are observed within
the existing deadline; they never cause another insertion or submission. A refusal types nothing; an uncertain
delivery requires inspection before retrying. It never clears another person's draft. Multiline input
is supported for the captured layouts; large or unfamiliar editor layouts can be refused.

`revive` requires the original lease and an unoccupied pane/workspace. It validates the explicit UUID
against a transcript in the recorded configuration and the original workspace. It never selects the
newest transcript or starts fresh as a fallback. Revival verifies the exact native resume argument;
`seed-check` may still be unverifiable for a resumed session. Revival follows the record's runtime and model,
never the fleet selection. `scripts/fleet-revive.sh plan|revive`, run from inside a fleet root, finds every
`DEAD` record on that root's board, derives the transcript from the record's seed, and calls `fleet revive` for
each under its own runtime (see `skills/reviving-dead-panes`). `fleet resume` still means adoption.

Codex has no verified background CI wake mechanism in this integration. `awaiting-ci` is refused even
with a watcher attestation, and that worker continues to consume capacity. Claude's watcher contract
is unchanged. Systematic debugging's evidence and phase requirements apply in either harness.

Use the updated fleet CLI for all operations on records containing runtime metadata. Older binaries
cannot safely operate on the extended records. Both native CLI lifecycles have been exercised, including
messaging, debugging, exact-session revival and harvest. See the [validation report](superpowers/specs/evidence/2026-09-11-fleet-runtime-validation.md)
for the measured revisions, integration results and remaining evaluation limits before deployment.

## Repeating validation

`bash fleet/it/run-runtime.sh --stubs` tests dispatch and switch-back using attributed stand-ins (RT1) and the
per-dispatch runtime/model choice on a claude box (RT2). `bash fleet/it/run-runtime.sh --choice-live` spends two
real trivial model turns to prove the same on the native CLIs: a claude worker on `claude-fable-5-1` and a codex
worker on codex's default model, both dispatched onto a box set to claude, each killed and revived. Codex runs in a
private `CODEX_HOME` inside the attempt directory: the credential is copied in and removed when the run exits, the
source configuration's top-level settings are copied so "no `-m`" still means that root's configured model, and the
checkout is pre-trusted there. `RTC_CODEX_HOME` names the source (default `/home/ubuntu/davis_root/.codex`) and is only
read. The harness never answers a folder-trust screen, because the answer persists into the CLI's configuration.
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
