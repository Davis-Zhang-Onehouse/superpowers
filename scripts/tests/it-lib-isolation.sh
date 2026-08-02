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

if [ "$fails" = 0 ]; then
  echo "PASS: it_classify_session_delta fails on a harness leak and on a vanished dt- session, and reports foreign churn as a note"
  exit 0
fi
echo FAIL
exit 1
