#!/usr/bin/env python3
"""SIGKILL a real `fleet dispatch` at a NAMED point in its transaction and report what it left behind.

Written by run-D.sh, into the section's own evidence dir.

The point matters more than the kill. `_do_dispatch`'s order is: claim -> gates again -> render ->
layout.bootstrap -> charter+seed -> isolate_build_cache -> register+record -> sessions.start -> record
again. Measured on this box, the claim lands ~120ms in and the child folder ~59ms after that, so the two
windows are wide enough to hit deliberately rather than hope for:

  trigger=lease  fire as soon as a claim directory exists -> inside the transaction, BEFORE the folder
  trigger=child  fire as soon as the child directory exists -> inside layout.bootstrap, mid-build

A run that fires neither trigger is reported as `fired=` and the caller counts it as an iteration that
asserted nothing (§E9's E9 reported `ok` for 82% of iterations that had nothing to assert; the fix is to
COUNT them, not to average them away).

Only the pid this process spawned is ever signalled. There is no pkill here.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

trigger, profile, title, base, cap, outfile, jsonfile = sys.argv[1:8]
home = Path(os.environ["FLEET_HOME"])
inst = Path(os.environ["FLEET_INSTANTS"])
leases, records = home / "pool" / "leases", home / "records"


def names(d, pattern="*"):
    try:
        return sorted(p.name for p in d.glob(pattern))
    except OSError:
        return []


def snapshot():
    child = [p for p in inst.iterdir()] if inst.is_dir() else []
    entries = []
    for c in child:
        if c.is_dir():
            entries = sorted(p.name for p in c.iterdir())
    return {
        "lease_dirs": names(leases),
        "lease_bodies": sorted(p.parent.name for p in leases.glob("*/lease.json")) if leases.is_dir() else [],
        "lease_staging": sorted(p.parent.name for p in leases.glob("*/.*tmp")) if leases.is_dir() else [],
        "children": sorted(p.name for p in child),
        "child_entries": entries,
        "records": names(records, "*.json"),
    }


t0 = time.monotonic()
with open(outfile, "w") as sink:
    proc = subprocess.Popen(
        [sys.executable, "-m", "fleet.cli", "dispatch", "--profile", profile, "--title", title,
         "--base", base, "--cap", cap],
        stdout=sink, stderr=subprocess.STDOUT)
    fired, at_kill = "", {}
    while proc.poll() is None:
        if trigger == "lease" and leases.is_dir() and any(leases.iterdir()):
            fired = "lease"
        elif trigger == "child" and inst.is_dir() and any(inst.iterdir()):
            fired = "child"
        if fired:
            at_kill = snapshot()
            at_kill["ms"] = round((time.monotonic() - t0) * 1000, 1)
            os.kill(proc.pid, 9)          # only ever the pid this process started
            break
        time.sleep(0.0002)
    rc = proc.wait()

after = snapshot()
report = {"trigger": trigger, "fired": fired, "rc": rc,
          "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
          "at_kill": at_kill, "after": after}
Path(jsonfile).write_text(json.dumps(report, indent=2))
#: One tab-separated line for the shell, so the caller parses fields rather than JSON.
print("\t".join(str(x) for x in (
    fired or "-", rc,
    len(after["lease_dirs"]), len(after["lease_bodies"]), len(after["lease_staging"]),
    len(after["children"]), len(after["child_entries"]),
    "CHARTER.md" in after["child_entries"] and "charter" or "no-charter",
    len(after["records"]),
    (at_kill or {}).get("ms", -1))))
