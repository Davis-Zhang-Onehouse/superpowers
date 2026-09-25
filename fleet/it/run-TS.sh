#!/usr/bin/env bash
# §TS — V23-P (FB-126): a REAL claude dispatched into a folder Claude Code does not trust stops at the folder-trust
# screen, and the dispatch must SAY so instead of printing a plain success.
#
# Measured on 2026-09-25: the first Claude dispatch into ws10 (and later ws8) opened on "Is this a project you created or
# one you trust?". `dispatch` exited 0 with nothing about it, because it verifies the seed by the worker's ARGV, and the
# argv is right while the pane waits on a human.
#
# The runner owns everything the real binary reads:
#  - a SCRATCH config root outside any git checkout ($TS_ROOT, mktemp under the parent `ts_scratch_parent` chooses).
#    The owners map sends both fixture slots to $TS_ROOT/.claude, whose .claude.json this runner writes:
#    onboarding done, and ONE trust record (the control slot). The operator's Claude config is never read or written, and nothing here answers the trust screen;
#  - a private tmux server (`it_section`) and a private store.
# The worker is never logged in, so no model is called: the trusted control reaches the prompt and prints "Not logged
# in", and the untrusted case never gets past the screen.
#
#   TS1a  control of the SETUP: the untrusted slot's pane really shows the trust screen (true at base and at the fix)
#   TS1b  the dispatch output carries `trust_screen observed`, and the path it names is the leased slot
#   TS1c  the pre-flight prediction row reads `untrusted` before the launch
#   TS2a  control: the trusted slot's pane reaches the prompt, and the dispatch reports no trust screen
#   TS2b  the pre-flight prediction row reads `trusted` for it
#
# Run: bash fleet/it/run-TS.sh      Budget: two real claude launches, ~40s, no model tokens.
IT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$IT_ROOT/lib.sh"

IT_FAILED=0
it_own_cases 'TS[0-9]+[a-z]?|ISOLATION-TS-(enter|leave)'

REAL_CLAUDE="${P_REAL_CLAUDE:-/home/ubuntu/.local/bin/claude}"
TS_WAIT="${TS_WAIT:-25}"

#: Final review M4. The control must stay logged out, so no model is ever called: no ambient credential reaches claude.
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN CLAUDE_CODE_OAUTH_TOKEN
it_section TS
it_fresh_store
OUT="$EV/out"; rm -rf "$OUT"; mkdir -p "$OUT"
export FLEET_INSTANTS="$EV/instants"; rm -rf "$FLEET_INSTANTS"; mkdir -p "$FLEET_INSTANTS"

if [ ! -x "$REAL_CLAUDE" ]; then
  it_skip TS1a "" "no real claude at $REAL_CLAUDE, so the trust screen cannot be produced"
  it_assert_isolation TS-leave
  echo "§TS skipped"; exit 0
fi

#: RV-33. The scratch parent must sit under NO `.git` entry. fleet's trust walk and Claude 2.1.282's root finder both
#: treat any `.git` (a dir or a file, even an empty one) on a directory or an ancestor as a git root, so a stray
#: `/tmp/.git` made both predictions UNKNOWN and failed TS1c/TS2b on the environment, not the product.
#: `ts_scratch_parent <candidate>...` prints the first candidate that exists, has no `.git` entry on itself or any
#: ancestor, and that `git -C` does not place in a work tree; else lists each rejected candidate and returns 1.
ts_scratch_parent() {
  local cand d rejected=""
  for cand in "$@"; do
    [ -n "$cand" ] || continue
    d="$(cd "$cand" 2>/dev/null && pwd -P)" || { rejected="$rejected $cand (missing);"; continue; }
    local hit
    hit="$(it_no_dot_git_above "$d")" || { rejected="$rejected $cand ($hit);"; continue; }   # RV-35: shared with lib.sh
    if env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR -u GIT_CEILING_DIRECTORIES \
         git -C "$d" rev-parse --show-toplevel >/dev/null 2>&1; then
      rejected="$rejected $cand (inside a git work tree);"; continue
    fi
    printf '%s\n' "$d"; return 0
  done
  printf '%s\n' "${rejected# }"
  return 1
}
if ! TS_PARENT="$(ts_scratch_parent "${TS_TMP_PARENT:-}" /tmp /var/tmp)"; then
  it_skip TS1a "" "SETUP: every candidate scratch parent sits under a .git entry ($TS_PARENT)"
  it_assert_isolation TS-leave
  echo "§TS skipped"; exit 0
fi
TS_ROOT="$(mktemp -d "$TS_PARENT/fleet-it-ts.XXXXXX")" || exit 2
TODOS=()
cleanup_TS() {
  for todo in "${TODOS[@]}"; do
    fleet close --id "$todo" --force --porcelain >> "$OUT/teardown.out" 2>&1
    fleet harvest --id "$todo" --porcelain >> "$OUT/teardown.out" 2>&1
  done
  it_cleanup_tmux
  it_tmux kill-server 2>/dev/null
  case "$TS_ROOT" in "$TS_PARENT"/fleet-it-ts.*) rm -rf "$TS_ROOT" ;; esac
}
trap cleanup_TS EXIT

# ---- the scratch config and the two slots, all outside any git checkout -----------------------------
git -C "$TS_ROOT" rev-parse --show-toplevel >/dev/null 2>&1 && { echo "§TS: $TS_ROOT is inside a git checkout" >&2; exit 2; }
UNTRUSTED="$TS_ROOT/untrusted-slot"; TRUSTED="$TS_ROOT/trusted-slot"
mkdir -p "$UNTRUSTED" "$TRUSTED" "$TS_ROOT/.claude"
python3 - "$TS_ROOT/.claude/.claude.json" "$TRUSTED" <<'PY'
import json, sys
json.dump({"hasCompletedOnboarding": True, "numStartups": 5,
           "projects": {sys.argv[2]: {"hasTrustDialogAccepted": True}}}, open(sys.argv[1], "w"))
PY
export CLAUDE_OWNERS_MAP="$EV/claude-owners.tsv"
printf '%s\t%s\n' "$TS_ROOT" 'integration-test' > "$CLAUDE_OWNERS_MAP"
export FLEET_CLAUDE_BIN="$REAL_CLAUDE"
echo "root: $TS_ROOT" > "$OUT/setup.txt"

PROFILE="$OUT/profile"; mkdir -p "$PROFILE"
printf '{"kind":"worker","placeholders":["TITLE","BASE"],"requires_clauses":[],"invocation_templates":[]}\n' > "$PROFILE/profile.json"
printf '# CHARTER — {{TITLE}}\nBase {{BASE}}. Instant {{PATH}}. A trust-screen fixture.\n' > "$PROFILE/charter.md"
printf 'You are a TEST FIXTURE (instant {{PATH}}, milestone {{MILESTONE}}, coordinator {{COORDINATOR}}). Do nothing.\n' > "$PROFILE/seed.txt"

COORD="$(fleet init --base 00000000 --name tsCoord --porcelain | awk -F'\t' '$1=="path"{print $2}')"
fleet milestone --instant "$COORD" --id t1 --title "untrusted" > "$OUT/setup.out" 2>&1
fleet milestone --instant "$COORD" --id t2 --title "trusted" >> "$OUT/setup.out" 2>&1
fleet set-golden --path "$UNTRUSTED" >> "$OUT/setup.out" 2>&1
fleet enroll --slot "$UNTRUSTED" >> "$OUT/setup.out" 2>&1
fleet enroll --slot "$TRUSTED" >> "$OUT/setup.out" 2>&1

ts_dispatch() {       # ts_dispatch <case> <title> <milestone> <slot name> -> $OUT/<case>-dispatch.out; sets TMUXN
  fleet dispatch --profile "$PROFILE" --title "$2" --base 00000000 --optype append --from "$COORD" \
        --milestone "$3" --slot "$4" --cap 5 --porcelain > "$OUT/$1-dispatch.out" 2>"$OUT/$1-dispatch.err"
  echo $? > "$OUT/$1-dispatch.rc"
  TMUXN="$(awk -F'\t' '$1=="tmux"{print $2}' "$OUT/$1-dispatch.out")"
  local todo; todo="$(awk -F'\t' '$1=="todo_id"{print $2}' "$OUT/$1-dispatch.out")"
  [ -n "$todo" ] && TODOS+=("$todo")
}
ts_wait_frame() {     # ts_wait_frame <session> <regex> <out> -> 0 once the pane shows the regex within TS_WAIT
  local deadline=$(( $(date +%s) + TS_WAIT ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    it_tmux capture-pane -p -t "$1" > "$3" 2>&1
    grep -Eq "$2" "$3" && return 0
    sleep 1
  done
  return 1
}
row() { awk -F'\t' -v k="$1" '$1==k{print $2; exit}' "$2"; }

# ---- TS1: the untrusted slot -------------------------------------------------------------------------
ts_dispatch TS1 tsUntrusted t1 untrusted-slot
if ts_wait_frame "$TMUXN" 'one you trust' "$OUT/TS1-pane.txt"; then
  it_pass TS1a "fleet/it/TS/out/TS1-pane.txt" "the untrusted slot's real claude shows the folder-trust screen (setup control): dispatch rc=$(cat "$OUT/TS1-dispatch.rc")"
else
  it_fail TS1a "fleet/it/TS/out/TS1-pane.txt" "SETUP, not a verdict: no trust screen within ${TS_WAIT}s (dispatch rc=$(cat "$OUT/TS1-dispatch.rc"))"
fi
screen="$(row trust_screen "$OUT/TS1-dispatch.out")"; spath="$(row trust_screen_path "$OUT/TS1-dispatch.out")"
if [ "$(cat "$OUT/TS1-dispatch.rc")" = 0 ] && [ "${screen%% *}" = observed ] && [ "$spath" = "$UNTRUSTED" ]; then
  it_pass TS1b "fleet/it/TS/out/TS1-dispatch.out" "dispatch exited 0 and REPORTED the trust screen (trust_screen='$screen') naming the leased slot as the path on screen"
else
  it_fail TS1b "fleet/it/TS/out/TS1-dispatch.out" "dispatch did not report the trust screen its own pane shows: rc=$(cat "$OUT/TS1-dispatch.rc") trust_screen='$screen' trust_screen_path='$spath' (want observed / $UNTRUSTED)"
fi
pred="$(row trust "$OUT/TS1-dispatch.out")"
if [ "${pred%% *}" = untrusted ]; then
  it_pass TS1c "fleet/it/TS/out/TS1-dispatch.out" "the pre-flight prediction read the scratch config and said untrusted: '$pred'"
else
  it_fail TS1c "fleet/it/TS/out/TS1-dispatch.out" "no untrusted prediction before the launch: trust='$pred'"
fi

# ---- TS2: the control, a slot the scratch config trusts ----------------------------------------------
ts_dispatch TS2 tsTrusted t2 trusted-slot
if ts_wait_frame "$TMUXN" 'Not logged in|auto mode' "$OUT/TS2-pane.txt" && ! grep -q 'one you trust' "$OUT/TS2-pane.txt" \
   && [ "$(cat "$OUT/TS2-dispatch.rc")" = 0 ] && [ "$(row trust_screen "$OUT/TS2-dispatch.out" | cut -d' ' -f1)" = none ]; then
  it_pass TS2a "fleet/it/TS/out/TS2-pane.txt" "control: the trusted slot's claude reached its prompt with no trust screen, and dispatch reported none (trust_screen='$(row trust_screen "$OUT/TS2-dispatch.out")')"
else
  it_fail TS2a "fleet/it/TS/out/TS2-pane.txt" "control broken: rc=$(cat "$OUT/TS2-dispatch.rc") trust_screen='$(row trust_screen "$OUT/TS2-dispatch.out")'"
fi
pred="$(row trust "$OUT/TS2-dispatch.out")"
if [ "${pred%% *}" = trusted ]; then
  it_pass TS2b "fleet/it/TS/out/TS2-dispatch.out" "the prediction named the scratch trust record: '$pred'"
else
  it_fail TS2b "fleet/it/TS/out/TS2-dispatch.out" "no trusted prediction for the trusted slot: trust='$pred'"
fi

cleanup_TS; trap - EXIT
it_assert_isolation TS-leave
echo "§TS done: IT_FAILED=$IT_FAILED"; exit "$IT_FAILED"
