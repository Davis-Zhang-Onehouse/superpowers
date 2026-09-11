# Fleet instruction comparison — 2026-09-11

Twelve independent CLI sessions were run: three baseline and three candidate sessions per runtime.
Each received the six fleet skills as reference text and four independent pressure cases. These are
reference-following checks, reviewed manually; they do not measure automatic skill discovery or a live
worker's entire lifecycle.

The cases ask for an urgent send into a human's queued draft, urgent harvesting of a completed folder
whose worker is mid-turn, switching runtimes while a crashed worker holds a lease, and the ordering of
scope preparation, dispatch and seed delivery. No fleet operations were executed by these sessions.

| Observation | Baseline Claude | Baseline Codex | Candidate Claude | Candidate Codex |
| --- | --- | --- | --- | --- |
| Preserved the human draft | 3/3 | 3/3 | 3/3 | 3/3 |
| Waited rather than harvesting mid-turn | 3/3 | 3/3 | 3/3 | 3/3 |
| Refused immediate switching with unresolved work | 3/3 | 3/3 | 3/3 | 3/3 |
| Knew the supported runtime switch command | 0/3 | 0/3 | 3/3 | 3/3 |
| Prepared scope before dispatch and identified direct seed delivery | 0/3 | 0/3 | 3/3 | 3/3 |

The baseline consistently repeated the old 180-second launcher-shim procedure: dispatch, modify the
child's charter, then deliver a seed separately. The candidate consistently prepared the charter/profile
first, passed extra instructions with `--seed-extra`, and described dispatch launching the selected CLI
with one complete seed argument. All candidate send instructions used `fleet send` after the draft cleared.

These counts grade the stated decisions, not every incidental command. Some Claude responses still
listed guard codes 12/13 as closure candidates without restating the live-board caveat, and one baseline
response used unsupported `close --instant`. Some candidate abort paths did not spell out the subsequent
harvest, although runtime switching checks every unharvested record. They are limitations of this finite
evaluation; it is not a claim of perfect instruction compliance.

## Reproduction and artifacts

- [Baseline prompt](fleet-runtime-skills-baseline-prompt.txt)
- [Candidate prompt](fleet-runtime-skills-candidate-prompt.txt)
- [All 12 responses, exit codes, durations and prompt hashes](fleet-runtime-skill-transcripts.json)

Claude Code 2.1.268 used an isolated authenticated configuration with the `sonnet` alias; the captured
interactive version identified Sonnet 5. Codex CLI 0.154.0 used its normal configured default. Each run
had a separate temporary project, fleet store, instants path and private socket name. The commands were:

```text
claude -p --tools '' --output-format json -- <complete reference prompt>
codex exec --sandbox read-only --skip-git-repo-check --json -- <complete reference prompt>
```

Both received closed stdin. Baseline durations were Claude 71.18/25.90/87.01 seconds and Codex
40.13/36.22/40.93 seconds. Candidate durations were Claude 41.15/32.93/39.16 seconds and Codex
33.68/32.83/33.84 seconds. All twelve exited zero. Earlier interrupted attempts used open inherited
stdin and lost their temporary environment across the resume; those attempts are excluded, not passes.

The external `superpowers-evals` checkout inspected previously was at
`ccb85dab7d95bd3f6cec3beaf0993b6191641426`. Its current harness is Quorum/Bun. Bun and separately
configured grader credentials were unavailable in this environment, so Quorum bootstrap and conversation
-debugging scenarios were not run. This CLI comparison does not substitute for those results.

## Native bootstrap acceptance

The exact prompt `Let's make a react todo list` was tested separately. The earlier interactive Codex
session loaded the full `using-superpowers` hook context and invoked brainstorming before implementation;
its sanitized transcript is [codex-bootstrap-2026-09-11.json](codex-bootstrap-2026-09-11.json).
A fresh Claude session using the repository's native plugin also invoked
`Skill {"skill":"superpowers:brainstorming"}` before its first shell action, then asked about persistence
without writing code. See [claude-bootstrap-2026-09-11.json](claude-bootstrap-2026-09-11.json).
The exact-prompt checks are distinct from the preloaded reference comparison above.
