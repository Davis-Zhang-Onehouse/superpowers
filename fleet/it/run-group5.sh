#!/usr/bin/env bash
# Plan 6 integration sections §L (meta loop), §M (CLI surface), §N (real tmux) — group 5.
#
# Reports into RESULTS-group5.tsv (never RESULTS.tsv). Every section asserts the isolation contract on
# entry and on exit; §N gets its own FLEET_HOME and tmux prefix through `it_section`.
#
# Usage: run-group5.sh [L|M|N ...]     (default: L M N)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$HERE/lib.sh"

# --- group-5 reporting: our own file, never RESULTS.tsv -------------------------------------------
# `IT_RESULTS` wins when the caller names one, so a re-run can be sent to a scratch register without
# editing this file. Hard-coding the path made `IT_RESULTS=... run-group5.sh` silently write
# RESULTS-group5.tsv anyway — a runner that ignores the isolation knob it was given is the same class of
# defect as a bare `tmux`.
RESULTS="${IT_RESULTS:-$HERE/RESULTS-group5.tsv}"
[ -f "$RESULTS" ] || printf 'case\tverdict\tevidence\tnote\n' > "$RESULTS"

WANTED=("$@")
[ "${#WANTED[@]}" -eq 0 ] && WANTED=(L M N)

# This runner OWNS its case ids: its prior rows are dropped before it writes new ones, so a re-run
# REPLACES its verdicts instead of appending a second opinion. RESULTS-group5.tsv carried three rows per
# case from three runs, which makes `grep -c FAIL` a wrong answer and `zero NOT-RUN` inexpressible.
#
# Ownership is scoped to the sections ACTUALLY REQUESTED. Owning all of L/M/N unconditionally would make
# `run-group5.sh L` delete §M's and §N's rows and then not rewrite them — turning a partial re-run into
# silent NOT-RUN, which is the very state AC-3 forbids and worse than the duplicate rows it fixes.
own=''
for want in "${WANTED[@]}"; do
  case "$want" in
    L) own="$own|L[0-9]+|ISOLATION-L-(enter|leave)" ;;
    M) own="$own|M[0-9]+[a-z]?|M8-[a-z-]+|ISOLATION-M-(enter|leave)" ;;
    N) own="$own|N[0-9]+[a-z]?|ISOLATION-N-(enter|leave)" ;;
  esac
done
# The two run-level rows are rewritten by every invocation, so they are always owned.
IT_OWNED_CASES="${own#|}|SOURCE-STABLE|CLAUDE-COUNT"
it_own_cases "$IT_OWNED_CASES"
IT_FAILED=0

# Every section starts from a VIRGIN store. `it_section` only `mkdir -p`s, so three earlier runs had left
# §N with six leftover instants and a lease held by a record from 06:50 — and §N picks its subject with
# `ls "$FLEET_HOME/instants" | head -1`, which sorts `-nowned` before `-nprobe`. N6 therefore measured a
# leftover instant: `resume --slot ns1` reattached the old ns2 record (`claimed false`) instead of claiming
# ns1, so the lease it then asserts was `free` before the reap as well as after. Same shape in L8, where a
# store with memory from an earlier run reported `stale-source` instead of `no-prior-state`.
#
# A fixture that survives its own run does not test what it says, and it fails LATER than the change that
# broke it. The store is a fixture, not evidence: everything a section asserts, it creates.
it_fresh_fixture() {      # call immediately after it_section, before anything writes
  rm -rf "$FLEET_HOME" "$SLOTS"
  mkdir -p "$FLEET_HOME" "$SLOTS"
}

CLAUDE_BEFORE="$(pgrep -x claude | wc -l | tr -d ' ')"
CLAUDE_PIDS_BEFORE="$(it_claude_pids)"      # the set, for it_assert_no_new_claude (see the leave assertion)

# --- the exact implementation these results describe ----------------------------------------------
# The working tree is being edited by the base instant while these sections run, so the bytes under
# test are pinned into the evidence rather than described. A verdict whose source nobody can re-derive
# is not evidence.
# The file name carries this runner's own prefix: `bin/source-pin.sh <phase> <dir>` writes
# `<dir>/SOURCE-PIN-before.txt`, so the unprefixed name is now the shared control's, and two writers to
# one register is the defect this whole wave is about.
it_pin() {                # it_pin <tag>
  local out="$HERE/SOURCE-PIN-group5-$1.txt"
  {
    printf 'pinned at %s\n' "$(date -Is)"
    printf 'git HEAD: %s\n' "$(git -C "$INSTANT" rev-parse HEAD 2>/dev/null)"
    printf 'git status --porcelain:\n'; git -C "$INSTANT" status --porcelain 2>/dev/null
    printf 'sha256 of the package under test:\n'
    (cd "$INSTANT" && sha256sum src/fleet/*.py)
  } > "$out"
  printf '%s\n' "$out"
}

# --- helpers --------------------------------------------------------------------------------------

sq() { printf '%s' "$*" | tr '\n\t' '  ' | tr -s ' '; }   # one TSV cell, never two records

RC=0; OUT_FILE=""; ERR_FILE=""
it_run() {                # it_run <tag> <cmd...>  -> $RC, $OUT_FILE, $ERR_FILE
  local tag="$1"; shift
  OUT_FILE="$EV/$tag.stdout"; ERR_FILE="$EV/$tag.stderr"
  "$@" > "$OUT_FILE" 2> "$ERR_FILE"; RC=$?
  return 0
}

it_py() {                 # it_py <case> <script> [extra note]  -> PASS on exit 0
  local case="$1" script="$2"
  local log="$EV/$case.out"
  if python3 "$script" > "$log" 2>&1; then
    it_pass "$case" "$log" "$(grep -m1 '^OK' "$log" | cut -c1-300)"
  else
    it_fail "$case" "$log" "$(grep -m1 -E '^(FAIL|AssertionError|[A-Za-z.]*Error)' "$log" | cut -c1-300)"
  fi
}

# The harness's OWN tmux calls, all on the SECTION's private server via `it_tmux` (`-L itfleet-<SECTION>`).
#
# W-1: `session.default_probes()` now reads the socket from `FLEET_TMUX_SOCKET`, which `it_section` exports,
# so every `fleet`/`fleet.cli` subprocess a section spawns talks to that private server. A bare `tmux` here
# would leave the harness on the operator's LIVE server while the product under test is on the private one:
# `fleet resume --tmux itfleet-M-worker` would create the session where the harness cannot see it, and
# `it_cap` would capture from a server the product never touched. Worse, the CREATE would land on the live
# server — which is the exact defect W-1 exists to fix (§M's `itfleet-M-worker` once did, and §E's
# isolation assertion correctly failed on it).
#
# Targets keep their EXACT markers (`FI-23`): `=name` for a target-SESSION, `=name:` for a target-PANE.
# `capture-pane -t =name` fails with *can't find pane* even for a session that exists, because a pane
# target is parsed as `session:window.pane` — and that failure is SILENT, so it passes the prefix cases
# vacuously with two empty screens comparing equal. `new-session -s` is neither: it NAMES the session
# being created, so a marker there would become part of the name.
it_tmux_new() {           # it_tmux_new <session> <command>   (always the itfleet- prefix)
  case "$1" in
    itfleet-*) ;;
    *) printf 'REFUSED: session %s does not carry the itfleet- prefix\n' "$1" >&2; return 1;;
  esac
  it_tmux new-session -d -s "$1" -x 120 -y 33 "$2"
}
it_tmux_kill() { it_tmux kill-session -t "=$1" 2>/dev/null; true; }
it_cap()  { it_tmux capture-pane -p -t "=$1:"; }     # `=` and `:` -> exact session, no prefix match
it_send() { it_tmux send-keys -t "=$1:" "${@:2}"; }

# Set per section (`$EV/py`) so a section's generated scripts sit with the evidence they produced, rather
# than in one shared `py/` two concurrent sections would overwrite for each other.
PY_DIR=""

# =================================================================================================
# §L — meta loop
# =================================================================================================
section_L() {
  it_section L || return 1
  it_fresh_fixture
  export EV SLOTS DUMMY INSTANT SECTION
  PY_DIR="$EV/py"
  mkdir -p "$EV/reg" "$SLOTS" "$PY_DIR"

  # ---- L1 ---------------------------------------------------------------------------------------
  cat > "$PY_DIR/l1.py" <<'PY'
"""L1 — register the dummy ISSUES.md; prime reports its COUNT and reports no issues."""
import os
from pathlib import Path
from fleet.harvest import Harvest, exit_code
EV, DUMMY = Path(os.environ["EV"]), Path(os.environ["DUMMY"])
h = Harvest(EV / "home-l1")
src = h.register(str(DUMMY), str(DUMMY / "ISSUES.md"))
count = h.prime(src)
assert isinstance(count, int) and not isinstance(count, bool), f"prime returned {type(count)}"
found = h.ids_found(src)
print("prime count:", count, "ids_found:", found)
assert count == 3, f"prime recorded {count}, expected the register's 3 ids"
assert found == 3, f"ids_found={found}"
rows = h.run(src)
for r in rows:
    print("row:", r.kind, r.severity, r.ids_found, r.new_count, r.detail[:120])
kinds = [r.kind for r in rows]
assert kinds == ["source"], f"a primed source reported {kinds}; expected the source row alone"
assert rows[0].new_count == 0, f"new_count={rows[0].new_count} after prime"
assert rows[0].ids_found == 3
assert "produced nothing" in rows[0].detail
assert exit_code(rows) == 0, "a primed clean source is not clean"
print("OK L1: prime reported the count (3) as a number and reported no issue ids; the next tick is 0 new")
PY
  it_py L1 "$PY_DIR/l1.py"

  # ---- L2 / L3 / L4 -----------------------------------------------------------------------------
  cat > "$PY_DIR/l234.py" <<'PY'
"""L2 append two ⇒ both named · L3 insert BEFORE the last heading ⇒ detected · L4 renumber ⇒ zero new."""
import os, shutil, sys
from pathlib import Path
from fleet.harvest import Harvest
EV, DUMMY = Path(os.environ["EV"]), Path(os.environ["DUMMY"])
case = sys.argv[1]
base = EV / "reg" / case
base.mkdir(parents=True, exist_ok=True)
reg = base / "ISSUES.md"
shutil.copyfile(DUMMY / "ISSUES.md", reg)
h = Harvest(EV / f"home-{case}")
src = h.register(str(base), str(reg))
print("primed:", h.prime(src))

if case == "l2":
    reg.write_text(reg.read_text() + "## RI-40 — an appended issue\n## RI-41 — a second appended issue\n")
    want = ["RI-40", "RI-41"]
elif case == "l3":
    lines = reg.read_text().splitlines(keepends=True)
    last = max(i for i, line in enumerate(lines) if line.startswith("## "))
    lines.insert(last, "## RI-50 — inserted BEFORE the last heading (OBS-11's shape)\n")
    reg.write_text("".join(lines))
    print("inserted at line", last + 1, "of", len(lines), "; last heading is now line",
          max(i for i, l in enumerate(reg.read_text().splitlines(), start=1) if l.startswith("## ")))
    want = ["RI-50"]
else:  # l4 — renumber the whole register's PREFIX
    reg.write_text(reg.read_text().replace("## RI-", "## QQ-"))
    want = []

new = h.new_issues(src)
got = [i.id for i in new]
print("new ids:", got, "expected:", want)
assert got == want, f"{case}: new={got}, expected {want}"
if case == "l4":
    print("register now:", [l for l in reg.read_text().splitlines() if l.startswith("## ")])
print(f"OK {case.upper()}: new={got or 'none'} (expected {want or 'zero new'})")
PY
  ( python3 "$PY_DIR/l234.py" l2 ) > "$EV/L2.out" 2>&1 \
    && it_pass L2 "$EV/L2.out" "$(grep -m1 '^OK' "$EV/L2.out")" \
    || it_fail L2 "$EV/L2.out" "$(tail -2 "$EV/L2.out" | tr '\n' ' ')"
  ( python3 "$PY_DIR/l234.py" l3 ) > "$EV/L3.out" 2>&1 \
    && it_pass L3 "$EV/L3.out" "$(grep -m1 '^OK' "$EV/L3.out")" \
    || it_fail L3 "$EV/L3.out" "$(tail -2 "$EV/L3.out" | tr '\n' ' ')"
  ( python3 "$PY_DIR/l234.py" l4 ) > "$EV/L4.out" 2>&1 \
    && it_pass L4 "$EV/L4.out" "$(grep -m1 '^OK' "$EV/L4.out")" \
    || it_fail L4 "$EV/L4.out" "$(tail -2 "$EV/L4.out" | tr '\n' ' ')"

  # ---- L5 ---------------------------------------------------------------------------------------
  cat > "$PY_DIR/l5.py" <<'PY'
"""L5 — three halves, in this order:
  (a) a register using ### headings and an id RI-9a ⇒ ids_found NON-ZERO (the extractor really parses it)
  (b) a NON-EMPTY register yielding zero ids ⇒ ERROR (VacuousExtraction / violation row / exit 1)
  (c) an EMPTY register ⇒ clean, with an info row
Without (a), (b) would only be testing a broken regex."""
import os
from pathlib import Path
from fleet.harvest import Harvest, VacuousExtraction, extract, exit_code, EMPTY_REGISTER, VACUOUS
EV = Path(os.environ["EV"])

# (a) --------------------------------------------------------------------------------------------
a = EV / "reg" / "l5a"; a.mkdir(parents=True, exist_ok=True)
(a / "ISSUES.md").write_text(
    "# Register with third-level ids\n"
    "### RI-9a — an id with a letter suffix\n"
    "#### Status\n"
    "OPEN\n"
    "### W2-14 — a digit inside the prefix\n"
    "### RCF-B-8 — a middle segment\n"
    "### A third-level heading that is not an id\n")
h = Harvest(EV / "home-l5a")
src_a = h.register(str(a), str(a / "ISSUES.md"))
ids = [i.id for i in extract((a / "ISSUES.md").read_text())]
found = h.ids_found(src_a)
print("(a) ids parsed:", ids, "ids_found:", found)
assert found != 0, "ids_found is ZERO on a ### register — the extractor is blind and (b) would be vacuous"
assert "RI-9a" in ids, f"RI-9a not parsed: {ids}"
assert found == 3, f"ids_found={found}, expected 3 (RI-9a, W2-14, RCF-B-8)"

# (b) --------------------------------------------------------------------------------------------
b = EV / "reg" / "l5b"; b.mkdir(parents=True, exist_ok=True)
(b / "ISSUES.md").write_text(
    "This register has content and no ids.\n\n"
    "- a bullet about a problem\n"
    "# Notes\n"
    "## Something that is not an id\n"
    "Some more prose.\n")
hb = Harvest(EV / "home-l5b")
src_b = hb.register(str(b), str(b / "ISSUES.md"))
raised = None
try:
    hb.ids_found(src_b)
except VacuousExtraction as exc:
    raised = exc
print("(b) VacuousExtraction:", type(raised).__name__ if raised else None)
assert raised is not None, "a non-empty register yielding zero ids did NOT raise"
assert raised.exit_code == 1, f"VacuousExtraction.exit_code={raised.exit_code}"
rows_b = hb.run(src_b)
print("(b) rows:", [(r.kind, r.severity) for r in rows_b])
assert [r.kind for r in rows_b] == [VACUOUS], f"expected a vacuous-extraction row, got {rows_b}"
assert rows_b[0].severity == "violation"
assert exit_code(rows_b) == 1, "a vacuous extraction did not report non-zero"

# (c) --------------------------------------------------------------------------------------------
c = EV / "reg" / "l5c"; c.mkdir(parents=True, exist_ok=True)
(c / "ISSUES.md").write_text("")
hc = Harvest(EV / "home-l5c")
src_c = hc.register(str(c), str(c / "ISSUES.md"))
print("(c) primed:", hc.prime(src_c))
rows_c = hc.run(src_c)
print("(c) rows:", [(r.kind, r.severity, r.ids_found) for r in rows_c])
kinds = [r.kind for r in rows_c]
assert EMPTY_REGISTER in kinds, f"an empty register reported no info row: {kinds}"
assert all(r.severity == "info" for r in rows_c), f"an empty register went RED: {rows_c}"
assert exit_code(rows_c) == 0
print("OK L5: (a) ids_found=3 incl RI-9a from ### headings · (b) non-empty/zero-ids raises "
      "VacuousExtraction and reports exit 1 · (c) empty register is clean with an empty-register info row")
PY
  it_py L5 "$PY_DIR/l5.py"

  # ---- L6 ---------------------------------------------------------------------------------------
  cat > "$PY_DIR/l6.py" <<'PY'
"""L6 — a registered source that produced NOTHING is reported as such, not omitted."""
import os
from pathlib import Path
from fleet.harvest import Harvest, SOURCE
EV, DUMMY = Path(os.environ["EV"]), Path(os.environ["DUMMY"])
h = Harvest(EV / "home-l6")
quiet = EV / "reg" / "l6quiet"; quiet.mkdir(parents=True, exist_ok=True)
(quiet / "ISSUES.md").write_text("# quiet register\n## RI-1 — the only issue, already known\n")
s1 = h.register(str(DUMMY), str(DUMMY / "ISSUES.md"))
s2 = h.register(str(quiet), str(quiet / "ISSUES.md"))
h.prime(s1); h.prime(s2)                      # both now have memory: both will produce nothing
rows = h.report(live_work=False)
for r in rows:
    print("row:", r.kind, r.subject, r.severity, "|", r.detail[:110])
source_rows = [r for r in rows if r.kind == SOURCE]
assert len(source_rows) == 2, f"{len(source_rows)} source row(s) for 2 registered sources — one was omitted"
for r in source_rows:
    assert r.new_count == 0
    assert "produced nothing" in r.detail, f"a silent source did not say so: {r.detail}"
pops = [r for r in rows if r.kind == "population"]
assert len(pops) == 1 and "2 watched source(s)" in pops[0].detail, pops
print("OK L6: both silent sources are rows that say 'produced nothing'; the population row counts 2")
PY
  it_py L6 "$PY_DIR/l6.py"

  # ---- L7 -- every verb prints the stale-cadence line to stderr; stdout stays parseable ----------
  L7H="$FLEET_HOME"
  fleet init --home "$L7H" --name l7probe > "$EV/L7-setup-init.out" 2>&1
  INST="$(ls "$L7H/instants" | head -1)"
  INSTP="$L7H/instants/$INST"
  export L7H INSTP
  # a stale watched source: registered in 2020, never run
  cat > "$PY_DIR/l7setup.py" <<'PY'
import os
from pathlib import Path
from fleet.harvest import Harvest
from fleet.roadmap import Milestone, Roadmap
home, inst = Path(os.environ["L7H"]), Path(os.environ["INSTP"])
stale_base = Path(os.environ["EV"]) / "reg" / "l7stale"
stale_base.mkdir(parents=True, exist_ok=True)
(stale_base / "ISSUES.md").write_text("# stale register\n## SS-1 — one issue nobody has harvested\n")
src = Harvest(home, now=lambda: "2020-01-01T00:00:00Z").register(str(stale_base),
                                                                str(stale_base / "ISSUES.md"))
print("stale source:", src.base, src.registered_at, src.last_run)
road = Roadmap(inst)
road.add(Milestone(id="M1", title="the probe milestone", status="ready", deps=[], evidence=[]))
print("milestones:", [m.id for m in road.milestones()])
PY
  python3 "$PY_DIR/l7setup.py" > "$EV/L7-setup.out" 2>&1
  STALE_BASE="$EV/reg/l7stale"
  mkdir -p "$SLOTS/s1"
  fleet enroll --home "$L7H" --slot "$SLOTS/s1" >> "$EV/L7-setup.out" 2>&1
  fleet resume --home "$L7H" --instant "$INSTP" --slot s1 --tmux "itfleet-L-none" \
        >> "$EV/L7-setup.out" 2>&1
  TODO="$(python3 - <<'PY'
import json, os
from pathlib import Path
recs = sorted((Path(os.environ["L7H"]) / "records").glob("*.json"))
print(json.loads(recs[0].read_text())["todo_id"] if recs else "")
PY
)"
  fleet propose --home "$L7H" --instant "$INSTP" --milestone M1 --status done \
        --evidence "$EV/L7-setup.out" >> "$EV/L7-setup.out" 2>&1
  mkdir -p "$EV/profile"
  printf '{"kind": "worker"}\n' > "$EV/profile/profile.json"
  printf 'A charter for {{TITLE}} at {{PATH}}.\n' > "$EV/profile/charter.md"
  printf 'seed for {{INSTANT}}\n' > "$EV/profile/seed.txt"
  export TODO STALE_BASE

  verb_args() {   # the valid argv for one verb; mutating verbs run --dry-run so L7 changes nothing
    case "$1" in
      init)      echo "--name l7v --dry-run" ;;
      dispatch)  echo "--profile $EV/profile --title l7t --dry-run" ;;
      resume)    echo "--instant $INSTP --dry-run" ;;
      declare)   echo "--instant $INSTP --phase awaiting-ci --dry-run" ;;
      park)      echo "--instant $INSTP --question l7question --dry-run" ;;
      unpark)    echo "--instant $INSTP --dry-run" ;;
      propose)   echo "--instant $INSTP --milestone M1 --status done --evidence e1 --dry-run" ;;
      apply)     echo "--instant $INSTP --milestone M1 --dry-run" ;;
      review)    echo "--instant $INSTP --dry-run" ;;
      complete)  echo "--instant $INSTP --dry-run" ;;
      abort)     echo "--instant $INSTP --reason l7reason --dry-run" ;;
      close)     echo "--id $TODO --dry-run" ;;
      harvest)   echo "--dry-run" ;;
      enroll)    echo "--slot $SLOTS/s1 --dry-run" ;;
      unenroll)  echo "--slot s1 --dry-run" ;;
      reap)      echo "--base $INSTP --dry-run" ;;
      set-golden) echo "--path $DUMMY/alpha --dry-run" ;;
      board|leases|selftest|reconcile|compaction-status) echo "" ;;
      status)    echo "--id $TODO" ;;
      roadmap|lint|verify|brief) echo "--instant $INSTP" ;;
      base-check) echo "--id $TODO" ;;
      milestone) echo "--instant $INSTP --id l7m --title l7milestone --dry-run" ;;
      pane-guard) echo "--pane itfleet-L-absent-zzz" ;;
      *) echo "UNMAPPED" ;;
    esac
  }

  VERB_LIST="$(python3 -c 'from fleet.cli import VERBS; print(" ".join(sorted(VERBS)))')"
  COLS_MAP="$(python3 -c 'from fleet.cli import PORCELAIN_COLUMNS as P; print("\n".join(f"{k} {len(v)}" for k,v in P.items()))')"
  L7LOG="$EV/L7-per-verb.txt"; : > "$L7LOG"
  l7_bad=0; l7_nostdout=0; l7_verbs=0; l7_leak=0
  for v in $VERB_LIST; do
    args="$(verb_args "$v")"
    if [ "$args" = "UNMAPPED" ]; then
      printf '%s UNMAPPED\n' "$v" >> "$L7LOG"; l7_bad=$((l7_bad+1)); continue
    fi
    l7_verbs=$((l7_verbs+1))
    # shellcheck disable=SC2086
    timeout 120 python3 -m fleet.cli "$v" $args --home "$L7H" --porcelain \
        > "$EV/L7-$v.stdout" 2> "$EV/L7-$v.stderr"; rc=$?
    cad=$(grep -c '^cadence:' "$EV/L7-$v.stderr")
    named=$(grep -c 'l7stale' "$EV/L7-$v.stderr")
    leak=$(grep -c 'cadence:' "$EV/L7-$v.stdout")
    ncols=$(printf '%s\n' "$COLS_MAP" | awk -v v="$v" '$1==v{print $2}')
    lines=$(grep -c . "$EV/L7-$v.stdout")
    badlines=$(awk -F'\t' -v n="$ncols" 'NF>0 && NF!=n {c++} END {print c+0}' "$EV/L7-$v.stdout")
    printf '%s rc=%s cadence=%s names_stale=%s stdout_lines=%s cols=%s malformed=%s leak=%s\n' \
           "$v" "$rc" "$cad" "$named" "$lines" "$ncols" "$badlines" "$leak" >> "$L7LOG"
    [ "$cad" -ge 1 ] || l7_bad=$((l7_bad+1))
    [ "$named" -ge 1 ] || l7_bad=$((l7_bad+1))
    [ "$badlines" = "0" ] || l7_bad=$((l7_bad+1))
    [ "$leak" = "0" ] || l7_leak=$((l7_leak+1))
    [ "$lines" -gt 0 ] || l7_nostdout=$((l7_nostdout+1))
  done
  note="verbs=$l7_verbs, failures=$l7_bad, cadence-on-stdout=$l7_leak, empty-stdout=$l7_nostdout"
  if [ "$l7_bad" = "0" ] && [ "$l7_leak" = "0" ]; then
    it_pass L7 "$L7LOG" "every verb printed a stale-cadence line to stderr naming the stale source; \
every porcelain stdout parsed at its declared column count; $note"
  else
    it_fail L7 "$L7LOG" "$note :: $(grep -v 'cadence=1 names_stale=1' "$L7LOG" | grep -v 'malformed=0 leak=0' | head -3 | tr '\n' ' ')"
  fi

  # ---- L8 ---------------------------------------------------------------------------------------
  L8H="$EV/home-l8"
  # L8's whole claim is about the FIRST harvest of a source with NO memory, so the store must have none.
  # This home lives under $EV rather than $FLEET_HOME, so `it_fresh_fixture` does not reach it: a previous
  # run left `seen` state and a `last_run` 8h old, and the first tick then reported `stale-source` instead
  # of `no-prior-state` — still exit 1, so the case would have passed on the exit code alone.
  rm -rf "$L8H"
  mkdir -p "$L8H"
  cat > "$PY_DIR/l8setup.py" <<'PY'
import os
from pathlib import Path
from fleet.harvest import Harvest
EV = Path(os.environ["EV"])
base = EV / "reg" / "l8"; base.mkdir(parents=True, exist_ok=True)
(base / "ISSUES.md").write_text("# l8\n## L8-1 — first\n## L8-2 — second\n")
src = Harvest(Path(os.environ["L8H"])).register(str(base), str(base / "ISSUES.md"))
print("registered", src.base, "seen dir exists:",
      (Path(os.environ["L8H"]) / "harvest" / "seen").is_dir())
PY
  L8H="$L8H" python3 "$PY_DIR/l8setup.py" > "$EV/L8-setup.out" 2>&1
  it_run L8-first fleet harvest --home "$L8H" --porcelain; rc1=$RC
  cp "$OUT_FILE" "$EV/L8-first.tsv"
  it_run L8-second fleet harvest --home "$L8H" --porcelain; rc2=$RC
  cp "$OUT_FILE" "$EV/L8-second.tsv"
  first_nomem=$(grep -c 'no-prior-state' "$EV/L8-first.tsv")
  second_nomem=$(grep -c 'no-prior-state' "$EV/L8-second.tsv")
  if [ "$rc1" != "0" ] && [ "$first_nomem" -ge 1 ] && [ "$rc2" = "0" ] && [ "$second_nomem" = "0" ]; then
    it_pass L8 "$EV/L8-first.tsv" "first run: exit $rc1 with a no-prior-state violation; second run: exit $rc2, clean"
  else
    it_fail L8 "$EV/L8-first.tsv" "first rc=$rc1 nomem=$first_nomem; second rc=$rc2 nomem=$second_nomem"
  fi

  # ---- L9 ---------------------------------------------------------------------------------------
  cat > "$PY_DIR/l9.py" <<'PY'
"""L9 — the same advice in TWO documents ⇒ repetitions flags it at 2, with a citation per instance."""
import os
from pathlib import Path
from fleet.harvest import Harvest, Repetition
from fleet.errors import BadInput
EV = Path(os.environ["EV"])
h = Harvest(EV / "home-l9")
advice = "always re-derive the state from the join instead of trusting the board"
doc_a = (EV / "reg" / "l9-A.md"); doc_a.parent.mkdir(parents=True, exist_ok=True)
doc_b = (EV / "reg" / "l9-B.md")
doc_a.write_text(f"# DECISIONS\n\n## RI-5 {advice}\nsomething else entirely on this line\n")
doc_b.write_text(f"# HANDOFF\n\n- OI-9 {advice}\na different sentence that repeats nowhere\n")
corpus = {str(doc_a): doc_a.read_text(), str(doc_b): doc_b.read_text()}
reps = h.repetitions(corpus)
for r in reps:
    print("repetition:", r.count, "|", r.subject, "|", r.where)
hits = [r for r in reps if r.subject == advice]
assert len(hits) == 1, f"the repeated advice was not flagged once: {[r.subject for r in reps]}"
rep = hits[0]
assert rep.count == 2, f"count={rep.count}, expected 2 — the threshold IS two"
assert len(rep.where) == 2, f"citations={rep.where}"
assert {c.rsplit(':', 1)[0] for c in rep.where} == set(corpus), f"one citation per document: {rep.where}"
for citation in rep.where:
    path, _, line = citation.rpartition(":")
    text = Path(path).read_text().splitlines()[int(line) - 1]
    print("cited", citation, "->", text)
    assert advice in text, f"citation {citation} does not point at the advice"
try:
    Repetition(subject="x", count=2, where=[])
except BadInput as exc:
    print("uncited repetition refused:", str(exc)[:80])
else:
    raise AssertionError("a repetition with no citation was constructible")
try:
    h.repetitions(corpus, min_count=1)
except BadInput as exc:
    print("min_count=1 refused:", str(exc)[:80])
else:
    raise AssertionError("min_count=1 was accepted; a 'repetition' of one is an observation")
print("OK L9: the shared advice is flagged at count 2 with one verifiable citation per instance "
      "(the id prefix RI-5 vs OI-9 and the bullet/heading markers are normalised away)")
PY
  it_py L9 "$PY_DIR/l9.py"

  it_assert_isolation "L-leave"
}

# =================================================================================================
# §M — CLI surface
# =================================================================================================
section_M() {
  it_section M || return 1
  it_fresh_fixture
  export EV SLOTS DUMMY INSTANT SECTION
  PY_DIR="$EV/py"
  mkdir -p "$SLOTS/ms1" "$EV/profile" "$PY_DIR"
  printf '{"kind": "worker"}\n' > "$EV/profile/profile.json"
  printf 'A charter for {{TITLE}} at {{PATH}}.\n' > "$EV/profile/charter.md"
  printf 'seed for {{INSTANT}}\n' > "$EV/profile/seed.txt"

  fleet init --name mprobe > "$EV/M-setup.out" 2>&1
  INST="$(ls "$FLEET_HOME/instants" | head -1)"
  INSTP="$FLEET_HOME/instants/$INST"
  fleet enroll --slot "$SLOTS/ms1" >> "$EV/M-setup.out" 2>&1
  fleet set-golden --path "$DUMMY/alpha" >> "$EV/M-setup.out" 2>&1
  # a live pane the record can point at, so `board`/`status` have a slot-holding subject
  it_tmux_new "itfleet-M-worker" "sh -c 'i=1; while [ \$i -le 200 ]; do echo filler line \$i; i=\$((i+1)); done; echo \"? for shortcuts\"; printf \"\\342\\235\\257\\302\\240\"; sleep 1200'"
  sleep 1
  fleet resume --instant "$INSTP" --slot ms1 --tmux "itfleet-M-worker" >> "$EV/M-setup.out" 2>&1
  TODO="$(python3 - <<'PY'
import json, os
from pathlib import Path
recs = sorted((Path(os.environ["FLEET_HOME"]) / "records").glob("*.json"))
print(json.loads(recs[0].read_text())["todo_id"] if recs else "")
PY
)"
  cat > "$PY_DIR/msetup.py" <<'PY'
import os
from pathlib import Path
from fleet.roadmap import Milestone, Roadmap
road = Roadmap(Path(os.environ["INSTP"]))
if not road.milestones():
    road.add(Milestone(id="M1", title="the probe milestone", status="ready", deps=[], evidence=[]))
print("milestones:", [m.id for m in road.milestones()])
PY
  python3 "$PY_DIR/msetup.py" >> "$EV/M-setup.out" 2>&1
  fleet propose --instant "$INSTP" --milestone M1 --status done --evidence "$EV/M-setup.out" \
        >> "$EV/M-setup.out" 2>&1
  export INSTP TODO

  m_args() {
    case "$1" in
      init)      echo "--name mv1 --dry-run" ;;
      dispatch)  echo "--profile $EV/profile --title mt --dry-run" ;;
      resume)    echo "--instant $INSTP --dry-run" ;;
      declare)   echo "--instant $INSTP --phase awaiting-ci --dry-run" ;;
      park)      echo "--instant $INSTP --question mq --dry-run" ;;
      unpark)    echo "--instant $INSTP --dry-run" ;;
      propose)   echo "--instant $INSTP --milestone M1 --status done --evidence e1 --dry-run" ;;
      apply)     echo "--instant $INSTP --milestone M1 --dry-run" ;;
      review)    echo "--instant $INSTP --dry-run" ;;
      complete)  echo "--instant $INSTP --dry-run" ;;
      abort)     echo "--instant $INSTP --reason mreason --dry-run" ;;
      close)     echo "--id $TODO --dry-run" ;;
      harvest)   echo "--dry-run" ;;
      enroll)    echo "--slot $SLOTS/ms1 --dry-run" ;;
      unenroll)  echo "--slot ms1 --dry-run" ;;
      reap)      echo "--base $INSTP --dry-run" ;;
      set-golden) echo "--path $DUMMY/alpha --dry-run" ;;
      board|leases|selftest|reconcile|compaction-status) echo "" ;;
      status)    echo "--id $TODO" ;;
      roadmap|lint|verify|brief) echo "--instant $INSTP" ;;
      base-check) echo "--id $TODO" ;;
      milestone) echo "--instant $INSTP --id m5m --title m5milestone --dry-run" ;;
      pane-guard) echo "--pane itfleet-M-absent-zzz" ;;
      *) echo "UNMAPPED" ;;
    esac
  }

  VERBS_ALL="$(python3 -c 'from fleet.cli import VERBS; print(" ".join(sorted(VERBS)))')"
  NVERBS="$(printf '%s\n' $VERBS_ALL | wc -l | tr -d ' ')"

  # ---- M1 ---------------------------------------------------------------------------------------
  M1LOG="$EV/M1-per-verb.txt"; : > "$M1LOG"
  m1_bad=0
  for v in $VERBS_ALL; do
    args="$(m_args "$v")"
    allowed="$(python3 -c "from fleet.cli import registered_codes; print(' '.join(str(c) for c in sorted(registered_codes('$v'))))")"
    # shellcheck disable=SC2086
    timeout 120 python3 -m fleet.cli "$v" $args > "$EV/M1-$v.stdout" 2> "$EV/M1-$v.stderr"; rc=$?
    ok=no
    for c in $allowed; do [ "$rc" = "$c" ] && ok=yes; done
    printf '%-20s rc=%-4s allowed=[%s] %s\n' "$v" "$rc" "$allowed" "$ok" >> "$M1LOG"
    [ "$ok" = yes ] || m1_bad=$((m1_bad+1))
  done
  if [ "$m1_bad" = 0 ]; then
    it_pass M1 "$M1LOG" "all $NVERBS verbs ran and every exit code came from the registry (the plan says 20; FD-12 added seven, so the population is $NVERBS)"
  else
    it_fail M1 "$M1LOG" "$m1_bad verb(s) returned an unregistered code: $(grep -c ' no$' "$M1LOG")"
  fi

  # ---- M2 / M6 ----------------------------------------------------------------------------------
  it_run M2 python3 -m fleet.cli; m2rc=$RC
  missing=""
  for v in $VERBS_ALL; do
    grep -qF -- "$v" "$EV/M2.stdout" "$EV/M2.stderr" || missing="$missing $v"
  done
  if [ -z "$missing" ]; then
    it_pass M2 "$EV/M2.stderr" "no-args usage lists all $NVERBS verbs (exit $m2rc, on stderr — stdout stays data)"
  else
    it_fail M2 "$EV/M2.stderr" "usage omits:$missing"
  fi

  it_run M6 python3 -m fleet.cli notaverb --porcelain; m6rc=$RC
  missing=""
  for v in $VERBS_ALL; do grep -qF -- "$v" "$EV/M6.stderr" || missing="$missing $v"; done
  if [ "$m6rc" = 2 ] && [ -z "$missing" ] && grep -q "is not a fleet verb" "$EV/M6.stderr"; then
    it_pass M6 "$EV/M6.stderr" "unknown verb ⇒ exit 2 and the whole map ($NVERBS verbs) is printed"
  else
    it_fail M6 "$EV/M6.stderr" "rc=$m6rc missing:$missing"
  fi

  # ---- M3 ---------------------------------------------------------------------------------------
  cat > "$PY_DIR/m3.py" <<'PY'
"""M3 — every declared long flag appears in that verb's usage (usage is DERIVED from VERBS)."""
from fleet.cli import VERBS, usage
bad = []
for name, spec in sorted(VERBS.items()):
    text = usage(name)
    for flag in spec.flags:
        if flag.name not in text:
            bad.append(f"{name}: {flag.name} missing from usage")
        if flag.takes_value and f"{flag.name} <value>" not in text:
            bad.append(f"{name}: {flag.name} documented without its value")
        if flag.required and "(required)" not in text:
            bad.append(f"{name}: {flag.name} is required and usage says nothing")
    print(f"{name}: {len(spec.flags)} flag(s) all present")
assert not bad, "\n".join(bad)
print(f"OK M3: every declared flag of all {len(VERBS)} verbs appears in its own usage, "
      "with its value form and required marker")
PY
  it_py M3 "$PY_DIR/m3.py"

  # ---- M4 ---------------------------------------------------------------------------------------
  M4LOG="$EV/M4-per-verb.txt"; : > "$M4LOG"
  m4_bad=0
  for v in $VERBS_ALL; do
    timeout 10 python3 -m fleet.cli "$v" --not-a-declared-flag > /dev/null 2> "$EV/M4-$v.stderr"; rc=$?
    named=$(grep -c 'not-a-declared-flag' "$EV/M4-$v.stderr")
    printf '%-20s rc=%s names_flag=%s\n' "$v" "$rc" "$named" >> "$M4LOG"
    { [ "$rc" = 2 ] && [ "$named" -ge 1 ]; } || m4_bad=$((m4_bad+1))
  done
  [ "$m4_bad" = 0 ] \
    && it_pass M4 "$M4LOG" "an undeclared flag ⇒ exit 2 naming the token, for all $NVERBS verbs" \
    || it_fail M4 "$M4LOG" "$m4_bad verb(s) accepted or mis-reported an undeclared flag"

  # ---- M5 — the generated last-with-no-value matrix ----------------------------------------------
  python3 - > "$EV/M5-matrix.txt" <<'PY'
from fleet.cli import VERBS
for name, spec in sorted(VERBS.items()):
    for flag in spec.flags:
        print(name, flag.name, "value" if flag.takes_value else "switch")
PY
  M5LOG="$EV/M5-per-flag.txt"; : > "$M5LOG"
  m5_bad=0; m5_hang=0; m5_value=0; m5_switch=0; m5_slow=""
  while read -r v f kind; do
    if [ "$kind" = value ]; then
      m5_value=$((m5_value+1))
      # shape (a): the flag alone, last, with no value
      timeout 5 python3 -m fleet.cli "$v" "$f" > /dev/null 2> "$EV/M5-a.stderr"; rca=$?
      diaga=$(grep -c 'needs a value' "$EV/M5-a.stderr")
      # shape (b): a full valid argv with the flag appended last
      args="$(m_args "$v")"
      # shellcheck disable=SC2086
      if [ "$args" = "UNMAPPED" ]; then
        printf '%-20s %-18s UNMAPPED — add it to m_args\n' "$v" "$f" >> "$M5LOG"
        m5_bad=$((m5_bad+1)); continue
      fi
      timeout 5 python3 -m fleet.cli "$v" $args "$f" > /dev/null 2> "$EV/M5-b.stderr"; rcb=$?
      diagb=$(grep -c 'needs a value' "$EV/M5-b.stderr")
      printf '%-20s %-18s value  alone:rc=%-4s diag=%s  appended:rc=%-4s diag=%s\n' \
             "$v" "$f" "$rca" "$diaga" "$rcb" "$diagb" >> "$M5LOG"
      { [ "$rca" = 2 ] && [ "$diaga" -ge 1 ] && [ "$rcb" = 2 ] && [ "$diagb" -ge 1 ]; } || m5_bad=$((m5_bad+1))
      { [ "$rca" = 124 ] || [ "$rcb" = 124 ]; } && m5_hang=$((m5_hang+1))
    else
      m5_switch=$((m5_switch+1))
      args="$(m_args "$v")"
      if [ "$args" = "UNMAPPED" ]; then
        printf '%-20s %-18s UNMAPPED — add it to m_args\n' "$v" "$f" >> "$M5LOG"
        m5_bad=$((m5_bad+1)); continue
      fi
      # shellcheck disable=SC2086
      timeout 5 python3 -m fleet.cli "$v" $args "$f" > /dev/null 2>&1; rcs=$?
      extra=""
      if [ "$rcs" = 124 ]; then
        # not a hang until it fails to terminate with a generous wall too
        # shellcheck disable=SC2086
        timeout 120 python3 -m fleet.cli "$v" $args "$f" > /dev/null 2>&1; rc2=$?
        extra="retry120:rc=$rc2"
        [ "$rc2" = 124 ] && m5_hang=$((m5_hang+1)) || m5_slow="$m5_slow $v$f"
      fi
      printf '%-20s %-18s switch appended:rc=%-4s %s\n' "$v" "$f" "$rcs" "$extra" >> "$M5LOG"
    fi
  done < "$EV/M5-matrix.txt"
  if [ "$m5_bad" = 0 ] && [ "$m5_hang" = 0 ]; then
    it_pass M5 "$M5LOG" "every value-taking flag of every verb ($m5_value flag/verb pairs × 2 shapes) exited 2 with the 'needs a value' diagnostic inside timeout 5; NO flag hung ($m5_switch switch flags also checked for hang-freedom;${m5_slow:- none} exceeded 5s)"
  else
    it_fail M5 "$M5LOG" "value-flag failures=$m5_bad, hangs=$m5_hang, slow=${m5_slow:-none}"
  fi

  # ---- M7 ---------------------------------------------------------------------------------------
  cat > "$PY_DIR/m7.py" <<'PY'
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
PY
  it_py M7 "$PY_DIR/m7.py"

  # ---- M8 — zero delta per read-only verb --------------------------------------------------------
  RO_VERBS="$(python3 -c 'from fleet.cli import VERBS; print(" ".join(sorted(n for n,s in VERBS.items() if s.read_only)))')"
  m8_fails=0
  for v in $RO_VERBS; do
    args="$(m_args "$v")"
    # shellcheck disable=SC2086
    it_zero_delta "M8-$v" fleet "$v" $args
    [ "$(tail -1 "$RESULTS" | cut -f2)" = FAIL ] && m8_fails=$((m8_fails+1))
  done
  [ "$m8_fails" = 0 ] \
    && it_pass M8 "$RESULTS" "each of the $(printf '%s\n' $RO_VERBS | wc -l | tr -d ' ') read-only verbs left a zero delta over FLEET_HOME+slots, asserted per verb (content AND mtime)" \
    || it_fail M8 "$RESULTS" "$m8_fails read-only verb(s) changed state"

  # ---- M9 ---------------------------------------------------------------------------------------
  cat > "$PY_DIR/m9.py" <<'PY'
"""M9 — an audit of every handler: no push/merge/publish/rm-rf outside the section dir, no spawn behind
a handler's back, and every DELETE site named together with the path it deletes.

The audit runs over the WHOLE package, not over `cli.py`'s intra-module call closure. A handler reaches
another module through an attribute call (`ctx.pool.unenroll`), and a closure that follows only bare-name
calls inside one module cannot cross that boundary — so the package's own `FORBIDDEN_CALLS` invariant is
unenforced exactly where the deletes live."""
import ast, os
from pathlib import Path
from fleet.cli import FORBIDDEN_CALLS, FORBIDDEN_COMMANDS, VERBS
pkg = Path(os.environ["INSTANT"]) / "src" / "fleet"
#: Probe/runner factories: the only functions allowed to spawn. Each is referenced by `default_context`
#: (or a caller's own injection) and by no handler.
SEAMS = {("session.py", "default_probes"), ("cli.py", "_default_runner"),
         ("workspace.py", "default_git")}
DELETERS = {"rmtree", "remove", "removedirs", "unlink", "rmdir"}
#: Every delete-shaped call in the package, read and accounted for. `pool` deletes its own bookkeeping
#: under `<FLEET_HOME>`; `roadmap._consume` calls `list.remove` on a python list and touches no file.
#: A new, moved or renamed site fails this case rather than being absorbed.
DELETE_ALLOWLIST = {
    ("pool.py", "unenroll", "unlink"),      # <home>/pool/enrolled/<slot>.json
    ("pool.py", "release", "unlink"),       # <home>/pool/leases/<slot>/lease.json and leftovers
    ("pool.py", "release", "rmdir"),        # <home>/pool/leases/<slot>
    ("roadmap.py", "_consume", "remove"),   # list.remove(body) — not a filesystem call
    # SI-9 / SI-7. Four sites added deliberately, each with the reason it is safe. The list stays a
    # CEILING: it is printed when an entry disappears, so it cannot quietly grow stale.
    ("atomic.py", "atomic_write", "unlink"),  # its OWN staging file, path.parent/tmp_name(path.name),
                                              # on the failure path only. Not removing it leaves a partial
                                              # file for the next reader — FI-20's third property.
    ("atomic.py", "_break", "rmdir"),         # its OWN advisory lock dir, path.parent/f".{path.name}.lock",
                                              # and only after the holder is shown dead. rmdir cannot empty
                                              # a directory, so it fails safe.
    ("pool.py", "_reclaim", "unlink"),        # staging litter inside <home>/pool/leases/<slot>, and ONLY
                                              # names matching atomic.tmp_name's shape: anything else raises
                                              # Refused naming it rather than being swept (SI-7).
    ("pool.py", "_reclaim", "rmdir"),         # <home>/pool/leases/<slot> once emptied of that litter.
    # The release pipeline. Both arguments are also written out in test_cli.py's OUTWARD_CALL_SITES —
    # which is itself a finding: this build now audits its delete sites in TWO registries that nothing
    # keeps in step, so a site can be declared in one and undeclared in the other. Tracked as `II-3` in
    # operations/tasks/fleetItStabilisation.
    ("atomic.py", "atomic_symlink", "unlink"),  # its OWN staging symlink, link.parent/tmp_name(link.name),
                                                # on the failure path only. The sibling of atomic_write's
                                                # entry above, for the one thing that primitive cannot
                                                # publish: os.symlink refuses an existing name, so the
                                                # alternative leaves `current` absent — measured at 238160
                                                # sightings by a concurrent reader over 300 flips.
    ("release_verify.py", "run", "rmtree"),     # the WRITABLE COPY it made moments earlier, at a name only
                                                # atomic.tmp_name can produce, under $FLEET_RELEASES. The
                                                # copy exists because run-all.sh writes RESULTS*.tsv beside
                                                # itself and the export is chmod -R a-w. In a `finally`, so
                                                # the refusal path does not leave a full copy of every
                                                # verified release on disk.
}
NOT_A_FILE_DELETE = {("roadmap.py", "_consume", "remove")}

def owner_of(tree):
    """The chain of enclosing functions for every node. A class name is not who makes a call, and a
    nested helper inside a probe factory is still inside that factory — the seam is the whole closure."""
    out = {}
    def walk(node, chain):
        for child in ast.iter_child_nodes(node):
            nxt = chain + (child.name,) if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                else chain
            out[id(child)] = nxt
            walk(child, nxt)
    walk(tree, ())
    return out

IN_PACKAGE = set()
for path in sorted(pkg.glob("*.py")):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            IN_PACKAGE.add(node.name)
SELF_LIKE = {"self", "ctx", "store", "pool", "sessions", "harvest", "roadmap", "review", "profile"}
bad, spawn_sites, examined, in_pkg_sites, deletes, delete_sites = [], [], 0, [], set(), []
for path in sorted(pkg.glob("*.py")):
    text = path.read_text()
    examined += 1
    for shape in FORBIDDEN_COMMANDS + ("rm -rf ~", "> /etc", "sudo "):
        if shape in text:
            bad.append(f"{path.name} contains the outward shape {shape!r}")
    tree = ast.parse(text)
    owners = owner_of(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        attribute = isinstance(node.func, ast.Attribute)
        name = node.func.attr if attribute else getattr(node.func, "id", "")
        receiver = getattr(node.func.value, "id", "") if attribute else ""
        if name not in FORBIDDEN_CALLS:
            continue
        chain = owners.get(id(node), ())
        owner = chain[-1] if chain else "<module>"
        site = (f"{path.name}:{node.lineno} {'.'.join(chain) or '<module>'}() -> "
                f"{receiver + '.' if receiver else ''}{name}()")
        if any((path.name, link) in SEAMS for link in chain):
            spawn_sites.append(site)
        elif name in DELETERS:
            deletes.add((path.name, owner, name))
            delete_sites.append(site)
        elif receiver in SELF_LIKE and name in IN_PACKAGE:
            in_pkg_sites.append(site)
        else:
            bad.append(f"FORBIDDEN CALL {site}")
print(f"examined {examined} module(s) behind {len(VERBS)} handlers")
for site in sorted(spawn_sites):
    print("spawn seam (no handler reaches it):", site)
for site in sorted(in_pkg_sites):
    print("in-package method, not a spawn:", site)
for site in sorted(delete_sites):
    print("DELETE site:", site)
undeclared = sorted(deletes - DELETE_ALLOWLIST)
if undeclared:
    bad.append(f"UNDECLARED DELETE SITE(S): {undeclared}")
gone = sorted(DELETE_ALLOWLIST - deletes)
if gone:
    print("allow-listed delete no longer present (the list is a ceiling):", gone)
# Every file-deleting site must derive its target from the store root, never from a workspace or $HOME.
source_of = {}
for path in sorted(pkg.glob("*.py")):
    body = path.read_text()
    for node in ast.walk(ast.parse(body)):
        if isinstance(node, ast.FunctionDef):
            source_of[(path.name, node.name)] = ast.get_source_segment(body, node) or ""
# SI-9. The rule WAS `"self.enrolled" in body or "self.leases" in body` — a substring test, which is
# why it rejected atomic.py's two sites: their targets are derived from the function's OWN operand
# (`path.parent / tmp_name(path.name)`), which is every bit as rooted, just not rooted in the pool.
#
# The fix is to widen the RULE, not to add names to the allowlist. An allowlist entry says "somebody
# decided this one is fine"; a rule says what makes any delete fine, and can still fail. What makes these
# safe is that the deleted path is DERIVED, inside the same function, from either the store root or one of
# the function's own parameters — never from $HOME, the environment, or an absolute literal. So that is
# what is now checked, by following the assignments.
FORBIDDEN_SOURCES = ("Path.home", "expanduser", "os.environ", "getenv", "os.sep")
ROOTS = ("self.enrolled", "self.leases", "self.root", "self.home")

def deleted_names(fn):
    """The local name each delete in this function is applied to: `os.unlink(tmp)` -> tmp,
    `lock.rmdir()` -> lock, `entry.unlink()` -> entry."""
    out = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("unlink", "rmdir", "rmtree", "remove"):
            continue
        if isinstance(node.func.value, ast.Name) and node.func.value.id not in ("os", "shutil"):
            out.add(node.func.value.id)                     # receiver.unlink()
        for arg in node.args:                               # os.unlink(x)
            if isinstance(arg, ast.Name):
                out.add(arg.id)
    return out

def derivation_ok(fn, name, depth=0):
    """Whether EVERY assignment to `name` in this function derives it from a parameter or the store root.

    "Every", not "some", and that word was bought by a mutation. The first version of this returned True on
    the first assignment it found that mentioned the store root — so injecting a SECOND assignment
    `record = Path.home() / 'victim.json'` right above `record.unlink()` SURVIVED: the original rooted
    assignment was still there, the check found it, and never looked at the poisoned one. A rule that any
    single safe assignment satisfies is a rule an attacker (or a careless edit) satisfies by leaving the
    safe line in place.
    """
    if depth > 6:
        return False
    params = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
    sources = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                sources.append(node.value)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                sources.append(node.value)
        elif isinstance(node, (ast.For, ast.comprehension)):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                sources.append(node.iter)
    if not sources:
        return name in params            # a parameter never assigned: the caller's path, which is the point
    for src in sources:
        text = ast.unparse(src)
        if any(f in text for f in FORBIDDEN_SOURCES):
            return False                 # ONE poisoned assignment condemns the name
        if any(r in text for r in ROOTS):
            continue
        if any(isinstance(n, ast.Name) and (n.id in params or derivation_ok(fn, n.id, depth + 1))
               for n in ast.walk(src)):
            continue
        return False                     # this assignment is derived from nothing we can vouch for
    return True


fn_of = {}
for path in sorted(pkg.glob("*.py")):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            fn_of[(path.name, node.name)] = node

for module, function, call in sorted(deletes):
    if (module, function, call) in NOT_A_FILE_DELETE:
        print(f"{module}:{function}() {call}() is a list operation, not a filesystem delete")
        continue
    fn = fn_of.get((module, function))
    if fn is None:
        bad.append(f"{module}:{function}() could not be parsed, so its delete is unverified")
        continue
    names = deleted_names(fn)
    if not names:
        bad.append(f"{module}:{function}() deletes something this audit could not name — unverified")
        continue
    unrooted = sorted(n for n in names if not derivation_ok(fn, n))
    print(f"{module}:{function}() {call}() targets {sorted(names)} derived from the store root or its own "
          f"operand: {not unrooted}")
    if unrooted:
        bad.append(f"{module}:{function}() deletes {unrooted}, which is derived neither from the store "
                   f"root nor from the function's own parameters")
assert not bad, "\n".join(bad)
print(f"OK M9: across all {examined} modules — no push/merge/publish/rm-rf shape anywhere; the only "
      f"spawn sites are the {len(SEAMS)} probe/runner factories ({len(spawn_sites)} call sites), none "
      f"reachable from a handler; every delete is one of {len(deletes)} accounted-for sites, and each "
      f"target is DERIVED (by following the assignments, not by matching a substring) from the store root "
      f"or from that function's own parameters — never from $HOME, the environment or an absolute literal")
PY
  it_py M9 "$PY_DIR/m9.py"

  # ---- M10 / M11 — pane-guard against REAL panes -------------------------------------------------
  # Every pane is built so its input box is the LAST row of the capture (a real pane's box is at the
  # bottom of the screen); the filler is what makes the geometry deterministic at any pane height.
  FILL='i=1; while [ $i -le 200 ]; do echo "filler line $i"; i=$((i+1)); done;'
  it_tmux_new "itfleet-M-clean" "sh -c '$FILL echo \"? for shortcuts\"; printf \"\\342\\235\\257\\302\\240\"; sleep 900'"
  it_tmux_new "itfleet-M-queued" "sh -c '$FILL echo \"? for shortcuts\"; printf \"\\342\\235\\257\\302\\240draft message\"; sleep 900'"
  it_tmux_new "itfleet-M-busy" "sh -c '$FILL echo \"? for shortcuts\"; echo \"esc to interrupt\"; sleep 900'"
  it_tmux_new "itfleet-M-shell" "sleep 900"
  sleep 2
  m10_bad=0
  for pair in "itfleet-M-clean 0" "itfleet-M-queued 10" "itfleet-M-busy 11" "itfleet-M-shell 12" "itfleet-M-absent-zzz 13"; do
    set -- $pair
    pane="$1"; want="$2"
    it_cap "$pane" > "$EV/M10-$pane.pane" 2>/dev/null || : > "$EV/M10-$pane.pane"
    it_run "M10-$pane" fleet pane-guard --pane "$pane"; rc=$RC
    printf 'pane=%s want=%s got=%s\n%s\n' "$pane" "$want" "$rc" "$(cat "$OUT_FILE")" \
      >> "$EV/M10-verdicts.txt"
    [ "$rc" = "$want" ] || m10_bad=$((m10_bad+1))
  done
  [ "$m10_bad" = 0 ] \
    && it_pass M10 "$EV/M10-verdicts.txt" "real panes: clean=0 queued=10 esc-to-interrupt=11 non-claude-shell=12 nonexistent=13" \
    || it_fail M10 "$EV/M10-verdicts.txt" "$m10_bad of 5 real-pane verdicts wrong"

  # M11 — the real render byte sequence: U+276F U+00A0 == e2 9d af c2 a0
  it_cap "itfleet-M-queued" > "$EV/M11-pane.txt"
  grep -v '^$' "$EV/M11-pane.txt" | tail -1 > "$EV/M11-caret-line.txt"
  hexdump -C "$EV/M11-caret-line.txt" > "$EV/M11-caret-line.hex"
  hexdump -C "$EV/M11-pane.txt" | tail -20 > "$EV/M11-pane-tail.hex"
  it_run M11 fleet pane-guard --pane "itfleet-M-queued"; m11rc=$RC
  m11bytes=$(od -An -tx1 "$EV/M11-caret-line.txt" | tr -d ' \n' | grep -c 'e29daf.*c2a0' || true)
  if [ "$m11rc" = 10 ] && [ "$m11bytes" -ge 1 ] && grep -q "draft message" "$EV/M11.stdout"; then
    it_pass M11 "$EV/M11-caret-line.hex" "the pane really renders e2 9d af c2 a0 (❯ + U+00A0) and pane-guard returns 10, quoting 'draft message'; hexdump in M11-caret-line.hex / M11-pane-tail.hex"
  else
    it_fail M11 "$EV/M11-caret-line.hex" "rc=$m11rc (want 10), nbsp-bytes-present=$m11bytes"
  fi

  # M11b — the same real render with the box NOT in the bottom rows of the capture. Not in the plan;
  # reported because a real tmux capture is padded to the pane height with blank lines.
  it_tmux_new "itfleet-M-padded" "sh -c 'echo \"? for shortcuts\"; printf \"\\342\\235\\257\\302\\240draft message\\n\"; sleep 900'"
  sleep 1
  it_cap "itfleet-M-padded" > "$EV/M11b-pane.txt"
  hexdump -C "$EV/M11b-pane.txt" > "$EV/M11b-pane.hex"
  it_run M11b fleet pane-guard --pane "itfleet-M-padded"; m11brc=$RC
  blanks=$(awk 'BEGIN{c=0} {if ($0=="") c++; else c=0} END{print c}' "$EV/M11b-pane.txt")
  if [ "$m11brc" = 10 ]; then
    it_pass M11b "$EV/M11b-pane.txt" "queued text is still seen with $blanks blank line(s) of pane padding below the box"
  else
    it_fail M11b "$EV/M11b-pane.txt" "SAME bytes, box $blanks blank capture line(s) above the pane bottom ⇒ pane-guard returned $m11brc (want 10): session.PROMPT_TAIL_LINES=8 counts RAW capture lines, and tmux pads a capture to the pane height, so an input box further than 8 rows from the bottom is invisible to the predicate — a FALSE SAFE with text in the box"
  fi

  # ---- M12 --------------------------------------------------------------------------------------
  fleet init --name m12probe > "$EV/M12-setup.out" 2>&1
  M12INST="$(ls "$FLEET_HOME/instants" | grep m12probe | head -1)"
  M12P="$FLEET_HOME/instants/$M12INST"
  OUTSIDE="$EV/m12-should-not-exist.txt"
  rm -f "$OUTSIDE" 2>/dev/null
  {
    printf '# RUNBOOK — %s\n\n' "$M12INST"
    printf 'Updated: 00000000\nStatus: hand-written for M12\n\n'
    printf '```bash\necho a-recipe-that-really-runs\n```\n\n'
    printf '```bash\necho dirt > %s\n```\n\n' "$OUTSIDE"
    printf '```bash\nrm -rf /tmp/fleet-m12-target\n```\n'
  } > "$M12P/RUNBOOK.md"
  it_run M12 fleet verify --instant "$M12P" --porcelain; m12rc=$RC
  exec_rows=$(awk -F'\t' '$1=="executed"{c++} END{print c+0}' "$OUT_FILE")
  outside_rows=$(awk -F'\t' '$1=="outside-sandbox"{c++} END{print c+0}' "$OUT_FILE")
  never_rows=$(awk -F'\t' '$1=="never-executed"{c++} END{print c+0}' "$OUT_FILE")
  wrote_outside=no; [ -e "$OUTSIDE" ] && wrote_outside=yes
  if [ "$exec_rows" -ge 1 ] && [ "$outside_rows" -ge 2 ] && [ "$never_rows" -ge 2 ] \
     && [ "$wrote_outside" = no ] && [ "$m12rc" = 1 ]; then
    it_pass M12 "$EV/M12.stdout" "1 recipe executed in the sandbox; 2 refused BEFORE execution (a redirect outside the sandbox and a delete) and each is also reported never-executed; the outside path was never created; exit $m12rc"
  else
    it_fail M12 "$EV/M12.stdout" "executed=$exec_rows outside=$outside_rows never=$never_rows wrote_outside=$wrote_outside rc=$m12rc"
  fi

  # ---- M13 — selftest always stamps; refuses ONLY for dirt inside the covered paths --------------
  git -C "$INSTANT" status --porcelain > "$EV/M13-git-before.txt"
  it_run M13-outside fleet selftest --porcelain; rc_out=$RC
  cp "$OUT_FILE" "$EV/M13-outside.tsv"
  stamp_out=$(awk -F'\t' '$1=="tree"{c++} END{print c+0}' "$EV/M13-outside.tsv")
  inside_out=$(awk -F'\t' '$1=="dirty-inside-coverage"{c++} END{print c+0}' "$EV/M13-outside.tsv")
  suite_out=$(awk -F'\t' '$1=="suite"{print $3}' "$EV/M13-outside.tsv")
  DIRT="$INSTANT/tests/it-group5-m13-dirt-probe.txt"
  printf 'M13 probe: dirt INSIDE a covered path. Deleted by run-group5.sh.\n' > "$DIRT"
  git -C "$INSTANT" status --porcelain > "$EV/M13-git-dirty.txt"
  it_run M13-inside fleet selftest --porcelain; rc_in=$RC
  cp "$OUT_FILE" "$EV/M13-inside.tsv"
  stamp_in=$(awk -F'\t' '$1=="tree"{c++} END{print c+0}' "$EV/M13-inside.tsv")
  inside_in=$(awk -F'\t' '$1=="dirty-inside-coverage"{c++} END{print c+0}' "$EV/M13-inside.tsv")
  rm -f "$DIRT"
  git -C "$INSTANT" status --porcelain > "$EV/M13-git-after.txt"
  # Both suite runs are captured so the claim is evidenced rather than described. The earlier comment here
  # said the verdict "can never be green" because `selftest`'s re-entrancy mark failed a contract test:
  # that is no longer true and was left standing after the fix — measured 2026-07-30T15:4x, 723 tests OK
  # both WITH and WITHOUT `FLEET_SELFTEST=1` (M13-suite-with-guard.txt / -without-guard.txt).
  #
  # M13's real PRECONDITION, which it does not create and cannot: `src/` and `tests/` must be COMMITTED.
  # The `outside` half asserts exit 0 with no `dirty-inside-coverage` row, and `selftest` reports that row
  # whenever a covered path is modified in the working tree — so any uncommitted edit to src/ or tests/ by
  # anyone makes this case red, correctly, and the verdict is about the tree rather than about `selftest`.
  ( cd "$INSTANT" && PYTHONPATH="$INSTANT/src" python3 -m unittest discover -s tests 2>&1 | tail -12 ) \
      > "$EV/M13-suite-without-guard.txt"
  ( cd "$INSTANT" && PYTHONPATH="$INSTANT/src" FLEET_SELFTEST=1 python3 -m unittest discover -s tests 2>&1 \
      | tail -16 ) > "$EV/M13-suite-with-guard.txt"
  if [ "$stamp_out" -ge 1 ] && [ "$inside_out" = 0 ] && [ "$rc_out" = 0 ] \
     && [ "$stamp_in" -ge 1 ] && [ "$inside_in" -ge 1 ] && [ "$rc_in" != 0 ]; then
    it_pass M13 "$EV/M13-inside.tsv" "dirt outside the covered paths ⇒ exit $rc_out WITH a tree stamp; dirt inside tests/ ⇒ exit $rc_in with a dirty-inside-coverage violation, and the stamp is printed in BOTH runs"
  else
    it_fail M13 "$EV/M13-inside.tsv" "$(sq "outside: rc=$rc_out (want 0) stamp_rows=$stamp_out inside_rows=$inside_out suite=$suite_out; inside: rc=$rc_in stamp_rows=$stamp_in inside_rows=$inside_in")"
  fi

  # ---- M14 --------------------------------------------------------------------------------------
  M14LOG="$EV/M14-per-verb.txt"; : > "$M14LOG"
  m14_bad=0; m14_src=0
  for v in $VERBS_ALL; do
    timeout 10 python3 -m fleet.cli "$v" --help > "$EV/M14-$v.stdout" 2> "$EV/M14-$v.stderr"; rc=$?
    src=$(cat "$EV/M14-$v.stdout" "$EV/M14-$v.stderr" | grep -cE '^\s*(def |import |class |return |raise )')
    printf '%-20s rc=%s source_lines=%s\n' "$v" "$rc" "$src" >> "$M14LOG"
    [ "$rc" = 0 ] || m14_bad=$((m14_bad+1))
    [ "$src" = 0 ] || m14_src=$((m14_src+1))
  done
  if [ "$m14_bad" = 0 ] && [ "$m14_src" = 0 ]; then
    it_pass M14 "$M14LOG" "--help exits 0 for all $NVERBS verbs and prints no source code"
  else
    it_fail M14 "$M14LOG" "--help exits non-zero for $m14_bad of $NVERBS verbs (no verb declares a --help flag, so the parser refuses it as undeclared: exit 2 with usage on stderr); verbs printing source code: $m14_src"
  fi

  it_cleanup_tmux
  it_assert_isolation "M-leave"
}

# =================================================================================================
# §N — real tmux session lifecycle  (own FLEET_HOME, own prefix, serial)
# =================================================================================================
section_N() {
  it_section N || return 1
  it_fresh_fixture
  export EV SLOTS DUMMY INSTANT SECTION
  PY_DIR="$EV/py"
  mkdir -p "$SLOTS/ns1" "$SLOTS/ns2" "$PY_DIR"
  RCFILE="$EV/nbsp.bashrc"
  # A real shell whose prompt is the real render: U+276F followed by U+00A0.
  {
    printf 'PS1=$'"'"'\\u276f\\u00a0'"'"'\n'
    printf 'unset PROMPT_COMMAND\n'
  } > "$RCFILE"
  SHELL_CMD="bash --noprofile --rcfile $RCFILE -i"

  fleet init --name nprobe > "$EV/N-setup.out" 2>&1
  INST="$(ls "$FLEET_HOME/instants" | head -1)"
  INSTP="$FLEET_HOME/instants/$INST"
  fleet enroll --slot "$SLOTS/ns1" >> "$EV/N-setup.out" 2>&1

  # ---- N1 --------------------------------------------------------------------------------------
  W1="itfleet-N-w1"
  it_tmux_new "$W1" "$SHELL_CMD"
  sleep 1.5
  fleet resume --instant "$INSTP" --slot ns1 --tmux "$W1" >> "$EV/N-setup.out" 2>&1
  TODO="$(python3 - <<'PY'
import json, os
from pathlib import Path
recs = sorted((Path(os.environ["FLEET_HOME"]) / "records").glob("*.json"))
print(json.loads(recs[0].read_text())["todo_id"] if recs else "")
PY
)"
  export INSTP TODO
  it_run N1 fleet status --id "$TODO" --porcelain; n1rc=$RC
  ALIVE="$(python3 -c "
from fleet.session import SessionLayer, default_probes
print(SessionLayer(default_probes()).alive('$W1'))")"
  live_ev=$(grep -c '^evidence.liveness	session' "$EV/N1.stdout")
  state=$(awk -F'\t' '$1=="state"{print $2}' "$EV/N1.stdout")
  if [ "$n1rc" = 0 ] && [ "$ALIVE" = True ] && [ "$live_ev" -ge 1 ]; then
    it_pass N1 "$EV/N1.stdout" "real session $W1 is live: status state=$state, evidence.liveness=session, SessionLayer.alive=$ALIVE"
  else
    it_fail N1 "$EV/N1.stdout" "rc=$n1rc alive=$ALIVE liveness_rows=$live_ev state=$state"
  fi

  # ---- N2 --------------------------------------------------------------------------------------
  it_cap "$W1" > "$EV/N2-pane.txt"
  cat > "$PY_DIR/n2.py" <<'PY'
"""N2 — the captured pane round-trips through the predicates: what the probe captures is what the
predicates are handed, and both agree with pane-guard's own answer."""
import os, subprocess, sys
from pathlib import Path
from fleet.session import SessionLayer, default_probes
name = os.environ["W1"]
sl = SessionLayer(default_probes())
captured = sl.pane(name)
on_disk = Path(os.environ["EV"], "N2-pane.txt").read_text()
print("probe capture lines:", len(captured.splitlines()), "tmux capture lines:", len(on_disk.splitlines()))
assert captured.rstrip("\n") == on_disk.rstrip("\n"), "the probe's capture differs from tmux's own"
print("busy:", sl.busy(captured), "unsubmitted:", repr(sl.unsubmitted(captured)))
assert sl.busy(captured) is False
assert sl.unsubmitted(captured) is None, "a quiet shell reported queued text"
done = subprocess.run([sys.executable, "-m", "fleet.cli", "pane-guard", "--pane", name],
                      capture_output=True, text=True, env=dict(os.environ))
print("pane-guard rc:", done.returncode)
print(done.stdout)
assert done.returncode in (0, 12), f"pane-guard rc={done.returncode}"
print("OK N2: the captured text round-trips — probe == tmux, busy=False, unsubmitted=None, and "
      f"pane-guard agrees (rc={done.returncode}: a bash pane carries no claude marker)")
PY
  export W1
  it_py N2 "$PY_DIR/n2.py"

  # ---- N3 — type text and do NOT submit it -----------------------------------------------------
  # Fill the screen first so the shell prompt is the LAST row of the capture, as a real pane's box is.
  it_send "$W1" 'i=1; while [ $i -le 200 ]; do echo "filler line $i"; i=$((i+1)); done; echo "? for shortcuts"' Enter
  sleep 2
  it_send "$W1" -l 'draft message'
  sleep 1
  it_cap "$W1" > "$EV/N3-pane.txt"
  grep -v '^$' "$EV/N3-pane.txt" | tail -1 > "$EV/N3-caret-line.txt"
  hexdump -C "$EV/N3-caret-line.txt" > "$EV/N3-caret-line.hex"
  hexdump -C "$EV/N3-pane.txt" | tail -12 > "$EV/N3-pane-tail.hex"
  it_run N3 fleet pane-guard --pane "$W1"; n3rc=$RC
  it_run N3-status fleet status --id "$TODO" --porcelain
  n3bytes=$(od -An -tx1 "$EV/N3-caret-line.txt" | tr -d ' \n' | grep -c 'e29dafc2a0' || true)
  verbatim=$(grep -c 'draft message' "$EV/N3-status.stdout")
  if [ "$n3rc" = 10 ] && [ "$n3bytes" -ge 1 ] && [ "$verbatim" -ge 1 ]; then
    it_pass N3 "$EV/N3-caret-line.hex" "typed-not-submitted in a REAL bash pane rendering ❯+U+00A0 (e2 9d af c2 a0): pane-guard=10 and status reports 'draft message' verbatim (state=$(awk -F'\t' '$1=="state"{print $2}' "$EV/N3-status.stdout"))"
  else
    it_fail N3 "$EV/N3-caret-line.hex" "rc=$n3rc (want 10) nbsp_bytes=$n3bytes status_names_text=$verbatim"
  fi

  # ---- N4 — submit it; the alarm must clear ----------------------------------------------------
  it_send "$W1" Enter
  sleep 1.5
  it_cap "$W1" > "$EV/N4-pane.txt"
  it_run N4 fleet pane-guard --pane "$W1"; n4rc=$RC
  it_run N4-status fleet status --id "$TODO" --porcelain
  n4state=$(awk -F'\t' '$1=="state"{print $2}' "$EV/N4-status.stdout")
  if [ "$n4rc" != 10 ] && [ "$n4state" != "BLOCKED" ]; then
    it_pass N4 "$EV/N4-pane.txt" "after submitting, pane-guard=$n4rc (no longer queued-text) and status state=$n4state"
  else
    it_fail N4 "$EV/N4-pane.txt" "$(sq "the alarm did NOT clear: pane-guard=$n4rc, status state=$n4state. The submitted line is still drawn ABOVE the new empty box, and session.unsubmitted() returns the FIRST caret line in its 8-line window instead of the box's own line — so already-sent text re-alarms. It quoted: $(sed -n 's/.*unsubmitted text in its input box (\(.*\)); a send.*/\1/p' "$EV/N4.stdout" | head -1)")"
  fi
  # N4b — the boundary: scroll the submitted line out of the 8-line window and it does clear.
  it_send "$W1" 'i=1; while [ $i -le 12 ]; do echo "after-submit line $i"; i=$((i+1)); done; echo "? for shortcuts"' Enter
  sleep 2
  it_cap "$W1" > "$EV/N4b-pane.txt"
  it_run N4b fleet pane-guard --pane "$W1"; n4brc=$RC
  [ "$n4brc" != 10 ] \
    && it_pass N4b "$EV/N4b-pane.txt" "the same pane clears (pane-guard=$n4brc) once the submitted line is more than PROMPT_TAIL_LINES=8 rows above the box — which locates N4's failure exactly" \
    || it_fail N4b "$EV/N4b-pane.txt" "still 10 even with the history scrolled away"

  # ---- N5 --------------------------------------------------------------------------------------
  it_send "$W1" -l 'echo "esc to interrupt"'
  it_send "$W1" Enter
  sleep 1.5
  it_cap "$W1" > "$EV/N5-pane.txt"
  it_run N5 fleet pane-guard --pane "$W1"; n5rc=$RC
  it_run N5-close fleet close --id "$TODO"; n5crc=$RC
  # The section's OWN session, on the section's own server: `it_tmux`, exact target (`=`, no trailing
  # colon — this is a target-SESSION, not a pane).
  still_alive="$(it_tmux has-session -t "=$W1" 2>/dev/null && echo yes || echo no)"
  if [ "$n5rc" = 11 ] && [ "$n5crc" = 4 ] && [ "$still_alive" = yes ]; then
    it_pass N5 "$EV/N5-close.stderr" "esc-to-interrupt in a real pane ⇒ pane-guard=11; close refused with exit 4 naming its override, and the session is still alive"
  else
    it_fail N5 "$EV/N5-close.stderr" "pane-guard=$n5rc (want 11), close rc=$n5crc (want 4), session alive=$still_alive"
  fi

  # ---- N6 --------------------------------------------------------------------------------------
  it_tmux_kill "$W1"                 # killed EXTERNALLY, behind the tool's back
  sleep 0.5
  it_run N6-status fleet status --id "$TODO" --porcelain
  n6state=$(awk -F'\t' '$1=="state"{print $2}' "$EV/N6-status.stdout")
  it_run N6-leases-before fleet leases --porcelain
  OWNER=$(awk -F'\t' '$1=="ns1"{print $4}' "$EV/N6-leases-before.stdout")
  # A foreign base first: the refusal must NAME the owner rather than read as a bug (RI-31).
  it_run N6-reap-foreign fleet reap --base "$INSTP" --porcelain; n6frc=$RC
  foreign_names_owner=$(grep -c -- "$OWNER" "$EV/N6-reap-foreign.stdout")
  it_run N6-reap fleet reap --base "$OWNER" --porcelain; n6rc=$RC
  it_run N6-leases-after fleet leases --porcelain
  before_held=$(awk -F'\t' '$1=="ns1"{print $2}' "$EV/N6-leases-before.stdout")
  after_held=$(awk -F'\t' '$1=="ns1"{print $2}' "$EV/N6-leases-after.stdout")
  if [ "$n6state" = DEAD ] && [ "$before_held" = held ] && [ "$after_held" = free ]; then
    it_pass N6 "$EV/N6-status.stdout" "$(sq "an external kill-session ⇒ status DEAD on the next poll; reap --base $OWNER (exit $n6rc) took ns1 from $before_held to $after_held; a reap from a foreign base refused first (exit $n6frc) and named the owner ($foreign_names_owner hit)")"
  else
    it_fail N6 "$EV/N6-status.stdout" "$(sq "state=$n6state lease before=$before_held after=$after_held reap rc=$n6rc owner=$OWNER foreign-reap rc=$n6frc")"
  fi

  # ---- N7 — a session whose name is a PREFIX of another's ---------------------------------------
  LONG="itfleet-N-pre-ab"; SHORT="itfleet-N-pre-a"
  it_tmux_new "$LONG" "sh -c 'echo I-am-the-LONG-session; sleep 600'"
  sleep 1
  # All three are about the sessions UNDER TEST, so all three are on the section's private server. The
  # loose/exact pair is the point of N7: `-t itfleet-N-pre-a` resolves BY PREFIX to `itfleet-N-pre-ab`,
  # `-t =itfleet-N-pre-a` does not. Asking the LIVE server would prove nothing, and `$LONG` only exists
  # on the private one.
  it_tmux ls > "$EV/N7-sessions.txt" 2>&1
  it_tmux has-session -t "$SHORT" > "$EV/N7-has-session-loose.txt" 2>&1; loose=$?
  it_tmux has-session -t "=$SHORT" > "$EV/N7-has-session-exact.txt" 2>&1; exact=$?
  cat > "$PY_DIR/n7.py" <<'PY'
"""N7 — liveness must never confuse a session with a longer one that it is a prefix of."""
import os
from fleet.session import SessionLayer, default_probes
sl = SessionLayer(default_probes())
long_name, short_name = os.environ["LONG"], os.environ["SHORT"]
print("sessions on the box that start with the prefix:")
print(open(os.environ["EV"] + "/N7-sessions.txt").read())
alive_long = sl.alive(long_name)
alive_short = sl.alive(short_name)
pane_long = sl.pane(long_name)
pane_short = sl.pane(short_name)
print(f"alive({long_name})={alive_long}  alive({short_name})={alive_short}")
print(f"pane({short_name}) first line: {pane_short.splitlines()[:1]}")
fails = []
if not alive_long:
    fails.append(f"{long_name} exists and alive() says False")
if alive_short:
    fails.append(f"{short_name} does NOT exist and alive() says True — the liveness probe resolved a "
                 f"prefix to {long_name}")
if pane_short.strip() and pane_short.strip() == pane_long.strip():
    fails.append(f"pane({short_name}) returned {long_name}'s screen: "
                 f"{pane_short.splitlines()[:1]}")
assert not fails, "\n".join(fails)
print("OK N7: the prefix name is not alive and does not capture the longer session's pane")
PY
  export LONG SHORT
  it_py N7 "$PY_DIR/n7.py"
  # The label names the argv that actually ran, socket included — an evidence file that misdescribes its
  # own command is worse than no evidence file.
  printf 'tmux -L %s has-session -t %s (loose) rc=%s\ntmux -L %s has-session -t =%s (exact) rc=%s\n' \
         "$IT_TMUX_SOCKET" "$SHORT" "$loose" "$IT_TMUX_SOCKET" "$SHORT" "$exact" \
         > "$EV/N7-tmux-target.txt"
  it_tmux_kill "$LONG"

  # ---- N8 — scrollback is not current state ----------------------------------------------------
  HIST="itfleet-N-hist"
  it_tmux_new "$HIST" "sh -c 'i=1; while [ \$i -le 100 ]; do echo \"history line \$i\"; i=\$((i+1)); done; printf \"\\342\\235\\257\\302\\240an old draft nobody sent\\n\"; j=1; while [ \$j -le 12 ]; do echo \"later output \$j\"; j=\$((j+1)); done; echo \"? for shortcuts\"; printf \"\\342\\235\\257\\302\\240\"; sleep 900'"
  sleep 2
  it_cap "$HIST" > "$EV/N8-pane.txt"
  # The section's own pane, private server, `=name:` — a pane target needs the trailing colon (`FI-23`).
  it_tmux capture-pane -p -S -200 -t "=$HIST:" > "$EV/N8-scrollback.txt"
  hexdump -C "$EV/N8-pane.txt" | tail -12 > "$EV/N8-pane-tail.hex"
  it_run N8 fleet pane-guard --pane "$HIST"; n8rc=$RC
  old_in_capture=$(grep -c 'an old draft nobody sent' "$EV/N8-pane.txt")
  hist_lines=$(grep -c 'history line' "$EV/N8-scrollback.txt")
  if [ "$n8rc" = 0 ] && [ "$old_in_capture" -ge 1 ]; then
    it_pass N8 "$EV/N8-pane.txt" "$hist_lines history lines in scrollback and the old ❯+U+00A0 prompt IS in the captured screen ($old_in_capture hit), yet the empty box now ⇒ pane-guard=0, no queued text"
  else
    it_fail N8 "$EV/N8-pane.txt" "rc=$n8rc (want 0), old prompt present in capture=$old_in_capture, history lines=$hist_lines"
  fi

  # ---- N9 — close disarms nothing it does not own ----------------------------------------------
  OWN="itfleet-N-own"; OTHER="itfleet-N-bystander"; export OWN OTHER
  it_tmux_new "$OWN" "sleep 900"
  it_tmux_new "$OTHER" "sleep 900"
  sleep 1
  mkdir -p "$SLOTS/ns2"
  fleet enroll --slot "$SLOTS/ns2" >> "$EV/N-setup.out" 2>&1
  fleet init --name nOwned > "$EV/N9-setup.out" 2>&1
  N9INST="$FLEET_HOME/instants/$(ls "$FLEET_HOME/instants" | grep nowned | head -1)"
  fleet resume --instant "$N9INST" --slot ns2 --tmux "$OWN" >> "$EV/N9-setup.out" 2>&1
  N9TODO="$(python3 - <<'PY'
import json, os
from pathlib import Path
for path in sorted((Path(os.environ["FLEET_HOME"]) / "records").glob("*.json")):
    rec = json.loads(path.read_text())
    if rec.get("tmux") == os.environ["OWN"]:
        print(rec["todo_id"]); break
PY
)"
  it_run N9 fleet close --id "$N9TODO" --force; n9rc=$RC
  sleep 0.5
  # The three subjects of the case are §N's own sessions, so they are asked of §N's own server.
  it_tmux ls > "$EV/N9-sessions-after.txt" 2>&1
  own_gone=$(it_tmux has-session -t "=$OWN" 2>/dev/null && echo alive || echo gone)
  other_alive=$(it_tmux has-session -t "=$OTHER" 2>/dev/null && echo alive || echo gone)
  hist_alive=$(it_tmux has-session -t "=$HIST" 2>/dev/null && echo alive || echo gone)
  # DELIBERATELY BARE, and deliberately READ-ONLY: this pair is the "the operator's sessions are
  # untouched" snapshot, and the operator's sessions are on the LIVE/default server by definition. An
  # `it_tmux ls | grep -c '^dt-'` here would count dt- sessions on §N's own private server — always zero,
  # a claim that would hold if `close` had deleted every live session on the box. The binding form of this
  # check is `it_assert_isolation` (full live name-set vs the baseline); this is the in-case snapshot.
  it_live_tmux_sessions > "$EV/N9-live-sessions-after.txt"
  dt_untouched=$(tmux ls 2>/dev/null | grep -c '^dt-')
  named_other=$(grep -c "$OTHER" "$EV/N9.stdout" "$EV/N9.stderr" | awk -F: '{s+=$2} END{print s+0}')
  if [ "$n9rc" = 0 ] && [ "$own_gone" = gone ] && [ "$other_alive" = alive ] \
     && [ "$hist_alive" = alive ] && [ "$named_other" = 0 ]; then
    it_pass N9 "$EV/N9-sessions-after.txt" "close ended only the session its record names ($OWN gone); the bystander and the history session are untouched, close never names them; on the LIVE server (N9-live-sessions-after.txt) $dt_untouched dt- session(s) are still present — REPORTED, not asserted: the binding live-server check is ISOLATION-N-leave"
  else
    it_fail N9 "$EV/N9-sessions-after.txt" "rc=$n9rc own=$own_gone other=$other_alive hist=$hist_alive names_other=$named_other"
  fi

  it_cleanup_tmux
  it_assert_isolation "N-leave"
}

# =================================================================================================

printf 'source pinned: %s\n' "$(it_pin "before")"
for want in "${WANTED[@]}"; do
  case "$want" in
    L) section_L ;;
    M) section_M ;;
    N) section_N ;;
    *) printf 'unknown section %s\n' "$want" >&2 ;;
  esac
done
# SOURCE-STABLE — GIVEN a pin of `src/fleet/*.py` taken before the sections ran, WHEN they have all
# finished, THEN the pin is byte-identical. This is a run-level row, not a section's: it says whether every
# verdict above is attributable to ONE tree state. A drifted pin does not make those verdicts false, it
# makes them unattributable — which is why the failure text names the rewrite rather than any section.
printf 'source pinned: %s\n' "$(it_pin "after")"
pin_drift="$(diff <(grep 'src/fleet' "$HERE/SOURCE-PIN-group5-before.txt") \
                  <(grep 'src/fleet' "$HERE/SOURCE-PIN-group5-after.txt") | grep '^[<>]' | head -6)"
if [ -z "$pin_drift" ]; then
  it_pass "SOURCE-STABLE" "$HERE/SOURCE-PIN-group5-after.txt" "src/fleet/*.py byte-identical for the whole run"
else
  it_fail "SOURCE-STABLE" "$HERE/SOURCE-PIN-group5-after.txt" \
    "$(sq "the implementation was rewritten WHILE these sections ran: $pin_drift")"
fi

# The PID SET, not the count. This failed on 8 -> 7 in the close-out run: a DECREASE, caused by one of the
# operator's own sessions ending, with nothing in §L/§M/§N able to start or signal a `claude`. A count cannot
# tell "the thing I was forbidden to do" from "something unrelated finished", so it reported the operator's
# churn as this section's contamination — `SI-1`'s shape one control over. The rule is asymmetric and the
# helper now is too: an ADDITION fails, a REMOVAL is reported. Lifted into lib.sh from §D, which wrote it.
it_assert_no_new_claude "CLAUDE-COUNT" "$CLAUDE_PIDS_BEFORE" "§L/§M/§N launch no claude: no verb here reaches sessions.start."
# P-3 / `FI-32`: every evidence reference in the register is INSTANT-RELATIVE. The section code builds
# absolute paths (`$EV/...`) because that is what the commands need, and `it_pass` writes whatever cell it
# is handed — so the rewrite is done once, here, over the rows this run wrote. An absolute path in a
# results file is one reboot from an unbacked claim, and `bin/lint-evidence-paths.sh` fails the register
# for it. Relativising by hand after each run is the kind of step that gets skipped exactly once.
sed -i "s|$INSTANT/||g" "$RESULTS"

printf '\n== group 5 done; failures flagged: %s ==\n' "${IT_FAILED:-0}"
exit 0
