#!/usr/bin/env python3
"""Report which issues are NEW in an ISSUES.md since the last check — by ID, not by count.

Watchers usually diff a COUNT and then print the last N headings. That is wrong the moment an
append-only file is not strictly appended: a register whose entries are kept in numeric order (or
whose author inserts a back-filled ID) grows by one while the LAST heading is unchanged, so the
watcher confidently names an issue that is not new. Observed for real: RI-8 and RI-9 landed and
the watcher announced RI-5 three times.

Diff the SET of IDs instead. That is correct regardless of ordering, insertion, or renumbering.

    new-issues.py <ISSUES.md> --state <file> [--json]

Exit: 0 = nothing new · 1 = new issues found (so a watcher can fire on non-zero) · 2 = bad input.
"""
import argparse
import json
import os
import re
import sys

HEADING = re.compile(r"^##\s+(?P<id>[A-Za-z]+-\d+)\s*[—:-]?\s*(?P<title>.*)$", re.M)


def parse(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    return {m.group("id"): m.group("title").strip() for m in HEADING.finditer(text)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Report new issue IDs since the last check.")
    ap.add_argument("issues", help="path to an ISSUES.md")
    ap.add_argument("--state", required=True, help="file storing the IDs already seen")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not os.path.isfile(a.issues):
        print(f"no such file: {a.issues}", file=sys.stderr)
        return 2

    found = parse(a.issues)
    seen = set()
    if os.path.isfile(a.state):
        seen = {l.strip() for l in open(a.state, encoding="utf-8") if l.strip()}

    new = {k: v for k, v in found.items() if k not in seen}
    with open(a.state, "w", encoding="utf-8") as fh:
        fh.write("\n".join(sorted(found)) + "\n")

    if a.json:
        print(json.dumps({"new": new, "total": len(found)}, indent=2, ensure_ascii=False))
    else:
        for k in sorted(new):
            print(f"{k} — {new[k]}")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
