#!/usr/bin/env bash
# Plan 6 §E (concurrency, 9 cases) and §K (compaction, 10 cases) — integration group 3.
#
# These are the two sections the 477 hermetic tests cannot touch at all: every probe in them is
# injected, so nothing there can observe a race, a real tmux session, or a real process.
#
# ISOLATION, and one unavoidable deviation, stated up front
# --------------------------------------------------------
# The contract says tmux sessions carry the prefix `itfleet-` and no `dt-` session is ever created.
# `cli._do_dispatch` HARDCODES `tmux = f"dt-{name.name}"` and `ctx.sessions.start(tmux, lease.path,
# "claude")`. There is no `--no-launch` flag on any verb (Plan 6 §D2 assumes one) and no `--tmux` flag
# on `dispatch` (only `resume` has one). So a real dispatch cannot be made to honour either half of
# that rule from the outside. This is recorded as a finding, not worked around silently.
#
# What this harness does instead is strictly stronger on the property the rule exists to protect —
# "the live ANSI coordinator's tmux server is not touched". TWO layers, composed, not either:
#
#   * `-L "$IT_TMUX_SOCKET"` (W-1). `it_section` sets the socket to `itfleet-<SECTION>` and exports it
#     as FLEET_TMUX_SOCKET, which `session.default_probes` reads — so the package's tmux calls AND this
#     harness's own (always via `it_tmux`) land on ONE named server per section. This is the layer that
#     makes the harness and the product agree about WHICH server the section's sessions live on.
#   * TMUX_TMPDIR is still pointed at a private, per-section socket DIRECTORY. It is deliberately kept
#     rather than dropped as redundant, because it is the layer that survives the other one failing:
#     `default_probes` degrades to a BARE `tmux` when FLEET_TMUX_SOCKET is empty or unset
#     (`os.environ.get(...) or None`), and a bare `tmux new-session` on the live server is exactly the
#     `dt-` session on the operator's server that this contract exists to prevent. A socket NAME can be
#     lost by a dropped export; a socket DIRECTORY cannot be escaped by any server name, `default`
#     included. The two compose cleanly and by construction: `-L NAME` under `TMUX_TMPDIR=D` is the
#     socket `D/tmux-$UID/NAME`, and harness and product inherit the same env, so they cannot diverge.
#     The one cost is an ordering rule — a read of the LIVE server must not see TMUX_TMPDIR — and the
#     two such reads in this file are made immune to it with `env -u TMUX_TMPDIR` rather than left to
#     depend on statement order.
#
#   The live server's session list is snapshotted before and compared after; `it_assert_isolation` now
#   compares the whole live session-name SET against `live-tmux-sessions.txt` as well (`SI-1`).
#   * `fleet/it/bin/claude` is placed first on PATH: a real process in a real pane that
#     is not claude. `pgrep -x claude` is asserted identical before and after each section (§A6).
#     Plan 6 §J1 endorses this substitution ("a real tmux worker (a shell, not `claude`)").
#
# Real OS concurrency only: `&` + `wait` with a FIFO start barrier, never threads. Every probabilistic
# case states its sample size and writes a per-iteration log, so a flake is visible rather than averaged.
#
# Usage: ./run-group3.sh [E|K|all]
set -uo pipefail

G3_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$G3_HERE/lib.sh"

#: NEVER the shared RESULTS.tsv — that file belongs to another writer, and one register with two
#: writers is `FI-16`/`FI-29`'s own shape. `IT_RESULTS` is honoured so a concurrent re-run can be given
#: its own file: the previous form HARDCODED the path and silently ignored `IT_RESULTS`, which meant an
#: operator who set the variable to stay out of another agent's way was overruled without being told.
RESULTS="${IT_RESULTS:-$G3_HERE/RESULTS-group3.tsv}"
PROFILES="$INSTANT/tests/fixtures/profiles"
#: The compaction-kind fixture, reused rather than invented: tests/fixtures/profiles/compaction
#: declares "kind": "compaction", whose only legal opType is `compact` (profiles.OPTYPES_OF_KIND).
P_COMPACT="$PROFILES/compaction"
#: A non-compaction kind for K9. The shipped domain is profiles.KINDS = worker|coordinator|compaction;
#: there is no `fix` kind, so §K9's "fix-kind profile" is read as "a profile whose declared kind does
#: not admit --optype compact", and workerCompliant is that profile.
P_WORKER="$PROFILES/workerCompliant"

IT_FAILED=0
G3_CLAUDE_BEFORE=""
G3_TMUX_BEFORE=""

if [ ! -s "$RESULTS" ]; then
  printf 'case\tverdict\tevidence\tnote\n' > "$RESULTS"
fi

# --- recording: every evidence reference is INSTANT-RELATIVE ---------------------------------------
#
# P-3 / `FI-32`. The paths the cases build are absolute because they are used for WRITING, and passing
# one straight to `it_pass` put `/home/ubuntu/.../evidence/...` into the results file — which
# `bin/lint-evidence-paths.sh` fails, and which is one reboot from being an unbacked claim. FI-32 is
# precisely this defect: "the proof for 9-of-9 concurrency passes was cited by absolute /tmp path".
#
# Relativised at the RECORDING boundary rather than at each of the 46 call sites, so a case added later
# cannot reintroduce it — the same reason `it_tmux` exists instead of a rule about remembering `-L`.
g3_rel() { case "${1:-}" in "$INSTANT"/*) printf '%s' "${1#"$INSTANT"/}" ;; *) printf '%s' "${1:-}" ;; esac; }
g3_pass() { it_pass "$1" "$(g3_rel "${2:-}")" "${3:-}"; }
g3_fail() { it_fail "$1" "$(g3_rel "${2:-}")" "${3:-}"; }
g3_skip() { it_skip "$1" "$(g3_rel "${2:-}")" "${3:-}"; }

# --- section enter / leave -------------------------------------------------------------------------

#: The ONE bare-tmux reader in this file, used twice: the live-server pre-image and post-image. Both are
#: READ-ONLY and both must stay on the DEFAULT server — a private-server read here would compare a
#: private server against a live pre-image and the isolation assertion would become a false compare in
#: the other direction, i.e. vacuous. `env -u TMUX_TMPDIR` states that intent in the call itself instead
#: of leaving it to depend on whether the caller happens to run before the export / after the unset.
#: `II-2`. This was a bare `tmux ls`, whose lines carry a window count and an `(attached)` marker, so the
#: comparison it fed failed when the operator merely attached to an unrelated session. §B had the same
#: bug; §C and §D did not. `lib.sh` states the rule and the reason in `it_live_tmux_sessions` — the
#: shared helper these four copies declined to use.
g3_live_tmux() { env -u TMUX_TMPDIR tmux ls -F '#{session_name}' 2>/dev/null | sort; }

g3_enter() {                    # g3_enter <SECTION>
  it_section "$1"
  # The expected `board --porcelain` field count, read from the DECLARED schema rather than typed. It was the
  # literal 6, and `SI-27` added a `milestone` column — after which all 50 iterations reported a torn render
  # and E4 failed for a reason that had nothing to do with concurrency. A check that hardcodes a schema
  # measures the schema it was written against, not the one in front of it.
  G3_BOARD_COLS="$(python3 -c 'from fleet.cli import PORCELAIN_COLUMNS; print(len(PORCELAIN_COLUMNS["board"]))')"                                    # own FLEET_HOME, own slots, own SOCKET, isolation asserted
  #: Evidence dir override. A section's evidence path is otherwise `<SECTION>/`, and re-running §E would
  #: overwrite logs that rows in a results file THIS RUN does not own still cite. Section identity —
  #: FLEET_HOME's shape, the tmux socket, the case ids — is unchanged; only where the bytes land moves.
  if [ -n "${G3_EV_DIR:-}" ]; then
    EV="$IT_ROOT/$G3_EV_DIR"; SLOTS="$EV/slots"; export FLEET_HOME="$EV/home"
    mkdir -p "$EV" "$SLOTS" "$FLEET_HOME"
  fi
  G3_SOCK="/tmp/itf$1"                               # short path: a long TMUX_TMPDIR overflows sun_path
  rm -rf "$G3_SOCK"; mkdir -p "$G3_SOCK"
  G3_TMUX_BEFORE="$(g3_live_tmux)"                   # the LIVE server, deliberately: see g3_live_tmux
  G3_CLAUDE_BEFORE="$(pgrep -x claude 2>/dev/null | wc -l)"
  #: KEPT, not redundant with `-L`: this is what contains a tmux call that lost its socket name. See the
  #: two-layer note in the header. `-L NAME` under this becomes `$TMUX_TMPDIR/tmux-$UID/NAME`, and both
  #: this harness (via `it_tmux`) and every `fleet` subprocess (via FLEET_TMUX_SOCKET) inherit it.
  export TMUX_TMPDIR="$G3_SOCK"
  export PATH="$G3_HERE/bin:$PATH"
  mkdir -p "$EV/out"
  printf '%s\n' "$G3_TMUX_BEFORE" > "$EV/out/live-tmux-before.txt"
  #: The private-session ledger starts EMPTY for each section. It is appended to by every
  #: `g3_kill_sessions` sweep and read once at leave; carried over from §E it would make §K's
  #: `private-leak` row a statement about §E's sessions, attributed to §K.
  : > "$EV/out/private-tmux-sessions.txt"
}

#: Every session on the section's PRIVATE server. It cannot be filtered by TMUX_PREFIX the way
#: `it_cleanup_tmux` is: `cli._do_dispatch` hardcodes `dt-{name}` for the session it starts, so a
#: `^itfleet-` filter would match nothing and every dispatched pane would leak. Killing everything is
#: therefore the correct scope — but ONLY once "everything" provably means the private server, so the
#: server is `-L $IT_TMUX_SOCKET` via `it_tmux` (which refuses outright when no section has been
#: entered) and the socket name is re-checked here. A bare `tmux kill-session` in this loop was safe
#: only while nothing else used a socket name; W-1 gave the product `-L itfleet-<SECTION>` while this
#: loop still spoke to `default` inside the same TMUX_TMPDIR — two servers, so the loop listed an empty
#: one and killed nothing, and every §E pane leaked for the life of the run.
g3_kill_sessions() {
  case "${IT_TMUX_SOCKET:-}" in
    itfleet-*) ;;
    *) echo "g3_kill_sessions: socket is '${IT_TMUX_SOCKET:-}', not an itfleet-* private server." \
            "This loop kills EVERY session it is shown — refusing to run it against that." >&2
       return 2 ;;
  esac
  #: The names are RECORDED before they are killed, so `it_assert_no_private_leak` can assert at leave that
  #: none of them is also on the DEFAULT server. They are `dt-<instant>` — hardcoded by `cli._do_dispatch`
  #: — which is exactly why no name-shape rule can cover them. See the note in `g3_leave`.
  #:
  #: APPENDED to a ledger, not overwritten, and this is the whole difference between a check and a
  #: decoration. This function runs after nearly every case (sixteen call sites in this file), so a file
  #: rewritten each sweep holds only what was alive at the LAST one — normally nothing, because §E kills
  #: its dispatches as it goes. Measured with the first, overwriting version: `ISOLATION-E-private-leak`
  #: reported "none of the 0 session(s)" and passed, in a section that had just started and killed dozens.
  #: The ledger is the union of every session this section ever put on its private server.
  mkdir -p "$EV/out"
  local ledger="$EV/out/private-tmux-sessions.txt" now
  now="$(it_tmux ls -F '#{session_name}' 2>/dev/null | sort)"
  if [ -n "$now" ]; then
    printf '%s\n' "$now" >> "$ledger"
    sort -u -o "$ledger" "$ledger"
  fi
  #: `=$s` — an EXACT target. `kill-session -t itfleet-N-pre-a` resolves BY PREFIX and destroyed a live
  #: `itfleet-N-pre-ab` in N7c; that is `FI-23`/`SI-2` and it must not come back through the harness.
  #: Killed from the CURRENT listing, not from the ledger: the ledger holds names already reaped by an
  #: earlier sweep, and re-targeting those is noise at best.
  printf '%s\n' "$now" | while read -r s; do
    [ -n "$s" ] && it_tmux kill-session -t "=$s" 2>/dev/null
  done
  true
}

g3_leave() {                    # g3_leave <SECTION>
  g3_kill_sessions
  local after_claude
  after_claude="$(pgrep -x claude 2>/dev/null | wc -l)"
  #: BEFORE the live read, and it must stay before it: `it_assert_isolation` (below) reads the live
  #: server with a BARE `tmux ls` (`it_live_tmux_sessions`), which is only the live server while
  #: TMUX_TMPDIR is unset. `g3_live_tmux` no longer depends on this ordering; that helper does.
  unset TMUX_TMPDIR
  local after_tmux
  after_tmux="$(g3_live_tmux)"                       # the LIVE server, deliberately: see g3_live_tmux
  printf '%s\n' "$after_tmux" > "$EV/out/live-tmux-after.txt"
  #: `II-1`. Was a private byte-comparison — the FOURTH copy of the isolation contract, and the one the
  #: original RCA missed entirely because it read `run-B/C/D.sh` and stopped. §group3 runs more sections
  #: than any of those three, so it was the widest exposure of the defect.
  #:
  #: Split into the two questions it conflated, each with one implementation. The classifier decides the
  #: general contract, where operator churn on a shared box is a NOTE rather than a failure.
  #: `it_assert_no_private_leak` decides the part the classifier cannot: the sessions this section starts
  #: are `dt-<instant>` (hardcoded by `cli._do_dispatch`), so they carry no harness prefix, and a leaked
  #: one is indistinguishable BY SHAPE from another operator's dispatch. The exact names can tell.
  local g3_classified
  g3_classified="$(it_classify_session_delta "$G3_TMUX_BEFORE" "$after_tmux")"
  if [ "${g3_classified%%|*}" = FAIL ]; then
    g3_fail "ISOLATION-$1-live-tmux" "$EV/out/live-tmux-after.txt" "${g3_classified#*|}"
  else
    g3_pass "ISOLATION-$1-live-tmux" "$EV/out/live-tmux-after.txt" "${g3_classified#*|}"
  fi
  it_assert_no_private_leak "ISOLATION-$1-private-leak" "$EV/out/private-tmux-sessions.txt" \
    "dt-* dispatch sessions: no name-shape rule can catch these, only the exact names"
  if [ "$after_claude" = "$G3_CLAUDE_BEFORE" ]; then
    g3_pass "ISOLATION-$1-claude-count" "" "pgrep -x claude: $after_claude before and after (A6)"
  else
    g3_fail "ISOLATION-$1-claude-count" "" \
            "pgrep -x claude went $G3_CLAUDE_BEFORE -> $after_claude; no claude may launch outside §P"
  fi
  it_assert_isolation "$1-leave"
  rm -rf "$G3_SOCK"
}

# --- per-case sandbox ------------------------------------------------------------------------------

g3_home() {                     # g3_home <tag> [n_slots]
  G3_TAG="$1"; local want="${2:-0}" i
  export FLEET_HOME="$EV/home/$G3_TAG"
  export FLEET_INSTANTS="$EV/instants/$G3_TAG"
  G3_SLOTS="$SLOTS/$G3_TAG"
  CD="$EV/out/$G3_TAG"
  rm -rf "$FLEET_HOME" "$FLEET_INSTANTS" "$G3_SLOTS" "$CD"
  mkdir -p "$FLEET_HOME" "$FLEET_INSTANTS" "$G3_SLOTS" "$CD"
  for i in $(seq 1 "$want"); do
    mkdir -p "$G3_SLOTS/s$i"
    fleet enroll --slot "$G3_SLOTS/s$i" >> "$CD/enroll.out" 2>&1
  done
}

#: A manifest over EVERYTHING a dispatch could touch inside this sandbox: the store, the pool, the
#: slots and the instants dir. `it_zero_delta` covers only FLEET_HOME+SLOTS, and K9's assertion is
#: specifically "no instant" as well as "no lease, no record".
g3_manifest() { it_manifest "$FLEET_HOME" "$G3_SLOTS" "$FLEET_INSTANTS"; }

# --- the start barrier -----------------------------------------------------------------------------
#
# A FIFO, not a spin loop. Every child blocks in open(2) on the read end; the parent opening the write
# end releases all of them in the same instant, with no CPU burned and no ordering imposed by whoever
# happened to be scheduled first. That matters: a barrier that leaks a head start is a barrier that
# hides the race it was built to expose.

g3_barrier_new() { G3_GO="$CD/${1:-go}.fifo"; rm -f "$G3_GO"; mkfifo "$G3_GO"; }
g3_barrier_open() { exec 9>"$G3_GO"; }
g3_barrier_close() { exec 9>&-; rm -f "$G3_GO"; }

#: Spawn one barrier-gated `fleet` invocation; its pid lands in G3_PID. Deliberately NOT returned
#: through a command substitution: `$( ... & echo $! )` starts the job inside a subshell, which orphans
#: it the moment the substitution closes and makes `wait` in the caller fail — a harness that cannot
#: collect its children's exit codes cannot count winners, which is the whole assertion here.
g3_spawn() {                    # g3_spawn <tag> <verb...>   -> G3_PID
  local tag="$1"; shift
  (
    exec 8<"$G3_GO"                                  # blocks until the parent opens the write end
    exec python3 -m fleet.cli "$@" > "$CD/$tag.out" 2>&1
  ) &
  G3_PID=$!
}

g3_count_rc() {                 # g3_count_rc <want> <rc-file>   -> how many lines equal <want>
  awk -v w="$2" '$1==w' "$1" | wc -l | tr -d ' '
}

g3_traceback_in() {             # g3_traceback_in <files...>  -> 0 when a python traceback is present
  grep -lE 'Traceback \(most recent call last\)|JSONDecodeError|FileNotFoundError|FileExistsError' \
       "$@" 2>/dev/null | head -1
}

#: Poll until nothing holds <dir> as its cwd. `pool.release` refuses while a live pid sits in the slot
#: (OBS-48) and that refusal is correct, so a case that needs a slot back waits for the pane to die.
g3_wait_cwd_clear() {           # g3_wait_cwd_clear <dir> [tries]
  local dir="$1" tries="${2:-40}" n
  for _ in $(seq 1 "$tries"); do
    n="$(python3 - "$dir" <<'PY'
import os, sys
from pathlib import Path
want = Path(sys.argv[1]).resolve()
n = 0
for entry in Path("/proc").iterdir():
    if not entry.name.isdigit():
        continue
    try:
        if (entry / "cwd").resolve() == want:
            n += 1
    except OSError:
        pass
print(n)
PY
)"
    [ "$n" = "0" ] && return 0
    sleep 0.25
  done
  return 1
}

# ===================================================================================================
# §E — concurrency.  Own FLEET_HOME, serial section.
# ===================================================================================================

# E1 — GIVEN three enrolled slots and ten dispatchers held at a start barrier, WHEN the barrier opens,
# THEN exactly three exit 0 onto three DISTINCT slots, seven exit 3, and three leases are held — on every
# one of twenty iterations. The distinctness is the load-bearing half: a pool that hands the same slot to
# two winners still produces 3x exit 0, so counting exit codes alone would pass a double-lease.
e1_ten_dispatchers_three_slots() {
  local iters=20 procs=10 log="$EV/out/E1-per-iteration.tsv" bad=0 i k
  printf 'iter\texit0\texit3\tother\tdistinct_slots\tleases_held\tverdict\n' > "$log"
  for i in $(seq 1 "$iters"); do
    g3_home "e1/i$i" 3
    g3_barrier_new
    local pids=() rcs="$CD/rc.txt"; : > "$rcs"
    for k in $(seq 1 "$procs"); do
      g3_spawn "w$k" dispatch --profile "$P_WORKER" --title "e1 i$i w$k" --base 00000000 --cap 10
      pids+=("$G3_PID")
    done
    sleep 0.3
    g3_barrier_open
    for k in $(seq 1 "$procs"); do wait "${pids[k-1]}"; printf '%s\n' "$?" >> "$rcs"; done
    g3_barrier_close

    local n0 n3 other slots distinct held verdict
    n0="$(g3_count_rc "$rcs" 0)"; n3="$(g3_count_rc "$rcs" 3)"
    other=$((procs - n0 - n3))
    slots="$(awk '$1=="slot"{print $2}' "$CD"/w*.out | sort)"
    distinct="$(printf '%s\n' "$slots" | sort -u | grep -c . )"
    held="$(fleet leases --porcelain 2>/dev/null | awk -F'\t' '$2=="held"' | wc -l | tr -d ' ')"
    if [ "$n0" = 3 ] && [ "$n3" = 7 ] && [ "$other" = 0 ] && [ "$distinct" = 3 ] \
       && [ "$held" = 3 ]; then verdict=ok; else verdict=BAD; bad=$((bad+1)); fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$i" "$n0" "$n3" "$other" "$distinct" "$held" "$verdict" \
      >> "$log"
    g3_kill_sessions
  done
  if [ "$bad" = 0 ]; then
    g3_pass E1 "$log" "n=$iters iterations x $procs concurrent dispatch, 3 slots: every iteration 3x exit 0 / 7x exit 3, 3 distinct slots"
  else
    g3_fail E1 "$log" "n=$iters iterations x $procs concurrent dispatch: $bad iteration(s) deviated (rate $bad/$iters) — see the per-iteration log"
  fi
}

# E2 — GIVEN three enrolled slots but all ten claims naming s1 BY NAME, WHEN they race, THEN exactly one
# wins, nine exit 3, and the lease body names the winner. Reading the winner out of the lease BODY rather
# than out of the exit codes is what makes this an atomicity assertion: nine refusals are also what a
# capacity check that ran before any claim would produce, and that would prove nothing about the race.
e2_ten_claims_one_named_slot() {
  local iters=10 procs=10 log="$EV/out/E2-per-iteration.tsv" bad=0 i k
  printf 'iter\texit0\texit3\tother\twinner\tlease_body_todo_id\tverdict\n' > "$log"
  for i in $(seq 1 "$iters"); do
    g3_home "e2/i$i" 3                               # 3 enrolled, all ten target s1 by NAME, so the
    g3_barrier_new                                   # capacity guard cannot stand in for the race
    local pids=() rcs="$CD/rc.txt"; : > "$rcs"
    for k in $(seq 1 "$procs"); do
      g3_spawn "w$k" dispatch --profile "$P_WORKER" --title "e2 i$i w$k" --base 00000000 --cap 10 \
               --slot s1
      pids+=("$G3_PID")
    done
    sleep 0.3
    g3_barrier_open
    for k in $(seq 1 "$procs"); do wait "${pids[k-1]}"; printf '%s\n' "$?" >> "$rcs"; done
    g3_barrier_close

    local n0 n3 other winner body verdict
    n0="$(g3_count_rc "$rcs" 0)"; n3="$(g3_count_rc "$rcs" 3)"; other=$((procs - n0 - n3))
    winner="$(awk '$1=="todo_id"{print $2}' "$CD"/w*.out | sort -u | tr '\n' ' ' | sed 's/ $//')"
    body="$(python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1]))["todo_id"])
except Exception as e: print("UNREADABLE:%s"%e)' "$FLEET_HOME/pool/leases/s1/lease.json" 2>/dev/null)"
    if [ "$n0" = 1 ] && [ "$n3" = 9 ] && [ "$other" = 0 ] && [ "$winner" = "$body" ]; then
      verdict=ok; else verdict=BAD; bad=$((bad+1)); fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$i" "$n0" "$n3" "$other" "$winner" "$body" "$verdict" >> "$log"
    g3_kill_sessions
  done
  if [ "$bad" = 0 ]; then
    g3_pass E2 "$log" "n=$iters x $procs concurrent claims on ONE named slot: 1 winner / 9x exit 3 every time, lease body names the winner"
  else
    g3_fail E2 "$log" "n=$iters x $procs concurrent named-slot claims: $bad iteration(s) deviated (rate $bad/$iters)"
  fi
}

# E3 — GIVEN a WIP cap of 1, WHEN five dispatchers race twenty times, THEN exactly one enters active dev
# every time and the rest exit 4 NAMING the cap. The window is real rather than theoretical: the cap is
# evaluated from RECORDS and the record is written AFTER the gate, so a read-then-write cap admits two.
e3_concurrent_under_cap_one() {
  local iters=20 procs=5 log="$EV/out/E3-per-iteration.tsv" bad=0 i k
  printf 'iter\texit0\texit4\tother\tcap_named\tverdict\n' > "$log"
  for i in $(seq 1 "$iters"); do
    g3_home "e3/i$i" 5                               # 5 slots, so the POOL is never the limiter
    g3_barrier_new
    local pids=() rcs="$CD/rc.txt"; : > "$rcs"
    for k in $(seq 1 "$procs"); do
      g3_spawn "w$k" dispatch --profile "$P_WORKER" --title "e3 i$i w$k" --base 00000000 --cap 1
      pids+=("$G3_PID")
    done
    sleep 0.3
    g3_barrier_open
    for k in $(seq 1 "$procs"); do wait "${pids[k-1]}"; printf '%s\n' "$?" >> "$rcs"; done
    g3_barrier_close

    local n0 n4 other named verdict
    n0="$(g3_count_rc "$rcs" 0)"; n4="$(g3_count_rc "$rcs" 4)"; other=$((procs - n0 - n4))
    named="$(grep -l 'the WIP cap is 1' "$CD"/w*.out 2>/dev/null | wc -l | tr -d ' ')"
    if [ "$n0" = 1 ] && [ "$n4" = "$((procs-1))" ] && [ "$other" = 0 ] \
       && [ "$named" = "$((procs-1))" ]; then verdict=ok; else verdict=BAD; bad=$((bad+1)); fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$i" "$n0" "$n4" "$other" "$named" "$verdict" >> "$log"
    g3_kill_sessions
  done
  if [ "$bad" = 0 ]; then
    g3_pass E3 "$log" "n=$iters x $procs concurrent dispatch at cap 1: exactly one entered active dev every time, the rest exit 4 naming the cap"
  else
    g3_fail E3 "$log" "n=$iters x $procs concurrent dispatch at cap 1: $bad iteration(s) admitted the wrong number (rate $bad/$iters) — the cap is evaluated from RECORDS and the record is written after the gate"
  fi
}

# E4 — GIVEN a dispatch actively mutating the store, WHEN six `board` reads run against it concurrently,
# fifty times, THEN no read sees a torn record, a short row, or a traceback. `board` is the verb an
# operator polls while work is in flight, so a reader that can observe a half-written record turns routine
# polling into a false alarm — and the alarm arrives at the moment the fleet is busiest.
e4_board_never_tears() {
  local iters=50 reads=6 log="$EV/out/E4-per-iteration.tsv" bad=0 i
  g3_home "e4" 50
  printf 'iter\tboard_reads\tbad_field_count\tboard_nonzero_exit\ttraceback\tcadence_unreadable\tverdict\n' > "$log"
  local todo_ids="$CD/todo-ids.txt"; : > "$todo_ids"
  for i in $(seq 1 "$iters"); do
    g3_barrier_new "go$i"
    local dpid bpid
    g3_spawn "d$i" dispatch --profile "$P_WORKER" --title "e4 w$i" --base 00000000 --cap 200
    dpid=$G3_PID
    (
      exec 8<"$G3_GO"
      for r in $(seq 1 "$reads"); do
        python3 -m fleet.cli board --porcelain > "$CD/b$i-$r.out" 2> "$CD/b$i-$r.err"
        printf '%s\n' "$?" >> "$CD/b$i.rc"
      done
    ) &
    bpid=$!
    sleep 0.25
    g3_barrier_open
    wait "$dpid"; printf '%s\n' "$?" >> "$CD/d.rc"
    wait "$bpid"
    g3_barrier_close
    awk '$1=="todo_id"{print $2}' "$CD/d$i.out" >> "$todo_ids"

    # A torn record shows up three ways, and all three are checked: a row with the wrong number of
    # fields, a non-zero exit from `board`, or a python traceback (json.loads is not guarded).
    local badfields nonzero tb cad verdict
    badfields="$(awk -F'\t' -v want="$G3_BOARD_COLS" 'NF!=want && NF>0 {c++} END{print c+0}' "$CD"/b$i-*.out)"
    nonzero="$(awk '$1!=0' "$CD/b$i.rc" 2>/dev/null | wc -l | tr -d ' ')"
    tb="$(g3_traceback_in "$CD"/b$i-*.err)"; [ -n "$tb" ] && tb=yes || tb=no
    cad="$(grep -l 'could not be evaluated' "$CD"/b$i-*.err 2>/dev/null | wc -l | tr -d ' ')"
    if [ "$badfields" = 0 ] && [ "$nonzero" = 0 ] && [ "$tb" = no ]; then
      verdict=ok; else verdict=BAD; bad=$((bad+1)); fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$i" "$reads" "$badfields" "$nonzero" "$tb" "$cad" \
      "$verdict" >> "$log"
  done
  # Every record ever dispatched must be renderable at the end, with a non-empty state.
  local missing=0 id
  fleet board --porcelain > "$CD/board-final.out" 2>/dev/null
  while read -r id; do
    [ -z "$id" ] && continue
    awk -F'\t' -v w="$id" '$1==w && $3!=""' "$CD/board-final.out" | grep -q . \
      || missing=$((missing+1))
  done < "$todo_ids"
  g3_kill_sessions
  if [ "$bad" = 0 ] && [ "$missing" = 0 ]; then
    g3_pass E4 "$log" "n=$iters iterations, $((iters*reads)) concurrent board reads against a live dispatch: no torn record, no short row, no traceback; all $(grep -c . "$todo_ids") records render with a state"
  else
    g3_fail E4 "$log" "n=$iters iterations, $((iters*reads)) board reads: $bad iteration(s) saw a torn/short/failed render, $missing record(s) unrenderable at the end"
  fi
}

# E5 — GIVEN one instant, WHEN two `declare` calls race on it, THEN the file is always valid JSON, the
# last writer wins, and every echo-back is a value a CONSUMER could read. Valid JSON on its own is too weak
# an assertion: a declaration that parses but reports a phase nobody set is exactly the failure here, and
# it is invisible to a check that only asks whether the file loads.
e5_concurrent_declare() {
  local iters=20 log="$EV/out/E5-per-iteration.tsv" bad=0 i
  printf 'iter\techo_a\techo_b\tconsumer_reads\tjson_valid\tverdict\n' > "$log"
  for i in $(seq 1 "$iters"); do
    g3_home "e5/i$i" 1
    fleet dispatch --profile "$P_WORKER" --title "e5 i$i" --base 00000000 --cap 5 \
      > "$CD/dispatch.out" 2>&1
    local child; child="$(awk '$1=="instant"{print $2}' "$CD/dispatch.out")"
    if [ -z "$child" ]; then
      printf '%s\tSETUP-FAILED\t-\t-\t-\tBAD\n' "$i" >> "$log"; bad=$((bad+1)); g3_kill_sessions
      continue
    fi
    g3_barrier_new
    local pa pb
    g3_spawn a declare --instant "$child" --phase awaiting-ci --watcher $$;      pa=$G3_PID
    g3_spawn b declare --instant "$child" --phase blocked-on-review; pb=$G3_PID
    sleep 0.25
    g3_barrier_open
    wait "$pa"; wait "$pb"
    g3_barrier_close

    local ea eb reader valid verdict
    ea="$(awk '$1=="phase"{print $2}' "$CD/a.out")"; eb="$(awk '$1=="phase"{print $2}' "$CD/b.out")"
    reader="$(python3 -c 'import json,sys
try:
    print(json.load(open(sys.argv[1])).get("phase","<none>"))
except Exception as e:
    print("UNREADABLE:%s"%type(e).__name__)' "$child/.fleet/declare.json")"
    case "$reader" in UNREADABLE:*) valid=no;; *) valid=yes;; esac
    # Last writer wins, the file is ALWAYS valid JSON, and both echo-backs are values a consumer
    # really could read — an echo-back naming something never written is the RCF-9 failure returning.
    verdict=ok
    [ "$valid" = yes ] || verdict=BAD
    for e in "$ea" "$eb"; do
      case "$e" in awaiting-ci|blocked-on-review) ;; *) verdict=BAD;; esac
    done
    case "$reader" in awaiting-ci|blocked-on-review) ;; *) verdict=BAD;; esac
    [ "$verdict" = ok ] || bad=$((bad+1))
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$i" "${ea:-<none>}" "${eb:-<none>}" "$reader" "$valid" \
      "$verdict" >> "$log"
    g3_kill_sessions
  done
  if [ "$bad" = 0 ]; then
    g3_pass E5 "$log" "n=$iters x 2 concurrent declare on one instant: file always valid JSON, last writer wins, every echo-back is a value a consumer could read"
  else
    g3_fail E5 "$log" "n=$iters x 2 concurrent declare: $bad iteration(s) produced invalid JSON or an echo-back no consumer could read (rate $bad/$iters)"
  fi
}

e6_concurrent_harvest_two_workers() {
  local iters=5 log="$EV/out/E6-per-iteration.tsv" bad=0 i
  printf 'iter\trc_a\trc_b\tslots_free\trecords_stamped\trecords_readable\ttraceback\tharvested_rows\tother_violations\tverdict\n' > "$log"
  for i in $(seq 1 "$iters"); do
    g3_home "e6/i$i" 2
    local ids=() paths=() k
    for k in a b; do
      fleet dispatch --profile "$P_WORKER" --title "e6 i$i $k" --base 00000000 --cap 5 \
        > "$CD/dispatch-$k.out" 2>&1
      ids+=("$(awk '$1=="todo_id"{print $2}' "$CD/dispatch-$k.out")")
      paths+=("$(awk '$1=="instant"{print $2}' "$CD/dispatch-$k.out")")
    done
    # Each worker earns its gate, renames its own folder, and its pane is closed first: `harvest`
    # releases the slot NON-forced, and a live pid in the slot is a correct refusal (OBS-48), not
    # this case's subject.
    local ok_setup=1 idx=0 newpath=()
    for k in 0 1; do
      fleet review --instant "${paths[k]}" --scope all --verdict READY > "$CD/review-$k.out" 2>&1
      fleet complete --instant "${paths[k]}" > "$CD/complete-$k.out" 2>&1 || ok_setup=0
      newpath+=("$(awk '$1=="path"{print $2}' "$CD/complete-$k.out")")
      fleet close --id "${ids[k]}" --force > "$CD/close-$k.out" 2>&1
    done
    g3_wait_cwd_clear "$G3_SLOTS/s1" || true
    g3_wait_cwd_clear "$G3_SLOTS/s2" || true
    if [ "$ok_setup" = 0 ]; then
      printf '%s\tSETUP-FAILED\t-\t-\t-\t-\t-\tBAD\n' "$i" >> "$log"; bad=$((bad+1))
      g3_kill_sessions; continue
    fi

    g3_barrier_new
    local pa pb ra rb
    #: `--porcelain`, so the rows are asserted on by KIND rather than by reading an aligned column layout.
    #: The first attempt at the assertion below matched tab-separated fields against the human format and
    #: silently counted zero of everything — an assertion anchored to the reporting layer's spacing, which
    #: is `OBS-50`'s family and would have read as a pass had the counts been compared the other way round.
    g3_spawn ha harvest --porcelain --id "${ids[0]}"; pa=$G3_PID
    g3_spawn hb harvest --porcelain --id "${ids[1]}"; pb=$G3_PID
    sleep 0.25
    g3_barrier_open
    wait "$pa"; ra=$?
    wait "$pb"; rb=$?
    g3_barrier_close

    local free stamped readable tb verdict
    free="$(fleet leases --porcelain 2>/dev/null | awk -F'\t' '$2=="free"' | wc -l | tr -d ' ')"
    stamped="$(python3 -c 'import json,glob,sys
n=0
for p in glob.glob(sys.argv[1]+"/records/*.json"):
    try:
        n += 1 if json.load(open(p)).get("harvested_at") else 0
    except Exception: pass
print(n)' "$FLEET_HOME")"
    readable="$(python3 -c 'import json,glob,sys
ok=0
for p in glob.glob(sys.argv[1]+"/records/*.json"):
    try:
        json.load(open(p)); ok+=1
    except Exception: pass
print(ok)' "$FLEET_HOME")"
    tb="$(g3_traceback_in "$CD/ha.out" "$CD/hb.out")"; [ -n "$tb" ] && tb=yes || tb=no
    #: THIS CASE'S OWN DEFECT, found on the Task 15 re-run and fixed here (see the note below the
    #: function). `harvest` reports a VIOLATION row and exits 1 — correctly — because every case in §E
    #: dispatches from the synthetic base `00000000`, whose `00000000/ISSUES.md` register does not exist
    #: on disk. That row is `unreadable-source`, and it is what the verb is supposed to say. Asserting
    #: `rc = 0` therefore made E6 UNPASSABLE for a reason that has nothing to do with concurrency:
    #: reproduced with ONE harvest, no second process. So the exit code is admitted as 0 or 1 and the
    #: violation is pinned BY KIND instead — anything other than `unreadable-source` still fails the case,
    #: and both transactions must now be visible as `harvested` rows, which is stronger than the exit code
    #: ever was on the property Plan 6 §E6 actually states.
    local harvested other_violation
    harvested="$(awk -F'\t' '$1=="harvested"' "$CD/ha.out" "$CD/hb.out" | wc -l | tr -d ' ')"
    other_violation="$(awk -F'\t' '$3=="violation" && $1!="unreadable-source"' \
                        "$CD/ha.out" "$CD/hb.out" | wc -l | tr -d ' ')"
    if { [ "$ra" = 0 ] || [ "$ra" = 1 ]; } && { [ "$rb" = 0 ] || [ "$rb" = 1 ]; } \
       && [ "$harvested" = 2 ] && [ "$other_violation" = 0 ] \
       && [ "$free" = 2 ] && [ "$stamped" = 2 ] \
       && [ "$readable" = 2 ] && [ "$tb" = no ]; then verdict=ok; else verdict=BAD; bad=$((bad+1)); fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$i" "$ra" "$rb" "$free" "$stamped" "$readable" \
      "$tb" "$harvested" "$other_violation" "$verdict" >> "$log"
    g3_kill_sessions
  done
  if [ "$bad" = 0 ]; then
    g3_pass E6 "$log" "n=$iters x 2 concurrent harvest of DIFFERENT workers: both transactions completed (2 harvested rows), both slots free, both records stamped and readable, no violation other than the synthetic base's absent register"
  else
    g3_fail E6 "$log" "n=$iters x 2 concurrent harvest: $bad iteration(s) left a transaction incomplete (rate $bad/$iters)"
  fi
}

#: E6's exit-code assertion was a HARNESS defect, and worth recording next to the case rather than in a
#: report nobody re-reads. `rc = 0` cannot happen here: `record_dispatch` registers `<base>/ISSUES.md` for
#: the base the dispatch names, every §E case names the synthetic base `00000000`, and no such register
#: exists — so every `harvest` tick emits `unreadable-source` (a VIOLATION) and exits 1. That is the verb
#: behaving as designed, and it is not concurrency: one dispatch, one harvest, no second process
#: reproduces it exactly. The case had a 5/5 "failure rate" that no product change could ever move, which
#: is the same family as an unclearable alarm — a red light whose remedy does not exist.

# E7 — GIVEN two DIFFERENT bases, WHEN `record_dispatch` runs for both concurrently, THEN both appear in
# sources.json every time. One file, two writers, read-modify-write. The lost update is silent at the
# moment it happens; the symptom surfaces later as an unregistered-base violation against a base that WAS
# registered, which reads as a product bug rather than as a race.
e7_concurrent_record_dispatch_two_bases() {
  local iters=20 log="$EV/out/E7-per-iteration.tsv" bad=0 i
  printf 'iter\trc_a\trc_b\tsources_in_registry\tbases\tregistry_readable\tverdict\n' > "$log"
  for i in $(seq 1 "$iters"); do
    g3_home "e7/i$i" 2
    g3_barrier_new
    local pa pb ra rb
    g3_spawn a dispatch --profile "$P_WORKER" --title "e7 i$i a" --base 00000001 --cap 5; pa=$G3_PID
    g3_spawn b dispatch --profile "$P_WORKER" --title "e7 i$i b" --base 00000002 --cap 5; pb=$G3_PID
    sleep 0.25
    g3_barrier_open
    wait "$pa"; ra=$?
    wait "$pb"; rb=$?
    g3_barrier_close

    local n bases readable verdict
    read -r n bases readable <<<"$(python3 -c 'import json,sys
try:
    d=json.load(open(sys.argv[1]))
    s=[e["base"] for e in d.get("sources",[])]
    print(len(s), ",".join(sorted(s)) or "-", "yes")
except Exception as e:
    print(-1, "UNREADABLE", "no")' "$FLEET_HOME/harvest/sources.json" 2>/dev/null)"
    if [ "$ra" = 0 ] && [ "$rb" = 0 ] && [ "$n" = 2 ] && [ "$bases" = "00000001,00000002" ] \
       && [ "$readable" = yes ]; then verdict=ok; else verdict=BAD; bad=$((bad+1)); fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$i" "$ra" "$rb" "$n" "$bases" "$readable" "$verdict" >> "$log"
    g3_kill_sessions
  done
  if [ "$bad" = 0 ]; then
    g3_pass E7 "$log" "n=$iters x 2 concurrent record_dispatch for DIFFERENT bases: both bases in sources.json every time"
  else
    g3_fail E7 "$log" "n=$iters x 2 concurrent record_dispatch for different bases: $bad iteration(s) lost a base or corrupted the registry (rate $bad/$iters) — harvest.register is a read-modify-write of one JSON file through a SHARED tmp path"
  fi
}

# E8 — GIVEN four stale leases, WHEN two `reap`s run concurrently, THEN every slot is freed exactly once,
# no slot is double-REPORTED, and no exception escapes. Double-reporting is asserted alongside
# double-freeing because the count is what an operator reads to decide whether the pool recovered: a reap
# that frees four slots and claims eight is wrong in the only field anyone acts on.
e8_concurrent_reap() {
  local iters=10 stale=4 log="$EV/out/E8-per-iteration.tsv" bad=0 i k
  printf 'iter\trc_a\trc_b\tfreed_union\tdouble_reported\theld_after\ttraceback\tverdict\n' > "$log"
  for i in $(seq 1 "$iters"); do
    g3_home "e8/i$i" "$stale"
    for k in $(seq 1 "$stale"); do
      fleet dispatch --profile "$P_WORKER" --title "e8 i$i w$k" --base 00000000 --cap 20 \
        > "$CD/d$k.out" 2>&1
    done
    g3_kill_sessions                                 # every lease is now STALE: no session, no pid
    for k in $(seq 1 "$stale"); do g3_wait_cwd_clear "$G3_SLOTS/s$k" || true; done

    g3_barrier_new
    local pa pb ra rb
    g3_spawn ra reap --all --porcelain; pa=$G3_PID
    g3_spawn rb reap --all --porcelain; pb=$G3_PID
    sleep 0.25
    g3_barrier_open
    wait "$pa"; ra=$?
    wait "$pb"; rb=$?
    g3_barrier_close

    local union dbl held tb verdict
    union="$(awk -F'\t' '$1=="reaped"{print $2}' "$CD/ra.out" "$CD/rb.out" | sort -u | grep -c .)"
    dbl="$(awk -F'\t' '$1=="reaped"{print $2}' "$CD/ra.out" "$CD/rb.out" | sort | uniq -d | grep -c .)"
    held="$(fleet leases --porcelain 2>/dev/null | awk -F'\t' '$2=="held"' | wc -l | tr -d ' ')"
    tb="$(g3_traceback_in "$CD/ra.out" "$CD/rb.out")"; [ -n "$tb" ] && tb=yes || tb=no
    # A slot is freed once and never double-freed, and NO exception escapes. Both processes reporting
    # the same slot is a double FREE attempt, which is what `release`'s unguarded rmdir would raise on.
    if [ "$union" = "$stale" ] && [ "$dbl" = 0 ] && [ "$held" = 0 ] && [ "$tb" = no ] \
       && { [ "$ra" = 0 ] || [ "$ra" = 4 ]; } && { [ "$rb" = 0 ] || [ "$rb" = 4 ]; }; then
      verdict=ok; else verdict=BAD; bad=$((bad+1)); fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$i" "$ra" "$rb" "$union" "$dbl" "$held" "$tb" \
      "$verdict" >> "$log"
  done
  if [ "$bad" = 0 ]; then
    g3_pass E8 "$log" "n=$iters x 2 concurrent reap over $stale stale leases: every slot freed exactly once, never double-reported, no exception escaped"
  else
    g3_fail E8 "$log" "n=$iters x 2 concurrent reap over $stale stale leases: $bad iteration(s) double-freed, left a lease, or let an exception escape (rate $bad/$iters)"
  fi
}

# E9 — GIVEN three concurrent dispatchers, WHEN a random one is SIGKILLed at a random point, twenty times,
# THEN every lease it orphaned is recovered by `reap`, BY NAME. The pass note states how many iterations
# ACTUALLY produced an orphan, because a run that happened to produce none would pass while measuring
# nothing (`SI-8`) — the exercised count is what separates this from a vacuous green.
e9_sigkill_a_dispatcher() {
  local iters=20 procs=3 log="$EV/out/E9-per-iteration.tsv" bad=0 i k
  printf 'iter\tvictim\tdelay_s\tleases_held\torphan_leases\treap_recovered\treap_says_so\tverdict\n' \
    > "$log"
  for i in $(seq 1 "$iters"); do
    g3_home "e9/i$i" "$procs"
    g3_barrier_new
    local pids=()
    for k in $(seq 1 "$procs"); do
      g3_spawn "w$k" dispatch --profile "$P_WORKER" --title "e9 i$i w$k" --base 00000000 --cap 20
      pids+=("$G3_PID")
    done
    sleep 0.3
    g3_barrier_open
    local victim delay
    victim=$(( (RANDOM % procs) + 1 ))
    delay="$(awk -v s="$RANDOM" 'BEGIN{srand(s); printf "%.3f", rand()*0.6}')"
    sleep "$delay"
    kill -9 "${pids[victim-1]}" 2>/dev/null
    for k in $(seq 1 "$procs"); do wait "${pids[k-1]}" 2>/dev/null; done
    g3_barrier_close

    # An ORPHAN lease is one no record claims AND no live process claims (no live session, nothing
    # holding the slot as cwd). That state is permitted only if `reap` then recovers it AND SAYS SO.
    local orphans held
    held="$(fleet leases --porcelain 2>/dev/null | awk -F'\t' '$2=="held"' | wc -l | tr -d ' ')"
    orphans="$(python3 - "$FLEET_HOME" "$IT_TMUX_SOCKET" <<'PY'
import json, os, shlex, sys
from pathlib import Path
home = Path(sys.argv[1])
#: The section's PRIVATE server, passed in rather than read from the environment so that an empty value
#: is a crash here and not a silent bare `tmux` reaching the live one. The product creates the pane on
#: `-L itfleet-<SECTION>` (session.TMUX_SOCKET_ENV), so asking any other server "is this lease's session
#: alive?" answers a confident NO about a session that is very much alive — every held lease would be
#: mis-classified as an orphan and E9 would assert `reap` recovers leases that were never orphaned.
socket = sys.argv[2]
if not socket:
    raise SystemExit("E9: no private tmux socket was passed; refusing to probe a bare tmux server")
records = []
for p in (home / "records").glob("*.json"):
    try:
        records.append(json.load(open(p)))
    except Exception:
        records.append({})
claimed = {r.get("slot") for r in records}
def cwd_holders(path):
    want = Path(path).resolve()
    n = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if (entry / "cwd").resolve() == want:
                n += 1
        except OSError:
            pass
    return n
orphans = []
leases = home / "pool" / "leases"
if leases.is_dir():
    for d in sorted(leases.iterdir()):
        body = d / "lease.json"
        if not body.is_file():
            orphans.append(d.name)          # a claim dir with no body is an orphan by construction
            continue
        lease = json.load(open(body))
        if lease.get("slot") in claimed:
            continue
        #: `-L <private socket>` and an EXACT `=name` target (`FI-23`): `has-session -t dt-e9-i1-w1`
        #: resolves BY PREFIX, so a stale lease could be declared live by a DIFFERENT session whose name
        #: merely starts the same way. Both arguments are shell-quoted because this goes through a shell.
        probe = "tmux -L %s has-session -t %s 2>/dev/null" % (
            shlex.quote(socket), shlex.quote("=" + (lease.get("tmux") or "")))
        if os.system(probe) == 0:
            continue
        if cwd_holders(lease["path"]):
            continue
        orphans.append(d.name)
print(",".join(orphans) or "-")
PY
)"
    local recovered says verdict
    if [ "$orphans" = "-" ]; then
      recovered=n/a; says=n/a; verdict=ok
    else
      fleet reap --all --porcelain > "$CD/reap.out" 2>&1
      local still
      still="$(python3 -c 'import sys,os
from pathlib import Path
home=Path(sys.argv[1]); want=sys.argv[2].split(",")
left=[s for s in want if (home/"pool"/"leases"/s).is_dir()]
print(",".join(left) or "-")' "$FLEET_HOME" "$orphans")"
      #: EVERY kind `reap` uses to report a recovery, DERIVED from the product rather than typed here.
      #:
      #: This matched only `reaped`, and `reaped` is the kind for freeing a normal LEASE. An INTERRUPTED
      #: CLAIM — the bodiless directory a writer leaves when it dies between the lease body's write and
      #: its rename — is reported under `reap-reclaimed`, deliberately: `cli.py:2100` says "An interrupted
      #: claim gets its OWN row and its own kind, never a `REAPED` row". `SI-7` added that kind and this
      #: case was never taught it.
      #:
      #: So every iteration whose SIGKILL landed in the mkdir->body window scored `says=no` and FAILed,
      #: while reap had in fact cleared the slot AND named it in full. Measured 2026-08-02 under load:
      #: 17 iterations produced an orphan, and the verdict tracked the row KIND with no exceptions —
      #: 14 `reaped` all ok, 3 `reap-reclaimed` all BAD, every one of the 17 actually recovered. A false
      #: RED, and `II-4`'s family: the harness not knowing a product capability and charging the product
      #: for the gap.
      #:
      #: Load-dependent because contention widens the microsecond window, which is why 120 iterations on
      #: an idle box found nothing and the first 20 under load found three.
      local kinds
      kinds="$(python3 -c 'from fleet.cli import REAPED, REAP_RECLAIMED
print(" ".join((REAPED, REAP_RECLAIMED)))')" || kinds="reaped reap-reclaimed"
      says=no
      local s k
      for s in ${orphans//,/ }; do
        for k in $kinds; do
          awk -F'\t' -v w="$s" -v k="$k" '$1==k && $2==w' "$CD/reap.out" | grep -q . && says=yes
        done
      done
      #: `E9` mode 2. An EMPTY claim directory — the SIGKILL landed between the `mkdir` and the staging
      #: write, so there is no body AND no staging file, hence no pid and no evidence the writer is dead.
      #: Below the age floor `reap` MUST NOT clear it: a bodiless claim cannot be told from one being
      #: born, and clearing it hands a live worker's slot to a second claimant. So demanding immediate
      #: recovery here demands behaviour the product is right not to have.
      #:
      #: The contract that actually matters is "no slot is lost PERMANENTLY", and this now asserts that
      #: rather than assuming it: a declined claim must be REPORTED with a wait, and then, after the
      #: floor, a second reap must genuinely recover it. That is stronger than the original check, not
      #: weaker — it adds an outcome the old version never verified.
      local declined=no
      awk -F'\t' -v w="$s" '$1=="reap-unattributable"' "$CD/reap.out" | grep -q . && declined=yes
      if [ "$still" != "-" ] && [ "$declined" = yes ]; then
        local floor
        floor="$(python3 -c 'from fleet.pool import INTERRUPTED_CLAIM_AGE_S
print(int(INTERRUPTED_CLAIM_AGE_S) + 2)')" || floor=32
        sleep "$floor"
        fleet reap --all --porcelain > "$CD/reap-after-floor.out" 2>&1
        still="$(python3 -c 'import sys
from pathlib import Path
home=Path(sys.argv[1]); want=sys.argv[2].split(",")
print(",".join([s for s in want if (home/"pool"/"leases"/s).is_dir()]) or "-")' "$FLEET_HOME" "$orphans")"
        says=yes                                  # reap DID account for it, twice: declined then cleared
      fi
      if [ "$still" = "-" ] && [ "$says" = yes ]; then recovered=yes; verdict=ok
      else recovered="$still"; verdict=BAD; bad=$((bad+1)); fi
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$i" "$victim" "$delay" "$held" "$orphans" \
      "$recovered" "$says" "$verdict" >> "$log"
    g3_kill_sessions
  done
  local orphaned
  orphaned="$(awk -F'\t' 'NR>1 && $5!="-"' "$log" | wc -l | tr -d ' ')"
  if [ "$bad" != 0 ]; then
    g3_fail E9 "$log" "n=$iters SIGKILLs of a random dispatcher: $bad iteration(s) ended with a lease no record, no process and no reap could account for (rate $bad/$iters)"
  elif [ "$orphaned" = 0 ]; then
    # `SI-8`. This case's real assertion — an orphaned lease is recoverable and reap SAYS so — only engages
    # on an iteration that actually produced an orphan, which needs the kill to land in a narrow slice of
    # its delay range. Measured: orphans appeared iff delay_s was in [0.11, 0.24], with zero exceptions over
    # 40 iterations of two independent runs, i.e. ~18% of iterations. The other ~82% recorded `verdict=ok`
    # having asserted NOTHING, and a run of 20 could report PASS with the property untested.
    #
    # That is how the inherited 9/9 came to be read as a statement about the pool when it was a statement
    # about $RANDOM: it drew exactly one in-window sample, and that one happened to be the recoverable
    # variant. The unrecoverable variant behind it (`SI-7`) was a permanently lost workspace.
    #
    # So zero exercised iterations is a SKIP with the reason, never a PASS. Absence is never success, and
    # this is that rule applied one level finer than usual: not an unrun case, an unrun ASSERTION inside a
    # case that reports itself as run.
    g3_skip E9 "$log" "n=$iters SIGKILLs completed with NO iteration producing an orphaned lease, so the case's actual property — an orphan is recoverable and reap names it — was never exercised. Not a pass: the kill has to land in roughly 18% of its delay range to create one. Re-run, or drive the kill point deterministically at the lease body's write/rename boundary"
  else
    g3_pass E9 "$log" "n=$iters SIGKILLs of a random one of $procs concurrent dispatchers at a random point: $orphaned of $iters iteration(s) ACTUALLY produced an orphaned lease and reap recovered every one of them by name. The exercised count is stated because a run that produced none proves nothing (SI-8)"
  fi
}

run_E() {
  g3_enter E
  e1_ten_dispatchers_three_slots
  e2_ten_claims_one_named_slot
  e3_concurrent_under_cap_one
  e4_board_never_tears
  e5_concurrent_declare
  e6_concurrent_harvest_two_workers
  e7_concurrent_record_dispatch_two_bases
  e8_concurrent_reap
  e9_sigkill_a_dispatcher
  g3_leave E
}

# ===================================================================================================
# §K — compaction.  Own FLEET_HOME, serial section.
# ===================================================================================================

k_main_narrative() {            # K1 K2 K3 K4 K5 K7 — one compaction, in its real lifecycle order
  g3_home "kA" 2
  local out="$CD"
  fleet dispatch --optype compact --profile "$P_COMPACT" --title "fold the stack" --base 00000000 \
    > "$out/k1-dispatch.out" 2>&1
  local rc=$? child id
  child="$(awk '$1=="instant"{print $2}' "$out/k1-dispatch.out")"
  id="$(awk '$1=="todo_id"{print $2}' "$out/k1-dispatch.out")"

  # --- K1 ---
  local born=no
  case "$child" in *-inflight-compact-*) born=yes;; esac
  if [ "$rc" = 0 ] && [ -n "$child" ] && [ -d "$child" ] && [ "$born" = yes ]; then
    g3_pass K1 "$out/k1-dispatch.out" "born $(basename "$child")"
  else
    g3_fail K1 "$out/k1-dispatch.out" "exit $rc; child='$child' is not an -inflight-compact- folder (born=$born)"
    return
  fi

  # --- K2: COMPACTED.md is INFO for the compaction's whole inflight life, never a violation ---
  fleet lint --instant "$child" --porcelain > "$out/k2-lint.out" 2>"$out/k2-lint.err"; rc=$?
  local sev
  sev="$(awk -F'\t' '$2 ~ /COMPACTED\.md$/{print $3}' "$out/k2-lint.out" | head -1)"
  local viol
  viol="$(awk -F'\t' '$3=="violation"' "$out/k2-lint.out" | wc -l | tr -d ' ')"
  if [ "$rc" = 0 ] && [ "$sev" = info ] && [ "$viol" = 0 ]; then
    g3_pass K2 "$out/k2-lint.out" "COMPACTED.md reported '$sev', exit 0, 0 violations"
  else
    g3_fail K2 "$out/k2-lint.out" "want info+exit 0, got severity='$sev' exit $rc with $viol violation(s)"
  fi

  # --- K3: dispatch is frozen and NAMES the compaction; resume is NOT (refusing a resume is an outage) ---
  fleet dispatch --profile "$P_WORKER" --title "k3 blocked" --base 00000000 \
    > "$out/k3-dispatch.out" 2>&1; rc=$?
  local names=no
  grep -qF "$(basename "$child")" "$out/k3-dispatch.out" && names=yes
  if [ "$rc" = 4 ] && [ "$names" = yes ]; then
    g3_pass K3a "$out/k3-dispatch.out" "dispatch exit 4 naming $(basename "$child")"
  else
    g3_fail K3a "$out/k3-dispatch.out" "want exit 4 naming the compaction; got exit $rc, names=$names"
  fi
  fleet resume --instant "$child" > "$out/k3-resume.out" 2>&1; rc=$?
  if [ "$rc" = 0 ]; then
    g3_pass K3b "$out/k3-resume.out" "resume exit 0 under the freeze (FD-9: refusing a resume is its own outage)"
  else
    g3_fail K3b "$out/k3-resume.out" "resume exit $rc under the freeze — a refused recovery path is the alarm that blocks the fix"
  fi

  # --- K4: compaction-status reports it and mutates NOTHING (content + mtime) ---
  local before after
  before="$(g3_manifest)"
  fleet compaction-status --porcelain > "$out/k4.out" 2>"$out/k4.err"; rc=$?
  after="$(g3_manifest)"
  local reports=no
  grep -qF "$(basename "$child")" "$out/k4.out" && reports=yes
  if [ "$reports" = yes ] && [ "$before" = "$after" ]; then
    g3_pass K4 "$out/k4.out" "names $(basename "$child"), exit $rc, zero delta over store+pool+slots+instants (content+mtime)"
  else
    g3_fail K4 "$out/k4.out" "reports=$reports; delta: $(diff <(printf '%s' "$before") <(printf '%s' "$after") | head -3 | tr '\n' ' ')"
  fi

  # --- K5: TWO INDEPENDENT RULES. The cap reports ROOM and the dispatch is STILL refused. ---
  fleet declare --instant "$child" --phase awaiting-ci --watcher $$ > "$out/k5-declare.out" 2>&1
  fleet dispatch --dry-run --profile "$P_WORKER" --title "k5 probe" --base 00000000 --porcelain \
    > "$out/k5-dryrun.out" 2>&1
  local capline exline
  capline="$(awk -F'\t' '$1=="guard.wip-cap"{print $2}' "$out/k5-dryrun.out")"
  exline="$(awk -F'\t' '$1=="guard.compaction-exclusive"{print $2}' "$out/k5-dryrun.out")"
  fleet dispatch --profile "$P_WORKER" --title "k5 real" --base 00000000 > "$out/k5-real.out" 2>&1
  rc=$?
  case "$capline" in allow*) local caproom=yes;; *) local caproom=no;; esac
  case "$exline" in refuse*) local frozen=yes;; *) local frozen=no;; esac
  if [ "$caproom" = yes ] && [ "$frozen" = yes ] && [ "$rc" = 4 ]; then
    g3_pass K5 "$out/k5-dryrun.out" "declared awaiting-ci: wip-cap says ROOM ($capline), compaction-exclusive still REFUSES, real dispatch exit 4"
  else
    g3_fail K5 "$out/k5-dryrun.out" "caproom=$caproom frozen=$frozen real-dispatch-exit=$rc; capline='$capline' exline='$exline'"
  fi

  # --- K7: rename to -complete-compact- WITHOUT COMPACTED.md => violation; write it => clean, freeze lifts ---
  fleet review --instant "$child" --scope all --verdict READY > "$out/k7-review.out" 2>&1
  fleet complete --instant "$child" > "$out/k7-complete.out" 2>&1; rc=$?
  local done_path
  done_path="$(awk '$1=="path"{print $2}' "$out/k7-complete.out")"
  if [ "$rc" != 0 ] || [ -z "$done_path" ] || [ ! -d "$done_path" ]; then
    g3_fail K7 "$out/k7-complete.out" "could not reach -complete-compact-: complete exit $rc, path='$done_path'"
    return
  fi
  fleet lint --instant "$done_path" --porcelain > "$out/k7-lint-before.out" 2>&1
  local rc_before=$?
  local v_before
  v_before="$(awk -F'\t' '$3=="violation" && $2 ~ /COMPACTED\.md$/' "$out/k7-lint-before.out" | wc -l | tr -d ' ')"
  cat > "$done_path/COMPACTED.md" <<'MD'
# COMPACTED — integration fixture (§K7)

## 1. Inputs folded
- (fixture) this compaction folded no real instant; §K6 covers the four-part contract.

## 2. Stacked chain per repo
- (fixture) none.

## 3. Merged ACs with proof paths
- (fixture) none.

## 4. Input issues reconciled
- (fixture) none.
MD
  fleet lint --instant "$done_path" --porcelain > "$out/k7-lint-after.out" 2>&1
  local rc_after=$?
  local v_after
  v_after="$(awk -F'\t' '$3=="violation"' "$out/k7-lint-after.out" | wc -l | tr -d ' ')"
  fleet dispatch --profile "$P_WORKER" --title "k7 after" --base 00000000 > "$out/k7-dispatch.out" 2>&1
  local rc_disp=$?
  if [ "$v_before" -ge 1 ] && [ "$rc_before" = 1 ] && [ "$v_after" = 0 ] && [ "$rc_after" = 0 ] \
     && [ "$rc_disp" = 0 ]; then
    g3_pass K7 "$out/k7-lint-after.out" "-complete-compact- without COMPACTED.md: $v_before violation(s), exit $rc_before; after writing it: clean exit $rc_after; the freeze LIFTED (dispatch exit 0)"
  else
    g3_fail K7 "$out/k7-lint-after.out" "before: $v_before violation(s)/exit $rc_before (want >=1/1); after: $v_after violation(s)/exit $rc_after (want 0/0); post-freeze dispatch exit $rc_disp (want 0)"
  fi
  g3_kill_sessions
}

# K6 — GIVEN `COMPACTED.md`'s four-part contract, WHEN this build is searched for either a producer or a
# checker of it, THEN neither exists — so the case records WHY it cannot be asserted and SKIPs, naming the
# search it performed. A skip that states its reason is the honest outcome here; a pass would certify a
# contract that nothing in the product enforces, which is worse than an admitted gap.
k6_four_part_contract() {
  local note ev="$EV/out/K6-why-not-runnable.txt"
  mkdir -p "$EV/out"
  {
    echo "K6 — 'COMPACTED.md carries the four-part contract' has no assertion available in this build."
    echo
    echo "Searched for a producer and for a checker:"
    echo "  * No verb in cli.VERBS writes COMPACTED.md (grep -rn COMPACTED src/ hits layout.py only)."
    echo "  * layout.validate is presence-only, by its own docstring: 'Check one instant against its"
    echo "    cell. Presence only — never content.' The matrix rows for COMPACTED.md are"
    echo "    (inflight,compact)=due-later, (complete,compact)=required, (abort,compact)=optional."
    echo "  * No rule anywhere reads inputs, per-repo stacked chains, merged ACs with proof paths, or"
    echo "    input-issue reconciliation. grep -rni 'four-part|reconciled|stacked chain' src/ -> 0 hits."
    echo
    echo "So any test written here would assert only that a file this harness itself wrote contains the"
    echo "words this harness put in it. It would pass whatever the implementation did, and would keep"
    echo "passing if the contract were dropped entirely — which makes it a false green, not a test."
    echo "Reported as unrunnable rather than run vacuously: absence is never success."
  } > "$ev"
  note="no verb produces COMPACTED.md and no rule checks its CONTENT (layout.validate is presence-only), so no assertion here can fail if the four-part contract is violated"
  g3_skip K6 "$ev" "$note"
}

# K8 — GIVEN a compaction that was dispatched and then ABORTED, WHEN lint runs and a dispatch is
# attempted, THEN lint emits no `COMPACTED.md` row at all — not even an info — and the freeze is lifted
# (dispatch exit 0). Both halves matter: an abandoned compaction that kept freezing dispatch would be an
# outage with no verb to clear it, and an info row would train the reader to ignore the column.
k8_abort_lifts_the_freeze() {
  g3_home "kB" 2
  local out="$CD"
  fleet dispatch --optype compact --profile "$P_COMPACT" --title "fold then abort" --base 00000000 \
    > "$out/dispatch.out" 2>&1
  local child id
  child="$(awk '$1=="instant"{print $2}' "$out/dispatch.out")"
  id="$(awk '$1=="todo_id"{print $2}' "$out/dispatch.out")"
  if [ -z "$child" ] || [ ! -d "$child" ]; then
    g3_fail K8 "$out/dispatch.out" "setup: no inflight compaction was created"; return
  fi
  # The plan's literal step first, so the OBS-48 interaction is observed rather than designed around:
  # `abort` releases the lease NON-forced and a live pane sits in the slot as its cwd.
  fleet abort --instant "$child" --reason "integration fixture: K8 needs an -abort-compact- instant" \
    > "$out/abort-first.out" 2>&1
  local rc_first=$?
  local note_first="direct abort with the pane still live: exit $rc_first"
  if [ "$rc_first" != 0 ]; then
    fleet close --id "$id" --force > "$out/close.out" 2>&1
    g3_wait_cwd_clear "$G3_SLOTS/s1" || true
    g3_wait_cwd_clear "$G3_SLOTS/s2" || true
    fleet abort --instant "$child" --reason "integration fixture: K8 needs an -abort-compact- instant" \
      > "$out/abort.out" 2>&1
  else
    cp "$out/abort-first.out" "$out/abort.out"
  fi
  local rc=$? aborted
  aborted="$(awk '$1=="path"{print $2}' "$out/abort.out")"
  if [ -z "$aborted" ] || [ ! -d "$aborted" ]; then
    g3_fail K8 "$out/abort.out" "abort did not produce an -abort-compact- folder ($note_first, second attempt exit $rc)"
    return
  fi
  fleet lint --instant "$aborted" --porcelain > "$out/lint.out" 2>&1
  local rc_lint=$? rows
  rows="$(awk -F'\t' '$2 ~ /COMPACTED\.md$/' "$out/lint.out" | wc -l | tr -d ' ')"
  local viol
  viol="$(awk -F'\t' '$3=="violation"' "$out/lint.out" | wc -l | tr -d ' ')"
  fleet dispatch --profile "$P_WORKER" --title "k8 after" --base 00000000 > "$out/dispatch2.out" 2>&1
  local rc_disp=$?
  if [ "$rc_lint" = 0 ] && [ "$viol" = 0 ] && [ "$rows" = 0 ] && [ "$rc_disp" = 0 ]; then
    g3_pass K8 "$out/lint.out" "-abort-compact-: lint clean with NO COMPACTED.md row at all (optional, not even info); freeze lifted (dispatch exit 0). $note_first"
  else
    g3_fail K8 "$out/lint.out" "lint exit $rc_lint with $viol violation(s) and $rows COMPACTED.md row(s) (want 0/0/0); post-abort dispatch exit $rc_disp (want 0). $note_first"
  fi
  g3_kill_sessions
}

# K9 — GIVEN `--optype compact` handed a WORKER profile, WHEN dispatch runs, THEN it exits 4 naming the
# profile BEFORE any side effect: zero leases, zero records, zero instants, and a zero delta over content
# AND mtime. Refusing AFTER a partial build is the failure mode this exists for, and only the manifest
# comparison can tell the two apart — the exit code is identical either way.
k9_wrong_kind_refused_before_any_side_effect() {
  g3_home "kC" 2
  local out="$CD" before after
  before="$(g3_manifest)"
  fleet dispatch --optype compact --profile "$P_WORKER" --title "k9 wrong kind" --base 00000000 \
    > "$out/dispatch.out" 2>&1
  local rc=$?
  after="$(g3_manifest)"
  local leases records instants names
  leases="$(find "$FLEET_HOME/pool/leases" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')"
  records="$(find "$FLEET_HOME/records" -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"
  instants="$(find "$FLEET_INSTANTS" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')"
  names=no; grep -qF "$P_WORKER" "$out/dispatch.out" && names=yes
  if [ "$rc" = 4 ] && [ "$leases" = 0 ] && [ "$records" = 0 ] && [ "$instants" = 0 ] \
     && [ "$before" = "$after" ] && [ "$names" = yes ]; then
    g3_pass K9 "$out/dispatch.out" "exit 4 naming the profile, BEFORE any side effect: 0 leases, 0 records, 0 instants, zero delta (content+mtime)"
  else
    g3_fail K9 "$out/dispatch.out" "exit $rc (want 4); leases=$leases records=$records instants=$instants names_profile=$names; delta: $(diff <(printf '%s' "$before") <(printf '%s' "$after") | head -3 | tr '\n' ' ')"
  fi
}

# K10 — GIVEN three slots and a cap of 5, so that neither the pool nor the WIP cap can stand in for the
# exclusivity rule, WHEN two compaction dispatches race twenty times, THEN exactly one compaction exists
# every time and the second is refused BY THE FIRST rather than by capacity.
k10_two_concurrent_compactions() {
  local iters=20 log="$EV/out/K10-per-iteration.tsv" bad=0 i
  printf 'iter\trc_a\trc_b\tinflight_compact_folders\tcompact_records\tsecond_refused_by_first\tverdict\n' \
    > "$log"
  for i in $(seq 1 "$iters"); do
    g3_home "kD/i$i" 3                               # 3 slots and cap 5: neither the pool nor the WIP
    g3_barrier_new                                   # cap can stand in for the exclusivity rule
    local pa pb ra rb
    g3_spawn a dispatch --optype compact --profile "$P_COMPACT" --title "k10 i$i a" \
             --base 00000000 --cap 5; pa=$G3_PID
    g3_spawn b dispatch --optype compact --profile "$P_COMPACT" --title "k10 i$i b" \
             --base 00000000 --cap 5; pb=$G3_PID
    sleep 0.25
    g3_barrier_open
    wait "$pa"; ra=$?
    wait "$pb"; rb=$?
    g3_barrier_close

    local folders recs refused verdict
    folders="$(find "$FLEET_INSTANTS" -mindepth 1 -maxdepth 1 -type d -name '*-inflight-compact-*' \
               2>/dev/null | wc -l | tr -d ' ')"
    recs="$(python3 -c 'import json,glob,sys
n=0
for p in glob.glob(sys.argv[1]+"/records/*.json"):
    try:
        r=json.load(open(p))
        n += 1 if "-inflight-compact-" in r.get("child_instant","") else 0
    except Exception: pass
print(n)' "$FLEET_HOME")"
    refused=no
    grep -qE 'compaction-exclusive|a compaction is exclusive' "$CD/a.out" "$CD/b.out" 2>/dev/null \
      && refused=yes
    if [ "$folders" = 1 ] && [ "$recs" = 1 ] && [ "$refused" = yes ] \
       && { { [ "$ra" = 0 ] && [ "$rb" = 4 ]; } || { [ "$ra" = 4 ] && [ "$rb" = 0 ]; }; }; then
      verdict=ok; else verdict=BAD; bad=$((bad+1)); fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$i" "$ra" "$rb" "$folders" "$recs" "$refused" "$verdict" \
      >> "$log"
    g3_kill_sessions
  done
  if [ "$bad" = 0 ]; then
    g3_pass K10 "$log" "n=$iters x 2 concurrent compaction dispatches: exactly one compaction existed every time, the second refused by the first"
  else
    g3_fail K10 "$log" "n=$iters x 2 concurrent compaction dispatches: $bad iteration(s) ended with the wrong number of compactions (rate $bad/$iters) — CompactionExclusive is evaluated from RECORDS and the record is written after the gate"
  fi
}

run_K() {
  g3_enter K
  k_main_narrative                                   # K1 K2 K3 K4 K5 K7
  k6_four_part_contract
  k8_abort_lifts_the_freeze
  k9_wrong_kind_refused_before_any_side_effect
  k10_two_concurrent_compactions
  g3_leave K
}

# ===================================================================================================

#: This runner OWNS its rows (`it_own_cases`, `SI-4`): the prior rows for the cases THIS invocation is
#: about to produce are dropped first, so the results file is the CURRENT verdict per case rather than an
#: append-only log that has to be read backwards. Without it a re-run leaves the superseded FAIL sitting
#: next to the new PASS and `grep -c FAIL` becomes a wrong answer.
#
#: Scoped to the SELECTION, not to everything the file can emit. `run-group3.sh E` must not delete §K's
#: rows, because it is not going to write them back — that would turn supersession into deletion and
#: re-introduce NOT-RUN cases (AC-3) by the very mechanism meant to eliminate them.
G3_ARG="${1:-all}"
g3_owned_cases() {
  #: `private-leak` added with `II-1`: a section must OWN every row it writes, or the merge keeps a stale
  #: copy of it alongside the fresh one.
  local e_iso='ISOLATION-E-(enter|leave|live-tmux|claude-count|private-leak)'
  local k_iso='ISOLATION-K-(enter|leave|live-tmux|claude-count|private-leak)'
  local e_all='E[1-9]' k_all='K([1-9]|10)|K3[ab]'
  case "$1" in
    E)      printf '%s|%s' "$e_all" "$e_iso" ;;
    K)      printf '%s|%s' "$k_all" "$k_iso" ;;
    all)    printf '%s|%s|%s|%s' "$e_all" "$k_all" "$e_iso" "$k_iso" ;;
    E[1-9]) printf '%s|%s' "$1" "$e_iso" ;;
    #: An unrecognised argument exits 2 below without running anything, so it must own nothing. A regex
    #: that matched everything here would wipe the file on a typo.
    *)      printf 'G3-OWNS-NOTHING' ;;
  esac
}
it_own_cases "$(g3_owned_cases "$G3_ARG")"

#: Per-case entry points. Added on the Task 15 re-run: re-running one case after a targeted change (or to
#: confirm a mutation is caught) should not cost the whole section, and the section-level `g3_enter` /
#: `g3_leave` isolation contract is asserted either way — a single case is never run without it.
case "$G3_ARG" in
  E) run_E ;;
  K) run_K ;;
  all) run_E; run_K ;;
  E1) g3_enter E; e1_ten_dispatchers_three_slots; g3_leave E ;;
  E2) g3_enter E; e2_ten_claims_one_named_slot; g3_leave E ;;
  E3) g3_enter E; e3_concurrent_under_cap_one; g3_leave E ;;
  E4) g3_enter E; e4_board_never_tears; g3_leave E ;;
  E5) g3_enter E; e5_concurrent_declare; g3_leave E ;;
  E6) g3_enter E; e6_concurrent_harvest_two_workers; g3_leave E ;;
  E7) g3_enter E; e7_concurrent_record_dispatch_two_bases; g3_leave E ;;
  E8) g3_enter E; e8_concurrent_reap; g3_leave E ;;
  E9) g3_enter E; e9_sigkill_a_dispatcher; g3_leave E ;;
  *) echo "usage: $0 [E|K|all|E1..E9]" >&2; exit 2 ;;
esac

printf '\n--- RESULTS-group3.tsv ---\n'
column -t -s "$(printf '\t')" "$RESULTS" 2>/dev/null || cat "$RESULTS"
#: `II-11`. Was `exit "$IT_FAILED"` — a COUNT. `exit` truncates modulo 256, so a section with
#: exactly 256 failures reported SUCCESS, and one with 300 reported 44, a number meaning nothing
#: to any reader. An exit status is a one-byte verdict, not a tally: the count is already printed
#: on the line above and is in the register, which is where a consumer should read it anyway.
if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
exit 1
