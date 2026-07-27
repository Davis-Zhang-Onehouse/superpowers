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

# scope enforcement: a single narrow round does not satisfy "all stages"
d=$(mkinstant inst-fmt READY 0 0 format)
python3 "$T/workspace-gate.py" "$d" --require-scope all >/dev/null 2>&1; chk "format-only round rejected by --require-scope all" 1 $?
# ...but stages covered ACROSS rounds do, with the newest round's verdict governing. R1=all followed
# by a narrow R2 follow-up is the normal shape of a re-review (live: r6 was R1=all, R2=alignment).
d=$(mkinstant inst-union READY 0 0 all)
{ echo; echo "## Round R2 — 2026-01-02 · trigger: pre-complete · scope: alignment"
  echo "## Round R2 summary — overall verdict: READY"
  echo "- Open findings: Critical 0 · Important 0 · Minor 0"; } >> "$d/REVIEW.md"
python3 "$T/workspace-gate.py" "$d" --require-scope all >/dev/null 2>&1
chk "a narrow follow-up round after a full round still satisfies --require-scope all" 0 $?
# three narrow rounds that together cover every stage also satisfy it
d=$(mkinstant inst-union3 READY 0 0 format)
for r in 2:alignment 3:code; do
  n=${r%%:*}; sc=${r##*:}
  { echo; echo "## Round R$n — 2026-01-0$n · trigger: pre-complete · scope: $sc"
    echo "## Round R$n summary — overall verdict: READY"
    echo "- Open findings: Critical 0 · Important 0 · Minor 0"; } >> "$d/REVIEW.md"
done
python3 "$T/workspace-gate.py" "$d" --require-scope all >/dev/null 2>&1
chk "format+alignment+code across rounds satisfies --require-scope all" 0 $?
# an unparseable scope should be visible rather than silently treated as satisfied
d=$(mkinstant inst-noscope READY 0 0)
python3 - "$d/REVIEW.md" <<'PYX'
import sys,re
p=sys.argv[1]; t=open(p).read()
open(p,"w").write(re.sub(r" · scope: \w+", "", t))
PYX
out=$(python3 "$T/workspace-gate.py" "$d" 2>&1)
echo "$out" | grep -qi "scope=unknown" && ok "reports an unparseable scope rather than assuming one" \
  || bad "silently assumed a scope"

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

# A multi-round REVIEW.md needs a per-round summary heading, and reviewers disambiguate the obvious
# way: "## Round R2 summary — overall verdict:". That must NOT be eaten as the start of a new round
# (coordinator RI-13). Both the plain and the numbered summary headings must parse.
d="$tmp/inst-multiround"; mkdir -p "$d"
{ echo "# X — REVIEW"; echo
  echo "## Round R2 — 2026-01-02 · trigger: pre-complete · scope: all"
  echo "### Stage 1 — Format (verdict: PASS)"; echo
  echo "## Round R2 summary — overall verdict: **READY**"
  echo "- Open findings: Critical 0 · Important 0 · Minor 0"; echo
  echo "## Round R1 — 2026-01-01 · trigger: on-demand · scope: all"; echo
  echo "## Round summary — overall verdict: NOT-READY"
  echo "- Open findings: Critical 1 · Important 0 · Minor 0"; } > "$d/REVIEW.md"
python3 "$T/workspace-gate.py" "$d" >/dev/null 2>&1
chk "numbered per-round summary heading parses (multi-round file)" 0 $?
out=$(python3 "$T/workspace-gate.py" "$d" 2>&1)
echo "$out" | grep -q "R2" && ok "picks the newest round (R2), not R1" || bad "picked the wrong round"
# and the newest round must still be able to FAIL
d="$tmp/inst-multiround-bad"; mkdir -p "$d"
{ echo "# X"; echo
  echo "## Round R2 — 2026-01-02 · trigger: pre-complete · scope: all"; echo
  echo "## Round R2 summary — overall verdict: NOT-READY"
  echo "- Open findings: Critical 1 · Important 0 · Minor 0"; echo
  echo "## Round R1 — 2026-01-01 · trigger: on-demand · scope: all"; echo
  echo "## Round summary — overall verdict: READY"
  echo "- Open findings: Critical 0 · Important 0 · Minor 0"; } > "$d/REVIEW.md"
python3 "$T/workspace-gate.py" "$d" >/dev/null 2>&1
chk "a newest-round NOT-READY still fails even if an older round was READY" 1 $?

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

# Prose must never front-run the ledger: an instant whose HANDOFF claims a review round that
# REVIEW.md does not contain is a narrative ahead of its evidence (worker R7 OI-8). But "R1" is also
# a MILESTONE name in efforts like this one, so only round-shaped phrasings may count.
d="$tmp/inst-claim"; mkdir -p "$d"
{ echo "# X — REVIEW"; echo; echo "## Round R1 — 2026-01-01 · trigger: pre-complete · scope: all"; echo
  echo "## Round summary — overall verdict: READY"
  echo "- Open findings: Critical 0 · Important 0 · Minor 0"; } > "$d/REVIEW.md"
printf '# H\n\nreview round R2 found three things.\n' > "$d/HANDOFF.md"
out=$(python3 "$T/workspace-gate.py" "$d" 2>&1)
echo "$out" | grep -qiE "claims .*R2|R2.*not in REVIEW|unbacked" && ok "flags a round claimed in prose but absent from the ledger" \
  || bad "silent about a claimed round with no ledger entry"
# a milestone called R2 must NOT be mistaken for a review round
printf '# H\n\nR2 delivered the velox raise batch; depends-on R1.\n' > "$d/HANDOFF.md"
out=$(python3 "$T/workspace-gate.py" "$d" 2>&1)
echo "$out" | grep -qiE "claims|unbacked" && bad "mistook a milestone name for a review round" \
  || ok "milestone names are not read as review rounds"
python3 "$T/workspace-gate.py" "$d" >/dev/null 2>&1
chk "the claim check is advisory, never changes the verdict" 0 $?

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

echo "== workspace-lint (presence, which content checks cannot see) =="
mkw(){ local d="$tmp/$1"; mkdir -p "$d"/{evidence,investigations,plans}
  for f in HANDOFF CHARTER RUNBOOK DECISIONS ISSUES ASSUMPTIONS; do
    printf '# %s\nUpdated: 2026-01-01 | Status: LIVE\n' "$f" > "$d/$f.md"; done
  : > "$d/evidence/INDEX.md"; echo "$d"; }
w=$(mkw inst-ok); python3 "$T/workspace-lint.py" "$w" >/dev/null 2>&1
chk "a complete instant passes" 0 $?
w=$(mkw inst-nohandoff); rm "$w/HANDOFF.md"
out=$(python3 "$T/workspace-lint.py" "$w" 2>&1); rc=$?
chk "a missing canonical file is a violation" 1 $rc
echo "$out" | grep -q "HANDOFF.md" && ok "names the missing file" || bad "did not name it"
# STATE.md is NOT canonical: dispatch-todo seeds one, but folding it into HANDOFF is legitimate and
# 4 of 8 live instants had done exactly that. Reporting it as a violation would chase a non-problem.
w=$(mkw inst-nostate); python3 "$T/workspace-lint.py" "$w" >/dev/null 2>&1
chk "a missing STATE.md is NOT a violation" 0 $?
python3 "$T/workspace-lint.py" "$w" 2>&1 | grep -qi "STATE.md" && ok "still mentions it as info" || bad "silent about it"
python3 "$T/workspace-lint.py" "$w" --require-state >/dev/null 2>&1
chk "--require-state makes it a violation when an effort wants it" 1 $?
w=$(mkw inst-nodir); rmdir "$w/plans"
python3 "$T/workspace-lint.py" "$w" >/dev/null 2>&1; chk "a missing canonical dir is a violation" 1 $?
w=$(mkw inst-noidx); rm "$w/evidence/INDEX.md"
python3 "$T/workspace-lint.py" "$w" >/dev/null 2>&1; chk "unindexed evidence is a violation" 1 $?
w=$(mkw inst-nohdr); printf '# ISSUES\nno header here\n' > "$w/ISSUES.md"
out=$(python3 "$T/workspace-lint.py" "$w" 2>&1); rc=$?
chk "a canonical file with no Updated/Status header is a violation" 1 $rc
echo "$out" | grep -qi "header" && ok "says which file lacks a header" || bad "unclear"

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

# A register that RENUMBERS its issues (I-1..I-7 -> OI-1..OI-7, which happened) must not re-report
# them all: the titles are unchanged, only the prefix moved.
printf '# ISSUES\n\n## I-1 — alpha thing\n\n## I-2 — beta thing\n' > "$ni"; rm -f "$st"
python3 "$T/new-issues.py" "$ni" --state "$st" >/dev/null 2>&1
printf '# ISSUES\n\n## OI-1 — alpha thing\n\n## OI-2 — beta thing\n' > "$ni"
out=$(python3 "$T/new-issues.py" "$ni" --state "$st" 2>&1); rc=$?
chk "renumbered issues with unchanged titles are not re-reported" 0 $rc
printf '# ISSUES\n\n## OI-1 — alpha thing\n\n## OI-2 — beta thing\n\n## OI-3 — gamma thing\n' > "$ni"
out=$(python3 "$T/new-issues.py" "$ni" --state "$st" 2>&1); rc=$?
chk "a genuinely new issue after a renumber still fires" 1 $rc
echo "$out" | grep -q "gamma" && ok "names only the new one" || bad "wrong issue named"

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

# If a baseline uploaded no results for some tests (a CI dim that produced no surefire — worker R3
# OI-7), the diff for those tests CANNOT run. Silently skipping them is the exact "absence read as
# absence of failure" error this tool exists to catch, so it must say what it could not compare.
mk lin_partial.tsv "a	PASS" "b	PASS"
out=$(python3 "$T/regression-check.py" --baseline "$tmp/base.tsv" --lineage-base "$tmp/lin_partial.tsv" \
        --current "$tmp/cur_clean.tsv" 2>&1); rc=$?
echo "$out" | grep -qiE "not comparable|uncomparable|coverage" \
  && ok "reports what it could NOT compare against the lineage base" \
  || bad "silently skipped tests the lineage base never covered"
echo "$out" | grep -qE "\bc\b|\bd\b" && ok "names the uncomparable tests" || bad "does not name them"
chk "a coverage gap alone is visible but not fatal by default" 0 $rc
python3 "$T/regression-check.py" --baseline "$tmp/base.tsv" --lineage-base "$tmp/lin_partial.tsv" \
  --current "$tmp/cur_clean.tsv" --strict-coverage >/dev/null 2>&1
chk "--strict-coverage makes an incomparable baseline fatal" 1 $?
# and a fully-covering lineage base reports no gap
out=$(python3 "$T/regression-check.py" --baseline "$tmp/base.tsv" --lineage-base "$tmp/lineage.tsv" \
        --current "$tmp/cur_clean.tsv" 2>&1)
echo "$out" | grep -qiE "not comparable: 0|coverage: complete" && ok "says coverage is complete when it is" \
  || bad "no positive statement of full coverage"

# A suite ADDED after the baseline that ships RED has no prior green to lose, so no diff can see it:
# a dim reports CLEAN while the suite fails completely. This is how a 5/5-failing validate suite
# reached ship-readiness (coordinator RI-15, found by R3). Absent + failing is NOT "unproven" — it is red.
mk cur_newred.tsv "a	PASS" "b	PASS" "c	PASS" "d	FAIL" "brandNewSuite.t1	FAIL" "brandNewSuite.t2	FAIL"
out=$(python3 "$T/regression-check.py" --baseline "$tmp/base.tsv" --lineage-base "$tmp/lineage.tsv" \
        --current "$tmp/cur_newred.tsv" 2>&1); rc=$?
chk "a newly-added suite shipping RED fails the check" 1 $rc
echo "$out" | grep -q "brandNewSuite.t1" && ok "names the unbaselined red tests" || bad "did not surface them"
# The tool CANNOT tell "added by this stack" from "existed but was never measured" (a dim that
# uploaded no surefire). Claiming NEW sends the reader after the wrong worker — say what is known.
echo "$out" | grep -qiE "no baseline covered|never measured|cannot tell" \
  && ok "states that it cannot tell newly-added from never-measured" \
  || bad "asserts the reds are NEW when it cannot know that"
echo "$out" | grep -qi "^CLEAN" && bad "still headlined CLEAN with a new suite failing" || ok "verdict is not CLEAN"
# a newly-added suite that is GREEN is merely new, not a failure
mk cur_newgreen.tsv "a	PASS" "b	PASS" "c	PASS" "d	FAIL" "brandNewSuite.t1	PASS"
python3 "$T/regression-check.py" --baseline "$tmp/base.tsv" --lineage-base "$tmp/lineage.tsv" \
  --current "$tmp/cur_newgreen.tsv" >/dev/null 2>&1
chk "a newly-added GREEN suite is not a failure" 0 $?
# documented red-red residuals need an escape hatch, but it must still be visible
out=$(python3 "$T/regression-check.py" --baseline "$tmp/base.tsv" --lineage-base "$tmp/lineage.tsv" \
        --current "$tmp/cur_newred.tsv" --allow-new-red 2>&1); rc=$?
chk "--allow-new-red downgrades it to a warning" 0 $rc
echo "$out" | grep -q "brandNewSuite.t1" && ok "still names them under --allow-new-red" || bad "went silent"

# OI-9: a round recording a VERDICT but no stage verdicts, findings or scope is a claim with no visible
# basis. Third instance (r2's unparseable scope, lift-01's empty round). Default pass/fail is unchanged —
# the ledger is still the arbiter — but silence about it would let an empty round look identical to a
# fully-evidenced one.
d="$tmp/inst-emptyround"; mkdir -p "$d"
{ echo "# X — REVIEW"; echo; echo "## Round R1 — 2026-01-01 · trigger: pre-complete"; echo
  echo "## Round summary — overall verdict: READY"; } > "$d/REVIEW.md"
out=$(python3 "$T/workspace-gate.py" "$d" 2>&1)
echo "$out" | grep -qiE "no stage|no findings|thin" && ok "flags a round with a verdict but no recorded stages" \
  || bad "an empty round reads the same as an evidenced one"
d=$(mkinstant inst-fullround READY 0 0 all)
out=$(python3 "$T/workspace-gate.py" "$d" 2>&1)
echo "$out" | grep -qiE "no stage|thin" && bad "warned about a round that DOES record a stage" \
  || ok "no warning when stages are recorded"

echo "== surefire-to-tsv (the adapter nobody should hand-roll) =="
sd="$tmp/surefire"; mkdir -p "$sd"
# the exact trap: hostname="..." precedes name="...", and 'hostname="' ENDS WITH 'name="'
cat > "$sd/TEST-org.example.MySuite.xml" <<'EOX'
<?xml version="1.0" encoding="UTF-8"?>
<testsuite errors="0" failures="1" hostname="8c3f2b1a9d4e" name="org.example.MySuite" tests="3">
  <testcase classname="org.example.MySuite" name="passes"/>
  <testcase classname="org.example.MySuite" name="fails"><failure message="boom">trace</failure></testcase>
  <testcase classname="org.example.MySuite" name="skips"><skipped/></testcase>
</testsuite>
EOX
out=$(python3 "$T/surefire-to-tsv.py" "$sd" 2>/dev/null)
echo "$out" | grep -q "org.example.MySuite::passes	PASS" && ok "suite name read from the name attribute" \
  || bad "wrong suite name (the hostname trap): $(echo "$out" | head -1)"
echo "$out" | grep -q "8c3f2b1a9d4e" && bad "captured the CI hostname as the suite name" || ok "hostname not captured"
echo "$out" | grep -q "MySuite::fails	FAIL" && ok "a <failure> becomes FAIL" || bad "failure not detected"
echo "$out" | grep -q "skips" && bad "a skipped test was emitted as a result" || ok "skipped omitted (not a result)"
python3 "$T/surefire-to-tsv.py" "$sd" --include-skipped 2>/dev/null | grep -q "skips	SKIP" \
  && ok "--include-skipped emits SKIP" || bad "--include-skipped did nothing"
python3 "$T/surefire-to-tsv.py" "$sd" --dim bv40 2>/dev/null | grep -q "bv40::org.example.MySuite::passes" \
  && ok "--dim qualifies names so dimensions are never collapsed" || bad "--dim did not qualify"
python3 "$T/surefire-to-tsv.py" "$tmp/nothing-here" >/dev/null 2>&1
chk "an empty extraction is an error, not an empty diff" 2 $?

# A discovery filter that skips files without saying so is the same silent drop as a bad regex
# (worker R3 OI-11 lost 43 rows per slow-dim extraction to a hand-rolled parser).
# NOT under a path containing "surefire" — otherwise the path heuristic matches and nothing is skipped
odd="$tmp/reports-slowdim"; mkdir -p "$odd"
cat > "$odd/results-slowdim.xml" <<'EOX'
<?xml version="1.0"?>
<testsuite hostname="h" name="org.example.SlowSuite" tests="1">
  <testcase classname="org.example.SlowSuite" name="slowtest"/>
</testsuite>
EOX
out=$(python3 "$T/surefire-to-tsv.py" "$odd" 2>&1)
echo "$out" | grep -qi "skipped\|not matched\|--all-xml" && ok "reports XML files it did not read" \
  || bad "silently skipped a non-TEST- prefixed XML"
python3 "$T/surefire-to-tsv.py" "$odd" --all-xml 2>/dev/null | grep -q "SlowSuite::slowtest" \
  && ok "--all-xml picks up differently-named reports" || bad "--all-xml did not include it"

echo "== regress semantics version (results must be self-describing) =="
python3 "$T/regression-check.py" --version 2>&1 | grep -qE "semantics|v[0-9]" \
  && ok "--version reports the semantics version" || bad "no version to cite"
out=$(python3 "$T/regression-check.py" --baseline "$tmp/base.tsv" --current "$tmp/cur_clean.tsv" 2>&1)
echo "$out" | grep -qE "semantics" && ok "every run stamps its semantics version" || bad "output is not self-describing"
python3 "$T/regression-check.py" --baseline "$tmp/base.tsv" --current "$tmp/cur_clean.tsv" --json 2>/dev/null \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("semantics_version"), "missing"; print("ok")' >/dev/null 2>&1 \
  && ok "json carries semantics_version" || bad "json lacks semantics_version"

echo "== regress input sanity =="
# A broken extractor makes the two files share NO names. That must not read as "coverage: complete".
mk lhs.tsv "hostA::t1	PASS" "hostA::t2	PASS"
mk rhs.tsv "hostB::t1	PASS" "hostB::t2	FAIL"
out=$(python3 "$T/regression-check.py" --baseline "$tmp/lhs.tsv" --current "$tmp/rhs.tsv" 2>&1); rc=$?
echo "$out" | grep -qi "coverage: complete" && bad "claimed complete coverage with ZERO shared names" \
  || ok "does not claim complete coverage when nothing matches"
echo "$out" | grep -qiE "overlap|shared|extraction" && ok "reports the name overlap" || bad "overlap not reported"
chk "zero overlap between baseline and current fails" 1 $rc

# A whole CI dimension can VANISH from the current run. With dim-qualified names the surviving dim
# still overlaps the baseline perfectly, so overlap looks fine and every current test is comparable —
# while 1001 baseline results simply stopped existing (coordinator RI-17). Coverage was only ever
# checked in one direction: current -> baseline. Absence in the OTHER direction is the FC-21 class.
mk base_2dim.tsv "bv40::s::t1	PASS" "bv40::s::t2	PASS" "bv41::s::t1	PASS" "bv41::s::t2	PASS"
mk cur_1dim.tsv "bv41::s::t1	PASS" "bv41::s::t2	PASS"
out=$(python3 "$T/regression-check.py" --baseline "$tmp/base_2dim.tsv" --current "$tmp/cur_1dim.tsv" 2>&1); rc=$?
echo "$out" | grep -qi "coverage: complete" && bad "claimed complete coverage while a whole dim vanished" \
  || ok "does not claim complete coverage when baseline results vanished"
echo "$out" | grep -qiE "vanish|missing|absent from the current" && ok "reports the vanished results" \
  || bad "silent about results that disappeared"
echo "$out" | grep -q "bv40" && ok "names the dimension that went missing" || bad "does not name the lost dim"
chk "a vanished dimension is visible but not fatal by default" 0 $rc
python3 "$T/regression-check.py" --baseline "$tmp/base_2dim.tsv" --current "$tmp/cur_1dim.tsv" \
  --strict-coverage >/dev/null 2>&1
chk "--strict-coverage makes a vanished dimension fatal" 1 $?
# a few individually-deleted tests are not a lost dimension
mk cur_minus1.tsv "bv40::s::t1	PASS" "bv41::s::t1	PASS" "bv41::s::t2	PASS"
out=$(python3 "$T/regression-check.py" --baseline "$tmp/base_2dim.tsv" --current "$tmp/cur_minus1.tsv" 2>&1)
echo "$out" | grep -qi "entire dimension" && bad "called one missing test a lost dimension" \
  || ok "one missing test is not reported as a lost dimension"

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
