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
#: The THIRD live resource this harness can damage, and the one `it_assert_isolation` could not see.
#: `I2-11`/`FI-196`: `it_section` sandboxes FLEET_HOME and the tmux server, so the record store and the
#: session set were both provably isolated — and every `fleet init` still wrote its FOLDER into whatever
#: tree the CALLER's `$FLEET_INSTANTS` named, because `cli.default_context` resolved the instants directory
#: from the environment and `--home` never scoped it. Ten strays reached a live effort tree that way and
#: one of them came up believing it WAS the coordinator, while the isolation assertion recorded PASS on
#: every call. The contamination was structurally unobservable to the check that exists to catch it.
#: PER SECTION, not one shared file — the same rule `dt-sessions-seen` already states two functions
#: down: *"two sections running concurrently would otherwise both write it, and a register with two
#: writers is the defect this whole wave is about."* It binds harder here than for the tmux baseline,
#: because this one ADVANCES on an attributed NOTE and therefore writes on most calls rather than only
#: on the establishing one. `it_section` repoints it; this value is what a call before any section uses.
LIVE_INSTANTS_SNAPSHOT="$IT_ROOT/live-instants.txt"
#: `$FLEET_INSTANTS` AS THIS FILE WAS SOURCED — before any `it_section` rewrites it. That is precisely the
#: operator's ambient value, inherited from the SHARED tmux server, and it is the tree the ten strays
#: landed in. Captured here rather than read later, because after `it_section` the variable names our own
#: sandbox and the vector would have erased itself from the evidence.
IT_AMBIENT_INSTANTS="${FLEET_INSTANTS:-}"
#: And the ambient `$FLEET_HOME` for the same reason one line up. With `FLEET_INSTANTS` UNSET — which is
#: the state of a clean box, and the state this fix is meant to make safe — the product derives
#: `$FLEET_HOME/instants`, so that is where a leak would go and it must be watched or the check watches
#: NOTHING and reports a PASS about it. `SI-1`'s shape, found in review before it shipped.
IT_AMBIENT_HOME="${FLEET_HOME:-}"
#: The instants half's FAIL marker, a CONSTANT because a control asserts on it. `W1-11` used to grep
#: `^ISOLATION-W1-11-injected\tFAIL` alone — but `it_assert_isolation` also FAILs for the stores half
#: and the tmux half, so a live-stores change during the run would have made the instants decoy pass
#: for a reason that has nothing to do with instants. A control that can pass on the wrong evidence is
#: not a control. Found in review.
IT_INSTANTS_FAIL_MARK="A FOLDER THIS SECTION NAMED IS IN A LIVE INSTANTS TREE"

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
  # SANDBOXED BY CONSTRUCTION, and this line is the whole point of the fix. `it_section` already gave the
  # section its own store, its own slots and its own tmux SERVER; the instants directory was the one shared
  # resource it left to the caller's environment. FIFTEEN runners remembered to export it and SIX did not —
  # `run-Q run-all run-e9-leak run-group5 run-m9-mutation run-w1` — and `run-group5.sh` is the one that
  # creates instants (`:324 :556 :1231 :1328 :1533`, named `l7probe mprobe m12probe nprobe nOwned`, which
  # is 5 of the 5 stray names release-verify 0.3.9 minted). A runner could be exposed by FORGETTING, and a
  # guarantee you have to remember is the failure mode this whole wave keeps paying for.
  #
  # `$FLEET_HOME/instants` and NOT `$EV/instants`, and the difference is a REGRESSION I measured rather than
  # a preference. `$FLEET_HOME/instants` is exactly what `cli.default_context` DERIVES when nothing names the
  # directory, so on a box with `FLEET_INSTANTS` unset this line changes nothing at all — it makes the
  # existing default explicit, which is what stops an ambient value overriding it. Pointing it at `$EV`
  # instead moved the directory, and `run-group5.sh` reads the derived path directly (`:1232` and `:1534`,
  # `ls "$FLEET_HOME/instants"`): §M failed with *"cannot access .../M/home/instants: No such file or
  # directory"*. A sandbox that relocates what it is sandboxing is a second defect wearing the fix's badge.
  #
  # Set BEFORE the assertion below, so a section is already sandboxed on the call that establishes the
  # baseline. The eleven runners that name `$EV/instants` for themselves two lines later still override it;
  # they are unaffected either way.
  export FLEET_INSTANTS="$FLEET_HOME/instants"
  mkdir -p "$FLEET_INSTANTS"
  # This section's OWN instants baseline. Scoping it to the section is also what makes the comparison mean
  # what its rows claim: "did anything appear in a live tree BETWEEN THIS SECTION'S enter AND ITS leave".
  LIVE_INSTANTS_SNAPSHOT="$IT_ROOT/live-instants-$SECTION.txt"
  rm -f "$LIVE_INSTANTS_SNAPSHOT"
  # The section's register of every instantName it ASKED the product to create. It is what lets the
  # isolation assertion tell OUR escape from the operator dispatching into their own tree while we run —
  # without it the check either misses the defect or cries wolf, and a check that cries wolf gets ignored.
  IT_ASKED_NAMES="$EV/it-asked-names.txt"
  : > "$IT_ASKED_NAMES"
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
  # `$FLEET_INSTANTS` is `$FLEET_HOME/instants`, so the `rm -rf` above takes the sandboxed instants
  # directory with it and the guarantee `it_section` just made evaporates for the rest of the section.
  # Three callers do not export a FLEET_INSTANTS of their own — run-I.sh, run-Q.sh, run-i7.sh — so this is
  # not theoretical. Found in review, not in the field.
  mkdir -p "${FLEET_INSTANTS:-$FLEET_HOME/instants}"
}

# Never a bare `fleet` on PATH — FLEET_HOME must be explicit.
#
# The wrapper records every instantName this section ASKS for and touches nothing else: argv is read, both
# streams and the exit code pass through untouched. That matters — §A parses `--porcelain` stdout
# byte-for-byte and several sections branch on `$?`, so a wrapper that captured stdout to inspect it would
# change what the suite measures in order to measure it.
fleet() {
  if [ -n "${IT_ASKED_NAMES:-}" ]; then
    local _prev="" _a
    for _a in "$@"; do
      case "$_prev" in --name|--title) printf '%s\n' "$_a" >> "$IT_ASKED_NAMES" ;; esac
      _prev="$_a"
    done
  fi
  python3 -m fleet.cli "$@"
}

it_pass() { printf '%s\tPASS\t%s\t%s\n' "$1" "${2:-}" "${3:-}" >> "$RESULTS"; printf 'PASS %s %s\n' "$1" "${3:-}"; }
# shellcheck disable=SC2034  # read by each runner's own exit gate (e.g. run-G.sh) after lib.sh is sourced in
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
                  printf '%s %s\n' "$(sha256sum "$f" 2>/dev/null | cut -d' ' -f1 || echo dir)" \
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

# Classify a claude-pid delta instead of comparing counts. Prints "<verdict>|<detail>", verdict OK or FAIL.
#
# `SI-25` again, and this time in the ADDITION direction. §B, §C and §E compared `pgrep -x claude | wc -l`
# before and after; that count moves for a reason no section can cause, and consecutive release gates died
# on it:
#
#     ISOLATION-B-claude-count  pgrep -x claude went 13 -> 14; no claude may launch outside §P
#     ISOLATION-C-claude-count  pgrep -x claude went 14 -> 13; §C must launch none
#     ISOLATION-E-claude-count  pgrep -x claude went 13 -> 14; no claude may launch outside §P
#
# +1 then -1 is not a launch. `pgrep -x` matches on `comm`, and between `fork()` and `exec()` a child
# carries its PARENT's `comm` — so every tool call any live agent session makes puts a process named
# `claude` on this box for a few hundred milliseconds. Measured directly: against a 9-process baseline,
# pids 1158926 and 1162691 appeared for ~630ms each, exactly during three deliberate tool calls. On a box
# where other operators are working those transients are continuous, and a count check fires on whichever
# section boundary one happens to land in — which is a coin toss, not a control.
#
# The resolution is the one this file has already reached twice: do not make the check cleverer about
# WHETHER a change is acceptable — attribute it mechanically and report what could not be attributed. A
# claude a SECTION launched has its cwd in a slot or instant under `$INSTANT`, because dispatch starts a
# worker in the slot it leased. Anything else is somebody else's session, or a fork already gone by the
# time it could be asked. Neither is this section's to fail on.
#
# The assertion the contract actually states — "no claude is launched outside §P" — is NOT weakened: a real
# leak is still alive when the check runs, so its cwd is readable, and it still FAILS.
it_classify_claude_delta() {    # it_classify_claude_delta <before-pids> <after-pids>
  local before="$1" after="$2" added removed mine foreign pid cwd
  added="$(comm -13 <(printf '%s\n' "$before") <(printf '%s\n' "$after") | tr '\n' ' ')"
  removed="$(comm -23 <(printf '%s\n' "$before") <(printf '%s\n' "$after") | tr '\n' ' ')"
  mine=""; foreign=""
  for pid in $added; do
    if it_pid_cwd_inside_instant "$pid"; then
      mine="$mine $pid"
    else
      cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null | sed "s|$HOME|~|")"
      foreign="$foreign $pid(${cwd:-gone-before-it-could-be-read})"
    fi
  done

  if [ -n "${mine// /}" ]; then
    printf 'FAIL|a claude process launched BY THIS SECTION appeared: pid(s)%s, with a cwd inside this instant. No section outside §P may launch one\n' "$mine"
    return 0
  fi
  printf 'OK|no claude was launched by this section (%s live before, %s after)' \
         "$(printf '%s' "$before" | grep -c .)" "$(printf '%s' "$after" | grep -c .)"
  [ -n "${foreign// /}" ] && printf '. %s claude pid(s) appeared with a cwd OUTSIDE this instant —%s— which a section cannot cause; on a shared box most are fork-before-exec children of another live agent session, named `claude` only until they exec. Reported, not charged here' \
         "$(printf '%s' "$foreign" | wc -w)" "$foreign"
  [ -n "${removed// /}" ] && printf '. pid(s)%s EXITED during the run, which is the operator'"'"'s own and is reported rather than failed' "$removed"
  printf '\n'
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
# The LIVE instants directories — the ones this harness must never write into. Derived, never hardcoded:
#
#   1. `$IT_AMBIENT_INSTANTS`, the caller's own `$FLEET_INSTANTS` as lib.sh was sourced. This is the
#      measured vector: the shared tmux server exports it globally, so `release-verify` inherits the FIRST
#      effort's tree and hands it to the suite through `env=dict(os.environ, …)`.
#   2. `$HOME/.fleet/instants`, which is where a `fleet` with no `$FLEET_INSTANTS` lands by default and is
#      a real store on this box.
#
# Anything under `$IT_ROOT` is OURS and is excluded: the section sandbox is not a live tree, and watching
# it would turn every legitimate case into a failure.
it_live_instants_roots() {
  local root
  for root in "$IT_AMBIENT_INSTANTS" "${IT_AMBIENT_HOME:+$IT_AMBIENT_HOME/instants}" "$HOME/.fleet/instants"; do
    [ -n "$root" ] || continue
    [ -d "$root" ] || continue
    case "$(cd "$root" && pwd -P)/" in "$IT_ROOT"/*) continue ;; esac
    printf '%s\n' "$(cd "$root" && pwd -P)"
  done | sort -u
}

# One line per entry, `<full path>\t<basename>` — `find -printf '%p\t%f\n'`. Names only — never content or mtimes. A live effort tree is
# WRITTEN CONTINUOUSLY by the instants living in it, so hashing it the way the stores half hashes
# `~/.claude-dispatch-board` would fail on every call for reasons that have nothing to do with this
# harness. The question here is narrower and answerable: *did a FOLDER APPEAR OR VANISH.*
it_instants_manifest() {
  local root
  it_live_instants_roots | while read -r root; do
    find "$root" -maxdepth 1 -mindepth 1 -type d -printf '%p\t%f\n' 2>/dev/null
  done | sort
}

#: `-append-<name>` tail of an instant folder, lowercased and dashless — the form in which a folder name
#: can be compared with what a runner ASKED for. `identity.camel()` only changes case and separators, so
#: this comparison is exact under it: `--name nOwned` produced `…-append-nowned` in `run-group5.sh:1533`.
it_instant_name_tail() {
  printf '%s' "$1" | sed -E 's/^[0-9]{8}-[0-9]{8}-(inflight|complete|abort)-(append|compact)-//' \
                   | tr -d -- '_-' | tr '[:upper:]' '[:lower:]'
}

# THE ATTRIBUTION. An entry that appeared in (or vanished from) a live tree is charged to THIS SECTION only
# when its name is one this section asked the product to create; anything else is the operator using their
# own box and is recorded as a NOTE.
#
# The asymmetry is deliberate and it is the opposite of the tmux half's. There, an ADDITION is ours only if
# it carries our prefix, because sessions are cheap and the operator's come and go. Here a name we asked
# for, appearing in a tree we do not own, IS the defect — there is no other way for it to get there — so it
# is a FAIL in BOTH directions: appearing means we minted a stray, and vanishing means we renamed or
# destroyed one, which is worse.
it_classify_instants_delta() {   # it_classify_instants_delta <baseline> <after>
  local baseline="$1" after="$2" appeared vanished ours="" others="" line entry tail asked=" " n
  appeared="$(comm -13 <(printf '%s\n' "$baseline") <(printf '%s\n' "$after") | grep -v '^$')"
  vanished="$(comm -23 <(printf '%s\n' "$baseline") <(printf '%s\n' "$after") | grep -v '^$')"

  # The asked-for names, normalised ONCE into a space-delimited set. A `--name` value is not yet an instant
  # folder name, so it is normalised through the same tail function with a synthetic prefix — one code path
  # for both sides of the comparison, because two normalisers are two things to keep in step.
  if [ -s "${IT_ASKED_NAMES:-/dev/null}" ]; then
    while IFS= read -r n; do
      [ -n "$n" ] || continue
      asked="$asked$(it_instant_name_tail "00000000-00000000-inflight-append-$n") "
    done < "$IT_ASKED_NAMES"
    # DISTRUST ABSENCE, and this branch is here because the absence was real. The first version of
    # `it_instant_name_tail` ended `tr -d '-_'`, which `tr` reads as OPTIONS (`invalid option -- '_'`), so
    # every tail came back EMPTY and every escape was attributed to "the operator" — a check that can never
    # charge anything to itself and therefore can never fail. `W1-11` caught it before it shipped. An
    # attributor that normalises a non-empty register to nothing is broken, not reassuring, and it says so.
    if [ -z "${asked// /}" ]; then
      printf 'FAIL|THE ATTRIBUTOR IS BROKEN: %s holds %s name(s) and every one normalised to the empty string, so nothing could ever be charged to this section and this check cannot fail. Fix it_instant_name_tail before trusting any ISOLATION verdict about instants.\n' \
        "$IT_ASKED_NAMES" "$(grep -c . "$IT_ASKED_NAMES")"
      return 0
    fi
  fi

  while IFS= read -r line; do
    [ -n "$line" ] || continue
    entry="${line##*$'\t'}"
    # Only an entry that PARSES as an instantName is a candidate. Two reasons, and the second is not
    # cosmetic: a live tree may hold ordinary directories that are nobody's instant, and the membership test
    # below is a bash PATTERN substitution — a directory literally named `*` would otherwise normalise to a
    # glob, match everything in the asked-set, and raise a FAIL about a folder we never created.
    if ! [[ "$entry" =~ ^[0-9]{8}-[0-9]{8}-(inflight|complete|abort)-(append|compact)-[A-Za-z0-9]+$ ]]; then
      others="$others ${entry}"
      continue
    fi
    tail="$(it_instant_name_tail "$entry")"
    if [ -n "$tail" ] && [ "$asked" != "${asked/ $tail / }" ]; then
      ours="$ours ${line%%$'\t'*}"
    else
      others="$others ${entry}"
    fi
  done <<< "$appeared
$vanished"

  if [ -n "${ours// /}" ]; then
    printf 'FAIL|'"$IT_INSTANTS_FAIL_MARK"':%s. This section asked the product to create that instantName and the folder is outside %s, so it cannot be anyone else. That is I2-11 — the instants directory resolved from the environment rather than from the sandbox — and it is how ten strays and FI-196 happened while this very assertion recorded PASS.\n' \
      "$ours" "$IT_ROOT"
    return 0
  fi
  if [ -n "${others// /}" ]; then
    printf 'NOTE|instants appeared or vanished in a live tree and NONE carries a name this section asked for, so this is the operator using their own box:%s\n' "$others"
    return 0
  fi
  printf 'OK|live instants trees byte-identical\n'
}

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
  # --- THE THIRD HALF: the live INSTANTS directories -----------------------------------------------
  #
  # Evaluated HERE, above the tmux baseline branch, and NOT after it. That branch `return`s on a first run,
  # and the comment on it records what the last such early return cost: a half that is skipped on the
  # establishing call never binds at all. Its fact is carried into whichever row this call emits, exactly
  # like `stores_note`.
  local instants_now instants_note="" instants_classified instants_verdict instants_roots
  instants_roots="$(it_live_instants_roots | grep -c . )"
  instants_now="$(it_instants_manifest)"
  # DISTRUST ABSENCE. Zero watched trees is not "nothing changed", it is "nothing was looked at", and the
  # terminal row below would otherwise report `unchanged in 0 live tree(s)` — true, vacuous, and reading
  # exactly like a pass. On a box with FLEET_INSTANTS and FLEET_HOME both unset that is the DEFAULT state.
  if [ "$instants_roots" = 0 ]; then
    instants_note="the instants half is VACUOUS on this call: ZERO live instants trees resolved (ambient FLEET_INSTANTS=[${IT_AMBIENT_INSTANTS:-unset}], ambient FLEET_HOME=[${IT_AMBIENT_HOME:-unset}], ~/.fleet/instants absent), so it compared NOTHING and proves nothing. "
  fi
  if [ ! -f "$LIVE_INSTANTS_SNAPSHOT" ]; then
    printf '%s\n' "$instants_now" > "$LIVE_INSTANTS_SNAPSHOT"
    instants_note="${instants_note}live-INSTANTS baseline ESTABLISHED on this call ($(printf '%s' "$instants_now" | grep -c . ) folder(s) across $(it_live_instants_roots | grep -c . ) live tree(s)), so the instants half is vacuous here and binds from the next call on. "
  else
    instants_classified="$(it_classify_instants_delta "$(cat "$LIVE_INSTANTS_SNAPSHOT")" "$instants_now")"
    instants_verdict="${instants_classified%%|*}"
    if [ "$instants_verdict" = FAIL ]; then
      # The artifact is the ACTUAL per-section baseline, not the hardcoded shared name it used to be —
      # a row citing a file the comparison did not use sends the reader to the wrong evidence.
      it_fail "ISOLATION-$tag" "${LIVE_INSTANTS_SNAPSHOT#$IT_ROOT/}" "${stores_note}${instants_note}${instants_classified#*|}"
      return 1
    fi
    if [ "$instants_verdict" = NOTE ]; then
      # The baseline MOVES FORWARD on an attributed NOTE, and only there. Otherwise one operator dispatch
      # mid-run re-reports itself on every remaining call of a 24-minute suite, and a row that repeats
      # something already judged harmless is how a real one stops being read. It never moves forward on a
      # FAIL: that alarm has to keep firing until somebody clears the folder.
      printf '%s\n' "$instants_now" > "$LIVE_INSTANTS_SNAPSHOT"
      instants_note="${instants_note}${instants_classified#*|} "
    fi
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
            "${stores_note}${instants_note}live-session baseline ESTABLISHED on this call ($(printf '%s' "$sessions" | grep -c . ) sessions), so the tmux comparison is vacuous here; it binds from the next call on"
    return 0
  fi
  local classified verdict detail
  classified="$(it_classify_session_delta "$(cat "$LIVE_TMUX_SNAPSHOT")" "$sessions")"
  verdict="${classified%%|*}"; detail="${classified#*|}"
  if [ "$verdict" = FAIL ]; then
    it_fail "ISOLATION-$tag" "fleet/it/live-tmux-sessions.txt" "${stores_note}${instants_note}${detail}"
    return 1
  fi
  if [ "$verdict" = NOTE ]; then
    # Recorded on the PASS row rather than swallowed: the run stays attributable, and `verify` reads this
    # to decide between RED and INCONCLUSIVE.
    it_pass "ISOLATION-$tag" "fleet/it/live-tmux-sessions.txt" "${stores_note}${instants_note}${detail}"
    return 0
  fi
  it_pass "ISOLATION-$tag" "" \
          "${stores_note}${instants_note}live stores byte-identical; live instants trees unchanged in $(it_live_instants_roots | grep -c . ) live tree(s); live tmux session set byte-identical ($(printf '%s' "$sessions" | grep -c . ) sessions, incl. $(printf '%s' "$sessions" | grep -c '^dt-') dt-); section work is on socket $IT_TMUX_SOCKET"
}

# Kills only this section's sessions, on the private server, by EXACT name. Two changes from the form that
# shipped: the server is `-L $IT_TMUX_SOCKET` (so a cleanup can no longer reach the live server at all),
# and the target carries `=` — `kill-session -t itfleet-N-pre-a` resolves BY PREFIX and destroyed a live
# `itfleet-N-pre-ab` in `N7c`. That defect was fixed in the product and left standing in the harness that
# judges it (`SI-2`).
it_cleanup_tmux() { it_tmux ls -F '#{session_name}' 2>/dev/null | grep "^${TMUX_PREFIX}" \
                    | while read -r s; do it_tmux kill-session -t "=$s" 2>/dev/null; done; true; }
