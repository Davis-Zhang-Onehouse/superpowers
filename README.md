# Superpowers

**This fork adds Fleet: infrastructure for coordinating long-running coding agents.** Superpowers provides the engineering skills; Fleet adds isolated worker checkouts, durable task context, an evidence-backed roadmap, and a coordinator that dispatches and reviews work. You set the direction without becoming the message bus between sessions.

**Here for Fleet? Start with the [Fleet quickstart](#fleet-quickstart).** The official Superpowers marketplace installs upstream Superpowers, not this fork's Fleet additions. The upstream overview and harness instructions are retained below for reference.

For the story behind the workflow, read [Closing the Loop on My Coding Workflow](docs/fleet-introduction.md).

Superpowers is a complete software development methodology for your coding agents, built on top of a set of composable skills and some initial instructions that make sure your agent uses them.

## Table of Contents

- [Fleet quickstart](#fleet-quickstart)
  - [Create a Fleet root](#1-create-a-fleet-root)
  - [Install the fork in your runtime](#2-install-the-fork-in-your-runtime)
  - [Prepare worker checkouts](#3-prepare-worker-checkouts)
  - [Launch your coordinator](#4-launch-your-coordinator)
  - [Use Fleet day to day](#5-use-fleet-day-to-day)
- [How it works](#how-it-works)
- [Commercial Services](#commercial-services)
- [Getting Started](#installation)
  - [Claude Code](#claude-code)
  - [Antigravity](#antigravity)
  - [Codex App](#codex-app)
  - [Codex CLI](#codex-cli)
  - [Cursor](#cursor)
  - [Devin CLI](#devin-cli)
  - [Factory Droid](#factory-droid)
  - [Gemini CLI](#gemini-cli)
  - [GitHub Copilot CLI](#github-copilot-cli)
  - [Grok Build CLI](#grok-build-cli)
  - [Kimi Code](#kimi-code)
  - [OpenCode](#opencode)
  - [Pi](#pi)
  - [Qwen Code](#qwen-code)
  - [Hermes Agent](#hermes-agent)
  - [Muse](#muse)
- [The Basic Workflow](#the-basic-workflow)
- [When Something Goes Wrong](#when-something-goes-wrong)
- [Community](#community)
- [What's Inside](#whats-inside)
- [Philosophy](#philosophy)
- [Contributing](#contributing)
- [Updating](#updating)
- [License](#license)
- [Visual companion telemetry](#visual-companion-telemetry)

## Fleet quickstart

This walkthrough creates a separate Fleet root, three execution slots (one coordinator plus two workers), and a shared directory for task records. It uses the source checkout directly; no Fleet release deployment is needed for a first run.

Start on **Linux**, with **Python 3.10+**, **Git**, **Bash**, **tmux**, and either **Claude Code or Codex CLI** installed. Fleet's Python package uses only the standard library. Your project's build tools and dependencies are separate prerequisites. Workers are real CLI sessions and consume your account's usage; begin with a small cap.

Choose one runtime per fleet, including its coordinator. Configure its model through the CLI, not Fleet. See [runtime support and measured CLI versions](docs/README.fleet-runtimes.md) if your terminal or CLI version behaves differently.

### 1. Create a Fleet root

Run these commands in a fresh Bash shell, with no `FLEET_*` settings inherited from another fleet. Use a new directory **under your home directory**, not your home directory itself or a directory inside an existing Fleet root. The root name also names its dedicated tmux server, so choose a distinct name for each fleet.

```bash
export FLEET_SETUP_ROOT="$HOME/fleet-demo"
mkdir -p "$FLEET_SETUP_ROOT"
git clone --branch live https://github.com/Davis-Zhang-Onehouse/superpowers.git \
  "$FLEET_SETUP_ROOT/superpowers"

cd "$FLEET_SETUP_ROOT"
./superpowers/bin/fleet root-init --path "$FLEET_SETUP_ROOT" --name demo
mkdir -p "$FLEET_SETUP_ROOT/efforts/demo/instants"
. "$FLEET_SETUP_ROOT/superpowers/scripts/fleet-env.sh" \
  "$FLEET_SETUP_ROOT/efforts/demo/instants"

fleet runtime
fleet leases
```

The environment script adds Fleet to `PATH` and selects this root's store, tmux server, and task-record directory. An empty pool is expected at this point. Check that Fleet's `root` line names your new directory before continuing.

### 2. Install the fork in your runtime

Pick **one** of the following. Install the plugin in the same runtime configuration that workers will use. If you already have upstream Superpowers enabled there, disable that copy first to avoid loading both versions. Review this fork and its hooks before trusting them.

#### Claude Code setup

Claude workers resolve their configuration through a workspace-owner map. Set up an explicit map for this root instead of relying on the machine-specific default:

```bash
fleet runtime --set claude
export CLAUDE_OWNERS_MAP="$FLEET_SETUP_ROOT/claude-owners.tsv"
export CLAUDE_CONFIG_DIR="$FLEET_SETUP_ROOT/.claude"
mkdir -p "$CLAUDE_CONFIG_DIR"

# Replace the email with the account that owns these workspaces.
printf '%s\t%s\n' "$FLEET_SETUP_ROOT" 'you@example.com' > "$CLAUDE_OWNERS_MAP"
claude auth login
claude plugin marketplace add "$FLEET_SETUP_ROOT/superpowers" --scope user
claude plugin install superpowers@superpowers-dev --scope user
```

This is a new root-local Claude configuration; signing in elsewhere does not configure it. Keep `CLAUDE_OWNERS_MAP` exported in shells that dispatch work. The launcher uses Claude's `auto` permission mode and `--remote-control`; your CLI/account must support those options.

#### Codex CLI setup

Codex workers use your existing `CODEX_HOME`, or `$HOME/.codex` if unset. Authenticate, then give that same configuration the superpowers skills:

```bash
fleet runtime --set codex
codex login
bash "$FLEET_SETUP_ROOT/superpowers/scripts/fleet-codex-skills.sh" \
  --codex-home "${CODEX_HOME:-$HOME/.codex}" --releases "$FLEET_RELEASES" --dry-run
# then the same command without --dry-run
```

On a root that deploys releases, this writes one link, `<codex-home>/skills/superpowers -> $FLEET_RELEASES/current/skills`, so every deploy moves codex workers onto the deployed skills, the same way the marketplace entry moves claude workers. Codex lists them as `superpowers:<name>`, and a worker loads one by reading its `SKILL.md` ([codex-tools.md](skills/using-superpowers/references/codex-tools.md)). `fleet dispatch --runtime codex` refuses a `CODEX_HOME` that cannot see the core skills, and `scripts/release-postflight.sh` checks the link after each deploy. The link is used rather than `codex plugin marketplace add`, which records the release `current` resolves to today, and rather than `codex plugin add`, which copies a snapshot. Neither follows a deploy.

A root that runs straight from this checkout, with nothing deployed under `$FLEET_RELEASES/current` yet, can install the plugin instead: `codex plugin marketplace add "$FLEET_SETUP_ROOT/superpowers"`, then `codex plugin add superpowers@superpowers-dev`. Re-run that after you update the checkout. For the plugin, keep native hooks enabled, review and trust its hook, and start a fresh session after installation. See the official [plugin instructions](https://developers.openai.com/codex/plugins) and [hook settings](https://developers.openai.com/codex/hooks). Fleet may require specific command approvals for tmux and peer-process inspection outside the Codex sandbox; do not disable the sandbox globally to get started.

#### Check that skills actually load

Before dispatching, open your selected CLI in a scratch directory under this root and send exactly:

```text
Let's make a react todo list
```

The agent should load `using-superpowers` and start brainstorming **before writing code**. Stop the smoke-test session after confirming this. A plugin appearing in a list is not enough: Fleet's coordination depends on its skills loading into new sessions.

### 3. Prepare worker checkouts

A **slot** is an execution directory containing one or more repositories. A task's **instant** is its durable context record, stored separately from the checkout. A **golden workspace** is the prepared template Fleet copies when creating slots.

Replace the URL below with your project, check out the intended starting branch, and install its dependencies in the golden workspace before copying it:

```bash
export FLEET_PROJECT_URL='https://github.com/YOUR-ORG/YOUR-PROJECT.git'
mkdir -p "$FLEET_SETUP_ROOT/golden"
git clone "$FLEET_PROJECT_URL" "$FLEET_SETUP_ROOT/golden/project"

# Do any project-specific checkout/build setup in golden/project now.
fleet set-golden --path "$FLEET_SETUP_ROOT/golden"
fleet clone --slot "$FLEET_SETUP_ROOT/ws1" --verify-repos project
fleet clone --slot "$FLEET_SETUP_ROOT/ws2" --verify-repos project
fleet clone --slot "$FLEET_SETUP_ROOT/ws3" --verify-repos project
fleet leases
```

You should now see three enrolled, unleased slots. `fleet clone` copies the whole golden directory, verifies the named repositories' HEADs, then enrolls the slot. Use ordinary, self-contained Git clones for this walkthrough, not linked worktrees; keep credentials and unrelated files out of the golden template. Do not enroll the golden workspace itself.

Your layout is now:

```text
fleet-demo/
├── .fleet-root                  # fleet identity
├── .fleet/                      # records, pool, leases, runtime selection
├── superpowers/                 # Fleet CLI + this fork's skills
├── golden/project/              # prepared source template; not a worker
├── ws1/project/                 # independent execution slots
├── ws2/project/
├── ws3/project/
└── efforts/demo/instants/        # coordinator and worker task records
    └── …-inflight-append-…/      # created on dispatch
        ├── CHARTER.md
        ├── HANDOFF.md
        └── .fleet/roadmap.json   # the coordinator's project roadmap
```

### 4. Launch your coordinator

Create `efforts/demo/brief.md` in your editor. Give it a small, concrete first goal, acceptance criteria, and limits. For example:

```text
You are the coordinator for this effort. Load coordinating-instants and using-fleet.
The project repository is named project inside each execution slot.

Goal: assess this project's test coverage before we change its behavior.
Done means: a reproducible baseline test result, a map of the existing tests,
and a ranked list of gaps, each backed by a code path or observed test result.

Write the effort charter and propose a dependency-aware roadmap for my approval.
After approval, prepare task-specific worker profiles and dispatch with a fleet
cap of 3, including yourself: at most two workers alongside this coordinator.
Pin each worker's repository baseline and keep the roadmap evidence-backed.
Do not change application code, push branches, open PRs, or deploy anything.
Stop when the acceptance criteria are met; escalate decisions outside this scope.
```

Then launch the coordinator using the included role profile and your brief:

```bash
fleet dispatch \
  --profile "$FLEET_SETUP_ROOT/superpowers/skills/using-fleet/profiles/coordinator" \
  --title demo-coordinator \
  --seed-extra "$FLEET_SETUP_ROOT/efforts/demo/brief.md" \
  --cap 3

fleet-view
tmux -L "$FLEET_TMUX_SOCKET" list-sessions
```

Dispatch creates the coordinator's instant, leases a slot, and starts its CLI in tmux. Attach to the session named in the output, handle any trust/authentication dialogs, review the proposed roadmap, and approve it when ready. The coordinator then prepares and dispatches the first workers. No separate `fleet init` is needed for this path.

The coordinator is a long-running agent session following a workflow, **not an unattended scheduler installed by this quickstart**. Keep it running, authorize an appropriate continuation/monitoring mechanism in your harness, and expect human input for approval dialogs or out-of-scope decisions. A tmux session surviving a disconnect does not itself guarantee the agent keeps taking turns.

### 5. Use Fleet day to day

In each new terminal, restore the environment before issuing Fleet commands:

```bash
export FLEET_SETUP_ROOT="$HOME/fleet-demo"
cd "$FLEET_SETUP_ROOT"
. "$FLEET_SETUP_ROOT/superpowers/scripts/fleet-env.sh" \
  "$FLEET_SETUP_ROOT/efforts/demo/instants"
# Claude users also restore the map used for dispatch:
# export CLAUDE_OWNERS_MAP="$FLEET_SETUP_ROOT/claude-owners.tsv"

fleet-view                       # workers and slot occupancy
fleet-view roadmap               # coordinator roadmap; use --instant PATH if needed
fleet board --porcelain           # machine-readable observations
fleet leases                     # execution capacity
```

To interact with a coding session the old way, list the sessions and attach to the one you want:

```bash
tmux -L "$FLEET_TMUX_SOCKET" list-sessions
tmux -L "$FLEET_TMUX_SOCKET" attach -t SESSION_NAME
```

Detach with **Ctrl-b, then d**; this leaves the session running. Review results through the task's assembled context and evidence, not just its last chat message. Let the coordinator follow the review, completion, and harvest workflow before reusing a slot; a worker saying “done” is not a released lease.

**If the first dispatch stalls:** inspect the session for a trust or approval dialog; check `fleet runtime` and `fleet leases`; confirm the selected runtime is authenticated and the fork's plugin loads in that configuration. For Claude owner-resolution errors, check the map and root-local `.claude` directory. For Codex host-access refusals, approve the specific Fleet command and retry. A refusal's `clears when` text names the prerequisite—do not jump to `--force`.

Next steps:

- [Runtime setup, messaging, recovery, and limitations](docs/README.fleet-runtimes.md).
- [Fleet command reference](skills/using-fleet/SKILL.md) and [coordinator workflow](skills/coordinating-instants/SKILL.md).
- [Multi-milestone efforts and PR stacks](skills/running-a-stacked-effort/SKILL.md), once the small first run works.
- [Tested Fleet releases and deployment](skills/releasing-fleet/SKILL.md), before updating infrastructure under active work. This quickstart runs from source; pulling new code into that checkout changes the CLI future commands execute. Updating the CLI and refreshing a runtime's installed plugin are separate operations.

## How it works

It starts from the moment you fire up your coding agent. As soon as it sees that you're building something, it *doesn't* just jump into trying to write code. Instead, it steps back and asks you what you're really trying to do. 

Once it's teased a spec out of the conversation, it shows it to you in chunks short enough to actually read and digest. 

After you've signed off on the design, your agent puts together an implementation plan that's clear enough for an enthusiastic junior engineer with poor taste, no judgement, no project context, and an aversion to testing to follow. It emphasizes true red/green TDD, YAGNI (You Aren't Gonna Need It), and DRY. 

Next up, once you say "go", it launches a *subagent-driven-development* process, having agents work through each engineering task, inspecting and reviewing their work, and continuing forward. It's not uncommon for your agent to work autonomously for a couple hours at a time without deviating from the plan you put together.

There's a bunch more to it, but that's the core of the system. And because the skills trigger automatically, you don't need to do anything special. Your coding agent just has Superpowers.

## Commercial Services

If you're using Superpowers in enterprise and could benefit from commercial support, additional tooling, or managed spending, please don't hesitate to drop us a line at sales@primeradiant.com.

## Installation

These are the **upstream Superpowers** harness instructions. To install this fork with Fleet, use the [Fleet quickstart](#fleet-quickstart) above. Fleet's worker runtimes are Claude Code and Codex CLI; the other harness integrations below are not Fleet runtime support claims.

Installation differs by harness. If you use more than one, install Superpowers separately for each one.

### Claude Code

Superpowers is available via the [official Claude plugin marketplace](https://claude.com/plugins/superpowers)

#### Official Marketplace

- Install the plugin from Anthropic's official marketplace:

  ```bash
  /plugin install superpowers@claude-plugins-official
  ```

#### Superpowers Marketplace

The Superpowers marketplace provides Superpowers and some other related plugins for Claude Code.

- Register the marketplace:

  ```bash
  /plugin marketplace add obra/superpowers-marketplace
  ```

- Install the plugin from this marketplace:

  ```bash
  /plugin install superpowers@superpowers-marketplace
  ```

### Antigravity

Install Superpowers as a plugin from this repository:

```bash
agy plugin install https://github.com/obra/superpowers
```

Antigravity runs the plugin's session-start hook, so Superpowers is active from
the first message. Reinstall with the same command to update.

### Codex App

Superpowers is available via the [official Codex plugin marketplace](https://github.com/openai/plugins).

- In the Codex app, click on Plugins in the sidebar.
- You should see `Superpowers` in the Coding section.
- Click the `+` next to Superpowers and follow the prompts.

### Codex CLI

Superpowers is available via the [official Codex plugin marketplace](https://github.com/openai/plugins).

- Open the plugin search interface:

  ```bash
  /plugins
  ```

- Search for Superpowers:

  ```bash
  superpowers
  ```

- Select `Install Plugin`.

### Cursor

- In Cursor Agent chat, install from marketplace:

  ```text
  /add-plugin superpowers
  ```

- Or search for "superpowers" in the plugin marketplace.

### Devin CLI

- Install the plugin from this repository:

  ```bash
  devin plugins install obra/superpowers
  ```

- Update to the latest version with:

  ```bash
  devin plugins update superpowers
  ```

### Factory Droid

- Register the marketplace:

  ```bash
  droid plugin marketplace add https://github.com/obra/superpowers
  ```

- Install the plugin:

  ```bash
  droid plugin install superpowers@superpowers
  ```

### Gemini CLI

- Install the extension:

  ```bash
  gemini extensions install https://github.com/obra/superpowers
  ```

- Update later:

  ```bash
  gemini extensions update superpowers
  ```

### GitHub Copilot CLI

- Register the marketplace:

  ```bash
  copilot plugin marketplace add obra/superpowers-marketplace
  ```

- Install the plugin:

  ```bash
  copilot plugin install superpowers@superpowers-marketplace
  ```

### Grok Build CLI

Superpowers is available via the [official Grok plugin marketplace](https://github.com/xai-org/plugin-marketplace).

- Install the plugin from xAI's official marketplace:

  ```bash
  grok plugin install superpowers@xai-official --trust
  ```

- Or open the marketplace in the TUI, search for Superpowers, and install it:

  ```text
  /marketplace
  ```

### Kimi Code

Superpowers is available in Kimi Code's plugin marketplace.

- Open Kimi Code's plugin manager:

  ```text
  /plugins
  ```

- Go to `Marketplace` > `Superpowers` and install it.

- Or install directly from this repository:

  ```text
  /plugins install https://github.com/obra/superpowers
  ```

- Detailed docs: [docs/README.kimi.md](docs/README.kimi.md)

### OpenCode

OpenCode uses its own plugin install; install Superpowers separately even if you
already use it in another harness.

- Tell OpenCode:

  ```
  Fetch and follow instructions from https://raw.githubusercontent.com/obra/superpowers/refs/heads/main/.opencode/INSTALL.md
  ```

- Detailed docs: [docs/README.opencode.md](docs/README.opencode.md)

### Pi

Install Superpowers as a Pi package from this repository:

```bash
pi install git:github.com/obra/superpowers
```

For local development, run Pi with this checkout loaded as a temporary package:

```bash
pi -e /path/to/superpowers
```

The Pi package loads the Superpowers skills and a small extension that injects the `using-superpowers` bootstrap at session startup and again after compaction. Pi has native skills, so no compatibility `Skill` tool is required. Subagent and task-list tools remain optional Pi companion packages.

### Qwen Code

Qwen Code installs plugins from Claude Code marketplaces directly.

- Install the plugin from this repository, and pick `superpowers` when prompted:

  ```bash
  qwen extensions install obra/superpowers
  ```

- Update later:

  ```bash
  qwen extensions update superpowers
  ```

### Hermes Agent

Install Superpowers as a Hermes plugin from this repository:

```bash
hermes plugins install obra/superpowers --enable
```

Restart any active Hermes sessions after installing. Note: Hermes has no
post-compaction hook, so a very long session that compacts over its first
turn loses the bootstrap — start a fresh session if skills stop triggering.

### Muse

Superpowers is available as a native Muse plugin — same repo, same skills, all harnesses. The `using-superpowers` bootstrap is injected via the native `SessionStart` hook alongside Claude Code, Codex, Cursor, Gemini, Pi, and the rest — no per-session opt-in.

- Install from a local checkout:

  ```bash
  muse plugins install ./
  muse plugins approve superpowers
  ```

  Or clone and install:

  ```bash
  git clone https://github.com/obra/superpowers.git
  muse plugins install ./superpowers
  muse plugins approve superpowers
  ```

- Update later:

  ```bash
  muse plugins update superpowers
  ```

Restart any active Muse sessions after installing so the `SessionStart` hook takes effect — skills are active immediately, hooks require approval on first install. To verify, start a fresh session and send `Let's make a react todo list` — a working install auto-triggers `brainstorming` before any code is written. Version is tracked in `.version-bump.json` so `scripts/bump-version.sh` keeps it in sync.

## The Basic Workflow

1. **brainstorming** - Activates before writing code. Refines rough ideas through questions, explores alternatives, presents design in sections for validation. Saves design document.

2. **using-git-worktrees** - Activates after design approval. Creates isolated workspace on new branch, runs project setup, verifies clean test baseline.

3. **writing-plans** - Activates with approved design. Breaks work into bite-sized tasks (2-5 minutes each). Every task has exact file paths, complete code, verification steps.

4. **subagent-driven-development** or **executing-plans** - Activates with plan. Either dispatches a fresh subagent per task with a review after each (most thorough), or implements every task inline in the current session with one fresh review of the whole branch at the end (cheapest).

5. **test-driven-development** - Activates during implementation. Enforces RED-GREEN-REFACTOR: write failing test, watch it fail, write minimal code, watch it pass, commit. Deletes code written before tests.

6. **requesting-code-review** - Activates between tasks. Reviews against plan, reports issues by severity. Critical issues block progress.

7. **finishing-a-development-branch** - Activates when tasks complete. Verifies tests, presents options (merge/PR/keep/discard), cleans up worktree.

**The agent checks for relevant skills before any task.** Mandatory workflows, not suggestions.

## When Something Goes Wrong

Sometimes a session misbehaves: a skill fires when it shouldn't, stays silent when it should, or the agent ignores its plan, repeats work, or burns more tokens than you'd expect. Ask your coding agent to "figure out what went wrong with superpowers in this session" and it will invoke the **diagnosing-superpowers** skill. To examine an earlier session, name it: "figure out what went wrong with superpowers in session `<id>`".

The skill reads the session transcript, reports what happened with line-level evidence, and, if you want, packages a scrubbed bundle for a bug report.

## Community

Superpowers is built by [Jesse Vincent](https://blog.fsck.com) and the rest of the folks at [Prime Radiant](https://primeradiant.com).

- **Discord**: [Join us](https://discord.gg/35wsABTejz) for community support, questions, and sharing what you're building with Superpowers
- **Issues**: https://github.com/obra/superpowers/issues
- **Release announcements**: [Sign up](https://primeradiant.com/superpowers/) to get notified about new versions

## What's Inside

### Skills Library

**Testing**
- **test-driven-development** - RED-GREEN-REFACTOR cycle (includes testing anti-patterns reference)

**Debugging**
- **systematic-debugging** - 4-phase root cause process (includes root-cause-tracing, defense-in-depth, condition-based-waiting techniques)
- **verification-before-completion** - Ensure it's actually fixed
- **diagnosing-superpowers** - Work out what went wrong in a session, with evidence; export a scrubbed bundle or file an issue

**Collaboration** 
- **brainstorming** - Socratic design refinement
- **writing-plans** - Detailed implementation plans
- **executing-plans** - Inline plan execution: one context, one final review
- **dispatching-subagents** - Concurrent subagent workflows inside ONE session
- **coordinating-instants** - Coordinate an effort across dispatched worker instants (fleet)
- **working-as-a-dispatched-instant** - You ARE a dispatched worker instant (fleet)
- **using-fleet** - The fleet command surface: verbs, exit codes, porcelain
- **requesting-code-review** - Pre-review checklist
- **receiving-code-review** - Responding to feedback
- **using-git-worktrees** - Parallel development branches
- **finishing-a-development-branch** - Merge/PR decision workflow
- **subagent-driven-development** - Fast iteration with two-stage review (spec compliance, then code quality)

**Meta**
- **writing-skills** - Create new skills following best practices (includes testing methodology)
- **using-superpowers** - Introduction to the skills system

## Philosophy

- **Test-Driven Development** - Write tests first, always
- **Systematic over ad-hoc** - Process over guessing
- **Complexity reduction** - Simplicity as primary goal
- **Evidence over claims** - Verify before declaring success

Read [the original release announcement](https://blog.fsck.com/2025/10/09/superpowers/).

## Contributing

The general contribution process for Superpowers is below. Keep in mind that we don't generally accept contributions of new skills and that any updates to skills must work across all of the coding agents we support.

1. Fork the repository
2. Switch to the 'dev' branch
3. Create a branch for your work
4. Follow the `writing-skills` skill for creating and testing new and modified skills
5. Submit a PR, being sure to fill in the pull request template.

Skill-behavior tests use the drill eval harness from [superpowers-evals](https://github.com/prime-radiant-inc/superpowers-evals/), cloned into `evals/` — see `evals/README.md` for setup. Plugin-infrastructure tests live at `tests/` and run via the relevant `run-*.sh` or `npm test`.

See `skills/writing-skills/SKILL.md` for the complete guide.

## Updating

Superpowers updates are somewhat coding-agent dependent, but are often automatic.

## License

MIT License - see LICENSE file for details

## Visual companion telemetry

Because skills and plugins don't provide any feedback to creators, we have no idea how many of you are using Superpowers. By default, the Prime Radiant logo on brainstorming's optional visual companion feature is loaded from our website. It includes the version of Superpowers in use. It does not include any details about your project, prompt, or coding agent. We don't see your clicks or anything about what you're building. This helps us have a rough idea of how many folks are using Superpowers and which version of Superpowers they're using. It's 100% optional. To disable this, set the environment variable `SUPERPOWERS_DISABLE_TELEMETRY` to any true value. Superpowers also honors Claude Code's `DISABLE_TELEMETRY` and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` opt-outs.
