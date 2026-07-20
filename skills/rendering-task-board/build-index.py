#!/usr/bin/env python3
"""Roll up a task-board deliverable's 00-INDEX board from its ticket files.

A task-board deliverable is a FOLDER (its own git repo): one markdown ticket per issue
(`<class>-NN-slug.md`, one issue per file) plus a `00-INDEX.md` snapshot board. This tool
owns the mechanical, drift-prone part — the status-grouped index tables — so the author can
focus on the judgment part (de-churning each ticket to a current-status snapshot, sourcing,
decomposition). See SKILL.md for the full standard.

Each ticket must carry ONE line:  **Status:** <marker + optional qualifier>
Status is read via the legend emojis (✅ 🟩 · 🔵 · ⏳ · 🅿 · ⬜ ⬛ 🔲 · ⛔ ⏹ 🔀) or textual
words (DONE/CLOSED, RUNNING, PENDING/BLOCKED, PARKED, TODO/OPEN, SUPERSEDED). Open tickets are
sub-grouped by their filename class prefix (hygiene / residual / reconciliation / scope / …).

Usage:
    build-index.py <board-dir>            # print the grouped board (the AUTO region) to stdout
    build-index.py --write <board-dir>    # rewrite the region between the AUTO markers in 00-INDEX.md
    build-index.py --check <board-dir>    # exit 1 if any ticket lacks a Status line, or the index drifted

The AUTO region in 00-INDEX.md is delimited by:
    <!-- board:auto:start -->
    <!-- board:auto:end -->
Everything outside those markers (North-star / bottom-line prose) is author-owned and preserved.
"""
import argparse
import os
import re
import sys

START = "<!-- board:auto:start -->"
END = "<!-- board:auto:end -->"
STATUS_CAP = 90

EMOJI_BUCKET = {
    "✅": "done", "🟩": "done", "🟢": "done", "☑": "done",
    "🔵": "in_progress", "🔷": "in_progress", "🏃": "in_progress",
    "⏳": "blocked", "⏸": "blocked", "🚧": "blocked",
    "🅿": "parked",
    "⬜": "todo", "⬛": "todo", "🔲": "todo", "☐": "todo", "▢": "todo",
    "⛔": "superseded", "⏹": "superseded", "🔀": "superseded", "🚫": "superseded",
}
TEXT_BUCKET = [
    (r"\bSUPERSEDED\b|\bDROPPED\b|\bABANDONED\b|\bOBSOLETE\b", "superseded"),
    (r"\bDONE\b|\bCOMPLETE\b|\bCOMPLETED\b|\bCLOSED\b|\bMERGED\b", "done"),
    (r"\bRUNNING\b|\bDISPATCHED\b|\bINFLIGHT\b|\bIN.PROGRESS\b|\bWIP\b", "in_progress"),
    (r"\bPENDING\b|\bBLOCKED\b|\bWAITING\b|\bAWAIT", "blocked"),
    (r"\bPARKED\b", "parked"),
    (r"\bTODO\b|\bOPEN\b|\bPLANNED\b|\bNOT.STARTED\b", "todo"),
]
# open sub-groups: class-prefix -> (sort key, heading). Unknown classes fall through to "Open".
OPEN_GROUPS = {
    "hygiene": (10, "Merge / hygiene"),
    "residual": (20, "Residual tail"),
    "reconciliation": (20, "Residual tail"),
    "scope": (30, "Next effort — scope"),
}
OPEN_DEFAULT = (40, "Open")


def status_bucket(text):
    for ch in text:
        if ch in EMOJI_BUCKET:
            return EMOJI_BUCKET[ch]
    up = text.upper().replace("-", " ")
    for pat, bucket in TEXT_BUCKET:
        if re.search(pat, up):
            return bucket
    return None


def short(text):
    t = re.sub(r"\s+", " ", text).strip()
    if len(t) <= STATUS_CAP:
        return t
    return t[:STATUS_CAP].rsplit(" ", 1)[0].rstrip(" .,;—-") + "…"


def is_ticket(fname):
    if not fname.endswith(".md"):
        return False
    stem = fname[:-3]
    return stem.upper() not in ("00-INDEX", "INDEX", "README")


def parse_ticket(path):
    """Return dict(id, task, status, bucket, cls) or None if no Status line."""
    text = open(path, encoding="utf-8").read()
    # `**Status:**` may start its own line OR sit inline in a `· **Field:** … · **Status:** … · **Field:**`
    # metadata line. Capture up to the next ` · **Field**` separator or end of line.
    sm = re.search(r"\*\*Status:?\*\*:?\s*(.+?)(?:\s+·\s+\*\*|$)", text, re.M)
    if not sm:
        return None
    status = sm.group(1).strip()
    bucket = status_bucket(status)
    if bucket is None:
        return None
    tm = re.search(r"^#\s+(.*)$", text, re.M)
    title = tm.group(1).strip() if tm else os.path.basename(path)[:-3]
    task = re.sub(r"^\[[^\]]*\]\s*", "", title).strip()  # drop a leading [tag]
    tid = os.path.basename(path)[:-3]
    return {"id": tid, "task": task, "status": short(status), "bucket": bucket, "cls": classify(tid)}


def classify(tid):
    """Class = the known ticket-class token in the id, wherever it sits (ids may be prefixed
    with a tracker key like `ENG-45519-hygiene-01-…`). Falls back to the first token."""
    tokens = tid.lower().split("-")
    for known in ("hygiene", "residual", "reconciliation", "scope", "gap", "infra"):
        if known in tokens:
            return known
    return tokens[0]


def collect(board_dir):
    tickets, broken = [], []
    for fn in sorted(os.listdir(board_dir)):
        if not is_ticket(fn):
            continue
        t = parse_ticket(os.path.join(board_dir, fn))
        (tickets if t else broken).append(t or fn)
    return tickets, broken


def table(rows):
    out = ["| Ticket | Task | Status |", "|--------|------|--------|"]
    for t in rows:
        out.append(f"| `{t['id']}` | {t['task']} | {t['status']} |")
    return out


def render(tickets):
    blocks = []
    done = [t for t in tickets if t["bucket"] == "done"]
    running = [t for t in tickets if t["bucket"] == "in_progress"]
    superseded = [t for t in tickets if t["bucket"] == "superseded"]
    openish = [t for t in tickets if t["bucket"] in ("todo", "blocked", "parked")]

    if done:
        blocks.append([f"## ✅ Done ({len(done)})"] + table(done))
    if running:
        blocks.append([f"## 🔵 In progress ({len(running)})"] + table(running))
    if openish:
        groups = {}
        for t in openish:
            key, heading = OPEN_GROUPS.get(t["cls"], OPEN_DEFAULT)
            groups.setdefault((key, heading), []).append(t)
        sec = [f"## 🔲 Open — TODO ({len(openish)})"]
        for (_, heading), rows in sorted(groups.items(), key=lambda kv: kv[0][0]):
            sec.append("")
            sec.append(f"### {heading} ({len(rows)})")
            sec.extend(table(rows))
        blocks.append(sec)
    if superseded:
        blocks.append([f"## ⛔ Superseded ({len(superseded)})"] + table(superseded))

    return "\n\n".join("\n".join(b) for b in blocks) + "\n"


def do_write(board_dir, body):
    idx = os.path.join(board_dir, "00-INDEX.md")
    if not os.path.isfile(idx):
        print(f"error: {idx} not found — create it with the AUTO markers first (see SKILL.md).",
              file=sys.stderr)
        return 2
    text = open(idx, encoding="utf-8").read()
    if START not in text or END not in text:
        print(f"error: {idx} is missing the AUTO markers:\n  {START}\n  {END}", file=sys.stderr)
        return 2
    pre, rest = text.split(START, 1)
    _, post = rest.split(END, 1)
    new = f"{pre}{START}\n{body}{END}{post}"
    open(idx, "w", encoding="utf-8").write(new)
    return 0


def do_check(board_dir, body):
    tickets, broken = collect(board_dir)
    rc = 0
    if broken:
        rc = 1
        for fn in broken:
            print(f"drift: {fn} has no parseable **Status:** line", file=sys.stderr)
    idx = os.path.join(board_dir, "00-INDEX.md")
    if os.path.isfile(idx):
        text = open(idx, encoding="utf-8").read()
        if START in text and END in text:
            cur = text.split(START, 1)[1].split(END, 1)[0]
            if cur.strip("\n") != ("\n" + body).strip("\n"):
                rc = 1
                print("drift: 00-INDEX AUTO region is stale — run --write", file=sys.stderr)
    if rc == 0:
        print("board in sync")
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(description="Roll up a task-board deliverable's index from its tickets.")
    ap.add_argument("board_dir", help="the task-board folder (holds the ticket .md files)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true", help="update the AUTO region in 00-INDEX.md")
    g.add_argument("--check", action="store_true", help="exit 1 if tickets are malformed or index drifted")
    args = ap.parse_args(argv)

    tickets, broken = collect(args.board_dir)
    body = render(tickets)

    if args.check:
        return do_check(args.board_dir, body)
    if broken:
        for fn in broken:
            print(f"warning: {fn} has no parseable **Status:** line — skipped", file=sys.stderr)
    if args.write:
        return do_write(args.board_dir, body)
    sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
