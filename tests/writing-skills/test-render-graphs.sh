#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SCRIPT_UNDER_TEST="$REPO_ROOT/skills/writing-skills/render-graphs.js"
NODE_BIN="$(command -v node)"

PASSES=0
FAILURES=0
SKIPPED=0
TEST_ROOT="$(mktemp -d)"

cleanup() {
  rm -rf "$TEST_ROOT"
}
trap cleanup EXIT

pass() {
  echo "  [PASS] $1"
  PASSES=$((PASSES + 1))
}

fail() {
  echo "  [FAIL] $1"
  FAILURES=$((FAILURES + 1))
}

# A precondition this suite cannot satisfy is NOT a pass. It is reported as its own
# outcome, counted separately, and exits 2 -- so "nothing failed" can never be read as
# "rendering was verified" on a box with no Graphviz.
skip() {
  echo "  [SKIP] $1"
  SKIPPED=$((SKIPPED + 1))
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  local description="$3"

  if printf '%s' "$haystack" | grep -Fq -- "$needle"; then
    pass "$description"
  else
    fail "$description"
    echo "    expected to find: $needle"
  fi
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  local description="$3"

  if printf '%s' "$haystack" | grep -Fq -- "$needle"; then
    fail "$description"
    echo "    did not expect to find: $needle"
  else
    pass "$description"
  fi
}

fixture="$TEST_ROOT/fixture-skill"
mkdir -p "$fixture" "$TEST_ROOT/empty-path"
cat >"$fixture/SKILL.md" <<'EOF'
---
name: fixture-skill
---

# Fixture Skill

```dot
digraph fixture_graph {
  start -> end;
}
```
EOF

echo "Writing-skills render-graphs tests"

missing_dot_output="$(PATH="$TEST_ROOT/empty-path" "$NODE_BIN" "$SCRIPT_UNDER_TEST" "$fixture" 2>&1)"
missing_dot_status=$?

if [[ "$missing_dot_status" -ne 0 ]]; then
  pass "missing Graphviz exits non-zero"
else
  fail "missing Graphviz exits non-zero"
fi
assert_contains "$missing_dot_output" "Error: graphviz (dot) not found." "missing Graphviz reports install guidance"
assert_not_contains "$missing_dot_output" "ReferenceError: require is not defined" "script runs as an ES module"

# Everything below renders for real, which needs Graphviz on PATH. Without it these five
# assertions fail for a reason that has nothing to do with render-graphs.js -- five reds
# indistinguishable from a genuine regression. Check the precondition and say so instead.
if command -v dot >/dev/null 2>&1; then
  render_output="$("$NODE_BIN" "$SCRIPT_UNDER_TEST" "$fixture" 2>&1)"
  render_status=$?

  if [[ "$render_status" -eq 0 ]]; then
    pass "fixture diagram renders"
  else
    fail "fixture diagram renders"
    printf '%s\n' "$render_output"
  fi

  assert_contains "$render_output" "Found 1 diagram(s)" "reports discovered diagram"
  assert_contains "$render_output" "Rendered: fixture_graph.svg" "reports rendered SVG"

  if [[ -f "$fixture/diagrams/fixture_graph.svg" ]]; then
    pass "writes SVG output"
  else
    fail "writes SVG output"
  fi

  if [[ -f "$fixture/diagrams/fixture_graph.svg" ]] && grep -Fq "<svg" "$fixture/diagrams/fixture_graph.svg"; then
    pass "SVG output has SVG markup"
  else
    fail "SVG output has SVG markup"
  fi
else
  skip "fixture diagram renders"
  skip "reports discovered diagram"
  skip "reports rendered SVG"
  skip "writes SVG output"
  skip "SVG output has SVG markup"
  echo "    graphviz (dot) is not on PATH, so rendering was NOT verified."
  echo "    install it: apt install graphviz   # or: brew install graphviz"
fi

echo
echo "Results: $PASSES passed, $FAILURES failed, $SKIPPED skipped"

if [[ "$FAILURES" -gt 0 ]]; then
  exit 1
fi

# Distinct status: 1 means an assertion caught something, 2 means the suite could not look.
if [[ "$SKIPPED" -gt 0 ]]; then
  exit 2
fi
