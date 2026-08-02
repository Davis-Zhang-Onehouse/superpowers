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
case "$out" in *itfleet-B-worker*) note "ok   the leak names the session" ;;
               *) note "FAIL the leak does not name the session: $out"; fails=1 ;; esac

# --- the observed false RED: another operator's session appearing is a note --------------------------
out="$(classify $'dt-live\nzsh' $'claude_mor_design_chinmay\ndt-live\nzsh')"
check "a foreign session appearing is a NOTE" "NOTE" "${out%%|*}"

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
