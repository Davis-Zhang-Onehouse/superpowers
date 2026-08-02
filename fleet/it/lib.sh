#!/usr/bin/env bash
# Integration-test harness. Sourced by every section.
#
# Its whole job is the isolation contract: the ANSI coordinator is LIVE on the old tooling, so a section that
# cannot prove it touched nothing does not get to report a pass. "Absence is never success" applies to the
# harness itself — a section that skips silently is a false pass, so `it_skip` writes a row saying so.
set -uo pipefail

IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The fleet package root — the directory holding src/ and tests/. One level up from `it/`, where the old
# layout had it two levels up (fleet/it/ inside an instant). Named INSTANT for continuity with
# every runner that already uses it; it is the PACKAGE root now, and the runners only ever ask it for
# src/ and tests/.
INSTANT="$(cd "$IT_ROOT/.." && pwd)"
export PYTHONPATH="$INSTANT/src"
# One results file per RUNNER when asked, so two sections can run concurrently without a shared
# read-modify-write. `it_own_cases` rewrites this file; two runners doing that at once is `FI-16`/`FI-29`'s
# shape — concurrent writers to one register — and last-writer-wins would silently drop a section's rows.
# The merge into the single RESULTS.tsv is then done by ONE writer, deliberately.
RESULTS="${IT_RESULTS:-$IT_ROOT/RESULTS.tsv}"

LIVE_SNAPSHOT="$IT_ROOT/live-stores.sha256"
LIVE_TMUX_SNAPSHOT="$IT_ROOT/live-tmux-sessions.txt"

# W-1. Every section gets a tmux server of its OWN, named by socket.
#
# `-L` is a namespace no prefix accident can escape: an EXACT target stops a command resolving to the
# wrong session ON a server (`FI-23`), a private server stops the wrong session being reachable AT ALL.
# Both, not either.
#
# The socket is per SECTION and not one shared `itfleet`, because the requirement has two halves: two IT
# groups must not see each other's sessions, AND neither may see the operator's. §M created
# `itfleet-M-worker` on the DEFAULT server and §E's server-wide isolation assertion failed on it — that
# was cross-agent contamination, not a product defect. A single shared private socket fixes the second
# half and leaves the first exactly as broken, one layer down: run §E and §M concurrently on one socket
# and §E sees §M's sessions again.
IT_TMUX_SOCKET=""       # set by it_section. Empty until then, and it_tmux refuses rather than guessing.

# The harness's OWN tmux calls. Never a bare `tmux` for section work — the same rule as `fleet()` below,
# and for the same reason: the server, like FLEET_HOME, is explicit or it is somebody else's.
#
# The bare form still has exactly two legitimate uses, both READ-ONLY and both about the live server:
# `it_live_tmux_sessions` and a section's deliberate "the operator's sessions are untouched" snapshot.
it_tmux() {
  if [ -z "$IT_TMUX_SOCKET" ]; then
    echo "it_tmux: no section entered, so there is no private server to talk to. A bare tmux here would" \
         "reach the LIVE one — refusing." >&2
    return 2
  fi
  tmux -L "$IT_TMUX_SOCKET" "$@"
}
# shellcheck disable=SC1091
. "$IT_ROOT/facts.env"
# The `dummy-project` fixture: two REAL git repos with history, used by §C's base-position cases and by
# §L's register cases. It cannot be stored as a directory inside this repository — git records a nested
# repo as a gitlink and stores none of its content, so a fresh clone would get empty directories and the
# sections would fail for a reason unrelated to what they test. It is therefore an ARCHIVE, unpacked on
# demand and gitignored once unpacked.
#
# `DUMMY` also gains a default here. It was `export`ed by run-group5.sh and never assigned anywhere in the
# harness, so §L only worked when the caller happened to have it in the environment — a latent dependency
# on the operator's shell.
if [ ! -d "$IT_ROOT/dummy-project" ] && [ -f "$IT_ROOT/fixtures/dummy-project.tar.gz" ]; then
  tar xzf "$IT_ROOT/fixtures/dummy-project.tar.gz" -C "$IT_ROOT"
fi
: "${DUMMY:=$IT_ROOT/dummy-project}"
export DUMMY

it_section() {            # it_section <name> -> own FLEET_HOME, own slots, own tmux prefix, own tmux SERVER
  SECTION="$1"
  export FLEET_HOME="$IT_ROOT/$SECTION/home"
  SLOTS="$IT_ROOT/$SECTION/slots"
  EV="$IT_ROOT/$SECTION"
  mkdir -p "$FLEET_HOME" "$SLOTS" "$EV"
  TMUX_PREFIX="itfleet-$SECTION"
  # The section's own tmux server, and the variable that carries it into every `fleet` subprocess this
  # section spawns (`session.TMUX_SOCKET_ENV`). The name prefix stays too: it is what `it_cleanup_tmux`
  # matches, and defence in depth costs nothing here.
  IT_TMUX_SOCKET="itfleet-$SECTION"
  export FLEET_TMUX_SOCKET="$IT_TMUX_SOCKET"
  it_assert_isolation "$SECTION-enter"
}

# A VIRGIN record store for this section. `it_section` only `mkdir -p`s FLEET_HOME, so a second run inherits
# the first run's records — and §H was measured failing exactly that way: `H10`'s dispatch was refused because
# the previous run's worker still held the WIP cap. A section whose verdicts depend on whether it has been run
# before is not measuring the product.
#
# Opt-in rather than folded into `it_section`, because a few runners accumulate state across sections on
# purpose (`run-group5.sh` walks §L §M §N in one process) and a blanket reset would silently change what they
# measure. Call it immediately after `it_section`, before anything writes.
it_fresh_store() {
  rm -rf "$FLEET_HOME"
  mkdir -p "$FLEET_HOME"
}

fleet() { python3 -m fleet.cli "$@"; }     # never a bare `fleet` on PATH — FLEET_HOME must be explicit

it_pass() { printf '%s\tPASS\t%s\t%s\n' "$1" "${2:-}" "${3:-}" >> "$RESULTS"; printf 'PASS %s %s\n' "$1" "${3:-}"; }
it_fail() { printf '%s\tFAIL\t%s\t%s\n' "$1" "${2:-}" "${3:-}" >> "$RESULTS"; printf 'FAIL %s %s\n' "$1" "${3:-}" >&2; IT_FAILED=1; }
it_skip() { printf '%s\tSKIP\t%s\t%s\n' "$1" "${2:-}" "${3:-cannot run — reason must be stated}" >> "$RESULTS"
            printf 'SKIP %s %s\n' "$1" "${3:-}" >&2; }

# A runner OWNS its cases: it drops its own prior rows before writing new ones, so RESULTS.tsv is the
# CURRENT state of every case rather than a log that has to be read backwards.
#
# `SI-4`: supersession used to live in the note column as prose — "supersedes the pre-fix FAIL" — which
# left 21 FAIL rows in a file whose sections all pass, and made `grep -c FAIL` a wrong answer. Machine-
# consumed state parsed out of prose is the one thing the north star forbids, and `zero NOT-RUN` (AC-3)
# cannot even be expressed in an append-only file: a NOT-RUN row has to be REPLACED, not annotated.
# History is not lost — git holds it, which is the right home for a log.
it_own_cases() {          # it_own_cases <extended regex matched against the whole case field>
  local re="$1" tmp
  [ -f "$RESULTS" ] || return 0
  # Staged NEXT TO the target, not in $TMPDIR. §A's A8c audit found this was the harness's only write that
  # left the instant altogether — and `mv` across filesystems is not atomic, so a temp in /tmp also gave up
  # the atomicity this function depends on. Same directory means same filesystem means a real rename.
  tmp="$(mktemp "$(dirname "$RESULTS")/.$(basename "$RESULTS").XXXXXX")"
  awk -F'\t' -v re="^($re)\$" 'NR==1 || $1 !~ re' "$RESULTS" > "$tmp" && mv "$tmp" "$RESULTS"
}

it_expect_exit() {        # it_expect_exit <case> <want> <cmd...>
  local case="$1" want="$2"; shift 2
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" = "$want" ]; then it_pass "$case" "" "exit $rc"
  else it_fail "$case" "" "want exit $want, got $rc :: $(printf '%s' "$out" | head -2 | tr '\n' ' ')"; fi
}

it_expect_contains() {    # it_expect_contains <case> <needle> <cmd...>
  local case="$1" needle="$2"; shift 2
  local out; out="$("$@" 2>&1)"
  if printf '%s' "$out" | grep -qF -- "$needle"; then it_pass "$case" "" "contains '$needle'"
  else it_fail "$case" "" "missing '$needle' :: $(printf '%s' "$out" | head -2 | tr '\n' ' ')"; fi
}

# A zero-delta assertion that catches a TRANSIENT write, not just a net change: content AND mtimes.
# The guards implementer showed a claim-then-release restores bytes exactly while still touching mtimes.
it_manifest() { find "$@" -mindepth 0 2>/dev/null | sort | while read -r f; do
                  printf '%s %s %s\n' "$(sha256sum "$f" 2>/dev/null | cut -d' ' -f1 || echo dir)" \
                                      "$(stat -c '%Y.%n' "$f" 2>/dev/null)"; done; }

it_zero_delta() {         # it_zero_delta <case> <cmd...>   over FLEET_HOME + slots
  local case="$1"; shift
  local before after
  before="$(it_manifest "$FLEET_HOME" "$SLOTS")"
  "$@" >/dev/null 2>&1
  after="$(it_manifest "$FLEET_HOME" "$SLOTS")"
  if [ "$before" = "$after" ]; then it_pass "$case" "" "zero delta (content+mtime)"
  else it_fail "$case" "" "delta: $(diff <(printf '%s' "$before") <(printf '%s' "$after") | head -3 | tr '\n' ' ')"; fi
}

# The SESSION NAMES on the live (default) tmux server, sorted. Names rather than `tmux ls` lines, because
# a line carries a window count and an `(attached)` marker that change when the operator merely attaches —
# that is not a contamination and a check that reports it as one gets switched off. A session APPEARING or
# DISAPPEARING is the thing that must never happen.
it_live_tmux_sessions() { tmux ls -F '#{session_name}' 2>/dev/null | sort; }

# it_assert_no_private_leak <case-id> <private-names-file> [<note-suffix>]
#
# Every session name this section created on its PRIVATE server, asserted ABSENT from the default one.
#
# `II-1`. This is the one thing the byte-comparisons in §B/§C/§D/§group3 were catching that
# `it_classify_session_delta` cannot, and the reason they could not simply be deleted. The classifier
# decides by NAME SHAPE: an `itfleet-*` name appearing on the live server is a leak, anything else
# appearing is the operator using a shared box. But `cli._do_dispatch` hardcodes `dt-{name}` for the
# session it starts, so the sessions §D and §group3 create do NOT carry a harness prefix — a leaked one
# looks exactly like another operator's dispatch and is downgraded to NOTE.
#
# Byte-comparing the whole live list did catch that, at the price of failing on any unrelated session
# appearing or vanishing mid-section, which on this box happens constantly. This asserts the EXACT names
# instead: no false positive from operator churn, and strictly stronger than byte-equality for the leak
# itself, because it names the leaked session rather than printing a diff of everything that moved.
#
# Called AFTER the section's private-server cleanup, deliberately: killing a session on the private
# socket cannot remove a copy that leaked to the default server, so a name still present here after the
# kill is a leak and not a race.
it_assert_no_private_leak() {
  local case_id="$1" names_file="$2" note="${3:-}"
  local live leaked="" n=0
  live="$(it_live_tmux_sessions)"
  if [ -s "$names_file" ]; then
    while read -r s; do
      [ -n "$s" ] || continue
      n=$((n+1))
      printf '%s\n' "$live" | grep -qxF -- "$s" && leaked="$leaked $s"
    done < "$names_file"
  fi
  if [ -n "${leaked// /}" ]; then
    it_fail "$case_id" "$names_file" \
      "session(s) this section created on its private server are ALSO on the DEFAULT server:$leaked. The harness works on socket ${IT_TMUX_SOCKET:-?} and nothing it starts may reach the default one. These names are dispatch sessions (\`dt-*\`, hardcoded by cli._do_dispatch), so they carry no harness prefix and the shape-based classifier reads them as another operator's work — this case is what tells the difference."
    return 1
  fi
  it_pass "$case_id" "$names_file" \
    "none of the $n session(s) this section created on socket ${IT_TMUX_SOCKET:-?} appears on the default server${note:+ ($note)}"
  return 0
}

# The live `claude` PID SET, sorted. Not a count.
#
# §D's first run failed its claude-count assertion on 9 -> 8 — a DECREASE, caused by the operator's own
# session ending, with nothing in §D able to start or signal a `claude`. A count cannot tell "the thing I
# was forbidden to do" from "something unrelated finished", so it reports the operator's churn as the
# section's contamination. That is `SI-1`'s shape one control over: the check was too coarse to be
# falsifiable in the direction that matters.
#
# The rule the sections actually need is asymmetric, so the helpers are too: an ADDITION is a violation (a
# section launched a process it must not have), a REMOVAL is news (report it, do not fail on it). §D wrote
# this for itself; lifted here so every section gets it and no section has to re-derive it.
it_claude_pids() { pgrep -x claude 2>/dev/null | sort -n; }

#: Whether a pid's cwd is inside this instant. ATTRIBUTION, not a guess: `fleet dispatch` starts a worker
#: with `sessions.start(tmux, lease.path, "claude")`, so a claude a SECTION launched has its cwd in a slot
#: or instant under `$INSTANT`. One whose cwd is elsewhere cannot be this section's, because a section can
#: only dispatch into slots it leased.
it_pid_cwd_inside_instant() {   # it_pid_cwd_inside_instant <pid>
  local cwd; cwd="$(readlink "/proc/$1/cwd" 2>/dev/null)" || return 1
  case "$cwd" in "$INSTANT"/*) return 0 ;; *) return 1 ;; esac
}

it_assert_no_new_claude() {      # it_assert_no_new_claude <case> <before-pids> [note-suffix]
  local case="$1" before="$2" extra="${3:-}" after added removed mine foreign pid
  after="$(it_claude_pids)"
  added="$(comm -13 <(printf '%s\n' "$before") <(printf '%s\n' "$after") | tr '\n' ' ')"
  removed="$(comm -23 <(printf '%s\n' "$before") <(printf '%s\n' "$after") | tr '\n' ' ')"

  # `SI-25`: an ADDITION is not automatically this section's. The operator starts sessions on other projects
  # while a run is in flight — measured: `claude --continue` in `…/tasks/quantonOnSpark4` appeared mid-§M and
  # this check charged it to §L/§M/§N, which contain no dispatch and no `sessions.start` at all. That is
  # `SD-4`'s shape one control over, and the same resolution applies: do not make the check cleverer about
  # WHETHER a change is acceptable — make it attribute mechanically and report what it could not attribute.
  mine=""; foreign=""
  for pid in $added; do
    if it_pid_cwd_inside_instant "$pid"; then mine="$mine $pid"
    else foreign="$foreign $pid($(readlink "/proc/$pid/cwd" 2>/dev/null | sed "s|$HOME|~|"))"; fi
  done

  if [ -n "$mine" ]; then
    it_fail "$case" "" "a claude process launched BY THIS SECTION appeared: pid(s)$mine, with a cwd inside this instant. No section outside §P may launch one. $extra"
  elif [ -n "$foreign" ]; then
    it_pass "$case" "" "no claude appeared from this section. $(printf '%s' "$foreign" | wc -w) claude process(es) DID start during the run with a cwd OUTSIDE this instant —$foreign— which a section cannot cause: dispatch starts a worker in the slot it leased, so a cwd elsewhere is somebody else's session. Reported, not charged to this section. $extra"
  else
    it_pass "$case" "" "no claude process appeared (pids before: $(printf '%s' "$before" | grep -c .), after: $(printf '%s' "$after" | grep -c .)$([ -n "$removed" ] && printf '; %s ended during the run, which is the operator'"'"'s and is reported rather than failed' "$removed")). $extra"
  fi
}

# Re-baseline the live session set, WITH A STATED REASON, and never automatically.
#
# `SI-1` made the isolation check compare the whole live session-name set, which means it fires on any
# change — including one the operator legitimately makes. That happened: `dt-ansiFinalCompactionAndCloseout`
# was closed by the operator, and every section after that failed `ISOLATION-*` on a TRUE POSITIVE.
#
# The check cannot tell "a section leaked a session" from "the operator closed one", and it must not try:
# a control that guesses which changes are fine is a control that eventually excuses the wrong one. So the
# resolution is human, and the only thing mechanised is that it CANNOT BE SILENT — every re-baseline appends
# a row naming who, why, and exactly what moved. An unexplained baseline change is then visible as a missing
# row rather than as nothing at all, which is the whole "absence is never success" discipline applied to the
# control's own maintenance.
it_rebaseline_live_tmux() {     # it_rebaseline_live_tmux <reason>
  local reason="${1:?a re-baseline needs a reason — an unexplained one destroys the control}"
  local log="$IT_ROOT/live-tmux-rebaselines.tsv" now before after removed added
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  before="$([ -f "$LIVE_TMUX_SNAPSHOT" ] && cat "$LIVE_TMUX_SNAPSHOT" || echo)"
  after="$(it_live_tmux_sessions)"
  removed="$(comm -23 <(printf '%s\n' "$before") <(printf '%s\n' "$after") | tr '\n' ' ')"
  added="$(comm -13 <(printf '%s\n' "$before") <(printf '%s\n' "$after") | tr '\n' ' ')"
  [ -f "$log" ] || printf 'when\treason\tremoved\tadded\n' > "$log"
  printf '%s\t%s\t%s\t%s\n' "$now" "$reason" "${removed:-none}" "${added:-none}" >> "$log"
  printf '%s\n' "$after" > "$LIVE_TMUX_SNAPSHOT"
  printf 'live-tmux baseline re-established (%s sessions). removed:%s added:%s\n' \
         "$(printf '%s' "$after" | grep -c .)" "${removed:-none}" "${added:-none}"
}

# Classify a live-session delta instead of comparing it for equality. Prints "<verdict>|<detail>", where
# verdict is OK, NOTE or FAIL.
#
# `it_assert_no_new_claude` already does exactly this for the OTHER baseline, and says why (`SI-25`): do
# not make the check cleverer about WHETHER a change is acceptable — attribute it mechanically and report
# what cannot be attributed. The tmux half never got that treatment, so a coordinator of the operator's
# finishing normally produced the same signal as this harness killing live work. Measured: §B's `B3`, a
# case that dispatches nothing and whose own checks report "§B launches no process at all", failed on
# `claude_mor_design_chinmay` appearing mid-run.
#
# The asymmetry is INVERTED from the claude check, and deliberately. There, an ADDITION is the violation
# (a section spawned a process). Here, a REMOVAL is (the product killed live work), while an addition can
# only be ours if it carries our own prefix.
it_classify_session_delta() {   # it_classify_session_delta <baseline> <after>
  local baseline="$1" after="$2" appeared vanished leaked killed
  appeared="$(comm -13 <(printf '%s\n' "$baseline" | sort) <(printf '%s\n' "$after" | sort) | grep -v '^$')"
  vanished="$(comm -23 <(printf '%s\n' "$baseline" | sort) <(printf '%s\n' "$after" | sort) | grep -v '^$')"

  # A harness-prefixed name is a failure in EITHER direction, and the first version of this function only
  # checked one. The harness never puts an `itfleet-*` session on the DEFAULT server at all, so such a name
  # appearing means it leaked there, and such a name VANISHING from the baseline means either it leaked and
  # was cleaned up, or the baseline is a fiction. Neither is ever legitimate.
  #
  # Checking only `appeared` silently disabled `W1-7`, the suite's own negative control: it doctors the
  # baseline by ADDING `itfleet-W1-a-session-that-does-not-exist`, which surfaces as VANISHED, fell through
  # to the NOTE branch, and passed. W1-7's failure text is the correct reading — "every isolation PASS in
  # this file is unfalsifiable". A control that no longer controls is worse than no control, and this one
  # was broken by the very change that was supposed to make the check more honest.
  local prefix="^(${TMUX_PREFIX:-itfleet-}|itfleet-)"
  leaked="$(printf '%s\n' "$appeared" | grep -E "$prefix" | tr '\n' ' ')"
  local stray
  stray="$(printf '%s\n' "$vanished" | grep -E "$prefix" | tr '\n' ' ')"
  killed="$(printf '%s\n' "$vanished" | grep -E '^dt-' | tr '\n' ' ')"

  if [ -n "${leaked// /}" ]; then
    printf 'FAIL|a session THIS HARNESS could have created appeared on the LIVE server: %s. The harness works on socket %s and must never reach the default one.\n' \
      "$leaked" "${IT_TMUX_SOCKET:-?}"
    return 0
  fi
  if [ -n "${stray// /}" ]; then
    printf 'FAIL|a harness-prefixed session was in the live baseline and is now gone: %s. The harness never creates one on the default server, so either it leaked there and was cleaned up, or the baseline is a fiction — both are failures.\n' \
      "$stray"
    return 0
  fi
  if [ -n "${killed// /}" ]; then
    printf 'FAIL|a dt- session DISAPPEARED from the live server during this section: %s. Live work vanishing mid-run cannot be attributed to anyone else, so it is charged here.\n' \
      "$killed"
    return 0
  fi
  if [ -n "${appeared// /}" ] || [ -n "${vanished// /}" ]; then
    printf 'NOTE|operator activity, not this section: appeared=[%s] vanished=[%s]. Neither carries a harness prefix and no dt- session was lost, so this is the box being used while the suite ran.\n' \
      "$(printf '%s' "$appeared" | tr '\n' ' ')" "$(printf '%s' "$vanished" | tr '\n' ' ')"
    return 0
  fi
  printf 'OK|live tmux session set byte-identical\n'
}

# The contract. Called on entering and leaving every section.
#
# `SI-1`: the tmux half of this check used to be `grep -q '^dt-'` — it asked only whether a `dt-` session
# existed, so a NEW session on the live server raised nothing. That is precisely how §M's
# `itfleet-M-worker` reached the live server unremarked, and it means every earlier `ISOLATION-*` PASS
# proves "no dt- session touched" and NOT "the live server is unchanged". Now the full name set is
# compared, so appearing and disappearing sessions are both caught, whatever they are called.
it_assert_isolation() {
  local tag="$1" now sessions
  now="$( { find ~/.claude-dispatch-board ~/.claude-ws-pool -type f -print0 2>/dev/null | sort -z | xargs -0 sha256sum; } )"
  # ESTABLISH on the first call, exactly as the tmux baseline below does. Both are snapshots of THIS BOX —
  # the operator's pdispatch stores and the live session set — so neither can be committed: another checkout
  # has different sessions and would fail on its first run for a reason that has nothing to do with the
  # product. Before this branch existed the stores comparison had no establishing case at all, so a fresh
  # checkout could never pass it; the tmux half had been given one and the stores half had not.
  #
  # A SKIP and not a PASS, for the reason already written one branch down: an establishing call COMPARED
  # NOTHING, and reporting it as a pass is "absence is never success" wearing the harness's own badge.
  #: NOT an early return. Returning here on a first run establishes the stores baseline and skips the tmux
  #: half entirely, leaving the tmux baseline unset — after which `W1-7`'s negative control repoints a
  #: baseline that does not exist and `W1-7-restored` fails. Measured, not reasoned about. The establishing
  #: fact is carried into whichever row this call ends up emitting instead.
  local stores_note=""
  if [ ! -f "$LIVE_SNAPSHOT" ]; then
    printf '%s\n' "$now" > "$LIVE_SNAPSHOT"
    stores_note="live-STORES baseline ESTABLISHED on this call ($(printf '%s' "$now" | grep -c . ) file(s) hashed), so the stores half is vacuous here and binds from the next call on. "
  elif [ "$now" != "$(cat "$LIVE_SNAPSHOT")" ]; then
    it_fail "ISOLATION-$tag" "" "THE LIVE STORES CHANGED — the ANSI coordinator runs on them. Aborting."
    return 1
  fi
  sessions="$(it_live_tmux_sessions)"
  # Recorded, never touched. Per section rather than one shared file: two sections running concurrently
  # would otherwise both write it, and a register with two writers is the defect this whole wave is about.
  if tmux ls 2>/dev/null | grep -q '^dt-'; then
    tmux ls 2>/dev/null | grep '^dt-' > "$IT_ROOT/dt-sessions-seen${SECTION:+-$SECTION}.txt"
  fi
  if [ ! -f "$LIVE_TMUX_SNAPSHOT" ]; then
    printf '%s\n' "$sessions" > "$LIVE_TMUX_SNAPSHOT"
    # Not a PASS. This call ESTABLISHED the baseline and therefore compared nothing, and a baseline-setting
    # call reported as a pass is the "absence is never success" defect wearing the harness's own badge.
    it_skip "ISOLATION-$tag" "fleet/it/live-tmux-sessions.txt" \
            "${stores_note}live-session baseline ESTABLISHED on this call ($(printf '%s' "$sessions" | grep -c . ) sessions), so the tmux comparison is vacuous here; it binds from the next call on"
    return 0
  fi
  local classified verdict detail
  classified="$(it_classify_session_delta "$(cat "$LIVE_TMUX_SNAPSHOT")" "$sessions")"
  verdict="${classified%%|*}"; detail="${classified#*|}"
  if [ "$verdict" = FAIL ]; then
    it_fail "ISOLATION-$tag" "fleet/it/live-tmux-sessions.txt" "${stores_note}${detail}"
    return 1
  fi
  if [ "$verdict" = NOTE ]; then
    # Recorded on the PASS row rather than swallowed: the run stays attributable, and `verify` reads this
    # to decide between RED and INCONCLUSIVE.
    it_pass "ISOLATION-$tag" "fleet/it/live-tmux-sessions.txt" "${stores_note}${detail}"
    return 0
  fi
  it_pass "ISOLATION-$tag" "" \
          "${stores_note}live stores byte-identical; live tmux session set byte-identical ($(printf '%s' "$sessions" | grep -c . ) sessions, incl. $(printf '%s' "$sessions" | grep -c '^dt-') dt-); section work is on socket $IT_TMUX_SOCKET"
}

# Kills only this section's sessions, on the private server, by EXACT name. Two changes from the form that
# shipped: the server is `-L $IT_TMUX_SOCKET` (so a cleanup can no longer reach the live server at all),
# and the target carries `=` — `kill-session -t itfleet-N-pre-a` resolves BY PREFIX and destroyed a live
# `itfleet-N-pre-ab` in `N7c`. That defect was fixed in the product and left standing in the harness that
# judges it (`SI-2`).
it_cleanup_tmux() { it_tmux ls -F '#{session_name}' 2>/dev/null | grep "^${TMUX_PREFIX}" \
                    | while read -r s; do it_tmux kill-session -t "=$s" 2>/dev/null; done; true; }
