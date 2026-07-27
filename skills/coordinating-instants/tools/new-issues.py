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


def norm_title(t):
    """A register that renumbers its issues (I-1.. -> OI-1..) has not gained any: the titles are the
    stable content. Track both, so a prefix change is not seven false alarms."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", t.lower()).split())[:90]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Report new issue IDs since the last check.")
    ap.add_argument("issues", help="path to an ISSUES.md")
    ap.add_argument("--state", required=True, help="file storing the IDs already seen")
    ap.add_argument("--prime", action="store_true",
                    help="record what exists NOW as already-seen and report nothing. Run this when a "
                         "watcher starts: otherwise its first tick re-alarms the entire history, and "
                         "'first time I have seen this' gets conflated with 'this just happened'.")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not os.path.isfile(a.issues):
        print(f"no such file: {a.issues}", file=sys.stderr)
        return 2

    found = parse(a.issues)
    seen, seen_titles = set(), set()
    if os.path.isfile(a.state):
        for l in open(a.state, encoding="utf-8"):
            l = l.rstrip("\n")
            if not l.strip():
                continue
            ident, _, title = l.partition("\t")
            seen.add(ident.strip())
            if title.strip():
                seen_titles.add(title.strip())

    def dump():
        with open(a.state, "w", encoding="utf-8") as fh:
            for k in sorted(found):
                fh.write(f"{k}\t{norm_title(found[k])}\n")

    if a.prime:
        dump()
        print(f"primed: {len(found)} existing issue(s) recorded as already-seen (not re-alarmed)")
        return 0

    new = {k: v for k, v in found.items()
           if k not in seen and norm_title(v) not in seen_titles}
    dump()

    if a.json:
        print(json.dumps({"new": new, "total": len(found)}, indent=2, ensure_ascii=False))
    else:
        for k in sorted(new):
            print(f"{k} — {new[k]}")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
