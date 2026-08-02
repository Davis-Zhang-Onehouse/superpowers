#!/usr/bin/env bash
# §I — Review and gate.  plans/plan-6-integration-tests.md lines 202-211.
#
# The section exists for one sentence in `src/fleet/review.py`: **the ledger is `.fleet/review.json` and
# `REVIEW.md` is a VIEW of it.** In the predecessor the markdown WAS the input, and a gate regex over
# idiomatic prose blocked two genuinely-READY workers in a row — one for writing its verdict in bold
# (`OBS-15`), one for disambiguating a two-round summary heading (`OBS-19`). That is the worst direction for
# a gate to be wrong in: it refuses correct work, and the diagnostic blames a MISSING line, so the reader
# goes hunting for a problem that is not there.
#
# I5/I6/I7 are the heart of it, and they are the reason this file is written the way it is. Each one
# mutilates `REVIEW.md` in a way that a reader could not survive — deleted, replaced by prose that
# CONTRADICTS the ledger (bold `NOT-READY`, a `Round 2 of 2 (final)` heading — the exact two shapes that
# blocked `OBS-15` and `OBS-19`), replaced by a DIRECTORY — and then asserts the gate is unchanged. Plan 6's
# note on those three lines is *"any read at all would fail here"*, and that is precisely the property: not
# "the gate tolerates a damaged view" but "the gate never opens it", because a deleted file, a lying file and
# a directory-where-a-file-should-be cannot all be read successfully by the same code.
#
# THE TRAP IN "UNCHANGED", and how each of those three is made falsifiable. An assertion that a value did not
# change passes trivially against a gate that is broken into always returning the same thing. So none of
# I5/I6/I7 asserts a literal. Each one:
#   1. captures the gate's exit code AND its full reason string BEFORE touching the view — the PRE-IMAGE;
#   2. captures it TWICE, requires the two to agree, AND requires what they agree on to be a real verdict —
#      a non-empty row opening with a declared guard id, and nothing on stderr. "Unchanged" is only a claim
#      about the corruption if the answer was stable to begin with, and only a claim at all if the baseline
#      was a MEASUREMENT rather than a traceback (see `i_preimage`, which was written this way only after a
#      mutant that crashed on every query made I7 pass);
#   3. corrupts the view, re-asks, and compares byte-for-byte against that recorded pre-image; and
#   4. asserts the corruption IS STILL THERE afterwards — the gate did not quietly re-render the file it
#      stands accused of reading.
# A comparison against a recorded pre-image cannot pass vacuously. And the pre-images are deliberately not
# all the same verdict: I5 and I6 preserve an ALLOW (exit 0), I7 preserves a REFUSAL (exit 1), while I1/I2/I3
# in this same section show the gate returning 0, 1 and 2 on three different ledgers — so a gate frozen on
# any one answer fails somewhere in this file.
#
# HOW THE GATE IS ASKED. `fleet review --instant X` with NO `--verdict` records no round and — the
# load-bearing half — does not call `render()`. So interrogating the gate cannot itself recreate or repair
# the view, which a query that rendered would do, silently converting I5 into a test of nothing.
#
# Run: bash fleet/it/run-I.sh
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
# `§I` is owned too, so this run RETIRES the section-level `NOT-RUN` row rather than leaving it beside eight
# fresh PASSes. A results file that reads as both not-run and passing is the false pass the register exists
# to make impossible, and `zero NOT-RUN` cannot be expressed by annotating a row (see `it_own_cases`).
it_own_cases '§I|I[0-9]+[a-z]?|ISOLATION-I-(enter|leave)'

it_section I

# §I starts no tmux session and launches no process: every case is `fleet init` plus `fleet review` plus a
# python driver, all on the local filesystem. The cleanup is kept anyway because it costs nothing and a
# section that assumes it can never leak is a section nobody checks.
trap 'it_cleanup_tmux' EXIT
OUT="$EV/out"; rm -rf "$OUT"; mkdir -p "$OUT"
export FLEET_INSTANTS="$EV/instants"; rm -rf "$FLEET_INSTANTS"; mkdir -p "$FLEET_INSTANTS"
it_fresh_store            # a section whose verdicts depend on whether it has been run before measures nothing
TAG="i$$"

bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2

i_init() {                       # i_init <name> -> prints the instant path
  local out="$OUT/init-$1.out"
  fleet init --base 00000000 --name "$1" --porcelain > "$out" 2>&1
  awk -F'\t' '$1=="path"{print $2; exit}' "$out"
}

# THE GATE, ASKED NON-DESTRUCTIVELY. Writes three files per label — the whole porcelain (`.raw`), just the
# gate row as `guard<TAB>reason` (`.row`), and the exit code (`.rc`) — and prints the exit code.
#
# The row is what I5/I6/I7 diff. Not a substring of it: `Verdict.reason` carries the round number, the
# recorded timestamp, the covered scopes, the finding counts and the ledger path, so byte-equality of that
# string is a far stronger statement than "still exit 0" and it is what makes the pre-image comparison sharp.
i_gate() {                       # i_gate <label> <instant> [extra flags...] -> prints the exit code
  local label="$1" inst="$2"; shift 2
  fleet review --instant "$inst" --porcelain "$@" > "$OUT/$label.raw" 2>"$OUT/$label.err"
  local rc=$?
  awk -F'\t' '$1=="gate"{print $2 "\t" $4}' "$OUT/$label.raw" > "$OUT/$label.row"
  printf '%s\n' "$rc" > "$OUT/$label.rc"
  printf '%s' "$rc"
}

# The PRE-IMAGE, captured twice. Returns 0 only if the two queries agree AND the answer they agree on is a
# real verdict — see the header for why "twice", and read the next paragraph for why "real".
#
# Found by mutation-testing this very file before it was ever reported green — a build whose `gate()` reads
# `REVIEW.md` was injected on a scratch COPY of the package (never on `src/`, which the pin protects and
# other agents were editing at the time), and I5/I6/I8 duly failed while **I7 passed**. That mutant crashed
# on EVERY query, so the
# pre-image was a traceback and an EMPTY gate row, the post-image was the same traceback, they compared equal,
# and the case reported the property held on a build that did exactly the thing the case forbids. That is the
# vacuous pass this section is written against, wearing the harness's own badge — a pre-image is only a
# baseline if it is a MEASUREMENT. So the row must be non-empty, must open with one of the three declared
# guard ids, and stderr must be empty: a traceback is not a verdict and never becomes a baseline.
i_preimage() {                   # i_preimage <label> <instant>
  local label="$1" inst="$2"
  i_gate "$label-pre1" "$inst" --require-scope all >/dev/null
  i_gate "$label-pre2" "$inst" --require-scope all >/dev/null
  cmp -s "$OUT/$label-pre1.row" "$OUT/$label-pre2.row" \
    && cmp -s "$OUT/$label-pre1.rc" "$OUT/$label-pre2.rc" \
    && grep -qE '^review-(verdict|scope|undecidable)	.' "$OUT/$label-pre1.row" \
    && [ ! -s "$OUT/$label-pre1.err" ] && [ ! -s "$OUT/$label-pre2.err" ]
}

i_matches_preimage() {           # i_matches_preimage <label>  (compares -post against -pre1)
  cmp -s "$OUT/$1-pre1.row" "$OUT/$1-post.row" && cmp -s "$OUT/$1-pre1.rc" "$OUT/$1-post.rc"
}

py() { python3 - "$@"; }

# ==================================================================================================
# I1 — a READY round ⇒ the gate allows, exit 0.
# ==================================================================================================
#: The baseline the other seven are read against. Asserted on three things at once, because "exit 0" alone
#: does not distinguish an allowing gate from a gate that cannot fail: the code, the machine-readable GUARD
#: id (`review-verdict`, never grepped out of the sentence — `RCF-9` is what grepping the sentence costs),
#: and that the reason states the basis it decided on. The rendered view is checked to EXIST here so that
#: I5's deletion is the removal of something that was really there.
I1="$(i_init "i1$TAG")"
[ -d "$I1" ] || { echo "init produced no instant; nothing below is a verdict" >&2; exit 2; }
fleet review --instant "$I1" --scope all --verdict READY \
      --finding "I1-a:Minor:applied:src/fleet/review.py:a naming nit in the docstring:reworded, already applied" \
      --porcelain > "$OUT/I1-record.out" 2>&1
i1_record_rc=$?
i1_rc="$(i_gate I1-gate "$I1")"
cat "$OUT/I1-gate.row"
i1_guard=0; grep -q '^review-verdict	' "$OUT/I1-gate.row" && i1_guard=1
i1_basis=0; grep -q 'recorded READY at' "$OUT/I1-gate.row" \
            && grep -q '0 open blocking findings' "$OUT/I1-gate.row" && i1_basis=1
i1_view=0;  [ -f "$I1/REVIEW.md" ] && i1_view=1
if [ "$i1_record_rc" = 0 ] && [ "$i1_rc" = 0 ] && [ "$i1_guard$i1_basis$i1_view" = "111" ]; then
  it_pass I1 "fleet/it/I/out/I1-gate.row" \
    "one READY round recorded through the CLI ⇒ the gate ALLOWS at exit 0, and it says why it allowed: guard \`review-verdict\` (the machine-readable half, compared rather than grepped out of prose) and a reason naming the round, its recorded timestamp and 0 open blocking findings. Recording also rendered REVIEW.md, which matters two cases later — I5 deletes a file that demonstrably existed"
else
  it_fail I1 "fleet/it/I/out/I1-gate.row" \
    "record_rc=$i1_record_rc gate_rc=$i1_rc (want 0) guard=$i1_guard basis=$i1_basis view_rendered=$i1_view — see the files"
fi

# ==================================================================================================
# I2 — READY-WITH-FIXES with an OPEN `Important` ⇒ exit 1, and the reason NAMES THE COUNT.
# ==================================================================================================
#: A verdict is not a permission. `READY-WITH-FIXES` is the reviewer's summary; `open_blocking()` is the
#: arithmetic, and the arithmetic wins — one open `Important` refuses the gate at exit 1 while the recorded
#: verdict still reads READY-WITH-FIXES. The `Nit` alongside it is a control: `Minor`/`Nit` are outside
#: `BLOCKING_SEVERITIES`, so a gate counting findings rather than BLOCKING findings would say 2.
#:
#: "Names the count" is then asserted TWICE, at two different counts. A single assertion of "the reason
#: contains 1" is satisfied by a hardcoded 1, and this reason contains "round 1" as well — so a second round
#: restates the still-open `Important` and adds another, and the count has to MOVE to 2. A number that
#: tracks the ledger is a report; a number that does not is decoration.
I2="$(i_init "i2$TAG")"
fleet review --instant "$I2" --scope all --verdict READY-WITH-FIXES \
      --finding "I2-imp:Important:open:src/fleet/cli.py:the handler collapses two instants into one flag:split the flag before merging" \
      --finding "I2-nit:Nit:open:src/fleet/cli.py:a trailing space:strip it" \
      --porcelain > "$OUT/I2-round1.out" 2>&1
i2_rc="$(i_gate I2-gate1 "$I2")"
cat "$OUT/I2-gate1.row"
# A SECOND round: the Important is restated still-open, and a second one is raised. Count must go 1 -> 2.
fleet review --instant "$I2" --scope code --verdict READY-WITH-FIXES \
      --finding "I2-imp:Important:open:src/fleet/cli.py:still open after the first round:split the flag before merging" \
      --finding "I2-imp2:Important:open:src/fleet/review.py:a second blocking finding:record a status for it" \
      --porcelain > "$OUT/I2-round2.out" 2>&1
i2_rc2="$(i_gate I2-gate2 "$I2")"
cat "$OUT/I2-gate2.row"
i2_verdict_kept=0; grep -q 'recorded READY-WITH-FIXES' "$OUT/I2-gate1.row" && i2_verdict_kept=1
i2_count1=0; grep -q '1 open blocking finding(s) remain' "$OUT/I2-gate1.row" && i2_count1=1
i2_count2=0; grep -q '2 open blocking finding(s) remain' "$OUT/I2-gate2.row" && i2_count2=1
i2_named=0;  grep -q 'I2-imp (Important, src/fleet/cli.py)' "$OUT/I2-gate1.row" && i2_named=1
i2_nit_excluded=0; grep -q 'I2-nit' "$OUT/I2-gate1.row" || i2_nit_excluded=1
if [ "$i2_rc" = 1 ] && [ "$i2_rc2" = 1 ] \
   && [ "$i2_verdict_kept$i2_count1$i2_count2$i2_named$i2_nit_excluded" = "11111" ]; then
  it_pass I2 "fleet/it/I/out/I2-gate2.row" \
    "READY-WITH-FIXES plus one OPEN Important ⇒ exit 1, and the reason NAMES THE COUNT: '1 open blocking finding(s) remain of severity Critical/Important: I2-imp (Important, src/fleet/cli.py)'. The recorded verdict still reads READY-WITH-FIXES — the arithmetic of open_blocking() refuses, not the summary word. The count is asserted at TWO values, because a single '1' is indistinguishable from a hardcoded one: a second round restates the Important still-open and raises another, and the reason moves to '2 open blocking finding(s)' (exit 1 both times). The Nit is the control — it is outside BLOCKING_SEVERITIES and appears in NEITHER count, so a gate counting findings rather than blocking ones would have said 2 and then 3"
else
  it_fail I2 "fleet/it/I/out/I2-gate2.row" \
    "rc1=$i2_rc rc2=$i2_rc2 (want 1 and 1) verdict-preserved=$i2_verdict_kept count-says-1=$i2_count1 count-says-2=$i2_count2 finding-named=$i2_named nit-excluded=$i2_nit_excluded — a count that does not move with the ledger is decoration"
fi

# ==================================================================================================
# I3 — NO round at all ⇒ exit **2** (UNDECIDABLE), with a reason that says undecidable and never
#      "not-ready".  Asserted against a REAL not-ready ledger, side by side.
# ==================================================================================================
#: The distinction is the whole case, so it is measured as a distinction and not as a literal. An empty
#: ledger and a NOT-READY ledger both fail closed, and a build that collapsed them into one non-zero class
#: would pass any assertion made about either one alone (`OI-3`: that is exactly what a test cannot see
#: through). So two instants are gated in the same breath:
#:
#:   * `i3none` — nothing recorded. Wanted: exit 2, guard `review-undecidable`, the word UNDECIDABLE, the
#:     sentence "nothing has been judged", and NOT ONE case-insensitive occurrence of "not-ready" anywhere
#:     in the row. A reader sent to "this work was rejected" when the truth is "nobody has looked at it yet"
#:     goes looking for findings that do not exist.
#:   * `i3nr` — a round recorded NOT-READY. Wanted: exit 1, guard `review-verdict`, and the words NOT-READY
#:     present. This is what the other row must not look like.
#:
#: Both halves are required. Without the second, "never says not-ready" is satisfied by a build that cannot
#: say it at all; without the first, exit 2 could be any refusal.
I3NONE="$(i_init "i3none$TAG")"
i3_rc="$(i_gate I3-none "$I3NONE")"
cat "$OUT/I3-none.row"
I3NR="$(i_init "i3nr$TAG")"
fleet review --instant "$I3NR" --scope all --verdict NOT-READY \
      --finding "I3-crit:Critical:open:src/fleet/store.py:a torn write on the record register:hold the lock across read-modify-write" \
      --porcelain > "$OUT/I3-nr-record.out" 2>&1
i3nr_rc="$(i_gate I3-nr "$I3NR")"
cat "$OUT/I3-nr.row"
i3_guard=0; grep -q '^review-undecidable	' "$OUT/I3-none.row" && i3_guard=1
i3_word=0;  grep -q 'UNDECIDABLE: no review round has been recorded' "$OUT/I3-none.row" \
            && grep -q 'nothing has been judged' "$OUT/I3-none.row" && i3_word=1
i3_clean=0; grep -qi 'not.ready' "$OUT/I3-none.row" || i3_clean=1
i3_zero=0;  grep -q 'population: 0 round(s)' "$OUT/I3-none.row" && i3_zero=1
i3nr_guard=0; grep -q '^review-verdict	' "$OUT/I3-nr.row" && i3nr_guard=1
i3nr_word=0;  grep -q 'recorded verdict NOT-READY' "$OUT/I3-nr.row" && i3nr_word=1
if [ "$i3_rc" = 2 ] && [ "$i3nr_rc" = 1 ] \
   && [ "$i3_guard$i3_word$i3_clean$i3_zero$i3nr_guard$i3nr_word" = "111111" ]; then
  it_pass I3 "fleet/it/I/out/I3-none.row" \
    "an empty ledger is UNDECIDABLE, not decided-no, and it is asserted in the WORDING as well as the code: exit **2** (not 1), guard \`review-undecidable\` (not \`review-verdict\`), the reason opens 'UNDECIDABLE: no review round has been recorded', says 'nothing has been judged', reports 'population: 0 round(s)' — and contains not one case-insensitive occurrence of 'not-ready' anywhere. Measured SIDE BY SIDE with a real NOT-READY ledger on a second instant, which exits **1** with guard \`review-verdict\` and does say 'recorded verdict NOT-READY': without that half, 'never says not-ready' would also be satisfied by a build incapable of saying it. Two states, two codes, two guards, two sentences — a reader is sent to two different problems"
else
  it_fail I3 "fleet/it/I/out/I3-none.row" \
    "empty-ledger rc=$i3_rc (want 2) guard=$i3_guard undecidable-wording=$i3_word no-not-ready-wording=$i3_clean population-0=$i3_zero :: real-NOT-READY rc=$i3nr_rc (want 1) guard=$i3nr_guard says-NOT-READY=$i3nr_word"
fi

# ==================================================================================================
# I4 — round 1 `--scope all`, round 2 NARROW ⇒ `--require-scope all` STILL passes. Coverage is CUMULATIVE.
# ==================================================================================================
#: `OBS-30`, and it was found by pointing the tool at production instants AFTER every fixture passed. A
#: worker reviewed in full in round 1 and re-checked narrowly in round 2 HAS been reviewed in full; judging
#: coverage on the newest round alone rejects it, which is a false refusal of correct work.
#:
#: The negative control is what stops this being a test of a no-op. `--require-scope all` against a ledger
#: holding ONLY a narrow round must REFUSE, at guard `review-scope`, naming the atoms it is missing. Without
#: it, a `--require-scope` that was silently ignored would pass the positive half perfectly.
I4="$(i_init "i4cum$TAG")"
fleet review --instant "$I4" --scope all --verdict READY \
      --finding "I4-a:Minor:applied:evidence/INDEX.md:a full pass in round 1:noted" --porcelain \
      > "$OUT/I4-round1.out" 2>&1
fleet review --instant "$I4" --scope code --verdict READY \
      --finding "I4-b:Nit:applied:src/fleet/review.py:a narrow re-check in round 2:noted" --porcelain \
      > "$OUT/I4-round2.out" 2>&1
i4_rc="$(i_gate I4-cumulative "$I4" --require-scope all)"
cat "$OUT/I4-cumulative.row"
I4N="$(i_init "i4narrow$TAG")"
fleet review --instant "$I4N" --scope code --verdict READY \
      --finding "I4-c:Nit:applied:src/fleet/review.py:the only round, and it is narrow:noted" --porcelain \
      > "$OUT/I4-narrow-record.out" 2>&1
i4n_rc="$(i_gate I4-narrow-only "$I4N" --require-scope all)"
cat "$OUT/I4-narrow-only.row"
i4_newest_narrow=0; grep -q 'round 2 (scope code)' "$OUT/I4-cumulative.row" && i4_newest_narrow=1
i4_union=0; grep -q 'scopes covered: alignment, all, code, format' "$OUT/I4-cumulative.row" && i4_union=1
i4n_guard=0; grep -q '^review-scope	' "$OUT/I4-narrow-only.row" && i4n_guard=1
i4n_missing=0; grep -q 'missing: alignment, format' "$OUT/I4-narrow-only.row" && i4n_missing=1
if [ "$i4_rc" = 0 ] && [ "$i4n_rc" = 1 ] \
   && [ "$i4_newest_narrow$i4_union$i4n_guard$i4n_missing" = "1111" ]; then
  it_pass I4 "fleet/it/I/out/I4-cumulative.row" \
    "scope coverage is the UNION across rounds, not the newest round's: round 1 \`all\` then round 2 \`code\` ⇒ \`--require-scope all\` passes at exit 0, while the gate row confirms the NEWEST round is the narrow one ('round 2 (scope code)') and coverage reads 'alignment, all, code, format'. OBS-30 was found by pointing the tool at production instants after every fixture passed, and reading only the newest round is a false refusal of a correctly-reviewed worker. The negative control makes this falsifiable: a second instant whose ONLY round is \`code\` is REFUSED at exit 1, guard \`review-scope\`, naming 'missing: alignment, format' — so a \`--require-scope\` that was silently ignored could not have produced both rows"
else
  it_fail I4 "fleet/it/I/out/I4-cumulative.row" \
    "cumulative rc=$i4_rc (want 0) newest-is-narrow=$i4_newest_narrow union-covered=$i4_union :: narrow-only control rc=$i4n_rc (want 1) guard=$i4n_guard names-missing=$i4n_missing"
fi

# ==================================================================================================
# I5 — DELETE `REVIEW.md` ⇒ the gate is UNCHANGED, against a pre-image captured before the deletion.
# ==================================================================================================
#: Plan 6: *any read at all would fail here.* An `open()` on a path that does not exist raises; there is no
#: way to read this file successfully and no way to be tolerant of its absence without noticing it. So the
#: gate returning the SAME exit code and the byte-identical reason is not "the gate coped" — it is proof the
#: file was never on the path the decision travelled.
#:
#: Falsifiability, restated at the case that needs it most: the compared value is a PRE-IMAGE recorded from
#: this same instant moments earlier, captured twice and required to agree, so there is no literal here for
#: a broken gate to accidentally satisfy. And the file is asserted STILL ABSENT afterwards — a gate that
#: re-rendered the view it is accused of reading would have restored it and hidden the whole question.
I5="$(i_init "i5$TAG")"
fleet review --instant "$I5" --scope all --verdict READY \
      --finding "I5-a:Minor:applied:REVIEW.md:the view is derived:regenerated, not edited" --porcelain \
      > "$OUT/I5-record.out" 2>&1
i5_existed=0; [ -f "$I5/REVIEW.md" ] && i5_existed=1
i5_stable=0; i_preimage I5 "$I5" && i5_stable=1
rm -f "$I5/REVIEW.md"
i5_deleted=0; [ -e "$I5/REVIEW.md" ] || i5_deleted=1
i_gate I5-post "$I5" --require-scope all >/dev/null
i5_same=0; i_matches_preimage I5 && i5_same=1
i5_still_gone=0; [ -e "$I5/REVIEW.md" ] || i5_still_gone=1
printf 'pre1 rc=%s\npost rc=%s\n' "$(cat "$OUT/I5-pre1.rc")" "$(cat "$OUT/I5-post.rc")" > "$OUT/I5-compare.txt"
diff "$OUT/I5-pre1.row" "$OUT/I5-post.row" >> "$OUT/I5-compare.txt" 2>&1
echo "I5: existed=$i5_existed stable=$i5_stable deleted=$i5_deleted same=$i5_same still-gone=$i5_still_gone"
if [ "$i5_existed$i5_stable$i5_deleted$i5_same$i5_still_gone" = "11111" ]; then
  it_pass I5 "fleet/it/I/out/I5-compare.txt" \
    "REVIEW.md DELETED ⇒ the gate is unchanged: exit code $(cat "$OUT/I5-post.rc") and a BYTE-IDENTICAL reason string (round number, recorded timestamp, covered scopes, finding counts, ledger path — all of it) against a PRE-IMAGE captured from this instant before the deletion. The pre-image was captured TWICE, the two agreed, and what they agreed on was a REAL verdict (a non-empty row under a declared guard id, clean stderr — a traceback never becomes a baseline), so the comparison is not vacuous: there is no literal here a gate frozen on one answer could satisfy, and this section's I1/I2/I3 rows show the same gate returning 0, 1 and 2 on other ledgers. Plan 6's note is 'any read at all would fail here' — an open() on an absent path raises, so equality proves the file is not on the path the decision travels. And REVIEW.md is still absent afterwards: the gate did not re-render the view it stands accused of reading, which would have restored the file and hidden the question"
else
  it_fail I5 "fleet/it/I/out/I5-compare.txt" \
    "view-existed-first=$i5_existed pre-image-stable=$i5_stable deletion-took=$i5_deleted gate-unchanged=$i5_same view-still-absent=$i5_still_gone; pre rc=$(cat "$OUT/I5-pre1.rc") post rc=$(cat "$OUT/I5-post.rc") — see the diff in the evidence file"
fi

# ==================================================================================================
# I6 — replace `REVIEW.md` with a CONTRADICTING file (bold `NOT-READY`, a `Round 2 of 2 (final)` heading)
#      ⇒ the gate is UNCHANGED.
# ==================================================================================================
#: This is `OBS-15` and `OBS-19` reconstructed byte for byte. The predecessor's gate regex over idiomatic
#: markdown blocked one genuinely-READY worker for writing its verdict in **bold** and a second for
#: disambiguating a two-round summary heading as "Round 2 of 2 (final)". Both shapes are in the file written
#: below, together, over a ledger whose single round is READY.
#:
#: So the view now says the opposite of the ledger, in the two dialects that historically won. If anything
#: at all consulted it the gate would flip to a refusal — the corruption is designed to be READ SUCCESSFULLY
#: and to lie, which is the one failure mode I5's deletion and I7's directory cannot produce. Same
#: discipline: pre-image first, captured twice; byte comparison after; and the lying file is asserted still
#: present and byte-unchanged, so the gate neither read it nor overwrote it.
I6="$(i_init "i6$TAG")"
fleet review --instant "$I6" --scope all --verdict READY \
      --finding "I6-a:Minor:applied:src/fleet/review.py:prose is not a control signal:the ledger is the arbiter" \
      --porcelain > "$OUT/I6-record.out" 2>&1
i6_stable=0; i_preimage I6 "$I6" && i6_stable=1
cat > "$I6/REVIEW.md" <<'MD'
# REVIEW — hand-written, and it contradicts the ledger on purpose

**Verdict: NOT-READY**

This document is the `OBS-15` / `OBS-19` pair reconstructed. The predecessor's gate matched a regex over
prose exactly like this, and it blocked two genuinely-READY workers: one wrote its verdict in **bold**, one
disambiguated its summary heading. Both shapes are below.

## Round 2 of 2 (final)

| id | severity | status | location | finding | action |
|---|---|---|---|---|---|
| FAKE-1 | Critical | open | everywhere | a Critical that exists nowhere in the ledger | none, it is fiction |

**Gate:** REFUSED (`not-ready`)

NOT-READY. NOT READY. not-ready.
MD
i6_bold=0; grep -q '\*\*Verdict: NOT-READY\*\*' "$I6/REVIEW.md" && i6_bold=1
i6_head=0; grep -q '^## Round 2 of 2 (final)$' "$I6/REVIEW.md" && i6_head=1
i6_lie_sha="$(sha256sum "$I6/REVIEW.md" | cut -d' ' -f1)"
i_gate I6-post "$I6" --require-scope all >/dev/null
i6_same=0; i_matches_preimage I6 && i6_same=1
i6_intact=0; [ "$i6_lie_sha" = "$(sha256sum "$I6/REVIEW.md" | cut -d' ' -f1)" ] && i6_intact=1
printf 'pre1 rc=%s\npost rc=%s\ncontradicting-view sha=%s\n' \
       "$(cat "$OUT/I6-pre1.rc")" "$(cat "$OUT/I6-post.rc")" "$i6_lie_sha" > "$OUT/I6-compare.txt"
diff "$OUT/I6-pre1.row" "$OUT/I6-post.row" >> "$OUT/I6-compare.txt" 2>&1
cp "$I6/REVIEW.md" "$OUT/I6-contradicting-view.md"
echo "I6: stable=$i6_stable bold=$i6_bold heading=$i6_head same=$i6_same lie-intact=$i6_intact"
if [ "$i6_stable$i6_bold$i6_head$i6_same$i6_intact" = "11111" ]; then
  it_pass I6 "fleet/it/I/out/I6-compare.txt" \
    "REVIEW.md replaced by a file that CONTRADICTS the ledger — bold '**Verdict: NOT-READY**', a '## Round 2 of 2 (final)' heading, a fictional open Critical, and the literal words 'NOT-READY' six times — over a ledger whose one round is READY ⇒ the gate is unchanged: exit $(cat "$OUT/I6-post.rc") and a byte-identical reason against a pre-image captured twice before the swap and validated as a real verdict rather than a traceback. This corruption is the one that CAN be read successfully and lies, unlike I5's absence and I7's directory, and it is OBS-15/OBS-19 reconstructed: the predecessor's regex blocked one READY worker for bolding its verdict and a second for disambiguating a two-round heading, so both dialects are in the file at once. Anything consulting the view would have flipped this gate to a refusal. The lying file is also byte-unchanged afterwards, so the gate neither read it nor overwrote it — verbatim copy at fleet/it/I/out/I6-contradicting-view.md"
else
  it_fail I6 "fleet/it/I/out/I6-compare.txt" \
    "pre-image-stable=$i6_stable bold-verdict-present=$i6_bold two-round-heading-present=$i6_head gate-unchanged=$i6_same lying-file-intact=$i6_intact; pre rc=$(cat "$OUT/I6-pre1.rc") post rc=$(cat "$OUT/I6-post.rc") — if gate-unchanged=0 the view is being read and OBS-15/OBS-19 have returned"
fi

# ==================================================================================================
# I7 — replace `REVIEW.md` with a DIRECTORY ⇒ the gate is UNCHANGED, and here it preserves a REFUSAL.
# ==================================================================================================
#: The third shape, and the one no tolerant reader survives: `open()` on a directory raises `IsADirectoryError`
#: regardless of mode, so there is no lenient read and no default-on-missing that gets past it. A decoy file
#: is planted inside so that even a gate that globbed for markdown would find something to be wrong about.
#:
#: Deliberately seeded to REFUSE (`READY-WITH-FIXES` with an open `Critical`, exit 1) where I5 and I6
#: preserve an ALLOW. "Unchanged" has to hold in both directions: a gate stuck on refusal would pass I7 and
#: fail I5/I6, and a gate stuck on allow would do the reverse. Neither can pass this section.
I7="$(i_init "i7$TAG")"
fleet review --instant "$I7" --scope all --verdict READY-WITH-FIXES \
      --finding "I7-crit:Critical:open:src/fleet/review.py:an open Critical, so this gate REFUSES:record a status for it in a later round" \
      --porcelain > "$OUT/I7-record.out" 2>&1
i7_stable=0; i_preimage I7 "$I7" && i7_stable=1
i7_refuses=0; [ "$(cat "$OUT/I7-pre1.rc")" = 1 ] && i7_refuses=1
rm -rf "$I7/REVIEW.md"
mkdir -p "$I7/REVIEW.md/decoy"
printf '**NOT-READY** — a decoy, so even a gate that globbed for markdown would find prose to misread.\n' \
       > "$I7/REVIEW.md/decoy/VERDICT.md"
i7_isdir=0; [ -d "$I7/REVIEW.md" ] && i7_isdir=1
i_gate I7-post "$I7" --require-scope all >/dev/null
i7_same=0; i_matches_preimage I7 && i7_same=1
i7_still_dir=0; [ -d "$I7/REVIEW.md" ] && [ -f "$I7/REVIEW.md/decoy/VERDICT.md" ] && i7_still_dir=1
printf 'pre1 rc=%s\npost rc=%s\nREVIEW.md is a directory: %s\n' \
       "$(cat "$OUT/I7-pre1.rc")" "$(cat "$OUT/I7-post.rc")" "$i7_isdir" > "$OUT/I7-compare.txt"
diff "$OUT/I7-pre1.row" "$OUT/I7-post.row" >> "$OUT/I7-compare.txt" 2>&1
echo "I7: stable=$i7_stable refuses=$i7_refuses isdir=$i7_isdir same=$i7_same still-dir=$i7_still_dir"
if [ "$i7_stable$i7_refuses$i7_isdir$i7_same$i7_still_dir" = "11111" ]; then
  it_pass I7 "fleet/it/I/out/I7-compare.txt" \
    "REVIEW.md replaced by a DIRECTORY (with a decoy **NOT-READY** markdown file inside it) ⇒ the gate is unchanged: exit $(cat "$OUT/I7-post.rc") and a byte-identical reason against a pre-image captured twice beforehand and validated as a real verdict — this is the case that made that validation mandatory: a mutant whose gate DID read the view crashed on every query, so an empty row compared equal to an empty row and I7 passed on the very build it exists to catch (see \`i_preimage\`). open() on a directory raises IsADirectoryError in every mode, so there is no lenient read and no default-on-missing that gets past this — 'any read at all would fail here'. This instant is seeded to REFUSE (READY-WITH-FIXES with an open Critical, exit 1) where I5 and I6 preserve an ALLOW at exit 0, so 'unchanged' is asserted in BOTH directions: a gate frozen on refusal passes here and fails I5/I6, one frozen on allow does the reverse, and neither survives the section. The directory and its decoy are still in place afterwards"
else
  it_fail I7 "fleet/it/I/out/I7-compare.txt" \
    "pre-image-stable=$i7_stable pre-image-was-a-refusal=$i7_refuses swap-to-directory-took=$i7_isdir gate-unchanged=$i7_same directory-still-there=$i7_still_dir; pre rc=$(cat "$OUT/I7-pre1.rc") post rc=$(cat "$OUT/I7-post.rc")"
fi

# ==================================================================================================
# I8 — render twice ⇒ BYTE-IDENTICAL; hand-edit `REVIEW.md` then render ⇒ RESTORED.
# ==================================================================================================
#: `NFR2-10`: a derived view is regenerated in full, never accumulated, and every timestamp in it comes from
#: the LEDGER — which is what makes two renders of one ledger byte-identical without freezing the clock
#: (`NFR2-3`, the injected `now`). Appending instead would make the file a history whose newest section a
#: reader has to find, and "which section is current" is a question a derived view must never raise.
#:
#: The byte-identity half is asserted at the LIBRARY, and that is a deliberate, stated limitation rather
#: than a shortcut. `render()` is reachable from the CLI only as a side effect of `fleet review --verdict`,
#: which necessarily APPENDS a round — so through the CLI alone the two renders are of two DIFFERENT
#: ledgers and differing bytes would be correct. "Two renders of ONE ledger" is only expressible where the
#: render can be called without mutating, i.e. at the library. §H's `SI-26` is the warning against leaning
#: on a driver — a mechanism only reachable from python is not a mechanism — so the CLI half is asserted too,
#: and it is the half a worker actually walks: hand-edit the view, record the next round, and the edit is
#: gone because the writer regenerated the whole file rather than appending to it.
I8="$(i_init "i8$TAG")"
fleet review --instant "$I8" --scope all --verdict READY \
      --finding "I8-a:Minor:applied:REVIEW.md:hand edits to a derived view are discarded:regenerate, never accumulate" \
      --porcelain > "$OUT/I8-record.out" 2>&1
cp "$I8/REVIEW.md" "$OUT/I8-render1.md"
i8_sha1="$(sha256sum "$I8/REVIEW.md" | cut -d' ' -f1)"
py "$I8" > "$OUT/I8-twice.txt" 2>&1 <<'PY'
import pathlib, sys
from fleet.review import Review
review = Review(pathlib.Path(sys.argv[1]))
first = review.render()
second = review.render()
print("two renders returned identical bytes:", first == second)
print("the file on disk equals what render returned:",
      review.view_path().read_text(encoding="utf-8") == second)
print("timestamps in the view come from the ledger:",
      all(r.at in second for r in review.rounds()))
PY
cat "$OUT/I8-twice.txt"
i8_sha2="$(sha256sum "$I8/REVIEW.md" | cut -d' ' -f1)"
i8_identical=0; grep -q '^two renders returned identical bytes: True$' "$OUT/I8-twice.txt" \
                && grep -q '^the file on disk equals what render returned: True$' "$OUT/I8-twice.txt" \
                && [ "$i8_sha1" = "$i8_sha2" ] && i8_identical=1
i8_from_ledger=0; grep -q '^timestamps in the view come from the ledger: True$' "$OUT/I8-twice.txt" \
                  && i8_from_ledger=1

# Restoration, at the library: a hand edit, then a render of the UNCHANGED ledger, back to the same bytes.
{ printf '\n**HAND EDIT: NOT-READY** — and a `Round 2 of 2 (final)` heading for good measure.\n'; } \
  >> "$I8/REVIEW.md"
i8_sha_edited="$(sha256sum "$I8/REVIEW.md" | cut -d' ' -f1)"
py "$I8" > "$OUT/I8-restore.txt" 2>&1 <<'PY'
import pathlib, sys
from fleet.review import Review
Review(pathlib.Path(sys.argv[1])).render()
print("re-rendered")
PY
i8_sha_restored="$(sha256sum "$I8/REVIEW.md" | cut -d' ' -f1)"
i8_edit_took=0;  [ "$i8_sha_edited" != "$i8_sha1" ] && i8_edit_took=1
i8_restored=0;   [ "$i8_sha_restored" = "$i8_sha1" ] && i8_restored=1

# Restoration, through the CLI: a hand edit, then the next recorded round. The edit must not survive, and
# the file must be a full regeneration of the NEW ledger.
printf '\n**HAND EDIT AGAIN: NOT-READY**\n' >> "$I8/REVIEW.md"
fleet review --instant "$I8" --scope format --verdict READY \
      --finding "I8-b:Nit:applied:REVIEW.md:a second round, so the view legitimately changes:regenerated in full" \
      --porcelain > "$OUT/I8-round2.out" 2>&1
cp "$I8/REVIEW.md" "$OUT/I8-after-cli-render.md"
i8_edit_gone=0; grep -q 'HAND EDIT' "$I8/REVIEW.md" || i8_edit_gone=1
i8_regenerated=0; grep -q '^## Round 1 ' "$I8/REVIEW.md" && grep -q '^## Round 2 ' "$I8/REVIEW.md" \
                  && i8_regenerated=1
{ printf 'render1 sha=%s\nrender2 sha=%s\nhand-edited sha=%s\nre-rendered sha=%s\n' \
         "$i8_sha1" "$i8_sha2" "$i8_sha_edited" "$i8_sha_restored"
  cat "$OUT/I8-twice.txt"; } > "$OUT/I8-summary.txt"
cat "$OUT/I8-summary.txt"
if [ "$i8_identical$i8_from_ledger$i8_edit_took$i8_restored$i8_edit_gone$i8_regenerated" = "111111" ]; then
  it_pass I8 "fleet/it/I/out/I8-summary.txt" \
    "the view is DERIVED and regenerated in full. Two renders of one unchanged ledger are byte-identical (sha ${i8_sha1:0:12}… both times, the returned string equal to the bytes on disk), and every timestamp in the view is one the LEDGER holds — which is why byte-identity needs no frozen clock (NFR2-3's injected now). Then a hand edit that DID change the file (sha moved to ${i8_sha_edited:0:12}…) is discarded by the next render, back to ${i8_sha1:0:12}… exactly. The byte-identity half is asserted at the library and that is a stated limitation, not a shortcut: the CLI reaches render() only as a side effect of \`review --verdict\`, which appends a round, so two CLI renders are of two different ledgers and differing bytes would be CORRECT. The CLI half a worker actually walks is asserted too — hand-edit, then record round 2: the edit is gone and the file carries BOTH '## Round 1' and '## Round 2', so the writer regenerated the whole document rather than appending to it (NFR2-10)"
else
  it_fail I8 "fleet/it/I/out/I8-summary.txt" \
    "two-renders-identical=$i8_identical timestamps-from-ledger=$i8_from_ledger hand-edit-actually-changed-it=$i8_edit_took restored-by-render=$i8_restored cli-render-dropped-the-edit=$i8_edit_gone full-regeneration=$i8_regenerated; shas render1=$i8_sha1 render2=$i8_sha2 edited=$i8_sha_edited restored=$i8_sha_restored"
fi

it_assert_isolation I-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict" >&2; exit 3; }
sed -i "s|$INSTANT/||g" "$RESULTS"
echo "§I done: IT_FAILED=$IT_FAILED"
#: `II-11`. Was `exit "$IT_FAILED"` — a COUNT. `exit` truncates modulo 256, so a section with
#: exactly 256 failures reported SUCCESS, and one with 300 reported 44, a number meaning nothing
#: to any reader. An exit status is a one-byte verdict, not a tally: the count is already printed
#: on the line above and is in the register, which is where a consumer should read it anyway.
if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
exit 1
