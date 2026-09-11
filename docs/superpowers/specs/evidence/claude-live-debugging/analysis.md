# RCA: test_calc.py::Addition::test_add failure

## Symptom (captured artifact)
`evidence/test_calc_before_fix.log`:
```
test_calc.py::Addition::test_add FAILED
E       AssertionError: -1 != 5
```
`add(2, 3)` returned `-1` instead of `5`.

## Why-chain
1. **FACT** — `test_calc.py:6` calls `self.assertEqual(add(2, 3), 5)`.
2. **FACT** — `evidence/calc_before.py:2` (pre-fix `calc.py`) defines `add(a, b)` as `return a - b`, i.e. subtraction, not addition.
3. **FACT** — `2 - 3 == -1`, matching the observed failure value exactly (`-1 != 5`).

Root cause: `add` in `calc.py` was implemented with the wrong operator (`-` instead of `+`). No deeper/environmental cause — single-line logic bug, fully explains the symptom.

## Fix
`calc.py:2`: changed `return a - b` → `return a + b`.

## Verification
`evidence/test_calc_after_fix.log`: `test_calc.py::Addition::test_add PASSED`, 1 passed.
