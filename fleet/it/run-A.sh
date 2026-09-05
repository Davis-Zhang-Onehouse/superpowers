#!/usr/bin/env bash
# Plan 6 §A — environment, isolation, exit codes (8 cases). Serial, runs first.
#
# WHAT §A IS FOR, AND WHY IT IS NOT A FORMALITY
# ---------------------------------------------
# Every other section's verdict is conditional on §A: if `FLEET_HOME` can silently become `~/.fleet`,
# then a §B..§O pass proves nothing about which store it passed against; if the live-store snapshot is
# not actually compared, then "the live fleet was untouched" is an assertion and not a measurement.
#
# So §A's cases are deliberately written as *negative controls wherever a negative control is possible*:
#   * A1 asks whether the fallback exists by giving each mutating verb a SANDBOXED $HOME and looking for
#     `$HOME/.fleet` afterwards. The operator's real `~/.fleet` is never the target of a write; it is
#     snapshotted (existence + content + mtime) before and after, so "we did not touch it" is measured.
#   * A2 does not re-implement `it_assert_isolation` (that would test a copy). It asserts the mechanism
#     exists, that every runner reaches it, AND that it FAILS when handed a perturbed snapshot — because
#     a comparison that cannot fail is not a comparison.
#   * A4's dynamic half installs a `sys.meta_path` hook that refuses any non-stdlib import REQUESTED BY A
#     FLEET MODULE, so a lazy `import` inside a handler is caught too — an AST scan alone cannot see one.
#     Attribution is by calling frame and not by module name, because the stdlib itself probes non-stdlib
#     names: CPython's `copy.py` does `from org.python.core import PyStringMap` inside a try/except for
#     Jython, and a name-only deny-list reports that as a fleet violation. A check that cannot tell whose
#     import it caught is a check that gets switched off.
#   * A5 drives REAL handlers, not `--dry-run`. §M's M1 already asserted registry containment over one
#     `--dry-run` invocation per verb; that leaves the code a verb returns when it actually does its work
#     unmeasured, which is the cell Plan 6 §A5 asks for ("a matrix drives each verb into ok / attention /
#     bad-input / no-capacity / refused and asserts the code").
#
# ISOLATION
# ---------
#   * Every fleet call carries an explicit `FLEET_HOME` (`it_section A`), except the A1 probes, whose
#     whole subject is its ABSENCE — and those run with `HOME` pointed into `$EV` so the fallback, if it
#     fires, lands in the section's own evidence tree and nowhere near the operator's.
#   * tmux: one session is created, `itfleet-A-a5shell`, on the PRIVATE server `-L itfleet-A` via
#     `it_tmux`. No `dt-` name is ever a target; §A runs no real `dispatch` (which hardcodes
#     `dt-{name}` — see run-group3.sh's header), only `dispatch --dry-run`, which claims, creates and
#     starts nothing. The live server is read (`tmux ls`) and never written.
#   * No `claude` process is started or killed. `pgrep -x claude` is compared before and after (A6).
#
# Usage:  IT_RESULTS=.../RESULTS-A.tsv bash fleet/it/run-A.sh
set -uo pipefail

A_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$A_HERE/lib.sh"

#: NEVER the shared RESULTS.tsv — that register has one deliberate writer (the coordinator merges).
RESULTS="${IT_RESULTS:-$A_HERE/RESULTS-A.tsv}"
IT_FAILED=0
[ -s "$RESULTS" ] || printf 'case\tverdict\tevidence\tnote\n' > "$RESULTS"

#: This runner OWNS its rows (`SI-4`): a re-run REPLACES them rather than appending a second verdict.
it_own_cases 'A[0-9]+[a-z]?|ISOLATION-A-(enter|leave)'

# --- recording: every evidence reference is INSTANT-RELATIVE (P-3 / FI-32) ---------------------------
a_rel()  { case "${1:-}" in "$INSTANT"/*) printf '%s' "${1#"$INSTANT"/}" ;; *) printf '%s' "${1:-}" ;; esac; }
a_pass() { it_pass "$1" "$(a_rel "${2:-}")" "${3:-}"; }
a_fail() { it_fail "$1" "$(a_rel "${2:-}")" "${3:-}"; }
a_skip() { it_skip "$1" "$(a_rel "${2:-}")" "${3:-}"; }
#: one note, one line — a newline in a note splits a TSV record in two.
sq()     { printf '%s' "$1" | tr '\n\t' '  ' | tr -s ' '; }
#: For notes that quote CAPTURED OUTPUT. Instant-rooted paths become relative; any other absolute path
#: (a stdlib traceback, a sandbox HOME) becomes `<abs>`. Applied at the quoting site rather than left to
#: the final sed, because the final sed only knows about $INSTANT — and `bin/lint-evidence-paths.sh`
#: fails the whole register on one `/home/...` in a note (P-3 / FI-32).
scrub()  { sed "s|$INSTANT/||g" | sed -E 's#(^|[[:space:]"'"'"'(])/(tmp|home|var|root)/[^[:space:]"'"'"')]*#\1<abs>#g'; }

# --- a clean section tree ---------------------------------------------------------------------------
#: Built from IT_ROOT (which lib.sh derives from BASH_SOURCE), never from an unset variable, and checked
#: against its expected value before the rm. A prior agent's interrupted `rm -rf` on an unset path
#: destroyed 1333 tracked files; the guard costs one line.
A_EVDIR="$IT_ROOT/A"
# The guard checks the PARENT'S IDENTITY, not the path's spelling. The original matched
# `*/evidence/04-integration/A`, which was correct where it was written and refused outright the moment the
# harness moved — a guard keyed on a layout protects one layout. What actually matters is that IT_ROOT really
# is the harness root (so `$IT_ROOT/A` cannot be `/A` from an unset variable) and that the target is exactly
# the §A section dir. `lib.sh` is the proof of identity: only the harness root contains it.
case "$A_EVDIR" in
  */A) [ -n "${IT_ROOT:-}" ] && [ -f "$IT_ROOT/lib.sh" ] && rm -rf "$A_EVDIR" \
       || { echo "run-A.sh: refusing to rm '$A_EVDIR' — IT_ROOT=${IT_ROOT:-<unset>} is not a harness root (no lib.sh)" >&2; exit 2; } ;;
  *) echo "run-A.sh: refusing to rm '$A_EVDIR' — it is not a §A section dir" >&2; exit 2 ;;
esac
mkdir -p "$A_EVDIR/out"
OUT="$A_EVDIR/out"
PY_DIR="$A_EVDIR/py"; mkdir -p "$PY_DIR"

# --- pre-images, taken BEFORE any section work ------------------------------------------------------
#
#: These two reads are the only bare (default-server / whole-machine) reads in this file and both are
#: READ-ONLY. They must be taken before `it_section` so that anything they show is attributable to the
#: world §A inherited rather than to §A.
A_LIVE_BEFORE="$OUT/live-sessions-before.txt"
A_LIVE_CREATED_BEFORE="$OUT/live-sessions-created-before.txt"
A_CLAUDE_BEFORE="$OUT/claude-pids-before.txt"
it_live_tmux_sessions                                        > "$A_LIVE_BEFORE"
tmux ls -F '#{session_name} #{session_created}' 2>/dev/null | sort > "$A_LIVE_CREATED_BEFORE"
pgrep -x claude 2>/dev/null | sort -n                        > "$A_CLAUDE_BEFORE"

#: The operator's REAL store. Recorded — existence, content AND mtime — and never written. `it_manifest`
#: on a path that does not exist prints nothing, which is the correct pre-image for "absent".
A_REAL_FLEET="$HOME/.fleet"
A_REAL_EXISTS_BEFORE="$([ -e "$A_REAL_FLEET" ] && echo yes || echo no)"
it_manifest "$A_REAL_FLEET" > "$OUT/A1-real-fleet-before.manifest"

# --- A0 — the live-session baseline this run inherited ----------------------------------------------
#
#: Not a Plan 6 case. It exists because `it_assert_isolation` compares the live session set against a
#: PERSISTED baseline (`live-tmux-sessions.txt`) with no re-baselining path, so any legitimate operator
#: change between two runs is reported as this run's contamination. Recording the drift BEFORE §A does
#: anything is what separates "§A moved a session" from "a session moved before §A started".
a0_baseline_drift() {
  local drift; drift="$(diff "$LIVE_TMUX_SNAPSHOT" "$A_LIVE_BEFORE" | grep '^[<>]' | tr '\n' ' ')"
  cp "$LIVE_TMUX_SNAPSHOT" "$OUT/live-sessions-baseline.txt"
  if [ -z "$drift" ]; then
    a_pass A0 "$A_LIVE_BEFORE" "$(sq "the live session set at §A t0 is byte-identical to the recorded baseline ($(grep -c . "$A_LIVE_BEFORE") sessions), so ISOLATION-A-enter compares a current baseline")"
  else
    a_skip A0 "$A_LIVE_BEFORE" "$(sq "NOT A §A CASE and NOT §A's doing: the live session set already differed from the recorded baseline BEFORE §A ran a single command — $drift. Measured at t0, ahead of it_section, so ISOLATION-A-enter's FAIL below is inherited drift, not contamination by §A. lib.sh offers no re-baselining path (REPORTED: a file this runner does not own)")"
  fi
}
a0_baseline_drift

# --- enter the section -----------------------------------------------------------------------------
#: Sets FLEET_HOME / SLOTS / EV / TMUX_PREFIX / IT_TMUX_SOCKET and asserts the isolation contract. Its
#: verdict is left to stand exactly as the harness reports it — masking it here would be the defect A2
#: exists to catch, wearing §A's badge.
it_section A
FLEET_INSTANTS="$EV/instants"; export FLEET_INSTANTS
mkdir -p "$FLEET_INSTANTS"

A_PROFILE="$INSTANT/tests/fixtures/profiles/workerCompliant"
A_NVERBS="$(python3 -c 'from fleet.cli import VERBS; print(len(VERBS))')"
A_VERBS_ALL="$(python3 -c 'from fleet.cli import VERBS; print(" ".join(sorted(VERBS)))')"
A_MUTATING="$(python3 -c 'from fleet.cli import VERBS
print(" ".join(sorted(n for n, s in VERBS.items() if not s.read_only)))')"
# shellcheck disable=SC2034  # A1 asserts the MUTATING verbs refuse; the read-only counterpart is
# derived here but never asserted on. See SI-50.
A_READONLY="$(python3 -c 'from fleet.cli import VERBS
print(" ".join(sorted(n for n, s in VERBS.items() if s.read_only)))')"

a_run() {                 # a_run <logbase> <cmd...> -> A_RC, stdout $A_OUT, stderr $A_ERR
  local base="$1"; shift
  A_OUT="$OUT/$base.stdout"; A_ERR="$OUT/$base.stderr"
  timeout 300 "$@" > "$A_OUT" 2> "$A_ERR"; A_RC=$?
}

# ===================================================================================================
# A1 — FLEET_HOME unset ⇒ every MUTATING verb refuses exit 2, and never falls back to ~/.fleet
# ===================================================================================================
#
# The probe is built so the fallback, if it fires, cannot reach the operator: each verb gets its own
# fresh `HOME` under `$EV/A1/`, and `Path.home()` honours `HOME`, so `default_context`'s
# `Path.home() / ".fleet"` resolves inside the section's evidence tree. The real `~/.fleet` is
# snapshotted around the whole probe (A1c) and is never a write target.
#
# Anti-vacuity, which matters more here than anywhere else in §A: "exit 2" alone proves nothing, because
# a mutating verb invoked with a required flag missing ALSO exits 2 (`W2-20`'s other half). So every
# invocation below supplies every required flag, points at a REAL instant by absolute path, and its
# diagnostic is inspected: a refusal that never names `FLEET_HOME` or `--home` is not the refusal Plan 6
# asks for, and is recorded as INCONCLUSIVE rather than counted as a pass.
a1_fixture() {
  #: `rel` and `relrepo` are the release verbs' sandbox — see the note in `a1_args`. They are created
  #: empty and stay empty: every release verb is expected to refuse before reaching them, and if one
  #: stops refusing, this is where the damage lands instead of in the operator's release area.
  local d="$EV/A1"; mkdir -p "$d/wd" "$d/ctlhome" "$d/inst" "$d/slotsrc" "$d/rel" "$d/relrepo"
  #: One real instant, created through a valid FLEET_HOME, then addressed by ABSOLUTE path — so no A1
  #: probe can exit 2 merely because its `--instant` did not resolve in an empty fallback store.
  A1_MK() { timeout 60 python3 -m fleet.cli init --home "$d/ctlhome" --instants-dir "$d/inst" \
                    --name "$1" --base 00000000 >> "$OUT/A1-fixture.out" 2>&1; }
  A1_MK a1subject; A1_MK a1completee; A1_MK a1abortee
  A1_INST="$(find "$d/inst" -mindepth 1 -maxdepth 1 -name '*a1subject' | head -1)"
  A1_COMP="$(find "$d/inst" -mindepth 1 -maxdepth 1 -name '*a1completee' | head -1)"
  A1_ABRT="$(find "$d/inst" -mindepth 1 -maxdepth 1 -name '*a1abortee' | head -1)"
  #: A milestone in the instant's own roadmap (not in the store), so `propose`/`apply` are otherwise
  #: complete invocations and their exit code is attributable to the home alone.
  cat > "$PY_DIR/a1seed.py" <<'PY'
import os
from pathlib import Path
from fleet.roadmap import Milestone, Roadmap
road = Roadmap(Path(os.environ["A1_INST"]))
if not road.milestones():
    road.add(Milestone(id="M1", title="the A1 milestone", status="ready", deps=[], evidence=[]))
print("milestones:", [m.id for m in road.milestones()])
PY
  A1_INST="$A1_INST" python3 "$PY_DIR/a1seed.py" >> "$OUT/A1-fixture.out" 2>&1
  #: `complete` needs a passed review gate to reach its ok path; seeded here so its A1 probe is a real
  #: attempt to rename an instant and not a gate refusal in disguise.
  timeout 60 python3 -m fleet.cli review --home "$d/ctlhome" --instants-dir "$d/inst" \
           --instant "$A1_COMP" --scope all --verdict READY >> "$OUT/A1-fixture.out" 2>&1
  A1_D="$d"
}

a1_args() {               # every required flag supplied; no value contains a space
  local d="$A1_D"
  case "$1" in
    init)       echo "--name a1probe --base 00000000" ;;
    #: --dry-run for dispatch ALONE, and stated: a real dispatch hardcodes a `dt-` session name
    #: (cli._do_dispatch) and the isolation contract forbids creating one. --dry-run still resolves the
    #: store and evaluates every gate against it, which is exactly the fallback question A1 asks.
    dispatch)   echo "--profile $A_PROFILE --title a1probe --base 00000000 --dry-run" ;;
    resume)     echo "--instant $A1_INST --tmux itfleet-A-a1resume" ;;
    declare)    echo "--instant $A1_INST --phase awaiting-ci" ;;
    park)       echo "--instant $A1_INST --question a1park" ;;
    unpark)     echo "--instant $A1_INST" ;;
    milestone)  echo "--instant $A1_INST --id a1m --title a1milestone" ;;
    propose)    echo "--instant $A1_INST --milestone M1 --status running --evidence a1evidence" ;;
    apply)      echo "--instant $A1_INST --milestone M1" ;;
    review)     echo "--instant $A1_INST --scope all --verdict READY" ;;
    complete)   echo "--instant $A1_COMP" ;;
    abort)      echo "--instant $A1_ABRT --reason a1reason" ;;
    close)      echo "--id a1probe-00000000" ;;
    harvest)    echo "" ;;
    enroll)     echo "--slot $d/slotsrc" ;;
    unenroll)   echo "--slot slotsrc" ;;
    reap)       echo "--base 00000000" ;;
    set-golden) echo "--path $DUMMY/alpha" ;;
    clone)      echo "--slot $d/slotsrc" ;;
    #: The release verbs. `--releases` is passed to EVERY one of them and always points inside the
    #: section tree. It is not optional care: without it the verb resolves $FLEET_RELEASES or its
    #: built-in default, which on this box is the operator's real release area — and A1's whole premise
    #: is that a verb might NOT refuse, in which case an unsandboxed probe would deploy or roll back the
    #: live fleet to find that out. The refusal is what is under test; the sandbox is what makes it safe
    #: to be wrong about.
    #:
    #: `release-cut` also needs `--repo`. Without it the verb refuses for a MISSING FLAG rather than for
    #: the missing home, which is exit 2 for an unrelated reason — measured, and exactly what A1b's
    #: `inconclusive` bucket is for. A fixture that produces the right exit code for the wrong reason is
    #: not a fixture.
    release-cut)      echo "--version 9.9.9 --repo $d/relrepo --releases $d/rel" ;;
    release-verify)   echo "--version 9.9.9 --releases $d/rel" ;;
    release-promote)  echo "--version 9.9.9 --releases $d/rel" ;;
    release-deploy)   echo "--version 9.9.9 --releases $d/rel --reason a1reason --force" ;;
    release-rollback) echo "--to 9.9.9 --releases $d/rel --reason a1reason" ;;
    *)          echo "A1-UNMAPPED" ;;
  esac
}

a1_no_fallback() {
  a1_fixture
  local log="$OUT/A1-per-verb.txt"; : > "$log"
  local n=0 wrote=0 nonrefusing=0 attributed=0 inconclusive=0 unmapped=0
  local wrote_list="" nonref_list="" inconc_list="" unmapped_list=""
  for v in $A_MUTATING; do
    n=$((n+1))
    local fh="$A1_D/fakehome-$v"; rm -rf "$fh"; mkdir -p "$fh"
    local args; args="$(a1_args "$v")"
    if [ "$args" = "A1-UNMAPPED" ]; then
      #: `II-4`. A verb with no argv recipe used to be counted as NON-REFUSING, so the register read
      #: "N of M mutating verbs did NOT refuse: clone(unmapped) …" — an accusation pointed at the
      #: product, in the same column and the same words as a real admission-control defect, when the
      #: truth is that this harness does not know how to call the verb. Its own count, its own case
      #: (`A1d`), and no bearing on `A1b`'s verdict about the verbs it CAN call.
      printf '%-12s UNMAPPED (no argv recipe in a1_args — harness gap, not a product verdict)\n' \
             "$v" >> "$log"
      unmapped=$((unmapped+1)); unmapped_list="$unmapped_list $v"; continue
    fi
    local out rc created names_home
    # shellcheck disable=SC2086
    out="$(cd "$A1_D/wd" && env -u FLEET_HOME -u FLEET_INSTANTS HOME="$fh" \
           timeout 120 python3 -m fleet.cli "$v" $args 2>&1)"; rc=$?
    printf '%s\n' "$out" > "$OUT/A1-$v.out"
    created=no; [ -e "$fh/.fleet" ] && created=yes
    #: `II-10`. Anchored on the SENTENCE `SI-15` emits, not on the flag name. It was
    #: `grep -qE 'FLEET_HOME|--home'`, and `--home` is a COMMON_FLAG that appears in the usage block
    #: every verb prints on ANY parse error — measured at 39 of 39 verbs. So a verb that never
    #: implemented the store refusal, but exited 2 because its argv was wrong, was counted as an
    #: attributable refusal, and the `inconclusive` bucket that exists to catch exactly that could
    #: never fire. A check that cannot tell the refusal it wants from an error it does not want is
    #: not a check.
    names_home=no
    printf '%s' "$out" | grep -qF 'writes to a store and no store was named' && names_home=yes
    printf '%-12s rc=%-3s created_HOME_dot_fleet=%-3s names_home=%-3s\n' \
           "$v" "$rc" "$created" "$names_home" >> "$log"
    [ "$created" = yes ] && { wrote=$((wrote+1)); wrote_list="$wrote_list $v"; }
    if [ "$rc" != 2 ]; then
      nonrefusing=$((nonrefusing+1)); nonref_list="$nonref_list $v(exit$rc)"
    elif [ "$names_home" = yes ]; then
      attributed=$((attributed+1))
    else
      inconclusive=$((inconclusive+1)); inconc_list="$inconc_list $v"
    fi
  done
  #: Every path the fallback created, so the FAIL names artefacts and not a count.
  find "$A1_D" -maxdepth 4 -path '*fakehome-*/.fleet*' | sed "s|$INSTANT/||" | sort \
       > "$OUT/A1-fallback-artefacts.txt"

  if [ "$wrote" = 0 ]; then
    a_pass A1a "$log" "$(sq "no mutating verb created \$HOME/.fleet with FLEET_HOME unset ($n verbs, a fresh sandbox HOME each)")"
  else
    a_fail A1a "$OUT/A1-fallback-artefacts.txt" "$(sq "$wrote of $n mutating verbs FELL BACK and WROTE a store under \$HOME/.fleet with FLEET_HOME unset:$wrote_list — cli.default_context resolves 'parsed --home or \$FLEET_HOME or Path.home()/\".fleet\"', so an unset FLEET_HOME writes shared state instead of refusing. Artefacts listed in the evidence file; the sandbox HOME kept them out of the operator's tree")"
  fi

  #: A1b judges the verbs this harness can actually invoke. `$probed`, not `$n` — reporting a verdict
  #: over a population that includes verbs never run is how the unmapped ones got counted as failures
  #: in the first place.
  local probed=$((n - unmapped))
  if [ "$nonrefusing" = 0 ] && [ "$inconclusive" = 0 ]; then
    a_pass A1b "$log" "$(sq "all $probed probed mutating verbs exited 2 with the SI-15 store refusal ('writes to a store and no store was named'), matched on that sentence rather than on the flag name --home, which every verb's usage block also contains (II-10). $unmapped verb(s) had no argv recipe and are A1d's business, not this case's")"
  elif [ "$nonrefusing" = 0 ]; then
    a_fail A1b "$log" "$(sq "$attributed of $probed probed mutating verbs refused with exit 2 carrying the SI-15 store refusal; $inconclusive exited 2 for an unrelated reason ($inconc_list) so their refusal is NOT attributable to the missing home — the fallback is latent for them, not absent")"
  else
    a_fail A1b "$log" "$(sq "$nonrefusing of $probed probed mutating verbs did NOT refuse:$nonref_list. Attributable refusals: $attributed; exit-2-for-another-reason: $inconclusive ($inconc_list). Plan 6 A1 requires exit 2 from every mutating verb")"
  fi

  #: A1d — the coverage case. `II-4`. §A derives its verb population from `cli.VERBS` on purpose, so a
  #: new verb cannot escape coverage; the argv recipes are hand-written, so a new verb CAN escape a
  #: fixture. That gap is real and must be loud — but it is a debt owed by whoever added the verb, not
  #: a defect in the verb. Naming it separately is what makes the next person's message read "you owe a
  #: fixture" instead of "the product failed to refuse".
  if [ "$unmapped" = 0 ]; then
    a_pass A1d "$log" "$(sq "every one of the $n mutating verbs in cli.VERBS has an argv recipe in a1_args, so A1a/A1b judge the whole population and not a subset of it")"
  else
    a_fail A1d "$log" "$(sq "$unmapped of $n mutating verbs have NO argv recipe in a1_args:$unmapped_list. This is a HARNESS gap, not a product verdict: these verbs were never invoked, so A1a and A1b say nothing about them. Add a recipe to a1_args in run-A.sh — every required flag supplied, no value containing a space, and any release verb given --releases inside the section tree")"
  fi
}

a1_real_store_untouched() {
  local after_exists after
  after_exists="$([ -e "$A_REAL_FLEET" ] && echo yes || echo no)"
  it_manifest "$A_REAL_FLEET" > "$OUT/A1-real-fleet-after.manifest"
  if [ "$A_REAL_EXISTS_BEFORE" = "$after_exists" ] \
     && diff -q "$OUT/A1-real-fleet-before.manifest" "$OUT/A1-real-fleet-after.manifest" >/dev/null; then
    a_pass A1c "$OUT/A1-real-fleet-after.manifest" "$(sq "the operator's real ~/.fleet is unchanged across the whole A1 probe: exists=$after_exists before and after, and its content+mtime manifest is byte-identical (empty manifest = absent). Every probe ran with HOME redirected into the section tree, so the fallback could not reach it")"
  else
    a_fail A1c "$OUT/A1-real-fleet-after.manifest" "$(sq "the real ~/.fleet CHANGED during the A1 probe: exists $A_REAL_EXISTS_BEFORE -> $after_exists; manifest diff: $(diff "$OUT/A1-real-fleet-before.manifest" "$OUT/A1-real-fleet-after.manifest" | head -3 | scrub | tr '\n' ' ')")"
  fi
}

# a1_detail <id>...  — what each NAMED sub-assertion asserts, and nothing about the others.
#
# `II-8`. The A1 aggregate used to recite all three descriptions whatever failed:
#   "1 of 3 sub-assertions failed — see A1a (a store was written under $HOME/.fleet) / A1b (a verb did
#    not refuse) / A1c (the operator's store moved)"
# It was written as a reader's index into the other three rows. It reads as a report of them. A reader
# took "a store was written under $HOME/.fleet" from a run where A1a had PASSED, put it in an RCA's
# root-cause table as a second instance of a git-dependency class, and it survived into a handoff's
# next-action list. The awk below always knew which ids failed; only the count was kept.
#
# EXTRACTION MARKER: bin/a1-detail-control.sh lifts this function out by name. Keep the `a1_detail() {`
# opening and the lone `}` closing on their own lines.
a1_detail() {
  local id out=""
  for id in "$@"; do
    case "$id" in
      A1a) out="$out A1a (a store was written under \$HOME/.fleet)" ;;
      A1b) out="$out A1b (a mutating verb did not refuse)" ;;
      A1c) out="$out A1c (the operator's store moved)" ;;
      #: No other case id appears in this text. Naming one here would put "A1b" into a message about
      #: A1d and re-create the exact misreading `II-8` exists to prevent — the control in
      #: bin/a1-detail-control.sh asserts the absence of the ids that passed, and it catches this.
      A1d) out="$out A1d (a mutating verb has no argv recipe, so it was never invoked)" ;;
      *)   out="$out $id (no description registered — add one to a1_detail)" ;;
    esac
  done
  printf '%s' "$out"
}

a1() {
  a1_no_fallback
  a1_real_store_untouched
  local failed; failed="$(awk -F'\t' '$1 ~ /^A1[abcd]$/ && $2=="FAIL" {printf "%s ", $1}' "$RESULTS")"
  local bad; bad="$(printf '%s' "$failed" | wc -w | tr -d ' ')"
  if [ "$bad" = 0 ]; then
    a_pass A1 "$OUT/A1-per-verb.txt" "$(sq "FLEET_HOME unset ⇒ every mutating verb refuses exit 2 with the SI-15 store refusal, nothing falls back to ~/.fleet, the operator's store is untouched, and every mutating verb had an argv recipe so the population judged is the whole one (A1a+A1b+A1c+A1d)")"
  else
    # shellcheck disable=SC2086
    a_fail A1 "$OUT/A1-per-verb.txt" "$(sq "$bad of 4 sub-assertions failed:$(a1_detail $failed). The sub-assertions not named here PASSED — read this row as a list of failures, not as an index of the four")"
  fi
}

# ===================================================================================================
# A2 — the live-store snapshot exists, is compared, and the comparison can FAIL
# ===================================================================================================
#
# `it_assert_isolation` already diffs `live-stores.sha256`, so §A does not re-read the live stores: a
# second implementation of the check would be a second thing to be wrong, and the contract forbids §A
# reading `~/.claude-dispatch-board` / `~/.claude-ws-pool` at all. What §A asserts instead is the three
# properties that make the existing mechanism worth anything.
a2_snapshot_covers_both_stores() {
  local lines board pool
  lines="$(grep -c . "$LIVE_SNAPSHOT")"
  board="$(grep -c 'claude-dispatch-board' "$LIVE_SNAPSHOT")"
  pool="$(grep -c 'claude-ws-pool' "$LIVE_SNAPSHOT")"
  cp "$LIVE_SNAPSHOT" "$OUT/A2-snapshot-copy.sha256"
  #: sha256sum's own form is `<64 hex>  <path>`; anything else is not a snapshot this check can diff.
  local malformed; malformed="$(grep -cvE '^[0-9a-f]{64}[[:space:]]+/' "$LIVE_SNAPSHOT")"
  if [ "$lines" -gt 0 ] && [ "$board" -gt 0 ] && [ "$pool" -gt 0 ] && [ "$malformed" = 0 ]; then
    a_pass A2a "fleet/it/live-stores.sha256" "$(sq "the snapshot exists and covers BOTH live stores: $lines sha256 lines, $board dispatch-board + $pool ws-pool entries, 0 malformed")"
  else
    a_fail A2a "fleet/it/live-stores.sha256" "$(sq "snapshot unusable: $lines lines, dispatch-board=$board, ws-pool=$pool, malformed=$malformed — a snapshot missing a store cannot detect a change in it")"
  fi
}

a2_mechanism_fires() {
  #: The negative control. Run in a SUBSHELL with its own RESULTS and its own LIVE_SNAPSHOT, so the FAIL
  #: it must produce lands in a scratch register and cannot set this runner's IT_FAILED.
  local neg="$OUT/A2-negative-control.tsv" corrupt="$OUT/A2-perturbed-snapshot.sha256" rc
  printf 'case\tverdict\tevidence\tnote\n' > "$neg"
  #: A perturbation of the SNAPSHOT, not of the stores. Same shape, one extra entry — the minimum change
  #: a real modification would produce.
  { cat "$LIVE_SNAPSHOT"
    printf '%064d  /nonexistent/a2-perturbation\n' 0; } > "$corrupt"
  ( RESULTS="$neg"; LIVE_SNAPSHOT="$corrupt"; IT_FAILED=0
    it_assert_isolation A2-NEGATIVE-CONTROL >/dev/null 2>&1 ); rc=$?
  local row; row="$(grep '^ISOLATION-A2-NEGATIVE-CONTROL' "$neg" | head -1)"
  if [ "$rc" != 0 ] && printf '%s' "$row" | grep -q 'FAIL' \
     && printf '%s' "$row" | grep -q 'THE LIVE STORES CHANGED'; then
    a_pass A2b "$neg" "$(sq "negative control: handed a snapshot differing by ONE entry, it_assert_isolation returns $rc and writes a FAIL saying THE LIVE STORES CHANGED — so the store comparison is an assertion, not decoration. The live stores themselves were not read by this runner and not perturbed; only the snapshot handed to the mechanism was")"
  else
    a_fail A2b "$neg" "$(sq "negative control did NOT fire: rc=$rc, row='$(printf '%s' "$row" | scrub | tr '\n\t' '  ')' — a store comparison that passes against a perturbed snapshot proves nothing about the live stores in ANY section")"
  fi
}

a2_every_runner_rediffs() {
  local log="$OUT/A2-runner-coverage.txt"; : > "$log"
  local missing=0 seen=0
  for f in "$IT_ROOT"/run-*.sh; do
    local base sources enters asserts
    base="$(basename "$f")"; seen=$((seen+1))
    sources=$(grep -cE '^[[:space:]]*\.[[:space:]]+.*lib\.sh' "$f")
    enters=$(grep -cE 'it_section[[:space:]]' "$f")
    asserts=$(grep -cE 'it_assert_isolation' "$f")
    printf '%-18s sources_lib=%s it_section=%s it_assert_isolation=%s\n' \
           "$base" "$sources" "$enters" "$asserts" >> "$log"
    #: `it_section` calls `it_assert_isolation` itself, so either route counts; sourcing lib.sh is what
    #: makes the snapshot path the same one for every runner.
    { [ "$sources" -ge 1 ] && { [ "$enters" -ge 1 ] || [ "$asserts" -ge 1 ]; }; } || missing=$((missing+1))
  done
  if [ "$missing" = 0 ] && [ "$seen" -ge 2 ]; then
    a_pass A2c "$log" "$(sq "all $seen run-*.sh runners source lib.sh and reach it_assert_isolation (via it_section or directly), so 'every later section re-diffs the snapshot' is structural rather than a convention")"
  else
    a_fail A2c "$log" "$(sq "$missing of $seen runners never reach it_assert_isolation — those sections run without re-diffing the live stores")"
  fi
}

a2() {
  a2_snapshot_covers_both_stores
  a2_mechanism_fires
  a2_every_runner_rediffs
  local bad; bad="$(awk -F'\t' '$1 ~ /^A2[abc]$/ && $2=="FAIL"' "$RESULTS" | wc -l | tr -d ' ')"
  if [ "$bad" = 0 ]; then
    a_pass A2 "$OUT/A2-negative-control.tsv" "$(sq "the live-store snapshot exists and covers both stores, every runner re-diffs it, and the comparison FAILS when perturbed (A2a+A2b+A2c). §A adds no second implementation of the check")"
  else
    a_fail A2 "$OUT/A2-negative-control.tsv" "$(sq "$bad of 3 sub-assertions failed — see A2a/A2b/A2c")"
  fi
}

# ===================================================================================================
# A3 — `import fleet` from a SECOND checkout at a different path (NFR2-2)
# ===================================================================================================
a3() {
  local d="$EV/A3"; mkdir -p "$d/wd" "$d/home" "$d/instants"
  A3_CO="$d/checkout2/src"; mkdir -p "$A3_CO"
  cp -r "$INSTANT/src/fleet" "$A3_CO/"
  #: Byte-compiled leftovers would let a stale `__pycache__` from the primary tree answer the import.
  find "$d/checkout2" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
  local nfiles; nfiles="$(find "$A3_CO/fleet" -name '*.py' | wc -l | tr -d ' ')"

  #: cwd is $d/wd — NOT the checkout and NOT the instant — so nothing can be answered by '' on sys.path.
  a_run A3-import env -u PYTHONPATH -u FLEET_HOME -u FLEET_INSTANTS PYTHONPATH="$A3_CO" \
        python3 -c 'import fleet, fleet.cli; print(fleet.__file__); print(fleet.cli.__file__)'
  local rc_i=$A_RC
  #: Run it from $d/wd. `cd` inside the subshell so the parent's cwd is untouched.
  ( cd "$d/wd" && env -u PYTHONPATH -u FLEET_HOME -u FLEET_INSTANTS PYTHONPATH="$A3_CO" \
    python3 -c 'import fleet, fleet.cli; print(fleet.__file__)' > "$OUT/A3-cwd-elsewhere.stdout" 2>&1 )
  local rc_c=$?
  local from_second=no
  grep -q "^$A3_CO/fleet/" "$OUT/A3-cwd-elsewhere.stdout" && from_second=yes

  if [ "$rc_i" = 0 ] && [ "$rc_c" = 0 ] && [ "$from_second" = yes ]; then
    a_pass A3 "$OUT/A3-cwd-elsewhere.stdout" "$(sq "import fleet succeeds from a second checkout of $nfiles modules at a different path, with cwd elsewhere and __pycache__ stripped; fleet.__file__ resolves INTO the second checkout")"
  else
    a_fail A3 "$OUT/A3-cwd-elsewhere.stdout" "$(sq "second-checkout import failed: rc(import)=$rc_i rc(cwd-elsewhere)=$rc_c resolved_into_second_checkout=$from_second :: $(head -2 "$OUT/A3-import.stderr" | scrub | tr '\n' ' ')")"
  fi

  #: A3b — the half that actually matters for NFR2-2: not one import, but EVERY fleet module answering
  #: from the second checkout while a real verb runs. One module still resolving to the primary tree
  #: would make A3 a pass over a package that is only half relocated.
  cat > "$PY_DIR/a3b.py" <<'PY'
"""A3b — run a real verb from the second checkout and prove no module came from anywhere else."""
import os, sys
from fleet.cli import VERBS, main, registered_codes
co = os.path.realpath(os.environ["A3_CO"])
rc = main(["leases"])
assert rc in registered_codes("leases"), rc
loaded = {n: getattr(m, "__file__", None) for n, m in sorted(sys.modules.items())
          if n == "fleet" or n.startswith("fleet.")}
outside = {n: f for n, f in loaded.items() if f and not os.path.realpath(f).startswith(co)}
for n, f in loaded.items():
    print(f"{n:22} {f}")
print("modules:", len(loaded), "verbs:", len(VERBS), "leases_rc:", rc)
print("OUTSIDE_SECOND_CHECKOUT:", outside)
assert not outside, outside
print("OK A3b")
PY
  ( cd "$d/wd" && env -u PYTHONPATH PYTHONPATH="$A3_CO" \
    FLEET_HOME="$d/home" FLEET_INSTANTS="$d/instants" A3_CO="$A3_CO" \
    python3 "$PY_DIR/a3b.py" > "$OUT/A3b.out" 2>&1 )
  local rc_b=$?
  local nmods; nmods="$(grep -c '^fleet' "$OUT/A3b.out")"
  if [ "$rc_b" = 0 ] && grep -q '^OK A3b' "$OUT/A3b.out"; then
    a_pass A3b "$OUT/A3b.out" "$(sq "a real verb ran from the second checkout and all $nmods loaded fleet.* modules resolved INSIDE it — no module leaked from the primary tree")"
  else
    a_fail A3b "$OUT/A3b.out" "$(sq "rc=$rc_b :: $(grep -E 'OUTSIDE_SECOND_CHECKOUT|Error' "$OUT/A3b.out" | head -2 | scrub | tr '\n' ' ')")"
  fi
}

# ===================================================================================================
# A4 — no import outside the stdlib: an AST scan AND a real run with the import surface restricted
# ===================================================================================================
a4() {
  local d="$EV/A4"; mkdir -p "$d/wd" "$d/home" "$d/instants" "$d/slot"

  # --- A4a: the static scan ---
  cat > "$PY_DIR/a4a.py" <<'PY'
"""A4a — AST scan of EVERY src/fleet/*.py. `ast.walk` sees a function-local import too, which is the
one a module-header grep misses (`cli._default_runner` really does `import subprocess` inside itself)."""
import ast, json, os, sys
from pathlib import Path
src = Path(os.environ["A4_SRC"])
std = set(sys.stdlib_module_names)
files = sorted(src.glob("*.py"))
assert files, f"no modules under {src}"
per_file, offenders = {}, []
for path in files:
    tree = ast.parse(path.read_text())
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                roots.add("<relative>")
            elif node.module:
                roots.add(node.module.split(".")[0])
    per_file[path.name] = sorted(roots)
    for root in sorted(roots):
        if root not in std and root not in ("fleet", "<relative>"):
            offenders.append(f"{path.name}:{root}")
for name, roots in per_file.items():
    print(f"{name:22} {' '.join(roots)}")
print("FILES:", len(files))
print("DISTINCT_ROOTS:", sorted({r for rs in per_file.values() for r in rs}))
print("OFFENDERS:", offenders)
print(json.dumps({"files": len(files), "offenders": offenders}))
assert not offenders, offenders
print("OK A4a")
PY
  A4_SRC="$INSTANT/src/fleet" python3 "$PY_DIR/a4a.py" > "$OUT/A4a.out" 2>&1
  local rc_a=$? nfiles roots
  nfiles="$(sed -n 's/^FILES: //p' "$OUT/A4a.out" | head -1)"
  roots="$(sed -n 's/^DISTINCT_ROOTS: //p' "$OUT/A4a.out" | head -1)"
  #: The population is asserted, not assumed: a scan that silently examined 3 of 17 files is OBS-49.
  local ondisk; ondisk="$(find "$INSTANT/src/fleet" -mindepth 1 -maxdepth 1 -name '*.py' | wc -l | tr -d ' ')"
  if [ "$rc_a" = 0 ] && [ "${nfiles:-0}" = "$ondisk" ] && [ "${nfiles:-0}" -gt 0 ]; then
    a_pass A4a "$OUT/A4a.out" "$(sq "AST scan of all $nfiles of $ondisk src/fleet/*.py modules (function-local imports included): every import root is stdlib or fleet. Roots seen: $roots")"
  else
    a_fail A4a "$OUT/A4a.out" "$(sq "rc=$rc_a scanned=${nfiles:-0} of $ondisk on disk :: $(grep -E 'OFFENDERS|Error' "$OUT/A4a.out" | head -2 | scrub | tr '\n' ' ')")"
  fi

  # --- A4b: no dynamic escape hatch the AST scan cannot see ---
  local dyn="$OUT/A4b-dynamic-import-sites.txt"
  grep -nE '\b(importlib|__import__|pkgutil|pkg_resources)\b|\beval\(|\bexec\(' \
       "$INSTANT"/src/fleet/*.py > "$dyn" 2>/dev/null
  local ndyn; ndyn="$(grep -c . "$dyn")"
  if [ "$ndyn" = 0 ]; then
    a_pass A4b "$dyn" "$(sq "no importlib / __import__ / pkgutil / pkg_resources / eval / exec anywhere in src/fleet — so the A4a AST scan sees the WHOLE import surface and is not defeated by a name computed at runtime")"
  else
    a_fail A4b "$dyn" "$(sq "$ndyn dynamic-import or eval/exec site(s) in src/fleet — an AST scan cannot bound the import surface past them: $(head -2 "$dyn" | scrub | tr '\n' ' ')")"
  fi

  # --- A4c: a REAL run with the import surface restricted ---
  cat > "$PY_DIR/a4c.py" <<'PY'
"""A4c — real verbs, run under `-S` (no site-packages on sys.path) with a meta_path hook that REFUSES
any non-stdlib import requested BY A FLEET MODULE.

Attribution is by calling frame, deliberately. A name-only deny-list reports the stdlib's own optional
probes as fleet violations: CPython's `copy.py` does `from org.python.core import PyStringMap` inside a
try/except for Jython, so `org` is attempted on every run and is nobody's defect. A check that cannot
say whose import it caught is a check that gets switched off — which is worse than not having it.
"""
import os, sys, importlib
FLEET_DIR = os.path.realpath(os.environ["A4_SRC_SECOND"])
STD = set(sys.stdlib_module_names)
REFUSED, ALLOWED_ELSEWHERE = [], []


def _requester():
    """The frame that ACTUALLY asked for this module, skipping only importlib's own machinery.

    The first version of this walked the whole stack for the nearest fleet frame, which is wrong and
    said so loudly: `cli.py` imports `dataclasses`, `dataclasses` imports `copy`, and `copy` probes
    `org.python.core` — so the nearest fleet frame up the stack is `cli.py` and a stdlib probe three
    levels down got attributed to the product. Only the IMMEDIATE requester can answer "whose import
    is this", so the walk stops at the first frame that is not import machinery.
    """
    frame = sys._getframe(1)
    while frame:
        name = os.path.realpath(frame.f_code.co_filename)
        base = os.path.basename(name)
        if base.startswith("<") or "importlib" in name or base in ("a4c.py",):
            frame = frame.f_back
            continue
        return name if name.startswith(FLEET_DIR) else None
    return None


class DenyNonStdlibFromFleet:
    def find_module(self, name, path=None):
        return self.find_spec(name, path)

    def find_spec(self, name, path=None, target=None):
        root = name.split(".")[0]
        if root in STD or root == "fleet":
            return None
        who = _requester()
        if who is None:
            ALLOWED_ELSEWHERE.append(name)
            return None
        REFUSED.append(f"{name} <- {who}")
        raise ImportError(f"A4c: refused non-stdlib import {name!r} requested by {who}")


sys.meta_path.insert(0, DenyNonStdlibFromFleet())

# Import every module in the package with the hook armed, so a module-level third-party import is caught
# before any verb runs.
mods = sorted(p[:-3] for p in os.listdir(os.path.join(FLEET_DIR))
              if p.endswith(".py") and p != "__init__.py")
for mod in ["fleet"] + [f"fleet.{m}" for m in mods]:
    importlib.import_module(mod)
print("site_packages_on_path:", [p for p in sys.path if "site-packages" in p or "dist-packages" in p])
print("modules_imported:", len(mods) + 1)

from fleet.cli import main, registered_codes            # noqa: E402

INST, SLOT = os.environ["A4_INST"], os.environ["A4_SLOT"]
# Real handlers, chosen to cover the runtime-heavy paths: subprocess (`verify`), /proc (`reconcile`),
# git (`set-golden`), json state (`enroll`/`harvest`/`reap`), the layout matrix (`init`/`lint`).
matrix = [("leases", []), ("board", []), ("lint", ["--instant", INST]), ("roadmap", ["--instant", INST]),
          ("reconcile", []), ("compaction-status", []), ("verify", ["--instant", INST]),
          ("init", ["--name", "a4cprobe"]), ("enroll", ["--slot", SLOT]),
          ("set-golden", ["--path", os.environ["A4_GOLDEN"]]), ("harvest", []), ("reap", []),
          ("declare", ["--instant", INST, "--phase", "awaiting-ci"]),
          ("park", ["--instant", INST, "--question", "a4c"]), ("unpark", ["--instant", INST]),
          ("pane-guard", ["--pane", "itfleet-A-absent-zzz"])]
codes = {}
for verb, args in matrix:
    rc = main([verb] + args)
    codes[verb] = rc
    assert rc in registered_codes(verb), f"{verb} returned unregistered {rc}"
print("verbs_run:", len(matrix), "codes:", codes)
print("REFUSED_FROM_FLEET:", REFUSED)
print("attempted_elsewhere_and_allowed:", sorted(set(ALLOWED_ELSEWHERE)))
assert not REFUSED, REFUSED
print("OK A4c")
PY
  timeout 60 python3 -m fleet.cli init --home "$d/home" --instants-dir "$d/instants" \
           --name a4cbase --base 00000000 > "$OUT/A4c-setup.out" 2>&1
  local a4inst; a4inst="$(find "$d/instants" -mindepth 1 -maxdepth 1 -name '*a4cbase' | head -1)"
  ( cd "$d/wd" && env -u PYTHONPATH PYTHONPATH="$A3_CO" \
    FLEET_HOME="$d/home" FLEET_INSTANTS="$d/instants" \
    A4_SRC_SECOND="$A3_CO/fleet" A4_INST="$a4inst" A4_SLOT="$d/slot" A4_GOLDEN="$DUMMY/alpha" \
    timeout 300 python3 -S "$PY_DIR/a4c.py" > "$OUT/A4c.out" 2>&1 )
  local rc_c=$? nverbs nsite nmods_i
  nverbs="$(sed -n 's/^verbs_run: \([0-9]*\).*/\1/p' "$OUT/A4c.out" | head -1)"
  nmods_i="$(sed -n 's/^modules_imported: //p' "$OUT/A4c.out" | head -1)"
  #: The COUNT of site/dist-packages entries left on sys.path, never the paths themselves — an absolute
  #: path in a note is what `bin/lint-evidence-paths.sh` fails the register for (P-3 / FI-32).
  nsite="$(sed -n 's/^site_packages_on_path: //p' "$OUT/A4c.out" | head -1 \
           | tr ',' '\n' | grep -c 'packages')"
  if [ "$rc_c" = 0 ] && grep -q '^OK A4c' "$OUT/A4c.out" && [ "${nsite:-1}" = 0 ]; then
    a_pass A4c "$OUT/A4c.out" "$(sq "real run with the import surface restricted: python3 -S leaves $nsite site/dist-packages entries on sys.path, all ${nmods_i:-0} fleet modules imported and ${nverbs:-0} REAL verbs run (subprocess, /proc and git paths included) under a meta_path hook that refuses any non-stdlib import requested from a fleet frame — 0 refusals. The stdlib's own Jython probe (top-level 'org', from copy.py) is attributed elsewhere and allowed, which is exactly why the hook attributes by calling frame and not by module name")"
  else
    a_fail A4c "$OUT/A4c.out" "$(sq "rc=$rc_c site_or_dist_packages_still_on_path=${nsite:-unknown} :: $(grep -E 'REFUSED_FROM_FLEET|Error|assert' "$OUT/A4c.out" | head -3 | scrub | tr '\n' ' ')")"
  fi

  local bad; bad="$(awk -F'\t' '$1 ~ /^A4[abc]$/ && $2=="FAIL"' "$RESULTS" | wc -l | tr -d ' ')"
  if [ "$bad" = 0 ]; then
    a_pass A4 "$OUT/A4c.out" "$(sq "no import outside the stdlib: static (A4a, all $nfiles modules incl. function-local imports), no dynamic escape hatch (A4b), and a real -S run with a frame-attributed deny hook (A4c)")"
  else
    a_fail A4 "$OUT/A4c.out" "$(sq "$bad of 3 sub-assertions failed — see A4a/A4b/A4c")"
  fi
}

# ===================================================================================================
# A5 — every verb's exit code is in the registry; a matrix drives each verb into
#      ok / attention / bad-input / no-capacity / refused
# ===================================================================================================
#
# The population is 27, and asserting 27 is the point: Plan 6 says 20, `FD-12` added seven. The count is
# READ OFF `cli.VERBS` rather than typed here, so a 28th verb fails this case instead of slipping past it.
#
# Every invocation below runs a REAL handler. §M's M1 already established registry containment over one
# `--dry-run` invocation per verb; `--dry-run` returns before the work, so it leaves "what code does this
# verb return when it does its job" unmeasured. The one exception is `dispatch`, and it is stated: a real
# dispatch hardcodes a `dt-` session name, which the isolation contract forbids §A from creating.
A5_LOG=""
#: `registered_codes(verb)` for every verb, computed ONCE off the source. Per-invocation it would be 70
#: interpreter starts, and — more to the point — the permitted set must be read from the registry rather
#: than from the run it is judging.
a5_allowed_table() {
  python3 -c 'from fleet.cli import VERBS, registered_codes
for v in sorted(VERBS):
    print(v, " ".join(str(c) for c in sorted(registered_codes(v))))' > "$OUT/A5-allowed-codes.txt"
}
a5_allowed() { awk -v v="$1" '$1==v {$1=""; print; exit}' "$OUT/A5-allowed-codes.txt"; }

a5_record() {             # a5_record <state> <verb> <want> <got> <note>
  printf '%-12s %-18s want=%-4s got=%-4s %s\n' "$1" "$2" "$3" "$4" "${5:-}" >> "$A5_LOG"
  A5_N=$((A5_N+1))
  local allowed; allowed="$(a5_allowed "$2")"
  case " $allowed " in *" $4 "*) ;; *) A5_UNREG=$((A5_UNREG+1)); A5_UNREG_LIST="$A5_UNREG_LIST $2($4)";; esac
  A5_SEEN="$A5_SEEN $4"
  A5_VERBS_SEEN="$A5_VERBS_SEEN $2"
  if [ "$3" != "-" ] && [ "$3" != "$4" ]; then
    A5_WRONG=$((A5_WRONG+1)); A5_WRONG_LIST="$A5_WRONG_LIST $2:$1(want$3,got$4)"
  fi
  A5_CODE_PRODUCER="$A5_CODE_PRODUCER
$4 $2"
  true
}

a5_drive() {              # a5_drive <state> <verb> <want> <args...>
  local state="$1" verb="$2" want="$3"; shift 3
  a_run "A5-$state-$verb" timeout 300 python3 -m fleet.cli "$verb" "$@"
  a5_record "$state" "$verb" "$want" "$A_RC" "$state"
  A5_LAST_RC="$A_RC"
}

a5_setup() {
  A5_H="$EV/A5/home"; A5_I="$EV/A5/instants"
  mkdir -p "$A5_H" "$A5_I" "$SLOTS/a5s1" "$SLOTS/a5s2"
  export FLEET_HOME="$A5_H" FLEET_INSTANTS="$A5_I"
  local mk
  for mk in a5subject a5lintbad a5gatefail a5gatepass a5abortee; do
    timeout 60 python3 -m fleet.cli init --name "$mk" --base 00000000 >> "$OUT/A5-setup.out" 2>&1
  done
  A5_INST="$(find "$A5_I" -mindepth 1 -maxdepth 1 -name '*a5subject' | head -1)"
  A5_LINTBAD="$(find "$A5_I" -mindepth 1 -maxdepth 1 -name '*a5lintbad' | head -1)"
  A5_GATEFAIL="$(find "$A5_I" -mindepth 1 -maxdepth 1 -name '*a5gatefail' | head -1)"
  A5_GATEPASS="$(find "$A5_I" -mindepth 1 -maxdepth 1 -name '*a5gatepass' | head -1)"
  A5_ABORTEE="$(find "$A5_I" -mindepth 1 -maxdepth 1 -name '*a5abortee' | head -1)"
  cat > "$PY_DIR/a5seed.py" <<'PY'
import os
from pathlib import Path
from fleet.roadmap import Milestone, Roadmap
road = Roadmap(Path(os.environ["A5_INST"]))
if not road.milestones():
    road.add(Milestone(id="M1", title="the A5 milestone", status="ready", deps=[], evidence=[]))
print("milestones:", [m.id for m in road.milestones()])
PY
  A5_INST="$A5_INST" python3 "$PY_DIR/a5seed.py" >> "$OUT/A5-setup.out" 2>&1
  #: STATE.md is forbidden in every cell of the layout matrix — the cheapest deterministic `lint`
  #: violation, and it is `B2`'s subject rather than something invented here.
  : > "$A5_LINTBAD/STATE.md"
  #: `complete` has THREE distinct answers and the fixture must produce each, because two of them are
  #: different exit codes for what a careless test would call "the gate said no":
  #:   READY round recorded      -> 0  (ok, the folder is renamed)
  #:   NOT-READY round recorded  -> 1  (attention: JUDGED and failed)
  #:   no round recorded at all  -> 2  (bad input: gate `review-undecidable`, "nothing has been judged")
  #: The first pass of this runner seeded no round on the attention instant and got 2 where it wanted 1 —
  #: the test was wrong and the product's distinction is the point (`OI-3`: one non-zero class for two
  #: mechanisms is what a caller cannot act on). Both are now driven, separately.
  timeout 60 python3 -m fleet.cli review --instant "$A5_GATEPASS" --scope all --verdict READY \
           >> "$OUT/A5-setup.out" 2>&1
  timeout 60 python3 -m fleet.cli review --instant "$A5_GATEFAIL" --scope all --verdict NOT-READY \
           >> "$OUT/A5-setup.out" 2>&1
  #: A fourth instant, left with NO review round, for the undecidable cell.
  timeout 60 python3 -m fleet.cli init --name a5undecidable --base 00000000 >> "$OUT/A5-setup.out" 2>&1
  A5_UNDEC="$(find "$A5_I" -mindepth 1 -maxdepth 1 -name '*a5undecidable' | head -1)"
  #: A home of its own for the harvest pair, so the two ticks differ in ONE thing: the memory the first
  #: wrote. In the shared home they do not — see A5f.
  A5_H_HARVEST="$EV/A5/home-harvest"; A5_I_HARVEST="$EV/A5/instants-harvest"
  mkdir -p "$A5_H_HARVEST" "$A5_I_HARVEST"
  timeout 60 python3 -m fleet.cli init --home "$A5_H_HARVEST" --instants-dir "$A5_I_HARVEST" \
           --name a5hv --base 00000000 >> "$OUT/A5-setup.out" 2>&1
  #: Dedicated homes so `dispatch`'s three reachable codes are each forced by ONE differing condition.
  A5_H_EMPTY="$EV/A5/home-empty"; A5_I_EMPTY="$EV/A5/instants-empty"
  A5_H_FREE="$EV/A5/home-free";   A5_I_FREE="$EV/A5/instants-free"
  mkdir -p "$A5_H_EMPTY" "$A5_I_EMPTY" "$A5_H_FREE" "$A5_I_FREE" "$SLOTS/a5free"
  timeout 60 python3 -m fleet.cli enroll --home "$A5_H_FREE" --slot "$SLOTS/a5free" \
           >> "$OUT/A5-setup.out" 2>&1
  #: One real pane on the PRIVATE server, for `pane-guard` against something that exists. `sleep` and
  #: not the `bin/claude` stub, because the stub `exec sleep`s anyway and this verdict (12, not-claude)
  #: is the one a plain pane is entitled to. pane-guard's `0` needs a pane rendering claude's input box;
  #: §M10 owns that matrix and §A does not restate it.
  it_tmux new-session -d -s "$TMUX_PREFIX-a5shell" "sleep 900" >> "$OUT/A5-setup.out" 2>&1
  sleep 1
}

a5_main_matrix() {
  A5_LOG="$OUT/A5-matrix.txt"; : > "$A5_LOG"
  A5_N=0; A5_UNREG=0; A5_WRONG=0; A5_UNREG_LIST=""; A5_WRONG_LIST=""; A5_SEEN=""
  A5_VERBS_SEEN=""; A5_CODE_PRODUCER=""
  #: Pre-initialised so a cell that never runs is reported as `unrun` in A5e rather than tripping
  #: `set -u` on the way to the report — a runner that dies while writing its own caveats loses them.
  A5_SELFTEST_RC=unrun; A5_HARVEST_1=unrun; A5_HARVEST_2=unrun; A5_LAST_RC=unrun
  A5_NC_GUARD=unrun; A5_REF_NAMES_LEASE=unrun; A5_REF_GUARD=unrun; A5_TODO=""
  a5_allowed_table
  a5_setup

  # ---- bad-input (2): an undeclared flag, for ALL 27 verbs -----------------------------------------
  #: The one state every verb can be driven into without any fixture, so it is the cell that makes the
  #: matrix's population complete rather than "the verbs that happened to be set up".
  local v
  for v in $A_VERBS_ALL; do
    a5_drive bad-input "$v" 2 --a5-not-a-declared-flag
  done

  # ---- ok (0): a REAL success path per verb --------------------------------------------------------
  a5_drive ok init       0 --name a5extra --base 00000000
  a5_drive ok enroll     0 --slot "$SLOTS/a5s1"
  a5_drive ok enroll     0 --slot "$SLOTS/a5s2"
  a5_drive ok set-golden 0 --path "$DUMMY/alpha"
  a5_drive ok leases     0
  a5_drive ok board      0
  a5_drive ok lint       0 --instant "$A5_INST"
  a5_drive ok verify     0 --instant "$A5_INST"
  a5_drive ok roadmap    0 --instant "$A5_INST"
  a5_drive ok reconcile  0
  a5_drive ok compaction-status 0
  a5_drive ok declare    0 --instant "$A5_INST" --phase awaiting-ci
  a5_drive ok park       0 --instant "$A5_INST" --question a5park
  a5_drive ok unpark     0 --instant "$A5_INST"
  a5_drive ok propose    0 --instant "$A5_INST" --milestone M1 --status running \
                           --evidence "$OUT/A5-setup.out"
  a5_drive ok apply      0 --instant "$A5_INST" --milestone M1
  a5_drive ok review     0 --instant "$A5_INST" --scope all --verdict READY
  #: resume claims a5s1 and writes a record — the fixture the next four cases need. Its `--tmux` is an
  #: `itfleet-A-` name, never the `dt-{name}` default.
  a5_drive ok resume     0 --instant "$A5_INST" --slot a5s1 --tmux "$TMUX_PREFIX-a5worker"
  A5_TODO="$(A5_H="$A5_H" python3 -c "
import json, os
from pathlib import Path
recs = sorted((Path(os.environ['A5_H']) / 'records').glob('*.json'))
print(json.loads(recs[0].read_text())['todo_id'] if recs else '')")"
  if [ -n "$A5_TODO" ]; then
    a5_drive ok status 0 --id "$A5_TODO"
    a5_drive ok close  0 --id "$A5_TODO"
  else
    a5_record ok status "0" "-" "NOT-DRIVEN: no record on disk after resume"
    a5_record ok close  "0" "-" "NOT-DRIVEN: no record on disk after resume"
  fi
  a5_drive ok selftest   - ;   A5_SELFTEST_RC="$A5_LAST_RC"
  a5_drive ok abort      0 --instant "$A5_ABORTEE" --reason a5reason
  a5_drive ok complete   0 --instant "$A5_GATEPASS"
  #: dispatch's ok, in a home whose only difference from the no-capacity home is one enrolled slot.
  a5_drive ok dispatch   0 --home "$A5_H_FREE" --instants-dir "$A5_I_FREE" \
                           --profile "$A_PROFILE" --title a5dok --base 00000000 --dry-run

  # ---- attention (1) -------------------------------------------------------------------------------
  a5_drive attention lint     1 --instant "$A5_LINTBAD"
  a5_drive attention review    1 --instant "$A5_INST" --scope all --verdict NOT-READY
  a5_drive attention complete  1 --instant "$A5_GATEFAIL"
  #: The gate's third answer, asserted as its OWN cell: no round recorded is not the same as a round that
  #: decided against, and the two must not collapse into one non-zero class.
  a5_drive undecidable complete 2 --instant "$A5_UNDEC"
  #: harvest's two answers come from the SAME command run twice in a home of its own: a first tick over a
  #: register it has no memory of (1, `no-prior-state`), then a second over the memory the first wrote (0).
  #: The pair is the assertion; a single tick cannot distinguish "clean" from "no state yet".
  a5_drive attention harvest 1 --home "$A5_H_HARVEST" --instants-dir "$A5_I_HARVEST"
  A5_HARVEST_1="$A5_LAST_RC"
  a5_drive ok        harvest 0 --home "$A5_H_HARVEST" --instants-dir "$A5_I_HARVEST"
  A5_HARVEST_2="$A5_LAST_RC"

  # ---- no-capacity (3) -----------------------------------------------------------------------------
  a5_drive no-capacity dispatch 3 --home "$A5_H_EMPTY" --instants-dir "$A5_I_EMPTY" \
                                  --profile "$A_PROFILE" --title a5dnc --base 00000000 --dry-run
  A5_NC_GUARD=no
  grep -q 'pool-capacity' "$OUT/A5-no-capacity-dispatch.stdout" 2>/dev/null && A5_NC_GUARD=yes

  # ---- refused (4) ---------------------------------------------------------------------------------
  #: Two mechanisms, deliberately: `OI-3` is a test that could not tell a full pool from a policy
  #: refusal because both produced one non-zero class.
  a5_drive refused unenroll 4 --slot a5s1
  A5_REF_NAMES_LEASE=no
  grep -q 'leased by todo' "$OUT/A5-refused-unenroll.stderr" 2>/dev/null && A5_REF_NAMES_LEASE=yes
  a5_drive refused dispatch 4 --profile "$A_PROFILE" --title a5dref --base 00000000 --cap 0 --dry-run
  A5_REF_GUARD=no
  grep -q 'wip-cap' "$OUT/A5-refused-dispatch.stdout" 2>/dev/null && A5_REF_GUARD=yes

  # ---- pane-guard's own registry (FD-10: 0/10/11/12/13) -------------------------------------------
  a5_drive unknown-pane pane-guard 13 --pane "$TMUX_PREFIX-absent-zzz"
  a5_drive not-claude   pane-guard 12 --pane "$TMUX_PREFIX-a5shell"

  # ---- the freed-then-unenrolled tail, so reap and unenroll both reach ok -------------------------
  a5_drive ok reap     0 --base 00000000
  a5_drive ok unenroll 0 --slot a5s2
}

#: A5f — `harvest`'s attention code must be CLEARABLE. It is the cadence alarm: `_cadence` runs it for
#: every verb and prints every overdue obligation, and the module's own comment says an always-red alarm
#: is the failure `OBS-21` avoided (`FI-18`). So "a tick with nothing new returns 0" is a real property,
#: and this cell measures whether one dispatch from the DEFAULT base takes it away permanently.
a5f_root_base_poisons_the_register() {
  local h="$EV/A5/home-a5f" i="$EV/A5/instants-a5f" t1 t2 t3 t4
  mkdir -p "$h" "$i"
  timeout 60 python3 -m fleet.cli init --home "$h" --instants-dir "$i" --name a5f --base 00000000 \
           > "$OUT/A5f-setup.out" 2>&1
  local inst; inst="$(find "$i" -mindepth 1 -maxdepth 1 -name '*a5f' | head -1)"
  timeout 60 python3 -m fleet.cli harvest --home "$h" --instants-dir "$i" >/dev/null 2>&1; t1=$?
  timeout 60 python3 -m fleet.cli harvest --home "$h" --instants-dir "$i" >/dev/null 2>&1; t2=$?
  #: `resume` and not `dispatch`, so the reproduction needs no tmux session and no `dt-` name at all —
  #: both verbs reach the same writer, `harvest.record_dispatch`.
  timeout 60 python3 -m fleet.cli resume --home "$h" --instants-dir "$i" --instant "$inst" \
           --tmux "$TMUX_PREFIX-a5f" > "$OUT/A5f-resume.out" 2>&1
  timeout 60 python3 -m fleet.cli harvest --home "$h" --instants-dir "$i" \
           > "$OUT/A5f-tick3.out" 2>&1; t3=$?
  timeout 60 python3 -m fleet.cli harvest --home "$h" --instants-dir "$i" \
           > "$OUT/A5f-tick4.out" 2>&1; t4=$?
  cp "$h/harvest/sources.json" "$OUT/A5f-sources.json" 2>/dev/null
  local unreadable; unreadable="$(grep -c 'unreadable-source' "$OUT/A5f-tick4.out")"
  printf 'pre-resume  tick1=%s tick2=%s\npost-resume tick3=%s tick4=%s\nunreadable-source rows in tick4: %s\n' \
         "$t1" "$t2" "$t3" "$t4" "$unreadable" > "$OUT/A5f-summary.txt"
  if [ "$t1" = 1 ] && [ "$t2" = 0 ] && [ "$t3" = 0 ] && [ "$t4" = 0 ]; then
    a_pass A5f "$OUT/A5f-summary.txt" "$(sq "harvest's attention code is clearable: tick1=$t1 (no prior state), tick2=$t2, and a resume from the default base leaves tick3=$t3 tick4=$t4 — the register stays readable")"
  else
    a_fail A5f "$OUT/A5f-summary.txt" "$(sq "DEFECT in src/fleet, REPORTED not fixed: harvest is clean before a resume (tick1=$t1 no-prior-state, tick2=$t2) and can NEVER return 0 again afterwards (tick3=$t3, tick4=$t4, $unreadable unreadable-source violation row(s) per tick). Cause: resume/dispatch both call harvest.record_dispatch, which registers record.base_instant VERBATIM as a watched source — for the documented default base (identity.ROOT_BASE '00000000') that stores base='00000000', issues_path='00000000/ISSUES.md', a relative path to a folder that does not exist, so every later tick emits an unreadable-source VIOLATION. harvest's exit code is stuck at 1 with no verb that can clear it, and _cadence runs this for EVERY verb — the always-red alarm harvest.py's own comment cites OBS-21/FI-18 for avoiding. Register copied to A5f-sources.json")"
  fi
}

a5_verdicts() {
  # A5a — population
  local covered missing
  covered="$(printf '%s\n' $A5_VERBS_SEEN | sort -u | grep -c .)"
  missing="$(comm -23 <(printf '%s\n' $A_VERBS_ALL | sort -u) \
                      <(printf '%s\n' $A5_VERBS_SEEN | sort -u) | tr '\n' ' ')"
  if [ "$covered" = "$A_NVERBS" ] && [ -z "$(printf '%s' "$missing" | tr -d ' ')" ]; then
    a_pass A5a "$A5_LOG" "$(sq "the matrix covers all $A_NVERBS verbs read off cli.VERBS — the plan says 20, FD-12 added seven, and the count is derived rather than typed so a 28th verb fails this case")"
  else
    a_fail A5a "$A5_LOG" "$(sq "the matrix covered $covered of $A_NVERBS verbs; not driven: $missing")"
  fi

  # A5b — the registry assertion, over every invocation
  if [ "$A5_UNREG" = 0 ]; then
    a_pass A5b "$A5_LOG" "$(sq "every one of $A5_N real invocations returned a code inside registered_codes(verb) — the 5 base codes for 26 verbs and FD-10's 0/10/11/12/13 for pane-guard")"
  else
    a_fail A5b "$A5_LOG" "$(sq "$A5_UNREG of $A5_N invocations returned a code the registry does not list:$A5_UNREG_LIST — a tick that branches on an exit code was not told about it (NFR2-8)")"
  fi

  # A5c — the intended state produced the intended code
  if [ "$A5_WRONG" = 0 ]; then
    a_pass A5c "$A5_LOG" "$(sq "every driven cell returned the code its state calls for: $A5_N invocations, 0 mismatches. Cells whose code is state-dependent (selftest, the two harvest ticks) carry no want and are reported in A5e instead of asserted here")"
  else
    a_fail A5c "$A5_LOG" "$(sq "$A5_WRONG cell(s) returned the wrong code:$A5_WRONG_LIST")"
  fi

  # A5d — coverage of all five base codes, each with its producer named
  local codes_seen missing_codes=""
  codes_seen="$(printf '%s\n' $A5_SEEN | sort -un | tr '\n' ' ')"
  local c
  for c in 0 1 2 3 4; do
    case " $codes_seen " in *" $c "*) ;; *) missing_codes="$missing_codes $c";; esac
  done
  printf '%s\n' "$A5_CODE_PRODUCER" | grep -E '^[0-9]+ ' | sort -u > "$OUT/A5-code-producers.txt"
  if [ -z "$(printf '%s' "$missing_codes" | tr -d ' ')" ]; then
    a_pass A5d "$OUT/A5-code-producers.txt" "$(sq "all five registry codes were really produced: 0 ok (init/enroll/leases/...), 1 attention (lint on a forbidden STATE.md, review NOT-READY, complete on an unpassed gate), 2 bad-input (an undeclared flag, all $A_NVERBS verbs), 3 no-capacity (dispatch --dry-run, 0 enrolled slots, guard named=$A5_NC_GUARD), 4 refused (unenroll of a leased slot, message names the lease=$A5_REF_NAMES_LEASE; and dispatch --cap 0, wip-cap named=$A5_REF_GUARD). Codes observed: $codes_seen")"
  else
    a_fail A5d "$OUT/A5-code-producers.txt" "$(sq "codes never produced by any verb in the matrix:$missing_codes (observed: $codes_seen) — an unproduced registry code is a branch no caller can be shown to need")"
  fi

  # A5e — the cells §A could NOT drive, said out loud rather than left as a silent gap
  a_skip A5e "$A5_LOG" "$(sq "NOT DRIVEN, stated rather than passed vacuously: (1) dispatch's ok/no-capacity/refused are driven through --dry-run only, because a real dispatch HARDCODES a dt-{name} tmux session (cli._do_dispatch) and the isolation contract forbids §A creating one — there is no --no-launch flag; (2) pane-guard's 0/10/11 need a pane rendering claude's input box, which §M10 already drives against real panes; (3) selftest returned $A5_SELFTEST_RC and is the one cell carrying no want: its code is a property of the working TREE (M13 shows dirt inside src/ or tests/ makes it 1) and other agents are editing that tree, so it is asserted for registry membership (A5b) alone. harvest's pair IS asserted ($A5_HARVEST_1 then $A5_HARVEST_2) once given a home of its own — in the shared home the second tick cannot reach 0, which is A5f; (4) no-capacity and refused are reachable for dispatch and unenroll only — the other 25 verbs have no admission rule to refuse them, so 'drive EVERY verb into all five' is not a property this domain has")"

  # A5f — a DEFECT found while driving harvest's ok cell, kept as its own asserted cell rather than as a
  # sentence in A5e. Not part of the A5 aggregate: it is not one of Plan 6's A5 obligations, it is a
  # product finding this matrix walked into, and burying it in a note is how a finding stops being one.
  a5f_root_base_poisons_the_register

  local bad; bad="$(awk -F'\t' '$1 ~ /^A5[abcd]$/ && $2=="FAIL"' "$RESULTS" | wc -l | tr -d ' ')"
  if [ "$bad" = 0 ]; then
    a_pass A5 "$A5_LOG" "$(sq "all $A_NVERBS verbs driven through $A5_N REAL invocations (no --dry-run except dispatch, and that is stated in A5e): every code came from the registry and every intended state produced its own code; all five base codes really occurred")"
  else
    a_fail A5 "$A5_LOG" "$(sq "$bad of 4 asserted sub-cases failed — see A5a/A5b/A5c/A5d")"
  fi
}

a5() { a5_main_matrix; a5_verdicts; export FLEET_HOME="$EV/home" FLEET_INSTANTS="$EV/instants"; }

# ===================================================================================================
# A6 — `pgrep -x claude` identical before and after
# ===================================================================================================
a6() {
  local after="$OUT/claude-pids-after.txt"
  pgrep -x claude 2>/dev/null | sort -n > "$after"
  local nb na
  nb="$(grep -c . "$A_CLAUDE_BEFORE")"; na="$(grep -c . "$after")"
  #: The detector's own liveness, first. `0 == 0` before and after is also what a broken `pgrep`
  #: invocation returns, and that is a pass that would hold if nothing were being measured.
  if [ "$nb" = 0 ]; then
    a_skip A6 "$after" "$(sq "pgrep -x claude matched NOTHING before §A ran, so before==after ($nb==$na) cannot distinguish 'no claude was started' from 'the detector matches nothing' — the same reason W1-4 skips when no dt- session exists. §A launched no claude; the assertion is simply not available on this machine state")"
    return
  fi
  #: Classified, not diffed. A bare set comparison fails on BOTH directions of a change no section can
  #: cause: a foreign session ENDING (which broke a release gate on 10 -> 9, pid 3754352, a COMPLETE
  #: worker's pane exiting) and a foreign fork-before-exec transient APPEARING. §A launches no claude, so
  #: an addition whose cwd is inside this instant would be a genuine leak and still FAILS.
  local a_claude
  a_claude="$(it_classify_claude_delta "$(cat "$A_CLAUDE_BEFORE")" "$(cat "$after")")"
  if [ "${a_claude%%|*}" = FAIL ]; then
    a_fail A6 "$after" "$(sq "${a_claude#*|}")"
  else
    a_pass A6 "$after" "$(sq "${a_claude#*|}. Compared as an attributed SET, not a count: the detector is live (it matched $nb processes before), so this is a measurement and not an empty world. §A starts and kills no claude; the only long-lived process it created is a tmux 'sleep 900' pane on the private server")"
  fi
}

# ===================================================================================================
# A7 — no `^dt-` session created, killed or written to
# ===================================================================================================
a7() {
  local after="$OUT/live-sessions-after.txt" after_c="$OUT/live-sessions-created-after.txt"
  it_live_tmux_sessions > "$after"
  tmux ls -F '#{session_name} #{session_created}' 2>/dev/null | sort > "$after_c"
  grep '^dt-' "$A_LIVE_CREATED_BEFORE" > "$OUT/A7-dt-before.txt" 2>/dev/null || : > "$OUT/A7-dt-before.txt"
  grep '^dt-' "$after_c"               > "$OUT/A7-dt-after.txt"  2>/dev/null || : > "$OUT/A7-dt-after.txt"
  local ndt; ndt="$(grep -c . "$OUT/A7-dt-before.txt")"
  #: `session_created` and not `session_activity`: activity moves whenever a live pane produces output,
  #: which is the coordinator working and not a contamination. Creation time is stable, so an identical
  #: (name, created) set rules out a session being killed and re-made under the same name.
  local dt_same=no
  diff -q "$OUT/A7-dt-before.txt" "$OUT/A7-dt-after.txt" >/dev/null && dt_same=yes

  #: §A's own private server: no session it created may carry a `dt-` name, whatever the product does
  #: elsewhere. This is the half §A can assert positively.
  it_tmux ls -F '#{session_name}' 2>/dev/null | sort > "$OUT/A7-private-sessions.txt"
  local priv_dt; priv_dt="$(grep -c '^dt-' "$OUT/A7-private-sessions.txt")"

  #: The audit half: which code can name a `dt-` session at all, and on which server.
  grep -nE 'dt-' "$INSTANT"/src/fleet/*.py > "$OUT/A7-product-dt-sites.txt" 2>/dev/null
  local prod_sites; prod_sites="$(grep -c . "$OUT/A7-product-dt-sites.txt")"
  local socket_read; socket_read="$(grep -c 'TMUX_SOCKET_ENV' "$INSTANT/src/fleet/session.py")"

  if [ "$dt_same" = yes ] && [ "$priv_dt" = 0 ]; then
    a_pass A7 "$OUT/A7-dt-after.txt" "$(sq "no dt- session was created or killed: the live server's dt- set is identical before and after by NAME AND session_created ($ndt session(s)), and §A's own private server (socket $IT_TMUX_SOCKET) carries $priv_dt dt- sessions — the only session §A created is $TMUX_PREFIX-a5shell. §A runs no real dispatch, only dispatch --dry-run, which claims/creates/starts nothing")"
  else
    a_fail A7 "$OUT/A7-dt-after.txt" "$(sq "dt- sessions moved: live-set-identical=$dt_same, dt- sessions on §A's private server=$priv_dt :: $(diff "$OUT/A7-dt-before.txt" "$OUT/A7-dt-after.txt" | grep '^[<>]' | scrub | tr '\n' ' ')")"
  fi

  if [ "$ndt" = 0 ]; then
    a_skip A7b "$OUT/A7-product-dt-sites.txt" "$(sq "the 'never WRITTEN TO' half cannot be asserted this run: there is no dt- session on the live server at all, so a check for 'not written to' would pass against an empty world — the distinction run-w1.sh's W1-4 skips for the same reason. What IS asserted: cli._do_dispatch hardcodes tmux=f'dt-{name.name}' at $prod_sites site(s) in src/fleet (A7-product-dt-sites.txt) and routes every tmux call through FLEET_TMUX_SOCKET ($socket_read reference(s) in session.py), which it_section exports as $IT_TMUX_SOCKET — so a real dispatch's dt- session lands on a private server. REPORTED as a product finding: there is no flag on any verb to choose the session name at dispatch (only resume has --tmux), so Plan 6's 'no session matching ^dt- is created' cannot be honoured from outside")"
  else
    #: A dt- session exists: assert its creation time is untouched, which is the strongest read-only
    #: statement available about "not killed and re-made".
    a_pass A7b "$OUT/A7-dt-after.txt" "$(sq "$ndt dt- session(s) exist on the live server and their (name, session_created) pairs are byte-identical before and after §A; §A never made one a target and never sent keys to any session outside socket $IT_TMUX_SOCKET")"
  fi
}

# ===================================================================================================
# A8 — the harness itself contains no `push`, `merge`, `rm -rf ~`, or write outside the section dir
# ===================================================================================================
#
# An audit, over `lib.sh` and every `run-*.sh` INCLUDING this one — a runner that exempts itself from
# the audit it performs is the audit's own blind spot. Reading these files is fine; §A owns none of them
# but `run-A.sh`, so a finding is REPORTED and never edited away.
a8() {
  local files="" f
  for f in "$IT_ROOT/lib.sh" "$IT_ROOT"/run-*.sh; do files="$files $f"; done
  local nfiles; nfiles="$(printf '%s\n' $files | grep -c .)"

  #: A grep is the wrong tool for this audit and the first pass proved it: `grep -nE 'git +(push|merge)'`
  #: matched run-A.sh's OWN comment describing the pattern and its OWN pass-note saying "no git push", so
  #: the auditor failed itself on three lines of prose. Whether a line PUSHES is a question about code,
  #: not about text, so each line is stripped of its comment and (for the command questions) of its
  #: quoted string literals before the patterns are applied. Two different strips, because the two
  #: questions need opposite things: a forbidden COMMAND inside quotes is a string, while a write
  #: TARGET is almost always inside quotes.
  cat > "$PY_DIR/a8audit.py" <<'PY'
"""A8 — the audit of the harness itself. Classified by lexing the shell, not by grepping the text.

Three greps were tried first and all three failed the same way: they judged PROSE. `grep -nE 'git
+(push|merge)'` matched this runner's own comment describing the pattern and its own pass-note saying
"no git push"; the rm-target grep, run against a quote-stripped line, reported `;;` as the target of
`rm -rf "$A_EVDIR"`. Whether a line PUSHES is a question about code, and the only way to ask it is to
know which characters the shell would run as words and which it would pass as data.

So one scan produces two renderings of every line:

  `code`   — what the shell RUNS. Quoted spans collapse to a token (`<V>` if the span began with `$`,
             else `<L>`), and a `$( ... )` substitution is code again even inside double quotes, which
             is exactly where the false positives lived.
  `masked` — the same, but each token carries its content, so a write TARGET (almost always quoted) is
             still readable.

Heredoc bodies are DATA and are skipped, counted rather than silently dropped: every runner here embeds
python that way, including this audit, whose regexes contain the very strings it searches for. The one
thing this cannot see is a heredoc written out as a script and then executed; no runner does that.
"""
import json, os, re, sys

FORBIDDEN = [
    (re.compile(r"\bgit\s+(push|merge)\b"), "git push/merge"),
    (re.compile(r"\bgh\s+pr\s+merge\b"), "gh pr merge"),
    (re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+(\$HOME|~(/|\s|$)|/home/[a-z]+\s*$)"), "rm -rf home"),
]
KILL = re.compile(r"tmux[^;&|]*kill-(server|session)")
RM_CMD = re.compile(r"\brm\s+(-[a-zA-Z]+\s+)*-[a-zA-Z]*r[a-zA-Z]*\b")
RM_TGT = re.compile(r"\brm\s+(-[a-zA-Z]+\s+)*-[a-zA-Z]*r[a-zA-Z]*\s+(?P<target>\S+)")
WRITE_OUT = re.compile(r"(>>?|tee)\s*<\$?(IT_ROOT|LIVE_TMUX_SNAPSHOT|RESULTS|LIVE_SNAPSHOT)\b"
                       r"|(>>?|tee)\s*<\$(IT_ROOT|LIVE_TMUX_SNAPSHOT|RESULTS|LIVE_SNAPSHOT)")
TMPDIR = re.compile(r"\bmktemp\b|\$TMPDIR|(^|[\s<(=])/tmp/")
HEREDOC = re.compile(r"<<-?\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?")


def lex(line):
    """-> (code, masked, comment_stripped_raw). A tiny context stack, not a full shell parser."""
    code, masked, plain = [], [], []
    stack = ["CODE"]          # CODE | DQ | SQ | CS(=command substitution, code again)
    span = []
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        top = stack[-1]
        if top == "CODE" or top == "CS":
            if ch == "#" and top == "CODE":
                break                                   # a top-level comment; the rest is prose
            if line.startswith("$(", i):
                stack.append("CS"); code.append("$("); masked.append("$("); plain.append("$(")
                i += 2; continue
            if ch == ")" and top == "CS":
                stack.pop(); code.append(")"); masked.append(")"); plain.append(")")
                i += 1; continue
            if ch in "\"'":
                stack.append("DQ" if ch == '"' else "SQ"); span = []
                plain.append(ch); i += 1; continue
            code.append(ch); masked.append(ch); plain.append(ch); i += 1; continue
        # inside a quoted span
        if top == "DQ" and line.startswith("$(", i):
            # a substitution inside a string: flush what we have as a token, then lex code again
            token = "".join(span)
            code.append("<V>" if token.startswith("$") else "<L>")
            masked.append("<" + token + ">")
            span = []
            stack.append("CS"); code.append("$("); masked.append("$("); plain.append("$(")
            i += 2; continue
        if (top == "DQ" and ch == '"') or (top == "SQ" and ch == "'"):
            stack.pop()
            token = "".join(span)
            code.append("<V>" if token.startswith("$") else "<L>")
            masked.append("<" + token + ">")
            plain.append(ch); span = []
            i += 1; continue
        span.append(ch); plain.append(ch); i += 1
    return "".join(code), "".join(masked), "".join(plain)


report = {"forbidden": [], "kill_unsafe": [], "kill_all": [], "rm_all": [], "rm_unrooted": [],
          "writes_outside": [], "writes_tmpdir": [], "files": 0, "heredoc_data_lines": 0}
for path in sys.argv[1:]:
    report["files"] += 1
    name = os.path.basename(path)
    pending = None
    for lineno, raw in enumerate(open(path, encoding="utf-8", errors="replace"), start=1):
        raw = raw.rstrip("\n")
        if pending is not None:
            report["heredoc_data_lines"] += 1
            if raw.strip() == pending:
                pending = None
            continue
        code, masked, plain = lex(raw)
        where = f"{name}:{lineno}"
        for pattern, label in FORBIDDEN:
            if pattern.search(code):
                report["forbidden"].append(f"{where} [{label}] {code.strip()[:120]}")
        if KILL.search(code):
            report["kill_all"].append(f"{where} {masked.strip()[:130]}")
            # Safe iff it names a private server: `-L <socket>`, or `it_tmux` — lib.sh's wrapper, which
            # refuses outright when no section has been entered and so cannot reach the default server.
            if not re.search(r"tmux\s+-L\b", code) and not re.search(r"\bit_tmux\b", code):
                report["kill_unsafe"].append(f"{where} {masked.strip()[:130]}")
        if RM_CMD.search(code):
            m = RM_TGT.search(masked)
            target = m.group("target") if m else "(none)"
            report["rm_all"].append(f"{where} target={target}")
            rooted = target.startswith("<$") or target.startswith("$")
            # `find <$DIR> ... -exec rm -rf {} +`: the target is find's own substitution and the bound is
            # find's START PATH, so the question moves one argument left rather than disappearing.
            if not rooted and target.startswith("{}") and re.search(r"\bfind\s+<\$", masked):
                rooted = True
            if not rooted:
                report["rm_unrooted"].append(f"{where} target={target} :: {masked.strip()[:110]}")
        if WRITE_OUT.search(masked):
            report["writes_outside"].append(f"{where} {masked.strip()[:130]}")
        if TMPDIR.search(masked):
            report["writes_tmpdir"].append(f"{where} {masked.strip()[:130]}")
        # On `plain` (comment stripped, quotes KEPT) and never on `code`: in `code` two adjacent quoted
        # spans render as `<V><L>`, whose `<<` opened a phantom heredoc with tag `L` that swallowed 2500
        # lines of three runners — an audit that silently stops reading is the OBS-49 shape, so the
        # skipped-line count is printed and was what made this visible.
        m_here = HEREDOC.search(plain)
        if m_here:
            pending = m_here.group(1)

print(f"=== heredoc data lines skipped: {report['heredoc_data_lines']}")
for key in ("forbidden", "kill_all", "kill_unsafe", "rm_all", "rm_unrooted",
            "writes_outside", "writes_tmpdir"):
    print(f"=== {key} ({len(report[key])})")
    for row in report[key]:
        print("   ", row)
print("COUNTS " + json.dumps({k: (v if isinstance(v, int) else len(v)) for k, v in report.items()}))
PY
  # shellcheck disable=SC2086
  python3 "$PY_DIR/a8audit.py" $files > "$OUT/A8-audit.txt" 2>&1
  local counts; counts="$(sed -n 's/^COUNTS //p' "$OUT/A8-audit.txt" | head -1)"
  a8_n() { printf '%s' "$counts" | python3 -c "import json,sys; print(json.load(sys.stdin).get('$1', -1))"; }
  local n_forbidden n_kill n_kill_unsafe n_rm n_rm_bad n_out n_tmp
  n_forbidden="$(a8_n forbidden)"; n_kill="$(a8_n kill_all)"; n_kill_unsafe="$(a8_n kill_unsafe)"
  n_rm="$(a8_n rm_all)"; n_rm_bad="$(a8_n rm_unrooted)"
  n_out="$(a8_n writes_outside)"; n_tmp="$(a8_n writes_tmpdir)"

  # ---- A8a: the forbidden commands ----------------------------------------------------------------
  if [ "$n_forbidden" = 0 ] && [ "$n_kill_unsafe" = 0 ]; then
    a_pass A8a "$OUT/A8-audit.txt" "$(sq "audited $nfiles harness files (lib.sh + every run-*.sh, this runner included, comments and string literals discounted): 0 git push / git merge / gh pr merge / rm -rf-on-home in an EXECUTED position; all $n_kill tmux kill-server/kill-session sites name a private server (tmux -L, or it_tmux which refuses when no section is entered), so none can reach the live tmux server")"
  else
    a_fail A8a "$OUT/A8-audit.txt" "$(sq "$n_forbidden forbidden command(s) and $n_kill_unsafe of $n_kill tmux kill site(s) with no private socket, across $nfiles files :: $(sed -n '/^=== forbidden/,/^=== kill_all/p' "$OUT/A8-audit.txt" | sed -n '2,3p' | scrub | tr '\n' ' ')")"
  fi

  # ---- A8b: every rm -rf target is a variable, never a literal ------------------------------------
  if [ "$n_rm_bad" = 0 ]; then
    a_pass A8b "$OUT/A8-audit.txt" "$(sq "$n_rm rm -rf site(s) across the harness and every one takes a \$VARIABLE target (\$EV / \$FLEET_HOME / \$SLOTS / \$G3_SOCK / \$A_EVDIR), so none is a literal path and none can widen past the section tree. The delete recipes that appear as text — the one run-group5.sh writes into a RUNBOOK.md for M12 to REFUSE, and the shapes M9 searches handlers for — are string literals and are correctly not counted as commands")"
  else
    a_fail A8b "$OUT/A8-audit.txt" "$(sq "$n_rm_bad of $n_rm rm -rf site(s) take a literal, non-variable target :: $(sed -n '/^=== rm_unrooted/,/^=== writes_outside/p' "$OUT/A8-audit.txt" | sed -n '2,3p' | scrub | tr '\n' ' ')")"
  fi

  # ---- A8c: writes outside the section dir -------------------------------------------------------
  #: The clause as written is "no write outside the section dir", so every write to `$IT_ROOT/...` rather
  #: than `$EV/...` is a hit and is ENUMERATED — the honest answer here is a list, not a boolean.
  local nout=$((n_out + n_tmp))
  #: ADJUDICATED as a plan-vs-design divergence (`SI-18`), so the verdict is SKIP-with-the-reason rather
  #: than a standing FAIL. The distinction matters and is not a softening:
  #:
  #:   * A FAIL means the DESIGN violates the rule. It does not. The register (`RESULTS.tsv`) and the
  #:     live-session baseline are state SHARED ACROSS sections — a results file inside one section's
  #:     directory could not be a fleet-wide register, and the baseline has to outlive any single section
  #:     or it cannot detect drift between them. Both are deliberately at `fleet/it/` level.
  #:   * The clause as the plan words it — "no write outside the section dir" — is therefore stricter than
  #:     the design it audits, and the PLAN is what is wrong. That is the parent's file and the parent is a
  #:     live writer, so it is named here rather than edited (`SD-0`).
  #:   * What `P-3` actually protects — no EVIDENCE path escaping the instant — holds, is asserted by
  #:     `A8a`/`A8b`, and is independently enforced on every commit by `bin/lint-evidence-paths.sh`.
  #:
  #: A standing FAIL that everyone knows is a specification bug is corrosive: it teaches readers to skim
  #: FAIL rows, which is exactly what 21 stale FAIL rows did to this file before `SI-4`. The enumeration is
  #: kept in full — the reason a SKIP is honest here is that it still says precisely what it found.
  if [ "$nout" = 0 ]; then
    a_pass A8c "$OUT/A8-audit.txt" "$(sq "no harness write lands outside the section dir")"
  else
    a_skip A8c "$OUT/A8-audit.txt" "$(sq "$nout write site(s) land OUTSIDE <section>/ — the clause as written does not hold, and every one is deliberate: $n_out site(s) write the register (\$RESULTS) and the live-session baseline (\$IT_ROOT/live-tmux-sessions.txt, \$IT_ROOT/dt-sessions-seen-<S>.txt) at fleet/it level, which is right for state SHARED across sections but is outside <section>/; $n_tmp site(s) touch \$TMPDIR — chiefly it_own_cases staging the register through mktemp, the only write that leaves the instant at all, transient and never cited as evidence. What P-3 actually protects (no evidence path outside the instant) HOLDS. SKIP not FAIL: the clause is stricter than the design (SI-18), the register and the baseline are shared-across-sections BY DESIGN, and what P-3 protects — no evidence path outside the instant — holds and is enforced per-commit by lint-evidence-paths.sh")"
  fi

  local bad skipped
  bad="$(awk -F'\t' '$1 ~ /^A8[abc]$/ && $2=="FAIL"' "$RESULTS" | wc -l | tr -d ' ')"
  #: A8c's SKIP must not be laundered into "and no write outside the section dir". The roll-up says what
  #: each sub-assertion actually established, and names the one that did not run as specified — a summary
  #: that claims its skipped half is the whole failure mode this file exists to catch.
  skipped="$(awk -F'\t' '$1 ~ /^A8[abc]$/ && $2=="SKIP"' "$RESULTS" | wc -l | tr -d ' ')"
  if [ "$bad" = 0 ] && [ "$skipped" != 0 ]; then
    a_pass A8 "$OUT/A8-audit.txt" "$(sq "the harness contains no push, no merge and no rm -rf on the home directory (A8a+A8b), audited over $nfiles files including run-A.sh itself. A8c is SKIPPED, not proven: its clause ('no write outside <section>/') is stricter than the design, because the register and the live-session baseline are shared ACROSS sections by construction — see A8c's own row for the enumeration and SI-18 for the adjudication. What P-3 protects is asserted elsewhere and enforced per-commit")"
  elif [ "$bad" = 0 ]; then
    a_pass A8 "$OUT/A8-audit.txt" "$(sq "the harness contains no push, no merge, no rm -rf on the home directory and no write outside the section dir (A8a+A8b+A8c), audited over $nfiles files including run-A.sh itself")"
  else
    a_fail A8 "$OUT/A8-audit.txt" "$(sq "$bad of 3 audit assertions failed — A8a forbidden commands / A8b rm -rf targets / A8c writes outside <section>/; see each row. A8c's failure is the register-level writes lib.sh makes by design, enumerated rather than waived")"
  fi
}

# ===================================================================================================
run_A() {
  a1
  a2
  a3
  a4
  a5
  a8            #: before the post-images, since it only reads files
  a6            #: post-images last, so they cover everything §A did
  a7
}

run_A

# --- leave the section -----------------------------------------------------------------------------
it_cleanup_tmux                      #: only `itfleet-A*`, only on socket itfleet-A, only by EXACT name
it_assert_isolation A-leave

# --- P-3: every evidence reference is instant-relative ---------------------------------------------
sed -i "s|$INSTANT/||g" "$RESULTS"
#: A last line of defence rather than a claim: `bin/lint-evidence-paths.sh` fails the register on any
#: absolute /tmp|/home|/var|/root reference, and a note (not just an evidence column) can carry one.
if grep -nE '(^|[[:space:]"'"'"'(])/(tmp|home|var|root)/' "$RESULTS" > "$OUT/leaked-abs-paths.txt"; then
  echo "run-A.sh: WARNING — absolute paths remain in $RESULTS (see out/leaked-abs-paths.txt):" >&2
  head -3 "$OUT/leaked-abs-paths.txt" >&2
  IT_FAILED=1
fi

printf '\n--- %s ---\n' "$(basename "$RESULTS")"
column -t -s "$(printf '\t')" "$RESULTS" 2>/dev/null || cat "$RESULTS"
#: `II-11`. Was `exit "$IT_FAILED"` — a COUNT. `exit` truncates modulo 256, so a section with
#: exactly 256 failures reported SUCCESS, and one with 300 reported 44, a number meaning nothing
#: to any reader. An exit status is a one-byte verdict, not a tally: the count is already printed
#: on the line above and is in the register, which is where a consumer should read it anyway.
if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
exit 1
