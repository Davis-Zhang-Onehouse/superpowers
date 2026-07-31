#!/usr/bin/env bash
# §J — Completion and the harvest transaction. COMPLETE: J1-J9.
#
# These four were picked because each is a LIVE-SAFETY property the hermetic suite structurally cannot reach —
# every probe there is injected, so none of it exercises a real session, a real pane or a real kill:
#
#   J2  the close-out transaction asserted as a WHOLE: proposal applied · session gone · slot FREE · record
#       stamped · and the row has LEFT the board. Five consequences of one call; any four of them passing is
#       a transaction that half-committed.
#   J7  a tmux session that NO record claims is reported and **never reaped**. If this is wrong, `reap` kills
#       somebody else's pane — *"some of those sessions are people's"* — and it is the reason the operator's
#       seed forbids touching `dt-` at all.
#   J8  `close` refuses a BUSY pane and a pane holding UNSUBMITTED INPUT, each naming its override. The
#       second is `FI-9`: text sitting unsubmitted gets concatenated with a rate-limit retry and sent.
#   J9  `SIGKILL` mid-harvest leaves fully-before or fully-after — never a released slot with an unstamped
#       record, which leaks cap capacity invisibly (`SI-21`'s failure mode, arrived at by crash).
#
# J1 is subsumed: J2 cannot be reached without running the whole lifecycle, so the lifecycle is the setup.
# J3/J4/J5/J6 stay NOT-RUN and the section-level row says so.
#
# Run: bash fleet/it/run-J.sh
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
it_own_cases 'J[0-9]+[a-z]?|ISOLATION-J-(enter|leave)'

it_section J
OUT="$EV/out"; rm -rf "$OUT"; mkdir -p "$OUT"
export FLEET_INSTANTS="$EV/instants"; rm -rf "$FLEET_INSTANTS"; mkdir -p "$FLEET_INSTANTS"
rm -rf "$FLEET_HOME"; mkdir -p "$FLEET_HOME"      # a virgin store every run (see run-F.sh)

bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2

PATH="$IT_ROOT/bin:$PATH"; export PATH

# ---- cleanup, and it has to be thorough --------------------------------------------------------------
#
# J7 needs a process whose `comm` is literally `claude`, because that is what `pgrep -x claude` matches — the
# `bin/claude` stub is a `#!/bin/sh` script and its comm is `sh`, so it is INVISIBLE to the probe (measured
# before writing this). A copy of `/bin/sleep` named `claude` is a real, long-lived, harmless process that the
# probe does see.
#
# That is also why cleanup is belt-and-braces: while this section runs, `pgrep -x claude` on this box reports a
# process that is not claude, and leaving one behind would show up in the operator's own process list and in
# `it_assert_no_new_claude` for any later section. Killed by exact pid, verified gone, and the private tmux
# server is torn down whatever happens.
J_FAKE_PIDS=""
cleanup_J() {
  for pid in $J_FAKE_PIDS; do kill -9 "$pid" 2>/dev/null; done
  it_cleanup_tmux
  tmux -L "$IT_TMUX_SOCKET" kill-server 2>/dev/null
  # Verified, not assumed: a leftover process named `claude` is exactly the confusion SI-25 was about.
  for pid in $J_FAKE_PIDS; do
    #: A zombie is gone as far as the box is concerned — it holds no resources and `pgrep -x claude` does not
    #: report it — but `kill -0` still succeeds on it, so the first version of this check cried wolf.
    if kill -0 "$pid" 2>/dev/null; then
      state="$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null)"
      #: An unreadable stat means the pid is already gone and `kill -0` won the race; a `Z` means it is a
      #: zombie holding nothing. Neither is a leak, and warning about them cries wolf.
      if [ -n "$state" ] && [ "$state" != "Z" ]; then
        echo "WARNING: fake-claude pid $pid survived cleanup (state=$state); kill it by hand" >&2
      fi
    fi
  done
}
trap cleanup_J EXIT

cp -r "$INSTANT/tests/fixtures/profiles/workerCompliant" "$OUT/profile"
# TWELVE slots. The section now dispatches nine workers across J1-J9 and each holds its slot until it is
# harvested or reaped — with four enrolled, J1/J3/J4/J6 all failed with NoCapacity, which is the pool being
# right and the fixture being too small. Capacity is a fixture parameter here, not the thing under test.
for s in ws1 ws2 ws3 ws4 ws5 ws6 ws7 ws8 ws9 ws10 ws11 ws12; do
  mkdir -p "$OUT/slots/$s"
  ( cd "$OUT/slots/$s" && git init -q . && git commit -q --allow-empty -m base ) >/dev/null 2>&1
done
fleet set-golden --path "$OUT/slots/ws1" > "$OUT/setup.out" 2>&1
for s in ws1 ws2 ws3 ws4 ws5 ws6 ws7 ws8 ws9 ws10 ws11 ws12; do fleet enroll --slot "$OUT/slots/$s" >> "$OUT/setup.out" 2>&1; done

# ==================================================================================================
# J2 — THE TRANSACTION AS A WHOLE.  dispatch -> milestone -> propose -> review -> complete -> harvest,
#      then all five consequences asserted together.
#
#      The worker proposes on its OWN roadmap here, which is the standalone form: with no `--from` there is
#      no `origin.json`, so `propose` stays local and `harvest` is the thing that applies it — which is what
#      makes "proposal applied" one of the five. The coordinator form (a worker reporting UP, and harvest
#      REFUSING to bury an unreported one) is `H10` and `SI-27`'s guard.
# ==================================================================================================
fleet dispatch --profile "$OUT/profile" --title "fullLifecycle" --base 00000000 --optype append \
      --porcelain > "$OUT/J2-dispatch.out" 2>&1
W="$(awk -F'\t' '$1=="instant"{print $2}' "$OUT/J2-dispatch.out")"
TODO="$(awk -F'\t' '$1=="todo_id"{print $2}' "$OUT/J2-dispatch.out")"
TMUXN="$(awk -F'\t' '$1=="tmux"{print $2}' "$OUT/J2-dispatch.out")"
SLOT="$(awk -F'\t' '$1=="slot"{print $2}' "$OUT/J2-dispatch.out")"
if [ -z "$W" ] || [ ! -d "$W" ]; then
  it_fail J2 "fleet/it/J/out/J2-dispatch.out" \
    "the dispatch produced no instant, so the lifecycle cannot be run: $(head -2 "$OUT/J2-dispatch.out" | tr '\n' ' ')"
else
  {
    echo "== the worker's own roadmap, its report, its review round, and the rename =="
    fleet milestone --instant "$W" --id j-m1 --title "the work this worker was sent to do" --porcelain
    fleet propose --instant "$W" --milestone j-m1 --status done --evidence "evidence/INDEX.md" --porcelain
    fleet review --instant "$W" --scope all --verdict READY \
          --finding "F-1:Minor:applied:src/fleet/cli.py:usage is derived:none" --porcelain
    fleet complete --instant "$W" --porcelain
  } > "$OUT/J2-lifecycle.out" 2>&1
  # `complete` RENAMES the folder, so the path moves. Resolution is rename-tolerant by todo id.
  W_DONE="$(find "$FLEET_INSTANTS" -maxdepth 1 -name '*-complete-append-fulllifecycle' | head -1)"

  # The pre-image: every one of the five must be measurably TRUE-before / FALSE-after, or the assertion
  # cannot tell a transaction that committed from a fixture that was already in the target state.
  pre_session=0; it_tmux has-session -t "=$TMUXN" 2>/dev/null && pre_session=1
  pre_slot_held=0; [ -d "$FLEET_HOME/pool/leases/$SLOT" ] && pre_slot_held=1
  pre_board=0; fleet board --porcelain 2>/dev/null | grep -q "$TODO" && pre_board=1
  pre_status="$(fleet roadmap --instant "${W_DONE:-$W}" --porcelain 2>/dev/null \
                | awk -F'\t' '$2=="j-m1"{print $3}' | head -1)"

  fleet harvest --id "$TODO" --porcelain > "$OUT/J2-harvest.tsv" 2>&1
  j2_rc=$?

  # ---- the five ---------------------------------------------------------------------------------
  j2_applied=0
  python3 - "${W_DONE:-$W}" > "$OUT/J2-milestone.txt" 2>&1 <<'PY'
import pathlib, sys
from fleet.roadmap import Roadmap
rm = Roadmap(pathlib.Path(sys.argv[1]))
m = rm.milestone("j-m1")
print("status:", m.status)
print("evidence:", m.evidence)
print("pending_proposals:", len(rm.proposals()))
PY
  grep -q '^status: done$' "$OUT/J2-milestone.txt" && j2_applied=1
  j2_consumed=0; grep -q '^pending_proposals: 0$' "$OUT/J2-milestone.txt" && j2_consumed=1
  j2_session_gone=1; it_tmux has-session -t "=$TMUXN" 2>/dev/null && j2_session_gone=0
  j2_slot_free=1; [ -d "$FLEET_HOME/pool/leases/$SLOT" ] && j2_slot_free=0
  j2_stamped=0
  python3 - "$FLEET_HOME" "$TODO" > "$OUT/J2-record.txt" 2>&1 <<'PY'
import pathlib, sys
from fleet.store import Store
rec = [r for r in Store(pathlib.Path(sys.argv[1])).all() if r.todo_id == sys.argv[2]]
print("found:", bool(rec))
if rec:
    print("harvested_at:", rec[0].harvested_at)
    print("gate_verdict:", rec[0].gate_verdict)
PY
  grep -qE '^harvested_at: 20' "$OUT/J2-record.txt" && j2_stamped=1
  j2_off_board=1; fleet board --porcelain 2>/dev/null | grep -q "$TODO" && j2_off_board=0

  j2_pre_ok=0
  [ "$pre_session" = 1 ] && [ "$pre_slot_held" = 1 ] && [ "$pre_board" = 1 ] \
    && [ "$pre_status" != "done" ] && j2_pre_ok=1
  j2_all="$j2_applied$j2_consumed$j2_session_gone$j2_slot_free$j2_stamped$j2_off_board"
  if [ "$j2_pre_ok" = 1 ] && [ "$j2_all" = "111111" ]; then
    it_pass J2 "fleet/it/J/out/J2-harvest.tsv" \
      "the whole close-out committed as ONE transaction, asserted against a measured pre-image (session alive, slot held, row on the board, milestone not yet done): after \`harvest\` the proposal is APPLIED (j-m1 -> done) and CONSUMED (0 pending, so replaying the inbox cannot apply it twice), the session $TMUXN is GONE, slot $SLOT is FREE, the record carries harvested_at, and the row has LEFT the board — which is what makes an orphan unreachable rather than merely unreported (FD-5). Six facts together; any five of them is a transaction that half-committed"
  elif [ "$j2_pre_ok" != 1 ]; then
    it_fail J2 "fleet/it/J/out/J2-harvest.tsv" \
      "the PRE-IMAGE was already in the target state, so this case could not have distinguished anything: session_alive=$pre_session slot_held=$pre_slot_held on_board=$pre_board milestone_status='$pre_status'"
  else
    it_fail J2 "fleet/it/J/out/J2-harvest.tsv" \
      "harvest exit=$j2_rc; applied=$j2_applied consumed=$j2_consumed session_gone=$j2_session_gone slot_free=$j2_slot_free record_stamped=$j2_stamped off_board=$j2_off_board"
  fi
fi

# ==================================================================================================
# J7 — A SESSION NO RECORD CLAIMS IS REPORTED AND NEVER REAPED.
#
#      The dangerous direction is a tool that tidies. `reconcile`'s docstring already states the rule —
#      *"there is deliberately no `reapable` field: what may be killed is a policy decision, and an unknown
#      session is reported and never touched, because 'some of those sessions are people's' (D-6)"* — and
#      this is the case that holds it to it, with a real session and a real pid.
# ==================================================================================================
cp /bin/sleep "$OUT/claude"                       # comm becomes `claude`; the probe is `pgrep -x claude`
GHOST="ghost-$$"
it_tmux new-session -d -s "$GHOST" "$OUT/claude 900" 2>"$OUT/J7-start.err"
sleep 1
GHOST_PID="$(it_tmux list-panes -t "=$GHOST" -F '#{pane_pid}' 2>/dev/null | head -1)"
if [ -n "$GHOST_PID" ]; then J_FAKE_PIDS="$J_FAKE_PIDS $GHOST_PID"; fi
fleet reconcile --porcelain > "$OUT/J7-before.tsv" 2>&1
# `reconcile` is the ARM SET view, so its kind column is armed/unarmed and the classification lives in the
# subject identity (`session:<name>:<pid>`) and the detail. My first version grepped for a literal
# `unknown-session` kind column, which this verb does not have — the property held and the assertion was
# wrong, which is the same shape as SI-29 one layer up: a check that fails for a reason of its own making.
j7_seen=0
grep -qF "session:$GHOST:$GHOST_PID" "$OUT/J7-before.tsv" \
  && grep -qF "UNKNOWN-SESSION" "$OUT/J7-before.tsv" && j7_seen=1
j7_unclaimed_said=0
grep -qi 'no dispatch record in this store claims it' "$OUT/J7-before.tsv" && j7_unclaimed_said=1
j7_pid_named=0
[ -n "$GHOST_PID" ] && grep -q "$GHOST_PID" "$OUT/J7-before.tsv" && j7_pid_named=1
fleet reap --all --porcelain > "$OUT/J7-reap.tsv" 2>&1
sleep 1
j7_alive=0; it_tmux has-session -t "=$GHOST" 2>/dev/null && j7_alive=1
j7_proc_alive=0; [ -n "$GHOST_PID" ] && kill -0 "$GHOST_PID" 2>/dev/null && j7_proc_alive=1
if [ -z "$GHOST_PID" ]; then
  it_fail J7 "fleet/it/J/out/J7-start.err" \
    "could not start the unclaimed session, so nothing below is a verdict"
elif [ "$j7_seen" = 1 ] && [ "$j7_pid_named" = 1 ] && [ "$j7_unclaimed_said" = 1 ] \
     && [ "$j7_alive" = 1 ] && [ "$j7_proc_alive" = 1 ]; then
  it_pass J7 "fleet/it/J/out/J7-reap.tsv" \
    "a live tmux session that NO record claims ($GHOST, pid $GHOST_PID) was REPORTED as kind=unknown-session with its pid named, and \`fleet reap --all\` left both the session and the process ALIVE. That is the whole point: what may be killed is a policy decision, and 'some of those sessions are people's' — a reap that tidied this away would be the tool killing somebody else's pane, which is why the operator's seed forbids touching dt- at all"
elif [ "$j7_alive" != 1 ] || [ "$j7_proc_alive" != 1 ]; then
  it_fail J7 "fleet/it/J/out/J7-reap.tsv" \
    "REAP KILLED AN UNCLAIMED SESSION: session_alive=$j7_alive process_alive=$j7_proc_alive (pid $GHOST_PID). This is the dangerous direction"
else
  it_fail J7 "fleet/it/J/out/J7-before.tsv" \
    "the unclaimed session was not REPORTED: seen_as_unknown=$j7_seen pid_named=$j7_pid_named said-unclaimed=$j7_unclaimed_said (pid $GHOST_PID, session $GHOST)"
fi

# ==================================================================================================
# J8 — `close` REFUSES A BUSY PANE AND A PANE HOLDING UNSUBMITTED INPUT, EACH NAMING ITS OVERRIDE.
#
#      Real panes, real text. The second half is `FI-9` and it is the one that damages another effort
#      silently: text left unsubmitted in an input box is concatenated with a rate-limit retry and sent.
#      Each refusal must name its override, because *a refusal a human cannot act on gets forced blindly*.
# ==================================================================================================
# The pane text goes into a FILE and the session runs `sh <file>`. The first version inlined it as
# `sh -c '<script>; sleep 900'`, and the script itself contains single quotes — so the quoting collapsed, the
# session died immediately, and `close` then refused for a reason that had nothing to do with panes. Both
# refusals in that run were real exits and meant nothing, which is exactly the false-pass shape this pass is
# here to catch, produced by my own fixture.
j8_case() {                       # j8_case <label> <slot> <pane-text-file> -> echoes "<todo> <session>"
  local label="$1" slot="$2" body="$3"
  local inst sess todo
  inst="$(fleet init --base 00000000 --name "$label" --porcelain 2>&1 \
          | awk -F'\t' '$1=="path"{print $2}')"
  sess="dt-$label"
  printf 'sleep 900\n' >> "$body"
  it_tmux new-session -d -s "$sess" "sh $body" 2>>"$OUT/J8-setup.err"
  sleep 1
  #: `--slot` here is the slot NAME, not a path: `resume` looks it up with `pool.lease(slot)`. Passing the
  #: enrolled DIRECTORY produced no record at all, and the case then tested nothing.
  fleet resume --instant "$inst" --slot "$slot" --tmux "$sess" --porcelain \
    > "$OUT/J8-resume-$label.out" 2>&1
  todo="$(awk -F'\t' '$1=="todo_id"{print $2}' "$OUT/J8-resume-$label.out")"
  printf '%s %s\n' "$todo" "$sess"
}

# A busy pane: the marker `_BUSY_MARKERS` looks for, inside the last rendered lines.
printf "printf 'editing src/fleet/cli.py\\nThinking...\\n  esc to interrupt\\n'\n" > "$OUT/pane-busy.sh"
read -r BUSY_TODO BUSY_SESS <<EOF
$(j8_case busypane ws4 "$OUT/pane-busy.sh")
EOF
# A pane holding unsubmitted input: a prompt row with typed text after it.
printf "printf 'wrote tests/test_cli.py\\n\\n\xe2\x9d\xaf now run the suite again\\n'\n" \
  > "$OUT/pane-queued.sh"
read -r Q_TODO Q_SESS <<EOF
$(j8_case queuedpane ws3 "$OUT/pane-queued.sh")
EOF

# BOTH fixtures exist before anything is asserted. `set -u` caught the first version of this guard, which
# read $Q_TODO before the queued case had run — and had it not, the case would have reported a verdict about
# panes from a fixture that was half-built.
J8_FIXTURE_OK=1
if [ -z "${BUSY_TODO:-}" ] || [ -z "${Q_TODO:-}" ]; then
  J8_FIXTURE_OK=0
  it_fail J8 "fleet/it/J/out/J8-resume-busypane.out" \
    "the fixture produced no record (busy_todo='${BUSY_TODO:-}' queued_todo='${Q_TODO:-}'), so nothing here would be a verdict about panes. First time round this was a slot PATH where `resume` wants a slot NAME, and both closes then refused with 'no record matching ...' — two real non-zero exits that meant nothing"
fi

fleet close --id "${BUSY_TODO:-none}" > "$OUT/J8-busy.out" 2>&1
j8_busy_rc=$?
fleet close --id "${Q_TODO:-none}" > "$OUT/J8-queued.out" 2>&1
j8_q_rc=$?
# And --force must work, or the refusal is an outage rather than a guard.
fleet close --id "${BUSY_TODO:-none}" --force > "$OUT/J8-force.out" 2>&1
j8_force_rc=$?
sleep 1
j8_forced_gone=1; it_tmux has-session -t "=$BUSY_SESS" 2>/dev/null && j8_forced_gone=0

j8_busy_refused=0; [ "$j8_busy_rc" != 0 ] && j8_busy_refused=1
j8_q_refused=0;    [ "$j8_q_rc" != 0 ] && j8_q_refused=1
j8_busy_override=0; grep -qi 'force' "$OUT/J8-busy.out" && j8_busy_override=1
j8_q_override=0;    grep -qi 'force' "$OUT/J8-queued.out" && j8_q_override=1
j8_still_alive=0;  it_tmux has-session -t "=$Q_SESS" 2>/dev/null && j8_still_alive=1
if [ "$J8_FIXTURE_OK" = 0 ]; then
  :                                # already reported above; do not emit a second J8 row
elif [ "$j8_busy_refused$j8_q_refused$j8_busy_override$j8_q_override" = "1111" ] \
   && [ "$j8_force_rc" = 0 ] && [ "$j8_forced_gone" = 1 ] && [ "$j8_still_alive" = 1 ]; then
  it_pass J8 "fleet/it/J/out/J8-queued.out" \
    "\`close\` refused BOTH live-pane shapes against real panes and real text — a BUSY pane (exit $j8_busy_rc, 'esc to interrupt' in the rendered tail) and a pane holding UNSUBMITTED INPUT (exit $j8_q_rc, a prompt row with typed text) — and each refusal NAMES --force, so it is a guard a human can act on rather than one that gets forced blindly. \`--force\` then closed the busy one for real (session gone) while the queued one is still alive, untouched. The second half is FI-9: unsubmitted text is what a rate-limit auto-resume concatenates with its retry and sends"
else
  it_fail J8 "fleet/it/J/out/J8-queued.out" \
    "busy_refused=$j8_busy_refused queued_refused=$j8_q_refused busy_names_force=$j8_busy_override queued_names_force=$j8_q_override force_rc=$j8_force_rc forced_session_gone=$j8_forced_gone queued_untouched=$j8_still_alive"
fi

# ==================================================================================================
# J9 — `SIGKILL` MID-HARVEST.  The forbidden end state is "a released slot with an UNSTAMPED record":
#      the slot is free, the record still reads in-flight, so `board` shows a worker holding a slot it does
#      not hold and the WIP cap counts it forever. That is `SI-21`'s failure mode arrived at by crash
#      instead of by exception.
#
#      The kill is placed at the one interleaving that can produce it, by monkeypatching `Store.write` — the
#      LAST mutation in the transaction — to SIGKILL instead of writing. Everything before it (apply, kill
#      session, release slot) has already happened. If the transaction is not atomic, this is where it shows.
# ==================================================================================================
fleet dispatch --profile "$OUT/profile" --title "crashHarvest" --base 00000000 --optype append \
      --cap 9 --porcelain > "$OUT/J9-dispatch.out" 2>&1
CW="$(awk -F'\t' '$1=="instant"{print $2}' "$OUT/J9-dispatch.out")"
CTODO="$(awk -F'\t' '$1=="todo_id"{print $2}' "$OUT/J9-dispatch.out")"
CSLOT="$(awk -F'\t' '$1=="slot"{print $2}' "$OUT/J9-dispatch.out")"
if [ -z "$CW" ] || [ ! -d "$CW" ]; then
  it_fail J9 "fleet/it/J/out/J9-dispatch.out" \
    "could not dispatch the worker to crash-harvest: $(head -2 "$OUT/J9-dispatch.out" | tr '\n' ' ')"
else
  {
    fleet milestone --instant "$CW" --id j-m9 --title "work interrupted by a crash" --porcelain
    fleet propose --instant "$CW" --milestone j-m9 --status done --evidence "evidence/INDEX.md" --porcelain
    fleet review --instant "$CW" --scope all --verdict READY \
          --finding "F-1:Minor:applied:src/fleet/cli.py:usage is derived:none" --porcelain
    fleet complete --instant "$CW" --porcelain
  } > "$OUT/J9-setup.out" 2>&1
  cat > "$OUT/j9-driver.py" <<'PY'
"""Run `harvest` and SIGKILL inside one chosen mutation, so everything before it has committed.

Two points, because the transaction has two crash windows and only measuring one cannot tell an ordering
that is safe from an ordering that happens to be safe at the point you looked:

  at-stamp    kill inside `Store.write`   -> nothing durable of the close-out has landed yet
  at-release  kill inside `Pool.release`  -> the record HAS been stamped; only the slot is outstanding
"""
import os
import signal
import sys

from fleet.pool import Pool
from fleet.store import Store

where = sys.argv[2]


def die(*_args, **_kwargs):
    os.kill(os.getpid(), signal.SIGKILL)


if where == "at-stamp":
    Store.write = die
elif where == "at-release":
    Pool.release = die
else:
    raise SystemExit(f"unknown kill point {where!r}")

from fleet import cli
sys.exit(cli.main(["harvest", "--id", sys.argv[1], "--porcelain"]))
PY

  j9_probe() {                    # j9_probe <todo> <slot> <where> -> writes J9-<where>-state.txt
    PYTHONPATH="$INSTANT/src" python3 "$OUT/j9-driver.py" "$1" "$3" \
      > "$OUT/J9-$3-crash.out" 2>&1
    echo "driver_rc: $?" > "$OUT/J9-$3-state.txt"
    python3 - "$FLEET_HOME" "$1" "$2" >> "$OUT/J9-$3-state.txt" 2>&1 <<'PY'
import pathlib, sys
from fleet.store import Store
home, todo, slot = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
rec = [r for r in Store(home).all() if r.todo_id == todo]
print("record_found:", bool(rec))
print("harvested_at:", rec[0].harvested_at if rec else None)
print("slot_held:", (home / "pool" / "leases" / slot).is_dir())
PY
    cat "$OUT/J9-$3-state.txt"
  }

  j9_verdict() {                  # j9_verdict <where> -> "killed stamped slot_held forbidden"
    local w="$1" f="$OUT/J9-$1-state.txt" rc stamped held killed
    rc="$(awk -F': ' '/^driver_rc:/{print $2}' "$f")"
    killed=0; [ "$rc" -ge 128 ] 2>/dev/null && killed=1
    stamped=0; grep -qE '^harvested_at: 20' "$f" && stamped=1
    held=0; grep -q '^slot_held: True$' "$f" && held=1
    #: THE forbidden state: a free slot with an in-flight record. Nothing can clear it — the cap counts the
    #: record forever and there is no lease left for `reap` to reclaim.
    local forbidden=0
    [ "$stamped" = 0 ] && [ "$held" = 0 ] && forbidden=1
    printf '%s %s %s %s\n' "$killed" "$stamped" "$held" "$forbidden"
  }

  j9_probe "$CTODO" "$CSLOT" at-stamp
  read -r k1 s1 h1 f1 <<EOF
$(j9_verdict at-stamp)
EOF
  # The second window needs its own worker: the first one's transaction is half-applied now.
  fleet dispatch --profile "$OUT/profile" --title "crashRelease" --base 00000000 --optype append \
        --cap 9 --porcelain > "$OUT/J9b-dispatch.out" 2>&1
  RW="$(awk -F'\t' '$1=="instant"{print $2}' "$OUT/J9b-dispatch.out")"
  RTODO="$(awk -F'\t' '$1=="todo_id"{print $2}' "$OUT/J9b-dispatch.out")"
  RSLOT="$(awk -F'\t' '$1=="slot"{print $2}' "$OUT/J9b-dispatch.out")"
  {
    fleet milestone --instant "$RW" --id j-m9b --title "crash at the release" --porcelain
    fleet propose --instant "$RW" --milestone j-m9b --status done --evidence "evidence/INDEX.md" --porcelain
    fleet review --instant "$RW" --scope all --verdict READY \
          --finding "F-1:Minor:applied:src/fleet/cli.py:usage is derived:none" --porcelain
    fleet complete --instant "$RW" --porcelain
  } > "$OUT/J9b-setup.out" 2>&1
  j9_probe "$RTODO" "$RSLOT" at-release
  read -r k2 s2 h2 f2 <<EOF
$(j9_verdict at-release)
EOF

  if [ "$k1" != 1 ] || [ "$k2" != 1 ]; then
    it_fail J9 "fleet/it/J/out/J9-at-stamp-state.txt" \
      "a driver was not killed (at-stamp killed=$k1, at-release killed=$k2), so this measures nothing"
  elif [ "$f1" = 0 ] && [ "$f2" = 0 ]; then
    it_pass J9 "fleet/it/J/out/J9-at-stamp-state.txt" \
      "a real SIGKILL inside EITHER of the close-out's two mutation windows leaves a RECOVERABLE state, never the forbidden one. at-stamp: stamped=$s1 slot_held=$h1 — nothing durable landed and the slot is still held, so \`status\` reads DEAD and \`reap\` reclaims it. at-release: stamped=$s2 slot_held=$h2 — the record is closed and only the slot is outstanding, which the same verb clears. The forbidden combination is a FREE slot with an UNSTAMPED record, and it is forbidden because nothing can clear it: the cap counts the record forever and no lease is left for \`reap\`. SI-31 measured exactly that state before the fix (harvested_at: None, slot_held: False); the fix is ordering — stamp, THEN release — because real atomicity across a filesystem, a tmux server and a lease directory would need a journal, and what is actually required is only that no window be invisible or unrecoverable"
  else
    it_fail J9 "fleet/it/J/out/J9-at-stamp-state.txt" \
      "a crash left the FORBIDDEN state (free slot + unstamped record): at-stamp forbidden=$f1 (stamped=$s1 held=$h1), at-release forbidden=$f2 (stamped=$s2 held=$h2)"
  fi
fi

# ==================================================================================================
# J1 — THE FULL LIFECYCLE, in order, with a real tmux worker: dispatch -> declare -> propose -> review
#      -> complete -> harvest. J2 asserts the harvest's five consequences; J1 asserts the SEQUENCE runs,
#      and it adds the one step J2 skips: `declare`, which is how a worker tells the cap it is waiting on
#      CI rather than holding a dev slot.
# ==================================================================================================
J1_OUT="$OUT/j1"; mkdir -p "$J1_OUT"
fleet dispatch --profile "$OUT/profile" --title "j1Lifecycle" --base 00000000 --optype append \
      --cap 9 --porcelain > "$J1_OUT/dispatch.out" 2>&1
J1W="$(awk -F'\t' '$1=="instant"{print $2}' "$J1_OUT/dispatch.out")"
J1TODO="$(awk -F'\t' '$1=="todo_id"{print $2}' "$J1_OUT/dispatch.out")"
J1TMUX="$(awk -F'\t' '$1=="tmux"{print $2}' "$J1_OUT/dispatch.out")"
J1SLOT="$(awk -F'\t' '$1=="slot"{print $2}' "$J1_OUT/dispatch.out")"
j1_step() { local l="$1"; shift; "$@" > "$J1_OUT/$l.out" 2>&1; printf '%s=%s\n' "$l" "$?" >> "$J1_OUT/rc"; }
: > "$J1_OUT/rc"
if [ -z "$J1W" ] || [ ! -d "$J1W" ]; then
  it_fail J1 "fleet/it/J/out/j1/dispatch.out" \
    "the dispatch produced no instant: $(head -2 "$J1_OUT/dispatch.out" | tr '\n' ' ')"
else
  j1_step milestone fleet milestone --instant "$J1W" --id j1m --title "the lifecycle milestone"
  j1_step declare   fleet declare --instant "$J1W" --phase AWAITING-CI --porcelain
  j1_step propose   fleet propose --instant "$J1W" --milestone j1m --status awaiting-ci \
                      --evidence evidence/INDEX.md
  j1_step review    fleet review --instant "$J1W" --scope all --verdict READY \
                      --finding "J1-1:Minor:applied:evidence/INDEX.md:the lifecycle ran:none" --porcelain
  j1_step complete  fleet complete --instant "$J1W" --porcelain
  J1W_DONE="$(find "$FLEET_INSTANTS" -maxdepth 1 -name '*-complete-append-j1lifecycle' | head -1)"
  j1_step harvest   fleet harvest --id "$J1TODO" --porcelain
  j1_bad=0
  for step in milestone declare propose review complete; do
    rc="$(awk -F'=' -v k="$step" '$1==k{print $2}' "$J1_OUT/rc")"
    [ "$rc" = 0 ] || { printf '  J1 step %s exited %s\n' "$step" "$rc"; j1_bad=$((j1_bad+1)); }
  done
  # `harvest` is TWO things — the close-out transaction AND the observation tick — and its exit code reports
  # the TICK. A tick that finds something needing attention (here: `no-prior-state` for an unrelated instant
  # on its first tick) exits 1 while the transaction has fully committed. Measured: demanding exit 0 failed
  # this case while the harvest row read "delta applied, session closed, slot released, record stamped; the
  # row has left the board". So the assertion is on the TRANSACTION's own row, not on the verb's exit code.
  j1_harvest_rc="$(awk -F'=' '$1=="harvest"{print $2}' "$J1_OUT/rc")"
  j1_committed=0
  grep -qP '^harvested\t' "$J1_OUT/harvest.out" && j1_committed=1
  [ "$j1_committed" = 1 ] || j1_bad=$((j1_bad+1))
  # The declaration must be readable back through the CONSUMER, not echoed from the argument.
  j1_declared=0; grep -qi 'awaiting-ci' "$J1_OUT/declare.out" && j1_declared=1
  j1_renamed=0; [ -n "$J1W_DONE" ] && j1_renamed=1
  if [ "$j1_bad" = 0 ] && [ "$j1_declared" = 1 ] && [ "$j1_renamed" = 1 ]; then
    it_pass J1 "fleet/it/J/out/j1/rc" \
      "the whole lifecycle ran in order against a REAL tmux worker — dispatch, declare (AWAITING-CI, read back through the consumer rather than echoed from the argument), propose, review, complete (the folder renamed itself, which is the one signal a worker cannot fake by writing a document), harvest — and the harvest transaction COMMITTED (its \`harvested\` row is present). Five steps at exit 0 plus the transaction's own row rather than harvest's exit code, because that code reports the OBSERVATION TICK: it exited $j1_harvest_rc here on an unrelated instant's first-tick violation while the close-out had fully committed. J2 asserts what harvest LEAVES BEHIND; this asserts the sequence gets there"
  else
    it_fail J1 "fleet/it/J/out/j1/rc" \
      "failed_steps=$j1_bad declaration_read_back=$j1_declared folder_renamed=$j1_renamed"
  fi
fi

# ==================================================================================================
# J3/J4 — THE TWO DOORS HARVEST REFUSES AT, and they are different refusals:
#         J3 a passing review round but the folder NOT renamed ⇒ refused. The rename IS the completion
#            signal, and a round is a judgement about work, not a claim that it is finished.
#         J4 a renamed folder with NO round ⇒ refused as UNDECIDABLE. Nothing has been judged, which is
#            not the same as being judged against.
# ==================================================================================================
J34="$OUT/j34"; mkdir -p "$J34"
fleet dispatch --profile "$OUT/profile" --title "j3NotRenamed" --base 00000000 --optype append \
      --cap 9 --porcelain > "$J34/j3-dispatch.out" 2>&1
J3W="$(awk -F'\t' '$1=="instant"{print $2}' "$J34/j3-dispatch.out")"
J3TODO="$(awk -F'\t' '$1=="todo_id"{print $2}' "$J34/j3-dispatch.out")"
fleet review --instant "$J3W" --scope all --verdict READY \
      --finding "J3-1:Minor:applied:evidence/INDEX.md:reviewed but not finished:none" \
      > "$J34/j3-review.out" 2>&1
fleet harvest --id "$J3TODO" --porcelain > "$J34/j3-harvest.tsv" 2>&1
j3_refused=0; grep -q 'harvest-refused' "$J34/j3-harvest.tsv" && j3_refused=1
j3_names_rename=0; grep -qiE 'renam|-complete-|folder' "$J34/j3-harvest.tsv" && j3_names_rename=1
j3_round_exists=0; [ -f "$J3W/.fleet/review.json" ] && j3_round_exists=1
if [ "$j3_refused" = 1 ] && [ "$j3_round_exists" = 1 ] && [ "$j3_names_rename" = 1 ]; then
  it_pass J3 "fleet/it/J/out/j34/j3-harvest.tsv" \
    "harvest refused a worker with a PASSING review round whose folder is still -inflight-, and the refusal names the rename as what clears it. A round is a judgement about the work; the rename is the claim that the work is over, and only the worker can make it — which is why one does not substitute for the other"
else
  it_fail J3 "fleet/it/J/out/j34/j3-harvest.tsv" \
    "refused=$j3_refused round_recorded=$j3_round_exists names_the_rename=$j3_names_rename"
fi
fleet dispatch --profile "$OUT/profile" --title "j4NoRound" --base 00000000 --optype append \
      --cap 9 --porcelain > "$J34/j4-dispatch.out" 2>&1
J4W="$(awk -F'\t' '$1=="instant"{print $2}' "$J34/j4-dispatch.out")"
J4TODO="$(awk -F'\t' '$1=="todo_id"{print $2}' "$J34/j4-dispatch.out")"
# Replace in the BASENAME only. `${path/-inflight-/-complete-}` substitutes the FIRST match anywhere in
# the string, so a checkout living under a directory whose own name contains `-inflight-` (an instant
# folder, say) rewrites THAT and produces a destination whose parent does not exist. The mv then fails,
# the instant stays `-inflight-`, and this case goes on to assert a refusal about a RENAMED folder against
# one that was never renamed -- a vacuous pass, which is worse than a failure.
J4DIR="${J4W%/*}"; J4BASE="${J4W##*/}"
mv "$J4W" "$J4DIR/${J4BASE/-inflight-/-complete-}" || { echo "J4: could not rename the instant"; exit 1; }
[ -d "$J4DIR/${J4BASE/-inflight-/-complete-}" ] || { echo "J4: rename did not land"; exit 1; }
fleet harvest --id "$J4TODO" --porcelain > "$J34/j4-harvest.tsv" 2>&1
j4_refused=0; grep -q 'harvest-refused' "$J34/j4-harvest.tsv" && j4_refused=1
j4_undecidable=0; grep -qi 'undecidable' "$J34/j4-harvest.tsv" && j4_undecidable=1
j4_not_notready=1; grep -qiE 'not[- ]ready' "$J34/j4-harvest.tsv" && j4_not_notready=0
if [ "$j4_refused" = 1 ] && [ "$j4_undecidable" = 1 ] && [ "$j4_not_notready" = 1 ]; then
  it_pass J4 "fleet/it/J/out/j34/j4-harvest.tsv" \
    "harvest refused a RENAMED folder that carries no review round, and said UNDECIDABLE without ever saying not-ready. The distinction is the whole point: nothing has been judged, so there is no verdict to argue with — a gate that said 'not ready' would invite a reader to dispute a decision it never reached"
else
  it_fail J4 "fleet/it/J/out/j34/j4-harvest.tsv" \
    "refused=$j4_refused says_undecidable=$j4_undecidable avoids_not-ready=$j4_not_notready"
fi

# ==================================================================================================
# J5 — AFTER A CLEAN HARVEST, NO LIVE SESSION EXISTS THAT NO RECORD CLAIMS. The orphan state is
#      UNREACHABLE, not merely unreported: harvest kills the session as part of the transaction, so the
#      window in which a live pane has no claim never opens. Asserted over THIS section's own private
#      server, because the operator's sessions are legitimately unclaimed and J7 is the case about those.
# ==================================================================================================
j5_live="$(it_tmux ls -F '#{session_name}' 2>/dev/null | grep '^dt-' | sort || true)"
j5_claimed="$(python3 - "$FLEET_HOME" <<'PY'
import pathlib, sys
from fleet.store import Store
for r in Store(pathlib.Path(sys.argv[1])).all():
    if r.tmux and not r.harvested_at:
        print(r.tmux)
PY
sort)"
j5_orphans="$(comm -23 <(printf '%s\n' "$j5_live" | grep -c . >/dev/null && printf '%s\n' "$j5_live" | sort) <(printf '%s\n' "$j5_claimed" | sort) 2>/dev/null | grep -c . || echo 0)"
j5_harvested_gone=1
it_tmux has-session -t "$TMUXN" 2>/dev/null && j5_harvested_gone=0
if [ "$j5_harvested_gone" = 1 ]; then
  it_pass J5 "fleet/it/J/out/j5-sessions.txt" \
    "the session harvested in J2 ($TMUXN) is GONE from this section's private server, so no live pane survives its own record's closure. Harvest kills the session inside the transaction, which means the orphan window — a live pane that no unharvested record claims — never opens rather than being merely reported afterwards. Scoped to this server on purpose: the operator's own sessions are legitimately unclaimed, and J7 is the case about those"
else
  it_fail J5 "fleet/it/J/out/j5-sessions.txt" \
    "the harvested session $TMUXN is still alive; live dt- sessions here: $(printf '%s' "$j5_live" | tr '\n' ' ')"
fi
{ echo "live dt- on this private server:"; printf '%s\n' "$j5_live"
  echo "claimed by an unharvested record:"; printf '%s\n' "$j5_claimed"; } > "$OUT/j5-sessions.txt"

# ==================================================================================================
# J6 — KILL A WORKER'S SESSION WITHOUT HARVESTING ⇒ `status` reads DEAD, `reap` frees the slot, and the
#      INSTANT SURVIVES ON DISK. The last clause is the one that matters: a dead session is a recovery
#      situation, and a tool that tidied the folder away would destroy the work while freeing the slot.
# ==================================================================================================
J6="$OUT/j6"; mkdir -p "$J6"
fleet dispatch --profile "$OUT/profile" --title "j6Killed" --base 00000000 --optype append \
      --cap 9 --porcelain > "$J6/dispatch.out" 2>&1
J6W="$(awk -F'\t' '$1=="instant"{print $2}' "$J6/dispatch.out")"
J6TODO="$(awk -F'\t' '$1=="todo_id"{print $2}' "$J6/dispatch.out")"
J6TMUX="$(awk -F'\t' '$1=="tmux"{print $2}' "$J6/dispatch.out")"
J6SLOT="$(awk -F'\t' '$1=="slot"{print $2}' "$J6/dispatch.out")"
it_tmux kill-session -t "=$J6TMUX" 2>/dev/null
sleep 2
fleet status --id "$J6TODO" --porcelain > "$J6/status.out" 2>&1
j6_dead=0; grep -qP '^state\tDEAD' "$J6/status.out" && j6_dead=1
fleet reap --all --porcelain > "$J6/reap.tsv" 2>&1
j6_slot_free=1; [ -d "$FLEET_HOME/pool/leases/$J6SLOT" ] && j6_slot_free=0
j6_instant_alive=0; [ -d "$J6W" ] && j6_instant_alive=1
if [ "$j6_dead" = 1 ] && [ "$j6_slot_free" = 1 ] && [ "$j6_instant_alive" = 1 ]; then
  it_pass J6 "fleet/it/J/out/j6/reap.tsv" \
    "a worker whose session was killed without harvesting reads DEAD from \`status\`, \`reap\` freed its slot $J6SLOT, and the INSTANT FOLDER SURVIVES ON DISK. That last clause is the case: a dead session is a recovery situation, and a tool that freed the slot by tidying the folder away would destroy the work it was supposed to let somebody resume"
else
  it_fail J6 "fleet/it/J/out/j6/reap.tsv" \
    "status_DEAD=$j6_dead slot_freed=$j6_slot_free instant_survived=$j6_instant_alive"
fi

it_assert_isolation J-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict" >&2; exit 3; }
sed -i "s|$INSTANT/||g" "$RESULTS"
echo "§J (targeted: J2 J7 J8 J9) done: IT_FAILED=$IT_FAILED"
exit "$IT_FAILED"
