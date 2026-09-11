# Native fleet lifecycle evidence

Measured on source revision `59531ec`, with Claude Code 2.1.268 and Codex CLI 0.154.0.
Each runtime used its own explicit store, authenticated native-plugin configuration, two slots,
and private tmux server. No mixed-runtime fleet was used.

| Claim | Claude evidence | Codex evidence |
| --- | --- | --- |
| Test command outcomes and exit codes | claude/commands.json | codex/commands.json |
| Whole live runner and isolation passed | claude/runner.log | codex/runner.log |
| Tested versions and source revision | claude/environment.json | codex/environment.json |
| Both records harvested | claude/records.json | codex/records.json |
| Both milestones done with attributed evidence | claude/roadmap.json | codex/roadmap.json |
| Worker-produced failure, fix and verification | claude/claudeworker1/evidence/ | codex/codexworker1/evidence/ |
| Independent second worker | claude/claudeworker2/evidence/ | codex/codexworker2/evidence/ |
| Native coordinator and worker exchanges | claude/session-*.json | codex/session-*.json |

Session exports contain user/assistant exchanges and tool results. Internal reasoning and harness
system/developer context are excluded. Terminal frame exports omit trailing blank padding rows. The frames and explicit driver commands complement
those transcripts: the driver issued `apply`, `close`, and `harvest`; the worker models issued their
own review, proposal, and completion commands. Coordinators loaded the coordination skills and read
the roadmap; this is not an evaluation of autonomous model dispatch policy.

The workers were given a subtract-instead-of-add defect and asked to capture the failure before
editing. Both runtimes independently completed the two-worker contract. The runner checked WIP cap,
early-switch refusal, missing-review and premature-harvest refusal, and refusal to message a retired
worker. It switched to the other runtime and back after all workers and the coordinator exited.

Initial runner attempts had setup/assertion errors, documented in the parent validation report.
One earlier Codex send stopped after an indeterminate input observation; it was inspected and recovered
through an explicit session UUID. No automatic resend was used. The fresh runs recorded here passed.

`zombie-before.json` and `zombie-after.json` are a separate finite Linux process fixture, not a model.
A sleep executable named codex exits while its parent defers reaping: `/proc` still lists state Z but
has no executable or cwd. Discovery previously raised a live-process inspection error and now omits
that exited process. The accompanying regression still refuses unreadable processes in state S.
