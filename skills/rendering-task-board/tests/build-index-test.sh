#!/usr/bin/env bash
# Hermetic self-test for build-index.py. Path-independent. Prints PASS/FAIL, exits non-zero on failure.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tool="$here/../build-index.py"
board="$here/fixtures/board"
expected="$here/fixtures/expected-index.md"
fail=0

# --- Test 1: rolled-up board matches golden (status-grouped, class sub-grouped, deduped-by-file) ---
tmp="$(mktemp)"
python3 "$tool" "$board" > "$tmp" 2>/dev/null || { echo "  FAIL - builder exited non-zero"; fail=1; }
if diff -u "$expected" "$tmp" > /tmp/idx-diff.$$ 2>&1; then
  echo "  ok   - golden index matches"
else
  echo "  FAIL - golden index mismatch:"; sed 's/^/      /' /tmp/idx-diff.$$; fail=1
fi
rm -f /tmp/idx-diff.$$

# --- Test 2: superseded ticket is grouped as superseded, not Done or Open ---
if awk '/^## ⛔ Superseded/{f=1} /gap-99-old/{if(f)print "yes"}' "$tmp" | grep -q yes; then
  echo "  ok   - superseded ticket bucketed correctly"
else echo "  FAIL - superseded ticket mis-bucketed"; fail=1; fi

# --- Test 3: --write updates only the AUTO region, preserving author prose ---
work="$(mktemp -d)"; cp "$board"/*.md "$work"/
cat > "$work/00-INDEX.md" <<'EOF'
# Demo — status board
North star prose the author owns.
<!-- board:auto:start -->
STALE — should be replaced
<!-- board:auto:end -->
Footer prose the author owns.
EOF
python3 "$tool" --write "$work" >/dev/null 2>&1
if grep -q "North star prose the author owns." "$work/00-INDEX.md" \
   && grep -q "Footer prose the author owns." "$work/00-INDEX.md" \
   && grep -q '`gap-01-demo`' "$work/00-INDEX.md" \
   && ! grep -q "STALE" "$work/00-INDEX.md"; then
  echo "  ok   - --write refreshes AUTO region, keeps prose"
else echo "  FAIL - --write did not update AUTO region correctly"; fail=1; fi

# --- Test 4: --check passes when index is in sync, fails after a ticket status drifts ---
python3 "$tool" --check "$work" >/dev/null 2>&1 && echo "  ok   - --check clean when in sync" \
  || { echo "  FAIL - --check flagged an in-sync board"; fail=1; }
# perturb: no Status line
printf '# [Bad] no status line here\n\nnothing\n' > "$work/gap-77-broken.md"
if python3 "$tool" --check "$work" >/dev/null 2>&1; then
  echo "  FAIL - --check passed a ticket with no Status line"; fail=1
else echo "  ok   - --check catches a Status-less ticket"; fi

# --- Test 5: 00-INDEX.md itself is never treated as a ticket ---
if grep -q '`00-INDEX`' "$tmp"; then echo "  FAIL - index listed itself as a ticket"; fail=1
else echo "  ok   - index file excluded from tickets"; fi

# --- Test 6: inline **Status:** metadata + tracker-prefixed id (ENG-455NN-scope-…) ---
real="$(mktemp -d)"
cat > "$real/ENG-45525-scope-09-real-shape.md" <<'EOF'
# [SCOPING] A real-shaped scope ticket

**Epic:** X · **Type:** Scoping task · **Status:** OPEN (not yet scoped) · **Priority:** Medium

## Why
Body.
EOF
r6="$(python3 "$tool" "$real" 2>/dev/null)"
if printf '%s' "$r6" | grep -q '### Next effort — scope' \
   && printf '%s' "$r6" | grep -q '`ENG-45525-scope-09-real-shape` | A real-shaped scope ticket | OPEN (not yet scoped) |'; then
  echo "  ok   - inline Status + tracker-prefixed id parsed and class-grouped"
else echo "  FAIL - inline Status / tracker-prefixed id not handled:"; printf '%s\n' "$r6" | sed 's/^/      /'; fail=1; fi
rm -rf "$real"

rm -rf "$work" "$tmp"
if [ $fail = 0 ]; then echo "PASS"; else echo "FAIL"; fi
exit $fail
