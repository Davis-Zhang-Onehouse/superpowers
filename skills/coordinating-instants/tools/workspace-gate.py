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
import datetime
import glob
import json
import os
import re
import sys

# "## Round R2 summary — overall verdict: …" is a SUMMARY, not the start of round R2. Without the
# negative lookahead the summary line is consumed as a round header and the round it opens contains
# no summary — so the gate reports "no verdict line" for a file that plainly has one.
ROUND_RE = re.compile(r"^##\s+Round\s+R(\d+)(?!\s+summary)\b(.*)$", re.M | re.I)
# Accept both the single-round "## Round summary" and the per-round "## Round R2 summary" headings.
VERDICT_RE = re.compile(r"^##\s*Round(?:\s+R\d+)?\s+summary.*?overall verdict:\s*"
                        r"(READY-WITH-FIXES|NOT-READY|READY)\b", re.M | re.I)
# Tolerate both the template's "- Open findings: Critical n · Important n" and the equally common
# "- Open Critical: n · Open Important: n". Reviewers write markdown, not a grammar.
OPEN_RE = re.compile(r"^-\s*.*?Open.*?Critical[:\s]+(\d+).*?Important[:\s]+(\d+)", re.M | re.I)
# Only round-SHAPED phrasings count: "R1" alone is a milestone name in many efforts, and reading
# those as review rounds would fire on every instant.
CLAIM_RE = re.compile(r"(?:review\s+round|REVIEW\.md\s+|\bround)\s+R(\d+)", re.I)
SUMMARY_LINE_RE = re.compile(r"^##\s*Round(?:\s+R\d+)?\s+summary.*$", re.M | re.I)


def strip_emphasis(text):
    """Markdown emphasis is idiomatic and nothing enforces bare text; a gate that cannot read a
    BOLD verdict fails a genuinely-READY worker — the worst direction for a gate to be wrong in."""
    return text.replace("**", "").replace("__", "").replace("`", "")
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
    body, header = strip_emphasis(text[start:end]), strip_emphasis(rounds[idx].group(2))
    r["round"] = f"R{rounds[idx].group(1)}"

    vm = VERDICT_RE.search(body)
    if not vm:
        # Distinguish "the line is missing" from "the line is there but I cannot read it" — saying
        # ABSENT when it is merely unparseable sends the reader hunting for the wrong problem.
        sm_line = SUMMARY_LINE_RE.search(body)
        if sm_line:
            r["reasons"].append(
                f"round {r['round']}: could not parse a verdict from this line — "
                f"{sm_line.group(0).strip()!r}; expected READY | READY-WITH-FIXES | NOT-READY")
        else:
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
    # Stages accumulate ACROSS rounds: R1=all followed by a narrow R2 re-review is the normal shape,
    # and judging only the latest round would reject it. The newest round still governs the VERDICT.
    scopes = set()
    for m in rounds:
        sm2 = SCOPE_RE.search(m.group(2))
        if sm2:
            scopes.add(sm2.group(1).lower())
    r["scopes_across_rounds"] = sorted(scopes)
    if require_scope:
        want = require_scope.lower()
        satisfied = (want in scopes) or (want == "all" and {"format", "alignment", "code"} <= scopes)
        if not satisfied:
            rc = max(rc, 1)
            r["reasons"].append(f"scopes across rounds are {sorted(scopes) or ['unknown']}, "
                                f"which do not cover '{require_scope}'")

    if harvest:
        name = r["instant"]
        if "-complete-" not in name:
            rc = max(rc, 1)
            r["reasons"].append(f"instant folder is not renamed to -complete- ({name}) — a report file is "
                                "not a completion signal; the worker renames its own folder after passing")
        r["harvest_ready"] = (rc == 0)

    # A verdict with no recorded stage verdicts, findings or scope has no visible basis. Advisory: the
    # ledger stays the arbiter, but an empty round must not read identically to an evidenced one.
    if not re.search(r"^###\s*Stage\s+\d", body, re.M) and not re.search(r"^####?\s*RV-\d", body, re.M):
        r["reasons"].append(f"advisory: round {r['round']} records a verdict but no stage verdicts and no "
                            f"RV- findings — thin ledger, nothing shows what was actually reviewed")

    # Advisory only: prose that claims a round the ledger does not contain is a narrative ahead of
    # its evidence. It never changes the verdict — the ledger is the arbiter either way.
    have = {m.group(1) for m in ROUND_RE.finditer(text)}
    claimed = set()
    for fn in ("HANDOFF.md", "ISSUES.md"):
        fp = os.path.join(path, fn)
        if os.path.isfile(fp):
            body = open(fp, encoding="utf-8", errors="replace").read()
            claimed |= {m.group(1) for m in CLAIM_RE.finditer(body)}
    unbacked = sorted(claimed - have, key=int)
    if unbacked:
        r["unbacked_round_claims"] = unbacked
        r["reasons"].append("advisory: prose claims review round(s) R" + ", R".join(unbacked) +
                            " that REVIEW.md does not contain — write the ledger before describing it")

    r["gate"] = {0: "PASS", 1: "FAIL", 2: "UNDECIDABLE"}[rc]
    if rc == 0 and not r["reasons"]:
        r["reasons"].append(f"{verdict}" + (f" with 0 open Critical/Important" if verdict != "READY" else ""))
    return rc, r


def mark_harvested(instant, res):
    """Write gate_verdict + harvested_at into the instant's dispatch record, if there is one.

    Instants get RENAMED (-inflight- -> -complete-), so match records on the stable
    <base>-<curr> timestamp prefix of the folder name rather than the recorded path.
    """
    board = os.environ.get("BOARD_DIR") or os.path.join(os.path.expanduser("~"), ".claude-dispatch-board")
    name = os.path.basename(os.path.abspath(instant.rstrip("/")))
    # <base>-<curr> is NOT unique — two instants dispatched in the same minute share it. The stable
    # identity is the whole name with only the <state> token varying.
    m = re.match(r"^(\d{8}-\d{8})-(?:inflight|complete|abort)-(.+)$", name)
    if not m:
        return None
    pref, rest = m.group(1), m.group(2)
    for f in sorted(glob.glob(os.path.join(board, "records", "*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        child = os.path.basename(str(d.get("child_instant", "")).rstrip("/"))
        cm = re.match(r"^(\d{8}-\d{8})-(?:inflight|complete|abort)-(.+)$", child)
        if not cm or cm.group(1) != pref or cm.group(2) != rest:
            continue
        d["gate_verdict"] = res.get("verdict")
        d["gate_round"] = res.get("round")
        d["harvested_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=2, ensure_ascii=False)
        return f
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mechanical review gate for a worker instant.")
    ap.add_argument("instant", help="path to the dispatched worker's instant folder")
    ap.add_argument("--require-scope", help="require the latest round to have this scope (e.g. all)")
    ap.add_argument("--harvest", action="store_true",
                    help="also require the folder to be renamed -complete- (harvest precondition)")
    ap.add_argument("--record", action="store_true",
                    help="on a PASSING --harvest gate, persist gate_verdict + harvested_at into the "
                         "dispatch board record, so a successor coordinator inherits harvest state "
                         "mechanically instead of trusting prose")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)

    rc, res = decide(a.instant, a.require_scope, a.harvest)

    if a.record:
        if rc == 0 and a.harvest:
            marked = mark_harvested(a.instant, res)
            res["recorded_in"] = marked or "(no matching board record)"
        else:
            res["recorded_in"] = "(not recorded — gate did not pass with --harvest)"
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
