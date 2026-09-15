# DECISIONS   (durable; append-only register)

## D-1 — Keep `fleet revive` as the only actor; the script derives and orchestrates   (2026-09-15, ACTIVE)
### Context
The partner asked for the revive skill to offload every mechanical step to a script and to revive every dead pane without an operator naming one, and exempted a revive-only change from the `--full` gate.
### Decision
No `fleet` verb or record field changes. `scripts/fleet-revive.sh` becomes `plan` / `revive` over the whole root: it reads `board --porcelain`, derives per-record values through `status`/`leases --porcelain`, and calls `fleet revive --id --session-id` (dry-run for all, then start for all).
### Rationale
Every safety check already lives in the verb (runtime match, held lease, unoccupied pane/workspace, transcript-vs-workspace, verified resume) and is exercised by the hermetic suite. Re-implementing them in bash would duplicate a contract; adding a verb would widen the release beyond "revive-related". Alternatives: `fleet revive --all` in Python (rejected: CLI contract change, verb-parity tests, wider gate); recording the session UUID at dispatch (rejected for this instant: touches the dispatch path).
### Consequences
The script is the operator surface; the verb is the actor. The release gate will still run the standard roster because `scripts/` changed.

## D-2 — Transcript identity = recorded configuration + slot cwd + the record's seed as first user message   (2026-09-15, ACTIVE)
### Context
Records carry no native session UUID. A slot's project directory holds every past occupant's transcripts; mtime is not identity (measured: three occupants in one slot). The old helper listed candidates and refused to choose.
### Decision
A candidate is a main transcript (Claude: `projects/**/<uuid>.jsonl`, never a `subagents/` file; Codex: `sessions/**/rollout-*.jsonl`) whose metadata cwd resolves to the lease path and whose first user message, whitespace-squashed, starts with the record's `.fleet/seed.txt` squashed (first 200 chars). Exactly one match is the answer; several matches choose the latest-started and print all; zero is a refusal.
### Rationale
Measured on this box: a dispatched worker's first user message is the seed verbatim (ws1 `d0db599f`, ws3 `995a2a6a`, `3ffd9dc2`), and the seed embeds the instant path with its dispatch timestamp, so it is unique per record. A re-brief (send-keys) delivers the same seed, so a re-briefed session still matches.
### Consequences
A record whose instant has no `seed.txt`, or whose seed never reached a transcript, cannot be revived automatically; the script says so and names `fleet revive --session-id` for the hand path.

## D-3 — The root comes from the working directory; conflicting `FLEET_*` exports are dropped   (2026-09-15, ACTIVE)
### Context
The partner requires the skill to refuse unless invoked under a folder indicating the fleet root, and to accommodate several roots with their own tmux servers.
### Decision
The script walks up from `$PWD` to a `.fleet-root` marker (stopping below `$HOME`, like `fleet.root`), refuses (rc 2) when none is found, unsets `FLEET_HOME`, `FLEET_ROOT`, `FLEET_TMUX_SOCKET`, `FLEET_RELEASES`, `FLEET_INSTANTS`, and passes `--root <root>` on every `fleet` call. Per-record servers come from the records (`fleet` follows `tmux_socket` itself).
### Rationale
`resolve_home` ranks `$FLEET_HOME` above `--root`, so a stale export from another root would silently redirect the store; the marker is the one fact the partner asked to be authoritative.
### Consequences
An operator who wants a different root changes directory; there is no flag to override the root.

## D-4 — Any pre-flight problem refuses the whole run   (2026-09-15, ACTIVE)
### Context
The partner said "error out" for a runtime mismatch.
### Decision
`plan` and `revive` evaluate every DEAD record first (runtime match, abort recorded, seed and transcript, `fleet revive --dry-run`); any problem prints all problems and exits 2 with nothing started. Once starting, a failed start does not stop the others; the run exits 1 and names the failures; re-running revives what is still DEAD.
### Rationale
A partially-started run is harder to reason about than a refused one; a mismatch can only arise from a hand-edited `runtime.json`, which the operator should fix once for the whole fleet.
### Consequences
The `revive` subcommand is idempotent over the board.
