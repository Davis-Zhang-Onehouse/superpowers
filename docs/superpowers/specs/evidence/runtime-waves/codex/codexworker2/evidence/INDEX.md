# Evidence for m2

| Criterion | Artifact | Source / reproduction |
| --- | --- | --- |
| Original source before editing | original-calc.py, original-test_calc.py | Byte copies from leased slot before fix |
| Failing test captured before editing | failing-test.txt | python3 -m unittest -v in leased slot; exit 1 |
| Minimal addition fix | change.diff, fixed-calc.py | Diff against captured original; replace subtraction with addition |
| Passing test after fixing | passing-test.txt | python3 -m unittest -v in leased slot; 1 test passes, exit 0 |

Diagnosis: ../investigations/addition/analysis.md.
Original artifacts are historical evidence; do not overwrite to regenerate them.
