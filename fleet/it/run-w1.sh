#!/usr/bin/env bash
# W-1 — prove the IT harness has a tmux server of its own.
#
# The claim is not "we passed -L". The claim is a pair of blindnesses, and each half is asserted from the
# side that matters:
#   (a) a session created through the PRODUCT lands on the private server and leaves the live server's
#       session set byte-identical — so an IT section cannot reach the operator's coordinator; and
#   (b) from the private server the live sessions are NOT VISIBLE — so an IT section cannot even read
#       them, which is what §E's server-wide isolation assertion was really asking about.
#
# Run: bash fleet/it/run-w1.sh
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
OUT="$IT_ROOT/W1/out"
mkdir -p "$OUT"

bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2

# This runner owns these rows. Re-running it replaces them rather than appending a second opinion.
it_own_cases 'W1-[0-9]+|W1-7-restored|ISOLATION-W1-(enter|leave)'

it_section W1
S="itfleet-W1-probe-$$"

# Whatever happens after this point, this section's sessions die on the private server only.
trap 'it_cleanup_tmux' EXIT

# ---------------------------------------------------------------------------------------------------
# The pre-image of the live server, captured through the same helper the isolation check uses.
it_live_tmux_sessions > "$OUT/live-sessions-before.txt"

# W1-1 · the product, handed nothing but FLEET_TMUX_SOCKET from the environment, starts a session.
#        A python subprocess rather than a direct tmux call, because the property under test is that the
#        PRODUCT's seam honours the variable — a harness that started the session itself would prove
#        nothing about `fleet`.
python3 - "$S" > "$OUT/W1-1-start.txt" 2>&1 <<'PY'
import sys
from pathlib import Path
from fleet.session import SessionLayer, default_probes
name = sys.argv[1]
layer = SessionLayer(default_probes())          # socket comes from FLEET_TMUX_SOCKET, unnamed here
layer.start(name, Path("/tmp"), "sleep 120")
print("alive:", layer.alive(name))
PY
if grep -q '^alive: True$' "$OUT/W1-1-start.txt"; then
  it_pass W1-1 "fleet/it/W1/out/W1-1-start.txt" \
    "the product started $S and reports it alive, with the server taken from FLEET_TMUX_SOCKET=$IT_TMUX_SOCKET and no socket named in the call"
else
  it_fail W1-1 "fleet/it/W1/out/W1-1-start.txt" \
    "the product did not bring up $S: $(head -3 "$OUT/W1-1-start.txt" | tr '\n' ' ')"
fi

# W1-2 · it is on the PRIVATE server.
it_tmux ls -F '#{session_name}' > "$OUT/W1-2-private-sessions.txt" 2>&1 || true
if grep -qx "$S" "$OUT/W1-2-private-sessions.txt"; then
  it_pass W1-2 "fleet/it/W1/out/W1-2-private-sessions.txt" \
    "$S is on socket $IT_TMUX_SOCKET"
else
  it_fail W1-2 "fleet/it/W1/out/W1-2-private-sessions.txt" \
    "$S is NOT on the private server — where did the product put it?"
fi

# W1-3 · the live server did not notice. THE case: it is the assertion §M failed and nothing caught.
it_live_tmux_sessions > "$OUT/live-sessions-after.txt"
if diff -q "$OUT/live-sessions-before.txt" "$OUT/live-sessions-after.txt" >/dev/null; then
  it_pass W1-3 "fleet/it/W1/out/live-sessions-after.txt" \
    "the live server's session set is byte-identical across a session being created and made live on the private one ($(grep -c . "$OUT/live-sessions-after.txt") sessions, incl. $(grep -c '^dt-' "$OUT/live-sessions-after.txt") dt-)"
else
  it_fail W1-3 "fleet/it/W1/out/live-sessions-after.txt" \
    "THE LIVE SERVER CHANGED: $(diff "$OUT/live-sessions-before.txt" "$OUT/live-sessions-after.txt" | grep '^[<>]' | tr '\n' ' ')"
fi

# W1-4 · and it is not visible from the private server either — the other direction, which is the one an
#        isolation assertion actually reads. A section that can SEE `dt-…` can also match it by prefix.
if [ "$(grep -c '^dt-' "$OUT/live-sessions-after.txt")" -eq 0 ]; then
  it_skip W1-4 "" "no dt- session exists on the live server right now, so this cell cannot distinguish blindness from an empty world"
elif grep -q '^dt-' "$OUT/W1-2-private-sessions.txt"; then
  it_fail W1-4 "fleet/it/W1/out/W1-2-private-sessions.txt" \
    "a dt- session is VISIBLE from the private server: $(grep '^dt-' "$OUT/W1-2-private-sessions.txt" | tr '\n' ' ')"
else
  it_pass W1-4 "fleet/it/W1/out/W1-2-private-sessions.txt" \
    "the $(grep -c '^dt-' "$OUT/live-sessions-after.txt") dt- session(s) live on the default server are NOT visible from socket $IT_TMUX_SOCKET"
fi

# W1-5 · the product is blind to them too, which is the claim a section relies on. `alive()` must say no
#        about a session that demonstrably exists — on the other server.
DT="$(grep '^dt-' "$OUT/live-sessions-after.txt" | head -1)"
if [ -z "$DT" ]; then
  it_skip W1-5 "" "no dt- session to be blind to"
else
  python3 - "$DT" > "$OUT/W1-5-blindness.txt" 2>&1 <<'PY'
from fleet.session import SessionLayer, default_probes
import sys
name = sys.argv[1]
print("private:", SessionLayer(default_probes()).alive(name))
print("default:", SessionLayer(default_probes(tmux_socket=None)).alive(name))
PY
  # READ-ONLY on both servers: `alive` is has-session, and the name is never passed to anything else.
  if grep -q '^private: False$' "$OUT/W1-5-blindness.txt" && grep -q '^default: True$' "$OUT/W1-5-blindness.txt"; then
    it_pass W1-5 "fleet/it/W1/out/W1-5-blindness.txt" \
      "the product reports $DT alive on the default server and NOT alive on $IT_TMUX_SOCKET — the same call, the same name, two servers, so the blindness is the socket's and not a lookup failure"
  else
    it_fail W1-5 "fleet/it/W1/out/W1-5-blindness.txt" \
      "want private:False + default:True, got: $(tr '\n' ' ' < "$OUT/W1-5-blindness.txt")"
  fi
fi

# W1-6 · cleanup kills this section's session by exact name on the private server, and nothing else.
it_cleanup_tmux
it_tmux ls -F '#{session_name}' > "$OUT/W1-6-private-after-cleanup.txt" 2>&1 || true
it_live_tmux_sessions > "$OUT/live-sessions-final.txt"
if grep -qx "$S" "$OUT/W1-6-private-after-cleanup.txt"; then
  it_fail W1-6 "fleet/it/W1/out/W1-6-private-after-cleanup.txt" "$S survived cleanup"
elif ! diff -q "$OUT/live-sessions-before.txt" "$OUT/live-sessions-final.txt" >/dev/null; then
  it_fail W1-6 "fleet/it/W1/out/live-sessions-final.txt" \
    "cleanup changed the LIVE server: $(diff "$OUT/live-sessions-before.txt" "$OUT/live-sessions-final.txt" | grep '^[<>]' | tr '\n' ' ')"
else
  it_pass W1-6 "fleet/it/W1/out/W1-6-private-after-cleanup.txt" \
    "cleanup removed $S from the private server by exact name and left the live server's session set byte-identical"
fi

# W1-8 · TWO IT GROUPS CANNOT SEE EACH OTHER. This is the half of W-1 that a single shared private socket
#        would leave exactly as broken, one layer down: §E's isolation assertion is server-WIDE, so with
#        §E and §M on one socket §E sees §M's sessions again and fails for the original reason. The socket
#        is therefore per section (`it_section`), and this case is what says so.
#
#        Two synthetic group sockets, so the assertion does not depend on which sections happen to exist.
GA="itfleet-W1-groupA-$$"; GB="itfleet-W1-groupB-$$"
tmux -L "$GA" new-session -d -s "session-of-A" "sleep 60" 2>/dev/null
tmux -L "$GB" new-session -d -s "session-of-B" "sleep 60" 2>/dev/null
tmux -L "$GA" ls -F '#{session_name}' > "$OUT/W1-8-groupA.txt" 2>&1 || true
tmux -L "$GB" ls -F '#{session_name}' > "$OUT/W1-8-groupB.txt" 2>&1 || true
if ! grep -qx 'session-of-A' "$OUT/W1-8-groupA.txt" || ! grep -qx 'session-of-B' "$OUT/W1-8-groupB.txt"; then
  it_fail W1-8 "fleet/it/W1/out/W1-8-groupA.txt" \
    "one of the two group servers never came up, so mutual invisibility would hold vacuously"
elif grep -qx 'session-of-B' "$OUT/W1-8-groupA.txt" || grep -qx 'session-of-A' "$OUT/W1-8-groupB.txt"; then
  it_fail W1-8 "fleet/it/W1/out/W1-8-groupA.txt" \
    "the two group servers can see each other's sessions — a section's server-wide isolation assertion would fail on the other section's work, which is SI-1's original symptom"
else
  it_pass W1-8 "fleet/it/W1/out/W1-8-groupA.txt" \
    "each group server shows ONLY its own session and neither shows the other's — both live, so the invisibility is measured and not vacuous. This is why the socket is per section rather than one shared 'itfleet'"
fi
tmux -L "$GA" kill-server 2>/dev/null; tmux -L "$GB" kill-server 2>/dev/null; true

# W1-7 · THE NEGATIVE CONTROL. Everything above would also pass if `it_assert_isolation` had been left as
#        the `grep -q '^dt-'` it was, because no dt- session was touched — which is exactly the hole
#        `SI-1` names. So the alarm is verified the way a mutation's killer is verified: by making it go
#        off. The baseline is doctored rather than the live server being written to; W1-2 already showed a
#        real new session appears in a `-F '#{session_name}'` listing, so the two together cover
#        "a session appearing on the live server is caught" with zero outward action.
#
#        RESULTS and the real baseline are swapped out for the duration, so the deliberate FAIL lands in a
#        scratch file and can never be mistaken for a verdict about this run.
(
  REAL_RESULTS="$RESULTS"
  RESULTS="$OUT/W1-7-negative-control.tsv"; : > "$RESULTS"
  cp "$LIVE_TMUX_SNAPSHOT" "$OUT/W1-7-baseline-real.txt"
  # The doctored baseline goes in a file of its OWN and `LIVE_TMUX_SNAPSHOT` is REPOINTED at it for the
  # duration. The first version overwrote the real path in place and restored it after — correct in
  # isolation, but a concurrent runner reading the baseline inside that window would have compared the live
  # server against a fiction. Found by §A's review of this file; the window was small and real.
  { cat "$OUT/W1-7-baseline-real.txt"; echo "itfleet-W1-a-session-that-does-not-exist"; } | sort \
    > "$OUT/W1-7-baseline-doctored.txt"
  LIVE_TMUX_SNAPSHOT="$OUT/W1-7-baseline-doctored.txt"
  it_assert_isolation W1-7-injected >/dev/null 2>&1
  RESULTS="$REAL_RESULTS"
  if grep -q '^ISOLATION-W1-7-injected	FAIL' "$OUT/W1-7-negative-control.tsv"; then
    it_pass W1-7 "fleet/it/W1/out/W1-7-negative-control.tsv" \
      "negative control: a live session set differing by ONE non-dt- name is reported FAIL — so W1-3 and W1-6 are assertions and not decoration. The pre-SI-1 check would have passed this, because nothing dt- moved"
  else
    it_fail W1-7 "fleet/it/W1/out/W1-7-negative-control.tsv" \
      "THE ALARM DOES NOT GO OFF: a doctored baseline produced $(cut -f1,2 "$OUT/W1-7-negative-control.tsv" | tr '\n' ' ') — every isolation PASS in this file is unfalsifiable"
  fi
)
# The real baseline must be untouched. Now a stronger claim than "restored": the control never wrote it at
# all, because it ran against a repointed copy inside a subshell. Asserted anyway — a control that leaves
# the thing it borrowed altered is worse than no control, and asserting it is how I know the repoint held.
if diff -q "$OUT/W1-7-baseline-real.txt" "$LIVE_TMUX_SNAPSHOT" >/dev/null; then
  it_pass W1-7-restored "" "the real baseline is byte-identical: the negative control ran against a repointed COPY and never wrote the shared file"
else
  it_fail W1-7-restored "fleet/it/live-tmux-sessions.txt" \
    "the negative control left the baseline doctored — every later isolation verdict is against a fiction"
fi

# W1-9 · NEGATIVE CONTROL for `SI-25`'s attribution. The claude check now decides whose an added process is
#        by cwd containment, and the §L/§M/§N run that exercised it only saw a REMOVAL — so the branch that
#        matters most, "a claude appeared and it IS this section's", had never fired. An attribution nobody
#        has seen fail is `SI-1`'s shape a fourth time.
#
#        Both branches are driven with a real process each, named `claude` so `pgrep -x claude` matches it
#        exactly as it would a dispatched worker: one started INSIDE the instant (what a section's dispatch
#        produces, since a worker starts in the slot it leased) and one started OUTSIDE (what the operator's
#        own session looks like). No real `claude` is launched — a copy of the stub carries the name.
W9="$OUT/w1-9"; mkdir -p "$W9/inside"
cp "$IT_ROOT/bin/claude" "$W9/claude"
( cd "$W9/inside" && exec "$W9/claude" sleep-forever ) >/dev/null 2>&1 &
inside_pid=$!
( cd /tmp && exec "$W9/claude" sleep-forever ) >/dev/null 2>&1 &
outside_pid=$!
sleep 0.5
w9_ok=1
w9_detail=""
if it_pid_cwd_inside_instant "$inside_pid"; then
  w9_detail="$w9_detail inside-attributed=yes"
else
  w9_ok=0; w9_detail="$w9_detail inside-attributed=NO(cwd=$(readlink /proc/$inside_pid/cwd 2>/dev/null))"
fi
if it_pid_cwd_inside_instant "$outside_pid"; then
  w9_ok=0; w9_detail="$w9_detail outside-attributed-as-mine=YES(wrong)"
else
  w9_detail="$w9_detail outside-attributed=correctly-foreign"
fi
kill "$inside_pid" "$outside_pid" 2>/dev/null
wait "$inside_pid" "$outside_pid" 2>/dev/null
{ printf 'inside_pid\t%s\noutside_pid\t%s\nverdict\t%s\n' "$inside_pid" "$outside_pid" "$w9_detail"; } \
  > "$OUT/W1-9-attribution.tsv"
if [ "$w9_ok" = 1 ]; then
  it_pass W1-9 "fleet/it/W1/out/W1-9-attribution.tsv" \
    "SI-25's attribution is FALSIFIABLE, both directions with a real process each: a claude-named process started INSIDE the instant attributes to the section (which is what makes an added worker FAIL), and one started outside does not (which is what stopped the operator's quantonOnSpark4 session being charged to §L/§M/§N). Without this the branch that accuses had never fired —$w9_detail"
else
  it_fail W1-9 "fleet/it/W1/out/W1-9-attribution.tsv" \
    "the attribution does not discriminate:$w9_detail"
fi

it_assert_isolation W1-leave

bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict from this run" >&2; exit 3; }
echo "W-1 done: IT_FAILED=$IT_FAILED"
#: `II-11`. Was `exit "$IT_FAILED"` — a COUNT. `exit` truncates modulo 256, so a section with
#: exactly 256 failures reported SUCCESS, and one with 300 reported 44, a number meaning nothing
#: to any reader. An exit status is a one-byte verdict, not a tally: the count is already printed
#: on the line above and is in the register, which is where a consumer should read it anyway.
if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
exit 1
