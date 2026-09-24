#!/usr/bin/env bash
# SI-9 — M9's delete-site rule, verified by MUTATION.
#
# M9 is a CEILING on where the package may delete. Its value comes from being hard to widen, so widening it
# is exactly the change that must be shown to still fail. The old rule was a substring test —
# `"self.enrolled" in body or "self.leases" in body` — which rejected `atomic.py`'s two staging deletes even
# though their targets derive from the function's own operand. The fix widened the RULE (follow the
# assignments) rather than adding names to the allowlist, because an allowlist entry says "somebody decided
# this one is fine" while a rule says what makes ANY delete fine and can still fire.
#
# Four mutations, each on a `cp -r` copy, each target asserted **present-and-unique** before injection, and
# every copy asserted byte-identical to the package the baseline just proved GREEN before it is mutated — a
# killer verified against a red baseline proves nothing. The mutations, their anchors and the rule that reads
# each outcome live in `m9_mutations.py`, which the hermetic `tests/test_m9_mutations.py` also imports.
#
# `FB-108`: a mutation that did not APPLY is `FAIL … NOT-APPLIED`, and its copy is never audited. It used to be
# audited anyway, pass as the un-mutated package it was, and read as SURVIVED.
#
#   M1  a second assignment putting the target under $HOME          -> SURVIVED-then-KILLED (see below)
#   M2  a delete of an absolute string literal                             -> killed
#   M3  a brand-new undeclared delete site (the allowlist ceiling)   -> killed
#   M4  a target read out of the environment                        -> killed
#
# **M1 is reported as `SURVIVED-then-KILLED`, never as a plain kill** — the convention `FI-28` established,
# because a mutation score that hides a first-pass survival is the same class as a green suite hiding an
# unrun section. It survived because the first version of `derivation_ok` returned True on the FIRST
# assignment it found that mentioned the store root, so leaving the original safe line in place next to a
# poisoned one satisfied it. The rule now requires EVERY assignment to the deleted name to be safe. That
# word was bought by this mutation.
#
# Run: bash fleet/it/run-m9-mutation.sh
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
it_own_cases 'M9-mut-(baseline|1|2|3|4)|ISOLATION-M9mut-(enter|leave)'

EV="$IT_ROOT/M9-mutation"
mkdir -p "$EV"

# A2c. This runner needs no FLEET_HOME — it only reads source trees — but it must still prove it touched
# nothing, so the isolation contract is asserted directly. `SECTION` is set because the check names its
# per-section dt- record from it.
# shellcheck disable=SC2034  # consumed by lib.sh's per-section helpers
SECTION=M9mut
it_assert_isolation M9mut-enter

# The audit under test, extracted from the runner that owns it so this script cannot drift from it. The old
# copy is removed first and the extraction's exit status is checked: `m9.py` persists in `$EV` between runs,
# so an extraction that failed silently used to audit every mutant with a stale rule.
rm -f "$EV/m9.py"
if ! python3 - "$IT_ROOT/run-group5.sh" "$EV/m9.py" <<'PY'
import pathlib, sys
src = pathlib.Path(sys.argv[1]).read_text()
start = src.index('cat > "$PY_DIR/m9.py" <<')
body = src.index('\n', start) + 1
end = src.index('\nPY\n', body)
pathlib.Path(sys.argv[2]).write_text(src[body:end] + '\n')
print(f"extracted the M9 audit: {len(src[body:end].splitlines())} lines")
PY
then
  it_fail M9-mut-baseline "fleet/it/run-group5.sh" \
    "could not extract the M9 audit from run-group5.sh, so there is no rule to mutate against"
  exit 1
fi

run_audit() {                 # run_audit <instant-root> <logfile>  -> exit code of the audit
  INSTANT="$1" PYTHONPATH="$1/src" python3 "$EV/m9.py" > "$2" 2>&1
}

# --- baseline: the REAL package must pass, or every kill below is noise ----------------------------
if run_audit "$INSTANT" "$EV/real.out"; then
  it_pass M9-mut-baseline "fleet/it/M9-mutation/real.out" \
    "the real package passes the widened rule: every delete target is DERIVED (by following the assignments, not by matching a substring) from the store root or from that function's own parameters"
else
  it_fail M9-mut-baseline "fleet/it/M9-mutation/real.out" \
    "the audit does not pass on the unmutated package, so no kill below means anything: $(grep -m1 -E 'AssertionError|Error' "$EV/real.out" | cut -c1-200)"
  echo "baseline is red — refusing to report mutation results" >&2
  exit 1
fi

# --- the four mutations ---------------------------------------------------------------------------
M9MUT="$IT_ROOT/m9_mutations.py"
declare -A APPLIED=()
for n in 1 2 3 4; do
  rm -rf "$EV/mut$n"; mkdir -p "$EV/mut$n"; cp -r "$INSTANT/src" "$EV/mut$n/"
  #: `tests/` as well as `src/`, since `II-3`: the audit imports OUTWARD_CALL_SITES from
  #: `$INSTANT/tests/test_cli.py` as the authority for which delete sites are argued for. A mutant tree
  #: with no `tests/` makes every mutant die of ModuleNotFoundError, which is a kill for the wrong
  #: reason and proves nothing about the audit.
  #:
  #: Caught by this runner itself, on release 0.2.0, reporting exactly that: "died for the WRONG reason
  #: — a kill that is really an import failure proves nothing". The `II-3` change was checked against
  #: the extracted audit and against the real package, and not against a mutant tree; the case that
  #: exists to notice a kill arriving for the wrong reason is what noticed.
  cp -r "$INSTANT/tests" "$EV/mut$n/"
  #: The copy IS the package the baseline just proved green, byte for byte, before anything is injected.
  if ! diff -rq "$INSTANT/src" "$EV/mut$n/src" > "$EV/mut$n.inject" 2>&1; then
    echo "  NOT APPLIED — M$n: the copy differs from the package the baseline audited; nothing injected" \
      >> "$EV/mut$n.inject"
    cat "$EV/mut$n.inject"
    continue
  fi
  #: One process per mutation, its exit status checked, and the mutated file compared with the original.
  #: APPLIED is set only when the injection says so AND the bytes on disk changed. A single heredoc for all
  #: four is what let M2's failed assert abort M3 and M4 unnoticed (FB-108).
  #: `cmp` exits 1 for "differ" and 2 for an error (a missing file, an empty `rel`); only 1 counts.
  rel="$(python3 "$M9MUT" rel "$n")"
  [ -n "$rel" ] || echo "  NOT APPLIED — M$n: m9_mutations.py named no file to mutate" >> "$EV/mut$n.inject"
  if [ -n "$rel" ] && python3 "$M9MUT" inject "$EV/mut$n" "$n" >> "$EV/mut$n.inject" 2>&1; then
    cmp -s "$INSTANT/$rel" "$EV/mut$n/$rel"; cmp_rc=$?
    if [ "$cmp_rc" -eq 1 ]; then
      APPLIED[$n]=1
    else
      echo "  NOT APPLIED — M$n: cmp of $rel against the original exited $cmp_rc, not 1 (differ)" >> "$EV/mut$n.inject"
    fi
  fi
  cat "$EV/mut$n.inject"
done

#: What each mutation must be caught BY is its `why` in m9_mutations.py, and `classify` there is the only
#: place an outcome becomes a verdict. A kill for the wrong reason is not a kill: a copy that fails to import
#: also exits non-zero, and an early version of this check "killed" all four that way while none of the
#: mutations had actually been applied. M2's expected reason ("could not name") and why it is not the
#: unrooted one are written down beside its entry there.
declare -A WHAT=(
  [1]="a second assignment putting the delete target under \$HOME. Reported SURVIVED-then-KILLED (FI-28's convention): it survived the first rule, which accepted a name if ANY of its assignments looked rooted, and forced the rule to require EVERY assignment to be safe"
  # The backticks below are ESCAPED, deliberately. Unescaped, bash reads them as a command substitution
  # even inside double quotes, tries to run `<abs>` — a redirect from a file named `abs` — prints
  # "syntax error near unexpected token `newline'" on stderr, and substitutes the empty string. So this
  # note rendered as "quoted here as  so the note itself…" in every run since it was written, and the
  # case PASSed regardless. A case whose own evidence text is silently rewritten by the shell cannot be
  # trusted to say what it did.
  [2]="a delete of an absolute string literal (quoted here as \`<abs>\` so the note itself does not trip lint-evidence-paths: the injected call is os.unlink of a hard-coded path under var-tmp). Caught on the UNVERIFIABLE branch, not the unrooted one: a string literal leaves no name to trace, so the audit refuses to vouch for it at all"
  [3]="a brand-new delete site the allowlist does not declare — the ceiling itself"
  [4]="a delete target read out of os.environ['HOME']"
)


for n in 1 2 3 4; do
  why="$(python3 "$M9MUT" why "$n")"
  if [ -n "${APPLIED[$n]:-}" ]; then
    run_audit "$EV/mut$n" "$EV/mut$n.out"; audit_rc=$?
    read -r verdict kind < <(python3 "$M9MUT" classify "$n" 1 "$audit_rc" "$EV/mut$n.out")
  else
    #: Never audited: an un-mutated copy passes, and that pass is no verdict on the rule (FB-108).
    read -r verdict kind < <(python3 "$M9MUT" classify "$n" 0 - -)
  fi
  case "$kind" in
    KILLED)
      it_pass "M9-mut-$n" "fleet/it/M9-mutation/mut$n.out" \
        "KILLED by the named check ($why): ${WHAT[$n]}" ;;
    SURVIVED)
      it_fail "M9-mut-$n" "fleet/it/M9-mutation/mut$n.out" \
        "SURVIVED: ${WHAT[$n]} — the mutation WAS applied (inject verified the write and cmp found the mutant differs from the original) and the rule did not fire, so it is decoration on this shape" ;;
    WRONG-REASON)
      it_fail "M9-mut-$n" "fleet/it/M9-mutation/mut$n.out" \
        "died for the WRONG reason — a kill that is really an import failure proves nothing: $(grep -m1 -E 'Error' "$EV/mut$n.out" | cut -c1-200)" ;;
    NOT-APPLIED)
      it_fail "M9-mut-$n" "fleet/it/M9-mutation/mut$n.inject" \
        "NOT-APPLIED: the mutation was never written into its copy, so the audit was not run on it — neither a kill nor a survival, a harness defect: $(grep -m1 'NOT APPLIED' "$EV/mut$n.inject" | cut -c1-200)" ;;
    *)
      it_fail "M9-mut-$n" "fleet/it/M9-mutation/mut$n.inject" \
        "no verdict: m9_mutations.py classify printed '${verdict:-} ${kind:-}'" ;;
  esac
done

it_assert_isolation M9mut-leave
sed -i "s|$INSTANT/||g" "$RESULTS"
echo "M9 mutation check done: IT_FAILED=$IT_FAILED"
#: `II-11`. Was `exit "$IT_FAILED"` — a COUNT. `exit` truncates modulo 256, so a section with
#: exactly 256 failures reported SUCCESS, and one with 300 reported 44, a number meaning nothing
#: to any reader. An exit status is a one-byte verdict, not a tally: the count is already printed
#: on the line above and is in the register, which is where a consumer should read it anyway.
if [ "${IT_FAILED:-0}" -eq 0 ]; then exit 0; fi
exit 1
