#!/usr/bin/env bash
# Plan 6 §B — instant model and layout, 14 cases.  Parallel-safe; own FLEET_HOME, own tmux socket.
#
# What this section is FOR
# -----------------------
# §K already exercised the compaction LIFECYCLE (the freeze, the presence gate reached through
# `complete`, the `abort` row) by driving real verbs. §B is the LAYOUT/NAMING half of the same model:
# every cell of `layout.REQUIREMENTS` is reached by the FOLDER NAME ALONE — an `mv` on disk and nothing
# else — and every refusal in `identity.InstantName` is reached from the outside. That distinction is the
# point rather than a shortcut: `layout.py`'s own docstring says the `W2-21` unclearable alarm survived
# because "the states were branches in code rather than rows in a table", and a test that reaches a cell
# only through the verb that writes into it cannot tell a table from a branch. Here the only thing that
# changes between a clean lint and a violation is three characters of a directory name.
#
# Where a §K case already covers a property, the note on the row says so and states this section's own
# angle instead of repeating it (B5 vs K2, B6/B7 vs K7, B8 vs K8).
#
# ISOLATION
# ---------
# §B launches nothing. No verb used here calls `session.start` — `init`, `lint`, `status`, `resume`,
# `enroll` and `harvest` only ever QUERY tmux (`ls`, `has-session`, `list-panes`), and none of those
# starts a server. So no `dt-` session is created, none is killed, and no `claude` is spawned. Two layers
# are still put between this section and the operator's live server, exactly as §§E/K do, because "the
# code path I read does not start a server" is an argument and `-L` + `TMUX_TMPDIR` are a boundary:
#
#   * `FLEET_TMUX_SOCKET=itfleet-B` (set by `it_section`), which `session.default_probes` reads, so every
#     tmux call the PRODUCT makes names a private server;
#   * `TMUX_TMPDIR` pointed at a private directory, which is the layer that survives the first one being
#     lost — `default_probes` degrades to a BARE `tmux` when the variable is empty, and a socket NAME can
#     be dropped by a missing export while a socket DIRECTORY cannot be escaped by any server name.
#
# The live (default) server is read twice, both times READ-ONLY and both times with `env -u TMUX_TMPDIR`
# so the read cannot silently become a read of the private server — a false compare in that direction is
# a vacuous isolation pass, which is worse than a failing one.
#
# THE TRAP THIS FILE WALKED INTO ONCE, RECORDED SO IT CANNOT COME BACK
# -------------------------------------------------------------------
# `${path/-inflight-/-complete-}` over a FULL path is wrong here and fails SILENTLY. This harness lives
# inside `.../00000000-07300312-inflight-append-fleetInfraRebuild/fleet/it/`, so the first
# `-inflight-` in any absolute path under `$EV` belongs to the HARNESS's own instant folder, not to the
# fixture. The substitution rewrote the wrong component, the `mv` failed with "No such file or
# directory", and the case that followed it PASSED — against a folder that had never been renamed. Every
# state rename in this file therefore goes through `b_rename_state`, which rewrites the BASENAME's third
# dash-field and refuses anything that is not a 5-field instant name, and every case that depends on a
# rename asserts the new folder exists and the old one does not.
#
# Usage: IT_RESULTS=<file> bash fleet/it/run-B.sh [all|B1..B14]
set -uo pipefail

B_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$B_HERE/lib.sh"

#: NEVER the shared RESULTS.tsv — the coordinator merges, and one register with two writers is
#: `FI-16`/`FI-29`'s own shape.
RESULTS="${IT_RESULTS:-$B_HERE/RESULTS-B.tsv}"

IT_FAILED=0
B_CLAUDE_BEFORE=""
B_TMUX_BEFORE=""

if [ ! -s "$RESULTS" ]; then
  printf 'case\tverdict\tevidence\tnote\n' > "$RESULTS"
fi

# --- recording: every evidence reference is INSTANT-RELATIVE (P-3 / `FI-32`) ------------------------
#
# Relativised at the RECORDING boundary rather than at each call site, so a case added later cannot
# reintroduce an absolute path into the register that `bin/lint-evidence-paths.sh` then fails.
b_rel() { case "${1:-}" in "$INSTANT"/*) printf '%s' "${1#"$INSTANT"/}" ;; *) printf '%s' "${1:-}" ;; esac; }
b_pass() { it_pass "$1" "$(b_rel "${2:-}")" "${3:-}"; }
b_fail() { it_fail "$1" "$(b_rel "${2:-}")" "${3:-}"; }
b_skip() { it_skip "$1" "$(b_rel "${2:-}")" "${3:-}"; }

# --- section enter / leave --------------------------------------------------------------------------

#: The ONE bare-tmux reader in this file, used twice: the live-server pre-image and post-image. `env -u
#: TMUX_TMPDIR` states in the call itself that this must reach the DEFAULT server, instead of leaving it
#: to depend on whether the caller happens to run before the export or after the unset.
#: `II-2`. This was a bare `tmux ls`, whose lines carry a window count and an `(attached)` marker — so the
#: comparison below failed when the operator merely attached to an unrelated session. `lib.sh` had already
#: learned that and says so in `it_live_tmux_sessions`; §B declined the shared helper and so did not get
#: the lesson. Names only now, exactly what the shared reader returns.
b_live_tmux() { env -u TMUX_TMPDIR tmux ls -F '#{session_name}' 2>/dev/null | sort; }

b_enter() {
  it_section B                                       # own FLEET_HOME, own slots, own socket; isolation asserted
  OUT="$EV/out"
  mkdir -p "$OUT"
  B_SOCK="/tmp/itfB"                                 # short path: a long TMUX_TMPDIR overflows sun_path
  rm -rf "$B_SOCK"; mkdir -p "$B_SOCK"
  B_TMUX_BEFORE="$(b_live_tmux)"
  B_CLAUDE_BEFORE="$(pgrep -x claude 2>/dev/null | wc -l)"
  export TMUX_TMPDIR="$B_SOCK"
  export PATH="$B_HERE/bin:$PATH"                    # the `claude` stub, never the real binary
  printf '%s\n' "$B_TMUX_BEFORE" > "$OUT/live-tmux-before.txt"
  printf '%s\n' "$B_CLAUDE_BEFORE" > "$OUT/claude-count-before.txt"
}

b_leave() {
  #: Nothing here creates a session, so there is nothing to kill — and a blanket kill loop that has no
  #: work to do is a loop waiting to be pointed at the wrong server. What IS asserted is that the
  #: private server never came into existence at all, which is the same claim one layer stronger.
  local private
  private="$(it_tmux ls -F '#{session_name}' 2>/dev/null | sort | tr '\n' ' ')"
  printf '%s\n' "${private:-(no server on socket $IT_TMUX_SOCKET — §B starts no session)}" \
    > "$OUT/private-tmux-after.txt"
  local after_claude
  after_claude="$(pgrep -x claude 2>/dev/null | wc -l)"
  #: BEFORE the live read, and it must stay before it: `it_assert_isolation` reads the live server with a
  #: bare `tmux ls`, which is only the live server while TMUX_TMPDIR is unset.
  unset TMUX_TMPDIR
  local after_tmux
  after_tmux="$(b_live_tmux)"
  printf '%s\n' "$after_tmux" > "$OUT/live-tmux-after.txt"
  printf '%s\n' "$after_claude" > "$OUT/claude-count-after.txt"
  #: `II-1`. This was a private byte-comparison — one of four copies of the isolation contract, so the fix
  #: that taught `lib.sh` to CLASSIFY the delta rather than compare it reached `lib.sh` and stopped there.
  #: Measured before the collapse: `B3`, a case that dispatches nothing and whose own sibling row states
  #: "§B launches no process at all", FAILED because `claude_mor_design_chinmay` appeared on the default
  #: server mid-run.
  #:
  #: The case id stays, so the register still carries a per-section isolation row; what is gone is the
  #: second implementation of the rule. §B creates no session at all, so there is nothing for
  #: `it_assert_no_private_leak` to check here and the classifier is this section's whole contract.
  local b_classified
  b_classified="$(it_classify_session_delta "$B_TMUX_BEFORE" "$after_tmux")"
  if [ "${b_classified%%|*}" = FAIL ]; then
    b_fail "ISOLATION-B-live-tmux" "$OUT/live-tmux-after.txt" "${b_classified#*|}"
  else
    b_pass "ISOLATION-B-live-tmux" "$OUT/live-tmux-after.txt" \
      "${b_classified#*|} §B's own private server ($IT_TMUX_SOCKET) held: ${private:-nothing — it was never started}"
  fi
  if [ "$after_claude" = "$B_CLAUDE_BEFORE" ]; then
    b_pass "ISOLATION-B-claude-count" "$OUT/claude-count-after.txt" \
      "pgrep -x claude: $after_claude before and after (A6); §B launches no process at all"
  else
    b_fail "ISOLATION-B-claude-count" "$OUT/claude-count-after.txt" \
      "pgrep -x claude went $B_CLAUDE_BEFORE -> $after_claude; no claude may launch outside §P"
  fi
  it_assert_isolation "B-leave"
  rm -rf "$B_SOCK"
}

# --- per-case sandbox ------------------------------------------------------------------------------

b_home() {                      # b_home <tag> [n_slots]
  B_TAG="$1"; local want="${2:-0}" i
  #: Built from $EV and a non-empty tag, never from a variable that could be unset: a prior agent
  #: `kill -9`'d a runner mid-`rm -rf` and destroyed 1333 tracked files.
  [ -n "${EV:-}" ] && [ -n "$B_TAG" ] || { echo "b_home: refusing to build a path from an empty EV/tag" >&2; return 2; }
  export FLEET_HOME="$EV/home/$B_TAG"
  export FLEET_INSTANTS="$EV/instants/$B_TAG"
  B_SLOTS="$SLOTS/$B_TAG"
  CD="$OUT/$B_TAG"
  rm -rf "$FLEET_HOME" "$FLEET_INSTANTS" "$B_SLOTS" "$CD"
  mkdir -p "$FLEET_HOME" "$FLEET_INSTANTS" "$B_SLOTS" "$CD"
  for i in $(seq 1 "$want"); do
    mkdir -p "$B_SLOTS/s$i"
    fleet enroll --slot "$B_SLOTS/s$i" >> "$CD/enroll.out" 2>&1
  done
}

b_run() {                       # b_run <outfile> <cmd...>  -> B_RC
  local f="$1"; shift
  "$@" > "$f" 2>&1; B_RC=$?
}

#: The instant `init` just made, from its own porcelain (`path` field) rather than from a `find`: the
#: verb's answer is the thing under test, and re-deriving it here would hide a verb that reported one
#: path and wrote another.
b_init() {                      # b_init <outfile> <init-args...>  -> B_INSTANT, B_RC
  local f="$1"; shift
  b_run "$f" fleet init --porcelain "$@"
  B_INSTANT="$(awk -F'\t' '$1=="path"{print $2}' "$f")"
}

#: Rename an instant's `<state>` field ON DISK, the way a worker does. BASENAME ONLY — see the trap note
#: in this file's header; a substitution over the full path rewrites the harness's own instant folder and
#: the `mv` then fails silently. Refuses anything that is not a 5-field instant name.
b_rename_state() {              # b_rename_state <instant-path> <new-state>  -> prints the NEW path
  local src="$1" want="$2" dir base new
  dir="$(dirname "$src")"; base="$(basename "$src")"
  new="$(printf '%s' "$base" | awk -F- -v s="$want" 'NF==5{print $1"-"$2"-"s"-"$4"-"$5}')"
  if [ -z "$new" ]; then
    echo "b_rename_state: '$base' is not a 5-field instant name; refusing to guess" >&2; return 2
  fi
  mv "$src" "$dir/$new" || return 1
  [ -d "$dir/$new" ] && [ ! -e "$src" ] || { echo "b_rename_state: rename did not take" >&2; return 1; }
  printf '%s' "$dir/$new"
}

#: A folder whose NAME is the fixture. `init` cannot create these — its `--name` is a title that
#: `identity.camel` normalises and its `--base` is validated — so the only way to put an ungrammatical
#: instant in front of the checker is to make one.
b_mkname() {                    # b_mkname <folder-name>  -> prints the path
  local path="$FLEET_INSTANTS/$1"
  mkdir -p "$path"
  printf '%s' "$path"
}

b_viol() { awk -F'\t' '$3=="violation"' "$1" | wc -l | tr -d ' '; }
b_rows_for() { awk -F'\t' -v pat="$2" '$2 ~ pat' "$1" | wc -l | tr -d ' '; }

# ===================================================================================================
# B1 / B2 — the bootstrap creates EXACTLY the canonical set, and STATE.md is not in it.
# ===================================================================================================

#: The canonical set as the matrix declares it: `CANONICAL` (6 documents) + `evidence/INDEX.md` +
#: `CANONICAL_DIRS` (3). Spelled out here rather than read out of `layout.py`, deliberately: a test that
#: imports the table it is checking asserts only that the table equals itself.
B_CANONICAL='ASSUMPTIONS.md CHARTER.md DECISIONS.md HANDOFF.md ISSUES.md RUNBOOK.md evidence evidence/INDEX.md investigations plans'

b1_init_creates_exactly_the_canonical_set() {
  b_home b1
  b_init "$CD/init.out" --name b1canonical
  local rc_init=$B_RC
  if [ "$rc_init" != 0 ] || [ -z "$B_INSTANT" ] || [ ! -d "$B_INSTANT" ]; then
    b_fail B1 "$CD/init.out" "init exit $rc_init; path='$B_INSTANT' is not a directory"; return
  fi
  local got want created
  got="$( (cd "$B_INSTANT" && find . -mindepth 1 | sed 's|^\./||' | LC_ALL=C sort) | tr '\n' ' ')"
  want="$(printf '%s ' $B_CANONICAL)"
  created="$(awk -F'\t' '$1=="created"{print $2}' "$CD/init.out")"
  b_run "$CD/lint.out" fleet lint --instant "$B_INSTANT" --porcelain
  local rc_lint=$B_RC viol
  viol="$(b_viol "$CD/lint.out")"
  { echo "instant: $(basename "$B_INSTANT")"; echo "init reported created=$created"; echo
    echo "on disk (find, sorted):"; printf '%s\n' $got | sed 's/^/  /'
    echo; echo "the canonical set the matrix declares:"; printf '%s\n' $B_CANONICAL | sed 's/^/  /'
  } > "$CD/tree.txt"
  if [ "$got" = "$want" ] && [ "$created" = 10 ] && [ "$rc_lint" = 0 ] && [ "$viol" = 0 ]; then
    b_pass B1 "$CD/tree.txt" \
      "init created EXACTLY the canonical set and nothing else (10 entries: 6 documents + evidence/INDEX.md + 3 dirs), set-equal to the matrix's declaration; lint exit 0 with 0 violations"
  else
    b_fail B1 "$CD/tree.txt" \
      "want the canonical set / created=10 / lint exit 0 with 0 violations; got created=$created lint exit $rc_lint viol=$viol; on disk='$got' want='$want'"
  fi
}

b2_state_md_is_not_created() {
  #: Both cells `init` can reach, not just the default one. `layout.py` marks `STATE.md` FORBIDDEN in
  #: every cell precisely because the `RCF-11`/FD-7 disagreement was between four consumers; asserting
  #: it for one opType would leave the second consumer of the same table untested.
  local bad="" cell path
  b_home b2
  for cell in append compact; do
    b_init "$CD/init-$cell.out" --name "b2$cell" --optype "$cell"
    path="$B_INSTANT"
    if [ "$B_RC" != 0 ] || [ ! -d "$path" ]; then bad="$bad init($cell)=exit$B_RC;"; continue; fi
    [ -e "$path/STATE.md" ] && bad="$bad $cell:STATE.md-EXISTS;"
    grep -qF 'STATE.md' "$CD/init-$cell.out" && bad="$bad $cell:init-listed-STATE.md;"
  done
  { echo "STATE.md presence after init, per cell the bootstrap can reach:"
    for cell in append compact; do
      path="$(awk -F'\t' '$1=="path"{print $2}' "$CD/init-$cell.out")"
      printf '  (inflight, %s) %s -> STATE.md %s\n' "$cell" "$(basename "${path:-none}")" \
        "$([ -e "$path/STATE.md" ] && echo PRESENT || echo absent)"
    done; } > "$CD/state-md.txt"
  if [ -z "$bad" ]; then
    b_pass B2 "$CD/state-md.txt" \
      "STATE.md absent on disk after init in BOTH cells the bootstrap can reach ((inflight,append) and (inflight,compact)), and named in neither init's created list — the seed and the gate read one table (FD-7)"
  else
    b_fail B2 "$CD/state-md.txt" "STATE.md was created or listed:$bad"
  fi
}

# B3 — GIVEN an instant that lints clean, WHEN a `STATE.md` is written into it BY HAND, THEN lint reports
# exactly one violation, under the rule `forbidden`, NAMING that file, at exit 1. The clean run before the
# write is half the case: without it, a lint that reported a violation on every instant would pass.
b3_state_md_by_hand_is_a_violation() {
  b_home b3
  b_init "$CD/init.out" --name b3state
  local instant="$B_INSTANT"
  b_run "$CD/lint-clean.out" fleet lint --instant "$instant" --porcelain
  local rc_clean=$B_RC
  printf '# STATE\n\nphase: running\n' > "$instant/STATE.md"
  b_run "$CD/lint-dirty.out" fleet lint --instant "$instant" --porcelain
  local rc_dirty=$B_RC
  local viol names rule
  viol="$(b_viol "$CD/lint-dirty.out")"
  names="$(awk -F'\t' '$3=="violation" && $2 ~ /\/STATE\.md$/{print $2}' "$CD/lint-dirty.out")"
  rule="$(awk -F'\t' '$3=="violation" && $2 ~ /\/STATE\.md$/{print $1}' "$CD/lint-dirty.out")"
  if [ "$rc_clean" = 0 ] && [ "$rc_dirty" = 1 ] && [ "$viol" = 1 ] && [ -n "$names" ] \
     && [ "$rule" = forbidden ]; then
    b_pass B3 "$CD/lint-dirty.out" \
      "clean before (exit 0); one hand-written STATE.md => exactly 1 violation, rule '$rule', NAMING $(basename "$(dirname "$names")")/STATE.md, exit 1"
  else
    b_fail B3 "$CD/lint-dirty.out" \
      "want clean exit 0 then exactly 1 'forbidden' violation naming STATE.md at exit 1; got rc_clean=$rc_clean rc_dirty=$rc_dirty viol=$viol rule='$rule' named='$names'"
  fi
}

# ===================================================================================================
# B4 — the alarm clears by DOING WHAT IT ASKED, and by nothing else.
# ===================================================================================================

b4_delete_then_restore() {
  b_home b4
  b_init "$CD/init.out" --name b4restore
  local instant="$B_INSTANT" victim="DECISIONS.md" vre='/DECISIONS[.]md$'
  #: DECISIONS.md rather than ISSUES.md: ISSUES.md is also the watched register, so deleting it would
  #: make `harvest`'s half of `lint` speak too and the row under test would no longer be the only one.
  b_run "$CD/lint-0-clean.out" fleet lint --instant "$instant" --porcelain
  local rc0=$B_RC v0; v0="$(b_viol "$CD/lint-0-clean.out")"

  rm "$instant/$victim"
  b_run "$CD/lint-1-missing.out" fleet lint --instant "$instant" --porcelain
  local rc1=$B_RC v1 named1 rule1
  v1="$(b_viol "$CD/lint-1-missing.out")"
  named1="$(awk -F'\t' -v v="$vre" '$3=="violation" && $2 ~ v{print $2}' "$CD/lint-1-missing.out")"
  rule1="$(awk -F'\t' -v v="$vre" '$3=="violation" && $2 ~ v{print $1}' "$CD/lint-1-missing.out")"

  #: THE ANTI-VACUITY CONTROL. B4 is one of the two cases most likely to pass for the wrong reason: a
  #: checker that merely re-read the folder and forgot its complaint would also go green on the restore.
  #: So an IRRELEVANT write happens first, and the alarm must STILL be up. Only then does the restore
  #: count as "the alarm cleared because the thing it named was done".
  printf 'a file the matrix says nothing about\n' > "$instant/NOTES-b4.md"
  b_run "$CD/lint-2-irrelevant-write.out" fleet lint --instant "$instant" --porcelain
  local rc2=$B_RC v2 named2
  v2="$(b_viol "$CD/lint-2-irrelevant-write.out")"
  named2="$(awk -F'\t' -v v="$vre" '$3=="violation" && $2 ~ v{print $2}' "$CD/lint-2-irrelevant-write.out")"
  rm -f "$instant/NOTES-b4.md"

  printf '# DECISIONS — restored by §B4\n\nrestored to clear the violation that named this file.\n' \
    > "$instant/$victim"
  b_run "$CD/lint-3-restored.out" fleet lint --instant "$instant" --porcelain
  local rc3=$B_RC v3; v3="$(b_viol "$CD/lint-3-restored.out")"

  if [ "$rc0" = 0 ] && [ "$v0" = 0 ] \
     && [ "$rc1" = 1 ] && [ "$v1" = 1 ] && [ -n "$named1" ] && [ "$rule1" = required ] \
     && [ "$rc2" = 1 ] && [ "$v2" = 1 ] && [ -n "$named2" ] \
     && [ "$rc3" = 0 ] && [ "$v3" = 0 ]; then
    b_pass B4 "$CD/lint-3-restored.out" \
      "delete $victim => exactly 1 'required' violation NAMING it, exit 1; an IRRELEVANT write (NOTES-b4.md) leaves the alarm up (control against a checker that clears on any change); restoring the NAMED file => 0 violations, exit 0. Both halves asserted."
  else
    b_fail B4 "$CD/lint-3-restored.out" \
      "want 0/0 -> 1 'required' naming $victim/1 -> still 1/1 after an irrelevant write -> 0/0; got exit/viol $rc0/$v0 -> $rc1/$v1 (rule='$rule1' named='$named1') -> $rc2/$v2 (named='$named2') -> $rc3/$v3"
  fi
}

# ===================================================================================================
# B5..B8 — the COMPACTED.md column of the matrix, reached by the folder name and nothing else.
# ===================================================================================================

b5_b6_b7_compaction_presence_by_rename() {
  b_home b56
  b_init "$CD/init.out" --name b5compaction --optype compact
  local instant="$B_INSTANT"
  case "$(basename "${instant:-}")" in
    *-inflight-compact-*) ;;
    *) b_fail B5 "$CD/init.out" "setup: init --optype compact did not make an -inflight-compact- folder ('$instant')"
       b_fail B6 "$CD/init.out" "setup failed in B5"; b_fail B7 "$CD/init.out" "setup failed in B5"; return ;;
  esac

  # --- B5: inflight-compact, no COMPACTED.md => INFO, exit 0 ---
  local absent=yes; [ -e "$instant/COMPACTED.md" ] && absent=no
  b_run "$CD/b5-lint.out" fleet lint --instant "$instant" --porcelain
  local rc5=$B_RC sev5 v5 rule5
  sev5="$(awk -F'\t' '$2 ~ /\/COMPACTED\.md$/{print $3}' "$CD/b5-lint.out" | head -1)"
  rule5="$(awk -F'\t' '$2 ~ /\/COMPACTED\.md$/{print $1}' "$CD/b5-lint.out" | head -1)"
  v5="$(b_viol "$CD/b5-lint.out")"
  if [ "$absent" = yes ] && [ "$rc5" = 0 ] && [ "$sev5" = info ] && [ "$rule5" = due-later ] \
     && [ "$v5" = 0 ]; then
    b_pass B5 "$CD/b5-lint.out" \
      "-inflight-compact- with no COMPACTED.md: rule 'due-later', severity info, 0 violations, exit 0. §K2 proved this for a DISPATCHED compaction; this angle is the bootstrap's own output — layout.bootstrap declines to seed a DUE_LATER file and layout.validate declines to fault it, so seed and gate agree in the same cell"
  else
    b_fail B5 "$CD/b5-lint.out" \
      "want COMPACTED.md absent + rule due-later + info + 0 violations + exit 0; got absent=$absent rule='$rule5' severity='$sev5' viol=$v5 exit $rc5"
  fi

  # --- B6: the SAME folder, renamed -complete-compact- and nothing else => VIOLATION ---
  local completed
  completed="$(b_rename_state "$instant" complete)" || {
    b_fail B6 "$CD/b5-lint.out" "could not rename to -complete-compact-"; b_fail B7 "" "B6 setup failed"; return; }
  b_run "$CD/b6-lint.out" fleet lint --instant "$completed" --porcelain
  local rc6=$B_RC v6 sev6 rule6 named6
  v6="$(b_viol "$CD/b6-lint.out")"
  sev6="$(awk -F'\t' '$2 ~ /\/COMPACTED\.md$/{print $3}' "$CD/b6-lint.out" | head -1)"
  rule6="$(awk -F'\t' '$2 ~ /\/COMPACTED\.md$/{print $1}' "$CD/b6-lint.out" | head -1)"
  named6="$(awk -F'\t' '$3=="violation" && $2 ~ /\/COMPACTED\.md$/{print $2}' "$CD/b6-lint.out")"
  if [ "$rc6" = 1 ] && [ "$v6" = 1 ] && [ "$sev6" = violation ] && [ "$rule6" = required ] \
     && [ -n "$named6" ]; then
    b_pass B6 "$CD/b6-lint.out" \
      "the SAME folder, three characters of its name changed and NOTHING else written: info becomes exactly 1 'required' violation naming COMPACTED.md, exit 1. §K7 reached this cell through the 'complete' VERB; this reaches it by an on-disk mv, so the verdict is provably the matrix row (complete,compact) and not something the 'complete' verb wrote"
  else
    b_fail B6 "$CD/b6-lint.out" \
      "want exactly 1 'required' violation naming COMPACTED.md at exit 1; got exit $rc6 viol=$v6 rule='$rule6' severity='$sev6' named='$named6'"
  fi

  # --- B7: write COMPACTED.md => clean ---
  printf '# COMPACTED — §B7 fixture\n\npresence only; §K6 records why no CONTENT contract is assertable.\n' \
    > "$completed/COMPACTED.md"
  b_run "$CD/b7-lint.out" fleet lint --instant "$completed" --porcelain
  local rc7=$B_RC v7 rows7
  v7="$(b_viol "$CD/b7-lint.out")"
  rows7="$(b_rows_for "$CD/b7-lint.out" 'COMPACTED[.]md$')"
  if [ "$rc7" = 0 ] && [ "$v7" = 0 ] && [ "$rows7" = 0 ]; then
    b_pass B7 "$CD/b7-lint.out" \
      "writing COMPACTED.md into the -complete-compact- folder clears it: 0 violations, 0 COMPACTED.md rows at all, exit 0 — the alarm cleared by doing exactly what it named (W2-21's unclearable-alarm family)"
  else
    b_fail B7 "$CD/b7-lint.out" \
      "want 0 violations, no COMPACTED.md row, exit 0; got exit $rc7 viol=$v7 COMPACTED.md-rows=$rows7"
  fi
}

b8_abort_compact_is_silent() {
  b_home b8
  b_init "$CD/init.out" --name b8aborted --optype compact
  local instant="$B_INSTANT" aborted
  aborted="$(b_rename_state "$instant" abort)" || { b_fail B8 "$CD/init.out" "could not rename to -abort-compact-"; return; }
  [ -e "$aborted/COMPACTED.md" ] && { b_fail B8 "$CD/init.out" "setup: COMPACTED.md exists"; return; }
  b_run "$CD/b8-lint.out" fleet lint --instant "$aborted" --porcelain
  local rc8=$B_RC v8 rows8
  v8="$(b_viol "$CD/b8-lint.out")"
  rows8="$(b_rows_for "$CD/b8-lint.out" 'COMPACTED[.]md$')"

  #: The other half of "abort is a ROW and not a fallthrough". `layout.requirement` refuses a
  #: `(state, opType)` pair that is not in the matrix — exit 2, not exit 0 — so a clean exit 0 here is
  #: only reachable through a real `(abort, compact)` row. Renaming the same folder on to -complete- and
  #: back proves the three cells are three rows rather than one branch with two guesses.
  local completed back
  completed="$(b_rename_state "$aborted" complete)" || true
  b_run "$CD/b8-as-complete.out" fleet lint --instant "$completed" --porcelain
  local rc_c=$B_RC v_c; v_c="$(b_viol "$CD/b8-as-complete.out")"
  back="$(b_rename_state "$completed" abort)" || true
  b_run "$CD/b8-back-to-abort.out" fleet lint --instant "$back" --porcelain
  local rc_b=$B_RC v_b rows_b
  v_b="$(b_viol "$CD/b8-back-to-abort.out")"
  rows_b="$(b_rows_for "$CD/b8-back-to-abort.out" 'COMPACTED[.]md$')"

  if [ "$rc8" = 0 ] && [ "$v8" = 0 ] && [ "$rows8" = 0 ] \
     && [ "$rc_c" = 1 ] && [ "$v_c" = 1 ] \
     && [ "$rc_b" = 0 ] && [ "$v_b" = 0 ] && [ "$rows_b" = 0 ]; then
    b_pass B8 "$CD/b8-lint.out" \
      "-abort-compact- with no COMPACTED.md: exit 0, 0 violations and NO COMPACTED.md row at all — not even an info. §K8 reached this through the 'abort' VERB; this reaches it by mv, and then mv's the same folder to -complete- (1 violation) and back to -abort- (silent again), which is what distinguishes a real (abort,compact)=OPTIONAL row from a fallthrough: an absent cell exits 2, not 0"
  else
    b_fail B8 "$CD/b8-lint.out" \
      "want abort: exit 0/0 viol/0 rows, complete: exit 1/1 viol, abort again: exit 0/0/0; got $rc8/$v8/$rows8 then $rc_c/$v_c then $rc_b/$v_b/$rows_b"
  fi
}

# ===================================================================================================
# B9..B12 — the name grammar refuses, and refuses with exit 2.
# ===================================================================================================
#
# Two vectors per case where both exist, because they are different doors on the same rule: the INPUT
# flag (`init --base`, which builds an `InstantName` before it touches the disk) and the ON-DISK name
# (`lint --instant`, which parses the folder FIRST and refuses rather than judging it, per
# `layout.validate`'s docstring). A rule enforced at one door only is `identity.py`'s own stated history:
# "the predecessor parsed this string at ten call sites with divergent rules".

b9_main_base_refused() {
  b_home b9
  b_run "$CD/b9-init.out" fleet init --base main --name b9main
  local rc_in=$B_RC
  #: Counted BEFORE the on-disk fixture is made, so "nothing was written" is about the refusal and not
  #: about a `find` filter that happens to exclude what this case created itself.
  local created; created="$(find "$FLEET_INSTANTS" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')"
  local folder; folder="$(b_mkname 'main-07301500-inflight-append-b9onDisk')"
  b_run "$CD/b9-lint.out" fleet lint --instant "$folder" --porcelain
  local rc_disk=$B_RC
  local says_in=no says_disk=no dep=no
  grep -q "base_instant='main'" "$CD/b9-init.out" && says_in=yes
  grep -q "base_instant='main'" "$CD/b9-lint.out" && says_disk=yes
  grep -qF '`main` is deprecated' "$CD/b9-init.out" && dep=yes
  if [ "$rc_in" = 2 ] && [ "$rc_disk" = 2 ] && [ "$says_in" = yes ] && [ "$says_disk" = yes ] \
     && [ "$dep" = yes ] && [ "$created" = 0 ]; then
    b_pass B9 "$CD/b9-init.out" \
      "a 'main-…' name is refused exit 2 at BOTH doors — \`init --base main\` (before anything is written: 0 folders created) and \`lint\` on a main-… folder already on disk — and both messages name base_instant='main' and say \`main\` is deprecated"
  else
    b_fail B9 "$CD/b9-init.out" \
      "want exit 2 at both doors naming base_instant='main'; got init exit $rc_in (names=$says_in, deprecated-note=$dep, folders created=$created), lint exit $rc_disk (names=$says_disk)"
  fi
}

b10_four_digit_base_refused() {
  b_home b10
  b_run "$CD/b10-init.out" fleet init --base 0715 --name b10short
  local rc_in=$B_RC
  local folder; folder="$(b_mkname '0715-07301500-inflight-append-b10onDisk')"
  b_run "$CD/b10-lint.out" fleet lint --instant "$folder" --porcelain
  local rc_disk=$B_RC
  #: The other side of the width rule, so the case cannot pass by refusing every base: 9 digits is also
  #: refused, and the canonical 8-digit root is ACCEPTED. A checker that says no to everything is not a
  #: checker.
  b_run "$CD/b10-nine.out" fleet init --base 000000000 --name b10long
  local rc_nine=$B_RC
  b_run "$CD/b10-eight.out" fleet init --base 00000000 --name b10ok --porcelain
  local rc_eight=$B_RC
  local says=no; grep -q "base_instant='0715'" "$CD/b10-init.out" && says=yes
  if [ "$rc_in" = 2 ] && [ "$rc_disk" = 2 ] && [ "$rc_nine" = 2 ] && [ "$rc_eight" = 0 ] \
     && [ "$says" = yes ]; then
    b_pass B10 "$CD/b10-init.out" \
      "a 4-digit base is refused exit 2 at both doors (\`init --base 0715\` and \`lint\` on a 0715-… folder), the message names base_instant='0715', 9 digits is refused too (exit 2), and the canonical 8-digit 00000000 is ACCEPTED (exit 0) — so the refusal is the width rule and not a blanket no"
  else
    b_fail B10 "$CD/b10-init.out" \
      "want 2/2/2 and 0 for the 8-digit control; got init(4)=$rc_in lint(4)=$rc_disk init(9)=$rc_nine init(8)=$rc_eight names=$says"
  fi
}

b11_six_dash_fields_refused() {
  b_home b11
  local folder; folder="$(b_mkname '00000000-07301500-inflight-append-two-words')"
  b_run "$CD/b11-lint.out" fleet lint --instant "$folder" --porcelain
  local rc6=$B_RC
  #: Arity in the other direction as well, so "refused" is about the GRAMMAR having exactly 5 fields
  #: rather than about "not exactly what I expected".
  local four; four="$(b_mkname '00000000-07301500-inflight-append')"
  b_run "$CD/b11-four.out" fleet lint --instant "$four" --porcelain
  local rc4=$B_RC
  local says=no g5=no
  grep -qF 'has 6 dash-separated fields' "$CD/b11-lint.out" && says=yes
  grep -qF 'the grammar has exactly 5' "$CD/b11-lint.out" && g5=yes
  if [ "$rc6" = 2 ] && [ "$rc4" = 2 ] && [ "$says" = yes ] && [ "$g5" = yes ]; then
    b_pass B11 "$CD/b11-lint.out" \
      "a 6-dash-field folder is refused exit 2 and the message COUNTS the fields ('has 6 dash-separated fields', 'the grammar has exactly 5'); a 4-field folder is refused too, so the rule is the arity and not a fixed expectation"
  else
    b_fail B11 "$CD/b11-lint.out" \
      "want exit 2 for 6 fields and for 4 fields, with the count named; got 6-field exit $rc6 (counts=$says, states-5=$g5), 4-field exit $rc4"
  fi
}

b12_dash_in_instant_name() {
  b_home b12
  # (i) the only INPUT surface that takes a name. It takes a TITLE, and normalises it.
  b_init "$CD/b12-init.out" --name 'two-words'
  local rc_in=$B_RC path="$B_INSTANT" field=""
  [ -n "$path" ] && field="$(basename "$path" | cut -d- -f5)"
  local dashless=no legal=no lint_clean=no fields=0
  [ -n "$field" ] && case "$field" in *-*) ;; *) dashless=yes ;; esac
  printf '%s' "$field" | grep -Eq '^[a-z][A-Za-z0-9]*$' && legal=yes
  [ -n "$path" ] && fields="$(basename "$path" | awk -F- '{print NF}')"
  if [ -d "${path:-/nonexistent}" ]; then
    b_run "$CD/b12-lint-normalised.out" fleet lint --instant "$path" --porcelain
    [ "$B_RC" = 0 ] && lint_clean=yes
  fi
  # (ii) the ON-DISK name field. A dash there is an arity failure (see B11); the domain check on the
  #      field itself is reachable with a name that is illegal for another reason.
  local dashy; dashy="$(b_mkname '00000000-07301500-inflight-append-two-words')"
  b_run "$CD/b12-lint-dashy.out" fleet lint --instant "$dashy" --porcelain
  local rc_dashy=$B_RC
  local uppercase; uppercase="$(b_mkname '00000000-07301500-inflight-append-TwoWords')"
  b_run "$CD/b12-lint-domain.out" fleet lint --instant "$uppercase" --porcelain
  local rc_dom=$B_RC dom_names=no
  grep -q "instantName='TwoWords'" "$CD/b12-lint-domain.out" && dom_names=yes

  { echo "B12 — 'instantName with a dash => refused'. What the build actually does, at both doors:"
    echo
    echo "  (i)  init --name 'two-words'  -> exit $rc_in, folder $(basename "${path:-none}")"
    echo "       the <instantName> field is '$field' (dashless=$dashless, matches ^[a-z][A-Za-z0-9]*\$=$legal),"
    echo "       $fields dash-fields, lint clean=$lint_clean"
    echo "       NOT a refusal. --name is a TITLE, and identity.camel normalises it by documented design:"
    echo "       'A title becomes a dashless camelCase instantName. The result is always a legal name"
    echo "       field, so a dispatch cannot produce an ungrammatical instant from an awkward title.'"
    echo
    echo "  (ii) lint on 00000000-07301500-inflight-append-two-words -> exit $rc_dashy"
    echo "       refused, but as an ARITY failure (6 dash-fields), which is B11's assertion. A dash in the"
    echo "       name position is unreachable by InstantName's per-field domain check, because"
    echo "       text.split('-') turns it into a sixth field before any field is validated."
    echo "       The per-field check on <instantName> IS real and IS reachable:"
    echo "       lint on ...-append-TwoWords -> exit $rc_dom, message names instantName='TwoWords'=$dom_names"
    echo
    echo "  So the INVARIANT the case is about holds — an instantName containing a dash cannot come into"
    echo "  existence — but it holds by normalisation at the input door and by arity at the disk door,"
    echo "  NOT by 'refused, exit 2' at the input door as the plan words it. Recorded, not smoothed over."
  } > "$CD/b12-what-happens.txt"

  if [ "$rc_in" = 0 ] && [ "$dashless" = yes ] && [ "$legal" = yes ] && [ "$fields" = 5 ] \
     && [ "$lint_clean" = yes ] && [ "$rc_dashy" = 2 ] && [ "$rc_dom" = 2 ] && [ "$dom_names" = yes ]; then
    b_pass B12 "$CD/b12-what-happens.txt" \
      "an instantName containing a dash cannot exist: the only input surface (init --name 'two-words') NORMALISES to '$field' (5 fields, dashless, lint clean) and an on-disk dash is refused exit 2. DIVERGENCE FROM THE PLAN, stated: init does NOT refuse (exit 0, by identity.camel's documented design), and a dash on disk is refused as B11's arity error, not by the <instantName> domain check — which is real and reachable (…-append-TwoWords => exit 2 naming instantName)"
    else
    b_fail B12 "$CD/b12-what-happens.txt" \
      "want init to yield a legal dashless 5-field name that lints clean, and exit 2 for both on-disk forms; got init exit $rc_in field='$field' dashless=$dashless legal=$legal fields=$fields lint_clean=$lint_clean; dash-on-disk exit $rc_dashy; domain-check exit $rc_dom (names=$dom_names)"
  fi
}

# ===================================================================================================
# B13 — a rename the recorded path predates. `status` follows it; the watcher's memory is not orphaned.
# ===================================================================================================

b13_rename_is_followed_not_orphaned() {
  # --- half 1: `status` follows the folder ---------------------------------------------------------
  #
  #: `resume` is used rather than `dispatch` and it is not a convenience: `cli._do_dispatch` HARDCODES
  #: `tmux = f"dt-{name.name}"` and launches it, and this section is forbidden from creating any `dt-`
  #: session at all. `resume` is the one verb that writes a record, takes `--tmux` (so the session name
  #: is `itfleet-B-…`), and NEVER calls `session.start` — it only asks whether the name is alive. The
  #: record it writes is the same `store.Record` a dispatch writes, which is what `status` reads.
  b_home b13s 1
  b_init "$CD/init.out" --name b13follows
  local instant="$B_INSTANT" curr tid
  if [ -z "$instant" ] || [ ! -d "$instant" ]; then
    b_fail B13 "$CD/init.out" "setup: init did not create an instant"; return
  fi
  curr="$(basename "$instant" | cut -d- -f2)"
  tid="b13follows-$curr"
  b_run "$CD/resume.out" fleet resume --instant "$instant" --slot s1 --tmux "itfleet-B-b13" --porcelain
  local rc_resume=$B_RC
  b_run "$CD/status-before.out" fleet status --id "$tid" --porcelain
  local rc_sb=$B_RC state_b path_b
  state_b="$(awk -F'\t' '$1=="evidence.folder_state"{print $2}' "$CD/status-before.out")"
  path_b="$(awk -F'\t' '$1=="evidence.instant"{print $2}' "$CD/status-before.out")"

  local completed
  completed="$(b_rename_state "$instant" complete)" || {
    b_fail B13 "$CD/resume.out" "could not rename -inflight- -> -complete-"; return; }
  b_run "$CD/status-after.out" fleet status --id "$tid" --porcelain
  local rc_sa=$B_RC state_a path_a id_a
  state_a="$(awk -F'\t' '$1=="evidence.folder_state"{print $2}' "$CD/status-after.out")"
  path_a="$(awk -F'\t' '$1=="evidence.instant"{print $2}' "$CD/status-after.out")"
  id_a="$(awk -F'\t' '$1=="identity"{print $2}' "$CD/status-after.out")"
  #: The record must still hold the STALE path. If the rename were followed by rewriting the record,
  #: "status follows a rename" would be untested — the resolver would never be exercised again.
  local rec_stale=no
  grep -qF "$(basename "$instant")" "$FLEET_HOME"/records/*.json 2>/dev/null && rec_stale=yes

  local h1=ok
  [ "$rc_resume" = 0 ] && [ "$rc_sb" = 0 ] && [ "$rc_sa" = 0 ] || h1="exit codes $rc_resume/$rc_sb/$rc_sa"
  [ "$state_b" = inflight ] || h1="$h1; folder_state before='$state_b' want inflight"
  [ "$state_a" = complete ] || h1="$h1; folder_state after='$state_a' want complete"
  [ "$path_b" = "$instant" ] || h1="$h1; path before='$path_b'"
  [ "$path_a" = "$completed" ] || h1="$h1; path after='$path_a' want '$completed'"
  [ "$id_a" = "$tid" ] || h1="$h1; identity='$id_a' want '$tid'"
  [ "$rec_stale" = yes ] || h1="$h1; the record no longer names the pre-rename path, so nothing was resolved"

  # --- half 2: the watcher's memory survives the rename -------------------------------------------
  b_home b13h
  b_init "$CD/init.out" --name b13memory
  local inst2="$B_INSTANT"
  printf '\n## IT-1 the one filed issue this register holds\n\nbody\n' >> "$inst2/ISSUES.md"
  b_run "$CD/harvest-1.out" fleet harvest --porcelain
  local rc_h1=$B_RC seen1 nseen1 new1 nostate1
  seen1="$(ls -1 "$FLEET_HOME/harvest/seen" 2>/dev/null | head -1)"
  nseen1="$(ls -1 "$FLEET_HOME/harvest/seen" 2>/dev/null | wc -l | tr -d ' ')"
  new1="$(grep -c 'new: IT-1' "$CD/harvest-1.out")"
  nostate1="$(awk -F'\t' '$1=="no-prior-state"' "$CD/harvest-1.out" | wc -l | tr -d ' ')"

  local done2
  done2="$(b_rename_state "$inst2" complete)" || {
    b_fail B13 "$CD/harvest-1.out" "could not rename the watched base -inflight- -> -complete-"; return; }
  b_run "$CD/harvest-2.out" fleet harvest --porcelain
  local rc_h2=$B_RC seen2 nseen2 zero2 nostate2
  seen2="$(ls -1 "$FLEET_HOME/harvest/seen" 2>/dev/null | head -1)"
  nseen2="$(ls -1 "$FLEET_HOME/harvest/seen" 2>/dev/null | wc -l | tr -d ' ')"
  zero2="$(grep -c '0 new' "$CD/harvest-2.out")"
  nostate2="$(awk -F'\t' '$1=="no-prior-state"' "$CD/harvest-2.out" | wc -l | tr -d ' ')"

  local h2=ok
  [ "$nseen1" = 1 ] || h2="one seen file expected before the rename, found $nseen1"
  [ "$new1" -ge 1 ] || h2="$h2; the first tick did not announce IT-1"
  [ "$nostate1" = 1 ] || h2="$h2; the first tick should report no-prior-state exactly once, got $nostate1"
  [ "$nseen2" = 1 ] || h2="$h2; the rename left $nseen2 seen file(s) — an orphan plus a new one is the defect"
  [ "$seen1" = "$seen2" ] || h2="$h2; the state file MOVED: '$seen1' -> '$seen2'"
  [ "$zero2" -ge 1 ] || h2="$h2; the post-rename tick did not report '0 new' — memory was lost"
  [ "$nostate2" = 0 ] || h2="$h2; the post-rename tick reported no-prior-state, i.e. the memory was orphaned"
  [ "$rc_h1" = 1 ] || h2="$h2; first tick exit $rc_h1 (want 1: the no-prior-state violation)"
  [ "$rc_h2" = 0 ] || h2="$h2; second tick exit $rc_h2 (want 0)"

  { echo "half 1 — status follows the rename"
    echo "  record todo_id      : $tid   (record still names $(basename "$instant"): $rec_stale)"
    echo "  before the rename   : folder_state=$state_b instant=$(basename "${path_b:-none}")"
    echo "  after  the rename   : folder_state=$state_a instant=$(basename "${path_a:-none}") identity=$id_a"
    echo "  verdict             : $h1"
    echo
    echo "half 2 — the watcher's state file is not orphaned"
    echo "  tick 1 (pre-rename) : exit $rc_h1, seen files=$nseen1 ('$seen1'), no-prior-state rows=$nostate1"
    echo "  renamed base        : $(basename "$inst2") -> $(basename "$done2")"
    echo "  tick 2 (post-rename): exit $rc_h2, seen files=$nseen2 ('$seen2'), '0 new' rows=$zero2, no-prior-state rows=$nostate2"
    echo "  verdict             : $h2"
    echo
    echo "MECHANISM, and a fragility worth naming: the memory survives because harvest.register dedups on"
    echo "_base_key() (which OMITS <state>) and keeps the ORIGINALLY registered base string, so"
    echo "Harvest._seen_path recomputes the same filename. _seen_path itself is NOT state-independent —"
    echo "it is sha1(source.base) plus the sanitised basename, both of which contain '-inflight-'. The"
    echo "invariant therefore rests on nothing ever rewriting entry['base'], not on the key omitting the"
    echo "state as the plan's parenthesis says. Filed as an observation, not a failure: the observable"
    echo "behaviour is correct today."
  } > "$CD/b13.txt"

  if [ "$h1" = ok ] && [ "$h2" = ok ]; then
    b_pass B13 "$CD/b13.txt" \
      "-inflight- -> -complete- renamed on disk with no verb: status follows it (folder_state inflight->complete, evidence.instant becomes the NEW path, identity unchanged) while the record still names the STALE path, so the resolver is what did the work; and the watcher's memory is not orphaned — ONE seen file with the SAME name before and after, the post-rename tick reads '0 new' and stops reporting no-prior-state (exit 1 -> 0)"
  else
    b_fail B13 "$CD/b13.txt" "half1: $h1 | half2: $h2"
  fi
}

# ===================================================================================================
# B14 — two instants in the same minute. Each resolves to itself, neither to the other.
# ===================================================================================================

b14_same_minute_siblings() {
  b_home b14
  #: ORDERING IS THE CASE. The `-abort-` sibling is created FIRST and, being 'abort', sorts before
  #: 'complete' in `identity.resolve`'s `sorted(parent.iterdir())`. A resolver keyed on base-curr (or on
  #: any prefix) walks that sorted list and returns the FIRST match, which is the abort sibling — so with
  #: this ordering the historical defect (`OBS-14`) answers alpha to a query about beta. Reversed, the
  #: right answer comes out first and the case passes without testing anything.
  b_init "$CD/init-alpha.out" --name alpha
  local a="$B_INSTANT"
  b_init "$CD/init-beta.out" --name beta
  local b="$B_INSTANT"
  if [ -z "$a" ] || [ -z "$b" ]; then b_fail B14 "$CD/init-alpha.out" "setup: init failed"; return; fi

  #: The same minute, deterministically. Two `init`s a second apart across a minute boundary would give
  #: two `curr` stamps and the case would silently stop being about a collision — so beta is moved on to
  #: alpha's `curr` rather than hoping the clock cooperates. That is the same class of silent-vacuity the
  #: ordering note above is about.
  local curr dir abort_sib complete_sib
  curr="$(basename "$a" | cut -d- -f2)"
  dir="$FLEET_INSTANTS"
  abort_sib="$dir/00000000-$curr-abort-append-alpha"
  complete_sib="$dir/00000000-$curr-complete-append-beta"
  mv "$a" "$abort_sib" || { b_fail B14 "$CD/init-alpha.out" "could not place the abort sibling"; return; }
  mv "$b" "$complete_sib" || { b_fail B14 "$CD/init-beta.out" "could not place the complete sibling"; return; }
  ls -la --time-style=full-iso "$dir" > "$CD/siblings.txt" 2>&1
  { echo; echo "sorted(iterdir) order, i.e. the order identity.resolve walks:"; ls -1 "$dir" | LC_ALL=C sort; } \
    >> "$CD/siblings.txt"
  local first
  first="$(ls -1 "$dir" | LC_ALL=C sort | head -1)"

  # Each stale -inflight- path must resolve to ITS OWN sibling.
  b_run "$CD/b14-beta.out" fleet lint --instant "00000000-$curr-inflight-append-beta" --porcelain
  local rc_beta=$B_RC got_beta
  got_beta="$(awk -F'\t' '$1=="population"{print $2; exit}' "$CD/b14-beta.out")"
  b_run "$CD/b14-alpha.out" fleet lint --instant "00000000-$curr-inflight-append-alpha" --porcelain
  local rc_alpha=$B_RC got_alpha
  got_alpha="$(awk -F'\t' '$1=="population"{print $2; exit}' "$CD/b14-alpha.out")"
  #: THE ANTI-VACUITY CONTROL. A third name in the same minute resolves to NEITHER. Without it, "both
  #: resolved to themselves" is also what a resolver that just returns `parent/<name-you-asked-for>`
  #: would produce, and this case would pass on an implementation that cannot collide at all.
  b_run "$CD/b14-gamma.out" fleet lint --instant "00000000-$curr-inflight-append-gamma" --porcelain
  local rc_gamma=$B_RC gamma_refused=no
  grep -qF 'is not an instant on disk' "$CD/b14-gamma.out" && gamma_refused=yes

  local why=ok
  [ "$first" = "$(basename "$abort_sib")" ] || why="the abort sibling is not first in sort order ('$first'), so the ordering the case depends on is not in place"
  [ "$rc_beta" = 0 ] || why="$why; lint on the stale beta path exited $rc_beta"
  [ "$got_beta" = "$complete_sib" ] || why="$why; stale beta resolved to '$got_beta', want '$complete_sib'"
  [ "$rc_alpha" = 0 ] || why="$why; lint on the stale alpha path exited $rc_alpha"
  [ "$got_alpha" = "$abort_sib" ] || why="$why; stale alpha resolved to '$got_alpha', want '$abort_sib'"
  [ "$rc_gamma" = 2 ] || why="$why; a third same-minute name exited $rc_gamma, want 2"
  [ "$gamma_refused" = yes ] || why="$why; the third name was not refused as 'not an instant on disk'"

  { echo "two instants, one minute (curr=$curr), the abort sibling created FIRST and sorting first:"
    echo "  $(basename "$abort_sib")"
    echo "  $(basename "$complete_sib")"
    echo "sort order walked by identity.resolve: first entry is '$first'"
    echo
    echo "  stale 00000000-$curr-inflight-append-beta   -> exit $rc_beta  $(basename "${got_beta:-none}")"
    echo "  stale 00000000-$curr-inflight-append-alpha  -> exit $rc_alpha  $(basename "${got_alpha:-none}")"
    echo "  stale 00000000-$curr-inflight-append-gamma  -> exit $rc_gamma  refused='$gamma_refused'"
    echo
    echo "verdict: $why"; } > "$CD/b14.txt"

  if [ "$why" = ok ]; then
    b_pass B14 "$CD/b14.txt" \
      "same minute (curr=$curr), the -abort- sibling created FIRST and sorting first: the stale -inflight-…-beta path resolves to -complete-…-beta and NOT to the abort sibling that precedes it, the stale -inflight-…-alpha path resolves to -abort-…-alpha, and a THIRD same-minute name (gamma) resolves to nothing at all (exit 2) — the control that stops this passing on a resolver that cannot collide"
  else
    b_fail B14 "$CD/b14.txt" "$why"
  fi
}

# ===================================================================================================

B_ARG="${1:-all}"
#: This runner OWNS its rows (`SI-4`): prior rows for the cases THIS invocation writes are dropped first,
#: so the register is the CURRENT verdict per case rather than an append-only log read backwards. Scoped
#: to the SELECTION — a single-case re-run must not delete the other thirteen it is not going to write.
b_owned_cases() {
  local iso='ISOLATION-B-(enter|leave|live-tmux|claude-count)'
  case "$1" in
    all)              printf 'B([1-9]|1[0-4])|%s' "$iso" ;;
    B[1-9]|B1[0-4])   printf '%s|%s' "$1" "$iso" ;;
    #: An unrecognised argument exits 2 below without running anything, so it must own nothing: a regex
    #: that matched everything here would wipe the register on a typo.
    *)                printf 'B-OWNS-NOTHING' ;;
  esac
}
it_own_cases "$(b_owned_cases "$B_ARG")"

run_B() {
  b1_init_creates_exactly_the_canonical_set
  b2_state_md_is_not_created
  b3_state_md_by_hand_is_a_violation
  b4_delete_then_restore
  b5_b6_b7_compaction_presence_by_rename
  b8_abort_compact_is_silent
  b9_main_base_refused
  b10_four_digit_base_refused
  b11_six_dash_fields_refused
  b12_dash_in_instant_name
  b13_rename_is_followed_not_orphaned
  b14_same_minute_siblings
}

case "$B_ARG" in
  all) b_enter; run_B; b_leave ;;
  B1)  b_enter; b1_init_creates_exactly_the_canonical_set; b_leave ;;
  B2)  b_enter; b2_state_md_is_not_created; b_leave ;;
  B3)  b_enter; b3_state_md_by_hand_is_a_violation; b_leave ;;
  B4)  b_enter; b4_delete_then_restore; b_leave ;;
  B5|B6|B7) b_enter; b5_b6_b7_compaction_presence_by_rename; b_leave ;;
  B8)  b_enter; b8_abort_compact_is_silent; b_leave ;;
  B9)  b_enter; b9_main_base_refused; b_leave ;;
  B10) b_enter; b10_four_digit_base_refused; b_leave ;;
  B11) b_enter; b11_six_dash_fields_refused; b_leave ;;
  B12) b_enter; b12_dash_in_instant_name; b_leave ;;
  B13) b_enter; b13_rename_is_followed_not_orphaned; b_leave ;;
  B14) b_enter; b14_same_minute_siblings; b_leave ;;
  *) echo "usage: $0 [all|B1..B14]" >&2; exit 2 ;;
esac

#: P-3 / `FI-32`: the register cites INSTANT-RELATIVE paths only, or `bin/lint-evidence-paths.sh` fails
#: it. `b_rel` already relativises at the recording boundary; this is the belt to that braces, and it is
#: what `run-group3.sh` and `run-group5.sh` both end with.
sed -i "s|$INSTANT/||g" "$RESULTS"

printf '\n--- %s ---\n' "$(basename "$RESULTS")"
column -t -s "$(printf '\t')" "$RESULTS" 2>/dev/null || cat "$RESULTS"
exit "${IT_FAILED:-0}"
