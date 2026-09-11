# Evidence index

Captured in slot2 on 2026-09-11.

| Acceptance | Artifact | Source / reproduction |
| --- | --- | --- |
| Capture failure before editing | before-test.txt; before-exit.txt | python3 -m unittest -v; exit 1; test_add reports -1 != 5 |
| Preserve original source | original-calc.py; original-test_calc.py | Copied from leased slot before edit; historical baseline |
| Correct addition | fixed-calc.py; fix.diff | Single operator change from subtraction to addition |
| Passing test after fix | after-test.txt; after-exit.txt | python3 -m unittest -v; 1 test passes; exit 0 |

Original and fixed source snapshots permit comparison without changing the slot. The test file was unchanged.
