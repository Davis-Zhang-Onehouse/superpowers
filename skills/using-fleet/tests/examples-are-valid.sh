#!/usr/bin/env bash
# Every `--finding` string any fleet skill prints must be ACCEPTED by the product.
#
# This exists because of a specific failure, found by a real dispatched worker in §P: the worker skill's
# copy-paste finish sequence documented
#     --finding "RV-1:info:closed:evidence/INDEX.md:every AC has an artifact:none"
# and BOTH `info` and `closed` are outside their declared domains, so the command exited 2 — on the one block
# a finishing worker is most likely to paste, gating the verb that gates `complete`.
#
# V1 could not catch it: `fleet review` is a real verb. V2 could not: the claim beside it was true. A
# six-field colon-joined string with two closed domains is simply not checkable by eye, so it is checked by
# the parser that will reject it.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SKILLS="$HERE/../.."
FLEET_SRC="$HERE/../../../fleet/src"

# Every --finding "..." occurrence across every skill, with the file it came from.
mapfile -t FOUND < <(grep -rhno -- '--finding "[^"]*"' "$SKILLS"/*/SKILL.md 2>/dev/null | sed 's/.*--finding "//; s/"$//')
if [ "${#FOUND[@]}" -eq 0 ]; then
  echo "PASS: no fleet skill documents a --finding string, so there is nothing to validate (and this suite will start binding the moment one does)"
  exit 0
fi

out="$(PYTHONPATH="$FLEET_SRC" python3 - "${FOUND[@]}" <<'PY'
import sys
from fleet.cli import _finding_of
from fleet.errors import BadInput
from fleet.review import FINDING_STATUSES, SEVERITIES

bad = 0
for text in sys.argv[1:]:
    try:
        f = _finding_of(text)
    except BadInput as exc:
        print(f"SHAPE: {text!r} -> {exc}")
        bad = 1
        continue
    if f.severity not in SEVERITIES:
        print(f"SEVERITY: {text!r} uses {f.severity!r}; allowed {SEVERITIES}")
        bad = 1
    if f.status not in FINDING_STATUSES:
        print(f"STATUS: {text!r} uses {f.status!r}; allowed {FINDING_STATUSES}")
        bad = 1
print(f"checked {len(sys.argv) - 1}")
print("BAD" if bad else "OK")
PY
)"
printf '%s\n' "$out"
if printf '%s' "$out" | tail -1 | grep -qx OK; then
  echo "PASS: every --finding string documented in a fleet skill parses into six fields and uses only values inside the severity and status domains — checked by the product's own parser, because a colon-joined string with two closed domains is not checkable by eye"
  exit 0
fi
echo "FAIL"
exit 1
