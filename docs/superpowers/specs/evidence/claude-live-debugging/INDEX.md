# Claude debugging evidence

Captured from the private `claudeLive-09111923` session on 2026-09-11.

| Claim | Artifact | Reproduction |
| --- | --- | --- |
| Addition test fails before editing | test_calc_before_fix.log | python -m pytest test_calc.py |
| Original implementation subtracts | calc_before.py | Original source snapshot |
| Addition test passes after fix | test_calc_after_fix.log | python -m pytest test_calc.py |
| Diagnosis references captured evidence | analysis.md | Worker-written investigation |
