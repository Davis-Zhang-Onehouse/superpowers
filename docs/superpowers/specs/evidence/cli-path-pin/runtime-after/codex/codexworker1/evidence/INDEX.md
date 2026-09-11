# Evidence index

| Criterion | Artifact | Source / reproduce |
|---|---|---|
| Original source captured before editing | calc.before.py, test_calc.before.py | Copies of slot files before the fix; retained historical evidence |
| Failure reproduced before editing | unittest-before.txt, unittest-before.exit | python3 -m unittest -v on original source; exit 1 |
| Fix verified | unittest-after.txt, unittest-after.exit | python3 -m unittest -v in slot1; exit 0, one test passed |
| Minimal change reviewed | change.diff, calc.after.py | Original vs final source; test file verified byte-identical |

Diagnosis: [analysis](../investigations/addition/analysis.md).
