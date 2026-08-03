# RUNBOOK — self-contained; one build + one validation run re-derives every claim

## Environment
```bash
export REPO=/home/ubuntu/davis_root/superpowers
export FLEET_HOME=/home/ubuntu/.fleet
export FLEET_RELEASES=/home/ubuntu/davis_root/fleet-releases
```
`--home` and `--releases` are passed EXPLICITLY below: a mutating verb refuses a write with no named
store (`SI-15`), and that refusal is a feature when these commands get copied elsewhere.

## FIRST — is any brief stale?   (`D-4`; run before working any gap)
```bash
bash bin/reverify-briefs.sh          # ~2s; one row per gap; exit 1 if a premise moved
```
Exit 1 with `A-2 REFUTED` is EXPECTED and recorded (`ASSUMPTIONS.md` `A-2`). Any other non-HOLDS row is
new — read it before designing. Do not pipe it through `tee` and read `$?`: that reads tee's exit, which is
how `SI-38` shipped.

## Reproduce G-1 + G-2   (the active work; ~6 min, costs nothing)
```bash
bash bin/repro-g2-stall-loop.sh      # detector works · nobody consumes · detector is unguarded
```
Three parts, each with its own artifact under `evidence/repro-g2/`. PART 3 is a mutation experiment and
**carries its own control**: M-2 (revert `FI-14`) must be KILLED or M-1's survival means nothing. Expected
rows: `M-1 SURVIVED`, `M-2 KILLED`, `M-3 SURVIVED`, all `AS-PREDICTED`.

A mutant tree must mirror the repo layout (`<tree>/fleet/{src,tests}` + `<tree>/skills`) — four cases resolve
the repo root as `parents[2]`. A flat `{src,tests}` copy turns 4 cases red and the baseline gate then
(correctly) refuses to report anything.

RCA: `investigations/g1-g2-stall-loop/analysis.md`.

## Build / test
```bash
cd $REPO/fleet && PYTHONPATH=src python3 -m unittest discover -s tests    # ~70s, 1177 tests
cd $REPO && bash fleet/it/run-all.sh                                      # ~25 min; ends in a BATCH VERDICT
```
**One IT job at a time.** Concurrent runners contaminated a run in this line of work (`SI-36`).

## Release cycle
```bash
cd $REPO
FLEET_HOME=$FLEET_HOME bin/fleet release-cut --version X.Y.Z --repo $REPO --releases $FLEET_RELEASES --notes "…"
FLEET_HOME=$FLEET_HOME bin/fleet release-verify  --version X.Y.Z --releases $FLEET_RELEASES   # ~25 min
FLEET_HOME=$FLEET_HOME bin/fleet release-promote --version X.Y.Z --releases $FLEET_RELEASES
FLEET_HOME=$FLEET_HOME bin/fleet release-list    --releases $FLEET_RELEASES
```
A cut needs a CLEAN tree. Verification takes a `git worktree` at the tag; `git -C $REPO worktree list`
shows a leaked one.

## Triaging a red gate
```bash
V=$FLEET_RELEASES/fleet-vX.Y.Z/.release/evidence
cat $V/VERDICT.tsv
grep -P '\tFAIL\t' $V/it-RESULTS-closeout-*.tsv | cut -f1,2,4
```
Read the PER-RUNNER registers, never the merged `it-RESULTS.tsv` — it keeps rows from runs that did not
happen this time (`II-6`). Evidence a FAIL row cites is carried into `it-cited/` (`QI-5`).

## A real interactive pane (for G-1, G-2, G-4)
**Authorised without asking for this session (`D-6`).** The mechanical guards still hold: private socket,
`itfleet-probe-*`, never the default server, never `dt-`.
```bash
bash bin/probe-ra1-send-race.sh                      # the RA-1 gap sweep, ~10 min (needs the env var below)
LP=$REPO/fleet/it/bin/live-pane.sh
bash $LP selftest                                    # 9 checks, shell mode, costs nothing
S=$(FLEET_ALLOW_LIVE_CLAUDE=1 bash $LP start g1)     # a REAL claude; spends weekly allowance
bash $LP guard "$S"; bash $LP submit "$S" "text"; bash $LP cap "$S"
bash $LP stop "$S"; bash $LP reap
```
Never the default tmux server, never a `dt-` name, always `itfleet-probe-*`.

## Mutating a case (for G-5)
```bash
bash $REPO/fleet/it/run-m9-mutation.sh              # the PATTERN: cp -r, inject, assert death BY REASON
P=/home/ubuntu/davis_root/operations/tasks/fleetItStabilisation/00000000-08020624-inflight-append-itSuiteStabilisation
bash $P/bin/case-risk-census.sh                     # the sampling frame
cat $P/investigations-ac2-first-targets.md          # the mutation each first target needs
```

## The controls that guard the harness's own checks
```bash
bash $P/bin/m9-controls.sh            # 7: receiver resolution + registry cross-check
bash $P/bin/a1-detail-control.sh      # A1 names only what failed
bash $P/bin/batch-verdict-control.sh  # run-all.sh's exit, over synthetic registers
bash $P/bin/exit-status-control.sh    # 19: no runner exits a COUNT
bash $REPO/scripts/tests/it-lib-isolation.sh   # 16: the isolation classifier + leak detector
```

## State at the time of writing   (LIVING — re-verified 2026-08-03T03:17Z)
- **`11f2f58`** on `live`, tree CLEAN, HEAD == `origin/live`
  (`ssh://git@github.com/Davis-Zhang-Onehouse/superpowers.git`)
- `0.3.1` RELEASED and GREEN; `current` → the checkout (DEV). **`d07b4a2` and `11f2f58` are NOT covered by
  any release verification** — `AC-2` needs a cut over them.
- 1183 hermetic tests (was 1177 at `b9b0a08` — HISTORICAL); gate roster 12 runners, 0 FAIL rows as of
  `0.3.1`
- Re-derive all of the above: `bash bin/reverify-briefs.sh` prints the tip, branch and tree state in its
  header.
