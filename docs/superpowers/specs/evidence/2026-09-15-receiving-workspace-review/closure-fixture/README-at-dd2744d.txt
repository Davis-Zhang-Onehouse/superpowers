# linkgate
The check is exercised by the case list in `.github/tests/cases.sh`, which also gates that every
exit status the checker can produce has a case. The count is derived, not asserted: run
`bash .github/tests/cases.sh` (it prints `26 passed, 0 failed` at this tip).

## Quickstart
Run the harness before opening a PR: `FAST=1 bash .github/tests/cases.sh`.
The suite is 22 cases and finishes in under a second with `FAST=1`.
