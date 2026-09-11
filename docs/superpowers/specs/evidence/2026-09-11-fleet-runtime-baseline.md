# Runtime baseline — 2026-09-11

Implementation starts at `31f2c2b`, in the isolated `feat/fleet-runtime-selection`
checkout. No production fleet store or tmux session was used.

Versions measured locally: Claude Code 2.1.268 (configured Sonnet alias displayed
Sonnet 5), Codex CLI 0.154.0 (configured default gpt-6-astra), tmux 3.2a.

The session, seedcheck, peers, store, and root-resolution baseline passed: 181
tests. After adding the Codex hook, all 1,733 existing fleet unit tests passed in
105.812 seconds. Logs are retained locally under
`.private-journal/runtime-evidence/` and are not release evidence for the unfinished
runtime implementation.

The committed `fleet/it/fixtures/runtime/manifest.json` attributes raw ANSI frames
to actual actions in a private 100-column, 35-row tmux server. Both CLIs have idle,
queued, busy, and dialog captures. Busy was observed during a shell delay. Claude
initially reached an account quota dialog; after the human switched accounts,
the private configuration was refreshed and Claude completed `Reply with READY
only.` successfully. No extra usage purchase was approved or attempted.

Codex's idle prompt uses `›`, with dim placeholder text. Its header scrolls away;
the model/path footer remains. Normal-intensity input distinguishes queued text
from the placeholder. Trust and tool approval screens are dialogs, not idle.
Claude uses `❯`, an input border, and a status row containing permission-mode or
interrupt hints. Bottom padding is not content.

The native Codex process is a child of the Node launcher. The launcher executable
is `node`; the worker executable is the installed vendor binary ending in
`bin/codex`, with process comm `codex`. A Node argv mentioning Codex does not prove
worker identity. Claude runs a native executable under its versioned installation
directory, with comm `claude`. Pane ancestry is required to assign either worker
to a tmux session.

In a clean native-plugin Codex session, the exact message `Let's make a react
todo list` caused the agent to read `using-superpowers` and `brainstorming`, inspect
the empty project, and ask a scope question before writing code. The baseline
manifest disabled lifecycle hooks, however, so this does not establish bootstrap
injection at startup. Candidate hook trust, resume, compaction, multiline delivery,
and complete fleet lifecycle validation remain pending.

The outer tool sandbox could not reliably preserve a tmux server or expose its
processes across invocations. Live observations therefore used an explicitly
approved persistent private test driver outside that outer sandbox. Both CLIs
retained their own normal permission policies. Captures and transcripts remain
in the private evidence directory; credentials and full configuration files are
excluded from tracked evidence.

## Follow-up: executable alias identity

The real dispatch probe found a distinction the original interactive probe did not exercise. On Claude
Code 2.1.268, launching `/home/ubuntu/.local/bin/claude` yields `/proc/PID/comm = claude`, while launching
its resolved target `/home/ubuntu/.local/share/claude/versions/2.1.268` yields `comm = 2.1.268`.
`/proc/PID/exe` names the same versioned executable in both cases; both `-p` probe invocations exited zero.
Resolving away the executable symlink therefore breaks the `pgrep -x claude` census and seed verification.
Launch configuration must retain the caller's absolute executable alias. This was measured with isolated
configuration and a finite `Reply exactly OK` prompt, not inferred from the filename alone.
