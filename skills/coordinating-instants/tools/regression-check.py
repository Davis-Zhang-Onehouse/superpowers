#!/usr/bin/env python3
"""Two-diff non-regression check for a coordinator harvest.

Diffing only against the fixed original baseline misses the most dangerous class: an item a
PRIOR instant already turned green that THIS stack turns red again. Versus the original
baseline that is red->red, i.e. invisible. Catching it needs a second diff against the
**lineage base** (the end-state this instant inherited), plus a by-name assertion that every
row the registry marks CLOSED is actually green now.

    regression-check.py --baseline B --current C [--lineage-base L]
                        [--closed-list F | --closed-from-md REGISTRY [--closed-marker 🟩]] [--json]

Results files: one `name<TAB>PASS|FAIL` per line (whitespace-separated also accepted; `#`
comments and blanks ignored). Adapt whatever your CI produces into this shape.

Exit codes: 0 = clean   1 = regressions / re-breaks / closed-not-green found   2 = bad input.
"""
import argparse
import json
import os
import re
import sys

PASSY = {"PASS", "PASSED", "OK", "GREEN", "SUCCESS", "1", "TRUE"}
FAILY = {"FAIL", "FAILED", "ERROR", "RED", "FAILURE", "0", "FALSE"}


def load(path):
    if not os.path.isfile(path):
        print(f"error: no such results file: {path}", file=sys.stderr)
        sys.exit(2)
    out = {}
    for ln in open(path, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split("\t") if "\t" in ln else ln.rsplit(None, 1)
        if len(parts) != 2:
            continue
        name, status = parts[0].strip(), parts[1].strip().upper()
        if status in PASSY:
            out[name] = True
        elif status in FAILY:
            out[name] = False
    return out


def closed_from_md(path, marker):
    """Extract identifiers from registry rows carrying the closed marker."""
    ids = []
    for ln in open(path, encoding="utf-8", errors="replace"):
        if marker not in ln or not ln.strip().startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if not cells:
            continue
        m = re.search(r"`([^`]+)`", cells[0])
        ident = (m.group(1) if m else cells[0]).strip()
        ident = re.sub(r"[*~]", "", ident).strip()
        if ident:
            ids.append(ident)
    return ids


def main(argv=None):
    ap = argparse.ArgumentParser(description="Two-diff non-regression check.")
    ap.add_argument("--baseline", required=True, help="the fixed original baseline results")
    ap.add_argument("--current", required=True, help="this run's results")
    ap.add_argument("--lineage-base", help="results of the end-state this instant inherited (the second diff)")
    ap.add_argument("--closed-list", help="file of identifiers the registry marks CLOSED (one per line)")
    ap.add_argument("--closed-from-md", help="registry markdown to extract CLOSED rows from")
    ap.add_argument("--closed-marker", default="🟩", help="marker denoting a closed row (default 🟩)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    base, cur = load(a.baseline), load(a.current)
    lin = load(a.lineage_base) if a.lineage_base else None

    regressions = sorted(n for n, ok in base.items() if ok and cur.get(n) is False)
    rebreaks = sorted(n for n, ok in (lin or {}).items()
                      if ok and cur.get(n) is False and n not in regressions)

    closed = []
    if a.closed_list:
        closed = [l.strip() for l in open(a.closed_list, encoding="utf-8") if l.strip() and not l.startswith("#")]
    elif a.closed_from_md:
        closed = closed_from_md(a.closed_from_md, a.closed_marker)
    closed_not_green = sorted(n for n in closed if cur.get(n) is not True)
    missing = sorted(n for n in closed if n not in cur)

    res = {
        "regressions": regressions,
        "rebreaks": rebreaks,
        "closed_not_green": closed_not_green,
        "closed_absent_from_results": missing,
        "counts": {"baseline": len(base), "current": len(cur), "lineage_base": len(lin or {}), "closed": len(closed)},
        "lineage_diff_run": lin is not None,
    }
    rc = 1 if (regressions or rebreaks or closed_not_green) else 0
    res["result"] = "FAIL" if rc else "CLEAN"

    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(f"{res['result']} — regressions={len(regressions)} rebreaks={len(rebreaks)} "
              f"closed-not-green={len(closed_not_green)}")
        for n in regressions:
            print(f"  REGRESSION (green->red vs baseline): {n}")
        for n in rebreaks:
            print(f"  RE-BREAK (green in lineage base, red now — invisible vs baseline): {n}")
        for n in closed_not_green:
            tag = "absent from results" if n in missing else "red"
            print(f"  CLOSED-NOT-GREEN (registry says closed, run says {tag}): {n}")
        if lin is None:
            print("  note: no --lineage-base given — the re-break class was NOT checked.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
