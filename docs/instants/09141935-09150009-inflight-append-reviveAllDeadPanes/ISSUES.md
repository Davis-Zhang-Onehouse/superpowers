# ISSUES   (durable; append-only; one sub-section per issue)

## OI-1 Codex rollouts carry injected user-role blocks ahead of the prompt
### Symptom
Review round 1 (C1): the matcher took the first user-role block as "the prompt"; on this box 4 of 6 real rollouts open with `<recommended_plugins>` or `# AGENTS.md instructions for <cwd>` as a user block, so a DEAD Codex record would never match and the whole run would be refused.
### Root cause
The Claude measurement (first `type == user` row is the seed) was generalised to Codex without measuring a Codex rollout; the one Codex sample read was a session whose prompt happened to be the first non-environment user block.
### Action taken
The matcher inspects the first five user blocks on either runtime and matches if any carries the whole seed (96a29bb). Measured afterwards against two real rollouts whose prompts sit behind the injected blocks (evidence #5).
### Status
FIXED

## OI-2 A seed prefix stops being an identity once the instant path falls outside it
### Symptom
Review round 1 (C2): the first 200 squashed characters were compared; the reviewer measured the dispatch timestamp ending at character 172 on one profile (28 characters of margin) and past 200 on a coordinator seed. Past the margin every worker of an effort dispatched into a slot compares equal, the tiebreak picks one, and `fleet revive`'s own check (cwd == lease path) cannot tell them apart.
### Root cause
The prefix was meant as tolerance for a seed edited after dispatch; measured seeds are 2.6k–5.9k characters, so 200 bought no tolerance and lost specificity.
### Action taken
The whole squashed seed is compared, and the run refuses when two records resolve to one transcript (96a29bb).
### Status
FIXED

## OI-3 Board states that cannot be fixtured hermetically
### Symptom
The test cannot produce `UNREACHABLE` (needs a live pid holding the slot with no session) or a released-lease `DEAD` row (a record whose lease is released does not hold a slot and is not a board row at all, FD-4), so the script's `no lease` branch and its UNREACHABLE note are exercised only by reading.
### Root cause
Those states are defined by live processes and tmux servers the hermetic test deliberately does not create.
### Action taken
None; the branches are read-only diagnostics that start nothing.
### Status
DOCUMENTED
