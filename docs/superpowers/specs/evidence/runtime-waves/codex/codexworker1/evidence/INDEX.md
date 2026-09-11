# Evidence index

Captured 2026-09-11 in leased slot1, after GO.

| Criterion | Artifact | Source and reproduction |
|---|---|---|
| Readiness before GO | ready.txt | Written after brief and charter read |
| Original source before fix | original-calc.py, original-test_calc.py | Byte copies from slot before edit; historical snapshots |
| Capture failing test | failing.txt | python3 -m unittest -v in slot; exit 1; reproduce with archived files in an isolated directory named calc.py and test_calc.py |
| Correct addition and passing test | fixed-calc.py, passing.txt | Source copy and python3 -m unittest -v after operator fix; exit 0 |
| Minimal change | fix.diff | Python difflib of original and fixed calc.py; test file confirmed byte-identical |
| READY review | review.txt | fleet review, captured after evidence review |
| Report milestone done | proposal.txt | fleet propose for m1 with this index |
| Complete instant | completion.txt | fleet complete after review and proposal |
