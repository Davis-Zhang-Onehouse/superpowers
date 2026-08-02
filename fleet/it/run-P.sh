#!/usr/bin/env bash
# §P — AC-11: THE REAL DISPATCH. A real `claude`, reading the real seed, following the new skills.
#
# Everything else in this harness substitutes for the worker: `bin/claude` is a shell stub, and every other
# section asserts a property of the mechanism with nothing intelligent on the other end. This is the one case
# where the thing being tested is whether a MODEL can follow the contract — and it is the only case that can
# answer it, because V1/V2/V3 prove the commands exist, the refusals are real and the sequence runs, and none
# of them proves the instructions are followable.
#
# TWO deliberate choices, both stated because both narrow what this proves:
#
#  1. A PRIVATE tmux socket. The dispatch is real in every way that matters — a real `claude` binary, a real
#     session, a real seed, real work — and the socket is orthogonal to all of it. `SD-1` made the server a
#     parameter precisely so this is possible, and running it on the default server would put the operator's
#     coordinator at risk for no gain in coverage.
#
#  2. A wrapper named `claude` on PATH that execs the real binary with the seed as its initial prompt.
#     `fleet dispatch` runs `sessions.start(tmux, lease.path, "claude")` — cwd and nothing else. NOTHING in
#     `fleet` delivers the seed to the worker: `dispatch` writes `.fleet/seed.txt` into the INSTANT and starts
#     the process in the SLOT. Seed delivery is the caller's job (which is what `pane-guard` exists to gate),
#     and this section does it through argv rather than send-keys so the measurement does not depend on
#     keystroke timing. `pane-guard` is asserted separately, against the live pane.
#
# Run: bash fleet/it/run-P.sh          Budget: one real claude, one task, polled to completion.
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
it_own_cases 'P[0-9]+[a-z]?|ISOLATION-P-(enter|leave)'

it_section P
it_fresh_store
OUT="$EV/out"; rm -rf "$OUT"; mkdir -p "$OUT"
export FLEET_INSTANTS="$EV/instants"; rm -rf "$FLEET_INSTANTS"; mkdir -p "$FLEET_INSTANTS"

bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2

REAL_CLAUDE="${P_REAL_CLAUDE:-/home/ubuntu/.local/bin/claude}"
P_TIMEOUT="${P_TIMEOUT:-900}"

cleanup_P() {
  it_cleanup_tmux
  tmux -L "$IT_TMUX_SOCKET" kill-server 2>/dev/null
}
trap cleanup_P EXIT

if [ ! -x "$REAL_CLAUDE" ]; then
  it_skip P1 "" "no real claude at $REAL_CLAUDE, so the one case that measures followability cannot run"
  it_assert_isolation P-leave
  echo "§P skipped"; exit 0
fi

# ---- the slot: a real git repo, with a lineage base on a DIVERGED sibling --------------------------
# Same shape as §LB, because the worker must have something real to reposition onto and the gate on
# `propose --status done` must have teeth. The worker lands here, at the golden, exactly as ws3 did.
SLOT="$OUT/slot"; mkdir -p "$SLOT/alpha"
(
  cd "$SLOT/alpha" && git init -q . && git config user.email p@fleet && git config user.name p
  echo base > f.txt && git add -A && git commit -q -m "A: common ancestor"
  git branch -q ancestor
  git checkout -q -b sibling && echo siblingwork > f.txt && git commit -qam "L: the sibling's tip"
  git checkout -q ancestor && git checkout -q -b goldenbranch
  echo goldenwork > g.txt && git add -A && git commit -q -m "G: the golden prebuild"
) >/dev/null 2>&1
L="$(git -C "$SLOT/alpha" rev-parse sibling)"

# ---- the coordinator, and one milestone for the worker --------------------------------------------
COORD="$(fleet init --base 00000000 --name pCoord --porcelain | awk -F'\t' '$1=="path"{print $2}')"
fleet milestone --instant "$COORD" --id p1 --title "prove the worker contract end to end" \
      > "$OUT/P-milestone.out" 2>&1
fleet set-golden --path "$SLOT" > "$OUT/P-setup.out" 2>&1
fleet enroll --slot "$SLOT" >> "$OUT/P-setup.out" 2>&1

# ---- the profile: the shipped worker template, plus THIS run's task ---------------------------------
PROFILE="$OUT/profile"
cp -r "$IT_ROOT/../../skills/using-fleet/profiles/worker" "$PROFILE"
cat >> "$PROFILE/seed.txt" <<'TASK'

=== YOUR TASK (this is the whole job; it is small on purpose) ===

You are being used to test the skills you were just told to load. Do the job, and report honestly on the
instructions themselves — including anything that was wrong, missing, or that you could not follow.

1. Orient. Run the `fleet brief` command above and read every row.
2. Run `fleet base-check --id <your todo id>`. The todo id is in your brief's output.
3. You are NOT on your lineage base. Do what your seed's POSITION YOUR WORKSPACE section tells you, then
   run `fleet base-check` again and confirm it now says you are at the base.
4. Write a report to "$INSTANT/evidence/P-worker-report.md" answering, in your own words:
     - what `fleet brief` told you, and whether the `destination` row was useful
     - what `base-check` said before and after you repositioned
     - anything in the seed or in the working-as-a-dispatched-instant skill that was WRONG, missing,
       ambiguous, or that you could not do as written. Be specific and be blunt: this is the point of the
       exercise, and "it was all fine" is only useful if it is true.
4b. Also write, in that report, whether `propose --status done` would have been REFUSED had you not
    repositioned — and say how you know (did you try it? did the brief tell you? did you read it somewhere?).
5. Record a review round:
     fleet review --instant "$INSTANT" --scope all --verdict READY \
       --finding "P-1:Minor:applied:evidence/P-worker-report.md:the report is written:none"
6. Report done, citing your report as evidence:
     fleet propose --milestone p1 --status done --evidence evidence/P-worker-report.md
7. Rename yourself complete:  fleet complete --instant "$INSTANT"
8. Then STOP. Do not harvest yourself, do not touch any other instant, do not commit or push anything, and
   do not leave this slot or your instant folder.

You have one job and a time budget. Work directly; do not ask for confirmation.
TASK

# ---- the launcher: the real binary, the seed as its prompt ------------------------------------------
mkdir -p "$OUT/bin"
cat > "$OUT/bin/claude" <<WRAP
#!/usr/bin/env bash
# The REAL claude, launched with this instant's seed as its initial prompt. \`fleet dispatch\` passes cwd and
# nothing else, so without this the worker starts with no instruction at all.
#
# It WAITS for the seed file, and that is not defensive padding — it is a real ordering problem. \`dispatch\`
# renders the seed INTO the instant and starts this session as part of the same call, so the caller cannot
# write the file until dispatch has returned, by which time this wrapper has already exec'd. The first run of
# §P lost exactly that race: claude came up with an EMPTY prompt and sat idle at it until the poll gave up.
for _ in \$(seq 1 120); do
  [ -s "$OUT/seed-to-send.txt" ] && break
  sleep 1
done
if [ ! -s "$OUT/seed-to-send.txt" ]; then
  echo "no seed arrived within 120s — refusing to start with an empty prompt" >&2
  exec sleep 300
fi
exec "$REAL_CLAUDE" --permission-mode auto "\$(cat "$OUT/seed-to-send.txt")"
WRAP
chmod +x "$OUT/bin/claude"
PATH="$OUT/bin:$PATH"; export PATH

# ---- dispatch, for real ----------------------------------------------------------------------------
# The seed is rendered by `dispatch` INTO the instant, so it cannot be read before the dispatch exists — and
# the session starts inside that same call. The wrapper therefore WAITS for this file rather than assuming it
# is already there (see the wrapper above; the first run of §P lost that race and the worker sat at an empty
# prompt). Truncated here so a stale seed from a previous run cannot be picked up.
: > "$OUT/seed-to-send.txt"
fleet dispatch --profile "$PROFILE" --title "pRealWorker" --base 00000000 --optype append \
      --from "$COORD" --milestone p1 --lineage-base "alpha=$L" --lineage-mode code \
      --porcelain > "$OUT/P-dispatch.out" 2>&1
P_RC=$?
W="$(awk -F'\t' '$1=="instant"{print $2}' "$OUT/P-dispatch.out")"
TODO="$(awk -F'\t' '$1=="todo_id"{print $2}' "$OUT/P-dispatch.out")"
TMUXN="$(awk -F'\t' '$1=="tmux"{print $2}' "$OUT/P-dispatch.out")"

if [ "$P_RC" != 0 ] || [ -z "$W" ] || [ ! -d "$W" ]; then
  it_fail P1 "fleet/it/P/out/P-dispatch.out" \
    "the real dispatch failed (exit $P_RC): $(head -3 "$OUT/P-dispatch.out" | tr '\n' ' ')"
  it_assert_isolation P-leave
  echo "§P done: IT_FAILED=1"; exit 1
fi

# The seed the worker must actually receive: what dispatch rendered, plus the instant path it needs.
{ printf 'Your instant folder is %s and your leased slot is %s (your cwd).\n\n' "$W" "$SLOT"
  cat "$W/.fleet/seed.txt"; } > "$OUT/seed-to-send.txt"
mkdir -p "$W/evidence"

# ---- P1: the pane is live and running the real claude ----------------------------------------------
sleep 20
p1_alive=0; it_tmux has-session -t "=$TMUXN" 2>/dev/null && p1_alive=1
# `capture-pane -t` takes a PANE target: the bare session name resolves to its active pane, while `=name` is
# the session-EXACT form and does not. The first version used `=` and captured "can't find pane".
it_tmux capture-pane -p -t "$TMUXN" > "$OUT/P1-pane.txt" 2>&1 || true
# Whether the pane holds a real claude is asked of `pane-guard`, not of a grep for glyphs. The product already
# owns that judgement, its answer is the contract an external monitor branches on, and a homemade heuristic is
# a second derivation that can disagree — which it did: the grep said no while pane-guard said 0 (safe).
fleet pane-guard --pane "$TMUXN" > "$OUT/P1-guard.out" 2>&1
p1_guard=$?
p1_is_claude=0; case "$p1_guard" in 0|10|11) p1_is_claude=1 ;; esac
P_PID="$(it_tmux list-panes -t "$TMUXN" -F '#{pane_pid}' 2>/dev/null | head -1)"
if [ "$p1_alive" = 1 ] && [ "$p1_is_claude" = 1 ]; then
  it_pass P1 "fleet/it/P/out/P1-pane.txt" \
    "a REAL dispatch produced a live session $TMUXN (pane pid $P_PID), and \`pane-guard\` classifies it as $p1_guard — one of 0/10/11, all of which mean 'a claude pane', rather than 12 not-claude or 13 unknown. Asked of the product rather than of a grep for glyphs, because pane-guard already owns that judgement and a homemade heuristic is a second derivation that can disagree (it did: the grep said no while pane-guard said safe). Everything else in this harness substitutes a stub for the worker; this is the one case where the thing on the other end is a model"
else
  it_fail P1 "fleet/it/P/out/P1-pane.txt" \
    "the pane is not a live claude: alive=$p1_alive pane-guard=$p1_guard (12=not-claude, 13=unknown)"
fi

# ---- P2: pane-guard answers about a REAL claude pane ------------------------------------------------
# The send contract, against a live model rather than a fixture. Read-only: it captures and classifies.
fleet pane-guard --pane "$TMUXN" > "$OUT/P2-guard.out" 2>&1
p2_rc=$?
case "$p2_rc" in
  0|10|11) it_pass P2 "fleet/it/P/out/P2-guard.out" \
      "pane-guard classified a REAL claude pane as $p2_rc (0 safe / 10 queued / 11 mid-turn) rather than 12 not-claude or 13 unknown — so the contract an external monitor branches on before any send-keys works against a live model, not only against the stub §D uses" ;;
  *) it_fail P2 "fleet/it/P/out/P2-guard.out" \
      "pane-guard returned $p2_rc against a real claude pane (12=not-claude, 13=unknown both mean it could not see it)" ;;
esac

# ---- poll for the worker to finish its contract ------------------------------------------------------
deadline=$(( $(date +%s) + P_TIMEOUT ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  done_folder="$(find "$FLEET_INSTANTS" -maxdepth 1 -name '*-complete-append-prealworker' | head -1)"
  [ -n "$done_folder" ] && break
  sleep 15
done
W_FINAL="${done_folder:-$W}"
it_tmux capture-pane -p -t "=$TMUXN" > "$OUT/P-pane-final.txt" 2>&1 || true

# ---- P3: the worker followed the contract ------------------------------------------------------------
p3_report=0; [ -f "$W_FINAL/evidence/P-worker-report.md" ] && p3_report=1
p3_renamed=0; case "$(basename "$W_FINAL")" in *-complete-append-*) p3_renamed=1;; esac
p3_review=0; [ -f "$W_FINAL/.fleet/review.json" ] && p3_review=1
p3_proposed=0
python3 - "$COORD" > "$OUT/P3-inbox.txt" 2>&1 <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1]) / ".fleet" / "proposals.json"
data = json.loads(p.read_text()) if p.is_file() else {"pending": [], "applied": []}
for key in ("pending", "applied"):
    for entry in data.get(key, []):
        print(f"{key} milestone={entry['milestone']} status={entry['status']} instant={entry['instant']} "
              f"evidence={entry['evidence']}")
PY
grep -q 'milestone=p1 status=done' "$OUT/P3-inbox.txt" && p3_proposed=1
if [ "$p3_report$p3_proposed$p3_review$p3_renamed" = "1111" ]; then
  it_pass P3 "fleet/it/P/out/P3-inbox.txt" \
    "a real claude followed the whole worker contract from the seed alone: it wrote its report, recorded a review round, proposed p1=done into the COORDINATOR's inbox with its evidence attached, and renamed its own folder -complete-. The gate on \`propose --status done\` means it could not have reported done without first repositioning onto the lineage base its seed named"
else
  it_fail P3 "fleet/it/P/out/P3-inbox.txt" \
    "the contract was not completed: report=$p3_report proposed=$p3_proposed review=$p3_review renamed=$p3_renamed (folder $(basename "$W_FINAL"))"
fi

# ---- P4: the coordinator closes the loop -------------------------------------------------------------
fleet apply --instant "$COORD" --milestone p1 --porcelain > "$OUT/P4-apply.out" 2>&1
p4_apply=$?
# `close` FIRST, and the reason is a refusal the first version of this case walked straight into: the worker's
# claude was still running with the slot as its cwd, and `harvest` refused to release it — *"slot 'slot' is
# held as cwd by live pid(s) N; releasing it would let a second worker be leased into a directory somebody is
# still in"*. That refusal is the pool protecting a live process and is exactly right; the sequence was wrong.
# `close` ends the session and stamps the record; `harvest` applies the delta and releases the lease. Two
# verbs because they are two decisions, and `close` does not do a neighbour's job.
# ...and `close` itself must WAIT for the turn to end. Measured: the worker had already renamed itself
# `-complete-`, and `close` still refused with exit 4 — *"mid-turn: dt-prealworker is still offering a way to
# interrupt, so closing it now ends a turn in progress and whatever that turn had not yet written down"*. The
# contract is `pane-guard`: 10 (queued-text) and 11 (mid-turn) mean WAIT; 0 (safe), 12 (not-claude) and 13
# (unknown-pane, i.e. it has already gone) mean the pane can be closed. Finishing the contract and finishing
# the TURN are different moments, and a coordinator that conflates them either forces a close or gets refused.
p4_guard=11
p4_waited=0
while [ "$p4_waited" -lt 40 ]; do
  fleet pane-guard --pane "$TMUXN" > "$OUT/P4-guard.out" 2>&1
  p4_guard=$?
  case "$p4_guard" in 10|11) : ;; *) break ;; esac
  sleep 15; p4_waited=$((p4_waited+1))
done
fleet close --id "$TODO" --porcelain > "$OUT/P4-close.out" 2>&1
p4_close=$?
# The pid needs a moment to actually leave the slot before the cwd-holder check can pass.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  [ -n "$P_PID" ] && kill -0 "$P_PID" 2>/dev/null || break
  sleep 2
done
p4_status="$(fleet roadmap --instant "$COORD" --porcelain 2>/dev/null | awk -F'\t' '$2=="p1"{print $3}' | head -1)"
fleet harvest --id "$TODO" --porcelain > "$OUT/P4-harvest.tsv" 2>&1
p4_slotfree=1; [ -d "$FLEET_HOME/pool/leases/$(basename "$SLOT")" ] && p4_slotfree=0
p4_offboard=1; fleet board --porcelain 2>/dev/null | grep -q "$TODO" && p4_offboard=0
p4_done=0
python3 - "$COORD" > "$OUT/P4-milestone.txt" 2>&1 <<'PY'
import pathlib, sys
from fleet.roadmap import Roadmap
m = Roadmap(pathlib.Path(sys.argv[1])).milestone("p1")
print("status:", m.status)
print("evidence:", m.evidence)
PY
grep -q '^status: done$' "$OUT/P4-milestone.txt" && p4_done=1
if [ "$p4_apply" = 0 ] && [ "$p4_close" = 0 ] && [ "$p4_done" = 1 ] && [ "$p4_slotfree" = 1 ] \
   && [ "$p4_offboard" = 1 ]; then
  it_pass P4 "fleet/it/P/out/P4-harvest.tsv" \
    "the coordinator closed the loop on real work: \`apply\` moved p1 to done carrying the worker's own evidence; \`pane-guard\` was polled until the pane left mid-turn (it reached $p4_guard) because \`close\` REFUSES a turn in progress even after the worker has renamed itself complete; then \`close\` ended the session and \`harvest\` released the slot so the row LEFT the board. AC-11 end to end — dispatch, a real model doing the job, propose, apply, wait, close, harvest"
else
  it_fail P4 "fleet/it/P/out/P4-harvest.tsv" \
    "apply_rc=$p4_apply close_rc=$p4_close milestone_done=$p4_done slot_free=$p4_slotfree off_board=$p4_offboard (status was '$p4_status')"
fi

it_assert_isolation P-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict" >&2; exit 3; }
sed -i "s|$INSTANT/||g" "$RESULTS"
echo "§P done: IT_FAILED=$IT_FAILED"
#: `II-11`. Was `exit "$IT_FAILED"` — a COUNT. `exit` truncates modulo 256, so a section with
#: exactly 256 failures reported SUCCESS, and one with 300 reported 44, a number meaning nothing
#: to any reader. An exit status is a one-byte verdict, not a tally: the count is already printed
#: on the line above and is in the register, which is where a consumer should read it anyway.
if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
exit 1
