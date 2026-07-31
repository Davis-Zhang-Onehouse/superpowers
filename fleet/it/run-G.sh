#!/usr/bin/env bash
# §G — Declarations.  plans/plan-6-integration-tests.md lines 177-189.
#
# The section exists for one failure, and every case is a face of it. `RCF-9`: a worker wrote
# `## Phase: AWAITING-CI` into its `HANDOFF.md` exactly as its brief worded it, a leading `## ` defeated
# the consumer's regex, the declaration was a silent no-op, and at a WIP cap of 1 that undeclared waiter
# held the effort's only dev slot for the length of a CI queue. The model's answer has three parts and
# §G measures all three, because any one of them alone reproduces the failure with better manners:
#
#   1. A declaration is a VERB'S PRODUCT, never prose. `store.Declarations` opens no `.md` file at all,
#      so no amount of correctly-shaped markdown can move the state (G2, G5).
#   2. The acknowledgement is a RE-READ THROUGH THE CONSUMER, not an echo of the argument — the argument
#      is what the declarer already believed, and it is exactly what the failing worker believed (G1).
#   3. THE AUTHOR IS TOLD. A rule that merely ignores the line leaves the worker convinced it declared
#      something, which is the whole of RCF-9 minus the regex (G3).
#
# WHY EVERY NEGATIVE CASE CARRIES A POSITIVE CONTROL. Four of these seven cases are of the form "X does
# not happen", and a product that does nothing at all passes all four. So:
#   * G2's undeclared instant has a TWIN with a byte-identical prose block and a real declaration; the
#     three consumers are asked about both, so prose is held constant and only the declaration varies.
#     A consumer that always answered "(none declared)" fails the twin.
#   * G3 is what makes G2 and G4 non-vacuous: it requires the lint to FIRE, by line number, on the same
#     file in the same run. A lint that flags nothing passes G2 and G4 trivially and fails G3.
#   * G4 is asserted twice — once pure (retraction only ⇒ zero findings) and once with one genuine
#     near-miss line appended to the SAME file, so a single `lint` invocation flags one line and not the
#     other two. Discrimination inside one measurement cannot be vacuous.
#   * G5's inert prose is measured against the same consumers that then report a real `park`, and the
#     empty-park refusal proves the state is left standing rather than cleared.
#   * G7's rename is controlled by a rename that must NOT resolve (the NAME field changed, not just the
#     state), so "resolution follows the folder" is not "resolution finds any sibling".
#
# §G STARTS NO TMUX SESSION. Nothing here dispatches: the whole surface under test is an instant's own
# `.fleet/declare.json` and the verbs that read it. `resume` is used twice to mint a RECORD (never a
# session) so `status` can be asked for `evidence.declared_phase` — that field is `reconcile`'s own read
# of the declaration, i.e. the join the WIP cap counts, and it is a genuinely different consumer from
# `brief`. The cleanup trap and the private socket stay anyway: costing nothing is not a reason to drop a
# control, and `it_section` has already pointed `FLEET_TMUX_SOCKET` at a private server.
#
# Run: bash fleet/it/run-G.sh
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
# `§G` is owned too: `RESULTS.tsv` carries a section-level NOT-RUN row for §G, and a run that leaves it
# standing beside seven real rows reports the section as both run and not-run.
it_own_cases '§G|G[0-9]+[a-z]?|ISOLATION-G-(enter|leave)'

it_section G

trap 'it_cleanup_tmux' EXIT
OUT="$EV/out"; rm -rf "$OUT"; mkdir -p "$OUT"
export FLEET_INSTANTS="$EV/instants"; rm -rf "$FLEET_INSTANTS"; mkdir -p "$FLEET_INSTANTS"
it_fresh_store            # a virgin store: §H was measured inheriting a previous run's WIP-cap holder

bash "$IT_ROOT/bin/source-pin.sh" before "$OUT" || exit 2

# --- the product's own constants, read from the product ------------------------------------------------
# Never retyped here. `NEAR_MISS_FILES` is the reason the rule is a rule and not a folder-wide grep, and a
# fixture that hardcodes the file list cannot notice the list changing underneath it.
G_NEAR_MISS="$(python3 -c 'from fleet.cli import NEAR_MISS; print(NEAR_MISS)')"
G_NM_FILES="$(python3 -c 'from fleet.cli import NEAR_MISS_FILES; print(" ".join(NEAR_MISS_FILES))')"
G_CI_TOKEN="$(python3 -c 'from fleet.reconcile import PHASE_AWAITING_CI; print(PHASE_AWAITING_CI)')"
printf 'NEAR_MISS=%s\nNEAR_MISS_FILES=%s\nPHASE_AWAITING_CI=%s\n' \
       "$G_NEAR_MISS" "$G_NM_FILES" "$G_CI_TOKEN" > "$OUT/constants.txt"
cat "$OUT/constants.txt"

g_init() {                        # g_init <name> -> prints the instant path
  local out="$OUT/init-$1.out"
  fleet init --base 00000000 --name "$1" --porcelain > "$out" 2>&1
  awk -F'\t' '$1=="path"{print $2; exit}' "$out"
}
g_brief_phase() {                 # g_brief_phase <instant> -> brief's phase row detail, or a marker
  fleet brief --instant "$1" --porcelain 2>/dev/null \
    | awk -F'\t' '$1=="phase"{print $4; found=1} END{if(!found) print "NO-PHASE-ROW"}'
}
g_lint_declared() {               # g_lint_declared <lint-porcelain-file> -> lint's own view of the phase
  awk -F'\t' '$1=="population" && $4 ~ /near-miss file/ {print $4}' "$1" \
    | sed 's/.*the declared phase is //'
}
g_status_field() {                # g_status_field <todo_id> <key> -> the value, "(absent)" if no row
  fleet status --porcelain --id "$1" 2>/dev/null \
    | awk -F'\t' -v k="$2" '$1==k{print $2; found=1} END{if(!found) print "(absent)"}'
}
g_line_of() {                     # g_line_of <file> <exact line> -> its 1-based line number, or 0
  local n; n="$(grep -nxF -- "$2" "$1" 2>/dev/null | head -1 | cut -d: -f1)"
  printf '%s' "${n:-0}"
}
g_flagged() {                     # g_flagged <lint-file> <lineno> -> 0 if a near-miss row names that line
  [ "$2" = 0 ] && return 1
  awk -F'\t' -v kind="$G_NEAR_MISS" -v n="$2" \
      '$1==kind && $2 ~ (":" n "$") {found=1} END{exit found?0:1}' "$1"
}
g_near_miss_count() {             # g_near_miss_count <lint-porcelain-file> -> how many findings
  awk -F'\t' -v kind="$G_NEAR_MISS" '$1==kind{n++} END{print n+0}' "$1"
}

# The seven prose lines, in the four shapes Plan 6 names. Bold gets three variants and trailing prose two,
# so a verdict about a shape does not hinge on which markdown rendering the fixture author happened to
# pick — a shape counts as flagged if ANY of its variants is.
G_S1='## Phase: AWAITING-CI'                                  # plain (the literal RCF-9 line)
G_S2A='## **Phase: AWAITING-CI**'                             # bold, whole line
G_S2B='- **Phase**: AWAITING-CI'                              # bold key, bullet
G_S2C='**Phase:** AWAITING-CI'                                # bold key and colon
G_S3='    Phase: AWAITING-CI'                                 # indented (a fenced/quoted rendering)
G_S4A='## Phase: AWAITING-CI — waiting on the CI queue'       # trailing prose, em dash
G_S4B='Phase: AWAITING-CI (waiting on the CI queue)'          # trailing prose, parenthetical
G_BLOCK_FILE="$OUT/prose-block.txt"
cat > "$G_BLOCK_FILE" <<EOF

## Current state

$G_S1
$G_S2A
$G_S2B
$G_S2C
$G_S3
$G_S4A
$G_S4B

still working.
EOF
G_BLOCK_BYTES="$(wc -c < "$G_BLOCK_FILE")"
# A correct retraction. Plan 6 calls this the fixture that would have made a naive lint fire on 5 of 5
# live instants: every register that DISCUSSES the defect quotes the line while declaring nothing.
G_R1='Phase: AWAITING-CI was declared and is now REMOVED'
G_R2='`Phase: AWAITING-CI` was declared and is now REMOVED'

DECLARED="$(g_init gdeclared)"    # G1, and G2's positive control
PROSE="$(g_init gprose)"          # G2 (negative) and G3
RETRACT="$(g_init gretract)"      # G4
PARKED="$(g_init gpark)"          # G5
EMPTY="$(g_init gempty)"          # G6
RENAME="$(g_init grename)"        # G7
for d in "$DECLARED" "$PROSE" "$RETRACT" "$PARKED" "$EMPTY" "$RENAME"; do
  [ -d "$d" ] || { echo "init produced no instant ($d); nothing below is a verdict" >&2; exit 2; }
done

# ==================================================================================================
# G1 — `declare --phase awaiting-ci` ⇒ STDOUT EQUALS WHAT A FRESH CONSUMER READS BACK.
#
#      The argument is deliberately UGLY (`  AWAITING-CI  `), because the load-bearing half of the
#      requirement is invisible when the argument is already normalised: an echo and a re-read are the
#      same string for `awaiting-ci`, and a verb that echoes passes the spelled case while reproducing
#      RCF-9 exactly. Three FRESH consumers, in three separate processes, are then asked — and the token
#      is compared against `reconcile.PHASE_AWAITING_CI`, which is the string the WIP cap's join
#      actually compares. A declaration acknowledged as one token and consumed as another is RCF-9 with
#      the regex moved one layer down.
# ==================================================================================================
G1_ASKED='  AWAITING-CI  '
#: What the `asked` row is EXPECTED to carry: `_oneline` collapses whitespace and strips on the way to
#: stdout, deliberately — one record, one line, or a value with a newline in it splits a TSV record in two
#: (`NFR2-7`). So the echo cannot be compared byte-for-byte against the argument, and the case difference
#: is what carries the non-echo assertion. Measured, not assumed: the row does come back upper-case.
G1_ECHOED='AWAITING-CI'
fleet declare --instant "$DECLARED" --phase "$G1_ASKED" --porcelain > "$OUT/G1-declare.tsv" 2>&1
g1_rc=$?
cat "$OUT/G1-declare.tsv"
g1_printed="$(awk -F'\t' '$1=="phase"{print $2}' "$OUT/G1-declare.tsv")"
g1_asked_back="$(awk -F'\t' '$1=="asked"{print $2}' "$OUT/G1-declare.tsv")"
# Fresh consumer 1: `brief`, which reads through `Declarations` exactly as the enforcing verbs do.
g1_brief="$(g_brief_phase "$DECLARED")"
# Fresh consumer 2: `lint`'s population row, which states the declared phase it saw.
fleet lint --instant "$DECLARED" --porcelain > "$OUT/G1-lint.tsv" 2>&1
g1_lint="$(g_lint_declared "$OUT/G1-lint.tsv")"
# Fresh consumer 3: the reconcile JOIN, through a record. `resume` mints the record and starts nothing.
G1_TID="$(fleet resume --instant "$DECLARED" --porcelain 2>&1 | awk -F'\t' '$1=="todo_id"{print $2}')"
g1_join="$(g_status_field "$G1_TID" evidence.declared_phase)"
{ printf 'asked\t%s\nstdout.phase\t%s\nstdout.asked\t%s\nbrief\t%s\nlint\t%s\njoin\t%s\nconstant\t%s\n' \
    "$G1_ASKED" "$g1_printed" "$g1_asked_back" "$g1_brief" "$g1_lint" "$g1_join" "$G_CI_TOKEN"
} > "$OUT/G1-consumers.tsv"
cat "$OUT/G1-consumers.tsv"
g1_agree=0
[ "$g1_printed" = "$G_CI_TOKEN" ] && [ "$g1_brief" = "phase=$G_CI_TOKEN, parked=(not parked)" ] \
  && [ "$g1_lint" = "'$G_CI_TOKEN'" ] && [ "$g1_join" = "$G_CI_TOKEN" ] && g1_agree=1
g1_not_echo=0
[ "$g1_printed" != "$G1_ASKED" ] && [ "$g1_printed" != "$g1_asked_back" ] \
  && [ "$g1_asked_back" = "$G1_ECHOED" ] && g1_not_echo=1
if [ "$g1_rc" = 0 ] && [ "$g1_agree" = 1 ] && [ "$g1_not_echo" = 1 ]; then
  it_pass G1 "fleet/it/G/out/G1-consumers.tsv" \
    "\`declare\` was handed the ugly argument '$G1_ASKED' and printed '$g1_printed', which is NOT an echo: the same call's own \`asked\` row reads '$g1_asked_back' beside it. And that one token is what three FRESH consumers in three separate processes read back — \`brief\`'s phase row, \`lint\`'s population row, and \`status\`'s evidence.declared_phase, which is the reconcile JOIN and therefore the field the WIP cap counts. It also equals reconcile.PHASE_AWAITING_CI read out of the product, so the token acknowledged is the token consumed. The ugly argument is the whole point: with a pre-normalised one an echo and a re-read are the same string, and an echoing verb would pass this case while reproducing RCF-9 — handing the declarer back its own belief. One measured aside, not a finding: the \`asked\` row is whitespace-collapsed on the way out by _oneline (one record, one line, NFR2-7), so the argument's spaces are not visible there and the CASE difference is what makes the two rows distinguishable"
else
  it_fail G1 "fleet/it/G/out/G1-consumers.tsv" \
    "rc=$g1_rc printed='$g1_printed' (want '$G_CI_TOKEN') brief='$g1_brief' lint='$g1_lint' join='$g1_join' consumers-agree=$g1_agree not-an-echo=$g1_not_echo asked-round-tripped='$g1_asked_back'"
fi

# ==================================================================================================
# G2 — FOUR HAND-WRITTEN DECLARATION SHAPES IN `HANDOFF.md`, NO DECLARATION ⇒ THE STATE NEVER CHANGES.
#
#      With the positive control that makes it falsifiable: `$DECLARED` receives a BYTE-IDENTICAL prose
#      block and has a real declaration, so the prose is held constant and only the declaration varies.
#      Three consumers, both instants. If a consumer answered "(none declared)" unconditionally — the
#      cheapest way to pass a "does not happen" case — the twin's rows would be wrong.
#
#      The delta is measured on `.fleet/` (content AND mtime, via `it_manifest`) and on the record store,
#      because "the state never changes" has to exclude a transient write as well as a net one.
# ==================================================================================================
g2_fleet_before="$(it_manifest "$PROSE/.fleet")"
g2_store_before="$(it_manifest "$FLEET_HOME")"
g2_brief_before="$(g_brief_phase "$PROSE")"
cat "$G_BLOCK_FILE" >> "$PROSE/HANDOFF.md"
cat "$G_BLOCK_FILE" >> "$DECLARED/HANDOFF.md"
g2_fleet_after="$(it_manifest "$PROSE/.fleet")"
g2_store_after="$(it_manifest "$FLEET_HOME")"
# The two files carry the same bytes in the appended region — measured, not asserted in prose. The length
# is taken in BYTES from the block file, because the em dash in shape 4 is three of them and a character
# count would compare two misaligned suffixes.
g2_prose_sha="$(sha256sum "$G_BLOCK_FILE" | cut -c1-12)"
g2_same_prose=0
[ "$(tail -c "$G_BLOCK_BYTES" "$PROSE/HANDOFF.md" | sha256sum)" \
  = "$(tail -c "$G_BLOCK_BYTES" "$DECLARED/HANDOFF.md" | sha256sum)" ] \
  && [ "$(tail -c "$G_BLOCK_BYTES" "$PROSE/HANDOFF.md" | sha256sum | cut -d' ' -f1)" \
     = "$(sha256sum "$G_BLOCK_FILE" | cut -d' ' -f1)" ] && g2_same_prose=1

fleet lint --instant "$PROSE" --porcelain > "$OUT/G2-lint-undeclared.tsv" 2>&1
G2_TID="$(fleet resume --instant "$PROSE" --porcelain 2>&1 | awk -F'\t' '$1=="todo_id"{print $2}')"
{ printf '=== the UNDECLARED instant, carrying all seven prose lines ===\n'
  printf 'brief\t%s\n' "$(g_brief_phase "$PROSE")"
  printf 'lint.declared\t%s\n' "$(g_lint_declared "$OUT/G2-lint-undeclared.tsv")"
  printf 'join\t%s\n' "$(g_status_field "$G2_TID" evidence.declared_phase)"
  printf '=== the TWIN: byte-identical prose, plus a real declaration ===\n'
  printf 'brief\t%s\n' "$(g_brief_phase "$DECLARED")"
  printf 'join\t%s\n' "$(g_status_field "$G1_TID" evidence.declared_phase)"
  printf '=== the delta across the prose write ===\n'
  printf 'fleet_dir_unchanged\t%s\n' "$([ "$g2_fleet_before" = "$g2_fleet_after" ] && echo true || echo false)"
  printf 'store_unchanged\t%s\n' "$([ "$g2_store_before" = "$g2_store_after" ] && echo true || echo false)"
  printf 'prose_block_sha12\t%s\n' "$g2_prose_sha"
} > "$OUT/G2-consumers.tsv"
cat "$OUT/G2-consumers.tsv"
g2_undeclared=0
[ "$(g_brief_phase "$PROSE")" = "phase=(none declared), parked=(not parked)" ] \
  && [ "$(g_lint_declared "$OUT/G2-lint-undeclared.tsv")" = "None" ] \
  && [ "$(g_status_field "$G2_TID" evidence.declared_phase)" = "" ] && g2_undeclared=1
g2_twin=0
[ "$(g_brief_phase "$DECLARED")" = "phase=$G_CI_TOKEN, parked=(not parked)" ] \
  && [ "$(g_status_field "$G1_TID" evidence.declared_phase)" = "$G_CI_TOKEN" ] && g2_twin=1
g2_zero=0
[ "$g2_fleet_before" = "$g2_fleet_after" ] && [ "$g2_store_before" = "$g2_store_after" ] && g2_zero=1
if [ "$g2_undeclared" = 1 ] && [ "$g2_twin" = 1 ] && [ "$g2_zero" = 1 ] && [ "$g2_same_prose" = 1 ] \
   && [ "$g2_brief_before" = "phase=(none declared), parked=(not parked)" ]; then
  it_pass G2 "fleet/it/G/out/G2-consumers.tsv" \
    "seven declaration-shaped lines in four shapes (plain · bold ×3 · indented · trailing prose ×2) hand-written into HANDOFF.md with no declaration: all three consumers still report NO phase — \`brief\` says (none declared), \`lint\`'s population says None, the reconcile join's evidence.declared_phase is empty — and \`.fleet/\` is unchanged in content AND mtime (so not even a transient write), as is the record store. NOT VACUOUS: a twin instant carries the BYTE-IDENTICAL prose block (sha12 $g2_prose_sha, both files compared) with a real declaration behind it and every consumer reads $G_CI_TOKEN there. Prose held constant, declaration varied, and the read follows the declaration — a consumer that always answered '(none declared)' would fail the twin"
else
  it_fail G2 "fleet/it/G/out/G2-consumers.tsv" \
    "undeclared-reads-none=$g2_undeclared twin-reads-declared=$g2_twin zero-delta(.fleet+store)=$g2_zero identical-prose-in-both=$g2_same_prose brief-before-the-write='$g2_brief_before' — see the file"
fi

# ==================================================================================================
# G3 — …AND `lint` FLAGS EACH OF THOSE FOUR AS A DECLARATION-SHAPED LINE WITH NO BACKING DECLARATION.
#      *The author must be told, not merely ignored.*
#
#      This is the case that makes G2 and G4 non-vacuous, so it is the one that must fire. Three
#      properties, one lint run each:
#        (a) every one of the four shapes is named BY LINE NUMBER;
#        (b) the same lines with a declaration behind them are NOT findings — a rule, not a grep
#            (`$DECLARED` carries the identical block and is linted here);
#        (c) the rule is scoped to `NEAR_MISS_FILES` and not to the folder: the identical block is
#            appended to a file that is NOT in that list, read out of the product, and the finding count
#            does not move.
# ==================================================================================================
G3_H="$PROSE/HANDOFF.md"
g3_l1="$(g_line_of "$G3_H" "$G_S1")"; g3_l2a="$(g_line_of "$G3_H" "$G_S2A")"
g3_l2b="$(g_line_of "$G3_H" "$G_S2B")"; g3_l2c="$(g_line_of "$G3_H" "$G_S2C")"
g3_l3="$(g_line_of "$G3_H" "$G_S3")"; g3_l4a="$(g_line_of "$G3_H" "$G_S4A")"
g3_l4b="$(g_line_of "$G3_H" "$G_S4B")"
fleet lint --instant "$PROSE" --porcelain > "$OUT/G3-lint.tsv" 2>&1
g3_rc=$?

g_shape_verdict() {               # g_shape_verdict <label> <lineno...> -> prints "flagged"/"NOT-FLAGGED"
  local label="$1"; shift
  local n hit=0
  for n in "$@"; do g_flagged "$OUT/G3-lint.tsv" "$n" && hit=1; done
  printf '%s\t%s\tlines=%s\n' "$label" "$([ "$hit" = 1 ] && echo flagged || echo NOT-FLAGGED)" "$*"
  [ "$hit" = 1 ]
}
{ printf '=== shape by shape, against lint on the UNDECLARED instant (rc=%s) ===\n' "$g3_rc"
  g_shape_verdict "1 plain"          "$g3_l1"; g3_s1=$?
  g_shape_verdict "2 bold"           "$g3_l2a" "$g3_l2b" "$g3_l2c"; g3_s2=$?
  g_shape_verdict "3 indented"       "$g3_l3"; g3_s3=$?
  g_shape_verdict "4 trailing prose" "$g3_l4a" "$g3_l4b"; g3_s4=$?
} > "$OUT/G3-shapes.tsv" 2>&1
cat "$OUT/G3-shapes.tsv"
g3_flagged=0
for v in "$g3_s1" "$g3_s2" "$g3_s3" "$g3_s4"; do [ "$v" = 0 ] && g3_flagged=$((g3_flagged + 1)); done

# (b) the same lines WITH a declaration behind them: not a finding.
fleet lint --instant "$DECLARED" --porcelain > "$OUT/G3-lint-declared.tsv" 2>&1
g3_declared_rc=$?
g3_declared_rows="$(g_near_miss_count "$OUT/G3-lint-declared.tsv")"

# (c) the scoping. The control file is chosen BY EXCLUSION from the product's own list.
G3_CONTROL_FILE=DECISIONS.md
g3_control_ok=0
case " $G_NM_FILES " in *" $G3_CONTROL_FILE "*) g3_control_ok=0 ;; *) g3_control_ok=1 ;; esac
g3_before_rows="$(g_near_miss_count "$OUT/G3-lint.tsv")"
cat "$G_BLOCK_FILE" >> "$PROSE/$G3_CONTROL_FILE"
fleet lint --instant "$PROSE" --porcelain > "$OUT/G3-lint-scoped.tsv" 2>&1
g3_after_rows="$(g_near_miss_count "$OUT/G3-lint-scoped.tsv")"
g3_scoped=0
[ "$g3_control_ok" = 1 ] && [ "$g3_before_rows" = "$g3_after_rows" ] && g3_scoped=1
{ printf 'near_miss_rows_handoff_only\t%s\n' "$g3_before_rows"
  printf 'near_miss_rows_after_%s\t%s\n' "$G3_CONTROL_FILE" "$g3_after_rows"
  printf 'near_miss_files_from_product\t%s\n' "$G_NM_FILES"
  printf 'control_file_is_outside_that_list\t%s\n' "$([ "$g3_control_ok" = 1 ] && echo true || echo false)"
  printf 'near_miss_rows_with_a_declaration_behind_them\t%s (lint rc=%s)\n' \
         "$g3_declared_rows" "$g3_declared_rc"
} > "$OUT/G3-scope.tsv"
cat "$OUT/G3-scope.tsv"

if [ "$g3_flagged" = 4 ] && [ "$g3_rc" = 1 ] && [ "$g3_declared_rows" = 0 ] && [ "$g3_scoped" = 1 ]; then
  it_pass G3 "fleet/it/G/out/G3-shapes.tsv" \
    "all four shapes are named by line number as $G_NEAR_MISS findings (lint rc=$g3_rc, $g3_before_rows rows), the identical lines with a real declaration behind them are NOT findings ($g3_declared_rows rows — a rule, not a grep), and appending the identical block to $G3_CONTROL_FILE (outside NEAR_MISS_FILES=$G_NM_FILES, read from the product) moves the count not at all. This is the case that makes G2 and G4 non-vacuous: a lint that flagged nothing would pass both of those trivially and fails here"
else
  it_fail G3 "fleet/it/G/out/G3-shapes.tsv" \
    "THE AUTHOR IS TOLD ABOUT ONLY $g3_flagged OF THE 4 SHAPES Plan 6 requires. \`fleet lint --instant <the instant> --porcelain\` exits $g3_rc with $g3_before_rows $G_NEAR_MISS row(s). Flagged: plain (line $g3_l1) and indented (line $g3_l3). NOT flagged: BOLD in all three renderings ('$G_S2A' line $g3_l2a, '$G_S2B' line $g3_l2b, '$G_S2C' line $g3_l2c) and TRAILING PROSE in both ('$G_S4A' line $g3_l4a, '$G_S4B' line $g3_l4b). Cause: cli._DECLARATION_SHAPED allows an emphasis run only BEFORE the word and anchors the value at end of line, so any closed \`**\` and any explanatory suffix fall out of the population. The bold gap is unambiguous — a bolded phase line carries no retraction language and collides with nothing. The trailing-prose gap is in real tension with G4, whose retraction fixture is ALSO a value followed by prose, and the end-of-line anchor is exactly what buys G4: the two halves of Plan 6 cannot both hold under a shape-only rule, and closing this needs a retraction-aware rule rather than a looser regex. The other three properties DO hold: with a declaration behind them the same lines yield $g3_declared_rows findings, and the rule is scoped to NEAR_MISS_FILES=$G_NM_FILES rather than the folder (adding the block to $G3_CONTROL_FILE left the count at $g3_after_rows)"
fi

# ==================================================================================================
# G4 — A CORRECT RETRACTION IN PROSE, WITH NO LIVE DECLARATION ⇒ **NOT** FLAGGED.
#      Plan 6: the fixture that would have made a naive lint fire on 5 of 5 live instants. Every
#      register that DISCUSSES this defect quotes the line while declaring nothing, and a permanently-red
#      lint trains everyone to ignore red — which costs more than the rule earns.
#
#      Asserted in two phases so it cannot be vacuous. Phase A is the plan's literal case: retraction
#      only ⇒ zero findings, exit 0. Phase B appends ONE genuine near-miss line to the SAME file, so a
#      single `lint` invocation flags that line and neither retraction. Discrimination measured inside one
#      call, not inferred from two.
# ==================================================================================================
{ printf '\n## Current state\n\n%s\n%s\n' "$G_R1" "$G_R2"; } >> "$RETRACT/HANDOFF.md"
fleet lint --instant "$RETRACT" --porcelain > "$OUT/G4-lint-retraction-only.tsv" 2>&1
g4_a_rc=$?
g4_a_rows="$(g_near_miss_count "$OUT/G4-lint-retraction-only.tsv")"

printf '%s\n' "$G_S1" >> "$RETRACT/HANDOFF.md"      # one real near-miss, same file, same lint call
fleet lint --instant "$RETRACT" --porcelain > "$OUT/G4-lint-mixed.tsv" 2>&1
g4_b_rc=$?
g4_b_rows="$(g_near_miss_count "$OUT/G4-lint-mixed.tsv")"
g4_r1="$(g_line_of "$RETRACT/HANDOFF.md" "$G_R1")"
g4_r2="$(g_line_of "$RETRACT/HANDOFF.md" "$G_R2")"
g4_plain="$(g_line_of "$RETRACT/HANDOFF.md" "$G_S1")"
g4_r1_flagged=1; g_flagged "$OUT/G4-lint-mixed.tsv" "$g4_r1" || g4_r1_flagged=0
g4_r2_flagged=1; g_flagged "$OUT/G4-lint-mixed.tsv" "$g4_r2" || g4_r2_flagged=0
g4_plain_flagged=1; g_flagged "$OUT/G4-lint-mixed.tsv" "$g4_plain" || g4_plain_flagged=0
{ printf 'phase A: retraction lines only\trows=%s\trc=%s\n' "$g4_a_rows" "$g4_a_rc"
  printf 'phase B: one plain near-miss appended\trows=%s\trc=%s\n' "$g4_b_rows" "$g4_b_rc"
  printf 'retraction line %s flagged\t%s\n' "$g4_r1" "$g4_r1_flagged"
  printf 'retraction line %s flagged\t%s\n' "$g4_r2" "$g4_r2_flagged"
  printf 'plain line %s flagged\t%s\n' "$g4_plain" "$g4_plain_flagged"
} > "$OUT/G4-discrimination.tsv"
cat "$OUT/G4-discrimination.tsv"
if [ "$g4_a_rows" = 0 ] && [ "$g4_a_rc" = 0 ] && [ "$g4_b_rows" = 1 ] \
   && [ "$g4_plain_flagged" = 1 ] && [ "$g4_r1_flagged" = 0 ] && [ "$g4_r2_flagged" = 0 ]; then
  it_pass G4 "fleet/it/G/out/G4-discrimination.tsv" \
    "a correct retraction in prose with no live declaration is NOT flagged: on its own, both renderings (bare and backticked) give $g4_a_rows findings and lint exits $g4_a_rc — clean. NOT VACUOUS, and not by appeal to another case: one plain near-miss line was appended to the SAME HANDOFF.md and ONE lint call then flags line $g4_plain and neither retraction (lines $g4_r1, $g4_r2), $g4_b_rows row(s) total. So the rule discriminates within a single measurement. This is the fixture Plan 6 names as the one that would have made a naive lint fire on 5 of 5 live instants: every register that DISCUSSES RCF-9 quotes the line, and a permanently-red lint trains everyone to ignore red"
else
  it_fail G4 "fleet/it/G/out/G4-discrimination.tsv" \
    "retraction-only rows=$g4_a_rows rc=$g4_a_rc (want 0/0); mixed rows=$g4_b_rows (want 1) with plain-flagged=$g4_plain_flagged (want 1) retraction-flagged=$g4_r1_flagged/$g4_r2_flagged (want 0/0) — a flagged retraction is the false positive that fires on 5 of 5 live instants"
fi

# ==================================================================================================
# G5 — `park` / `parked` / `unpark` ROUND TRIP; A `<none> — nothing has arisen` LINE IN PROSE ⇒ NO PARK.
#
#      Same shape as G2 one field over, and the same discipline: the inert prose is measured against the
#      consumers that then report a real park, so "no park" cannot pass by a consumer that never reports
#      one. The empty-park refusal is here rather than in G6 because it is the same question asked of the
#      same file — and its answer is the CONTRAST that makes G6's verdict a defect rather than a taste:
#      `park` refuses an empty question with exit 2 and leaves the standing park intact.
# ==================================================================================================
G5_Q='does the reviewer want the split, or is one PR acceptable?'
g5_fleet_before="$(it_manifest "$PARKED/.fleet")"
{ printf '\n## Parked decisions\n\nParked: <none> — nothing has arisen\n<none> — nothing has arisen\n'
} >> "$PARKED/HANDOFF.md"
g5_fleet_after="$(it_manifest "$PARKED/.fleet")"
g5_prose_read="$(g_brief_phase "$PARKED")"

fleet park --instant "$PARKED" --question "$G5_Q" --porcelain > "$OUT/G5-park.tsv" 2>&1
g5_park_rc=$?
g5_park_echo="$(awk -F'\t' '$1=="parked"{print $2}' "$OUT/G5-park.tsv")"
g5_parked_read="$(g_brief_phase "$PARKED")"

fleet park --instant "$PARKED" --question "" --porcelain > "$OUT/G5-park-empty.tsv" 2>&1
g5_empty_rc=$?
g5_after_empty="$(g_brief_phase "$PARKED")"

fleet unpark --instant "$PARKED" --porcelain > "$OUT/G5-unpark.tsv" 2>&1
g5_unpark_rc=$?
g5_cleared="$(awk -F'\t' '$1=="cleared"{print $2}' "$OUT/G5-unpark.tsv")"
g5_unparked_read="$(g_brief_phase "$PARKED")"
{ printf 'after the <none> prose\t%s\n' "$g5_prose_read"
  printf 'fleet_dir_unchanged_across_the_prose_write\t%s\n' \
         "$([ "$g5_fleet_before" = "$g5_fleet_after" ] && echo true || echo false)"
  printf 'park rc=%s echoed\t%s\n' "$g5_park_rc" "$g5_park_echo"
  printf 'after park\t%s\n' "$g5_parked_read"
  printf 'park --question "" rc=%s\n' "$g5_empty_rc"
  printf 'after the refused empty park\t%s\n' "$g5_after_empty"
  printf 'unpark rc=%s cleared\t%s\n' "$g5_unpark_rc" "$g5_cleared"
  printf 'after unpark\t%s\n' "$g5_unparked_read"
} > "$OUT/G5-roundtrip.tsv"
cat "$OUT/G5-roundtrip.tsv"
g5_ok=0
[ "$g5_prose_read" = "phase=(none declared), parked=(not parked)" ] \
  && [ "$g5_fleet_before" = "$g5_fleet_after" ] \
  && [ "$g5_park_rc" = 0 ] && [ "$g5_park_echo" = "$G5_Q" ] \
  && [ "$g5_parked_read" = "phase=(none declared), parked=$G5_Q" ] \
  && [ "$g5_empty_rc" = 2 ] && [ "$g5_after_empty" = "phase=(none declared), parked=$G5_Q" ] \
  && [ "$g5_unpark_rc" = 0 ] && [ "$g5_cleared" = "$G5_Q" ] \
  && [ "$g5_unparked_read" = "phase=(none declared), parked=(not parked)" ] && g5_ok=1
if [ "$g5_ok" = 1 ]; then
  it_pass G5 "fleet/it/G/out/G5-roundtrip.tsv" \
    "the full round trip through a FRESH consumer at every step: two \`<none> — nothing has arisen\` lines in HANDOFF.md leave \`brief\` at parked=(not parked) with \`.fleet/\` unchanged in content and mtime; \`park\` then makes the same consumer report the question verbatim; \`unpark\` names what it cleared and the consumer returns to (not parked). NOT VACUOUS: the same consumer that reports 'no park' for the prose reports the real park two steps later, so a consumer that never reported one would fail here. And \`park --question \"\"\` exits 2 with the STANDING PARK INTACT — the same store, the same file, the empty argument refused and nothing overwritten, which is exactly what G6 asks of \`declare\`"
else
  it_fail G5 "fleet/it/G/out/G5-roundtrip.tsv" \
    "prose-read='$g5_prose_read' fleet-dir-unchanged=$([ "$g5_fleet_before" = "$g5_fleet_after" ] && echo true || echo false) park(rc=$g5_park_rc,echo='$g5_park_echo')-> '$g5_parked_read'; empty-park rc=$g5_empty_rc -> '$g5_after_empty'; unpark(rc=$g5_unpark_rc,cleared='$g5_cleared') -> '$g5_unparked_read'"
fi

# ==================================================================================================
# G6 — `declare --phase ""` ⇒ EXIT 2, AND THE PHASE IS UNCHANGED (NOT SILENTLY CLEARED).
#
#      Measured on an instant that already carries the four prose shapes, so the CONSEQUENCE of whatever
#      the verb does is visible in the same run rather than argued about: the near-miss rule is switched
#      off by `declared is not None`, and the empty string is not None.
# ==================================================================================================
cat "$G_BLOCK_FILE" >> "$EMPTY/HANDOFF.md"
fleet lint --instant "$EMPTY" --porcelain > "$OUT/G6-lint-before.tsv" 2>&1
g6_lint_before_rc=$?
g6_rows_before="$(g_near_miss_count "$OUT/G6-lint-before.tsv")"

fleet declare --instant "$EMPTY" --phase "$G_CI_TOKEN" --porcelain > "$OUT/G6-declare-real.tsv" 2>&1
g6_before_sha="$(sha256sum "$EMPTY/.fleet/declare.json" 2>/dev/null | cut -c1-12)"
g6_before_read="$(g_brief_phase "$EMPTY")"

fleet declare --instant "$EMPTY" --phase "" --porcelain > "$OUT/G6-declare-empty.tsv" 2>&1
g6_rc=$?
cat "$OUT/G6-declare-empty.tsv"
g6_after_sha="$(sha256sum "$EMPTY/.fleet/declare.json" 2>/dev/null | cut -c1-12)"
g6_after_read="$(g_brief_phase "$EMPTY")"
fleet lint --instant "$EMPTY" --porcelain > "$OUT/G6-lint-after.tsv" 2>&1
g6_lint_after_rc=$?
g6_rows_after="$(g_near_miss_count "$OUT/G6-lint-after.tsv")"
g6_lint_sees="$(g_lint_declared "$OUT/G6-lint-after.tsv")"
{ printf 'lint before any declaration\trows=%s\trc=%s\n' "$g6_rows_before" "$g6_lint_before_rc"
  printf 'after declare --phase %s\tstate=%s\tdeclare.json sha12=%s\n' \
         "$G_CI_TOKEN" "$g6_before_read" "$g6_before_sha"
  printf 'declare --phase "" rc\t%s\t(Plan 6 requires 2)\n' "$g6_rc"
  printf 'after declare --phase ""\tstate=%s\tdeclare.json sha12=%s\n' "$g6_after_read" "$g6_after_sha"
  printf 'stored phase, raw\t%s\n' "$(tr -d ' \n' < "$EMPTY/.fleet/declare.json")"
  printf 'lint after the empty declaration\trows=%s\trc=%s\tlint sees phase=%s\n' \
         "$g6_rows_after" "$g6_lint_after_rc" "$g6_lint_sees"
} > "$OUT/G6-empty-phase.tsv"
cat "$OUT/G6-empty-phase.tsv"
g6_unchanged=0
[ "$g6_before_sha" = "$g6_after_sha" ] && [ "$g6_before_read" = "$g6_after_read" ] && g6_unchanged=1
if [ "$g6_rc" = 2 ] && [ "$g6_unchanged" = 1 ]; then
  it_pass G6 "fleet/it/G/out/G6-empty-phase.tsv" \
    "\`declare --phase \"\"\` exits 2 and the declaration is untouched: declare.json sha12 $g6_before_sha before and after, and \`brief\` still reads '$g6_after_read'. An empty argument is refused rather than applied, so the phase cannot be cleared by a verb whose job is to set one"
else
  it_fail G6 "fleet/it/G/out/G6-empty-phase.tsv" \
    "PRODUCT DEFECT. \`fleet declare --instant <the instant> --phase \"\" --porcelain\` exits $g6_rc (Plan 6 requires 2) and SILENTLY CLEARS THE PHASE: declare.json goes from sha12 $g6_before_sha to $g6_after_sha, the stored value from '$G_CI_TOKEN' to the empty string, and \`brief\` from '$g6_before_read' to '$g6_after_read'. Cause: _normalise_phase(\"\") returns \"\", which is not None, so set_phase STORES it and _do_declare's own no-op guard (\`if value is None\`) does not fire — the one check meant to catch a declaration that did not land. THE CONSEQUENCE, measured in this run on the same instant: lint went from $g6_rows_before near-miss row(s) at rc=$g6_lint_before_rc to $g6_rows_after at rc=$g6_lint_after_rc, because near_miss_rows skips every line when \`declared is not None\`. So \`declare --phase \"\"\` buys SILENCE from the RCF-9 control while buying no exclusion at all: the WIP cap compares the phase against '$G_CI_TOKEN' and an empty string is not it, and every consumer reports '$g6_after_read'. Contrast \`park\`, asserted in G5 on the same file: an empty question exits 2 and leaves the standing value intact"
fi

# ==================================================================================================
# G7 — A DECLARATION SURVIVES AN INSTANT RENAME (`.fleet/` MOVES WITH THE FOLDER).
#
#      The worker's own rename IS its completion signal, so every recorded path goes stale at exactly the
#      moment the work finishes. Three readers are asked through the STALE path — `identity.resolve` from
#      an argument (`brief`) and from a RECORD (`status`, via `_child_of`) — and the control is a rename
#      that must NOT resolve: `stable_key` varies only `state`, never a prefix, so changing the NAME
#      field has to be refused rather than matched to the nearest sibling (`OBS-14`).
# ==================================================================================================
G7_Q='is the base position right for this milestone?'
fleet declare --instant "$RENAME" --phase "$G_CI_TOKEN" --porcelain > "$OUT/G7-declare.tsv" 2>&1
fleet park --instant "$RENAME" --question "$G7_Q" --porcelain > "$OUT/G7-park.tsv" 2>&1
G7_TID="$(fleet resume --instant "$RENAME" --porcelain 2>&1 | awk -F'\t' '$1=="todo_id"{print $2}')"
g7_before_read="$(g_brief_phase "$RENAME")"

# The rename, on the BASENAME only: the parent path may itself contain `-inflight-`, and a substitution
# over the whole path is how a fixture renames somebody else's workspace.
G7_BASE="$(basename "$RENAME")"; G7_DIR="$(dirname "$RENAME")"
G7_NEW="$G7_DIR/${G7_BASE/-inflight-/-complete-}"
mv "$RENAME" "$G7_NEW"
g7_moved=0
[ -f "$G7_NEW/.fleet/declare.json" ] && [ ! -e "$RENAME" ] && g7_moved=1

fleet brief --instant "$RENAME" --porcelain > "$OUT/G7-brief-stale.tsv" 2>&1
g7_stale_rc=$?
g7_stale_read="$(awk -F'\t' '$1=="phase"{print $4}' "$OUT/G7-brief-stale.tsv")"
fleet brief --instant "$G7_NEW" --porcelain > "$OUT/G7-brief-new.tsv" 2>&1
g7_new_read="$(awk -F'\t' '$1=="phase"{print $4}' "$OUT/G7-brief-new.tsv")"
fleet status --porcelain --id "$G7_TID" > "$OUT/G7-status.tsv" 2>&1
g7_status_rc=$?
g7_join_phase="$(awk -F'\t' '$1=="evidence.declared_phase"{print $2}' "$OUT/G7-status.tsv")"
g7_join_park="$(awk -F'\t' '$1=="evidence.parked"{print $2}' "$OUT/G7-status.tsv")"
g7_folder="$(awk -F'\t' '$1=="evidence.folder_state"{print $2}' "$OUT/G7-status.tsv")"

# The control: the NAME field changes too, so the stable key no longer matches and nothing may resolve.
G7_OTHER="$G7_DIR/${G7_BASE/-inflight-append-grename/-complete-append-grenameElse}"
mv "$G7_NEW" "$G7_OTHER"
fleet brief --instant "$RENAME" --porcelain > "$OUT/G7-brief-control.tsv" 2>&1
g7_control_rc=$?
mv "$G7_OTHER" "$G7_NEW"
{ printf 'before the rename\t%s\n' "$g7_before_read"
  printf 'declare.json moved with the folder\t%s\n' "$([ "$g7_moved" = 1 ] && echo true || echo false)"
  printf 'brief via the STALE path (rc=%s)\t%s\n' "$g7_stale_rc" "$g7_stale_read"
  printf 'brief via the NEW path\t%s\n' "$g7_new_read"
  printf 'status via the RECORD (rc=%s)\tphase=%s parked=%s folder_state=%s\n' \
         "$g7_status_rc" "$g7_join_phase" "$g7_join_park" "$g7_folder"
  printf 'control: the NAME field changed too, brief rc\t%s\t(want 2)\n' "$g7_control_rc"
} > "$OUT/G7-rename.tsv"
cat "$OUT/G7-rename.tsv"
G7_WANT="phase=$G_CI_TOKEN, parked=$G7_Q"
g7_ok=0
[ "$g7_moved" = 1 ] && [ "$g7_stale_rc" = 0 ] && [ "$g7_stale_read" = "$G7_WANT" ] \
  && [ "$g7_new_read" = "$G7_WANT" ] && [ "$g7_status_rc" = 0 ] \
  && [ "$g7_join_phase" = "$G_CI_TOKEN" ] && [ "$g7_join_park" = "$G7_Q" ] \
  && [ "$g7_folder" = complete ] && [ "$g7_control_rc" = 2 ] && g7_ok=1
if [ "$g7_ok" = 1 ]; then
  it_pass G7 "fleet/it/G/out/G7-rename.tsv" \
    "a phase AND a parked question survive the rename that IS the completion signal: \`.fleet/declare.json\` moved with the folder (present at the new path, the old path gone), and both readings still say '$G7_WANT' — through the STALE argument path (\`brief\`, which resolves via identity.resolve) and through the RECORD, whose child_instant predates the rename (\`status\`, via _child_of), where the join also reports folder_state=$g7_folder. NOT VACUOUS: the control renames the NAME field as well as the state, and the stale path is then REFUSED with exit $g7_control_rc — resolution matches the full stable key with only \`state\` varying, so it cannot have passed by finding the nearest sibling (OBS-14: two instants dispatched in the same minute share base-curr)"
else
  it_fail G7 "fleet/it/G/out/G7-rename.tsv" \
    "moved=$g7_moved stale(rc=$g7_stale_rc)='$g7_stale_read' new='$g7_new_read' want='$G7_WANT'; join(rc=$g7_status_rc) phase='$g7_join_phase' parked='$g7_join_park' folder='$g7_folder'; control rc=$g7_control_rc (want 2, a refusal)"
fi

it_assert_isolation G-leave
bash "$IT_ROOT/bin/source-pin.sh" after "$OUT" || { echo "CONTAMINATED — no verdict" >&2; exit 3; }
sed -i "s|$INSTANT/||g" "$RESULTS"
echo "§G done: IT_FAILED=$IT_FAILED"
exit "$IT_FAILED"
