#!/usr/bin/env bash
# Every shipped profile must DECLARE its kind and render with exactly the context `fleet dispatch` supplies.
#
# The kind is declared and never inferred: three of five profiles once silently became `worker` because it was
# read out of charter prose. And `Profile.render` refuses to emit an artifact containing a literal {{TOKEN}},
# so an unresolved placeholder fails here rather than reaching a charter a worker reads as authoritative.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROFILES="$HERE/../profiles"
FLEET_SRC="${FLEET_SRC:-$HERE/../../../fleet/src}"

out="$(PYTHONPATH="$FLEET_SRC" python3 - "$PROFILES" <<'PY'
import json, pathlib, sys
from fleet.profiles import Profile

root = pathlib.Path(sys.argv[1])
# Exactly what `_do_dispatch` passes to `profile.render`. If dispatch gains a substitution, this list must
# gain it too — a template that renders under a richer context than production supplies is a template that
# fails on its first real dispatch.
context = {"TITLE": "a title", "INSTANT": "00000000-07300001-inflight-append-probe", "SLOT": "ws1",
           "TODO_ID": "probe-07300001", "BASE": "00000000", "PATH": "/tmp/probe",
           "MILESTONE": "m1", "COORDINATOR": "/tmp/coord",
           "LINEAGE_BASE": "alpha=" + "a" * 40, "LINEAGE_MODE": "code",
           "CHECKOUT": "git -C alpha checkout --detach " + "a" * 40}
bad = 0
for kind in ("worker", "compaction", "coordinator"):
    d = root / kind
    if not (d / "profile.json").is_file():
        print(f"MISSING: {d}/profile.json"); bad = 1; continue
    declared = json.loads((d / "profile.json").read_text()).get("kind")
    if declared != kind:
        print(f"KIND: {kind} declares {declared!r}, expected {kind!r}"); bad = 1
    try:
        rendered = Profile.load(d).render(context)
    except Exception as exc:                       # noqa: BLE001 - the message IS the finding
        print(f"RENDER: {kind} did not render: {exc}"); bad = 1; continue
    for artifact in ("charter", "seed"):
        if artifact not in rendered:
            print(f"ARTIFACT: {kind} produced no {artifact}"); bad = 1
        elif "{{" in rendered[artifact]:
            print(f"PLACEHOLDER: {kind}/{artifact} still contains a literal {{{{"); bad = 1
if "{{CHECKOUT}}" not in (root / "worker" / "seed.txt").read_text():
    print("CHECKOUT: worker/seed.txt must reference {{CHECKOUT}}, so the positioning instruction is GENERATED "
          "from the recorded lineage base and cannot drift from the field the gate checks")
    bad = 1
print("BAD" if bad else "OK")
PY
)"
printf '%s\n' "$out"
if printf '%s' "$out" | tail -1 | grep -qx OK; then
  echo "PASS: all three profiles declare their kind, render under dispatch's full context, leave no literal {{TOKEN}}, and the worker seed generates its positioning instruction from {{CHECKOUT}}"
  exit 0
fi
echo "FAIL"
exit 1
