"""M7 — every view's --porcelain parses with stderr discarded, and the human form and the porcelain
form report the same (identity, state) set."""
import os, re, subprocess, sys
from fleet.cli import PORCELAIN_COLUMNS
ENV = dict(os.environ)
INSTP, TODO = ENV["INSTP"], ENV["TODO"]
VIEWS = {
    "board": ([], 0, 2),        # (args, identity column, state column) in porcelain
    "leases": ([], 0, 1),
    "roadmap": (["--instant", INSTP], 1, 2),
    "status": (["--id", TODO], None, None),
}

def run(verb, args, porcelain):
    cmd = [sys.executable, "-m", "fleet.cli", verb] + args + (["--porcelain"] if porcelain else [])
    done = subprocess.run(cmd, capture_output=True, text=True, env=ENV)
    return done.returncode, done.stdout, done.stderr

def human_cells(text):
    """The human form: a banner, then rows of columns separated by two or more spaces."""
    rows = []
    for line in text.splitlines()[1:]:
        if not line.strip():
            continue
        rows.append([c for c in re.split(r"\s{2,}", line.strip()) if c])
    return rows

bad = []
for verb, (args, ident_col, state_col) in VIEWS.items():
    ncols = len(PORCELAIN_COLUMNS[verb])
    rc, out, err = run(verb, args, True)
    print(f"--- {verb}: rc={rc} porcelain lines={len([l for l in out.splitlines() if l])} cols={ncols}")
    for line in out.splitlines():
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != ncols:
            bad.append(f"{verb}: porcelain line has {len(fields)} fields, declared {ncols}: {line!r}")
    if not [l for l in out.splitlines() if l]:
        bad.append(f"{verb}: porcelain produced no rows, so nothing was parsed")
    rc_h, out_h, err_h = run(verb, args, False)
    print(f"    human lines={len(out_h.splitlines())}")
    if verb == "status":
        pfields = dict(line.split("\t", 1) for line in out.splitlines() if line)
        p_pair = (pfields.get("identity"), pfields.get("state"))
        head = [c for c in re.split(r"\s{2,}", out_h.splitlines()[0].strip()) if c]
        h_pair = (head[0], head[1] if len(head) > 1 else None)
        print(f"    porcelain pair={p_pair} human pair={h_pair}")
        if p_pair != h_pair:
            bad.append(f"status: porcelain {p_pair} != human {h_pair}")
        continue
    p_pairs = {(l.split("\t")[ident_col], l.split("\t")[state_col]) for l in out.splitlines() if l}
    h_pairs = set()
    if verb == "board":
        # human columns: label, identity, state, slot, note
        for cells in human_cells(out_h):
            if len(cells) >= 3:
                h_pairs.add((cells[1], cells[2]))
    elif verb == "leases":
        for cells in human_cells(out_h):
            if len(cells) >= 2:
                h_pairs.add((cells[0], cells[1]))
    elif verb == "roadmap":
        for cells in human_cells(out_h):
            if len(cells) >= 3:
                h_pairs.add((cells[1], cells[2]))
    print(f"    porcelain set={sorted(p_pairs)}")
    print(f"    human set    ={sorted(h_pairs)}")
    if p_pairs != h_pairs:
        bad.append(f"{verb}: porcelain {sorted(p_pairs)} != human {sorted(h_pairs)}")
assert not bad, "\n".join(bad)
print("OK M7: board/leases/roadmap/status parse at their declared column counts with stderr discarded, "
      "and each view's human form reports the same (identity, state) set as its porcelain form")
