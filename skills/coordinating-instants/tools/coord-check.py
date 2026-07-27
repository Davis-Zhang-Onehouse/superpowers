#!/usr/bin/env python3
"""Detect drift between the coordinator's HANDOFF registry and reality on disk.

The registry rots the moment you look away. This compares each milestone row's Status
against the actual state of its instant folder and reports the mismatches — most
importantly the silent one: a worker whose folder says `-complete-` while the registry
still says running, i.e. DONE-BUT-UNHARVESTED.

    coord-check.py --handoff HANDOFF.md --instants-dir <dir-holding-the-instants> [--json]

Exit codes: 0 = in sync   1 = drift found   2 = bad input.
"""
import argparse
import json
import os
import re
import sys

DONE = "done"
RUNNING = "running"
PENDING = "pending"
OTHER = "other"

STATUS_CLASS = [
    (r"⛔|⏹|🔀|SUPERSEDED", OTHER),
    (r"🅿|PARKED", OTHER),
    (r"✅|🟩|\bDONE\b|\bCOMPLETE\b", DONE),
    (r"🔵|\bRUNNING\b|\bDISPATCHED\b|\bINFLIGHT\b", RUNNING),
    (r"🟨|\bREADY\b|⬜|⬛|🔲|\bTODO\b|\bBLOCKED\b", PENDING),
]


def classify(cell):
    up = cell.upper()
    for pat, cls in STATUS_CLASS:
        if re.search(pat, up if pat.isupper() or "\\b" in pat else cell, re.I):
            return cls
    return OTHER


def resolve(raw, on_disk):
    """Registries abbreviate long instant names with an ellipsis. Resolve to the real folder.

    Returns (resolved_name_or_None, all_matches). Exact match wins; otherwise `…`/`...` are
    treated as wildcards. Ambiguity is reported, never silently picked.
    """
    if raw in on_disk:
        return raw, [raw]
    if "…" in raw or "..." in raw:
        parts = [re.escape(p) for p in re.split(r"…|\.\.\.", raw)]
        pat = re.compile("^" + ".*".join(parts) + "$")
        matches = [n for n in on_disk if pat.match(n)]
        if len(matches) == 1:
            return matches[0], matches
        return None, matches
    return None, []


def rows(handoff):
    """Yield (instant_name, status_cell) from any markdown table having Instant + Status columns."""
    lines = open(handoff, encoding="utf-8", errors="replace").read().splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$", lines[i + 1]):
            head = [c.strip().lower() for c in ln.strip("|").split("|")]
            try:
                ii, si = head.index("instant"), head.index("status")
            except ValueError:
                i += 2
                while i < len(lines) and lines[i].strip().startswith("|"):
                    i += 1
                continue
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if len(cells) > max(ii, si):
                    m = re.search(r"`([^`]+)`", cells[ii])
                    name = (m.group(1) if m else cells[ii]).strip()
                    name = re.sub(r"[*~]", "", name).strip()
                    if name and name not in ("—", "-", ""):
                        yield name, cells[si]
                i += 1
            continue
        i += 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Coordinator registry drift check.")
    ap.add_argument("--handoff", required=True)
    ap.add_argument("--instants-dir", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    for p in (a.handoff, a.instants_dir):
        if not os.path.exists(p):
            print(f"error: no such path: {p}", file=sys.stderr)
            return 2

    on_disk = sorted(os.listdir(a.instants_dir))
    drift, checked = [], 0
    for raw, status in rows(a.handoff):
        # Registry cells that aren't instant references at all (placeholders like "(fires when X)") are skipped.
        if not re.search(r"-(inflight|complete|abort)-", raw):
            continue
        checked += 1
        cls = classify(status)
        name, matches = resolve(raw, on_disk)
        if len(matches) > 1:
            drift.append({"instant": raw, "kind": "ambiguous-reference",
                          "detail": f"abbreviated name matches {len(matches)} folders "
                                    f"({', '.join(matches[:3])}…) — write it unambiguously"})
            continue
        if name is None:
            drift.append({"instant": raw, "kind": "missing-folder",
                          "detail": f"registry references an instant that does not exist in {a.instants_dir}"})
            continue
        if "-complete-" in name and cls == RUNNING:
            drift.append({"instant": name, "kind": "done-but-unharvested",
                          "detail": "folder is -complete- but the registry still says running — "
                                    "gate it and harvest its delta, then update the row"})
        elif "-inflight-" in name and cls == DONE:
            drift.append({"instant": name, "kind": "done-but-still-inflight",
                          "detail": "registry says done but the folder is still -inflight- — the worker "
                                    "never renamed it, so it was never gated"})
    res = {"checked_rows": checked, "drift": drift, "result": "DRIFT" if drift else "IN-SYNC"}
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(f"{res['result']} — {checked} row(s) checked, {len(drift)} drift")
        for d in drift:
            print(f"  {d['kind']}: {d['instant']}\n    {d['detail']}")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
