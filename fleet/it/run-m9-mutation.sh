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
# every copy asserted GREEN before it is mutated — a killer verified against a red baseline proves nothing.
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
# Run: bash evidence/04-integration/run-m9-mutation.sh
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
it_own_cases 'M9-mut-(baseline|1|2|3|4)|ISOLATION-M9mut-(enter|leave)'

EV="$IT_ROOT/M9-mutation"
mkdir -p "$EV"

# A2c. This runner needs no FLEET_HOME — it only reads source trees — but it must still prove it touched
# nothing, so the isolation contract is asserted directly. `SECTION` is set because the check names its
# per-section dt- record from it.
SECTION=M9mut
it_assert_isolation M9mut-enter

# The audit under test, extracted from the runner that owns it so this script cannot drift from it.
python3 - "$IT_ROOT/run-group5.sh" "$EV/m9.py" <<'PY'
import pathlib, sys
src = pathlib.Path(sys.argv[1]).read_text()
start = src.index('cat > "$PY_DIR/m9.py" <<')
body = src.index('\n', start) + 1
end = src.index('\nPY\n', body)
pathlib.Path(sys.argv[2]).write_text(src[body:end] + '\n')
print(f"extracted the M9 audit: {len(src[body:end].splitlines())} lines")
PY

run_audit() {                 # run_audit <instant-root> <logfile>  -> exit code of the audit
  INSTANT="$1" PYTHONPATH="$1/src" python3 "$EV/m9.py" > "$2" 2>&1
}

# --- baseline: the REAL package must pass, or every kill below is noise ----------------------------
if run_audit "$INSTANT" "$EV/real.out"; then
  it_pass M9-mut-baseline "evidence/04-integration/M9-mutation/real.out" \
    "the real package passes the widened rule: every delete target is DERIVED (by following the assignments, not by matching a substring) from the store root or from that function's own parameters"
else
  it_fail M9-mut-baseline "evidence/04-integration/M9-mutation/real.out" \
    "the audit does not pass on the unmutated package, so no kill below means anything: $(grep -m1 -E 'AssertionError|Error' "$EV/real.out" | cut -c1-200)"
  echo "baseline is red — refusing to report mutation results" >&2
  exit 1
fi

# --- the four mutations ---------------------------------------------------------------------------
for n in 1 2 3 4; do
  rm -rf "$EV/mut$n"; mkdir -p "$EV/mut$n"; cp -r "$INSTANT/src" "$EV/mut$n/"
done

python3 - "$EV" <<'PY'
import pathlib, sys
EV = pathlib.Path(sys.argv[1])

def inject(rel, old, new, label):
    path = EV / rel
    text = path.read_text()
    count = text.count(old)
    #: present-and-unique, asserted. A mutation applied twice, or not at all, makes the kill unattributable —
    #: and a `cp -r` copy is exactly where that goes unnoticed.
    assert count == 1, f"{label}: anchor appears {count} times, not once"
    path.write_text(text.replace(old, new))
    print(f"  {label}: injected")

inject("mut1/src/fleet/pool.py", "        record.unlink()",
       "        record = Path.home() / 'victim.json'\n        record.unlink()",
       "M1 a second assignment putting the target under $HOME")
inject("mut2/src/fleet/atomic.py", "            os.unlink(tmp)",
       "            os.unlink('/var/tmp/whatever')",
       "M2 a delete of an absolute literal")
inject("mut3/src/fleet/store.py", "\nimport ",
       "\ndef _sneaky_cleanup(victim):\n    victim.unlink()\n\n\nimport ",
       "M3 a brand-new undeclared delete site")
inject("mut4/src/fleet/pool.py", "        record.unlink()",
       "        import os as _o\n        record = Path(_o.environ['HOME']) / 'x.json'\n"
       "        record.unlink()",
       "M4 a target read out of the environment")
PY

#: What each mutation must be caught BY. A kill for the wrong reason is not a kill: a copy that fails to
#: import also exits non-zero, and an early version of this check "killed" all four that way while none of
#: the mutations had actually been applied.
#: M2's expected reason is NOT "derived neither from the store root", which is what I first predicted and
#: what this check then rejected as a kill for the wrong reason. `os.unlink('/var/tmp/whatever')` passes a
#: string literal, so there is no local name to trace and the audit takes its *unverifiable* branch instead:
#: "deletes something this audit could not name". That is a legitimate kill and arguably the stronger one —
#: the audit refuses to pass a delete it cannot attribute at all, rather than reasoning about it. The
#: expectation was wrong, not the rule, and the distinction only surfaced because this table demands a
#: reason rather than accepting any non-zero exit.
declare -A WHY=(
  [1]="derived neither from the store root"
  [2]="could not name"
  [3]="UNDECLARED DELETE SITE"
  [4]="derived neither from the store root"
)
declare -A WHAT=(
  [1]="a second assignment putting the delete target under \$HOME. Reported SURVIVED-then-KILLED (FI-28's convention): it survived the first rule, which accepted a name if ANY of its assignments looked rooted, and forced the rule to require EVERY assignment to be safe"
  [2]="a delete of an absolute string literal (quoted here as `<abs>` so the note itself does not trip lint-evidence-paths: the injected call is os.unlink of a hard-coded path under var-tmp). Caught on the UNVERIFIABLE branch, not the unrooted one: a string literal leaves no name to trace, so the audit refuses to vouch for it at all"
  [3]="a brand-new delete site the allowlist does not declare — the ceiling itself"
  [4]="a delete target read out of os.environ['HOME']"
)

for n in 1 2 3 4; do
  if run_audit "$EV/mut$n" "$EV/mut$n.out"; then
    it_fail "M9-mut-$n" "evidence/04-integration/M9-mutation/mut$n.out" \
      "SURVIVED: ${WHAT[$n]} — the rule did not fire, so it is decoration on this shape"
  elif grep -q "${WHY[$n]}" "$EV/mut$n.out"; then
    it_pass "M9-mut-$n" "evidence/04-integration/M9-mutation/mut$n.out" \
      "KILLED by the named check (${WHY[$n]}): ${WHAT[$n]}"
  else
    it_fail "M9-mut-$n" "evidence/04-integration/M9-mutation/mut$n.out" \
      "died for the WRONG reason — a kill that is really an import failure proves nothing: $(grep -m1 -E 'Error' "$EV/mut$n.out" | cut -c1-200)"
  fi
done

it_assert_isolation M9mut-leave
sed -i "s|$INSTANT/||g" "$RESULTS"
echo "M9 mutation check done: IT_FAILED=$IT_FAILED"
exit "$IT_FAILED"
