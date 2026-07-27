#!/usr/bin/env python3
"""Flatten JUnit/surefire XML into the `name<TAB>PASS|FAIL` shape regression-check.py consumes.

Ship this so nobody hand-rolls the adapter. A hand-rolled one bit for real: the regex
`<testsuite\\s+[^>]*?name="([^"]+)"` captures the CI container HOSTNAME, because surefire writes
`hostname="…"` before `name="…"` and `hostname="` ends with `name="`. Every name then differs per
run, nothing matches across runs, and the diff is confidently, wholly wrong. Parsing XML as XML
removes that whole class.

    surefire-to-tsv.py <dir-or-file>... [--dim <label>] [--include-skipped]

Per-dimension runs must NOT be collapsed with "FAIL anywhere wins": a test that fails on one CI
dimension and passes on another then looks like a regression on both. Pass --dim to qualify names
with the dimension, and diff each dimension separately.

Output: one `<suite>::<test><TAB>PASS|FAIL` per line, sorted, duplicates resolved to FAIL (a retry
that failed once is not a pass for the same dimension).
"""
import argparse
import os
import sys
import xml.etree.ElementTree as ET


def xml_files(paths):
    for p in paths:
        if os.path.isfile(p):
            yield p
        elif os.path.isdir(p):
            for root, _, names in os.walk(p):
                for n in sorted(names):
                    if n.endswith(".xml") and (n.startswith("TEST-") or "surefire" in root.lower()
                                               or n.startswith("TESTS-")):
                        yield os.path.join(root, n)
        else:
            print(f"warning: no such path: {p}", file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Flatten surefire/JUnit XML to name<TAB>PASS|FAIL.")
    ap.add_argument("paths", nargs="+", help="surefire directories and/or XML files")
    ap.add_argument("--dim", help="CI dimension label; qualifies every name so dimensions are never collapsed")
    ap.add_argument("--include-skipped", action="store_true",
                    help="emit skipped tests as SKIP (default: omit them — a skipped test is not a result)")
    a = ap.parse_args(argv)

    results = {}
    files = suites = 0
    for f in xml_files(a.paths):
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError as e:
            print(f"warning: unparseable XML {f}: {e}", file=sys.stderr)
            continue
        files += 1
        # a file may hold <testsuite> or <testsuites><testsuite>…
        nodes = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
        for ts in nodes:
            suites += 1
            suite = ts.get("name") or "(unnamed-suite)"     # attribute lookup, not a regex
            for tc in ts.findall("testcase"):
                tname = tc.get("name") or "(unnamed-test)"
                key = f"{suite}::{tname}"
                if a.dim:
                    key = f"{a.dim}::{key}"
                if tc.find("failure") is not None or tc.find("error") is not None:
                    status = "FAIL"
                elif tc.find("skipped") is not None:
                    status = "SKIP"
                else:
                    status = "PASS"
                prev = results.get(key)
                # FAIL wins over PASS within one dimension (a flaky retry is not a pass)
                if prev == "FAIL" or (prev == "PASS" and status == "FAIL"):
                    status = "FAIL"
                elif prev == "PASS" and status == "SKIP":
                    status = "PASS"
                results[key] = status

    emitted = 0
    for k in sorted(results):
        v = results[k]
        if v == "SKIP" and not a.include_skipped:
            continue
        print(f"{k}\t{v}")
        emitted += 1

    fails = sum(1 for v in results.values() if v == "FAIL")
    print(f"# {files} file(s), {suites} suite(s), {emitted} result(s) emitted, {fails} FAIL",
          file=sys.stderr)
    if emitted == 0:
        print("# nothing emitted — check the paths and that these are surefire/JUnit XMLs", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
