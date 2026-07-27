#!/usr/bin/env bash
# Hermetic self-tests for workspace-gate.py, regression-check.py, coord-check.py.
# Path-independent. Prints PASS/FAIL; exits non-zero on any failure.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$here/.."
fail=0
ok(){ echo "  ok   - $1"; }
bad(){ echo "  FAIL - $1"; fail=1; }
chk(){ # chk <desc> <expected-rc> <actual-rc>
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (expected rc=$2, got rc=$3)"; fi; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

mkinstant(){ # mkinstant <name> <verdict> <crit> <imp> [scope] [round2block]
  local d="$tmp/$1"; mkdir -p "$d"
  { echo "# X — REVIEW"
    echo
    echo "## Round R1 — 2026-01-01 · trigger: pre-complete · scope: ${5:-all}"
    echo "### Stage 1 — Format & hygiene   (verdict: PASS)"
    echo
    echo "## Round summary — overall verdict: $2"
    echo "- Stage verdicts: format=PASS · alignment=ALIGNED · code=CLEAN"
    echo "- Open findings: Critical $3 · Important $4 · Minor 0"
  } > "$d/REVIEW.md"
  echo "$d"
}

echo "== workspace-gate =="
d=$(mkinstant inst-ready READY 0 0);            python3 "$T/workspace-gate.py" "$d" >/dev/null 2>&1; chk "READY passes" 0 $?
d=$(mkinstant inst-rwf READY-WITH-FIXES 0 0);   python3 "$T/workspace-gate.py" "$d" >/dev/null 2>&1; chk "READY-WITH-FIXES + 0 open passes" 0 $?
d=$(mkinstant inst-imp READY-WITH-FIXES 0 2);   python3 "$T/workspace-gate.py" "$d" >/dev/null 2>&1; chk "READY-WITH-FIXES + 2 Important fails" 1 $?
d=$(mkinstant inst-crit READY-WITH-FIXES 1 0);  python3 "$T/workspace-gate.py" "$d" >/dev/null 2>&1; chk "open Critical fails" 1 $?
d=$(mkinstant inst-nr NOT-READY 0 0);           python3 "$T/workspace-gate.py" "$d" >/dev/null 2>&1; chk "NOT-READY fails" 1 $?

mkdir -p "$tmp/inst-none";                      python3 "$T/workspace-gate.py" "$tmp/inst-none" >/dev/null 2>&1; chk "missing REVIEW.md fails closed (rc=2)" 2 $?
mkdir -p "$tmp/inst-bad"; echo "# nothing here" > "$tmp/inst-bad/REVIEW.md"
                                                python3 "$T/workspace-gate.py" "$tmp/inst-bad" >/dev/null 2>&1; chk "unparseable fails closed (rc=2)" 2 $?

# latest round wins: R1 READY then a newer R2 NOT-READY
d=$(mkinstant inst-multi READY 0 0)
{ echo; echo "## Round R2 — 2026-01-02 · trigger: pre-complete · scope: all"
  echo "## Round summary — overall verdict: NOT-READY"
  echo "- Open findings: Critical 1 · Important 0 · Minor 0"; } >> "$d/REVIEW.md"
python3 "$T/workspace-gate.py" "$d" >/dev/null 2>&1; chk "latest round wins (R2 NOT-READY)" 1 $?

# scope enforcement
d=$(mkinstant inst-fmt READY 0 0 format)
python3 "$T/workspace-gate.py" "$d" --require-scope all >/dev/null 2>&1; chk "format-only round rejected by --require-scope all" 1 $?

# harvest precondition: gate ok but folder not renamed complete
d=$(mkinstant 07180102-07190000-inflight-append-mrX READY 0 0)
python3 "$T/workspace-gate.py" "$d" --harvest >/dev/null 2>&1; chk "--harvest rejects an -inflight- folder" 1 $?
d=$(mkinstant 07180102-07190000-complete-append-mrX READY 0 0)
python3 "$T/workspace-gate.py" "$d" --harvest >/dev/null 2>&1; chk "--harvest accepts a -complete- folder" 0 $?

# Markdown emphasis is idiomatic and the template does not enforce bare text. A gate that cannot
# read a BOLD verdict fails a genuinely-READY worker (coordinator RI-11) — the worst direction for
# a gate to be wrong in, because it blocks correct work.
d="$tmp/inst-bold"; mkdir -p "$d"
{ echo "# X — REVIEW"; echo
  echo "## Round R1 — 2026-01-01 · trigger: pre-complete · scope: all"; echo
  echo "## Round summary — overall verdict: **READY**"
  echo "- **Open Critical: 0 · Open Important: 0 · Open Minor: 0**"; } > "$d/REVIEW.md"
python3 "$T/workspace-gate.py" "$d" >/dev/null 2>&1
chk "a BOLD verdict parses" 0 $?
d="$tmp/inst-bold-open"; mkdir -p "$d"
{ echo "# X"; echo; echo "## Round R1 — 2026-01-01 · trigger: pre-complete · scope: all"; echo
  echo "## Round summary — overall verdict: **READY-WITH-FIXES**"
  echo "- **Open Critical: 0 · Open Important: 2 · Open Minor: 1**"; } > "$d/REVIEW.md"
python3 "$T/workspace-gate.py" "$d" >/dev/null 2>&1
chk "bold open-counts are still counted (2 Important fails)" 1 $?
# A summary line that exists but cannot be parsed must SAY so — reporting it as absent sends the
# coordinator hunting for the wrong problem.
d="$tmp/inst-garbled"; mkdir -p "$d"
{ echo "# X"; echo; echo "## Round R1 — 2026-01-01 · trigger: pre-complete · scope: all"; echo
  echo "## Round summary — overall verdict: mostly fine I think"; } > "$d/REVIEW.md"
out=$(python3 "$T/workspace-gate.py" "$d" 2>&1); rc=$?
chk "an unparseable verdict fails closed" 2 $rc
echo "$out" | grep -qi "could not parse\|unparseable" && ok "says unparseable, not absent" \
  || bad "misdiagnoses an unparseable line as a missing one"

# Harvest must be RECORDED where a tool can see it, or every finished instant screams forever
# and a successor coordinator cannot tell owed work from history (coordinator RI-1 / RI-5).
export BOARD_DIR="$tmp/board"; mkdir -p "$BOARD_DIR/records"
d=$(mkinstant 07180102-07190000-complete-append-mrH READY 0 0)
cat > "$BOARD_DIR/records/mrh.json" <<EOF
{ "todo_id": "mrh", "child_instant": "$tmp/07180102-07190000-inflight-append-mrH",
  "base_instant": "/base/one", "tmux": "dt-mrh", "ws": "/ws", "slot": "ws9" }
EOF
python3 "$T/workspace-gate.py" "$d" --harvest --record >/dev/null 2>&1
chk "gate --harvest --record succeeds on a passing instant" 0 $?
grep -q harvested_at "$BOARD_DIR/records/mrh.json" && ok "harvest recorded into the board record" \
  || bad "harvest NOT recorded (successor coordinator still has to trust prose)"
grep -q '"gate_verdict": *"READY"' "$BOARD_DIR/records/mrh.json" && ok "gate verdict recorded" || bad "verdict not recorded"

# a FAILING gate must never mark something harvested
python3 - "$BOARD_DIR/records/mrh.json" <<'PYX'
import json,sys
p=sys.argv[1]; d=json.load(open(p))
d.pop("harvested_at",None); d.pop("gate_verdict",None); json.dump(d,open(p,"w"))
PYX
d2=$(mkinstant 07180102-07190001-complete-append-mrBad NOT-READY 0 0)
cat > "$BOARD_DIR/records/mrbad.json" <<EOF
{ "todo_id": "mrbad", "child_instant": "$tmp/07180102-07190001-inflight-append-mrBad",
  "base_instant": "/base/one", "tmux": "dt-mrbad", "ws": "/ws", "slot": "ws9" }
EOF
python3 "$T/workspace-gate.py" "$d2" --harvest --record >/dev/null 2>&1
chk "failing gate still fails with --record" 1 $?
grep -q harvested_at "$BOARD_DIR/records/mrbad.json" && bad "marked harvested despite a failed gate" \
  || ok "failed gate records nothing"
unset BOARD_DIR

echo "== regression-check =="
res(){ printf '%s\n' "$@"; }   # helper
mk(){ printf '%s\n' "${@:2}" > "$tmp/$1"; }
mk base.tsv "a	PASS" "b	PASS" "c	FAIL" "d	FAIL"
mk cur_clean.tsv "a	PASS" "b	PASS" "c	PASS" "d	FAIL"
python3 "$T/regression-check.py" --baseline "$tmp/base.tsv" --current "$tmp/cur_clean.tsv" >/dev/null 2>&1
chk "clean run passes" 0 $?
mk cur_reg.tsv "a	PASS" "b	FAIL" "c	FAIL" "d	FAIL"
python3 "$T/regression-check.py" --baseline "$tmp/base.tsv" --current "$tmp/cur_reg.tsv" >/dev/null 2>&1
chk "green->red vs baseline fails" 1 $?
out=$(python3 "$T/regression-check.py" --baseline "$tmp/base.tsv" --current "$tmp/cur_reg.tsv" 2>&1)
echo "$out" | grep -q "b" && ok "names the regressed test" || bad "did not name the regressed test"

# THE INVISIBLE CLASS: c was red@baseline, turned green by the lineage base, red again now.
mk lineage.tsv "a	PASS" "b	PASS" "c	PASS" "d	FAIL"
mk cur_rebreak.tsv "a	PASS" "b	PASS" "c	FAIL" "d	FAIL"
python3 "$T/regression-check.py" --baseline "$tmp/base.tsv" --current "$tmp/cur_rebreak.tsv" >/dev/null 2>&1
chk "re-break is INVISIBLE vs baseline alone (passes)" 0 $?
python3 "$T/regression-check.py" --baseline "$tmp/base.tsv" --lineage-base "$tmp/lineage.tsv" --current "$tmp/cur_rebreak.tsv" >/dev/null 2>&1
chk "re-break CAUGHT by the second diff" 1 $?

# assert-closed: registry says c is closed, current is red
mk closed.txt "c"
python3 "$T/regression-check.py" --baseline "$tmp/base.tsv" --current "$tmp/cur_rebreak.tsv" --closed-list "$tmp/closed.txt" >/dev/null 2>&1
chk "registry-closed row not green fails" 1 $?
python3 "$T/regression-check.py" --baseline "$tmp/base.tsv" --current "$tmp/cur_clean.tsv" --closed-list "$tmp/closed.txt" >/dev/null 2>&1
chk "registry-closed row green passes" 0 $?
# closed row missing from results entirely = coverage gap
mk closed2.txt "zzz"
python3 "$T/regression-check.py" --baseline "$tmp/base.tsv" --current "$tmp/cur_clean.tsv" --closed-list "$tmp/closed2.txt" >/dev/null 2>&1
chk "registry-closed row absent from results fails" 1 $?
# extract closed rows from a markdown registry
printf '| Test | Status |\n|---|---|\n| `c` | 🟩 CLOSED |\n| `d` | ⬛ OPEN |\n' > "$tmp/cat.md"
python3 "$T/regression-check.py" --baseline "$tmp/base.tsv" --current "$tmp/cur_rebreak.tsv" --closed-from-md "$tmp/cat.md" >/dev/null 2>&1
chk "closed rows parsed from markdown registry" 1 $?

echo "== new-issues (diff by ID, not by count) =="
ni="$tmp/ISSUES.md"; st="$tmp/seen.txt"
printf '# ISSUES\n\n## RI-1 — first\nbody\n\n## RI-2 — second\nbody\n' > "$ni"
out=$(python3 "$T/new-issues.py" "$ni" --state "$st" 2>&1); rc=$?
chk "first run reports everything as new" 1 $rc
echo "$out" | grep -q "RI-1" && echo "$out" | grep -q "RI-2" && ok "names both" || bad "missed one"
python3 "$T/new-issues.py" "$ni" --state "$st" >/dev/null 2>&1
chk "second run reports nothing new" 0 $?
# THE REAL BUG: a new entry inserted BEFORE the last one. Count grows, last heading unchanged.
printf '# ISSUES\n\n## RI-1 — first\nbody\n\n## RI-3 — third\nbody\n\n## RI-2 — second\nbody\n' > "$ni"
out=$(python3 "$T/new-issues.py" "$ni" --state "$st" 2>&1); rc=$?
chk "detects an entry inserted mid-file" 1 $rc
echo "$out" | grep -q "RI-3" && ok "names the actually-new issue" || bad "named the wrong issue"
echo "$out" | grep -q "RI-2" && bad "re-reported an old issue" || ok "does not re-report old issues"

# A restarted watcher must not re-alarm everything it already handled. Priming records current
# reality as "already seen" WITHOUT reporting it — the honest alternative to silently swallowing.
printf '# ISSUES\n\n## RI-1 — a\n\n## RI-2 — b\n' > "$ni"; rm -f "$st"
out=$(python3 "$T/new-issues.py" "$ni" --state "$st" --prime 2>&1); rc=$?
chk "--prime reports nothing on a fresh state" 0 $rc
echo "$out" | grep -qi "prim" && ok "says it primed, and how many" || bad "silent priming hides a reset"
python3 "$T/new-issues.py" "$ni" --state "$st" >/dev/null 2>&1
chk "after priming, existing issues are not re-reported" 0 $?
printf '# ISSUES\n\n## RI-1 — a\n\n## RI-3 — c\n\n## RI-2 — b\n' > "$ni"
out=$(python3 "$T/new-issues.py" "$ni" --state "$st" 2>&1); rc=$?
chk "a genuinely new issue after priming still fires" 1 $rc
echo "$out" | grep -q "RI-3" && ok "names it" || bad "missed the new issue"

echo "== coord-check =="
inst="$tmp/instants"; mkdir -p "$inst/07180102-07190000-complete-append-mrA" "$inst/07180102-07190001-inflight-append-mrB"
mkh(){ printf '# H\n\n## Live milestone registry\n| MR | Task | Disposition | Depends-on | Instant | Slot | Status | Proof |\n|---|---|---|---|---|---|---|---|\n%s\n' "$1" > "$tmp/HANDOFF.md"; }
mkh '| MR-A | a | port | — | `07180102-07190000-complete-append-mrA` | ws1 | ✅ done | ok |
| MR-B | b | port | — | `07180102-07190001-inflight-append-mrB` | ws2 | 🔵 running | ok |'
python3 "$T/coord-check.py" --handoff "$tmp/HANDOFF.md" --instants-dir "$inst" >/dev/null 2>&1
chk "registry in sync passes" 0 $?
# drift: registry says running, folder says complete (done-but-unharvested)
mkh '| MR-A | a | port | — | `07180102-07190000-complete-append-mrA` | ws1 | 🔵 running | ok |'
python3 "$T/coord-check.py" --handoff "$tmp/HANDOFF.md" --instants-dir "$inst" >/dev/null 2>&1
chk "done-but-unharvested drift caught" 1 $?
out=$(python3 "$T/coord-check.py" --handoff "$tmp/HANDOFF.md" --instants-dir "$inst" 2>&1)
echo "$out" | grep -qi "unharvested\|complete" && ok "explains the unharvested drift" || bad "drift message unclear"
# drift: registry says done, folder still inflight
mkh '| MR-B | b | port | — | `07180102-07190001-inflight-append-mrB` | ws2 | ✅ done | ok |'
python3 "$T/coord-check.py" --handoff "$tmp/HANDOFF.md" --instants-dir "$inst" >/dev/null 2>&1
chk "done-but-still-inflight drift caught" 1 $?
# drift: referenced instant does not exist
mkh '| MR-C | c | port | — | `07180102-07190009-inflight-append-ghost` | ws3 | 🔵 running | ok |'
python3 "$T/coord-check.py" --handoff "$tmp/HANDOFF.md" --instants-dir "$inst" >/dev/null 2>&1
chk "missing instant folder caught" 1 $?

# real-world: registries abbreviate long instant names with an ellipsis — must resolve, not false-positive
mkh '| MR-A | a | port | — | `07180102-07190000-complete-…mrA` | ws1 | ✅ done | ok |'
python3 "$T/coord-check.py" --handoff "$tmp/HANDOFF.md" --instants-dir "$inst" >/dev/null 2>&1
chk "ellipsis-abbreviated instant name resolves" 0 $?
mkh '| MR-A | a | port | — | `07180102-07190000-complete-...mrA` | ws1 | 🔵 running | ok |'
python3 "$T/coord-check.py" --handoff "$tmp/HANDOFF.md" --instants-dir "$inst" >/dev/null 2>&1
chk "ascii '...' abbreviation resolves (and still catches drift)" 1 $?
# real-world: non-instant placeholder cells must be skipped, not reported missing
mkh '| FINAL | f | compaction | — | (fires when MR-A and MR-B are done) | tbd | ⏳ PENDING | — |'
python3 "$T/coord-check.py" --handoff "$tmp/HANDOFF.md" --instants-dir "$inst" >/dev/null 2>&1
chk "placeholder (non-instant) cell skipped" 0 $?
# ambiguous abbreviation must not silently pass
mkdir -p "$inst/07180102-07190002-complete-append-mrAlt"
mkh '| MR-? | x | port | — | `07180102-…-complete-…` | ws1 | ✅ done | ok |'
python3 "$T/coord-check.py" --handoff "$tmp/HANDOFF.md" --instants-dir "$inst" >/dev/null 2>&1
chk "ambiguous abbreviation flagged" 1 $?

if [ $fail = 0 ]; then echo "PASS"; else echo "FAIL"; fi
exit $fail
