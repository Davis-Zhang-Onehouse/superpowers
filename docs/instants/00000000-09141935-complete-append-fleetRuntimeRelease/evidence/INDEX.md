# Evidence index — acceptance criteria → artifact → source
Updated: 2026-09-14 22:10 UTC | Status: LIVE

| # | Criterion | Artifact (this folder) | What it shows | Source (command @ commit) |
|---|-----------|------------------------|---------------|---------------------------|
| 1 | AS-1 baseline | `hermetic-71c69a2.log` | 1,849 tests OK (117 s) on the branch as received | `PYTHONPATH=src python3 -m unittest discover -s tests -q` @ 71c69a2 (worktree) |
| 2 | AC-2 (first attempt) | `hermetic-db0ba8d.log` | 1,896 run, 2 F + 52 E — the OI-2 merge artifact | same command @ db0ba8d (`.worktrees/fleet-runtime-rebase`) |
| 3 | AC-2 | `hermetic-db0ba8d-plus-dispatch-fix.log` | 1,896 OK after the OI-2 fix | same command @ the dispatch-fix tree (later folded into 4de441c) |
| 4 | AC-2 + AC-3 | `2026-09-14-round1-checks-a.log`, `it-RESULTS-round1-runtime-A-group5.tsv` | after review round 1: 1,901 tests, 1 F (my new assertion, OI-3); hooks/codex/scripts PASS; run-runtime --stubs + §A + group5: 90 PASS / 1 FAIL (M13, same test) / 5 SKIP | round-1 job @ 896864b (unreachable after the autosquash; that tree = 26aa9ae minus the M13 assertion fix) |
| 5 | AC-2 + AC-3 | `2026-09-14-round1-checks-b.log`, `it-RESULTS-round1-M.tsv` | assertion fixed: 1,901 OK; §M 37 PASS | @ 9e0c03c (tree identical to the squashed tip `26aa9ae`) |
| 6 | AC-2 + AC-3 (round 2) | `2026-09-14-round2-checks-a.log`, `it-RESULTS-round2-N-F-G-H-I-J-O-LB-first.tsv` | after review round 2 (`b871a41`): 1,903 hermetic OK; §F §G §H §I §LB PASS; J1 and O4 FAIL (OI-5, OI-6); §N mis-launched by my loop | round-2 job @ b871a41 |
| 7 | OI-5 is pre-existing | `it-RESULTS-live-f15b585-J.tsv` | §J on the untouched live checkout: J1 FAIL with the same note — the branch did not cause it | `IT_RESULTS=<scratch> bash run-J.sh` @ live f15b585 (main checkout) |
| 8 | AC-3 (round 2, fixed) | `2026-09-14-round2-checks-b.log`, `it-RESULTS-round2-{J,O,N}.tsv` | §J 11 PASS (J1 fixed), §O 13 PASS (O4 fixed), §N 14 PASS | @ the J1/O4 runner fix tree (committed as the `it:` commit on top of b871a41) |
| 9 | AC-4 | `release-0.6.0/VERDICT.tsv`, `release-gate.log`, `release-verify.log`, `hermetic-tail.txt`, `it-fail-rows.txt`, `it-RESULTS-closeout-{runtime,A,group5,J,O}.tsv` | fleet 0.6.0: hermetic GREEN, it GREEN (full roster, 0 FAIL rows), overall GREEN; gate ran 21:12→21:54 UTC | `scripts/release-gate.sh 0.6.0 --full` @ tag fleet/v0.6.0 (e99d7d4); source `/home/ubuntu/davis_root/fleet-releases/fleet-v0.6.0/.release/evidence/` |
| 10 | AC-4 | `release-0.6.0/release-status.txt`, `postflight.txt` | `current` → fleet-v0.6.0, state RELEASED; postflight OK on every manifest and root | `fleet release-status`; `scripts/release-postflight.sh 0.6.0` |
| 11 | AC-3 (§P clause) | `P-0.6.0/it-RESULTS-P.tsv`, `run-P.log`, `P-worker-report.md`, `P-config-dir.txt` | §P on the deployed tip: P1-P4 PASS + isolation; a real `claude` followed the worker contract from the seed alone; the real CLI resolved the operator's config dir `/home/ubuntu/davis_root/.claude` (RV-10's fix executed for the first time) | `IT_RESULTS=<scratch> bash fleet/it/run-P.sh` @ e99d7d4, 22:02→22:04 UTC (spends one real claude) |

## How to regenerate each artifact
- `hermetic-<sha>.log`: RUNBOOK § Hermetic suite, from a checkout at `<sha>`.
- `it-RESULTS-*.tsv`: RUNBOOK § Integration sections (scratch `IT_RESULTS`), from a checkout of the tip (the rebase worktree was removed after landing; `live` carries the same tree).
- `P-0.6.0/*`: `cd fleet/it; IT_RESULTS=<scratch> bash run-P.sh` (≈3 min here; one real claude).
- `release-0.6.0/*`: a re-verify would be a NEW attempt on the same tag (Trap 5 archives this one); the deployed copies are the primary record.
