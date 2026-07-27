#!/usr/bin/env bash
# Hermetic tests for the dispatch hygiene fixes:
#   - dispatch-todo persists the rendered SEED + archives the PROFILE into the child instant
#   - dispatch-todo isolates the build cache so parallel workers cannot poison a shared one
#   - install-branch-guard.sh makes pushing a shared base branch impossible (not just discouraged)
#   - ref-guard.sh gives a worktree instead of writing to a shared read-only reference checkout
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$here/.."
fail=0
ok(){ echo "  ok   - $1"; }
bad(){ echo "  FAIL - $1"; fail=1; }
chk(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (expected rc=$2, got rc=$3)"; fi; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

echo "== dispatch-todo hygiene (seed + profile archive + build isolation) =="
export POOL_DIR="$tmp/pool" BOARD_DIR="$tmp/board"
mkdir -p "$tmp/golden" "$tmp/ws1" "$tmp/base" "$tmp/prof"
# a minimal maintain-workspace-ish base instant
: > "$tmp/base/HANDOFF.md"; : > "$tmp/base/CHARTER.md"
printf 'CHARTER for {{TITLE}}\n{{BRIEF}}\n' > "$tmp/prof/charter.md"
printf 'seed for {{TITLE}} in {{WS}} -- run a | b ; c\n' > "$tmp/prof/seed.txt"
printf 'do the thing\n' > "$tmp/brief.md"
# use --no-duplicate (no golden clone needed): pre-populate the slot with a maven project
mkdir -p "$tmp/ws1/repoA"; : > "$tmp/ws1/repoA/pom.xml"
# this slot already has a POPULATED repo under a non-default name (as real slots do)
mkdir -p "$tmp/ws1/.m2-compact1/org/x"; : > "$tmp/ws1/.m2-compact1/org/x/x.jar"
bash "$S/wspool.sh" add "$tmp/ws1" >/dev/null 2>&1

out=$(bash "$S/dispatch-todo.sh" --base "$tmp/base" --profile "$tmp/prof" --title "Hygiene Probe" \
        --brief "$tmp/brief.md" --golden "$tmp/golden" --no-launch --no-duplicate 2>&1)
rc=$?
chk "dispatch --no-launch succeeds" 0 $rc
# child instants are created as SIBLINGS of the base instant (the instant model)
child=$(ls -d "$tmp"/*inflight* 2>/dev/null | head -1)
if [ -n "$child" ]; then
  [ -f "$child/.dispatch/seed.txt" ] && ok "rendered seed persisted in the child instant" \
    || bad "seed not persisted (dispatch-launch would have nothing to replay)"
  grep -q "run a | b ; c" "$child/.dispatch/seed.txt" 2>/dev/null \
    && ok "persisted seed keeps metacharacters verbatim" || bad "seed content wrong"
  [ -f "$child/.dispatch/profile/charter.md" ] && ok "profile snapshot archived into the instant" \
    || bad "profile not archived (effort becomes unreproducible once the profile is edited)"
  rec="$BOARD_DIR/records/"*.json
  grep -q '"seed_file"' $rec 2>/dev/null && ok "record carries seed_file" || bad "record has no seed_file"
  grep -q '"profile_archive"' $rec 2>/dev/null && ok "record carries profile_archive" || bad "record has no profile_archive"
  [ -f "$tmp/ws1/repoA/.mvn/maven.config" ] && ok "per-workspace build cache configured" \
    || bad "no build isolation written (shared cache can be poisoned)"
  grep -q "$tmp/ws1" "$tmp/ws1/repoA/.mvn/maven.config" 2>/dev/null \
    && ok "cache points inside this workspace" || bad "cache path not workspace-local"
  mrepo=$(sed -n 's/.*-Dmaven.repo.local=//p' "$tmp/ws1/repoA/.mvn/maven.config" | head -1)
  [ -d "$mrepo" ] && ok "the configured repo directory actually exists" \
    || bad "configured a cache directory that does not exist (cold/broken build)"
  [ "$mrepo" = "$tmp/ws1/.m2-compact1" ] && ok "reuses the slot's already-populated repo" \
    || bad "ignored the populated repo ($mrepo) — cold cache"
else
  bad "no child instant created — skipping hygiene assertions"
fi

echo "== profile-check (a profile defect must not survive a per-brief patch) =="
mkdir -p "$tmp/badprof" "$tmp/goodprof"
printf 'AC-4: Update the M1 CATALOG.md for this gap when it is green.\n' > "$tmp/badprof/charter.md"
printf 'go do the thing\n' > "$tmp/badprof/seed.txt"
bash "$S/profile-check.sh" "$tmp/badprof" >/dev/null 2>&1
chk "flags a profile telling the worker to write the canonical catalog" 1 $?
out=$(bash "$S/profile-check.sh" "$tmp/badprof" 2>&1)
echo "$out" | grep -qi "single-writer\|catalog" && ok "explains the single-writer violation" || bad "unclear message"
cat > "$tmp/goodprof/charter.md" <<'EOP'
AC-4: deliver a PROPOSED catalog delta; never edit the canonical catalog (single-writer).
AC-5: before renaming, run superpowers:review-workspace on this instant and PASS it.
AC-6: write your report to the base dispatch/ path, then rename your folder -inflight- to -complete-.
EOP
printf 'go do the thing\n' > "$tmp/goodprof/seed.txt"
bash "$S/profile-check.sh" "$tmp/goodprof" >/dev/null 2>&1
chk "a correct profile passes" 0 $?
# Worker rules must NOT be applied to a coordinator profile: the coordinator IS the catalog's
# writer, and it does not report-back to itself. Flagging a correct profile is the same
# false-alarm trap the linter exists to prevent.
mkdir -p "$tmp/coordprof"
cat > "$tmp/coordprof/charter.md" <<'EOP'
Kind: **COORDINATOR** (standing orchestrator). You do NO dev yourself.
You are the single writer of the canonical catalog; workers propose deltas and you apply them.
Gate every worker with pdispatch gate INSTANT --harvest before harvesting.
EOP
printf 'coordinate\n' > "$tmp/coordprof/seed.txt"
bash "$S/profile-check.sh" "$tmp/coordprof" >/dev/null 2>&1
chk "coordinator profile is judged by coordinator rules" 0 $?
# ...and a coordinator profile that never gates its workers IS a violation
printf 'Kind: COORDINATOR\nJust coordinate things.\n' > "$tmp/coordprof/charter.md"
bash "$S/profile-check.sh" "$tmp/coordprof" >/dev/null 2>&1
chk "coordinator profile with no gating requirement is flagged" 1 $?
# RI-7: the word "coordinator" appearing LATER in a worker's Kind line must not flip the kind.
# A kind-aware linter that silently picks the wrong kind is worse than no linter: it turns
# "unchecked" into "checked and fine".
mkdir -p "$tmp/tricky"
cat > "$tmp/tricky/charter.md" <<'EOP'
Kind: **WORKER** (one milestone). The coordinator does no dev; you do.
AC-4: Update the M1 CATALOG.md for this gap when it is green.
EOP
printf 'go\n' > "$tmp/tricky/seed.txt"
out=$(bash "$S/profile-check.sh" "$tmp/tricky" 2>&1); rc=$?
echo "$out" | grep -q "profile kind: worker" && ok "kind anchored to the declared token" \
  || bad "kind mis-detected: $(echo "$out" | head -1)"
chk "worker rules actually ran (catches the catalog violation)" 1 $rc
# an undeclared kind must default to the STRICTEST rule set, not the laxest
printf 'No kind line here at all.\nJust do the work.\n' > "$tmp/tricky/charter.md"
out=$(bash "$S/profile-check.sh" "$tmp/tricky" 2>&1)
echo "$out" | grep -q "profile kind: worker" && ok "undeclared kind defaults to worker" || bad "undeclared kind not strict"

# the SHIPPED profiles must themselves be clean
for pr in ansi ansi-expose compact-ansi coord-ansi; do
  bash "$S/profile-check.sh" "$S/profiles/$pr" >/dev/null 2>&1
  chk "shipped profile '$pr' is clean" 0 $?
done

echo "== golden inheritance (RI-3) =="
# a second dispatch for the SAME base must not fail merely because --golden was omitted
out2=$(bash "$S/dispatch-todo.sh" --base "$tmp/base" --profile "$tmp/prof" --title "Second Probe" \
        --brief "$tmp/brief.md" --no-launch --no-duplicate 2>&1); rc2=$?
chk "second dispatch inherits the golden from this effort's last dispatch" 0 $rc2
echo "$out2" | grep -qi "golden" && ok "says where the golden came from" || bad "silent about the inherited golden"

echo "== base-check (a worker must not silently build on the wrong base) =="
# The pool duplicates from the GOLDEN (prebuilt artifacts), but a milestone's work must stack on the
# LINEAGE base. Repositioning is a manual first step today; forgetting it is invisible and poisons
# the stack. Verify it mechanically instead.
bc="$tmp/bcws"; mkdir -p "$bc/repoX"
(cd "$bc/repoX" && git init -q . && git config user.email t@t && git config user.name t \
  && echo a > f && git add f && git commit -q -m one \
  && echo b >> f && git commit -q -am two) >/dev/null 2>&1
old=$(cd "$bc/repoX" && git rev-parse HEAD~1); new=$(cd "$bc/repoX" && git rev-parse HEAD)
bash "$S/base-check.sh" --ws "$bc" --expect "repoX=$new" >/dev/null 2>&1
chk "passes when the workspace is at the expected base" 0 $?
bash "$S/base-check.sh" --ws "$bc" --expect "repoX=$old" >/dev/null 2>&1
chk "FAILS when the workspace is at the wrong commit" 1 $?
out=$(bash "$S/base-check.sh" --ws "$bc" --expect "repoX=$old" 2>&1)
echo "$out" | grep -q "repoX" && echo "$out" | grep -qi "expect" && ok "names the repo and both shas" \
  || bad "unclear mismatch report"
bash "$S/base-check.sh" --ws "$bc" --expect "nosuch=$new" >/dev/null 2>&1
chk "missing repo in the workspace is a failure" 1 $?
# a short sha prefix should still match
bash "$S/base-check.sh" --ws "$bc" --expect "repoX=${new:0:9}" >/dev/null 2>&1
chk "accepts an abbreviated sha" 0 $?
# and it should read the expectation straight from a dispatch record
mkdir -p "$BOARD_DIR/records"
cat > "$BOARD_DIR/records/bcprobe.json" <<EOF
{ "todo_id": "bcprobe", "ws": "$bc", "child_instant": "$tmp/x", "tmux": "dt-bcprobe",
  "base_instant": "$tmp/base", "lineage_base": "repoX=$new" }
EOF
bash "$S/base-check.sh" bcprobe >/dev/null 2>&1
chk "reads the expected base from the dispatch record" 0 $?

echo "== install-branch-guard =="
r="$tmp/repo"; mkdir -p "$r"; (cd "$r" && git init -q . && git config user.email t@t && git config user.name t \
  && git commit -q --allow-empty -m init) >/dev/null 2>&1
bash "$S/install-branch-guard.sh" "$r" shared-base >/dev/null 2>&1; chk "installs the hook" 0 $?
[ -x "$r/.git/hooks/pre-push" ] && ok "pre-push hook is executable" || bad "hook missing/not executable"
# simulate the hook's decision: pushing the protected branch must be refused
out=$(cd "$r" && echo "refs/heads/shared-base abc refs/heads/shared-base def" | ./.git/hooks/pre-push origin /dev/null 2>&1); rc=$?
chk "refuses a push to the protected shared branch" 1 $rc
out=$(cd "$r" && echo "refs/heads/mr-1 abc refs/heads/mr-1 def" | ./.git/hooks/pre-push origin /dev/null 2>&1); rc=$?
chk "allows a push to the worker's own branch" 0 $rc
bash "$S/install-branch-guard.sh" "$r" shared-base >/dev/null 2>&1; chk "re-install is idempotent" 0 $?

echo "== ref-guard =="
ref="$tmp/ref"; mkdir -p "$ref"; (cd "$ref" && git init -q . && git config user.email t@t && git config user.name t \
  && echo x > f && git add f && git commit -q -m init) >/dev/null 2>&1
bash "$S/ref-guard.sh" check "$ref" >/dev/null 2>&1; chk "check warns while the reference is writable" 1 $?
bash "$S/ref-guard.sh" worktree "$ref" "$tmp/wt" >/dev/null 2>&1; chk "creates a writable worktree" 0 $?
[ -e "$tmp/wt/f" ] && ok "worktree has the content" || bad "worktree empty"
bash "$S/ref-guard.sh" protect "$ref" >/dev/null 2>&1; chk "protect makes it read-only" 0 $?
bash "$S/ref-guard.sh" check "$ref" >/dev/null 2>&1; chk "check passes once protected" 0 $?
chmod -R u+w "$ref" 2>/dev/null || true

if [ $fail = 0 ]; then echo "PASS"; else echo "FAIL"; fi
exit $fail
