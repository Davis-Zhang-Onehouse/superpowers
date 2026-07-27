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
else
  bad "no child instant created — skipping hygiene assertions"
fi

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
