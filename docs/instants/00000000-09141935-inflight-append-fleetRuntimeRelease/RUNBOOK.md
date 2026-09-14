# Fleet runtime selection — review, rebase, release — RUNBOOK
Updated: 2026-09-14 by session 53ee129f-4b4a-4005-bdb6-dfab263001b1 | Status: LIVE (commands only; one current recipe per task)

## Hermetic suite (from a checkout; ~2 min)
```bash
cd <checkout>/fleet
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -q
```

## Integration sections without dirtying RESULTS.tsv
```bash
cd <checkout>/fleet/it
R="$PWD/RESULTS-scratch-$$.tsv"; printf 'case\tverdict\tevidence\tnote\n' > "$R"
IT_RESULTS="$R" bash run-runtime.sh --stubs
IT_RESULTS="$R" bash run-A.sh
IT_RESULTS="$R" bash run-group5.sh          # §L §M §N
awk -F'\t' '$2=="FAIL"' "$R"; rm "$R"; git status --short
```

## Rebase
```bash
cd /home/ubuntu/davis_root/superpowers/.worktrees/fleet-runtime
git rebase live        # resolve; then re-run the hermetic suite
```

## Release notes (the `--notes` string for 0.6.0)
```
runtime selection: one fleet runs under Claude Code or Codex CLI, chosen between runs with `fleet runtime --set`; dispatch launches the selected CLI directly with the rendered seed as one argument (no PATH shim); `fleet send` delivers a guarded, observed pane message; `fleet revive` resumes a worker's exact session; both runtimes are discovered by peers/board/close/harvest; pane-guard 15 now covers every measured operator dialog on either CLI; native Codex SessionStart bootstrap hook; six fleet skills and docs/README.fleet-runtimes.md updated. Records now carry a runtime field an older fleet binary cannot read — update every root's fleet in step.
```

## Release chain (see skills/releasing-fleet/SKILL.md for the traps)
```bash
cd /home/ubuntu/davis_root/superpowers && . scripts/fleet-env.sh
REPO=/home/ubuntu/davis_root/superpowers; FLEET=$REPO/bin/fleet
bash scripts/release-preflight.sh
# de-risk the --full roster first (D-6): IT_RESULTS=<scratch> bash fleet/it/run-{F,G,H,I,J,O,lineage}.sh from .worktrees/fleet-runtime-rebase/fleet/it
$FLEET release-cut --version X.Y.Z --repo "$REPO" --releases "$FLEET_RELEASES" --notes "…" --dry-run
$FLEET release-cut --version X.Y.Z --repo "$REPO" --releases "$FLEET_RELEASES" --notes "…"
setsid nohup bash scripts/release-gate.sh X.Y.Z --full > <scratch>/gate-X.Y.Z.log 2>&1 < /dev/null &   # --full for a minor bump (D-6); ~1 h; ZERO tool calls while it runs
$FLEET release-promote --version X.Y.Z --releases "$FLEET_RELEASES"
$FLEET release-deploy  --version X.Y.Z --releases "$FLEET_RELEASES" --reason "…"
bash scripts/release-postflight.sh X.Y.Z
```
