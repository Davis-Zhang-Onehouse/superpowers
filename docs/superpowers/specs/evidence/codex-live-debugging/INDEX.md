# Debugging evidence

Captured in /tmp/fleet-runtime-probe-8x14rwii/live/slot on 2026-09-11.

| Claim | Artifact | Source / regenerate |
|---|---|---|
| Original test fails | tests-before.log | python -m pytest test_calc.py before fix |
| Wrong operator | calc.py.before:2 | Original calc.py snapshot |
| Expected addition | test_calc.py.before:6 | Original test_calc.py snapshot |
| Corrected operator | calc.py.after:2 | Updated calc.py snapshot |
| Verification | tests-after.log | python -m pytest after fix |
