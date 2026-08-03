# Archive — stall-loop feature dev, 2026-08-03

Everything from one session's feature development, parked here so `live` could be restored to its
pre-feature state. Nothing in this directory is product code; it is the record.

## Why it is here
The effort workspace lives at
`/home/ubuntu/davis_root/operations/tasks/metaOpt/fleetInfraOps/00000000-08030228-inflight-append-fleetOpenGapClosure`
and **that tree is not under version control** — no `.git` at or above it. So the only way to preserve it
alongside the code it describes was to copy it into this branch.

## Contents
`instant-snapshot/` — the effort workspace, verbatim, as of archiving (46 files):
- `specs/2026-08-03-stall-loop-design.md` — the design, incl. the four explicit questions (who detects,
  under what condition, who is nudged, what is actually sent)
- `plans/2026-08-03-stall-loop-implementation.md` — the 10-task implementation plan
- `investigations/g1-g2-stall-loop/analysis.md` — the RCA, every node a cited fact or a flagged assumption
- `investigations/g1-g2-stall-loop/state-vocabulary.md` — exact `IDLE`/`PARKED`/`AWAITING-CI` definitions
  and the observed-vs-declared split
- `bin/` — five runnable checks: `reverify-briefs.sh`, `repro-g2-stall-loop.sh` (mutation experiment with
  its own control), `probe-ra1-send-race.sh` (live-pane gap sweep), `probe-nudge-eligibility.sh`,
  `measure-attention.sh`
- `evidence/` — captured artifacts with provenance, indexed in `evidence/INDEX.md`
- `DECISIONS.md` (`D-1`..`D-11`), `ISSUES.md` (incl. `G-9`..`G-12`), `ASSUMPTIONS.md`, `HANDOFF.md`

## The code, on this branch's history
| commit | what |
|---|---|
| `653ff90` | `G-10` — the `IDLE` detector gets a test; mutation control flips `M-1`/`M-3` to KILLED |
| `fdccc8c` | `#{session_attached}` collected, failing safe |
| `4933291` | `G-11` — a parked question asks for a human (`ACTIONABLE_STATES` += `PARKED`) |
| `32368a9` | `D-10` — an `awaiting-ci` declaration needs a live watcher |
| `bb3371e` | **WIP, UNREVIEWED** — `fleet pane-send` (`G-1`). See its message for the done/not-done split. |

The first four were reviewed clean; the suite was 1204 green at `32368a9`.

## Findings raised during the work, still open
- **`G-12`** — both shipped charters instruct `fleet declare phase awaiting-ci`, in which `phase` is a stray
  positional, so the command exits 2; and `profiles.py:209` LINTS that the charters contain that broken
  literal, so a charter carrying the working form would fail lint. Verified three independent ways.
  Pre-existing, out of scope for this work, not fixed.
- **`G-9`** — `bin/reverify-briefs.sh` is a check with no control; two of its ten rows assert an absence.
- Two deferred minors, both in the SDD ledger.

## Not restored to a prior state, because it was never changed
No machine configuration was modified during this work: the `claude-watchdog` daemon was already running
before it started and was only ever queried with `status` (read-only); nothing was written to `FLEET_HOME`;
the live-pane probes reaped their own tmux sessions and left an empty ledger.
