# Evidence index — acceptance criteria → artifact → source
Updated: 2026-09-15

| # | Criterion | Artifact (this folder) | What it shows | Source |
|---|-----------|------------------------|---------------|--------|
| 1 | AC-1, AC-2, AC-3 | `test-fleet-revive.log` | 37 checks ok: outside-root, outside-HOME, stale-env, seed matching on both runtimes (real rollout shape, caveat row), decoys, same-start fork, legacy configuration, revive-all ordering, partial failure, seven refusals (incl. a write-time tie and a failed search), empty board | `bash scripts/tests/fleet-revive.sh` @ c88cf04 |
| 2 | AC-1 | `plan-davis_root.log` | from `/home/ubuntu/davis_root`: name davis, server fleet-davis, store derived; three stale exports dropped; nothing DEAD | `cd /home/ubuntu/davis_root && bash superpowers/scripts/fleet-revive.sh plan` |
| 3 | AC-1 | `plan-davis2_root.log` | from `/home/ubuntu/davis2_root` with davis's exports set: davis2's name/server/store; nothing DEAD | same, from davis2_root |
| 4 | AC-1 | `plan-outside-root.log` | from `/home/ubuntu`: refused rc 2 naming the marker | same, from `/home/ubuntu` |
| 5 | AC-3 | `matcher-live-records.log` | the embedded matcher against two live Claude worker records (one transcript each) and two real Codex rollouts whose prompts sit behind injected user blocks (matched), plus a negative control (no match) | matcher extracted from the script @ 96a29bb, run read-only |
| 6 | AC-2 | `e2e-real-verb-revive.log` | scratch root, compiled stand-in named `claude`, real tmux server: DEAD → `revive` rc 0 → RUNNING, `launched_at` moved; second run "nothing to revive"; after kill-server `plan` derives the same UUID | python driver in the session transcript (scratchpad), re-run on 96a29bb |
| 7 | AC-4 | `test-fleet-runtime-helpers.log` | the sibling helper test still passes after dropping the removed subcommands | `bash scripts/tests/fleet-runtime-helpers.sh` |

| 8 | AC-1..3 | `../REVIEW.md` | review round 1: 2 Critical + 5 Important + 7 Minor, all applied or dispositioned; fixes in 96a29bb. Round 2 (verification): all seven round-1 findings confirmed fixed; 1 Important residual + 5 minor applied in c88cf04, 1 routed | reviewer subagents, 2026-09-15 |

## How to regenerate each artifact
- `test-*.log`: the commands in RUNBOOK § Test.
- `plan-*.log`: RUNBOOK § Use, from each directory.
- `matcher-live-records.log`: `sed -n '/<<'"'"'PY_MATCH'"'"'$/,/^PY_MATCH$/p' scripts/fleet-revive.sh | sed '1d;$d' > matcher.py; python3 matcher.py claude /home/ubuntu/davis_root/.claude /home/ubuntu/davis_root/ws1 <instant>/.fleet/seed.txt`
- `e2e-real-verb-revive.log`: needs a compiled stand-in (`gcc` of a `pause()` loop named `claude`) and a scratch `$HOME`; see the session transcript for the driver.
