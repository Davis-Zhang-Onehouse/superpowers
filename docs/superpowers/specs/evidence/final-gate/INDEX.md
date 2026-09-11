# Final default integration gate

The default 17-runner batch completed against source/test revision `b3516c7`. Its original result is
250 PASS / 1 FAIL / 10 SKIP, exit 1. `FULL-RUN-closeout.log`, the individual `RESULTS-closeout-*.tsv`
files, and `summary.json` retain that result. This is not a clean batch result and is not relabeled as one.
The before/after source pins are byte-identical, and all 67 files match that commit.

The sole failed case was E1. In all twenty iterations, it created three workers on three distinct
leases. Two or three waiting calls instead received the documented five-second admission-lock refusal,
where the older assertion required every loser to return no-capacity immediately. `e1-before/` retains
the iteration table and all ten call outputs from the first iteration.

The corrected E1 recognizes only the exact named lock-timeout refusal. After all original callers exit,
it retries those calls once, requiring no-capacity and an unchanged content/mtime manifest over records,
leases and instants. It still requires exactly three initial winners and three distinct held leases.
The targeted rerun passed all twenty iterations and all five isolation checks, exit 0. See `e1-after/`
for the iteration table, runner output, original and retry call results, and unchanged source pins.
All 20 iterations retained three distinct leases; every named timeout retry returned no-capacity with
an unchanged state manifest. The full batch was not repeated after this isolated test correction; its
original exit 1 remains recorded above. The other 250 passing checks and ten stated skips came from
the complete batch on the same source/test files.
No product source or unit tests changed for this test expectation correction.

The batch's M13 checks include complete unit-suite repetitions with and without the self-test guard;
both passed all 1,849 tests. The dirty-source control identifies its temporary test file, and the clean
control reports the tested commit. `exported-commit-unit.log` separately records the export check.

`evidence-path-lint.log` records exit 1 across 7 historical/generated result tables. Five rows in the
pre-existing tracked `fleet/it/RESULTS.tsv` already contain absolute paths. This remains a nonpassing
control. The batch's merged historical table is not used for the fresh counts above; the original
tracked table was restored after preserving the run's own result files.
