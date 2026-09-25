#!/usr/bin/env bash
# §SO — one owner per session (V23-T, RV-S1 / S5-I1). Run: bash fleet/it/run-SO.sh
#
# A re-dispatch of a title reuses `dt-<name>`, so an aborted record and its re-dispatch name ONE real tmux session.
# The hermetic suite (tests/test_session_ownership.py) proves the rule with stubbed probes; this section proves it
# against a real private server, real `tmux has-session` and the real process census:
#   SO1  the aborted record reads COMPLETE with liveness `none`: the live session is the re-dispatch's (liveness
#        `session`). At base the aborted record read the session as its own — the route by which it carried the new
#        worker's pid, which `scripts/fleet-finished-pids.sh` maps to exclude-from-auto-resume. (The stand-in `claude`
#        execs /bin/sleep, which the process census does not count, so liveness is the observable here, not the pid.)
#   SO2  `close --id <aborted record>` exits 0 and leaves the re-dispatch's session ALIVE. At base it killed it.
#   SO3  control: `close --id <re-dispatch> --force` still ends its own session.
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"
IT_FAILED=0
it_own_cases 'SO[0-9]+|ISOLATION-SO-(enter|leave)'
it_section SO
trap 'it_cleanup_tmux; tmux -L "$IT_TMUX_SOCKET" kill-server 2>/dev/null' EXIT
OUT="$EV/out"; rm -rf "$OUT"; mkdir -p "$OUT"
export FLEET_INSTANTS="$EV/instants"; rm -rf "$FLEET_INSTANTS"
it_fresh_store
mkdir -p "$FLEET_INSTANTS"
bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2
PATH="$IT_ROOT/bin:$PATH"; export PATH          # the stand-in `claude` (bin/claude): no model is launched

cp -r "$INSTANT/tests/fixtures/profiles/workerCompliant" "$OUT/profile"
for s in ws1 ws2; do
  mkdir -p "$OUT/slots/$s"
  ( cd "$OUT/slots/$s" && git init -q . && git commit -q --allow-empty -m base ) >/dev/null 2>&1
done
fleet set-golden --path "$OUT/slots/ws1" > "$OUT/setup.out" 2>&1
for s in ws1 ws2; do fleet enroll --slot "$OUT/slots/$s" >> "$OUT/setup.out" 2>&1; done

field() { awk -F'\t' -v k="$1" '$1==k{print $2; exit}' "$2"; }
alive() { tmux -L "$IT_TMUX_SOCKET" has-session -t "=$1" 2>/dev/null; }

fleet dispatch --profile "$OUT/profile" --title "reuseMe" --base 00000000 --optype append --porcelain \
  > "$OUT/old-dispatch.out" 2>&1
OLD_ID="$(field todo_id "$OUT/old-dispatch.out")"; OLD="$(field instant "$OUT/old-dispatch.out")"
TMUXN="$(field tmux "$OUT/old-dispatch.out")"
if [ -z "$OLD_ID" ] || ! alive "$TMUXN"; then
  echo "setup: the first dispatch did not leave a live session; nothing below is a verdict" >&2
  cat "$OUT/old-dispatch.out" >&2; exit 2
fi
fleet abort --instant "$OLD" --reason "superseded: re-dispatching the same title" --force > "$OUT/old-abort.out" 2>&1
# The child path and todo id derive from (base, MINUTE, title): the same minute is refused (SI-20), so wait it out.
minute="$(date -u +%M)"; while [ "$(date -u +%M)" = "$minute" ]; do sleep 2; done
fleet dispatch --profile "$OUT/profile" --title "reuseMe" --base 00000000 --optype append --porcelain \
  > "$OUT/new-dispatch.out" 2>&1
NEW_ID="$(field todo_id "$OUT/new-dispatch.out")"
if [ -z "$NEW_ID" ] || [ "$NEW_ID" = "$OLD_ID" ] || [ "$(field tmux "$OUT/new-dispatch.out")" != "$TMUXN" ] \
   || ! alive "$TMUXN"; then
  echo "setup: the re-dispatch did not reuse a live $TMUXN under a new record; nothing below is a verdict" >&2
  cat "$OUT/old-abort.out" "$OUT/new-dispatch.out" >&2; exit 2
fi

# ---- SO1 --------------------------------------------------------------------------------------------------------
fleet status --id "$OLD_ID" --porcelain > "$OUT/SO1-old-status.tsv" 2>&1; old_rc=$?
fleet status --id "$NEW_ID" --porcelain > "$OUT/SO1-new-status.tsv" 2>&1; new_rc=$?
old_state="$(field state "$OUT/SO1-old-status.tsv")"; old_live="$(field evidence.liveness "$OUT/SO1-old-status.tsv")"
old_pid="$(field evidence.pid "$OUT/SO1-old-status.tsv")"; new_live="$(field evidence.liveness "$OUT/SO1-new-status.tsv")"
if [ "$old_rc$new_rc" = 00 ] && [ "$old_state" = COMPLETE ] && [ "$old_live" = none ] && [ -z "$old_pid" ] \
   && [ "$new_live" != none ] && [ -n "$new_live" ]; then
  it_pass SO1 "fleet/it/SO/out/SO1-old-status.tsv" \
    "the aborted record reads COMPLETE with liveness none and no pid; the live session is the re-dispatch's (liveness $new_live)"
else
  it_fail SO1 "fleet/it/SO/out/SO1-old-status.tsv" \
    "rc=$old_rc/$new_rc old state=$old_state liveness=$old_live pid='$old_pid', new liveness=$new_live: the aborted record reads the re-dispatch's session"
fi

# ---- SO2 --------------------------------------------------------------------------------------------------------
fleet close --id "$OLD_ID" > "$OUT/SO2-close-old.out" 2>&1; close_rc=$?
if [ "$close_rc" = 0 ] && alive "$TMUXN" && grep -qF "belongs to $NEW_ID" "$OUT/SO2-close-old.out"; then
  it_pass SO2 "fleet/it/SO/out/SO2-close-old.out" \
    "close of the aborted record exited 0, left $TMUXN (the re-dispatch's) alive and named its owner"
else
  it_fail SO2 "fleet/it/SO/out/SO2-close-old.out" \
    "close rc=$close_rc, session alive after: $(alive "$TMUXN" && echo yes || echo NO): a verb aimed at the old record reached the new worker's session"
fi

# ---- SO3 (control) ---------------------------------------------------------------------------------------------
fleet close --id "$NEW_ID" --force > "$OUT/SO3-close-new.out" 2>&1; own_rc=$?
if [ "$own_rc" = 0 ] && ! alive "$TMUXN"; then
  it_pass SO3 "fleet/it/SO/out/SO3-close-new.out" "control: close of the owner still ends its own session"
else
  it_fail SO3 "fleet/it/SO/out/SO3-close-new.out" "close of the owner rc=$own_rc; its session is still alive"
fi

bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict" >&2; exit 3; }
it_assert_isolation SO-leave
[ "$IT_FAILED" -eq 0 ]
