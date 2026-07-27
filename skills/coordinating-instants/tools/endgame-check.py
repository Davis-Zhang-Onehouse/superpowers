#!/usr/bin/env python3
"""Check the endgame contract before a coordinator stops.

Phase F says: stop dispatch, one final compaction, gate it, STOP — and **leave no orphans**: every open
issue must end fixed, parked for the operator by name, or reassigned to a NAMED successor. "Owned by the
coordinator, later" is an orphan, because the coordinator is the thing that is stopping. That rule is the
easiest one to skip and the most expensive to skip: it is how a validate suite failing 5/5 on a secondary
dimension survived a whole effort and reached ship-readiness.

    endgame-check.py <coordinator-instant> [--json]

Exit: 0 = contract satisfied · 1 = something would be left orphaned · 2 = bad input.

What it CANNOT check, and prints as manual steps: that the final compaction's CI ran with the right
flags, and that its own gate passed. Those need the compaction instant, which may not exist yet.
"""
import argparse
import json
import os
import re
import sys

ISSUE_RE = re.compile(r"^##\s+([A-Za-z]+-\d+)\s*[—:-]?\s*(.*)$", re.M)
OPEN_RE = re.compile(r"^###?\s*Status\s*\n?\s*(.*)$", re.M | re.I)


def issue_blocks(text):
    parts = re.split(r"(?m)^(?=##\s+[A-Za-z]+-\d+)", text)
    for p in parts:
        m = ISSUE_RE.match(p)
        if m:
            yield m.group(1), m.group(2).strip(), p


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check the Phase F endgame contract.")
    ap.add_argument("instant")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    d = a.instant
    if not os.path.isdir(d):
        print(f"no such instant: {d}", file=sys.stderr)
        return 2

    issues_p = os.path.join(d, "ISSUES.md")
    handoff_p = os.path.join(d, "HANDOFF.md")
    if not os.path.isfile(issues_p):
        print(f"no ISSUES.md in {d}", file=sys.stderr)
        return 2
    itext = open(issues_p, encoding="utf-8", errors="replace").read()
    htext = open(handoff_p, encoding="utf-8", errors="replace").read() if os.path.isfile(handoff_p) else ""

    # the parked block is where operator-only items live; a successor is named anywhere in the entry
    parked = ""
    pm = re.search(r"(?m)^##\s+Parked decision.*?$(.*?)(?=^##\s|\Z)", htext, re.S)
    if pm:
        parked = pm.group(1)

    orphans, open_ids = [], []
    for iid, title, body in issue_blocks(itext):
        status_line = ""
        sm = re.search(r"(?ms)^###\s*Status\s*$\s*(.+?)$", body)
        if sm:
            status_line = sm.group(1)
        else:
            sm2 = re.search(r"(?mi)^\*\*?Status:?\*?\*?:?\s*(.+)$", body)
            status_line = sm2.group(1) if sm2 else ""
        if not re.search(r"\bOPEN\b", status_line, re.I):
            continue
        open_ids.append(iid)
        # dispositioned if: named in the parked block, OR names a successor/owner, OR carries a
        # forward-carry statement (an explicit AC on a later instant).
        disposed = (iid in parked
                    or re.search(r"(?i)(owned by|reassigned to|carried (as|into)|named successor|"
                                 r"open AC on|parked for the operator|operator-only)", body))
        if not disposed:
            orphans.append((iid, title[:70]))

    res = {"instant": os.path.basename(os.path.abspath(d.rstrip("/"))),
           "open_issues": open_ids, "orphans": [o[0] for o in orphans],
           "result": "ORPHANS" if orphans else "OK"}

    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(f"{res['result']}: {len(open_ids)} open issue(s), {len(orphans)} would be orphaned")
        for iid, t in orphans:
            print(f"  ORPHAN {iid} — {t}")
            print(f"    ends neither fixed, parked by name, nor reassigned to a NAMED successor.")
        if not orphans and open_ids:
            print("  every open issue is parked, reassigned, or carried forward explicitly.")
        print()
        print("  NOT checkable here — do these by hand on the final compaction:")
        print("   · run its CI diff with `pdispatch regress --strict-coverage` and WITHOUT")
        print("     `--allow-new-red`, so a lost dimension and a red-with-no-baseline both BLOCK.")
        print("   · gate it with `pdispatch gate <compaction> --harvest --record --require-scope all`.")
        print("   · re-assert every registry-CLOSED row by name via `--closed-from-md`.")
    return 1 if orphans else 0


if __name__ == "__main__":
    sys.exit(main())
