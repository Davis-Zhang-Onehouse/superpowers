#!/usr/bin/env python3
"""Check an instant's canonical file SET exists — presence, not content.

A review's format stage inspects the content of files that are present, so a missing canonical file
passes it silently. That is the day's recurring family: a check that passes without checking the
thing you care about. This asks the one question the content checks cannot.

Authority for the set is superpowers:maintain-workspace (templates.md). NOTE that `STATE.md` is NOT
in it: `dispatch-todo` seeds one as a convenience, and folding its contents into HANDOFF is a
legitimate choice several instants made — so a missing STATE.md is reported as INFO, never a
violation. Nothing else may be absent.

    workspace-lint.py <instant-dir> [--json] [--require-state]

Exit: 0 clean · 1 violations · 2 bad input.
"""
import argparse
import json
import os
import re
import sys

REQUIRED_FILES = ["HANDOFF.md", "CHARTER.md", "RUNBOOK.md", "DECISIONS.md", "ISSUES.md", "ASSUMPTIONS.md"]
REQUIRED_DIRS = ["evidence", "investigations", "plans"]
OPTIONAL_FILES = ["STATE.md", "REVIEW.md", "COMPACTED.md"]
HEADER_RE = re.compile(r"^(?:Updated|Status)\s*:", re.M | re.I)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check an instant's canonical file set.")
    ap.add_argument("instant")
    ap.add_argument("--require-state", action="store_true",
                    help="also require STATE.md. Off by default: it is not in maintain-workspace's "
                         "canonical set, and folding it into HANDOFF is legitimate.")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    d = a.instant
    if not os.path.isdir(d):
        print(f"no such instant: {d}", file=sys.stderr)
        return 2

    missing_files = [f for f in REQUIRED_FILES if not os.path.isfile(os.path.join(d, f))]
    if a.require_state and not os.path.isfile(os.path.join(d, "STATE.md")):
        missing_files.append("STATE.md")
    missing_dirs = [x for x in REQUIRED_DIRS if not os.path.isdir(os.path.join(d, x))]
    no_evidence_index = (os.path.isdir(os.path.join(d, "evidence"))
                         and not os.path.isfile(os.path.join(d, "evidence", "INDEX.md")))
    # a canonical file with no Updated:/Status: header is present-but-unmaintained
    headerless = []
    for f in REQUIRED_FILES:
        p = os.path.join(d, f)
        if os.path.isfile(p):
            head = "".join(open(p, encoding="utf-8", errors="replace").readlines()[:4])
            if not HEADER_RE.search(head):
                headerless.append(f)
    info = [f for f in OPTIONAL_FILES if not os.path.isfile(os.path.join(d, f))]

    viol = bool(missing_files or missing_dirs or no_evidence_index or headerless)
    res = {"instant": os.path.basename(os.path.abspath(d.rstrip("/"))),
           "missing_files": missing_files, "missing_dirs": missing_dirs,
           "evidence_index_missing": no_evidence_index, "headerless": headerless,
           "absent_optional": info, "result": "VIOLATIONS" if viol else "OK"}

    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(f"{res['result']}: {res['instant']}")
        for f in missing_files:
            print(f"  MISSING canonical file: {f}")
        for x in missing_dirs:
            print(f"  MISSING canonical dir:  {x}/")
        if no_evidence_index:
            print("  MISSING evidence/INDEX.md (evidence exists but is unindexed)")
        for f in headerless:
            print(f"  NO HEADER in {f} — a canonical file needs an 'Updated:'/'Status:' header")
        if info:
            note = " (STATE.md may legitimately be folded into HANDOFF)" if "STATE.md" in info else ""
            print(f"  info: absent optional file(s): {', '.join(info)}{note}")
    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(main())
