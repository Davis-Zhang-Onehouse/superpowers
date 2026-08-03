#!/usr/bin/env bash
# RA-1 / A-6 — re-measure the type→Enter race on a REAL claude pane.
#
# WHY: `G-1` §2's table is the load-bearing evidence for the whole delivery contract, and it was
# CARRIED-OVER from the parent instant rather than regenerated here — one measurement, one session,
# 2026-08-02. The RCA flagged it `RA-1`. The operator authorised the allowance spend 2026-08-03.
#
# DERIVED FROM the original probe (`…/quantonFeedbackAndReleases/investigations/fi-15/probe2-timing.sh`),
# with the measurement logic kept IDENTICAL so the numbers are comparable, plus three deliberate changes:
#
#   1. OUTPUT LANDS HERE. The original writes `timing.txt` next to itself and opens with `: > "$LOG"`.
#      Running it in place would TRUNCATE the very artifact this probe exists to compare against, inside
#      another effort's instant — which the charter forbids touching at all.
#
#   2. THE BOX IS CLEARED BETWEEN TRIALS (C-u), and emptiness is ASSERTED before typing.
#      The original relies on `settle()` (poll for pane-guard 0). When trial 1 leaves a dropped Enter's
#      text in the box, settle() cannot reach 0 — it warns after 150s and the trial proceeds anyway. That
#      is visible in the original artifact: the WARNING sits between the gap=0 row and the gap=0.05 row,
#      so when the 50ms trial typed, the box ALREADY held trial 1's marker. Its `guard_after_type=10` was
#      therefore true whatever its own keystroke did, and its Enter submitted the CONCATENATION of two
#      markers (`guard_after_Enter=11`, mid-turn). The gap=0 result is clean and stands; the claim "at
#      50ms and above it submits every time" was measured with residue in the box.
#
#   3. gap=0 IS REPEATED. It is the only trial the contract depends on, and the original ran it once. A
#      race measured once cannot be distinguished from a coincidence.
#
#   4. A POSITIVE CONTROL ON THE REMEDY: one `live-pane.sh submit` (type → poll for 10 → Enter), so the
#      run shows both the failure and the fix under the same conditions.
#
# Run:   FLEET_ALLOW_LIVE_CLAUDE=1 bash bin/probe-ra1-send-race.sh
# Costs: ONE real claude session on a private tmux socket. Never the default server, never a `dt-` name.
set -uo pipefail

LP="${LP:-/home/ubuntu/davis_root/superpowers/fleet/it/bin/live-pane.sh}"
INSTANT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$INSTANT_DIR/evidence/2026-08-03-ra1-send-race.txt"
TSV="$INSTANT_DIR/evidence/2026-08-03-ra1-send-race.tsv"
: > "$LOG"
printf 'gap_s\tguard_after_type\tguard_after_enter\tclean\n' > "$TSV"
rec() { printf '%s\n' "$*" | tee -a "$LOG"; }

rec "RA-1 re-measurement of the FI-15 type->Enter race"
rec "when:    $(date -u +%FT%TZ)"
rec "claude:  $(/home/ubuntu/.local/bin/claude --version 2>/dev/null | head -1)  (original measurement: 2.1.220)"
rec "loadavg: $(cut -d' ' -f1-3 /proc/loadavg)   # relevant to A-5: the race is timing-sensitive"
rec "repo:    $(git -C /home/ubuntu/davis_root/superpowers rev-parse --short HEAD)"
rec ""

SESSION="$("$LP" start ra1race)" || exit 2
trap '"$LP" stop "$SESSION" >/dev/null 2>&1; "$LP" reap >/dev/null 2>&1' EXIT
rec "session: $SESSION"

# --- wait for the model to be READY, and show what state it booted into ---------------------------
# A fresh claude in a fresh scratch dir may show a trust prompt or onboarding. If it does, every trial
# below measures that widget instead of the input box, so this is asserted rather than assumed.
ready=0
for i in $(seq 1 60); do
  g="$("$LP" guard "$SESSION")" || true
  [ "$g" = 0 ] && { ready=1; break; }
  sleep 2
done
rec "boot:    pane-guard=$g after $((i*2))s  ($([ "$ready" = 1 ] && echo READY || echo 'NOT SETTLED'))"
rec ""
rec "--- pane at boot (first 12 lines) ---"
"$LP" cap "$SESSION" | head -12 | sed 's/^/    /' | tee -a "$LOG"
rec ""
if [ "$ready" != 1 ]; then
  rec "ABORTING: the pane never reached pane-guard=0, so nothing below would measure the input box."
  rec "Read the capture above — a trust prompt or onboarding screen is the likely cause."
  exit 1
fi

# Bring the pane to pane-guard=0 — model IDLE and box EMPTY — which is the only state a trial may start
# from. The two blockers are different and need different treatment, and conflating them was a bug in the
# first version of this probe: it read `11` (mid-turn) as "the box still has text", C-u'd at a busy model,
# gave up after 10s and labelled three good trials CONTAMINATED. `11` is not a dirty box; it is the model
# still answering the PREVIOUS trial's submission, and the only cure is to wait.
#   11 -> the model is working. Wait for it. A turn here is seconds, but budget generously.
#   10 -> text is sitting in the box. C-u it, then re-check.
settle_empty() {
  local i g
  for i in $(seq 1 90); do
    g="$("$LP" guard "$SESSION")" || true
    case "$g" in
      0)  return 0 ;;
      10) "$LP" key "$SESSION" C-u >/dev/null 2>&1 || true; sleep 0.5 ;;
      *)  sleep 2 ;;                       # 11 mid-turn, or a transient 12/13/14: wait it out
    esac
  done
  rec "  WARNING: pane never reached idle+empty (last pane-guard=$g) — the row below is CONTAMINATED"
  return 1
}
clear_box() { settle_empty; }

rec "A submitted trial shows guard_after_type=10 (text queued) and guard_after_Enter != 10."
rec "A DROPPED Enter leaves it at 10. Every trial starts from an ASSERTED-empty box."
rec ""

trial() {              # trial <label> <gap-seconds>
  local label="$1" gap="$2" marker="m${RANDOM}" before after clean=clean
  clear_box || clean=CONTAMINATED
  "$LP" type "$SESSION" "$marker"
  before="$("$LP" guard "$SESSION")" || true
  [ "$gap" != 0 ] && sleep "$gap"
  "$LP" key "$SESSION" Enter
  sleep 4
  after="$("$LP" guard "$SESSION")" || true
  rec "$(printf '%-20s gap=%-7s guard_after_type=%-3s guard_after_Enter=%-3s submitted=%-22s [%s]' \
        "$label" "${gap}s" "$before" "$after" \
        "$([ "$after" != 10 ] && echo YES || echo 'NO - still queued')" "$clean")"
  printf '%s\t%s\t%s\t%s\n' "$gap" "$before" "$after" "$clean" >> "$TSV"
}

# The FIRST run of this probe found the gap=0 outcome is NOT deterministic: trial 1 dropped the Enter,
# trial 2 at the same gap from an equally clean box submitted. That is what a race looks like, and it means
# the question is not "does it fail?" but "how often?" — because a fixed delay (which is what the one
# production send path uses) can only ever buy a PROBABILITY. So each gap is repeated and the rate reported.
for n in 1 2 3 4 5; do trial "immediate Enter #$n" 0; done
for n in 1 2 3;       do trial "50ms gap #$n"      0.05; done
for n in 1 2;         do trial "150ms gap #$n"     0.15; done   # what claude-auto-retry actually uses (A-5)
trial "500ms gap"          0.5
trial "3s gap"             3

# --- the remedy, under the same conditions --------------------------------------------------------
rec ""
rec "--- positive control: the CONDITION-based contract (live-pane.sh submit: type, poll for 10, Enter) ---"
clear_box || rec "  WARNING: box not empty before the control"
marker="ctl${RANDOM}"
if "$LP" submit "$SESSION" "$marker" 2>&1 | sed 's/^/    /' | tee -a "$LOG"; then
  sleep 4
  after="$("$LP" guard "$SESSION")" || true
  rec "$(printf '%-20s %s  guard_after=%-3s submitted=%s' "submit (condition)" \
        "polled for the box to hold the text, then Enter" "$after" \
        "$([ "$after" != 10 ] && echo YES || echo 'NO - still queued')")"
else
  rec "submit REFUSED to press Enter — it reported the text never reached the box, which is the"
  rec "behaviour that distinguishes it from a blind send. Not a failure of the contract."
fi

rec ""
rec "=== DROP RATE per gap (clean trials only; a drop is guard_after_Enter=10) ==="
awk -F'\t' 'NR>1 && $4=="clean" {n[$1]++; if ($3==10) d[$1]++}
  END { for (g in n) printf "  gap=%-7s trials=%-3s dropped=%-3s rate=%s\n", g"s", n[g], (d[g]+0), (d[g]+0)"/"n[g] }' \
  "$TSV" | sort | tee -a "$LOG"
rec ""
rec "A NON-ZERO rate at any gap means a fixed delay buys a PROBABILITY, not a guarantee — which is the"
rec "whole argument for a condition. A zero rate at 150ms does NOT clear claude-auto-retry (A-5): this box"
rec "was at loadavg $(cut -d' ' -f1 /proc/loadavg) and the failure is silent when it happens."
rec ""
rec "=== compare with the 2026-08-02 original (parent instant, investigations/fi-15/timing.txt) ==="
rec "  immediate Enter  gap=0s     guard_after_type=0   guard_after_Enter=10  submitted=NO"
rec "  50ms gap         gap=0.05s  guard_after_type=10  guard_after_Enter=11  submitted=YES  <- residue in box"
rec "  500ms gap        gap=0.5s   guard_after_type=10  guard_after_Enter=0   submitted=YES  <- residue in box"
rec "  3s gap           gap=3s     guard_after_type=10  guard_after_Enter=0   submitted=YES  <- residue in box"
