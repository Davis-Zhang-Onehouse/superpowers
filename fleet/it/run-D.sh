#!/usr/bin/env bash
# Plan 6 §D — dispatch and rollback (D1–D11), against a real filesystem, a real tmux server, real
# permission failures and real SIGKILLs.
#
# WHAT THIS SECTION IS FOR
# ------------------------
# §D is the transaction: gates → claim → gates again → render → write the tree → record → launch. The
# hermetic suite injects every edge of it, so nothing there can observe a `chmod 000`, a `FileExistsError`
# from a real `mkdir`, or a process that stops existing halfway through. D9–D11 are the three cases no
# unit test can do, and the judge for all three is `DECISIONS.md` FD-14:
#
#   "The fallible steps — render the profile, validate flags, evaluate guards — happen BEFORE the child
#    folder exists. Rollback releases the lease and NAMES whatever it left behind."
#
# So "no half-built instant" is a claim about the ORDER of the transaction, and it is tested as one: each
# injection is placed at a known point in that order, and what is left behind is compared against what
# FD-14 promises for that point. Two of the three literal injections in the plan turn out not to land at
# all (D9, and half of D10) — those are reported as SKIP/FAIL with the reason rather than passed
# vacuously, and a substitute injection that DOES land is run beside them so the rollback path itself is
# still exercised.
#
# THE FOUR DEVIATIONS FROM THE PLAN'S OWN WORDING, STATED UP FRONT
# ---------------------------------------------------------------
#  1. `--no-launch` (D2) DOES NOT EXIST on any verb. `run-group3.sh` recorded this already. D2 is a SKIP
#     naming it, and D2b asserts the half of D2 that a real dispatch can reach. The PENDING-LAUNCH half
#     is unreachable together with "lease held": the only paths to PENDING-LAUNCH are (a) a launch that
#     failed, which releases the lease, and (b) a claim with no record, which has no child instant and no
#     record. Both are demonstrated (D2b, D11) so the reader can see it is a gap and not an untested
#     guess.
#  2. `dispatch` NEVER READS THE DECLARED GOLDEN and never clones it. `_do_dispatch` calls
#     `workspace.isolate_build_cache(lease.path)` and nothing else on `Workspace`; there is no `clone` in
#     the package at all. So D9's "golden path unreadable (chmod 000)" cannot fail a dispatch — D9 proves
#     the injection is INERT (the dispatch succeeds with the golden at mode 000) and SKIPs, and D9b
#     injects the same failure one step downstream, on the slot the golden would have been cloned INTO,
#     which is where the real `PermissionError` lands.
#  3. "The child path already exists" has two forms and they behave completely differently. As a FILE
#     (D10a) it is a real `FileExistsError` inside `layout.bootstrap` and rolls back correctly. As a
#     DIRECTORY (D10b) — which is what a same-minute, same-base, same-title second dispatch produces,
#     the collision `identity.stable_key`'s own docstring names (OBS-14) — there is NO failure and NO
#     rollback: the running worker's `CHARTER.md` is overwritten and its record is replaced. D10b FAILs.
#  4. "No leaked lease" cannot hold under SIGKILL (D11) and FD-14 does not promise that it does: a killed
#     process runs no rollback. The property that IS FD-14's is asserted instead — the leak is a state
#     with a name (`reconcile` pass 3 / `stale-lease`) and `reap` recovers it AND SAYS SO — and the
#     plan's wording is reported as needing amendment.
#
# NOT VACUOUS, BY CONSTRUCTION
# ----------------------------
# Two specific traps, both with a precedent in this instant's own evidence:
#   * D1's zero delta is worthless if the manifest is blind, so the SAME dispatch is run WITHOUT
#     `--dry-run` in a twin sandbox and the manifest is required to MOVE. Zero delta is only reported
#     against a manifest that has just been shown to be sensitive.
#   * D9–D11's "no lease, no instant, no record" passes trivially if the injection fired before anything
#     existed (§E9's E9 asserted nothing in ~82% of its iterations). Every one of these cases therefore
#     records WHERE in the transaction it fired and what existed at that moment: D9b and D10a assert the
#     rollback SENTENCE names the path the product actually left on disk, and D11/D11b log a per-iteration
#     window and fail if too few iterations landed inside the transaction at all.
#
# ISOLATION
# ---------
#   * `it_section D` → own FLEET_HOME under D/home, own slots, own tmux SERVER `-L itfleet-D`, exported
#     as FLEET_TMUX_SOCKET so every `fleet` subprocess agrees with the harness about which server it is.
#   * TMUX_TMPDIR is pointed at a private socket DIRECTORY as well, exactly as run-group3.sh does and for
#     its reason: a socket NAME can be lost by a dropped export and `session.default_probes` then degrades
#     to a BARE `tmux`, which is a `dt-` session on the operator's live server. A socket DIRECTORY cannot
#     be escaped by any server name. The two compose; the cost is that a read of the LIVE server must not
#     see TMUX_TMPDIR, so `d_live_tmux` uses `env -u TMUX_TMPDIR` rather than depending on statement order.
#   * `dispatch` HARDCODES its session name as `dt-{instantName}` (`cli._do_dispatch`; only `resume` has
#     `--tmux`). A `dt-` session is therefore unavoidable — and lands on `itfleet-D`, never on the live
#     server. The live server's session-name set is snapshotted before and compared after; the live stores
#     are compared by `it_assert_isolation`; `pgrep -x claude` is compared before and after (the stub at
#     bin/claude is first on PATH and `exec sleep`s, so its comm is never `claude`).
#   * Every `chmod 000` is registered and restored by an EXIT trap. Every kill is `kill -9 <a pid this
#     harness captured>`; there is no `pkill` and no `kill-server` anywhere in this file.
#
# Usage: IT_RESULTS=<file> bash fleet/it/run-D.sh
set -uo pipefail

D_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$D_HERE/lib.sh"

#: NEVER the shared RESULTS.tsv: §C is being written concurrently and one register with two writers is
#: FI-16/FI-29's own shape.
RESULTS="${IT_RESULTS:-$D_HERE/RESULTS-D.tsv}"
[ -s "$RESULTS" ] || printf 'case\tverdict\tevidence\tnote\n' > "$RESULTS"

IT_FAILED=0

PROFILES="$INSTANT/tests/fixtures/profiles"
P_WORKER="$PROFILES/workerCompliant"            # kind=worker  → opType append
P_COMPACT="$PROFILES/compaction"                # kind=compaction → opType compact
#: seed.txt names {{RUN_ID}}, which the dispatch context ({TITLE,INSTANT,SLOT,TODO_ID,BASE,PATH}) does
#: not supply — i.e. the "unresolvable token" D5 asks for, already in the fixtures.
P_TOKEN="$PROFILES/placeholders"
P_NOKIND="$PROFILES/_invalid/undeclaredKind"    # profile.json with no "kind" field
P_NOMANIFEST="$PROFILES/_invalid/proseOnlyKind" # no profile.json at all; the kind is only in prose
BASE=00000000

D_LIVE_BEFORE=""
D_CLAUDE_BEFORE=""
D_SOCK=""
D_CHMOD_RESTORE=()

# --- recording ------------------------------------------------------------------------------------
#
# P-3 / FI-32: every evidence reference and every note is INSTANT-RELATIVE. Relativised at the recording
# boundary rather than at 40 call sites, so a case added later cannot reintroduce it — and it is done for
# the NOTE as well as the path, because `bin/lint-evidence-paths.sh` rejects an absolute path anywhere in
# the file including inside a note, and product diagnostics quote absolute paths freely. Anything still
# absolute after the instant prefix is stripped (a traceback through the interpreter's own tree, say) is
# elided rather than smuggled through. Newlines and tabs are flattened for the same reason: a note with a
# tab in it silently invents a column.
#: The delimiter is `!` and not `|`, because `\|` under a `|` delimiter is an ESCAPED DELIMITER (a literal
#: pipe) and not an alternation — the elision would silently never fire, which is the failure mode where a
#: sanitiser reads as working right up until the day it matters.
d_san() {
  printf '%s' "${1:-}" \
    | tr '\n\t' '  ' \
    | sed -e "s!$INSTANT/!!g" \
          -e "s!\(^\|[[:space:]\"'(]\)/\(tmp\|home\|var\|root\)/[^[:space:]\"')]*!\1<abs-path-elided>!g" \
    | sed -e 's/  */ /g' -e 's/^ //' -e 's/ $//' \
    | cut -c1-900
}
d_pass() { it_pass "$1" "$(d_san "${2:-}")" "$(d_san "${3:-}")"; }
d_fail() { it_fail "$1" "$(d_san "${2:-}")" "$(d_san "${3:-}")"; }
d_skip() { it_skip "$1" "$(d_san "${2:-}")" "$(d_san "${3:-}")"; }

#: This runner OWNS these rows: a re-run REPLACES them rather than appending a second opinion (SI-4).
#: `enter|leave` are `it_assert_isolation`'s; `live-tmux|claude-count` are this file's own two. Every id
#: is D-scoped, so §C's rows in a shared file could not be touched even if one were used.
it_own_cases 'D[0-9]+[a-z]?|ISOLATION-D-(enter|leave|live-tmux|claude-count|private-leak)'

# --- enter / leave --------------------------------------------------------------------------------

#: The LIVE (default) server. The ONE bare-tmux reader in this file, read-only, used twice: pre-image and
#: post-image. `env -u TMUX_TMPDIR` states in the call itself that this must not resolve to the private
#: socket directory — otherwise the "after" is a private server compared against a live pre-image, which
#: is a false compare in the direction that reads as a pass.
d_live_tmux() { env -u TMUX_TMPDIR tmux ls -F '#{session_name}' 2>/dev/null | sort; }
#: The PID SET, not just the count. A count comparison fires on the operator's own churn as loudly as on a
#: launch — SI-1's exact shape, one control over: this section's first run failed `claude-count` on 9 -> 8,
#: a DECREASE, which no section can cause (nothing here starts or signals a claude; every kill in this file
#: targets a pid this harness spawned). A set makes the two directions separable, so the rule the contract
#: actually states — "no claude is launched outside §P" — is asserted on ADDITIONS, and a removal is
#: reported by pid rather than either failing the section or being silently tolerated.
d_claude_pids() { pgrep -x claude 2>/dev/null | sort -n; }

d_restore_chmod() {
  local p
  for p in "${D_CHMOD_RESTORE[@]:-}"; do
    [ -n "$p" ] && chmod -R u+rwX "$p" 2>/dev/null
  done
  true
}
#: Registered so the EXIT trap can always put it back, even if a case dies mid-way. A 000 directory left
#: behind would make the next run's own `rm -rf` fail and read as a product defect.
d_chmod000() { chmod 000 "$1" && D_CHMOD_RESTORE+=("$1"); }
trap 'd_restore_chmod' EXIT

d_enter() {
  D_LIVE_BEFORE="$(d_live_tmux)"
  D_CLAUDE_BEFORE="$(d_claude_pids)"
  it_section D                     # own FLEET_HOME / slots / socket; live stores + live sessions asserted
  #: A short path: a long TMUX_TMPDIR overflows sun_path. This is a SOCKET directory, not evidence — the
  #: "never /tmp" rule is about where proof lands, and run-group3.sh set the same precedent for the same
  #: sun_path reason.
  D_SOCK="/tmp/itfD.$$"
  rm -rf "$D_SOCK"; mkdir -p "$D_SOCK"
  export TMUX_TMPDIR="$D_SOCK"
  export PATH="$IT_ROOT/bin:$PATH"               # the `claude` stub, first
  mkdir -p "$EV/out" "$EV/bin" "$EV/home" "$EV/instants"
  printf '%s\n' "$D_LIVE_BEFORE" > "$EV/out/live-tmux-before.txt"
  printf '%s\n' "$D_CLAUDE_BEFORE" > "$EV/out/claude-pids-before.txt"
}

#: Kills only sessions on the PRIVATE server, by EXACT name (`=`, FI-23/SI-2 — a prefix target destroyed a
#: live session in N7c). It cannot filter on TMUX_PREFIX the way `it_cleanup_tmux` does, because the
#: sessions this section creates are named `dt-<instantName>` by the product; so the scope is "everything
#: on this server", which is correct ONLY because the server is provably the private one — re-checked here
#: rather than assumed.
d_kill_private_sessions() {
  case "${IT_TMUX_SOCKET:-}" in
    itfleet-D) ;;
    *) echo "d_kill_private_sessions: socket is '${IT_TMUX_SOCKET:-}', not itfleet-D. This loop kills" \
            "every session it is shown — refusing to run it against that." >&2
       return 2 ;;
  esac
  it_tmux ls -F '#{session_name}' 2>/dev/null > "$EV/out/private-tmux-sessions.txt"
  while read -r s; do
    [ -n "$s" ] && it_tmux kill-session -t "=$s" 2>/dev/null
  done < "$EV/out/private-tmux-sessions.txt"
  true
}

d_leave() {
  d_kill_private_sessions
  local after_claude after_tmux added removed
  after_claude="$(d_claude_pids)"
  after_tmux="$(d_live_tmux)"
  printf '%s\n' "$after_tmux" > "$EV/out/live-tmux-after.txt"
  #: `II-1`. Was a private byte-comparison — the copy that mattered most, because it is the one that
  #: caught something the shared classifier cannot. Split into the two questions it was conflating, each
  #: with a single implementation:
  #:
  #:   ISOLATION-D-live-tmux     the general contract, via `it_classify_session_delta`. Operator churn on
  #:                             a shared box becomes a NOTE instead of a failure — the point of the fix.
  #:   ISOLATION-D-private-leak  what the classifier CANNOT decide, and the reason this comparison could
  #:                             not simply be deleted. The classifier judges by NAME SHAPE, and §D's
  #:                             sessions are named `dt-<instant>` by `cli._do_dispatch`, not `itfleet-*`
  #:                             — so a leaked one carries no harness prefix and reads as another
  #:                             operator's dispatch. Asserting this section's EXACT session names is
  #:                             free of false positives and strictly stronger than byte-equality for
  #:                             the leak itself: it names the session instead of diffing everything.
  #:
  #: The old PASS note cited `private-tmux-sessions.txt` as evidence while asserting nothing whatever
  #: about it. It is now an assertion rather than a citation.
  local d_classified
  d_classified="$(it_classify_session_delta "$D_LIVE_BEFORE" "$after_tmux")"
  if [ "${d_classified%%|*}" = FAIL ]; then
    d_fail ISOLATION-D-live-tmux "$EV/out/live-tmux-after.txt" "${d_classified#*|}"
  else
    d_pass ISOLATION-D-live-tmux "$EV/out/live-tmux-after.txt" \
      "${d_classified#*|} ($(printf '%s' "$after_tmux" | grep -c .) sessions, $(printf '%s' "$after_tmux" | grep -c '^dt-') of them dt-)"
  fi
  it_assert_no_private_leak ISOLATION-D-private-leak "$EV/out/private-tmux-sessions.txt" \
    "dt-* dispatch sessions: no name-shape rule can catch these, only the exact names"
  printf '%s\n' "$after_claude" > "$EV/out/claude-pids-after.txt"
  #: Attributed, not merely detected. `added` alone still charged this section for another operator's
  #: fork-before-exec transient — the ADDITION half of the same blind spot the DECREASE note above
  #: describes. A claude §D launched has its cwd in a slot under $INSTANT and still FAILS; every dispatch
  #: here launches the stub at bin/claude, which execs sleep, so no pane process is ever named claude.
  local d_claude
  d_claude="$(it_classify_claude_delta "$D_CLAUDE_BEFORE" "$after_claude")"
  if [ "${d_claude%%|*}" = FAIL ]; then
    d_fail ISOLATION-D-claude-count "$EV/out/claude-pids-after.txt" "${d_claude#*|}"
  else
    d_pass ISOLATION-D-claude-count "$EV/out/claude-pids-after.txt" "${d_claude#*|} (A6)"
  fi
  #: BEFORE it_assert_isolation, which reads the live server with a bare `tmux ls`.
  unset TMUX_TMPDIR
  it_assert_isolation D-leave
  case "$D_SOCK" in /tmp/itfD.*) rm -rf "$D_SOCK" ;; esac
}

# --- per-case sandbox -----------------------------------------------------------------------------

#: Every case gets its own FLEET_HOME, instants dir, slot set and log dir. `rm -rf` builds every path from
#: $EV and refuses if $EV is not this section's own directory or if the tag is empty — a prior agent
#: destroyed 1333 tracked files by being killed mid-`rm -rf`, and the defence is that the path cannot be
#: wrong rather than that the run cannot be interrupted.
d_home() {                        # d_home <tag> [n_slots]
  local want="${2:-0}" i
  D_TAG="${1:?d_home needs a tag}"
  case "${EV:-}" in
    "$IT_ROOT/D") ;;
    *) echo "d_home: EV is '${EV:-}', not this section's dir. Refusing to rm -rf under it." >&2; exit 2 ;;
  esac
  export FLEET_HOME="$EV/home/$D_TAG"
  export FLEET_INSTANTS="$EV/instants/$D_TAG"
  D_SLOTS="$SLOTS/$D_TAG"
  CD="$EV/out/$D_TAG"
  D_LEASES="$FLEET_HOME/pool/leases"
  D_RECORDS="$FLEET_HOME/records"
  #: A case that chmod-000'd a slot must not leave the next run unable to clear it.
  chmod -R u+rwX "$D_SLOTS" 2>/dev/null
  rm -rf "$FLEET_HOME" "$FLEET_INSTANTS" "$D_SLOTS" "$CD"
  mkdir -p "$FLEET_HOME" "$FLEET_INSTANTS" "$D_SLOTS" "$CD"
  for i in $(seq 1 "$want"); do
    mkdir -p "$D_SLOTS/s$i"
    fleet enroll --slot "$D_SLOTS/s$i" >> "$CD/enroll.out" 2>&1
  done
}

#: Content AND mtime, over everything a dispatch could touch: the store (records, pool, harvest registry,
#: golden), the slots, the instants dir, and the PROFILE directory it reads — so "it wrote nothing" covers
#: the input it was handed as well as the outputs it owns.
d_manifest() { it_manifest "$FLEET_HOME" "$D_SLOTS" "$FLEET_INSTANTS" "$PROFILES"; }

d_n_records()  { find "$D_RECORDS" -maxdepth 1 -name '*.json' 2>/dev/null | wc -l | tr -d ' '; }
d_n_leases()   { find "$D_LEASES" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' '; }
d_n_children() { find "$FLEET_INSTANTS" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' '; }
d_held()       { fleet leases --porcelain 2>/dev/null | awk -F'\t' '$2=="held"' | wc -l | tr -d ' '; }

#: Run a fleet verb, keep stdout+stderr and the exit code. `rc` in a global so a case can assert on the
#: code and the text separately without re-running (a re-run of a mutating verb is a different fact).
d_run() {                         # d_run <logfile> <verb...>   -> D_RC, log written
  local log="$1"; shift
  fleet "$@" > "$log" 2>&1
  D_RC=$?
  return 0
}

# ==================================================================================================
# D1 — `dispatch --dry-run` writes nothing, over a manifest just shown to be sensitive
# ==================================================================================================

d1_dry_run_zero_delta() {
  d_home d1 1
  local before after dry_cd
  dry_cd="$CD"
  before="$(d_manifest)"; printf '%s\n' "$before" > "$dry_cd/manifest-before.txt"
  d_run "$dry_cd/dry.out" dispatch --profile "$P_WORKER" --title "d1 dry" --base "$BASE" --cap 9 --dry-run
  local dry_rc="$D_RC"
  after="$(d_manifest)"; printf '%s\n' "$after" > "$dry_cd/manifest-after.txt"
  local delta records leases
  delta="$(diff <(printf '%s\n' "$before") <(printf '%s\n' "$after") | grep -c '^[<>]')"
  records="$(d_n_records)"; leases="$(d_n_leases)"

  #: The control. A zero delta means nothing unless the same command, without the flag, MOVES this
  #: manifest — otherwise D1 is a statement about the manifest's blindness.
  d_home d1-real 1
  local rbefore rafter rdelta
  rbefore="$(d_manifest)"
  d_run "$CD/real.out" dispatch --profile "$P_WORKER" --title "d1 real" --base "$BASE" --cap 9
  rafter="$(d_manifest)"
  rdelta="$(diff <(printf '%s\n' "$rbefore") <(printf '%s\n' "$rafter") | grep -c '^[<>]')"
  printf 'dry-run delta %s lines\nreal delta %s lines\n' "$delta" "$rdelta" > "$CD/sensitivity.txt"

  if [ "$rdelta" -lt 5 ]; then
    d_fail D1 "$dry_cd/manifest-after.txt" \
      "CANNOT JUDGE: the control dispatch (same command, no --dry-run) moved the manifest by only $rdelta line(s), so a zero delta from the dry run would prove nothing about the dry run"
  elif [ "$delta" = 0 ] && [ "$dry_rc" = 0 ] && [ "$records" = 0 ] && [ "$leases" = 0 ]; then
    d_pass D1 "$dry_cd/manifest-after.txt" \
      "exit 0 and ZERO delta over $(printf '%s\n' "$before" | grep -c .) paths (sha256 AND mtime) across the store, the pool, the slots, the instants dir and the profile dir; 0 records and 0 lease dirs created. The identical command without --dry-run moves the same manifest by $rdelta lines, so the manifest is sensitive and the zero is a fact about the dry run"
  else
    d_fail D1 "$dry_cd/manifest-after.txt" \
      "dry run exit $dry_rc, manifest delta $delta line(s), records=$records lease-dirs=$leases (control delta $rdelta): $(diff <(printf '%s\n' "$before") <(printf '%s\n' "$after") | grep '^[<>]' | head -3 | tr '\n' ' ')"
  fi
}

# ==================================================================================================
# D2 — the flag the case is written around does not exist; D2b asserts the reachable half
# ==================================================================================================

d2_no_launch_flag_absent() {
  d_home d2 1
  d_run "$CD/no-launch.out" dispatch --profile "$P_WORKER" --title "d2 nolaunch" --base "$BASE" \
        --cap 9 --no-launch
  local rc="$D_RC" refused
  refused=0
  grep -q "is not a flag dispatch declares" "$CD/no-launch.out" && refused=1
  #: A SKIP, not a FAIL: the product refuses an undeclared flag correctly (FI-19d). What is missing is the
  #: FLAG, i.e. the plan assumed a surface that was never built. §K's K6 is the precedent for reporting
  #: that as unrunnable rather than inventing a substitute and calling it the case.
  if [ "$rc" = 2 ] && [ "$refused" = 1 ]; then
    d_skip D2 "$CD/no-launch.out" \
      "UNRUNNABLE AS SPECIFIED: no verb declares --no-launch (exit 2, the parser names it as undeclared). Without it every real dispatch launches a session and stamps launched_at, so the state D2 describes — child instant + record + LEASE HELD + no session + PENDING-LAUNCH — is unreachable: the only routes to PENDING-LAUNCH are a launch that FAILED (which releases the lease; see D10b) and a claim with no record (which has no instant and no record; see D11). D2b asserts the reachable half"
  else
    d_fail D2 "$CD/no-launch.out" \
      "expected exit 2 naming --no-launch as undeclared; got exit $rc (refused-message present: $refused)"
  fi
}

d2b_real_dispatch_state() {
  d_home d2b 1
  d_run "$CD/dispatch.out" dispatch --profile "$P_WORKER" --title "d2b worker" --base "$BASE" --cap 9
  local rc="$D_RC" todo child tmux held recs charter state priv live_dt
  todo="$(awk '$1=="todo_id"{print $2}' "$CD/dispatch.out")"
  child="$(awk '$1=="instant"{print $2}' "$CD/dispatch.out")"
  tmux="$(awk '$1=="tmux"{print $2}' "$CD/dispatch.out")"
  held="$(d_held)"; recs="$(d_n_records)"
  charter=0; [ -s "$child/CHARTER.md" ] && charter=1
  d_run "$CD/status.out" status --id "$todo" --porcelain
  state="$(awk -F'\t' '$1=="state"{print $2}' "$CD/status.out")"
  priv=0; it_tmux has-session -t "=$tmux" 2>/dev/null && priv=1
  live_dt="$(d_live_tmux | grep -c "^$tmux\$")"
  {
    printf 'todo_id\t%s\ntmux\t%s\nstate\t%s\nsession_on_private_socket\t%s\nsession_on_live_server\t%s\n' \
           "$todo" "$tmux" "$state" "$priv" "$live_dt"
    printf 'lease_held\t%s\nrecords\t%s\ncharter_nonempty\t%s\n' "$held" "$recs" "$charter"
  } > "$CD/summary.tsv"
  if [ "$rc" = 0 ] && [ -d "$child" ] && [ "$charter" = 1 ] && [ "$recs" = 1 ] && [ "$held" = 1 ] \
     && [ "$priv" = 1 ] && [ "$live_dt" = 0 ] && [ "$state" = RUNNING ]; then
    d_pass D2b "$CD/summary.tsv" \
      "real dispatch, no flags withheld: child instant exists with a non-empty CHARTER.md, 1 record written, 1 lease HELD by the same todo_id, and the session the product named ($tmux) exists on socket itfleet-D and on NO live server. status says RUNNING and NOT PENDING-LAUNCH, because dispatch launched the pane and stamped launched_at — which is exactly why D2 as written needs --no-launch"
  else
    d_fail D2b "$CD/summary.tsv" \
      "exit $rc, child=$([ -d "$child" ] && echo yes || echo no) charter=$charter records=$recs held=$held private_session=$priv live_session=$live_dt state=${state:-none}"
  fi
}

# ==================================================================================================
# D3 — dispatch registers its own base; nobody calls register
# ==================================================================================================

d3_dispatch_registers_base() {
  d_home d3 1
  local registry="$FLEET_HOME/harvest/sources.json" before_exists
  before_exists=0; [ -e "$registry" ] && before_exists=1
  #: The whole verb log for this sandbox, so "without anyone calling register" is checkable rather than
  #: asserted: enroll, then dispatch, and nothing else touches this FLEET_HOME.
  printf 'enroll --slot <D/slots/d3/s1>\ndispatch --profile workerCompliant --title "d3 base" --base %s --cap 9\n' \
         "$BASE" > "$CD/verbs-run.txt"
  d_run "$CD/dispatch.out" dispatch --profile "$P_WORKER" --title "d3 base" --base "$BASE" --cap 9
  local rc="$D_RC" emitted in_file in_view
  emitted="$(awk '$1=="watched_source"{print $2}' "$CD/dispatch.out")"
  in_file=0; [ -f "$registry" ] && grep -q "\"base\": \"$BASE\"" "$registry" && in_file=1
  d_run "$CD/harvest-dry.out" harvest --dry-run --porcelain
  in_view="$(awk -F'\t' -v b="$BASE" '$1=="source" && $2==b' "$CD/harvest-dry.out" | wc -l | tr -d ' ')"
  cp "$registry" "$CD/sources.json" 2>/dev/null
  if [ "$rc" = 0 ] && [ "$before_exists" = 0 ] && [ "$in_file" = 1 ] && [ "$in_view" = 1 ] \
     && [ "$emitted" = "$BASE" ]; then
    d_pass D3 "$CD/sources.json" \
      "the registry did not exist before the dispatch; after it, base $BASE is a watched source in sources.json AND in the consumer's own view (harvest --dry-run prints a source row for it), and dispatch reported watched_source=$BASE itself. The only verbs run against this store are the two in verbs-run.txt — there is no register verb on the surface at all, which is the point: the transaction cannot forget it (harvest.record_dispatch)"
  else
    d_fail D3 "$CD/sources.json" \
      "exit $rc, registry_existed_before=$before_exists in_sources_json=$in_file in_harvest_view=$in_view emitted='$emitted'"
  fi
}

# ==================================================================================================
# D4 — an unregistered base is a lint violation, and registering it clears
# ==================================================================================================

d4_unregistered_base_lint() {
  d_home d4 0
  local child rule_before rule_after rc_before rc_after
  d_run "$CD/init.out" init --name handRolled --base 00000042
  child="$(awk '$1=="path"{print $2}' "$CD/init.out")"
  #: A record written STRAIGHT TO THE STORE, which is the population `Harvest.lint` exists for ("a
  #: hand-rolled script, an older build, or a verb that grew its own path"). Written through the product's
  #: own `Store.write` so the record is schema-valid — the defect under test is the missing REGISTRATION,
  #: and a record that failed to parse would test the parser instead.
  python3 - "$child" > "$CD/fabricate.out" 2>&1 <<'PY'
import os, sys
from pathlib import Path
from fleet.store import Record, Store
rec = Record(todo_id="handRolled-99999999", child_instant=sys.argv[1], base_instant="00000042",
             slot="", tmux="", profile="", golden="", lineage_base="", title="hand rolled",
             dispatched_at="2026-07-30T00:00:00Z")
print(Store(Path(os.environ["FLEET_HOME"])).write(rec).name)
PY
  d_run "$CD/lint-before.out" lint --instant "$child" --porcelain
  rc_before="$D_RC"
  rule_before="$(awk -F'\t' '$1=="unregistered-base" && $2=="00000042"' "$CD/lint-before.out" | wc -l | tr -d ' ')"
  #: Registering it. There is no `register` verb, so the base is registered the only way the surface
  #: allows — through a real transaction that calls `harvest.record_dispatch` (here `resume`, which needs
  #: no slot). Reported below, because a violation whose remedy has no verb is a weaker alarm than it looks.
  d_run "$CD/resume.out" resume --instant "$child"
  d_run "$CD/lint-after.out" lint --instant "$child" --porcelain
  rc_after="$D_RC"
  rule_after="$(awk -F'\t' '$1=="unregistered-base" && $2=="00000042"' "$CD/lint-after.out" | wc -l | tr -d ' ')"
  if [ "$rule_before" = 1 ] && [ "$rc_before" = 1 ] && [ "$rule_after" = 0 ] && [ "$rc_after" = 0 ]; then
    d_pass D4 "$CD/lint-before.out" \
      "a record written straight to the store naming base 00000042 produces exactly one unregistered-base violation and exit 1; registering that base (via a real record_dispatch — there is NO register verb, so resume is the only slot-free route) clears the violation and lint exits 0. The population line moves from 1 source to 2, so the clear is a registration and not a narrowed scope"
  else
    d_fail D4 "$CD/lint-before.out" \
      "before: rule rows=$rule_before exit=$rc_before; after registering: rule rows=$rule_after exit=$rc_after"
  fi
}

# ==================================================================================================
# D5 — the rendered charter has no placeholder left; an unresolvable token is refused
# ==================================================================================================

d5_render_and_refuse() {
  d_home d5 1
  d_run "$CD/dispatch.out" dispatch --profile "$P_WORKER" --title "d5 render" --base "$BASE" --cap 9
  local rc="$D_RC" child left_charter left_seed
  child="$(awk '$1=="instant"{print $2}' "$CD/dispatch.out")"
  left_charter="$(grep -c '{{[A-Za-z0-9_]*}}' "$child/CHARTER.md" 2>/dev/null)"
  left_seed="$(grep -c '{{[A-Za-z0-9_]*}}' "$child/.fleet/seed.txt" 2>/dev/null)"
  cp "$child/CHARTER.md" "$CD/CHARTER.rendered.md" 2>/dev/null
  #: The token that must be refused. Rendering happens BEFORE the child folder is created (FD-14), so the
  #: refusal is also the cheapest rollback there is: nothing but the lease exists to give back.
  d_home d5-token 1
  local trc left_lease left_child left_rec named
  d_run "$CD/token.out" dispatch --profile "$P_TOKEN" --title "d5 token" --base "$BASE" --cap 9
  trc="$D_RC"
  left_lease="$(d_n_leases)"; left_child="$(d_n_children)"; left_rec="$(d_n_records)"
  named=0; grep -q 'unresolved placeholder(s) {{RUN_ID}}' "$CD/token.out" && named=1
  if [ "$rc" = 0 ] && [ "$left_charter" = 0 ] && [ "$left_seed" = 0 ] \
     && [ "$trc" = 2 ] && [ "$named" = 1 ] && [ "$left_lease" = 0 ] && [ "$left_child" = 0 ] \
     && [ "$left_rec" = 0 ]; then
    d_pass D5 "$CD/token.out" \
      "the rendered CHARTER.md and .fleet/seed.txt of a real dispatch contain zero {{TOKEN}} occurrences; a profile whose seed names {{RUN_ID}} (which the dispatch context does not supply) is REFUSED with exit 2 naming the token and the six values it was given. FD-14's ordering is visible in the aftermath: 0 lease dirs, 0 instants, 0 records — the render is fallible and it runs before the folder exists, so this rollback had nothing to undo"
  else
    d_fail D5 "$CD/token.out" \
      "render: exit $rc charter_tokens=$left_charter seed_tokens=$left_seed; token profile: exit $trc named=$named leases=$left_lease instants=$left_child records=$left_rec"
  fi
}

# ==================================================================================================
# D6 / D7 / D8 — the kind/opType table, and no default kind
# ==================================================================================================

#: A free slot is enrolled for each of these, deliberately: with an empty pool `pool-capacity` refuses
#: FIRST with exit 3 and the case would pass on the wrong rule. `guards_for` puts capacity last, so the
#: exit 4 asserted here can only come from the rule under test — and the rule's own name is asserted too.
d_expect_refusal() {              # d_expect_refusal <case> <want_rc> <needle> <verb...>
  local case="$1" want="$2" needle="$3"; shift 3
  d_home "${case,,}" 1
  d_run "$CD/out.txt" "$@"
  local rc="$D_RC" hit leases recs
  hit=0; grep -qF -- "$needle" "$CD/out.txt" && hit=1
  leases="$(d_n_leases)"; recs="$(d_n_records)"
  if [ "$rc" = "$want" ] && [ "$hit" = 1 ] && [ "$leases" = 0 ] && [ "$recs" = 0 ]; then
    d_pass "$case" "$CD/out.txt" \
      "exit $rc with a free slot enrolled (so pool-capacity, which is evaluated last and would answer 3, cannot be the refuser); the diagnostic contains: $needle. Nothing was claimed and nothing was recorded"
  else
    d_fail "$case" "$CD/out.txt" \
      "want exit $want and the named diagnostic; got exit $rc needle=$hit leases=$leases records=$recs :: $(head -1 "$CD/out.txt")"
  fi
}

# ==================================================================================================
# D9 / D9b — the golden made unreadable, and the same failure where it can actually land
# ==================================================================================================

d9_golden_unreadable() {
  d_home d9 1
  local golden="$EV/home/d9-golden"
  rm -rf "$golden"; mkdir -p "$golden/repo"
  d_run "$CD/set-golden.out" set-golden --path "$golden"
  local set_rc="$D_RC"
  d_chmod000 "$golden"
  d_run "$CD/dispatch.out" dispatch --profile "$P_WORKER" --title "d9 golden" --base "$BASE" --cap 9
  local rc="$D_RC" recs leases
  recs="$(d_n_records)"; leases="$(d_n_leases)"
  chmod -R u+rwX "$golden" 2>/dev/null
  #: Why it is inert, from the package itself rather than from reading: every site that mentions the
  #: golden, the build-cache isolation or a clone, so a reader can see that `_do_dispatch` reaches none of
  #: the first and all of the second, and that the third does not exist.
  grep -rn '\.golden()\|isolate_build_cache\|clone' "$INSTANT/src/fleet" --include='*.py' \
    > "$CD/golden-and-clone-sites.txt" 2>/dev/null
  { printf 'set-golden exit\t%s\ndispatch-with-golden-at-mode-000 exit\t%s\nrecords\t%s\nlease dirs\t%s\n' \
           "$set_rc" "$rc" "$recs" "$leases"
    printf 'sites naming golden()/isolate_build_cache/clone in src/fleet\t%s\n' \
           "$(grep -c . "$CD/golden-and-clone-sites.txt")"
    printf 'callers of Workspace.golden() outside workspace.py\t%s\n' \
           "$(grep -c '\.golden()' "$CD/golden-and-clone-sites.txt" | tr -d ' ')"
  } > "$CD/inertness.tsv"
  if [ "$rc" = 0 ] && [ "$recs" = 1 ] && [ "$leases" = 1 ]; then
    d_skip D9 "$CD/inertness.tsv" \
      "INJECTION IS INERT, so there is no rollback to judge: with the declared golden at mode 000 the dispatch still exits 0, writes its record and holds its lease. dispatch never reads the golden and never clones it — _do_dispatch's only Workspace call is isolate_build_cache(lease.path), and the package contains no clone at all, so a slot is an EMPTY directory and record.golden is set to the SLOT path rather than to the golden. Reported as a defect; D9b injects the same PermissionError one step downstream, where it does land"
  else
    d_fail D9 "$CD/inertness.tsv" \
      "expected the chmod-000 golden to be inert (exit 0, 1 record, 1 lease) so the case could be reported as unrunnable; got exit $rc records=$recs leases=$leases — if the dispatch now fails on the golden this case is RUNNABLE and must be rewritten to assert the rollback"
  fi
}

d9b_slot_unreadable_rollback() {
  d_home d9b 1
  local slot="$D_SLOTS/s1" expect_child
  d_chmod000 "$slot"
  d_run "$CD/dispatch.out" dispatch --profile "$P_WORKER" --title "d9b slot" --base "$BASE" --cap 9
  local rc="$D_RC"
  chmod -R u+rwX "$slot" 2>/dev/null
  local leases recs children named landed rolled
  leases="$(d_n_leases)"; recs="$(d_n_records)"; children="$(d_n_children)"
  #: WHERE it landed. The traceback frame is the proof the injection fired INSIDE the transaction rather
  #: than before it: isolate_build_cache runs after the claim, after layout.bootstrap and after the
  #: charter is written, and before the record is written.
  #: RE-AIMED. This grepped the TRACEBACK for `isolate_build_cache` to prove where the failure landed.
  #: `SI-22` now catches `OSError` in `main` and prints the errno text plus a sentence INSTEAD of a
  #: traceback, so the frame names are gone — deliberately, because a traceback is the shape §9's alarm
  #: contract forbids. The step is still identifiable, and more robustly: the errno text names the `.m2`
  #: path, and `.m2` is created by nothing but `workspace.isolate_build_cache`. Asserting on the PATH rather
  #: than on a stack frame also stops the case breaking the next time an internal function is renamed.
  landed=0
  grep -q 'PermissionError' "$CD/dispatch.out" && grep -q '/\.m2' "$CD/dispatch.out" && landed=1
  #: And the traceback must be GONE — that is what SI-22 bought, so it is asserted rather than assumed.
  no_traceback=1; grep -q 'Traceback (most recent call last)' "$CD/dispatch.out" && no_traceback=0
  rolled=0; grep -q 'dispatch rolled back: the lease on' "$CD/dispatch.out" && rolled=1
  expect_child="$(find "$FLEET_INSTANTS" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1)"
  #: FD-14: rollback "releases the lease and NAMES whatever it left behind". Both halves are asserted, and
  #: the second one is asserted against the path that is actually on disk — a rollback narrative naming
  #: some other path would be a worse defect than no narrative.
  named=0
  [ -n "$expect_child" ] && grep -qF -- "$expect_child" "$CD/dispatch.out" && named=1
  {
    printf 'exit\t%s\nPermissionError names the .m2 path\t%s\nno traceback\t%s\nrollback sentence printed\t%s\n' \
           "$rc" "$landed" "$no_traceback" "$rolled"
    printf 'lease dirs left\t%s\nrecords left\t%s\ninstants left\t%s\n' "$leases" "$recs" "$children"
    printf 'leftover instant named in the rollback sentence\t%s\n' "$named"
    printf 'leftover instant entries\t%s\n' "$(find "$expect_child" 2>/dev/null | wc -l | tr -d ' ')"
  } > "$CD/rollback.tsv"
  if [ "$landed" = 1 ] && [ "$rolled" = 1 ] && [ "$leases" = 0 ] && [ "$recs" = 0 ] && [ "$named" = 1 ] \
     && [ "$no_traceback" = 1 ]; then
    d_pass D9b "$CD/rollback.tsv" \
      "a REAL PermissionError (slot at mode 000) in the build-cache step — after the claim, after layout.bootstrap, after the charter write, before the record — rolls back exactly as FD-14 specifies: 0 lease dirs left, 0 records left, and the child folder already built is LEFT IN PLACE and NAMED in the rollback sentence, asserted against the path actually on disk. Judged against FD-14 rather than against 'no half-built instant': the folder is the named leftover the decision chose over a delete. And since SI-22 the operator gets the errno text plus a sentence with NO TRACEBACK (asserted), which is what §9's alarm contract asks for; the step is identified by the .m2 path in that text rather than by a stack frame, so renaming an internal function cannot break this case"
  else
    d_fail D9b "$CD/rollback.tsv" \
      "exit $rc permission_error_names_m2=$landed no_traceback=$no_traceback rollback_sentence=$rolled leases=$leases records=$recs instants=$children leftover_named=$named"
  fi
}

# ==================================================================================================
# D10a / D10b — the child path already exists, as a file and as a directory
# ==================================================================================================

d10a_child_path_is_a_file() {
  d_home d10a 1
  #: The child path is `<instants>/<base>-MMDDHHMM-inflight-append-<camel(title)>` and there is no clock
  #: override on the surface, so BOTH the current UTC minute and the next one are blocked. A minute
  #: rollover between here and the dispatch would otherwise make the injection silently miss.
  local n1 n2 f1 f2
  n1="$(date -u +%m%d%H%M)"; n2="$(date -u -d '+1 minute' +%m%d%H%M)"
  f1="$FLEET_INSTANTS/$BASE-$n1-inflight-append-d10aBlocked"
  f2="$FLEET_INSTANTS/$BASE-$n2-inflight-append-d10aBlocked"
  printf 'a file, not a directory, sitting exactly where the child instant would go\n' > "$f1"
  printf 'a file, not a directory, sitting exactly where the child instant would go\n' > "$f2"
  local sha_before
  sha_before="$(sha256sum "$f1" | cut -d' ' -f1)"
  d_run "$CD/dispatch.out" dispatch --profile "$P_WORKER" --title "d10a blocked" --base "$BASE" --cap 9
  local rc="$D_RC" leases recs landed rolled named sha_after blocker
  leases="$(d_n_leases)"; recs="$(d_n_records)"
  #: RE-AIMED. `SI-20` now refuses this collision BEFORE the claim, so the shape the case was written
  #: against no longer occurs — and the new shape is strictly better. What used to happen: the claim was
  #: taken, `layout.bootstrap`'s mkdir raised `FileExistsError` mid-transaction, the handler rolled the
  #: lease back and the error escaped as a traceback. What happens now: `dispatch` sees the occupied child
  #: path, refuses with exit 4 and a sentence naming it, and never claims anything — so there is nothing to
  #: roll back and NO rollback sentence, which is why `rolled` is no longer required.
  #:
  #: The property the plan actually asks for — "no leaked lease, no half-built instant, no record" — is
  #: *more* strongly satisfied by refusing early than by unwinding, and the refusal is `Refused` (exit 4,
  #: registered) rather than an unhandled traceback. `D10b` is the case that proves the same guard protects
  #: a LIVE worker; this one proves it fires on a bare file too.
  refused=0; grep -q 'Refused: a dispatch this minute already produced' "$CD/dispatch.out" && refused=1
  landed=0; grep -q 'layout.bootstrap\|FileExistsError' "$CD/dispatch.out" && landed=1
  rolled=0; grep -q 'dispatch rolled back: the lease on' "$CD/dispatch.out" && rolled=1
  blocker="$(grep -o "$FLEET_INSTANTS/$BASE-[0-9]*-inflight-append-d10aBlocked" "$CD/dispatch.out" | head -1)"
  named=0; [ -n "$blocker" ] && named=1
  sha_after="$(sha256sum "$f1" | cut -d' ' -f1)"
  {
    printf 'exit\t%s\nrefused before the claim\t%s\nlanded in layout.bootstrap\t%s\nrollback sentence printed\t%s\n' \
           "$rc" "$refused" "$landed" "$rolled"
    printf 'lease dirs left\t%s\nrecords left\t%s\nblocking file unchanged\t%s\n' \
           "$leases" "$recs" "$([ "$sha_before" = "$sha_after" ] && echo yes || echo NO)"
  } > "$CD/rollback.tsv"
  if [ "$refused" = 1 ] && [ "$rc" = 4 ] && [ "$leases" = 0 ] && [ "$recs" = 0 ] \
     && [ "$named" = 1 ] && [ "$sha_before" = "$sha_after" ]; then
    d_pass D10a "$CD/rollback.tsv" \
      "with a FILE at the exact child path, dispatch REFUSES before claiming anything: exit 4 (Refused, registered — not an unhandled traceback), the sentence names the occupied path, 0 lease dirs, 0 records, and the pre-existing file byte-identical. Stronger than the rollback this case originally asserted: SI-20 moved the check ahead of the claim, so there is nothing to undo and no rollback sentence at all. The plan's property (no leaked lease, no half-built instant, no record) is satisfied by not starting rather than by unwinding"
  elif [ "$landed" = 1 ] && [ "$rolled" = 1 ] && [ "$leases" = 0 ] && [ "$recs" = 0 ] && [ "$named" = 1 ]; then
    d_fail D10a "$CD/rollback.tsv" \
      "REGRESSION: the pre-claim collision check did not fire, so this fell through to the old mid-transaction FileExistsError path (exit $rc). It rolled back correctly, but SI-20 is supposed to prevent the transaction starting at all"
  else
    d_fail D10a "$CD/rollback.tsv" \
      "exit $rc refused=$refused landed_in_bootstrap=$landed rollback_sentence=$rolled leases=$leases records=$recs named=$named blocker_unchanged=$([ "$sha_before" = "$sha_after" ] && echo yes || echo NO)"
  fi
}

d10b_child_path_is_a_live_instant() {
  d_home d10b 2
  #: The collision `identity.stable_key`'s docstring already names (OBS-14: "base-curr alone is NOT
  #: unique — two instants dispatched in the same minute share it"). Same base, same title, same UTC
  #: minute → the same instant folder, the same todo_id and the same tmux name. Two slots, so capacity is
  #: not what stops it.
  d_run "$CD/first.out" dispatch --profile "$P_WORKER" --title "d10b twin" --base "$BASE" --cap 9
  local rc1="$D_RC" child todo
  child="$(awk '$1=="instant"{print $2}' "$CD/first.out")"
  todo="$(awk '$1=="todo_id"{print $2}' "$CD/first.out")"
  if [ "$rc1" != 0 ] || [ -z "$child" ]; then
    d_fail D10b "$CD/first.out" "the first dispatch of the twin pair did not succeed (exit $rc1); the collision case could not be set up"
    return
  fi
  #: The running worker's own edit to its charter, which is what "outward state" means here.
  printf '\nWORKER EDIT: a line this worker wrote into its own charter after being dispatched.\n' \
    >> "$child/CHARTER.md"
  local sha_before rec_before
  sha_before="$(sha256sum "$child/CHARTER.md" | cut -d' ' -f1)"
  cp "$D_RECORDS/$todo.json" "$CD/record-before.json"
  rec_before="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["slot"], d["launched_at"])' "$CD/record-before.json")"

  local min_before min_after
  min_before="$(date -u +%m%d%H%M)"
  d_run "$CD/second.out" dispatch --profile "$P_WORKER" --title "d10b twin" --base "$BASE" --cap 9
  local rc2="$D_RC"
  min_after="$(date -u +%m%d%H%M)"
  if [ "$min_before" != "$min_after" ]; then
    d_skip D10b "$CD/second.out" \
      "the UTC minute rolled over between the two dispatches ($min_before -> $min_after), so the two instant names did not collide and the case tested nothing. Re-run"
    return
  fi
  local sha_after edit_gone rec_after slot_now held_slot board_rows
  sha_after="$(sha256sum "$child/CHARTER.md" | cut -d' ' -f1)"
  edit_gone="$(grep -c 'WORKER EDIT' "$child/CHARTER.md")"
  cp "$D_RECORDS/$todo.json" "$CD/record-after.json"
  rec_after="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["slot"], d["launched_at"])' "$CD/record-after.json")"
  d_run "$CD/leases.out" leases --porcelain
  held_slot="$(awk -F'\t' '$2=="held"{print $1}' "$CD/leases.out" | tr '\n' ' ')"
  slot_now="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["slot"])' "$CD/record-after.json")"
  d_run "$CD/board.out" board --porcelain
  board_rows="$(grep -c . "$CD/board.out")"
  {
    printf 'second dispatch exit\t%s\n' "$rc2"
    printf 'charter sha before / after\t%s / %s\n' "$sha_before" "$sha_after"
    printf "the worker's own charter edit survived\t%s\n" "$([ "$edit_gone" -gt 0 ] && echo yes || echo NO)"
    printf 'record (slot, launched_at) before\t%s\n' "$rec_before"
    printf 'record (slot, launched_at) after\t%s\n' "$rec_after"
    printf 'slot actually held\t%s\n' "$held_slot"
    printf 'slot the surviving record names\t%s\n' "$slot_now"
    printf 'rows on the board\t%s\n' "$board_rows"
  } > "$CD/damage.tsv"
  if [ "$edit_gone" = 0 ] || [ "$sha_before" != "$sha_after" ] || [ "$rec_before" != "$rec_after" ]; then
    d_fail D10b "$CD/damage.tsv" \
      "NO ROLLBACK AND REAL DAMAGE. A second dispatch with the same base, title and UTC minute resolves to the SAME child path, todo_id and tmux name (OBS-14). It overwrote the running worker's CHARTER.md (the worker's own edit is gone) and replaced its record with one naming the OTHER slot and launched_at=null, then failed at sessions.start (duplicate session) and rolled back only its own lease. Net: the live worker's slot is held by a lease no record names, the board shows $board_rows rows, and none of this is in the rollback sentence"
  else
    d_pass D10b "$CD/damage.tsv" \
      "a second dispatch onto an existing child instant left the running worker's charter and record intact (second exit $rc2)"
  fi
}

# ==================================================================================================
# D11 / D11b — SIGKILL the dispatch process mid-transaction
# ==================================================================================================

d_write_killer() {
  cat > "$EV/bin/dispatch-killer.py" <<'PY'
#!/usr/bin/env python3
"""SIGKILL a real `fleet dispatch` at a NAMED point in its transaction and report what it left behind.

Written by run-D.sh, into the section's own evidence dir.

The point matters more than the kill. `_do_dispatch`'s order is: claim -> gates again -> render ->
layout.bootstrap -> charter+seed -> isolate_build_cache -> register+record -> sessions.start -> record
again. Measured on this box, the claim lands ~120ms in and the child folder ~59ms after that, so the two
windows are wide enough to hit deliberately rather than hope for:

  trigger=lease  fire as soon as a claim directory exists -> inside the transaction, BEFORE the folder
  trigger=child  fire as soon as the child directory exists -> inside layout.bootstrap, mid-build

A run that fires neither trigger is reported as `fired=` and the caller counts it as an iteration that
asserted nothing (§E9's E9 reported `ok` for 82% of iterations that had nothing to assert; the fix is to
COUNT them, not to average them away).

Only the pid this process spawned is ever signalled. There is no pkill here.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

trigger, profile, title, base, cap, outfile, jsonfile = sys.argv[1:8]
home = Path(os.environ["FLEET_HOME"])
inst = Path(os.environ["FLEET_INSTANTS"])
leases, records = home / "pool" / "leases", home / "records"


def names(d, pattern="*"):
    try:
        return sorted(p.name for p in d.glob(pattern))
    except OSError:
        return []


def snapshot():
    child = [p for p in inst.iterdir()] if inst.is_dir() else []
    entries = []
    for c in child:
        if c.is_dir():
            entries = sorted(p.name for p in c.iterdir())
    return {
        "lease_dirs": names(leases),
        "lease_bodies": sorted(p.parent.name for p in leases.glob("*/lease.json")) if leases.is_dir() else [],
        "lease_staging": sorted(p.parent.name for p in leases.glob("*/.*tmp")) if leases.is_dir() else [],
        "children": sorted(p.name for p in child),
        "child_entries": entries,
        "records": names(records, "*.json"),
    }


t0 = time.monotonic()
with open(outfile, "w") as sink:
    proc = subprocess.Popen(
        [sys.executable, "-m", "fleet.cli", "dispatch", "--profile", profile, "--title", title,
         "--base", base, "--cap", cap],
        stdout=sink, stderr=subprocess.STDOUT)
    fired, at_kill = "", {}
    while proc.poll() is None:
        if trigger == "lease" and leases.is_dir() and any(leases.iterdir()):
            fired = "lease"
        elif trigger == "child" and inst.is_dir() and any(inst.iterdir()):
            fired = "child"
        if fired:
            at_kill = snapshot()
            at_kill["ms"] = round((time.monotonic() - t0) * 1000, 1)
            os.kill(proc.pid, 9)          # only ever the pid this process started
            break
        time.sleep(0.0002)
    rc = proc.wait()

after = snapshot()
report = {"trigger": trigger, "fired": fired, "rc": rc,
          "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
          "at_kill": at_kill, "after": after}
Path(jsonfile).write_text(json.dumps(report, indent=2))
#: One tab-separated line for the shell, so the caller parses fields rather than JSON.
print("\t".join(str(x) for x in (
    fired or "-", rc,
    len(after["lease_dirs"]), len(after["lease_bodies"]), len(after["lease_staging"]),
    len(after["children"]), len(after["child_entries"]),
    "CHARTER.md" in after["child_entries"] and "charter" or "no-charter",
    len(after["records"]),
    (at_kill or {}).get("ms", -1))))
PY
  chmod +x "$EV/bin/dispatch-killer.py"
}

#: One shared body for both SIGKILL cases: the only difference is WHERE the kill fires, and a second copy
#: of this loop would be a second set of assertions to keep in agreement.
d_sigkill_case() {                # d_sigkill_case <case> <trigger> <iters>
  local case="$1" trigger="$2" iters="$3" log i
  d_home "${case,,}" 0
  log="$CD/per-iteration.tsv"
  printf 'iter\tfired\trc\tlease_dirs\tlease_bodies\tstaging\tinstants\tchild_entries\tcharter\trecords\tkill_at_ms\tleases_view\tboard_row\treap_row\tleases_after_reap\tverdict\n' \
    > "$log"
  local fired_n=0 bad=0 leaked=0 recovered=0 halfbuilt=0 records_left=0 named_n=0
  local bodiless=0 reclaimed_row=0 reaped_row=0
  for i in $(seq 1 "$iters"); do
    d_home "${case,,}/i$i" 1
    local line fired rc ld lb st ch ce charter rec at
    line="$(python3 "$EV/bin/dispatch-killer.py" "$trigger" "$P_WORKER" "$case i$i" "$BASE" 9 \
              "$CD/dispatch.out" "$CD/report.json" 2>"$CD/killer.err")"
    IFS=$'\t' read -r fired rc ld lb st ch ce charter rec at <<<"$line"
    local verdict=ok reap_row=n/a after_reap=0 leases_view=n/a board_row=n/a
    if [ -z "${fired:-}" ]; then
      #: The killer itself failed. Never silently an `ok`: a harness error reported as a product pass is
      #: the exact shape this section is checking the product for.
      fired=killer-error; rc="?"; ld=0; lb=0; st=0; ch=0; ce=0; charter="?"; rec=0; at=-1
      verdict=killer-error
    fi
    after_reap="$ld"
    if [ "$verdict" = killer-error ]; then
      :
    elif [ "$fired" = "-" ]; then
      verdict=asserted-nothing            # the process finished before the trigger; counted, never averaged
    else
      fired_n=$((fired_n + 1))
      [ "$rc" = "-9" ] || verdict=not-killed
      [ "$rec" != 0 ] && { verdict=record-written; records_left=$((records_left + 1)); }
      [ "$ch" != 0 ] && halfbuilt=$((halfbuilt + 1))
      [ "$ld" != 0 ] && leaked=$((leaked + 1))
      #: The FD-14 half that IS testable for a SIGKILL: whatever is left has a name and a recovery. `reap`
      #: is asked as the owning base, not with --all, so the ownership scope is exercised too.
      if [ "$ld" != 0 ]; then
        #: Is the leak VISIBLE before anybody runs a reap? Both views are asked, because the two windows
        #: leave two different states and only one of them reaches `board`: a claim whose lease body never
        #: landed (SI-7) has no owner to build a subject from, so `reconcile` cannot see it and the label
        #: lives in the `leases` view instead (`render.leases` -> "interrupted"). A check that asked only
        #: `board` would report the SI-7 leak as unnamed, which is wrong, and only `leases` would miss the
        #: stale-lease subject. The row records what each one said.
        d_run "$CD/leases.out" leases --porcelain
        leases_view="$(awk -F'\t' 'NR==1{print $2}' "$CD/leases.out")"
        [ -z "$leases_view" ] && leases_view=empty
        d_run "$CD/board.out" board --porcelain
        board_row="$(awk -F'\t' 'NR==1{print $2}' "$CD/board.out")"
        [ -z "$board_row" ] && board_row=empty
        case "$leases_view$board_row" in
          *interrupted*|*held*|*stale-lease*) named_n=$((named_n + 1)) ;;
        esac
        d_run "$CD/reap.out" reap --base "$BASE" --porcelain
        reap_row="$(awk -F'\t' '$1=="reaped"||$1=="reap-reclaimed"{print $1}' "$CD/reap.out" | head -1)"
        [ -z "$reap_row" ] && reap_row=none
        [ "$reap_row" = reap-reclaimed ] && reclaimed_row=$((reclaimed_row + 1))
        [ "$reap_row" = reaped ] && reaped_row=$((reaped_row + 1))
        [ "$lb" = 0 ] && bodiless=$((bodiless + 1))
        after_reap="$(d_n_leases)"
        if [ "$after_reap" = 0 ] && [ "$reap_row" != none ]; then
          recovered=$((recovered + 1))
        elif [ "$verdict" = ok ]; then
          verdict=lease-not-recovered
        fi
      fi
    fi
    [ "$verdict" != ok ] && [ "$verdict" != asserted-nothing ] && bad=$((bad + 1))
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$i" "$fired" "$rc" "$ld" "$lb" "$st" "$ch" "$ce" "$charter" "$rec" "$at" \
      "$leases_view" "$board_row" "$reap_row" "$after_reap" "$verdict" >> "$log"
  done
  #: Back to the case's own dir so the evidence path in the row is the log, not the last iteration's.
  CD="$EV/out/${case,,}"
  D_SIGKILL_LOG="$log"
  D_SIGKILL_FIRED="$fired_n"; D_SIGKILL_BAD="$bad"; D_SIGKILL_LEAKED="$leaked"
  D_SIGKILL_RECOVERED="$recovered"; D_SIGKILL_HALFBUILT="$halfbuilt"
  D_SIGKILL_RECORDS="$records_left"; D_SIGKILL_NAMED="$named_n"; D_SIGKILL_ITERS="$iters"
  D_SIGKILL_BODILESS="$bodiless"; D_SIGKILL_RECLAIMED_ROW="$reclaimed_row"
  D_SIGKILL_REAPED_ROW="$reaped_row"
}

d11_sigkill_before_the_folder() {
  d_sigkill_case D11 lease 12
  local need=$(( (D_SIGKILL_ITERS * 3 + 3) / 4 ))          # at least 75% must have landed in the window
  if [ "$D_SIGKILL_FIRED" -lt "$need" ]; then
    d_fail D11 "$D_SIGKILL_LOG" \
      "CANNOT JUDGE: only $D_SIGKILL_FIRED of $D_SIGKILL_ITERS iterations were killed inside the transaction at all (needed $need), so the rest asserted nothing about rollback"
  elif [ "$D_SIGKILL_BAD" != 0 ]; then
    d_fail D11 "$D_SIGKILL_LOG" \
      "$D_SIGKILL_BAD of $D_SIGKILL_FIRED in-window iterations failed: records_written=$D_SIGKILL_RECORDS half_built_instants=$D_SIGKILL_HALFBUILT leases_not_recovered=$((D_SIGKILL_LEAKED - D_SIGKILL_RECOVERED)); see the per-iteration log"
  else
    d_pass D11 "$D_SIGKILL_LOG" \
      "$D_SIGKILL_FIRED of $D_SIGKILL_ITERS iterations SIGKILLed with the claim already taken and the child folder not yet created — the killer logs the millisecond, ~115ms into a ~200ms transaction. 0 records and 0 instants in every one, so 'no half-built instant, no record' holds exactly where FD-14 orders it to. A lease is left in $D_SIGKILL_LEAKED of them (a killed process runs no rollback; FD-14 promises a NAMED leftover, not none) and in $D_SIGKILL_BODILESS of those the leftover is precisely SI-7's interrupted claim: the mkdir that won the slot, with the lease body still under its staging name. It is labelled before anyone acts ($D_SIGKILL_NAMED of $D_SIGKILL_LEAKED, via the leases view's 'interrupted' — board cannot see it, there being no owner to build a subject from) and reap --base cleared every one and said so, $D_SIGKILL_RECLAIMED_ROW as reap-reclaimed and $D_SIGKILL_REAPED_ROW as reaped, naming the dead writer's pid. Recovery was immediate, on the staging pid's liveness, not on the 30s floor"
  fi
}

d11b_sigkill_mid_bootstrap() {
  d_sigkill_case D11b child 8
  local need=$(( (D_SIGKILL_ITERS * 3 + 3) / 4 ))
  if [ "$D_SIGKILL_FIRED" -lt "$need" ]; then
    d_fail D11b "$D_SIGKILL_LOG" \
      "CANNOT JUDGE: only $D_SIGKILL_FIRED of $D_SIGKILL_ITERS iterations were killed inside layout.bootstrap (needed $need)"
  elif [ "$D_SIGKILL_RECORDS" != 0 ]; then
    d_fail D11b "$D_SIGKILL_LOG" \
      "$D_SIGKILL_RECORDS of $D_SIGKILL_FIRED iterations left a RECORD behind after being killed mid-bootstrap"
  elif [ "$D_SIGKILL_LEAKED" != "$D_SIGKILL_RECOVERED" ]; then
    d_fail D11b "$D_SIGKILL_LOG" \
      "$((D_SIGKILL_LEAKED - D_SIGKILL_RECOVERED)) of $D_SIGKILL_LEAKED leaked leases were NOT recovered by reap --base"
  else
    d_pass D11b "$D_SIGKILL_LOG" \
      "the harder window: $D_SIGKILL_FIRED of $D_SIGKILL_ITERS iterations SIGKILLed INSIDE layout.bootstrap, ~170ms in. $D_SIGKILL_HALFBUILT left a genuinely half-built instant (the log carries each one's entry count and whether CHARTER.md made it), and 0 left a record — the record is written after the tree, so the two windows leak different things and neither leaks a record. Here the lease body HAD landed, so the leftover is a stale lease rather than SI-7's interrupted claim: reconcile names it as a stale-lease subject on the board ($D_SIGKILL_NAMED of $D_SIGKILL_LEAKED) and reap --base gave every one back as $D_SIGKILL_REAPED_ROW reaped row(s), naming the owner. Judged against FD-14, which orders the FALLIBLE steps before the folder and promises a NAMED leftover rather than none: a SIGKILL is not a fallible step and no rollback runs, so the plan's literal 'no half-built instant, no leaked lease' is unachievable in this window and is reported as needing amendment, not as a product defect"
  fi
}

# ==================================================================================================

main() {
  d_enter
  d_write_killer

  d1_dry_run_zero_delta
  d2_no_launch_flag_absent
  d2b_real_dispatch_state
  d3_dispatch_registers_base
  d4_unregistered_base_lint
  d5_render_and_refuse
  d_expect_refusal D6 4 "declares kind='compaction', whose opType(s) are compact" \
    dispatch --profile "$P_COMPACT" --title "d6 mismatch" --base "$BASE" --cap 9 --optype append
  d_expect_refusal D7 4 "declares kind='worker', whose opType(s) are append" \
    dispatch --profile "$P_WORKER" --title "d7 mismatch" --base "$BASE" --cap 9 --optype compact
  d_expect_refusal D8 2 "an undeclared kind is an error, not a \`worker\`" \
    dispatch --profile "$P_NOKIND" --title "d8 nokind" --base "$BASE" --cap 9
  d_expect_refusal D8b 2 "declares no kind: there is no profile.json" \
    dispatch --profile "$P_NOMANIFEST" --title "d8b nomanifest" --base "$BASE" --cap 9
  d9_golden_unreadable
  d9b_slot_unreadable_rollback
  d10a_child_path_is_a_file
  d10b_child_path_is_a_live_instant
  d11_sigkill_before_the_folder
  d11b_sigkill_mid_bootstrap

  d_leave
  #: P-3: instant-relative, at the very end, over the whole file this runner owns.
  sed -i "s|$INSTANT/||g" "$RESULTS"
  printf '\n§D finished with IT_FAILED=%s\n' "$IT_FAILED"
  #: `II-11`. Was `exit "$IT_FAILED"` — a COUNT. `exit` truncates modulo 256, so a section with
  #: exactly 256 failures reported SUCCESS, and one with 300 reported 44, a number meaning nothing
  #: to any reader. An exit status is a one-byte verdict, not a tally: the count is already printed
  #: on the line above and is in the register, which is where a consumer should read it anyway.
  if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
  exit 1
}

main "$@"
