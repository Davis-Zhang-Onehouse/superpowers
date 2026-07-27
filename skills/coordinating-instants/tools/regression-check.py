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
    ap.add_argument("--allow-new-red", action="store_true",
                    help="downgrade NEW-RED (a test absent from every baseline that fails now) to a "
                         "warning. Use only for residuals documented as intentionally red — they are "
                         "still listed.")
    ap.add_argument("--strict-coverage", action="store_true",
                    help="fail if a baseline did not cover tests present in the current run, i.e. the "
                         "diff for those tests could not run at all (a CI dim that uploaded no results)")
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
    # A test present NOW but absent from a baseline cannot be diffed against it. Skipping those
    # silently is the "absence read as absence of failure" error this tool exists to catch, so the
    # gap is always reported — and can be made fatal.
    # Split "absent from the baselines" by its CURRENT result. A test that no baseline covered and
    # that FAILS now is not merely unproven — it is a red that no diff can ever surface, because
    # there was never a green to lose. That blindness is how a fully-failing new suite ships.
    absent = [n for n in cur if n not in base and (lin is None or n not in lin)]
    new_red = sorted(n for n in absent if cur.get(n) is False)
    new_green = sorted(n for n in absent if cur.get(n) is True)
    uncomparable_lineage = sorted(n for n in cur if lin is not None and n not in lin and n not in absent)
    uncomparable_baseline = sorted(n for n in cur if n not in base and n not in absent)

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
    res["not_comparable_vs_lineage_base"] = uncomparable_lineage
    res["not_comparable_vs_baseline"] = uncomparable_baseline
    res["new_red"] = new_red
    res["new_green"] = new_green
    rc = 1 if (regressions or rebreaks or closed_not_green) else 0
    if new_red and not a.allow_new_red:
        rc = 1
    if a.strict_coverage and (uncomparable_lineage or uncomparable_baseline):
        rc = 1
    res["result"] = "FAIL" if rc else "CLEAN"

    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(f"{res['result']} — regressions={len(regressions)} rebreaks={len(rebreaks)} "
              f"new-red={len(new_red)} closed-not-green={len(closed_not_green)}")
        for n in new_red:
            tag = "warning, allowed" if a.allow_new_red else "FAIL"
            print(f"  NEW-RED ({tag}): {n} — added since the baselines and failing; no diff can see this")
        if new_green:
            print(f"  new since the baselines and green: {len(new_green)} test(s) (informational)")
        for n in regressions:
            print(f"  REGRESSION (green->red vs baseline): {n}")
        for n in rebreaks:
            print(f"  RE-BREAK (green in lineage base, red now — invisible vs baseline): {n}")
        gaps = len(uncomparable_lineage) + len(uncomparable_baseline)
        if gaps:
            print(f"  coverage: NOT COMPARABLE for {gaps} test(s) — a baseline never covered them, so "
                  f"their diff could not run:")
            for n in (uncomparable_lineage or uncomparable_baseline)[:8]:
                which = "lineage base" if n in uncomparable_lineage else "baseline"
                print(f"    not in {which}: {n}")
            print("  treat these as UNPROVEN, not unbroken (use --strict-coverage to fail on them).")
        else:
            print("  coverage: complete — every current test was comparable against each baseline.")
        for n in closed_not_green:
            tag = "absent from results" if n in missing else "red"
            print(f"  CLOSED-NOT-GREEN (registry says closed, run says {tag}): {n}")
        if lin is None:
            print("  note: no --lineage-base given — the re-break class was NOT checked.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
