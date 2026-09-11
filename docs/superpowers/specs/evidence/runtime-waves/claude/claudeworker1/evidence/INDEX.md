# INDEX — claudeworker1

Updated: 2026-09-11  |  Status: LIVE

criterion -> artifact -> source -> how to regenerate.

## m1 "addition 1" — fix the failing addition test

- **Capture failing output and original source before editing**
  -> `ready.txt` (READY ack before GO), `calc.py.orig` (original source: `add(a, b)` returned `a - b`),
     `before-failing.log` (`python3 -m unittest -v test_calc` before the fix)
  -> source: `slot1/calc.py`, `slot1/test_calc.py` at dispatch
  -> regenerate: `git show :calc.py` in the slot before any edit, or re-run the failing test against the
     original source

- **Root cause**
  -> `calc.py`'s `add(a, b)` returned `a - b` instead of `a + b`, so `test_calc.py::Addition::test_add`
     failed: `add(2, 3)` returned `-1`, not `5` (see `before-failing.log`:
     `AssertionError: -1 != 5`)

- **Fix and passing test**
  -> `calc.py.fixed` (fixed source: `add(a, b)` now returns `a + b`), `after-passing.log`
     (`python3 -m unittest -v test_calc` after the fix: `test_add ... ok`)
  -> source: `slot1/calc.py` after the one-line edit
  -> regenerate: `python3 -m unittest -v test_calc` from `slot1/`
