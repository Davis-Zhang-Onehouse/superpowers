# INDEX — claudeworker2

Updated: 2026-09-11  |  Status: LIVE

criterion -> artifact -> source -> how to regenerate.

## Diagnosis

`calc.py`'s `add(a, b)` returned `a - b` instead of `a + b`, causing `test_calc.Addition.test_add`
(`assertEqual(add(2, 3), 5)`) to fail with `-1 != 5`.

- `evidence/01-diagnose/calc.py.orig` — original (buggy) source, captured before any edit
- `evidence/01-diagnose/failing-output.txt` — `python3 -m unittest -v test_calc` output before the fix (FAILED)

## Fix

Changed `return a - b` to `return a + b` in `calc.py` (one-line change, in the leased slot).

- `evidence/01-diagnose/calc.py.fixed` — corrected source, captured after the edit
- `evidence/01-diagnose/passing-output.txt` — `python3 -m unittest -v test_calc` output after the fix (OK)
