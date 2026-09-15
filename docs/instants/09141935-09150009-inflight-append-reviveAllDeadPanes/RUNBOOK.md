# Revive all dead panes — RUNBOOK
## Test
```bash
cd /home/ubuntu/davis_root/superpowers
bash scripts/tests/fleet-revive.sh
bash scripts/tests/fleet-runtime-helpers.sh
bash scripts/lint-shell.sh scripts/fleet-revive.sh scripts/tests/fleet-revive.sh
```
## Use (from inside a fleet root)
```bash
cd /home/ubuntu/davis_root
bash "$FLEET_RELEASES/current/scripts/fleet-revive.sh" plan     # read-only
bash "$FLEET_RELEASES/current/scripts/fleet-revive.sh" revive   # revive every DEAD record
```
## Release notes (the `--notes` string for 0.6.1)
```
reviving-dead-panes: scripts/fleet-revive.sh plan|revive runs from inside a fleet root, reads that root's board, and revives every DEAD record on either runtime — server, slot, configuration and transcript derived from the records (the transcript is the one carrying the record's seed), the whole run refused when a record's runtime differs from the fleet selection, when an abort is recorded, or when no transcript matches; the skill follows the script.
```

## Release chain (patch; standard gate, no --full — the partner exempted a revive-only change)
```bash
cd /home/ubuntu/davis_root/superpowers && . scripts/fleet-env.sh
REPO=/home/ubuntu/davis_root/superpowers; FLEET=$REPO/bin/fleet
bash scripts/release-preflight.sh
$FLEET release-cut --version 0.6.1 --repo "$REPO" --releases "$FLEET_RELEASES" --notes "…" --dry-run
$FLEET release-cut --version 0.6.1 --repo "$REPO" --releases "$FLEET_RELEASES" --notes "…"
setsid nohup bash scripts/release-gate.sh 0.6.1 > <scratch>/gate-0.6.1.log 2>&1 < /dev/null &   # ~25-45 min; ZERO tool calls while it runs
$FLEET release-promote --version 0.6.1 --releases "$FLEET_RELEASES"
$FLEET release-deploy  --version 0.6.1 --releases "$FLEET_RELEASES" --reason "…"
bash scripts/release-postflight.sh 0.6.1
```
