#!/usr/bin/env bash
# `it_assert_isolation`'s session-delta classification, with a negative control.
#
# This function is what every other section's verdict rests on, so loosening it is exactly the change that
# could quietly stop protecting anything. The control is the first case below: if a leaked IT-prefixed
# session stops failing, the whole change is unfalsifiable and the rest of this file proves nothing.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fails=0
note() { printf '  %s\n' "$*"; }
check() { if [ "$2" = "$3" ]; then note "ok   $1"; else note "FAIL $1 — wanted [$2] got [$3]"; fails=1; fi; }

# Drive the classifier directly with a baseline and an "after" set, so no real tmux server is needed and
# the case cannot be perturbed by whatever is running on this box.
classify() {   # classify <baseline-lines> <after-lines> -> prints "verdict|detail"
  BASELINE="$1" AFTER="$2" TMUX_PREFIX="itfleet-B" bash -c '
    . "'"$REPO"'/fleet/it/lib.sh" 2>/dev/null || true
    it_classify_session_delta "$BASELINE" "$AFTER"
  '
}

# --- THE NEGATIVE CONTROL: a leaked harness session must still be a hard failure ---------------------
out="$(classify $'dt-live\nzsh' $'dt-live\nitfleet-B-worker\nzsh')"
check "an IT-prefixed session appearing is a LEAK" "FAIL" "${out%%|*}"
# Matched against the FAIL verdict AND the name, not the name alone. As first written this checked only
# `*itfleet-B-worker*` over the whole output — which the NOTE branch also prints, in its `appeared=[…]`
# list. So it passed with the leak branch disabled and discriminated nothing: a vacuous check sitting
# inside the negative control that exists to prove the rest is not vacuous.
case "$out" in 'FAIL|'*itfleet-B-worker*) note "ok   the leak FAILs and names the session" ;;
               *) note "FAIL the leak is not reported as a FAIL naming the session: $out"; fails=1 ;; esac

# --- the observed false RED: another operator's session appearing is a note --------------------------
out="$(classify $'dt-live\nzsh' $'claude_mor_design_chinmay\ndt-live\nzsh')"
check "a foreign session appearing is a NOTE" "NOTE" "${out%%|*}"

# --- a harness-prefixed session VANISHING is a hard failure too --------------------------------------
# The direction W1-7's negative control actually injects: it doctors the baseline by ADDING an itfleet-
# name, which surfaces as vanished. The first version of the classifier checked only `appeared`, so this
# fell through to NOTE and W1-7 passed while asserting nothing.
out="$(classify $'dt-live\nitfleet-W1-ghost\nzsh' $'dt-live\nzsh')"
check "a harness-prefixed session vanishing is a FAIL" "FAIL" "${out%%|*}"
case "$out" in 'FAIL|'*itfleet-W1-ghost*) note "ok   the vanished harness session is named" ;;
               *) note "FAIL the vanished harness session is not named: $out"; fails=1 ;; esac

# --- a dt- session disappearing is still a hard failure ----------------------------------------------
out="$(classify $'dt-live\nzsh' $'zsh')"
check "a dt- session disappearing is a FAIL" "FAIL" "${out%%|*}"

# --- a non-dt session disappearing is a note ---------------------------------------------------------
out="$(classify $'dt-live\nzsh' $'dt-live')"
check "a non-dt session disappearing is a NOTE" "NOTE" "${out%%|*}"

# --- no change at all is a clean pass ----------------------------------------------------------------
out="$(classify $'dt-live\nzsh' $'dt-live\nzsh')"
check "an unchanged set is OK" "OK" "${out%%|*}"

# --- a leak AND foreign activity together: the leak wins ---------------------------------------------
out="$(classify $'zsh' $'claude_other\nitfleet-B-x\nzsh')"
check "a leak alongside foreign activity still FAILs" "FAIL" "${out%%|*}"

# =====================================================================================================
# `it_assert_no_private_leak` — the part of the contract the classifier CANNOT decide.
#
# `II-1`. The classifier judges by NAME SHAPE: `itfleet-*` appearing is a leak, anything else appearing is
# the operator using a shared box. But `cli._do_dispatch` hardcodes `dt-{name}` for the session it starts,
# so §D's and §group3's own sessions carry NO harness prefix — a leaked one looks exactly like another
# operator's dispatch. That is why the four private byte-comparisons could not simply be deleted: this is
# the load-bearing part of what they were doing, and this helper is what replaced it.
#
# `it_live_tmux_sessions` is STUBBED rather than exercised against a real server. Testing this for real
# would mean putting a `dt-` or `itfleet-` session on the DEFAULT server — the precise act the isolation
# contract forbids, and one that would corrupt any suite running concurrently on this shared box. The stub
# drives the SHIPPED function, not a copy of it.
leakcheck() {   # leakcheck <live sessions> <private names> -> "PASS|detail" or "FAIL|detail"
  LIVE="$1" NAMES="$2" bash -c '
    . "'"$REPO"'/fleet/it/lib.sh" 2>/dev/null || true
    it_live_tmux_sessions() { printf "%s\n" "$LIVE"; }
    it_pass() { printf "PASS|%s\n" "$3"; }
    it_fail() { printf "FAIL|%s\n" "$3"; }
    f="$(mktemp)"; printf "%s\n" "$NAMES" > "$f"
    IT_TMUX_SOCKET=itfleet-D it_assert_no_private_leak LEAKCASE "$f" ""
    rm -f "$f"
  '
}

# THE NEGATIVE CONTROL for this helper: a dt- session on both servers must be a hard failure. If this stops
# failing, collapsing the byte-comparisons dropped real coverage and everything below is theatre.
out="$(leakcheck $'dt-someone-else\ndt-mine\nzsh' $'dt-mine')"
check "a private dt- name also on the default server is a LEAK" "FAIL" "${out%%|*}"
case "$out" in 'FAIL|'*dt-mine*) note "ok   the leak FAILs and names the session" ;;
               *) note "FAIL the leak is not reported as a FAIL naming the session: $out"; fails=1 ;; esac

# The two are not redundant, shown rather than asserted: this exact delta is only a NOTE to the classifier,
# because a `dt-` arrival carries no harness prefix. One check sees it; the other cannot.
out="$(classify $'zsh' $'dt-mine\nzsh')"
check "a dt- session APPEARING is only a NOTE to the classifier" "NOTE" "${out%%|*}"

# Another operator's dt- session, which this section did not create, must NOT fail. This is the false
# positive that byte-comparison produced on every run and that `II-1` exists to remove.
out="$(leakcheck $'dt-someone-else\nzsh' $'dt-mine')"
check "a foreign dt- session on the live server is not this section's leak" "PASS" "${out%%|*}"

# Nothing created at all: clean, and it must report the zero rather than imply a check it did not make.
out="$(leakcheck $'dt-someone-else\nzsh' '')"
check "no private sessions is a PASS" "PASS" "${out%%|*}"
case "$out" in *"none of the 0 session"*) note "ok   an empty private set reports its count, not a bare pass" ;;
               *) note "FAIL an empty private set does not report its count: $out"; fails=1 ;; esac

# EXACT match, not substring. `kill-session -t itfleet-N-pre-a` prefix-resolved and destroyed a live
# `itfleet-N-pre-ab` in N7c (FI-23/SI-2); the same sloppiness in the READ direction would invent leaks
# that are not there and make the case untrustworthy in the other direction.
out="$(leakcheck $'dt-mine-extra\nzsh' $'dt-mine')"
check "a longer live name is not a prefix match for a private one" "PASS" "${out%%|*}"

if [ "$fails" = 0 ]; then
  echo "PASS: it_classify_session_delta fails on a harness leak and on a vanished dt- session and reports foreign churn as a note; it_assert_no_private_leak catches by EXACT NAME the dt- leak the classifier cannot see"
  exit 0
fi
echo FAIL
exit 1
