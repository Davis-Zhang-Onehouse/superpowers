#!/usr/bin/env bash
# Run: bash fleet/it/run-AT.sh
#
# §AT — B24 (x2 G-4, FI-9): A HUMAN ATTACHED AND TYPING IS NOT A WORKER WAITING ON ONE.
#
# `BLOCKED` is actionable, and a pane showing unsubmitted text or a dialog reads the same whether a worker is
# stuck there or a human is attached and mid-sentence. fleet never read tmux's `#{session_attached}`, so the
# board said "needs you" to the person already at the pane. Each case here is a REAL dispatch on this
# section's PRIVATE server with a REAL attached client (a pty from util-linux `script`), read back through
# `board`, `reconcile` and `status`. Pane CONTENT is a frame, because the stand-in `claude` draws no chrome.
#
#   AT1  unsubmitted text, a human ATTACHED        -> BLOCKED, not counted (reconcile `info`), note says so
#   AT2  the same text, NOBODY attached            -> BLOCKED and counted — a swallowed submit (the control)
#   AT3  an operator dialog, a human ATTACHED      -> BLOCKED, not counted
#   AT4  the same dialog, NOBODY attached          -> BLOCKED and counted — the stuck worker the reporter's
#                                                     RETRACTED remedy (narrow BLOCKED to park.json) would hide
#   AT5  a quiet pane, a human ATTACHED            -> RUNNING: attachment alone makes nothing actionable
#   AT6  `status` reports the attachment as evidence
#   AT7  the banner counts exactly the three BLOCKED workers nobody interactive is attached to
#   AT8  a dialog with only a READ-ONLY client attached (`attach -r`) -> counted: that client cannot answer the
#        modal, and tmux still counts it in #{session_attached} and moves #{session_activity} on its dropped
#        keystrokes (RV-28)
#   AT0  fixture control: tmux itself reports 1 client on every attached session and 0 on every other, or
#        every verdict above is about something else
#
# On the base before B24, AT1 and AT3 FAIL (both `attention`) and AT7 reads `5 needs you`.
set -uo pipefail
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck disable=SC1091
. "$IT_ROOT/lib.sh"
RESULTS="${IT_RESULTS:-$IT_ROOT/RESULTS-AT.tsv}"
[ -f "$RESULTS" ] || printf 'case\tverdict\tevidence\tnote\n' > "$RESULTS"
it_own_cases 'AT[0-9]+|ISOLATION-AT-(enter|leave)'
IT_FAILED=0

it_section AT
it_fresh_store
export FLEET_INSTANTS="$EV/instants"; rm -rf "$FLEET_INSTANTS"; mkdir -p "$FLEET_INSTANTS"
OUT="$EV/out"; rm -rf "$OUT"; mkdir -p "$OUT"
CLIENTS=()
# Every client wrapper is OURS and killed by the pid captured at spawn — never by a pattern, which would match
# this shell (FB-15: a `script` wrapper left alive outlives the section).
at_cleanup() {
  local p
  for p in "${CLIENTS[@]}"; do kill "$p" 2>/dev/null; done
  tmux -L "$IT_TMUX_SOCKET" kill-server 2>/dev/null
  for p in "${CLIENTS[@]}"; do kill -9 "$p" 2>/dev/null; wait "$p" 2>/dev/null; done
  rm -f "${TMUX_TMPDIR:-/tmp}/tmux-$(id -u)/$IT_TMUX_SOCKET"
}
trap at_cleanup EXIT
bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2
PATH="$IT_ROOT/bin:$PATH"; export PATH          # the stand-in `claude`: a dispatch here launches no model

if ! command -v script >/dev/null 2>&1; then
  for c in AT0 AT1 AT2 AT3 AT4 AT5 AT6 AT7 AT8; do it_skip "$c" "" 'util-linux `script` is not installed, so no client can be attached'; done
  it_assert_isolation AT-leave; exit "$IT_FAILED"
fi

COORD="$(fleet init --base 00000000 --name "coordat$$" --porcelain 2>"$OUT/init.err" | awk -F'\t' '$1=="path"{print $2; exit}')"
cp -r "$INSTANT/tests/fixtures/profiles/workerCompliant" "$OUT/profile"
{ for n in 1 2 3 4 5 6; do
    ( mkdir -p "$OUT/slots/s$n" && cd "$OUT/slots/s$n" && git init -q . && git commit -q --allow-empty -m base ) &&
    fleet enroll --slot "$OUT/slots/s$n" --porcelain || exit 1
  done
  fleet set-golden --path "$OUT/slots/s1" --porcelain
} > "$OUT/setup.out" 2>&1 || { echo "setup failed; nothing below is a verdict (see $OUT/setup.out)" >&2; exit 2; }

# A human mid-sentence: text in the input box, nothing submitted, the turn over (no interrupt hint).
printf 'wrote target/fleet.jar\ndone\n\n\342\235\257 also re-run the rebase check before you\n' > "$OUT/typing.txt"
printf 'Which of these should I keep?\n  1. Drop it\n  2. Keep it and carry the note\n\nEnter to select \302\267 Tab/Arrow keys to navigate \302\267 Esc to cancel\n' > "$OUT/dialog.txt"
printf 'compiled 42 files\nwrote target/fleet.jar\ndone\n' > "$OUT/quiet.txt"

# dispatch <tag> -> ID, TMUXS. Six independent scenarios on one store, so every dispatch past the cap overrides.
dispatch() {
  fleet dispatch --profile "$OUT/profile" --title "$1" --base 00000000 --optype append --from "$COORD" \
        --override "AT: independent scenarios on one private store" --porcelain > "$OUT/$1-dispatch.out" 2>&1
  ID="$(awk -F'\t' '$1=="todo_id"{print $2}' "$OUT/$1-dispatch.out")"
  TMUXS="$(awk -F'\t' '$1=="tmux"{print $2}' "$OUT/$1-dispatch.out")"
  [ -n "$ID" ] && [ -n "$TMUXS" ] || { echo "dispatch $1 produced no record; nothing below is a verdict" >&2; exit 2; }
}
# frame <file>: replace the session's pane content, keeping its name, server and cwd.
frame() {
  local cwd; cwd="$(it_tmux display -p -t "=$TMUXS:" '#{pane_current_path}' 2>/dev/null)"
  it_tmux kill-session -t "=$TMUXS" 2>/dev/null
  it_tmux new-session -d -s "$TMUXS" -c "${cwd:-$OUT}" "bash -c 'cat $1; exec sleep 100000'"; sleep 0.6
}
# attach: a REAL client on the session. stdin is a FIFO this shell holds open: /dev/zero would TYPE (NULs move
# #{session_activity}), /dev/null would end `script` at EOF. $TMUX unset: attaching from inside a pane is nesting.
# `attach -r` for a read-only client.
attach() {
  local fifo="$OUT/$TMUXS.client.in" fd
  mkfifo "$fifo"; exec {fd}<>"$fifo"
  env -u TMUX SHELL=/bin/sh setsid script -qfc "tmux -L $IT_TMUX_SOCKET attach ${1:-} -t =$TMUXS" /dev/null \
      < "$fifo" > "$OUT/$TMUXS.client.tty" 2>&1 &
  CLIENTS+=("$!")
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    [ "$(it_tmux list-clients -t "=$TMUXS" -F x 2>/dev/null | wc -l)" -ge 1 ] && break; sleep 0.3
  done
}
# observe <tag>: the board row, the reconcile severity and status, each verb's rc captured before anything else.
observe() {
  fleet board --porcelain > "$OUT/$1-board.tsv" 2>&1; echo "$?" > "$OUT/$1-board.rc"
  fleet reconcile --porcelain > "$OUT/$1-reconcile.tsv" 2>&1; echo "$?" > "$OUT/$1-reconcile.rc"
  fleet status --id "$ID" --porcelain > "$OUT/$1-status.tsv" 2>&1; echo "$?" > "$OUT/$1-status.rc"
  STATE="$(awk -F'\t' -v t="$ID" '$1==t{print $3}' "$OUT/$1-board.tsv")"
  NOTE="$(awk -F'\t' -v t="$ID" '$1==t{print $7}' "$OUT/$1-board.tsv")"
  SEV="$(awk -F'\t' -v t="$ID" '$2==t{print $3}' "$OUT/$1-reconcile.tsv")"
  RCS="$(cat "$OUT/$1-board.rc")/$(cat "$OUT/$1-reconcile.rc")/$(cat "$OUT/$1-status.rc")"
}

dispatch atTyping;   T1="$TMUXS"; frame "$OUT/typing.txt"; attach; observe AT1
AT1=("$STATE" "$SEV" "$NOTE" "$RCS")
dispatch atSwallow;  T2="$TMUXS"; frame "$OUT/typing.txt";         observe AT2
AT2=("$STATE" "$SEV" "$NOTE" "$RCS")
dispatch atDialog;   T3="$TMUXS"; frame "$OUT/dialog.txt"; attach; observe AT3
AT3=("$STATE" "$SEV" "$NOTE" "$RCS")
dispatch atStuck;    T4="$TMUXS"; frame "$OUT/dialog.txt";         observe AT4
AT4=("$STATE" "$SEV" "$NOTE" "$RCS")
dispatch atQuiet;    T5="$TMUXS"; frame "$OUT/quiet.txt";  attach; observe AT5
AT5=("$STATE" "$SEV" "$NOTE" "$RCS")
dispatch atReadOnly; T6="$TMUXS"; frame "$OUT/dialog.txt"; attach -r; observe AT8
AT8=("$STATE" "$SEV" "$NOTE" "$RCS")
it_tmux list-clients -t "=$T6" -F '#{client_readonly}' > "$OUT/AT8-clients.out" 2>&1
fleet board > "$OUT/banner.out" 2>&1; banner_rc=$?
it_tmux list-sessions -F '#{session_name} #{session_attached}' > "$OUT/AT0-attached.out" 2>&1

# ---- AT0: the fixture is the state it claims -------------------------------------------------------------
want="$(printf '%s 1\n%s 0\n%s 1\n%s 0\n%s 1\n%s 1\n' "$T1" "$T2" "$T3" "$T4" "$T5" "$T6" | sort)"
if [ "$(sort "$OUT/AT0-attached.out")" = "$want" ] && [ "$(cat "$OUT/AT8-clients.out")" = 1 ]; then
  it_pass AT0 "fleet/it/AT/out/AT0-attached.out" 'fixture control: tmux reports one client on each attached session and none on the others, and the AT8 client is read-only'
else it_fail AT0 "fleet/it/AT/out/AT0-attached.out" "tmux did not report the attachment the fixture built: $(tr '\n' ';' < "$OUT/AT0-attached.out")"; fi

# verdict <case> <want-state> <want-sev> <note-must-contain|-> <note-must-not-contain|-> <array...>
verdict() {
  local c="$1" ws="$2" wv="$3" has="$4" hasnt="$5" s="$6" v="$7" n="$8" r="$9" what="${10}"
  if [ "$r" = "0/0/0" ] && [ "$s" = "$ws" ] && [ "$v" = "$wv" ] &&
     { [ "$has" = - ] || [[ "$n" == *"$has"* ]]; } && { [ "$hasnt" = - ] || [[ "$n" != *"$hasnt"* ]]; }; then
    it_pass "$c" "fleet/it/AT/out/$c-board.tsv" "$what: $s, reconcile $v"
  else
    it_fail "$c" "fleet/it/AT/out/$c-board.tsv" "$what: want $ws/$wv, got state=$s severity=$v rc(board/reconcile/status)=$r note=$n"
  fi
}
verdict AT1 BLOCKED info      'a human is attached' -          "${AT1[@]}" 'a human attached and typing is not counted'
verdict AT2 BLOCKED attention -                     'attached' "${AT2[@]}" 'the same text with nobody attached is a swallowed submit and is counted'
verdict AT3 BLOCKED info      'a human is attached' -          "${AT3[@]}" 'a dialog in front of an attached human is theirs to answer'
verdict AT4 BLOCKED attention -                     'attached' "${AT4[@]}" 'the same dialog with nobody attached is a stuck worker and is counted'
verdict AT5 RUNNING info      -                     -          "${AT5[@]}" 'attachment alone makes nothing actionable'
verdict AT8 BLOCKED attention -                     'a human is attached' "${AT8[@]}" 'a dialog with only a read-only client attached is still a stuck worker'

# ---- AT6: the fact is evidence on `status`, for any consumer that must not type into an occupied pane ------
att="$(awk -F'\t' '$1=="evidence.attached"{print $2}' "$OUT/AT1-status.tsv")"
att2="$(awk -F'\t' '$1=="evidence.attached"{print $2}' "$OUT/AT2-status.tsv")"
if [[ "$att" == "1 client, last input "* ]] && [ "$att2" = "no client" ]; then
  it_pass AT6 "fleet/it/AT/out/AT1-status.tsv" "status carries the attachment: attached=[$att], detached=[$att2]"
else it_fail AT6 "fleet/it/AT/out/AT1-status.tsv" "status evidence.attached: attached=[$att] detached=[$att2]"; fi

# ---- AT7: the banner counts exactly the three BLOCKED workers no interactive client is at ------------------
if [ "$banner_rc" = 0 ] && grep -q '6 holding a slot · 3 needs you' "$OUT/banner.out"; then
  it_pass AT7 "fleet/it/AT/out/banner.out" 'banner: 6 holding a slot · 3 needs you'
else it_fail AT7 "fleet/it/AT/out/banner.out" "board rc=$banner_rc; $(grep -o '[0-9]* holding a slot · [0-9]* needs you' "$OUT/banner.out")"; fi

at_cleanup; CLIENTS=()
it_assert_isolation AT-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || exit 3
exit "$IT_FAILED"
