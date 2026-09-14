# Evidence index — acceptance criteria → artifact → source
Updated: 2026-09-14

| # | Criterion | Artifact (this folder) | What it shows | Source (command @ commit) |
|---|-----------|------------------------|---------------|---------------------------|
| 1 | AS-1 baseline | `hermetic-71c69a2.log` | 1,849 tests OK (117 s) on the branch as received | `PYTHONPATH=src python3 -m unittest discover -s tests -q` @ 71c69a2 (worktree) |
| 2 | AC-2 (first attempt) | `hermetic-db0ba8d.log` | 1,896 run, 2 F + 52 E — the OI-2 merge artifact | same command @ db0ba8d (`.worktrees/fleet-runtime-rebase`) |
| 3 | AC-2 | `hermetic-db0ba8d-plus-dispatch-fix.log` | 1,896 OK after the OI-2 fix | same command @ the dispatch-fix tree (later folded into 4de441c) |
| 4 | AC-2 + AC-3 | `2026-09-14-round1-checks-a.log`, `it-RESULTS-round1-runtime-A-group5.tsv` | after review round 1: 1,901 tests, 1 F (my new assertion, OI-3); hooks/codex/scripts PASS; run-runtime --stubs + §A + group5: 90 PASS / 1 FAIL (M13, same test) / 5 SKIP | round-1 job @ 896864b |
| 5 | AC-2 + AC-3 | `2026-09-14-round1-checks-b.log`, `it-RESULTS-round1-M.tsv` | assertion fixed: 1,901 OK; §M 37 PASS | @ 9e0c03c (tree identical to the squashed tip `26aa9ae`) |
| 6 | AC-2 + AC-3 (round 2) | `2026-09-14-round2-checks-a.log`, `it-RESULTS-round2-N-F-G-H-I-J-O-LB-first.tsv` | after review round 2 (`b871a41`): 1,903 hermetic OK; §F §G §H §I §LB PASS; J1 and O4 FAIL (OI-5, OI-6); §N mis-launched by my loop | round-2 job @ b871a41 |
| 7 | OI-5 is pre-existing | `it-RESULTS-live-f15b585-J.tsv` | §J on the untouched live checkout: J1 FAIL with the same note — the branch did not cause it | `IT_RESULTS=<scratch> bash run-J.sh` @ live f15b585 (main checkout) |
| 8 | AC-3 (round 2, fixed) | `2026-09-14-round2-checks-b.log`, `it-RESULTS-round2-{J,O,N}.tsv` | §J 11 PASS (J1 fixed), §O 13 PASS (O4 fixed), §N 14 PASS | @ the J1/O4 runner fix tree (committed as the `it:` commit on top of b871a41) |

## How to regenerate each artifact
- `hermetic-<sha>.log`: RUNBOOK § Hermetic suite, from a checkout at `<sha>`.
- `it-RESULTS-*.tsv`: RUNBOOK § Integration sections (scratch `IT_RESULTS`), from `.worktrees/fleet-runtime-rebase/fleet/it`.
