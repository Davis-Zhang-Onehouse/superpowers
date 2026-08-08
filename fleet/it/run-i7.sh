#!/usr/bin/env bash
# Run: bash fleet/it/run-i7.sh
#
# §i7 — FI-208: THE DIM GHOST SUGGESTION IS NOT TEXT A HUMAN TYPED.
#
# Claude Code draws a model-generated suggestion into an EMPTY input box in SGR 2 (DIM). `session.py`
# captured the pane WITHOUT `-e`, so tmux stripped that attribute before any predicate saw the string —
# and from there a suggestion and a message somebody typed and never sent are the SAME BYTES.
#
# The measured harm, on a live effort, over ten and a half hours:
#   * `pane-guard` answered `10 queued-text` for every idle worker — every box alarm a false positive;
#   * `close` REFUSED a finished worker, naming a remedy of *"the text is submitted or cleared"* for a
#     box with nothing in it to clear. A refusal whose remedy cannot be performed is not a guard, it is a
#     toll: the only exit was `--force`, which the refusal itself frames as a last resort;
#   * "who typed that?" was investigated for days over strings that had no author.
#
# WHY THIS SECTION EXISTS RATHER THAN ANOTHER UNIT CASE. The defect is in the capture ARGV, one layer
# BELOW every predicate. A case that hands a predicate a string cannot reach it, and this is measured, not
# argued: the ghost cases in `tests/test_session.py` PASS against the pre-fix source — vacuously, because
# the pre-fix `_caret_content` cannot find a caret in an escaped line at all. Only going out to a real
# tmux and coming back sees what the product sees.
#
# BOTH DIRECTIONS, OR NEITHER. Making the ghost read as empty is the easy half. Doing it in a way that
# also stops REAL queued text being seen is a worse defect than the one being closed, because a
# `send-keys` then concatenates silently onto somebody's draft — proven by execution on a private socket,
# one user turn, no separator. So i7-2 and i7-4 are the twins of i7-1 and i7-3 and they must keep passing
# unchanged. That is FI-180's rule: when a fix makes a failure stop being visible, it is not done until
# the visibility is replaced.
set -uo pipefail
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck disable=SC1091
. "$IT_ROOT/lib.sh"

#: RESULTS is redirected and the cases are owned BEFORE `it_section`, and the order is the whole point:
#: `it_section` itself calls `it_assert_isolation "<name>-enter"`, which writes a row to whatever `RESULTS`
#: names AT THAT MOMENT. Setting it afterwards sends the enter row to the shared, COMMITTED `RESULTS.tsv`
#: and the exit row to ours — so the register gained one duplicate `ISOLATION-i7-enter` per run and the
#: repo was dirty for a reason nothing in the change table explained. `run-Q.sh:44` already orders it this
#: way; I did not, and four runs proved it.
RESULTS="$IT_ROOT/RESULTS-i7.tsv"
[ -f "$RESULTS" ] || printf 'case\tverdict\tevidence\tnote\n' > "$RESULTS"
#: The ISOLATION rows are OURS too. Every other section says so — `run-A.sh:52`, `run-Q.sh:44`,
#: `run-H.sh:22`, `run-J.sh:26`, `run-m9-mutation.sh:31` — and omitting them makes a register grow one
#: duplicate row per run, forever.
it_own_cases 'i7-[0-9]+|ISOLATION-i7-(enter|exit)'

it_section i7
it_fresh_store
#: `it_section` names FLEET_HOME and the tmux server; it does NOT name FLEET_INSTANTS, so `fleet init`
#: below takes it from the AMBIENT environment. Measured, by me, on this section's first run: it inherited
#: a live coordinator's value and created four template instants inside another effort's tree. Nothing was
#: overwritten and the live record store stayed clean, but a test that writes into a live effort is the
#: same defect `i4` is chartered on, arriving from a different direction. Named here, not remembered:
#: `run-J.sh:30` already does this and the harness does not, which is how the gap survived.
export FLEET_INSTANTS="$IT_ROOT/i7/instants"; rm -rf "$FLEET_INSTANTS"; mkdir -p "$FLEET_INSTANTS"
OUT="$IT_ROOT/i7/out"; mkdir -p "$OUT"

GHOST_SESS="itfleet-i7-ghost"
TYPED_SESS="itfleet-i7-typed"

# --------------------------------------------------------------------------------------------------
# FIXTURE — the two frames, rendered into REAL panes on this section's PRIVATE server.
#
# `cat`, never `printf '<frame>'`: the frames contain `%` and backslashes and a printf format string
# would eat them. The pane then sleeps, so the frame stays on screen for the whole section.
# --------------------------------------------------------------------------------------------------
render() {                        # render <session> <frame-file>
  #: Assigned on SEPARATE lines, and that is not style. `local a="$1" b="$(f "$a")"` expands every word
  #: BEFORE `local` binds any of them, so `$a` is unbound inside the command substitution — under `set -u`
  #: the substitution fails, `b` collapses to a constant, and BOTH calls then write the same file. Caught
  #: here by measurement: the first run of this section rendered the TYPED frame into both panes, i7-1
  #: reported `10` and the report was a correct verdict about the wrong fixture.
  local sess="$1"
  local frame="$2"
  local script="$OUT/$(basename "$frame").sh"
  cat > "$script" <<EOS
#!/usr/bin/env bash
printf '\033[2J\033[H'
cat '$frame'
while :; do sleep 3600; done
EOS
  it_tmux new-session -d -s "$sess" -x 200 -y 24 "bash $script"
}
render "$GHOST_SESS" "$IT_ROOT/fixtures/i7-ghost-box.frame"
render "$TYPED_SESS" "$IT_ROOT/fixtures/i7-typed-box.frame"
sleep 1

# The fixture is asserted before anything is concluded from it, and asserted so that it DISCRIMINATES.
# `J8`'s lesson was that a collapsed quote killed the session and both refusals then meant nothing; the
# first run of THIS section taught the sharper half — a fixture bug rendered the TYPED frame into both
# panes and every case still produced a plausible verdict, because "a caret is on screen" is true of both
# frames. So each pane is checked for the thing that makes it ITSELF: SGR 2 on the ghost pane, the probe
# token on the typed pane, and the two panes must not be showing the same screen.
it_tmux capture-pane -p -e -t "=$GHOST_SESS:" > "$OUT/i7-ghost-capture.raw" 2>&1
it_tmux capture-pane -p    -t "=$GHOST_SESS:" > "$OUT/i7-ghost-capture.plain" 2>&1
it_tmux capture-pane -p -e -t "=$TYPED_SESS:" > "$OUT/i7-typed-capture.raw" 2>&1
FIXTURE_OK=1
FIXTURE_WHY=""
grep -q '❯' "$OUT/i7-ghost-capture.plain" \
  || { FIXTURE_OK=0; FIXTURE_WHY="$FIXTURE_WHY; the ghost pane shows no input box at all"; }
grep -q $'\x1b\\[2m' "$OUT/i7-ghost-capture.raw" \
  || { FIXTURE_OK=0; FIXTURE_WHY="$FIXTURE_WHY; the ghost pane carries NO SGR 2, so it is not the ghost frame"; }
grep -q 'REAL-TYPED-TEXT-GAMMA' "$OUT/i7-typed-capture.raw" \
  || { FIXTURE_OK=0; FIXTURE_WHY="$FIXTURE_WHY; the typed pane does not carry the probe token"; }
grep -q 'REAL-TYPED-TEXT-GAMMA' "$OUT/i7-ghost-capture.raw" \
  && { FIXTURE_OK=0; FIXTURE_WHY="$FIXTURE_WHY; BOTH panes are showing the TYPED frame — the two cases would not be measuring different things"; }

if [ "$FIXTURE_OK" != 1 ]; then
  for c in i7-1 i7-2 i7-3 i7-4 i7-5; do
    it_fail "$c" "fleet/it/i7/out/i7-ghost-capture.raw" \
      "THE FIXTURE DOES NOT DISCRIMINATE${FIXTURE_WHY}. Every verdict below would be about the wrong screen, which is a false pass wearing a real exit code"
  done
  it_cleanup_tmux; exit 1
fi

# --------------------------------------------------------------------------------------------------
# i7-5 — THE CAPTURE ASKS TMUX FOR THE ATTRIBUTE. The root cause, asserted at the only layer that has it.
#        Placed first because every case below is vacuous if the attribute never arrives.
# --------------------------------------------------------------------------------------------------
guard_of() {                      # guard_of <session> -> prints the porcelain, returns the code
  fleet pane-guard --pane "$1" --porcelain 2>&1; return $?
}
fleet pane-guard --pane "$GHOST_SESS" --porcelain > "$OUT/i7-guard-ghost.out" 2>&1
GHOST_RC=$?
fleet pane-guard --pane "$TYPED_SESS" --porcelain > "$OUT/i7-guard-typed.out" 2>&1
TYPED_RC=$?

# Does what the PRODUCT captured carry the attribute? Asked of the product's own probe, not of tmux —
# tmux answering `-e` correctly proves nothing about the argv fleet builds.
python3 - "$OUT/i7-probe-capture.raw" "$GHOST_SESS" <<'PY'
import os, pathlib, sys
sys.path.insert(0, os.path.join(os.environ["PWD"], "src"))
from fleet.session import default_probes
text = default_probes(tmux_socket=os.environ["FLEET_TMUX_SOCKET"]).capture_pane(sys.argv[2])
pathlib.Path(sys.argv[1]).write_text(text if text is not None else "<CAPTURE FAILED>")
PY
if grep -q $'\x1b\\[2m' "$OUT/i7-probe-capture.raw" 2>/dev/null; then
  it_pass i7-5 "fleet/it/i7/out/i7-probe-capture.raw" \
    "the capture fleet's OWN probe takes carries SGR 2 (DIM). That is the bit that separates the TUI's ghost suggestion from a message a human typed, and it used to be discarded at the capture site — below unsubmitted(), below pane-guard, below close's refusal and below every external monitor, where nothing above could recover it or even tell it was gone"
else
  it_fail i7-5 "fleet/it/i7/out/i7-probe-capture.raw" \
    "fleet's own capture carries NO SGR 2 attribute, so the ghost and typed text are the same bytes to every consumer (FI-208). Compare i7-ghost-capture.raw, which has it, with i7-ghost-capture.plain, which does not"
fi

# --------------------------------------------------------------------------------------------------
# i7-1 — DECOY A: A DIM BODY IS AN EMPTY BOX.               (this is the case that FAILS on the defect)
# --------------------------------------------------------------------------------------------------
# ⚠️ `0` ONLY, not `0 or 12`. The first version of this case accepted either, and a review showed that
# made it undiscriminating: `12 not-claude` is the code the close-out contract treats as permission to
# tear the pane down, so a band of `0-or-12` passes whether the box was correctly read as empty OR the
# pane stopped being recognised as a claude at all — the second being the regression `shift+tab to cycle`
# was added to prevent. With the band widened, deleting that marker broke nothing. It does now.
if [ "$GHOST_RC" = 0 ]; then
  it_pass i7-1 "fleet/it/i7/out/i7-guard-ghost.out" \
    "a DIM-wrapped body classifies as an EMPTY input box on a pane still recognised as claude (pane-guard=0). Classified by ATTRIBUTE, not by matching the text: the suggestion is model-generated prose, so a denylist of suggestion strings could never have been completed. Asserting 0 rather than '0 or 12' is deliberate — 12 would mean the ghost stopped being read as text AND the pane stopped being read as claude, which is a different, more dangerous answer wearing a passing grade"
elif [ "$GHOST_RC" = 10 ]; then
  it_fail i7-1 "fleet/it/i7/out/i7-guard-ghost.out" \
    "pane-guard returned 10 queued-text for a box that is EMPTY: its body is drawn entirely in SGR 2, Claude Code's own suggestion. That is FI-208 and every box alarm it produces is a false positive"
elif [ "$GHOST_RC" = 12 ]; then
  it_fail i7-1 "fleet/it/i7/out/i7-guard-ghost.out" \
    "pane-guard returned 12 not-claude. The ghost is no longer read as text — but the pane is no longer read as a CLAUDE either, and 12 is the code that authorises tearing it down. A live IDLE Claude Code pane matches none of the legacy CLAUDE_MARKERS, so the ghost was the only thing holding this up; the fix must supply the replacement marker (FI-180). Check cli.CLAUDE_MARKERS still carries 'shift+tab to cycle'"
else
  it_fail i7-1 "fleet/it/i7/out/i7-guard-ghost.out" \
    "pane-guard returned an unexpected $GHOST_RC for the ghost pane; wanted 0"
fi

# --------------------------------------------------------------------------------------------------
# i7-6 — THE THIRD CONTROL, required by the coordinator 2026-08-08T02:39Z after it accepted the
#        correction: A BOX HOLDING REAL TYPED TEXT ON AN ESC-PREFIXED ROW MUST CLASSIFY NON-EMPTY.
#
#        This is the false-safe that `-e` alone would have caused. The live caret row is `ESC[39m` then
#        the caret, so a text-only `line.strip()[0]` sees `ESC`, never finds the box, and reports every
#        pane as empty — `0 safe` over a real draft. i7-2 does not cover it: its frame is the same shape,
#        so this asserts the PROPERTY rather than trusting the fixture to carry it.
# --------------------------------------------------------------------------------------------------
python3 - "$OUT/i7-esc-caret.out" <<'PY'
import os, pathlib, sys
sys.path.insert(0, os.path.join(os.environ["PWD"], "src"))
from fleet.session import Probes, SessionLayer
rows = []
sessions = SessionLayer(Probes(lambda: [], lambda n: "", lambda n: False,
                               lambda *a: None, lambda n: None))
CASES = [
    ("attribute BEFORE the caret", "\x1b[39m❯\xa0REAL-TYPED-TEXT-GAMMA", "REAL-TYPED-TEXT-GAMMA"),
    ("attribute AFTER the caret",  "❯\xa0\x1b[39mREAL-TYPED-TEXT-GAMMA", "REAL-TYPED-TEXT-GAMMA"),
    ("truecolor body",  "\x1b[39m❯\xa0\x1b[38;2;136;192;208mREAL-TYPED-TEXT-GAMMA",
     "REAL-TYPED-TEXT-GAMMA"),
    ("all-DIM body is still empty", "\x1b[39m❯\xa0\x1b[2mkeep watching\x1b[0m", None),
]
bad = 0
for label, row, want in CASES:
    text = "\n".join(["output", row, "\x1b[39m\x1b[49m", "\x1b[39m\x1b[49m"])
    got = sessions.unsubmitted(text)
    ok = got == want
    bad += 0 if ok else 1
    rows.append(f"{'ok ' if ok else 'BAD'} {label:34s} -> {got!r} (wanted {want!r})")
rows.append(f"FAILURES={bad}")
pathlib.Path(sys.argv[1]).write_text("\n".join(rows) + "\n")
PY
if grep -q '^FAILURES=0$' "$OUT/i7-esc-caret.out" 2>/dev/null; then
  it_pass i7-6 "fleet/it/i7/out/i7-esc-caret.out" \
    "a box holding REAL typed text on an ESC-PREFIXED row classifies NON-EMPTY, in every escaped form measured on a live pane (attribute before the caret, after it, and a truecolor body) — while an all-DIM body still classifies EMPTY. This is the control the coordinator required after accepting that '-e alone' is a false-safe: without it, adding -e turns every 10 queued-text into 0 safe and a send-keys lands in somebody's unsent draft"
else
  it_fail i7-6 "fleet/it/i7/out/i7-esc-caret.out" \
    "A BOX WITH REAL TYPED TEXT READS EMPTY on at least one escaped caret form — see the BAD rows. Every live pane measured has an attribute adjacent to its caret, so this is not an edge case: it is the default, and its failure direction is a send concatenating onto an unsent message"
fi

# --------------------------------------------------------------------------------------------------
# i7-2 — DECOY B: REAL TYPED TEXT IS STILL SEEN, AND REPORTED VERBATIM.        (the FI-180 twin)
#        Without this, i7-1 is satisfied by a guard that has simply stopped looking.
# --------------------------------------------------------------------------------------------------
TYPED_FIELD="$(awk -F'\t' '$1=="queued_text"{print $2}' "$OUT/i7-guard-typed.out")"
if [ "$TYPED_RC" = 10 ] && [ "$TYPED_FIELD" = "REAL-TYPED-TEXT-GAMMA" ]; then
  it_pass i7-2 "fleet/it/i7/out/i7-guard-typed.out" \
    "genuinely typed text still returns 10 queued-text and the queued_text FIELD still carries it verbatim. send-keys DOES concatenate onto a draft — proven by execution, one user turn with no separator — so this guard is correct and the FI-208 fix must not weaken it. i7-1 without this case would be satisfied by a guard that had stopped looking"
else
  it_fail i7-2 "fleet/it/i7/out/i7-guard-typed.out" \
    "REAL QUEUED TEXT IS NO LONGER VISIBLE: pane-guard=$TYPED_RC queued_text='$TYPED_FIELD', wanted 10 and 'REAL-TYPED-TEXT-GAMMA'. A send here concatenates onto somebody's unsent draft"
fi

# --------------------------------------------------------------------------------------------------
# i7-3 / i7-4 — THE USER-VISIBLE HARM, END TO END: `close`'s refusal.
#               rc=10 is a number; being unable to close a finished worker is what it cost.
# --------------------------------------------------------------------------------------------------
close_case() {                    # close_case <label> <slot> <session> -> echoes the todo id
  local label="$1" slot="$2" sess="$3" inst todo
  mkdir -p "$SLOTS/$slot"
  fleet enroll --slot "$SLOTS/$slot" --porcelain > "$OUT/i7-enroll-$label.out" 2>&1
  inst="$(fleet init --base 00000000 --name "$label" --porcelain 2>&1 \
          | awk -F'\t' '$1=="path"{print $2}')"
  fleet resume --instant "$inst" --slot "$slot" --tmux "$sess" --porcelain \
    > "$OUT/i7-resume-$label.out" 2>&1
  awk -F'\t' '$1=="todo_id"{print $2}' "$OUT/i7-resume-$label.out"
}
GHOST_TODO="$(close_case i7ghost wsG "$GHOST_SESS")"
TYPED_TODO="$(close_case i7typed wsT "$TYPED_SESS")"

if [ -z "$GHOST_TODO" ] || [ -z "$TYPED_TODO" ]; then
  it_fail i7-3 "fleet/it/i7/out/i7-resume-i7ghost.out" \
    "no record was created (ghost='$GHOST_TODO' typed='$TYPED_TODO'), so a close verdict here would be about a missing record and not about a pane"
  it_fail i7-4 "fleet/it/i7/out/i7-resume-i7typed.out" "same missing fixture as i7-3"
else
  fleet close --id "$GHOST_TODO" --dry-run > "$OUT/i7-close-ghost.out" 2>&1
  GC=$?
  fleet close --id "$TYPED_TODO" --dry-run > "$OUT/i7-close-typed.out" 2>&1
  TC=$?

  if [ "$GC" = 0 ]; then
    it_pass i7-3 "fleet/it/i7/out/i7-close-ghost.out" \
      "close no longer refuses a worker whose box holds only the DIM suggestion (exit 0, would-close true). Before the fix this was exit 4 refused queued-text, naming a remedy of 'the text is submitted or cleared' that CANNOT BE PERFORMED because there is no text — leaving --force as the only exit and turning a guard into a toll"
  else
    it_fail i7-3 "fleet/it/i7/out/i7-close-ghost.out" \
      "close exited $GC for a pane whose box is EMPTY. If that is 4/queued-text, read its stated remedy against the box: it asks for text to be submitted or cleared and there is none, so nobody can ever clear this refusal (FI-208)"
  fi

  if [ "$TC" = 4 ] && grep -q 'REAL-TYPED-TEXT-GAMMA' "$OUT/i7-close-typed.out"; then
    it_pass i7-4 "fleet/it/i7/out/i7-close-typed.out" \
      "close still REFUSES a pane holding genuinely typed text (exit 4, queued-text, the text quoted back), and the refusal still names --force. FI-9: text left in a box is what a rate-limit auto-resume concatenates with its retry and sends. i7-3 alone would have removed this protection rather than corrected it"
  else
    it_fail i7-4 "fleet/it/i7/out/i7-close-typed.out" \
      "close exited $TC for a pane holding REAL unsubmitted text; wanted 4 with the text quoted. The FI-208 fix has blinded the close guard, which is worse than the false positive it replaced"
  fi
fi

it_cleanup_tmux
it_assert_isolation i7-exit
exit "${IT_FAILED:-0}"
