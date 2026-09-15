# Revive all dead panes, on either runtime, from the fleet root — CHARTER   (durable; edit deliberately)
Instant: 09141935-09150009-complete-append-reviveAllDeadPanes
Updated: 2026-09-15 by session 53ee129f-4b4a-4005-bdb6-dfab263001b1 | Status: DURABLE

## Goal (e2e)
Make `superpowers:reviving-dead-panes` a repeatable, root-scoped, runtime-aware operation: the operator
invokes the skill from inside a fleet root, a script reads the board, finds every `DEAD` record, derives
every value (server, slot, configuration, transcript) from the records, refuses when the fleet's selected
runtime differs from a record's runtime, and revives them all — then a release carries it.

## First 3 raw prompts (verbatim)
1. > by default are we using claude for fleet?
2. > let's look into the claude skill revive dead pane. It needs
   > - to work for both claude and codex - if the runtime differs from what the pane was using, error out.
   > - it needs to accommodate different fleet root which comes with different tmux namespace
   > - it should offload as much steps as possible to scripts to ensure it is repeatable
   > - instead of user tell which pane to revive, it should just check fleet-view and figure that out dead pane and revive all of them. It error out when the claude skill is not invoked directly under a folder indicating the fleet root.
   >
   > This part once you tested and validated things locally and the change is limited to revive pane related item, you can go cut a release and deploy without going through the full ITs.
3. (none yet)

## Setup to begin with
- Base instant: `09141935` (`00000000-09141935-complete-append-fleetRuntimeRelease`: fleet 0.6.0 released with runtime selection).
- Branches / checkouts at start: `live` @ `350a661` in `/home/ubuntu/davis_root/superpowers` (clean); deployed release `fleet-v0.6.0` (`fleet-releases/current`).
- Existing surface: `skills/reviving-dead-panes/SKILL.md`, `scripts/fleet-revive.sh` (`plan`/`transcripts`/`launcher`/`start`, one record at a time, operator picks the transcript), `fleet revive --id --session-id` (refuses a runtime mismatch, requires the held lease and an unoccupied pane/workspace), test `scripts/tests/fleet-runtime-helpers.sh`.
- Measured before design (2026-09-15): records carry no native session UUID; a worker's transcript's FIRST user message is the record's `.fleet/seed.txt` verbatim (ws1 `d0db599f`, ws3 `995a2a6a`/`3ffd9dc2`); a slot's project directory holds transcripts of many occupants, so mtime is not identity.

## Scope
- IN: `scripts/fleet-revive.sh` (root-scoped, board-driven, revive-all, runtime check, automatic transcript identity), its test, the `reviving-dead-panes` skill text, the runtimes README paragraph that names the helper; a patch release (cut → standard gate → promote → deploy → postflight).
- OUT: changes to `fleet` verbs or records (no CLI change; `fleet revive` stays the single actor); mixed-runtime fleets; a `--full` roster gate (the partner exempted it for a revive-only change); reviving `UNREACHABLE`, `UNKNOWN-SESSION` or `STALE-LEASE` rows.

## Acceptance criteria (NL → executable proof → self-review)

### AC-1 Root-scoped: works from inside any fleet root, refuses elsewhere
- [x] Statement: run from a directory inside a fleet root (marker walk, stopping below $HOME), the script derives root, store and tmux server from the marker and ignores stale `FLEET_*` exports; run from a directory that is not inside a root, it refuses (rc 2) without touching anything.
- Proof: `scripts/tests/fleet-revive.sh` cases `outside-root`, `stale-env` (from a subdirectory); a manual run from `/home/ubuntu/davis_root` and from `/home/ubuntu/davis2_root` (evidence/).
- Self-review: MET — evidence #1 (test, 30 checks ok), #2/#3 (both real roots derive their own name/server/store and drop davis's exports), #4 (`/home/ubuntu` refused rc 2).

### AC-2 Board-driven revive-all with runtime check
- [x] Statement: the script reads `fleet board --porcelain`, selects every `worker` row in state `DEAD`, refuses the whole run (rc 2, nothing started) when any selected record's runtime differs from the fleet selection, when an abort is recorded, or when no unique transcript can be derived; otherwise dry-runs every revival, then starts them all and reports pane-guard per record; with no `DEAD` row it exits 0 and says so.
- Proof: test cases `nothing-dead`, `runtime-mismatch`, `abort-recorded`, `no-seed-match`, `revive-all` (two DEAD records, both revived, argv captured), plus an end-to-end run through the real verb on a scratch root (evidence #6).
- Self-review: MET — evidence #1; #6 shows DEAD → `fleet revive` start → RUNNING with `launched_at` moved, a second `revive` is a no-op, and after the server is killed `plan` derives the same transcript again. No `fleet/src` change, so the hermetic suite is untouched by this instant (the gate re-runs it).

### AC-3 Transcript identity is derived, on both runtimes
- [x] Statement: for a Claude record the transcript is the one under the recorded (or owner-resolved) configuration whose metadata cwd is the slot and whose first user message is the record's seed; for a Codex record the same rule over `sessions/` rollouts; subagent files and other occupants' transcripts are never chosen; several matches choose the latest-started and say so.
- Proof: test cases `claude-seed-match` (decoy, older occupant and subagent file not chosen), `codex-seed-match`, `latest-of-two`; the matcher run against two live worker records on this box (evidence #5).
- Self-review: MET — #5: ws1 → `d0db599f`, ws3 → `3ffd9dc2` (one match each among 83 main transcripts); Codex: rollouts `01a0916d` (prompt behind `<recommended_plugins>`) and `01a0917b` (behind an AGENTS.md preamble) matched by their real prompts, a control prompt matched nothing. Round 1 found and fixed the first rule's Codex blind spot (OI-1) and its prefix cliff (OI-2).

### AC-4 Skill and docs match the script; released
- [x] Statement: `skills/reviving-dead-panes/SKILL.md` tells the operator to run the script from the root and to read its output, keeps the measured traps that still apply, and names no removed subcommand; `docs/README.fleet-runtimes.md` agrees; a patch release is cut, verified by the standard gate, promoted, deployed, postflight OK.
- Proof: `grep` of removed names returns nothing outside history; `fleet-releases/current` → the new version; `evidence/release-<v>/`.
- Self-review: MET — fleet 0.6.1 cut (f85dee3, tag fleet/v0.6.1), standard-roster gate GREEN in 39 min (1,903 hermetic OK; IT 335 PASS / 11 SKIP / 0 FAIL, no FAIL row in any per-runner closeout), promoted, deployed 2026-09-15 (`current → fleet-v0.6.1`), postflight OK on both roots; the deployed script run from `/home/ubuntu/davis_root` resolves the deployed binary (evidence #9-#12). The removed subcommand names survive only in the historical plan/spec/backlog prose.

## Setup to end up with (the handoff)
- Deliverables: `live` commits 6609648, 96a29bb, c88cf04, ce7a866, f85dee3 (fleet v0.6.1); `fleet-releases/current → fleet-v0.6.1`; this instant renamed complete.
- Reproducible stack: RUNBOOK.md (test, lint, manual plan, release chain).

## Standing constraints / rules
- No change to `fleet` verbs or record schema in this instant (keeps the release revive-only, as the partner's exemption requires).
- The gate runs the standard roster (no `--full`); never pipe a control; `setsid`; silence while it runs; not after ~02:45 UTC.
- Commits look user-authored (no co-author trailer).

## Environment
- Box: this EC2 host; roots `davis` (`/home/ubuntu/davis_root`, socket `fleet-davis`; live workers still on socket `fleet` from earlier records) and `davis2`.
