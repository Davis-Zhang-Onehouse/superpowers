#!/usr/bin/env python3
"""Mechanical completion gate for a dispatched worker instant.

Reads the instant's REVIEW.md (written by superpowers:review-workspace), finds the LATEST
round, and decides pass/fail so the coordinator cannot rationalise "findings addressed".

PASS iff the latest round's overall verdict is READY, or READY-WITH-FIXES with zero open
Critical and zero open Important findings.

    workspace-gate.py <instant-dir> [--require-scope all] [--harvest] [--json]

Exit codes:  0 = gate passed   1 = gate failed   2 = cannot decide (missing/unparseable) — fail closed.

--harvest additionally requires the worker to have renamed its own folder to `-complete-`
(a report file is not a completion signal), so it is the precondition for harvesting.
"""
import argparse
import json
import os
import re
import sys

ROUND_RE = re.compile(r"^##\s+Round\s+R(\d+)\b(.*)$", re.M)
VERDICT_RE = re.compile(r"^##\s*Round summary.*?overall verdict:\s*(READY-WITH-FIXES|NOT-READY|READY)\b",
                        re.M | re.I)
OPEN_RE = re.compile(r"^-\s*Open findings:.*?Critical[:\s]+(\d+).*?Important[:\s]+(\d+)", re.M | re.I)
SCOPE_RE = re.compile(r"scope:\s*([A-Za-z-]+)")


def decide(path, require_scope=None, harvest=False):
    """Return (rc, result-dict)."""
    r = {"instant": os.path.basename(os.path.abspath(path.rstrip("/"))), "gate": "UNKNOWN", "reasons": []}
    review = os.path.join(path, "REVIEW.md")
    if not os.path.isfile(review):
        r["reasons"].append("no REVIEW.md — the review gate was never run")
        return 2, r
    text = open(review, encoding="utf-8", errors="replace").read()

    rounds = list(ROUND_RE.finditer(text))
    if not rounds:
        r["reasons"].append("REVIEW.md has no '## Round R<n>' section")
        return 2, r
    # latest = highest round number; its body runs to the next round header (or EOF)
    idx = max(range(len(rounds)), key=lambda i: int(rounds[i].group(1)))
    start = rounds[idx].start()
    end = rounds[idx + 1].start() if idx + 1 < len(rounds) else len(text)
    body, header = text[start:end], rounds[idx].group(2)
    r["round"] = f"R{rounds[idx].group(1)}"

    vm = VERDICT_RE.search(body)
    if not vm:
        r["reasons"].append(f"round {r['round']} has no '## Round summary — overall verdict:' line")
        return 2, r
    verdict = vm.group(1).upper()
    r["verdict"] = verdict

    sm = SCOPE_RE.search(header)
    r["scope"] = sm.group(1).lower() if sm else "unknown"

    om = OPEN_RE.search(body)
    crit, imp = (int(om.group(1)), int(om.group(2))) if om else (None, None)
    r["open_critical"], r["open_important"] = crit, imp

    rc = 0
    if verdict == "NOT-READY":
        rc = 1
        r["reasons"].append("overall verdict is NOT-READY")
    elif verdict == "READY-WITH-FIXES":
        if om is None:
            rc = 2
            r["reasons"].append("READY-WITH-FIXES but no '- Open findings:' line to count Critical/Important")
        elif crit or imp:
            rc = 1
            r["reasons"].append(f"READY-WITH-FIXES with open findings: Critical {crit} · Important {imp} "
                                "(bar is zero of each)")
    if require_scope and r["scope"] != require_scope.lower():
        rc = max(rc, 1)
        r["reasons"].append(f"latest round scope is '{r['scope']}', required '{require_scope}'")

    if harvest:
        name = r["instant"]
        if "-complete-" not in name:
            rc = max(rc, 1)
            r["reasons"].append(f"instant folder is not renamed to -complete- ({name}) — a report file is "
                                "not a completion signal; the worker renames its own folder after passing")
        r["harvest_ready"] = (rc == 0)

    r["gate"] = {0: "PASS", 1: "FAIL", 2: "UNDECIDABLE"}[rc]
    if rc == 0 and not r["reasons"]:
        r["reasons"].append(f"{verdict}" + (f" with 0 open Critical/Important" if verdict != "READY" else ""))
    return rc, r


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mechanical review gate for a worker instant.")
    ap.add_argument("instant", help="path to the dispatched worker's instant folder")
    ap.add_argument("--require-scope", help="require the latest round to have this scope (e.g. all)")
    ap.add_argument("--harvest", action="store_true",
                    help="also require the folder to be renamed -complete- (harvest precondition)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)

    rc, res = decide(a.instant, a.require_scope, a.harvest)
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(f"{res['gate']}: {res.get('round','-')} verdict={res.get('verdict','-')} "
              f"scope={res.get('scope','-')}")
        for why in res["reasons"]:
            print(f"  - {why}")
        if rc:
            print("  => do NOT mark complete / harvest.", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
